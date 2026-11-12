"""SubagentStop hook: record the moment a subagent hands off (basis of mechanism 5).

Writes a subagent_stop event with a timestamp. The actual "edits after handoff"
detection happens post-hoc in audit_factory.py: artifact file mtimes are compared
against the last subagent_stop/accepted for that task.

It also tells the CONTROLLER that the role came back. On TP1-15045 a role started,
stopped on a refusal, and nothing recorded its return: the dispatch stayed `running`, `next`
answered `wait_existing_job` for the rest of the story, `recover` changed nothing, and the
person's "it's dead, go on" freed nothing. The journal held a `subagent_stop` of that very
role the whole time — the fact was there and nobody was told. `record_return` is the telling:
a FACT ("this role stopped"), never a decision about whether its work is good.

Except for a dispatch a `story_step bind` receipt owns: there the stop only journals, and
`story_step finish` tells the controller (`story_step_receipt`).
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from hooklib import (read_event, project_root, state_dir, is_seeded,
                     subagent_type, artifacts_dir, read_json)
from exit_gate import _existing, _identity, UNKNOWN_DISPATCH


DIGEST_CHARS = 2000
# The EVENT's own ids that `exit_gate._identity` falls back to when no `dispatch_id` is sent (the order there
# is dispatch_id, agent_id, session_id). They name the host's thread or agent, never a dispatch of a story.
HOST_ID_FIELDS = ("agent_id", "session_id")


def _digest(event: dict) -> str:
    """The role's closing words, as the host happened to hand them over. Best effort: the
    controller's `resolve_return` reads better with them and works without them."""
    for key in ("digest", "result", "last_message", "final_message", "response"):
        value = (event or {}).get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:DIGEST_CHARS]
    try:
        transcript = Path(str((event or {}).get("transcript_path") or ""))
        if not transcript.is_file():
            return ""
        last = ""
        with transcript.open(encoding="utf-8", errors="replace") as handle:
            for line in handle:
                try:
                    record = json.loads(line)
                except Exception:
                    continue
                message = record.get("message") if isinstance(record, dict) else None
                if not isinstance(message, dict) or message.get("role") != "assistant":
                    continue
                content = message.get("content")
                if isinstance(content, str):
                    last = content
                elif isinstance(content, list):
                    text = " ".join(str(part.get("text") or "") for part in content
                                    if isinstance(part, dict) and part.get("type") == "text")
                    last = text or last
        return last.strip()[:DIGEST_CHARS]
    except Exception:
        return ""


def _dispatch_id(event: dict, scope: dict) -> str:
    """The dispatch this role was running, from the receipt scope, else from the prompt the
    host still carries, else from `hooklib.subagent_meta` once P4 ships it.

    The scope's `dispatch` is `exit_gate._identity`'s `dispatch_id or agent_id or session_id`: with no
    `dispatch_id` on the event it is the HOST's id (a Codex thread id, a Claude `agent_id`), which no
    controller dispatch is keyed by. Such a value is no dispatch of the story - it is skipped, so nobody is
    named an owner for a stop nobody could tell, and a Claude stop with no receipt reaches the two
    fallbacks below (the TP1-15045 remedy). A stop that carries a real `dispatch_id` is unchanged."""
    event = event or {}
    recorded = str((scope or {}).get("dispatch") or "").strip()
    host_ids = {str(event.get(key) or "").strip() for key in HOST_ID_FIELDS} - {""}
    if recorded == UNKNOWN_DISPATCH or (not event.get("dispatch_id") and recorded in host_ids):
        recorded = ""
    if recorded:
        return recorded
    try:
        import hooklib
        meta = getattr(hooklib, "subagent_meta", None)
        if meta is not None:
            found = meta(Path(str((event or {}).get("transcript_path") or "")))
            if isinstance(found, dict) and found.get("dispatch_id"):
                return str(found["dispatch_id"])
    except Exception:
        pass
    haystack = " ".join(str((event or {}).get(k) or "")
                        for k in ("prompt", "description", "first_prompt"))
    import re
    hit = re.search(r"Dispatch id:\s*([^\s\"']+)", haystack)
    return hit.group(1) if hit else ""


