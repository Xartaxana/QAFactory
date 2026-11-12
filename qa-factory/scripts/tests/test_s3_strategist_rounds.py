#!/usr/bin/env python3
"""RN1-2: the S3 strategist cannot hand in an unfilled plan and makes no formal rework round.

Every key is one named `check` (K-1.1 .. K-6.2 of docs/tasks/specs/t-631-rn1-2-s3-strategist-no-formal-rounds.md as amended by the
plan critic, B-1..B-6). The defects they pin were all met on one run (LOCAL-1): rows written without the revision mark that code
knows, a `Q101` that is no register id found only after S3 closed, a question the register lacked with no door to raise it.
"""
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import SCRIPTS, check, check_eq, check_in, check_not_in, cleanup, finish, run_script, temp_project  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import coverage_contract  # noqa: E402
import planning_contract as PC  # noqa: E402
import question_register as QR  # noqa: E402

WANT = coverage_contract.COVERAGE_CONTRACT_REVISION
TICKET = "QA-S3"
MD_HEAD = ("---\ntask: " + TICKET + "\n---\n\n## Plan\n\n| TS | what we verify | R | defect hypothesis | impact class | priority | observable | oracle | "
           "disposition + reason | fit | level | technique |\n|---|---|---|---|---|---|---|---|---|---|---|---|\n")


def plan_row(rid="TS-1", **extra):
    """A row that passes `validate_plan` and carries NO revision mark (the role no longer writes it)."""
    row = {"id": rid, "schema_version": 1, "impact": "moderate", "likelihood": "medium", "confidence": "medium",
           "risk_rationale": "shared component", "risk_source_refs": ["R-1"], "risk_policy_revision": "factory-starter-v1",
           "coverage_refs": [], "unknowns": [], "verification_depth": "normal", "required_scenarios": ["opens"],
           "test_level_rationale": "user path", "design_review_required": False, "requirements": ["R-1"], "disposition": "automate",
           "level": "api", "reason": "r", "coverage_obligations": [{"obligation_id": f"OB-{rid}"}],
           "coverage_delta": {"baseline_kind": "initial", "initial_scope_rationale": "no existing case observes it",
                              "entries": [{"obligation_id": f"OB-{rid}", "disposition": "gap", "rationale": "bounded search found nothing",
                                           "gap_reason": "new check awaits Gate A"}],
                              "counts": {"logical_cases_before": 0, "logical_cases_after": 1, "executable_instances_before": 0,
                                         "executable_instances_after": 1}, "planned_instance_ids": [f"planned:{rid}"]}}
    row.update(extra)
    return row


def question(n, **extra):
    q = {"id": f"Q{n}", "question": f"Is it {n}?", "source_says": [{"quote": "x", "where": "AC-1"}],
         "readings": [{"reading": "one", "from": "description", "if_chosen": "c1"}, {"reading": "two", "from": "comment", "if_chosen": "c2"}],
         "severity": "major", "owner_role": "po_ba"}
    q.update(extra)
    return q


def entry(n=1, **extra):
    e = {"key": f"new:{n}", "question": "Is the guest cart kept?", "source_says": [{"quote": "cart", "where": "AC-1"}],
         "readings": [{"reading": "kept", "from": "description", "if_chosen": "keep it"},
                      {"reading": "dropped", "from": "comment", "if_chosen": "drop it"}], "severity": "major", "owner_role": "po_ba"}
    e.update(extra)
    return e


def branch(*keys):
    return {key: {"a": {"level": "api"}, "b": {"level": "integration"}, "not_needed": {}} if key.startswith(("Q", "new")) else {} for key in keys}


