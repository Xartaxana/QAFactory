#!/usr/bin/env python3
"""GW1-29 (F-3 variant b): an e2e-ui `automate` row without a highest-risk field is information, never a refusal.

The plan disputing itself (prose says risky, fields say moderate) is the strategist's judgement. The S3 detector warns and
exits 0; a branch of `if_answered` that makes the row such a row is warned about too; gate A prints one line "for your
information" and puts no choice to the person.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import SCRIPTS, check, check_in, check_not_in, cleanup, finish, run_script, temp_project  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import gate_brief  # noqa: E402
import planning_contract as P  # noqa: E402
from test_case_gates import plan_row, write_story  # noqa: E402


def row(rid="TS-8", **extra):
    base = {"id": rid, "impact": "moderate", "likelihood": "medium", "verification_depth": "normal",
            "disposition": "automate", "level": "e2e-ui"}
    base.update(extra)
    return base


def main() -> None:
    # the plain row: one record, naming the fields
    found = P.plan_warnings([row()])
    check("a moderate/medium/normal e2e-ui automate row gives exactly one record", len(found) == 1, str(found))
    check_in("and it names the row and the level", "TS-8: `automate` at level e2e-ui", found)

    # a branch makes the unearned e2e: the record names the branch
    branch = row("TS-9", disposition="manual", level="manual",
                 if_answered={"Q2": {"a": {"disposition": "automate", "level": "e2e-ui"},
                                     "b": {"disposition": "manual"}}})
    found = P.plan_warnings([branch])
    check("a branch that makes the row an unearned e2e is named with its question and letter",
          len(found) == 1 and found[0].startswith("TS-9 (Q2 = a): `automate` at level e2e-ui"), str(found))
    check("the `*` patch counts too", len(P.plan_warnings([row("TS-9", disposition="manual", level="manual",
          if_answered={"Q2": {"*": {"disposition": "automate", "level": "e2e-ui"}}})])) == 1)
    check("two branches of one row give one record", len(P.plan_warnings([row(
          "TS-9", disposition="manual", level="manual", if_answered={"Q2": {
              "a": {"disposition": "automate", "level": "e2e-ui"},
              "b": {"disposition": "automate", "level": "e2e-ui"}}})])) == 1)

    # edges: nothing to say
    check("a branch on a severe row is silent", not P.plan_warnings([row(
          "TS-9", impact="severe", disposition="manual", level="manual",
          if_answered={"Q2": {"a": {"disposition": "automate", "level": "e2e-ui"}}})]))
    check("a branch that makes the row `manual` at e2e-ui is silent", not P.plan_warnings([row(
          "TS-9", disposition="manual", level="manual",
          if_answered={"Q2": {"a": {"disposition": "manual", "level": "e2e-ui"}}})]))
    check("a branch patch that is not an object is passed over", not P.plan_warnings([row(
          "TS-9", disposition="manual", level="manual", if_answered={"Q2": {"a": "automate"}})]))
    check("an empty `{}` branch is not read", not P.plan_warnings([row(
          "TS-9", disposition="manual", level="manual", if_answered={"Q2": {"a": {}}})]))
    check("an `if_answered` that is not an object is passed over", not P.plan_warnings([row(
          "TS-9", disposition="manual", level="manual", if_answered=["Q2"])]))
    check("an `api` automate row is not this rule's business", not P.plan_warnings([row("TS-3", level="api")]))
    check("a severe-impact e2e row does not warn (case_gates::part_pyramid_warning)",
          not P.plan_warnings([row("TS-2", impact="severe", verification_depth="critical")]))
    check("`impact: None` is read as it is (the condition's text is unchanged)",
          "impact=None" in P.plan_warnings([row("TS-4", impact=None)])[0])
    check("no rows, no warnings", P.plan_warnings([]) == [] and P.plan_warnings(None) == [])

    # the gate's ids: one per row, no branch text
    ids = gate_brief.unearned_automation([row("TS-8", if_answered={"Q2": {"a": {"level": "e2e-ui"}}}), row("TS-5")])
    check("`unearned_automation` gives each id once, cut before the branch text", ids == ["TS-8", "TS-5"], str(ids))

    # the S3 detector: warns, exits 0
    root = temp_project("qa-plan-info-")
    try:
        write_story(root, "QA-29", [plan_row("TS-8", disposition="automate", level="e2e-ui")], mode="legacy")
        result = run_script("planning_contract.py", "--root", root, cwd=root)
        check_in("the S3 detector prints the row as a WARN", "WARN TS-8: `automate` at level e2e-ui", result.stdout)
        check("and exits 0: the warning is not a refusal", result.returncode == 0, result.stdout + result.stderr)
        check_not_in("with no REJECT in the output", "REJECT", result.stdout)
    finally:
        cleanup(root)

    # the card: for information, no choice, no "your call"
    lines = gate_brief._tail_sections({"unearned_automation": ["TS-8", "TS-5"], "plan_gloss": {"TS-8": "badge colour"}}, [])
    text = "\n".join(lines)
    check_in("the section says it is for information", "for your information", text)
    check_in("it names the rows with their gloss", "TS-8 (badge colour), TS-5", text)
    check_in("it says this is no question", "this is no question to you", text)
    check_not_in("it offers no choice", "your call", text)
    check_not_in("and no 'keep, move to manual'", "Keep, move", text)
    check("no rows, no section", not gate_brief._tail_sections({"unearned_automation": []}, []))

    finish("test_plan_warnings_info")


if __name__ == "__main__":
    main()
