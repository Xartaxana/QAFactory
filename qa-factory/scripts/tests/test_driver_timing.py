#!/usr/bin/env python3
"""driver_timing.py - the hop timing aggregator and the pure parts of the silent-wait watchdog (t-1937 P2-1, P2-4; node TR3-2).

The aggregator reads `state/driver-timings.jsonl` (the driver's step lines) and `state/driver-runs.jsonl` (a call's result row, the next
`launched` row). Every case builds those two files by hand in a temp story, so no clock is read and no process runs (FR-31).
"""
import contextlib
import io
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import check, check_eq, check_in, check_not_in, finish  # noqa: E402

sys.path.insert(0, str(harness.SCRIPTS))
import driver_timing as DT  # noqa: E402

T0 = datetime(2026, 11, 6, 10, 0, 0, tzinfo=timezone.utc)


def at(seconds: float) -> str:
    return (T0 + timedelta(seconds=seconds)).isoformat()


def story(task: str = "QA-1"):
    root = harness.temp_project("driver-timing-")
    task_root = root / "qa-factory" / "artifacts" / task
    (task_root / "state").mkdir(parents=True)
    return root, task_root


def write_jsonl(path: Path, rows: list, raw_lines: list = ()) -> None:
    path.write_text("".join(json.dumps(r) + "\n" for r in rows) + "".join(line + "\n" for line in raw_lines), encoding="utf-8")


def runs(end_at: float, launch_at: float) -> list:
    return [{"ts": at(end_at), "kind": "role", "dispatch": "S5-qa-automator-1", "exit_code": 0},
            {"ts": at(launch_at), "kind": "launched", "dispatch_id": "S5-qa-code-critic-1"}]


def step(end_at: float, name: str, seconds: float, **extra) -> dict:
    return dict({"ts": at(end_at), "stage": "S5", "dispatch": "S5-qa-automator-1", "step": name, "seconds": seconds}, **extra)


def main_out(task_root: Path, *flags):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = DT.cli_main(["--task-root", str(task_root), *flags])
    return code, out.getvalue()


def hop_split_sums_to_wall() -> None:
    root, task_root = story()
    try:
        write_jsonl(task_root / "state" / "driver-runs.jsonl", runs(0, 30))
        write_jsonl(task_root / "state" / "driver-timings.jsonl", [
            step(3, "bind", 2.0), step(15, "handoff", 10.0), step(21, "finish", 5.0), step(29, "start", 3.0),
            step(27, "start.pre_work", 1.5)])           # a part of `start`: listed, never added to the hop a second time
        data = DT.report(task_root)
        hop = data["hops"][0]
        check_eq("the hop is the span from the result row to the next launch", (hop["wall_s"], hop["after"], hop["before"]),
                 (30.0, "S5-qa-automator-1", "S5-qa-code-critic-1"))
        check_eq("its steps are the timed top-level steps inside it", hop["steps"], {"bind": 2.0, "handoff": 10.0, "finish": 5.0, "start": 3.0})
        check_eq("a part of start is a sub-step, not a step", hop["sub_steps"], {"start.pre_work": 1.5})
        check_eq("attributed + unattributed == wall", round(hop["attributed_s"] + hop["unattributed_s"], 2), hop["wall_s"])
        check_eq("the step total of the hop", hop["attributed_s"], 20.0)
        check_eq("per-step totals count every line", data["step_totals"]["start.pre_work"], {"n": 1, "seconds": 1.5, "errors": 0})
    finally:
        harness.cleanup(root)


def unattributed_remainder_is_named() -> None:
    root, task_root = story()
    try:
        write_jsonl(task_root / "state" / "driver-runs.jsonl", runs(0, 30))
        write_jsonl(task_root / "state" / "driver-timings.jsonl", [step(10, "bind", 4.0)])
        data = DT.report(task_root)
        check_eq("the remainder is a number, not a hole", data["hops"][0]["unattributed_s"], 26.0)
        code, text = main_out(task_root)
        check_in("the text names the unattributed part", "unattributed 26.0 s", text)
        check_eq("and exits 0", code, 0)
        write_jsonl(task_root / "state" / "driver-timings.jsonl", [step(30, "bind", 30.5)])
        over = DT.report(task_root)["hops"][0]
        check_eq("steps over the wall (whole-second stamps) are named and the remainder is not negative",
                 (over["unattributed_s"], over.get("over_attributed_s")), (0.0, 0.5))
    finally:
        harness.cleanup(root)


