"""The chain S2 -> S3 -> S4 -> gate A, at the four places the 0.7.7 review found it broken.

Each of these was a story that could not move. The plan's `impact` and the register's impact
CLASS were both called `impact`, so the strategist copied one into the other and every row came
back "invalid starter impact" with no document naming a correct value. `case_versions` looked
for cases only under the story folder, so a project with its own case store pinned nothing and
gate A approved an empty set. `planning_contract.py <file>` — the command s3.md prescribes —
rejected the very shape `work/test-plan.json` is written in. And the register's contradiction
matrix reached no plan row at all: `source_conflict` / `oracle_unknown` were required by the
validator and set by nobody.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import (SCRIPTS, check, check_eq, check_in, check_not_in, cleanup,  # noqa: E402
                     finish, run_script, temp_dir, temp_project, use_project)

sys.path.insert(0, str(SCRIPTS))

import case_versions as V  # noqa: E402
import gate_brief  # noqa: E402
import planning_contract as PC  # noqa: E402

REGISTER = (
    "---\ntask: TP1-15045\n---\n\n"
    "## Register\n\n"
    "| R | Requirement | source | derived_from | verifiable | ac_ref | observable | impact |\n"
    "|---|---|---|---|---|---|---|---|\n"
    "| R-1 | a denied caller gets 403 | ac | - | yes | AC-1 | diff:src/api.py:10 | access |\n\n"
    "## Contradiction matrix\n\n"
    "| R | parent story/feature | area cases (TC-*) | area open bugs |\n"
    "|---|---|---|---|\n"
    "| R-1 | contradicts:\"the parent feature says 401\" (feature 3) | silent | silent |\n"
)


def plan_row(**extra) -> dict:
    """A row that satisfies the starter risk contract, so a finding is the one under test."""
    return dict({"id": "TS-1", "impact": "moderate", "likelihood": "medium",
                 "confidence": "medium", "risk_rationale": "a permission seam",
                 "risk_source_refs": ["requirement:R-1"], "risk_policy_revision": "factory-starter-v1",
                 "coverage_refs": [], "unknowns": [], "verification_depth": "normal",
                 "required_scenarios": ["a denied caller"], "design_review_required": False,
                 "test_level_rationale": "HTTP contract, no UI involved"}, **extra)


def write_case(path: Path, case_id: str, task: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\nid: {case_id}\nstatus: Draft\ntask: {task}\n---\n"
                    f"Requirements: R-1\nPlan row: TS-1\n\n## Then\n1. denied with 403.\n",
                    encoding="utf-8")
    return path


# --- B-F1: two scales, two fields ------------------------------------------------------------

def test_the_two_impacts_are_told_apart() -> None:
    errors = PC.validate_plan([plan_row(impact="data-loss")])
    check_in("a register damage class in `impact` is named as such, with both scales",
             "belongs in `impact_class`", errors)
    check_in("and the message says what `impact` is", "risk scale", errors)
    check_eq("the class in its own field is accepted",
             PC.validate_plan([plan_row(impact_class="data-loss")]), [])
    check_in("a class outside the register's closed list is refused",
             "is not the register's closed list",
             PC.validate_plan([plan_row(impact_class="annoying")]))
    check_eq("a plan written before the field existed still validates",
             PC.validate_plan([plan_row()]), [])


# --- B-F12: the shape the plan is actually written in ----------------------------------------

def test_the_command_s3_prescribes_reads_the_file_s3_writes() -> None:
    root = temp_dir("qa-plan-shape-")
    try:
        plan = root / "test-plan.json"
        plan.write_text(json.dumps({"rows": [plan_row()]}), encoding="utf-8")
        result = run_script("planning_contract.py", plan, "--kind", "plan")
        check_eq("the wrapped shape is valid, not 'plan must be an array'", result.returncode, 0)
        check_not_in("and the old refusal is gone", "must be an array of behavior rows",
                     result.stdout + result.stderr)
        plan.write_text(json.dumps([plan_row()]), encoding="utf-8")
        check_eq("the bare array still works", run_script("planning_contract.py", plan,
                                                          "--kind", "plan").returncode, 0)
    finally:
        cleanup(root)


# --- B-F11: the contradiction chain ----------------------------------------------------------

def test_a_contradiction_the_register_recorded_lands_on_a_plan_row() -> None:
    errors = PC.contradiction_errors([plan_row()], REGISTER)
    check_eq("an unflagged row is exactly one finding", len(errors), 1)
    check_in("naming the requirement", "R-1", errors)
    check_in("quoting what the matrix recorded", "the parent feature says 401", errors)
    check_in("and the fields that carry it", "source_conflict", errors)
    check_eq("a flagged row closes the chain",
             PC.contradiction_errors([plan_row(source_conflict=True,
                                               design_review_required=True)], REGISTER), [])
    check_eq("`oracle_unknown` is the other half of the same fork",
             PC.contradiction_errors([plan_row(oracle_unknown=True,
                                               design_review_required=True)], REGISTER), [])
    check_in("a contradiction no row covers at all is a finding too",
             "no plan row covers R-1",
             PC.contradiction_errors([plan_row(risk_source_refs=["requirement:R-9"])], REGISTER))
    check_eq("a register with no contradictions says nothing",
             PC.contradiction_errors([plan_row()], REGISTER.split("## Contradiction")[0]), [])
    check_in("a flagged row still needs an independent design review",
             "independent design review required",
             PC.validate_plan([plan_row(source_conflict=True)]))


def test_the_contradiction_reaches_the_owner_at_gate_a() -> None:
    base = temp_dir("qa-contradiction-gate-") / "qa-factory"
    task_root = base / "artifacts" / "TP1-15045"
    (task_root / "work").mkdir(parents=True)
    (task_root / "state").mkdir(parents=True)
    (base / "config.json").write_text("{}", encoding="utf-8")
    try:
        (task_root / "work" / "requirements-register.md").write_text(REGISTER, encoding="utf-8")
        (task_root / "work" / "test-plan.json").write_text(json.dumps(
            [plan_row(source_conflict=True, design_review_required=True)]), encoding="utf-8")
        (task_root / "pipeline.json").write_text(json.dumps({"ticket": "TP1-15045"}),
                                                 encoding="utf-8")
        text = gate_brief.render(gate_brief.collect("TP1-15045", task_root))
        check_in("the gate A packet asks the owner about it", "Open questions", text)
        check_in("with the quote from the register", "the parent feature says 401", text)
        check_in("and the row it rests on", "TS-1", text)
        pipeline = {"ticket": "TP1-15045",
                    "gate_waivers": [{"gate": "A", "requirement": "R-1",
                                      "decision": "test the 403 reading"}]}
        (task_root / "pipeline.json").write_text(json.dumps(pipeline), encoding="utf-8")
        answered = gate_brief.render(gate_brief.collect("TP1-15045", task_root))
        check_not_in("a question the person already answered is not asked twice",
                     "the parent feature says 401", answered)
    finally:
        cleanup(base.parent)


# --- t-227b F14: a row that rests on an open question and says nothing about an answer --------

def _fence_register_and_md_plan(task: Path, rows) -> None:
    """GW1-41 (A1, A4): the S3 exit reads the register and test-plan.md. A register of ONE requirement, R-1, and a plan
    table whose every row names it, so the register fence has nothing to refuse and the check under test is the one asserted."""
    (task / "work" / "requirements-register.md").write_text(
        "## Register\n\n| R | Requirement | source | derived_from | verifiable | ac_ref |\n|---|---|---|---|---|---|\n"
        "| R-1 | a denied caller gets 403 | ac | - | yes | AC-1 |\n", encoding="utf-8")
    cells = "".join(f"| {r.get('id', 'TS-1')} | what | R-1 | h | degraded | P2 | o | o | `{r.get('disposition') or 'automate'}` - r | | | t |\n"
                    for r in rows if isinstance(r, dict))
    (task / "test-plan.md").write_text(
        "---\ntask: QA-33\n---\n\n## Plan\n\n| TS | what we verify | R | defect hypothesis | impact class | priority | observable | oracle | "
        "disposition + reason | fit | level | technique |\n|---|---|---|---|---|---|---|---|---|---|---|---|\n" + cells
        # RG1-2 (t-609): the S3 exit demands the section, so a fixture plan carries its null form (this file went red at the branch without it)
        + "\n## Recommended regression\nNo regression: nothing in this fixture defends an existing test\n", encoding="utf-8")


def _branch_story(root: Path, rows, questions=None, register: bool = True) -> Path:
    """A story at its S3 exit: the plan, and the register whose questions the rows rest on. `register=False` leaves out the
    register and the md plan (the exit then cannot check the plan against the register: UNREADABLE, exit 3)."""
    task = root / "qa-factory" / "artifacts" / "QA-33"
    (task / "work").mkdir(parents=True, exist_ok=True)
    (task / "state").mkdir(parents=True, exist_ok=True)
    (task / "pipeline.json").write_text(json.dumps(
        {"task": "QA-33", "stages": {"S3": {"status": "running"}}}), encoding="utf-8")
    if register:     # every row names R-1, the one requirement of the register, and has a disposition (A1: a row without one counts for nothing)
        rows = [dict({"requirements": ["R-1"], "disposition": "automate"}, **r) if isinstance(r, dict) else r for r in rows]
    (task / "work" / "test-plan.json").write_text(json.dumps({"rows": rows}), encoding="utf-8")
    (task / "state" / "controller.json").write_text(json.dumps(
        {"plan_contract_mode": "legacy", "coverage_contract_version": 1}), encoding="utf-8")
    (task / "work" / "requirements-readiness.json").unlink(missing_ok=True)
    (task / "work" / "question-answers.jsonl").unlink(missing_ok=True)
    (task / "work" / "requirements-register.md").unlink(missing_ok=True)
    (task / "test-plan.md").unlink(missing_ok=True)
    if register:
        _fence_register_and_md_plan(task, rows)
    if questions is not None:
        (task / "work" / "requirements-readiness.json").write_text(json.dumps(
            {"verdict": "blocked", "open_questions": [
                {"id": qid, "question": f"Which behaviour for {qid}?", "severity": "major",
                 "readings": [{"reading": f"r{n}", "from": "description", "if_chosen": "x"}
                              for n in range(count)]} for qid, count in questions]}), encoding="utf-8")
    return task


def test_the_s3_exit_refuses_a_row_that_rests_on_a_question_with_no_branch() -> None:
    """cmp2 (TP1-15045): TS-1, TS-3, TS-6, TS-11 and TS-13 named Q3, Q2, Q1, Q5 and Q6 and carried no
    `if_answered`; the person answered all six at gate A and no row moved. The S3 exit now REFUSES such a
    row - one stop, while the strategist still holds the context - and the S4 rehearsal stays the backstop."""
    root = temp_project("qa-s3-missing-branch-")
    try:
        ids = [("Q1", 2), ("Q2", 2), ("Q5", 2), ("Q50", 3)]
        rest = plan_row(id="TS-1", question_refs=["Q5"], reason="the expected value rests on open Q5")
        _branch_story(root, [rest, plan_row(id="TS-2")], ids)
        result = run_script("planning_contract.py", "--root", root, cwd=root)
        check_eq("the S3 exit detector REFUSES a row with a question and no branch (exit 1)", result.returncode, 1)
        check_in("it names the row and the question", "TS-1: it rests on Q5", result.stdout)
        check_in("and the answers that have no branch, `not_needed` included",
                 "no branch for a, b, not_needed", result.stdout)
        check_in("and says whose repair it is", "the strategist's rework repairs this row", result.stdout)
        check_not_in("a row that names no question is not touched", "TS-2", result.stdout)
        check_in("a person's word passes it", 'waiver.py --task <TICKET> --stage S3 --block', result.stdout)
        # t-721 3.6 (C2-3): ONE record. The S4 reader (`gate_preflight.check_question_branches`) reads the S3 word of
        # the same finding (the message or the `missing_branch_line`), so the text no longer says "record it twice
        # ... `--stage S4`": it names `--stage S3` only and says the same word also passes the S4 check (C7).
        check_in("the same S3 word also passes the question-branch check at the case stage, S4 (C7, 3.6)",
                 "also passes the question-branch check at the case stage (S4)", result.stdout)
        check_not_in("...and is NOT asked to be recorded a second time for S4 (3.6: one record)",
                     "--stage S4", result.stdout)
        # C2-1: `exit_gate.detector_errors` hands the strategist EVERY finding line of the verdict (the reader is
        # `detector_verdict.parse`), not a tail of three lines: each row to repair is a finding line of its own,
        # and the word for both stages stands in the tail after the block (O11/F-3: no "rows to repair" repeat)
        _branch_story(root, [rest, plan_row(id="TS-3", question_refs=["Q1"], reason="rests on Q1")], ids)
        two = run_script("planning_contract.py", "--root", root, cwd=root)
        tail = "\n".join(two.stdout.strip().splitlines()[-3:])
        import detector_verdict as DETV
        verdict = DETV.parse(two.returncode, two.stdout, two.stderr)
        check_eq("the verdict has one finding per row, none unmigrated, no defect",
                 (len(verdict["findings"]), verdict["unmigrated"], verdict["defects"]), (2, "", []))
        check_in("the first finding names the first row, its question and what it lacks",
                 "TS-1: it rests on Q5 but `if_answered` has no branch for a, b, not_needed", verdict["findings"][0])
        check_in("...and the second the second row", "TS-3: it rests on Q1 but `if_answered` has no branch for a, b, "
                 "not_needed", verdict["findings"][1])
        check_not_in("the 'rows to repair' repeat of the findings is gone", "rows to repair", two.stdout)
        # t-721 3.6: the tail carries the ONE record (`--stage S3`) and says it also passes S4 - no second `--stage S4`
        check_in("...and the person's word, one record for S3 that also passes S4, in the tail",
                 "`waiver.py --task <TICKET> --stage S3 --block", tail)
        check_in("...saying the same word passes the S4 check too", "the case stage (S4)", tail)
        check_not_in("...and no second record for S4 in the tail", "--stage S4", tail)
        check_in("...with a `--block` text that is the start of the finding itself", "(`TS-1: it rests on Q5`)", tail)
        # C7: ONE `--block` text passes the finding at S3 (the exit gate matches it in the detector's tail) and
        # at S4 (the rehearsal matches it in its own message), each recorded for its own stage
        import question_register as QR
        import waiver
        use_project(root)
        task = root / "qa-factory" / "artifacts" / "QA-33"
        s4_message = "question branches - " + PC.variant_errors(
            [rest], QR.load(task)["questions"], ())[0]["message"]
        block = "TS-1: it rests on Q5"
        word = lambda stage: {"stage_overrides": [{"stage": stage, "match": block, "decision": "go on",  # noqa: E731
                                                   "at": "2026-10-01T10:00:00", "by": "human"}]}
        gate_record = "planning_contract.py: " + verdict["findings"][0]       # what the exit gate holds (C2-1)
        check_eq("the one block text passes the S3 exit's finding record",
                 waiver.split_overridden([gate_record], word("S3"), "S3")[0], [])
        check_eq("...and the S4 rehearsal's message", waiver.split_overridden([s4_message], word("S4"), "S4")[0], [])
        # the WRITER's substring rule is unchanged (waiver.py): a record is read against its own stage. What 3.6 changed
        # is the S4 READER, which now also asks `split_overridden(..., "S3")` for the same finding (pinned in
        # test_question_branches), so the S3 record is quoted by S4 even though `split_overridden(..., "S4")` ignores it
        check_eq("...the writer reads a record against its own stage: the S3 record alone is not an S4 record",
                 waiver.split_overridden([s4_message], word("S3"), "S4")[0], [s4_message])
        # each branch shape the contract names is accepted
        for branches in ({"a": {}, "b": {}, "not_needed": {}}, {"*": {}, "not_needed": {}},
                         {"a": {"level": "api"}, "*": {"level": "unit"}, "not_needed": {}}):
            rows = [dict(rest, if_answered={"Q5": branches})]
            _branch_story(root, rows, ids)
            ok = run_script("planning_contract.py", "--root", root, cwd=root)
            check_eq(f"a row with a branch for every answer passes ({sorted(branches)})", ok.returncode, 0)
        # the adversarial inputs: each one is still a refusal
        for name, branches in (("an empty entry `{}`", {}), ("only `a` of two readings", {"a": {}, "not_needed": {}}),
                               ("no `not_needed`", {"a": {}, "b": {}}), ("`*` alone", {"*": {}})):
            _branch_story(root, [dict(rest, if_answered={"Q5": branches})], ids)
            got = run_script("planning_contract.py", "--root", root, cwd=root)
            check_eq(f"{name}: refused", got.returncode, 1)
        # `Q50` is not `Q5`: a row that rests on Q5 only is not asked for Q50's branches, and the reverse
        _branch_story(root, [dict(rest, if_answered={"Q5": {"*": {}, "not_needed": {}}})], ids)
        check_eq("a row resting on Q5 with Q5 branched is not refused for Q50's three readings",
                 run_script("planning_contract.py", "--root", root, cwd=root).returncode, 0)
        _branch_story(root, [plan_row(id="TS-4", question_refs=["Q50"], reason="rests on Q50")], ids)
        got = run_script("planning_contract.py", "--root", root, cwd=root)
        check_in("Q50 itself names its own three readings", "no branch for a, b, c, not_needed", got.stdout)
        check_not_in("and no Q5 finding comes with it", "rests on Q5 ", got.stdout)
        # a reason naming the question with NO `question_refs` at all rests on it just the same
        _branch_story(root, [plan_row(id="TS-8", reason="expected value per Q1."),
                             plan_row(id="TS-9", question_refs=["Q2"], if_answered={"Q2": {"*": {}, "not_needed": {}}})],
                      ids)
        got = run_script("planning_contract.py", "--root", root, cwd=root)
        check_in("a reason that carries the id token rests on it", "TS-8: it rests on Q1", got.stdout)
        # a settled question is never asked for a branch (C4)
        task = _branch_story(root, [plan_row(id="TS-8", reason="expected value per Q1."),
                                    plan_row(id="TS-9", question_refs=["Q2"],
                                             if_answered={"Q2": {"*": {}, "not_needed": {}}})], ids)
        (task / "work" / "question-answers.jsonl").write_text(json.dumps(
            {"kind": "question", "id": "Q1", "status": "answered", "reading": "a", "words": "Q1: a",
             "by": "person", "where": "S3 stop", "at": "2026-10-01T10:00:00+00:00"}) + "\n", encoding="utf-8")
        got = run_script("planning_contract.py", "--root", root, cwd=root)
        check_eq("Q1 answered at the S3 stop: its row needs no branch, the exit passes", got.returncode, 0)
        # a legacy plan (no branch field at all) is never refused, and neither is a register nobody can read
        _branch_story(root, [plan_row(id="TS-8", reason="rests on Q1")], ids)
        check_eq("a story with no `question_refs` / `if_answered` anywhere is never refused (builder rule 9)",
                 run_script("planning_contract.py", "--root", root, cwd=root).returncode, 0)
        _branch_story(root, [dict(rest)], None, register=False)
        got = run_script("planning_contract.py", "--root", root, cwd=root)
        # GW1-41 (A4): no register file is no longer a silent pass; the exit cannot check the plan against it, so it says so
        check_eq("no register file: UNREADABLE, exit 3 (A4; it was a silent exit 0 before the fence, P1)", got.returncode, 3)
        check_in("...and the line names the register", "the register's questions could not be read", got.stdout)   # re-pin t-754 m-4: the line no longer names the file
    finally:
        cleanup(root)


def test_t256_o11_the_s3_tail_counts_errors_conflicts_and_missing_branches_in_one_line() -> None:
    """`exit_gate.detector_errors` hands the role only the LAST THREE lines: the plan problems and the contradictions
    are printed above them and were cut, so one summary line counts all three kinds, right before the waiver line."""
    import re
    root = temp_project("qa-s3-tail-")
    try:
        ids = [("Q5", 2)]
        rows = [plan_row(id="TS-1", impact="bogus", question_refs=["Q5"], reason="rests on Q5"),
                plan_row(id="TS-2", question_refs=["Q5"], reason="rests on Q5")]
        task = _branch_story(root, rows, ids)
        (task / "work" / "requirements-register.md").write_text(REGISTER, encoding="utf-8")
        result = run_script("planning_contract.py", "--root", root, cwd=root)
        lines = result.stdout.strip().splitlines()
        check_eq("the S3 exit refuses (exit 1)", result.returncode, 1)
        found = re.fullmatch(r"S3 exit: (\d+) error\(s\), (\d+) conflict\(s\), (\d+) question-branch problem\(s\)"
                             r", (\d+) requirement\(s\) without a row, (\d+) candidate\(s\) without a test row"
                             r", (\d+) requirement\(s\) waiting with no branch, (\d+) regression problem\(s\), (\d+) plan target problem\(s\)"
                             r", (\d+) request problem\(s\)", lines[-2])
        check("the line before the waiver line is the summary", found is not None, lines[-2][:120])
        errors = len(PC.gate_plan_errors(rows, "legacy", 1))
        conflicts = len(PC.contradiction_errors(rows, REGISTER))
        # GW1-41 (A1, A6): the summary gained three counts of the register fence; the story has none of them (0, 0, 0)
        check_eq("its counts are the plan problems, the contradictions, the rows that lack a branch, and the fence's three (0 here)",
                 tuple(int(n) for n in found.groups()) if found else None, (errors, conflicts, 2, 0, 0, 0, 0, 0, 0))   # + RG1-2: the regression count, + TQ1-21: the plan-target count, + RN1-6: the request count, 0 here
        check("...and each is more than zero here, so none of the three counts is a constant", errors > 0 and conflicts > 0)
        check_in("the last line is the person's word", "A person's word passes any of these", lines[-1])
        check_in("the line before the summary is the last finding, whole (O11/F-3: no 'rows to repair' repeat)",
                 "- TS-2: it rests on Q5 but `if_answered` has no branch", lines[-3])
        check_not_in("...and nothing prints a 'rows to repair' line", "rows to repair", result.stdout)
        # one row, nothing else: the counts say so
        _branch_story(root, [plan_row(id="TS-2", question_refs=["Q5"], reason="rests on Q5")], ids)
        only = run_script("planning_contract.py", "--root", root, cwd=root).stdout.strip().splitlines()
        check_eq("a missing branch alone: 0 and 0 and 1 (and the fence's three at 0)", only[-2],
                 "S3 exit: 0 error(s), 0 conflict(s), 1 question-branch problem(s), 0 requirement(s) without a row, "
                 "0 candidate(s) without a test row, 0 requirement(s) waiting with no branch, 0 regression problem(s), 0 plan target problem(s), "
                 "0 request problem(s)")
        # an OK exit prints no summary
        _branch_story(root, [plan_row(id="TS-2")], ids)
        ok = run_script("planning_contract.py", "--root", root, cwd=root)
        check_eq("an exit that passes prints no summary line", (ok.returncode, "S3 exit:" in ok.stdout), (0, False))
    finally:
        cleanup(root)


def test_t256_o12_a_plan_created_on_or_after_the_cutoff_is_checked_even_with_no_branch_field() -> None:
    """The invariant "a story with no branch field is never refused" is DATED (ORACLE_CUTOFF 2026-10-02), not dropped:
    the reason-only input `manual until Q5 is answered` is a finding for a plan created from that day."""
    root = temp_project("qa-s3-cutoff-")
    try:
        ids = [("Q5", 2)]
        rows = [plan_row(id="TS-1", disposition="manual-agent", reason="manual until Q5 is answered")]
        for created, refused in (("2026-10-01", False), ("2026-10-02", True), ("2026-12-31", True), (None, False)):
            task = _branch_story(root, rows, ids)
            if created:     # the helper's plan table stays (A1 reads it); only the front matter gains the date
                md = task / "test-plan.md"
                md.write_text(md.read_text(encoding="utf-8").replace("---\ntask: QA-33\n", f"---\ntask: QA-33\ncreated: {created}\n", 1),
                              encoding="utf-8")
            got = run_script("planning_contract.py", "--root", root, cwd=root)
            check_eq(f"plan created {created}: {'refused' if refused else 'silent (the legacy invariant)'}",
                     got.returncode, 1 if refused else 0)
            if refused:
                check_in("...naming the row and the question, with no branch field anywhere", "TS-1: it rests on Q5", got.stdout)
        # the date is read where the plan says it: the front matter of test-plan.md
        check_eq("planning_contract.plan_created reads it", PC.plan_created(task), None)
        (task / "test-plan.md").write_text("---\ncreated: 2026-10-05\n---\n", encoding="utf-8")
        check_eq("...from the front matter", PC.plan_created(task), "2026-10-05")
    finally:
        cleanup(root)


# --- B-F2 / B-F3 / B-F4: one case store, one default -----------------------------------------

def test_the_project_case_store_is_where_the_cases_are_found() -> None:
    root = temp_dir("qa-cases-root-")
    try:
        (root / "qa-factory").mkdir(parents=True)
        (root / "qa-factory" / "config.json").write_text(
            json.dumps({"schema_version": 1, "cases_root": "tests/cases"}), encoding="utf-8")
        task_root = root / "qa-factory" / "artifacts" / "TP1-15045"
        (task_root / "work").mkdir(parents=True)
        mine = write_case(root / "tests" / "cases" / "workflows" / "TC-001.md",
                          "TC-001", "TP1-15045")
        write_case(root / "tests" / "cases" / "workflows" / "TC-900.md", "TC-900", "TP1-1")
        found = V.discover_cases(task_root)
        check_eq("the project's own store is searched", [p.name for p in found], ["TC-001.md"])
        check_eq("another story's case in the shared library is not this story's",
                 all(p != task_root for p in found), True)
        check_eq("and the default store follows the same key",
                 V.store_root(task_root).resolve(), (root / "tests" / "cases").resolve())
        result = run_script("case_versions.py", "--task-root", task_root, "--all", cwd=root)
        check("`--all` pins without being told where the store is", result.returncode == 0,
              result.stdout + result.stderr)
        check_in("one case pinned", '"pinned": 1', result.stdout)
        verify = run_script("case_versions.py", "--task-root", task_root, "--verify", cwd=root)
        check("and `--verify` counts it", verify.returncode == 0, verify.stderr)
        check_in("not zero, as it answered on every cases_root project", '"cases": 1',
                 verify.stdout)
        mine.write_text(mine.read_text(encoding="utf-8") + "\n2. and logged.\n", encoding="utf-8")
        check_eq("an edited case is reported unpinned", len(V.unpinned(task_root)), 1)
    finally:
        cleanup(root)


def test_a_story_without_a_store_keeps_its_own_cases() -> None:
    root = temp_dir("qa-cases-story-")
    try:
        (root / "qa-factory").mkdir(parents=True)
        (root / "qa-factory" / "config.json").write_text(
            json.dumps({"schema_version": 1}), encoding="utf-8")
        task_root = root / "qa-factory" / "artifacts" / "TP1-15045"
        write_case(task_root / "work" / "test-cases" / "wf" / "TC-001.md", "TC-001",
                   "TP1-15045")
        check_eq("the story's own directory is the default store",
                 V.store_root(task_root).resolve(),
                 (task_root / "work" / "test-cases").resolve())
        check_eq("and its cases are found", [p.name for p in V.discover_cases(task_root)],
                 ["TC-001.md"])
    finally:
        cleanup(root)


# --- B-F5 / B-F14: what the gate A packet shows ----------------------------------------------

def test_the_two_documents_gate_a_is_about_are_in_the_packet() -> None:
    base = temp_dir("qa-gate-docs-") / "qa-factory"
    task_root = base / "artifacts" / "TP1-15045"
    (task_root / "work").mkdir(parents=True)
    (task_root / "state").mkdir(parents=True)
    (base / "config.json").write_text("{}", encoding="utf-8")
    try:
        # The two documents written FOR a person live at the story root, not under work/.
        (task_root / "test-plan.md").write_text("# plan\n", encoding="utf-8")
        (task_root / "understanding.md").write_text("# understanding\n", encoding="utf-8")
        (task_root / "work" / "requirements-register.md").write_text("# register\n",
                                                                     encoding="utf-8")
        (task_root / "work" / "test-plan.json").write_text(json.dumps([plan_row()]),
                                                           encoding="utf-8")
        (task_root / "pipeline.json").write_text(json.dumps({"ticket": "TP1-15045"}),
                                                 encoding="utf-8")
        docs = gate_brief.collect("TP1-15045", task_root)["documents"]
        check_eq("the plan is listed", docs.get("plan"),
                 "qa-factory/artifacts/TP1-15045/test-plan.md")
        check_eq("and understanding.md, the other document the gate is about",
                 docs.get("understanding"),
                 "qa-factory/artifacts/TP1-15045/understanding.md")
        # GW1-11: the register left GATE_A_DOCUMENTS (a working file, not a document to approve); "read from work/" is now
        # pinned on contract.artifact itself, which documents() calls for the two that remain.
        check_eq("GW1-11: the register is not among the gate A documents", docs.get("register"), None)
        check_eq("a working artifact is still read from work/",
                 __import__("contract").artifact(task_root, "requirements-register.md"),
                 task_root / "work" / "requirements-register.md")
    finally:
        cleanup(base.parent)


def test_the_size_line_reads_the_keys_sizing_actually_writes() -> None:
    base = temp_dir("qa-gate-sizing-") / "qa-factory"
    task_root = base / "artifacts" / "TP1-15045"
    (task_root / "work").mkdir(parents=True)
    (base / "config.json").write_text("{}", encoding="utf-8")
    try:
        (task_root / "work" / "sizing.json").write_text(json.dumps(
            {"size": "XXL", "cap": 28, "computed_budget": 34, "recommended_budget": 28,
             "overage": 6, "unverifiable": [{"r": "R-4", "reason": "observable: none"},
                                            {"r": "R-7", "reason": "verifiable: no"}]}),
            encoding="utf-8")
        line = gate_brief.sizing_line(task_root)
        check_in("what the requirements weigh is shown (the computed budget)", "the requirements weigh 34", line)
        check_in("with the cap it was held down to (t-342: the cap says it, no 'recommended' figure)", "the XXL cap is 28", line)
        check_in("the overage is named", "over the cap by 6", line)
        check_in("the unverifiable requirements are COUNTED, not printed raw",
                 "2 requirement(s)", line)
        check_not_in("no python repr reaches the person", "{'r'", line)
        check_in("and XXL says what the person may do (OH3-15: the word passes it, no 'decompos'): old world, rows", "Your word tests it as one story", line)
        check_in("old world names that the functions were not named", "the functions were not named", line)
        check_not_in("no word of splitting reaches the person", "decompos", line)
    finally:
        cleanup(base.parent)


# --- open before the MR ----------------------------------------------------------------------

def test_what_is_still_open_is_listed_before_the_mr_not_after_it() -> None:
    """The owner's decision of 21.09.2026: the factory waits at a gate, keeps a non-critical
    answer as a remark, and before the MR shows everything not done and every question left
    open — the same list that goes into the MR description on "open the MR anyway"."""
    base = temp_dir("qa-open-before-mr-") / "qa-factory"
    task_root = base / "artifacts" / "TP1-15045"
    (task_root / "work").mkdir(parents=True)
    (task_root / "state").mkdir(parents=True)
    (base / "config.json").write_text("{}", encoding="utf-8")
    try:
        (task_root / "pipeline.json").write_text(json.dumps(
            {"ticket": "TP1-15045",
             "remarks": [{"stage": "S4", "text": "the colour of the badge is not my concern",
                          "at": "2026-09-21T10:00:00"}]}), encoding="utf-8")
        (task_root / "work" / "requirements-readiness.json").write_text(json.dumps(
            {"open_questions": [
                {"id": "R-9", "question": "where does a removed node go?", "severity": "major",
                 "owner_role": "po_ba"},
                {"id": "R-8", "question": "answered long ago", "severity": "minor",
                 "owner_role": "po_ba", "answer": "it is archived"}]}), encoding="utf-8")
        (task_root / "work" / "automation-manifest.json").write_text(json.dumps(
            {"unresolved": [{"case": "TC-004", "reason": "pending_implementation",
                             "owner": "dev"}]}), encoding="utf-8")
        lines = gate_brief.open_before_mr(task_root)
        blob = "\n".join(lines)
        check_in("an unanswered gate A question is listed", "where does a removed node go?", blob)
        check_not_in("one with a recorded answer is not", "answered long ago", blob)
        check_in("a remark kept instead of re-asked is carried", "colour of the badge", blob)
        check_in("and says it was kept, not asked again", "not re-asked", blob)
        check_in("an unresolved row is listed with what it is waiting on",
                 "TC-004 not automated", blob)
        check_in("with its owner", "owner: dev", blob)
        text = gate_brief.render_gate_b("TP1-15045", task_root)
        check_in("the gate B brief carries the section", "## Open before the MR", text)
        # t-305 N8 (R6): the MR is offered only on a verdict that opens delivery (`yes`, `after_checks`); this story has no
        # ledger, which reads `no`, so the way past is "deliver with known gaps" and the MR sentence is not there.
        check_not_in("a story whose verdict reads `no` is not offered the MR", "open the MR anyway", text)
        (task_root / "work" / "ledger.json").write_text(json.dumps({"delivery_verdict": "after_checks", "delivery_ready": False,
                                                                    "rows": []}), encoding="utf-8")
        check_in("and the person's way past it (a verdict that opens delivery)", "open the MR anyway",
                 gate_brief.render_gate_b("TP1-15045", task_root))
        check_eq("every line is one markdown bullet, ready for the MR description",
                 all(line.startswith("- ") for line in lines), True)
        many = json.loads((task_root / "work" / "requirements-readiness.json").read_text(
            encoding="utf-8"))
        many["open_questions"] = [{"id": f"R-{n}", "question": f"question {n}",
                                   "severity": "minor", "owner_role": "po_ba"} for n in range(20)]
        (task_root / "work" / "requirements-readiness.json").write_text(json.dumps(many),
                                                                        encoding="utf-8")
        capped = gate_brief.render_gate_b("TP1-15045", task_root)
        check_in("a long list is capped with a count, never truncated in silence",
                 "more of the same kinds", capped)
        section = capped.split("## Open before the MR", 1)[1].split("\n## ", 1)[0]
        check("and the section stays inside the brief's budget",
              len([l for l in section.splitlines() if l.startswith("- ")])
              <= gate_brief.MAX_OPEN_BEFORE_MR + 1)
    finally:
        cleanup(base.parent)


def test_c2_1_eleven_plan_errors_reach_the_strategist_as_eleven_records() -> None:
    """C2-1 (t-726 p. 8): the S3 exit used to print `errors[:10]` and the gate kept the last three lines. Eleven plan
    errors are eleven finding records of the gate, in the order of the detector, and their texts after the script name
    are the errors' own texts: no defect, no unmigrated text (a count of eleven records would also be met by ten
    findings and one defect, so the texts are compared)."""
    import exit_gate
    root = temp_project("qa-s3-eleven-")
    try:
        rows = [plan_row(id=f"TS-{n}", impact="bogus") for n in range(1, 13)]
        _branch_story(root, rows, None)
        use_project(root)
        errors = PC.gate_plan_errors(rows, "legacy", 1)
        check("the fixture gives more than ten plan errors", len(errors) > 10, str(len(errors)))
        records = exit_gate.detector_errors("qa-test-strategist")
        found = [r for r in records if r.kind == "finding"]
        check_eq("every error is a finding record of its own (none cut at ten, none left in a tail)", len(found), len(errors))
        check_eq("...with the error's own text, in the order of the detector",
                 [str(r).split("planning_contract.py: ", 1)[1] for r in found], [PC.one_line(e) for e in errors])
        check_eq("...and neither a defect nor an unmigrated record beside them",
                 sorted({r.kind for r in records}), ["finding", "summary"])
    finally:
        cleanup(root)


def test_g1_5_the_exit_detector_hands_the_role_only_its_own_grounding_findings() -> None:
    """G1-5 fix round (F-7): `_detector_body` adds ONE line - the `who == "role"` findings of `GT.exit_findings` - to the refusal and to its
    `S3 exit:` count; a finding of the driver or the conductor never comes back to the role as its work. The findings are stood in for
    (the rules themselves are pinned in test_grounding_table.py): what is pinned here is that the detector CALLS the exit and filters by `who`."""
    import contextlib
    import io
    import grounding_table as GT
    root = temp_project("qa-s3-exit-grounding-")
    real = GT.exit_findings
    try:
        _branch_story(root, [plan_row(id="TS-1")], None)

        def detect(findings):
            GT.exit_findings = lambda *a, **k: list(findings)
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = PC._detector_body(root)
            return code, out.getvalue()
        role, driver, conductor = (GT.Finding("R7", "a K-1 risk is named by no plan row", "role"),
                                   GT.Finding("R2", "the driver owes the hunks", "driver"),
                                   GT.Finding("R0", "the table is missing", "conductor"))
        code, shown = detect([role, driver, conductor])
        check_eq("a role finding refuses the exit (exit 1)", code, 1)
        check_in("...and is handed over in the person-visible form", "[grounding R7] a K-1 risk is named by no plan row", shown)
        check_not_in("...a driver finding is not handed to the role", "the driver owes the hunks", shown)
        check_not_in("...nor is a conductor finding", "the table is missing", shown)
        check_in("...the role's finding is counted in the `S3 exit:` line", "S3 exit: 1 error(s)", shown)
        code, shown = detect([driver, conductor])
        check_eq("only driver and conductor findings: the detector passes (exit 0), they close nothing through the role", (code, "S3 exit:" in shown), (0, False))
    finally:
        GT.exit_findings = real
        cleanup(root)


if __name__ == "__main__":
    test_g1_5_the_exit_detector_hands_the_role_only_its_own_grounding_findings()
    test_c2_1_eleven_plan_errors_reach_the_strategist_as_eleven_records()
    test_the_two_impacts_are_told_apart()
    test_the_command_s3_prescribes_reads_the_file_s3_writes()
    test_a_contradiction_the_register_recorded_lands_on_a_plan_row()
    test_the_contradiction_reaches_the_owner_at_gate_a()
    test_the_s3_exit_refuses_a_row_that_rests_on_a_question_with_no_branch()
    test_t256_o11_the_s3_tail_counts_errors_conflicts_and_missing_branches_in_one_line()
    test_t256_o12_a_plan_created_on_or_after_the_cutoff_is_checked_even_with_no_branch_field()
    test_the_project_case_store_is_where_the_cases_are_found()
    test_a_story_without_a_store_keeps_its_own_cases()
    test_the_two_documents_gate_a_is_about_are_in_the_packet()
    test_the_size_line_reads_the_keys_sizing_actually_writes()
    test_what_is_still_open_is_listed_before_the_mr_not_after_it()
    finish("S3-S4 chain")
