import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import case_lifecycle as L
from event_store import content_hash

def action(kind='retire', disposition='removed'):
 return {'action_id':'LC-1','kind':kind,'reason':'approved removal','case_refs':[{'case_id':'TC-1','version':'cv_1'}], 'authoritative_change_refs':['R-1'], 'coverage_before':['O-1'],'coverage_after':['O-1'],'test_refs':[{'path':'t.py','sha256':'h'}],'replacement_refs':(['TC-2'] if kind=='migrate' else []),'shared_dependents':[{'disposition':'preserved','evidence_ref':'dep'}],'proposed_code_changes':[{'path':'t.py','change':'delete'}],'requirement_disposition':disposition,'proposed_tms_action':'archive','external_id':'EXT-1','case_file':'cases/TC-1.md'}
def decision(a): return {'id':'B-1','status':'approved','gate':'B','action':'case_lifecycle','content_hash':content_hash([a]),'source_revision':'src','authorization_source':'owner','destination':'tms','channel':'xray'}
def main():
 a=action(); assert not L.validate_actions([a]); assert L.validate_actions([action('retire','still_required')]); assert L.validate_actions([action() | {'proposed_code_changes':[]}]); assert L.validate_actions([action('migrate') | {'replacement_refs':[]}]); assert L.authorize([a],decision(a),'B','src')==[]
 assert L.authorize([a],dict(decision(a),content_hash='bad'),'B','src')
 assert L.prepare_archive(a,decision(a),'src',{'archive':False},'r')['status']=='pending'
 p=L.prepare_archive(a,decision(a),'src',{'archive':True,'conditional_updates':True},'r')['proposal']; assert p['expected_remote_revision']=='r' and p['lifecycle_key']
 print('=== test_case_lifecycle: 8/8 ok ===')
if __name__=='__main__': main()
