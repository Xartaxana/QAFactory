#!/usr/bin/env python3
"""DC1-16 (the Dev6 review of TP2-2702): the refusal of a resume to an unknown id names the door.

`SG-resume-unknown` (the branch where the story knows some agents) said only "anything else is a new dispatch and belongs
in Agent". The strategist's role had stopped with an empty form, its id was bound to no dispatch, and the conductor ran the
whole dispatch again. Now `stage_guard._resume_doors` names the door a live dispatch of THIS story can use, and only then:
`story_step.py bind` for a running dispatch or an unaccepted returned one, `story_step.py resume --agent-id` for a stopped
one. The decision (DENY) is never changed; a door that would not open is never named (FR-2).

  K2-1 Claude, the Dev6 review in both worlds (`running`; `record_return` then `returned_unaccepted`): the refusal carries the
       ready `bind`, the real `story_step.py bind` runs, the repeat is ALLOWED, and in the returned world `finish` accepts
  K2-2 a repair dispatch on an ACCEPTED stage (HF9-1): the door opens, the stage stays completed
  K2-3 a `blocked` / `paused` dispatch with no agent: the refusal carries `resume`; the real `story_step.py resume` runs; ALLOW
  K2-4 a retired agent is never offered the bind (E2); beside an open name only the open one is (E7)
  K2-5 a name another story's receipt holds, on Claude AND Codex, or a vetoing receipt of this story: no bind (E3)
  K2-6 no door: no running / stopped record, statuses with their own door, a returned dispatch on an accepted stage: today's
       text byte for byte (E4, E5)
  K2-7 malformed stores and a helper that raises: DENY, today's tail, no `guard_crashed` (E6); the KEY names the dispatch
  K2-8 the failed bind's facts (E8, E9), several candidates, and the three refusals of `resume`: today's text
  K2-9 the pinned constants equal the controller's; the `SG-resume-none` branch (E11)

Each key names the mutation it kills: see the report (r0107-s3b-n2-report.md).
"""
import contextlib
import io
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import (SCRIPTS, check_eq, check_in, check_not_in, cleanup, finish,  # noqa: E402
                     run_script, temp_project, use_project)

sys.path.insert(0, str(SCRIPTS))
import controller as CTL  # noqa: E402
import hooklib  # noqa: E402
import host_dispatch as HD  # noqa: E402
import stage_guard as SG  # noqa: E402
from controller import Controller  # noqa: E402
from host_adapter import normalize  # noqa: E402

import test_controller_state as BASE  # noqa: E402  (accept_stage: a stage the controller has accepted)

TICKET = "QA-1"
OTHER_STORY = "QA-2"
ROLE = "qa-worker"
CASES = ["TC-1"]
D1 = "S3-qa-worker-1"
KNOWN = "KNOWN-1"
DASH = chr(0x2014)
# The text this refusal had before DC1-16, copied from the code at a9033e94 (not read back from stage_guard).
TODAY_TAIL = ("A resume goes back to an agent that already holds this story's context; anything else is a new dispatch "
              "and belongs in Agent, where the stage rules apply.")


def today(names: str, known: tuple = (KNOWN,)) -> str:
    """The whole refusal as it read before DC1-16, for a story that knows only KNOWN (or the sorted `known`)."""
    return (f"{TICKET}: resuming '{names}' is blocked {DASH} it is not a dispatch this story ran "
            f"(it knows {sorted(known)}). {TODAY_TAIL}")


def bind_cmd(dispatch: str, agent: str) -> str:
    return f"story_step.py bind --task {TICKET} --dispatch-id {dispatch} --agent-id {agent}"


def resume_cmd(dispatch: str, agent: str) -> str:
    return f"story_step.py resume --task {TICKET} --dispatch-id {dispatch} --agent-id {agent}"


# --- fixtures -------------------------------------------------------------------------------------------------------

def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def story(prefix: str, accepted: int = 3):
    """(project, story folder, controller): stages S0..S{accepted-1} accepted by the controller, the story knows agent KNOWN
    (a stage of pipeline.json carries it), nothing running."""
    root = temp_project(prefix)
    task = root / "qa-factory" / "artifacts" / TICKET
    task.mkdir(parents=True)
    write_json(task / "pipeline.json", {"ticket": TICKET, "stages": {}, "gates": {}})
    use_project(root)
    controller = Controller(task)
    controller.apply("initialize", {"scope": CASES, "source_revision": "r", "known_paths": {"root": str(root)},
                                    "idempotency_key": "init"})
    for number in range(accepted):
        BASE.accept_stage(controller, task, f"S{number}")
    seed_known(task)
    return root, task, controller


def seed_known(task: Path, agent: str = KNOWN) -> None:
    path = task / "pipeline.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data.setdefault("stages", {}).setdefault("S0", {})["agent_id"] = agent
    write_json(path, data)


def dispatch(controller, ident: str = D1, stage: str = "S3") -> None:
    controller.apply("dispatch", {"id": ident, "stage": stage, "role": ROLE, "scope": CASES, "input_hash": "h-" + ident,
                                  "budget": {}, "known_paths": {}, "idempotency_key": "dispatch-" + ident})


def doctor(task: Path, mutate) -> None:
    """Edit the controller's state file the guard reads (a copy in a temp project, never a live artifact)."""
    path = task / "state" / "controller.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    mutate(data)
    write_json(path, data)


def record(task: Path, key: str, **row) -> None:
    doctor(task, lambda data: data["dispatches"].__setitem__(key, dict({"id": key, "stage": "S3", "role": ROLE}, **row)))


