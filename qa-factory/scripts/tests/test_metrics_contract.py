"""Numeric, missing-data and rendered contract checks for project metrics."""
import contextlib
import hashlib
import io
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import metrics_projection
from metrics_projection import compute, render, project, CATALOGUE
from dashboard_refresh import refresh_project
from content_size import content_bytes
from dashboard_fixture import build

# project() takes no clock: it reads datetime.now() once and windows every request to the 30 days
# before it, and the session fixture of test_has_factory_activity_false_excluded_from_every_metric is
# stamped 2026-09-17, so the wall clock turned it red from 2026-10-17 (B-396). FixedClock answers now()
# with the SAME instant values() pins for compute() (2026-09-18, the day after the stamp: one clock for
# the file, no second date to keep in step) and leaves fromisoformat/fromtimestamp/min to datetime.
PINNED_NOW = datetime(2026, 9, 18, tzinfo=timezone.utc)


class FixedClock(datetime):
    @classmethod
    def now(cls, tz=None):
        return PINNED_NOW if tz is None else PINNED_NOW.astimezone(tz)


def _listing(root):
    """Every path under `root`: kind, size, mtime (ns) and sha256 of a file's bytes. A directory's
    mtime moves when an entry is created or removed in it, so a temp file written and replaced
    shows up there even though the final tree looks the same."""
    rows = {}
    for path in sorted(Path(root).rglob('*')):
        stat = path.stat()
        rel = path.relative_to(root).as_posix()
        if path.is_file():
            rows[rel] = ('file', stat.st_size, stat.st_mtime_ns, hashlib.sha256(path.read_bytes()).hexdigest())
        else:
            rows[rel] = ('dir', stat.st_mtime_ns)
    return rows


def _make_old(root, when=1_500_000_000):
    """Stamp every path with a time long ago, files first and the directories deepest first, so a
    write during a render cannot hide inside the clock's granularity."""
    paths = sorted(Path(root).rglob('*'), key=lambda p: (p.is_dir(), -len(p.parts)))
    for path in paths:
        os.utime(path, (when, when))


def _render(root, out, *flags):
    from factory_dashboard import main
    with contextlib.redirect_stdout(io.StringIO()):
        main(['--root', str(root), *flags, '--out', str(out)])


