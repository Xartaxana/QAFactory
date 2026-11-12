#!/usr/bin/env python3
"""SC1-14 FJ-C: the gates of a grown window (12) and (13), the one rule for the rows of a plan rework, the scope of a narrow plan look.

A window is its author's chain; a case added after the plan review whose test reaches a written window grows it (`grown`). (12)
`Controller._grown_window_problems` holds an author dispatch that lacks the new case and a critic dispatch over the grown window;
(13) `Controller._grown_close_problems` keeps S5 open until both roles have covered all of W'; `_plan_rework_rows_problems` lets a plan
rework change the blocker rows, the new cases and their test neighbours; `_plan_look_missed` refuses a narrow look that
misses a moved row (a person's words lift it, and its door names the whole set the look must cover). Every key names the mutation it kills (spec t-1314 section 5, FJ-C: MJ26-MJ30, MJ34, MJ37-MJ40, MJ47, MJ48).
"""
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import SCRIPTS, check, check_eq, check_in, check_not_in, cleanup, finish, temp_dir  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import controller as CT  # noqa: E402
import s5_plan as SP  # noqa: E402
import waiver as W  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_controller_rework_scope import evidence  # noqa: E402
from test_s5_plan import put, s5_story  # noqa: E402
from test_s5_plan_check import remark_text, test_row, write_form  # noqa: E402
from test_s5_plan_controller import accept_it, probe, refused, send  # noqa: E402
from test_s5_plan_windows import planned_story, set_tests, write_window  # noqa: E402
os.environ.pop("QA_FACTORY_RUN_MODE", None)
AUTHOR, CRITIC = "qa-automator", "qa-code-critic"
CASES4 = ("TC-1", "TC-2", "TC-3", "TC-4")
TRIO = ("TC-1", "TC-2", "TC-3")
WORD = "plan before windows"


def req(role, scope, **extra):
    return dict({"id": "S5-x-9", "stage": "S5", "role": role, "scope": list(scope)}, **extra)


def grown_story(root):
    """Window 1 (TC-1, TC-2) written and reviewed; then the plan grows: TC-3's test reaches it. Window 2 is TC-4's, unwritten."""
    c = planned_story(root, CASES4, [["TC-1", "TC-2"], ["TC-3"], ["TC-4"]], config=(2, 2))
    write_window(c, root, "S5-qa-automator-1", ["TC-1", "TC-2"])
    write_window(c, root, "S5-qa-code-critic-1", ["TC-1", "TC-2"], role=CRITIC)
    set_tests(root, [["TC-1", "TC-2", "TC-3"], ["TC-4"]])
    return c


def accept_open(c, root, ident):
    c.apply("accept", {"id": ident, "status": "accepted", "stage_complete": False, "unresolved": True, "reason": "the repair round is open",
                       "evidence_refs": [evidence(root, ident + ".txt")], "idempotency_key": ident + "-ok"})


def close(c, root, ident, **extra):
    return refused(lambda: c.apply("accept", dict({"id": ident, "status": "accepted", "stage_complete": True,
                                                   "evidence_refs": [evidence(root, ident + ".txt")], "idempotency_key": ident + "-close"}, **extra)))


def word(root):
    pipeline = json.loads((root / "pipeline.json").read_text(encoding="utf-8"))
    W.apply_stage_override(pipeline, "S5", WORD, "go on with this window", W.now_iso())
    put(root, "pipeline.json", json.dumps(pipeline))