def sendmessage(root: Path, *targets: str, task_id: str = TICKET) -> dict:
    """A Claude `SendMessage`; several targets go under several recipient aliases (every one must be recorded)."""
    aliases = ("to", "recipient", "agent_id", "id", "target")
    tool_input = {alias: target for alias, target in zip(aliases, targets)}
    tool_input["task_id"] = task_id
    return {"tool_name": "SendMessage", "cwd": str(root), "tool_input": tool_input}


def codex(root: Path, target: str, **extra) -> dict:
    return normalize(dict(tool_name="collaborationfollowup_task", host="codex", cwd=str(root),
                          tool_input={"target": target, "message": "opaque"}, **extra))


SIGNALS: list = []


@contextlib.contextmanager
def in_project(root: Path):
    saved_env = os.environ.get("CLAUDE_PROJECT_DIR")
    saved_signal = hooklib.person_signal
    hooklib.person_signal = lambda *args, **kwargs: SIGNALS.append(args)
    with hooklib.selftest_root_restored():
        hooklib._PROJECT_ROOT_CACHE = root
        os.environ["CLAUDE_PROJECT_DIR"] = str(root)
        try:
            yield
        finally:
            hooklib.person_signal = saved_signal
            if saved_env is None:
                os.environ.pop("CLAUDE_PROJECT_DIR", None)
            else:
                os.environ["CLAUDE_PROJECT_DIR"] = saved_env


def verdict(root: Path, event: dict) -> tuple:
    """`SG.check` (the hook's entry, so a crash would show as ALLOW): (code, refusal text or "")."""
    with in_project(root), contextlib.redirect_stderr(io.StringIO()):
        code = SG.check(event)
        return code, (SG.LAST_DENIAL["message"] if code == SG.DENY else "")


def story_step(root: Path, *args):
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(root))
    return run_script("story_step.py", *args, cwd=root, env=env)


def receipt(root: Path, identity: str, ticket: str, dispatch_id: str, **extra) -> None:
    write_json(HD.binding_path(root, identity), dict(
        {"agent_id": identity, "agent_type": ROLE, "task_id": ticket, "dispatch_id": dispatch_id, "status": "running",
         "bound_by": "story_step"}, **extra))


def close_story(task: Path) -> None:
    """The story reads as closed by the ONE reading (`hooklib.story_closure`): `closed_at` stamped on pipeline.json."""
    path = task / "pipeline.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["closed_at"] = "2026-10-01T00:00:00"
    write_json(path, data)


def other_story(root: Path) -> None:
    write_json(root / "qa-factory" / "artifacts" / OTHER_STORY / "pipeline.json",
               {"ticket": OTHER_STORY, "stages": {}, "gates": {}})


# --- K2-1 / K2-2 / K2-3: from the refusal, through the real door, to ALLOW -------------------------------------------

def k2_1_sara_both_worlds() -> None:
    """KILLS: `returned` list absent (the returned world keeps today's tail); `running` list absent; the command not built
    from the record's key."""
    for world in ("running", "returned_unaccepted"):
        root, task, controller = story(f"qa-doors-k1-{world[:3]}-")
        try:
            dispatch(controller)
            if world == "returned_unaccepted":
                check_eq("K2-1 setup: record_return took", controller.record_return(D1, "the form is blank"), True)
            state = Controller(task).state()
            check_eq(f"K2-1 [{world}] setup: the record's status", state["dispatches"][D1]["status"], world)
            check_eq(f"K2-1 [{world}] setup: the stage is not accepted", state["stages"].get("S3", {}).get("status") != "completed",
                     True)
            code, text = verdict(root, sendmessage(root, "X1"))
            check_eq(f"K2-1 [{world}] an unknown id is refused", code, SG.DENY)
            check_in(f"K2-1 [{world}] ... as today", "is not a dispatch this story ran", text)
            check_in(f"K2-1 [{world}] ... keeping 'belongs in Agent'", "belongs in Agent", text)
            check_in(f"K2-1 [{world}] ... with the ready bind", f"`{bind_cmd(D1, 'X1')}`", text)
            check_in(f"K2-1 [{world}] ... the dispatch printed with its role", f"working on {D1} ({ROLE}):", text)
            check_not_in(f"K2-1 [{world}] ... and no resume door", "story_step.py resume", text)
            done = story_step(root, "bind", "--task", TICKET, "--dispatch-id", D1, "--agent-id", "X1")
            check_eq(f"K2-1 [{world}] the real bind: exit 0", done.returncode, 0)
            check_eq(f"K2-1 [{world}] ... the door is used: the repeat is ALLOWED", verdict(root, sendmessage(root, "X1"))[0],
                     SG.ALLOW)
            check_eq(f"K2-1 [{world}] ... and only that id: another unknown id is still refused",
                     verdict(root, sendmessage(root, "X2"))[0], SG.DENY)
            if world == "returned_unaccepted":
                (task / "S3-out.txt").write_text("out", encoding="utf-8")   # the evidence file `finish` asks for
                done = story_step(root, "finish", "--task", TICKET, "--dispatch-id", D1, "--digest", "done",
                                  "--output", "S3-out.txt")
                check_eq("K2-1 [returned] finish takes the bound dispatch", done.returncode, 0)
                check_eq("K2-1 [returned] ... the record is accepted",
                         Controller(task).state()["dispatches"][D1]["status"], "accepted")
        finally:
            cleanup(root)


