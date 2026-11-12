import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from candidate_evidence import assess_candidate


class CandidateEvidenceTests(unittest.TestCase):
    def test_test_assertions_must_resolve_in_the_declared_test_file(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); path = root / "tests" / "test_feature.py"; path.parent.mkdir()
            path.write_text("def test_feature():\n    assert answer == 1\n", encoding="utf-8")
            good = {"kind": "test", "path": "tests/test_feature.py", "selector": "test_feature",
                    "execution_boundary": "component", "channel": "api", "runtime": "python",
                    "framework": "unittest", "ownership": "development-repository",
                    "assertion_refs": ["tests/test_feature.py:2"]}
            result = assess_candidate(good, root)
            self.assertTrue(result["executable"]); self.assertEqual(result["assertion_status"], "sufficient")
            bad = dict(good, assertion_refs=["src/feature.py:2"])
            self.assertEqual(assess_candidate(bad, root)["assertion_status"], "unknown")
            mixed = dict(good, assertion_refs=["tests/test_feature.py:2#test_feature", "tests/test_feature.py:9"])
            self.assertEqual(assess_candidate(mixed, root)["assertion_status"], "unknown")
            implementation = dict(good, implementation_refs=["tests/test_feature.py:2"])
            self.assertEqual(assess_candidate(implementation, root)["assertion_status"], "unknown")
            placeholder = dict(good, selector="unknown")
            self.assertFalse(assess_candidate(placeholder, root)["executable"])
            unknown_boundary = dict(good, execution_boundary="unknown")
            self.assertEqual(assess_candidate(unknown_boundary, root)["assertion_status"], "unknown")
            self.assertEqual(result["ownership"], "development-repository")

    def test_helper_and_unexpanded_suite_never_count_as_executable(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); path = root / "tests" / "helpers.py"; path.parent.mkdir()
            path.write_text("def check():\n    assert True\n", encoding="utf-8")
            helper = {"kind": "helper", "path": "tests/helpers.py", "selector": "check",
                      "execution_boundary": "component",
                      "assertion_refs": ["tests/helpers.py:2"]}
            suite = {"kind": "suite", "path": "tests/helpers.py", "selector": "suite",
                     "execution_boundary": "component",
                     "assertion_refs": ["tests/helpers.py:2"]}
            self.assertFalse(assess_candidate(helper, root)["executable"])
            self.assertFalse(assess_candidate(suite, root)["executable"])


if __name__ == "__main__":
    unittest.main()
