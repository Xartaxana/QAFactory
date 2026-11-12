"""The joins the dashboard reads a story through, on the shapes TP1-15045 actually wrote.

Before 0.7.12 each of these read a field that does not exist: triage was keyed by `test_id`,
the case name fell back to the pytest node id although `case_version_links[].case_id` was on
every run row, the level was looked for in one of its three sources, superseded manifest rows
were counted as instances, and every session captured in the project's cost folder was summed
into the project whatever directory it had been opened in.
"""
import sys
from pathlib import Path
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import factory_dashboard as D


def _entry(instance, case, status="green", file="testproject1_test_harness/tests/workflow/t_api.py", **extra):
    entry = {"instance_id": instance, "case": case, "status": status, "file": file,
             "selector": file + "::" + instance,
             "case_version_links": [{"case_id": case, "version": "cv_" + case}]}
    entry.update(extra)
    return entry


def _result(instance, status, node, case, profile_id="", attempt="att-1"):
    return {"instance_id": instance, "test_id": node, "status": status, "attempt_id": attempt,
            "profile_id": profile_id, "case_version_links": [{"case_id": case, "version": "cv_" + case}]}


class DeadRowTests(unittest.TestCase):
    def test_superseded_duplicate_rows_never_become_instances(self):
        manifest = {"tests": [
            _entry("test_a", "TC-001"),
            _entry("test_a_old", "TC-001", note="SUPERSEDED DUPLICATE - replaced in window 3"),
            _entry("test_b_old", "TC-002", critic_note="SUPERSEDED DUPLICATE"),
        ]}
        self.assertEqual([e["instance_id"] for e in D.live_manifest_entries(manifest)], ["test_a"])

    def test_stale_unresolved_row_is_not_a_block(self):
        self.assertTrue(D.is_stale_unresolved({"detail": "STALE, kept as a labeled marker only"}))
        self.assertFalse(D.is_stale_unresolved({"detail": "no keys on this stand"}))


class TerminalResultTests(unittest.TestCase):
    def test_a_settled_row_wins_over_the_partial_one_of_the_same_instance(self):
        report = {"current_results": [
            _result("test_a", "partial", "pkg.mod::test_a", "TC-001"),
            _result("test_a", "passed", "pkg.mod::test_a", "TC-001"),
        ]}
        self.assertEqual(D.result_status_of(D.run_rows_by_alias(report)["test_a"]), "passed")

    def test_partial_falls_back_to_the_manifest_word_not_to_green(self):
        manifest = {"tests": [_entry("test_red", "TC-003", status="red")]}
        report = {"current_results": [_result("test_red", "partial", "pkg.mod::test_red", "TC-003")]}
        row = D.story_projection({"manifest": manifest, "report": report}, {}, {}, [], [])["rows"][0]
        self.assertEqual(row["status"], "failed")
        self.assertEqual(row["state"], "bug")


class LevelTests(unittest.TestCase):
    def test_profile_id_then_the_plan_row_then_the_longest_path_glob(self):
        globs = {"api": ["tests/**"], "e2e-ui": ["tests/ui/**"]}
        entry = _entry("test_a", "TC-001", file="tests/ui/workflows/t.py")
        self.assertEqual(D.instance_level(entry, {"profile_id": "api"}, "TC-001", {}, globs), "api")
        self.assertEqual(D.instance_level(entry, {}, "TC-001", {"TC-001": "component"}, globs), "component")
        # the file path, never the dotted module path, and the longest pattern wins
        self.assertEqual(D.instance_level(entry, {}, "TC-001", {}, globs), "e2e-ui")
        self.assertEqual(D.instance_level({"file": ""}, {}, "TC-9", {}, globs), D.LEVEL_NONE)


