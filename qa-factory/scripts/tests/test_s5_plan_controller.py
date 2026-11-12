#!/usr/bin/env python3
"""SC1-14 B1b: the controller enforces the S5 plan order, the exit gate reads the plan, the review chain is capped.

A window of S5 is dispatched only against a plan that is there, read, clean, reviewed, not blocked and still the one that was
reviewed (`planned` form); a plan dispatch has its own shape (stage, role, parent, predecessor, cap); the accept of a plan never
closes S5 and asks the window's receipts of nobody. A story that began on the earlier form (`legacy`) is never asked for a plan.
Every key names the mutation it kills (spec t-1246 section 5, B1b: M18 window starts at `blocked`, M19 receipts asked of a plan,
M20 `stage_complete` accepted on a plan, M21 `legacy` requires a plan, M22 the driver passes on the plan form, M23 a rework changes a
row outside the blockers, M24 a block name is a substring of another) and the two revisions of the re-check (R1, R2).
"""
import ast
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import SCRIPTS, check, check_eq, check_in, check_not_in, cleanup, finish, temp_dir  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import contract as CC  # noqa: E402
import controller as CT  # noqa: E402
import exit_gate  # noqa: E402
import s5_plan as SP  # noqa: E402
import waiver as W  # noqa: E402
from event_store import StateConflict  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_controller_rework_scope import evidence  # noqa: E402
from test_s5_plan import put, s5_story  # noqa: E402
from test_s5_plan_check import remark_text, test_row, write_form  # noqa: E402

os.environ.pop("QA_FACTORY_RUN_MODE", None)      # a desktop process: the plan form is the default of an S5 with no record
CASES = ("TC-1", "TC-2")
AUTHOR, CRITIC = "qa-automator", "qa-code-critic"
WORD_WINDOWS, WORD_FORM, WORD_ROUND = "plan before windows", "plan form switch", "plan review round"


def refused(call):
    try:
        call()
    except (StateConflict, ValueError) as exc:
        return f"{type(exc).__name__}: {exc}"
    return ""


def story(root, legacy_window=False):
    """A controller task at S5 with gate A approved and two windows (one case each)."""
    c = s5_story(root, cases=CASES, with_case_files=True)
    put(root, "qa-factory/config.json", json.dumps({"dispatch": {"api_window_cases": 1}}))
    return c


def send(c, root, ident, role, scope=CASES, purpose=None, accept=False, **extra):
    payload = dict({"id": ident, "stage": "S5", "role": role, "scope": list(scope), "input_hash": "h", "budget": {},
                    "known_paths": {}, "idempotency_key": ident}, **extra)
    if purpose:
        payload["purpose"] = purpose
    c.apply("dispatch", payload)
    if accept:
        accept_it(c, root, ident)


def accept_it(c, root, ident, **extra):
    c.apply("accept", dict({"id": ident, "status": "accepted", "evidence_refs": [evidence(root, ident + ".txt")],
                            "idempotency_key": ident + "-ok"}, **extra))


def fill(root, c, assert_text=None):
    """The skeleton, then one `new` test per case (every Then of the case in it)."""
    plan = SP.init(root, c)
    plan["tests"] = [test_row(f"T-{i}", [row["case"]], [f"{row['case']}#{t['n']}" for t in row["thens"]])
                     for i, row in enumerate(plan["cases"], 1)]
    if assert_text:
        plan["tests"][0]["assert"] = assert_text
    put(root, SP.PLAN_REL, json.dumps(plan))
    return plan


def review(c, root, ident, outcome, *remarks, rework=False):
    """The plan critic's dispatch: the form, the receipt `finish` writes, the accept. `rework` sends the parent back."""
    if rework:
        c.apply("dispatch", c.build_rework_request("S5", CRITIC, list(CASES), "look again", purpose=CT.S5_PLAN))
        ident = sorted(d for d in c.state()["dispatches"] if d.startswith("S5-" + CRITIC))[-1]
    else:
        send(c, root, ident, CRITIC, purpose=CT.S5_PLAN)
    write_form(root, ident, outcome, *remarks)
    SP.stamp_review(root, ident)
    accept_it(c, root, ident)
    return ident


def rework_author(c, root, assert_text=None, **kw):
    request = c.build_rework_request("S5", AUTHOR, list(CASES), "mend the blocker rows", purpose=CT.S5_PLAN, **kw)
    c.apply("dispatch", request)
    plan = SP.load(root)
    if assert_text:
        plan["tests"][0]["assert"] = assert_text
        put(root, SP.PLAN_REL, json.dumps(plan))
    return request["id"]


def approved(root, outcome="approved", *remarks):
    c = story(root)
    send(c, root, "S5-qa-automator-1", AUTHOR, purpose=CT.S5_PLAN)
    fill(root, c)
    accept_it(c, root, "S5-qa-automator-1")
    review(c, root, "S5-qa-code-critic-1", outcome, *remarks)
    return c


def probe(c, request):
    """What the plan order says to this dispatch request, without committing it (a started window would block the next probe)."""
    state = c.state()
    return refused(lambda: CT.Controller._raise_all(c._s5_plan_problems(request, state)))


def window(c, root, ident="S5-qa-automator-9", case="TC-1", role=AUTHOR):
    return probe(c, {"id": ident, "stage": "S5", "role": role, "scope": [case]})


BLOCKER = remark_text("PR-1", "blocker", case="TC-1", test="T-1")
NOTE = remark_text("PR-2", "remark", case="TC-2")


