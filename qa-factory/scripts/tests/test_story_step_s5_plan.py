#!/usr/bin/env python3
"""SC1-14 part C1: `story_step` starts and finishes the S5 PLAN dispatch like any other (spec t-1246 section 3 C1, E3, E4; t-1314 delta).

`start --purpose s5_plan` writes the plan's skeleton after `apply` and never before it; the plan critic runs no code judge and no
probe-debt settle (there is no code); a resumed role (the stage's `rework_mode` is `resume` AND the packet carries the parent's
`agent_id`) reads only its delta; the handover form is the contract of the dispatch's purpose; `finish` of a plan dispatch never
completes S5, the critic's receipt is written BEFORE its accept, and the ready command of the next move is printed before `next:`.
Each key names the mutation it kills (M33 resumed lines at `fresh`, M34 the skeleton before `apply`, M35 `finish` of the plan critic
with no receipt, M36 `complete` true on a plan, M37 the code judge on the plan critic).
"""
import argparse
import contextlib
import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import check, check_eq, check_in, check_not_in, cleanup, finish, temp_dir  # noqa: E402

sys.path.insert(0, str(harness.SCRIPTS))
import controller as CT  # noqa: E402
import s5_plan as SP  # noqa: E402
import story_step  # noqa: E402
from event_store import StateConflict  # noqa: E402

from test_s5_plan import put  # noqa: E402
from test_s5_plan_controller import AUTHOR, CRITIC, accept_it, fill, rework_author, review, send, story  # noqa: E402
from test_s5_plan_check import remark_text, write_form  # noqa: E402

TICKET = "QA-T"
PLAN_CONTRACT, REVIEW_CONTRACT = "s5-automator-plan-to-critic", "s5-critic-plan-to-automator"


class Env:
    """The story of `story()` (two cases, one per window) with `story_step` pointed at it and its scripts replaced by a recorder: a
    script run is a call in `calls`, `handoff_init` and `brief_pack` leave the file they would write, the rest answer 0."""

    def __init__(self, prefix):
        self.root = temp_dir(prefix)
        harness.use_project(self.root)
        self.c = story(self.root)
        self.calls = []
        self.saved = (story_step._task_root, story_step._run, story_step._handoff_check, story_step._finish_gate)
        story_step._task_root = lambda task: self.root
        story_step._run = self.run
        story_step._handoff_check = lambda task, did, root: ("green", "", f"work/handoffs/{did}.yaml")
        story_step._finish_gate = lambda *args: (0, "", [])

    def run(self, script, *args):
        self.calls.append((script, args))
        if script == "handoff_init.py":
            put(self.root, f"work/handoffs/{args[args.index('--dispatch') + 1]}.yaml", "contract: stub\n")
        if script == "brief_pack.py":
            put(self.root, f"work/briefs/{args[args.index('--dispatch') + 1]}.md", "brief\n")
        return 0, ""

    def scripts(self):
        return [call[0] for call in self.calls]

    def start(self, role, purpose="s5_plan", scope=""):
        args = argparse.Namespace(task=TICKET, stage="S5", role=role, id=None, scope=scope, purpose=purpose, execution_kind="",
                                  wait_seconds=0)
        return self.say(story_step.start, args)

    def finish(self, dispatch_id, **flags):
        args = argparse.Namespace(task=TICKET, dispatch_id=dispatch_id, digest="done", output=[], not_complete=False, complete=False,
                                  window=None, unresolved=None, reason=None, ignore_handoff=False, wait_seconds=0)
        args.__dict__.update(flags)
        return self.say(story_step.finish, args)

    @staticmethod
    def say(call, args):
        shown = io.StringIO()
        with contextlib.redirect_stdout(shown):
            code = call(args)
        return code, shown.getvalue()

    def status(self, dispatch_id):
        return self.c.state()["dispatches"][dispatch_id]["status"]

    def close(self):
        story_step._task_root, story_step._run, story_step._handoff_check, story_step._finish_gate = self.saved
        cleanup(self.root)


def ready(text):
    return [line for line in text.splitlines() if line.startswith("--- next: ")]


def contract_arg(calls, dispatch_id):
    for script, args in calls:
        if script == "handoff_init.py" and args[args.index("--dispatch") + 1] == dispatch_id and "--contract" in args:
            return args[args.index("--contract") + 1]
    return None


# --- K1: the plan author's start -------------------------------------------------------------------------------

