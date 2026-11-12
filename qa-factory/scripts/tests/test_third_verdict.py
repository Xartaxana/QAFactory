#!/usr/bin/env python3
"""The third delivery verdict, `after_checks` (t-305 N8, PROJECT.md P21): decided from TYPED records through
`references/delivery-verdict-kinds.json`, never from a reason's text.

Keys K-N8.1-6, 14, 18-20 and 22 of the node spec live here (the others stand in the test file of the module they
test: test_check_delivery, test_traceability, test_ledger, test_report_facts, test_validate_artifacts_report,
test_stage_guard, test_gate_brief_and_retro, test_story_run_delivery_b, test_handoff_producers, test_measurers).

The purpose-built fixture `fixtures/after-checks/` is `artifacts-good` plus: a manual-human case (TC-004), a handed test
(TC-005, with its command), a manual check that did not answer and the triage row code writes for it (TC-002), and a plan
with a regression list - and no `no` kind anywhere. Its variants are built here, as named functions over a temp copy:
`red` (one APP_BUG, the negative control) and `analyst_ne` (a NOT_EXECUTED row nobody can re-derive), plus the eight
inputs of the NOT_EXECUTED battery (K-N8.3).
"""
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import (FIXTURES, GOOD, SCRIPTS, check, check_eq, check_in, check_not_in, cleanup,  # noqa: E402
                     finish, repaste_appendix, temp_dir)

sys.path.insert(0, str(SCRIPTS))
import check_delivery as CD  # noqa: E402
import contract as C  # noqa: E402
import delivery_verdict as DV  # noqa: E402
import grammar as G  # noqa: E402
import report_facts as RF  # noqa: E402

AFTER = FIXTURES / "after-checks"
DOC = DV.load_kinds()[0]


# --- helpers ----------------------------------------------------------------------------------------------------

def story(source: Path = AFTER) -> Path:
    """A throw-away copy of a fixture story (outside the package) - a task root the checks can write into."""
    root = temp_dir("qa-third-verdict-")
    target = root / "QA-1"
    shutil.copytree(source, target)
    return target


def read(task: Path, rel: str):
    return json.loads((task / rel).read_text(encoding="utf-8"))


def write(task: Path, rel: str, data) -> None:
    (task / rel).write_text(json.dumps(data, indent=2), encoding="utf-8")


def edit(task: Path, rel: str, change) -> None:
    data = read(task, rel)
    change(data)
    write(task, rel, data)


def run(task: Path) -> dict:
    return CD.assess(task)


def codes(doc: dict) -> list:
    return [f["code"] for f in doc.get("factory_findings") or []]


def entities(doc: dict, code: str) -> list:
    return [f["entity"] for f in doc.get("factory_findings") or [] if f["code"] == code]


def red(task: Path) -> None:
    """The negative control: TC-001's result becomes `failed` and the analyst triages it APP_BUG."""
    edit(task, "work/run-report.json", lambda r: r["results"][0].update(result="failed", attempt_id="a1"))
    edit(task, "work/triage.json", lambda t: t["triage"].append(
        {"instance_id": "tests/test_coupon.py::test_cap_rejected", "attempt_id": "a1", "verdict": "APP_BUG",
         "evidence": "evidence/sanity-20260911-105500.json"}))


def analyst_ne(task: Path, **extra) -> None:
    """TC-001 failed, and a NOT_EXECUTED row with no `source` (an analyst's) answers it."""
    edit(task, "work/run-report.json", lambda r: r["results"][0].update(result="failed", attempt_id="a1"))
    row = {"instance_id": "tests/test_coupon.py::test_cap_rejected", "attempt_id": "a1", "verdict": "NOT_EXECUTED"}
    row.update(extra)
    edit(task, "work/triage.json", lambda t: t["triage"].append(row))


# --- K-N8.1: every row of the verdict table, by id --------------------------------------------------------------

LEDGER_ROWS = [
    # (id, state, needs, expected kind, expected verdict)
    ("L1", "passed_green", {}, "passed", "none"),
    *[("L2", f"failed:{v}", {}, "red", "no")
      for v in ("APP_BUG", "APP_CHANGED", "TEST_BUG", "TEST_BUG:collection", "untriaged", "CASE_DEFECT", "FLAKY")],
    ("L3", "failed:NOT_EXECUTED", {}, "not_executed_unproven", "no"),
    ("L4", "failed:ENV_ISSUE", {}, "env_undecided", "no"),
    ("L4", "env_blocked:user", {}, "env_undecided", "no"),
    ("L4", "env_blocked:user", {"env_option": "accept"}, "env_accepted", "after_checks"),
    ("L4", "failed:ENV_ISSUE", {"env_option": "handed"}, "handed", "after_checks"),
    ("L4", "env_blocked:user", {"env_option": "apply"}, "env_change_pending", "after_checks"),
    ("L4", "env_blocked:user", {"env_option": "theirs"}, "env_change_pending", "after_checks"),
    ("L5", "not_executed:handed_to_person", {}, "handed", "after_checks"),
    ("L5", "not_executed:no result recorded for this row's cases", {"disposition": "manual-human"}, "manual_human", "after_checks"),
    ("L6", "not_executed:no result recorded for this row's cases", {}, "not_executed", "no"),
    ("L6", "not_executed:no result recorded for this row's cases", {"disposition": "automate"}, "not_executed", "no"),
    ("L7", "skipped:cosmetic, outside the diff, no user impact recorded", {}, "planned_skip", "none"),
    ("L8", "skipped:inconclusive run", {}, "decided_elsewhere", "none"),
    ("L8", "skipped:marked skipped in the run", {}, "decided_elsewhere", "none"),
    ("L9", "impossible", {}, "impossible", "no"),
    # G1-3 flipped this kind from `none` to `no` (FR-21 blocks delivery; t-988 section L F-1 (a), premise measured 0 of 116 ledgers)
    ("L10", "pending_implementation", {}, "pending_implementation", "no"),
    ("L11", "deferred_by_decision", {}, "deferred_undecided", "no"),
    ("L12", "waived:deferred_by_decision", {"words": True}, "deferred_with_words", "after_checks"),
    ("L12", "waived:deferred_by_decision", {}, "deferred_undecided", "no"),
    ("L13", "waived:not_executed:no result recorded for this row's cases", {"words": True}, "deferred_with_words", "after_checks"),
    ("L13", "waived:env_blocked:user", {"words": True}, "deferred_with_words", "after_checks"),
    ("L13", "waived:failed:ENV_ISSUE", {"words": True}, "deferred_with_words", "after_checks"),
    ("L13", "waived:failed:APP_BUG", {"words": True}, "red", "no"),
    ("L13", "waived:failed:NOT_EXECUTED", {"words": True}, "not_executed_unproven", "no"),
    ("L13", "waived:impossible", {"words": True}, "impossible", "no"),
    ("L14", "not_verified_flaky", {}, "flaky_unverified", "no"),
    ("L15", "review_skipped", {}, "review_gap", "no"),
    ("L15", "review_rejected", {}, "review_gap", "no"),
    ("L15", "review_unrecognised:maybe", {}, "review_gap", "no"),
    ("L16", "review_unverified", {}, "review_unverified", "after_checks"),
    ("L17", "not_verified:expectation_unconfirmed", {}, "unconfirmed_expectation", "after_checks"),
    ("L18", "not_verified:missing_sensitivity_proof", {}, "decided_elsewhere", "none"),
    # TQ1-18 (S-1): the longest prefix wins, so the base-refusal state is its own kind and `no`, and the row above stays as it was
    ("L18", "not_verified:oracle_on_refused_base", {}, "refused_base", "no"),
    ("L19", "partial", {}, "partial_or_error", "no"),
    ("L19", "error", {}, "partial_or_error", "no"),
    ("L20", "subtask_in_progress", {}, "subtask_open", "no"),
    # HF2-18: the analyst's control experiment found the assert stricter than the requirement; the person decides
    ("L21", "failed:ASSERT_STRICTER", {}, "assert_stricter", "after_checks"),
    ("L21", "waived:failed:ASSERT_STRICTER", {"words": True}, "assert_stricter", "after_checks"),
    # t-2181 PC-5 (§2.3): a green that met a side which was not real / was not known; the prefix's `decided_elsewhere` stays for the rest
    ("L22", "not_verified:on_substitute", {}, "on_substitute", "after_checks"),
    ("L22", "not_verified:sides_unknown", {}, "sides_unknown", "after_checks"),
    ("L22", "not_verified:placeholder_open", {}, "placeholder_open", "after_checks"),     # t-2277 J-C7
]
TRACE_ROWS = [
    ("T1", "unresolved:handed_to_person", {}, "handed", "after_checks"),
    ("T2", "unresolved:expectation_unconfirmed", {}, "unconfirmed_expectation", "after_checks"),
    ("T3", "unresolved:blocked_by_env", {}, "env_undecided", "no"),
    ("T3", "unresolved:blocked_by_env", {"env_option": "accept"}, "env_accepted", "after_checks"),
    ("T4", "unresolved:contradicts_requirement", {}, "chain_broken", "no"),
    ("T4", "unresolved:no_reason", {}, "chain_broken", "no"),
    ("T5", "result:inconclusive", {}, "not_executed_unproven", "no"),
    ("T5", "result:inconclusive", {"code_row": True}, "not_executed_code", "after_checks"),
    *[("T6", f"result:{w}", {}, "chain_broken", "no") for w in ("skipped", "not_run", "partial", "error", "blocked")],
    ("T7", "manual_human_no_package", {}, "manual_human", "after_checks"),
    *[("T8", w, {}, "chain_broken", "no") for w in ("no_plan_row", "no_case", "not_in_manifest", "no_result", "register_empty")],
]
# the kinds a producer fixes (R1-R8): their verdicts, from the file
PRODUCER_KINDS = [("R1", "factory_record", "no"), ("R2", "run_not_deliverable", "no"), ("R3", "s6_null_run", "none"),
                  ("R4", "triage_gap", "no"), ("R5", "handed", "after_checks"), ("R6", "coverage_gap", "no"),
                  ("R7", "unconfirmed_expectation", "after_checks"), ("R7", "review_unverified", "after_checks"),
                  ("R8", "regression", "none"), ("R8", "regression_missing", "none"),
                  ("R9", "branch_lost", "after_checks"), ("R9", "branch_excluded", "after_checks"),
                  ("R9", "branch_unproven", "after_checks"), ("R9", "branches_not_recorded", "after_checks"),
                  ("R9", "source_unreconciled", "after_checks"), ("R9", "attachment_question_open", "after_checks"),
                  ("R9", "branch_excluded_by_word", "none"), ("R9", "branches_unreadable", "no"),
                  ("R10", "awaiting_implementation", "no"), ("R11", "on_substitute", "after_checks"), ("R11", "sides_unknown", "after_checks")]