class TriageAndNameTests(unittest.TestCase):
    def setUp(self):
        self.manifest = {"tests": [
            _entry("test_env", "TC-006", status="red", file="tests/ui/t.py"),
            _entry("test_bug", "TC-003", status="red", file="tests/ui/t.py"),
        ]}
        self.report = {"current_results": [
            _result("test_env", "failed", "tests.ui.t::test_env[chromium]", "TC-006", "e2e-ui", "att-env"),
            _result("test_bug", "failed", "tests.ui.t::test_bug[chromium]", "TC-003", "e2e-ui", "att-bug"),
        ]}
        self.triage = {"triage": [{"instance_id": "test_env", "attempt_id": "att-env",
                                   "test": "tests/ui/t.py::test_env", "verdict": "ENV_ISSUE", "case": "TC-006"}]}

    def test_triage_joins_by_instance_and_attempt_not_by_a_field_nobody_writes(self):
        task = {"manifest": self.manifest, "report": self.report, "triage_doc": self.triage}
        rows = {r["case"]: r for r in D.story_projection(task, {}, {}, [], [])["rows"]}
        self.assertEqual(rows["TC-006"]["verdict"], "ENV_ISSUE")
        self.assertEqual(rows["TC-006"]["state"], "env")

    def test_a_filed_bug_is_the_verdict_when_triage_never_wrote_one(self):
        bugs = [{"id": "BUG-2", "title": "duplicate ADDED badge", "found_by": "TC-003",
                 "severity": "minor", "violates": "requirement:R-3"}]
        task = {"manifest": self.manifest, "report": self.report, "triage_doc": self.triage}
        rows = {r["case"]: r for r in D.story_projection(task, {}, {}, bugs, [])["rows"]}
        self.assertEqual(rows["TC-003"]["verdict"], "APP_BUG")
        self.assertEqual(rows["TC-003"]["bugs"], ["BUG-2"])

    def test_the_case_title_is_the_name_and_the_node_id_is_the_hover(self):
        task = {"manifest": self.manifest, "report": self.report, "triage_doc": self.triage}
        titles = {"TC-003": "Added node gets a green border, and only it"}
        rows = {r["case"]: r for r in D.story_projection(task, titles, {}, [], [])["rows"]}
        self.assertEqual(rows["TC-003"]["title"], "Added node gets a green border, and only it")
        self.assertEqual(rows["TC-003"]["node"], "tests.ui.t::test_bug[chromium]")
        html = D.instance_row_html(rows["TC-003"])
        self.assertIn("Added node gets a green border", html)
        self.assertIn("class='id'>tests.ui.t::test_bug[chromium]<", html)


class SelftestIsNotAStoryTests(unittest.TestCase):
    def test_a_folder_starting_with_underscore_is_not_a_task(self):
        import tempfile, json as _json
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for name in ("_selftest", "TP1-1"):
                d = root / "qa-factory" / "artifacts" / name / "work"
                d.mkdir(parents=True)
                (d / "run-report.json").write_text(_json.dumps({"current_results": []}), encoding="utf-8")
            (root / "qa-factory" / "config.json").write_text("{}", encoding="utf-8")
            self.assertEqual([t["task"] for t in D.parse_taskruns(root)], ["TP1-1"])


class SessionAttributionTests(unittest.TestCase):
    def _s(self, sid, slug, cost):
        return {"session_id": sid, "usage_completeness": "complete", "pricing_coverage": "complete",
                "transcript": rf"C:\Users\dev3\.claude\projects\{slug}\{sid}.jsonl",
                "by_model": {"m": {"input": 10, "output": 0, "cache_read": 0, "cache_write_5m": 0,
                                   "cache_write_1h": 0, "cost": cost}},
                "priced_subtotal_usd": cost, "total_cost_usd": cost, "reconciliation": {"match": True}}

    def test_a_session_of_a_parent_directory_is_not_this_project(self):
        root = Path(r"D:/ws1/repo\test-harness")
        own = self._s("in", "D--ws-repo-test-harness", 5)
        above = self._s("above", "D--ws", 2400)
        inside, outside = D.split_project_sessions([own, above], root)
        self.assertEqual([s["session_id"] for s in inside], ["in"])
        self.assertEqual([s["session_id"] for s in outside], ["above"])

    def test_a_copied_cost_folder_still_places_its_own_sessions(self):
        # An incident review renders the project from a copy, so no slug matches the path.
        own = self._s("in", "D--ws-repo-test-harness", 5)
        above = self._s("above", "D--ws", 2400)
        inside, outside = D.split_project_sessions([own, above], Path(r"C:\tmp\copy"))
        self.assertEqual([s["session_id"] for s in inside], ["in"])
        self.assertEqual([s["session_id"] for s in outside], ["above"])

    def test_the_outside_money_is_shown_and_never_summed(self):
        root = Path(r"D:/ws1/repo\test-harness")
        html = D.tab_cost([self._s("in", "D--ws-repo-test-harness", 5),
                           self._s("above", "D--ws", 2400)], None, root)
        self.assertIn("Sessions of parent directories", html)
        self.assertNotIn("$2,405.00", html)
        self.assertIn("$5.00", html)