def k2_2_repair_dispatch_on_an_accepted_stage() -> None:
    """KILLS: the stage check applied to `running` (an accepted stage's repair dispatch would lose its door)."""
    root, task, controller = story("qa-doors-k2-", accepted=4)
    try:
        request = dict(controller.build_rework_request("S3", ROLE, CASES, "round one"))
        controller.apply("dispatch", request)
        rework = request["id"]
        check_eq("K2-2 setup: the stage is completed", Controller(task).state()["stages"]["S3"]["status"], "completed")
        code, text = verdict(root, sendmessage(root, "X1"))
        check_eq("K2-2 the repair dispatch's unknown id is refused", code, SG.DENY)
        check_in("K2-2 ... with the ready bind", f"`{bind_cmd(rework, 'X1')}`", text)
        done = story_step(root, "bind", "--task", TICKET, "--dispatch-id", rework, "--agent-id", "X1")
        check_eq("K2-2 the real bind (HF9-1, bind-only): exit 0", done.returncode, 0)
        check_eq("K2-2 ... the repeat is ALLOWED", verdict(root, sendmessage(root, "X1"))[0], SG.ALLOW)
        check_eq("K2-2 ... the stage stays completed", Controller(task).state()["stages"]["S3"]["status"], "completed")
    finally:
        cleanup(root)


def k2_3_stopped_dispatch_gets_the_resume_door() -> None:
    """KILLS: `stopped` offered the `bind` door (the projection writes no id for a stopped record)."""
    for status in ("blocked", "paused"):
        root, task, controller = story(f"qa-doors-k3-{status[:2]}-")
        try:
            dispatch(controller)
            controller.apply("checkpoint", {"id": D1, "status": status, "reason": "stopped", "checkpoint": {"remaining": []},
                                            "idempotency_key": "cp-" + status})
            code, text = verdict(root, sendmessage(root, "X1"))
            check_eq(f"K2-3 [{status}] an unknown id is refused", code, SG.DENY)
            check_in(f"K2-3 [{status}] ... with the ready resume", f"`{resume_cmd(D1, 'X1')}`", text)
            check_in(f"K2-3 [{status}] ... saying the dispatch is stopped", f"working on {D1} ({ROLE}), stopped:", text)
            check_not_in(f"K2-3 [{status}] ... and no bind", "story_step.py bind", text)
            done = story_step(root, "resume", "--task", TICKET, "--dispatch-id", D1, "--agent-id", "X1")
            check_eq(f"K2-3 [{status}] the real resume: exit 0", done.returncode, 0)
            check_eq(f"K2-3 [{status}] ... the repeat is ALLOWED", verdict(root, sendmessage(root, "X1"))[0], SG.ALLOW)
        finally:
            cleanup(root)


# --- K2-4 / K2-5: whom the door is never offered to ------------------------------------------------------------------

def k2_4_retired_agents() -> None:
    """KILLS: open targets without subtracting `retired`."""
    root, task, controller = story("qa-doors-k4-")
    try:
        dispatch(controller)
        record(task, "S3-qa-worker-0", status="superseded", agent_id="R1")
        code, text = verdict(root, sendmessage(root, "R1"))
        check_eq("K2-4 a retired agent is refused", code, SG.DENY)
        check_in("K2-4 ... with the fact in brackets", "R1: dispatch S3-qa-worker-0 is superseded", text)
        check_not_in("K2-4 ... and not offered the bind (E2)", "story_step.py bind", text)
        check_in("K2-4 ... today's tail", TODAY_TAIL, text)
        code, text = verdict(root, sendmessage(root, "R1", "X1"))
        check_eq("K2-4 a retired agent beside an open name: refused", code, SG.DENY)
        check_in("K2-4 E7 ... the open name gets its command", f"`{bind_cmd(D1, 'X1')}`", text)
        check_not_in("K2-4 E7 ... the retired one does not", "--agent-id R1", text)
        check_in("K2-4 E7 ... its fact stays in brackets", "R1: dispatch S3-qa-worker-0 is superseded", text)
        # F4 (critic t-217): a name no record carries, whose receipt of THIS story names a retired dispatch (a bind of a
        # returned dispatch writes no id on the record, so `_resumable_agents` never retired the name): no door, on Claude
        receipt(root, "X2", TICKET, "S3-qa-worker-0")
        code, text = verdict(root, sendmessage(root, "X2"))
        check_eq("K2-4 F4 a receipt of this story names a superseded dispatch: refused", code, SG.DENY)
        check_not_in("K2-4 F4 ... and not offered the bind", "story_step.py bind", text)
        check_in("K2-4 F4 ... today's tail", TODAY_TAIL, text)
        receipt(root, "X4", TICKET, "S3-qa-worker-404")
        code, text = verdict(root, sendmessage(root, "X4"))
        check_not_in("K2-4 F4 a receipt naming a dispatch with no record here: no bind either", "story_step.py bind", text)
        receipt(root, "X5", TICKET, D1)
        check_in("K2-4 F4 control: a receipt naming a LIVE dispatch of this story keeps the door",
                 f"`{bind_cmd(D1, 'X5')}`", verdict(root, sendmessage(root, "X5"))[1])
    finally:
        cleanup(root)


