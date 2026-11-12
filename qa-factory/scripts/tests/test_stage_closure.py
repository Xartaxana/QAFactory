#!/usr/bin/env python3
"""The last role of a stage closes it.

TP2-2553: S4's designer AND its critic were both accepted with
`stage_complete: false`. The reducer marks a stage `completed` only when the accepted dispatch
carries the flag, and `stage_repairs` repaired only a stage whose last dispatch carried it —
so gate A refused with "stage not completed" and the only road out was a duplicate
`S4-qa-case-critic-2` over evidence nobody had changed.

Three rules here, all keyed on `contract.stage_closes_with`: a completion that says nothing
closes the stage when its role is the stage's last; saying `false` there is refused with the
flag named; and a journal already written in the old shape is repaired by `recover`, in the
open, with the dispatch named. The designer keeps its `false` — it is not the last role.
"""
import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import (SCRIPTS, check, check_eq, check_in, cleanup, finish, temp_dir)  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
from controller import Controller  # noqa: E402
from event_store import StateConflict  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_controller_state as BASE  # noqa: E402

DESIGNER = "S4-qa-case-designer-1"
CRITIC = "S4-qa-case-critic-1"


def at_s4(root: Path) -> Controller:
    """A story accepted through S0..S3, with S4 not yet run."""
    (root / "qa-factory").mkdir(parents=True, exist_ok=True)
    (root / "qa-factory" / "config.json").write_text("{}", encoding="utf-8")
    controller = Controller(root)
    controller.apply("initialize", {"scope": ["TC-1"], "source_revision": "src-1",
                                    "known_paths": {"root": str(root)}, "idempotency_key": "init"})
    for number in range(4):
        BASE.accept_stage(controller, root, f"S{number}")
    return controller


