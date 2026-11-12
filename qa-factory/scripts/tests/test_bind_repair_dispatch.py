#!/usr/bin/env python3
"""HF9-1 (batch hotfix-12586/9, TP1-14857 S3 and S4): the agent of a REPAIR dispatch reaches the controller record.

A repair dispatch exists only after its stage was accepted. `story_step.py bind` wrote the agent id through `stage_done.py
--status running`, which refuses a running call on a stage the controller holds `completed`; `bind` swallowed that refusal,
so the record and `pipeline.json` never learned the id and the resume guard answered "not a dispatch this story ran".
Now `stage_done` commits a BIND-ONLY stage_transition for a running dispatch of that stage: the id lands on the record through
the one existing writer (the projection), and the accepted stage stays accepted.

  K-A1 completed stage + running rework: exit 0, the record has the id and its stamp, the stage stays completed
  K-A2 the resume guard allows a SendMessage to that agent
  K-A3 a bound dispatch later superseded: its agent is refused with the fact
  K-A4 a never-bound agent is refused
  K-A5 refusals unchanged: accepted dispatch, no dispatch id, another stage's running dispatch, blank agent id, unknown id
  K-A6 replay: a store written before the flag keeps the rework sub-state; with the flag there is none
  K-A7 the same bind twice is the recovered event, the state does not move
  K-A8 `story_step.py bind` end to end, and its note when stage_done still refuses (E12)

Each key names the mutation it kills: drop the bind_only guard -> K-A1; drop the `running` condition -> K-A5 (accepted id);
drop the `stage` condition -> K-A5 (another stage's id); drop the blank-id condition -> K-A5.
"""
import contextlib
import copy
import io
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import (SCRIPTS, check, check_eq, check_in, check_not_in, cleanup, finish,  # noqa: E402
                     run_script, temp_project, use_project)

sys.path.insert(0, str(SCRIPTS))
import hooklib  # noqa: E402
import runtime_paths as RP  # noqa: E402
import stage_done  # noqa: E402
import stage_guard as SG  # noqa: E402
import waiver  # noqa: E402
from controller import Controller, projection  # noqa: E402

import test_controller_state as BASE  # noqa: E402  (accept_stage: a stage the controller has accepted)

TICKET = "QA-1"
ROLE = "qa-worker"
CASES = ["TC-1"]


def repair_story(prefix, rework_open=True):
    """(project, story folder, controller, rework id): S0-S3 accepted by the controller, then ONE rework dispatch of S3 running
    (`rework_open=False`: no rework, the id is "")."""
    root = temp_project(prefix)
    task = root / "qa-factory" / "artifacts" / TICKET
    task.mkdir(parents=True)
    (task / "pipeline.json").write_text(json.dumps({"ticket": TICKET, "stages": {}, "gates": {}}), encoding="utf-8")
    use_project(root)
    controller = Controller(task)
    controller.apply("initialize", {"scope": CASES, "source_revision": "r", "known_paths": {"root": str(root)},
                                    "idempotency_key": "init"})
    for number in range(4):
        BASE.accept_stage(controller, task, f"S{number}")
    if not rework_open:
        return root, task, controller, ""
    request = dict(controller.build_rework_request("S3", ROLE, CASES, "round one"))
    controller.apply("dispatch", request)
    return root, task, controller, request["id"]


def run_stage_done(*args, **kwargs):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = stage_done.run(*args, **kwargs)
    return code, out.getvalue(), err.getvalue()


def bind(agent, dispatch, stage="S3", no_journal=True):
    return run_stage_done(TICKET, stage, "running", ROLE, "", no_journal, agent, dispatch_id=dispatch)


def pipeline_of(task):
    return json.loads((task / "pipeline.json").read_text(encoding="utf-8"))


def journal_lines(root):
    path = RP.record(root, "journal.jsonl")
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.is_file() else []


def resume(root, agent):
    """The resume guard's verdict for a SendMessage to `agent` in this story: (code, the refusal text)."""
    saved = os.environ.get("CLAUDE_PROJECT_DIR")
    with hooklib.selftest_root_restored():
        hooklib._PROJECT_ROOT_CACHE = root
        os.environ["CLAUDE_PROJECT_DIR"] = str(root)
        try:
            event = {"tool_name": "SendMessage", "cwd": str(root), "tool_input": {"to": agent, "task_id": TICKET}}
            with contextlib.redirect_stderr(io.StringIO()):
                code = SG._check(event)
            return code, (SG.LAST_DENIAL or {}).get("message", "") if code == SG.DENY else ""
        finally:
            if saved is None:
                os.environ.pop("CLAUDE_PROJECT_DIR", None)
            else:
                os.environ["CLAUDE_PROJECT_DIR"] = saved


