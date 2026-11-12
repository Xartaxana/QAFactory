from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from event_store import content_hash
from planning_contract import VERIFICATION_DEPTHS, STARTER_LEVELS, validate_case_actions, publication_manifest, validate_plan, _validate_coverage_delta
from runtime_policy import cumulative_budget, retry_decision, resolve_model, checkpoint_due


class PlanningPolicyTests(unittest.TestCase):
    def test_coverage_delta_counts_cases_and_unique_instances(self):
        row = {"id": "TS-1", "coverage_obligations": [{"obligation_id": "O-1"}],
               "coverage_delta": {
                   "baseline_kind": "accepted",
                   "entries": [{"obligation_id": "O-1", "disposition": "strengthen",
                                "rationale": "add assertions to TC-1", "existing_case_refs": ["TC-1"]}],
                   "counts": {"logical_cases_before": 1, "logical_cases_after": 1,
                              "executable_instances_before": 2, "executable_instances_after": 2},
                   "planned_instance_ids": ["TC-1[a]", "TC-1[b]"]}}
        self.assertEqual(_validate_coverage_delta(row), [])
        row["coverage_delta"]["planned_instance_ids"][1] = "TC-1[a]"
        self.assertTrue(any("counted once" in e for e in _validate_coverage_delta(row)))

    def test_coverage_delta_blocks_hidden_growth_without_scope_decision(self):
        row = {"id": "TS-1", "coverage_obligations": [{"obligation_id": "O-1"}],
               "coverage_delta": {
                   "baseline_kind": "accepted",
                   "entries": [{"obligation_id": "O-1", "disposition": "gap",
                                "rationale": "existing case cannot observe audit", "gap_reason": "audit unavailable"}],
                   "counts": {"logical_cases_before": 1, "logical_cases_after": 2,
                              "executable_instances_before": 1, "executable_instances_after": 2},
                   "planned_instance_ids": ["TC-1", "TC-2"]}}
        self.assertTrue(any("accepted scope expansion" in e for e in _validate_coverage_delta(row)))
        row["coverage_delta"]["accepted_scope_expansion_ref"] = {
            "ref": "decision:GATE-A-7", "revision": "plan-r3"}
        self.assertEqual(_validate_coverage_delta(row), [])

    def test_initial_gate_a_can_approve_justified_new_scope(self):
        row = {"id": "TS-1", "coverage_obligations": [{"obligation_id": "O-1"}],
               "coverage_delta": {"baseline_kind": "initial",
                   "initial_scope_rationale": "no existing case observes requirement R-1",
                   "entries": [{"obligation_id": "O-1", "disposition": "gap",
                                "rationale": "bounded search found no reusable case",
                                "gap_reason": "new check awaits initial Gate A approval"}],
                   "counts": {"logical_cases_before": 0, "logical_cases_after": 1,
                              "executable_instances_before": 0, "executable_instances_after": 1},
                   "planned_instance_ids": ["planned:R-1"]}}
        self.assertEqual(_validate_coverage_delta(row), [])

    def test_manual_case_search_incomplete_blocks_create(self):
        action = {"scenario_id": "manual-1", "execution_mode": "agent-manual", "case_action": "create",
                  "rationale": "new oracle", "search_scope": "component", "search_snapshot_revision": "r1",
                  "search_completeness": "incomplete", "automation_action": "not_applicable",
                  "proposed_case_version": "v1"}
        self.assertTrue(validate_case_actions([action]))
        action["search_completeness"] = "complete"
        decision = {"action": "publish_cases", "status": "approved", "content_hash": content_hash([action]),
                    "destination": "project/suite", "authorization_source": "gate-A"}
        first = publication_manifest([action], decision, {})
        self.assertEqual(first, publication_manifest([action], decision, {}))
        action["case_action"] = "reuse"
        action["existing_case_refs"] = [{"id": "TMS-1", "revision": "v0"}]
        decision["content_hash"] = content_hash([action])
        with self.assertRaises(ValueError):
            publication_manifest([action], decision, {"TMS-1": "human-edited"})

    def test_unknown_impact_never_low(self):
        row = {"id": "P1", "impact": "unknown", "likelihood": "unknown", "confidence": "low",
               "risk_rationale": "source unavailable", "risk_source_refs": ["req1"],
               "risk_policy_revision": "v1", "coverage_refs": [], "unknowns": ["effect"],
               "verification_depth": "low", "required_scenarios": ["S1"],
               "test_level_rationale": "unit isolates contract", "design_review_required": False}
        self.assertTrue(validate_plan([row]))
        row.update(verification_depth="critical", design_review_required=True)
        self.assertEqual(validate_plan([row]), [])

    def test_starter_risk_requires_typed_evidence_and_its_declared_scale(self):
        self.assertTrue(validate_plan({"rows": []}))
        self.assertTrue(validate_plan(["low"]))
        row = {"id":"P", "impact":"severe", "likelihood":"low", "confidence":"high",
               "risk_rationale":"access control", "risk_source_refs":["R1"],
               "risk_policy_revision":"factory-starter-v1", "coverage_refs":[], "unknowns":[],
               "verification_depth":"critical", "required_scenarios":["C1"],
               "test_level_rationale":"contract boundary", "design_review_required":True}
        self.assertEqual(validate_plan([row]), [])
        self.assertTrue(validate_plan([dict(row, impact="tiny")]))
        self.assertTrue(validate_plan([dict(row, risk_source_refs="R1")]))
        self.assertTrue(validate_plan([dict(row, verification_depth="normal")]))

    def test_hard_quota_never_retries(self):
        self.assertFalse(retry_decision("ExceededBudget", 0, 100)["retry"])
        self.assertTrue(retry_decision("503", 0, 100)["retry"])
        self.assertFalse(retry_decision("503", 2, 100)["retry"])
        self.assertFalse(retry_decision("rate_limit_exceeded", 0, 100, 60)["retry"])

    def test_model_inherits_and_unsupported_override_blocks(self):
        parent = {"model": "host-model", "effort": "medium"}
        supported = {"host-model": ["medium"]}
        self.assertEqual(resolve_model("critic", parent, {}, {}, supported)["model"], "host-model")
        with self.assertRaises(ValueError):
            resolve_model("critic", parent, {"roles": {"critic": {"model": "absent"}}}, {}, supported)
        self.assertTrue(checkpoint_due("qa-code-critic", {"requests": 15})["checkpoint"])

    def test_cumulative_budget_cannot_reset_on_fresh_dispatch(self):
        result = cumulative_budget("qa-automator", {"requests": 38, "active_seconds": 100,
                                   "output_tokens": 500, "repair_cycles": 1},
                                   {"requests": 1, "active_seconds": 2,
                                    "output_tokens": 10, "repair_cycles": 0})
        self.assertTrue(result["checkpoint"])
        self.assertEqual(39, result["counters"]["requests"])

    def test_cumulative_budget_preserves_unknown_telemetry(self):
        result = cumulative_budget("qa-scout", {"requests": 1}, {"requests": 1})
        self.assertIsNone(result["counters"]["active_seconds"])
        self.assertIn("active_seconds", result["telemetry_unknown"])

    def test_cumulative_budget_enforces_repair_cap(self):
        result = cumulative_budget("qa-code-critic", {"requests": 1, "active_seconds": 1,
                                   "output_tokens": 1, "repair_cycles": 1},
                                   {"requests": 1, "active_seconds": 1,
                                    "output_tokens": 1, "repair_cycles": 1})
        self.assertTrue(result["checkpoint"])
        self.assertIn("repair_cycles", result["reasons"])

    def test_n2_invalid_verification_depth_names_low_normal_critical(self):
        errors = validate_plan([{"id": "TS-1", "verification_depth": "deep"}, {"id": "TS-2", "verification_depth": "deep"}])
        self.assertIn("TS-1: invalid verification depth (one of low, normal, critical)", errors)
        self.assertIn("TS-2: invalid verification depth (one of low, normal, critical)", errors)
        self.assertIn("TS-2: invalid verification depth", ' '.join(errors))      # the pinned prefix (test_plan_row.py:244)
        self.assertEqual(VERIFICATION_DEPTHS, ("low", "normal", "critical"))
        self.assertEqual(validate_plan([{"id": "TS-3", "verification_depth": "normal"}]).count(
            "TS-3: invalid verification depth (one of low, normal, critical)"), 0)

    def test_n2_invalid_starter_likelihood_names_its_list(self):
        row = {"id": "TS-1", "risk_policy_revision": "factory-starter-v1", "impact": "low",
               "likelihood": "very", "confidence": "sure", "verification_depth": "normal"}
        errors = validate_plan([row])
        self.assertIn("TS-1: invalid starter likelihood (one of low, medium, high, unknown)", errors)
        self.assertIn("TS-1: invalid starter confidence (one of low, medium, high, unknown)", errors)
        self.assertEqual(STARTER_LEVELS, ("low", "medium", "high", "unknown"))
        errors = validate_plan([dict(row, impact="huge", likelihood="low", confidence="low")])
        self.assertIn("TS-1: invalid starter impact (one of low, moderate, severe, unknown)", errors)
        # the register-class branch is unchanged
        errors = validate_plan([dict(row, impact="money", likelihood="low", confidence="low")])
        self.assertTrue(any("belongs in `impact_class`" in e for e in errors))
        self.assertFalse(any("invalid starter impact" in e for e in errors))


if __name__ == "__main__":
    unittest.main()
