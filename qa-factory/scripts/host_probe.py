"""Prepare harmless host-origin allow/deny probes; inspect receipts without simulating hooks.

Run --prepare, execute each returned command as a separate native shell tool call,
then run --check. A synthetic script test is never a live host probe.
"""
import argparse
import contextlib
import hashlib
import json
import re
import secrets
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
import release_fingerprint
from event_store import EventStore, StateConflict, atomic_json

# How long a writer of the probe store (or of a guard-parse receipt) waits for another writer before it gives up. Two hooks of
# one host message run in parallel and each used to read the whole store, wait for the package walk and write it back, so the
# later write erased the earlier one (FB-6, hypothesis H1). A hook that waits stalls the host's own tool call, so the wait is
# short; what it cannot wait out is reported by the caller as "not recorded", never as a changed decision of the guard (E1).
STORE_LOCK_WAIT_S = 5
# How many rows from the top of a child's transcript `check_role_context` reads, at most: the delivered context is the
# opening of the child's own input, so a heading met later is something the child quoted or read, not what it was handed (E17).
ROLE_CONTEXT_ROWS = 20
CHALLENGE_PREFIX = 'QA_CONTEXT_RECEIVED_'
RETURNED_LIMIT = 120  # what a mismatch keeps of the child's answer: the store stays small
# The two forms any build of injection_marker ever wrote (32 hex now, 48 before). A stored challenge of
# any other shape is not judged at all: an unknown never passes (FR-59).
_CHALLENGE_FORM = re.compile(r'(?:[0-9a-f]{32}|[0-9a-f]{48})')
_IDENTIFIER_RUN = re.compile(r'[0-9A-Za-z_]*')
# The rows of a child transcript that are a tool call: Codex `response_item` payload types (the Claude form
# is a `tool_use` block inside an assistant row).
_TOOL_ROWS = frozenset({'function_call', 'custom_tool_call', 'local_shell_call'})
TOOL_DETAIL = ('the probe child used a tool; it must answer from its context alone - '
               're-probe under a new task name')


def _unknown(why):
    """The fingerprint of bytes that could not be read: `unknown:<why>:<nonce>`. The nonce is fresh on every call, so
    it equals no stored value and no second call of itself - an unread tree never matches a probe (FR-41, FR-59)."""
    return f"unknown:{why}:{secrets.token_hex(8)}"


def fingerprint(root):
    """What the probe is bound to: the package's bytes (the ONE recipe, `release_fingerprint.package_fingerprint`, called through
    the module attribute - AR-15) and the project's own `qa-factory/config.json` (b'' when absent: the probe's project binding).
    The hooks/hooks.json and the scripts the old walk named are inside the recipe. A file that cannot be read gives
    `unknown:package_unreadable:<nonce>` or `unknown:config_unreadable:<nonce>`; this never raises."""
    package = Path(__file__).resolve().parents[1]
    try:
        aggregate = release_fingerprint.package_fingerprint(package)
    except Exception:  # noqa: BLE001 - an OSError, a loop in the walk: no claim is made on bytes that were not read
        return _unknown("package_unreadable")
    config = Path(root) / "qa-factory/config.json"
    try:
        project = config.read_bytes() if config.is_file() else b""
    except Exception:  # noqa: BLE001 - as above
        return _unknown("config_unreadable")
    return hashlib.sha256(aggregate.encode("ascii") + b"\n" + project).hexdigest()


def _read_dict(path):
    """The JSON object in `path`, or None when it is absent, unreadable, not JSON or not an object: `hooklib.read_json` (AR-13,
    the one reader) with one retry around it. On Windows a reader that meets another process's `os.replace` is refused with a
    PermissionError for a moment, and a store read as lost for that moment would drop a fact (an estimate, not measured), so
    that error is retried once, here, and any other OSError is "nothing there". Never raises."""
    from hooklib import read_json
    for attempt in (0, 1):
        try:
            return read_json(path, None, errors=(FileNotFoundError, IsADirectoryError, ValueError), kind=dict)
        except PermissionError:
            if attempt:
                return None
            time.sleep(0.05)
        except OSError:
            return None
    return None


@contextlib.contextmanager
def _store_lock(root, name):
    """The writer lock of one receipt family, kept under `qa-factory/state/<name>/` (not under `host-receipts/**`: that
    path is carried to another machine by install-paths.json). Raises StateConflict when the lock stays busy for
    STORE_LOCK_WAIT_S; the caller decides what that means for itself (E1)."""
    with EventStore(Path(root) / "qa-factory/state" / name).lock(wait_seconds=STORE_LOCK_WAIT_S):
        yield


def _store_update(root, change):
    """The ONE writer of `host-probe.json` (AR-14). Under the lock: read the store, call `change(current)` - `current` is
    the stored object or None when it cannot be read as one - and write what `change` returns as `(new, result)`
    (`new` None writes nothing). Everything slow (the package walk, a transcript) is done by the caller BEFORE this: the
    lock holds a read, a comparison and a write. Raises StateConflict when the lock stays busy."""
    path = Path(root) / "qa-factory/state/host-probe.json"
    with _store_lock(root, "host-probe-lock"):
        new, result = change(_read_dict(path))
        if new is not None:
            atomic_json(path, new)
        return result


def prepare(root, session):
    if not session:
        raise ValueError("real host session identity is required")
    nonce = secrets.token_hex(16)
    data = {"nonce": nonce, "session_id": session, "fingerprint": fingerprint(root),
            "created_at": datetime.now(timezone.utc).isoformat(), "checks": {},
            "commands": [f"echo QA_FACTORY_PROBE_{kind}_{nonce}" for kind in ("ALLOW", "DENY")]}
    _store_update(root, lambda _current: (data, None))   # a new store replaces whatever stood, readable or not
    return data


def probe_command(event):
    """The shell command the guard checks for an event, or '' when it checks none that can be read (FR-17).

    The guard reads the NORMALIZED event: `host_adapter.normalize` joins every command field, reads an argv
    list as its elements joined by a space, and turns the one literal `exec_command` of a Desktop code cell
    into a `Bash` call whose `command` is the inner command. The probe reads that same text: an event that
    carries the transport record `normalize` leaves is read as it is, a raw event (the telemetry wrapper's)
    goes through `normalize` first. The transport's own `input` is never read, so a normalizer that loses
    the echo loses it for the guard and for the probe alike - the safe side - and a transport a caller sent
    never makes a receipt. `command`, else `cmd`, else ''; any other shape, and any exception, is ''."""
    try:
        if not (isinstance(event, dict) and isinstance(event.get("_qa_host"), dict)):
            from host_adapter import normalize
            event = normalize(event)
        if (event.get("_qa_host") or {}).get("refusal"):
            return ""  # refused by normalize: the guard's command checks never read this event (I5, edge 19)
        ti = event.get("tool_input")
        for key in ("command", "cmd"):
            if isinstance(ti, dict) and isinstance(ti.get(key), str) and ti[key]:
                return ti[key]
    except Exception:  # noqa: BLE001 - an unreadable event is no probe; never an exception in a hook wrapper (E8)
        pass
    return ""


