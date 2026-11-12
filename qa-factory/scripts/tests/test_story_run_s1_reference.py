#!/usr/bin/env python3
"""t-2181 PC-9b (§3.1 item 2, F-4; joint plan t-2277 m-new-8): the S1 reference window, in process (SLOW: CI only, never run on a developer machine).

A seeded story is given a side with a `reference` stand; the driver's `stage_simple("S1")` runs with the role run, the walk session and
the controller faked, and spies on every call. What is proved:

  R1  `reference_window_opens_survey_env_walk`: after the scout (which does NOT close S1) one runner dispatch is registered with
      purpose `reference_walk`, and the walk session is opened with `walk_session.py open --place survey --env <reference> --walk <that
      dispatch id>`; the runner's role run closes the stage (`complete=True`) and closes the walk afterwards
  R2  the runner is told the put command; with a snapshot already on disk (S1 made again) the command carries `--replace`
  R3  a reference that cannot be reached: the walk is not opened, the DRIVER writes the gap-only snapshot (one gap line), the runner only hands over, no question
  R5  `rework S1` re-enters the window: the scout's rework leaves S1 open, the runner walks the reference again and its put carries --replace
  R6  the same rework on a story with no reference: one role run with the caller's `complete`, nothing registered
  (the controller here is a fake; the REAL controller, the exit gate and the stand rules are proved by the fast test_reference_window.py)
  R4  a story with no side carrying a reference: byte-identical S1 path - one role run (the scout), nothing registered, no walk opened
"""
import contextlib
import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import check, check_eq, check_in  # noqa: E402
from story_run_common import driver_for, run_scenarios, seed  # noqa: E402

KEY = "QA-9"
SIDES = {"product": {"reality": "real", "deliverable": True, "reference": "old", "source": "person"}}


def world(sides):
    """(root, task_root, driver, calls): a seeded story, the driver with its side effects replaced by spies."""
    import controller
    root, task_root, env = seed(KEY)
    if sides:
        harness.run_script("stage_done.py", "--task", KEY, "--set", "sides.product.reality=real", "--set", "sides.product.deliverable=true",
                           "--set", "sides.product.reference=old", "--set", "sides.product.source=person", cwd=root, env=env)
    driver = driver_for(root, env, KEY)
    calls = {"roles": [], "py": [], "dispatch": []}

    class FakeController:
        def __init__(self, *args, **kwargs):
            pass

        def state(self):
            return {"dispatches": {}}

        def prepare(self, request):
            calls["dispatch"].append(("prepare", dict(request)))
            return {"dispatch_request": dict(request)}

        def apply(self, operation, request):
            calls["dispatch"].append((operation, dict(request)))

    real_controller = controller.Controller
    controller.Controller = FakeController
    driver.controller_state = lambda: {"dispatches": {}}
    driver.record_running = lambda *a, **k: None

    def run_role(stage, role, **kwargs):
        calls["roles"].append((stage, role, kwargs))
        after = kwargs.get("after")
        if after:
            after({}, {})
        return ({}, {})
    driver.run_role = run_role
    walk_open_code = {"code": 0, "text": ""}

    def py(script, *args, **kwargs):
        calls["py"].append((script, args))
        return (walk_open_code["code"], walk_open_code["text"]) if args and args[0] == "open" else (0, "")
    driver.py = py
    return root, task_root, driver, calls, walk_open_code, real_controller


def teardown(root, real_controller):
    import controller
    controller.Controller = real_controller
    harness.cleanup(root)


def stage(driver):
    with contextlib.redirect_stdout(io.StringIO()):
        driver.stage_simple("S1")


def r1_reference_window_opens_survey_env_walk() -> None:
    root, task_root, driver, calls, _code, real = world(SIDES)
    try:
        stage(driver)
        roles = [(s, r, k.get("complete")) for s, r, k in calls["roles"]]
        check_eq("R1: the scout runs first and does not close S1; the runner's window closes it", roles,
                 [("S1", "qa-scout", False), ("S1", "qa-runner", True)])
        ops = [(op, req.get("purpose")) for op, req in calls["dispatch"]]
        check_eq("R1: one runner dispatch registered at S1 with purpose reference_walk (the purpose rides `prepare` too: the controller's kind rule)",
                 ops, [("prepare", "reference_walk"), ("dispatch", "reference_walk")])
        opened = [args for script, args in calls["py"] if script == "walk_session.py" and args[0] == "open"]
        check("R1: walk_session.py open once, --place survey --env old --walk <the runner's dispatch id>", len(opened) == 1 and "survey" in opened[0]
              and opened[0][opened[0].index("--env") + 1] == "old" and opened[0][opened[0].index("--walk") + 1] == "S1-qa-runner-1", str(opened))
        closed = [args for script, args in calls["py"] if script == "walk_session.py" and args[0] == "close"]
        check("R1: the walk is closed after the runner", len(closed) == 1 and "S1-qa-runner-1" in closed[0], str(closed))
        brief = " ".join(calls["roles"][1][2]["extra"])
        check_in("R2: the runner's brief names the put command", "reference_snapshot.py", brief)
        check("R2: no snapshot yet: no --replace", "--replace" not in brief, brief)
        check_eq("R1: the runner's role run carries purpose reference_walk", calls["roles"][1][2].get("purpose"), "reference_walk")
    finally:
        teardown(root, real)


