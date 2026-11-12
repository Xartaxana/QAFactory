"""Run one hook unchanged while recording a sanitized, fail-silent duration span."""
import hashlib, io, json, os, runpy, sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parent))
from hooklib import project_root
from telemetry_capture import Span


def _write_pretool_receipt(root, event, raw=""):
    """A command a role runs from a shell (activity_capture.py, host_probe.py, onboard_apply.py)
    is not told which session it belongs to. The PreToolUse hook that fires moments before that very
    call carries both the session id and the command, so it leaves a receipt for session_identity.resolve
    to read: one file per session and script, never one per call, and none for a command that names no
    reader script (the text of other commands is not stored). It runs whether or not the project is
    onboarded: before config.json exists the receipt goes to the spool under the user's home, because
    a hook never creates `qa-factory/` (session_identity.write_receipt).

    `raw` is the event's own text, as it arrived: the cheap filter that lets every other command pass
    without reading it through host_probe. Fail-silent, as everything on this path."""
    try:
        import session_identity
        rules = session_identity.load_rules()
        if rules and any(name in (raw or json.dumps(event)) for name in rules["receipt_scripts"]):
            session_identity.write_receipt(root, event, rules=rules)
    except Exception:
        pass


def _plugin_version(plugin_root):
    """The version this copy's own manifest names ("" when none is readable): the same three
    manifests `story_version.installed_version` reads, of THIS copy rather than of the story."""
    for manifest in (".claude-plugin", ".codex-plugin", ".plugin"):
        try:
            data = json.loads((plugin_root / manifest / "plugin.json").read_text(encoding="utf-8"))
            version = str(data.get("version") or "").split("+", 1)[0].strip()
            if version:
                return version
        except Exception:
            continue
    return ""


def _write_package_receipt(root, event, hook_name):
    """B-014: which copy of the package the hooks of this session ran from.

    A project that enables one installed copy of the package while the driver loads another
    (`--plugin-dir`) can run the guards of one generation under a role of the other; nothing
    recorded which generation a session's hooks came from, so nothing could tell. This hook is
    the one thing every hook command of the package already goes through, and `__file__` here is
    the copy that is running - so it says so, once per session and root, in a receipt of its own
    (`package-<hash of session>.json`, beside the pretool one). The driver reads it after the
    session and compares the roots with its own. Roots accumulate: two different roots in one
    session are exactly what it is looking for. No fingerprint: the root and its manifest's
    version are what a person can be told. Fail-silent, as everything on this path: a hook that
    cannot write a receipt still has its own job to do."""
    session_id = str(event.get("session_id") or "").strip()
    if not session_id:
        return
    try:
        plugin_root = Path(__file__).resolve().parent.parent
        receipt_dir = root / "qa-factory" / "state" / "host-receipts"
        path = receipt_dir / f"package-{hashlib.sha256(session_id.encode('utf-8')).hexdigest()[:16]}.json"
        mine = str(plugin_root)
        entry = {"plugin_root": mine, "version": _plugin_version(plugin_root),
                 "first_hook": f"{event.get('hook_event_name') or 'hook'}:{hook_name}"}
        # Parallel hooks of one session read-modify-write the same file, and the second write can
        # drop the first one's root: the file is read back, and written again while this root is missing.
        for _ in range(3):
            try:
                current = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                current = {}
            roots = [r for r in (current.get("roots") if isinstance(current, dict) else None) or []
                     if isinstance(r, dict)]
            if any(r.get("plugin_root") == mine for r in roots):
                return
            roots.append(entry)
            receipt_dir.mkdir(parents=True, exist_ok=True)
            tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
            tmp.write_text(json.dumps({"session_id": session_id, "roots": roots,
                                       "observed_at": datetime.now(timezone.utc).isoformat()}), encoding="utf-8")
            os.replace(tmp, path)
    except Exception:
        pass