# --- the window gate: every refusal, then all at once --------------------------------------------------------------------------

def k1_window_refusals():
    root = temp_dir("qa-s5pc-win-")
    try:
        c = story(root)
        text = window(c, root)
        check("K1 (E21): a bare window with no plan on the plan form is refused, every gap listed at once",
              "2 problems" in text and "there is no work/s5-plan.json" in text and "no accepted review of the plan" in text, text)
        check("K1: each refusal names its door and the word that passes it", "story_step.py start" in text and f'--block "{WORD_WINDOWS}"' in text, text)
        send(c, root, "S5-qa-automator-1", AUTHOR, purpose=CT.S5_PLAN)
        put(root, SP.PLAN_REL, "{not json")
        check_in("K1 (2): an unreadable plan is refused", "cannot be read", window(c, root))
        put(root, SP.PLAN_REL, json.dumps({"schema": 1}))
        check_in("K1 (3): a plan with gaps is refused with the gaps", "gap(s)", window(c, root, "S5-qa-automator-8"))
        fill(root, c)
        accept_it(c, root, "S5-qa-automator-1")
        check_in("K1 (4): a clean plan nobody reviewed is refused", "no accepted review of the plan", window(c, root, "S5-qa-automator-7"))
        review(c, root, "S5-qa-code-critic-1", "approved")
        check_eq("K1: the reviewed plan lets the window start", window(c, root, "S5-qa-automator-6"), "")
        plan = SP.load(root)
        plan["scope_hash"] = "other"
        put(root, SP.PLAN_REL, json.dumps(plan))
        text = window(c, root, "S5-qa-automator-5", case="TC-2")
        check("K1 (8)+(7): other cases/approved plan, and a plan changed after the review, are both listed",
              "other cases or another approved test plan" in text and "changed after its last accepted review" in text, text)
        plan["scope_hash"] = SP.current_hashes(root, c)[0]
        plan["cases"] = [r for r in plan["cases"] if r["case"] != "TC-2"]
        put(root, SP.PLAN_REL, json.dumps(plan))
        check_in("K1 (9): a window's case the plan does not have is refused", "not in the plan", window(c, root, "S5-qa-automator-4", case="TC-2"))
    finally:
        cleanup(root)


def k2_blocked_and_the_cap():
    root = temp_dir("qa-s5pc-blk-")
    try:
        c = approved(root, "blocked", BLOCKER, NOTE)
        text = window(c, root)
        check("K1 (6) M18: a blocked plan refuses the window and names the door (the rework of the author)",
              "blocks the plan (PR-1)" in text and "--purpose s5_plan" in text and "three moves" not in text, text)
        check_not_in("K1 (6): the word `plan review round` is not yet put to the conductor", WORD_ROUND, text)
        author = rework_author(c, root, assert_text="the response is 201")
        accept_it(c, root, author)
        # R1: the first look after a blocker is allowed (the cap counts looks AFTER a blocker, and this is the first)
        review(c, root, "S5-qa-code-critic-2", "blocked", remark_text("PR-3", "blocker", case="TC-1", test="T-1"), rework=True)
        text = window(c, root)
        check("K1 (6): blocked again after the re-look - the conductor gets the three moves, with their cost",
              "three moves" in text and WORD_WINDOWS in text and WORD_ROUND in text and "about one call of the author" in text, text)
        chain = SP.reviews(root, c.state())
        check_eq("R1: the chain has had one look after a blocker and none for new cases", SP.looks(chain), {"after_blocker": 1, "new_cases": 0})
        again = c.build_rework_request("S5", CRITIC, list(CASES), "once more", purpose=CT.S5_PLAN)
        text = refused(lambda: c.apply("dispatch", again))
        check("(2e): a second look after a blocker is refused with the word `plan review round`",
              WORD_ROUND in text and "StateConflict" in text, text)
        pipeline = json.loads((root / "pipeline.json").read_text(encoding="utf-8"))
        W.apply_stage_override(pipeline, "S5", WORD_ROUND, "one more round", W.now_iso())
        put(root, "pipeline.json", json.dumps(pipeline))
        check_eq("(2e): the person's word passes it", refused(lambda: c.apply("dispatch", again)), "")
        # the word `plan before windows` passes the window refusal; the word of another refusal does not
        check_in("M24: the word of the round cap does not pass the window refusal", "blocks the plan", window(c, root))
        W.apply_stage_override(pipeline, "S5", WORD_WINDOWS, "go on, the blocker goes into the window", W.now_iso())
        put(root, "pipeline.json", json.dumps(pipeline))
        check_eq("(6): the person's word `plan before windows` lets the window start", window(c, root), "")
        check_in("the blocker of the LAST review goes to the window as a remark", "PR-3",
                 SP.render_slice(SP.window_slice(root, 1, c.state())))
    finally:
        cleanup(root)


