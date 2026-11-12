#!/usr/bin/env python3
"""A red test is a draft until someone reproduces it (TP1-15045).

Every shape here is that story's own. BUG-1 came from
`popup.popup_container.locator("span", has_text=DIFF_BADGE_ADDED).count() == 1` — a
case-insensitive substring match that counted the popup legend's "Added" chip as a second
badge, deterministically. BUG-2 came from a Then nobody had triaged, on a case the critic had
listed as unreviewed. Neither was ever reproduced by hand: the "steps" were the assertion line.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness import (check, check_eq, check_in, check_not_in, cleanup,  # noqa: E402
                     finish, temp_dir)

import contract as C  # noqa: E402
import delivery_summary as DS  # noqa: E402
import factory_dashboard as FD  # noqa: E402
import gate_preflight as GP  # noqa: E402
import s5_precheck as P  # noqa: E402
import traceability as T  # noqa: E402
import validate_artifacts as V  # noqa: E402

BADGE_TEST = '''"""Tests for TC-003."""


def test_added_badge(popup):
    """@case TC-003."""
    assert popup.popup_container.locator("span", has_text=DIFF_BADGE_ADDED).count() == 1


def test_added_badge_scoped(popup):
    """@case TC-003."""
    assert node_chrome("n-7").locator("[data-testid=diff-badge-added]").count() == 1
'''

DRAFT = {
    "title": "a removed node is drawn at the origin",
    "impact": "degraded",
    "violates": "requirement:R-4",
    "case": "TC-004",
    "triage_ref": {"instance_id": "test_removed_node[chromium]", "attempt_id": "a3"},
    "manual_steps": ["open the diff of revision 4 against revision 3",
                     "the removed node sits at the top left corner, not among its neighbours"],
    "confirmation": "unconfirmed",
    "mechanism": {"status": "unknown", "why": "the cause was not traced in this fixture"},
    "red_test_none": "manual check only",
}

LEGACY_BUG = """---
id: BUG-1
title: two ADDED badges in the node popup
severity: minor
status: Open
area: diff
found_by: TC-003
violates: requirement:R-2
impact: cosmetic
created: 2026-09-20
---

## User impact
A reader of the popup counts two badges.

## Initial state
A revision with one added node.
"""


# --- S5: a count of what a substring matched --------------------------------------------------

def smells_name_the_substring_count() -> None:
    root = temp_dir("qa-bug-smell-")
    try:
        path = root / "test_badges.py"
        path.write_text(BADGE_TEST, encoding="utf-8")
        pyfile = P.PyFile(path, BADGE_TEST)
        targets = [(pyfile, name, node) for name, node in sorted(pyfile.functions.items())]
        findings = []
        P.check_smells("TC-003", "", [pyfile], targets, findings)
        messages = [f["message"] for f in findings]
        check_in("a count compared with a number over a `has_text` match is a finding",
                 "case-insensitive SUBSTRING match", messages)
        check_in("and the finding names the incident that taught it",
                 "legend's 'Added' chip", messages)
        check_eq("exactly one line of that file is named, not both",
                 sum(1 for m in messages if "SUBSTRING" in m), 1)
        check_not_in("a count scoped by a test id is not a finding",
                     "test_badges.py:10", messages)
        check("the fix names the scoped element, never a second matcher",
              all("data-testid" in f["fix"] for f in findings if "SUBSTRING" in f["message"]))
    finally:
        cleanup(root)


# --- gate B: a draft rests on a verdict and on steps a person can follow -----------------------

def story(root: Path, draft: dict, *, reviewed: bool = True, triage: bool = True) -> Path:
    """One story at gate B: a bug draft, the triage row behind it, the critic's roll-call."""
    (root / "qa-factory").mkdir(parents=True, exist_ok=True)
    (root / "qa-factory" / "config.json").write_text("{}", encoding="utf-8")
    task = root / "qa-factory" / "artifacts" / "TP1-15045"
    (task / "work" / "bug-drafts").mkdir(parents=True, exist_ok=True)
    (task / "pipeline.json").write_text(json.dumps({"ticket": "TP1-15045"}), encoding="utf-8")
    (task / "work" / "bug-drafts" / "removed-node.json").write_text(
        json.dumps(draft), encoding="utf-8")
    rows = [{"instance_id": "test_removed_node[chromium]", "attempt_id": "a3",
             "test": "tests/test_diff.py::test_removed_node", "verdict": "APP_BUG",
             "evidence": "evidence/run.json"}] if triage else []
    (task / "work" / "triage.json").write_text(json.dumps({"triage": rows}), encoding="utf-8")
    findings = (task / "work" / "test-cases" / "critic-findings.md")
    findings.parent.mkdir(parents=True, exist_ok=True)
    findings.write_text("## Roll-call\n\n| Plan row | Case | Reviewed |\n|---|---|---|\n"
                        f"| TS-4 | TC-004 | {'yes' if reviewed else 'no'} |\n", encoding="utf-8")
    return task