def story(prefix, rows, questions=None, mode="new", cells=None):
    """(project, task root): a story whose register holds `questions`, whose plan is `rows`, in plan-contract `mode`."""
    project = temp_project(prefix)
    task = project / "qa-factory" / "artifacts" / TICKET
    for sub in ("work", "state"):
        (task / sub).mkdir(parents=True, exist_ok=True)
    (task / "pipeline.json").write_text(json.dumps({"task": TICKET, "stages": {"S3": {"status": "running"}}}), encoding="utf-8")
    (task / "work" / "requirements-register.md").write_text(
        "## Register\n\n| R | Requirement | source | derived_from | verifiable | ac_ref |\n|---|---|---|---|---|---|\n"
        "| R-1 | the path opens | ac | - | yes | AC-1 |\n", encoding="utf-8")
    (task / "work" / "requirements-readiness.json").write_text(
        json.dumps({"open_questions": [question(n) for n in range(1, 7)] if questions is None else questions}), encoding="utf-8")
    cells = cells or {}
    body = "".join(f"| {r['id']} | what | R-1 | h | degraded | P2 | o | o | {cells.get(r['id'], '`automate` - r')} | | | t |\n"
                   for r in rows if isinstance(r, dict))
    (task / "test-plan.md").write_text(MD_HEAD + body + "\n## Recommended regression\n\nNo regression: the fixture story defends no blast radius\n",
                                       encoding="utf-8")
    (task / "work" / "test-plan.json").write_text(json.dumps({"rows": rows}), encoding="utf-8")
    (task / "state" / "controller.json").write_text(json.dumps({"plan_contract_mode": mode, "coverage_contract_version": 1}), encoding="utf-8")
    return project, task


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def plan_rows(task: Path) -> list:
    return json.loads((task / "work" / "test-plan.json").read_text(encoding="utf-8"))["rows"]


def detect(project):
    return run_script("planning_contract.py", "--root", project, cwd=project)


def refusals(task, rows, **kw):
    found, unread = PC.s3_branch_refusals(task, rows)
    return [f for f in found if not kw or f["kind"] == kw["kind"]], unread


# --- item 1: the revision mark is code's -------------------------------------------------------------------------------------

def test_k1_the_mark() -> None:
    project, task = story("qa-rn12-k1-", [plan_row("TS-1"), plan_row("TS-2")])
    try:
        done = PC.project_plan(task)
        check_eq("K-1.1: every row carries the revision constant after project_plan",
                 ([r.get("coverage_contract_revision") for r in plan_rows(task)], done.wrote, done.problems), ([WANT, WANT], True, []))
        again = PC.project_plan(task)
        check_eq("K-1.1: a second call writes nothing", (again.wrote, again.problems), (False, []))
    finally:
        cleanup(project)
    row_with_new = plan_row("TS-1", question_refs=["new:1"], if_answered=branch("new:1"), new_questions=[entry(1)])
    project, task = story("qa-rn12-k12-", [row_with_new, plan_row("TS-2")])
    try:
        held = {name: sha(task / name) for name in ("work/test-plan.json", "test-plan.md", "work/requirements-readiness.json")}
        result = detect(project)
        check("K-1.2: the detector on the unstamped plan (valid delta, a new: ref) says OK", result.returncode == 0 and "OK:" in result.stdout,
              result.stdout + result.stderr)
        check_eq("K-1.2: ...and writes nothing: plan, human view and register are byte-identical (FR-45; no rename reaches the disk)",
                 {name: sha(task / name) for name in held}, held)
    finally:
        cleanup(project)
    project, task = story("qa-rn12-k13-", [plan_row("TS-1", coverage_contract_revision="coverage-observation-v0")])
    try:
        result = detect(project)
        check("K-1.3: another revision is refused", result.returncode == 1, result.stdout)
        check_in("K-1.3: ...naming the expected revision", "'coverage-observation-v1'", result.stdout)
        check_in("K-1.3: ...and the way out", "remove the field", result.stdout)
        check_eq("K-1.3: ...in ONE line (the bare unsupported-revision line is dropped)",
                 sum("coverage_contract_revision" in line for line in result.stdout.splitlines() if line.startswith("- ")), 1)
    finally:
        cleanup(project)


