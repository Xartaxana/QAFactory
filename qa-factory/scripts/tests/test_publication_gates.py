"""After-A descriptions and after-B actions have independent, exact authorization."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import external_writes as E
from event_store import content_hash


class GateTests(unittest.TestCase):
    def test_gate_a_binds_manifest_content_and_target(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            (root / "work").mkdir()
            fields={"title":"approved"}
            proposal={"kind":"case","publication_key":"key","action":"create","case_version":"cv", "fields":fields}
            manifest={"content_hash":"caseshash","destination":"xray","requests":[{"idempotency_key":"key","action":"create","case_version":"cv","fields_hash":content_hash(fields),"status":"ready_for_transport"}]}
            (root / "work/tms-publication-manifest.json").write_text(json.dumps(manifest))
            pipeline={"gates":{"A":{"decision":"approved","publish_cases":{"action":"publish_cases","status":"approved","content_hash":"caseshash","destination":"xray"}}}}
            (root / "pipeline.json").write_text(json.dumps(pipeline))
            with patch.object(E,"artifacts_dir",return_value=root):
                self.assertTrue(E.publication_allowed("QA-1",proposal,"xray"))
                self.assertFalse(E.publication_allowed("QA-1",dict(proposal,fields={"title":"unapproved"}),"xray"))
                self.assertFalse(E.publication_allowed("QA-1",proposal,"testrail"))
                self.assertFalse(E.publication_allowed("QA-1",{"kind":"bug"}))
                pipeline["gates"]["A"].pop("publish_cases")
                (root / "pipeline.json").write_text(json.dumps(pipeline))
                self.assertFalse(E.publication_allowed("QA-1",proposal,"xray"))

    def test_phase_separates_description_publication_from_results(self):
        description=Path("case-description.json")
        result=Path("case-result.json")
        def load(path):
            if path.name == "pipeline.json":
                return {"gates":{"A":{"decision":"approved"},"B":{"decision":"approved"}}}, None
            return ({"publication_key":"key"} if path == description else {"action":"update"}), None
        cfg={"external_writes":{"bugs":"jira","cases":"xray"}}
        with patch.object(E,"load_json",side_effect=load), patch.object(E,"artifacts_dir",return_value=Path("task")), patch.object(E,"list_proposals",side_effect=lambda t,k:[description,result] if k == "case" else []), patch.object(E,"publication_allowed",return_value=True), patch.object(E,"process_case_proposal") as process:
            self.assertEqual(E.run("QA-1",cfg,True,False,"after-a"),0)
            self.assertEqual([c.args[0] for c in process.call_args_list],[description])
            process.reset_mock()
            self.assertEqual(E.run("QA-1",cfg,True,False,"after-b"),0)
            self.assertEqual([c.args[0] for c in process.call_args_list],[result])

    def test_remote_case_receipt_preserves_approved_case_bytes(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            (root / "pipeline.json").write_text("{}")
            case=root / "TC-001.md"
            case.write_text("approved case bytes",encoding="utf-8")
            proposal=root / "case-1.json"
            proposal.write_text(json.dumps({"kind":"case", "action":"create", "publication_key":"key", "case_file":str(case), "pending":{"invoke":"tms"}}))
            with patch.object(E,"publication_allowed",return_value=True), patch.object(E,"state_dir",return_value=root), patch.object(E,"journal_external_write"):
                self.assertEqual(E.record_result(proposal,"TMS-1",""),1)
                self.assertIn("pending",json.loads(proposal.read_text()))
                self.assertEqual(E.record_result(proposal,"TMS-1","","r2"),0)
                self.assertEqual(json.loads(proposal.read_text())["result"]["remote_revision"],"r2")
                self.assertEqual(case.read_text(encoding="utf-8"),"approved case bytes")

    def test_work_proposals_reach_agent_transport_without_duplicate_dispatch(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            (root / "work/proposals").mkdir(parents=True)
            (root / "pipeline.json").write_text(json.dumps({"gates":{"A":{"decision":"approved"}}}))
            proposal=root / "work/proposals/case-1.json"
            proposal.write_text(json.dumps({"kind":"case","action":"create","publication_key":"key","case_file":"TC-001.md","destination":"project/suite","fields":{"title":"case"}}))
            cfg={"external_writes":{"cases":"xray","write_scopes":["create_case"],"channels":{"xray":{"method":"agent","invoke":"tms-adapter"}}}}
            with patch.object(E,"artifacts_dir",return_value=root),patch.object(E,"state_dir",return_value=root),patch.object(E,"publication_allowed",return_value=True):
                self.assertEqual(E.run("QA-1",cfg,True,False,"after-a"),E.EXIT_NEEDS_AGENT)
                data=json.loads(proposal.read_text())
                self.assertEqual(data["pending"]["payload"]["destination"],"project/suite")
                stamp=proposal.stat().st_mtime_ns
                self.assertEqual(E.run("QA-1",cfg,True,False,"after-a"),E.EXIT_NEEDS_AGENT)
                self.assertEqual(stamp,proposal.stat().st_mtime_ns)
                (root / "proposals").mkdir()
                (root / "proposals/case-1.json").write_text("{}")
                with self.assertRaises(ValueError):
                    E.list_proposals("QA-1","case")

    def test_update_cannot_change_authorized_remote_target(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            (root / "work").mkdir()
            decision={"action":"publish_cases","status":"approved","content_hash":"h","destination":"project/suite","channel":"xray"}
            (root / "pipeline.json").write_text(json.dumps({"gates":{"A":{"decision":"approved","publish_cases":decision}}}))
            fields={"title":"approved"}
            manifest={"destination":"project/suite","channel":"xray","content_hash":"h","requests":[{"idempotency_key":"k","action":"update","case_version":"v","fields_hash":content_hash(fields),"status":"ready_for_transport","existing_case_refs":[{"id":"TMS-1","revision":"r1"}]}]}
            (root / "work/tms-publication-manifest.json").write_text(json.dumps(manifest))
            proposal={"kind":"case","publication_key":"k","action":"update","case_version":"v","fields":fields,"destination":"project/suite","external_id":"TMS-1","expected_remote_revision":"r1"}
            with patch.object(E,"artifacts_dir",return_value=root):
                self.assertTrue(E.publication_allowed("QA-1",proposal,"xray"))
                self.assertFalse(E.publication_allowed("QA-1",dict(proposal,external_id="TMS-2"),"xray"))
                self.assertFalse(E.publication_allowed("QA-1",dict(proposal,expected_remote_revision="r2"),"xray"))
                self.assertFalse(E.publication_allowed("QA-1",dict(proposal,destination="other"),"xray"))

    def test_declined_gate_b_never_authorizes_write(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            (root / "pipeline.json").write_text(json.dumps({"gates":{"B":{"decision":"declined"}}}))
            with patch.object(E,"artifacts_dir",return_value=root):
                self.assertFalse(E.publication_allowed("QA-1",{"kind":"bug"}))


if __name__ == "__main__":
    unittest.main()
