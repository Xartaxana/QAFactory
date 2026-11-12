#!/usr/bin/env python3
"""jobs guard: a part of test_controller_rework.py, split by tools/test_split.py (TD-11c). The shared helpers are in controller_rework_common."""
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import SCRIPTS, check_eq, check_in, cleanup, finish, s5_apply, temp_dir, temp_project
sys.path.insert(0, str(SCRIPTS))
import person_words  # noqa: E402
import stage_guard  # noqa: E402
from controller import DISPATCH_DEFAULTS, Controller
from event_store import StateConflict  # noqa: E402
sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_controller_state as BASE  # noqa: E402
import test_controller_rework_scope as SCOPED  # noqa: E402  (plan_row/gate_a_task fixtures)
import test_dispatch_liveness as LIFE  # noqa: E402  (transcript/fake_hooklib fixtures)
from controller_rework_common import AUTOMATOR, at_s5, host_receipt  # noqa: E402


def journal(root, records):
    path = root / "qa-factory" / "records" / "journal.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")


# --- a dispatch nobody is doing is not a job to wait for -----------------------------------

def next_never_waits_for_an_agent_that_was_never_launched():
    root = temp_project("qa-never-started-")
    try:
        controller = at_s5(root)
        check_eq("the stuck state is the one the person saw",
                 controller._next_action_for_state(controller.state())["action"], "wait_existing_job")
        # What a launch really leaves behind on this host: the OTHER roles' transcripts. The
        # automator's receipt is ten minutes old and no transcript names it.
        LIFE.fake_hooklib([LIFE.transcript(root, "critic", "S4-qa-case-critic-1",
                                           role="qa-case-critic", ticket=root.name, age=30)])
        # The receipt here is seconds old, so the project's own waiting time is the honest way
        # to reach the threshold; a story in flight is never closed before it passes.
        early = Controller(root).next_action()
        check_eq("seconds after the receipt the factory says it cannot tell yet",
                 (early["action"], early["liveness"]), ("wait_existing_job", "unknown"))
        (root / "qa-factory" / "config.json").write_text(
            json.dumps({"dispatch": {"never_started_after_s": 0.01}}), encoding="utf-8")
        action = Controller(root).next_action()
        check_eq("next closes it instead of telling the story to wait",
                 action["action"], "relaunch")
        check_eq("and hands over the packet that starts the work again",
                 action["dispatch_request"]["role"], "qa-automator")
        check_eq("with the scope and inputs of the receipt that never reached an agent",
                 (action["dispatch_request"]["scope"], action["dispatch_request"]["input_hash"]),
                 (["TC-1"], "s5-input"))
        check_eq("under an id that does not collide with it",
                 action["dispatch_request"]["id"], "S5-qa-automator-2")
        state = Controller(root).state()
        check_eq("the receipt is kept, marked for what it was",
                 state["dispatches"][AUTOMATOR]["status"], "never_started")
        check_in("the journalled reason says why the factory believes it",
                 "no subagent transcript names this dispatch",
                 state["dispatches"][AUTOMATOR].get("reason", ""))
        check_eq("and S5 is startable again", state["stages"]["S5"]["status"], "pending")
        check_eq("a second pass has nothing left to close",
                 Controller(root).never_started_fixes(), [])
        check_eq("and recover agrees with next", Controller(root).recover()["journalled_repairs"], [])
        s5_apply(controller, dict(action["dispatch_request"]))
        check_eq("the relaunch packet dispatches as it stands",
                 Controller(root).state()["dispatches"]["S5-qa-automator-2"]["status"], "running")
    finally:
        LIFE.without_hooklib()
        cleanup(root)


def a_working_agent_is_still_waited_for():
    root = temp_project("qa-launched-")
    try:
        controller = at_s5(root)
        LIFE.fake_hooklib([LIFE.transcript(root, "auto", AUTOMATOR, ticket=root.name, age=5)])
        check_eq("a transcript written five seconds ago closes nothing",
                 controller.liveness_fixes(), [])
        action = Controller(root).next_action()
        check_eq("so next still waits for the job", action["action"], "wait_existing_job")
        check_eq("and says on what evidence", action["liveness"], "alive")
    finally:
        LIFE.without_hooklib()
        cleanup(root)


