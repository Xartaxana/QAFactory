#!/usr/bin/env python3
"""A stand gap carries its own fix, and a fixture is not a stand.

Both shapes are TP1-15045's (22.09.2026). The automator found the exact cause of a
blocked partition — `customer-config.yaml:304-311`, `features:subWorkflow enabled: false` —
and the manifest carried a paragraph of prose, so the person read "blocked by the
environment" instead of the one line that would have unblocked it. In the same story a
workflow-validation case was parked on the stand because the shared `assistant` fixture
wanted a Jira tool and an integration that the case's own Then never mentions: the test's
choice of data, filed as the stand's fault.

What is checked here: the refusal lands on the dispatch that can still repair it and nowhere
else, it names the variable and never its value, a person's word passes it, and the writers
(`manifest_put`) and readers (`validate_artifacts`, `stage_guard`) agree about the field.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness import (check, check_eq, check_in, check_not_in, cleanup, finish,  # noqa: E402
                     temp_dir)

import contract as C  # noqa: E402
import manifest_put as M  # noqa: E402
import s5_precheck as P  # noqa: E402
import stage_guard as SG  # noqa: E402
import validate_artifacts as V  # noqa: E402

CASE_MD = """---
id: TC-700
status: Approved
preconditions:
  - id: PC-1
    what: the sub-workflow feature flag is on
    check: {http: "/api/health"}
---
## Given
A workflow with a sub-workflow node.

## When
The workflow is validated.

