#!/usr/bin/env python3
"""An obligation id is the plan's, and an unbound obligation is named while the window is open.

Every shape here is TP2-2553's own. The plan spelled `TS-1-O1`; every fragment the
automator wrote spelled `OB-1`. `coverage_projection` joins by exact equality, so twelve green
instances produced `unique_instances: 0` and nine coverage gaps — read by everyone downstream
as missing product coverage. Window 2 then spent two repair rounds on bindings for `OB-6..OB-9`
that had never existed, and nothing said so until delivery.

So: `manifest_put.py` refuses a spelling the plan does not name (and a person's word passes
it), `s5_precheck.py` names an unbound obligation of the dispatch scope before the handoff,
and `migrate_artifacts.py --if-older` renames the `OB-n` a 0.7.9 story already wrote.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness import (check, check_eq, check_in, check_not_in, cleanup, finish,  # noqa: E402
                     run_script, temp_project)

import coverage_contract as CC  # noqa: E402
import manifest_put as M  # noqa: E402
import s5_precheck as P  # noqa: E402

TICKET = "TP2-2553"

# Three obligations over two plan rows — the smallest shape that tells a positional rename
# (OB-2 -> TS-1-O2) apart from a per-row one.
PLAN_ROWS = [
    {"id": "TS-1", "schema_version": 2, "coverage_obligations": [
        {"obligation_id": "TS-1-O1", "decision": "automate", "execution_scope": "current_task"},
        {"obligation_id": "TS-1-O2", "decision": "automate", "execution_scope": "current_task"}]},
    {"id": "TS-2", "schema_version": 2, "coverage_obligations": [
        {"obligation_id": "TS-2-O1", "decision": "automate", "execution_scope": "current_task"}]},
]

CASE_MD = """---
id: {case}
status: Draft
---
Plan row: {row}

## Given
A request.

## When
Call it.

