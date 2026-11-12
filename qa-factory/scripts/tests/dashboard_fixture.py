"""Isolated synthetic project for the real renderer; never imported by production."""
import json
from pathlib import Path
from datetime import datetime, timezone
from decimal import Decimal
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from event_store import atomic_json
from cost_capture import zero


def build(root):
    root=Path(root); qf=root/'qa-factory'; qf.mkdir(parents=True,exist_ok=True)
    cases=json.loads((Path(__file__).parent/'fixtures/dashboard-0.7.json').read_text(encoding='utf-8'))['cases']
    today=datetime.now(timezone.utc).replace(hour=10,minute=0,second=0,microsecond=0)
    cfg={'schema_version':1,'metrics':{'signal_policy':{'version':'demo-only-v1','rules':[{
        'id':'reject-rate','metric':'F02','field':'rate','direction':'above','threshold':15,'recovery_threshold':5,
        'min_sample':10,'recovery_samples':2,'mode':'absolute','title':'DEMO: factory reject rate needs review',
        'next_action':'Inspect rejected handoffs by role and reason'}]}}}
    atomic_json(qf/'config.json',cfg)
    obligations=[]
    for task in sorted({r['task'] for r in cases}):
        directory=qf/'artifacts'/task
        selected=[r for r in cases if r['task']==task]
        report={'current_results':[],'current_manual_checks':[]}
        manual=[];manifest=[]
        for r in selected:
            if r['mock_id'].split('-')[-1].startswith('F'):r['channel']='manual-agent'
            path=directory/'work/test-cases'/(r['id']+'.md');path.parent.mkdir(parents=True,exist_ok=True)
            path.write_text('---\nid: '+r['id']+'\ntitle: '+r['title']+'\nchannel: '+r['channel']+'\nowner: QA lead\n---\n# '+r['title']+'\n',encoding='utf-8')
            if r['channel']=='manual-human':
                obligations.append(f"| O-{r['id']} | {r['title']} | {task} | Human checks | {r['reason']} | {today.date()} | {path} | open |")
            elif r['channel']=='manual-agent':
                report['current_manual_checks'].append({'case':r['id'],'check':r['title'],'result':r['status'],'result_note':r['reason']})
                manual.append({'case':r['id'],'result':r['status'],'evidence_validated':True,'evidence_refs':[]})
            else:
                report['current_results'].append({'case':r['id'],'test_id':'demo::'+r['id'],'instance_id':r['id'],
                    'status':r['status'],'level':r['level'],'reason':r['reason'],'execution_scope':'feature'})
                manifest.append({'case':r['id'],'test_id':'demo::'+r['id'],'instance_id':r['id'],'level':r['level']})
        atomic_json(directory/'work/run-report.json',report)
        atomic_json(directory/'work/automation-manifest.json',{'tests':manifest,'unresolved':[]})
        atomic_json(directory/'work/ledger.json',{'manual_evidence':{'rows':manual}})
        atomic_json(directory/'pipeline.json',{'parent_feature':'DEMO-PROJECT' if task!='DEMO-15047' else 'DEMO-ROLES','stages':{}})
    (qf/'obligations.md').write_text('| id | essence | task | type | trigger | created | details | status |\n|---|---|---|---|---|---|---|---|\n'+'\n'.join(obligations),encoding='utf-8')
    journal=[{'event_id':f'demo-event-{i}','ts':today.isoformat(),'event':'reject' if i<4 else 'accepted',
              'role':'qa-automator' if i%2 else 'qa-case-designer','reason':'Missing evidence' if i<4 else 'Accepted output'} for i in range(20)]
    (qf/'state').mkdir(exist_ok=True)
    (qf/'records').mkdir(exist_ok=True)
    (qf/'records/journal.jsonl').write_text(''.join(json.dumps(x)+'\n' for x in journal),encoding='utf-8')
    entries=[('story','DEMO-15045',860000,'7.20',2),('story','DEMO-15046',520000,'3.10',1),
             ('story','DEMO-15047',690000,'4.80',2),('doctor',None,60000,'.18',1),('onboarding',None,320000,'.96',1),('unclassified',None,40000,'.12',1)]
    for kind,task,tokens,cost,n in entries:
        for i in range(n):
            sid=(task or kind)+'-'+str(i);aid='activity-'+sid; amount=float(Decimal(cost)/n);count=tokens//n
            usage=dict(zero(),requests=1,input=count*7//10,output=count//10,cache_read=count*2//10)
            valuation={'pricing_coverage':'complete','subtotal_usd':str(amount),'missing_rate_categories':[],'provenance':{'kind':'synthetic_fixture'}}
            model=dict(usage,cost=amount,valuation=valuation)
            request={'request_key':'demo:'+sid,'model_id':'DEMO synthetic tariff','stream':'orchestrator','task':task or '(no task)',
                     'activity_id':aid,'activity_segment_id':aid,'timestamp':today.isoformat(),'usage':usage,'valuation':valuation}
            session={'session_id':sid,'requests':[request],'by_model':{'DEMO synthetic tariff':model},
                     'orchestrator':{'by_model':{'DEMO synthetic tariff':model},'cost':amount},
                     'by_task':{task or '(no task)':{'tokens':count,'cost':amount}},
                     'by_activity':{aid:{'type':kind,'task':task,'tokens':count,'cost':amount}},
                     'usage_completeness':'complete','usage_status':'actual','pricing_coverage':'complete','tariff_confirmation':'confirmed',
                     'priced_subtotal_usd':amount,'total_cost_usd':amount,'started':today.isoformat(),'ended':today.isoformat(),
                     'reconciliation':{'match':True},'tools':{'exec_command':12,'apply_patch':3}}
            atomic_json(qf/'state/cost'/(sid+'.json'),session)
    return cases


if __name__=='__main__':
    build(sys.argv[1])
    from factory_dashboard import main
    main(['--root',sys.argv[1]])