def _story_dispatch(event: dict, scope: dict) -> str:
    """The dispatch id of this stop, or "" when the stop names no story or no dispatch of it (a host id
    alone is none, see `_dispatch_id`): the one condition under which the controller can be told anything
    (`record_return` and the journal's `return_owner` both stand on it). `main` computes it ONCE per stop
    and hands it down; the functions below compute it themselves only when called without it."""
    task = str((scope or {}).get("task") or "").strip()
    if not task or task == "unknown-task":
        return ""
    import hooklib
    if not hooklib.is_one_component(task):
        return ""      # an exploration id (`explore:<slug>`) is no story folder: no controller dispatch, no `return_owner` (XT1-2)
    return _dispatch_id(event, scope)


def story_step_receipt(event: dict, scope: dict, dispatch: str | None = None) -> str:
    """File name of the story_step receipt that owns this dispatch, or "" when none does.

    TP2-2406 S5-7 / S5-8 (20.10.2026, Codex Desktop): the native child's per-turn stop fires
    while the role is still working on the same thread, and this hook told the controller the
    dispatch had RETURNED 97 s before the role called `run_suite`, which then refused with "no
    active S5-qa-automator-7 dispatch". A dispatch bound by `story_step bind` is returned to the
    controller by `story_step finish` alone (`host_dispatch.enrich` and `record` say the same for the
    receipt), so a stop that finds such a receipt - running or already terminal - only journals.

    The receipt `event["host_binding"]` names decides ONLY when it is a story_step receipt. On the
    live host two receipts coexist for one dispatch - the one `host_dispatch.record` writes at spawn,
    keyed by the child's thread id (no `bound_by`), and the one `story_step bind` writes, keyed by its
    path - and `enrich` finds the thread-id one first; so every other answer (a readable receipt of
    another writer, an unreadable one, none) falls through to the receipt directory, searched
    by task AND dispatch id as `story_step._release_binding` matches it - never by role, which would
    let a previous window's receipt shadow this dispatch, and never a dispatch guessed from a receipt
    (an unknown dispatch id matches nothing). The directory is read through `host_dispatch.receipt_files`
    (AR-13, axis 20: the one scanner of the receipts; a receipt that cannot be read is left out there), and
    the NAME of the child is never compared here: `enrich` resolved it through `host_dispatch.binding_names`
    into `host_binding` before this hook ran, under whatever spelling the host used (`/root/<name>`, `<name>`,
    a thread id). `dispatch` is the stop's dispatch id when the caller already resolved it (`main`, once).
    Never raises: an unreadable answer is "no owner", which is today's path."""
    try:
        from host_dispatch import receipt_files
        named = str((event or {}).get("host_binding") or "")
        if named:
            receipt = read_json(named, {}, kind=dict, errors=Exception)
            if receipt.get("bound_by") == "story_step":
                return Path(named).name
        task = str((scope or {}).get("task") or "").strip()
        if dispatch is None:
            dispatch = _story_dispatch(event, scope)
        if not dispatch:
            return ""
        for path, receipt in receipt_files(project_root(event)):
            if (receipt.get("bound_by") == "story_step"
                    and receipt.get("task_id") == task and receipt.get("dispatch_id") == dispatch):
                return path.name
    except Exception:
        pass
    return ""