def r2_rework_puts_with_replace() -> None:
    root, task_root, driver, calls, _code, real = world(SIDES)
    try:
        (task_root / "work").mkdir(parents=True, exist_ok=True)
        (task_root / "work" / "reference-snapshot.yaml").write_text("items: []\n", encoding="utf-8")
        stage(driver)
        check_in("R2: S1 made again over a snapshot - the runner's put carries --replace", "--replace", " ".join(calls["roles"][-1][2]["extra"]))
    finally:
        teardown(root, real)


def r3_unreachable_reference_is_one_gap_line() -> None:
    root, task_root, driver, calls, code, real = world(SIDES)
    try:
        code["code"], code["text"] = 3, json.dumps({"status": "refused", "reason": "no route to old"})
        stage(driver)
        brief = " ".join(calls["roles"][-1][2]["extra"])
        check_in("R3: the brief says the driver already wrote the gap-only snapshot (F5)", "already written", brief)
        import reference_snapshot
        check_eq("R3: and that snapshot holds the gap line with the probe's words", (reference_snapshot.read(task_root) or {}).get("gaps"),
                 ["the old version at old could not be reached: no route to old"])
        check("R3: no walk close for a walk that never opened", not [a for s, a in calls["py"] if a and a[0] == "close"], str(calls["py"]))
        check("R3: the runner's role run has no after hook", calls["roles"][-1][2].get("after") is None)
    finally:
        teardown(root, real)


def r4_no_reference_is_the_old_path() -> None:
    root, task_root, driver, calls, _code, real = world(None)
    try:
        stage(driver)
        check_eq("R4: one role run, the scout, with no `complete` forced", [(s, r, k.get("complete")) for s, r, k in calls["roles"]],
                 [("S1", "qa-scout", None)])
        check_eq("R4: nothing registered, no walk opened", (calls["dispatch"], calls["py"]), ([], []))
    finally:
        teardown(root, real)


def r5_rework_s1_re_enters_the_window() -> None:
    """t-2277 batch 2b D (critic t-2513 F1): `Driver.rework("S1", scout)` over an accepted S1 with a snapshot on disk: the scout's rework does NOT
    close S1, the runner walks the reference again and its put
    carries --replace. The controller's `rework` answer is faked (the real rework operation is the controller's own tests)."""
    root, task_root, driver, calls, _code, real = world(SIDES)
    try:
        (task_root / "work").mkdir(parents=True, exist_ok=True)
        (task_root / "work" / "reference-snapshot.yaml").write_text("items: []\n", encoding="utf-8")
        driver.controller = lambda op, *args, **kw: {"request": {"id": "S1-qa-scout-2", "scope": []}}
        with contextlib.redirect_stdout(io.StringIO()):
            driver.rework("S1", "qa-scout", [], "the ticket changed", cause="ticket_changed", complete=True)
        check_eq("R5: the scout's rework leaves S1 open, the runner's window closes it",
                 [(s, r, k.get("complete")) for s, r, k in calls["roles"]], [("S1", "qa-scout", False), ("S1", "qa-runner", True)])
        check_in("R5: the old snapshot is replaced - the put carries --replace", "--replace", " ".join(calls["roles"][1][2]["extra"]))
        opened = [args for script, args in calls["py"] if script == "walk_session.py" and args[0] == "open"]
        check("R5: the survey walk opens on the reference stand again", len(opened) == 1 and opened[0][opened[0].index("--env") + 1] == "old", str(opened))
    finally:
        teardown(root, real)


def r6_rework_of_a_story_with_no_reference_is_the_old_path() -> None:
    """t-2277 batch 2b D, edge: `rework S1` on a story with no reference stand runs the scout with the caller's `complete` and nothing more."""
    root, task_root, driver, calls, _code, real = world(None)
    try:
        driver.controller = lambda op, *args, **kw: {"request": {"id": "S1-qa-scout-2", "scope": []}}
        with contextlib.redirect_stdout(io.StringIO()):
            driver.rework("S1", "qa-scout", [], "the ticket changed", cause="ticket_changed", complete=True)
        check_eq("R6: one role run with `complete` as given, nothing registered, no walk", ([(s, r, k.get("complete")) for s, r, k in calls["roles"]],
                 calls["dispatch"], calls["py"]), ([("S1", "qa-scout", True)], [], []))
    finally:
        teardown(root, real)


def main() -> None:
    run_scenarios([], [r1_reference_window_opens_survey_env_walk, r2_rework_puts_with_replace,
                       r3_unreachable_reference_is_one_gap_line, r4_no_reference_is_the_old_path,
                       r5_rework_s1_re_enters_the_window, r6_rework_of_a_story_with_no_reference_is_the_old_path])
    harness.finish("test_story_run_s1_reference")


if __name__ == "__main__":
    main()
