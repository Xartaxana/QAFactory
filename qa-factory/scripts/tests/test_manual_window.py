#!/usr/bin/env python3
"""SC2-38 item 3 (node N3, spec r0107-s3c-sc2-17-19-38 section 5): the manual runner window is ONE case, run in turn.

  K3-1  `manual_blocks` with the window size (E3, E4); the default and size 5 keep the old cut
  K3-2  the door of `start` offers one case and counts the rest (E1, E3, E6)
  K3-3  `Driver.manual_plan` and the door cut the same cases the same way (twins); the cost of the re-prepare per entry (E8)
  K3-4  the ceiling stays: a `--scope` of 5 is accepted, of 6 refused (E2)
  K3-5  a story in flight: an accepted block of 3 is not offered again, the rest goes one by one (E5)
  K3-6  `story_progress._block_position` counts windows by the window size
  K3-7  `qa-runner.md` no longer promises a concurrent run (control inside)
  K3-8  a rework of 6 cases keeps its ceiling-sized blocks and its door (E11)

Each check names the ONE mutation that kills it. Fixtures are those of `test_story_step_manual_block.py`.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import check, check_eq, check_in, check_not_in, cleanup, finish, temp_dir  # noqa: E402

sys.path.insert(0, str(harness.SCRIPTS))
import controller  # noqa: E402
from controller import MANUAL_BLOCK_CASES, MANUAL_WINDOW_CASES, manual_blocks  # noqa: E402
import test_story_step_manual_block as MB  # noqa: E402  (real_story, start, accept, door_scope, MIXED_7)


def the_split_by_the_window():
    """K3-1 (E3, E4). KILLS: the default of `manual_blocks` turned into 1 (K-S3 and this); the window constant not 1."""
    check_eq("K3-1: the window is three cases (t-1957 N5s), the ceiling is still five", (MANUAL_WINDOW_CASES, MANUAL_BLOCK_CASES), (3, 5))
    check_eq("K3-1: three cases are one window", manual_blocks(["a", "b", "c"], MANUAL_WINDOW_CASES), [["a", "b", "c"]])
    check_eq("K3-1: four cases are 3 + 1", manual_blocks(["a", "b", "c", "d"], MANUAL_WINDOW_CASES), [["a", "b", "c"], ["d"]])
    check_eq("K3-1: one case is one window", manual_blocks(["a"], MANUAL_WINDOW_CASES), [["a"]])
    check_eq("K3-1: nothing is nothing", manual_blocks([], MANUAL_WINDOW_CASES), [])
    check_eq("K3-1: the default cut is the old one (5 is one block)", manual_blocks(list("abcde")), [list("abcde")])
    check_eq("K3-1: size 5 is the old cut (6 is 5 + 1)", manual_blocks(list("abcdef"), 5), [list("abcde"), ["f"]])
    try:
        manual_blocks(["a"], 0)
        raised = False
    except ValueError:
        raised = True
    check_eq("K3-1: E4, a size below 1 is still a ValueError", raised, True)


def the_door_offers_one_case():
    """K3-2 (E1, E3, E6). KILLS: the door cut by the default; a literal 5 in the tail."""
    root = temp_dir("qa-win-door-")
    try:
        c = MB.real_story(root, MB.MIXED_7)
        for label, scope in (("no --scope", None), ("an empty one", "")):
            code, text, _ = MB.start(root, c, scope)
            check_eq(f"K3-2: {label}: refused, the door is the first lane of three", (code, MB.door_scope(text)), (2, "TC-2,TC-3,TC-4"))
        check_in("K3-2: the tail counts the rest and says the size", "then 1 more block(s) of at most 3 case(s) for: TC-5, TC-6, TC-7", text)
        check_not_in("K3-2: no literal 5 in the tail", "of at most 5", text)
        # E6: a case `prepare` refuses is not silently dropped; the door is the next window of the cleaned rest
        refuse_2 = lambda case: ([], "no executable obligation") if case == "TC-2" else ([f"OB-{case}"], "")  # noqa: E731
        code, text, _ = MB.start(root, c, "TC-2,TC-3", prepare=refuse_2)
        check_eq("K3-2: E6, the refused case is named and the door is the other one", (code, MB.door_scope(text)), (2, "TC-3"))
        check_in("K3-2: E6, the refusal line stays", "TC-2: not checked by hand - no executable obligation", text)
    finally:
        cleanup(root)


def the_driver_and_the_door_are_twins():
    """K3-3 (E8). KILLS: the driver on the old size while the door is a window (`MANUAL_BLOCK_MAX = MANUAL_BLOCK_CASES`)."""
    import story_run
    check_eq("K3-3: the driver's size is the window", story_run.Driver.MANUAL_BLOCK_MAX, MANUAL_WINDOW_CASES)
    cases = [f"TC-{n}" for n in range(2, 8)]
    calls, done = [], set()
    driver = story_run.Driver.__new__(story_run.Driver)
    driver.task_root = Path(temp_dir("qa-win-nofiles-"))     # no request files there: no case names an account (one lane)
    driver.manual_done = lambda: set(done)
    driver.manual_order = lambda given: list(given)
    driver.manual_prepare = lambda case: (calls.append(case) or ([f"OB-{case}"], "", ""))
    plan = driver.manual_plan(cases)
    check_eq("K3-3: the driver cuts the cases (no account named: one lane) into windows of three", plan["blocks"],
             [cases[:3], cases[3:]])
    root = temp_dir("qa-win-twin-")
    try:
        c = MB.real_story(root, MB.MIXED_7)
        _, text, _ = MB.start(root, c, None)
        offered = MB.door_scope(text).split(",") + [x.strip() for x in text.split("for: ", 1)[1].split(";", 1)[0].split(",")]
        check_eq("K3-3: the door offers the same cases in the same order", offered, [x for b in plan["blocks"] for x in b])
    finally:
        cleanup(root)
    # E8: every entry prepares ALL the cases left; with a window of three that is n + (n - 3) + ... + 3
    many = [f"TC-{n}" for n in range(1, 16)]
    for size, expected in ((MANUAL_WINDOW_CASES, 45), (MANUAL_BLOCK_CASES, 30)):
        calls.clear()
        done.clear()
        driver.MANUAL_BLOCK_MAX = size
        while True:
            blocks = driver.manual_plan(many)["blocks"]
            if not blocks:
                break
            done.update(blocks[0])
        check_eq(f"K3-3: 15 cases, size {size}: the prepare calls over all entries", len(calls), expected)


def the_ceiling_stays():
    """K3-4 (E2). KILLS: `validate_manual_runner_block` or `manual_block_problems` moved to the window size."""
    for count, code_expected in ((5, 0), (6, 2)):
        root = temp_dir("qa-win-ceiling-")
        try:
            c = MB.real_story(root, ["automate"] + ["manual-agent"] * 6)
            scope = ",".join(f"TC-{n}" for n in range(2, 2 + count))
            code, text, _ = MB.start(root, c, scope)
            check_eq(f"K3-4: --scope of {count}: exit", code, code_expected)
            if code_expected:
                check_in("K3-4: beyond the ceiling the old refusal", "it names 6 cases, at most 5: split the block", text)
        finally:
            cleanup(root)


def a_story_in_flight():
    """K3-5 (E5). KILLS: the accepted cases repeated in the door; the rest offered as one block."""
    root = temp_dir("qa-win-flight-")
    try:
        c = MB.real_story(root, MB.MIXED_7)
        MB.start(root, c, "TC-2,TC-3,TC-4")
        MB.accept(c, root, "S6-qa-runner-1", "manual", ["TC-2", "TC-3", "TC-4"])
        code, text, _ = MB.start(root, c, None)
        check_eq("K3-5: an accepted block of three is not offered again; the rest is the next lane", (code, MB.door_scope(text)),
                 (2, "TC-5,TC-6,TC-7"))
        check_not_in("K3-5: ...and nothing is left to count", "more block(s)", text)
    finally:
        cleanup(root)


def progress_counts_windows():
    """K3-6. KILLS: `story_progress` left on `MANUAL_BLOCK_CASES`."""
    import story_progress as SP
    ids = [f"QA-9_TC_{n:03d}" for n in range(1, 8)]
    first = {"id": "S6-qa-runner-2", "stage": "S6", "role": "qa-runner", "status": "running", "scope": ids[:2],
             "execution_kind": "manual", "manual_case_ids": ids[:2]}
    saved = SP._scope_of
    SP._scope_of = lambda *_a, **_k: {"derived": True, "scope": ids}
    try:
        got = SP._block_position(None, {}, [first], first, "QA-9")
        check_eq("K3-6: 5 cases left, a window of three: 1 in flight + 2", got["blocks_total"], 3)
    finally:
        SP._scope_of = saved


def the_runner_sequencing_line():
    """K3-7. KILLS: the `run.parallel` promise back in `qa-runner.md`."""
    text = (harness.PLUGIN_ROOT / "agents" / "qa-runner.md").read_text(encoding="utf-8")
    # X7-3: the runner is a charter with no numbered items (R-drop of the item number); the promise is looked for in the whole text
    check_not_in("K3-7: no concurrent run is promised", "run.parallel", text)
    old = "7. **Sequencing.** Blocks run in turn; two run concurrently only when\n   `config.run.parallel` is `true`."
    check("K3-7 negative control: the old text carries the promise", "run.parallel" in old)


def a_rework_keeps_the_ceiling():
    """K3-8 (E11). KILLS: `_rework_block_problems` or the rework door moved to the window size."""
    cases = [f"TC-{n}" for n in range(2, 8)]
    ctl = controller.Controller.__new__(controller.Controller)
    ctl._half_membership_problems = lambda *a, **k: []
    problems = ctl._rework_block_problems("S6", {}, cases)
    check_eq("K3-8: six cases are one problem", len(problems), 1)
    check_in("K3-8: the old size sentence", "it names 6 cases, at most 5: split the block", problems[0])
    check_in("K3-8: the door is the first FIVE", "--cases TC-2,TC-3,TC-4,TC-5,TC-6 ", problems[0])
    check_in("K3-8: and the one left, with the ceiling", "then 1 more block(s) of at most 5 for: TC-7", problems[0])
    check_eq("K3-8: five cases are no problem", ctl._rework_block_problems("S6", {}, cases[:5]), [])


def main():
    the_split_by_the_window()
    the_door_offers_one_case()
    the_driver_and_the_door_are_twins()
    the_ceiling_stays()
    a_story_in_flight()
    progress_counts_windows()
    the_runner_sequencing_line()
    a_rework_keeps_the_ceiling()
    finish("test_manual_window")


if __name__ == "__main__":
    main()
