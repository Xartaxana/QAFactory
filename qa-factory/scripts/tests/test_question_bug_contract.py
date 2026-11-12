"""contract.question_errors / bug_confirmation: a gate question carries what the source
says and at least two readings with their origin; a bug is unconfirmed until reproduced.
The shapes are TP1-15045's own: Q3 (removed node position) and BUG-1/BUG-2.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import contract as C


Q3 = {
    "id": "Q3",
    "question": "What does 'shown at its former position' mean for a removed node?",
    "source_says": [
        {"quote": "that node is shown at its former position in the graph with a red border",
         "where": "TP1-14482 acceptance criteria, AC-4"},
        {"quote": "the position of elements displayed in the diff does not correspond to the position of the real restoration state",
         "where": "TP1-14482 comment by the implementing developer, 2026-09-09"},
    ],
    "readings": [
        {"reading": "the same canvas coordinates as in the old revision",
         "from": "acceptance_criteria:AC-4",
         "if_chosen": "TC-004 Then 5 stands; the implementation violates AC-4"},
        {"reading": "the same place in the structure: same neighbours and edges, layout decided by auto-layout",
         "from": "comment:TP1-14482 2026-09-09",
         "if_chosen": "TC-004 Then 5 is rewritten to check neighbours and edges; no bug"},
    ],
    "severity": "major",
    "owner_role": "po_ba",
}


class QuestionTests(unittest.TestCase):
    def test_a_question_with_two_sourced_readings_is_answerable(self):
        self.assertEqual(C.question_errors(Q3), [])

    def test_the_fifteen_forty_five_wording_is_refused(self):
        legacy = {"question": "Where must a removed node appear when the YAML has no layout meta?",
                  "severity": "minor", "owner_role": "po_ba"}
        errors = C.question_errors(legacy)
        self.assertTrue(any("source_says" in e for e in errors), errors)
        self.assertTrue(any("fewer than two readings" in e for e in errors), errors)

    def test_a_reading_names_where_it_comes_from(self):
        bad = dict(Q3, readings=[dict(Q3["readings"][0], **{"from": "gut feeling"}), Q3["readings"][1]])
        self.assertTrue(any("readings[0].from" in e for e in C.question_errors(bad)))
        one = dict(Q3, readings=Q3["readings"][:1])
        self.assertTrue(any("fewer than two" in e for e in C.question_errors(one)))
        empty = dict(Q3, readings=[dict(Q3["readings"][0], if_chosen=""), Q3["readings"][1]])
        self.assertTrue(any("if_chosen is empty" in e for e in C.question_errors(empty)))
        self.assertEqual(C.question_errors("text"), ["question is not an object"])


class BugConfirmationTests(unittest.TestCase):
    def test_legacy_records_read_as_confirmed(self):
        self.assertEqual(C.bug_confirmation({"id": "BUG-1", "status": "Open"}), "confirmed_by_person")
        self.assertEqual(C.bug_confirmation(None), "confirmed_by_person")

    def test_the_closed_list(self):
        for value in C.BUG_CONFIRMATIONS:
            self.assertEqual(C.bug_confirmation({"confirmation": value}), value)
        # HF8-16 (K10, F-5): a word that is there and is not on the list reads one step DOWN, never as a person's word
        self.assertEqual(C.bug_confirmation({"confirmation": "maybe"}), "unconfirmed")
        self.assertEqual(C.bug_confirmation({"confirmation": "unknown"}), "unconfirmed")
        self.assertEqual(C.bug_confirmation({"confirmation": "  "}), "confirmed_by_person")
        self.assertIn("triage_ref", C.BUG_DRAFT_REQUIRED)
        self.assertIn("manual_steps", C.BUG_DRAFT_REQUIRED)


if __name__ == "__main__":
    unittest.main()
