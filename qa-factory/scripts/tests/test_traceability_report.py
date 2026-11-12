#!/usr/bin/env python3
"""The report's traceability table: every requirement, every case, one result word each.

TP1-15045 is the story that earned this file. What the person was handed said "verified 0"
beside eighteen green tests, printed one decision paragraph eleven times, carried six dead
duplicate rows and a stale "TC-014 blocked_by_env", and never mentioned BUG-4 at all — the
instance that proved it was red, triaged and filed, but no Then binding named it.

These tests assert the rules that fix each of those, on a synthetic story small enough to read:
dead and STALE records never enter a row, a partition the person decided about is one row with
their words, an instance no binding names is still a row, and every register R and plan TC is
present or `--check` fails.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import check, check_eq, check_in, check_not_in, cleanup, finish, temp_dir  # noqa: E402
from harness import SCRIPTS  # noqa: E402

sys.path.insert(0, str(SCRIPTS))

import traceability as T  # noqa: E402

REGISTER = """---
task: T-1
---

## Register

| R | Requirement (one verifiable statement) | source | derived_from | verifiable | ac_ref |
|---|---|---|---|---|---|
| R-1 | The diff marks the added node and nothing else | ac | — | yes | AC-1 |
| R-2 | Validate answers like update per input partition | feature | — | yes | TR-1 |
| R-3 | A removed node without layout meta has a defined position | derived | aspect:inputs | no | — |
"""

PLAN = """---
task: T-1
---
# Test plan - T-1

Not planned as rows: R-3 is a Gate A question (Q3) and appears once in the packet below.

## Plan

| TS | what we verify | R | defect hypothesis | impact class | priority | observable | oracle | disposition + reason | fit | level | technique |
|---|---|---|---|---|---|---|---|---|---|---|---|
| TS-1 | added node is marked | R-1 | contract @ diff | degraded | P2 | diff:src/diff.ts:22 | requirement:R-1 | `automate` — core AC | new | e2e-ui | decision table |
| TS-2 | validate parity per partition | R-2 | contract @ validate | degraded | P2 | diff:src/api.py:10 | requirement:R-2 | `automate` — feature TR-1 | new | api | partitions |

## Gate A question packet

1. R-3 / Q3 (once): where must a removed node without layout metadata appear? Code puts it at {0,0}.
"""

CASE_1 = """---
id: TC-001
title: Added node is marked and unchanged nodes are not
area: diff
task: T-1
covers: [R-1]
plan_row: TS-1
---
Requirements: R-1
Plan row: TS-1

## Then
1. The added node carries the ADDED badge.
2. No unchanged node carries it.
"""

CASE_2 = """---
id: TC-002
title: Validate answers like update per input partition
area: diff
task: T-1
covers: [R-2]
plan_row: TS-2
---
Requirements: R-2
Plan row: TS-2

## Then
1. Each partition returns its expected status.
2. The guardrail partition returns 400 with the guardrail message.
"""

MANIFEST = {
    "tests": [
        {"case": "SUPERSEDED-DUPLICATE-no-longer-a-case-id", "file": "tests/ui/test_diff.py",
         "selector": "test_marks_only_the_added_node", "status": "green",
         "note": "SUPERSEDED DUPLICATE - delinked aggregate row"},
        {"case": "TC-001", "covers": ["TC-001"], "file": "tests/ui/test_diff.py",
         "instance_id": "test_marks_only_the_added_node", "shape": "new", "status": "red"},
        {"case": "TC-002", "covers": ["TC-002"], "file": "tests/api/test_validate.py",
         "instance_id": "test_parity_per_partition[valid]", "shape": "parameterize",
         "status": "green", "critic_verdict": "approved", "probe": {"kind": "red"}},
        {"case": "TC-002", "covers": ["TC-002"], "file": "tests/api/test_validate.py",
         "instance_id": "test_parity_per_partition[self-reference]", "shape": "parameterize",
         "status": "red"},
    ],
    "then_bindings": [
        {"case": "TC-001", "then": 1, "instance_id": "test_marks_only_the_added_node",
         "status": "covered"},
        {"case": "TC-001", "then": 2, "instance_id": "test_marks_only_the_added_node",
         "status": "covered"},
        {"case": "TC-002", "then": 1, "instance_id": "test_parity_per_partition[valid]",
         "status": "covered"},
        {"case": "TC-002", "then": 2, "instance_id": "", "status": "unresolved",
         "reason": "blocked_by_env"},
    ],
    "unresolved": [
        {"case": "TC-002", "reason": "handed_to_person", "partition": "P-guardrail",
         "partitions": ["P-guardrail"],
         "detail": "api: run the P-guardrail partition where the AWS keys are"},
        {"case": "TC-001", "reason": "blocked_by_env", "partition": "stale-marker",
         "detail": "STALE, kept as a labeled marker only - the partition is green"},
    ],
}

RUN_REPORT = {
    "schema_version": 2, "task_id": "T-1", "execution_status": "failed",
    "current_results": [
        {"instance_id": "test_marks_only_the_added_node", "status": "failed", "profile_id": "e2e-ui",
         "reason": "AssertionError: Expected exactly one ADDED badge, found 2"},
        {"instance_id": "test_parity_per_partition[valid]", "status": "passed", "profile_id": "api"},
        {"instance_id": "test_parity_per_partition[self-reference]", "status": "failed",
         "profile_id": "api", "reason": "AssertionError: error details must name the input"},
    ],
    "results": [],
}

TRIAGE = {"schema_version": 1, "task_id": "T-1", "triage": [
    {"instance_id": "test_parity_per_partition[self-reference]", "attempt_id": "a1",
     "case": "TC-002", "verdict": "APP_BUG", "evidence": "source read"}]}

BUG = """---
id: BUG-1
title: The diff marks two nodes ADDED when one was added
severity: minor
found_by: TC-001
violates: requirement:R-1
gate_b_decision_id: gateB-T-1
---

