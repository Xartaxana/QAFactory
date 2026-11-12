#!/usr/bin/env python3
"""SC2-19: the `resume` door in the texts that name the pause -> recover road of a halted role (`_pause_recover_door`,
`_halt_doors`, `_decide_refusal`). Spec: r0107-s3c-sc2-17-19-38.md, node N2.

  K2-1 every branch of `_halt_doors` with an agent on the record: the clause, with the real task and dispatch
  K2-2 no usable agent (absent, empty, blanks, not a string): the old text, byte for byte; a padded id is stripped
  K2-3 `_decide_refusal` of a role that does not close its stage, `--open` and `--close`
  K2-4 FR-2: the REAL `finish` refusal -> the printed `pause` -> the printed `resume` -> the record is `running` and the
       dispatch is accepted; every printed door opens
  K2-5 `_gate_refusal`, `_gate_unreadable`: no agent, no resume clause, text unchanged
  K2-6 the old text is a PREFIX of the new one (readers of `--status blocked`, `--operation recover` keep their text)

KILLS (one test file each, this one): a clause without the agent condition -> K2-2; the agent passed in `_gate_refusal`
-> K2-5; a `<T>` instead of the real task -> K2-1; the clause put before the old text -> K2-6; the agent not passed in
`_decide_refusal` -> K2-3.
"""
import re
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import check, check_eq, check_in, check_not_in, cleanup, finish  # noqa: E402

sys.path.insert(0, str(harness.SCRIPTS))
import story_step  # noqa: E402

import test_story_step as STEP  # noqa: E402
import test_story_step_materialize as MAT  # noqa: E402  (s4_halted, finish_cli)

TASK, DID, AGENT = "QA-R1", "s4-designer", "AG-77"
ROOT = Path("C:/stories/QA-R1")
# The text of `_pause_recover_door` before SC2-19, copied from the code at 8bf9e4c3 (not read back from story_step).
OLD = ("checkpoint it as blocked, `story_step.py pause --task " + TASK + " --dispatch-id " + DID + " --reason "
       "\"<what the role could not do>\" --status blocked`, then take a person's word on what the role stopped "
       "for with the retry: `controller.py --task-root " + str(ROOT) + " --operation recover` (it prints the ready "
       "packet; the person's word goes with the retry)")
CLAUSE = ("; or, when the person's word is for the same agent to go on: after that pause, `story_step.py resume --task "
          + TASK + " --dispatch-id " + DID + "`, then the word goes to agent " + AGENT + " as a message")
RESUME_CMD = "story_step.py resume --task"


def args_of(task=TASK, did=DID):
    return types.SimpleNamespace(task=task, dispatch_id=did)


def record(stage, role, **more):
    return dict({"id": DID, "stage": stage, "role": role, "status": "running"}, **more)


def k2_1_every_branch_with_an_agent():
    """KILLS: clause without a branch (one of the four); `<T>` for the task; a clause only on the always-road."""
    rows = (("closing role, S4 critic", record("S4", "qa-case-critic", agent_id=AGENT), False),
            ("non-closing role, form halt", record("S4", "qa-case-designer", agent_id=AGENT), True),
            ("non-closing role, digest halt", record("S4", "qa-case-designer", agent_id=AGENT), False),
            ("S5", record("S5", "qa-code-critic", agent_id=AGENT), False))
    for label, dispatch, form_halted in rows:
        text = story_step._halt_doors(args_of(), ROOT, dispatch, form_halted)
        check_in(f"K2-1 [{label}] the old road stands", OLD, text)
        check_in(f"K2-1 [{label}] the resume clause, real task, dispatch and agent", CLAUSE, text)
        check_eq(f"K2-1 [{label}] the clause once", text.count(RESUME_CMD), 1)
        check_eq(f"K2-1 [{label}] no placeholder of the old spelling", len(re.findall(r"<T>|<task root>", text)), 0)


