"""Cost tab: By activity removal, non-factory sessions and incomplete-agent marker, Token composition card, and the Deferred-decisions empty-state class."""
import sys
import tempfile
from pathlib import Path
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import factory_dashboard as D


def _request_session(sid, task, cost, input_=1000, cache_read=0, cache_write_5m=0, cache_write_1h=0,
                      output=0, has_factory_activity=None, incomplete_agents=None):
    usage = {'input': input_, 'output': output, 'cache_read': cache_read,
             'cache_write_5m': cache_write_5m, 'cache_write_1h': cache_write_1h}
    row = {'request_key': sid + ':r', 'task': task, 'activity_id': 'a', 'timestamp': '2026-09-20T00:00:00Z',
           'usage': usage, 'valuation': {'pricing_coverage': 'complete', 'subtotal_usd': str(cost)}}
    s = {'session_id': sid, 'usage_completeness': 'complete', 'requests': [row],
         'by_model': {'m': dict(usage, cost=cost)}, 'by_activity': {'a': {'type': 'story', 'task': task}},
         'priced_subtotal_usd': cost, 'total_cost_usd': cost, 'pricing_coverage': 'complete',
         'reconciliation': {'match': True}}
    if has_factory_activity is not None:
        s['has_factory_activity'] = has_factory_activity
    if incomplete_agents is not None:
        s['incomplete_agents'] = incomplete_agents
    return s


class ByActivityRemovedTests(unittest.TestCase):
    def test_by_activity_section_is_gone_by_task_remains_the_source_of_truth(self):
        s = _request_session('sess-1', 'TP1-1', cost=5)
        html = D.tab_cost([s], {})
        self.assertNotIn('By activity', html)
        self.assertIn('By task', html)
        self.assertIn('TP1-1', html)


class NonFactorySessionsTests(unittest.TestCase):
    def test_session_of_another_directory_is_shown_apart_and_never_summed(self):
        # On TP1-15045 eight sessions captured here belonged to directories above the
        # project; summing them made a $258 story read as $2,873.
        factory = _request_session('f1', 'TP1-1', cost=5, has_factory_activity=True)
        nonfactory = _request_session('nf1', '(no task)', cost=3, has_factory_activity=False)
        html = D.tab_cost([factory, nonfactory], {})
        self.assertIn('Sessions of parent directories', html)
        self.assertIn('$5.00', html)   # All stories and activities, and the check sum
        self.assertNotIn('$8.00', html)

    def test_legacy_session_without_the_field_still_counts_as_factory(self):
        legacy = _request_session('leg1', 'TP1-1', cost=5)  # no has_factory_activity key
        html = D.tab_cost([legacy], {})
        self.assertNotIn('Sessions of parent directories', html)
        self.assertIn('$5.00', html)


class IncompleteAgentsMarkerTests(unittest.TestCase):
    def test_incomplete_agents_marks_the_task_cell_never_a_silent_sum(self):
        s = _request_session('s1', 'TP1-2', cost=5, incomplete_agents=['qa-factory:qa-case-designer'])
        html = D.tab_cost([s], {})
        self.assertIn('incomplete', html)
        self.assertIn('qa-factory:qa-case-designer', html)


class TokenCompositionCardTests(unittest.TestCase):
    def test_card_is_one_third_width_with_hot_cache_headline_and_legend_no_cost_comparison(self):
        s = _request_session('s1', 'TP1-3', cost=5, input_=10_000, cache_read=90_000)
        html = D.tab_cost([s], {})
        self.assertIn('Token composition', html)
        self.assertIn("style='max-width:33%'", html)
        self.assertIn('Hot cache share: 90.0%', html)
        self.assertIn('cache read', html)  # legend entry present
        self.assertNotIn('without cache', html)
        self.assertNotIn('would have cost', html)


def _agent_session(sid, task, agent, cost, has_factory_activity=None):
    """A session shaped like the real defect: a story session whose agents[] carries a
    non-factory subagent (general-purpose/Explore), and a session with no story evidence at
    all, playing the analysis-session role. Two request rows, distinguished by `stream` —
    orchestrator (free) and the one agent dispatch (carries the whole `cost`) — the same
    shape cost_capture.py itself writes, so dashboard_cost_groups.by_agent's per-request
    grouping resolves the agent's own label via `agents[].file`."""
    agent_file = 'agent-' + sid + '.jsonl'
    usage_small = {'input': 100, 'output': 10, 'cache_read': 0, 'cache_write_5m': 0, 'cache_write_1h': 0}
    usage_agent = {'input': 1000, 'output': 100, 'cache_read': 0, 'cache_write_5m': 0, 'cache_write_1h': 0}
    orch_row = {'request_key': sid + ':orch', 'task': task, 'activity_id': 'a', 'stream': 'orchestrator',
                'timestamp': '2026-09-20T00:00:00Z', 'usage': usage_small,
                'valuation': {'pricing_coverage': 'complete', 'subtotal_usd': '0'}}
    agent_row = {'request_key': sid + ':agent', 'task': task, 'activity_id': 'a', 'stream': agent_file,
                 'timestamp': '2026-09-20T00:00:01Z', 'usage': usage_agent,
                 'valuation': {'pricing_coverage': 'complete', 'subtotal_usd': str(cost)}}
    s = {'session_id': sid, 'usage_completeness': 'complete', 'requests': [orch_row, agent_row],
         'by_model': {'m': dict(usage_small, requests=1, cost=0)},
         'by_activity': {'a': {'type': 'story' if has_factory_activity is not False else 'unclassified', 'task': task}},
         'orchestrator': {'by_model': {'m': dict(usage_small, requests=1, cost=0)}, 'cost': 0},
         'agents': [{'agent': agent, 'file': agent_file, 'task': task, 'tokens': 1100, 'cost': cost,
                     'by_model': {'m': dict(usage_agent, requests=1, cost=cost)}}],
         'priced_subtotal_usd': cost, 'total_cost_usd': cost, 'pricing_coverage': 'complete',
         'reconciliation': {'match': True}}
    if has_factory_activity is not None:
        s['has_factory_activity'] = has_factory_activity
    return s


