#!/usr/bin/env python3
"""The report counts what the run checked by hand, and says its gaps in ONE form (HF8-17, run 12586, owner 29.10.2026).

On 12586 three manual checks passed with screenshots, yet the appendix read `not run` and "Not proven" gave the plan's own reason
(the plan said `e2e-ui`, the check was done by hand); "Open questions" said 0 while "Left with you" carried four; "Where to look"
listed the plan's sections twelve times; the case-appendix marker stood inside the regression block (and looped S9); the regression
commands named this machine; the verdict counted the factory's own bookkeeping among the requirements not proven.

Keys (the spec's, `r0107-s5b-hf8-19-22.md` N4): M1 a manual-agent case reads what its valid record says, whatever the plan's `level`
column says (and `manual-human` waits); M8 a failed manual check is not `pass`, not `wait`; M2 Open questions counts what the
person is asked under "Left with you"; M3 every section once; M4 the appendix marker ends the regression section; M5 no path of this
machine in a regression command; M6 the ONE form of a gap line (E17) and the whole-word name check; M7 the verdict splits the
factory's bookkeeping off the not-proven count and changes no word; I the integrations the cases could not be tied to.

Run on its own: `python -B scripts/tests/test_report_manual_counted.py`.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness import (FIXTURES, check, check_eq, check_in, check_not_in, cleanup,  # noqa: E402
                     finish, temp_dir)

import check_delivery as CD  # noqa: E402
import delivery_verdict as DV  # noqa: E402
import gate_preflight as GP  # noqa: E402
import render_case_appendix as RCA  # noqa: E402
import report_facts as RF  # noqa: E402
import traceability as T  # noqa: E402


class _Story(T.Story):
    """A story that knows one case, its plan row and what its manual record says: the real `case_outcome`, `level_for`,
    `plan_row_for`, `confirmed_bug_of` and `manual_outcome` over typed rows, no files."""

    def __init__(self, level="", disposition="", entry=None, bugs=(), unresolved=None, manifest=None):
        self.artifacts = Path("no-such-story")
        self.manifest = manifest or {}
        self.plan_rows = [{"ts": "TS-1", "disposition": disposition, "reason": "not deterministic on the stand"}]
        self.plan_by_ts = {"TS-1": self.plan_rows[0]}
        self.cases = {"TC-001": {"plan_row": "TS-1"}}
        self.case_levels = {"TC-001": level} if level else {}
        self.bugs = list(bugs)
        self.unresolved_by_case = unresolved or {}
        self._manual_cases = {"TC-001": entry} if entry else {}
        self._open_oracles = {}


class _Index(dict):
    """The case index the report reads: a dict of case metadata that can also say which key names a case id."""

    def matching(self, case):
        return [k for k in self if k == case]


PASSED = {"case": "TC-001", "state": "checked", "result": RF.RESULT_WORDS["pass"], "actual": "cancelled after the click",
          "links": {"post_action": ["evidence/" + "ab" * 32 + ".png"]}}
FAILED = dict(PASSED, result=RF.RESULT_WORDS["fail"], actual="the page still read active")
UNSURE = dict(PASSED, result=RF.RESULT_WORDS["inconclusive"], actual="the banner never loaded")


def m1_manual_counted() -> None:
    got = _Story("e2e-ui", "manual-agent", PASSED).case_outcome("TC-001", "R-1")
    check_eq("M1 a valid passed manual record on a row whose level column says e2e-ui reads `pass`", got["result"], "pass")
    check_eq("M1 ... at the level of the record, not of the plan's column", got["level"], "manual-agent")
    check_in("M1 ... with the check's own words as the basis", "checked by hand:", got["basis"])
    check_not_in("M1 ... and not the plan's reason (the run disproved it)", "not deterministic", got["basis"])
    check_eq("M1 the requirement it proves is `proven`, not `unproven`", RF._classify([got["result"]]), "proven")
    again = _Story("", "manual-agent", PASSED).case_outcome("TC-001", "R-1")
    check_eq("M1 control: the same case with an empty level column read `pass` before and still does", again["result"], "pass")
    # an invalid / absent record keeps the plan's reading (FR-18): the branch is not reached
    none = _Story("e2e-ui", "manual-agent", None).case_outcome("TC-001", "R-1")
    check_eq("M1 no valid record: `not run` with the plan's reason, as before", (none["result"], "not deterministic" in none["basis"]),
             ("not run", True))
    # position: a confirmed bug of the requirement is above the manual reading (I2), and a live test is below nothing
    bug = {"id": "BUG-1", "state": "confirmed", "requirements": ["R-1"], "title": "Cancel keeps charging", "cases": [], "filed": True}
    over = _Story("e2e-ui", "manual-agent", PASSED, bugs=[bug]).case_outcome("TC-001", "R-1")
    check_eq("M1 a confirmed bug of the requirement stays above a passed manual check", (over["result"], over["bug"]), ("bug", "BUG-1"))
    # the neighbour: a row that says e2e-ui and is planned for a person waits for that person (was `not run`)
    human = _Story("e2e-ui", "manual-human").case_outcome("TC-001", "R-1")
    check_eq("M1 e2e-ui + manual-human reads `wait`, not `not run`", (human["result"], human["level"]), ("wait", "manual-human"))
    plain = _Story("api", "automate").case_outcome("TC-001", "R-1")
    check_eq("M1 control: a plain automated row with no result reads `not run` at its level", (plain["result"], plain["level"]),
             ("not run", "api"))
    inconclusive = _Story("e2e-ui", "manual-agent", UNSURE).case_outcome("TC-001", "R-1")
    check_eq("M1 an inconclusive record waits (it counts toward nothing)", inconclusive["result"], "wait")
    # t-442 (canon part D), position (I2): the case's OWN live instance is above the manual reading. A case the plan disposes to
    # `manual-agent` that also has a live test the run never ran reads what that test says (`not run`), never the manual `pass`.
    entry = {"instance_id": "inst-1", "covers": ["TC-001"], "status": "written", "file": "tests/test_cancel.py"}
    live = _Story("e2e-ui", "manual-agent", PASSED, manifest={"tests": [entry]})
    live.instances = {"inst-1": entry}
    live.results, live.report = [], {}
    own = live.case_outcome("TC-001", "R-1")
    check_eq("M1 (I2) a live instance of the case beside a passed manual record: the instance's reading, not `pass`",
             (own["result"], [t["instance_id"] for t in own["tests"]]), ("not run", ["inst-1"]))
    check_not_in("M1 (I2) ... and not the manual check's words", "checked by hand", own["basis"])
    other = dict(entry, covers=["TC-009"])
    gone = _Story("e2e-ui", "manual-agent", PASSED, manifest={"tests": [other]})
    gone.instances, gone.results, gone.report = {"inst-1": other}, [], {}
    again = gone.case_outcome("TC-001", "R-1")
    check_eq("M1 (I2) control: the only live test covers ANOTHER case, so the manual record is read again",
             (again["result"], again["level"]), ("pass", "manual-agent"))


def m8_manual_failed() -> None:
    got = _Story("e2e-ui", "manual-agent", FAILED).case_outcome("TC-001", "R-1")
    check_eq("M8 a failed manual check is `blocked`: not `pass`, not `wait`", got["result"], "blocked")
    check_eq("M8 ... says it failed, in its own words", got["basis"], "checked by hand, failed: the page still read active")
    check_eq("M8 ... and the requirement is not proven", RF._classify([got["result"]]), "unproven")
    bug = {"id": "BUG-2", "state": "confirmed", "requirements": ["R-1"], "title": "x", "cases": [], "filed": True}
    check_eq("M8 a confirmed bug of the requirement is still above it",
             _Story("e2e-ui", "manual-agent", FAILED, bugs=[bug]).case_outcome("TC-001", "R-1")["result"], "bug")
    index = _Index({"TC-001": {"plan_row": "TS-1"}})
    for result, listed in (("blocked", []), ("wait", ["TC-001"])):
        facts = RF._cases({"items": []}, {"rows": [{"case": "TC-001", "result": result, "requirement": "R-1"}]}, index,
                          [{"ts": "TS-1", "disposition": "manual-agent"}], {}, {}, unconfirmed=[])
        check_eq(f"M8 `{result}` row: the case is {'' if listed else 'not '}in the list of cases a person must check",
                 facts["to_check"], listed)


def m10_manual_vs_table() -> None:
    """RD1-18: a case the block counts as passed, read otherwise by the table, is a line naming both - and only then."""
    def facts_of(read, case=None):
        return {"manual": {"checked": 1, "total": 1, "note": "", "cases": [dict(PASSED, **(case or {}), refused=False, left_line="",
                                                                              then="x", before="", shots=RF._manual_shots(Path("no-such-story"), None), quotes="", rejudged="",
                                                                              why="", plan_row="TS-1", requirements=["R-1"])],
                           "table_rows": {"TC-001": read}},
                "unknown": {}}
    agree = facts_of([{"result": "pass", "held": False}])
    check_eq("M10 agreeing: no line", RF._manual_vs_table(agree), [])
    split = facts_of([{"result": "not run", "held": False}])
    split["manual"]["vs_table"] = RF._manual_vs_table(split)          # what `build` stores; the render only appends
    import contextlib
    import io
    said = io.StringIO()
    with contextlib.redirect_stderr(said):
        RF._r_manual_checks(split)
        RF._r_manual_checks(split)
    check_eq("t-593 F-6 the render prints nothing, however many times it runs (the line is said once, at `build`)", said.getvalue(), "")
    shown, kept = io.StringIO(), RF._manual_vs_table
    RF._manual_vs_table = lambda facts: ["The table reads TC-001 as not run; the check says pass"]
    try:
        with contextlib.redirect_stderr(shown):
            built = RF.build(FIXTURES / "after-checks")
    finally:
        RF._manual_vs_table = kept
    check_eq("t-593 F-6 `build` says the line once on stderr and keeps it for the block",
             (shown.getvalue().count("report: The table reads TC-001 as not run"), (built.get("manual") or {}).get("vs_table")),
             (1, ["The table reads TC-001 as not run; the check says pass"]))
    check_eq("M10 the table reads not run while the check says pass: one line naming both",
             RF._manual_vs_table(split), ["The table reads TC-001 as not run; the check says pass"])
    check_in("M10 ... and the block carries it", "The table reads TC-001 as not run; the check says pass", RF._r_manual_checks(split))
    check_eq("M10 agreeing: the block is byte for byte the block without the key",
             RF._r_manual_checks(agree), RF._r_manual_checks({"manual": dict(agree["manual"], table_rows={}), "unknown": {}}))
    check_eq("M10 a live test, an unresolved row or a bug on the case: excluded, no line",
             RF._manual_vs_table(facts_of([{"result": "bug", "held": True}])), [])
    check_eq("M10 a record that does not stand (state not checked): nothing to compare",
             RF._manual_vs_table(facts_of([{"result": "not run", "held": False}], {"state": "not_checked"})), [])
    check_eq("M10 a failed record is not a `pass` claim: no line",
             RF._manual_vs_table(facts_of([{"result": "blocked", "held": False}], FAILED)), [])
    check_eq("M10 no manual block at all: no line", RF._manual_vs_table({"manual": None}), [])


def _ledger(items=(), records=()):
    return {"items": list(items), "records": list(records)}


def m2_open_questions() -> None:
    root = temp_dir("qa-manual-m2-")
    try:
        (root / "work").mkdir(parents=True)
        (root / "work" / "question-register.json").write_text(json.dumps({"questions": []}), encoding="utf-8")
        asked = {"counts": True, "source": "ledger", "ref": "TC-008"}
        gate = {"counts": True, "source": "gate_b", "ref": "TC-009"}
        plan = {"counts": False, "source": "plan", "ref": "regression"}
        check_eq("M2 asks = typed items that count, except the ones born at gate B and the regression list",
                 (RF.left_asks(_ledger([asked, gate, plan, dict(asked, ref="TC-010")])), RF.left_asks(_ledger([gate, plan])),
                  RF.left_asks(None)), (2, 0, 0))
        facts = {"questions": {"listed": [], "answered": 0, "left_asks": 4}, "unknown": {}}
        check_in("M2 the heading says what 'Left with you' asks, beside the register", '## Open questions — 0 · 4 asked under "Left with you"',
                 RF._r_questions(facts))
        facts["questions"]["left_asks"] = 0
        check_eq("M2 none asked: the heading is as before, no segment", RF._r_questions(facts).splitlines()[0], "## Open questions — 0")
        check_eq("M2 a story the ledger of which is unknown: no segment (`left_asks` 0)",
                 RF._r_questions({"questions": {"listed": [], "answered": 0}, "unknown": {}}).splitlines()[0], "## Open questions — 0")
    finally:
        cleanup(root)


def m3_where_once() -> None:
    root = temp_dir("qa-manual-m3-")
    try:
        (root / "test-plan.md").write_text("# Plan\n\n" + "\n".join(f"## Case {n}\n\n## Given\n\n## When\n\n## Then\n" for n in (1, 2)), encoding="utf-8")
        got = RF._where(root, {})["files"]["test-plan.md"]
        check_eq("M3 each section once, in the order it first stands", got, ["Case 1", "Given", "When", "Then", "Case 2"])
        twelve = RF._where(root, {})["files"]["test-plan.md"]
        check_eq("M3 control: no section is listed twice", len(twelve), len(set(twelve)))
    finally:
        cleanup(root)


def m4_marker() -> None:
    start, end = RCA.START, RCA.END
    plan = "## Recommended regression\n\n- run a\n- run b\n\n" + start + "\n## Case appendix\n\n| x |\n" + end + "\n"
    check_eq("M4 the appendix marker ends the section", DV.regression_lines(plan), ["- run a", "- run b"])
    fenced = "## Recommended regression\n\n```\n" + start + "\n```\n- run c\n"
    check_eq("M4 a marker inside a fence is text", DV.regression_lines(fenced), ["```", start, "```", "- run c"])
    # a fence is closed by a marker of its OWN kind only: a `~~~` line inside a backtick fence is text, so what follows it is
    # still inside the fence (a heading and the appendix marker there end nothing)
    mixed = "## Recommended regression\n\n```\n~~~\n## not a heading\n" + start + "\n- run d\n```\n- run e\n\n## Next\n\ntext\n"
    check_eq("M4 (t-436) a `~~~` line inside a backtick fence does not close it: a heading and the marker inside stay text",
             DV.regression_lines(mixed), ["```", "~~~", "## not a heading", start, "- run d", "```", "- run e"])
    tilde = "## Recommended regression\n\n~~~\n```\n## not a heading\n~~~\n- run f\n\n## Next\n"
    check_eq("M4 (t-436) and the same the other way round: a backtick line inside a tilde fence is text",
             DV.regression_lines(tilde), ["~~~", "```", "## not a heading", "~~~", "- run f"])
    inside = "## Recommended regression\n\n- see " + start + " here\n"
    check_eq("M4 a marker word that is not the START of a line is text", DV.regression_lines(inside), ["- see " + start + " here"])
    plain = "## Recommended regression\n\n- run a\n\n## Next\n\ntext\n"
    check_eq("M4 a plan with no marker reads as before", DV.regression_lines(plain), ["- run a"])
    check_eq("M4 no regression heading is `None`, a blank section `[]`", (DV.regression_lines("# x\n" + start), DV.regression_lines(
             "## Recommended regression\n\n" + start + "\n")), (None, []))
    check_eq("M4 the prefix is derived from the one constant", DV.appendix_marker_prefix() + "start -->", start)
    root = temp_dir("qa-manual-m4-")
    try:
        (root / "test-plan.md").write_text(plan, encoding="utf-8")
        block = RF._r_regression({"regression": RF._regression(root)})
        check_not_in("M4 `_r_regression` carries no marker", "case-appendix", block)
        check_in("M4 ... and the list", "- run b", block)
        check_eq("M4 `check` on the same lines is the same (a repeat is empty)", RF._regression(root)["lines"], ["- run a", "- run b"])
    finally:
        cleanup(root)


def m5_paths() -> None:
    P = DV.portable_regression_line
    tail = " --label B-3 -- tests/ui/test_edit.py"
    want = '"${CLAUDE_PLUGIN_ROOT}/scripts/run_suite.py"'
    check_eq("M5 a quoted Windows path", P('python "D:/ws2/x/ai-packages/qa-factory/scripts/run_suite.py"' + tail), "python " + want + tail)
    check_eq("M5 a Windows path with back slashes", P('python "D:/ws/scripts\\run_suite.py"'), "python " + want)
    check_eq("M5 a POSIX path, unquoted", P("python /home/x/y/scripts/run_suite.py" + tail), "python ${CLAUDE_PLUGIN_ROOT}/scripts/run_suite.py" + tail)
    check_eq("M5 a path with spaces, quoted", P("python '/home/my user/qa/scripts/run_suite.py'"), "python '${CLAUDE_PLUGIN_ROOT}/scripts/run_suite.py'")
    check_eq("M5 idempotent: the result is no machine path", (P(P("python /home/x/y/scripts/run_suite.py")), DV.machine_paths(P("python /home/x/y/scripts/run_suite.py"))),
             ("python ${CLAUDE_PLUGIN_ROOT}/scripts/run_suite.py", []))
    foreign = 'python "C:/other/tool.py" and /home/x/y/scripts/not_ours_at_all.py'
    check_eq("M5 a path that is not ours is NOT rewritten (negative control: it is named)", (P(foreign), len(DV.machine_paths(foreign))), (foreign, 2))
    check_eq("M5 relative commands and URLs are untouched", [P(s) for s in ("pytest tests/api/test_a.py", "GET https://h.example/a/b/c")],
             ["pytest tests/api/test_a.py", "GET https://h.example/a/b/c"])
    root = temp_dir("qa-manual-m5-")
    try:
        (root / "test-plan.md").write_text('## Recommended regression\n\n- `python "D:/ws6/x/scripts/run_suite.py" --label B-3`\n- run C:/other/tool.py\n', encoding="utf-8")
        got = RF._regression(root)
        check_eq("M5 `_regression`: the ours line is portable, the foreign one stays and is named",
                 (got["lines"], got["machine_paths"]), (['- `python "${CLAUDE_PLUGIN_ROOT}/scripts/run_suite.py" --label B-3`', "- run C:/other/tool.py"],
                                                        ["C:/other/tool.py"]))
    finally:
        cleanup(root)


def m6_gap_line() -> None:
    L = RF.left_gap_line
    check_eq("M6 the form", L("R-3", "the cart total", "your answer to Q-1", ["R-3", "R-4"]),
             "- **R-3** (R-3, R-4) — To check: the cart total. Needed: your answer to Q-1")
    check_eq("M6 no requirements: no brackets", L("TC-001", "x", "y"), "- **TC-001** — To check: x. Needed: y")
    check_eq("M6 no ref", L("", "x", "y"), "- **a check the run does not name** — To check: x. Needed: y")
    check_eq("M6 no what", L("TC-1", "", "y"), "- **TC-1** — To check: the requirement as written. Needed: y")
    check_eq("M6 no needed: the gap stays and says so", L("TC-1", "x", ""), "- **TC-1** — To check: x. Needed: not named yet — a factory gap")
    check_eq("M6 one line whatever the words", "\n" in L("a\nb", "x\ny", "z\nw"), False)
    for size, whole in ((200, True), (201, False)):
        text = "w" * size
        line = L("R-1", text, text)
        check_eq(f"M6 a field of {size} characters is {'whole' if whole else 'cut with the ellipsis'}", (text in line, "…" in line), (whole, not whole))
    check_eq("M6 `left_with_you_line` keeps its text", RF.left_with_you_line("The page reads cancelled.", "Q-7"),
             "To check: The page reads cancelled. Needed: your answer to Q-7")
    check_eq("M6 ... and its no-question words", RF.left_with_you_line("x", ""), "To check: x. Needed: a question about it, which nobody has raised yet")
    check_eq("M6 `gap_needed_line` is the one assembly", RF.left_with_you_line("x", "Q"), RF.gap_needed_line("x", "your answer to Q"))
    # F-10: the refused manual case's line is assembled by `gap_needed_line` too - the words "Needed:" are spelled in one place only
    source = (Path(RF.__file__).read_text(encoding="utf-8"))
    check_eq("M6 `Needed: {` is spelled once in report_facts (inside `gap_needed_line`), nowhere by hand", source.count("Needed: {"), 1)
    check_eq("M6 ... and no hand-made 'To check: {' either", source.count("To check: {"), 1)
    flat = "- **BR-3** (R-7) — To check: x. Needed: y"
    check_eq("M6 `_names_item`: the item BR-3 is named by `**BR-3**`", RF._names_item(flat, {"ref": "BR-3"}, {}), True)
    check_eq("M6 ... R-3, which is no part of BR-3, is not", RF._names_item(flat, {"ref": "R-3"}, {}), False)
    check_eq("M6 ... an item of case TC-1 is not named by a line of R-7", RF._names_item("- **R-7** — To check: x", {"case": "TC-1"}, {}), False)
    check_eq("M6 ... the requirement R-7 is", RF._names_item(flat, {"ref": "R-7"}, {}), True)
    # the lines of the findings left open after gate B
    facts = {"gate_b": {"decided": True}, "exploratory": {"active": [
        {"oracle_status": "owner_question", "_case": "TC-004", "statement": "The page shows two banners", "question": "Is that intended?"},
        {"oracle_status": "owner_question", "statement": "", "question": ""},
        {"oracle_status": "person_confirmed", "statement": "settled"}]}}
    check_eq("M6 the findings left open: one E17 line each, a finding with no case is `a finding`", RF._open_finding_lines(facts),
             ["- **TC-004** — To check: The page shows two banners. Needed: your answer: Is that intended?",
              "- **a finding** — To check: what the run saw but could not settle. Needed: not named yet — a factory gap"])
    check_eq("M6 before gate B there is no line", RF._open_finding_lines(dict(facts, gate_b={"decided": False})), [])
    check_eq("M6 no register: nothing", RF._open_finding_lines({"gate_b": {"decided": True}, "exploratory": None}), [])
    check_in("M6 the block carries the finding line", "- **TC-004** — To check:", RF._r_left_gate_b(dict(facts, ledger={"items": []})))


def m7_bookkeeping() -> None:
    ledger_doc = json.loads((FIXTURES / "run-12586-gate-b" / "TP1-12586" / "work" / "ledger.json").read_text(encoding="utf-8"))
    ctx = {"factory_refs": set(), "case_lift": {}}
    records = [dict(CD.reason_record(r["detail"], ctx), owner=r["owner"], entity=r["entity"]) for r in ledger_doc["reason_records"]]
    ours = sorted({ref for r in records if r["owner"] == "factory" for ref in r["refs"]})
    check_eq("M7 on the 12586 ledger the factory's reasons name the cases TC-001 and TC-004 by `refs` (their `entity` names none)",
             (ours, sorted({r["entity"] for r in records if r["owner"] == "factory"})),
             (["TC-001", "TC-004"], ["approved", "its", "sensitivity_proof.instance_id", "test"]))
    led = RF._ledger_facts(dict(ledger_doc, reason_records=[dict(r, refs=r["refs"]) for r in records]))
    check_eq("M7 `_ledger_facts` carries them typed", sorted({x for r in led["records"] if r["owner"] == "factory" for x in r["refs"]}), ["TC-001", "TC-004"])

    def item(rid, cases, klass="unproven", plan_row="TS-9"):
        return {"id": rid, "class": klass, "cases": cases, "plan_row": plan_row}

    reqs = {"counts": {"proven": 1, "bug": 0, "unproven": 3, "wait": 0, "deferred": 0},
            "items": [item("R-1", ["TC-001"]), item("R-5", ["TC-002"]), item("R-2", ["TC-004"], plan_row="TS-4"), item("R-9", ["TC-001"], "proven")]}
    RF._count_bookkeeping(reqs, led, {"rows": []})
    # R-1: only the factory names TC-001 -> bookkeeping; R-5: a product reason names R-5 (and TC-002) -> not; R-2: the product reason of
    # TS-4 is absent in this ledger, so TC-004 alone is the factory's -> bookkeeping; a `proven` requirement is never counted
    # F-11: the requirements here are SYNTHETIC (the 12586 fixture has no register), so this is the mechanism on the real reasons, not
    # a measurement of 12586; the real number is a live proof (the report's "Live proofs" row)
    check_eq("M7 on SYNTHETIC requirements over the real 12586 reasons: 2 of the 3 `unproven` are open only in the factory's records",
             reqs["counts"]["bookkeeping"], 2)
    check_eq("M7 `unproven` is the same number (a split, not a subtraction)", reqs["counts"]["unproven"], 3)
    blocked = {"counts": {"unproven": 1}, "items": [item("R-5", ["TC-002"])]}
    RF._count_bookkeeping(blocked, {"records": [{"owner": "factory", "entity": "x", "refs": ["TC-002"]},
                                                {"owner": "product", "entity": "R-5", "refs": ["R-5"]}]}, {"rows": []})
    check_eq("M7 a reason of another owner on the requirement's id keeps it out", blocked["counts"]["bookkeeping"], 0)
    for label, doc in (("no ledger", None), ("an empty set of reasons", {"records": []}),
                       ("a legacy ledger (records with no `refs`)", {"records": [{"owner": "factory", "entity": "TC-1", "refs": None}]})):
        legacy = {"counts": {"unproven": 1}, "items": [item("R-1", ["TC-001"])]}
        RF._count_bookkeeping(legacy, doc, {"rows": []})
        check_eq(f"M7 {label}: no bookkeeping, the number is not changed", (legacy["counts"]["bookkeeping"], legacy["counts"]["unproven"]), (0, 1))
    # F-7: a factory-owned reason that is about an EXECUTION OUTCOME is not "our records only" - the check never ran, or its red stands
    ctx = {"factory_refs": set(), "case_lift": {}}
    check_eq("M7 a `not_executed` ledger state is an execution outcome too (its owner is the product's, so it never counted as ours)",
             [RF._execution_outcome(f"ledger: TC-1 is `{s}` (x)") for s in ("not_executed", "not_executed:handed_to_person")], [True, True])
    for state, execution in (("failed:NOT_EXECUTED", True), ("failed:RUNNER_MISREAD_EVIDENCE", True),
                             ("failed:TEST_BUG", False), ("not_verified:oracle_on_refused_base", False)):
        rr = CD.reason_record(f"ledger: TC-002 is `{state}` (no detail)", ctx)
        check_eq(f"M7 the reason of `{state}` is factory-owned (the premise)", rr["owner"], "factory")
        got = RF._ledger_facts(dict(ledger_doc, reason_records=[rr]))["records"]
        check_eq(f"M7 ... and `_ledger_facts` marks execution = {execution} for `{state}`", [r["execution"] for r in got], [execution])
        one = {"counts": {"unproven": 1}, "items": [item("R-5", ["TC-002"])]}
        RF._count_bookkeeping(one, {"records": got}, {"rows": []})
        check_eq(f"M7 ... so `{state}` is {'not ' if execution else ''}bookkeeping", one["counts"]["bookkeeping"], 0 if execution else 1)
    check_eq("M7 an execution outcome beside a bookkeeping reason keeps the requirement out (control: the bookkeeping one alone counts)",
             [RF._count_bookkeeping(x, {"records": recs}, {"rows": []}) or x["counts"]["bookkeeping"] for x, recs in (
                 ({"counts": {"unproven": 1}, "items": [item("R-5", ["TC-002"])]},
                  [{"owner": "factory", "entity": "x", "refs": ["TC-002"], "execution": False}]),
                 ({"counts": {"unproven": 1}, "items": [item("R-5", ["TC-002"])]},
                  [{"owner": "factory", "entity": "x", "refs": ["TC-002"], "execution": False},
                   {"owner": "factory", "entity": "y", "refs": ["TC-002"], "execution": True}]))], [1, 0])
    check_eq("M7 `_execution_outcome` never raises on odd input", [RF._execution_outcome(v) for v in (None, "", 5, "no state quoted")],
             [False, False, False, False])
    base = {"requirements": {"total": 4, "items": [], "counts": dict(reqs["counts"], wait=0, deferred=0, bookkeeping=2)}, "bugs": None,
            "cases": None, "tests": None, "ledger": None, "unknown": {}, "delivery": None, "gate_b": {"decided": False},
            "verdict": {"ready": None, "word": None, "first_reason": "", "disagreement": ""}}
    said = RF._r_verdict(base, "")
    check_in("M7 the verdict says it: same number, split", "3 not proven (2 of them open only in the factory's own records)", said)
    base["requirements"]["counts"]["bookkeeping"] = 0
    check_not_in("M7 no bookkeeping: no segment", "open only in", RF._r_verdict(base, ""))


def m9_integrations() -> None:
    check_eq("I no integration unmatched: no line", RF._r_integration_gap({"integrations": {"names": [], "readable": True}}), "")
    named = RF._r_integration_gap({"integrations": {"names": ["Jira", "Sonar"], "readable": True}})
    check_in("I the integrations are named in one E17 line", "- **Jira, Sonar** — To check: access to Jira, Sonar is not set", named)
    check_eq("I ... one line", named.count("\n"), 1)
    unknown = RF._r_integration_gap({"integrations": {"names": [], "readable": False}})
    check_in("I an answer that is not known: a line that says it could not be established", "could not be established", unknown)
    check_eq("I a facts dict with no key: no line", RF._r_integration_gap({}), "")
    check_eq("I the reader is the preflight's (names come from `unmatched_integrations`)",
             RF._integrations(Path("no-such-story"), {}), {"names": [], "readable": False})
    check("I the production reader exists", callable(GP.unmatched_integrations))
    # a reader that RAISES is `readable: False` (the report says it could not be established), never the silence of `True` with no names
    original = GP.unmatched_integrations

    def broken(art):
        raise RuntimeError("config reader boom")
    try:
        GP.unmatched_integrations = broken
        raised = RF._integrations(Path("a-story"), {})
    finally:
        GP.unmatched_integrations = original
    check_eq("I (t-436) a reader that raises is `readable: False`, no names", raised, {"names": [], "readable": False})
    check_in("I ... and the report says it could not be established", "could not be established",
             RF._r_integration_gap({"integrations": raised}))
    # F-6: a readable config with no `environment` block records no integration ("none"); only a real unknown keeps the line
    from harness import temp_project
    root = temp_project("qa-manual-i-")
    try:
        task = root / "qa-factory" / "artifacts" / "QA-1"
        task.mkdir(parents=True)
        (task / "pipeline.json").write_text(json.dumps({"ticket": "QA-1"}), encoding="utf-8")
        config = root / "qa-factory" / "config.json"
        for label, text, want in (("a readable config with no `environment` block", json.dumps({"adapters": {}}), {"names": [], "readable": True}),
                                  ("an `environment` that is not an object", json.dumps({"environment": "stand-1"}), {"names": [], "readable": False}),
                                  ("a config that cannot be parsed", "{not json", {"names": [], "readable": False}),
                                  ("an empty config file", "{}", {"names": [], "readable": False})):
            config.write_text(text, encoding="utf-8")
            check_eq(f"I {label}", GP.unmatched_integrations(task), want)
        config.unlink()
        check_eq("I no config file at all is not known", GP.unmatched_integrations(task), {"names": [], "readable": False})
        config.write_text(json.dumps({"adapters": {}}), encoding="utf-8")
        (task / "pipeline.json").unlink()
        check_eq("I no story is not known either", GP.unmatched_integrations(task), {"names": [], "readable": False})
        check_eq("I ... and a known 'none' prints no line", RF._r_integration_gap({"integrations": {"names": [], "readable": True}}), "")
    finally:
        cleanup(root)


def main() -> int:
    m1_manual_counted()
    m8_manual_failed()
    m10_manual_vs_table()
    m2_open_questions()
    m3_where_once()
    m4_marker()
    m5_paths()
    m6_gap_line()
    m7_bookkeeping()
    m9_integrations()
    return finish("test_report_manual_counted")


if __name__ == "__main__":
    raise SystemExit(main())
