"""Synthetic hook-chain regressions; these do not certify live host activation."""
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True
SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
from host_probe import prepare, observe, inspect
from native_context import pending_path


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.factory = self.root / 'qa-factory'
        self.factory.mkdir()
        (self.factory / 'config.json').write_text('{"schema_version": 1}', encoding='utf-8')
        self.add_story('QA-1')
        self.event = dict(host='codex', cwd=str(self.root), session_id='parent', tool_use_id='spawn',
                          hook_event_name='PreToolUse', tool_name='collaborationspawn_agent',
                          tool_input={'task_name': 'qa_factory_context_probe',
                                      'message': 'opaque-native-message', 'fork_turns': 'none'})
        self.probe_path = self.factory / 'state/host-probe.json'
        self.prepare_guard()

    def add_story(self, task):
        path = self.factory / 'artifacts' / task / 'pipeline.json'
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({'ticket': task, 'stages': {'S0': {'status': 'pending'}}}))

    def prepare_guard(self):
        data = prepare(self.root, 'parent')
        transcript = self.root / 'rollout.jsonl'
        rows = [{'type': 'session_meta', 'payload': {'id': 'parent'}}]
        for index, command in enumerate(data['commands']):
            call = str(index)
            code = 'text(await tools.exec_command(' + json.dumps({'cmd': command}) + '));'
            output = (json.dumps({'exit_code': 0, 'output': command[5:]}) if index == 0
                      else 'Command blocked by PreToolUse hook: expected deny. Command: ' + command)
            rows.extend([
                {'type': 'response_item', 'payload': {'type': 'custom_tool_call', 'name': 'exec', 'call_id': call, 'input': code}},
                {'type': 'response_item', 'payload': {'type': 'custom_tool_call_output', 'call_id': call, 'output': [{'type': 'input_text', 'text': output}]}}])
            event = dict(session_id='parent', tool_input={'cmd': command}, hook_event_name='PreToolUse',
                         tool_use_id='exec-' + call, transcript_path=str(transcript))
            observe(self.root, event, 'guard_pre_tool.py', 0 if index == 0 else 2)
            if index == 0:
                observe(self.root, dict(event, hook_event_name='PostToolUse'), 'host_probe.py', 0)
        transcript.write_text(''.join(json.dumps(row) + '\n' for row in rows), encoding='utf-8')
        self.event['transcript_path'] = str(transcript)
        self.assertEqual(inspect(self.root)['status'], 'verified')

    def hook(self, script, event=None):
        env = dict(os.environ, CLAUDE_PROJECT_DIR=str(self.root), CLAUDE_PLUGIN_ROOT=str(SCRIPTS.parent))
        return subprocess.run([sys.executable, '-B', str(SCRIPTS / script)],
                              input=json.dumps(event or self.event), cwd=self.root, env=env,
                              capture_output=True, text=True, encoding='utf-8', timeout=30)