def empty_file_says_no_timings() -> None:
    root, task_root = story()
    try:
        code, text = main_out(task_root)
        check_eq("no carrier file: exit 0", code, 0)
        check_in("and the text says so by story, not 0 s of overhead", "no timings recorded for QA-1", text)
        check("the absent carrier is not read as a number", "0 s" not in text and "hop" not in text, text)
        (task_root / "state" / "driver-timings.jsonl").write_text("", encoding="utf-8")
        code, text = main_out(task_root, "--check-hop-s", "20")
        check_eq("an empty carrier file: the same words, exit 0 even with --check-hop-s", (code, "no timings recorded for QA-1" in text), (0, True))
        code, text = main_out(task_root, "--json")
        check_eq("--json carries timed: false", json.loads(text)["timed"], False)
    finally:
        harness.cleanup(root)


def unreadable_line_is_counted_not_dropped() -> None:
    root, task_root = story()
    try:
        write_jsonl(task_root / "state" / "driver-runs.jsonl", runs(0, 30))
        write_jsonl(task_root / "state" / "driver-timings.jsonl", [step(10, "bind", 4.0)], raw_lines=["{not json", '["a list"]'])
        data = DT.report(task_root)
        check_eq("two unreadable lines are counted in problems", len(data["problems"]), 2)
        check("the readable line still counts", data["hops"][0]["steps"] == {"bind": 4.0}, str(data["hops"]))
        code, text = main_out(task_root)
        check_in("and the text names them", "line 2 is not a JSON object", text)
        write_jsonl(task_root / "state" / "driver-timings.jsonl", [], raw_lines=["{not json"])
        data = DT.report(task_root)
        check_eq("only unreadable lines: still 'no timings recorded' plus the count",
                 (data["timed"], len(data["problems"]), data["text"]), (False, 1, "no timings recorded for QA-1"))
        write_jsonl(task_root / "state" / "driver-timings.jsonl", [{"ts": "yesterday", "step": "bind", "seconds": 1}, {"ts": at(5), "step": "x", "seconds": "a lot"}])
        check_eq("a line without a usable ts or seconds is counted too", len(DT.report(task_root)["problems"]), 2)
    finally:
        harness.cleanup(root)


def check_hop_s_at_and_beyond() -> None:
    root, task_root = story()
    try:
        write_jsonl(task_root / "state" / "driver-timings.jsonl", [step(3, "bind", 1.0)])
        for wall, listed in ((19.9, False), (20.0, False), (20.1, True)):
            write_jsonl(task_root / "state" / "driver-runs.jsonl", runs(0, wall))
            code, text = main_out(task_root, "--check-hop-s", "20")
            check_eq(f"a hop of {wall} s: exit {1 if listed else 0}", code, 1 if listed else 0)
            check_eq(f"a hop of {wall} s is {'listed' if listed else 'not listed'} as over", f"{wall} s" in text.split("hops over 20.0 s:")[-1], listed)
        code, text = main_out(task_root)
        check_eq("without --check-hop-s the exit is 0 whatever the hops (advice, not a gate)", code, 0)
    finally:
        harness.cleanup(root)


def a_step_that_straddles_a_launch_is_named() -> None:
    root, task_root = story()
    try:
        write_jsonl(task_root / "state" / "driver-runs.jsonl", runs(0, 30))
        write_jsonl(task_root / "state" / "driver-timings.jsonl", [step(60, "handoff", 50.0), step(10, "bind", 2.0)])
        data = DT.report(task_root)
        check_eq("the handoff that resumed the role (a launch inside it) is in no hop", data["hops"][0]["steps"], {"bind": 2.0})
        check_in("and is named", "handoff", " ".join(data["straddling_a_launch"]))
    finally:
        harness.cleanup(root)


