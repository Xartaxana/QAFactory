#!/usr/bin/env python3
"""RH1-5 B12: the reader of `hook_signal` in the run report (AR-22: `hooklib.person_signal` writes, this reads). K10: N signals
of different kinds are counted and named with the journal path; none recorded; no journal file (none recorded, E21); an
unreadable journal is `unknown` with the reason (E26, FR-41); a broken line is skipped and counted; another story's signal is
not counted; a task-less signal before the history started is not counted; with no start date a task-less row is not taken."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import SCRIPTS, check, check_eq, check_in, cleanup, finish, temp_project  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import report_facts as RF  # noqa: E402
import runtime_paths as RP  # noqa: E402

TASK = "QA-R1"


def sig(kind, task=TASK, ts="2026-10-28T10:00:00+00:00", event="hook_signal"):
    return json.dumps({"ts": ts, "event": event, "agent": "x.py", "kind": kind, "task": task, "session": "s", "notes": "n"})


def run(root: Path, lines, pipeline=None, journal_missing=False, unreadable=False):
    art = root / "qa-factory" / "artifacts" / TASK
    art.mkdir(parents=True, exist_ok=True)
    journal = RP.record(root, "journal.jsonl")
    journal.parent.mkdir(parents=True, exist_ok=True)
    if unreadable:
        journal.unlink(missing_ok=True)
        journal.mkdir()                          # a directory where a file is expected: is_file() False, so use a file we cannot open
        journal.rmdir()
        journal.write_bytes(b"")
    elif journal_missing:
        journal.unlink(missing_ok=True)
    else:
        journal.write_text("\n".join(lines) + "\n", encoding="utf-8")
    unknown = {}
    found = RF._hook_signals(art, root / "qa-factory", pipeline if pipeline is not None else {"created_at": "2026-10-28T09:00:00+00:00"}, unknown)
    return found, unknown


def main() -> None:
    root = temp_project("qa-report-signals-")
    try:
        found, unknown = run(root, [sig("guard_crashed"), sig("guard_crashed"), sig("config"), sig("config", task="QA-OTHER"),
                                    sig("guard_crashed", event="gate_block")])
        check_eq("K10: N signals of this story, by kind (another story's and other events do not count)",
                 (found["count"], found["kinds"]), (3, {"guard_crashed": 2, "config": 1}))
        check_in("K10: the path of the journal is named", "journal.jsonl", found["path"])
        line = RF._r_hook_signals(found, "")
        # HF8-20 (P9): the line is words for a person - the count and where it is kept; the kinds, the journal's path and the event's
        # name stay in `found` (the machine record) and never reach the line
        check_in("K10: the line has the count and says where the signals are kept", "3 signals, kept in the factory's own log", line)
        check("K10: ...and carries neither the kinds, nor the event's name, nor the journal's path",
              not any(word in line for word in ("guard_crashed", "config", "hook_signal", "journal.jsonl")), line)
        found, _u = run(root, [sig("config", task="QA-OTHER")])
        check_eq("K10: none of this story: count 0", found["count"], 0)
        check_in("K10: ...the line says `none recorded`", "none recorded", RF._r_hook_signals(found, ""))
        found, unknown = run(root, [], journal_missing=True)
        check_eq("E21: no journal file: count 0 (an answer, not `unknown`)", (found["count"], unknown), (0, {}))
        # a broken line is skipped and counted
        found, _u = run(root, [sig("config"), "{not json", sig("config")])
        check_eq("a broken line is skipped and counted", (found["count"], found["skipped"]), (2, 1))
        check_in("...and said in the line", "1 line(s) could not be read", RF._r_hook_signals(found, ""))
        # a task-less signal: placed by time
        found, _u = run(root, [sig("config", task="", ts="2026-10-28T08:00:00+00:00"), sig("config", task="", ts="2026-10-28T10:00:00+00:00")])
        check_eq("a task-less signal before the history started is not counted; one after it is", found["count"], 1)
        found, _u = run(root, [sig("config", task="")], pipeline={})
        check_eq("no start date in the pipeline: the task-less row is NOT taken and the line says so",
                 (found["count"], found["no_task_unplaced"]), (0, 1))
        check_in("...the 'none recorded' line says how many could not be placed", "1 signal(s) with no task could not be placed",
                 RF._r_hook_signals(found, ""))
        # N6: a task-less row is bounded by the story's END too; the stamps are compared as INSTANTS, not as texts
        closed = {"created_at": "2026-10-28T09:00:00+00:00", "closed_at": "2026-10-28T12:00:00+00:00",
                  "stages": {"S9": {"started_at": "2026-10-28T12:30:00+00:00"}}}
        rows = [sig("config", task="", ts="2026-10-28T10:00:00+00:00"),     # inside
                sig("config", task="", ts="2026-10-28T12:20:00+00:00"),     # after the close, inside the retro stage's stamp
                sig("config", task="", ts="2026-10-28T14:00:00+00:00"),     # a later story's
                sig("config", task="", ts="2026-10-28T08:00:00+00:00")]     # before
        found, _u = run(root, rows, pipeline=closed)
        check_eq("N6: a task-less row after the story's end is not this story's (inside and the retro tail are)", found["count"], 2)
        found, _u = run(root, rows, pipeline={"created_at": "2026-10-28T09:00:00+00:00"})
        check_eq("N6: an OPEN story has no end (over-report beats loss): 3 rows from the start", found["count"], 3)
        found, _u = run(root, [sig("config", task="", ts="2026-10-28T11:00:00+02:00")], pipeline={"created_at": "2026-10-28T09:30:00Z"})
        check_eq("N6: forms are compared as instants: 11:00+02:00 is 09:00Z, before a 09:30Z start", found["count"], 0)
        found, _u = run(root, [sig("config", task="", ts="2026-10-28T11:00:00+02:00")], pipeline={"created_at": "2026-10-28T08:30:00Z"})
        check_eq("N6: ...and 11:00+02:00 after an 08:30Z start is counted (a string compare would drop it)", found["count"], 1)
        found, _u = run(root, [sig("config", task="", ts="not a time")], pipeline=closed)
        check_eq("N6: a row whose stamp cannot be read is counted, never lost", found["count"], 1)
        found, _u = run(root, [sig("config", task="QA-R1", ts="2027-01-01T00:00:00+00:00")], pipeline=closed)
        check_eq("N6: a row that NAMES the story counts whatever its time", found["count"], 1)
        # N7: one note (same story, same text) said three times (hook, finish, driver) is ONE; two different notes are two
        note = lambda text, task=TASK: json.dumps({"ts": "2026-10-28T10:00:00+00:00", "event": "hook_signal", "agent": "x",
                                                   "kind": "exit_gate_note", "task": task, "session": "", "notes": text})
        found, _u = run(root, [note("a"), note("a"), note("a"), note("b"), note("a", "QA-OTHER")])
        check_eq("N7: three copies of one exit_gate_note count once; a different note counts too", (found["count"], found["kinds"]), (2, {"exit_gate_note": 2}))
        found, _u = run(root, [sig("guard_crashed"), sig("guard_crashed")])
        check_eq("N7 control: other kinds repeat as they happened (two guard_crashed are two)", found["kinds"], {"guard_crashed": 2})
        # E26: the journal cannot be read -> unknown with the reason
        journal = RP.record(root, "journal.jsonl")
        journal.write_text("x", encoding="utf-8")
        real_read = Path.read_text

        def deny(self, *a, **k):
            if self == journal:
                raise PermissionError("locked")
            return real_read(self, *a, **k)
        Path.read_text = deny
        try:
            unknown = {}
            found = RF._hook_signals(root / "qa-factory" / "artifacts" / TASK, root / "qa-factory", {}, unknown)
        finally:
            Path.read_text = real_read
        check_eq("E26: an unreadable journal: count is None, not 0", found["count"], None)
        check_in("E26: ...the reason is kept in unknown['hook_signals']", "PermissionError", unknown.get("hook_signals", ""))
        line = RF._r_hook_signals(found, unknown["hook_signals"])
        check("E26: ...the line says `unknown` with the reason (FR-41)", "unknown - the journal" in line and "PermissionError" in line, line)
        # the block "Where to look" renders it
        facts = {"where": {"files": {}, "retro_skip_words": "", "hook_signals": {"count": 0, "kinds": {}, "path": "p", "skipped": 0, "no_task_unplaced": 0}},
                 "unknown": {}}
        check_in("the block `Where to look` carries the line", "the factory's own signals during this run: none recorded", RF._r_where(facts))
    finally:
        cleanup(root)
    finish("test_report_hook_signals")


if __name__ == "__main__":
    main()
