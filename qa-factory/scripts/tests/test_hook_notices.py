#!/usr/bin/env python3
"""RH1-5 B6: the ONE catcher of a hook's advice (`hooklib.notice` / `take_notices`) and of a signal to the person
(`person_signal`, the journal event `hook_signal`). K7 (stdout at exit 0 is exactly one JSON object or empty), E18-E20, E22,
the shape of the journal line, a failed write never raises."""
import contextlib
import io
import json
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import SCRIPTS, check, check_eq, check_in, check_not_in, cleanup, finish, temp_project, use_project  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import hooklib  # noqa: E402
import runtime_paths as RP  # noqa: E402

def said(fn) -> tuple:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        result = fn()
    return result, out.getvalue(), err.getvalue()


def journal_rows(root: Path) -> list:
    path = RP.record(root, "journal.jsonl")
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.is_file() else []


def main() -> None:
    root = temp_project("qa-notices-")
    try:
        use_project(root)
        ev = {"hook_event_name": "PreToolUse", "session_id": "sess-a", "cwd": str(root), "tool_name": "Bash"}
        # K7: one JSON object, no verdict in it, several texts glued by a newline (E19)
        hooklib.notice(ev, "first", reader="role")
        hooklib.notice(ev, "second", reader="orchestrator")
        _r, out, err = said(lambda: hooklib.take_notices(ev, 0))
        objects = [json.loads(line) for line in out.splitlines() if line.strip()]
        check_eq("K7: exactly one JSON object on stdout", len(objects), 1)
        body = objects[0]["hookSpecificOutput"]
        check_eq("K7: additionalContext carries both texts joined by a newline", body["additionalContext"], "first\nsecond")
        check_not_in("K7: and the object has no permissionDecision", "permissionDecision", out)
        check_eq("K7: nothing on stderr", err, "")
        check_eq("the queue is empty afterwards: a second take says nothing", said(lambda: hooklib.take_notices(ev, 0))[1:], ("", ""))
        # E22: empty
        hooklib.notice(ev, "", reader="role")
        hooklib.notice(ev, "   ", reader="role")
        check_eq("E22: an empty notice says nothing", said(lambda: hooklib.take_notices(ev, 0))[1:], ("", ""))
        check_eq("E22: an empty person_signal writes nothing", hooklib.person_signal(ev, "x", ""), False)
        # exit 2: stderr, after the refusal, marked
        hooklib.notice(ev, "late advice", reader="role")
        _r, out, err = said(lambda: hooklib.take_notices(ev, 2))
        check_eq("exit 2: stdout stays empty", out, "")
        check_in("exit 2: stderr carries it, marked as not part of the refusal", "(Not part of the refusal above.) late advice", err)
        # E18: a hook without a model reader, and a `person` notice, become signals
        stop = dict(ev, hook_event_name="SubagentStop")
        hooklib.notice(stop, "for a role on a stop hook", reader="role")
        hooklib.notice(ev, "for the person", reader="person")
        _r, out, err = said(lambda: hooklib.take_notices(stop, 0))
        rows = journal_rows(root)
        check_eq("E18: nothing printed to the silent channel", (out, err), ("", ""))
        check_eq("E18: both became hook_signal lines", [r["event"] for r in rows[-2:]], ["hook_signal", "hook_signal"])
        check_eq("E18: ...of kind notice, with the text in notes", sorted(r["notes"] for r in rows[-2:]),
                 ["for a role on a stop hook", "for the person"])
        # the line's shape
        row = rows[-1]
        check_eq("the line has ts, event, agent, kind, task, session, notes",
                 sorted(row), ["agent", "event", "kind", "notes", "session", "task", "ts"])
        check("the ts has no timezone suffix problem for the validator: ISO with an offset", re.match(r"\d{4}-\d\d-\d\dT", row["ts"]) is not None, row["ts"])
        check_eq("session is the event's", row["session"], "sess-a")
        # E20: once per session
        for key_event, label in ((ev, "with a session id"), (dict(ev, session_id=""), "without one")):
            hooklib.notice(key_event, "once-text", reader="role", once_key=f"k-{label}-{root.name}")
            hooklib.notice(key_event, "once-text", reader="role", once_key=f"k-{label}-{root.name}")
            _r, out, _e = said(lambda: hooklib.take_notices(key_event, 0))
            n = out.count("once-text")
            check_eq(f"E20: {label}: said {'once' if key_event.get('session_id') else 'every time'}", n,
                     1 if key_event.get("session_id") else 2)
        hooklib.notice(dict(ev, session_id=""), "twice", reader="role", once_key="nokey")
        hooklib.notice(dict(ev, session_id=""), "twice", reader="role", once_key="nokey")
        check_eq("E20: no session id: every time (two queued)", len(hooklib._NOTICES), 2)
        hooklib._NOTICES[:] = []
        # person_signal once_key
        before = len(journal_rows(root))
        hooklib.person_signal(ev, "config", "same", once_key="sig-" + root.name)
        hooklib.person_signal(ev, "config", "same", once_key="sig-" + root.name)
        check_eq("a person_signal with a once_key lands once per session", len(journal_rows(root)) - before, 1)
        # E16: a failed write never raises; the last resort is stderr
        (root / "qa-factory" / "config.json").write_text(json.dumps({"journal_path": "blocker/inner/journal.jsonl"}), encoding="utf-8")
        (root / "blocker").write_text("a file where a folder is needed", encoding="utf-8")
        landed, _o, err = said(lambda: hooklib.person_signal(ev, "guard_crashed", "Bash: ValueError: x"))
        check_eq("E16: a journal that cannot be written: False, no exception", landed, False)
        check_in("E16: the last resort names the kind and the text on stderr", "guard_crashed: Bash: ValueError: x", err)
        (root / "qa-factory" / "config.json").write_text("{}", encoding="utf-8")
        # t-1459 (E16, the last resort): in a project without the factory marker the signal never creates `qa-factory/`;
        # it goes to stderr. Killing: person_signal creating the journal folder under a project_root() fallback.
        bare = Path(tempfile.mkdtemp(prefix="qa-notices-bare-"))
        try:
            use_project(bare)
            landed, _o, err = said(lambda: hooklib.person_signal({"session_id": "s-bare", "cwd": str(bare)}, "inject", "no marker here"))
            check_eq("no marker: the signal did not land in a journal", landed, False)
            check_eq("no marker: no qa-factory folder was created", (bare / "qa-factory").exists(), False)
            check_in("no marker: the last resort names the kind and the text on stderr", "inject: no marker here", err)
            use_project(root)
            check_eq("no marker control: an onboarded project still lands its signal",
                     hooklib.person_signal(ev, "inject", "marker present"), True)
        finally:
            use_project(root)
            cleanup(bare)
    finally:
        cleanup(root)

    check("the temp dir is cleaned", not Path(tempfile.gettempdir(), root.name).exists())
    finish("test_hook_notices")


if __name__ == "__main__":
    main()
