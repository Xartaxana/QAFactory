"""Doctor reports local Git, transport access, API access and hook stages independently."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from readiness import check_vcs
from vcs_evidence import AccessError, git_readiness, readiness
from host_capabilities import inspect as inspect_host
from host_probe import prepare, observe, inspect


def result(stdout='', returncode=0):
    return subprocess.CompletedProcess([], returncode, stdout, '')


class DoctorAccess(unittest.TestCase):
    def test_ssh_access_survives_api_failure(self):
        calls = []
        def run(cmd, **kwargs):
            calls.append((cmd, kwargs))
            if cmd == ['git', 'remote']: return result('upstream\norigin\n')
            if cmd[:3] == ['git', 'remote', 'get-url']:
                return result('git@gitlab.example:team/repo.git\n')
            if cmd[:2] == ['git', 'ls-remote']:
                return result('a' * 40 + '\tHEAD\n')
            if cmd == ['git', 'config', '--get', 'core.sshCommand']: return result('', 1)
            raise AssertionError(cmd)
        with patch('shutil.which', return_value='git'), patch('subprocess.run', side_effect=run), \
             patch('vcs_evidence.api', side_effect=AccessError('unauthenticated')):
            vcs = check_vcs(Path('.'), True)
            api = readiness({'adapters': {'vcs': {'name': 'gitlab'}}}, Path('.'))
        self.assertEqual(vcs['status'], 'ok')
        self.assertEqual(vcs['remote_read']['status'], 'ok')
        self.assertEqual(vcs['remote_read']['transport'], 'ssh')
        self.assertEqual(api['status'], 'missing')
        self.assertIn('only operations requiring', api['note'])
        shell = next(kw for cmd, kw in calls if cmd[1] == 'ls-remote')
        self.assertEqual(shell['env']['GIT_TERMINAL_PROMPT'], '0')
        self.assertEqual(shell['timeout'], 20)

    def test_existing_ssh_command_is_preserved(self):
        with patch.dict(os.environ, {}, clear=True), patch('subprocess.run', side_effect=[
                result('git@gitlab.example:team/repo.git'), result('custom-ssh -i project-key'),
                result('b' * 40 + '\tHEAD\n')]) as run:
            remote = git_readiness(Path('.'))
        self.assertEqual(remote['status'], 'ok')
        self.assertNotIn('GIT_SSH_COMMAND', run.call_args.kwargs['env'])

    def test_no_remote_network_probe_by_default(self):
        with patch('shutil.which', return_value='git'), patch('subprocess.run', return_value=result('origin\n')) as run:
            vcs = check_vcs(Path('.'))
        self.assertEqual(vcs['remote_read']['status'], 'unknown')
        self.assertEqual(run.call_count, 1)

    def test_network_failure_does_not_claim_bad_auth(self):
        with patch('subprocess.run', return_value=result('git@gitlab.example:team/repo.git')), \
             patch('vcs_evidence.api', side_effect=AccessError('cli_network_or_config_failure')):
            api = readiness({'adapters': {'vcs': {'name': 'gitlab'}}}, Path('.'))
        self.assertEqual(api['status'], 'unknown')
        self.assertNotIn('authentication failed', api['note'])
        with patch('subprocess.run', side_effect=[result('https://example.invalid/repo.git'), result('credential-secret', 128)]):
            remote = git_readiness(Path('.'))
        self.assertEqual(remote['status'], 'unknown')
        self.assertNotIn('credential-secret', json.dumps(remote))
        with patch('subprocess.run', side_effect=subprocess.TimeoutExpired('git', 20)):
            self.assertEqual(git_readiness(Path('.'))['status'], 'unknown')

    def test_ssh_failure_does_not_claim_no_key_exists(self):
        # `ssh -o BatchMode=yes` cannot prompt, so a passphrase-protected key that is merely
        # locked fails exactly like a missing one. The note says what the probe established
        # and offers the door that fits both: it never tells the person the key is absent.
        with patch.dict(os.environ, {}, clear=True), patch('subprocess.run', side_effect=[
                result('git@example.invalid:team/repo.git'), result('', 1), result('', 128)]):
            remote = git_readiness(Path('.'))
        self.assertEqual(remote['status'], 'unknown')
        self.assertEqual(remote['transport'], 'ssh')
        self.assertIn('not verified', remote['note'])
        self.assertIn('unlock an existing passphrase-protected key', remote['note'])
        self.assertIn('SSH key authorization', remote['note'])
        self.assertIn('network', remote['note'])
        self.assertNotIn('credentials', remote['note'])
        self.assertNotIn('empty remote', remote['note'])
        self.assertIn('Local Git remains available', remote['note'])
        # The https note keeps its meaning.
        with patch.dict(os.environ, {}, clear=True), patch('subprocess.run', side_effect=[
                result('https://example.invalid/repo.git'), result('', 128)]):
            https = git_readiness(Path('.'))
        self.assertEqual(https['status'], 'unknown')
        self.assertIn('check network/credentials or an empty remote', https['note'])
        self.assertNotIn('passphrase', https['note'])

    def test_guard_verification_advances_to_context_probe(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data = prepare(root, 'session')
            transcript = root / 'rollout.jsonl'
            rows = [{'type': 'session_meta', 'payload': {'id': 'session'}}]
            for index, command in enumerate(data['commands']):
                call = str(index)
                code = 'const r = await tools.exec_command(' + json.dumps({'cmd': command}) + ');\ntext(JSON.stringify({exit_code:r.exit_code,output:r.output}));'
                output = (json.dumps({'exit_code': 0, 'output': command[5:] + '\r\n'}) if index == 0
                          else 'Command blocked by PreToolUse hook: expected deny. Command: ' + command)
                rows.extend([{'type': 'response_item', 'payload': {'type': 'custom_tool_call', 'name': 'exec', 'call_id': call, 'input': code}},
                             {'type': 'response_item', 'payload': {'type': 'custom_tool_call_output', 'call_id': call, 'output': [{'type': 'input_text', 'text': output}]}}])
                event = dict(session_id='session', tool_input={'cmd': command}, hook_event_name='PreToolUse',
                             tool_use_id='exec-' + call, transcript_path=str(transcript))
                observe(root, event, 'guard_pre_tool.py', 0 if index == 0 else 2)
                if index == 0: observe(root, dict(event, hook_event_name='PostToolUse'), 'host_probe.py', 0)
            transcript.write_text(''.join(json.dumps(r) + '\n' for r in rows))
            probe = inspect(root)
            self.assertEqual(probe['status'], 'verified')
            self.assertEqual(probe['injection'], 'unverified')
            self.assertEqual(probe['next_action'], 'dispatch_context_probe')
            host = inspect_host(root)
            self.assertFalse(host['story_ready'])
            self.assertIn('Dispatch the read-only', host['note'])
            with patch('host_probe.inspect', return_value=dict(probe, injection='verified')):
                host = inspect_host(root)
            self.assertTrue(host['story_ready'])
            self.assertNotIn('not yet verified', host['note'])


if __name__ == '__main__':
    unittest.main()
