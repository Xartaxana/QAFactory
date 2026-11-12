#!/usr/bin/env python3
"""Stop hook of the conductor's session: wake the conductor about a role that has already returned (HF8-15 (1b)).

Run 12586 stopped because the conductor ended its turn on "waiting" for a critic that had handed its report back: the
host's end-of-turn notice reached nobody, the receipt of the dispatch stayed `running` until `story_step finish`, and
no code moved. The question "has it returned?" is already answered by the host's own record (`dispatch_liveness`:
the role's transcript ends with the handback call and the host's acknowledgement, and the stop hooks have let it go).
This hook asks it ONCE when the conductor's session ends a turn, and when the answer is RETURNED it refuses the end
of the turn one time, naming the dispatch and the move (`story_step.py finish`, or `--needs-author`).

What it does NOT do (P1, P22): it never reads the conductor's words ("waiting" is not read, FR-12); it says nothing
for ALIVE or for an unknown (a conductor that ends a turn over an unknown is not disturbed); it never blocks twice
for the same return (a key `(session, dispatch, last_at)` in `state/conductor-stop.json`, and the host's own
`stop_hook_active`), so a person's question is delayed by one turn of the conductor and never locked out.

POSITION of the checks, cheapest first (AR-12: this runs at every Stop of every session): the driver's mode and the
host's markers answer before anything is read; then the receipts of the project (one small folder); transcripts are
read ONLY for a receipt that is this session's, non-terminal, bound by `story_step`, and whose dispatch the
controller still calls `running`. INVARIANT: a receipt of another session is never woken for (a parallel story's
conductor does not get another's work, E11), and an unknown is never RETURNED (AR-28): every failure to read is exit 0.

Every exception is exit 0 and one `gate_unreadable` signal of the journal (FR-59): a hook must not block on its own
defect. A host with no handback form (Codex; `hooks/codex.json` does not carry this hook) answers nothing.
"""
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# The variable the driver exports (`launch_card.RUN_MODE_ENV`; `story_step.current_run_mode` reads it). NAMED here, not
# imported: `launch_card` pulls the liveness and lifecycle modules in, and this runs at every Stop (AR-12, E15). The
# value is pinned equal to the definition by `test_conductor_stop.py`.
RUN_MODE_ENV = "QA_FACTORY_RUN_MODE"
DRIVER_MODE = "driver"
FUSE_FILE = "conductor-stop.json"


def _running(root, task, dispatch) -> bool:
    """True ONLY when the story's controller records this dispatch as `running`. Every doubt is False (a conductor is
    never woken for what the controller does not call running): no folder, no record, no status, a ticket that is not
    one path component. The reader of the controller's record is `worker_lifecycle.binding_is_active`, which answers
    True on every doubt - the wrong direction for a wake-up - so this is the strict twin of that one question."""
    from host_dispatch import controller_record
    record = controller_record(root, task, dispatch)
    return record is not None and record.get("status") == "running"


def _returned(root, session_transcript, now) -> list:
    """`[(task, dispatch, last_at, first evidence line)]` of the dispatches of THIS session whose roles the host's own
    record says have returned. A dispatch is asked about with EVERY non-terminal receipt it has (`_native_verdict`:
    RETURNED needs each of them, so a second living receipt keeps the conductor asleep)."""
    import host_adapter
    from host_dispatch import binding_names, receipt_files
    receipts = [data for _path, data in receipt_files(root)]
    open_ = [r for r in receipts if r.get("bound_by") == "story_step" and r.get("status") != "terminal"
             and r.get("task_id") and r.get("dispatch_id") and isinstance(r.get("agent_id"), str)
             and not r["agent_id"].startswith("/")]
    if not open_:
        return []                                   # E9: nothing bound - no transcript is read
    keys = []
    for receipt in open_:
        key = (str(receipt["task_id"]), str(receipt["dispatch_id"]))
        if key not in keys and host_adapter.subagent_transcript_of(session_transcript, binding_names(receipt)):
            keys.append(key)                        # E11: only the receipts whose agent lives in THIS session
    found = []
    if not keys:
        return found
    import dispatch_liveness as DL
    limits, held = DL.thresholds(root), {}
    for task, dispatch in keys:
        if not _running(root, task, dispatch):
            continue
        waiting = [r for r in open_ if (str(r["task_id"]), str(r["dispatch_id"])) == (task, dispatch)]
        verdict, _notes = DL._native_verdict(root, waiting, now, limits, held)
        if isinstance(verdict, dict) and verdict.get("state") == DL.RETURNED:
            evidence = [line for line in verdict.get("evidence") or [] if isinstance(line, str) and line.strip()]
            found.append((task, dispatch, verdict.get("last_at"), evidence[0].strip() if evidence else "the host's record"))
    return found


def _fresh(path: Path, session: str, returned: list) -> list:
    """The returns not woken for yet. A fuse file that cannot be read is empty (one block, E14)."""
    import hooklib
    fuse = hooklib.read_json(path, {}, kind=dict, errors=Exception)
    return [item for item in returned if f"{session}|{item[0]}|{item[1]}|{item[2]}" not in fuse]


def _remember(path: Path, session: str, items: list) -> bool:
    """Write the keys of the returns woken for; False when the file cannot be written - then NO block is made (E14:
    better no alarm than a loop)."""
    import hooklib
    from event_store import atomic_json
    try:
        fuse = hooklib.read_json(path, {}, kind=dict, errors=Exception)
        for task, dispatch, last_at, _line in items:
            fuse[f"{session}|{task}|{dispatch}|{last_at}"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        atomic_json(path, fuse)
        return True
    except Exception:  # noqa: BLE001 - an unwritable fuse means no block
        return False


def wake_text(items: list) -> str:
    """ONE text for every returned dispatch of the turn (E10)."""
    lines = []
    for task, dispatch, _last_at, evidence in items:
        lines.append(f"{dispatch} has returned ({evidence}): it is not busy. Take it: "
                     f"`story_step.py finish --task {task} --dispatch-id {dispatch} --digest -`, or `--needs-author`.")
    return "\n".join(lines)


def decide(event, now=None) -> tuple:
    """`(exit code, text for stderr)`: 2 and the wake text at most once per returned dispatch, else 0 and nothing."""
    if os.environ.get(RUN_MODE_ENV, "").strip() == DRIVER_MODE:
        return 0, ""                                # E15: the driver has its own turn
    if not isinstance(event, dict) or event.get("stop_hook_active"):
        return 0, ""                                # E6: the host is already handling a forced return
    import host_adapter
    if host_adapter.is_codex(event):
        return 0, ""
    transcript = event.get("transcript_path")
    if not isinstance(transcript, str) or not transcript.strip():
        return 0, ""
    import session_identity
    session = session_identity.resolve(event, "", "conductor_stop.py").get("session_id") or ""
    if not session:
        return 0, ""                                # no session, no receipt that is "hers": silence (AR-28)
    import hooklib
    root = hooklib.project_root(event)
    returned = _returned(root, transcript, time.time() if now is None else now)
    if not returned:
        return 0, ""
    path = root / "qa-factory" / "state" / FUSE_FILE
    fresh = _fresh(path, session, returned)
    if not fresh or not _remember(path, session, fresh):
        return 0, ""
    return 2, wake_text(fresh)


def main() -> None:
    import hooklib
    hooklib.run_stop_hook(decide, "conductor_stop",
                          "conductor_stop: unreadable - the wake-up check crashed ({exc}) - the factory's own defect; "
                          "a returned role may wait unnoticed: ask `story_step.py where`")


if __name__ == "__main__":
    main()