def k3_r1_new_cases_look_has_its_own_cap():
    root = temp_dir("qa-s5pc-r1-")
    try:
        c = approved(root, "blocked", BLOCKER)
        accept_it(c, root, rework_author(c, root, assert_text="the response is 201"))
        review(c, root, "S5-qa-code-critic-2", "approved", rework=True)
        chain = SP.reviews(root, c.state())
        check_eq("R1: two reviews in the chain, one look - after a blocker", (len(chain), SP.looks(chain)), (2, {"after_blocker": 1, "new_cases": 0}))
        check_eq("R1: the next look would be the look for new cases", SP.next_look(chain), "new_cases")
        request = {"id": "r", "stage": "S5", "role": CRITIC, "scope": list(CASES), "purpose": CT.S5_PLAN, "rework_of": "S5-qa-code-critic-2"}
        check_eq("R1: the look for new cases is NOT refused although the chain already has two reviews", probe(c, request), "")
    finally:
        cleanup(root)
    root = temp_dir("qa-s5pc-r1b-")
    try:
        c = approved(root)
        review(c, root, "S5-qa-code-critic-2", "approved", rework=True)         # the look for new cases, the first and the only
        chain = SP.reviews(root, c.state())
        check_eq("R1: a look after an approval is a look for new cases", SP.looks(chain), {"after_blocker": 0, "new_cases": 1})
        request = {"id": "r2", "stage": "S5", "role": CRITIC, "scope": list(CASES), "purpose": CT.S5_PLAN, "rework_of": "S5-qa-code-critic-2"}
        text = probe(c, request)
        check("R1: a second look for new cases is refused (its own cap of 1) with the word `plan review round`",
              WORD_ROUND in text and "StateConflict" in text, text)
    finally:
        cleanup(root)


def k4_r2_the_stamp_of_the_last_accepted_review():
    root = temp_dir("qa-s5pc-r2-")
    try:
        c = approved(root)
        stamp = SP.reviews(root, c.state())[-1]["plan_sha256"]
        plan = SP.load(root)
        plan["refactor"] = "changed after the review"
        put(root, SP.PLAN_REL, json.dumps(plan))
        # a critic looks at the changed plan: the receipt is written (finish does it first) and the accept is REFUSED
        c.apply("dispatch", c.build_rework_request("S5", CRITIC, list(CASES), "look again", purpose=CT.S5_PLAN))
        write_form(root, "S5-qa-code-critic-2", "approved")
        SP.stamp_review(root, "S5-qa-code-critic-2")
        put(root, SP.PLAN_REL, json.dumps(dict(plan, refactor="and changed once more")))      # ... and the accept is refused: sha differs
        text = refused(lambda: accept_it(c, root, "S5-qa-code-critic-2"))
        check("accept of a critic: the stamp measured on other bytes is refused", "changed after this review was stamped" in text, text)
        lines = json.loads((root / SP.REVIEWS_REL).read_text(encoding="utf-8"))
        check_eq("R2: the refused dispatch's stamp is the LAST line of the file", lines[-1]["dispatch"], "S5-qa-code-critic-2")
        put(root, SP.PLAN_REL, json.dumps(plan))       # the plan is back to the bytes the REFUSED review stamped
        check_in("R2: the gate takes the stamp of the last ACCEPTED review, not the last line of the file: still changed",
                 "changed after its last accepted review (S5-qa-code-critic-1)", window(c, root))
        check_eq("R2 control: the first review's stamp is the accepted one", SP.reviews(root, c.state())[-1]["plan_sha256"], stamp)
    finally:
        cleanup(root)


def k5_e32_a_persons_words_rework_of_the_plan():
    root = temp_dir("qa-s5pc-e32-")
    try:
        c = approved(root)
        check_eq("fixture: the reviewed plan lets a window start", window(c, root, "S5-qa-automator-8"), "")
        request = c.build_rework_request("S5", AUTHOR, list(CASES), "the person's words", purpose=CT.S5_PLAN, words_given=True)
        check_eq("E32: the rework carries the person's words", request.get("person_words"), True)
        c.apply("dispatch", request)
        plan = SP.load(root)
        plan["tests"][1]["assert"] = "the person asked for this"
        put(root, SP.PLAN_REL, json.dumps(plan))
        check_eq("E32: a person's-words rework may change any row (no blocker bounds it)", refused(lambda: accept_it(c, root, request["id"])), "")
        states = {d["id"]: d["status"] for d in c.state()["dispatches"].values()}
        check_eq("E32: the plan critic's review stays accepted (B1a)", states["S5-qa-code-critic-1"], "accepted")
        check_in("E32: the changed plan stales the review through the sha check (E11)", "changed after its last accepted review", window(c, root))
    finally:
        cleanup(root)


# --- the plan dispatch -------------------------------------------------------------------------------------------------------