def k1_start_writes_the_skeleton_after_apply():
    """KILLS M34 (the skeleton before `apply`): a refused start leaves no `work/s5-plan.json`."""
    env = Env("qa-s5c1-start-")
    try:
        code, out = env.start(AUTHOR)
        did = "S5-qa-automator-1"
        check_eq("K1: the plan author's start exits 0", code, 0)
        check("K1: the skeleton is on disk, one row per case", (env.root / SP.PLAN_REL).is_file()
              and [r["case"] for r in SP.load(env.root)["cases"]] == ["TC-1", "TC-2"], out[-300:])
        check_in("K1: the start says so", f"plan skeleton: {SP.PLAN_REL} (2 case row(s))", out)
        check_eq("K1: the dispatch is a plan dispatch", CT.s5_part_of(env.c.state()["dispatches"][did]), "plan")
        check_eq("K1: the form is the contract of the PURPOSE (handoff_init --contract)", contract_arg(env.calls, did), PLAN_CONTRACT)
        fill(env.root, env.c)
        accept_it(env.c, env.root, did)
        (env.root / SP.PLAN_REL).unlink()
        try:
            env.start(AUTHOR)
            refused = ""
        except StateConflict as exc:
            refused = str(exc)
        check("K1 (M34): a start the controller refuses (the plan is accepted: reworked, not dispatched again) raises", "accepted" in refused, refused[:200])
        check("K1 (M34): ... and wrote no skeleton: the refusal came before the plan was touched", not (env.root / SP.PLAN_REL).exists())
        check_eq("K1: the critic's start writes no skeleton of its own", (env.start(CRITIC)[0], (env.root / SP.PLAN_REL).exists()), (0, False))
    finally:
        env.close()


def k2_init_by_record():
    """`_s5_plan_init` reads the RECORD: a window, the critic and a rework are told apart; a rework keeps the author's rows."""
    env = Env("qa-s5c1-init-")
    try:
        send(env.c, env.root, "S5-qa-automator-1", AUTHOR, purpose=CT.S5_PLAN)
        plan = fill(env.root, env.c)
        accept_it(env.c, env.root, "S5-qa-automator-1")
        review(env.c, env.root, "S5-qa-code-critic-1", "blocked", remark_text("PR-1", "blocker", case="TC-1", test="T-1"))
        check_eq("K2: the critic's plan dispatch owes no skeleton", story_step._s5_plan_init(TICKET, env.root, env.c, "S5-qa-code-critic-1"), [])
        check_eq("K2: an unknown dispatch owes none", story_step._s5_plan_init(TICKET, env.root, env.c, "nope"), [])
        bytes_before = (env.root / SP.PLAN_REL).read_bytes()
        rework = rework_author(env.c, env.root)
        notes = story_step._s5_plan_init(TICKET, env.root, env.c, rework)
        check("K2: a rework of the plan refreshes it", notes and "plan skeleton:" in notes[0], notes)
        check_eq("K2: ... keeping the author's rows and tests", SP.load(env.root)["tests"], plan["tests"])
        check("K2: ... and moving nothing to .prev (E38 is the fresh start's)", not (env.root / SP.PREV_REL).exists())
        check_eq("K2: the plan bytes are what the critic read (a current plan is not rewritten)", (env.root / SP.PLAN_REL).read_bytes(), bytes_before)
        put(env.root, SP.PLAN_REL, b"{half")
        notes = story_step._s5_plan_init(TICKET, env.root, env.c, rework)
        check("K2: an unreadable plan is a note with the door, never a stop", notes and "s5_plan.py" in notes[0] and "--init" in notes[0], notes)
        check_eq("K2: ... and the file is untouched", (env.root / SP.PLAN_REL).read_bytes(), b"{half")
    finally:
        env.close()


# --- K3: no code to judge ----------------------------------------------------------------------------------------

