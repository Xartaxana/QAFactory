#!/usr/bin/env python3
"""GB-1b (t-1509, HF5-17): the driver carries out the orders gate B gave, and settles them.

The driver half of the model `test_gate_b_orders.py` pins on the controller's side. Run 12586: the person chose two bug drafts at
gate B; the story counted itself closed and the reporter was refused. Since 0.10.5 gate B gives ORDERS (`bugs` to the bug reporter,
`mr` to the delivery step); `next` says `execute_gate_b` while one is due, `Driver._act_execute_gate_b` -> `after_gate_B` carries
them out and the controller says `closed` after every order is done or called off.

Keys of spec §5.1b: K9 the seam over the recorded run (the real controller, the real `story_step.py start`; only the agent and the
conductor are stubs), K9r a released reporter is never sent again, K9s two passes that move nothing end in the seam, K12 `no
delivery` calls off the MR with the person's words and the reporter still runs, K14 the crash between the delivery mark and
`settle_order` (the delivery never runs twice; `mr: done` only with a record of the MR), K15 a decision of 0.10.4 (no orders).

The fixture `fixtures/run-12586-gate-b` holds the decision recorded by 0.10.4 (no orders). Every key that needs orders first records
a NEW decision on a throwaway COPY with `--bugs ordered --mr open`; the committed fixture is never written.
"""
import contextlib
import io
import json
import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import (SCRIPTS, check, check_eq, check_in, check_not_in, cleanup, finish,  # noqa: E402
                     run_script, temp_project, use_project)

sys.path.insert(0, str(SCRIPTS))
import controller as CTL  # noqa: E402
from controller import Controller  # noqa: E402

from story_run_common import driver_for, run_scenarios  # noqa: E402

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "run-12586-gate-b" / "TP1-12586"
TASK = "TP1-12586"
DRAFTS = ["ms-teams-move-project-mismatch", "ms-teams-occupied-project-mismatch"]
GATE_B_WORDS = "file both bugs and open the merge request\n"
MR_URL = "https://example.invalid/mr/1"
REPORTER = "S8-qa-bug-reporter-1"


def project_env(root):
    return dict(os.environ, CLAUDE_PROJECT_DIR=str(root), PYTHONDONTWRITEBYTECODE="1")


def quiet(call, *args, **kwargs):
    with contextlib.redirect_stdout(io.StringIO()):
        return call(*args, **kwargs)


def story(prefix, *, decide=True, mr="open", bugs="ordered", drafts=DRAFTS):
    """(root, task root, driver, calls): a throwaway COPY of the recorded run 12586 (the decision of 0.10.4), with - when `decide` -
    a NEW gate B decision recorded on it through the controller's own builder, so its orders are written the way the CLI writes
    them. The driver is the real one over that copy; `calls` records what the stubs were asked (`reporter`, `conductor`)."""
    root = temp_project(prefix)
    use_project(root)
    task_root = root / "qa-factory" / "artifacts" / TASK
    shutil.copytree(FIXTURE, task_root)
    c = Controller(task_root)
    c._project_pipeline(CTL.projection(c.store.read()))
    if decide:
        c.apply("decision", c.build_gate_decision("B", GATE_B_WORDS, list(drafts), bugs=bugs, mr=mr))
    return root, task_root, new_driver(root, task_root, [])[0], []


RELEASE_WORDS = "leave the drafts, no bug now"


