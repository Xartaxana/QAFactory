#!/usr/bin/env python3
"""What the factory cannot execute at all goes to the person — by their choice, not silently.

TP2-2536 is the story that earned this. Eight Maestro/iOS cases, and the session the
factory ran in had no Xcode, no Simulator and no `maestro` binary: not a stand that was down
and not a `manual-human` row, but a runner that does not exist here. The gate rehearsal said
nothing, S5 wrote the tests, no window could be completed without a run, S6-S9 never ran, and
the person executed everything by hand twice while the factory waited for a receipt.

These tests assert the whole path of the owner's decision of 22.09.2026:
  - the rehearsal asks ONE question per profile before gate A, with three answers, and asks
    nothing when the launcher resolves;
  - only the third answer hands anything over, and it is recorded where every block a
    person's word passes is recorded (`stage_overrides[]`);
  - S5 still writes and reviews the code; the window closes by code with
    `unresolved: handed_to_person`, with no receipt and no waiting;
  - S6 never sees those cases, the ledger never says PASS for them, and gate B says
    `delivery_ready: after_checks` (t-305 N8, owner 03.10 - it was `no` under the rule of 0.7.9: the person decided to run
    them, so nothing is owed back) with the exact list of what the person runs.
"""
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import (SCRIPTS, check, check_eq, check_in, check_not_in, cleanup,  # noqa: E402
                     finish, temp_dir, use_project)

sys.path.insert(0, str(SCRIPTS))

import acceptance  # noqa: E402
import check_delivery  # noqa: E402
import contract as C  # noqa: E402
import gate_brief  # noqa: E402
import gate_preflight  # noqa: E402
import run_suite  # noqa: E402
import s5_precheck  # noqa: E402
from controller import names_handed  # noqa: E402

MISSING_TOOL = "maestro-not-installed-in-this-session"
PROFILE = "tests-e2e-ios"


def plan_row(row_id: str, level: str = "e2e-ui") -> dict:
    return {"id": row_id, "requirement_ids": ["R-1"], "level": level, "disposition": "automate",
            "impact": "moderate", "likelihood": "medium", "design_review_required": False,
            "confidence": "medium", "risk_rationale": "registration validation",
            "risk_source_refs": ["strategy/test-strategy.md@2026-09-22"],
            "risk_policy_revision": "factory-starter-v1", "coverage_refs": [], "unknowns": [],
            "verification_depth": "normal", "defect_hypothesis": "form accepts an empty email",
            "required_scenarios": ["an empty email"],
            "test_level_rationale": "the form only exists in the app"}


def config(argv) -> dict:
    """The 2536 shape: one profile, one command, and the tools its script names."""
    return {"schema_version": 1, "tests_root": ".", "app_root": ".",
            "profiles": [{"profile_id": PROFILE, "capabilities": ["e2e-ui"],
                          "roots": {"repo": ".", "test": "tests-e2e-ios"},
                          "commands": {"run": {"argv": argv, "cwd": "."}},
                          "execution_prerequisites": {"hook_executables": []}}]}


def story(prefix: str, argv, overrides=()) -> Path:
    root = temp_dir(prefix)
    task_root = root / "qa-factory" / "artifacts" / "TP2-2536"
    (task_root / "work" / "test-cases" / "registration").mkdir(parents=True)
    (task_root / "state").mkdir(parents=True)
    (root / "qa-factory" / "config.json").write_text(json.dumps(config(argv)), encoding="utf-8")
    (root / "qa-factory" / "readiness.json").write_text(json.dumps(
        {"capabilities": {"environment": {"status": "ok"}, "test_repo": {"status": "ok"}}}),
        encoding="utf-8")
    (task_root / "work" / "test-plan.json").write_text(
        json.dumps([plan_row("TS-1")]), encoding="utf-8")
    for name in ("source-inventory.json", "context-manifest.json", "context-bundle.json"):
        (task_root / "work" / name).write_text("{}", encoding="utf-8")
    (task_root / "pipeline.json").write_text(json.dumps(
        {"ticket": "TP2-2536",
         "stages": {"S3": {"status": "done"}, "S4": {"status": "done"}},
         "stage_overrides": list(overrides)}), encoding="utf-8")
    for case in ("TC-001", "TC-002"):
        (task_root / "work" / "test-cases" / "registration" / f"{case}.md").write_text(
            f"---\nid: {case}\narea: registration\n---\n\nPlan row: TS-1\n\n"
            "## Then\n1. rejected.\n", encoding="utf-8")
    return root


