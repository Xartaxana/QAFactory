"""contract: obligation ids join the plan, a receipt is found through its binding, and the
delivery manifest knows which records the factory rewrites after S8. The shapes are
TP2-2553's own: plan `TS-1-O1`, manifest `OB-1`, receipts in bindings only.
"""
import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import contract as C


def _plan(rows):
    return {"rows": rows}


def _row(row_id, *oids):
    return {"id": row_id, "schema_version": 2,
            "coverage_obligations": [{"obligation_id": oid} for oid in oids]}


class ObligationIdTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="qa-obligation-")
        self.root = Path(self.tmp.name) / "TP2-2553"
        (self.root / "work").mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def _write_plan(self, rows):
        (self.root / "work" / "test-plan.json").write_text(json.dumps(_plan(rows)), encoding="utf-8")

    def test_plan_order_is_the_order(self):
        self._write_plan([_row("TS-1", "TS-1-O1", "TS-1-O2"), _row("TS-2", "TS-2-O1"),
                          {"id": "TS-3", "schema_version": 1}])
        self.assertEqual(C.plan_obligation_ids(self.root), ["TS-1-O1", "TS-1-O2", "TS-2-O1"])
        self.assertEqual([r for r, _ in C.plan_obligations(self.root)], ["TS-1", "TS-1", "TS-2"])

    def test_the_manifest_spelling_of_2553_is_unknown(self):
        self._write_plan([_row("TS-1", "TS-1-O1", "TS-1-O2"), _row("TS-2", "TS-2-O1")])
        self.assertEqual(C.unknown_obligation_ids(["OB-1", "TS-1-O2", "OB-9"], self.root), ["OB-1", "OB-9"])
        self.assertEqual(C.unknown_obligation_ids([], self.root), [])

    def test_a_legacy_plan_refuses_nothing(self):
        self._write_plan([{"id": "TS-1", "schema_version": 1}])
        self.assertEqual(C.unknown_obligation_ids(["OB-1"], self.root), [])
        self.assertEqual(C.unknown_obligation_ids(["OB-1"], self.root / "nowhere"), [])

    def test_ob_n_maps_by_position(self):
        self._write_plan([_row("TS-1", "TS-1-O1", "TS-1-O2"), _row("TS-2", "TS-2-O1")])
        mapping = C.legacy_obligation_map(self.root)
        self.assertEqual(mapping, {"OB-1": "TS-1-O1", "OB-2": "TS-1-O2", "OB-3": "TS-2-O1"})
        self.assertNotIn("OB-4", mapping)
        self.assertTrue(C.LEGACY_OBLIGATION_RE.match("OB-12"))
        self.assertFalse(C.LEGACY_OBLIGATION_RE.match("TS-1-O1"))


class BindingReceiptTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="qa-receipt-")
        self.root = Path(self.tmp.name) / "TP2-2553"
        receipts = self.root / "work" / "sensitivity-receipts"
        receipts.mkdir(parents=True)
        self.receipt = receipts / "test_list_default-abcd.json"
        self.receipt.write_text('{"instance_id": "test_list[default]"}', encoding="utf-8")
        self.sha = hashlib.sha256(self.receipt.read_bytes()).hexdigest()
        self.entry = {"case": "TC-001", "test_function": "test_list", "parameter": "default"}
        self.manifest = {"obligation_bindings": [
            {"obligation_id": "TS-1-O1", "instance_ids": ["TC-001::test_list[default]"],
             "sensitivity": "proven", "probe_receipt_ref": "work/sensitivity-receipts/test_list_default-abcd.json"}]}

    def tearDown(self):
        self.tmp.cleanup()

    def test_the_binding_names_the_receipt_under_any_spelling(self):
        ref = C.binding_receipt_ref(self.manifest, self.entry, self.root)
        self.assertEqual(ref, {"path": "work/sensitivity-receipts/test_list_default-abcd.json",
                               "sha256": self.sha, "obligation_id": "TS-1-O1"})
        filled, oid = C.with_binding_receipt(self.entry, self.manifest, self.root)
        self.assertEqual(oid, "TS-1-O1")
        self.assertEqual(filled["sensitivity_proof"]["receipt_ref"]["sha256"], self.sha)
        self.assertNotIn("sensitivity_proof", self.entry)

    def test_a_row_that_carries_its_own_ref_is_left_alone(self):
        own = dict(self.entry, sensitivity_proof={"receipt_ref": {"path": "x", "sha256": "y"}})
        self.assertEqual(C.with_binding_receipt(own, self.manifest, self.root), (own, ""))

    def test_no_binding_no_file_no_ref(self):
        self.assertEqual(C.binding_receipt_ref({}, self.entry, self.root), {})
        unproven = {"obligation_bindings": [dict(self.manifest["obligation_bindings"][0], sensitivity="missing")]}
        self.assertEqual(C.binding_receipt_ref(unproven, self.entry, self.root), {})
        self.receipt.unlink()
        self.assertEqual(C.binding_receipt_ref(self.manifest, self.entry, self.root), {})
        self.assertEqual(C.with_binding_receipt(self.entry, self.manifest, self.root), (self.entry, ""))

    def test_an_escaping_path_is_never_hashed(self):
        outside = {"obligation_bindings": [dict(self.manifest["obligation_bindings"][0],
                                                probe_receipt_ref="../../outside.json")]}
        self.assertEqual(C.binding_receipt_ref(outside, self.entry, self.root), {})