def test_k14_legacy_and_the_one_predicate() -> None:
    legacy = [{k: v for k, v in plan_row(r).items() if k not in ("coverage_delta",)} for r in ("TS-1", "TS-2")]
    project, task = story("qa-rn12-k14-", legacy, mode="legacy")
    try:
        done = PC.project_plan(task)
        result = detect(project)
        check_eq("K-1.4: legacy mode, no row marked: project_plan writes nothing", (done.wrote, done.problems), (False, []))
        check("K-1.4: ...and the detector is OK (a legacy plan stays legacy)", result.returncode == 0, result.stdout)
    finally:
        cleanup(project)
    mixed = [plan_row("TS-1", coverage_contract_revision=WANT), {k: v for k, v in plan_row("TS-2").items() if k != "coverage_delta"}]
    project, task = story("qa-rn12-k14m-", mixed, mode="legacy")
    try:
        result = detect(project)
        check("K-1.4: legacy, one marked and one not: the unmarked row owes its coverage_delta in the role's context",
              result.returncode == 1 and "TS-2: coverage_delta required" in result.stdout, result.stdout)
    finally:
        cleanup(project)
    # B-5a: ONE predicate with the controller (`is not None` = carries a value, `not value` = unmarked)
    import controller
    cases = {"all absent": [{}, {}], "all empty string": [{"coverage_contract_revision": ""}] * 2, "all None": [{"coverage_contract_revision": None}] * 2,
             "one marked": [{"coverage_contract_revision": WANT}, {}], "empty beside marked": [{"coverage_contract_revision": WANT}, {"coverage_contract_revision": ""}],
             "all marked": [{"coverage_contract_revision": WANT}] * 2}
    for label, rows_ in cases.items():
        for mode in ("legacy", "new"):
            stamped = PC.stamp_revision([dict(r, id=f"TS-{i}") for i, r in enumerate(rows_)], mode)
            try:
                controller.Controller._coverage_contract_revisions(stamped, allow_legacy=(mode == "legacy"))
                gate_a = "passes"
            except Exception:  # noqa: BLE001 - StateConflict
                gate_a = "refuses"
            check_eq(f"K-1.4b parity: {label} / {mode}: gate A on the stamped rows passes (the exit's verdict is gate A's)", gate_a, "passes")
    empty = PC.stamp_revision([{"id": "TS-1", "coverage_contract_revision": ""}, {"id": "TS-2", "coverage_contract_revision": ""}], "legacy")
    check_eq("B-5a: legacy mode with every row \"\" is stamped (the controller counts \"\" as present)",
             [r["coverage_contract_revision"] for r in empty], [WANT, WANT])
    other = PC.stamp_revision([{"id": "TS-1", "coverage_contract_revision": "v0"}, {"id": "TS-2"}], "new")
    check_eq("K-1.1: a value other than the constant is never relabelled", [r["coverage_contract_revision"] for r in other], ["v0", WANT])
    check_eq("K-1.1: a non-list is returned as it is", PC.stamp_revision("x", "new"), "x")


# --- item 2: the question branches are checked in the exit ---------------------------------------------------------------------

