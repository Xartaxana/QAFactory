import copy
import json
import sys
import tempfile
from pathlib import Path
import unittest
from unittest import mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import metric_signals
from metric_signals import evaluate, hot_cache_share, _hot_cache_signals, refresh, MIN_HOT_CACHE_TOKENS
from dashboard_cost_groups import group, TOKEN_FIELDS
from dashboard_widgets import signals_html


class SignalsTests(unittest.TestCase):
    def snapshot(self, value, sample=20, revision='one', status='available', start='2026-09-01T00:00:00Z', end='2026-09-19T00:00:00Z', version=1):
        return {'input_hash':revision,'as_of':end,'metrics':[{'id':'F02','label':'Reject rate','value':{'rate':value},
            'status':status,'sample_size':sample,'scope':'project','formula_version':version,'window_start':start,'window_end':end}]}

    def policy(self, mode='absolute'):
        return {'version':'test-only-v1','rules':[{'id':'rejects','metric':'F02','field':'rate','direction':'above',
            'threshold':10,'recovery_threshold':5,'min_sample':10,'recovery_samples':2,'mode':mode}]}

    def test_breach_recovery_regression_missing_and_replay(self):
        policy=self.policy()
        first=evaluate(self.snapshot(20),[],{},policy)
        self.assertEqual(first['signals'][0]['status'],'active')
        unknown=evaluate(self.snapshot(None,status='partial'),[],first,policy)
        self.assertEqual(unknown['signals'][0]['status'],'active')
        self.assertEqual(unknown['signals'][0]['evaluation'],'not_evaluated')
        verifying=evaluate(self.snapshot(4,revision='two'),[],unknown,policy)
        self.assertEqual(verifying['signals'][0]['status'],'verifying')
        replay=evaluate(self.snapshot(4,revision='unrelated-change'),[],verifying,policy)
        self.assertEqual(replay['signals'][0]['recovery_count'],1)
        resolved=evaluate(self.snapshot(3,sample=21,revision='three'),[],replay,policy)
        self.assertEqual(resolved['signals'][0]['status'],'resolved')
        regression=evaluate(self.snapshot(20,sample=22,revision='four'),[],resolved,policy)
        self.assertEqual(regression['signals'][0]['status'],'active')
        self.assertEqual(len(regression['signals']),1)

    def test_nonoverlapping_comparable_windows_and_minimum_sample(self):
        policy=self.policy('trend')
        overlapping=self.snapshot(5,start='2026-08-28T00:00:00Z',end='2026-09-15T00:00:00Z')
        result=evaluate(self.snapshot(20),[overlapping],{},policy)
        self.assertEqual(result['evaluations'][0]['status'],'not_evaluated')
        baseline=self.snapshot(5,start='2026-08-14T00:00:00Z',end='2026-09-01T00:00:00Z')
        result=evaluate(self.snapshot(20),[baseline],{},policy)
        self.assertEqual(result['signals'][0]['baseline'],5)
        self.assertEqual(result['signals'][0]['status'],'active')
        low=evaluate(self.snapshot(20,sample=9),[baseline],{},policy)
        self.assertFalse(low['signals'])
        incompatible=copy.deepcopy(baseline);incompatible['metrics'][0]['scope']='another-project'
        self.assertFalse(evaluate(self.snapshot(20),[incompatible],{},policy)['signals'])

    def test_a_baseline_of_another_formula_version_is_an_incompatible_baseline(self):
        """t-196: the money metrics moved to formula version 2 (the price now comes from the story's own
        rate base). The module already reads a baseline as compatible only on an equal version: the old
        version-1 points give the existing 'no comparable baseline' state, not a new one."""
        policy=self.policy('trend')
        baseline=self.snapshot(5,start='2026-08-14T00:00:00Z',end='2026-09-01T00:00:00Z')
        control=evaluate(self.snapshot(20),[baseline],{},policy)
        self.assertEqual(control['signals'][0]['baseline'],5,'control: the same baseline at an equal version is used')
        moved=evaluate(self.snapshot(20,version=2),[baseline],{},policy)
        self.assertFalse(moved['signals'])
        self.assertEqual([(e['status'],e['reason']) for e in moved['evaluations']],
                         [('not_evaluated','No complete, comparable non-overlapping baseline window')])
        later=copy.deepcopy(baseline);later['metrics'][0]['formula_version']=2
        self.assertEqual(evaluate(self.snapshot(20,version=2),[later],{},policy)['signals'][0]['baseline'],5,
                         'a baseline of the new version is compared')

    def test_a_money_metric_of_the_projection_meets_its_old_history_as_incompatible(self):
        """The real `compute` builds C02 at version 2; a history point an older build wrote (version 1)
        is not its baseline. Killer of 'a money metric left at version 1'."""
        from datetime import datetime, timezone
        import metrics_projection
        now=datetime(2026,9,18,tzinfo=timezone.utc)
        data={'sessions':[{'usage_completeness':'complete','requests':[{
            'request_key':'k','timestamp':'2026-09-17T00:00:00Z','stream':'orchestrator','model_id':'m',
            'activity_id':'a','activity_segment_id':'s','usage':{'input':1},
            'valuation':{'subtotal_usd':'25','pricing_coverage':'complete'}}]}]}
        c02=next(m for m in metrics_projection.compute(data,now) if m['id']=='C02')
        self.assertEqual((c02['status'],c02['formula_version']),('available',2))
        start,end=metrics_projection.timestamp(c02['window_start']),metrics_projection.timestamp(c02['window_end'])
        def history(version):
            return [{'as_of':'2026-08-01T00:00:00Z','metrics':[dict(c02,value=5,formula_version=version,
                     window_start=(start-(end-start)).isoformat(),window_end=start.isoformat())]}]
        snapshot={'input_hash':'h','as_of':now.isoformat(),'metrics':[c02]}
        policy={'version':'test-only-v1','rules':[{'id':'cost','metric':'C02','direction':'above','threshold':10,
            'recovery_threshold':5,'min_sample':1,'recovery_samples':1,'mode':'trend'}]}
        self.assertEqual(evaluate(snapshot,history(2),{},policy)['signals'][0]['baseline'],5,'control: an equal version compares')
        old=evaluate(snapshot,history(1),{},policy)
        self.assertFalse(old['signals'])
        self.assertEqual(old['evaluations'][0]['reason'],'No complete, comparable non-overlapping baseline window')

    def test_rule_version_is_required_and_retirement_cannot_clear(self):
        with self.assertRaises(ValueError): evaluate(self.snapshot(20),[],{},dict(self.policy(),version=None))
        previous=evaluate(self.snapshot(20),[],{},self.policy())
        retired=evaluate(self.snapshot(0),[],previous,{})
        self.assertEqual(retired['signals'][0]['evaluation'],'not_evaluated')

    def test_acknowledgement_never_resolves_and_regression_reactivates(self):
        first=evaluate(self.snapshot(20),[],{},self.policy())
        first['signals'][0].update(status='verifying',acknowledged_at='2026-09-19',decision_ref='decision.md')
        same=evaluate(self.snapshot(20),[],first,self.policy())
        self.assertEqual(same['signals'][0]['status'],'verifying')
        worse=evaluate(self.snapshot(25),[],same,self.policy())
        self.assertEqual(worse['signals'][0]['status'],'active')


