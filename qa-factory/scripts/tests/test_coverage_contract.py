import hashlib, json, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import acceptance
import coverage_contract as C
import proof_level
import window_record as WR
from event_store import content_hash

def observed_obligation(oid='O-1', kinds=None):
 ob=obligation(oid); ob['planned_check_refs']=['before','action','complete','after','positive','left','right']
 kinds=kinds or ['ordinary']
 ob['observation_contract']={'claim_kind':kinds,'oracle_ref':{'ref':'R-1','revision':'r'},
  'surfaces':[{'id':'response','boundary':'api payload','assertion_ref':'after','status':'planned'}],
  'controls':['after'],'completion_ref':'complete','independent_expectations':[],
  'source_conflicts':[]}
 if set(kinds)&{'state_unchanged','no_write_attempt'}:
  ob['observation_contract'].update(sequence=[{'phase':'before_read','ref':'before'},
   {'phase':'action','ref':'action'},{'phase':'completion','ref':'complete'},
   {'phase':'after_read','ref':'after'}],positive_control_ref='positive',
   reachability_assertion_ref='action')
 return ob

def obligation(oid='O-1', decision='reuse', scope='current_task'):
 return {'obligation_id':oid,'behavior':'b','observation_boundary':'api','completion_condition':'done','requirement_refs':[{'ref':'R-1','revision':'r'}],'applicable_scenarios':['positive'],'oracle_status':'resolved','oracle_source_ref':'spec','decision':decision,'execution_scope':scope,'sufficiency_review':{'author_dispatch_id':'d','input_hash':'h','rationale':'r'},'coverage_links':[{'candidate_id':'c','assessment':'sufficient','assessment_reason':'r','assertion_refs':['a'],'proves':['b'],'does_not_prove':[]}], 'planned_check_refs':['x']}