## Then
1. The call returns state `SUBWORKFLOW`.
"""

TEST_PY = '''"""Tests for TC-700."""


def test_subworkflow_state(client, assistant):
    """@case TC-700."""
    assert_that(client.validate()["state"], equal_to("SUBWORKFLOW"))
'''

CONFTEST_PY = '''import pytest


@pytest.fixture
def assistant():
    return {"id": "a"}


@pytest.fixture
def client():
    return None
'''

REMEDY = {"kind": "flag", "where": "testproject1/config/customer-config.yaml:306-311",
          "change": "enabled: true", "restart": "testproject1, testproject1-ui"}
# A made-up value in the shape a role would paste: the point of the rule is that it never
# reaches an artifact, so the fixture that proves the rule carries no real one either.
LEAKED_LINE = "set NON_OWNER_PASSWORD=" + "n0t-a-real-" + "value7 in .env"


def make_story(root: Path, unresolved: list, scope=("TC-700",), overrides=()) -> Path:
    task = root / "qa-factory" / "artifacts" / "QA-700"
    (task / "work" / "test-cases").mkdir(parents=True)
    (task / "work" / "run-blocks").mkdir(parents=True)
    (task / "state").mkdir(parents=True)
    manifest = {"tests": [{"case": "TC-700", "file": "tests/test_sub.py", "marker": "TC-700",
                           "test_function": "test_subworkflow_state", "status": "red"}],
                "unresolved": unresolved,
                "then_bindings": [{"case": "TC-700", "then": 1,
                                   "instance_id": "test_subworkflow_state",
                                   "assertion_ref": "tests/test_sub.py:5",
                                   "status": "covered"}]}
    (task / "work" / "automation-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    (task / "work" / "test-cases" / "TC-700.md").write_text(CASE_MD, encoding="utf-8")
    (task / "state" / "controller.json").write_text(json.dumps(
        {"dispatches": {"S5-qa-automator-1": {"id": "S5-qa-automator-1", "stage": "S5",
                                              "role": "qa-automator", "status": "running",
                                              "scope": list(scope)}}}), encoding="utf-8")
    (task / "pipeline.json").write_text(json.dumps(
        {"ticket": "QA-700", "stage_overrides": list(overrides)}), encoding="utf-8")
    (root / "tests").mkdir(parents=True, exist_ok=True)
    (root / "tests" / "test_sub.py").write_text(TEST_PY, encoding="utf-8")
    (root / "tests" / "conftest.py").write_text(CONFTEST_PY, encoding="utf-8")
    (root / "qa-factory").mkdir(parents=True, exist_ok=True)
    (root / "qa-factory" / "config.json").write_text(json.dumps(
        {"environment": {"integrations": [{"name": "jira", "keys": ["JIRA_TOKEN"]}]}}),
        encoding="utf-8")
    return task


def messages(result: dict) -> str:
    return "\n".join(f["message"] + " || " + f["fix"] for f in result["findings"]
                     if f["check"] == "environment")


def the_block_says_what_would_end_it() -> None:
    root = temp_dir("qa-remedy-")
    try:
        prose = [{"case": "TC-700", "reason": "blocked_by_env",
                  "detail": "the sub-workflow feature is off on this stand"}]
        task = make_story(root, prose)
        scoped = P.run(task, "S5-qa-automator-1")
        check_in("a blocked row of this dispatch with no remedy is a refusal",
                 "with no `remedy`", messages(scoped))
        check_in("and the fix names the shape, not a complaint", "kind: flag|credential",
                 messages(scoped))
        check("which makes the check reject", scoped["ok"] is False)

        # The same row, written by a window this dispatch does not own: a note. A story that
        # upgraded the plugin mid-flight carries rows nobody here can repair any more.
        other = P.run(task, None)
        check_not_in("an unscoped run refuses nothing about it", "with no `remedy`",
                     messages(other))
        check_in("it says so as a note instead", "a row this dispatch does not own",
                 "\n".join(other["notes"]))
    finally:
        cleanup(root)

    ok_root = temp_dir("qa-remedy-ok-")
    try:
        fixed = make_story(ok_root, [{"case": "TC-700", "reason": "blocked_by_env",
                                      "detail": "the sub-workflow feature is off",
                                      "remedy": REMEDY}])
        check_eq("a row that carries its fix passes",
                 messages(P.run(fixed, "S5-qa-automator-1")), "")
    finally:
        cleanup(ok_root)

    bad_root = temp_dir("qa-remedy-bad-")
    try:
        bad = make_story(bad_root, [{"case": "TC-700", "reason": "blocked_by_env",
                                     "remedy": {"kind": "feature", "where": "", "change": "on"}}])
        broken = messages(P.run(bad, "S5-qa-automator-1"))
        check_in("an invented kind is named", "remedy.kind must be one of", broken)
        check_in("and an empty `where` is named", "remedy.where is empty", broken)
    finally:
        cleanup(bad_root)


def names_only_never_values() -> None:
    root = temp_dir("qa-remedy-secret-")
    try:
        task = make_story(root, [{
            "case": "TC-700", "reason": "blocked_by_env",
            "detail": "the stand has no guardrail account: " + LEAKED_LINE,
            "remedy": {"kind": "credential", "where": "testproject1_test_harness/.env",
                       "change": "add NON_OWNER_PASSWORD"}}])
        result = messages(P.run(task, "S5-qa-automator-1"))
        check_in("a credential VALUE in the prose is a refusal",
                 "name the variable, never its value", result)
        check_in("and the message names the variable it found", "NON_OWNER_PASSWORD", result)
        check_eq("the check reads the same names env_probe does",
                 [bool(P._secret_name().search(k)) for k in ("NON_OWNER_PASSWORD", "BASE_URL")],
                 [True, False])
        check_eq("a name pointing at another name is not a leak",
                 P.secret_value_leaks("AUTH_CLIENT_SECRET: NON_OWNER_SECRET"), [])
        check_eq("nor is a sentence about a missing one",
                 P.secret_value_leaks("AUTH_TOKEN: unavailable on this stand"), [])
        check_eq("nor a placeholder the role wrote for the person",
                 P.secret_value_leaks("OWNER_PASSWORD=<the account's password>"), [])
    finally:
        cleanup(root)


def a_fixture_is_not_a_stand() -> None:
    root = temp_dir("qa-fixture-")
    try:
        task = make_story(root, [{
            "case": "TC-700", "reason": "blocked_by_env",
            "detail": "the assistant fixture needs a jira integration this stand has not got",
            "remedy": REMEDY}])
        result = P.run(task, "S5-qa-automator-1")
        text = messages(result)
        check_in("a conftest fixture the case never mentions is a refusal",
                 "the block is the fixture `assistant`", text)
        check_in("and the message says where the block really comes from",
                 "the test's own fixture, not from the case", text)
        check_in("the fix is the test defect, not a question for the person",
                 "minimum the Then requires, through the API", text)
        check_in("an integration the project declared is caught the same way",
                 "the block is the integration `jira`", text)
        check("no finding here asks the person anything",
              not any("?" in f["fix"] for f in result["findings"]))
    finally:
        cleanup(root)

    named = temp_dir("qa-fixture-named-")
    try:
        # The case that DOES ask for the dependency: its own text names it, so the stand is
        # the honest answer and nothing here fires.
        task = make_story(named, [{"case": "TC-700", "reason": "blocked_by_env",
                                   "detail": "the assistant fixture needs a jira integration",
                                   "remedy": REMEDY}])
        (task / "work" / "test-cases" / "TC-700.md").write_text(CASE_MD.replace(
            "A workflow with a sub-workflow node.",
            "A workflow whose node calls the assistant, with jira bound to it."),
            encoding="utf-8")
        check_eq("a dependency the approved case names is not a fixture finding",
                 messages(P.run(task, "S5-qa-automator-1")), "")
    finally:
        cleanup(named)


def a_persons_word_passes_it() -> None:
    root = temp_dir("qa-remedy-waiver-")
    try:
        answered = [{"stage": "S5", "match": "remedy", "decision": "accept it as it stands",
                     "at": "2026-09-23T10:00:00+00:00", "by": "human"}]
        task = make_story(root, [{"case": "TC-700", "reason": "blocked_by_env",
                                  "detail": "the feature is off"}], overrides=answered)
        result = P.run(task, "S5-qa-automator-1")
        check_eq("the refusal a person answered is gone", messages(result), "")
        check_in("and their words are kept where the reader sees them",
                 "accept it as it stands", "\n".join(result["notes"]))
        check_in("the note still says what was passed", "with no `remedy`",
                 "\n".join(result["notes"]))
    finally:
        cleanup(root)


def the_writers_and_readers_agree() -> None:
    path = Path("automation-manifest.json")
    errors: list = []
    V.check_manifest_invariants(path, {"unresolved": [
        {"case": "TC-1", "reason": "blocked_by_env", "detail": "the flag is off"},
        {"case": "TC-2", "reason": "blocked_by_env", "remedy": REMEDY}]}, errors)
    check_in("a manifest that knows remedies refuses the row that has none",
             "blocks on the environment with no `remedy`", errors)
    legacy: list = []
    V.check_manifest_invariants(path, {"unresolved": [
        {"case": "TC-1", "reason": "blocked_by_env", "detail": "the flag is off"}]}, legacy)
    check_eq("a manifest written before the field is validated as it always was", legacy, [])
    shape: list = []
    V.check_manifest_invariants(path, {"unresolved": [
        {"case": "TC-1", "reason": "blocked_by_env", "remedy": {"kind": "flag"}}]}, shape)
    check_in("a remedy that is not one is refused whatever the file's age",
             "remedy.where is empty", shape)
    report: list = []
    V.check_remedy_rows(Path("run-report.json"), [
        {"case": "TC-3", "area": "api", "remedy": REMEDY},
        {"case": "TC-4", "area": "api", "needs": "the guardrail account"}],
        "env_blocked[]", report)
    check_in("a run report's env_blocked row owes the same fix",
             "env_blocked[] TC-4 blocks on the environment with no `remedy`", report)
    handed: list = []
    V.check_manifest_invariants(path, {"unresolved": [
        {"case": "TC-1", "reason": "handed_to_person", "remedy": REMEDY},
        {"case": "TC-2", "reason": "impossible", "detail": "the product offers no way"}]}, handed)
    check_eq("a row the person took, and a row that is not about the stand, owe nothing",
             handed, [])

    merged = M.merge({"unresolved": [{"case": "TC-1", "reason": "blocked_by_env",
                                      "detail": "the flag is off"}]},
                     {"unresolved": [{"case": "TC-1", "reason": "blocked_by_env",
                                      "remedy": REMEDY}]})[0]
    check_eq("the later row with the fix supersedes the prose-only one",
             (merged["unresolved"][0]["remedy"]["where"], merged["unresolved"][0]["detail"]),
             (REMEDY["where"], "the flag is off"))
    check_eq("a remedy is not a reason, and stage_guard keeps reading the reason",
             SG.unresolved_rows_without_decision({"unresolved": [
                 {"case": "TC-1", "reason": "blocked_by_env", "remedy": REMEDY}]}), [])
    check_eq("an invented reason is still what it refuses",
             SG.unresolved_rows_without_decision({"unresolved": [
                 {"case": "TC-1", "reason": "stand_gap", "remedy": REMEDY}]}),
             ["TC-1 (stand_gap)"])
    check("the closed list is the contract's, not a second copy",
          "blocked_by_env" in C.UNRESOLVED_REASONS and "remedy" not in C.UNRESOLVED_REASONS)


def main() -> None:
    the_block_says_what_would_end_it()
    names_only_never_values()
    a_fixture_is_not_a_stand()
    a_persons_word_passes_it()
    the_writers_and_readers_agree()
    finish("test_stand_gap_remedy")


if __name__ == "__main__":
    main()
