#!/usr/bin/env python3
"""TR4-11 (t-2222 items 11.1 and 11.2, part B1): the person's stop is a record, and the driver's journal goes through the one appender.

Expectations are the spec's (docs/tasks/specs/t-2222-tr4-10-11-s5-windows-leftovers.md items 11.1, 11.2) and the plan critic's F-1, F-3, F-8
(docs/tasks/specs/reviews/t-2227-tr4-10-11-plan-critic.md), not what the code prints (FR-58).

11.1  Ctrl-C on either road of `Driver.run` writes ONE `stopped_by_person` row to driver-runs.jsonl through `journal_run`, with
      `since` (the process start) and `cut` (the calls this process launched and saw no end for); the interrupt is re-raised.
      No story folder -> nothing written; a failed write -> one note, still re-raised; a second Ctrl-C while writing -> no traceback past
      `run`, a record already written is kept; an interrupt inside a run-level handler (funnel) writes it too (F-3).
      `collect_stall` clears exactly the rows in `cut` (round trip with a real `Driver`; the id form is a twin of K3's, tied here).
11.2  `_append_jsonl` is `hooklib.append_jsonl_line`: a torn tail is repaired, no private `open(..., "a")` is left in the driver set,
      a journal of mixed CRLF / LF lines (the Windows text-mode rows of before) is read whole by every reader of the file (F-8).

Nothing here reaches the network, a model or a subprocess.

Run:  python -B scripts/tests/test_driver_stop_record.py
"""
import contextlib
import io
import json
import re
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import SCRIPTS, check, check_eq, cleanup, finish, temp_dir  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import collect_stall as CS  # noqa: E402
import driver_journal as DJ  # noqa: E402
import story_run as SR  # noqa: E402

NAME = "driver-runs.jsonl"


def rig(root: Path, with_state_dir: bool = True):
    """A bare Driver whose `run` can be driven: every step before the loop is a no-op, the loop asks `where` and `boundary_step`."""
    d = SR.Driver.__new__(SR.Driver)
    d.task = "QA-STOP"
    d.task_root = root / "artifacts" / "QA-STOP"
    d.state_dir = d.task_root / "state"
    d.task_root.mkdir(parents=True)
    (d.task_root / "pipeline.json").write_text("{}", encoding="utf-8")
    if with_state_dir:
        d.state_dir.mkdir()
    d.state, d.flags, d.answer_kind, d.max_boundaries, d.until = {}, SimpleNamespace(answer=None), None, 3, None
    d.progress_line = lambda: None
    d.reconcile_question = lambda: None
    for name in ("owed_rows_step", "adopt_legacy_snapshot", "check_run_mode", "report_gap_class_problem", "skip_sources_late",
                 "ticket_freshness_entry", "accept_no_trace"):
        setattr(d, name, lambda *a, **k: None)
    for name in ("ticket_rework_step", "seam_rework_step", "answer_rework_step", "code_close_step", "consumer_word_step"):
        setattr(d, name, lambda *a, **k: False)
    d.guarded = lambda fn, record=None: fn()
    d.where = lambda: {"action": "dispatch"}
    d.until_reached = lambda action: False
    d.boundary_step = lambda action: None
    return d


def rows_of(d):
    path = d.state_dir / NAME
    return [json.loads(line) for line in path.read_text(encoding="utf-8").split("\n") if line.strip()] if path.is_file() else []


def stops(d):
    return [r for r in rows_of(d) if r.get("kind") == "stopped_by_person"]


def run_catching(d):
    """`d.run()`; what it raised (the case reads it) and what it printed."""
    out, error = io.StringIO(), None
    with contextlib.redirect_stdout(out):
        try:
            d.run()
        except BaseException as exc:  # noqa: BLE001 - the interrupt itself is the thing under test
            error = exc
    return error, out.getvalue()


def launch(d, call="role", dispatch="S5-x-1", at="2026-11-10T10:00:00+00:00"):
    d.journal_run({"kind": "launched", "call": call, "role": "r", "dispatch_id": dispatch, "stage": "S5", "started_at": at})


