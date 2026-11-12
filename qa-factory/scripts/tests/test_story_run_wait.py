#!/usr/bin/env python3
"""The wall clock of a role call and the silent wait (t-1937 P2-4, node TR3-2). SLOW: it starts the stub `claude` as a process; CI runs it.

`run_claude` journals `wall_ms` (the driver's own clock) next to the CLI's `duration_ms`, and prints one note when the two differ by more
than 120 s. `launch` runs a watchdog thread while the process is waited for; it tells ONE line per silence episode and never kills.

No test sleeps to synchronise (FR-31): the stub role WAITS FOR A FLAG FILE (30 s fail-safe) and the patched transcript reader writes that
flag on its third poll, so the watchdog has certainly polled three times when the role ends. The 120 s case moves a fake clock instead of
waiting. Nothing here reaches the network or a real model; the stub and the helpers live in `story_run_common`.
"""
import contextlib
import io
import json
import os
import sys
import threading
import time
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import check, check_eq  # noqa: E402
import story_run_common as T  # noqa: E402
from story_run_common import STUB, driver_for, run_scenarios, seed  # noqa: E402

TASK = "QA-1"
DISPATCH = "S1-qa-scout-1"
WAIT_PRELUDE = r'''
import os as _os, time as _time
from pathlib import Path as _Path
_flag = _os.environ.get("STUB_WAIT_FLAG")
if _flag:
    _end = _time.monotonic() + 30
    while not _Path(_flag).exists() and _time.monotonic() < _end:
        _time.sleep(0.05)
'''


def world():
    """A seeded project whose stub claude waits for `flag` (when STUB_WAIT_FLAG is set) before it answers, and a Driver over it."""
    root, task_root, env = seed(TASK)
    Path(env["STORY_RUN_CLAUDE"]).write_text(WAIT_PRELUDE + STUB, encoding="utf-8")
    flag = root / "role-may-end.flag"
    os.environ["STUB_WAIT_FLAG"] = str(flag)
    driver = driver_for(root, env, TASK)
    return root, task_root, driver, flag


def call(driver, task_root, redirected=None) -> str:
    """One role call; the console text it printed. The driver's timing lines go to the ORIGINAL stdout (`sys.__stdout__`, t-2034 M2),
    so that stream is swapped for a buffer here; `redirected` (a StringIO) is where `sys.stdout` points during the call."""
    out, original = redirected if redirected is not None else io.StringIO(), io.StringIO()
    kept = sys.__stdout__
    sys.__stdout__ = original
    try:
        with contextlib.redirect_stdout(out):
            driver.run_claude("role", f"Artifacts dir: {task_root}\nDispatch: {DISPATCH}.\n", role="qa-scout", dispatch=DISPATCH, stage="S1")
    finally:
        sys.__stdout__ = kept
    return original.getvalue()


def role_rows(task_root) -> list:
    return [r for r in T.jsonl(task_root / "state" / "driver-runs.jsonl") if r.get("kind") == "role"]


def done(root) -> None:
    os.environ.pop("STUB_WAIT_FLAG", None)
    harness.cleanup(root)


def wall_ms_journalled() -> None:
    root, task_root, driver, flag = world()
    try:
        os.environ.pop("STUB_WAIT_FLAG", None)
        call(driver, task_root)
        row = role_rows(task_root)[-1]
        check("wall_ms is a whole number of milliseconds, next to the CLI's duration_ms",
              isinstance(row.get("wall_ms"), int) and not isinstance(row.get("wall_ms"), bool) and row["wall_ms"] >= 0 and row["duration_ms"] == 1500,
              json.dumps(row)[:400])
    finally:
        done(root)


def wall_vs_duration_note_over_120s() -> None:
    import story_run
    root, task_root, driver, flag = world()
    saved = story_run.time
    try:
        os.environ.pop("STUB_WAIT_FLAG", None)
        clock = {"now": 1_000_000.0}
        story_run.time = types.SimpleNamespace(**{k: getattr(time, k) for k in dir(time) if not k.startswith("_")})
        story_run.time.time = lambda: clock["now"]
        real = driver.launch

        def slow(*args, **kwargs):
            finished = real(*args, **kwargs)
            clock["now"] += 200.0                    # the call took 200 s of wall clock; the stub's CLI says 1.5 s
            return finished
        driver.launch = slow
        text = call(driver, task_root)
        check("a call 200 s long by the wall and 1.5 s by the CLI prints the note, with both clocks",
              f"note: {DISPATCH} took 3m20s of wall clock, the CLI reports 0m02s: its own count covers only the last turn" in text, text[-400:])
        check_eq("and the row holds the driver's own wall", role_rows(task_root)[-1]["wall_ms"], 200000)
        driver.launch = real
        quiet = call(driver, task_root)
        check("a call with no gap prints no such note (negative control)", "of wall clock" not in quiet, quiet[-300:])
    finally:
        story_run.time = saved
        done(root)