def k2_2_no_usable_agent_is_the_old_text():
    """KILLS: a clause without the agent condition (empty, blank, non-string)."""
    for label, agent in (("empty", ""), ("blanks", "   \t"), ("None", None), ("int", 5), ("list", ["A"]), ("dict", {})):
        check_eq(f"K2-2 [{label}] _pause_recover_door is the old text", story_step._pause_recover_door(TASK, DID, ROOT, agent), OLD)
        dispatch = record("S5", "qa-code-critic", agent_id=agent)
        check_eq(f"K2-2 [{label}] _halt_doors S5 is the old text",
                 story_step._halt_doors(args_of(), ROOT, dispatch, False), OLD)
    dispatch = record("S5", "qa-code-critic")
    check_eq("K2-2 [absent key] _halt_doors S5 is the old text", story_step._halt_doors(args_of(), ROOT, dispatch, False), OLD)
    check_eq("K2-2 [default argument] the three-argument call is the old text",
             story_step._pause_recover_door(TASK, DID, ROOT), OLD)
    check_eq("K2-2 a padded id is stripped", story_step._pause_recover_door(TASK, DID, ROOT, "  " + AGENT + " "), OLD + CLAUSE)


def k2_3_decide_refusal_of_a_non_closing_role():
    """KILLS: `_decide_refusal` not handing the record's agent over."""
    for kind in ("open", "close"):
        dispatch = record("S4", "qa-case-designer", agent_id=AGENT, scope=["TC-1"])
        text = story_step._decide_refusal(kind, [], dispatch, DID, {}, TASK, ROOT, False)
        check_in(f"K2-3 [{kind}] the old road", OLD, text)
        check_in(f"K2-3 [{kind}] the clause", CLAUSE, text)
        bare = story_step._decide_refusal(kind, [], dict(dispatch, agent_id=""), DID, {}, TASK, ROOT, False)
        check_in(f"K2-3 [{kind}] no agent: the old road", OLD, bare)
        check_not_in(f"K2-3 [{kind}] no agent: no resume clause", RESUME_CMD, bare)


def k2_4_every_printed_door_opens():
    """FR-2: finish refusal -> printed pause -> printed resume -> running -> accepted. KILLS: a clause naming a command
    the controller refuses (resume before pause, a wrong dispatch id)."""
    root, env, art = MAT.s4_halted("qa-halt-sc219-", TASK, role="qa-case-designer", did=DID)
    try:
        bound = harness.run_script("story_step.py", "bind", "--task", TASK, "--dispatch-id", DID, "--agent-id", AGENT,
                                   cwd=root, env=env)
        check_eq("K2-4 setup: the agent is bound", bound.returncode, 0)
        check_eq("K2-4 setup: the record holds the agent", STEP.dispatch_record(art, DID).get("agent_id"), AGENT)
        done = MAT.finish_cli(root, env, TASK, DID, "qa-case-designer S4 TC-1 · ok")
        check_eq("K2-4 finish refuses the declared halt", done.returncode, 2)
        printed = re.search(r"; or, when the person's word is for the same agent to go on: after that pause, "
                            r"`(story_step\.py resume --task \S+ --dispatch-id \S+)`, then the word goes to agent (\S+) as a message",
                            done.stdout)
        check("K2-4 the refusal prints the resume door", printed is not None, done.stdout)
        resume_args = printed.group(1).split()[2:]
        check_eq("K2-4 the printed agent is the record's", printed.group(2), AGENT)
        paused = harness.run_script("story_step.py", "pause", "--task", TASK, "--dispatch-id", DID, "--reason", "needs a person",
                                    "--status", "blocked", cwd=root, env=env)
        check_eq("K2-4 the printed pause: exit 0", paused.returncode, 0)
        check_eq("K2-4 ... the record is blocked", STEP.dispatch_record(art, DID)["status"], "blocked")
        resumed = harness.run_script("story_step.py", "resume", *resume_args, cwd=root, env=env)
        check_eq("K2-4 the printed resume: exit 0", resumed.returncode, 0)
        check_eq("K2-4 ... the record is running again", STEP.dispatch_record(art, DID)["status"], "running")
        check_eq("K2-4 ... with the same agent", STEP.dispatch_record(art, DID).get("agent_id"), AGENT)
        closed = STEP.run_decide(root, env, TASK, ["--close"], dispatch=DID)
        check_eq("K2-4 the person's decision is recorded", closed.returncode, 0)
        accepted = MAT.finish_cli(root, env, TASK, DID, "qa-case-designer S4 TC-1 · ok")
        check_eq("K2-4 finish takes the dispatch", accepted.returncode, 0)
        check_eq("K2-4 ... the record is accepted", STEP.dispatch_record(art, DID)["status"], "accepted")
    finally:
        cleanup(root)