def observe(root, event, script=None, code=None):
    # Called from the hook wrapper's one try block, ahead of two other recorders: an odd raw
    # event shape must come back as "nothing observed", never as an exception that skips them.
    if not isinstance(event, dict):
        return False
    path = Path(root) / "qa-factory/state/host-probe.json"
    if not path.is_file():
        return False
    # An unreadable store or one of another shape is "nothing observed", never an exception: on the guard's path an
    # exception is exit 1, which on Claude Code is not a block (E5).
    data = _read_dict(path)
    if data is None:
        return False
    # The cheap checks first (AR-12): this runs on every tool event while the store exists, and the fingerprint walks the whole
    # package. An event that is not another session's, and whose command is not a probe echo at all, ends here - it could never
    # have matched. The fingerprint is still judged before the DENY block and before any receipt (the invariant of this order).
    if data.get("session_id") != event.get("session_id"):
        return False
    command = probe_command(event)
    if not command.strip().startswith("echo QA_FACTORY_PROBE_"):
        return False
    if data.get("fingerprint") != fingerprint(root):
        return False
    nonce = data.get("nonce")
    if not isinstance(nonce, str) or not nonce:
        return False
    match = re.fullmatch(r"echo QA_FACTORY_PROBE_(ALLOW|DENY)_" + re.escape(nonce), command.strip())
    if not match:
        return False
    kind, phase = match[1], event.get("hook_event_name")
    if script is None and phase == "PreToolUse" and kind == "DENY":
        # The normal guard blocks only this harmless nonce-bearing echo.
        return True
    if script == "guard_pre_tool.py" and phase == "PreToolUse":
        key = kind.lower() + "_guard"
    elif phase == "PostToolUse" and script == "host_probe.py":
        key = kind.lower() + "_executed"
    else:
        return False
    def change(current):
        # Judged again UNDER the lock, against what is stored now: a store `--prepare` made while the package was walked has
        # another nonce, and a fact about the old pair must not land in it (E3, E4). A store of another shape takes no write (E5).
        checks = current.get("checks") if current is not None else None
        if current is None or current.get("nonce") != nonce or not isinstance(checks, dict):
            return None, None
        checks[key] = {"exit_code": code, "tool_use_id": event.get("tool_use_id"),
                       "command": command.strip(), "session_id": event.get("session_id"),
                       "transcript_path": event.get("transcript_path"),
                       "observed_at": datetime.now(timezone.utc).isoformat()}
        return current, None
    try:
        _store_update(root, change)
    except StateConflict:
        pass   # the lock stayed busy: the fact is not recorded and `--check` names it; the guard's own decision is untouched (E1)
    return False


def nested_command(payload):
    """Recognize one literal code-mode shell call; never evaluate transcript code."""
    if payload.get('type') != 'custom_tool_call' or str(payload.get('name', '')).rsplit('.', 1)[-1] != 'exec':
        return None
    source = str(payload.get('input') or '')
    match = re.fullmatch(r'\s*text\(\s*await\s+tools\.exec_command\(\s*(\{.*\})\s*\)\s*\)\s*;?\s*', source, re.S)
    if not match:
        # Desktop doctors also retain the result before printing it. Accept only
        # an unchanged result, stdout, or the exact exit/output projection; never evaluate JS.
        match = re.fullmatch(
            r'\s*(?:const|let)\s+(?P<var>[A-Za-z_]\w*)\s*=\s*await\s+tools\.exec_command\(\s*'
            r'(?P<args>\{.*\})\s*\)\s*;\s*text\(\s*'
            r'(?:(?P=var)(?:\.output)?|JSON\.stringify\(\s*(?:(?P=var)|\{\s*exit_code\s*:\s*(?P=var)\.exit_code\s*,\s*'
            r'output\s*:\s*(?P=var)\.output\s*\})\s*\))\s*\)\s*;?\s*', source, re.S)
        raw_args = match['args'] if match else None
    else:
        raw_args = match[1]
    if not match:
        return None
    try:
        # The host validates tool options. Correlation needs the literal command,
        # not a second, inevitably stale copy of the exec_command option schema.
        # All values must still be JSON literals; never evaluate expressions.
        raw = re.sub(r'(?<=[{,])\s*([A-Za-z_$][\w$]*)\s*:',
                     lambda m: json.dumps(m[1]) + ':', raw_args)
        args = json.loads(raw)
        return args['cmd'] if isinstance(args, dict) and isinstance(args.get('cmd'), str) else None
    except ValueError:
        return None


def nested_result(payload, command):
    output = payload.get('output') or []
    texts = [c.get('text', '') for c in output if isinstance(c, dict)] if isinstance(output, list) else [str(output)]
    if command.startswith('echo QA_FACTORY_PROBE_DENY_'):
        return any('Command blocked by PreToolUse hook:' in t and 'Command: ' + command in t for t in texts)
    for text in texts:
        # The matching PostToolUse receipt supplies exit status; stdout alone is
        # sufficient only for this exact nonce-bearing echo, not arbitrary commands.
        if command.startswith('echo QA_FACTORY_PROBE_ALLOW_') and text.strip() == command[5:]:
            return True
        try:
            result = json.loads(text)
            if isinstance(result, dict) and result.get('exit_code') == 0 and str(result.get('output', '')).strip() == command[5:]:
                return True
        except ValueError:
            pass
    return False


def claude_call_present(rows, call, command, session):
    """Claude Code keeps a tool call as a `tool_use` block of an assistant row. The receipt is
    real when that block carries the receipt's id, in the receipt's session, and — for a shell
    probe — the exact command. Until 0.7.5 only the Codex row shape was understood, so on
    Claude Code the probe could not verify even with every receipt in place."""
    for row in rows:
        if row.get("type") != "assistant":
            continue
        if session and row.get("sessionId") and row.get("sessionId") != session:
            continue
        content = (row.get("message") or {}).get("content") or []
        for block in content if isinstance(content, list) else []:
            if not isinstance(block, dict) or block.get("type") != "tool_use" or block.get("id") != call:
                continue
            asked = str((block.get("input") or {}).get("command") or "").strip()
            return not command or asked == command
    return False


def _transcript_rows(path):
    rows = []
    try:
        with Path(path).open(encoding="utf-8") as handle:
            for line in handle:
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if isinstance(row, dict):
                    rows.append(row)
    except OSError:
        pass
    return rows


def host_call_present(receipt):
    """Correlate a hook receipt with a real host transcript tool call."""
    call = receipt.get("tool_use_id")
    if not call or not receipt.get("transcript_path"):
        return False
    command, session = receipt.get('command'), receipt.get('session_id')
    if claude_call_present(_transcript_rows(receipt["transcript_path"]), call, command, session):
        return True
    nested_ids, outputs, same_session = set(), {}, False
    try:
        with Path(receipt["transcript_path"]).open(encoding="utf-8") as handle:
            for line in handle:
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                payload = row.get("payload") or {}
                if row.get('type') == 'session_meta' and payload.get('id') == session:
                    same_session = True
                if row.get("type") == "response_item" and payload.get("type") in {"function_call", "custom_tool_call"} and payload.get("call_id") == call:
                    return True
                if row.get('type') != 'response_item':
                    continue
                if command and nested_command(payload) == command:
                    nested_ids.add(payload.get('call_id'))
                if payload.get('type') == 'custom_tool_call_output':
                    outputs[payload.get('call_id')] = payload
    except OSError:
        pass
    # Code mode assigns exec-* IDs inside the outer call. Correlate the unique probe
    # command AND its host result, never text merely mentioned in a prompt or comment.
    return bool(same_session and str(call).startswith('exec-') and len(nested_ids) == 1
                and nested_result(outputs.get(next(iter(nested_ids)), {}), command))