def k3_no_judge_on_the_plan():
    """KILLS M37 (the code judge on the plan critic)."""
    env = Env("qa-s5c1-judge-")
    real_active = story_step.judge.active
    story_step.judge.active = lambda *a, **k: True
    try:
        env.calls.clear()
        story_step._pre_work(CRITIC, env.root, "S5-qa-code-critic-9", "")
        check_in("K3 (control): a window critic's start runs the code judge", "judge_code.py", env.scripts())
        env.calls.clear()
        story_step._pre_work(CRITIC, env.root, "S5-qa-code-critic-9", CT.S5_PLAN)
        check_eq("K3 (M37): the plan critic's start runs nothing", env.scripts(), [])
        story_step._settle_probe_debt(TICKET, "S5", CRITIC, "S5-qa-code-critic-9", env.root, story_step._settle_clock(), "")
        check_in("K3 (control): a window critic's start settles the probe debt", "probe_debt.py", env.scripts())
        env.calls.clear()
        extras, notes = story_step._settle_probe_debt(TICKET, "S5", CRITIC, "S5-qa-code-critic-9", env.root, story_step._settle_clock(), CT.S5_PLAN)
        check_eq("K3: the plan critic's start settles nothing and says why", (env.scripts(), extras, notes),
                 ([], [], ["plan dispatch: no code to judge or probe"]))
        check_eq("K3: the author's start owes no settle and no note (not the debt's role)",
                 story_step._settle_probe_debt(TICKET, "S5", AUTHOR, "S5-qa-automator-1", env.root, 0.0, CT.S5_PLAN), ([], []))
        # through the dispatch RECORD, the road `materialize` takes (it passes no purpose)
        send(env.c, env.root, "S5-qa-automator-1", AUTHOR, purpose=CT.S5_PLAN)
        fill(env.root, env.c)
        accept_it(env.c, env.root, "S5-qa-automator-1")
        send(env.c, env.root, "S5-qa-code-critic-1", CRITIC, purpose=CT.S5_PLAN)
        env.calls.clear()
        story_step._pre_work(CRITIC, env.root, "S5-qa-code-critic-1")
        check_eq("K3: a plan critic found by its record runs no judge either", env.scripts(), [])
    finally:
        story_step.judge.active = real_active
        env.close()


# --- K4: the packet's resumed lines (E3, E4) -----------------------------------------------------------------------

def k4_resumed_lines():
    """KILLS M33 (the resumed lines at `fresh`)."""
    packet = {"id": "S5-qa-automator-3", "stage": "S5", "rework_of": "S5-qa-automator-2", "agent_id": "agent-7", "reason": "mend",
              "repair_cause": "test_defect", "purpose": "s5_plan", "input_hash": "h"}
    lines = story_step._packet_lines(packet, TICKET)
    check_eq("K4: S5 resumes: the rework line, then the two resumed sentences", len(lines), 3)
    check_in("K4: the agent is the parent's", "You are resumed (same agent as S5-qa-automator-2): the brief is already read; read only "
             f"qa-factory/artifacts/{TICKET}/work/briefs/S5-qa-automator-3-delta.md.", lines[1])
    check_in("K4 (E4): the fallback names the brief first", f"If you do not hold S5-qa-automator-2's context, read qa-factory/artifacts/{TICKET}/work/briefs/S5-qa-automator-3.md first.", lines[1])
    check_eq("K4: with no task name the paths are task-relative", "work/briefs/S5-qa-automator-3-delta.md" in story_step._packet_lines(packet)[1], True)
    fresh = story_step._packet_lines(dict(packet, stage="S6"), TICKET)
    check_eq("K4 (M33, E3): a stage whose rework_mode is fresh is never told it is resumed (even with an agent_id)", len(fresh), 2)
    check("K4: ... the same lines as before the node", all("resumed" not in line for line in fresh), fresh)
    check_eq("K4 (E3): no agent_id: no resumed line", len(story_step._packet_lines({k: v for k, v in packet.items() if k != "agent_id"}, TICKET)), 2)
    check_eq("K4 (E3): an empty agent_id: no resumed line", len(story_step._packet_lines(dict(packet, agent_id="  "), TICKET)), 2)
    check_eq("K4: not a rework: nothing", story_step._packet_lines({k: v for k, v in packet.items() if k != "rework_of"}, TICKET), ())
    check_eq("K4: no packet: nothing", (story_step._packet_lines(None), story_step._packet_lines({})), ((), ()))
    real = story_step.C.rework_mode
    try:
        story_step.C.rework_mode = lambda stage: (_ for _ in ()).throw(ValueError("typo"))
        check_eq("K4: a rework_mode that cannot be read is fresh (a typo never resumes an agent)",
                 len(story_step._packet_lines(packet, TICKET)), 2)
    finally:
        story_step.C.rework_mode = real
    check_eq("K4: the unchanged rework line comes first", lines[0], "Rework of S5-qa-automator-2 (cause test_defect): mend")


# --- K5: the form by purpose -----------------------------------------------------------------------------------------

