"""`worker_lifecycle.cancellation` refuses with EVERY problem of a request (K1, C4-5).

The four checks each compare a field of the request with a constant and none reads what another
established, so a request with no evidence, an unreported source blocker and a tool still running
used to cost three rounds: the first failure was raised and hid the rest. The BEFORE texts below
are the verbatim output of the same calls on 72e2f22c (the commit this node was cut from).
"""
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from worker_lifecycle import cancellation, guard

CAUSE = "cancellation requires an explicit cause and evidence_ref; elapsed time is not a cause"
NOTIFIED = "required-source blocker must be reported to the user before stopping"
BUDGET = "hard budget requires explicit authorization_ref"
TOOL = "allow the active tool operation to settle before cancellation"


def head(count):
    return f"{count} problems - the request is refused whole, every one is listed:"


class CancellationChain(unittest.TestCase):
    def refusal(self, request):
        with self.assertRaises(ValueError) as caught:
            cancellation(request)
        return str(caught.exception)

    def test_a_sound_request_is_recorded(self):
        self.assertEqual({"cause": "user_stop", "evidence_ref": "x", "retry_charge": False, "status": "requested"},
                         cancellation({"cause": "user_stop", "evidence_ref": "x", "tool_active": True}))
        self.assertTrue(cancellation({"cause": "terminal_failure", "evidence_ref": "x"})["retry_charge"])

    def test_one_failing_check_keeps_its_old_text_byte_for_byte(self):
        for expected, request in [
            (CAUSE, {"cause": "timeout", "evidence_ref": "x"}),
            (CAUSE, {"cause": "user_stop"}),
            (CAUSE, {}),
            (NOTIFIED, {"cause": "source_blocker", "evidence_ref": "x"}),
            (BUDGET, {"cause": "authorized_budget", "evidence_ref": "x"}),
            (TOOL, {"cause": "terminal_failure", "evidence_ref": "x", "tool_active": True}),
        ]:
            with self.subTest(request=request):
                self.assertEqual(expected, self.refusal(request))

    def test_two_independent_problems_are_one_refusal_in_chain_order(self):
        # BEFORE: only CAUSE (the first failure) was told
        self.assertEqual(f"{head(2)}\n1) {CAUSE}\n2) {TOOL}",
                         self.refusal({"cause": "timeout", "evidence_ref": "x", "tool_active": True}))
        # BEFORE: only NOTIFIED
        self.assertEqual(f"{head(2)}\n1) {NOTIFIED}\n2) {TOOL}",
                         self.refusal({"cause": "source_blocker", "evidence_ref": "x", "tool_active": True}))
        # BEFORE: only CAUSE (no evidence_ref came first)
        self.assertEqual(f"{head(2)}\n1) {CAUSE}\n2) {BUDGET}",
                         self.refusal({"cause": "authorized_budget"}))

    def test_three_problems_in_one_refusal(self):
        # BEFORE: only CAUSE
        self.assertEqual(f"{head(3)}\n1) {CAUSE}\n2) {NOTIFIED}\n3) {TOOL}",
                         self.refusal({"cause": "source_blocker", "tool_active": True}))

    def test_a_check_does_not_fire_outside_its_own_cause(self):
        # the control for the independence claim: each cause-specific requirement belongs to its
        # cause alone, so a joint refusal never lists a requirement of another cause
        self.assertEqual(BUDGET, self.refusal({"cause": "authorized_budget", "evidence_ref": "x",
                                               "user_notified": False}))
        self.assertEqual(NOTIFIED, self.refusal({"cause": "source_blocker", "evidence_ref": "x",
                                                 "authorization_ref": None}))
        # a user's own stop passes while a tool is active: that is the one cause that may
        self.assertEqual("user_stop", cancellation({"cause": "user_stop", "evidence_ref": "x",
                                                    "tool_active": True})["cause"])

    def test_the_class_is_the_one_the_single_check_always_raised(self):
        for request in ({}, {"cause": "source_blocker", "tool_active": True}):
            with self.assertRaises(ValueError):
                cancellation(request)