def evidence(root: Path, name: str) -> dict:
    path = root / name
    path.write_text(name, encoding="utf-8")
    return {"path": name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def dispatch_s4(controller: Controller, identity: str, role: str) -> None:
    controller.apply("dispatch", {"id": identity, "stage": "S4", "role": role, "scope": ["TC-1"],
                                  "input_hash": "cases-1", "budget": {}, "known_paths": {},
                                  "idempotency_key": "d-" + identity})


def the_last_role_closes_the_stage():
    root = temp_dir("qa-stage-closure-")
    try:
        controller = at_s4(root)
        dispatch_s4(controller, DESIGNER, "qa-case-designer")
        controller.apply("accept", {"id": DESIGNER, "status": "accepted", "stage_complete": False,
                                    "evidence_refs": [evidence(root, "designer.txt")],
                                    "idempotency_key": "a-designer"})
        check_eq("the designer is not the last role, so its false stands",
                 controller.state()["dispatches"][DESIGNER]["stage_complete"], False)
        check("and S4 is not closed by it",
              controller.state()["stages"]["S4"]["status"] != "completed")

        dispatch_s4(controller, CRITIC, "qa-case-critic")
        # The completion says nothing about the flag — the 2553 receipt said `false`, and
        # saying nothing used to mean the same thing.
        BASE.record_stage_acceptance(root, "S4", DESIGNER)  # E-B11: the closing accept needs the acceptor's record
        controller.apply("accept", {"id": CRITIC, "status": "accepted",
                                    "evidence_refs": [evidence(root, "critic.txt")],
                                    "idempotency_key": "a-critic"})
        check_eq("the critic's acceptance closes S4 without being asked",
                 controller.state()["stages"]["S4"]["status"], "completed")
        check_eq("and the receipt itself carries the flag",
                 controller.state()["dispatches"][CRITIC]["stage_complete"], True)
    finally:
        cleanup(root)


def saying_false_on_the_closing_role_is_refused():
    root = temp_dir("qa-stage-closure-false-")
    try:
        controller = at_s4(root)
        dispatch_s4(controller, DESIGNER, "qa-case-designer")
        controller.apply("accept", {"id": DESIGNER, "status": "accepted", "stage_complete": False,
                                    "evidence_refs": [evidence(root, "designer.txt")],
                                    "idempotency_key": "a-designer"})
        dispatch_s4(controller, CRITIC, "qa-case-critic")
        refused = ""
        try:
            controller.apply("accept", {"id": CRITIC, "status": "accepted", "stage_complete": False,
                                        "evidence_refs": [evidence(root, "critic.txt")],
                                        "idempotency_key": "a-critic"})
        except StateConflict as exc:
            refused = str(exc)
        check_in("the refusal names the flag", "stage_complete: false", refused)
        check_in("and the dispatch it was passed on", CRITIC, refused)
        check_in("and the stage it would strand", "S4", refused)
        check_in("with the two ways out", "checkpoint", refused)
        # A completion that says what is still open is not the silent `false` this refuses.
        controller.apply("accept", {"id": CRITIC, "status": "accepted", "stage_complete": False,
                                    "unresolved": True, "reason": "TC-1's oracle is still open",
                                    "evidence_refs": [evidence(root, "critic.txt")],
                                    "idempotency_key": "a-critic-open"})
        check_eq("a partial acceptance that names its remainder is taken",
                 controller.state()["dispatches"][CRITIC]["status"], "accepted")
        check("and it does not close the stage behind the person's back",
              controller.state()["stages"]["S4"]["status"] != "completed")
    finally:
        cleanup(root)


def recover_closes_a_stage_written_in_the_old_shape():
    root = temp_dir("qa-stage-closure-recover-")
    try:
        controller = at_s4(root)
        dispatch_s4(controller, DESIGNER, "qa-case-designer")
        controller.apply("accept", {"id": DESIGNER, "status": "accepted", "stage_complete": False,
                                    "evidence_refs": [evidence(root, "designer.txt")],
                                    "idempotency_key": "a-designer"})
        dispatch_s4(controller, CRITIC, "qa-case-critic")
        # The journal of the run itself: 0.7.17 wrote this receipt and refused nothing.
        controller.store.commit("accept", {"id": CRITIC, "status": "accepted",
                                           "stage_complete": False,
                                           "evidence_refs": [evidence(root, "critic.txt")]},
                                "a-critic-legacy", None, None, controller.project)
        check("the old shape leaves S4 short of completed",
              Controller(root).state()["stages"]["S4"]["status"] != "completed")
        result = Controller(root).recover()
        fixes = [fix for fix in result["journalled_repairs"] if fix.get("stage") == "S4"]
        check_eq("recover repairs it by itself, journalled", len(fixes), 1)
        check_eq("naming the dispatch that should have closed it", fixes[0]["dispatch_id"], CRITIC)
        check_in("and why nothing else could", "no dispatch of the stage is open", fixes[0]["reason"])
        check_eq("S4 is completed afterwards",
                 Controller(root).state()["stages"]["S4"]["status"], "completed")
        check_eq("and a second recover has nothing left to do",
                 [f for f in Controller(root).recover()["journalled_repairs"]
                  if f.get("stage") == "S4"], [])
    finally:
        cleanup(root)


def story_step_finish_names_the_work_a_stage_leaves_open():
    """t-721 C2-3 (T5b, section 3.4 item 1): `story_step.py finish --not-complete --unresolved <ids> --reason "<words>"` on
    a stage other than S5 reaches the controller and is accepted - the very shape saying_false_on_the_closing_role_is_refused
    shows the controller takes. (SS used to refuse the pair with --not-complete on EVERY stage; now only S5.)"""
    import os
    from harness import run_script, temp_project
    project = temp_project("qa-stage-closure-ss-")
    try:
        art = project / "qa-factory" / "artifacts" / "QA-C"
        art.mkdir(parents=True)
        controller = at_s4(art)
        dispatch_s4(controller, CRITIC, "qa-case-critic")
        (art / "work" / "test-cases").mkdir(parents=True)
        # GW1-8: `finish` re-reads S4's exit gate, which validates the case files. This test records NO decision (the
        # conductor's `--unresolved` pair never lifts the gate), so the case must be a valid one; the decision road over
        # an INVALID case is T5/T5c in test_story_step.py (`open_close_checks`).
        (art / "work" / "test-cases" / "TC-1.md").write_text(
            "---\nid: TC-1\ntitle: t\narea: api\npriority: P2\nstatus: Draft\nchannel: auto\nreuse_decision: new\n"
            "updated: 2026-09-01\ntask: QA-C\ncovers: [R-1]\n---\nthe case\n", encoding="utf-8")
        env = dict(os.environ, CLAUDE_PROJECT_DIR=str(project))
        done = run_script("story_step.py", "finish", "--task", "QA-C", "--dispatch-id", CRITIC, "--digest",
                          "qa-case-critic S4 done", "--ignore-handoff", "--not-complete", "--unresolved", "TC-1",
                          "--reason", "TC-1's oracle is still open", cwd=project, env=env)
        got = Controller(art).state()["dispatches"][CRITIC]
        check_eq("T5b: --not-complete with --unresolved on S4 reaches the controller and is accepted, exit 0",
                 (done.returncode, got["status"], got.get("stage_complete"), got.get("unresolved"), got.get("reason")),
                 (0, "accepted", False, "TC-1", "TC-1's oracle is still open"))
        check("T5b: and S4 is not closed behind the person's back",
              Controller(art).state()["stages"]["S4"]["status"] != "completed")
        check_in("T5b: said as an open stage", "stage open", done.stdout)
    finally:
        cleanup(project)


def main():
    story_step_finish_names_the_work_a_stage_leaves_open()
    the_last_role_closes_the_stage()
    saying_false_on_the_closing_role_is_refused()
    recover_closes_a_stage_written_in_the_old_shape()
    finish("stage closure")


if __name__ == "__main__":
    main()