def a1_a2_a4_a8_bind_of_a_repair_dispatch():
    """KILLS: drop the bind_only guard (K-A1 exits 2); the projection keeps writing the stage block (completed -> rework)."""
    root, task, controller, rework = repair_story("qa-bindrep-a1-")
    try:
        before = len(journal_lines(root))
        # control: the guard knows no agent yet - the failure this node fixes
        code, text = resume(root, "A2")
        check_eq("K-A2 control: before the bind the agent is refused", code, SG.DENY)
        code, out, err = bind("A2", rework, no_journal=False)
        check_eq("K-A1 the bind of a running repair dispatch on a completed stage: exit 0", code, 0)
        check_not_in("K-A1 ... and no refusal text", "already accepted by the controller", err)
        state = Controller(task).state()
        record = state["dispatches"][rework]
        check_eq("K-A1 the record holds the agent id", record.get("agent_id"), "A2")
        check("K-A1 ... and the stamp of the bind event", isinstance(record.get("agent_bound_seq"), int)
              and not isinstance(record.get("agent_bound_seq"), bool), str(record))
        # t-1589 F6 (fails before the fix: the line said `S3 -> running`)
        check_in("F6 a bind-only call says the agent was bound and the stage stays done", "S3 agent bound (stage stays done)", out)
        check_not_in("F6 ... and does not say the stage went to running", "S3 -> running", out)
        check_eq("K-A1 the dispatch is still running", record.get("status"), "running")
        stage = state["stages"]["S3"]
        check_eq("K-A1 the controller's S3 stays completed", stage.get("status"), "completed")
        check_not_in("K-A1 ... with no rework sub-state", "rework", json.dumps(stage))
        pipe = pipeline_of(task)["stages"]["S3"]
        check_eq("K-A1 pipeline.json: S3 stays done", pipe.get("status"), "done")
        check_eq("K-A1 ... and names the agent", pipe.get("agent_id"), "A2")
        check_not_in("K-A1 ... with no rework key", "rework", json.dumps(pipe))
        lines = journal_lines(root)
        check_eq("K-A1 exactly one `delegated` line was journaled", [r.get("event") for r in lines[before:]], ["delegated"])
        # K-A2
        check_eq("K-A2 the resume guard allows a SendMessage to the bound agent", resume(root, "A2")[0], SG.ALLOW)
        # K-A4 (known is now {A2}: the refusal is the unknown-recipient one)
        code, text = resume(root, "never-bound")
        check_eq("K-A4 a never-bound agent is refused", code, SG.DENY)
        check_in("K-A4 ... as not a dispatch this story ran", "is not a dispatch this story ran", text)
        # E8: a second, different agent bound to the same running dispatch: the last bind wins
        code, _out, _err = bind("A3", rework)
        check_eq("E8 a second agent on the same running dispatch: exit 0", code, 0)
        check_eq("E8 ... the last bind wins", Controller(task).state()["dispatches"][rework].get("agent_id"), "A3")
        check_eq("E8 ... the stage is still completed", Controller(task).state()["stages"]["S3"].get("status"), "completed")
    finally:
        cleanup(root)


def a3_a_superseded_dispatch_loses_its_agent():
    """K-A3: a dispatch bound in round 1 and superseded later is refused with the fact, whatever wrote its id."""
    root, task, controller, rework = repair_story("qa-bindrep-a3-")
    try:
        check_eq("K-A3 setup: the bind", bind("A2", rework)[0], 0)
        check_eq("K-A3 setup: resumable while running", resume(root, "A2")[0], SG.ALLOW)
        path = task / "state" / "controller.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["dispatches"][rework]["status"] = "superseded"
        path.write_text(json.dumps(data), encoding="utf-8")
        code, text = resume(root, "A2")
        check_eq("K-A3 a superseded dispatch's agent is refused", code, SG.DENY)
        check_in("K-A3 ... and the fact is printed", "is superseded", text)
    finally:
        cleanup(root)


