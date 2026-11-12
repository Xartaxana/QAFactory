"""Canonical migration and late-usage projection seams."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import contract
import cost_capture
from migrate_artifacts import migrate, plan
from benchmark_compare import compare
from reconcile_mutations import reconcile
from execution_fingerprint import verify_files, build as build_fingerprint
import hashlib


class StorageTests(unittest.TestCase):
    def test_migration_conflict_is_not_hidden(self):
        with tempfile.TemporaryDirectory() as td:
            task = Path(td)
            (task / "work").mkdir()
            (task / "triage.json").write_text("{}")
            (task / "work/triage.json").write_text('{"x":1}')
            with self.assertRaises(ValueError):
                contract.artifact(task, "triage.json")
            self.assertEqual(plan(task)["conflicts"], ["triage.json"])
            with self.assertRaises(ValueError):
                migrate(task)
            self.assertEqual((task / "triage.json").read_text(), "{}")

    def test_migration_repeat_keeps_canonical(self):
        with tempfile.TemporaryDirectory() as td:
            task = Path(td)
            (task / "triage.json").write_text("{}")
            migrate(task)
            self.assertEqual(migrate(task)["actions"], [])
            self.assertEqual(contract.artifact(task, "triage.json").read_text(), "{}")

    def test_late_usage_replaces_projection_without_story_dispatch(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            state = root / "qa-factory"
            state.mkdir()
            (state / "config.json").write_text("{}")
            transcript = root / "session.jsonl"
            def row(rid):
                return json.dumps({"type":"assistant","requestId":rid,
                  "timestamp":"2026-09-17T10:00:00Z", "message":{"model":"model-x", "usage":{"input_tokens":100}, "content":[]}})
            transcript.write_text(row("a") + "\n")
            with patch.object(cost_capture, "read_event", return_value={"transcript_path":str(transcript),"session_id":"s"}), patch.object(cost_capture,"state_dir",return_value=state), patch.object(cost_capture,"load_config",return_value={"cost":{"model_prices":{"model-x":{"input":1}}}}), patch("dashboard_refresh.refresh_project") as refresh:
                with self.assertRaises(SystemExit):
                    cost_capture.main()
                output = state / "state/cost/s.json"
                first = output.read_bytes()
                cost_capture.main()
                self.assertEqual(output.read_bytes(), first)
                self.assertEqual(refresh.call_count, 2)   # re-pinned by design (HF2-9 K2): an unchanged Stop renders too
                transcript.write_text(row("a") + "\n" + row("b") + "\n")
                with self.assertRaises(SystemExit):
                    cost_capture.main()
                self.assertEqual(json.loads(output.read_text())["by_model"]["model-x"]["requests"], 2)
                self.assertEqual(refresh.call_count, 3)   # re-pinned by design (HF2-9 K2)

    def test_crash_after_write_before_checkpoint_preserves_bytes(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            task=root / "task"
            (task / "state").mkdir(parents=True)
            source=root / "test.py"
            source.write_text("partial edit")
            state={"revision":2,"mutations":{"m":{"status":"writing","paths":[str(source)],
                   "before_hashes":{str(source):hashlib.sha256(b"before").hexdigest()}}}}
            (task / "state/controller.json").write_text(json.dumps(state))
            result=reconcile(task,[root])
            self.assertEqual(result["groups"][0]["files"][0]["status"],"changed_without_checkpoint")
            self.assertEqual(source.read_text(),"partial edit")
            self.assertEqual(result["groups"][0]["recorded_status"],"writing")

    def test_changed_actual_input_cannot_reuse_claimed_fingerprint(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/"helper.py"
            path.write_bytes(b"before")
            records=[{"path":str(path),"sha256":hashlib.sha256(b"before").hexdigest()}]
            self.assertTrue(verify_files(records))
            path.write_bytes(b"after")
            with self.assertRaises(ValueError):
                verify_files(records)

    def test_fresh_observation_of_same_build_does_not_change_fingerprint(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/"test.py"
            path.write_text("test content")
            runtime={"profile_id":"local","environment_id":"local","expected_source_revision":"sha",
                     "timestamp":"2026-09-17T10:00:00Z","result":"not_applicable","evidence_refs":[]}
            spec={"source_revision":"sha","test_files":[str(path)],"config_files":[str(path)],
                  "dependency_files":[],"runtime_provenance":runtime,"profile_id":"local"}
            before=build_fingerprint(spec)["input_fingerprint"]
            runtime["timestamp"]="2026-09-17T11:00:00Z"
            self.assertEqual(before,build_fingerprint(spec)["input_fingerprint"])

    def test_benchmark_rejects_missing_usage_and_quality_loss(self):
        before = dict(model_policy="p",scope_hash="s",environment="e",cache_policy="c",quality_corpus="q",usage_status="actual",cost_usd=10,evidence_refs=["usage"],verified_scope=["one"])
        after = dict(before, cost_usd=4)
        self.assertEqual(compare(before, after)["status"], "passed")
        self.assertEqual(compare(before, dict(after, usage_status="provisional"))["status"], "not_measured")
        self.assertEqual(compare(before, dict(after, verified_scope=[]))["status"], "quality_regression")


if __name__ == "__main__":
    unittest.main()
