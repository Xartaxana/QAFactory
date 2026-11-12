"""A single accepted v2 instance can verify two obligations without a duplicate run."""
import hashlib
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import mark_project, s5_apply
from controller import Controller
from test_controller_state import record_stage_acceptance
from event_store import content_hash
from coverage_contract import coverage_projection


def evidence(root, name, text):
    path = root / name
    path.write_text(text, encoding="utf-8")
    return {"path": name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def obligation(oid, requirement):
    return {"obligation_id": oid, "requirement_refs": [{"ref": requirement, "revision": "1"}],
            "behavior": "shared selected test proves " + requirement, "oracle_source_ref": "spec:" + requirement,
            "oracle_status": "resolved", "applicable_scenarios": [{"kind": "positive", "rationale": "main"}],
            "observation_boundary": "API state", "completion_condition": "request and state read complete",
            "coverage_links": [{"test_ref": "tests/test_shared.py::test_shared", "assertion_refs": ["tests/test_shared.py:9"],
                "proves": [requirement], "does_not_prove": [], "assessment": "sufficient",
                "assessment_reason": "assertion observes both effects"}],
            "decision": "reuse", "remaining_gap": "", "planned_check_refs": [],
            "execution_scope": "current_task",
            "sufficiency_review": {"author_dispatch_id": "strategy", "input_hash": "strategy-h", "rationale": "direct"},
            "observation_contract": {"claim_kind": ["ordinary"],
                "oracle_ref": {"ref": requirement, "revision": "1"},
                "surfaces": [{"id": "response", "boundary": "selected response", "assertion_ref": "tests/test_shared.py:9", "status": "planned"}],
                "controls": [], "completion_ref": "tests/test_shared.py:9",
                "independent_expectations": [], "source_conflicts": []}}


def accept_stage(controller, root, number):
    stage = f"S{number}"; ref = evidence(root, stage + ".txt", stage)
    record_stage_acceptance(root, stage)  # E-B11: S2-S4 close over the acceptor's record; the qa-worker stub has no author dispatch
    controller.apply("dispatch", {"id": "d" + stage, "stage": stage, "role": "qa-worker",
        "scope": ["TC-1", "TC-2"], "input_hash": stage, "budget": {}, "known_paths": {},
        "idempotency_key": "dispatch-" + stage})
    controller.apply("accept", {"id": "d" + stage, "status": "accepted", "stage_complete": True,
        "evidence_refs": [ref], "idempotency_key": "accept-" + stage})


def main():
    with tempfile.TemporaryDirectory(prefix="qa-coverage-controller-") as td:
        root = mark_project(Path(td))
        controller = Controller(root)
        controller.apply("initialize", {"scope": ["TC-1", "TC-2"], "source_revision": "src",
            "known_paths": {"root": str(root)}, "idempotency_key": "init"})
        for number in range(3):
            accept_stage(controller, root, number)
        one, two = obligation("O-1", "R-1"), obligation("O-2", "R-2")
        row = {"id": "TS-1", "schema_version": 2, "impact": "moderate", "likelihood": "medium",
            "confidence": "high", "risk_rationale": "two effects", "risk_source_refs": ["R-1", "R-2"],
            "risk_policy_revision": "factory-starter-v1", "coverage_refs": ["R-1", "R-2"],
            "unknowns": [], "verification_depth": "normal", "required_scenarios": ["TC-1", "TC-2"],
            "test_level_rationale": "unit", "design_review_required": False,
            "coverage_contract_revision": "coverage-observation-v1",
            "coverage_delta": {"baseline_kind": "initial", "initial_scope_rationale": "fixture initial scope",
                "planned_instance_ids": ["shared-i"],
                "counts": {"logical_cases_before": 2, "logical_cases_after": 2, "executable_instances_before": 1, "executable_instances_after": 1},
                "entries": [{"obligation_id": "O-1", "disposition": "reuse", "rationale": "shared assertion", "existing_case_refs": ["TC-1"]},
                            {"obligation_id": "O-2", "disposition": "reuse", "rationale": "shared assertion", "existing_case_refs": ["TC-2"]}]},
            "coverage_obligations": [one, two]}
        document = {"schema_version": 2, "rows": [row], "lifecycle_actions": []}
        (root / "work").mkdir()
        (root / "work/test-plan.json").write_text(json.dumps(document), encoding="utf-8")
        accept_stage(controller, root, 3)
        state_dir = root / "state"; state_dir.mkdir(exist_ok=True)
        (state_dir / "story-case-links.json").write_text(json.dumps({"links": [
            {"case_id": "TC-1", "version": "cv1"}, {"case_id": "TC-2", "version": "cv2"}]}))
        accept_stage(controller, root, 4)
        gate = {"id": "A", "gate": "A", "action": "approve", "status": "approved",
            "authorization_source": "human", "source_revision": "src", "scope": ["TC-1", "TC-2"],
            "input_revision": "src", "plan_content_hash": content_hash(document),
            "plan_semantic_hash": Controller._plan_semantic_hash(document),
            "oracle_content_hashes": Controller._oracle_hashes([row]), "coverage_contract_revisions": ["coverage-observation-v1"], "idempotency_key": "A"}
        controller.apply("decision", gate)
        s5_apply(controller, {"id": "s5-author", "stage": "S5", "role": "qa-automator",
            "scope": ["TC-1", "TC-2"], "input_hash": "s5-h", "budget": {}, "known_paths": {},
            "idempotency_key": "s5-author"})
        controller.apply("accept", {"id": "s5-author", "status": "accepted", "stage_complete": False,
            "evidence_refs": [evidence(root, "author.txt", "author green receipt")],
            "idempotency_key": "s5-author-accept"})
        s5_apply(controller, {"id": "s5-critic", "stage": "S5", "role": "qa-code-critic",
            "scope": ["TC-1", "TC-2"], "input_hash": "s5-h", "budget": {}, "known_paths": {},
            "idempotency_key": "s5-critic"})
        run_ref = evidence(root, "run.txt", "one selected execution")
        refs = [{"obligation_id": "O-1", "obligation_hash": content_hash(one)},
                {"obligation_id": "O-2", "obligation_hash": content_hash(two)}]
        instance = {"schema_version": 2, "instance_id": "shared-i", "outcome": "passed",
            "input_hash": "s5-h", "review": {"verdict": "approved", "input_hash": "s5-h"},
            "change_disposition": "unchanged", "change_basis_ref": "repo:test-sha",
            "obligation_ids": ["O-1", "O-2"], "obligation_refs": refs,
            "obligation_hash": content_hash(refs), "assertion_id": "tests/test_shared.py:9",
            "defect_location": "src/shared.py:4", "execution_fingerprint": "run-fingerprint",
            "evidence_refs": [run_ref]}
        window = {"schema_version": 2, "input_hash": "s5-h", "required_quality_checks": [],
            "author_dispatch_id": "s5-author", "reviewer_dispatch_id": "s5-critic",
            "quality_receipts": [], "scope_instances": {"TC-1": ["shared-i"], "TC-2": ["shared-i"]},
            "instances": [instance]}
        window_path = root / "work/s5-window.json"
        window_path.write_text(json.dumps(window), encoding="utf-8")
        window_ref = {"path": "work/s5-window.json", "sha256": hashlib.sha256(window_path.read_bytes()).hexdigest()}
        controller.apply("accept", {"id": "s5-critic", "status": "accepted", "stage_complete": True,
            "window": window, "evidence_refs": [window_ref], "idempotency_key": "s5-accept"})
        bindings = [{"obligation_id": oid, "obligation_hash": content_hash(ob),
            "instance_ids": ["shared-i"], "design_assessment": "sufficient", "code_validity": "valid",
            "sensitivity": "not_required", "change_disposition": "unchanged",
            "change_basis_ref": "repo:test-sha", "assertion_refs": ["tests/test_shared.py:9"],
            "quality_not_applicable_reason": "no configured quality gate", "review_receipt_ref": "work/s5-window.json"}
            for oid, ob in (("O-1", one), ("O-2", two))]
        projection = coverage_projection(root,
            {"current_results": [{"instance_id": "shared-i", "status": "passed",
                                   "input_fingerprint": "run-fingerprint"}]},
            {"obligation_bindings": bindings})
        assert projection["unique_instances"] == 1
        assert len(projection["obligations"]) == 2 and all(item["verified"] for item in projection["obligations"])
    print("=== test_coverage_controller_integration: 2/2 ok ===")


if __name__ == "__main__":
    main()
