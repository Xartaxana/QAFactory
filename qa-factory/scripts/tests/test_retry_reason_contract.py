"""contract.retry_reason_for: the closed list a resumed dispatch names, classified from
the parent's checkpoint wording. The cases are the ten real retries of TP1-15045 (0.7.13
Factory tab: "retry dispatches: 10 - parents (10)" and not one reason), plus the host and
person cases the list was made for.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import contract as C


def parent(status, reason):
    return {"status": status, "reason": reason}


class RetryReasonTests(unittest.TestCase):
    def test_the_fifteen_forty_five_wording(self):
        cases = [
            (parent("superseded", "source review awaiting the person"), "awaiting_person"),
            (parent("superseded", "understanding blocked: 1 blocking question (AC-6 oracle) awaiting the person"), "awaiting_person"),
            (parent("superseded", "test toolchain was not installed; now installed via poetry install; non-owner credentials supplied by the person"), "environment"),
            (parent("superseded", "window ran out of turn budget mid-diagnosis of TC-001 live load timeout"), "turn_budget"),
            (parent("superseded", "turn-budget guard fired at 780 to 810 calls mid red probe"), "turn_budget"),
            (parent("superseded", "window budget exhausted after TC-007 and TC-008 work"), "turn_budget"),
            (parent("superseded", "node_ids.py collect-only parser breaks under pytest.ini addopts=-v: run_suite.py --mine cannot launch"), "factory_defect"),
            (parent("incomplete", "11/11 real instances fresh-green under 0.7.8; all fixable smells fixed+reverified"), "checkpoint"),
            (parent("incomplete", "manifest structural fix applied (tests[17..23] missing case field)"), "checkpoint"),
        ]
        for record, expected in cases:
            self.assertEqual(C.retry_reason_for(record), expected, record["reason"])

    def test_host_person_and_silence(self):
        self.assertEqual(C.retry_reason_for(parent("blocked", "getaddrinfo ENOTFOUND api.example")), "host_error:ENOTFOUND")
        self.assertEqual(C.retry_reason_for(parent("blocked", "launcher exit code 137")), "host_error:137")
        self.assertEqual(C.retry_reason_for(parent("never_started", "")), "subagent_silent")
        self.assertEqual(C.retry_reason_for(parent("incomplete", "the role stopped without acceptance")), "subagent_silent")
        self.assertEqual(C.retry_reason_for(parent("incomplete", "exited with no digest")), "no_digest_at_exit")
        self.assertEqual(C.retry_reason_for(parent("incomplete", "context compacted mid window")), "compaction")
        self.assertEqual(C.retry_reason_for(parent("returned_unaccepted", "digest present")), "unaccepted_result")
        self.assertEqual(C.retry_reason_for(parent("blocked", "anything"), words="run it again"), "person_word")
        self.assertEqual(C.retry_reason_for({}), "unknown")
        self.assertEqual(C.retry_reason_for(None), "unknown")

    def test_validity(self):
        for value in C.RETRY_REASONS:
            self.assertEqual(C.retry_reason_valid(value), value != "host_error", value)
        self.assertTrue(C.retry_reason_valid("host_error:ENOTFOUND"))
        self.assertFalse(C.retry_reason_valid("host_error:"))
        self.assertFalse(C.retry_reason_valid("because"))
        self.assertFalse(C.retry_reason_valid(None))


if __name__ == "__main__":
    unittest.main()