def end(d, kind="role", dispatch="S5-x-1"):
    d.journal_run({"kind": kind, "role": "r", "dispatch": dispatch, "stage": "S5", "exit_code": 0, "is_error": False, "infra": None})


# --- 11.1 ----------------------------------------------------------------------------------------------------------------------------
def ctrl_c_serial_writes_one_stop_record(tmp):
    d = rig(tmp / "serial")

    def interrupt():
        raise KeyboardInterrupt()
    d.reconcile_question = interrupt
    error, out = run_catching(d)
    found = stops(d)
    check("ctrl_c_serial_writes_one_stop_record: the interrupt is re-raised", isinstance(error, KeyboardInterrupt), repr(error))
    check_eq("ctrl_c_serial_writes_one_stop_record: ONE row of kind stopped_by_person", len(found), 1)
    row = found[0] if found else {}
    check("ctrl_c_serial_writes_one_stop_record: who, since, at, ts, empty cut",
          row.get("who") == "person" and row.get("since") == d.run_started and row.get("at") and row.get("ts") and row.get("cut") == [], str(row))
    check("ctrl_c_serial_writes_one_stop_record: none of the keys the outcome readers bind on",
          not any(k in row for k in ("dispatch", "session_id", "total_cost_usd", "exit_code", "is_error", "infra", "call", "dispatch_id")), str(row))
    check_eq("ctrl_c_serial_writes_one_stop_record: no console line of its own", out, "")


def ctrl_c_parallel_road_writes_one_stop_record(tmp):
    d = rig(tmp / "parallel")

    def boundary_step(action):
        """What `run_chains` does on Ctrl-C: two chain threads each launched a call, one of them ended, the interrupt comes out."""
        def chain(dispatch):
            launch(d, dispatch=dispatch, at="2026-11-10T10:00:01+00:00")
        threads = [threading.Thread(target=chain, args=(x,)) for x in ("S5-w1-1", "S5-w2-1")]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        end(d, dispatch="S5-w1-1")
        raise KeyboardInterrupt()
    d.boundary_step = boundary_step
    error, _out = run_catching(d)
    found = stops(d)
    check("ctrl_c_parallel_road_writes_one_stop_record: re-raised", isinstance(error, KeyboardInterrupt), repr(error))
    check_eq("ctrl_c_parallel_road_writes_one_stop_record: ONE row", len(found), 1)
    check_eq("ctrl_c_parallel_road_writes_one_stop_record: `cut` is the call that has no end row",
             found[0]["cut"] if found else None, ["S5-w2-1@2026-11-10T10:00:01+00:00"])


def ctrl_c_in_run_level_handler_writes_one_stop_record(tmp):
    d = rig(tmp / "handler")
    d.boundary = "where"

    def refuse():
        raise SR.Refusal("a script said no")
    d.reconcile_question = refuse
    d.settle_unread_answer = lambda: ""
    d.refusal_lines = lambda refusal: []
    d.question_from_refusal = lambda refusal, boundary: "q"
    d._answer = {}

    def funnel(question):
        launch(d, call="conductor", dispatch="", at="2026-11-10T10:00:02+00:00")      # the paid conductor call began, then Ctrl-C
        raise KeyboardInterrupt()
    d.funnel = funnel
    error, _out = run_catching(d)
    found = stops(d)
    check("ctrl_c_in_run_level_handler_writes_one_stop_record: a Ctrl-C inside `except Refusal` -> funnel is re-raised", isinstance(error, KeyboardInterrupt), repr(error))
    check_eq("ctrl_c_in_run_level_handler_writes_one_stop_record: ONE row, naming the conductor call",
             [r["cut"] for r in found], [["conductor@2026-11-10T10:00:02+00:00"]])


