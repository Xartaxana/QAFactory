"""Gate A shows exact pinned steps inside the plan, never a separate work document."""
import sys
import json
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from case_versions import create_version, pin
from render_case_appendix import render_task, embed, START

class AppendixTests(unittest.TestCase):
    def test_scoped_full_content_and_idempotent_embedding(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            source=root / "TC-001.md"
            source.write_text("---\nid: TC-001\nplan_row: TS-1\nbasis: requirement:R-1\nchannel: agent-manual\n---\nGiven a saved order\nWhen the user cancels\nThen status is cancelled\n",encoding="utf-8")
            other=root / "TC-999.md"
            other.write_text("unrelated",encoding="utf-8")
            task=root / "QA-1"
            pin(task,create_version(root / "store",source))
            source.write_text("changed after review",encoding="utf-8")
            appendix=render_task(task)
            self.assertIn("Then status is cancelled",appendix)
            self.assertNotIn("changed after review",appendix)
            self.assertNotIn("TC-999",appendix)
            plan=task / "test-plan.md"
            plan.write_text("# Plan\nUser scope remains.\n",encoding="utf-8")
            embed(plan,appendix)
            first=plan.read_bytes()
            embed(plan,appendix)
            self.assertEqual(first,plan.read_bytes())
            self.assertEqual(plan.read_text(encoding="utf-8").count(START),1)
            self.assertIn("User scope remains.",plan.read_text(encoding="utf-8"))

    def test_old_story_proof_cannot_automate_new_shared_case_content(self):
        import check_coverage as coverage
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            store=root / "cases"
            store.mkdir()
            (root / "qa-factory").mkdir()
            (root / "qa-factory/config.json").write_text(json.dumps({"cases_root":"cases"}))
            source=store / "TC-001.md"
            text="---\nid: TC-001\narea: payments\nstatus: Approved\n---\nExpected old value\n"
            source.write_text(text,encoding="utf-8")
            task=root / "qa-factory/artifacts/OLD"
            version=create_version(root / "versions",source)
            pin(task,version)
            (task / "work").mkdir()
            # HF3-1: the manifest's green is not a run; an instance counts only with a green run row of its own
            (task / "work/run-report.json").write_text(json.dumps({"current_results":[{"instance_id":"ti_old_1","status":"passed"}]}))
            (task / "work/automation-manifest.json").write_text(json.dumps({"tests":[{"case":"TC-001","instance_id":"ti_old_1","status":"green","critic_verdict":"approved","case_version_links":[{"case_id":"TC-001","version":version["version"]}]}]}))
            self.assertEqual(coverage.collect_cases(root)["payments"]["automated"],1)
            source.write_text(text.replace("old value","new behavior"),encoding="utf-8")
            self.assertEqual(coverage.collect_cases(root)["payments"]["automated"],0)

    def test_broken_markers_do_not_overwrite_plan(self):
        with tempfile.TemporaryDirectory() as td:
            plan=Path(td) / "test-plan.md"
            plan.write_text(START,encoding="utf-8")
            with self.assertRaises(ValueError):
                embed(plan,"cases")
            self.assertEqual(plan.read_text(encoding="utf-8"),START)

    def test_cases_are_listed_in_code_point_order_like_the_case_index_refusal(self):
        # C4-12: one order for a Path walk, on every platform - TC-002.md before a-x.md (the old lowercase key put a-x.md first)
        from render_case_appendix import render_files
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            for name in ("a-x.md","TC-002.md"):
                (root / name).write_text("Then "+name,encoding="utf-8")
            appendix=render_files([root / "a-x.md",root / "TC-002.md"])
            self.assertLess(appendix.index("| TC-002 |"),appendix.index("| a-x |"))
            self.assertLess(appendix.index("### TC-002"),appendix.index("### a-x"))

if __name__ == "__main__":
    unittest.main()