def _session(session_id, input_=0, output=0, cache_read=0, cache_write_5m=0, cache_write_1h=0,
             started='2026-09-20T09:00:00Z', ended='2026-09-20T10:00:00Z'):
    return {'session_id': session_id, 'started': started, 'ended': ended,
            'by_model': {'m': {'input': input_, 'output': output, 'cache_read': cache_read,
                               'cache_write_5m': cache_write_5m, 'cache_write_1h': cache_write_1h}}}


def _story_session(session_id, task, kind, input_=0, output=0, cache_read=0, cache_write_5m=0, cache_write_1h=0):
    usage = {'input': input_, 'output': output, 'cache_read': cache_read,
             'cache_write_5m': cache_write_5m, 'cache_write_1h': cache_write_1h}
    row = {'request_key': session_id + ':1', 'task': task, 'activity_id': 'a1',
           'timestamp': '2026-09-20T00:00:00Z', 'usage': usage,
           'valuation': {'pricing_coverage': 'complete', 'subtotal_usd': '1'}}
    return {'session_id': session_id, 'usage_completeness': 'complete',
            'by_activity': {'a1': {'type': kind, 'task': task}}, 'requests': [row],
            'by_model': {'m': usage}}


def _cold(session_id, task='S1', share=5):
    """A 200k-token story session with the given hot-cache share in percent."""
    read = 2_000 * share
    return _story_session(session_id, task, 'story', input_=200_000 - read, cache_read=read)


def _warm(session_id, task='S1'):
    return _story_session(session_id, task, 'story', cache_read=200_000)


