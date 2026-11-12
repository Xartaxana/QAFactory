"""Cross-component acceptance, source and recovery seams."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import unittest.mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import mark_project
from controller import Controller
from red_sandbox import prepare, verify
from acceptance import validate_window
from source_preflight import assess_freshness
import hooklib


class LifecycleTests(unittest.TestCase):
    def test_checkpoint_cannot_accept_and_retry_supersedes(self):
        with tempfile.TemporaryDirectory() as td:
            mark_project(Path(td))
            c = Controller(td)
            c.apply("initialize", {"scope": ["one"], "source_revision": "a", "known_paths": {"root": td},
                                   "idempotency_key": "init"})
            request = {"id": "d1", "stage": "S0", "role": "qa-scout", "scope": ["one"],
                       "input_hash": "h", "budget": {}, "known_paths": {}, "idempotency_key": "d1"}
            c.apply("dispatch", request)
            with self.assertRaises(ValueError):
                c.apply("checkpoint", {"id": "d1", "status": "accepted", "checkpoint": {"remaining": []},
                                       "reason": "fake done", "idempotency_key": "bad"})
            c.apply("checkpoint", {"id": "d1", "status": "paused", "checkpoint": {"remaining": ["one"]},
                                   "reason": "503", "idempotency_key": "cp"})
            request.update(id="d2", parent_retry="d1", checkpoint={"remaining": ["one"]}, idempotency_key="d2")
            c.apply("dispatch", request)
            self.assertEqual(c.state()["dispatches"]["d1"]["status"], "superseded")
            self.assertEqual(c.next_action()["dispatch_id"], "d2")

    def test_typecheck_failure_not_hidden_by_green_product(self):
        record = {"input_hash": "h", "required_quality_checks": ["tsc"],
                  "quality_receipts": [{"id": "tsc", "input_hash": "h", "status": "failed"}],
                  "instances": [{"instance_id": "i", "outcome": "passed", "input_hash": "h",
                                  "review": {"verdict": "approved", "input_hash": "h"}}]}
        # HF4-10 (t-1480): only a check some factory script produces a receipt for is demanded; the data names `tsc`
        import window_record
        with tempfile.TemporaryDirectory() as td:
            producers = Path(td) / "quality-producers.json"
            producers.write_text(json.dumps({"schema_version": 1, "producers": {"tsc": "tsc_receipt.py"}, "why": {}}),
                                 encoding="utf-8")
            with unittest.mock.patch.object(window_record, "QUALITY_PRODUCERS_FILE", producers):
                self.assertEqual(validate_window(record, Path.cwd()),
                                 ["change_disposition:i", "evidence:i", "quality:tsc"])

    def test_red_uses_uncommitted_bytes_and_wrong_failure_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "repo"
            repo.mkdir()
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            test = repo / "test.py"
            test.write_text("assert 1 == 1\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(repo), "add", "test.py"], check=True)
            test.write_text("assert 2 == 2\n", encoding="utf-8")
            before = test.read_bytes()
            receipt = prepare(repo, Path(td) / "probe", {"mutations": [{"path": "test.py",
                "instance_id": "i", "before_sha256": hashlib.sha256(before).hexdigest(),
                "replacement_utf8": "assert 2 == 3\n", "expected_location": "test.py:1", "expected_reason": "2 != 3"}]})
            self.assertEqual(test.read_bytes(), before)
            self.assertEqual(verify(receipt, [{"instance_id": "i", "status": "failed", "failure_kind": "import"}])["status"], "incomplete")
            self.assertEqual(verify(receipt, [{"instance_id": "i", "status": "failed", "failure_kind": "assertion",
                "location": "test.py:1", "reason": "2 != 3", "semantic_verdict": "intended_failure"}])["status"], "accepted")

    def test_freshness_does_not_run_regression_or_undeployed_code(self):
        old = {"source": "a", "requirements_revision": "r"}
        new = dict(old, source="b")
        self.assertEqual(assess_freshness(old, old, "matched", ["i"])["action"], "reuse")
        self.assertEqual(assess_freshness(old, new, "mismatched", ["i"])["selected"], [])
        decision = assess_freshness(old, new, "matched", ["i"], ["i", "regression"])
        self.assertEqual(decision["selected"], ["i"])
        self.assertEqual(decision["regression_recommendations"], ["regression"])

    def test_custom_artifact_root_and_path_escape(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "qa-factory").mkdir()
            (root / "qa-factory/config.json").write_text(json.dumps({"artifact_root": "quality/tasks"}))
            self.assertEqual(hooklib.artifact_root(root=root), root.resolve() / "quality/tasks")
            with self.assertRaises(ValueError):
                hooklib.artifacts_dir("../other")


if __name__ == "__main__":
    unittest.main()
