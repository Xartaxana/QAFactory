"""Focused contracts for durable, non-fake orchestrator rollover."""
import sys
import tempfile
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import mark_project
from controller import Controller
from event_store import StateConflict
from session_handoff import can_takeover, rollover_status, validate_takeover


class SessionHandoffTests(unittest.TestCase):
    def test_threshold_is_pending_not_story_budget_reset(self):
        due = rollover_status({"model_requests": 40})
        self.assertTrue(due["rollover_pending"])
        self.assertEqual(["context_percent"], due["telemetry_unknown"])

    def test_running_work_blocks_takeover(self):
        self.assertFalse(can_takeover({"dispatches": {"d": {"id": "d", "status": "running"}}})["ready"])

    def test_pending_jobs_and_unverified_fresh_ack_block_takeover(self):
        state = {"revision": 3, "dispatches": {}, "running_jobs": [{"id": "j"}]}
        with self.assertRaises(ValueError):
            validate_takeover(None, {"_expected_revision": 3, "host_capability": "manual_continuation",
                                     "lease": {"owner_session_id": "n", "generation": 1}}, state)
        state["running_jobs"] = []
        with self.assertRaises(ValueError):
            validate_takeover(None, {"_expected_revision": 3, "host_capability": "fresh_orchestrator_context",
                                     "new_session_id": "n", "host_ack": {"session_id": "n"},
                                     "lease": {"owner_session_id": "n", "generation": 1}}, state)

    # --- validate_takeover refuses with EVERY problem (K1, C4-5) ---------------------------
    # The BEFORE texts below are the verbatim output of the same calls on 72e2f22c (the commit
    # this node was cut from), where each raised the first failure only.
    HEAD2 = "2 problems - the request is refused whole, every one is listed:"
    REVISION = "takeover requires current expected_revision"
    BLOCKED = "takeover blocked until running work/jobs/writes are reconciled"
    CAPABILITY = "unsupported handoff capability"
    ACK = "fresh handoff requires verified host acknowledgement"
    OWNER = "takeover owner does not hold current lease"
    GENERATION = "takeover lease generation must increase"
    HELD = {"owner_session_id": "old", "generation": 1}
    STATE = {"revision": 3, "dispatches": {}}

    @classmethod
    def good(cls, **change):
        request = {"_expected_revision": 3, "host_capability": "manual_continuation",
                   "owner_session_id": "old", "lease": {"owner_session_id": "n", "generation": 2}}
        request.update(change)
        return request

    def refusal(self, request, state=None):
        with self.assertRaises(ValueError) as caught:
            validate_takeover(self.HELD, request, self.STATE if state is None else state)
        return str(caught.exception)

    def test_takeover_passes_when_nothing_is_wrong(self):
        self.assertIs(True, validate_takeover(self.HELD, self.good(), self.STATE))
        # the empty problem list raises nothing, and no lease held skips the lease checks
        self.assertIs(True, validate_takeover(None, self.good(owner_session_id="x", lease={}), self.STATE))

    def test_one_failing_check_keeps_its_old_text_byte_for_byte(self):
        fresh = dict(host_capability="fresh_orchestrator_context", new_session_id="n")
        for expected, request, state in [
            (self.REVISION, self.good(_expected_revision=2), None),
            (self.BLOCKED, self.good(), dict(self.STATE, running_jobs=[{"id": "j"}])),
            (self.CAPABILITY, self.good(host_capability="zzz"), None),
            (self.ACK, self.good(host_ack={"session_id": "n"}, **fresh), None),
            (self.OWNER, self.good(owner_session_id="other"), None),
            (self.GENERATION, self.good(lease={"owner_session_id": "n", "generation": 1}), None),
        ]:
            with self.subTest(expected=expected, request=request):
                self.assertEqual(expected, self.refusal(request, state))

    def test_two_independent_problems_are_one_refusal_in_chain_order(self):
        self.assertEqual(f"{self.HEAD2}\n1) {self.REVISION}\n2) {self.CAPABILITY}",
                         self.refusal(self.good(_expected_revision=2, host_capability="zzz")))
        # the order is the chain's, whichever problem the request has "first"
        self.assertEqual(f"{self.HEAD2}\n1) {self.BLOCKED}\n2) {self.GENERATION}",
                         self.refusal(self.good(lease={"generation": 1}),
                                      dict(self.STATE, running_jobs=[{"id": "j"}])))

    def test_all_five_possible_problems_in_one_refusal(self):
        # an unsupported capability and an unverified acknowledgement exclude each other, so
        # five is the most one request can carry
        request = self.good(_expected_revision=2, host_capability="fresh_orchestrator_context",
                            new_session_id="n", owner_session_id="other", lease={"generation": 1})
        self.assertEqual("5 problems - the request is refused whole, every one is listed:\n"
                         f"1) {self.REVISION}\n2) {self.BLOCKED}\n3) {self.ACK}\n4) {self.OWNER}\n5) {self.GENERATION}",
                         self.refusal(request, dict(self.STATE, running_jobs=[{"id": "j"}])))

    def test_values_a_later_check_would_have_choked_on_are_refusals_not_errors(self):
        # BEFORE (72e2f22c): AttributeError / AttributeError / TypeError, each only after every
        # earlier check passed. In a chain they would hide the problems found before them.
        fresh = dict(host_capability="fresh_orchestrator_context", new_session_id="n")
        self.assertEqual(f"{self.HEAD2}\n1) {self.REVISION}\n2) {self.ACK}",
                         self.refusal(self.good(_expected_revision=2, host_ack="not an object", **fresh)))
        self.assertEqual(f"{self.HEAD2}\n1) {self.REVISION}\n2) {self.GENERATION}",
                         self.refusal(self.good(_expected_revision=2, lease=None)))
        self.assertEqual(f"{self.HEAD2}\n1) {self.REVISION}\n2) {self.GENERATION}",
                         self.refusal(self.good(_expected_revision=2, lease={"generation": "9"})))
        self.assertEqual(f"{self.HEAD2}\n1) {self.REVISION}\n2) {self.CAPABILITY}",
                         self.refusal(self.good(_expected_revision=2, host_capability=["x"])))

    def test_negative_control_a_request_that_is_not_an_object_stops_and_names_what_did_not_run(self):
        note = ("(the capability, acknowledgement, owner and lease checks did not run: "
                "they read the request as an object)")
        self.assertEqual(f"{self.REVISION} {note}", self.refusal("not a request"))
        # the readiness check reads the state alone, so it still runs and the note closes the refusal
        self.assertEqual(f"{self.HEAD2}\n1) {self.REVISION}\n2) {self.BLOCKED} {note}",
                         self.refusal(None, dict(self.STATE, running_jobs=[{"id": "j"}])))

    def test_the_handoff_operation_reaches_the_joint_refusal_as_a_value_error(self):
        with tempfile.TemporaryDirectory() as raw:
            mark_project(Path(raw))
            root = Path(raw) / "TASK-9"; root.mkdir()
            c = Controller(root)
            c.apply("initialize", {"scope": ["TC-1"], "source_revision": "r",
                "known_paths": {"root": str(root)}, "idempotency_key": "init"})
            state = c.state()
            request = {"owner_session_id": "other", "host_capability": "zzz", "expected_revision": 99,
                       "lease": {"owner_session_id": "n", "generation": 1}, "idempotency_key": "joint"}
            with self.assertRaises(ValueError) as caught:
                c.validate("handoff", request, state)
            self.assertIn(self.REVISION, str(caught.exception))
            self.assertIn(self.CAPABILITY, str(caught.exception))

    def test_proposal_reconciliation_uses_pending_and_result_shape(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw); proposals = root / "work/proposals"; proposals.mkdir(parents=True)
            state = {"dispatches": {}}
            (proposals / "draft.json").write_text('{"kind":"bug"}', encoding="utf-8")
            self.assertTrue(can_takeover(state, root)["ready"])
            (proposals / "pending.json").write_text('{"pending":{"method":"agent"}}', encoding="utf-8")
            self.assertFalse(can_takeover(state, root)["ready"])
            (proposals / "pending.json").write_text('{"result":{"external_id":"X-1","url":"https://example.test/X-1"}}', encoding="utf-8")
            self.assertTrue(can_takeover(state, root)["ready"])

    def test_the_takeover_lists_are_in_code_point_order_on_every_platform(self):
        # t-892 (C4-7): the lists `can_takeover` hands to the joint refusal followed the order the
        # directory was listed in (raw on Linux, case-folded on NTFS), so the refusal named its jobs
        # and writes in a different order on a developer's machine and in CI. Uppercase first, by
        # code point: `B.json` before `a.json`, `a.json` before `c.json` - created in the reverse order.
        def names(rows):
            return [row["path"].replace("\\", "/").rsplit("/", 1)[-1] for row in rows]

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            for folder, kind in (("state/execution-jobs", "running"), ("state/external-writes", "writing")):
                (root / folder).mkdir(parents=True)
                for name in ("c.json", "a.json", "B.json"):
                    (root / folder / name).write_text('{"status": "%s"}' % kind, encoding="utf-8")
            proposals = root / "work/proposals"; proposals.mkdir(parents=True)
            for name in ("z.json", "Y.json"):
                (proposals / name).write_text('{"pending":{"method":"agent"}}', encoding="utf-8")
            got = can_takeover({"dispatches": {}}, root)
            self.assertEqual(["B.json", "a.json", "c.json"], names(got["running_jobs"]))
            # the external-writes files first (their folder is walked first), then the proposals
            self.assertEqual(["B.json", "a.json", "c.json", "Y.json", "z.json"], names(got["unknown_external_writes"]))

    def test_unsupported_host_has_manual_packet_and_lease_is_exclusive(self):
        with tempfile.TemporaryDirectory() as raw:
            mark_project(Path(raw))
            root = Path(raw) / "TASK-1"; root.mkdir()
            c = Controller(root)
            c.apply("initialize", {"scope": ["TC-1"], "source_revision": "r",
                "known_paths": {"root": str(root)}, "idempotency_key": "init"})
            c.apply("handoff", {"owner_session_id": None, "host_capability": "manual_continuation",
                "expected_revision": 1, "lease": {"owner_session_id": "old", "generation": 1},
                "idempotency_key": "manual"})
            packet = (root / "state/checkpoint.json").read_text(encoding="utf-8")
            self.assertIn("next_action", packet)
            with self.assertRaises(StateConflict):
                c.apply("handoff", {"owner_session_id": "other", "host_capability": "fresh_orchestrator_context",
                    "new_session_id": "new", "expected_revision": 2,
                    "lease": {"owner_session_id": "new", "generation": 2}, "idempotency_key": "racing"})

    def test_post_gate_case_critic_requires_reopen(self):
        with tempfile.TemporaryDirectory() as raw:
            mark_project(Path(raw))
            root = Path(raw) / "TASK-2"; root.mkdir()
            c = Controller(root)
            c.apply("initialize", {"scope": ["TC-1"], "source_revision": "r",
                "known_paths": {"root": str(root)}, "idempotency_key": "init"})
            # Direct projection setup is unnecessary: a Gate-A decision is enough to exercise the guard.
            c.store.commit("decision", {"id": "A", "gate": "A", "action": "approve", "status": "approved",
                "authorization_source": "human", "source_revision": "r", "scope": ["TC-1"],
                "input_revision": "r"}, "seed-A", project=c.project)
            with self.assertRaises(StateConflict):
                c.apply("dispatch", {"id": "critic", "stage": "S4", "role": "qa-case-critic",
                    "scope": ["TC-1"], "input_hash": "x", "budget": {}, "known_paths": {},
                    "idempotency_key": "critic"})

    def test_new_manual_runner_block_is_bounded_but_automation_is_not(self):
        with tempfile.TemporaryDirectory() as raw:
            workspace = mark_project(Path(raw))
            root = workspace / "TASK-3"; root.mkdir()
            c = Controller(root)
            cases = [f"TC-{number}" for number in range(1, 7)]
            c.apply("initialize", {"scope": cases, "source_revision": "r",
                "known_paths": {"root": str(root), "project_root": str(workspace)}, "idempotency_key": "init"})
            prepared = c.prepare({"stage": "S0", "role": "qa-runner", "scope": cases[:5],
                "execution_kind": "manual", "manual_case_ids": cases[:5]})
            self.assertEqual(cases[:5], prepared["dispatch_request"]["manual_case_ids"])
            with self.assertRaisesRegex(StateConflict, "split the block"):
                c.prepare({"stage": "S0", "role": "qa-runner", "scope": cases,
                    "execution_kind": "manual", "manual_case_ids": cases})
            manual = {"id": "manual-six", "stage": "S0", "role": "qa-runner",
                "scope": cases, "input_hash": "x", "budget": {}, "known_paths": {},
                "execution_kind": "manual", "manual_case_ids": cases,
                "idempotency_key": "manual-six"}
            with self.assertRaisesRegex(StateConflict, "split the block"):
                c.apply("dispatch", manual)
            automated = dict(manual, id="automated-many", execution_kind="automation",
                manual_case_ids=None, idempotency_key="automated-many")
            c.apply("dispatch", automated)
            self.assertEqual("automation", c.state()["dispatches"]["automated-many"]["execution_kind"])


if __name__ == "__main__":
    unittest.main()
