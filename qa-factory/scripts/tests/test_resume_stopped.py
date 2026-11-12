#!/usr/bin/env python3
"""SC2-17: a `SendMessage` to a STOPPED agent (its only open dispatch `blocked`/`paused`) is refused when `resume` would open,
and the refusal names that door (`story_step.py resume`). Run 12586: a message went to a blocked critic, the controller never learned
that the agent went on, and `finish` was refused by R6.

Error direction: a DENY is given only with a door that works (FR-2, P15); every doubt (another status, two stopped records, a request
the controller would refuse, a helper that raises, a store that does not read) is today's ALLOW.

Keys (docs/tasks/specs/r0107-s3c-sc2-17-19-38.md section 3.3):
K1-1 E1 and the real `resume` to ALLOW; K1-2 E2 (`paused`); K1-3 E3, E5; K1-4 E4 (four reasons), E6, E7; K1-5 a helper that raises, through
the real `check`; K1-6 E13 byte for byte; K1-7 E8, E9 in three worlds, each with the real `resume`; K1-8 a refusal writes nothing;
K1-9 the registry row and the command in the text.

KILLS (named, never run here - the batch canon runs them): no "exactly one" condition -> K1-3; `running` not excluded -> K1-3; no
`_resume_problems` check -> K1-4; the branch before `unrecorded` -> K1-6; the call outside the `try` -> K1-5; no `extra` (receipts) -> K1-7;
`--agent-id` in the door of an agent the record holds -> K1-1; no `--agent-id` when the record holds none -> K1-7.
"""
import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import SCRIPTS, check_eq, check_in, check_not_in, cleanup, finish  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import refusal_registry  # noqa: E402
import stage_guard as SG  # noqa: E402
from controller import Controller  # noqa: E402
from host_adapter import normalize  # noqa: E402

import test_resume_doors as RD  # noqa: E402  (story, dispatch, doctor, record, sendmessage, codex, receipt, verdict, story_step)

TICKET, D1, AGENT = RD.TICKET, RD.D1, "A1"
DOOR = f"story_step.py resume --task {TICKET} --dispatch-id {D1}"


def stop(controller, status: str = "blocked", reason: str = "stopped", ident: str = D1) -> None:
    controller.apply("checkpoint", {"id": ident, "status": status, "reason": reason, "checkpoint": {"remaining": []},
                                    "idempotency_key": f"cp-{ident}-{status}-{reason}"})


def world(prefix: str, status: str = "blocked", agent: str = AGENT, reason: str = "stopped"):
    """(project, task, controller): S3 dispatched (with `agent` on the record, or none), then stopped."""
    root, task, controller = RD.story(prefix)
    request = {"id": D1, "stage": "S3", "role": RD.ROLE, "scope": RD.CASES, "input_hash": "h-" + D1, "budget": {},
               "known_paths": {}, "idempotency_key": "dispatch-" + D1}
    if agent:
        request["agent_id"] = agent
    controller.apply("dispatch", request)
    stop(controller, status, reason)
    return root, task, controller


def tree(task: Path) -> dict:
    """Every file of the story folder with its bytes."""
    return {str(p.relative_to(task)): p.read_bytes() for p in sorted(task.rglob("*")) if p.is_file()}


def codex_interrupt(root: Path, target: str) -> dict:
    return normalize(dict(tool_name="collaborationsend_input", host="codex", cwd=str(root), task_id=TICKET,
                          tool_input={"target": target, "message": "opaque", "interrupt": True}))