def new_driver(root, task_root, calls, verdict=None, release=False):
    """A driver (one more process over the same story) with the agent and the conductor replaced: the reporter is the REAL
    `story_step.py start` followed by an accept (the stub is only the agent that would have done the work), the conductor's
    answer is `verdict` (default: a delivery that opened `MR_URL`). The checks of the delivery verdict (`recompute_verdict`) are
    not what is under test and answer `no`."""
    env = dict(os.environ, STORY_RUN_CLAUDE=str(root / "unused"), STUB_CONTROL=str(root / "unused"), STUB_LOG=str(root / "unused"))
    driver = driver_for(root, env, TASK)
    driver.recompute_verdict = lambda: "no"
    answer = verdict if verdict is not None else {"action": "continue", "did": "pushed branch qa/x and opened a Draft MR", "mr": MR_URL}

    def run_role(stage, role, **kwargs):
        calls.append(("reporter", role))
        started = run_script("story_step.py", "start", "--task", TASK, "--stage", stage, "--role", role, cwd=root, env=project_env(root))
        check(f"the stub reporter starts through the real story_step ({stage} {role})", started.returncode == 0, (started.stdout + started.stderr)[-400:])
        c = Controller(task_root)
        if release:                      # a person's word ends the executor (B4): the order is called off by the projection
            c.release_dispatch(REPORTER, RELEASE_WORDS)
        else:
            c.store.commit("accept", {"id": REPORTER, "status": "accepted", "stage_complete": False}, "acc:" + REPORTER, None, None, c.project)
        return "", None

    def run_claude(kind, prompt, **kwargs):
        calls.append(("conductor", kind))
        return {"result": "delivered\n" + json.dumps(answer), "session_id": "s-1", "total_cost_usd": 0.0, "num_turns": 1}
    driver.run_role, driver.run_claude = run_role, run_claude
    return driver, calls


def state_of(task_root):
    return Controller(task_root).state()


def orders_of(task_root):
    return CTL.gate_b_orders(state_of(task_root))


def mark_of(task_root):
    path = task_root / "state" / "driver-state.json"
    return (json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}).get("delivery") or {}


def settled(task_root, order):
    decision = CTL.latest_gate_b(state_of(task_root)) or {}
    return (decision.get("orders_settled") or {}).get(order) or {}


def count(calls, kind):
    return len([c for c in calls if c[0] == kind])


def next_of(task_root):
    return Controller(task_root).next_action()


# --- K9: the seam -----------------------------------------------------------------------------------------

def k9_the_driver_carries_out_both_orders_and_the_story_closes():
    root, task_root, driver, calls = story("qa-gbd-k9-")
    try:
        driver, calls = new_driver(root, task_root, calls)
        action = next_of(task_root)
        check_eq("K9: the new decision orders both: next is execute_gate_b with bugs and mr due",
                 (action["action"], [o["order"] for o in action["orders"]]), ("execute_gate_b", ["bugs", "mr"]))
        quiet(driver.dispatch_action, action)
        check_eq("K9: the real reporter ran once and the conductor once", (count(calls, "reporter"), count(calls, "conductor")), (1, 1))
        check_eq("K9: bugs is done by the accepted reporter (the projection), mr by settle_order", (orders_of(task_root)["bugs"], orders_of(task_root)["mr"]), ("done", "done"))
        check_eq("K9: the mr order was settled `done` with the MR the delivery named",
                 (settled(task_root, "mr").get("outcome"), settled(task_root, "mr").get("ref")), ("done", MR_URL))
        check_eq("K9: next is now closed (the retro, S9)", (next_of(task_root)["action"], next_of(task_root).get("stage")), ("closed", "S9"))
        check_eq("K9: the delivery mark carries the MR as a field", mark_of(task_root).get("mr"), MR_URL)
    finally:
        cleanup(root)


