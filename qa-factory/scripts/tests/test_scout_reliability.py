"""Incident regressions: waiting, required evidence, storage, API failures and host probes."""
import json
import io
import contextlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import mark_project
from runtime_policy import checkpoint_due
from worker_lifecycle import cancellation, guard
from controller import Controller
from source_inventory import completeness, collect_jira_source
from vcs_evidence import collect, AccessError
from host_probe import prepare, observe, inspect, injection_marker, bind_injection, check_child, host_call_present


class Reliability(unittest.TestCase):
    def test_discovery_does_not_expire(self):
        for seconds in (300, 900, 1800, 5400):
            self.assertFalse(checkpoint_due('qa-scout', {'active_seconds': seconds})['blocking'])
            state = {'dispatches': {'d': {'id': 'd', 'status': 'running'}}}
            self.assertEqual(Controller._next_action_for_state(state)['action'], 'wait_existing_job')
        for reason in ('timeout', 'missing_digest', 'normal_window_exceeded'):
            with self.assertRaises(ValueError): cancellation({'cause': reason, 'evidence_ref': 'x'})
        with self.assertRaises(ValueError): cancellation({'cause': 'source_blocker', 'evidence_ref': 'x'})
        self.assertFalse(cancellation({'cause': 'user_stop', 'evidence_ref': 'x', 'tool_active': True})['retry_charge'])

    def test_native_cancel_is_denied_without_controller_authority(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = root / 'qa-factory/state/host-dispatches'; folder.mkdir(parents=True)
            (folder / 'b.json').write_text(json.dumps({'agent_id': 'child', 'task_name': 'qa_scout__t', 'status': 'running'}))
            with patch('hooklib.project_root', return_value=root):
                for name, ti in [('interrupt_agent', {'target': 'child'}), ('collaborationinterrupt_agent', {'target': 'qa_scout__t'}), ('close_agent', {'id': 'child'}), ('send_input', {'id': 'child', 'interrupt': True})]:
                    with self.assertRaises(SystemExit) as exc: guard({'tool_name': name, 'tool_input': ti})
                    self.assertEqual(exc.exception.code, 2)
                guard({'tool_name': 'send_input', 'tool_input': {'id': 'child', 'message': 'status'}})

    def test_stale_host_receipt_does_not_block_controller_replacement(self):
        from worker_lifecycle import binding_is_active
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state = root / 'qa-factory/artifacts/TASK-1/state'; state.mkdir(parents=True)
            receipt = {'task_id': 'TASK-1', 'dispatch_id': 'S5-qa-automator-19',
                       'status': 'running'}
            controller = {'dispatches': {'S5-qa-automator-19': {
                'id': 'S5-qa-automator-19', 'status': 'returned_unaccepted'}}}
            (state / 'controller.json').write_text(json.dumps(controller), encoding='utf-8')
            self.assertFalse(binding_is_active(root, receipt))
            controller['dispatches']['S5-qa-automator-19']['status'] = 'running'
            (state / 'controller.json').write_text(json.dumps(controller), encoding='utf-8')
            self.assertTrue(binding_is_active(root, receipt))
            (state / 'controller.json').unlink()
            self.assertTrue(binding_is_active(root, receipt))

    def test_a_receipt_is_active_unless_the_controller_recorded_the_dispatch_not_running(self):
        """False only on a recorded controller fact; every doubt keeps the receipt active."""
        from worker_lifecycle import binding_is_active
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state = root / 'qa-factory/artifacts/TASK-1/state'; state.mkdir(parents=True)
            target = state / 'controller.json'
            receipt = {'task_id': 'TASK-1', 'dispatch_id': 'D-1', 'status': 'running'}
            def settle(status):
                target.write_text(json.dumps({'dispatches': {'D-1': {'id': 'D-1', 'status': status}}}), encoding='utf-8')
            for status in ('released_by_person', 'never_started', 'accepted'):
                settle(status)
                self.assertFalse(binding_is_active(root, receipt), status)
            settle('running')
            self.assertTrue(binding_is_active(root, receipt))
            # no recorded status is no recorded fact
            target.write_text(json.dumps({'dispatches': {'D-1': {'id': 'D-1'}}}), encoding='utf-8')
            self.assertTrue(binding_is_active(root, receipt))
            settle('released_by_person')
            self.assertTrue(binding_is_active(root, dict(receipt, dispatch_id='')))
            self.assertTrue(binding_is_active(root, {'task_id': 'TASK-1', 'status': 'running'}))
            self.assertTrue(binding_is_active(root, dict(receipt, task_id='')))
            self.assertTrue(binding_is_active(root, {'dispatch_id': 'D-1', 'status': 'running'}))
            self.assertTrue(binding_is_active(root, dict(receipt, dispatch_id='D-2')))
            for body in ('{not json', '[]', '"text"', 'null', '{"dispatches": []}', '{"dispatches": {"D-1": "x"}}'):
                target.write_text(body, encoding='utf-8')
                self.assertTrue(binding_is_active(root, receipt), body)
            settle('released_by_person')
            for ticket in ('TASK-1/../TASK-1', 'A\\B', 'C:D', '..'):
                self.assertTrue(binding_is_active(root, dict(receipt, task_id=ticket)), ticket)
            # terminal answers without reading anything: no controller.json exists at all
            target.unlink()
            self.assertFalse(binding_is_active(root, dict(receipt, status='terminal')))
            self.assertFalse(binding_is_active(root, {'status': 'terminal'}))

    def spawn_verdict(self, root, task='TASK-1', role='qa-automator'):
        """(exit code, stderr) of the spawn guard for a role of a story whose host is ready."""
        event = {'tool_name': 'spawn_agent', 'tool_input': {'agent_type': role, 'message': 'x'}}
        code = 0
        with patch('hooklib.project_root', return_value=root), \
                patch('stage_guard.requested_ticket', return_value=task), \
                patch('host_capabilities.inspect', return_value={'story_ready': True}), \
                contextlib.redirect_stderr(io.StringIO()) as err:
            try:
                guard(event)
            except SystemExit as stop:
                code = stop.code
        return code, err.getvalue()

    def test_spawn_is_blocked_only_by_an_active_receipt_and_the_block_names_its_door(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state = root / 'qa-factory/artifacts/TASK-1/state'; state.mkdir(parents=True)
            mark_project(root)
            folder = root / 'qa-factory/state/host-dispatches'; folder.mkdir(parents=True)
            def controller(**statuses):
                (state / 'controller.json').write_text(json.dumps({'dispatches': {
                    k: {'id': k, 'status': v} for k, v in statuses.items()}}), encoding='utf-8')
            def receipt(name, **fields):
                body = {'agent_id': name, 'agent_type': 'qa-automator', 'task_id': 'TASK-1', 'status': 'running'}
                body.update(fields)
                (folder / (name + '.json')).write_text(json.dumps(body), encoding='utf-8')
            # a receipt of a dispatch the controller released does not block the replacement
            receipt('a', dispatch_id='S5-qa-automator-19')
            controller(**{'S5-qa-automator-19': 'released_by_person'})
            self.assertEqual(self.spawn_verdict(root)[0], 0)
            # the same receipt of a dispatch still running blocks, and the block names the door
            controller(**{'S5-qa-automator-19': 'running'})
            code, message = self.spawn_verdict(root)
            self.assertEqual(code, 2)
            self.assertIn('already owns this task/role', message)
            self.assertIn('S5-qa-automator-19', message)
            self.assertIn('--operation release --dispatch S5-qa-automator-19 --words', message)
            self.assertIn('controller.py --task-root', message)
            self.assertIn('TASK-1', message)
            # another role of the story, and another story, are not blocked by it
            self.assertEqual(self.spawn_verdict(root, role='qa-scout')[0], 0)
            self.assertEqual(self.spawn_verdict(root, task='TASK-2')[0], 0)
            # two receipts, one settled and one running: blocks, and names the running one
            receipt('b', dispatch_id='S5-qa-automator-20')
            controller(**{'S5-qa-automator-19': 'accepted', 'S5-qa-automator-20': 'running'})
            code, message = self.spawn_verdict(root)
            self.assertEqual(code, 2)
            self.assertIn('S5-qa-automator-20', message)
            self.assertNotIn('S5-qa-automator-19', message)
            # a terminal receipt blocks nothing
            controller(**{'S5-qa-automator-19': 'running', 'S5-qa-automator-20': 'running'})
            receipt('a', dispatch_id='S5-qa-automator-19', status='terminal')
            receipt('b', dispatch_id='S5-qa-automator-20', status='terminal')
            self.assertEqual(self.spawn_verdict(root)[0], 0)
            # an unbound receipt blocks, and says that release cannot address it
            receipt('c', dispatch_id=None)
            code, message = self.spawn_verdict(root)
            self.assertEqual(code, 2)
            self.assertIn('names no dispatch', message)
            self.assertNotIn('--operation release --dispatch', message)
            # the controller is unreadable: every doubt keeps the receipt active
            receipt('c', dispatch_id='S5-qa-automator-21')
            (state / 'controller.json').write_text('{not json', encoding='utf-8')
            self.assertEqual(self.spawn_verdict(root)[0], 2)

    def test_active_binding_counts_only_for_the_story_it_names(self):
        from worker_lifecycle import active_binding
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = root / 'qa-factory/state/host-dispatches'; folder.mkdir(parents=True)
            def receipt(name, **fields):
                body = {'agent_id': name, 'dispatch_id': 'S5-qa-automator-12', 'status': 'running'}
                body.update(fields)
                (folder / (name + '.json')).write_text(json.dumps(body), encoding='utf-8')
            receipt('foreign', task_id='QA-OTHER')
            receipt('none')
            receipt('empty', task_id='')
            self.assertIsNone(active_binding(root, 'S5-qa-automator-12', 'QA-9'))
            receipt('own', task_id='QA-9')
            self.assertEqual(active_binding(root, 'S5-qa-automator-12', 'QA-9')['agent_id'], 'own')
            receipt('own', task_id='QA-9', status='terminal')
            self.assertIsNone(active_binding(root, 'S5-qa-automator-12', 'QA-9'))

    def test_checkpoint_waits_for_this_storys_worker_and_not_for_another_storys(self):
        from event_store import StateConflict
        from host_dispatch import binding_path
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); task = root / 'qa-factory/artifacts/TASK-1'; task.mkdir(parents=True)
            mark_project(root)    # the project marker: no marker, no project, no veto (t-622)
            c = Controller(task)
            state = {'source_revision': 'fixture', 'dispatches': {'d': {'id': 'd', 'status': 'running'}}, 'stages': {}}
            path = binding_path(root, 'child'); path.parent.mkdir(parents=True)
            path.write_text(json.dumps({'task_id': 'TASK-1', 'dispatch_id': 'd', 'status': 'running'}))
            with self.assertRaisesRegex(StateConflict, 'host worker is still active'):
                c.validate('checkpoint', {'id': 'd', 'status': 'blocked'}, state)
            # the same dispatch id in another story, or a receipt naming no story, is not this one
            for owner in ('TASK-OTHER', None, ''):
                path.write_text(json.dumps({'task_id': owner, 'dispatch_id': 'd', 'status': 'running'}))
                try:
                    c.validate('checkpoint', {'id': 'd', 'status': 'blocked', 'remaining': ['x'], 'reason': 'y'}, state)
                except (StateConflict, ValueError) as refusal:
                    self.assertNotIn('host worker is still active', str(refusal), owner)

    def test_unavailable_source_and_material_block(self):
        seen = {'words': 'agreed', 'shown': {'relevance': 'unknown'}}
        item = {'source_id': 's', 'required': True, 'status': 'unavailable', 'relevance': 'unknown',
                'human_review': seen}
        self.assertTrue(completeness({'sources': [item]})['gate_blocked'])
        item.update(status='read', relevance='relevant', inspection_status='read',
                    human_review={'words': 'agreed', 'shown': {'relevance': 'relevant'}},
                    materials={k: {'status': 'read', 'count': 0} for k in ('comments', 'attachments', 'external_media')})
        self.assertFalse(completeness({'sources': [item]})['gate_blocked'])
        item['materials']['external_media']['status'] = 'unavailable'
        self.assertTrue(completeness({'sources': [item]})['gate_blocked'])

    def test_a_persons_word_passes_an_unavailable_material(self):
        item = {'source_id': 's', 'required': True, 'status': 'read', 'relevance': 'relevant',
                'inspection_status': 'read',
                'human_review': {'words': 'agreed', 'shown': {'relevance': 'relevant'}},
                'materials': {'comments': {'status': 'read'}, 'attachments': {'status': 'read', 'items': []},
                              'external_media': {'status': 'unavailable'}}}
        self.assertTrue(completeness({'sources': [item]})['gate_blocked'])
        item['gap_acceptance'] = {'words': 'go on without the video'}
        summary = completeness({'sources': [item]})
        self.assertFalse(summary['gate_blocked'])
        self.assertEqual(summary['accepted_gaps'], ['s'])
        self.assertFalse(summary['complete'])  # passed is not the same fact as complete
        item['gap_acceptance'] = {'words': '   '}
        self.assertTrue(completeness({'sources': [item]})['gate_blocked'])

    def test_an_excluded_source_owes_no_materials(self):
        kept = {'source_id': 'k', 'required': True, 'status': 'read', 'relevance': 'relevant',
                'inspection_status': 'read',
                'human_review': {'words': 'agreed', 'shown': {'relevance': 'relevant'}},
                'materials': {k: {'status': 'read'} for k in ('comments', 'attachments', 'external_media')}}
        left_out = {'source_id': 'x', 'required': True, 'status': 'excluded', 'relevance': 'not_relevant',
                    'inspection_status': 'pending',
                    'human_review': {'words': 'agreed', 'shown': {'relevance': 'not_relevant'}},
                    'materials': {'attachments': {'status': 'read', 'items': [
                        {'attachment_id': '1', 'status': 'read', 'analysis_status': 'pending'},
                        {'attachment_id': '2', 'status': 'read', 'analysis_status': 'unavailable'}]}}}
        summary = completeness({'sources': [kept, left_out]})
        self.assertFalse(summary['gate_blocked'])
        self.assertEqual(summary['incomplete_materials'] + summary['unavailable_materials'], [])

    def test_nothing_passes_before_a_person_saw_the_decisions(self):
        item = {'source_id': 's', 'required': True, 'status': 'read', 'relevance': 'relevant',
                'inspection_status': 'read',
                'materials': {k: {'status': 'read'} for k in ('comments', 'attachments', 'external_media')}}
        summary = completeness({'sources': [item]})
        self.assertTrue(summary['review_missing'] and summary['gate_blocked'] and summary['awaiting_review'])
        item['human_review'] = {'words': 'agreed', 'shown': {'relevance': 'relevant'}}
        self.assertFalse(completeness({'sources': [item]})['gate_blocked'])
        # a source found after the review goes to gate A; it does not reopen the stop
        late = dict(item, source_id='late'); late.pop('human_review')
        summary = completeness({'sources': [item, late]})
        self.assertFalse(summary['gate_blocked'])
        self.assertEqual(summary['unreviewed'], ['late'])
        # a decision flipped after the review is unreviewed again
        item['relevance'] = 'not_relevant'; item['status'] = 'excluded'
        self.assertTrue(completeness({'sources': [item]})['review_missing'])

    def test_attachment_failure_keeps_body_and_other_originals(self):
        class Client:
            base_url = 'https://jira.invalid'; acceptance_criteria_fields = []
            def issue(self, key):
                return {'key': key, 'fields': {'updated': 'rev', 'summary': 'subject', 'attachment': [
                    {'id': '1', 'filename': 'long-' * 50 + '.md', 'content': 'one', 'size': 3},
                    {'id': '2', 'filename': 'same.md', 'content': 'two', 'size': 3}]}}
            def all_comments(self, *a): return []
            def get_bytes(self, url):
                if url == 'two': raise OSError('path too long')
                return b'one'
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'deep-project-root' / 'work' / 'source-inventory.json'
            item = collect_jira_source(Client(), 'TASK-1', output)
            self.assertEqual(item['status'], 'read')
            self.assertTrue((output.parent / item['snapshot_ref']).is_file())
            one, two = item['materials']['attachments']['items']
            self.assertEqual(one['status'], 'read')
            self.assertEqual(len(one['local_ref']), 70)
            self.assertEqual(two['status'], 'unavailable')
            self.assertTrue(completeness({'sources': [item]})['gate_blocked'])

    def test_mr_access_and_pagination(self):
        calls = []
        def read(host, endpoint):
            calls.append(endpoint)
            if endpoint == 'user' or endpoint.count('/') == 1: return {'id': 1}
            if '?' not in endpoint: return {'sha': 'revision', 'updated_at': 'now'}
            return [{'id': i} for i in range(100)] if endpoint.endswith('&page=1') else [{'id': 100}]
        for iid in (11, 12):
            row = collect(f'https://gitlab.invalid/team/project/-/merge_requests/{iid}', read)
            self.assertTrue(row['complete'])
            for name in ('notes', 'discussions', 'diffs'): self.assertEqual(len(row[name]), 101)
        def denied(*a): raise AccessError('unauthenticated')
        row = collect('https://gitlab.invalid/team/project/-/merge_requests/11', denied)
        self.assertEqual(row['error'], 'unauthenticated')
        self.assertFalse(row['complete'])
        self.assertFalse(row['api_authenticated'])

    def test_links_inside_original_attachment_enter_required_inventory(self):
        class Client:
            base_url = 'https://jira.invalid'; acceptance_criteria_fields = []; api_version = '2'
            project_keys = []
            def issue(self, key):
                return {'key': key, 'fields': {'updated': 'rev', 'summary': 'subject', 'attachment': [
                    {'id': '1', 'filename': 'review.md', 'content': 'one'}]}}
            def all_comments(self, *a): return []
            def get_bytes(self, url): return b'Tested subject PRODUCT-22; https://gitlab.invalid/team/project/-/merge_requests/11'
            # PRODUCT is an unknown prefix: one probe of the project, not of PRODUCT-22
            # itself, confirms it before the key becomes a pending mention.
            def get_json(self, path): return {'key': 'PRODUCT'}
        with tempfile.TemporaryDirectory() as tmp:
            row = collect_jira_source(Client(), 'TASK-1', Path(tmp) / 'work/source-inventory.json')
            self.assertIn('PRODUCT-22', row['mentioned_ticket_keys'])
            self.assertEqual(row['materials']['external_media']['count'], 1)
            self.assertEqual(row['materials']['external_media']['status'], 'pending')

    def test_host_probe_rejects_receipts_without_host_calls_and_stale_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root / 'qa-factory').mkdir()
            cfg = root / 'qa-factory/config.json'; cfg.write_text('{}')    # written by hand on purpose: the config's CONTENT is the subject (its change makes the probe stale)
            data = prepare(root, 's')
            transcript = root / 'rollout.jsonl'; transcript.write_text('')
            for i, cmd in enumerate(data['commands']):
                ev = {'session_id': 's', 'tool_input': {'cmd': cmd}, 'hook_event_name': 'PreToolUse', 'tool_use_id': str(i), 'transcript_path': str(transcript)}
                observe(root, ev, 'guard_pre_tool.py', 0 if i == 0 else 2)
                if i == 0:
                    observe(root, dict(ev, hook_event_name='PostToolUse'), 'host_probe.py', 0)
            self.assertEqual(inspect(root)['status'], 'unverified')
            transcript.write_text(''.join(json.dumps({'type': 'response_item', 'payload': {'type': 'function_call', 'call_id': str(i)}})+'\n' for i in (0, 1)))
            self.assertEqual(inspect(root)['status'], 'verified')
            cfg.write_text('{"changed":true}')
            self.assertEqual(inspect(root)['status'], 'stale')

    def test_defaults_for_current_codex_models_are_unconfirmed(self):
        from cost_capture import resolve_rate, value_usage
        for model in ('gpt-6-astra', 'gpt-5.6-sol', 'gpt-5.6-terra', 'gpt-5.6-luna', 'gpt-5.5'):
            self.assertIsNotNone(resolve_rate(model, {})[0])
            valued = value_usage({'requests': 1, 'input': 1000, 'session_input_tokens': 1000}, model, {})
            self.assertEqual(valued['tariff_confirmation'], 'unconfirmed')
            self.assertEqual(valued['pricing_coverage'], 'complete')
        self.assertEqual(value_usage({'input': 100}, 'gpt-unknown', {})['pricing_coverage'], 'none')

    def test_code_mode_probe_requires_same_session_literal_call_and_real_outcome(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'rollout.jsonl'
            for kind in ('ALLOW', 'DENY'):
                command = 'echo QA_FACTORY_PROBE_' + kind + '_nonce'
                receipt = dict(tool_use_id='exec-inner', session_id='s', command=command, transcript_path=str(path))
                code = 'text(await tools.exec_command({cmd:' + json.dumps(command) + ',max_output_tokens:2000}));'
                result = (json.dumps(dict(exit_code=0, output=command[5:]+'\n')) if kind == 'ALLOW'
                          else 'Command blocked by PreToolUse hook: expected probe. Command: ' + command)
                rows = [dict(type='session_meta', payload=dict(id='s')),
                        dict(type='response_item', payload=dict(type='custom_tool_call', name='functions.exec', call_id='outer', input=code)),
                        dict(type='response_item', payload=dict(type='custom_tool_call_output', call_id='outer', output=[dict(type='input_text', text=result)]))]
                def save(): path.write_text(''.join(json.dumps(r)+'\n' for r in rows))
                variants = [code,
                    'const r = await tools.exec_command(' + json.dumps({'cmd': command}) + ');\ntext(JSON.stringify({exit_code:r.exit_code,output:r.output}));\n',
                    'let result = await tools.exec_command(' + json.dumps({'cmd': command}) + '); text(result);',
                    'const result = await tools.exec_command(' + json.dumps({'cmd': command}) + '); text(JSON.stringify(result));']
                for variant in variants:
                    rows[1]['payload']['input'] = variant
                    save(); self.assertTrue(host_call_present(receipt), variant)
                rows[1]['payload']['input'] = ('const r = await tools.exec_command('
                                             + json.dumps({'cmd': command}) + '); text(r.output);')
                rows[-1]['payload']['output'][0]['text'] = command[5:] + '\r\n' if kind == 'ALLOW' else result
                save(); self.assertTrue(host_call_present(receipt))
                rows[-1]['payload']['output'][0]['text'] = 'unrelated ' + command[5:]
                save(); self.assertFalse(host_call_present(receipt))
                rows[-1]['payload']['output'][0]['text'] = result
                # Native shell selection caused another real Doctor false negative.
                # Extra literal options do not change the nonce-bearing command.
                for options in (
                        {'shell': 'powershell', 'login': False, 'workdir': 'C:\\project',
                         'yield_time_ms': 10000, 'max_output_tokens': 1000},
                        {'shell': '/bin/bash', 'tty': False, 'justification': 'probe',
                         'prefix_rule': ['echo'], 'future_option': {'mode': 'literal'}}):
                    rows[1]['payload']['input'] = ('const r = await tools.exec_command('
                        + json.dumps(dict(cmd=command, **options)) + '); text(r.output);')
                    rows[-1]['payload']['output'][0]['text'] = command[5:] + '\r\n' if kind == 'ALLOW' else result
                    save(); self.assertTrue(host_call_present(receipt), options)
                rows[-1]['payload']['output'][0]['text'] = result
                for invalid in [variants[1].replace('r.exit_code', '0'),
                                variants[1].replace('text(JSON', 'r.output="forged"; text(JSON'),
                                'if (false) { ' + code + ' }', code + code,
                                'text(' + json.dumps(code) + ');',
                                'text(await tools.exec_command({cmd: getCommand(), shell:"powershell"}));',
                                'text(await tools.exec_command({cmd:' + json.dumps(command) + ',shell:getShell()}));']:
                    rows[1]['payload']['input'] = invalid
                    save(); self.assertFalse(host_call_present(receipt), invalid)
                rows[1]['payload']['input'] = code
                save()
                self.assertFalse(host_call_present(dict(receipt, session_id='other')))
                rows[-1]['payload']['call_id'] = 'foreign'; save(); self.assertFalse(host_call_present(receipt))
                rows[-1]['payload']['call_id'] = 'outer'
                rows[1]['payload']['input'] = '// ' + code; save(); self.assertFalse(host_call_present(receipt))

    def test_injection_requires_the_actual_bound_child_response(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = mark_project(Path(tmp))
            prepare(root, 'parent')
            transcript = root / 'parent.jsonl'
            transcript.write_text(json.dumps({'type': 'response_item', 'payload': {'type': 'function_call', 'call_id': 'spawn'}})+'\n')
            event = {'session_id': 'parent', 'tool_use_id': 'spawn', 'transcript_path': str(transcript),
                     'tool_input': {'prompt': 'QA_FACTORY_CONTEXT_PROBE'}}
            marker = injection_marker(root, event).split('Return exactly ')[-1]
            self.assertTrue(marker.startswith('QA_CONTEXT_RECEIVED_'))
            bind_injection(root, event, 'child')
            child = root / 'child.jsonl'
            child.write_text(json.dumps({'type': 'response_item', 'payload': {'type': 'message', 'role': 'user', 'content': [{'text': marker}]}})+'\n')
            stop = {'agent_id': 'child', 'agent_transcript_path': str(child)}
            check_child(root, stop)
            self.assertEqual(inspect(root)['injection'], 'unverified')
            child.write_text(json.dumps({'type': 'response_item', 'payload': {'type': 'message', 'role': 'assistant', 'content': [{'text': marker}]}})+'\n')
            check_child(root, dict(stop, agent_id='foreign'))
            self.assertEqual(inspect(root)['injection'], 'unverified')
            check_child(root, stop)
            self.assertEqual(inspect(root)['injection'], 'verified')
            with child.open('a') as handle:
                handle.write(json.dumps({'type':'event_msg','payload':{'type':'task_complete'}})+'\n')
            self.assertEqual(inspect(root)['injection'], 'verified')
            child.write_text(child.read_text().replace(marker,'tampered'))
            self.assertEqual(inspect(root)['injection'], 'unverified')

    def test_checkpoint_cannot_orphan_a_bound_running_worker(self):
        from event_store import StateConflict
        from host_dispatch import binding_path
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); task = root / 'qa-factory/artifacts/TASK-1'; task.mkdir(parents=True)
            mark_project(root)    # the project marker: no marker, no project, no veto (t-622)
            c = Controller(task)
            state = {'source_revision': 'fixture', 'dispatches': {'d': {'id': 'd', 'status': 'running'}}, 'stages': {}}
            path = binding_path(root, 'child'); path.parent.mkdir(parents=True)
            path.write_text(json.dumps({'task_id': 'TASK-1', 'dispatch_id': 'd', 'status': 'running'}))
            with self.assertRaisesRegex(StateConflict, 'host worker is still active'):
                c.validate('checkpoint', {'id': 'd', 'status': 'blocked'}, state)
            with self.assertRaises(ValueError) as refused:     # t-913: the reference is a field of the request (FR-46)
                c.validate('request_cancel', {'id': 'd', 'cause': 'user_stop', 'evidence_ref': '../missing'}, state)
            self.assertNotIsInstance(refused.exception, StateConflict)
            (task / 'stop.md').write_text('Explicit user stop recorded for the worker')
            c.validate('request_cancel', {'id': 'd', 'cause': 'user_stop', 'evidence_ref': 'stop.md'}, state)

    def test_native_path_only_spawn_binds_verified_child_identity(self):
        from host_adapter import normalize, rewritten_input
        from host_dispatch import record, enrich, binding_path
        with tempfile.TemporaryDirectory() as tmp, patch('hooklib.project_root') as project_root:
            root = mark_project(Path(tmp)); project_root.return_value = root
            prepare(root, 'parent')
            parent = root/'parent.jsonl'
            parent.write_text(json.dumps(dict(type='response_item', payload=dict(type='function_call', call_id='spawn')))+'\n')
            event = normalize(dict(tool_name='collaborationspawn_agent', session_id='parent', tool_use_id='spawn',
                transcript_path=str(parent), tool_input=dict(agent_type='qa-scout', task_name='probe', message='QA_FACTORY_CONTEXT_PROBE')))
            self.assertEqual(event['tool_name'], 'Agent')
            rewritten = rewritten_input(event, dict(event['tool_input'], prompt='injected'))
            self.assertEqual(rewritten['message'], 'injected')
            self.assertNotIn('subagent_type', rewritten)
            marker = injection_marker(root, event).split('Return exactly ')[-1]
            record(dict(event, hook_event_name='PostToolUse', tool_response={'task_name':'/root/probe'}))
            child = root/'child.jsonl'
            rows = [dict(type='session_meta', payload=dict(id='child', parent_thread_id='foreign', agent_path='/root/probe')),
                    dict(type='response_item', payload=dict(type='message', role='assistant', content=[dict(text=marker)]))]
            def save(): child.write_text(''.join(json.dumps(r)+'\n' for r in rows))
            save()
            stop = dict(host='codex', hook_event_name='SubagentStop', session_id='parent', agent_id='child', agent_transcript_path=str(child))
            self.assertNotIn('host_binding', enrich(dict(stop)))
            check_child(root, stop); self.assertEqual(inspect(root)['injection'], 'unverified')
            rows[0]['payload']['parent_thread_id'] = 'parent'; save()
            bound = enrich(dict(stop))
            self.assertEqual(bound['factory_diagnostic'], 'context_probe')
            record(dict(bound, _exit_gate_released=True))
            self.assertEqual(json.loads(binding_path(root, '/root/probe').read_text())['status'], 'terminal')
            self.assertEqual(inspect(root)['injection'], 'verified')

    def test_subagent_start_delivers_without_rewriting_opaque_message(self):
        from native_context import stage, deliver, pending_path, PROBE_TASK
        from host_dispatch import binding_path, record, resolve_binding_path
        from host_adapter import normalize
        from event_store import StateConflict
        with tempfile.TemporaryDirectory() as tmp, patch('hooklib.project_root') as project_root:
            root=mark_project(Path(tmp));project_root.return_value=root
            prepare(root,'parent')
            event=normalize(dict(host='codex',tool_name='collaborationspawn_agent',session_id='parent',tool_use_id='spawn',
                tool_input=dict(task_name=PROBE_TASK,message='opaque-host-message')))
            self.assertEqual(event['tool_input']['subagent_type'], 'qa-scout')
            marker=injection_marker(root,event)
            self.assertIn('QA_CONTEXT_RECEIVED_',marker)
            stage(root,event,'qa-scout','role rules'+marker,'')
            with self.assertRaises(StateConflict): stage(root,event,'qa-scout','other','')
            wrong=dict(host='codex',hook_event_name='SubagentStart',session_id='parent',agent_id='wrong',agent_type='qa-reviewer')
            with contextlib.redirect_stdout(io.StringIO()) as out: deliver(root,wrong)
            self.assertEqual(out.getvalue(),'')
            with contextlib.redirect_stdout(io.StringIO()) as out: deliver(root,dict(wrong,agent_id='child',agent_type='qa-scout'))
            self.assertEqual(json.loads(out.getvalue())['hookSpecificOutput']['additionalContext'],'role rules'+marker)
            self.assertEqual(event['_qa_host']['input']['message'],'opaque-host-message')
            self.assertEqual(json.loads(binding_path(root,'child').read_text())['factory_diagnostic'],'context_probe')
            record(dict(event,hook_event_name='PostToolUse',tool_response={'task_name':'/root/'+PROBE_TASK}))
            self.assertEqual(len(list((root/'qa-factory/state/host-dispatches').glob('*.json'))),1)
            self.assertEqual(resolve_binding_path(root,'/root/'+PROBE_TASK),binding_path(root,'child'))
            self.assertEqual(json.loads(pending_path(root,'parent').read_text())['status'],'delivered')


if __name__ == '__main__':
    unittest.main()