class ByAgentFactoryOnlyTests(unittest.TestCase):
    def test_nonfactory_session_agents_never_appear_in_by_agent(self):
        # The 2090c31a shape: an unrelated analysis session (general-purpose/Explore
        # subagents), no story/doctor/onboarding activity ever opened.
        analysis = _agent_session('an1', '(no task)', 'general-purpose', 276, has_factory_activity=False)
        story = _agent_session('f1', 'TP1-1', 'qa-factory:qa-scout', 5, has_factory_activity=True)
        html = D.tab_cost([story, analysis], {})
        self.assertNotIn('general-purpose', html)
        self.assertIn('qa-factory:qa-scout', html)
        self.assertIn('Sessions of parent directories', html)

    def test_legacy_session_with_no_activity_evidence_is_nonfactory_not_unclassified(self):
        # an old-format file (no has_factory_activity field) whose by_activity
        # shows no doctor/onboarding/story type at all must not default to "factory" just
        # because the field is missing — it used to render as "Unclassified" in By task.
        legacy_no_evidence = {'session_id': 'leg-old', 'usage_completeness': 'complete',
            'requests': [{'request_key': 'leg-old:r', 'task': None, 'activity_id': 'u',
                          'timestamp': '2026-09-20T00:00:00Z',
                          'usage': {'input': 500, 'output': 0, 'cache_read': 0, 'cache_write_5m': 0, 'cache_write_1h': 0},
                          'valuation': {'pricing_coverage': 'complete', 'subtotal_usd': '9.0'}}],
            'by_model': {'m': {'input': 500, 'output': 0, 'cache_read': 0, 'cache_write_5m': 0,
                               'cache_write_1h': 0, 'cost': 9.0}},
            'by_activity': {'u': {'type': 'unclassified'}},
            'priced_subtotal_usd': 9.0, 'total_cost_usd': 9.0, 'pricing_coverage': 'complete',
            'reconciliation': {'match': True}}
        html = D.tab_cost([legacy_no_evidence], {})
        self.assertNotIn('Unclassified', html)
        self.assertIn('Sessions of parent directories', html)

    def test_by_agent_total_matches_by_task_total(self):
        s1 = _agent_session('f1', 'TP1-1', 'qa-factory:qa-scout', 5, has_factory_activity=True)
        s2 = _agent_session('f2', 'TP1-2', 'qa-factory:qa-runner', 7, has_factory_activity=True)
        nonfactory = _agent_session('nf1', '(no task)', 'general-purpose', 100, has_factory_activity=False)
        html = D.tab_cost([s1, s2, nonfactory], {})
        by_task_section = html.split("By task</h2>")[1].split("</section>")[0]
        by_agent_section = html.split("By agent</h2>")[1].split("</section>")[0]
        self.assertIn('$12.00', by_task_section)   # All stories and activities (factory-only)
        self.assertIn('$12.00', by_agent_section)  # Sum of orchestrator + agents (factory-only)
        self.assertNotIn('general-purpose', by_agent_section)
        self.assertIn('Sessions of parent directories', html)


class StaleCostFileMarkerTests(unittest.TestCase):
    def test_not_recomputed_session_is_flagged_in_an_alert(self):
        s = _request_session('s1', 'TP1-9', cost=5, has_factory_activity=True)
        s['recapture_status'] = {'status': 'not_recomputed', 'reason': 'transcript file no longer present'}
        html = D.tab_cost([s], {})
        self.assertIn('Stale cost files', html)
        self.assertIn('s1', html)


class DeferredEmptyStateClassTests(unittest.TestCase):
    def test_empty_deferred_and_findings_sections_both_carry_their_class(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            html = D.tab_factory(root, {}, [], [], [], False)
            self.assertIn("<section class='deferred'>", html)
            self.assertIn("<section class='findings'>", html)


if __name__ == '__main__':
    unittest.main()