def k9r_a_released_reporter_is_never_sent_again():
    """B4: a person's release of the reporter calls `bugs` off. The delivery then asks the person (`ask_person`), so the story is
    still `executing` with `mr` due - the one state where a driver that dispatches the reporter on a due-looking executor would
    send it again. A NEW process (empty `gate_b_ran`) takes the next `execute_gate_b`: no second dispatch, then `closed`."""
    import story_run
    root, task_root, driver, calls = story("qa-gbd-k9r-")
    try:
        driver, calls = new_driver(root, task_root, calls, verdict={"action": "ask_person", "did": "", "question": "Which reviewer?"}, release=True)
        try:
            quiet(driver.dispatch_action, next_of(task_root))
            asked = None
        except story_run.Person as exc:
            asked = exc
        check("K9r: the delivery asked the person (the story stays open)", asked is not None and asked.kind == "delivery", str(asked))
        check_eq("K9r: the reporter ran once, and its release cancelled bugs with the person's words",
                 (count(calls, "reporter"), settled(task_root, "bugs").get("outcome"), settled(task_root, "bugs").get("words")),
                 (1, "cancelled", RELEASE_WORDS))
        action = next_of(task_root)
        check_eq("K9r: next still asks for the MR only; the released reporter is not an order any more",
                 (action["action"], [o["order"] for o in action["orders"]]), ("execute_gate_b", ["mr"]))
        again, calls = new_driver(root, task_root, calls)
        quiet(again.dispatch_action, action)
        check_eq("K9r: the new process dispatched no reporter (still one) and the delivery ran again for its answer",
                 (count(calls, "reporter"), count(calls, "conductor")), (1, 2))
        check_eq("K9r: next is closed; bugs stayed cancelled, mr is done",
                 (next_of(task_root)["action"], orders_of(task_root)["bugs"], orders_of(task_root)["mr"]), ("closed", "cancelled", "done"))
        quiet(again.after_gate_B)
        check_eq("K9r: a repeat of the pass on the closed story dispatches nothing", (count(calls, "reporter"), count(calls, "conductor")), (1, 2))
    finally:
        cleanup(root)


def k9s_two_passes_that_move_nothing_end_in_the_seam():
    """AR-17, FR-48: a pass that moved no order is looked at again by the loop; the SECOND goes to the one seam (`no_move`) and
    there is never a third pass. A pass that moved an order starts the count again."""
    root, task_root, driver, calls = story("qa-gbd-k9s-")
    try:
        passes, seam = [], []
        driver.after_gate_B = lambda: passes.append("pass")
        driver.no_move = lambda state, moves=None: seam.append(state) or "continue"
        action = next_of(task_root)
        quiet(driver._act_execute_gate_b, action)
        check_eq("K9s: pass 1 moved nothing: looked at again, the seam is not called", (len(passes), len(seam)), (1, 0))
        quiet(driver._act_execute_gate_b, action)
        check_eq("K9s: pass 2 moved nothing: the seam is called ONCE, with two passes behind it and no third", (len(passes), len(seam)), (2, 1))
        state = seam[0] if seam else {}
        check_eq("K9s: the seam gets the threshold reason at S8", (state.get("why"), state.get("stage")), ("threshold", "S8"))
        check_in("K9s: its lead names both orders in words", "the bug reports and the merge request", state.get("lead", ""))
        check_not_in("K9s: and no command or flag", "--", state.get("lead", ""))
        # the count starts again: one idle pass, then a pass that moves an order, then one idle pass - no seam yet
        driver.gate_b_idle = 0
        quiet(driver._act_execute_gate_b, action)
        driver.after_gate_B = lambda: driver.controller("settle_order", "--order", "mr", "--outcome", "done", "--ref=https://example.invalid/mr/9")
        quiet(driver._act_execute_gate_b, action)
        check_eq("K9s: a pass that moved an order resets the count (no seam)", (driver.gate_b_idle, len(seam)), (0, 1))
        driver.after_gate_B = lambda: passes.append("pass")
        quiet(driver._act_execute_gate_b, next_of(task_root))
        check_eq("K9s: and the next idle pass is the first again", (driver.gate_b_idle, len(seam)), (1, 1))
    finally:
        cleanup(root)