def a_host_receipt_is_evidence_too():
    root = temp_project("qa-host-receipt-")
    try:
        controller = at_s5(root)
        host_receipt(root, agent_id="a1", agent_type="qa-automator", task_id=root.name,
                     dispatch_id=AUTOMATOR, status="running")
        check_eq("a live host binding for this dispatch is evidence of a launch",
                 controller.liveness_fixes(), [])
    finally:
        cleanup(root)


def a_host_that_records_nothing_is_left_alone():
    """Absence of a record is evidence only on a host that keeps records. A bundled runtime
    journals no subagent_stop at all, and a job running there is still a job."""
    root = temp_project("qa-silent-host-")
    try:
        controller = at_s5(root)
        LIFE.without_hooklib()
        check_eq("with nothing recorded for this story nothing is closed",
                 controller.liveness_fixes(), [])
        action = Controller(root).next_action()
        check_eq("and next answers exactly as it did before", action["action"], "wait_existing_job")
        check_eq("saying plainly that it cannot tell", action["liveness"], "unknown")
        check_in("and carrying the one command a person's word needs",
                 "--operation release", action["release"])
    finally:
        cleanup(root)


def a_recorded_denial_closes_it_even_with_a_receipt():
    """A receipt that came BEFORE the refusal does not save the dispatch: it is a launch of
    something else, long silent. (A receipt after the refusal, or a living agent, does: see
    test_denial_scope.py - this test used to pin a receipt with no time and a file written
    seconds ago, which is exactly the live automator the denial must not close.)"""
    root = temp_project("qa-denied-")
    try:
        controller = at_s5(root)
        host_receipt(root, agent_id="a1", agent_type="qa-automator", task_id=root.name,
                     dispatch_id=AUTOMATOR, status="running",
                     bound_at=1_789_969_860.0 - 3600)    # an hour before the refusal below
        denials = root / "state" / "dispatch-denials.jsonl"
        denials.parent.mkdir(parents=True, exist_ok=True)
        denials.write_text(json.dumps({"at": "2026-09-21T05:51:00+00:00", "stage": "S5",
                                       "role": "qa-automator", "dispatch_id": AUTOMATOR,
                                       "reason": "stage guard refused S5"}) + "\n", encoding="utf-8")
        fixes = controller.never_started_fixes()
        check_eq("a recorded denial is the end of the argument", len(fixes), 1)
        check_in("and it says which record proved it", "dispatch-denials.jsonl", fixes[0]["reason"])
    finally:
        cleanup(root)