def bug_drafts_of(task: Path) -> list:
    rehearsal = GP.Rehearsal(task, "B")
    rehearsal.check_bug_drafts()
    return rehearsal.findings


def a_draft_without_a_verdict_is_the_factory_s_own() -> None:
    root = temp_dir("qa-bug-gateb-")
    try:
        task = story(root, {k: v for k, v in DRAFT.items() if k != "triage_ref"})
        findings = bug_drafts_of(task)
        check_eq("a draft with no triage_ref yields exactly one finding", len(findings), 1)
        check_eq("and it is the factory's to repair, never a question for the person",
                 findings[0]["class"], GP.FACTORY_FIXABLE)
        check_in("the finding names the case and the stage that owns it",
                 "TC-004 is red with no triage verdict", [findings[0]["message"]])
        check_in("and the fix says how a person's word passes it, as a line they write (t-357: no script named)",
                 f"write `{findings[0]['id']}: accept` with your reason", findings[0]["fix"])
        check_eq("and the stage and block that word is recorded against travel as data (t-357)",
                 [(d["stage"], d["block"]) for d in findings[0]["waives"]], [("S9", "TC-004 bug draft without a triage verdict")])

        pipeline = json.loads((task / "pipeline.json").read_text(encoding="utf-8"))
        pipeline["stage_overrides"] = [
            {"stage": "S9", "match": "TC-004 is red with no triage verdict",
             "decision": "I saw it myself on the stand, file it", "at": "2026-09-24T10:00:00"}]
        (task / "pipeline.json").write_text(json.dumps(pipeline), encoding="utf-8")
        check_eq("a person's recorded word passes the block", bug_drafts_of(task), [])
    finally:
        cleanup(root)


def a_draft_from_an_unreviewed_case_cannot_become_a_bug() -> None:
    root = temp_dir("qa-bug-unreviewed-")
    try:
        task = story(root, dict(DRAFT), reviewed=False)
        messages = [f["message"] for f in bug_drafts_of(task)]
        check_in("a case the critic never read is named", "never reached the case critic",
                 messages)
        check_eq("and nothing else is wrong with that draft", len(messages), 1)
    finally:
        cleanup(root)


def a_draft_whose_steps_are_the_assertion_line_is_an_observation() -> None:
    root = temp_dir("qa-bug-steps-")
    try:
        task = story(root, {k: v for k, v in DRAFT.items() if k != "manual_steps"})
        messages = [f["message"] for f in bug_drafts_of(task)]
        check_in("a draft with no manual steps is named", "carries no `manual_steps`", messages)
        check_in("and the reason is stated as the factory's own defect",
                 "which nobody can follow", messages)
    finally:
        cleanup(root)


def a_verdict_that_is_not_app_bug_never_becomes_a_bug() -> None:
    root = temp_dir("qa-bug-verdict-")
    try:
        task = story(root, dict(DRAFT))
        triage = json.loads((task / "work" / "triage.json").read_text(encoding="utf-8"))
        triage["triage"][0]["verdict"] = "TEST_BUG"
        (task / "work" / "triage.json").write_text(json.dumps(triage), encoding="utf-8")
        messages = [f["message"] for f in bug_drafts_of(task)]
        check_in("a TEST_BUG verdict behind a bug draft is a finding",
                 "whose verdict is TEST_BUG, not APP_BUG", messages)
    finally:
        cleanup(root)


def a_complete_draft_passes_the_rehearsal() -> None:
    root = temp_dir("qa-bug-clean-")
    try:
        task = story(root, dict(DRAFT))
        check_eq("a triaged draft on a reviewed case with steps raises nothing",
                 bug_drafts_of(task), [])
        result = GP.run(task, "B")
        check_not_in("and the whole gate B rehearsal says nothing about bug drafts either",
                     "bug_drafts", [f["check"] for f in result["findings"]])
    finally:
        cleanup(root)


# --- the record: legacy bugs still validate, new ones state their confirmation -----------------