def k6_plan_dispatch_shape():
    root = temp_dir("qa-s5pc-req-")
    try:
        c = story(root)
        base = {"id": "x", "stage": "S5", "role": AUTHOR, "scope": list(CASES), "input_hash": "h", "budget": {}, "known_paths": {},
                "idempotency_key": "x", "purpose": CT.S5_PLAN}
        text = refused(lambda: c.apply("dispatch", dict(base, stage="S4", id="x1", idempotency_key="x1", role="qa-case-designer")))
        check("(2a) E23: the word on S4 is refused naming the stage and the role", "ValueError" in text and "stage S4" in text, text)
        text = refused(lambda: c.apply("dispatch", dict(base, role="qa-runner", id="x2", idempotency_key="x2")))
        check("(2a): the word on another role of S5 is refused", "ValueError" in text and "qa-runner" in text, text)
        text = refused(lambda: c.apply("dispatch", dict(base, role=CRITIC, id="x3", idempotency_key="x3")))
        check("(2c): the critic of the plan before the author's plan is accepted is refused, with the door of the author",
              "StateConflict" in text and "dispatch the author first" in text and "story_step.py start" in text, text)
        send(c, root, "S5-qa-automator-1", AUTHOR, purpose=CT.S5_PLAN)
        fill(root, c)
        accept_it(c, root, "S5-qa-automator-1")
        text = refused(lambda: c.apply("dispatch", dict(base, id="x4", idempotency_key="x4")))
        check("(2d): a fresh author's plan beside an accepted one is refused with the rework door",
              "reworked, not dispatched again" in text and "--operation rework" in text, text)
        # a window before the review: refused by the gate. The refusal is ASSERTED - a gate that let the window through must
        # fail this key, not skip it (t-1320 F-7: the check used to sit in an `except` that a passing window never reached)
        text = refused(lambda: send(c, root, "S5-qa-automator-2", AUTHOR, scope=("TC-1",)))
        check("a window before the review is the gate's refusal, not a crash and not a pass",
              "StateConflict" in text and "no accepted review" in text, text)
    finally:
        cleanup(root)
    root = temp_dir("qa-s5pc-req2-")
    try:
        c = approved(root)
        base = {"id": "y", "stage": "S5", "role": CRITIC, "scope": list(CASES), "input_hash": "h", "budget": {}, "known_paths": {},
                "idempotency_key": "y", "purpose": CT.S5_PLAN}
        check_in("(2d) E25: a second fresh plan critic is refused - one critic per stage, the second look is a rework",
                 "reworked, not dispatched again", refused(lambda: c.apply("dispatch", base)))
        send(c, root, "S5-qa-automator-2", AUTHOR, scope=("TC-1",), accept=True)
        text = refused(lambda: c.apply("dispatch", dict(base, id="y2", idempotency_key="y2", role=AUTHOR, rework_of="S5-qa-automator-2")))
        check("(2a) E23: a rework of a WINDOW with the word is refused", "requires a rework of a plan dispatch" in text and "ValueError" in text, text)
    finally:
        cleanup(root)


def k7_legacy_and_the_driver():
    root = temp_dir("qa-s5pc-leg-")
    try:
        old = os.environ.get("QA_FACTORY_RUN_MODE")
        os.environ["QA_FACTORY_RUN_MODE"] = "driver"
        try:
            c = story(root)
            check_eq("K7 (E21): the driver's first window of a story with no record passes (the earlier form)",
                     refused(lambda: send(c, root, "S5-qa-automator-1", AUTHOR, scope=("TC-1",), accept=True)), "")
            os.environ.pop("QA_FACTORY_RUN_MODE")
            check_eq("K7 M21: a window of a story on the earlier form needs no plan, no file, no review (desktop process)",
                     window(c, root, "S5-qa-automator-2", case="TC-2"), "")
            body = dict(id="z", stage="S5", role=AUTHOR, scope=list(CASES), input_hash="h", budget={}, known_paths={},
                        idempotency_key="z", purpose=CT.S5_PLAN)
            text = refused(lambda: c.apply("dispatch", body))
            check("K7 (2b): a plan on a story that began on the earlier form is refused with the word `plan form switch`",
                  "StateConflict" in text and "began on the earlier form" in text and WORD_FORM in text, text)
            pipeline = json.loads((root / "pipeline.json").read_text(encoding="utf-8"))
            W.apply_stage_override(pipeline, "S5", WORD_FORM, "switch to the plan form", W.now_iso())
            put(root, "pipeline.json", json.dumps(pipeline))
            check_eq("K7 (2b): the person's word passes it", refused(lambda: c.apply("dispatch", body)), "")
        finally:
            if old is None:
                os.environ.pop("QA_FACTORY_RUN_MODE", None)
            else:
                os.environ["QA_FACTORY_RUN_MODE"] = old
    finally:
        cleanup(root)
    root = temp_dir("qa-s5pc-drv-")
    try:
        c = approved(root)
        os.environ["QA_FACTORY_RUN_MODE"] = "driver"
        try:
            text = window(c, root, "S5-qa-automator-5")
        finally:
            os.environ.pop("QA_FACTORY_RUN_MODE", None)
        check("K7 (10) M22: the driver on the plan form is refused with `plan form switch`, though the plan is reviewed",
              "does not run" in text and WORD_FORM in text, text)
        check_eq("K7 (10) control: the same window from a desktop process starts", window(c, root, "S5-qa-automator-6"), "")
    finally:
        cleanup(root)


# --- the accept of a plan -----------------------------------------------------------------------------------------------------