class HotCacheSignalTests(unittest.TestCase):
    """warns on hot-cache share, one signal per story/label, through the shared signal engine."""

    def snapshot(self):
        return {'as_of': '2026-09-20T10:00:00Z', 'input_hash': 'h', 'metrics': []}

    def _refresh_snapshot(self, as_of='2026-09-20T10:00:00Z'):
        # refresh() also runs the legacy-estimate loop, which needs a C08 metric on the snapshot.
        return dict(self.snapshot(), as_of=as_of, metrics=[{'id': 'C08', 'label': 'Tokenomics band hit',
            'value': None, 'status': 'unavailable', 'sample_size': 0, 'scope': 'project',
            'formula_version': 1, 'window_start': '2026-09-01T00:00:00Z', 'window_end': '2026-09-20T10:00:00Z'}])

    def _ids(self, receipt):
        return [s['id'] for s in receipt['signals']]

    def _hc(self, signals):
        return [s for s in signals if s['id'].startswith('hot-cache-v1:')]

    def test_formula_excludes_output_and_handles_no_denominator(self):
        self.assertEqual(hot_cache_share({'cache_read': 90, 'input': 10, 'output': 900}), 90.0)
        self.assertIsNone(hot_cache_share({'output': 500}))

    def test_small_session_is_not_evaluated_not_alarmed(self):
        cold = _session('tiny', input_=100, cache_read=10)  # far under MIN_HOT_CACHE_TOKENS
        self.assertLess(sum(cold['by_model']['m'].values()), MIN_HOT_CACHE_TOKENS)
        signals, evaluations = _hot_cache_signals(self.snapshot(), {}, [cold], {})
        self.assertFalse(signals)
        self.assertTrue(any(e['status'] == 'not_evaluated' for e in evaluations))

    def test_large_cold_session_raises_one_story_signal_listing_it(self):
        signals, _ = _hot_cache_signals(self.snapshot(), {}, [_cold('sess-1')], {})  # 5% hot cache, 200k tokens
        self.assertEqual([s['id'] for s in signals], ['hot-cache-v1:story-S1'])
        sig = signals[0]
        self.assertEqual(sig['status'], 'active')
        self.assertEqual(sig['title'], 'Hot cache share below 90% - S1: 1 of 1 sessions')
        self.assertEqual(sig['sessions'], [{'session_id': 'sess-1', 'share': 5.0, 'tokens': 200_000}])
        self.assertEqual(sig['scope_share'], 5.0)

    def test_warm_story_raises_no_signal(self):
        signals, _ = _hot_cache_signals(self.snapshot(), {}, [_warm('sess-2')], {})
        self.assertFalse(signals)

    def test_threshold_from_config_overrides_default(self):
        session = _story_session('sess-3', 'S3', 'story', input_=100_000, cache_read=130_000)  # 56.5% hot cache
        default_signals, _ = _hot_cache_signals(self.snapshot(), {}, [session], {})
        self.assertEqual([s['id'] for s in default_signals], ['hot-cache-v1:story-S3'])
        loose_signals, _ = _hot_cache_signals(self.snapshot(), {}, [session], {'metrics': {'hot_cache_min_percent': 50}})
        self.assertFalse(loose_signals)

    def test_a_three_cold_one_warm_story_is_one_signal_with_sorted_sessions(self):
        sessions = [_cold('c3', share=15), _warm('w'), _cold('c1', share=5), _cold('c2', share=10)]
        signals, _ = _hot_cache_signals(self.snapshot(), {}, sessions, {})
        self.assertEqual(len(signals), 1)
        sig = signals[0]
        self.assertEqual(sig['id'], 'hot-cache-v1:story-S1')
        self.assertEqual(sig['title'], 'Hot cache share below 90% - S1: 3 of 4 sessions')
        self.assertEqual([s['session_id'] for s in sig['sessions']], ['c1', 'c2', 'c3'])
        self.assertEqual([s['share'] for s in sig['sessions']], [5.0, 10.0, 15.0])
        self.assertEqual(sig['current'], 5.0)

    def test_b_warm_story_average_does_not_hide_one_cold_session(self):
        sessions = [_warm('w%d' % i) for i in range(9)] + [_cold('cold', share=5)]
        story = _hot_cache_signals(self.snapshot(), {}, sessions, {})
        composition = {k: sum(s['by_model']['m'][k] for s in sessions) for k in ('input', 'cache_read')}
        self.assertGreaterEqual(hot_cache_share(composition), 90)  # the label's own share is warm...
        signals, _ = story
        self.assertEqual(len(signals), 1)  # ...and the cold session still fires
        self.assertEqual(signals[0]['current'], 5.0)
        self.assertEqual([s['session_id'] for s in signals[0]['sessions']], ['cold'])
        self.assertEqual(signals[0]['title'], 'Hot cache share below 90% - S1: 1 of 10 sessions')

    def test_c_cold_session_under_min_tokens_does_not_fire_and_is_not_listed(self):
        tiny_cold = _story_session('tiny', 'S1', 'story', input_=100, cache_read=10)  # 9 % share, 110 tokens
        self.assertLess(110, MIN_HOT_CACHE_TOKENS)
        signals, evaluations = _hot_cache_signals(self.snapshot(), {}, [_warm('w'), tiny_cold], {})
        self.assertFalse(signals)
        # ...and next to a genuinely cold session it is not among the listed ones.
        signals, _ = _hot_cache_signals(self.snapshot(), {}, [_warm('w'), tiny_cold, _cold('c')], {})
        self.assertEqual([s['session_id'] for s in signals[0]['sessions']], ['c'])
        self.assertIn('1 of 2 sessions', signals[0]['title'])
        only_tiny, evaluations = _hot_cache_signals(self.snapshot(), {}, [tiny_cold], {})
        self.assertFalse(only_tiny)
        self.assertTrue(any(e['status'] == 'not_evaluated' for e in evaluations))

    def test_non_story_labels_are_grouped_like_stories(self):
        story = _cold('s1', task='TP1-1')
        doctor = _story_session('s2', None, 'doctor', input_=190_000, cache_read=10_000)
        signals, _ = _hot_cache_signals(self.snapshot(), {}, [story, doctor], {})
        self.assertEqual(sorted(s['id'] for s in signals),
                         ['hot-cache-v1:story-Doctor', 'hot-cache-v1:story-TP1-1'])
        self.assertFalse([s for s in signals if ':session-' in s['id']])

    def test_legacy_multi_task_session_fires_under_each_label_named_legacy_index(self):
        # Two small cold requests-sessions of label A (100k tokens each, 5 %): together 200k tokens
        # at 5 %, which would be A's own share if A's composition were complete.
        small = [_story_session('small%d' % i, 'A', 'story', input_=95_000, cache_read=5_000) for i in (0, 1)]
        # A legacy whole-session row: no requests[], no session_id, two tasks, 200k tokens at 50 %.
        # tokens=None on its by_task rows: the label's own token count is 0, the session's is not.
        legacy = {'usage_completeness': 'complete', 'by_model': {'m': {
            'input': 100_000, 'output': 0, 'cache_read': 100_000, 'cache_write_5m': 0, 'cache_write_1h': 0}},
            'by_task': {'A': {'tokens': None, 'cost': None}, 'B': {'tokens': None, 'cost': None}}}
        signals, _ = _hot_cache_signals(self.snapshot(), {}, small + [legacy], {})
        by_id = {s['id']: s for s in signals}
        self.assertEqual(sorted(by_id), ['hot-cache-v1:story-A', 'hot-cache-v1:story-B'])
        for label in ('A', 'B'):
            sig = by_id['hot-cache-v1:story-' + label]
            self.assertEqual(sig['evaluation'], 'evaluated')  # B has no tokens of its own: sample must not be 0
            # named legacy-<index in sessions>, exactly as group_cost names it (B-195: whole session under both)
            self.assertEqual(sig['sessions'], [{'session_id': 'legacy-2', 'share': 50.0, 'tokens': 200_000}])
            self.assertEqual(sig['title'], f'Hot cache share below 90% - {label}: 1 of 1 sessions')
            # A's composition is incomplete (the legacy row split over two tasks): its own share
            # (5 % from the small sessions) must not contribute.
            self.assertIsNone(sig['scope_share'])
            self.assertEqual(sig['current'], 50.0)

    def test_no_sessions_no_signals(self):
        for sessions in ([], None):
            self.assertEqual(_hot_cache_signals(self.snapshot(), {}, sessions or [], {}), ([], []))

    def test_share_is_rounded_for_display_but_the_threshold_sees_the_exact_value(self):
        # 179_980 / 200_000 = 89.99 %: rounds to 90.0 yet is below the 90 % threshold.
        edge = _story_session('edge', 'S1', 'story', input_=20_020, cache_read=179_980)
        signals, _ = _hot_cache_signals(self.snapshot(), {}, [edge], {})
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0]['current'], 90.0)
        self.assertEqual(signals[0]['sessions'][0]['share'], 90.0)
        odd = _story_session('odd', 'S2', 'story', input_=51_000, cache_read=200_000)  # 79.6813 %
        signals, _ = _hot_cache_signals(self.snapshot(), {}, [odd], {})
        self.assertEqual(signals[0]['current'], 79.7)

    def test_refresh_wires_sessions_and_cfg_threshold_end_to_end(self):
        with tempfile.TemporaryDirectory() as td:
            receipt, _ = refresh(td, self._refresh_snapshot(), {}, [_cold('sess-9', task='S9')])
            self.assertTrue([s for s in receipt['signals'] if s['id'] == 'hot-cache-v1:story-S9' and s['status'] == 'active'])
            loose_receipt, _ = refresh(td, self._refresh_snapshot(), {'metrics': {'hot_cache_min_percent': 1}},
                                       [_cold('sess-10', task='S10')])
            self.assertFalse([s for s in loose_receipt['signals'] if s['id'] == 'hot-cache-v1:story-S10'])
            # metric-signals.json actually persisted, same file the shared banner reads.
            self.assertTrue((Path(td) / 'qa-factory/state/metric-signals.json').exists())

    def test_repeated_refresh_keeps_each_signal_id_once(self):
        sid = 'hot-cache-v1:story-S1'
        with tempfile.TemporaryDirectory() as td:
            first, _ = refresh(td, self._refresh_snapshot(), {}, [_cold('sess-dup')])
            first_seen = next(s for s in first['signals'] if s['id'] == sid)['first_seen']
            later = self._refresh_snapshot('2026-09-21T10:00:00Z')
            for _ in range(2):
                second, _ = refresh(td, later, {}, [_cold('sess-dup')])
                self.assertEqual(len(self._ids(second)), len(set(self._ids(second))))
                on_disk = json.loads((Path(td) / 'qa-factory/state/metric-signals.json').read_text(encoding='utf-8'))
                self.assertEqual(len(self._ids(on_disk)), len(set(self._ids(on_disk))))
                mine = [s for s in second['signals'] if s['id'] == sid]
                self.assertEqual(len(mine), 1)
                self.assertEqual(mine[0]['evaluation'], 'evaluated')
                self.assertEqual(mine[0]['first_seen'], first_seen)

    def test_duplicates_already_on_disk_heal_in_one_refresh(self):
        sid = 'hot-cache-v1:story-S1'
        with tempfile.TemporaryDirectory() as td:
            first, _ = refresh(td, self._refresh_snapshot(), {}, [_cold('sess-heal')])
            good = next(s for s in first['signals'] if s['id'] == sid)
            ghost = dict(good, evaluation='not_evaluated', reason='Rule retired or policy version changed',
                         first_seen='1999-01-01T00:00:00Z')
            path = Path(td) / 'qa-factory/state/metric-signals.json'
            # not_evaluated copy first: the evaluated one must still win and lend its lifecycle.
            path.write_text(json.dumps(dict(first, signals=[ghost, good])), encoding='utf-8')
            healed, _ = refresh(td, self._refresh_snapshot(), {}, [_cold('sess-heal')])
            mine = [s for s in healed['signals'] if s['id'] == sid]
            self.assertEqual(len(mine), 1)
            self.assertEqual(mine[0]['first_seen'], good['first_seen'])
            self.assertEqual(len(self._ids(healed)), len(set(self._ids(healed))))

    def test_prior_signal_outside_this_refresh_stays_once_as_not_evaluated(self):
        sid = 'hot-cache-v1:story-S1'
        with tempfile.TemporaryDirectory() as td:
            refresh(td, self._refresh_snapshot(), {}, [_cold('sess-gone')])
            for sessions in ([], None):
                receipt, _ = refresh(td, self._refresh_snapshot(), {}, sessions)
                mine = [s for s in receipt['signals'] if s['id'] == sid]
                self.assertEqual(len(mine), 1)
                self.assertEqual(mine[0]['evaluation'], 'not_evaluated')

    def test_d_previous_per_session_signals_are_dropped_in_every_state(self):
        old = {'severity': 'warning', 'metric': 'C-hot-cache', 'scope': 'session x', 'title': 'old',
               'baseline': None, 'current': 5.0, 'sample_size': 200_000, 'window_start': 'a', 'window_end': 'b',
               'next_action': 'x', 'rule_version': 'hot-cache-v1', 'first_seen': 'a', 'reason': ''}
        seeded = {'signals': [dict(old, id='hot-cache-v1:session-x', status='active', evaluation='evaluated'),
                              dict(old, id='hot-cache-v1:session-y', status='active', evaluation='not_evaluated'),
                              dict(old, id='hot-cache-v1:session-z', status='verifying', evaluation='evaluated')]}
        for sessions in ([_cold('x'), _cold('y')], []):
            with tempfile.TemporaryDirectory() as td:
                path = Path(td) / 'qa-factory/state/metric-signals.json'
                path.parent.mkdir(parents=True)
                path.write_text(json.dumps(seeded), encoding='utf-8')
                receipt, _ = refresh(td, self._refresh_snapshot(), {}, sessions)
                self.assertFalse([i for i in self._ids(receipt) if i.startswith('hot-cache-v1:session-')])
                on_disk = json.loads(path.read_text(encoding='utf-8'))
                self.assertFalse([i for i in self._ids(on_disk) if i.startswith('hot-cache-v1:session-')])

    def test_acknowledged_signal_is_not_reactivated_by_rounding(self):
        odd = lambda: _story_session('odd', 'S2', 'story', input_=51_000, cache_read=200_000)  # 79.6813 %
        with tempfile.TemporaryDirectory() as td:
            refresh(td, self._refresh_snapshot(), {}, [odd()])
            path = Path(td) / 'qa-factory/state/metric-signals.json'
            receipt = json.loads(path.read_text(encoding='utf-8'))
            receipt['signals'][0].update(status='verifying', acknowledged_at='2026-09-20', decision_ref='d.md')
            path.write_text(json.dumps(receipt), encoding='utf-8')
            again, _ = refresh(td, self._refresh_snapshot('2026-09-21T10:00:00Z'), {}, [odd()])
            sig = next(s for s in again['signals'] if s['id'] == 'hot-cache-v1:story-S2')
            self.assertEqual(sig['status'], 'verifying')

    def test_recovery_lifecycle_matches_other_rules(self):
        first, _ = _hot_cache_signals(self.snapshot(), {}, [_cold('sess-4')], {})
        active = next(s for s in first if s['id'] == 'hot-cache-v1:story-S1')
        self.assertEqual(active['status'], 'active')
        second, _ = _hot_cache_signals(self.snapshot(), {'signals': first}, [_warm('sess-4')], {})
        recovered = next(s for s in second if s['id'] == 'hot-cache-v1:story-S1')
        self.assertEqual(recovered['status'], 'resolved')


