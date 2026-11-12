#!/usr/bin/env python3
"""HF8-15 (2), node N2: a `SendMessage` to a CLOSED author is refused, and the refusal names the controller's door.

Run 12586 and 14857: the S5 critic of a window ran, the author's fixture was the defect, and the conductor went round the controller
with a message to the closed author (its accepted dispatch). `stage_guard._resumable_agents` now retires such an agent (every
record it rides `accepted`, one on a stage whose `rework_mode` is `resume`, no rework of that role waiting for a binding), `_vouched`
does the same for a Codex receipt, and the tail of `SG-resume-unknown` / `SG-resume-none` names the door (`_closed_author_door`):
`story_step.py finish --needs-author` while the S5 critic runs, else `controller.py --operation rework`.

Keys (the spec's K2-n, docs/tasks/specs/r0107-s3b2-hf8-15-sc2-38.md section 4.3):
K2-1 E1 from the refusal, through the real `finish --needs-author`, to the ALLOW of the next message (FR-2), and the refusal again
     once the new author is accepted; K2-2 E2; K2-3 E3, E4, E5; K2-4 E6, E7 (and the pin of the S5 `rework_mode`); K2-5 E8 through
     `SG.check`, a helper that raises; K2-6 E9 and the `SG-resume-none` branch, and `superseded` byte for byte; K2-7 Codex, `_vouched`.

KILLS (one narrow key each, never run here - the batch canon runs them): no `rework_mode` condition -> K2-4; no unbound-record
condition -> K2-3; `all` replaced by `any` -> K2-4; `_vouched` without the condition -> K2-7; the call outside the `try` -> K2-5;
the door without the critic branch -> K2-1.
"""
import json
import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import SCRIPTS, check_eq, check_in, check_not_in, cleanup, finish  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import contract  # noqa: E402
import controller as CTL  # noqa: E402
import stage_guard as SG  # noqa: E402
import story_step  # noqa: E402
from controller import Controller  # noqa: E402

import test_needs_author as NA  # noqa: E402  (a story at S5: the author accepted and bound to AGENT, the critic running)
import test_resume_doors as RD  # noqa: E402  (verdict / sendmessage / receipt / doctor / record)

TICKET, AUTHOR, CRITIC, AGENT = NA.TICKET, NA.AUTHOR, NA.CRITIC, NA.AGENT
CLOSED = f"dispatch {AUTHOR} is accepted; closed work goes back through the controller"
NEEDS_AUTHOR = f"story_step.py finish --task {TICKET} --dispatch-id {CRITIC} --needs-author <cases> --reason \"<words>\""
REWORK = ("controller.py --task-root <T> --operation rework --stage S5 --role qa-automator --cases <ids> --reason \"<words>\" --brief")
NEW_DISPATCH = "A new dispatch is the answer: `controller.py --task-root <T> --operation recover` prints the ready retry packet"


def story(prefix: str, known: str = ""):
    """(project, task, controller): the story of `test_needs_author` plus the `pipeline.json` the guard reads (`known`: an agent a
    stage of it names, so the refusal is the `SG-resume-unknown` branch; empty: the `SG-resume-none` branch)."""
    project, task, controller = NA.story(prefix)
    pipeline = json.loads((task / "pipeline.json").read_text(encoding="utf-8"))   # the story's own file: stages and gate A stay
    if known:
        pipeline.setdefault("stages", {}).setdefault("S0", {})["agent_id"] = known
    RD.write_json(task / "pipeline.json", pipeline)
    return project, task, controller


def verdict(project: Path, *targets: str, agent: str = AGENT) -> tuple:
    return RD.verdict(project, RD.sendmessage(project, *(targets or (agent,)), task_id=TICKET))


def row(**fields) -> dict:
    return dict({"stage": "S5", "role": "qa-automator", "status": "accepted", "agent_id": AGENT}, **fields)


def add(task: Path, key: str, **fields) -> None:
    RD.doctor(task, lambda data: data["dispatches"].__setitem__(key, dict({"id": key}, **row(**fields))))


# --- K2-1: from the refusal, through the real door, to ALLOW ---------------------------------------------------------------

