"""Native event/transport regression probes; no model calls or live app writes."""
import json
import os
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
# This file drives the real launchers as subprocesses and never imports harness.py, so the
# rule harness.py states had no effect here: those children wrote scripts/__pycache__ back
# into the package, and a marketplace whose source is a local directory ships whatever lies
# there. The children inherit both of these.
sys.dont_write_bytecode=True
os.environ['PYTHONDONTWRITEBYTECODE']='1'
from host_adapter import normalize, mutation_events, rewritten_input
from codex_usage import scan

SCRIPTS=Path(__file__).resolve().parents[1]


def hook_entries(wiring):
    """Every (event name, hook) of codex.json, in file order."""
    return [(name,hook) for name,entries in wiring['hooks'].items()
            for entry in entries for hook in entry['hooks']]


def launcher_parts(command):
    """One wiring line as (launcher prefix, arguments, shell suffix).

    Every entry of codex.json is the SAME launcher — one run-py.cmd, one telemetry_hook.py —
    with a different argument list. That is what makes it enough to start one of them for
    real and compare the other thirteen as strings: the two tests below used to spend 42
    pwsh launches at 2.48 s each, 15% of the whole selftest, re-proving one launcher."""
    head,rest=command.split(' telemetry_hook.py ',1)
    args,separator,suffix=rest.partition(';')
    return head,args.split(),separator+suffix


