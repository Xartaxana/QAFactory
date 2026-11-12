#!/usr/bin/env python3
"""report_facts.py: the facts of the report are built once by code, and the blocks state them.

TP1-13797 (cmp1) is the story that earned this file: its report said "No product bug is recorded"
while BUG-1 lay in the story's folder, printed "Fact: not recorded" for a size the factory had computed,
listed gate A's decision under "Decided at gate B", and asked the person about items whose only gap was the
factory's own bookkeeping. Each section below is one of the requirements of B-211 turned into a check; the
five mutations the piece must kill (a count from a second source, a timestamp inside a block, an unknown
printed as 0, a factory-owned ref left in "Left with you", the 200/201 cut off by one) each have a check
that fails on them.

Run on its own: `python -B scripts/tests/test_report_facts.py`.
"""
import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import (check, check_eq, check_in, check_not_in, cleanup, finish, repaste_appendix, run_script,  # noqa: E402
                     temp_dir, temp_project, use_project)
from harness import SCRIPTS  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import contract as C  # noqa: E402
import exploratory_findings as EF  # noqa: E402
import gate_brief as GB  # noqa: E402
import grammar as G  # noqa: E402
import report_facts as RF  # noqa: E402
import traceability as T  # noqa: E402
import validate_artifacts as V  # noqa: E402

CMP1 = Path(r"C:\Users\dev1\AppData\Local\Temp\t108\cmp1\qa-factory")

REGISTER = """---
task: T-1
---

## Register

| R | Requirement | source | derived_from | verifiable | ac_ref |
|---|---|---|---|---|---|
| R-1 | The owner can cancel from settings | ac | - | yes | AC-1 |
| R-2 | Access lasts to the end of the paid period | ac | - | yes | AC-2 |
| R-3 | Old invoices stay readable | ac | - | yes | AC-3 |
| R-4 | The export keeps its column order | ac | - | yes | AC-4 |
"""

PLAN = """---
task: T-1
---
# Test plan - T-1

## Plan

| TS | what we verify | R | defect hypothesis | impact class | priority | observable | oracle | disposition + reason | fit | level | technique |
|---|---|---|---|---|---|---|---|---|---|---|---|
| TS-1 | cancel from settings | R-1 | state @ cancel | degraded | P2 | diff:src/a.py:1 | requirement:R-1 | `automate` - core AC | new | api | decision table |
| TS-2 | paid period | R-2 | boundary @ period end | money | P0 | diff:src/b.py:1 | requirement:R-2 | `manual-human` - needs a billing cycle | new | manual-human | walkthrough |
| TS-3 | old invoices | R-3 | contract @ reader | blocked-flow | P1 | diff:src/c.py:1 | requirement:R-3 | `skip` - the app team's suite | new | api | smoke |

## Recommended regression

1. run the billing suite
"""

CASE = """---
id: {cid}
title: {title}
area: billing
task: T-1
covers: [{req}]
plan_row: {ts}
---
Requirements: {req}
Plan row: {ts}

## Then
1. The subscription reads cancelled.
"""

MANIFEST = {"tests": [
    {"case": "TC-001", "covers": ["TC-001"], "file": "tests/api/test_a.py", "instance_id": "test_a",
     "status": "green", "critic_verdict": "approved"}]}

RUN_REPORT = {"schema_version": 2, "task_id": "T-1", "execution_status": "passed",
              "current_results": [{"instance_id": "test_a", "status": "passed"}], "results": []}

READINESS = {"open_questions": [
    {"id": "Q1", "question": "Is a refund due after cancelling?", "owner_role": "po_ba", "severity": "blocker",
     "readings": [{"reading": "yes"}, {"reading": "no"}]},
    {"id": "Q2", "question": "Does the period end at midnight UTC?", "owner_role": "dev_arch", "severity": "major"}]}

BUG = """---
id: BUG-1
title: Cancelling keeps charging the card
severity: major
violates: requirement:R-1
gate_b_decision_id: gateB-T-1
confirmation: confirmed_by_person
---

## Actual result
The card is charged again.
"""

GATE_A = "Gate A: approved, go on. The 14 rows stand.\n\n5. s5_environment-1, credentials - accept the gap."
GATE_B = "Gate B: draft MR, bugs into a file.\n\nTC-002: run it yourself, I accept the risk."


def test_row(ref="test_a", state="passed_green", level="not_required", reason="unmeasured", words="not probed (unchanged test)"):
    return {"ref": ref, "kind": "test", "state": state, "detail": ref, "proof_level": level,
            "proof_words": words, "proof_reason": reason}


def ledger(rows=None, ready=False, records=None, findings=None):
    return {"ticket": "T-1", "rows": rows if rows is not None else [test_row()], "delivery_ready": ready,
            "reasons": [r["detail"] for r in records or []], "blocked_by": [],
            "reason_records": records if records is not None else [
                {"code": "TRACEABILITY_GAP", "entity": "R-2", "owner": "product",
                 "detail": "traceability: R-2 has no terminal outcome (waits)"},
                {"code": "FACTORY_DEFECT", "entity": "x", "owner": "factory", "detail": "factory: a row the reducer could not join"}],
            "factory_findings": findings or []}


def write(path: Path, text, binary: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(text, (dict, list)):
        text = json.dumps(text)
    path.write_text(text, encoding="utf-8", newline="\n")


def story(pipeline=None, with_bug=True, with_ledger=True, extra_ledger=None, sizing=True) -> Path:
    """A project whose story `T-1` has every source; returns the task root."""
    root = temp_project("qa-report-facts-")
    task = root / "qa-factory" / "artifacts" / "T-1"
    work = task / "work"
    write(work / "requirements-register.md", REGISTER)
    write(task / "test-plan.md", PLAN)
    write(work / "test-cases" / "billing" / "TC-001.md", CASE.format(cid="TC-001", title="Cancel", req="R-1", ts="TS-1"))
    write(work / "test-cases" / "billing" / "TC-002.md", CASE.format(cid="TC-002", title="Paid period", req="R-2", ts="TS-2"))
    write(work / "automation-manifest.json", MANIFEST)
    write(work / "run-report.json", RUN_REPORT)
    write(work / "requirements-readiness.json", READINESS)
    write(task / "understanding.md", "# T-1\n\n## Why this change\n\n## What we verify\n")
    write(task / "pipeline.json", pipeline if pipeline is not None else {
        "ticket": "T-1", "size": None, "gates": {"A": {"authorization_source": GATE_A}},
        "stage_overrides": [{"stage": "S2", "match": "size", "decision": "test it as one story"}]})
    if with_bug:
        write(task / "bugs" / "BUG-1.md", BUG)
    if with_ledger:
        write(work / "ledger.json", extra_ledger or ledger())
    if sizing:
        write(work / "sizing.json", {"size": "M", "cap": 13, "computed_budget": 9, "verifiable_count": 4})
    use_project(root)
    return task


def render_all(task: Path) -> dict:
    return RF.render(RF.build(task))


def tree_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def cli(task: Path, *flags):
    return run_script("report_facts.py", "--task-root", task, *flags)


# --- the one reader of each fact -------------------------------------------------------------------------

def one_source_per_count() -> None:
    task = story()
    try:
        facts = RF.build(task)
        check_eq("the facts carry their own keys", sorted(facts), sorted(
            ["task", "unknown", "bugs", "requirements", "manual", "cases", "tests", "changes", "probe_debt", "person_build", "ledger",
             "questions", "delivery", "gate_a", "gate_b", "size", "where", "not_proven", "skipped", "regression", "verdict",
             "over_cap_windows", "collect_gaps", "quality_not_run", "exploratory", "integrations", "owed_rework", "branches", "attachments", "grounding", "passed_over", "reference_runs"]))   # passed_over: TR1-9, the work a code close passed over (report_facts.py `_passed_over_gap`)
        check_eq("a story with every source has no unknown entry", facts["unknown"], {})
        blocks = RF.render(facts)
        # (a) the bug count is the bug reader's: the ledger of this story has no failed row at all, and the
        # bug sits in the story's own folder - a count read from the ledger would say 0.
        check_eq("the bug reader finds BUG-1 in the story's folder", facts["bugs"]["confirmed"], 1)
        check_in("the verdict says 1 confirmed bug (the bug reader, not the ledger)", "Product bugs: 1 confirmed (major), 0 unconfirmed", blocks["verdict"])
        check_in("the bugs heading agrees with the verdict (FR-10)", "## Product bugs \u2014 1 confirmed \u00b7 0 unconfirmed", blocks["bugs"])
        check_in("the bug is named with its requirement", "**major \u00b7 R-1** \u2014 Cancelling keeps charging the card (BUG-1)", blocks["bugs"])
        check_in("a bug in the story's own folder is told as the factory's bookkeeping", "lies in the story's own folder", blocks["bugs"])
        c = facts["requirements"]["counts"]
        check_eq("requirements: R-1 proven, R-2 waits, R-3 deferred, R-4 has no plan row", c,
                 {"proven": 1, "bug": 0, "unproven": 1, "wait": 1, "deferred": 1, "bookkeeping": 0})
        check_in("the verdict counts requirements", "Of 4 requirements: 1 proven by tests", blocks["verdict"])
        check_in("the counts add up to the total", "1 not proven, 1 waiting for a person, 1 deferred by your decision", blocks["verdict"])
        check_in("a person must check the manual case", "A person must check 1 case; 0 cases are closed only partly", blocks["verdict"])
        check_in("the proven tests are counted", "1 green test counts as proven", blocks["verdict"])
        check_in("the factory's own reasons are told, not asked (FR-3)", "1 open reason in the checks is the factory's own bookkeeping", blocks["verdict"])
        check_in("the delivery line is the ledger's word plus the first reason",
                 "`delivery_ready: no \u2014 BUG-1 is a confirmed product bug (R-1)", blocks["verdict"])
    finally:
        cleanup(task.parents[2])


def first_reason_order() -> None:
    """(viii) confirmed bugs, then requirements without a proving result by plan priority P0 to P3, then R number."""
    task = story(with_bug=False)
    try:
        v = RF.build(task)["verdict"]
        check_eq("no bug: the P0 requirement (R-2) goes first, not the lowest R number", v["first_kind"], "requirement")
        check_in("R-2 (P0, money) is the first reason", "R-2 (Access lasts to the end of the paid period) is not proven", v["first_reason"])
        # ties: R-5 and R-3 both P1 -> the lower R number first; a requirement with no plan row sorts last
        plan = PLAN.replace("| R-3 | contract @ reader", "| R-3 | contract @ reader")
        write(task / "test-plan.md", plan.replace("`manual-human` - needs a billing cycle", "`automate` - billing").replace("| P0 |", "| P1 |"))
        v = RF.build(task)["verdict"]
        check_in("a tie on priority goes to the lower R number", "R-2 (", v["first_reason"])
        again = RF.build(task)["verdict"]
        check_eq("and the order is deterministic", again["first_reason_full"], v["first_reason_full"])
        write(task / "bugs" / "BUG-1.md", BUG)
        v = RF.build(task)["verdict"]
        confirmed_word = v["word"]
        check_eq("a confirmed bug outranks every requirement", v["first_kind"], "bug")
        write(task / "bugs" / "BUG-1.md", BUG.replace("confirmed_by_person", "unconfirmed"))
        v = RF.build(task)["verdict"]
        # RN1-16: an unconfirmed draft that names a requirement leads the head, said as "not confirmed yet"; the WORD is the ledger's (E-A10)
        check_eq("an unconfirmed bug leads the head as a draft, said as not confirmed yet", v["first_kind"], "bug_draft")
        check_in("... the head says it is not confirmed yet", "not confirmed yet", v["first_reason_full"])
        check_eq("... and the verdict word is the same as with the confirmed bug", v["word"], confirmed_word)
        facts = RF.build(task)
        check_in("it is listed, marked, and counts toward nothing", "unconfirmed \u2014 nobody has reproduced it", RF.render(facts)["bugs"])
    finally:
        cleanup(task.parents[2])


def bug_on_a_manual_case() -> None:
    """t-202 F2 (R-213.1): BUG-1 of cmp1 named R-7 while R-7's only case was planned for a person - its row
    read "not run", R-7 stood under "Not proven" and the verdict counted "0 with a product bug". A manual (or
    never-run) case whose requirement has a CONFIRMED bug record classes `bug`; a draft, or a bug that names
    no requirement, changes nothing; a requirement is never both "with a bug" and "Not proven"."""
    task = story(with_bug=False)
    bug2 = BUG.replace("BUG-1", "BUG-2").replace("R-1", "R-2")   # R-2's only case, TC-002, is planned manual-human
    try:
        qa = task.parents[1]

        def read():
            facts = RF.build(task)
            by_id = {i["id"]: i for i in facts["requirements"]["items"]}
            row = next(r for r in T.build(qa, task)["rows"] if r["requirement"] == "R-2")
            return facts, by_id, row

        facts, by_id, row = read()
        check_eq("before any bug: the manual case waits for the person", (row["result"], by_id["R-2"]["class"]), ("wait", "wait"))
        check_in("and R-2 is under Not proven", "R-2", " ".join(i["id"] for i in facts["not_proven"]))

        write(task / "bugs" / "BUG-2.md", bug2)
        facts, by_id, row = read()
        blocks = RF.render(facts)
        check_eq("a confirmed bug naming R-2: the manual case's row is the bug", (row["result"], row["bug"]), ("bug", "BUG-2"))
        check_eq("its basis is the bug's title", row["basis"], "Cancelling keeps charging the card")
        check_eq("the requirement's class is bug", by_id["R-2"]["class"], "bug")
        check_in("the verdict counts it under 'with a product bug'", "1 proven by tests, 1 with a product bug, 1 not proven, 0 waiting for a person, 1 deferred",
                 blocks["verdict"])
        check_not_in("R-2 leaves Not proven", "R-2", " ".join(i["id"] for i in facts["not_proven"]))
        check_not_in("and the block", "**R-2**", blocks["not-proven"])
        appendix = T.render(T.build(qa, task))
        r2 = next(ln for ln in appendix.splitlines() if ln.startswith("| R-2 "))
        check_in("the appendix says the same, from the same rows (FR-10)", "**BUG-2**", r2)
        in_bug = {r["requirement"] for r in T.build(qa, task)["rows"] if r["result"] == "bug"}
        check_eq("the verdict's count and the appendix's rows agree",
                 (facts["requirements"]["counts"]["bug"], len(in_bug)), (1, 1))
        check_eq("INVARIANT: no requirement is both 'with a bug' and under Not proven",
                 sorted({i["id"] for i in facts["requirements"]["items"] if i["class"] == "bug"}
                        & {i["id"] for i in facts["not_proven"]}), [])

        write(task / "bugs" / "BUG-2.md", bug2.replace("confirmed_by_person", "unconfirmed"))
        facts, by_id, row = read()
        check_eq("a draft (unconfirmed) bug: today's class", (row["result"], by_id["R-2"]["class"]), ("wait", "wait"))
        check_in("it is counted as unconfirmed, and nothing else",
                 "Product bugs: 0 confirmed, 1 unconfirmed.", RF.render(facts)["verdict"])
        check_in("and R-2 stays under Not proven", "R-2", " ".join(i["id"] for i in facts["not_proven"]))

        write(task / "bugs" / "BUG-2.md", bug2.replace("violates: requirement:R-2", "violates: invariant:billing"))
        facts, by_id, row = read()
        check_eq("a bug that names no requirement: nothing changes", (row["result"], by_id["R-2"]["class"]), ("wait", "wait"))

        write(task / "bugs" / "BUG-2.md", bug2.replace("R-2", "R-9"))
        facts, by_id, row = read()
        check_eq("a bug that names another requirement: nothing changes for R-2", (row["result"], by_id["R-2"]["class"]), ("wait", "wait"))

        # a never-run automated case (the `not run` branch) takes the same road
        write(task / "bugs" / "BUG-2.md", bug2)
        write(task / "test-plan.md", PLAN.replace("`manual-human` - needs a billing cycle", "`automate` - billing").replace(
            "| P0 | diff:src/b.py:1 | requirement:R-2 | `automate` - billing | new | manual-human |", "| P0 | diff:src/b.py:1 | requirement:R-2 | `automate` - billing | new | api |"))
        facts, by_id, row = read()
        check_eq("a case planned for automation that never ran, with a confirmed bug: the bug too", (row["result"], row["bug"]), ("bug", "BUG-2"))
    finally:
        cleanup(task.parents[2])


def same_bytes_inside_and_outside_the_project() -> None:
    """t-202 F5: `decided_cases` read the case ids in the PROCESS's project, so the cmp1 report rendered from the
    repo root named no case in gate B's words and pruned nothing, and two renders of one story differed in bytes."""
    import shutil
    words = "Gate B: draft MR.\n\nAB-1_TC_002: run it yourself, I accept the risk."
    pipeline = {"ticket": "T-1", "gates": {"A": {"authorization_source": GATE_A}, "B": {"authorization_source": words}}}
    task = story(pipeline=pipeline)
    root = task.parents[2]
    other = temp_project("qa-report-outside-")
    copy = temp_dir("qa-report-copy-") / "project"
    try:
        cfg_path = root / "qa-factory" / "config.json"
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        cfg["case_id_form"] = "{ticket}_TC_{nnn}"
        cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
        C.case_config_reset()
        shutil.copytree(root, copy)
        task2 = copy / "qa-factory" / "artifacts" / "T-1"
        for t in (task, task2):
            legacy_report(t)
            text = (t / "test-report.md").read_text(encoding="utf-8")
            (t / "test-report.md").write_text(text.replace("(R-2, TC-002)", "(R-2, AB-1_TC_002)"), encoding="utf-8", newline="")
            # t-305 N8 (F10): the words close an item only when the ledger agrees the case is closed - an item whose case
            # no ledger row names is still owed (the error is toward keeping), so this story's ledger says it passed
            (t / "work").mkdir(exist_ok=True)
            (t / "work" / "ledger.json").write_text(json.dumps(
                {"rows": [{"ref": "TS-2", "kind": "plan_row", "state": "passed_green", "detail": "AB-1_TC_002"}],
                 "left_items": [], "delivery_ready": True, "delivery_verdict": "yes"}), encoding="utf-8")
        check_eq("the case id the words name is one of the project's forms",
                 C.case_ids("AB-1_TC_002 and TC-001", task), ["AB-1_TC_002", "TC-001"])
        use_project(root)
        inside = RF.write(task)
        check("inside the project: written", inside["ok"], str(inside["lines"]))
        use_project(other)
        check_eq("(control) from the other project the same words name no case", C.case_ids(words), [])
        outside = RF.write(task2)
        check("outside the project: written", outside["ok"], str(outside["lines"]))
        a, b = (task / "test-report.md").read_bytes(), (task2 / "test-report.md").read_bytes()
        check_eq("a render from outside the project is the same bytes as one from inside",
                 hashlib.sha256(a).hexdigest(), hashlib.sha256(b).hexdigest())
        text = a.decode("utf-8")
        check_not_in("and the item the words answer was taken out, from both", "Access after cancelling", text)
        check_in("and the gate B block names the case, from both", 'Your words name AB-1_TC_002: "AB-1_TC_002: run it yourself, I accept the risk."', text)
        # the other callers of `decided_cases` keep today's resolution when no config is handed over
        use_project(root)
        decided = T.decided_cases(pipeline)
        check_eq("cfg None: the process's own project decides, as before", sorted(decided), ["AB-1_TC_002"])
        use_project(other)
        check_eq("cfg None from another project: its own forms, as before", T.decided_cases(pipeline), {})
        check_eq("cfg handed over: the story's forms, wherever the process stands",
                 sorted(T.decided_cases(pipeline, C.case_config(task2))), ["AB-1_TC_002"])
    finally:
        use_project(root)
        cleanup(root)
        cleanup(other)
        cleanup(copy.parent)


def the_cut() -> None:
    """The one truncation of the blocks: the first-reason sentence, 200 characters, a word boundary, an ellipsis."""
    word = "abcdefghi "
    at = (word * 30)[:200]
    check_eq("a sentence of exactly 200 characters is whole", RF._cut(at), at.strip())
    over = (word * 30)[:201]
    cut = RF._cut(over)
    check_eq("one character more is cut", cut.endswith(RF.ELLIPSIS), True)
    check("and the cut text is at most 200 characters, ellipsis included", len(cut) <= 200, str(len(cut)))
    check("on a word boundary", cut[:-1].split(" ")[-1] == "abcdefghi", cut[-30:])
    exact = ("abcdefghi " * 21)[:199] + "z"
    check_eq("exactly 200 characters of several words, ending in a letter, are whole", (len(exact), RF._cut(exact)), (200, exact))
    check_eq("the same plus one character is cut", RF._cut(exact + "q").endswith(RF.ELLIPSIS), True)
    check_eq("199 is whole", RF._cut("x" * 199), "x" * 199)
    check_eq("200 of one long word is whole", RF._cut("y" * 200), "y" * 200)
    hard = RF._cut("z" * 201)
    check_eq("one word longer than the room is cut where it stands", (len(hard), hard.endswith(RF.ELLIPSIS)), (200, True))
    check_eq("an empty text stays empty", RF._cut(""), "")
    task = story(with_bug=False)
    try:
        long = "word " * 80
        write(task / "work" / "requirements-register.md", REGISTER.replace("Access lasts to the end of the paid period", long.strip()))
        v = RF.build(task)["verdict"]
        check("the verdict's reason in a real story is cut to the limit", len(v["first_reason"]) <= 200 and v["first_reason"].endswith(RF.ELLIPSIS), v["first_reason"])
        check("the full text is kept in the facts", len(v["first_reason_full"]) > 200)
    finally:
        cleanup(task.parents[2])


# --- (ix) Proven ------------------------------------------------------------------------------------------

def proven_rules() -> None:
    cases = {
        "unmeasured": test_row("t_unmeasured", reason="unmeasured"),
        "unchanged": test_row("t_unchanged", reason="unchanged"),
        "reached": test_row("t_reached", level="live", reason="", words="the check is live"),
        "handed": test_row("t_handed", reason="handed", words="not probed (handed to the person)"),
        "new, no live check": test_row("t_new", level=None, reason="", words="no live check"),
        "unknown level": test_row("t_unknown", level="unknown", reason="", words="proof level unknown"),
        "unverified": test_row("t_unverified", state="review_unverified"),
        "red": test_row("t_red", state="failed:APP_BUG"),
        "a legacy row with no proof_reason": {k: v for k, v in test_row("t_legacy").items() if k != "proof_reason"},
    }
    manifest = {"tests": [{"case": "TC-001", "covers": ["TC-001"], "file": "tests/api/test_a.py", "instance_id": ref,
                           "status": "green", "critic_verdict": "approved" if ref != "t_fixes" else "approved_with_fixes"}
                          for ref in [r["ref"] for r in cases.values()] + ["t_fixes", "t_noverdict"]]}
    for entry in manifest["tests"]:
        if entry["instance_id"] == "t_noverdict":
            del entry["critic_verdict"]
    rows = list(cases.values()) + [test_row("t_fixes"), test_row("t_noverdict"), dict(test_row("t_dead"), dead=True)]
    task = story(extra_ledger=ledger(rows))
    try:
        write(task / "work" / "automation-manifest.json", manifest)
        facts = RF.build(task)
        counted = sorted(t["instance"] for t in facts["tests"]["proven"])
        check_eq("Proven counts: reached, unchanged, unmeasured (V9), approved_with_fixes, and a legacy row it computes",
                 counted, ["t_fixes", "t_legacy", "t_reached", "t_unchanged", "t_unmeasured"])
        check_eq("excluded and said: handed, new with no live check, unknown, no verdict",
                 facts["tests"]["green_not_counted"], 4)
        check_eq("an unverified test is counted apart, never as proven", facts["tests"]["unverified"], 1)
        body = RF.render(facts)["proven"]
        check_in("the heading carries the code's count", "## Proven \u2014 5 green tests", body)
        check_in("each line has the critic's words and the level words", "reviewed by the code critic \u00b7 the check is live", body)
        check_in("an approved-with-fixes verdict keeps its own words (FR-35)", "fixes named", body)
        check_in("what was not counted is said", "4 more green tests are not counted", body)
        check_in("the code critic's unverified tests are told in the verdict",
                 "1 test could not be verified by the code critic", RF.render(facts)["verdict"])
    finally:
        cleanup(task.parents[2])
    task = story(extra_ledger=ledger([test_row("t_only", level=None, reason="", words="no live check")]))
    try:
        write(task / "work" / "automation-manifest.json", {"tests": [dict(MANIFEST["tests"][0], instance_id="t_only")]})
        body = render_all(task)["proven"]
        check("zero counted: the heading still stands and says 0 (never left out)", body.startswith("## Proven \u2014 0 green tests"), body[:60])
        check_in("and says so in words", "No green test is counted as proven.", body)
    finally:
        cleanup(task.parents[2])


def expectation_change_words() -> None:
    """F21: the words of a test changed after its red run reach the person in Proven."""
    import run_history as RH
    import s5_precheck as S5
    task = story()
    saved = (RH.expectation_changes, S5.word_passed_pairs)
    pair = {"function": "tests.api.test_a.test_a", "instance_ids": ["test_a"], "cases": ["TC-001"], "owed": True,
            "record": {"what_changed": "403 -> 401", "reason": "the case leaves the code open", "critic_verdict": "legitimate_correction"},
            "passed_by_word": False}
    other = {"function": "tests.api.test_gone.test_gone", "instance_ids": [], "cases": ["TC-002"], "owed": True, "record": None,
             "passed_by_word": True}
    try:
        RH.expectation_changes = lambda root, cases, manifest: {"pairs": [pair, other], "unmeasured": []}
        S5.word_passed_pairs = lambda root, changes, cases: [p for p in changes["pairs"] if p.get("passed_by_word")]
        write(task / "pipeline.json", {"ticket": "T-1", "gates": {"A": {"authorization_source": GATE_A}},
                                       "stage_overrides": [{"stage": "S5", "match": "changed-after-red", "decision": "let it stand"}]})
        body = render_all(task)["proven"]
        check_in("a recorded change is attached to its test, in words", "its expectation changed after a red run \u2014 403 -> 401 (the case leaves the code open)", body)
        check_in("with the critic's own verdict word", "recorded and judged: legitimate_correction", body)
        check_in("a change a person's word passed is listed, with their words, even when no proven test carries it",
                 'not recorded, passed by a person\'s word: "let it stand"', body)
        RH.expectation_changes = lambda root, cases, manifest: {"pairs": [], "unmeasured": ["a block could not be read"]}
        facts = RF.build(task)
        check_in("an unmeasured detector is an unknown entry, not silence (FR-41)", "a block could not be read", facts["unknown"].get("expectation_changes", ""))
        check_in("and the block says so", "Unknown which tests changed after a red run", RF.render(facts)["proven"])
        def boom(*_a):
            raise RuntimeError("detector broke")
        RH.expectation_changes = boom
        check_in("a detector that raises is an unknown entry too", "detector broke", RF.build(task)["unknown"].get("expectation_changes", ""))
    finally:
        RH.expectation_changes, S5.word_passed_pairs = saved
        cleanup(task.parents[2])


def probe_debt_line() -> None:
    """(x) R15: read-only `probe_debt.find`; N items -> the sentence with owner factory; 0 -> no line; raising -> unknown."""
    import probe_debt as PD
    task = story()
    saved = PD.find
    try:
        PD.find = lambda *a, **k: {"items": [{"instance_id": "a"}, {"instance_id": "b"}], "info": []}
        body = render_all(task)["proven"]
        check_in("N live checks not receipted: the sentence, owner factory",
                 "2 live checks ran and were not receipted \u2014 the factory's own bookkeeping (owner: factory).", body)
        PD.find = lambda *a, **k: {"items": [{"instance_id": "a"}], "info": []}
        check_in("one is singular", "1 live check ran and was not receipted", render_all(task)["proven"])
        PD.find = lambda *a, **k: {"items": [], "info": [{"why": "row gone"}]}
        check_not_in("none: no line", "not receipted", render_all(task)["proven"])
        def boom(*a, **k):
            raise OSError("no probes folder")
        PD.find = boom
        facts = RF.build(task)
        check_in("find raising is an unknown entry", "no probes folder", facts["unknown"].get("probe_debt", ""))
        check_in("said in the block", "Unknown whether live checks were left unreceipted", RF.render(facts)["proven"])
    finally:
        PD.find = saved
        cleanup(task.parents[2])


# --- (xi) questions ---------------------------------------------------------------------------------------

def open_questions() -> None:
    task = story()
    try:
        body = render_all(task)["open-questions"]
        check_in("open questions are listed in a code block with owner and text", "```\npo_ba \u00b7 Is a refund due after cancelling?\n", body)
        check_in("the heading carries the count", "## Open questions \u2014 2", body)
        write(task / "work" / "question-answers.jsonl", json.dumps(
            {"kind": "question", "id": "Q1", "status": "answered", "reading": "a", "words": "Q1: a", "where": "gate A",
             "by": "person", "at": "2026-09-30T10:00:00", "row_hash": ""}) + "\n")
        body = render_all(task)["open-questions"]
        check_not_in("an answered question gets no card", "refund", body)
        check_in("and the count follows", "## Open questions \u2014 1", body)
        write(task / "pipeline.json", {"ticket": "T-1", "gates": {"A": {"authorization_source": "Please look at Q2 again; Q2 stands"}}})
        body = render_all(task)["open-questions"]
        check_in("an id in the person's words without an answer record is `named`, with the note",
                 "(named in your gate A words; the factory recorded no answer)", body)
        # F-6 (t-596): a line that STARTS with the id and is no token is told as a line the factory did not read, never as "no answer"
        write(task / "pipeline.json", {"ticket": "T-1", "gates": {"A": {"authorization_source": "Q2: a question I read; Q2 stands"}}})
        body = render_all(task)["open-questions"]
        check_in("F-6 a stray line of a `named` question is told as that",
                 '(named in your gate A words, on a line the factory did not read as an answer: "Q2: a question I read; Q2 stands")', body)
        check_not_in("F-6 ... and not as `no answer`", "recorded no answer", body)
        write(task / "work" / "question-answers.jsonl", "")
        write(task / "work" / "requirements-readiness.json", {"open_questions": []})
        body = render_all(task)["open-questions"]
        check_in("an empty list prints none", "## Open questions \u2014 0\n\nnone", body)
        (task / "work" / "requirements-readiness.json").unlink()
        facts = RF.build(task)
        check_in("no register at all is unknown, not `none` (FR-41)", "no question register", facts["unknown"].get("questions", ""))
        check_in("and the block says unknown", "## Open questions \u2014 unknown", RF.render(facts)["open-questions"])
    finally:
        cleanup(task.parents[2])


# --- (xii) Not proven --------------------------------------------------------------------------------------

def not_proven_items() -> None:
    task = story()
    try:
        facts = RF.build(task)
        body = RF.render(facts)["not-proven"]
        ids = [i["id"] for i in facts["not_proven"]]
        # owner amendment 03.10: what the approved PLAN decided not to check (R-3, a `skip` row) is its own section, so
        # "Not proven" holds only the checks that could not execute
        check_eq("one item per requirement with no pass, no bug and no plan skip; a proven one is not here", ids, ["R-2", "R-4"])
        check_eq("the plan-skipped requirement stands in its own section", [i["id"] for i in facts["skipped"]], ["R-3"])
        skipped = RF.render(facts)["skipped-by-plan"]
        check_in("the section opens with the heading the amendment names", "## Skipped by the plan (approved at gate A)", skipped)
        check_in("and carries the plan's reason verbatim", "the app team's suite (plan row TS-3, skipped by the plan)", skipped)
        check_not_in("R-3 is not under Not proven", "R-3", body)
        check_in("the risk comes from the plan row's impact class through the data table and its defect hypothesis",
                 "risk: money can be charged, paid or counted wrongly in production; the plan's defect hypothesis: boundary @ period end", body)
        check_in("a requirement no plan row names: said, not guessed (FR-41)", "risk: not assessed at planning \u2014 no plan row", body)
        # the deferred branch of "Not proven" (a deferral no plan row and no gate A waiver stands behind), by the pure helper
        item = {"id": "R-9", "class": "deferred", "bases": ["parked"], "plan_row": "", "impact": "", "hypothesis": "", "partly": []}
        plan_rows = [{"ts": "TS-9", "requirements": ["R-9"], "disposition": "automate", "reason": "x"}]
        bare = RF._not_proven({"items": [item]}, plan_rows, {})
        check_in("a deferred item says there is no word of the person's about it", "no word of yours about it is recorded",
                 bare[0]["cause"])
        said = RF._not_proven({"items": [item]}, plan_rows,
                              {"gates": {"B": {"authorization_source": "R-9: put it aside, I decide that"}}})
        check_in("a deferred item is listed with the person's words when they name it", 'your words: "R-9: put it aside, I decide that"',
                 said[0]["cause"])
        # a gate A waiver is the plan's own decision (the person approved it there); a gate B one is not
        gate_a = {"gate_waivers": [{"gate": "A", "requirement": "R-9", "decision": "not this release", "at": "x"}]}
        check_eq("a gate A waiver moves the requirement to the plan-skipped section, with their words",
                 [(i["id"], i["cause"]) for i in RF._skipped_by_plan({"items": [item]}, plan_rows, gate_a)],
                 [("R-9", 'your words at gate A: "not this release"')])
        check_eq("and out of Not proven", RF._not_proven({"items": [item]}, plan_rows, gate_a), [])
        gate_b = {"gate_waivers": [{"gate": "B", "requirement": "R-9", "decision": "not this release", "at": "x"}]}
        check_eq("a gate B waiver does not: the person's word there is not the approved plan's",
                 (RF._skipped_by_plan({"items": [item]}, plan_rows, gate_b), len(RF._not_proven({"items": [item]}, plan_rows, gate_b))),
                 ([], 1))
        check_in("every item has the `R-n`, the cause and ` : ` before the risk", "- **R-2** \u2014 ", body)
        table = json.loads(RF.RISK_WORDS_PATH.read_text(encoding="utf-8"))["impact"]
        check_eq("the risk table holds words for every class of the plan's own scale (FR-13: data, not code)",
                 sorted(set(G.IMPACT_SCALE) - set(table)), [])
        write(task / "test-plan.md", PLAN.replace("| money |", "| sentiment |"))
        check_in("a class the table does not hold is quoted as written, not interpreted", 'the impact class "sentiment"',
                 render_all(task)["not-proven"])
        write(task / "test-plan.md", PLAN.replace("| money |", "|  |"))
        check_in("a plan row with no impact class says so", "the plan row TS-2 records no impact class", render_all(task)["not-proven"])
        check_not_in("the test-plan's project-wide environment finding is never an item here (F17)", "s5_environment", body)
    finally:
        cleanup(task.parents[2])


def answered_suffix() -> None:
    """R-216a.1, report side: a cause that cites a question answered at gate A carries the suffix (once);
    `named` is never read as answered (Q10)."""
    task = story()
    try:
        write(task / "test-plan.md", PLAN.replace("needs a billing cycle", "rests on open question Q1"))
        body = render_all(task)["not-proven"]
        check_not_in("a question only named in the person's words gets no suffix", "answered at gate A", body)
        write(task / "pipeline.json", {"ticket": "T-1", "gates": {"A": {"authorization_source": "Q1: a, go on"}}})
        check_not_in("an id in the person's words with no answer record is `named`: no suffix", "answered at gate A", render_all(task)["not-proven"])
        write(task / "work" / "question-answers.jsonl", json.dumps(
            {"kind": "question", "id": "Q1", "status": "answered", "reading": "a", "words": "Q1: a, go on", "where": "gate A",
             "by": "person", "at": "2026-09-30T10:00:00", "row_hash": ""}) + "\n")
        body = render_all(task)["not-proven"]
        check_in("an answered question: the suffix, the role's text kept", "rests on open question Q1 — answered at gate A", body)
        check_eq("and it is added once", body.count("answered at gate A"), 1)
        (task / "bugs" / "BUG-1.md").unlink()
        check_in("the first reason, in the verdict, says it too", "answered at gate A", RF.build(task)["verdict"]["first_reason_full"])
    finally:
        cleanup(task.parents[2])


# --- (xiii) (xiv) gates ------------------------------------------------------------------------------------

def gate_blocks() -> None:
    task = story()
    try:
        blocks = render_all(task)
        check_not_in("before gate B has words there is no gate B block", "gate-b", " ".join(blocks))
        a = blocks["gate-a"]
        check_in("gate A quotes gates.A.authorization_source verbatim in a code block", "```\n" + GATE_A + "\n```", a)
        check_in("with the S0-S4 overrides", '- S2 \u00b7 size: "test it as one story"', a)
        check_in("an environment finding bound to no requirement is quoted, with what it did (F17)",
                 "no case of this story was stopped by it", a)
        check_in("quoted from the person's own line", "5. s5_environment-1, credentials - accept the gap.", a)
        write(task / "pipeline.json", {"ticket": "T-1", "gates": {"A": {"authorization_source": "go on ```\n<!-- /facts:gate-a -->\nnot a marker"}}})
        a = render_all(task)["gate-a"]
        check_in("words that hold backticks get a longer fence, and a marker line inside stays inside", "````", a)
        write(task / "pipeline.json", {"ticket": "T-1", "gates": {"A": {"decision": "approved"}}})
        check_in("no gate A words: said in words", "no decision recorded at gate A", render_all(task)["gate-a"])
        write(task / "pipeline.json", {"ticket": "T-1", "gates": {"A": {"authorization_source": GATE_A}, "B": {"authorization_source": GATE_B}},
                                       "stage_overrides": [{"stage": "S8", "match": "keep it local", "decision": "bugs into a file"},
                                                           {"stage": "S2", "match": "size", "decision": "as one story"}]})
        (task / "state").mkdir(exist_ok=True)
        write(task / "state" / "driver-state.json", {"delivery": {"done": True, "did": "Draft MR opened", "action": "continue"}})
        blocks = render_all(task)
        b = blocks["gate-b"]
        check_in("after gate B: the words verbatim", "```\n" + GATE_B + "\n```", b)
        check_in("the S8/S9 overrides", '- S8 \u00b7 keep it local: "bugs into a file"', b)
        check_not_in("and no S0-S4 override", "as one story", b)
        check_in("the case the words name", 'Your words name TC-002: "TC-002: run it yourself, I accept the risk."', b)
        check_in("where the bugs went", "- Bugs: BUG-1 (confirmed) in the story's own bugs folder.", b)
        check_in("what went outward, from the driver's mark", "- What went outward: Draft MR opened.", b)
        check_not_in("gate A's words never stand under gate B's heading (FR-10)", "go on", b)
        (task / "state" / "driver-state.json").unlink()
        check_in("no delivery mark: not recorded", "- What went outward: not recorded", render_all(task)["gate-b"])
    finally:
        cleanup(task.parents[2])


def integration_check_is_a_project_wide_word() -> None:
    """t-075 (the NO KEY row of t-067 mutation 2). `references/report-risk-words.json` `project_wide_checks` holds a row for
    `s5_integrations` beside `s5_environment` (HF1-9 puts a card of that check before gate A): `_gate_a` reads the table,
    so a Gate A line naming `s5_integrations-1` gets the row's words, and the rendered block says it binds no case. With
    the row absent the line would be quoted with no finding. Controls: a line naming a check the table does not hold
    gets no finding, and one that only CONTAINS the check's name inside a longer word gets none either."""
    line = "5. s5_integrations-1, keys - accept the gap."
    words = "Gate A: approved, go on.\n\n" + line
    found = RF._gate_a({"gates": {"A": {"authorization_source": words}}}, None, {})["env_findings"]
    check_eq("_gate_a: the integration check named in the person's words is a finding, with the table's words",
             [(f["id"], f["what"]) for f in found],
             [("s5_integrations-1", "a project-wide check of an integration's keys when no case could be tied to it; "
                                    "it binds no requirement and no case")])
    check_in("and the finding quotes the person's own line", line, found[0]["line"] if found else "")
    for label, text in (("a check the table does not hold", "5. s5_unknown-1, keys - accept the gap."),
                        ("the name inside a longer word", "5. xs5_integrations-1, keys - accept the gap.")):
        check_eq(f"_gate_a control: {label} is no finding",
                 RF._gate_a({"gates": {"A": {"authorization_source": "Gate A: go on.\n\n" + text}}}, None, {})["env_findings"], [])
    task = story(pipeline={"ticket": "T-1", "gates": {"A": {"authorization_source": words}}})
    try:
        block = render_all(task)["gate-a"]
        check_in("the rendered gate A block says what it did: a project-wide check of an integration's keys",
                 "a project-wide check of an integration's keys when no case could be tied to it", block)
        check_in("and quotes the line", line, block)
    finally:
        cleanup(task.parents[2])


def every_project_wide_word_has_a_key() -> None:
    """GW1-20 (a data row with no reading test, FR-28, FR-32). Every word of `project_wide_checks` in
    `references/report-risk-words.json` is named in this file: a row added with no key that names it fails here, not
    later in a report. Control: a word the file does not name (built from two halves, so this file does not name it
    either) is reported by the same function."""
    words = json.loads((SCRIPTS.parent / "references" / "report-risk-words.json").read_text(encoding="utf-8"))["project_wide_checks"]
    source = Path(__file__).read_text(encoding="utf-8")

    def unkeyed(table: dict) -> list:
        return sorted(word for word in table if f'"{word}' not in source and f"`{word}" not in source and f"{word}-1" not in source)

    check("project_wide_checks is a non-empty table of words", isinstance(words, dict) and len(words) > 0, str(words))
    check_eq("every word of project_wide_checks has a key in this file", unkeyed(words), [])
    ghost = "s5_" + "nokey_word"
    check_eq("control: a word no key names is reported", unkeyed({**words, ghost: "x"}), [ghost])


# --- (xv) (xvi) size and where to look --------------------------------------------------------------------

def size_and_where() -> None:
    task = story()
    try:
        s = render_all(task)["size"]
        check_in("a size computed at S2 is the forecast even when the pipeline holds none",
                 "Forecast: **M** \u2014 the requirements weigh 9 (each weighted by its priority and area); the M cap is 13.", s)
        check_in("the fact is the template's counts", "Fact: **M** \u2014 4 testable requirements, 3 plan rows, 2 cases, 1 tests.", s)
        check_in("no difference", "Difference: none.", s)
        write(task / "pipeline.json", {"ticket": "T-1", "size": "L", "size_initial": "M", "size_final": "L", "size_reason": "re-estimated", "gates": {}})
        check_in("a re-estimate is shown", "Difference: M -> L (re-estimated).", render_all(task)["size"])
        # t-357 (critic t-346 F7): a half of the forecast that is missing is said in its own words - never "computed budget"
        sizing = task / "work" / "sizing.json"
        held = sizing.read_text(encoding="utf-8")
        write(sizing, {"size": "M", "computed_budget": 9, "verifiable_count": 4})
        s = render_all(task)["size"]
        check_in("F7: the weight known and the cap not: the weight, and that no cap is recorded for the size",
                 "Forecast: **M** — the requirements weigh 9 (each weighted by its priority and area); no cap is recorded for size M.", s)
        write(sizing, {"size": "M", "cap": 13, "verifiable_count": 4})
        s = render_all(task)["size"]
        check_in("F7: the cap known and the weight not: the cap, and that the weight is not recorded",
                 "Forecast: **M** — the M cap is 13; what the requirements weigh is not recorded.", s)
        write(sizing, {"size": "M", "verifiable_count": 4})
        s = render_all(task)["size"]
        check_in("F7: neither recorded: both said unknown, with why (FR-41)",
                 "Forecast: **M** — what the requirements weigh is unknown (no sizing record).", s)
        write(sizing, {"size": "M", "cap": 0, "computed_budget": 0})
        s = render_all(task)["size"]
        check_in("F7 AT the edge: a weight of 0 and a cap of 0 are numbers, not absences",
                 "the requirements weigh 0 (each weighted by its priority and area); the M cap is 0.", s)
        import human_text
        for label, body in (("both", {"size": "M", "cap": 13, "computed_budget": 9}), ("weight only", {"size": "M", "computed_budget": 84}),
                            ("cap only", {"size": "M", "cap": 13}), ("neither", {"size": "M"})):
            write(sizing, body)
            for old in ("computed budget", "computed_budget", "a weighted count of expected cases"):
                check_not_in(f"F7 ({label}): the jargon {old!r} is never said to a person", old, render_all(task)["size"])
            check_eq(f"F7 ({label}) (t-357 vi): the size block breaks no rule of human-questions.md (human_text.problems == [])",
                     human_text.problems(render_all(task)["size"], kind="report"), [])
        check_in("F7 control: the same checker catches a ledger field named in code quotes in a report",
                 "snake_token", [p["rule"] for p in human_text.problems("Forecast: `computed_budget` is unknown.", kind="report")])
        sizing.write_text(held, encoding="utf-8")
        (task / "work" / "sizing.json").unlink()
        write(task / "pipeline.json", {"ticket": "T-1", "gates": {}})
        s = render_all(task)["size"]
        check_in("nothing recorded anywhere: unknown, with why (FR-41)", "Forecast: unknown \u2014 no size was recorded", s)
        check_in("the fact's size is not invented", "Fact: size not recorded", s)
        w = render_all(task)["where-to-look"]
        check_in("the real headings of understanding.md", "- understanding.md \u2014 sections: Why this change; What we verify", w)
        check_in("a plan with no retro: the retro has not run", "retro.md \u2014 not written: the retro has not run", w)
        check_not_in("never a work/ path", "work/", w)
        write(task / "pipeline.json", {"ticket": "T-1", "retro_mode": "skip", "retro_mode_words": "no retro, thanks", "gates": {}})
        check_in("a retro the person skipped carries their words", 'you chose to skip it \u2014 "no retro, thanks"', render_all(task)["where-to-look"])
        write(task / "retro.md", "# Retro\n\n## Time\n\n## Cost by role\n")
        check_in("a retro that exists lists its headings", "- retro.md \u2014 sections: Time; Cost by role", render_all(task)["where-to-look"])
    finally:
        cleanup(task.parents[2])


# --- (i) every source absent ------------------------------------------------------------------------------

def every_source_absent() -> None:
    """(i) A story with nothing: every count is an `unknown` entry with its reason, never 0 (mutation c)."""
    root = temp_dir("qa-report-empty-")
    task = root / "qa-factory" / "artifacts" / "T-9"
    task.mkdir(parents=True)
    try:
        facts = RF.build(task)
        for key in ("pipeline", "ledger", "requirements", "questions"):
            check(f"unknown entry for {key}", bool(facts["unknown"].get(key)), str(facts["unknown"]))
        blocks = RF.render(facts)
        v = blocks["verdict"]
        check_in("the verdict says unknown, not ready and not not-ready", "**Verdict: unknown.**", v)
        check_in("requirements: unknown in words", "Requirements: unknown \u2014 no requirements register was found", v)
        check_not_in("an unknown count is never printed as 0", "Of 0 requirements", v)
        check_not_in("nor as a zero list of counts", "0 proven by tests", v)
        check_in("tests: unknown", "Tests: unknown", v)
        check_in("the ledger's absence reaches the delivery line in words", "`delivery_ready: unknown \u2014 the factory's record of the checks was not found", v)
        check_in("proven: unknown", "## Proven \u2014 unknown", blocks["proven"])
        check_not_in("proven is not `0 green tests` when it is not known", "0 green tests", blocks["proven"])
        check_in("bugs: read, none found, with the folders named", "None found (looked in the story's own bugs folder: no such folder", blocks["bugs"])
        check_in("questions: unknown", "## Open questions \u2014 unknown", blocks["open-questions"])
        check_in("not proven: unknown", "Unknown what is not proven", blocks["not-proven"])
        check_in("gate A: unknown", "Unknown what was decided at gate A", blocks["gate-a"])
        s = blocks["size"]
        check_in("size: the counts are unknown, not 0",
                 "Fact: size not recorded — unknown testable requirements, unknown plan rows, unknown cases, unknown tests.", s)
        check_not_in("a count of a source that is absent is not 0", "0 ", s.replace("Forecast: unknown", ""))
        check_eq("nothing in any block is cut or empty", all(body.strip() for body in blocks.values()), True)
        check_eq("no work/ path anywhere", any("work/" in body for body in blocks.values()), False)
        (task / "work").mkdir()
        (task / "work" / "requirements-register.md").write_text("## Register\n\n| R | Requirement |\n|---|---|\n", encoding="utf-8")
        facts = RF.build(task)
        v = RF.render(facts)["verdict"]
        check_in("a register that exists and is empty is a fact: 0 requirements, and the register is empty", "(the register is empty)", v)
    finally:
        cleanup(root)


# --- (ii) (iii) (iv) the report file ----------------------------------------------------------------------

def legacy_report(task: Path, crlf: bool = False) -> str:
    text = """# T-1 \u2014 test report

**The change.** Cancelling a subscription from settings.

**Verdict: not ready to ship as is.** 9 green tests. No product bug is recorded.

`delivery_ready: no`

Notation: R-n - a requirement; TC-n - a test case.

## Proven \u2014 9 green tests

- a hand-typed line, 9 of them

## Product bugs \u2014 0 confirmed \u00b7 0 unconfirmed

None recorded.

## Left with you

1. **Access after cancelling (R-2, TC-002).** To check: the subscription answers until the period ends. How: check by hand.

## Not proven, and what it costs

- **R-2** \u2014 nobody waited out a period.

## Decided at gate B

Not yet decided. Gate A, in the person's words: "Gate A: approved, go on."

## Factory defects \u2014 nothing is wanted from you

Nothing this run. The scribe's own prose stays.

## Size

Forecast: XXL
Fact: not recorded

## Where to look

- somewhere

## Appendix \u2014 traceability

@APPENDIX@

## Retro proposals

- the analyst's appended proposal stays
"""
    # The scribe pastes `traceability.py --render` verbatim (qa-doc-scribe.md), and `--check` compares it with a fresh render
    # (HF2-6b): this report carries the render of the story as it stands when the report is written.
    text = text.replace("@APPENDIX@", T.render(T.build(task.parents[1], task)).strip("\n"))
    if crlf:
        text = text.replace("\n", "\r\n")
    (task / "test-report.md").write_bytes(text.encode("utf-8"))
    return text


def report_absent() -> None:
    task = story()
    try:
        w = RF.write(task)
        check_eq("no report: --write refuses", w["ok"], False)
        check_in("naming S8's scribe as the door", "story_step.py start --task T-1 --stage S8 --role qa-doc-scribe", w["lines"][0])
        check_in("and saying what it expected", "does not start one", w["lines"][0])
        problems = RF.check(task)
        check_in("--check refuses the same way", "story_step.py start --task T-1 --stage S8 --role qa-doc-scribe", problems[0])
        r = cli(task, "--write")
        check_eq("the CLI exits 1", r.returncode, 1)
        r = cli(task, "--check")
        check_eq("and so does --check", r.returncode, 1)
        check("no report file was made", not (task / "test-report.md").exists())
    finally:
        cleanup(task.parents[2])


def legacy_check_passes() -> None:
    task = story()
    try:
        legacy_report(task)
        notes: list = []
        check_eq("an unmarked report passes --check", RF.check(task, notes), [])
        check_eq("and says it is not checked (P8's line)", notes, [G.LEGACY_FACTS_LINE])
        r = cli(task, "--check")
        check_eq("CLI: exit 0 on a legacy report", r.returncode, 0)
        check_in("and prints the legacy line", G.LEGACY_FACTS_LINE, r.stdout)
    finally:
        cleanup(task.parents[2])


def conversion_inline() -> None:
    """(iii) an unmarked report: old bytes saved first, code-owned sections become blocks, prose stays."""
    for crlf in (False, True):
        task = story()
        try:
            legacy_report(task, crlf)
            raw = (task / "test-report.md").read_bytes()
            w = RF.write(task)
            name = "CRLF" if crlf else "LF"
            check(f"[{name}] --write succeeds on a legacy report", w["ok"], str(w["lines"]))
            sha = hashlib.sha256(raw).hexdigest()[:12]
            saved = task / "state" / "report-history" / f"test-report-{sha}.md"
            check(f"[{name}] the old bytes are saved to state/report-history/test-report-<sha12>.md first", saved.is_file())
            check_eq(f"[{name}] byte for byte", saved.read_bytes() if saved.is_file() else b"", raw)
            new = (task / "test-report.md").read_bytes().decode("utf-8")
            blocks = G.find_blocks(new)
            check_eq(f"[{name}] every block is there but gate B (no words yet)", sorted(blocks),
                     sorted(set(G.REPORT_BLOCKS) - set(G.REPORT_BLOCKS_AFTER_GATE_B) - set(G.REPORT_BLOCKS_WHEN_PRESENT)))
            check_in(f"[{name}] prose outside the blocks is kept: the change", "Cancelling a subscription from settings.", new)
            check_in(f"[{name}] the Left with you item with its How text", "How: check by hand.", new)
            check_in(f"[{name}] the factory defects paragraph", "The scribe's own prose stays.", new)
            check_in(f"[{name}] the retro analyst's appended proposals", "the analyst's appended proposal stays", new)
            check_in(f"[{name}] the notation line and the appendix", "| R-1 | Cancel | TC-001 |", new)
            check_not_in(f"[{name}] the hand-typed Proven line is gone (it was code's)", "a hand-typed line", new)
            check_not_in(f"[{name}] the old gate B section held gate A's words: it is gone, not kept", "Not yet decided. Gate A", new)
            check_not_in(f"[{name}] nor is the old verdict kept beside the new one", "9 green tests. No product bug", new)
            check_eq(f"[{name}] one delivery_ready line", len(re.findall(r"delivery_ready:", new)), 1)
            order = [m.group(1) for m in re.finditer(r"<!-- facts:([a-z-]+) -->", new)]
            check_eq(f"[{name}] the blocks stand in the template's order", order,
                     [b for b in G.REPORT_BLOCKS if b not in G.REPORT_BLOCKS_AFTER_GATE_B and b not in G.REPORT_BLOCKS_WHEN_PRESENT])
            check_in(f"[{name}] the change paragraph stays above the verdict", "**The change.**", new.split("<!-- facts:verdict -->")[0])
            check_eq(f"[{name}] --check passes after --write", RF.check(task), [])
            r = cli(task, "--check")
            check_eq(f"[{name}] CLI --check exit 0", r.returncode, 0)
            again = RF.write(task)
            check_eq(f"[{name}] a second --write changes nothing", (again["ok"], (task / "test-report.md").read_bytes().decode("utf-8")), (True, new))
            if crlf:
                body = blocks["verdict"][2]
                check_not_in("[CRLF] LF inside a block whatever the file uses", "\r", body)
                check("[CRLF] the prose outside a block keeps its CRLF", "**The change.** Cancelling a subscription from settings.\r\n" in new)
            errors: list = []
            V.check_test_report(task / "test-report.md", errors)
            mine = [e for e in errors if "block" in e or "section" in e or "gate" in e.lower()]
            check_eq(f"[{name}] the report contract (P8) has nothing to say about the blocks or the sections", mine, [])
        finally:
            cleanup(task.parents[2])


def edit_inside_a_block() -> None:
    """(iv) bytes edited inside a block: saved to history, one line names the block."""
    task = story()
    try:
        legacy_report(task)
        RF.write(task)
        path = task / "test-report.md"
        text = path.read_text(encoding="utf-8")
        edited = text.replace("Product bugs: 1 confirmed", "Product bugs: 7 confirmed")
        check("the fixture is edited", edited != text)
        path.write_text(edited, encoding="utf-8", newline="")
        problems = RF.check(task)
        check_eq("--check names the edited block, with the door", [p for p in problems if "`verdict`" in p and "--write" in p] != [], True)
        w = RF.write(task)
        check_eq("--write refreshes it", w["ok"], True)
        sha = hashlib.sha256(edited.encode("utf-8")).hexdigest()[:12]
        check("the edited bytes are in report-history", (task / "state" / "report-history" / f"test-report-{sha}.md").is_file())
        check_eq("one line names the block", [ln for ln in w["lines"] if "replaced block `verdict`" in ln] != [], True)
        check_in("and the edit is gone from the report", "1 confirmed", path.read_text(encoding="utf-8"))
        before = sorted((task / "state" / "report-history").iterdir())
        RF._history(task, edited.encode("utf-8"))
        check_eq("saving the same bytes twice is a no-op (never overwritten)", sorted((task / "state" / "report-history").iterdir()), before)
    finally:
        cleanup(task.parents[2])


def damaged_markers() -> None:
    task = story()
    try:
        legacy_report(task)
        RF.write(task)
        path = task / "test-report.md"
        text = path.read_text(encoding="utf-8").replace("<!-- /facts:size -->\n", "")
        path.write_text(text, encoding="utf-8", newline="")
        before = path.read_bytes()
        w = RF.write(task)
        check_eq("damaged markers: --write refuses and changes nothing", (w["ok"], path.read_bytes() == before), (False, True))
        check_in("naming the block and the expected closing marker", "<!-- /facts:size -->", " ".join(w["lines"]))
        check_in("and a door the scribe can use", "story_step.py start --task T-1 --stage S8 --role qa-doc-scribe", " ".join(w["lines"]))
        check_eq("--check refuses too", any("size" in p for p in RF.check(task)), True)
    finally:
        cleanup(task.parents[2])


def older_contract_report() -> None:
    task = story()
    try:
        (task / "test-report.md").write_text("# T-1\n\n## Verdict\n\n## Check coverage\n\n| a | b |\n", encoding="utf-8")
        w = RF.write(task)
        check_eq("a report of the older section list is refused, untouched", w["ok"], False)
        check_in("with the scribe as the door", "story_step.py start --task T-1", w["lines"][0])
    finally:
        cleanup(task.parents[2])


# --- (v) --check -------------------------------------------------------------------------------------------

def check_is_pure_and_exact() -> None:
    task = story(pipeline={"ticket": "T-1", "gates": {"A": {"authorization_source": GATE_A}}})
    try:
        legacy_report(task)
        RF.write(task)
        root = task.parents[2]
        before = tree_hash(root)
        check_eq("a written report checks clean", RF.check(task), [])
        r = cli(task, "--check")
        check_eq("CLI exit 0 and the tree is untouched (FR-45)", (r.returncode, tree_hash(root) == before), (0, True))
        # a block that differs from a fresh render
        path = task / "test-report.md"
        path.write_text(path.read_text(encoding="utf-8").replace("Open questions \u2014 2", "Open questions \u2014 9"), encoding="utf-8", newline="")
        before = tree_hash(root)
        r = cli(task, "--check")
        check_eq("a stale block: exit 1", r.returncode, 1)
        lines = [ln for ln in r.stdout.splitlines() if ln.strip()]
        check_eq("one line per problem", len(lines), 1)
        check_in("FR-1: names the block, what is expected and the door", "block `open-questions` differs from a fresh render", lines[0])
        check_in("the door is --write", "report_facts.py --task T-1 --write", lines[0])
        check_eq("--check changed nothing", tree_hash(root), before)
        RF.write(task)
        # gate B words without the block
        write(task / "pipeline.json", {"ticket": "T-1", "gates": {"A": {"authorization_source": GATE_A}, "B": {"authorization_source": GATE_B}}})
        problems = RF.check(task)
        check_eq("gate B words without the block", [p for p in problems if "gate B has recorded words but the report has no `gate-b` block" in p] != [], True)
        RF.write(task)
        check_eq("--write renders it and the report checks clean", RF.check(task), [])
        write(task / "pipeline.json", {"ticket": "T-1", "gates": {"A": {"authorization_source": GATE_A}}})
        check_eq("a gate B block before the gate has words is refused too", any("stands before gate B" in p for p in RF.check(task)), True)
        # a Not proven item missing a part
        RF.write(task)
        text = path.read_text(encoding="utf-8")
        broken = re.sub(r"\n- \*\*R-2\*\* .*", "\n- **R-2** \u2014 nobody waited", text, count=1)
        check("the Not proven line was found", broken != text)
        path.write_text(broken, encoding="utf-8", newline="")
        problems = RF.check(task)
        check_eq("a Not proven item with no risk is named", [p for p in problems if "lacks its requirement, its cause or its risk" in p] != [], True)
    finally:
        cleanup(task.parents[2])


LIFT_RUN = {"execution_status": "passed", "env_preflight": "pass", "manual_checks": [], "impossible": [], "env_blocked": [],
            "current_env_blocked": [], "totals": {}, "results": [],
            "current_results": [{"instance_id": "g101", "test_id": "tests.m.g101", "status": "partial",
                                 "current_reason": "instance_manifest_join_failed", "raw_status": "not_run",
                                 "case_version_links": [{"case_id": "TC-101", "version": "v1"}]}]}

LIFT_PLAN = ("---\ntask: T-2\n---\n\n## Plan\n\n| TS | what we verify | R | defect hypothesis | impact class | priority | observable | oracle | "
             "disposition + reason | fit | level | technique |\n|---|---|---|---|---|---|---|---|---|---|---|---|\n"
             "| TS-101 | a check | R-101 | h | money | P0 | expected-contract | requirement:R-101 | `automate` - reason | new | api | t |\n"
             "| TS-102 | a check | R-102 | h | money | P0 | expected-contract | requirement:R-102 | `automate` - reason | new | api | t |\n")


def lift_case(cid: str, req: str, ts: str) -> str:
    return (f"---\nid: {cid}\ntitle: {cid}\narea: lift\npriority: P0\nstatus: Approved\nchannel: api\nreuse_decision: new\n"
            f"updated: 2026-09-30\ntask: T-2\ncovers: [{req}]\ndefect_class: contract\nbasis: requirement:{req}\n---\n\n"
            f"Requirements: {req}\nPlan row: {ts}\n\n## Steps\n\n| # | Action | Expected |\n|---|---|---|\n| 1 | act | see |\n")


FACTORY_ITEM = ("1. **The first (R-101, TC-101).** To check: a thing. There is no test. How: run it again.\n")
PRODUCT_ITEM = ("2. **The second (R-102, TC-102).** To check: another thing. There is no test. How: look at it.\n")
MIXED_ITEM = ("3. **Both (R-101, R-102, TC-101, TC-102).** To check: both things. How: look.\n")


def factory_owned_left_items() -> None:
    """(v) (d) a "Left with you" item whose refs are all the factory's own: --check names it, --write rebuilds the list."""
    root = temp_project("qa-report-lift-")
    task = root / "qa-factory" / "artifacts" / "T-2"
    work = task / "work"
    try:
        write(task / "test-plan.md", LIFT_PLAN)
        write(work / "test-cases" / "lift" / "TC-101.md", lift_case("TC-101", "R-101", "TS-101"))
        write(work / "test-cases" / "lift" / "TC-102.md", lift_case("TC-102", "R-102", "TS-102"))
        write(work / "run-report.json", LIFT_RUN)
        write(work / "automation-manifest.json", {"tests": [], "unresolved": []})
        write(work / "requirements-register.md", REGISTER.replace("R-1 ", "R-101 ").replace("R-2 ", "R-102 "))
        write(task / "pipeline.json", {"ticket": "T-2", "gates": {}})
        use_project(root)
        import check_delivery as CD
        lift = CD.case_ownership(task)
        check_eq("the fixture's ownership: TC-101 is only the reducer's doubt, TC-102 has no row", sorted(lift["factory_cases"]), ["TC-101"])
        body = "\n".join(["# T-2 \u2014 test report", "", "## Left with you", "", FACTORY_ITEM, PRODUCT_ITEM, MIXED_ITEM,
                          "- **Regression** \u2014 the factory does not run it.", ""])
        write(task / "test-report.md", "<!-- facts:size -->\n## Size\n\nx\n<!-- /facts:size -->\n\n" + body)
        # t-305 N8 (F10): ONE predicate decides the prune and the check - an item is removed (and not demanded) only when
        # the ledger says its case is closed: passed, or failed with a triage verdict. Here TC-101's doubt is resolved
        # (it passed) and TC-102 is still owed.
        closed = {"rows": [{"ref": "TS-101", "kind": "plan_row", "state": "passed_green", "detail": "TC-101"},
                           {"ref": "TS-102", "kind": "plan_row", "state": "not_executed:no result recorded for this row's cases",
                            "detail": "TC-102"}], "left_items": [], "delivery_ready": False, "delivery_verdict": "no"}
        write(work / "ledger.json", closed)
        problems = [p for p in RF.check(task) if "Left with you" in p]
        check_eq("--check names exactly the one item whose refs are all the factory's", len(problems), 1)
        check_in("it is the first item", "The first (R-101, TC-101)", problems[0])
        check_in("with the door", "report_facts.py --task T-2 --write", problems[0])
        w = RF.write(task)
        text = (task / "test-report.md").read_text(encoding="utf-8")
        check_not_in("--write takes it out of the list", "The first (R-101, TC-101)", text)
        check_in("a product item stays", "The second (R-102, TC-102)", text)
        check_in("an item with a product ref among its refs stays (direction of error: keep)", "Both (R-101, R-102, TC-101, TC-102)", text)
        check_in("an item with no refs (regression) stays", "**Regression**", text)
        check("the old report is saved (nothing is deleted)", any((task / "state" / "report-history").iterdir()))
        check_eq("and --check no longer finds it", [p for p in RF.check(task) if "Left with you" in p], [])
        check_eq("the line says what was taken out and why", any("all its refs are the factory's own bookkeeping" in ln for ln in w["lines"]), True)
        # K-N8.9: the same item while its case is STILL owed (a row that is not passed/triaged): kept, and --check is silent
        owed = json.loads(json.dumps(closed))
        owed["rows"][0]["state"] = "partial"
        write(work / "ledger.json", owed)
        write(task / "test-report.md", "<!-- facts:size -->\n## Size\n\nx\n<!-- /facts:size -->\n\n" + body)
        check_eq("K-N8.9: an open factory-owned item is NOT refused by --check", [p for p in RF.check(task) if "Left with you" in p], [])
        RF.write(task)
        check_in("K-N8.9: and --write keeps it", "The first (R-101, TC-101)", (task / "test-report.md").read_text(encoding="utf-8"))
        check_eq("K-N8.9: --write then --check -> nothing about Left with you", [p for p in RF.check(task) if "Left with you" in p], [])
    finally:
        cleanup(root)


# --- (vii) the verdict after gate B -----------------------------------------------------------------------

def verdict_change_after_gate_b() -> None:
    # t-305 N8 (F10): the item gate B's words name leaves only when the ledger says its case is closed (passed here)
    closed = ledger(rows=[test_row(), {"ref": "TS-2", "kind": "plan_row", "state": "passed_green", "detail": "TC-002"}])
    task = story(pipeline={"ticket": "T-1", "gates": {"A": {"authorization_source": GATE_A}}}, with_bug=False,
                 extra_ledger=closed)
    try:
        legacy_report(task)
        RF.write(task)
        path = task / "test-report.md"
        before = G.find_blocks(path.read_text(encoding="utf-8"))["verdict"][2]
        check_not_in("before gate B there is no change notice", "Changed since gate B", before)
        old_sentence = before.split("\n")[0].split(" Product bugs:")[0]
        write(task / "pipeline.json", {"ticket": "T-1", "gates": {"A": {"authorization_source": GATE_A}, "B": {"authorization_source": GATE_B}}})
        write(task / "bugs" / "BUG-1.md", BUG)   # the reporter filed it after gate B
        RF.write(task)
        check_not_in("an item gate B's words answered by naming its case leaves \"Left with you\" (close_gate_b's rule, kept)",
                     "Access after cancelling", path.read_text(encoding="utf-8"))
        after = G.find_blocks(path.read_text(encoding="utf-8"))["verdict"][2]
        check_in("the rebuild after gate B prints the old text", f'the verdict read "{old_sentence}"', after)
        check_in("and the new text", 'it now reads "**Verdict: not ready to ship as is.** Because BUG-1 is a confirmed product bug', after)
        check_eq("the late bug adds its headline to the render, and `--write` renders the appendix with it (HF8-22): --check passes",
                 RF.check(task), [])
        check_eq("the notice is stable: --check passes", RF.check(task), [])
        RF.write(task)
        again = G.find_blocks(path.read_text(encoding="utf-8"))["verdict"][2]
        check_eq("a third write keeps the OLD text from the previous block body, not the last one", again, after)
        (task / "bugs" / "BUG-1.md").unlink()
        RF.write(task)
        back = G.find_blocks(path.read_text(encoding="utf-8"))["verdict"][2]
        check_not_in("when the sentence reads as it did before gate B again, the notice goes", "Changed since gate B", back)
        repaste_appendix(task)
        check_eq("no change, no notice, and --check passes", RF.check(task), [])
    finally:
        cleanup(task.parents[2])


# --- (xvii) (xix) determinism, CLI, mid-flight --------------------------------------------------------------

def determinism() -> None:
    task = story()
    try:
        first = render_all(task)
        second = render_all(task)
        check_eq("(b) two renders of one story are identical bytes", json.dumps(first, sort_keys=True), json.dumps(second, sort_keys=True))
        joined = "\n".join(first.values())
        check_eq("no ISO timestamp inside a block", re.findall(r"\d{4}-\d\d-\d\d[T ]\d\d:\d\d", joined), [])
        check_eq("no clock time inside a block", re.findall(r"\b\d\d:\d\d:\d\d\b", joined), [])
        check_eq("LF inside blocks", "\r" in joined, False)
        facts_a = json.dumps(RF.build(task), sort_keys=True, default=str)
        facts_b = json.dumps(RF.build(task), sort_keys=True, default=str)
        check_eq("the facts are the same twice", facts_a, facts_b)
        for name, body in first.items():
            check(f"block `{name}` opens with its own heading (or is the verdict)", name == "verdict" or body.startswith(G.REPORT_BLOCK_HEADINGS[name]), body[:40])
        r1 = cli(task, "--json")
        r2 = cli(task, "--json")
        check_eq("--json: same bytes twice", r1.stdout, r2.stdout)
        check_eq("--json prints only JSON (FR-14)", json.loads(r1.stdout)["task"], "T-1")
        check_eq("and its keys are sorted", list(json.loads(r1.stdout)) == sorted(json.loads(r1.stdout)), True)
        legacy_report(task)
        r = cli(task, "--json", "--write")
        check_eq("--json with --write: stdout is still only JSON", json.loads(r.stdout)["task"], "T-1")
        check_in("and the write's lines go to stderr", "code-owned blocks refreshed", r.stderr)
        r = cli(task)
        check_in("no flag: the blocks are printed", "<!-- facts:verdict -->", r.stdout)
    finally:
        cleanup(task.parents[2])


def mid_flight() -> None:
    """(xix) before gate B and before the retro: what exists is rendered, nothing is final, nothing is invented."""
    task = story(pipeline={"ticket": "T-1", "gates": {"A": {"authorization_source": GATE_A}}})
    try:
        legacy_report(task)
        w = RF.write(task)
        text = (task / "test-report.md").read_text(encoding="utf-8")
        check_eq("written mid-flight", w["ok"], True)
        check_not_in("no gate B block before the gate", "facts:gate-b", text)
        check_in("the retro is marked as not run", "retro.md \u2014 not written: the retro has not run", text)
        check_not_in("no delivery line is invented", "Delivery:", text)
        check_eq("and the report checks clean", RF.check(task), [])
    finally:
        cleanup(task.parents[2])


def reports_keep_their_own_words() -> None:
    """The report's checks (P8) and forbidden spellings: a rendered report has no `work/` path, no hash id."""
    task = story(pipeline={"ticket": "T-1", "gates": {"A": {"authorization_source": GATE_A}, "B": {"authorization_source": GATE_B}}})
    try:
        legacy_report(task)
        RF.write(task)
        text = (task / "test-report.md").read_text(encoding="utf-8")
        body = text.split("## Appendix")[0]
        for needle in G.REPORT_FORBIDDEN:
            check_not_in(f"the rendered report carries no `{needle}`", needle, body)
        check_eq("no bare decision id", G.REPORT_BARE_DECISION_RE.findall(body), [])
    finally:
        cleanup(task.parents[2])


# --- cmp1: the real legacy report ------------------------------------------------------------------------

def cmp1_conversion() -> None:
    """The conversion road on a COPY of the cmp1 story (its report is an unmarked legacy one)."""
    source = CMP1 / "artifacts" / "TP1-13797"
    if not source.is_dir():
        print("SKIP the cmp1 conversion: the copy of the cmp1 story is not on this machine")
        return
    import shutil
    root = temp_dir("qa-report-cmp1-")
    try:
        shutil.copytree(CMP1, root / "qa-factory", ignore=shutil.ignore_patterns("TP1-13958", "TP1-14336", "TP1-14501", "TP1-15045"))
        task = root / "qa-factory" / "artifacts" / "TP1-13797"
        raw = (task / "test-report.md").read_bytes()
        check("the copy's report is an unmarked legacy one", not G.has_markers(raw.decode("utf-8")))
        notes: list = []
        check_eq("--check on it passes with the legacy line", (RF.check(task, notes), notes), ([], [G.LEGACY_FACTS_LINE]))
        before = tree_hash(root)
        r = cli(task, "--json")
        facts = json.loads(r.stdout)
        check_eq("building the facts writes nothing", tree_hash(root), before)
        check_eq("cmp1: the bug reader finds BUG-1 in the story's folder", facts["bugs"]["confirmed"], 1)
        check_eq("cmp1: nothing is unknown", facts["unknown"], {})
        w = RF.write(task)
        check("cmp1: --write ok", w["ok"], str(w["lines"]))
        sha = hashlib.sha256(raw).hexdigest()[:12]
        check("cmp1: the old report is in report-history, byte for byte",
              (task / "state" / "report-history" / f"test-report-{sha}.md").read_bytes() == raw)
        new = (task / "test-report.md").read_bytes().decode("utf-8")
        blocks = G.find_blocks(new)
        check_eq("cmp1: every block (gate B has words; `left-gate-b` waits for an answer that left a check), the manual-checks "
                 "block among them", sorted(blocks), sorted(set(G.REPORT_BLOCKS) - {"left-gate-b"} - set(G.REPORT_BLOCKS_WHEN_PRESENT)))
        check_in("cmp1: no manual-agent case was planned: 0 of 0 and the line says so", "## Checked by hand — 0 of 0", blocks["manual-checks"][2])
        check_in("cmp1: the change paragraph is kept", "GitHub webhook settings gain an optional JSON path filter", new)
        check_in("cmp1: the scribe's Factory defects paragraph is kept", "the ledger could not join 13 run rows", new)
        check_in("cmp1: the appendix is kept", "## Appendix", new)
        check_in("cmp1: the verdict now names BUG-1", "BUG-1 is a confirmed product bug", blocks["verdict"][2])
        check_not_in("cmp1: gate A's words are no longer under gate B's heading", "Not yet decided", new)
        check_in("cmp1: the size is the computed one", "Forecast: **XXL** \u2014 the requirements weigh 47 (each weighted by its priority and area); the XXL cap is 28", blocks["size"][2])
        # HF2-6b: the copy's appendix is the older generation's hand-typed table; the one thing --check still says about it is
        # that the appendix is not the render (the scribe's door), never a block
        check_eq("cmp1: --check after --write says nothing but the appendix", [p for p in RF.check(task) if "the appendix" not in p], [])
        check_eq("cmp1: a second --write is a no-op", RF.write(task)["lines"], ["test-report.md: every code-owned block already matches a fresh render"])
        errors: list = []
        V.check_test_report(task / "test-report.md", errors)
        check_eq("cmp1: nothing the contract refuses comes from a block", [e for e in errors if "block" in e or "gate" in e.lower()], [])
        print("cmp1 verdict block:\n" + blocks["verdict"][2])
    finally:
        cleanup(root)


# --- t-227c (P20, F7): the Thens whose expected value nobody confirmed are left with the person -------------------

def unconfirmed_expectations() -> None:
    """A Then the automator could not assert (no source for its value) reaches the report as a "Left with you" line:
    what to check, and the one answer wanted. The facts carry it as a structured entry read from the binding row
    (a field, never wording - FR-12); the scribe's section and t-250's block are written from it."""
    import question_register as QR
    task = story()
    try:
        facts = RF.build(task)
        check_eq("CONTROL: a story with no such binding lists nothing (every story before t-227)", facts["cases"]["unconfirmed"], [])
        manifest = dict(MANIFEST, then_bindings=[
            {"case": "TC-001", "then": 1, "instance_id": None, "assertion_ref": None, "status": "unresolved",
             "reason": "expectation_unconfirmed", "question": "Q1"}])
        write(task / "work" / "automation-manifest.json", manifest)
        facts = RF.build(task)
        found = facts["cases"]["unconfirmed"]
        check_eq("one entry, for the Then and the question the binding names",
                 [(i["case"].rsplit("/", 1)[-1], i["then"], i["question"], i["answered"]) for i in found], [("TC-001", 1, "Q1", False)])
        check_eq("its line is the spec's: what to check, and the answer wanted",
                 found[0]["line"], "To check: The subscription reads cancelled. Needed: your answer to Q1")
        check_eq("and the line is built by the one function", found[0]["line"],
                 RF.left_with_you_line("The subscription reads cancelled.", "Q1"))
        check_in("the case waits for a person (the traceability row is `wait`)", "TC-001", " ".join(facts["cases"]["to_check"]))
        check_eq("a binding that names no question still asks for one, in words",
                 RF.left_with_you_line("x", ""), "To check: x. Needed: a question about it, which nobody has raised yet")
        view = {q["id"]: q for q in QR.load(task)["questions"]}["Q1"]
        QR.record(task, "Q1", "answered", "Q1: a", "gate A", "driver", view["row_hash"], reading="a")
        again = RF.build(task)["cases"]["unconfirmed"]
        check_eq("answered since: the test was written before the answer, so no `Needed` line is owed (F19)",
                 [(i["answered"], i["line"]) for i in again], [(True, "")])
        write(task / "work" / "automation-manifest.json", dict(manifest, then_bindings=[dict(manifest["then_bindings"][0], status="covered")]))
        check_eq("a COVERED binding is not a gap", RF.build(task)["cases"]["unconfirmed"], [])
    finally:
        cleanup(task.parents[2])


# --- t-250 B3 (F10, P20): "Checked by hand" - what an agent checked in the product, shown to the person --------------

MC_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "manual-checks"
THENS = {"TC-001": "The subscription reads cancelled.", "TC-002": "Access lasts to the end of the paid period.",
         "TC-003": "Old invoices stay readable.", "TC-004": "The export keeps its column order.",
         "TC-005": "The export file is named after the owner."}
HAND_CASES = (("TC-001", "R-1", "TS-1"), ("TC-002", "R-2", "TS-2"), ("TC-003", "R-3", "TS-3"), ("TC-004", "R-4", "TS-4"))
CLAIM = {"r": "R-1", "value": "active", "ref": "base:b9c0c4e:settings.py:41", "source": "claim"}
NOT_RECORDED = {"r": "R-2", "value": None, "ref": None, "source": "not_recorded"}


def hand_case(cid: str, req: str, ts: str) -> str:
    return CASE.replace("1. The subscription reads cancelled.", "1. " + THENS[cid]).format(cid=cid, title=cid, req=req, ts=ts)


def evidence(task: Path, case: str, attempt: str, label: str, phase: str, kind: str = "image", payload=None,
             proves=("observed",), ext: str = ".png") -> dict:
    """One captured file under work/evidence/manual/<case>/<attempt>/ and the ref a record holds for it."""
    rel = f"work/evidence/manual/{case}/{attempt}/{label}{ext}"
    data = payload if payload is not None else f"{case}-{attempt}-{label}".encode()
    path = task / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return {"path": rel, "content_hash": hashlib.sha256(data).hexdigest(), "kind": kind, "phase": phase,
            "captured_at": "2026-10-01T10:00:00+00:00", "proves": list(proves), "mask_acknowledged": True}


def export_ref(task: Path, ref: dict) -> str:
    """What the ledger's export step leaves for a ref: the captured bytes at `evidence/<hash><suffix>`."""
    target = task / RF._export_path(ref)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes((task / ref["path"]).read_bytes())
    return target.relative_to(task).as_posix()


def manual_row(case: str, ob: str, result: str, actual: str, refs: list, before=None, **over) -> dict:
    row = {"schema_version": 2, "case": case, "case_version": "cv_" + case, "obligation_ids": [ob],
           "current_obligation_ids": [ob], "attempt_id": "a1", "dispatch_id": "S6-qa-runner-1", "expected": [THENS[case]],
           "actual": actual, "result": result, "evidence_policy": "ui", "limitations": [], "evidence_refs": refs,
           "evidence_validated": True}
    if before is not None:
        row["before_change"] = before
    row.update(over)
    return row


def k4_rows(task: Path) -> tuple:
    """TC-001 passed (before: a claim, a pre and a post image and a DOM text), TC-002 inconclusive (nothing recorded
    about its before, one pre image and a limitation); every file is exported as the ledger would leave it."""
    pre1 = evidence(task, "TC-001", "a1", "001-pre", "pre_action")
    post1 = evidence(task, "TC-001", "a1", "002-post", "post_action", proves=["completion"])
    dom1 = evidence(task, "TC-001", "a1", "003-dom", "supporting", kind="log", payload=b"dom text", ext=".txt")
    pre2 = evidence(task, "TC-002", "a1", "001-pre", "pre_action")
    for ref in (pre1, post1, dom1, pre2):
        export_ref(task, ref)
    rows = [manual_row("TC-001", "OB-1", "pass", "The subscription read cancelled after the click", [pre1, post1, dom1], CLAIM),
            manual_row("TC-002", "OB-2", "inconclusive", "The paid period could not be reached on this stand", [pre2],
                       NOT_RECORDED, limitations=["the stand had no paid plan"])]
    return rows, {"pre1": pre1, "post1": post1, "dom1": dom1, "pre2": pre2}


def manual_story(rows=None, raw=None, with_rows: bool = True) -> Path:
    """A story whose plan has three `manual-agent` rows (TS-1..TS-3, obligations OB-1..OB-3 in work/test-plan.json) and
    one automated row (TS-4, the only green test). `rows` are the reducer's `current_manual_checks`; `raw` the
    `manual_checks` it keeps as written (default: the same rows)."""
    task = story(with_bug=False)
    work = task / "work"
    write(task / "test-plan.md", (MC_FIXTURES / "test-plan.md").read_text(encoding="utf-8"))
    write(work / "test-plan.json", (MC_FIXTURES / "test-plan.json").read_text(encoding="utf-8"))
    for old in (work / "test-cases" / "billing").glob("*.md"):
        old.unlink()
    for cid, req, ts in HAND_CASES:
        write(work / "test-cases" / "billing" / f"{cid}.md", hand_case(cid, req, ts))
    write(work / "automation-manifest.json", {"tests": [dict(MANIFEST["tests"][0], case="TC-004", covers=["TC-004"])]})
    if with_rows:
        rows = rows if rows is not None else k4_rows(task)[0]
        write(work / "run-report.json", dict(RUN_REPORT, current_manual_checks=rows,
                                             manual_checks=raw if raw is not None else rows))
    return task


def block_of(task: Path) -> str:
    return render_all(task)["manual-checks"]


def case_line(body: str, case: str) -> str:
    return next((ln for ln in body.splitlines() if ln.startswith(f"- **{case}**")), "")


def manual_checks_k4() -> None:
    """K4 (t-250): two records (pass, inconclusive) and one manual row without a record -> `Checked by hand - 2 of 3`;
    the third reads "not checked", and no one of the three stands under Proven (the one green test, TC-004, does)."""
    task = manual_story()
    try:
        facts = RF.build(task)
        blocks = RF.render(facts)
        body = blocks["manual-checks"]
        check_eq("the block is a block of the report, right after `proven`",
                 list(G.REPORT_BLOCKS)[list(G.REPORT_BLOCKS).index("proven") + 1], "manual-checks")
        check_eq("its heading is the grammar's own", G.REPORT_BLOCK_HEADINGS["manual-checks"], "## Checked by hand")
        check_in("K4: n of m - two valid records of three manual-agent cases", "## Checked by hand — 2 of 3\n", body)
        lines = [ln for ln in body.splitlines() if ln.startswith("- ")]
        check_eq("one line per manual-agent case, in plan-row order",
                 [ln.split("**")[1] for ln in lines], ["TC-001", "TC-002", "TC-003"])
        check_eq("the automated case has no line (it is not a manual-agent case)", "TC-004" in body, False)
        pre1, post1, dom1, pre2 = (RF._export_path(r) for r in k4_rows(task)[1].values())
        passed = case_line(body, "TC-001")
        check_in("the Then, quoted", '"The subscription reads cancelled."', passed)
        check_in("before the change: the claim's value and where it comes from", "before the change: active · base:b9c0c4e:settings.py:41", passed)
        check_not_in("F10: no bare `before:` beside `before the action:` (two different things, one word)", " — before: ", passed)
        check_in("now: the runner's words, no link", "now: The subscription read cancelled after the click — result", passed)
        check_in("the result word", "result: passed", passed)
        check_in("t-420: the pictures are exported, so the line says provided", f" — {RF.SHOTS_PROVIDED}", passed)
        for path in (pre1, post1, "evidence/"):
            check_not_in("t-420: no link or path of a screenshot in the report line (the owner's word 31.10.2026)", path, passed)
        check_not_in("t-420: ... nor the phase words that named the links", "before the action", passed)
        check_not_in("HF8-20: a text capture is never named by its path to a person", dom1, passed)
        check_not_in("HF8-20: ... nor the phase that held only that capture", "also captured", passed)
        check_in("the requirement", "(R-1)", passed)
        inconclusive = case_line(body, "TC-002")
        check_in("an inconclusive record is counted in n and says so", "result: inconclusive (it counts toward nothing)", inconclusive)
        check_in("its before is not recorded - in the requirements' words", "before the change: not recorded by the requirements", inconclusive)
        check_in("and with no capture after the action it says that, not a link", "no capture was taken after the action", inconclusive)
        check_in("its one picture is exported: provided, with no path", f" — {RF.SHOTS_PROVIDED}", inconclusive)
        check_not_in("t-420: ... and no path", pre2, inconclusive)
        third = case_line(body, "TC-003")
        check_in("the third reads not checked", "not checked: no record was written", third)
        check_in("with its Then, quoted", '"Old invoices stay readable."', third)
        for cid in ("TC-001", "TC-002", "TC-003"):
            check_not_in(f"{cid} never stands under Proven", cid, blocks["proven"])
        check_in("CONTROL: the green test's own case does (the check is not vacuous)", "TC-004", blocks["proven"])
        check_not_in("`not_recorded` is never read as `unchanged`", "unchanged", body)
        check_not_in("no path under work/ reaches the person", "work/", body)
        check_not_in("no field name of ours does (FR-6)", "pre_action", body)
        check_eq("the gate B text is this block, whole (FR-10: one renderer)", RF.manual_checks_text(task), body)
        check_eq("two renders are the same bytes", RF.manual_checks_text(task), RF.manual_checks_text(task))
        check_eq("the facts carry the counts", (facts["manual"]["checked"], facts["manual"]["total"]), (2, 3))
        before_tree = tree_hash(task.parents[2])
        RF.manual_checks_text(task)
        RF.build(task)
        check_eq("rendering the block writes nothing: not an export, not a request file (FR-45)", tree_hash(task.parents[2]), before_tree)
        print("K4 | records: TC-001 pass, TC-002 inconclusive; TC-003 no record -> '## Checked by hand — 2 of 3'; "
              "TC-003: '" + third.split(" — ", 2)[-1] + "'; TC-001..TC-003 in Proven: "
              + str([c for c in ("TC-001", "TC-002", "TC-003") if c in blocks["proven"]]))
        print("K4 block:\n" + body)
    finally:
        cleanup(task.parents[2])


def manual_record_in_the_traceability_table() -> None:
    """t-271 D5 (t-263): a VALID manual-agent record is read by the traceability table the way the "Checked by hand" block reads
    it - a passed one `pass` (so its R counts proven), an inconclusive one `wait`, no record `not run`. The two readers cannot
    disagree (FR-10): the table asks `report_facts._manual` itself."""
    task = manual_story()
    try:
        qa = task.parents[1]
        rows = {r["case"]: r for r in T.build(qa, task)["rows"] if r["case"] in ("TC-001", "TC-002", "TC-003")}
        check_eq("D5: TC-001 (a valid record, result pass) reads `pass`", rows["TC-001"]["result"], "pass")
        check_eq("D5: ... with the runner's words as its basis, no capture path (t-420)", rows["TC-001"]["basis"],
                 "checked by hand: The subscription read cancelled after the click")
        check_eq("D5: ... and no work/ path reaches the person", "work/" in rows["TC-001"]["basis"], False)
        check_eq("D5: TC-002 (inconclusive) reads `wait`", rows["TC-002"]["result"], "wait")
        check_in("D5: ... saying what the runner said", "checked by hand, inconclusive: The paid period could not be reached on this stand", rows["TC-002"]["basis"])
        check_eq("D5: TC-003 (no record) reads `not run`, as before", rows["TC-003"]["result"], "not run")
        facts = RF.build(task)
        classes = {i["id"]: i["class"] for i in facts["requirements"]["items"]}
        check_eq("D5: the R of the passed manual case counts proven (the report block and the appendix agree, FR-10)",
                 (classes["R-1"], classes["R-2"], classes["R-3"]), ("proven", "wait", "unproven"))
        check_in("D5: ... and the block counts the same case: `result: passed`", "result: passed", case_line(RF.render(facts)["manual-checks"], "TC-001"))
        print("K-D5 | TC-001 valid pass -> 'pass' basis 'checked by hand: <the runner's words>', R-1 proven; TC-002 inconclusive -> wait; TC-003 none -> not run")
    finally:
        cleanup(task.parents[2])
    # a record the block does not count is not a pass here either; a failed one is never a pass
    for label, make in (("evidence not validated", lambda t: manual_row("TC-001", "OB-1", "pass", "x", k4_rows(t)[0][0]["evidence_refs"], evidence_validated=False)),
                        ("a failed check", lambda t: manual_row("TC-001", "OB-1", "fail", "x", k4_rows(t)[0][0]["evidence_refs"])),
                        ("a record the reducer marked stale", lambda t: manual_row("TC-001", "OB-1", "pass", "x", k4_rows(t)[0][0]["evidence_refs"],
                                                                                   current_reason="invalidated_evidence"))):
        task = manual_story(with_rows=False)
        try:
            write(task / "work" / "run-report.json", dict(RUN_REPORT, current_manual_checks=[make(task)], manual_checks=[make(task)]))
            row = next(r for r in T.build(task.parents[1], task)["rows"] if r["case"] == "TC-001")
            check(f"D5 control: {label}: never `pass`", row["result"] != "pass", row["result"])
        finally:
            cleanup(task.parents[2])


def manual_checks_edges() -> None:
    """The edges the spec names: the empty plan, the missing sources, the refusal's text, a record the validator
    refused (C12), a record nobody can read, a case with no obligation, the legacy shapes."""
    # (1) m = 0: the heading is still there
    task = story()
    try:
        body = block_of(task)
        check_in("m = 0: the heading reads 0 of 0", "## Checked by hand — 0 of 0\n", body)
        check_in("and one line says no case was planned", "no case was planned for a manual check", body)
        check_not_in("a manual-HUMAN row is not a manual-agent case", "TC-002", body)
    finally:
        cleanup(task.parents[2])

    # (4) never raises: the sources that are missing say what is missing
    root = temp_dir("qa-manual-missing-")
    try:
        nothing = root / "qa-factory" / "artifacts" / "T-9"
        check_in("a story folder that does not exist: 0 of 0 and the line naming it",
                 "the story folder T-9 was not found", RF.manual_checks_text(nothing))
        nothing.mkdir(parents=True)
        text = RF.manual_checks_text(nothing)
        check_in("a story with no plan: 0 of 0", "## Checked by hand — 0 of 0", text)
        check_in("and the line names the plan", "the plan (test-plan.md) was not found", text)
        check_eq("a task root that is not a path at all does not raise", RF.manual_checks_text("").startswith("## Checked by hand"), True)
        check_eq("nor a number", RF.manual_checks_text(7).startswith("## Checked by hand"), True)
    finally:
        cleanup(root)

    task = manual_story(with_rows=False)
    try:
        body = block_of(task)
        check_in("no run report at all: every case is listed, 0 of 3", "## Checked by hand — 0 of 3", body)
        check_eq("each says no record was written", body.count("not checked: no record was written"), 3)
        write(task / "work" / "run-report.json", "{ not json")
        body = block_of(task)
        check_in("a run report nobody can read is said in words, with no file named (HF8-20)", "not checked: the run's results cannot be read", body)
        check_in("and the cases are still counted", "0 of 3", body)
    finally:
        cleanup(task.parents[2])

    # the plan has manual rows, no case was written for them: not "no case was planned"
    task = manual_story(with_rows=False)
    try:
        for old in (task / "work" / "test-cases" / "billing").glob("*.md"):
            old.unlink()
        body = block_of(task)
        check_in("manual rows with no case written for them say so", "the plan's manual rows (TS-1, TS-2, TS-3) have no case written for them", body)
        check_not_in("and never claim nothing was planned", "no case was planned", body)
    finally:
        cleanup(task.parents[2])

    # (3a) the refusal's text: reason and door, and the case joins "Left with you" (Decision 9)
    task = manual_story()
    try:
        before = RF.build(task)
        check_not_in("CONTROL: before any refusal TC-003 is not among the cases a person must check", "TC-003", " ".join(before["cases"]["to_check"]))
        refused = MC_FIXTURES / "request-refused.json"
        write(task / "work" / "evidence" / "manual" / "TC-003" / "request.json", refused.read_text(encoding="utf-8"))
        facts = RF.build(task)
        line = case_line(RF.render(facts)["manual-checks"], "TC-003")
        want = json.loads(refused.read_text(encoding="utf-8"))["refused"]
        check_in("(a) the refusal's reason, verbatim", want["reason"], line)
        check_in("and its door, verbatim", want["door"], line)
        check_in("under `not checked`", "not checked: expectation unconfirmed", line)
        check_in("the case is also left with the person (Decision 9)", "TC-003", " ".join(facts["cases"]["to_check"]))
        entry = next(c for c in facts["manual"]["cases"] if c["case"] == "TC-003")
        check_eq("the refused flag is the fact", (entry["refused"], entry["state"]), (True, "not_checked"))
        check_eq("its Left with you line: what to check, and where the way out is - not the block's wording",
                 entry["left_line"], 'To check: Old invoices stay readable. Needed: the way out named under "Checked by hand" for this case')
        check_not_in("one line, no duplication of the block's wording", want["reason"], entry["left_line"])
        # t-271 D5: TC-002's inconclusive record now reads `wait` in the traceability table (it was `not run`), so
        # it was already among the cases a person must check before the refusal: 1 before, 2 with TC-003.
        check_in("the verdict counts it among the cases a person must check (1 before: the inconclusive TC-002)", "A person must check 2 cases;", RF.render(facts)["verdict"])
        check_in("CONTROL: before the refusal the same sentence said 1", "A person must check 1 case;", RF.render(before)["verdict"])
        check_eq("a case NOT refused (no record) is not left with the person by this rule",
                 [c["case"] for c in facts["manual"]["cases"] if c["refused"]], ["TC-003"])
        check_in("heading unchanged by the refusal: it was never counted in n", "2 of 3", RF.render(facts)["manual-checks"])
        # a refusal file that is not an object, or has no `refused`, is no refusal
        write(task / "work" / "evidence" / "manual" / "TC-003" / "request.json", "[]")
        check_in("a request.json that is not an object: the plain reason", "not checked: no record was written", block_of(task))
        write(task / "work" / "evidence" / "manual" / "TC-003" / "request.json", {"schema_version": 2, "case": "TC-003"})
        check_in("a request with no `refused`: the plain reason", "not checked: no record was written", block_of(task))
    finally:
        cleanup(task.parents[2])

    # (3b) C12: the reducer downgraded a runner "pass" because its evidence is invalid
    task = manual_story()
    try:
        raw = json.loads((task / "work" / "run-report.json").read_text(encoding="utf-8"))["manual_checks"]
        rows = json.loads(json.dumps(raw))
        rows[0].update(result="inconclusive", evidence_validated=False,
                       evidence_errors=["evidence hash mismatch", "evidence proves must be a nonempty array"])
        write(task / "work" / "run-report.json", dict(RUN_REPORT, current_manual_checks=rows, manual_checks=raw))
        body = block_of(task)
        line = case_line(body, "TC-001")
        check_in("C12: the downgrade reads runner said pass; evidence invalid: <its first error>",
                 "not checked: runner said pass; evidence invalid: evidence hash mismatch", line)
        check_in("the invalid record is not counted in n", "## Checked by hand — 1 of 3", body)
        check_not_in("and says nothing about a link or a result", "result:", line)
        check_not_in("it is not under Proven either", "TC-001", RF.render(RF.build(task))["proven"])
        raw_fail = json.loads(json.dumps(raw))
        raw_fail[0]["result"] = "fail"
        write(task / "work" / "run-report.json", dict(RUN_REPORT, current_manual_checks=rows, manual_checks=raw_fail))
        check_in("a runner `fail` is told as fail (FR-35: each verdict keeps its word)",
                 "runner said fail; evidence invalid: evidence hash mismatch", block_of(task))
        write(task / "work" / "run-report.json", dict(RUN_REPORT, current_manual_checks=rows, manual_checks=[]))
        check_in("the runner's word is not in the raw rows: only the reason is told",
                 "not checked: evidence invalid: evidence hash mismatch", block_of(task))
        rows[0]["evidence_errors"] = []
        write(task / "work" / "run-report.json", dict(RUN_REPORT, current_manual_checks=rows, manual_checks=raw))
        check_in("no error recorded: says so", "evidence invalid: no reason was recorded", block_of(task))
    finally:
        cleanup(task.parents[2])

    # a record the reducer marked stale, a legacy row, and a row not validated at all: never counted
    task = manual_story()
    try:
        raw = json.loads((task / "work" / "run-report.json").read_text(encoding="utf-8"))["manual_checks"]
        for label, change, words in (
                ("stale", {"current_reason": "invalidated_evidence", "result": "inconclusive"}, "no longer stands"),
                ("unorderable", {"current_reason": "ambiguous_attempt_order", "result": "inconclusive"}, "order of its attempts cannot be told"),
                ("older form", {"schema_version": 1, "evidence_validated": None}, "older form")):
            rows = json.loads(json.dumps(raw))
            rows[0].update(change)
            write(task / "work" / "run-report.json", dict(RUN_REPORT, current_manual_checks=rows, manual_checks=raw))
            body = block_of(task)
            check_in(f"{label}: not counted", "1 of 3", body)
            check_in(f"{label}: and told", words, case_line(body, "TC-001"))
    finally:
        cleanup(task.parents[2])

    # HF8-20 (F-3): a record that carries `then_quotes` and `rejudge_of` reaches the block through `_manual`, whole
    task = manual_story()
    try:
        raw = json.loads((task / "work" / "run-report.json").read_text(encoding="utf-8"))["manual_checks"]
        rows = json.loads(json.dumps(raw))
        rows[0].update(then_quotes=[{"then": 1, "quote": "Status: cancelled", "kind": "text"}],
                       rejudge_of="a9", rejudge_reason="the first read missed the banner")
        write(task / "work" / "run-report.json", dict(RUN_REPORT, current_manual_checks=rows, manual_checks=raw))
        line = case_line(block_of(task), "TC-001")
        check_in("a record with a quote: the block prints what the captured page says", "the captured page says: Status: cancelled", line)
        check_in("... and says it was re-judged from the earlier captures, in words",
                 "re-judged from the captures taken earlier, the check was not run again: the first read missed the banner", line)
        check_not_in("... with no attempt id", "a9", line)
    finally:
        cleanup(task.parents[2])

    # (3b/4) a record file nobody can read: counted as not checked, named by attempt (no work/ path)
    task = manual_story()
    try:
        raw = json.loads((task / "work" / "run-report.json").read_text(encoding="utf-8"))["manual_checks"]
        write(task / "work" / "run-report.json", dict(RUN_REPORT, current_manual_checks=raw[:1], manual_checks=raw[:1]))
        folder = task / "work" / "evidence" / "manual" / "TC-002" / "a1"
        folder.mkdir(parents=True, exist_ok=True)
        write(folder / "record.json", "{ torn")
        body = block_of(task)
        check_in("a malformed record: not checked, said in words with no attempt id (HF8-20)", "not checked: the record of the check cannot be read", case_line(body, "TC-002"))
        check_in("and not counted", "1 of 3", body)
        check_not_in("and no path under work/ is shown", "work/", body)
        write(folder / "record.json", {"schema_version": 2, "case": "TC-002"})
        check_in("a record that reads but the reducer never saw: said, not counted",
                 "its record was written, but the run has not been finalized since", case_line(block_of(task), "TC-002"))
        check_in("still not counted", "1 of 3", block_of(task))
        folder2 = task / "work" / "evidence" / "manual" / "TC-003" / "a2"
        folder2.mkdir(parents=True, exist_ok=True)
        write(folder2 / "record.json", [1, 2])
        check_in("a record that is JSON but not an object is unreadable too, said in words (HF8-20)",
                 "not checked: the record of the check cannot be read", case_line(block_of(task), "TC-003"))
    finally:
        cleanup(task.parents[2])

    # (9) a manual-agent case missing from the obligations mapping: "no obligation", never counted in n - error direction
    task = manual_story()
    try:
        plan = json.loads((MC_FIXTURES / "test-plan.json").read_text(encoding="utf-8"))
        plan["rows"][1]["coverage_obligations"] = []   # TS-2 has a valid record but the plan holds no obligation for it
        write(task / "work" / "test-plan.json", plan)
        body = block_of(task)
        check_in("(9) no obligation: told", "not checked: no obligation", case_line(body, "TC-002"))
        check_in("(9) and never counted, whatever the record says", "## Checked by hand — 1 of 3", body)
        check_not_in("(9) its result is not shown as if it were checked", "result:", case_line(body, "TC-002"))
        write(task / "work" / "test-plan.json", "{ torn")
        body = block_of(task)
        check_in("an unreadable obligations file: no case is counted, and the line says why",
                 "no obligation (the plan's obligations could not be read", case_line(body, "TC-001"))
        check_in("0 of 3", "0 of 3", body)
        (task / "work" / "test-plan.json").unlink()
        check_in("no obligations file at all: nothing can be bound, nothing is counted", "0 of 3", block_of(task))
    finally:
        cleanup(task.parents[2])

    # (2) `not_recorded` never renders a value; a claim row with a missing ref is not a claim; legacy phases read through
    task = manual_story()
    try:
        raw = json.loads((task / "work" / "run-report.json").read_text(encoding="utf-8"))["manual_checks"]
        rows = json.loads(json.dumps(raw))
        rows[0]["before_change"] = {"r": "R-1", "value": "ACTIVE-FROM-THE-DIFF", "ref": "diff:x:1", "source": "not_recorded"}
        write(task / "work" / "run-report.json", dict(RUN_REPORT, current_manual_checks=rows, manual_checks=rows))
        line = case_line(block_of(task), "TC-001")
        check_in("`not_recorded` renders as not recorded", "before the change: not recorded by the requirements", line)
        check_not_in("and NEVER as the value it carries (the diff is not an oracle, P20)", "ACTIVE-FROM-THE-DIFF", line)
        rows[0]["before_change"] = {"r": "R-1", "value": "active", "ref": "", "source": "claim"}
        write(task / "work" / "run-report.json", dict(RUN_REPORT, current_manual_checks=rows, manual_checks=rows))
        check_in("a claim with no ref is not a claim", "before the change: not recorded by the requirements", case_line(block_of(task), "TC-001"))
        rows[0]["before_change"] = {"r": "R-1", "value": "absent", "ref": "absent", "source": "claim"}
        write(task / "work" / "run-report.json", dict(RUN_REPORT, current_manual_checks=rows, manual_checks=rows))
        check_in("an `absent` before is its own reference: said once", "before the change: absent —", case_line(block_of(task), "TC-001"))
        del rows[0]["before_change"]
        write(task / "work" / "run-report.json", dict(RUN_REPORT, current_manual_checks=rows, manual_checks=rows))
        check_in("a record from before `before_change` existed: not recorded, not unchanged", "before the change: not recorded by the requirements", case_line(block_of(task), "TC-001"))
        for ref, phase in zip(rows[0]["evidence_refs"], ("before", "after", "supporting")):
            ref["phase"] = phase
        write(task / "work" / "run-report.json", dict(RUN_REPORT, current_manual_checks=rows, manual_checks=rows))
        line = case_line(block_of(task), "TC-001")
        pre1, post1, dom1 = (RF._export_path(r) for r in rows[0]["evidence_refs"])
        check_in("a legacy record (before / after) reads through the aliases: a post picture is found (the words are the runner's alone)",
                 "now: The subscription read cancelled after the click — result", line)
        check_not_in("and no phase word or path is printed", "the action", line.replace("after the click", ""))
        check_not_in("HF8-20: and a text capture is not named", dom1, line)
        check_not_in("... nor a picture", post1, line)
        rows[0]["evidence_refs"][0]["phase"] = "somewhere-else"
        write(task / "work" / "run-report.json", dict(RUN_REPORT, current_manual_checks=rows, manual_checks=rows))
        check_in("a phase nobody knows is still a provided picture", RF.SHOTS_PROVIDED, case_line(block_of(task), "TC-001"))
    finally:
        cleanup(task.parents[2])

    # links: a file the ledger has not exported yet is said so; a ref with no hash gives no link
    task = manual_story(with_rows=False)
    try:
        pre = evidence(task, "TC-001", "a1", "001-pre", "pre_action")
        post = evidence(task, "TC-001", "a1", "002-post", "post_action", proves=["completion"])
        rows = [manual_row("TC-001", "OB-1", "pass", "it read cancelled", [pre, dict(post, content_hash="short")], CLAIM)]
        write(task / "work" / "run-report.json", dict(RUN_REPORT, current_manual_checks=rows, manual_checks=rows))
        line = case_line(block_of(task), "TC-001")
        check_in("a picture not exported yet: not provided, said so, no path (t-420)", RF.SHOTS_NO_COPY, line)
        check_not_in("... and the path is not printed", RF._export_path(pre), line)
        export_ref(task, pre)
        line = case_line(block_of(task), "TC-001")
        check_in("t-423 F5: a picture whose hash is unusable is TAKEN with no copy: not provided, never 'none were taken'",
                 RF.SHOTS_NO_COPY, line)
        check_not_in("t-423 F5: ... although the exported one stands on disk", RF.SHOTS_NONE, line)
        check_not_in("t-423 F5: ... and 'no capture after the action' is not said about a post picture that was taken",
                     "no capture was taken after the action", line)
        check_not_in("t-423 F4: the words 'not exported yet' (untrue where nothing will follow) are gone", "not exported yet", line)
        post["content_hash"] = hashlib.sha256((task / post["path"]).read_bytes()).hexdigest()
        rows[0]["evidence_refs"][1] = post
        write(task / "work" / "run-report.json", dict(RUN_REPORT, current_manual_checks=rows, manual_checks=rows))
        export_ref(task, post)
        check_in("once exported it reads provided", RF.SHOTS_PROVIDED, block_of(task))
        check_not_in("... and the no-copy note goes", "no copy on this machine", block_of(task))
        chat = RF.screenshots_chat_text(task)
        check_in("t-420: the chat text names the exported file's absolute path", str(task.resolve() / RF._export_path(pre)), chat)
        check_in("... under its case", "- TC-001 (", chat)
        import contextlib, io
        said = io.StringIO()
        with contextlib.redirect_stdout(said):
            code = RF.main(["--task-root", str(task), "--screenshots"])
        check_eq("t-420: `--screenshots` prints that same text and exits 0", (code, said.getvalue().strip()), (0, chat.strip()))
        check_not_in("... and the same path is not in the report block", str(task.resolve()), block_of(task))
        check_not_in("... nor in the written report: the hash path is never in `test-report.md` blocks", RF._export_path(pre), "".join(RF.render(RF.build(task)).values()))
    finally:
        cleanup(task.parents[2])

    # t-420: a case with no picture by design (an API check) and the chat line when nothing is provided
    task = manual_story(with_rows=False)
    try:
        state = evidence(task, "TC-001", "a1", "001-state", "post_action", kind="state", payload=b"{}", ext=".json", proves=["completion"])
        export_ref(task, state)
        rows = [manual_row("TC-001", "OB-1", "pass", "the API said cancelled", [state], CLAIM)]
        write(task / "work" / "run-report.json", dict(RUN_REPORT, current_manual_checks=rows, manual_checks=rows))
        line = case_line(block_of(task), "TC-001")
        check_in("t-420: no picture by design: `not provided` with its reason, and the verdict is untouched", RF.SHOTS_NONE, line)
        check_in("... the verdict word is the runner's", "result: passed", line)
        check_not_in("... never a debt word", "missing", line)
        check_eq("t-420: no screenshot at all: one sentence in chat", RF.screenshots_chat_text(task), "No screenshots were provided for the manual checks.")
        check_eq("t-420: a task root that is no folder does not raise", isinstance(RF.screenshots_chat_text(task / "nowhere"), str), True)
        check_eq("... nor a value that is no path", isinstance(RF.screenshots_chat_text(None), str), True)
    finally:
        cleanup(task.parents[2])

    # t-423 F5: a case's SECOND record is read too (the chat text and the words both come from every record), and the words after
    # a clean checkout (nothing on disk) are the same as after a refused export: no copy on this machine - never 'yet'
    task = manual_story(with_rows=False)
    try:
        first = evidence(task, "TC-001", "a1", "001-pre", "pre_action")
        second = evidence(task, "TC-001", "a2", "001-pre", "pre_action")
        export_ref(task, first)
        rows = [manual_row("TC-001", "OB-1", "pass", "it read cancelled", [first], CLAIM),
                manual_row("TC-001", "OB-1", "pass", "it read cancelled again", [second], CLAIM, attempt_id="a2")]
        write(task / "work" / "run-report.json", dict(RUN_REPORT, current_manual_checks=rows, manual_checks=rows))
        line = case_line(block_of(task), "TC-001")
        check_in("t-423 F5: the second record's picture has no copy: the line is not 'provided'", RF.SHOTS_NO_COPY, line)
        check_not_in("t-423 F5: ... though the first record's is exported", RF.SHOTS_PROVIDED, line)
        check_eq("t-423 F5: ... and the list holds the one copy there is", RF.screenshot_groups(task)[0][1], [str(task.resolve() / RF._export_path(first))])
        export_ref(task, second)
        check_in("t-423 F5: both exported: provided", RF.SHOTS_PROVIDED, case_line(block_of(task), "TC-001"))
        check_eq("t-423 F5: ... and the list holds both, the first record's first",
                 RF.screenshot_groups(task)[0][1], [str(task.resolve() / RF._export_path(r)) for r in (first, second)])
        import shutil
        shutil.rmtree(task / "evidence")
        line = case_line(block_of(task), "TC-001")
        check_in("t-423 F4: a clean checkout (no copy on disk): the words promise nothing", RF.SHOTS_NO_COPY, line)
        check_eq("t-423 F4: ... and the gate B section is absent, so nothing is promised there either", RF.screenshot_section(task), [])
    finally:
        cleanup(task.parents[2])

    # (4) the renderer failing is unknown (FR-41), never a raise and never "nothing was checked"
    task = manual_story()
    saved = RF._manual
    try:
        def boom(*_a, **_k):
            raise RuntimeError("the plan reader broke")
        RF._manual = boom
        text = RF.manual_checks_text(task)
        check_in("a renderer that fails: the heading says unknown", "## Checked by hand — unknown", text)
        check_in("and says why", "the plan reader broke", text)
        facts = RF.build(task)
        check_eq("the facts carry no manual entry, and an unknown one", (facts["manual"], "manual" in facts["unknown"]), (None, True))
        check_in("the report's block says unknown", "## Checked by hand — unknown", RF.render(facts)["manual-checks"])
        check_eq("and a failure here does not take the other facts down", facts["verdict"]["ready"] is not None, True)
    finally:
        RF._manual = saved
        cleanup(task.parents[2])


def manual_checks_stand_blocked() -> None:
    """F3 (t-277, critic t-275): a case whose capture could not identify the stand (the runtime probe was unmatched or
    failed) left `env_blocked.json` in its attempt. The block said "no record was written" and lost the probe line and
    the remedy; it now says the stand could not be verified, with both, as the capture recorded them (FR-20, FR-41)."""
    blocked = {"id": "TC-003", "probe_line": "runtime probe of e2e-ui start read 'mismatched', not matched",
               "remedy": "bring the stand up on the build under test, then capture again", "owner": "user"}
    want = "not checked: the stand could not be verified — " + blocked["probe_line"] + "; " + blocked["remedy"]
    task = manual_story()
    try:
        base = task / "work" / "evidence" / "manual" / "TC-003"
        write(base / "a1" / "env_blocked.json", blocked)
        body = block_of(task)
        line = case_line(body, "TC-003")
        check_in("F3: an env_blocked attempt reads: the stand could not be verified, the probe line, the remedy", want, line)
        check_not_in("F3: and no longer 'no record was written'", "no record was written", line)
        check_in("F3: it is still not counted (n stays 2 of 3)", "## Checked by hand — 2 of 3", body)
        check_not_in("F3: nor does the field name or a path reach the person (FR-6)", "env_blocked", line)
        check_not_in("F3: no path under work/ either", "work/", line)
        print("F3 rendered line: " + line)
        # a case WITH a valid record is not touched by a blocked attempt of its own (the record wins)
        write(task / "work" / "evidence" / "manual" / "TC-001" / "a2" / "env_blocked.json", dict(blocked, id="TC-001"))
        check_in("F3: a case with a valid current record stays checked", "result: passed", case_line(block_of(task), "TC-001"))
        # precedence 1: a refused request.json comes first
        refused = json.loads((MC_FIXTURES / "request-refused.json").read_text(encoding="utf-8"))["refused"]
        write(base / "request.json", (MC_FIXTURES / "request-refused.json").read_text(encoding="utf-8"))
        line = case_line(block_of(task), "TC-003")
        check_in("F3 precedence: a refused prepare is told first", refused["reason"], line)
        check_not_in("F3 precedence: ... not the stand", "the stand could not be verified", line)
        (base / "request.json").unlink()
        # precedence 2: the blocked stand comes before an unreadable record in the same attempt
        write(base / "a1" / "record.json", "{ torn")
        check_in("F3 precedence: env_blocked before an unreadable record", want, case_line(block_of(task), "TC-003"))
        (base / "a1" / "record.json").unlink()
        # precedence 3: the LATEST attempt decides - a newer attempt with nothing in it reads plain
        (base / "a2").mkdir()
        check_in("F3: a newer open attempt (nothing captured yet) reads 'no record was written'",
                 "not checked: no record was written", case_line(block_of(task), "TC-003"))
        write(base / "a2" / "env_blocked.json", dict(blocked, probe_line="runtime probe of e2e-ui end read 'unknown', not matched"))
        check_in("F3: a newer blocked attempt says its own probe line",
                 "runtime probe of e2e-ui end read 'unknown', not matched; " + blocked["remedy"], case_line(block_of(task), "TC-003"))
        # a file that cannot be read is named by its attempt; one with no words says so, never an empty clause
        write(base / "a2" / "env_blocked.json", "{ torn")
        check_in("F3: an unreadable stand-check record is said in words, with no file or attempt id (HF8-20)",
                 "not checked: the record of the stand check cannot be read", case_line(block_of(task), "TC-003"))
        write(base / "a2" / "env_blocked.json", {"id": "TC-003"})
        check_in("F3: a blocked attempt that recorded no words says so (FR-41: nothing is made up)",
                 "not checked: the stand could not be verified — no probe line was recorded", case_line(block_of(task), "TC-003"))
        check_not_in("F3: ... and ends with no dangling semicolon", ";", case_line(block_of(task), "TC-003").split("no probe line was recorded", 1)[1])
        write(base / "a2" / "env_blocked.json", [1])
        check_in("F3: a JSON that is not an object is unreadable too",
                 "the record of the stand check cannot be read", case_line(block_of(task), "TC-003"))
    finally:
        cleanup(task.parents[2])


def manual_export_path_is_what_the_code_writes() -> None:
    """FR-37: the link the block prints is the path `manual_evidence.export_records` writes - the report computes it
    (a report writes nothing), this pins the two to each other for every suffix rule."""
    import manual_evidence as ME
    task = manual_story(with_rows=False)
    saved = ME.validate_record
    try:
        ME.validate_record = lambda record, root, policy=None: []   # the record's own validity is not what is pinned
        refs = [evidence(task, "TC-001", "a1", "1", "pre_action"),
                evidence(task, "TC-001", "a1", "2", "post_action", kind="log", payload=b"log", ext=".LOG"),
                evidence(task, "TC-001", "a1", "3", "supporting", kind="other", payload=b"x", ext=".exe"),
                evidence(task, "TC-001", "a1", "4", "supporting", kind="log", payload=b"noext", ext="")]
        record = manual_row("TC-001", "OB-1", "pass", "x", refs, CLAIM)
        done = ME.export_records(task, [record])
        check_eq("the export wrote the row", [e for e in done["errors"]], [])
        written = [r["path"] for r in done["rows"][0]["evidence_refs"]]
        check_eq("the report's path is the exported path, for each suffix rule (.png, .LOG, an unsafe .exe, none)",
                 [RF._export_path(r) for r in refs], written)
        check_eq("the unsafe suffix became .bin and the upper-case one is folded", [Path(p).suffix for p in written], [".png", ".log", ".bin", ".bin"])
        check_eq("every one of them is a file under evidence/", all((task / p).is_file() and p.startswith("evidence/") for p in written), True)
    finally:
        ME.validate_record = saved
        cleanup(task.parents[2])


def partly_proven_unconfirmed_then() -> None:
    """t-255's analog (t-250 B3): a requirement whose rows hold a `pass` and one Then nobody confirmed read "proven" -
    the verdict counted it with the proven ones. Now it is partly proven: out of the proven count, named in the verdict
    with the Then and its question; a requirement whose every Then passes still reads proven."""
    import question_register as QR
    task = story(with_bug=False)
    try:
        two = CASE.replace("1. The subscription reads cancelled.",
                           "1. The subscription reads cancelled.\n2. The card is not charged again.")
        write(task / "work" / "test-cases" / "billing" / "TC-001.md", two.format(cid="TC-001", title="Cancel", req="R-1", ts="TS-1"))
        bindings = [{"case": "TC-001", "then": 1, "instance_id": "test_a", "assertion_ref": "a", "status": "covered"},
                    {"case": "TC-001", "then": 2, "instance_id": "test_a", "assertion_ref": "b", "status": "covered"}]
        write(task / "work" / "automation-manifest.json", dict(MANIFEST, then_bindings=bindings))
        facts = RF.build(task)
        item = next(i for i in facts["requirements"]["items"] if i["id"] == "R-1")
        check_eq("CONTROL: every Then of R-1 passes - it reads proven", (item["class"], item["partly"]), ("proven", []))
        check_eq("CONTROL: and is counted among the proven", facts["requirements"]["counts"]["proven"], 1)
        check_in("CONTROL: the verdict says nothing about partly", "1 proven by tests", RF.render(facts)["verdict"])
        check_not_in("CONTROL: ... and no partly sentence", "partly proven", RF.render(facts)["verdict"])

        held = [bindings[0], {"case": "TC-001", "then": 2, "instance_id": None, "assertion_ref": None,
                              "status": "unresolved", "reason": "expectation_unconfirmed", "question": "Q1"}]
        write(task / "work" / "automation-manifest.json", dict(MANIFEST, then_bindings=held))
        facts = RF.build(task)
        item = next(i for i in facts["requirements"]["items"] if i["id"] == "R-1")
        check_in("the traceability row of the unconfirmed Then is `wait`, the other is `pass` (the premise)",
                 "pass", " ".join(item["results"]))
        check_in("...and `wait`", "wait", " ".join(item["results"]))
        check_eq("the requirement is NOT proven: it waits for the person", item["class"], "wait")
        check_eq("and says which Then waits for which question", item["partly"], ["Then 2 waits for Q1 (TC-001)"])
        check_eq("it stays out of the proven count", facts["requirements"]["counts"]["proven"], 0)
        verdict = RF.render(facts)["verdict"]
        check_in("the verdict reads partly proven, with the Then and the question",
                 "R-1 is partly proven — Then 2 waits for Q1 (TC-001).", verdict)
        check_in("and counts it with the ones waiting for a person, not the proven", "0 proven by tests", verdict)
        check_in("Not proven lists it, with the partly words in its cause", "- **R-1** — partly proven — Then 2 waits for Q1 (TC-001)", RF.render(facts)["not-proven"])
        check_eq("the item still has the shape --check wants (`**R-n** - cause : risk`)", all(
            ln.partition(" : ")[2].strip() for ln in RF.render(facts)["not-proven"].splitlines() if ln.startswith("- ")), True)
        # a red check outranks it (the class function, whatever a row says); no pass means it is just waiting
        check_eq("`_classify`: a bug outranks a held Then", RF._classify(["bug", "pass", "wait"], True), "bug")
        check_eq("`_classify`: a pass with a held Then waits", RF._classify(["pass"], True), "wait")
        check_eq("`_classify`: a pass with no held Then is proven (CONTROL)", RF._classify(["pass", "wait"], False), "proven")
        # HF2-5 (5a-K3, A1): a pass beside a deferred or a blocked row is not "proven by tests"
        check_eq("5a-K3 `_classify`: pass + deferred -> deferred", RF._classify(["pass", "deferred"]), "deferred")
        check_eq("5a-K3 `_classify`: pass + blocked -> wait", RF._classify(["pass", "blocked"]), "wait")
        check_eq("5a-K3 `_classify`: a bug is above a deferred and a blocked row",
                 (RF._classify(["bug", "pass", "deferred"]), RF._classify(["bug", "pass", "blocked"])), ("bug", "bug"))
        check_eq("5a-K3 `_classify`: a held Then and a deferred row: the worse one (wait) wins",
                 RF._classify(["pass", "deferred"], True), "wait")
        check_eq("5a-K3 `_classify`: blocked and deferred beside a pass: wait", RF._classify(["pass", "deferred", "blocked"]), "wait")
        check_eq("5a-K3 `_classify` CONTROL: a pass alone is proven; no pass keeps its worst word (unchanged)",
                 (RF._classify(["pass"]), RF._classify(["deferred"]), RF._classify(["blocked"]), RF._classify([])),
                 ("proven", "deferred", "unproven", "unproven"))
        write(task / "work" / "automation-manifest.json", {"tests": [], "then_bindings": [
            dict(held[1], then=1), dict(held[1], then=2)]})
        item = next(i for i in RF.build(task)["requirements"]["items"] if i["id"] == "R-1")
        check_eq("no pass at all: waiting, and NOT called partly proven (nothing is proven)", (item["class"], item["partly"]), ("wait", []))
        # answered since: the test was written before the answer
        write(task / "work" / "automation-manifest.json", dict(MANIFEST, then_bindings=held))
        view = {q["id"]: q for q in QR.load(task)["questions"]}["Q1"]
        QR.record(task, "Q1", "answered", "Q1: a", "gate A", "driver", view["row_hash"], reading="a")
        item = next(i for i in RF.build(task)["requirements"]["items"] if i["id"] == "R-1")
        check_eq("answered since: still not proven (it has not run against the answer), said so",
                 (item["class"], item["partly"]), ("wait", ["Then 2 has not run since Q1 was answered (TC-001)"]))
        # a binding that names no question
        write(task / "work" / "automation-manifest.json", dict(MANIFEST, then_bindings=[bindings[0], dict(held[1], question="")]))
        check_eq("no question named: it says nobody has raised one", next(i for i in RF.build(task)["requirements"]["items"] if i["id"] == "R-1")["partly"],
                 ["Then 2 waits for a question nobody has raised yet (TC-001)"])
        # --write and --check agree
        legacy_report(task)
        check_eq("the report writes", RF.write(task)["ok"], True)
        check_eq("and checks clean with the partly line in it", RF.check(task), [])
    finally:
        cleanup(task.parents[2])


# --- t-305 N8: the third verdict in the report -------------------------------------------------------------------

def _item(ref: str, kind: str = "manual_human", req=("R-2",), case=None, **more) -> dict:
    return dict({"kind": kind, "kinds": [kind], "ref": ref, "case": ref if case is None else case, "requirements": list(req),
                 "tests": [], "to_check": "", "how": "", "words": "", "source": "ledger", "counts": True}, **more)


def verdict_block_follows_the_ledger_word() -> None:
    """K-N8.8 (D9, F11): the report quotes the ledger's WORD and never recomputes it; its own facts only add a sentence."""
    gate = {"A": {"authorization_source": GATE_A}}
    # the ledger says yes while the report's own facts name unproven requirements: the head reads ready, plus the sentence
    task = story(pipeline={"ticket": "T-1", "gates": gate}, extra_ledger=dict(ledger(records=[]), delivery_ready=True,
                 delivery_verdict="yes"))
    try:
        legacy_report(task)
        RF.write(task)
        head = G.find_blocks((task / "test-report.md").read_text(encoding="utf-8"))["verdict"][2]
        check_in("K-N8.8 yes + candidates: the head reads ready", "**Verdict: ready to ship.**", head)
        check_in("K-N8.8 and the line is the ledger's", "`delivery_ready: yes`", head)
        check_in("K-N8.8 and one sentence says what the ledger does not hold (in words, HF8-20)",
                 "which the factory's record of the checks does not hold — the factory's own finding.", head)
        check_in("K-N8.8 naming the first candidate", "name BUG-1 is a confirmed product bug (R-1)", head)
        check_not_in("K-N8.8 the word is never changed by the report's facts", "Because", head)
    finally:
        cleanup(task.parents[2])
    # after_checks: the Q4 head and line with n; what the third verdict already means is no disagreement
    held = [_item("TC-002"), _item("R-4", "unconfirmed_expectation", req=("R-4",), case="")]
    task = story(pipeline={"ticket": "T-1", "gates": gate}, with_bug=False,
                 extra_ledger=dict(ledger(records=[]), delivery_ready=False, delivery_verdict="after_checks",
                                   left_items=held + [{"kind": "regression", "ref": "regression", "counts": False}]))
    try:
        legacy_report(task)
        RF.write(task)
        head = G.find_blocks((task / "test-report.md").read_text(encoding="utf-8"))["verdict"][2]
        check_in("K-N8.8 after_checks: the head", "**Verdict: ready once you finish the checks left with you.**", head)
        check_in("K-N8.8 and the line carries n (the regression row never counts)",
                 "`delivery_ready: after_checks — 2 items are left with you`", head)
        check_not_in("K-N8.8 what the ledger holds is no disagreement", "which the factory's record of the checks does not hold", head)
        check_eq("K-N8.8 --check passes", [p for p in RF.check(task) if "verdict" in p], [])
    finally:
        cleanup(task.parents[2])
    # NEG: a report that recomputed the word from its own facts would say `no` over this ledger; it must not
    task = story(pipeline={"ticket": "T-1", "gates": gate}, extra_ledger=dict(ledger(records=[]), delivery_ready=False,
                 delivery_verdict="after_checks", left_items=[_item("TC-002")]))
    try:
        legacy_report(task)
        RF.write(task)
        head = G.find_blocks((task / "test-report.md").read_text(encoding="utf-8"))["verdict"][2]
        check_in("K-N8.8 NEG: a confirmed bug in the report's facts does not turn the ledger's word", "ready once you finish", head)
        check_in("K-N8.8 NEG: it is named beside the word", "BUG-1 is a confirmed product bug", head)
    finally:
        cleanup(task.parents[2])
    # an inconsistent word is `unknown`, said as unknown (FR-41), never the other side's
    task = story(extra_ledger=dict(ledger(records=[]), delivery_ready=True, delivery_verdict="no"))
    try:
        legacy_report(task)
        RF.write(task)
        head = G.find_blocks((task / "test-report.md").read_text(encoding="utf-8"))["verdict"][2]
        check_in("K-N8.8 a word that disagrees with its bool reads unknown", "**Verdict: unknown.**", head)
    finally:
        cleanup(task.parents[2])


def the_one_predicate_loop() -> None:
    """K-N8.9 (F10, FR-57): what `--write` removes, `--check` never demands - ONE predicate, both ways."""
    words = "Gate B: draft MR.\n\nTC-002: run it yourself, I accept the risk."
    pipeline = {"ticket": "T-1", "gates": {"A": {"authorization_source": GATE_A}, "B": {"authorization_source": words}}}
    owed = {"rows": [{"ref": "TS-2", "kind": "plan_row", "state": "not_executed:handed_to_person", "detail": "TC-002: run it"}],
            "left_items": [_item("TC-002", "handed")], "delivery_ready": False, "delivery_verdict": "after_checks",
            "reasons": [], "reason_records": [], "blocked_by": [], "factory_findings": []}
    task = story(pipeline=pipeline, extra_ledger=owed)
    try:
        legacy_report(task)
        RF.write(task)
        path = task / "test-report.md"
        text = path.read_text(encoding="utf-8")
        check_in("K-N8.9 an open handed item named in gate B's words is KEPT", "Access after cancelling", text)
        check_in("K-N8.9 and their own line is quoted under it", 'Your words at gate B: "TC-002: run it yourself, I accept the risk."',
                 text)
        check_eq("K-N8.9 the quote is added once (idempotent)", text.count("Your words at gate B:"), 1)
        RF.write(task)
        check_eq("K-N8.9 a second --write changes nothing", path.read_text(encoding="utf-8"), text)
        check_eq("K-N8.9 --write then --check -> nothing about Left with you",
                 [p for p in RF.check(task) if "Left with you" in p], [])
        # the case is closed now: the same words remove the item, and --check does not demand it
        write(task / "work" / "ledger.json", dict(owed, rows=[dict(owed["rows"][0], state="passed_green")], left_items=[],
                                                  delivery_ready=True, delivery_verdict="yes"))
        RF.write(task)
        gone = path.read_text(encoding="utf-8")
        check_not_in("K-N8.9 a closed item is removed", "Access after cancelling", gone)
        check_eq("K-N8.9 and not demanded", [p for p in RF.check(task) if "Left with you" in p], [])
    finally:
        cleanup(task.parents[2])


def completeness_of_left_with_you() -> None:
    """K-N8.10 (F9): every check the ledger leaves with the person has an item the scribe wrote; AT and BEYOND the limit."""
    import shutil
    import check_delivery as CD
    source = Path(__file__).resolve().parent / "fixtures" / "after-checks"
    root = temp_dir("qa-report-complete-")
    task = root / "QA-1"
    try:
        shutil.copytree(source, task)
        CD.assess(task)
        res = RF.write(task)
        check("K-N8.10 setup: --write", res["ok"], str(res["lines"]))
        path = task / "test-report.md"
        full = path.read_text(encoding="utf-8")
        gaps = lambda: [p for p in RF.check(task) if "has no item for" in p]  # noqa: E731
        check_eq("K-N8.10 AT the limit: every item present -> []", gaps(), [])
        lines = full.splitlines(keepends=True)
        without = lambda needle: "".join(ln for ln in lines if needle not in ln)  # noqa: E731
        path.write_text(without("(R-4, TC-004)"), encoding="utf-8")
        found = gaps()
        check_eq("K-N8.10 BEYOND: one item missing -> exactly one line", len(found), 1)
        check_in("K-N8.10 naming it", "case TC-004", found[0])
        check_in("K-N8.10 with the two doors, the scribe's and --write", "report_facts.py --task QA-1 --write", found[0])
        check_in("K-N8.10 ... the scribe's", "qa-doc-scribe", found[0])
        start = full.index("## Left with you")
        end = full.index("<!-- facts:regression -->")
        path.write_text(full[:start] + "## Left with you\n\n" + full[end:], encoding="utf-8")
        check_eq("K-N8.10 an empty section on after_checks: one line per expected ref", len(gaps()), 3)
        path.write_text(full.replace("<!-- facts:regression -->", "4. **An extra the scribe wanted (R-1, TC-001).** To check: x. "
                        "How: y.\n\n<!-- facts:regression -->"), encoding="utf-8")
        check_eq("K-N8.10 an extra scribe item is allowed", gaps(), [])
        path.write_text(full.replace("<!-- /facts:regression -->\n", "<!-- /facts:regression -->\n\nA paragraph after the block.\n"),
                        encoding="utf-8")
        position = [p for p in RF.check(task) if "stands outside" in p]
        check_eq("K-N8.10 a paragraph after the regression block: the position line", len(position), 1)
        check_in("K-N8.10 it says where to move it", "move it above the regression block", position[0])
        # a requirement-keyed item is matched by its R-n
        edit = full.replace("**The token confirmation (R-4, TC-004).**", "**The token confirmation (R-4).**")
        path.write_text(edit, encoding="utf-8")
        check_eq("K-N8.10 an item that names the case's requirement but not the case still misses the case", len(gaps()), 1)
    finally:
        cleanup(root)


def collect_gaps_rows() -> None:
    """RH1-3 3.6b (B4): the project's test files that could not be collected reach the report from the story's own
    `state/collect-gaps.json` (one writer, one reader), one line per path, owner project; no file -> no line and no claim."""
    import shutil
    import check_delivery as CD
    import collect_gaps as CG
    source = Path(__file__).resolve().parent / "fixtures" / "after-checks"
    root = temp_dir("qa-report-collect-gaps-")
    task = root / "QA-1"
    try:
        shutil.copytree(source, task)
        CD.assess(task)
        RF.write(task)
        before = (task / "test-report.md").read_text(encoding="utf-8")
        check_not_in("K-3.6b-none no collect-gaps.json: no line, and nothing claims everything was collected",
                     "could not be collected", G.find_blocks(before)["regression"][2])
        check_eq("K-3.6b-none ... and no unknown entry", RF.build(task)["unknown"].get("collect_gaps"), None)

        gap = {"path": "tests/mcp/test_mcp_config_clone.py", "head": "ModuleNotFoundError: No module named 'testproject1_sdk.x'"}
        folder = {"path": "tests/servicenow_budget", "head": ""}
        CG.record(task, "gate_a", "project", [gap, folder])
        CG.record(task, "s5_collect", "api", [gap])
        CG.record(task, "s5_collect", "ui", [gap])
        RF.write(task)
        block = G.find_blocks((task / "test-report.md").read_text(encoding="utf-8"))["regression"][2]
        lines = [ln for ln in block.splitlines() if "could not be collected" in ln]
        check_eq("K-3.6b-row one line per PATH (3 records, 2 paths)", len(lines), 2)
        check_in("K-3.6b-row the line names the file, its cause, that its tests were not run and the owner",
                 "the project's test file tests/mcp/test_mcp_config_clone.py could not be collected "
                 "(ModuleNotFoundError: No module named 'testproject1_sdk.x'); tests in it were not run — owner: project", lines[0])
        check_in("K-3.6b-dedupe the path named by two sources and two profiles carries them all once",
                 "[profile: api, project, ui]", lines[0])
        check_in("K-3.6b-row a folder with no cause has no empty parentheses", "tests/servicenow_budget could not be collected; tests in it",
                 lines[1])
        check_in("K-3.6b-owner the block keeps the regression list above the new lines",
                 "### Regression to run", block.split("### Test files the run could not collect")[0])
        check_eq("K-3.6b-row --check is clean with the lines in the block", [p for p in RF.check(task) if "regression" in p], [])
        RF.render(RF.build(task))  # pure: the same facts render twice alike
        check_eq("K-3.6b-pure the report is rebuilt alike from the same record",
                 RF.render(RF.build(task))["regression"], RF.render(RF.build(task))["regression"])

        # F4 (AR-27): the owner BY SOURCE - a test file the story's own S5 request names is the story's, never "project"
        mine = {"path": "tests/story/test_new.py", "head": "SyntaxError: bad", "owner": "story"}
        CG.record(task, "s5_collect", "api", [dict(gap, owner="project"), mine, {"path": "tests/odd/test_x.py", "head": ""}])
        block = RF.render(RF.build(task))["regression"]
        by_file = {ln.split(" test file ")[1].split(" could not")[0]: ln for ln in block.splitlines() if " test file " in ln}
        check_in("F4-owner a file the story wrote is called the story's, with its owner named",
                 "the story's own test file tests/story/test_new.py could not be collected (SyntaxError: bad)", by_file["tests/story/test_new.py"])
        check_in("F4-owner ... owner: the story (its S5 automation)", "owner: the story (its S5 automation)", by_file["tests/story/test_new.py"])
        check_in("F4-owner a path gate A also found stays the project's", "owner: project", by_file[gap["path"]])
        check_in("F4-owner a row with no owner word is no claim: owner not established", "owner: not established",
                 by_file["tests/odd/test_x.py"])

        (task / "state" / "collect-gaps.json").write_text("{nope", encoding="utf-8")
        facts = RF.build(task)
        check_in("K-3.6b-unknown a record that cannot be read is an unknown entry", "collect-gaps.json", facts["unknown"].get("collect_gaps", ""))
        check_in("K-3.6b-unknown ... rendered as an Unknown line, never as a clean history", "Unknown which test files could not be collected",
                 RF.render(facts)["regression"])
        CG.record(task, "gate_a", "project", [gap])
        for profile in ("api", "ui"):
            CG.record(task, "s5_collect", profile, [])
        CG.record(task, "gate_a", "project", [])
        check_eq("K-3.6b-erase a record emptied by a later clean collect leaves no line",
                 "could not be collected" in RF.render(RF.build(task))["regression"], False)
    finally:
        cleanup(root)


def regression_block() -> None:
    """K-N8.11 (F3, FR-49): the S3 list, verbatim and last in the section; a marked report written before the block gets it."""
    import shutil
    import check_delivery as CD
    source = Path(__file__).resolve().parent / "fixtures" / "after-checks"
    root = temp_dir("qa-report-regression-")
    task = root / "QA-1"
    try:
        shutil.copytree(source, task)
        bullets = ["- `poetry run pytest tests/test_cart.py` - covers the cart total path", "- `npm run e2e -- --grep coupon`  (two spaces)",
                   "- run the nightly smoke for checkout, by hand if the runner is down"]
        plan = (task / "test-plan.md").read_text(encoding="utf-8")
        head = plan.split("## Recommended regression")[0]
        (task / "test-plan.md").write_text(head + "## Recommended regression\n\n" + "\n".join(bullets) + "\n", encoding="utf-8")
        CD.assess(task)
        RF.write(task)
        text = (task / "test-report.md").read_text(encoding="utf-8")
        block = G.find_blocks(text)["regression"][2].splitlines()
        # HF8-17: the lines the gap readers add (the integrations a story with no configuration could not tie) stand AFTER the list
        check_eq("K-N8.11 a section of 3 bullets -> 3 byte-equal lines in the block", block[2:2 + len(bullets)], bullets)
        check_eq("K-N8.11 the block opens with its own heading", block[0], "### Regression to run (from the plan approved at gate A)")
        check("K-N8.11 and it is last in the section: the next marker after it is the next section's block",
              text.index("<!-- /facts:regression -->") < text.index("<!-- facts:open-questions -->")
              and text.index("## Left with you") < text.index("<!-- facts:regression -->"))
        # a marked report written before N8 has no block (and no plan-skipped one): --write inserts both, in place
        old = text
        for name in ("regression", "skipped-by-plan"):
            start, end, _ = G.find_blocks(old)[name]
            begin = old.rfind(f"<!-- facts:{name} -->", 0, start)
            stop = old.find("\n", end) + 1
            old = old[:begin] + old[stop:]
        check_eq("K-N8.11 setup: the old report has neither", [n for n in ("regression", "skipped-by-plan") if n in G.find_blocks(old)], [])
        (task / "test-report.md").write_text(old, encoding="utf-8")
        check("K-N8.11 --check names the missing block", any("block `regression` is missing" in p for p in RF.check(task)))
        res = RF.write(task)
        check("K-N8.11 --write inserts it", res["ok"], str(res["lines"]))
        again = (task / "test-report.md").read_text(encoding="utf-8")
        names = [m.group(1) for m in re.finditer(r"<!-- facts:([a-z-]+) -->", again)]
        check_eq("K-N8.11 every block, in REPORT_BLOCKS order", names,
                 [b for b in G.REPORT_BLOCKS if b not in G.REPORT_BLOCKS_AFTER_GATE_B and b not in G.REPORT_BLOCKS_WHEN_PRESENT])
        # the fixture's pasted appendix is older than HF8-17 (`e2e-ui` + `manual-human` read `not run`, now `wait`): paste it again
        repaste_appendix(task)
        check_eq("K-N8.11 and --check is clean", RF.check(task), [])
        # no section at all: the gap line, never a block
        (task / "test-plan.md").write_text(head, encoding="utf-8")
        CD.assess(task)
        RF.write(task)
        gap = G.find_blocks((task / "test-report.md").read_text(encoding="utf-8"))["regression"][2]
        check_in("K-N8.11 a plan with no regression section: the gap line", "no regression scope was recorded at S3 — a factory gap", gap)
        check_eq("K-N8.11 --check is still clean (a gap line is not a block)", [p for p in RF.check(task) if "regression" in p], [])
    finally:
        cleanup(root)


PB_EXPECTED = "0123456789abcdef0123456789abcdef01234567"
PB_TESTED = "fedcba9876543210fedcba9876543210fedcba98"


def _pb_block(task: Path, name: str, profile: str, at: str, record: dict) -> None:
    write(task / "work" / "run-blocks" / f"{name}.json",
          {"attempt_id": name, "attempt_started_at": at, "profile_id": profile, "runtime_provenance": record})


def _pb_person(profile: str, words: str, kind: str = "deployed", tested: str = "") -> dict:
    """A run block's provenance that is a PERSON's word (`profile_contract.person_confirmed` accepts it)."""
    confirmation = {"kind": kind, "task": "T-1", "revision": tested or PB_EXPECTED, "words": words, "at": "2026-10-03T09:30:00Z"}
    record = {"profile_id": profile, "timestamp": "2026-10-03T09:31:00+00:00", "environment_id": "local",
              "expected_source_revision": PB_EXPECTED, "observed_runtime_identity": "person_confirmed:" + (tested or PB_EXPECTED)[:12],
              "evidence_refs": [], "result": "person_confirmed",
              "provenance": {"technical_verification": False, "identity_kind": "person_confirmed"},
              "person_confirmation": confirmation}
    if kind == "test_deployed":
        confirmation["story_revision"] = PB_EXPECTED
        record["tested_build"] = tested
    return record


def _pb_matched(profile: str) -> dict:
    return {"profile_id": profile, "timestamp": "2026-10-03T11:00:00+00:00", "environment_id": "local",
            "expected_source_revision": PB_EXPECTED, "observed_runtime_identity": "container:" + PB_EXPECTED[:12],
            "evidence_refs": ["evidence/runtime-provenance.json"], "result": "matched",
            "provenance": {"technical_verification": True, "source_linkage": "exact", "deployed_source_revision": PB_EXPECTED}}


def person_build_line() -> None:
    """K-N2.14 (t-300 N2, critic t-393 F4): the report says in one line, per PROFILE, when its tests ran on a build the PERSON
    confirmed - from the CURRENT run block of the profile only, the words folded to one capped line, the line clean by the
    report's own rules. No person's word, no line (the negative twin).
    t-305 N8 attempt 2 (F7, the owner's ruling): the words are quoted VERBATIM in a code span of a line that starts with
    `RF.PERSON_LINE_LEAD`; the text rules are not applied to the span and still are to the factory's own part of the line."""
    def proven(task: Path) -> str:
        return RF.render(RF.build(task))["proven"]

    def lines_of(text: str) -> list:
        return [ln for ln in text.splitlines() if ln.startswith(RF.PERSON_LINE_LEAD)]

    task = story()
    try:
        check_eq("K-N2.14 the facts carry the key", RF.build(task)["person_build"], [])
        check_eq("K-N2.14 NEG: no run block -> no line", lines_of(proven(task)), [])
        _pb_block(task, "a1", "api", "2026-10-03T08:00:00+00:00", _pb_matched("api"))
        check_eq("K-N2.14 NEG: a matched block -> no line", lines_of(proven(task)), [])
        # the person's word on the api profile
        _pb_block(task, "a2", "api", "2026-10-03T09:40:00+00:00", _pb_person("api", "yes, the new build is on the stand"))
        text = proven(task)
        want = ("On a build you confirmed, the api tests ran: `yes, the new build is on the stand` (2026-10-03). "
                "The factory did not read which build the stand runs.")
        check_eq("K-N2.14 a person-confirmed block -> the line, with the profile, the words and the date", lines_of(text), [want])
        check_eq("K-N2.14 it stands right after the section header, followed by a blank line",
                 text.splitlines()[:4], [text.splitlines()[0], "", want, ""])
        # a later matched run of the same profile removes the line: the superseded block is never read
        _pb_block(task, "a3", "api", "2026-10-03T11:00:00+00:00", _pb_matched("api"))
        check_eq("K-N2.14 a later matched block of the same profile removes the line", lines_of(proven(task)), [])
        # a reparse block carries no provenance and does not erase the person's word
        write(task / "work" / "run-blocks" / "a3.json", {"attempt_id": "a3", "attempt_started_at": "2026-10-03T08:00:00+00:00",
                                                         "profile_id": "api"})
        check_eq("K-N2.14 a block with no provenance is no current block: the word stands", len(lines_of(proven(task))), 1)
        (task / "work" / "run-blocks" / "a3.json").unlink()
        # two profiles: one matched, one the person's word -> one line naming only the second
        _pb_block(task, "u1", "ui", "2026-10-03T09:50:00+00:00", _pb_person("ui", "the ui build is there"))
        _pb_block(task, "a4", "api", "2026-10-03T12:00:00+00:00", _pb_matched("api"))
        found = lines_of(proven(task))
        check_eq("K-N2.14 two profiles (api matched, ui the person's word) -> ONE line", len(found), 1)
        check_in("K-N2.14 ... naming the ui profile", "the ui tests ran", found[0])
        check_not_in("K-N2.14 ... and not the api profile", "the api tests", "\n".join(found))
        check_not_in("K-N2.14 ... and never 'every test'", "every test", proven(task))
    finally:
        cleanup(task.parents[2])
    # a test-deployed word: the second form follows the first
    task = story()
    try:
        _pb_block(task, "b1", "api", "2026-10-03T09:40:00+00:00", _pb_person("api", "test the build that is there", "test_deployed", PB_TESTED))
        found = lines_of(proven(task))
        check_eq("K-N2.14 tested_build -> two lines for the profile", len(found), 2)
        check_eq("K-N2.14 ... the second names both builds, 12 characters each, and what a green test proves", found[1],
                 f"On a build you confirmed, the api tests ran on build {PB_TESTED[:12]}, not this story's {PB_EXPECTED[:12]}, "
                 "by your decision: a green test proves that build only.")
    finally:
        cleanup(task.parents[2])
    # --- F7: the words are quoted VERBATIM; the text rules still judge the factory's own part of the line ---------------------
    def quoted_of(line: str) -> str:
        """The person's span of a finished line, as a reader of the line sees it (the code span, fence taken off)."""
        import human_text
        split = human_text.quoted_split(line)
        return split[1].strip() if split else ""

    def forbidden_errors(task: Path) -> list:
        errors: list = []
        V.check_report_forbidden(task / "test-report.md", errors)
        return errors

    import human_text
    check_in("K-F7 the lead of the line is DATA in references/human-text.json (action_lines.quoted_words), FR-13",
             RF.PERSON_LINE_LEAD, human_text.quoted_prefixes(human_text.rules()["action_lines"]))
    task = story()
    try:
        legacy_report(task, False)
        # K-F7.1: a flag and a path in the words stand verbatim, and the report passes its own check
        flag_words = "--skip_cache from work/build"
        _pb_block(task, "c1", "api", "2026-10-03T09:40:00+00:00", _pb_person("api", flag_words))
        found = lines_of(proven(task))
        check_eq("K-F7.1 words with a flag and a path -> ONE line", len(found), 1)
        check_eq("K-F7.1 the words stand verbatim in the quoted span", quoted_of(found[0]), flag_words)
        check("K-F7.1 the factory's own part of that line obeys the rules (the span is taken out by position)",
              RF._clean_line(found[0]), found[0])
        w = RF.write(task)
        check("K-F7.1 --write succeeds", w["ok"], str(w["lines"]))
        check_eq("K-F7.1 --check passes with the words in", RF.check(task), [])
        check_eq("K-F7.1 the report's forbidden-needle check passes (a `work/` path inside the span)", forbidden_errors(task), [])
        check_in("K-F7.1 the words are in the written report, byte for byte", "`--skip_cache from work/build`",
                 (task / "test-report.md").read_text(encoding="utf-8"))
        # K-F7.2 (the negative twin): the SAME flag/path in the factory's own part of the line is still refused
        report = (task / "test-report.md").read_text(encoding="utf-8")
        mine = lines_of(report)[0]
        for label, edited in (("a path under work/ after the caveat", mine + " See work/build."),
                              ("the words in backquotes on a line that does not start with the lead",
                               "The api tests ran: `--skip_cache from work/build`"),
                              ("a path in the lead's own sentence", mine.replace("tests ran:", "tests ran from work/build:", 1))):
            (task / "test-report.md").write_text(report.replace(mine, edited, 1), encoding="utf-8", newline="\n")
            check(f"K-F7.2 negative twin: {label} is refused", any("work/" in e for e in forbidden_errors(task)),
                  str(forbidden_errors(task)))
        (task / "test-report.md").write_text(report, encoding="utf-8", newline="\n")
        check("K-F7.2 negative twin: `_clean_line` refuses a flag in the factory's part",
              not RF._clean_line("On a build you confirmed, the api tests ran: `x` (2026-10-03). Pass --skip_cache yourself."))
        check("K-F7.2 ... and accepts the same flag inside the span",
              RF._clean_line("On a build you confirmed, the api tests ran: `Pass --skip_cache yourself` (2026-10-03). Fine."))
        # words that carry a backquote: a longer fence keeps them ONE span, and the rules still do not judge them
        tick = "ran `make build --force` then work/x"
        _pb_block(task, "c2", "api", "2026-10-03T09:45:00+00:00", _pb_person("api", tick))
        found = lines_of(proven(task))
        check_eq("K-F7.5 words with backquotes stand verbatim in ONE span", quoted_of(found[0]), tick)
        check("K-F7.5 ... and the line's own part is clean", RF._clean_line(found[0]), found[0])
        RF.write(task)
        check_eq("K-F7.5 ... and the written report passes the needle check", forbidden_errors(task), [])
        # K-F7.6 (G3, attempt 3): the exemption is EXACTLY one span at the rendered position - `human_text.quoted_split`, ONE
        # definition read by the shape rows and by the report validator. Anything else on a line that merely starts with the lead
        # is judged as usual. The fence form the renderer emits (a run longer than any inside the words, padded when the words
        # start or end with a backquote) is what the closing-run rule reads: the first later run of EXACTLY that length.
        rendered = lines_of(proven(task))[0]
        split = human_text.quoted_split(rendered)
        check("K-F7.6 the rendered line (backquotes in the words, longer fence) is recognised, and its span is the words",
              bool(split) and split[1].strip() == tick and split[2].startswith(" ("), repr(split))
        report = (task / "test-report.md").read_text(encoding="utf-8")
        mine = lines_of(report)[0]
        probes = (("the critic's probe: the lead, then other text and several spans",
                   "On a build you confirmed, see `cv_1a2b`, `--skip_cache` and `scripts/check_delivery.py`"),
                  ("a second span after the date", mine.replace(")", ") and `--other_flag work/y`", 1)),
                  ("the lead followed by different text", "On a build you confirmed, the api tests ran on `work/x` (2026-10-03)."),
                  ("several spans, the first not followed by the date", "On a build you confirmed, the api tests ran: `a` and `work/x` (2026-10-03)."),
                  ("a backquote in the profile", "On a build you confirmed, the `x` tests ran: `work/x` (2026-10-03)."),
                  ("a line that does not begin with the lead", "Note: On a build you confirmed, the api tests ran: `work/x` (2026-10-03)."))
        for label, line in probes:
            if label == "a second span after the date":
                # the rendered shape, so the FIRST span is exempt - and the second one stays in what is judged
                got = human_text.quoted_split(line)
                check("K-F7.6 a second span after the date: only the first span is taken out, the second stays judged",
                      bool(got) and "`--other_flag work/y`" in got[2], repr(got))
            else:
                check(f"K-F7.6 {label}: not the rendered shape, so nothing is exempt", human_text.quoted_split(line) is None, line)
            (task / "test-report.md").write_text(report.replace(mine, line, 1), encoding="utf-8", newline="\n")
            check(f"K-F7.6 {label}: the report check refuses it", bool(forbidden_errors(task)), str(forbidden_errors(task)))
        (task / "test-report.md").write_text(report, encoding="utf-8", newline="\n")
        check("K-F7.6 the probe line is refused by the shape rows too (a flag, a script name)",
              not RF._clean_line("On a build you confirmed, see `cv_1a2b`, `--skip_cache` and `scripts/check_delivery.py`"))
        check("K-F7.6 ... and the rendered line with a second span after the date is refused by `_clean_line`",
              not RF._clean_line(mine.replace(")", ") and `--other_flag work/y`", 1)))
        check_eq("K-F7.6 the real line with `--skip_cache from work/build` still passes the report check", forbidden_errors(task), [])
        check("K-F7.6 the empty-words line has no span: nothing matches, it is judged whole",
              human_text.quoted_split("On a build you confirmed, the api tests ran (2026-10-03; no words of yours are recorded). "
                                      "The factory did not read which build the stand runs.") is None)
        # K-F7.3: the cap - AT (120 whole) and BEYOND (121 cut, a visible ellipsis); newlines become single spaces
        at120 = ("a" * 59 + " " + "b" * 60)
        beyond = ("a" * 59 + " " + "b" * 61)
        check_eq("K-F7.3 setup: 120 and 121 characters", (len(at120), len(beyond)), (120, 121))
        _pb_block(task, "c3", "api", "2026-10-03T09:50:00+00:00", _pb_person("api", at120))
        check_eq("K-F7.3 AT the cap: 120 characters are whole, no ellipsis", quoted_of(lines_of(proven(task))[0]), at120)
        _pb_block(task, "c4", "api", "2026-10-03T09:55:00+00:00", _pb_person("api", beyond))
        cut = quoted_of(lines_of(proven(task))[0])
        check("K-F7.3 BEYOND the cap: cut at 120 or less with a visible ellipsis, never silently",
              len(cut) <= RF.PERSON_WORDS_LIMIT and cut.endswith(RF.ELLIPSIS) and len(cut) < len(beyond), repr(cut))
        _pb_block(task, "c5", "api", "2026-10-03T10:00:00+00:00", _pb_person("api", "yes\n  it is the\r\nnew   build " + "word " * 40))
        found = lines_of(proven(task))
        quoted = quoted_of(found[0])
        check("K-F7.3 newlines inside the words become single spaces: ONE line, capped, ellipsis",
              len(found) == 1 and "\n" not in quoted and quoted.startswith("yes it is the new build word")
              and quoted.endswith(RF.ELLIPSIS) and len(quoted) <= RF.PERSON_WORDS_LIMIT, repr(found))
        # K-F7.4: empty words, or none recorded -> the build was confirmed, with the date, and no empty quotation marks. A
        # record that carries no words is not a valid person's word (`profile_contract.person_confirmed`), so the renderer is
        # driven with the facts directly.
        for label, words in (("empty", ""), ("blanks and newlines", "  \n \t "), ("absent", None)):
            entry = {"profile": "api", "words": words, "at": "2026-10-03", "tested_build": "", "expected": ""}
            lines = RF._person_build_lines({"person_build": [entry], "unknown": {}})
            check_eq(f"K-F7.4 {label} words -> one line, the date, no quotation",
                     lines, ["On a build you confirmed, the api tests ran (2026-10-03; no words of yours are recorded). "
                             "The factory did not read which build the stand runs."])
            check_not_in(f"K-F7.4 {label} words -> no empty quotation marks", "``", lines[0])
            check_not_in(f"K-F7.4 {label} words -> no empty double quotes", '""', lines[0])
        # an unreadable run block may have been the word: said, not guessed (FR-41)
        write(task / "work" / "run-blocks" / "zz.json", "{ torn")
        text = proven(task)
        check_in("K-N2.14 an unreadable run block -> an Unknown line, not silence", "whether the tests ran on a build you confirmed", text)
        check_eq("K-N2.14 ... and no confident line beside it", lines_of(text), [])
    finally:
        cleanup(task.parents[2])


def head_never_names_a_hash() -> None:
    """K-G2 (t-305 N8 attempt 3, G2, FR-20): the head of a `no` never prints a `ti_<hash>` id - a person cannot open it and the
    report check refuses it. A waiver does not hide a failure from the head (`waived:failed:*` holds the `no`, the kinds file L13), a
    test row is named by its case id and selector, and a test row with neither is no candidate: the residual sentence speaks."""
    def head_of(rows: list) -> tuple:
        task = story(with_bug=False, extra_ledger=ledger(rows=rows, ready=False))
        try:
            legacy_report(task, False)
            res = RF.write(task)
            check("K-G2 setup: --write", res["ok"], str(res["lines"]))
            path = task / "test-report.md"
            head = G.find_blocks(path.read_text(encoding="utf-8"))["verdict"][2].splitlines()[0]
            errors: list = []
            V.check_report_forbidden(path, errors)
            return head, errors, RF.build(task)["verdict"]["word"]
        finally:
            cleanup(task.parents[2])
    ti = "ti_4fa2889035cac1487897"
    plan = {"ref": "TS-1", "kind": "plan_row", "state": "not_executed:no result recorded for this row's cases", "detail": "TC-001"}
    test = {"ref": ti, "kind": "test", "state": "failed:APP_BUG", "detail": "tests/api/test_a.py::TC-001"}
    for label, rows, want in (
            ("a `not_executed` plan row whose test failed", [plan, test],
             "Because TC-001 (tests/api/test_a.py::TC-001) failed in the run - the triage verdict is APP_BUG"),
            ("a gate A waiver on the failed plan row (`waived:failed:APP_BUG`)",
             [dict(plan, state="waived:failed:APP_BUG"), dict(test, state="waived:failed:APP_BUG")],
             "Because TS-1 (TC-001) failed in the run - the triage verdict is APP_BUG"),
            ("a waived failed TEST row under a `not_executed` plan row", [plan, dict(test, state="waived:failed:APP_BUG")],
             "Because TC-001 (tests/api/test_a.py::TC-001) failed in the run - the triage verdict is APP_BUG")):
        head, errors, word = head_of(rows)
        check_eq(f"K-G2 {label}: the ledger says no", word, "no")
        check_in(f"K-G2 {label}: the head names the failure by its case", want, head)
        check_not_in(f"K-G2 {label}: the head carries no hash id", "ti_", head)
        check_eq(f"K-G2 {label}: the report passes the forbidden-needle check", errors, [])
    # a test row with no case and no selector: no candidate, no id - the head says something else, in words
    head, errors, word = head_of([plan, dict(test, detail=ti)])
    check_not_in("K-G2 a failed test row with neither a case nor a selector: no hash id in the head", "ti_", head)
    check_not_in("K-G2 ... and it is not named as a failure from a row that cannot be named", "failed in the run", head)
    check_eq("K-G2 ... and the report passes the check", errors, [])


# --- HF2-6b (RD1-8): one number "proven", one carrier of a question's status, the appendix compared ------------------

def shaped_12586(verdicts=None, handed=()) -> Path:
    """The shape of 12586: nine requirements, each with one case and one test, every test GREEN in the run. `verdicts`: {n: the
    critic's verdict of test n} (the others carry none, so the ledger does not count them); `handed`: cases a person took."""
    ids = range(1, 10)
    rows = [test_row(f"test_{n}", reason="handed" if f"TC-00{n}" in handed else "unmeasured") for n in ids]
    task = story(with_bug=False, extra_ledger=ledger(rows))
    write(task / "work" / "requirements-register.md", REGISTER.split("| R-1")[0]
          + "".join(f"| R-{n} | Requirement {n} | ac | - | yes | AC-{n} |\n" for n in ids))
    write(task / "test-plan.md", PLAN.split("| TS-1")[0] + "".join(
        f"| TS-{n} | thing {n} | R-{n} | state @ {n} | degraded | P2 | diff:src/a.py:{n} | requirement:R-{n} | `automate` - core | new "
        "| api | decision table |\n" for n in ids) + "\n## Recommended regression\n\n1. run the billing suite\n")
    tests = []
    for n in ids:
        write(task / "work" / "test-cases" / "billing" / f"TC-00{n}.md", CASE.format(cid=f"TC-00{n}", title=f"Case {n}", req=f"R-{n}", ts=f"TS-{n}"))
        tests.append(dict({"case": f"TC-00{n}", "covers": [f"TC-00{n}"], "file": "tests/api/test_a.py", "instance_id": f"test_{n}",
                           "status": "green"}, **({"critic_verdict": verdicts[n]} if (verdicts or {}).get(n) else {})))
    write(task / "work" / "automation-manifest.json", {"tests": tests, "unresolved": [
        {"case": c, "reason": "handed_to_person", "detail": "run it: npm test"} for c in handed]})
    write(task / "work" / "run-report.json", dict(RUN_REPORT, current_results=[{"instance_id": f"test_{n}", "status": "passed"} for n in ids]))
    return task


def one_number_proven() -> None:
    """6b-K1/K2 and critic t-118 item 6: "N proven by tests" in the verdict and "M green tests count as proven" are ONE fact.
    On the shape of 12586 (nine requirements, nine green tests, one counted) the trace says nine `pass` and the report says one."""
    task = shaped_12586({1: "approved"}, handed=("TC-008",))
    try:
        facts = RF.build(task)
        by_id = {i["id"]: i for i in facts["requirements"]["items"]}
        verdict = RF.render(facts)["verdict"]
        check_eq("12586 shape: every requirement's trace row is a `pass`", sorted({r for i in by_id.values() for r in i["results"]}), ["pass"])
        check_eq("one green test counts", facts["tests"]["count"], 1)
        check_eq("one requirement is proven by tests; the handed one waits, the rest are not proven",
                 facts["requirements"]["counts"], {"proven": 1, "bug": 0, "unproven": 7, "wait": 1, "deferred": 0, "bookkeeping": 0})
        check_in("the verdict counts ONE proven requirement", "Of 9 requirements: 1 proven by tests", verdict)
        check_in("and the same one green test", "1 green test counts as proven", verdict)
        not_proven = RF.render(facts)["not-proven"]
        words = RF.NOT_COUNTED_WORDS + RF.NOT_COUNTED_REASON
        for rid in ("R-2", "R-3", "R-4", "R-5", "R-6", "R-7", "R-9"):
            check_eq(f"{rid}: green but not counted -> not proven, with the critic/probe words first",
                     (by_id[rid]["class"], by_id[rid]["bases"][0]), ("unproven", words))
            check_in(f"{rid} stands under Not proven with those words", words, _line_of(not_proven, rid))
        check_eq("R-1: the counted test keeps its requirement proven", by_id["R-1"]["class"], "proven")
        # critic t-118 item 6 / P21: a test the person TOOK is not "not approved by the critic" (FR-35)
        check_eq("R-8 (handed): the requirement WAITS", by_id["R-8"]["class"], "wait")
        check_in("... with the hand-off words", "handed to the person", by_id["R-8"]["bases"][0])
        check_not_in("... and never the critic's", "the code critic has not approved", by_id["R-8"]["bases"][0])
        check_in("R-8 stands under Not proven with the hand-off words", "handed to the person", _line_of(not_proven, "R-8"))
    finally:
        cleanup(task.parents[2])
    # D5: a `pass` row with NO tests (a manual record) is not asked for a counted test
    reqs = {"items": [{"id": "R-1", "class": "proven", "bases": ["checked by hand"], "results": ["pass"]}],
            "counts": {"proven": 1, "bug": 0, "unproven": 0, "wait": 0, "deferred": 0}}
    RF._count_by_tests(reqs, {"proven": [], "count": 0, "green_not_counted": 0, "unverified": 0}, {},
                       {"rows": [{"requirement": "R-1", "result": "pass", "tests": []}]})
    check_eq("a manual record (`pass`, no tests) stays proven as today", (reqs["items"][0]["class"], reqs["counts"]["proven"]), ("proven", 1))
    # K2: no ledger -> which tests count is UNKNOWN, and so is the number
    task = story(with_ledger=False)
    try:
        facts = RF.build(task)
        verdict = RF.render(facts)["verdict"]
        check_eq("no ledger: no tests fact", facts["tests"], None)
        check_eq("the count of proven requirements is unknown, not a number", facts["requirements"]["counts"]["proven"], None)
        check_in("the verdict says so, with the ledger's own unknown", "proven by tests: unknown — " + facts["unknown"]["ledger"], verdict)
        check_not_in("... never as 0 or 1", " proven by tests, ", verdict)
        check_eq("the requirement the trace calls `pass` reads `unknown`: never proven, never unproven",
                 next(i["class"] for i in facts["requirements"]["items"] if i["id"] == "R-1"), "unknown")
        check_not_in("and it is not listed under Not proven", "R-1", " ".join(i["id"] for i in facts["not_proven"]))
    finally:
        cleanup(task.parents[2])


def _line_of(block: str, rid: str) -> str:
    return next((ln for ln in block.splitlines() if ln.startswith(f"- **{rid}**")), "")


def questions_have_one_predicate() -> None:
    """6b-K3 (M4): a question is listed unless `QR.settled`; the "Needed" line of a Then follows the same predicate."""
    import question_register as QR

    def say(task, *records):
        write(task / "work" / "question-answers.jsonl", "".join(json.dumps(
            dict({"kind": "question", "status": "answered", "reading": "a", "where": "gate A", "by": "person",
                  "at": "2026-09-30T10:00:00", "row_hash": ""}, **r)) + "\n" for r in records))

    task = story()
    try:
        say(task, {"id": "Q1", "status": "deferred_to_report", "reading": "", "words": "Q1: until the report"},
            {"id": "Q2", "status": "not_needed", "reading": "", "words": "Q2: not needed"})
        facts = RF.build(task)
        body = RF.render(facts)["open-questions"]
        check_eq("not_needed is settled; deferred_to_report is kept open", [q["id"] for q in facts["questions"]["listed"]], ["Q1"])
        check_in("the deferred question is listed with its mark", "Is a refund due after cancelling? (kept on your word until this report)", body)
        check_eq("one question is settled", facts["questions"]["answered"], 1)
        say(task, {"id": "Q1", "words": "Q1: a", "row_hash": "0" * 64}, {"id": "Q2", "words": "Q2: a", "row_hash": ""})
        facts = RF.build(task)
        body = RF.render(facts)["open-questions"]
        check_eq("answered, but to an earlier wording of the row: still listed; the other is settled",
                 [(q["id"], q["changed"]) for q in facts["questions"]["listed"]], [("Q1", True)])
        check_in("with the words that say why", "(your answer was given to an earlier wording of this question)", body)
        check_in("the heading counts it", "## Open questions — 1", body)
        manifest = dict(MANIFEST, then_bindings=[{"case": "TC-001", "then": 1, "instance_id": None, "assertion_ref": None,
                                                  "status": "unresolved", "reason": "expectation_unconfirmed", "question": "Q1"}])
        write(task / "work" / "automation-manifest.json", manifest)
        found = RF.build(task)["cases"]["unconfirmed"]
        check_eq("the Then still waits: its answer was given to another wording, so the `Needed` line is owed",
                 [(i["answered"], i["line"]) for i in found],
                 [(False, "To check: The subscription reads cancelled. Needed: your answer to Q1")])
        # 6b-K6: the Then number is read by the contract's one reader (a bool, a float, a list are "none"); no `int(...)` here
        for bad in (True, 4.0, [4], {"n": 1}, "x", 0):
            index = C.case_index(task)
            got = RF._unconfirmed_thens(task, dict(manifest, then_bindings=[dict(manifest["then_bindings"][0], then=bad)]), index,
                                        RF._key_fn(index))
            check_eq(f"a row whose then is {bad!r} numbers no Then", [i["then"] for i in got], [0])
            check_in(f"... and the line says so ({bad!r})", "To check: a Then the row does not number. Needed:", got[0]["line"])
        write(task / "work" / "automation-manifest.json", manifest)
        view ={q["id"]: q for q in QR.load(task)["questions"]}["Q1"]
        QR.record(task, "Q1", "answered", "Q1: a", "gate A", "driver", view["row_hash"], reading="a")
        check_eq("CONTROL: answered on the row as it stands now -> settled, no `Needed` line",
                 [(i["answered"], i["line"]) for i in RF.build(task)["cases"]["unconfirmed"]], [(True, "")])
        check_eq("CONTROL: and the question leaves the list", RF.build(task)["questions"]["listed"], [])
        write(task / "work" / "automation-manifest.json", dict(manifest, then_bindings=[dict(manifest["then_bindings"][0], then="1")]))
        check_eq("CONTROL: the text `1` is Then 1", [i["then"] for i in RF.build(task)["cases"]["unconfirmed"]], [1])
    finally:
        cleanup(task.parents[2])


def gate_a_names_an_unanswered_question() -> None:
    """6b-K4 (F-5 b): an id in the person's gate A words with no recorded answer stays under Open questions, and the gate A block
    says so under the quote - read from the question facts, not from a second scan of the words."""
    sentence = "Your words here name Q2, but no answer to it is recorded, so it stays under Open questions."
    task = story(pipeline={"ticket": "T-1", "gates": {"A": {"authorization_source": "Please look at Q2 again; Q2 stands"}}})
    try:
        a = render_all(task)["gate-a"]
        check_in("a `named` question: the sentence under the quote", "```\n" + sentence, a)
        check_eq("... once", a.count(sentence), 1)
        # GW1-42: a line that STARTS with the id and is no token is told as a line not read, with the line - never as "no answer"
        write(task / "pipeline.json", {"ticket": "T-1", "gates": {"A": {"authorization_source": "Q2: a (see the ticket)"}}})
        a = render_all(task)["gate-a"]
        stray = 'Your words here name Q2 in a line the factory did not read as an answer: "Q2: a (see the ticket)". Write `Q2: <letter>` alone on a line'
        check_in("GW1-42 a stray line of a `named` question is told as that, with the line", stray, a)
        check_not_in("GW1-42 ... and not as 'no answer is recorded'", "no answer to it is recorded", a)
        # F-6 (t-596): the Open questions section tells the same line, never "the factory recorded no answer" of it (FR-10)
        listed = render_all(task)["open-questions"]
        check_in("F-6 the Open questions section tells the stray line too", 'on a line the factory did not read as an answer: "Q2: a (see the ticket)"', listed)
        check_not_in("F-6 ... and does not say the factory recorded no answer", "recorded no answer", listed)
        # F-5 (t-596): the form never names a letter the person did not choose (Q2: b here)
        write(task / "pipeline.json", {"ticket": "T-1", "gates": {"A": {"authorization_source": "Q2: b (see the ticket)"}}})
        b = render_all(task)["gate-a"]
        check_in("F-5 the line is told whatever the letter", 'in a line the factory did not read as an answer: "Q2: b (see the ticket)"', b)
        check_not_in("F-5 ... and the form does not hard-code `a`", "`Q2: a`", b)
        write(task / "pipeline.json", {"ticket": "T-1", "gates": {"A": {"authorization_source": "Q2: a (see the ticket)"}}})
        # CONTROL: a prose mention keeps the old sentence in the section (the mutation that tells every named question as a stray fails here)
        write(task / "pipeline.json", {"ticket": "T-1", "gates": {"A": {"authorization_source": "Please look at Q2 again; Q2 stands"}}})
        check_in("F-6 CONTROL: a prose mention keeps `the factory recorded no answer`", "recorded no answer", render_all(task)["open-questions"])
        write(task / "pipeline.json", {"ticket": "T-1", "gates": {"A": {"authorization_source": "approve\n\nEarlier answer at this gate:\nQ2: a (old)"}}})
        check_not_in("GW1-42 the replaced earlier answer's line is not told", "did not read as an answer", render_all(task)["gate-a"])
        write(task / "pipeline.json", {"ticket": "T-1", "gates": {"A": {"authorization_source": "Q2: a question I read; Q2 stands"}}})
        write(task / "work" / "question-answers.jsonl", json.dumps(
            {"kind": "question", "id": "Q2", "status": "answered", "reading": "a", "words": "Q2: a", "where": "gate A", "by": "person",
             "at": "2026-09-30T10:00:00", "row_hash": ""}) + "\n")
        check_not_in("a recorded answer: no sentence", "Your words here name", render_all(task)["gate-a"])
        write(task / "work" / "question-answers.jsonl", "")
        write(task / "pipeline.json", {"ticket": "T-1", "gates": {"A": {"authorization_source": "Q-2: a question I read; Q10 stands"}}})
        check_not_in("`Q-2` and `Q10` are not the register's `Q2` (the register's own matcher)", "Your words here name", render_all(task)["gate-a"])
        write(task / "pipeline.json", {"ticket": "T-1", "gates": {"A": {"authorization_source": GATE_A}, "B": {"authorization_source": "Q2 stands"}}})
        check_not_in("a question only the gate B words name is not told under gate A", "Your words here name", render_all(task)["gate-a"])
    finally:
        cleanup(task.parents[2])


def _appendix_lines(task: Path) -> list:
    return [p for p in RF.check(task) if "appendix" in p]


def _set_report(task: Path, change) -> None:
    path = task / "test-report.md"
    path.write_text(change(path.read_text(encoding="utf-8")), encoding="utf-8", newline="")


def appendix_is_compared_with_a_render() -> None:
    """6b-K5 (M5), HF8-22 (L-B): the appendix is the `traceability.py --render` text, `--check` compares it (ONE line for any
    difference, worded as a stale block, door `--write`) and `--write` renders it again."""
    door = "report_facts.py --task T-1 --write"

    def fresh() -> Path:
        task = story(pipeline={"ticket": "T-1", "gates": {"A": {"authorization_source": GATE_A}}})
        legacy_report(task)
        RF.write(task)
        return task

    task = fresh()
    try:
        root = task.parents[2]
        check_eq("(a) a fresh report checks clean, appendix included", RF.check(task), [])
        before = tree_hash(root)
        # (b) a `pass` for a test the run holds no row for
        write(task / "work" / "run-report.json", dict(RUN_REPORT, current_results=[]))
        before = tree_hash(root)
        import stage_done as SD
        found = _appendix_lines(task)
        check_eq("(b) --check wrote nothing (FR-45)", tree_hash(root), before)
        check_eq("(b) ONE line for the appendix", len(found), 1)
        check_in("(b) worded as a stale block, so the S9 exit rebuilds it", "block `appendix` differs from a fresh render of the trace", found[0])
        check_in("(b) the mark `stage_done.report_problems` reads, and the name it takes out", SD.STALE_MARK, found[0])
        check_eq("(b) ... the name `report_problems` reads is `appendix`", SD.STALE_NAME_RE.search(found[0]).group(1), "appendix")
        check_in("(b) what was expected and the door: `--write`", f"expected exactly what `traceability.py --task T-1 --render` prints under the heading; run `{door}`", found[0])
        check_not_in("(b) the scribe is no door of a block of code", "story_step.py", found[0])
        write(task / "work" / "run-report.json", RUN_REPORT)
        check_eq("(b) CONTROL: the run restored, the appendix is clean again", _appendix_lines(task), [])
        # (c) three rows differ in their Result cell: still ONE line, and `--write` brings the file back to the render
        text = (task / "test-report.md").read_text(encoding="utf-8")
        for rid, word in (("R-2", "wait"), ("R-3", "deferred"), ("R-4", "not planned")):
            check(f"(c) setup: {rid} reads {word}", re.search(rf"\| {rid} \|.*\*\*{word}\*\*", text) is not None, text[-900:])
            _set_report(task, lambda t, rid=rid, word=word: re.sub(rf"(\| {rid} \|.*)\*\*{word}\*\*", r"\1**pass**", t))
        check_eq("(c) three rows differ: ONE line", len(_appendix_lines(task)), 1)
        written = RF.write(task)
        check("(c) `--write` renders the appendix again", written["ok"] and any("replaced the appendix" in l for l in written["lines"]), written)
        check_eq("(c) and the report checks clean", RF.check(task), [])
        check("(c) the bytes it replaced are kept", bool(written["history"]) and Path(written["history"]).is_file(), written)
        # (d) a row the trace no longer has, and one that is absent from the appendix
        _set_report(task, lambda t: t.replace("| R-1 | Cancel | TC-001 |", "| R-1 | Cancel | TC-001<br>Then 9 |"))
        check_eq("(d) a moved row: ONE line", len(_appendix_lines(task)), 1)
        RF.write(task)
        check_eq("(d) `--write` settles it", RF.check(task), [])
        # (d'') a requirement missing from the appendix altogether: the same one line, settled by `--write`
        _set_report(task, lambda t: re.sub(r"\n\| R-4 \|[^\n]*", "", t))
        check_eq("(d'') R-4 stands in no row: ONE line", len(_appendix_lines(task)), 1)
        errors: list = []
        V.check_report_traceability(task / "test-report.md", errors)
        check_in("... and the traceability check still names it", "'R-4'", " ".join(errors))
        RF.write(task)
        check_eq("(d'') `--write` puts the row back", RF.check(task), [])
        # (d''') a surplus row (the case was deleted)
        _set_report(task, lambda t: t.replace("| R-3 |", "| R-1 | gone | TC-009 | — | api | **pass** | x |\n| R-3 |", 1))
        found = _appendix_lines(task)
        check_eq("(d''') a surplus row: ONE line", len(found), 1)
        # a difference outside the Result cells: one line
        RF.write(task)
        _set_report(task, lambda t: t.replace("| R-2 | Paid period |", "| R-2 | Paid period, retyped |", 1))
        found = _appendix_lines(task)
        check_eq("a cell outside Result differs: ONE line", len(found), 1)
        # (i) two rows of one key: one line
        RF.write(task)
        _set_report(task, lambda t: re.sub(r"(\n\| R-2 \|[^\n]*)", r"\1\1", t, count=1))
        found = _appendix_lines(task)
        check_eq("(i) a duplicate key: ONE line", len(found), 1)
        RF.write(task)
        # the body is compared after the heading line, newlines trimmed: blank lines around it are not a difference
        repaste_appendix(task)
        _set_report(task, lambda t: t.replace("## Appendix — traceability\n\n", "## Appendix — traceability\n\n\n\n"))
        check_eq("blank lines between the heading and the table are not a difference", _appendix_lines(task), [])
        # (e) no appendix section: nothing to compare (the slots refuse that)
        _set_report(task, lambda t: t.partition("## Appendix")[0] + "## Retro proposals\n\n- x\n")
        check_eq("(e) no `## Appendix` section: no appendix check", _appendix_lines(task), [])
    finally:
        cleanup(task.parents[2])
    # (f) a trace the factory cannot build is one line, never a pass (FR-59)
    task = fresh()
    saved = T.build
    try:
        def boom(*_a):
            raise RuntimeError("the cases folder is gone")
        T.build = boom
        found = _appendix_lines(task)
        _set_report(task, lambda t: t.replace("| R-2 | Paid period |", "| R-2 | Paid period, retyped |", 1))
        written = RF.write(task)
        check_in("(f) `--write` over a trace that cannot be built leaves the appendix as it is (the hand-made row stays)",
                 "| R-2 | Paid period, retyped |", (task / "test-report.md").read_text(encoding="utf-8"))
        check("(f) ... and says so", any("the appendix was not refreshed: the trace could not be built (RuntimeError" in l for l in written["lines"]), written)
        T.build = saved
        check_eq("(f) T.build raises: one line", len(found), 1)
        check_in("(f) it says why, what was expected and the door", "the appendix could not be compared: RuntimeError: the cases folder is gone - "
                 "expected a trace the factory can build; run `traceability.py --task T-1 --check`", found[0])
    finally:
        T.build = saved
        cleanup(task.parents[2])
    # (g) a legacy report without markers is not checked (P8)
    task = story()
    try:
        legacy_report(task)
        _set_report(task, lambda t: t.replace("| R-1 |", "| R-9 |"))
        notes: list = []
        check_eq("(g) legacy report: [] and the legacy line", (RF.check(task, notes), notes), ([], [G.LEGACY_FACTS_LINE]))
    finally:
        cleanup(task.parents[2])


def fb8_person_content_line_at_and_beyond_cap() -> None:
    """FB-8 (R16, E23): the report line of a `test as is` word names the accepted files (3 named, a 4th counted) and stands IN PLACE
    of the base line of the person-confirmed kinds."""
    task = story()
    try:
        for n, (name, stamp) in enumerate((("3 files", "2026-10-03T09:40:00+00:00"), ("4 files", "2026-10-03T09:50:00+00:00"))):
            files = [f"f{i}.py" for i in range(3 + n)]
            record = _pb_person("api", "test as is, build file", kind="content_accepted")
            record["content_identity"] = record["person_confirmation"]["content"] = "a" * 64
            record["accepted_files"] = files
            _pb_block(task, f"fb{n}", "api", stamp, record)
            found = [ln for ln in RF.render(RF.build(task))["proven"].splitlines() if ln.startswith(RF.PERSON_LINE_LEAD)]
            shown = "f0.py, f1.py, f2.py" + (" and 1 more" if n else "")
            check_eq(f"FB8 (E23): {name}: one line, the files capped at three, the words quoted, and no base line",
                     found, [f"On a build you confirmed, the api tests ran although {shown} on the stand differ from this story's "
                             "(`test as is, build file`, 2026-10-03): a green test proves this story's build only where those files "
                             "do not matter."])
        check_eq("FB8 (R16): the facts carry the kind and the files",
                 (RF.build(task)["person_build"][0]["kind"], RF.build(task)["person_build"][0]["accepted_files"]),
                 ("content_accepted", ["f0.py", "f1.py", "f2.py", "f3.py"]))
    finally:
        cleanup(task.parents[2])


# --- r0107 S6 step 3 (TQ1-20): the branch accounting in the report (keys R-1..R-11) -----------------------------------------
# Mutations (named, not run here; each killed by THIS file, test_report_facts.py):
#   m20 _r_left_branches without `_shown` on `to_check`/`how`                      -> R-8
#   m21 report_facts.check: the `("gate_b", "branches")` exemption back to gate_b   -> R-1 (--check demands a scribe item)
#   m22 left_asks counts `source: branches`                                          -> R-9
#   m26 _requirements ignores `debts` (R shown proven while a branch is owed)        -> R-5
#   m60 _attachments_line: the tail is always "offered at the plan gate"              -> R-10   [was m36 in the spec; clash, t-402]
#   m61 _branch_unit_lines: no `and <k> more`, or a cut at 10 only                   -> R-4 (the limits at 1 and 10000)   [was m37; clash, t-402]

def branch_item(key, kind="branch_lost", req=("R-1",), to_check="including a move into a project that already has one",
                how="no case carries it and nobody left it out: nobody checked it", **more) -> dict:
    return dict({"kind": kind, "kinds": [kind], "ref": key, "item_key": key, "case": "", "requirements": list(req), "tests": [],
                 "to_check": to_check, "how": how, "words": "", "source": "branches", "counts": True}, **more)


def branch_story(items, **kw) -> Path:
    """A story whose ledger holds `items` as `left_items` under `after_checks` (no bug: the third verdict is not a `no`)."""
    gate = {"A": {"authorization_source": GATE_A}}
    return story(pipeline={"ticket": "T-1", "gates": gate}, with_bug=False,
                 extra_ledger=dict(ledger(records=[]), delivery_ready=False, delivery_verdict="after_checks", left_items=items, **kw))


def with_account(result):
    """Replace `branch_accounting.account` (the report's one reader of the branches) by `result` (a dict, or an Exception to raise)."""
    import branch_accounting as BA
    real = BA.account

    def fake(art):
        if isinstance(result, Exception):
            raise result
        return result
    BA.account = fake
    return lambda: setattr(BA, "account", real)


def accounted(records=(), not_obligation=(), left_out=()) -> dict:
    return {"state": "kept", "records": list(records), "not_obligation": list(not_obligation), "left_out": list(left_out)}


def with_limits(**changes):
    import branch_accounting as BA
    real = BA.table
    BA.table = lambda: {**real(), **changes}
    return lambda: setattr(BA, "table", real)


def by_word_record(bn="BN-3", r="R-1", text="the occupied project", question="Q-2") -> dict:
    return {"text": "", "kind": "branch_excluded_by_word", "case": "", "ref": bn, "item_key": bn, "requirements": [r], "to_check": text,
            "how": f"excluded by your answer to {question}", "source": "branches", "question": question}


def a_bug_candidate_reaches_left_with_you() -> None:
    """G2-3 (FR-22): a `bug_candidate` item of the ledger (source `grounding`, no case, keyed by its K-n) is OWED a line in "Left with you":
    `--check` names it when the scribe's section lacks it, and is silent once a line names it with its words. Mutation (named, NOT run,
    killed here): the kind stops counting toward the items the report demands (`delivery_verdict.left_item_is_open`)."""
    gate = {"A": {"authorization_source": GATE_A}}
    how = ("Say at gate B that this needs a bug report (name K-2): the conductor sends it to the failure analyst at S7; "
           "or leave it with you.")
    cand = _item("K-2", "bug_candidate", req=("R-1",), case="", item_key="K-2", source="grounding",
                 to_check="off by one at src/app.py:14 - no plan row names it", how=how)
    task = story(pipeline={"ticket": "T-1", "gates": gate}, with_bug=False,
                 extra_ledger=dict(ledger(records=[]), delivery_ready=False, delivery_verdict="after_checks", left_items=[cand]))
    try:
        legacy_report(task)
        RF.write(task)
        gaps = lambda: [p for p in RF.check(task) if "has no item for" in p]  # noqa: E731
        found = gaps()
        check_eq("G2-3 the report with no line for K-2: --check names exactly it", (len(found), "K-2" in found[0], "bug_candidate" in found[0]), (1, True, True))
        path = task / "test-report.md"
        text = path.read_text(encoding="utf-8")
        start = text.index("## Left with you")
        end = text.index("<!-- facts:regression -->") if "<!-- facts:regression -->" in text else len(text)
        line = ("1. **Off by one at src/app.py:14 (R-1, K-2).** To check: the cap is applied once. There is no test for it. "
                "Needed: say at gate B that this needs a bug report, or check it yourself.\n\n")
        path.write_text(text[:start] + "## Left with you\n\n" + line + text[end:], encoding="utf-8")
        check_eq("G2-3 once a line names K-2 with its words: --check is silent about it", gaps(), [])
        RF.write(task)
        check_in("G2-3 and --write keeps the line (the prune never takes out a candidate)", "K-2", path.read_text(encoding="utf-8"))
        check_eq("G2-3 and --check stays silent after --write", gaps(), [])
    finally:
        cleanup(task.parents[2])


def r_1_to_r_3_blocks() -> None:
    # R-1: a debt: the block names BN and R and what is needed (form E17); a fixture without the block is red
    task = branch_story([branch_item("BN-1")])
    try:
        legacy_report(task)
        RF.write(task)
        text = (task / "test-report.md").read_text(encoding="utf-8")
        block = G.find_blocks(text)["left-branches"][2]
        check_in("R-1 the block opens with its own heading", "### Branches left with you", block)
        check_in("R-1 BN, R, what to check and what is needed, in one E17 line",
                 "- **BN-1** (R-1) — To check: including a move into a project that already has one. Needed: no case carries it "
                 "and nobody left it out: nobody checked it", block)
        check("R-1 the block stands inside `Left with you`, before the regression block",
              text.index("## Left with you") < text.index("<!-- facts:left-branches -->") < text.index("<!-- facts:regression -->"))
        check_eq("R-1 --check passes and asks the scribe for no item of the branch", [p for p in RF.check(task) if "BN-1" in p or "left-branches" in p], [])
        path = task / "test-report.md"
        path.write_text(RF._remove_block(text, "left-branches"), encoding="utf-8")
        found = [p for p in RF.check(task) if "left-branches" in p]
        check_eq("R-1 a report with no block: --check is red, one line", len(found), 1)
        check_in("R-1 ... and names the door", "report_facts.py --task T-1 --write", found[0])
        errors: list = []
        V.check_report_forbidden(task / "test-report.md", errors)
        check_eq("R-1 the validator's forbidden words are clean", errors, [])
        check_eq("R-1 the validator's `Left with you` rule does not take the block for the scribe's items",
                 [e for e in _left_item_errors(text) if "BN-1" in e], [])
    finally:
        cleanup(task.parents[2])
    # R-2: no debt -> no block; a row that does not count -> no block
    for name, items in (("no item", []), ("an item that does not count", [branch_item("BN-1", counts=False)]),
                        ("an item of the ledger's own source", [_item("TC-002")])):
        task = branch_story(items)
        try:
            check_not_in(f"R-2 {name}: no block", "left-branches", " ".join(render_all(task)))
        finally:
            cleanup(task.parents[2])
    # R-3: a story with no section at all renders as before; `missing` is one line; an unreadable record is `Unknown`
    task = story()
    try:
        blocks = render_all(task)
        check_eq("R-3 legacy: neither branch block exists", [n for n in ("left-branches", "branches-not-proven") if n in blocks], [])
        size = blocks["size"]
        check_not_in("R-3 legacy: no attachment, left-out or no-obligation line in the size block", "were left out", size)
        check_not_in("R-3 legacy: no attachments line", "Attachments", size)
    finally:
        cleanup(task.parents[2])
    task = branch_story([branch_item("branches", kind="branches_not_recorded", req=(), to_check="the register has no record of the story's branches",
                                     how="check what the story's qualifiers ask")])
    try:
        body = render_all(task)["left-branches"]
        check_eq("R-3 missing: ONE line", [ln for ln in body.splitlines() if ln.startswith("- ")], [
            "- **the branches of this story** — To check: the register has no record of the story's branches. Needed: check what the story's qualifiers ask"])
    finally:
        cleanup(task.parents[2])
    undo = with_account(RuntimeError("the register is broken"))
    task = branch_story([])
    try:
        body = render_all(task)["left-branches"]
        check_in("R-3 unreadable: `Unknown`, in the form of `_unknown_line`", "Unknown — the record of the story's branches could not be read", body)
        check_not_in("R-3 ... never `all accounted`", "accounted", body)
        check_not_in("R-3 ... and no exception class or path reaches the person", "RuntimeError", body)
    finally:
        undo()
        cleanup(task.parents[2])


def _left_item_errors(text: str) -> list:
    folder = temp_dir("qa-rf-left-")
    try:
        (folder / "test-report.md").write_text(text, encoding="utf-8")
        errors: list = []
        V.check_report_left_with_you(folder / "test-report.md", errors)
        return errors
    finally:
        cleanup(folder)


def r_4_units() -> None:
    def units(n, text="a sentence of the ticket"):
        return [f"{text} {i}" for i in range(n)]
    item = lambda lines: branch_item("ticket-text", kind="source_unreconciled", req=(), lines=lines,          # noqa: E731
                                     to_check=f"{len(lines)} parts of the ticket have no home (description {len(lines)}, criteria 0, comments 0)",
                                     how="read these parts and say whether each asks for something to check")
    for room, long, n, expected_lines, more in ((10, 300, 10, 10, None), (10, 300, 11, 10, "   and 1 more"), (1, 300, 3, 1, "   and 2 more"),
                                                 (10, 10000, 11, 10, "   and 1 more"), (1, 10000, 1, 1, None)):
        undo = with_limits(report_units_shown=room, unit_text_shown=long)
        task = branch_story([item(units(n))])
        try:
            body = render_all(task)["left-branches"]
            rows = [ln for ln in body.splitlines() if ln.startswith("   - ")]
            check_eq(f"R-4 {n} parts at report_units_shown={room}: {expected_lines} separate lines", len(rows), expected_lines)
            check_eq(f"R-4 ... and the rest is counted ({more})", [ln for ln in body.splitlines() if ln.startswith("   and ")], [more] if more else [])
            check_in(f"R-4 ... the head line names the number as the record has it ({n})", f"{n} parts of the ticket have no home (description {n}, criteria 0, comments 0)", body)
        finally:
            undo()
            cleanup(task.parents[2])
    undo = with_limits(report_units_shown=10, unit_text_shown=20)
    long_unit = "x" * 21
    task = branch_story([item([long_unit, "y" * 20])])
    try:
        rows = [ln for ln in render_all(task)["left-branches"].splitlines() if ln.startswith("   - ")]
        check_eq("R-4 a unit over unit_text_shown is cut with the ellipsis, one at the limit stands whole", rows, ["   - " + "x" * 19 + "…", "   - " + "y" * 20])
        ledger_item = json.loads((task / "work" / "ledger.json").read_text(encoding="utf-8"))["left_items"][0]
        check_in("R-4 ... the whole text stays in the ledger's `lines`", long_unit, ledger_item["lines"])
    finally:
        undo()
        cleanup(task.parents[2])


def r_5_to_r_9() -> None:
    # R-5: a requirement with a branch owed is not Proven; the partly words name the branch; check asks no scribe item
    plain = story(with_bug=False)
    owed = branch_story([branch_item("BN-1", req=("R-1",))])
    try:
        before = {i["id"]: i for i in RF.build(plain)["requirements"]["items"]}
        after = {i["id"]: i for i in RF.build(owed)["requirements"]["items"]}
        check_eq("R-5 setup: R-1 is proven without the debt", before["R-1"]["class"], "proven")
        check_eq("R-5 R-1 with a branch owed is class `wait`", after["R-1"]["class"], "wait")
        check_in("R-5 ... and `partly` names the branch", "BN-1 is left with you", " ".join(after["R-1"]["partly"]))
        check_eq("R-5 a requirement the branch does not name stays as it was", after["R-4"]["class"], before["R-4"]["class"])
        legacy_report(owed)
        RF.write(owed)
        check_eq("R-5 --check: no scribe item is demanded for source: branches", [p for p in RF.check(owed) if "has no item for" in p], [])
    finally:
        cleanup(plain.parents[2])
        cleanup(owed.parents[2])
    # R-6: a branch a recorded answer excluded stands in `## Branches not proven` ONLY
    # t-1676 W3: a cut made by the person's QUOTED words has no question: the line says "excluded by your words", never "answer to " + nothing
    quoted = dict(by_word_record(), question="", quote="only the add-to-cart function", words_file="s1.txt")
    undo_quote = with_account(accounted([quoted]))
    quote_task = branch_story([])
    try:
        check_in("W3 quote-form branch line", 'excluded by your words "only the add-to-cart function"', render_all(quote_task)["branches-not-proven"])
        check_not_in("W3 ... and no empty `answer to`", "answer to ", render_all(quote_task)["branches-not-proven"])
    finally:
        undo_quote()
        cleanup(quote_task.parents[2])
    undo = with_account(accounted([by_word_record()]))
    task = branch_story([])
    try:
        blocks = render_all(task)
        check_in("R-6 the named block", "- BN-3 (R-1) the occupied project: excluded by your answer to Q-2", blocks["branches-not-proven"])
        check_not_in("R-6 ... and the branch stands in no other block", "BN-3", "".join(b for n, b in blocks.items() if n != "branches-not-proven"))
        check_not_in("R-6 `left-branches` does not exist for it", "left-branches", " ".join(blocks))
        legacy_text = legacy_report(task)
        converted = RF._convert(legacy_text, False)
        check_eq("R-6 conversion: no `left-branches` or `branches-not-proven` marker", [n for n in ("left-branches", "branches-not-proven") if f"facts:{n}" in converted], [])
        RF.write(task)
        check_eq("R-6 --write then --check: nothing about the block", [p for p in RF.check(task) if "branches" in p], [])
    finally:
        undo()
        cleanup(task.parents[2])
    # R-7: not_obligation named by a count line at N > 0; the machine keys never reach the person
    undo = with_account(accounted(not_obligation=[(2, "a greeting"), (1, "a thanks")]))
    task = branch_story([branch_item("ticket-text", kind="source_unreconciled", req=(), lines=["a part"], to_check="1 parts of the ticket have no home (description 1, criteria 0, comments 0)",
                                     how="read it"),
                         branch_item("test-candidates", kind="source_unreconciled", req=(), lines=["C-2"], to_check="1 existing tests were not walked for branches", how="check what these tests already prove"),
                         branch_item("branches", kind="branches_not_recorded", req=(), to_check="the register has no record", how="check")])
    try:
        blocks = render_all(task)
        check_in("R-7 the count line in `size` at N > 0", "3 parts of the ticket were read as no obligation: a greeting, a thanks.", blocks["size"])
        body = blocks["left-branches"]
        for key in ("ticket-text", "test-candidates", "**branches**"):
            check_not_in(f"R-7 the machine key `{key}` is not in the text a person reads", key, body)
        for words in ("the ticket text", "the existing tests", "the branches of this story"):
            check_in(f"R-7 ... its words are: {words}", words, body)
    finally:
        undo()
        cleanup(task.parents[2])
    undo = with_account(accounted(not_obligation=[]))
    task = branch_story([])
    try:
        check_not_in("R-7 N = 0: no such line", "no obligation", render_all(task)["size"])
    finally:
        undo()
        cleanup(task.parents[2])
    # R-8: a spelling the validator refuses is cut BEFORE the line; all cut -> the sentence that sends the person to the source
    hostile = branch_item("BN-1", to_check="network/ingress is closed for multi_tenant", how="see work/log.txt and cv_ab12 first")
    gone = branch_item("BN-2", to_check="work/x", how="ti_ab12", req=("R-4",))
    task = branch_story([hostile, gone])
    try:
        legacy_report(task)
        RF.write(task)
        text = (task / "test-report.md").read_text(encoding="utf-8")
        body = G.find_blocks(text)["left-branches"][2]
        # the shape reader (validate_artifacts.report_id_shape_hit, AR-13) flags a `work/` path, a `cv_`/`ti_` + 4 hex digits hash and the
        # summary marker, on a word boundary: `network/ingress` and `multi_tenant` are not those shapes and stay; `work/log.txt` and `cv_ab12` go
        check_in("R-8 the words that pass stay (network/ingress, multi_tenant); a `work/` path and a `cv_` hash go", "To check: network/ingress is closed for multi_tenant. Needed: see and first", body)
        check_not_in("R-8 ... the words that fail are not there", "cv_ab12", body)
        check_in("R-8 all cut: the wording is in the ticket", "the wording is in the ticket; find it by the branches of this story", body)
        errors: list = []
        V.check_report_forbidden(task / "test-report.md", errors)
        check_eq("R-8 the whole report passes check_report_forbidden", errors, [])
        check_eq("R-8 report_facts.check is clean on the block", [p for p in RF.check(task) if "left-branches" in p], [])
    finally:
        cleanup(task.parents[2])
    # R-9: the branch items are not asked of the person under `Open questions`
    task = branch_story([branch_item("BN-1"), branch_item("attachment:form.png", kind="attachment_question_open")])
    try:
        check_eq("R-9 left_asks does not count them", RF.build(task)["questions"]["left_asks"], 0)
        check_not_in("R-9 the heading carries no `asked under`", "asked under", render_all(task)["open-questions"])
        mixed = branch_story([branch_item("BN-1"), _item("TC-002")])
        try:
            check_eq("R-9 pair: a ledger item beside them is still counted", RF.build(mixed)["questions"]["left_asks"], 1)
        finally:
            cleanup(mixed.parents[2])
    finally:
        cleanup(task.parents[2])


def r_10_11_size_and_pictures() -> None:
    import gate_brief as GB
    real = GB.attachments_data

    def view(names, before, key="T-1", known=True, named="same"):
        named = before if named == "same" else named
        return lambda art: {"state": "known", "known": True, "tickets": [{"key": key, "known": known, "reason": "", "items": [
            {"name": n, "opened": False, "cause": "left out"} for n in names]}], "total": len(names), "before": before, "named": named}

    def size_of(task, data, decided):
        GB.attachments_data = data
        if decided is not None:
            write(task / "state" / "controller.json", {"source_revision": "r1", "decisions": {"d": {"gate": "A", "status": "approved", "source_revision": "r1"}} if decided else {}})
        try:
            return render_all(task)["size"]
        finally:
            GB.attachments_data = real
    for name, names, before, decided, expect in (
            ("offered", ["a.png", "b.pdf"], ["T-1: a.png", "T-1: b.pdf"], True,
             "Attachments were not turned into requirements: 2 (a.png, b.pdf). They were offered to you at the plan gate."),
            ("arrived later", ["a.png", "b.pdf"], ["T-1: a.png"], True,
             "Attachments were not turned into requirements: 2 (a.png, b.pdf). 1 arrived after that gate and were not offered: T-1: b.pdf."),
            ("gate not reached", ["a.png"], None, False, "Attachments were not turned into requirements: 1 (a.png). They were not offered: the plan gate was not reached."),
            ("no record of the show", ["a.png"], None, True,
             "Attachments were not turned into requirements: 1 (a.png). Whether the plan gate's message named them is not recorded."),
            # N-3: the record holds the whole list, the packet named 15 of 16; the report reads what was NAMED, never the whole list
            ("16 files, the packet named 15", ["f%d.png" % i for i in range(16)], ["T-1: f%d.png" % i for i in range(16)], True,
             "1 arrived after that gate and were not offered: T-1: f15.png."),
            ("a not-known packet named none", ["a.png"], ["T-1: a.png"], True, "1 arrived after that gate and were not offered: T-1: a.png."),
            ("an old record with no named list", ["a.png"], ["T-1: a.png"], True, "Whether the plan gate's message named them is not recorded.")):
        task = story(with_bug=False)
        try:
            named = {"16 files, the packet named 15": ["T-1: f%d.png" % i for i in range(15)], "a not-known packet named none": [],
                     "an old record with no named list": None}.get(name, "same")
            body = size_of(task, view(names, before, named=named), decided)
            check_in(f"R-10 the tail `{name}`", expect, body)
            for word in ("checked", "verified"):
                check_not_in(f"R-10 `{word}` is never said of an attachment", word, body)
        finally:
            cleanup(task.parents[2])
    task = story(with_bug=False)
    try:
        body = size_of(task, view(["n%d.png" % i for i in range(12)], ["T-1: n%d.png" % i for i in range(12)]), True)
        check_in("R-10 at most report_units_shown names, then `and <k> more`", "(n0.png, n1.png, n2.png, n3.png, n4.png, n5.png, n6.png, n7.png, n8.png, n9.png, and 2 more)", body)
        body = size_of(task, view(["network/map.png"], ["T-1: network/map.png"]), True)
        check_in("R-10 a name with `network/` is not a forbidden shape (the shape reader's boundary), so `_shown` keeps it", "network/map.png", body)
        body = size_of(task, view(["work/map.png"], ["T-1: work/map.png"]), True)
        check_not_in("R-10 (control) a name that IS the `work/` shape is cut by `_shown`", "work/map.png", body)
        report_path = task / "test-report.md"
        legacy_report(task)
        GB.attachments_data = view(["network/map.png"], ["T-1: network/map.png"])
        try:
            write(task / "state" / "controller.json", {"source_revision": "r1", "decisions": {}})
            RF.write(task)
        finally:
            GB.attachments_data = real
        errors: list = []
        V.check_report_forbidden(report_path, errors)
        check_eq("R-10 check_report_forbidden is clean with `network/` in a name", errors, [])
        body = size_of(task, lambda art: {"state": "unreadable", "known": False, "reason": "the list of the story's sources cannot be read", "tickets": [], "total": 0}, None)
        check_in("R-10 a list that cannot be read: not known, said", "Attachments: not known (the list of the story's sources cannot be read).", body)
        check_eq("R-10 no attachments: the same bytes as a story that keeps no list", size_of(task, view([], None), None),
                 size_of(task, lambda art: {"state": "absent"}, None))
    finally:
        cleanup(task.parents[2])
    undo = with_account(accounted(left_out=[("TP1-9", "not relevant"), ("TP1-10", "excluded")]))
    task = story(with_bug=False)
    try:
        check_in("R-10 the left-out tickets (amendment 2.3), never read as reconciled",
                 "2 linked tickets were left out and not reconciled: TP1-9 (not relevant), TP1-10 (excluded).", render_all(task)["size"])
    finally:
        undo()
        cleanup(task.parents[2])
    # R-11: a picture that disagrees is a line of the block, not a count of Open questions
    task = branch_story([branch_item("attachment:form work/x.png", kind="attachment_question_open", to_check="R-1 against form.png",
                                     how="the file and the requirement disagree; nobody has said which is right")])
    try:
        blocks = render_all(task)
        check_in("R-11 the picture line, its name through `_shown`", "- **the file form** (R-1) — To check: R-1 against form.png. Needed: the file and the requirement disagree",
                 blocks["left-branches"])
        check_not_in("R-11 not in the count of Open questions", "asked under", blocks["open-questions"])
    finally:
        cleanup(task.parents[2])


def red_test_is_not_not_probed() -> None:
    """RD1-20 (1): a RED test with no proof level is counted under its own words, not as "not probed" (CART-1: "18 not probed"
    over 17 green and one red). A red test with a level stays on it; no red tests: the line is what it was."""
    import delivery_summary as S
    import proof_level as PL

    def line_of(rows):
        task = story(extra_ledger=ledger(rows=rows))
        try:
            summary = S.build(task)
            return summary["proof_levels"], S.proof_levels_line(summary["proof_levels"], summary["not_required_reasons"])
        finally:
            cleanup(task.parents[2])
    green = [test_row(f"g{i}", level="none", reason="") for i in range(17)]
    counts, text = line_of(green + [test_row("r1", state="failed:APP_BUG", level="none", reason="")])
    check_eq("17 green and 1 red with no level: the red is its own count", counts, {"none": 17, "probe_not_applicable_red": 1})
    check_in("the line says 17 not probed", f"{PL.words(None)}: 17", text)
    check_in("and the red words once", f"{PL.red_words()}: 1", text)
    check_eq("the words are the vocabulary's", PL.red_words(), "probe not applicable: red")
    counts, text = line_of(green[:2] + [test_row("r1", state="failed:APP_BUG", level="live", reason="")])
    check_eq("a red test with a reached level stays on the level", counts, {"none": 2, "live": 1})
    check_not_in("and no red words", PL.red_words(), text)
    counts, _ = line_of(green[:2] + [test_row("r1", state="waived:failed:APP_BUG", level="none", reason="")])
    check_eq("a waiver wrapper is taken off before the test (as the ledger facts read it)", counts, {"none": 2, "probe_not_applicable_red": 1})
    counts, text = line_of(green)
    check_eq("no red test: today's count", counts, {"none": 17})
    check_not_in("and today's line", PL.red_words(), text)


def coverage_owner_in_the_verdict() -> None:
    """RD1-21: the factory's `coverage:` reasons are a behaviour no test proves, said apart from its bookkeeping; the count of
    "open only in the factory's own records" does not grow with the owner; a reason no rule placed says so."""
    import ledger as L
    cov = {"code": L.COVERAGE_GAP_CODE, "entity": "OB-1", "owner": "factory", "detail": "coverage: OB-1 — evidence incomplete", "refs": ["TC-001"]}
    book = {"code": "FACTORY_DEFECT", "entity": "x", "owner": "factory", "detail": "factory: a row the reducer could not join"}
    prod = {"code": "TRACEABILITY_GAP", "entity": "R-2", "owner": "product", "detail": "traceability: R-2 has no terminal outcome (waits)"}
    line = L.factory_coverage_line(1)
    both = story(extra_ledger=ledger(records=[prod, cov, book]))
    try:
        facts = RF.build(both)
        check_eq("the ledger facts carry the count and the code of each record", (facts["ledger"]["factory_coverage"],
                 [r["code"] for r in facts["ledger"]["records"]]), (1, ["TRACEABILITY_GAP", L.COVERAGE_GAP_CODE, "FACTORY_DEFECT"]))
        verdict = RF.render(facts)["verdict"]
        check_in("the bookkeeping sentence counts only the bookkeeping (2 factory reasons, 1 of them coverage)",
                 "1 open reason in the checks is the factory's own bookkeeping", verdict)
        check_in("and the unproven behaviour is told in the ledger's own words", line + ".", verdict)
    finally:
        cleanup(both.parents[2])
    only = story(extra_ledger=ledger(records=[cov]))
    try:
        verdict = RF.render(RF.build(only))["verdict"]
        check_not_in("a coverage-only factory list has no bookkeeping sentence", "factory's own bookkeeping", verdict)
        check_in("but says the behaviour stays unproven", line, verdict)
    finally:
        cleanup(only.parents[2])
    unowned = story(extra_ledger=ledger(records=[prod, dict(book, detail="some new check: z", owner="product", owner_established=False)]))
    try:
        facts = RF.build(unowned)
        check_eq("an unestablished owner is listed by its detail", facts["ledger"]["unowned"], ["some new check: z"])
        check_in("and the verdict says it", "owner not established: some new check: z.", RF.render(facts)["verdict"])
    finally:
        cleanup(unowned.parents[2])
    # the residual head (`_verdict`): bookkeeping and coverage are separate parts
    led = {"word": "no", "ready": False, "owners": {"factory": 3}, "limit_windows": 0, "items": [], "reds": [], "entities": [],
           "factory_coverage": 2}
    residual = RF._verdict({"ledger": led, "requirements": None, "bugs": None, "tests": None})["first_reason_full"]
    check_in("the residual names the 1 bookkeeping reason", "1 that are the factory's own bookkeeping", residual)
    check_in("and the 2 unproven behaviours", L.factory_coverage_line(2), residual)
    only_cov = RF._verdict({"ledger": dict(led, owners={"factory": 2}), "requirements": None, "bugs": None, "tests": None})["first_reason_full"]
    check_not_in("no bookkeeping part when every factory reason is coverage", "bookkeeping", only_cov)
    # `_count_bookkeeping`: the owner change does not grow "open only in the factory's own records", with the case id in the text or without
    items = [{"class": "unproven", "id": "R-1", "plan_row": "TS-1", "cases": ["TC-001"]}]
    for label, refs in (("with the case in the text", ["TC-001"]), ("without it", [])):
        reqs = {"counts": {}, "items": [dict(i) for i in items]}
        RF._count_bookkeeping(reqs, {"records": [{"owner": "factory", "entity": "OB-1", "refs": refs, "code": L.COVERAGE_GAP_CODE,
                                                  "execution": False}]}, {})
        check_eq(f"a coverage record does not make a requirement bookkeeping {label}", reqs["counts"]["bookkeeping"], 0)
    reqs = {"counts": {}, "items": [dict(i) for i in items]}
    RF._count_bookkeeping(reqs, {"records": [{"owner": "factory", "entity": "x", "refs": ["TC-001"], "code": "FACTORY_DEFECT",
                                              "execution": False}]}, {})
    check_eq("the control: a bookkeeping record still does", reqs["counts"]["bookkeeping"], 1)
    # the summary fragment (delivery_summary.render): no reassurance over an unproven behaviour
    import delivery_summary as S
    summary = {"counts": {}, "gaps": [], "bugs": [], "blocked_by": ["factory"], "factory_coverage_gaps": 1,
               "reasons_by_owner": {"factory": ["coverage: OB-1 — x"]}}
    check_not_in("the fragment does not say the product is fine", "Nothing here says the product is not ready", S.render(summary))
    check_in("the control: without the count it does", "Nothing here says the product is not ready", S.render(dict(summary, factory_coverage_gaps=0)))


G25_TABLE = """schema_version: 1
implementation_source: diff
refactoring_share:
  measure: changed_production_lines
  refactoring: 6
  unclassified: 0
  total: 20
  percent: 30.0
  road: none
  mixed_hunks:
    - H-2
  outside_files:
    - tests/test_cart.py
  pseudo_files:
    - src/old_name.py
requirement_coverage:
  implemented: 1
  partial: 0
  n: 2
  unknown: 0
  percent: 50.0
  road: highlight
  outside:
    - r: R-2
      state: not_implemented
orphans:
  - id: G-9
    was: old row
blast_radius:
  index:
    state: present
  areas:
    - id: B-1
      key: repo:src/cart.ts
      language: ts
      truncated: yes
      touched:
        file: src/cart.ts
"""


def g2_5_what_the_change_touches() -> None:
    """G2-5: the Size block carries the refactoring share, the coverage and the rest of what the table saved, in a person's words; and the
    delivery check records a `not_implemented` requirement as `pending_implementation` with no word of the person. Mutations named, NOT run,
    each killed by this file: the records written only after the stop word (the no-word check); a pending item listed in Left with you (the
    verdict check); `n/a` hidden (the unknown-share check)."""
    import check_delivery as D
    import delivery_verdict as DV
    import grounding_table as GT
    import human_text
    task = story()
    try:
        none_facts = RF.build(task)
        check_eq("G2-5 a story with no table has no grounding fact and no line", (none_facts["grounding"], RF._r_grounding(none_facts), "grounding" in none_facts["unknown"]), (None, "", False))
        check_eq("G2-5 ... and its Size block is what it was", RF.render(none_facts)["size"], RF._r_size(none_facts))
        (task / "work" / "grounding.yaml").write_bytes(G25_TABLE.encode("utf-8"))
        facts = RF.build(task)
        body = RF.render(facts)["size"]
        text = RF._r_grounding(facts)
        check("G2-5 the lines end the Size block", body.endswith(text) and body.startswith("## Size"))
        check_in("G2-5 the share is printed BELOW the notify mark too (a line of the report, never of the gate)", "Refactoring share: 30.0% of 20 changed production lines — no card was needed.", text)
        check_in("G2-5 the part-refactoring blocks", "1 changed block is part refactoring and part change of behaviour", text)
        check_in("G2-5 the files outside the measure and the ones with no changed line", "Files outside the measure (tests, documents, generated): tests/test_cart.py.", text)
        check_in("G2-5 ... renames", "Files with no changed line (renames, mode changes): src/old_name.py.", text)
        check_in("G2-5 the coverage names the requirement left out", "Requirement coverage: 1 of 2 (50.0%); not covered: R-2 (not implemented).", text)
        check_in("G2-5 the orphans are counted", "1 record of an earlier version of the table is kept and not counted.", text)
        check_in("G2-5 the cut caller list", "1 changed file was measured on a cut list of its callers: src/cart.ts.", text)
        check_in("G2-5 the name-search language", "language other than Python were measured by name search only: ts.", text)
        check_eq("G2-5 the words obey the shape rules of a report (AR-16)", human_text.problems(text, kind="report"), [])
        for machine in ("K-", "B-1", "refactoring_share", "requirement_coverage", "outside_diff", "mixed_hunks", "work/"):
            check_not_in(f"G2-5 no machine word `{machine}`", machine, text)
        check_not_in("G2-5 the regression is not touched: no regression word", "egression", text)
        # n/a is printed; a share the table never saved is said; an unknown road is a gap of the factory
        (task / "work" / "grounding.yaml").write_bytes(b"schema_version: 1\nimplementation_source: diff\nrefactoring_share:\n  percent: n/a\n  road: unknown\n  reason: a hunk has an empty mark\n")
        got = RF._r_grounding(RF.build(task))
        check_in("G2-5 n/a is printed", "Refactoring share: n/a — could not be measured (a hunk has an empty mark); a gap of the factory.", got)
        check_in("G2-5 a coverage the table does not hold is said", "Requirement coverage: not measured", got)
        (task / "work" / "grounding.yaml").write_bytes(b"schema_version: 1\nimplementation_source: diff\nrequirement_coverage:\n  n: 0\n  road: stop\n  reading: nothing_asked\n")
        check_in("G2-5 a share the table does not hold is said", "Refactoring share: not measured", RF._r_grounding(RF.build(task)))
        check_in("G2-5 nothing asked of the change", "no requirement of the story is left for this change to implement", RF._r_grounding(RF.build(task)))
        # off a diff: the source of the null outcome; a table nobody can read: one Unknown line, never silence
        (task / "work" / "grounding.yaml").write_bytes(b"schema_version: 1\nimplementation_source: ungrounded\nnull_outcome:\n  source: ungrounded\n  words: This story records no implementation to read.\n")
        check_in("G2-5 no diff: the null outcome's source", "no implementation diff was read for this story (ungrounded). This story records no implementation to read.", RF._r_grounding(RF.build(task)))
        (task / "work" / "grounding.yaml").write_bytes(b"schema_version: 1\n\timplementation_source: diff\n")
        broken = RF.build(task)
        check_in("G2-5 an unreadable table is one Unknown line", "Unknown what the change touches — ", RF._r_grounding(broken))
        check_eq("G2-5 ... and an entry in unknown", "grounding" in broken["unknown"], True)

        # the delivery side: a requirement of N the table calls not_implemented is a record WITHOUT the person's word
        (task / "work" / "grounding.yaml").write_bytes(b"schema_version: 1\nimplementation_source: diff\nrequirements:\n  - r: R-1\n    state: implemented\n"
                                                      b"  - r: R-2\n    state: not_implemented\n    question: Is it built?\n")
        real = GT.coverage_of(task)
        check_eq("G2-5 the control: the real coverage leaves R-2 out as not_implemented (R-3, R-4 have no line: absent, no record)",
                 [(o["r"], o["state"]) for o in real["outside"]], [("R-2", "not_implemented"), ("R-3", "absent"), ("R-4", "absent")])
        recs = D.grounding_records(task, {"rows": []}, {})
        check_eq("G2-5 the record: kind, ref, source, case, and the text the spec gives",
                 [(r["kind"], r["ref"], r["source"], r["case"], r["text"]) for r in recs],
                 [("pending_implementation", "R-2", "grounding", "", "grounding: R-2 is required by the story and this change does not implement it")])
        check_eq("G2-5 ... with no word of the person, the verdict is `no`, owner product, and the item is not Left with you",
                 (DV.decide([r["kind"] for r in recs])[0], DV.verdict_of_kind("pending_implementation"), DV.counts("pending_implementation")), ("no", "no", False))
        check_eq("G2-5 ... and the text has an owner family (FR-19)", (D.reason_family(recs[0]["text"]) is not None, D.reason_owner(recs[0]["text"])), (True, "product"))
        real_cov, real_digest, real_word = GT.coverage_of, GT.coverage_digest, GT.stop_word
        try:
            cov = lambda outside: (lambda root: {"outside": outside})            # noqa: E731
            outside = [{"r": "R-2", "state": "not_implemented"}, {"r": "R-3", "state": "outside_diff"}, {"r": "R-4", "state": "unknown"}, {"r": "R-5", "state": "absent"}]
            GT.coverage_of, GT.coverage_digest, GT.stop_word = cov(outside), (lambda root, c: "abc"), (lambda pipeline, prefix, digest: None)
            check_eq("G2-5 no word: only not_implemented (outside_diff with where none waits for the word; unknown and absent give none)",
                     [r["ref"] for r in D.grounding_records(task, {"rows": []}, {})], ["R-2"])
            GT.stop_word = lambda pipeline, prefix, digest: {"decision": "go on"}
            check_eq("G2-5 a word for the current digest: the outside_diff with where none is the same record",
                     [r["ref"] for r in D.grounding_records(task, {"rows": []}, {})], ["R-2", "R-3"])
            GT.coverage_of = cov([{"r": "R-6", "state": "partial"}])
            check_eq("G2-5 a partial gives no record", D.grounding_records(task, {"rows": []}, {}), [])

            def boom(root):
                raise RuntimeError("the register moved")
            GT.coverage_of = boom
            thrown = D.grounding_records(task, {"rows": []}, {})
            check_eq("G2-5 coverage_of that raises is ONE factory_record, never `nothing to say`", [(r["kind"], "register moved" in r["text"]) for r in thrown], [("factory_record", True)])
            GT.coverage_of = lambda root: {"road": "unknown", "reason": "the policy cannot be read", "outside": []}
            unknown = D.grounding_records(task, {"rows": []}, {})
            check_eq("G2-5 F-2: coverage_of that RETURNS road unknown (the ordinary way to fail) is ONE factory_record with its reason, never `nothing to say`",
                     [(r["kind"], "the policy cannot be read" in r["text"]) for r in unknown], [("factory_record", True)])
        finally:
            GT.coverage_of, GT.coverage_digest, GT.stop_word = real_cov, real_digest, real_word
        (task / "work" / "grounding.yaml").write_bytes(b"schema_version: 1\nimplementation_source: ungrounded\nnull_outcome:\n  source: ungrounded\n  words: x\n")
        check_eq("G2-5 a story with no diff gets no pending record", D.grounding_records(task, {"rows": []}, {}), [])
    finally:
        cleanup(task.parents[2])


def one_bug_many_manifestations_in_the_report() -> None:
    """t-2187 N3a (5.9, 8.3): `_r_bugs` prints, under a bug that shows in 2+ ways, its cause (how it was confirmed, in words), EVERY way
    (none cut), the claims nobody verified as "Not verified:" and a possible same cause by the NUMBER of another row; a bug with one way
    and no link prints byte-for-byte what it printed before the keys existed (golden); no file name and no field name in any line."""
    def rec(i, title, cases, **over):
        base = {"id": i, "title": title, "severity": "minor", "state": "unconfirmed", "confirmation": "unconfirmed", "reproduced_how": [],
                "reproduction_problems": [], "requirements": ["R-8"], "cases": cases, "homes": [], "filing": None, "gate_b_not_chosen": False,
                "gate_b_words": ""}
        return dict(base, **over)

    def facts(*records):
        return {"bugs": {"records": list(records), "confirmed": 0, "reproduced": 0, "unconfirmed": len(records), "unreadable": 0,
                         "outside_home": [], "sources": []}, "unknown": {}}
    ways = [f"way {n}; start: state {n}; seen: {n}" for n in range(1, 8)]
    cause = {"status": "confirmed", "statement": "the field replaces it with 1.", "why": "", "by_code": True, "runs": 2, "by_person": False,
             "unverified": ["pasting -1 behaves like typing it"]}
    old = RF._r_bugs(facts(rec("qty", "Quantity changes", ["TC-1"])))
    key_free = {k: v for k, v in rec("qty", "Quantity changes", ["TC-1"]).items()}
    check_eq("R-N3a golden: a bug with the new keys empty prints the same bytes as a bug without them", old,
             RF._r_bugs(facts(dict(key_free, manifestations=[], cause={}, same_cause_as=[], draft_names=[]))))
    check_in("R-N3a ... and that is the old row line, alone under its heading", "1. **minor · R-8 · TC-1** — Quantity changes (qty) (unconfirmed", old)
    one = RF._r_bugs(facts(rec("qty", "Quantity changes", ["TC-1"], manifestations=ways[:1], cause=cause)))
    check_eq("R-N3a one way, whatever the cause says: no new line", one, old)
    merged = RF._r_bugs(facts(rec("qty", "Quantity changes", ["TC-1"], manifestations=ways, cause=cause, draft_names=["qty-coerced"]),
                              rec("cart", "Cart keeps one digit", ["TC-2"], same_cause_as=["qty-coerced"], draft_names=["cart-digit"])))
    lines = merged.splitlines()
    first = next(i for i, ln in enumerate(lines) if ln.startswith("1. "))
    check_eq("R-N3a the cause line, how it was confirmed (code and two starting states, the count as a word like the packet)", lines[first + 1],
             "   One cause (by the line of the application code that does it and by trying it from two starting states): the field replaces it with 1.")
    check_eq("R-N3a every one of 7 ways has its line, none cut", lines[first + 2: first + 10], ["   Shows as:"] + [f"   - {w}" for w in ways])
    check_eq("R-N3a the unverified claim is said as not verified", lines[first + 10], "   Not verified: pasting -1 behaves like typing it.")
    check_eq("R-N3a m1 the first bug shows the link too: the cart draft names it, so each row names the other", lines[first + 11],
             "   Possibly the same cause as 2 (not verified).")
    check_eq("R-N3a the second bug names the first by its row number, not by a file", lines[first + 13], "   Possibly the same cause as 1 (not verified).")
    check_not_in("R-N3a no file name in the text", ".json", merged)
    check_not_in("R-N3a no draft stem in a link line", "qty-coerced", merged)
    # the cause that does not stand, is unverified or unknown, and a link to a row that is not in the report
    for label, change, said in (
            ("not standing", {"status": "unknown", "why": "the evidence behind it could not be re-read"},
             "   Cause not established: the evidence behind it could not be re-read."),
            ("the person's word", {"by_code": False, "runs": 0, "by_person": True}, "   One cause (on your word at gate B): the field replaces it with 1."),
            ("unverified", {"status": "unverified", "why": "only one start state was run"}, "   Possibly one cause (not verified: only one start state was run): the field replaces it with 1."),
            ("unknown", {"status": "unknown", "why": "no access to the code", "statement": ""}, "   Cause not established: no access to the code."),
            ("no word", {"status": "", "why": ""}, "   Cause not established."),
            ("a code line only", {"runs": 0}, "   One cause (by the line of the application code that does it): the field replaces it with 1."),
            ("runs only, one state", {"by_code": False, "runs": 1}, "   One cause (by trying it from one starting state): the field replaces it with 1.")):
        text = RF._r_bugs(facts(rec("qty", "Quantity changes", ["TC-1"], manifestations=ways[:2], cause=dict(cause, **change))))
        check_in(f"R-N3a cause {label}", said + "\n", text)
        if label in ("not standing", "unverified", "unknown", "no word"):
            check_not_in(f"R-N3a cause {label}: never the line of a confirmed cause", "One cause (", text)
    dangling = RF._r_bugs(facts(rec("cart", "Cart keeps one digit", ["TC-2"], same_cause_as=["no-such-draft"])))
    check_not_in("R-N3a a link to a draft that is no row of the report prints nothing", "Possibly", dangling)
    selfish = RF._r_bugs(facts(rec("qty", "Quantity changes", ["TC-1"], same_cause_as=["qty"], draft_names=["qty"])))
    check_not_in("R-N3a a bug is never said to share a cause with itself", "Possibly", selfish)


def pc_10_sides_measure() -> None:
    """t-2181 §8 (PC-10): `facts["sides_measure"]` carries the counters of a story with a sides record, read through the existing readers.
    KILLS: an unknown printed as 0 (the manifest, the controller record, the journal, the ledger each absent); a key on a story with no sides
    record (old stories stay byte-stable); a second parser of the provisional rows or of the journal."""
    import driver_journal as DJ
    sides = {"ui": {"reality": "real", "deliverable": True}, "backend": {"reality": "substituted", "deliverable": False}}
    plain = story()
    try:
        before = RF.build(plain)
        check_not_in("PC-10 a story with no sides record has no sides counters key", "sides_measure", sorted(before))
        blocks_before = RF.render(before)
        check_not_in("PC-10 ... and the JSON of the facts does not name it", "sides_measure", json.dumps(before, default=str))
    finally:
        cleanup(plain.parents[2])
    task = story(pipeline={"ticket": "T-1", "size": None, "gates": {"A": {"authorization_source": GATE_A}},
                           "stage_overrides": [{"stage": "S2", "match": "size", "decision": "test it as one story"}], "sides": sides})
    try:
        facts = RF.build(task)
        measure = facts["sides_measure"]
        check_eq("PC-10 the report's blocks are byte-stable when only the sides record is added", RF.render(facts), blocks_before)
        check_eq("PC-10 no provisional rows: 0 of 0, measured (the manifest was read)", measure["provisional"],
                 {"settled_matched": 0, "total": 0, "by_status": {}, "skipped": 0})
        check_in("PC-10 test_body_edits_at_bind has no producer: unmeasured with its why", "unmeasured: ", measure["test_body_edits_at_bind"])
        check_in("PC-10 green_after_bind_only has no producer: unmeasured with its why", "unmeasured: ", measure["green_after_bind_only"])
        check_in("PC-10 no controller record: phase 2 unmeasured, not 0", "unmeasured: ", measure["phase2_cost"])
        check_in("PC-10 ... and phase 1 too", "unmeasured: ", measure["phase1_cost"])
        check_in("PC-10 ... and the conductor's cost", "unmeasured: ", measure["conductor_cost"])
        check_eq("PC-10 no sides_unknown flag: False, carried", measure["sides_unknown"], False)
        check_eq("PC-10 a ledger with no sides state counts 0 and 0 (measured)", (measure["on_substitute_count"], measure["sides_unknown_count"]), (0, 0))
        check_eq("PC-10 the non-real side is named, read through story_sides", measure["non_real_sides"], ["backend"])
        check_eq("PC-10 no hold: awaiting none", measure["awaiting"], {"state": "none", "since": ""})
        # the manifest: two provisional rows, one settled_matched; one malformed row is counted as skipped, never as a row
        manifest = dict(MANIFEST, provisional=[{"id": "P-1", "status": "settled_matched"}, {"id": "P-2", "status": "open"}, "junk"])
        write(task / "work" / "automation-manifest.json", manifest)
        check_eq("PC-10 provisional: 1 settled_matched of 2, 1 row skipped",
                 RF.build(task)["sides_measure"]["provisional"],
                 {"settled_matched": 1, "total": 2, "by_status": {"open": 1, "settled_matched": 1}, "skipped": 1})
        # phase 2: dispatches by cause `source_arrived` or purpose `bind`; phase 1 = the dispatches made before the first of them
        def controller(extra=None):
            records = {
                "S5-qa-automator-1": {"id": "S5-qa-automator-1", "stage": "S5", "dispatched_seq": 1},
                "S1-qa-scout-2": {"id": "S1-qa-scout-2", "stage": "S1", "repair_cause": "source_arrived", "dispatched_seq": 5},
                "S5-qa-automator-3": {"id": "S5-qa-automator-3", "stage": "S5", "dispatched_seq": 6,
                                      "request_binding": {"purpose": "bind"}},
                "S6-qa-executor-4": {"id": "S6-qa-executor-4", "stage": "S6", "dispatched_seq": 7}}
            records.update(extra or {})
            write(task / "state" / "controller.json", {"dispatches": records})

        def journal(jrows):
            (task / "state" / DJ.JOURNAL_NAME).write_text("".join(json.dumps(r) + "\n" for r in jrows), encoding="utf-8")

        def row(dispatch, session, cost, role="qa-automator"):
            return {"kind": "dispatch", "role": role, "dispatch": dispatch, "session_id": session, "total_cost_usd": cost}

        controller()
        rows = [row("S5-qa-automator-1", "s1", 1.0), row("S1-qa-scout-2", "s2", 0.5, "qa-scout"), row("S5-qa-automator-3", "s3", 0.25),
                row("S6-qa-executor-4", "s4", 2.0), row("", "s5", 0.1, "conductor")]
        journal(rows)
        got = RF.build(task)["sides_measure"]
        check_eq("PC-10 phase 2 is the two arrival dispatches' journal cost", got["phase2_cost"], {"dispatches": 2, "cost_usd": 0.75})
        check_eq("PC-10 phase 1 is the dispatches BEFORE the first phase-2 one: the S6 dispatch after the bind round is not in it",
                 got["phase1_cost"], {"dispatches": 1, "cost_usd": 1.0})
        check_eq("PC-10 the conductor's pair is in neither phase: it is carried apart, in the same shape",
                 got["conductor_cost"], {"dispatches": 0, "cost_usd": 0.1})
        rows[1]["total_cost_usd"] = "n/a"
        journal(rows)
        got = RF.build(task)["sides_measure"]
        check_in("PC-10 a pair whose cost the journal marks unknown makes phase 2 unmeasured, not a smaller sum", "unmeasured: ", got["phase2_cost"])
        check_eq("PC-10 ... and phase 1, whose pairs are all known, stays measured", got["phase1_cost"], {"dispatches": 1, "cost_usd": 1.0})
        # F1: an empty journal, a phase-2 dispatch with no pair, a phase-1 dispatch with no pair: unknown, never 0
        journal([])
        got = RF.build(task)["sides_measure"]
        check_in("PC-10 F1 an empty journal: phase 2 is absent with its reason, not $0", "absent: the driver journal names no session", got["phase2_cost"])
        check_in("PC-10 F1 ... phase 1 unmeasured, not $0", "unmeasured: ", got["phase1_cost"])
        check_in("PC-10 F1 ... the conductor unmeasured, not $0", "unmeasured: ", got["conductor_cost"])
        journal([row("S5-qa-automator-1", "s1", 1.0), row("S6-qa-executor-4", "s4", 2.0)])
        got = RF.build(task)["sides_measure"]
        check_in("PC-10 F1 a phase-2 dispatch with no journal pair: unmeasured, naming it", "S1-qa-scout-2", got["phase2_cost"])
        check_in("PC-10 F1 ... unmeasured, not '0 dispatches'", "unmeasured: ", got["phase2_cost"])
        journal([row("S1-qa-scout-2", "s2", 0.5, "qa-scout"), row("S5-qa-automator-3", "s3", 0.25)])
        got = RF.build(task)["sides_measure"]
        check_in("PC-10 F1 a phase-1 dispatch with no journal pair: phase 1 unmeasured, naming it", "S5-qa-automator-1", got["phase1_cost"])
        check_eq("PC-10 F1 NEGATIVE control: the same journal with its phase-2 pairs present keeps phase 2 measured",
                 got["phase2_cost"], {"dispatches": 2, "cost_usd": 0.75})
        # F2: a per-call root (one session's total falls) is not money, as factory_dashboard.journal_records reads it
        journal([row("S5-qa-automator-1", "s1", 1.0), row("S5-qa-automator-1", "s1", 0.5),
                 row("S1-qa-scout-2", "s2", 0.3, "qa-scout"), row("S1-qa-scout-2", "s2", 0.8, "qa-scout"),
                 row("S5-qa-automator-3", "s3", 0.25), row("S6-qa-executor-4", "s4", 2.0)])
        got = RF.build(task)["sides_measure"]
        check_in("PC-10 F2 a per-call root: phase 1 is unmeasured, not the 0.5 of a falling total", "unmeasured: ", got["phase1_cost"])
        check_in("PC-10 F2 ... phase 2 too (session s2 has several rows under a falling root)", "unmeasured: ", got["phase2_cost"])
        # F3: a record with no integer dispatched_seq makes phase 1 unmeasured
        controller({"S6-qa-executor-4": {"id": "S6-qa-executor-4", "stage": "S6"}})
        journal([row("S5-qa-automator-1", "s1", 1.0), row("S1-qa-scout-2", "s2", 0.5, "qa-scout"), row("S5-qa-automator-3", "s3", 0.25),
                 row("S6-qa-executor-4", "s4", 2.0)])
        got = RF.build(task)["sides_measure"]
        check_in("PC-10 F3 a dispatch with no sequence: phase 1 unmeasured", "a dispatch has no sequence", got["phase1_cost"])
        check_eq("PC-10 F3 ... phase 2 is still measured", got["phase2_cost"], {"dispatches": 2, "cost_usd": 0.75})
        # F3 edge: a story with no phase-2 dispatch: phase 2 absent with its reason, phase 1 is every dispatch
        write(task / "state" / "controller.json", {"dispatches": {
            "S5-qa-automator-1": {"id": "S5-qa-automator-1", "stage": "S5", "dispatched_seq": 1},
            "S6-qa-executor-4": {"id": "S6-qa-executor-4", "stage": "S6", "dispatched_seq": 2}}})
        journal([row("S5-qa-automator-1", "s1", 1.0), row("S6-qa-executor-4", "s4", 2.0)])
        got = RF.build(task)["sides_measure"]
        check_in("PC-10 F3 no phase-2 dispatch: the counter is absent with its reason", "absent: the story has no phase-2 dispatch", got["phase2_cost"])
        check_eq("PC-10 F3 ... phase 1 is every dispatch", got["phase1_cost"], {"dispatches": 2, "cost_usd": 3.0})
        # F4: the cause is read through controller.repair_cause: a word outside REPAIR_CAUSES is not `source_arrived`
        controller({"S6-qa-executor-4": {"id": "S6-qa-executor-4", "stage": "S6", "dispatched_seq": 7, "repair_cause": "source_arrived_x"}})
        journal([row("S5-qa-automator-1", "s1", 1.0), row("S1-qa-scout-2", "s2", 0.5, "qa-scout"), row("S5-qa-automator-3", "s3", 0.25),
                 row("S6-qa-executor-4", "s4", 2.0)])
        check_eq("PC-10 F4 a cause word outside controller.REPAIR_CAUSES is not phase 2",
                 RF.build(task)["sides_measure"]["phase2_cost"], {"dispatches": 2, "cost_usd": 0.75})
        controller()
        # the ledger's own state words, and the verdict the calibration check reads
        write(task / "work" / "ledger.json", ledger(rows=[
            {"ref": "TS-1", "kind": "plan_row", "state": "not_verified:on_substitute", "detail": "TS-1"},
            {"ref": "TS-2", "kind": "plan_row", "state": "not_verified:sides_unknown", "detail": "TS-2"},
            {"ref": "TS-3", "kind": "plan_row", "state": "not_verified:on_substitute", "detail": "TS-3"},
            test_row()]))
        got = RF.build(task)["sides_measure"]
        check_eq("PC-10 on_substitute and sides_unknown plan rows are counted", (got["on_substitute_count"], got["sides_unknown_count"]), (2, 1))
        check_eq("PC-10 the verdict word is the ledger's (not ready here)", got["verdict"], "no")
        (task / "work" / "ledger.json").unlink()
        got = RF.build(task)["sides_measure"]
        check_in("PC-10 no ledger: the counts are unmeasured, not 0", "unmeasured: ", got["on_substitute_count"])
        check_in("PC-10 ... both of them", "unmeasured: ", got["sides_unknown_count"])
        (task / "work" / "automation-manifest.json").write_text("{not json", encoding="utf-8")
        check_in("PC-10 an unreadable manifest: provisional unmeasured", "unmeasured: ", RF.build(task)["sides_measure"]["provisional"])
        (task / "work" / "automation-manifest.json").unlink()
        check_in("PC-10 an absent manifest: provisional unmeasured", "unmeasured: ", RF.build(task)["sides_measure"]["provisional"])
        # F5: sides_unknown alone is a record and is carried; an unreadable side table reads unmeasured, not []
        flagged = story(pipeline={"ticket": "T-1", "sides_unknown": True})
        try:
            got = RF.build(flagged)["sides_measure"]
            check_eq("PC-10 F5 sides_unknown with no sides record: the flag is carried", got["sides_unknown"], True)
            check_eq("PC-10 F5 ... and the default side is real, so no non-real side is claimed", got["non_real_sides"], [])
            import contract as C
            saved = C.SIDE_REALITIES_PATH
            C.SIDE_REALITIES_PATH = Path(flagged) / "no-such-table.json"
            try:
                got = RF.build(flagged)["sides_measure"]
                check_in("PC-10 F5 an unreadable side-realities table: non_real_sides unmeasured, not []", "unmeasured: ", got["non_real_sides"])
            finally:
                C.SIDE_REALITIES_PATH = saved
        finally:
            cleanup(flagged.parents[2])
        # F4 negative control: the default side alone is not a sides record (no key)
        bare = story(pipeline={"ticket": "T-1"})
        try:
            check_not_in("PC-10 F4 the default side alone is not a sides record", "sides_measure", sorted(RF.build(bare)))
        finally:
            cleanup(bare.parents[2])
        # a hold alone is a sides record: the hold is read through contract.awaiting
        held = story(pipeline={"ticket": "T-1", "awaiting": {"since": "2026-11-01T10:00:00", "stopped": True}})
        try:
            check_eq("PC-10 a stopped hold is read, since carried", RF.build(held)["sides_measure"]["awaiting"],
                     {"state": "stopped", "since": "2026-11-01T10:00:00"})
        finally:
            cleanup(held.parents[2])
    finally:
        cleanup(task.parents[2])


# --- FL-8 (t-2277): the price and the USE of the first look and of the registry --------------------------------------------------
# KILLS: an unknown counted as 0 (briefs, journal, homes, probes, gate A each absent); a counter that refuses or judges; a second reader of
# the usage; a zero-question line without its counter-metrics; an "unread" finding on a null or absent record.

FL8_STARTED = "2026-11-05T09:00:00+00:00"       # the fixture story's start
FL8_ROW_AT = "2026-11-01T10:00:00+00:00"        # a registry row recorded before it
FL8_ROWS = [
    {"req": "R-1", "status": "confirms", "why": "the Pay button is under the total", "evidence": ["work/evidence/manual/survey-R-1/a1/001.txt"],
     "quote": "Pay",
     "path": {"url": "/cart", "steps": ["open the cart"], "locators": [{"what": "Pay button", "selector": "button#pay", "seen": "yes"}],
              "api": [{"method": "GET", "path": "/api/cart", "auth": "none", "seen": "yes",
                       "sample": {"request": "GET /api/cart", "status": "200", "response": "total 12"}}],
              "stand_needs": ["a seeded cart", "a user with a card"]}},
    {"req": "R-2", "status": "missing", "blocked_by": "product", "why": "the discount field is not on the page",
     "path": {"locators": [{"what": "discount field", "selector": "input#code", "seen": "no"}], "stand_needs": ["a coupon"]}}]


def fl8_story(rows=None, pipeline=None, home=None, record=True, **frame):
    """A story with a first-look record of the CURRENT keys (so it is not stale); `home` is the text of the S5 test file the manifest names."""
    import first_look as FL
    import grounding_table as GT
    task = story(pipeline=pipeline)
    started = json.loads((task / "pipeline.json").read_text(encoding="utf-8"))
    if "created_at" not in started:           # the story's start: the registry rows a story KNEW are those recorded before it (B3)
        write(task / "pipeline.json", dict(started, created_at=FL8_STARTED))
    if record:
        heads, reg_hash = FL.current_keys(task)
        body = {"walk": "w1", "stand": "dev", "stand_build": "not_established", "source_head": json.loads(heads), "register_hash": reg_hash,
                "rows": FL8_ROWS if rows is None else rows, "gaps": ["the discount screen was not found"]}
        body.update(frame)
        GT.write_yaml(task / "work" / "first-look.yaml", body)
    if home is not None:
        write(task.parents[2] / "tests" / "api" / "test_a.py", home)
    return task


def fl8_briefs(task: Path, **by_dispatch) -> None:
    for name, text in by_dispatch.items():
        write(task / "work" / "briefs" / f"{name.replace('_', '-')}.md", text)


def fl8_controller(task: Path, dispatches: dict) -> None:
    write(task / "state" / "controller.json", {"dispatches": dispatches})


def fl8_journal(task: Path, rows: list) -> None:
    import driver_journal as DJ
    (task / "state" / DJ.JOURNAL_NAME).write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def fl8_registry_role(task: Path, role: str = "auditor", at: str = None) -> None:
    """A known role recorded BEFORE the story began (`at`, default FL8_ROW_AT; "" leaves the row with no time)."""
    import project_knowledge as PK
    row, problem, _ = PK.record(task.parents[2], key=PK.ROLES_KEY, environment="", element=role, state="known", scope="project",
                                value={"sign_in": "account"}, words="the person said so", source="person", story="T-0", by="conductor")
    assert row is not None, problem
    fl8_row_time(task, row["id"], FL8_ROW_AT if at is None else at)


def fl8_row_time(task: Path, pk_id: str, at: str) -> None:
    """Set (or, for "", remove) the `at` of a registry row: `PK.record` stamps now, which is after every fixture story's start."""
    path = task.parents[2] / "qa-factory" / "records" / "project-knowledge.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    for fact in data["facts"]:
        if fact["id"] == pk_id:
            if at:
                fact["at"] = at
            else:
                fact.pop("at", None)
    path.write_text(json.dumps(data), encoding="utf-8")


def fl8_strategist_form(task: Path, roles: list) -> None:
    fl8_controller(task, {"S3-qa-test-strategist-1": {"id": "S3-qa-test-strategist-1", "stage": "S3", "role": "qa-test-strategist",
                                                      "status": "accepted"}})
    body = "scope:\n  - id: R-1\n" + ("product_roles:\n" + "".join(f"  - role: {r}\n    sign_in: account\n" for r in roles) if roles else "product_roles: []\n")
    write(task / "work" / "handoffs" / "S3-qa-test-strategist-1.yaml", body)


def first_look_cost_from_story_journal() -> None:
    task = fl8_story()
    try:
        dispatch = {"id": "S1-qa-scout-1", "stage": "S1", "dispatched_seq": 1, "request_binding": {"purpose": "first_look"}}
        other = {"id": "S3-qa-test-strategist-2", "stage": "S3", "dispatched_seq": 2}
        row = lambda d, s, c: {"kind": "dispatch", "role": "r", "dispatch": d, "session_id": s, "total_cost_usd": c}   # noqa: E731
        check_in("FL-8 no controller record: the cost is unmeasured, not 0", "unmeasured: ", RF.build(task)["first_look_measure"]["cost"])
        fl8_controller(task, {"S3-qa-test-strategist-2": other})
        check_in("FL-8 a story with no first-look dispatch: absent with its reason", "absent: the story has no first-look dispatch",
                 RF.build(task)["first_look_measure"]["cost"])
        fl8_controller(task, {"S1-qa-scout-1": dispatch, "S3-qa-test-strategist-2": other})
        check_in("FL-8 no driver journal: unmeasured, not $0", "unmeasured: the story has no driver journal", RF.build(task)["first_look_measure"]["cost"])
        fl8_journal(task, [row("S1-qa-scout-1", "s1", 0.5), row("S3-qa-test-strategist-2", "s2", 4.0)])
        check_eq("FL-8 the cost is the journal's pair of the first-look dispatch ALONE", RF.build(task)["first_look_measure"]["cost"],
                 {"dispatches": 1, "cost_usd": 0.5})
        fl8_journal(task, [row("S3-qa-test-strategist-2", "s2", 4.0)])
        check_in("FL-8 a first-look dispatch with no journal pair: unmeasured, naming it", "S1-qa-scout-1", RF.build(task)["first_look_measure"]["cost"])
        fl8_journal(task, [row("S1-qa-scout-1", "s1", "n/a"), row("S3-qa-test-strategist-2", "s2", 4.0)])
        check_in("FL-8 a pair of unknown cost: unmeasured, not a smaller sum", "unmeasured: ", RF.build(task)["first_look_measure"]["cost"])
    finally:
        cleanup(task.parents[2])


def first_look_share_and_answers_counted() -> None:
    import first_look as FL
    task = fl8_story()
    try:
        got = RF.build(task)["first_look_measure"]
        check_eq("FL-8 the share is first_look.share's (1 of 2 reachable, the floor 30)", got["share"], {"reachable": 1, "counted": 2, "share": 50.0, "floor": 30})
        check_in("FL-8 no attempt: whether the question was asked is unmeasured, not False", "unmeasured: ", got["questions"]["dead_asked"])
        check_in("FL-8 the same-code question has no carrier on this build: unmeasured", "unmeasured: ", got["questions"]["same_code_asked"])
        check_eq("FL-8 no word of the person: none", got["questions"]["answer"], "none")
        FL.begin(task, "w1", "dev")
        check_eq("FL-8 an attempt that was not marked: the question was not asked", RF.build(task)["first_look_measure"]["questions"]["dead_asked"], False)
        FL.mark_asked(task)
        check_eq("FL-8 the attempt marked asked: counted", RF.build(task)["first_look_measure"]["questions"]["dead_asked"], True)
        heads, reg_hash = FL.current_keys(task)
        write(task / "pipeline.json", {"ticket": "T-1", "first_look_continue": {"source_head": heads, "register_hash": reg_hash}})
        check_eq("FL-8 the word `continue` for these keys is counted as continue", RF.build(task)["first_look_measure"]["questions"]["answer"], "continue")
        write(task / "pipeline.json", {"ticket": "T-1", "awaiting": {"cause": "first_look_stop", "held_from": "S3", "since": "2026-11-01T10:00:00"}})
        check_eq("FL-8 a first_look_stop hold is counted as stop", RF.build(task)["first_look_measure"]["questions"]["answer"], "stop")
        (task / "work" / "first-look.yaml").write_text("garbage: [\n", encoding="utf-8")
        check_in("FL-8 an unreadable record: the share is unmeasured, not 0%", "unmeasured: ", RF.build(task)["first_look_measure"]["share"])
    finally:
        cleanup(task.parents[2])


def first_look_attempt_outcome_counted() -> None:
    import first_look as FL
    task = fl8_story()
    try:
        check_in("FL-8 no attempt: the outcome is unmeasured", "unmeasured: ", RF.build(task)["first_look_measure"]["attempt"])
        FL.begin(task, "w1", "dev")
        check_eq("FL-8 a walk opened: walking, no failure", RF.build(task)["first_look_measure"]["attempt"], {"outcome": "walking", "open_failures": 0})
        FL.end(task, "open_failed")
        check_eq("FL-8 an open that failed is counted", RF.build(task)["first_look_measure"]["attempt"], {"outcome": "open_failed", "open_failures": 1})
        FL.end(task, "written")
        check_eq("FL-8 the written outcome", RF.build(task)["first_look_measure"]["attempt"]["outcome"], "written")
    finally:
        cleanup(task.parents[2])


def use_locators_and_routes_in_s5_homes_counted() -> None:
    task = fl8_story()
    try:
        u1 = lambda: RF.build(task)["first_look_measure"]["use"]["u1_locators_and_routes_in_s5_homes"]      # noqa: E731
        check_in("FL-8 u1 CONTROL: the manifest names a test file that cannot be read: unmeasured, not 0", "unmeasured: ", u1())
        write(task.parents[2] / "tests" / "api" / "test_a.py", "def test_a():\n    page.click('button#pay')\n")
        check_eq("FL-8 u1 a seen locator in the home counts, an unseen one (seen: no) and a route not in it do not",
                 u1(), {"locators_seen": 1, "locators_found": 1, "routes_seen": 1, "routes_found": 0, "found": 1})
        write(task.parents[2] / "tests" / "api" / "test_a.py", "def test_a():\n    page.click('button#pay')\n    api.get('/api/cart')\n    page.fill('input#code')\n")
        check_eq("FL-8 u1 the route stands in an API client string too (a string compare); `input#code` was seen: no, so it is not counted",
                 u1()["found"], 2)
        write(task / "work" / "automation-manifest.json", {"tests": []})
        check_in("FL-8 u1 a manifest naming no home: unmeasured", "unmeasured: ", u1())
    finally:
        cleanup(task.parents[2])


def use_s4_cases_citing_walked_path_counted() -> None:
    task = fl8_story(home="x")
    try:
        u2 = lambda: RF.build(task)["first_look_measure"]["use"]["u2_cases_citing_the_walked_path"]       # noqa: E731
        check_eq("FL-8 u2 cases are read and none cites the walked path: 0 (measured)", u2(), 0)
        case = task / "work" / "test-cases" / "billing" / "TC-001.md"
        case.write_text(case.read_text(encoding="utf-8") + "\nStep: open the cart (first_look:R-1)\n", encoding="utf-8")
        check_eq("FL-8 u2 one case cites first_look:R-1", u2(), 1)
        for path in (task / "work" / "test-cases").rglob("*.md"):
            path.unlink()
        check_in("FL-8 u2 no case file at all: unmeasured, not 0", "unmeasured: ", u2())
    finally:
        cleanup(task.parents[2])


def use_probes_on_seen_elements_counted_or_unmeasured() -> None:
    import investigation_probe as IP
    task = fl8_story(home="x")
    real = IP.capture_lines
    try:
        u3 = lambda: RF.build(task)["first_look_measure"]["use"]["u3_probes_on_seen_elements"]      # noqa: E731
        check_in("FL-8 u3 no S5 probe record keeps the selector: unmeasured NAMING the missing S5 carrier, not 0",
                 "unmeasured: no S5 automator probe record keeps the probe's selector", u3())
        calls = []
        def seen_by_s7(t):
            calls.append(t)
            return [{"selector": "button#pay"}, {"selector": "input#code"}]
        IP.capture_lines = seen_by_s7
        check_in("FL-8 u3 F4: S7 investigation captures that DO keep a selector are never read under an S5 label - still unmeasured",
                 "unmeasured: no S5 automator probe record", u3())
        check_eq("FL-8 u3 F4: ... and the S7 capture reader was not called", calls, [])
    finally:
        IP.capture_lines = real
        cleanup(task.parents[2])


def unread_record_is_finding_line() -> None:
    task = fl8_story(home="def test_a():\n    pass\n")
    try:
        facts = RF.build(task)
        lines = RF.finding_lines(facts)
        check_in("FL-8 zero by u1 and u2 over a non-empty record: a finding line, not a refusal", "The first-look record was not read", lines)
        check_eq("FL-8 ... and `check` has no problem of its own for it", [p for p in RF.check(task) if "first-look" in p.lower()], [])
        case = task / "work" / "test-cases" / "billing" / "TC-001.md"
        case.write_text(case.read_text(encoding="utf-8") + "\nStep: (first_look:R-1)\n", encoding="utf-8")
        check_not_in("FL-8 CONTROL: one case cites the path: no unread line", "was not read", RF.finding_lines(RF.build(task)))
        case.write_text(case.read_text(encoding="utf-8").replace("(first_look:R-1)", ""), encoding="utf-8")
        write(task.parents[2] / "tests" / "api" / "test_a.py", "x")
        (task.parents[2] / "tests" / "api" / "test_a.py").unlink()
        check_not_in("FL-8 an UNMEASURED u1 (the home cannot be read) is not zero: no unread line", "was not read", RF.finding_lines(RF.build(task)))
    finally:
        cleanup(task.parents[2])


def null_record_no_unread_finding() -> None:
    import grounding_table as GT
    task = fl8_story(record=False)
    try:
        check_eq("FL-8 a story with no first look at all has no measure key and no table", ("first_look_measure" in RF.build(task), RF.retro_lines(RF.build(task))),
                 (False, []))
        GT.write_yaml(task / "work" / "first-look.yaml", {"null": "no_stand", "rows": [], "gaps": ["no stand is named"]})
        facts = RF.build(task)
        check_eq("FL-8 a null record: its rows are 0 (declared), its gap line is counted", (facts["first_look_measure"]["record"]["rows"], facts["first_look_measure"]["gaps"]), (0, 1))
        check_not_in("FL-8 a null record gives no `unread` finding line", "was not read", RF.finding_lines(facts))
        (task / "work" / "first-look.yaml").unlink()
        import first_look as FL
        FL.begin(task, "w1", "dev")
        facts = RF.build(task)
        check_eq("FL-8 an absent record beside an attempt: no unread line, the counts are unmeasured, not 0",
                 ("was not read" in "\n".join(RF.finding_lines(facts)), facts["first_look_measure"]["gaps"].startswith("unmeasured: ")), (False, True))
        (task / "work" / "first-look.yaml").write_text("garbage: [\n", encoding="utf-8")
        facts = RF.build(task)
        check_in("FL-8 an unreadable record is a gap line, not a crash", "could not be read", RF.finding_lines(facts))
        check_in("FL-8 ... and its stand needs are unmeasured", "unmeasured: ", facts["first_look_measure"]["stand_needs"])
    finally:
        cleanup(task.parents[2])


def stand_needs_and_gaps_are_read() -> None:
    task = fl8_story(home="x")
    try:
        got = RF.build(task)["first_look_measure"]
        check_eq("FL-8 the record's `stand_needs` have a reader: 2 + 1 named", got["stand_needs"], 3)
        check_eq("FL-8 the record's `gaps` have a reader: 1 named", got["gaps"], 1)
        check_in("FL-8 the retro lines show both", "stand needs named 3; gaps named 1", RF.retro_lines(RF.build(task)))
    finally:
        cleanup(task.parents[2])


def counts_never_refuse() -> None:
    task = story()
    try:
        before = RF.check(task)
        facts_before = RF.build(task)
        check_not_in("FL-8 an older story's facts carry no counters (byte-stable)", "knowledge_use", json.dumps(facts_before, default=str))
    finally:
        cleanup(task.parents[2])
    task = fl8_story(home="def test_a():\n    pass\n")
    try:
        fl8_registry_role(task)
        (task.parents[2] / "qa-factory" / "records" / "project-knowledge.json").write_text("{not json", encoding="utf-8")
        facts = RF.build(task)
        check_in("FL-8 an unreadable registry is named, never a crash and never an empty table", "cannot be read", "; ".join(facts["knowledge_use"]["problems"]))
        check_eq("FL-8 the counters change nothing `check` says (the same problem lines with a record, a registry and no briefs)", RF.check(task), before)
        check_eq("FL-8 the facts of the counters are plain JSON", json.loads(json.dumps(facts, default=str))["first_look_measure"]["record"]["kind"], "ok")
    finally:
        cleanup(task.parents[2])


def knowledge_use_counts_registry_and_first_look_in_one_table() -> None:
    task = fl8_story(home="page.click('button#pay')")
    try:
        fl8_registry_role(task)
        fl8_briefs(task, S3_qa_test_strategist_1="[knowledge:product.roles]\n- R-1 confirms: x [first-look:R-1]\n")
        facts = RF.build(task)
        use = facts["knowledge_use"]
        check_eq("FL-8 ONE table: the registry role and both first-look rows", [(e["source"], e["key"]) for e in use["entries"]],
                 [("registry", "product.roles"), ("first_look", "R-1"), ("first_look", "R-2")])
        check_eq("FL-8 the facts carry knowledge_use's own return (no second count)", use, RF.knowledge_use(task, task.parents[2]))
        row = {e["key"]: e for e in use["entries"] if e["source"] == "first_look"}
        check_eq("FL-8 R-1: reached the strategist, used (its locator stands in the home)", (row["R-1"]["reached"], row["R-1"]["used"]), (["qa-test-strategist"], True))
        check_eq("FL-8 R-2: in no brief, its parts all measured zero", (row["R-2"]["reached"], row["R-2"]["used"]), ([], False))
        check_in("FL-8 the retro table has a line per knowledge", "- first_look R-1: reached qa-test-strategist; used", RF.retro_lines(facts))
        src = (Path(RF.__file__)).read_text(encoding="utf-8")
        check_eq("FL-8 AR-13: the usage has ONE reader function in the file", src.count("\ndef knowledge_use("), 1)
    finally:
        cleanup(task.parents[2])


def known_role_reached_strategist_and_case_critic() -> None:
    task = fl8_story(home="x")
    try:
        fl8_registry_role(task)
        fl8_briefs(task, S3_qa_test_strategist_1="roster\n- auditor [knowledge:product.roles]\n",
                   S4_qa_case_critic_1="roster\n- auditor [knowledge:product.roles]\n", S4_qa_case_designer_1="no roster here\n",
                   S4_qa_case_critic_1_decisions="[knowledge:product.roles] a side file is not a brief\n")
        entry = RF.knowledge_use(task)["entries"][0]
        check_eq("FL-8 the known role reached the strategist AND the case critic, not the designer", entry["reached"], ["qa-case-critic", "qa-test-strategist"])
    finally:
        cleanup(task.parents[2])


def known_credential_not_reasked_counts_used() -> None:
    import gate_preflight as GP
    import project_knowledge as PK
    task = fl8_credential_story()
    try:
        used = lambda: [e["used"] for e in RF.knowledge_use(task)["entries"] if e["key"] == PK.ACCOUNTS_KEY]       # noqa: E731
        check_in("FL-8 F5: no driver state (a conductor-run story): unmeasured, never `used`", "unmeasured: the story has no driver state", used()[0])
        fl8_shown_gaps(task, None)
        check_in("FL-8 F5: a driver state that never showed gate A: unmeasured", "unmeasured: gate A was not shown yet", used()[0])
        fl8_shown_gaps(task, [])
        check_eq("FL-8 F5: gate A shown with no card of the known pair: not asked again, counted USED", used(), [True])
        fl8_shown_gaps(task, [{"id": GP.role_gap_id("dev", "another"), "case_id": "TC-1", "cases": ["TC-1"]}])
        check_eq("FL-8 F5: a card of ANOTHER role on that stand does not count as asking about this pair", used(), [True])
        fl8_shown_gaps(task, [{"id": GP.role_gap_id("dev", "auditor"), "case_id": "TC-1", "cases": ["TC-1"]}])
        check_eq("FL-8 F5 CONTROL: gate A SHOWED the card of that pair (asked again, even if answered `go on`): not used", used(), [False])
        write(task / "pipeline.json", {"ticket": "T-1", "created_at": FL8_STARTED, "gates": {"A": {"authorization_source": "Gate A: approved, go on."}}})
        check_eq("FL-8 F5: the words do not matter, the SHOWN card does (the error does not go toward the good outcome)", used(), [False])
    finally:
        cleanup(task.parents[2])


def fl8_credential_story() -> Path:
    """A story whose project knows the account pair dev / auditor (config + registry row recorded before the story's start)."""
    import project_knowledge as PK
    task = fl8_story(record=False)
    root = task.parents[2]
    cfg_path = root / "qa-factory" / "config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    cfg["environments"] = [{"name": "dev", "base_url": "http://x", "credentials_by_role": {"auditor": "QA_A_EMAIL / QA_A_PASSWORD"}}]
    write(cfg_path, cfg)
    write(root / PK.RECORD_REL, {"schema_version": 1, "facts": [
        {"id": "PK-1", "key": PK.ACCOUNTS_KEY, "environment": "dev", "element": "auditor", "state": "known", "scope": "stand", "value": None,
         "provenance": {"source": "person", "words": "w", "story": "S-1", "by": "conductor", "where": ""}, "at": FL8_ROW_AT}]})
    return task


def fl8_shown_gaps(task: Path, gaps) -> None:
    """The driver's record of what gate A SHOWED (`state/driver-state.json` `shown_gaps.A.gaps`); None = a state that shows no gate A."""
    write(task / "state" / "driver-state.json", {"shown_gaps": {} if gaps is None else {"A": {"gaps": gaps, "covered": []}}})


def a_used_credential_is_not_a_fact_that_missed_the_decision() -> None:
    """B1: the account mark lives in the gate-A note, never in a brief - a USED pair read as `in no brief` was a false finding on every
    story of a project with a known account and kept briefs."""
    import gate_preflight as GP
    import project_knowledge as PK
    task = fl8_credential_story()
    try:
        fl8_shown_gaps(task, [])
        fl8_briefs(task, S3_qa_test_strategist_1=f"- auditor [knowledge:product.roles]\nnote {GP.ACCOUNT_MARK}\n")
        check_eq("FL-8 B1: the producer's own token names the registry's key by ONE normalisation",
                 RF._key_of_mark(GP.ACCOUNT_MARK.strip("[]").split(":", 1)[1]), PK.ACCOUNTS_KEY)
        check_eq("FL-8 B1: ... a full key is itself, an unknown token matches nothing", (RF._key_of_mark(PK.ROLES_KEY), RF._key_of_mark("sides")),
                 (PK.ROLES_KEY, "sides"))
        entry = [e for e in RF.knowledge_use(task)["entries"] if e["key"] == PK.ACCOUNTS_KEY][0]
        check_eq("FL-8 B1: used, its reach has no brief carrier: unmeasured with the reason", (entry["used"], entry["reached"]),
                 (True, "unmeasured: " + RF.NO_ACCOUNT_REACH))
        facts = RF.build(task)
        check_eq("FL-8 B1: a used credential gives NO `did not reach a decision` line", [l for l in RF.finding_lines(facts) if "credentials" in l], [])
        metrics = facts["knowledge_use"]["counter_metrics"]
        check_eq("FL-8 B1: ... and counter-metric (2) is 0 beside kept briefs", (metrics["known_not_reached"], metrics["known_not_reaching_a_decision"]), (0, 0))
        fl8_shown_gaps(task, [{"id": GP.role_gap_id("dev", "auditor"), "case_id": "TC-1", "cases": ["TC-1"]}])
        check_eq("FL-8 B1 CONTROL: asked again at gate A (not used), its reach still unmeasured: no `did not reach` line either",
                 [l for l in RF.finding_lines(RF.build(task)) if "credentials" in l], [])
    finally:
        cleanup(task.parents[2])


def an_unreadable_registry_makes_the_counter_metric_unmeasured_not_zero() -> None:
    """B2 (AR-28, FR-41): `known facts no brief carried: 0` beside a registry that could not be read is the very case the counter-metrics expose."""
    task = fl8_story(home="x")
    try:
        fl8_registry_role(task)
        fl8_briefs(task, S3_qa_test_strategist_1="- auditor [knowledge:product.roles]\n")
        registry = task.parents[2] / "qa-factory" / "records" / "project-knowledge.json"
        good = registry.read_text(encoding="utf-8")
        registry.write_text("{not json", encoding="utf-8")
        facts = RF.build(task)
        metrics = facts["knowledge_use"]["counter_metrics"]
        check_eq("FL-8 B2: unreadable registry + kept briefs: the three counters are `unmeasured`, not 0",
                 [str(metrics[k]).startswith("unmeasured: ") for k in ("known_not_reached", "available_unused", "known_not_reaching_a_decision")],
                 [True, True, True])
        check_in("FL-8 B2: ... naming the registry problem", "cannot be read", metrics["known_not_reached"])
        line = RF.question_count_line(0, facts)
        check_in("FL-8 B2: `zero questions` is printed WITH the unmeasured counter-metric", "Questions put to the person: 0; known facts no brief carried: unmeasured: ", line)
        check_in("FL-8 B2: the retro table says the registry was not read", "- unmeasured: ", "\n".join(RF.retro_lines(facts)))
        registry.write_text(json.dumps({"schema_version": 1, "facts": []}), encoding="utf-8")
        empty = RF.build(task)["knowledge_use"]
        check_eq("FL-8 B2 CONTROL: a registry that reads and holds no row is a MEASURED zero, not unmeasured",
                 (empty["problems"], empty["counter_metrics"]["known_not_reached"]), ([], 0))
        registry.write_text(good, encoding="utf-8")
        check_eq("FL-8 B2 CONTROL: the readable registry with the role in a brief is measured 0",
                 RF.build(task)["knowledge_use"]["counter_metrics"]["known_not_reached"], 0)
    finally:
        cleanup(task.parents[2])


def a_fact_the_story_taught_is_not_one_it_ignored() -> None:
    """B3: a registry fact is known to the story only if the registry recorded it BEFORE the story's start."""
    task = fl8_story(record=False)
    try:
        fl8_registry_role(task, "auditor", at="2026-11-06T10:00:00+00:00")           # recorded AFTER the story began (this story taught it)
        fl8_briefs(task, S3_qa_test_strategist_1="roster written before the row existed\n")
        facts = RF.build(task)
        check_eq("FL-8 B3: a row recorded after the story began is no entry and gives no `did not reach` line, and no key",
                 ("knowledge_use" in facts, RF.finding_lines(facts)), (False, []))
        fl8_registry_role(task, "guest")                                               # recorded before it
        facts = RF.build(task)
        check_eq("FL-8 B3: ... a row recorded BEFORE the start is an entry (the key appears)",
                 [e["element"] for e in facts["knowledge_use"]["entries"]], ["guest"])
        check_in("FL-8 B3: ... and, in no brief, a finding line naming it ALONE", "A known fact did not reach a decision: product.roles guest was in no brief",
                 RF.finding_lines(facts))
        check_not_in("FL-8 B3: ... never the one this story taught", "auditor", "\n".join(RF.finding_lines(facts)))
    finally:
        cleanup(task.parents[2])
    task = story()          # an older story: no first look; the project gained a registry LATER
    try:
        import project_knowledge as PK
        row, problem, _ = PK.record(task.parents[2], key=PK.ROLES_KEY, environment="", element="auditor", state="known", scope="project",
                                    value={"sign_in": "account"}, words="w", source="person", story="T-9", by="conductor")
        assert row is not None, problem
        write(task / "pipeline.json", dict(json.loads((task / "pipeline.json").read_text(encoding="utf-8")), created_at=FL8_STARTED))
        fl8_row_time(task, row["id"], "2026-12-01T10:00:00+00:00")
        check_not_in("FL-8 B3: an older story + a registry of only later rows: its facts carry no counters (byte-stable)", "knowledge_use",
                     json.dumps(RF.build(task), default=str))
        fl8_row_time(task, row["id"], FL8_ROW_AT)
        check_in("FL-8 B3 CONTROL: the same story with a row known before its start gets the key", "knowledge_use", RF.build(task))
    finally:
        cleanup(task.parents[2])


def a_fact_with_no_time_or_a_story_with_no_start_is_unmeasured() -> None:
    """B3 edges: unknown is `unmeasured`, never known and never not-reached."""
    task = fl8_story(record=False)
    try:
        fl8_registry_role(task, "auditor", at="")
        fl8_briefs(task, S3_qa_test_strategist_1="roster without it\n")
        use = RF.knowledge_use(task)
        entry = use["entries"][0]
        check_eq("FL-8 B3: a row with no time: reach and use `unmeasured`, naming why", (entry["reached"], entry["used"]),
                 ("unmeasured: " + RF.NO_ROW_TIME,) * 2)
        check_eq("FL-8 B3: ... no finding line, and counter-metric (2) is not raised by it", (RF.finding_lines({"knowledge_use": use}),
                 use["counter_metrics"]["known_not_reached"], use["counter_metrics"]["used_unmeasured"]), ([], 0, 1))
        check_in("FL-8 B3: ... the fact is not hidden: the key is there", "knowledge_use", RF.build(task))
        fl8_registry_role(task, "guest")
        write(task / "pipeline.json", {"ticket": "T-1"})
        entries = {e["element"]: e for e in RF.knowledge_use(task)["entries"]}
        check_eq("FL-8 B3: a story with no start time: EVERY registry fact is unmeasured, none known",
                 {k: v["reached"] for k, v in entries.items()}, {"auditor": "unmeasured: " + RF.NO_START, "guest": "unmeasured: " + RF.NO_START})
    finally:
        cleanup(task.parents[2])


def reached_is_per_element_not_per_key() -> None:
    """F3 (rule 15): the marker and the element on ONE line; a capped roster and the empty-roster line prove nothing of an element."""
    task = fl8_story(record=False)
    try:
        fl8_registry_role(task, "auditor")
        fl8_registry_role(task, "guest")
        fl8_briefs(task, S3_qa_test_strategist_1="Product roles:\n- auditor: an account on dev (the person, T-0) [knowledge:product.roles]\n+1 more\n")
        reached = {e["element"]: e["reached"] for e in RF.knowledge_use(task)["entries"]}
        check_eq("FL-8 F3: a capped roster naming only `auditor`: `guest` is NOT reached", reached, {"auditor": ["qa-test-strategist"], "guest": []})
        check_in("FL-8 F3: ... and its `did not reach` line is not hidden", "product.roles guest was in no brief", RF.finding_lines(RF.build(task)))
        check_not_in("FL-8 F3: ... while auditor's is not raised", "product.roles auditor", "\n".join(RF.finding_lines(RF.build(task))))
        fl8_briefs(task, S3_qa_test_strategist_1="Product roles: none recorded yet (a project learns them story by story). [knowledge:product.roles]\n")
        check_eq("FL-8 F3: the EMPTY-roster line carries the mark and reaches no element",
                 {e["element"]: e["reached"] for e in RF.knowledge_use(task)["entries"]}, {"auditor": [], "guest": []})
        fl8_briefs(task, S3_qa_test_strategist_1="- Auditor [knowledge:product.roles]\n")
        check_eq("FL-8 F3: the element is compared by the key's form (`Auditor` is `auditor`)",
                 {e["element"]: e["reached"] for e in RF.knowledge_use(task)["entries"]}, {"auditor": ["qa-test-strategist"], "guest": []})
    finally:
        cleanup(task.parents[2])


def the_error_shape_of_the_first_look_measure_has_a_reader() -> None:
    """F2: `build` writes only `{"record": {...}}` when the measure itself fails; the retro lines must not crash on it."""
    facts = {"first_look_measure": {"record": {"kind": "error", "rows": "unmeasured: x", "stale": False, "problem": "ValueError: x"}}}
    lines = RF.retro_lines(facts)
    check_in("FL-8 F2: retro_lines on the error shape: unmeasured words, no KeyError", "First look: stand needs named unmeasured: ", "\n".join(lines))
    check_in("FL-8 F2: ... and the finding line says the record could not be read", "could not be read", RF.finding_lines(facts))


def the_plan_rows_are_counted_by_one_helper() -> None:
    """F6: `placeholder_open` and the delivery counters share one plan-row count."""
    import ledger as L
    rows = [{"kind": "plan_row", "state": L.PLACEHOLDER_OPEN_STATE}, {"kind": "plan_row", "state": L.PLACEHOLDER_OPEN_STATE},
            {"kind": "plan_row", "state": L.ON_SUBSTITUTE_STATE}, {"kind": "other", "state": L.PLACEHOLDER_OPEN_STATE}, "junk"]
    check_eq("FL-8 F6: one count by state over the plan rows only", RF._plan_row_counts({"rows": rows}, (L.PLACEHOLDER_OPEN_STATE, L.ON_SUBSTITUTE_STATE)),
             {L.PLACEHOLDER_OPEN_STATE: 2, L.ON_SUBSTITUTE_STATE: 1})
    check_eq("FL-8 F6: a ledger with no rows counts 0 per state", RF._plan_row_counts({}, (L.PLACEHOLDER_OPEN_STATE,)), {L.PLACEHOLDER_OPEN_STATE: 0})
    src = Path(RF.__file__).read_text(encoding="utf-8")
    check_eq("FL-8 F6: the file counts a ledger's plan rows by state in ONE place (not once per counter)",
             src.count('isinstance(r, dict) and r.get("kind") == "plan_row"'), 1)
    task = fl8_story(home="x")
    try:
        facts = RF.build(task)
        check_eq("FL-8 F6: the measure reads placeholder_open through it (the fixture ledger has no placeholder row: a measured 0)",
                 facts["first_look_measure"]["placeholder_open"], 0)
    finally:
        cleanup(task.parents[2])


def the_retro_knowledge_facts_are_one_assembly_with_build() -> None:
    """F1 (AR-22: a produced field has a reader): the retro reads `knowledge_facts`/`question_count`, the same assembly `build` uses."""
    task = fl8_story(home="x")
    try:
        fl8_registry_role(task)
        facts = RF.build(task)
        read = RF.knowledge_facts(task)
        check_eq("FL-8 F1: knowledge_facts is what build put in the facts (one assembly)",
                 {k: facts[k] for k in ("knowledge_use", "first_look_measure")}, read)
        (task / "work" / "requirements-readiness.json").unlink()
        check_in("FL-8 F1: no register: the question count is unmeasured, never 0", "unmeasured: ", str(RF.question_count(task)))
        write(task / "work" / "requirements-readiness.json", {"open_questions": []})
        check_eq("FL-8 F1: a register read with no question: a MEASURED zero", RF.question_count(task), 0)
        write(task / "work" / "requirements-readiness.json", {"open_questions": [
            {"id": "Q1", "text": "a", "options": ["a", "b"]}, {"id": "Q2", "text": "b", "options": ["a", "b"]}]})
        check_eq("FL-8 F1: two questions in the register are counted", RF.question_count(task), 2)
    finally:
        cleanup(task.parents[2])
    old = story()
    try:
        check_eq("FL-8 F1: an older story (no first look, no registry) has no knowledge facts", RF.knowledge_facts(old), {})
    finally:
        cleanup(old.parents[2])


def known_fact_not_reaching_decision_is_finding_line() -> None:
    task = fl8_story(record=False)
    try:
        fl8_registry_role(task)
        fl8_briefs(task, S3_qa_test_strategist_1="roster without the marker\n")
        lines = RF.finding_lines(RF.build(task))
        check_in("FL-8 a known fact that was in no brief: a finding line naming it", "A known fact did not reach a decision: product.roles auditor was in no brief", lines)
        fl8_briefs(task, S3_qa_test_strategist_1="- auditor [knowledge:product.roles]\n")
        fl8_strategist_form(task, ["guest"])
        metrics = RF.knowledge_use(task)["counter_metrics"]
        check_in("FL-8 reached a role but not in its product_roles: a finding line, available_unused counted",
                 "reached qa-test-strategist and was not used", RF.finding_lines(RF.build(task)))
        check_eq("FL-8 counter-metric (2) is the sum of both kinds", (metrics["known_not_reached"], metrics["available_unused"], metrics["known_not_reaching_a_decision"]), (0, 1, 1))
        fl8_strategist_form(task, ["Auditor"])
        check_eq("FL-8 CONTROL: the strategist named the role (by its form): no finding line", RF.finding_lines(RF.build(task)), [])
        check_in("FL-8 counter-metrics (1) and (3) have no carrier: unmeasured with the step 0 reason", "unmeasured: answer scope is not recorded",
                 RF.knowledge_use(task)["counter_metrics"]["answer_scope_applied_as_rule"])
        check_in("FL-8 ... and (1)", "invented_not_asked", RF.knowledge_use(task)["counter_metrics"]["invented_not_asked"])
    finally:
        cleanup(task.parents[2])


def briefs_not_kept_reads_unmeasured() -> None:
    task = fl8_story(home="x")
    try:
        fl8_registry_role(task)
        use = RF.knowledge_use(task)
        check_eq("FL-8 no briefs on disk: the reach is `unmeasured: briefs are not kept`", use["entries"][0]["reached"], "unmeasured: briefs are not kept")
        check_eq("FL-8 ... the briefs word says so", use["briefs"], "unmeasured: briefs are not kept")
        check_in("FL-8 ... counter-metric (2) is unmeasured, not 0", "unmeasured: briefs are not kept", use["counter_metrics"]["known_not_reaching_a_decision"])
        check_not_in("FL-8 ... and no `was in no brief` finding (unknown is not `not reached`)", "was in no brief", RF.finding_lines(RF.build(task)))
        write(task / "work" / "briefs" / "S3-qa-test-strategist-1.md", "x")
        (task / "work" / "briefs" / "S3-qa-test-strategist-1.md").unlink()
        check_eq("FL-8 an empty briefs folder is `not kept` too", RF.knowledge_use(task)["briefs"], "unmeasured: briefs are not kept")
    finally:
        cleanup(task.parents[2])


def zero_questions_printed_with_counter_metrics() -> None:
    task = fl8_story(home="x")
    try:
        fl8_registry_role(task)
        fl8_briefs(task, S3_qa_test_strategist_1="- auditor [knowledge:product.roles]\n")
        facts = RF.build(task)
        zero = RF.question_count_line(0, facts)
        check_in("FL-8 zero questions is printed together with the counter-metrics", "Questions put to the person: 0; known facts no brief carried: 0", zero)
        check_in("FL-8 ... all four, the two without a carrier unmeasured", "answer invented where a question was owed: unmeasured: ", zero)
        check_eq("FL-8 zero with no counter-metrics to print: the zero is NOT printed, it is unmeasured", RF.question_count_line(0, {}),
                 "unmeasured: zero questions is not printed without its counter-metrics")
        check_eq("FL-8 a count over zero stands alone when there are no counter-metrics", RF.question_count_line(3, {}), "Questions put to the person: 3")
    finally:
        cleanup(task.parents[2])


def main() -> None:
    first_look_cost_from_story_journal()
    first_look_share_and_answers_counted()
    first_look_attempt_outcome_counted()
    use_locators_and_routes_in_s5_homes_counted()
    use_s4_cases_citing_walked_path_counted()
    use_probes_on_seen_elements_counted_or_unmeasured()
    unread_record_is_finding_line()
    null_record_no_unread_finding()
    stand_needs_and_gaps_are_read()
    counts_never_refuse()
    knowledge_use_counts_registry_and_first_look_in_one_table()
    known_role_reached_strategist_and_case_critic()
    known_credential_not_reasked_counts_used()
    known_fact_not_reaching_decision_is_finding_line()
    briefs_not_kept_reads_unmeasured()
    zero_questions_printed_with_counter_metrics()
    a_used_credential_is_not_a_fact_that_missed_the_decision()
    an_unreadable_registry_makes_the_counter_metric_unmeasured_not_zero()
    a_fact_the_story_taught_is_not_one_it_ignored()
    a_fact_with_no_time_or_a_story_with_no_start_is_unmeasured()
    reached_is_per_element_not_per_key()
    the_error_shape_of_the_first_look_measure_has_a_reader()
    the_plan_rows_are_counted_by_one_helper()
    the_retro_knowledge_facts_are_one_assembly_with_build()
    pc_10_sides_measure()
    one_bug_many_manifestations_in_the_report()
    g2_5_what_the_change_touches()
    red_test_is_not_not_probed()
    coverage_owner_in_the_verdict()
    a_bug_candidate_reaches_left_with_you()
    r_1_to_r_3_blocks()
    r_4_units()
    r_5_to_r_9()
    r_10_11_size_and_pictures()
    fb8_person_content_line_at_and_beyond_cap()
    one_number_proven()
    questions_have_one_predicate()
    gate_a_names_an_unanswered_question()
    appendix_is_compared_with_a_render()
    head_never_names_a_hash()
    person_build_line()
    verdict_block_follows_the_ledger_word()
    the_one_predicate_loop()
    completeness_of_left_with_you()
    regression_block()
    collect_gaps_rows()
    manual_checks_k4()
    manual_record_in_the_traceability_table()
    manual_checks_edges()
    manual_checks_stand_blocked()
    manual_export_path_is_what_the_code_writes()
    partly_proven_unconfirmed_then()
    unconfirmed_expectations()
    one_source_per_count()
    first_reason_order()
    bug_on_a_manual_case()
    same_bytes_inside_and_outside_the_project()
    the_cut()
    proven_rules()
    expectation_change_words()
    probe_debt_line()
    open_questions()
    not_proven_items()
    answered_suffix()
    gate_blocks()
    integration_check_is_a_project_wide_word()
    every_project_wide_word_has_a_key()
    size_and_where()
    every_source_absent()
    report_absent()
    legacy_check_passes()
    conversion_inline()
    edit_inside_a_block()
    damaged_markers()
    older_contract_report()
    check_is_pure_and_exact()
    factory_owned_left_items()
    verdict_change_after_gate_b()
    determinism()
    mid_flight()
    reports_keep_their_own_words()
    cmp1_conversion()
    review_gaps_block()
    review_gaps_every_open_row_and_one_filter()
    review_gaps_null_unknown_and_head()
    over_cap_windows_line()
    register_less_story_is_byte_identical()
    exploratory_block_and_formal_line()
    register_adds_nothing_to_bugs_or_verdict()
    gate_lines_stand_above_the_bug_headline()
    damaged_register_is_unknown_never_none()
    exploratory_block_removed_and_added()
    probe_count_is_the_probes_reader()
    exploratory_block_in_words_k_b1_a()
    exploratory_block_in_words_negative_control_k_b1_b()
    exploratory_words_of_codes_and_formal_split_n7_n9f()
    w2_decisions_b_c()
    ep1_37_a_tool_gap_is_the_factorys()
    finish("report_facts")


def ep1_37_a_tool_gap_is_the_factorys() -> None:
    """EP1-37 p. 8 (M-6, FR-19): `unknown["expectation_changes_code"] == "tool"` makes the Unknown sentence name its owner - the
    factory's reader - so it is not read as a gap of the product; without the code the sentence is as it was."""
    import report_facts as RF
    what = "which tests changed after a red run"
    tool = RF._unknown_line({"unknown": {"expectation_changes": "the file cannot be read by this reader",
                                         "expectation_changes_code": "tool"}}, "expectation_changes", what)
    check_in("a tool gap says whose it is", "a gap of the factory's tool, not of the product", tool)
    plain = RF._unknown_line({"unknown": {"expectation_changes": "the file cannot be read by this reader"}}, "expectation_changes", what)
    check_not_in("without the code the sentence is as it was", "factory's tool", plain)
    check_eq("and its text is the old one", plain, f"Unknown {what} — the file cannot be read by this reader.")
    import run_history as RH
    check_in("run_history says the reader is the one that cannot read (no `not a Python file`)", "cannot be read by this reader",
             Path(RH.__file__).read_text(encoding="utf-8"))


def w2_decisions_b_c() -> None:
    """P2 fix round W2, Lead decisions B and C (HF8-20). KILLS (M-i): `(for <owner_role>)` printed again; (M-j): the exception text of
    an unreadable register put into person text."""
    task = story()
    try:
        add_finding(task, "unresolved_question", "the period end is not stated", target="t-2")
        item = RF._exploratory_item(next(iter(EF.read(task)["active"].values())))
        check_not_in("W2-B the owner's role is never printed in person text (no '(for ...)', no 'po_ba')", "po_ba", item)
        check_not_in("W2-B ... and no '(for '", "(for ", item)
        original = EF.read
        EF.read = lambda root: (_ for _ in ()).throw(OSError(r"C:\x\work\exploratory-findings.jsonl is locked"))
        try:
            facts = RF.build(task)
            gate = RF.exploratory_gate_lines(task)
        finally:
            EF.read = original
        check_eq("W2-C an unreadable register: the fact says in words that the record could not be read", facts["unknown"].get("exploratory"),
                 RF.RECORD_UNREADABLE)
        shown = "\n".join(gate) + RF.render(facts).get("exploratory", "")
        check_not_in("W2-C ... and no exception text, class or path reaches a person", "OSError", shown)
        check_not_in("W2-C ... nor a path", "work\\", shown)
        check_eq("W2-C the gate line is the same fixed words, with no question to answer", gate,
                 [f"{RF.EXPLORATORY_HEAD}: unknown — {RF.RECORD_UNREADABLE}."])
        check("W2-D no 'register' in the Unknown words a person reads", "register" not in RF.EXPLORATORY_WHAT and "register" not in RF.RECORD_UNREADABLE)
    finally:
        cleanup(task.parents[2])


# --- P2 M1 step 3: the readers of the findings register -----------------------------------------------------------------

BY = "S7-qa-failure-analyst-1"
# sha256[:16] of the Proven block of `story()` rendered by the code BEFORE the register readers landed (git 1e228adf).
PROVEN_GOLDEN = "e0d2b7758a71e7fa"
TEMPLATE = SCRIPTS.parent / "references" / "templates" / "test-report.md"
GATE_COUNT = "Exploratory findings and unresolved questions: {n} — not bugs, nothing is filed from them"


def add_finding(task: Path, kind="observation", statement="the export keeps a stale column", target=None, probe=None,
                status="unverified") -> str:
    write(task / "work" / "evidence" / "e1.txt", "seen")
    line = {"op": "add", "kind": kind, "title": statement[:40], "statement": statement, "refs": ["R-1"],
            "why_not_a_bug": "no requirement says what the column should read", "probe": probe,
            "verification_status": status, "evidence_refs": [{"path": "work/evidence/e1.txt"}]}
    if kind == "unresolved_question":
        line.update(question="Which column order is right?", owner_role="po_ba")
    if kind == "coverage_gap":
        line.update(missing_prerequisite="a stand with the export enabled")
    if target:
        line["origin"] = {"dispatch": BY, "target": target}
    return EF.append(task, line, by=BY)


def correct_finding(task: Path, old: str, target: str, statement: str, reason: str) -> str:
    return EF.append(task, {"op": "correct", "kind": "observation", "title": statement[:40], "statement": statement,
                            "why_not_a_bug": "the second look settles it", "evidence_refs": [{"path": "work/evidence/e1.txt"}],
                            "corrects": {"id": old, "reason": reason}, "origin": {"dispatch": BY, "target": target}}, by=BY)


def withdraw_finding(task: Path, old: str, target: str, reason: str) -> str:
    return EF.append(task, {"op": "withdraw", "withdraws": {"id": old, "reason": reason},
                            "origin": {"dispatch": BY, "target": target}}, by=BY)


def register_less_ok(task: Path) -> bool:
    """K-M1-5's judgment: no `exploratory` block, no formal line, no gate lines, the Proven block as it was before the readers."""
    facts = RF.build(task)
    blocks = RF.render(facts)
    return ("exploratory" not in blocks and "exploratory" not in facts["unknown"]
            and hashlib.sha256(blocks["proven"].encode()).hexdigest()[:16] == PROVEN_GOLDEN
            and "Formal test execution" not in blocks["proven"] and RF.exploratory_gate_lines(task) == [])


def register_less_story_is_byte_identical() -> None:
    """K-M1-5 (AC-8). KILLS: the block rendered unconditionally (the control below), the formal line without a register,
    gate lines without a register."""
    task = story()
    try:
        facts = RF.build(task)
        check_eq("K-M1-5 no register file: the fact is None", facts["exploratory"], None)
        check_eq("K-M1-5 the blocks rendered are exactly the always-present ones",
                 sorted(RF.render(facts)),
                 sorted(["verdict", "proven", "manual-checks", "bugs", "review-gaps", "regression", "open-questions", "skipped-by-plan",
                         "not-proven", "gate-a", "size", "where-to-look"]))
        check("K-M1-5 the Proven block's bytes (sha256[:16]) equal the pre-change golden; no exploratory part, formal line or gate line",
              register_less_ok(task))
        packet = GB.render_gate_b("T-1", task)
        original = RF.exploratory_gate_parts
        RF.exploratory_gate_parts = lambda root: {"head": [], "questions": [], "left_open": [], "gaps": [], "unknown": False}
        try:
            without = GB.render_gate_b("T-1", task)
        finally:
            RF.exploratory_gate_parts = original
        check_eq("K-M1-5 render_gate_b equals the packet with the call removed", packet, without)
        check_not_in("K-M1-5 and the packet says nothing of a register", "Exploratory", packet)
        write(task / "work" / "exploratory-findings.jsonl", "")
        check("K-M1-5 a 0-byte register is the same as none", register_less_ok(task))
        template = TEMPLATE.read_text(encoding="utf-8")
        check_not_in("K-M1-5 the template keeps no exploratory block", "facts:exploratory", template)
        errors: list = []
        V.check_report_blocks(TEMPLATE, errors)
        # (the template is a report whose gate B has no words: that one error is the template's own, not this block's)
        check_eq("K-M1-5 and the template passes check_report_blocks without it: no missing block, no word of this one",
                 [e for e in errors if "exploratory" in e or "missing" in e], [])
        # negative control: the block rendered unconditionally fails the same judgment
        kept = RF._register_shown
        RF._register_shown = lambda facts: True
        try:
            (task / "work" / "exploratory-findings.jsonl").unlink()
            check("K-M1-5 NEGATIVE CONTROL: rendering the block unconditionally makes the judgment fail", not register_less_ok(task))
        finally:
            RF._register_shown = kept
    finally:
        cleanup(task.parents[2])


def exploratory_block_and_formal_line() -> None:
    """K-M1-6 (AC-3/4). KILLS: the slot before `bugs`, a missing field of an entry, a struck line printed whole."""
    task = story()
    try:
        add_finding(task, "observation", "the export keeps a stale column", target="t-1",
                    probe={"method": "api", "runs": 3, "reproduced": 3, "environment": "stand", "safe_to_break": None},
                    status="reproduced")
        add_finding(task, "unresolved_question", "the period end is not stated", target="t-2")
        add_finding(task, "coverage_gap", "no stand with the export", target="t-3")
        add_finding(task, "observation", "first reading of the totals", target="t-4")
        correct_finding(task, "EX-4", "t-4", "second reading of the totals", "the first reading was wrong")
        add_finding(task, "observation", "a column that was not there", target="t-5")
        withdraw_finding(task, "EX-6", "t-5", "it was another story's file")
        write(task / "work" / "evidence" / "investigation" / "D" / "captures.jsonl",
              '{"started_at": "2026-10-29T10:00:00"}\n{"n": 1, "target": "t-1"}\n{"n": 2, "target": "t-1"}\n')
        blocks = RF.render(RF.build(task))
        body = blocks["exploratory"]
        check_eq("K-M1-6 the block opens with its heading", body.splitlines()[0], "## Exploratory findings and unresolved questions")
        check_eq("K-M1-6 three lists, in this order", [ln for ln in body.splitlines() if ln.startswith("### ")],
                 ["### Observations", "### Unresolved questions", "### Coverage gaps"])
        for needle in ("- the export keeps a stale column — seen again (3 of 3 tries) — why it is not a bug: "
                       "no requirement says what the column should read",
                       "- the period end is not stated — not checked again — waits for your answer: Which column order is right? "
                       "— why it is not a bug:",
                       "- no stand with the export — not checked again — missing: a stand with the export enabled",
                       "- second reading of the totals — not checked again",
                       "- ~~first reading of the totals~~ — corrected later: the first reading was wrong",
                       "- ~~a column that was not there~~ — withdrawn: it was another story's file"):
            check_in(f"K-M1-6 the block holds `{needle[:50]}`", needle, body)
        check_not_in("K-M1-6 a struck line is not printed whole", "- first reading of the totals", body)
        check_not_in("K-M1-6 no register id stands in the block", "EX-", body)
        check_in("K-M1-6 the Proven block ends with the formal line (1 test, 1 execution, 2 probes, 3 findings and 1 gap)",
                 "Formal test execution: 1 test, 1 execution. Exploratory probes: 2 probes; 3 findings and 1 gap (what the "
                 "factory could not check) — not tests, not counted as proven.", blocks["proven"])
        legacy_report(task)
        res = RF.write(task)
        check("K-M1-6 --write does not raise and succeeds on a register", res["ok"], str(res["lines"]))
        text = (task / "test-report.md").read_text(encoding="utf-8")
        order = [m.group(1) for m in re.finditer(r"<!-- facts:([a-z-]+) -->", text)]
        check_eq("K-M1-6 the block stands after `bugs` and before `review-gaps`",
                 order[order.index("bugs"):order.index("review-gaps") + 1], ["bugs", "exploratory", "review-gaps"])
        check_eq("K-M1-6 --check is clean", RF.check(task), [])
        check_eq("K-M1-6 a second --write changes nothing", (RF.write(task)["ok"], (task / "test-report.md").read_text(encoding="utf-8")),
                 (True, text))
    finally:
        cleanup(task.parents[2])


def register_adds_nothing_to_bugs_or_verdict() -> None:
    """K-M1-7 (AC-2/9, AR-27). KILLS: an entry counted as a bug, a triage row or a proven requirement."""
    task = story()
    try:
        before = RF.build(task)
        before_blocks = RF.render(before)
        for n in range(1, 4):
            add_finding(task, "observation", f"stray observation {n}", target=f"t-{n}")
        add_finding(task, "unresolved_question", "an open question", target="t-9")
        after = RF.build(task)
        after_blocks = RF.render(after)
        check_eq("K-M1-7 facts[bugs] unchanged by four entries", after["bugs"], before["bugs"])
        check_eq("K-M1-7 requirements.counts unchanged", after["requirements"]["counts"], before["requirements"]["counts"])
        check_eq("K-M1-7 the verdict block unchanged", after_blocks["verdict"], before_blocks["verdict"])
        check_eq("K-M1-7 the bugs block unchanged", after_blocks["bugs"], before_blocks["bugs"])
        check_eq("K-M1-7 the proven count unchanged", after["tests"]["count"], before["tests"]["count"])
        check_not_in("K-M1-7 no entry is under the bugs block", "stray observation", after_blocks["bugs"])
    finally:
        cleanup(task.parents[2])


def gate_lines_stand_above_the_bug_headline() -> None:
    """K-M1-8 (FR-10). KILLS: the lines below the headline, the headline missing, "Bugs found - none" standing alone."""
    task = story(with_bug=False)
    try:
        check_eq("K-M1-8 no register: no gate lines", RF.exploratory_gate_lines(task), [])
        add_finding(task, "unresolved_question", "the period end is not stated", target="t-2")
        add_finding(task, "coverage_gap", "no stand with the export", target="t-3")
        add_finding(task, "observation", "an observation is counted, not listed", target="t-4")
        add_finding(task, "unresolved_question", "withdrawn question", target="t-5")
        withdraw_finding(task, "EX-4", "t-5", "answered elsewhere")
        lines = RF.exploratory_gate_lines(task)
        check_eq("K-M1-8 the headline counts the active entries", lines[0], GATE_COUNT.format(n=3))
        check_eq("K-M1-8 then the questions (a role's question with no case: listed, no answer form), then the gaps, no id of the register",
                 lines[1:], ["Questions for you — is this intended? (1)",
                             "- the period end is not stated. Seen: the period end is not stated. Before the change: not recorded. "
                             "Now: not recorded. The question: Which column order is right? No test case is named for it - answer in words.",
                             "What the factory could not check (1)",
                             "- no stand with the export — missing: a stand with the export enabled"])
        check_not_in("K-M1-8/E decision E: no EX-n id in a gate line", "EX-", "\n".join(lines))
        packet = GB.render_gate_b("T-1", task)
        check_in("K-M1-8 the packet holds the bug headline", "Bugs found — none", packet)
        check_in("K-M1-8 and the count line", GATE_COUNT.format(n=3), packet)
        check("K-M1-8 the count line stands ABOVE the bug headline",
              0 < packet.index(GATE_COUNT.format(n=3)) < packet.index("Bugs found — none"))
        check("K-M1-8 the packet still opens with its title", packet.startswith("# Gate B — T-1\n\n" + GATE_COUNT.format(n=3)))
    finally:
        cleanup(task.parents[2])


def damaged_register_is_unknown_never_none() -> None:
    """K-M1-9 (AR-28, FR-41). KILLS: dropping the Unknown line, a damaged-only register read as empty."""
    task = story()
    try:
        write(task / "work" / "exploratory-findings.jsonl", "not json at all\n")
        facts = RF.build(task)
        check_eq("K-M1-9 the unknown entry counts the damaged line, in words (the reason stays with the role channel)",
                 facts["unknown"]["exploratory"], "1 line(s) of the findings record cannot be read")
        check_eq("K-M1-9 ... and the role channel still has the reason", EF.read(task)["unreadable"], [(1, "not valid JSON")])
        blocks = RF.render(facts)
        check_in("K-M1-9 a damaged-only register: the block exists and holds the Unknown line",
                 "Unknown what the run saw but could not settle — 1 line(s) of the findings record cannot be read.",
                 blocks["exploratory"])
        check_not_in("K-M1-9 the machine reason of a damaged line is not shown to a person", "not valid JSON", blocks["exploratory"])
        check_not_in("K-M1-9 and no list says \"none\" over what cannot be read", "none", blocks["exploratory"])
        gate = RF.exploratory_gate_lines(task)
        check_eq("K-M1-9 the gate headline counts 0 and the Unknown sentence follows", (gate[0], gate[1].startswith("Unknown what the run saw")),
                 (GATE_COUNT.format(n=0), True))
        check_in("K-M1-9 the formal line is there too", "Formal test execution:", blocks["proven"])
        add_finding(task, "observation", "a readable one", target="t-1")
        blocks = RF.render(RF.build(task))
        check("K-M1-9 a readable line beside the damaged one: both the Unknown line and the entry",
              "Unknown what the run saw" in blocks["exploratory"] and "- a readable one — not checked again" in blocks["exploratory"])
        check_in("K-M1-9 an empty list beside a damaged line reads \"none readable\"", "none readable", blocks["exploratory"])
    finally:
        cleanup(task.parents[2])


def probe_count_is_the_probes_reader() -> None:
    """K-M1-6 m4. The probes made are counted through `investigation_probe.capture_lines` (one reader of captures.jsonl, its
    damaged-line rule), never by a reader of this module's own. KILLS: a private captures reader that counts a damaged line
    as a probe, a missing reader read as 0."""
    task = story()
    try:
        add_finding(task, "observation", "the export keeps a stale column", target="t-1")
        captures = task / "work" / "evidence" / "investigation" / "D" / "captures.jsonl"
        write(captures, '{"started_at": "2026-10-29T10:00:00"}\n{"n": 1, "target": "t-1"}\n')
        check_eq("m4 one capture line (the header is not a probe): 1", RF._probe_count(task), 1)
        check_in("m4 ... and the Proven block says 1 probe", "Exploratory probes: 1 probe; 1 finding and 0 gaps",
                 RF.render(RF.build(task))["proven"])
        write(captures, '{"started_at": "2026-10-29T10:00:00"}\n{"n": 1, "target": "t-1"}\n{not json}\n')
        check_eq("m4 a damaged line (the probe reader's rule): the count is unknown, not 2", RF._probe_count(task), None)
        check_in("m4 ... and the Proven block says so", "an unknown number of probes", RF.render(RF.build(task))["proven"])
        write(captures, '{"started_at": "2026-10-29T10:00:00"}\n{"n": 1, "target": "t-1"}\n')
        saved = sys.modules.get("investigation_probe")
        sys.modules["investigation_probe"] = None          # `import investigation_probe` now raises ImportError
        try:
            check_eq("m4 the probe module absent: the count is unknown, never 0", RF._probe_count(task), None)
            check_in("m4 ... and the proven line says so", "an unknown number of probes", RF.render(RF.build(task))["proven"])
        finally:
            if saved is None:
                del sys.modules["investigation_probe"]
            else:
                sys.modules["investigation_probe"] = saved
        check_eq("m4 control: the module back, the count is back", RF._probe_count(task), 1)
        check_eq("m4 no pass folder at all: 0", RF._probe_count(Path(str(task) + "-none")), 0)
    finally:
        cleanup(task)


# --- P2 fix round W1 (critic t-1579): the block in words for a person (HF8-20) ----------------------------------------------

MACHINE_SHAPES = (r"\.(jsonl?|ya?ml|txt)\b", r"[0-9a-f]{12,}", r"\bS\d+-[a-z-]+-\d+\b", r"\bEX-\d+\b",
                  r"\b(unverified|not_reproduced|environment_event|owner_question)\b", r"sha256", r"work/")
PNG = "work/evidence/manual/TC-006/a1/screen-1.png"


def words_register(task: Path) -> None:
    """A register shaped as `investigation.project` writes it (carriers: a runner hand-back and a manual request) plus a probe
    line, a `.txt`, a `.png`, free text that names paths, and every status."""
    write(task / "work" / "handoffs" / "S6-qa-runner-1.yaml", "manual_observations: []\n")
    write(task / "work" / "evidence" / "manual" / "TC-006" / "request.json", {"refused": True})
    write(task / "work" / "evidence" / "investigation" / "R" / "T" / "001-request-response.json", {"status": 403})
    write(task / "work" / "evidence" / "e1.txt", "seen")
    write(task / PNG, "png", binary=True)
    carrier = [{"path": "work/handoffs/S6-qa-runner-1.yaml"}, {"path": "work/evidence/manual/TC-006/request.json"},
               {"path": "work/evidence/investigation/R/T/001-request-response.json"}, {"path": "work/evidence/e1.txt"},
               {"path": PNG}]
    base = {"op": "add", "kind": "observation", "refs": ["TC-006", "R-16"],
            "why_not_a_bug": "see /abs/work/handoffs/S6-qa-runner-1.yaml and C:\\x\\work\\a.json", "evidence_refs": carrier}
    probe = {"method": "api", "runs": 3, "reproduced": 3, "environment": "stand", "safe_to_break": None}
    for n, (status, over) in enumerate((("unverified", {}), ("reproduced", {"probe": probe}), ("not_reproduced", {"probe": dict(probe, reproduced=0)}),
                                        ("environment_event", {"probe": dict(probe, reproduced=1)})), 1):
        EF.append(task, dict(base, title=f"s{n}", statement=f"line {n} was observed in work/evidence/investigation/R/T/001-request-response.json",
                             verification_status=status, origin={"dispatch": BY, "target": f"t-{n}"}, **over), by=BY)
    EF.append(task, dict(base, kind="unresolved_question", title="q", statement="the period end is not stated",
                         question="Is the period end meant to be included?", owner_role="the person who decides the story's expected behaviour",
                         verification_status="unverified", origin={"dispatch": BY, "target": "t-5"}), by=BY)
    EF.append(task, dict(base, kind="coverage_gap", title="g", statement="the factory could not read the test runner's hand-back",
                         missing_prerequisite="a readable copy of the test runner's hand-back", verification_status="unverified",
                         origin={"dispatch": BY, "target": "t-6"}), by=BY)


def machine_shapes_in(text: str) -> list:
    return [pattern for pattern in MACHINE_SHAPES if re.search(pattern, text)]


def exploratory_block_in_words_k_b1_a() -> None:
    """K-B1-a (HF8-20). KILLS: a sha, a directory or a path, a register id, a dispatch id, a status or oracle code in the block; a
    .txt/.json shown as evidence. The .png basename IS shown."""
    task = story()
    try:
        words_register(task)
        body = RF.render(RF.build(task))["exploratory"]
        check_eq("K-B1-a the block holds no machine shape (path, hash, dispatch id, EX-n, code)", machine_shapes_in(body), [])
        check_in("K-B1-a t-423 F3: the finding says in words that its screenshot is provided (the file is on disk)", "screenshots: provided", body)
        check_not_in("K-B1-a ... and no file name, directory or count of the evidence", "screen-1", body)
        chat = RF.screenshots_chat_text(task)
        check_in("t-423 F3: the finding's picture is in the chat text, under its case", "- finding TC-006: " + str(task.resolve() / PNG), chat)
        check_eq("t-423 F3: ... once, though four lines of the case hold it", chat.count("screen-1.png"), 1)
        check_in("K-B1-a the case id stays when the line's refs name one", "- TC-006 — line 1 was observed in the evidence record", body)
        for words in ("not checked again", "seen again (3 of 3 tries)", "not seen again (0 of 3 tries)",
                      "caused by the test environment, not the product (1 of 3 tries)",
                      "waits for your answer: Is the period end meant to be included?", "missing: a readable copy of the test runner's hand-back"):
            check_in(f"K-B1-a the block says `{words[:40]}`", words, body)
        # the person-text scrub is the last line of defence: adversarial paths in free text
        for hostile in ("state/events.jsonl", "pipeline.json", "C:\\x\\work\\a.json", "/abs/work/handoffs/S6-qa-runner-1.yaml",
                        "work/evidence/investigation/R/T/001-request-response.json"):
            item = RF._exploratory_item({"_status": "active", "kind": "observation", "statement": f"seen in {hostile}",
                                         "why_not_a_bug": f"read {hostile}", "verification_status": "unverified"})
            # `state/events.jsonl` and `pipeline.json` are named at the producer (investigation._record_words), not here
            if hostile not in ("state/events.jsonl", "pipeline.json"):
                check_eq(f"K-B1-a plain_words leaves no machine shape of `{hostile[-24:]}`", machine_shapes_in(item), [])
        # the screenshot rule: only images, only the name, each once, any case of the suffix
        refs = {"evidence_refs": [{"path": "work/a/b.PNG"}, {"path": "work/a/c.txt"}, {"path": "x\\d.jpeg", "sha256": "ab" * 32},
                                  {"path": "work/a/b.PNG"}, "junk", {"path": None}, {}]}
        check_eq("K-B1-a _exploratory_shots: image files only, once each, no other file; none is on disk when no folder is given",
                 RF._exploratory_shots(None, refs), {"taken": 2, "provided": 0, "files": []})
        on_disk = RF._exploratory_shots(task, {"evidence_refs": [{"path": PNG}, {"path": "work/gone.png"}]})
        check_eq("t-423 F3: ... a picture on disk is provided and listed, one that is gone is taken and not provided",
                 on_disk, {"taken": 2, "provided": 1, "files": [PNG]})
        check_eq("K-B1-a ... and nothing at all (no count, no `none recorded`) when there is no image",
                 RF._exploratory_shots(None, {"evidence_refs": [{"path": "work/evidence/e1.txt", "sha256": "ab" * 32}]})["taken"], 0)
        check_eq("K-B1-a ... evidence_refs absent: nothing", RF._exploratory_shots(None, {})["taken"], 0)
        check_not_in("K-B1-a ... a line with no image has no screenshots sentence", "screenshots:",
                     RF._exploratory_item({"_status": "active", "kind": "observation", "statement": "s", "why_not_a_bug": "w",
                                           "evidence_refs": [{"path": "work/evidence/e1.txt"}]}))
        check_in("t-423 F3: a line whose picture has no copy says so in the manual case's own words", RF.SHOTS_NO_COPY,
                 RF._exploratory_item({"_status": "active", "kind": "observation", "statement": "s", "why_not_a_bug": "w",
                                       "evidence_refs": [{"path": "work/a/b.PNG"}]}))
    finally:
        cleanup(task.parents[2])


def exploratory_block_in_words_negative_control_k_b1_b() -> None:
    """K-B1-b. NEGATIVE CONTROL of K-B1-a: the old evidence words (path in backticks, sha256) make the same judgment fail."""
    task = story()
    kept = G.shots_words
    try:
        words_register(task)
        G.shots_words = lambda taken, provided: "evidence: `work/evidence/e1.txt` (sha256 " + "ab" * 6 + ")"
        body = RF.render(RF.build(task))["exploratory"]
        check("K-B1-b NEGATIVE CONTROL: the old evidence words make K-B1-a's judgment fail", machine_shapes_in(body) != [],
              "the old words left no machine shape: the patterns of K-B1-a cannot fail")
    finally:
        G.shots_words = kept
        cleanup(task.parents[2])


def exploratory_words_of_codes_and_formal_split_n7_n9f() -> None:
    """N1 status words, N7 (the `oracle_status` reader), N9f (m6). KILLS: a status code without a word, an unknown code printed as a
    fact, `oracle_status` read by nobody, a gap counted as a finding."""
    check_eq("N1 EXPLORATORY_STATUS_WORDS keys == the writer's STATUSES (a code without a word fails here)",
             sorted(RF.EXPLORATORY_STATUS_WORDS), sorted(EF.STATUSES))
    check("N7 every oracle word is a code the writer knows, or the one the gate B answer adds",
          set(RF.EXPLORATORY_ORACLE_WORDS) <= set(EF.ORACLES) | {"person_confirmed"})
    line = {"_status": "active", "kind": "observation", "statement": "s", "why_not_a_bug": "w", "verification_status": "unverified"}
    for oracle, words in (("owner_question", "left open with you"), ("person_confirmed", "confirmed by you at gate B"),
                          ("documented_text_only", "the expectation stands only on documentation text")):
        check_in(f"N7 oracle_status {oracle} is read into words", words, RF._exploratory_item(dict(line, oracle_status=oracle)))
    plain = RF._exploratory_item(dict(line, oracle_status="none"))
    check("N7 oracle_status none says nothing", "waits" not in plain and "documentation" not in plain and "confirmed" not in plain, plain)
    check_in("N1 an unknown status code is said to be unrecorded, not printed", "status not recorded",
             RF._exploratory_item(dict(line, verification_status="investigated")))
    check_not_in("N1 ... and the code itself is not shown", "investigated", RF._exploratory_item(dict(line, verification_status="investigated")))
    task = story()
    try:
        add_finding(task, "coverage_gap", "no stand with the export", target="t-1")
        add_finding(task, "coverage_gap", "no data for the period", target="t-2")
        facts = RF.build(task)
        check_eq("N9f formal counts: two gaps are no finding", (facts["exploratory"]["formal"]["findings"], facts["exploratory"]["formal"]["gaps"]), (0, 2))
        check_in("N9f the formal line", "0 findings and 2 gaps (what the factory could not check) — not tests, not counted as proven.",
                 RF.render(facts)["proven"])
    finally:
        cleanup(task.parents[2])


def exploratory_block_removed_and_added() -> None:
    """K-M1-10 (B2). KILLS: the gate-B wording for this block, a removal with no history copy, an add that loses bytes."""
    task = story()
    try:
        add_finding(task, "observation", "the export keeps a stale column", target="t-1")
        legacy_report(task)
        RF.write(task)
        history = task / "state" / "report-history"
        raw = (task / "test-report.md").read_bytes()
        check_in("K-M1-10 setup: the marked report holds the block", "<!-- facts:exploratory -->", raw.decode("utf-8"))
        (task / "work" / "exploratory-findings.jsonl").write_bytes(b"")
        kept = len(list(history.iterdir()))
        problems = RF.check(task)
        mine = [p for p in problems if "`exploratory`" in p]
        check_eq("K-M1-10 --check names the register reason and the door, once", len(mine), 1)
        check_in("K-M1-10 the reason", "block `exploratory` stands though the findings register holds no line", mine[0])
        check_in("K-M1-10 the door", "--write", mine[0])
        check_not_in("K-M1-10 the gate-B wording is never printed for this block", "gate B", mine[0])
        res = RF.write(task)
        check("K-M1-10 --write ok", res["ok"], str(res["lines"]))
        check_in("K-M1-10 --write names the register reason",
                 "removed block `exploratory`: the findings register holds no line; the block is removed", "\n".join(res["lines"]))
        check_not_in("K-M1-10 and not the gate-B wording", "only once its gate", "\n".join(res["lines"]))
        check_not_in("K-M1-10 the block is gone", "facts:exploratory", (task / "test-report.md").read_text(encoding="utf-8"))
        saved = history / f"test-report-{hashlib.sha256(raw).hexdigest()[:12]}.md"
        check("K-M1-10 one history copy, byte for byte the report that held the block",
              len(list(history.iterdir())) == kept + 1 and saved.is_file() and saved.read_bytes() == raw)
        check_eq("K-M1-10 --check is clean again", RF.check(task), [])
        # the other way: a register that now holds a line, a marked report with no block
        add_finding(task, "observation", "a later observation", target="t-2")
        problems = RF.check(task)
        mine = [p for p in problems if "`exploratory`" in p]
        check("K-M1-10 a non-empty register with no block: `block `exploratory` is missing`, door --write",
              len(mine) == 1 and "block `exploratory` is missing" in mine[0] and "--write" in mine[0], str(mine))
        before_copies = len(list(history.iterdir()))
        res = RF.write(task)
        check_in("K-M1-10 --write adds it with its own note", "added block `exploratory`: the findings register holds lines",
                 "\n".join(res["lines"]))
        check_not_in("K-M1-10 adding the block replaces nothing of its own", "replaced block `exploratory`", "\n".join(res["lines"]))
        # the Proven block gains its formal line with the register, so THAT replacement (not the add) is what saves bytes
        check_eq("K-M1-10 the one history copy is the Proven block's replaced bytes",
                 ("replaced block `proven`" in "\n".join(res["lines"]), len(list(history.iterdir()))), (True, before_copies + 1))
        order = [m.group(1) for m in re.finditer(r"<!-- facts:([a-z-]+) -->", (task / "test-report.md").read_text(encoding="utf-8"))]
        check_eq("K-M1-10 and it stands between `bugs` and `review-gaps`",
                 order[order.index("bugs"):order.index("review-gaps") + 1], ["bugs", "exploratory", "review-gaps"])
    finally:
        cleanup(task.parents[2])


# --- SC1-14 FJ-A: the window that went over its cap ---------------------------------------------------------------------

def over_cap_windows_line() -> None:
    """KILLS: MJ41 (the line is not written), MJ42 (a line when there is no over-cap window / the story is `legacy`)."""
    task = story()
    try:
        facts = RF.build(task)
        check_eq("no over-cap window (or legacy): the fact is empty when the cut says nothing", facts["over_cap_windows"], [])
        check_not_in("no over-cap window (or legacy): no line", "over the cap", "".join(RF.render(facts).values()))
        legacy = dict(facts, over_cap_windows=None)
        check_not_in("no over-cap window (or legacy): a facts dict with no list has no line", "over the cap", RF.render(legacy)["review-gaps"])
        shown = dict(facts, over_cap_windows=[{"window": 2, "cases": 5, "cap": 4, "surface": "other"},
                                              {"window": 3, "cases": 3, "cap": 2, "surface": "ui"}])
        body = RF.render(shown)["review-gaps"]
        check_in("an over-cap window is one line of the report with its numbers", "Window 2 over the cap: 5 cases, cap 4.\n", body)
        check_in("an over-cap window is one line of the report with its numbers: one per window", "Window 3 over the cap: 3 cases, cap 2.\n", body)
        check_in("an over-cap window has a heading of its own, with the count (M1)", "### Windows over the cap — 2\n\nWindow 2 over the cap", body)
        check_not_in("an over-cap window stands under no 'nothing rejected' line", "None: the code critic left no test rejected.\n\nWindow", body)
        saved = RF.review_gap_lines, RF.run_gap_lines
        RF.review_gap_lines, RF.run_gap_lines = (lambda gaps: []), (lambda gaps: ["- `test_4` (TC-004) — the run failed"])
        try:
            with_runs = RF.render(shown)["review-gaps"]
        finally:
            RF.review_gap_lines, RF.run_gap_lines = saved
        head = with_runs.split("### Windows over the cap", 1)
        check_in("with runs left failing the over-cap lines are NOT under the runs heading (M1)", "### Runs left failing", head[0])
        check_eq("with runs left failing the over-cap lines are NOT under the runs heading (M1): their own heading follows", len(head), 2)
        check_not_in("with runs left failing the over-cap lines are NOT under the runs heading (M1): the runs part holds none", "over the cap", head[0])
        unread = RF.render(dict(shown, ledger=None))["review-gaps"]
        check_in("a ledger that is not read still shows the over-cap windows (the fact is the cut's, M1)", "Window 2 over the cap: 5 cases, cap 4.", unread)
        check_in("a ledger that is not read still says it is unknown", "## Review gaps — unknown", unread)
    finally:
        cleanup(task)
    import test_s5_plan_windows as TW
    root = TW.temp_dir("qa-rf-overcap-")
    try:
        TW.planned_story(root, TW.CASES6[:3], [list(TW.CASES6[:3])], config=(2, 2))
        check_eq("the fact is the controller's cut: one window of three cases over the cap of two",
                 RF._over_cap_windows(root), [{"window": 1, "cases": 3, "cap": 2, "surface": "other"}])
        TW.set_tests(root, [["TC-1"], ["TC-2"], ["TC-3"]])
        check_eq("no group over the cap: no window listed", RF._over_cap_windows(root), [])
    finally:
        TW.cleanup(root)


# --- C1-5c: the `review-gaps` block (one renderer, imported by gate B) ------------------------------------------------

REMARK = {"id": "F-1", "problem": "it never reads the flag", "expected": "the flag reads cancelled", "fix": "assert the flag",
          "cause": "test_defect"}


def gap_row(n: int, remarks=(REMARK,), window=True, state="review_rejected") -> dict:
    row = {"ref": f"ti_{n:04x}", "kind": "test", "state": state, "detail": f"tests/a.py::test_{n}", "function": f"test_{n}",
           "case": f"TC-{n:03d}"}
    if remarks is not None:     # an S7-window row has no `remarks` key (only an S5 window sets it)
        row["remarks"] = list(remarks)
    if window:
        row["repair_limit"] = {"stage": "S5", "counted": 2, "cap": 2, "reason": "cap"}
    return row


S5_WINDOW = {"stage": "S5", "cases": ["TC-001", "TC-002"], "tests": [], "reason": "cap", "counted": 2, "cap": 2, "token": "debt",
             "at": "", "refs": [], "fixed": False, "fixed_by": "", "missing": [], "remarks": []}


def gap_block(rows, windows=(), problem="") -> str:
    task = story(with_bug=False, extra_ledger=dict(ledger(rows=rows), repair_windows=list(windows), repair_windows_problem=problem))
    try:
        return RF.render(RF.build(task))["review-gaps"]
    finally:
        cleanup(task.parents[2])


def review_gaps_block() -> None:
    """The block stands after `bugs`; one line per window, then per test what the critic said, expected and asked; a test with no
    remark says so; 12 tests whole and 13 cut with "(+1 more in the ledger)"; an unmatched remark is on the window line; the
    renderer gate B imports is the block's own."""
    always = [b for b in G.REPORT_BLOCKS if b not in G.REPORT_BLOCKS_WHEN_PRESENT]
    check_eq("the block follows `bugs` in the grammar (the always-present blocks) and is not a gate-B block",
             (always[always.index("bugs") + 1], "review-gaps" in G.REPORT_BLOCKS_AFTER_GATE_B), ("review-gaps", False))
    check_eq("and the grammar puts `exploratory` right after `bugs`, before it (B1)",
             (G.REPORT_BLOCKS[G.REPORT_BLOCKS.index("bugs") + 1], G.REPORT_BLOCKS[G.REPORT_BLOCKS.index("bugs") + 2]),
             ("exploratory", "review-gaps"))
    window = dict(S5_WINDOW, remarks=[dict(REMARK, id="F-9", problem="a file no test is in")])
    body = gap_block([gap_row(1), gap_row(2, remarks=())], [window])
    lines = body.splitlines()
    check_eq("the heading counts the rejected tests", lines[0], "## Review gaps — 2 tests the code critic rejected")
    check_in("the window line: rounds against the limit, the cases, the person's choice",
             "Repair limit exhausted: 2 of 2 rounds about the tests themselves (TC-001, TC-002); you chose: debt.", body)
    check_in("a test: its function, case, and the critic's problem, expectation and fix",
             '- `test_1` (TC-001) — the critic: "it never reads the flag" — expected: "the flag reads cancelled" — to fix: "assert the flag"', body)
    check_in("a test with no remark says so (I4)", "- `test_2` (TC-002) — the critic's remarks were not recorded", body)
    check_in("a remark no test takes stays on the window line (edge 7.2)",
             '- not about one of these tests — the critic: "a file no test is in"', body)
    for needle in ("test_defect", "F-1", "d-1", "ti_"):
        check_not_in("no cause token, finding id, dispatch id or hash in the block: " + needle, needle, body)
    whole = gap_block([gap_row(n) for n in range(1, 13)], [S5_WINDOW])
    check_eq("12 tests are listed whole, with no overflow line", (whole.count("- `test_"), "more in the factory's record" in whole), (12, False))
    cut = gap_block([gap_row(n) for n in range(1, 14)], [S5_WINDOW])
    check_eq("13 tests: 12 listed and the overflow line", (cut.count("- `test_"), "(+1 more in the factory's record of the checks)" in cut), (12, True))
    again = RF.render(RF.build(task := story(with_bug=False, extra_ledger=dict(ledger(rows=[gap_row(1)]), repair_windows=[S5_WINDOW]))))
    try:
        check_eq("rebuilt twice, the block is the same", RF.render(RF.build(task))["review-gaps"], again["review-gaps"])
    finally:
        cleanup(task.parents[2])
    fixed = gap_block([], [dict(S5_WINDOW, fixed=True, fixed_by="d-2")])
    check_in("a window a later review cleared says so, without the dispatch id",
             "Earlier the repair limit was exhausted (TC-001, TC-002); a later review cleared those tests.", fixed)
    check_not_in("... and names no dispatch", "d-2", fixed)
    s7 = gap_block([], [dict(S5_WINDOW, stage="S7", cases=["TC-004"], reason="cap")])
    check_eq("an S7 window's line stands under the runs heading, not among the critic's rejections",
             "Repair limit exhausted" in s7.split("### Runs left failing", 1)[-1], True)
    check_eq("... and not above it", "Repair limit exhausted" in s7.split("### Runs left failing", 1)[0], False)
    runs = gap_block([dict(gap_row(4, remarks=None, window=False), state="failed:TEST_BUG", repair_limit={"stage": "S7", "counted": 2, "cap": 2, "reason": "cap"},
                           triage_words="the run failed: the locator is stale"),
                      gap_row(5)], [S5_WINDOW, dict(S5_WINDOW, stage="S7", cases=["TC-004"], tests=["i4"])])
    section = runs.split("### Runs left failing", 1)
    check_in("S7 rows have a heading of their own (`###`: the block holds one `##` section)", "### Runs left failing — 1", runs)
    check_in("... the run's row", "- `test_4` (TC-004) — the run failed: the locator is stale", runs)
    check_not_in("... the critic's 'not recorded' line appears only on S5 rows", "not recorded", section[1] if len(section) > 1 else "x")
    check_eq("the S7 row is not counted among the critic's rejections", runs.splitlines()[0], "## Review gaps — 1 test the code critic rejected")


def review_gaps_every_open_row_and_one_filter() -> None:
    """t-711 F1/F2. F1: the block lists EVERY open S5-window row whatever its state - a rejected test that failed at S6 and was
    triaged at S7 keeps its remarks, a delinked one says the test no longer exists, a window with no test open says so, a dead
    rejection no window covers stays out. F2: the function names and the critic's words go through the filter the verdict's reds use
    (`_shown`): the report that carries `ti_` / `cv_` / `work/` in a remark still passes the validator, the row says once that words
    were shortened, and a remark of which nothing is left prints that note and no empty quote."""
    ran = gap_row(1, state="failed:TEST_BUG")
    dead = dict(gap_row(2, remarks=()), dead=True)
    stray = dict(gap_row(3, remarks=None, window=False), dead=True)
    body = gap_block([ran, dead, stray], [dict(S5_WINDOW, refs=["a", "b"])])
    check_eq("F1: the failed-then-triaged row and the dead row are counted, the uncovered dead one is not",
             body.splitlines()[0], "## Review gaps — 2 tests the code critic rejected")
    check_in("F1: the triaged row keeps the critic's words under its S5 window",
             '- `test_1` (TC-001) — the critic: "it never reads the flag" — expected: "the flag reads cancelled" — to fix: "assert the flag"', body)
    check_in("F1: a dead row is listed and says the test no longer exists",
             "- `test_2` (TC-002) (the test no longer exists) — the critic's remarks were not recorded", body)
    check_not_in("F1: ... and a dead rejection no window covers stays out", "test_3", body)
    check_in("edge: a window with no test left open keeps its line, with the limit clause, and says so",
             "Repair limit exhausted: 2 of 2 rounds about the tests themselves (TC-001, TC-002); you chose: debt. No test is left open.",
             gap_block([], [dict(S5_WINDOW, refs=[])]))
    both = dict(gap_row(5, state="failed:TEST_BUG"), repair_limit={"stage": "S7", "counted": 2, "cap": 2, "reason": "cap"},
                triage_words="the run failed; the run's reason: boom")
    twice = gap_block([both], [S5_WINDOW, dict(S5_WINDOW, stage="S7", tests=["i5"])])
    check_in("F1: a row under an S5 and an S7 window stands among the critic's rejections", '- `test_5` (TC-005) — the critic: "it never reads the flag"', twice)
    check_in("... and among the runs", "- `test_5` (TC-005) — the run failed; the run's reason: boom", twice.split("### Runs left failing", 1)[-1])
    # F2
    hostile = {"id": "F-1", "problem": "it asserts nothing in work/out.txt after ti_ab12 ran", "expected": "the flag reads cancelled", "fix": "cv_1a2b"}
    # the shape reader flags `cv_`/`ti_` + 4 hex digits and a `work/` path (validate_artifacts.report_id_shape_hit, AR-13): the fixture words are those shapes
    nothing_left = {"id": "F-2", "problem": "ti_1a2b", "expected": "cv_2c3d", "fix": "work/z"}
    window_word = dict(REMARK, id="F-3", problem="see work/log.txt", expected="x", fix="y")
    rows = [dict(gap_row(1, remarks=(hostile, hostile)), function="cv_9f8e7d"), gap_row(2, remarks=(nothing_left,))]
    windows = [dict(S5_WINDOW, remarks=[window_word])]
    block = gap_block(rows, windows)
    note = "(a path in the critic's words was shortened)"
    check_in("F2: a name the filter takes out is said so, the test and its case stay", "- a test whose name is not shown (TC-001) —", block)
    check_in("F2: the words that pass stay, the others are left out", 'the critic: "it asserts nothing in after ran" — expected: "the flag reads cancelled"', block)
    check_in("F2: a part with nothing left is left out whole, never an empty quote", '"the flag reads cancelled" ' + note, block)
    check_in("F2: a remark of which nothing is left prints the note and nothing else", "- `test_2` (TC-002) — " + note, block)
    check_in("F2: a window's remark is filtered the same way", '- not about one of these tests — the critic: "see" — expected: "x" — to fix: "y" ' + note, block)
    check_eq("F2: the note stands ONCE on a row, however many remarks were shortened", block.split("- a test whose")[1].split("- `test_2`")[0].count(note), 1)
    check_not_in("F2: no empty quote", '""', block)
    for needle in ("ti_", "cv_", "work/"):
        check_not_in("F2: nothing the validator forbids in the block: " + needle, needle, block)
    task = story(with_bug=False, extra_ledger=dict(ledger(rows=rows), repair_windows=windows))
    try:
        legacy_report(task)
        RF.write(task)
        report = (task / "test-report.md").read_text(encoding="utf-8")
        check_in("F2: the whole report carries the block", "## Review gaps — 2 tests the code critic rejected", report)
        errors: list = []
        V.check_report_forbidden(task / "test-report.md", errors)
        check_eq("F2: the whole report passes check_report_forbidden", errors, [])
        write(task / "control.md", 'x\n\n- the critic: "' + hostile["problem"] + '"\n')
        control: list = []
        V.check_report_forbidden(task / "control.md", control)
        check_eq("F2 control: the same words unfiltered ARE refused by the validator (work/ and ti_)", len(control), 2)
    finally:
        cleanup(task.parents[2])


def review_gaps_null_unknown_and_head() -> None:
    """An empty carrier prints the null line (never nothing); an unreadable record is said; a ledger that cannot be read is
    `unknown`; a field the record lacks is named, not blank; the head's residual names the windows."""
    null = gap_block([])
    check_eq("nothing to list: the heading and the null line", null.splitlines()[0::2][:2],
             ["## Review gaps — 0 tests the code critic rejected", "None: the code critic left no test rejected."])
    check_in("an unreadable record is said in words", "Unknown — the record of the repair-limit answers cannot be read.",
             gap_block([], [], problem="the record of the repair-limit answers cannot be read"))
    bare = gap_block([gap_row(1)], [dict(S5_WINDOW, token="", counted=None, cap=None, cases=[])])
    check_in("a window lacking its choice, rounds and cases names each as not recorded",
             "Repair limit exhausted: the number of rounds is not recorded (cases not recorded); you chose: not recorded.", bare)
    odd = gap_block([gap_row(1, remarks=({"id": "F-1", "problem": "p"},))])
    check_in("a remark lacking expected and fix says so, never blank", '"p" — expected: not recorded — to fix: not recorded', odd)
    task = story(with_ledger=False)
    try:
        body = RF.render(RF.build(task))["review-gaps"]
        check_in("no ledger: the block says unknown", "## Review gaps — unknown", body)
    finally:
        cleanup(task.parents[2])
    # the head's residual: the ledger says no for reasons nobody explains, and a window ran out of rounds
    base = ledger(rows=[gap_row(1)], records=[{"code": "REVIEW", "entity": "x", "owner": "review", "detail": "ledger: x"}])
    facts = {"ledger": RF._ledger_facts(dict(base, repair_windows=[S5_WINDOW])), "requirements": None, "bugs": None, "tests": None}
    check_in("the residual names the windows", "1 waiting on the environment or a review; repair limit exhausted on 1 window",
             RF._verdict(facts)["first_reason"])
    facts["ledger"] = RF._ledger_facts(base)
    check_not_in("... and does not when the ledger names none", "repair limit exhausted", RF._verdict(facts)["first_reason"])


if __name__ == "__main__":
    main()
