"""Environment preparation remains visible without replaying accepted work."""
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from controller import Controller, projection
from event_store import StateConflict
from session_handoff import can_takeover


class EnvironmentLifecycleTests(unittest.TestCase):
    def test_unsettled_job_controls_next_checkpoint_and_blocks_takeover(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            directory = root / 'state/environment-jobs'
            directory.mkdir(parents=True)
            (directory / 'job.json').write_text(json.dumps({'idempotency_key': 'build'}))
            job = {'job_id': 'job', 'status': 'stalled', 'settled': False}
            with patch('environment_preparation.environment_job_status', return_value=job):
                controller = Controller(root)
                self.assertEqual(controller.next_action()['action'], 'observe_environment_job')
                packet = controller.checkpoint_packet()
                self.assertEqual(packet['next_action']['job_id'], 'job')
                self.assertTrue(packet['running_jobs'])
                self.assertFalse(can_takeover({'dispatches': {}}, root)['ready'])
            with patch('environment_preparation.environment_job_status', return_value=dict(job, status='ready', settled=True)):
                self.assertTrue(can_takeover({'dispatches': {}}, root)['ready'])
                self.assertFalse(Controller(root).state()['running_jobs'])
            (directory / 'job.json').write_text('broken json')
            self.assertFalse(can_takeover({'dispatches': {}}, root)['ready'])
            self.assertEqual(Controller(root).next_action()['status'], 'unknown')

    def test_stopped_work_requires_explicit_matching_accepted_evidence(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            evidence = root / 'accepted.txt'
            evidence.write_text('accepted output')
            ref = {'path': evidence.name, 'sha256': hashlib.sha256(evidence.read_bytes()).hexdigest()}
            old = {'id': 'old', 'status': 'blocked', 'stage': 'S2', 'role': 'qa-requirements-tester',
                   'scope': ['TC-1'], 'input_hash': 'same'}
            new = dict(old, id='new', status='accepted', evidence_refs=[ref])
            state = {'source_revision': 'r', 'dispatches': {'old': old, 'new': new}}
            request = {'id': 'old', 'accepted_dispatch_id': 'new', 'reason': 'same work accepted by later dispatch'}
            controller = Controller(root)
            controller.validate('reconcile_dispatch', request, state)
            new['input_hash'] = 'different'
            with self.assertRaises(StateConflict):
                controller.validate('reconcile_dispatch', request, state)
            new['input_hash'] = 'same'
            new['unresolved'] = ['TC-1']
            with self.assertRaises(StateConflict):
                controller.validate('reconcile_dispatch', request, state)
            del new['unresolved']
            evidence.write_text('changed')
            with self.assertRaises(StateConflict):
                controller.validate('reconcile_dispatch', request, state)
            events = [{'type': 'initialize', 'sequence': 1, 'payload': {'dispatches': state['dispatches']}},
                      {'type': 'reconcile_dispatch', 'sequence': 2, 'payload': request}]
            projected = projection(events)
            self.assertEqual(projected['dispatches']['old']['status'], 'superseded')
            self.assertEqual(projected['dispatches']['old']['superseded_by'], 'new')
            self.assertEqual(projected['dispatches']['new']['status'], 'accepted')


if __name__ == '__main__':
    unittest.main()