def test_k2_the_exit_refuses_branches() -> None:
    bad = plan_row("TS-1", question_refs=["Q101"], if_answered=branch("Q101"))
    project, task = story("qa-rn12-k21-", [bad])
    try:
        result = detect(project)
        check("K-2.1: Q101 against a register of Q1..Q6: exit 1 and a REJECT block that holds it",
              result.returncode == 1 and "REJECT" in result.stdout and "Q101" in result.stdout, result.stdout)
        lines = [line for line in result.stdout.splitlines() if line.startswith("- ") and "`Q101`" in line]
        check_eq("K-2.4: Q101 in question_refs AND in if_answered is ONE line", len(lines), 1)
        check_in("K-2.1/3.4: the line names the door (new:<n> and new_questions) and the register ids", 'new_questions', lines[0])
        check_not_in("K-6.2: and nothing about the revision mark", "coverage_contract_revision", result.stdout)
        check_eq("K-6.2: no REJECT line names a .py command except the waiver line",
                 [l for l in result.stdout.splitlines() if l.startswith("- ") and ".py" in l], [])
    finally:
        cleanup(project)
    project, task = story("qa-rn12-k22-", [plan_row("TS-1", question_refs=["Q101"], if_answered=branch("Q101"))], questions=[])
    try:
        result = detect(project)
        check("K-2.2: a register of ZERO questions: still REJECT, never OK", result.returncode == 1 and "OK:" not in result.stdout, result.stdout)
    finally:
        cleanup(project)
    project, task = story("qa-rn12-k26-", [plan_row("TS-1", question_refs=["Q1"], if_answered=branch("Q1"))])
    try:
        (task / "work" / "requirements-readiness.json").write_text("{not json", encoding="utf-8")
        result = detect(project)
        check("K-2.6: an unreadable register with refs present: UNREADABLE and exit 3, no OK:",
              result.returncode == 3 and "UNREADABLE:" in result.stdout and "OK:" not in result.stdout, result.stdout)
    finally:
        cleanup(project)
    # K-2.5: a recorded S3 waiver quoting the Q101 line passes the stop (the existing waiver reader, one record)
    import waiver
    finding = PC.variant_errors([bad], [question(1)], ())[0]
    pipeline = {"stage_overrides": [{"stage": "S3", "decision": "go on", "match": "TS-1: `Q101` is not a question id of the register"}]}
    blocking, passed = waiver.split_overridden([finding["message"]], pipeline, "S3")
    check_eq("K-2.5: a person's word quoting the head of the Q101 line passes it", (blocking, len(passed)), ([], 1))


def test_k23_every_kind() -> None:
    held = QR.settled
    QR.settled = lambda q: isinstance(q, dict) and q.get("id") == "Q2"      # Q2 is "answered" for the settled_question fixture
    try:
        rows_ = [plan_row("TS-1", question_refs=["Q101"]),                                            # unresolved_ref
                 plan_row("TS-2", oracle_unknown=True),                                               # missing_refs (a sibling row carries refs)
                 plan_row("TS-3", question_refs=["Q1"], if_answered=["Q1"]),                          # bad_branch
                 plan_row("TS-4", question_refs=["Q1"], if_answered={"Q1": {"a": {"level": "api"}, "b": {"coverage_obligations": [{"obligation_id": "OB-OTHER"}]},
                                                                            "not_needed": {}}}),     # invalid_variant
                 plan_row("TS-5", question_refs=["Q3"], if_answered={"Q3": {"a": {"reason": "kept per Q3"}, "b": {}, "not_needed": {}}}),  # stale_reason
                 plan_row("TS-6", question_refs=["Q2"], if_answered=branch("Q2")),                    # settled_question
                 plan_row("TS-7", question_refs=["Q4", "Q5"], if_answered=branch("Q4", "Q5")),        # dependent_pair (both patch level)
                 plan_row("TS-8", question_refs=["Q6"])]                                              # missing_branch
        project, task = story("qa-rn12-k23-", rows_)
        try:
            found, unread = PC.s3_branch_refusals(task, PC.stamp_revision(rows_, "new"))     # the rows as the exit judges them: stamped
            kinds = {f["kind"] for f in found}
            check_eq("K-2.3: s3_branch_refusals reads the register", unread, "")
            check_eq("K-2.3: one fixture row per kind of S3_EXIT_KINDS: every kind is found", sorted(set(PC.S3_EXIT_KINDS) - kinds), [])
            check_eq("K-2.3: ...and each finding starts with the row it is about and says its way out (the owner's rework)",
                     [f["kind"] for f in found if not f["message"].startswith(f["where"]) or "rework repairs" not in f["message"]], [])
            result = detect(project)
            blocks = [l for l in result.stdout.splitlines() if l.startswith("REJECT") and "question-branch problem" in l]
            check_eq("K-2.3: ONE REJECT block for the branch problems", len(blocks), 1)
            check_in("K-2.3: its header counts them and says to repair now", "Repair them now, while S3 still holds the context", blocks[0])
            check_in("K-2.3: the summary line counts question-branch problems", "question-branch problem(s),", result.stdout)
        finally:
            cleanup(project)
    finally:
        QR.settled = held
    project, task = story("qa-rn12-k271-", [plan_row("TS-1", question_refs=["Q101"])])
    try:
        import stage_done
        check_eq("K-2.7: s3_branch_line on a plan with only an unresolved_ref says nothing (the exit refuses it)", stage_done.s3_branch_line(task), "")
    finally:
        cleanup(project)
    # B-4: no_row_for_question stays a WARN: not an exit kind, not a remark
    check("B-4: no_row_for_question is a warn kind, not an exit kind", "no_row_for_question" in PC.S3_WARN_KINDS
          and "no_row_for_question" not in PC.S3_EXIT_KINDS)
    # a plan with no branch field at all and no questions passes unchanged
    project, task = story("qa-rn12-e1-", [plan_row("TS-1")])
    try:
        result = detect(project)
        check("E-1: a plan with zero questions passes the exit unchanged", result.returncode == 0 and "OK:" in result.stdout, result.stdout)
    finally:
        cleanup(project)