def the_timer_writes_by_every_road() -> None:
    seen = []
    write = lambda step_name, seconds, **kw: seen.append((step_name, seconds >= 0, kw))      # noqa: E731
    with DT.Timer(write, "bind", "D-1", "S5"):
        pass
    try:
        with DT.Timer(write, "finish", "D-1", "S5"):
            raise ValueError("boom")
    except ValueError:
        seen.append(("passed through", True, {}))
    with DT.Timer(write, "start", "", "S5") as lap:
        lap.dispatch = "D-2"
    check_eq("an ok step writes with no error", seen[0][2]["error"], "")
    check_eq("a raising step still writes, with the exception type, and the exception passes", (seen[1][2]["error"], seen[2][0]), ("ValueError", "passed through"))
    check_eq("the dispatch can be set inside the block", seen[3][2]["dispatch"], "D-2")
    laps = DT.Laps()
    with laps.lap("start.pre_work"):
        pass
    check_eq("Laps round-trips through the parsed lines", [n for n, _s in DT.parse_lines("x\n" + "\n".join(laps.lines()) + "\ntiming: bad")], ["start.pre_work"])
    check_eq("the row carries the error key only on a failure", ("error" in DT.row("t", "S5", "d", "s", 1.234), DT.row("t", "S5", "d", "s", 1.234, "X")["error"]), (False, "X"))


def the_wall_note_and_the_silence_episodes() -> None:
    check_eq("120.0 s of difference says nothing", DT.wall_note("D", 121500, 1500), "")
    check_in("over 120 s says one note with both clocks", "took 2m03s of wall clock, the CLI reports 0m02s", DT.wall_note("D", 123000, 1500))
    check_eq("an absent duration is an unknown, not a difference", DT.wall_note("D", 999999, None), "")
    quiet = DT.Silence("D-1", 600)
    check_eq("within the threshold: nothing", quiet.check(1000.0, 1600.0), "")
    first = quiet.check(1000.0, 1601.0)
    check_in("past it: one progress line", "[progress] D-1 has written nothing for 10 min (last at ", first)
    check_eq("the same episode says nothing again", (quiet.check(1000.0, 1700.0), quiet.check(1000.0, 5000.0)), ("", ""))
    check_eq("an unknown (no transcript) says nothing and keeps the episode", quiet.check(None, 9000.0), "")
    quiet.check(8000.0, 8100.0)
    check_in("a write ended the episode: the next silence speaks again", "has written nothing", quiet.check(8000.0, 9000.0))


def main_transcript(folder: Path, name: str, dispatch: str) -> Path:
    """A driver role's transcript: a MAIN session file (no `subagents/` anywhere), its first user message the role prompt."""
    path = folder / f"{name}.jsonl"
    prompt = f"You are qa-automator. Ticket: QA-1. Dispatch: {dispatch}.\nDo the work."
    path.write_text(json.dumps({"type": "user", "timestamp": "2026-11-06T10:00:00Z", "message": {"role": "user", "content": prompt}}) + "\n",
                    encoding="utf-8")
    return path


def silence_reads_the_main_transcript() -> None:
    import os
    root = harness.temp_project("driver-timing-main-")
    try:
        sessions = root / "host-sessions"
        sessions.mkdir()
        cost = root / "qa-factory" / "state" / "cost"
        cost.mkdir(parents=True)
        check_eq("no cost file written yet: an unknown, not a guess", DT.last_write(root, "S5-qa-automator-13"), None)
        mine = main_transcript(sessions, "sess-a", "S5-qa-automator-13")
        other = main_transcript(sessions, "sess-b", "S5-qa-automator-14")
        (cost / "sess-a.json").write_text(json.dumps({"transcript": str(mine)}), encoding="utf-8")
        os.utime(mine, (5000.0, 5000.0))
        os.utime(other, (9000.0, 9000.0))
        check("the fixture has no subagents folder at all (the old reader would find nothing)", not (sessions / "sess-a" / "subagents").exists(), "")
        memo = {}
        check_eq("the main transcript that names the dispatch is read: its mtime", DT.last_write(root, "S5-qa-automator-13", 0.0, memo), 5000.0)
        check_eq("the path found is kept for the later polls", memo.get("path"), mine)
        os.utime(mine, (6000.0, 6000.0))
        check_eq("a later poll only stats the kept path", DT.last_write(root, "S5-qa-automator-13", 0.0, memo), 6000.0)
        check_eq("a dispatch no transcript names is an unknown", DT.last_write(root, "S5-qa-automator-99"), None)
        check_eq("a transcript older than the launch is not this launch's", DT.last_write(root, "S5-qa-automator-13", 7000.0), None)
        (cost / "bad.json").write_text("{", encoding="utf-8")
        check_eq("a damaged cost file contributes nothing", DT.last_write(root, "S5-qa-automator-13"), 6000.0)
    finally:
        harness.cleanup(root)