def k8_accept_of_the_plan():
    root = temp_dir("qa-s5pc-acc-")
    try:
        c = story(root)
        send(c, root, "S5-qa-automator-1", AUTHOR, purpose=CT.S5_PLAN)
        SP.init(root, c)
        text = refused(lambda: accept_it(c, root, "S5-qa-automator-1"))
        check("accept 1: a plan with a gap is refused with the gaps, as a repair for the role", "gap(s)" in text and "This is a repair" in text, text)
        fill(root, c)
        text = refused(lambda: accept_it(c, root, "S5-qa-automator-1", stage_complete=True))
        check("accept 2 M20: `stage_complete: true` on a plan is refused - a plan never closes S5", "a plan never closes S5" in text, text)
        check_eq("accept 3 M19: a clean plan is accepted on its evidence alone (no window receipts asked)",
                 refused(lambda: accept_it(c, root, "S5-qa-automator-1")), "")
        check_eq("accept 3: ... and S5 is not closed", (c.state()["stages"].get("S5") or {}).get("status") != "completed", True)
        send(c, root, "S5-qa-code-critic-1", CRITIC, purpose=CT.S5_PLAN)
        text = refused(lambda: accept_it(c, root, "S5-qa-code-critic-1"))
        check("accept critic 1: no form and no receipt - refused", "cannot be read" in text and "no form" in text, text)
        write_form(root, "S5-qa-code-critic-1", "approved", NOTE)
        SP.stamp_review(root, "S5-qa-code-critic-1")
        text = refused(lambda: accept_it(c, root, "S5-qa-code-critic-1"))
        check("accept critic 2 (E40): `approved` with a remark contradicts itself", "contradicts itself" in text and "`approved`" in text, text)
        write_form(root, "S5-qa-code-critic-1", "approved_with_remarks", NOTE)
        check_eq("accept critic 3: `approved_with_remarks` with a remark agrees", refused(lambda: accept_it(c, root, "S5-qa-code-critic-1")), "")
        check_eq("accept critic 3: the review is in the chain", [e["dispatch"] for e in SP.reviews(root, c.state())], ["S5-qa-code-critic-1"])
        for bad, outcome, kind in (("blocked without a blocker", "blocked", "remark"), ("approved_with_remarks with a blocker", "approved_with_remarks", "blocker")):
            problem = SP.verdict_problem({"outcome": outcome, "remarks": [{"id": "PR-1", "kind": kind}]})
            check(f"E40: {bad} is a contradiction", bool(problem), problem)
    finally:
        cleanup(root)


def k9_rework_changes_only_the_blocker_rows():
    root = temp_dir("qa-s5pc-e1-")
    try:
        c = approved(root, "blocked", BLOCKER, NOTE)
        author = rework_author(c, root)
        plan = SP.load(root)
        plan["tests"][0]["assert"] = "TC-1 row mended"
        plan["tests"][1]["assert"] = "TC-2 row changed too"
        put(root, SP.PLAN_REL, json.dumps(plan))
        text = refused(lambda: accept_it(c, root, author))
        check("E1 M23: a rework that changes a row no blocker names is refused with the list of cases",
              "which no blocker of S5-qa-code-critic-1 names" in text and "TC-2" in text and "TC-1," not in text, text)
        plan["tests"][1]["assert"] = test_row("T-2", ["TC-2"], ["TC-2#1"])["assert"]
        put(root, SP.PLAN_REL, json.dumps(plan))
        check_eq("E1: only the blocker's row changed - accepted", refused(lambda: accept_it(c, root, author)), "")
    finally:
        cleanup(root)


# --- the exit gate and the words -----------------------------------------------------------------------------------------------

def k10_exit_gate():
    root = temp_dir("qa-s5pc-eg-")
    try:
        state = {"dispatches": {"w": {"id": "w", "stage": "S5", "role": AUTHOR, "status": "accepted", "request_binding": {}},
                                "p": {"id": "p", "stage": "S5", "role": AUTHOR, "status": "running", "request_binding": {"purpose": CT.S5_PLAN}},
                                "c": {"id": "c", "stage": "S5", "role": CRITIC, "status": "running", "request_binding": {"purpose": CT.S5_PLAN}}}}
        put(root, "state/controller.json", json.dumps(state))
        check_eq("EG: the newest S5 record of the role is the plan -> it is the plan dispatch", (exit_gate._s5_plan_dispatch(root, AUTHOR) or {}).get("id"), "p")
        put(root, "state/controller.json", json.dumps({"dispatches": dict(state["dispatches"], w2={"id": "w2", "stage": "S5", "role": AUTHOR,
                                                                                                    "status": "running", "request_binding": {}})}))
        check_eq("EG: a window after the plan -> not a plan (the newest one decides)", exit_gate._s5_plan_dispatch(root, AUTHOR), None)
        put(root, "state/controller.json", "{broken")
        check_eq("EG: an unreadable state -> not a plan (today's check, the direction of refusing)", exit_gate._s5_plan_dispatch(root, AUTHOR), None)
        put(root, "state/controller.json", json.dumps(state))
        old = exit_gate.artifact_root
        exit_gate.artifact_root = lambda: Path(root).parent
        try:
            lines = exit_gate.required_outputs_errors(AUTHOR, Path(root).name)
            check("EG: the plan author without the plan file is told the file, not the manifest", len(lines) == 1 and "work/s5-plan.json" in lines[0]
                  and "automation-manifest" not in lines[0], str(lines))
            put(root, SP.PLAN_REL, "{}")
            check_eq("EG: with the plan file the author owes nothing else (no manifest, no evidence)", exit_gate.required_outputs_errors(AUTHOR, Path(root).name), [])
            lines = exit_gate.required_outputs_errors(CRITIC, Path(root).name)
            check("EG: the plan critic without a form is told the form", len(lines) == 1 and "work/handoffs/c.yaml" in lines[0], str(lines))
            put(root, "work/handoffs/c.yaml", "schema_version: 1\nreview:\n  outcome: approved\nremarks: []\n")
            check_eq("EG: a form with an empty `remarks` section is a section", exit_gate.required_outputs_errors(CRITIC, Path(root).name), [])
            put(root, "state/controller.json", json.dumps({"dispatches": {"w": state["dispatches"]["w"]}}))
            lines = exit_gate.required_outputs_errors(AUTHOR, Path(root).name)
            check("EG control: a window author still owes the manifest", len(lines) == 1 and "missing required output" in lines[0], str(lines))
        finally:
            exit_gate.artifact_root = old
    finally:
        cleanup(root)