# --- does the guard still PARSE ordinary events of this host? ------------------------------
#
# The allow/deny probe above proves the guard FIRES. It does not prove the guard still
# understands the event shapes this host sends: `PT-unparsed-event` / `PT-patch-unchecked`
# refuse fail-closed precisely when it does not, and 0.7.7 made the second one in a row a
# diagnosis with `owner: factory` that ends in "run /qa-factory:qa-doctor" — while the doctor
# had nothing to look at. Exit 0 is that proof and costs nothing extra: both of those
# refusals leave through hooklib.block() with exit 2, so a call the guard LET THROUGH is a
# call it read. One receipt per session, overwritten, for the same reason telemetry_hook.py's
# pretool receipt is one per session: a session makes hundreds of tool calls, and one file per
# call is the unbounded growth the cost files already taught this factory to avoid.
#
# Codex never sends Write/Edit: its file mutation is `apply_patch` (also namespaced, e.g.
# `functions.apply_patch`), and note_guard_parse resolves the name through host_adapter.normalize
# before the lookup. Until then the write family could never become verified on that host
# (M25). Only the guard's own exit-0 PreToolUse receipt counts, so a malformed patch the guard
# refuses with exit 2 certifies nothing.
GUARD_FAMILIES = {"Bash": "bash", "PowerShell": "bash",
                  "Write": "write", "Edit": "write", "NotebookEdit": "write",
                  "apply_patch": "write"}


def _guard_hash():
    return hashlib.sha256((Path(__file__).parent / "guard_pre_tool.py").read_bytes()).hexdigest()


def _guard_parse_path(root, session):
    name = hashlib.sha256(str(session).encode("utf-8")).hexdigest()[:16]
    return Path(root) / "qa-factory/state/host-receipts" / f"guard-parse-{name}.json"


def _guard_parse_rows(root, limit=None):
    """The guard-parse receipts of the project that read as objects, newest first (`limit`: only the newest N FILES are
    read, so an unreadable newest file yields no row rather than an older one). The ONE reader of these files for
    `guard_parse` (no session named) and for the `other_session_hooks` condition (AR-13). Never raises."""
    try:
        paths = sorted((Path(root) / "qa-factory/state/host-receipts").glob("guard-parse-*.json"),
                       key=lambda p: p.stat().st_mtime, reverse=True)
    except OSError:
        return []
    rows = []
    for path in paths[:limit]:
        loaded = _read_dict(path)
        if loaded is not None:
            rows.append(loaded)
    return rows


def host_version(event):
    """Whatever version string this host actually hands a hook; '' when it hands none.

    Claude Code does not document a version field on hook events (checked 2026-09-21), so this
    is best effort: it is reported when present and simply absent otherwise — never guessed."""
    import os
    event = event or {}
    for value in (event.get("host_version"), event.get("version"), event.get("client_version"),
                  os.environ.get("CLAUDE_CODE_VERSION"), os.environ.get("CODEX_VERSION")):
        if str(value or "").strip():
            return str(value).strip()
    return ""


def note_guard_parse(root, event, script, code):
    """Record how the pre-tool guard handled one ordinary event, by tool family.

    Fail-silent on purpose, like the guard's own counter: a receipt about the guard is never
    allowed to change what the guard decided, and this runs after that decision is made."""
    from host_adapter import normalize
    raw = event if isinstance(event, dict) else {}
    try:
        # telemetry_hook hands over the RAW event. normalize() refuses a non-object event or
        # tool_input (ValueError); that is "nothing to record" here, and it must not escape:
        # the caller runs the next recorders after this one inside the same try.
        event = normalize(event or {})
    except Exception:
        return
    family = GUARD_FAMILIES.get(str(event.get("tool_name") or ""))
    session = str(event.get("session_id") or "").strip()
    if (script != "guard_pre_tool.py" or event.get("hook_event_name") != "PreToolUse"
            or not family or not session):
        return
    try:
        path = _guard_parse_path(root, session)
        current = _guard_hash()
        version = host_version(event)
        from host_capabilities import host_of_event
        # The host is read off what the host SENT: normalize() renames a Codex shell call to
        # `Bash`, which would erase the tool-name signal host_of_event relies on.
        host = host_of_event(raw)
        # Read-modify-write under the lock: a Write and a Bash call of one message run their hooks in parallel and both
        # recorded their family into the file they had read before the other's write (the same class as the probe store).
        # A lock that stays busy is "not recorded" - the fail-silent rule of this function, handled by the except below.
        with _store_lock(root, "guard-parse-lock"):
            data = _read_dict(path)
            if data is None or data.get("guard_hash") != current:
                # The guard changed: evidence about the previous one says nothing about this one.
                data = {"guard_hash": current, "families": {}}
            if version:
                data["host_version"] = version
            data["session_id"] = session
            data["host"] = host
            entry = (data.setdefault("families", {})).setdefault(family, {})
            now = datetime.now(timezone.utc).isoformat()
            entry.update(tool_name=str(event.get("tool_name")), exit_code=code, observed_at=now)
            if code == 0:
                entry["parsed_at"] = now  # let through == read; see the comment above
            atomic_json(path, data)
    except Exception:
        return


def guard_parse(root, session=None):
    """The doctor's report of that evidence: did the guard read an ordinary shell call and an
    ordinary file write in this session, and did either fail-closed refusal fire?"""
    if session:
        loaded_rows = [_read_dict(_guard_parse_path(root, session))]
    else:
        loaded_rows = _guard_parse_rows(root, limit=1)
    data = {}
    for loaded in loaded_rows:
        if isinstance(loaded, dict) and loaded.get("guard_hash") == _guard_hash():
            data = loaded
    families = {}
    for family in ("bash", "write"):
        entry = (data.get("families") or {}).get(family) or {}
        fresh = False
        try:
            age = (datetime.now(timezone.utc)
                   - datetime.fromisoformat(entry["parsed_at"])).total_seconds()
            fresh = 0 <= age < PROBE_TTL_S
        except (KeyError, TypeError, ValueError):
            fresh = False
        families[family] = {"status": "verified" if fresh else "unverified",
                            "tool_name": entry.get("tool_name"),
                            "exit_code": entry.get("exit_code"),
                            "observed_at": entry.get("observed_at")}
    refusal = _fail_closed_refusal(root, data.get("session_id") or session)
    version = data.get("host_version") or ""
    if refusal:
        return {"status": "guard_defect", "owner": "factory", "families": families,
                "refusal": refusal, "host_version": version,
                "reason": f"The guard refused {refusal['count']} call(s) with `{refusal['refusal']}`: "
                          "it did not parse this host's events. Owner: the factory — nothing here is "
                          "the person's to repair" + (f" (host {version})" if version else "") + "."}
    missing = sorted(f for f, v in families.items() if v["status"] != "verified")
    if missing:
        return {"status": "unverified", "owner": "factory", "families": families,
                "host_version": version,
                "reason": "No clean guard handling on record for: " + ", ".join(missing)
                          + ". Make one ordinary call of each shape in this session "
                            "(a shell command, and a Write of one temp file), then re-run --check."}
    return {"status": "verified", "families": families, "host_version": version,
            "reason": "The pre-tool guard parsed an ordinary shell call and an ordinary file write in this session."}