class Tests(unittest.TestCase):
 def test_validation_semantics(self):
  row={'id':'TS-1','schema_version':2,'coverage_obligations':[obligation()]}; self.assertFalse(C.validate_obligations([row],True)); self.assertTrue(C.validate_obligations([dict(row,coverage_obligations=[obligation(),obligation()])],True))
  bad=obligation(); bad['oracle_status']='unresolved'; self.assertTrue(C.validate_obligations([dict(row,coverage_obligations=[bad])],True)); bad=obligation(); bad['coverage_links']=[]; self.assertTrue(C.validate_obligations([dict(row,coverage_obligations=[bad])],True))
 def test_version_refusal_names_the_key_and_its_value(self):
  # TR2-8 (B-9, FR-1): a row that is not on schema version 2 is refused naming the KEY and the value; a look-alike key is named as not the key
  ob=[obligation()]; tail='the row key is exactly `schema_version`, written as the number 2'
  absent=C.validate_obligations([{'id':'TS-1','coverage_obligations':ob}],True)
  self.assertTrue(absent and absent[0].startswith('TS-1: coverage schema version 2 required') and tail in absent[0],'key absent: refused, key named: '+repr(absent))
  self.assertFalse(C.validate_obligations([{'id':'TS-1','coverage_obligations':ob}]),'key absent, v2 not required: the legacy row passes as it always did')
  text=C.validate_obligations([{'id':'TS-1','schema_version':'2','coverage_obligations':ob}],True)
  self.assertTrue(text and tail in text[0],'the value as the string "2": refused, number named: '+repr(text))
  wrong=C.validate_obligations([{'id':'TS-1','schema_version':3,'coverage_obligations':ob}],True)
  self.assertTrue(wrong and tail in wrong[0],'a wrong number: refused, key named: '+repr(wrong))
  alike=C.validate_obligations([{'id':'TS-2','coverage_schema_version':2,'coverage_obligations':ob}],True)
  self.assertTrue(alike and 'schema_version' in alike[0] and '`coverage_schema_version`, which is not the key' in alike[0],'a look-alike key: named as not the key: '+repr(alike))
  self.assertFalse(C.validate_obligations([{'id':'TS-1','schema_version':2,'coverage_obligations':ob}],True),'control: the right key and value pass')
 def _policy_errors(self, decision, policy, absent=False):
  ob=obligation(decision=decision)
  if absent: ob.pop('evidence_policy',None)
  else: ob['evidence_policy']=policy
  return C.validate_obligations([{'id':'TS-1','schema_version':2,'coverage_obligations':[ob]}],True)
 def test_manual_agent_policy_must_be_word(self):
  # F5(a): ONE word of the five, stripped, not case-folded; the arm B record, a list, a number, blank, absent and an unknown word are refused
  for good in ('ui','api','cli','no_write','static',' ui '): self.assertEqual(self._policy_errors('manual-agent',good),[],good)
  for bad in ({'executed_by':'agent','evidence':'screenshots'},['ui'],3,None,'','  ','UI','video'):
   errors=self._policy_errors('manual-agent',bad); self.assertEqual(len(errors),1,bad); self.assertTrue(errors[0].startswith('O-1: '),errors)
   self.assertIn('api|cli|no_write|static|ui',errors[0]); self.assertIn('completion_condition',errors[0])
  self.assertEqual(len(self._policy_errors('manual-agent',None,absent=True)),1)
  self.assertEqual(self._policy_errors('reuse',{'any':'thing'}),[])        # only a manual-agent obligation has the rule
 def test_manual_human_policy_must_be_string(self):
  # C5: any non-empty text; no membership
  self.assertEqual(self._policy_errors('manual-human','a person looks at it'),[])
  for bad in ({'k':'v'},['ui'],5): self.assertEqual(len(self._policy_errors('manual-human',bad)),1,bad)
  for bad in ('  ',''): self.assertIn('evidence_policy required before Gate A',self._policy_errors('manual-human',bad)[0])
 def test_policy_shape_error_constant_in_message(self):
  # F5(c) item 1 reads the fixed part: one producer, every shape error of a manual-agent obligation carries it, no other error does
  errors=self._policy_errors('manual-agent',{'a':1}); self.assertTrue(all(C.POLICY_SHAPE_ERROR in e for e in errors))
  bad=obligation(); bad['oracle_status']='maybe'
  other=C.validate_obligations([{'id':'TS-1','schema_version':2,'coverage_obligations':[bad]}],True)
  self.assertTrue(other); self.assertFalse(any(C.POLICY_SHAPE_ERROR in e for e in other))
 def test_every_message_names_the_field_and_what_it_expects(self):
  # F-cmp2-14 (FR-1): a role without Bash reads these through a hook; each message carries the field
  # name and the expected value in one sentence, after the `{oid}: ` prefix.
  def errors_of(mutate):
   ob=obligation(); mutate(ob); return C.validate_obligations([{'id':'TS-1','schema_version':2,'coverage_obligations':[ob]}],True)
  def link(ob,**kw):
   ob['coverage_links'][0].update(kw)
  def drop(ob,key):
   ob['coverage_links'][0].pop(key,None)
  cases=[
   ('sufficiency_review required: {author_dispatch_id, input_hash, rationale}, all non-empty', lambda o:o.pop('sufficiency_review')),
   ('sufficiency_review required: {author_dispatch_id, input_hash, rationale}, all non-empty', lambda o:o.update(sufficiency_review={'author_dispatch_id':'d','input_hash':'','rationale':'r'})),
   ('coverage_links[0] needs candidate_id (CAND-n) or test_ref (a test node id)', lambda o:(drop(o,'candidate_id'),drop(o,'test_ref'))),
   ('coverage_links[0] needs assessment: one of sufficient | partial | none | unknown, and assessment_reason', lambda o:link(o,assessment='maybe')),
   ('coverage_links[0] needs assessment: one of sufficient | partial | none | unknown, and assessment_reason', lambda o:drop(o,'assessment_reason')),
   ('coverage_links[0] needs does_not_prove: a list', lambda o:drop(o,'does_not_prove')),
   ('coverage_links[0] with assessment sufficient needs assertion_refs and proves', lambda o:drop(o,'proves')),
   ('coverage_links[0].assertion_refs needs test assertion ids, not production code references', lambda o:link(o,assertion_refs=['production:src/router.py:9'])),
   ('coverage_links[0].candidate_kind: one of test | suite | helper', lambda o:link(o,candidate_kind='mock')),
   ('coverage_links[0] needs an object {candidate_id or test_ref, assessment, assessment_reason, does_not_prove}', lambda o:o.update(coverage_links=['x'])),
   ('oracle_status: not filled. One of: resolved | unresolved', lambda o:o.update(oracle_status='maybe')),
   ('oracle_source_ref needs the independent source', lambda o:o.pop('oracle_source_ref')),
   ('decision: not filled. One of: reuse | extend | new | manual-agent | manual-human | unresolved', lambda o:o.update(decision='skip')),
   ('execution_scope: not filled. One of: current_task | recommended_regression', lambda o:o.update(execution_scope='')),
   ('decision needs unresolved while oracle_status is unresolved', lambda o:o.update(oracle_status='unresolved')),
   ('coverage_links needs a list of links', lambda o:o.pop('coverage_links')),
   ('coverage_links needs at least one link when decision is reuse', lambda o:o.update(coverage_links=[])),
   ('planned_check_refs needs at least one check id when decision is extend | new | manual-agent | manual-human', lambda o:(o.update(decision='new',planned_check_refs=[]))),
   ('missing behavior: behavior needs a non-empty sentence', lambda o:o.pop('behavior')),
   ('requirement_refs needs a non-empty list of {ref, revision} objects', lambda o:o.update(requirement_refs=[])),
   ('applicable_scenarios needs a non-empty list of scenario ids', lambda o:o.update(applicable_scenarios=[])),
   ('requirement_refs[1] needs {ref, revision}, both non-empty', lambda o:o.update(requirement_refs=[{'ref':'R-1','revision':'r'},{'ref':'R-2'}])),
  ]
  for expected,mutate in cases:
   found=errors_of(mutate)
   self.assertTrue(any(e.startswith('O-1: ') and expected in e for e in found),(expected,found))
  # the link index is the position in the list, not always 0
  two=obligation(); two['coverage_links'].append(dict(two['coverage_links'][0],candidate_id='',test_ref=''))
  self.assertTrue(any('coverage_links[1] needs candidate_id (CAND-n) or test_ref' in e for e in C.validate_obligations([{'id':'TS-1','schema_version':2,'coverage_obligations':[two]}],True)))
  # a valid obligation says nothing
  self.assertFalse(errors_of(lambda o:None))
 def test_projection_never_infers_verified(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td); (root/'work').mkdir(); ob=obligation(); row={'id':'TS-1','schema_version':2,'coverage_obligations':[ob]}; (root/'work/test-plan.json').write_text(json.dumps({'rows':[row]})); bind={'obligation_id':'O-1','obligation_hash':content_hash(ob),'instance_ids':['i'],'design_assessment':'sufficient','code_validity':'valid','sensitivity':'not_required','change_disposition':'unchanged','change_basis_ref':'x','assertion_refs':['a'],'quality_not_applicable_reason':'x','review_receipt_ref':'fake'}; p=C.coverage_projection(root,{'current_results':[{'instance_id':'i','status':'passed'}]},{'obligation_bindings':[bind]}); self.assertFalse(p['obligations'][0]['verified'])
   ob2=obligation('O-2',scope='recommended_regression'); row['coverage_obligations']=[ob,ob2]; (root/'work/test-plan.json').write_text(json.dumps({'rows':[row]})); p=C.coverage_projection(root,{'current_results':[{'instance_id':'i','status':'passed'}]},{'obligation_bindings':[bind]}); self.assertEqual(p['unique_instances'],1); self.assertFalse(p['obligations'][1]['verified'])
 def test_rejects_production_assertion_and_nonexecutable_candidate(self):
  row={'id':'TS-1','schema_version':2,'coverage_obligations':[obligation()]}
  production=obligation(); production['coverage_links'][0]['assertion_refs']=['production:src/router.py:9']
  self.assertTrue(C.validate_obligations([dict(row,coverage_obligations=[production])],True))
  helper=obligation(); helper['coverage_links'][0]['candidate_kind']='helper'
  self.assertTrue(C.validate_obligations([dict(row,coverage_obligations=[helper])],True))
  suite=obligation(); suite['coverage_links'][0].update({'candidate_kind':'suite'})
  self.assertTrue(C.validate_obligations([dict(row,coverage_obligations=[suite])],True))
 def test_explicit_incomplete_part_blocks_verified_projection(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td); (root/'work').mkdir(); ob=obligation(); ob['parts']=[{'part_id':'color-green','status':'sufficient'},{'part_id':'color-amber','status':'unresolved'}]
   (root/'work/test-plan.json').write_text(json.dumps({'rows':[{'id':'TS-1','schema_version':2,'coverage_obligations':[ob]}]}))
   p=C.coverage_projection(root,{'current_results':[]},{'obligation_bindings':[]})
   self.assertFalse(p['obligations'][0]['verified']); self.assertIn('compound obligation',p['obligations'][0]['gap'])
 def test_reused_candidate_join_requires_structurally_valid_same_assertion(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td); (root/'work').mkdir(); ob=obligation(); ob['coverage_links'][0]['candidate_id']='existing-c'; ob['coverage_links'][0]['candidate_origin']='existing'
   ob['coverage_links'][0]['assertion_refs']=['tests/test_a.py:8']
   bundle={'existing_test_candidates':[{'candidate_id':'existing-c','candidate_evidence':{'executable':True,'assertion_status':'sufficient','assertion_refs':['tests/test_a.py:8']}}]}
   (root/'work/context-bundle.json').write_text(json.dumps(bundle))
   self.assertTrue(C._reused_candidate_join(root,ob,{'assertion_refs':['tests/test_a.py:8']})[0])
   self.assertFalse(C._reused_candidate_join(root,ob,{'assertion_refs':['src/a.py:8']})[0])
   ob['parts']=[{'part_id':'color','status':'sufficient','covered_by':['tests/test_a.py:8']}]
   self.assertTrue(C._parts_complete(ob)); ob['parts'][0]['covered_by']=['invented']
   self.assertFalse(C._parts_complete(ob))
 def test_observation_contract_is_revision_gated_and_orders_no_write(self):
  legacy={'id':'TS-1','schema_version':2,'coverage_obligations':[obligation()]}
  self.assertFalse(C.validate_obligations([legacy],True))
  revised=dict(legacy,coverage_contract_revision=C.COVERAGE_CONTRACT_REVISION)
  self.assertTrue(any('observation_contract required' in e for e in C.validate_obligations([revised],True)))
  ob=observed_obligation(kinds=['state_unchanged','no_write_attempt']); revised['coverage_obligations']=[ob]
  self.assertFalse(C.validate_obligations([revised],True))
  ob['observation_contract']['sequence'][2]['phase']='after_read'
  self.assertTrue(any('no-write sequence' in e for e in C.validate_obligations([revised],True)))
 def test_parity_needs_partition_specific_oracles_and_gap_cannot_be_full(self):
  ob=observed_obligation(kinds=['response_parity'])
  row={'id':'TS-1','schema_version':2,'coverage_contract_revision':C.COVERAGE_CONTRACT_REVISION,
       'coverage_obligations':[ob]}
  self.assertTrue(any('independent expectations' in e for e in C.validate_obligations([row],True)))
  ob['observation_contract']['independent_expectations']=[
   {'partition_ref':'left','expected_ref':'R-1:left','attribution_assertion_ref':'left'},
   {'partition_ref':'right','expected_ref':'R-1:right','attribution_assertion_ref':'right'}]
  self.assertFalse(C.validate_obligations([row],True))
  ob['observation_contract']['surfaces'][0].update(status='gap',gap_reason='audit stream unavailable')
  self.assertTrue(any('gap surface cannot' in e for e in C.validate_obligations([row],True)))
 def test_no_leak_requires_direct_payload_assertion(self):
  ob=observed_obligation(kinds=['no_leak'])
  row={'id':'TS-1','schema_version':2,'coverage_contract_revision':C.COVERAGE_CONTRACT_REVISION,
       'coverage_obligations':[ob]}
  self.assertTrue(any('denied response payload' in e for e in C.validate_obligations([row],True)))
  ob['observation_contract']['payload_assertion_ref']='after'
  self.assertFalse(C.validate_obligations([row],True))
 def test_dict_scenarios_revision_and_declared_conflicts_are_validated(self):
  ob=observed_obligation(); ob['applicable_scenarios']=[{'scenario_id':'S-1','steps':[{'step_id':'complete'}]}]
  ob['observation_contract']['controls']=['S-1']; ob['observation_contract']['completion_ref']='complete'
  row={'id':'TS-1','schema_version':2,'coverage_contract_revision':C.COVERAGE_CONTRACT_REVISION,
       'coverage_obligations':[ob]}
  self.assertFalse(C.validate_obligations([row],True))
  ob['observation_contract']['oracle_ref']['revision']='wrong'
  self.assertTrue(any('revision must match' in e for e in C.validate_obligations([row],True)))
  ob['observation_contract']['oracle_ref']={'ref':'D-1','revision':'d-r1'}
  ob['observation_contract']['source_conflicts']=['D-1']
  self.assertTrue(any('must join' in e for e in C.validate_obligations([row],True)))
  ob['source_conflict_refs']=[{'id':'D-1'}]
  self.assertFalse(C.validate_obligations([row],True))
 def test_gap_surface_does_not_require_an_assertion_but_cannot_be_full(self):
  ob=observed_obligation(); ob['coverage_links'][0]['assessment']='partial'
  ob['observation_contract']['surfaces']=[{'id':'audit','boundary':'audit stream','status':'gap',
                                           'gap_reason':'stand exposes no audit stream'}]
  row={'id':'TS-1','schema_version':2,'coverage_contract_revision':C.COVERAGE_CONTRACT_REVISION,
       'coverage_obligations':[ob]}
  self.assertFalse(C.validate_obligations([row],True))
  ob['observation_contract']['claim_kind']=[]
  self.assertTrue(any('claim_kind' in e for e in C.validate_obligations([row],True)))
 def test_observation_malformed_ids_duplicate_partitions_and_reused_control_fail_closed(self):
  ob=observed_obligation(kinds=['state_unchanged']); row={'id':'TS-1','schema_version':2,
   'coverage_contract_revision':C.COVERAGE_CONTRACT_REVISION,'coverage_obligations':[ob]}
  ob['observation_contract']['surfaces'][0]['id']={'bad':'id'}
  self.assertTrue(any('surface IDs' in e for e in C.validate_obligations([row],True)))
  ob=observed_obligation(kinds=['state_unchanged']); row['coverage_obligations']=[ob]
  ob['observation_contract']['positive_control_ref']='action'
  self.assertTrue(any('must be separate' in e for e in C.validate_obligations([row],True)))
  ob=observed_obligation(kinds=['response_parity']); row['coverage_obligations']=[ob]
  ob['observation_contract']['independent_expectations']=[
   {'partition_ref':'same','expected_ref':'left','attribution_assertion_ref':'left'},
   {'partition_ref':'same','expected_ref':'right','attribution_assertion_ref':'right'}]
  self.assertTrue(any('partition refs must be unique' in e for e in C.validate_obligations([row],True)))

