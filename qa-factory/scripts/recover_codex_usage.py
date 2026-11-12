"""Import a Codex rollout with explicitly reviewed tool-call boundary evidence."""
import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from codex_usage import metadata, scan
from activity_capture import update
from event_store import atomic_json


def recover(root, transcript, boundaries, write=False):
    root, transcript = Path(root).resolve(), Path(transcript).resolve()
    meta=metadata(transcript);session=meta.get('id')
    if not session or any(c in session for c in '/\\:'):raise ValueError('Unsupported session identity')
    usage,*_,adapter=scan(transcript)
    facts={}
    with transcript.open(encoding='utf-8') as stream:
        for line in stream:
            try:row=json.loads(line)
            except ValueError:continue
            payload=row.get('payload') or {}
            if row.get('type')=='response_item' and payload.get('type') in {'function_call','custom_tool_call'}:
                facts[payload.get('call_id')]={'timestamp':row.get('timestamp'),'text':str(payload.get('input') or payload.get('arguments') or '')}
    checked=[]
    for boundary in boundaries:
        fact=facts.get(boundary.get('call_id'))
        kind,action=boundary.get('type'),boundary.get('action')
        if not fact or fact['timestamp']!=boundary.get('timestamp'):
            raise ValueError('Boundary has no matching source tool-call identity/timestamp')
        if kind not in {'doctor','onboarding','story'} or action not in {'start','end'}:
            raise ValueError('Unsupported activity boundary')
        import re
        if not re.search(r'activity_capture\.py[\'\"]?\s+--action\s+'+action+r'\s+--type\s+'+kind+r'\b',fact['text']):
            raise ValueError('Source call does not declare this activity boundary')
        task=boundary.get('task') or ''
        if kind=='story' and (not task or not re.search(r'--task\s+'+re.escape(task)+r'\b',fact['text'])):
            raise ValueError('Story boundary lacks an explicit source task')
        checked.append(boundary)
    checked.sort(key=lambda b:b['timestamp'])
    source={'method':'reviewed_explicit_tool_call_boundaries','transcript_sha256':hashlib.sha256(transcript.read_bytes()).hexdigest(),
            'boundaries_sha256':hashlib.sha256(json.dumps(checked,sort_keys=True).encode()).hexdigest(),
            'confidence':'recorded command intent; original activity receipts missing; gaps remain unclassified'}
    result={'session_id':session,'request_count':len(usage),'adapter':adapter,'recovery':source,
            'boundaries':checked,'write':write}
    if not write:return result
    if not (root/'qa-factory/config.json').is_file():raise ValueError('Project configuration required')
    path=root/'qa-factory/state/activities'/(session+'.json')
    if path.exists():
        old=json.loads(path.read_text(encoding='utf-8'))
        if old.get('recovery')!=source:raise ValueError('Existing activity evidence differs; do not overwrite it')
    else:
        stack=[];ignored=[]
        for row in checked:
            identity=(row['type'],row.get('task') or '')
            if row['action']=='start' and stack and stack[-1]==identity:
                ignored.append(dict(row,reason='duplicate start of active workflow'));continue
            if row['action']=='end' and (not stack or stack[-1]!=identity):
                ignored.append(dict(row,reason='unmatched end; attribution not extended'));continue
            update(path,session,row['action'],row['type'],row.get('task') or '',
                   event_id='recovered:'+row['call_id'],timestamp=row['timestamp'],
                   evidence_ref=str(transcript)+'#'+row['call_id'])
            if row['action']=='start':stack.append(identity)
            else:stack.pop()
        doc=json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'schema_version':1,'session_id':session,'activities':[],'active_stack':[],'processed_events':{}}
        doc['recovery']=source;doc['ignored_boundaries']=ignored
        atomic_json(path,doc)
    event={'host':'codex','cwd':str(root),'session_id':session,'transcript_path':str(transcript),'hook_event_name':'HistoricalImport'}
    run=subprocess.run([sys.executable,str(Path(__file__).parent/'cost_capture.py')],input=json.dumps(event),text=True,encoding='utf-8',capture_output=True,cwd=root)
    cost=root/'qa-factory/state/cost'/(session+'.json')
    if run.returncode or run.stderr.strip() or not cost.exists():raise RuntimeError('Historical capture failed: '+run.stderr)
    captured=json.loads(cost.read_text(encoding='utf-8'))
    if (captured.get('attribution_provenance') or {}).get('recovery')!=source:
        raise RuntimeError('Historical capture did not preserve the reviewed recovery evidence')
    result['cost_file']=str(cost)
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',required=True);parser.add_argument('--transcript',required=True)
    parser.add_argument('--boundaries',required=True,help='Reviewed JSON list: call_id, timestamp, action, type, optional task')
    parser.add_argument('--write',action='store_true')
    args=parser.parse_args()
    print(json.dumps(recover(args.root,args.transcript,json.loads(Path(args.boundaries).read_text(encoding='utf-8')),args.write),indent=2))