def k_n8_1_every_row_of_the_table() -> None:
    third_kind = "handed"
    for rid, state, needs, kind, verdict in LEDGER_ROWS:
        got = DV.kind_of_state(state, DOC, **needs)
        check_eq(f"K-N8.1 {rid} `{state}` {needs or ''} -> kind {kind}", got, kind)
        check_eq(f"K-N8.1 {rid} `{state}` -> verdict {verdict}", DV.verdict_of_kind(got, DOC), verdict)
    for rid, gap, needs, kind, verdict in TRACE_ROWS:
        got = DV.kind_of_gap(gap, DOC, **needs)
        check_eq(f"K-N8.1 {rid} gap `{gap}` {needs or ''} -> kind {kind}", got, kind)
        check_eq(f"K-N8.1 {rid} gap `{gap}` -> verdict {verdict}", DV.verdict_of_kind(got, DOC), verdict)
    for rid, kind, verdict in PRODUCER_KINDS:
        check_eq(f"K-N8.1 {rid} kind `{kind}` -> verdict {verdict}", DV.verdict_of_kind(kind, DOC), verdict)
    # the combination rule, over every kind of the file: alone, with a `no`, with a third kind, with a none kind
    word_of_verdict = {"no": "no", "after_checks": "after_checks", "none": "yes"}
    for kind, entry in DOC["kinds"].items():
        verdict = entry["verdict"]
        check_eq(f"K-N8.1 kind `{kind}` alone", DV.decide([kind], DOC)[0], word_of_verdict[verdict])
        check_eq(f"K-N8.1 kind `{kind}` + a `no` kind is no", DV.decide([kind, "red"], DOC)[0], "no")
        if verdict != "no":
            check_eq(f"K-N8.1 kind `{kind}` + a third kind", DV.decide([kind, third_kind], DOC)[0], "after_checks")
            check_eq(f"K-N8.1 kind `{kind}` + a none kind", DV.decide([kind, "passed"], DOC)[0], word_of_verdict[verdict])
    check_eq("K-N8.1 no kinds at all is yes", DV.decide([], DOC), ("yes", []))
    word, findings = DV.decide(["handed", "not_a_kind"], DOC)
    check_eq("K-N8.1 an unknown kind is no", word, "no")
    check_eq("K-N8.1 and says so, once, naming it", [(f["code"], f["entity"]) for f in findings],
             [("VERDICT_KIND_UNKNOWN", "not_a_kind")])
    check_eq("K-N8.1 an absent state is unknown, never a default", DV.kind_of_state("failed:WEIRD", DOC), None)
    check_eq("K-N8.1 and so is an absent gap word", DV.kind_of_gap("brand_new_gap", DOC), None)
    # the kinds file itself: every owner is a word of the contract (the A4 class), every mapped kind exists
    check_eq("K-N8.1 the owners of the kinds file are the contract's", DV.OWNERS, tuple(C.DELIVERY_REASON_OWNERS))
    check_eq("K-N8.1 every owner in the kinds file is one of them",
             sorted({e["owner"] for e in DOC["kinds"].values()} - set(C.DELIVERY_REASON_OWNERS)), [])
    check_eq("K-N8.1 every owner of check_delivery's maps is one of them (FR-19)",
             sorted({*CD.OWNER_BY_TRIAGE_VERDICT.values(), *CD.OWNER_BY_LEDGER_STATE.values(), *CD.OWNER_BY_CODE.values()}
                    - set(C.DELIVERY_REASON_OWNERS)), [])
    # an unreadable or absent file: fail closed, with ONE finding
    gone = DV.decide(["passed"], None)
    check_eq("K-N8.1 the real file reads", DV.load_kinds()[1], "")
    broken = temp_dir("qa-kinds-")
    try:
        bad = broken / "delivery-verdict-kinds.json"
        bad.write_text("{not json", encoding="utf-8")
        doc, problem = DV.load_kinds(bad)
        check("K-N8.1 a file that is not JSON reads as nothing, with its reason", doc == {} and problem, problem)
        missing = DV.load_kinds(broken / "absent.json")
        check("K-N8.1 an absent file reads as nothing, with its reason", missing[0] == {} and missing[1], str(missing))
    finally:
        cleanup(broken)
    check_eq("K-N8.1 the verdict over the real file is still yes for a pass (control)", gone[0], "yes")


# --- K-N8.2: the verdict never reads a reason's TEXT -------------------------------------------------------------

def k_n8_2_text_is_never_read() -> None:
    def word_with_texts_replaced(task: Path) -> str:
        """Every producer's sentences replaced by "x": the word must not move."""
        saved = (CD.ledger_records, CD.traceability_records, CD.triage_reasons, CD.run_reasons, CD.witness_reasons,
                 CD._completeness, CD.factory_finding_reasons)

        def xs_records(orig):
            return lambda *a, **k: [dict(r, text="x" if r.get("text") else "") for r in orig(*a, **k)]

        def xs_list(orig):
            return lambda *a, **k: ["x" for _ in orig(*a, **k)]
        CD.ledger_records, CD.traceability_records = xs_records(saved[0]), xs_records(saved[1])
        CD.triage_reasons, CD.run_reasons, CD.witness_reasons = xs_list(saved[2]), xs_list(saved[3]), xs_list(saved[4])
        CD._completeness = lambda a: [("x", kind, case) for _t, kind, case in saved[5](a)]
        CD.factory_finding_reasons = xs_list(saved[6])
        try:
            return run(task)["delivery_verdict"]
        finally:
            (CD.ledger_records, CD.traceability_records, CD.triage_reasons, CD.run_reasons, CD.witness_reasons,
             CD._completeness, CD.factory_finding_reasons) = saved

    for name, build, expected in (("base", lambda t: None, "after_checks"), ("red", red, "no"),
                                  ("analyst_ne", analyst_ne, "no")):
        task = story()
        try:
            build(task)
            plain = run(task)["delivery_verdict"]
            check_eq(f"K-N8.2 {name}: the word", plain, expected)
            check_eq(f"K-N8.2 {name}: every sentence replaced by 'x' leaves the word", word_with_texts_replaced(task), plain)
        finally:
            cleanup(task.parent)
    # a forged sentence alone: a triage reason that starts like a handed one is still a `triage_gap`
    task = story(GOOD)
    saved = CD.triage_reasons
    CD.triage_reasons = lambda artifacts: ["handed to the person: 1 test(s) nothing here could run — TC-9: x"]
    try:
        doc = run(task)
        check_eq("K-N8.2 a reason forged to start `handed to the person:` alone gives no", doc["delivery_verdict"], "no")
        check_eq("K-N8.2 and its record is a triage gap, whatever it says",
                 [r["kind"] for r in doc["reason_records"] if r["detail"].startswith("handed to the person")], ["triage_gap"])
    finally:
        CD.triage_reasons = saved
        cleanup(task.parent)
    # the same forged sentence over a story that DOES have real items: the guard `VERDICT_WITHOUT_ITEMS` cannot rescue it
    # there, so only the kind keeps the word `no` (a classifier reading the sentence would say `after_checks`)
    task = story()
    CD.triage_reasons = lambda artifacts: ["handed to the person: 1 test(s) nothing here could run — TC-9: x"]
    try:
        doc = run(task)
        check_eq("K-N8.2 a forged `handed to the person:` sentence beside real items is still `no`", doc["delivery_verdict"], "no")
    finally:
        CD.triage_reasons = saved
        cleanup(task.parent)


