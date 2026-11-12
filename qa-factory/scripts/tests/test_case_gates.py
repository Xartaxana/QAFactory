#!/usr/bin/env python3
"""S3/S4 gates: the plan contract, the critic roll-call, pinning and the closed vocabularies.

Every case here is a defect the TP1-15045 run actually produced:
  - the plan contract was checked after S4 instead of at the S3 exit;
  - an approving verdict beside seven rows nobody read semantically;
  - a one-line replacement dropped "because no repair round was left";
  - the designer blocked for not running a script it cannot run;
  - an absolute Windows path inside a delivered artifact;
  - a defect class outside the closed vocabulary, noticed three dispatches late.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import SCRIPTS, check, check_in, cleanup, finish, run_script, temp_project  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import case_versions as V  # noqa: E402
import critic_rollcall as R  # noqa: E402
import planning_contract as P  # noqa: E402


def plan_row(rid="TS-1", **extra):
    """A row that passes `validate_plan` — the shape the write-time hook already enforces, so
    the exit gate only has to add what gate-inputs adds on top of it."""
    row = {"id": rid, "schema_version": 1, "impact": "moderate", "likelihood": "medium",
           "confidence": "medium", "risk_rationale": "shared component", "risk_source_refs": ["R-1"],
           "risk_policy_revision": "factory-starter-v1", "coverage_refs": [], "unknowns": [],
           "verification_depth": "normal", "required_scenarios": ["opens"],
           "test_level_rationale": "user path", "design_review_required": False,
           "coverage_contract_revision": "coverage-observation-v1",
           "coverage_obligations": [{"obligation_id": f"OB-{rid}"}],
           "coverage_delta": {"baseline_kind": "initial",
                              "initial_scope_rationale": "no existing case observes it",
                              "entries": [{"obligation_id": f"OB-{rid}", "disposition": "gap",
                                           "rationale": "bounded search found nothing reusable",
                                           "gap_reason": "new check awaits Gate A"}],
                              "counts": {"logical_cases_before": 0, "logical_cases_after": 1,
                                         "executable_instances_before": 0,
                                         "executable_instances_after": 1},
                              "planned_instance_ids": [f"planned:{rid}"]}}
    row.update(extra)
    return {key: value for key, value in row.items() if value is not None or key != "coverage_contract_revision"}


def legacy_row(rid="TS-1", **extra):
    """The same row as a story that never opted into the coverage contract writes it."""
    row = plan_row(rid, **extra)
    for key in ("coverage_contract_revision", "coverage_obligations", "coverage_delta"):
        row.pop(key, None)
    return row


def write_story(root: Path, ticket: str, rows, mode="new", version=1) -> Path:
    task = root / "qa-factory" / "artifacts" / ticket
    (task / "work").mkdir(parents=True, exist_ok=True)
    (task / "state").mkdir(parents=True, exist_ok=True)
    (task / "pipeline.json").write_text(json.dumps(
        {"task": ticket, "stages": {"S3": {"status": "running"}}}), encoding="utf-8")
    # GW1-41 (A1, A4): the S3 exit checks the plan against the register. A register of ONE requirement, R-1; every row names
    # it and carries a disposition (a row without one counts for nothing); test-plan.md has the same rows in its `R` column.
    rows = [dict({"requirements": ["R-1"], "disposition": "automate"}, **r) if isinstance(r, dict) else r for r in rows]
    (task / "work" / "requirements-register.md").write_text(
        "## Register\n\n| R | Requirement | source | derived_from | verifiable | ac_ref |\n|---|---|---|---|---|---|\n"
        "| R-1 | the path opens | ac | - | yes | AC-1 |\n", encoding="utf-8")
    cells = "".join(f"| {r.get('id', 'TS-1')} | what | R-1 | h | degraded | P2 | o | o | `automate` - r | | | t |\n"
                    for r in rows if isinstance(r, dict))
    (task / "test-plan.md").write_text(
        "---\ntask: " + ticket + "\n---\n\n## Plan\n\n| TS | what we verify | R | defect hypothesis | impact class | priority | observable | oracle | "
        "disposition + reason | fit | level | technique |\n|---|---|---|---|---|---|---|---|---|---|---|---|\n" + cells
        + "\n## Recommended regression\n\nNo regression: the fixture story defends no blast radius\n", encoding="utf-8")
    (task / "work" / "test-plan.json").write_text(json.dumps(rows), encoding="utf-8")
    (task / "state" / "controller.json").write_text(json.dumps(
        {"plan_contract_mode": mode, "coverage_contract_version": version}), encoding="utf-8")
    return task


# --- what gate-inputs will require, required at the S3 exit -------------------------

def part_plan_contract() -> None:
    complete = [plan_row("TS-1"), plan_row("TS-2")]
    check("a complete plan passes the gate rule", not P.gate_plan_errors(complete, "new", 1))

    # RN1-2: the revision mark is CODE's. `coverage_revision_errors` no longer says "missing"; the S3 exit judges the plan as if
    # stamped (`stamp_revision`), so a mixed set owes its `coverage_delta` in the strategist's context (the proof is demanded
    # before the mark is written), and a row naming another revision is refused with the expected value.
    mixed = [plan_row("TS-1"), legacy_row("TS-2")]
    check("a half-migrated plan is no 'missing field' finding any more", not P.coverage_revision_errors(mixed))
    stamped_mixed = P.stamp_revision(mixed, "legacy")
    check_in("but its stamped row owes the coverage delta", "TS-2: coverage_delta required",
             " ".join(P.gate_plan_errors(stamped_mixed, "legacy", 1)))
    check_in("another revision is named with the expected one",
             "coverage-observation-v1", " ".join(P.coverage_revision_errors([plan_row("TS-3", coverage_contract_revision="v0")])))

    bare = [legacy_row("TS-1"), legacy_row("TS-2")]
    check("a wholly legacy plan stays readable and unstamped (the controller's own rule)",
          P.stamp_revision(bare, "legacy") == bare and not P.coverage_revision_errors(bare))
    check("in the new contract mode the same plan is stamped, row by row",
          [r["coverage_contract_revision"] for r in P.stamp_revision(bare, "new")] == ["coverage-observation-v1"] * 2)

    root = temp_project("qa-plan-gate-")
    try:
        write_story(root, "QA-22", mixed, mode="legacy")
        result = run_script("planning_contract.py", "--root", root, cwd=root)
        check("the S3 exit detector fails on it", result.returncode == 1, result.stdout)
        check_in("naming the row that owes its coverage delta", "TS-2: coverage_delta required", result.stdout)
        check_in("and the way a person passes the block", "waiver.py", result.stdout)

        write_story(root, "QA-22", [plan_row("TS-1"), plan_row("TS-2")], mode="legacy")
        ok = run_script("planning_contract.py", "--root", root, cwd=root)
        check("a repaired plan passes the same detector", ok.returncode == 0,
              ok.stdout + ok.stderr)
    finally:
        cleanup(root)

    empty = temp_project("qa-plan-gate-empty-")
    try:
        result = run_script("planning_contract.py", "--root", empty, cwd=empty)
        check("a project with no story is fail-open, never a block", result.returncode == 0,
              result.stdout + result.stderr)
    finally:
        cleanup(empty)


# --- the verdict is computed from the roll-call ---------------------------------------

LIVE_ROLLCALL = """# Critic findings

