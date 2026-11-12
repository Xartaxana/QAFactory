"""An unrelated failed instance does not erase a witnessed passed obligation."""
import hashlib
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import coverage_contract as C
from event_store import content_hash


def main():
    with tempfile.TemporaryDirectory(prefix="qa-targeted-coverage-") as td:
        root = Path(td); work = root / "work"; work.mkdir()
        evidence = root / "run.txt"; evidence.write_text("immutable run evidence", encoding="utf-8")
        evidence_ref = {"path": "run.txt", "sha256": hashlib.sha256(evidence.read_bytes()).hexdigest()}
        obligation = {"obligation_id": "O-PASS", "behavior": "selected behavior", "observation_boundary": "api",
            "completion_condition": "done", "requirement_refs": [{"ref": "R-1", "revision": "1"}],
            "applicable_scenarios": ["positive"], "oracle_status": "resolved", "oracle_source_ref": "spec:R-1",
            "decision": "reuse", "execution_scope": "current_task",
            "sufficiency_review": {"author_dispatch_id": "s3", "input_hash": "h", "rationale": "direct"},
            "coverage_links": [{"candidate_id": "c", "assessment": "sufficient", "assessment_reason": "direct",
                "assertion_refs": ["test.py:9"], "proves": ["selected behavior"], "does_not_prove": []}],
            "planned_check_refs": []}
        row = {"id": "TS-1", "schema_version": 2, "coverage_obligations": [obligation]}
        (work / "test-plan.json").write_text(json.dumps({"rows": [row]}), encoding="utf-8")
        ob_hash = content_hash(obligation)
        common = {"schema_version": 2, "input_hash": "window-h",
            "review": {"verdict": "approved", "input_hash": "window-h"},
            "change_disposition": "unchanged", "change_basis_ref": "repo:test",
            "assertion_id": "test.py:9", "defect_location": "src.py:4", "evidence_refs": [evidence_ref]}
        passed = dict(common, instance_id="selected", outcome="passed", execution_fingerprint="fp-pass",
            obligation_ids=["O-PASS"], obligation_refs=[{"obligation_id": "O-PASS", "obligation_hash": ob_hash}],
            obligation_hash=content_hash([{"obligation_id": "O-PASS", "obligation_hash": ob_hash}]))
        failed = dict(common, instance_id="unrelated", outcome="failed", execution_fingerprint="fp-fail",
            obligation_ids=["O-OTHER"], obligation_refs=[{"obligation_id": "O-OTHER", "obligation_hash": "other"}],
            obligation_hash=content_hash([{"obligation_id": "O-OTHER", "obligation_hash": "other"}]))
        window = {"schema_version": 2, "input_hash": "window-h", "required_quality_checks": ["typecheck"],
            "quality_receipts": [{"id": "typecheck", "status": "passed", "input_hash": "window-h"}],
            "scope_instances": {"TC-1": ["selected"], "TC-2": ["unrelated"]},
            "instances": [passed, failed]}
        receipt = work / "window.json"; receipt.write_text(json.dumps(window), encoding="utf-8")
        receipt_ref = {"path": "work/window.json", "sha256": hashlib.sha256(receipt.read_bytes()).hexdigest()}
        state = {"dispatches": {"critic": {"stage": "S5", "status": "accepted",
            "window": window, "evidence_refs": [receipt_ref]}}}

        class FakeController:
            def __init__(self, _root): pass
            def state(self): return state

        binding = {"obligation_id": "O-PASS", "obligation_hash": ob_hash, "instance_ids": ["selected"],
            "design_assessment": "sufficient", "code_validity": "valid", "sensitivity": "not_required",
            "change_disposition": "unchanged", "change_basis_ref": "repo:test",
            "assertion_refs": ["test.py:9"], "quality_receipt_refs": ["typecheck"],
            "review_receipt_ref": "work/window.json"}
        report = {"current_results": [
            {"instance_id": "selected", "status": "passed", "input_fingerprint": "fp-pass"},
            {"instance_id": "unrelated", "status": "failed", "input_fingerprint": "fp-fail"}]}
        # HF4-10 (t-1480): only a check some factory script produces a receipt for is demanded; the data names `typecheck`
        import window_record as WR
        producers = root / "quality-producers.json"
        producers.write_text(json.dumps({"schema_version": 1, "producers": {"typecheck": "typecheck_receipt.py"}, "why": {}}),
                             encoding="utf-8")
        with patch("controller.Controller", FakeController), patch.object(WR, "QUALITY_PRODUCERS_FILE", producers):
            projection = C.coverage_projection(root, report, {"obligation_bindings": [binding]})
        assert projection["obligations"][0]["verified"] is True
        assert projection["obligations"][0]["execution_state"] == "passed"
        assert projection["unique_instances"] == 1
    print("=== test_coverage_targeted_projection: 3/3 ok ===")


if __name__ == "__main__":
    main()