# --- K-N8.3: NOT_EXECUTED is the third verdict only for what code can write again ---------------------------------

def k_n8_3_not_executed_battery() -> None:
    task = story()
    try:
        doc = run(task)
        check_eq("K-N8.3 the true code row: after_checks", doc["delivery_verdict"], "after_checks")
        check_eq("K-N8.3 and no finding", entities(doc, "NOT_EXECUTED_NOT_RE_DERIVED"), [])
    finally:
        cleanup(task.parent)

    def with_second_manual_check(t: dict) -> None:
        pass

    def manual(r: dict, **change) -> None:
        for key in ("manual_checks", "current_manual_checks"):
            r[key][0].update(change)

    cases = {
        "1 an analyst's row on a red result": (analyst_ne, "tests/test_coupon.py::test_cap_rejected"),
        "2 `source: code` forged on a result failure": (lambda t: analyst_ne(t, source="code"),
                                                        "tests/test_coupon.py::test_cap_rejected"),
        "3 `source: Code`": (lambda t: edit(t, "work/triage.json", lambda d: d["triage"][0].update(source="Code")), "TC-002"),
        "4 a code row on a manual fail": (lambda t: edit(t, "work/run-report.json", lambda r: manual(r, result="fail")),
                                          "TC-002"),
        "5 evidence_validated false": (lambda t: edit(t, "work/run-report.json", lambda r: manual(r, evidence_validated=False)),
                                       "TC-002"),
        "6 a contradicts_requirement row added after S7": (
            lambda t: edit(t, "work/automation-manifest.json", lambda m: m["unresolved"].append(
                {"case": "TC-002", "reason": "contradicts_requirement", "detail": "the case misread R-2"})), "TC-002"),
        "7 the attempt was re-run": (lambda t: edit(t, "work/triage.json", lambda d: d["triage"][0].update(attempt_id="a0")),
                                     "TC-002"),
    }

    def two_failures(t: Path) -> None:
        second = {"case": "TC-003", "result": "inconclusive", "attempt_id": "a1", "evidence_validated": True,
                  "limitations": ["the page returned 503"], "evidence_refs": [{"path": "evidence/tc-002-order-record.txt"}]}
        edit(t, "work/run-report.json", lambda r: [r[k].append(dict(second)) for k in ("manual_checks", "current_manual_checks")])
        edit(t, "work/triage.json", lambda d: d["triage"][0].update(test="TC-003"))
    cases["8 a code row that names two failures"] = (two_failures, "TC-002")
    for label, (build, entity) in cases.items():
        task = story()
        try:
            build(task)
            doc = run(task)
            check_eq(f"K-N8.3 input {label}: no", doc["delivery_verdict"], "no")
            check_in(f"K-N8.3 input {label}: a finding names the row", entity, entities(doc, "NOT_EXECUTED_NOT_RE_DERIVED"))
            check_eq(f"K-N8.3 input {label}: the bool is False", doc["delivery_ready"], False)
        finally:
            cleanup(task.parent)
    # the owner of a `failed:NOT_EXECUTED` reason is the factory's (E2, FR-19)
    task = story()
    try:
        analyst_ne(task)
        doc = run(task)
        owners = [r["owner"] for r in doc["reason_records"] if "failed:NOT_EXECUTED" in r["detail"]]
        check("K-N8.3 a failed:NOT_EXECUTED reason exists", bool(owners), str(doc["reasons"]))
        check_eq("K-N8.3 and it is the factory's, a word the contract holds", set(owners), {"factory"})
    finally:
        cleanup(task.parent)
    # the helper itself: pure, and its error direction is False
    import s7_pretriage as S7
    report = C.load_json(AFTER / "work" / "run-report.json")
    manifest = C.load_json(AFTER / "work" / "automation-manifest.json")
    row = C.triage_rows(C.load_json(AFTER / "work" / "triage.json"))[0]
    check_eq("K-N8.3 rederives: the committed row is what S7 writes", S7.rederives(row, report, manifest), True)
    check_eq("K-N8.3 rederives: another verdict is not", S7.rederives(dict(row, verdict="APP_BUG"), report, manifest), False)
    check_eq("K-N8.3 rederives: another attempt is not", S7.rederives(dict(row, attempt_id="a2"), report, manifest), False)
    check_eq("K-N8.3 rederives: not an object is not", S7.rederives("x", report, manifest), False)
    check_eq("K-N8.3 rederives: a row an analyst answers is not (its own row is kept)",
             S7.rederives(row, report, manifest, rows=[{"instance_id": "TC-002", "verdict": "TEST_BUG"}]), False)


# --- K-N8.4: regression is always listed and never decides --------------------------------------------------------

def k_n8_4_regression() -> None:
    def regression_row(doc):
        return [i for i in doc["left_items"] if i["ref"] == "regression"]

    task = story(GOOD)
    try:
        doc = run(task)
        check_eq("K-N8.4 a plan with a regression list and nothing else open: yes", doc["delivery_verdict"], "yes")
        row = regression_row(doc)
        check_eq("K-N8.4 the row is the regression kind", [r["kind"] for r in row], ["regression"])
        check_eq("K-N8.4 its lines are the plan's, verbatim",
                 row[0]["lines"], ["- `poetry run pytest tests/test_cart.py` - covers the cart total path the change reuses"])
        check_eq("K-N8.4 it never counts", row[0]["counts"], False)
        check_eq("K-N8.4 no finding", codes(doc), [])
    finally:
        cleanup(task.parent)
    # the section is absent: yes, a finding, the gap line - never a block
    task = story(GOOD)
    try:
        plan = task / "test-plan.md"
        plan.write_text(plan.read_text(encoding="utf-8").split("## Recommended regression")[0], encoding="utf-8")
        doc = run(task)
        check_eq("K-N8.4 a plan with no regression section: still yes", doc["delivery_verdict"], "yes")
        check_eq("K-N8.4 with the finding", codes(doc), ["REGRESSION_SCOPE_MISSING"])
        row = regression_row(doc)
        check_eq("K-N8.4 and the gap line", (row[0]["kind"], row[0]["lines"]),
                 ("regression_missing", ["no regression scope was recorded at S3 — a factory gap"]))
        plan.write_text(plan.read_text(encoding="utf-8") + "\n## Recommended regression\n\n   \n", encoding="utf-8")
        doc = run(task)
        check_eq("K-N8.4 a blank section is the same gap", (doc["delivery_verdict"], codes(doc)),
                 ("yes", ["REGRESSION_SCOPE_MISSING"]))
        # a section that gives only its own why is a list like any other (E3 split: not a gap)
        plan.write_text(plan.read_text(encoding="utf-8").rstrip() + "\nNone: the change touches no shared path.\n",
                        encoding="utf-8")
        doc = run(task)
        check_eq("K-N8.4 a section that says only why: carried, no finding", (doc["delivery_verdict"], codes(doc)),
                 ("yes", []))
        check_eq("K-N8.4 verbatim", regression_row(doc)[0]["lines"], ["None: the change touches no shared path."])
    finally:
        cleanup(task.parent)
    # the pure reader: code fences, the next section, absence
    check_eq("K-N8.4 absent -> None", DV.regression_lines("# t\n\n## Plan\n"), None)
    check_eq("K-N8.4 a `## ` line inside a fence does not end it",
             DV.regression_lines("## Recommended regression\n\n```\n## not a heading\n```\n- a\n\n## Next\n- b\n"),
             ["```", "## not a heading", "```", "- a"])


# --- K-N8.5: a deferral is the third verdict only with the person's words ----------------------------------------