def executor_findings(root: Path) -> list:
    task_root = root / "qa-factory" / "artifacts" / "TP2-2536"
    result = gate_preflight.run(task_root, "A")
    return [f for f in result["findings"] if f["check"] == "s5_executor"]


# --- gate A: one question, three answers ------------------------------------------------------

def the_rehearsal_asks_before_the_gate_and_only_once_per_profile():
    root = story("qa-handed-ask-", [MISSING_TOOL])
    try:
        use_project(root)
        found = executor_findings(root)
        check_eq("a profile whose launcher does not exist here is one question", len(found), 1)
        check_eq("and it is the person's call, never a defect of theirs to repair",
                 found[0]["class"], gate_preflight.PERSON_DECIDES)
        check_in("the missing tool is named exactly", MISSING_TOOL, found[0]["message"])
        check_in("with the profile whose tests run through it", PROFILE, found[0]["message"])
        check_in("and how many cases it is about", "2 cases", found[0]["message"])
        check_in("the cases themselves are named", "TC-001", found[0]["message"])
        check_in("option (a) is to install it here", "install it here", found[0]["fix"])
        check_in("option (b) is another environment", "name an environment", found[0]["fix"])
        check_in("option (c) is the person running them", "you run these 2 case(s) yourself",
                 found[0]["fix"])
        check_in("and (c) promises no waiting", "never wait for your results", found[0]["fix"])
        check_eq("the three answers are machine-readable too",
                 [row["action"] for row in found[0]["options"]],
                 ["install_here", "other_environment", "handed_to_person"])
        check_eq("the finding says which profile and tool it is about",
                 (found[0]["profile"], found[0]["tool"]), (PROFILE, MISSING_TOOL))
        check_in("and what it keyed the cases on", "capabilities", found[0]["keyed_on"])
    finally:
        cleanup(root)


def nothing_is_asked_when_the_launcher_resolves():
    root = story("qa-handed-quiet-", [sys.executable, "-c", "pass"])
    try:
        use_project(root)
        check_eq("a profile the factory can launch raises no question at all",
                 executor_findings(root), [])
    finally:
        cleanup(root)


def the_persons_word_is_read_where_every_other_word_is_read():
    overrides = [{"stage": "S5", "match": f"executor unavailable: {PROFILE}",
                  "decision": "I'll run the iOS flows on my laptop", "at": "2026-09-22T10:00:00+00:00"}]
    root = story("qa-handed-answered-", [MISSING_TOOL], overrides)
    try:
        use_project(root)
        pipeline = json.loads((root / "qa-factory" / "artifacts" / "TP2-2536"
                               / "pipeline.json").read_text(encoding="utf-8"))
        handed = C.handed_profiles(pipeline)
        check_eq("the decision is read out of stage_overrides[], not a store of its own",
                 sorted(handed), [PROFILE])
        check_in("with the person's own words", "on my laptop", handed[PROFILE]["words"])
        check_eq("and the question is not asked a second time", executor_findings(root), [])
        check_eq("a stage override about something else hands nothing over",
                 C.handed_profiles({"stage_overrides": [
                     {"stage": "S5", "match": "story budget", "decision": "go on"}]}), {})
        check_eq("and neither does an override nobody actually decided",
                 C.handed_profiles({"stage_overrides": [
                     {"stage": "S5", "match": f"executor unavailable: {PROFILE}", "decision": ""}]}), {})
    finally:
        cleanup(root)


# --- S5: the code is written and reviewed, and the window closes without a run ----------------

