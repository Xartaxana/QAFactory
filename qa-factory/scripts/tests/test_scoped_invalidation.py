"""A changed source invalidates only affected evidence and never erases missing work."""
import sys,json,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from event_store import EventStore, StateConflict
from controller import projection
import finalize_task as F
import contract as C

def write(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(data),encoding="utf-8")

class InvalidationTests(unittest.TestCase):
    def test_partial_batch_invalidation_and_repair(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            manifest={"tests":[{"instance_id":"i1","case":"TC-1"},{"instance_id":"i2","case":"TC-2"}]}
            write(root / "work/automation-manifest.json",manifest)
            before={"block_id":"initial","dispatch_id":"author","attempt_started_at":"2026-09-17T10:00:00Z","results":[{"instance_id":"i1","status":"passed"},{"instance_id":"i2","status":"passed"}],"manual_checks":[{"case":"TC-1","result":"passed"}]}
            block=root / "work/run-blocks/initial.json"
            write(block,before)
            original=block.read_bytes()
            EventStore(root).commit("invalidate",{"dispatch_ids":["author"],"affected_scope":["TC-1"]},"invalidate")
            F.refresh(root)
            report=C.load_json(root / "work/run-report.json")
            current=C.current_instance_results(report)
            self.assertEqual(current["i1"]["status"],"not_run")
            self.assertEqual(current["i2"]["status"],"passed")
            self.assertEqual(report["current_manual_checks"][0]["result"],"inconclusive")
            self.assertEqual(report["execution_status"],"not_executed")
            self.assertEqual(original,block.read_bytes())
            write(root / "work/run-blocks/repair.json",{"block_id":"repair","dispatch_id":"repair","attempt_started_at":"2026-09-17T11:00:00Z","results":[{"instance_id":"i1","status":"passed"}],"manual_checks":[{"case":"TC-1","result":"passed"}]})
            F.refresh(root)
            report=C.load_json(root / "work/run-report.json")
            self.assertEqual(report["execution_status"],"passed")
            self.assertEqual(len(report["results"]),3)
            self.assertEqual(C.current_instance_results(report)["i2"]["status"],"passed")

    def test_corrupt_journal_cannot_be_treated_as_fresh(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            store=EventStore(root)
            store.commit("invalidate",{"dispatch_ids":[],"affected_scope":[]},"i")
            store.log.write_text("invalid\n",encoding="utf-8")
            with self.assertRaises(StateConflict):
                F.refresh(root)
            self.assertEqual(C.load_json(root / "work/finalization-receipt.json")["status"],"incomplete")

    def test_invalidated_window_reopens_stage_and_source_gate(self):
        entries=[("initialize",{"source_revision":"old","scope":["A","B"]}),
                 ("dispatch",{"id":"a","stage":"S5","scope":["A"]}),
                 ("accept",{"id":"a","status":"accepted","stage_complete":False}),
                 ("dispatch",{"id":"b","stage":"S5","scope":["B"]}),
                 ("accept",{"id":"b","status":"accepted","stage_complete":True}),
                 ("decision",{"id":"gate","gate":"A","status":"approved","source_revision":"old"}),
                 ("invalidate",{"dispatch_ids":["a"],"affected_scope":["A"],"source_revision":"new"})]
        state=projection([{"sequence":n,"type":kind,"payload":payload} for n,(kind,payload) in enumerate(entries,1)])
        self.assertEqual(state["stages"]["S5"]["status"],"pending")
        self.assertEqual(state["dispatches"]["b"]["status"],"accepted")
        self.assertEqual(state["decisions"]["gate"]["status"],"stale")

if __name__ == "__main__": unittest.main()