## Then
1. The body carries `status_ok`.
"""


def make_story(rows=PLAN_ROWS, legacy_plan=False):
    """A project with one story, its plan and two cases (TC-005 on TS-1, TC-006 on TS-2)."""
    root = temp_project("qa-obligation-join-")
    task = root / "qa-factory" / "artifacts" / TICKET
    (task / "work" / "test-cases").mkdir(parents=True)
    plan = [{"id": "TS-1", "schema_version": 1}] if legacy_plan else rows
    (task / "work" / "test-plan.json").write_text(json.dumps({"rows": plan}), encoding="utf-8")
    for case, row in (("TC-005", "TS-1"), ("TC-006", "TS-2")):
        (task / "work" / "test-cases" / f"{case}.md").write_text(
            CASE_MD.format(case=case, row=row), encoding="utf-8")
    return root, task


def put(root, fragment):
    path = root / "fragment.json"
    path.write_text(json.dumps(fragment), encoding="utf-8")
    return run_script("manifest_put.py", "--task", TICKET, "--fragment", str(path), cwd=root,
                      env={**dict(__import__("os").environ), "CLAUDE_PROJECT_DIR": str(root)})


def main() -> None:
    # --- 1. the refusal, and the one word that passes it ------------------------------------
    root, task = make_story()
    try:
        legacy_fragment = {"tests": [{"case": "TC-005", "file": "tests/t.py",
                                      "instance_id": "test_ok", "covers": ["TC-005"]}],
                           "obligation_bindings": [{"obligation_id": "OB-1",
                                                    "instance_ids": ["test_ok"]},
                                                   {"obligation_id": "OB-2",
                                                    "instance_ids": ["test_ok"]}]}
        result = put(root, legacy_fragment)
        check_eq("a fragment spelling OB-n against a schema-2 plan is refused",
                 result.returncode, M.EXIT_BAD_FRAGMENT)
        check_in("the refusal names the ids it refused", "OB-1, OB-2", result.stderr)
        check_in("and the ids the plan does name",
                 "the plan names TS-1-O1, TS-1-O2, TS-2-O1", result.stderr)
        check_in("and where they are written", "work/test-plan.json", result.stderr)
        check_in("and the word that passes it", 'waiver.py --task <TICKET> --stage S5 '
                 '--block "obligation-id"', result.stderr)
        check_not_in("nothing was committed", "revision", result.stdout)

        # A person's recorded decision passes any block in this factory — read here, at the
        # source, the way s5_precheck.passed_by_word reads it.
        (task / "pipeline.json").write_text(json.dumps({"stage_overrides": [
            {"stage": "S5", "match": "obligation-id", "decision": "keep the ids as they are, "
             "this story predates the plan rewrite", "at": "2026-09-23"}]}), encoding="utf-8")
        passed = put(root, legacy_fragment)
        check_eq("a person's word passes the refusal", passed.returncode, 0)
        check_in("and the fragment lands", "automation-manifest.json: revision", passed.stdout)
    finally:
        cleanup(root)

    # --- 2. a legacy plan names no obligation and refuses none -------------------------------
    root, task = make_story(legacy_plan=True)
    try:
        result = put(root, {"obligation_bindings": [{"obligation_id": "OB-1",
                                                     "instance_ids": ["test_ok"]}]})
        check_eq("a plan with no schema-2 obligations refuses nothing", result.returncode, 0)
    finally:
        cleanup(root)

    # --- 3. s5_precheck names the unbound obligation of the scope ----------------------------
    root, task = make_story()
    try:
        manifest = {"tests": [
            {"case": "TC-005", "file": "tests/t.py", "instance_id": "test_five",
             "covers": ["TC-005"], "status": "green"},
            {"case": "TC-006", "file": "tests/t.py", "instance_id": "test_six",
             "covers": ["TC-006"], "status": "green"}],
            "obligation_bindings": [{"obligation_id": "TS-1-O1", "instance_ids": ["test_five"]},
                                    {"obligation_id": "TS-1-O2", "instance_ids": ["test_five"]}]}
        findings: list = []
        P.check_obligations(task, manifest, ["TC-005", "TC-006"], {}, set(), findings)
        check_eq("one bound and one unbound obligation is exactly one finding",
                 len(findings), 1)
        if findings:
            check_in("the finding names the unbound obligation", "TS-2-O1", findings[0]["message"])
            check_in("and the case it belongs to", "TC-006", findings[0]["message"])
            check_eq("and it is a repair, not a question", findings[0]["level"], "repair")
            check_in("its fix names the writer", "manifest_put.py", findings[0]["fix"])
            # one `--block "obligation-id"` covers this check and manifest_put both.
            check_in("and its id carries the block word", "obligation-id", findings[0]["id"])

        # a binding the plan does not know is the same finding, with the allowed ids named.
        stray = dict(manifest, obligation_bindings=[{"obligation_id": "OB-1",
                                                     "instance_ids": ["test_five"]}])
        findings = []
        P.check_obligations(task, stray, ["TC-005", "TC-006"], {}, set(), findings)
        check_eq("an unknown spelling leaves every obligation of the scope unbound",
                 len(findings), 3)
        check_in("and the finding names what the plan does allow",
                 "it names TS-1-O1, TS-1-O2, TS-2-O1", findings[0]["message"])

        # what is not owed: a handed case, and a manual obligation the runner discharges.
        findings = []
        P.check_obligations(task, manifest, ["TC-005", "TC-006"], {}, {"TC-006"}, findings)
        check_eq("a case handed to the person owes no binding", findings, [])
        manual_root, manual_task = make_story(rows=[
            PLAN_ROWS[0],
            {"id": "TS-2", "schema_version": 2, "coverage_obligations": [
                {"obligation_id": "TS-2-O1", "decision": "manual-human",
                 "execution_scope": "current_task"}]}])
        try:
            findings = []
            P.check_obligations(manual_task, manifest, ["TC-005", "TC-006"], {}, set(), findings)
            check_eq("a manual-* obligation is not an automated binding's job", findings, [])
        finally:
            cleanup(manual_root)

        # legacy plan: nothing to join, nothing to ask.
        legacy_root, legacy_task = make_story(legacy_plan=True)
        try:
            findings = []
            P.check_obligations(legacy_task, manifest, ["TC-005"], {}, set(), findings)
            check_eq("a legacy plan produces no finding", findings, [])
        finally:
            cleanup(legacy_root)
    finally:
        cleanup(root)

    # --- 4. the migration renames OB-n by position, and never guesses ------------------------
    root, task = make_story()
    try:
        seed = {"tests": [
            {"case": "TC-005", "file": "tests/t.py", "instance_id": "test_five",
             "covers": ["TC-005"], "status": "green",
             "obligation_refs": [{"obligation_id": "OB-1", "obligation_hash": "h1"}],
             "obligation_ids": ["OB-1"]},
            {"case": "TC-006", "file": "tests/t.py", "instance_id": "test_six",
             "covers": ["TC-006"], "status": "green"}],
            "obligation_bindings": [
                {"obligation_id": "OB-1", "instance_ids": ["test_five"], "sensitivity": "proven"},
                {"obligation_id": "OB-2", "instance_ids": ["test_five"]},
                {"obligation_id": "OB-3", "instance_ids": ["test_six"]},
                {"obligation_id": "OB-4", "instance_ids": ["test_six"]}]}
        # seeded the way 0.7.9 wrote it: straight into the artifact, before the refusal existed.
        (task / "work" / "automation-manifest.json").write_text(json.dumps(seed), encoding="utf-8")
        (task / "state").mkdir(exist_ok=True)

        import migrate_artifacts as MA
        # the real entry point: a story resumed on a newer plugin, exactly as a resume runs it.
        proc = run_script("migrate_artifacts.py", "--task-root", str(task), "--if-older",
                          cwd=root)
        check("--if-older runs to the end", proc.returncode == 0,
              f"exit {proc.returncode}; stderr: {proc.stderr[-800:]}; stdout: {proc.stdout[-400:]}")
        # the journal writes its own OK line first; the report is the last line. A last line that is not
        # JSON is one FAIL line with the stdout tail (B-320), never a traceback that hides the other checks.
        try:
            report = json.loads(proc.stdout.strip().splitlines()[-1])
        except (ValueError, IndexError):
            check("the last stdout line is the JSON report", False,
                  f"stdout tail: {proc.stdout[-400:]!r}; stderr tail: {proc.stderr[-400:]!r}")
            report = None
        if report is not None:
            left = json.dumps(report.get("left"))
            check_in("and says what it renamed",
                     "obligation_bindings[] renamed to the plan's ids", json.dumps(report["changed"]))
            migrated = json.loads((task / "work" / "automation-manifest.json").read_text(encoding="utf-8"))
            bound = sorted(b["obligation_id"] for b in migrated.get("obligation_bindings") or [])
            check("OB-1..OB-3 are renamed to the ids the plan names, OB-4 stays",
                  bound == ["OB-4", "TS-1-O1", "TS-1-O2", "TS-2-O1"], f"got {bound!r}; left: {left}")
            retracted = sorted(migrated.get("retracted_obligations") or [])
            check("the old spellings are retracted, not left beside the new ones",
                  retracted == ["OB-1", "OB-2", "OB-3"], f"got {retracted!r}; left: {left}")
            check("an OB-n past the plan's count is reported, never guessed", "OB-4" in left,
                  f"left: {left}")
            check("with the reason", "no obligation at that position in the plan (3 named)" in left,
                  f"left: {left}")
            check_eq("the renamed binding keeps its own fields",
                     next(b for b in migrated["obligation_bindings"]
                          if b["obligation_id"] == "TS-1-O1").get("sensitivity"), "proven")
            five = next(t for t in migrated["tests"] if t.get("instance_id") == "test_five")
            check_eq("the instance re-cites the same obligation by the plan's id",
                     five.get("obligation_ids"), ["TS-1-O1"])
            check_eq("and so do its obligation_refs, hash untouched",
                     five.get("obligation_refs"), [{"obligation_id": "TS-1-O1", "obligation_hash": "h1"}])

            # the point of the whole package: the projection joins again.
            projection = CC.coverage_projection(task, report={}, manifest=migrated)
            check("coverage_projection now joins instances instead of reporting nine gaps",
                  projection["unique_instances"] > 0,
                  f"unique_instances = {projection['unique_instances']}")
            check_eq("every obligation of the plan is reachable",
                     sorted(o["obligation_id"] for o in projection["obligations"]),
                     ["TS-1-O1", "TS-1-O2", "TS-2-O1"])

            # run twice: the second pass has nothing left to rename and writes nothing.
            again = MA._rename_legacy_obligations(
                task, TICKET, root,
                json.loads((task / "work" / "automation-manifest.json").read_text(encoding="utf-8")))
            check_eq("a second run renames nothing", again["changed"], [])
    finally:
        cleanup(root)

    # --- one stale test row can leave the manifest (TP1-13797, 27.09) -------------------
    # `tests[]` had no door: a row leaves only when every case it proves goes unresolved, and a
    # partition-scoped unresolved row by design does not compete with `tests[]`. So seven rows
    # written before each partition had an explicit id stood beside the good ones, `run_suite`
    # refused the whole case request over one id it could not find, and TC-002/TC-003 could not
    # be run at all.
    import manifest_put as MP
    held = {"tests": [
        {"instance_id": "test_x[case0]", "test_file": "a.py", "covers": ["TC-002"]},
        {"instance_id": "test_x[regex-operator]", "test_file": "a.py", "covers": ["TC-002"]},
        {"instance_id": "test_y[falsy-match]", "test_file": "a.py", "covers": ["TC-003"]}]}
    summary = {}
    MP._retract_instances(held, {"retracted_instances": ["test_x[case0]"]}, summary)
    check_eq("a retracted instance leaves tests[], the case's good rows stay",
             [e["instance_id"] for e in held["tests"]],
             ["test_x[regex-operator]", "test_y[falsy-match]"])
    check_eq("and the retraction is recorded for the next reader",
             held.get("retracted_instances"), ["test_x[case0]"])
    check_eq("the summary counts it", summary.get("retracted_instances"), 1)
    refused = ""
    try:
        MP._retract_instances(dict(held), {"retracted_instances": ["test_x[regex-operator]"],
            "tests": [{"instance_id": "test_x[regex-operator]", "test_file": "a.py",
                       "covers": ["TC-002"]}]}, {})
    except ValueError as exc:
        refused = str(exc)
    check_in("one fragment cannot both send and retract an instance",
             "cannot both send and retract", refused)
    missing = ""
    try:
        MP._retract_instances(dict(held), {"retracted_instances": ["test_z[nope]"]}, {})
    except ValueError as exc:
        missing = str(exc)
    check_in("and an id no row answers to is refused, not silently ignored",
             "names no row this manifest holds", missing)

    finish("obligation join (TP2-2553)")


if __name__ == "__main__":
    main()