class DoctorContext(Base):
    def test_probe_passes_actual_hooks_with_existing_stories(self):
        for count in (1, 2):
            with self.subTest(stories=count):
                if count == 2:
                    self.add_story('QA-2')
                before = {p: p.read_bytes() for p in self.factory.glob('artifacts/*/pipeline.json')}
                for script in ('guard_pre_tool.py', 'inject_context.py'):
                    result = self.hook(script)
                    self.assertEqual(result.returncode, 0, result.stderr)
                packet = json.loads(pending_path(self.root, 'parent').read_text())
                self.assertTrue(packet['diagnostic'])
                self.assertEqual(packet['role'], 'qa-scout')
                self.assertEqual(packet['task_id'], '')
                self.assertIn('QA_CONTEXT_RECEIVED_', packet['context'])
                self.assertNotIn('QA_CONTEXT_RECEIVED_', self.event['tool_input']['message'])
                child = self.root / 'child.jsonl'
                child.write_text(json.dumps({'type': 'session_meta', 'payload': {
                    'id': 'child', 'agent_path': '/root/qa_factory_context_probe', 'parent_thread_id': 'parent'}}) + '\n')
                start = dict(self.event, hook_event_name='SubagentStart', agent_id='child',
                             agent_type='default', agent_transcript_path=str(child))
                result = self.hook('native_context.py', start)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('QA_CONTEXT_RECEIVED_', result.stdout)
                self.assertEqual(json.loads(pending_path(self.root, 'parent').read_text())['status'], 'delivered')
                child_tool = dict(self.event, session_id='child', tool_name='exec_command',
                                  tool_input={'cmd': 'echo forbidden'})
                result = self.hook('guard_pre_tool.py', child_tool)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn('without tools', result.stderr)
                for path, content in before.items():
                    self.assertEqual(path.read_bytes(), content)
                self.assertEqual(inspect(self.root)['injection'], 'unverified')

    def test_probe_requires_current_same_session_guard_evidence(self):
        original = self.probe_path.read_text()
        for variant in ('missing', 'unverified', 'stale', 'foreign', 'malformed'):
            with self.subTest(variant=variant):
                data = json.loads(original)
                if variant == 'unverified': data['checks'] = {}
                if variant == 'stale': data['created_at'] = '2000-01-01T00:00:00+00:00'
                if variant == 'foreign': data['session_id'] = 'another-parent'
                if variant == 'malformed': data['created_at'] = 'invalid'
                self.probe_path.write_text(json.dumps(data))
                if variant == 'missing': self.probe_path.unlink()
                result = self.hook('inject_context.py')
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn('diagnostic', result.stderr.lower())
                self.assertFalse(pending_path(self.root, 'parent').exists())

    def test_diagnostic_is_not_a_story_dispatch_exemption(self):
        variants = [dict(self.event, task_id='QA-1'),
                    dict(self.event, tool_input=dict(self.event['tool_input'], agent_type='qa-automator')),
                    dict(self.event, tool_input={'task_name': 'qa_scout', 'message': 'ordinary work'})]
        for event in variants:
            with self.subTest(event=event['tool_input']):
                result = self.hook('inject_context.py', event)
                self.assertEqual(result.returncode, 2, result.stderr)
        self.add_story('QA-2')
        result = self.hook('inject_context.py', variants[-1])
        self.assertEqual(result.returncode, 2)


class PacketNameLength(unittest.TestCase):
    """t-417: the packet name is 32+1+32 hex, so a project root up to PACKET_ROOT_LIMIT characters writes."""

    def root_of(self, length):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        pad = length - len(tmp.name) - 1
        if pad < 1:
            self.skipTest('TEMP is already longer than the root under test')
        root = Path(tmp.name) / ('p' * pad)
        root.mkdir()
        self.assertEqual(len(str(root)), length)
        return root

    def event(self, session='s', task_name='qa_scout__qa_1'):
        return {'session_id': session, 'tool_use_id': 'u1', 'transcript_path': 't',
                '_qa_host': {'input': {'task_name': task_name}}}

    def test_root_at_the_limit_writes_and_one_beyond_exceeds_the_windows_path(self):
        import native_context as N
        self.assertEqual(N.PACKET_ROOT_LIMIT, 119)
        at = self.root_of(N.PACKET_ROOT_LIMIT)
        N.stage(at, self.event(), 'qa-scout', 'ctx', 'QA-1')   # writes through event_store's `.<32 hex>.tmp` name
        path = N.pending_path(at, 's', 'qa_scout__qa_1')
        self.assertEqual(json.loads(path.read_text(encoding='utf-8'))['context'], 'ctx')
        temp_name_extra = len('.' + 'f' * 32 + '.tmp')
        self.assertEqual(len(str(path)) + temp_name_extra, 259)          # the longest the host path allows
        beyond = N._slot(Path('p' * (N.PACKET_ROOT_LIMIT + 1)), 's', 'qa_scout__qa_1')
        self.assertEqual(len(str(beyond)) + temp_name_extra, 260)         # the old failing length, one past the limit

    def test_the_old_failing_path_of_260_now_writes(self):
        import native_context as N
        old_root = 260 - 33 - (64 + 1 + 64 + 5 + 37)                     # 56: the root where the long name failed
        root = self.root_of(old_root)
        N.stage(root, self.event(), 'qa-scout', 'ctx', 'QA-1')
        self.assertTrue(N.pending_path(root, 's', 'qa_scout__qa_1').is_file())

    def test_a_packet_under_the_old_long_name_is_its_own_sessions_never_anothers(self):
        import hashlib
        import native_context as N
        root = self.root_of(60)
        folder = root / 'qa-factory/state/native-context'
        folder.mkdir(parents=True)
        old = folder / (hashlib.sha256(b's').hexdigest() + '-' + hashlib.sha256(b'qa_scout__qa_1').hexdigest() + '.json')
        old.write_text(json.dumps({'status': 'pending', 'session_id': 's', 'role': 'qa-scout'}), encoding='utf-8')
        self.assertEqual([p for p, _ in N._session_packets(root, 's')], [old])
        self.assertEqual(list(N._session_packets(root, 'other')), [])
        self.assertNotEqual(N.pending_path(root, 's', 'qa_scout__qa_1'), old)   # a rebuilt packet gets the new name