class BindingSelectionTests(unittest.TestCase):
    """B-313: an instance gets the receipt of an obligation it declares, never a sibling's."""

    INSTANCE = "TC-001::test_list[default]"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="qa-receipt-select-")
        self.root = Path(self.tmp.name) / "TP2-2406"
        (self.root / "work" / "sensitivity-receipts").mkdir(parents=True)
        for name in ("stale", "first", "second"):
            self._receipt(name)

    def tearDown(self):
        self.tmp.cleanup()

    def _receipt(self, name):
        path = self.root / "work" / "sensitivity-receipts" / f"{name}.json"
        path.write_text(json.dumps({"receipt": name}), encoding="utf-8")
        return f"work/sensitivity-receipts/{name}.json"

    def _binding(self, oid, name, **extra):
        return dict({"obligation_id": oid, "instance_ids": [self.INSTANCE], "sensitivity": "proven",
                     "probe_receipt_ref": f"work/sensitivity-receipts/{name}.json"}, **extra)

    def _entry(self, **extra):
        return dict({"case": "TC-001", "test_function": "test_list", "parameter": "default"}, **extra)

    def test_a_stale_sibling_listed_first_does_not_shadow_the_declared_obligation(self):
        manifest = {"obligation_bindings": [self._binding("OB-STALE", "stale"),
                                            self._binding("TS-1-O1", "first")]}
        entry = self._entry(obligation_refs=[{"obligation_id": "TS-1-O1"}])
        ref = C.binding_receipt_ref(manifest, entry, self.root)
        self.assertEqual((ref["path"], ref["obligation_id"]),
                         ("work/sensitivity-receipts/first.json", "TS-1-O1"))

    def test_two_exact_candidates_the_proof_path_picks_the_second(self):
        manifest = {"obligation_bindings": [self._binding("TS-1-O1", "first"),
                                            self._binding("TS-1-O2", "second")]}
        entry = self._entry(obligation_refs=[{"obligation_id": "TS-1-O1"}],
                            obligation_ids=["TS-1-O2"],
                            sensitivity_proof={"receipt_ref": {"path": "work/sensitivity-receipts/second.json"}})
        self.assertEqual(C.binding_receipt_ref(manifest, entry, self.root)["obligation_id"], "TS-1-O2")
        # no proof, or a proof without a ref, or a ref naming no candidate: manifest order
        for proof in (None, {}, {"receipt_ref": {"path": "work/sensitivity-receipts/stale.json"}}):
            probe = dict(entry)
            probe.pop("sensitivity_proof")
            if proof is not None:
                probe["sensitivity_proof"] = proof
            self.assertEqual(C.binding_receipt_ref(manifest, probe, self.root)["obligation_id"], "TS-1-O1")

    def test_declared_but_none_exact_is_no_receipt(self):
        manifest = {"obligation_bindings": [self._binding("OB-STALE", "stale")]}
        for entry in (self._entry(obligation_refs=[{"obligation_id": "TS-1-O1"}]),
                      self._entry(obligation_ids=["TS-1-O1"])):
            self.assertEqual(C.binding_receipt_ref(manifest, entry, self.root), {})
            self.assertEqual(C.with_binding_receipt(entry, manifest, self.root), (entry, ""))

    def test_nothing_declared_keeps_first_wins(self):
        manifest = {"obligation_bindings": [self._binding("OB-STALE", "stale"),
                                            self._binding("TS-1-O1", "first")]}
        for entry in (self._entry(), self._entry(obligation_refs=[], obligation_ids=[]),
                      self._entry(obligation_refs=["not-a-dict", {"no_id": 1}, {"obligation_id": ""}])):
            ref = C.binding_receipt_ref(manifest, entry, self.root)
            self.assertEqual(ref["obligation_id"], "OB-STALE")

    def test_an_ob_n_spelling_is_resolved_through_the_plan_map(self):
        (self.root / "work" / "test-plan.json").write_text(
            json.dumps(_plan([_row("TS-1", "TS-1-O1", "TS-1-O2")])), encoding="utf-8")
        # the binding says OB-2, the entry says what the plan says: they are one obligation
        manifest = {"obligation_bindings": [self._binding("OB-STALE", "stale"),
                                            self._binding("OB-2", "second")]}
        entry = self._entry(obligation_refs=[{"obligation_id": "TS-1-O2"}])
        ref = C.binding_receipt_ref(manifest, entry, self.root)
        self.assertEqual((ref["path"], ref["obligation_id"]),
                         ("work/sensitivity-receipts/second.json", "OB-2"))
        # and the other way round: the entry carries the legacy spelling
        manifest = {"obligation_bindings": [self._binding("OB-STALE", "stale"),
                                            self._binding("TS-1-O2", "second")]}
        entry = self._entry(obligation_ids=["OB-2"])
        self.assertEqual(C.binding_receipt_ref(manifest, entry, self.root)["obligation_id"], "TS-1-O2")

    def test_an_ob_n_with_no_mapping_is_compared_as_written(self):
        manifest = {"obligation_bindings": [self._binding("OB-STALE", "stale"),
                                            self._binding("OB-9", "second")]}
        entry = self._entry(obligation_refs=[{"obligation_id": "OB-9"}])
        self.assertEqual(C.binding_receipt_ref(manifest, entry, self.root)["obligation_id"], "OB-9")
        entry = self._entry(obligation_refs=[{"obligation_id": "OB-8"}])
        self.assertEqual(C.binding_receipt_ref(manifest, entry, self.root), {})