def no_state_dir_writes_nothing(tmp):
    d = rig(tmp / "nostate", with_state_dir=False)

    def interrupt():
        raise KeyboardInterrupt()
    d.reconcile_question = interrupt
    error, out = run_catching(d)
    check("no_state_dir_writes_nothing: re-raised", isinstance(error, KeyboardInterrupt), repr(error))
    check("no_state_dir_writes_nothing: the story's state folder is not created", not d.state_dir.exists(), str(d.state_dir))
    check_eq("no_state_dir_writes_nothing: no console line", out, "")


def before_run_no_record(tmp):
    """Ctrl-C in `__init__` / argparse is outside `run`: nothing calls `person_stop_record` (no call was launched either)."""
    d = rig(tmp / "before")
    check("before_run: a driver that never ran `run` has written no row", rows_of(d) == [], str(rows_of(d)))
    d.progress_line = lambda: (_ for _ in ()).throw(KeyboardInterrupt())    # the header line of `run` itself
    error, _out = run_catching(d)
    check("before_run: an interrupt in the header line is re-raised and writes nothing (no call could have been launched)",
          isinstance(error, KeyboardInterrupt) and rows_of(d) == [], f"{error!r} {rows_of(d)}")


def failed_write_is_one_note(tmp):
    d = rig(tmp / "failwrite")
    real = SR._append_jsonl

    def interrupt():
        raise KeyboardInterrupt()
    d.reconcile_question = interrupt

    def broken(path, record):
        raise PermissionError("denied")
    SR._append_jsonl = broken
    try:
        error, out = run_catching(d)
    finally:
        SR._append_jsonl = real
    check("failed_write_is_one_note: the KeyboardInterrupt still re-raises", isinstance(error, KeyboardInterrupt), repr(error))
    lines = [line for line in out.splitlines() if line.strip()]
    check("failed_write_is_one_note: ONE `note:` line naming the error",
          len(lines) == 1 and lines[0].startswith("note:") and "PermissionError" in lines[0], out)


def second_ctrl_c_while_writing(tmp):
    real_append = SR._append_jsonl
    # (a) the second interrupt comes BEFORE the row is on disk: the record is absent, nothing raises past `person_stop_record`
    d = rig(tmp / "second-a")

    def first_then_second_before(path, record):
        raise KeyboardInterrupt()
    SR._append_jsonl = first_then_second_before
    try:
        d.run_started = SR._now()
        returned = d.person_stop_record()
    finally:
        SR._append_jsonl = real_append
    check("second_ctrl_c (before the write): person_stop_record returns, raises nothing, the record is absent", returned is None and stops(d) == [], str(stops(d)))

    # (b) the second interrupt comes AFTER the row is written: the record stays, and `run` still ends with the FIRST interrupt only
    d = rig(tmp / "second-b")

    def interrupt():
        raise KeyboardInterrupt("first")
    d.reconcile_question = interrupt

    def write_then_interrupt(path, record):
        real_append(path, record)
        raise KeyboardInterrupt("second")
    SR._append_jsonl = write_then_interrupt
    try:
        error, _out = run_catching(d)
    finally:
        SR._append_jsonl = real_append
    check("second_ctrl_c (after the write): the record already written is kept", len(stops(d)) == 1, str(stops(d)))
    check("second_ctrl_c (after the write): `run` ends with a KeyboardInterrupt, no other error", isinstance(error, KeyboardInterrupt), repr(error))