class CompletenessTests(unittest.TestCase):
    def test_incomplete_cost_is_a_named_factory_finding_not_a_grey_unknown(self):
        row = {"incomplete_agents": {"qa-scout"}, "provisional_sessions": {"s1"}, "sessions": 2,
               "unpriced_tokens": 0, "priced": True, "ok": None}
        text, cls, is_finding = D.task_completeness(row)
        self.assertTrue(is_finding)
        self.assertEqual(cls, "warn")
        self.assertIn("1 role without usage", text)
        self.assertIn("1 session provisional", text)
        finding = D.cost_findings_from_tasks({"TP1-1": row})[0]
        self.assertIn("cost incomplete for TP1-1", finding)
        self.assertIn("qa-scout", finding)
        self.assertIn("owner: factory".lower(), finding.lower())

    def test_a_clean_task_reads_reconciled(self):
        row = {"incomplete_agents": set(), "provisional_sessions": set(), "sessions": 1,
               "unpriced_tokens": 0, "priced": True, "ok": True}
        text, cls, is_finding = D.task_completeness(row)
        self.assertFalse(is_finding)
        self.assertEqual(cls, "ok")
        self.assertIn("reconciled", text)
        self.assertEqual(D.cost_findings_from_tasks({"TP1-1": row}), [])


class BasisTests(unittest.TestCase):
    """Why a green row can be believed: the critic's verdict in its own words (FR-35) and how sure
    the check is (D-0010/D-0012). "review not recorded" is for a critic that never spoke."""

    def test_each_verdict_shows_its_own_words(self):
        green = {"status": "passed"}
        for verdict, words in (("rejected", "rejected by the code critic"),
                               ("unverified", "the code critic could not verify it"),
                               ("", "review not recorded"),
                               ("maybe", "review verdict not recognised: maybe")):
            self.assertEqual(D.instance_basis(_entry("t", "TC-1", critic_verdict=verdict), green), words, verdict)

    def test_without_the_task_root_the_level_is_the_probe_blocks_own(self):
        green = {"status": "passed"}
        for probe, words in (({"proof_level": "live"}, "the check is live"),
                             ({"window_probe": True}, "the check is live"),
                             ({"mutation_kind": "real_behavior"}, "catches a broken product"),
                             ({}, "not probed")):
            entry = _entry("t", "TC-1", critic_verdict="approved", probe=probe)
            self.assertEqual(D.instance_basis(entry, green), "reviewed by the code critic · " + words, probe)
        entry = _entry("t", "TC-1", critic_verdict="approved_with_fixes")
        self.assertEqual(D.instance_basis(entry, green), "reviewed by the code critic, fixes named · not probed")

    def test_a_missing_level_vocabulary_never_crashes_the_dashboard(self):
        import contextlib
        import io
        import proof_level as PL
        real = PL.LEVELS_FILE
        PL.LEVELS_FILE = Path(real).with_name("no-such-levels.json")
        PL._reset()
        D._LEVELS_NOTE_SHOWN = False
        seen = io.StringIO()
        try:
            with contextlib.redirect_stderr(seen):
                first = D.instance_basis(_entry("t", "TC-1", critic_verdict="approved"), {"status": "passed"})
                second = D.instance_basis(_entry("t", "TC-2", critic_verdict="rejected"), {"status": "passed"})
        finally:
            PL.LEVELS_FILE = real
            PL._reset()
        self.assertEqual(first, "critic verdict: approved (proof level not shown)")
        self.assertEqual(second, "critic verdict: rejected (proof level not shown)")
        self.assertEqual(seen.getvalue().count("proof levels are not shown"), 1, seen.getvalue())
        self.assertIn("references/verification-levels.json", seen.getvalue())
        self.assertIn("reinstall the plugin", seen.getvalue())

    def test_a_verdict_is_read_stripped(self):
        entry = _entry("t", "TC-1", critic_verdict="  unverified\n")
        self.assertEqual(D.instance_basis(entry, {"status": "passed"}), "the code critic could not verify it")

    def test_a_red_row_still_says_what_the_run_said(self):
        self.assertEqual(D.instance_basis(_entry("t", "TC-1", status="red"), {"status": "failed", "reason": "boom"}),
                         "boom")

    def test_with_the_task_root_the_level_is_what_the_receipts_reach(self):
        import hashlib
        import json
        import os
        from harness import cleanup, temp_dir, use_project
        root = temp_dir("qa-dashboard-basis-")
        try:
            (root / "qa-factory").mkdir()
            (root / "qa-factory" / "config.json").write_text(json.dumps({"tests_root": "tests"}), encoding="utf-8")
            source = root / "tests" / "t_api.py"
            source.parent.mkdir()
            source.write_text("def test_a():\n    assert 1 + 1 == 2\n", encoding="utf-8")
            use_project(root)
            task = root / "qa-factory" / "artifacts" / "T-1"
            receipts = task / "work" / "sensitivity-receipts"
            receipts.mkdir(parents=True)
            sha = hashlib.sha256(source.read_bytes()).hexdigest()
            body = {"instance_id": "test_a", "case_version": "cv_TC-1", "test_content_hash": sha,
                    "source_revision": "s", "build_id": "b", "mutation": "invert",
                    "expected_assertion_failure": "x", "actual_failure": "x", "assertion_location": "t:1",
                    "restoration_evidence": "restored", "failure_kind": "assertion", "immutable": True,
                    "receipt_hash": "h", "proof_level": "live", "probe_tool": "probe_by_code.py",
                    "mutation_kind": "assertion"}
            (receipts / "r.json").write_text(json.dumps(body), encoding="utf-8")
            ref = {"path": "work/sensitivity-receipts/r.json",
                   "sha256": hashlib.sha256((receipts / "r.json").read_bytes()).hexdigest()}
            entry = _entry("test_a", "TC-1", file="tests/t_api.py", critic_verdict="approved",
                           new_or_changed=True, sensitivity_proof={"receipt_ref": ref})
            report = {"current_results": [_result("test_a", "passed", "tests.t_api::test_a", "TC-1")]}
            task_dict = {"manifest": {"tests": [entry]}, "report": report, "artifact_path": str(task)}
            row = D.story_projection(task_dict, {}, {}, [], [])["rows"][0]
            self.assertEqual(row["basis"], "reviewed by the code critic · the check is live")
            # The same test after its code changed: the receipt is for other bytes, no level is claimed.
            source.write_text("def test_a():\n    assert 1 + 1 == 3\n", encoding="utf-8")
            row = D.story_projection(task_dict, {}, {}, [], [])["rows"][0]
            self.assertEqual(row["basis"], "reviewed by the code critic · not probed")
            # And a projection without the root reads the row's own probe block, as it always could.
            no_root = dict(task_dict)
            no_root.pop("artifact_path")
            row = D.story_projection(no_root, {}, {}, [], [])["rows"][0]
            self.assertEqual(row["basis"], "reviewed by the code critic · not probed")
        finally:
            os.environ.pop("CLAUDE_PROJECT_DIR", None)
            import hooklib
            hooklib._PROJECT_ROOT_CACHE = None
            cleanup(root)


