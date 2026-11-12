"""check_delivery.py — the aggregator. It invents nothing; it collects, and it defaults to no.

TQ1-20 (S6.03) keys V-1..V-6, V-8, V-10, V-16 are the last functions of this file (`v_1_to_4_verdict_by_branch`, `v_10_and_16_word_and_case_item`).
Mutations named, NOT run; one killing file each (this one):
  m14 delivery-verdict-kinds.json: `branch_lost` -> `verdict: none`         -> V-1
  m15 _exclusions: `person` with no check of the answer's binding to the branch -> V-5 (at the verdict)
  m16 build_left_items: the key by `requirements[0]` before `item_key`     -> V-6
  m24 the case's own kind suppresses the branch's record again            -> V-16
"""
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from harness import (  # noqa: E402
    BAD, GOOD, SCRIPTS, check, check_eq, check_in, check_not_in, cleanup, finish, run_script,
    temp_project,
)

sys.path.insert(0, str(SCRIPTS))
import check_delivery as D  # noqa: E402
import contract as C  # noqa: E402


def coverage_gap_print() -> None:
    """RD1-21: the CLI's "nothing here says the product is not ready" is printed over bookkeeping only - never over a
    behaviour no test proves (the ledger's one predicate, `factory_coverage_gaps`)."""
    import contextlib
    import io
    import ledger as L
    cov = {"code": L.COVERAGE_GAP_CODE, "entity": "OB-1", "owner": "factory", "detail": "coverage: OB-1 — evidence incomplete"}
    book = {"code": "FACTORY_DEFECT", "entity": "x", "owner": "factory", "detail": "factory: a row the reducer could not join"}

    def printed(records) -> str:
        doc = {"rows": [], "reasons": [r["detail"] for r in records], "reason_records": records, "delivery_ready": False,
               "delivery_verdict": "no", "blocked_by": ["factory"], "left_items": [], "factory_findings": []}
        real, argv, out = D.assess, sys.argv, io.StringIO()
        D.assess = lambda artifacts, **kw: doc
        sys.argv = ["check_delivery.py", str(GOOD)]
        try:
            with contextlib.redirect_stdout(out):
                try:
                    D.main()
                except SystemExit:
                    pass
        finally:
            D.assess, sys.argv = real, argv
        return out.getvalue()
    check_in("control: a bookkeeping-only list is told it is the factory's", "Nothing here says the product is not ready", printed([book]))
    over = printed([cov, book])
    check_not_in("a coverage gap among the factory's reasons is not reassured over", "Nothing here says the product is not ready", over)
    check_in("and the heading's first line says it stays unproven", L.factory_coverage_line(1), over)


def main() -> None:
    coverage_gap_print()
    root = temp_project("qa-factory-delivery-")
    good_set, bad_set = root / "good", root / "bad"
    shutil.copytree(GOOD, good_set)
    shutil.copytree(BAD, bad_set)
    # --- the good set delivers ------------------------------------------------------------
    p = run_script("check_delivery.py", good_set)
    check_eq("good: exit 0", p.returncode, 0)
    check_in("good: delivery_ready yes", "delivery_ready: yes", p.stdout)
    good = json.loads((good_set / "work" / "ledger.json").read_text(encoding="utf-8"))
    check_eq("good: the verdict lands in ledger.json", good["delivery_ready"], True)
    check_eq("good: with no reasons", good["reasons"], [])
    check_in("good: and in ledger.md", "`delivery_ready: yes`",
             (good_set / "work" / "ledger.md").read_text(encoding="utf-8"))

    # --- the bad set does not, and says why ------------------------------------------------
    p = run_script("check_delivery.py", bad_set)
    check_eq("bad: exit 1", p.returncode, 1)
    check_in("bad: delivery_ready no", "delivery_ready: no", p.stdout)
    bad = json.loads((bad_set / "work" / "ledger.json").read_text(encoding="utf-8"))
    check_eq("bad: the verdict lands in ledger.json", bad["delivery_ready"], False)
    check("bad: at least three reasons", len(bad["reasons"]) >= 3, str(bad["reasons"]))
    reasons = "\n".join(bad["reasons"])
    check_in("bad: the undecided unresolved case is named", "TC-003", reasons)
    check_in("bad: the unfixed flake is named", "FLAKY and was not fixed", reasons)
    check_in("bad: the requirement with no outcome is named", "R-4 has no terminal outcome", reasons)
    check_in("bad: the missing critic verdict is named", "no critic verdict", reasons)
    check_in("bad: the open subtask is named", "QA-1-2", reasons)
    check_in("bad: the gate-B consequence is spelled out", "deliver with known gaps", p.stdout)

    # --- every reason comes from a check that exists elsewhere ------------------------------
    check_eq("witness_reasons is quiet on the good manifest", D.witness_reasons(good_set), [])
    check_eq("completeness_reasons is quiet on the good set", D.completeness_reasons(good_set), [])
    check_eq("run_reasons is quiet on the good set", D.run_reasons(good_set), [])
    check_eq("triage_reasons is quiet on the good set", D.triage_reasons(good_set), [])
    check("completeness_reasons speaks on the bad set", bool(D.completeness_reasons(bad_set)))
    check("triage_reasons speaks on the bad set", bool(D.triage_reasons(bad_set)))

    try:
        art = root / "qa-factory" / "artifacts" / "QA-1"
        shutil.copytree(GOOD, art)

        # 1. A run that never executed cannot deliver, however green the rest looks.
        report = C.load_json(art / "work" / "run-report.json")
        # `failed` is deliverable HERE — a failure is allowed to ship once it carries a triage
        # verdict, and that is triage_reasons' job, not this one's. Everything else is not.
        for status, deliverable in (("passed", True), ("failed", True), ("env_blocked", False),
                                    ("not_executed", False), ("broken_run", False), ("timeout", False)):
            report["execution_status"] = status
            (art / "work" / "run-report.json").write_text(json.dumps(report), encoding="utf-8")
            reasons = D.run_reasons(art)
            check_eq(f"execution_status {status} -> {'deliverable' if deliverable else 'blocked'}",
                     not reasons, deliverable)
        report["execution_status"] = "wishful"
        (art / "work" / "run-report.json").write_text(json.dumps(report), encoding="utf-8")
        check_in("an invented execution_status is rejected", "outside", "\n".join(D.run_reasons(art)))

        # K-N8.21 (t-305 N8, Q19, R3): S6 closed on a code-only receipt - nothing to execute, or everything handed - and
        # `not_executed` is what it left on purpose: the run decides nothing, the cases do. Only that status, only with the receipt.
        import s7_pretriage
        real_receipt = s7_pretriage.s6_closed_by_code
        try:
            for status, receipt, refused in (("not_executed", True, False), ("not_executed", False, True),
                                             ("env_blocked", True, True), ("broken_run", True, True), ("timeout", True, True),
                                             ("passed", True, False), ("failed", False, False)):
                report["execution_status"] = status
                (art / "work" / "run-report.json").write_text(json.dumps(report), encoding="utf-8")
                s7_pretriage.s6_closed_by_code = lambda root, said=receipt: said
                said = D.run_reasons(art)
                check_eq(f"K-N8.21 execution_status {status} with{'' if receipt else 'out'} the S6 code-only receipt -> "
                         f"{'refused' if refused else 'no reason'}", bool(said), refused)
                if refused and status == "not_executed":
                    check_in("K-N8.21 and without the receipt it is today's text", "only ['passed', 'failed'] can deliver",
                             "\n".join(said))
        finally:
            s7_pretriage.s6_closed_by_code = real_receipt
        report["execution_status"] = "passed"
        (art / "work" / "run-report.json").write_text(json.dumps(report), encoding="utf-8")

        # 2. A missing run report is a reason, not a crash.
        (art / "work" / "run-report.json").unlink()
        check_in("a missing run-report.json is a reason", "run-report.json is missing",
                 "\n".join(D.run_reasons(art)))

        # 3. A FLAKY that WAS fixed stops blocking delivery.
        shutil.copy(GOOD / "work" / "run-report.json", art / "work" / "run-report.json")
        (art / "work" / "triage.json").write_text(json.dumps({"triage": [{
            "test": "tests/test_coupon.py::test_cap_rejected", "verdict": "FLAKY",
            "evidence": "evidence/reruns.json", "mechanism": "timing", "reruns": 5,
            "fix_rounds": 1, "fix_result": "fixed"}]}), encoding="utf-8")
        check_eq("a fixed flake is not a delivery reason", D.triage_reasons(art), [])
        doc = D.assess(art)
        check_eq("and the set still delivers", doc["delivery_ready"], True)

        # 4. An ENV_ISSUE with no recorded decision blocks; with one, it does not. t-305 N8 attempt 2 (F2, F3): the row is
        # bound to its failure by `contract.bind_triage` (so the run report holds the failing test), and the decision is the
        # pipeline's own record of the person's gate B answer - triage.json is the analyst's file and decides nothing.
        report = json.loads((GOOD / "work" / "run-report.json").read_text(encoding="utf-8"))
        report["results"][0].update(result="failed", attempt_id="a1")
        (art / "work" / "run-report.json").write_text(json.dumps(report), encoding="utf-8")
        pipeline_path = art / "pipeline.json"
        pipeline_was = pipeline_path.read_text(encoding="utf-8") if pipeline_path.is_file() else None

        def triage_with(**extra) -> None:
            (art / "work" / "triage.json").write_text(json.dumps({"triage": [dict({
                "instance_id": "tests/test_coupon.py::test_cap_rejected", "attempt_id": "a1", "verdict": "ENV_ISSUE",
                "evidence": "evidence/env.json"}, **extra)]}), encoding="utf-8")

        def answer_recorded(text) -> None:
            pipeline = json.loads(pipeline_was) if pipeline_was else {}
            pipeline["stage_overrides"] = [] if text is None else [
                {"stage": "S9", "match": "stand gap: TC-001", "decision": text, "at": "2026-10-03T10:00:00Z", "by": "human"}]
            pipeline_path.write_text(json.dumps(pipeline), encoding="utf-8")
        triage_with()
        answer_recorded(None)
        check_in("an undecided ENV_ISSUE blocks", "no recorded decision", "\n".join(D.triage_reasons(art)))
        answer_recorded("accept - the person wrote: TC-001: accept")
        check_not_in("a decided ENV_ISSUE (the person's recorded gate B answer, one of the card's closed words) does not",
                     "no recorded decision", "\n".join(D.triage_reasons(art)))
        # t-305 N8 (F5): ANY non-empty value used to pass ("fix now" read as accepted); only the card's words are a decision now
        for said in ("fix now", "yes", "resolved", "I accept the risk, agreed at gate B"):
            answer_recorded(said)
            check_in(f"an ENV_ISSUE whose recorded answer reads `{said}` is still undecided", "no recorded decision",
                     "\n".join(D.triage_reasons(art)))
        # F3: the `decision` field of triage.json is the analyst's, not the person's: with no gate record it lifts nothing
        answer_recorded(None)
        for fields in ({"decision": "accept"}, {"resolved": True, "accepted_by": "someone"}):
            triage_with(**fields)
            check_in(f"F3: a triage row carrying {sorted(fields)} and no gate record is still undecided", "no recorded decision",
                     "\n".join(D.triage_reasons(art)))
        # F2: a row the binding gives no failure is a reason that says so, never a silent pass
        triage_with(instance_id="nowhere::nothing")
        check_in("F2: a row no failure binds to says it could not be matched to a case", "could not be matched to a case",
                 "\n".join(D.triage_reasons(art)))
        if pipeline_was is not None:
            pipeline_path.write_text(pipeline_was, encoding="utf-8")
        else:
            pipeline_path.unlink(missing_ok=True)
        shutil.copy(GOOD / "work" / "run-report.json", art / "work" / "run-report.json")

        # 5. The case lifecycle: an approved, green test whose case file never moved out of
        # Draft is a contradiction, not a detail — the coverage map counts that frontmatter.
        case = art / "work" / "test-cases" / "checkout" / "TC-001.md"
        original = case.read_text(encoding="utf-8")
        check_eq("an Automated case is quiet", D.lifecycle_reasons(art), [])
        for status in ("Draft", "Review", "Approved"):
            case.write_text(original.replace("status: Automated", f"status: {status}"), encoding="utf-8")
            said = "\n".join(D.lifecycle_reasons(art))
            check_in(f"a green test whose case says {status} blocks", "TC-001", said)
            check_in(f"and the message names the owner ({status})", "step 8b", said)
        case.write_text(original.replace("status: Automated", "status: Draft"), encoding="utf-8")
        check_eq("and the aggregator refuses delivery for it",
                 D.assess(art)["delivery_ready"], False)
        case.write_text(original, encoding="utf-8")
        check_eq("restoring the transition clears it", D.lifecycle_reasons(art), [])

        # A case nobody approved is nobody's contradiction: the rule fires on the verdict.
        manifest_path = art / "work" / "automation-manifest.json"
        manifest = C.load_json(manifest_path)
        manifest["tests"][0]["critic_verdict"] = "rejected"
        manifest["tests"][0]["status"] = "red"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        case.write_text(original.replace("status: Automated", "status: Draft"), encoding="utf-8")
        check_eq("a rejected test leaves the case status alone", D.lifecycle_reasons(art), [])
    finally:
        cleanup(root)

    # --- FTR-13: deferred_by_decision must block delivery ----------------------------------
    # deferred_by_decision is a terminal traceability outcome (check_traceability.py clears
    # the chain for it) but the default-NO contract means an explicitly deferred requirement
    # must NOT satisfy Gate B without a deliver_with_risks override.  Before the fix, this
    # ledger row produced no blocking reason and delivery_ready would reach True incorrectly.
    deferred_row = {"ref": "TC-010", "state": "deferred_by_decision:gate A", "detail": "waived at gate A"}
    reasons_with_deferred = D.ledger_reasons({"rows": [deferred_row]})
    check("FTR-13: deferred_by_decision is a blocking ledger state", bool(reasons_with_deferred),
          "ledger_reasons returned empty — deferred_by_decision not in blocking set; "
          "check_delivery.py line 267 must include it")
    check_in("FTR-13: the reason names the deferred row", "TC-010", "\n".join(reasons_with_deferred))
    check_in("FTR-13: the reason names the state", "deferred_by_decision",
             "\n".join(reasons_with_deferred))
    # A ledger row with a bare deferred_by_decision (no colon suffix) must also block.
    bare_row = {"ref": "TC-011", "state": "deferred_by_decision", "detail": "no gate recorded"}
    check("FTR-13: bare deferred_by_decision also blocks", bool(D.ledger_reasons({"rows": [bare_row]})))

    # FTR-13 e2e: assess() must return delivery_ready=False for a deferred row -----------
    # The unit assertions above test ledger_reasons() in isolation.  This call exercises the
    # full chain: plan_row_state() → ledger rows → ledger_reasons() → assess() verdict.
    root_deferred = temp_project("qa-factory-delivery-deferred-")
    try:
        art_deferred = root_deferred / "qa-factory" / "artifacts" / "QA-1"
        shutil.copytree(GOOD, art_deferred)
        # TC-001 maps to plan row TS-1.  Adding it to unresolved[] with a decided reason
        # makes plan_row_state() short-circuit to deferred_by_decision before consulting
        # run results — the exact code path the FTR-13 fix guards.
        mpath = C.artifact(art_deferred, "automation-manifest.json")
        mdata = C.load_json(mpath)
        mdata.setdefault("unresolved", []).append(
            {"case": "TC-001", "reason": "deferred_by_decision:gate A"}
        )
        mpath.write_text(json.dumps(mdata, ensure_ascii=False), encoding="utf-8")
        deferred_doc = D.assess(art_deferred)
        check_eq("FTR-13 e2e: deferred_by_decision row makes delivery_ready False",
                 deferred_doc["delivery_ready"], False)
        check("FTR-13 e2e: the reason names the deferred case",
              any("TC-001" in r and "deferred_by_decision" in r
                  for r in deferred_doc["reasons"]),
              str(deferred_doc["reasons"]))
    finally:
        cleanup(root_deferred)

    receipt_in_the_binding_only()
    levels_in_delivery()
    coverage_of_an_unverified_test()
    an_unconfirmed_expectation_holds_nothing()
    a_whole_case_unconfirmed_row_is_a_debt_not_a_hold()
    gate_b_triage_reads_the_one_definition()
    triage_rows_bind_by_spelling_one_side_at_a_time()
    triage_attempts_and_legacy_reports()
    a_red_run_does_not_also_ask_for_the_stamp()
    the_record_text_carries_the_repair_limit()
    a_case_taken_by_hand_is_handed()
    a_case_taken_by_hand_closes_its_requirement()
    a_handed_case_with_a_plan_obligation_is_no_coverage_reason()
    a_case_handed_through_the_door_reaches_gate_b_with_its_steps()
    a_then_handed_beside_an_unprobed_test_keeps_every_then()
    a_blocked_item_lists_only_its_blocked_thens()
    a_mixed_item_lists_the_thens_each_record_leaves()
    a_failed_case_keeps_the_then_the_person_took()
    a_red_test_is_not_asked_for_a_sensitivity_proof()
    a_test_changed_after_its_run_is_the_persons_only_without_a_stand()
    rh1_9_no_flag_reader_without_a_writer()
    v_1_to_4_verdict_by_branch()
    v_10_and_16_word_and_case_item()
    g2_3_the_fr22_road()
    awaiting_story_reads_one_awaiting_implementation_record()
    stopped_story_reads_awaiting_implementation()
    first_look_stop_reads_awaiting_implementation()
    a_diff_story_pending_implementation_is_not_the_awaiting_kind()
    finish("test_check_delivery")


GROUNDING_TABLE = """schema_version: 1
implementation_source: diff
rows:
  - id: G-1
    requirements: [R-1]
    risks:
      - id: K-1
        hypothesis: "null at src/app.py:10"
      - id: K-2
        hypothesis: "off by one at src/app.py:14"
      - id: K-3
        hypothesis: "stale cache at src/app.py:18"
"""
CANDIDATE_ROW = ("| R-4 | The coupon cap check is skipped for guests | derived | bug:candidate-defect | yes | - | "
                 "current-code:src/app.py:30 |\n")
Q9 = {"id": "Q9", "question": "Which total does the cart show?", "source_says": "", "severity": "major",
      "readings": [{"id": "a", "reading": "net"}, {"id": "b", "reading": "gross"}]}