def cut_list_follows_journal_run(tmp):
    d = rig(tmp / "cut")
    launch(d, dispatch="S5-a-1", at="T1")
    launch(d, dispatch="S5-b-1", at="T2")
    launch(d, call="conductor", dispatch="", at="T3")
    end(d, dispatch="S5-a-1")
    d.run_started = SR._now()
    d.person_stop_record()
    check_eq("cut: calls launched and not ended, sorted; the ended one is gone", stops(d)[0]["cut"], ["S5-b-1@T2", "conductor@T3"])
    end(d, kind="conductor", dispatch="")
    d.person_stop_record()
    check_eq("cut: a conductor call is ended by its own outcome row (key = kind)", stops(d)[1]["cut"], ["S5-b-1@T2"])
    # a stop row, a note, a trace row are not launches and not ends
    d.journal_run({"kind": "note", "note": "x"})
    d.person_stop_record()
    check_eq("cut: a non-launch, non-outcome row changes nothing", stops(d)[2]["cut"], ["S5-b-1@T2"])
    # a launched row that could not be written is not a cut call (the file has no such row)
    real = SR._append_jsonl
    SR._append_jsonl = lambda path, record: (_ for _ in ()).throw(OSError("full"))
    try:
        try:
            launch(d, dispatch="S5-lost-1", at="T9")
        except OSError:
            pass
    finally:
        SR._append_jsonl = real
    d.person_stop_record()
    check_eq("cut: a launched row whose write failed is not named", stops(d)[3]["cut"], ["S5-b-1@T2"])
    d2 = rig(tmp / "cut-fresh")
    d2.run_started = SR._now()
    d2.person_stop_record()
    check_eq("cut: a process that launched nothing cuts nothing", stops(d2)[0]["cut"], [])


def round_trip_with_the_collector(tmp):
    """The id form of `journal_run` / `person_stop_record` is the twin of `collect_stall._k3_k4`'s: tied by a real driver and a real verdict."""
    d = rig(tmp / "roundtrip")
    old = {"kind": "launched", "call": "role", "role": "r", "dispatch_id": "S5-dead-1", "stage": "S5",
           "started_at": "2020-01-01T00:00:00+00:00", "ts": "2020-01-01T00:00:00+00:00"}
    (d.state_dir / NAME).write_text(json.dumps(old) + "\n", encoding="utf-8")        # a driver that died on its own, long ago
    launch(d, dispatch="S5-x-1", at=SR._now())
    launch(d, call="conductor", dispatch="", at=SR._now())
    d.run_started = "2020-06-01T00:00:00+00:00"
    d.person_stop_record()
    rows = CS._jsonl_rows(d.state_dir / NAME, NAME, [])
    now = 1_900_000_000          # far later than every row: the quiet window is no excuse
    verdict = CS.judge({"closed": True, "unreadable": [], "driver_runs": rows}, None, now, 0)
    where = sorted(s["where"] for s in verdict["signals"])
    check_eq("round trip: the row of the earlier dead driver stays K3, the two calls this process cut are cleared", where,
             ["driver-runs.jsonl launched S5-dead-1"])
    check_eq("round trip: the two cleared rows are named in `ignored` for the stop", sum("stopped by the person" in i["why"] for i in verdict["ignored"]), 2)
    check("round trip: the verdict has no unreadable reason", verdict["unreadable_reasons"] == [], str(verdict["unreadable_reasons"]))
    # the record is not an outcome for any K4 / K3 matching
    check("round trip: the stop row is no outcome row of the collector", not CS._is_outcome(rows[-1]), str(rows[-1]))


# --- 11.2 ----------------------------------------------------------------------------------------------------------------------------
def append_jsonl_repairs_torn_tail(tmp):
    path = tmp / "torn" / "state" / NAME
    path.parent.mkdir(parents=True)
    path.write_bytes(b'{"kind": "a"}\n{"kind": "tor')          # a crash mid-line: no newline at the end
    SR._append_jsonl(path, {"kind": "b", "text": "caf\u00e9 \u4e2d"})
    raw = path.read_bytes()
    lines = raw.split(b"\n")
    check_eq("append_jsonl_repairs_torn_tail: the new row starts on its own line (torn line, then the row, then the end)", len(lines), 4)
    check("append_jsonl_repairs_torn_tail: the new row parses and keeps its non-ASCII text (ensure_ascii False, UTF-8)",
          json.loads(lines[2]) == {"kind": "b", "text": "caf\u00e9 \u4e2d"} and raw.endswith(b"\n"), repr(raw))
    check("append_jsonl_repairs_torn_tail: the line ends in a bare LF, never CRLF", b"\r" not in raw)
    fresh = tmp / "made" / "deep" / "state" / NAME
    SR._append_jsonl(fresh, {"kind": "first"})
    check_eq("append_jsonl: an absent file and folder are created", fresh.read_bytes(), b'{"kind": "first"}\n')
    try:
        SR._append_jsonl(tmp / "torn" / "state" / NAME / "inside", {"kind": "x"})        # a path under a FILE: an OSError, as before
        raised = None
    except OSError as exc:
        raised = exc
    check("append_jsonl: an OSError reaches the caller", raised is not None, "nothing raised")