# t-176 (P5-F, t-134 R7, critic V12): a binding's role-written `unchanged` never makes a test witnessed
# that the ONE predicate (proof_level.proof_required) says is owed a live check. Both readers of the
# `not_required` branch - `witnessed_binding` (the window item) and `coverage_projection` (the manifest
# rows that list the binding's instances) - are driven end to end on a real accepted-window receipt.
NEW={'value':'new','basis':'b','resolved':True}
UNCHANGED={'value':'unchanged','basis':'b','resolved':True}

def fixture(td, ids=('selected',), item_extra=None, binding_extra=None):
 root=Path(td); (root/'work').mkdir(); ev=root/'run.txt'; ev.write_text('immutable run evidence',encoding='utf-8')
 ref={'path':'run.txt','sha256':hashlib.sha256(ev.read_bytes()).hexdigest()}
 ob=obligation('O-PASS'); (root/'work/test-plan.json').write_text(json.dumps({'rows':[{'id':'TS-1','schema_version':2,'coverage_obligations':[ob]}]}))
 refs=[{'obligation_id':'O-PASS','obligation_hash':content_hash(ob)}]
 items=[dict({'schema_version':2,'instance_id':i,'input_hash':'window-h','outcome':'passed','review':{'verdict':'approved','input_hash':'window-h'},
  'change_disposition':'unchanged','change_basis_ref':'repo:test','assertion_id':'test.py:9','defect_location':'src.py:4','evidence_refs':[ref],
  'execution_fingerprint':'fp-'+i,'obligation_ids':['O-PASS'],'obligation_refs':refs,'obligation_hash':content_hash(refs)},**(item_extra or {}).get(i,{})) for i in ids]
 window={'schema_version':2,'input_hash':'window-h','required_quality_checks':[],'quality_receipts':[],'scope_instances':{'TC-1':list(ids)},'instances':items}
 receipt=root/'work/window.json'; receipt.write_text(json.dumps(window))
 state={'dispatches':{'critic':{'stage':'S5','status':'accepted','window':window,
  'evidence_refs':[{'path':'work/window.json','sha256':hashlib.sha256(receipt.read_bytes()).hexdigest()}]}}}
 class Fake:
  def __init__(self,_root): pass
  def state(self): return state
 binding=dict({'obligation_id':'O-PASS','obligation_hash':content_hash(ob),'instance_ids':list(ids),'design_assessment':'sufficient','code_validity':'valid',
  'sensitivity':'not_required','change_disposition':'unchanged','change_basis_ref':'repo:test','assertion_refs':['test.py:9'],
  'quality_not_applicable_reason':'no configured quality gate','review_receipt_ref':'work/window.json'},**(binding_extra or {}))
 report={'current_results':[{'instance_id':i,'status':'passed','input_fingerprint':'fp-'+i} for i in ids]}
 return root,binding,report,Fake,ob