def k2_5_gate_texts_have_no_agent():
    """KILLS: the agent passed in `_gate_refusal` or `_gate_unreadable`."""
    dispatch = record("S5", "qa-code-critic", agent_id=AGENT)
    unreadable = story_step._gate_unreadable(args_of(), ROOT, dispatch, "no such file")
    check_in("K2-5 _gate_unreadable keeps the old road", OLD, unreadable)
    check_not_in("K2-5 _gate_unreadable: no resume clause", RESUME_CMD, unreadable)
    many = story_step._gate_unreadable(args_of(), ROOT, dispatch, "x", records=[types.SimpleNamespace(script="a.py")])
    check_in("K2-5 _gate_unreadable (records) keeps the old road", OLD, many)
    check_not_in("K2-5 _gate_unreadable (records): no resume clause", RESUME_CMD, many)
    root, env, art = MAT.s4_halted("qa-halt-sc219b-", "QA-R2", role="qa-case-designer", did=DID, verdict="ok")
    try:
        story_step_args = types.SimpleNamespace(task="QA-R2", dispatch_id=DID)
        refusal = story_step._gate_refusal(story_step_args, art, record("S4", "qa-case-designer", agent_id=AGENT),
                                           ["finding one"])
        check_not_in("K2-5 _gate_refusal: no resume clause", RESUME_CMD, refusal)
        check_in("K2-5 _gate_refusal keeps the pause road", "story_step.py pause --task QA-R2", refusal)
    finally:
        cleanup(root)


def k2_6_the_old_text_is_a_prefix():
    """KILLS: the clause put before the old text."""
    new = story_step._pause_recover_door(TASK, DID, ROOT, AGENT)
    check_eq("K2-6 the old text is the prefix, byte for byte", new[:len(OLD)], OLD)
    check_eq("K2-6 the clause follows", new[len(OLD):], CLAUSE)
    check_in("K2-6 the reader substrings stand", "--status blocked", new)
    check_in("K2-6 ... and the recover door", "--operation recover", new)
    check_in("K2-6 ... and the person's word", "take a person's word", new)


def refused_text(call) -> str:
    """The message of the refusal `call` raises, or '' when it went through."""
    try:
        call()
    except Exception as exc:  # noqa: BLE001
        return str(exc)
    return ""


def k2_7_the_controller_clause_needs_an_agent_and_comes_first():
    """t-442 (canon part D). `Controller._resume_clause`: the clause a refusal of `accept` / `checkpoint` on a STOPPED dispatch
    starts with. KILLS: the clause printed with an empty command (no agent condition); the clause never said."""
    import test_controller_resume as CR
    clause = (f"if the same agent continued it: `story_step.py resume --task {CR.TICKET} --dispatch-id {CR.D}`, "
              "then run this again; else ")
    ask = {"accept": {"id": CR.D, "status": "accepted", "evidence_refs": [], "idempotency_key": "t442-a"},
           "checkpoint": {"id": CR.D, "status": "blocked", "reason": "again", "checkpoint": {"remaining": []},
                          "idempotency_key": "t442-c"}}
    heads = {"accept": f"{CR.D} is blocked: a stopped dispatch is not accepted where it stands.",
             "checkpoint": "only the active dispatch can finish; " + CR.D + " is blocked"}
    for bound in (True, False):
        for op in ("accept", "checkpoint"):
            root, art, c = CR.story(bind=bound)
            try:
                CR.stop(c)
                text = refused_text(lambda: c.apply(op, ask[op]))
                label = f"K2-7 [{op}, {'agent on the record' if bound else 'no agent on the record'}]"
                check(label + " a refusal is given", bool(text), text)
                if bound:
                    check_eq(label + " the resume clause comes FIRST, with the real task and dispatch", text.startswith(clause + heads[op]), True)
                    check_eq(label + " ... said once", text.count("if the same agent continued it"), 1)
                else:
                    check_not_in(label + " no clause (no agent can continue it)", "if the same agent continued it", text)
                    check_eq(label + " the old text stands first, byte for byte", text.startswith(heads[op]), True)
            finally:
                cleanup(root)


def main():
    k2_1_every_branch_with_an_agent()
    k2_2_no_usable_agent_is_the_old_text()
    k2_3_decide_refusal_of_a_non_closing_role()
    k2_4_every_printed_door_opens()
    k2_5_gate_texts_have_no_agent()
    k2_6_the_old_text_is_a_prefix()
    k2_7_the_controller_clause_needs_an_agent_and_comes_first()
    finish("test_halt_resume_door")


if __name__ == "__main__":
    main()