def k2_1_the_scenario_of_the_finding() -> None:
    """KILLS: the door without the critic branch; the closed condition absent (no DENY); `finish --needs-author` not binding."""
    project, task, _controller = story("qa-closed-k1-")
    try:
        code, text = verdict(project)
        check_eq("K2-1 E1 a message to the closed author while the critic runs: DENY", code, SG.DENY)
        check_in("K2-1 ... the none branch, with the count and the fact", f"1 agent recorded for this story, none resumable: "
                 f"{AGENT} ({CLOSED})", text)
        check_in("K2-1 ... and the door is the critic's own `finish --needs-author`", f"`{NEEDS_AUTHOR}`", text)
        check_in("K2-1 ... said as a closed dispatch", "A closed dispatch does not take more work by message.", text)
        check_not_in("K2-1 ... no bind and no new dispatch offered", "story_step.py bind", text)
        check_not_in("K2-1 ... nor the new-dispatch answer", "A new dispatch is the answer", text)
        done, _said = NA.run()
        check_eq("K2-1 the real `finish --needs-author` is accepted (the door opens)", done, 0)
        check_eq("K2-1 ... and the next message to the author, with the card, is ALLOWED", verdict(project)[0], SG.ALLOW)
        NA.retry_cycle(task)
        code, text = verdict(project)
        check_eq("K2-1 the rework accepted again: the author is closed again", code, SG.DENY)
        check_in("K2-1 ... and the critic's retry runs, so the door is the same", f"--dispatch-id {NA.current_critic(task)} "
                 "--needs-author", text)
    finally:
        cleanup(project)


# --- K2-2: the rework of the controller keeps the agent open ------------------------------------------------------------------

def k2_2_a_running_rework_with_the_same_agent() -> None:
    """KILLS: `all` replaced by a test on the accepted record alone (the rework's own record is ignored)."""
    project, task, _controller = story("qa-closed-k2-")
    try:
        add(task, "S5-qa-automator-2", status="running")
        check_eq("K2-2 E2 accepted author, a rework running with the same agent_id: ALLOW", verdict(project)[0], SG.ALLOW)
    finally:
        cleanup(project)


# --- K2-3: what stays on the side of ALLOW ---------------------------------------------------------------------------------------

def k2_3_unbound_unknown_and_pipeline_only() -> None:
    """KILLS: no unbound-record condition; a pipeline-only agent treated as closed; a doubt treated as a refusal."""
    project, task, _controller = story("qa-closed-k3-")
    try:
        for status in ("running", "blocked", "paused", "returned_unaccepted"):
            add(task, "S5-qa-automator-9", status=status, agent_id="")
            check_eq(f"K2-3 E3 a rework `{status}` with no agent_id waits for its bind: the old answer (ALLOW)", verdict(project)[0],
                     SG.ALLOW)
        RD.doctor(task, lambda data: data["dispatches"].pop("S5-qa-automator-9"))
        control = verdict(project)
        check_eq("K2-3 E3 control: without that record the same message is refused", control[0], SG.DENY)
        add(task, "S5-qa-automator-9", status="stale", agent_id="")
        check_eq("K2-3 E3 a `stale` record with no agent_id is no pending bind: still closed", verdict(project)[0], SG.DENY)
    finally:
        cleanup(project)
    project, task, _controller = story("qa-closed-k3p-", known="P1")
    try:
        check_eq("K2-3 E4 an agent only pipeline.json knows (no record): ALLOW, as before", verdict(project, agent="P1")[0], SG.ALLOW)
    finally:
        cleanup(project)
    for label, change in (("no status", lambda r: r.pop("status")), ("no role", lambda r: r.pop("role")),
                          ("no stage", lambda r: r.pop("stage")), ("a status that is no word", lambda r: r.update(status=7)),
                          ("an empty role", lambda r: r.update(role=""))):
        project, task, _controller = story("qa-closed-k3e-")
        try:
            RD.doctor(task, lambda data, change=change: change(data["dispatches"][AUTHOR]))
            check_eq(f"K2-3 E5 the author's record has {label}: not closed (ALLOW)", verdict(project)[0], SG.ALLOW)
        finally:
            cleanup(project)
    project, task, _controller = story("qa-closed-k3u-")
    try:
        with mock.patch.object(contract, "_stage_entry", side_effect=OSError("stages.json is gone")):
            check_eq("K2-3 E5 stages.json does not read: not closed (ALLOW)", verdict(project)[0], SG.ALLOW)
        with mock.patch.object(contract, "rework_mode", side_effect=ValueError("a typo in the table")):
            check_eq("K2-3 E5 a rework_mode that is no word: not closed (ALLOW)", verdict(project)[0], SG.ALLOW)
        check_eq("K2-3 E5 control: the table read, the same message is refused", verdict(project)[0], SG.DENY)
        RD.doctor(task, lambda data: data["dispatches"].__setitem__(AUTHOR, "not an object"))
        check_eq("K2-3 E5 a record that is not an object: no agent rides it and the rule does not crash; an unknown X1 is refused as before",
                 verdict(project, "X1")[0], SG.DENY)
    finally:
        cleanup(project)


# --- K2-4: stale or blocked records of the same agent, fresh stages, and the pin ------------------------------------------------------