def fr22_story(root: Path, name: str, plan, table: bool = True, candidate: bool = False, answer: bool = False) -> Path:
    """G2-3: the good set with `plan` as work/test-plan.json, a grounding table (K-1..K-3) and, with `candidate`, R-4 marked as a
    bug candidate in the register. Bytes are written with LF (the table reader refuses CR, FR-29)."""
    art = root / name / "qa-factory" / "artifacts" / "QA-1"
    shutil.copytree(GOOD, art)
    (art / "work" / "test-plan.json").write_text(json.dumps(plan), encoding="utf-8")
    if table:
        (art / "work" / "grounding.yaml").write_bytes(GROUNDING_TABLE.encode("utf-8") if table is True else table)
    if candidate:
        reg = art / "work" / "requirements-register.md"
        text = reg.read_text(encoding="utf-8")
        reg.write_bytes(text.replace("\n\n## Contradiction matrix", "\n" + CANDIDATE_ROW + "\n## Contradiction matrix", 1).encode("utf-8"))
    (art / "work" / "requirements-readiness.json").write_text(json.dumps({"open_questions": [Q9]}), encoding="utf-8")
    if answer:
        (art / "work" / "question-answers.jsonl").write_text(json.dumps(
            {"id": "Q9", "status": "answered", "reading": "a", "words": "Q9: a", "where": "gate A", "at": "2026-10-30T10:00:00"}) + "\n",
            encoding="utf-8")
    return art


def fr22_records(art: Path, ledger_states=None) -> list:
    """The records `grounding_records` writes over the story's real ledger, or over a ledger whose plan rows read `ledger_states`."""
    doc = D.L.build(art)
    if ledger_states is not None:
        doc = dict(doc, rows=[{"ref": ref, "kind": "plan_row", "state": state, "detail": ""} for ref, state in ledger_states.items()])
    return D.grounding_records(art, doc, D.gather(art))


def g2_3_the_fr22_road() -> None:
    """G2-3 (FR-22): a place the code reads wrong, with no EXECUTED check behind it, is a `bug_candidate` (the third verdict, never a
    `no`); keys per row of the spec's table. Mutations named, NOT run, killed by this file: the record is not appended in `assess`;
    `skip` closes a candidate (`row_tests_it` accepts it); the green-`oracle_unknown` branch is removed."""
    root = temp_project("qa-factory-delivery-fr22-")
    try:
        auto = lambda rid, disposition="automate", **more: dict({"id": rid, "disposition": disposition, "requirements": ["R-2"]}, **more)  # noqa: E731
        # (1) no row names the candidate: a record; the key, the text, the kind and the owner family are the spec's
        art = fr22_story(root, "none", [auto("TS-1", risk_source_refs=["grounding:K-1"])])
        got = {r["ref"]: r for r in fr22_records(art)}
        check_eq("G2-3 row 1: K-2 and K-3 are named by no row, K-1 by an automate row that is green", sorted(got), ["K-2", "K-3"])
        rec = got["K-2"]
        check_eq("G2-3 row 1: kind, key, source, requirements", (rec["kind"], rec["item_key"], rec["source"], rec["requirements"], rec["case"]),
                 ("bug_candidate", "K-2", "grounding", ["R-1"], ""))
        check("G2-3 row 1: text starts `grounding:` and names the ref, to_check says no row names it",
              rec["text"].startswith("grounding: K-2 ") and "no plan row names it" in rec["to_check"], str(rec))
        check_in("G2-3 row 1: how names the road and the ref", "Say at gate B that this needs a bug report (name K-2)", rec["how"])
        check_in("G2-3 row 1: how names the failure analyst at S7", "the failure analyst at S7", rec["how"])
        doc = D.assess(art)
        items = {i["ref"]: i for i in doc["left_items"]}
        check_eq("G2-3 end to end: both candidates are Left items, the verdict is the third word, not a `no`",
                 (sorted(k for k, i in items.items() if i["kind"] == "bug_candidate"), doc["delivery_verdict"], doc["reasons"]),
                 (["K-2", "K-3"], "after_checks", []))
        check_eq("G2-3 and the item carries the record's words (the key is the ref)", (items["K-2"]["to_check"], items["K-2"]["source"]),
                 (rec["to_check"], "grounding"))
        # (2) the pair: `skip` / `manual-human` / `unverifiable` name it and close nothing; an automate row closes it
        for disposition in ("skip", "manual-human", "unverifiable"):
            art = fr22_story(root, "excl-" + disposition, [auto("TS-1", disposition, risk_source_refs=["grounding:K-1", "grounding:K-2", "grounding:K-3"])])
            got = {r["ref"]: r for r in fr22_records(art)}
            check_eq(f"G2-3 row 2 pair: a `{disposition}` row that names K-1..K-3 closes none", sorted(got), ["K-1", "K-2", "K-3"])
            check_in(f"G2-3 row 2: to_check names the row and its disposition ({disposition})", f"TS-1) check nothing: {disposition}", got["K-1"]["to_check"])
        art = fr22_story(root, "mixed", [auto("TS-1", "skip", risk_source_refs=["grounding:K-1"]), auto("TS-2", risk_source_refs=["grounding:K-1"])])
        check_eq("G2-3 row 2 control: the same K-1 named by a skip row AND an automate row (green) is closed",
                 [r["ref"] for r in fr22_records(art)], ["K-2", "K-3"])
        # (3) a testing row the ledger does not hold
        art = fr22_story(root, "unlinked", [auto("TS-9", risk_source_refs=["grounding:K-1", "grounding:K-2", "grounding:K-3"])])
        got = {r["ref"]: r for r in fr22_records(art)}
        check_eq("G2-3 row 3: an automate row missing from the ledger leaves all three a candidate", sorted(got), ["K-1", "K-2", "K-3"])
        check_in("G2-3 row 3: the words say it could not be linked", "could not be linked", got["K-1"]["to_check"])
        # (4)(5) a testing row in the ledger: not executed -> nothing (its own kind); red -> nothing (an ordinary bug)
        art = fr22_story(root, "states", [auto("TS-1", risk_source_refs=["grounding:K-1", "grounding:K-2", "grounding:K-3"])])
        for state in ("not_executed:no result recorded for this row's cases", "failed:APP_BUG", "env_blocked:person", "not_verified:expectation_unconfirmed"):
            check_eq(f"G2-3 rows 4-5: ledger state `{state}` writes no candidate", fr22_records(art, {"TS-1": state}), [])
        check_eq("G2-3 row 4-5 control: the green state writes none either", fr22_records(art, {"TS-1": "passed_green"}), [])
        # (6) green, oracle_unknown nobody answered: first move - the ledger alone says nothing about it (control); then the record
        plan = [auto("TS-1", risk_source_refs=["grounding:K-1", "grounding:K-2", "grounding:K-3"], oracle_unknown=True)]
        art = fr22_story(root, "oracle-bare", plan, table=False)
        base = D.assess(art)
        check_eq("G2-3 row 6 first move: without the table the ledger lets a green oracle_unknown row through as `yes`",
                 (base["delivery_verdict"], base["left_items"] and [i["kind"] for i in base["left_items"]]), ("yes", ["regression"]))
        art = fr22_story(root, "oracle", plan)
        got = {r["ref"]: r for r in fr22_records(art)}
        check_eq("G2-3 row 6: a green row whose oracle_unknown nobody answered is `unconfirmed_expectation`, not silence",
                 sorted((r["ref"], r["kind"]) for r in got.values()), [("K-1", "unconfirmed_expectation"), ("K-2", "unconfirmed_expectation"),
                                                                       ("K-3", "unconfirmed_expectation")])
        check_eq("G2-3 row 6: the end-to-end verdict is the third word", D.assess(art)["delivery_verdict"], "after_checks")
        art = fr22_story(root, "oracle-ref-nowhere", [dict(plan[0], question_refs=["Q77"])])
        check_eq("G2-3 row 6: a question_refs entry the register does not hold is no answer",
                 sorted(r["kind"] for r in fr22_records(art)), ["unconfirmed_expectation"] * 3)
        art = fr22_story(root, "oracle-open", [dict(plan[0], question_refs=["Q9"])])
        check_eq("G2-3 row 6: the question named and still open: unconfirmed", sorted(r["kind"] for r in fr22_records(art)), ["unconfirmed_expectation"] * 3)
        # (7) green with an answer: nothing
        art = fr22_story(root, "oracle-answered", [dict(plan[0], question_refs=["Q9"])], answer=True)
        check_eq("G2-3 row 7: the question answered -> no record", fr22_records(art), [])
        art = fr22_story(root, "green-clean", [auto("TS-1", risk_source_refs=["grounding:K-1", "grounding:K-2", "grounding:K-3"])])
        check_eq("G2-3 row 7 control: green with no oracle_unknown -> no record", fr22_records(art), [])
        # (8) unreadable inputs with a candidate present are the factory's record, not 'no candidates'
        art = fr22_story(root, "bad-table", [auto("TS-1")], table=b"schema_version: 1\r\nimplementation_source: diff\r\n")
        got = fr22_records(art)
        check_eq("G2-3 row 8: a table that exists and cannot be read -> ONE factory_record, owner text `factory:`",
                 [(r["kind"], r["text"].startswith("factory: ")) for r in got], [("factory_record", True)])
        check("G2-3 row 8: it is a reason (verdict `no`), not a pass", D.assess(art)["delivery_ready"] is False)
        art = fr22_story(root, "bad-register", [auto("TS-1")], table=False)
        (art / "work" / "requirements-register.md").write_bytes(b"   \n")
        check_eq("G2-3 row 8: a register that exists and is empty -> a factory_record", [r["kind"] for r in fr22_records(art)], ["factory_record"])
        art = fr22_story(root, "no-table", [auto("TS-1")], table=False)
        check_eq("G2-3 edge: no table and no candidate mark -> no record, the old behaviour", fr22_records(art), [])
        art = fr22_story(root, "off-diff", [auto("TS-1")], table=b"schema_version: 1\nimplementation_source: ''\nnull_outcome:\n  source: absent\n  words: none\n")
        check_eq("G2-3 edge: a table of a story with no diff has no risks -> the K entry is silent", fr22_records(art), [])
        art = fr22_story(root, "no-risks", [auto("TS-1")], table=b"schema_version: 1\nimplementation_source: diff\nrows: []\n")
        check_eq("G2-3 edge: a diff table without risks -> no K record", fr22_records(art), [])
        # (9) the register entry works in any source world; a place that is not named says so; two candidates of one place are two records
        art = fr22_story(root, "register", [auto("TS-1", risk_source_refs=["grounding:K-1", "grounding:K-2", "grounding:K-3"])], candidate=True)
        got = {r["ref"]: r for r in fr22_records(art)}
        check_eq("G2-3 register: R-4 (a marked row no plan row names) is a record", sorted(got), ["R-4"])
        check_eq("G2-3 register: source, requirements, place in to_check", (got["R-4"]["source"], got["R-4"]["requirements"],
                 "src/app.py:30" in got["R-4"]["to_check"]), ("register", ["R-4"], True))
        reg = art / "work" / "requirements-register.md"
        reg.write_bytes(reg.read_bytes().replace(b"current-code:src/app.py:30", b"expected-contract"))
        got = {r["ref"]: r for r in fr22_records(art)}
        check_in("G2-3 edge: `file: None` -> the words say the place is not named", "place in the code not named", got["R-4"]["to_check"])
        art = fr22_story(root, "same-place", [auto("TS-1", risk_source_refs=["grounding:K-1"])], candidate=True)
        check_eq("G2-3 edge: a K-n and an R-n for one place are two records", sorted(r["ref"] for r in fr22_records(art)), ["K-2", "K-3", "R-4"])
        art = fr22_story(root, "both-named", [auto("TS-1", risk_source_refs=["grounding:K-2"], requirements=["R-4"])], candidate=True)
        check_eq("G2-3 edge: ONE row naming both closes both (K-2 and R-4)", sorted(r["ref"] for r in fr22_records(art)), ["K-1", "K-3"])
        # (10) not_planned: the person's decision rides in `how`; the candidate is not lost by being listed there
        art = fr22_story(root, "not-planned", {"rows": [auto("TS-1", risk_source_refs=["grounding:K-1"])],
                                               "not_planned": [{"ref": "K-2", "state": "deferred_by_decision", "reason": "the owner said later"}]})
        got = {r["ref"]: r for r in fr22_records(art)}
        check_eq("G2-3 not_planned: K-2 stays a candidate", sorted(got), ["K-2", "K-3"])
        check_in("G2-3 not_planned: how carries the decision, K-3's does not", "deferred_by_decision - the owner said later", got["K-2"]["how"])
        check_not_in("G2-3 not_planned: K-3 has no decision text", "Recorded for", got["K-3"]["how"])
        # (11) the plan the table cannot be matched to (no plan JSON): every candidate stays listed (an unknown is no pass)
        art = fr22_story(root, "no-plan", [])
        check_eq("G2-3 edge: an empty plan names nothing -> three candidates", sorted(r["ref"] for r in fr22_records(art)), ["K-1", "K-2", "K-3"])
        # (12) the predicate has ONE definition
        import planning_contract as PC
        check_eq("G2-3 row_tests_it: automate and manual-agent only; junk is False",
                 [PC.row_tests_it(r) for r in ({"disposition": "automate"}, {"disposition": "manual-agent"}, {"disposition": "skip"},
                                               {"disposition": "manual-human"}, {"disposition": "unverifiable"}, {"disposition": "not_needed"},
                                               {"disposition": "Automate"}, {}, None, "automate")],
                 [True, True, False, False, False, False, False, False, False, False])
        check_eq("G2-3 candidates_without_row calls it: skip does not close, automate does",
                 [c["r"] for c in PC.candidates_without_row([{"id": "TS-1", "requirements": ["R-1"], "disposition": "skip"}],
                                                            [{"r": "R-1"}], [])], ["R-1"])
        check_eq("G2-3 ... and automate closes", PC.candidates_without_row([{"id": "TS-1", "requirements": ["R-1"], "disposition": "automate"}],
                                                                           [{"r": "R-1"}], []), [])
        # (13) the conductor's road (references/conductor-actions.json, the row of `rework`) says the candidate goes to the failure analyst
        actions = json.loads((SCRIPTS.parent / "references" / "conductor-actions.json").read_text(encoding="utf-8"))["actions"]
        rework = [a for a in actions if "--operation rework" in a["run"]]
        check_eq("G2-3 conductor: ONE rework row, and its words name the bug candidate and the failure analyst",
                 (len(rework), "bug candidate" in rework[0]["says"] and "failure analyst at S7" in rework[0]["says"]), (1, True))
    finally:
        cleanup(root)