def window(outcome="handed_to_person", probe=None) -> dict:
    instance = {"instance_id": "registration_empty_email", "input_hash": "H1",
                "outcome": outcome, "review": {"verdict": "approved", "input_hash": "H1"},
                "change_disposition": "new_or_changed", "change_basis_ref": "diff",
                "evidence_refs": []}
    if probe is not None:
        instance["probe"] = probe
    # EP1-4 (t-626 FR-4/AR-28): a hand-off claim counts as far as the manifest confirms it, through `scope_instances`
    return {"required_quality_checks": [], "instances": [instance],
            "scope_instances": {"TC-001": ["registration_empty_email"]}}


def a_handed_instance_is_never_a_product_gap():
    root = temp_dir("qa-handed-window-")
    try:
        (root / "work").mkdir(parents=True)
        (root / "work" / "automation-manifest.json").write_text(json.dumps({
            "tests": [{"case": "TC-001", "instance_id": "registration_empty_email", "covers": ["TC-001"]}],
            "unresolved": [{"case": "TC-001", "reason": "handed_to_person",
                            "detail": f"{PROFILE}: cd tests-e2e-ios && ./scripts/run-local.sh"}]}), encoding="utf-8")
        proof = root / "proof.txt"
        proof.write_text("the test code as the critic reviewed it", encoding="utf-8")
        record = window()
        record["instances"][0]["evidence_refs"] = [
            {"path": "proof.txt", "sha256": hashlib.sha256(proof.read_bytes()).hexdigest()}]
        gaps = acceptance.validate_window(record, root)
        check_eq("the one gap says exactly what happened: it was handed over",
                 gaps, ["handed_to_person:registration_empty_email"])
        check_not_in("never as an unproven product behaviour", "product:", gaps)
        check_not_in("and never as a missing red probe", "sensitivity:", gaps)

        failed = window(outcome="failed")
        failed["instances"][0]["evidence_refs"] = record["instances"][0]["evidence_refs"]
        check_in("a test that actually ran and failed is still a product gap",
                 "product:registration_empty_email", acceptance.validate_window(failed, root))
        unreviewed = window()
        unreviewed["instances"][0]["evidence_refs"] = record["instances"][0]["evidence_refs"]
        unreviewed["instances"][0]["review"] = {"verdict": "rejected", "input_hash": "H1"}
        check_in("handing a test over does not excuse it from review",
                 "review:registration_empty_email", acceptance.validate_window(unreviewed, root))
    finally:
        cleanup(root)


def the_completion_has_to_say_the_handover_out_loud():
    check("a completion naming the reason passes",
          names_handed({"unresolved": True, "reason": "handed_to_person: tests-e2e-ios"}))
    check("so does one that names it in a structured unresolved list",
          names_handed({"unresolved": [{"case": "TC-001", "reason": "handed_to_person"}]}))
    check_eq("a silent completion does not", names_handed({"unresolved": True, "reason": "gaps"}),
             False)
    check_eq("and neither does an empty one", names_handed({}), False)


