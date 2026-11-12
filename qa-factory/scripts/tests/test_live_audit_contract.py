"""Regression tests for live-story audit findings, independent of an application."""
import sys
import unittest
import tempfile
import json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from runtime_policy import cumulative_budget, warning_milestones
from env_probe import integration_readiness


class LiveAuditContracts(unittest.TestCase):
    def test_large_discovery_never_hard_blocks(self):
        counters = dict(output_tokens=74700, active_seconds=1900, requests=80, repair_cycles=0)
        result = cumulative_budget("qa-scout", dict.fromkeys(counters, 0), counters)
        self.assertTrue(result["checkpoint"])
        self.assertFalse(result["blocking"])
        notices = warning_milestones(counters)
        self.assertIn("output_tokens:72000", notices["new_markers"])
        self.assertFalse(warning_milestones(counters, emitted=notices["emitted"])["warning"])

    def test_repair_bound_is_independent_of_soft_discovery(self):
        counters = dict(output_tokens=2, active_seconds=1, requests=1, repair_cycles=2)
        self.assertTrue(cumulative_budget("qa-case-designer", dict.fromkeys(counters, 0), counters)["blocking"])

    def test_legacy_integration_does_not_demand_all_three_keys(self):
        spec = dict(name="aws-parameter-store", keys=["A", "B", "PROFILE"])
        result = integration_readiness(spec, {})
        self.assertEqual(result["status"], "unknown")
        self.assertIn("applicability", result["reason"])

    def test_alternative_presence_does_not_prove_access(self):
        spec = dict(applicability="required", credential_alternatives=[["A", "B"], ["PROFILE"]])
        self.assertEqual(integration_readiness(spec, {"PROFILE": "yes"})["status"], "unknown")
        self.assertEqual(integration_readiness(spec, {})["status"], "missing")
        spec["environments"] = ["preview"]
        self.assertEqual(integration_readiness(spec, {}, "local")["status"], "not_required")

class BaselineContracts(unittest.TestCase):
    def test_baseline_never_produces_green_product_block(self):
        from run_suite import build_run_block
        self.assertIsNone(build_run_block({"evidence_phase": "baseline"}, {}, "attempt"))

    def test_baseline_requires_old_build_and_approval(self):
        from baseline_contract import validate_baseline_request
        request = {"evidence_phase": "baseline", "runtime_provenance": {"expected_source_revision": "old"},
                   "baseline_contract": {"case_id": "TC-1", "case_version": "v1", "baseline_revision": "old",
                     "verification_revision": "new", "fixture_identity": "seed1", "gate_a_decision_ref": "A1",
                     "reason": "before/after", "execution_scope": "current_task", "capture_steps": ["open"],
                     "comparison_assertions": ["compare graph"], "capture_artifact_refs": ["evidence/before.json"]}}
        self.assertEqual(validate_baseline_request(request), [])
        request["runtime_provenance"]["expected_source_revision"] = "new"
        self.assertTrue(validate_baseline_request(request))

    def test_windows_process_identity_survives_timestamp_format_upgrade(self):
        from unittest.mock import patch
        import run_suite
        with patch.object(run_suite, "process_started_at", return_value="2026-09-19T01:00:00.123456+00:00"):
            self.assertTrue(run_suite.same_process(42, "2026-09-19T01:00:00.1234567Z"))
            self.assertFalse(run_suite.same_process(42, "2026-09-19T01:00:01.1234567Z"))

    def test_environment_does_not_use_array_order(self):
        from environment_selection import select_environment
        cfg = {"environments": [{"name": "first"}, {"name": "second"}]}
        self.assertEqual(select_environment(cfg)["status"], "question_required")
        self.assertEqual(select_environment(cfg, saved="second")["environment_id"], "second")

class PacketIntegration(unittest.TestCase):
    def test_builder_hashes_output_and_patch_does_not_overwrite_on_conflict(self):
        from controller import Controller
        from artifact_packet import patch_document, skeleton
        from event_store import atomic_json
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "qa-factory").mkdir()
            (root / "qa-factory/config.json").write_text("{}", encoding="utf-8")
            atomic_json(root / "work/source.json", {"facts": [{"id": "F-1", "value": "full source"}]})
            result = skeleton(root, {"source": "work/source.json", "path": "work/draft.json", "copy_keys": ["facts"]})
            self.assertEqual(json.loads((root / "work/draft.json").read_text())["copied"]["facts"][0]["value"], "full source")
            request = {"path": "work/draft.json", "expected_hash": result["content_hash"],
                       "changes": [{"keys": ["semantic_decisions"], "value": {"F-1": "needs review"}}]}
            patch_document(root, request)
            with self.assertRaises(ValueError): patch_document(root, request)
            packet = Controller(root).prepare({"dispatch_id": "D1", "outputs": ["work/draft.json"]})
            self.assertEqual(len(packet["accept_request"]["evidence_refs"][0]["sha256"]), 64)
            self.assertFalse((root / "state/events.jsonl").exists())
            with self.assertRaises(ValueError):
                Controller(root).prepare({"dispatch_id": "D1", "outputs": ["../outside.json"]})

    def test_large_handoff_retains_facts_and_detects_same_id_changes(self):
        from context_bundle import build
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            manifest = {"ticket": "QA-1", "implementations": [{"repo_id": "app", "source_sha": "abc"}],
                        "changed_areas": ["src"], "coverage_status": "not_found", "constraints": [],
                        "facts": [{"id": f"F-{n}", "value": "old"} for n in range(501)]}
            before = build(manifest, root)
            manifest["facts"][500]["value"] = "new"
            after = build(manifest, root, before)
            self.assertEqual(len(after["facts"]), 501)
            self.assertEqual(len(after["fact_pages"]), 2)
            self.assertEqual(after["delta"]["added_or_changed_ids"], ["F-500"])

if __name__ == "__main__":
    unittest.main()