def k_n8_5_deferred() -> None:
    def defer(task: Path, words: bool) -> None:
        edit(task, "work/automation-manifest.json", lambda m: m["unresolved"].append(
            {"case": "TC-002", "reason": "deferred_by_decision:gateA"}))
        if words:
            edit(task, "pipeline.json", lambda p: p.update(gate_waivers=[
                {"gate": "A", "requirement": "R-2", "decision": "defer it, the order page is down this week",
                 "at": "2026-09-11T10:00:00Z", "by": "human"}]))

    task = story(GOOD)
    try:
        defer(task, False)
        doc = run(task)
        check_eq("K-N8.5 a bare deferred_by_decision: no", doc["delivery_verdict"], "no")
        mine = [r for r in doc["reason_records"] if r["detail"].startswith("deferred without a decision")]
        check_eq("K-N8.5 one reason, in words", len(mine), 1)
        check_eq("K-N8.5 the reason stays the product's (N-3: the requirement is unproven)", mine[0]["owner"], "product")
        check_eq("K-N8.5 the factory's share is its own finding", entities(doc, "DEFERRED_WITHOUT_DECISION"), ["TS-2"])
        owned = [f["owner"] for f in doc["factory_findings"] if f["code"] == "DEFERRED_WITHOUT_DECISION"]
        check_eq("K-N8.5 owned by the factory", owned, ["factory"])
    finally:
        cleanup(task.parent)
    task = story(GOOD)
    try:
        defer(task, True)
        doc = run(task)
        check_eq("K-N8.5 waived:deferred_by_decision with their words: after_checks", doc["delivery_verdict"], "after_checks")
        item = [i for i in doc["left_items"] if i["ref"] == "TC-002"][0]
        check_eq("K-N8.5 the item is a deferral with words", item["kind"], "deferred_with_words")
        check_in("K-N8.5 and quotes them", "the order page is down this week", item["words"])
        check_eq("K-N8.5 gate A's words, so the item is not born at gate B", item["source"], "ledger")
    finally:
        cleanup(task.parent)
    # N-2: a waiver never lifts a found bug
    check_eq("K-N8.5 control: waived:failed:APP_BUG stays no",
             DV.decide([DV.kind_of_state("waived:failed:APP_BUG", DOC, words=True)], DOC)[0], "no")


# --- K-N8.6: the person's word about a stand gap, as the card's closed words --------------------------------------

def k_n8_6_env_words() -> None:
    # F3 (attempt 2): the triage row's `decision` field is NOT a source - triage.json is the analyst's file, not the person's.
    # The reader takes no row at all, and the old field list is gone; the end-to-end twin is in `k_f3_the_analyst_is_not_the_person`
    check("K-N8.6 the triage row is no argument of the reader any more (one source: the gate B record)",
          list(CD.env_decision.__code__.co_varnames[:CD.env_decision.__code__.co_argcount]) == ["case_key", "decisions", "cfg"])
    check("K-N8.6 and the field list that read it is gone", not hasattr(CD, "ENV_DECISION_KEYS"))
    waivers = {"workflows/TC-001": {"option": "handed", "words": "handed - the person wrote: TC-001: run", "at": "x"}}
    check_eq("K-N8.6 a gate B waiver `handed` is read, by the bare id too", CD.env_decision("TC-001", waivers), "handed")
    check_eq("K-N8.6 no record of the person's: undecided", CD.env_decision("TC-001", {}), "")
    check_eq("K-N8.6 an answer that is not one of the four (empty option) is not read",
             CD.env_decision("TC-001", {"TC-001": {"option": "", "words": "fix now", "at": ""}}), "")
    two = {"a/TC-001": {"option": "accept", "words": "", "at": ""}, "b/TC-001": {"option": "handed", "words": "", "at": ""}}
    check_eq("K-N8.6 two gaps of one id that disagree are undecided", CD.env_decision("TC-001", two), "")
    # the kinds the options give, and what a re-run does through the ledger states (L1/L2 decide it)
    for option, kind in (("accept", "env_accepted"), ("handed", "handed"), ("apply", "env_change_pending"),
                         ("theirs", "env_change_pending"), ("", "env_undecided")):
        check_eq(f"K-N8.6 option `{option}` -> {kind}", DV.kind_of_state("env_blocked:user", DOC, env_option=option), kind)
    check_eq("K-N8.6 `apply`, no re-run yet: the third",
             DV.decide([DV.kind_of_state("env_blocked:user", DOC, env_option="apply")], DOC)[0], "after_checks")
    check_eq("K-N8.6 then a re-run that passed: the row is passed_green, yes",
             DV.decide([DV.kind_of_state("passed_green", DOC, env_option="apply")], DOC)[0], "yes")
    check_eq("K-N8.6 or a re-run that failed and nobody triaged: no",
             DV.decide([DV.kind_of_state("failed:untriaged", DOC, env_option="apply")], DOC)[0], "no")
    # end to end: a stand gap on TC-002, answered through the person's recorded word
    for answer, expected in (("accept - the person wrote: TC-002: accept", "after_checks"),
                             ("apply - the person wrote: TC-002: change", "after_checks"),
                             ("handed - the person wrote: TC-002: run", "after_checks"),
                             ("fix now", "no"), (None, "no")):
        task = story(GOOD)
        try:
            edit(task, "work/automation-manifest.json", lambda m: m["unresolved"].append(
                {"case": "TC-002", "reason": "blocked_by_env", "owner": "user", "detail": "the stand has no sandbox account"}))
            if answer:
                edit(task, "pipeline.json", lambda p: p.update(stage_overrides=[
                    {"stage": "S9", "match": "stand gap: TC-002", "decision": answer, "at": "2026-10-03T10:00:00Z", "by": "human"}]))
            doc = run(task)
            check_eq(f"K-N8.6 e2e: {answer!r} -> {expected}", doc["delivery_verdict"], expected)
            if expected == "after_checks":
                item = [i for i in doc["left_items"] if i["ref"] == "TC-002"][0]
                check_eq("K-N8.6 e2e: the item is born at gate B and quotes their words", (item["source"], item["words"]),
                         ("gate_b", answer))
        finally:
            cleanup(task.parent)


# --- K-N8.14: THE reader of the word -----------------------------------------------------------------------------

def k_n8_14_word_of() -> None:
    battery = [({"delivery_verdict": "yes", "delivery_ready": True}, "yes"),
               ({"delivery_verdict": "after_checks", "delivery_ready": False}, "after_checks"),
               ({"delivery_verdict": "no", "delivery_ready": False}, "no"),
               ({"delivery_ready": True}, "yes"), ({"delivery_ready": False}, "no"),
               ({"delivery_ready": "no"}, "unknown"), ({"delivery_verdict": "yes", "delivery_ready": False}, "unknown"),
               ({"delivery_verdict": "maybe"}, "unknown"), (None, None)]
    for ledger, expected in battery:
        check_eq(f"K-N8.14 word_of({ledger}) -> {expected}", DV.word_of(ledger), expected)
    check_eq("K-N8.14 a ledger with neither field reads no (derived from `is True`)", DV.word_of({}), "no")
    check_eq("K-N8.14 an after_checks word over a True bool is unknown", DV.word_of(
        {"delivery_verdict": "after_checks", "delivery_ready": True}), "unknown")
    check_eq("K-N8.14 not a mapping: unknown", DV.word_of(["yes"]), "unknown")


# --- K-N8.18: the MR description quotes the report's section, once ------------------------------------------------

def k_n8_18_one_list() -> None:
    import delivery_summary as DS
    task = story()
    try:
        doc = run(task)
        res = RF.write(task)
        check("K-N8.18 setup: --write rendered the report", res["ok"], str(res["lines"]))
        section = RF.left_with_you_text(task)
        check("K-N8.18 setup: the report has the section", bool(section))
        text = DS.render(DS.build(task, C.load_json(task / "work" / "ledger.json")))
        check_in("K-N8.18 the section is in the MR text byte-equal", section.rstrip("\n"), text)
        for gone in ("Run these yourself", "Left with you (the code critic could not verify these tests)"):
            check_not_in(f"K-N8.18 the old list `{gone}` is gone", gone, text)
        check_in("K-N8.18 it carries the regression block's own lines", "poetry run pytest tests/test_cart.py", text)
        (task / "test-report.md").unlink()
        text = DS.render(DS.build(task, C.load_json(task / "work" / "ledger.json")))
        check_in("K-N8.18 no report: one line, never a silent gap", "Left with you: the report has none yet — see test-report.md", text)
        check_eq("K-N8.18 the summary carries the word", DS.build(task, C.load_json(task / "work" / "ledger.json"))["delivery_verdict"],
                 "after_checks")
        del doc
    finally:
        cleanup(task.parent)


# --- K-N8.19: the dashboard chip ---------------------------------------------------------------------------------

def k_n8_19_ready_chip() -> None:
    import factory_dashboard as FD
    for ledger, expected in (({"delivery_verdict": "yes", "delivery_ready": True}, ("yes", "ok")),
                             ({"delivery_verdict": "after_checks", "delivery_ready": False}, ("after_checks", "skip")),
                             ({"delivery_verdict": "no", "delivery_ready": False}, ("no", "warn")),
                             ({"delivery_ready": True}, ("yes", "ok")), ({"delivery_ready": False}, ("no", "warn")),
                             ({}, ("not recorded", "nd")), (None, ("not recorded", "nd")),
                             ({"delivery_verdict": "maybe", "delivery_ready": False}, ("unknown (maybe)", "warn")),
                             ({"delivery_ready": "no"}, ("unknown (no)", "warn")),
                             ({"delivery_verdict": "yes", "delivery_ready": False}, ("unknown (yes)", "warn"))):
        check_eq(f"K-N8.19 ready_chip({ledger})", FD.ready_chip(ledger), expected)
    check_eq("K-N8.19 three words, three classes", len({FD.ready_chip({"delivery_ready": r, "delivery_verdict": w})[1]
                                                          for r, w in ((True, "yes"), (False, "after_checks"), (False, "no"))}), 3)