def k14_a_crash_between_the_mark_and_settle_order_never_runs_the_delivery_twice():
    """t-017 D3 + B5: the delivery has outward effects and never runs twice. The first process dies (an exception in the
    controller call) right after the mark is written; the next one settles `mr` from the mark. `mr: done` only with a record of
    the MR: a mark without one is `cancelled delivered_without_mr`, a mark of an experiment is `cancelled no_trace`."""
    root, task_root, driver, calls = story("qa-gbd-k14-")
    try:
        driver, calls = new_driver(root, task_root, calls)
        real = driver.controller

        def killed(operation, *args, **kwargs):
            if operation == "settle_order":
                raise KeyboardInterrupt("the process was killed before settle_order")
            return real(operation, *args, **kwargs)
        driver.controller = killed
        try:
            quiet(driver.dispatch_action, next_of(task_root))
            died = False
        except KeyboardInterrupt:
            died = True
        check("K14: the first process died at settle_order", died)
        check_eq("K14: the mark is on disk with the MR, the order is still due, the conductor was called once",
                 (mark_of(task_root).get("mr"), orders_of(task_root)["mr"], count(calls, "conductor")), (MR_URL, "due", 1))
        action = next_of(task_root)
        check_eq("K14: next asks for the MR order only (the reporter is done)", (action["action"], [o["order"] for o in action["orders"]]), ("execute_gate_b", ["mr"]))
        second, calls = new_driver(root, task_root, calls)
        quiet(second.dispatch_action, action)
        check_eq("K14: the second process settled `mr` from the mark: done with the MR as its ref",
                 (settled(task_root, "mr").get("outcome"), settled(task_root, "mr").get("ref")), ("done", MR_URL))
        check_eq("K14: the conductor was called exactly ONCE across the crash; the reporter once", (count(calls, "conductor"), count(calls, "reporter")), (1, 1))
        check_eq("K14: next is closed", next_of(task_root)["action"], "closed")
        quiet(second.after_gate_B)
        check_eq("K14: a third pass repeats nothing (same key: no new event, no new call)", (count(calls, "conductor"), orders_of(task_root)["mr"]), (1, "done"))
    finally:
        cleanup(root)
    # a mark with no record of an MR is never `done`, whatever shape the missing record has (FR-41)
    for label, verdict, outcome, code in (
            ("an empty mr", {"action": "continue", "did": "committed; the person said no MR", "mr": ""}, "cancelled", "delivered_without_mr"),
            ("no mr field (an older conductor)", {"action": "continue", "did": "pushed branch qa/x and opened MR !7"}, "cancelled", "delivered_without_mr"),
            ("a blank mr", {"action": "continue", "did": "pushed", "mr": "   "}, "cancelled", "delivered_without_mr"),
            ("a boolean mr", {"action": "continue", "did": "pushed", "mr": True}, "cancelled", "delivered_without_mr"),
            ("a list mr", {"action": "continue", "did": "pushed", "mr": ["https://example.invalid/mr/1"]}, "cancelled", "delivered_without_mr"),
            ("a word, not a record (F6)", {"action": "continue", "did": "pushed", "mr": "none"}, "cancelled", "delivered_without_mr"),
            ("a phrase, not a record (F6)", {"action": "continue", "did": "pushed", "mr": "not opened"}, "cancelled", "delivered_without_mr"),
            ("a link (F6)", {"action": "continue", "did": "pushed", "mr": "https://x/mr/1"}, "done", None),
            ("an id token (F6)", {"action": "continue", "did": "pushed", "mr": "!42"}, "done", None),
            ("a whole-number mr (an id)", {"action": "continue", "did": "pushed", "mr": 42}, "done", None)):
        root, task_root, driver, calls = story("qa-gbd-k14m-")
        try:
            driver, calls = new_driver(root, task_root, calls, verdict=verdict)
            quiet(driver.dispatch_action, next_of(task_root))
            entry = settled(task_root, "mr")
            check_eq(f"K14 {label}: the order ended `{outcome}`", orders_of(task_root)["mr"], outcome)
            check_eq(f"K14 {label}: its reason code", entry.get("reason_code"), code)
            if outcome == "done":
                check_eq(f"K14 {label}: and the record is the verdict's own", entry.get("ref"), str(verdict["mr"]))
            else:
                check(f"K14 {label}: never `done`, and the step's own record is the ref", entry.get("outcome") != "done" and bool(entry.get("ref")), str(entry))
            check_eq(f"K14 {label}: the story is closed after it", next_of(task_root)["action"], "closed")
        finally:
            cleanup(root)
    # an experiment sends nothing: the null outcome is a coded cancel, and the conductor is never called
    root, task_root, driver, calls = story("qa-gbd-k14n-")
    try:
        driver, calls = new_driver(root, task_root, calls)
        driver.no_trace = lambda: True
        quiet(driver.dispatch_action, next_of(task_root))
        check_eq("K14 experiment: the mark is nothing_outward, mr cancelled `no_trace`, the conductor never called",
                 (mark_of(task_root).get("action"), settled(task_root, "mr").get("reason_code"), count(calls, "conductor")),
                 ("nothing_outward", "no_trace", 0))
    finally:
        cleanup(root)