# --- item 3: the new: door ---------------------------------------------------------------------------------------------------

def test_k3_the_door() -> None:
    row = plan_row("TS-1", question_refs=["new:1"], if_answered=branch("new:1"), new_questions=[entry(1)])
    project, task = story("qa-rn12-k31-", [row, plan_row("TS-2")], cells={"TS-1": "`unverifiable` - waits for new:1; a: kept, b: dropped"})
    try:
        result = detect(project)
        check("K-3.1: a valid new: entry with its branch passes the exit", result.returncode == 0 and "OK:" in result.stdout, result.stdout)
        done = PC.project_plan(task)
        rows_ = {r["id"]: r for r in plan_rows(task)}
        register = json.loads((task / "work" / "requirements-readiness.json").read_text(encoding="utf-8"))["open_questions"]
        check_eq("K-3.2: the register gains Q7 (it held Q1..Q6)", [q["id"] for q in register][-1:], ["Q7"])
        check_eq("K-3.2: ...with raised_for {row, origin, key, digest}", (register[-1]["raised_for"]["row"], register[-1]["raised_for"]["origin"],
                                                                         register[-1]["raised_for"]["key"]), ("TS-1", "S3-plan", "new:1"))
        check_eq("K-3.2: the row rests on Q7 at the same place, its branch is keyed Q7, and no new_questions is left",
                 (rows_["TS-1"]["question_refs"], list(rows_["TS-1"]["if_answered"]), "new_questions" in rows_["TS-1"]), (["Q7"], ["Q7"], False))
        md = (task / "test-plan.md").read_text(encoding="utf-8")
        check_in("B-1: the human view says Q7 where it said new:1", "waits for Q7; a: kept", md)
        check_not_in("B-1: ...and no new:1 is left in it", "new:1", md)
        before = (sha(task / "work" / "test-plan.json"), sha(task / "work" / "requirements-readiness.json"))
        again = PC.project_plan(task)
        check_eq("K-3.2: a second call writes nothing and raises nothing twice", (again.wrote, again.problems, (sha(task / "work" / "test-plan.json"),
                                                                                       sha(task / "work" / "requirements-readiness.json"))),
                 (False, [], before))
        check_eq("K-3.2: (the first call wrote)", (done.wrote, done.problems), (True, []))
        # B-3: a LATER, different new:1 on the same row is a new question, never the earlier id
        rows2 = plan_rows(task)
        rows2[0].update(question_refs=["Q7", "new:1"], new_questions=[entry(1, question="Is the price refreshed?")])
        rows2[0]["if_answered"]["new:1"] = branch("new:1")["new:1"]
        (task / "work" / "test-plan.json").write_text(json.dumps({"rows": rows2}), encoding="utf-8")
        PC.project_plan(task)
        later = [r for r in plan_rows(task) if r["id"] == "TS-1"][0]
        check_eq("K-3.7: the second, different new:1 on the same row is Q8, not Q7", later["question_refs"], ["Q7", "Q8"])
    finally:
        cleanup(project)
    two = [plan_row("TS-1", question_refs=["new:1"], if_answered=branch("new:1"), new_questions=[entry(1)]),
           plan_row("TS-2", question_refs=["new:1"], if_answered=branch("new:1"), new_questions=[entry(1, question="Is the order kept?")])]
    project, task = story("qa-rn12-k33-", two)
    try:
        check("K-3.3: two rows, each with its own new:1: no unresolved_ref at the exit", not refusals(task, two, kind="unresolved_ref")[0])
        PC.project_plan(task)
        check_eq("K-3.3: ...and Q7 and Q8 after the projection", [r["question_refs"] for r in plan_rows(task)], [["Q7"], ["Q8"]])
    finally:
        cleanup(project)