def k11_words_and_nesting():
    words = (WORD_WINDOWS, WORD_FORM, WORD_ROUND)
    check("M24 block names: no word is a substring of another",
          not any(a != b and a in b for a in words for b in words), str(words))
    check_eq("the words are the controller's constants", (CT.WORD_PLAN_BEFORE_WINDOWS, CT.WORD_PLAN_FORM_SWITCH, CT.WORD_PLAN_REVIEW_ROUND), words)
    path = SCRIPTS / "controller.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    validate = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "validate")

    def depth(node, level=0):
        deeper = [depth(child, level + (1 if isinstance(child, (ast.If, ast.For, ast.While, ast.Try, ast.With)) else 0))
                  for child in ast.iter_child_nodes(node)]
        return max([level] + deeper)
    calls = [n for n in ast.walk(validate) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
             and n.func.attr in ("_s5_plan_problems", "_s5_plan_accept_problems")]
    check_eq("validate: the two branches are one call each", sorted(c.func.attr for c in calls), ["_s5_plan_accept_problems", "_s5_plan_problems"])
    # `depth` counts an `elif` as one more level, so the op chain of `validate` grows by one per op: 18 before B1b, 19 since c1f65a401 (PC-6)
    # added `elif op in HOLD_OPERATIONS:` to that chain (the new op's own branch is one call; no nested block was added to B1b's branches).
    check("validate: the nesting did not grow (the pinned depth is 19: B1b's 18 plus PC-6's one elif)", depth(validate) <= 19, str(depth(validate)))


# --- the chain fix round (t-1340): t-1320 F-1, F-2, F-3 -----------------------------------------------------------------------

def k12_f1_a_window_may_rewrite_the_test_a_later_row_extends():
    """KILLS: the window gate (3) calling the check WITH the project's files (`files=True`): window 2 was refused after window 1
    legitimately renamed the function an `extend` row builds on, though the plan's bytes had not moved (E11 holds those)."""
    root = temp_dir("qa-s5pc-f1-")
    try:
        c = story(root)
        put(root, "tests/test_api.py", "def test_create():\n    assert True\n")
        send(c, root, "S5-qa-automator-1", AUTHOR, purpose=CT.S5_PLAN)
        plan = fill(root, c)
        plan["tests"][1].update(shape="extend", extends="tests/test_api.py::test_create")
        put(root, SP.PLAN_REL, json.dumps(plan))
        check_eq("F-1 fixture: the plan with an extend row is clean against the files as they are", SP.check(root, c), [])
        accept_it(c, root, "S5-qa-automator-1")
        review(c, root, "S5-qa-code-critic-1", "approved")
        check_eq("F-1 fixture: window 1 may start", window(c, root, "S5-qa-automator-6"), "")
        put(root, "tests/test_api.py", "def test_create_renamed():\n    assert True\n")      # window 1 rewrote the function
        check_eq("F-1: window 2 is not refused for it - the plan is the one that was reviewed",
                 window(c, root, "S5-qa-automator-7", case="TC-2"), "")
        check("F-1 control: the full check (the author's accept, `--check`) still sees the missing function",
              any("test_create" in finding for finding in SP.check(root, c)), str(SP.check(root, c)))
        check_eq("F-1 control: `files=False` is what leaves the files alone", SP.check(root, c, files=False), [])
        plan["tests"][1]["extends"] = ""
        put(root, SP.PLAN_REL, json.dumps(plan))
        check_in("F-1 control: a changed plan is still the gate's (7), files or not",
                 "changed after its last accepted review", window(c, root, "S5-qa-automator-8", case="TC-2"))
    finally:
        cleanup(root)


def k13_f2_a_removed_test_does_not_lift_the_row_bound():
    """KILLS: `blocker_cases` resolving the blocker's test by the plan as it stands. The author removes (renames) the test the blocker
    names; the old lookup found nothing, returned None ("about the whole plan") and the rework could change ANY row."""
    root = temp_dir("qa-s5pc-f2-")
    try:
        c = approved(root, "blocked", remark_text("PR-1", "blocker", test="T-2"))
        chain = SP.reviews(root, c.state())
        check_eq("F-2: the receipt keeps the test -> cases map of the plan the critic saw", chain[-1]["tests"],
                 {"T-1": ["TC-1"], "T-2": ["TC-2"]})
        author = rework_author(c, root)
        plan = SP.load(root)
        plan["tests"][1]["id"] = "T-5"                        # the blocker's test is gone from the plan ...
        plan["tests"][0]["assert"] = "the response is 201"   # ... and a row no blocker names is changed with it
        put(root, SP.PLAN_REL, json.dumps(plan))
        text = refused(lambda: accept_it(c, root, author))
        check("F-2 M23: the change of TC-1's row, which no blocker binds, is refused though the blocker's test is gone",
              "TC-1" in text and "no blocker" in text, text)
        plan["tests"][0]["assert"] = "the response is 200"
        put(root, SP.PLAN_REL, json.dumps(plan))
        check_eq("F-2 control: renaming the blocker's own test (the row TC-2 only) is accepted", refused(lambda: accept_it(c, root, author)), "")
    finally:
        cleanup(root)