def k2_5_other_story_and_vetoing_receipts() -> None:
    """KILLS: the receipt subtraction applied on Codex only; the `why` subtraction removed."""
    root, task, controller = story("qa-doors-k5-")
    try:
        dispatch(controller)
        other_story(root)
        check_in("K2-5 control: before the receipt the Claude id is offered the bind",
                 f"`{bind_cmd(D1, 'X1')}`", verdict(root, sendmessage(root, "X1"))[1])
        check_in("K2-5 control: ... and the Codex name too",
                 f"`{bind_cmd(D1, 'X1')}`", verdict(root, codex(root, "X1", task_id=TICKET))[1])
        receipt(root, "X1", OTHER_STORY, "S3-qa-worker-9")
        for label, event in (("Claude", sendmessage(root, "X1")), ("Codex", codex(root, "X1", task_id=TICKET))):
            code, text = verdict(root, event)
            check_eq(f"K2-5 [{label}] a name another story's receipt holds is refused", code, SG.DENY)
            check_not_in(f"K2-5 [{label}] ... and not offered the bind (E3)", "story_step.py bind", text)
            check_in(f"K2-5 [{label}] ... today's tail", TODAY_TAIL, text)
        # F2 (critic t-217): a Codex SPAWN receipt has the story's task_id and `dispatch_id: None` (`host_dispatch.record`):
        # no veto in `_recipient_receipts`, but another story's all the same
        receipt(root, "X3", OTHER_STORY, None, host="codex")
        check_in("K2-5 F2 control: the spawn receipt is read as a receipt of the other story",
                 repr({OTHER_STORY}), repr(SG._receipt_stories(codex(root, "X3", task_id=TICKET), "X3")))
        for label, event in (("Claude", sendmessage(root, "X3")), ("Codex", codex(root, "X3", task_id=TICKET))):
            code, text = verdict(root, event)
            check_eq(f"K2-5 F2 [{label}] a spawn receipt with no dispatch id, of another story: refused", code, SG.DENY)
            check_not_in(f"K2-5 F2 [{label}] ... and not offered the bind", "story_step.py bind", text)
            check_in(f"K2-5 F2 [{label}] ... today's tail", TODAY_TAIL, text)
        # a receipt of THIS story whose dispatch has no record here vetoes the Codex name (`why`): no door either
        receipt(root, "/root/qa_v", TICKET, "S3-qa-worker-404")
        code, text = verdict(root, codex(root, "/root/qa_v", task_id=TICKET))
        check_eq("K2-5 [Codex] a vetoing receipt: refused", code, SG.DENY)
        check_in("K2-5 ... with the fact", "dispatch S3-qa-worker-404 has no record in this story", text)
        check_not_in("K2-5 ... and no bind", "story_step.py bind", text)
    finally:
        cleanup(root)


# --- K2-6 / K2-7: the cases with no door, and the malformed ones -----------------------------------------------------

def k2_6_no_door_is_today_byte_for_byte() -> None:
    """KILLS: any status counted as `running`; `returned` without the stage check; a door named for an empty store."""
    cases = [("an empty store (no S3 record at all)", None, {}),
             ("accepted", "accepted", {}), ("stale", "stale", {}), ("incomplete", "incomplete", {}),
             ("superseded, no agent", "superseded", {}), ("released_by_person", "released_by_person", {}),
             ("abandoned", "abandoned", {}), ("never_started", "never_started", {}),
             ("settled by an odd word", "wandering", {}),
             ("returned_unaccepted on an ACCEPTED stage", "returned_unaccepted", {"stage_completed": True})]
    for label, status, flags in cases:
        root, task, controller = story("qa-doors-k6-")
        try:
            if status is not None:
                record(task, D1, status=status)
            if flags.get("stage_completed"):
                doctor(task, lambda data: data["stages"].__setitem__("S3", {"status": "completed"}))
            code, text = verdict(root, sendmessage(root, "X1"))
            check_eq(f"K2-6 {label}: refused", code, SG.DENY)
            check_eq(f"K2-6 {label}: today's text, byte for byte", text, today("X1"))
        finally:
            cleanup(root)


def k2_7_malformed_stores_and_a_raising_helper() -> None:
    """KILLS: no `stage` check; the helper outside `try`; the name read from the `id` field instead of the key."""
    shapes = [("dispatches is a list", lambda data: data.__setitem__("dispatches", [1, 2])),
              ("a record that is a string", lambda data: data["dispatches"].__setitem__("junk", "running")),
              ("a running record with no stage", lambda data: data["dispatches"].__setitem__(
                  "n", {"id": "n", "status": "running", "role": ROLE})),
              ("a running record whose stage is a number", lambda data: data["dispatches"].__setitem__(
                  "n", {"id": "n", "stage": 7, "status": "running", "role": ROLE})),
              ("a running record with no id", lambda data: data["dispatches"].__setitem__(
                  "n", {"stage": "S3", "status": "running", "role": ROLE})),
              ("stages is not an object", lambda data: data.__setitem__("stages", "x"))]
    for label, mutate in shapes:
        root, task, controller = story("qa-doors-k7-")
        try:
            doctor(task, mutate)
            before = len(SIGNALS)
            code, text = verdict(root, sendmessage(root, "X1"))
            check_eq(f"K2-7 {label}: DENY, never ALLOW", code, SG.DENY)
            check_eq(f"K2-7 {label}: no `guard_crashed` signal", len(SIGNALS), before)
            if label != "stages is not an object":
                check_eq(f"K2-7 {label}: today's text, byte for byte", text, today("X1"))
        finally:
            cleanup(root)
    root, task, controller = story("qa-doors-k7b-")
    try:
        dispatch(controller)
        original = SG._resume_doors
        SG._resume_doors = lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom"))
        try:
            before = len(SIGNALS)
            code, text = verdict(root, sendmessage(root, "X1"))
        finally:
            SG._resume_doors = original
        check_eq("K2-7 a helper that raises: DENY, not ALLOW", code, SG.DENY)
        check_eq("K2-7 ... with today's text", text, today("X1"))
        check_eq("K2-7 ... and no `guard_crashed` signal", len(SIGNALS), before)
        # the dispatch is named by its KEY: `bind` looks it up by the key
        doctor(task, lambda data: data["dispatches"].__setitem__("KEY-S3", data["dispatches"].pop(D1)))
        code, text = verdict(root, sendmessage(root, "X1"))
        check_in("K2-7 the command carries the record's key, not its `id` field", f"`{bind_cmd('KEY-S3', 'X1')}`", text)
        check_not_in("K2-7 ... and not the id field", f"--dispatch-id {D1} ", text)
        # one bad record beside a good one: the good one is named
        doctor(task, lambda data: data["dispatches"].__setitem__("bad", {"id": "bad", "status": "running", "stage": 7}))
        check_in("K2-7 a malformed record beside a good one: the good one is named",
                 f"`{bind_cmd('KEY-S3', 'X1')}`", verdict(root, sendmessage(root, "X1"))[1])
    finally:
        cleanup(root)


