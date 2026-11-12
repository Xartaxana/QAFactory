"""Bad initialize paths must not poison the durable event log or prevent recovery."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import mark_project
from controller import Controller


class ControllerPaths(unittest.TestCase):
    def test_invalid_initialize_is_rejected_before_commit(self):
        for paths in (['a', 'b'], 'path', {'project_root': []}, {'repository_roots': ['repo']},
                      {'repository_roots': {'repo': None}}):
            with self.subTest(paths=paths), tempfile.TemporaryDirectory() as tmp:
                story = Path(tmp) / 'QA-1'
                story.mkdir()                       # a story folder is created by S0; a journal write never makes one
                c = Controller(story)
                with self.assertRaisesRegex(ValueError, 'known_paths'):
                    c.apply('initialize', {'source_revision': 'source', 'scope': ['QA-1'],
                            'known_paths': paths, 'idempotency_key': 'init', 'expected_revision': 0})
                self.assertEqual(c.store.read(), [])
                self.assertFalse((c.store.state / 'projection-stale.json').exists())

    def test_legacy_list_recovers_without_changing_events_or_task_progress(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = mark_project(Path(tmp).resolve())
            task = project / 'qa-factory/artifacts/QA-1'
            task.mkdir(parents=True)                # S0 creates the story; the journal write below only commits to it
            c = Controller(task)
            old_paths = [str(task), str(task / 'work/ticket.md'), str(project)]
            # Reproduce bytes committed by the old validator, not today's input API.
            c.store.commit('initialize', {'source_revision': 'source', 'scope': ['QA-1'],
                           'known_paths': old_paths, 'legacy_import': {'stages': {'S0': {'status': 'completed'}},
                           'dispatches': {}, 'decisions': {}}, 'coverage_contract_version': 1,
                           'plan_contract_mode': 'legacy'}, 'legacy-init')
            original = c.store.log.read_bytes()
            self.assertEqual(c.store.recover(c.project), 1)
            self.assertEqual(c.store.log.read_bytes(), original)
            state = json.loads((task / 'state/controller.json').read_text())
            self.assertEqual(state['legacy_known_paths'], old_paths)
            self.assertEqual(state['known_paths'], {})
            self.assertEqual(state['stages']['S0']['status'], 'completed')
            self.assertEqual(state['source_revision'], 'source')
            packet = c.prepare()
            self.assertEqual(Path(packet['resolved_paths']['project_root']), project)
            self.assertEqual(Path(packet['resolved_paths']['task_root']), task)
            self.assertEqual(packet['next_action']['stage'], 'S1')
            self.assertEqual(c.store.recover(c.project), 1)
            self.assertEqual(c.store.log.read_bytes(), original)
            request = {'id': 'scout', 'stage': 'S1', 'role': 'qa-scout', 'scope': ['QA-1'],
                       'input_hash': 'input', 'budget': {}, 'known_paths': old_paths,
                       'idempotency_key': 'scout', 'expected_revision': 1}
            with self.assertRaisesRegex(ValueError, 'known_paths'):
                c.apply('dispatch', request)
            self.assertEqual(c.store.log.read_bytes(), original)


class RunGateFindsTheProject(unittest.TestCase):
    """t-622 (B-309 (d)): the RUN gate's project. `Controller._project_root` is `runtime_paths.nearest_project` and answers
    None when the story sits under no `qa-factory/config.json` - it used to answer the task root, so the `{project_root}`
    of a dispatch packet became the story's own folder. A packet that depends on a project then asks the finder `prepare`
    uses, `project_for_task(story, hint=<state's recorded project_root>)`; when that finds none, ITS refusal stands."""

    ROLE = 'qa-scout'

    # The stories under `self.base / 'stories'` (QA-2, QA-3, QA-4) deliberately sit under NO project marker: they model the
    # "unknown" road of t-622 / t-617 section 8.2 (no project -> a refusal or the defaults), so they must not be built
    # through `harness.mark_project` / `temp_project`.
    def setUp(self):
        import hooklib
        self.hooklib = hooklib
        self.saved = {key: os.environ.get(key) for key in ('CLAUDE_PROJECT_DIR', 'QA_FACTORY_SKIP_DASHBOARD_REFRESH')}
        os.environ['QA_FACTORY_SKIP_DASHBOARD_REFRESH'] = '1'
        self.addCleanup(self.restore)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()

    def restore(self):
        for key, value in self.saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self.hooklib._PROJECT_ROOT_CACHE = None

    def process_project(self, folder):
        os.environ['CLAUDE_PROJECT_DIR'] = str(folder)
        self.hooklib._PROJECT_ROOT_CACHE = None

    def e4_story(self):
        """A story kept outside its project's folder (test_resolver's E4 layout): the project's artifact_root names it."""
        home = self.base / 'home'
        (home / 'qa-factory').mkdir(parents=True)
        (home / 'qa-factory' / 'config.json').write_text(json.dumps({'artifact_root': str(self.base / 'stories')}), encoding='utf-8')
        task = self.base / 'stories' / 'QA-1'
        # `prepare` keeps the story's own work files absolute (they are under the story, not under the project) and the RUN
        # gate refuses an absolute path that is not on this machine: a story past its first stages has these files
        (task / 'work').mkdir(parents=True)
        for name in ('test-plan', 'source-inventory', 'context-manifest', 'context-bundle'):
            (task / 'work' / f'{name}.json').write_text('{}', encoding='utf-8')
        return home, task

    def initialized(self, task, known):
        c = Controller(task)
        c.apply('initialize', {'scope': ['TC-1'], 'source_revision': 'src', 'known_paths': known, 'idempotency_key': 'init'})
        return c

    def packet(self, c, number=1):
        request = c.prepare({'stage': 'S0', 'role': self.ROLE, 'id': f'S0-{self.ROLE}-{number}'})['dispatch_request']
        request['idempotency_key'] = f'dispatch:{number}'
        return request

    def refusal(self, c, request):
        try:
            c.apply('dispatch', request)
        except ValueError as exc:
            return str(exc)
        return ''

    def test_an_e4_story_goes_prepare_to_dispatch_and_resolves_against_its_project(self):
        home, task = self.e4_story()
        self.process_project(home)
        c = self.initialized(task, {'root': str(task), 'project_root': str(home)})
        self.assertIsNone(c._project_root(), 'no marker at or above a story kept outside its project: None, never the task root')
        request = self.packet(c)
        self.assertEqual(request['known_paths']['project_root'], '{project_root}')
        c.apply('dispatch', request)
        kept = c.state()['dispatches'][f'S0-{self.ROLE}-1']['known_paths']
        self.assertEqual(Path(kept['project_root']), home, 'the token resolves against the project prepare wrote it from')
        self.assertNotEqual(Path(kept['project_root']), task, 'never the story itself')

    def test_the_hint_is_the_recorded_project_when_the_process_works_elsewhere(self):
        home, task = self.e4_story()
        self.process_project(self.base)                  # the process works in a folder that is no project: only the hint can say
        c = self.initialized(task, {'root': str(task), 'project_root': str(home)})
        c.apply('dispatch', {
            'id': f'S0-{self.ROLE}-1', 'stage': 'S0', 'role': self.ROLE, 'scope': ['TC-1'], 'input_hash': 'h', 'budget': {},
            'known_paths': {'root': '{task_root}', 'project_root': '{project_root}'}, 'idempotency_key': 'dispatch:1'})
        kept = c.state()['dispatches'][f'S0-{self.ROLE}-1']['known_paths']
        self.assertEqual(Path(kept['project_root']), home, "the state's recorded project_root is the hint, admitted by its artifact root")

    def test_no_project_at_all_refuses_with_the_finders_door_and_dispatches_nothing(self):
        task = self.base / 'stories' / 'QA-2'
        task.mkdir(parents=True)
        self.process_project(self.base)
        c = self.initialized(task, {'root': str(task)})
        for label, known in (('a token', {'root': '{task_root}', 'project_root': '{project_root}'}),
                             ('an absolute project_root', {'root': str(task), 'project_root': str(self.base / 'elsewhere')}),
                             ('a token in another key', {'root': str(task), 'scripts_root': '{project_root}/scripts'})):
            with self.subTest(packet=label):
                text = self.refusal(c, {'id': f'S0-{self.ROLE}-1', 'stage': 'S0', 'role': self.ROLE, 'scope': ['TC-1'],
                                        'input_hash': 'h', 'budget': {}, 'known_paths': known, 'idempotency_key': 'dispatch:x'})
                self.assertIn('--project', text, 'the finder\'s own door')
                self.assertIn(str(task), text, 'names the story')
                self.assertNotIn('has no root in this process', text, 'never the generic token text, which blames the packet')
                self.assertNotIn('--operation prepare', text, 'prepare writes {project_root} again: not a door for this refusal')
                self.assertNotIn(f'S0-{self.ROLE}-1', c.state()['dispatches'])

    def test_a_packet_that_needs_no_project_passes_as_before(self):
        task = self.base / 'stories' / 'QA-3'
        task.mkdir(parents=True)
        self.process_project(self.base)
        c = self.initialized(task, {'root': str(task)})
        c.apply('dispatch', {'id': f'S0-{self.ROLE}-1', 'stage': 'S0', 'role': self.ROLE, 'scope': ['TC-1'], 'input_hash': 'h',
                             'budget': {}, 'known_paths': {'root': str(task)}, 'idempotency_key': 'dispatch:1'})
        self.assertEqual(c.state()['dispatches'][f'S0-{self.ROLE}-1']['status'], 'running')

    def test_a_marked_story_is_unchanged(self):
        project = self.base / 'proj'
        task = project / 'qa-factory' / 'artifacts' / 'QA-1'
        task.mkdir(parents=True)
        mark_project(project)
        self.process_project(project)
        c = self.initialized(task, {'root': str(task), 'project_root': str(project)})
        self.assertEqual(c._project_root(), project)
        c.apply('dispatch', self.packet(c))
        kept = c.state()['dispatches'][f'S0-{self.ROLE}-1']['known_paths']
        self.assertEqual(Path(kept['project_root']), project)

    def test_the_config_reads_fall_to_their_defaults_with_no_project(self):
        task = self.base / 'stories' / 'QA-4'
        task.mkdir(parents=True)
        c = Controller(task)
        self.assertIsNone(c._project_root())
        from controller import DISPATCH_DEFAULTS
        for name in DISPATCH_DEFAULTS:
            self.assertEqual(c._dispatch_setting(name), DISPATCH_DEFAULTS[name], name)
        self.assertEqual(c._s5_window_cases(), c._dispatch_setting('api_window_cases') or 1)
        self.assertEqual(c._handed_cases(), {})


if __name__ == '__main__':
    unittest.main()
