"""Producer and public-summary regressions from the multi-stage field failures."""
import json
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import artifact_producer as P
import check_coverage as COV
import manual_evidence as M
import factory_dashboard as FD
import validate_artifacts as V
from ledger_fingerprint import snapshot as ledger_input_snapshot
from hooklib import parse_frontmatter
import delivery_summary as D
import runtime_paths as R


class Producers(unittest.TestCase):
    def test_case_and_bug_renderer_roundtrip_quotes_through_actual_parser(self):
        value = {'frontmatter': {'id': 'BUG-1', 'title': 'Response says "denied": exact',
                                 'covers': ['R-1', 'R-2']}, 'body': 'body'}
        rendered = P.render(value)
        parsed = parse_frontmatter(rendered)
        self.assertEqual(parsed['title'], value['frontmatter']['title'])
        self.assertEqual(parsed['covers'], '["R-1","R-2"]')
        self.assertEqual(P._roundtrip_frontmatter(value)[1], [])

    def test_batch_returns_one_stable_repair_fingerprint(self):
        batch = [{'kind': 'readiness', 'path': 'work/requirements-readiness.json',
                  'data': P.prepare('readiness')},
                 {'kind': 'triage', 'path': 'work/triage.json', 'data': {'triage': [{}]}}]
        first = P.validate_batch(batch); second = P.validate_batch(batch)
        self.assertFalse(first['valid']); self.assertEqual(first['repair_fingerprint'], second['repair_fingerprint'])
        self.assertGreaterEqual(len(first['errors']), 2)

    def test_bug_producer_requires_selected_draft_provenance(self):
        value = P.prepare('bug')
        self.assertIn('source_draft', value['frontmatter'])
        issues = P.validate('bug', value)
        self.assertTrue(any('source_draft' in issue for issue in issues))

    def test_verification_gap_stale_close_cannot_erase_current_evidence(self):
        with tempfile.TemporaryDirectory() as raw:
            opened = P.update_verification_gap(raw, {'id': 'G-1', 'reason': 'audit stream unavailable'})
            closed = P.update_verification_gap(raw, {'id': 'G-1', 'expected_revision': opened['revision'],
                'status': 'closed', 'closed_by': {'ref': 'work/receipts/audit.json', 'revision': 'sha256:abc'}})
            self.assertEqual(closed['revision'], 2)
            with self.assertRaisesRegex(ValueError, 'stale|immutable'):
                P.update_verification_gap(raw, {'id': 'G-1', 'expected_revision': 1,
                    'status': 'closed', 'closed_by': {'ref': 'other', 'revision': 'sha256:def'}})
            saved = json.loads((Path(raw) / 'work/verification-gaps.json').read_text())['gaps'][0]
            self.assertEqual(saved['closed_by']['ref'], 'work/receipts/audit.json')

    def test_coverage_map_renderer_writes_hash_bound_receipt(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw); facts = {'API': {'total': 2, 'automated': 1, 'max_updated': '2026-09-19'}}
            map_path, receipt_path, receipt = COV.write_map(root, facts, '2026-09-19')
            self.assertEqual(COV.parse_map(map_path.read_text())[1]['API']['total'], 2)
            self.assertEqual(json.loads(receipt_path.read_text())['map_sha256'], receipt['map_sha256'])

    def test_manual_case_obligation_mapping_uses_pinned_case_traceability(self):
        with tempfile.TemporaryDirectory() as raw:
            task = Path(raw); pinned = task / 'state/case-versions/TC-1/cv_1.md'
            pinned.parent.mkdir(parents=True)
            pinned.write_text('---\nid: TC-1\ntask: QA-1\n---\nRequirements: R-1\nPlan row: TS-1\n')
            links = {'links': [{'case_id': 'TC-1', 'version': 'cv_1',
                                'path': 'state/case-versions/TC-1/cv_1.md'}]}
            (task / 'state/story-case-links.json').write_text(json.dumps(links))
            rows = [{'id': 'TS-1', 'coverage_obligations': [
                {'obligation_id': 'O-1', 'requirement_refs': [{'ref': 'R-1'}]},
                {'obligation_id': 'O-2', 'requirement_refs': [{'ref': 'R-2'}]}]}]
            self.assertEqual(M._case_obligation_mapping(task, rows, 'TC-1'), {'O-1'})

    def test_manual_prepare_binds_current_gate_policy_and_rejects_case_mismatch(self):
        obligation = {'obligation_id': 'O-1', 'behavior': 'saved', 'decision': 'manual-agent',
                      'execution_scope': 'current_task', 'oracle_status': 'resolved',
                      'evidence_policy': 'ui', 'completion_condition': 'save completed'}
        rows = [{'id': 'TS-1', 'coverage_obligations': [obligation]}]
        state = {'revision': 7, 'source_revision': 'src-1', 'decisions': {
            'A-1': {'id': 'A-1', 'gate': 'A', 'status': 'approved'}}}
        controller = unittest.mock.Mock(); controller.state.return_value = state
        controller._current_gate_a.return_value = state['decisions']['A-1']  # C5: prepare asks the controller for the current one
        with tempfile.TemporaryDirectory() as raw, \
             patch('controller.Controller', return_value=controller), \
             patch('coverage_contract.plan_rows', return_value=rows), \
             patch('planning_contract.validate_plan', return_value=[]), \
             patch('contract.story_case_links', return_value=[{'case_id': 'TC-1', 'version': 'cv_1'}]), \
             patch.object(M, '_case_obligation_mapping', return_value={'O-1'}):
            request = M.prepare_request(raw, 'TC-1', ['O-1'])
            self.assertEqual(request['gate_a_decision_ref'], 'A-1')
            self.assertTrue(request['approved_policy_hash'])
        with tempfile.TemporaryDirectory() as raw, \
             patch('controller.Controller', return_value=controller), \
             patch('coverage_contract.plan_rows', return_value=rows), \
             patch('planning_contract.validate_plan', return_value=[]), \
             patch('contract.story_case_links', return_value=[{'case_id': 'TC-1', 'version': 'cv_1'}]), \
             patch.object(M, '_case_obligation_mapping', return_value=set()):
            with self.assertRaisesRegex(ValueError, 'traceability'):
                M.prepare_request(raw, 'TC-1', ['O-1'])

    def test_invalid_readiness_returns_all_errors_without_publishing(self):
        with tempfile.TemporaryDirectory() as raw:
            result = P.publish(raw, 'readiness', P.prepare('readiness'),
                               'work/requirements-readiness.json')
            self.assertFalse(result['valid'])
            self.assertGreaterEqual(len(result['errors']), 3)
            self.assertFalse((Path(raw) / 'work/requirements-readiness.json').exists())

    @staticmethod
    def readiness_data(verdict='blocked', q4_severity='minor', aspect=None):
        """F-12586-sev: Q1 major, Q2 minor, Q3 blocker, Q4 `q4_severity`, Q5 blocker; two readings each."""
        def row(qid, severity):
            return {'id': qid, 'question': f'question {qid}?', 'severity': severity, 'owner_role': 'qa',
                    'readings': [{'reading': 'x'}, {'reading': 'y'}]}
        return {'verdict': verdict, 'goal_summary': 'Check the filter of the webhook payload end to end, by its paths',
                'aspects': {'functional': {'status': aspect or 'ready'}},
                'register': {'total': 3, 'by_source': {'story': 2, 'ac': 1}},
                'open_questions': [row('Q1', 'major'), row('Q2', 'minor'), row('Q3', 'blocker'), row('Q4', q4_severity), row('Q5', 'blocker')]}

    NOT_CHECKED = ('the verdict was not checked against the recorded answers (no --task-root): blocker questions Q3, Q5 '
                   'may be answered already; publish checks it')

    def story_with_answers(self, raw, verdict='blocked'):
        """A story root whose register is F-12586-sev and whose answers file holds the words of the fixture (Q3 until the report, the rest answered)."""
        import question_register as QR
        root = Path(raw); (root / 'work').mkdir(exist_ok=True)
        target = root / 'work' / 'requirements-readiness.json'
        target.write_text(json.dumps(self.readiness_data(verdict)), encoding='utf-8')
        QR.record_answers(root, 'Q1: b\nQ2: a\nQ3: until the report\nQ4: a\nQ5: a\n', 'S2 stop', 'person')
        return root, target

    def test_validate_without_a_story_root_says_what_it_did_not_check_and_never_fails_for_it(self):
        notes = []
        errors = P.validate('readiness', self.readiness_data(), None, notes)
        self.assertEqual((errors, notes), ([], [self.NOT_CHECKED]), 'blocked + blocker rows: valid, and said as not_checked')
        self.assertEqual(P.validate('readiness', self.readiness_data()), [], 'the old two-argument call still works')
        notes = []
        errors = P.validate('readiness', self.readiness_data('ready', aspect='blocked'), None, notes)
        self.assertTrue(any('contradiction' in e for e in errors) and notes == [], 'ready over a blocked aspect needs no answers file: an error')
        data = self.readiness_data()
        for row in data['open_questions']:
            row['severity'] = 'minor' if row['severity'] == 'blocker' else row['severity']
        notes = []
        errors = P.validate('readiness', data, None, notes)
        self.assertTrue(any('no open blocker question and no blocked aspect' in e for e in errors) and notes == [],
                        'blocked with no blocking row at all needs no answers file: an error')
        notes = []
        P.validate('triage', {'triage': []}, None, notes)
        self.assertEqual(notes, [], 'another artifact kind never fills not_checked')

    def test_validate_with_a_story_root_checks_the_verdict_against_the_answers(self):
        with tempfile.TemporaryDirectory() as raw:
            root, _ = self.story_with_answers(raw)
            notes = []
            errors = P.validate('readiness', self.readiness_data('blocked'), root, notes)
            self.assertEqual(notes, [], 'with a root nothing is left unchecked')
            self.assertTrue(len(errors) == 1 and 'no open blocker question and no blocked aspect' in errors[0], str(errors))
            self.assertEqual(P.validate('readiness', self.readiness_data('ready'), root, []), [], 'ready: every blocker is settled or kept open')

    def test_batch_carries_not_checked_per_artifact_and_publish_never_does(self):
        item = {'kind': 'readiness', 'path': 'work/requirements-readiness.json', 'data': self.readiness_data()}
        result = P.validate_batch([item])
        self.assertEqual((result['valid'], result['errors'], result['not_checked']),
                         (True, [], [{'artifact': 'work/requirements-readiness.json', 'detail': self.NOT_CHECKED}]))
        with tempfile.TemporaryDirectory() as raw:
            root, target = self.story_with_answers(raw)
            self.assertNotIn('not_checked', P.validate_batch([item], root), 'with a root the field is absent')
            import hashlib
            before = hashlib.sha256(target.read_bytes()).hexdigest()
            refused = P.publish(root, 'readiness', self.readiness_data('blocked'), 'work/requirements-readiness.json', before)
            self.assertFalse(refused['valid'])
            self.assertNotIn('not_checked', refused)
            self.assertIn('Expected: verdict', refused['errors'][0]['detail'])
            done = P.publish(root, 'readiness', self.readiness_data('ready'), 'work/requirements-readiness.json', before)
            self.assertTrue(done['valid'] and 'not_checked' not in done, str(done))
        self.assertNotIn('not_checked', P.validate_batch([{'kind': 'triage', 'path': 'work/triage.json', 'data': {'triage': []}}]))

    def test_validate_cli_without_task_root_exits_zero_and_prints_not_checked(self):
        import subprocess
        with tempfile.TemporaryDirectory() as raw:
            source = Path(raw) / 'readiness.json'
            source.write_text(json.dumps(self.readiness_data()), encoding='utf-8')
            run = subprocess.run([sys.executable, '-B', str(Path(P.__file__).resolve()), 'validate', '--kind', 'readiness', '--input', str(source)],
                                 capture_output=True, text=True, encoding='utf-8', cwd=raw)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            printed = json.loads(run.stdout.strip().splitlines()[-1])
            self.assertEqual((printed['valid'], printed['errors'], printed['not_checked']), (True, [], [self.NOT_CHECKED]))

    def test_triage_enum_is_not_a_subtype_and_requires_identity(self):
        issues = P.validate('triage', {'triage': [{'verdict': 'TEST_BUG:collection', 'evidence': 'report'}]})
        self.assertTrue(any('verdict' in x for x in issues))
        self.assertTrue(any('instance_id' in x for x in issues))

    def test_missing_execution_cannot_be_reported_as_verified(self):
        with tempfile.TemporaryDirectory() as raw:
            value = D.build(raw, {'rows': [
                {'ref': 'TS-1', 'kind': 'plan_row', 'state': 'passed_green'},
                {'ref': 'TS-2', 'kind': 'plan_row', 'state': 'not_executed:missing'},
                {'ref': 'TS-3', 'kind': 'plan_row', 'state': 'failed:APP_BUG'}]})
            self.assertEqual(value['counts']['verified'], 1)
            self.assertEqual(value['counts']['failed'], 1)
            self.assertEqual(value['gaps'][0]['ref'], 'TS-2')
            self.assertIn('TS-2', D.render(value))

    def test_missing_before_capture_is_a_separate_unverified_comparison(self):
        with tempfile.TemporaryDirectory() as raw:
            task = Path(raw); (task / 'work').mkdir(); (task / 'state').mkdir()
            (task / 'state/controller.json').write_text(json.dumps({'source_revision': 'new', 'decisions': {
                'A-1': {'id': 'A-1', 'gate': 'A', 'status': 'approved', 'source_revision': 'new'}}}))
            (task / 'work/test-plan.json').write_text(json.dumps({'rows': [{
                'id': 'TS-1', 'case_id': 'TC-1', 'case_version': 'v1', 'baseline_required': True,
                'execution_scope': 'current_task', 'baseline_revision': 'old', 'verification_revision': 'new',
                'fixture_identity': 'seed-1', 'comparison_assertions': ['compare graph']}]}))
            summary = D.build(task, {'rows': [{'ref': 'TS-1', 'kind': 'plan_row', 'state': 'passed_green'}]})
            self.assertEqual(summary['counts']['verified'], 1)
            self.assertEqual(summary['counts']['env_blocked'], 0)
            self.assertFalse(summary['comparisons_ready'])
            self.assertEqual(summary['comparison_gaps'][0]['status'], 'awaiting_baseline')
            text = D.render(summary)
            self.assertIn('Before/after comparisons awaiting a before-state capture:\n- TC-1: ' + summary['comparison_gaps'][0]['reason'], text)
            self.assertNotIn('awaiting_before', text)
            html = FD.delivery_summary_html([{'task': 'QA-1', 'delivery_summary': summary}])
            self.assertIn('Before/after comparisons', html)
            self.assertIn('including in production?', html)

    def test_remote_receipt_requires_id_and_url(self):
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / 'work/proposals/a.json'
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps({'kind': 'bug', 'bug_file': 'bugs/BUG-1.md',
                                       'result': {'external_id': 'B-1'}}))
            self.assertEqual(D.build(raw, {})['bugs'][0]['state'], 'provenance_invalid')

    def test_delivery_summary_counts_current_attempts_and_links_selected_drafts(self):
        with tempfile.TemporaryDirectory() as raw:
            task = Path(raw); (task / 'work/proposals').mkdir(parents=True)
            (task / 'work/bug-drafts').mkdir(); (task / 'state').mkdir()
            (task / 'state/controller.json').write_text(json.dumps({'revision': 4, 'decisions': {
                'B-1': {'id': 'B-1', 'gate': 'B', 'status': 'approved',
                        'selected_drafts': ['work/bug-drafts/d1.json']}}}))
            (task / 'work/bug-drafts/d1.json').write_text('{}')
            (task / 'work/bug-drafts/d2.json').write_text('{}')
            (task / 'work/proposals/p1.json').write_text(json.dumps({'kind': 'bug',
                'bug_file': 'bugs/BUG-1.md', 'source_draft': 'work/bug-drafts/d1.json',
                'gate_b_decision_id': 'B-1', 'result': {'external_id': 'B-1', 'url': 'https://bugs/1'}}))
            (task / 'work/proposals/p2.json').write_text(json.dumps({'kind': 'bug',
                'bug_file': 'bugs/BUG-2.md', 'source_draft': 'work/bug-drafts/d2.json',
                'gate_b_decision_id': 'B-1', 'result': {'external_id': 'B-2', 'url': 'https://bugs/2'}}))
            (task / 'work/test-plan.json').write_text(json.dumps({'rows': [{'id': 'TS-1',
                'coverage_obligations': [{'decision': 'manual-agent'}]}, {'id': 'TS-2'}]}))
            (task / 'work/run-report.json').write_text(json.dumps({'current_results': [
                {'instance_id': 'i1', 'status': 'passed'}, {'instance_id': 'old', 'status': 'passed', 'stale': True}],
                'current_manual_checks': [
                    {'case': 'TC-1', 'attempt_id': 'a1', 'result': 'pass', 'evidence_validated': True},
                    {'case': 'TC-1', 'attempt_id': 'a1', 'result': 'pass', 'evidence_validated': True},
                    {'case': 'TC-2', 'attempt_id': 'a2', 'result': 'pass', 'evidence_validated': True, 'stale': True}]}))
            (task / 'work/verification-gaps.json').write_text(json.dumps({'gaps': [
                {'id': 'G-open', 'revision': 1, 'status': 'open', 'reason': 'oracle missing'},
                {'id': 'G-closed', 'revision': 2, 'status': 'closed', 'reason': 'was missing',
                 'closed_by': {'ref': 'receipt', 'revision': 'sha256:a'}}]}))
            ledger = {'rows': [{'ref': 'TS-1', 'kind': 'plan_row', 'state': 'passed_green'},
                               {'ref': 'TS-2', 'kind': 'plan_row', 'state': 'not_executed:missing'}]}
            summary = D.build(task, ledger)
            self.assertEqual(summary['counts']['executed'], 2)
            self.assertIsNone(summary['counts']['planned_manual'])
            self.assertEqual(summary['counts']['executed_manual'], 1)
            self.assertEqual({b['ref']: b['state'] for b in summary['bugs']}['bugs/BUG-1.md'], 'published')
            self.assertEqual({b['ref']: b['state'] for b in summary['bugs']}['bugs/BUG-2.md'], 'provenance_invalid')
            self.assertEqual([g['id'] for g in summary['current_design_gaps']], ['G-open'])
            html = FD.delivery_summary_html([{'task': 'QA-1', 'delivery_summary': summary}])
            self.assertIn('<th>Executed instances</th>', html); self.assertIn('<td>unknown</td>', html)

    def test_report_uses_exact_projection_and_machine_fragment_is_outside_prose_budget(self):
        with tempfile.TemporaryDirectory() as raw:
            task = Path(raw); (task / 'state').mkdir(); (task / 'work').mkdir()
            (task / 'state/controller.json').write_text('{"plan_contract_mode":"new","decisions":{}}')
            ledger = {'rows': [{'ref': 'TS-1', 'kind': 'plan_row', 'state': 'passed_green'}]}
            (task / 'work/ledger.json').write_text(json.dumps(ledger))
            (task / 'work/run-report.json').write_text('{"current_results":[]}')
            fragment = D.render(D.build(task, ledger))
            # The fragment lives in work/ since the report was rewritten for the person
            # (TP1-15045: the machine summary sat in the body, twice); the report itself
            # carries none of it.
            # t-305 N8: the fragment now carries the report's own "Left with you" section or one line with an em dash, so it
            # is written the way `delivery_summary.write` writes it (UTF-8), not with the machine's default encoding
            summary = task / 'work/delivery-summary.md'; summary.write_text(fragment, encoding='utf-8')
            report = task / 'test-report.md'; report.write_text('# T-1 — test report\n\n`delivery_ready: yes`\n')
            with patch.object(V, 'check_report_coverage'), patch.object(V, 'check_report_ledger_and_readiness'), \
                 patch.object(V, 'check_report_sections'):
                errors = []; V.check_test_report(report, errors); self.assertEqual(errors, [])
                summary.write_text(fragment.replace('Recorded verification', 'Retyped verification'), encoding='utf-8')
                errors = []; V.check_test_report(report, errors)
                self.assertTrue(any('STALE_REPORT_SUMMARY' in error for error in errors))
            huge_machine = ('<!-- factory-summary:start -->\n' + 'machine\n' * 4000 +
                            '<!-- factory-summary:end -->\n')
            report.write_text(huge_machine)
            errors = []; V.check_report_ledger_and_readiness(report, errors)
            self.assertFalse(any('bytes outside' in error for error in errors))

    def test_present_ledger_fingerprint_exposes_staleness_without_erasing_failures(self):
        with tempfile.TemporaryDirectory() as raw:
            task = Path(raw); (task / 'work').mkdir(); (task / 'state').mkdir()
            for name in ('test-plan.json', 'run-report.json', 'automation-manifest.json', 'triage.json'):
                (task / 'work' / name).write_text('{}')
            ledger = {'rows': [{'ref': 'TS-1', 'kind': 'plan_row', 'state': 'failed:APP_BUG'},
                               {'ref': 'TS-2', 'kind': 'plan_row', 'state': 'passed_green'}],
                      'delivery_ready': True,
                      'source_inputs': ledger_input_snapshot(task)}
            current = D.build(task, ledger)
            self.assertEqual(current['ledger_freshness'], 'current')
            (task / 'work/run-report.json').write_text('{"changed":true}')
            stale = D.build(task, ledger)
            self.assertEqual(stale['ledger_freshness'], 'stale')
            self.assertEqual(stale['counts']['failed'], 1)
            self.assertEqual(stale['counts']['verified'], 0)
            self.assertEqual(stale['counts']['unverified'], 1)
            self.assertFalse(stale['delivery_ready'])
            legacy = D.build(task, {'rows': ledger['rows']})
            self.assertEqual(legacy['ledger_freshness'], 'unknown')
            self.assertTrue(any('legacy ledger' in gap for gap in legacy['source_gaps']))

    def test_skipped_and_setup_error_do_not_inflate_executed_instances(self):
        with tempfile.TemporaryDirectory() as raw:
            task = Path(raw); (task / 'work').mkdir(); (task / 'state').mkdir()
            (task / 'work/run-report.json').write_text(json.dumps({'current_results': [
                {'instance_id': 'pass', 'status': 'passed'}, {'instance_id': 'skip', 'status': 'skipped'},
                {'instance_id': 'setup', 'status': 'error'}]}))
            summary = D.build(task, {'rows': [{'ref': 'TS-1', 'kind': 'plan_row', 'state': 'passed_green'}]})
            self.assertEqual(summary['counts']['executed'], 1)

    def test_paths_resolve_from_installation_not_product_cwd(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw); (root / 'qa-factory').mkdir()
            (root / 'qa-factory/config.json').write_text('{"code_repos": [{"name":"app", "path":"app"}]}')
            value = R.resolve_runtime(root / 'qa-factory/artifacts/T')
            self.assertTrue(Path(value['entrypoints']['run_suite']).is_file())
            self.assertEqual(value['repository_roots']['app'], str((root / 'app').resolve()))
            self.assertNotEqual(value['plugin_root'], str(root))

    def test_the_handoff_slot_reads_the_verdict_word_not_the_truthiness_of_a_field(self):
        """K-N8.24 (t-305 N8): `delivery.ready` is the ledger's WORD - `after_checks` is not `no`, and the string "no" is not ready."""
        import handoff_check as HC
        cases = ((' {"delivery_verdict":"yes","delivery_ready":true}', 'yes'),
                 ('{"delivery_verdict":"after_checks","delivery_ready":false}', 'after_checks'),
                 ('{"delivery_verdict":"no","delivery_ready":false}', 'no'),
                 ('{"delivery_ready":true}', 'yes'), ('{"delivery_ready":false}', 'no'),
                 ('{"delivery_ready":"no"}', 'unknown'), ('{"delivery_verdict":"yes","delivery_ready":false}', 'unknown'))
        for text, word in cases:
            with tempfile.TemporaryDirectory() as raw:
                task = Path(raw); (task / 'work').mkdir()
                (task / 'work/ledger.json').write_text(text, encoding='utf-8')
                value = HC._delivery_ready(HC.Artifacts(task), {})
                self.assertEqual(value[0] if value else None, word, text)
        with tempfile.TemporaryDirectory() as raw:
            self.assertIsNone(HC._delivery_ready(HC.Artifacts(Path(raw)), {}),
                              'a story with no ledger says nothing')
            (Path(raw) / 'work').mkdir()
            (Path(raw) / 'work/ledger.json').write_text('{"rows": []}', encoding='utf-8')
            self.assertIsNone(HC._delivery_ready(HC.Artifacts(Path(raw)), {}),
                              'a ledger holding neither the word nor the bool says nothing')


    def test_n2_bad_status_and_bad_severity_are_two_problems_with_their_lists(self):
        value = P.prepare('bug')
        value['frontmatter'].update(status='Wontfix', severity='huge')
        issues = P.validate('bug', value)
        self.assertIn('frontmatter.status must be one of ' + P.one_of(V.BUG_STATUS), issues)
        self.assertIn('frontmatter.severity must be one of ' + P.one_of(V.BUG_SEVERITY), issues)
        self.assertIn('frontmatter.status must be one of Blocked, Closed, Fixed', ' '.join(issues))
        self.assertFalse(any('invalid bug status/severity' in issue for issue in issues))
        only_severity = P.prepare('bug')
        only_severity['frontmatter'].update(status='Open', severity='huge')       # E-N2-12: each field judged alone
        issues = P.validate('bug', only_severity)
        self.assertTrue(any(issue.startswith('frontmatter.severity must be one of') for issue in issues))
        self.assertFalse(any(issue.startswith('frontmatter.status must be one of') for issue in issues))
        case = P.prepare('case')
        case['frontmatter'].update(status='Done', channel='fax')
        issues = P.validate('case', case)
        self.assertIn('frontmatter.status must be one of ' + P.one_of(V.CASE_STATUS), issues)
        self.assertIn('frontmatter.channel must be one of ' + P.one_of(V.CASE_CHANNEL), issues)

    def test_n2_a_triage_row_missing_attempt_id_names_attempt_id(self):
        self.assertEqual(P.TRIAGE_ROW_IDS, ('instance_id', 'attempt_id'))
        issues = P.validate('triage', {'triage': [{'attempt_id': 'a-1'}, {'instance_id': 'i-1'}, {}]})
        self.assertIn('triage[0]: instance_id and attempt_id required (missing: instance_id)', issues)
        self.assertIn('triage[1]: instance_id and attempt_id required (missing: attempt_id)', issues)
        self.assertIn('triage[2]: instance_id and attempt_id required (missing: instance_id, attempt_id)', issues)

    def test_n2_every_multi_problem_refusal_is_validator_friction(self):
        import friction
        from detector_verdict import compound
        value = P.prepare('bug')
        value['frontmatter'].update(status='Wontfix', severity='huge')
        text = compound(P.validate('bug', value))
        self.assertEqual(friction.classify('artifact_producer.py: ' + text), 'validator')


if __name__ == '__main__':
    unittest.main()