def witnessed(ids=('selected',), item_extra=None, binding_extra=None, lax=True, stub=None):
 """witnessed_binding on a real receipt; `lax` replaces the window's own validator, which already asks the
 same predicate of an item that has no probe, so what is left under test is the binding layer's own condition."""
 with tempfile.TemporaryDirectory() as td:
  root,binding,report,Fake,_=fixture(td,ids,item_extra,binding_extra)
  results={r['instance_id']:r for r in report['current_results']}
  with patch('controller.Controller',Fake), patch('acceptance.validate_window',(lambda w,r:[]) if lax else acceptance.validate_window), \
       patch('proof_level.proof_required',**({'side_effect':stub} if stub else {'wraps':proof_level.proof_required})):
   return C.witnessed_binding(root,binding,list(ids),results)

def projected(manifest_extra=None, ids=('selected',), item_extra=None, binding_extra=None, stub=None, manual=None):
 with tempfile.TemporaryDirectory() as td:
  root,binding,report,Fake,ob=fixture(td,ids,item_extra,binding_extra)
  manifest=dict({'obligation_bindings':[binding]},**(manifest_extra or {}))
  if manual:
   ob2=dict(obligation('O-PASS',decision='manual-agent')); (root/'work/test-plan.json').write_text(json.dumps({'rows':[{'id':'TS-1','schema_version':2,'coverage_obligations':[ob2]}]}))
   report=dict(report,current_manual_checks=[{'obligation_id':'O-PASS','evidence_validated':True,'result':'pass'}])
  with patch('controller.Controller',Fake), patch('acceptance.validate_window',lambda w,r:[]), patch('coverage_contract.validate_manual_current',lambda t,r:[]), \
       patch('proof_level.proof_required',**({'side_effect':stub} if stub else {'wraps':proof_level.proof_required})):
   return C.coverage_projection(root,report,manifest)['obligations'][0]

def row(iid, novelty=None, **more):
 return dict({'instance_id':iid},**({'novelty':novelty} if novelty is not None else {}),**more)

class BindingProofTests(unittest.TestCase):
 def test_control_unchanged_item_is_witnessed_without_any_patch(self):
  # the fixture itself is a genuinely accepted window: the real validator passes it
  self.assertTrue(witnessed(lax=False))
  self.assertTrue(witnessed(lax=False,item_extra={'selected':{'novelty':UNCHANGED}}))
  self.assertTrue(projected()['verified'])
 def test_hf4_10_nothing_demanded_means_a_binding_without_quality_fields_is_verified_by_the_projection(self):
  # killing key for the removed `refs or reason` line of `coverage_projection`: the window demands no quality check,
  # the binding carries neither refs nor a reason -> still witnessed (restoring the line makes this False)
  self.assertTrue(projected(binding_extra={'quality_not_applicable_reason':None})['verified'])
  # the other side: a ref to a receipt nothing owes is still false
  self.assertFalse(projected(binding_extra={'quality_not_applicable_reason':None,'quality_receipt_refs':['vcs']})['verified'])
 def test_r7_1_item_measured_new_changed_or_unknown_is_not_witnessed_as_not_required(self):
  for value in ('new','changed','unknown'):
   self.assertFalse(witnessed(item_extra={'selected':{'novelty':{'value':value,'basis':'b','resolved':True}}}),value)
  self.assertTrue(witnessed(item_extra={'selected':{'novelty':UNCHANGED}}))
  # a row flag the predicate honours, and an unreadable novelty, are owed too
  self.assertFalse(witnessed(item_extra={'selected':{'new_or_changed':True}}))
  self.assertFalse(witnessed(item_extra={'selected':{'sensitivity_proof_required':True}}))
  for bad in (None,[],7,{},{'value':'UNCHANGED'},'unchanged'):
   self.assertFalse(witnessed(item_extra={'selected':{'novelty':bad}}),repr(bad))
 def test_r7_3_an_item_without_novelty_keeps_todays_answer(self):
  self.assertTrue(witnessed())
  self.assertTrue(witnessed(item_extra={'selected':{'covers':['TC-1']}}))
 def test_edge_ii_one_owed_instance_among_several_refuses_the_binding(self):
  ids=('selected','second')
  self.assertTrue(witnessed(ids))
  self.assertFalse(witnessed(ids,item_extra={'second':{'novelty':NEW}}))
  self.assertFalse(witnessed(ids,item_extra={'selected':{'novelty':NEW}}))
 def test_r7_4_proven_binding_path_is_untouched_by_the_novelty_condition(self):
  proven={'sensitivity':'proven','proof_kind':'live','probe_receipt_ref':'run.txt','change_disposition':'new_or_changed'}
  item={'selected':{'change_disposition':'new_or_changed','novelty':NEW,'probe':{'evidence_ref':'run.txt'}}}
  self.assertTrue(witnessed(item_extra=item,binding_extra=proven))
  self.assertFalse(witnessed(item_extra=item,binding_extra=dict(proven,probe_receipt_ref='other.txt')))
  self.assertFalse(witnessed(item_extra=item,binding_extra=dict(proven,proof_kind='design_analysis')))
  # the projection reader: a proven binding stays verified though its manifest row is measured new
  p=projected({'tests':[row('selected',NEW,change_disposition='new_or_changed')]},item_extra=item,binding_extra=proven)
  self.assertEqual((p['sensitivity'],p['verified']),('proven',True))
 def test_edge_iv_a_raising_predicate_is_never_witnessed_in_either_reader(self):
  def boom(entry,manifest): raise RuntimeError('boom')
  self.assertFalse(witnessed(stub=boom))
  self.assertFalse(projected({'tests':[row('selected')]},stub=boom)['verified'])
  self.assertIs(C._proof_owed({'a':1},{}),False)  # the real predicate: a keyless, unflagged row is not owed
  with patch('proof_level.proof_required',side_effect=boom): self.assertIs(C._proof_owed({'a':1},{}),True)
 def test_r7_2_projection_refuses_when_a_manifest_row_of_the_instance_is_owed(self):
  for value in ('new','changed','unknown'):
   p=projected({'tests':[row('selected',{'value':value,'basis':'b','resolved':True})]})
   self.assertFalse(p['verified'],value); self.assertEqual(p['sensitivity'],'not_required'); self.assertIn('evidence incomplete',p['gap'])
  self.assertFalse(projected({'tests':[row('selected',new_or_changed=True)]})['verified'])  # the keyless row: the predicate's own flags
  self.assertFalse(projected({'tests':[row('selected',{'value':'unchanged','resolved':True},change_disposition='new_or_changed')]})['verified'])
  self.assertFalse(projected({'tests':[row('selected',None,sensitivity_proof_required=True)]})['verified'])
  for bad in (None,[],7,{}):
   self.assertFalse(projected({'tests':[dict(row('selected'),novelty=bad)]})['verified'],repr(bad))
 def test_r7_3_no_row_or_a_keyless_row_keeps_todays_answer(self):
  self.assertTrue(projected()['verified'])
  self.assertTrue(projected({'tests':[]})['verified'])
  self.assertTrue(projected({'tests':[row('selected')]})['verified'])                 # a row with no novelty key
  self.assertTrue(projected({'tests':[row('unrelated',NEW)]})['verified'])            # an owed row of ANOTHER instance
  self.assertTrue(projected({'tests':[row('selected',UNCHANGED)]})['verified'])      # measured unchanged
 def test_r7_4_winner_is_the_measured_novelty_not_the_role_written_unchanged(self):
  # the binding says unchanged, and so does the window item; only the manifest row knows the test is new
  p=projected({'tests':[row('selected',NEW)]}); self.assertFalse(p['verified'])
  self.assertFalse(projected({'tests':[row('selected',NEW,change_disposition='unchanged')]})['verified'])
 def test_projection_aliases_and_retracted_aliases(self):
  aliased=row('TC-1::selected',NEW,case='TC-1')   # canonical differs from the binding's spelling; `selected` is an alias
  self.assertFalse(projected({'tests':[aliased]})['verified'])
  self.assertTrue(projected({'tests':[dict(aliased,novelty=UNCHANGED)]})['verified'])
  self.assertFalse(projected({'tests':[row('selected',NEW)],'retracted_instances':['other']})['verified'])
  # edge iii: a row listed under a retracted alias only does not bind
  self.assertTrue(projected({'tests':[row('selected',NEW)],'retracted_instances':['selected']})['verified'])
  self.assertTrue(projected({'tests':[aliased],'retracted_instances':['selected','TC-1::selected']})['verified'])
  self.assertFalse(projected({'tests':[aliased],'retracted_instances':['TC-1::selected']})['verified'])  # the live alias `selected` still joins
 def test_edge_ii_projection_any_owed_row_of_several_wins(self):
  ids=('selected','second')
  self.assertTrue(projected({'tests':[row('selected',UNCHANGED),row('second',UNCHANGED)]},ids)['verified'])
  self.assertFalse(projected({'tests':[row('selected',UNCHANGED),row('second',NEW)]},ids)['verified'])
  self.assertFalse(projected({'tests':[row('second',NEW),row('selected',UNCHANGED)]},ids)['verified'])
 def test_edge_i_manifest_unavailable_never_raises(self):
  for bad in (None,[],7,'x'):
   self.assertIs(C._manifest_owes_proof(bad,['selected']),False)
   self.assertIs(C._proof_owed({'novelty':NEW},bad),True)   # a measured `new` needs no manifest to be owed
   self.assertIs(C._proof_owed({'case':'TC-1'},bad),False)
  self.assertIs(C._manifest_owes_proof({'tests':[row('selected',NEW)]},[]),False)   # no instance, no row to join
  self.assertIs(C._manifest_owes_proof({'tests':[row('selected',NEW)]},None),False)
  self.assertIs(C._manifest_owes_proof({'tests':['junk',None,row('selected',NEW)]},['selected']),True)
 def test_edge_v_manual_branch_is_not_subjected_to_the_condition(self):
  # a manual obligation has no test row; its `not_required` is set by the manual branch from the
  # validated capture, so a manifest row that is owed (here, for a same-named instance) changes nothing
  p=projected({'tests':[row('selected',NEW)]},manual=True)
  self.assertEqual((p['sensitivity'],p['code_validity'],p['execution_state'],p['verified']),('not_required','not_applicable','passed',True))
  self.assertTrue(projected(manual=True)['verified'])