APPEND_OPEN = re.compile(r"""\.open\(\s*["'][aA][bt+]*["']|\bopen\([^)\n]*(?:,\s*|\bmode\s*=\s*)["'][aA][bt+]*["']""")


def story_run_has_no_private_appender():
    fixture = ('with path.open("a", encoding="utf-8") as handle:\n    handle.write(line)\nwith open(p, "a") as h:\n    pass\n'
               'with open(p, mode="a") as h:\n    pass\nwith open(p, mode=\'a\') as h:\n    pass\nwith open(p, mode="a+") as h:\n    pass\n')
    check_eq("story_run_has_no_private_appender (positive control): the scan finds the positional and the keyword forms in a fixture string",
             len(APPEND_OPEN.findall(fixture)), 5)
    check_eq("story_run_has_no_private_appender (negative control): a read mode is not matched",
             len(APPEND_OPEN.findall('with open(p, mode="r") as h:\n    pass\nwith open(p, "r") as h:\n    pass\n')), 0)
    sources = harness.driver_sources()
    found = [(path.name, text.count("\n", 0, m.start()) + 1, m.group(0)) for path, text in sources for m in APPEND_OPEN.finditer(text)]
    check("story_run_has_no_private_appender: no file of the driver set opens a file for append", found == [], str(found))


def mixed_line_endings_are_read_whole(tmp):
    """F-8: rows written in text mode on Windows ended CRLF; the one appender writes LF. A journal holding both is read whole by the readers."""
    path = tmp / "mixed" / "state" / NAME
    path.parent.mkdir(parents=True)
    first, second = {"kind": "role", "dispatch": "d1", "session_id": "s1", "exit_code": 0, "ts": "2026-11-10T10:00:00+00:00"}, {"kind": "launched", "call": "role", "dispatch_id": "d2", "started_at": "2026-11-10T10:01:00+00:00"}
    path.write_bytes((json.dumps(first) + "\r\n" + json.dumps(second) + "\r\n").encode("utf-8"))
    SR._append_jsonl(path, {"kind": "stopped_by_person", "who": "person", "at": "x", "since": "y", "cut": []})
    raw = path.read_bytes()
    check("mixed endings: the file holds both CRLF and bare LF lines", raw.count(b"\r\n") == 2 and raw.count(b"\n") == 3, repr(raw[-80:]))
    for label, rows in (("story_run._read_jsonl", SR._read_jsonl(path)), ("driver_journal.read_rows", DJ.read_rows(path)),
                        ("collect_stall._jsonl_rows", CS._jsonl_rows(path, NAME, []))):
        check_eq(f"mixed endings: {label} reads all three rows", [r["kind"] for r in rows], ["role", "launched", "stopped_by_person"])
    reasons: list = []
    check_eq("mixed endings: collect_stall names no broken line", (CS._jsonl_rows(path, NAME, reasons), reasons)[1], [])


def main():
    tmp = temp_dir("qa-stop-record-")
    try:
        ctrl_c_serial_writes_one_stop_record(tmp)
        ctrl_c_parallel_road_writes_one_stop_record(tmp)
        ctrl_c_in_run_level_handler_writes_one_stop_record(tmp)
        no_state_dir_writes_nothing(tmp)
        before_run_no_record(tmp)
        failed_write_is_one_note(tmp)
        second_ctrl_c_while_writing(tmp)
        cut_list_follows_journal_run(tmp)
        round_trip_with_the_collector(tmp)
        append_jsonl_repairs_torn_tail(tmp)
        story_run_has_no_private_appender()
        mixed_line_endings_are_read_whole(tmp)
    finally:
        cleanup(tmp)
    finish("test_driver_stop_record")


if __name__ == "__main__":
    main()