def k1_gate_12():
    root = temp_dir("qa-fjc-12-")
    try:
        c = grown_story(root)
        cut = c.stage_scope("S5")
        check_eq("fixture: window 1 grew by TC-3", (cut["windows"][0]["scope"], cut["windows"][0]["grown"]), (["TC-1", "TC-2", "TC-3"], ["TC-3"]))
        text = probe(c, req(AUTHOR, ["TC-1", "TC-2"], rework_of="S5-qa-automator-1"))
        check_in("a rework of a grown window without its new case is refused", "window 1 grew after the plan review by TC-3", text)
        check_in("a rework of a grown window without its new case is refused: its author reworks it with them first", "its author reworks it with them first", text)
        check_in("(12) names the test", "T-1", text)
        check_in("(12) door: the exact rework command, all of W', cause ticket_changed", "--cases TC-1,TC-2,TC-3 --cause ticket_changed", text)
        check_in("(12) the word that passes it", WORD, text)
        critic = probe(c, req(CRITIC, ["TC-1", "TC-2", "TC-3"], rework_of="S5-qa-code-critic-1"))
        check_in("a critic dispatch over a grown window waits for its author", "the critic of window 1 waits for its author to cover TC-3", critic)
        check_in("a critic dispatch over the grown window, even its old scope, waits", "waits for its author",
                 probe(c, req(CRITIC, ["TC-1", "TC-2"], rework_of="S5-qa-code-critic-1")))
        check_not_in("a critic of another window is not held", "waits for its author", probe(c, req(CRITIC, ["TC-4"])))
        check_in("a fresh window with the new case alone is refused (it splits the test)", "splits the cases of test(s) T-1",
                 probe(c, req(AUTHOR, ["TC-3"])))
        l1 = probe(c, req(AUTHOR, ["TC-1", "TC-2", "TC-3"]))
        check_in("L1: a fresh author dispatch over a written window is refused", "window 1 is written (TC-1, TC-2, TC-3) and a window is its author's chain", l1)
        check_in("L1: the door is the rework of that window", "--operation rework --stage S5 --role qa-automator --cases TC-1,TC-2,TC-3", l1)
        check_in("L1: the word that passes it", WORD, l1)
        check_in("L1: a fresh dispatch over part of a written window is refused too", "is its author's chain",
                 probe(c, req(AUTHOR, ["TC-1", "TC-2"])))
        check_eq("L1: a fresh author dispatch over cases of no written window passes", probe(c, req(AUTHOR, ["TC-4"])), "")
        check_not_in("L1: a retry of the window is not a fresh dispatch", "is its author's chain",
                     probe(c, req(AUTHOR, ["TC-1", "TC-2", "TC-3"], parent_retry="S5-qa-automator-1")))
        check_not_in("L1: a relaunch of the window is not a fresh dispatch", "is its author's chain",
                     probe(c, req(AUTHOR, ["TC-1", "TC-2", "TC-3"], relaunch_of="S5-qa-automator-1")))
        check_not_in("L1: a person's-words dispatch passes", "is its author's chain",
                     probe(c, req(AUTHOR, ["TC-1", "TC-2", "TC-3"], person_words=True)))
        check_eq("a grown window rework with all its cases passes", probe(c, req(AUTHOR, ["TC-1", "TC-2", "TC-3"], rework_of="S5-qa-automator-1")), "")
        check_not_in("a person's-words rework is not held by (12)", "grew after the plan review",
                     probe(c, req(AUTHOR, ["TC-1", "TC-2"], rework_of="S5-qa-automator-1", person_words=True)))
        check_not_in("a person's-words critic is not held by (12)", "waits for its author",
                     probe(c, req(CRITIC, ["TC-1", "TC-2", "TC-3"], person_words=True)))
        # the grown rework: the cause comes from the door, and it spends no cap
        cause = re.search(r"--cause (\w+)", text).group(1)
        request = c.build_rework_request("S5", AUTHOR, ["TC-1", "TC-2", "TC-3"], "case TC-3 added to S5 after the plan review", cause=cause)
        c.apply("dispatch", request)
        ledger = CT.repair_ledger(c.state()["dispatches"], request)
        check_eq("the grown window rework spends no window cap", (ledger["counted"], ledger["by_cause"]), (0, {"ticket_changed": 1}))
        check_eq("grown clears once the rework is dispatched", c.stage_scope("S5")["window_cut"]["grown"], [])
        check_eq("after the grown rework, a narrow rework of the window passes", probe(c, req(AUTHOR, ["TC-1"], rework_of=request["id"])), "")
        check_not_in("after the grown rework the critic over W' is no longer held", "waits for its author",
                     probe(c, req(CRITIC, ["TC-1", "TC-2", "TC-3"], rework_of="S5-qa-code-critic-1")))
    finally:
        cleanup(root)
    root = temp_dir("qa-fjc-12w-")
    try:
        c = grown_story(root)
        word(root)
        check_not_in("a person's word passes a grown window", "grew after the plan review",
                     probe(c, req(AUTHOR, ["TC-1", "TC-2"], rework_of="S5-qa-automator-1")))
        check_not_in("L1: a person's word passes a fresh dispatch over a written window", "is its author's chain",
                     probe(c, req(AUTHOR, ["TC-1", "TC-2", "TC-3"])))
    finally:
        cleanup(root)