def k5_form_by_purpose():
    plan = lambda stage, role, purpose: {"stage": stage, "role": role, "request_binding": {"purpose": purpose}}  # noqa: E731
    check_eq("K5: the plan author's purpose has its contract", story_step._purpose_contract("S5", AUTHOR, plan("S5", AUTHOR, "s5_plan")), PLAN_CONTRACT)
    check_eq("K5: the plan critic's too", story_step._purpose_contract("S5", CRITIC, plan("S5", CRITIC, "s5_plan")), REVIEW_CONTRACT)
    check_eq("K5: a purpose nobody registered resolves to nothing (today's lookup follows)",
             story_step._purpose_contract("S5", AUTHOR, plan("S5", AUTHOR, "repair_verify")), "")
    check_eq("K5: no purpose, no record, a record without a binding: nothing",
             [story_step._purpose_contract("S5", AUTHOR, r) for r in ({"stage": "S5"}, None, {"request_binding": None})], ["", "", ""])
    check_eq("K5: the TOP of a record is never read", story_step._purpose_contract("S5", AUTHOR, {"purpose": "s5_plan"}), "")
    check("K5: a form is owed to the plan pair", story_step._form_owed("S5", AUTHOR, plan("S5", AUTHOR, "s5_plan")))
    check("K5: and, as before, to the usual pair", story_step._form_owed("S5", AUTHOR, None))
    check_eq("K5: a role with no contract at all is owed none", story_step._form_owed("S5", "qa-nobody", plan("S5", "qa-nobody", "s5_plan")), False)
    import handoff
    real = handoff.contract_of
    try:
        handoff.contract_of = lambda *a, **k: (_ for _ in ()).throw(OSError("registry"))
        check("K5: a registry that cannot be read owes the form (an unknown waits, FR-59)", story_step._form_owed("S5", AUTHOR, None))
        check_eq("K5: ... and names no contract by purpose", story_step._purpose_contract("S5", AUTHOR, plan("S5", AUTHOR, "s5_plan")), "")
    finally:
        handoff.contract_of = real
    check_eq("K5: no note for a plan dispatch that got its contract", story_step._plan_form_gap(AUTHOR, plan("S5", AUTHOR, "s5_plan"), PLAN_CONTRACT), [])
    check_eq("K5: no note for a window dispatch", story_step._plan_form_gap(AUTHOR, plan("S5", AUTHOR, ""), ""), [])
    gap = story_step._plan_form_gap("qa-nobody", plan("S5", "qa-nobody", "s5_plan"), "")
    check("K5: a plan dispatch whose pair is not registered is told, not silently given the window's form",
          len(gap) == 1 and "no contract is registered for purpose s5_plan" in gap[0], gap)


# --- K6: finish of the plan --------------------------------------------------------------------------------------------