# --- K2-8: facts, several candidates, the refusals of `resume` ---------------------------------------------------------

def k2_8_facts_candidates_and_resume_refusals() -> None:
    """KILLS: `stopped` without the agent check; without the `running` check; without the budget-reason check."""
    root, task, controller = story("qa-doors-k8-")
    try:
        dispatch(controller)
        # E8: the running record already carries agent Y1
        record(task, D1, status="running", agent_id="Y1")
        code, text = verdict(root, sendmessage(root, "X1"))
        check_in("K2-8 E8 a running record bound to Y1: the door and the fact",
                 f"working on {D1} ({ROLE}) (now bound to Y1; a bind replaces it, and Y1 can be resumed as it is):", text)
        check_in("K2-8 E8 ... the command", f"`{bind_cmd(D1, 'X1')}`", text)
        record(task, D1, status="running")
        # E9: a path target
        check_in("K2-8 E9 a path target: the command carries the path", f"`{bind_cmd(D1, '/root/qa_x')}`",
                 verdict(root, sendmessage(root, "/root/qa_x"))[1])
        # several running records
        record(task, "S3-qa-worker-2", status="running", role="qa-critic")
        code, text = verdict(root, sendmessage(root, "X1"))
        check_in("K2-8 several candidates: the prose lists them with their roles",
                 f"working on <one of: {D1} ({ROLE}), S3-qa-worker-2 (qa-critic)>:", text)
        check_in("K2-8 ... the command lists them bare", f"--dispatch-id <one of: {D1}, S3-qa-worker-2> --agent-id X1`", text)
        # several open names
        check_in("K2-8 several open names: the command carries a placeholder",
                 "--agent-id <id>`", verdict(root, sendmessage(root, "X1", "X2"))[1])
        check_not_in("K2-8 ... not either name", "--agent-id X1", verdict(root, sendmessage(root, "X1", "X2"))[1])
    finally:
        cleanup(root)
    # F5 (critic t-217): a RETURNED record held by Y1 names its holder too (the bind replaces it just the same)
    root, task, controller = story("qa-doors-k8r-")
    try:
        dispatch(controller)
        check_eq("K2-8 F5 setup: record_return took", controller.record_return(D1, "blank"), True)
        record(task, D1, status="returned_unaccepted", agent_id="Y1")
        text = verdict(root, sendmessage(root, "X1"))[1]
        check_in("K2-8 F5 a returned record bound to Y1: the holder is named",
                 f"working on {D1} ({ROLE}) (now bound to Y1; a bind replaces it, and Y1 can be resumed as it is):", text)
    finally:
        cleanup(root)
    # the refusals of `resume` (controller.py: held by another agent, a running neighbour, the story budget, a closed
    # story): the guard names no door, AND the real `resume` refuses (F6: the pin runs the controller, not a copy of it)
    refusals = [("a stopped record held by agent Y1", {"agent_id": "Y1"}, False, False),
                ("a stopped record beside a running record", {}, True, False),
                ("a stopped record that stopped on the story budget", {"reason": CTL.BUDGET_EXHAUSTED}, False, False),
                ("a stopped record on a CLOSED story (F1)", {}, False, True)]
    for label, row, with_running, closed in refusals:
        root, task, controller = story("qa-doors-k8b-")
        try:
            record(task, D1, status="blocked", **row)
            if with_running:
                record(task, "S3-qa-worker-2", status="running", stage="")   # running, but no stage: no `bind` door either
            if closed:
                check_in("K2-8 F1 control: the same record on an OPEN story is offered the resume",
                         f"`{resume_cmd(D1, 'X1')}`", verdict(root, sendmessage(root, "X1"))[1])
                close_story(task)
            code, text = verdict(root, sendmessage(root, "X1"))
            check_eq(f"K2-8 {label}: refused", code, SG.DENY)
            known = (KNOWN, "Y1") if row.get("agent_id") else (KNOWN,)
            check_eq(f"K2-8 {label}: today's text, byte for byte", text, today("X1", known))
            done = story_step(root, "resume", "--task", TICKET, "--dispatch-id", D1, "--agent-id", "X1")
            check_eq(f"K2-8 {label}: the real resume refuses too (no door is named where the command refuses)",
                     done.returncode != 0, True)
        finally:
            cleanup(root)
    # F1: a RUNNING dispatch on a closed story keeps the bind door; whether the real bind opens it is asserted, not assumed
    root, task, controller = story("qa-doors-k8d-")
    try:
        dispatch(controller)
        close_story(task)
        text = verdict(root, sendmessage(root, "X1"))[1]
        check_in("K2-8 F1 a running dispatch on a closed story: the guard still names the bind", f"`{bind_cmd(D1, 'X1')}`", text)
        done = story_step(root, "bind", "--task", TICKET, "--dispatch-id", D1, "--agent-id", "X1")
        check_eq("K2-8 F1 ... and the real bind on it", done.returncode, 0)
        check_eq("K2-8 F1 ... then the repeat is ALLOWED", verdict(root, sendmessage(root, "X1"))[0], SG.ALLOW)
    finally:
        cleanup(root)
    # a stopped record beside a running one that CAN be bound: only the bind is named
    root, task, controller = story("qa-doors-k8c-")
    try:
        record(task, D1, status="blocked")
        record(task, "S3-qa-worker-2", status="running")
        text = verdict(root, sendmessage(root, "X1"))[1]
        check_in("K2-8 a stopped and a running record: the bind is named", f"`{bind_cmd('S3-qa-worker-2', 'X1')}`", text)
        check_not_in("K2-8 ... and no resume (the controller would refuse it)", "story_step.py resume", text)
    finally:
        cleanup(root)


