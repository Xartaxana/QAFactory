#!/usr/bin/env python3
"""SC1-14 B1a: every reader of S5 dispatch records tells the plan from a window.

S5 holds two kinds of dispatch of one role: the PLAN (one dispatch of the author and one of the critic over EVERY case of the stage,
`purpose: s5_plan`) and the WINDOWS. A reader that took "the accepted S5 dispatch of this role and scope" without the kind read the
plan as a window: the plan critic stood in for window 1's critic, closed S5, spent a window's repair round, parented a rework, was
a window's reviewer, a progress group, a probe author. `controller.s5_part_of` is the one reader of the kind; this file pins each
site (spec t-1246 section 0r N1 and section 3, part B1a). A story whose S5 began on the old form has no plan record and reads as
before: each key has its old-form control. Every key names the mutation it kills (section 5, B1a).
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import SCRIPTS, check, check_eq, check_in, check_not_in, finish, temp_dir, cleanup  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import controller as CT  # noqa: E402
import probe_debt  # noqa: E402
import stage_status  # noqa: E402
import story_progress  # noqa: E402
import window_record  # noqa: E402
from controller import Controller  # noqa: E402
from event_store import StateConflict  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_controller_rework_scope import evidence  # noqa: E402
from test_s5_process import s5_task  # noqa: E402

PLAN = {"purpose": CT.S5_PLAN}
CASES = ("TC-1", "TC-2", "TC-3")


def receipt(identifier, role="qa-automator", scope=CASES, status="accepted", plan=False, **extra):
    """A dispatch record of S5 as the controller keeps it: a plan one carries the word in its `request_binding`."""
    item = {"id": identifier, "stage": "S5", "role": role, "scope": list(scope), "status": status}
    if plan:
        item["request_binding"] = dict(PLAN)
    item.update(extra)
    return item


def ledger_of(*receipts):
    return {r["id"]: r for r in receipts}


def refusal(call):
    try:
        call()
    except (StateConflict, ValueError) as exc:
        return str(exc)
    return ""


def send(c, root, identifier, role="qa-automator", scope=CASES, plan=False, accept=True, **extra):
    """Dispatch (and accept) one S5 record; a plan one carries `purpose: s5_plan`. The accept says nothing of `stage_complete`
    unless asked: what the controller does with the silence is a part of the keys."""
    payload = dict({"id": identifier, "stage": "S5", "role": role, "scope": list(scope), "input_hash": "h", "budget": {},
                    "known_paths": {}, "idempotency_key": identifier}, **extra)
    if plan:
        payload["purpose"] = CT.S5_PLAN
    c.apply("dispatch", payload)
    if accept:
        c.apply("accept", {"id": identifier, "status": "accepted", "evidence_refs": [evidence(root, identifier + ".txt")],
                           "idempotency_key": identifier + "-ok"})


def without_plan_order(c):
    """B1a pins the READERS of the record kind; the plan order (B1b: no window without a plan file and a reviewed plan, no accept
    of a plan with a gap) is pinned in test_s5_plan_controller.py. Here the controller is told to wave it through."""
    c._s5_plan_problems = lambda p, state: []
    c._s5_plan_accept_problems = lambda d, p, state: []
    return c


def three_windows(root):
    """A story of three cases cut into three windows (one case each), with the plan dispatched before any window."""
    c = without_plan_order(s5_task(root, CASES))
    (root / "qa-factory" / "config.json").write_text(json.dumps({"dispatch": {"api_window_cases": 1}}), encoding="utf-8")
    check_eq("fixture: three windows of one case", [w["scope"] for w in c.stage_scope("S5")["windows"]],
             [["TC-1"], ["TC-2"], ["TC-3"]])
    return c


# --- the plan critic closes nothing, and stands in for no window's reviewer ---------------------------------------------------

def k1_the_plan_critic_does_not_close_the_stage():
    root = temp_dir("qa-s5kind-close-")
    try:
        c = three_windows(root)
        send(c, root, "S5-qa-automator-1", plan=True)
        send(c, root, "S5-qa-code-critic-1", role="qa-code-critic", plan=True)      # M13: no stage_complete, and it is accepted
        state = c.state()
        record = state["dispatches"]["S5-qa-code-critic-1"]
        check_eq("plan critic accepted with stage_complete absent -> accepted", record["status"], "accepted")
        check_eq("plan critic accepted with stage_complete absent -> not closed (the controller sets none)",
                 record.get("stage_complete"), None)
        check("plan critic accepted with stage_complete absent -> not closed: S5 is not completed",
              (state["stages"].get("S5") or {}).get("status") != "completed")
        check_eq("plan critic accepted -> _closes_stage is False", c._closes_stage(record, state), False)
        # the same record without the word is a critic of every case, the old form: it DOES close the stage (the control)
        old = dict(record, request_binding={})
        check_eq("control: a critic over every case without the word closes the stage", c._closes_stage(old, state), True)
        # an explicit `stage_complete: false` on a plan critic is not the refusal "leaves S5 with no role to close it"
        check_eq("plan critic with stage_complete false and no unresolved is not refused as closing the stage",
                 refusal(lambda: send(c, root, "S5-qa-code-critic-2", role="qa-code-critic", plan=True, accept=False)
                         or c.apply("accept", {"id": "S5-qa-code-critic-2", "status": "accepted", "stage_complete": False,
                                               "evidence_refs": [evidence(root, "plan-critic-2.txt")],
                                               "idempotency_key": "plan-critic-2-ok"})), "")
    finally:
        cleanup(root)


def k2_windows_with_the_plan_accepted():
    root = temp_dir("qa-s5kind-windows-")
    try:
        c = three_windows(root)
        send(c, root, "S5-qa-automator-1", plan=True)
        send(c, root, "S5-qa-code-critic-1", role="qa-code-critic", plan=True)
        send(c, root, "S5-qa-automator-2", scope=("TC-1",))
        windows = c.stage_scope("S5")["windows"]
        check_eq("the plan critic is in no window's accepted_by (M12): window 1 holds its author only",
                 windows[0]["accepted_by"], {"qa-automator": "S5-qa-automator-2"})
        check_eq("the plan is in no window's accepted_by (M12): windows 2 and 3 hold nothing",
                 [w["accepted_by"] for w in windows[1:]], [{}, {}])
        send(c, root, "S5-qa-code-critic-2", role="qa-code-critic", scope=("TC-1",), accept=False)
        state = c.state()
        critic = state["dispatches"]["S5-qa-code-critic-2"]
        check_eq("window 1 critic with windows 2-3 open does not close S5 (plan critic accepted)",
                 c._closes_stage(critic, state), False)
        c.apply("accept", {"id": "S5-qa-code-critic-2", "status": "accepted", "stage_complete": False,
                           "evidence_refs": [evidence(root, "w1-critic.txt")], "idempotency_key": "w1-critic-ok"})
        check_eq("window 1 critic --not-complete is accepted with the plan critic accepted",
                 c.state()["dispatches"]["S5-qa-code-critic-2"]["status"], "accepted")
        # progress after the plan (E33): window 2 of 3, one window done - the plan is not a group of its own
        send(c, root, "S5-qa-automator-3", scope=("TC-2",), accept=False)
        state = c.state()
        mine = list(state["dispatches"].values())
        position = story_progress._window_position(root, state, mine, state["dispatches"]["S5-qa-automator-3"], None)
        check_eq("progress shows window 2 of 3 after the plan",
                 (position["kind"], position["window"], position["windows_total"], position["windows_done"]),
                 ("window", 2, 3, 1))
        # the dashboard's window position for a story with no plan record is unchanged: the same records without the plan
        old = [d for d in mine if CT.s5_part_of(d) != "plan"]
        again = story_progress._window_position(root, state, old, state["dispatches"]["S5-qa-automator-3"], None)
        check_eq("control: with no plan record the position is the same", position, again)
    finally:
        cleanup(root)


# --- the counters: a plan is its own key ---------------------------------------------------------------------------------------

def k3_single_window_opener():
    plan = receipt("S5-qa-automator-1", plan=True)
    window = receipt("S5-qa-automator-2")
    both = ledger_of(plan, window)
    check_eq("single window: the window's first dispatch is the opener",
             CT.repair_ledger(both, window)["counted"], 0)
    check_eq("single window: the window's first dispatch is the opener (it opened the window)",
             CT.repair_ledger(both, window)["opened"], True)
    # the old form: two dispatches over the one window, the second is a round (control that the ledger counts at all)
    old = ledger_of(receipt("a1"), receipt("a2", rework_of="a1", purpose="repair_verify"))
    check_eq("control: with no plan record the second dispatch is a round", CT.repair_ledger(old, old["a2"])["counted"], 1)
    check_eq("the key of a window is unchanged (stage:role:hash of the scope)", CT.budget_scope(window),
             "S5:qa-automator:" + CT.content_hash(sorted(CASES)))
    check_eq("a window key is unchanged (stage:hash of the scope)", CT.window_key(window), "S5:" + CT.content_hash(sorted(CASES)))
    check_eq("the key of a plan is its own", CT.budget_scope(plan), "S5:qa-automator:plan")
    check_eq("the window key of a plan is its own", CT.window_key(plan), "S5:plan")
    check_eq("ledger_key follows budget_scope for a plan", CT.ledger_key(plan), "S5:qa-automator:plan")
    check_eq("a plan request (not yet a record) keys as a plan too",
             CT.budget_scope({"stage": "S5", "role": "qa-code-critic", "purpose": CT.S5_PLAN, "scope": list(CASES)}),
             "S5:qa-code-critic:plan")
    check_eq("a crooked record keys as a window (old behaviour)",
             CT.budget_scope({"stage": "S5", "role": "qa-automator", "scope": ["TC-1"], "request_binding": ["s5_plan"]}),
             "S5:qa-automator:" + CT.content_hash(["TC-1"]))


def k4_plan_rounds_spend_no_window_cap():
    p1 = receipt("p1", plan=True)
    p2 = receipt("p2", plan=True, rework_of="p1", purpose=CT.S5_PLAN)
    p3 = receipt("p3", plan=True, rework_of="p2", purpose=CT.S5_PLAN)
    w1 = receipt("w1")
    w2 = receipt("w2", rework_of="w1", purpose="repair_verify")
    led = ledger_of(p1, p2, p3, w1, w2)
    check_eq("plan rounds spend no window cap: the window has one round (its own)", CT.repair_rounds(led, w2), 1)
    check_eq("plan rounds are counted under the plan's own key", CT.repair_rounds(led, p3), 2)
    check_eq("plan rounds spend no window cap: the plan chain has no window's round in it",
             [r["id"] for r in CT.repair_ledger(led, p1)["rounds"]], ["p2", "p3"])
    check_eq("mechanical rounds of a plan are not the window's",
             CT.mechanical_rounds(ledger_of(receipt("m1", plan=True, repair_cause="mechanical"), w1), w1), 0)


# --- the parent of a rework ----------------------------------------------------------------------------------------------------

def k5_rework_parent_by_kind():
    root = temp_dir("qa-s5kind-rework-")
    try:
        c = three_windows(root)
        send(c, root, "S5-qa-automator-1", plan=True, agent_id="agent-plan")
        send(c, root, "S5-qa-code-critic-1", role="qa-code-critic", plan=True)
        send(c, root, "S5-qa-automator-2", scope=("TC-1",), agent_id="agent-w1")
        send(c, root, "S5-qa-automator-3", scope=("TC-2",), agent_id="agent-w2")
        check_eq("fixture: the host's agent id is on the record", c.state()["dispatches"]["S5-qa-automator-1"].get("agent_id"),
                 "agent-plan")
        plan_rework = c.build_rework_request("S5", "qa-automator", ["TC-1"], "plan stale", purpose=CT.S5_PLAN)
        check_eq("stale-plan rework after windows parents on the plan dispatch", plan_rework["rework_of"], "S5-qa-automator-1")
        window_rework = c.build_rework_request("S5", "qa-automator", ["TC-2"], "the window is wrong")
        check_eq("window rework parents on a window (the last window, not the plan)", window_rework["rework_of"],
                 "S5-qa-automator-3")
        check_eq("a window rework is for the window's purpose", window_rework["purpose"], "repair_verify")
        check_eq("the plan rework is for the plan's purpose", plan_rework["purpose"], CT.S5_PLAN)
        # agent_id: carried only on resume, from the parent of the right kind
        real = Controller._rework_mode
        try:
            check_eq("agent_id carried only on resume: S5 is `resume` in stages.json (the real reader), so the window's agent is carried",
                     window_rework.get("agent_id"), "agent-w2")
            Controller._rework_mode = staticmethod(lambda stage: "resume")
            again = c.build_rework_request("S5", "qa-automator", ["TC-2"], "the window is wrong")
            check_eq("agent_id carried only on resume: resume carries the window's agent", again.get("agent_id"), "agent-w2")
            plan_again = c.build_rework_request("S5", "qa-automator", ["TC-1"], "plan stale", purpose=CT.S5_PLAN)
            check_eq("agent_id carried only on resume: the plan rework carries the PLAN's agent",
                     plan_again.get("agent_id"), "agent-plan")
            # a parent with no agent id: nothing to carry (the card names `bind`)
            critic_rework = c.build_rework_request("S5", "qa-code-critic", ["TC-1"], "plan review again", purpose=CT.S5_PLAN)
            check_not_in("agent_id carried only on resume: a parent with no agent_id carries none (resume)", "agent_id",
                         json.dumps(critic_rework))
            Controller._rework_mode = staticmethod(lambda stage: "fresh")
            check_not_in("agent_id carried only on resume: fresh carries none", "agent_id",
                         json.dumps(c.build_rework_request("S5", "qa-automator", ["TC-2"], "x")))

            def unreadable(stage):
                raise OSError("stages.json is not readable")
            Controller._rework_mode = staticmethod(unreadable)
            check_not_in("agent_id carried only on resume: an unreadable rework_mode carries none", "agent_id",
                         json.dumps(c.build_rework_request("S5", "qa-automator", ["TC-2"], "x")))
            Controller._rework_mode = staticmethod(lambda stage: "")
            check_not_in("agent_id carried only on resume: an unknown mode word carries none", "agent_id",
                         json.dumps(c.build_rework_request("S5", "qa-automator", ["TC-2"], "x")))
        finally:
            Controller._rework_mode = staticmethod(real)     # read off the class it is a plain function: put it back as one
        check_eq("the seam is SC1-1 part B's reader: S5 resumes", Controller._rework_mode("S5"), "resume")
    finally:
        cleanup(root)


def k5c_the_rework_parent_is_the_window_of_the_cases():
    """t-CF (B3, F5, the `_rework_mode` hookup). KILLS: M-B3a the parent is `prior[-1]` (the last window's agent is resumed for
    window 1's cases); M-B3b a parent with no record still carries an agent; M-B3c a rework over two windows passes; M-F5 a person's
    words over two windows is refused or resumes an agent; M-H1 `_rework_mode` is the stub `fresh`."""
    root = temp_dir("qa-s5kind-parent-")
    try:
        c = three_windows(root)
        send(c, root, "S5-qa-automator-1", plan=True, agent_id="agent-plan")
        send(c, root, "S5-qa-code-critic-1", role="qa-code-critic", plan=True)
        send(c, root, "S5-qa-automator-2", scope=("TC-1",), agent_id="agent-w1")
        send(c, root, "S5-qa-automator-3", scope=("TC-2",), agent_id="agent-w2")
        send(c, root, "S5-qa-automator-4", scope=("TC-3",), agent_id="agent-w3")
        first = c.build_rework_request("S5", "qa-automator", ["TC-1"], "window 1 is wrong")
        check_eq("B3: the parent of a rework is the window of its cases, not the last record of the role", first["rework_of"],
                 "S5-qa-automator-2")
        check_eq("B3: ... and the agent resumed is that window's (S5 is `resume`)", first.get("agent_id"), "agent-w1")
        last = c.build_rework_request("S5", "qa-automator", ["TC-3"], "window 3 is wrong")
        check_eq("B3: the last window's cases still parent on the last window", (last["rework_of"], last.get("agent_id")),
                 ("S5-qa-automator-4", "agent-w3"))
        text = refusal(lambda: c.build_rework_request("S5", "qa-automator", ["TC-1", "TC-2"], "both are wrong"))
        check("B3: a rework over two windows is refused naming the windows and the door",
              "meets 2 windows" in text and "window 1: TC-1" in text and "window 2: TC-2" in text and "--words-file" in text
              and "<the cases of one window>" in text, text)
        spanning = c.build_rework_request("S5", "qa-automator", ["TC-1", "TC-2"], "the person said so", words_given=True)
        check_eq("F5: a person's-words rework over two windows is not refused and carries no agent_id",
                 ("agent_id" in spanning, spanning.get("person_words")), (False, True))
        check_eq("F5: ... its parent is the last record that meets the cases", spanning["rework_of"], "S5-qa-automator-3")
        check_eq("F5 control: the plan critic and the plan are no window's parent", first["purpose"], "repair_verify")
        # the plan rework is not a window rework: it spans every window and is not refused
        check_eq("B3: the plan's rework over every case is not a window rework",
                 c.build_rework_request("S5", "qa-automator", list(CASES), "plan stale", purpose=CT.S5_PLAN).get("agent_id"), "agent-plan")
    finally:
        cleanup(root)
    root = temp_dir("qa-s5kind-norecord-")
    try:
        c = three_windows(root)
        send(c, root, "S5-qa-automator-1", scope=("TC-1",), agent_id="agent-w1")
        request = c.build_rework_request("S5", "qa-automator", ["TC-3"], "window 3 was never written")
        check_eq("B3: cases no accepted record covers -> no agent_id (a fresh agent; the packet card names `bind`)",
                 ("agent_id" in request, request["rework_of"]), (False, "S5-qa-automator-1"))
        check_eq("B3 control: the same story, the window that IS written, carries its agent",
                 c.build_rework_request("S5", "qa-automator", ["TC-1"], "x").get("agent_id"), "agent-w1")
    finally:
        cleanup(root)


def k5e_the_rework_parent_is_the_authors_chain_not_the_cut_window():
    """FJ-C edge 4. KILLS: the parent read by the SCOPE of each record (or the window by the cut) instead of the author's chain: window 1
    was written by S5-qa-automator-2 over TC-1 and TC-2 and reworked by -3 over TC-1 alone (agent-w1b); a rework for TC-2 goes to the
    latest accepted member of the chain - -3, whose own scope does not meet TC-2 - and resumes the agent that holds the window now."""
    root = temp_dir("qa-s5kind-chain-")
    try:
        c = three_windows(root)
        send(c, root, "S5-qa-automator-1", plan=True, agent_id="agent-plan")
        send(c, root, "S5-qa-code-critic-1", role="qa-code-critic", plan=True)
        send(c, root, "S5-qa-automator-2", scope=("TC-1", "TC-2"), agent_id="agent-w1")
        send(c, root, "S5-qa-automator-3", scope=("TC-3",), agent_id="agent-w2")
        again = c.build_rework_request("S5", "qa-automator", ["TC-1"], "window 1 is wrong")
        check_eq("fixture: the rework of TC-1 parents on the window's author", again["rework_of"], "S5-qa-automator-2")
        c.apply("dispatch", dict(again, agent_id="agent-w1b"))
        c.apply("accept", {"id": again["id"], "status": "accepted", "evidence_refs": [evidence(root, "w1-rework.txt")],
                           "idempotency_key": "w1-rework-ok"})
        check_eq("fixture: the rework is a member of the chain, its own scope is TC-1 only",
                 [w["scope"] for w in c._written_windows(c.state(), list(CASES))], [["TC-1", "TC-2"], ["TC-3"]])
        request = c.build_rework_request("S5", "qa-automator", ["TC-2"], "window 1 is still wrong")
        check_eq("FJ-C: the rework parent is the author's chain, not the cut window: the latest accepted member of the chain, "
                 "though its own scope does not meet the case", (request["rework_of"], request.get("agent_id")), (again["id"], "agent-w1b"))
        text = refusal(lambda: c.build_rework_request("S5", "qa-automator", ["TC-2", "TC-3"], "both"))
        check("FJ-C: ... a rework over two written chains is still refused with the door", "meets 2 windows" in text
              and "window 1: TC-2" in text and "window 2: TC-3" in text and "--words-file" in text, text)
        words = c.build_rework_request("S5", "qa-automator", ["TC-2", "TC-3"], "the person said so", words_given=True)
        check_eq("FJ-C: ... and with a person's words it is not refused and resumes no agent", ("agent_id" in words, words.get("person_words")),
                 (False, True))
    finally:
        cleanup(root)


def k5d_rework_mode_reads_stages_json():
    """The `_rework_mode` seam is a call to `contract.rework_mode`. KILLS: M-H1 the stub; M-H2 a second parsing of stages.json."""
    import contract
    check_eq("the seam answers what stages.json says: S5 resumes", Controller._rework_mode("S5"), contract.rework_mode("S5"))
    check_eq("... and a fresh-agent stage is fresh", (Controller._rework_mode("S4"), Controller._rework_mode("S3")), ("fresh", "fresh"))
    check_eq("... and a stage the table does not name is fresh", Controller._rework_mode("S99"), "fresh")
    root = temp_dir("qa-s5kind-badtable-")
    try:
        bad = root / "stages.json"
        bad.write_text("{not json", encoding="utf-8")
        check_eq("a malformed stages.json is `fresh` (SC1-1's contract), it does not raise", contract.rework_mode("S5", path=bad), "fresh")
        real = contract.rework_mode
        try:
            def typo(stage):
                raise ValueError("stages.json: stage S5 has rework_mode 'resum'")
            contract.rework_mode = typo
            c = three_windows(root)
            send(c, root, "S5-qa-automator-1", scope=("TC-1",), agent_id="agent-w1")
            request = c.build_rework_request("S5", "qa-automator", ["TC-1"], "x")
            check_not_in("a rework_mode that is neither word is read as `fresh` by the request (no raise, no agent_id)", "agent_id",
                         json.dumps(request))
            contract.rework_mode = lambda stage: "resume"
            check_eq("the seam is routed through `contract.rework_mode`: a patched reader changes the request",
                     c.build_rework_request("S5", "qa-automator", ["TC-1"], "x").get("agent_id"), "agent-w1")
        finally:
            contract.rework_mode = real
    finally:
        cleanup(root)


def k5b_a_story_of_windows_only_has_no_plan_to_rework():
    """`--purpose s5_plan` on a story whose S5 began on the old form has no plan to parent on and says how to get one."""
    root = temp_dir("qa-s5kind-noplan-")
    try:
        c = three_windows(root)
        send(c, root, "S5-qa-automator-1", scope=("TC-1",))
        text = refusal(lambda: c.build_rework_request("S5", "qa-automator", ["TC-1"], "x", purpose=CT.S5_PLAN))
        check_in("no accepted S5 plan dispatch: names the role", "no accepted S5 plan dispatch of qa-automator to rework", text)
        check_in("no accepted S5 plan dispatch: names the door that dispatches one", "story_step.py start --purpose s5_plan", text)
        # the old form reads as before: a window rework parents on the window, no refusal
        request = c.build_rework_request("S5", "qa-automator", ["TC-1"], "x")
        check_eq("old form: a window rework parents on the window", request["rework_of"], "S5-qa-automator-1")
        check_eq("old form: the request carries exactly the keys it carried before the node (no agent_id)",
                 sorted(k for k in request if k in ("agent_id", "purpose", "rework_of")), ["purpose", "rework_of"])
    finally:
        cleanup(root)


def k6_rework_refusals_by_kind():
    root = temp_dir("qa-s5kind-refuse-")
    try:
        c = three_windows(root)
        text = refusal(lambda: c.build_rework_request("S5", "qa-automator", ["TC-1"], "x"))
        check_in("nothing accepted at all: the old refusal stands", "no accepted qa-automator dispatch on S5 to rework", text)
        check_not_in("nothing accepted at all: the new words are not used", "S5 window", text)
        send(c, root, "S5-qa-automator-1", plan=True)
        text = refusal(lambda: c.build_rework_request("S5", "qa-automator", ["TC-1"], "x"))
        check_in("only the plan is accepted: a window rework says there is no window yet",
                 "no accepted S5 window of qa-automator yet; the plan is reworked with `--purpose s5_plan`", text)
        check_eq("only the plan is accepted: the plan rework works",
                 c.build_rework_request("S5", "qa-automator", ["TC-1"], "x", purpose=CT.S5_PLAN)["rework_of"], "S5-qa-automator-1")
        # a live window dispatch of the role is the old live-dispatch refusal, not the plan's
        send(c, root, "S5-qa-automator-2", scope=("TC-1",), accept=False)
        text = refusal(lambda: c.build_rework_request("S5", "qa-automator", ["TC-1"], "x"))
        check_in("a running window is named as running, not as a missing window", "S5-qa-automator-2 is running", text)
    finally:
        cleanup(root)


# --- the stamp of a person's-words rework ------------------------------------------------------------------------------------

def k7_a_persons_words_rework_leaves_the_plan_review():
    plan_critic = receipt("pc", role="qa-code-critic", plan=True)
    window_critic = receipt("wc", role="qa-code-critic", scope=("TC-1",))
    plan_author = receipt("pa", plan=True)
    window_author = receipt("wa", scope=("TC-1",))
    check_eq("the plan critic is not a review of a window (M17)", Controller._is_review_of(plan_critic, "S5", "qa-automator"), False)
    check_eq("the window critic is (control)", Controller._is_review_of(window_critic, "S5", "qa-automator"), True)
    state = {"stages": {"S5": {"status": "completed"}}, "decisions": {},
             "dispatches": ledger_of(plan_author, plan_critic, window_author, window_critic)}
    stamp = Controller._rerun_stamp(state, "S5", "qa-automator", ["TC-1"])
    check_eq("a person's-words S5 rework leaves the plan review accepted", stamp.get("reviews"), ["wc"])
    old = {"stages": {"S5": {"status": "completed"}}, "decisions": {},
           "dispatches": ledger_of(window_author, window_critic)}
    check_eq("control: with no plan record the stamp names the window critic", Controller._rerun_stamp(
        old, "S5", "qa-automator", ["TC-1"]).get("reviews"), ["wc"])
    check_eq("another stage's critic is unchanged: S4 case critic is a review of S4",
             Controller._is_review_of({"stage": "S4", "role": "qa-case-critic", "status": "accepted"}, "S4", "qa-case-designer"),
             True)


# --- the window record: a plan is not the window's reviewer or author ---------------------------------------------------------

def k8_the_window_record_never_names_the_plan():
    plan_critic = receipt("pc", role="qa-code-critic", plan=True, input_hash="h")
    plan_author = receipt("pa", plan=True, input_hash="h")
    window_author = receipt("wa", input_hash="h")
    window_critic = receipt("wc", role="qa-code-critic", input_hash="h")
    check_eq("window record reviewer is never the plan critic: _same_window rejects the plan record",
             window_record._same_window(plan_critic, window_author), False)
    check_eq("control: a window record of the same scope and hash is the same window",
             window_record._same_window(window_critic, window_author), True)
    # the plan critic is LATER in the state than the window critic and has the same scope (single window): still not the peer
    state = {"dispatches": ledger_of(window_author, window_critic, plan_critic)}
    check_eq("window record reviewer is never the plan critic: _peer picks the window critic",
             window_record._peer(state, window_author, "qa-code-critic").get("id"), "wc")
    check_eq("window record author is never the plan author", window_record._peer(
        {"dispatches": ledger_of(plan_author, window_critic)}, window_critic, "qa-automator"), {})
    # the controller's twin (`_s5_v2_collect.same_window`): the same refusal, from the other side
    root = temp_dir("qa-s5kind-v2-")
    try:
        c = without_plan_order(s5_task(root, ("TC-1", "TC-2")))
        mine = receipt("wc", role="qa-code-critic", scope=("TC-1", "TC-2"), status="running", input_hash="h")

        def problems_for(author):
            state = {"dispatches": ledger_of(author, mine), "source_revision": None}
            out = []
            c._s5_v2_collect(mine, state, {"author_dispatch_id": author["id"], "reviewer_dispatch_id": "wc",
                                           "input_hash": "h", "instances": []}, out)
            return [str(text) for _, text in out]

        wanted = "coverage v2 S5 completion requires distinct accepted author and active critic for the same window"
        check_not_in("control: a window author of the same window is accepted by _s5_v2_collect", wanted,
                     " ".join(problems_for(receipt("wa", scope=("TC-1", "TC-2"), input_hash="h"))))
        check_in("a plan author is never the window's author in _s5_v2_collect", wanted,
                 " ".join(problems_for(receipt("pa", scope=("TC-1", "TC-2"), plan=True, input_hash="h"))))
    finally:
        cleanup(root)


# --- the dashboard: the plan is a kind, not a window --------------------------------------------------------------------------

def k9_progress_and_rounds():
    root = temp_dir("qa-s5kind-progress-")
    try:
        c = three_windows(root)
        send(c, root, "S5-qa-automator-1", plan=True, accept=False)
        state = c.state()
        running = state["dispatches"]["S5-qa-automator-1"]
        position = story_progress._window_position(root, state, list(state["dispatches"].values()), running, None)
        check_eq("progress while the plan runs: kind plan, its role, no window number", position,
                 {"kind": "plan", "role": "qa-automator", "dispatch": "S5-qa-automator-1"})
        c.apply("accept", {"id": "S5-qa-automator-1", "status": "accepted", "evidence_refs": [evidence(root, "pa.txt")],
                           "idempotency_key": "pa-ok"})
        state = c.state()
        position = story_progress._window_position(root, state, list(state["dispatches"].values()), None, None)
        check_eq("progress after the plan and before any window: kind plan", position["kind"], "plan")
    finally:
        cleanup(root)
    # rounds_spent reads the controller.json of a task
    task = temp_dir("qa-s5kind-rounds-")
    try:
        (task / "state").mkdir()

        def spend(*records):
            (task / "state" / "controller.json").write_text(json.dumps({"dispatches": ledger_of(*records)}), encoding="utf-8")
            return stage_status.rounds_spent(task, "S5", "qa-automator")

        p1 = receipt("p1", plan=True)
        p2 = receipt("p2", plan=True, rework_of="p1", purpose=CT.S5_PLAN)
        w1 = receipt("w1")
        w2 = receipt("w2", rework_of="w1", purpose="repair_verify")
        check_eq("rounds_spent ignores the plan: the last record is a window, the plan's narrow rework is not its round",
                 spend(p1, p2, w1, w2), 1)
        check_eq("rounds_spent of the plan: the last record is the plan, only plan records are counted",
                 spend(p1, w1, w2, p2), 1)
        check_eq("rounds_spent: a window not yet reworked has none, whatever the plan did", spend(p1, p2, w1), None)
        check_eq("control: with no plan record the count is as before", spend(w1, w2), 1)
        check_eq("another stage keeps its count", stage_status.rounds_spent(task, "S4", "qa-automator"), None)
    finally:
        cleanup(task)


# --- the probe debt: the author of a rebind is a window automator ------------------------------------------------------------

def k10_probe_author():
    task = temp_dir("qa-s5kind-probe-")
    try:
        (task / "state").mkdir()

        def author(*records):
            (task / "state" / "controller.json").write_text(json.dumps({"dispatches": ledger_of(*records)}), encoding="utf-8")
            return probe_debt._author_dispatch(task)

        check_eq("probe author is a window automator: the plan author after the window is skipped",
                 author(receipt("w1", scope=("TC-1",)), receipt("p1", plan=True)), "w1")
        check_eq("probe author is a window automator: the plan author before the first window is none",
                 author(receipt("p1", plan=True)), "")
        check_eq("control: with no plan record the latest accepted author", author(receipt("w1"), receipt("w2")), "w2")
        check_eq("the critic is never the author", author(receipt("c1", role="qa-code-critic")), "")
    finally:
        cleanup(task)


if __name__ == "__main__":
    k1_the_plan_critic_does_not_close_the_stage()
    k2_windows_with_the_plan_accepted()
    k3_single_window_opener()
    k4_plan_rounds_spend_no_window_cap()
    k5_rework_parent_by_kind()
    k5b_a_story_of_windows_only_has_no_plan_to_rework()
    k5c_the_rework_parent_is_the_window_of_the_cases()
    k5e_the_rework_parent_is_the_authors_chain_not_the_cut_window()
    k5d_rework_mode_reads_stages_json()
    k6_rework_refusals_by_kind()
    k7_a_persons_words_rework_leaves_the_plan_review()
    k8_the_window_record_never_names_the_plan()
    k9_progress_and_rounds()
    k10_probe_author()
    finish("test_s5_kind_readers")