class MetricsContractTests(unittest.TestCase):
    def test_current_results_drive_legacy_visual_widgets(self):
        from factory_dashboard import tab_automation
        task={'task':'T','report':{'current_results':[
            {'instance_id':'a','test_id':'a','status':'pass','level':'api'},
            {'instance_id':'b','test_id':'b','status':'blocked','level':'e2e-ui'}],
            'totals':{'passed':999}},'hardening':{'verdict':'green'},'manifest_tests':{'a'},
            'triage':[],'planned_cases':{},'structured_plan':{},'case_levels':{},'unresolved':{}}
        text=tab_automation({'Runs':[]},[task],[],{},testing_html='')
        self.assertIn('1 green',text)
        self.assertIn('1 yellow',text)
        self.assertNotIn('999 green',text)
        self.assertNotIn('Phase 8',text)
        self.assertNotIn('hardening x3',text)

    def values(self, data):
        return {r['id']:r for r in compute(data,datetime(2026,9,18,tzinfo=timezone.utc))}

    def test_catalogue_complete_and_unique(self):
        self.assertEqual(len(CATALOGUE),48)
        self.assertEqual(len({r['id'] for r in CATALOGUE}),48)
        refs=Path(__file__).resolve().parents[2]/'references/metrics'
        for prefix,name in [('T','testing'),('A','automation'),('F','factory'),('C','cost')]:
            text=(refs/(name+'.md')).read_text(encoding='utf-8')
            for row in CATALOGUE:
                if row['id'].startswith(prefix):self.assertIn(row['formula'],text)

    def test_money_metrics_carry_formula_version_2_and_nothing_else_moves(self):
        """t-196: the price now comes from the story's own rate base (P18, 30.09), so every metric that
        reads a usd figure starts at version 2 and its 1.5x-override history is an incompatible baseline.
        The set is enumerated on purpose: a metric added later is version 1 until its own entry says otherwise."""
        moved={'C02','C06','C08','C09','C10','C11','C15','F08'}
        versions={r['id']:r['formula_version'] for r in compute({},datetime(2026,9,18,tzinfo=timezone.utc))}
        self.assertEqual({k for k,v in versions.items() if v!=1},moved)
        self.assertEqual({versions[k] for k in moved},{2})
        self.assertEqual(len(versions),48)
        self.assertTrue(moved<={r['id'] for r in CATALOGUE},'an id of the table that the catalogue does not hold')
        self.assertEqual({r['id']:metrics_projection.formula_version_of(r['id']) for r in CATALOGUE},versions,
                         'the built version is the table\'s, never patched afterwards')
        self.assertEqual(metrics_projection.formula_version_of('Z99'),1,'a metric added later is not bumped by accident')
        self.assertEqual(versions['C03'],1,'C03 reads usd totals but is a verdict that three sums agree')
        self.assertIn('formula v2',render({'as_of':'now','metrics':compute({})},'C'))
        text=(Path(__file__).resolve().parents[2]/'references/metrics-contract.md').read_text(encoding='utf-8')
        for mid in sorted(moved):
            self.assertIn(mid,text.split('Window metrics use')[0].split('Version 2')[1],mid+' is not named in the contract text')

    def test_coverage_denominators_include_gaps_not_regression(self):
        obs=[dict(scope='current_task',approved=True,priority='P1' if i<4 else 'P2',
                  verified=i in {0,1,2,4,5,6}) for i in range(10)]
        obs.extend([dict(scope='recommended_regression')]*2)
        m=self.values(dict(plan_known=True,obligations=obs))
        self.assertEqual(m['T01']['value'],60)
        self.assertEqual(m['T02']['value'],75)
        self.assertEqual(m['T06']['value']['recommended_regression_not_run'],2)

    def test_estimate_numeric_oracles(self):
        rows=[dict(forecast={'size_final':'M'},complete_cost=n,completed=True) for n in [38,60]]
        m=self.values(dict(estimates=rows))
        self.assertEqual(m['C08']['value'],50)
        self.assertEqual(m['C09']['value']['M']['median'],49)
        self.assertAlmostEqual(m['C10']['value'],100*((-9/47+13/47)/2))
        self.assertAlmostEqual(m['C11']['value']['MMRE'],(9/38+13/60)/2)
        self.assertEqual(m['C11']['value']['PRED25'],100)

    def test_driver_ties_are_stable_and_include_shares(self):
        m=self.values({'estimates':[{'drivers':['z','a'],'completed':True},{'drivers':['a','z'],'completed':True},
                                    {'drivers':['b'],'completed':True},
                                    {'drivers':['should-not-count'],'forecast':{'size_initial':'S','size_final':'M'}}]})
        self.assertEqual(list(m['C13']['value']),['a','z','b'])
        self.assertEqual(m['C13']['value']['a'],{'count':2,'share_percent':200/3})
        self.assertEqual(m['C13']['sample_size'],3)
        self.assertEqual(m['C12']['sample_size'],0)
        self.assertEqual(m['C08']['excluded']['not_completed'],1)

    def test_missing_history_and_rates_do_not_become_zero_or_mismatch(self):
        m=self.values(dict(bugs_known=True,bugs=[{'id':'B','status':'Fixed','severity':'major'}],
               sessions=[{'by_model':{},'total_cost_usd':None,'priced_subtotal_usd':2,
                          'reconciliation':{'match':None}}]))
        self.assertEqual(m['T13']['status'],'unavailable')
        self.assertEqual(m['C02']['status'],'partial')
        self.assertEqual(m['C02']['value'],2)
        self.assertEqual(m['C03']['value'],'unknown')

    def test_usage_window_and_partial_pricing_use_request_facts(self):
        base={'usage_completeness':'complete','pricing_coverage':'partial','requests':[
            {'request_key':'p:s:old:main','timestamp':'2026-08-01T00:00:00Z','stream':'orchestrator',
             'model_id':'m','activity_id':'story','usage':{'input':9000000},
             'activity_segment_id':'old-segment',
             'valuation':{'subtotal_usd':'90','pricing_coverage':'complete'}},
            {'request_key':'p:s:r1:main','timestamp':'2026-09-17T00:00:00Z','stream':'orchestrator',
             'model_id':'m','activity_id':'story','usage':{'input':1000000},
             'activity_segment_id':'story-segment',
             'valuation':{'subtotal_usd':'2','pricing_coverage':'complete'}},
            {'request_key':'p:s:r2:agent','timestamp':'2026-09-17T00:01:00Z','stream':'agent-1',
             'model_id':'m','activity_id':'doctor','usage':{'output':500000},
             'activity_segment_id':'doctor-segment',
             'valuation':{'subtotal_usd':'0','pricing_coverage':'partial','missing_rate_categories':['output']}}]}
        m=self.values({'window_days':30,'sessions':[base]})
        self.assertEqual(m['C01']['value'],1500000)
        self.assertEqual(m['C02']['value'],2)
        self.assertEqual(m['C02']['status'],'partial')
        self.assertEqual(m['C03']['value'],'unknown')
        self.assertEqual(m['C05']['value'],0) # distinct explicit activities are never bridged
        self.assertAlmostEqual(m['F08']['value']['token_percent'],1000000/1500000*100)
        self.assertEqual(m['C06']['value']['requests'],2)

    def test_request_decimal_subtotals_remain_exact_before_projection(self):
        rows=[{'request_key':f'p:s:{i}:main','timestamp':'2026-09-17T00:00:00Z',
               'stream':'orchestrator','model_id':'m','activity_id':'story','activity_segment_id':'seg',
               'usage':{'input':1},
               'valuation':{'subtotal_usd':'0.0000001','pricing_coverage':'complete'}} for i in range(10)]
        m=self.values({'sessions':[{'usage_completeness':'complete','requests':rows}]})
        self.assertEqual(m['C02']['value'],0.000001)
        self.assertEqual(m['C02']['status'],'available')
        self.assertEqual(m['C03']['value'],'matched')

    def test_project_uses_latest_estimate_and_complete_pinned_task_requests(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); qf=root/'qa-factory'; (qf/'state').mkdir(parents=True)
            task_path=qf/'artifacts/T'; task_path.mkdir(parents=True)
            (task_path/'pipeline.json').write_text(json.dumps({'stages':{'S9':{'status':'done'}}}))
            tasks=[{'task':'T','artifact_path':str(task_path),'coverage':{},'manifest_entries':[]}]
            sessions=[{'usage_completeness':'complete','by_task':{'T':{'cost':999}},'requests':[
                {'task':'T','timestamp':'2026-09-17T00:00:00Z','valuation':{
                 'pricing_coverage':'complete','subtotal_usd':'6'}},
                {'task':'T','timestamp':'2026-08-01T00:00:00Z','valuation':{
                 'pricing_coverage':'complete','subtotal_usd':'90'}}]}]
            estimates=[{'task':'T','ts':'2026-09-16T00:00:00Z','forecast':{'size_final':'S'}},
                       {'task':'T','ts':'2026-09-17T00:00:00Z','forecast':{'size_final':'M'}}]
            (qf/'state/benefit-inputs.json').write_text(json.dumps({
                'approved_by':'owner','approved_at':'2026-09-17','evidence_refs':['approval'],
                'period_start':'2026-09-01T00:00:00Z','period_end':'2026-09-18T00:00:00Z',
                'scope':{'tasks':['T']},'case_baselines':[],
                'counterfactual_usd':100,'actual_human_usd':20,'actual_infra_usd':10}))
            result=project(root,tasks,[],sessions,[],estimates,{},registry=[])
            metrics={m['id']:m for m in result['metrics']}
            self.assertEqual(metrics['C09']['value']['M']['median'],96)
            self.assertNotIn('S',metrics['C09']['value'])
            self.assertAlmostEqual(metrics['C15']['value'],100*(100-36)/36)

    def test_has_factory_activity_false_excluded_from_every_metric(self):
        """a session whose cwd merely sat inside the project (no factory activity) must
        not count toward any story/factory metric; a 0.7.4 file with no such field still
        counts, same as today (backward compatibility)."""
        def session(sid, tokens, has_factory_activity=None):
            row = {'request_key': sid + ':r', 'timestamp': '2026-09-17T00:00:00Z', 'stream': 'orchestrator',
                   'model_id': 'm', 'activity_id': 'a', 'activity_segment_id': 'a-seg',
                   'usage': {'input': tokens}, 'valuation': {'subtotal_usd': '1', 'pricing_coverage': 'complete'}}
            s = {'usage_completeness': 'complete', 'session_id': sid, 'requests': [row]}
            if has_factory_activity is not None:
                s['has_factory_activity'] = has_factory_activity
            return s
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); (root / 'qa-factory/state').mkdir(parents=True)
            sessions = [session('factory-1', 100000, True), session('nonfactory-1', 900000, False),
                        session('legacy-1', 50000)]  # no field at all -> counts, like 0.7.4
            with mock.patch.object(metrics_projection, 'datetime', FixedClock):
                result = project(root, [], [], sessions, [], [], {}, registry=[])
            metrics = {m['id']: m for m in result['metrics']}
            self.assertEqual(metrics['C01']['value'], 150000)

    def test_benefit_excludes_unapproved_baseline(self):
        inputs=dict(approved_by='owner',approved_at='2026-09-18',evidence_refs=['approval'],
                    case_baselines=[dict(case_id='C',manual_minutes=12,evidence_ref='timing')],
                    automation_authoring_hours=.2,maintenance_hours=.1,
                    counterfactual_usd=100,actual_human_usd=20,actual_infra_usd=10)
        data=dict(benefit_inputs=inputs,benefit_executions=['C','C'],benefit_scope_matches=True,
                  comparable_actual_model_usd=50)
        m=self.values(data)
        self.assertAlmostEqual(m['C14']['value']['net_hours'],.1)
        self.assertEqual(m['C15']['value'],25)
        inputs.pop('approved_by')
        self.assertEqual(self.values(data)['C15']['status'],'unavailable')

    def test_formula_expansion_uses_catalogue(self):
        text=render({'as_of':'now','metrics':compute({})},'TAFC')
        self.assertEqual(text.count('<summary>Formulas</summary>'),48)
        self.assertNotIn('check A10',text)
        self.assertIn('Testing quality',text)

    def test_refresh_canonical_registry_and_missing_html(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);qf=root/'qa-factory';qf.mkdir()
            (qf/'config.json').write_text('{}')
            first=refresh_project(root)
            self.assertEqual(refresh_project(root)['input_hash'],first['input_hash'])
            (qf/'factory-backlog.md').write_text('# Findings about the factory\n')
            self.assertNotEqual(refresh_project(root)['input_hash'],first['input_hash'])
            output=qf/'state/factory-dashboard.html'
            output.unlink();refresh_project(root)
            self.assertTrue(output.exists())
            text=output.read_text(encoding='utf-8')
            self.assertNotIn('Cadence schedule',text)
            self.assertNotIn('arming the cadences',text)
            self.assertNotIn('/qa-maintenance',text)

    def test_project_without_write_returns_the_same_value_and_opens_nothing_for_writing(self):
        """R15 (B-197): `write=False` is the read-only form of project(). Same value (the clock
        fields apart), no state/metrics.json, no directory created; the default still writes."""
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)/'root'; (root/'qa-factory/state').mkdir(parents=True)
            tasks=[{'task':'T','artifact_path':str(root/'qa-factory/artifacts/T'),'coverage':{},'manifest_entries':[]}]
            estimates=[{'task':'T','ts':'2026-09-16T00:00:00Z','forecast':{'size_final':'S'}}]
            before=_listing(root)
            cold=project(root,tasks,[],[],[],estimates,{},registry=[],write=False)
            self.assertEqual(_listing(root),before)
            self.assertFalse((root/'qa-factory/state/metrics.json').exists())
            written=project(root,tasks,[],[],[],estimates,{},registry=[])
            self.assertTrue((root/'qa-factory/state/metrics.json').is_file())
            self.assertEqual(json.loads((root/'qa-factory/state/metrics.json').read_text(encoding='utf-8'))['input_hash'],
                             written['input_hash'])
            for key in ('input_hash','source_manifest','errors','estimates','real_estimate_records'):
                self.assertEqual(cold[key],written[key],key)
            self.assertEqual([m['id'] for m in cold['metrics']],[m['id'] for m in written['metrics']])
            # the same call on a root that does not exist creates nothing either
            missing=Path(td)/'nothing-here'
            self.assertEqual(project(missing,[],[],[],[],[],{},write=False)['schema_version'],1)
            self.assertFalse(missing.exists())

    def test_size_normalizes_only_crlf(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'agent.md'
            for n in (8999,9000,9001):
                value=b'x'*(n-100)+b'\n'*100
                p.write_bytes(value);self.assertEqual(content_bytes(p),n)
                p.write_bytes(value.replace(b'\n',b'\r\n'));self.assertEqual(content_bytes(p),n)
            p.write_bytes('\u00e9\r\n'.encode('utf-8'));self.assertEqual(content_bytes(p),3)


class ReadOnlyRenderTests(unittest.TestCase):
    """B-197 / R15: `factory_dashboard.py --read-only` opens nothing under the root for writing.
    The invariant is measured on the whole tree: paths, sizes, mtimes and sha256 before and after."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.out = self.base / 'outside' / 'page.html'       # the one write allowed, outside the root

    def fixture(self, name, rendered_once=True):
        root = self.base / name
        build(root)
        if rendered_once:
            # a live root: the state a normal render leaves (metrics.json, history, signals, the page)
            _render(root, self.base / (name + '-first.html'))
        return root

    def read_only_leaves_the_tree_as_found(self, root):
        _make_old(root)
        before = _listing(root)
        _render(root, self.out, '--read-only')
        after = _listing(root)
        self.assertEqual(sorted(after), sorted(before), 'a file or directory was created or removed')
        self.assertEqual({k: v for k, v in after.items() if v != before[k]}, {}, 'a path changed')
        self.assertTrue(self.out.is_file() and self.out.stat().st_size > 0)

    def test_read_only_render_of_a_live_root_changes_no_byte_and_no_mtime(self):
        root = self.fixture('live')
        self.assertTrue((root / 'qa-factory/state/metrics.json').is_file())
        self.read_only_leaves_the_tree_as_found(root)

    def test_positive_control_the_same_render_without_read_only_writes_metrics_json(self):
        root = self.fixture('control')
        _make_old(root)
        before = _listing(root)
        _render(root, self.out)
        after = _listing(root)
        self.assertNotEqual(after['qa-factory/state/metrics.json'], before['qa-factory/state/metrics.json'])
        self.assertGreater(after['qa-factory/state/metrics.json'][2], before['qa-factory/state/metrics.json'][2])

    def test_edges_no_metrics_file_yet_an_invalid_one_and_no_state_folder(self):
        with self.subTest('no metrics.json yet (nothing has ever been rendered)'):
            root = self.fixture('never', rendered_once=False)
            self.assertFalse((root / 'qa-factory/state/metrics.json').exists())
            self.read_only_leaves_the_tree_as_found(root)
            self.assertFalse((root / 'qa-factory/state/metrics.json').exists())
        with self.subTest('metrics.json that is not JSON'):
            root = self.fixture('broken')
            (root / 'qa-factory/state/metrics.json').write_bytes(b'{not json')
            self.read_only_leaves_the_tree_as_found(root)
            self.assertEqual((root / 'qa-factory/state/metrics.json').read_bytes(), b'{not json')
        with self.subTest('a root with no state folder at all'):
            root = self.base / 'stateless'
            (root / 'qa-factory').mkdir(parents=True)
            (root / 'qa-factory/config.json').write_text('{}', encoding='utf-8')
            self.read_only_leaves_the_tree_as_found(root)
            self.assertFalse((root / 'qa-factory/state').exists())

    def test_read_only_needs_no_writer_of_metrics_json(self):
        """The mutation killer: with the projection's writer made to raise, --read-only still renders."""
        root = self.fixture('nowrite')
        boom = mock.Mock(side_effect=AssertionError('metrics_projection.atomic_json was called'))
        with mock.patch.object(metrics_projection, 'atomic_json', boom):
            self.read_only_leaves_the_tree_as_found(root)
        boom.assert_not_called()
        # and the control: the same patch does stop a normal render, so the patch is wired to the writer
        with mock.patch.object(metrics_projection, 'atomic_json', boom), self.assertRaises(AssertionError):
            _render(root, self.base / 'normal.html')


if __name__=='__main__':unittest.main()