def _part(kind, task, tokens, share):
    """One request of `tokens` tokens at `share` percent hot cache, under activity `kind`."""
    read = tokens * share // 100
    return (kind, task, {'input': tokens - read, 'cache_read': read})


def _multi_session(session_id, parts, carried=()):
    """A request-ledger session with one request per part; the parts at the indexes in `carried`
    carry a `carry:` request id (what cost_capture.collapse_requests leaves)."""
    activities, requests, total = {}, [], {k: 0 for k in TOKEN_FIELDS}
    for n, (kind, task, usage) in enumerate(parts):
        usage = {k: usage.get(k, 0) for k in TOKEN_FIELDS}
        activities['a%d' % n] = {'type': kind, 'task': task}
        requests.append({'request_key': '%s:%d' % (session_id, n),
                         'request_id': 'carry:s:m' if n in carried else 'r%d' % n,
                         'task': task, 'activity_id': 'a%d' % n, 'timestamp': '2026-09-20T00:00:00Z',
                         'usage': usage, 'valuation': {'pricing_coverage': 'complete', 'subtotal_usd': '1'}})
        for k in TOKEN_FIELDS:
            total[k] += usage[k]
    return {'session_id': session_id, 'usage_completeness': 'complete', 'by_activity': activities,
            'requests': requests, 'by_model': {'m': total}}


