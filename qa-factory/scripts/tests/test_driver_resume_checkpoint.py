#!/usr/bin/env python3
"""FB-4, the driver's side (AR-19): `Driver._act_resume_checkpoint` makes a stopped dispatch running with the ONE command
`story_step.py resume` BEFORE it resumes the role's session.

K-DR1 a blocked dispatch with pending words: the record is `running` when the session goes on, `accept` no longer says
"stopped", no `-2` dispatch exists; K-DR2 another dispatch running: a `Refusal` with `.dispatch` and `.retry`, the session is
not resumed, the words stay; K-DR3 `incomplete` (or no session id): today's road, nothing resumed. The session is a stub."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import check, check_eq, check_in, check_not_in, cleanup, finish  # noqa: E402
import story_run_common as common  # noqa: E402

sys.path.insert(0, str(harness.SCRIPTS))
from controller import Controller  # noqa: E402
import story_run  # noqa: E402

TASK, D, AGENT, WORDS = "QA-9", "S1-qa-scout-1", "agent-A", "the stand is Local"


def rig(status="blocked", session=True, real_resume_role=False):
    root, task_root, env = common.seed(TASK)
    c = Controller(task_root)
    c.apply("dispatch", {"id": D, "stage": "S1", "role": "qa-scout", "scope": [], "input_hash": "x", "budget": {},
                         "known_paths": {}, "idempotency_key": "d1"})
    bind = {"stage": "S1", "status": "running", "digest": "", "dispatch_id": D}
    c.store.commit("stage_transition", dict(bind, agent_id=AGENT) if session else bind, "bind-1")    # no session: no id anywhere
    c.apply("checkpoint", c.build_checkpoint_request(D, status, "source review awaiting the person"))
    driver = common.driver_for(root, env, TASK)
    if session:
        driver.state.setdefault("sessions", {})[D] = AGENT
    driver.state.setdefault("pending_words", {})[D] = WORDS
    seen = []
    driver.completion_for = lambda *a, **k: None
    if real_resume_role:
        # the REAL `resume_role` (its `record_running` included) over a stubbed `run_claude`: the session call is where we look
        def run_claude(kind, prompt, **k):
            seen.append((k.get("dispatch"), Controller(task_root).state()["dispatches"][k.get("dispatch")]["status"], k.get("resume")))
            raise StopIteration("the stub session ends here")
        driver.run_claude = run_claude
    else:
        driver.resume_role = lambda stage, role, dispatch, words, **k: seen.append(
            (dispatch, Controller(task_root).state()["dispatches"][dispatch]["status"]))
    return root, task_root, c, driver, seen


def main():
    root, task_root, c, driver, seen = rig(real_resume_role=True)
    try:
        try:
            driver._act_resume_checkpoint({"action": "resume_checkpoint", "dispatch_id": D})
        except StopIteration:
            pass
        check_eq("K-DR1: the record is running when the (stubbed) session call is made, over the recorded session",
                 seen, [(D, "running", AGENT)])
        refused = ""
        try:
            c.apply("accept", {"id": D, "status": "accepted", "evidence_refs": [], "idempotency_key": "a1"})
        except Exception as exc:  # noqa: BLE001
            refused = str(exc)
        check_not_in("K-DR1: accept is no longer refused as a stopped dispatch", "stopped dispatch", refused)
        check_eq("K-DR1: no S1-qa-scout-2 exists", sorted(c.state()["dispatches"]), [D])
    finally:
        cleanup(root)

    root, task_root, c, driver, seen = rig()
    try:
        c.apply("dispatch", {"id": "S1-other-1", "stage": "S1", "role": "qa-other", "scope": [], "input_hash": "y", "budget": {},
                             "known_paths": {}, "idempotency_key": "d2"})
        caught = None
        try:
            driver._act_resume_checkpoint({"action": "resume_checkpoint", "dispatch_id": D})
        except story_run.Refusal as refusal:
            caught = refusal
        check("K-DR2: a Refusal is raised", caught is not None)
        if caught is not None:
            check_eq("K-DR2: it names the dispatch and carries the step to retry", (caught.dispatch, callable(caught.retry)), (D, True))
            check_in("K-DR2: and says why", "sequential task already has an active dispatch", str(caught))
        check_eq("K-DR2: the session was not resumed", seen, [])
        check_eq("K-DR2: the words stay in pending_words", driver.state["pending_words"].get(D), WORDS)
    finally:
        cleanup(root)

    root, task_root, c, driver, seen = rig(status="incomplete")
    try:
        driver._act_resume_checkpoint({"action": "resume_checkpoint", "dispatch_id": D})
        check_eq("K-DR3: incomplete: today's road, the role resumes over the unchanged record", seen, [(D, "incomplete")])
    finally:
        cleanup(root)
    root, task_root, c, driver, seen = rig(session=False)
    try:
        driver._act_resume_checkpoint({"action": "resume_checkpoint", "dispatch_id": D})
        check_eq("K-DR3: no session id known: today's road, nothing resumed, the record unchanged", seen, [(D, "blocked")])
    finally:
        cleanup(root)
    finish("test_driver_resume_checkpoint")


if __name__ == "__main__":
    main()