# --- K2-9: pins and the neighbouring branch ------------------------------------------------------------------------------

def k2_9_pins_and_the_none_branch() -> None:
    """KILLS: the pins drifting from the controller; the `SG-resume-none` tail unconditional / never changed."""
    check_eq("K2-9 RESUMABLE_STOPPED equals Controller.RESUMABLE", set(SG.RESUMABLE_STOPPED), set(Controller.RESUMABLE))
    check_eq("K2-9 RETURNED_UNACCEPTED equals controller.RETURNED", SG.RETURNED_UNACCEPTED, CTL.RETURNED)
    check_eq("K2-9 BUDGET_EXHAUSTED equals controller.BUDGET_EXHAUSTED", SG.BUDGET_EXHAUSTED, CTL.BUDGET_EXHAUSTED)
    check_eq("K2-9 UNRESUMABLE is still the controller's RELEASED pair", set(SG.UNRESUMABLE), {"superseded", CTL.RELEASED})
    # E11: the story records only retired agents, nothing is known
    root, task, controller = story("qa-doors-k9-")
    try:
        write_json(task / "pipeline.json", {"ticket": TICKET, "stages": {}, "gates": {}})
        record(task, "S3-qa-worker-0", status="superseded", agent_id="R1")
        code, text = verdict(root, sendmessage(root, "R1"))
        check_eq("K2-9 E11 every name retired: refused", code, SG.DENY)
        check_in("K2-9 E11 ... the count of retired agents is still said", "1 agent recorded for this story, none resumable", text)
        check_in("K2-9 E11 ... the answer is the new dispatch",
                 ". A new dispatch is the answer: `controller.py --task-root <T> --operation recover` prints the ready retry "
                 "packet, and `--operation dispatch --input <file>` sends it.", text)
        check_not_in("K2-9 E11 ... the bind is not offered", "story_step.py bind", text)
        code, text = verdict(root, sendmessage(root, "R1", "Z9"))
        check_in("K2-9 E11 a retired name beside an unknown one: today's text with the bind",
                 "or bind it with `story_step.py bind --task <TICKET> --dispatch-id <DISPATCH> --agent-id <id>`. "
                 "To go on without one, `controller.py --task-root <T> --operation recover` prints the ready retry packet "
                 "for the stopped dispatch, and `--operation dispatch --input <file>` sends it.", text)
        code, text = verdict(root, sendmessage(root, "Z9"))
        check_not_in("K2-9 E11 control: an unknown name with nothing retired keeps the old tail",
                     "A new dispatch is the answer", text)
        # F3: another story's receipt on Claude (no `why` there): the neighbouring branch offers no bind either
        other_story(root)
        check_in("K2-9 F3 control: before the receipt the unknown name is invited to bind",
                 "or bind it with `story_step.py bind", verdict(root, sendmessage(root, "Z8"))[1])
        receipt(root, "Z8", OTHER_STORY, "S3-qa-worker-9")
        code, text = verdict(root, sendmessage(root, "Z8"))
        check_eq("K2-9 F3 [Claude] a name another story's receipt holds: refused", code, SG.DENY)
        check_in("K2-9 F3 ... the answer is the new dispatch", "A new dispatch is the answer", text)
        check_not_in("K2-9 F3 ... and the bind is not offered", "or bind it with", text)
        # F3 POSITION: a helper that raises must not open the refusal; the branch keeps its old invitation
        original = SG._open_targets
        SG._open_targets = lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom"))
        try:
            code, text = verdict(root, sendmessage(root, "Z8"))
        finally:
            SG._open_targets = original
        check_eq("K2-9 F3 a raising helper: DENY, not ALLOW", code, SG.DENY)
        check_in("K2-9 F3 ... with the old invitation", "or bind it with `story_step.py bind", text)
        # a vetoing receipt of this story (Codex) on an otherwise empty record
        receipt(root, "/root/qa_v", TICKET, "S3-qa-worker-404")
        code, text = verdict(root, codex(root, "/root/qa_v", task_id=TICKET))
        check_in("K2-9 E11 [Codex] a vetoed receipt only: the receipt fact is said",
                 "a receipt names /root/qa_v, but dispatch S3-qa-worker-404 has no record in this story", text)
        check_in("K2-9 E11 [Codex] ... and the answer is the new dispatch", "A new dispatch is the answer", text)
    finally:
        cleanup(root)


# --- t-442 (canon part D): the CONTROLLER side of `resume` - the request it builds and the refusals it gives ----------------
# The keys above read the guard (what it names); the survivors of the canon mutation pass sat in `controller.py`
# (`build_resume_request`, `_resume_problems`, `_resume_status_problems`, `_last_stop_sequence`). Every expected text and
# value below comes from the docstrings of those functions and the stage's status vocabulary, not from a run.
# Each key builds its own story; the file `test_resume_stopped.py` calls these too (its mutants are the same sites).

def refused(call) -> tuple:
    """(exception class name, message) of a refusal, or ("", "") when the call went through."""
    try:
        call()
    except Exception as exc:  # noqa: BLE001
        return type(exc).__name__, str(exc)
    return "", ""


def stopped_story(prefix: str, agent: str = "A1", status: str = "blocked", reason: str = "stopped"):
    """(project, story folder, controller): S3 dispatched (the record holds `agent`, or none when empty), then stopped."""
    root, task, controller = story(prefix)
    request = {"id": D1, "stage": "S3", "role": ROLE, "scope": CASES, "input_hash": "h-" + D1, "budget": {},
               "known_paths": {}, "idempotency_key": "dispatch-" + D1}
    if agent:
        request["agent_id"] = agent
    controller.apply("dispatch", request)
    stop_again(controller, status, reason)
    return root, task, controller