def rh1_9_no_flag_reader_without_a_writer() -> None:
    """RH1-9 N5 (AR-22): the reader of two manifest flags nothing wrote is gone; a stale REQUIRED proof is still refused
    through `PL.reached` (E7). K-D1, K-D2, K-D3."""
    root, task, proof, manifest, version, ref = delivery_fixture("qa-delivery-rh19-")

    def reasons() -> str:
        (task / "work" / "automation-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        return "\n".join(D.case_version_reasons(task))
    flags = ("proof" + "_stale", "review" + "_stale")
    try:
        # K-D1: both flags true on a row whose proof is current -> no reason of the removed reader.
        for name in flags:
            manifest["tests"][0][name] = True
        said = reasons()
        check_not_in("K-D1: a row carrying both flags is not refused for them", "carries stale proof or review", said)
        check_not_in("K-D1: its current proof is still no reason", "requires current sensitivity proof", said)
        # K-D2: the required probe's receipt is for OTHER bytes -> the reason of `PL.reached` stays (E7).
        (root / "tests" / "test_search.py").write_text("def test_search():\n    assert 2 + 2 == 5\n", encoding="utf-8")
        import proof_level
        proof_level._reset()
        check_in("K-D2: a required probe whose receipt is of other bytes is still refused",
                 "requires current sensitivity proof", reasons())
    finally:
        env_reset()
        cleanup(root)


def a_test_changed_after_its_run_is_the_persons_only_without_a_stand() -> None:
    """HF2-11c2 (P19 step 5, P21, F-5): the ledger state `not_executed:changed_since_run` is kind `changed_unrun`
    (`after_checks`, owner `environment`) when the person's word that passes the stand block is recorded for S5 or S6, kind
    `changed_unrun_ours` (`no`, owner `factory`: the stand was there and the factory did not run the test again) otherwise;
    the "Left with you" item names `run_suite.py --mine <case>`. The reader of the word is `waiver.split_overridden`, with
    the constant of `waiver.py`. Kills: the kind without `needs` (m1: one of the two branches), a second literal of the block
    name (m2: the census), the kind without an owner (m4: `test_delivery_ownership`)."""
    import delivery_verdict as DV
    import ledger as L
    import waiver
    block = waiver.STAND_NOT_CONFIRMED_BLOCK
    row = {"ref": "TC-1", "kind": "plan_row", "state": L.CHANGED_STATE,
           "detail": "tests/test_a.py - the test changed after this run: its run measured other code"}
    doc = DV.load_kinds()[0]

    def facts(*overrides) -> dict:
        return {"dispositions": {}, "decisions": {}, "cfg": {}, "manifest": {}, "triage": [], "plan": [],
                "index": {"area/TC-1": {"plan_row": "TC-1", "case_id": "TC-1"}},
                "pipeline": {"stage_overrides": [dict({"decision": "go on without a stand", "match": block}, **o)
                                                 for o in overrides]}}

    def read(f) -> tuple:
        """`(kind, verdict, owner, the Left-with-you items)` of the one row."""
        records = D.ledger_records({"rows": [row]}, f)
        kind = records[0]["kind"]
        return kind, DV.verdict_of_kind(kind, doc), DV.owner_of_kind(kind, doc), D.build_left_items(records, f, doc)

    for stage in ("S5", "S6"):
        kind, verdict, owner, items = read(facts({"stage": stage}))
        check_eq(f"the word recorded at {stage}: kind, verdict and owner", (kind, verdict, owner),
                 ("changed_unrun", "after_checks", "environment"))
        check_eq("... one item is left with the person: the case", [(i["case"], i["kind"]) for i in items], [("TC-1", "changed_unrun")])
        check_in(f"... and names the command that runs it again ({stage})", "`run_suite.py --mine TC-1`", items[0]["how"] if items else "")
        check_eq("... the delivery is `after_checks`", DV.decide([kind], doc)[0], "after_checks")
    kind, verdict, owner, items = read(facts())
    check_eq("no word recorded: kind, verdict and owner", (kind, verdict, owner), ("changed_unrun_ours", "no", "factory"))
    check_eq("... nothing is left with the person (it is ours to repair)", items, [])
    check_eq("... the delivery is `no`", DV.decide([kind], doc)[0], "no")
    check_in("... and the row stays a reason, in the ledger's words", "ledger: TC-1 is `not_executed:changed_since_run`",
             D.ledger_records({"rows": [row]}, facts())[0]["text"])
    for label, f in (("a word taken back", facts({"stage": "S6", "revoked_at": "2026-10-26T10:00:00Z"})),
                     ("a word at another stage", facts({"stage": "S4"})),
                     ("a word about another block", facts({"stage": "S6", "match": waiver.QUESTION_THRESHOLD_BLOCK})),
                     ("a word with no decision", facts({"stage": "S6", "decision": " "})),
                     ("no pipeline at all", {k: v for k, v in facts({"stage": "S6"}).items() if k != "pipeline"}),
                     ("no facts at all", None)):
        check_eq(f"{label}: the word is not recorded (`no`, the direction of error)", D.stand_word(f), False)
        if f is not None:
            check_eq(f"{label}: the kind is the factory's", read(f)[0], "changed_unrun_ours")
    # one reader, one constant: the stages are the driver's and the registry's, the block name is written once
    import story_run
    block_names = json.loads((SCRIPTS.parent / "references" / "block-names.json").read_text(encoding="utf-8"))["names"]
    registry = next(r["stages"] for r in block_names if r["block"] == block)
    check_eq("the stages of the word are the driver's", D.STAND_WORD_STAGES, story_run.Driver.STAND_STAGES)
    check_eq("... and the registry's", D.STAND_WORD_STAGES, tuple(registry))


def a_blocked_item_lists_only_its_blocked_thens() -> None:
    """HF2-3 3c1 handoff Q2 (integration): the "Left with you" item of a case whose only kind is `blocked_by_check` lists the
    clauses of the Thens that stand behind the red check (`to_check`), never every Then of the case: the other Thens a test
    proved. An item with no Then row (the ledger's own record of the kind) lists none and names the case. Kills: the old
    branch that lists every Then (m1: Then 1's clause appears in `to_check`), a branch that lists none for a row (m2)."""
    from harness import FIXTURES, temp_dir
    top = temp_dir("qa-left-blocked-")
    try:
        task = top / "QA-1"
        shutil.copytree(FIXTURES / "after-checks", task)
        case = task / "work" / "test-cases" / "checkout" / "TC-001.md"
        case.write_text(case.read_text(encoding="utf-8").rstrip() + "\n\n## Then\n"
                        "1. A 422 with code `DISCOUNT_TOO_LARGE` is returned.\n"
                        "2. The total is unchanged, read back from the order record.\n", encoding="utf-8")
        mpath = task / "work" / "automation-manifest.json"
        manifest = json.loads(mpath.read_text(encoding="utf-8"))
        manifest["then_bindings"] = [
            {"case": "TC-001", "then": 1, "instance_id": C.test_instance_id(manifest["tests"][0]),
             "assertion_ref": "tests/test_coupon.py:9", "status": "covered"},
            {"case": "TC-001", "then": 2, "instance_id": None, "assertion_ref": None, "status": "unresolved",
             "reason": "blocked_by_check", "blocking_check": "TC-009", "detail": "read the total back after TC-009 is fixed"}]
        mpath.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        doc = D.assess(task)
        found = [i for i in doc["left_items"] if i["counts"] and i["ref"] == "TC-001"]
        check_eq("blocked: ONE counting item for TC-001", len(found), 1)
        item = found[0] if found else {"kinds": [], "to_check": "-"}
        check_eq("blocked: the item's only kind is the blocked one", item["kinds"], ["blocked_by_check"])
        check_eq("blocked: only the blocked Then is listed", item["to_check"], "The total is unchanged, read back from the order record.")
        check_not_in("blocked control: not the Then a test proved", "DISCOUNT_TOO_LARGE", item["to_check"])
        bare = D.build_left_items([{"text": "", "kind": "blocked_by_check", "case": "TC-001", "ref": "TC-001", "source": "ledger"}],
                                  D.gather(task))
        check_eq("blocked: a record with no Then row lists no Then and names the case, never an empty line (HF2-0 R1, FR-41)",
                 [(i["case"], i["to_check"], i["how"]) for i in bare],
                 [("TC-001", "TC-001", "check after the check this one depends on is fixed")])
    finally:
        cleanup(top)


def a_mixed_item_lists_the_thens_each_record_leaves() -> None:
    """AR-26 (the unit is the (Then, instance) pair), P21 (what the person must do is named exactly), the owner's question
    on HF2-3: an item of MIXED kinds that holds a `blocked_by_check` record lists the UNION of the Thens each record leaves
    to the person - the blocked Then, the Then-level handed Then (with its part) - once each, by Then number, never every Then
    merely because the kinds are mixed. A record that leaves the WHOLE case (a whole-case hand-off, `not_executed`) lists
    every Then, as before. Kills: m1 - a mixed item lists every Then (Then 1's clause appears in the blocked + handed item)."""
    from harness import FIXTURES, temp_dir
    top = temp_dir("qa-left-mixed-")
    try:
        task = top / "QA-1"
        shutil.copytree(FIXTURES / "after-checks", task)
        case = task / "work" / "test-cases" / "checkout" / "TC-001.md"
        case.write_text(case.read_text(encoding="utf-8").rstrip() + "\n\n## Then\n"
                        "1. A 422 with code `DISCOUNT_TOO_LARGE` is returned.\n"
                        "2. The total is unchanged, read back from the order record.\n"
                        "3. An audit line is written.\n", encoding="utf-8")
        facts = D.gather(task)

        def rec(kind: str, source: str, **more) -> dict:
            return {"text": "", "kind": kind, "case": "TC-001", "ref": "TC-001", "source": source, **more}

        def left(*records) -> dict:
            items = D.build_left_items(list(records), facts)
            return next(i for i in items if i["ref"] == "TC-001")

        blocked2 = rec("blocked_by_check", "blocked", then=2, how="x")
        item = left(blocked2, rec("handed", "handed", then=3, part="the audit log"))
        check_eq("mixed: both kinds are on the one item", sorted(item["kinds"]), ["blocked_by_check", "handed"])
        check_eq("mixed rule (union of the Thens each record leaves): blocked Then 2 + handed Then 3, with its part",
                 item["to_check"], "The total is unchanged, read back from the order record.; "
                 "An audit line is written. - the part: the audit log")
        check_not_in("mixed: not the Then a test proved", "DISCOUNT_TOO_LARGE", item["to_check"])
        item = left(blocked2, rec("handed", "handed", then=2), rec("handed", "handed", then=2))
        check_eq("mixed: a Then named by two records is listed once", item["to_check"].count("The total is unchanged"), 1)
        item = left(rec("blocked_by_check", "ledger"), rec("handed", "handed", then=3))
        check_eq("mixed: a blocked record with no Then row adds none - only the handed Then", item["to_check"],
                 "An audit line is written.")
        item = left(blocked2, rec("handed", "handed"))
        check_in("control, whole-case hand-off (every Then of the case): Then 1", "DISCOUNT_TOO_LARGE", item["to_check"])
        check_in("... Then 2", "The total is unchanged", item["to_check"])
        check_in("... Then 3", "An audit line is written", item["to_check"])
        item = left(blocked2, rec("not_executed_code", "ledger"))
        check_in("control, a not_executed record leaves the whole case (as before): Then 1", "DISCOUNT_TOO_LARGE",
                 item["to_check"])
    finally:
        cleanup(top)


def a_failed_case_keeps_the_then_the_person_took() -> None:
    """HF2-3 (3c1-K4b, F6): the filter of `assess` (G9) drops the WHOLE-case hand-off of a case that failed - the failed row's
    own kind decides (P21) - and ONLY that. A Then the person took beside the case's own result is a Then no run answered; the
    case's red does not answer it, so the "Left with you" line stays."""
    root, art = _red_story()
    try:
        mpath = art / "work" / "automation-manifest.json"
        manifest = json.loads(mpath.read_text(encoding="utf-8"))
        manifest["then_bindings"] = [{"case": "TC-001", "then": 2, "instance_id": None, "assertion_ref": None,
                                      "status": "unresolved", "reason": "handed_to_person", "owner": "person",
                                      "detail": "open the order record and read the total"}]
        mpath.write_text(json.dumps(manifest), encoding="utf-8")
        doc = D.assess(art)
        check_eq("K4b: the case failed, so the verdict is no", doc["delivery_verdict"], "no")
        kinds = [k for i in doc["left_items"] if i.get("ref") == "TC-001" for k in i.get("kinds") or []]
        check_in("K4b: ... and the Then the person took is still listed", "handed", kinds)
        # control: the same case with the WHOLE case handed - the record goes, as before
        manifest["then_bindings"] = []
        manifest["unresolved"] = [{"case": "TC-001", "reason": "handed_to_person", "detail": "android: npm run e2e -- --grep TC-001"}]
        mpath.write_text(json.dumps(manifest), encoding="utf-8")
        doc = D.assess(art)
        kinds = [k for i in doc["left_items"] if i.get("ref") == "TC-001" for k in i.get("kinds") or []]
        check_not_in("K4b control: a whole-case hand-off of a failed case is dropped (P21)", "handed", kinds)
    finally:
        cleanup(root)


def a_red_test_is_not_asked_for_a_sensitivity_proof() -> None:
    """HF2-3 (3c1-K4c, FB-3 (a), F9): a test red against a requirement - a `contradicts_requirement` row names it and its CURRENT
    result is `failed` - gets no "requires current sensitivity proof" line; it is the product's bug. Every input that is NOT that
    keeps the line (the allowed error direction, FR-59): a current `passed`, a red with no row, a row about another instance, a
    report nobody can read, and run blocks that say failed while the report says passed (the report is the only source)."""
    root, task, proof, manifest, version, ref = delivery_fixture("qa-delivery-red-proof-")
    iid = "test_search[eu]"
    asked = "requires current sensitivity proof"
    try:
        manifest["obligation_bindings"][0]["probe_receipt_ref"] = "work/sensitivity-receipts/gone.json"

        def reasons(rows=None, status="failed", report="ok", block=None) -> str:
            m = json.loads(json.dumps(manifest))
            m["unresolved"] = rows if rows is not None else [
                {"case": "TC-009", "reason": "contradicts_requirement", "instance_ids": [iid], "detail": "not delivered"}]
            m["then_bindings"] = [{"case": "TC-009", "then": 1, "instance_id": iid, "assertion_ref": "tests/test_search.py:9",
                                   "status": "covered"}]
            (task / "work" / "automation-manifest.json").write_text(json.dumps(m), encoding="utf-8")
            path = task / "work" / "run-report.json"
            if report == "ok":
                path.write_text(json.dumps({"current_results": [{"instance_id": iid, "case": "TC-009", "status": status}]}), encoding="utf-8")
            elif report == "garbage":
                path.write_text("{not json", encoding="utf-8")
            elif path.exists():
                path.unlink()
            blocks = task / "work" / "run-blocks"
            if block:
                blocks.mkdir(parents=True, exist_ok=True)
                (blocks / "20261024T000000Z-b1.json").write_text(json.dumps(
                    {"purpose": "initial", "results": [{"instance_id": iid, "status": block}]}), encoding="utf-8")
            return "\n".join(D.case_version_reasons(task))

        check_not_in("K4c: red by a row and a failed current result -> no sensitivity-proof line", asked, reasons())
        check_in("K4c (a): the current result is `passed` -> the line stays", asked, reasons(status="passed"))
        check_in("K4c (b): a red with no row (FB-3) -> the line stays", asked, reasons(rows=[]))
        check_in("K4c (c): a row about another instance -> the line stays", asked, reasons(rows=[
            {"case": "TC-009", "reason": "contradicts_requirement", "instance_ids": ["somebody_else"], "detail": "x"}]))
        check_in("K4c (d): no report -> the line stays", asked, reasons(report="none"))
        check_in("K4c (d): a report that is not JSON -> the line stays", asked, reasons(report="garbage"))
        check_in("K4c (a, m10): the blocks say failed, the report says passed -> the line stays (the report is the source)", asked,
                 reasons(status="passed", block="failed"))
    finally:
        env_reset()
        cleanup(root)


def the_record_text_carries_the_repair_limit() -> None:
    """C1-5c (section 3.3): a rejected row a window covers says why its rounds ended, in the words the report prints; a row
    without `repair_limit` reads exactly as before; the unknown count has its own sentence; no cause token is printed."""
    def text(limit):
        row = {"ref": "t1", "kind": "test", "state": "review_rejected", "detail": "tests/a.py::test_x"}
        if limit is not None:
            row["repair_limit"] = limit
        return D.ledger_records({"rows": [row]})[0]["text"]
    check_eq("no window: the record text is what it was",
             text(None), "ledger: t1 is `review_rejected` (tests/a.py::test_x)")
    check_eq("a window at the cap", text({"stage": "S5", "counted": 2, "cap": 2, "reason": "cap"}),
             "ledger: t1 is `review_rejected` (tests/a.py::test_x); repair limit exhausted: 2 of 2 rounds about the tests themselves")
    check_eq("a count nobody could read", text({"stage": "S5", "counted": None, "cap": None, "reason": "unknown"}),
             "ledger: t1 is `review_rejected` (tests/a.py::test_x); the factory could not count its repair rounds")
    check_not_in("no cause token reaches the text", "test_defect", text({"stage": "S5", "counted": 2, "cap": 2, "reason": "cap"}))
    check_eq("the owner of such a reason is still the review's",
             D.reason_record(text({"stage": "S5", "counted": 2, "cap": 2, "reason": "cap"}))["owner"], "review")


def a_case_handed_through_the_door_reaches_gate_b_with_its_steps() -> None:
    """t-721 C2-3 (T12, section 3.7): after `story_step.py decide --hand`, the three readers of gate B see the case:
    `handed_rows` (the manifest's own `handed_to_person` row), `handed_records` (kind `handed`, `how` = the row's `detail`
    - the steps or the command, never the person's words - and `no_command` false), and `mark_handed` (a ledger row of the
    case that executed nothing becomes `not_executed:handed_to_person`)."""
    import os
    import test_story_step as TS
    from harness import use_project
    root = temp_project("qa-delivery-door-")
    try:
        use_project(root)
        art, _window = TS.s5_window_story(root, "QA-T12", handed=False)
        TS.set_rows(art, [])
        done = TS.run_decide(root, dict(os.environ, CLAUDE_PROJECT_DIR=str(root)), "QA-T12", ["--hand", "TC-2"])
        check_eq("T12: the door exits 0", done.returncode, 0)
        rows = D.handed_rows(art)
        check_eq("T12: handed_rows sees the case, its `what` is the steps", [(r["case"], r["what"]) for r in rows],
                 [("TC-2", "by hand - the steps of TC-2")])
        records = [r for r in D.handed_records(art) if r["kind"] == "handed"]
        check_eq("T12: handed_records: kind `handed`, `how` = the detail, a command is named (no_command false)",
                 [(r["case"], r["how"], r["no_command"]) for r in records],
                 [("TC-2", "by hand - the steps of TC-2", False)])
        check_not_in("T12: and `how` holds no word of the person", "myself", records[0]["how"] if records else "")
        marked = D.mark_handed({"rows": [{"ref": "TC-2", "kind": "plan_row", "state": "not_executed:no result",
                                          "detail": "x"}]}, art)
        check_eq("T12: a ledger row of the case that executed nothing becomes handed", marked["rows"][0]["state"],
                 D.HANDED_LEDGER_STATE)
    finally:
        cleanup(root)


def a_case_taken_by_hand_is_handed() -> None:
    """t-699 F5 / C1-6b: a case whose `request.json` says `refused.by: person_checks` is restated `not_executed:handed_to_person`
    (so its kind is `handed`, the third verdict); another `by`, or a row that observed a result, keeps its state; a second call
    adds no row and changes nothing; a case that is also handed in the manifest keeps the manifest's words."""
    import manual_capture as MC
    from harness import install_artifacts, use_project
    root = temp_project("qa-delivery-by-hand-")
    try:
        art = install_artifacts(root, GOOD, "QA-1")
        use_project(root)
        key = sorted(C.case_index(art))[0]
        path = MC.case_root(art, key) / "request.json"
        path.parent.mkdir(parents=True, exist_ok=True)

        def doc():
            return {"rows": [{"ref": D._bare(key), "kind": "plan_row", "state": "not_executed:no result", "detail": "x"},
                             {"ref": "t9", "kind": "test", "state": "failed:TEST_BUG", "detail": f"{D._bare(key)} red"}]}

        def refused(**over):
            path.write_text(json.dumps({"refused": dict({"reason": "the stand does not answer", "door": "check it by hand"}, **over)}), encoding="utf-8")
        refused(by=D.PERSON_CHECKS)
        once = D.mark_handed(doc(), art)
        check_eq("person_checks: the unexecuted row is handed, with the refusal's words",
                 (once["rows"][0]["state"], once["rows"][0]["detail"]),
                 (D.HANDED_LEDGER_STATE, f"{key}: the stand does not answer - check it by hand"))
        check_eq("and a row that observed a failure keeps its state", once["rows"][1]["state"], "failed:TEST_BUG")
        twice = D.mark_handed(json.loads(json.dumps(once)), art)
        check_eq("a second call adds no row and changes nothing", (twice, len(twice["rows"])), (once, 2))
        kinds = [(r["ref"], r["kind"]) for r in D.ledger_records(once)]
        check_eq("its kind is `handed`; the failed row keeps its own", (kinds[0], kinds[1][1] != "handed"), ((D._bare(key), "handed"), True))
        refused(by="left_unchecked")
        check_eq("another `by` leaves the row as it was", D.mark_handed(doc(), art)["rows"][0]["state"], "not_executed:no result")
        refused()
        check_eq("no `by` leaves the row as it was", D.mark_handed(doc(), art)["rows"][0]["state"], "not_executed:no result")
    finally:
        cleanup(root)


def a_case_taken_by_hand_closes_its_requirement() -> None:
    """C5-4 (P21): the requirement of a manual-agent case the person took by hand (`refused.by: person_checks`) has an outcome in
    "Left with you" - one item for the case, verdict `after_checks` - where its chain read `not_in_manifest` (`no`).
    `person_check_rows` decides a verdict now, so its error direction is `no`: every input that is not exactly the record keeps the
    old gap (the walk's cases are in test_traceability.py); here the verdict. INVARIANT: a `no` kind is never turned into
    `after_checks` by the hand-off - a requirement with a case that is broken stays `no`, a red run is a `no`, and
    `left_unchecked` (the `go on` word) is the same `no` it was.
    Kills: `left_unchecked` read as handed (K-C54.5), the branch above the results (K-C54.6, with test_traceability.py)."""
    import manual_capture as MC
    from harness import FIXTURES, temp_dir
    root = temp_dir("qa-delivery-c54-")
    task = root / "QA-1"
    shutil.copytree(FIXTURES / "after-checks", task)
    try:
        def edit(rel: str, change) -> None:
            data = json.loads((task / rel).read_text(encoding="utf-8"))
            change(data)
            (task / rel).write_text(json.dumps(data), encoding="utf-8")
        edit("work/run-report.json", lambda r: r.update(manual_checks=[], current_manual_checks=[]))
        request = MC.case_root(task, "TC-002") / "request.json"
        request.parent.mkdir(parents=True, exist_ok=True)

        def refused(by=D.PERSON_CHECKS):
            request.write_text(json.dumps({"refused": {"by": by, "reason": "the stand does not answer", "door": "check it by hand"}}),
                               encoding="utf-8")

        def verdict_and_items() -> tuple:
            doc = D.assess(task)
            return doc["delivery_verdict"], [i for i in doc["left_items"] if i.get("case") == "TC-002"], doc
        word, _items, doc = verdict_and_items()
        check_eq("K-C54.5 control: no record - R-2 is a broken chain, so a `no`", (word, any("R-2" in r for r in doc["reasons"])), ("no", True))
        refused()
        word, items, doc = verdict_and_items()
        # the fixture holds other `after_checks` items (TC-004, TC-005) and a requirement it leaves open: only R-2's part is asked
        check_eq("K-C54.5 `person_checks`: ONE item for the case, kind `handed`, naming R-2 (a second item is a stop)",
                 [(i["kind"], i["requirements"]) for i in items], [("handed", ["R-2"])])
        check("K-C54.5 ... and R-2 is no reason of a `no`", not any("R-2" in r for r in doc["reasons"]), str(doc["reasons"]))
        refused("left_unchecked")
        word, items, doc = verdict_and_items()
        check_eq("K-C54.5 `left_unchecked` (`go on`): no item, R-2 is a `no` as it was", (items, any("R-2" in r for r in doc["reasons"])),
                 ([], True))
        refused("PERSON_CHECKS")
        check_eq("K-C54.5 another case of the word is no hand-off", verdict_and_items()[1], [])
        # t-593 F-8 (c): the stale record. A later pass writes the case's `request.json` anew (no `refused`): the old refusal is gone
        # with the file's old content, so the case is no longer handed and R-2 is a `no` as it was (the record binds to its pass)
        refused()
        check_eq("F-8 control: the record stands", len(verdict_and_items()[1]), 1)
        request.write_text(json.dumps({"case": "TC-002", "steps": []}), encoding="utf-8")
        word, items, doc = verdict_and_items()
        check_eq("F-8 a request rewritten by a later pass (no `refused`): no hand-off item, R-2 is a `no`",
                 (items, any("R-2" in r for r in doc["reasons"])), ([], True))
        request.write_text("{not json", encoding="utf-8")
        check_eq("F-8 an unreadable request.json: no hand-off item either (the direction of `no`)", verdict_and_items()[1], [])
        # a requirement shared with a broken case stays `no`: TC-001 also names R-2 and has no run result
        refused()
        case_file = task / "work" / "test-cases" / "checkout" / "TC-001.md"
        case_file.write_text(case_file.read_text(encoding="utf-8").replace("Requirements: R-1", "Requirements: R-1, R-2"), encoding="utf-8")
        edit("work/run-report.json", lambda r: r.update(results=[]))
        records = [x for x in D.traceability_records(task) if "R-2" in (x.get("requirements") or [])]
        check_eq("K-C54.6 mixed requirement (one handed, one with no result): ONE `no` record, none of the hand-off's",
                 [(x["kind"], x["case"]) for x in records], [("chain_broken", "")])
        # a red run beside the record: the observed failure is older than the hand-off
        edit("work/run-report.json", lambda r: r.update(
            results=[{"test": "tests/test_coupon.py::test_cap_rejected", "case": "TC-001", "result": "passed"}],
            manual_checks=[{"case": "TC-002", "result": "failed", "attempt_id": "a1", "evidence_validated": True}],
            current_manual_checks=[{"case": "TC-002", "result": "failed", "attempt_id": "a1", "evidence_validated": True}]))
        word, items, doc = verdict_and_items()
        check_eq("K-C54.6 a red run beside `person_checks`: no hand-off item, the verdict is `no`", (items, word), ([], "no"))
        # a case id the evidence folder cannot be named for is skipped, not a crash, and does not stop the keys after it
        refused()
        saved = C.case_index
        try:
            C.case_index = lambda artifacts: {"area__x/TC__1": {}, "TC-002": {}}
            check_eq("K-C54.7 a key `case_root` refuses (ValueError) is skipped; the next key is still read",
                     [r["case"] for r in D.person_check_rows(task)], ["TC-002"])
        finally:
            C.case_index = saved
    finally:
        cleanup(root)


def a_handed_case_with_a_plan_obligation_is_no_coverage_reason() -> None:
    """C5-4 (t-593 F-1): on a story whose `work/test-plan.json` is schema 2, the obligation of a plan row whose cases the person took
    by hand (`refused.by: person_checks`) is "Left with you" - verdict `after_checks`, no `coverage:` reason - where it read `no`
    (the fixture of the first C5-4 keys had no schema-2 plan, so coverage read `legacy_assessment_not_available`).
    INVARIANT: only a hand-off lifts it. No record, `left_unchecked` (`go on`), a plan row another case shares, a red run and an
    unreadable hand-off set all keep the reason (FR-59). Kills: the reason lifted for every manual-agent obligation (control),
    for `left_unchecked`, or for a shared row; the red exception dropped."""
    import manual_capture as MC
    from harness import FIXTURES, temp_dir
    root = temp_dir("qa-delivery-c54-plan-")
    task = root / "QA-1"
    shutil.copytree(FIXTURES / "after-checks", task)
    try:
        report = json.loads((task / "work" / "run-report.json").read_text(encoding="utf-8"))
        report.update(manual_checks=[], current_manual_checks=[])
        (task / "work" / "run-report.json").write_text(json.dumps(report), encoding="utf-8")
        ob = {"obligation_id": "O-TC2", "behavior": "b", "observation_boundary": "api", "completion_condition": "done",
              "requirement_refs": [{"ref": "R-2", "revision": "r"}], "applicable_scenarios": ["positive"],
              "oracle_status": "resolved", "oracle_source_ref": "spec", "decision": "manual-agent",
              "execution_scope": "current_task", "planned_check_refs": ["x"]}
        (task / "work" / "test-plan.json").write_text(json.dumps(
            {"rows": [{"id": "TS-2", "schema_version": 2, "coverage_obligations": [ob]}]}), encoding="utf-8")
        request = MC.case_root(task, "TC-002") / "request.json"
        request.parent.mkdir(parents=True, exist_ok=True)

        def refused(by=D.PERSON_CHECKS):
            request.write_text(json.dumps({"refused": {"by": by, "reason": "the stand does not answer", "door": "check it by hand"}}),
                               encoding="utf-8")

        def state() -> tuple:
            doc = D.assess(task)
            return doc["delivery_verdict"], [r for r in doc["reasons"] if "O-TC2" in r], doc
        word, reasons, _ = state()
        check_eq("F-1 control: a schema-2 plan, no hand-off: the coverage reason, `no`", (word, len(reasons)), ("no", 1))
        refused()
        word, reasons, doc = state()
        check_eq("F-1 `person_checks`: no coverage reason, the verdict is the third one",
                 (word, reasons, [i["kind"] for i in doc["left_items"] if i.get("case") == "TC-002"]), ("after_checks", [], ["handed"]))
        refused("left_unchecked")
        word, reasons, _ = state()
        check_eq("F-1 `left_unchecked` (`go on`): the reason stays, `no`", (word, len(reasons)), ("no", 1))
        refused()
        case_file = task / "work" / "test-cases" / "checkout" / "TC-001.md"
        saved = case_file.read_text(encoding="utf-8")
        case_file.write_text(saved.replace("Plan row: TS-1", "Plan row: TS-2"), encoding="utf-8")
        check_eq("F-1 a plan row another (not handed) case shares: not lifted", D.handed_plan_rows(task), frozenset())
        check_eq("F-1 ... and its reason stays", len(state()[1]), 1)
        case_file.write_text(saved, encoding="utf-8")
        check_eq("F-1 control: the row of the handed case alone", D.handed_plan_rows(task), frozenset({"TS-2"}))
        keep = C.case_index
        try:
            def broken(artifacts):
                raise ValueError("unreadable")
            C.case_index = broken
            check_eq("F-1 an unreadable case index: no row is handed", D.handed_plan_rows(task), frozenset())
        finally:
            C.case_index = keep
        # a live red beside the hand-off keeps the reason (the obligation is `failed`, so `coverage red:`)
        obligation = {"obligation_id": "O-TC2", "plan_row": "TS-2", "execution_scope": "current_task", "verified": False,
                      "person_debt": False, "gap": "g", "execution_state": "failed", "oracle_open": False}
        check_eq("F-1 a red obligation of a handed row stays a reason",
                 D.coverage_reasons({"coverage": {"obligations": [obligation]}}, frozenset({"TS-2"})), ["coverage red: O-TC2 — g"])
        check_eq("F-1 ... and a not-run one of the same row goes",
                 D.coverage_reasons({"coverage": {"obligations": [dict(obligation, execution_state="not_run")]}}, frozenset({"TS-2"})), [])
    finally:
        cleanup(root)


# ---------------------------------------------------------------------------------------------- t-416
# `lifecycle_reasons` asked for the `Automated` stamp of an approved, manifest-green test whose OWN run is red, and
# `case_stamp` (t-415) refuses that stamp until the run is repaired: a false sentence ("approved and green") behind a
# door that cannot open (FR-2, FR-5). INVARIANT the skip must keep: the red run is never dropped - it is its own `no`
# reason, or (a stand gap the person accepted) a named item in their list (`after_checks`); no path gives `yes`.
RED_ID = "tests/test_coupon.py::test_cap_rejected"
RED_CLASSES = (
    ("no triage row", None, None),
    ("APP_BUG", {"verdict": "APP_BUG"}, None),
    ("TEST_BUG", {"verdict": "TEST_BUG"}, None),
    ("TEST_BUG:collection", {"verdict": "TEST_BUG:collection"}, None),
    ("ENV_ISSUE undecided", {"verdict": "ENV_ISSUE"}, None),
    ("ENV_ISSUE accepted", {"verdict": "ENV_ISSUE"}, "accept - the person wrote: TC-001: accept"),
    ("FLAKY fixed", {"verdict": "FLAKY", "mechanism": "timing", "reruns": 5, "fix_rounds": 1, "fix_result": "fixed"}, None),
    ("FLAKY unfixed", {"verdict": "FLAKY", "mechanism": "timing", "reruns": 5, "fix_rounds": 1,
                       "fix_result": "not_fixed"}, None),
    ("APP_CHANGED", {"verdict": "APP_CHANGED"}, None),
    ("CASE_DEFECT", {"verdict": "CASE_DEFECT"}, None),
    ("NOT_EXECUTED", {"verdict": "NOT_EXECUTED"}, None),
)


def _red_story(result="failed", exec_status="passed", triage=None, answer=None, case_status="Approved") -> tuple:
    """`(root, art)`: the good story with ONE run row `result`, the manifest test (green, approved) bound to that row, the
    case file at `case_status`, an optional triage row and an optional recorded gate-B answer."""
    root = temp_project("qa-factory-red-stamp-")
    art = root / "qa-factory" / "artifacts" / "QA-1"
    shutil.copytree(GOOD, art)
    report = json.loads((art / "work" / "run-report.json").read_text(encoding="utf-8"))
    report["execution_status"] = exec_status
    report["results"][0].update(result=result, attempt_id="a1")
    (art / "work" / "run-report.json").write_text(json.dumps(report), encoding="utf-8")
    mpath = art / "work" / "automation-manifest.json"
    manifest = json.loads(mpath.read_text(encoding="utf-8"))
    manifest["tests"][0]["instance_id"] = RED_ID
    mpath.write_text(json.dumps(manifest), encoding="utf-8")
    case = art / "work" / "test-cases" / "checkout" / "TC-001.md"
    case.write_text(case.read_text(encoding="utf-8").replace("status: Automated", f"status: {case_status}"),
                    encoding="utf-8")
    if triage:
        (art / "work" / "triage.json").write_text(json.dumps({"triage": [dict(
            {"instance_id": RED_ID, "attempt_id": "a1", "evidence": "evidence/x.json"}, **triage)]}), encoding="utf-8")
    if answer:
        (art / "pipeline.json").write_text(json.dumps({"stage_overrides": [
            {"stage": "S9", "match": "stand gap: TC-001", "decision": answer, "at": "2026-10-03T10:00:00Z",
             "by": "human"}]}), encoding="utf-8")
    return root, art


def a_red_run_does_not_also_ask_for_the_stamp() -> None:
    # K1 "a red run does not also ask for the stamp" - red before the fix (the sentence was printed for run=failed)
    root, art = _red_story()
    try:
        check_eq("K1: a red run does not also ask for the stamp", D.lifecycle_reasons(art), [])
        check_eq("K1: for `error` neither", D.lifecycle_reasons(_retarget(art, result="error")), [])
        # K2a: the verdict under that red run is still `no`, and the reasons name the run
        doc = D.assess(art)
        check_eq("K2a: no triage row -> the verdict is still no", doc["delivery_verdict"], "no")
        said = "\n".join(doc["reasons"])
        check_in("K2a: the reasons name the run's test", RED_ID, said)
        # the story was retargeted to `error` two lines up: the ledger names that very result for the case (t-419, C6)
        check_in("K2a: and the run's own result word beside the case", "is `error` (TC-001)", said)
        check_not_in("K2a: the false lifecycle sentence is gone", "step 8b", said)
    finally:
        cleanup(root)

    # K2a/K2b/K2c: the whole matrix - run result x execution_status x triage class - never gives `yes`; an accepted
    # stand gap is the one path to `after_checks`, and the person's list names the case there.
    outcomes = {}
    for result in ("failed", "error"):
        for exec_status in ("passed", "failed"):
            for name, row, answer in RED_CLASSES:
                root, art = _red_story(result, exec_status, row, answer)
                try:
                    check_eq(f"K1 matrix: {result}/{exec_status}/{name}: no lifecycle sentence",
                             D.lifecycle_reasons(art), [])
                    doc = D.assess(art)
                    outcomes[(result, exec_status, name)] = word = doc["delivery_verdict"]
                    check("K2c: " + f"{result}/{exec_status}/{name}: never `yes` ({word})", word != "yes")
                    check("K2c: " + f"{result}/{exec_status}/{name}: delivery_ready is False", doc["delivery_ready"] is False)
                    if word == "no":
                        # t-419 (C6): "names the run" is the run's own reason text - its result word (`failed` / `error`) beside
                        # the case it ran for - not `TC-001` alone, which any reason about the case would carry
                        check(f"K2a: {result}/{exec_status}/{name}: a `no` carries a reason that names the run's own result",
                              any("TC-001" in r and result in r for r in doc["reasons"]), str(doc["reasons"]))
                    else:
                        check_eq(f"K2b: {result}/{exec_status}/{name}: the third verdict only for the accepted stand gap",
                                 (word, name), ("after_checks", "ENV_ISSUE accepted"))
                        check_eq("K2b: ... with no reason", doc["reasons"], [])
                        items = [i for i in doc["left_items"] if i.get("counts")]
                        check("K2b: the person's list names the case", any(i.get("ref") == "TC-001" for i in items), str(items))
                        check_in("K2b: ... as the accepted stand gap", "env_accepted", ",".join(
                            k for i in items for k in (i.get("kinds") or [i.get("kind")])))
                finally:
                    cleanup(root)
    check_eq("K2b: the accepted stand gap of a `failed` result is the third verdict",
             outcomes[("failed", "passed", "ENV_ISSUE accepted")], "after_checks")
    check("K2c: every other row is `no`", all(w == "no" for k, w in outcomes.items() if k[2] != "ENV_ISSUE accepted"
                                              or k[0] == "error"), str(outcomes))

    # K3 / K5 FLIPPED by HF3-1 (A-K5; FR-59, FR-18, the finding "three readers of green without a run row" - P20: the
    # expectation follows that requirement, not the code): a test the manifest calls green but the run recorded NO green row
    # for is not stamped by `case_stamp` (`instance_hold` = `not_run`), so the stamp must not be demanded either - the sentence
    # "approved and green" would be false and its door shut (FR-2, FR-5). The unrun test is never dropped: the ledger gives it
    # its own `no` reason (`not_executed:`), so the verdict stays `no` and nothing here gives `yes`.
    root, art = _red_story(result="passed")
    try:
        (art / "work" / "run-report.json").unlink()
        check_eq("K3 (HF3-1): no run report -> the case is held: the stamp is NOT demanded (it was)", D.lifecycle_reasons(art), [])
        doc = D.assess(art)
        check_eq("K3: ... and the verdict is still `no`: the unrun test is its own reason", doc["delivery_verdict"], "no")
        check("K3: ... a reason remains and it is not the lifecycle sentence", bool(doc["reasons"]) and "step 8b" not in "\n".join(doc["reasons"]),
              str(doc["reasons"]))
        report = {"execution_status": "passed", "results": [], "current_results": []}
        (art / "work" / "run-report.json").write_text(json.dumps(report), encoding="utf-8")
        check_eq("K3 (HF3-1): a run report with no row -> held, the stamp is not demanded", D.lifecycle_reasons(art), [])
        # K5 an unreadable run report: no exception, and the case is held (an unknown is no run)
        for body in ("{not json", "[]", "null", "\"text\"", '{"results": "x", "current_results": 7}'):
            (art / "work" / "run-report.json").write_text(body, encoding="utf-8")
            check_eq(f"K5 (HF3-1): run-report.json = {body!r} -> held, the stamp is not demanded", D.lifecycle_reasons(art), [])
        (art / "work" / "run-report.json").write_bytes(b"\xff\xfe\x00\x01")
        check_eq("K5 (HF3-1): undecodable bytes -> held", D.lifecycle_reasons(art), [])
        check_eq("K5: ... and the verdict is not `yes`", D.assess(art)["delivery_verdict"], "no")
    finally:
        cleanup(root)

    # A-K5 / A-1 (critic t-1276): a `skipped` run row holds the case (no green row of its own), so the stamp is not demanded, and
    # the verdict stays `no`. What carries that `no` is the TRACE chain (`result:skipped` is not terminal -> `chain_broken`): the
    # ledger reads the row `skipped:` (kind `decided_elsewhere`, verdict `none`). The earlier lifecycle reason that used to repeat
    # the `no` is gone, so this key is the only thing that keeps the skipped run from reading as delivery.
    root, art = _red_story(result="skipped")
    try:
        check_eq("A-K5 (A-1): a `skipped` run row -> held, the stamp is not demanded", D.lifecycle_reasons(art), [])
        doc = D.assess(art)
        check_eq("A-K5 (A-1): ... and the verdict is `no`", doc["delivery_verdict"], "no")
        check_in("A-K5 (A-1): ... carried by the trace chain naming the skipped result", "run result 'skipped' is not terminal",
                 "\n".join(doc["reasons"]))
    finally:
        cleanup(root)

    # A-K5 (HF3-1): the stamp is demanded exactly of the cases the stamp can give (`case_stamp.instance_hold` == "")
    root, art = _red_story(result="passed")
    try:
        mpath = art / "work" / "automation-manifest.json"

        def verdict_as(word):
            manifest = json.loads(mpath.read_text(encoding="utf-8"))
            manifest["tests"][0]["critic_verdict"] = word
            mpath.write_text(json.dumps(manifest), encoding="utf-8")
            return "\n".join(D.lifecycle_reasons(art))

        check_in("A-K5: green + approved + a green row + the file Approved -> the stamp IS demanded", "step 8b", verdict_as("approved"))
        # m3's killer: `approved_with_fixes` is a legal verdict the stamp gives (F-2), so the lifecycle demands it too -
        # held as `not_approved` it would silently stop (the dead door the other way)
        check_in("A-K5 (F-2): `approved_with_fixes` + a green row + the file Approved -> the stamp IS demanded", "step 8b",
                 verdict_as("approved_with_fixes"))
        for word in ("rejected", "mystery"):
            check_eq(f"A-K5: a `{word}` verdict + green: the stamp cannot be given, so it is not demanded (was: a dead door)",
                     verdict_as(word), "")
        verdict_as("approved_with_fixes")
        _retarget(art, status="Automated")
        check_eq("A-K5 (F-2): `approved_with_fixes` + a green row + the file Automated -> quiet", D.lifecycle_reasons(art), [])
        _retarget(art, status="Approved")
        # B1 (critic t-1254): a dead row (`SUPERSEDED DUPLICATE`) is no instance of its case - it neither holds nor demands
        manifest = json.loads(mpath.read_text(encoding="utf-8"))
        live = manifest["tests"][0]
        dead = dict(live, instance_id="tests/test_coupon.py::test_old", note="SUPERSEDED DUPLICATE - split")
        manifest["tests"] = [live, dead]
        mpath.write_text(json.dumps(manifest), encoding="utf-8")
        check_eq("B1: a dead green row with NO run beside a live one with a green run: the stamp is demanded ONCE, for the live one",
                 len(D.lifecycle_reasons(art)), 1)
        manifest["tests"] = [dead]
        mpath.write_text(json.dumps(manifest), encoding="utf-8")
        check_eq("B1: a case whose only row is dead demands nothing (the stamp has no evidence to give)", D.lifecycle_reasons(art), [])
        manifest["tests"] = [live, dead]
        mpath.write_text(json.dumps(manifest), encoding="utf-8")
        report = json.loads((art / "work" / "run-report.json").read_text(encoding="utf-8"))
        report["results"].append({"test": "tests/test_coupon.py::test_old", "case": "TC-001", "result": "failed", "attempt_id": "a1"})
        (art / "work" / "run-report.json").write_text(json.dumps(report), encoding="utf-8")
        check_in("B1: a RED row of a dead instance holds nothing: the stamp is still demanded", "step 8b", "\n".join(D.lifecycle_reasons(art)))
        manifest["tests"] = [live]
        mpath.write_text(json.dumps(manifest), encoding="utf-8")

        # M1 (critic t-1254; FR-59): the join cannot be built -> ONE reason names what could not be established; the gate
        # holds neither every case (a stamp reason would vanish for a case the stamp can give) nor none (a false sentence)
        import case_stamp as CS
        was = CS.instance_hold

        def broken(entry, index):
            raise RuntimeError("the run join is broken")
        CS.instance_hold = broken
        try:
            said = D.lifecycle_reasons(art)
            check_eq("M1: a raising predicate -> exactly ONE reason", len(said), 1)
            check("M1: ... it names what could not be established and the cause", "case lifecycle not checked" in said[0]
                  and "the run join is broken" in said[0] and "RuntimeError" in said[0], said[0])
            check_eq("M1: ... it is a no, never a yes", D.assess(art)["delivery_verdict"], "no")
        finally:
            CS.instance_hold = was
        check_eq("M1 control: the same story with the predicate restored: the ordinary stamp reason, not the unestablished one",
                 ["step 8b" in r and "not checked" not in r for r in D.lifecycle_reasons(art)], [True])
    finally:
        cleanup(root)

    # K4 a green run without the stamp: the stamp is still demanded (and the verdict is no for it)
    root, art = _red_story(result="passed")
    try:
        said = "\n".join(D.lifecycle_reasons(art))
        check_in("K4: a green run, case Approved -> the stamp is demanded", "step 8b", said)
        check_eq("K4: and the verdict is no", D.assess(art)["delivery_verdict"], "no")
        check_eq("K4: a green run, case Automated -> quiet", D.lifecycle_reasons(_retarget(art, status="Automated")), [])
        # a red row of ANOTHER test holds nothing here (the case is back to Approved first)
        _retarget(art, status="Approved")
        report = json.loads((art / "work" / "run-report.json").read_text(encoding="utf-8"))
        report["results"].append({"test": "tests/test_other.py::test_unrelated", "case": "TC-009", "result": "failed",
                                  "attempt_id": "a1"})
        (art / "work" / "run-report.json").write_text(json.dumps(report), encoding="utf-8")
        check_in("K4: another instance's red run does not hold this test's case", "step 8b",
                 "\n".join(D.lifecycle_reasons(art)))
    finally:
        cleanup(root)

    # t-419 F1 (critic t-418, real data TP1-15045): a PASSED `x[unparseable]` whose manifest `test` is the bare function,
    # beside a red sibling `x[json]` of another case. The case is not held: the stamp is still demanded (the old widening
    # read the sibling's red as this instance's, and the case lost its lifecycle reason along with its stamp).
    root, art = _red_story(result="passed")
    try:
        mpath = art / "work" / "automation-manifest.json"
        manifest = json.loads(mpath.read_text(encoding="utf-8"))
        manifest["tests"][0].pop("instance_id", None)
        manifest["tests"][0].update(test=RED_ID, parameter="unparseable")
        mpath.write_text(json.dumps(manifest), encoding="utf-8")
        report = json.loads((art / "work" / "run-report.json").read_text(encoding="utf-8"))
        report["results"] = [
            {"test": RED_ID + "[unparseable]", "instance_id": "test_cap_rejected[unparseable]", "case": "TC-001",
             "result": "passed", "attempt_id": "a1"},
            {"test": RED_ID + "[json]", "instance_id": "test_cap_rejected[json]", "case": "TC-009", "result": "failed",
             "attempt_id": "a1"}]
        (art / "work" / "run-report.json").write_text(json.dumps(report), encoding="utf-8")
        check_in("F1 t-419: a red sibling parameter holds nothing: the stamp is still demanded", "step 8b",
                 "\n".join(D.lifecycle_reasons(art)))
        report["results"][0]["result"] = "failed"
        (art / "work" / "run-report.json").write_text(json.dumps(report), encoding="utf-8")
        check_eq("F1 t-419 control: its OWN parameter red holds the case", D.lifecycle_reasons(art), [])
    finally:
        cleanup(root)

    # edge 5: a case with two instances, one red - the case is held whole, as `case_stamp` holds its stamp
    root, art = _red_story()
    try:
        mpath = art / "work" / "automation-manifest.json"
        manifest = json.loads(mpath.read_text(encoding="utf-8"))
        manifest["tests"].append(dict(manifest["tests"][0], instance_id="tests/test_coupon.py::test_other_green"))
        mpath.write_text(json.dumps(manifest), encoding="utf-8")
        report = json.loads((art / "work" / "run-report.json").read_text(encoding="utf-8"))
        report["results"].append({"test": "tests/test_coupon.py::test_other_green", "case": "TC-001", "result": "passed",
                                  "attempt_id": "a1"})
        (art / "work" / "run-report.json").write_text(json.dumps(report), encoding="utf-8")
        check_eq("edge 5: one red of two instances holds the case: no lifecycle reason", D.lifecycle_reasons(art), [])
        check("edge 5: and the verdict is not yes", D.assess(art)["delivery_verdict"] != "yes")
        # the repaired run lifts the hold: the stamp is demanded again
        report["results"][0]["result"] = "passed"
        (art / "work" / "run-report.json").write_text(json.dumps(report), encoding="utf-8")
        check_in("edge 5: both green -> the stamp is demanded again", "step 8b", "\n".join(D.lifecycle_reasons(art)))
    finally:
        cleanup(root)

    # the pinned branch is NOT skipped: its proof is the manifest's `case_version_links`, written by the automator and
    # independent of the run, so a red run does not make it impossible (the reasoning of the skip does not hold there)
    import hashlib
    root, art = _red_story()
    try:
        snapshot = art / "state" / "case-versions" / "TC-001" / "snapshot.md"
        snapshot.parent.mkdir(parents=True)
        snapshot.write_text((art / "work" / "test-cases" / "checkout" / "TC-001.md").read_text(encoding="utf-8"),
                            encoding="utf-8")
        digest = hashlib.sha256(snapshot.read_bytes()).hexdigest()
        (art / "state" / "story-case-links.json").write_text(json.dumps({"links": [
            {"case_id": "TC-001", "version": "cv_" + digest[:20], "content_hash": digest,
             "path": snapshot.relative_to(art).as_posix()}]}), encoding="utf-8")
        check_in("pinned: a red run still leaves the pinned-proof reason (the skip is not applied there)",
                 "lacks current pinned CaseVersion proof", "\n".join(D.lifecycle_reasons(art)))
    finally:
        cleanup(root)


def _retarget(art: Path, result: str = "", status: str = "") -> Path:
    """Rewrite the story's one run result and/or its case status in place; returns the same `art`."""
    if result:
        report = json.loads((art / "work" / "run-report.json").read_text(encoding="utf-8"))
        report["results"][0]["result"] = result
        (art / "work" / "run-report.json").write_text(json.dumps(report), encoding="utf-8")
    if status:
        case = art / "work" / "test-cases" / "checkout" / "TC-001.md"
        text = case.read_text(encoding="utf-8")
        for was in ("Approved", "Draft", "Review", "Automated"):
            text = text.replace(f"status: {was}", f"status: {status}")
        case.write_text(text, encoding="utf-8")
    return art


# ---------------------------------------------------------------------------------------------- t-311
# The fourth definition of "a failure that needs triage" (t-309 removed three): `triage_reasons` matched rows by
# the exact (instance_id, attempt), so on TP1-15045 (cmp2r) the analyst's `..[chromium]` rows did not bind to
# the run report's ids and gate B said "no verdict" for failures that HAD one; it also ignored a manual
# `inconclusive`, so a sign-in-page case with no verdict at all held nothing.
def _triage_run(report: dict, rows: list, answered: bool = False, cases: bool = False) -> list:
    """`D.triage_reasons` over a throw-away task holding exactly this run report and these triage rows. `answered`: the
    person's gate B answer (`accept`) is recorded for every case an ENV_ISSUE row binds to - the pipeline's own record, the
    only thing that lifts such a row (t-305 N8 attempt 2, F3; the triage row's own fields decide nothing)."""
    from harness import temp_dir
    task = temp_dir("qa-triage-bind-")
    try:
        (task / "work").mkdir()
        if answered or cases:
            # a failure speaks for a case through the run report's own row (or the manifest, which this task has none of)
            report = json.loads(json.dumps(report))
            for key in ("results", "current_results"):
                for index, row in enumerate(report.get(key) or []):
                    if isinstance(row, dict) and not row.get("case"):
                        row["case"] = f"TC-{900 + index}"
        (task / "work" / "run-report.json").write_text(json.dumps(report), encoding="utf-8")
        (task / "work" / "triage.json").write_text(json.dumps({"triage": rows}), encoding="utf-8")
        if answered:
            cases = sorted({c for _row, cs, _keys in D._triage_binding(D.gather(task), "ENV_ISSUE") for c in cs})
            (task / "pipeline.json").write_text(json.dumps({"stage_overrides": [
                {"stage": "S9", "match": f"stand gap: {case}", "decision": "accept - the person wrote: accept",
                 "at": "2026-10-03T10:00:00Z", "by": "human"} for case in cases]}), encoding="utf-8")
        return D.triage_reasons(task)
    finally:
        cleanup(task)


def _no_verdict(reasons: list) -> list:
    return [r for r in reasons if "has no verdict" in r]


def gate_b_triage_reads_the_one_definition() -> None:
    from test_s7_null_outcome import APP_BUG_A, APP_BUG_B, ENV_A, ENV_B, MANUAL, cmp2r_report, cmp2r_rows
    decided = list(cmp2r_rows())
    report = cmp2r_report()
    # K1: the cmp2r shape - 4 failed results (two UI ids WITHOUT the `[chromium]` the analyst wrote), 3 manual
    # `inconclusive`, 7 rows -> no failure is "without a verdict" and nothing else holds delivery. The two ENV_ISSUE rows
    # are lifted by the person's recorded gate B answer (t-305 N8 attempt 2, F3: not by a field of the analyst's row)
    check_eq("K1: seven rows answer four failed results and three inconclusive manual checks: no reason at all",
             _triage_run(report, decided, answered=True), [])
    unanswered = _triage_run(report, decided, answered=False, cases=True)
    check_eq("F3: the same rows with no recorded answer: exactly the ENV_ISSUE rows ask for one",
             len([r for r in unanswered if "is ENV_ISSUE with no recorded decision" in r]),
             len([r for r in decided if r["verdict"] == "ENV_ISSUE"]))
    check_eq("F3: ... and nothing else holds delivery", len([r for r in unanswered if "is ENV_ISSUE" not in r]), 0)
    # the controls: take a row away and exactly its failure loses its verdict (same function, same report)
    for dropped, label, shown in (
            (2, "the UI row `[chromium]` over a suffix-less id", ENV_A.replace("[chromium]", "")),
            (3, "the other UI row `[chromium]`", ENV_B.replace("[chromium]", "")),
            (0, "an API row", APP_BUG_A), (1, "the other API row", APP_BUG_B),
            (4, "a manual `inconclusive` (the old reading ignored it)", MANUAL[0]),
            (6, "the last manual `inconclusive`", MANUAL[2])):
        said = _no_verdict(_triage_run(report, [r for i, r in enumerate(decided) if i != dropped]))
        check_eq(f"K1 control: without {label}, one failure has no verdict and it is {shown}",
                 [shown in line for line in said], [True])
    check_eq("K3: no row at all -> every one of the 7 failures has no verdict (the old behaviour, kept)",
             len(_no_verdict(_triage_run(report, []))), 7)
    check_in("K3: ... a manual `inconclusive` among them, by its case id", MANUAL[1],
             "\n".join(_no_verdict(_triage_run(report, []))))
    # K4: a manual `inconclusive` with a verdict is bound whatever the row's other fields say; a failed result row
    # for a case already repaired holds nothing
    only_manual = {"current_results": [], "current_manual_checks": [{"case": MANUAL[0], "result": "inconclusive"}]}
    check_eq("K4: an inconclusive manual check with its row: bound", _no_verdict(_triage_run(only_manual, decided)), [])
    check_eq("K4: ... and without its row: no verdict", len(_no_verdict(_triage_run(only_manual, []))), 1)
    green = {"execution_status": "passed", "current_results": [{"instance_id": APP_BUG_A, "status": "passed"}],
             "current_manual_checks": [{"case": MANUAL[0], "result": "pass"}]}
    check_eq("K5: rows of failures that are green now are no reason of this kind (not a phantom)",
             _no_verdict(_triage_run(green, decided)), [])
    # a manual failure that no row could name is still a failure, said, never dropped
    nameless = {"current_results": [], "current_manual_checks": [{"result": "inconclusive"}]}
    check_in("K6: a failing manual check with no case/instance/test is a reason that says so",
             "manual check #1 has no case, instance_id or test", "\n".join(_triage_run(nameless, decided)))
    # t-319 (t-311 Q1, K7 of the fix node): a manual check nobody judged is the REVIEW's, and only that reason - the
    # `triage:manual:` family of references/delivery-reason-owners.json; every other `triage:` reason keeps `factory`
    check_eq("K6/K7: ... which is the manual no-verdict reason: its owner is `review` (the `triage:manual:` family)",
             D.reason_record("\n".join(_triage_run(nameless, decided)))["owner"], "review")
    named_manual = [r for r in _triage_run(report, [r for i, r in enumerate(decided) if i != 4]) if "has no verdict" in r]
    check_eq("K7: a NAMED manual `inconclusive` with no row: the same family, owner `review`",
             [(r.startswith("triage:manual: "), D.reason_record(r)["owner"]) for r in named_manual], [(True, "review")])
    nameless_result = {"current_results": [{"status": "failed", "nodeid": "z"}], "current_manual_checks": []}
    said = _triage_run(nameless_result, [])
    check_eq("F4: a failed RESULT row with no name is a reason that says so, and it is the factory's (not `review`)",
             [("has no instance_id, test_instance_id, test_id or test" in r, r.startswith("triage: "), D.reason_record(r)["owner"])
              for r in said],
             [(True, True, "factory")])
    # t-323 BL-2 (critic t-327): a failed result row carrying only a `case` is just as nameless - fail-closed
    case_only = _triage_run({"current_results": [{"status": "failed", "case": "C1"}, {"status": "failed", "case": "C1"}],
                             "current_manual_checks": []}, [])
    check_eq("BL-2: two case-only failed result rows are two nameless failures, the factory's",
             [("has no instance_id, test_instance_id, test_id or test" in r, D.reason_record(r)["owner"]) for r in case_only],
             [(True, "factory")] * 2)
    result_said = _no_verdict(_triage_run(report, [r for i, r in enumerate(decided) if i != 0]))
    check_eq("K7 control: a failed RESULT with no verdict keeps the owner `factory`",
             [(r.startswith("triage: "), D.reason_record(r)["owner"]) for r in result_said], [(True, "factory")])
    other = [r for r in _triage_run({"current_results": [{"instance_id": "x", "status": "failed"}], "current_manual_checks": []},
                                   [{"instance_id": "x", "verdict": "ENV_ISSUE"}]) if r.startswith("triage:")]
    check_eq("K7 control: an undecided ENV_ISSUE is still `factory`", [D.reason_record(r)["owner"] for r in other], ["factory"])


def triage_rows_bind_by_spelling_one_side_at_a_time() -> None:
    def result(name: str) -> dict:
        return {"instance_id": name, "status": "failed"}

    def row(name: str, **extra) -> dict:
        return dict({"instance_id": name, "verdict": "APP_BUG", "evidence": "evidence/x.json"}, **extra)

    def run(failed: list, rows: list) -> list:
        return _triage_run({"current_results": [result(n) for n in failed], "current_manual_checks": []}, rows)

    # a row with its parameter over a failure without it, and the reverse
    check_eq("a row `x[chromium]` answers the failure `x`", run(["x"], [row("x[chromium]")]), [])
    check_eq("a row `x` answers the failure `x[chromium]`", run(["x[chromium]"], [row("x")]), [])
    # siblings: each failure binds the row that names it EXACTLY, and nobody else's
    check_eq("two siblings, two exact rows: bound", run(["x[json]", "x[multi]"], [row("x[json]"), row("x[multi]")]), [])
    said = _no_verdict(run(["x[json]", "x[multi]"], [row("x[json]")]))
    check_eq("two siblings, one row: the other sibling has no verdict - never covered by the base", len(said), 1)
    check_in("... and it is the one with no row", "x[multi]", said[0])
    check_eq("a row `x[json]` is never a verdict for the failure `x[multi]`",
             len(_no_verdict(run(["x[multi]"], [row("x[json]")]))), 1)
    # the base: a row `x` over two parameterised failures is a verdict for neither, and says why (never silent)
    reasons = run(["x[json]", "x[multi]"], [row("x")])
    check_eq("the base row over two siblings: no failure reads 'no verdict' for a row that names it",
             _no_verdict(reasons), [])
    check_eq("... one reason, naming the row and both failures",
             [("names 2 failures" in r and "x[json]" in r and "x[multi]" in r) for r in reasons], [True])
    check_eq("the base row over ONE parameterised failure binds (the only candidate)", run(["x[json]"], [row("x")]), [])
    # exact beats spelling: with both `x` and `x[json]` failing, a row `x[json]` covers only the second
    said = _no_verdict(run(["x", "x[json]"], [row("x[json]")]))
    check_eq("failures `x` and `x[json]`, a row `x[json]`: the base failure has no verdict, once",
             [line.split(" has no verdict")[0].rsplit(" ", 1)[1] for line in said], ["x"])
    check_eq("failures `x` and `x[json]`, a row `x` and a row `x[json]`: both bound",
             run(["x", "x[json]"], [row("x"), row("x[json]")]), [])
    # edges of the ids: two groups stripped once, an empty id, a case id is not an instance
    check_eq("a row `x[a][b]` does not answer the failure `x` (stripped once)", len(_no_verdict(run(["x"], [row("x[a][b]")]))), 1)
    check_eq("a row with no id names nothing", len(_no_verdict(run(["x"], [{"verdict": "APP_BUG", "evidence": "e"}]))), 1)
    check_eq("a row named by a case id does not cover an instance of that case", len(_no_verdict(_triage_run(
        {"current_results": [{"instance_id": "x", "case": "TC-1", "status": "failed"}], "current_manual_checks": []},
        [{"case": "TC-1", "verdict": "APP_BUG", "evidence": "e"}]))), 1)
    check_eq("the old substring guard holds: a row `i10` is no verdict for `i1`", len(_no_verdict(run(["i1"], [row("i10")]))), 1)
    check_eq("a legacy row that names its failure by `test` only still binds", run(["i1"], [{"test": "i1", "verdict": "APP_BUG", "evidence": "e"}]), [])


def triage_attempts_and_legacy_reports() -> None:
    def failed(attempt=None) -> dict:
        return dict({"instance_id": "t[p]", "status": "failed"}, **({"attempt_id": attempt} if attempt else {}))

    def row(attempt=None) -> dict:
        return dict({"instance_id": "t[p]", "verdict": "APP_BUG", "evidence": "e"}, **({"attempt_id": attempt} if attempt else {}))

    def run(results: list, rows: list) -> list:
        return _no_verdict(_triage_run({"current_results": results, "current_manual_checks": []}, rows))

    def run_with_history(rows: list) -> list:
        """the failure is attempt a1 while the report's history records a LATER attempt a2 of the instance"""
        return _no_verdict(_triage_run({"current_results": [failed("a1")], "current_manual_checks": [],
                                        "results": [failed("a1"), dict(failed("a2"), status="passed")]}, rows))

    check_eq("a row with no attempt answers the failure's latest attempt", run([failed("a2")], [row()]), [])
    check_eq("a row of the same attempt binds", run([failed("a2")], [row("a2")]), [])
    check_eq("a verdict of an OLDER attempt is not this failure's", len(run([failed("a2")], [row("a1")])), 1)
    check_eq("an older row beside the current one is history, not an ambiguity", run([failed("a2")], [row("a1"), row("a2")]), [])
    check_eq("an attempt-less row beside the current one: the named one wins", run([failed("a2")], [row(), row("a2")]), [])
    # t-323 F1: two rows for ONE failure are one class with its own reason (it used to read "no verdict")
    two = _triage_run({"current_results": [failed("a2")], "current_manual_checks": []}, [row("a2"), row("a2")])
    check_eq("CONTROL: two rows of the same attempt are refused as 'N rows answer the failure; keep one', not as 'no verdict'",
             ([r for r in two if " rows answer the failure t[p] in triage.json; keep one" in r].__len__(),
              len(_no_verdict(two))), (1, 0))
    check_eq("F3: a row with no attempt never answers an older recorded attempt, the row that names it does",
             (len(run_with_history([row()])), len(run_with_history([row("a1")]))), (1, 0))
    check_eq("a failure with no attempt takes a row of any attempt", run([failed()], [row("a1")]), [])
    # a legacy report (results[] only, `result` words) must not hide its failures
    legacy = {"results": [{"test": "tests/test_a.py::test_a", "case": "TC-1", "result": "failed"},
                          {"test": "tests/test_a.py::test_b", "case": "TC-2", "result": "passed"}], "manual_checks": []}
    check_eq("a report with no `current_results` is read through the contract's projection: its failure shows",
             len(_no_verdict(_triage_run(legacy, []))), 1)
    check_eq("... and its row binds", _no_verdict(_triage_run(
        legacy, [{"test": "tests/test_a.py::test_a", "verdict": "APP_BUG", "evidence": "e"}])), [])
    check_eq("an empty report asks for nothing", _triage_run({}, []), [])


def a_whole_case_unconfirmed_row_is_a_debt_not_a_hold() -> None:
    """t-271 D2: a WHOLE-case `unresolved[]` row whose reason is `expectation_unconfirmed` (it names its question) is the
    person's debt. Before, `completeness_reasons` called the word "outside the closed list" and held delivery."""
    root = temp_project("qa-factory-delivery-whole-unconfirmed-")
    try:
        art = root / "qa-factory" / "artifacts" / "QA-1"
        shutil.copytree(GOOD, art)
        path = C.artifact(art, "automation-manifest.json")
        manifest = C.load_json(path)
        manifest["unresolved"] = [{"case": "TC-001", "reason": "wishful", "question": "Q7"}]
        path.write_text(json.dumps(manifest), encoding="utf-8")
        check_in("CONTROL: an invented reason on the same row is still `outside the closed list`", "outside",
                 [r for r in D.completeness_reasons(art) if "TC-001" in r])
        manifest["unresolved"] = [{"case": "TC-001", "reason": "expectation_unconfirmed", "question": "Q7", "observed": "403"}]
        path.write_text(json.dumps(manifest), encoding="utf-8")
        check_eq("D2: the contract's word is no completeness reason", [r for r in D.completeness_reasons(art) if "TC-001" in r], [])
        doc = D.assess(art)
        # t-305 N8 (Q5 i, P20): it holds NOTHING (no reason) and it is not `yes` either - the expectation nobody confirmed is a
        # check left with the person, which is the third verdict
        check_eq("D2: no reason holds it, and the verdict is the third word", (doc["reasons"], doc["delivery_verdict"], doc["delivery_ready"]),
                 ([], "after_checks", False))
        states = {r["ref"]: r["state"] for r in doc["rows"]}
        check_eq("D2: the plan row of the case reads the person's-debt state, never `not_executed`", states["TS-1"], "not_verified:expectation_unconfirmed")
        check_eq("D2: it is listed under the person's debts", [d["ref"] for d in doc["person_debts"]], ["TS-1"])
        check_in("D2: with the question and the value seen", "Needed: your answer to Q7", doc["person_debts"][0]["detail"])
        check_in("D2: ... and what the test saw", "observed: 403", doc["person_debts"][0]["detail"])
        print("K-D2 | whole-case row {TC-001, expectation_unconfirmed, Q7}: completeness reasons []; delivery_ready "
              f"{doc['delivery_ready']}; ledger TS-1 = {states['TS-1']}; person_debts {[d['ref'] for d in doc['person_debts']]}")
    finally:
        cleanup(root)


def an_unconfirmed_expectation_holds_nothing() -> None:
    """t-227c (P20, F7): a Then whose expected value nobody confirmed reads `not_verified:expectation_unconfirmed`.
    It is a gap in the report, listed under the person's name ("Needed: your answer to Q7") - NOT a reason: a
    reason holds `delivery_ready`, and an unverified check is not a found discrepancy (FR-21/FR-22)."""
    row = {"ref": "TS-1", "state": L_STATE, "detail": "TC-001 Then 4: expected value unconfirmed, observed: 403. Needed: your answer to Q7"}
    check_eq("ledger_reasons holds nothing for the state (the `blocking` set does not name it)", D.ledger_reasons({"rows": [row]}), [])
    check("CONTROL: the same function does hold a failed row", bool(D.ledger_reasons({"rows": [dict(row, state="failed:APP_BUG")]})))
    root = temp_project("qa-factory-delivery-unconfirmed-")
    try:
        art = root / "qa-factory" / "artifacts" / "QA-1"
        shutil.copytree(GOOD, art)
        before = D.assess(art)
        check_eq("CONTROL: the good set delivers", (before["delivery_ready"], before["reasons"]), (True, []))
        check_eq("and lists nobody's debt", before["person_debts"], [])
        path = C.artifact(art, "automation-manifest.json")
        manifest = C.load_json(path)
        manifest["then_bindings"] = [{"case": "TC-001", "then": 1, "instance_id": None, "assertion_ref": None, "status": "unresolved",
                                      "reason": "expectation_unconfirmed", "question": "Q7", "observed": "403"}]
        path.write_text(json.dumps(manifest), encoding="utf-8")
        doc = D.assess(art)
        states = {r["ref"]: r["state"] for r in doc["rows"]}
        check_eq("the plan row of the case reads the new state, not `passed_green`", states["TS-1"], "not_verified:expectation_unconfirmed")
        check_eq("F7 + Q5 (i): it is the third verdict - no reason holds delivery, and it is not `yes`",
                 (doc["delivery_verdict"], doc["delivery_ready"]), ("after_checks", False))
        check_eq("no reason is made of it", doc["reasons"], [])
        check_eq("no owner is blamed for it (no reason record, no factory defect)", doc["reason_records"], [])
        check_eq("it is listed under the person's debts", [d["ref"] for d in doc["person_debts"]], ["TS-1"])
        check_in("with what is wanted of them, in the task's own terms (FR-20)", "Needed: your answer to Q7", doc["person_debts"][0]["detail"])
        written = json.loads((art / "work" / "ledger.json").read_text(encoding="utf-8"))
        check_eq("and the written ledger says the same",
                 (written["delivery_verdict"], written["delivery_ready"], len(written["person_debts"])), ("after_checks", False, 1))
        check_in("ledger.md shows it under its own heading", "Left with you (nothing blocks on it)",
                 (art / "work" / "ledger.md").read_text(encoding="utf-8"))
        cli = run_script("check_delivery.py", art)
        check_eq("the CLI exits 1 (exit 0 is `yes` only, C4) and prints the word", (cli.returncode, "delivery_ready: after_checks" in cli.stdout),
                 (1, True))
        check_in("and the person is shown the question", "Needed: your answer to Q7", cli.stdout)
        # a red Then of the same case is still the red's: the new word never softens a failure (C2's order)
        report = C.load_json(art / "work" / "run-report.json")
        report["current_results"] = [{"instance_id": "test_cap_rejected", "case": "TC-001", "status": "failed", "reason": "AssertionError"}]
        (art / "work" / "run-report.json").write_text(json.dumps(report), encoding="utf-8")
        red = D.assess(art)
        check("a failed run of the same case reads failed and holds delivery",
              {r["ref"]: r["state"] for r in red["rows"]}["TS-1"].startswith("failed:") and red["delivery_ready"] is False,
              str({r["ref"]: r["state"] for r in red["rows"]}))
    finally:
        cleanup(root)


L_STATE = "not_verified:expectation_unconfirmed"


TEST_SRC = "def test_search():\n    assert 1 + 1 == 2\n"


def delivery_fixture(prefix: str) -> tuple:
    """A story whose one test row names a REAL file under a real project (the current bytes of a
    row's test have one reader, `proof_level`, and it reads the file), a pinned case version, a live
    receipt written for those very bytes and an obligation binding that names it — and no
    `tests[].sensitivity_proof`, which is the shape 0.7.9 published.
    Returns (root, task, receipt body, manifest, case version, receipt ref)."""
    import hashlib

    from harness import temp_dir, use_project
    root = temp_dir(prefix)
    (root / "qa-factory").mkdir()
    (root / "qa-factory" / "config.json").write_text(json.dumps({"tests_root": "tests"}), encoding="utf-8")
    (root / "tests").mkdir()
    (root / "tests" / "test_search.py").write_text(TEST_SRC, encoding="utf-8")
    use_project(root)
    task = root / "TP2-2553"
    snapshot = task / "state" / "case-versions" / "TC-009" / "snapshot.md"
    snapshot.parent.mkdir(parents=True)
    snapshot.write_text("---\nid: TC-009\n---\n", encoding="utf-8")
    content_hash = hashlib.sha256(snapshot.read_bytes()).hexdigest()
    version = "cv_" + content_hash[:20]
    (task / "state" / "story-case-links.json").write_text(json.dumps({"links": [
        {"case_id": "TC-009", "version": version, "content_hash": content_hash,
         "path": snapshot.relative_to(task).as_posix()}]}), encoding="utf-8")
    proof = {"instance_id": "test_search[eu]", "case_version": version,
             "test_content_hash": hashlib.sha256((root / "tests" / "test_search.py").read_bytes()).hexdigest(),
             "source_revision": "s1", "build_id": "b1", "mutation": "return None",
             "expected_assertion_failure": "no results", "actual_failure": "AssertionError",
             "assertion_location": "tests/test_search.py:9", "failure_kind": "assertion",
             "restoration_evidence": "main tree unchanged", "immutable": True,
             "receipt_hash": "h1"}
    receipts = task / "work" / "sensitivity-receipts"
    receipts.mkdir(parents=True)
    (receipts / "r.json").write_text(json.dumps(proof), encoding="utf-8")
    ref = "work/sensitivity-receipts/r.json"
    manifest = {"tests": [{"case": "TC-009", "covers": ["TC-009"], "file": "tests/test_search.py",
                           "instance_id": "test_search[eu]", "sensitivity_proof_required": True,
                           "case_version_links": [{"case_id": "TC-009", "version": version}]}],
                "obligation_bindings": [{"obligation_id": "TS-3-O1", "sensitivity": "proven",
                                         "instance_ids": ["test_search[eu]"],
                                         "probe_receipt_ref": ref}]}
    (task / "work" / "automation-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return root, task, proof, manifest, version, ref


def env_reset() -> None:
    """`use_project` pins hooklib's project root inside this process; give it back."""
    import os
    os.environ.pop("CLAUDE_PROJECT_DIR", None)
    import hooklib
    hooklib._PROJECT_ROOT_CACHE = None


def receipt_in_the_binding_only() -> None:
    """TP2-2553: the probe wrote the receipt where delivery does not look.

    `red_sandbox.py --probe` of 0.7.9 published `obligation_bindings[].probe_receipt_ref` and
    nothing else, while this aggregator read `tests[].sensitivity_proof.receipt_ref`. Four
    hash-bound receipts sat on disk and gate B asked the person for four waivers over missing
    proof, owner `product`. The fallback finds them; the gap that remains is ours."""
    root, task, proof, manifest, version, ref = delivery_fixture("qa-delivery-binding-receipt-")
    receipts = task / "work" / "sensitivity-receipts"
    try:
        check_not_in("the proof in the binding is not a missing proof",
                     "requires current sensitivity proof",
                     "\n".join(D.case_version_reasons(task)))
        findings = D.binding_proof_findings(task)
        check_eq("it is one factory finding instead", len(findings), 1)
        check_eq("owned by us, never by the person", findings[0]["owner"], "factory")
        check_in("naming the binding the proof was found through", "TS-3-O1", findings[0]["detail"])
        check_in("and what the probe failed to write", "tests[].sensitivity_proof",
                 findings[0]["detail"])

        # A row that carries its own ref is untouched by the fallback, and a receipt that is
        # wrong is still wrong wherever it was found — with both places named.
        manifest["obligation_bindings"][0]["probe_receipt_ref"] = "work/sensitivity-receipts/gone.json"
        (task / "work" / "automation-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        check_in("with no receipt anywhere the reason stands",
                 "requires current sensitivity proof", "\n".join(D.case_version_reasons(task)))
        check_eq("and it is not a factory finding", D.binding_proof_findings(task), [])

        (receipts / "bad.json").write_text(json.dumps(dict(proof, failure_kind="collection")),
                                           encoding="utf-8")
        manifest["obligation_bindings"][0]["probe_receipt_ref"] = "work/sensitivity-receipts/bad.json"
        (task / "work" / "automation-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        said = "\n".join(D.case_version_reasons(task))
        check_in("a bad receipt in the binding is still a reason", "controlled assertion failure", said)
        check_in("and the reason says both places were looked in", "obligation binding TS-3-O1", said)
    finally:
        env_reset()
        cleanup(root)


def levels_in_delivery() -> None:
    """D-0010/D-0012 at delivery: one predicate, one reader of receipts, and a missing HIGHER level
    is never a reason. A legacy mutable probe record is refused with the door named."""
    from harness import temp_project
    import shutil
    root, task, proof, manifest, version, ref = delivery_fixture("qa-delivery-levels-")

    def reasons() -> str:
        (task / "work" / "automation-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        return "\n".join(D.case_version_reasons(task))

    try:
        # A live receipt is all a new or changed test is asked for: nothing about the product level.
        proof.update(proof_level="live", probe_tool="probe_by_code.py", mutation_kind="assertion")
        (task / "work" / "sensitivity-receipts" / "r.json").write_text(json.dumps(proof), encoding="utf-8")
        said = reasons()
        check_not_in("a live receipt satisfies the requirement", "requires current sensitivity proof", said)
        check_not_in("and no higher level is asked for", "catches a broken product", said)
        check_not_in("nor the product's name", "red_sandbox", said)

        # No receipt at all: the reason stands, owned by the factory, and starts as it always did.
        manifest["obligation_bindings"][0]["probe_receipt_ref"] = "work/sensitivity-receipts/gone.json"
        said = reasons()
        check_in("no receipt anywhere is a reason", "requires current sensitivity proof", said)
        record = D.reason_record(next(line for line in said.splitlines() if "sensitivity proof" in line))
        check_eq("owned by the factory", record["owner"], "factory")
        check_in("and it starts with the instance", "test instance test_search[eu] requires", said)

        # A legacy mutable probe record (probe_by_code before receipts): valid for the window, invalid
        # here, and the reason names the rerun door — not "must identify an immutable receipt".
        mutable = dict(proof, immutable=False)
        mutable.pop("receipt_hash")
        (task / "work" / "sensitivity-receipts" / "old.json").write_text(json.dumps(mutable), encoding="utf-8")
        manifest["obligation_bindings"][0]["probe_receipt_ref"] = "work/sensitivity-receipts/old.json"
        said = reasons()
        check_in("a mutable record names the rerun door",
                 "its live-check record predates receipts; rerun probe_by_code.py --instance test_search[eu]", said)
        check_not_in("and not the receipt contract's own wording", "must identify an immutable receipt", said)
        line = next(x for x in said.splitlines() if "predates receipts" in x)
        check("the reason still starts 'test instance '", line.startswith("test instance "), line)
        check_eq("and belongs to the factory", D.reason_record(line)["owner"], "factory")

        # Unchanged and handed rows are never asked, whatever the flags say (one predicate).
        manifest["tests"][0].update(sensitivity_proof_required=False, new_or_changed=False,
                                    change_disposition="unchanged")
        check_not_in("an unchanged test is not asked for a proof", "requires current sensitivity proof", reasons())
        check_eq("nor is it a finding", D.binding_proof_findings(task), [])
        manifest["tests"][0].update(new_or_changed=True, change_disposition="new_or_changed")
        manifest["unresolved"] = [{"case": "TC-009", "reason": "handed_to_person", "detail": "api: run it yourself"}]
        check_not_in("a handed test is not asked for a proof", "requires current sensitivity proof", reasons())
        check_eq("and it is not a finding", D.binding_proof_findings(task), [])
    finally:
        env_reset()
        cleanup(root)

    # --- the verdicts at delivery (FR-35, D-0013, FR-19) -----------------------------------------
    check_eq("review_unverified never blocks delivery",
             D.ledger_reasons({"rows": [{"ref": "t", "state": "review_unverified", "detail": "x"}]}), [])
    check("review_rejected still blocks",
          bool(D.ledger_reasons({"rows": [{"ref": "t", "state": "review_rejected", "detail": "x"}]})))
    said = D.ledger_reasons({"rows": [{"ref": "t", "state": "review_unrecognised:maybe", "detail": "x"}]})
    check_eq("an unrecognised verdict blocks", len(said), 1)
    check_eq("as a defect of the factory, never the critic's rejection",
             D.reason_record(said[0])["owner"], "factory")
    check_eq("review_rejected is the review's", D.reason_record(
        D.ledger_reasons({"rows": [{"ref": "t", "state": "review_rejected", "detail": "x"}]})[0])["owner"], "review")
    check_eq("review_unverified is owned (the person's debt)", D.OWNER_BY_LEDGER_STATE["review_unverified"],
             "environment")
    check_eq("and so is review_unrecognised", D.OWNER_BY_LEDGER_STATE["review_unrecognised"], "factory")
    check_eq("its owner is resolved from the state word",
             D.reason_owner("ledger: t is `review_unverified` (x)"), "environment")

    art_root = temp_project("qa-factory-delivery-verdicts-")
    try:
        art = art_root / "qa-factory" / "artifacts" / "QA-1"
        shutil.copytree(GOOD, art)
        mpath = art / "work" / "automation-manifest.json"
        base = C.load_json(mpath)
        # t-305 N8 (Q5 ii): a test the code critic could not verify is no longer `yes` (P21: not all checked) and not `no`
        # either: it is the third verdict, with the test listed as an item left with the person
        for verdict, word, owner in (("approved", "yes", None), ("unverified", "after_checks", None),
                                     ("rejected", "no", "review"), ("Unverified", "no", "factory")):
            data = json.loads(json.dumps(base))
            data["tests"][0]["critic_verdict"] = verdict
            if verdict == "unverified":
                data["tests"][0]["sensitivity_proof_missing_reason"] = "the stand was down while probing"
            mpath.write_text(json.dumps(data), encoding="utf-8")
            doc = D.assess(art)
            ready = word == "yes"
            check_eq(f"e2e: verdict {verdict!r} -> the word {word}", doc["delivery_verdict"], word)
            check_eq(f"e2e: verdict {verdict!r} -> delivery_ready {ready} (the bool of the word)", doc["delivery_ready"], ready)
            check_eq(f"e2e: verdict {verdict!r} -> blocked_by",
                     [o for o in doc["blocked_by"]], [owner] if owner else [])
            if verdict == "unverified":
                summary = C.load_json(art / "work" / "delivery-summary.json")
                check_eq("e2e: the unverified test is still on the summary's data",
                         [r["why"] for r in summary["unverified_by_critic"]], ["the stand was down while probing"])
                item = [i for i in doc["left_items"] if i["counts"]]
                check_eq("e2e: and is ONE item left with the person: its case, its kind, its test",
                         [(i["ref"], i["kind"], i["tests"]) for i in item], [("TC-001", "review_unverified", ["TC-001"])])
                text = (art / "work" / "delivery-summary.md").read_text(encoding="utf-8")
                check_not_in("e2e: the summary builds no list of its own (the report's section is quoted, F9)",
                             "the code critic could not verify these tests", text)
                check_not_in("e2e: the release verdict is the scribe's one statement (FR-10)",
                             "Not ready for release", text)
            if verdict == "Unverified":
                check_in("e2e: the unrecognised word is named", "review_unrecognised:Unverified",
                         "\n".join(doc["reasons"]))

        # D-0013 and the case lifecycle: an unverified green test has no receipt, so its case is never
        # stamped Automated; that is the person's debt, not a lifecycle contradiction. An approved
        # one with the same Draft case still blocks.
        case = art / "work" / "test-cases" / "checkout" / "TC-001.md"
        original = case.read_text(encoding="utf-8")
        case.write_text(original.replace("status: Automated", "status: Draft"), encoding="utf-8")
        for verdict, ready in (("unverified", True), ("approved", False)):
            data = json.loads(json.dumps(base))
            data["tests"][0]["critic_verdict"] = verdict
            data["tests"][0]["sensitivity_proof_missing_reason"] = "the stand was down while probing"
            mpath.write_text(json.dumps(data), encoding="utf-8")
            said = "\n".join(D.lifecycle_reasons(art))
            doc = D.assess(art)
            check_eq(f"lifecycle: {verdict} green test + Draft case -> "
                     f"{'no case reason' if ready else 'a case reason'}", "step 8b" not in said, ready)
            # "ready" here means: no case reason holds it. The unverified test is the third verdict (not `yes`), the approved
            # one with the Draft case is `no`.
            check_eq(f"lifecycle e2e: {verdict} green + Draft case -> the word",
                     doc["delivery_verdict"], "after_checks" if ready else "no")
            if ready:
                check_eq("lifecycle e2e: the unverified test is an item left with the person, and nothing blocks",
                         ([i["ref"] for i in doc["left_items"] if i["counts"]], doc["reasons"]), (["TC-001"], []))
        case.write_text(original, encoding="utf-8")

        # F1 (D-0013 wins over "an absent live check blocks"): on a PINNED story a new test with no
        # receipt is a proof reason when approved and the person's debt when unverified.
        import hashlib
        links, versions = [], {}
        for cid in ("TC-001", "TC-002"):          # every case of the story is pinned, as its cases stand
            snapshot = art / "state" / "case-versions" / cid / "snapshot.md"
            snapshot.parent.mkdir(parents=True)
            snapshot.write_text((art / "work" / "test-cases" / "checkout" / f"{cid}.md").read_text(encoding="utf-8"),
                                encoding="utf-8")
            digest = hashlib.sha256(snapshot.read_bytes()).hexdigest()
            versions[cid] = "cv_" + digest[:20]
            links.append({"case_id": cid, "version": versions[cid], "content_hash": digest,
                          "path": snapshot.relative_to(art).as_posix()})
        version = versions["TC-001"]
        (art / "state" / "story-case-links.json").write_text(json.dumps({"links": links}), encoding="utf-8")
        for verdict, ready in (("unverified", True), ("approved", False), ("approved_with_fixes", False)):
            data = json.loads(json.dumps(base))
            test = data["tests"][0]
            test.update(critic_verdict=verdict, new_or_changed=True, instance_id="test_cap_rejected",
                        case_version_links=[{"case_id": "TC-001", "version": version}])
            if verdict == "approved_with_fixes":
                test["fix_notes"] = ["rename"]
            if verdict == "unverified":
                test["sensitivity_proof_missing_reason"] = "the probe tool gave no receipt"
            mpath.write_text(json.dumps(data), encoding="utf-8")
            said = "\n".join(D.case_version_reasons(art))
            doc = D.assess(art)
            check_eq(f"pinned: {verdict} new test, no receipt -> proof reason present", "requires current sensitivity proof" in said,
                     not ready)
            check_eq(f"pinned e2e: {verdict} new test, no receipt -> the word",
                     doc["delivery_verdict"], "after_checks" if ready else "no")
            if ready:
                summary = C.load_json(art / "work" / "delivery-summary.json")
                check_eq("pinned e2e: the debt is listed with the critic's reason (the summary's data)",
                         [r["why"] for r in summary["unverified_by_critic"]], ["the probe tool gave no receipt"])
                check_eq("pinned e2e: and no other reason holds delivery", doc["reasons"], [])

        # F3 (the critic's flaky probe): a FLAKY-fixed row is green in the ledger, yet the verdict is
        # still unverified, so the debt is still listed.
        data = json.loads(json.dumps(base))
        data["tests"][0]["critic_verdict"] = "unverified"
        mpath.write_text(json.dumps(data), encoding="utf-8")
        (art / "work" / "triage.json").write_text(json.dumps({"triage": [{
            "test": "tests/test_coupon.py::TC-001", "case": "TC-001", "verdict": "FLAKY", "evidence": "evidence/reruns.json",
            "mechanism": "timing", "reruns": 5, "fix_rounds": 1, "fix_result": "fixed"}]}), encoding="utf-8")
        doc = D.assess(art)
        row = next(r for r in doc["rows"] if r["kind"] == "test")
        check_eq("flaky-fixed: the ledger row itself reads green", row["state"], "passed_green")
        summary = C.load_json(art / "work" / "delivery-summary.json")
        check_eq("flaky-fixed: the debt is still listed (from the manifest's verdict, not the state)",
                 [r["test"] for r in summary["unverified_by_critic"]], ["tests/test_coupon.py::TC-001"])
    finally:
        cleanup(art_root)


def coverage_of_an_unverified_test() -> None:
    """D-0013 in the coverage projection: an obligation whose only test the critic could not verify is
    not "current sufficient evidence incomplete" - it is the person's debt, said in words, and it is
    never a delivery reason. Everything else keeps its own gap."""
    from harness import temp_dir
    import coverage_contract as CC
    from event_store import content_hash
    root = temp_dir("qa-coverage-debt-")
    try:
        (root / "work").mkdir()
        ob = {"obligation_id": "O-1", "behavior": "b", "observation_boundary": "api", "completion_condition": "done",
              "requirement_refs": [{"ref": "R-1", "revision": "r"}], "applicable_scenarios": ["positive"],
              "oracle_status": "resolved", "oracle_source_ref": "spec", "decision": "reuse",
              "execution_scope": "current_task", "planned_check_refs": ["x"],
              "sufficiency_review": {"author_dispatch_id": "d", "input_hash": "h", "rationale": "r"},
              "coverage_links": [{"candidate_id": "c", "assessment": "sufficient", "assessment_reason": "r",
                                  "assertion_refs": ["a"], "proves": ["b"], "does_not_prove": []}]}
        (root / "work" / "test-plan.json").write_text(json.dumps(
            {"rows": [{"id": "TS-1", "schema_version": 2, "coverage_obligations": [ob]}]}), encoding="utf-8")
        binding = {"obligation_id": "O-1", "obligation_hash": content_hash(ob), "instance_ids": ["i"],
                   "design_assessment": "sufficient", "code_validity": "valid", "sensitivity": "missing",
                   "assertion_refs": ["a"], "quality_not_applicable_reason": "x"}

        def projected(verdict, status="passed", **over):
            tests = [{"instance_id": "i", "file": "tests/a.py", "critic_verdict": verdict}] if verdict is not None else []
            plan = dict(binding, **over)
            return CC.coverage_projection(root, {"current_results": [{"instance_id": "i", "status": status}]},
                                          {"tests": tests, "obligation_bindings": [plan]})["obligations"][0]

        debt = projected(" unverified ")
        check_eq("unverified + green + nothing else missing: the person's debt", (debt["verified"], debt["person_debt"]),
                 (False, True))
        check_in("said in words", "the code critic could not verify the test that covers it", debt["gap"])
        check_eq("and never a delivery reason", D.coverage_reasons({"coverage": {"obligations": [debt]}}), [])
        approved = projected("approved")
        check_eq("an approved test with the same gap is not a debt", approved["person_debt"], False)
        check_eq("and keeps its own gap", approved["gap"], "current sufficient evidence incomplete")
        check_eq("which is a delivery reason", len(D.coverage_reasons({"coverage": {"obligations": [approved]}})), 1)
        check_eq("no test row for the instance: not a debt", projected(None)["person_debt"], False)
        failed = projected("unverified", status="failed")
        check_eq("an unverified test with a red run is not a debt: the failure keeps its gap",
                 (failed["person_debt"], failed["execution_state"]), (False, "failed"))
        check_eq("and still blocks", len(D.coverage_reasons({"coverage": {"obligations": [failed]}})), 1)
        check_eq("a design that is not sufficient is not the debt either",
                 projected("unverified", design_assessment="partial")["person_debt"], False)
    finally:
        cleanup(root)


def a_then_handed_beside_an_unprobed_test_keeps_every_then() -> None:
    """HF1 batch fix round, B3 (critic t-070): a case with a Then the person took AND a test the code critic could not verify
    (the probe gap, `review_unverified`) is ONE item of two kinds. Its other Thens rest on a test whose sensitivity was never
    proved, so "Left with you" lists EVERY Then and the part rides on the Then the person took; the item that is ONLY the
    handed Then keeps the narrowed list, and the item that is ONLY the unverified test keeps the full list as before."""
    from harness import FIXTURES, temp_dir
    top = temp_dir("qa-left-compose-")
    try:
        def story(handed: bool, unverified: bool) -> Path:
            task = top / f"s{int(handed)}{int(unverified)}" / "QA-1"
            shutil.copytree(FIXTURES / "after-checks", task)
            case = task / "work" / "test-cases" / "checkout" / "TC-001.md"
            case.write_text(case.read_text(encoding="utf-8").rstrip() + "\n\n## Then\n"
                            "1. A 422 with code `DISCOUNT_TOO_LARGE` is returned.\n"
                            "2. The total is unchanged, read back from the order record.\n", encoding="utf-8")
            mpath = task / "work" / "automation-manifest.json"
            manifest = json.loads(mpath.read_text(encoding="utf-8"))
            manifest["then_bindings"] = [{"case": "TC-001", "then": 1, "instance_id": C.test_instance_id(manifest["tests"][0]),
                                          "assertion_ref": "tests/test_coupon.py:9", "status": "covered"}]
            if handed:
                manifest["then_bindings"].append(
                    {"case": "TC-001", "then": 2, "instance_id": None, "assertion_ref": None, "status": "unresolved",
                     "reason": "handed_to_person", "detail": "open the order record and read the total", "owner": "person",
                     "part": "the total read back"})
            if unverified:
                manifest["tests"][0]["critic_verdict"] = "unverified"
                manifest["tests"][0]["sensitivity_proof_missing_reason"] = "the stand was down while probing"
            mpath.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
            return task

        def item_of(task: Path) -> dict:
            doc = D.assess(task)
            found = [i for i in doc["left_items"] if i["counts"] and i["ref"] == "TC-001"]
            check_eq("compose: ONE counting item for TC-001", len(found), 1)
            return {"doc": doc, **(found[0] if found else {"kinds": [], "to_check": ""})}

        both = item_of(story(True, True))
        check_eq("compose: the item carries both kinds", sorted(both["kinds"]), ["handed", "review_unverified"])
        check_eq("compose: the verdict is the third one", both["doc"]["delivery_verdict"], "after_checks")
        check_in("compose: every Then is listed: Then 1 (the one a green test could not prove here)", "DISCOUNT_TOO_LARGE", both["to_check"])
        check_in("compose: ... and Then 2", "The total is unchanged", both["to_check"])
        check_in("compose: ... with the part on the Then the person took", "The total is unchanged, read back from the order record."
                 " - the part: the total read back", both["to_check"])
        check_not_in("compose: the part rides on that Then only", "DISCOUNT_TOO_LARGE is returned. - the part", both["to_check"].replace("`", ""))

        only_handed = item_of(story(True, False))
        check_eq("compose control: a handed Then alone is one kind", only_handed["kinds"], ["handed"])
        check_in("compose control: the handed-only item keeps the narrowed list: the Then and its part",
                 "The total is unchanged", only_handed["to_check"])
        check_not_in("compose control: ... and not the Thens a green test proved", "DISCOUNT_TOO_LARGE", only_handed["to_check"])

        only_unverified = item_of(story(False, True))
        check_eq("compose control: an unverified test alone is one kind", only_unverified["kinds"], ["review_unverified"])
        check_in("compose control: ... and lists every Then, with no part", "DISCOUNT_TOO_LARGE", only_unverified["to_check"])
        check_not_in("compose control: ... no part is invented", "the part", only_unverified["to_check"])
    finally:
        cleanup(top)


# === TQ1-20 (S6.03), the verdict's side: the records of branch accounting in `assess`. The fixture is `test_branch_accounting.delivery_story`. ===

def _items(doc) -> dict:
    return {i["ref"]: i for i in doc["left_items"] if i.get("kinds")}


def v_1_to_4_verdict_by_branch() -> None:
    from test_branch_accounting import delivery_story
    root = temp_project("qa-cd-v1-")
    try:
        task = delivery_story(root, bn2="absent")
        doc = D.assess(task)
        item = _items(doc).get("BN-2") or {}
        check_eq("V-1 everything green and one branch with no home: `after_checks`, not delivered as ready", (doc["delivery_verdict"], doc["delivery_ready"]), ("after_checks", False))
        check_eq("V-1 (m14) ... the item BN-2 with its requirement, what to check and `counts`", (item.get("kinds"), item.get("requirements"), item.get("to_check"), item.get("counts")),
                 (["branch_lost"], ["R-2"], "the occupied project", True))
        task = delivery_story(root)
        doc = D.assess(task)
        check_eq("V-2 pair: the branches have homes and are `covered`: `yes`, no item of theirs", (doc["delivery_verdict"], doc["delivery_ready"], sorted(_items(doc))), ("yes", True, []))
        # V-3: a red beside a branch with no home: `no`, and the branch is still an item (FR-21: the debt is not hidden behind the red)
        task = delivery_story(root, bn2="absent")
        report = task / "work" / "run-report.json"
        report.write_text(json.dumps({**json.loads(report.read_text(encoding="utf-8")), "execution_status": "broken_run"}), encoding="utf-8")
        doc = D.assess(task)
        check_eq("V-3 a red row beside a branch with no home: `no`, and BN-2 is still listed", (doc["delivery_verdict"], "BN-2" in _items(doc)), ("no", True))
        # V-4: every kind of the table (spec 3.3) on its own fixture; `branch_excluded` and `branch_lost` stay two items (FR-35)
        homes = {"branch_homes": [{"branch": "BN-2", "home": "excluded", "reason": "the role left it out", "decided_by": "role"}]}
        for name, kw, expect in (("lost", dict(bn2="absent"), {"BN-2": "branch_lost"}), ("unproven", dict(bn2="unbound"), {"BN-2": "branch_unproven"}),
                                 ("excluded by the role", dict(bn2="absent", plan_extra=homes), {"BN-2": "branch_excluded"}),
                                 ("source_unreconciled", dict(obligations="| unit | home |\n|---|---|"), {"ticket-text": "source_unreconciled"})):
            task = delivery_story(root, **kw)
            doc = D.assess(task)
            check_eq(f"V-4 {name}: the item and its kind", {r: i["kinds"][0] for r, i in _items(doc).items()}, expect)
            check_eq(f"V-4 {name}: `after_checks`", doc["delivery_verdict"], "after_checks")
        task = delivery_story(root, bn1="absent", bn2="absent", plan_extra=homes)
        check_eq("V-4 `branch_lost` and `branch_excluded` side by side are two items, never one", {r: i["kinds"] for r, i in _items(D.assess(task)).items()},
                 {"BN-1": ["branch_lost"], "BN-2": ["branch_excluded"]})
        task = delivery_story(root)
        register = task / "work" / "requirements-register.md"
        text = register.read_text(encoding="utf-8")
        register.write_text(text[:text.index("## Branches")] + text[text.index("## Contradiction matrix"):], encoding="utf-8")
        check_eq("V-4 a dated register with no `## Branches`: `branches_not_recorded`", {r: i["kinds"] for r, i in _items(D.assess(task)).items()}, {"branches": ["branches_not_recorded"]})
        task = delivery_story(root)
        import branch_accounting as BA
        real = BA.delivery_records
        BA.delivery_records = lambda art: (_ for _ in ()).throw(BA.Unreadable("test-plan.json cannot be read"))      # the reader fails: the plan is broken
        try:
            doc = D.assess(task)
        finally:
            BA.delivery_records = real
        check_eq("V-8 pair: the reader cannot read what it must: `no`, the text starts `factory: `, never `yes`",
                 (doc["delivery_verdict"], any(r.startswith("factory: branch accounting") for r in doc["reasons"])), ("no", True))
        # V-5 at the verdict: the person's word is a proven answer, nothing less
        ask = [{"id": "Q1", "question": "Is BN-2 in scope?", "source_says": ""}, {"id": "Q2", "question": "Is the colour right?", "source_says": ""}]
        from test_branch_accounting import v_ask
        for name, decided, answer, answers, expect in (("a confirmed answer naming BN-2", "person", "Q1", (("Q1", "answered", 0),), ("yes", "branch_excluded_by_word")),
                                                       ("the same answer, decided by the role", "role", "Q1", (("Q1", "answered", 0),), ("after_checks", "branch_excluded")),
                                                       ("an answer to another question", "person", "Q2", (("Q2", "answered", 1),), ("after_checks", "branch_excluded")),
                                                       ("no answer recorded", "person", "Q1", (), ("after_checks", "branch_excluded"))):
            plan = {"branch_homes": [{"branch": "BN-2", "home": "excluded", "reason": "narrowed", "decided_by": decided, "answer": answer}]}
            task = delivery_story(root, bn2="absent", plan_extra=plan)
            v_ask(task, ask, answers)
            doc = D.assess(task)
            check_eq(f"V-5 (m15) {name}", (doc["delivery_verdict"], DV_kind(doc, "BN-2")), expect)
        # V-6: two branches of ONE requirement are two items
        task = delivery_story(root, bn1="absent", bn2="absent")
        register = task / "work" / "requirements-register.md"
        register.write_text(register.read_text(encoding="utf-8").replace("| BN-2 | R-2 |", "| BN-2 | R-1 |"), encoding="utf-8")
        items = _items(D.assess(task))
        check_eq("V-6 (m16) two branches of R-1: two items, each with its own words", {r: (i["requirements"], i["to_check"]) for r, i in items.items()},
                 {"BN-1": (["R-1"], "a coupon above the cap"), "BN-2": (["R-1"], "the occupied project")})
        facts = D.gather(task)
        plain = [{"text": "", "kind": "handed", "case": "", "ref": "R-4", "requirements": ["R-4"], "source": "handed", "to_check": ""},
                 {"text": "", "kind": "handed", "case": "", "ref": "R-4", "requirements": ["R-4"], "source": "handed", "to_check": ""}]
        built = D.build_left_items(plain, facts)
        check_eq("V-6 a record with no `item_key` keeps the key it always had: one item by its first requirement, no `lines`", ([i["ref"] for i in built], "lines" in built[0]), (["R-4"], False))
    finally:
        cleanup(root)


def DV_kind(doc, ref):
    item = _items(doc).get(ref)
    return item["kinds"][0] if item else next((r["kind"] for r in doc.get("records", []) if r.get("ref") == ref), "branch_excluded_by_word")


def v_10_and_16_word_and_case_item() -> None:
    import delivery_verdict as DV
    from test_branch_accounting import delivery_story, v_hand_then
    root = temp_project("qa-cd-v10-")
    try:
        doc = DV.load_kinds()[0]
        handed = DV.verdict_of_kind("handed", doc)
        check_eq("V-10 every new debt kind carries the verdict of `handed` (the person's third word opens what `yes` opens, P21)",
                 {k: DV.verdict_of_kind(k, doc) for k in ("branch_lost", "branch_excluded", "branch_unproven", "branches_not_recorded", "source_unreconciled", "attachment_question_open")},
                 {k: handed for k in ("branch_lost", "branch_excluded", "branch_unproven", "branches_not_recorded", "source_unreconciled", "attachment_question_open")})
        check_eq("V-10 ... `branch_excluded_by_word` holds nothing, `branches_unreadable` is `no`", (DV.verdict_of_kind("branch_excluded_by_word", doc), DV.verdict_of_kind("branches_unreadable", doc)), ("none", "no"))
        task = delivery_story(root, bn2="absent")
        verdict = D.assess(task)
        check_eq("V-10 `word_of` reads the ledger of such a story as the third word, as it reads a `handed` one",
                 DV.word_of({"delivery_ready": verdict["delivery_ready"], "delivery_verdict": verdict["delivery_verdict"]}), "after_checks")
        # V-16: the branch is an item beside the case's own item: no suppression by the case's kind (spec C1)
        task = delivery_story(root, bn1="covered", bn2="unbound")
        v_hand_then(task, 1)
        doc = D.assess(task)
        items = _items(doc)
        check_eq("V-16 (m24) Then 1 handed and Then 2 with no kind: the case's item AND the branch's item", ("TC-001" in items, items.get("BN-2", {}).get("kinds")), (True, ["branch_unproven"]))
    finally:
        cleanup(root)


def f5_unprepared_walk_is_a_left_item() -> None:
    """F5(e) 3 (t-1936 N5, AR-27): the ledger's `unprepared_walks` reach "Left with you" as kind `unprepared_walk` (`after_checks`,
    owner factory), one item per case, with the reason as what is left to check. KILLS: the producer unwired from `assess`, the kind
    row removed (an unknown kind decides `no`), the item's `to_check` overwritten by the case's Thens."""
    import delivery_verdict as DV
    doc_kinds, problem = DV.load_kinds()
    check_eq("test_kind_row_shape_accepted: the kinds file loads with the new row (`_shape_problem` accepts the pair)",
             (problem, doc_kinds["kinds"].get("unprepared_walk")), ("", {"verdict": "after_checks", "owner": "factory"}))
    ledger = {"unprepared_walks": [{"case": "TC-007", "obligation_ids": ["OB-7"], "reason": "the plan gives TC-007's check an evidence rule that is not one word",
                                    "observations": [], "finding": ""}, {"reason": "no case"}, "junk"]}
    records = D.unprepared_records(ledger)
    check_eq("test_unprepared_walk_is_left_item_after_checks: one record per walk with a case; junk and a caseless row are dropped",
             [(r["kind"], r["case"], r["source"]) for r in records], [("unprepared_walk", "TC-007", "ledger")])
    check_eq("... a ledger without the key has none", (D.unprepared_records({}), D.unprepared_records(None)), ([], []))
    check_eq("... the verdict of the kind is the third word", DV.decide([r["kind"] for r in records])[0], "after_checks")
    facts = {"index": {}, "manifest": {}, "report": {}, "cfg": {}, "decisions": {}, "triage": {}}
    items = D.build_left_items(records, facts, doc_kinds)
    check_eq("test_unprepared_walk_is_left_item_after_checks: ONE counting item under its own kind",
             [(i["ref"], i["kinds"], i["counts"]) for i in items], [("TC-007", ["unprepared_walk"], True)])
    check_in("... naming the factory's failure and the reason", "evidence rule that is not one word", items[0]["to_check"])
    check_eq("negative control: an unknown kind is never a pass", DV.decide(["unprepared_walks"])[0], "no")


def _held_story(**hold) -> Path:
    """The after-checks fixture story (a copy) held for code: `pipeline.awaiting` = `hold`."""
    from test_third_verdict import edit, story
    task = story()
    edit(task, "pipeline.json", lambda p: p.update(awaiting=hold))
    return task


def awaiting_story_reads_one_awaiting_implementation_record() -> None:
    """t-2181 C10 / PC-5: a story held for code gives ONE record `awaiting_implementation` (`no`, owner product) and runs no other check
    (no bug candidate, no gate B reason). The ONE exception (AR-27, the Lead's fork): a red a recorded S7 verdict stands behind keeps its
    own record beside the hold - it was written before the story parked, and the verdict is `no` either way.
    KILLS: the hold read after the other checks; a second awaiting record per case; the recorded bug dropped from the report."""
    from test_third_verdict import red, story
    held = _held_story(since="2026-11-08T12:00:00")
    quiet = D.assess(held)
    check_eq("awaiting: with no red, ONE reason, ONE record of kind awaiting_implementation, owner product",
             ([r["kind"] for r in quiet["reason_records"]], [r["owner"] for r in quiet["reason_records"]], len(quiet["reasons"])),
             (["awaiting_implementation"], ["product"], 1))
    check_eq("awaiting: the words of the default cause", quiet["reasons"], ["grounding: waiting for a fix"])
    check_eq("awaiting: the verdict is `no`, not ready", (quiet["delivery_verdict"], quiet["delivery_ready"]), ("no", False))
    check_eq("awaiting: no item of the other records is left (only the regression row, which decides nothing)",
             [i for i in quiet["left_items"] if i.get("kinds")], [])
    red(held)       # a red result and its recorded APP_BUG triage sit in the story, written before it parked
    doc = D.assess(held)
    kinds = [r["kind"] for r in doc["reason_records"]]
    check_eq("awaiting + a recorded bug: still ONE awaiting_implementation record, first, and nothing but red beside it",
             (kinds[0], kinds.count("awaiting_implementation"), set(kinds)), ("awaiting_implementation", 1, {"awaiting_implementation", "red"}))
    check("awaiting + a recorded bug: the APP_BUG red reaches the report under its own record",
          any("APP_BUG" in r for r in doc["reasons"]), str(doc["reasons"]))
    check_eq("awaiting + a recorded bug: the verdict is `no` (it cannot get weaker)", (doc["delivery_verdict"], doc["delivery_ready"]), ("no", False))
    check_eq("awaiting + a recorded bug: no bug candidate or other item is added",
             [i for i in doc["left_items"] if i.get("kinds")], [])
    control = D.assess(story())
    check_eq("control: the same story not held is not `awaiting`", [r["kind"] for r in control["reason_records"]], [])


def stopped_story_reads_awaiting_implementation() -> None:
    """B4: a stopped hold is the same kind, and the line carries the person's words (carried whole, never read)."""
    task = _held_story(since="2026-11-08T12:00:00", stopped={"at": "2026-11-09T10:00:00", "words": "the team dropped the feature"})
    doc = D.assess(task)
    check_eq("stopped: still ONE awaiting_implementation record", [r["kind"] for r in doc["reason_records"]], ["awaiting_implementation"])
    check_eq("stopped: the line says so and carries the person's words",
             doc["reasons"], ['grounding: waiting for a fix; the person stopped waiting: "the team dropped the feature"'])
    check_eq("stopped: still `no`", doc["delivery_verdict"], "no")
    bare = D.assess(_held_story(since="2026-11-08T12:00:00", stopped={"at": "2026-11-09T10:00:00"}))
    check_eq("stopped with no words: the suffix only, no empty quote", bare["reasons"], ["grounding: waiting for a fix; the person stopped waiting"])


def first_look_stop_reads_awaiting_implementation() -> None:
    """t-2277 PC-5: the words by `cause` - a story stopped after the first look says the feature does not work yet; a cause the table
    does not hold reads as the default cause (an unknown cause never hides the hold)."""
    doc = D.assess(_held_story(cause="first_look_stop", held_from="S3", since="2026-11-08T12:00:00"))
    check_eq("first_look_stop: kind and words", ([r["kind"] for r in doc["reason_records"]], doc["reasons"]),
             (["awaiting_implementation"], ["grounding: stopped after the first look: the feature does not work yet"]))
    check_eq("first_look_stop: the record is typed with its cause", D.awaiting_record(C.awaiting({"awaiting": {"cause": "first_look_stop"}}))["cause"],
             "first_look_stop")
    odd = D.assess(_held_story(cause="something_new"))
    check_eq("an unknown cause reads as the default cause", odd["reasons"], ["grounding: waiting for a fix"])
    check_eq("the sentence has an owner family (FR-19: no classifier finding)",
             [f for f in doc["factory_findings"] if f["code"] == "REASON_OWNER_UNCLASSIFIED"], [])


def a_diff_story_pending_implementation_is_not_the_awaiting_kind() -> None:
    """E-V1: the grounding `pending_implementation` (a requirement the change does not implement) keeps its own kind and `no`;
    the hold's kind is another, also `no`, and neither is ever listed in Left with you."""
    import delivery_verdict as DV
    check_eq("the two kinds are two", (DV.verdict_of_kind("pending_implementation"), DV.verdict_of_kind("awaiting_implementation")), ("no", "no"))
    check_eq("pending_implementation record keeps its kind", D.pending_implementation_record("R-2")["kind"], "pending_implementation")
    check_eq("neither counts toward the third word", (DV.counts("pending_implementation"), DV.counts("awaiting_implementation")), (False, False))
    # a requirement of a DIFF story that the grounding table calls `not_implemented` is still a `pending_implementation` record (`no`),
    # read while the story is NOT held for code (moved here from test_report_facts: the same check_delivery/delivery_verdict surface)
    from test_third_verdict import story
    task = story()
    table = ("schema_version: 1", "implementation_source: diff", "requirements:", "  - r: R-2", "    state: not_implemented", "    question: Is it built?")
    (task / "work" / "grounding.yaml").write_bytes(("\n".join(table) + "\n").encode("utf-8"))
    recs = D.grounding_records(task, {"rows": []}, {})
    check_eq("a diff story's `not_implemented` requirement keeps its own kind", [r["kind"] for r in recs], ["pending_implementation"])
    check_eq("... decides `no`, and the story is not held for code", (DV.decide([r["kind"] for r in recs])[0], C.awaiting(C.load_json(task / "pipeline.json"))["state"]),
             ("no", "none"))


if __name__ == "__main__":
    f5_unprepared_walk_is_a_left_item()
    main()