class NativeHostTests(unittest.TestCase):
    def test_reviewed_historical_import_is_idempotent_and_keeps_gaps(self):
        from recover_codex_usage import recover
        from dashboard_cost_groups import group
        from datetime import datetime
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);qf=root/'qa-factory';qf.mkdir();(qf/'config.json').write_text('{"schema_version":1}')
            path=root/'rollout.jsonl'
            boundaries=[dict(call_id='start',timestamp='2026-09-19T10:00:02Z',action='start',type='doctor'),
                        dict(call_id='end',timestamp='2026-09-19T10:00:04Z',action='end',type='doctor')]
            records=[{'type':'session_meta','payload':{'id':'s','cli_version':'fixture'}},
                     {'type':'turn_context','payload':{'turn_id':'t','model':'gpt-5.6-terra'}}]
            for boundary in boundaries:
                records.append({'type':'response_item','timestamp':boundary['timestamp'],'payload':{'type':'function_call','call_id':boundary['call_id'],
                    'arguments':"activity_capture.py --action "+boundary['action']+" --type doctor"}})
            for i in (1,3,5):
                records.append({'type':'token_usage_record','timestamp':f'2026-09-19T10:00:0{i}Z','payload':{'thread_id':'s','turn_id':'t','response_id':str(i),
                    'usage':{'input_tokens':100,'cached_input_tokens':40,'output_tokens':20,'total_tokens':120}}})
            path.write_text(''.join(json.dumps(r)+'\n' for r in records),encoding='utf-8')
            self.assertEqual(recover(root,path,boundaries)['request_count'],3)
            self.assertFalse((qf/'state').exists())
            # A historical import reads an OLD transcript: backdating it lets the recapture
            # maintenance pass run inside the first import, which is where capture_key was
            # lost before 0.7.18 (the strip happened before the writer lock was asked for).
            os.utime(path,(time.time()-4000,)*2)
            recover(root,path,boundaries,True)
            cost=qf/'state/cost/s.json';doc=json.loads(cost.read_text(encoding='utf-8'))
            # capture_key is the whole reason a second import is a no-op, so assert the field
            # itself instead of inferring it from bytes: a pass that strips it (the recapture
            # maintenance pass does, and drops it for good when the writer lock is already
            # held) makes every later capture rewrite the file, and the compare below then
            # fails on the wall-clock fields alone. Pin the input that decided whether that
            # pass ran: `_stale_reason` compares the activity file's mtime against
            # `generated`, which is truncated to whole seconds, so this import was "stale" or
            # not depending on which side of a second boundary the capture happened to land.
            self.assertIn('capture_key',doc)
            stamp=datetime.fromisoformat(doc['generated']).timestamp()-60
            os.utime(qf/'state/activities/s.json',(stamp,stamp))
            first=cost.read_bytes()
            recover(root,path,boundaries,True)
            self.assertEqual(first,cost.read_bytes())
            doc=json.loads(first);groups,_=group([doc])
            self.assertEqual(groups['Doctor']['tokens'],120)
            self.assertEqual(groups['Unclassified']['tokens'],240)
            self.assertEqual(doc['usage_completeness'],'provisional')
            with self.assertRaises(ValueError):recover(root,path,[dict(boundaries[0],call_id='invented')],True)

    def test_native_role_export_and_exact_policy(self):
        from codex_roles import export, check_override
        with tempfile.TemporaryDirectory() as tmp:
            policy={'roles':{'qa-scout':{'model':'gpt-test','effort':'high'}}}
            result=export(tmp,policy,True)
            self.assertGreater(len(result['roles']),5)
            check_override(tmp,'qa-scout',{'model':'gpt-test','effort':'high'})
            with self.assertRaises(ValueError):check_override(tmp,'qa-scout',{'model':'other','effort':'high'})
            (Path(tmp)/'.codex/agents/qa-scout.toml').write_text('name="mine"')
            with self.assertRaises(ValueError):export(tmp,policy,True)

    def test_terra_context_tariff_is_request_scoped(self):
        from cost_capture import value_usage
        from datetime import datetime, timezone
        at=datetime(2026,9,19,tzinfo=timezone.utc)
        short=value_usage({'requests':1,'input':200000,'cache_read':72000,'output':1000},'gpt-5.6-terra',{},at=at)
        long=value_usage({'requests':1,'input':200001,'cache_read':72000,'output':1000},'gpt-5.6-terra',{},at=at)
        self.assertEqual(short['rate_provenance']['context_band'],'short')
        self.assertEqual(long['rate_provenance']['context_band'],'long')
        self.assertAlmostEqual(float(short['subtotal_usd']),.4264)
        self.assertAlmostEqual(float(long['subtotal_usd']),.846804)
        self.assertEqual(value_usage({'input':1},'gpt-5.6-terra-other',{},at=at)['pricing_coverage'],'none')

    def test_native_wiring_runs_literal_launcher_and_preserves_block(self):
        """Every hook of codex.json still answers the event the host sends it with exit 0 and,
        when it speaks, a JSON object. The LAUNCHER is proven on the first entry and again on
        the block below (exit 2); the other thirteen lines are asserted to be that same
        launcher with only their arguments changed, and their scripts are started through
        telemetry_hook.py directly — see launcher_parts."""
        wiring=json.loads((SCRIPTS.parent/'hooks/codex.json').read_text(encoding='utf-8'))
        entries=hook_entries(wiring)
        key='commandWindows' if os.name == 'nt' else 'command'
        head,_,suffix=launcher_parts(entries[0][1][key])
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            env=dict(os.environ,CLAUDE_PROJECT_DIR=str(root),CLAUDE_PLUGIN_ROOT=str(SCRIPTS.parent),QA_FACTORY_PYTHON=sys.executable)
            def event_for(name):
                return {'hook_event_name':name,'turn_id':'native-fixture','session_id':'fixture','cwd':str(root),
                        'tool_name':'exec_command','tool_input':{'cmd':'git status'},'source':'compact'}
            proven_name,proven=entries[0]
            command=proven[key].replace('${CLAUDE_PLUGIN_ROOT}',str(SCRIPTS.parent))
            result=self.run_native_command(command,event_for(proven_name),root,env)
            self.assertEqual(result.returncode,0,(proven_name,command,result.stderr))
            if result.stdout.strip():self.assertIsInstance(json.loads(result.stdout),dict)
            for name,hook in entries:
                line_head,args,line_suffix=launcher_parts(hook[key])
                self.assertEqual((line_head,line_suffix),(head,suffix),(name,hook[key]))
                self.assertEqual(args,launcher_parts(hook['command'])[1],name)
                if hook is proven:continue
                run=subprocess.run([sys.executable,str(SCRIPTS/'telemetry_hook.py'),*args],input=json.dumps(event_for(name)),
                    text=True,encoding='utf-8',capture_output=True,cwd=root,env=env,timeout=30)
                self.assertEqual(run.returncode,0,(name,args,run.stderr))
                if run.stdout.strip():self.assertIsInstance(json.loads(run.stdout),dict)
            (root/'qa-factory').mkdir();(root/'qa-factory/config.json').write_text('{"schema_version":1,"protected_app_paths":["src"]}')
            event={'turn_id':'t','cwd':str(root),'tool_name':'apply_patch','tool_input':{'command':'*** Begin Patch\n*** Add File: src/app.py\n+x\n*** End Patch'}}
            command=wiring['hooks']['PreToolUse'][0]['hooks'][0][key].replace('${CLAUDE_PLUGIN_ROOT}',str(SCRIPTS.parent))
            result=self.run_native_command(command,event,root,env)
            self.assertEqual(result.returncode,2,result.stderr)

    def run_native_command(self,command,event,root,env):
        if os.name == 'nt':
            command=[shutil.which('pwsh') or shutil.which('powershell'),'-NoProfile','-Command',command]
        return subprocess.run(command,input=json.dumps(event),shell=os.name != 'nt',text=True,
            encoding='utf-8',capture_output=True,cwd=root,env=env,timeout=30)

    @unittest.skipUnless(os.name == 'nt', 'Windows host shell contract')
    def test_windows_hooks_start_in_powershell_and_preserve_stdin_exit(self):
        """One entry started for real under pwsh, in a path with spaces, for both exit codes:
        stdin arrives whole, Unicode survives, the argument list is the one the POSIX
        `command` states, and the exit code reaches the host. The other thirteen
        commandWindows lines are that same launcher with different arguments, compared as
        strings \u2014 see launcher_parts."""
        wiring=json.loads((SCRIPTS.parent/'hooks/codex.json').read_text(encoding='utf-8'))
        shell=shutil.which('pwsh') or shutil.which('powershell')
        self.assertIsNotNone(shell)
        entries=hook_entries(wiring)
        proven=entries[0][1]
        head,proven_args,suffix=launcher_parts(proven['commandWindows'])
        for name,hook in entries:
            line_head,args,line_suffix=launcher_parts(hook['commandWindows'])
            self.assertEqual((line_head,line_suffix),(head,suffix),(name,hook['commandWindows']))
            self.assertEqual(args,hook['command'].split(' telemetry_hook.py ',1)[1].split(),name)
        with tempfile.TemporaryDirectory(prefix='qa factory ') as tmp:
            root=Path(tmp);(root/'hooks').mkdir();(root/'scripts').mkdir()
            shutil.copyfile(SCRIPTS.parent/'hooks/run-py.cmd',root/'hooks/run-py.cmd')
            shutil.copyfile(SCRIPTS/'run_py_entry.py',root/'scripts/run_py_entry.py')
            (root/'scripts/telemetry_hook.py').write_text(
                'import json,sys\ne=json.load(sys.stdin)\nprint(json.dumps({"event":e,"args":sys.argv[1:]}))\nsys.exit(e.get("exit",0))\n')
            env=dict(os.environ,CLAUDE_PLUGIN_ROOT=str(root),QA_FACTORY_PYTHON=sys.executable)
            command=proven['commandWindows'].replace('${CLAUDE_PLUGIN_ROOT}',str(root))
            for code in (0,2):
                payload={'exit':code,'message':'Unicode and spaces: \u2713'}
                run=subprocess.run([shell,'-NoProfile','-Command',command],input=json.dumps(payload),
                    capture_output=True,text=True,encoding='utf-8',cwd=root,env=env,timeout=30)
                self.assertEqual(run.returncode,code,run.stderr)
                out=json.loads(run.stdout)
                self.assertEqual(out['event'],payload)
                self.assertEqual(out['args'],proven_args)

    def test_native_usage_capture_closes_activity_after_final_response_and_replays(self):
        from activity_capture import update
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);qf=root/'qa-factory';qf.mkdir();(qf/'config.json').write_text('{"schema_version":1}')
            path=root/'rollout.jsonl'
            records=[{'type':'session_meta','payload':{'id':'s','cli_version':'fixture'}},
                     {'type':'turn_context','payload':{'turn_id':'t','model':'gpt-5.6-terra'}},
                     {'type':'token_usage_record','timestamp':'2026-09-19T10:00:05Z','payload':{'thread_id':'s','turn_id':'t','response_id':'r','usage':{'input_tokens':100,'cached_input_tokens':40,'output_tokens':20,'total_tokens':120}}}]
            path.write_text(''.join(json.dumps(r)+'\n' for r in records),encoding='utf-8')
            activities=qf/'state/activities/s.json'
            doc=update(activities,'s','start','doctor',event_id='doctor-entry',timestamp='2026-09-19T10:00:00Z')
            doc['pending_close']={'type':'doctor','task':''};activities.write_text(json.dumps(doc))
            event={'turn_id':'t','session_id':'s','hook_event_name':'Stop','transcript_path':str(path)}
            result=self.run_hook(root,'cost_capture.py',event,True)
            self.assertEqual(result.returncode,0,result.stderr)
            out=qf/'state/cost/s.json';first=json.loads(out.read_text(encoding='utf-8'))
            self.assertEqual(len(first['requests']),1)
            self.assertEqual(list(first['by_activity'].values())[0]['type'],'doctor')
            self.assertEqual(json.loads(activities.read_text())['active_stack'],[])
            self.assertEqual(first['usage_completeness'],'provisional')
            result=self.run_hook(root,'cost_capture.py',event,True)
            second=json.loads(out.read_text(encoding='utf-8'))
            self.assertEqual(first['requests'],second['requests'])

    def test_patch_checks_source_destination_and_every_file(self):
        event=normalize({"tool_name":"apply_patch","cwd":str(SCRIPTS),"tool_input":{"command":
            "*** Begin Patch\n*** Update File: old.txt\n*** Move to: new.txt\n@@\n-old\n+new\n*** Delete File: gone.txt\n*** Add File: added.txt\n+data\n*** End Patch"}})
        ops=mutation_events(event)
        self.assertEqual([Path(o['tool_input']['file_path']).name for o in ops],['old.txt','new.txt','gone.txt','added.txt'])
        with self.assertRaises(ValueError): mutation_events(normalize(dict(event,tool_input={'command':'unknown patch'})))

    def test_dispatch_rewrite_preserves_native_schema(self):
        event=normalize({'tool_name':'spawn_agent','tool_input':{'agent_type':'qa-scout','message':'QA-1','fork_context':False}})
        self.assertEqual(event['tool_input']['subagent_type'],'qa-scout')
        result=rewritten_input(event,dict(event['tool_input'],prompt='QA-1 plus context'))
        self.assertEqual(result,{'agent_type':'qa-scout','message':'QA-1 plus context','fork_context':False})

    def test_desktop_spawn_records_host_dispatch_from_task_name(self):
        """A Codex collaboration spawn must bind its running controller dispatch."""
        import hooklib, host_dispatch
        with tempfile.TemporaryDirectory() as tmp, hooklib.selftest_root_restored():
            root=Path(tmp); qf=root/'qa-factory'; (qf/'state').mkdir(parents=True)
            (qf/'config.json').write_text('{"schema_version":1}')
            state=qf/'artifacts'/'TP2-2406'/'state'; state.mkdir(parents=True)
            (state.parent/'pipeline.json').write_text(json.dumps({'ticket':'TP2-2406'}))
            (state/'controller.json').write_text(json.dumps({'dispatches':{
                'S7-qa-failure-analyst-4':{'id':'S7-qa-failure-analyst-4',
                    'role':'qa-failure-analyst','status':'running'}}}))
            hooklib.pin_project_root(root)
            event=normalize({'tool_name':'collaboration.spawn_agent','cwd':str(root),
                'session_id':'parent','tool_use_id':'spawn-4','tool_input':{
                    'task_name':'qa_failure_analyst__tp2_2406_s7_4','message':'opaque'},
                'tool_response':{'task_path':'/root/qa_failure_analyst__tp2_2406_s7_4'}})
            host_dispatch.record(event)
            receipts=list((qf/'state/host-dispatches').glob('*.json'))
            self.assertEqual(len(receipts),1)
            receipt=json.loads(receipts[0].read_text())
            self.assertEqual((receipt['agent_type'],receipt['task_id'],receipt['dispatch_id']),
                             ('qa-failure-analyst','TP2-2406','S7-qa-failure-analyst-4'))

    def test_receipt_carries_its_launch_time_and_nothing_rewrites_it(self):
        """`bound_at` is set once, when the receipt is created. The file's own mtime is the
        last write, so a rebind, the SubagentStop mark or an enrich made every receipt look
        fresh; liveness needs the launch."""
        import hooklib, host_dispatch
        with tempfile.TemporaryDirectory() as tmp, hooklib.selftest_root_restored():
            root=Path(tmp); qf=root/'qa-factory'; (qf/'state').mkdir(parents=True)
            (qf/'config.json').write_text('{"schema_version":1}')
            state=qf/'artifacts'/'TP2-2406'/'state'; state.mkdir(parents=True)
            (state.parent/'pipeline.json').write_text(json.dumps({'ticket':'TP2-2406'}))
            (state/'controller.json').write_text(json.dumps({'dispatches':{
                'S7-qa-failure-analyst-4':{'id':'S7-qa-failure-analyst-4',
                    'role':'qa-failure-analyst','status':'running'}}}))
            hooklib.pin_project_root(root)
            event=normalize({'tool_name':'collaboration.spawn_agent','cwd':str(root),
                'session_id':'parent','tool_use_id':'spawn-4','tool_input':{
                    'task_name':'qa_failure_analyst__tp2_2406_s7_4','message':'opaque'},
                'tool_response':{'task_path':'/root/qa_failure_analyst__tp2_2406_s7_4'}})
            before=time.time()
            host_dispatch.record(event)
            after=time.time()
            path=host_dispatch.binding_path(root,'/root/qa_failure_analyst__tp2_2406_s7_4')
            receipt=json.loads(path.read_text())
            self.assertIsInstance(receipt['bound_at'],float)
            self.assertTrue(before<=receipt['bound_at']<=after,(before,receipt['bound_at'],after))
            self.assertEqual((receipt['agent_type'],receipt['status'],receipt['host']),
                             ('qa-failure-analyst','running','codex'))   # the shape keeps every key
            # A sentinel in the file: a refresh by any later writer would replace it.
            sentinel=12345.5
            path.write_text(json.dumps(dict(receipt,bound_at=sentinel)))
            host_dispatch.record(event)   # the same launch seen again: the path-only rebind
            rebound=json.loads(path.read_text())
            self.assertEqual(rebound['bound_at'],sentinel)
            host_dispatch.enrich(dict(event,agent_id=receipt['agent_id']))
            self.assertEqual(json.loads(path.read_text())['bound_at'],sentinel)
            host_dispatch.record({'hook_event_name':'SubagentStop','session_id':'parent',
                'agent_id':receipt['agent_id'],'_exit_gate_released':True,'cwd':str(root)})
            stopped=json.loads(path.read_text())
            self.assertEqual((stopped['status'],stopped['terminal_source']),('terminal','SubagentStop'))
            self.assertEqual(stopped['bound_at'],sentinel)
            # A receipt written before this change has none, and nothing gives it one.
            old={k:v for k,v in receipt.items() if k!='bound_at'}
            path.write_text(json.dumps(old))
            host_dispatch.record(event)
            host_dispatch.record({'hook_event_name':'SubagentStop','session_id':'parent',
                'agent_id':receipt['agent_id'],'_exit_gate_released':True,'cwd':str(root)})
            self.assertNotIn('bound_at',json.loads(path.read_text()))

    def test_probe_task_name_may_carry_a_unique_suffix_and_nothing_else_is_a_probe(self):
        """A consumed task name cannot be reused, so a second context probe after a fix
        needs a fresh name. The identity is PROBE_TASK, or PROBE_TASK + '__' + a non-empty
        suffix (the same __suffix convention a story's task name uses). A single underscore,
        an empty suffix, another prefix and no name at all are not probes: one predicate,
        native_context.is_probe_task, serves native_role and diagnostic alike."""
        from native_context import PROBE_TASK, diagnostic, is_probe_task
        from host_adapter import native_role
        probes=[PROBE_TASK,PROBE_TASK+'__2',PROBE_TASK+'__retry_after_fix',PROBE_TASK+'___x']
        others=[PROBE_TASK+'_x',PROBE_TASK+'_',PROBE_TASK+'__','x_'+PROBE_TASK+'__2',
                'x'+PROBE_TASK,PROBE_TASK+'x','',None]
        for name in probes:
            self.assertEqual(native_role(name),'qa-scout',name)
            self.assertTrue(is_probe_task(name),name)
            self.assertTrue(diagnostic({'_qa_host':{'input':{'task_name':name}}}),name)
        for name in others:
            self.assertNotEqual(native_role(name),'qa-scout',name)
            self.assertEqual(native_role(name),str(name or ''),name)
            self.assertFalse(is_probe_task(name),name)
            self.assertFalse(diagnostic({'_qa_host':{'input':{'task_name':name}}}),name)
        # The desktop spawn path reaches the same answer through normalize().
        event=normalize({'tool_name':'collaboration.spawn_agent','turn_id':'t','tool_input':{
            'task_name':PROBE_TASK+'__2','message':'opaque'}})
        self.assertEqual(event['tool_input']['subagent_type'],'qa-scout')
        self.assertTrue(diagnostic(event))
        # A production role name keeps its strict mapping.
        self.assertEqual(native_role('qa_scout__qa_1'),'qa-scout')
        self.assertFalse(diagnostic({'_qa_host':{'input':{'task_name':'qa_scout__qa_1'}}}))
        self.assertEqual(native_role('qa_unknown_role__qa_1'),'qa_unknown_role__qa_1')

    def test_every_native_launch_keeps_its_own_packet(self):
        """One packet slot per host session could not tell a stale packet (a failed launch
        emits no SubagentStart) from a LIVE one, so "replace" handed a running child the
        context of another story. Each named launch now has its own packet, keyed by
        (session, raw task_name); only a re-stage of the SAME launch is refused, and an
        existing packet is never overwritten by a different launch."""
        import native_context
        from event_store import StateConflict
        def launch(session,use,name,probe=False):
            event={'session_id':session,'tool_use_id':use,'transcript_path':'t-'+use}
            if name is not None:event['_qa_host']={'input':{'task_name':name}}
            if probe:event['tool_input']={'prompt':'QA_FACTORY_CONTEXT_PROBE'}
            return event
        def files(root):
            return sorted((Path(root)/'qa-factory/state/native-context').glob('*.json'))
        keys=('status','role','context','session_id','tool_use_id','transcript_path','task_id','task_name','diagnostic')
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            native_context.stage(root,launch('s','u1','qa_scout__qa_1',probe=True),'qa-scout','first','QA-1')
            (first,)=files(root);before=first.read_bytes()
            # The file name carries the session first, so one session's packets are found by prefix.
            import hashlib
            key=hashlib.sha256(b's').hexdigest()[:32]
            self.assertEqual(first.name,key+'-'+hashlib.sha256(b'qa_scout__qa_1').hexdigest()[:32]+'.json')
            with self.assertRaises(StateConflict):   # the same launch staged twice
                native_context.stage(root,launch('s','u1','qa_scout__qa_1'),'qa-scout','same','QA-1')
            self.assertEqual(first.read_bytes(),before)
            # A different task of the same session gets its own file; the first is untouched.
            native_context.stage(root,launch('s','u2','qa_scout__qa_2'),'qa-reviewer','later','QA-2')
            self.assertEqual(len(files(root)),2)
            self.assertEqual(first.read_bytes(),before)
            self.assertEqual(native_context.pending_path(root,'s','qa_scout__qa_1'),first)
            packet=json.loads(native_context.pending_path(root,'s','qa_scout__qa_2').read_text(encoding='utf-8'))
            self.assertEqual({k:packet[k] for k in keys},
                {'status':'pending','role':'qa-reviewer','context':'later','session_id':'s','tool_use_id':'u2',
                 'transcript_path':'t-u2','task_id':'QA-2','task_name':'qa_scout__qa_2','diagnostic':False})
            # An unnamed launch keeps the session-only key, whatever named launches exist.
            native_context.stage(root,launch('s','u3',None),'qa-scout','plain','QA-3')
            self.assertEqual(len(files(root)),3)
            self.assertEqual(native_context.pending_path(root,'s').name,key+'.json')   # as at HEAD
            for name in (None,''):                  # two unnamed launches are the same key
                with self.assertRaises(StateConflict):
                    native_context.stage(root,launch('s','u4',name),'qa-scout','second','QA-4')
            self.assertEqual(json.loads(native_context.pending_path(root,'s').read_text(encoding='utf-8'))['context'],'plain')
            self.assertEqual(first.read_bytes(),before)
            # Another session is another key, and a foreign unreadable file is skipped, not met.
            (files(root)[0].parent/'junk.json').write_text('{not json',encoding='utf-8')
            (files(root)[0].parent/'list.json').write_text('[]',encoding='utf-8')
            native_context.stage(root,launch('t','u5','qa_scout__qa_1'),'qa-scout','other session','QA-5')
            self.assertEqual(len(files(root)),6)
        with tempfile.TemporaryDirectory() as tmp:
            # A pending packet of the SAME key that cannot be read keeps the behaviour it
            # always had: the parse error reaches the caller (inject_context turns a
            # ValueError into exit 2) and the file is left as it was.
            root=Path(tmp)
            path=native_context.pending_path(root,'s','qa_scout__qa_1');path.parent.mkdir(parents=True)
            path.write_text('{not json',encoding='utf-8')
            with self.assertRaises(ValueError):
                native_context.stage(root,launch('s','u1','qa_scout__qa_1'),'qa-scout','first','QA-1')
            self.assertEqual(path.read_text(encoding='utf-8'),'{not json')

    def test_subagent_start_delivers_each_child_the_packet_of_its_own_launch(self):
        import contextlib, hashlib, io, hooklib, native_context
        from unittest.mock import patch
        from host_dispatch import binding_path
        from native_context import stage, deliver
        with tempfile.TemporaryDirectory() as tmp, hooklib.selftest_root_restored():
            root=Path(tmp);qf=root/'qa-factory';(qf/'state').mkdir(parents=True)
            (qf/'config.json').write_text('{"schema_version":1}')
            for ticket in ('STORY-A','STORY-B'):
                d=qf/'artifacts'/ticket;d.mkdir(parents=True)
                (d/'pipeline.json').write_text(json.dumps({'ticket':ticket,'stages':{'S1':{'status':'running'}}}))
            hooklib.pin_project_root(root)
            def launch(use,name):
                return normalize({'host':'codex','tool_name':'collaboration.spawn_agent','session_id':'parent',
                    'tool_use_id':use,'tool_input':{'task_name':name,'message':'opaque'}})
            def start(child,name=None,role='qa-scout'):
                event={'host':'codex','hook_event_name':'SubagentStart','session_id':'parent',
                       'agent_id':child,'agent_type':role}
                if name:   # the child's own transcript says which task it is, as the host writes it
                    transcript=root/(child+'.jsonl')
                    transcript.write_text(json.dumps({'type':'session_meta','payload':{
                        'id':child,'agent_path':'/root/'+name,'parent_thread_id':'parent'}})+'\n')
                    event['agent_transcript_path']=str(transcript)
                return event
            seen={}
            def run(event):
                with contextlib.redirect_stdout(io.StringIO()) as out, contextlib.redirect_stderr(io.StringIO()) as err:
                    deliver(root,event)
                text=out.getvalue();seen['err']=err.getvalue()
                return json.loads(text)['hookSpecificOutput']['additionalContext'] if text else ''
            def packets():
                return {p:p.read_bytes() for p in (qf/'state/native-context').glob('*.json')}
            a,b='qa_scout__story_a','qa_scout__story_b'
            # (i) two launches in flight: each child gets its own context, bound to its own ticket.
            stage(root,launch('ua',a),'qa-scout','context A','STORY-A')
            stage(root,launch('ub',b),'qa-scout','context B','STORY-B')
            self.assertEqual(run(start('child-a',a)),'context A')
            self.assertEqual(json.loads(binding_path(root,'child-a').read_text())['task_id'],'STORY-A')
            self.assertEqual(run(start('child-b',b)),'context B')
            self.assertEqual(json.loads(binding_path(root,'child-b').read_text())['task_id'],'STORY-B')
            self.assertEqual({json.loads(v)['status'] for v in packets().values()},{'delivered'})
            self.assertEqual(seen['err'],'')   # a clean delivery says nothing on stderr
            # A delivered packet is only a record: the context (up to 100 KB) is not kept,
            # the identities are.
            for value in packets().values():
                kept=json.loads(value)
                self.assertNotIn('context',kept)
                self.assertEqual((kept['role'],kept['status']),('qa-scout','delivered'))
                self.assertIn(kept['task_name'],(a,b))
                self.assertEqual(kept['task_id'],'STORY-A' if kept['task_name']==a else 'STORY-B')
            # (ii) a launch that failed (never started) stays pending and untouched.
            shutil.rmtree(qf/'state/native-context');shutil.rmtree(qf/'state/host-dispatches')
            stage(root,launch('ua',a),'qa-scout','context A','STORY-A')
            stage(root,launch('ub',b),'qa-scout','context B','STORY-B')
            stale=[p for p,v in packets().items() if json.loads(v)['task_name']==a][0]
            stale_bytes=stale.read_bytes()
            self.assertEqual(run(start('child-b',b)),'context B')
            self.assertEqual(stale.read_bytes(),stale_bytes)
            self.assertEqual(json.loads(stale_bytes)['status'],'pending')
            # A child whose task name is known but matches no packet never gets a named one.
            self.assertEqual(run(start('child-c','qa_scout__story_c')),'')
            self.assertEqual(stale.read_bytes(),stale_bytes)
            self.assertEqual(seen['err'],'')   # no candidate at all: silent, as before
            # (v) no child identity and two pending packets of one role: ambiguous, nothing moves,
            # and the starved child is told why, on stderr only, naming tasks and never contexts.
            shutil.rmtree(qf/'state/native-context')
            stage(root,launch('ua',a),'qa-scout','context A','STORY-A')
            stage(root,launch('ub',b),'qa-scout','context B','STORY-B')
            before=packets()
            self.assertEqual(run(start('child-x')),'')
            self.assertEqual(packets(),before)
            message=seen['err']
            self.assertEqual(len(message.strip().splitlines()),1,message)
            for fact in ('qa-scout',a,b,'several','no context was delivered','unique task name'):
                self.assertIn(fact,message)
            for secret in ('context A','context B'):
                self.assertNotIn(secret,message)
            # (vi) exactly one role match and no identity: delivered, as with one launch in flight.
            (qf/'state/native-context').joinpath(native_context.pending_path(root,'parent',b).name).unlink()
            self.assertEqual(run(start('child-y')),'context A')
            self.assertEqual(seen['err'],'')
            # (vii) wrong role and no name: nothing.
            shutil.rmtree(qf/'state/native-context')
            stage(root,{'host':'codex','session_id':'parent','tool_use_id':'uz'},'qa-scout','plain','STORY-A')
            self.assertEqual(run(start('child-w',role='qa-reviewer')),'')
            self.assertEqual(seen['err'],'')
            # A packet with no task name is still delivered to a named child of its own role...
            self.assertEqual(run(start('child-v',a)),'plain')
            # ...and an unreadable file of this session is skipped, not met.
            prefix=hashlib.sha256(b'parent').hexdigest()[:32]
            (qf/'state/native-context'/(prefix+'-junk.json')).write_text('{not json')
            stage(root,launch('ub',b),'qa-scout','context B','STORY-B')
            self.assertEqual(run(start('child-u',b)),'context B')
            # Files of OTHER sessions are not even opened by a delivery: the folder is never
            # emptied, so every SubagentStart would otherwise parse every session's packets.
            other=dict(launch('uo','qa_scout__story_o'),session_id='other')
            stage(root,other,'qa-scout','context O','STORY-A')
            foreign=native_context.pending_path(root,'other','qa_scout__story_o')
            (qf/'state/native-context/stray.json').write_text('{not json')
            stage(root,launch('ua2',a),'qa-scout','context A2','STORY-A')
            opened=[];real=Path.read_text
            def spy(self,*args,**kwargs):
                opened.append(self.name);return real(self,*args,**kwargs)
            with patch.object(Path,'read_text',spy):
                self.assertEqual(run(start('child-t',a)),'context A2')
            self.assertTrue(foreign.is_file())
            self.assertNotIn(foreign.name,opened)
            self.assertNotIn('stray.json',opened)

    def test_desktop_spawn_is_identified_by_its_task_name_alone(self):
        """Codex 0.155.1 desktop passes `task_name`, `fork_turns` and an OPAQUE encrypted
        `message` (TP2-2556, 23.09): the ticket is unreadable from the dispatch text
        in principle, and the slug in the task name is the only carrier left. With a stale
        story also `running`, the "single running story" fallback refused four dispatches
        the controller had already accepted, and the refusal named none of this."""
        import hooklib, stage_guard
        opaque='gAAAAABo'+'x'*64
        event=normalize({'tool_name':'collaboration.spawn_agent','turn_id':'t','tool_input':{
            'task_name':'qa_automator__tp2_2556_s5_11','fork_turns':'none','message':opaque}})
        self.assertEqual(event['tool_input']['subagent_type'],'qa-automator')
        self.assertEqual(event['_qa_host']['input']['message'],opaque)
        with tempfile.TemporaryDirectory() as tmp, hooklib.selftest_root_restored():
            root=Path(tmp);qf=root/'qa-factory';(qf/'state').mkdir(parents=True)
            (qf/'config.json').write_text('{"schema_version":1}')
            for name in ('TP2-2534','TP2-2556','TP2-2599'):
                d=qf/'artifacts'/name;d.mkdir(parents=True)
                (d/'pipeline.json').write_text(json.dumps({'ticket':name,'stages':{'S1':{'status':'running'}}}))
            hooklib.pin_project_root(root)
            self.assertEqual(stage_guard.requested_ticket(event),'TP2-2556')
            shutil.rmtree(qf/'artifacts/TP2-2556')
            self.assertEqual(stage_guard.requested_ticket(event),'')
            self.assertEqual(stage_guard.check(event),2)
            message=stage_guard.LAST_DENIAL['message']
            self.assertTrue(message.startswith('task identity is missing or ambiguous'),message)
            for fact in (str((qf/'artifacts').resolve()),'qa_automator__tp2_2556_s5_11',
                         'TP2-2534','QA_FACTORY_TASK'):
                self.assertIn(fact,message)

    def run_hook(self,root,script,event,wrapped=False):
        command=[sys.executable,str(SCRIPTS/'telemetry_hook.py'),script] if wrapped else [sys.executable,str(SCRIPTS/script)]
        env=dict(os.environ,CLAUDE_PROJECT_DIR=str(root))
        return subprocess.run(command,cwd=root,input=json.dumps(dict(event,cwd=str(root))),text=True,
                              capture_output=True,encoding='utf-8',env=env,timeout=30)

    def test_native_guard_and_multi_file_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); (root/'qa-factory').mkdir();(root/'src').mkdir()
            (root/'qa-factory/config.json').write_text(json.dumps({'schema_version':1,'protected_app_paths':['src']}))
            e={'turn_id':'t','tool_name':'apply_patch','tool_input':{'command':'*** Begin Patch\n*** Add File: safe.txt\n+ok\n*** Add File: src/app.py\n+bad\n*** End Patch'}}
            result=self.run_hook(root,'guard_pre_tool.py',e)
            self.assertEqual(result.returncode,2,result.stderr)
            self.assertIn('APP-UNDER-TEST',result.stderr)
            task=root/'qa-factory/artifacts/QA-1';task.mkdir(parents=True)
            (task/'triage.json').write_text('{}')
            e['tool_input']['command']='*** Begin Patch\n*** Add File: safe.txt\n+ok\n*** Add File: qa-factory/artifacts/QA-1/triage.json\n+{}\n*** End Patch'
            result=self.run_hook(root,'validate_artifacts.py',e)
            self.assertEqual(result.returncode,2,result.stderr)
            self.assertIn('triage',result.stderr)
            result=self.run_hook(root,'precompact_guard.py',{'turn_id':'t','session_id':'s','hook_event_name':'PreCompact'},True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertIn('COMPACT GUARD',json.loads(result.stdout)['systemMessage'])

    def test_native_usage_no_cache_reasoning_or_notification_duplication(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'rollout.jsonl'
            rows=[{'type':'session_meta','payload':{'id':'s','cli_version':'fixture'}},
                  {'type':'turn_context','payload':{'turn_id':'t','model':'gpt-test'}},
                  {'type':'token_usage_record','timestamp':'2026-09-19T10:00:00Z','payload':{
                      'thread_id':'s','turn_id':'t','response_id':'r1','usage':{'input_tokens':100,'cached_input_tokens':60,
                      'output_tokens':20,'reasoning_output_tokens':10,'total_tokens':120}}},
                  {'type':'event_msg','payload':{'type':'token_count','info':{'last_token_usage':{'input_tokens':100}}}}]
            rows.append(rows[2])
            path.write_text(''.join(json.dumps(r)+'\n' for r in rows),encoding='utf-8')
            usage,*_,receipt=scan(path)
            self.assertEqual(len(usage),1)
            self.assertEqual(usage['r1'][0],'gpt-test')
            self.assertEqual(usage['r1'][1],{'input_tokens':40,'cache_read_input_tokens':60,'output_tokens':20})
            self.assertEqual(receipt['status'],'recorded')

if __name__=='__main__': unittest.main()