def k14_f3_the_three_moves_are_for_a_blocker_that_was_looked_at_again():
    """KILLS: the three-moves text keyed on `looks(chain)["after_blocker"] >= 1` (a chain-wide count): r1 blocked, r2 approved, r3
    blocked by a NEW case is not "reviewed again after the rework and the blocker stands" - nobody looked again at r3's blocker."""
    root = temp_dir("qa-s5pc-f3-")
    try:
        c = approved(root, "blocked", BLOCKER)
        accept_it(c, root, rework_author(c, root, assert_text="the response is 201"))
        review(c, root, "S5-qa-code-critic-2", "approved", rework=True)
        review(c, root, "S5-qa-code-critic-3", "blocked", remark_text("PR-5", "blocker", case="TC-2", test="T-2"), rework=True)
        chain = SP.reviews(root, c.state())
        check_eq("F-3 fixture: blocked, approved, blocked", [e["outcome"] for e in chain], ["blocked", "approved", "blocked"])
        text = window(c, root)
        check("F-3: the last blocker was not looked at again - the door is the author's rework and one look, not the three moves",
              "blocks the plan (PR-5)" in text and "three moves" not in text and "--purpose s5_plan" in text, text)
        check_not_in("F-3: and the text does not claim a second review of this blocker", "reviewed again after the rework", text)
    finally:
        cleanup(root)


def k15_the_review_readers_hear_the_values_file():
    """KILLS: `s5_plan._review_element` / `exit_gate._s5_plan_outputs_errors` reading the raw form (SC1-2 part D, `form_view`): a
    `review.outcome` or a `remarks` section the critic wrote only in `<dispatch>.values.yaml` was not heard."""
    import handoff_check
    root = temp_dir("qa-s5pc-fv-")
    try:
        approved(root)
        form = root / "work" / "handoffs" / "S5-qa-code-critic-1.yaml"
        text = form.read_text(encoding="utf-8")
        check("fixture: the form says `approved`", "outcome: approved" in text, text)
        form.write_text(text.replace("outcome: approved", "outcome: <approved|approved_with_remarks|blocked>"), encoding="utf-8")
        check_in("control: the raw form no longer carries a verdict", "review.outcome", SP.review_of(root, "S5-qa-code-critic-1")["unreadable"])
        handoff_check.sibling_values(form).write_text("review.outcome: approved\n", encoding="utf-8")
        element = SP.review_of(root, "S5-qa-code-critic-1")
        check_eq("form_view: the verdict written only in the waiting values file is heard", (element["outcome"], element["unreadable"]),
                 ("approved", ""))
    finally:
        cleanup(root)
    # the exit gate's reader of the same form: the one reader and the one path (no second literal of `work/handoffs/`)
    source = (SCRIPTS / "exit_gate.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    reader = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_s5_plan_outputs_errors")
    body = ast.get_source_segment(source, reader)
    check("F-5/form_view: the exit gate reads the critic's form through `form_view`", "handoff_check.form_view(" in body, body[:200])
    check("F-5: ... at the path `story_step.FORM_REL` names, not a literal of its own",
          "FORM_REL.format(" in body and "work/handoffs/" not in body.replace("`", ""), body[:200])

# --- t-1508 R2: a person's word on the rework lifts the row bound (the door of the refusal) ----------------------------------

def _rows_bound_story(root):
    """A blocked review, a rework of the author's plan that changed a row no blocker names (TC-2): the refusal of the row bound.
    Returns the controller, the rework dispatch id and the refusal text."""
    c = approved(root, "blocked", BLOCKER, NOTE)
    author = rework_author(c, root)
    plan = SP.load(root)
    plan["tests"][0]["assert"] = "TC-1 row mended"
    plan["tests"][1]["assert"] = "TC-2 row changed too"
    put(root, SP.PLAN_REL, json.dumps(plan))
    return c, author, refused(lambda: accept_it(c, root, author))


def _say(root, line):
    pipeline = json.loads((root / "pipeline.json").read_text(encoding="utf-8"))
    W.apply_stage_override(pipeline, "S5", line, "the person asked for these rows to change", W.now_iso())
    put(root, "pipeline.json", json.dumps(pipeline))