# t-238 (the analog t-219 section 0d named): the critic publishes with `window_record --review-receipt`, so
# `review_receipt_ref` names work/review-receipts/<id>.json - a receipt, never equal to the window - and the
# reader said "not witnessed" for every binding published that way. The reader rebuilds the receipt from the
# accepted dispatch's window (`window_record.receipt_dict`) and compares it whole. These cases are driven on
# a receipt the REAL writer wrote.
def receipt_story(td, ids=('selected','second')):
 root,binding,report,_,_=fixture(td,ids)
 window=dict(json.loads((root/'work/window.json').read_text()),author_dispatch_id='author',reviewer_dispatch_id='critic')
 return root,binding,report,window

def put_window(root, window, name='critic'):
 path=root/'work/windows'/(name+'.json'); path.parent.mkdir(exist_ok=True); path.write_text(json.dumps(window))
 return {'path':'work/windows/%s.json'%name,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}

def dispatch(window, ref, ident='critic', status='accepted'):
 return {'id':ident,'stage':'S5','status':status,'window':window,'evidence_refs':[ref]}

def published(root, window):
 """The receipt as the critic's `--review-receipt` writes it: the real writer, the real path."""
 return WR.write_review_receipt(root,window,window['reviewer_dispatch_id'])['path']

def stand_of(dispatches):
 class Fake:
  def __init__(self,_root): pass
  def state(self): return {'dispatches':dispatches}
 return Fake

def why(root, dispatches, ref):
 with patch('controller.Controller',stand_of(dispatches)): return C.window_of_ref(root,ref)

def bound(root, binding, report, dispatches, ref, ids=('selected','second'), lax=True):
 results={r['instance_id']:r for r in report['current_results']}
 with patch('controller.Controller',stand_of(dispatches)), patch('acceptance.validate_window',(lambda w,r:[]) if lax else acceptance.validate_window):
  return C.witnessed_binding(root,dict(binding,review_receipt_ref=ref),list(ids),results)

def tree(root):
 return {p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(root.rglob('*')) if p.is_file()}

def per_test(window, review=True, item=True, probe=True):
 """The window's instances with the per-test fields (t-043 C) - or with only some of them."""
 items=[]
 for it in window['instances']:
  it=dict(it,probe={'evidence_ref':'run.txt','input_hash':'window-h'},review=dict(it['review']))
  if item: it['test_code_sha']='code-'+it['instance_id']; it['instance_identity']={'job_id':'j'}
  if review: it['review']['test_code_sha']='code-'+it['instance_id']
  if probe: it['probe']['test_code_sha']='code-'+it['instance_id']
  items.append(it)
 return dict(window,instances=items)

