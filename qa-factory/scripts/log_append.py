"""The factory's event journal with format validation (mechanism 7). The single write point.

Usage (the orchestrator, on every dispatch/acceptance/skip):
    log_append.py --event delegated --agent qa-runner --task TASK-101 [--notes "..."] [--field key=value ...]  (via run-py.cmd)

A person's reason goes by file, whole: `--reason-file <path>` (instead of `--reason`; read by `person_words.read`).

In a batch (several events in one call - cheaper, see below):
    log_append.py --batch events.json
    log_append.py --batch -     # the same JSON array on stdin

`--batch` takes an ARRAY of objects with the same field names (`event`, `agent`, `task`, ...;
extra fields go in a nested `fields` object). Validation runs over ALL elements at once, and
the write either lands whole or does not land at all: a half-written batch is worse than an
unwritten one - you cannot reconstruct what happened from it.

Why a batch. Every tool call is a separate model request, and a request pays for the WHOLE
orchestrator context again. Measured on the 09.09 run: 35 separate calls of this script at an
average context of 247K tokens = $1.73 on journal bookkeeping alone. A phase's events pile up
and leave in one call; an event needed RIGHT NOW (a gate block, an escalation) is written on
its own - the journal matters more than the saving.

Mandatory fields per event type (after the pattern of the HQ repo):
    delegated:        agent, task
    accepted:         agent, task, by; for generators (qa-automator) - witness
    rejected:         agent, task, by, failure_class (spec|capability|recon|tooling|env), reason_family
    escalated:        agent, task, reason
    dispatch_skipped: task, reason  ("rejecting is allowed, being invisible is not")
    defect_found:     task, ref (task_id of the original acceptance)
    gate:             task, gate, decision
    calibrated:       notes (the outcome of a calibration run)
    subagent_stop:    agent (written by the hook)
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from hooklib import project_root, load_config, is_seeded, require_project
import runtime_paths as RP

EVENTS = {
    "delegated": ["agent", "task"],
    "accepted": ["agent", "task", "by"],
    "rejected": ["agent", "task", "by", "failure_class", "reason_family"],
    "escalated": ["agent", "task", "reason"],
    "dispatch_skipped": ["task", "reason"],
    "defect_found": ["task", "ref"],
    "gate": ["task", "gate", "decision"],
    "calibrated": ["notes"],
    "subagent_stop": ["agent"],
    "unsafe_completion": ["agent", "notes"],
    "gate_block": ["agent", "notes"],
    "compact": ["notes"],
    # Added with the two-gate pipeline (C2 seams): the sanctioned write points for the
    # decisions stage_guard and check_delivery read back.
    "deliver_with_risks": ["task", "reason"],
    "external_write": ["task", "ref"],
    "halt": ["task", "reason"],
    "human_answer": ["task", "notes"],
    # A person asked to stop showing a story on the board (archive_task.py). Never a role:
    # until 0.3.0 S9 set the flag on its own inference and that is what sent the factory
    # walking an epic for sibling tickets.
    "archived": ["task", "notes"],
    # The ticket moved while the story ran (s0.md 2b): severity + the fields that changed.
    "ticket_changed": ["task", "notes"],
    # The freshness check could NOT read the tracker (ticket_adapter.py freshness exited 1 or 3):
    # the ticket is neither changed nor unchanged, and calling it either would report an unknown
    # as a fact (FR-41). notes = the reason. Written by the skill-path caller of freshness, at most once per 6 hours.
    "ticket_unchecked": ["task", "notes"],
    # exit_gate.py released a turn whose handoff stayed unresolved (active Stop re-entry, or
    # the persisted fuse on repeated unchanged input). Written by journal_gate like
    # gate_block and unsafe_completion, so it carries the same required pair. It was missing
    # from this vocabulary while exit_gate.py wrote it, which made A6 report an "unknown
    # event" that no person could ever fix: the factory itself was the author.
    "handoff_incomplete": ["agent", "notes"],
    # hooklib.person_signal (RH1-5): a default the factory took without a person (a guard that crashed and allowed, a
    # gate that could not run, a notice for the person). `kind` says which; the run report counts them. Missing here,
    # A6 would report every one of them as an "unknown event" (RH1-5 fix round, N2).
    "hook_signal": ["agent", "kind", "notes"],
    # exit_gate.py again, same required pair. `gate_recheck_passed`: the re-entry after a
    # block found the artifacts repaired. `gate_override`: a block was passed by a person's
    # word (`stage_overrides[]`). `awaiting_human`: the scout stopped with every source
    # assessed so that the person can review them — S1 is not closed by it.
    "gate_recheck_passed": ["agent", "notes"],
    "gate_override": ["agent", "notes"],
    "awaiting_human": ["agent", "notes"],
    # migrate_artifacts.py --if-older, once per resume on a newer plugin: the
    # story's artifacts were rewritten to the current spelling by code, never by a person, and
    # a resume that finds nothing older writes no line at all — this event exists so the one
    # rewrite that DID happen is not a silent diff.
    "artifacts_migrated": ["task", "notes"],
}
FAILURE_CLASSES = {"spec", "capability", "recon", "tooling", "env"}
# The reject reason family - a short stable label ("the case cannot fail through the path it
# names", "the oracle is not anchored"). The list is NOT closed: families are born of practice
# and closed by calibration. The class answers "whose fault", the family "what exactly is
# wrong"; without it the journal yields only a count of rejects, and the reasons have to be dug
# out of artifacts by hand (measured 09.09: two rejects with class spec and an empty reason).
REASON_FAMILY_MIN, REASON_FAMILY_MAX = 10, 120
WITNESS_REQUIRED_AGENTS = {"qa-automator"}
FIELDS = ("agent", "task", "by", "reason", "ref", "gate", "decision",
          "failure_class", "reason_family", "witness", "notes")


def build_record(spec: dict) -> dict:
    """An event spec (from the arguments or from a batch element) -> a journal record."""
    record = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "event": str(spec.get("event", ""))}
    if spec.get("seeded") or is_seeded():
        record["seeded"] = True
    for key in FIELDS:
        val = spec.get(key)
        if val:
            record[key] = val
    extra = spec.get("fields") or {}
    if isinstance(extra, dict):
        record.update(extra)
    return record


def validate(record: dict) -> list:
    """A list of format violations; an empty list means the record is good."""
    event = record.get("event", "")
    if event not in EVENTS:
        return [f"unknown event '{event}' (allowed: {', '.join(sorted(EVENTS))})"]
    errors = [f"event '{event}' requires field '{f}'" for f in EVENTS[event] if not record.get(f)]
    if "," in str(record.get("task", "")):
        errors.append("a compound task ('A,B') is forbidden - one event per task, otherwise the machine reconciliation of delegated<->accepted pairs breaks (calibration finding C-2)")
    if event == "rejected":
        if record.get("failure_class") not in FAILURE_CLASSES:
            errors.append(f"failure_class '{record.get('failure_class')}' outside {sorted(FAILURE_CLASSES)}")
        fam = str(record.get("reason_family", "")).strip()
        if fam and not (REASON_FAMILY_MIN <= len(fam) <= REASON_FAMILY_MAX):
            errors.append(f"reason_family is {len(fam)} chars, outside {REASON_FAMILY_MIN}..{REASON_FAMILY_MAX}: a label, not a paragraph and not a placeholder")
        if fam and fam.lower() == str(record.get("failure_class", "")).lower():
            errors.append("reason_family repeats failure_class - the class answers \"whose fault\", the family \"what exactly is wrong\"")
    if event == "accepted" and record.get("agent") in WITNESS_REQUIRED_AGENTS and len(str(record.get("witness", ""))) < 30:
        errors.append(f"accepted for {record.get('agent')} requires a witness (verbatim run output, >=30 chars)")
    return errors


def load_batch(src: str) -> list:
    raw = sys.stdin.read() if src == "-" else Path(src).read_text(encoding="utf-8")
    data = json.loads(raw)
    if not isinstance(data, list):
        raise ValueError("--batch expects a JSON ARRAY of event objects")
    if not data:
        raise ValueError("--batch got an empty array - there is nothing to write")
    for item in data:
        if not isinstance(item, dict):
            raise ValueError("a batch element must be an object with an 'event' field")
    return data


def write(records: list) -> None:
    require_project("log_append")
    journal = RP.configured(project_root(), load_config().get("journal_path"), "journal.jsonl")
    journal.parent.mkdir(parents=True, exist_ok=True)
    import os
    from event_store import EventStore
    # Separate project lock: different task writers share this projection. The lock is machine-local,
    # so it lives in `state/` whichever folder the journal is in (the journal is a tracked record).
    with EventStore(RP.state_file(project_root(), ".journal-writer")).lock():
        existing = set()
        if journal.exists():
            for line in journal.read_text(encoding="utf-8").splitlines():
                try:
                    record = json.loads(line)
                    if record.get("source_event_id"):
                        existing.add(record["source_event_id"])
                except ValueError:
                    raise ValueError("shared journal is corrupt; repair before append")
        records = [r for r in records if not r.get("source_event_id") or r["source_event_id"] not in existing]
        with journal.open("a", encoding="utf-8") as f:
            f.write("".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records))
            f.flush()
            os.fsync(f.fileno())
    events = ", ".join(r["event"] for r in records)
    print(f"OK: {len(records)} event(s) ({events}) written to {journal.name}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--event", choices=sorted(EVENTS))
    ap.add_argument("--batch", default="", help="path to a JSON array of events, or '-' for stdin")
    ap.add_argument("--agent", default="")
    ap.add_argument("--task", default="")
    ap.add_argument("--by", default="")
    ap.add_argument("--reason", default="")
    ap.add_argument("--reason-file", dest="reason_file", default=None,
                    help="the reason as a file (UTF-8), read whole by person_words.read; instead of --reason. A person's reason goes "
                         "this way: a command line cuts a multi-line text at the first line break")
    ap.add_argument("--ref", default="")
    ap.add_argument("--gate", default="")
    ap.add_argument("--decision", default="")
    ap.add_argument("--failure-class", dest="failure_class", default="")
    ap.add_argument("--reason-family", dest="reason_family", default="",
                    help="reject reason family: a short stable label; for a role with a rubric, name the failed dimension")
    ap.add_argument("--witness", default="")
    ap.add_argument("--notes", default="")
    ap.add_argument("--field", action="append", default=[], help="extra fields key=value")
    ap.add_argument("--seeded", action="store_true", help="a test/training event (not a live incident)")
    args = ap.parse_args()

    if args.reason_file is not None:
        # HF8-23 (F4): the one reader of a person's words from a file (AR-13); both options at once, a missing, empty or non-UTF-8 file are
        # refused by it with the way out. Only the file form goes through it: an inline `--reason` is what it always was (a role's own text).
        import person_words
        try:
            args.reason = person_words.read(args.reason or None, args.reason_file, "--reason", "--reason-file")
        except ValueError as e:
            print(f"JOURNAL: {e}", file=sys.stderr)
            sys.exit(1)
    if bool(args.batch) == bool(args.event):
        print("JOURNAL: needs either --event (one event) or --batch (a batch), not both and not neither.", file=sys.stderr)
        sys.exit(1)

    if args.batch:
        try:
            specs = load_batch(args.batch)
        except Exception as e:
            print(f"JOURNAL: the batch could not be read: {e}", file=sys.stderr)
            sys.exit(1)
        if args.seeded:
            for spec in specs:
                spec["seeded"] = True
    else:
        extra = {}
        for item in args.field:
            k, _, v = item.partition("=")
            extra[k] = v
        specs = [{"event": args.event, "seeded": args.seeded, "fields": extra,
                  **{k: getattr(args, k) for k in FIELDS}}]

    records = [build_record(s) for s in specs]
    problems = []
    for n, record in enumerate(records, 1):
        for err in validate(record):
            problems.append(f"event {n} ({record.get('event') or '?'}): {err}" if len(records) > 1 else err)
    if problems:
        # A batch is written whole or not at all: a half-written journal is worse than none.
        print("JOURNAL: record rejected:\n- " + "\n- ".join(problems), file=sys.stderr)
        sys.exit(1)

    write(records)


if __name__ == "__main__":
    main()
