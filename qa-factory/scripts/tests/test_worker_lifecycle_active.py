"""active_binding and the spawn guard read the host's own `task_complete` (t-010/t-971, TP2-2406 S4, 13.10.2026).

The completed-but-unaccepted case designer's `story_step` receipt stayed `running` (only `story_step finish` closes it,
and it refused), so `worker_lifecycle.active_binding` - which read the receipt's `status` alone - kept the controller's
authorized durable checkpoint refused: "host worker is still active or cancellation unacknowledged". The host's own
completion record for the receipt's exact path and this launch (`dispatch_liveness.native_stop`) is the one new reason
a non-terminal receipt stops counting; the receipt itself is never written.

Keys: K1 completed (older than the grace window) -> not active (and the Controller's checkpoint no longer refuses);
K2 running -> active; K3 aborted, silent, no rollout, an earlier launch, cut mid-row -> active; K4 terminal -> not active;
K5 a failing helper frees nothing; K6 the spawn guard (`binding_is_active`, which `guard` calls) is NOT changed: it reads
only terminal/controller facts, so a completed rollout under a controller still `running` keeps refusing a duplicate
(the critic's Q2, t-011); K7 several receipts of one dispatch are asked together, as `dispatch_liveness.state` asks
them (one running receipt keeps the dispatch active); K8 several rollouts of one path are asked together; K9 a worker
that completed inside the grace window is still active (its stop hooks may send it back).
"""
import hashlib
import json
import sys
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_scout_reliability as scout
from controller import Controller
from event_store import StateConflict
from worker_lifecycle import active_binding, binding_is_active, guard, note_unlaunched_denial

AGENT = '/root/qa_case_designer__tp2_2406_3'
OTHER = '/root/qa_case_designer__tp2_2406_4'
STILL_ACTIVE = 'host worker is still active'


def stamp(epoch):
    return datetime.fromtimestamp(epoch, timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.000Z')


class Fixture:
    """A temp project holding one story_step receipt (as `story_step.bind` writes it), cost records and rollouts."""

    def __init__(self, tmp, now, ticket='TASK-1', dispatch='d'):
        self.root, self.now, self.ticket, self.dispatch = Path(tmp), now, ticket, dispatch
        self.bound_at = now - 500
        self.state = self.root / 'qa-factory/state'
        (self.root / 'qa-factory/artifacts' / ticket).mkdir(parents=True)
        (self.root / 'qa-factory/config.json').write_text('{}', encoding='utf-8')  # the project marker the controller reads
        self.receipt = self.write_receipt()

    def write_receipt(self, agent=AGENT, **fields):
        body = {'agent_id': agent, 'agent_type': 'qa-case-designer', 'task_id': self.ticket,
                'dispatch_id': self.dispatch, 'status': 'running', 'bound_by': 'story_step', 'bound_at': self.bound_at}
        body.update(fields)
        path = self.state / 'host-dispatches' / (hashlib.sha256(agent.encode()).hexdigest() + '.json')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(body), encoding='utf-8')
        return path

    def rollout(self, last, first_at=None, last_at=None, thread='01a135d4', agent=AGENT):
        """`last`: task_complete | turn_aborted (an event_msg) | response_item. Times default to the live S4 shape,
        the completion 400 s before now - past the 300 s grace window."""
        first_at = self.bound_at - 40 if first_at is None else first_at
        last_at = self.bound_at + 100 if last_at is None else last_at
        rows = [{'timestamp': stamp(first_at), 'type': 'session_meta',
                 'payload': {'id': thread, 'agent_path': agent, 'parent_thread_id': 'p-1'}},
                {'timestamp': stamp(first_at + 5), 'type': 'response_item', 'payload': {'type': 'message'}}]
        if last == 'response_item':
            rows.append({'timestamp': stamp(last_at), 'type': last, 'payload': {'type': 'message'}})
        else:
            payload = {'type': last, 'turn_id': 't-1'}
            if last == 'task_complete':
                payload['completed_at'] = last_at
            rows.append({'timestamp': stamp(last_at), 'type': 'event_msg', 'payload': payload})
        path = self.root / f'rollout-{thread}.jsonl'
        path.write_text('\n'.join(json.dumps(row) for row in rows) + '\n', encoding='utf-8')
        (self.state / 'cost').mkdir(parents=True, exist_ok=True)
        (self.state / 'cost' / f'{thread}.json').write_text(json.dumps({'transcript': str(path)}), encoding='utf-8')
        return path

    def active(self):
        return active_binding(self.root, self.dispatch, self.ticket, now=self.now)