def k2_4_other_statuses_fresh_stages_and_the_pin() -> None:
    """KILLS: no `rework_mode` condition; `all` replaced by `any`."""
    for status in ("stale", "blocked", "paused", "superseded"):
        project, task, _controller = story(f"qa-closed-k4-{status[:3]}-")
        try:
            add(task, "S5-qa-automator-0", status=status)
            check_eq(f"K2-4 E6 the agent also rides a `{status}` record: not all accepted, the old answer (ALLOW)",
                     verdict(project)[0], SG.ALLOW)
        finally:
            cleanup(project)
    project, task, _controller = story("qa-closed-k4s-")
    try:
        add(task, "S4-qa-case-designer-1", stage="S4", role="qa-case-designer", agent_id="F1")
        check_eq("K2-4 E7 an accepted author of a `fresh` stage (S4): the old answer (ALLOW)", verdict(project, agent="F1")[0], SG.ALLOW)
        known, retired = SG._resumable_agents({"stages": {}}, {"dispatches": {"s4": dict(row(), stage="S4", agent_id="F1")}})
        check_eq("K2-4 E7 ... `_resumable_agents` keeps it known and retires nothing", ({"F1"}, {}), (known, retired))
    finally:
        cleanup(project)
    # The pin (F-S4, SC2-38 item 6): the closed-author refusal rests on S5 resuming its role. If `stages.json` turns S5 to `fresh`
    # this fails and says whose condition goes with it.
    check_eq("K2-4 PIN: S5 `rework_mode` is `resume` - HF8-15 (2) node N2 (`_closed_only`) stands on it; with `fresh` the closed "
             "author is open again (SC2-38 item 6), decide that deliberately", contract.rework_mode("S5"), "resume")
    check_eq("K2-4 PIN: S4 is `fresh` (the isolation fixture's accepted S4 agent stays known)", contract.rework_mode("S4"), "fresh")
    check_eq("K2-4 the role and stage the door names equal story_step's", (SG._CRITIC_ROLE, SG._CRITIC_STAGE),
             (story_step.DEBT_ROLE, story_step.DEBT_STAGE))
    check_eq("K2-4 the statuses that wait for a bind are the controller's", set(SG._PENDING_BIND),
             {"running", CTL.RETURNED} | set(Controller.RESUMABLE))


# --- K2-5: a helper that raises ----------------------------------------------------------------------------------------------------

def k2_5_a_raising_helper() -> None:
    """KILLS: the call outside the `try` (the verdict would be ALLOW through guard_crashed)."""
    project, task, _controller = story("qa-closed-k5-", known="P1")
    try:
        before = len(RD.SIGNALS)
        with mock.patch.object(SG, "_closed_author_door", side_effect=RuntimeError("boom")):
            code, text = verdict(project)
        check_eq("K2-5 E8 [unknown branch] the new function raises: DENY, not ALLOW", code, SG.DENY)
        check_in("K2-5 ... with today's tail", SG._RESUME_UNKNOWN_TAIL, text)
        check_not_in("K2-5 ... and no door of the new rule", "A closed dispatch", text)
        check_eq("K2-5 ... and no `guard_crashed` signal", len(RD.SIGNALS), before)
        code, text = verdict(project)
        check_in("K2-5 control: unraised, the same message names the closed door", f"`{NEEDS_AUTHOR}`", text)
        check_in("K2-5 ... the unknown branch keeps its count of known agents", "(it knows ['P1'])", text)
    finally:
        cleanup(project)
    project, task, _controller = story("qa-closed-k5n-")
    try:
        with mock.patch.object(SG, "_closed_author_door", side_effect=RuntimeError("boom")):
            code, text = verdict(project)
        check_eq("K2-5 E8 [none branch] the new function raises: DENY", code, SG.DENY)
        check_in("K2-5 ... with the old door (the filter emptied `known`, a new dispatch is the answer)", NEW_DISPATCH, text)
    finally:
        cleanup(project)


# --- K2-6: neighbours, the none branch, `superseded` ------------------------------------------------------------------------------------