def k2_gate_13():
    root = temp_dir("qa-fjc-13a-")
    try:
        c = grown_story(root)
        send(c, root, "S5-qa-code-critic-2", CRITIC, scope=["TC-4"])
        text = close(c, root, "S5-qa-code-critic-2")
        check_in("S5 does not close while the grown window's author has not covered it", "S5 cannot close: window 1 grew after the plan review by TC-3", text)
        check_in("(13) names both roles when neither covered it", "its author and its critic have not covered all of", text)
    finally:
        cleanup(root)
    for name, rework in (("13a2", False), ("13a3", True)):
        root = temp_dir(f"qa-fjc-{name}-")
        try:
            c = grown_story(root)
            send(c, root, "S5-qa-code-critic-3", CRITIC, scope=["TC-1", "TC-2", "TC-3"], person_words=True)
            accept_open(c, root, "S5-qa-code-critic-3")
            if rework:
                request = c.build_rework_request("S5", AUTHOR, ["TC-1", "TC-2", "TC-3"], "case TC-3 added", cause="ticket_changed")
                c.apply("dispatch", request)
                accept_open(c, root, request["id"])
            send(c, root, "S5-qa-code-critic-2", CRITIC, scope=["TC-4"])
            text = close(c, root, "S5-qa-code-critic-2")
            if rework:
                check_not_in("both roles covered W': (13) lets the close go on to the old checks", "grew after the plan review", text)
            else:
                check("S5 does not close while the grown window's author has not covered it: a critic alone is not enough",
                      "its author has not covered" in text and "its critic" not in text, text)
        finally:
            cleanup(root)
    root = temp_dir("qa-fjc-13b-")
    try:
        c = grown_story(root)
        request = c.build_rework_request("S5", AUTHOR, ["TC-1", "TC-2", "TC-3"], "case TC-3 added", cause="ticket_changed")
        c.apply("dispatch", request)
        accept_open(c, root, request["id"])
        send(c, root, "S5-qa-code-critic-2", CRITIC, scope=["TC-4"])
        text = close(c, root, "S5-qa-code-critic-2")
        check("S5 does not close while the grown window's critic has not reviewed it",
              "its critic has not covered all of TC-1, TC-2, TC-3" in text and "its author" not in text, text)
        check_in("(13) door for the critic: an accepted critic meets the window, so it is reworked", "--operation rework --stage S5 --role qa-code-critic --cases TC-1,TC-2,TC-3", text)
        check_not_in("(13) door for the critic: ... and no fresh critic is started", "story_step.py start", text)
        word(root)
        check_not_in("a person's word passes (13)", "S5 cannot close", close(c, root, "S5-qa-code-critic-2"))
    finally:
        cleanup(root)
    root = temp_dir("qa-fjc-13d-")
    try:
        c = planned_story(root, CASES4, [["TC-1", "TC-2"], ["TC-3"], ["TC-4"]], config=(2, 2))
        write_window(c, root, "S5-qa-automator-1", ["TC-1", "TC-2"])
        set_tests(root, [["TC-1", "TC-2", "TC-3"], ["TC-4"]])
        request = c.build_rework_request("S5", AUTHOR, ["TC-1", "TC-2", "TC-3"], "case TC-3 added", cause="ticket_changed")
        c.apply("dispatch", request)
        accept_open(c, root, request["id"])
        send(c, root, "S5-qa-code-critic-2", CRITIC, scope=["TC-4"])
        text = close(c, root, "S5-qa-code-critic-2")
        check_in("(13) door for the critic: none ran, a fresh critic is started", "story_step.py start", text)
        check("(13) door for the critic: none ran, so nothing is reworked", "--role qa-code-critic --cases" not in text, text)
    finally:
        cleanup(root)
    root = temp_dir("qa-fjc-13m4-")
    try:
        c = grown_story(root)
        send(c, root, "S5-qa-code-critic-2", CRITIC, scope=["TC-4"])

        def broken(*_args, **_kwargs):
            raise ValueError("the plan cut failed")
        c.s5_windows_for = broken
        try:
            c._grown_cut(c.state())
            raised = False
        except ValueError:
            raised = True
        check("a cut that fails is not replaced by the cut by cases: the grown cut raises (M4)", raised)
        text = close(c, root, "S5-qa-code-critic-2")
        check_in("a cut that fails: (13) refuses with the reason, never counts it as nothing grown (M4)",
                 "whether a window of S5 grew after the plan review cannot be established (the plan cut failed)", text)
        check_eq("a cut that fails: (12) asks nothing", probe(c, req(CRITIC, ["TC-1", "TC-2", "TC-3"], rework_of="S5-qa-code-critic-1")) .count("waits for its author"), 0)
    finally:
        cleanup(root)
    root = temp_dir("qa-fjc-13c-")
    try:
        c = planned_story(root, CASES4, [["TC-1", "TC-2"], ["TC-3"], ["TC-4"]], config=(2, 2))
        write_window(c, root, "S5-qa-automator-1", ["TC-1", "TC-2"])
        send(c, root, "S5-qa-code-critic-2", CRITIC, scope=["TC-4"])
        text = close(c, root, "S5-qa-code-critic-2")
        check_not_in("a window that did not grow is accepted as before", "S5 cannot close", text)
        check_in("a window that did not grow is accepted as before: the old checks speak", "window acceptance record", text)
    finally:
        cleanup(root)