Verdict: approve_with_concerns (2 concerns, 0 fail), confidence: medium.

## Roll-call

| TS | case | status |
|---|---|---|
| TS-1 | TC-001 | found |
| TS-2 | TC-002 | found (not semantically reviewed) |
| TS-3 | TC-003 | found; sound |
"""


COLUMN_ROLLCALL = """# Critic findings

Verdict: approve_with_concerns (2 concerns, 0 fail), confidence: medium.

## Roll-call

| TS | case | reviewed | note |
|---|---|---|---|
| TS-1 | TC-001 | yes | found |
| TS-2 | TC-002 | no | found, not read yet |
| TS-3 | TC-003 | yes | found; sound |
"""


def part_rollcall() -> None:
    # The 0.7.4 shape has no `reviewed` column. Its rows are still read, and what it says about
    # them is NOTHING — until 0.7.19 a phrase list over the row decided it, so a critic who
    # worded the cell differently was counted as having reviewed it (FR-12).
    rows = R.parse_rollcall(LIVE_ROLLCALL)
    facts = R.derive(rows)
    check("the 0.7.4 table shape is still read", [r["case"] for r in rows] ==
          ["TC-001", "TC-002", "TC-003"])
    check("with no column, no row is called reviewed", facts["reviewed"] == 0, str(facts))
    check("and none is called unreviewed either", facts["unreviewed"] == [], str(facts))
    check("they are unstated, by name", facts["unstated"] == ["TC-001", "TC-002", "TC-003"],
          str(facts))
    check("so the verdict such a table computes is `partial`",
          facts["verdict_ceiling"] == "partial", str(facts))
    unstated_errors = R.findings_errors(Path("critic-findings.md"), LIVE_ROLLCALL)
    check_in("the refusal names the field that is missing", "has no `reviewed` column",
             unstated_errors)
    check_in("and the repair, for every row", "write `yes` or `no` for every row",
             unstated_errors)

    # With the column, the field decides — and an approve over a row it says `no` about is
    # refused exactly as before.
    facts = R.derive(R.parse_rollcall(COLUMN_ROLLCALL))
    check("the column is read row by row", facts["unreviewed"] == ["TC-002"], str(facts))
    errors = R.findings_errors(Path("critic-findings.md"), COLUMN_ROLLCALL)
    check_in("an approving verdict over an unreviewed row is refused", "the verdict this "
             "roll-call computes is `partial`", errors)
    check_in("the digest has to carry the count", '"2 of 3 reviewed"', errors)
    check_in("and gate A has to be told which cases", "Unreviewed for Gate A", errors)

    honest = COLUMN_ROLLCALL.replace("Verdict: approve_with_concerns (2 concerns, 0 fail),",
                                     "Verdict: partial — 2 of 3 reviewed,") + \
        "\nUnreviewed for Gate A: TC-002\n"
    check("a `partial` verdict with the count and the list passes",
          not R.findings_errors(Path("critic-findings.md"), honest),
          str(R.findings_errors(Path("critic-findings.md"), honest)))

    # The wording in the note no longer decides anything: the column says `yes`, so the row is
    # reviewed, and the same sentence that used to flip it is now what it always was — a note.
    worded = COLUMN_ROLLCALL.replace("| TS-2 | TC-002 | no | found, not read yet |",
                                     "| TS-2 | TC-002 | yes | found (not semantically reviewed "
                                     "in round 1) |")
    facts = R.derive(R.parse_rollcall(worded))
    check("a note that reads like a refusal does not override the column",
          (facts["reviewed"], facts["unreviewed"]) == (3, []), str(facts))

    explicit = """Verdict: approve

