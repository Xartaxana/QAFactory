"""contract.REMEDY_KINDS carries `reporter`: a runner that writes no parseable report is a
stand gap with the same four answers as a flag or a credential. TP2-2553 learned in
the middle of S5 that its Karma had no junit reporter; the gate A rehearsal proves it first.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import contract as C


class ReporterRemedyTests(unittest.TestCase):
    def test_reporter_is_a_remedy_kind(self):
        self.assertIn("reporter", C.REMEDY_KINDS)
        self.assertEqual(C.remedy_errors({"kind": "reporter", "where": "karma.conf.js:reporters",
                                          "change": "add 'junit' (karma-junit-reporter) and pass --reporters junit"}), [])

    def test_the_older_kinds_are_untouched(self):
        for kind in ("flag", "credential", "data", "service"):
            self.assertIn(kind, C.REMEDY_KINDS)
        self.assertTrue(C.remedy_errors({"kind": "runner", "where": "x", "change": "y"}))


if __name__ == "__main__":
    unittest.main()