def test_k34_the_entry_is_checked() -> None:
    def problems(**extra):
        rows_ = [plan_row("TS-1", question_refs=["new:1"], if_answered=branch("new:1"), new_questions=[entry(1, **extra)])]
        project, task = story("qa-rn12-k34-", rows_)
        try:
            return " | ".join(f["message"] for f in refusals(task, rows_)[0])
        finally:
            cleanup(project)
    check_in("K-3.4: one reading is refused naming readings", "readings has fewer than two", problems(readings=[entry()["readings"][0]]))
    no_from = problems(readings=[{"reading": "a", "if_chosen": "c"}, {"reading": "b", "from": "comment", "if_chosen": "c"}])
    check_in("B-2: a reading without `from` is refused (the shape the door tells the role is the shape the checker holds)", "readings[0].from", no_from)
    check_in("B-2: ...and the expected shape lists reading, from, if_chosen", "reading, from, if_chosen", no_from)
    check_in("K-3.4: new:100 is refused naming 1..99", "1 to 99", problems(key="new:100"))
    ok99 = [plan_row("TS-1", question_refs=["new:99"], if_answered=branch("new:99"), new_questions=[entry(99)])]
    project, task = story("qa-rn12-k34b-", ok99)
    try:
        check_eq("K-3.4: new:99 is accepted (AT the limit)", refusals(task, ok99)[0], [])
    finally:
        cleanup(project)
    orphan = [plan_row("TS-1", question_refs=["Q1"], if_answered=branch("Q1"), new_questions=[entry(1)])]
    project, task = story("qa-rn12-e4-", orphan)
    try:
        check_in("E-4: an entry no question_refs names is refused", "named by no question_refs", " | ".join(f["message"] for f in refusals(task, orphan)[0]))
    finally:
        cleanup(project)
    dangling = [plan_row("TS-1", question_refs=["new:1"], if_answered=branch("new:1"))]
    project, task = story("qa-rn12-e3-", dangling)
    try:
        found = refusals(task, dangling)[0]
        check("E-3: a new: ref with no entry is unresolved_ref", any(f["kind"] == "unresolved_ref" and f["question"] == "new:1" for f in found), str(found)[:200])
        done = PC.project_plan(task)
        check("E-3: ...and project_plan refuses to leave it for S4", done.problems and not done.wrote, str(done.problems))
    finally:
        cleanup(project)