def a_story_under_no_project_closes_nothing():
    """t-622 (B-309 (d), F-2): `_project_root` is None when no `qa-factory/config.json` stands at or above the story - it used
    to be the task root, so a receipt under `<story>/qa-factory/state/host-dispatches` (a folder that is no project's) was
    read as the project's and could close a dispatch. Now: no project, no host records to prove anything from."""
    root = temp_dir("qa-no-project-")     # NOT temp_project: this fixture models the "unknown" road (t-617 section 8.2) - the marker is removed below
    try:
        controller = at_s5(root)
        (root / "qa-factory" / "config.json").unlink()      # the gate-A fixture made the story its own project: it is none
        LIFE.without_hooklib()
        check_eq("fixture: no marker at or above the story, so the project is None (not the task root)",
                 controller._project_root(), None)
        host_receipt(root, agent_id="a1", agent_type="qa-automator", task_id=root.name,
                     dispatch_id=AUTOMATOR, status="terminal")
        check_eq("a terminal receipt under the story's own qa-factory/state closes nothing (the story is no project)",
                 controller.liveness_fixes(), [])
        check_eq("...and the dispatch is still running", controller.state()["dispatches"][AUTOMATOR]["status"], "running")
        check_eq("_launched_after with no project is True: undecided keeps the veto (it was a TypeError inside "
                 "dispatch_liveness, caught as False)", controller._launched_after({"id": AUTOMATOR}, None, {}), True)
        denials = root / "state" / "dispatch-denials.jsonl"
        denials.parent.mkdir(parents=True, exist_ok=True)
        denials.write_text(json.dumps({"at": "2026-09-21T05:51:00+00:00", "stage": "S5", "role": "qa-automator",
                                       "dispatch_id": AUTOMATOR, "reason": "stage guard refused S5"}) + "\n", encoding="utf-8")
        check_eq("a task-local denial with no project to read a launch from is not a refusal that closes the dispatch",
                 controller._denied(controller.state()["dispatches"][AUTOMATOR]), False)
        check_eq("...so never_started_fixes closes nothing either", controller.never_started_fixes(), [])
        action = Controller(root).next_action()
        check_eq("next still waits for the job", action["action"], "wait_existing_job")
        check_eq("saying plainly that it cannot tell", action["liveness"], "unknown")
        check_in("and names the missing config", "qa-factory/config.json", action["evidence"])
        check_in("and the one command a person's word needs", "--operation release", action["release"])
        check_eq("the config reads fall to their defaults (no TypeError escapes)",
                 (controller._dispatch_setting("api_window_cases"), controller._handed_cases()),
                 (DISPATCH_DEFAULTS["api_window_cases"], {}))
    finally:
        LIFE.without_hooklib()
        cleanup(root)


# --- the stage guard runs BEFORE the receipt ---------------------------------------------

def a_refused_dispatch_leaves_no_receipt():
    root = temp_project("qa-guard-before-")
    original = getattr(stage_guard, "dispatch_errors", None)
    try:
        controller = SCOPED.gate_a_task(root)
        seen = {}

        def refuse(pipeline, stage_id, assume_gate_approved=None, **kwargs):   # kwargs: task_root (C4-1)
            seen["stage"] = stage_id
            return [f"stage {stage_id} is past gate A, and gate A is not approved. "
                    "A person's word passes this: `"
                    + person_words.door(f"waiver.py --task T --stage {stage_id} --block \"gate A\"") + "`"]

        stage_guard.dispatch_errors = refuse
        message = ""
        try:
            s5_apply(controller, {"id": AUTOMATOR, "stage": "S5", "role": "qa-automator",
                                          "scope": ["TC-1"], "input_hash": "s5", "budget": {},
                                          "known_paths": {}, "idempotency_key": "d1"})
        except StateConflict as exc:
            message = str(exc)
        check_eq("the guard is asked about the stage being dispatched", seen.get("stage"), "S5")
        check_in("the refusal is the guard's own words", "past gate A", message)
        check_in("and it ends in the command that passes it", "waiver.py", message)
        check_eq("a refused dispatch leaves no receipt behind",
                 AUTOMATOR in controller.state()["dispatches"], False)
        check_eq("so the story is not waiting for anybody",
                 Controller(root).next_action()["action"], "prepare_stage")

        stage_guard.dispatch_errors = lambda pipeline, stage_id, assume_gate_approved=None, **kwargs: [
            "stage S5 cannot start"]
        message = ""
        try:
            s5_apply(controller, {"id": AUTOMATOR, "stage": "S5", "role": "qa-automator",
                                          "scope": ["TC-1"], "input_hash": "s5", "budget": {},
                                          "known_paths": {}, "idempotency_key": "d2"})
        except StateConflict as exc:
            message = str(exc)
        check_in("a block that forgot the person's word gets it added here", "waiver.py", message)

        del stage_guard.dispatch_errors
        s5_apply(controller, {"id": AUTOMATOR, "stage": "S5", "role": "qa-automator",
                                      "scope": ["TC-1"], "input_hash": "s5", "budget": {},
                                      "known_paths": {}, "idempotency_key": "d3"})
        check_eq("without the guard the controller behaves exactly as before",
                 controller.state()["dispatches"][AUTOMATOR]["status"], "running")
    finally:
        if original is not None:
            stage_guard.dispatch_errors = original
        elif hasattr(stage_guard, "dispatch_errors"):
            del stage_guard.dispatch_errors
        cleanup(root)