def k15_a_decision_of_0_10_4_keeps_its_old_road():
    """B6: a decision recorded before 0.10.5 carries no orders. With no delivery mark the delivery is called as it always was;
    with one it is not; `settle_order` is never called (no order of `mr` is tracked). A decision WITH orders whose `mr` is not
    ordered (`do_not_open`) never runs the delivery either."""
    root, task_root, driver, calls = story("qa-gbd-k15-", decide=False)
    try:
        check_eq("K15: the fixture's own decision carries no orders (bugs derived from the drafts, mr not ordered)",
                 (orders_of(task_root), "orders" in (CTL.latest_gate_b(state_of(task_root)) or {})), ({"bugs": "due", "mr": "not_ordered"}, False))
        operations = []
        real = driver.controller
        driver.controller = lambda operation, *a, **k: operations.append(operation) or real(operation, *a, **k)
        driver.delivery = lambda decision: calls.append(("delivery", "called"))
        driver.recompute_verdict = lambda: "no"
        quiet(driver.after_gate_B)
        check_eq("K15 without a mark: delivery() is called once (the old road)", count(calls, "delivery"), 1)
        driver.state["delivery"] = {"done": True, "at": "2026-10-28T10:00:00", "action": "continue", "did": "delivered", "mr": MR_URL}
        quiet(driver.after_gate_B)
        check_eq("K15 with a mark: delivery() is not called again", count(calls, "delivery"), 1)
        check_not_in("K15: settle_order is never called, with the mark or without it", "settle_order", operations)
        check_eq("K15: and the MR order stays not ordered", orders_of(task_root)["mr"], "not_ordered")
    finally:
        cleanup(root)
    root, task_root, driver, calls = story("qa-gbd-k15d-", mr="do_not_open")
    try:
        driver, calls = new_driver(root, task_root, calls)
        driver.delivery = lambda decision: calls.append(("delivery", "called"))
        quiet(driver.after_gate_B)
        check_eq("K15 `do_not_open`: the reporter runs, the delivery does not, mr stays not ordered",
                 (count(calls, "reporter"), count(calls, "delivery"), orders_of(task_root)["mr"]), (1, 0, "not_ordered"))
        check_eq("K15 `do_not_open`: and the story is closed by the reporter's accept", next_of(task_root)["action"], "closed")
    finally:
        cleanup(root)


def main() -> None:
    run_scenarios([], [
        k9_the_driver_carries_out_both_orders_and_the_story_closes,
        k9r_a_released_reporter_is_never_sent_again,
        k9s_two_passes_that_move_nothing_end_in_the_seam,
        k14_a_crash_between_the_mark_and_settle_order_never_runs_the_delivery_twice,
        k15_a_decision_of_0_10_4_keeps_its_old_road,
    ])
    finish("test_gate_b_driver")


if __name__ == "__main__":
    main()
