"""Gate A binds exact lifecycle actions and refuses unsafe retirement."""
import hashlib
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import mark_project
from controller import Controller
from event_store import StateConflict, content_hash
from test_controller_state import record_stage_acceptance


def ref(root, name):
    path = root / name; path.write_text(name, encoding="utf-8")
    return {"path": name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def action(code_changes):
    return {"action_id": "LC-1", "kind": "retire", "reason": "requirement removed by owner",
            "case_refs": [{"case_id": "TC-1", "version": "cv1"}],
            "test_refs": [{"path": "tests/old.py", "sha256": "old-hash"}],
            "authoritative_change_refs": ["decision:R-1@2"], "requirement_disposition": "removed",
            "replacement_refs": [], "shared_dependents": [{"disposition": "preserved", "evidence_ref": "deps.txt"}],
            "coverage_before": ["O-1"], "coverage_after": ["removed:R-1"],
            "proposed_code_changes": code_changes, "proposed_tms_action": "archive",
            "decision_receipt_ref": "gate-a"}


def setup(root, lifecycle):
    c = Controller(root)
    c.apply("initialize", {"scope": ["TC-1"], "source_revision": "src", "known_paths": {"root": str(root)},
                           "idempotency_key": "init"})
    for n in range(3):
        stage = f"S{n}"; c.apply("dispatch", {"id": stage, "stage": stage, "role": "worker", "scope": ["TC-1"],
            "input_hash": stage, "budget": {}, "known_paths": {}, "idempotency_key": "d" + stage})
        record_stage_acceptance(root, stage)  # E-B11 (no-op for S0/S1); the `worker` stub has no author dispatch
        c.apply("accept", {"id": stage, "status": "accepted", "stage_complete": True,
            "evidence_refs": [ref(root, stage + ".txt")], "idempotency_key": "a" + stage})
    ob = {"obligation_id": "O-1", "requirement_refs": [{"ref": "R-1", "revision": "2"}],
        "behavior": "removed behavior remains retired", "oracle_source_ref": "decision:R-1@2", "oracle_status": "resolved",
        "applicable_scenarios": ["state"], "observation_boundary": "case store", "completion_condition": "review complete",
        "coverage_links": [], "decision": "new", "remaining_gap": "", "planned_check_refs": ["TC-1"],
        "execution_scope": "current_task", "sufficiency_review": {"author_dispatch_id": "S3", "input_hash": "h", "rationale": "owner decision"},
        "observation_contract": {"claim_kind": ["ordinary"],
            "oracle_ref": {"ref": "R-1", "revision": "2"},
            "surfaces": [{"id": "retirement", "boundary": "case store", "status": "planned", "assertion_ref": "TC-1"}],
            "controls": ["TC-1"], "completion_ref": "TC-1", "independent_expectations": [], "source_conflicts": []}}
    row = {"id": "TS-1", "schema_version": 2, "impact": "low", "likelihood": "low", "confidence": "high",
        "risk_rationale": "bounded", "risk_source_refs": ["R-1"], "risk_policy_revision": "factory-starter-v1",
        "coverage_refs": ["R-1"], "unknowns": [], "verification_depth": "low", "required_scenarios": ["TC-1"],
        "test_level_rationale": "unit", "design_review_required": False, "bounded_reversible": True,
        "coverage_obligations": [ob], "coverage_contract_revision": "coverage-observation-v1",
        "coverage_delta": {"baseline_kind": "initial", "initial_scope_rationale": "retirement baseline",
            "entries": [{"obligation_id": "O-1", "disposition": "gap", "rationale": "new retirement check",
                         "gap_reason": "no prior retirement coverage"}],
            "counts": {"logical_cases_before": 0, "logical_cases_after": 1,
                       "executable_instances_before": 0, "executable_instances_after": 1},
            "planned_instance_ids": ["retirement-check"]}}
    doc = {"schema_version": 2, "rows": [row], "lifecycle_actions": lifecycle}
    work = root / "work"; work.mkdir()
    (work / "test-plan.json").write_text(json.dumps(doc), encoding="utf-8")
    for n in (3, 4):
        stage = f"S{n}"; c.apply("dispatch", {"id": stage, "stage": stage, "role": "worker", "scope": ["TC-1"],
            "input_hash": stage, "budget": {}, "known_paths": {}, "idempotency_key": "d" + stage})
        record_stage_acceptance(root, stage)  # E-B11
        c.apply("accept", {"id": stage, "status": "accepted", "stage_complete": True,
            "evidence_refs": [ref(root, stage + ".txt")], "idempotency_key": "a" + stage})
    state = root / "state"; state.mkdir(exist_ok=True)
    (state / "story-case-links.json").write_text(json.dumps({"links": [{"case_id": "TC-1", "version": "cv1"}]}))
    return c, doc, row


def main():
    with tempfile.TemporaryDirectory(prefix="qa-lifecycle-gate-") as td:
        root = mark_project(Path(td)); current = action([{"path": "tests/old.py", "change": "delete"}])
        c, doc, row = setup(root, [current])
        base = {"id": "A", "gate": "A", "action": "approve", "status": "approved", "authorization_source": "human",
            "source_revision": "src", "scope": ["TC-1"], "input_revision": "src",
            "lifecycle_actions_hash": content_hash([current]), "lifecycle_actions": [current], "idempotency_key": "A"}
        base.update(c.gate_inputs())
        c.apply("decision", base)
        assert c.next_action()["stage"] == "S5"

        unsafe_root = root / "unsafe"; unsafe_root.mkdir()
        unsafe = action([])
        c2, doc2, row2 = setup(unsafe_root, [unsafe])
        decision = dict(base, id="unsafe-A", plan_content_hash=content_hash(doc2),
            oracle_content_hashes=Controller._oracle_hashes([row2]), lifecycle_actions_hash=content_hash([unsafe]),
            lifecycle_actions=[unsafe], idempotency_key="unsafe-A")
        decision.update(c2.gate_inputs())
        try:
            c2.apply("decision", decision); rejected = False
        except StateConflict:
            rejected = True
        assert rejected
    print("=== test_controller_lifecycle_gate: 2/2 ok ===")


if __name__ == "__main__":
    main()