def a5_refusals_unchanged():
    """KILLS: drop the `running` condition (the accepted id binds); drop the `stage` condition (another stage's id binds);
    drop the blank-id condition. Every refused call leaves the event log byte for byte as it was."""
    root, task, controller, rework = repair_story("qa-bindrep-a5-")
    try:
        log = task / "state" / "events.jsonl"
        cases = (("an accepted dispatch", "A9", "dS3"),
                 ("no dispatch id", "A9", ""),
                 ("an id the record does not know", "A9", "D-404"),
                 ("a spaces-only agent id", "  ", rework),
                 ("an empty agent id", "", rework))
        for label, agent, dispatch in cases:
            snapshot = log.read_bytes()
            code, _out, err = bind(agent, dispatch)
            check_eq(f"K-A5 {label}: refused (EXIT_BAD_ARGS)", code, stage_done.EXIT_BAD_ARGS)
            check_in(f"K-A5 {label}: with today's text", "already accepted by the controller", err)
            check_in(f"K-A5 {label}: and today's door for a person's word", "waiver.py", err)
            check(f"K-A5 {label}: the event log is unchanged", log.read_bytes() == snapshot)
        record = Controller(task).state()["dispatches"][rework]
        check_eq("K-A5 the running repair dispatch kept no agent id", record.get("agent_id"), None)
        # a running dispatch of ANOTHER stage (the task is sequential: S4 runs only where no repair is open)
        other = repair_story("qa-bindrep-a5c-", rework_open=False)
        try:
            other_task = other[1]
            other[2].apply("dispatch", {"id": "dS4x", "stage": "S4", "role": ROLE, "scope": CASES, "input_hash": "h4",
                                        "budget": {}, "known_paths": {}, "idempotency_key": "dispatch-S4x"})
            use_project(other[0])
            other_log = other_task / "state" / "events.jsonl"
            snapshot = other_log.read_bytes()
            code, _out, err = bind("A9", "dS4x")
            check_eq("K-A5 a running dispatch of another stage (S4 named on an S3 call): refused", code,
                     stage_done.EXIT_BAD_ARGS)
            check_in("K-A5 ... with today's text", "already accepted by the controller", err)
            check("K-A5 ... the event log is unchanged", other_log.read_bytes() == snapshot)
            check_eq("K-A5 ... the S4 record kept no agent id",
                     Controller(other_task).state()["dispatches"]["dS4x"].get("agent_id"), None)
            # a dispatch id that exists only in ANOTHER story (dS4x, running there): this story's state is the only one read
            use_project(root)
            code, _out, err = bind("A9", "dS4x")
            check_eq("K-A5 a dispatch id of another story (running there): refused here", code, stage_done.EXIT_BAD_ARGS)
            check_eq("K-A5 ... and the other story's record kept no id",
                     Controller(other_task).state()["dispatches"]["dS4x"].get("agent_id"), None)
        finally:
            cleanup(other[0])
            use_project(root)
        # E5: a bind-only call neither reads nor consumes a person's word on the refusal it replaces
        original = waiver.split_overridden
        calls = []
        waiver.split_overridden = lambda *a, **k: (calls.append(a), original(*a, **k))[1]
        try:
            check_eq("E5 the bind-only call: exit 0", bind("A2", rework)[0], 0)
            check_eq("E5 ... split_overridden was never asked", calls, [])
            bind("A2", "dS3")
            check_eq("E5 control: the refused call DOES ask it", len(calls), 1)
        finally:
            waiver.split_overridden = original
    finally:
        cleanup(root)


def a6_replay_of_a_store_written_before_the_flag():
    """K-A6: the same transition WITHOUT `bind_only` projects the rework sub-state (as before); WITH it, no sub-state."""
    root, task, controller, rework = repair_story("qa-bindrep-a6-")
    try:
        events = copy.deepcopy(Controller(task).store.read())
        sequence = len(events) + 1
        payload = {"task": TICKET, "stage": "S3", "status": "running", "role": ROLE, "digest": "", "agent_id": "A2",
                   "dispatch_id": rework, "pipeline": {}, "journal_record": None}
        old = {"type": "stage_transition", "payload": dict(payload), "sequence": sequence, "event_id": "e-old",
               "idempotency_key": "stage:old"}
        new = {"type": "stage_transition", "payload": dict(payload, bind_only=True), "sequence": sequence,
               "event_id": "e-new", "idempotency_key": "stage:new"}
        before = projection(events + [old])
        after = projection(events + [new])
        check_eq("K-A6 a pre-flag event: the sub-state as today", (before["stages"]["S3"].get("rework"),
                 before["stages"]["S3"].get("rework_status")), (True, "running"))
        check_eq("K-A6 a pre-flag event: the id still lands on the record", before["dispatches"][rework].get("agent_id"), "A2")
        check_eq("K-A6 with the flag: no sub-state, the stage is as it was",
                 after["stages"]["S3"], projection(events)["stages"]["S3"])
        check_eq("K-A6 with the flag: the id lands on the record, stamped with the event's position",
                 (after["dispatches"][rework].get("agent_id"), after["dispatches"][rework].get("agent_bound_seq")),
                 ("A2", sequence))
        # a flag on a dispatch that is not running leaves everything alone (the projection's own condition)
        stray = {"type": "stage_transition", "payload": dict(payload, bind_only=True, dispatch_id="dS3"),
                 "sequence": sequence, "event_id": "e-stray", "idempotency_key": "stage:stray"}
        check_eq("K-A6 a flagged transition naming an accepted dispatch changes nothing",
                 projection(events + [stray])["dispatches"]["dS3"].get("agent_id"), None)
    finally:
        cleanup(root)


