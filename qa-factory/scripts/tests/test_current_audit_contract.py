"""Current-stage audit obligations and platform-independent prompt caps."""
import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import audit_factory as A
import selftest as S


class AuditContractTests(unittest.TestCase):
    def test_s8_never_requires_retired_board_or_future_s9(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);task=root/'artifacts/T';(task/'work/run-blocks').mkdir(parents=True)
            (task/'pipeline.json').write_text(json.dumps({'stages':{'S6':{'status':'done'},'S8':{'status':'done'}}}))
            (task/'test-report.md').write_text('# Report')
            (task/'work/run-blocks/one.json').write_text('{}')
            (task/'work/run-report.json').write_text(json.dumps({'reducer':{'sources':[{'source':'run-blocks/one.json'}]}}))
            with patch.object(A,'artifact_root',return_value=root/'artifacts'),patch.object(A,'state_dir',return_value=root),patch.object(A,'FINDINGS',[]),contextlib.redirect_stdout(io.StringIO()):
                A.a18_board_runs_row();A.a15_estimation_loop()
                self.assertEqual(A.FINDINGS,[])
                (task/'work/run-report.json').write_text('{}')
                A.a18_board_runs_row()
                self.assertTrue(A.FINDINGS)

    def test_both_limit_consumers_normalize_crlf(self):
        """The same charter measured the same, CRLF or LF, by both consumers - and a charter
        over the old per-file cap is a NOTE in both, never a violation (P7.1): the charter is
        the lightest of the three layers a dispatch pays for, and A25 is what bounds their sum.
        A per-file cap on the lightest layer is how a one-line rule for all twelve roles came
        to have nowhere to go."""
        original=(Path(__file__).resolve().parents[2]/'agents/qa-scout.md').read_bytes().replace(b'\r\n',b'\n')
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);(root/'agents').mkdir();(root/'references').mkdir()
            (root/'references/stages.json').write_text('{"stages":[],"witness":{}}')
            # cmd_limits also reads the role-rules register: this tree keeps one with no rows
            (root/'design').mkdir();(root/'design/role-rules.json').write_text('{"schema_version":1,"rows":[]}')
            role=root/'agents/qa-scout.md'
            for size in (8999,9000,9500):
                # the real charter has outgrown the small sizes: keep whole lines up to `size`, pad the rest
                kept=b''
                for line in original.splitlines(keepends=True):
                    if len(kept)+len(line)>size:
                        break
                    kept+=line
                payload=kept+b' '*(size-len(kept))
                seen=set()
                for crlf in (False,True):
                    role.write_bytes(payload.replace(b'\n',b'\r\n') if crlf else payload)
                    with patch.object(S,'PLUGIN_ROOT',root),patch.object(S,'RESULTS',[]),contextlib.redirect_stdout(io.StringIO()) as out:
                        self.assertTrue(S.cmd_limits())          # never failed by the charter
                        seen.add(''.join(l for l in out.getvalue().splitlines()
                                         if 'qa-scout.md' in l))
                    with patch.object(A,'PLUGIN_ROOT',root),patch.object(A,'FINDINGS',[]),contextlib.redirect_stdout(io.StringIO()) as out:
                        A.a19_agents_contract()
                        self.assertEqual([f for f in A.FINDINGS if 'bytes' in str(f)],[])
                        note='qa-scout.md: %d bytes' % size
                        self.assertEqual(note in out.getvalue(),size>9000)
                # CRLF or LF, the byte count both consumers print is the same one.
                self.assertEqual(len(seen),1,seen)

    def test_one_table_decides_a_test_files_timeout(self):
        """FR-31: ONE place decides how long a test file may run - `TEST_TIMEOUTS`, read by
        `_test_outcome`; a file that is not listed there gets 300 s whether or not it is
        registered in SLOW_TESTS (that registration only keeps it out of the fast tier). A file
        over its ceiling is red ("timed out"), never given a bigger ceiling by a second table.
        The timeout `_test_outcome` hands to run_subprocess is what is pinned here."""
        seen={}
        def fake(args,cwd=None,env=None,timeout=300):
            seen[Path(args[0]).name]=timeout
            return types.SimpleNamespace(returncode=0,stdout='=== x: 1/1 ok ===',stderr='')
        tests=Path(S.TESTS_DIR)
        names=('test_infra_failure.py','test_words_doors.py','test_story_run_words.py','test_audit_rules.py',
               'test_story_run_s7_live.py','test_no_move_seam.py','test_story_run_refusals.py')
        with patch.object(S,'run_subprocess',fake):
            for name in names:
                S._test_outcome(tests/name)
        for name in names:
            self.assertEqual(seen[name],S.TEST_TIMEOUTS.get(name,300),name)
        self.assertEqual(seen['test_infra_failure.py'],600)   # a row that exists upstream
        self.assertEqual(seen['test_audit_rules.py'],300)
        for name in ('test_story_run_s7_live.py','test_no_move_seam.py','test_story_run_refusals.py'):
            self.assertEqual(seen[name],600,name)             # t-2202: slow files that timed out or neared 300 s on a loaded runner
        self.assertFalse(hasattr(S,'SLOW_TEST_TIMEOUT_S'))    # no second table
        self.assertTrue({'test_words_doors.py','test_story_run_words.py'}<=set(S.slow_tests()["files"]))
        # the two files this wave deletes hold no registration
        self.assertFalse({'test_story_run.py','test_reporter_limited_window.py'}&set(S.slow_tests()["files"]))

        def hang(args,cwd=None,env=None,timeout=300):
            raise subprocess.TimeoutExpired(args,timeout)
        with patch.object(S,'run_subprocess',hang):
            _,ok,detail,_=S._test_outcome(tests/'test_audit_rules.py')
        self.assertFalse(ok)
        self.assertIn('timed out after 300s',detail)

    def test_the_cli_script_list_is_the_union_of_both_sides(self):
        """CLI_SCRIPTS keeps what the migration registered (the report-row reader and the
        launcher's entry) next to what the upstream release registered, and holds no row for
        a script this wave deletes."""
        for name in ('reporters','run_py_entry','gate_registry','proof_level','report_facts','manual_evidence','probe_by_code'):
            self.assertIn(name,A.CLI_SCRIPTS,name)
        self.assertNotIn('gap_decisions',A.CLI_SCRIPTS)


if __name__=='__main__':unittest.main()