def three_case_story(root, stamped, current, outcome="approved", *remarks):
    """A story of TRIO with the author's plan accepted, the critic's review stamped on `stamped` and `current` on disk after it."""
    c = s5_story(root, cases=TRIO, with_case_files=True)
    put(root, "qa-factory/config.json", json.dumps({"dispatch": {"api_window_cases": 4}}))
    send(c, root, "S5-qa-automator-1", AUTHOR, scope=TRIO, purpose=CT.S5_PLAN)
    plan = SP.init(root, c)
    rows = {row["case"]: row for row in plan["cases"]}

    def plan_with(groups):
        out = json.loads(json.dumps(plan))
        kept = {case for group in groups for case in group}
        out["cases"] = [row for row in out["cases"] if row["case"] in kept]
        out["tests"] = [test_row(f"T-{n}", g, [f"{case}#{t['n']}" for case in g for t in rows[case]["thens"]]) for n, g in enumerate(groups, 1)]
        return out
    full, reduced = plan_with([["TC-1", "TC-3"], ["TC-2"]]), plan_with([["TC-1"], ["TC-2"]])
    plans = {"full": full, "reduced": reduced}
    put(root, SP.PLAN_REL, json.dumps(full))
    accept_it(c, root, "S5-qa-automator-1")
    send(c, root, "S5-qa-code-critic-1", CRITIC, scope=TRIO, purpose=CT.S5_PLAN)
    write_form(root, "S5-qa-code-critic-1", outcome, *remarks)
    put(root, SP.PLAN_REL, json.dumps(plans[stamped]))
    SP.stamp_review(root, "S5-qa-code-critic-1")
    accept_it(c, root, "S5-qa-code-critic-1")
    put(root, SP.PLAN_REL, json.dumps(plans[current]))
    return c, plans


def k3_rows():
    root = temp_dir("qa-fjc-rows1-")
    try:
        c, plans = three_case_story(root, "reduced", "full")
        request = c.build_rework_request("S5", AUTHOR, list(TRIO), "TC-3 is new", purpose=CT.S5_PLAN)
        c.apply("dispatch", request)
        chain = SP.reviews(root, c.state())
        changed, new = SP.moved_cases(plans["full"], chain[-1]["rows_sha"])
        check_eq("fixture: TC-1's row moved with the new case's test, TC-3 is new", (changed, new), ({"TC-1"}, {"TC-3"}))
        check_eq("a plan rework for new cases may change the rows that share a test with them", c._plan_rework_rows_problems(c.state(), "."), [])
        mended = json.loads(json.dumps(plans["full"]))
        mended["tests"][1]["assert"] = "TC-2 changed too"
        put(root, SP.PLAN_REL, json.dumps(mended))
        text = refused(lambda: accept_it(c, root, request["id"]))
        check("a plan rework for new cases ... but not other rows", "TC-2" in text and "share no test with a new or a dropped case" in text
              and "TC-1," not in text, text)
        put(root, SP.PLAN_REL, json.dumps(plans["full"]))
        check_eq("a plan rework for new cases is accepted through the accept", refused(lambda: accept_it(c, root, request["id"])), "")
    finally:
        cleanup(root)
    root = temp_dir("qa-fjc-rows2-")
    try:
        c, plans = three_case_story(root, "full", "reduced")
        chain = SP.reviews(root, c.state())
        check_eq("fixture: TC-3 is gone, TC-1's row moved", (SP.moved_cases(plans["reduced"], chain[-1]["rows_sha"])), ({"TC-1"}, set()))
        check_eq("a plan rework that drops a case may change its test neighbours (the receipt's map)",
                 c._plan_rework_rows_problems(c.state(), "."), [])
        receipt = json.loads((root / SP.REVIEWS_REL).read_text(encoding="utf-8"))
        for line in receipt:
            line.pop("tests", None)
        put(root, SP.REVIEWS_REL, json.dumps(receipt))
        text = " ".join(str(p[1]) for p in c._plan_rework_rows_problems(c.state(), "."))
        check("a receipt with no tests map reads the neighbours by the new plan alone, and says so",
              "TC-1" in text and "keeps no tests map" in text, text)
    finally:
        cleanup(root)
    root = temp_dir("qa-fjc-rows3-")
    try:
        c, plans = three_case_story(root, "reduced", "full", "blocked", remark_text("PR-1", "blocker", case="TC-2"))
        mended = json.loads(json.dumps(plans["full"]))
        mended["tests"][1]["assert"] = "TC-2 mended"
        put(root, SP.PLAN_REL, json.dumps(mended))
        check_eq("after a blocker, the blocker rows and the new cases' neighbours may change", c._plan_rework_rows_problems(c.state(), "."), [])
    finally:
        cleanup(root)