class StopBranch(unittest.TestCase):
    """CX1-9 (B-2, E17): the stop branch of `guard` reads receipt names through `host_dispatch.binding_names`,
    matches the target OR its last component (never narrower than `main`), and judges ALL matches."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.folder = self.root / "qa-factory/state/host-dispatches"
        self.folder.mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def receipt(self, name, **fields):
        (self.folder / f"{name}.json").write_text(json.dumps(fields), encoding="utf-8")

    def stop(self, target, tool="interrupt_agent"):
        """The exit code of the guard for a stop of `target`: 2 = blocked, 0 = left alone."""
        key = "target" if tool == "interrupt_agent" else "id"
        ti = dict({key: target} if target is not None else {}, **({"interrupt": True} if tool == "send_input" else {}))
        with patch("hooklib.project_root", return_value=self.root), contextlib.redirect_stderr(io.StringIO()):
            try:
                guard({"tool_name": tool, "tool_input": ti})
            except SystemExit as exc:
                return exc.code
        return 0

    def test_a_full_path_target_against_a_name_only_receipt_is_refused(self):
        # the SubagentStart receipt: native_context.py -> host_dispatch.record writes the BARE name twice
        self.receipt("a", agent_id="019e-uuid", task_name="qa_x", task_path="qa_x", status="running")
        self.assertEqual(2, self.stop("/root/qa_x"))     # `main` blocked it by the last component
        self.assertEqual(2, self.stop("qa_x"))
        self.assertEqual(2, self.stop("019e-uuid"))
        self.assertEqual(0, self.stop("/root/qa_other"))

    def test_a_terminal_namesake_does_not_allow_stopping_a_live_worker(self):
        # `a` sorts first: on `main` the first match, terminal, ended the loop with the stop allowed
        self.receipt("a", agent_id="/root/qa_x", task_name="qa_x", task_path="/root/qa_x", status="terminal")
        self.receipt("b", agent_id="/elsewhere/qa_x", task_name="qa_x", task_path="/elsewhere/qa_x", status="running")
        self.assertEqual(2, self.stop("/elsewhere/qa_x"))
        self.assertEqual(2, self.stop("qa_x"))
        self.receipt("a", agent_id="/root/qa_x", task_name="qa_x", task_path="/root/qa_x", status="running")
        self.receipt("b", agent_id="/elsewhere/qa_x", task_name="qa_x", task_path="/elsewhere/qa_x", status="terminal")
        self.assertEqual(2, self.stop("/elsewhere/qa_x"))   # the live one is matched by the basename: wide is safe

    def test_the_bare_name_of_two_live_workers_is_refused_and_of_finished_ones_is_not(self):
        self.receipt("a", agent_id="/root/qa_x", status="running")
        self.receipt("b", agent_id="/other/qa_x", status="running")
        self.assertEqual(2, self.stop("qa_x"))
        self.receipt("a", agent_id="/root/qa_x", status="terminal")
        self.assertEqual(2, self.stop("qa_x"))               # one of the two is still live
        self.receipt("b", agent_id="/other/qa_x", status="terminal")
        self.assertEqual(0, self.stop("qa_x"))               # E17 control: only finished workers match
        self.assertEqual(0, self.stop("/elsewhere/qa_x"))

    def test_a_recorded_cancellation_allows_the_stop(self):
        state = self.root / "qa-factory/artifacts/T-1/state"
        state.mkdir(parents=True)
        (state / "controller.json").write_text(json.dumps(
            {"dispatches": {"D-1": {"id": "D-1", "cancellation": {"cause": "user_stop"}}}}), encoding="utf-8")
        self.receipt("a", agent_id="/root/qa_x", task_id="T-1", dispatch_id="D-1", status="running")
        self.assertEqual(0, self.stop("/root/qa_x"))
        self.receipt("a", agent_id="/root/qa_x", task_id="T-1", dispatch_id="D-2", status="running")
        self.assertEqual(2, self.stop("/root/qa_x"))
        (state / "controller.json").write_text("[1]", encoding="utf-8")
        self.assertEqual(2, self.stop("/root/qa_x"))         # a state we cannot read allows nothing

    def test_a_broken_receipt_beside_never_lets_a_live_stop_through(self):
        (self.folder / "0bad.json").write_text("{not json", encoding="utf-8")
        (self.folder / "0list.json").write_text("[1, 2]", encoding="utf-8")
        self.receipt("0odd", agent_id=["x"], task_name=7, task_path=None)
        self.receipt("z", agent_id="/root/qa_x", status="running")
        self.assertEqual(2, self.stop("/root/qa_x"))
        self.assertEqual(0, self.stop("/root/qa_y"))

    def test_a_stop_that_names_nobody_judges_every_live_receipt(self):
        self.receipt("a", agent_id="/root/qa_x", task_name="qa_x", task_path="/root/qa_x", status="running")
        self.assertEqual(2, self.stop(None))
        self.assertEqual(2, self.stop(None, "send_input"))

    def test_send_input_interrupt_is_a_stop_and_a_plain_message_is_not(self):
        self.receipt("a", agent_id="/root/qa_x", task_name="qa_x", status="running")
        with patch("hooklib.project_root", return_value=self.root), contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                guard({"tool_name": "send_input", "tool_input": {"id": "qa_x", "interrupt": True}})
            guard({"tool_name": "send_input", "tool_input": {"id": "qa_x", "message": "status"}})


if __name__ == "__main__":
    unittest.main()