def k2_6_neighbours_and_superseded() -> None:
    """KILLS: a closed target that launders a neighbour's door; a changed tail for a target `_closed_only` did not close."""
    project, task, _controller = story("qa-closed-k6-")
    try:
        code, text = verdict(project, AGENT, "X9")
        check_eq("K2-6 E9 a closed author and an unknown name: DENY", code, SG.DENY)
        check_in("K2-6 ... the closed one gets its own door, named", f"{AGENT}: A closed dispatch does not take more work by message.",
                 text)
        check_in("K2-6 ... the open one keeps the old invitation to bind", "or bind it with `story_step.py bind", text)
        check_not_in("K2-6 ... and the bind is not offered to the closed one", f"--agent-id {AGENT}", text)
    finally:
        cleanup(project)
    project, task, _controller = story("qa-closed-k6u-", known="P1")
    try:
        # E9 in the unknown branch: one closed, one open (the running critic is a dispatch a bind can reach)
        code, text = verdict(project, AGENT, "X9")
        check_in("K2-6 E9 [unknown branch] the closed door", f"`{NEEDS_AUTHOR}`", text)
        check_in("K2-6 ... and the open neighbour's door after it", "If X9 is the agent working on", text)
    finally:
        cleanup(project)
    # no critic running: the door is `rework`
    project, task, _controller = story("qa-closed-k6r-")
    try:
        RD.doctor(task, lambda data: data["dispatches"][CRITIC].update(status="accepted"))
        code, text = verdict(project)
        check_eq("K2-6 [none branch] no critic running: DENY", code, SG.DENY)
        check_in("K2-6 ... the door is the controller's `rework`, its card then goes to this agent", f"`{REWORK}`, then its card goes to "
                 "this agent.", text)
        check_not_in("K2-6 ... not the critic's move", "--needs-author", text)
    finally:
        cleanup(project)
    # `superseded`: today's text byte for byte (the DC1-16 E2/E11 pins hold it too)
    root, task, _controller = RD.story("qa-closed-k6s-")
    try:
        RD.write_json(task / "pipeline.json", {"ticket": RD.TICKET, "stages": {}, "gates": {}})
        RD.record(task, "S3-qa-worker-0", status="superseded", agent_id="R1")
        code, text = RD.verdict(root, RD.sendmessage(root, "R1"))
        check_eq("K2-6 a superseded agent: refused", code, SG.DENY)
        check_eq("K2-6 ... the whole refusal as before this node (no closed door, no changed tail)", text,
                 f"{RD.TICKET}: resuming a dispatch is blocked {RD.DASH} 1 agent recorded for this story, none resumable: R1 "
                 "(dispatch S3-qa-worker-0 is superseded). A new dispatch is the answer: `controller.py --task-root <T> --operation "
                 "recover` prints the ready retry packet, and `--operation dispatch --input <file>` sends it.")
    finally:
        cleanup(root)


# --- K2-7: Codex, a receipt does not vouch for a closed author ---------------------------------------------------------------------

def k2_7_codex_receipts() -> None:
    """KILLS: `_vouched` without the closed condition."""
    project, task, _controller = story("qa-closed-k7-")
    try:
        name = "/root/qa_author"
        RD.receipt(project, name, TICKET, AUTHOR, agent_type="qa-automator")
        code, text = RD.verdict(project, RD.codex(project, name, task_id=TICKET))
        check_eq("K2-7 a Codex message to a name whose receipt is the closed author's dispatch: DENY", code, SG.DENY)
        check_in("K2-7 ... the receipt's fact is the closed one", f"a receipt names {name}, but {CLOSED}", text)
        check_in("K2-7 ... and the door is the controller's", f"`{NEEDS_AUTHOR}`", text)
        vouched, why = SG._vouched(RD.codex(project, name, task_id=TICKET), TICKET, [name], Controller(task).state())
        check_eq("K2-7 `_vouched` itself: not vouched, the fact kept", (vouched, why), (set(), {name: CLOSED}))
        done, _said = NA.run()
        check_eq("K2-7 the real `finish --needs-author`", done, 0)
        new = NA.authors(task)[0]
        RD.receipt(project, name, TICKET, new, agent_type="qa-automator")
        check_eq("K2-7 the receipt of the NEW author's running dispatch vouches: ALLOW", RD.verdict(
            project, RD.codex(project, name, task_id=TICKET))[0], SG.ALLOW)
    finally:
        cleanup(project)
    # N2-2 (t-428): the closed fact is a `why` entry no other clause of `_open_targets` repeats (the receipt's dispatch is
    # an accepted record, not a missing or retired one). In the story that knows another agent, without the `why`
    # subtraction the name would be offered a bind to the running critic's dispatch next to the closed text.
    project, task, _controller = story("qa-closed-k7b-", known="KNOWN-1")
    try:
        name = "/root/qa_author"
        RD.receipt(project, name, TICKET, AUTHOR, agent_type="qa-automator")
        code, text = RD.verdict(project, RD.codex(project, name, task_id=TICKET))
        check_eq("K2-7 [known agent] a Codex message to the closed author's receipt: DENY", code, SG.DENY)
        check_in("K2-7 [known agent] ... the closed fact", CLOSED, text)
        check_not_in("K2-7 [known agent] ... and no bind is offered to the closed author's name", "story_step.py bind", text)
    finally:
        cleanup(project)


def main() -> None:
    k2_1_the_scenario_of_the_finding()
    k2_2_a_running_rework_with_the_same_agent()
    k2_3_unbound_unknown_and_pipeline_only()
    k2_4_other_statuses_fresh_stages_and_the_pin()
    k2_5_a_raising_helper()
    k2_6_neighbours_and_superseded()
    k2_7_codex_receipts()
    finish("test_resume_closed_author")


if __name__ == "__main__":
    main()