def k1_1_the_scenario_and_the_real_door() -> None:
    """KILLS: `--agent-id` in the door of an agent the record holds; no refusal at all."""
    root, task, _controller = world("qa-stopped-k1-")
    try:
        code, text = RD.verdict(root, RD.sendmessage(root, AGENT))
        check_eq("K1-1 E1 a message to a blocked agent: DENY", code, SG.DENY)
        check_in("K1-1 ... the door is `resume` of that dispatch", f"`{DOOR}`", text)
        check_not_in("K1-1 ... without --agent-id (the record holds the agent)", "--agent-id", text)
        check_in("K1-1 ... said as stopped", f"dispatch {D1} is blocked, stopped for a person", text)
        done = RD.story_step(root, "resume", "--task", TICKET, "--dispatch-id", D1)
        check_eq("K1-1 the real `resume`: exit 0", done.returncode, 0)
        check_eq("K1-1 ... the next message is ALLOWED", RD.verdict(root, RD.sendmessage(root, AGENT))[0], SG.ALLOW)
    finally:
        cleanup(root)


def k1_2_paused() -> None:
    root, task, _controller = world("qa-stopped-k2-", status="paused")
    try:
        code, text = RD.verdict(root, RD.sendmessage(root, AGENT))
        check_eq("K1-2 E2 a paused agent: DENY", code, SG.DENY)
        check_in("K1-2 ... with the same door and its status", f"`{DOOR}`", text)
        check_in("K1-2 ... saying paused", f"dispatch {D1} is paused", text)
    finally:
        cleanup(root)


def k1_3_running_beside_and_two_stopped() -> None:
    """KILLS: no "exactly one"; `running` not excluded."""
    root, task, _controller = world("qa-stopped-k3-")
    try:
        RD.record(task, "S3-qa-worker-7", status="running", agent_id=AGENT)
        check_eq("K1-3 E3 a running record of the same agent beside the old blocked one: ALLOW", RD.verdict(
            root, RD.sendmessage(root, AGENT))[0], SG.ALLOW)
        with mock.patch("controller.Controller", wraps=Controller) as built:
            RD.verdict(root, RD.sendmessage(root, AGENT))
        check_eq("K1-3 F-4 a message to a not-stopped agent builds no Controller (AR-12, lazy)", built.call_count, 0)
    finally:
        cleanup(root)
    root, task, _controller = world("qa-stopped-k3b-")
    try:
        with mock.patch("controller.Controller", wraps=Controller) as built:
            check_eq("K1-3 control: before the second record the same message is refused", RD.verdict(
                root, RD.sendmessage(root, AGENT))[0], SG.DENY)
        check_eq("K1-3 F-4 control: a stopped agent builds the Controller once", built.call_count, 1)
        RD.record(task, "S3-qa-worker-8", status="blocked", agent_id=AGENT)
        check_eq("K1-3 E5 two blocked records of one agent: ALLOW (no dispatch is guessed)", RD.verdict(
            root, RD.sendmessage(root, AGENT))[0], SG.ALLOW)
    finally:
        cleanup(root)