# --- rework is an operation -------------------------------------------------------------

def rework_is_built_from_the_accepted_work():
    root = temp_project("qa-rework-op-")
    try:
        controller = Controller(root)
        controller.apply("initialize", {"scope": ["TC-1", "TC-2"], "source_revision": "src-1",
                                        "known_paths": {"root": str(root)}, "idempotency_key": "init"})
        BASE.seed_plan(root, [SCOPED.plan_row(1, "automate")])
        for number in range(4):
            BASE.accept_stage(controller, root, f"S{number}")
        controller.apply("dispatch", {"id": "S4-qa-case-designer-1", "stage": "S4",
                                      "role": "qa-case-designer", "scope": ["TC-1", "TC-2"],
                                      "input_hash": "design-input", "known_paths": {"root": str(root)},
                                      "budget": {"requests": 40}, "idempotency_key": "d-designer"})
        BASE.record_stage_acceptance(root, "S4", "S4-qa-case-designer-1")  # E-B11
        controller.apply("accept", {"id": "S4-qa-case-designer-1", "status": "accepted",
                                    "stage_complete": True,
                                    "evidence_refs": [BASE.evidence_ref(root, "designer.txt")],
                                    "idempotency_key": "a-designer"})
        request = controller.build_rework_request("S4", "qa-case-designer", ["TC-2"],
                                                  "apply the critic's two exact replacements")
        check_eq("the input hash comes from the accepted work, not from a guess",
                 request["input_hash"], "design-input")
        check_eq("so does the budget", request["budget"], {"requests": 40})
        check_eq("and the paths", request["known_paths"], {"root": str(root)})
        check_eq("the scope is the cases the person named", request["scope"], ["TC-2"])
        check_eq("the id does not collide with the work it repeats",
                 request["id"], "S4-qa-case-designer-2")
        check_eq("it says which dispatch it reworks", request["rework_of"], "S4-qa-case-designer-1")
        controller.apply("dispatch", dict(request))
        check_eq("and it dispatches", controller.state()["dispatches"][request["id"]]["status"],
                 "running")

        for args, needle in (
                (("S4", "qa-case-designer", ["TC-9"], "why"), "outside the approved scope"),
                (("S4", "qa-code-critic", ["TC-2"], "why"), "accepted roles on S4"),
                (("S9", "qa-case-designer", ["TC-2"], "why"), "no accepted qa-case-designer"),
                (("S4", "qa-case-designer", [], "why"), "at least one case"),
                (("S4", "qa-case-designer", ["TC-2"], ""), "--reason")):
            message = ""
            try:
                controller.build_rework_request(*args)
            except ValueError as exc:
                message = str(exc)
            check_in(f"a refused rework names what it wants ({needle})", needle, message)
        message = ""
        try:
            controller.build_rework_request("S4", "qa-case-designer", ["TC-2"], "why", "regression")
        except ValueError as exc:
            message = str(exc)
        check_in("an invented purpose is answered with the list of real ones",
                 "must be one of: bind, build, collect", message)
    finally:
        cleanup(root)


def main():
    next_never_waits_for_an_agent_that_was_never_launched()
    a_working_agent_is_still_waited_for()
    a_host_receipt_is_evidence_too()
    a_host_that_records_nothing_is_left_alone()
    a_recorded_denial_closes_it_even_with_a_receipt()
    a_story_under_no_project_closes_nothing()
    a_refused_dispatch_leaves_no_receipt()
    rework_is_built_from_the_accepted_work()
    finish("test_controller_rework_jobs_guard")


# split: runner piece 1
if __name__ == "__main__":
    main()