def _unbound(session_id, share=5, tokens=200_000):
    """A cold session the capture tags to no task: it lands under Unclassified until bound."""
    return _multi_session(session_id, [_part('other', None, tokens, share)])


def _tokens(composition):
    return sum(composition[k] for k in TOKEN_FIELDS)


class PairCompositionTests(unittest.TestCase):
    """R14 / B-195: a session is judged under a label by that pair's own requests."""
    SNAP = {'as_of': '2026-09-20T10:00:00Z', 'input_hash': 'h', 'metrics': []}

    def run_signals(self, sessions, **kwargs):
        signals, evaluations = _hot_cache_signals(self.SNAP, {}, sessions, {}, **kwargs)
        return {s['id']: s for s in signals}, {e['id']: e for e in evaluations}

    def test_item1_group_keeps_two_values_and_carries_the_pair_composition(self):
        session = _multi_session('big', [_part('doctor', None, 1_000, 100), _part('story', 'X', 999_000, 50)])
        result = group([session])
        self.assertEqual(len(result), 2)  # mutation (d): three values
        tasks, days = result
        doctor, story = tasks['Doctor']['by_session']['big'], tasks['X']['by_session']['big']
        self.assertEqual((_tokens(doctor['composition']), doctor['composition']['cache_read']), (1_000, 1_000))
        self.assertEqual((_tokens(story['composition']), story['composition']['cache_read']), (999_000, 499_500))
        self.assertFalse(doctor['whole_session'] or story['whole_session'])
        self.assertEqual(tasks['X']['tokens'], 999_000)  # the label's own totals are untouched

    def test_item2_b195_probe_doctor_pair_below_minimum_story_judged_on_its_own_share(self):
        session = _multi_session('big', [_part('doctor', None, 1_000, 100), _part('story', 'X', 999_000, 50)])
        self.assertEqual(_tokens(session['by_model']['m']), 1_000_000)
        signals, evaluations = self.run_signals([session])
        self.assertNotIn('hot-cache-v1:story-Doctor', signals)  # mutations (a), (b)
        self.assertEqual(evaluations['hot-cache-v1:story-Doctor']['status'], 'not_evaluated')  # mutation (a)
        sig = signals['hot-cache-v1:story-X']
        self.assertEqual(sig['sessions'], [{'session_id': 'big', 'share': 50.0, 'tokens': 999_000}])  # mutation (b)
        self.assertEqual((sig['current'], sig['scope_share']), (50.0, 50.0))
        self.assertNotIn('note', sig)

    def test_item2_probe_with_a_cold_doctor_pair_still_raises_nothing_for_doctor(self):
        session = _multi_session('big', [_part('doctor', None, 1_000, 0), _part('story', 'X', 999_000, 50)])
        signals, evaluations = self.run_signals([session])
        self.assertNotIn('hot-cache-v1:story-Doctor', signals)  # mutation (a): a cold pair would be listed
        self.assertEqual(evaluations['hot-cache-v1:story-Doctor']['status'], 'not_evaluated')
        self.assertEqual([x['session_id'] for x in signals['hot-cache-v1:story-X']['sessions']], ['big'])

    def test_e15_pair_tokens_at_199999_and_200000(self):
        for pair_tokens, evaluated in ((199_999, False), (200_000, True)):
            with self.subTest(pair_tokens=pair_tokens):
                session = _multi_session('big', [_part('doctor', None, pair_tokens, 0),
                                                 _part('story', 'X', 1_000_000 - pair_tokens, 100)])
                self.assertEqual(_tokens(session['by_model']['m']), 1_000_000)
                signals, evaluations = self.run_signals([session])
                doctor = signals.get('hot-cache-v1:story-Doctor')
                self.assertEqual(evaluations['hot-cache-v1:story-Doctor']['status'],
                                 'evaluated' if evaluated else 'not_evaluated')
                if evaluated:
                    self.assertEqual(doctor['sessions'], [{'session_id': 'big', 'share': 0.0, 'tokens': 200_000}])
                else:
                    self.assertIsNone(doctor)
                self.assertNotIn('hot-cache-v1:story-X', signals)  # the warm rest never alarms

    def test_e_session_with_requests_under_three_labels_is_judged_per_pair(self):
        session = _multi_session('three', [_part('doctor', None, 1_000, 0), _part('story', 'X', 400_000, 50),
                                           _part('story', 'Y', 600_000, 100)])
        signals, evaluations = self.run_signals([session])
        self.assertEqual(sorted(signals), ['hot-cache-v1:story-X'])
        self.assertEqual(signals['hot-cache-v1:story-X']['sessions'],
                         [{'session_id': 'three', 'share': 50.0, 'tokens': 400_000}])
        self.assertEqual(evaluations['hot-cache-v1:story-Y']['status'], 'evaluated')
        self.assertEqual(evaluations['hot-cache-v1:story-Doctor']['status'], 'not_evaluated')

    def test_e_zero_token_pair_and_empty_or_foreign_label_values_raise_nothing_and_list_nothing(self):
        session = _multi_session('z', [_part('doctor', None, 0, 0), _part('story', 'X', 300_000, 50)])
        signals, evaluations = self.run_signals([session])
        self.assertNotIn('hot-cache-v1:story-Doctor', signals)
        self.assertEqual(evaluations['hot-cache-v1:story-Doctor']['status'], 'not_evaluated')
        self.assertEqual(len(signals['hot-cache-v1:story-X']['sessions']), 1)
        ghost = {'session_ids': set(), 'tokens': 0, 'composition': {}}  # no sessions, no by_session key
        stale = {'session_ids': {'s'}, 'tokens': 5, 'composition': {}, 'by_session': {}}
        with mock.patch.object(metric_signals, 'group_cost', return_value=({'Ghost': ghost, 'Stale': stale}, {})):
            signals, evaluations = self.run_signals([])
        self.assertEqual(signals, {})
        self.assertEqual({e['status'] for e in evaluations.values()}, {'not_evaluated'})

    def test_e_task_of_none_and_empty_give_the_same_signals(self):
        session = _multi_session('big', [_part('doctor', None, 1_000, 0), _part('story', 'X', 999_000, 50)])
        self.assertEqual(self.run_signals([session], task_of=None), self.run_signals([session], task_of={}))
        self.assertEqual(self.run_signals([session]), self.run_signals([session], task_of=None))

    def test_item3_legacy_session_without_a_ledger_keeps_the_whole_session_under_each_label(self):
        whole = {'input': 100_000, 'output': 0, 'cache_read': 100_000, 'cache_write_5m': 0, 'cache_write_1h': 0}
        legacy = {'session_id': 'old', 'usage_completeness': 'complete', 'by_model': {'m': whole},
                  'by_task': {'A': {'tokens': 50_000, 'cost': 1}, 'B': {'tokens': 150_000, 'cost': 1}}}
        tasks, _ = group([legacy])
        for label in ('A', 'B'):
            pair = tasks[label]['by_session']['old']
            self.assertTrue(pair['whole_session'])
            self.assertEqual(pair['composition'], whole)
        signals, _ = self.run_signals([legacy])
        for label in ('A', 'B'):
            self.assertEqual(signals['hot-cache-v1:story-' + label]['sessions'],
                             [{'session_id': 'old', 'share': 50.0, 'tokens': 200_000}])

    def test_item3_a_fully_collapsed_ledger_is_a_whole_session(self):
        session = _multi_session('col', [_part('other', None, 120_000, 50), _part('other', None, 130_000, 50)],
                                 carried=(0, 1))
        pair = group([session])[0]['Unclassified']['by_session']['col']
        self.assertTrue(pair['whole_session'])
        self.assertFalse(pair['partial_ledger'])
        self.assertEqual(_tokens(pair['composition']), 250_000)
        signals, _ = self.run_signals([session])
        self.assertEqual(signals['hot-cache-v1:story-Unclassified']['sessions'],
                         [{'session_id': 'col', 'share': 50.0, 'tokens': 250_000}])
        self.assertNotIn('note', signals['hot-cache-v1:story-Unclassified'])

    def test_e_partly_collapsed_ledger_is_judged_whole_and_the_note_says_so(self):
        # Doctor's own requests are 1,000 tokens; one request is carried, so the session is whole.
        session = _multi_session('part', [_part('doctor', None, 1_000, 100), _part('story', 'X', 999_000, 50)],
                                 carried=(1,))
        tasks, _ = group([session])
        self.assertTrue(tasks['Doctor']['by_session']['part']['partial_ledger'])
        self.assertEqual(_tokens(tasks['Doctor']['by_session']['part']['composition']), 1_000_000)
        signals, _ = self.run_signals([session])
        for label in ('Doctor', 'X'):
            sig = signals['hot-cache-v1:story-' + label]
            self.assertEqual([x['tokens'] for x in sig['sessions']], [1_000_000])  # never half by each rule
            self.assertIn('partly collapsed', sig['note'])
            self.assertIn('part', sig['note'])