def a_legacy_bug_still_validates_and_reads_as_confirmed() -> None:
    root = temp_dir("qa-bug-legacy-")
    try:
        path = root / "BUG-1.md"
        path.write_text(LEGACY_BUG, encoding="utf-8")
        errors = []
        V.check_bug(path, errors)
        check_eq("a bug filed before 0.7.16 validates unchanged", errors, [])
        check_eq("and reads as one a person stood behind",
                 C.bug_confirmation({"id": "BUG-1"}), "confirmed_by_person")

        fresh = LEGACY_BUG.replace("created: 2026-09-20", "created: 2026-09-25")
        path.write_text(fresh, encoding="utf-8")
        errors = []
        V.check_bug(path, errors)
        check_in("a bug filed now must say who has seen it", "'confirmation' is missing", errors)

        path.write_text(fresh.replace("impact: cosmetic", "impact: cosmetic\nconfirmation: maybe"),
                        encoding="utf-8")
        errors = []
        V.check_bug(path, errors)
        check_in("and an invented value is refused by name", "confirmation 'maybe' outside",
                 errors)

        path.write_text(
            fresh.replace("impact: cosmetic", "impact: cosmetic\nconfirmation: unconfirmed"),
            encoding="utf-8")
        errors = []
        V.check_bug(path, errors)
        check_eq("a value from the closed list is accepted", errors, [])
    finally:
        cleanup(root)


# --- what a person reads: the two groups apart ------------------------------------------------

def the_report_prints_the_two_groups() -> None:
    records = [{"id": "BUG-1", "confirmation": "confirmed_by_person"},
               {"id": "BUG-2", "confirmation": "unconfirmed"},
               {"id": "BUG-3", "confirmation": "unconfirmed"},
               {"id": "BUG-4"}]
    check_eq("the headline counts the two groups apart", T.bug_headline(records),
             "Product bugs — 2 confirmed · 2 unconfirmed.")
    check_eq("a bug with no confirmation at all counts as confirmed, not as a doubt",
             T.bug_groups(records)["confirmed_by_person"], ["BUG-1", "BUG-4"])
    check_eq("no bugs at all is not a count", T.bug_headline([]), "Product bugs — none.")
    table = {"rows": [{"requirement": "R-2", "what": "the badge", "case": "TC-003", "then": [3],
                       "tests": [], "level": "e2e-ui", "shape": "new", "result": "bug",
                       "bug": "BUG-2", "basis": "requirement:R-2"}],
             "bugs": records}
    rendered = T.render(table)
    check_in("the appendix says it in the same words", "2 confirmed · 2 unconfirmed", rendered)
    check_in("and an unconfirmed row is marked in the table itself",
             "**BUG-2**<br>unconfirmed", rendered)

    summary = {"counts": {}, "gaps": [],
               "bugs": [{"ref": "bugs/BUG-1.md", "state": "published", "external_id": "X-1",
                         "confirmation": "confirmed_by_person"},
                        {"ref": "work/bug-drafts/badge.json", "state": "draft",
                         "confirmation": "unconfirmed"}]}
    fragment = DS.render(summary)
    check_in("the delivery fragment splits them too", "Product bugs — 1 confirmed · 1 unconfirmed",
             fragment)
    check_in("and says what unconfirmed means, in the person's terms",
             "it counts toward nothing", fragment)


def the_board_splits_them_too() -> None:
    rows = FD.story_bug_rows(
        [{"id": "BUG-1", "title": "two ADDED badges", "severity": "minor", "found_by": "TC-003",
          "violates": "requirement:R-2", "area": "diff", "confirmation": "unconfirmed"}],
        [{"id": "draft-2", "title": "a removed node at the origin", "case": "TC-004",
          "confirmation": "unconfirmed"}],
        {"TC-003", "TC-004"})
    check_eq("every bug row of the board carries its confirmation",
             [r["confirmation"] for r in rows], ["unconfirmed", "unconfirmed"])
    check_eq("the head line never says a bare number again",
             FD.bug_confirmation_split(rows), "2 unconfirmed")
    check_in("and the table has a column of its own",
             "<th>Confirmed</th>", FD.story_bugs_table(rows))


if __name__ == "__main__":
    smells_name_the_substring_count()
    a_draft_without_a_verdict_is_the_factory_s_own()
    a_draft_from_an_unreviewed_case_cannot_become_a_bug()
    a_draft_whose_steps_are_the_assertion_line_is_an_observation()
    a_verdict_that_is_not_app_bug_never_becomes_a_bug()
    a_complete_draft_passes_the_rehearsal()
    a_legacy_bug_still_validates_and_reads_as_confirmed()
    the_report_prints_the_two_groups()
    the_board_splits_them_too()
    finish("bug confirmation (TP1-15045)")