# --- K-N8.20: the purpose-built fixture ---------------------------------------------------------------------------

def k_n8_20_fixture() -> None:
    task = story()
    try:
        doc = run(task)
        check_eq("K-N8.20 base: after_checks", doc["delivery_verdict"], "after_checks")
        check_eq("K-N8.20 base: zero reasons", doc["reasons"], [])
        counting = [(i["ref"], i["kind"]) for i in doc["left_items"] if i["counts"]]
        check_eq("K-N8.20 base: the items", sorted(counting),
                 [("TC-002", "not_executed_code"), ("TC-004", "manual_human"), ("TC-005", "handed")])
        regression = [i for i in doc["left_items"] if i["kind"] == "regression"]
        check_eq("K-N8.20 base: plus one regression row of one line", [len(i["lines"]) for i in regression], [1])
        check_eq("K-N8.20 base: the handed item carries its command", [i["how"] for i in doc["left_items"] if i["ref"] == "TC-005"],
                 ["android: npm run e2e -- --grep TC-005"])
        check_eq("K-N8.20 base: delivery_ready is the bool of the word", doc["delivery_ready"], False)
        res = RF.write(task)
        check("K-N8.20 base: --write", res["ok"], str(res["lines"]))
        problems = RF.check(task)
        check_eq("K-N8.20 base: --write then --check -> []", problems, [])
        head = (task / "test-report.md").read_text(encoding="utf-8")
        check_in("K-N8.20 base: the report's head and line", "**Verdict: ready once you finish the checks left with you.**", head)
        check_in("K-N8.20 base: with the count", "`delivery_ready: after_checks — 3 items are left with you`", head)
        print(f"K-N8.20 counts: ledger {len(doc['left_items'])} left_items rows "
              f"({len(counting)} counting + {len(regression)} regression), {len(doc['reasons'])} reasons, "
              f"{len(doc['factory_findings'])} findings")
    finally:
        cleanup(task.parent)
    task = story()
    try:
        red(task)
        doc = run(task)
        check_eq("K-N8.20 red: no", doc["delivery_verdict"], "no")
        check_in("K-N8.20 red: the first reason is the APP_BUG", "failed:APP_BUG", doc["reasons"][0])
        check_eq("K-N8.20 red: delivery_ready False", doc["delivery_ready"], False)
    finally:
        cleanup(task.parent)
    task = story()
    try:
        analyst_ne(task)
        doc = run(task)
        check_eq("K-N8.20 analyst_ne: no", doc["delivery_verdict"], "no")
        check_eq("K-N8.20 analyst_ne: the finding names the row", entities(doc, "NOT_EXECUTED_NOT_RE_DERIVED"),
                 ["tests/test_coupon.py::test_cap_rejected"])
    finally:
        cleanup(task.parent)


# --- K-N8.22: after_checks is impossible with nothing left --------------------------------------------------------

def k_n8_22_never_without_items() -> None:
    facts = {"index": {}, "manifest": {}, "cfg": {}, "decisions": {}, "report": {}, "triage": [], "plan": []}
    for kind, entry in DOC["kinds"].items():
        if entry["verdict"] != "after_checks":
            continue
        items = CD.build_left_items([{"kind": kind, "case": "TC-9", "ref": "TC-9", "requirements": ["R-9"], "source": "ledger"}],
                                    facts, DOC)
        check_eq(f"K-N8.22 a record of kind `{kind}` always makes a counting item", DV.count_items(items, DOC), 1)
        check_eq(f"K-N8.22 `{kind}`: keyed by the case", [i["ref"] for i in items], ["TC-9"])
    check_eq("K-N8.22 a requirement-only debt is keyed by its R-n",
             [i["ref"] for i in CD.build_left_items([{"kind": "unconfirmed_expectation", "case": "", "ref": "R-4",
                                                      "requirements": ["R-4"]}], facts, DOC)], ["R-4"])
    check_eq("K-N8.22 a `none` kind makes no item", CD.build_left_items([{"kind": "regression", "case": "TC-9"}], facts, DOC), [])
    # the forced breach: the verdict is `after_checks`, the list comes back empty -> no, and says why
    task = story()
    saved = CD.build_left_items
    CD.build_left_items = lambda *a, **k: []
    try:
        doc = run(task)
        check_eq("K-N8.22 forced breach: no", doc["delivery_verdict"], "no")
        check_in("K-N8.22 forced breach: VERDICT_WITHOUT_ITEMS", "VERDICT_WITHOUT_ITEMS", codes(doc))
        check("K-N8.22 forced breach: the no has a reason", bool(doc["reasons"]), str(doc["reasons"]))
        check_eq("K-N8.22 forced breach: never shipped as the third word", doc["delivery_ready"], False)
    finally:
        CD.build_left_items = saved
        cleanup(task.parent)
    # the property over every variant the file builds: after_checks => a counting item exists
    for build in (lambda t: None, red, analyst_ne):
        task = story()
        try:
            build(task)
            doc = run(task)
            check(f"K-N8.22 {doc['delivery_verdict']}: the third word has its item",
                  doc["delivery_verdict"] != "after_checks" or DV.count_items(doc["left_items"]) > 0)
        finally:
            cleanup(task.parent)


# --- the owner's amendment (03.10): the null outcomes in two sections -------------------------------------------

SKIPPED_HEAD = "## Skipped by the plan (approved at gate A)"
NOT_PROVEN_HEAD = "## Not proven, and what it costs"


def _blocks_of(task: Path) -> tuple:
    text = (task / "test-report.md").read_text(encoding="utf-8")
    found = G.find_blocks(text)
    return text, found["skipped-by-plan"][2], found["not-proven"][2]


def _line(block: str, requirement: str) -> str:
    return next(ln for ln in block.splitlines() if ln.startswith(f"- **{requirement}**"))