def a7_the_same_bind_twice():
    root, task, controller, rework = repair_story("qa-bindrep-a7-")
    try:
        first = bind("A2", rework)
        state_after_first = Controller(task).state()
        count = len(Controller(task).store.read())
        second = bind("A2", rework)
        check_eq("K-A7 both calls exit 0", (first[0], second[0]), (0, 0))
        check_in("K-A7 the second is the recovered event", "recovered existing event", second[1])
        check_in("K-A7 t-1587 F6 the recovered bind-only call keeps the bind form", "S3 agent bound (stage stays done)", second[1])
        check_not_in("K-A7 t-1587 F6 ... and not the status arrow", "S3 -> ", second[1])
        check_eq("K-A7 no event was added", len(Controller(task).store.read()), count)
        check_eq("K-A7 the state is equal", Controller(task).state(), state_after_first)
    finally:
        cleanup(root)


def a8_story_step_bind_end_to_end():
    """K-A8: the CLI. A running repair dispatch on a completed stage is bound for real; an accepted one gets the E12 note."""
    root, task, controller, rework = repair_story("qa-bindrep-a8-")
    try:
        env = dict(os.environ, CLAUDE_PROJECT_DIR=str(root))
        done = run_script("story_step.py", "bind", "--task", TICKET, "--dispatch-id", rework, "--agent-id", "A2",
                          cwd=root, env=env)
        check_eq("K-A8 bind of the running repair dispatch: exit 0", done.returncode, 0)
        check_in("K-A8 ... prints the binding", f"bound {rework} to agent A2", done.stdout)
        check_not_in("K-A8 ... and not the swallowed refusal's note", "already accepted", done.stdout)
        check_eq("K-A8 ... the record holds the id", Controller(task).state()["dispatches"][rework].get("agent_id"), "A2")
        check_eq("K-A8 ... and the guard allows the resume", resume(root, "A2")[0], SG.ALLOW)
        # E12: stage_done still refuses (the dispatch is accepted, not running) - the note tells the truth
        done = run_script("story_step.py", "bind", "--task", TICKET, "--dispatch-id", "dS3", "--agent-id", "A9",
                          cwd=root, env=env)
        check_eq("K-A8/E12 bind of an accepted dispatch: exit 0 as today", done.returncode, 0)
        check_in("K-A8/E12 the note says the id is NOT on the dispatch record", "NOT on the controller's dispatch record",
                 done.stdout)
        check_in("K-A8/E12 ... and that only the receipt is written", "Only the host receipt is written", done.stdout)
        check_in("K-A8/E12 ... the receipt is still written", "bound dS3 to agent A9", done.stdout)
        check_eq("K-A8/E12 ... and the record really holds no id", Controller(task).state()["dispatches"]["dS3"].get("agent_id"),
                 None)
        # t-1589 F5 (fails before the fix: the note claimed "is not a running dispatch" for a RUNNING one with a blank id)
        done = run_script("story_step.py", "bind", "--task", TICKET, "--dispatch-id", rework, "--agent-id", " ",
                          cwd=root, env=env)
        check_not_in("F5 a blank agent id on a RUNNING dispatch: the note does not call it not running",
                     "is not a running dispatch", done.stdout)
        check_in("F5 ... it names what stage_done binds", "non-blank agent id", done.stdout)
    finally:
        cleanup(root)


def main():
    a1_a2_a4_a8_bind_of_a_repair_dispatch()
    a3_a_superseded_dispatch_loses_its_agent()
    a5_refusals_unchanged()
    a6_replay_of_a_store_written_before_the_flag()
    a7_the_same_bind_twice()
    a8_story_step_bind_end_to_end()
    finish("test_bind_repair_dispatch")


if __name__ == "__main__":
    main()
