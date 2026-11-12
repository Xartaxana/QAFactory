"""ledger.py — every plan row and every test in exactly one state, and the count adds up."""
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from harness import (  # noqa: E402
    BAD, GOOD, SCRIPTS, check, check_eq, check_in, check_not_in, cleanup, finish, install_artifacts,
    run_script, temp_project, use_project,
)

sys.path.insert(0, str(SCRIPTS))
import contract as C  # noqa: E402
import ledger as L  # noqa: E402
import proof_level as PL  # noqa: E402

import test_probe_binding as PB  # noqa: E402  (HF2-11c: a real project and real `--mine` jobs, the shas of a run row are the producer's)

TEST_REL = "tests/test_coupon.py"
TEST_SRC = "def test_cap_rejected():\n    assert 1 + 1 == 2\n"


def receipt_body(iid: str, sha: str, **over) -> dict:
    """A live receipt `contract.sensitivity_proof_issues` accepts (the shape probe_by_code writes)."""
    body = {"instance_id": iid, "case_version": "cv_x", "test_content_hash": sha,
            "source_revision": "src", "build_id": "build", "mutation": "invert",
            "expected_assertion_failure": "denied", "actual_failure": "denied",
            "assertion_location": "t.py:2", "restoration_evidence": "restored",
            "failure_kind": "assertion", "immutable": True, "receipt_hash": "h-" + iid,
            "proof_level": PL.LIVE, "probe_tool": "probe_by_code.py", "mutation_kind": "assertion"}
    body.update(over)
    return body