def s5_precheck_demands_no_run_of_a_test_nothing_could_launch():
    root = temp_dir("qa-handed-precheck-")
    try:
        (root / "work").mkdir(parents=True)
        manifest = {"tests": [{"case": "TC-001", "instance_id": "test_empty_email",
                               "file": "tests-e2e-ios/flows/registration.yaml",
                               "status": "written", "covers": ["TC-001"]}],
                    "unresolved": [{"case": "TC-001", "reason": "handed_to_person",
                                    "detail": f"{PROFILE}: cd tests-e2e-ios && ./scripts/run-local.sh"}]}
        (root / "work" / "automation-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        result = s5_precheck.run(root)
        tags = [f["id"] for f in result["findings"]]
        check_not_in("a case in tests[] and unresolved[] at once is the sanctioned shape here",
                     "both-lists", tags)
        check_not_in("and no reporter row is owed for a run that never happened",
                     "no-row-test_empty_email", tags)

        manifest["tests"][0]["status"] = "green"
        (root / "work" / "automation-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        check_in("but `green` with nothing behind it is still a finding",
                 "handed-but-green", [f["id"] for f in s5_precheck.run(root)["findings"]])
    finally:
        cleanup(root)


# --- late discovery: the same question, never a silent handover -------------------------------

def a_tool_that_disappears_mid_s5_stops_the_run_and_asks_again():
    gap = run_suite.executor_gap(
        {"profile_id": PROFILE, "built_by": {"cases": ["TC-001", "TC-002"]},
         "command": {"argv": [MISSING_TOOL, "test"], "cwd": "."}}, {})
    check_eq("the missing launcher is named, not the whole command",
             (gap or {}).get("tool"), MISSING_TOOL)
    check_eq("with the profile and the cases the run was about",
             ((gap or {}).get("profile"), (gap or {}).get("cases")),
             (PROFILE, ["TC-001", "TC-002"]))
    check_eq("a launcher that resolves is never refused",
             run_suite.executor_gap({"profile_id": PROFILE,
                                     "command": {"argv": [sys.executable], "cwd": "."}}, {}), None)
    try:
        run_suite.refuse_missing_executor(PROFILE, MISSING_TOOL, ["TC-001"], "S5")
        code = 0
    except SystemExit as exc:
        code = exc.code
    check_eq("a run it cannot launch exits 3, launching nothing", code, 3)


# --- S6-S8: never PASS, never waited for ------------------------------------------------------

def handed_story(prefix: str) -> Path:
    """An S8-shaped story whose two cases were handed to the person."""
    root = temp_dir(prefix)
    (root / "work").mkdir(parents=True)
    (root / "work" / "automation-manifest.json").write_text(json.dumps({
        "run_witness": "",
        "tests": [{"case": "TC-001", "instance_id": "test_empty_email", "status": "written",
                   "file": "tests-e2e-ios/flows/registration.yaml", "covers": ["TC-001"],
                   "critic_verdict": "approved", "change_disposition": "new_or_changed"}],
        "unresolved": [{"case": "TC-001", "reason": "handed_to_person",
                        "detail": f"{PROFILE}: cd tests-e2e-ios && ./scripts/run-local.sh "
                                  "(tests-e2e-ios/flows/registration.yaml)"}]}), encoding="utf-8")
    return root


def the_ledger_says_handed_and_never_pass():
    root = handed_story("qa-handed-ledger-")
    try:
        doc = check_delivery.mark_handed(
            {"rows": [{"ref": "TS-1", "kind": "plan_row", "state": "not_executed:no result",
                       "detail": "TC-001"},
                      {"ref": "test_empty_email", "kind": "test",
                       "state": "not_executed:no result for this test in run-report.json",
                       "detail": "registration.yaml"}]}, root)
        states = {row["ref"]: row["state"] for row in doc["rows"]}
        check_eq("the plan row says it was handed over, not that a run failed",
                 states["TS-1"], check_delivery.HANDED_LEDGER_STATE)
        check_eq("and so does the test row", states["test_empty_email"],
                 check_delivery.HANDED_LEDGER_STATE)
        check_not_in("no handed row is ever PASS", "passed_green", list(states.values()))
        check_in("the row carries what the person runs", "run-local.sh",
                 [row["detail"] for row in doc["rows"]])

        reasons = check_delivery.handed_reasons(root)
        check_eq("the person is told once, not once per row", len(reasons), 1)
        check_in("with the count", "1 test(s)", reasons[0])
        check_in("and the exact command", "./scripts/run-local.sh", reasons[0])
        record = check_delivery.reason_record(reasons[0])
        check_eq("it is the environment's, not the product's and not a defect of ours",
                 (record["code"], record["owner"]), ("HANDED_TO_PERSON", "environment"))
        check_eq("the ledger does not repeat it in its own shorthand",
                 check_delivery.ledger_reasons(doc), [])
    finally:
        cleanup(root)


def the_report_fragment_carries_the_list_too():
    """t-305 N8 (F9, FR-10): the fragment quotes the report's own "Left with you" section - it builds no list of its own, so
    the MR description and the report cannot name different items. The handed list reaches it through that section."""
    import delivery_summary
    section = ("## Left with you\n\n1. **The registration form (R-1, TC-001).** To check: an empty email is refused. "
               f"How: `{PROFILE}: ./scripts/run-local.sh`.\n")
    summary = {
        'counts': {'planned': 1, 'executed': 0, 'planned_manual': None, 'executed_manual': 0,
                   'verified': 0, 'failed': 0, 'unverified': 1, 'env_blocked': 0, 'deferred': 0},
        'gaps': [], 'bugs': [], 'reasons_by_owner': {}, 'left_with_you': section,
        'handed_to_person': [{'case': 'TC-001', 'detail': f'{PROFILE}: ./scripts/run-local.sh',
                              'what': './scripts/run-local.sh'}]}
    text = delivery_summary.render(summary)
    check_in("the generated fragment quotes the report's section whole", section.rstrip("\n"), text)
    check_in("with the case and the command the scribe wrote there", "tests-e2e-ios: ./scripts/run-local.sh", text)
    check_not_in("and builds no list of its own", "Run these yourself", text)
    check_in("a summary with no report section says so in one line, never silently",
             "Left with you: the report has none yet", delivery_summary.render(dict(summary, left_with_you=None)))


def gate_b_shows_the_list_under_its_own_heading():
    root = handed_story("qa-handed-gate-b-")
    try:
        rows = gate_brief.handed_runs(root)
        check_eq("the list comes from the manifest, never from prose", len(rows), 1)
        check_eq("with the profile split out of the detail", rows[0]["profile"], PROFILE)
        check_in("and the command kept whole", "run-local.sh", rows[0]["what"])
        check_eq("a handed case is not repeated as a loose end in the debts list",
                 [line for line in gate_brief.open_debts(root) if "TC-001" in line], [])
    finally:
        cleanup(root)


def a_manifest_of_only_handed_tests_owes_no_run_witness():
    root = handed_story("qa-handed-witness-")
    try:
        import check_witness
        manifest = json.loads((root / "work" / "automation-manifest.json").read_text(encoding="utf-8"))
        check_eq("nothing ran, so nothing is owed as a run summary",
                 check_witness.RULES["automation-manifest.json"](manifest), [])
        manifest["tests"].append({"case": "TC-002", "instance_id": "test_other", "status": "green",
                                  "file": "tests-integration/tests/registration.spec.ts",
                                  "covers": ["TC-002"]})
        errors = check_witness.RULES["automation-manifest.json"](manifest)
        check_in("one test that DID run brings the witness back",
                 "run_witness missing", errors)
    finally:
        cleanup(root)


# --- backward compatibility -------------------------------------------------------------------

def a_story_without_a_handover_is_untouched():
    root = temp_dir("qa-handed-none-")
    try:
        (root / "work").mkdir(parents=True)
        (root / "work" / "automation-manifest.json").write_text(json.dumps(
            {"tests": [], "unresolved": [{"case": "TC-001", "reason": "blocked_by_env"}]}),
            encoding="utf-8")
        check_eq("an env block is not a handover", check_delivery.handed_rows(root), [])
        check_eq("and it produces no handover reason", check_delivery.handed_reasons(root), [])
        check_eq("`handed_to_person` joined the closed vocabulary without displacing anything",
                 C.UNRESOLVED_REASONS[:4],
                 ("impossible", "blocked_by_env", "pending_implementation", "contradicts_requirement"))
        check("and it is a valid unresolved reason", C.unresolved_reason_ok("handed_to_person"))
    finally:
        cleanup(root)


def main() -> None:
    the_rehearsal_asks_before_the_gate_and_only_once_per_profile()
    nothing_is_asked_when_the_launcher_resolves()
    the_persons_word_is_read_where_every_other_word_is_read()
    a_handed_instance_is_never_a_product_gap()
    the_completion_has_to_say_the_handover_out_loud()
    s5_precheck_demands_no_run_of_a_test_nothing_could_launch()
    a_tool_that_disappears_mid_s5_stops_the_run_and_asks_again()
    the_ledger_says_handed_and_never_pass()
    the_report_fragment_carries_the_list_too()
    gate_b_shows_the_list_under_its_own_heading()
    a_manifest_of_only_handed_tests_owes_no_run_witness()
    a_story_without_a_handover_is_untouched()
    finish("test_handed_to_person")


if __name__ == "__main__":
    main()