## Roll-call

| plan row | case | reviewed | note |
|---|---|---|---|
| TS-1 | TC-001 | yes | sound |
"""
    check("an explicit `reviewed` column is authoritative and a full review may approve",
          not R.findings_errors(Path("critic-findings.md"), explicit),
          str(R.findings_errors(Path("critic-findings.md"), explicit)))
    check_in("an unknown verdict is named against the closed list", "outside",
             R.findings_errors(Path("critic-findings.md"), explicit.replace("approve", "looks_fine")))


# --- the one-line fix that needs no second round -------------------------------------

def findings_with_fix(version="cv_old", extra="") -> str:
    fix = json.dumps([{"case_id": "TC-014", "locator": "Then 3",
                       "find": "denied with a 4xx", "replace": "denied with 401 or 403",
                       "reviewed_version": version}])
    return ("Verdict: approve_with_fixes\n\n## Roll-call\n\n"
            "| plan row | case | reviewed | note |\n|---|---|---|---|\n"
            "| TS-14 | TC-014 | yes | one wording fix |\n\n"
            f"## Fixes without a new round\n\n```json\n{fix}\n```\n" + extra)


def pin_case(task: Path, body: str, previous: str = "") -> str:
    source = task / "work" / "test-cases" / "api" / "TC-014.md"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(f"---\nid: TC-014\nstatus: Draft\ntask: QA-23\n---\n{body}\n", encoding="utf-8")
    record = V.create_version(task / "store", source)
    V.pin_batch(task, [record], {"TC-014": previous} if previous else None)
    return record["version"]


def part_fixes() -> None:
    root = temp_project("qa-case-fix-")
    try:
        task = root / "qa-factory" / "artifacts" / "QA-23"
        (task / "work").mkdir(parents=True)
        (task / "pipeline.json").write_text(json.dumps({"task": "QA-23"}), encoding="utf-8")
        old = pin_case(task, "Then 3: the request is denied with a 4xx status.")
        findings = task / "work" / "test-cases" / "api" / "critic-findings.md"
        findings.write_text(findings_with_fix(old), encoding="utf-8")

        errors = R.findings_errors(findings, task_root=task)
        check_in("a replacement that never reached the pinned case blocks",
                 "the fix for TC-014 was not applied", errors)

        debted = findings_with_fix(old, extra="\n## Gate A debts\n\n- TC-014 Then 3 stays loose; "
                                              "owner: qa-case-designer, next story\n")
        findings.write_text(debted, encoding="utf-8")
        check("declaring it a Gate A debt with an owner is accepted",
              not R.findings_errors(findings, task_root=task),
              str(R.findings_errors(findings, task_root=task)))

        pin_case(task, "Then 3: the request is denied with 401 or 403.", previous=old)
        findings.write_text(findings_with_fix(old), encoding="utf-8")
        check("applying it and re-pinning is accepted without a new review round",
              not R.findings_errors(findings, task_root=task),
              str(R.findings_errors(findings, task_root=task)))

        no_block = findings_with_fix(old).split("## Fixes")[0]
        check_in("approve_with_fixes with no replacements is just `approve`",
                 "with no `## Fixes without a new round` block",
                 R.findings_errors(findings, no_block, task))
    finally:
        cleanup(root)


# --- pinning is a code step, and its paths are portable --------------------------

def part_pinning() -> None:
    root = temp_project("qa-pin-")
    try:
        task = root / "qa-factory" / "artifacts" / "QA-15"
        cases = task / "work" / "test-cases" / "workflows"
        cases.mkdir(parents=True)
        for n in (1, 2):
            (cases / f"TC-00{n}.md").write_text(
                f"---\nid: TC-00{n}\nstatus: Draft\ntask: QA-15\n---\nbody {n}\n", encoding="utf-8")
        store = root / "qa-factory" / "case-store"

        missing = run_script("case_versions.py", "--store", store, "--task-root", task, "--verify",
                             cwd=root)
        check("the pre-critic check names unpinned cases", missing.returncode == 1)
        check_in("by case id", "TC-001", missing.stdout + missing.stderr)

        pinned = run_script("case_versions.py", "--store", store, "--task-root", task, "--all",
                            cwd=root)
        check("one batch command pins the whole story", pinned.returncode == 0,
              pinned.stdout + pinned.stderr)
        check_in("all of it", '"pinned": 2', pinned.stdout)
        check("and the precondition is then satisfied",
              run_script("case_versions.py", "--store", store, "--task-root", task, "--verify",
                         cwd=root).returncode == 0)

        (cases / "TC-001.md").write_text(
            "---\nid: TC-001\nstatus: Draft\ntask: QA-15\n---\nrepaired\n", encoding="utf-8")
        again = run_script("case_versions.py", "--store", store, "--task-root", task, "--all",
                           cwd=root)
        check("a repair round re-pins without hand-written expected versions",
              again.returncode == 0, again.stdout + again.stderr)

        links = json.loads((task / "state" / "story-case-links.json").read_text(encoding="utf-8"))
        paths = [link["store_provenance"]["source_path"] for link in links["links"]]
        check("A20: no link carries a machine-local path",
              all(not Path(p).is_absolute() and "\\" not in p for p in paths), str(paths))
        check_in("the provenance stays readable, relative to the project", "test-cases/workflows",
                 paths)
        check("an absolute path written before A20 is still read, not rejected",
              V.read_source_path({"store_provenance": {"source_path": "C:\\old\\TC-001.md"}})
              == "C:/old/TC-001.md")
    finally:
        cleanup(root)


# --- closed vocabularies, checked where the value is written -------------------------

PLAN_MD = """---
task: QA-26
created: 2026-09-20
---

