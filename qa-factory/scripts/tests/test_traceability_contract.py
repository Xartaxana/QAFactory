"""The traceability vocabulary of contract.py: one closed result list for the report's
appendix and the dashboard's case rows, and the case -> plan-row -> level lookup that reads
the level a person approved instead of guessing one from a path."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import contract as C

PLAN = """---
task: T-1
---
# Test plan - T-1

## Plan

| TS | what we verify | R | defect hypothesis | impact class | priority | observable | oracle | disposition + reason | fit | level | technique |
|---|---|---|---|---|---|---|---|---|---|---|---|
| TS-1 | the button opens the popup | R-1 | seam | degraded | P2 | diff:a.tsx:1 | requirement:R-1 | `automate` — main path | new | e2e-ui | state |
| TS-2 | validate writes nothing | R-2 | data-loss | data-loss | P0 | diff:b.py:1 | requirement:R-2 | `automate` — main path | new | api | no-write |
| TS-3 | read-only user | R-3 | permission | access | P0 | none | requirement:R-3 | `manual-human` — needs an eye | | | matrix |
"""
CASE = """---
id: {cid}
title: {title}
area: workflows
plan_row: {row}
---
Requirements: {req}
Plan row: {row}

## Given
- x
## When
- y
## Then
1. z
"""


class VocabularyTests(unittest.TestCase):
    def test_result_vocabulary_is_closed_and_human(self):
        self.assertEqual(C.TRACE_RESULTS, ("pass", "bug", "wait", "blocked", "not run", "unreachable", "deferred", "not planned"))
        for word in ("partial", "review_skipped", "review_rejected", "passed_green"):
            self.assertNotIn(word, C.TRACE_RESULTS)

    def test_levels_are_the_plan_levels_plus_the_human_lanes(self):
        for level in C.PLAN_LEVELS:
            self.assertIn(level, C.TRACE_LEVELS)
        self.assertIn("manual-human", C.TRACE_LEVELS)
        self.assertIn("manual-agent", C.TRACE_LEVELS)

    def test_row_errors_name_the_field(self):
        self.assertEqual(C.trace_row_errors({"requirement": "R-1", "case": "TC-001", "result": "pass"}), [])
        errors = C.trace_row_errors({"requirement": "", "case": "TC-001", "result": "partial", "level": "ui", "shape": "copy"})
        self.assertIn("trace.requirement is empty", errors)
        self.assertTrue(any(e.startswith("trace.result") for e in errors))
        self.assertTrue(any(e.startswith("trace.level") for e in errors))
        self.assertTrue(any(e.startswith("trace.shape") for e in errors))

    def test_a_bug_row_names_its_record(self):
        self.assertEqual(C.trace_row_errors({"requirement": "R-3", "case": "TC-003", "result": "bug", "bug": "BUG-2"}), [])
        self.assertIn("trace.bug names the bug record when result is bug",
                      C.trace_row_errors({"requirement": "R-3", "case": "TC-003", "result": "bug"}))

    def test_not_planned_needs_no_case(self):
        self.assertEqual(C.trace_row_errors({"requirement": "R-15", "case": "", "result": "not planned"}), [])


class LevelLookupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.art = Path(self.tmp.name) / "artifacts" / "T-1"
        (self.art / "work" / "test-cases" / "workflows").mkdir(parents=True)
        (self.art / "test-plan.md").write_text(PLAN, encoding="utf-8")
        for cid, title, row, req in (("TC-001", "The button opens the popup", "TS-1", "R-1"),
                                     ("TC-002", "validate writes nothing", "TS-2", "R-2"),
                                     ("TC-003", "A read-only user cannot restore", "TS-3", "R-3")):
            (self.art / "work" / "test-cases" / "workflows" / f"{cid}.md").write_text(
                CASE.format(cid=cid, title=title, row=row, req=req), encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_plan_levels_read_the_level_column(self):
        self.assertEqual(C.plan_levels(self.art), {"TS-1": "e2e-ui", "TS-2": "api", "TS-3": ""})

    def test_case_levels_follow_the_plan_row_and_never_guess(self):
        levels = C.case_levels(self.art)
        self.assertEqual(levels.get("TC-001"), "e2e-ui")
        self.assertEqual(levels.get("TC-002"), "api")
        self.assertNotIn("TC-003", levels)  # a manual-human row has no level in the plan

    def test_case_levels_accept_the_work_dir_too(self):
        self.assertEqual(C.case_levels(self.art / "work"), C.case_levels(self.art))

    def test_case_title_reads_the_frontmatter(self):
        self.assertEqual(C.case_title(self.art / "work" / "test-cases" / "workflows" / "TC-003.md"),
                         "A read-only user cannot restore")


if __name__ == "__main__":
    unittest.main()