class ReviewReceiptRefTests(unittest.TestCase):
 def story(self, td, mutate=None, receipt_of=None):
  root,binding,report,window=receipt_story(td)
  ref=put_window(root,window)
  published_from=receipt_of(window) if receipt_of else window
  path=published(root,published_from)
  return root,binding,report,window,{'critic':dispatch(window,ref)},path
 def test_a_receipt_published_by_the_writer_is_witnessed_and_the_window_file_still_is(self):
  with tempfile.TemporaryDirectory() as td:
   root,binding,report,window,disp,path=self.story(td)
   self.assertEqual(path,'work/review-receipts/critic.json')
   self.assertTrue(bound(root,binding,report,disp,path,lax=False))                   # as published
   self.assertTrue(bound(root,binding,report,disp,'work/windows/critic.json',lax=False))   # the control: today's ref
   self.assertEqual(why(root,disp,path),(window,''))
   self.assertEqual(why(root,disp,'work/windows/critic.json'),(window,''))
 def test_the_receipt_is_read_through_the_same_checks_as_the_window(self):
  # a receipt reaching the window does not skip what the reader asks of the window's instances
  with tempfile.TemporaryDirectory() as td:
   root,binding,report,window,disp,path=self.story(td)
   self.assertFalse(bound(root,binding,report,disp,path,ids=('selected','absent')))
   self.assertFalse(bound(root,dict(binding,assertion_refs=['elsewhere.py:1']),report,disp,path))
   self.assertFalse(bound(root,dict(binding,change_disposition='new_or_changed'),report,disp,path))
 def test_fr18_a_receipt_of_other_instances_is_not_the_windows_receipt(self):
  def differing(change):
   with tempfile.TemporaryDirectory() as td:
    root,binding,report,window=receipt_story(td)
    other=change(json.loads(json.dumps(window)))
    ref=put_window(root,window); path=published(root,other)
    disp={'critic':dispatch(window,ref)}
    return bound(root,binding,report,disp,path),why(root,disp,path)
  def body(w): w['instances'][0]['outcome']='failed'; return w
  def nested(w): w['instances'][1]['review']['verdict']='rejected'; return w
  def drop(w): w['instances']=w['instances'][:1]; return w
  def extra(w): w['instances'].append(dict(w['instances'][0],instance_id='third')); return w
  def input_hash(w): w['input_hash']='other'; return w
  def scope(w): w['scope_instances']={'TC-1':['selected']}; return w
  def quality(w): w['required_quality_checks']=['lint']; return w
  expected=[(body,'instances[selected].outcome'),(nested,'instances[second].review.verdict'),
   (drop,'instances (the set of instance ids differs)'),(extra,'instances (the set of instance ids differs)'),
   (input_hash,'input_hash'),(scope,'scope_instances.TC-1'),(quality,'required_quality_checks')]
  for change,field in expected:
   ok,(found,reason)=differing(change)
   self.assertFalse(ok,field); self.assertIsNone(found); self.assertEqual(reason,'receipt differs from the accepted window at '+field)
 def test_a_receipt_whose_hash_does_not_match_its_content_is_altered(self):
  with tempfile.TemporaryDirectory() as td:
   root,binding,report,window,disp,path=self.story(td)
   file=root/path; body=json.loads(file.read_text())
   body['instances'][0]['outcome']='failed'            # the hash is the writer's, the content is not
   file.write_text(json.dumps(body))
   self.assertFalse(bound(root,binding,report,disp,path))
   self.assertEqual(why(root,disp,path),(None,'receipt altered: its receipt_hash does not match its content'))
   body.pop('receipt_hash'); file.write_text(json.dumps(body))                     # no hash at all is no pass either
   self.assertEqual(why(root,disp,path)[1],'receipt altered: its receipt_hash does not match its content')
   body['receipt_hash']=content_hash({k:v for k,v in body.items() if k!='receipt_hash'}); file.write_text(json.dumps(body))
   self.assertEqual(why(root,disp,path)[1],'receipt differs from the accepted window at instances[selected].outcome')  # rehashed: the comparison still sees it
 def test_the_writers_own_equivalence_is_accepted_and_nothing_wider(self):
  # `copy`: the receipt was written before the review copied its per-test field; `legacy`: before any per-test field existed
  for name,old in (('copy',lambda w:per_test(w,review=False)),('legacy',lambda w:per_test(w,review=False,item=False,probe=False))):
   with tempfile.TemporaryDirectory() as td:
    root,binding,report,base=receipt_story(td)
    window=per_test(base); ref=put_window(root,window); disp={'critic':dispatch(window,ref)}
    path=published(root,old(base))
    on_disk=json.loads((root/path).read_text())
    self.assertNotEqual(on_disk['instances'],WR.receipt_dict(window)['instances'])
    self.assertEqual(WR._per_test_difference(on_disk,WR.receipt_dict(window)),name)   # the writer's own rule says so
    self.assertTrue(bound(root,binding,report,disp,path),name); self.assertEqual(why(root,disp,path),(window,''),name)
    # the same receipt, but it also differs in a field per-test binding does not add
    bad=old(base); bad['instances'][0]['outcome']='failed'
    (root/path).unlink(); published(root,bad)
    self.assertFalse(bound(root,binding,report,disp,path),name)
    self.assertEqual(why(root,disp,path),(None,'receipt differs from the accepted window at instances[selected].outcome'),name)
 def test_a_receipt_of_no_accepted_dispatch_names_the_lack(self):
  with tempfile.TemporaryDirectory() as td:
   root,binding,report,window,disp,path=self.story(td)
   for other in ({},{'critic':dispatch(window,disp['critic']['evidence_refs'][0],status='running')},
                 {'critic':dispatch(window,disp['critic']['evidence_refs'][0],ident='someone-else')},
                 {'critic':dict(dispatch(window,disp['critic']['evidence_refs'][0]),stage='S4')},
                 {'critic':dict(dispatch(window,disp['critic']['evidence_refs'][0]),window=None)}):
    self.assertFalse(bound(root,binding,report,other,path)); self.assertEqual(why(root,other,path),(None,'no accepted window for this receipt'))
 def test_a_missing_or_unreadable_file_and_a_missing_window_file_are_never_witnessed(self):
  with tempfile.TemporaryDirectory() as td:
   root,binding,report,window,disp,path=self.story(td)
   self.assertEqual(why(root,disp,'work/review-receipts/none.json'),(None,'no file at work/review-receipts/none.json'))
   self.assertFalse(bound(root,binding,report,disp,'work/review-receipts/none.json'))
   (root/'work/junk.json').write_text('{not json'); (root/'work/other.json').write_text('{"a": 1}')
   self.assertIn('unreadable',why(root,disp,'work/junk.json')[1]); self.assertFalse(bound(root,binding,report,disp,'work/junk.json'))
   self.assertIn('neither an accepted window nor a review receipt',why(root,disp,'work/other.json')[1])
   self.assertFalse(bound(root,binding,report,disp,'work/other.json'))
   (root/'work/windows/critic.json').unlink()                                     # the window file the dispatch names is gone
   self.assertFalse(bound(root,binding,report,disp,path))
   self.assertEqual(why(root,disp,path),(None,'window file missing: no evidence ref of the accepted dispatch holds its window'))
   self.assertFalse(bound(root,binding,report,disp,'work/windows/critic.json'))       # and today's ref to it
 def test_a_window_file_that_is_not_the_accepted_bytes_is_not_the_windows_file(self):
  with tempfile.TemporaryDirectory() as td:
   root,binding,report,window,disp,path=self.story(td)
   (root/'work/windows/critic.json').write_text(json.dumps(dict(window,input_hash='edited')))   # digest no longer matches the evidence ref
   self.assertEqual(why(root,disp,path)[1],'window file missing: no evidence ref of the accepted dispatch holds its window')
 def test_a_dispatch_accepted_twice_reads_the_latest_window(self):
  with tempfile.TemporaryDirectory() as td:
   root,binding,report,window=receipt_story(td)
   older=dict(window,instances=[dict(window['instances'][0],outcome='failed')]+window['instances'][1:])
   ref_old,ref_new=put_window(root,older,'critic-1'),put_window(root,window)
   disp={'critic-1':dispatch(older,ref_old),'critic-2':dispatch(window,ref_new)}
   path=published(root,window)
   self.assertTrue(bound(root,binding,report,disp,path)); self.assertEqual(why(root,disp,path),(window,''))
   (root/path).unlink(); path=published(root,older)                       # the receipt of the first acceptance: the window is now another
   self.assertFalse(bound(root,binding,report,disp,path))
   self.assertEqual(why(root,disp,path)[1],'receipt differs from the accepted window at instances[selected].outcome')
 def test_a_ref_outside_the_task_is_refused_and_the_reader_writes_nothing(self):
  with tempfile.TemporaryDirectory() as td:
   root,binding,report,window,disp,path=self.story(td)
   (Path(td).parent/'outside-t238.json').write_text('{}')
   try:
    before=tree(root)
    for bad in ('../outside-t238.json','work/../'+path,'work/review-receipts/../review-receipts/critic.json',str((root/path).resolve()),'/'+path,'\\'+path):
     self.assertFalse(bound(root,binding,report,disp,bad),bad); self.assertEqual(why(root,disp,bad),(None,'ref outside the task'),bad)
    for good in (path,'work/windows/critic.json'): bound(root,binding,report,disp,good); why(root,disp,good)
    self.assertEqual(tree(root),before)
   finally: (Path(td).parent/'outside-t238.json').unlink()
 def test_the_receipt_does_not_lend_the_window_a_binding_it_does_not_have(self):
  # an unreadable or absent ref of any kind stays False, as before
  with tempfile.TemporaryDirectory() as td:
   root,binding,report,window,disp,path=self.story(td)
   for ref in (None,'',7,[]): self.assertFalse(bound(root,binding,report,disp,ref),repr(ref))