def k6_finish_plan_flow():
    """KILLS M35 (no receipt before the accept) and M36 (`complete` on a plan)."""
    env = Env("qa-s5c1-finish-")
    try:
        env.start(AUTHOR)
        fill(env.root, env.c)
        env.root.joinpath("evidence.txt").write_text("e", encoding="utf-8")
        code, out = env.finish("S5-qa-automator-1", output=["evidence.txt"])
        check_eq("K6: the plan author's finish exits 0 and accepts", (code, env.status("S5-qa-automator-1")), (0, "accepted"))
        check_in("K6: the stage stays open", "stage open - next role of this stage", out)
        critic_start = "--- next: story_step.py start --task QA-T --stage S5 --role qa-code-critic --purpose s5_plan --scope TC-1,TC-2 ---"
        check_eq("K6: the next move after the author's plan is the critic's start over the same scope", ready(out), [critic_start])
        lines = out.splitlines()
        check("K6 (SC1-8): `next:` stays after it, the judge's line last", lines.index(critic_start) < next(
            i for i, l in enumerate(lines) if l.startswith("next: ")) < len(lines) - 1)
        env.calls.clear()
        story_step.judge.active, real_active = (lambda *a, **k: True), story_step.judge.active
        try:
            code, out = env.start(CRITIC)
        finally:
            story_step.judge.active = real_active
        check_eq("K6 (M37): the plan critic's whole start runs no code judge and no probe settle",
                 [s for s in env.scripts() if s in ("judge_code.py", "probe_debt.py")], [])
        check_in("K6: ... and says so", "note: plan dispatch: no code to judge or probe", out)
        check_eq("K6: its form is the review contract", contract_arg(env.calls, "S5-qa-code-critic-1"), REVIEW_CONTRACT)
        write_form(env.root, "S5-qa-code-critic-1", "approved")
        put(env.root, "work/plan-findings.md", "findings\n")
        # a stamp that cannot be written refuses the finish and accepts nothing
        real_stamp = SP.stamp_review
        SP.stamp_review = lambda root, did: (_ for _ in ()).throw(SP.PlanUnreadable("the plan is gone"))
        try:
            code, out = env.finish("S5-qa-code-critic-1")
        finally:
            SP.stamp_review = real_stamp
        check_eq("K6 (M35): a stamp that fails refuses the finish (exit 3)", code, 3)
        check_in("K6: ... with what, the expected file and a door", "the review of the plan was not receipted", out)
        check_in("K6: ... the door is a ready rework command", "--operation rework --stage S5 --role qa-automator --purpose s5_plan", out)
        check_eq("K6: ... and nothing is accepted", env.status("S5-qa-code-critic-1"), "running")
        check("K6: ... and no next move is printed", not ready(out))
        code, out = env.finish("S5-qa-code-critic-1")
        stamps = json.loads((env.root / SP.REVIEWS_REL).read_text(encoding="utf-8"))
        check_eq("K6 (M35): the receipt is written, for this dispatch", [s["dispatch"] for s in stamps], ["S5-qa-code-critic-1"])
        check_eq("K6 (M36): the critic of the plan is the stage's last role and still closes nothing: accepted, stage open",
                 (code, env.status("S5-qa-code-critic-1"), "stage open - next role of this stage" in out), (0, "accepted", True))
        check_eq("K6: the accepted review is read through the chain", [e["outcome"] for e in SP.reviews(env.root, env.c.state())], ["approved"])
        window_one = "--- next: story_step.py start --task QA-T --stage S5 --role qa-automator --scope TC-1 ---"
        check_eq("K6: approved: the next move is window 1's author", ready(out), [window_one])
        check_not_in("K6: the stage was not closed", "stage complete", out)
    finally:
        env.close()


def k7_plan_never_completes():
    """KILLS M36: `--complete` reaches the controller, which refuses it; the flag is not dropped here and the role's place is not the reason."""
    env = Env("qa-s5c1-complete-")
    try:
        env.start(AUTHOR)
        fill(env.root, env.c)
        env.root.joinpath("evidence.txt").write_text("e", encoding="utf-8")
        try:
            env.finish("S5-qa-automator-1", output=["evidence.txt"], complete=True)
            refused = ""
        except (StateConflict, ValueError) as exc:
            refused = str(exc)
        check("K7: a plan finished with --complete is refused by the controller (B1b)", refused != "", refused[:200])
        check_eq("K7: ... and stays running", env.status("S5-qa-automator-1"), "running")
        code, out = env.finish("S5-qa-automator-1", output=["evidence.txt"], not_complete=True, complete=True)
        check_eq("K7: --not-complete wins over --complete as everywhere", (code, env.status("S5-qa-automator-1")), (0, "accepted"))
    finally:
        env.close()


# --- K8: the next move, case by case -----------------------------------------------------------------------------------

def nxt(env, did):
    return story_step._plan_next(TICKET, env.root, env.c, did)


def k8_next_moves():
    env = Env("qa-s5c1-next-")
    try:
        send(env.c, env.root, "S5-qa-automator-1", AUTHOR, purpose=CT.S5_PLAN)
        fill(env.root, env.c)
        accept_it(env.c, env.root, "S5-qa-automator-1")
        check_eq("K8: author, no review yet: start the critic over the same scope",
                 nxt(env, "S5-qa-automator-1"),
                 (["story_step.py start --task QA-T --stage S5 --role qa-code-critic --purpose s5_plan --scope TC-1,TC-2"], []))
        review(env.c, env.root, "S5-qa-code-critic-1", "blocked", remark_text("PR-1", "blocker", case="TC-1", test="T-1"))
        check_eq("K8: critic blocked: rework the author over the cases the blockers bind",
                 nxt(env, "S5-qa-code-critic-1"),
                 (['controller.py --task QA-T --operation rework --stage S5 --role qa-automator --purpose s5_plan --cases TC-1 '
                   '--reason "mend the plan rows the critic blocked: PR-1" --brief'], []))
        rework = rework_author(env.c, env.root, assert_text="the response is 201")
        accept_it(env.c, env.root, rework)
        check_eq("K8: author's rework after a review: the critic's narrow look over the rows that moved",
                 nxt(env, rework),
                 (['controller.py --task QA-T --operation rework --stage S5 --role qa-code-critic --purpose s5_plan --cases TC-1 '
                   '--reason "look again at the plan rows that changed since your review: TC-1" --brief'], []))
        got, notes = nxt(env, "nope")
        check("K8: a dispatch the controller does not hold: no command, a note naming `where`", got == [] and notes and "where --task QA-T" in notes[0], notes)
        (env.root / SP.REVIEWS_REL).unlink()
        got, notes = nxt(env, "S5-qa-code-critic-1")
        check("K8 (AR-28): a review whose receipt is gone gives no command, a note with `where`",
              got == [] and notes and "cannot be read" in notes[0] and "where --task QA-T" in notes[0], (got, notes))
    finally:
        env.close()


