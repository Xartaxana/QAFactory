#!/usr/bin/env python3
"""The test rig never leaves the process in a deleted directory (conductor/4 C4-6, FR-31).

`story_run.Driver.__init__` chdirs into the project it is given, and the tests delete that temp project in a
`finally`. Windows refuses to delete a directory a process stands in, so the suite was green there; Linux deletes
it, and the NEXT test of the same process died in `os.getcwd()` with `FileNotFoundError` (the red package-fast
of 16.10). Three pieces, each pinned here:

  - `harness.cleanup(root)` goes back to the cwd `driver_for` recorded BEFORE it deletes the project;
  - the guard `harness.guard_cwd(test)` names the test that left a dead cwd, with a FAIL line, and moves the
    process back so that one offender costs one line;
  - `run_scenarios` runs the guard after every scenario, `finish` once at the end of a file.

A deleted cwd cannot be made on Windows, so the offender there is simulated by an `os.getcwd` that raises the way
Linux's does; on Linux the same pin also runs the real deletion. The healthy case (a test that restores, and
Windows in general) prints nothing and records nothing.
"""
import contextlib
import io
import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import check, check_eq, finish  # noqa: E402

START = os.getcwd()


def here():
    """Where the process stands, or the word for a dead cwd: a pin that fails must FAIL by name, not crash in
    `os.getcwd()` (the very thing this file guards against)."""
    try:
        return Path(os.getcwd()).resolve()
    except OSError:
        return "<the cwd is gone>"


@contextlib.contextmanager
def dead_cwd_as_linux_has_it():
    """Inside the block `os.getcwd()` raises what Linux raises when the cwd was deleted. The real directory is
    left standing: only the process's VIEW of it is dead, so the guard's way back (`os.chdir`) is the real one."""
    real = os.getcwd

    def gone():
        raise FileNotFoundError(2, "No such file or directory")
    os.getcwd = gone
    try:
        yield
    finally:
        os.getcwd = real


def judged(guard_call):
    """Run a guard call with its lines captured and its results taken back out of the file's tally:
    (what it returned, the lines it printed, the FAIL names it recorded). The pin judges the guard; the
    guard's own FAIL must not fail the pin."""
    mark = len(harness.RESULTS)
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        returned = guard_call()
    recorded = [name for ok, name in harness.RESULTS[mark:] if not ok]
    del harness.RESULTS[mark:]
    return returned, out.getvalue(), recorded


def back_at_start() -> None:
    os.chdir(START)
    harness._CWD_BASE = None


def guard_names_the_offender() -> None:
    elsewhere = harness.temp_dir("qa-cwd-guard-")
    try:
        os.chdir(elsewhere)
        harness.remember_cwd()
        with dead_cwd_as_linux_has_it():
            returned, shown, recorded = judged(lambda: harness.guard_cwd("a_test_that_deleted_its_cwd"))
        check_eq("the guard reports a dead cwd as not fine", returned, False)
        check("the guard's FAIL line names the offending test", "a_test_that_deleted_its_cwd" in shown, shown)
        check("the guard's FAIL line is a FAIL, the file's tally keeps it",
              shown.startswith("FAIL ") and len(recorded) == 1, f"{shown!r} {recorded!r}")
        check_eq("the guard moves the process back to the recorded base", here(), elsewhere.resolve())
    finally:
        back_at_start()
        harness.cleanup(elsewhere)


def guard_is_silent_when_the_test_restored() -> None:
    """The negative control: a test that went into a directory and came back leaves no line and no result."""
    elsewhere = harness.temp_dir("qa-cwd-guard-")
    try:
        os.chdir(elsewhere)
        os.chdir(START)
        returned, shown, recorded = judged(lambda: harness.guard_cwd("a_test_that_restored"))
        check_eq("a healthy cwd: the guard says fine", returned, True)
        check_eq("a healthy cwd: the guard prints nothing", shown, "")
        check_eq("a healthy cwd: the guard records nothing", recorded, [])
    finally:
        back_at_start()
        harness.cleanup(elsewhere)


def guard_without_a_base_goes_to_the_plugin_root() -> None:
    try:
        harness._CWD_BASE = None
        with dead_cwd_as_linux_has_it():
            returned, _shown, recorded = judged(lambda: harness.guard_cwd("a_test_with_no_recorded_base"))
        check_eq("no recorded base: the offender is still named", (returned, len(recorded)), (False, 1))
        check_eq("no recorded base: the process goes to the plugin root", here(),
                 harness.PLUGIN_ROOT.resolve())
    finally:
        back_at_start()


def run_scenarios_runs_the_guard() -> None:
    """The wiring: a scenario after which the cwd is dead is named by `run_scenarios`, a clean one is not."""
    import story_run_common as T

    def scenario_that_left_a_dead_cwd():
        pass

    def scenario_that_left_nothing():
        pass
    try:
        with dead_cwd_as_linux_has_it():
            _, shown, recorded = judged(lambda: T.run_scenarios([], [scenario_that_left_a_dead_cwd]))
        check_eq("run_scenarios: the offending scenario is named, once",
                 (len(recorded), "scenario_that_left_a_dead_cwd" in shown), (1, True))
        _, shown, recorded = judged(lambda: T.run_scenarios([], [scenario_that_left_nothing]))
        check_eq("run_scenarios: a clean scenario leaves no line", (shown, recorded), ("", []))
    finally:
        back_at_start()