def stop_again(controller, status: str = "blocked", reason: str = "stopped") -> None:
    controller.apply("checkpoint", {"id": D1, "status": status, "reason": reason, "checkpoint": {"remaining": []},
                                    "idempotency_key": f"cp-{D1}-{status}-{reason}"})


def checkpoint_sequences(controller) -> list:
    """The journal sequences of the `checkpoint` events of D1, in the order they were written."""
    return [event["sequence"] for event in controller.store.read()
            if event.get("type") == "checkpoint" and (event.get("payload") or {}).get("id") == D1]


def t442_the_stop_a_request_retires() -> None:
    """KILLS (controller.py): the `stop_sequence` check off; `_last_stop_sequence` returning the first stop for the last."""
    root, task, controller = stopped_story("qa-doors-t442-stop-")
    try:
        request = controller.build_resume_request(D1)
        check_eq("T442-1 a request built from the journal is not refused", refused(
            lambda: controller.validate("resume", request, controller.state())), ("", ""))
        sequences = checkpoint_sequences(controller)
        check_eq("T442-1 the request retires the one stop there is", request["stop_sequence"], sequences[-1])
        stale = dict(request, stop_sequence=request["stop_sequence"] - 1, idempotency_key=request["idempotency_key"] + ":stale")
        kind, text = refused(lambda: controller.validate("resume", stale, controller.state()))
        check_eq("T442-1 an older stop: StateConflict", kind, "StateConflict")
        check_in("T442-1 ... saying which stops were compared",
                 f"stale stop: the request retires the stop at sequence {stale['stop_sequence']}, the latest stop of {D1} is at "
                 f"{request['stop_sequence']}", text)
        check_in("T442-1 ... and the door that builds the request again", f"`story_step.py resume --task {TICKET} --dispatch-id {D1}`", text)
        bare = {key: value for key, value in request.items() if key != "stop_sequence"}
        check_in("T442-1 no stop_sequence at all: stale too", "stale stop", refused(
            lambda: controller.validate("resume", bare, controller.state()))[1])
        # two stops of one dispatch: the request retires the LATER one
        controller.apply("resume", request)
        stop_again(controller, "blocked", "stopped again")
        sequences = checkpoint_sequences(controller)
        check_eq("T442-2 setup: two checkpoint events of the dispatch, the second later", len(sequences) == 2 and sequences[0] < sequences[1], True)
        second = controller.build_resume_request(D1)
        check_eq("T442-2 the second request retires the later stop", second["stop_sequence"], sequences[1])
        check_eq("T442-2 ... and its key is built from it", second["idempotency_key"], f"resume:{D1}:{sequences[1]}")
        check_eq("T442-2 ... and is not refused", refused(lambda: controller.validate("resume", second, controller.state())), ("", ""))
        controller.apply("resume", second)
        check_eq("T442-2 the dispatch runs again", controller.state()["dispatches"][D1]["status"], "running")
    finally:
        cleanup(root)


def t442_the_agent_and_the_lease_of_a_request() -> None:
    """KILLS (controller.py): both agents empty not refused; the record's agent not filling the request; a blank given agent
    stripped to nothing; the orchestrator lease's owner not carried."""
    root, task, controller = stopped_story("qa-doors-t442-none-", agent="")
    try:
        request = controller.build_resume_request(D1)
        check_not_in("T442-3 no agent given, none recorded: the request carries none", "agent_id", " ".join(request))
        kind, text = refused(lambda: controller.validate("resume", request, controller.state()))
        check_eq("T442-3 ... and it is refused as the story's state", kind, "StateConflict")
        check_in("T442-3 ... saying no agent is recorded", f"{D1} has no recorded agent and the request names none", text)
        check_in("T442-3 ... with the `--agent-id` door", "--agent-id <the id the Agent call returned>", text)
        check_in("T442-3 ... and the retry packet for an agent that is gone", "--operation recover", text)
        named = controller.build_resume_request(D1, "A7")
        check_eq("T442-3 control: the same request with an agent given: not refused", refused(
            lambda: controller.validate("resume", named, controller.state())), ("", ""))
        check_eq("T442-3 ... and it carries that agent", named["agent_id"], "A7")
        check_eq("T442-3 a padded agent is given stripped", controller.build_resume_request(D1, "  A7 ")["agent_id"], "A7")
        check_eq("T442-4 a blank agent stays blank (`validate` refuses its shape)", controller.build_resume_request(D1, "  ")["agent_id"], "  ")
        check_in("T442-4 ... and is refused by name", "agent_id is the host's own id", refused(
            lambda: controller.validate("resume", controller.build_resume_request(D1, "  "), controller.state()))[1])
        check_not_in("T442-5 no lease: no owner on the request", "owner_session_id", " ".join(request))
    finally:
        cleanup(root)
    root, task, controller = stopped_story("qa-doors-t442-held-", agent="A1")
    try:
        check_eq("T442-6 the record's agent fills a request that names none", controller.build_resume_request(D1)["agent_id"], "A1")
        check_eq("T442-6 ... a given one that matches it is kept", controller.build_resume_request(D1, "A1")["agent_id"], "A1")
        other = controller.build_resume_request(D1, "A2")
        check_in("T442-6 ... a different one is a new dispatch, not a resume", f"{D1} is held by agent A1, the request names A2", refused(
            lambda: controller.validate("resume", other, controller.state()))[1])
        controller.store.commit("handoff", {"lease": {"owner_session_id": "s-42"}}, "h-t442")
        check_eq("T442-5 an orchestrator lease: its owner rides on the request", controller.build_resume_request(D1)["owner_session_id"], "s-42")
    finally:
        cleanup(root)