def k8b_blocker_about_the_whole_plan():
    env = Env("qa-s5c1-whole-")
    try:
        send(env.c, env.root, "S5-qa-automator-1", AUTHOR, purpose=CT.S5_PLAN)
        fill(env.root, env.c)
        accept_it(env.c, env.root, "S5-qa-automator-1")
        review(env.c, env.root, "S5-qa-code-critic-1", "blocked", remark_text("PR-2", "blocker"))
        command = nxt(env, "S5-qa-code-critic-1")[0][0]
        check_eq("K8b: a blocker that names no case, test or Then binds no row: the whole scope goes back",
                 command.split(" --cases ")[1].split(" ")[0], "TC-1,TC-2")
    finally:
        env.close()


def k9_next_after_approved():
    """The windows are read from `stage_scope`: the first window without its author, then without its critic, and a grown window first."""
    env = Env("qa-s5c1-win-")
    try:
        send(env.c, env.root, "S5-qa-automator-1", AUTHOR, purpose=CT.S5_PLAN)
        fill(env.root, env.c)
        accept_it(env.c, env.root, "S5-qa-automator-1")
        review(env.c, env.root, "S5-qa-code-critic-1", "approved_with_remarks", remark_text("PR-1", "remark", case="TC-2"))
        check_eq("K9: approved with remarks: window 1's author", nxt(env, "S5-qa-code-critic-1"),
                 (["story_step.py start --task QA-T --stage S5 --role qa-automator --scope TC-1"], []))
        send(env.c, env.root, "S5-qa-automator-2", AUTHOR, scope=["TC-1"], accept=True)
        check_eq("K9: window 1 written: its critic is next", nxt(env, "S5-qa-code-critic-1")[0],
                 ["story_step.py start --task QA-T --stage S5 --role qa-code-critic --scope TC-1"])
        # TC-2's test now covers TC-1 as well: window 1 grows by TC-2 (t-1314 section 2 item 6)
        plan = SP.load(env.root)
        plan["tests"] = [dict(plan["tests"][0], cases=["TC-1", "TC-2"], thens=plan["tests"][0]["thens"] + plan["tests"][1]["thens"])]
        put(env.root, SP.PLAN_REL, json.dumps(plan))
        got, notes = nxt(env, "S5-qa-code-critic-1")
        check_eq("K9: a grown window goes back to its author with the new case and the test that ties it", (got, notes), (
            ['controller.py --task QA-T --operation rework --stage S5 --role qa-automator --cause ticket_changed --cases TC-1,TC-2 '
             '--reason "case(s) TC-2 added to S5 after the plan review; test(s) T-1 extend this window" --brief'], []))
        check_not_in("K9: a window rework carries no purpose word (it is not the plan)", "--purpose", got[0])
    finally:
        env.close()


def k10_ready_commands_end_with_brief():
    """SC1-8: a ready rework command the code prints ends with `--brief`."""
    command = story_step._rework_command("QA-T", "qa-automator", ["TC-1", "TC-2"], "why")
    check("K10: ends with --brief", command.endswith(" --brief"), command)
    check_not_in("K10: no cases given: no --cases", " --cases ", story_step._rework_command("QA-T", "qa-automator", [], "why"))


# --- K11-K14: SC1-14 fix round X (B-1, F-1, F-2, F-3) ---------------------------------------------------------------------

def _materialize(env, dispatch_id):
    args = argparse.Namespace(task=TICKET, dispatch_id=dispatch_id, wait_seconds=0)
    return env.say(story_step.materialize, args)