def k1_4_the_door_would_not_open() -> None:
    """KILLS: no `_resume_problems` check."""
    cases = {}
    # the story budget
    root, task, _c = world("qa-stopped-k4a-", reason=SG.BUDGET_EXHAUSTED)
    cases["BUDGET_EXHAUSTED"] = (root, task)
    # another dispatch running
    root, task, controller = world("qa-stopped-k4b-")
    RD.dispatch(controller, "S3-qa-worker-9", "S3")   # a real second dispatch: the controller's own state has it running
    cases["another running"] = (root, task)
    # a closed story
    root, task, _c = world("qa-stopped-k4c-")
    RD.close_story(task)
    cases["closed story"] = (root, task)
    # no checkpoint of its own: the record is only stopped (imported / state_repair)
    root, task, _c = world("qa-stopped-k4d-")
    RD.doctor(task, lambda data: data["dispatches"].__setitem__("S3-qa-worker-3", {
        "id": "S3-qa-worker-3", "stage": "S3", "role": RD.ROLE, "status": "blocked", "agent_id": "C3"}))
    cases["no own checkpoint"] = (root, task)
    try:
        for label, (root, task) in cases.items():
            target = "C3" if label == "no own checkpoint" else AGENT
            if label == "no own checkpoint":
                RD.doctor(task, lambda data: data["dispatches"].pop(D1))
            check_eq(f"K1-4 E4 {label}: ALLOW as today (a refusal without a door that opens is never given)", RD.verdict(
                root, RD.sendmessage(root, target))[0], SG.ALLOW)
    finally:
        for root, _task in cases.values():
            cleanup(root)
    # E6: a store that does not read, a build that raises, a record that is no object
    root, task, _c = world("qa-stopped-k4e-")
    try:
        with mock.patch.object(Controller, "build_resume_request", side_effect=ValueError("no stop")):
            check_eq("K1-4 E6 the request does not build: ALLOW", RD.verdict(root, RD.sendmessage(root, AGENT))[0], SG.ALLOW)
        RD.doctor(task, lambda data: data["dispatches"].__setitem__("S3-qa-worker-5", "not an object"))
        check_eq("K1-4 E6 an agent with no object record: ALLOW (the rule does not crash)", RD.verdict(
            root, RD.sendmessage(root, RD.KNOWN))[0], SG.ALLOW)
        (task / "state" / "controller.json").write_text("{ broken", encoding="utf-8")
        check_eq("K1-4 E6 a controller.json that does not read: ALLOW", RD.verdict(root, RD.sendmessage(root, AGENT))[0], SG.ALLOW)
    finally:
        cleanup(root)
    # E7: an agent only pipeline.json knows
    root, task, _c = world("qa-stopped-k4f-")
    try:
        check_eq("K1-4 E7 an agent only pipeline.json knows (no record): ALLOW", RD.verdict(
            root, RD.sendmessage(root, RD.KNOWN))[0], SG.ALLOW)
    finally:
        cleanup(root)


def k1_5_a_helper_that_raises() -> None:
    """KILLS: the call outside the `try` (an exception reaches `check` as guard_crashed)."""
    root, task, _c = world("qa-stopped-k5-")
    try:
        before = len(RD.SIGNALS)
        with mock.patch.object(SG, "_stopped_refusal", side_effect=RuntimeError("boom")):
            code = RD.verdict(root, RD.sendmessage(root, AGENT))[0]
        check_eq("K1-5 the helper raises: ALLOW (today's answer)", code, SG.ALLOW)
        check_eq("K1-5 ... and no guard_crashed signal", len(RD.SIGNALS), before)
        check_eq("K1-5 control: unraised, the same message is refused", RD.verdict(root, RD.sendmessage(root, AGENT))[0], SG.DENY)
    finally:
        cleanup(root)


def k1_6_the_unknown_stays_first() -> None:
    """KILLS: the branch placed before `unrecorded` (an unknown neighbour would get this text)."""
    root, task, _c = world("qa-stopped-k6-")
    try:
        code, text = RD.verdict(root, RD.sendmessage(root, AGENT, "X9"))
        check_eq("K1-6 E13 a stopped agent and an unknown name: DENY", code, SG.DENY)
        check_eq("K1-6 ... the text of `SG-resume-unknown`, byte for byte", text, RD.today("X9", (RD.KNOWN, AGENT)))
        check_not_in("K1-6 ... not this node's", "stopped for a person", text)
    finally:
        cleanup(root)