def k_amendment_the_section_split() -> None:
    """Owner amendment 03.10 (FR-12: the ledger's own facts, never wording). One key per section with its negative twin:
    a plan-skipped case under "Not proven" is red, a NOT_EXECUTED case under "Skipped by the plan" is red."""
    task = story()
    try:
        doc = run(task)
        res = RF.write(task)
        check("amendment: --write", res["ok"], str(res["lines"]))
        text, skipped, notproven = _blocks_of(task)
        # --- the key of "Skipped by the plan": a plan decision, with the plan's reason verbatim
        check_eq("amendment: the section opens with its heading, as the template carries it", skipped.splitlines()[0], SKIPPED_HEAD)
        template = (Path(G.__file__).resolve().parents[1] / "references" / "templates" / "test-report.md").read_text(encoding="utf-8")
        check_in("amendment: the template carries that heading verbatim", SKIPPED_HEAD, template)
        check_in("amendment: and the other one", NOT_PROVEN_HEAD, template)
        check_in("amendment: R-3 (a plan `skip`) stands under it", "- **R-3** — cosmetic, outside the diff, no user impact recorded "
                 "(plan row TS-3, skipped by the plan) :", skipped)
        check_not_in("amendment: and not under Not proven", "R-3", notproven)
        # --- the key of "Not proven": checks that could not execute, each with what stopped it
        check_eq("amendment: Not proven opens with its heading", notproven.splitlines()[0], NOT_PROVEN_HEAD)
        # HF2-6 (6a): R-5's test is one the person took (TC-005, handed) and the run holds no row for it, so its trace reads
        # `wait`, no longer `pass` for a test that never ran - and a requirement that waits stands under "Not proven" (P21: it
        # stays under `after_checks`, which the next key's verdict word pins), so the list gains R-5; the first two are as before.
        check_eq("amendment: R-2 (code's NOT_EXECUTED row), R-4 (a manual-human case nobody evidenced) and R-5 (a test the person "
                 "took, no run row: it waits) stand under it",
                 [ln.split("**")[1] for ln in notproven.splitlines() if ln.startswith("- **")], ["R-2", "R-4", "R-5"])
        check_in("amendment: R-2 says what stopped it, in the role's own words", "what stopped it: the order record page returned 503 "
                 "for the whole window", _line(notproven, "R-2"))
        check_in("amendment: R-4 says what stopped it", "what stopped it: no evidence package was recorded for it", _line(notproven, "R-4"))
        check_not_in("amendment: neither stands under Skipped by the plan", "R-2", skipped)
        check_eq("amendment: --check recognises both headings and finds nothing", RF.check(task), [])
        check_eq("amendment: the verdict logic is untouched", doc["delivery_verdict"], "after_checks")
        # --- the negative twins: a line under the wrong heading is red (the blocks are code's: byte-equal to a fresh render)
        r3, r2 = _line(skipped, "R-3"), _line(notproven, "R-2")
        wrong = text.replace(r3 + "\n", "", 1).replace(NOT_PROVEN_HEAD + "\n\n", NOT_PROVEN_HEAD + "\n\n" + r3 + "\n", 1)
        (task / "test-report.md").write_text(wrong, encoding="utf-8")
        found = RF.check(task)
        check("amendment NEG: a plan-skipped case rendered under `Not proven` is red",
              any("block `not-proven` differs" in p for p in found) and any("block `skipped-by-plan` differs" in p for p in found), str(found))
        wrong = text.replace(r2 + "\n", "", 1).replace(SKIPPED_HEAD + "\n\n", SKIPPED_HEAD + "\n\n" + r2 + "\n", 1)
        (task / "test-report.md").write_text(wrong, encoding="utf-8")
        found = RF.check(task)
        check("amendment NEG: a NOT_EXECUTED case rendered under `Skipped by the plan` is red",
              any("block `skipped-by-plan` differs" in p for p in found), str(found))
        RF.write(task)
        check_eq("amendment: --write puts both back, byte for byte", _blocks_of(task)[0], text)
        # a requirement the plan skipped, in its own section even when the plan row is the only thing known
        check_eq("amendment: the ledger holds the plan skip as a none-kind row (it blocks nothing, FR-21)",
                 [r["state"] for r in doc["rows"] if r["ref"] == "TS-3"], ["skipped:cosmetic, outside the diff, no user impact recorded"])
    finally:
        cleanup(task.parent)
    # a gate A waiver is the plan's decision the person approved; their words are the reason, verbatim. A gate B one is not.
    for gate, section in (("A", "skipped"), ("B", "not-proven")):
        task = story()
        try:
            edit(task, "pipeline.json", lambda p: p.update(gate_waivers=[
                {"gate": gate, "requirement": "R-4", "decision": "not this release, the token lab is closed",
                 "at": "2026-10-03T10:00:00Z", "by": "human"}]))
            doc = run(task)
            RF.write(task)
            _text, skipped, notproven = _blocks_of(task)
            here, there = (skipped, notproven) if section == "skipped" else (notproven, skipped)
            check_in(f"amendment: a gate {gate} waiver puts R-4 under `{section}`", "- **R-4**", here)
            check_not_in(f"amendment: and not under the other section (gate {gate})", "- **R-4**", there)
            if section == "skipped":
                check_in("amendment: with their words verbatim", 'your words at gate A: "not this release, the token lab is closed"', skipped)
            check_eq(f"amendment: the verdict logic is unchanged by the grouping (gate {gate}: the row is a deferral with their words)",
                     doc["delivery_verdict"], "after_checks")
            check_eq(f"amendment: --check is clean (gate {gate})", RF.check(task), [])
        finally:
            cleanup(task.parent)
    # a red under a waiver stays `no`, and is in neither section (a bug is not a null outcome)
    task = story()
    try:
        red(task)
        edit(task, "pipeline.json", lambda p: p.update(gate_waivers=[
            {"gate": "A", "requirement": "R-1", "decision": "accept the gap", "at": "2026-10-03T10:00:00Z", "by": "human"}]))
        doc = run(task)
        RF.write(task)
        _text, skipped, notproven = _blocks_of(task)
        check_eq("amendment: a red under a gate A waiver is still `no`", doc["delivery_verdict"], "no")
        # HF2-6 (6a, 6b): the failed row of TC-001 is joined now, so R-1's trace reads `blocked`, and the waiver covers a test the
        # plan SKIPS, not one that ran and failed: R-1 is never "skipped by the plan". It is not proven, and the report says so
        # under "Not proven" with its row's basis - before, it was in neither section because the trace read `pass`.
        check_not_in("amendment: and R-1 is not a skipped requirement", "- **R-1**", skipped)
        check_in("amendment: ... it stands under Not proven, with the basis of its red row (the test ran and failed)",
                 "red run", _line(notproven, "R-1"))
    finally:
        cleanup(task.parent)


# --- attempt 2 (critic t-401): F1-F6 --------------------------------------------------------------------------------

def hand(task: Path, case: str = "TC-001", **extra) -> None:
    """The manifest hands `case` to the person (an `unresolved[]` row, with the command they run)."""
    edit(task, "work/automation-manifest.json", lambda m: m["unresolved"].append(
        dict({"case": case, "reason": "handed_to_person", "detail": "run it: npm test"}, **extra)))


def env_row(task: Path, **extra) -> None:
    """TC-001 failed and an analyst-style row (an instance id, no `case` field) triages it ENV_ISSUE."""
    edit(task, "work/run-report.json", lambda r: r["results"][0].update(result="failed", attempt_id="a1"))
    row = {"instance_id": "tests/test_coupon.py::test_cap_rejected", "attempt_id": "a1", "verdict": "ENV_ISSUE",
           "our_signal": "the stand returned 503", "env_fix": "restart", "unverified": "yes"}
    row.update(extra)
    edit(task, "work/triage.json", lambda t: t["triage"].append(row))


def answered(task: Path, text: str = "accept - the person wrote: TC-001: accept", case: str = "TC-001") -> None:
    """The pipeline's own record of the person's gate B answer to the stand gap of `case` (what the driver writes)."""
    edit(task, "pipeline.json", lambda p: p.update(stage_overrides=[
        {"stage": "S9", "match": f"stand gap: {case}", "decision": text, "at": "2026-10-03T10:00:00Z", "by": "human"}]))


def tc5_fails(task: Path) -> None:
    """TC-005 (handed for android) RAN, on its own instance, and failed; the analyst triages it APP_BUG."""
    edit(task, "work/run-report.json", lambda r: r["results"].append(
        {"test": "tests/e2e/coupon.android.spec.ts::TC-005", "case": "TC-005", "result": "failed", "attempt_id": "a1"}))
    edit(task, "work/triage.json", lambda t: t["triage"].append(
        {"instance_id": "tests/e2e/coupon.android.spec.ts::TC-005", "attempt_id": "a1", "verdict": "APP_BUG"}))


def k_f1_a_failure_outranks_a_handoff() -> None:
    """K-N8.27 (attempt 2, F1, P21): an OBSERVED failure always outranks a hand-off. No row whose run result is `failed:*` is
    restated as `not_executed:handed_to_person`, no case with a failed result reads kind `handed`, and `after_checks` / `yes`
    stay out of reach while a failed row with no recorded person's decision exists - EXCEPT a `failed:ASSERT_STRICTER` row
    whose triage row carries its control experiment (HF2-18, N6: the one observed failure that reaches `after_checks` on the
    analyst's word alone; without the experiment it is a `triage:` reason, so `no` - `test_triage_control.py`)."""
    def rows_of(doc: dict, case: str) -> list:
        return [r["state"] for r in doc["rows"] if case in str(r.get("detail"))]

    def handed_items(doc: dict, case: str) -> list:
        return [i for i in doc["left_items"] if i.get("kind") == "handed" and i.get("case") == case]

    task = story()
    try:
        doc = run(task)
        check_eq("K-N8.27 control: TC-005 handed, no failure -> after_checks, as before", doc["delivery_verdict"], "after_checks")
        check_eq("K-N8.27 control: the handed case still has its item", len(handed_items(doc, "TC-005")), 1)
    finally:
        cleanup(task.parent)
    task = story()
    try:
        red(task)
        check_eq("K-N8.27 control: red APP_BUG alone -> no", run(task)["delivery_verdict"], "no")
        hand(task, "TC-001")
        doc = run(task)
        check_eq("K-N8.27 red APP_BUG + the same case handed -> no", doc["delivery_verdict"], "no")
        check("K-N8.27 ... and the reason names the APP_BUG", any("failed:APP_BUG" in r for r in doc["reasons"]), str(doc["reasons"]))
        check("K-N8.27 ... no row of the case was restated as handed",
              not [s for s in rows_of(doc, "TC-001") if s == "not_executed:handed_to_person"], str(rows_of(doc, "TC-001")))
        check_eq("K-N8.27 ... and the case reads no `handed` item", handed_items(doc, "TC-001"), [])
        gap = [r for r in G_walk(task) if r["requirement"] == "R-1"][0]
        check_eq("K-N8.27 ... the traceability chain ends in the failed result, not in a hand-off gap",
                 (gap["outcome"], gap["gaps"]), ("executed_failed", []))
    finally:
        cleanup(task.parent)
    task = story()
    try:
        tc5_fails(task)
        doc = run(task)
        check_eq("K-N8.27 TC-005 handed for android and failing APP_BUG on its own instance -> no", doc["delivery_verdict"], "no")
        check("K-N8.27 ... the reason names it", any("TC-005" in r and "failed:APP_BUG" in r for r in doc["reasons"]),
              str(doc["reasons"]))
        check_eq("K-N8.27 ... and TC-005 reads no `handed` item", handed_items(doc, "TC-005"), [])
    finally:
        cleanup(task.parent)
    # a case with several instances, one failed and one handed
    task = story()
    try:
        red(task)
        edit(task, "work/automation-manifest.json", lambda m: m["tests"].append(
            {"case": "TC-001", "plan_row": "TS-1", "file": "tests/test_coupon_b.py", "marker": "TC-001", "status": "written",
             "critic_verdict": "approved"}))
        hand(task, "TC-001")
        check_eq("K-N8.27 edge: several instances, one failed and one handed -> no", run(task)["delivery_verdict"], "no")
    finally:
        cleanup(task.parent)
    # a failed row triaged ENV_ISSUE: the person's recorded accept lifts the failure, the hand-off then stands
    task = story()
    try:
        env_row(task)
        hand(task, "TC-001")
        check_eq("K-N8.27 edge: ENV_ISSUE + hand-off, the person has not answered -> no", run(task)["delivery_verdict"], "no")
    finally:
        cleanup(task.parent)
    task = story()
    try:
        env_row(task)
        hand(task, "TC-001")
        answered(task)
        doc = run(task)
        check_eq("K-N8.27 edge: ENV_ISSUE + a recorded gate B accept + a hand-off -> after_checks", doc["delivery_verdict"], "after_checks")
        check_eq("K-N8.27 ... the hand-off stands as an item", len(handed_items(doc, "TC-001")), 1)
    finally:
        cleanup(task.parent)
    # an empty and an absent unresolved[] list: today's behaviour, unchanged
    for label, change in (("empty", lambda m: m.update(unresolved=[])), ("absent", lambda m: m.pop("unresolved", None))):
        task = story()
        try:
            red(task)
            edit(task, "work/automation-manifest.json", change)
            doc = run(task)
            check_eq(f"K-N8.27 edge: red with an {label} unresolved[] -> no, as it always was", doc["delivery_verdict"], "no")
        finally:
            cleanup(task.parent)