def silence_line_survives_redirected_stdout_unit() -> None:
    """The watchdog's line goes to the ORIGINAL stdout: a `redirect_stdout` window (the driver's deferred question) does not eat it."""
    import threading
    kept, seen = sys.__stdout__, io.StringIO()
    sys.__stdout__ = seen
    saved = (DT.POLL_S, DT.last_write)
    DT.POLL_S, DT.last_write = 0.01, lambda *a, **k: 1.0       # silent since the epoch
    stop, redirected = threading.Event(), io.StringIO()
    try:
        with contextlib.redirect_stdout(redirected):
            thread = threading.Thread(target=DT.watch, args=(Path("."), "D-1", stop))
            thread.start()
            for _ in range(500):
                if seen.getvalue():
                    break
                stop.wait(0.01)
            stop.set()
            thread.join(5)
    finally:
        sys.__stdout__ = kept
        DT.POLL_S, DT.last_write = saved
    check_in("the line is on the original stdout", "[progress] D-1 has written nothing", seen.getvalue())
    check_eq("and not in the redirected buffer", redirected.getvalue(), "")
    check_eq("one line for the one episode", seen.getvalue().count("[progress]"), 1)
    sys.__stdout__ = None
    try:
        DT.console("nobody listens")
        failed = ""
    except Exception as exc:  # noqa: BLE001
        failed = type(exc).__name__
    finally:
        sys.__stdout__ = kept
    check_eq("no original stream: nothing printed, nothing raised", failed, "")


def a_byte_that_is_not_utf8_is_one_bad_line() -> None:
    root, task_root = story()
    try:
        write_jsonl(task_root / "state" / "driver-runs.jsonl", runs(0, 30))
        carrier = task_root / "state" / "driver-timings.jsonl"
        carrier.write_bytes((json.dumps(step(10, "bind", 4.0)) + "\n").encode("utf-8") + b'{"step": "caf\xc3\n')
        data = DT.report(task_root)
        check_eq("the readable line counts, the torn one is named", (data["hops"][0]["steps"], len(data["problems"])), ({"bind": 4.0}, 1))
        code, text = main_out(task_root)
        check_in("and the text is printed, no traceback", "line 2 is not a JSON object", text)
    finally:
        harness.cleanup(root)


def timing_lines_follow_the_run_mode() -> None:
    """`story_step.start` prints `timing:` lines only for the driver (t-2034 mode gate): on the skill road the printed card is the whole
    stdout (the byte pin of test_launch_card). Covers `timing_lines_not_in_card` and `timing_lines_absent_on_skill_road`.
    The mode reader unreadable/absent is the skill road's behaviour (FR-59: the byte pin is the side that must hold)."""
    import story_step
    from story_step_common import seed
    from test_story_step_start import run_start
    env_name = story_step.RUN_MODE_ENV
    saved = os.environ.get(env_name)
    root = harness.temp_project("driver-timing-mode-")
    try:
        harness.use_project(root)
        results = {}
        for label, value in (("driver", "driver"), ("desktop", "desktop"), ("absent", None), ("blank", "  ")):
            if value is None:
                os.environ.pop(env_name, None)
            else:
                os.environ[env_name] = value
            task = seed(root, f"QA-{label}")      # one story per road: the first start stamps the story's run mode
            code, out, _log = run_start(task,"S1", "qa-scout", lambda _a: (0, ""))
            results[label] = (code, out)
        check_eq("the driver road starts", results["driver"][0], 0)
        check("the driver road prints its timing lines after the card", "timing: start." in results["driver"][1], results["driver"][1][-300:])
        for label in ("desktop", "absent", "blank"):
            check_eq(f"skill road ({label}): the start succeeds", results[label][0], 0)
            check_not_in(f"skill road ({label}): no timing line in the printed card", "timing:", results[label][1])
    finally:
        if saved is None:
            os.environ.pop(env_name, None)
        else:
            os.environ[env_name] = saved
        harness.cleanup(root)


def main() -> None:
    timing_lines_follow_the_run_mode()
    silence_reads_the_main_transcript()
    silence_line_survives_redirected_stdout_unit()
    a_byte_that_is_not_utf8_is_one_bad_line()
    hop_split_sums_to_wall()
    unattributed_remainder_is_named()
    empty_file_says_no_timings()
    unreadable_line_is_counted_not_dropped()
    check_hop_s_at_and_beyond()
    a_step_that_straddles_a_launch_is_named()
    the_timer_writes_by_every_road()
    the_wall_note_and_the_silence_episodes()
    finish("test_driver_timing")


if __name__ == "__main__":
    main()