class LevelledReceiptTests(unittest.TestCase):
    """D-0010: a receipt reached through its binding has a level, and the reader that says which
    (`proof_level.reached`) uses the contract's own two lookups, never a third."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="qa-level-receipt-")
        self.root = Path(self.tmp.name) / "T-1"
        (self.root / "work" / "sensitivity-receipts").mkdir(parents=True)
        # t-016 Amendment 2: a row's current bytes are read from its test file under the project,
        # so the row names a real file and the receipt binds its raw sha256.
        import hooklib
        project = Path(self.tmp.name) / "project"
        (project / "qa-factory").mkdir(parents=True)
        (project / "qa-factory" / "config.json").write_text("{}", encoding="utf-8")
        (project / "tests").mkdir()
        test_file = project / "tests" / "test_one.py"
        test_file.write_text("def test_one():\n    assert 1 == 1\n", encoding="utf-8")
        self._env = os.environ.get("CLAUDE_PROJECT_DIR")
        os.environ["CLAUDE_PROJECT_DIR"] = str(project)
        hooklib._PROJECT_ROOT_CACHE = None
        self.entry = {"instance_id": "i1", "case": "TC-1", "covers": ["TC-1"], "new_or_changed": True,
                      "file": "tests/test_one.py",
                      "case_version_links": [{"case_id": "TC-1", "version": "cv_a"}]}
        raw = hashlib.sha256(test_file.read_bytes()).hexdigest()
        body = {"instance_id": "i1", "case_version": "cv_a", "test_content_hash": raw, "source_revision": "s",
                "build_id": "b", "mutation": "invert", "expected_assertion_failure": "e", "actual_failure": "e",
                "assertion_location": "t.py:1", "restoration_evidence": "r", "failure_kind": "assertion",
                "proof_level": "live", "probe_tool": "probe_by_code.py", "mutation_kind": "assertion",
                "evidence_refs": [], "immutable": True, "receipt_hash": "h" * 64}
        self.path = self.root / "work" / "sensitivity-receipts" / "i1-live-0123456789abcdef.json"
        self.path.write_text(json.dumps(body), encoding="utf-8")
        self.rel = "work/sensitivity-receipts/i1-live-0123456789abcdef.json"
        self.manifest = {"tests": [self.entry], "obligation_bindings": [
            {"obligation_id": "OB-1", "instance_ids": ["i1"], "sensitivity": "proven",
             "probe_receipt_ref": self.rel}]}

    def tearDown(self):
        import hooklib
        if self._env is None:
            os.environ.pop("CLAUDE_PROJECT_DIR", None)
        else:
            os.environ["CLAUDE_PROJECT_DIR"] = self._env
        hooklib._PROJECT_ROOT_CACHE = None
        self.tmp.cleanup()

    def test_the_live_receipt_is_valid_under_the_contract_unchanged(self):
        filled, oid = C.with_binding_receipt(self.entry, self.manifest, self.root)
        self.assertEqual(oid, "OB-1")
        self.assertEqual([], C.sensitivity_proof_issues(filled, self.root))

    def test_reached_through_the_binding_alone(self):
        import proof_level
        got = proof_level.reached(self.entry, self.manifest, self.root)
        self.assertEqual((got["level"], got["words"], got["issues"]), ("live", "the check is live", []))
        self.assertEqual(got["ref"]["path"], self.rel)

    def test_the_same_path_on_the_row_and_the_binding_is_one_receipt(self):
        import proof_level
        sha = hashlib.sha256(self.path.read_bytes()).hexdigest()
        row = dict(self.entry, sensitivity_proof={"receipt_ref": {"path": self.rel, "sha256": sha}})
        got = proof_level.reached(row, self.manifest, self.root)
        self.assertEqual((got["level"], got["issues"]), ("live", []))

    def test_an_unproven_binding_and_another_instances_receipt_reach_nothing(self):
        import proof_level
        unproven = {"obligation_bindings": [dict(self.manifest["obligation_bindings"][0], sensitivity="missing")]}
        got = proof_level.reached(self.entry, unproven, self.root)
        self.assertEqual((got["level"], got["issues"]), (None, ["no sensitivity receipt"]))
        other = dict(self.entry, instance_id="i2")
        got = proof_level.reached(other, {"obligation_bindings": [dict(
            self.manifest["obligation_bindings"][0], instance_ids=["i2"])]}, self.root)
        self.assertEqual(got["level"], None)
        self.assertIn("does not match the manifest instance", " ".join(got["issues"]))


class DeliveryVocabularyTests(unittest.TestCase):
    def test_the_words_exist(self):
        self.assertEqual(C.SUPERSEDED_BY_RERUN, "superseded_by_rerun")
        for path in ("state/events.jsonl", "work/ledger.json", "work/ledger.md", "work/automation-manifest.json"):
            self.assertIn(path, C.DELIVERY_VOLATILE_PATHS)


if __name__ == "__main__":
    unittest.main()
