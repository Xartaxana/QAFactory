#!/usr/bin/env python3
"""The joint test on recorded run 12586: stage N's real output fed to the check that judges it before stage N+1 (F6-51, D2).

The registry (`references/stage-joints.json`) says WHICH checks a role's output meets; this file holds the joints on
artifacts the factory really wrote in run 12586, reused whole from the in-package fixtures (no new copy, no edit of a
fixture). Three joints were MEASURED green before they were pinned (plan critic t-650, and again by this node):

  J1  S5 -> S6   `run-12586-gate-b/.../work/automation-manifest.json` -> `validate_artifacts.check_phase_json` (the
                 check behind the run's 04:45 "required key 'run_witness' is missing"): no error.
  J2  S3 -> A    `run-12586-gate-b/.../work/test-plan.json` -> `planning_contract.gate_plan_errors(rows,
                 *story_contract_mode(root))` - the pure check the S3 detector applies to the plan. NEVER the whole
                 detector `detector_main`: with no pipeline.json it exits 0 with no output (a vacuous green). The mode is
                 `legacy`, 1 because the fixture has no `state/controller.json`.
  J3  S7 -> S8   `run-12586-red-then/work/triage.json` -> `check_phase_json` + `check_triage_v0(path, data, errors, None)`.
                 Shallow by construction: `task_root=None` skips the cross-checks that need the whole story.

Not covered by a fixture (stated, not silently green): S4 -> S5 `check_case` (neither fixture carries the register and the
check reads the cwd project), S6 -> S7 `run-report.json` (the fixture is TRIMMED by its README: `env_preflight` and `witness`
are dropped - an artifact the factory did not write whole is not an older form, so it is not pinned), the digest joint
(held by test_exit_gate_digest_source.py) and the window quality joint (test_quality_demand.py).

Each joint has its negative: the same artifact with one demanded key removed in a COPY, and the check names that key.
Run on its own: `python -B scripts/tests/test_stage_joints_12586.py`.
"""
import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import FIXTURES, PLUGIN_ROOT, check, check_eq, check_in, finish, temp_dir  # noqa: E402

sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))
import planning_contract as PC  # noqa: E402
import validate_artifacts as VA  # noqa: E402

GATE_B = FIXTURES / "run-12586-gate-b" / "TP1-12586"
RED_THEN = FIXTURES / "run-12586-red-then"


def phase_errors(path: Path) -> list:
    errors, notes = [], []
    VA.check_phase_json(path, errors, notes)
    return [str(e) for e in errors]


def j1_automation_manifest() -> None:
    manifest = GATE_B / "work" / "automation-manifest.json"
    check_eq("J1 (S5 -> S6): the recorded automation manifest passes check_phase_json", phase_errors(manifest), [])
    data = json.loads(manifest.read_text(encoding="utf-8"))
    check_in("J1 holds the key that run lacked on 04:45 (`run_witness`)", "run_witness", list(data))
    tmp = temp_dir("qa-joint-j1-")
    try:
        broken = copy.deepcopy(data)
        del broken["run_witness"]
        copy_path = tmp / "automation-manifest.json"
        copy_path.write_text(json.dumps(broken), encoding="utf-8")
        check_in("J1 negative: the same manifest without `run_witness` is refused by name",
                 "run_witness", " | ".join(phase_errors(copy_path)))
    finally:
        for f in tmp.iterdir():
            f.unlink()
        tmp.rmdir()


def j2_test_plan() -> None:
    rows = json.loads((GATE_B / "work" / "test-plan.json").read_text(encoding="utf-8"))["rows"]
    mode = PC.story_contract_mode(GATE_B)
    check_eq("J2: the fixture has no state/controller.json, so the story reads as the legacy contract, version 1",
             tuple(mode), ("legacy", 1))
    check_eq("J2 (S3 -> gate A): the recorded plan has rows", len(rows) > 0, True)
    check_eq("J2: the recorded plan passes gate_plan_errors", list(PC.gate_plan_errors(rows, *mode)), [])
    broken = copy.deepcopy(rows)
    del broken[0]["confidence"]
    check_in("J2 negative: row 0 without `confidence` is refused by name",
             "missing confidence", " | ".join(str(e) for e in PC.gate_plan_errors(broken, *mode)))


def j3_triage() -> None:
    triage = RED_THEN / "work" / "triage.json"
    check_eq("J3 (S7 -> S8): the recorded triage passes check_phase_json", phase_errors(triage), [])
    data = json.loads(triage.read_text(encoding="utf-8"))
    errors: list = []
    VA.check_triage_v0(triage, data, errors, None)
    check_eq("J3: and the shallow triage check (task_root None: no cross-checks)", [str(e) for e in errors], [])
    tmp = temp_dir("qa-joint-j3-")
    try:
        broken = {k: v for k, v in data.items() if k != "triage"}
        copy_path = tmp / "triage.json"
        copy_path.write_text(json.dumps(broken), encoding="utf-8")
        check_in("J3 negative: a triage file without the `triage` key is refused by name",
                 "triage", " | ".join(phase_errors(copy_path)))
    finally:
        for f in tmp.iterdir():
            f.unlink()
        tmp.rmdir()


def not_covered_by_a_fixture() -> None:
    """The joints the fixtures do not hold are NAMED, so a missing joint is a printed line and never a silent green."""
    manifest = RED_THEN / "work" / "automation-manifest.json"
    check_in("not covered: S5 -> S6 on the TRIMMED red-then manifest (it has no run_witness, by its README)",
             "run_witness", " | ".join(phase_errors(manifest)))
    report = RED_THEN / "work" / "run-report.json"
    check("not covered: S6 -> S7 run-report.json is trimmed by its README, no joint is pinned on it",
          bool(phase_errors(report)), "the trimmed run report unexpectedly passes - re-measure and add the joint")
    print("NOT COVERED BY FIXTURE: S4 -> S5 check_case (no register in either fixture), S6 -> S7 run-report.json (trimmed)")


def main() -> None:
    j1_automation_manifest()
    j2_test_plan()
    j3_triage()
    not_covered_by_a_fixture()
    finish("test_stage_joints_12586")


if __name__ == "__main__":
    main()
