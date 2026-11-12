"""test_investigation.py - preservation of what the run left open (P2 M2).

Run from the package root: python -B scripts/tests/test_investigation.py

The story is the TP1-14857 snapshot at the S7 entry (fixtures/investigation-14857/TP1-14857: the 103-event
prefix, four accepted S6 forms, seven refused manual requests). Every test copies it into a temp project and never writes
the fixture; the last key proves the fixture tree is byte-identical after the run.

Keys: K-M2-1, K-M2-1b, K-M2-2, K-M2-2b, K-M2-3, K-M2-4 (both branches + negative control), K-M2-5, K-M2-6, K-M2-7,
K-M2-8, K-M2-9 (budget_problems and the three close_gaps texts), K-M2-E (edges of the evidence refs), K-M2-CLI;
wave 3 (P2 S7 integration): K-W3-1 (wait), K-W3-2 (the seven steps) with K-W3-4 (purity), K-W3-3 (pass_members),
K-W3-5 (CLI + NE28).
Mutation -> killing key (named, not run; the batch canon decides): drop the (b) recompute -> K-M2-1; key targets by
dispatch -> K-M2-2; skip unreadable -> K-M2-6; project over a role line -> K-M2-2b; resolve on NOT_EXECUTED -> K-M2-7
(the shipped fixture rows); `under=""` in the triage judge -> K-M2-7 (the `handoffs/...` evidence input); a fourth
close_gaps why accepted -> K-M2-9; a write of the register outside the writer -> K-M2-1 (the source grep).
"""
import contextlib
import hashlib
import io
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from harness import check, check_eq, cleanup, finish, temp_project  # noqa: E402

import contract as C  # noqa: E402
import exploratory_findings as EF  # noqa: E402
import finalize_task  # noqa: E402
import handoff  # noqa: E402
import controller as CT  # noqa: E402
import investigation as INV  # noqa: E402

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "investigation-14857" / "TP1-14857"
CASES = [f"TC-{n:03d}" for n in range(6, 13)]
TARGETS = [f"case-{case}" for case in CASES] + ["obs-S6-qa-runner-4-0"]
GAP_WHY = "the investigation ended before this target"
ROOTS: list = []


def tree_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if path.is_file():
            digest.update(path.relative_to(root).as_posix().encode("utf-8"))
            digest.update(path.read_bytes())
    return digest.hexdigest()


def story() -> Path:
    root = temp_project()
    ROOTS.append(root)
    task = root / "qa-factory" / "artifacts" / "TP1-14857"
    shutil.copytree(FIXTURE, task)
    return task


def register(task: Path) -> Path:
    return EF.register_path(task)


def file_bytes(task: Path):
    path = register(task)
    return path.read_bytes() if path.exists() else None