# Test plan

## Plan

| TS | what we verify | R | defect hypothesis | impact class | priority | observable | oracle | disposition + reason | fit | level |
|---|---|---|---|---|---|---|---|---|---|---|
| TS-1 | versioning is unchanged | R-1 | {klass} | degraded | P2 | diff:src/a.py:1 | requirement:R-1 | `automate` — main path | new | api |
"""


def part_vocabularies() -> None:
    import validate_artifacts as VA
    root = temp_project("qa-vocab-")
    try:
        task = root / "qa-factory" / "artifacts" / "QA-26"
        task.mkdir(parents=True)
        plan = task / "test-plan.md"
        plan.write_text(PLAN_MD.format(klass="regression @ workflow versioning API"), encoding="utf-8")
        errors: list = []
        VA.check_plan_v0(plan, errors)
        check_in("a plan row's invented defect class is refused where it is written",
                 "defect hypothesis 'regression @ workflow versioning API'", errors)
        check_in("with the allowed values in the message", "regression:BUG-NNN", errors)

        plan.write_text(PLAN_MD.format(klass="seam @ workflow versioning API"), encoding="utf-8")
        errors = []
        VA.check_plan_v0(plan, errors)
        check("a class from the closed list passes", not errors, str(errors))

        case = task / "work" / "test-cases" / "api" / "TC-001.md"
        case.parent.mkdir(parents=True)
        case.write_text("---\nid: TC-001\ntitle: t\narea: api\npriority: P2\nstatus: Draft\n"
                        "channel: auto\nreuse_decision: recycled\nupdated: 2026-09-20\n"
                        "task: QA-26\ncovers: [R-1]\ndefect_class: regression\n"
                        "basis: requirement:R-1\n---\nbody\n", encoding="utf-8")
        errors = []
        VA.check_case(case, errors)
        check_in("a case's defect_class is held to the same list", "defect_class 'regression'", errors)
        check_in("and reuse_decision is a closed list too", "reuse_decision 'recycled'", errors)
    finally:
        cleanup(root)


if __name__ == "__main__":
    part_plan_contract()
    part_rollcall()
    part_fixes()
    part_pinning()
    part_vocabularies()
    finish("test_case_gates")