def cleanup_goes_back_before_it_deletes() -> None:
    """The fixture: the project is deleted while the process stands in it; the cwd is restored first."""
    root = harness.temp_project("qa-cwd-guard-proj-")
    try:
        harness.remember_cwd()
        os.chdir(root)
        harness.cleanup(root)
        check_eq("cleanup: the cwd is back where it was recorded", here(), Path(START).resolve())
        check("cleanup: the project is gone (a cwd is no longer in its way, on Windows too)", not root.exists(), str(root))
        check("cleanup: the process's cwd exists", not harness.dead_cwd())
    finally:
        back_at_start()
        shutil.rmtree(root, ignore_errors=True)


def nested_records_keep_the_outermost_cwd() -> None:
    root = harness.temp_project("qa-cwd-guard-proj-")
    try:
        harness.remember_cwd()
        os.chdir(root)
        harness.remember_cwd()                       # a second driver_for, called while the first project is the cwd
        harness.cleanup(root)
        check_eq("nested: the OUTERMOST caller's cwd wins", here(), Path(START).resolve())
    finally:
        back_at_start()
        shutil.rmtree(root, ignore_errors=True)


def cleanup_of_another_root_does_not_move_the_process() -> None:
    mine, other = harness.temp_project("qa-cwd-guard-mine-"), harness.temp_project("qa-cwd-guard-other-")
    try:
        harness.remember_cwd()
        os.chdir(mine)
        harness.cleanup(other)
        check_eq("cleanup of a root the process is not in leaves the cwd alone", here(), mine.resolve())
        check("cleanup of a root the process is not in leaves the base for the owner's cleanup", harness._CWD_BASE is not None)
        harness.cleanup(mine)
        check_eq("the owner's cleanup then goes back", here(), Path(START).resolve())
    finally:
        back_at_start()
        shutil.rmtree(mine, ignore_errors=True)
        shutil.rmtree(other, ignore_errors=True)


def cleanup_without_a_recorded_base_goes_to_the_plugin_root() -> None:
    """A Driver built without `driver_for` (test_no_real_claude) never recorded a base: cleanup still takes
    the process out of the project it deletes, to the plugin root."""
    root = harness.temp_project("qa-cwd-guard-proj-")
    try:
        harness._CWD_BASE = None
        os.chdir(root)
        harness.cleanup(root)
        check_eq("cleanup with no recorded base: the process is at the plugin root", here(),
                 harness.PLUGIN_ROOT.resolve())
        check("cleanup with no recorded base: the project is gone", not root.exists(), str(root))
    finally:
        back_at_start()
        shutil.rmtree(root, ignore_errors=True)


def a_real_driver_is_taken_out_before_the_delete() -> None:
    """The class itself: a Driver built by `driver_for` has chdir'd into the project; `cleanup` takes the
    process out, whatever the OS does with a cwd that is deleted."""
    import story_run_common as T
    root, _task_root, env = T.seed("QA-1")
    try:
        T.driver_for(root, env, "QA-1")
        check_eq("driver_for: the Driver stands in the project (the premise of the class)",
                 here(), root.resolve())
    finally:
        harness.cleanup(root)
    check_eq("driver_for + cleanup: the process is back where driver_for found it", here(),
             Path(START).resolve())
    check("driver_for + cleanup: the project is gone", not root.exists(), str(root))
    back_at_start()


def a_real_deletion_is_named_where_the_os_allows_it() -> None:
    """Linux only (Windows refuses the delete, and the simulated pin above covers it): the real thing."""
    elsewhere = harness.temp_dir("qa-cwd-guard-real-")
    os.chdir(elsewhere)
    try:
        shutil.rmtree(elsewhere)
    except OSError:
        check("windows: a cwd cannot be deleted, so the guard has nothing real to name here", True)
        back_at_start()
        shutil.rmtree(elsewhere, ignore_errors=True)
        return
    try:
        returned, shown, recorded = judged(lambda: harness.guard_cwd("a_test_that_really_deleted_its_cwd"))
        check_eq("a really deleted cwd: named", (returned, len(recorded), "a_test_that_really_deleted_its_cwd" in shown),
                 (False, 1, True))
        check("a really deleted cwd: the process is out of it", not harness.dead_cwd())
    finally:
        back_at_start()


def main() -> None:
    guard_names_the_offender()
    guard_is_silent_when_the_test_restored()
    guard_without_a_base_goes_to_the_plugin_root()
    run_scenarios_runs_the_guard()
    cleanup_goes_back_before_it_deletes()
    nested_records_keep_the_outermost_cwd()
    cleanup_of_another_root_does_not_move_the_process()
    cleanup_without_a_recorded_base_goes_to_the_plugin_root()
    a_real_driver_is_taken_out_before_the_delete()
    a_real_deletion_is_named_where_the_os_allows_it()
    finish("test_harness_cwd_guard")


if __name__ == "__main__":
    main()
