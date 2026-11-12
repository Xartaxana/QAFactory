"""Q04/Q08: collisions, exact identity joins, and typed sensitivity receipts."""
import json
import hashlib
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import case_versions as V
import contract as C
import ledger as L
from run_suite import build_run_block, reparse_run_block
from finalize_task import reduce
from red_sandbox import write_sensitivity_receipts


def case(path: Path, cid: str, body: str = "body", area: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    front = f"id: {cid}\n" + (f"area: {area}\n" if area else "")
    path.write_text(f"---\n{front}---\nPlan row: TS-1\n# {body}\n", encoding="utf-8")


class IdentityProof(unittest.TestCase):
    def test_collision_preflight_is_atomic(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            left, right = root / "a/TC-001.md", root / "b/TC-001.md"
            case(left, "TC-001", "left", area="billing")
            case(right, "TC-001", "right", area="billing")
            with self.assertRaisesRegex(ValueError, "case identity collision.*TC-001"):
                V.validate_batch([left, right])
            self.assertFalse((root / "store").exists())
            self.assertFalse((root / "task/state/story-case-links.json").exists())

    def test_two_areas_numbered_alike_are_two_cases(self):
        """`speakers/TC-001` and `speaker-detail/TC-001` coexisted on TP2-2536. Reading
        the number as the identity made them a collision to refuse here — and, downstream, one
        pinned link that replaced the other on recovery (FB-2428-1)."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            left, right = root / "speakers/TC-001.md", root / "speaker-detail/TC-001.md"
            case(left, "TC-001", "list")
            case(right, "TC-001", "detail")
            keys = [c["key"] for c in V.validate_batch([left, right])]
            self.assertEqual(sorted(keys), ["speaker-detail/TC-001", "speakers/TC-001"])

    def test_filename_and_frontmatter_must_match(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "TC-001.md"
            case(path, "TC-002")
            with self.assertRaisesRegex(ValueError, "identity mismatch"):
                V.validate_batch([path])

    def test_pinned_version_is_derived_from_bytes(self):
        with tempfile.TemporaryDirectory() as td:
            task = Path(td)
            snapshot = task / "state/case-versions/TC-1/cv_wrong.md"
            snapshot.parent.mkdir(parents=True)
            snapshot.write_text("---\nid: TC-1\n---\n", encoding="utf-8")
            digest = hashlib.sha256(snapshot.read_bytes()).hexdigest()
            (task / "state/story-case-links.json").write_text(json.dumps({"links": [{
                "case_id": "TC-1", "version": "cv_wrong", "content_hash": digest,
                "path": "state/case-versions/TC-1/cv_wrong.md"}]}), encoding="utf-8")
            self.assertTrue(any("not the content-addressed version" in issue
                                for issue in C.case_link_issues(task)))

    def test_parallel_pin_writer_is_rejected_before_read_modify_write(self):
        with tempfile.TemporaryDirectory() as td:
            task = Path(td)
            with V.task_link_lock(task):
                with self.assertRaisesRegex(RuntimeError, "active writer"):
                    with V.task_link_lock(task):
                        pass

    def test_failed_outcome_survives_missing_proof(self):
        entry = {"instance_id": "i1", "case": "TC-1", "file": "test.py", "marker": "test_one",
                 "critic_verdict": "approved", "new_or_changed": True}
        report = {"current_results": [{"instance_id": "i1", "attempt_id": "a1", "status": "failed"}]}
        state, _ = L.test_state(entry, report, {"triage": []})
        self.assertEqual("failed:untriaged", state)

    def test_truthy_string_is_not_sensitivity_proof(self):
        entry = {"instance_id": "i1", "sensitivity_proof": "red probe exists"}
        self.assertIn("typed receipt object", C.sensitivity_proof_issues(entry)[0])

    def test_sensitivity_receipt_ref_is_hash_bound(self):
        with tempfile.TemporaryDirectory() as td:
            task = Path(td)
            receipt = {"instance_id": "i1", "case_version": "cv_abc", "test_content_hash": "t",
                "source_revision": "s", "build_id": "b", "mutation": "remove guard",
                "expected_assertion_failure": "denied", "actual_failure": "denied",
                "assertion_location": "test.py:4", "restoration_evidence": "restored hash",
                "immutable": True, "receipt_hash": "receipt-id"}
            path = task / "work/sensitivity-receipts/i1.json"
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps(receipt), encoding="utf-8")
            entry = {"instance_id": "i1", "case_version_links": [{"version": "cv_abc"}],
                     "sensitivity_proof": {"receipt_ref": {"path": "work/sensitivity-receipts/i1.json",
                         "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}}}
            self.assertEqual([], C.sensitivity_proof_issues(entry, task))
            path.write_text("{}", encoding="utf-8")
            self.assertIn("hash does not match", C.sensitivity_proof_issues(entry, task)[0])

    def test_new_contract_requires_producer_receipt(self):
        with tempfile.TemporaryDirectory() as td:
            task = Path(td)
            (task / "state").mkdir()
            (task / "state/controller.json").write_text(json.dumps({"plan_contract_mode": "new"}), encoding="utf-8")
            binding = {"case_version": "cv_abc", "test_content_hash": "test-hash",
                       "source_revision": "source", "build_id": "build",
                       "restoration_evidence": "restored-hash"}
            target = {"instance_id": "i1", "expected_location": "test.py:4",
                      "expected_reason": "denied", "mutation_kind": "real_behavior"}
            result = {"instance_id": "i1", "status": "failed", "failure_kind": "assertion",
                      "location": "test.py:4", "reason": "denied", "semantic_verdict": "intended_failure"}
            refs = write_sensitivity_receipts(task, {"repo": str(task), "original_hashes": {},
                "targets": [target]}, [result], {"i1": binding})
            entry = {"instance_id": "i1", "case_version_links": [{"version": "cv_abc"}],
                     "sensitivity_proof": refs["i1"]}
            self.assertEqual([], C.sensitivity_proof_issues(entry, task))
            inline, _ = C.sensitivity_proof_receipt({"sensitivity_proof": json.loads(
                (task / refs["i1"]["receipt_ref"]["path"]).read_text())}, task)
            self.assertEqual({}, inline)

    def test_both_probes_write_receipts_the_contract_takes_and_each_names_its_level(self):
        """D-0010: red_sandbox's receipt says it caught a broken product, probe_by_code's says the
        check is live, and `sensitivity_proof_issues` takes both UNCHANGED, in the strictest
        contract mode (`plan_contract_mode: new`, an immutable receipt_ref or nothing)."""
        import probe_by_code as PBC
        import proof_level
        with tempfile.TemporaryDirectory() as td:
            task = Path(td)
            (task / "state").mkdir()
            (task / "state/controller.json").write_text(json.dumps({"plan_contract_mode": "new"}), encoding="utf-8")
            binding = {"case_version": "cv_abc", "test_content_hash": "test-hash",
                       "source_revision": "source", "build_id": "build", "restoration_evidence": "restored-hash"}
            target = {"instance_id": "i1", "expected_location": "test.py:4",
                      "expected_reason": "denied", "mutation_kind": "real_behavior"}
            result = {"instance_id": "i1", "status": "failed", "failure_kind": "assertion",
                      "location": "test.py:4", "reason": "denied", "semantic_verdict": "intended_failure"}
            refs = write_sensitivity_receipts(task, {"repo": str(task), "original_hashes": {},
                                                     "targets": [target]}, [result], {"i1": binding})
            product = json.loads((task / refs["i1"]["receipt_ref"]["path"]).read_text(encoding="utf-8"))
            self.assertEqual(("catches_broken_product", "red_sandbox.py"),
                             (product["proof_level"], product["probe_tool"]))
            self.assertEqual("catches_broken_product", proof_level.level_of(product))
            self.assertEqual([], C.sensitivity_proof_issues(
                {"instance_id": "i1", "case_version_links": [{"version": "cv_abc"}],
                 "sensitivity_proof": refs["i1"]}, task))
            live = {"instance_id": "i1", "case_version": "cv_abc", "test_content_hash": "test-hash",
                    "source_revision": "source", "build_id": "build", "mutation": "invert",
                    "expected_assertion_failure": "denied", "actual_failure": "denied",
                    "assertion_location": "test.py:4", "restoration_evidence": "probe_by_code: t.py sha256 x "
                    "verified restored", "failure_kind": "assertion", "proof_level": "live",
                    "probe_tool": "probe_by_code.py", "mutation_kind": "assertion", "probe_record": "work/probes/i1.json",
                    "evidence_refs": [], "obligation_ids": ["O-1"], "immutable": True}
            ref, note = PBC.write_receipt(task, live, "i1")
            self.assertEqual("", note)
            entry = {"instance_id": "i1", "case_version_links": [{"version": "cv_abc"}],
                     "sensitivity_proof": {"receipt_ref": ref}}
            self.assertEqual([], C.sensitivity_proof_issues(entry, task))
            self.assertEqual("live", proof_level.level_of(json.loads((task / ref["path"]).read_text(encoding="utf-8"))))
            inline, _ = C.sensitivity_proof_receipt({"sensitivity_proof": json.loads(
                (task / ref["path"]).read_text(encoding="utf-8"))}, task)
            self.assertEqual({}, inline)

    def test_exact_reporter_mapping_and_safe_reparse_metadata(self):
        request = {"purpose": "initial", "selected_instance_ids": ["i1"], "dispatch_id": "d1",
                   "profile_id": "p", "input_fingerprint": "f",
                   "fingerprint_components": {"source_sha": "s", "test_content_sha": "t", "config_sha": "c"},
                   "runtime_provenance": {}, "instance_contracts": {"i1": {
                       "report_test_id": "Namespace.Type.Test", "parameters": {"n": 1},
                       "case_version_links": [{"case_id": "TC-1", "version": "cv_abc"}],
                       "obligation_ids": ["O-1"]}}}
        summary = {"execution_status": "failed", "reporter": "trx", "report_hash": "rawhash",
                   "reparsed": True, "results": [{"test_id": "Namespace.Type.Test", "status": "failed"}]}
        block = build_run_block(request, summary, "a1")
        self.assertEqual("failed", block["results"][0]["status"])
        self.assertEqual("a1", block["reporter_mapping"]["source_attempt_id"])
        self.assertTrue(block["reporter_mapping"]["reparsed"])
        self.assertEqual(["O-1"], block["results"][0]["obligation_ids"])

    def test_reporter_evidence_and_manifest_identity_survive_reduction(self):
        with tempfile.TemporaryDirectory() as td:
            task = Path(td)
            (task / "work/run-blocks").mkdir(parents=True)
            (task / "evidence").mkdir()
            raw = task / "evidence/report.trx"
            raw.write_text("immutable reporter evidence", encoding="utf-8")
            digest = hashlib.sha256(raw.read_bytes()).hexdigest()
            manifest = {"tests": [
                {"instance_id": "i1", "case": "TC-1", "parameters": {"db": "pg"},
                 "case_version_links": [{"case_id": "TC-1", "version": "cv_one"}],
                 "obligation_ids": ["O-1"]},
                {"instance_id": "i2", "case": "TC-1", "parameters": {"db": "mysql"},
                 "case_version_links": [{"case_id": "TC-1", "version": "cv_one"}],
                 "obligation_ids": ["O-1"]}]}
            (task / "work/automation-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            request = {"purpose": "initial", "selected_instance_ids": ["i1", "unknown"],
                "dispatch_id": "d", "profile_id": "p", "input_fingerprint": "f",
                "fingerprint_components": {}, "runtime_provenance": {}, "instance_contracts": {
                    "i1": {"report_test_id": "Exact.One"}, "unknown": {"report_test_id": "Exact.Unknown"}}}
            summary = {"execution_status": "passed", "reporter": "trx",
                "report_evidence": {"path": "evidence/report.trx", "sha256": digest},
                "results": [{"test_id": "Exact.One", "status": "failed"},
                            {"test_id": "Exact.Unknown", "status": "passed"}]}
            block = build_run_block(request, summary, "a1")
            (task / "work/run-blocks/a1.json").write_text(json.dumps(block), encoding="utf-8")
            report, _ = reduce(task)
            current = {row["instance_id"]: row for row in report["current_results"]}
            self.assertEqual({"db": "pg"}, current["i1"]["parameters"])
            self.assertEqual("partial", current["unknown"]["status"])
            self.assertEqual("INSTANCE_MANIFEST_JOIN_FAILED", report["factory_findings"][0]["code"])
            raw.write_text("tampered", encoding="utf-8")
            report, _ = reduce(task)
            current = {row["instance_id"]: row for row in report["current_results"]}
            self.assertEqual("failed", current["i1"]["status"])
            self.assertEqual("unverified", current["i1"]["verification_status"])
            self.assertEqual("not_run", current["unknown"]["status"])

    def test_reparse_supersedes_mapping_without_new_attempt(self):
        with tempfile.TemporaryDirectory() as td:
            task = Path(td)
            (task / "work/run-blocks").mkdir(parents=True)
            (task / "evidence").mkdir()
            raw = task / "evidence/report.xml"
            raw.write_text('<testsuite tests="1" failures="0"><testcase classname="Suite" name="Exact"/></testsuite>', encoding="utf-8")
            digest = hashlib.sha256(raw.read_bytes()).hexdigest()
            (task / "work/automation-manifest.json").write_text(json.dumps({"tests": [
                {"instance_id": "i1", "parameters": {"db": "pg"}},
                {"instance_id": "i2", "parameters": {"db": "mysql"}}]}), encoding="utf-8")
            request = {"purpose": "initial", "selected_instance_ids": ["i1"], "dispatch_id": "d",
                "profile_id": "p", "instance_contracts": {"i1": {"report_test_id": "Wrong"}}}
            summary = {"execution_status": "passed", "reporter": "junit-xml",
                "report_evidence": {"path": "evidence/report.xml", "sha256": digest},
                "results": [{"test_id": "Suite::Exact", "status": "passed"}]}
            old = build_run_block(request, summary, "attempt-1")
            old_path = task / "work/run-blocks/old.json"
            old_path.write_text(json.dumps(old), encoding="utf-8")
            new_path = reparse_run_block(task, old_path,
                {"instance_contracts": {"i1": {"report_test_id": "Suite::Exact",
                                                  "report_id_source": "machine_report"}}})
            new = json.loads(new_path.read_text(encoding="utf-8"))
            self.assertEqual("attempt-1", new["attempt_id"])
            self.assertEqual(old["block_id"], new["supersedes_block_id"])
            unrelated = dict(old, block_id="other", attempt_id="attempt-2",
                             results=[dict(old["results"][0], instance_id="i2", attempt_id="attempt-2")])
            (task / "work/run-blocks/other.json").write_text(json.dumps(unrelated), encoding="utf-8")
            forged = dict(new, block_id="forged", supersedes_block_id="other")
            (task / "work/run-blocks/forged.json").write_text(json.dumps(forged), encoding="utf-8")
            report, _ = reduce(task)
            self.assertTrue(any(row["instance_id"] == "i2" for row in report["results"]))


if __name__ == "__main__":
    unittest.main()