def _stale_plan(env):
    """The plan of a story whose case TC-2 joined after the review: no TC-2 row, the hashes of the earlier scope. Returns TC-1's row."""
    plan = SP.load(env.root)
    plan["cases"] = [row for row in plan["cases"] if row["case"] != "TC-2"]
    plan["scope_hash"], plan["gate_a_plan_hash"] = "old-scope", "old-gate"
    put(env.root, SP.PLAN_REL, json.dumps(plan))
    return plan["cases"][0]


def k11_materialize_refreshes_the_plan_rework():
    """B-1. KILLS: drop the `_s5_plan_init` call from `materialize` (the new case gets no row, the hashes stay stale: the window gate
    refuses for ever). Through the materialize path, not a direct `refresh` call."""
    env = Env("qa-s5x-mat-")
    try:
        env.start(AUTHOR)
        plan = fill(env.root, env.c)
        accept_it(env.c, env.root, "S5-qa-automator-1")
        review(env.c, env.root, "S5-qa-code-critic-1", "blocked", remark_text("PR-1", "blocker", case="TC-1", test="T-1"))
        rework = rework_author(env.c, env.root)
        first_row = _stale_plan(env)
        code, out = _materialize(env, rework)
        check_eq("K11 (B-1): materialize of the plan rework exits 0", code, 0)
        after = SP.load(env.root)
        fresh = SP._skeleton(env.root, env.c, "x")
        check_eq("K11 (B-1): the new case got its skeleton row, after the author's", [r["case"] for r in after["cases"]], ["TC-1", "TC-2"])
        check_eq("K11 (B-1): ... the old row is byte-equal", after["cases"][0], first_row)
        check_eq("K11 (B-1): ... the hashes are the current ones (the window gate compares them)",
                 (after["scope_hash"], after["gate_a_plan_hash"]), (fresh["scope_hash"], fresh["gate_a_plan_hash"]))
        check_eq("K11 (B-1): ... the author's tests are kept and nothing went to .prev", (after["tests"], (env.root / SP.PREV_REL).exists()),
                 (plan["tests"], False))
        check_in("K11 (B-1): the note says so", "plan skeleton:", out)
        again = (env.root / SP.PLAN_REL).read_bytes()
        _materialize(env, rework)
        check_eq("K11 (idempotent): a repeat materialize changes no byte of the plan (E11)", (env.root / SP.PLAN_REL).read_bytes(), again)
        # refused materialize: a differing card is refused BEFORE the plan is touched
        _stale_plan(env)
        stale_bytes = (env.root / SP.PLAN_REL).read_bytes()
        story_step.launch_card.card_path(env.root, rework).write_text("a card of an earlier packet\n", encoding="utf-8")
        try:
            _materialize(env, rework)
            refused = ""
        except ValueError as exc:
            refused = str(exc)
        check("K11: a refused materialize (differing card) is a refusal naming the door", "differs" in refused, refused[:200])
        check_eq("K11: ... and wrote no plan", (env.root / SP.PLAN_REL).read_bytes(), stale_bytes)
        # no plan file: as today, none is begun
        story_step.launch_card.card_path(env.root, rework).unlink()
        (env.root / SP.PLAN_REL).unlink()
        _materialize(env, rework)
        check_eq("K11 (edge): a materialize with no plan file begins none", (env.root / SP.PLAN_REL).exists(), False)
        # an unreadable plan: a note with the door, never silence
        put(env.root, SP.PLAN_REL, b"{half")
        code, out = _materialize(env, rework)
        check("K11 (edge): an unreadable plan is a note with the door, and the file is untouched",
              "--init" in out and (env.root / SP.PLAN_REL).read_bytes() == b"{half", out[-300:])
    finally:
        env.close()


def k12_resumed_card_names_the_brief_once():
    """F-1. KILLS: print `Read <brief> first` after the resumed line."""
    stage = {"id": "S5", "inputs": []}
    resumed = ("You are resumed (same agent as P): the brief is already read; read only d.md. If you do not hold P's context, read b.md first.",)
    card = story_step._prompt(TICKET, stage, "qa-automator", "S5-qa-automator-3", [], "qa-factory/x/b.md", "", resumed)
    check_eq("K12 (F-1): a resumed card says nothing more about the brief", "first; it names the files" in card, False)
    check_eq("K12 (F-1): ... the brief is named once, in the fallback", card.count("b.md"), 1)
    plain = story_step._prompt(TICKET, stage, "qa-automator", "S5-qa-automator-3", [], "qa-factory/x/b.md", "", ())
    check_in("K12 (F-1, control): a card that is not resumed still names it", "Read qa-factory/x/b.md first; it names the files and the commands.", plain)