def escalation_record_path(root, session):
    """Where guard_pre_tool.py keeps its refusal counter for one session.

    The name is built here rather than by importing that module: this runs from a doctor CLI
    whose `--root` need not be the cached project root a hook resolved. A test pins the two
    spellings together so they cannot drift (test_claude_host_probe.py)."""
    safe = "".join(c for c in str(session or "") if c.isalnum() or c in "-_")[:64]
    return Path(root) / "qa-factory/state/guard-escalation" / f"{safe or 'unknown'}.json"


def _fail_closed_refusal(root, session):
    """Did either fail-closed refusal actually fire in this session? The guard's own counter
    file is the record (guard_pre_tool.py writes it on every such refusal); it is disposable,
    so its absence is not evidence of health — only its presence is evidence of the defect."""
    if not session:
        return None
    try:
        record = json.loads(escalation_record_path(root, session).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if isinstance(record, dict) and record.get("refusal") in ("PT-unparsed-event", "PT-patch-unchecked"):
        return {"refusal": record["refusal"], "count": record.get("count"), "at": record.get("at")}
    return None


def injection_marker(root, event):
    """Only the designated read-only diagnostic dispatch receives the random challenge."""
    path = Path(root) / "qa-factory/state/host-probe.json"
    from native_context import diagnostic
    if not path.is_file() or not diagnostic(event):
        return ''
    data = _read_dict(path)    # a store of another shape is "no challenge", never an exception on the dispatch path (E5)
    if data is None or data.get('session_id') != event.get('session_id') or data.get('fingerprint') != fingerprint(root):
        return ''
    # 32 hex, the length this host copies reliably: on 13.10 two probe children (Codex Desktop,
    # gpt-5.6-terra) answered a 48-hex challenge as 41/48 and 47/48 characters, the tail dropped,
    # while the 32-hex allow/deny nonces were copied into 24 of 24 native tool calls.
    challenge = secrets.token_hex(16)
    nonce = data.get('nonce')

    def change(current):
        # The fingerprint above was walked BEFORE the lock; here only the stored nonce is compared again: a store that
        # `--prepare` replaced meanwhile is another probe's, and takes no challenge of this one (E3).
        if current is None or current.get('nonce') != nonce:
            return None, False
        current['injection'] = {'challenge': challenge, 'tool_use_id': event.get('tool_use_id'),
                                'transcript_path': event.get('transcript_path'), 'status': 'emitted'}
        return current, True
    try:
        if not _store_update(root, change):
            return ''
    except StateConflict:
        return ''    # a busy store is "no challenge" as a store of another session is (E1); `--check` stays `unverified`
    # The sentinel belongs to the identifier. The M11b '.' delimiter did not help: neither 13.10
    # child reproduced it (they answer the identifier alone, as "Return exactly" reads to them),
    # so nothing absorbed the trim. `_END` is reproduced with the token it ends; a host or model
    # that trims the last output character trims the sentinel, not the challenge. check_child
    # still demands the whole challenge and never the sentinel, so a truncated challenge fails.
    return ('\n\nRead-only doctor diagnostic: do not collect tickets or use tools. '
            'Return exactly ' + CHALLENGE_PREFIX + challenge + '_END.')


def bind_injection(root, event, agent):
    path = Path(root) / 'qa-factory/state/host-probe.json'
    if not path.is_file():
        return
    def change(data):
        proof = data.get('injection') if data is not None else None
        if isinstance(proof, dict) and proof.get('tool_use_id') and proof['tool_use_id'] == event.get('tool_use_id'):
            if not proof.get('agent_id') or (str(proof['agent_id']).startswith('/') and not str(agent).startswith('/')):
                proof['agent_id'] = agent
            return data, True
        return None, False    # no proof of this call, or a store that cannot be read as one: nothing is bound
    try:
        return _store_update(root, change)
    except StateConflict:
        return False          # a busy store binds nothing (E1)


NO_LAUNCH_ID_DETAIL = ("host response carries no launch id: the probe child cannot be tied to this launch, so its answer is "
                       "not judged; the host's answer to `Agent` must name the agent under a key of `launch_id_keys` in "
                       "references/{forms}; re-probe under a new task name")


def note_no_launch_id(root, event):
    """The host answered the launch of the probe child (the call whose `tool_use_id` the store holds) with no launch id:
    record that on the proof so `inspect` can say why the probe stays `unverified`. Only the proof of THIS call and only while
    it holds no agent; nothing else is written and nothing is judged here (FR-59: the safe direction is `unverified`)."""
    path = Path(root) / 'qa-factory/state/host-probe.json'
    if not path.is_file():
        return
    def change(data):
        proof = data.get('injection') if data is not None else None
        if (isinstance(proof, dict) and proof.get('tool_use_id') and proof['tool_use_id'] == event.get('tool_use_id')
                and not proof.get('agent_id')):
            proof['no_launch_id'] = True
            return data, True
        return None, False
    try:
        return _store_update(root, change)
    except StateConflict:
        return False


def is_probe_child(root, event):
    """Is this stop the doctor's context probe child? THE one predicate (AR-13, AR-15): `exit_gate` and `subagent_journal`
    both ask it, and nothing else decides it. Two routes. (1) The binding: a stop the host adapter has marked
    `factory_diagnostic: context_probe` with a `host_binding`. (2) The probe's own mark, TIED TO THE SAME LAUNCH: the store
    holds a probe of THIS session (`session_id` equal to the event's), its proof is still `emitted`, when the proof is bound
    the stop is that agent's (`agent_id` equal), and the stored challenge (a shape `_challenge_ok` accepts) appears with
    `QA_CONTEXT_RECEIVED_` in the child's last message or an assistant row of its transcript. Any of these missing is False
    BEFORE any transcript is read: a stage role of another session, or after the verdict, is never exempted by a mark it
    could have read from the store. An event, store or transcript that cannot be read is False (never raises)."""
    try:
        if event.get('factory_diagnostic') == 'context_probe' and event.get('host_binding'):
            return True
        data = _read_dict(Path(root) / 'qa-factory/state/host-probe.json')
        proof = data.get('injection') if data else None
        if not isinstance(proof, dict) or proof.get('status') != 'emitted' or not _challenge_ok(proof.get('challenge')):
            return False
        if not event.get('session_id') or data.get('session_id') != event.get('session_id'):
            return False
        if proof.get('agent_id') and proof['agent_id'] != event.get('agent_id'):
            return False
        mark = CHALLENGE_PREFIX + proof['challenge']
        last = event.get('last_assistant_message')
        if isinstance(last, str) and mark in last:
            return True
        transcript = event.get('agent_transcript_path')
        if not transcript:
            return False
        return any(mark in text for text in _assistant_texts(Path(transcript).read_bytes())[0])
    except Exception:  # noqa: BLE001 - a gate that asks must not break on a store or a transcript of another shape
        return False


def note_probe_launch(root, event, response):
    """The Claude PostToolUse `Agent|Task` entry of the probe launch (FR-17: the host's own hook is where this runs; on
    Codex `host_dispatch.record` does it). The id the host's answer carries, read by the one reader `launch_id_of`, binds
    the proof of THIS call (`bind_injection`); an answer with no id records the reason (`note_no_launch_id`). Both write
    only into the proof whose `tool_use_id` is this call's, so any other launch writes nothing."""
    from host_adapter import launch_id_of
    agent = launch_id_of(response)
    return bind_injection(root, event, agent) if agent else note_no_launch_id(root, event)


def _challenge_ok(value):
    """Whether a stored challenge has a shape some build of injection_marker wrote (32 or 48 lowercase hex).
    Anything else - absent, empty, a number, a list, any other length - is NOT judged: with no known
    challenge there is nothing a child's answer could be compared with, and an empty one would let
    every answer carrying the prefix pass (FR-59)."""
    return isinstance(value, str) and _CHALLENGE_FORM.fullmatch(value) is not None


def _returned(value):
    """The run of identifier characters [0-9A-Za-z_] at the start of `value`, at most RETURNED_LIMIT of
    them; '' when `value` is not text. The ONE cut: check_child applies it to what it stores, inspect to
    what it reads back, because a role can write the store and the detail reaches a person."""
    return _IDENTIFIER_RUN.match(value).group()[:RETURNED_LIMIT] if isinstance(value, str) else ''


def _assistant_texts(snapshot):
    """(texts, used_tool) of a child transcript, in ONE pass over its rows, both host shapes.

    `texts` are the texts of the assistant rows only (Claude `type: assistant` + `message.content`; Codex
    `response_item` + `payload.role == 'assistant'`): the host's own instruction row (developer, user,
    system) carries the full challenge by construction and proves nothing about the child. `used_tool` is
    True when the child made ANY tool call (a Claude `tool_use` block, a Codex `function_call` /
    `custom_tool_call` / `local_shell_call` row): a child that may have READ the challenge from the store,
    the launch packet or the parent transcript has not shown that it was handed it. A row that is not a
    JSON object raises ValueError, like an unparsable one: a transcript that cannot be read whole judges
    nothing.

    One tool call is the answer itself, not a tool: a host that returns a subagent's final report through a
    handback call (Claude Code, 10.2026) puts the child's words in that call's `input`, and the assistant rows
    hold no text at all. The call is named by `references/host-report-forms.json`, read through the one reader
    `host_adapter.report_forms` and matched EXACTLY; its string inputs are read as the child's texts and it does
    not count as a tool the child used - otherwise every probe child answers `tool_used` or nothing (OH3-13).
    With no readable form NO call is a handback: it counts as a tool, the answer is not found, the probe stays
    `unverified` (AR-28)."""
    from host_adapter import assistant_row_blocks, assistant_row_texts, handback_name, report_forms
    texts, used_tool = [], False
    forms, _why = report_forms()
    handback = handback_name(forms)
    for line in snapshot.decode('utf-8').splitlines():
        row = json.loads(line)
        if not isinstance(row, dict):
            raise ValueError('transcript row is not an object')
        texts.extend(assistant_row_texts(row, forms))   # the ONE row reader (AR-13); the strictness above stays here
        payload = row.get('payload') if isinstance(row.get('payload'), dict) else {}
        used_tool = used_tool or (row.get('type') == 'response_item' and payload.get('type') in _TOOL_ROWS)
        for block in assistant_row_blocks(row):         # the same blocks, not a second walk of the row shapes
            if block.get('type') == 'tool_use' and not (handback and block.get('name') == handback):
                used_tool = True
    return texts, used_tool


def check_child(root, event):
    """Judge the probe child's answer at its SubagentStop. Never raises and writes nothing it cannot stand
    behind: a hook that ends in an exception is not a block on Claude Code, so a store or an event of any
    shape ends here in silence (no write), never in a traceback (E8).

    `delivered` is written in ONE place: an assistant row of a child that made no tool call holds the whole
    stored challenge after the prefix. A `delivered` proof is never touched again - its hash fields are what
    `inspect` accepts it by - so that guard comes first, before any other check and any read of a transcript.
    The decision is taken after the whole scan, so the order of rows decides nothing. Otherwise: an answer
    that carries the prefix without the whole challenge is a `mismatch` naming what came back; a prefixed
    answer of a child that used a tool is `tool_used`; no prefixed answer writes nothing (`emitted` stays)."""
    path = Path(root) / 'qa-factory/state/host-probe.json'
    if not path.is_file():
        return
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        proof = data.get('injection') or {}
        if proof.get('status') == 'delivered':
            return
        if not proof.get('agent_id'):
            return
        if proof['agent_id'] != event.get('agent_id'):
            from host_dispatch import child_identity
            identity = child_identity(event)
            if identity.get('task_path') != proof['agent_id'] or identity.get('parent_session_id') != data.get('session_id'):
                return
        transcript, challenge = event.get('agent_transcript_path'), proof.get('challenge')
        if not transcript or not _challenge_ok(challenge):
            return
        snapshot = Path(transcript).read_bytes()
        texts, used_tool = _assistant_texts(snapshot)
        answers = [text for text in texts if CHALLENGE_PREFIX in text]
        if not answers:
            return
        if used_tool:
            verdict = dict(status='tool_used', child_transcript=transcript)
        elif any(CHALLENGE_PREFIX + challenge in text for text in answers):
            verdict = dict(status='delivered', child_transcript=transcript, transcript_bytes=len(snapshot),
                           transcript_hash=hashlib.sha256(snapshot).hexdigest())
        else:
            verdict = dict(status='mismatch', child_transcript=transcript,
                           returned=_returned(answers[0][answers[0].index(CHALLENGE_PREFIX):]))

        def change(current):
            # The transcript was read and judged BEFORE the lock; under it only the store is read again. The verdict is
            # written only into the SAME probe and the SAME challenge it was judged against, and never over a `delivered`
            # proof (the first guard of this function, held again at the write).
            now = current.get('injection') if current is not None else None
            if (not isinstance(now, dict) or current.get('nonce') != data.get('nonce')
                    or now.get('challenge') != challenge or now.get('agent_id') != proof.get('agent_id')
                    or now.get('status') == 'delivered'):
                return None, None
            now.pop('returned', None)
            now.update(verdict)
            return current, None
        _store_update(root, change)
    except Exception:  # noqa: BLE001 - see the docstring: an unreadable store or transcript, or a busy lock, changes nothing
        return


def _context_path(root, session):
    name = hashlib.sha256(str(session).encode("utf-8")).hexdigest()[:16]
    return Path(root) / "qa-factory/state/host-receipts" / f"context-delivery-{name}.json"


def _age_s(stamp, now=None):
    """Seconds since an ISO time WITH a UTC offset, or None when `stamp` is not one (a naive time cannot be set against the
    clock). A future time gives a negative age: the callers' window `0 <= age < PROBE_TTL_S` refuses it."""
    try:
        seen = datetime.fromisoformat(stamp)
    except (TypeError, ValueError):
        return None
    if seen.tzinfo is None:
        return None
    return ((now or datetime.now(timezone.utc)) - seen).total_seconds()


def _ends_context(row):
    """True for the first row that is the child's own move, not what it was handed: an assistant row of either host
    shape, or a Codex tool-call row. The row shapes are told apart by `host_adapter.assistant_row_blocks` and `_TOOL_ROWS`."""
    from host_adapter import assistant_row_blocks
    payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
    return bool(assistant_row_blocks(row) or row.get("type") == "assistant"
                or (row.get("type") == "response_item" and (payload.get("role") == "assistant" or payload.get("type") in _TOOL_ROWS)))


def check_role_context(root, event):
    """Keep the evidence that a REAL role dispatch was handed its context (HF8-12, W-5): at a child's SubagentStop, the
    packet heading `inject_context.PACKET_HEADING` stands among the first `ROLE_CONTEXT_ROWS` rows of its transcript, before
    its first move (an assistant row or a tool call). The receipt is `host-receipts/context-delivery-<sha16 session>.json`,
    the ONE writer of that family (AR-14). A diagnostic probe child has no packet, so it leaves none (E18); a heading the child
    quoted later is not read (E17). It is separate from `injection`: it says the text reached the child's input, not that the
    child read it, so it never makes `story_ready` (E9).

    Never raises (a hook that ends in an exception is not a block on Claude Code): no transcript, a row that is not a JSON
    object in the part read, bytes of the package that cannot be read, a project with no `qa-factory/` - no receipt. A session
    that already holds a receipt younger than `PROBE_TTL_S` reads only the bounded opening rows and, when the packet stands
    there, refreshes `observed_at` while KEEPING the held fingerprint: no package walk (AR-12), and a later story of a long
    session is seen after ITS S0 (`gate_brief._proved_warnings` compares `observed_at` with `S0.finished`). The kept
    fingerprint is the held one, so bytes that changed since are still refused by `role_context` (E20)."""
    try:
        if not isinstance(event, dict) or event.get("hook_event_name") != "SubagentStop":
            return
        transcript, session = event.get("agent_transcript_path"), event.get("session_id")
        if not isinstance(transcript, str) or not transcript or not isinstance(session, str) or not session.strip():
            return
        if not (Path(root) / "qa-factory").is_dir():
            return
        from hooklib import read_json
        path = _context_path(root, session)
        held = read_json(path, None, errors=Exception, kind=dict) or {}
        age = _age_s(held.get("observed_at"))
        kept = held.get("fingerprint") if age is not None and 0 <= age < PROBE_TTL_S else None
        if not _packet_in_opening(transcript):
            return
        stamp = kept if isinstance(kept, str) and kept and not kept.startswith("unknown:") else fingerprint(root)
        if stamp.startswith("unknown:"):
            return                            # bytes that were not read: no receipt is bound to them (FR-59)
        from host_capabilities import host_of_event
        agent_type = event.get("agent_type")
        atomic_json(path, {"session_id": session, "agent_type": agent_type if isinstance(agent_type, str) and agent_type else None,
                           "host": host_of_event(event), "child_transcript": transcript, "fingerprint": stamp,
                           "observed_at": datetime.now(timezone.utc).isoformat()})
    except Exception:  # noqa: BLE001 - see the docstring
        return


def _packet_in_opening(transcript):
    """True when the packet heading stands among the first `ROLE_CONTEXT_ROWS` rows of `transcript`, before the child's first
    move. A row that is not a JSON object is False (a transcript that cannot be read as rows is judged by none of them, E19);
    an unreadable file or a row that is not JSON raises, and the caller's one try block turns that into "no receipt"."""
    from inject_context import PACKET_HEADING
    with Path(transcript).open(encoding="utf-8") as handle:
        for number, line in enumerate(handle, 1):
            if number > ROLE_CONTEXT_ROWS:
                return False
            row = json.loads(line)
            if not isinstance(row, dict):
                return False
            if _ends_context(row):
                return False
            if PACKET_HEADING in json.dumps(row, ensure_ascii=False):
                return True
    return False


def _walk(root):
    return fingerprint(root)


def role_context(root, fingerprint=None):
    """The newest receipt of `check_role_context` that is still evidence, or None. The ONE reader of
    `context-delivery-*.json` (AR-13). Evidence is: the same package and config bytes (`fingerprint`, the one `inspect` already
    walked - passed in so a gate that asks on every spawn does not walk the package again, AR-12; None walks it here, and only
    when a receipt of the right age exists) and an age in `[0, PROBE_TTL_S)`. A missing folder, an unreadable file, JSON that
    is not an object, a field of another type, a time with no UTC offset: that file is skipped. Never raises - it is read on the
    path of the Codex spawn gate, where an exception is exit 1 and not a block (E26)."""
    try:
        from hooklib import read_json, sorted_paths
        now = datetime.now(timezone.utc)
        found = []
        for path in sorted_paths((Path(root) / "qa-factory/state/host-receipts").glob("context-delivery-*.json")):
            row = read_json(path, None, errors=Exception, kind=dict)
            if row is None or not all(isinstance(row.get(key), str) and row[key] for key in ("session_id", "host", "fingerprint")):
                continue
            age = _age_s(row.get("observed_at"), now)
            if age is not None and 0 <= age < PROBE_TTL_S:
                found.append((datetime.fromisoformat(row["observed_at"]), row))
        if not found:
            return None
        current = fingerprint if isinstance(fingerprint, str) and fingerprint else _walk(root)
        if current.startswith("unknown:"):
            return None
        same = [pair for pair in found if pair[1]["fingerprint"] == current]
        return max(same, key=lambda pair: pair[0])[1] if same else None
    except Exception:  # noqa: BLE001 - see the docstring
        return None


def _unmet(id_, reason):
    return {"id": id_, "reason": reason}


UNMET_TEXT_CHARS = 2000   # the longest `unmet_text` before the cut; the whole list stays under "missing" in --check (E3)


def unmet_text(missing):
    """The unmet conditions in one sentence, appended AFTER the existing first sentence of `reason` (FR-1).
    The one builder of this text: `inspect`, the context guard's refusal and the host_capabilities note all read `missing`
    through it (AR-13, AR-18). It never raises (a guard that raises exits 1, which is not a block) and never judges: an
    entry that is not a dict with a string `id` is skipped, a missing `reason` prints the `id` alone, an id this version
    does not know is printed as it is, white space (a stored value may carry a line break) collapses to one space."""
    try:
        parts = []
        for m in missing if isinstance(missing, list) else []:
            if isinstance(m, dict) and isinstance(m.get("id"), str):
                reason = m.get("reason")
                parts.append(f"{m['id']} ({reason})" if isinstance(reason, str) and reason else m["id"])
        if not parts:
            return ""
        text = " ".join((" Unmet: " + "; ".join(parts) + ".").split())
        text = " " + text
        if len(text) > UNMET_TEXT_CHARS:
            text = text[:UNMET_TEXT_CHARS] + ' (cut; the whole list is under "missing" in host_probe.py --check)'
        return text
    except Exception:  # noqa: BLE001 - a text builder on the refusal path never raises
        return ""


PROBE_TTL_S = 86400   # the one 24 h window of a probe, shared by every reader of its age


def _call_unmet(name, receipt):
    """The unmet transcript condition of one receipt of the pair, or None when its call is in the transcript.
    Each cause is its own id (an unknown is never a pass, FR-59); `host_call_present` stays the judge."""
    if host_call_present(receipt):
        return None
    if not receipt.get("tool_use_id"):
        return _unmet(f"{name}_no_receipt", f"no `{name}` receipt with a tool call id is recorded: run its native "
                      "command in this host session, after host_probe.py --prepare")
    path = receipt.get("transcript_path")
    if not path or not Path(path).is_file():
        return _unmet(f"{name}_no_transcript", f"the `{name}` receipt names no readable host transcript: the call "
                      "cannot be matched to the host's record; run --prepare and the pair again in one host session")
    return _unmet(f"{name}_not_in_transcript", f"the transcript holds no `{name}` call with the same id, session and exact "
                  "command as the receipt; run the documented pair as separate native tool calls in one session")


def _other_session_hooks(root, session, created, allow, deny):
    """The unmet condition `other_session_hooks`, or None. Named only when this session's guard left NO fact of the pair
    (no `allow_guard`, no `deny_guard`) while a guard-parse receipt of ANOTHER session has a family observed at or after
    `--prepare`: some hooks that ran were another session's. The condition cannot tell the probe's own echo from an ordinary call
    of that session (the receipt records ordinary calls), so the text says what was seen and offers the door as an "if". It only
    names (FR-59): it never changes the status and removes no other condition. A receipt that cannot be read, a family with
    no timed observation, a time with no UTC offset: no claim is made."""
    if allow or deny:
        return None
    for row in _guard_parse_rows(root):
        other = row.get("session_id")
        families = row.get("families")
        if not isinstance(other, str) or not other or other == session or not isinstance(families, dict):
            continue
        for entry in families.values():
            try:
                seen = datetime.fromisoformat(entry["observed_at"])
            except (KeyError, TypeError, ValueError):
                continue
            if seen.tzinfo is not None and seen >= created:
                return _unmet("other_session_hooks", "hooks of another session ran after --prepare and none of this session's; "
                                                     "if the pair was run there, run --prepare and the pair again in one session")
    return None


def _unmet_conditions(root, session, created, current, fingerprint_ok, unread, fresh, allow, deny, executed, checks):
    """Every condition of the `verified` conjunction that does not hold, in the order `inspect` checks them.
    The predicate itself stays in `inspect`; this only names what it cannot say. `root`, `session` (the session that
    prepared the probe) and `created` (its `created_at`) are for the one condition that reads the receipts of other sessions."""
    out = []
    if not current:
        if unread:
            out.append(_unmet("fingerprint_unread", "the package or config bytes could not be read, so nothing is judged against them; "
                                                    "fix the unreadable files, then run --prepare again"))
        elif not fingerprint_ok:
            out.append(_unmet("fingerprint_changed", "the package or config changed since --prepare; run --prepare again"))
        if not fresh:
            out.append(_unmet("probe_expired", "the probe is older than 24 hours (or dated in the future); run --prepare again"))
    if allow.get("exit_code") != 0:
        out.append(_unmet("allow_guard_not_allowed", "the guard did not record exit 0 for the harmless ALLOW command; "
                                                     "run it as a native tool call after --prepare"))
    if deny.get("exit_code") != 2:
        out.append(_unmet("deny_guard_not_blocked", "the guard did not record exit 2 for the DENY command; "
                                                    "run it as a native tool call after --prepare"))
    if executed.get("tool_use_id") != allow.get("tool_use_id"):
        out.append(_unmet("allow_executed_id_differs", f"the executed ALLOW call's tool call id ({executed.get('tool_use_id') or 'none'}) does not match "
                                                       f"the guard's ALLOW receipt id ({allow.get('tool_use_id') or 'none'}); "
                                                       "run the pair again in one session"))
    if checks.get("deny_executed"):
        out.append(_unmet("deny_was_executed", "the DENY command was executed, so the guard did not block it: a guard defect, "
                                               "not a probe to repeat"))
    for name, receipt in (("allow_guard", allow), ("deny_guard", deny), ("allow_executed", executed)):
        item = _call_unmet(name, receipt)
        if item:
            out.append(item)
    item = _other_session_hooks(root, session, created, allow, deny)
    if item:
        out.append(item)
    return out


def inspect(root, walked=None):
    """The probe's verdict. `walked`, when a caller passes a dict, receives `fingerprint`: the bytes this call judged against,
    so a second reader of the same moment (`role_context`) does not walk the package again (AR-12). The answer's keys do not change."""
    path = Path(root) / "qa-factory/state/host-probe.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        # One shape for every file that cannot be judged: unreadable, not JSON, JSON that is not an
        # object, no `created_at`, one that is not an ISO time or carries no UTC offset (a naive time
        # cannot be set against the clock). Never a traceback: the person gets the way to a fresh probe.
        created = datetime.fromisoformat(data["created_at"])
        if created.tzinfo is None:
            raise ValueError("created_at has no UTC offset")
    except (OSError, ValueError, TypeError, KeyError) as exc:
        gone = isinstance(exc, FileNotFoundError)
        missing = [_unmet("no_probe_file" if gone else "probe_file_unreadable",
                          "there is no probe file for this project yet" if gone else
                          "the probe file cannot be read as a probe (unreadable, not JSON, or no valid UTC created_at)")]
        return {"status": "unverified", "guard_parse": guard_parse(root), "missing": missing,
                "reason": "Run host_probe.py --prepare in the current host session, execute its two native tool commands, then --check."
                          + unmet_text(missing)}
    checks = data.get("checks")
    checks = checks if isinstance(checks, dict) else {}   # valid JSON of another shape is judged as empty, never a crash
    now_fingerprint = fingerprint(root)
    if walked is not None:
        walked["fingerprint"] = now_fingerprint
    unread = now_fingerprint.startswith("unknown:")   # bytes that could not be read: nothing is judged against them
    fingerprint_ok = data.get("fingerprint") == now_fingerprint
    age = (datetime.now(timezone.utc) - created).total_seconds()
    fresh = 0 <= age < PROBE_TTL_S
    current = fingerprint_ok and fresh
    allow, deny, executed = (r if isinstance(r, dict) else {}
                             for r in (checks.get(k) for k in ("allow_guard", "deny_guard", "allow_executed")))
    verified = (current and allow.get("exit_code") == 0 and deny.get("exit_code") == 2
                and executed.get("tool_use_id") == allow.get("tool_use_id") and not checks.get("deny_executed")
                and all(host_call_present(r) for r in (allow, deny, executed)))
    # Named only when the predicate above failed; empty (present) when it held. A failure the list cannot
    # explain is itself named, never left silent (FR-59).
    missing = [] if verified else (_unmet_conditions(root, data.get("session_id"), created, current, fingerprint_ok, unread, fresh,
                                                                   allow, deny, executed, checks)
                                   or [_unmet("unknown_condition", "the check failed on a condition this version cannot name; "
                                                                   "run --prepare and the pair again")])
    injection = data.get('injection')
    injection = injection if isinstance(injection, dict) else {}
    delivered = current and injection.get('status') == 'delivered' and host_call_present(injection)
    if delivered:
        try:
            with Path(injection['child_transcript']).open('rb') as stream:
                snapshot = stream.read(injection.get('transcript_bytes', -1))
            delivered = hashlib.sha256(snapshot).hexdigest() == injection['transcript_hash']
        except (OSError, KeyError, TypeError, ValueError):
            # A store a role can write may hold any type here; an unreadable proof is no proof, never a traceback
            # (a spawn gate that raises exits 1, which on Claude Code is not a block).
            delivered = False
    next_action = ('none' if verified and delivered else 'dispatch_context_probe' if verified
                   else 'prepare_probe' if not current else 'check_guard_evidence')
    detail = {}
    # Said in words and numbers so the doctor can tell a near miss from no answer; never a pass. Only while the
    # guard is verified: the re-probe it names is refused by stage_guard without a verified guard (FR-2). The
    # number is the agreeing PREFIX of the stored challenge, so "32 of 32" never stands beside `unverified` (FR-41);
    # a stored shape that cannot be stated truthfully (no readable answer, no judged challenge) gets no detail.
    status, returned, challenge = injection.get('status'), injection.get('returned'), injection.get('challenge')
    if verified and status == 'tool_used':
        detail = {"injection_detail": TOOL_DETAIL}
    elif verified and status == 'emitted' and injection.get('no_launch_id') is True and not injection.get('agent_id'):
        import host_adapter   # the forms file's name comes from its one reader (AR-13)
        detail = {"injection_detail": NO_LAUNCH_ID_DETAIL.format(forms=host_adapter.REPORT_FORMS_FILE.name)}
    elif verified and status == 'mismatch' and isinstance(returned, str) and _challenge_ok(challenge):
        returned = _returned(returned)
        import os
        got = (len(os.path.commonprefix([returned[len(CHALLENGE_PREFIX):], challenge]))
               if returned.startswith(CHALLENGE_PREFIX) else 0)
        detail = {"injection_detail": f"the probe child answered '{returned}' (its first {got} of "
                                      f"{len(challenge)} characters match the challenge); "
                                      "re-probe under a new task name"}
    if unread:
        # `unverified`, not `stale`: no change of the bytes was measured, they were not read (FR-41); the door is named (FR-1).
        why = now_fingerprint.split(":")[1]
        head = ("package files could not be read; the evidence was not judged" if why == "package_unreadable"
                else "the project's qa-factory/config.json could not be read; the evidence was not judged")
        which = "qa-factory/config.json"
        if why == "package_unreadable":
            # rare path, cost irrelevant: name the files (FR-1) through the one read of the survivor and the one cut of the list
            try:
                import factory_manifest
                release_fingerprint.file_digests(Path(__file__).resolve().parents[1])
                which = "none named: a second read of the package succeeded"
            except OSError as exc:
                which = factory_manifest._unreadable_names(exc) or "none named"
            except Exception:  # noqa: BLE001 - a walk that failed otherwise: no name is invented
                which = "could not list them"
        detail = {"fingerprint_detail": f"{head} ({why}); the files that could not be read: {which}. "
                                        "No probe is judged against unread bytes; fix them, then run --prepare again"}
    return {"status": "verified" if verified else "stale" if not (current or unread) else "unverified",
            "injection": "verified" if delivered else "unverified", **detail,
            # Separate evidence, separate line: a guard that fires but no longer parses this
            # host's events is exactly the failure the 0.7.7 escalation sends people here with.
            "guard_parse": guard_parse(root, data.get("session_id")),
            "next_action": next_action,
            "session_id": data.get("session_id"), "checks": checks, "missing": missing,
            "reason": ("Host allow/deny behavior verified" if verified else
                       f"{head}; no synthetic probe certifies host activation." + unmet_text(missing) if unread else
                       "Missing live allow/deny evidence; no synthetic probe certifies host activation." + unmet_text(missing))}


def _hook_fact():
    """One sentence when a pre-tool hook of this host recorded a host_probe.py call in this folder moments ago, else ''.

    The receipt is counted by the warm window, the script and the folder, not by the call or the session, so the
    sentence says only that much. No receipt says nothing about hooks. Never raises."""
    try:
        import session_identity
        found = session_identity.resolve(None, "", "host_probe.py")
        if found.get("source") == "receipt":
            return " A pre-tool hook of this host recorded a host_probe.py call in this folder moments ago."
    except Exception:  # noqa: BLE001 - a missing fact is never a reason to fail the refusal
        pass
    return ""


def _not_a_project(root, given=True):
    """The refusal text when `root` is not a factory project, else ''.

    `given` is True when `--root` named the directory, False when the ambient project was taken (OH3-5): before
    onboarding that fallback is the git top, and nothing there may be created or read as a probe.

    `hooklib.require_project` cannot be used: it resolves the ambient project from the
    environment and cwd and ignores the directory this CLI was told to use. The rule it
    enforces is the same: a probe store is never brought into existence under a root that
    onboarding did not make. A legacy operator pointed --root at a story artifact directory and
    got a store the real hooks, which resolve the project by its config.json, never read."""
    from hooklib import CONFIG_PATH_NAME
    resolved = Path(root).resolve()
    if (resolved / "qa-factory" / CONFIG_PATH_NAME).is_file():
        return ""
    # Same marker the hooks use, walked up from the refused directory for the hint.
    above = next((p for p in resolved.parents if (p / "qa-factory" / CONFIG_PATH_NAME).is_file()), None)
    if not given and not above:
        return (f"host_probe: this project is not onboarded yet (no qa-factory/config.json in {resolved} or above "
                "it), so the live guard cannot be probed here: the hooks record the pair only in an onboarded "
                "project. Nothing was written. Report the host hooks as unknown, owner factory, with this fact; "
                "the next step is /qa-factory:qa-onboarding." + _hook_fact())
    fix = (f"Re-run with --root {above}" if above else
           "Re-run with --root set to the project root, or leave --root out when you run it from "
           "inside the project; for a project that is not onboarded yet run /qa-factory:qa-onboarding first")
    return (f"host_probe: no qa-factory/config.json under {resolved} - refusing to create a probe "
            "store there: the real hooks read the store of a factory project only, so they would "
            "never see it.\n"
            "--root must be the project root: the directory that contains qa-factory/config.json "
            "(not a story folder, and not the qa-factory folder itself). " + fix + ".")


def main():
    import session_identity
    from hooklib import EXIT_NO_PROJECT, project_root
    ap = argparse.ArgumentParser(__doc__)
    ap.add_argument("--root", type=Path)
    ap.add_argument("--session")
    ap.add_argument("--prepare", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--hook", action="store_true")
    args = ap.parse_args()
    if args.hook:
        return 0  # telemetry wrapper records the actual PostToolUse receipt
    root = args.root or project_root()
    # OH3-5: the marker check holds for the ambient root too. After --hook (which touches nothing) and before
    # session_identity.resolve, prepare and inspect: no store, lock or folder may appear under a root onboarding
    # did not make, and no answer may promise a door (--prepare) that cannot open there.
    refusal = _not_a_project(root, given=args.root is not None)
    if refusal:
        print(refusal, file=sys.stderr)
        return EXIT_NO_PROJECT
    if args.prepare:
        # B-410: the session is found by session_identity (an id a person gave, a hook receipt, the host's own
        # variable); with none, nothing is written and the refusal says where it looked and what to do.
        found = session_identity.resolve(None, args.session or "", "host_probe.py")
        if not found["session_id"]:
            print(session_identity.refusal(found, "host_probe.py"), file=sys.stderr)
            return 1
        try:
            result = dict(prepare(root, found["session_id"]), identity_source=found["source"])
        except StateConflict:
            # Another writer holds the store (E1): said in words, with the door, never a traceback (FR-1).
            print("host_probe: the probe store is busy, run --prepare again", file=sys.stderr)
            return 1
    else:
        result = inspect(root)
    # Added keys only (FR-14): which root and which store this answer is about, so an operator
    # who passed the wrong --root can see it in the output instead of in a missing receipt.
    result = dict(result, root=str(Path(root).resolve()),
                  store=str((Path(root) / "qa-factory/state/host-probe.json").resolve()))
    print(json.dumps(result, indent=2))
    return 0 if args.prepare or result["status"] == "verified" else 2


if __name__ == "__main__":
    raise SystemExit(main())
