"""Evidence cohorts, history gaps and a real snapshot CLI projection."""
import json
from datetime import datetime,timezone
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from metrics_projection import compute
from bug_snapshot import validate


class EvidenceMetrics(unittest.TestCase):
    def metrics(self,data):
        return {r['id']:r for r in compute(data,datetime(2026,9,18,tzinfo=timezone.utc))}

    def test_original_fingerprint_cohort_and_repairs(self):
        rows=[dict(task='T',repo_id='app',profile_id='api',instance_id=str(i),fingerprint='v1',purpose='initial',
                   started_at='2026-09-16T00:00:00Z',status=s,equivalence_verified=True) for i,s in enumerate(['pass','fail','pass','fail'])]
        rows.append(dict(rows[1],purpose='flaky_diagnostic',status='pass',started_at='2026-09-17T00:00:00Z'))
        m=self.metrics({'attempts':rows,'attempt_history_known':True})
        self.assertEqual(m['A01']['value'],50)
        self.assertEqual(m['A03']['value'],25)
        self.assertEqual(m['A04']['value'],50)
        rows.append(dict(rows[3],purpose='repair_verify',status='pass',fingerprint='v2',started_at='2026-09-17T00:00:00Z'))
        self.assertEqual(self.metrics({'attempts':rows,'attempt_history_known':True})['A03']['numerator'],1)

    def test_history_median_and_unknown_dates(self):
        bugs=[dict(id=str(i),status='Fixed',severity='major',area='A',priority='P1',created_at='2026-09-01',
                   history_complete_since='2026-08-01',transitions=[{'from':'Open','to':'Fixed','at':f'2026-09-{1+n:02}','evidence_ref':'tracker'}])
              for i,n in enumerate([1,3,8])]
        bugs.append(dict(id='rejected',status='Rejected',severity='minor',created_at='2026-09-01',history_complete_since='2026-08-01',transitions=[]))
        m=self.metrics({'bugs_known':True,'bugs':bugs})
        self.assertEqual(m['T11']['value'],25)
        self.assertEqual(m['T13']['value'],3)
        bugs[0].pop('history_complete_since')
        self.assertEqual(self.metrics({'bugs_known':True,'bugs':bugs})['T13']['status'],'unavailable')

    def test_snapshot_cli_and_validation(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);(root/'qa-factory').mkdir();(root/'qa-factory/config.json').write_text('{}')
            value={'schema_version':1,'as_of':'2026-09-18','scope':'exported ticket bugs','evidence_refs':['tracker export'],'bugs':[]}
            file=root/'snapshot.json';file.write_text(json.dumps(value))
            result=subprocess.run([sys.executable,str(Path(__file__).resolve().parents[1]/'bug_snapshot.py'),'--root',str(root),'--input',str(file)],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertTrue((root/'qa-factory/state/metrics.json').is_file())
            value['bugs']=[{'id':'a'},{'id':'a'}]
            with self.assertRaises(ValueError):validate(value)


if __name__=='__main__':unittest.main()