class WaitingForAPersonTests(unittest.TestCase):
 # --- t-227c (P20, C3, F20): an obligation whose expected value waits for a person ---------------------------------
 # cmp2 OB-15 (plan row TS-15, case TC_015): R-19 exists only in the diff, Then 4 (P-multi) has no source, and the plan
 # still said `oracle_status: resolved`. The projection reads the sources NOW: such an obligation is `unresolved` AND the
 # person's debt - never a block - and an answered question turns it back, with the answered value, without editing the plan.
 FIX=Path(__file__).resolve().parent/'fixtures'/'oracle-provenance'
 def waiting_story(self,td,register=True,case='oracles',stored='unresolved',answered=False):
  import question_register as QR
  root=Path(td); (root/'work/test-cases/workflow-visual-diff').mkdir(parents=True)
  ob=obligation('OB-15',decision='unresolved' if stored=='unresolved' else 'new'); ob['requirement_refs']=[{'ref':'R-19','revision':'r'}]
  ob['oracle_status']=stored; ob['remaining_gap']='P-multi expected code needs owner' if stored=='unresolved' else ''
  row={'id':'TS-15','schema_version':2,'requirement_refs':['R-19'],'coverage_obligations':[ob]}
  (root/'work/test-plan.json').write_text(json.dumps({'rows':[row]}))
  (root/'work/requirements-readiness.json').write_text((self.FIX/'requirements-readiness.json').read_text(encoding='utf-8'),encoding='utf-8')
  text=(self.FIX/'requirements-register.md').read_text(encoding='utf-8')
  if register=='dated': text=text.replace('created: 2026-10-01','created: 2026-10-02')+("\n## Behaviour claims\n\n| R | before | before_ref | now | now_ref | differs | question |\n|---|---|---|---|---|---|---|\n| R-19 | unknown | diff:-w.py:1 | 400 | diff:+w.py:2 | yes | Q7 |\n")
  if register: (root/'work/requirements-register.md').write_text(text,encoding='utf-8')
  if case:
   body=(self.FIX/'TP1-15045_TC_015.md').read_text(encoding='utf-8').replace('TP1-15045_TC_015','TC-015').replace('updated: 2026-10-01','updated: 2026-10-02')
   if case=='oracles':
    body=body.replace('plan_row: TS-15\n','then_oracles: [{"then": 1, "source": "ac", "ref": "R-13"}, {"then": 4, "source": "unknown", "ref": "Q7"}]\nquestion_thens: [{"question": "Q7", "then": 4, "readings": {"a": "HTTP 400, the behaviour now", "b": ""}, "not_needed": ""}]\nplan_row: TS-15\n',1)
   (root/'work/test-cases/workflow-visual-diff/TC-015.md').write_text(body,encoding='utf-8')
  if answered:
   view={q['id']:q for q in QR.load(root)['questions']}['Q7']; QR.record(root,'Q7','answered','Q7: a','gate A','driver',view['row_hash'],reading='a')
  return root
 def project(self,root):
  return C.coverage_projection(root,{'current_results':[]},{'obligation_bindings':[]})['obligations'][0]
 def test_an_obligation_with_an_open_unknown_then_is_unresolved_and_the_persons_debt(self):
  import check_delivery as D
  with tempfile.TemporaryDirectory() as td:
   item=self.project(self.waiting_story(td,register=False))
   self.assertEqual((item['person_debt'],item['verified']),(True,False)); self.assertNotIn('oracle_status',item,'stored unresolved, read unresolved: nothing differs')
   self.assertIn('Q7',item['gap']); self.assertIn('left with you',item['gap']); self.assertNotIn('P-multi',item['gap'])
   self.assertEqual(D.coverage_reasons({'coverage':{'obligations':[item]}}),[],'the gap names the person and holds nothing (F7)')
 def test_the_false_resolved_of_an_implementation_only_requirement_is_read_as_unresolved(self):
  import check_delivery as D
  with tempfile.TemporaryDirectory() as td:     # stored `resolved` (the cmp2 plan), no case at all: only R-19 says so
   item=self.project(self.waiting_story(td,register='dated',case=None,stored='resolved'))
   self.assertEqual((item['oracle_status'],item['person_debt']),('unresolved',True)); self.assertIn('Q7',item['gap'])
   self.assertEqual(D.coverage_reasons({'coverage':{'obligations':[item]}}),[])
 def test_an_answered_question_reads_the_obligation_as_resolved_with_the_answered_value(self):
  with tempfile.TemporaryDirectory() as td:
   root=self.waiting_story(td,register='dated',answered=True)
   item=self.project(root)
   self.assertEqual((item['oracle_status'],item['person_debt']),('resolved',False))
   self.assertEqual(item['oracle_answers'],[{'then':4,'question':'Q7','expected':'HTTP 400, the behaviour now'}])
   self.assertEqual(json.loads((root/'work/test-plan.json').read_text())['rows'][0]['coverage_obligations'][0]['oracle_status'],'unresolved','the approved plan is never edited')
 def test_legacy_obligations_read_as_they_did(self):
  # the cmp2 shapes verbatim: no then_oracles line in the case, a register older than the cutoff, a stored `resolved`
  with tempfile.TemporaryDirectory() as td:
   item=self.project(self.waiting_story(td,register=True,case='plain',stored='resolved'))
   self.assertNotIn('oracle_status',item); self.assertNotIn('oracle_answers',item); self.assertFalse(item['person_debt'])
   self.assertEqual(item['gap'],'current sufficient evidence incomplete')
  with tempfile.TemporaryDirectory() as td:     # a story with none of the new files at all
   root=Path(td); (root/'work').mkdir(); ob=obligation(); (root/'work/test-plan.json').write_text(json.dumps({'rows':[{'id':'TS-1','schema_version':2,'coverage_obligations':[ob]}]}))
   item=self.project(root); self.assertFalse(item['person_debt']); self.assertNotIn('oracle_status',item)
 def test_a_stored_unresolved_oracle_with_no_question_behind_it_still_blocks(self):
  import check_delivery as D
  with tempfile.TemporaryDirectory() as td:     # no then_oracles, a legacy register: nobody is being asked, so nobody is owed anything
   item=self.project(self.waiting_story(td,register=True,case='plain',stored='unresolved'))
   self.assertFalse(item['person_debt']); self.assertEqual(item['gap'],'P-multi expected code needs owner')
   self.assertTrue(D.coverage_reasons({'coverage':{'obligations':[item]}}),'a block that nobody can answer stays a block, as today')
 def test_a_red_run_of_a_waiting_obligation_keeps_its_own_blocking_gap(self):
  with tempfile.TemporaryDirectory() as td:
   root=self.waiting_story(td,register=False)
   ob=json.loads((root/'work/test-plan.json').read_text())['rows'][0]['coverage_obligations'][0]
   bind={'obligation_id':'OB-15','obligation_hash':content_hash(ob),'instance_ids':['i']}
   item=C.coverage_projection(root,{'current_results':[{'instance_id':'i','status':'failed'}]},{'obligation_bindings':[bind]})['obligations'][0]
   self.assertEqual((item['execution_state'],item['person_debt']),('failed',False),'a failure is not the person\'s debt')
 def test_the_obligation_comes_from_the_mapping_not_from_the_case_text(self):
  # t-271 F2 (`_names` is gone): a case whose text never prints OB-15 still answers for it through the approved
  # mapping (its requirements against the obligation's requirement_refs); a case that prints the id and maps to
  # another requirement does not (the t-271 section of test_oracle_provenance.py holds the mutation key).
  with tempfile.TemporaryDirectory() as td:
   root=self.waiting_story(td,register=False)
   case=root/'work/test-cases/workflow-visual-diff/TC-015.md'
   text=case.read_text(encoding='utf-8'); self.assertIn('R-19',text)
   self.assertTrue(self.project(root)['person_debt'],'control: the case maps to R-19 and its Then 4 waits')
   case.write_text(text.replace('OB-15','the obligation'),encoding='utf-8')
   self.assertTrue(self.project(root)['person_debt'],'the id is not printed in the case: the mapping still reads it')
   case.write_text(text.replace('R-19','R-3'),encoding='utf-8')
   item=self.project(root)
   self.assertFalse(item['person_debt'],'a case that maps to another requirement says nothing about this obligation, whatever it prints')
   self.assertNotIn('left with you',item['gap'])