def t442_the_door_of_each_status() -> None:
    """KILLS (controller.py): the note that the stop checks did not run; the superseded-with-a-retry text; the `incomplete` text;
    the never-started / released text; a stopped record with no checkpoint of its own built into a request."""
    note = "(the agent, budget and stop checks did not run: it is not a stopped dispatch)"
    root, task, controller = stopped_story("qa-doors-t442-run-")
    try:
        request = controller.build_resume_request(D1)
        controller.apply("resume", request)
        again = dict(request, idempotency_key=request["idempotency_key"] + ":again")
        kind, text = refused(lambda: controller.validate("resume", again, controller.state()))
        check_eq("T442-7 a resume of a running dispatch: StateConflict", kind, "StateConflict")
        check_in("T442-7 ... it is not stopped", f"{D1} is running: it is not stopped", text)
        check_eq("T442-7 ... the note that the stop checks did not run ends the message, once", (text.endswith(note), text.count(note)), (True, 1))
    finally:
        cleanup(root)
    root, task, controller = stopped_story("qa-doors-t442-retry-")
    try:
        retry = Controller._retry_packet(controller.state(), controller.state()["dispatches"][D1])
        controller.apply("dispatch", dict(retry, idempotency_key="dispatch:t442-retry"))
        check_eq("T442-8 setup: the old dispatch is superseded", controller.state()["dispatches"][D1]["status"], "superseded")
        request = controller.build_resume_request(D1, "A1")
        kind, text = refused(lambda: controller.apply("resume", request))
        check_in("T442-8 a resume of a superseded dispatch with a retry: it names the retry that holds the work",
                 f"{D1} is superseded: {retry['id']} is its retry and holds this work now; finish or pause {retry['id']}", text)
        check_not_in("T442-8 ... not the text of a superseded dispatch with none", "this work was set aside", text)
    finally:
        cleanup(root)
    root, task, controller = stopped_story("qa-doors-t442-incomplete-", status="incomplete", reason="work left")
    try:
        kind, text = refused(lambda: controller.apply("resume", controller.build_resume_request(D1, "A1")))
        check_eq("T442-9 a resume of an incomplete dispatch: StateConflict", kind, "StateConflict")
        check_in("T442-9 ... it stopped with work left, no agent holds its context", f"{D1} is incomplete: it stopped with work left, not for a person's answer", text)
        check_in("T442-9 ... the door is the retry packet", "--operation recover` prints", text)
        check_not_in("T442-9 ... not the text of an unnamed status", "only a dispatch stopped for a person", text)
    finally:
        cleanup(root)
    for label, status, repair in (("never started", CTL.NEVER_STARTED, "state_repair"), ("released", CTL.RELEASED, "release")):
        root, task, controller = story("qa-doors-t442-" + label.split()[0] + "-")
        try:
            dispatch(controller)
            if repair == "release":
                controller.store.commit("release", {"dispatch_id": D1, "words": "the person set it free"}, "rel-t442")
            else:
                controller.store.commit("state_repair", {"fixes": [{"kind": CTL.NEVER_STARTED, "dispatch_id": D1, "stage": "S3",
                                                                    "digest": "", "reason": "never launched"}]}, "rep-t442")
            check_eq(f"T442-10 [{label}] setup: the record status", controller.state()["dispatches"][D1]["status"], status)
            kind, text = refused(lambda: controller.build_resume_request(D1, "A1"))
            check_eq(f"T442-10 [{label}] a resume request is refused", kind, "ValueError")
            check_in(f"T442-10 [{label}] ... it never reached an agent", f"{D1} is {status}: it never reached an agent", text)
            check_in(f"T442-10 [{label}] ... the door is the relaunch packet", "next` prints the relaunch packet", text)
        finally:
            cleanup(root)
    # a STOPPED record with no checkpoint event of its own (an imported one): refused, never a key `resume:<id>:None`
    root = temp_project("qa-doors-t442-legacy-")
    task = root / "qa-factory" / "artifacts" / TICKET
    task.mkdir(parents=True)
    write_json(task / "pipeline.json", {"task": TICKET})
    use_project(root)
    controller = Controller(task)
    try:
        legacy = {"id": "S0-legacy", "stage": "S0", "role": "qa-scout", "status": "blocked", "agent_id": "A1", "imported": True}
        controller.store.commit("initialize", {"scope": CASES, "source_revision": "s", "known_paths": {"root": str(task)},
                                               "coverage_contract_version": 2, "plan_contract_mode": "new", "host_capabilities": [],
                                               "legacy_import": {"stages": {}, "dispatches": {"S0-legacy": legacy}, "decisions": {}}},
                                "init-t442")
        revision = controller.state()["revision"]
        kind, text = refused(lambda: controller.build_resume_request("S0-legacy"))
        check_eq("T442-11 a blocked record with no checkpoint of its own: ValueError", kind, "ValueError")
        check_in("T442-11 ... no recorded stop to resume", "no recorded stop to resume (S0-legacy is blocked without a checkpoint of its own)", text)
        check_in("T442-11 ... the door is the retry packet", "--operation recover` prints", text)
        check_eq("T442-11 ... and nothing was written", controller.state()["revision"], revision)
    finally:
        cleanup(root)


def t442_controller_side() -> None:
    t442_the_stop_a_request_retires()
    t442_the_agent_and_the_lease_of_a_request()
    t442_the_door_of_each_status()


def main() -> None:
    k2_1_sara_both_worlds()
    k2_2_repair_dispatch_on_an_accepted_stage()
    k2_3_stopped_dispatch_gets_the_resume_door()
    k2_4_retired_agents()
    k2_5_other_story_and_vetoing_receipts()
    k2_6_no_door_is_today_byte_for_byte()
    k2_7_malformed_stores_and_a_raising_helper()
    k2_8_facts_candidates_and_resume_refusals()
    k2_9_pins_and_the_none_branch()
    t442_controller_side()
    finish("test_resume_doors")


if __name__ == "__main__":
    main()