def test_k35_failures_are_problems_not_passes() -> None:
    row = plan_row("TS-1", question_refs=["new:1"], if_answered=branch("new:1"), new_questions=[entry(1)])
    project, task = story("qa-rn12-k35-", [row])
    try:
        (task / "work" / "requirements-readiness.json").write_text("{not json", encoding="utf-8")
        held = sha(task / "work" / "test-plan.json")
        done = PC.project_plan(task)
        check_eq("K-3.5: an unreadable register: problems, the plan's sha unchanged", (bool(done.problems), done.wrote, sha(task / "work" / "test-plan.json")),
                 (True, False, held))
    finally:
        cleanup(project)
    project, task = story("qa-rn12-m7-", [row])
    try:
        held_plan = sha(task / "work" / "test-plan.json")
        saved = QR._write_readiness

        def failing(path, data):
            raise OSError("disk")
        QR._write_readiness = failing
        try:
            done = PC.project_plan(task)
        finally:
            QR._write_readiness = saved
        check_eq("K-3.5/M-7: the register write fails: the plan is NOT written (register first, plan second)",
                 (bool(done.problems), sha(task / "work" / "test-plan.json")), (True, held_plan))
    finally:
        cleanup(project)
    project, task = story("qa-rn12-k36-", [row])
    try:
        pipeline = json.loads((task / "pipeline.json").read_text(encoding="utf-8"))
        pipeline["gates"] = {"A": {"gate": "A", "status": "approved", "decision": "approved"}}
        (task / "pipeline.json").write_text(json.dumps(pipeline), encoding="utf-8")
        held = sha(task / "work" / "test-plan.json")
        done = PC.project_plan(task)
        check_eq("K-3.6: gate A approved and a write owed: nothing written, one problem line", (done.wrote, len(done.problems), sha(task / "work" / "test-plan.json")), (False, 1, held))
    finally:
        cleanup(project)
    stamped_plan = [plan_row("TS-1", coverage_contract_revision=WANT)]
    project, task = story("qa-rn12-m5-", stamped_plan)
    try:
        pipeline = json.loads((task / "pipeline.json").read_text(encoding="utf-8"))
        pipeline["gates"] = {"A": {"gate": "A", "status": "approved", "decision": "approved"}}
        (task / "pipeline.json").write_text(json.dumps(pipeline), encoding="utf-8")
        done = PC.project_plan(task)
        check_eq("m-5: gate A approved and NOTHING owed: no problem (the ban applies only when a write is owed)", (done.wrote, done.problems), (False, []))
    finally:
        cleanup(project)


def test_b6_a_candidate_defect_rests_on_a_declared_question() -> None:
    row = plan_row("TS-7", requirements=["R-7"], disposition="unverifiable", question_refs=["new:1"],
                   if_answered={"new:1": {"a": {"disposition": "automate", "level": "api"}, "b": {}, "not_needed": {}}}, new_questions=[entry(1)])
    scoped, virtual, problems = PC.plan_questions_view([row])
    candidate = [{"r": "R-7", "requirement": "x", "file": None, "line": None}]
    check_eq("B-6: the view is clean", problems, [])
    check_eq("B-6: with the virtual question the candidate defect is planned", PC.candidates_without_row(scoped, candidate, virtual), [])
    check_eq("B-6 control: without it the same rows leave the candidate unplanned", len(PC.candidates_without_row(scoped, candidate, [])), 1)
    sig = PC.register_fence.__code__.co_varnames[:3]
    check_eq("B-6: register_fence takes the virtual questions", sig, ("task_root", "rows", "extra_questions"))


def main() -> None:
    test_k1_the_mark()
    test_k14_legacy_and_the_one_predicate()
    test_k2_the_exit_refuses_branches()
    test_k23_every_kind()
    test_k3_the_door()
    test_k34_the_entry_is_checked()
    test_k35_failures_are_problems_not_passes()
    test_b6_a_candidate_defect_rests_on_a_declared_question()
    finish("test_s3_strategist_rounds")


if __name__ == "__main__":
    main()