def k16_r2_a_persons_word_lifts_the_row_bound():
    """KILLS (K-R2-1..5): the refusal of the row bound with no door for a person's word (t-1508 R2, F-3 (B)); a word matched without the
    dispatch id (K-R2-3); a pass that never asks the record (K-R2-2); an unreadable record read as a pass (K-R2-5)."""
    from role_cli import REPAIR_MARKER
    root = temp_dir("qa-s5pc-r2-")
    try:
        c, author, text = _rows_bound_story(root)
        line = f"plan rows by person: {author}"
        check("K-R2-1: the refusal names the door of a person's words, by file, with the id of the dispatch",
              "--words-file" in text and f'--block "{line}"' in text and "waiver.py --task" in text and "--stage S5" in text, text)
        check("K-R2-1: ... and keeps the repair marker last, so the driver still returns it to the role",
              text.rstrip().endswith("return it to qa-automator in one message") and REPAIR_MARKER in text, text)
        old = ("which no blocker of S5-qa-code-critic-1 names and which share no test with a new or a dropped case; only the blocker "
               "rows, the new cases and the cases that share a test with a new or dropped case change, the rest of the plan stays as "
               "the critic saw it")
        end = f". {REPAIR_MARKER}: return it to qa-automator in one message"
        stripped = re.sub(r"\. If a person asked for these rows to change.*?is not bound either", "", text, flags=re.S)
        check("K-R2-4: without the new sentence the refusal is the old one, byte for byte up to the repair marker",
              stripped.endswith(old + end) and stripped != text, stripped)
        check("K-R2-3: the door names the word with the id as it stands (no `;`: the id is compared for equality)",
              f'--block "plan rows by person: {author}"' in text and f"{author};" not in text, text)
        _say(root, "plan rows by person: " + author + "0")        # the word for another dispatch (a longer id)
        check_in("K-R2-3: a word for another dispatch does not pass this one",
                 "which no blocker of", refused(lambda: accept_it(c, root, author)))
        _say(root, "plan rows by person: *")
        check_in("K-R2-3: a `*` word passes no dispatch (the stage has no wildcard here)",
                 "which no blocker of", refused(lambda: accept_it(c, root, author)))
        _say(root, line)
        check_eq("K-R2-2: after the word for THIS dispatch, the same accept goes through", refused(lambda: accept_it(c, root, author)), "")
    finally:
        cleanup(root)
    root = temp_dir("qa-s5pc-r2b-")
    try:
        c, author, text = _rows_bound_story(root)
        _say(root, f"plan rows by person: {author}")
        pipeline = json.loads((root / "pipeline.json").read_text(encoding="utf-8"))
        check_eq("K-R2-3: the one reader hears the word for this dispatch and for no longer neighbour (equality, not substring)",
                 [v for v, _ in CC.stage_override_values(pipeline, "plan rows by person:")], [author])
        _say(root, f"plan rows by person: {author}0")
        _say(root, "plan rows by person: *")
        pipeline = json.loads((root / "pipeline.json").read_text(encoding="utf-8"))
        check_eq("K-R2-3: ... and a `*` word is a value no dispatch id equals",
                 [v for v, _ in CC.stage_override_values(pipeline, "plan rows by person:") if v == author], [author])
        state = c.state()
        check_eq("K-R2-3: ... so with the neighbour's and the `*` words on file, this dispatch's own word still lifts the bound",
                 c._s5_plan_accept_problems(state["dispatches"][author], {}, state), [])
        put(root, "pipeline.json", "{broken")
        check_in("K-R2-5: a record that cannot be read leaves the refusal standing (FR-59)", "which no blocker of", refused(lambda: accept_it(c, root, author)))
    finally:
        cleanup(root)
    root = temp_dir("qa-s5pc-r2c-")
    try:
        c = approved(root, "blocked", BLOCKER, NOTE)
        request = c.build_rework_request("S5", AUTHOR, list(CASES), "the person asked for these rows to change", purpose=CT.S5_PLAN,
                                         words_given=True)
        c.apply("dispatch", request)
        plan = SP.load(root)
        plan["tests"][1]["assert"] = "TC-2 row changed too"
        put(root, SP.PLAN_REL, json.dumps(plan))
        check_eq("K-R2-S0: a rework built with `--words-file` is not bound (as before), the door text is not needed",
                 refused(lambda: accept_it(c, root, request["id"])), "")
    finally:
        cleanup(root)


def k17_r2_seam_the_live_run_state():
    """KILLS (K-R2-S, spec t-1508 5.2 and 3a): the refusal of the row bound read on the REAL state of TP1-12586 at 12:10:29 (the
    events up to the dispatch `S5-qa-automator-5`, its plan, the critic's forms; `fixtures/run-12586-red-then/controller/README.txt`):
    the refusal names the door with the dispatch id, and after the person's word the same accept holds no row problem."""
    import shutil
    from role_cli import REPAIR_MARKER
    src = Path(__file__).resolve().parent / "fixtures" / "run-12586-red-then" / "controller" / "TP1-12586"
    root = temp_dir("qa-s5pc-seam-") / "TP1-12586"
    try:
        shutil.copytree(src, root)
        c = CT.Controller(root)
        state = c.state()
        d = state["dispatches"]["S5-qa-automator-5"]
        check_eq("K-R2-S: the live dispatch is the author's open plan rework", (d.get("purpose"), d.get("rework_of"), d.get("status")),
                 ("s5_plan", "S5-qa-automator-1", "running"))
        got = c._s5_plan_accept_problems(d, {}, state)
        text = " ".join(str(m) for _, m in got)
        check("K-R2-S: the live state is refused for the row bound, with the door of a person's word for THIS dispatch",
              "which no blocker of" in text and 'waiver.py --task TP1-12586 --stage S5 --block "plan rows by person: S5-qa-automator-5"' in text
              and REPAIR_MARKER in text, text)
        pipeline = json.loads((root / "pipeline.json").read_text(encoding="utf-8"))
        W.apply_stage_override(pipeline, "S5", "plan rows by person: S5-qa-automator-5", "the person asked for these rows to change", W.now_iso())
        put(root, "pipeline.json", json.dumps(pipeline))
        check_eq("K-R2-S: after the word the same accept holds no row problem", c._s5_plan_accept_problems(d, {}, c.state()), [])
        pass_log = (root / "state" / "passed-by-person.jsonl").read_text(encoding="utf-8")
        check_in("K-R2-S: ... and the pass is on record", "plan rows by person: S5-qa-automator-5", pass_log)
    finally:
        cleanup(root.parent)


def main():
    for name, fn in sorted(globals().items()):
        if name.startswith("k") and name[1:2].isdigit() and callable(fn):
            fn()
    finish("test_s5_plan_controller")


if __name__ == "__main__":
    main()