def main():
    if len(sys.argv)<2: return 1
    requested=Path(sys.argv[1])
    target=requested.resolve() if requested.is_absolute() else Path(__file__).resolve().parent / requested.name
    payload=sys.stdin.buffer.read()
    try: event=json.loads(payload.decode("utf-8")) if payload else {}
    except Exception: event={}
    root=project_root(event)
    enabled=(root/"qa-factory/config.json").is_file()
    if event.get("hook_event_name") == "PreToolUse":
        _write_pretool_receipt(root, event, payload.decode("utf-8", "replace"))
    if enabled:
        _write_package_receipt(root, event, target.name)
    ids={"session_id":str(event.get("session_id") or "") or None,
         "task":str(event.get("task") or event.get("task_id") or "") or None,
         "dispatch_id":str(event.get("dispatch_id") or event.get("agent_id") or "") or None,
         "tool_call_id":str(event.get("tool_use_id") or event.get("tool_call_id") or "") or None,
         "reason_code":str(event.get("hook_event_name") or os.environ.get("CLAUDE_HOOK_EVENT") or "hook")}
    path=root/"qa-factory/state/telemetry"/(f"hook-{os.getpid()}.jsonl")
    if enabled:
        try:
            from hooklib import load_config, rotate_telemetry
            rotate_telemetry(path.parent, load_config(event), keep_paths=(path,))
        except Exception:
            pass  # rotation is disposable housekeeping - never worth blocking the hook it rides on
    span=Span(path,span_kind="hook",source="plugin:"+target.name,**ids) if enabled else None
    if span:
        try: span.__enter__()
        except Exception: span=None
    old_argv,old_stdin,old_stdout=sys.argv,sys.stdin,sys.stdout
    from host_adapter import is_codex, context_output
    capture = io.StringIO() if is_codex(event) else None
    code=0
    target_done=False
    try:
        sys.argv=[str(target),*old_argv[2:]]
        sys.stdin=io.TextIOWrapper(io.BytesIO(payload),encoding="utf-8",errors="replace")
        if capture is not None:
            sys.stdout=capture
        try: runpy.run_path(str(target),run_name="__main__")
        except SystemExit as exc:
            if exc.code is None or isinstance(exc.code, int): code=exc.code or 0
            else:
                print(exc.code, file=sys.stderr)
                code=1
        target_done=True
        if capture is not None:
            sys.stdout=old_stdout
            output=capture.getvalue().strip()
            if output:
                try:
                    parsed=json.loads(output)
                except ValueError:
                    context_output(event, output)
                else:
                    print(json.dumps(parsed, ensure_ascii=False))
        if span:
            try: span.finish("ok" if code==0 else "error",ids["reason_code"])
            except Exception: pass
        if enabled:
            try:
                from host_probe import observe, note_guard_parse
                observe(root, event, target.name, code)
                note_guard_parse(root, event, target.name, code)
                from host_capabilities import record
                record(root, event, target.name, code)
                if target.name == 'exit_gate.py' and code == 0 and event.get('hook_event_name') == 'SubagentStop':
                    from host_dispatch import record as record_dispatch
                    from host_adapter import normalize
                    from host_dispatch import enrich
                    record_dispatch(dict(enrich(normalize(event)), _exit_gate_released=True))
            except (OSError, ValueError):
                pass
        return code
    except BaseException as exc:
        if span:
            try: span.finish("error",type(exc).__name__)
            except Exception: pass
        if enabled and not target_done:
            # A guard that RAISED left no exit code on the normal path, so the probe saw no fact at all: ALLOW without its
            # `allow_guard` is the set the 14857 report shows (FB-6, hypothesis H3). Exit 1 is what the host sees, and
            # that is what is recorded; a failure of the recorders after the target finished is not the target's failure.
            try:
                from host_probe import observe, note_guard_parse
                observe(root, event, target.name, 1)
                note_guard_parse(root, event, target.name, 1)
            except Exception:
                pass
        raise  # target ran exactly once; preserve its failure instead of retrying an external action
    finally:
        sys.argv,sys.stdin,sys.stdout=old_argv,old_stdin,old_stdout

if __name__=="__main__": raise SystemExit(main())