def k_g1_a_handoff_restates_only_what_nobody_ran() -> None:
    """K-N8.32 (attempt 3, G1, P21): a hand-off restates ONLY a row whose state prefix is `not_executed` (an ALLOW-list). Every
    observed result and every review verdict keeps its own state, so no row of kind `no` can become kind `handed`."""
    task = story()
    try:
        facts_task = task
        base = run(task)
        handed_rows = [r for r in base["rows"] if r["state"] == "not_executed:handed_to_person"]
        check("K-N8.32 control: a `not_executed` row of a handed case is restated as handed -> after_checks",
              bool(handed_rows) and base["delivery_verdict"] == "after_checks", str(base["rows"]))
        # the table, over mark_handed itself: every state a row can carry, on TC-005's plan row (a handed case)
        for state, restated in (("not_executed:no result recorded for this row's cases", True),
                                ("not_executed:handed_to_person", True), ("not_executed:", True),
                                ("failed:APP_BUG", False), ("failed:ENV_ISSUE", False), ("failed:untriaged", False),
                                ("partial", False), ("error", False), ("review_rejected", False),
                                ("review_unrecognised:maybe", False), ("review_skipped", False), ("not_verified_flaky", False),
                                ("passed_green", False), ("waived:failed:APP_BUG", False), ("waived:impossible", False),
                                ("env_blocked:user", False), ("impossible", False), ("skipped:inconclusive run", False),
                                ("a_state_nobody_knows_today", False)):
            doc = {"rows": [{"ref": "TS-5", "kind": "plan_row", "state": state, "detail": "TC-005"}]}
            got = CD.mark_handed(doc, facts_task)["rows"][0]["state"]
            check_eq(f"K-N8.32 a hand-off over `{state}` -> {'restated as handed' if restated else 'its own state'}",
                     got == "not_executed:handed_to_person" if restated else got == state, True)
    finally:
        cleanup(task.parent)
    # end to end: TC-005's test rejected by the critic, or with a partial result, and handed for android
    task = story()
    try:
        edit(task, "work/automation-manifest.json", lambda m: m["tests"][1].update(critic_verdict="rejected"))
        doc = run(task)
        check_eq("K-N8.32 TC-005's test `critic_verdict: rejected` + handed -> no", doc["delivery_verdict"], "no")
        check("K-N8.32 ... the reason is the review's", any("review_rejected" in r for r in doc["reasons"]), str(doc["reasons"]))
        check("K-N8.32 ... and no row of kind `no` was restated as handed",
              not [r for r in doc["rows"] if r["state"] == "not_executed:handed_to_person" and r["kind"] == "test"], str(doc["rows"]))
    finally:
        cleanup(task.parent)
    task = story()
    try:
        edit(task, "work/run-report.json", lambda r: r["results"].append(
            {"test": "tests/e2e/coupon.android.spec.ts::TC-005", "case": "TC-005", "result": "partial", "attempt_id": "a1"}))
        doc = run(task)
        check_eq("K-N8.32 TC-005 with a `partial` result + handed -> no", doc["delivery_verdict"], "no")
        check("K-N8.32 ... the row keeps its state `partial`", "partial" in [r["state"] for r in doc["rows"]], str(doc["rows"]))
    finally:
        cleanup(task.parent)
    # edges: a handed case with no row at all, and an empty / absent unresolved[] - unchanged
    task = story()
    try:
        hand(task, "TC-099")
        check_eq("K-N8.32 edge: a handed case with no row at all -> unchanged (after_checks)", run(task)["delivery_verdict"], "after_checks")
    finally:
        cleanup(task.parent)
    for label, change in (("empty", lambda m: m.update(unresolved=[])), ("absent", lambda m: m.pop("unresolved", None))):
        task = story()
        try:
            edit(task, "work/automation-manifest.json", change)
            doc = run(task)
            check(f"K-N8.32 edge: an {label} unresolved[] -> no handed row at all", not [
                r for r in doc["rows"] if r["state"] == "not_executed:handed_to_person"], str(doc["rows"]))
        finally:
            cleanup(task.parent)


def G_walk(task: Path) -> list:
    import check_traceability as CT
    return CT.walk(task)["rows"]


def k_f2_the_binding_is_the_contracts() -> None:
    """K-N8.28 (attempt 2, F2, FR-7/FR-57): a gate B answer recorded for a case is found for every triage row
    `contract.bind_triage` binds to that case - an analyst-style row with no `case` field included."""
    task = story()
    try:
        env_row(task)
        doc = run(task)
        check_eq("K-N8.28 negative twin: no recorded answer -> no", doc["delivery_verdict"], "no")
        mine = [r for r in doc["reasons"] if "is ENV_ISSUE" in r]
        check_eq("K-N8.28 ... one reason about the row", len(mine), 1)
        check("K-N8.28 ... that names the four closed answers", all(w in mine[0] for w in ("change", "myself", "run", "accept")), mine[0])
    finally:
        cleanup(task.parent)
    task = story()
    try:
        env_row(task)
        answered(task)
        doc = run(task)
        check_eq("K-N8.28 the analyst-style row (no `case`) + a recorded accept -> after_checks", doc["delivery_verdict"], "after_checks")
        check_eq("K-N8.28 ... with no reason left", doc["reasons"], [])
    finally:
        cleanup(task.parent)
    task = story()
    try:
        env_row(task, instance_id="nowhere::nothing")
        answered(task)
        doc = run(task)
        check_eq("K-N8.28 edge: a row the binding cannot bind to any case -> no", doc["delivery_verdict"], "no")
        check("K-N8.28 ... and the reason says the row could not be matched to a case",
              any("could not be matched to a case" in r for r in doc["reasons"]), str(doc["reasons"]))
    finally:
        cleanup(task.parent)


def k_f3_the_analyst_is_not_the_person() -> None:
    """K-N8.29 (attempt 2, F3): the `decision` field inside triage.json is NOT a person's word (the analyst writes that file).
    Only the pipeline's own record of the gate B answer lifts an ENV_ISSUE row."""
    task = story()
    try:
        env_row(task, decision="accept")
        doc = run(task)
        check_eq("K-N8.29 an ENV_ISSUE row with `decision: accept` and no gate record -> no", doc["delivery_verdict"], "no")
        check("K-N8.29 ... still asking for the person's answer", any("no recorded decision" in r for r in doc["reasons"]),
              str(doc["reasons"]))
        check_eq("K-N8.29 ... and the ledger's own reader finds no answer for the case (a second path to the same word)",
                 CD.env_option_of_case("TC-001", CD.gather(task)), "")
    finally:
        cleanup(task.parent)
    task = story()
    try:
        env_row(task, decision="accept")
        answered(task)
        check_eq("K-N8.29 the same row with the gate record -> after_checks", run(task)["delivery_verdict"], "after_checks")
    finally:
        cleanup(task.parent)
    task = story()
    try:
        env_row(task, decision="accept")
        answered(task, "fix now")
        check_eq("K-N8.29 a gate record that is not one of the four closed answers lifts nothing, whatever the field says",
                 run(task)["delivery_verdict"], "no")
    finally:
        cleanup(task.parent)
    s8 = (SCRIPTS.parent / "skills" / "qa-story" / "phases" / "s8.md").read_text(encoding="utf-8")
    check_not_in("K-N8.29 no role is told to write a `decision` into triage.json", "triage.json` `decision", s8)