class MovedUnclassifiedTests(unittest.TestCase):
    """R16 / C7: an old Unclassified signal is resolved only when EVERY session it lists moved."""
    U = 'hot-cache-v1:story-Unclassified'

    def snap(self, as_of='2026-09-20T10:00:00Z'):
        return {'as_of': as_of, 'input_hash': 'h', 'metrics': [{'id': 'C08', 'label': 'Tokenomics band hit',
                'value': None, 'status': 'unavailable', 'sample_size': 0, 'scope': 'project',
                'formula_version': 1, 'window_start': '2026-09-01T00:00:00Z', 'window_end': as_of}]}

    def old_receipt(self, td, ids=('u1', 'u2')):
        receipt, _ = refresh(td, self.snap(), {}, [_unbound(i) for i in ids])
        old = [s for s in receipt['signals'] if s['id'] == self.U]
        self.assertEqual(len(old), 1)
        self.assertEqual(old[0]['status'], 'active')
        self.assertEqual(sorted(x['session_id'] for x in old[0]['sessions']), sorted(ids))
        return old[0]

    def second(self, td, sessions, task_of):
        receipt, _ = refresh(td, self.snap('2026-09-21T10:00:00Z'), {}, sessions, task_of)
        mine = [s for s in receipt['signals'] if s['id'] == self.U]
        return receipt, mine

    def test_item4_all_sessions_moved_resolves_with_the_tasks_named_and_no_not_evaluated(self):
        with tempfile.TemporaryDirectory() as td:
            self.old_receipt(td)
            receipt, mine = self.second(td, [_unbound('u1'), _unbound('u2')], {'u1': 'T1', 'u2': 'T2'})
            self.assertEqual(len(mine), 1)
            self.assertEqual(mine[0]['status'], 'resolved')
            self.assertEqual(mine[0]['reason'], 'sessions moved to T1, T2')
            self.assertNotEqual(mine[0]['evaluation'], 'not_evaluated')
            self.assertEqual(len(self._ids(receipt)), len(set(self._ids(receipt))))
            on_disk = json.loads((Path(td) / 'qa-factory/state/metric-signals.json').read_text(encoding='utf-8'))
            self.assertEqual([s['status'] for s in on_disk['signals'] if s['id'] == self.U], ['resolved'])
            # the moved sessions are judged under their new labels
            self.assertEqual({'hot-cache-v1:story-T1', 'hot-cache-v1:story-T2'} - set(self._ids(receipt)), set())

    def _ids(self, receipt):
        return [s['id'] for s in receipt['signals']]

    def test_item4_sessions_moved_to_one_task_name_it_once(self):
        with tempfile.TemporaryDirectory() as td:
            self.old_receipt(td)
            _, mine = self.second(td, [_unbound('u1'), _unbound('u2')], {'u1': 'T1', 'u2': 'T1'})
            self.assertEqual((mine[0]['status'], mine[0]['reason']), ('resolved', 'sessions moved to T1'))

    def test_item4_a_listed_session_bound_to_a_task_with_no_cost_file_resolves_nothing(self):
        with tempfile.TemporaryDirectory() as td:
            old = self.old_receipt(td)
            _, mine = self.second(td, [_unbound('u1')], {'u1': 'T1', 'u2': 'T2'})  # u2: journal only  (mutation c)
            self.assertEqual(len(mine), 1)
            self.assertEqual(mine[0]['status'], 'active')
            self.assertNotIn('moved', mine[0]['reason'])
            self.assertEqual(mine[0]['sessions'], old['sessions'])
        signals, _ = _hot_cache_signals(self.snap(), {'signals': [old]}, [_unbound('u1')], {}, {'u1': 'T1', 'u2': 'T2'})
        self.assertNotIn(self.U, [s['id'] for s in signals])  # nothing resolved, nothing rewritten here

    def test_e_half_moved_half_still_unbound_keeps_the_signal_alive(self):
        with tempfile.TemporaryDirectory() as td:
            self.old_receipt(td)
            _, mine = self.second(td, [_unbound('u1'), _unbound('u2')], {'u1': 'T1'})
            self.assertEqual(len(mine), 1)
            self.assertEqual(mine[0]['status'], 'active')
            self.assertEqual(mine[0]['evaluation'], 'evaluated')
            self.assertEqual([x['session_id'] for x in mine[0]['sessions']], ['u2'])

    def test_e_a_moved_session_under_the_minimum_on_its_new_label_resolves_nothing(self):
        with tempfile.TemporaryDirectory() as td:
            old = self.old_receipt(td)
            small = _unbound('u2', tokens=1_000)
            signals, _ = _hot_cache_signals(self.snap(), {'signals': [old]}, [_unbound('u1'), small], {},
                                            {'u1': 'T1', 'u2': 'T2'})
            self.assertNotIn(self.U, [s['id'] for s in signals])

    def test_e_zero_listed_sessions_or_none_existing_now_is_left_alone(self):
        with tempfile.TemporaryDirectory() as td:
            old = self.old_receipt(td)
        legacy_now = {'usage_completeness': 'complete', 'by_model': {'m': {'input': 100_000, 'cache_read': 100_000}},
                      'by_task': {'T9': {'tokens': 200_000, 'cost': 1}}}
        cases = {'no sessions key': {k: v for k, v in old.items() if k != 'sessions'},
                 'empty list': dict(old, sessions=[]),
                 'sessions gone': dict(old, sessions=[{'session_id': 'ghost-1', 'share': 5.0, 'tokens': 200_000}]),
                 'legacy stand-in id': dict(old, sessions=[{'session_id': 'legacy-1', 'share': 5.0, 'tokens': 200_000}]),
                 'malformed entry': dict(old, sessions=['u1'])}
        for name, prior in cases.items():
            with self.subTest(name):
                signals, _ = _hot_cache_signals(self.snap(), {'signals': [prior]}, [_unbound('u1'), legacy_now],
                                                {}, {'u1': 'T1', 'ghost-1': 'T1'})
                self.assertNotIn(self.U, [s['id'] for s in signals])
        with tempfile.TemporaryDirectory() as td:
            self.old_receipt(td)
            _, mine = self.second(td, [], {'u1': 'T1', 'u2': 'T2'})
            self.assertEqual((len(mine), mine[0]['status']), (1, 'active'))
            self.assertEqual(mine[0]['sessions'], old['sessions'])

    def test_e_an_already_resolved_signal_is_not_resolved_again(self):
        with tempfile.TemporaryDirectory() as td:
            old = dict(self.old_receipt(td), status='resolved', reason='earlier')
        signals, _ = _hot_cache_signals(self.snap(), {'signals': [old]}, [_unbound('u1'), _unbound('u2')], {},
                                        {'u1': 'T1', 'u2': 'T2'})
        self.assertNotIn(self.U, [s['id'] for s in signals])