def k1_7_both_hosts_three_worlds() -> None:
    """KILLS: no receipts in `extra`; no `--agent-id` when the record holds none."""
    name = "/root/qa_stopped"
    # (1) the record holds the agent, the target is its id (Claude)
    root, task, _c = world("qa-stopped-k7a-")
    try:
        code, text = RD.verdict(root, RD.sendmessage(root, AGENT))
        check_eq("K1-7 (1) record with agent, target its id: DENY", code, SG.DENY)
        check_in("K1-7 (1) ... door without --agent-id", f"`{DOOR}`", text)
        check_eq("K1-7 (1) the real resume", RD.story_step(root, "resume", "--task", TICKET, "--dispatch-id", D1).returncode, 0)
        check_eq("K1-7 (1) ... ALLOW", RD.verdict(root, RD.sendmessage(root, AGENT))[0], SG.ALLOW)
    finally:
        cleanup(root)
    # (2) the record holds the agent, the target is a Codex name whose receipt names the dispatch
    root, task, _c = world("qa-stopped-k7b-")
    try:
        RD.receipt(root, name, TICKET, D1)
        for label, event in (("followup_task", RD.codex(root, name, task_id=TICKET)), ("send_input interrupt", codex_interrupt(root, name))):
            code, text = RD.verdict(root, event)
            check_eq(f"K1-7 (2) [{label}] a receipt-named target of a stopped dispatch: DENY", code, SG.DENY)
            check_in(f"K1-7 (2) [{label}] ... door without --agent-id (the record holds an agent)", f"`{DOOR}`", text)
        check_eq("K1-7 (2) the real resume", RD.story_step(root, "resume", "--task", TICKET, "--dispatch-id", D1).returncode, 0)
        check_eq("K1-7 (2) ... ALLOW", RD.verdict(root, RD.codex(root, name, task_id=TICKET))[0], SG.ALLOW)
    finally:
        cleanup(root)
    # (3) the record holds NO agent, the link is the receipt only: the door carries --agent-id
    root, task, _c = world("qa-stopped-k7c-", agent="")
    try:
        RD.receipt(root, name, TICKET, D1)
        for label, event in (("followup_task", RD.codex(root, name, task_id=TICKET)), ("send_input interrupt", codex_interrupt(root, name))):
            code, text = RD.verdict(root, event)
            check_eq(f"K1-7 (3) [{label}] a record with no agent: DENY", code, SG.DENY)
            check_in(f"K1-7 (3) [{label}] ... the door carries --agent-id", f"`{DOOR} --agent-id {name}`", text)
        done = RD.story_step(root, "resume", "--task", TICKET, "--dispatch-id", D1, "--agent-id", name)
        check_eq("K1-7 (3) the real resume with that door", done.returncode, 0)
        check_eq("K1-7 (3) ... ALLOW", RD.verdict(root, RD.codex(root, name, task_id=TICKET))[0], SG.ALLOW)
    finally:
        cleanup(root)


def k1_8_reading_writes_nothing() -> None:
    root, task, _c = world("qa-stopped-k8-")
    try:
        before = tree(task)
        check_eq("K1-8 setup: a refusal", RD.verdict(root, RD.sendmessage(root, AGENT))[0], SG.DENY)
        after = tree(task)
        check_eq("K1-8 the story folder is byte for byte the same after the refusal", after == before, True)
        check_eq("K1-8 ... and holds files to compare", len(before) > 0, True)
    finally:
        cleanup(root)


def k1_9_registry_and_the_command() -> None:
    row = next((e for e in refusal_registry.REGISTRY if e["id"] == "SG-resume-stopped"), None)
    check_eq("K1-9 the registry row exists", row is not None, True)
    check_eq("K1-9 ... and names this test", row and row["test"], "scripts/tests/test_resume_stopped.py")
    check_eq("K1-9 A24 finds no violation", refusal_registry.findings(), [])
    root, task, _c = world("qa-stopped-k9-")
    try:
        check_in("K1-9 the text carries the command", f"story_step.py resume --task {TICKET}", RD.verdict(
            root, RD.sendmessage(root, AGENT))[1])
    finally:
        cleanup(root)


def main() -> None:
    k1_1_the_scenario_and_the_real_door()
    k1_2_paused()
    k1_3_running_beside_and_two_stopped()
    k1_4_the_door_would_not_open()
    k1_5_a_helper_that_raises()
    k1_6_the_unknown_stays_first()
    k1_7_both_hosts_three_worlds()
    k1_8_reading_writes_nothing()
    k1_9_registry_and_the_command()
    RD.t442_controller_side()     # the controller's side of the same door: the request it builds and the refusals it gives
    finish("test_resume_stopped")


if __name__ == "__main__":
    main()