def k_f5_the_head_of_a_no_names_what_holds_it() -> None:
    """K-N8.30 (attempt 2, F5, FR-20): the head of a `no` names the first reason the third verdict does NOT cover, in the
    ledger's order - not a candidate the ledger already holds as something left with the person."""
    task = story()
    try:
        red(task)
        doc = run(task)
        check_eq("K-N8.30 setup: the red variant is `no`", doc["delivery_verdict"], "no")
        res = RF.write(task)
        check("K-N8.30 setup: --write", res["ok"], str(res["lines"]))
        head = G.find_blocks((task / "test-report.md").read_text(encoding="utf-8"))["verdict"][2].splitlines()[0]
        check_in("K-N8.30 the head names TS-1's APP_BUG", "Because TS-1 (TC-001) failed in the run - the triage verdict is APP_BUG", head)
        check_not_in("K-N8.30 ... not R-2's one-off check (the third verdict holds it)", "R-2", head.split("Product bugs:")[0])
        # the story is final (`red` ran): the fixture's hand-written appendix says R-1 `pass`, the render now says `blocked`
        # (HF2-6b compares the appendix with a fresh render), so the key pastes the render of THIS state, as the scribe does
        repaste_appendix(task)
        check_eq("K-N8.30 --check passes", RF.check(task), [])
    finally:
        cleanup(task.parent)
    # every candidate is held and the `no` is the factory's own: the residual sentence, never a held requirement's name
    task = story()
    try:
        edit(task, "work/run-report.json", lambda r: r.update(factory_findings=[
            {"entity": "TC-001", "code": "ROW_NOT_JOINED", "detail": "a result row could not be joined"}]))
        doc = run(task)
        check_eq("K-N8.30 edge: a factory finding alone holds the verdict at no", doc["delivery_verdict"], "no")
        RF.write(task)
        head = G.find_blocks((task / "test-report.md").read_text(encoding="utf-8"))["verdict"][2].splitlines()[0]
        check_in("K-N8.30 ... the head is the residual sentence, naming the factory's own bookkeeping",
                 "Because the checks still list open reasons", head.split("Product bugs:")[0])
        check_not_in("K-N8.30 ... never the name of a requirement the third verdict covers", "R-2 (", head.split("Product bugs:")[0])
    finally:
        cleanup(task.parent)


def k_f6_the_scribe_quotes_the_word() -> None:
    """K-N8.31 (attempt 2, F6): the scribe is told three words and to quote the word the check prints, not its exit code
    (`after_checks` exits 1 too)."""
    text = (SCRIPTS.parent / "agents" / "qa-doc-scribe.md").read_text(encoding="utf-8")
    flat = " ".join(text.split())
    check_in("K-N8.31 the charter names the three words", "`delivery_verdict` (`yes`, `after_checks` or `no`)", flat)
    check_in("K-N8.31 ... and says the word, not the exit code, is what is quoted", "never its exit code", flat)
    check_not_in("K-N8.31 the two-valued reading is gone", "exit 0/1", flat)
    check_not_in("K-N8.31 ... and so is `fills delivery_ready and reasons`", "fills `delivery_ready` and `reasons`", flat)


def k_tq1_18_a_refused_base_holds_delivery() -> None:
    """TQ1-18 D3-K16 (kills M-D3-7: the `refused_base` row removed from `delivery-verdict-kinds.json`): the new ledger state reads as its
    own kind, a reason reaches the person, the verdict is `no`; the control state of the same prefix stays `decided_elsewhere`."""
    state = "not_verified:oracle_on_refused_base"
    check_eq("D3-K16: the kind of the state is `refused_base`, not the prefix's `decided_elsewhere`", DV.kind_of_state(state), "refused_base")
    check_eq("... of the factory's own record", DV.owner_of_kind("refused_base"), "factory")
    ledger = {"rows": [{"ref": "TC-18", "kind": "plan_row", "state": state, "detail": "TC-18 - the base was a refusal"}]}
    reasons = CD.ledger_reasons(ledger)
    check_eq("F-4: `reason_owner` of the printed reason is the factory (AR-27), not the family default `product`",
             CD.reason_owner(reasons[0]) if reasons else "", "factory")
    check_eq("F-4: the same through the typed prefix table", CD.OWNER_BY_LEDGER_STATE.get("not_verified"), "factory")
    check("D3-K16: `ledger_reasons` holds a line for the row", len(reasons) == 1 and state in reasons[0], str(reasons))
    kinds = [rec["kind"] for rec in CD.ledger_records(ledger)]
    check_eq("D3-K16: `decide` says `no`", DV.decide(kinds)[0], "no")
    control = {"rows": [{"ref": "TC-19", "kind": "plan_row", "state": "not_verified:missing_sensitivity_proof", "detail": "x"}]}
    check_eq("CONTROL: `missing_sensitivity_proof` still decides nothing", (CD.ledger_reasons(control), DV.decide(
        [rec["kind"] for rec in CD.ledger_records(control)])[0]), ([], "yes"))


def k_pc5_s_b_after_checks_one_item_per_case() -> None:
    """t-2181 PC-5 (S-b, S15): a green run met only a substituted side -> `after_checks`, ONE counting item per case under kind
    `on_substitute`, listing its tests and the re-pass `how`; a stamp with `sides_unknown` -> kind `sides_unknown` (owner factory).
    Controls: the same story unstamped is not read; a red on the substitute is `no` (a bug is never softened)."""
    def stamp(task: Path, **fields) -> None:
        edit(task, "work/run-report.json", lambda r: r["results"][0].update(fields))

    def on(doc: dict, kind: str) -> dict:
        return {i["ref"]: i for i in doc["left_items"] if kind in (i.get("kinds") or [])}

    task = story()
    stamp(task, sides_met={"ui": "real", "backend": "substituted"})
    edit(task, "pipeline.json", lambda p: p.update(sides={"ui": {"reality": "real"}, "backend": {"reality": "substituted"}}))
    doc = run(task)
    items = on(doc, "on_substitute")
    check_eq("PC-5 S-b the green case is ONE item under `on_substitute`", sorted(items), ["TC-001"])
    item = items.get("TC-001") or {}
    check("PC-5 S-b the item counts and the verdict is the third word", item.get("counts") is True and doc["delivery_verdict"] == "after_checks",
          f"{doc['delivery_verdict']} {item}")
    check_in("PC-5 S-b the re-pass `how` names the side that is not real", "backend", item.get("how", ""))
    check_in("PC-5 S-b ... and starts as a how-line", "How: run", item.get("how", ""))
    check("PC-5 S-b the item lists the case's test (never an instance id the person cannot read)", bool(item.get("tests")), str(item))
    check_eq("PC-5 S-b the ledger row of the case reads `not_verified:on_substitute`",
             [r["state"] for r in doc.get("rows", []) if r.get("ref") == "TS-1"], ["not_verified:on_substitute"])
    unstamped = run(story())
    check_eq("control: the unstamped story has no such item", on(unstamped, "on_substitute"), {})
    stamp(task, sides_unknown="the registry could not be read")
    check_eq("PC-5 S12 the stamp's `sides_unknown` is kind `sides_unknown`, owner factory",
             (sorted(on(run(task), "sides_unknown")), DV.owner_of_kind("sides_unknown")), (["TC-001"], "factory"))
    red_task = story()
    red(red_task)
    stamp(red_task, sides_met={"backend": "substituted"})
    check_eq("control: a red on the substitute is `no`", run(red_task)["delivery_verdict"], "no")


def main() -> None:
    k_pc5_s_b_after_checks_one_item_per_case()
    k_tq1_18_a_refused_base_holds_delivery()
    k_n8_1_every_row_of_the_table()
    k_n8_2_text_is_never_read()
    k_n8_3_not_executed_battery()
    k_n8_4_regression()
    k_n8_5_deferred()
    k_n8_6_env_words()
    k_n8_14_word_of()
    k_n8_18_one_list()
    k_n8_19_ready_chip()
    k_n8_20_fixture()
    k_amendment_the_section_split()
    k_n8_22_never_without_items()
    k_f1_a_failure_outranks_a_handoff()
    k_g1_a_handoff_restates_only_what_nobody_ran()
    k_f2_the_binding_is_the_contracts()
    k_f3_the_analyst_is_not_the_person()
    k_f5_the_head_of_a_no_names_what_holds_it()
    k_f6_the_scribe_quotes_the_word()
    finish("test_third_verdict")


if __name__ == "__main__":
    main()