class ActiveBinding(unittest.TestCase):
    def test_k1_completed_but_unaccepted_is_not_active_and_the_receipt_is_left_alone(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Fixture(tmp, 1_800_000_000.0)
            f.rollout('task_complete')
            before = f.receipt.read_bytes()
            self.assertIsNone(f.active())
            self.assertEqual(f.receipt.read_bytes(), before)
            self.assertNotIn('terminal_source', json.loads(before))
            # a receipt naming another story is still not this story's
            self.assertIsNone(active_binding(f.root, 'd', 'OTHER', now=f.now))

    def test_k1_the_controllers_checkpoint_no_longer_refuses_for_a_completed_worker(self):
        from host_dispatch import binding_path
        with tempfile.TemporaryDirectory() as tmp:
            f = Fixture(tmp, time.time())
            state = {'source_revision': 'fixture', 'dispatches': {'d': {'id': 'd', 'status': 'running'}}, 'stages': {}}
            payload = {'id': 'd', 'status': 'blocked', 'checkpoint': {'remaining': ['x']}, 'reason': 'y'}
            controller = Controller(f.root / 'qa-factory/artifacts/TASK-1')
            self.assertEqual(binding_path(f.root, AGENT), f.receipt)
            f.rollout('response_item', last_at=f.now - 10)  # still being written: the refusal stands
            with self.assertRaisesRegex(StateConflict, STILL_ACTIVE):
                controller.validate('checkpoint', dict(payload), state)
            f.rollout('task_complete')  # the same worker, now ended
            controller.validate('checkpoint', dict(payload), state)  # accepted: it does not raise

    def test_k2_a_worker_still_being_written_is_active(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Fixture(tmp, 1_800_000_000.0)
            f.rollout('response_item', last_at=f.now - 10)
            self.assertEqual(f.active()['agent_id'], AGENT)

    def test_k3_every_other_ending_keeps_the_receipt_active(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Fixture(tmp, 1_800_000_000.0)
            cases = {
                'aborted just now': dict(last='turn_aborted', last_at=f.now - 10),
                'aborted long ago': dict(last='turn_aborted', last_at=f.now - 5000),
                'silent past the window, no completion': dict(last='response_item', last_at=f.now - 5000),
                'an earlier launch under the same path': dict(last='task_complete', first_at=f.bound_at - 3600,
                                                              last_at=f.bound_at - 3000),
                'ended before the receipt was written': dict(last='task_complete', first_at=f.bound_at - 200,
                                                             last_at=f.bound_at - 30),
            }
            for name, kwargs in cases.items():
                f.rollout(**kwargs)
                self.assertEqual((f.active() or {}).get('agent_id'), AGENT, name)
            # a completion followed by a half-written row: the worker went on
            path = f.rollout('task_complete')
            with path.open('a', encoding='utf-8') as handle:
                handle.write('{"timestamp": "')
            self.assertEqual((f.active() or {}).get('agent_id'), AGENT, 'cut mid-row after a completion')
            # no rollout at all: a cost record without a transcript, then no cost record
            cost = f.state / 'cost' / '01a135d4.json'
            f.rollout('task_complete')
            cost.write_text('{}', encoding='utf-8')
            self.assertEqual((f.active() or {}).get('agent_id'), AGENT, 'no transcript')
            cost.unlink()
            self.assertEqual((f.active() or {}).get('agent_id'), AGENT, 'no cost record')
            # a receipt not written by story_step is read by its status alone, as before
            f.rollout('task_complete')
            f.write_receipt(bound_by='spawn')
            self.assertEqual(f.active()['agent_id'], AGENT, 'not story_step-bound')

    def test_k4_a_terminal_receipt_is_not_active(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Fixture(tmp, 1_800_000_000.0)
            f.rollout('response_item', last_at=f.now - 10)
            f.write_receipt(status='terminal')
            self.assertIsNone(f.active())

    def test_k5_a_failing_helper_frees_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Fixture(tmp, 1_800_000_000.0)
            f.rollout('task_complete')
            self.assertIsNone(f.active())
            with patch('dispatch_liveness.native_stop', side_effect=RuntimeError('boom')):
                self.assertEqual(f.active()['agent_id'], AGENT)
            with patch('dispatch_liveness.native_rollouts', side_effect=RuntimeError('boom')):
                self.assertEqual(f.active()['agent_id'], AGENT)

    def test_k7_several_receipts_of_one_dispatch_are_asked_together(self):
        import dispatch_liveness as live
        with tempfile.TemporaryDirectory() as tmp:
            f = Fixture(tmp, 1_800_000_000.0)
            f.rollout('task_complete')
            state = lambda: live.state(f.root, f.ticket, {'id': f.dispatch}, now=f.now)['state']  # noqa: E731
            # a spawn-time receipt of the same dispatch (no rollout is read for it): the dispatch stays active
            f.write_receipt(agent=OTHER, bound_by='host_dispatch')
            self.assertEqual(f.active()['agent_id'], OTHER)
            self.assertEqual(state(), live.ALIVE)
            # a story_step receipt whose rollout is still being written: the same
            f.write_receipt(agent=OTHER)
            f.rollout('response_item', last_at=f.now - 10, thread='01a135d5', agent=OTHER)
            self.assertEqual(f.active()['agent_id'], OTHER)
            self.assertEqual(state(), live.ALIVE)
            # both ended: no active worker, and the liveness verdict is a return
            f.rollout('task_complete', thread='01a135d5', agent=OTHER)
            self.assertIsNone(f.active())
            self.assertEqual(state(), live.RETURNED)

    def test_k8_several_rollouts_of_one_path_are_asked_together(self):
        import dispatch_liveness as live
        with tempfile.TemporaryDirectory() as tmp:
            f = Fixture(tmp, 1_800_000_000.0)
            f.rollout('task_complete', first_at=f.bound_at + 60, thread='t-new')
            f.rollout('response_item', last_at=f.now - 5, thread='t-old')   # the same path, written 5 s ago
            self.assertEqual(f.active()['agent_id'], AGENT)
            self.assertEqual(live.state(f.root, f.ticket, {'id': f.dispatch}, now=f.now)['state'], live.ALIVE)
            f.rollout('task_complete', first_at=f.bound_at - 40, last_at=f.bound_at + 50, thread='t-old')
            self.assertIsNone(f.active())     # both ended: the same answer as the liveness reader's RETURNED

    def test_k9_a_worker_that_just_completed_is_still_active_inside_the_grace_window(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Fixture(tmp, 1_800_000_000.0)
            f.rollout('task_complete', last_at=f.now - 300)       # its stop hooks may still send it back
            self.assertEqual(f.active()['agent_id'], AGENT)
            f.rollout('task_complete', last_at=f.now - 301)
            self.assertIsNone(f.active())


CLAUDE = 'a5b4b2e19d35048ea'     # a Claude receipt's agent_id: the transcript stem's id, not an agent path
HANDBACK = json.loads((Path(__file__).resolve().parents[2] / 'references' / 'host-report-forms.json')
                      .read_text(encoding='utf-8'))['claude']['handback_tool']


class ClaudeFixture(Fixture):
    """A temp project holding one story_step receipt with a bare Claude agent id, its host transcript (the handback and
    the host's acknowledgement, with whatever rows come after), the sidecar and the hook's journal lines."""

    def __init__(self, tmp, now, **kw):
        super().__init__(tmp, now, **kw)
        self.receipt.unlink()
        self.receipt = self.write_receipt(agent=CLAUDE)
        self.transcript_path = self.root / 'sessions/s1/subagents' / f'agent-{CLAUDE}.jsonl'

    def row(self, kind, at, **fields):
        base = {'timestamp': stamp(at), 'type': kind}
        base.update(fields)
        return base

    def hand_back(self, ack_age, after=(), finished=True, stop=None, stop_status='completed', tail=''):
        """The transcript ends with the call and the host's acknowledgement `ack_age` s before now (then `after` rows,
        each a (seconds ago, text) pair); `finished`: the sidecar's value (None: no sidecar); `stop`: the hook's journal
        line at that many seconds after the acknowledgement."""
        at = self.now - ack_age
        rows = [self.row('user', at - 3000, message={'role': 'user', 'content': f'You are qa-case-designer. Ticket: {self.ticket}\nDispatch id: {self.dispatch}\n'}),
                self.row('assistant', at - 1, message={'role': 'assistant', 'content': [
                    {'type': 'tool_use', 'id': 'toolu_1', 'name': HANDBACK, 'input': {'message': 'report'}}]}),
                self.row('user', at, message={'role': 'user', 'content': [{'type': 'tool_result', 'tool_use_id': 'toolu_1', 'content': [
                    {'type': 'text', 'text': '{"success":true,"message":"Report delivered to your caller."}'}]}]})]
        rows += [self.row('assistant', self.now - ago, message={'role': 'assistant', 'content': [{'type': 'text', 'text': text}]})
                 for ago, text in after]
        self.transcript_path.parent.mkdir(parents=True, exist_ok=True)
        self.transcript_path.write_text(''.join(json.dumps(row) + '\n' for row in rows) + tail, encoding='utf-8')
        (self.state / 'cost').mkdir(parents=True, exist_ok=True)
        (self.state / 'cost' / 's1.json').write_text(json.dumps({'transcript': str(self.root / 'sessions/s1.jsonl')}), encoding='utf-8')
        import runtime_paths
        side, journal = self.transcript_path.with_name(f'agent-{CLAUDE}.meta.json'), runtime_paths.record(self.root, 'journal.jsonl')
        side.unlink(missing_ok=True)      # each call is a fresh scene: nothing of the one before stays
        journal.unlink(missing_ok=True)
        if finished is not None:
            side.write_text(json.dumps({'agentType': 'critic', 'finished': finished}), encoding='utf-8')
        if stop is not None:
            journal.parent.mkdir(parents=True, exist_ok=True)
            when = datetime.fromtimestamp(at + stop, timezone.utc).isoformat(timespec='milliseconds')
            journal.write_text(json.dumps({'ts': when, 'event': 'subagent_stop', 'agent': 'qa-factory:qa-case-designer',
                                           'task': self.ticket, 'dispatch': self.dispatch, 'status': stop_status,
                                           'dispatch_receipt': self.receipt.name, 'return_owner': 'story_step'}) + '\n',
                               encoding='utf-8')


class ClaudeActiveBinding(unittest.TestCase):
    def checkpoint(self, f, state=None):
        controller = Controller(f.root / 'qa-factory/artifacts/TASK-1')
        state = state or {'source_revision': 'fixture', 'dispatches': {'d': {'id': 'd', 'status': 'running'}}, 'stages': {}}
        controller.validate('checkpoint', {'id': 'd', 'status': 'blocked', 'checkpoint': {'remaining': ['x']}, 'reason': 'y'}, state)

    def test_kw1_a_critic_that_handed_back_is_not_active_and_the_checkpoint_passes_with_no_word(self):
        """The incident: the hook's `completed` line at the acknowledgement, the sidecar `finished`, a young receipt."""
        with tempfile.TemporaryDirectory() as tmp:
            f = ClaudeFixture(tmp, time.time())
            f.hand_back(81, stop=3)
            before = f.receipt.read_bytes()
            self.assertIsNone(f.active())
            self.assertEqual(f.receipt.read_bytes(), before)
            self.assertNotIn('terminal_source', json.loads(before))
            self.checkpoint(f)       # does not raise: the person's word is not needed
            self.assertIsNone(active_binding(f.root, 'd', 'OTHER', now=f.now))

    def test_kw2_rows_after_the_acknowledgement_or_an_open_window_keep_the_receipt_active(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = ClaudeFixture(tmp, time.time())
            cases = {
                'a resumed child (rows after the acknowledgement)': dict(ack_age=650, after=[(5, 'working again')], stop=3),
                'a row cut mid-line after the acknowledgement': dict(ack_age=650, stop=3, tail='{"timestamp": "'),
                'inside the grace window, no stop line': dict(ack_age=100),
                'the hook sent it back (incomplete)': dict(ack_age=650, stop=3, stop_status='incomplete'),
                'the sidecar says not finished': dict(ack_age=650, stop=3, finished=False),
            }
            for name, kwargs in cases.items():
                f.hand_back(**kwargs)
                self.assertEqual((f.active() or {}).get('agent_id'), CLAUDE, name)
            f.hand_back(100)
            with self.assertRaisesRegex(StateConflict, STILL_ACTIVE):
                self.checkpoint(f)
            f.hand_back(650)             # past the window with no stop line: the grace alone frees it
            self.assertIsNone(f.active())

    def test_kw3_a_failing_claude_helper_frees_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = ClaudeFixture(tmp, time.time())
            f.hand_back(650, stop=3)
            self.assertIsNone(f.active())
            for name in ('claude_stop', 'host_verdict', 'thresholds'):
                with patch(f'dispatch_liveness.{name}', side_effect=RuntimeError('boom')):
                    self.assertEqual(f.active()['agent_id'], CLAUDE, name)
            for name in ('_claude_vote', '_stop_records', '_tail'):
                with patch(f'dispatch_liveness.{name}', side_effect=RuntimeError('boom')):
                    self.assertEqual(f.active()['agent_id'], CLAUDE, name)

    def test_kw4_the_two_readers_agree(self):
        import dispatch_liveness as live
        with tempfile.TemporaryDirectory() as tmp:
            f = ClaudeFixture(tmp, time.time())
            cases = [dict(ack_age=81, stop=3), dict(ack_age=650, stop=3), dict(ack_age=650), dict(ack_age=100),
                     dict(ack_age=100, stop=3), dict(ack_age=650, stop=3, finished=False),
                     dict(ack_age=650, stop=3, stop_status='incomplete'),
                     dict(ack_age=650, after=[(5, 'again')], stop=3), dict(ack_age=650, finished=None)]
            for kwargs in cases:
                f.hand_back(**kwargs)
                verdict = live.state(f.root, f.ticket, {'id': f.dispatch}, now=f.now)['state']
                self.assertEqual(f.active() is None, verdict == live.RETURNED, f'{kwargs}: {verdict}')

    def test_kw5_a_receipt_of_a_dispatch_the_controller_no_longer_holds_running_is_not_active(self):
        """A receipt stays `running` on a host whose stop hook does not mark it terminal; when the controller itself no
        longer holds its dispatch `running` (accepted, superseded, released), the receipt is not an active worker."""
        with tempfile.TemporaryDirectory() as tmp:
            f = Fixture(tmp, 1_800_000_000.0)
            f.rollout('response_item', last_at=f.now - 10)        # a rollout still being written: K2 says active
            controller_json = f.root / 'qa-factory/artifacts' / f.ticket / 'state/controller.json'
            controller_json.parent.mkdir(parents=True, exist_ok=True)
            for status, expected in (('running', AGENT), ('accepted', None), ('superseded', None), ('released', None)):
                controller_json.write_text(json.dumps({'dispatches': {f.dispatch: {'id': f.dispatch, 'status': status}}}),
                                           encoding='utf-8')
                self.assertEqual((f.active() or {}).get('agent_id'), expected, status)
            # doubt keeps it active: a controller without the dispatch, or none at all
            controller_json.write_text(json.dumps({'dispatches': {}}), encoding='utf-8')
            self.assertEqual((f.active() or {}).get('agent_id'), AGENT, 'dispatch unknown to the controller')
            controller_json.unlink()
            self.assertEqual((f.active() or {}).get('agent_id'), AGENT, 'no controller.json')
            self.assertNotIn('terminal_source', json.loads(f.receipt.read_text(encoding='utf-8')))

    def test_kw6_the_spawn_guard_is_unchanged_for_a_handed_back_critic(self):
        """A host return frees the checkpoint, not the spawn guard: it reads controller facts only (K6)."""
        with tempfile.TemporaryDirectory() as tmp:
            f = ClaudeFixture(tmp, time.time(), dispatch='S4-qa-case-designer-3')
            controller = f.root / 'qa-factory/artifacts/TASK-1/state'
            controller.mkdir()
            (controller / 'controller.json').write_text(json.dumps({'dispatches': {
                f.dispatch: {'id': f.dispatch, 'status': 'running'}}}), encoding='utf-8')
            f.hand_back(650, stop=3)
            self.assertIsNone(f.active())                              # the checkpoint is free
            receipt = json.loads(f.receipt.read_text(encoding='utf-8'))
            self.assertTrue(binding_is_active(f.root, receipt))        # the guard still sees a running dispatch
            code, message = scout.Reliability.spawn_verdict(None, f.root, role='qa-case-designer')
            self.assertEqual(code, 2, message)


class SpawnGuard(unittest.TestCase):
    def test_k6_the_spawn_guard_reads_controller_facts_only_a_completed_rollout_does_not_free_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Fixture(tmp, time.time(), dispatch='S4-qa-case-designer-3')
            (f.root / 'qa-factory/config.json').write_text('{}', encoding='utf-8')
            controller = f.root / 'qa-factory/artifacts/TASK-1/state'
            controller.mkdir()
            (controller / 'controller.json').write_text(json.dumps({'dispatches': {
                f.dispatch: {'id': f.dispatch, 'status': 'running'}}}), encoding='utf-8')
            receipt = json.loads(f.receipt.read_text(encoding='utf-8'))
            f.rollout('response_item', last_at=f.now - 10)
            self.assertTrue(binding_is_active(f.root, receipt))
            code, message = scout.Reliability.spawn_verdict(None, f.root, role='qa-case-designer')
            self.assertEqual(code, 2, message)
            f.rollout('task_complete')  # the worker ended, but the controller still says running: the guard is unchanged
            self.assertTrue(binding_is_active(f.root, receipt))
            code, message = scout.Reliability.spawn_verdict(None, f.root, role='qa-case-designer')
            self.assertEqual(code, 2, message)
            # the existing door: once the controller records the dispatch as settled, the guard lets a replacement through
            (controller / 'controller.json').write_text(json.dumps({'dispatches': {
                f.dispatch: {'id': f.dispatch, 'status': 'accepted'}}}), encoding='utf-8')
            self.assertFalse(binding_is_active(f.root, receipt))
            code, message = scout.Reliability.spawn_verdict(None, f.root, role='qa-case-designer')
            self.assertEqual((code, message), (0, ''))


class SpawnRefusalIsUnconditional(unittest.TestCase):
    """t-1001 M-1: the denial note runs BEFORE `block`, so nothing it raises may stop the refusal (FB-24: "enforced either way")."""

    def spawn(self, root, note_patch=None):
        """`guard` against an unverified host; returns (how many times `block` ran, the exit code it gave)."""
        calls = []

        def block(message):
            calls.append(message)
            raise SystemExit(2)

        event = {'tool_name': 'spawn_agent', 'tool_input': {'task_name': 'qa_automator__task_1'}}
        with patch('hooklib.project_root', return_value=root), patch('hooklib.block', block), \
                patch('stage_guard.requested_ticket', return_value='TASK-1'), \
                patch('host_capabilities.inspect', return_value={'story_ready': False}):
            try:
                if note_patch is None:
                    guard(event)
                else:
                    with note_patch:
                        guard(event)
            except SystemExit as exit_:
                return len(calls), exit_.code
        return len(calls), 0

    def project(self, tmp):
        root = Path(tmp)
        state = root / 'qa-factory/artifacts/TASK-1/state'
        state.mkdir(parents=True)
        (root / 'qa-factory/config.json').write_text('{}', encoding='utf-8')
        return root, state / 'controller.json'

    def test_a_note_that_returns_a_caught_class_or_finds_nothing_still_refuses_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, controller = self.project(tmp)
            self.assertEqual(self.spawn(root), (1, 2), 'no controller.json')
            controller.write_text('[]', encoding='utf-8')
            self.assertEqual(self.spawn(root), (1, 2), 'a JSON list')
            controller.write_bytes(b'\xef\xbb\xbf' + json.dumps({'dispatches': {'d': {
                'id': 'd', 'stage': 'S5', 'role': 'qa-automator', 'status': 'running'}}}).encode('utf-8'))
            self.assertEqual(self.spawn(root), (1, 2), 'a BOM file now reads (it was a caught ValueError before)')
            self.assertTrue((controller.parent / 'dispatch-denials.jsonl').exists(), 'the BOM file was read and charged')

    def test_a_nesting_too_deep_for_the_parser_still_refuses_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, controller = self.project(tmp)
            controller.write_text('[' * 200_000, encoding='utf-8')  # generated here, never a committed fixture
            with patch('hooklib.project_root', return_value=root), self.assertRaises(RecursionError):
                note_unlaunched_denial(root, {'tool_name': 'spawn_agent'}, 'TASK-1', 'qa-automator', 'r')
            self.assertEqual(self.spawn(root), (1, 2))

    def test_a_half_installed_plugin_still_refuses_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, _ = self.project(tmp)
            gone = patch.dict(sys.modules, {'inject_context': None})  # `from inject_context import ...` raises ImportError
            self.assertEqual(self.spawn(root, gone), (1, 2))
            self.assertEqual(self.spawn(root, patch('worker_lifecycle.note_unlaunched_denial', side_effect=ImportError('x'))),
                             (1, 2))


if __name__ == '__main__':
    unittest.main()