def k13_plan_critic_gets_no_code_inputs():
    """F-2. KILLS: `_prompt_inputs` / `_inputs_notes` without the plan exemption."""
    env = Env("qa-s5x-inputs-")
    real_active = story_step.judge.active
    story_step.judge.active = lambda *a, **k: True
    try:
        send(env.c, env.root, "S5-qa-automator-1", AUTHOR, purpose=CT.S5_PLAN)
        fill(env.root, env.c)
        accept_it(env.c, env.root, "S5-qa-automator-1")
        review(env.c, env.root, "S5-qa-code-critic-1", "blocked", remark_text("PR-1", "blocker", case="TC-1", test="T-1"))
        put(env.root, "work/judge-code-S5-qa-code-critic-1.json", "{}")
        put(env.root, "work/probe-debt/S5-qa-code-critic-1.json", "{}")
        put(env.root, "work/probe-debt.json", "{}")
        extras = story_step._prompt_inputs(TICKET, "S5", CRITIC, env.root, "S5-qa-code-critic-1")
        check_eq("K13 (F-2): the plan critic is handed no judge output and no debt", extras, [])
        notes = story_step._inputs_notes(TICKET, "S5", CRITIC, "S5-qa-code-critic-1", env.root)
        check("K13 (F-2): ... and no `probe_debt --settle` instruction", not any("probe_debt" in n for n in notes), notes)
        put(env.root, "work/judge-code-S5-qa-code-critic-9.json", "{}")      # TR3-15: one judge file per critic dispatch, listed once it exists
        check_in("K13 (F-2, control): a window critic (no record) is still handed the judge output",
                 f"qa-factory/artifacts/{TICKET}/work/judge-code-S5-qa-code-critic-9.json", story_step._prompt_inputs(TICKET, "S5", CRITIC, env.root, "S5-qa-code-critic-9"))
        check("K13 (F-2, control): ... and still told to settle", any("probe_debt" in n for n in story_step._inputs_notes(
            TICKET, "S5", CRITIC, "S5-qa-code-critic-9", env.root)))
    finally:
        story_step.judge.active = real_active
        env.close()


def k14_bind_set_agent_is_no_resume():
    """F-3. KILLS: reading `agent_id` off a record `bind` touched (a fresh agent told "you are resumed")."""
    packet = {"id": "S5-qa-automator-3", "stage": "S5", "rework_of": "S5-qa-automator-2", "agent_id": "agent-7", "reason": "m",
              "repair_cause": "test_defect", "purpose": "s5_plan", "input_hash": "h"}
    check_eq("K14 (F-3, control): the request's own agent_id is a resume", len(story_step._packet_lines(packet, TICKET)), 3)
    check_eq("K14 (F-3): an id `bind` set on the record (agent_bound_seq) is none", len(story_step._packet_lines(dict(packet, agent_bound_seq=12), TICKET)), 2)
    env = Env("qa-s5x-bind-")
    try:
        env.start(AUTHOR)
        fill(env.root, env.c)
        accept_it(env.c, env.root, "S5-qa-automator-1")
        review(env.c, env.root, "S5-qa-code-critic-1", "blocked", remark_text("PR-1", "blocker", case="TC-1", test="T-1"))
        rework = rework_author(env.c, env.root)
        record = dict(env.c.state()["dispatches"][rework], agent_id="host-1", agent_bound_seq=9)
        event = story_step._request_packet(env.root, record)
        check_eq("K14 (F-3): `where` renders from the committed event: no bind-set id there", ("agent_id" in event, "agent_bound_seq" in event), (False, False))
        check_eq("K14 (F-3): ... so a fresh agent bound after the start is not told it is resumed", len(story_step._packet_lines(event, TICKET)), 2)
        check_eq("K14 (F-3): a record `bind` never touched is the record itself", story_step._request_packet(env.root, {"id": "x"}), {"id": "x"})
        lost = story_step._request_packet(env.root, {"id": "nope", "agent_id": "a", "agent_bound_seq": 1, "stage": "S5"})
        check_eq("K14 (F-3, FR-59): an event that cannot be read: the record without the id (the fresh direction)", lost, {"id": "nope", "stage": "S5"})
    finally:
        env.close()


def main():
    for name, fn in sorted(globals().items()):
        if name.startswith("k") and name[1:2].isdigit() and callable(fn):
            fn()
    finish("test_story_step_s5_plan")


if __name__ == "__main__":
    main()
