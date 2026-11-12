"""A pending shell result is not a failed install; terminal smoke evidence survives it."""
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from install_smoke import run_report


class SmokeReport(unittest.TestCase):
    def test_report_distinguishes_pending_pass_fail_and_crash(self):
        for outcome in ('pass', 'fail', 'missing-injection', 'crash'):
            with self.subTest(outcome=outcome), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / 'report.json'
                def smoke():
                    pending = json.loads(path.read_text())
                    self.assertEqual(pending['status'], 'running')
                    self.assertIsNone(pending['exit_code'])
                    print('PLUGIN: qa-factory fixture')
                    if outcome == 'crash': raise RuntimeError('fixture interrupted')
                    if outcome != 'missing-injection':
                        for role in ('qa-factory:qa-scout', 'qa-scout'):
                            print(f"PASS injection delivers to '{role}'")
                    if outcome == 'fail': print('FAIL fixture check')
                    raise SystemExit(0 if outcome != 'fail' else 1)
                with patch('install_smoke.main', side_effect=smoke), contextlib.redirect_stdout(io.StringIO()):
                    with self.assertRaises((SystemExit, RuntimeError)):
                        run_report(path)
                saved = json.loads(path.read_text())
                self.assertEqual(saved['status'], 'passed' if outcome == 'pass' else 'failed')
                self.assertEqual(saved['plugin_line'], 'PLUGIN: qa-factory fixture')
                self.assertIn('completed_at', saved)
                if outcome == 'crash': self.assertIn('fixture interrupted', saved['error'])
                if outcome == 'fail': self.assertEqual(saved['failures'], ['FAIL fixture check'])


if __name__ == '__main__':
    unittest.main()