def patched_reader(flag: Path, answers: list):
    """A transcript reader for the watchdog: returns `answers[i]` on poll i (the last one after that) and writes the flag on poll 3+."""
    polls = []

    def reader(project_root, dispatch, *_since_and_memo):
        polls.append(dispatch)
        if len(polls) >= len(answers) and len(polls) >= 3:
            flag.write_text("go", encoding="utf-8")
        answer = answers[min(len(polls), len(answers)) - 1]
        return answer() if callable(answer) else answer
    return reader, polls


def with_watchdog(reader):
    import driver_timing
    before = (driver_timing.POLL_S, driver_timing.last_write)
    driver_timing.POLL_S, driver_timing.last_write = 0.02, reader
    return before


def restore_watchdog(before) -> None:
    import driver_timing
    driver_timing.POLL_S, driver_timing.last_write = before


def silence_line_once_per_episode() -> None:
    root, task_root, driver, flag = world()
    threads = threading.active_count()
    before = None
    try:
        long_ago = time.time() - 3600
        reader, polls = patched_reader(flag, [long_ago])
        before = with_watchdog(reader)
        text = call(driver, task_root)
        said = [l for l in text.splitlines() if l.startswith(f"[progress] {DISPATCH} has written nothing for ")]
        check_eq("an hour of silence over three or more polls: ONE line", len(said), 1)
        check("the line names the minutes and the last write (HH:MM)", "for 60 min (last at " in said[0], said[0] if said else text[-300:])
        check("the watchdog polled at least three times", len(polls) >= 3, str(len(polls)))
        check_eq("the role was not stopped: its result row is an ordinary end row", role_rows(task_root)[-1]["exit_code"], 0)
        check_eq("the watchdog thread ended with the call (no leak)", threading.active_count(), threads)
        flag.unlink()
        # two episodes: silent, a write, silent again -> two lines
        reader, polls = patched_reader(flag, [long_ago, long_ago, lambda: time.time(), long_ago, long_ago])
        restore_watchdog(before)
        before = with_watchdog(reader)
        said = [l for l in call(driver, task_root).splitlines() if "has written nothing" in l]
        check_eq("a write between two silences makes two episodes: two lines", len(said), 2)
    finally:
        if before:
            restore_watchdog(before)
        done(root)


def no_line_when_transcript_grows() -> None:
    root, task_root, driver, flag = world()
    before = None
    try:
        reader, polls = patched_reader(flag, [lambda: time.time()])
        before = with_watchdog(reader)
        text = call(driver, task_root)
        check("a transcript written at every poll: no silence line", "has written nothing" not in text, text[-300:])
        check("the watchdog did poll", len(polls) >= 3, str(len(polls)))
        flag.unlink()
        reader, polls = patched_reader(flag, [None])
        restore_watchdog(before)
        before = with_watchdog(reader)
        text = call(driver, task_root)
        check("an unknown (no transcript found) prints nothing and the call still returns its result",
              "has written nothing" not in text and role_rows(task_root)[-1]["exit_code"] == 0, text[-300:])
    finally:
        if before:
            restore_watchdog(before)
        done(root)


def silence_line_survives_redirected_stdout() -> None:
    """t-2034 M2: `sys.stdout` is redirected process-wide while the driver builds a deferred question; the watchdog thread's line must
    still reach the console (the original stdout), and the redirected buffer must not hold it."""
    root, task_root, driver, flag = world()
    before = None
    try:
        reader, polls = patched_reader(flag, [time.time() - 3600])
        before = with_watchdog(reader)
        redirected = io.StringIO()
        console = call(driver, task_root, redirected)
        check("the silence line is on the original stdout", f"[progress] {DISPATCH} has written nothing for " in console, console[-300:])
        check_eq("and none of it was lost into the redirected buffer", "has written nothing" in redirected.getvalue(), False)
    finally:
        if before:
            restore_watchdog(before)
        done(root)


def main() -> None:
    run_scenarios([], [
        wall_ms_journalled,
        wall_vs_duration_note_over_120s,
        silence_line_once_per_episode,
        no_line_when_transcript_grows,
        silence_line_survives_redirected_stdout,
    ])
    harness.finish("test_story_run_wait")


if __name__ == "__main__":
    main()