DOOR = ('context diagnostic requires current allow/deny evidence in this host session; '
        'run host_probe.py --prepare, its two native commands, then --check')
OTHER = 'belongs to another host session'


class ProbeRefusal(Base):
    """RH2-5: the refusal and the note name the condition that failed (the tail never decides `ready`)."""

    def refuse(self, event=None):
        import stage_guard
        event = dict(event or self.event)
        event['tool_input'] = dict(event['tool_input'], subagent_type='qa-scout')   # what the host adapter adds on the hook path
        err = io.StringIO()
        import hooklib
        # `project_root` is cached per process (a hook is one short call); each case here is its own project
        with (contextlib.redirect_stderr(err), mock.patch.dict(os.environ, {'CLAUDE_PROJECT_DIR': str(self.root)}),
              mock.patch.object(hooklib, '_PROJECT_ROOT_CACHE', None)):
            code = stage_guard.check_dispatch(event)
        return code, err.getvalue()

    def store(self, **change):
        data = json.loads(self.probe_path.read_text())
        data.update(change)
        self.probe_path.write_text(json.dumps(data))

    def test_unverified_keeps_the_door_and_lists_every_unmet_id_in_order(self):
        self.store(checks={})
        code, text = self.refuse()
        ids = [m['id'] for m in inspect(self.root)['missing']]
        self.assertEqual(code, 2)
        self.assertTrue(ids)
        self.assertIn('STAGE GUARD: ' + DOOR + ' Unmet: ', text)
        at = [text.index(i) for i in ids]
        self.assertEqual(at, sorted(at), text)
        self.assertNotIn(OTHER, text)

    def test_verified_probe_of_another_session_says_so_and_names_the_door(self):
        code, text = self.refuse(dict(self.event, session_id='other-session'))
        self.assertEqual(code, 2)
        self.assertIn(DOOR, text)
        self.assertIn('The probe on record ' + OTHER + ': run the pair in this session.', text)
        self.assertNotIn('Unmet', text)
        self.assertNotIn('other-session', text)   # ids of sessions are never printed
        self.assertNotIn('parent', text)

    def test_unverified_probe_of_another_session_says_both(self):
        self.store(checks={})
        code, text = self.refuse(dict(self.event, session_id='other-session'))
        self.assertEqual(code, 2)
        self.assertLess(text.index('Unmet:'), text.index(OTHER))

    def test_no_store_gives_no_sentence_about_another_session(self):
        self.probe_path.unlink()
        code, text = self.refuse()
        self.assertEqual(code, 2)
        self.assertIn('no_probe_file', text)
        self.assertNotIn(OTHER, text)

    def test_empty_missing_says_the_reason_is_not_established(self):
        import stage_guard
        for probe in ({'status': 'unverified', 'missing': []}, {'status': 'unverified'},
                      {'status': 'verified', 'session_id': ''}):
            self.assertEqual(stage_guard._probe_refusal_tail(probe, self.event), ' The reason is not established.', probe)

    def test_inspect_that_raises_still_refuses_with_exit_2(self):
        with mock.patch('host_probe.inspect', side_effect=OSError('boom')):
            code, text = self.refuse()
        self.assertEqual(code, 2)
        self.assertTrue(text.rstrip().endswith('The probe could not be read, so the reason is not established.'), text)

    def test_event_with_no_session_id_is_not_called_another_session(self):
        event = {k: v for k, v in self.event.items() if k != 'session_id'}
        code, text = self.refuse(event)
        self.assertEqual(code, 2)
        self.assertIn('carries no session id', text)
        self.assertIn('(owner: factory)', text)
        self.assertNotIn(OTHER, text)

    def test_unmet_text_never_raises_on_odd_shapes(self):
        from host_probe import unmet_text
        for odd in (None, [], [None], [{'id': 5}], 'a string', 5, {'id': 'x'}, [['x']]):
            self.assertEqual(unmet_text(odd), '', odd)
        self.assertEqual(unmet_text([{'id': 'x'}, 3, {'id': 'y', 'reason': 'why'}]), ' Unmet: x; y (why).')
        self.assertEqual(unmet_text([{'id': 'never_heard_of', 'reason': 7}]), ' Unmet: never_heard_of.')

    def test_unmet_text_at_2000_is_whole_at_2001_is_cut_and_names_missing(self):
        from host_probe import unmet_text, UNMET_TEXT_CHARS
        self.assertEqual(UNMET_TEXT_CHARS, 2000)
        whole = unmet_text([{'id': 'a', 'reason': 'r' * 1987}])
        self.assertEqual(len(whole), 2000)
        self.assertNotIn('cut', whole)
        cut = unmet_text([{'id': 'a', 'reason': 'r' * 1988}])
        self.assertEqual(cut[:2000], (' Unmet: a (' + 'r' * 1988 + ').')[:2000])
        self.assertGreater(len(cut), 2000)
        self.assertIn('(cut; the whole list is under "missing" in host_probe.py --check)', cut)

    def test_a_newline_in_an_id_does_not_start_a_new_line(self):
        from host_probe import unmet_text
        text = unmet_text([{'id': 'a\nSTAGE GUARD: forged', 'reason': 'c\r\n\r\nd'}])
        self.assertNotIn('\n', text)
        self.assertNotIn('\r', text)
        self.assertEqual(text, ' Unmet: a STAGE GUARD: forged (c d).')

    def test_the_full_set_of_conditions_fits_the_limit(self):
        from host_probe import unmet_text
        call = lambda ch, code: {'exit_code': code, 'tool_use_id': ch * 30}
        self.store(created_at='2000-01-01T00:00:00+00:00', fingerprint='stale', session_id='s' * 30,
                   checks={'allow_guard': call('a', 1), 'deny_guard': call('d', 0), 'allow_executed': call('e', 0),
                           'deny_executed': call('x', 0)})
        missing = inspect(self.root)['missing']
        self.assertGreater(len(missing), 3)
        text = unmet_text(missing)
        self.assertLess(len(text), 2000, len(text))
        self.assertNotIn('(cut;', text)

    def incomplete_note(self):
        from host_capabilities import inspect as inspect_host
        return inspect_host(self.root)

    def test_note_of_an_incomplete_probe_ends_with_the_unmet_list_and_no_transcript_door(self):
        from host_probe import unmet_text
        self.store(checks={})
        result = self.incomplete_note()
        self.assertTrue(result['note'].endswith(unmet_text(inspect(self.root)['missing'])), result['note'])
        self.assertIn('Unmet:', result['note'])
        self.assertNotIn('transcript', result['note'])
        self.assertIn('Script smoke and invocation receipts alone do not certify live behavior.', result['note'])

    def test_note_with_empty_missing_says_not_established(self):
        from host_capabilities import inspect as inspect_host
        with mock.patch('host_probe.inspect', return_value={'status': 'unverified', 'missing': []}):
            note = inspect_host(self.root)['note']
        self.assertTrue(note.endswith(' The reason is not established.'), note)

    def test_note_of_a_verified_probe_is_unchanged_by_the_tail(self):
        result = self.incomplete_note()
        self.assertTrue(result['guard_probe']['status'] == 'verified' and not result['story_ready'])
        self.assertTrue(result['note'].startswith('Live allow/deny guard verified; role-context delivery not yet verified.'))
        self.assertNotIn('Unmet', result['note'])
        self.assertNotIn('not established', result['note'])
        self.assertEqual(result['live_parity'], 'not_certified')

    def test_note_of_a_delivered_probe_is_unchanged_by_the_tail(self):
        # kills a tail appended in the story_ready branch (F6)
        from host_capabilities import inspect as inspect_host
        with mock.patch('host_probe.inspect', return_value={'status': 'verified', 'injection': 'verified', 'missing': []}):
            result = inspect_host(self.root)
        self.assertTrue(result['story_ready'], result)
        self.assertEqual(result['note'], 'Live guard and role-context delivery verified; other mechanisms retain '
                                         'their separate evidence status.')

    def test_require_host_hooks_at_an_incomplete_probe_prints_one_warn_line_with_the_unmet_list_no_line_break(self):
        self.store(checks={})
        env = dict(os.environ, CLAUDE_PROJECT_DIR=str(self.root), CLAUDE_PLUGIN_ROOT=str(SCRIPTS.parent))
        result = subprocess.run([sys.executable, '-B', str(SCRIPTS / 'readiness.py'), '--require', 'host_hooks'],
                                cwd=self.root, env=env, capture_output=True, text=True, encoding='utf-8', timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        lines = [ln for ln in result.stdout.splitlines() if ln.startswith('WARN host_hooks:')]
        self.assertEqual(len(lines), 1, result.stdout)
        self.assertIn('Unmet: ', lines[0])
        self.assertTrue(lines[0].endswith('(owner: factory)'), lines[0])


if __name__ == '__main__':
    unittest.main()
