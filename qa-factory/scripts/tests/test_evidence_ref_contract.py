"""contract.evidence_ref_issue: a refusal about an evidence reference names the path, the
task root and the spelling that works. TP2-2553 section 1 was refused with the bare
words "missing or outside-task evidence" and spent a resume, a retry and two receipts on
finding out which reference and why.
"""
import hashlib
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import contract as C


class EvidenceRefTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="qa-evidence-"))
        (self.root / "work").mkdir()
        self.file = self.root / "work" / "receipt.json"
        self.file.write_bytes(b'{"ok": true}')
        self.sha = hashlib.sha256(self.file.read_bytes()).hexdigest()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.root, ignore_errors=True)

    def test_a_good_reference_has_no_issue(self):
        self.assertEqual(C.evidence_ref_issue(self.root, {"path": "work/receipt.json", "sha256": self.sha}), "")

    def test_a_missing_file_names_path_and_root(self):
        text = C.evidence_ref_issue(self.root, {"path": "work/gone.json", "sha256": "x"})
        self.assertIn("work/gone.json", text)
        self.assertIn(str(self.root.resolve()), text)
        self.assertIn("not a file", text)

    def test_an_absolute_path_under_the_root_offers_the_relative_spelling(self):
        text = C.evidence_ref_issue(self.root, {"path": str(self.file), "sha256": self.sha})
        self.assertIn("absolute", text)
        self.assertIn("work/receipt.json", text)

    def test_an_absolute_path_elsewhere_is_outside(self):
        other = Path(tempfile.gettempdir()) / "qa-evidence-elsewhere.json"
        text = C.evidence_ref_issue(self.root, {"path": str(other), "sha256": "x"})
        self.assertIn("outside the task root", text)

    def test_a_dotdot_path_escapes(self):
        text = C.evidence_ref_issue(self.root, {"path": "../outside.json", "sha256": "x"})
        self.assertIn("escapes", text)

    def test_a_stale_hash_is_stale_not_missing(self):
        text = C.evidence_ref_issue(self.root, {"path": "work/receipt.json", "sha256": "0" * 64})
        self.assertIn("stale sha256", text)
        self.assertNotIn("not a file", text)

    def test_a_shapeless_reference_is_named(self):
        self.assertIn("must be an object", C.evidence_ref_issue(self.root, "work/receipt.json"))
        self.assertIn("no path", C.evidence_ref_issue(self.root, {"sha256": "x"}))
        self.assertIn("no sha256", C.evidence_ref_issue(self.root, {"path": "work/receipt.json"}))

    def test_the_what_word_is_the_callers(self):
        text = C.evidence_ref_issue(self.root, {"path": "work/gone.json", "sha256": "x"}, what="policy evidence")
        self.assertTrue(text.startswith("policy evidence path"))


if __name__ == "__main__":
    unittest.main()