def edit(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    assert old in text, f"{old!r} not in {path.name}"
    path.write_text(text.replace(old, new), encoding="utf-8")


def pinned(task: Path, case: str) -> Path:
    """The pinned version file of a case: `case_index` reads the recorded version, not the authoring copy."""
    link = next(link for link in C.story_case_links(task) if link["case_id"] == case)
    return task / link["path"]


def runner_text(task: Path, n: int) -> str:
    return (task / "work" / "handoffs" / f"S6-qa-runner-{n}.yaml").read_text(encoding="utf-8")


def line_of(task: Path, target: str) -> dict:
    return EF.read(task)["active"][target]


def role_correct(task: Path, target: str, **over) -> str:
    """A role's own `correct` of the active line of a target (in-process, as the register's writer allows)."""
    active = line_of(task, target)
    line = {"op": "correct", "kind": active["kind"], "title": active["title"], "statement": "the role's own words",
            "why_not_a_bug": "the role looked", "evidence_refs": [{"path": active["evidence_refs"][0]["path"]}],
            "origin": {"dispatch": "S7-qa-failure-analyst-1", "target": target},
            "corrects": {"id": active["id"], "reason": "the role looked at it"}}
    for key in ("question", "owner_role", "missing_prerequisite"):
        if key in active:
            line[key] = active[key]
    line.update(over)
    return EF.append(task, line, by="S7-qa-failure-analyst-1")


def role_withdraw(task: Path, target: str) -> str:
    active = line_of(task, target)
    return EF.append(task, {"op": "withdraw", "withdraws": {"id": active["id"], "reason": "not a finding"},
                            "origin": active["origin"]}, by="S7-qa-failure-analyst-1")


def cli(*argv):
    """main() in-process: (code, stdout, stderr). SystemExit (argparse) is the exit code, as in a real run."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = INV.main([str(item) for item in argv])
        except SystemExit as stop:
            code = stop.code
    return code, out.getvalue(), err.getvalue()


def register_ok(task: Path) -> bool:
    """`exploratory_findings.py check` exits 0: every damaged line and every stale ref would make it 2."""
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        return EF.main(["check", "--task-root", str(task)]) == 0


def ids(found) -> list:
    return [target["id"] for target in found["targets"]]


def main() -> None:
    before_fixture = tree_hash(FIXTURE)
    try:
        key_targets_and_projection()
        key_no_targets()
        key_idempotent_and_role_words()
        key_no_question()
        key_finalize_task()
        key_close_gaps()
        key_close_gaps_resolved()
        key_unreadable()
        key_b1_words()
        key_b1_record_words()
        key_unresolved()
        key_writer_missing()
        key_budget_and_why()
        key_evidence_edges()
        key_cli()
        key_w3_wait()
        key_w3_decision()
        key_w3_pass_members()
        key_w3_cli()
        key_settled_open_target_not_reinvestigated()
        key_project_skips_settled_bug()
        check_eq("the fixture tree is byte-identical after the run (no test wrote it)", tree_hash(FIXTURE), before_fixture)
    finally:
        for root in ROOTS:
            cleanup(root)
    finish("test_investigation")


# --- K-M2-1 -----------------------------------------------------------------------------------------------------------

def key_targets_and_projection() -> None:
    task = story()
    found = INV.investigation_targets(task)
    check_eq("K-M2-1 fixture targets = case-TC-006..TC-012 + obs-S6-qa-runner-4-0 (8)", ids(found), TARGETS)
    check_eq("K-M2-1 nothing unreadable on the fixture", found["unreadable"], [])
    check("K-M2-1 investigation_targets wrote no register", file_bytes(task) is None)
    by_id = {target["id"]: target for target in found["targets"]}
    check_eq("K-M2-1 a refused case with a runner row has sources a+b", by_id["case-TC-006"]["sources"], ["a", "b"])
    check_eq("K-M2-1 the obs target has source a alone", by_id["obs-S6-qa-runner-4-0"]["sources"], ["a"])
    check_eq("K-M2-1 the question of a refused case is its first gap id", by_id["case-TC-007"]["question"], "Q2")
    check_eq("K-M2-1 no (c) target: the seven stale triage rows add none", sum(1 for t in found["targets"]
             if t["id"].startswith("case-")), 7)
    out = INV.project(task, "S7-qa-failure-analyst-1")
    check_eq("K-M2-1 project adds one line per target", len(out["added"]), 8)
    check_eq("K-M2-1 project corrected nothing, skipped nothing, printed nothing", (out["corrected"], out["skipped"], out["printed"]),
             ([], [], []))
    state = EF.read(task)
    check_eq("K-M2-1 the register holds the eight lines and no damaged one", (len(state["lines"]), state["unreadable"]), (8, []))
    for target in found["targets"]:
        if "a" not in target["sources"]:
            continue
        form = handoff.parse(runner_text(task, int(target["dispatch"].rsplit("-", 1)[1])))
        observed = form.data["manual_observations"][target["index"]]["observed"]
        line = state["active"][target["id"]]
        check(f"K-M2-1 {target['id']} statement == observed, byte for byte", line["statement"] == observed and observed != "")
    tc6 = state["active"]["case-TC-006"]
    check("K-M2-1 case-TC-006 statement is the runner's words", tc6["statement"].startswith("Code datasource COMPLETED, ")
          and tc6["statement"].endswith("the failed run left the index data deleted."))
    check_eq("K-M2-1 a refused case with a question is an unresolved_question, asked in the question's WORDS (its id is in refs)",
             (tc6["kind"], tc6["question"].startswith("Should a failed or guardrail-blocked manual reindex move Last indexed"),
              tc6["owner_role"]), ("unresolved_question", True, INV.OWNER_WORDS))
    check_eq("K-M2-1 oracle_status owner_question, status unverified, no probe", (tc6["oracle_status"], tc6["verification_status"],
             tc6["probe"]), ("owner_question", "unverified", None))
    check_eq("K-M2-1 refs are the case, its requirement ids and the question's id", tc6["refs"], ["TC-006", "R-16", "Q1"])
    check_eq("K-M2-1 the line is recorded by code and carries its origin", (tc6["recorded_by"], tc6["origin"]),
             ("code:investigation.project", {"dispatch": "S7-qa-failure-analyst-1", "target": "case-TC-006"}))
    paths = [ref["path"] for ref in tc6["evidence_refs"]]
    check_eq("K-M2-1 evidence = the carriers then the row's named file", paths, [
        "work/handoffs/S6-qa-runner-1.yaml", "work/evidence/manual/TC-006/request.json",
        "work/evidence/manual/TC-006/a1/005-request-response.json"])
    check_eq("K-M2-1 the why is the runner's verbatim reason", tc6["why_not_a_bug"].split(",")[0],
             "Expected value is an open owner question (OQ-4)")
    obs = state["active"]["obs-S6-qa-runner-4-0"]
    check_eq("K-M2-1 a multi-case row (not one pin) is an observation with no refs", (obs["kind"], obs["oracle_status"], obs["refs"]),
             ("observation", "none", []))

    # a `passed` row, a refusal with no open gap, a TEST_BUG triage row are NOT targets
    task2 = story()
    edit(task2 / "work" / "handoffs" / "S6-qa-runner-1.yaml", "\n# Rows blocked by the stand",
         "\n  - case: TC-001\n    then: \"passes\"\n    observed: \"it passed\"\n    before_change: \"x\"\n    result: passed\n"
         "    evidence: work/evidence/manual/TC-006/a1/005-request-response.json\n    why_inconclusive: \"\"\n"
         "\n# Rows blocked by the stand")
    case7 = pinned(task2, "TC-007")                                                # TC-007's question is answered
    edit(case7, "R-15", "R-1")
    edit(case7, '"source": "unknown", "ref": "Q2"', '"source": "spec", "ref": ""')
    triage = json.loads((task2 / "work" / "triage.json").read_text(encoding="utf-8"))
    triage["triage"].append({"test": "TC-001", "case": "TC-001", "verdict": "TEST_BUG", "evidence": "evidence/manual/TC-006/request.json"})
    (task2 / "work" / "triage.json").write_text(json.dumps(triage), encoding="utf-8")
    found2 = INV.investigation_targets(task2)
    by2 = {target["id"]: target for target in found2["targets"]}
    check_eq("K-M2-1 passed row / TEST_BUG row are not targets (still 8)", ids(found2), TARGETS)
    check_eq("K-M2-1 a refusal whose expectation_gaps is [] is no (b) source: TC-007 is (a) alone",
             (by2["case-TC-007"]["sources"], by2["case-TC-007"]["question"]), (["a"], None))
    INV.project(task2, "S7-x")
    tc7 = line_of(task2, "case-TC-007")
    check_eq("K-M2-1 an (a)-only case is an observation with oracle none", (tc7["kind"], tc7["oracle_status"]), ("observation", "none"))

    # the writer is the only door to the register file
    source = (Path(INV.__file__)).read_text(encoding="utf-8")
    check("K-M2-1 AR-13/AR-14: investigation.py names no register file and has no file write",
          "exploratory-findings.jsonl" not in source and ".write_text(" not in source and ".write_bytes(" not in source
          and "open(" not in source)
    check("K-M2-1 AR-1: no verdict word list in investigation.py", "NOT_EXECUTED" not in source and "APP_BUG" not in source)


# --- K-M2-1b ----------------------------------------------------------------------------------------------------------

def key_no_targets() -> None:
    root = temp_project()
    ROOTS.append(root)
    task = root / "qa-factory" / "artifacts" / "TP1-QUIET"
    (task / "work").mkdir(parents=True)
    (task / "pipeline.json").write_text(json.dumps({"gates": {"A": {"status": "approved"}, "B": {}}, "stages": {}}), encoding="utf-8")
    out = INV.project(task, "S7-x")
    check_eq("K-M2-1b no S6 form and no refusal: nothing added/corrected/skipped/printed", out,
             {"added": [], "corrected": [], "skipped": [], "printed": []})
    check("K-M2-1b zero targets writes no register file", file_bytes(task) is None)
    check_eq("K-M2-1b close_gaps of an absent register writes nothing", INV.close_gaps(task, GAP_WHY), [])
    check("K-M2-1b ... and no file", file_bytes(task) is None)

    task2 = story()                                    # zero accepted S6 dispatches: (a) empty, (b) still read
    (task2 / "state" / "events.jsonl").unlink()
    found = INV.investigation_targets(task2)
    check_eq("K-M2-1b zero accepted dispatches: the seven refusals are still targets, source b alone",
             (ids(found), {tuple(t["sources"]) for t in found["targets"]}), ([f"case-{c}" for c in CASES], {("b",)}))
    INV.project(task2, "S7-x")
    line = line_of(task2, "case-TC-006")
    check_eq("K-M2-1b a (b)-alone target says it was not observed and shows the refusal reason",
             (line["statement"], line["why_not_a_bug"].startswith("expectation unconfirmed")), (INV.NOT_OBSERVED_B, True))
    check("K-M2-1b ... the Then comes from the case file, not a placeholder", line["title"] != INV.NO_THEN and line["title"] != "case-TC-006")


# --- K-M2-2 / 2b ------------------------------------------------------------------------------------------------------

def key_idempotent_and_role_words() -> None:
    task = story()
    INV.project(task, "S7-a")
    first = file_bytes(task)
    again = INV.project(task, "S7-a")
    check_eq("K-M2-2 project twice: added == [] and nothing corrected", (again["added"], again["corrected"]), ([], []))
    check("K-M2-2 project twice: the file is byte-identical", file_bytes(task) == first)
    third = INV.project(task, "S7-another-dispatch")
    check("K-M2-2 a later dispatch id adds nothing either (ids are the target, not the dispatch)",
          third["added"] == [] and file_bytes(task) == first)

    role_correct(task, "case-TC-006")
    role_withdraw(task, "case-TC-007")
    mid = file_bytes(task)
    out = INV.project(task, "S7-a")
    check("K-M2-2b role correct, role withdraw, then project: 0 lines", out["added"] == [] and out["corrected"] == [] and file_bytes(task) == mid)
    check_eq("K-M2-2b both are skipped, by name, no refusal", sorted(out["skipped"]), ["case-TC-006", "case-TC-007"])

    task2 = story()                                    # a changed observation -> exactly one code `correct`
    INV.project(task2, "S7-a")
    count = len(EF.read(task2)["lines"])
    edit(task2 / "work" / "handoffs" / "S6-qa-runner-1.yaml", "not observed: same stand setting as TC-007",
         "now observed: the queue formed after all")
    out = INV.project(task2, "S7-b")
    after = EF.read(task2)
    check_eq("K-M2-2b a changed observed -> exactly one code correct", (len(out["corrected"]), out["added"], len(after["lines"])),
             (1, [], count + 1))
    last = after["lines"][-1]
    check_eq("K-M2-2b ... op correct by code, of the target's old line, with the new words", (last["op"], last["recorded_by"],
             last["statement"].startswith("now observed: the queue formed")), ("correct", "code:investigation.project", True))
    check_eq("K-M2-2b ... the target still has ONE active line", sum(1 for line in after["active"].values()
             if line["origin"]["target"] == "case-TC-008"), 1)
    again = INV.project(task2, "S7-b")
    check("K-M2-2b ... and a second project after it adds nothing", again["added"] == [] and again["corrected"] == []
          and len(EF.read(task2)["lines"]) == count + 1)


# --- K-M2-3 -----------------------------------------------------------------------------------------------------------

def key_no_question() -> None:
    task = story()
    case8 = pinned(task, "TC-008")                      # no linked question: an open Then with no ref
    edit(case8, "R-13", "R-1")
    edit(case8, '"source": "unknown", "ref": "Q3"', '"source": "unknown", "ref": ""')
    found = INV.investigation_targets(task)
    target = {t["id"]: t for t in found["targets"]}["case-TC-008"]
    check_eq("K-M2-3 a (b) target whose gaps carry no id has question None", (target["sources"], target["question"]), (["a", "b"], None))
    INV.project(task, "S7-x")
    line = line_of(task, "case-TC-008")
    check_eq("K-M2-3 it is an observation with oracle_status owner_question, not a refusal",
             (line["kind"], line["oracle_status"], "question" in line), ("observation", "owner_question", False))
    check_eq("K-M2-3 the register accepted all eight lines", len(EF.read(task)["lines"]), 8)


# --- K-M2-4 -----------------------------------------------------------------------------------------------------------

def key_finalize_task() -> None:
    task = story()                                     # (i) no product failure: the `:724-726` branch
    INV.project(task, "S7-x")
    before = file_bytes(task)
    finalize_task.refresh(task)
    check("K-M2-4 (i) refresh on the fixture leaves the register byte-identical", file_bytes(task) == before)
    triage = json.loads((task / "work" / "triage.json").read_text(encoding="utf-8"))
    archive = sorted((task / "state" / "migration").glob("stale-triage-*.json"))
    check_eq("K-M2-4 (i) the branch ran: the seven analyst rows were archived 'current failures repaired'",
             (triage["triage"], [json.loads(p.read_text(encoding="utf-8"))["reason"] for p in archive]),
             ([], ["current failures repaired"]))

    task2 = story()                                    # (ii) one failing result row + triage rows no failure binds: `:717-719`
    INV.project(task2, "S7-x")
    before2 = file_bytes(task2)
    block = sorted((task2 / "work" / "run-blocks").glob("*.json"))[-1]
    data = json.loads(block.read_text(encoding="utf-8"))
    data["results"][0]["status"] = "failed"
    data["results"][0]["reason"] = "AssertionError: a failure for the second branch"
    block.write_text(json.dumps(data), encoding="utf-8")
    report = finalize_task.refresh(task2)
    check_eq("K-M2-4 (ii) the run now has a product failure", report["execution_status"], "failed")
    check("K-M2-4 (ii) refresh leaves the register byte-identical", file_bytes(task2) == before2)
    archives = sorted((task2 / "state" / "migration").glob("stale-triage-*.json"))
    check_eq("K-M2-4 (ii) negative control: the unbound triage rows ARE archived in the same run, by the other reason",
             [(json.loads(p.read_text(encoding="utf-8"))["reason"], len(json.loads(p.read_text(encoding="utf-8"))["rows"]))
              for p in archives], [("not bound to current failure", 7)])


# --- K-M2-5 -----------------------------------------------------------------------------------------------------------

def key_close_gaps() -> None:
    task = story()
    INV.project(task, "S7-x")
    role_correct(task, "case-TC-006")
    printed: list = []
    written = INV.close_gaps(task, GAP_WHY, printed)
    state = EF.read(task)
    check_eq("K-M2-5 close_gaps: one correct per un-investigated target, none for the role-touched one",
             (len(written), printed), (7, []))
    gaps = {key: line for key, line in state["active"].items() if line["kind"] == "coverage_gap"}
    check_eq("K-M2-5 the seven are coverage_gaps, the role's line is not", sorted(gaps), [t for t in TARGETS if t != "case-TC-006"])
    sample = gaps["case-TC-007"]
    check_eq("K-M2-5 a gap carries its prerequisite, stays unverified, is recorded by code",
             (sample["missing_prerequisite"], sample["verification_status"], sample["recorded_by"], sample["op"]),
             (f"not investigated - {GAP_WHY}", "unverified", "code:investigation.close_gaps", "correct"))
    check_eq("K-M2-5 the correct names its reason", sample["corrects"]["reason"], GAP_WHY)
    check_eq("K-M2-5 the active map still holds ONE line per target", (len(state["active"]), sorted(state["active"])), (8, TARGETS))
    twice = INV.close_gaps(task, GAP_WHY)
    check("K-M2-5 twice: no new line", twice == [] and len(EF.read(task)["lines"]) == len(state["lines"]))
    other = INV.close_gaps(task, "gate B is already decided")
    check_eq("K-M2-5 a different why: one more correct per gap", len(other), 7)
    check_eq("K-M2-5 ... and still one active line per target", len(EF.read(task)["active"]), 8)
    project_again = INV.project(task, "S7-y")
    check("K-M2-5 a second S7 life: project adds nothing over the gaps", project_again["added"] == [] and project_again["corrected"] == [])
    try:
        INV.close_gaps(task, "a second investigation in one S7 chain is not run")
        refused = ""
    except ValueError as exc:
        refused = str(exc)
    check("K-M2-5 an unknown why is refused naming the three texts", all(text in refused for text in INV.WHY_TEXTS))

    task2 = story()                                    # the refs are re-hashed now; vanished paths are dropped
    INV.project(task2, "S7-x")
    evidence = task2 / "work" / "evidence" / "manual" / "TC-006" / "a1" / "005-request-response.json"
    evidence.write_bytes(evidence.read_bytes() + b" ")
    (task2 / "work" / "evidence" / "manual" / "TC-009" / "a1" / "001-request-response.json").unlink()
    for gone in ("work/handoffs/S6-qa-runner-3.yaml", "work/evidence/manual/TC-010/request.json",
                 "work/evidence/manual/TC-010/a1/017-request-response.json"):
        (task2 / gone).unlink()
    printed2: list = []
    written2 = INV.close_gaps(task2, GAP_WHY, printed2)
    after = EF.read(task2)["active"]
    new_hash = hashlib.sha256(evidence.read_bytes()).hexdigest()
    check_eq("K-M2-5 a changed file is re-hashed now", {r["path"]: r["sha256"] for r in after["case-TC-006"]["evidence_refs"]}
             ["work/evidence/manual/TC-006/a1/005-request-response.json"], new_hash)
    check_eq("K-M2-5 a path that is no longer a file is dropped from the ref list",
             [r["path"] for r in after["case-TC-009"]["evidence_refs"]],
             ["work/handoffs/S6-qa-runner-1.yaml", "work/evidence/manual/TC-009/request.json"])
    check("K-M2-5 a target whose every path vanished is skipped and printed, its line left as it was",
          after["case-TC-010"]["kind"] == "unresolved_question" and len(written2) == 7
          and any("case-TC-010" in line for line in printed2))
    check("K-M2-5 no ref that does not hash was written", all(C.evidence_ref_issue(task2, ref) == "" for line in after.values() if line["kind"] == "coverage_gap"
                  for ref in line["evidence_refs"]))


# --- K-M2-6 -----------------------------------------------------------------------------------------------------------

def key_unreadable() -> None:
    task = story()
    bad = task / "work" / "handoffs" / "S6-qa-runner-2.yaml"
    bad.write_bytes(b"manual_observations:\n  - case: TC-011\n    observed: \xff\xfe broken \x80\n")
    found = INV.investigation_targets(task)
    check_eq("K-M2-6 a form that cannot be read is unreadable, never skipped", [record for record, _ in found["unreadable"]],
             ["work/handoffs/S6-qa-runner-2.yaml"])
    out = INV.project(task, "S7-x")
    check("K-M2-6 a printed line names the file", any("work/handoffs/S6-qa-runner-2.yaml" in line for line in out["printed"]))
    gap = EF.read(task)["active"].get("gap-work/handoffs/S6-qa-runner-2.yaml")
    check_eq("K-M2-6 and one coverage_gap names it, with the file as its evidence",
             (gap["kind"], gap["statement"], gap["missing_prerequisite"], [r["path"] for r in gap["evidence_refs"]]),
             ("coverage_gap", "the factory could not read the test runner's hand-back",
              "a readable copy of the test runner's hand-back", ["work/handoffs/S6-qa-runner-2.yaml"]))
    size = len(EF.read(task)["lines"])
    again = INV.project(task, "S7-x")
    check("K-M2-6 once per record: a second project adds no second gap", again["added"] == [] and len(EF.read(task)["lines"]) == size)
    check_eq("K-M2-6 the other targets still projected (TC-011/TC-012 stay refusals)",
             sorted(key for key in EF.read(task)["active"] if key.startswith("case-")), [f"case-{c}" for c in CASES])

    task2 = story()                                    # an unreadable request, and a case index that raises
    (task2 / "work" / "evidence" / "manual" / "TC-007" / "request.json").write_text("{not json", encoding="utf-8")
    found2 = INV.investigation_targets(task2)
    check_eq("K-M2-6 an unreadable request.json is unreadable too", [record for record, _ in found2["unreadable"]],
             ["work/evidence/manual/TC-007/request.json"])
    check("K-M2-6 ... and the case is no (b) source", {t["id"]: t for t in found2["targets"]}["case-TC-007"]["sources"] == ["a"])
    task3 = story()
    pinned(task3, "TC-006").write_text("---\nid: TC-099\n---\nbroken\n", encoding="utf-8")
    found3 = INV.investigation_targets(task3)
    check_eq("K-M2-6 case_index raising ValueError: ONE unreadable record 'the case files', no (b) target",
             ([record for record, _ in found3["unreadable"]], any("b" in t["sources"] for t in found3["targets"])),
             ([INV.CASE_FILES], False))
    out3 = INV.project(task3, "S7-x")
    check("K-M2-6 ... printed, and one gap line with pipeline.json as its evidence", any(INV.CASE_FILES in line for line in out3["printed"])
          and EF.read(task3)["active"]["gap-" + INV.CASE_FILES]["evidence_refs"][0]["path"] == "pipeline.json")


# --- K-B1-c / K-B1-d (critic t-1579 B1, HF8-20: what the register says reaches a person) ----------------------------------------

PATH_SHAPES = ("work/", ".yaml", ".json", ".jsonl", "\\")


def key_b1_words() -> None:
    import question_register
    task = story()
    INV.project(task, "S7-qa-failure-analyst-1")
    rows = {q["id"]: q for q in question_register.load(task)["questions"]}
    tc6 = line_of(task, "case-TC-006")
    check_eq("K-B1-c the question is the question row's WORDS, read through question_register.load", tc6["question"], rows["Q1"]["question"])
    check("K-B1-c ... its id is kept in refs, and nowhere in the question or the owner", "Q1" in tc6["refs"] and "Q1" not in tc6["question"].split()
          and "Q1" not in tc6["owner_role"])
    check_eq("K-B1-c the owner is words, with no question id", tc6["owner_role"], INV.OWNER_WORDS)
    for target, line in EF.read(task)["active"].items():
        for field in ("why_not_a_bug", "title"):
            check(f"K-B1-c {target} {field}: no path shape", not any(shape in str(line.get(field)) for shape in PATH_SHAPES), str(line.get(field))[:120])
    # `statement` is the runner's own words, verbatim (K-M2-1); the report scrubs it at render time. The statement the CODE composes
    # (a refused case with no runner row) is checked here.
    own = story()
    (own / "state" / "events.jsonl").unlink()
    INV.project(own, "S7-x")
    for target, line in EF.read(own)["active"].items():
        check(f"K-B1-c {target}: the code's own statement is {INV.NOT_OBSERVED_B!r} and holds no path shape",
              line["statement"] == INV.NOT_OBSERVED_B and not any(shape in line["statement"] for shape in PATH_SHAPES), line["statement"][:100])
    # a question row that cannot be read: the gap's own words, else the fixed sentence; never the id
    broken = story()
    (broken / "work" / "requirements-readiness.json").write_text("{not json", encoding="utf-8")
    INV.project(broken, "S7-x")
    words = line_of(broken, "case-TC-006").get("question")
    check("K-B1-c an unreadable question register: still words, no bare id", bool(words) and words != "Q1", str(words))
    check_eq("K-B1-c ... _question_words: no row -> the case and the fixed sentence, never the gap's words that name the question id (decision A)",
             INV._question_words(broken, {"question": "Q99", "case": "TC-006", "question_words": "its question Q99 is not answered"},
                                 {"loaded": {}}), "TC-006 - " + INV.QUESTION_FALLBACK)
    check_eq("K-B1-c ... and with no case the sentence alone",
             INV._question_words(broken, {"question": "Q99", "question_words": "its question Q99 is not answered"}, {"loaded": {}}),
             INV.QUESTION_FALLBACK)
    check("K-B1-c ... the written line names the case and no question id", words.startswith("TC-006 - ") and "Q1" not in words, str(words))
    # the fallback why of an observation the runner left with no reason
    check_eq("K-B1-c the fallback why carries no dispatch id and no path", INV.OPEN_WHY, "the runner left this open and nobody has looked into it yet")
    fields = INV._fields(task, dict(INV._blank_target("obs-S6-qa-runner-9-0"), sources=["a"], carrier=["work/handoffs/S6-qa-runner-1.yaml"]), [])
    check_eq("K-B1-c _fields: no why_inconclusive and no refusal -> OPEN_WHY", fields["why_not_a_bug"], INV.OPEN_WHY)


def key_b1_record_words() -> None:
    task = story()
    (task / "state" / "events.jsonl").write_text("{not json\n", encoding="utf-8")
    found = INV.investigation_targets(task)
    check("K-B1-d setup: the event journal is unreadable (a record we could not read)", "state/events.jsonl" in [r for r, _ in found["unreadable"]],
          str(found["unreadable"]))
    out = INV.project(task, "S7-x")
    gap = EF.read(task)["active"]["gap-state/events.jsonl"]
    for field in ("title", "statement", "missing_prerequisite"):
        check(f"K-B1-d gap {field}: the story's event journal, no path", "the story's event journal" in gap[field]
              and not any(shape in gap[field] for shape in PATH_SHAPES), gap[field])
    check_eq("K-B1-d the why keeps the class and drops the exception text", gap["why_not_a_bug"], INV.RECORD_GAP_WHY)
    check("K-B1-d ... the role channel (printed) still carries the record and the reason", any("state/events.jsonl" in line for line in out["printed"]))
    for record, words in (("state/events.jsonl", "the story's event journal"), ("pipeline.json", "the story's stage record"),
                          ("work/handoffs/S6-qa-runner-2.yaml", "the test runner's hand-back"),
                          ("work/evidence/manual/TC-007/request.json", "the manual-check request of TC-007"),
                          ("work/manual/TC-007/request.json", "the manual-check request of TC-007"), (INV.CASE_FILES, INV.CASE_FILES),
                          ("work/evidence/a/b.png", "the evidence record"), ("state\\other.json", INV.ANY_RECORD), ("C:\\x\\y.json", INV.ANY_RECORD),
                          ("/abs/path.yaml", INV.ANY_RECORD), ("", INV.ANY_RECORD), (None, INV.ANY_RECORD)):
        check_eq(f"K-B1-d _record_words({record!r})", INV._record_words(record), words)
    for hostile in ("state/events.jsonl", "pipeline.json", "C:\\x\\work\\a.json", "/abs/work/handoffs/S6-qa-runner-1.yaml", "work/a/b/c.json"):
        check(f"K-B1-d _record_words never returns a path shape: {hostile[-22:]}", not any(shape in INV._record_words(hostile) for shape in PATH_SHAPES))


# --- K-M2-7 -----------------------------------------------------------------------------------------------------------

def key_close_gaps_resolved() -> None:
    """t-114 F1: `close_gaps` gaps only the UNRESOLVED code-only chains. Kill (named, not run): drop the `resolved` skip in
    `close_gaps` -> every assertion on the mixed state below (the resolved TC-007..TC-010 turn into gaps, n != k + g)."""
    shipped = json.loads(INV.BUDGET_PATH.read_text(encoding="utf-8"))
    adding = dict(shipped, resolving_verdicts=list(shipped["resolving_verdicts"]) + ["ENV_ISSUE"])
    task = story()
    INV.project(task, "S7-x")
    found = INV.open_targets(task, adding)
    resolved = sorted(t for t, _ in found["resolved"])
    waiting = sorted(t["id"] for t in found["unresolved"])
    check("K-F1 the mixed state is real: ENV_ISSUE rows with evidence resolve, others wait",
          "case-TC-007" in resolved and "case-TC-006" in waiting and len(resolved) + len(waiting) == 8, f"{resolved} / {waiting}")
    written = INV.close_gaps(task, GAP_WHY, budget=adding)
    gapped = sorted(t for t, line in EF.read(task)["active"].items() if line["kind"] == "coverage_gap")
    check_eq("K-F1 only the UNRESOLVED targets are gapped (n = k + g: every waiting target is a gap, no resolved one is)",
             (gapped, len(written)), (waiting, len(waiting)))
    check("K-F1 a resolved target keeps its observation (projected, not gapped)",
          all(EF.read(task)["active"][t]["kind"] != "coverage_gap" for t in resolved))
    # the same state through the other inputs: the computed unresolved set, and a budget nobody can read
    task2 = story()
    INV.project(task2, "S7-x")
    got = INV.close_gaps(task2, GAP_WHY, unresolved=[t for t in INV.open_targets(task2, adding)["unresolved"]])
    check_eq("K-F1 the caller's own unresolved set is honoured (targets or ids)", len(got), len(waiting))
    task3 = story()
    INV.project(task3, "S7-x")
    check_eq("K-F1 an unreadable budget resolves nothing (FR-59): every code-only chain is a gap",
             len(INV.close_gaps(task3, GAP_WHY, budget={})), 8)
    task4 = story()
    INV.project(task4, "S7-x")
    set_triage(task4, "TC-006", verdict="APP_BUG")
    check_eq("K-F1 with neither budget nor set, the shipped budget decides: an APP_BUG row with evidence is not gapped",
             (len(INV.close_gaps(task4, GAP_WHY)), EF.read(task4)["active"]["case-TC-006"]["kind"] != "coverage_gap"), (7, True))
    # load_budget: one reader, one rule
    budget, problems = INV.load_budget()
    check_eq("K-F1 load_budget reads the shipped file and finds it valid", (budget == shipped, problems), (True, []))
    saved = INV.BUDGET_PATH
    try:
        INV.BUDGET_PATH = task / "no-such-budget.json"
        check_eq("K-F1 load_budget on an absent file: (None, ['cannot be read'])", INV.load_budget(), (None, ["cannot be read"]))
    finally:
        INV.BUDGET_PATH = saved
    check_eq("K-F1 load_budget of another plugin root reads THAT root's file", INV.load_budget(task)[0], None)


def set_triage(task: Path, case: str, **fields) -> None:
    path = task / "work" / "triage.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    for row in data["triage"]:
        if row["case"] == case:
            row.update(fields)
    path.write_text(json.dumps(data), encoding="utf-8")


def key_unresolved() -> None:
    budget = {"resolving_verdicts": ["APP_BUG", "TEST_BUG"]}
    task = story()
    out = INV.unresolved_targets(task, budget)
    check_eq("K-M2-7 NOT_EXECUTED and ENV_ISSUE rows resolve nothing: all eight stay unresolved",
             ([t["id"] for t in out["unresolved"]], out["resolved"]), (TARGETS, []))
    check("K-M2-7 ... their rows are attached as context lines (verdict, evidence path)",
          "triage NOT_EXECUTED (evidence/manual/TC-006/a1/steps.jsonl)" in out["context"]["case-TC-006"][0]
          and "triage ENV_ISSUE (evidence/manual/TC-007/request.json)" in out["context"]["case-TC-007"][0]
          and "env_fix" in out["context"]["case-TC-007"][0] and "obs-S6-qa-runner-4-0" not in out["context"])

    # m9: the SHIPPED budget is the data that keeps NOT_EXECUTED / ENV_ISSUE unresolved (a copy of K-M3-1c's pin), and the
    # rule is data-driven: a budget copy that adds ENV_ISSUE makes the ENV_ISSUE row, whose evidence file exists, resolve
    shipped = json.loads(INV.BUDGET_PATH.read_text(encoding="utf-8"))      # (`budget` here is the local dict above)
    check("K-M2-7 m9 the shipped resolving_verdicts holds neither NOT_EXECUTED nor ENV_ISSUE (and holds APP_BUG)",
          not {"NOT_EXECUTED", "ENV_ISSUE"} & set(shipped["resolving_verdicts"]) and "APP_BUG" in shipped["resolving_verdicts"])
    out = INV.unresolved_targets(task, shipped)
    check_eq("K-M2-7 m9 on the shipped budget the NOT_EXECUTED and ENV_ISSUE rows resolve nothing", out["resolved"], [])
    out = INV.unresolved_targets(task, dict(shipped, resolving_verdicts=list(shipped["resolving_verdicts"]) + ["ENV_ISSUE"]))
    resolved = [target for target, _ in out["resolved"]]
    check("K-M2-7 m9 a budget copy that adds ENV_ISSUE resolves the ENV_ISSUE rows with evidence (the data decides, not the code), "
          "and still not the NOT_EXECUTED one", "case-TC-007" in resolved and "case-TC-006" not in resolved
          and all(INV.unresolved_targets(task, shipped)["resolved"] == [] for _ in (0,)), str(resolved))

    set_triage(task, "TC-006", verdict="APP_BUG")      # a resolving verdict WITH an existing evidence file
    out = INV.unresolved_targets(task, budget)
    check_eq("K-M2-7 an APP_BUG row with an existing evidence file resolves its case", [target for target, _ in out["resolved"]],
             ["case-TC-006"])
    check("K-M2-7 ... and only that case", "case-TC-006" not in [t["id"] for t in out["unresolved"]] and len(out["unresolved"]) == 7)
    check_eq("K-M2-7 a budget with no resolving_verdicts list resolves nothing (safe side)",
             [INV.unresolved_targets(task, bad)["resolved"] for bad in ({}, None, {"resolving_verdicts": "APP_BUG"},
                                                                          {"resolving_verdicts": [3]})], [[], [], [], []])

    (task / "work" / "evidence" / "manual" / "TC-006" / "a1" / "steps.jsonl").unlink()
    out = INV.unresolved_targets(task, budget)
    words = C.evidence_ref_issue(task / "work", {"path": "evidence/manual/TC-006/a1/steps.jsonl"}, "triage evidence",
                                 require_hash=False, under="evidence")
    check("K-M2-7 the same row with the file removed is unresolved", out["resolved"] == [] and len(out["unresolved"]) == 8)
    check("K-M2-7 ... with the judge's own words as context, 'evidence: <words>' (the story folder, not its absolute path: m1, AR-4)",
          words != "" and f"evidence: {INV._unrooted(task, words)}" in out["context"]["case-TC-006"][0])
    every = [line for lines in out["context"].values() for line in lines]
    check("K-M9a no context line holds the absolute task root (any spelling)",
          every and not any(root in line for line in every for root in (str(task), str(task.resolve()), task.resolve().as_posix())), str(every[:1]))
    check("K-M9a ... and the judge's words survive without it: 'the story folder'", "the story folder" in out["context"]["case-TC-006"][0])

    absolute = str(task / "work" / "evidence" / "manual" / "TC-007" / "request.json")
    for label, value in (("absolute", absolute), ("a .. escape", "../state/story-case-links.json"),
                         ("under work/ but outside work/evidence/", "handoffs/S6-qa-runner-1.yaml"),
                         ("a directory", "evidence/manual/TC-006/a1"), ("missing", "evidence/manual/TC-006/a1/nope.json"),
                         ("empty", ""), ("none", None), ("a number", 7)):
        t2 = story()
        set_triage(t2, "TC-006", verdict="APP_BUG", evidence=value)
        res = INV.unresolved_targets(t2, budget)
        check(f"K-M2-7 evidence {label}: stays unresolved", "case-TC-006" in [t["id"] for t in res["unresolved"]] and res["resolved"] == [])

    t3 = story()                                       # the triage file itself cannot be read
    (t3 / "work" / "triage.json").write_text("[1, 2", encoding="utf-8")
    res = INV.unresolved_targets(t3, budget)
    check("K-M2-7 an unreadable triage: every target unresolved, one context line 'triage: unreadable' each",
          len(res["unresolved"]) == 8 and all(lines == ["triage: unreadable"] for lines in res["context"].values()))

    t4 = story()                                       # the register resolves (i) an evidenced role outcome, (ii) a withdraw, a role gap
    INV.project(t4, "S7-x")
    probe = {"method": "api", "runs": 2, "reproduced": 2, "environment": "stand", "safe_to_break": None}
    role_correct(t4, "case-TC-008", probe=probe, verification_status="reproduced")
    role_correct(t4, "case-TC-009", probe=probe, verification_status="reproduced")    # replaced next: unverified code stays
    role_withdraw(t4, "case-TC-010")
    role_correct(t4, "case-TC-011", kind="coverage_gap", missing_prerequisite="a second stand")
    role_correct(t4, "case-TC-012")                    # a role line with no outcome and no probe: not resolved
    res = INV.unresolved_targets(t4, budget)
    check_eq("K-M2-7 register resolution: an evidenced role outcome (i), a withdraw and a role coverage_gap (ii)",
             sorted(target for target, _ in res["resolved"]), ["case-TC-008", "case-TC-009", "case-TC-010", "case-TC-011"])
    check_eq("K-M2-7 ... a role line with no outcome and the code lines stay unresolved", [t["id"] for t in res["unresolved"]],
             ["case-TC-006", "case-TC-007", "case-TC-012", "obs-S6-qa-runner-4-0"])


# --- K-M2-8 -----------------------------------------------------------------------------------------------------------

def key_writer_missing() -> None:
    task = story()
    saved = sys.modules.get("exploratory_findings")
    sys.modules["exploratory_findings"] = None         # `import exploratory_findings` now raises ImportError
    try:
        out = INV.project(task, "S7-x")
        printed: list = []
        closed = INV.close_gaps(task, GAP_WHY, printed)
    finally:
        sys.modules["exploratory_findings"] = saved
    check_eq("K-M2-8 writer missing: project prints 'the findings register is not installed', writes nothing",
             (out["printed"], out["added"], out["corrected"]), (["the findings register is not installed"], [], []))
    check_eq("K-M2-8 close_gaps says the same and closes nothing", (printed, closed), (["the findings register is not installed"], []))
    check("K-M2-8 no register file was created", file_bytes(task) is None)


# --- K-M2-9 -----------------------------------------------------------------------------------------------------------

def key_budget_and_why() -> None:
    shipped = {"schema_version": 1, "methods": ["api", "ui", "log", "source_read"], "probes_per_dispatch": 12,
               "reproductions_per_target": 3, "timebox_minutes": 10, "resolving_verdicts": ["APP_BUG"]}
    check_eq("K-M2-9 the shipped-shape dict is valid", INV.budget_problems(shipped), [])
    check_eq("K-M2-9 an empty resolving_verdicts list is valid", INV.budget_problems(dict(shipped, resolving_verdicts=[])), [])
    check_eq("K-M2-9 None -> 'cannot be read'", INV.budget_problems(None), ["cannot be read"])
    check_eq("K-M2-9 a list -> 'cannot be read'", INV.budget_problems([shipped]), ["cannot be read"])
    cases = (("probes_per_dispatch: 0", dict(shipped, probes_per_dispatch=0), "probes_per_dispatch"),
             ("probes_per_dispatch: true", dict(shipped, probes_per_dispatch=True), "probes_per_dispatch"),
             ("probes_per_dispatch: \"12\"", dict(shipped, probes_per_dispatch="12"), "probes_per_dispatch"),
             ("reproductions_per_target: -1", dict(shipped, reproductions_per_target=-1), "reproductions_per_target"),
             ("timebox_minutes: 1.5", dict(shipped, timebox_minutes=1.5), "timebox_minutes"),
             ("schema_version: 2", dict(shipped, schema_version=2), "schema_version"),
             ("schema_version: true", dict(shipped, schema_version=True), "schema_version"),
             ("methods: []", dict(shipped, methods=[]), "methods"),
             ("methods: ['api', '']", dict(shipped, methods=["api", ""]), "methods"),
             ("resolving_verdicts: \"x\"", dict(shipped, resolving_verdicts="x"), "resolving_verdicts"),
             ("resolving_verdicts: [1]", dict(shipped, resolving_verdicts=[1]), "resolving_verdicts"))
    for label, budget, key in cases:
        problems = INV.budget_problems(budget)
        check(f"K-M2-9 {label} -> exactly one problem, naming `{key}`", len(problems) == 1 and f"`{key}`" in problems[0])
    absent = dict(shipped)
    for key in ("schema_version", "methods", "probes_per_dispatch", "reproductions_per_target", "timebox_minutes",
                "resolving_verdicts"):
        del absent[key]
    problems = INV.budget_problems({})
    check_eq("K-M2-9 {} -> one problem per key, in the rule's order", [p.split("`")[1] for p in problems],
             ["schema_version", "methods", "probes_per_dispatch", "reproductions_per_target", "timebox_minutes",
              "resolving_verdicts"])
    check_eq("K-M2-9 budget_problems is pure: the dict it was given is unchanged", shipped["probes_per_dispatch"], 12)

    task = story()
    INV.project(task, "S7-x")
    size = len(EF.read(task)["lines"])
    for fourth in ("a second investigation in one S7 chain is not run", "", None, "The investigation ended before this target"):
        try:
            INV.close_gaps(task, fourth)
            message = ""
        except ValueError as exc:
            message = str(exc)
        check(f"K-M2-9 close_gaps with the why {fourth!r} -> ValueError naming the three texts, nothing written",
              all(text in message for text in INV.WHY_TEXTS) and len(EF.read(task)["lines"]) == size)
    check_eq("K-M2-9 exactly three texts exist", len(INV.WHY_TEXTS), 3)


# --- evidence edges ---------------------------------------------------------------------------------------------------

def key_evidence_edges() -> None:
    task = story()                                     # a row with no evidence path: its carrier is the evidence
    runner = task / "work" / "handoffs" / "S6-qa-runner-1.yaml"
    edit(runner, "    evidence: work/evidence/manual/TC-009/a1/001-request-response.json\n", "    evidence: \"\"\n")
    # and a named path that is not a file: printed, never a ref
    edit(runner, "    evidence: work/evidence/manual/TC-006/a1/005-request-response.json\n",
         "    evidence: work/evidence/manual/TC-006/a1/does-not-exist.json\n")
    out = INV.project(task, "S7-x")
    state = EF.read(task)["active"]
    check_eq("K-M2-E a target with no evidence path: its carriers are the evidence (>= 1 always satisfiable)",
             [r["path"] for r in state["case-TC-009"]["evidence_refs"]],
             ["work/handoffs/S6-qa-runner-1.yaml", "work/evidence/manual/TC-009/request.json"])
    check("K-M2-E a named path that is not a file is printed, not a ref",
          any("case-TC-006" in line and "does-not-exist.json" in line for line in out["printed"])
          and all("does-not-exist" not in r["path"] for r in state["case-TC-006"]["evidence_refs"]))
    check("K-M2-E every written ref hashes (the writer judged it)", register_ok(task))

    task2 = story()                                    # an evidence path that escapes the story folder is never a ref
    edit(task2 / "work" / "handoffs" / "S6-qa-runner-3.yaml", "evidence: work/evidence/manual/TC-010/a1/017-request-response.json",
         "evidence: ../../../../outside.txt")
    out2 = INV.project(task2, "S7-x")
    check("K-M2-E an escaping path is printed, the target still projects",
          any("escapes" in line for line in out2["printed"]) and "case-TC-010" in EF.read(task2)["active"])


# --- the CLI ----------------------------------------------------------------------------------------------------------

def key_cli() -> None:
    task = story()
    code, out, err = cli("targets", "--task-root", task)
    shown = json.loads(out)
    check("K-M2-CLI targets: exit 0, ONE JSON object with the eight targets", code == 0 and [t["id"] for t in shown["targets"]] == TARGETS
          and shown["unreadable"] == [] and out.count("\n") == 1)
    code, out, err = cli("project", "--task-root", task, "--dispatch", "S7-qa-failure-analyst-1")
    check("K-M2-CLI project: exit 0, eight added", code == 0 and len(json.loads(out)["added"]) == 8)
    code, out, err = cli("project", "--task-root", task, "--dispatch", "S7-qa-failure-analyst-1")
    check("K-M2-CLI project again: nothing added", code == 0 and json.loads(out)["added"] == [])
    code, out, err = cli("project", "--task-root", task)
    check("K-M2-CLI project with no --dispatch: refused, first stderr line '<command>: <problem>', exit 2",
          code == 2 and err.splitlines()[0].startswith("investigation.py project: --dispatch is required") and out == "")
    code, out, err = cli("close-gaps", "--task-root", task, "--why", "a second investigation in one S7 chain is not run")
    check("K-M2-CLI close-gaps with an unknown why: exit 2 naming the three texts",
          code == 2 and err.splitlines()[0].startswith("investigation.py close-gaps: ") and all(t in err for t in INV.WHY_TEXTS))
    code, out, err = cli("close-gaps", "--task-root", task)
    check("K-M2-CLI close-gaps with no --why: refused, exit 2", code == 2 and err.splitlines()[0].startswith("investigation.py close-gaps: "))
    code, out, err = cli("targets", "--task-root", task / "nope")
    check("K-M2-CLI a task root that is not a folder: refused", code == 2 and "is not a folder" in err.splitlines()[0])
    code, out, err = cli("frobnicate", "--task-root", task)
    check("K-M2-CLI an unknown subcommand: exit 2", code == 2)
    code, out, err = cli("close-gaps", "--task-root", task, "--why", GAP_WHY)
    closed = json.loads(out)
    check("K-M2-CLI close-gaps: exit 0, eight closed, nothing printed", code == 0 and len(closed["closed"]) == 8 and closed["printed"] == [])

    budget_file = task / "budget.json"                 # `unresolved` carries the ONE carrier of the budget's validity
    saved = INV.BUDGET_PATH
    try:
        INV.BUDGET_PATH = task / "no-such-budget.json"
        set_triage(task, "TC-006", verdict="APP_BUG")
        code, out, err = cli("unresolved", "--task-root", task)
        shown = json.loads(out)
        check_eq("K-M2-CLI unresolved with no budget file: budget_problems ['cannot be read'], nothing resolved",
                 (code, shown["budget_problems"], shown["resolved"], len(shown["unresolved"])), (0, ["cannot be read"], [], 8))
        check("K-M2-CLI ... no separate 'budget' field", "budget" not in shown)
        budget_file.write_text(json.dumps({"schema_version": 1, "methods": ["api"], "probes_per_dispatch": 0,
                                           "reproductions_per_target": 3, "timebox_minutes": 5,
                                           "resolving_verdicts": ["APP_BUG"]}), encoding="utf-8")
        INV.BUDGET_PATH = budget_file
        shown = json.loads(cli("unresolved", "--task-root", task)[1])
        check("K-M2-CLI an invalid budget: its problem is printed and the targets are computed with resolving_verdicts=[]",
              len(shown["budget_problems"]) == 1 and "`probes_per_dispatch`" in shown["budget_problems"][0] and shown["resolved"] == [])
        budget_file.write_text(json.dumps({"schema_version": 1, "methods": ["api"], "probes_per_dispatch": 4,
                                           "reproductions_per_target": 3, "timebox_minutes": 5,
                                           "resolving_verdicts": ["APP_BUG"]}), encoding="utf-8")
        shown = json.loads(cli("unresolved", "--task-root", task)[1])
        check_eq("K-M2-CLI a valid budget: no problems, the APP_BUG row resolves its case",
                 (shown["budget_problems"], [item[0] for item in shown["resolved"]]), ([], ["case-TC-006"]))
    finally:
        INV.BUDGET_PATH = saved


# --- wave 3: pass_members / decision ----------------------------------------------------------------------------------
# Mutation -> killing key (named, not run): step 5 after step 6 -> K-W3-2 (tie 5/6); drop the DISCOUNTED filter -> K-W3-3;
# `budget` used directly at step 3 -> K-W3-2 (substitution); step 1 after step 4 -> K-W3-1; a print in `decision` -> K-W3-4.

GATE_B = {"gates": {"B": {"decision": "approved"}}}
OPEN_B = {"gates": {"B": {}}}


def member(status: str, mid: str = "S7-qa-failure-analyst-2", purpose: str = "investigation") -> dict:
    return {"id": mid, "stage": "S7", "role": "qa-failure-analyst", "status": status, "request_binding": {"purpose": purpose}}


def state_of(*records) -> dict:
    return {"dispatches": {r["id"]: r for r in records}}


def budget() -> dict:
    return json.loads(INV.BUDGET_PATH.read_text(encoding="utf-8"))


def pure_decision(task: Path, state, pipeline, bud):
    """decision(...) with the K-W3-4 witnesses taken around it: no file under the task root changes, stdout stays empty."""
    before, out = tree_hash(task), io.StringIO()
    with contextlib.redirect_stdout(out):
        got = INV.decision(task, state, pipeline, bud)
    check_eq(f"K-W3-4 purity: {got!r} changed no file under the task root and printed nothing",
             (tree_hash(task), out.getvalue()), (before, ""))
    return got


def key_w3_wait() -> None:
    task = story()
    running = state_of(member("running"))
    check_eq("K-W3-1 a running member with 8 targets: wait on its id", pure_decision(task, running, OPEN_B, budget()),
             ("wait", "S7-qa-failure-analyst-2"))
    quiet = temp_project()
    ROOTS.append(quiet)
    empty = quiet / "qa-factory" / "artifacts" / "TP1-QUIET"
    (empty / "work").mkdir(parents=True)
    (empty / "pipeline.json").write_text("{}", encoding="utf-8")
    check_eq("K-W3-1 ... and with 0 targets (step 1 before step 4)", pure_decision(empty, running, OPEN_B, budget()),
             ("wait", "S7-qa-failure-analyst-2"))
    check_eq("K-W3-1 two running members: the first, in the state's order",
             pure_decision(task, state_of(member("running", "S7-a"), member("running", "S7-b")), OPEN_B, budget()), ("wait", "S7-a"))


def key_w3_decision() -> None:
    none_state = {"dispatches": {}}
    task = story()
    check_eq("K-W3-2 step 7: targets, no pass, gate B open -> dispatch", pure_decision(task, none_state, OPEN_B, budget()),
             ("dispatch", ""))
    check_eq("K-W3-2 step 6: gate B decided -> gaps", pure_decision(task, none_state, GATE_B, budget()),
             ("gaps", "gate B is already decided"))
    check_eq("K-W3-2 step 5: a pass made and ended -> gaps 'ended before'",
             pure_decision(task, state_of(member("accepted")), OPEN_B, budget()),
             ("gaps", "the investigation ended before this target"))
    check_eq("K-W3-2 tie 5/6: a past pass AND gate B decided -> 'ended before' (the fact that happened first)",
             pure_decision(task, state_of(member("accepted")), GATE_B, budget()),
             ("gaps", "the investigation ended before this target"))
    check_eq("K-W3-2 crooked state: no member invented -> dispatch", pure_decision(task, "not a state", OPEN_B, budget()),
             ("dispatch", ""))

    INV.project(task, "S7-x")                                 # all eight chains exist; withdraw them -> nothing unresolved
    for target in TARGETS:
        role_withdraw(task, target)
    check_eq("K-W3-2 step 4: nothing unresolved -> none", pure_decision(task, none_state, OPEN_B, budget()), ("none", ""))
    check_eq("K-W3-2 step 4 before 5 and 6: nothing unresolved, a past pass, gate B decided -> none",
             pure_decision(task, state_of(member("accepted")), GATE_B, budget()), ("none", ""))
    check_eq("K-W3-2 step 3, budget None, nothing unresolved -> none (today's close)",
             pure_decision(task, none_state, OPEN_B, None), ("none", ""))

    t2 = story()
    check_eq("K-W3-2 step 3: budget None with 8 targets -> gaps 'not available'", pure_decision(t2, none_state, OPEN_B, None),
             ("gaps", "the investigation is not available"))
    bad = dict(budget(), probes_per_dispatch=0, resolving_verdicts=["APP_BUG"])
    check_eq("K-W3-2 step 3: an invalid budget with 8 targets -> gaps 'not available'",
             pure_decision(t2, none_state, OPEN_B, bad), ("gaps", "the investigation is not available"))

    t3 = story()                                              # the [] substitution: TC-006 would resolve through the bad budget
    INV.project(t3, "S7-x")
    for target in TARGETS:
        if target != "case-TC-006":
            role_withdraw(t3, target)
    set_triage(t3, "TC-006", verdict="APP_BUG")
    check_eq("K-W3-2 control: the bad budget used directly would resolve TC-006",
             INV.unresolved_targets(t3, bad)["unresolved"], [])
    check_eq("K-W3-2 step 3: ... but `decision` substitutes resolving_verdicts=[]: TC-006 stays unresolved -> gaps",
             pure_decision(t3, none_state, OPEN_B, bad), ("gaps", "the investigation is not available"))

    saved = sys.modules.get("exploratory_findings")
    sys.modules["exploratory_findings"] = None
    try:
        got = pure_decision(story(), none_state, OPEN_B, budget())
        tie = pure_decision(story(), state_of(member("running")), OPEN_B, budget())
    finally:
        sys.modules["exploratory_findings"] = saved
    check_eq("K-W3-2 step 2: the register not importable -> none + the reason", got,
             ("none", "the findings register is not installed"))
    check_eq("K-W3-2 step 1 before step 2: a running member still waits", tie, ("wait", "S7-qa-failure-analyst-2"))
    check("K-W3-2 the removed text of the old rule never appears in the module",
          "a second investigation in one S7 chain is not run" not in Path(INV.__file__).read_text(encoding="utf-8"))

    t4 = story()                                              # unresolved_targets raising -> decision raises (pure, says nothing)
    real = INV.unresolved_targets

    def boom(*a, **k):
        raise RuntimeError("boom")

    INV.unresolved_targets = boom
    try:
        try:
            INV.decision(t4, none_state, OPEN_B, budget())
            raised = False
        except RuntimeError:
            raised = True
    finally:
        INV.unresolved_targets = real
    check("K-W3-2 an exception of unresolved_targets propagates out of decision", raised)


def key_w3_pass_members() -> None:
    kept = ["accepted", "blocked", "incomplete", "returned_unaccepted", "paused", "running", "abandoned"]
    records = [member(s, f"S7-{s}") for s in sorted(CT.DISCOUNTED) + kept]
    records += [dict(member("accepted", "S5-inv"), stage="S5"),
                {"id": "S7-triage", "stage": "S7", "role": "qa-failure-analyst", "status": "accepted"},
                dict(member("accepted", "S7-listbind"), request_binding=["investigation"])]
    got = INV.pass_members(state_of(*records))
    check_eq("K-W3-3 exactly the non-discounted S7 investigation records, ids and order kept", [m["id"] for m in got],
             [f"S7-{s}" for s in kept])
    check("K-W3-3 ... each is the record itself plus the id", all(m["status"] == m["id"][3:] for m in got))
    check_eq("K-W3-3 the discounted words are the controller's (no list in the module)",
             sorted(CT.DISCOUNTED), ["never_started", "released_by_person", "stale", "superseded"])
    keyed = {"k1": dict(member("accepted"), id=None), "k2": "not a record"}
    check_eq("K-W3-3 a record with no id takes its key; a non-dict record is skipped",
             [m["id"] for m in INV.pass_members({"dispatches": keyed})], ["k1"])
    check_eq("K-W3-3 crooked state / dispatches -> []",
             [INV.pass_members(x) for x in (None, [], "x", {}, {"dispatches": None}, {"dispatches": []})], [[]] * 6)


def key_w3_cli() -> None:
    task = story()
    code, out, err = cli("unresolved", "--task-root", task)
    shown = json.loads(out)
    check_eq("K-W3-5 unresolved prints pass_members [] for a story with no S7 dispatch", (code, shown["pass_members"]), (0, []))
    check_eq("K-M9 unresolved prints gate_b_answered (the fixture's gate B is not answered -> false)", shown["gate_b_answered"], False)
    answered = story()
    pipeline = json.loads((answered / "pipeline.json").read_text(encoding="utf-8"))
    pipeline.setdefault("gates", {})["B"] = {"decision": "approve"}
    (answered / "pipeline.json").write_text(json.dumps(pipeline), encoding="utf-8")
    check_eq("K-M9 ... true once gate B has a decision", json.loads(cli("unresolved", "--task-root", answered)[1])["gate_b_answered"], True)
    (answered / "pipeline.json").write_text("[1, 2", encoding="utf-8")
    code, out, err = cli("unresolved", "--task-root", answered)
    check("K-M9 ... an unreadable pipeline: null and ONE printed line on stderr", code == 0 and json.loads(out)["gate_b_answered"] is None
          and "gate_b_answered" in err, err)
    saved = INV._state_of
    INV._state_of = lambda task_root: state_of(member("running"), member("superseded", "S7-old"))
    try:
        shown = json.loads(cli("unresolved", "--task-root", task)[1])
    finally:
        INV._state_of = saved
    check_eq("K-W3-5 ... and [{id, status}] for one member (the discounted one is not listed)", shown["pass_members"],
             [{"id": "S7-qa-failure-analyst-2", "status": "running"}])
    rows = {r["id"]: r for r in json.loads((Path(INV.__file__).resolve().parents[1] / "references" / "null-outcomes.json")
                                           .read_text(encoding="utf-8"))["never_empty"]}
    check_eq("K-W3-5 NE28 is the register's null-outcome row (a validator on the evidence refs)",
             (rows["NE28"]["kind"], rows["NE28"]["guard"]), ("validator", "exploratory_findings.py::append"))


def key_settled_open_target_not_reinvestigated() -> None:
    """t-1991 U1 (iv): a target the analyst settled on the stand (record + carrier line) is resolved and listed under `settled`; the
    investigation does not dispatch for it and `close_gaps` does not gap it. `test_place_answers.py` holds the full set of edges."""
    import hashlib
    import place_answers as PA
    task = story()
    folder = task / "work" / "evidence" / "manual" / "settle-case-TC-006" / "a1"
    folder.mkdir(parents=True)
    (folder / "001-page.txt").write_text("the page shows no timestamp", encoding="utf-8")
    capture = (folder / "001-page.txt").relative_to(task).as_posix()
    (folder / "captures.jsonl").write_text(json.dumps({"path": capture, "kind": "page", "content_hash": hashlib.sha256(
        (folder / "001-page.txt").read_bytes()).hexdigest()}) + "\n", encoding="utf-8")
    record = {"place": "case-TC-006", "answer": "requirement_silent", "expectation": {"source": "none", "id": "", "quote": ""},
              "seen": {"quote": "no timestamp", "capture": capture}, "question": "Should the page show a timestamp?"}
    PA.write(task, "S7-qa-failure-analyst-1", "case-TC-006", record)
    found = INV.open_targets(task, INV.load_budget()[0])
    check("W-U1 the settled target is resolved, listed under `settled`, and no longer unresolved",
          "case-TC-006" not in ids({"targets": found["unresolved"]}) and ids({"targets": found["settled"]}) == ["case-TC-006"])
    check_eq("W-U1 ... why names the dispatch and the answer", dict(found["resolved"])["case-TC-006"],
             "settled by S7-qa-failure-analyst-1: requirement_silent")
    gaps = INV.close_gaps(task, GAP_WHY, budget=INV.load_budget()[0])
    check("W-U1 close_gaps never gaps a settled place as `not investigated`",
          all(EF.read(task)["active"].get("case-TC-006", {}).get("kind") != "coverage_gap" for _ in [0]) and "case-TC-006" not in
          [EF.target_of(line) for line in EF.read(task)["lines"] if line["id"] in gaps])


def key_project_skips_settled_bug() -> None:
    """t-1991 fix round F3: `project` puts no `owner_question` line on a target the analyst settled (here a `bug`, which writes no line of
    its own); a reader that cannot be asked projects it as before. `test_place_answers.py` holds the same edge with a real bug answer."""
    import place_answers as PA
    task = story()
    saved = PA.settled_answer
    try:
        PA.settled_answer = lambda root, place: ({"answer": "bug"}, "settled" if place == "case-TC-006" else "open", "")
        out = INV.project(task, "S7-qa-failure-analyst-1")
        check("F3 the settled target has no register line and is skipped", "case-TC-006" in out["skipped"]
              and EF.read(task)["active"].get("case-TC-006") is None)
        check("F3 the other targets are projected as ever", EF.read(task)["active"].get("case-TC-007") is not None)
        PA.settled_answer = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
        INV.project(task, "S7-qa-failure-analyst-1")
        check("F3 a reader that raises asks the question as before", EF.read(task)["active"].get("case-TC-006") is not None)
    finally:
        PA.settled_answer = saved


if __name__ == "__main__":
    main()