## Actual result
Two nodes carry the badge.
"""

BUG_2 = """---
id: BUG-2
title: Validate rejects a self-reference without naming the input
severity: minor
found_by: TC-002
violates: requirement:R-2
gate_b_decision_id: gateB-T-1
---

## Actual result
The message omits the input.
"""


def story() -> Path:
    root = temp_dir("qa-traceability-")
    task = root / "qa-factory" / "artifacts" / "T-1"
    work = task / "work"
    (work / "test-cases" / "diff").mkdir(parents=True)
    (task / "state").mkdir(parents=True)
    (root / "qa-factory" / "bugs").mkdir(parents=True)
    (work / "requirements-register.md").write_text(REGISTER, encoding="utf-8")
    (task / "test-plan.md").write_text(PLAN, encoding="utf-8")
    (work / "test-cases" / "diff" / "TC-001.md").write_text(CASE_1, encoding="utf-8")
    (work / "test-cases" / "diff" / "TC-002.md").write_text(CASE_2, encoding="utf-8")
    (work / "automation-manifest.json").write_text(json.dumps(MANIFEST), encoding="utf-8")
    (work / "run-report.json").write_text(json.dumps(RUN_REPORT), encoding="utf-8")
    (work / "triage.json").write_text(json.dumps(TRIAGE), encoding="utf-8")
    (task / "pipeline.json").write_text(json.dumps({
        "ticket": "T-1", "size": "S",
        "gates": {"B": {"id": "gateB-T-1", "authorization_source": "draft MR, bugs in a file"}},
        "stage_overrides": [{"stage": "S8", "match": "keep it local",
                             "decision": "collect all bugs into a file"}]}), encoding="utf-8")
    (root / "qa-factory" / "bugs" / "BUG-1.md").write_text(BUG, encoding="utf-8")
    (root / "qa-factory" / "bugs" / "BUG-2.md").write_text(BUG_2, encoding="utf-8")
    return root


def row_for(rows: list, requirement: str, case: str = "", partition: str = "") -> dict:
    for row in rows:
        if row["requirement"] != requirement or (case and row["case"] != case):
            continue
        if partition and row.get("partition") != partition:
            continue
        if not partition and row.get("partition"):
            continue
        return row
    return {}


def verdict_bases() -> None:
    """The basis of a green row: the critic's verdict in its own words (FR-35), and for an approving
    verdict how sure the check is - from the one reader of receipts, never from whether some
    `probe` key exists on the row (D-0010/D-0012)."""
    import hashlib

    from harness import use_project
    import proof_level as PL
    root = story()
    try:
        (root / "qa-factory" / "config.json").write_text(json.dumps({"tests_root": "tests"}), encoding="utf-8")
        rel = "tests/api/test_validate.py"
        source = root / rel
        source.parent.mkdir(parents=True)
        code = "def test_v():\n    assert 1 + 1 == 2\n"
        source.write_text(code, encoding="utf-8")
        use_project(root)
        task = root / "qa-factory" / "artifacts" / "T-1"
        sha = hashlib.sha256(source.read_bytes()).hexdigest()
        s = T.Story(root / "qa-factory", task)

        def entry(name, receipt=None, **over):
            row = {"case": "TC-001", "covers": ["TC-001"], "file": rel, "instance_id": "i-" + name,
                   "critic_verdict": "approved", "new_or_changed": True,
                   "case_version_links": [{"case_id": "TC-001", "version": "cv_x"}]}
            row.update(over)
            if receipt is not None:
                path = task / "work" / "sensitivity-receipts" / f"{name}.json"
                path.parent.mkdir(parents=True, exist_ok=True)
                body = {"instance_id": row["instance_id"], "case_version": "cv_x", "test_content_hash": sha,
                        "source_revision": "s", "build_id": "b", "mutation": "invert",
                        "expected_assertion_failure": "x", "actual_failure": "x", "assertion_location": "t:1",
                        "restoration_evidence": "restored", "failure_kind": "assertion", "immutable": True,
                        "receipt_hash": "h-" + name}
                body.update(receipt)
                path.write_text(json.dumps(body), encoding="utf-8")
                row["sensitivity_proof"] = {"receipt_ref": {
                    "path": path.relative_to(task).as_posix(),
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}}
            return row

        live = {"proof_level": "live", "probe_tool": "probe_by_code.py", "mutation_kind": "assertion"}
        product = {"proof_level": "catches_broken_product", "probe_tool": "red_sandbox.py",
                   "mutation": "real_behavior", "mutation_kind": "real_behavior"}
        check_eq("approved and live: the words of both",
                 s._review_basis(entry("a", live)), "reviewed by the code critic - the check is live")
        check_eq("approved with fixes and the product level",
                 s._review_basis(entry("b", product, critic_verdict="approved_with_fixes")),
                 "reviewed by the code critic, fixes named - catches a broken product")
        check_eq("a new test with no receipt: not probed",
                 s._review_basis(entry("c")), "reviewed by the code critic - not probed")
        check_eq("rejected shows its own words, never 'review not recorded'",
                 s._review_basis(entry("d", live, critic_verdict="rejected")), "rejected by the code critic")
        check_eq("unverified shows its own words",
                 s._review_basis(entry("e", critic_verdict="unverified")), "the code critic could not verify it")
        check_eq("no verdict is the one that says nothing was recorded",
                 s._review_basis(entry("f", critic_verdict="")), "review not recorded")
        check_eq("a word the vocabulary lacks is said as such",
                 s._review_basis(entry("g", critic_verdict="maybe")), "review verdict not recognised: maybe")
        check_eq("a `probe` key with no receipt proves nothing any more",
                 s._review_basis(entry("h", probe={"kind": "red"})), "reviewed by the code critic - not probed")
        # The receipt was measured on these bytes; a comment added since keeps it, code changed does not.
        held = entry("i", dict(live, test_code_sha=PL.code_sha(code.encode("utf-8"), rel)))
        source.write_text(code + "# a note\n", encoding="utf-8")
        check_eq("a comment-only edit keeps the level and says which proof",
                 s._review_basis(held),
                 "reviewed by the code critic - the check is live (the receipt holds over a comment-only change)")
        source.write_text(code.replace("2", "3"), encoding="utf-8")
        check_eq("an assert changed: the level is not reached",
                 s._review_basis(held), "reviewed by the code critic - not probed")
        source.unlink()
        check_eq("a test file that cannot be found says unknown, not 'not probed'",
                 s._review_basis(held), "reviewed by the code critic - " + PL.unknown_words())
        source.write_text(code, encoding="utf-8")
        check_eq("a verdict is read stripped, as in the ledger",
                 s._review_basis(entry("k", critic_verdict=" unverified ")), "the code critic could not verify it")
        # A report never crashes over its vocabulary (P1): one note on stderr, a basis that says less.
        import contextlib
        import io
        real = PL.LEVELS_FILE
        PL.LEVELS_FILE = Path(real).with_name("no-such-levels.json")
        PL._reset()
        T._LEVELS_NOTE_SHOWN = False
        seen = io.StringIO()
        try:
            with contextlib.redirect_stderr(seen):
                first = s._review_basis(entry("l", live))
                second = s._review_basis(entry("m", live))
        finally:
            PL.LEVELS_FILE = real
            PL._reset()
        check_eq("no vocabulary: the basis says what it can", first, "critic verdict: approved (proof level not shown)")
        check_eq("and every row does", second, first)
        check_eq("the reader is told once", seen.getvalue().count("proof levels are not shown"), 1)
        check_in("with the door", "reinstall the plugin", seen.getvalue())
        s.manifest = {"tests": [], "unresolved": [{"case": "TC-001", "reason": "handed_to_person",
                                                    "detail": "api: run it yourself"}]}
        check_eq("a handed test is not asked for a probe",
                 s._review_basis(entry("j")), "reviewed by the code critic - not probed (handed to the person)")
    finally:
        cleanup(root)
        import os
        os.environ.pop("CLAUDE_PROJECT_DIR", None)
        import hooklib
        hooklib._PROJECT_ROOT_CACHE = None


# --- t-227c (P20): an expected value nobody confirmed is a gap, never a pass ----------------------------------------

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "oracle-provenance"


def _readiness(*, before=True) -> str:
    question = {"id": "Q7", "question": "Which status code must PUT return for a body that breaks two checks?",
                "source_says": [{"quote": "same codes as before", "where": "R-19"}],
                # HF4-7 (N7-2): the readings say which one is the behaviour now (`claim`); an unmarked pair confirms nothing
                "readings": [{"reading": "Intended", "from": "claim", "if_chosen": "x", "claim": "now"},
                             {"reading": "Regression", "from": "claim", "if_chosen": "y", "claim": "before"}],
                "severity": "major", "owner_role": "po_ba", "now": {"value": "403", "where": "diff"}}
    if before:
        question["before"] = {"value": "400", "where": "base revision"}
    return json.dumps({"open_questions": [question]})


def p20_unconfirmed_expectation() -> None:
    """TP1-15045 cmp2: TC_015 Then 4 (P-multi) had no source for its expected value; a guessed 403 was
    asserted and read as a requirement violation. Now the automator writes `expectation_unconfirmed` for it, and
    the table says `wait` with the question and the before/now - never `pass`, `deferred` or `not run`."""
    import question_register as QR
    unknown = {"case": "TC-002", "then": 2, "instance_id": None, "assertion_ref": None, "status": "unresolved",
               "reason": "expectation_unconfirmed", "question": "Q7", "observed": "403"}
    manifest = {"tests": [{"case": "TC-002", "covers": ["TC-002"], "file": "tests/api/test_validate.py",
                           "instance_id": "test_parity[valid]", "shape": "new", "status": "green",
                           "critic_verdict": "approved"}],
                "then_bindings": [{"case": "TC-002", "then": 1, "instance_id": "test_parity[valid]", "status": "covered"},
                                  unknown],
                "unresolved": []}
    root = story()
    try:
        qa, task = root / "qa-factory", root / "qa-factory" / "artifacts" / "T-1"
        (task / "work" / "automation-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        # 6a (t-122, accepted): a `pass` needs the instance's own run row (`case_stamp.run_row_for`); the shared RUN_REPORT has
        # no row for `test_parity[valid]`, so this fixture gives it one - "asserted and green" now means a green row EXISTS
        report = json.loads(json.dumps(RUN_REPORT))
        report["current_results"].append({"instance_id": "test_parity[valid]", "status": "passed", "profile_id": "api"})
        (task / "work" / "run-report.json").write_text(json.dumps(report), encoding="utf-8")
        (task / "work" / "requirements-readiness.json").write_text(_readiness(), encoding="utf-8")
        rows = T.build(qa, task)["rows"]
        first =[r for r in rows if r["case"] == "TC-002" and r["then"] == [1]]
        check_eq("Then 1, asserted and green, passes", [r["result"] for r in first], ["pass"])
        waiting = [r for r in rows if r["case"] == "TC-002" and r["then"] == [2]]
        check_eq("Then 2, unconfirmed: ONE row of its own", len(waiting), 1)
        check_eq("its result is `wait`: never a pass, never `deferred`", waiting[0]["result"], "wait")
        check_eq("the basis says what happened, which question holds it, and before/now",
                 waiting[0]["basis"], "expectation unconfirmed, check not executed — Q7: before 400, now 403")
        check_eq("and no test is shown for it (nothing was executed against it)", waiting[0]["tests"], [])
        check("the legend explains `wait` for an expected value nobody confirmed", "nobody confirmed" in table_legend(rows, qa, task))
        # before/now absent: said, never guessed (FR-41)
        (task / "work" / "requirements-readiness.json").write_text(_readiness(before=False), encoding="utf-8")
        again = [r for r in T.build(qa, task)["rows"] if r["case"] == "TC-002" and r["then"] == [2]][0]
        check_eq("a question that shows no `before` says `before: not recorded`", again["basis"],
                 "expectation unconfirmed, check not executed — Q7: before: not recorded, now 403")
        (task / "work" / "requirements-readiness.json").unlink()
        gone = [r for r in T.build(qa, task)["rows"] if r["case"] == "TC-002" and r["then"] == [2]][0]
        check_eq("a question the register does not hold still reads `wait`, naming both gaps", (gone["result"], gone["basis"]),
                 ("wait", "expectation unconfirmed, check not executed — Q7: before: not recorded, now: not recorded"))
        # the answered question: the binding was written before the answer and has not run against it (F19)
        (task / "work" / "requirements-readiness.json").write_text(_readiness(), encoding="utf-8")
        view = {q["id"]: q for q in QR.load(task)["questions"]}["Q7"]
        QR.record(task, "Q7", "answered", "Q7: a", "gate A", "driver", view["row_hash"], reading="a")
        after = [r for r in T.build(qa, task)["rows"] if r["case"] == "TC-002" and r["then"] == [2]][0]
        check_eq("an answer given after the binding was written changes nothing here: still `wait`", after["result"], "wait")
        check_in("and the basis says where it was answered, in the words of that place", "answered at gate A", after["basis"])
        # a Then both covered AND unconfirmed is never a pass
        both = dict(manifest, then_bindings=manifest["then_bindings"] + [{"case": "TC-002", "then": 1, "instance_id": None,
                    "status": "unresolved", "reason": "expectation_unconfirmed", "question": "Q7"}])
        (task / "work" / "automation-manifest.json").write_text(json.dumps(both), encoding="utf-8")
        mixed = [r for r in T.build(qa, task)["rows"] if r["case"] == "TC-002" and r["then"] == [1]]
        check_eq("a Then bound AND unconfirmed: the worst outcome wins, never `pass`", [r["result"] for r in mixed], ["wait"])
        # LEGACY (the temporal edge): the manifest as every story before t-227 wrote it
        (task / "work" / "automation-manifest.json").write_text(json.dumps(MANIFEST), encoding="utf-8")
        legacy = T.build(qa, task)["rows"]
        check_not_in("a legacy manifest has no `expectation unconfirmed` row anywhere", "expectation unconfirmed",
                     json.dumps(legacy, ensure_ascii=False))
        check_eq("and reads exactly as before: a no-instance binding is still the partition row's to say (no row of its own)",
                 [r["result"] for r in legacy if r["case"] == "TC-002" and r["then"] == [2]], [])
        # the cmp2 shape, row 1624-1631 of its automation-manifest.json (read-only, copied verbatim): TC_015's P-multi
        # was `contradicts_requirement` with "expected 403 ... owner-unconfirmed" and NO then_bindings row for it
        cmp2_row = {"case": "TC-002", "reason": "contradicts_requirement",
                    "detail": "R-19 P-multi: expected 403 (autonomous check before guardrail dry-run, pre-refactor order); observed 400 on PUT - "
                              "check order changed (instance [multi] RED); expected code owner-unconfirmed",
                    "partitions": ["multi"]}
        (task / "work" / "automation-manifest.json").write_text(json.dumps({"tests": manifest["tests"], "unresolved": [cmp2_row]}), encoding="utf-8")
        for bug_file in (root / "qa-factory" / "bugs").glob("*.md"):
            bug_file.unlink()  # cmp2 had no bug record for it: the row's own reading is what is under test
        cmp2 = row_for(T.build(qa, task)["rows"], "R-2", "TC-002", partition="multi")
        check_eq("CMP2 SHAPE: the legacy partition row still reads `wait` from its own detail (nothing new is read)", cmp2["result"], "wait")
        check_in("and says what the row said", "R-19 P-multi: expected 403", cmp2["basis"])
        check_not_in("and never the new words", "expectation unconfirmed", cmp2["basis"])
    finally:
        cleanup(root)

    # R without a case: an unanswered behaviour claim is `wait`, not `not planned` (the R-without-case branch)
    claims = ("| R-3 | The removed node keeps a defined position | derived | aspect:inputs | yes | — | diff:src/diff.ts:40 | degraded |\n"
              "\n## Behaviour claims\n\n| R | before | before_ref | now | now_ref | differs | question |\n|---|---|---|---|---|---|---|\n"
              "| R-3 | 400 | base:abc1234:src/diff.ts:9 | 403 | diff:+src/diff.ts:40 | yes | Q7 |\n")
    register = REGISTER.replace("| R | Requirement (one verifiable statement) | source | derived_from | verifiable | ac_ref |\n|---|---|---|---|---|---|",
                                "| R | Requirement | source | derived_from | verifiable | ac_ref | observable | impact |\n|---|---|---|---|---|---|---|---|")
    register = "\n".join(line for line in register.splitlines() if not line.startswith("| R-3 |")) + "\n" + claims
    register = register.replace("| R-1 | The diff marks the added node and nothing else | ac | — | yes | AC-1 |",
                                "| R-1 | The diff marks the added node and nothing else | ac | — | yes | AC-1 | diff:src/diff.ts:22 | blocked-flow |")
    register = register.replace("| R-2 | Validate answers like update per input partition | feature | — | yes | TR-1 |",
                                "| R-2 | Validate answers like update per input partition | feature | — | yes | TR-1 | diff:src/api.py:10 | degraded |")
    root = story()
    try:
        qa, task = root / "qa-factory", root / "qa-factory" / "artifacts" / "T-1"
        (task / "work" / "requirements-register.md").write_text(register, encoding="utf-8")
        (task / "work" / "requirements-readiness.json").write_text(_readiness(), encoding="utf-8")
        r3 = row_for(T.build(qa, task)["rows"], "R-3")
        check_eq("an unanswered claim's R reads `wait`, never `not planned`", r3["result"], "wait")
        check_eq("with the same basis as a Then nobody confirmed", r3["basis"],
                 "expectation unconfirmed, check not executed — Q7: before 400, now 403")
        view = {q["id"]: q for q in QR.load(task)["questions"]}["Q7"]
        QR.record(task, "Q7", "answered", "Q7: a", "gate A", "driver", view["row_hash"], reading="a")
        check_eq("CONTROL: once the claim's question is answered the R is no claim any more (today's reading)",
                 row_for(T.build(qa, task)["rows"], "R-3")["result"], "not planned")
        (task / "work" / "requirements-register.md").write_text(register.split("\n## Behaviour claims")[0] + "\n", encoding="utf-8")
        check_eq("LEGACY: a register with no `## Behaviour claims` section reads as today",
                 row_for(T.build(qa, task)["rows"], "R-3")["result"], "not planned")
    finally:
        cleanup(root)


def table_legend(_rows, qa, task) -> str:
    return T.build(qa, task)["legend"]["wait"]


def the_oracle_reader_is_one_door() -> None:
    """`--oracles`: what the code critic's `invented_expectation` reads. cmp2's TC_015 with the sources the case
    names: Thens 1-3 settled, Then 4 `unknown` until Q7 is answered, then `person` with the matching reading."""
    import question_register as QR
    from harness import run_script
    # the fixture's id is the project's own form (`TP1-15045_TC_015`); this story has no config naming it, so
    # the case is read under the default form - the oracle lines under test are the fixture's, unchanged
    text = (FIXTURES / "TP1-15045_TC_015.md").read_text(encoding="utf-8").replace(
        "updated: 2026-10-01", "updated: 2026-10-02").replace("TP1-15045_TC_015", "TC-015")
    text = text.replace("plan_row: TS-15\n", 'then_oracles: [{"then": 1, "source": "ac", "ref": "R-13"}, {"then": 2, "source": "ac", "ref": "R-13"}, '
                        '{"then": 3, "source": "requirement", "ref": "R-13"}, {"then": 4, "source": "unknown", "ref": "Q7"}]\n'
                        'question_thens: [{"question": "Q7", "then": 4, "readings": {"a": "HTTP 400, the behaviour now", "b": ""}, "not_needed": ""}]\n'
                        "plan_row: TS-15\n", 1)
    root = temp_dir("qa-oracles-")
    try:
        task = root / "qa-factory" / "artifacts" / "TP1-15045"
        (task / "work" / "test-cases" / "workflow-visual-diff").mkdir(parents=True)
        (task / "work" / "requirements-readiness.json").write_text((FIXTURES / "requirements-readiness.json").read_text(encoding="utf-8"), encoding="utf-8")
        (task / "work" / "test-cases" / "workflow-visual-diff" / "TC-015.md").write_text(text, encoding="utf-8")
        states = {k: v["thens"] for k, v in T.case_oracles(task).items()}
        thens = next(iter(states.values()))
        check_eq("Thens 1-3 are settled by their requirement, Then 4 is open (unknown, Q7 unanswered); the word is the STORED one "
                 "(FR-14, G1-0: `ac` and the new `requirement` both settle, neither is rewritten)",
                 [(t["then"], t["source"], t["state"]) for t in thens],
                 [(1, "ac", "settled"), (2, "ac", "settled"), (3, "requirement", "settled"), (4, "unknown", "open")])
        check_in("and the open one says why", "the question is open", thens[3]["why"])
        done = run_script("traceability.py", "--task-root", task, "--oracles")
        check_eq("--oracles exits 0", done.returncode, 0)
        printed = json.loads(done.stdout)
        check_eq("and prints JSON only (FR-14), the same reading", [t["state"] for t in next(iter(printed.values()))["thens"]],
                 ["settled", "settled", "settled", "open"])
        view = {q["id"]: q for q in QR.load(task)["questions"]}["Q7"]
        QR.record(task, "Q7", "answered", "Q7: a", "gate A", "driver", view["row_hash"], reading="a")
        thens = next(iter(T.case_oracles(task).values()))["thens"]
        check_eq("answered: the same Then reads `person` at read time, the case file untouched",
                 (thens[3]["source"], thens[3]["state"], thens[3]["expected"]), ("person", "settled", "HTTP 400, the behaviour now"))
        broken = text.replace("then_oracles: [", "then_oracles: [{", 1)
        (task / "work" / "test-cases" / "workflow-visual-diff" / "TC-015.md").write_text(broken, encoding="utf-8")
        got = next(iter(T.case_oracles(task).values()))
        check("a case whose line cannot be read says so under `problem`, no traceback (P1)", got["thens"] == [] and bool(got.get("problem")), str(got))
        legacy = text.split("then_oracles:")[0] + "plan_row: TS-15\n---\n" + text.split("---\n", 2)[2]
        (task / "work" / "test-cases" / "workflow-visual-diff" / "TC-015.md").write_text(legacy, encoding="utf-8")
        check_eq("LEGACY: a case with no `then_oracles` line has nothing to read", next(iter(T.case_oracles(task).values()))["thens"], [])
    finally:
        cleanup(root)


def rd1_18_manual_unread() -> None:
    """RD1-18: a valid manual `pass` reads `pass` from the FILES (A1 control), and a manual result that could not be READ is
    `not run` with that reason - never `pass`, never `{}` (the plan's reason would blame the plan for a failed read)."""
    import report_facts as RF
    import test_report_facts as TRF
    task = TRF.manual_story()
    try:
        plan = task / "test-plan.md"
        text = plan.read_text(encoding="utf-8")
        edited = text.replace("| `manual-agent` - an agent checks it in the running product | new | manual-agent | walkthrough |\n| TS-2",
                              "| `manual-agent` - server rule covered by TS-2 | new | e2e-ui | walkthrough |\n| TS-2", 1)
        check("RD1-18 the fixture plan was edited to `e2e-ui` + a reason", edited != text)
        plan.write_text(edited, encoding="utf-8")
        qa = task.parents[1]
        row = next(r for r in T.build(qa, task)["rows"] if r["case"] == "TC-001")
        check_eq("RD1-18 key 0: a valid manual pass on an `e2e-ui` row reads `pass` at the manual level",
                 (row["result"], row["level"]), ("pass", "manual-agent"))
        check_in("RD1-18 ... with the check's words", "checked by hand:", row["basis"])
        real = RF._manual

        def broken(*args, **kwargs):
            raise ValueError("run-report.json is not valid")
        RF._manual = broken
        try:
            story = T.Story(qa, task)
            got = story.manual_outcome("TC-001")
            rows = [r for r in T.build(qa, task)["rows"] if r["case"] == "TC-001"]
        finally:
            RF._manual = real
        check_eq("RD1-18 an unreadable manual result is `not run`, not `pass`, not {}", (got.get("result"), got.get("level")),
                 ("not run", "manual-agent"))
        check_in("RD1-18 ... and says the results could not be read", "the manual results could not be read: ValueError", got.get("basis", ""))
        check_not_in("RD1-18 ... without the plan's reason", "server rule", got.get("basis", ""))
        check_eq("RD1-18 the table is still built over it (P1): the case row reads `not run`", [r["result"] for r in rows], ["not run"])
        stale = TRF.manual_story(rows=[])
        try:
            plain = T.Story(stale.parents[1], stale)
            check_eq("RD1-18 edge: no record and a read that worked keeps the plan's reading ({})", plain.manual_outcome("TC-001"), {})
        finally:
            cleanup(stale.parents[2])
    finally:
        cleanup(task.parents[2])


def rd1_19_triage_reason() -> None:
    """RD1-19: the triage row's sentence (`detail`, else `control.observed`) reaches the table's basis through the ONE reader
    `contract.triage_reason`; with no carrier the old phrase stays; the safety check names a table that fell back to it."""
    import contextlib
    import io

    import contract as C
    import report_facts as RF
    for label, value, want in (
            ("detail first", {"detail": "  the badge\n is  drawn twice ", "control": {"observed": "x"}, "reason": "r"}, "the badge is drawn twice"),
            ("then control.observed", {"control": {"observed": "same diff without the change"}, "reason": "r"}, "same diff without the change"),
            ("then reason", {"reason": "older spelling"}, "older spelling"),
            ("nothing", {}, ""), ("a non-string detail", {"detail": 5, "reason": ["x"]}, ""),
            ("control not an object", {"control": "oops"}, ""), ("a row that is not an object", None, "")):
        check_eq(f"RD1-19 triage_reason: {label}", C.triage_reason(value), want)
    root = story()
    try:
        task = root / "qa-factory" / "artifacts" / "T-1"
        qa = root / "qa-factory"
        (root / "qa-factory" / "bugs" / "BUG-2.md").unlink()    # no filed bug: the basis is the triage branch

        def basis_for(row_extra: dict, verdict: str = "APP_BUG") -> str:
            row = {"instance_id": "test_parity_per_partition[self-reference]", "attempt_id": "a1", "case": "TC-002",
                   "verdict": verdict, "evidence": "source read"}
            row.update(row_extra)
            (task / "work" / "triage.json").write_text(json.dumps({"schema_version": 1, "task_id": "T-1", "triage": [row]}),
                                                       encoding="utf-8")
            return row_for(T.build(qa, task)["rows"], "R-2", "TC-002", partition="self-reference")["basis"]

        check_in("RD1-19 `detail` without `reason` reaches the basis", "the message omits the input",
                 basis_for({"detail": "the message omits the input"}))
        check_in("RD1-19 only `control.observed` under ASSERT_STRICTER reaches the basis", "same difference without the change",
                 basis_for({"control": {"result": "effect_without_change", "observed": "same difference without the change"}},
                           "ASSERT_STRICTER"))
        empty = basis_for({})
        check_in("RD1-19 nothing recorded: the old phrase", "no reason recorded", empty)
        # the safety check: a basis that fell back to the phrase beside a triage row that HAS a reason
        row = {"case": "TC-002", "requirement": "R-2", "basis": "red run, triaged APP_BUG: no reason recorded; bug not filed",
               "tests": [{"instance_id": "test_parity_per_partition[self-reference]"}]}
        basis_for({"detail": "the message omits the input"})
        seen = io.StringIO()
        with contextlib.redirect_stderr(seen):
            lines = RF._reason_vs_table(task, [row])
            quiet = RF._reason_vs_table(task, [dict(row, basis="red run, triaged APP_BUG: the message omits the input; bug not filed")])
        check_eq("RD1-19 the safety check names the table row and the reason", len(lines), 1)
        check_in("RD1-19 ... on stderr as `report: ...`", "report: The table gives no reason for TC-002; the triage row says: the message omits the input", seen.getvalue())
        check_eq("RD1-19 a basis that carries its reason gives no line", quiet, [])
        check_eq("RD1-19 the row itself is not changed", row["basis"], "red run, triaged APP_BUG: no reason recorded; bug not filed")
        basis_for({})
        with contextlib.redirect_stderr(io.StringIO()):
            check_eq("RD1-19 a triage row with no reason: no line", RF._reason_vs_table(task, [row]), [])
    finally:
        cleanup(root)


def rd1_9a_rejected_is_not_pass() -> None:
    """RD1-9a: a green run of a test the critic rejected is `blocked`, never `pass`; after a review that approves it, `pass`.
    `REJECTED` (not the critic's word) keeps today's reading. The legend says what `blocked` now also means."""
    root = story()
    try:
        task = root / "qa-factory" / "artifacts" / "T-1"
        path = task / "work" / "automation-manifest.json"
        base = json.loads(path.read_text(encoding="utf-8"))

        def valid_row(verdict: str) -> dict:
            doc = json.loads(json.dumps(base))
            next(t for t in doc["tests"] if t.get("instance_id") == "test_parity_per_partition[valid]")["critic_verdict"] = verdict
            path.write_text(json.dumps(doc), encoding="utf-8")
            return row_for(T.build(root / "qa-factory", task)["rows"], "R-2", "TC-002")

        approved = valid_row("approved")
        check_eq("RD1-9a green + approved: pass", approved["result"], "pass")
        rejected = valid_row("rejected")
        check_eq("RD1-9a green + rejected: blocked, never pass", rejected["result"], "blocked")
        check_in("RD1-9a ... the basis says the critic has not reviewed the change", "does not count until the critic reviews",
                 rejected["basis"])
        check_eq("RD1-9a green + ` rejected ` (padded) reads as rejected", valid_row(" rejected ")["result"], "blocked")
        check_eq("RD1-9a green + `REJECTED` is not the critic's word: the table keeps `pass` with its own words",
                 valid_row("REJECTED")["result"], "pass")
        check_in("RD1-9a the legend of `blocked` names the critic's rejection", "critic rejected", T.LEGEND["blocked"])
        import report_facts as RF
        test = {"function": "test_x", "case": "TC-1", "remarks": [], "name_cut": False}
        check_in("RD1-9a the report's line with no remark and no file keeps `not recorded`", "the critic's remarks were not recorded",
                 RF._test_lines(test)[0])
        check_in("RD1-9a ... and with a findings file points to it", "the critic's remarks are in work/test-code/critic-findings.md",
                 RF._test_lines(dict(test, remarks_carrier="work/test-code/critic-findings.md"))[0])
    finally:
        cleanup(root)


def main() -> None:
    rd1_9a_rejected_is_not_pass()
    rd1_19_triage_reason()
    rd1_18_manual_unread()
    p20_unconfirmed_expectation()
    the_oracle_reader_is_one_door()
    root = story()
    try:
        task = root / "qa-factory" / "artifacts" / "T-1"
        table = T.build(root / "qa-factory", task)
        rows = table["rows"]
        check_eq("the table declares its schema", table["schema_version"], T.SCHEMA_VERSION)
        check_eq("the legend covers the whole result vocabulary",
                 sorted(table["legend"]), sorted(list(__import__("contract").TRACE_RESULTS)))

        added = row_for(rows, "R-1", "TC-001")
        check_eq("a red instance with a filed bug names the record", added["result"], "bug")
        check_eq("and the record, not the draft id", added["bug"], "BUG-1")
        check_in("the basis is what the run said", "Expected exactly one ADDED badge", added["basis"])
        check_eq("both Then clauses travel in one row", added["then"], [1, 2])
        check_eq("the shape comes from the manifest", added["shape"], "new")
        check_eq("the level comes from the plan row the case names", added["level"], "e2e-ui")

        check_not_in("a delinked aggregate never reaches a row", "SUPERSEDED",
                     json.dumps(rows, ensure_ascii=False))
        check_eq("a STALE unresolved row is not a partition the person must answer",
                 row_for(rows, "R-1", "TC-001", partition="stale-marker"), {})

        valid = row_for(rows, "R-2", "TC-002")
        check_eq("a green instance with a verdict passes", valid["result"], "pass")
        check_eq("and says what reviewed it and that nothing was asked of a test whose case was handed (t-175)",
                 valid["basis"], "reviewed by the code critic - not probed (handed to the person)")
        verdict_bases()

        guardrail = row_for(rows, "R-2", "TC-002", partition="P-guardrail")
        check_eq("a handed partition waits for the person", guardrail["result"], "wait")
        check_in("with the recorded reason beside it", "where the AWS keys are", guardrail["basis"])
        check_eq("and the Then whose only binding is that partition is not repeated",
                 [r for r in rows if r["case"] == "TC-002" and r["then"] == [2]], [])

        unbound = row_for(rows, "R-2", "TC-002", partition="self-reference")
        check_eq("an instance no Then binding names is still a row", unbound["result"], "bug")
        check_eq("and it names its bug record", unbound["bug"], "BUG-2")

        not_planned = row_for(rows, "R-3")
        check_eq("a register R with no plan row is 'not planned'", not_planned["result"], "not planned")
        check_in("with the gate-A question as its reason", "Q3", not_planned["basis"])

        check_eq("--check is green when nothing is missing", T.check(root / "qa-factory", task, table), [])
        short = dict(table, rows=[r for r in rows if r["requirement"] != "R-3"])
        check_in("a missing requirement is one line of --check", "R-3 is in the register",
                 T.check(root / "qa-factory", task, short))
        bad = dict(table, rows=[dict(rows[0], result="failed")])
        check_in("a result outside the vocabulary is refused", "trace.result must be one of",
                 T.check(root / "qa-factory", task, bad))

        rendered = T.render(table)
        check_in("the appendix carries the column contract",
                 "| R | What we verify | TC · Then | Test | Level · shape | Result | Basis |", rendered)
        check_in("a bug row prints the record instead of the word", "**BUG-1**", rendered)
        check_in("the test file legend names every file once",
                 "= `tests/api/test_validate.py`", rendered)
        check_not_in("no work/ path reaches the person", "work/", rendered)
        check_not_in("and no content-address hash", "cv_", rendered)

        path = T.write(task, table)
        check("--write puts the table under work/", path.parent.name == "work", str(path))
        check_eq("and it round-trips", json.loads(path.read_text(encoding="utf-8"))["task"], "T-1")

        gate_b = T.decided_at_gate_b(json.loads((task / "pipeline.json").read_text(encoding="utf-8")))
        check_in("the gate-B section quotes the person", '"draft MR, bugs in a file"', gate_b)
        check_in("and the S8 decision verbatim", "collect all bugs into a file", gate_b)
    finally:
        cleanup(root)
    finish("traceability report table")


if __name__ == "__main__":
    main()
