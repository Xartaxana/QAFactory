import json
import sys
from pathlib import Path
import tempfile
import unittest
from html.parser import HTMLParser
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dashboard_fixture import build
import factory_dashboard as D
from dashboard_cost_groups import group


class Rows(HTMLParser):
    def __init__(self):super().__init__();self.stack=[];self.groups=[];self.rows=[]
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag=='details':
            g={'class':a.get('class'),'open':'open' in a,'rows':[]}
            self.stack.append(g)
            if g['class'] in {'feat','taskd','lvl'}:self.groups.append(g)
        if tag=='tr' and 'data-case-id' in a:
            self.rows.append(a)
            for g in self.stack:g['rows'].append(a)
    def handle_endtag(self,tag):
        if tag=='details':self.stack.pop()


class RestoreTests(unittest.TestCase):
    def test_trends_break_at_missing_days_and_incompatible_scope(self):
        from metrics_projection import compute
        from dashboard_widgets import render
        import copy
        snapshot={'metrics':compute({}),'as_of':'2026-09-19T10:00:00Z'}
        metric=next(m for m in snapshot['metrics'] if m['id']=='F02')
        metric.update(value={'rate':20},status='available',sample_size=20)
        earlier=copy.deepcopy(snapshot);earlier['as_of']='2026-09-17T10:00:00Z'
        self.assertNotIn('<polyline',render(snapshot,'F',[earlier,snapshot]))
        earlier['as_of']='2026-09-18T10:00:00Z'
        self.assertIn('<polyline',render(snapshot,'F',[earlier,snapshot]))
        next(m for m in earlier['metrics'] if m['id']=='F02')['scope']='other-project'
        self.assertNotIn('<polyline',render(snapshot,'F',[earlier,snapshot]))

    def test_partial_cost_and_missing_ledger_are_not_green(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);build(root)
            path=next((root/'qa-factory/state/cost').glob('*.json'))
            doc=json.loads(path.read_text(encoding='utf-8'));doc['usage_completeness']='provisional';doc['reconciliation']['match']=None
            path.write_text(json.dumps(doc),encoding='utf-8')
            D.main(['--root',str(root)])
            page=(root/'qa-factory/state/factory-dashboard.html').read_text(encoding='utf-8')
            self.assertIn('not possible — see the cost-capture finding above',page)
            self.assertNotIn('sums reconcile',page)
            self.assertIn('Unavailable: factory-backlog.md is missing',page)

    def test_legacy_unclassified_usage_is_not_dropped(self):
        groups,_=group([{'by_model':{'old':{'input':100,'output':20}},'total_cost_usd':.5}])
        self.assertEqual(groups['Unclassified']['tokens'],120)
        self.assertEqual(groups['Unclassified']['cost'],.5)

    def test_all_sixty_named_cases_and_default_disclosure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);expected=build(root)
            D.main(['--root',str(root)])
            text=(root/'qa-factory/state/factory-dashboard.html').read_text(encoding='utf-8')
            parser=Rows();parser.feed(text)
            self.assertEqual(len(parser.rows),60)
            self.assertEqual(len({r['data-case-id'] for r in parser.rows}),60)
            # A check planned for a person reads `wait`, not `not_run`: the factory is not
            # waiting for it and nothing about it is broken (owner's decision on TC-015).
            statuses={s:sum(r['data-result']==s for r in parser.rows) for s in ('passed','failed','blocked','not_run','wait')}
            self.assertEqual(statuses,{'passed':50,'failed':2,'blocked':2,'not_run':2,'wait':4})
            for g in parser.groups:
                if g['rows']:self.assertEqual(g['open'],any(r['data-result'] not in {'pass','passed'} for r in g['rows']),g)
            for case in expected:self.assertIn(case['title'],text)
            for mid in [f'{p}{i:02}' for p,n in [('T',14),('A',10),('F',8),('C',15)] for i in range(1,n+1)]:self.assertIn("id='"+mid+"'",text)
            self.assertLess(text.index('Metric warnings'),text.index("class='tabs'"))
            self.assertIn('Test pyramid',text);self.assertIn('Next actions',text)
            self.assertIn('Remaining checks',text)
            self.assertIn('Doctor',text);self.assertIn('Onboarding',text)
            sessions=[json.loads(p.read_text(encoding='utf-8')) for p in (root/'qa-factory/state/cost').glob('*.json')]
            tasks,days=group(sessions)
            self.assertEqual(len(tasks),6)
            self.assertEqual(sum(v['tokens'] for v in tasks.values()),2490000)
            self.assertAlmostEqual(sum(v['cost'] for v in tasks.values()),16.36)
            self.assertEqual(tasks['DEMO-15045']['sessions'],2)


if __name__=='__main__':unittest.main()
