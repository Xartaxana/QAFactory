"""Two calls whose result nobody reads, kept because they are live (B-309 item "i"; t-425 kept them, no test said why).

  * `story_run.Driver.stage_S4` starts with a bare `self.stages()`: the stage table is `hooklib.load_ref_json("stages.json")["stages"]`,
    and a missing or broken table makes `load_ref_json` return {} so the index raises KeyError. That is a fail-fast guard: without
    it the KeyError comes later, after `pin_cases()` and `revise_plan()` have written. Live for its exception.
  * `hooklib.needs_guard` calls `resolve_app_root(cfg, event)` and ignores the answer: `project_root(event)` inside it fills the
    per-process root cache FROM THE EVENT's cwd. Every later `project_root()` of the guard process reads that cache; without the
    call it would walk from the process cwd instead. Live for its cache fill.

Runnable on its own: `python -B scripts/tests/test_bare_calls_live.py`."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import check_eq, cleanup, finish, temp_dir  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import hooklib  # noqa: E402
import story_run  # noqa: E402


def test_stage_s4_fails_fast_on_a_broken_stage_table() -> None:
    driver = object.__new__(story_run.Driver)        # no state at all: anything but the first line would raise AttributeError
    real = hooklib.load_ref_json
    try:
        hooklib.load_ref_json = lambda name: {}
        try:
            driver.stage_S4()
            got = "returned"
        except KeyError as exc:
            got = f"KeyError {exc}"
        except AttributeError:
            got = "AttributeError: reached the state before the stage table"
        check_eq("B1 a broken stage table stops stage_S4 on its FIRST line, before any state is touched", got, "KeyError 'stages'")
        hooklib.load_ref_json = real
        try:
            driver.stage_S4()
            got = "returned"
        except AttributeError:
            got = "AttributeError"
        check_eq("B1 control: with a real table the same bare object gets past the guard and fails on its missing state", got,
                 "AttributeError")
    finally:
        hooklib.load_ref_json = real


def test_needs_guard_pins_the_root_from_the_event() -> None:
    root = temp_dir("qa-bare-calls-")
    try:
        (root / "qa-factory").mkdir()
        (root / "qa-factory" / "config.json").write_text("{}", encoding="utf-8")
        with hooklib.selftest_root_restored():
            import os
            os.environ.pop("CLAUDE_PROJECT_DIR", None)
            hooklib._PROJECT_ROOT_CACHE = None
            answer = hooklib.needs_guard("ls", {}, {"cwd": str(root)})
            check_eq("B2 a plain command with no protected path needs no guard", answer, False)
            check_eq("B2 the root cache was filled from the event's cwd by the call nobody reads",
                     hooklib._PROJECT_ROOT_CACHE, root.resolve())
    finally:
        cleanup(root)


if __name__ == "__main__":
    test_stage_s4_fails_fast_on_a_broken_stage_table()
    test_needs_guard_pins_the_root_from_the_event()
    finish("bare_calls_live")