class ManualImageIdentityTests(unittest.TestCase):
 """t-300 N2 K-N2.10 (S13; t-279 Q1's `unknown` + image is retired by Q18-B): `validate_manual_current` reads a MANUAL
 record's two probes through the ONE predicate. A person's word for THIS story is taken - and, like a `matched` one, binds
 the checkout revision a run of the story recorded for the profile (none recorded: refused); the word of ANOTHER story is
 refused; an `unknown` is refused, with or without the image the container runs; a changed identity between the probes is
 refused. The `matched` record is unchanged (the control)."""
 IMAGE='image:sha256:'+'b'*64
 def test_image_identity_in_a_manual_record(self):
  sys.path.insert(0,str(Path(__file__).resolve().parent/'fixtures'/'manual-evidence'))
  import scaffold as S
  import test_manual_capture as TMC
  t=S.make_task()
  try:
   TMC.seed_runtime_records(t)
   steps=t.task/'steps.txt'; steps.write_text(TMC.UI_STEPS,encoding='utf-8')
   TMC.patch_backends(S.FakeBrowser())
   S.run(['ui','--task-root',str(t.task),'--case',S.CASES['ui'],'--steps-file',str(steps)])
   code,out,err=TMC.build(t,S.CASES['ui'],'--result','pass','--actual','x','--masked')
   self.assertEqual(code,0,err)
   record=json.loads((t.attempt_dir(S.CASES['ui'])/'record.json').read_text(encoding='utf-8'))
   def errors(before,after=None,**more):
    with t.patched(): return C.validate_manual_current(t.task,dict(record,runtime_before=before,runtime_after=after or before,**more))
   def image(identity=None,result='unknown',**extra):
    return dict(record['runtime_before'],result=result,observed_runtime_identity=identity or self.IMAGE,evidence_refs=[],
                provenance={'technical_verification':False},**extra)
   def word(**more): return TMC.person_probe(**more)
   self.assertEqual(errors(record['runtime_before']),[],'control: the matched record is unchanged')
   self.assertEqual(errors(word()),[],'K-N2.10: a person\'s word for this story, with a run revision recorded for the profile: valid')
   self.assertEqual(errors(record['runtime_before'],word(observed_runtime_identity=record['runtime_before']['observed_runtime_identity'])),[],
                    'K-N2.10 X14: matched before, the person\'s word after, ONE identity: valid')
   elsewhere=errors(word(task='OTHER-9'))
   self.assertTrue([e for e in elsewhere if 'manual runtime provenance is unverified' in e and 'was given for story OTHER-9, and this is story '+S.TICKET in e],
                   'K-N2.10 X5: a word given for ANOTHER story is refused, naming both: '+repr(elsewhere))
   self.assertIn('manual runtime changed during execution',errors(word(),word(observed_runtime_identity='image:sha256:'+'c'*64)),
                 'a redeploy between the probes (PC/PC, two identities) is refused')
   for old in (t.task/'evidence').glob('runtime-provenance-*.json'): old.unlink()
   self.assertTrue([e for e in errors(record['runtime_before']) if 'binds a checkout revision' in e],'control: matched with no recorded revision is still refused')
   self.assertTrue([e for e in errors(word()) if 'binds a checkout revision' in e],
                   'K-N2.10: a person\'s word binds the revision too: with NO run recorded for the profile it is refused (:691), unknown is not a match')
   # an `unknown` is taken by no token - with or without the image the container runs
   self.assertTrue([e for e in errors(image()) if 'manual runtime provenance is unverified: runtime probe returned unknown' in e],
                   'K-N2.10 Q18-B: unknown + image is refused now (t-279 Q1 took it)')
   self.assertTrue([e for e in errors(image(identity='image:sha256:abc')) if 'unverified' in e],'a malformed digest is refused too')
   self.assertTrue([e for e in errors(image(identity='build-1')) if 'unverified' in e],'a bare unknown with another identity is refused')
   self.assertTrue([e for e in errors(image(result='mismatched')) if 'unverified' in e],'the image on a mismatched is refused')
   self.assertTrue([e for e in errors(image(identity=self.IMAGE.replace('image:',''))) if e.startswith('manual runtime provenance is unverified: runtime probe returned')],'a digest without `image:` is refused')
  finally: S.cleanup(t)
if __name__=='__main__': unittest.main()