def put_receipt(task: Path, name: str, body: dict) -> dict:
    path = task / "work" / "sensitivity-receipts" / f"{name}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(body, indent=1), encoding="utf-8")
    import hashlib
    return {"path": path.relative_to(task).as_posix(),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def digest(path: Path) -> str:
    import hashlib
    return hashlib.sha256(path.read_bytes()).hexdigest()


def state_of(doc: dict, ref: str) -> str:
    return next((r["state"] for r in doc["rows"] if r["ref"] == ref), "<absent>")


def instance_ref(artifacts: Path, case: str) -> str:
    manifest = C.load_json(artifacts / "work" / "automation-manifest.json")
    entry = next(item for item in C.manifest_tests(manifest) if item.get("case") == case)
    return str(entry.get("instance_id") or C.test_instance_id(entry))


def a_green_on_a_refused_base_is_not_verified() -> None:
    """TQ1-18 (D3-K11..K13, K17, K18, D3-1, D3-2, D3-8): the code critic's `base_outcome: {refused, run}` turns a GREEN of THIS run into
    `not_verified:oracle_on_refused_base`; a red keeps its state, every other result keeps its own byte for byte, `working` / a word
    the writer refuses / no run / another run read as no record, and a test run again after its repair leaves the state by itself.
    Kills M-D3-5 (no condition on the result: the `error`/`partial`/`skipped`/no-result rows), M-D3-5a (the branch before the red:
    the `failed:untriaged` row), M-D3-8 (the run not compared: the repaired-test row)."""
    import manifest_put as MP
    check("the word the ledger reads is one of the writer's two", L.BASE_REFUSED in MP.BASE_OUTCOMES, str(MP.BASE_OUTCOMES))
    check_eq("the state is the one spelling the readers share", L.NOT_VERIFIED_REFUSED_BASE, "not_verified:oracle_on_refused_base")
    case = "TC-18"
    base = {"case": case, "instance_id": "test_move", "file": "tests/t.py", "covers": [case], "critic_verdict": "approved"}

    def state(status, entry_extra=None, run="A1", review=None):
        entry = dict(base, **(entry_extra or {}), **({"critic_verdict": review} if review else {}))
        rows = [{"instance_id": "test_move", "case": case, "status": status, "attempt_id": run}] if status else []
        return L.test_state(entry, {"current_results": rows}, {"triage": []}, None, {"tests": [entry]})

    refused = {"base_outcome": {"outcome": "refused", "run": "A1"}}
    check_eq("K13: no record: green, as it was", state("passed")[0], "passed_green")
    got, detail = state("passed", refused)
    check_eq("K11: a green of this run on a refused base is not verified", got, L.NOT_VERIFIED_REFUSED_BASE)
    check_in("... and the detail says why", "a refusal in this run", detail)
    check_eq("K12 (M-D3-5a): the red of the same row keeps its own state", state("failed", refused)[0], "failed:untriaged")
    for status in ("error", "partial", "skipped", None):
        check_eq(f"K12a (M-D3-5): `{status}` with the record is the state it has without it, byte for byte",
                 state(status, refused), state(status))
    check_eq("D3-1: an unverified review keeps its own state", state("passed", refused, review="unverified")[0], "review_unverified")
    check_eq("K17 (M-D3-8): the test repaired and run AGAIN (another attempt) is green with no command",
             state("passed", refused, run="A2")[0], "passed_green")
    check_eq("K18: `working` reads as no record", state("passed", {"base_outcome": {"outcome": "working", "run": "A1"}})[0], "passed_green")
    for name, block in (("a word the writer refuses", {"outcome": "refusde", "run": "A1"}), ("no run", {"outcome": "refused"}),
                        ("not an object", "refused")):
        check_eq(f"D3-2: {name} reads as no record (FR-41)", state("passed", {"base_outcome": block})[0], "passed_green")
    gone = dict(base, base_outcome={"outcome": "refused", "run": "A1"})
    check_eq("D3-8: a row of a run with no attempt id never matches a record",
             L.test_state(gone, {"current_results": [{"instance_id": "test_move", "case": case, "status": "passed"}]},
                          {"triage": []}, None, {"tests": [gone]})[0], "passed_green")


def coverage_gaps_are_not_reassured_over() -> None:
    """RD1-21: `render_reasons` prints "nothing here says the product is not ready" over bookkeeping only; a factory-owned
    `coverage:` record is a behaviour no test proves, so the line says that instead (one predicate, `factory_coverage_gaps`)."""
    cov = {"code": L.COVERAGE_GAP_CODE, "owner": "factory", "detail": "coverage: OB-1 — x"}
    book = {"code": "FACTORY_DEFECT", "owner": "factory", "detail": "factory: y"}
    prod_cov = {"code": L.COVERAGE_GAP_CODE, "owner": "product", "detail": "coverage red: OB-2 — x"}
    check_eq("the count: the factory's coverage records only, a non-object skipped",
             L.factory_coverage_gaps({"reason_records": [cov, "x", book, prod_cov]}), 1)
    text = "\n".join(L.render_reasons({"reason_records": [cov, book]}))
    check_in("the factory heading opens with the unproven line", "- " + L.factory_coverage_line(1), text)
    check_eq("and the reassurance is withdrawn", "Nothing here says the product is not ready" in text, False)
    check_in("the control: bookkeeping alone is reassured", "Nothing here says the product is not ready",
             "\n".join(L.render_reasons({"reason_records": [book]})))
    check_in("a `coverage red:` record (the product's) keeps the product heading", "What blocks delivery on the product side",
             "\n".join(L.render_reasons({"reason_records": [prod_cov, cov]})))


def main() -> None:
    coverage_gaps_are_not_reassured_over()
    a_green_on_a_refused_base_is_not_verified()
    # --- the good set -------------------------------------------------------------------------
    doc = L.build(GOOD)
    plan_rows = C.parse_plan(GOOD / "test-plan.md")
    manifest = C.load_json(GOOD / "work" / "automation-manifest.json")
    expected = len(plan_rows) + len(C.manifest_tests(manifest))
    check_eq("good: one row per plan row plus one per test", len(doc["rows"]), expected)
    check_eq("good: TS-1 passed green", state_of(doc, "TS-1"), "passed_green")
    check_eq("good: TS-2 (manual-agent, executed) passed green", state_of(doc, "TS-2"), "passed_green")
    check_in("good: TS-3 is a skip with its reason", "skipped:", state_of(doc, "TS-3"))
    check_eq("good: the test instance row is green", state_of(doc, instance_ref(GOOD, "TC-001")), "passed_green")
    check_eq("good: no review was skipped", doc["review_skipped"], False)
    check_eq("good: no open subtask", doc["subtasks_open"], [])
    for row in doc["rows"]:
        check(f"good: `{row['state']}` is in the ledger vocabulary", C.is_ledger_state(row["state"]),
              row["state"])

    # --- the bad set ---------------------------------------------------------------------------
    bad = L.build(BAD)
    check_eq("bad: TS-1 passed green", state_of(bad, "TS-1"), "passed_green")
    check_in("bad: TS-2 failed with the triage verdict", "failed:FLAKY", state_of(bad, "TS-2"))
    check_eq("bad: TS-3 is impossible (unresolved without a decision)",
             state_of(bad, "TS-3"), "impossible")
    check_eq("bad: the unfixed flake instance is not verified", state_of(bad, instance_ref(BAD, "TC-002")), "not_verified_flaky")
    check_eq("bad: a test with no critic verdict flips review_skipped", bad["review_skipped"], True)
    check_eq("bad: the open subtask is listed", [s["key"] for s in bad["subtasks_open"]], ["QA-1-2"])
    check_eq("bad: and it gets its own ledger row",
             state_of(bad, "QA-1-2"), "subtask_in_progress")
    for row in bad["rows"]:
        check(f"bad: `{row['state']}` is in the ledger vocabulary", C.is_ledger_state(row["state"]),
              row["state"])

    # --- the generated files --------------------------------------------------------------------
    root = temp_project("qa-factory-ledger-")
    try:
        art = root / "qa-factory" / "artifacts" / "QA-1"
        shutil.copytree(GOOD, art)
        (art / "work" / "ledger.json").unlink(missing_ok=True)
        (art / "work" / "ledger.md").unlink(missing_ok=True)
        p = run_script("ledger.py", art)
        check_eq("ledger.py exits 0", p.returncode, 0)
        check("ledger.json is written", (art / "work" / "ledger.json").exists(), p.stdout + p.stderr)
        check("ledger.md is written", (art / "work" / "ledger.md").exists(), p.stdout + p.stderr)
        written = json.loads((art / "work" / "ledger.json").read_text(encoding="utf-8"))
        check_eq("the written ledger has the same rows", len(written["rows"]), expected)
        check_eq("delivery_ready defaults to false — check_delivery decides it",
                 written["delivery_ready"], False)
        table = [ln for ln in (art / "work" / "ledger.md").read_text(encoding="utf-8").splitlines()
                 if ln.startswith("|")]
        check_eq("the markdown table has a header, a separator and one line per row",
                 len(table), expected + 2)
        check_in("the markdown states delivery readiness", "delivery_ready:",
                 (art / "work" / "ledger.md").read_text(encoding="utf-8"))

        # An env-blocked run puts its rows on the environment's owner, not on "passed".
        report = C.load_json(art / "work" / "run-report.json")
        report["execution_status"] = "env_blocked"
        report["env_preflight"] = "blocked"
        report["results"] = []
        report["manual_checks"] = []
        report["env_blocked"] = [{"area": "checkout", "owner": "user"}]
        (art / "work" / "run-report.json").write_text(json.dumps(report), encoding="utf-8")
        blocked = L.build(art)
        check_eq("an env-blocked run names the owner on the plan row",
                 state_of(blocked, "TS-1"), "env_blocked:user")
        check_eq("and on the test instance row", state_of(blocked, instance_ref(art, "TC-001")), "env_blocked:user")
    finally:
        cleanup(root)

    # --- what the person is shown: short cells, one footnote per decision ----------------------
    # TP1-15045: the same ~900-character decision paragraph stood in eleven rows of this
    # table, and six rows were delinked duplicates of tests nobody had written.
    decision = ("api: run/verify the P-guardrail partition where the AWS keys are - the "
                "integration data is absent on localhost and needs Parameter Store credentials")
    doc = {"ticket": "T-1", "rows": [
        {"ref": "TS-1", "kind": "plan_row", "state": "not_executed:handed_to_person",
         "detail": f"TC-012: {decision}"},
        {"ref": "test_a", "kind": "test", "state": "not_executed:handed_to_person",
         "detail": f"TC-012: {decision}"},
        {"ref": "ti_dead", "kind": "test", "state": "review_rejected",
         "detail": "tests/ui/test_diff.py::TC-002", "dead": True},
        {"ref": "TS-2", "kind": "plan_row", "state": "env_blocked:factory",
         "detail": "STALE, kept as a labeled marker only - the partition is green"},
    ]}
    markdown = L.render(doc)
    body = [ln for ln in markdown.splitlines() if ln.startswith("|")]
    check_eq("a dead duplicate and a STALE row never reach the table", len(body), 2 + 2)
    check_in("the cell says which case it is about", "| TC-012 [1] |", markdown)
    check_eq("and the paragraph is printed once", markdown.count(decision), 1)
    check_in("under the table, numbered", f"[1] {decision}", markdown)
    check_eq("splitting a short detail leaves it whole", L.split_detail("TC-001"), ("TC-001", ""))
    check_eq("a row the factory left behind is not the person's to read",
             [r["ref"] for r in L.table_rows(doc)], ["TS-1", "test_a"])

    each_verdict_keeps_its_own_word()
    rejected_is_one_reading()
    no_row_is_not_a_neighbours_green()
    the_level_a_test_reached_is_a_field_of_its_row()
    the_level_words_reach_the_markdown()
    the_words_follow_the_reason()
    the_summary_line_counts_by_reason()
    an_unconfirmed_then_is_never_green()
    a_deferred_then_beside_a_green_is_deferred()
    the_manual_evidence_line_speaks_the_phase_words()
    the_dashboard_prints_the_same_phase_words()
    the_third_verdict_in_the_ledger()
    the_repair_limit_carrier()
    the_carrier_is_written_once_and_read_whole()
    the_untyped_reason_is_recorded_and_worded()
    test_ledger_lists_unprepared_walks()
    triage_refs_names_what_the_ledger_matches()
    one_test_covers_three_cases()
    rollup_status_is_the_per_instance_projection()
    an_unknown_run_word_is_not_executed()
    a_green_of_other_code_is_not_a_pass()
    two_areas_are_two_cases_in_the_ledger()

    finish("test_ledger")


# --- C1-5c: work/review-debts.json (section 3.2) -----------------------------------------------------------------

FORM = ("schema_version: 1\ncontract: s5-critic-to-automator\nstage: S5\nfindings:\n"
        "  - id: F-1\n    file: tests/test_coupon.py\n    line: 12\n    problem: it never reads the cancelled flag\n"
        "    expected: \"the flag reads cancelled\"\n    fix: assert the flag\n    cause: test_defect\n    blocking: true\n"
        "  - id: F-2\n    file: tests/other.py\n    line: 3\n    problem: a finding about another file\n"
        "    expected: x\n    fix: y\n    cause: test_defect\n    blocking: true\n")


def window(**over) -> dict:
    base = {"stage": "S5", "cases": ["TC-001"], "tests": [], "critic_dispatch": "d-1", "form": "work/handoffs/d-1.yaml",
            "reason": "cap", "rounds": {"counted": 2, "cap": 2, "by_cause": {"test_defect": 2}},
            "choice": {"token": "debt", "words_file": "work/answers/q1.txt", "at": "2026-10-13T12:00:00"}}
    base.update(over)
    return base


def rejected_story(root: Path, verdict="rejected") -> Path:
    art = install_artifacts(root, GOOD, "QA-1")
    use_project(root)
    path = art / "work" / "automation-manifest.json"
    manifest = C.load_json(path)
    manifest["tests"][0]["critic_verdict"] = verdict
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return art


def the_repair_limit_carrier() -> None:
    """The carrier joins the ledger: no file changes nothing but the A8 line; a window puts the critic's remarks on the rows it
    covers (join by the manifest `file`), a finding no test takes goes to the window, a cleared window is `fixed`, an S7 window
    carries the triage wording and never the critic's remarks, and a record with missing keys never raises."""
    root = temp_project("qa-ledger-debts-")
    try:
        art = rejected_story(root)
        row = next(r for r in L.build(art)["rows"] if r["kind"] == "test")
        check_eq("no carrier: the rejected row has no window keys", ("remarks" in row, "repair_limit" in row), (False, False))
        check_eq("no carrier: no windows and no problem", (L.build(art)["repair_windows"], L.build(art)["repair_windows_problem"]), ([], ""))
        check_in("A8: a rejected row no window covers says the remarks were not recorded", L.NOT_RECORDED, L.render(L.build(art)))
        (art / "work" / "handoffs").mkdir(parents=True, exist_ok=True)
        (art / "work" / "handoffs" / "d-1.yaml").write_text(FORM, encoding="utf-8")
        L.write_review_debt(art, window())
        built = L.build(art)
        row = next(r for r in built["rows"] if r["kind"] == "test")
        check_eq("the window's limit is on the row", row["repair_limit"], {"stage": "S5", "counted": 2, "cap": 2, "reason": "cap"})
        check_eq("the remark joined by the manifest file is on the row, five keys",
                 [(r["id"], r["problem"], r["expected"], r["fix"], r["cause"]) for r in row["remarks"]],
                 [("F-1", "it never reads the cancelled flag", "the flag reads cancelled", "assert the flag", "test_defect")])
        check_eq("the row is named by its function and its case, never the hash", (row["function"], row["case"]), ("TC-001", "TC-001"))
        win = built["repair_windows"][0]
        check_eq("a finding no rejected test takes goes to the window line (edge 7.2)", [r["id"] for r in win["remarks"]], ["F-2"])
        check_eq("the window summary", (win["stage"], win["cases"], win["reason"], win["counted"], win["cap"], win["token"], win["fixed"], win["missing"]),
                 ("S5", ["TC-001"], "cap", 2, 2, "debt", False, []))
        check_not_in("the covered row does not print the not-recorded line", L.NOT_RECORDED, L.render(built))
        # an empty form: the row is covered and says no remark was recorded
        (art / "work" / "handoffs" / "d-1.yaml").write_text("findings: []\n", encoding="utf-8")
        row = next(r for r in L.build(art)["rows"] if r["kind"] == "test")
        check_eq("edge 7.1: an empty form leaves an empty remark list, said in the ledger", (row["remarks"], L.NOT_RECORDED in L.render(L.build(art))), ([], True))
        # F1: the rejected test then ran, failed and was triaged: the S5 window still covers its row, remarks and all
        art4 = rejected_story(temp_project("qa-ledger-debts-ran-"))
        (art4 / "work" / "handoffs").mkdir(parents=True, exist_ok=True)
        (art4 / "work" / "handoffs" / "d-1.yaml").write_text(FORM, encoding="utf-8")
        ref4 = instance_ref(art4, "TC-001")
        (art4 / "work" / "triage.json").write_text(json.dumps({"triage": [{"test": TEST_REL + "::TC-001", "instance_id": ref4, "verdict": "TEST_BUG", "evidence": "x"}]}), encoding="utf-8")
        report4 = C.load_json(art4 / "work" / "run-report.json")
        report4["results"][0].update(result="failed", status="failed", instance_id=ref4)
        (art4 / "work" / "run-report.json").write_text(json.dumps(report4), encoding="utf-8")
        L.write_review_debt(art4, window())
        ran = next(r for r in L.build(art4)["rows"] if r["kind"] == "test")
        check_eq("F1: a rejected test that failed at S6 and was triaged keeps its S5 window, its remarks and its name",
                 (ran["state"].split(":")[0], ran["repair_limit"]["stage"], [r["id"] for r in ran["remarks"]], ran["function"], L.build(art4)["repair_windows"][0]["refs"] == [ran["ref"]]),
                 ("failed", "S5", ["F-1"], "TC-001", True))
        cleanup(art4.parents[2])
        # a later review cleared the tests: the window is fixed
        art2 = rejected_story(temp_project("qa-ledger-debts-fixed-"), verdict="approved")
        (art2 / "work" / "handoffs").mkdir(parents=True, exist_ok=True)
        L.write_review_debt(art2, window(fixed_by="d-2"))
        fixed = L.build(art2)["repair_windows"][0]
        check_eq("a window whose tests are no longer rejected is fixed, with the fixing dispatch", (fixed["fixed"], fixed["fixed_by"], fixed["refs"]), (True, "d-2", []))
        cleanup(art2.parents[2])
        # S7: the window names the instance; the row carries the triage wording
        art3 = rejected_story(temp_project("qa-ledger-debts-s7-"), verdict="approved")
        ref = instance_ref(art3, "TC-001")
        (art3 / "work" / "triage.json").write_text(json.dumps({"triage": [{"test": TEST_REL + "::TC-001", "instance_id": ref, "verdict": "TEST_BUG", "evidence": "the selector no longer matches"}]}), encoding="utf-8")
        report = C.load_json(art3 / "work" / "run-report.json")
        report["results"][0].update(result="failed", status="failed", instance_id=ref, reason="the locator is stale")
        (art3 / "work" / "run-report.json").write_text(json.dumps(report), encoding="utf-8")
        L.write_review_debt(art3, window(stage="S7", cases=["TC-001"], tests=[ref], form="", critic_dispatch=""))
        s7_row = next(r for r in L.build(art3)["rows"] if r["kind"] == "test")
        check_eq("S7: a failed row covered by the window carries the limit and the triage wording, no remarks",
                 (s7_row["state"].split(":")[0], s7_row["repair_limit"]["stage"], s7_row.get("remarks"), s7_row["triage_words"]),
                 ("failed", "S7", None, "the run failed; the run's reason: the locator is stale"))
        # F4: the reason is the RUN's (`results[].reason`, artifact-contract-run.md), read under its own name; the triage row carries
        # none (its fields: test, verdict, evidence, ...), so a run that recorded no reason says exactly that
        report["results"][0].pop("reason")
        (art3 / "work" / "run-report.json").write_text(json.dumps(report), encoding="utf-8")
        check_eq("F4: a run with no reason says the run recorded none",
                 next(r for r in L.build(art3)["rows"] if r["kind"] == "test")["triage_words"], "the run failed; the run recorded no reason")
        (art3 / "work" / "run-report.json").write_text(json.dumps({k: v for k, v in report.items() if k != "results"}), encoding="utf-8")
        check_eq("F4: a run report with no results[] says the same",
                 next(r for r in L.build(art3)["rows"] if r["kind"] == "test").get("triage_words"),
                 "the run failed; the run recorded no reason")
        cleanup(art3.parents[2])
    finally:
        cleanup(root)


def the_carrier_is_written_once_and_read_whole() -> None:
    """ONE writer: a window recorded twice is one entry, another window is kept, a bad stage or reason is refused by name;
    a file that cannot be read is a problem in words and no windows; a record with keys missing names them and never raises."""
    root = temp_project("qa-ledger-debts-writer-")
    try:
        art = install_artifacts(root, GOOD, "QA-1")
        L.write_review_debt(art, window())
        L.write_review_debt(art, window(rounds={"counted": 3, "cap": 2, "by_cause": {}}))
        L.write_review_debt(art, window(critic_dispatch="d-2", cases=["TC-002"]))
        read = L.read_review_debts(art)
        check_eq("a window recorded twice is one entry, the second wins; another window is kept",
                 [(w["critic_dispatch"], w["rounds"]["counted"]) for w in read["windows"]], [("d-1", 3), ("d-2", 2)])
        check_eq("the schema version is written", C.load_json(art / "work" / "review-debts.json")["schema_version"], 1)
        for bad, what in ((window(stage="S6"), "S5 or S7"), (window(reason="whatever"), "one reason of")):
            try:
                L.write_review_debt(art, bad)
                got = ""
            except ValueError as exc:
                got = str(exc)
            check_in("a record the schema does not hold is refused by name: " + what, what, got)
        (art / "work" / "review-debts.json").write_text("{not json", encoding="utf-8")
        check_eq("an unreadable carrier is a problem in words, no windows", (L.read_review_debts(art)["windows"], bool(L.read_review_debts(art)["problem"])), ([], True))
        (art / "work" / "review-debts.json").write_text(json.dumps({"windows": [{"stage": "S5"}, 7, {"stage": "S9"}]}), encoding="utf-8")
        only = L.read_review_debts(art)
        check_eq("an entry that is no window is counted in the problem, the readable one stays", (len(only["windows"]), "2 entries" in only["problem"]), (1, True))
        check_eq("the keys a window lacks are named, never a KeyError", L.debt_missing(only["windows"][0]), ["reason", "choice", "cases"])
        # F3: what the reader could not read survives a rewrite as it stands, and the reader names its place
        broken = [7, {"stage": "S9", "cases": ["TC-9"]}]
        (art / "work" / "review-debts.json").write_text(json.dumps({"schema_version": 1, "windows": [window()] + broken}), encoding="utf-8")
        L.write_review_debt(art, window(critic_dispatch="d-2"))
        after = C.load_json(art / "work" / "review-debts.json")["windows"]
        check_eq("F3: the unreadable entries are re-emitted unchanged, in their places, and the new window is last",
                 (after[1:3], after[-1]["critic_dispatch"], len(after)), (broken, "d-2", 4))
        check_in("F3: the reader's problem line names them by place", "2 entries of the record of the repair-limit answers could not be read (place 2, 3 in the file)",
                 L.read_review_debts(art)["problem"])
        # ... and when NOTHING in the file can be read it is left as it was, with one line naming it
        import contextlib
        import io
        carrier = art / "work" / "review-debts.json"
        for text in ("{not json", json.dumps({"windows": [7, "x"]})):
            carrier.write_text(text, encoding="utf-8")
            before = carrier.read_bytes()
            said = io.StringIO()
            with contextlib.redirect_stderr(said):
                got = L.write_review_debt(art, window())
            check_eq("F3: nothing readable: the file is byte for byte as it was and nothing is returned", (carrier.read_bytes() == before, got), (True, None))
            check_eq("F3: ... and the writer printed one line naming the file", (len(said.getvalue().splitlines()), "review-debts.json is left as it was" in said.getvalue()), (1, True))
        check_eq("limit_words, cap and unknown", (L.limit_words("cap", 2, 2), L.limit_words("unknown", None, None)),
                 ("repair limit exhausted: 2 of 2 rounds about the tests themselves", "the factory could not count its repair rounds"))
        for reason in L.DEBT_REASONS:
            words = L.limit_words(reason, 1, 2)
            check_not_in("no `test_defect` in the clause of " + reason, "test_defect", words)
    finally:
        cleanup(root)


# --- t-305 N8: the verdict word travels with the ledger -----------------------------------------------------------

def the_third_verdict_in_the_ledger() -> None:
    """K-N8.13: a rebuild keeps `delivery_verdict` and `left_items`; a ledger written before the word is derived from its bool;
    ledger.md prints the word; a manual-human plan row WITH an evidence package is handed, never passed (Q17 d); a waiver
    carries the person's words on the row (`decision`)."""
    root = temp_project("qa-ledger-third-")
    try:
        art = install_artifacts(root, GOOD, "QA-1")
        use_project(root)
        previous = {"ticket": "QA-1", "rows": [], "delivery_ready": False, "delivery_verdict": "after_checks",
                    "left_items": [{"kind": "handed", "ref": "TC-009", "case": "TC-009", "counts": True}]}
        (art / "work" / "ledger.json").write_text(json.dumps(previous), encoding="utf-8")
        built = L.build(art)
        check_eq("K-N8.13 a rebuild keeps the word", built["delivery_verdict"], "after_checks")
        check_eq("K-N8.13 and the bool is exactly `yes` of that word", built["delivery_ready"], False)
        check_eq("K-N8.13 and left_items", built["left_items"], previous["left_items"])
        for old, word in (({"delivery_ready": True}, "yes"), ({"delivery_ready": False}, "no"), ({}, "no"),
                          ({"delivery_ready": "no"}, "no"), ({"delivery_verdict": "maybe", "delivery_ready": False}, "no"),
                          ({"delivery_verdict": "yes", "delivery_ready": False}, "no")):
            (art / "work" / "ledger.json").write_text(json.dumps(old), encoding="utf-8")
            built = L.build(art)
            check_eq(f"K-N8.13 a previous ledger {old} reads {word}, derived or refused", built["delivery_verdict"], word)
            check_eq(f"K-N8.13 and its bool is {word == 'yes'}", built["delivery_ready"], word == "yes")
        check_in("K-N8.13 ledger.md prints the word", "`delivery_ready: after_checks`", L.render(previous))
        check_in("K-N8.13 and `no`", "`delivery_ready: no`", L.render({"delivery_ready": False}))
        check_in("K-N8.13 and `yes`", "`delivery_ready: yes`", L.render({"delivery_ready": True}))
        # Q17 d: a manual-human plan row with an evidence package is handed to the person, never passed
        plan = (art / "test-plan.md").read_text(encoding="utf-8").replace("`manual-agent` - one-off check against the live order "
                                                                           "record", "`manual-human` - a person reads the record")
        (art / "test-plan.md").write_text(plan, encoding="utf-8")
        report = C.load_json(art / "work" / "run-report.json")
        report["manual_checks"] = []
        report["manual_human"] = [{"case": "TC-002", "evidence": "work/test-cases/checkout/TC-002.md"}]
        (art / "work" / "run-report.json").write_text(json.dumps(report), encoding="utf-8")
        (art / "work" / "ledger.json").unlink()
        doc = L.build(art)
        check_eq("K-N8.13 a manual-human row with its package is `not_executed:handed_to_person`", state_of(doc, "TS-2"),
                 "not_executed:handed_to_person")
        check_in("K-N8.13 and names the package", "work/test-cases/checkout/TC-002.md",
                 next(r["detail"] for r in doc["rows"] if r["ref"] == "TS-2"))
        check_not_in("K-N8.13 never passed_green", "passed_green", [state_of(doc, "TS-2")])
        # a waiver carries their words on the row
        pipeline = C.load_json(art / "pipeline.json")
        pipeline["gate_waivers"] = [{"gate": "A", "requirement": "R-2", "decision": "defer it, the page is down", "at": "2026-10-03T10:00:00Z"}]
        (art / "pipeline.json").write_text(json.dumps(pipeline), encoding="utf-8")
        doc = L.build(art)
        row = next(r for r in doc["rows"] if r["ref"] == "TS-2")
        check_eq("K-N8.13 the row is waived over its own state", row["state"], "waived:not_executed:handed_to_person")
        check_eq("K-N8.13 and carries the person's words, the gate and the requirement",
                 [(d["gate"], d["requirement"], d["words"]) for d in row["decision"]], [("A", "R-2", "defer it, the page is down")])
    finally:
        cleanup(root)


# --- RD1-9a: a rejection is read by one function, and a fixed flake does not outvote it -----------

def rejected_is_one_reading() -> None:
    import tempfile
    check_eq("is_rejected: the word", L.is_rejected({"critic_verdict": "rejected"}), True)
    check_eq("is_rejected: read stripped, as verdict_of", L.is_rejected({"critic_verdict": " rejected "}), True)
    check_eq("is_rejected: None", L.is_rejected(None), False)
    check_eq("is_rejected: no verdict", L.is_rejected({}), False)
    check_eq("is_rejected: unverified is the person's debt, not a rejection", L.is_rejected({"critic_verdict": "unverified"}), False)
    check_eq("is_rejected: `REJECTED` is not the critic's word (review_unrecognised)", L.is_rejected({"critic_verdict": "REJECTED"}), False)
    entry = {"case": "TC-9", "instance_id": "i9", "file": "tests/x.py", "status": "green"}
    report = {"results": [{"case": "TC-9", "instance_id": "i9", "status": "passed"}]}
    flaky = {"triage": [{"instance_id": "i9", "case": "TC-9", "verdict": "FLAKY", "fix_result": "fixed", "test": "tests/x.py"}]}
    check_eq("a fixed flake with no verdict still reads passed_green (the branch is unchanged)",
             L.test_state(entry, report, flaky)[0], "passed_green")
    check_eq("a fixed flake with an approving verdict reads passed_green",
             L.test_state(dict(entry, critic_verdict="approved"), report, flaky)[0], "passed_green")
    check_eq("a fixed flake the critic rejected reads review_rejected, never passed_green",
             L.test_state(dict(entry, critic_verdict="rejected"), report, flaky)[0], "review_rejected")
    check_eq("`REJECTED` on a fixed flake is not a rejection and not green by it (reads as before)",
             L.test_state(dict(entry, critic_verdict="REJECTED"), report, flaky)[0], "passed_green")
    # the carrier of the critic's remarks: a findings file that names the case as a WHOLE word
    with tempfile.TemporaryDirectory() as tmp:
        art = Path(tmp)
        check_eq("remarks_carrier: no findings file - empty", L.remarks_carrier(art, "TC-1"), "")
        folder = art / "work" / "test-code"
        folder.mkdir(parents=True)
        (folder / "critic-findings.md").write_text("## TC-12\n- the assertion is empty\n", encoding="utf-8")
        check_eq("remarks_carrier: TC-1 is not TC-12", L.remarks_carrier(art, "TC-1"), "")
        check_eq("remarks_carrier: TC-12 is named", L.remarks_carrier(art, "TC-12"), "work/test-code/critic-findings.md")
        (folder / "critic-findings-2.md").write_text("TC-1 asserts nothing\n", encoding="utf-8")
        check_eq("remarks_carrier: the second file names TC-1", L.remarks_carrier(art, "TC-1"), "work/test-code/critic-findings-2.md")
        check_eq("remarks_carrier: an empty case names nothing", L.remarks_carrier(art, ""), "")
    check_eq("remarks_words: a carrier is pointed to", L.remarks_words({"remarks_carrier": "work/test-code/critic-findings.md"}),
             "the critic's remarks are in work/test-code/critic-findings.md")
    check_eq("remarks_words: no carrier keeps the old words", L.remarks_words({}), L.NOT_RECORDED)
    row = {"ref": "i9", "kind": "test", "state": "review_rejected", "detail": "tests/x.py", "remarks_carrier": "work/test-code/critic-findings.md"}
    check_in("render: a rejected row with no remarks points to the file", "the critic's remarks are in work/test-code/critic-findings.md",
             L.render({"ticket": "T-1", "rows": [row]}))
    check_in("render: and without a carrier keeps the old sentence", L.NOT_RECORDED,
             L.render({"ticket": "T-1", "rows": [dict(row, remarks_carrier="")]}))


# --- FR-35: each critic verdict is its own reported state ---------------------------------------

def each_verdict_keeps_its_own_word() -> None:
    """The critic's 19 instances were 11 approved, 5 unverified, 3 rejected; the ledger read all 8
    non-approved as `review_rejected`. One state per verdict, and a word nobody holds is a defect of
    our record, never a rejection."""
    entry = {"case": "TC-9", "instance_id": "i9", "file": "tests/x.py", "status": "green"}
    report = {"results": [{"case": "TC-9", "instance_id": "i9", "status": "passed"}]}

    def state(**over):
        return L.test_state(dict(entry, **over), report, {"triage": []})

    check_eq("approved is green", state(critic_verdict="approved")[0], "passed_green")
    check_eq("approved with fixes is green", state(critic_verdict="approved_with_fixes")[0], "passed_green")
    check_eq("rejected is review_rejected", state(critic_verdict="rejected")[0], "review_rejected")
    check_eq("no verdict is review_skipped", state()[0], "review_skipped")
    got, detail = state(critic_verdict="unverified")
    check_eq("unverified is its own state", got, "review_unverified")
    check_eq("and with no reason the detail is the test alone", detail, "tests/x.py")
    _, detail = state(critic_verdict="unverified",
                      sensitivity_proof_missing_reason="the probe tool  gave no\nreceipt")
    check_eq("the critic's reason travels with it, on one line", detail,
             "tests/x.py — the probe tool gave no receipt")
    check_eq("a verdict is read stripped, as everywhere", state(critic_verdict="  unverified ")[0], "review_unverified")
    for word in ("Unverified", "maybe", "approve", "rejected!"):
        got = state(critic_verdict=word)[0]
        check_eq(f"the word {word!r} is not the critic's vocabulary: unrecognised", got,
                 f"review_unrecognised:{word.strip()}")
        check(f"and {word!r} is never read as a rejection", C.ledger_state_prefix(got) != "review_rejected", got)
        check(f"and its state is in the ledger vocabulary ({word!r})", C.is_ledger_state(got), got)
    odd = state(critic_verdict="`x`\n  y")[0]
    check_eq("a backtick and a newline never reach the state word", odd, "review_unrecognised:'x' y")
    for word in ("review_rejected", "review_unverified", "review_unrecognised", "not_verified", "partial", "error"):
        check(f"the ledger vocabulary holds {word}", C.is_ledger_state(word), word)
    check("unverified is a verdict the contract knows", "unverified" in C.CRITIC_VERDICTS)
    # Triage outranks review; review outranks proof.
    triage = {"triage": [{"instance_id": "i9", "case": "TC-9", "verdict": "APP_BUG", "test": "tests/x.py"}]}
    check_eq("a triage row outranks an unverified review",
             L.test_state(dict(entry, critic_verdict="unverified"), report, triage)[0], "failed:APP_BUG")
    check_eq("an unverified review outranks a missing proof",
             state(critic_verdict="unverified", new_or_changed=True)[0], "review_unverified")
    check_eq("and an unrecognised one outranks it too",
             state(critic_verdict="x", new_or_changed=True)[0], "review_unrecognised:x")

    # F2 (D-0013): the run result is read FIRST - an unverified verdict never hides a run failure.
    def with_result(status, **over):
        rep = {"results": [{"case": "TC-9", "instance_id": "i9", "status": status}]} if status else {"results": []}
        rep.update(over.pop("report", {}))
        return L.test_state(dict(entry, critic_verdict="unverified", **over), rep, {"triage": []})[0]

    check_eq("unverified + a green run is the person's debt", with_result("passed"), "review_unverified")
    check_eq("unverified + a red run stays a failure", with_result("failed"), "failed:untriaged")
    check_eq("unverified + an error stays an error", with_result("error"), "error")
    check_eq("unverified + a partial stays a partial", with_result("partial"), "partial")
    check_eq("unverified + a skipped run stays skipped", with_result("skipped"), "skipped:marked skipped in the run")
    check_eq("unverified + no result stays not executed", with_result(None),
             "not_executed:no result for this test in run-report.json")
    check_eq("unverified + a blocked stand stays env_blocked",
             with_result(None, report={"execution_status": "env_blocked"}), "env_blocked:user")
    check_eq("an unverified new test with an error is the error, not a missing proof",
             with_result("error", new_or_changed=True), "error")
    check_eq("and an unverified new test with a green run is still the debt",
             with_result("passed", new_or_changed=True), "review_unverified")
    check_eq("a rejected verdict is unchanged by the order (still the review's word)",
             L.test_state(dict(entry, critic_verdict="rejected"), {"results": [
                 {"case": "TC-9", "instance_id": "i9", "status": "failed"}]}, {"triage": []})[0], "review_rejected")


def no_row_is_not_a_neighbours_green() -> None:
    """HF2-6 K5 (RD1-8): a test the run recorded nothing for is `not_executed:<L.NO_RUN_RESULT>`, whatever a sibling instance of
    its case did. The case's summary used to lend the sibling's green to it (`results.get(case)`); the only case fallback left is
    the legacy step of `case_stamp.run_row_for` - an entry with no identity of its own, the only live entry of its case, the
    only current row of the case. Kills: the `results.get(case)` fallback kept in `test_state` (m6)."""
    approved = {"critic_verdict": "approved", "status": "green", "file": "tests/x.py"}
    sibling = dict(approved, case="TC-9", instance_id="sibling", test="tests/x.py::test_sibling")
    unrun = dict(approved, case="TC-9", instance_id="never_ran", test="tests/x.py::test_never_ran")
    report = {"results": [{"case": "TC-9", "instance_id": "sibling", "test": "tests/x.py::test_sibling", "status": "passed"}]}
    manifest = {"tests": [sibling, unrun]}
    wanted = "not_executed:" + L.NO_RUN_RESULT
    check_eq("the constant is the ledger's own sentence", L.NO_RUN_RESULT, "no result for this test in run-report.json")
    check_eq("K5 the instance with a green row of its own is green", L.test_state(sibling, report, {"triage": []}, None, manifest)[0],
             "passed_green")
    check_eq("K5 the instance WITHOUT a row of its own does not inherit its sibling's green",
             L.test_state(unrun, report, {"triage": []}, None, manifest)[0], wanted)
    check_eq("K5 ... and without the manifest it stands alone: not executed as well",
             L.test_state(unrun, report, {"triage": []})[0], wanted)
    # legacy: an entry with no identity of its own (a marker that is the case), one entry of the case, one row of the case
    legacy = dict(approved, case="TC-8", marker="TC-8")
    legacy_report = {"results": [{"case": "TC-8", "test": "tests/x.py::test_cap", "status": "passed"}]}
    check_eq("K5 legacy: the only entry and the only row of the case are joined (as today)",
             L.test_state(legacy, legacy_report, {"triage": []}, None, {"tests": [legacy]})[0], "passed_green")
    check_eq("K5 legacy: ... also without the manifest (the entry stands alone, the old reading)",
             L.test_state(legacy, legacy_report, {"triage": []})[0], "passed_green")
    second = dict(approved, case="TC-8", marker="TC-8", instance_id="second_of_tc8")
    two = {"tests": [legacy, second]}
    check_eq("K5 legacy: a SECOND live entry of the case without a row - neither inherits the case's row",
             [L.test_state(e, legacy_report, {"triage": []}, None, two)[0] for e in (legacy, second)], [wanted, wanted])
    dead = dict(second, note="SUPERSEDED DUPLICATE of the first")
    check_eq("K5 legacy: a dead (superseded) second entry does not count - the live one keeps its row",
             L.test_state(legacy, legacy_report, {"triage": []}, None, {"tests": [legacy, dead]})[0], "passed_green")
    two_rows = {"results": legacy_report["results"] + [{"case": "TC-8", "test": "tests/x.py::test_other", "status": "passed"}]}
    check_eq("K5 legacy: two rows of the case join nothing", L.test_state(legacy, two_rows, {"triage": []}, None, {"tests": [legacy]})[0],
             wanted)
    check_eq("K5 a stale row and a red-probe row are no run of the test",
             [L.test_state(unrun, {"results": [dict(report["results"][0], instance_id="never_ran", test="tests/x.py::test_never_ran", **over)]},
                           {"triage": []}, None, manifest)[0] for over in ({"stale": True}, {"red_probe": True},
                                                                           {"purpose": "diagnostic"})],
             [wanted] * 3)


FRESH_FILES = {"tests/conftest.py": PB.CONFTEST, "tests/plugins.py": PB.PLUGINS, "tests/test_a.py": PB.TEST_A}


def a_green_of_other_code_is_not_a_pass() -> None:
    """HF2-11c (TP2-12586): the run row's per-test shas against the bytes on disk NOW, read in `test_state` ON the row
    `run_row_for` returned (never inside the join). K1 a green of other code is `not_executed:changed_since_run`, the sentence
    is `run_freshness`'s; K2 a comment is not a change (D-0017); K3 a row with no shas keeps today's reading and SAYS it was
    not measured (FR-59); K4 an edit never hides a red. Kills: a stale green read `passed_green` (m1), the check inside
    `run_row_for` (6a K3: one join), `unknown` read `not_executed` (m3), a stale red read `passed_green` or lost (m4)."""
    fix = PB.Fixture(FRESH_FILES, [PB.row("test_a", "TC-1", "tests/test_a.py", critic_verdict="approved", status="green")],
                     scope=("TC-1",))
    try:
        fix.job(["TC-1"], completed=False)
        job = fix.job(["TC-1"])
        manifest = json.loads((fix.task / "work" / "automation-manifest.json").read_text(encoding="utf-8"))
        entry = manifest["tests"][0]
        contract = job["request"]["instance_contracts"]["test_a"]
        shas = {"instance_content_sha": contract.get("instance_content_sha", ""), "instance_code_sha": contract.get("instance_code_sha", "")}
        check("control: the job gives both per-test shas of the run", all(shas.values()), str(shas))
        no_triage = {"triage": []}
        display = "tests/test_a.py"

        def report(status="passed", **over) -> dict:
            return {"results": [dict({"case": "TC-1", "instance_id": "test_a", "status": status}, **dict(shas, **over))]}

        def state(rep=None, tri=None, e=None) -> tuple:
            return L.test_state(e or entry, rep or report(), tri or no_triage, fix.task, {"tests": [e or entry]})

        def put(old: str, new: str) -> None:
            PB.write(fix.root / "tests" / "test_a.py", PB.TEST_A.replace(old, new))

        check_eq("control: the run of the bytes on disk is a pass, and says nothing more", state(), ("passed_green", display))
        # K2: a comment, a docstring, a blank line (D-0017) is not a change
        put("    names = db.names()", "    # the names\n    names = db.names()")
        check_eq("K2: a comment-only edit after the run is still `passed_green`", state(), ("passed_green", display))
        # K1: a renamed variable is a change of the code
        put("names", "rows")
        got = state()
        check_eq("K1: a green of other code is `not_executed:changed_since_run`", got[0], L.CHANGED_STATE)
        check_eq("K1: ... the state is the ledger's own word", L.CHANGED_STATE, "not_executed:changed_since_run")
        check_in("K1: ... and the detail is the sentence of `run_freshness`", PL.WHY_RUN_CHANGED.split("{run}")[0], got[1])
        check_in("K1: ... after the test's own name", display + " — ", got[1])
        check("K1: ... a state the vocabulary holds", C.is_ledger_state(got[0]), got[0])
        check_eq("K1: an unverified review does not make a green of other code the person's debt",
                 L.test_state(dict(entry, critic_verdict="unverified"), report(), no_triage, fix.task, {"tests": [entry]})[0],
                 L.CHANGED_STATE)
        # K4: an edit never hides a red
        red = state(report("failed"))
        check_eq("K4: a red without a triage row stays `failed:untriaged`", red[0], "failed:untriaged")
        check_in("K4: ... and says the test changed after the run", " (the test changed after this run: ", red[1])
        triaged = {"triage": [{"instance_id": "test_a", "case": "TC-1", "verdict": "APP_BUG", "test": "tests/test_a.py"}]}
        red = state(report("failed"), triaged)
        check_eq("K4: a triaged red keeps its `failed:<verdict>`", red[0], "failed:APP_BUG")
        check_in("K4: ... and says so as well", " (the test changed after this run: ", red[1])
        # back to the bytes the run ran: fresh again, and a red carries no suffix
        PB.write(fix.root / "tests" / "test_a.py", PB.TEST_A)
        check_eq("K4 control: the run of the same bytes, red: no suffix", state(report("failed")), ("failed:untriaged", display))
        check_eq("K1 control: the bytes back as they were: `passed_green`", state(), ("passed_green", display))
        # K3: a row that recorded no per-test identity is not measured - today's reading, printed
        blank = report(instance_content_sha="", instance_code_sha="")
        got = state(blank)
        check_eq("K3: a row with no shas keeps today's reading", got[0], "passed_green")
        check_eq("K3: ... and says it was not measured", got[1], f"{display} — run freshness not measured: {PL.WHY_RUN_NO_IDENTITY}")
        put("names", "rows")
        check_eq("K3: ... whatever the test holds now (nothing to compare is not a change)", state(blank)[0], "passed_green")
        check_eq("K3: ... a red with no shas stays red", state(report("failed", instance_content_sha="", instance_code_sha=""))[0],
                 "failed:untriaged")
        PB.write(fix.root / "tests" / "test_a.py", PB.TEST_A)
        # the legacy step of the join: the only entry of its case, the only row of the case (6a) - same rules, nothing to measure now
        legacy = {"case": "TC-8", "marker": "TC-8", "file": "tests/test_a.py", "critic_verdict": "approved", "status": "green"}
        legacy_report = {"results": [dict({"case": "TC-8", "test": "tests/test_a.py::test_a", "status": "passed"}, **shas)]}
        got = L.test_state(legacy, legacy_report, no_triage, fix.task, {"tests": [legacy]})
        check_eq("K3 legacy: a row of the legacy step with shas and no job to measure the test now: today's reading", got[0], "passed_green")
        check_in("K3 legacy: ... printed as not measured", "run freshness not measured: ", got[1])
        # no row: 6a's reading, untouched
        check_eq("no row: still `not_executed:<NO_RUN_RESULT>`", state({"results": []})[0], "not_executed:" + L.NO_RUN_RESULT)
        # a test file that cannot be found: `unknown` in the LEDGER (Lead decision, t-129; FR-59) - today's reading, PRINTED
        gone = dict(entry, file="tests/gone.py", instance_id="gone")
        check_eq("a green row whose test file is absent: `passed_green` with the printed suffix (the unknown is named, never silent)",
                 L.test_state(gone, report(instance_id="gone"), no_triage, fix.task, {"tests": [gone]}),
                 ("passed_green", f"tests/gone.py — run freshness not measured: {PL.WHY_NO_FILE}"))
        check_eq("... a red row whose test file is absent keeps its state and adds no suffix (a red never depends on it)",
                 L.test_state(gone, report("failed", instance_id="gone"), no_triage, fix.task, {"tests": [gone]}),
                 ("failed:untriaged", "tests/gone.py"))
        check_eq("... the window's predicate is not the ledger's: a missing file stays `stale` there (it runs inside the project)",
                 PL.run_freshness(gone, report(instance_id="gone")["results"][0], fix.task), ("stale", PL.WHY_NO_FILE))
    finally:
        fix.close()


# --- the level a test reached (D-0010 / D-0012) -------------------------------------------------

def the_level_a_test_reached_is_a_field_of_its_row() -> None:
    root = temp_project("qa-ledger-proof-")
    try:
        (root / TEST_REL).write_text(TEST_SRC, encoding="utf-8")
        use_project(root)
        task = install_artifacts(root, GOOD, "T-1")
        sha = digest(root / TEST_REL)
        manifest_path = task / "work" / "automation-manifest.json"
        base = C.load_json(manifest_path)

        def build(entry_over=None, receipt=None, unresolved=None, name="r"):
            manifest = json.loads(json.dumps(base))
            test = manifest["tests"][0]
            test.update(instance_id="i-coupon", file=TEST_REL,
                        case_version_links=[{"case_id": "TC-001", "version": "cv_x"}],
                        trace_binding={"test_content_sha": sha})
            test.update(entry_over or {})
            if receipt is not None:
                test["sensitivity_proof"] = {"receipt_ref": put_receipt(task, name, receipt)}
            if unresolved:
                manifest["unresolved"] = unresolved
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            return L.build(task), manifest

        def row_of(doc):
            return next(r for r in doc["rows"] if r["ref"] == "i-coupon")

        doc, _ = build({"new_or_changed": True}, receipt_body("i-coupon", sha), name="live")
        row = row_of(doc)
        check_eq("a new test with a live receipt: green", row["state"], "passed_green")
        check_eq("its row names the level", row["proof_level"], "live")
        check_eq("and says it in the vocabulary's words", row["proof_words"], "the check is live")

        doc, _ = build({"new_or_changed": True}, receipt_body("i-coupon", sha, proof_level="catches_broken_product",
                                                                probe_tool="red_sandbox.py", mutation="real_behavior",
                                                                mutation_kind="real_behavior"), name="prod")
        check_eq("a product-level receipt satisfies the live requirement and shows its own level",
                 (row_of(doc)["state"], row_of(doc)["proof_level"]), ("passed_green", "catches_broken_product"))

        legacy = receipt_body("i-coupon", sha, mutation="real_behavior")
        for key in ("proof_level", "probe_tool", "mutation_kind"):
            legacy.pop(key)
        doc, _ = build({"unchanged": True, "change_disposition": "unchanged"}, legacy, name="old")
        check_eq("a receipt written before levels existed is the product level",
                 row_of(doc)["proof_level"], "catches_broken_product")

        doc, _ = build({"new_or_changed": True})
        row = row_of(doc)
        check_eq("a new test with no receipt is not verified", row["state"], "not_verified:missing_sensitivity_proof")
        check_eq("its level is null (probed by nobody)", row["proof_level"], None)
        check_eq("and it says 'not probed'", row["proof_words"], PL.words(None))

        doc, _ = build({"change_disposition": "unchanged"})
        row = row_of(doc)
        check_eq("an unchanged test needs nothing and is green", row["state"], "passed_green")
        check_eq("its level is not_required", row["proof_level"], L.PROOF_NOT_REQUIRED)
        check_eq("in the vocabulary's words", row["proof_words"], PL.not_required_words())

        handed = [{"case": "TC-001", "reason": "handed_to_person", "detail": "api: run it where the keys are"}]
        doc, _ = build({"new_or_changed": True}, unresolved=handed)
        row = row_of(doc)
        check_eq("a handed test is never asked for a proof", row["proof_level"], L.PROOF_NOT_REQUIRED)
        check("and its state is not the missing-proof one", not row["state"].startswith("not_verified"), row["state"])

        # A receipt for other bytes shows no level; a comment-only edit keeps it; a test file that is
        # gone shows unknown, not "not probed" (FR-41).
        doc, _ = build({"new_or_changed": True}, receipt_body("i-coupon", "0" * 64), name="stale")
        row = row_of(doc)
        check_eq("a receipt for other bytes: no level", row["proof_level"], None)
        check_eq("and the test is not verified", row["state"], "not_verified:missing_sensitivity_proof")
        doc, manifest = build({"new_or_changed": True}, receipt_body("i-coupon", sha), name="gone")
        (root / TEST_REL).unlink()
        row = row_of(L.build(task))
        check_eq("a row whose test file cannot be found is unknown", row["proof_level"], L.PROOF_UNKNOWN)
        check_eq("in words that say so", row["proof_words"], PL.unknown_words())
        check("and it is not 'not probed'", row["proof_words"] != PL.words(None), row["proof_words"])
        (root / TEST_REL).write_text(TEST_SRC, encoding="utf-8")
    finally:
        os_env_reset()
        cleanup(root)


# --- t-134 P5-E: the words and the reason of a test that is not probed ---------------------------

NOT_PROBED_WHY = "not probed ("   # every not-required word of the vocabulary opens so; the bare "not probed" is a required row's


def the_words_follow_the_reason() -> None:
    """A not-required row says WHY (`proof_level.not_required_why`), in `words_for(reason)`: an
    unchanged and an unmeasured test share today's words (V9), a handed one has its own on keyed and
    keyed-less rows alike (V11). `proof_reason` sits next to `proof_level`. The invariants: "unchanged
    test" only for `unchanged` / `unmeasured`; a handed row never reads it; a required row never
    reads a not-required word."""
    import delivery_summary as S
    root = temp_project("qa-ledger-reason-")
    try:
        (root / TEST_REL).write_text(TEST_SRC, encoding="utf-8")
        use_project(root)
        task = install_artifacts(root, GOOD, "T-1")
        sha = digest(root / TEST_REL)
        manifest_path = task / "work" / "automation-manifest.json"
        base = C.load_json(manifest_path)
        handed = [{"case": "TC-001", "reason": "handed_to_person", "detail": "api: run it where the keys are"}]
        fresh = {"value": "unchanged", "basis": "no change since the base", "measured_on": {TEST_REL: sha}}

        def build(entry_over=None, unresolved=None):
            manifest = json.loads(json.dumps(base))
            manifest["tests"][0].update(instance_id="i-coupon", file=TEST_REL,
                                        case_version_links=[{"case_id": "TC-001", "version": "cv_x"}],
                                        trace_binding={"test_content_sha": sha})
            manifest["tests"][0].update(entry_over or {})
            if unresolved:
                manifest["unresolved"] = unresolved
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            doc = L.build(task)
            return next(r for r in doc["rows"] if r["ref"] == "i-coupon"), doc, manifest

        unchanged_words, handed_words = PL.not_required_words(), PL.handed_words()
        cases = {  # label -> (entry override, unresolved, reason, words)
            "a legacy row (no novelty key), no flag": ({"change_disposition": "unchanged"}, None,
                                                       "unmeasured", unchanged_words),
            "a measured, fresh unchanged": ({"novelty": fresh}, None, "unchanged", unchanged_words),
            "a handed, flagged legacy row": ({"new_or_changed": True}, handed, "handed", handed_words),
            "a handed, keyless, unflagged row": ({"change_disposition": "unchanged"}, handed,
                                                 "handed", handed_words),
            "a handed row whose novelty is a fresh unchanged": ({"novelty": fresh}, handed, "handed", handed_words),
            "a handed row whose novelty is new": ({"novelty": {"value": "new"}}, handed, "handed", handed_words),
            "a handed row whose novelty is unknown": ({"novelty": {"value": "unknown"}}, handed, "handed",
                                                      handed_words),
        }
        seen = []
        for label, (over, unresolved, reason, words) in cases.items():
            row, _, _ = build(over, unresolved)
            check_eq(f"{label}: not required", row["proof_level"], L.PROOF_NOT_REQUIRED)
            check_eq(f"{label}: its reason", row.get("proof_reason"), reason)
            check_eq(f"{label}: its words follow the reason", row["proof_words"], words)
            seen.append(row)
        check("a handed row never reads the unchanged words, keyed or not",
              all("unchanged test" not in r["proof_words"] for r in seen if r.get("proof_reason") == "handed"),
              str([r["proof_words"] for r in seen]))
        check("the handed words are not the unchanged words", handed_words != unchanged_words, handed_words)

        # The ledger says what the ONE reader says (FR-17): the words and `proof_reason` are the reader's
        # reason and its words, for a row that is handed AND measured fresh-unchanged, handed wins (R6).
        row, doc, manifest = build({"novelty": fresh}, handed)
        check_eq("a handed and fresh-unchanged row: the reader's reason, and the words follow it",
                 (row.get("proof_reason"), row["proof_words"], PL.not_required_why(manifest["tests"][0], manifest)),
                 ("handed", handed_words, "handed"))
        row, _, _ = build({"novelty": fresh, "new_or_changed": True}, handed)
        check_eq("a handed row that a flag also calls new: handed wins", (row.get("proof_reason"), row["proof_words"]),
                 ("handed", handed_words))

        # A required row: reason "", and never a not-required word.
        required = {
            "a flagged new test, no receipt": {"new_or_changed": True},
            "a measured new test": {"novelty": {"value": "new"}},
            "a measured changed test": {"novelty": {"value": "changed"}},
            "novelty unknown (an S0 base that cannot answer)": {"novelty": {"value": "unknown"}},
            "an unchanged whose measured file changed since": {"novelty": dict(fresh, measured_on={TEST_REL: "0" * 64})},
        }
        for label, over in required.items():
            row, _, _ = build(over)
            check_eq(f"{label}: required, so the level is null", row["proof_level"], None)
            check_eq(f"{label}: and the reason is empty", row.get("proof_reason"), "")
            check_eq(f"{label}: its words are the reached ones, 'not probed'", row["proof_words"], PL.words(None))
            check_not_in(f"{label}: never a not-required word", NOT_PROBED_WHY, row["proof_words"])

        # Edge (i): no manifest at all. Whatever the reader says, proof_shown passes it through.
        entry = json.loads(json.dumps(base))["tests"][0]
        entry.update(instance_id="i-coupon", file=TEST_REL, change_disposition="unchanged",
                     case_version_links=[{"case_id": "TC-001", "version": "cv_x"}],
                     trace_binding={"test_content_sha": sha})
        shown = L.proof_shown(entry, None, task)
        check_eq("manifest None: no exception, the words follow the reader's reason",
                 shown, (L.PROOF_NOT_REQUIRED, PL.words_for(PL.not_required_why(entry, None))))
        check_eq("...and a legacy row with no manifest is today's words", shown[1], unchanged_words)
        check_eq("a non-row entry with no manifest: passed through, no exception",
                 L.proof_shown("not a row", None, task),
                 (L.PROOF_NOT_REQUIRED, PL.words_for(PL.not_required_why("not a row", None))))

        # Edge (ii): a reason outside the four. The reader's own fallback is "" (words_for), so the
        # row is not-required with empty words - never an exception, never the unchanged words.
        real = PL.not_required_why
        PL.not_required_why = lambda entry, manifest: "no_such_reason"
        try:
            odd = L.proof_shown(entry, None, task)
        finally:
            PL.not_required_why = real
        check_eq("a reason outside the four: proof_shown does not raise; its words are the reader's ''",
                 odd, (L.PROOF_NOT_REQUIRED, ""))
        check_eq("...which is what words_for says of it", PL.words_for("no_such_reason"), "")

        # The invariant over one ledger of all of them, read at the row level.
        for label, (over, unresolved, _, _) in cases.items():
            row, _, _ = build(over, unresolved)
            said_unchanged = "unchanged test" in row["proof_words"]
            check(f"{label}: 'unchanged test' only for unchanged / unmeasured",
                  said_unchanged == (row.get("proof_reason") in ("unchanged", "unmeasured")), str(row))

        # ledger.md: the words travel as the row carries them.
        doc = {"ticket": "T-1", "rows": [
            {"ref": "h", "kind": "test", "state": "passed_green", "detail": "tests/h.py::test_h",
             "proof_level": L.PROOF_NOT_REQUIRED, "proof_words": handed_words, "proof_reason": "handed"}]}
        check_in("a handed green row reads its own words in ledger.md",
                 f"tests/h.py::test_h; {handed_words} |", L.render(doc))

        # The delivery summary says it in the same words (V7, FR-10), and the level's total stays.
        row, doc, _ = build({"new_or_changed": True}, handed)
        summary = S.build(task, doc)
        check_eq("the summary's level total is by level id", summary["proof_levels"], {L.PROOF_NOT_REQUIRED: 1})
        check_in("a handed test is counted under the handed words",
                 f"Tests by proof level: {handed_words}: 1", S.render(summary))
        check_not_in("...and not under the unchanged words", "unchanged test", S.render(summary))
        row, doc, _ = build({"novelty": fresh})
        check_in("an unchanged test is counted under today's words",
                 f"Tests by proof level: {unchanged_words}: 1", S.render(S.build(task, doc)))
    finally:
        os_env_reset()
        cleanup(root)


def the_summary_line_counts_by_reason() -> None:
    """`delivery_summary.proof_levels_line`: the level id `not_required` keeps its total; its parts are
    split by the words of their reasons (V7)."""
    import delivery_summary as S
    today, handed = PL.not_required_words(), PL.handed_words()
    mixed = S.proof_levels_line({"live": 1, L.PROOF_NOT_REQUIRED: 4},
                                {"unchanged": 1, "unmeasured": 2, "handed": 1})
    check_eq("unchanged + unmeasured share one part, handed has its own, the total is 4",
             mixed, f"Tests by proof level: the check is live: 1; {today}: 3; {handed}: 1")
    check_eq("a ledger with no reasons (written before proof_reason): today's words, the level's total",
             S.proof_levels_line({L.PROOF_NOT_REQUIRED: 2}), f"Tests by proof level: {today}: 2")
    check_eq("reasons that do not add up to the level's total: the total wins, today's words",
             S.proof_levels_line({L.PROOF_NOT_REQUIRED: 3}, {"handed": 1}), f"Tests by proof level: {today}: 3")
    check_eq("a reason the vocabulary has no words for reads as today's words",
             S.proof_levels_line({L.PROOF_NOT_REQUIRED: 2}, {"no_such_reason": 1, "": 1}),
             f"Tests by proof level: {today}: 2")
    check_eq("only handed rows: only the handed words",
             S.proof_levels_line({L.PROOF_NOT_REQUIRED: 2}, {"handed": 2}), f"Tests by proof level: {handed}: 2")
    check_eq("a reasons value that is not an object does not raise",
             S.proof_levels_line({L.PROOF_NOT_REQUIRED: 2}, ["handed"]), f"Tests by proof level: {today}: 2")
    check_eq("edge (v): no not-required row: the line is what it was",
             S.proof_levels_line({"live": 2, "none": 1}, {}),
             "Tests by proof level: the check is live: 2; not probed: 1")
    check_eq("...and with no counts at all, no line", S.proof_levels_line({}, {"handed": 1}), "")


def os_env_reset() -> None:
    """`use_project` pins hooklib's project root inside this process; give it back."""
    import os
    os.environ.pop("CLAUDE_PROJECT_DIR", None)
    import hooklib
    hooklib._PROJECT_ROOT_CACHE = None


# --- ledger.md: a green test says how sure its check is ------------------------------------------

def the_level_words_reach_the_markdown() -> None:
    doc = {"ticket": "T-1", "rows": [
        {"ref": "a", "kind": "test", "state": "passed_green", "detail": "tests/a.py::test_a",
         "proof_level": "live", "proof_words": "the check is live"},
        {"ref": "b", "kind": "test", "state": "passed_green", "detail": "tests/b.py::test_b",
         "proof_level": "not_required", "proof_words": "not probed (unchanged test)"},
        {"ref": "c", "kind": "test", "state": "review_unverified", "detail": "tests/c.py::test_c",
         "proof_level": None, "proof_words": "not probed"},
        {"ref": "d", "kind": "test", "state": "passed_green", "detail": "tests/d.py::test_d"},
        {"ref": "TS-1", "kind": "plan_row", "state": "passed_green", "detail": "TC-001"},
    ]}
    lines = {ln.split("|")[1].strip(): ln for ln in L.render(doc).splitlines() if ln.startswith("| ") and "---" not in ln}
    check_in("a green test row appends its level words", "tests/a.py::test_a; the check is live |", lines["a"])
    check_in("an unchanged one says so", "tests/b.py::test_b; not probed (unchanged test) |", lines["b"])
    check_not_in("a row that is not green says nothing about the level", "not probed", lines["c"])
    check("a legacy row (no proof_words) keeps its cell as it was", lines["d"].endswith("| tests/d.py::test_d |"), lines["d"])
    check("a plan row is untouched", lines["TS-1"].endswith("| TC-001 |"), lines["TS-1"])
    long_detail = "tests/very/long/path/to/some/module/test_it.py::test_something_with_a_long_name_indeed"
    doc = {"ticket": "T-1", "rows": [{"ref": "e", "kind": "test", "state": "passed_green", "detail": long_detail,
                                       "proof_level": "live", "proof_words": "the check is live"}]}
    text = L.render(doc)
    check_in("a long detail keeps its footnote and still shows the words", "[1]; the check is live |", text)


# --- t-227c (P20): a Then whose expected value nobody confirmed is never green -------------------------------------

def an_unconfirmed_then_is_never_green() -> None:
    """cmp2 TC_015: Thens 1-3 asserted and green, Then 4 (P-multi) has no source for its value. The ledger
    never read `then_bindings`, so the row said `passed_green`. The new state sits AFTER every failure word and
    BEFORE `passed_green` (C2), and it holds nothing (F7): `person_debts` lists it."""
    case = "TP1-15045_TC_015"
    green = {"case": case, "instance_id": "test_put[p]", "file": "tests/t.py", "covers": [case],
             "critic_verdict": "approved", "status": "green"}
    bound = [{"case": case, "then": n, "instance_id": "test_put[p]", "assertion_ref": "tests/t.py:9", "status": "covered"}
             for n in (1, 2, 3)]
    unknown = {"case": case, "then": 4, "instance_id": None, "assertion_ref": None, "status": "unresolved",
               "reason": L.EXPECTATION_UNCONFIRMED, "question": "Q7", "observed": "403"}
    ran = {"current_results": [{"instance_id": "test_put[p]", "case": case, "status": "passed"}]}
    red = {"current_results": [{"instance_id": "test_put[p]", "case": case, "status": "failed", "reason": "AssertionError"}]}
    row = {"ts": "TS-15", "disposition": "automate"}
    by_row = {"TS-15": [case]}

    def state(manifest, report=ran, triage=None):
        return L.plan_row_state(row, manifest, report, triage or {}, by_row)

    control = state({"tests": [green], "then_bindings": bound})
    check_eq("CONTROL: Thens 1-3 bound and green, no unknown Then: the row IS green", control[0], "passed_green")
    got, detail = state({"tests": [green], "then_bindings": bound + [unknown]})
    check_eq("TC_015: the same row with Then 4 unknown NEVER reads passed_green", got, "not_verified:expectation_unconfirmed")
    check_eq("and the state is the one constant every reader shares", got, L.NOT_VERIFIED_UNCONFIRMED)
    check_in("its detail names the Then and the question", f"{case} Then 4", detail)
    check_in("the value the test saw, which it did not assert", "observed: 403", detail)
    check_in("and what is wanted of the person, in the task's own terms (FR-20)", "Needed: your answer to Q7", detail)
    _, silent = state({"tests": [green], "then_bindings": bound + [dict(unknown, observed=None)]})
    check_in("an absent `observed` (the test never reached the value) prints `observed: not recorded`", "observed: not recorded", silent)
    _, no_key = state({"tests": [green], "then_bindings": bound + [{k: v for k, v in unknown.items() if k != "observed"}]})
    check_in("and so does a row with no `observed` key at all", "observed: not recorded", no_key)
    check("the state is in the ledger vocabulary", C.is_ledger_state(got), got)
    # C2: the order. A failed Then outranks an unknown one; the new word outranks only green.
    triage = {"triage": [{"instance_id": "test_put[p]", "case": case, "verdict": "APP_BUG", "test": "tests/t.py"}]}
    check("a case with a failed Then AND an unknown Then reads failed",
          state({"tests": [green], "then_bindings": bound + [unknown]}, red, triage)[0].startswith("failed:"),
          state({"tests": [green], "then_bindings": bound + [unknown]}, red, triage)[0])
    check_eq("a flaky instance that is not fixed outranks it too",
             state({"tests": [green], "then_bindings": bound + [unknown]}, ran,
                   {"triage": [{"instance_id": "test_put[p]", "case": case, "verdict": "FLAKY", "test": "tests/t.py"}]})[0],
             "not_verified_flaky")
    check_eq("a partial run outranks it",
             state({"tests": [green], "then_bindings": bound + [unknown]},
                   {"current_results": [{"instance_id": "test_put[p]", "case": case, "status": "partial"}]})[0], "partial")
    # temporal edge: every manifest written before t-227 has no such row and reads as it did.
    check_eq("LEGACY: a manifest with no then_bindings at all (every story before t-227) reads as today",
             state({"tests": [green]})[0], "passed_green")
    # HF2-5 (5a-K2, A1) moved this key: it read `passed_green` for a Then-level `deferred_by_decision:*` row beside a green test,
    # which is the defect A1 names (the person's recorded deferral silently green). It stays the word "not the new word": the
    # state is the deferral's own, never `not_verified:expectation_unconfirmed`.
    check_eq("A binding that says `deferred_by_decision` is not the unconfirmed word (HF2-5: it reads the deferral's own state)",
             state({"tests": [green], "then_bindings": bound + [dict(unknown, reason="deferred_by_decision:gate A")]})[0],
             "deferred_by_decision")
    check_eq("a binding of ANOTHER case never leaks into this row",
             state({"tests": [green], "then_bindings": bound + [dict(unknown, case="TP1-15045_TC_099")]})[0], "passed_green")
    check_eq("a COVERED binding that carries the word is not a gap (the status decides)",
             state({"tests": [green], "then_bindings": bound + [dict(unknown, status="covered")]})[0], "passed_green")
    # F7: it holds nothing, and the person is shown it.
    doc = {"ticket": "T-1", "delivery_ready": True, "reasons": [], "rows": [
        {"ref": "TS-15", "kind": "plan_row", "state": got, "detail": detail},
        {"ref": "TS-1", "kind": "plan_row", "state": "passed_green", "detail": "TC-001"}]}
    check_eq("person_debts lists exactly the unconfirmed row", [d["ref"] for d in L.person_debts(doc)], ["TS-15"])
    text = L.render(doc)
    check_in("the rendered ledger shows it under the person's own heading", "Left with you (nothing blocks on it)", text)
    check_in("with the question wanted", "Needed: your answer to Q7", text)
    check_eq("a ledger with no such row prints no such heading", "Left with you" in L.render(dict(doc, rows=doc["rows"][1:])), False)


def a_deferred_then_beside_a_green_is_deferred() -> None:
    """HF2-5 (5a-K2, A1; F-12): a Then a person's decision put off (`then_bindings` row `deferred_by_decision:*`) beside a green
    test of its case read `passed_green` - the person's recorded deferral vanished from the ledger. It reads
    `deferred_by_decision` now, with the Then and the decision in the detail. The branch sits after every failure, flaky, partial,
    error, unconfirmed, skipped, manual and green-open word (an observed red beats a deferral) and before the blocked and
    hand-off remainders."""
    case = "TC-070"
    green = {"case": case, "instance_id": "test_a", "file": "tests/t.py", "covers": [case], "status": "green"}
    bound = [{"case": case, "then": n, "instance_id": "test_a", "assertion_ref": "tests/t.py:9", "status": "covered"} for n in (1, 2)]

    def row(then, reason, **over):
        return dict({"case": case, "then": then, "instance_id": None, "assertion_ref": None, "status": "unresolved",
                     "reason": reason, "detail": "d"}, **over)

    ran = {"current_results": [{"instance_id": "test_a", "case": case, "status": "passed"}]}
    failed = {"current_results": [{"instance_id": "test_a", "case": case, "status": "failed", "reason": "AssertionError"}]}
    by_row = {"TS-70": [case]}

    def state(bindings, report=ran, triage=None):
        return L.plan_row_state({"ts": "TS-70", "disposition": "automate"}, {"tests": [green], "then_bindings": bound + bindings},
                                report, triage or {}, by_row)

    check_eq("5a-K2 CONTROL: two bound Thens, nothing deferred: green", state([])[0], "passed_green")
    got = state([row(3, "deferred_by_decision:gate A")])
    check_eq("5a-K2: a Then-level deferred row beside a green reads the deferral's state, with the Then and the decision",
             got, ("deferred_by_decision", f"{case} Then 3: deferred_by_decision:gate A"))
    check("5a-K2: the state is in the ledger vocabulary", C.is_ledger_state(got[0]), got[0])
    check_eq("5a-K2: two deferred Thens are both named, in the manifest's order",
             state([row(3, "deferred_by_decision:gate A"), row(4, "deferred_by_decision:S5")])[1],
             f"{case} Then 3: deferred_by_decision:gate A; {case} Then 4: deferred_by_decision:S5")
    check_eq("5a-K2: red wins - a failed run of the case reads `failed:*`, not the deferral (m2: the branch above `failed`)",
             state([row(3, "deferred_by_decision:gate A")], failed)[0].startswith("failed:"), True)
    check_eq("5a-K2: the deferral outranks the hand-off remainder beside it",
             state([row(3, "deferred_by_decision:gate A"), row(4, "handed_to_person", owner="person")])[0], "deferred_by_decision")
    check_eq("5a-K2: ... and the blocked Then beside it",
             state([row(3, "deferred_by_decision:gate A"), row(4, C.BLOCKED_BY_CHECK, blocking_check="TC-071")])[0], "deferred_by_decision")
    check_eq("5a-K2: an unconfirmed Then is said before it (the order of the words above `passed_green`)",
             state([row(3, "deferred_by_decision:gate A"), row(4, L.EXPECTATION_UNCONFIRMED, question="Q1")])[0],
             L.NOT_VERIFIED_UNCONFIRMED)
    check_eq("5a-K2: a COVERED row that carries the word is no deferral (the status decides)",
             state([row(3, "deferred_by_decision:gate A", status="covered")])[0], "passed_green")
    check_eq("5a-K2: a deferred row whose Then reads as none (`then: 0`) is still a deferral, said by its case alone (the unknown "
             "never becomes green)", state([row(0, "deferred_by_decision:gate A")]), ("deferred_by_decision", f"{case}: deferred_by_decision:gate A"))
    check_eq("5a-K2: a deferred row of ANOTHER case never leaks into this row",
             state([row(3, "deferred_by_decision:gate A", case="TC-099")])[0], "passed_green")


# --- t-250 B3: the `## Manual evidence` line speaks the phase words ------------------------------------------------------

def the_manual_evidence_line_speaks_the_phase_words() -> None:
    """The ledger printed the raw `phase` of each evidence ref. A record written before the rename says `before` /
    `after`; one written now says `pre_action` / `post_action`; the dashboard shows the phase words either way, through
    the ONE table in grammar. The ledger's own line carries no link and no phase word since t-423 (the owner's word 31.10.2026:
    a delivered text says only whether the screenshots were provided): case, result, expected, actual, the sentence."""
    import grammar as G
    refs = [{"phase": "pre_action", "path": "evidence/" + "a" * 64 + ".png"},
            {"phase": "post_action", "path": "evidence/" + "b" * 64 + ".png"},
            {"phase": "supporting", "path": "evidence/" + "c" * 64 + ".txt"}]
    old = [dict(refs[0], phase="before"), dict(refs[1], phase="after"), refs[2]]
    row = lambda case, evidence_refs: {"case": case, "result": "pass", "expected": "it reads cancelled",  # noqa: E731
                                       "actual": "it read cancelled", "evidence_refs": evidence_refs}
    doc = {"ticket": "T-1", "rows": [], "manual_evidence": {"rows": [row("TC-1", refs), row("TC-2", old)], "errors": []}}
    lines = [ln for ln in L.render(doc).splitlines() if ln.startswith("- TC-")]
    check_eq("t-423 F2: a record with the phase words: the line ends with the sentence, no link, no path", lines[0],
             "- TC-1: pass — expected: it reads cancelled; actual: it read cancelled — " + G.SHOTS_PROVIDED)
    check_eq("a legacy record (before / after): the same line", lines[1].split(" — ", 2)[2], G.SHOTS_PROVIDED)
    check_not_in("and the raw legacy word never reaches the line", "before", lines[1].split(" — ", 2)[2])
    check_eq("the table is three words", G.MANUAL_PHASE_WORDS, ("pre_action", "post_action", "supporting"))
    check_eq("the aliases are the two old words", G.MANUAL_PHASE_ALIASES, {"before": "pre_action", "after": "post_action"})
    check_eq("a phase nobody knows keeps its own word (never hidden)", G.manual_phase_word("baseline"), "baseline")
    check_eq("no phase at all: the generic word, as before", (G.manual_phase_word(None), G.manual_phase_word("")), ("evidence", "evidence"))
    check_not_in("t-423 F2: an unknown phase word is not printed either: the ledger line has no phase word", "baseline",
                 L.render({"ticket": "T-1", "rows": [], "manual_evidence": {"rows": [row("TC-3", [dict(refs[0], phase="baseline")])]}}))
    check_eq("a ledger with no manual evidence prints no such section",
             "## Manual evidence" in L.render({"ticket": "T-1", "rows": [], "manual_evidence": {"rows": []}}), False)


def the_dashboard_prints_the_same_phase_words() -> None:
    """The dashboard's manual-evidence table printed the raw `phase` too (its fixture holds no refs, so no other test
    reads that word). One exported file per legacy phase: the link text is the phase word, not `before` / `after`."""
    import hashlib
    import tempfile
    from dashboard_fixture import build
    import factory_dashboard as D
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        build(root)
        task = root / "qa-factory" / "artifacts" / "DEMO-15045"
        ledger_path = task / "work" / "ledger.json"
        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
        refs = []
        for phase, data in (("before", b"one"), ("after", b"two"), ("supporting", b"three")):
            digest = hashlib.sha256(data).hexdigest()
            (task / "evidence").mkdir(exist_ok=True)
            (task / "evidence" / f"{digest}.png").write_bytes(data)
            refs.append({"phase": phase, "path": f"evidence/{digest}.png"})
        ledger["manual_evidence"] = {"rows": [{"case": "TC-LEGACY", "result": "pass", "evidence_validated": True,
                                               "evidence_refs": refs}], "errors": []}
        ledger_path.write_text(json.dumps(ledger), encoding="utf-8")
        import contextlib
        import io
        with contextlib.redirect_stdout(io.StringIO()):
            D.main(["--root", str(root)])
        page = (root / "qa-factory" / "state" / "factory-dashboard.html").read_text(encoding="utf-8")
        row = next((r for r in page.split("<tr>") if "TC-LEGACY" in r), "")
        check("(the fixture's row is on the page)", bool(row), page[:200])
        check_in("the dashboard prints the phase words: the legacy before is pre_action", ">pre_action</a>", row)
        check_in("and after is post_action", ">post_action</a>", row)
        check_in("and supporting is itself", ">supporting</a>", row)
        check_not_in("never the raw legacy word", ">before</a>", row)


def one_test_covers_three_cases() -> None:
    """HF2-3 (3c1), TP1-12586: the ledger of a task on disk (`ledger.build`, the real path) and the order of the
    branches. The per-key states of the two shapes are in `test_mixed_then_outcomes.py`; here, the table the delivery
    check reads and the keys that pin WHERE the new branches sit."""
    from harness import temp_dir
    import test_mixed_then_outcomes as M
    top = temp_dir("qa-ledger-mixed-")
    try:
        doc = L.build(M.on_disk(M.shape_b(), top))
        check_eq("mixed: the real build puts TS-4 failed and TS-5 / TS-6 behind it",
                 [state_of(doc, t) for t in ("TS-4", "TS-5", "TS-6")], ["failed:untriaged", L.BLOCKED_STATE, L.BLOCKED_STATE])
        check("mixed: the new state is in the ledger vocabulary", all(C.is_ledger_state(state_of(doc, t)) for t in ("TS-5", "TS-6")))
        detail = next(r["detail"] for r in doc["rows"] if r["ref"] == "TS-5")
        check_in("mixed: the row says what the Then waits for", "TC-005 Then 1: not proven - the test stopped at TC-004 Then 2", detail)
        check_in("mixed: ... and the table carries the state", L.BLOCKED_STATE, L.render(doc))
        # m1: a decided deferral of another case of the row outranks the failed case beside it
        both = M.shape_b()
        both["manifest"]["unresolved"].append({"case": "TC-009", "reason": "deferred_by_decision:gate A", "detail": "later"})
        state, _ = L.plan_row_state({"ts": "TS-4", "disposition": "automate"}, both["manifest"], both["report"], {},
                                    {"TS-4": ["TC-004", "TC-009"]})
        check_eq("mixed: a decided deferral outranks the failed case beside it (the order of the branches)", state,
                 "deferred_by_decision")
        # a failure word of the case itself is said before the blocked Then
        a = M.shape_a()
        a["report"]["current_results"].append({"instance_id": "g5_second", "case": "TC-005", "status": "partial"})
        a["manifest"]["tests"].append({"instance_id": "g5_second", "file": "tests/test_generic.py", "covers": ["TC-005"],
                                       "status": "green"})
        check_eq("mixed: a partial run of the case itself is said before the blocked Then",
                 L.plan_row_state({"ts": "TS-5", "disposition": "automate"}, a["manifest"], a["report"], {},
                                  {"TS-5": ["TC-005"]})[0], "partial")
        # the empty outcome: no row, no red, no blocked Then -> the state the ledger gave before
        plain = M.shape_b()
        plain["manifest"]["unresolved"] = []
        plain["report"] = {"current_results": [dict(r, status="passed") for r in plain["report"]["current_results"]]}
        check_eq("mixed: nothing red, nothing blocked -> green", L.plan_row_state(
            {"ts": "TS-5", "disposition": "automate"}, plain["manifest"], plain["report"], {}, {"TS-5": ["TC-005"]}),
            ("passed_green", "TC-005"))
    finally:
        cleanup(top)


def rollup_status_is_the_per_instance_projection() -> None:
    """FA-14: `rollup_status` is NOT changed by HF2-3 - the red of one instance still makes the case's rollup `failed`;
    which Thens that red belongs to is `ledger.plan_row_state`'s and the trace's (from `then_bindings`). Pinned."""
    check_eq("rollup: pass + fail -> failed", C.rollup_status(["passed", "failed"]), "failed")
    check_eq("rollup: pass + skip -> partial", C.rollup_status(["passed", "skipped"]), "partial")
    check_eq("rollup: pass + pass -> passed", C.rollup_status(["passed", "pass"]), "passed")
    check_eq("rollup: error without a failure -> error", C.rollup_status(["passed", "error"]), "error")
    check_eq("rollup: nothing -> empty", C.rollup_status([]), "")
    check_in("rollup: the docstring says where Then outcomes are read",
             "per-instance projection; Then outcomes are read from then_bindings by ledger and traceability",
             " ".join((C.rollup_status.__doc__ or "").split()))


def an_unknown_run_word_is_not_executed() -> None:
    """HF3-7 (hotfix-12586/3, F-5 (b), FR-10, FR-41): a run result word outside the contract's vocabulary
    (`expected_product_failure` has no producer - the run-report validator refuses it - and a made-up word) reads "not executed,
    the run recorded <word>" in EVERY reader: the rollup, the ledger's test row, its plan row and the delivery summary's count
    agree. Kills: the word kept in `rollup_status`'s failed set (m4 -> C-K3), the unknown-word branch removed from
    `plan_row_state` (m1 -> `test_mixed_then_outcomes.py` C-K2, here C-K4), the branch put before `failed` (m2 -> C-K4), the
    final `test_state` return left on `NO_RUN_RESULT` (m3 -> `test_traceability.py` C-K1, here the test-row keys)."""
    word = "expected_product_failure"
    # the one classifier: derived from the contract, not a third literal (M3, AR-1)
    check_eq("vocabulary: derived from the contract's statuses, aliases and the words a rollup makes",
             C.RUN_WORDS_KNOWN >= set(C.RESULT_STATUS) | set(C.RESULT_ALIASES) | {"partial", "inconclusive", "blocked"}, True)
    check_eq("vocabulary: the words nobody writes are outside it",
             [L._unknown_run_word(w) for w in (word, "weird-word", " Weird  Word ", "ok", "green")], [True] * 5)
    check_eq("vocabulary: every word the contract knows is inside it, in any case (`not_run` and `pass` included)",
             [L._unknown_run_word(w) for w in (*C.RESULT_STATUS, *C.RESULT_ALIASES, "partial", "inconclusive", "blocked",
                                                 "PASSED", " Failed ")], [False] * (len(C.RESULT_STATUS) + len(C.RESULT_ALIASES) + 5))
    check_eq("vocabulary: no word recorded is no unknown word (empty, None, blanks)",
             [L._unknown_run_word(w) for w in ("", None, "   ")], [False] * 3)
    check_eq("vocabulary: a non-string cannot raise", [L._unknown_run_word(w) for w in (0, [], {})], [False, False, False])
    # C-1 (critic t-1276; AR-13, AR-28): the classifier normalizes as `contract.result_status` does (strip + lower + alias, NO
    # collapsing of inner blanks), so a word with inner whitespace is unknown to the rollup AND to the ledger - the two readers
    # of one question give one answer. Before: `"not  run"` was neither `not_run` nor unknown and the plan row read `passed_green`.
    check_eq("C-1: inner whitespace makes the word unknown for the ledger exactly where `result_status` leaves it unaliased",
             [(L._unknown_run_word(w), C.result_status({"status": w}) in C.RUN_WORDS_KNOWN) for w in ("not  run", "not\trun", "not run")],
             [(True, False), (True, False), (False, True)])

    # --- C-K3: rollup_status -------------------------------------------------------------------------------------------
    roll = C.rollup_status
    check_eq("C-K3: the word alone is returned as it stands, not `failed`", roll([word]), word)
    check_eq("C-K3: a red beside it is never hidden (failed first)", roll(["failed", word]), "failed")
    check_eq("C-K3: ... nor an error", roll([word, "error"]), "error")
    check_eq("C-K3 (B3): beside a pass it is NOT folded into `partial` - the word travels to the reader",
             (roll(["passed", word]), roll(["pass", "passed", "weird"])), (word, "weird"))
    # HF4-3 (t-1530 F-3 (a), P20: expectation from the finding): every unknown word, once, in first-seen order. Kills: `unknown[-1]`
    # back, `set` for `dict.fromkeys` (order) -> here.
    check_eq("C-K3' (HF4-3): two unknown words: both are named", roll(["weird", "odd"]), "weird, odd")
    check_eq("C-K3' (HF4-3): order is kept, not sorted or set-ordered", roll(["odd", "weird"]), "odd, weird")
    check_eq("C-K3' (HF4-3): a blank word is dropped before the join", roll(["weird", " "]), "weird")
    check_eq("C-K3' (HF4-3): all blank stays no result, never a pass", roll(["passed", " "]), "")
    check_eq("C-K3' (HF4-3): beside a pass too", roll(["passed", "weird", "odd"]), "weird, odd")
    check_eq("C-K3' (HF4-3): the same word twice is named once (also after normalization)",
             (roll(["weird", "weird"]), roll(["Weird", " weird "])), ("weird", "weird"))
    check_eq("C-K3' (HF4-3): first-seen order, a repeat does not move a word", roll(["weird", "odd", "weird"]), "weird, odd")
    check_eq("C-K3' (HF4-3): the joined value is still an unknown word, never a pass",
             (L._unknown_run_word(roll(["passed", "weird", "odd"])), L._unknown_run_word(roll(["weird"]))), (True, True))
    check_eq("C-K3' (HF4-3): rollup_words splits a joined value, drops blanks, and reads a non-string as no word",
             [C.rollup_words(w) for w in ("weird, odd", "weird", "", None, 7, " a ,  , b")],
             [["weird", "odd"], ["weird"], [], [], [], ["a", "b"]])
    check_eq("C-K3: the word is read as `result_status` reads it (case, blanks)", roll(["passed", " Weird-Word "]), "weird-word")
    check_eq("C-K3: a known non-pass beside a pass is still `partial`",
             (roll(["passed", "skipped"]), roll(["passed", "inconclusive"]), roll(["passed", "not_run"])), ("partial",) * 3)
    check_eq("C-K3: an unknown word beside a known non-pass is `partial` as before (nothing half-green)",
             (roll(["skipped", "weird"]), roll(["partial", "weird"])), ("partial", "partial"))
    check_eq("C-K3: empty and blank statuses stay empty", (roll([]), roll(["", None])), ("", ""))

    # --- C-K4: where the branch sits in plan_row_state ---------------------------------------------------------------------
    def row_state(words: dict, cases: list | None = None) -> tuple:
        """`plan_row_state` of ONE plan row holding the cases of `words` ({case: [status of each of its instances]})."""
        tests, results = [], []
        for case, statuses in words.items():
            for n, status in enumerate(statuses):
                iid = f"t_{case[-1]}_{n}"
                tests.append({"instance_id": iid, "file": "tests/x.py", "case": case, "covers": [case], "status": "green"})
                results.append({"instance_id": iid, "case": case, "status": status})
        manifest, report = {"tests": tests}, {"current_results": results}
        return L.plan_row_state({"ts": "TS-1", "disposition": "automate"}, manifest, report, {}, {"TS-1": cases or list(words)})

    check_eq("C-K4: a failed case beside an unknown one is `failed:*` (the red is said first)",
             row_state({"TC-001": ["failed"], "TC-002": ["weird"]})[0], "failed:untriaged")
    check_eq("C-K4: a `partial` case beside an unknown one is `partial`", row_state({"TC-001": ["partial"], "TC-002": ["weird"]})[0], "partial")
    check_eq("C-K4: an `error` case beside an unknown one is `error`", row_state({"TC-001": ["error"], "TC-002": ["weird"]})[0], "error")
    got = row_state({"TC-001": ["weird"]})
    check_eq("C-K4: only the unknown word -> not executed, the run recorded it", got, ("not_executed:the run recorded weird for this row's cases", "TC-001"))
    check_eq("C-K4: an unknown case beside a passed one is `not_executed:`, never `passed_green`",
             row_state({"TC-001": ["weird"], "TC-002": ["passed"]}),
             ("not_executed:the run recorded weird for this row's cases", "TC-001"))
    check_eq("C-K4 (B3): ONE case with a pass and the unknown word on two instances reads the word too (not `partial`)",
             row_state({"TC-001": ["passed", word]})[0], f"not_executed:the run recorded {word} for this row's cases")
    check_eq("C-K4: ... and a failed instance of the same case is still `failed:*`",
             row_state({"TC-001": ["passed", word, "failed"]})[0], "failed:untriaged")
    check_eq("C-K4: two different unknown words are both named, once each, the cases beside them",
             row_state({"TC-001": ["weird"], "TC-002": ["odd"], "TC-003": ["weird"]}),
             ("not_executed:the run recorded weird, odd for this row's cases", "TC-001, TC-002, TC-003"))
    # HF4-3 C-K4': de-dup by WORD, not by the whole rolled-up string. Kills: de-dup by whole string (`weird, odd, odd`), classification
    # by the parts of `rollup_words` (`passed, failed` would read passed/failed).
    check_eq("C-K4' (HF4-3): a joined value and a single word of it are named once each",
             row_state({"TC-001": ["passed", "weird", "odd"], "TC-002": ["odd"]}),
             ("not_executed:the run recorded weird, odd for this row's cases", "TC-001, TC-002"))
    check_eq("C-K4' (HF4-3): one unknown word holding the join string beside a pass is not executed, never passed_green / failed",
             row_state({"TC-001": ["passed", "passed, failed"]})[0].startswith("not_executed:"), True)
    check_eq("C-K4: a backtick or a line break in the word cannot reach the state",
             row_state({"TC-001": ["a`b\nc"]})[0], "not_executed:the run recorded a'b c for this row's cases")
    for spelled in ("not  run", "not\trun"):
        check_eq(f"C-1: a run word with inner whitespace ({spelled!r}) is never `passed_green` - it is the unknown word, beside a pass too",
                 (row_state({"TC-001": [spelled]}), row_state({"TC-001": ["passed", spelled]})[0]),
                 (("not_executed:the run recorded not run for this row's cases", "TC-001"),
                  "not_executed:the run recorded not run for this row's cases"))
    check_eq("C-1 control: the plain alias `not run` is still the known `not_run` (skipped, not the unknown branch)",
             row_state({"TC-001": ["not run"]})[0].split(":")[0], "skipped")
    check_eq("C-K4 control: no unknown word -> `passed_green` as before", row_state({"TC-001": ["passed"], "TC-002": ["pass"]})[0], "passed_green")
    check_eq("C-K4 control: a known non-pass word keeps its own state (`skipped`, not the new branch)",
             row_state({"TC-001": ["skipped"]})[0].split(":")[0], "skipped")
    check("C-K4: the state is the ledger's vocabulary", C.is_ledger_state(row_state({"TC-001": [word]})[0]), row_state({"TC-001": [word]})[0])

    # --- the test row: the same word, and the same position (M3) ----------------------------------------------------------
    entry = {"instance_id": "i1", "case": "TC-001", "file": "tests/x.py", "critic_verdict": "approved", "status": "green"}
    manifest = {"tests": [entry]}

    def test_row(status, **report_over) -> str:
        report = dict({"current_results": [{"instance_id": "i1", "case": "TC-001", "status": status}]}, **report_over)
        return L.test_state(entry, report, {"triage": []}, None, manifest)[0]

    check_eq("test row: the run recorded a word outside the vocabulary -> that is what it says, not `no result`",
             test_row(word), f"not_executed:the run recorded {word} for this test")
    check_eq("test row: ... a made-up word the same", test_row("weird-word"), "not_executed:the run recorded weird-word for this test")
    check_eq("test row (C-1): a word with inner whitespace is the unknown word, not `no result` and not green",
             (test_row("not  run"), test_row("not\trun")), ("not_executed:the run recorded not run for this test",) * 2)
    check_eq("test row: a word of the vocabulary that is no result (`not_run`) keeps the ledger's own sentence",
             test_row("not_run"), "not_executed:" + L.NO_RUN_RESULT)
    check_eq("test row: no row for the test is still `no result`", L.test_state(entry, {"current_results": []}, {"triage": []}, None, manifest)[0],
             "not_executed:" + L.NO_RUN_RESULT)
    check_eq("test row (M3): an env_blocked run keeps the block's owner whatever word the row holds",
             test_row(word, execution_status="env_blocked").split(":")[0], "env_blocked")
    check_eq("test row: a failed row is still `failed:untriaged`, a passed one `passed_green`",
             (test_row("failed"), test_row("passed")), ("failed:untriaged", "passed_green"))
    check_eq("test row: the word is not a backtick in the state (check_delivery reads \"is `<state>`\")",
             test_row("a`b"), "not_executed:the run recorded a'b for this test")
    check("test row: the state is the ledger's vocabulary", C.is_ledger_state(test_row(word)), test_row(word))

    # --- a ledger written by 0.10.2 is read by this code: the verdict stays `no` (pure functions over manifest and report) ---
    old = L.plan_row_state({"ts": "TS-1", "disposition": "automate"}, {"tests": [entry]},
                           {"current_results": [{"instance_id": "i1", "case": "TC-001", "status": word}]}, {}, {"TS-1": ["TC-001"]})
    check_eq("0.10.2 ledger: the story a stored `failed:untriaged` came from now reads not executed (the verdict `no` stays `no`)",
             old[0].split(":")[0], "not_executed")

    # --- C-K5: the delivery summary does not count the word as executed -----------------------------------------------------
    import delivery_summary as S
    check_eq("C-K5: the terminal words of the summary hold no word nobody writes",
             sorted(S.TERMINAL_EXECUTION), sorted(["passed", "failed", "pass", "fail", "partial"]))
    root = temp_project("qa-ledger-unknown-word-")
    try:
        (root / TEST_REL).write_text(TEST_SRC, encoding="utf-8")
        use_project(root)
        task = install_artifacts(root, GOOD, "T-1")
        report_path = task / "work" / "run-report.json"
        base = C.load_json(report_path)

        def executed(status: str) -> int:
            report = json.loads(json.dumps(base))
            report["current_results"] = [{"instance_id": "i1", "case": "TC-001", "status": status}]
            report["manual_checks"], report["current_manual_checks"] = [], []
            report_path.write_text(json.dumps(report), encoding="utf-8")
            return S.build(task, L.build(task))["counts"]["executed"]

        check_eq("C-K5: a passed row is an executed test (control)", executed("passed"), 1)
        check_eq("C-K5: a row with the unknown word is NOT an executed test", executed(word), 0)
    finally:
        cleanup(root)


def the_untyped_reason_is_recorded_and_worded() -> None:
    """FU2 (t-1936): `untyped` (the verdict sent the window back with no finding the test writer can act on) is a reason of the
    ledger's closed list: written, read back, worded without a count (the counted reasons stay `cap` and `mech_cap`), and a debt
    file written before the word (reasons `sent_back` / `nobody`) still loads."""
    root = temp_project("qa-ledger-untyped-")
    try:
        art = install_artifacts(root, GOOD, "QA-1")
        check_in("untyped is in the closed list", "untyped", L.DEBT_REASONS)
        L.write_review_debt(art, window(reason="untyped", rounds={"counted": None, "cap": None, "by_cause": {}}))
        entry = L.read_review_debts(art)["windows"][0]
        check_eq("an untyped window is written and read back, nothing missing (it needs no counts)", (entry["reason"], L.debt_missing(entry)), ("untyped", []))
        check_eq("limit_words: the critic wrote no finding the test writer can act on",
                 L.limit_words("untyped", None, None), "the critic sent the tests back without writing a finding the test writer can act on")
        check_not_in("...and no cause token or count in it", "test_defect", L.limit_words("untyped", 2, 2))
        L.write_review_debt(art, window(reason="sent_back", critic_dispatch="d-2"))
        L.write_review_debt(art, window(reason="nobody", critic_dispatch="d-3"))
        check_eq("an old record without the word still loads beside it", [w["reason"] for w in L.read_review_debts(art)["windows"]],
                 ["untyped", "sent_back", "nobody"])
    finally:
        cleanup(root)


def test_ledger_lists_unprepared_walks() -> None:
    """F5(e) 3 (t-1936 N5): a run report row carrying the `unprepared` marker is listed in the ledger's `unprepared_walks`
    (the one list `check_delivery.unprepared_records` reads); a report without such a row, or no report, lists none."""
    root = temp_project("qa-ledger-unprepared-")
    try:
        art = rejected_story(root)
        check_eq("no unprepared row: the list is empty (the key is present)", L.build(art).get("unprepared_walks"), [])
        report = C.load_json(art / "work" / "run-report.json")
        report["current_manual_checks"] = [
            {"case": "TC-007", "current_obligation_ids": ["OB-7"], "observations": ["the field took 12"], "finding": "",
             "unprepared": {"reason": "the plan gives TC-007's check an evidence rule that is not one word"}},
            {"case": "TC-008", "current_obligation_ids": ["OB-8"], "result": "pass"}]
        (art / "work" / "run-report.json").write_text(json.dumps(report), encoding="utf-8")
        walks = L.build(art)["unprepared_walks"]
        check_eq("the unprepared row is listed with its case, obligations and reason; the ordinary row is not",
                 [(w["case"], w["obligation_ids"], w["reason"], w["observations"]) for w in walks],
                 [("TC-007", ["OB-7"], "the plan gives TC-007's check an evidence rule that is not one word", ["the field took 12"])])
    finally:
        cleanup(root)


def triage_refs_names_what_the_ledger_matches():
    """`ledger.triage_refs` (t-698 §18.4, F-18.4 (a)): the refs of the manifest tests a triage row answers are the ones `_covers` matches an S7
    debt window by - NOT the row's own `test` (a contract-shape row and a parametrized one spell the test differently than the ledger's ref)."""
    task = temp_project("qa-triage-refs-")
    try:
        work = task / "work"
        work.mkdir(parents=True, exist_ok=True)
        entry = {"file": "tests/test_coupon.py", "test_function": "test_limit", "case": "TC-1"}
        param = dict(entry, parameters={"browser": "chromium"})
        # The second row carries the identity the reducer gives every current row (HF2-6: a manifest test joins the run's row by
        # its own id; the old read-by-case fallback that let this row find the test without one is gone, a neighbour's row
        # of the case is never this test's).
        report_rows = [{"test_id": "tests/test_coupon.py::test_limit", "case": "TC-1", "status": "failed", "reason": "boom"},
                       {"test_id": "tests/test_coupon.py::test_limit[chromium]", "instance_id": "test_limit[browser=chromium]",
                        "case": "TC-1", "status": "failed", "reason": "boom"}]
        (work / "automation-manifest.json").write_text(json.dumps({"tests": [entry]}), encoding="utf-8")
        (work / "run-report.json").write_text(json.dumps({"current_results": report_rows[:1]}), encoding="utf-8")
        row = {"test": "tests/test_coupon.py::test_limit", "verdict": "TEST_BUG", "evidence": "e"}
        (work / "triage.json").write_text(json.dumps({"triage": [row]}), encoding="utf-8")
        check_eq("triage_refs: a contract-shape row answers the ledger's ref `test_limit`, not the row's own nodeid", L.triage_refs(task, row), ["test_limit"])
        (work / "automation-manifest.json").write_text(json.dumps({"tests": [param]}), encoding="utf-8")
        (work / "run-report.json").write_text(json.dumps({"current_results": report_rows[1:]}), encoding="utf-8")
        prow = dict(row, test="tests/test_coupon.py::test_limit[chromium]")
        (work / "triage.json").write_text(json.dumps({"triage": [prow]}), encoding="utf-8")
        check_eq("triage_refs: a parametrized test is named by the ledger's own spelling", L.triage_refs(task, prow), ["test_limit[browser=chromium]"])
        check_eq("triage_refs: a row no test answers has no ref (the caller says `unbound`)", L.triage_refs(task, {"test": "nowhere::t", "verdict": "TEST_BUG"}), [])
        (work / "automation-manifest.json").unlink()
        check_eq("triage_refs: no manifest, no ref - never a raise", L.triage_refs(task, prow), [])
    finally:
        cleanup(task)


def two_areas_are_two_cases_in_the_ledger():
    """D2-B3 (E-B3, AR-13, AR-28): `web/TC-4` and `api/TC-4` are two cases. The red of one is never read as the result of the
    other (the producer `run_results` adds a bare alias only when ONE area carries the id), and the two exact lookups the
    D2-B2 pass left (`handed_over`, `_whole_case_unconfirmed`) read by identity, never across areas."""
    def state(cases, report, manifest=None, disposition="automate"):
        return L.plan_row_state({"ts": "TS-1", "disposition": disposition, "reason": ""}, manifest or {}, report, {}, {"TS-1": cases})

    def red(*cases):
        return {"current_results": [{"case": c, "status": "failed", "instance_id": f"i{n}", "test_id": f"t{n}"} for n, c in enumerate(cases)]}

    # two areas carry the id, so no bare alias: the reds of `api` and `db` are not the result of `web`
    check("E-B3 ledger: the reds of `api/TC-4` and `db/TC-4` are not the result of `web/TC-4`",
          not state(["web/TC-4"], red("api/TC-4", "db/TC-4"))[0].startswith("failed:"), str(state(["web/TC-4"], red("api/TC-4", "db/TC-4"))))
    check("E-B3 ledger control: the same two reds are the result of the bare plan case (red wins)",
          state(["TC-4"], red("api/TC-4", "db/TC-4"))[0].startswith("failed:"), str(state(["TC-4"], red("api/TC-4", "db/TC-4"))))
    check("E-B3 ledger control: the red of `web/TC-4` is the result of `web/TC-4`",
          state(["web/TC-4"], red("web/TC-4"))[0].startswith("failed:"), str(state(["web/TC-4"], red("web/TC-4"))))
    check("E-B3 ledger control: one area, the bare plan case still reads its red",
          state(["TC-4"], red("api/TC-4"))[0].startswith("failed:"), str(state(["TC-4"], red("api/TC-4"))))
    # `case in handed_over` (the hand-off branch): by identity
    human = {"manual_human": [{"case": "TC-9", "evidence": "pack.md"}]}
    check_eq("handed_over: a package under `TC-9`, plan case `web/TC-9` -> handed", state(["web/TC-9"], human, disposition="manual-human")[0],
             L.HANDED_STATE)
    check("handed_over (E-B3): the package of `api/TC-9` is not the package of `web/TC-9`",
          state(["web/TC-9"], {"manual_human": [{"case": "api/TC-9", "evidence": "pack.md"}]}, disposition="manual-human")[0] != L.HANDED_STATE)
    # `_whole_case_unconfirmed`: by identity
    unc = lambda case: {"unresolved": [{"case": case, "reason": L.EXPECTATION_UNCONFIRMED, "question": "Q1"}]}
    check_eq("whole unconfirmed: row `TC-6`, plan case `web/TC-6` -> the sentence is kept",
             len(L._whole_case_unconfirmed(unc("TC-6"), ["web/TC-6"])), 1)
    check_eq("whole unconfirmed (E-B3): row `api/TC-6`, plan case `web/TC-6` -> none",
             L._whole_case_unconfirmed(unc("api/TC-6"), ["web/TC-6"]), [])
    check_eq("whole unconfirmed (E-B1): a blank row case names nothing", L._whole_case_unconfirmed(unc(""), ["web/TC-6"]), [])


if __name__ == "__main__":
    main()