def k4_look_scope():
    root = temp_dir("qa-fjc-look-")
    try:
        c, plans = three_case_story(root, "reduced", "full")
        check_in("a window rework before the narrow plan look is refused (plan changed after review)", "changed after its last accepted review",
                 probe(c, req(AUTHOR, ["TC-1"])))
        look = c.build_rework_request("S5", CRITIC, list(TRIO), "look at the new case", purpose=CT.S5_PLAN)
        c.apply("dispatch", look)
        write_form(root, look["id"], "approved")
        SP.stamp_review(root, look["id"])
        record, state = c.state()["dispatches"][look["id"]], c.state()
        narrow = " ".join(str(p[1]) for p in c._plan_review_problems(dict(record, scope=["TC-3"]), state, "."))
        check("a narrow look whose cases miss a changed row is refused",
              "the look scoped TC-3 but rows of TC-1 changed since S5-qa-code-critic-1" in narrow
              and "the stamp would cover rows nobody looked at" in narrow, narrow)
        check_in("the look refusal's door is the critic's rework over ALL the rows the look must cover (B2)",
                 "--role qa-code-critic --purpose s5_plan --cases TC-1,TC-3 --reason", narrow)
        check_eq("a look that covers the moved rows passes", c._plan_review_problems(dict(record, scope=["TC-1", "TC-3"]), state, "."), [])
        door = re.search(r"--purpose s5_plan --cases (\S+) --reason", narrow).group(1).split(",")
        check_eq("following the door once passes the look (B2)", c._plan_review_problems(dict(record, scope=door), state, "."), [])
        check_in("the look refusal names the word that passes it", WORD, narrow)
        passed = root / "state" / "passed-by-person.jsonl"
        check("fixture: no pass is recorded before a person's word", not passed.exists() or "the look scoped" not in passed.read_text(encoding="utf-8"))
        check_eq("a person's-words look is not held for its scope (P13)",
                 c._plan_review_problems(dict(record, scope=["TC-3"], person_words=True), state, "."), [])
        check_in("a person's-words look: the pass is recorded as a finding", "the look scoped TC-3", passed.read_text(encoding="utf-8"))
        passed.unlink()
        word(root)
        check_eq("a person's word passes the narrow look", c._plan_review_problems(dict(record, scope=["TC-3"]), c.state(), "."), [])
        check_in("a person's word passes the narrow look: the pass is recorded as a finding", "the look scoped TC-3", passed.read_text(encoding="utf-8"))
        check_eq("the full look is accepted", refused(lambda: accept_it(c, root, look["id"])), "")
    finally:
        cleanup(root)
    root = temp_dir("qa-fjc-look2-")
    try:
        c, plans = three_case_story(root, "reduced", "full")
        look = c.build_rework_request("S5", CRITIC, list(TRIO), "look at the new case", purpose=CT.S5_PLAN)
        c.apply("dispatch", look)
        write_form(root, look["id"], "approved")
        SP.stamp_review(root, look["id"])
        receipts = json.loads((root / SP.REVIEWS_REL).read_text(encoding="utf-8"))
        put(root, SP.REVIEWS_REL, json.dumps([line for line in receipts if line.get("dispatch") != "S5-qa-code-critic-1"]))
        record, state = c.state()["dispatches"][look["id"]], c.state()
        check("fixture: the previous review cannot be read", SP.reviews(root, state)[0]["unreadable"], str(SP.reviews(root, state)))
        narrow = " ".join(str(p[1]) for p in c._plan_review_problems(dict(record, scope=["TC-3"]), state, "."))
        check("an unreadable previous review does not skip the narrow look: a full look is asked (M5)",
              "S5-qa-code-critic-1 cannot be read" in narrow and "--cases TC-1,TC-2,TC-3 --reason" in narrow, narrow)
        check_eq("an unreadable previous review: a look over the whole plan passes",
                 [p for p in c._plan_review_problems(dict(record, scope=list(TRIO)), state, ".") if "the look scoped" in str(p[1])], [])
    finally:
        cleanup(root)


def main():
    k1_gate_12()
    k2_gate_13()
    k3_rows()
    k4_look_scope()
    finish("test_s5_grown_windows")


if __name__ == "__main__":
    main()
