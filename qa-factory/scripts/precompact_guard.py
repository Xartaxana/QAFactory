# -*- coding: utf-8 -*-
"""Compact guard (PreCompact): knowledge does not live in the chat — before the
context is compacted the carriers must be fresh, even mid-flow.

What it does:
0. Before anything else, and even with no config: when an onboarding run is open (its notes are in
   `qa-factory/state/onboarding/`, see onboarding_notes.py) it prints one line for the person saying
   where the notes are. It creates nothing and writes no journal without a config.
1. Writes a `compact` event (trigger: manual/auto) into the journal — the
   "a compact happened here" trace is visible to the next session and the audit.
2. Prints the carrier checklist: obligations / the strategy documents /
   factory-backlog / the metrics board / the pipeline.json checkpoint — the
   orchestrator must refresh them BEFORE the compact (the qa-story iron law);
   mid-phase — at minimum a pipeline.json checkpoint with "where we are and
   what's next" notes.
Never blocks (exit 0): compacting is the user's right; the guard makes
forgetting visible.
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hooklib import project_root, state_dir, read_event, load_config, is_seeded
import runtime_paths as RP


def main() -> None:
    event = read_event() or {}
    trigger = str(event.get("trigger", "unknown"))
    session = str(event.get("session_id", "unknown"))
    # An onboarding that is still running keeps its notes on disk (B-411); say so BEFORE the config exit,
    # because a first onboarding has no config yet and its notes are the only thing a compaction would
    # otherwise cost. The hook only prints: it creates nothing, and with no run it says nothing.
    line = onboarding_line(event)
    if line:
        print(line)
    if not (state_dir(event) / "config.json").exists():
        sys.exit(0)  # project not onboarded — nothing to checkpoint, no output
    try:
        journal = RP.configured(project_root(event), load_config(event).get("journal_path"), "journal.jsonl")
        journal.parent.mkdir(parents=True, exist_ok=True)
        rec = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "event": "compact",
            "agent": "precompact_guard",
            "notes": f"context compact (trigger: {trigger}); carrier checklist printed",
            "session": session,
        }
        if is_seeded():
            rec["seeded"] = True
        with journal.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass
    print(
        "COMPACT GUARD: preserve unfinished work in its current-stage artifacts before compacting.\n"
        "1) Record new obligations with evidence; do not repeat completed work.\n"
        "2) Keep strategy proposals for the authorized S9 fold; honor exact-file edit grants.\n"
        "3) Record new DD/FB items through project_decisions.py, without rewriting the registry.\n"
        "4) Metrics are derived by code from accepted artifacts; do not author a metrics board.\n"
        "5) Checkpoint the active controller dispatch and artifacts/<task>/pipeline.json; record next action.\n"
        + boundary_line(event) +
        "The check: 'what of this work will the next session NOT see in the files?' — the answer must be 'nothing'."
    )
    sys.exit(0)


def onboarding_line(event: dict | None) -> str:
    """The one line about an unfinished onboarding, written for the PERSON: PreCompact output is shown in
    the transcript and a compaction cannot be paused by a hook (tools/compact_snapshot.py:1-7), so a
    checklist addressed to the model would never be read by it. "" when no run is open or the check fails
    (a guard never blocks). The path comes from `onboarding_notes.notes_dir` (one function, FR-37)."""
    try:
        import onboarding_notes
        found = onboarding_notes.open_onboarding(project_root(event), event)
        if not found["open"]:
            return ""
        if not found["readable"]:
            return (f"ONBOARDING IN PROGRESS: an onboarding folder is at {found['path']}, but its progress file cannot "
                    f"be read ({'; '.join(found['problem'])}); after the compaction the onboarding says what it can "
                    "still use.")
        return (f"ONBOARDING IN PROGRESS: what this onboarding found and was told up to now is saved at {found['path']} "
                f"(phase {found['phase']}, {len(found['answered'])} topics answered, {len(found['awaiting_reply'])} "
                "batches awaiting a reply); after the compaction it resumes from there.")
    except Exception:
        return ""


def boundary_line(event: dict | None) -> str:
    """One extra checklist line when this compact is NOT at a stage boundary.

    A window may change at a closed stage and nowhere else (the owner's decision of 21.09,
    after TP1-15045 ended a window one step before gate A). A compact in the middle of
    a stage is not forbidden — compacting is the person's right and this guard has never
    blocked one — but the next window then reopens a stage whose dispatch is still running,
    so it is worth saying out loud which one."""
    try:
        import window_budget
        work = window_budget.open_work(state_dir(event))
    except Exception:
        return ""
    if not work.get("stage") and not work.get("dispatches"):
        return ""
    open_bits = []
    if work.get("stage"):
        open_bits.append(f"{work['stage']} is still running")
    if work.get("dispatches"):
        open_bits.append("open dispatch(es): " + ", ".join(work["dispatches"]))
    return (f"6) NOT a stage boundary: {work.get('task') or 'this story'} — "
            + "; ".join(open_bits) +
            ". The compact still proceeds (it is yours to make); afterwards re-read "
            "pipeline.json and the phase file. The cheap place to change a window is right "
            "after `stage_done.py --status done`.\n")


if __name__ == "__main__":
    main()