class SignalsHtmlTests(unittest.TestCase):
    def signal(self, **extra):
        return dict({'id': 'x:y', 'title': 'T', 'status': 'active', 'metric': 'C-hot-cache', 'baseline': None,
                     'current': 50.0, 'sample_size': 300000, 'next_action': 'Do it', 'window_start': 'a',
                     'window_end': 'b', 'evaluation': 'evaluated', 'reason': '', 'rule_version': 'hot-cache-v1'}, **extra)

    def render(self, signal):
        return signals_html({'signals': [signal], 'evaluations': [], 'status': 'evaluated',
                             'evaluated_at': '2026-09-20T10:00:00Z'}, [])

    def sessions(self, n):
        return [{'session_id': 'sess-%d' % i, 'share': 10.0 + i, 'tokens': 200_000 + i} for i in range(n)]

    def test_signal_without_sessions_renders_exactly_as_before(self):
        # Pinned from signals_html as it stood before the sessions list existed.
        expected = ("<li><b>T</b> · active: 50.0; n=300000. Do it "
                    "<a href='#C-hot-cache' data-open-tab='cost'>Evidence</a>"
                    "<details><summary>Window and evaluation</summary>a — b; evaluated; ; policy hot-cache-v1</details></li>")
        self.assertIn(expected, self.render(self.signal()))
        self.assertIn(expected, self.render(self.signal(sessions=[])))

    def test_ten_sessions_are_listed_without_a_more_line(self):
        page = self.render(self.signal(sessions=self.sessions(10)))
        self.assertEqual(page.count('<div>sess-'), 10)
        self.assertNotIn('more', page)
        self.assertIn('<div>sess-3 · 13.0% · 200,003 tokens</div>', page)

    def test_eleven_sessions_list_ten_and_count_the_rest(self):
        page = self.render(self.signal(sessions=self.sessions(11)))
        self.assertEqual(page.count('<div>sess-'), 10)
        self.assertIn('<div>+1 more</div>', page)
        self.assertNotIn('sess-10', page)
        # the list lives inside the signal's own details block
        details = page[page.index('<details>'):page.index('</details>')]
        self.assertIn('sess-0', details)


if __name__=='__main__':unittest.main()