class BugRowTests(unittest.TestCase):
    """t-2187 (5.18): a draft that speaks for several cases lists them all on its board row."""

    MERGED = {"title": "Quantity changes", "case": "TC-001", "cases": ["TC-001", "TC-002"],
              "manifestations": [{"action": "a", "start_state": "s", "seen": "x", "case": "TC-003"}]}

    def test_a_merged_draft_lists_case_cases_and_every_manifestations_case(self):
        rows = D.story_bug_rows([], [self.MERGED], {"TC-003"}, "QA-1")
        self.assertEqual([r["cases"] for r in rows], ["TC-001, TC-002, TC-003"])

    def test_a_case_named_only_by_a_manifestation_joins_the_story(self):
        self.assertEqual(len(D.story_bug_rows([], [self.MERGED], {"TC-003"}, "QA-1")), 1)
        self.assertEqual(D.story_bug_rows([], [self.MERGED], {"TC-009"}, "QA-1"), [])

    def test_an_old_draft_reads_as_before(self):
        self.assertEqual([r["cases"] for r in D.story_bug_rows([], [{"title": "x", "case": "TC-002"}], {"TC-002"}, "QA-1")], ["TC-002"])
        self.assertEqual([r["cases"] for r in D.story_bug_rows([], [{"title": "x", "cases": ["TC-004", "TC-005"]}], None, "QA-1")],
                         ["TC-004, TC-005"])
        # a draft that names no case at all was never listed (the empty set is "all filed"): unchanged
        self.assertEqual(D.story_bug_rows([], [{"title": "x"}], None, "QA-1"), [])

    def test_a_draft_with_every_case_filed_is_not_listed_again(self):
        filed = [{"id": "BUG-1", "title": "t", "task": "QA-1", "found_by": "TC-001 TC-002 TC-003"}]
        self.assertEqual([r["id"] for r in D.story_bug_rows(filed, [self.MERGED], {"TC-001"}, "QA-1")], ["BUG-1"])


class RemovedWidgetsTests(unittest.TestCase):
    def test_the_blocks_the_owner_removed_are_gone(self):
        source = (Path(__file__).resolve().parents[1] / "factory_dashboard.py").read_text(encoding="utf-8")
        for gone in ("<h2>Latency telemetry", "<h2>Orchestrator continuation", "<h2>Execution jobs",
                     "<h2>Approved scope awaiting execution", "SAMPLE VIEW", "<h2>Local bug records",
                     "def parse_board", "DEMO_ESTIMATES_DUMBBELL", "n={m['sample_size']}"):
            self.assertNotIn(gone, source, gone)


if __name__ == "__main__":
    unittest.main()