def record_return(event: dict, record: dict, scope: dict, dispatch: str | None = None) -> None:
    """Journal the return with the controller. Guarded end to end: a SubagentStop hook that
    raises would block the role from stopping, and nothing here is worth that. `dispatch` is the
    stop's dispatch id when `main` already resolved it."""
    try:
        task = str((scope or {}).get("task") or "").strip()
        if dispatch is None:
            dispatch = _story_dispatch(event, scope)
        if not dispatch:
            return
        from controller import Controller
        from event_store import LIFECYCLE_WAIT_SECONDS
        # With parallel windows a sibling's commit holds the story lock for a moment: the return waits for it instead of being
        # lost. The wait is bounded, not short: `Controller.record_return` tries 3 times, each up to 10 s (the lock wait) plus
        # 0.2 s x attempt of sleep: 31.2 s worst case. hooks.json sets no timeout, so the host's own default applies (not measured).
        handler = getattr(Controller(artifacts_dir(task, event), wait_seconds=LIFECYCLE_WAIT_SECONDS), "record_return", None)
        if handler is None:
            return  # a build without it behaves exactly as before
        if handler(dispatch, _digest(event), record.get("agent") or "") is False:
            # `record_return` never raises: a busy lock after its tries, and a dispatch no longer running, both answer False.
            # The `subagent_stop` row is already in the journal (`dispatch_liveness` recovers from it); say so on stderr.
            print(f"subagent_journal: the return of {dispatch} was not recorded with the controller (busy lock, or the "
                  "dispatch is no longer running); the journal row stays for dispatch_liveness", file=sys.stderr)
    except Exception as exc:
        # Still swallowed (a stop hook must not raise), but not silently: one line in the hook's log (stderr).
        try:
            print(f"subagent_journal: the return of {dispatch or '?'} was not recorded with the controller: "
                  f"{type(exc).__name__}: {exc}", file=sys.stderr)
        except Exception:
            pass


def main() -> None:
    event = read_event() or {}
    from host_probe import is_probe_child
    if is_probe_child(project_root(event), event):
        # The doctor's context probe dispatches a role with no story behind it. exit_gate.py already lets it through
        # (the same predicate); journaled, it became a `subagent_stop` of `unknown-task` at the head of a real story's journal.
        sys.exit(0)
    agent = subagent_type(event)
    if not agent:
        # a harness service request with no agent type — not a subagent handoff, not journaled
        sys.exit(0)
    if not (state_dir(event) / "config.json").exists():
        sys.exit(0)  # project not onboarded — no journal to write into, no output
    record = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "event": "subagent_stop",
        "agent": agent,
        "session": event.get("session_id", ""),
    }
    key, scope = _identity(event, agent.rpartition(":")[2])
    gate = _existing(key)
    record.update({k: scope[k] for k in ("task", "dispatch", "attempt", "hook", "input_fingerprint")})
    # A released Stop turn is not acceptance. Consumers can require status=completed
    # rather than inferring success from the mere presence of subagent_stop.
    # RH1-5 N3: a receipt `unreadable` (the gate could not decide) is NOT a completion: it reads as `incomplete`
    # (a closed set whose reader falls to the pass side is the silent pass FR-59 names)
    record["status"] = ("incomplete" if gate.get("status") in {"blocked", "incomplete", "unreadable"}
                        else "awaiting_human" if gate.get("status") == "awaiting_human" else "completed")
    if record["status"] == "incomplete":
        record["gate_receipt"] = key
    if is_seeded():
        record["seeded"] = True
    # Who tells the controller this role came back: `story_step finish` for a bound dispatch, this
    # hook for every other one (the trail reads it from the journal line, not from the controller).
    # `return_owner` is written only when a dispatch of the story was resolved (a host id alone is none):
    # with none, `record_return` bails and no one is told, so naming an owner would overclaim. The
    # receipt travels as `dispatch_receipt` (a file name of `state/host-dispatches/`; the PreToolUse
    # receipts of `state/host-receipts/` are another artifact); `host_binding` on the hook event is a
    # full path, so that key is not reused. Both new keys are trail: no code reads them.
    dispatch = _story_dispatch(event, scope)
    owner = story_step_receipt(event, scope, dispatch)
    if dispatch:
        record["return_owner"] = "story_step" if owner else "subagent_stop"
    if owner:
        record["dispatch_receipt"] = owner
    import hooklib
    hooklib.append_journal_line(event, record)      # N8: the ONE journal-line writer (the record's own `ts` is kept)
    if not owner:
        record_return(event, record, scope, dispatch)
    sys.exit(0)


if __name__ == "__main__":
    main()
