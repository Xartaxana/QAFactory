#!/usr/bin/env python3
"""The S5 exit: one instance identity, manifest invariants, the pre-critic check, the
batched runner and the red sandbox .

Everything here is a shape TP1-15045 produced for real: a case green at four of eight
partitions, a Then nothing asserts, a Then the test contradicts, a manifest row per case
instead of per test, a batch refused for naming one instance twice, a sandbox that failed
because the factory's own dashboard was rewritten under it.
"""
import contextlib
import hashlib
import io
import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness import (check, check_eq, check_in, check_not_in, cleanup, finish,  # noqa: E402
                     run_script, temp_dir, temp_project)

import contract as C  # noqa: E402
import manifest_put as M  # noqa: E402
import red_sandbox as RS  # noqa: E402
import run_suite as RUN  # noqa: E402
import s5_precheck as P  # noqa: E402
import validate_artifacts as V  # noqa: E402

CASE_MD = """---
id: TC-500
status: Draft
---
## Given
Partitions: P-ok, P-warn.

## When
Call validate.

## Then
1. The call returns `status_ok` for P-ok.
2. P-warn returns the `warnings` list.
3. The body's `help` is null.
"""

TEST_PY = '''"""Tests for TC-500."""
import os


def _read_state(record):
    """@case TC-500 helper"""
    return {"kind": record["kind"], "update_date": record.get("update_date")}


def test_status_ok(client):
    """@case TC-500 - P-ok."""
    body = client.get()
    assert_that(body["status_ok"], equal_to(True))
    assert_that(body.get("help"), not_none(), "help")
    granted = client.login()["access_token"]
    assert_that(granted, not_none(), "the product's own token field")


def test_denied(client):
    """@case TC-500 - denied."""
    before = _read_state(client.record())
    after = _read_state(client.record())
    assert_that(after, equal_to(before))
    assert_that(os.environ["OWNER_PASSWORD"], equal_to("x"))
    sleep(3)
'''


def make_story(root: Path, manifest: dict, blocks=(), triage=None) -> Path:
    task = root / "qa-factory" / "artifacts" / "QA-500"
    (task / "work" / "test-cases").mkdir(parents=True)
    (task / "work" / "run-blocks").mkdir(parents=True)
    (task / "work" / "automation-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    (task / "work" / "triage.json").write_text(
        json.dumps(triage or {"triage": []}, ensure_ascii=False), encoding="utf-8")
    (task / "work" / "test-cases" / "TC-500.md").write_text(CASE_MD, encoding="utf-8")
    (root / "tests").mkdir(parents=True, exist_ok=True)
    (root / "tests" / "test_validate.py").write_text(TEST_PY, encoding="utf-8")
    for i, block in enumerate(blocks):
        (task / "work" / "run-blocks" / f"2026092{i}T000000Z-b{i}.json").write_text(
            json.dumps(block, ensure_ascii=False), encoding="utf-8")
    return task


def messages(result: dict, check_name: str) -> str:
    return "\n".join(f["message"] + " || " + f["fix"]
                     for f in result["findings"] if f["check"] == check_name)


def identity() -> None:
    # identity is the TEST, not one case. A case is a coverage specification, and the
    # cases an instance proves are `covers` on its manifest entry.
    check_eq("an instance reads as function[parameter], with no case in it",
             C.instance_id("test_validate_per_partition", "missing-assistant"),
             "test_validate_per_partition[missing-assistant]")
    check_eq("a pytest node id is reduced to the function",
             C.instance_id("tests/a.py::test_x"), "test_x")
    check_eq("a parameter map is canonical, not collection-ordered",
             C.instance_id("test_x", {"b": 2, "a": 1}),
             C.instance_id("test_x", {"a": 1, "b": 2}))
    check_eq("the case of an instance is the first case it covers",
             C.instance_case({"instance_id": "test_x[eu]", "covers": ["TC-9", "TC-8"]}), "TC-9")
    check_eq("a 0.7.7 id still answers with the case its prefix names",
             C.instance_case("TC-012::test_x[eu]"), "TC-012")
    check_eq("an id that covers nothing and names nothing answers empty, never guesses",
             C.instance_case("ti_abc"), "")
    check_eq("one consolidated test carries every case it proves",
             C.manifest_test_links({"covers": ["TC-003", "TC-004", "TC-005"]}),
             ["TC-003", "TC-004", "TC-005"])
    aliases = C.instance_id_aliases({"file": "a.py", "test_function": "test_x",
                                     "parameter": "eu", "covers": ["TC-1", "TC-2"]})
    check_in("the canonical id comes first", "test_x[eu]", aliases[0])
    check("and a 0.7.7 spelling of the same test still matches it",
          "TC-2::test_x[eu]" in aliases, aliases)

    # `::` is legal in JSON and illegal in a Windows path: an id is an identity, a stem is a name.
    stem = C.instance_file_stem("TC-012::test_x[eu]")
    check("a file stem carries no path-illegal character",
          all(ch.isalnum() or ch in "._-" for ch in stem), stem)
    check_in("and stays readable", "TC-012--test_x", stem)
    check("two ids that sanitise alike keep different stems",
          C.instance_file_stem("TC-1::a[b]") != C.instance_file_stem("TC-1::a/b"))
    check_eq("an id that needs no sanitising keeps its own spelling",
             C.instance_file_stem("TC-1"), "TC-1")
    check_eq("an empty id still names a file", C.instance_file_stem(""), "instance")

    entry = {"case": "TC-7", "test_function": "test_limit", "parameter": "eu"}
    check_eq("a manifest entry derives the same id", C.test_instance_id(entry),
             "test_limit[eu]")
    check_eq("an explicit id still wins (imported and 0.7.x records)",
             C.test_instance_id({**entry, "instance_id": "ti_old"}), "ti_old")
    legacy = {"case": "TC-7", "selector": "a | b | c", "repository_id": "r"}
    check("an entry with no readable function keeps the 0.7.x hash identity",
          C.test_instance_id(legacy).startswith("ti_"), C.test_instance_id(legacy))


def manifest_invariants() -> None:
    green = {"tests": [{"case": "TC-1", "file": "a.py", "marker": "TC-1", "status": "green"}]}
    unresolved = {"unresolved": [{"case": "TC-1", "reason": "blocked_by_env"}]}
    both = M.merge(M.merge({}, unresolved)[0], green)[0]
    check_eq("a green tests[] entry clears the whole-case unresolved row",
             both["unresolved"], [])
    back = M.merge(both, unresolved)[0]
    check_eq("and an unresolved row clears the stale test entry", back["tests"], [])
    slice_row = {"unresolved": [{"case": "TC-1", "reason": "blocked_by_env",
                                 "partitions": ["P-warn"]}]}
    partial = M.merge(M.merge({}, green)[0], slice_row)[0]
    check_eq("a partition-scoped row is a different fact and both survive",
             (len(partial["tests"]), len(partial["unresolved"])), (1, 1))

    split = {"tests": [{"case": "TC-1", "file": "a.py", "test_function": "test_x",
                        "parameter": "eu", "marker": "TC-1"}]}
    twice = M.merge(M.merge({}, split)[0], split)[0]
    check_eq("splitting a parametrized test replaces, never duplicates",
             len(twice["tests"]), 1)
    old = {"tests": [{"case": "TC-1", "file": "a.py", "selector": "q", "repository_id": "r",
                      "profile_id": "p", "test": "a.py::test_x"}]}
    patch = {"tests": [{"instance_id": C.legacy_test_instance_id(old["tests"][0]),
                        "critic_verdict": "approved"}]}
    upgraded = M.merge(old, patch)[0]
    check_eq("a 0.7.x row is matched by its old id, not duplicated beside it",
             (len(upgraded["tests"]), upgraded["tests"][0].get("critic_verdict")),
             (1, "approved"))

    fix = {"self_fixes": [{"test": "t", "what": "selector", "why_test_defect": "renamed",
                           "evidence": "e.json"}]}
    deduped, summary = M.merge(M.merge({}, fix)[0], fix)
    check_eq("a byte-identical self_fix is not appended twice", len(deduped["self_fixes"]), 1)
    check_eq("and the drop is counted", summary.get("duplicate"), 1)


def validator_names_the_command() -> None:
    root = temp_dir("qa-s5-val-")
    try:
        manifest = {"tests": [{"case": "TC-1", "file": "tests/test_validate.py",
                               "instance_id": "TC-1::test_x", "status": "green"},
                              {"case": "TC-1", "file": "tests/test_validate.py",
                               "instance_id": "TC-1::test_x", "status": "green"}],
                    "unresolved": [{"case": "TC-1", "reason": "blocked_by_env"}],
                    "self_fixes": [{"test": "t", "what": "selector", "why_test_defect": "r",
                                    "evidence": "e"},
                                   {"test": "t", "what": "selector", "why_test_defect": "r",
                                    "evidence": "e"}]}
        errors: list = []
        V.check_manifest_invariants(root / "automation-manifest.json", manifest, errors)
        text = "\n".join(errors)
        check_in("a hand edit with two rows for one instance is rejected",
                 "two tests[] entries carry the instance id", text)
        check_in("a case in both lists is rejected", "disagree about whether it ran", text)
        check_in("a duplicated repair is rejected", "recorded twice", text)
        check_in("and the message names the command that owns the file",
                 "manifest_put.py", text)
        check_not_in("no message tells the author to edit the file",
                     "edit the file again", text)
    finally:
        cleanup(root)


def precheck_findings() -> None:
    root = temp_dir("qa-s5-pre-")
    try:
        manifest = {
            "tests": [{"case": "TC-500", "file": "tests/test_validate.py", "marker": "TC-500",
                       "instance_id": "TC-500", "status": "green"}],
            "unresolved": [{"case": "TC-500", "reason": "blocked_by_env",
                            "partitions": ["P-warn"]}],
            "self_fixes": [{"test": "t", "what": "selector", "why_test_defect": "r",
                            "evidence": "e"},
                           {"test": "t", "what": "selector", "why_test_defect": "r",
                            "evidence": "e"}],
        }
        block = {"purpose": "initial", "source_fingerprint": {"test_content_sha": "aaa"},
                 "results": [{"instance_id": "TC-500", "test_id": "tests/test_validate.py::x",
                              "status": "not_run", "report_matched": False,
                              "reason": "report row missing"}]}
        task = make_story(root, manifest, blocks=[block])
        result = P.run(task)
        check("a manifest with these shapes is not ok", result["ok"] is False)

        man = messages(result, "manifest")
        check_in("an id that names the case, not the test, is a finding",
                 "names the CASE, not one test", man)
        check_in("green at a subset of the partitions is a finding",
                 "is `green` while 1 of its partitions are unresolved", man)
        check_in("a byte-identical repair is a finding", "byte-identical", man)

        binds = messages(result, "bindings")
        check_in("a manifest with no then_bindings is a finding, not a crash",
                 "bindings missing: TC-500 has 3 Then clause(s)", binds)
        check_in("a Then resting on an unresolved partition is named",
                 "Then 2 of TC-500 rests on P-warn", binds)
        check_in("a Then the code contradicts is named",
                 "Then 3 of TC-500 demands `help` be null/empty", binds)

        run_map = messages(result, "run_mapping")
        check_in("a row with no reporter match is a finding", "TC-500: the newest run block",
                 run_map)
        check_in("and the fix is the reparse, never a rerun", "--reparse-block", run_map)
        # counting test functions per case argued for one test per case. It is gone.
        check_not_in("a case with more test functions than instances is NOT a finding",
                     "test functions", run_map)

        smells = "\n".join(a["message"] for a in result["advice"] if a["check"] == "smell")
        check_eq("X7-2 (2): the smells are ADVICE, none is a finding of the gate",
                 [f["id"] for f in result["findings"] if f["check"] == "smell"], [])
        check_in("an assert on an environment credential is ADVICE for the critic",
                 "credential read from the environment", smells)
        check_in("and it names what it traced, so the critic can judge it",
                 "is read in the assert itself", smells)
        # The other half of the same check: a field the PRODUCT returned is what the test is
        # for. Matching the word `token` refused that assert too, and a review circle went on
        # arguing with it (P5).
        check_not_in("a product response field named like a credential is NOT a finding",
                     "access_token", smells)
        check_not_in("nor is the line that reads it", "test_validate.py:58", smells)
        check_in("a comparison that can be None on both sides is ADVICE",
                 "None == None", smells)
        check_in("a sleep is ADVICE", "waits with sleep()", smells)

        check("every finding and every piece of advice carries the fixed keys",
              all(set(f) >= {"id", "check", "case", "message", "fix"} for f in result["findings"] + result["advice"]))
        check("no finding asks the person anything",
              not any("?" in f["fix"] for f in result["findings"] + result["advice"]),
              "\n".join(f["fix"] for f in result["findings"] + result["advice"] if "?" in f["fix"]))

        (task / "state").mkdir(parents=True, exist_ok=True)
        (task / "state" / "controller.json").write_text(json.dumps(
            {"dispatches": {"S5-qa-automator-1": {"id": "S5-qa-automator-1", "stage": "S5",
                                                  "scope": ["TC-900"]}}}), encoding="utf-8")
        scoped = P.run(task, "S5-qa-automator-1")
        check_eq("a dispatch id narrows the check to that dispatch's cases",
                 scoped["cases"], ["TC-900"])
        check_eq("an unknown dispatch falls back to the manifest, never to nothing",
                 P.run(task, "S5-qa-automator-9")["cases"], ["TC-500"])
        # The exit gate runs with no arguments: it must judge the handoff in front of it,
        # not a window closed a day earlier (TP1-15045, window TC-001/TC-002 refused
        # over a TC-014 finding).
        (task / "state" / "controller.json").write_text(json.dumps(
            {"dispatches": {
                "S5-qa-automator-1": {"id": "S5-qa-automator-1", "stage": "S5", "role": "qa-automator",
                                      "scope": ["TC-014"], "status": "accepted"},
                "S5-qa-automator-2": {"id": "S5-qa-automator-2", "stage": "S5", "role": "qa-automator",
                                      "scope": ["TC-900"], "status": "running"},
                "S5-qa-code-critic-1": {"id": "S5-qa-code-critic-1", "stage": "S5", "role": "qa-code-critic",
                                        "scope": ["TC-014"], "status": "running"}}}), encoding="utf-8")
        check_eq("the exit gate scopes the check to the one running automator dispatch",
                 P.running_dispatch(task), "S5-qa-automator-2")
        check_eq("...and that scope is what the detector then speaks about",
                 P.run(task, P.running_dispatch(task))["cases"], ["TC-900"])
        (task / "state" / "controller.json").write_text(json.dumps(
            {"dispatches": {"a": {"id": "a", "stage": "S5", "role": "qa-automator", "scope": ["TC-1"], "status": "running"},
                            "b": {"id": "b", "stage": "S5", "role": "qa-automator", "scope": ["TC-2"], "status": "running"}}}),
            encoding="utf-8")
        check_eq("two running automators: the gate cannot tell whose handoff it is and stays unscoped",
                 P.running_dispatch(task), None)

        bound = dict(manifest, then_bindings=[
            {"case": "TC-500", "then": n, "instance_id": "TC-500::test_status_ok",
             "assertion_ref": "tests/test_validate.py:12", "status": "covered"}
            for n in (1, 2, 3)])
        (task / "work" / "automation-manifest.json").write_text(
            json.dumps(bound), encoding="utf-8")
        again = P.run(task)
        check_not_in("recorded bindings silence the 'bindings missing' finding",
                     "bindings missing", messages(again, "bindings"))
    finally:
        cleanup(root)


def one_instance_may_prove_several_cases() -> None:
    """C-F9: a consolidated test is a legitimate shape. Reading tests[] by the `case` field
    alone reported it missing for every case but the owning one."""
    root = temp_dir("qa-s5-nm-")
    try:
        shared = {"case": "TC-500", "file": "tests/test_validate.py",
                  "marker": "TC-500", "instance_id": "TC-500::test_status_ok",
                  "status": "green",
                  "case_version_links": [{"case_id": "TC-500", "version": "cv_a"},
                                         {"case_id": "TC-501", "version": "cv_b"}]}
        manifest = {"tests": [shared], "then_bindings": [
            {"then": n, "instance_id": "TC-500::test_status_ok",
             "assertion_ref": "tests/test_validate.py:12", "status": "covered"}
            for n in (1, 2, 3)]}
        task = make_story(root, manifest)
        (task / "work" / "test-cases" / "TC-501.md").write_text(
            CASE_MD.replace("TC-500", "TC-501"), encoding="utf-8")
        check_eq("the owning case still finds its instance",
                 [C.test_instance_id(e) for e in P.instances_of_case(manifest, "TC-500")],
                 ["TC-500::test_status_ok"])
        check_eq("and so does the case it also proves",
                 [C.test_instance_id(e) for e in P.instances_of_case(manifest, "TC-501")],
                 ["TC-500::test_status_ok"])
        check_eq("a binding row that names only its instance belongs to both cases",
                 len(P.bindings_of_case(manifest, "TC-501")), 3)
        result = P.run(task)
        check_not_in("the shared case is not reported as having no test",
                     "no run block carries a result row for TC-501",
                     messages(result, "run_mapping"))
        check_not_in("and its Then clauses are not reported unbound",
                     "bindings missing: TC-501", messages(result, "bindings"))
        # the link is what keeps the consolidation traceable. A clause bound to an
        # instance that does not name this case is the one shape that IS a finding.
        stray = dict(manifest, then_bindings=list(manifest["then_bindings"]) +
                     [{"case": "TC-501", "then": 1, "instance_id": "test_elsewhere",
                       "assertion_ref": "tests/test_validate.py:3", "status": "covered"}])
        (task / "work" / "automation-manifest.json").write_text(json.dumps(stray),
                                                                encoding="utf-8")
        check_in("a clause bound to an instance that does not cover the case is a finding",
                 "lists TC-501 among the cases it covers",
                 messages(P.run(task), "bindings"))
    finally:
        cleanup(root)


CONSOLIDATED_CASE = """---
id: {case}
status: Approved
---
## Given
A request for {case}.

## When
Call validate.

## Then
1. The call returns `status_ok`.
"""

CONSOLIDATED_PY = '''"""One parametrized test for TC-003, TC-004 and TC-005."""


def test_validate(client, region):
    """@case TC-003 TC-004 TC-005."""
    body = client.get(region)
    assert_that(body["status_ok"], equal_to(True))
'''

TWINS_PY = '''"""Three tests that differ only in their data."""


def test_eu(client):
    """@case TC-003."""
    body = client.get("eu")
    assert_that(body["status_ok"], equal_to("eu-ok"))


def test_us(client):
    """@case TC-004."""
    body = client.get("us")
    assert_that(body["status_ok"], equal_to("us-ok"))


def test_ap(client):
    """@case TC-005."""
    body = client.get("ap")
    assert_that(body["status_ok"], equal_to("ap-ok"))
'''


def _three_case_story(root: Path, manifest: dict, blocks) -> Path:
    task = root / "qa-factory" / "artifacts" / "QA-540"
    (task / "work" / "test-cases").mkdir(parents=True)
    (task / "work" / "run-blocks").mkdir(parents=True)
    (task / "work" / "automation-manifest.json").write_text(json.dumps(manifest),
                                                            encoding="utf-8")
    (task / "work" / "triage.json").write_text('{"triage": []}', encoding="utf-8")
    for case in ("TC-003", "TC-004", "TC-005"):
        (task / "work" / "test-cases" / f"{case}.md").write_text(
            CONSOLIDATED_CASE.format(case=case), encoding="utf-8")
    (root / "tests").mkdir(parents=True, exist_ok=True)
    for i, block in enumerate(blocks):
        (task / "work" / "run-blocks" / f"2026092{i}T000000Z-b{i}.json").write_text(
            json.dumps(block), encoding="utf-8")
    return task


def the_automator_chooses_the_shape() -> None:
    """0.7.7 acceptance. One parametrized test proving three cases passes with no finding;
    three bodies that differ only in their data earn a hint, never a refusal."""
    root = temp_dir("qa-s5-shape-")
    try:
        cases = ["TC-003", "TC-004", "TC-005"]
        instances = [f"test_validate[{r}]" for r in ("eu", "us", "ap")]
        manifest = {
            "tests": [{"file": "tests/test_shape.py", "instance_id": i, "status": "green",
                       "test_function": "test_validate", "shape": "parameterize",
                       "consolidates": cases, "covers": cases,
                       "case_version_links": [{"case_id": c, "version": "cv"} for c in cases]}
                      for i in instances],
            "then_bindings": [{"case": c, "then": 1, "instance_id": i,
                               "assertion_ref": "tests/test_shape.py:6", "status": "covered"}
                              for c, i in zip(cases, instances)]}
        block = {"purpose": "initial", "source_fingerprint": {"test_content_sha": "aaa"},
                 "results": [{"instance_id": i, "test_id": f"tests/test_shape.py::{i}",
                              "status": "passed", "report_matched": True} for i in instances]}
        task = _three_case_story(root, manifest, [block])
        (root / "tests" / "test_shape.py").write_text(CONSOLIDATED_PY, encoding="utf-8")
        result = P.run(task)
        check_eq("one parametrized test covering three cases is checked as three cases",
                 result["cases"], cases)
        check("and passes the S5 exit with no finding at all", result["ok"] is True,
              "\n".join(f["message"] for f in result["findings"]))
        check_eq("and earns no hint either", result["hints"], [])

        for entry in manifest["tests"]:
            entry["shape"] = "new"
        manifest["tests"] = [
            {"file": "tests/test_shape.py", "instance_id": name, "status": "green",
             "test_function": name, "shape": "new", "covers": [case],
             "case_version_links": [{"case_id": case, "version": "cv"}]}
            for name, case in zip(("test_eu", "test_us", "test_ap"), cases)]
        manifest["then_bindings"] = [
            {"case": case, "then": 1, "instance_id": name,
             "assertion_ref": "tests/test_shape.py:6", "status": "covered"}
            for name, case in zip(("test_eu", "test_us", "test_ap"), cases)]
        block["results"] = [{"instance_id": n, "test_id": f"tests/test_shape.py::{n}",
                             "status": "passed", "report_matched": True}
                            for n in ("test_eu", "test_us", "test_ap")]
        (task / "work" / "automation-manifest.json").write_text(json.dumps(manifest),
                                                                encoding="utf-8")
        for path in (task / "work" / "run-blocks").glob("*.json"):
            path.write_text(json.dumps(block), encoding="utf-8")
        (root / "tests" / "test_shape.py").write_text(TWINS_PY, encoding="utf-8")
        twins = P.run(task)
        text = "\n".join(h["message"] for h in twins["advice"])
        check_in("three twin bodies with different data are named as one parametrized test",
                 "differ only in their data", text)
        check_in("and the advice names the cases they cover", "TC-003, TC-004, TC-005", text)
        check("advice never fails the gate — the shape was the author's to choose",
              twins["ok"] is True, "\n".join(f["message"] for f in twins["findings"]))
        check("and it is not mixed in with the repairs",
              all(f.get("level") == "repair" for f in twins["findings"]))
    finally:
        cleanup(root)


def a_contradicted_requirement_has_an_outcome() -> None:
    """C-F13: the code contradicts the requirement — the test is handed over red and the
    unresolved[] row says why. That is not the two lists disagreeing."""
    root = temp_dir("qa-s5-contra-")
    try:
        manifest = {
            "tests": [{"case": "TC-500", "file": "tests/test_validate.py", "marker": "TC-500",
                       "instance_id": "TC-500::test_status_ok", "status": "red"}],
            "unresolved": [{"case": "TC-500", "reason": P.CONTRADICTS,
                            "requirement": "R-4", "expected": "403", "observed": "401"}],
            "then_bindings": [{"case": "TC-500", "then": n,
                               "instance_id": "TC-500::test_status_ok",
                               "assertion_ref": "tests/test_validate.py:12",
                               "status": "covered"} for n in (1, 2, 3)]}
        task = make_story(root, manifest)
        man = messages(P.run(task), "manifest")
        check_not_in("a red test explained by contradicts_requirement is not 'both lists'",
                     "in tests[] and in unresolved[] at the same time", man)
        manifest["tests"][0]["status"] = "green"
        (task / "work" / "automation-manifest.json").write_text(json.dumps(manifest),
                                                                encoding="utf-8")
        check_in("but a GREEN test beside that row is the finding",
                 "does not prove the code contradicts the requirement",
                 messages(P.run(task), "manifest"))
    finally:
        cleanup(root)


def a_blocked_instance_is_the_third_allowed_shape() -> None:
    """t-219 (B7): a case is in tests[] and in unresolved[] at once with a `blocked_by_env` row that NAMES its
    instance (`instance_ids`; the cmp2 rows name a partition and the single-instance rule reaches them), beside a
    test that is not green. Beside a green row of THAT instance it is `blocked-but-green` - the row hides a real
    result - and the run mapping asks no reporter row of an instance that never reached a verdict (nor of one whose
    row has no remedy, which is no block at all)."""
    root = temp_dir("qa-s5-blocked-")
    try:
        fix = {"kind": "service", "where": "frontend localhost:5173", "change": "the page must load", "restart": "re-run"}
        row = {"case": "TC-500", "reason": P.BLOCKED_BY_ENV, "instance_ids": ["TC-500::test_status_ok"],
               "detail": "Loading", "remedy": fix}
        tests = [{"case": "TC-500", "file": "tests/test_validate.py", "marker": "TC-500", "covers": ["TC-500"],
                  "instance_id": "TC-500::test_status_ok", "status": "red"}]
        task = make_story(root, {"tests": tests, "unresolved": [row]})
        result = P.run(task)
        check_not_in("a blocked instance's row beside its red test is no 'both lists'",
                     "at the same time", messages(result, "manifest"))
        check_not_in("nor `partial-green`", "partial-green", json.dumps(result["findings"]))
        check_eq("the run mapping asks no reporter row of an instance the stand blocked",
                 [f for f in result["findings"] if f["check"] == "run_mapping"], [])
        # a partition row (the cmp2 shape) is reached by the single-instance rule, and a green beside it is the finding
        part = dict(row, partitions=["tc500-visual"])
        part.pop("instance_ids")
        for status, expected in (("red", False), ("green", True)):
            (task / "work" / "automation-manifest.json").write_text(
                json.dumps({"tests": [dict(tests[0], status=status)], "unresolved": [part]}), encoding="utf-8")
            found = [f for f in P.run(task)["findings"] if f["check"] == "manifest"]
            check_eq(f"a partition row on the case's only instance, its test {status}: blocked-but-green is {expected}",
                     any("blocked-but-green" in f["id"] for f in found), expected)
            check("and it never reads as `both-lists`", not any("both-lists" in f["id"] for f in found))
        green = [f for f in found if "blocked-but-green" in f["id"]]
        check_in("blocked-but-green names the door (manifest_put) and never a hand edit", "manifest_put.py",
                 green[0]["fix"] if green else "")
        # beside a green row of ANOTHER instance of the case: nothing - the normal state of a case with several
        two = [dict(tests[0], status="red"), dict(tests[0], status="green", instance_id="TC-500::test_other",
                                                  marker="TC-500", test="test_other", selector="tests/test_validate.py::test_other")]
        (task / "work" / "automation-manifest.json").write_text(
            json.dumps({"tests": two, "unresolved": [row]}), encoding="utf-8")
        found = [f for f in P.run(task)["findings"] if f["check"] == "manifest"]
        check_eq("beside a green row of ANOTHER instance of the case there is no manifest finding", found, [])
        # no remedy: not a block - the mapping asks again, and the environment check names the row
        bare = dict(row)
        bare.pop("remedy")
        (task / "work" / "automation-manifest.json").write_text(
            json.dumps({"tests": tests, "unresolved": [bare]}), encoding="utf-8")
        result = P.run(task)
        check("a row with no remedy is no block: the run mapping asks for the reporter row again",
              any(f["check"] == "run_mapping" for f in result["findings"]))
        findings, notes = [], []
        P.check_environment(task, {"tests": tests, "unresolved": [bare]}, ["TC-500"], {}, {}, findings, notes)
        check("and it keeps its `remedy-missing` finding", any("remedy-missing" in f["id"] for f in findings),
              str([f["id"] for f in findings]))
    finally:
        cleanup(root)


def a_green_is_compared_with_its_own_slice() -> None:
    """HF2-3 (3a2, K1/K2/K3/K10), through `P.run`: one case, two tests - a red one of P-ok and a green one of P-warn. A
    `contradicts_requirement` row speaks about ITS slice (the instance, the partition, the Thens it names), so the green
    sibling of another partition is the normal state of a case with several instances: not `partial-green` (what this
    shape said before), not `contradicts-but-green`. The same shape, but the green runs the row's partition: the
    contradiction is the finding. The partitions an `uncovered-partition` names are those a green test covers; a Then
    behind a red check needs no assertion; the whole-case id is built from the contract's tag."""
    root = temp_dir("qa-s5-slice-")
    try:
        def test(instance: str, status: str, partitions) -> dict:
            row = {"case": "TC-500", "file": "tests/test_validate.py", "marker": "TC-500", "covers": ["TC-500"],
                   "instance_id": instance, "status": status}
            if partitions is not None:
                row["partitions"] = partitions
            return row

        def bound(then: int, instance: str) -> dict:
            return {"case": "TC-500", "then": then, "instance_id": instance, "assertion_ref": "tests/test_validate.py:12",
                    "status": "covered"}

        def ids_of(result: dict, family: str) -> set:
            return {f["id"] for f in result["findings"] if f["check"] == family}

        red_row = {"case": "TC-500", "reason": P.CONTRADICTS, "partitions": ["P-ok"], "thens": [1], "detail": "d"}
        bindings = [bound(1, "test_status_ok"), bound(2, "test_denied"), bound(3, "test_denied")]
        manifest = {"tests": [test("test_status_ok", "red", ["P-ok"]), test("test_denied", "green", ["P-warn"])],
                    "unresolved": [red_row], "then_bindings": bindings}
        task = make_story(root, manifest)
        found = ids_of(P.run(task), "manifest")
        check_eq("K1: a partition row of the RED partition, a green test of another -> no manifest finding", found, set())

        def rewrite(data: dict) -> set:
            (task / "work" / "automation-manifest.json").write_text(json.dumps(data), encoding="utf-8")
            return ids_of(P.run(task), "manifest")

        check_eq("K1: the green test runs the row's partition -> `contradicts-but-green`, and never `partial-green`",
                 rewrite(dict(manifest, tests=[test("test_status_ok", "red", ["P-ok"]), test("test_denied", "green", ["P-ok"])])),
                 {"manifest:TC-500:contradicts-but-green"})
        check_eq("K1: the row names a Then the red test does not bind -> `contradicts-no-instance`",
                 rewrite(dict(manifest, unresolved=[dict(red_row, thens=[3])])), {"manifest:TC-500:contradicts-no-instance"})
        text = rewrite(dict(manifest, unresolved=[{k: v for k, v in red_row.items() if k not in ("partitions", "thens")}],
                            tests=[test("test_status_ok", "red", None), test("test_denied", "green", None)]))
        # R5 (t-1508): a row that names no `thens` leaves the red Thens unknown, so each RED instance it makes red also gets ONE
        # `red-own-thens-unnamed`; a test with `status: green` does not (its row is judged by `contradicts-but-green`, and the
        # two would contradict each other - t-1532 R5-1).
        check_eq("K1: a row with no slice key beside a green test -> `contradicts-but-green` as it always was "
                 "(+ one `red-own-thens-unnamed` for the RED instance, none for the green one)",
                 text, {"manifest:TC-500:contradicts-but-green", "manifest:TC-500:red-own-thens-unnamed-test_status_ok"})

        def uncovered(reason: str, green_partitions) -> bool:
            data = {"tests": [test("test_denied", "green", green_partitions)], "then_bindings": [bound(n, "test_denied") for n in (1, 2, 3)],
                    "unresolved": [{"case": "TC-500", "reason": reason, "partitions": ["P-warn"], "detail": "d"}]}
            (task / "work" / "automation-manifest.json").write_text(json.dumps(data), encoding="utf-8")
            return "bindings:TC-500:uncovered-partition-2" in ids_of(P.run(task), "bindings")

        check_eq("K2: a green test with no partition covers P-warn -> uncovered-partition", uncovered("impossible", None), True)
        check_eq("K2: ... a green test of P-warn", uncovered("impossible", ["P-warn"]), True)
        check_eq("K2: ... a green test of ANOTHER partition does not cover it", uncovered("impossible", ["P-ok"]), False)
        check_eq("K2: ... a contradicts_requirement row is not an uncovered partition", uncovered(P.CONTRADICTS, None), False)

        # K3: a Then no test asserts is `no-assert` unless it is a remainder; a contradicts row does not make it one
        (task / "work" / "test-cases" / "TC-500.md").write_text(CASE_MD + "4. The page shows `flux_capacitor_value`.\n", encoding="utf-8")
        base = {"tests": [test("test_status_ok", "green", None)], "then_bindings": [bound(n, "test_status_ok") for n in (1, 2, 3)]}
        remainder = {"case": "TC-500", "then": 4, "instance_id": None, "assertion_ref": None, "status": "unresolved", "detail": "d"}

        def no_assert(extra_binding=None, unresolved=()) -> bool:
            data = dict(base, then_bindings=base["then_bindings"] + ([extra_binding] if extra_binding else []),
                        unresolved=list(unresolved))
            (task / "work" / "automation-manifest.json").write_text(json.dumps(data), encoding="utf-8")
            return "bindings:TC-500:no-assert-4" in ids_of(P.run(task), "bindings")

        check_eq("K3: Then 4 that nothing asserts -> `no-assert-4`", no_assert(), True)
        check_eq("K3: ... left with its owner -> skipped", no_assert(dict(remainder, reason="handed_to_person")), False)
        check_eq("K3: ... behind a red check -> skipped",
                 no_assert(dict(remainder, reason="blocked_by_check", blocking_check="TC-501", instance_id="test_status_ok")), False)
        check_eq("K3 (N4): ... a contradicts_requirement row that names Then 4 grants no skip",
                 no_assert(unresolved=[{"case": "TC-500", "reason": P.CONTRADICTS, "thens": [4], "instance_ids": ["test_status_ok"],
                                        "detail": "d"}]), True)

        # HF2-5 (5a-K4, A2): a Then with NO covered row and an unresolved row of a reason from the closed list (or a decided
        # deferral) is recorded as not checked, so no assertion is owed; the red by a bug, an unknown reason and a Then that a
        # test also claims keep the finding
        check_eq("5a-K4 (a): a `blocked_by_check` Then row, no assert -> no finding",
                 no_assert(dict(remainder, reason="blocked_by_check", blocking_check="TC-501", instance_id="test_status_ok")), False)
        check_eq("5a-K4 (b): a Then row `contradicts_requirement`, no assert -> `no-assert-4` stays (a red by a bug is not commented out)",
                 no_assert(dict(remainder, reason=P.CONTRADICTS, instance_id="test_status_ok")), True)
        both = {"tests": [test("test_status_ok", "green", None)],
                "then_bindings": base["then_bindings"] + [bound(4, "test_status_ok"), dict(remainder, reason="handed_to_person")]}
        (task / "work" / "automation-manifest.json").write_text(json.dumps(both), encoding="utf-8")
        check_in("5a-K4 (c): covered AND unresolved on Then 4, no assert -> the finding (a test claims the Then)",
                 "bindings:TC-500:no-assert-4", ids_of(P.run(task), "bindings"))
        for reason, skipped in (("deferred_by_decision:S5", True), ("blocked_by_env", True), ("impossible", True),
                                ("pending_implementation", True), ("expectation_unconfirmed", True),
                                ("gone_fishing", False), ("", False), ("deferred_by_decision", False)):
            check_eq(f"5a-K4: a Then row with reason {reason!r} -> the assertion is {'not owed' if skipped else 'still owed (the unknown is no pass)'}",
                     not no_assert(dict(remainder, reason=reason)), skipped)

        # K10: every Then left with its owner is a whole-case hand-off, and the id is what it was
        handed = [dict(remainder, then=n, reason="handed_to_person") for n in (1, 2, 3, 4)]
        (task / "work" / "automation-manifest.json").write_text(json.dumps(
            {"tests": [test("test_status_ok", "green", None)], "then_bindings": handed}), encoding="utf-8")
        check_in("K10: `then-remainder-all` keeps its id byte for byte", "bindings:TC-500:then-remainder-all",
                 ids_of(P.run(task), "bindings"))
    finally:
        cleanup(root)


ORACLE_CASE_MD = """---
id: TC-500
status: Draft
---
## Given
A deleted workflow.

## When
PUT the workflow.

## Then
1. The call returns 404 and the body's `kind` is `not_found`.
2. The body's `help` is null.
"""

ORACLE_TEST_PY = '''"""Tests for TC-500."""


def test_deleted_is_refused(client):
    """@case TC-500."""
    response = client.put()
    assert_that(response.status_code, equal_to(403))
    assert_that(response.json()["kind"], equal_to("forbidden"))
    assert_that(response.json().get("help"), is_not(none()))
'''


def the_approved_case_is_the_oracle() -> None:
    """TP1-15045 sent TC-009 and TC-014 to `deferred_by_decision:designer` with the tests
    asserting the CODE's behaviour against the approved Then, using an existing test written
    to the code as the arbiter. After gate A the case is the oracle: the only routes out of
    S5 are a red test with `contradicts_requirement` and `impossible`."""
    root = temp_dir("qa-s5-oracle-")
    try:
        manifest = {
            "tests": [{"case": "TC-500", "file": "tests/test_oracle.py", "marker": "TC-500",
                       "instance_id": "test_deleted_is_refused", "status": "green"}],
            # The row says what it disputes. Until 0.7.19 two phrase lists over this prose
            # decided it, so a row worded otherwise escaped the check and a row worded like
            # this one was accused whether it was disputing anything or not (FR-12).
            "unresolved": [
                {"case": "TC-500", "reason": "deferred_by_decision:designer",
                 "disputes": "case_expectation",
                 "detail": "CASE-TEXT CONFLICT for the designer: case Then 2 says help is "
                           "null; the code and the live stand return non-null help, and an "
                           "existing test asserts not_none. Test keeps code behaviour."},
                {"case": "TC-501", "reason": "deferred_by_decision:owner",
                 "disputes": "derivation",
                 "detail": "Expected status not derivable from the register or the diff; the "
                           "owner must supply the access-control contract."}],
            "then_bindings": [{"case": "TC-500", "then": n, "instance_id": "test_deleted_is_refused",
                               "assertion_ref": "tests/test_oracle.py:6", "status": "covered"}
                              for n in (1, 2)]}
        block = {"purpose": "initial", "source_fingerprint": {"test_content_sha": "aaa"},
                 "results": [{"instance_id": "test_deleted_is_refused[chromium-1]",
                              "test_id": "tests/test_oracle.py::test_deleted_is_refused",
                              "status": "passed"}]}
        task = make_story(root, manifest, blocks=[block])
        (task / "work" / "test-cases" / "TC-500.md").write_text(ORACLE_CASE_MD, encoding="utf-8")
        (root / "tests" / "test_oracle.py").write_text(ORACLE_TEST_PY, encoding="utf-8")
        result = P.run(task)

        oracle = messages(result, "oracle")
        check_in("a deferral that disputes the approved case's expectation is a finding",
                 "TC-500 is unresolved with `deferred_by_decision:designer`", oracle)
        check_in("and it says which route the role actually has",
                 "only `contradicts_requirement` or `impossible`", oracle)
        check_not_in("a deferral that says the expected value is not derivable is left alone",
                     "TC-501", oracle)

        # A row that says nothing about what it disputes is asked, once, with the command that
        # answers it — the wording of the detail decides nothing either way now.
        for entry in manifest["unresolved"]:
            entry.pop("disputes", None)
        (task / "work" / "automation-manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
        unstated = messages(P.run(task), "oracle")
        check_in("a row that does not say what it disputes is asked to",
                 "TC-500 is unresolved with `deferred_by_decision:designer` and the row does "
                 "not say what it disputes", unstated)
        check_in("and the ask names the field's own values",
                 "`disputes` is one of ['nothing', 'derivation', 'case_expectation']", unstated)
        check_in("with the command that writes it", "manifest_put.py --task", unstated)
        check_in("the row whose prose used to read innocent is asked too, and by name",
                 "TC-501", unstated)
        check_not_in("and neither is accused of a dispute it did not declare",
                     "has no \"the case is wrong\" route", unstated)

        binds = messages(result, "bindings")
        check_in("a status code the test contradicts is a finding",
                 "Then 1 of TC-500 fixes status 404, and the tests of this case assert only 403",
                 binds)
        check_in("a literal the test contradicts is a finding",
                 "Then 1 of TC-500 fixes `kind` at 'not_found'", binds)
        check_in("a null the test contradicts is still a finding",
                 "Then 2 of TC-500 demands `help` be null/empty", binds)
        check_in("and every one of them is sent down the one route there is",
                 "hand the test over RED", binds)
        check_not_in("never back to the designer as a question about the case",
                     "designer question", binds)

        run_map = messages(result, "run_mapping")
        check_in("a run under another spelling is NAMED, not answered with a bare verdict",
                 "the id spelling differs from 'test_deleted_is_refused', the run itself is "
                 "there", run_map)
        check_in("and the repair is the mapping, never a rerun", "a rerun adds nothing", run_map)

        block["results"] = [{"instance_id": "", "test_id": "tests/test_oracle.py::"
                             "test_deleted_is_refused", "status": "passed"}]
        for path in (task / "work" / "run-blocks").glob("*.json"):
            path.write_text(json.dumps(block), encoding="utf-8")
        check_in("a reporter row nothing maps is named as that, not as a missing run",
                 "the mapping is missing, not the run", messages(P.run(task), "run_mapping"))
    finally:
        cleanup(root)


def the_oldest_manifest_row_is_named() -> None:
    """A `tests[]` row of the oldest shape — no `instance_id`, one function-level `selector`
    carrying every parameter — survived the 0.7.9 migration on TP1-15045 and made TC-012
    read as one test. `partial-green` names that row instead of a bare verdict."""
    root = temp_dir("qa-s5-legacy-")
    try:
        manifest = {
            "tests": [{"case": "TC-500", "file": "tests/test_validate.py", "marker": "TC-500",
                       "selector": "test_validate_per_partition[valid|warn|selfref]",
                       "status": "green"}],
            "unresolved": [{"case": "TC-500", "reason": "blocked_by_env",
                            "partitions": ["P-warn"]}]}
        task = make_story(root, manifest)
        man = messages(P.run(task), "manifest")
        check_in("the legacy row is named by its selector",
                 "test_validate_per_partition[valid|warn|selfref]", man)
        check_in("and the fix names who retires it",
                 "migrate_artifacts.py --task-root <TASK_ROOT> --if-older", man)
        check_in("while the covered partitions keep their runs",
                 "nothing here asks for a rerun", man)
    finally:
        cleanup(root)


def printed(result: dict) -> str:
    """What `s5_precheck.report` prints for this result."""
    import contextlib
    import io
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        P.report(result)
    return out.getvalue()


def precheck_is_project_agnostic() -> None:
    root = temp_dir("qa-s5-lang-")
    try:
        manifest = {"tests": [{"case": "TC-500", "file": "tests/ValidateTests.cs",
                               "marker": "TC-500", "instance_id": "TC-500::Validate",
                               "status": "green"}]}
        task = make_story(root, manifest)
        (root / "tests" / "ValidateTests.cs").write_text("// [Test] TC-500\n", encoding="utf-8")
        result = P.run(task)
        check_in("a non-Python test file is noted, never crashed on",
                 "is not a Python test file", "\n".join(result["notes"]))
        check_eq("and it produces no language-specific finding",
                 [f for f in result["findings"] if f["check"] == "smell"], [])
        # K-C4 (B-407 C, amendment 9): what the code could not read is LISTED, said in the note, and claimed for
        # nowhere - the code critic reads those files whole
        check_eq("K-C4: `unchecked` names the case, the file as the manifest wrote it and the checks not done",
                 result["unchecked"], [{"case": "TC-500", "file": "tests/ValidateTests.cs",
                                        "checks": ["Then assertions", "contradictions", "smells"]}])
        check_in("K-C4: the note says what the code did not do and who does",
                 "TC-500: ValidateTests.cs is not a Python test file; the code did not check its Then assertions, "
                 "contradictions or smells - the code critic reads them", result["notes"])
        quiet_ok = {"ok": True, "findings": [], "hints": [], "notes": [], "cases": ["TC-500"], "unchecked": []}
        legacy_line = ("OK: S5 exit checks pass for 1 case(s) (manifest invariants, Then bindings, oracle, run "
                       "mapping, obligation bindings).\n")
        check_eq("K-C4 (E-C8): a Python-only OK line is byte for byte the line it always was", printed(quiet_ok), legacy_line)
        check_eq("K-C4 (E-C8): ... and so is a result of the older shape that has no `unchecked` key at all",
                 printed({k: v for k, v in quiet_ok.items() if k != "unchecked"}), legacy_line)
        left = printed(dict(quiet_ok, unchecked=[
            {"case": "TC-500", "file": "tests/ValidateTests.cs", "checks": list(P.UNCHECKED_CHECKS)},
            {"case": "TC-501", "file": "tests/ValidateTests.cs", "checks": list(P.UNCHECKED_CHECKS)},
            {"case": "TC-501", "file": "ui/login.spec.ts", "checks": list(P.UNCHECKED_CHECKS)}]))
        check_eq("K-C4: the OK line names each unchecked file once and claims nothing for it", left,
                 "OK: S5 exit checks pass for 1 case(s) (manifest invariants, Then bindings, oracle, run mapping, "
                 "obligation bindings), except 2 test file(s) not checked by code for their Then "
                 "assertions, contradictions or smells (the code critic reads them in full): "
                 "tests/ValidateTests.cs, ui/login.spec.ts.\n")
        critic = " ".join((Path(P.__file__).resolve().parents[1] / "agents" / "qa-code-critic.md")
                          .read_text(encoding="utf-8").split())
        check("K-C4: the code critic's own text sends it to read the files the precheck lists as not checked by code",
              "not checked by code" in critic and "read those in full" in critic and "not checked by code" in left)
        py_only = temp_dir("qa-s5-pyonly-")
        try:
            clean = make_story(py_only, {"tests": [], "unresolved": []})
            done = P.run(clean)
            check_eq("K-C4 (E-C8): a story with no non-Python file has an empty `unchecked`", done["unchecked"], [])
            check_eq("K-C4 (E-C8): ... and its printed result is the legacy line, nothing else",
                     printed(done), "OK: S5 exit checks pass for 0 case(s) (manifest invariants, Then bindings, "
                     "oracle, run mapping, obligation bindings).\n")
        finally:
            cleanup(py_only)

        (root / "tests" / "broken.py").write_text("def test_x(:\n", encoding="utf-8")
        manifest["tests"][0]["file"] = "tests/broken.py"
        (task / "work" / "automation-manifest.json").write_text(json.dumps(manifest),
                                                                encoding="utf-8")
        check_in("a file that does not parse is a note, not a traceback",
                 "does not parse as Python", "\n".join(P.run(task)["notes"]))

        empty = temp_dir("qa-s5-empty-")
        try:
            bare = make_story(empty, {"tests": [], "unresolved": []})
            check("an empty manifest passes rather than refusing a story with nothing in it",
                  P.run(bare)["ok"] is True)
        finally:
            cleanup(empty)
    finally:
        cleanup(root)


def precheck_cli() -> None:
    root = temp_dir("qa-s5-cli-")
    try:
        task = make_story(root, {"tests": [{"case": "TC-500", "file": "tests/test_validate.py",
                                            "instance_id": "TC-500", "status": "green"}]})
        out = subprocess.run([sys.executable, "-B",
                              str(Path(__file__).resolve().parents[1] / "s5_precheck.py"),
                              "--task-root", str(task), "--json"],
                             capture_output=True, text=True, encoding="utf-8", timeout=120)
        check_eq("the CLI exits 1 on findings", out.returncode, 1)
        payload = json.loads(out.stdout)
        check("and prints the documented shape",
              set(payload) >= {"ok", "findings"} and payload["ok"] is False)
    finally:
        cleanup(root)


def batched_schedule() -> None:
    def request(instances, contracts, purpose="initial"):
        return {"task": "QA-1", "revision": "r1", "dispatch_id": "d1", "profile_id": "api",
                "purpose": purpose, "input_fingerprint": "f", "freshness": "fresh",
                "selected_instance_ids": instances, "instance_contracts": contracts,
                "command": {"reporter": "junit-xml", "selector_args": {i: [i] for i in instances}}}

    document = {"requests": [
        request(["TC-1::a"], {"TC-1::a": {"report_test_id": "t::a"}}),
        request(["TC-1::a", "TC-1::b"], {"TC-1::a": {"report_test_id": "t::a"},
                                         "TC-1::b": {"report_test_id": "t::b"}}),
    ]}
    merged, notes = RUN.merge_schedule(document)
    check_eq("a batch naming one instance twice becomes one request",
             len(merged["requests"]), 1)
    check_eq("and carries every instance of the case",
             merged["requests"][0]["selected_instance_ids"], ["TC-1::a", "TC-1::b"])
    check_eq("with a report_test_id for each", sorted(merged["requests"][0]["instance_contracts"]),
             ["TC-1::a", "TC-1::b"])
    check_in("the merge is said out loud, not done silently", "merged repeated instances",
             "\n".join(notes))

    different = {"requests": [request(["TC-1::a"], {"TC-1::a": {"report_test_id": "t::a"}}),
                              request(["TC-1::a"], {"TC-1::a": {"report_test_id": "t::a"}},
                                      purpose="red_probe")]}
    kept, notes2 = RUN.merge_schedule(different)
    check_eq("one instance under two different purposes is NOT merged away",
             len(kept["requests"]), 2)
    check_eq("and nothing is claimed about it", notes2, [])


def sandbox() -> None:
    repo = temp_dir("qa-s5-repo-")
    try:
        subprocess.run(["git", "init", "-q"], cwd=str(repo), capture_output=True, timeout=60)
        (repo / "tests").mkdir()
        (repo / "tests" / "test_old.py").write_text("def test_old():\n    assert 1\n",
                                                    encoding="utf-8")
        (repo / "qa-factory" / "state").mkdir(parents=True)
        dashboard = repo / "qa-factory" / "state" / "factory-dashboard.html"
        dashboard.write_text("<p>Generated 10:00</p>", encoding="utf-8")
        (repo / ".gitignore").write_text("ignored/\n", encoding="utf-8")
        (repo / "ignored").mkdir()
        (repo / "ignored" / "junk.py").write_text("x = 1\n", encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=str(repo), capture_output=True, timeout=60)
        subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "i"],
                       cwd=str(repo), capture_output=True, timeout=60)
        # The automator's new test file: written, never `git add`ed.
        new_test = repo / "tests" / "test_new.py"
        new_test.write_text("def test_new():\n    assert 2\n", encoding="utf-8")

        files = RS.repo_files(repo)
        check("an untracked, unignored test file is part of the sandbox",
              "tests/test_new.py" in files, sorted(files))
        check("an ignored file stays out", "ignored/junk.py" not in files)

        destination = Path(str(repo) + "-sandbox")
        receipt = RS.prepare(repo, destination, {"mutations": [
            {"path": "tests/test_new.py", "before_sha256": RS.digest(new_test),
             "replacement_utf8": "def test_new():\n    assert 3\n",
             "instance_id": "TC-1::test_new", "expected_location": "tests/test_new.py:2",
             "expected_reason": "assert 3"}]})
        check("the new test file reached the sandbox",
              (destination / "tests" / "test_new.py").is_file())
        check("and is in the integrity set",
              "tests/test_new.py" in receipt["original_hashes"])
        check_in("the factory's own generated state is excluded from the comparison",
                 "qa-factory/state/factory-dashboard.html", receipt["volatile"])

        dashboard.write_text("<p>Generated 10:01</p>", encoding="utf-8")
        result = RS.verify(receipt, [{"instance_id": "TC-1::test_new", "status": "failed",
                                      "failure_kind": "assertion",
                                      "location": "tests/test_new.py:2", "reason": "assert 3",
                                      "semantic_verdict": "intended_failure"}])
        check_eq("a dashboard redrawn under the probe no longer fails it",
                 result["status"], "accepted")

        survivor = [{"instance_id": "TC-1::test_new", "status": "passed"}]
        baseline = [{"instance_id": "TC-1::test_new", "status": "passed"}]
        defect = RS.verify(receipt, survivor, baseline)
        check_eq("a mutation that changes nothing is a probe defect, not a survivor",
                 defect["status"], "probe_defect")
        check_eq("owned by the factory", defect["proofs"][0].get("owner"), "factory")
        blamed = RS.verify(receipt, survivor)
        check_eq("with no unmutated run to compare, today's verdict stands",
                 blamed["proofs"][0]["verdict"], "incomplete_or_wrong_failure")

        try:
            RS.prepare(repo, Path(str(repo) + "-s2"), {"mutations": [
                {"path": "qa-factory/state/factory-dashboard.html",
                 "before_sha256": RS.digest(dashboard), "replacement_utf8": "x",
                 "instance_id": "i", "expected_location": "l", "expected_reason": "r"}]})
            check("a generated artefact cannot be a mutation target", False)
        except ValueError as exc:
            check_in("a generated artefact cannot be a mutation target",
                     "not a mutation target", str(exc))
        cleanup(destination)
    finally:
        cleanup(repo)


def request_template_is_complete() -> None:
    """C-F3: the skeleton carries every field the validator demands, each with a comment."""
    import execution_request as ER
    skeleton, legend = RUN.template("request")
    missing = [key for key in ("task", "revision", "dispatch_id", "profile_id", "purpose",
                               "input_fingerprint", "reason", "idempotency_key",
                               "selected_instance_ids", "current_scope_instance_ids",
                               "remaining_budget", "freshness", "runtime_provenance",
                               "runtime_probe", "fingerprint_components", "command",
                               "instance_contracts", "execution")
               if key not in skeleton]
    check_eq("the skeleton names every field validate_request requires", missing, [])
    check_eq("freshness is filled in, not left to guess", skeleton["freshness"], "fresh")
    check("a behavioral run is given a budget above zero", skeleton["remaining_budget"] > 0)
    check_eq("the purpose placeholder is one of the closed list",
             skeleton["purpose"] in ER.PURPOSES, True)
    check_eq("the reporter of execution matches the command's",
             skeleton["execution"]["reporter"]["format"], skeleton["command"]["reporter"])
    uncommented = [key for key in skeleton
                   if not any(line.strip().startswith(f"#   {key}:") for line in legend)]
    check_eq("every field carries its one-line comment", uncommented, [])
    schedule, schedule_legend = RUN.template("schedule")
    check_eq("a schedule skeleton names its own fields", sorted(schedule),
             ["max_workers", "min_selected_instances", "mode", "requests", "source_revision"])
    check_in("and says where its requests come from", "--template request",
             "\n".join(schedule_legend))
    result = run_script("run_suite.py", "--template", "request")
    check_eq("the CLI prints it and runs nothing", result.returncode, 0)
    check("stdout is loadable JSON on its own", isinstance(json.loads(result.stdout), dict))
    check_in("the legend goes to stderr, so a redirect leaves a usable file",
             "every field below is required", result.stderr)


def probe_publication_reads_the_author_record() -> None:
    """C-F2/C-F15: the publication branch honours --baseline, and the bindings are read from
    the manifest the author already wrote instead of a file nobody was told to write."""
    task = temp_dir("qa-s5-publish-")
    try:
        target = {"instance_id": "TC-1::test_limit", "expected_location": "tests/t.py:4",
                  "expected_reason": "denied", "mutation_kind": "real_behavior"}
        receipt = {"repo": str(task), "original_hashes": {}, "targets": [target]}
        survivor = [{"instance_id": "TC-1::test_limit", "status": "passed"}]
        baseline = [{"instance_id": "TC-1::test_limit", "status": "passed"}]
        try:
            RS.write_sensitivity_receipts(task, receipt, survivor, {"TC-1::test_limit": {
                "case_version": "cv_a", "test_content_hash": "t", "source_revision": "s",
                "build_id": "b", "restoration_evidence": "r"}}, baseline)
            check("a mutation that changed nothing is a probe defect at publication too", False)
        except ValueError as exc:
            check_in("a mutation that changed nothing is a probe defect at publication too",
                     "repair the mutation, do not repair the test", str(exc))

        (task / "work" / "run-blocks").mkdir(parents=True)
        (task / "work" / "automation-manifest.json").write_text(json.dumps({"tests": [
            {"case": "TC-1", "instance_id": "TC-1::test_limit", "status": "green",
             "case_version_links": [{"case_id": "TC-1", "version": "cv_a"}],
             "trace_binding": {"test_content_sha": "tsha"}}]}), encoding="utf-8")
        (task / "work" / "run-blocks" / "b1.json").write_text(json.dumps({
            "block_id": "b1", "runtime_provenance": {"observed_runtime_identity": "img:9"},
            "results": [{"instance_id": "TC-1::test_limit", "status": "passed",
                         "source_fingerprint": {"source_sha": "abc123", "test_content_sha": "tsha"}}]}),
            encoding="utf-8")
        bindings = RS.manifest_bindings(task, receipt)
        check_eq("the case version comes from the instance's own links",
                 bindings["TC-1::test_limit"]["case_version"], "cv_a")
        check_eq("the source revision comes from the run block that executed it",
                 bindings["TC-1::test_limit"]["source_revision"], "abc123")
        check_eq("the build identity comes from that block's runtime provenance",
                 bindings["TC-1::test_limit"]["build_id"], "img:9")
        check_in("the probe's own verified hashes are the restoration evidence",
                 "main-tree file hashes unchanged",
                 bindings["TC-1::test_limit"]["restoration_evidence"])

        proved = [{"instance_id": "TC-1::test_limit", "status": "failed",
                   "failure_kind": "assertion", "location": "tests/t.py:4",
                   "reason": "denied", "semantic_verdict": "intended_failure"}]
        refs = RS.write_sensitivity_receipts(task, receipt, proved, bindings)
        check("a receipt is published with no --bindings file at all",
              bool(refs["TC-1::test_limit"]["receipt_ref"]["sha256"]))

        (task / "work" / "automation-manifest.json").write_text(json.dumps({"tests": [
            {"case": "TC-1", "instance_id": "TC-1::test_limit"}]}), encoding="utf-8")
        try:
            RS.manifest_bindings(task, receipt)
            check("a gap in the author's record names the field, not a missing file", False)
        except ValueError as exc:
            check_in("a gap in the author's record names the field, not a missing file",
                     "case_version_links", str(exc))
    finally:
        cleanup(task)


def a_measured_number_is_not_a_status() -> None:
    """Live TP1-13797, 27.09: TC-002's Then 4 reads "The create call succeeds (2xx), and a
    subsequent GET returns the 500-character expression unchanged". `returns` + `500` matched the
    status pattern, so the gate told the automator its test contradicted a clause demanding HTTP
    500 — while the clause demands 2xx and says so. The automator held its ground and was right;
    it cost a boundary and a dispatch."""
    import s5_precheck as SP
    check_eq("the length in `500-character` is not a status demand",
             SP.clause_status_codes("The create call succeeds (2xx), and a subsequent GET "
                                    "returns the 500-character expression unchanged."), [])
    check_eq("nor is a count of items", SP.clause_status_codes("answers 200 items in one page"), [])
    check_eq("a real status demand still reads",
             SP.clause_status_codes("the save is rejected with status 400"), ["400"])
    check_eq("including a bare status word",
             SP.clause_status_codes("returns 404 Not Found"), ["404"])
    check_eq("and a backticked code",
             SP.clause_status_codes("the response code is `201`"), ["201"])
    check_eq("a status that is the number alone still reads",
             SP.clause_status_codes("the status is 500 and the body is empty"), ["500"])


def red_probe_holds_the_dashboard() -> None:
    import os
    saved = os.environ.pop("QA_FACTORY_SKIP_DASHBOARD_REFRESH", None)
    try:
        RUN.hold_dashboard("test")
        check_eq("the hold is an environment fact, so the children inherit it",
                 os.environ.get("QA_FACTORY_SKIP_DASHBOARD_REFRESH"), "1")
        RUN.refresh_dashboard()  # must be a no-op, not an import of the dashboard
        check("a held refresh does nothing at all", True)
    finally:
        os.environ.pop("QA_FACTORY_SKIP_DASHBOARD_REFRESH", None)
        os.environ.pop("QA_FACTORY_SKIP_DASHBOARD_REASON", None)
        if saved is not None:
            os.environ["QA_FACTORY_SKIP_DASHBOARD_REFRESH"] = saved


# --- B-194: a test changed between its red run and the next green run -------------------------
#
# Every fixture below is synthetic and built on the shape TP1-13797 (cmp1) produced for real,
# as the critic's measurement corrected it: the first attempt is RED by the junit of its own
# block while every ROW of it is `not_run` / "report row missing" (the reporter's ids are not the
# contract's); a later attempt "passed" but its rows are unmapped too; the parameter ids were
# renamed between the runs; the first `passed` row is a reparse block that carries no sha, and
# the shas live only in the job records of `state/execution-jobs/`.

FILTER_PY = '''"""Filter tests (TC-500, TC-501, TC-502)."""


class TestFilters:
    def test_invalid_filter_is_rejected(self, client):
        """@case TC-500."""
        assert_that(client.put("bad").status_code, equal_to(400))

    def test_boundary_valid(self, client):
        """@case TC-501."""
        assert_that(client.put("ok").status_code, equal_to(200))

    def test_matching_delivery(self, client):
        """@case TC-502."""
        assert_that(client.get().status_code, equal_to(200))
'''
FN = "test_invalid_filter_is_rejected"
FN_B = "test_boundary_valid"
FN_M = "test_matching_delivery"
TRIPLES = ((FN, "TC-500"), (FN_B, "TC-501"), (FN_M, "TC-502"))
KEY = "test_filter_mod.TestFilters." + FN
KEY_B = "test_filter_mod.TestFilters." + FN_B
CLASS = "tests.test_filter_mod.TestFilters"


def filter_story(root: Path, ticket: str = "QA-500", source: str = FILTER_PY,
                 tests: tuple = TRIPLES, file: str = "tests/test_filter_mod.py") -> Path:
    task = root / "qa-factory" / "artifacts" / ticket
    for folder in ("work/test-cases", "work/run-blocks", "state/execution-jobs", "evidence/runs"):
        (task / folder).mkdir(parents=True, exist_ok=True)
    (root / "tests").mkdir(parents=True, exist_ok=True)
    (root / file).write_text(source, encoding="utf-8")
    for case in ("TC-500", "TC-501", "TC-502", "TC-503"):
        (task / "work" / "test-cases" / f"{case}.md").write_text(
            CASE_MD.replace("TC-500", case), encoding="utf-8")
    manifest = {"tests": [{"case": case, "file": file, "instance_id": f"{fn}[P-new]",
                           "test_function": fn, "covers": [case], "status": "green"}
                          for fn, case in tests]}
    (task / "work" / "automation-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (task / "work" / "triage.json").write_text('{"triage": []}', encoding="utf-8")
    return task


def brow(fn: str, param: str, status: str, prefix: str, case: str, matched: bool = True,
         reason: str = "", **extra) -> dict:
    return {"instance_id": f"{fn}[{param}]", "test_id": f"{prefix}.test_filter_mod.TestFilters::{fn}[{param}]",
            "status": status, "reason": reason, "report_matched": matched,
            "case_version_links": [{"case_id": case, "version": "cv"}], **extra}


def unmapped(fn: str, param: str, prefix: str, case: str) -> dict:
    return brow(fn, param, "not_run", prefix, case, matched=False, reason="report row missing")


def junit(task: Path, attempt: str, cases: list) -> dict:
    """A raw junit report written under the story, and the evidence entry that names it."""
    def testcase(fn, param, outcome):
        inner = {"failed": '<failure message="assert 200 == 400"/>',
                 "error": '<error message="boom"/>'}.get(outcome, "")
        return f'<testcase classname="{CLASS}" name="{fn}[{param}]">{inner}</testcase>'
    xml = (f'<testsuites><testsuite name="s" tests="{len(cases)}">'
           + "".join(testcase(*c) for c in cases) + "</testsuite></testsuites>").encode("utf-8")
    relative = f"evidence/runs/{attempt}/report.junit.xml"
    (task / relative).parent.mkdir(parents=True, exist_ok=True)
    (task / relative).write_bytes(xml)
    return {"summary": "", "reporter": "junit-xml", "report_path": relative,
            "report_sha256": hashlib.sha256(xml).hexdigest()}


def write_block(task: Path, name: str, attempt: str, started, status: str, rows: list,
                evidence=None, dispatch: str = "S5-qa-automator-1", file_sha: str = "F",
                **extra) -> None:
    data = {"schema_version": 2, "block_id": attempt, "attempt_id": attempt,
            "attempt_started_at": started, "dispatch_id": dispatch, "purpose": "repair_verify",
            "source_fingerprint": {"test_content_sha": file_sha}, "execution_status": status,
            "results": rows, "evidence": [evidence] if evidence else [], **extra}
    if started is None:
        data.pop("attempt_started_at")
    (task / "work" / "run-blocks" / name).write_text(json.dumps(data), encoding="utf-8")


def write_job(task: Path, attempt: str, contracts: dict) -> None:
    """The job record of one attempt: `{instance id: (raw content sha, code sha)}`."""
    body = {"job_id": attempt, "request": {"instance_contracts": {
        iid: {"instance_content_sha": raw, "instance_code_sha": code,
              "instance_content_scope": "function"} for iid, (raw, code) in contracts.items()}}}
    (task / "state" / "execution-jobs" / f"{attempt}.json").write_text(json.dumps(body), encoding="utf-8")


def one_run(task: Path, attempt: str, minute: int, outcome: str, fields: dict, fn: str = FN,
            case: str = "TC-500", file_sha: str = "F", dispatch: str = "S5-qa-automator-1",
            evidence: bool = True, name: str = "") -> None:
    """One attempt of ONE function with its own junit and a row that carries `fields`."""
    started = f"2026-09-30T05:{minute:02d}:00+00:00"
    proof = junit(task, attempt, [(fn, "P-new", outcome)]) if evidence else None
    write_block(task, name or f"20260930T05{minute:02d}00000000Z-{attempt}.json", attempt, started,
                "passed" if outcome == "passed" else "failed",
                [brow(fn, "P-new", outcome, "tests", case, **fields)], proof, dispatch=dispatch,
                file_sha=file_sha)


def two_runs(task: Path, red: dict, green: dict, files: tuple = ("F1", "F2")) -> None:
    one_run(task, "r1", 0, "failed", red, file_sha=files[0])
    one_run(task, "g1", 10, "passed", green, file_sha=files[1])


A1, A2, A3, A4 = ("a1a1a1a1a1a1a1a1a1a1", "a2a2a2a2a2a2a2a2a2a2",
                  "a3a3a3a3a3a3a3a3a3a3", "a4a4a4a4a4a4a4a4a4a4")
A4_BLOCK = f"20260930T045703820495Z-{A4}.json"
A4_REPARSE = f"{A4}-reparse-90c4417c8064.json"
OLD = {FN: "P-old", FN_B: "P-b-old", FN_M: "P-m-old"}
NEW = {FN: "P-new", FN_B: "P-b-new", FN_M: "P-new"}


def cmp1_shape(task: Path) -> None:
    def passed_all(params):
        return [(fn, params[fn], "passed") for fn, _c in TRIPLES]
    red_junit = [(FN, OLD[FN], "failed"), (FN_B, OLD[FN_B], "passed"), (FN_M, OLD[FN_M], "passed")]
    write_block(task, f"20260930T044951000000Z-{A1}.json", A1, "2026-09-30T04:48:51.525234+00:00",
                "failed", [unmapped(fn, OLD[fn], "pkg_h.tests", case) for fn, case in TRIPLES],
                junit(task, A1, red_junit))
    write_block(task, f"20260930T045213000000Z-{A2}.json", A2, "2026-09-30T04:51:13.000000+00:00",
                "passed", [unmapped(fn, OLD[fn], "pkg_h.tests", case) for fn, case in TRIPLES],
                junit(task, A2, passed_all(OLD)))
    write_block(task, f"20260930T045436000000Z-{A3}.json", A3, "2026-09-30T04:54:00.000000+00:00",
                "broken_run", [unmapped(fn, NEW[fn], "pkg_h.tests", case) for fn, case in TRIPLES])
    evidence = junit(task, A4, passed_all(NEW))
    write_block(task, A4_BLOCK, A4, "2026-09-30T04:56:13.929353+00:00", "passed",
                [unmapped(fn, NEW[fn], "pkg_h.tests", case) for fn, case in TRIPLES], evidence)
    write_block(task, A4_REPARSE, A4, "2026-09-30T04:56:13.929353+00:00", "passed",
                [brow(fn, NEW[fn], "passed", "tests", case) for fn, case in TRIPLES], evidence,
                reparse_of=f"work/run-blocks/{A4_BLOCK}", supersedes_block_id=A4)
    write_job(task, A1, {f"{FN}[P-old]": ("r1", "043359472ce6"), f"{FN_B}[P-b-old]": ("rb1", "bcode1"),
                         f"{FN_M}[P-m-old]": ("rm1", "mcode1")})
    write_job(task, A4, {f"{FN}[P-new]": ("r4", "356e3dfc8977"), f"{FN_B}[P-b-new]": ("rb4", "bcode2"),
                         f"{FN_M}[P-new]": ("rm4", "mcode2")})


def changes_of(task: Path, **kwargs) -> dict:
    return P.run(task, **kwargs)["expectation_changes"]


def car(result: dict) -> list:
    """The `changed-after-red` findings of a run (every tag that starts with the word)."""
    return [f for f in result["findings"] if f["id"].split(":", 2)[2].startswith("changed-after-red")]


def the_cmp1_shape_is_found() -> None:
    root = temp_project("qa-s5-exp-")
    try:
        task = filter_story(root)
        cmp1_shape(task)

        def tree() -> dict:
            return {str(p.relative_to(task)): hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in sorted(task.rglob("*")) if p.is_file()}
        before = tree()
        result = P.run(task)
        check_eq("the measurement writes nothing into the story (FR-45)", tree(), before)
        pairs = result["expectation_changes"]["pairs"]
        check_eq("cmp1: exactly ONE pair (the two functions that only passed under a renamed id "
                 "are not red, whatever their rows say)", [p["function"] for p in pairs], [KEY])
        if not pairs:
            return  # the check above already failed; the rest reads the pair
        pair = pairs[0]
        check_eq("the red is the first attempt, confirmed by the junit of its own block",
                 (pair["red_attempt"], pair["red_status"], pair["red_basis"]), (A1, "failed", "report"))
        check_eq("the green is the reparse block that carries no sha",
                 (pair["green_attempt"], pair["green_block"]), (A4, A4_REPARSE))
        check_eq("the shas come from the job records, the code sha first",
                 (pair["sha_basis"], pair["red_sha"], pair["green_sha"]),
                 ("code", "043359472ce6", "356e3dfc8977"))
        check_eq("every spelling of the instance id is listed, the old and the renamed",
                 pair["instance_ids"], sorted([f"{FN}[P-old]", f"{FN}[P-new]"]))
        check_eq("the pair names its case, its stage and is owed", (pair["cases"], pair["stage_of_green"],
                                                                     pair["owed"], pair["record"]),
                 (["TC-500"], "S5", True, None))
        check_eq("the red run's own report is named", pair["red_evidence"],
                 f"evidence/runs/{A1}/report.junit.xml")

        found = car(result)
        check_eq("one finding for the one owed pair, in the oracle family",
                 [f["check"] for f in found], ["oracle"])
        fix = found[0]["fix"]
        check_in("the fix prints the exact command with the key and the attempts filled in",
                 "manifest_put.py --task QA-500 --fragment '", fix)
        check_in("with the function key", f'"function": "{KEY}"', fix)
        check_in("and both attempts", f'"red_attempt": "{A1}", "green_attempt": "{A4}"', fix)
        check_in("the second door is the red test with contradicts_requirement (FR-34)",
                 "hand the test over RED with `contradicts_requirement`", fix)
        check_not_in("no door names triage.json: the automator cannot write it (FR-2)",
                     "triage.json", found[0]["message"] + fix)
        check_in("and the person's word has its block word", '--block "changed-after-red"', fix)
        check("a story in flight (no expectation_changes key at all) gets the finding and is "
              "refused nothing else over the new field",
              "expectation_changes" not in json.loads(
                  (task / "work" / "automation-manifest.json").read_text(encoding="utf-8"))
              and not [f for f in result["findings"] if "expectation" in f["message"]
                       and f not in found])

        out = subprocess.run([sys.executable, "-B", str(Path(__file__).resolve().parents[1]
                                                        / "s5_precheck.py"),
                              "--task-root", str(task), "--json"],
                             capture_output=True, text=True, encoding="utf-8", timeout=120)
        payload = json.loads(out.stdout)
        check_eq("--json carries the pairs under expectation_changes",
                 [p["function"] for p in payload["expectation_changes"]["pairs"]], [KEY])
        check_eq("and the CLI exits 1 on the owed pair", out.returncode, 1)

        # R8: the finding does not depend on the open-oracle branch, which used to return first
        # (TQ1-1: the open-oracle branch is now the structural gate - Then 1 reads `unknown` with a question the register
        # does not hold, and the manifest binds it as proved)
        (task / "work" / "test-cases" / "TC-500.md").write_text(
            CASE_MD.replace("status: Draft\n", 'status: Draft\nthen_oracles: [{"then": 1, "source": "unknown", "ref": "Q4"}, '
                            '{"then": 2, "source": "requirement", "ref": "R-1"}, {"then": 3, "source": "requirement", "ref": "R-1"}]\n'),
            encoding="utf-8")
        manifest_path = task / "work" / "automation-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["then_bindings"] = [{"case": "TC-500", "then": 1, "instance_id": f"{FN}[P-new]",
                                      "assertion_ref": "tests/test_filter_mod.py:5", "status": "covered"}]
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        both = P.run(task)
        check("the open-oracle finding stands", any(f["id"].endswith(":open-oracle-asserted-1")
                                                     for f in both["findings"]))
        check_eq("and the changed-after-red finding is not swallowed by its early return",
                 len(car(both)), 1)
    finally:
        cleanup(root)


def the_sha_chain_decides_same_or_changed() -> None:
    """The first basis present on BOTH sides decides: code sha, raw content sha, the block's
    file-level sha. Unknown on every level is CHANGED, never same (FR-41)."""
    root = temp_project("qa-s5-chain-")
    try:
        table = [
            ("a neighbour test of the same file changed: the file sha moved, this test's did not",
             {"instance_code_sha": "c1", "instance_content_sha": "r1"},
             {"instance_code_sha": "c1", "instance_content_sha": "r1"}, ("F1", "F2"), None),
            ("a comment-only edit: the raw sha moved, the code sha did not",
             {"instance_code_sha": "c1", "instance_content_sha": "r1"},
             {"instance_code_sha": "c1", "instance_content_sha": "r2"}, ("F1", "F2"), None),
            ("a changed body: the code sha moved",
             {"instance_code_sha": "c1", "instance_content_sha": "r1"},
             {"instance_code_sha": "c2", "instance_content_sha": "r2"}, ("F1", "F1"), "code"),
            ("no code sha anywhere, raw content sha equal: the file sha is not consulted",
             {"instance_content_sha": "r1"}, {"instance_content_sha": "r1"}, ("F1", "F2"), None),
            ("no code sha anywhere, raw content sha moved",
             {"instance_content_sha": "r1"}, {"instance_content_sha": "r2"}, ("F1", "F1"), "raw"),
            ("a code sha on ONE side only: the first basis on BOTH sides decides",
             {"instance_content_sha": "r1"},
             {"instance_code_sha": "c2", "instance_content_sha": "r1"}, ("F1", "F2"), None),
            ("only the file sha, equal", {}, {}, ("F1", "F1"), None),
            ("only the file sha, moved", {}, {}, ("F1", "F2"), "file"),
            ("no sha at all, on either side: unknown counts as CHANGED", {}, {}, ("", ""), "unknown"),
            ("no sha on one side only: unknown too", {"instance_code_sha": "c1"}, {}, ("", ""), "unknown"),
        ]
        for n, (label, red, green, files, basis) in enumerate(table):
            task = filter_story(root, ticket=f"QA-51{n}")
            two_runs(task, red, green, files)
            pairs = changes_of(task)["pairs"]
            check_eq(label, [p["sha_basis"] for p in pairs], [basis] if basis else [])
    finally:
        cleanup(root)


def the_reused_function_lands_on_the_safe_side() -> None:
    """`function_sha` may only err toward "different". Real shas from the real function, fed
    through the pairing: what must be `same` is, and every input a gate must not miss is not."""
    import execution_fingerprint as EF
    work = temp_dir("qa-s5-fsha-")
    root = temp_project("qa-s5-safe-")
    try:
        path, helper = work / "test_m.py", work / "conftest.py"
        base = ('PARAMS = [1, 2]\n\n\nclass TestFilters:\n    LIMIT = 5\n\n'
                '    def test_x(self, client):\n        """@case TC-500."""\n'
                '        # explains\n        assert client.get() == 400\n\n'
                '    def test_other(self):\n        assert 1\n')
        helper_v1 = "import pytest\n\n\n@pytest.fixture\ndef client():\n    return 1\n"

        def shas(source: str, fixture: str = helper_v1) -> dict:
            path.write_text(source, encoding="utf-8")
            helper.write_text(fixture, encoding="utf-8")
            got = EF.function_sha(str(path), "test_x", ("TestFilters",), helper_files=[str(helper)],
                                  cache={})
            return {"instance_code_sha": got["code_sha"], "instance_content_sha": got["sha"]}

        before = shas(base)
        cases = [
            ("a comment-only edit is the same test", base.replace("# explains", "# explains more"), helper_v1, False),
            ("a marker-only edit is the same test", base.replace("@case TC-500.", "@case TC-500 TC-501."), helper_v1, False),
            ("an edit of a NEIGHBOUR test is not this test's change", base.replace("assert 1", "assert 2"), helper_v1, False),
            ("a literal in the body is a change", base.replace("== 400", "== 403"), helper_v1, True),
            ("a module-level constant is a change", base.replace("[1, 2]", "[1, 2, 3]"), helper_v1, True),
            ("a class-level constant is a change", base.replace("LIMIT = 5", "LIMIT = 6"), helper_v1, True),
            ("a conftest fixture is a change", base, helper_v1.replace("return 1", "return 2"), True),
            ("an unparsable file is a change", "def test_x(:\n", helper_v1, True),
        ]
        for n, (label, source, fixture, changed) in enumerate(cases):
            task = filter_story(root, ticket=f"QA-52{n}")
            two_runs(task, before, shas(source, fixture), files=("F", "F"))
            check_eq(label, len(changes_of(task)["pairs"]), 1 if changed else 0)
    finally:
        cleanup(root)
        cleanup(work)


def several_reds_and_a_change_that_was_undone() -> None:
    root = temp_project("qa-s5-many-")
    try:
        task = filter_story(root, ticket="QA-530")
        one_run(task, "r1", 0, "failed", {"instance_code_sha": "X"})
        one_run(task, "r2", 5, "failed", {"instance_code_sha": "Y"})
        one_run(task, "g1", 10, "passed", {"instance_code_sha": "Z"})
        pairs = changes_of(task)["pairs"]
        check_eq("several reds before the green: ONE pair, from the FIRST red after the last pass",
                 [(p["red_attempt"], p["green_attempt"]) for p in pairs], [("r1", "g1")])
        check_eq("and the sha of the red in between is listed",
                 [p["intermediate_shas"] for p in pairs], [["Y"]])
        task = filter_story(root, ticket="QA-531")
        one_run(task, "r1", 0, "failed", {"instance_code_sha": "X"})
        one_run(task, "r2", 5, "failed", {"instance_code_sha": "Y"})
        one_run(task, "g1", 10, "passed", {"instance_code_sha": "X"})
        check_eq("changed and changed back is identical bytes: no pair", changes_of(task)["pairs"], [])
        task = filter_story(root, ticket="QA-532")
        one_run(task, "r1", 0, "failed", {"instance_code_sha": "X"})
        one_run(task, "g1", 5, "passed", {"instance_code_sha": "Y"})
        one_run(task, "r2", 10, "failed", {"instance_code_sha": "Y"})
        one_run(task, "g2", 15, "passed", {"instance_code_sha": "W"})
        check_eq("red -> green -> red -> green on new bytes is two pairs, each from its own red",
                 [(p["red_attempt"], p["green_attempt"]) for p in changes_of(task)["pairs"]],
                 [("r1", "g1"), ("r2", "g2")])
    finally:
        cleanup(root)


def a_reparse_is_ordered_by_time_not_by_name() -> None:
    """R3a/R16a. A reparse block is named `<attempt>-reparse-<hash>.json` and keeps the
    attempt_started_at of the block it supersedes. An attempt id that starts with `0` sorts before
    every `2026...` file name, so ordering by name put the reparse's `passed` before the red."""
    root = temp_project("qa-s5-order-")
    try:
        task = filter_story(root, ticket="QA-540")
        attempt = "0bb0bb0bb0bb0bb0bb0b"
        one_run(task, "r1", 0, "failed", {})
        write_block(task, f"20260930T051000000000Z-{attempt}.json", attempt,
                    "2026-09-30T05:10:00+00:00", "passed",
                    [unmapped(FN, "P-new", "pkg_h.tests", "TC-500")],
                    junit(task, attempt, [(FN, "P-new", "passed")]))
        write_block(task, f"{attempt}-reparse-abc123.json", attempt, "2026-09-30T05:10:00+00:00",
                    "passed", [brow(FN, "P-new", "passed", "tests", "TC-500")],
                    junit(task, attempt, [(FN, "P-new", "passed")]),
                    reparse_of=f"work/run-blocks/20260930T051000000000Z-{attempt}.json",
                    supersedes_block_id=attempt)
        write_job(task, "r1", {f"{FN}[P-new]": ("r1", "code-1")})
        write_job(task, attempt, {f"{FN}[P-new]": ("r2", "code-2")})
        blocks, bad = P.read_run_blocks(task)
        check_eq("blocks are ordered by their clock, the reparse right after its own attempt",
                 [b["name"] for b in blocks],
                 ["20260930T050000000000Z-r1.json", f"20260930T051000000000Z-{attempt}.json",
                  f"{attempt}-reparse-abc123.json"])
        check_eq("and every readable block is read", bad, [])
        check_eq("the pair is the red and the reparse's pass, by time",
                 [(p["red_attempt"], p["green_block"], p["sha_basis"])
                  for p in changes_of(task)["pairs"]], [("r1", f"{attempt}-reparse-abc123.json", "code")])
        rows = P.run_block_rows(task)
        check_eq("run_block_rows carries that order to every reader (R16)",
                 [r["block"] for r in rows][-1], f"{attempt}-reparse-abc123.json")
        result = P.run(task)
        check_not_in("check_run_mapping reads the reparse's row as the NEWEST, not the original's "
                     "not_run", "newest run block says", messages(result, "run_mapping"))

        # a block with no attempt_started_at is ordered by the stamp of its file name, and a
        # reparse of it takes its parent's clock; equal or missing clocks say so in the note
        task = filter_story(root, ticket="QA-541")
        one_run(task, "r1", 0, "failed", {"instance_code_sha": "X"})
        one_run(task, "g1", 10, "passed", {"instance_code_sha": "Y"})
        for name in ("20260930T050000000000Z-r1.json", "20260930T051000000000Z-g1.json"):
            data = json.loads((task / "work" / "run-blocks" / name).read_text(encoding="utf-8"))
            data.pop("attempt_started_at")
            (task / "work" / "run-blocks" / name).write_text(json.dumps(data), encoding="utf-8")
        pair = changes_of(task)["pairs"][0]
        check_eq("no clock inside the blocks: the file-name stamp orders them, and the pair says the "
                 "order was not measured", (pair["red_attempt"], pair["note"]),
                 ("r1", "attempt order unknown"))
        # the SAME attempt is never "order unknown": the reparse follows its original
        task = filter_story(root, ticket="QA-542")
        one_run(task, "r1", 0, "failed", {"instance_code_sha": "X"})
        write_block(task, "r1-reparse-1.json", "r1", "2026-09-30T05:00:00+00:00", "passed",
                    [brow(FN, "P-new", "passed", "tests", "TC-500", instance_code_sha="Y")],
                    reparse_of="work/run-blocks/20260930T050000000000Z-r1.json",
                    supersedes_block_id="r1")
        check_eq("a red and a pass of ONE attempt (the reparse): a pair with no order note when the "
                 "shas differ", [(p["red_attempt"], p["green_attempt"], p["note"])
                                 for p in changes_of(task)["pairs"]], [("r1", "r1", "")])
    finally:
        cleanup(root)


def a_red_is_confirmed_by_its_own_report() -> None:
    root = temp_project("qa-s5-red-")
    try:
        # a row that says `failed` while the raw report says it passed is not red
        task = filter_story(root, ticket="QA-550")
        write_block(task, "20260930T050000000000Z-r1.json", "r1", "2026-09-30T05:00:00+00:00",
                    "failed", [brow(FN, "P-new", "failed", "tests", "TC-500", instance_code_sha="X")],
                    junit(task, "r1", [(FN, "P-new", "passed")]))
        one_run(task, "g1", 10, "passed", {"instance_code_sha": "Y"})
        check_eq("a function that PASSED in the red block's raw report is not red, whatever its row says",
                 changes_of(task)["pairs"], [])
        # the report cannot be read: the row's own word, marked as unconfirmed
        for label, ticket, red_row, evidence, expected in (
                ("no report at all: an unmapped row of a failed block is `red_unconfirmed`", "QA-551",
                 unmapped(FN, "P-new", "pkg_h.tests", "TC-500"), False, ("red_unconfirmed", "unconfirmed")),
                ("no report at all: a `failed` row is taken as it says, marked as the row's word", "QA-552",
                 brow(FN, "P-new", "failed", "tests", "TC-500"), False, ("failed", "row")),
                ("a report whose sha256 is not the recorded one cannot be read either", "QA-553",
                 unmapped(FN, "P-new", "pkg_h.tests", "TC-500"), True, ("red_unconfirmed", "unconfirmed"))):
            task = filter_story(root, ticket=ticket)
            proof = None
            if evidence:
                proof = junit(task, "r1", [(FN, "P-new", "failed")])
                proof["report_sha256"] = "0" * 64
            write_block(task, "20260930T050000000000Z-r1.json", "r1", "2026-09-30T05:00:00+00:00",
                        "failed", [{**red_row, "instance_code_sha": "X"}], proof)
            one_run(task, "g1", 10, "passed", {"instance_code_sha": "Y"})
            got = changes_of(task)["pairs"]
            check_eq(label, [(p["red_status"], p["red_basis"]) for p in got], [expected])
        # a run with no product outcome never manufactures a red
        task = filter_story(root, ticket="QA-554")
        for n, (status, reason, block_status) in enumerate((
                ("not_run", "report row missing", "broken_run"), ("skipped", "flaky stand", "failed"),
                ("not_run", "inconclusive", "failed"), ("not_run", "report row missing", "timeout"))):
            write_block(task, f"20260930T04{n}000000000Z-x{n}.json", f"x{n}",
                        f"2026-09-30T04:0{n}:00+00:00", block_status,
                        [brow(FN, "P-new", status, "tests", "TC-500", matched=False, reason=reason,
                              instance_code_sha="X")])
        one_run(task, "g1", 10, "passed", {"instance_code_sha": "Y"})
        check_eq("broken_run, skipped, inconclusive and timeout are never red", changes_of(task)["pairs"], [])
    finally:
        cleanup(root)


def an_orphaned_red_and_a_test_handed_over_red() -> None:
    root = temp_project("qa-s5-orphan-")
    try:
        # the red test is gone from its file (renamed): its expectation went somewhere
        task = filter_story(root, ticket="QA-560")
        one_run(task, "r1", 0, "failed", {"instance_code_sha": "X"}, fn="test_gone")
        result = P.run(task)
        pairs = result["expectation_changes"]["pairs"]
        check_eq("a red whose function is absent from the current test file is an orphaned red",
                 [(p["function"], p["green_attempt"], p["orphan"], p["owed"]) for p in pairs],
                 [("test_filter_mod.TestFilters.test_gone", None, True, True)])
        check_in("its finding says the test no longer exists", "no test of that name exists any more",
                 car(result)[0]["message"])
        check_in("and its fix offers the same record, with a null green attempt",
                 '"green_attempt": null', car(result)[0]["fix"])
        # a test that still exists and is handed over RED owes nothing
        task = filter_story(root, ticket="QA-561")
        one_run(task, "r1", 0, "failed", {"instance_code_sha": "X"})
        one_run(task, "r2", 5, "failed", {"instance_code_sha": "X"})
        result = P.run(task)
        check_eq("a test that still exists and stays RED (FR-34) has no pair", result["expectation_changes"]["pairs"], [])
        check_eq("and no finding", car(result), [])
        # the file cannot tell whether the function still exists: said, not guessed
        task = filter_story(root, ticket="QA-562", source="// [Test] TC-500\n", file="tests/Filters.cs")
        one_run(task, "r1", 0, "failed", {"instance_code_sha": "X"})
        got = changes_of(task)
        check_eq("no Python file to read: no pair is invented", got["pairs"], [])
        check_in("and the measurement says it could not tell", "cannot be read", got["unmeasured"])
    finally:
        cleanup(root)


def pairs_of_another_stage_are_listed_not_owed() -> None:
    root = temp_project("qa-s5-stage-")
    try:
        task = filter_story(root, ticket="QA-570")
        one_run(task, "r1", 0, "failed", {"instance_code_sha": "X"}, dispatch="S6-qa-runner-1")
        one_run(task, "g1", 10, "passed", {"instance_code_sha": "Y"}, dispatch="S7-qa-automator-2")
        result = P.run(task)
        pair = result["expectation_changes"]["pairs"][0]
        check_eq("red at S6, green at S7: the pair is listed", (pair["stage_of_green"], pair["owed"]), ("S7", False))
        check_eq("and owes nothing at S5", car(result), [])
        check_in("a note lists it", "listed, nothing is owed at S5", "\n".join(result["notes"]))
        # the controller's record of the dispatch wins over the spelling of its id
        state = task / "state" / "controller.json"
        for dispatch, stage, owed in (("run-7", "S7", False), ("run-5", "S5", True)):
            state.write_text(json.dumps({"dispatches": {dispatch: {"id": dispatch, "stage": stage}}}),
                             encoding="utf-8")
            one_run(task, "g1", 10, "passed", {"instance_code_sha": "Y"}, dispatch=dispatch)
            one_run(task, "r1", 0, "failed", {"instance_code_sha": "X"}, dispatch=dispatch)
            check_eq(f"a dispatch the controller says is {stage}", changes_of(task)["pairs"][0]["owed"], owed)
        # outside the check's scope nothing is owed either
        state.write_text(json.dumps({"dispatches": {"d": {"id": "d", "stage": "S5", "scope": ["TC-501"]}}}),
                         encoding="utf-8")
        check_eq("a pair with no case in this dispatch's scope is listed only",
                 [p["owed"] for p in P.run(task, "d")["expectation_changes"]["pairs"]], [False])
    finally:
        cleanup(root)


def put(root: Path, ticket: str, fragment) -> "subprocess.CompletedProcess":
    path = root / "fragment.json"
    path.write_text(json.dumps(fragment, ensure_ascii=False), encoding="utf-8")
    return run_script("manifest_put.py", "--task", ticket, "--fragment", path, cwd=root,
                      env={**os.environ, "CLAUDE_PROJECT_DIR": str(root)})


def manifest_of(task: Path) -> dict:
    return json.loads((task / "work" / "automation-manifest.json").read_text(encoding="utf-8"))


def a_record_answers_the_finding() -> None:
    root = temp_project("qa-s5-record-")
    try:
        task = filter_story(root)
        cmp1_shape(task)
        finding = car(P.run(task))[0]
        raw = re.search(r"--fragment '(.*?)'`", finding["fix"]).group(1)
        fragment = json.loads(raw)
        row = fragment["expectation_changes"][0]
        check_eq("the printed fragment is valid JSON with the key and attempts filled in",
                 (row["function"], row["red_attempt"], row["green_attempt"]), (KEY, A1, A4))
        row.update(then_refs=[{"case": "TC-500", "then": 1}], what_changed="400 -> 422",
                   reason="the case leaves the exact status of a malformed filter open")
        done = put(root, "QA-500", fragment)
        check_eq("manifest_put takes the row the finding printed", done.returncode, 0)
        check_in("and says how many records it holds", "expectation_changes: 1 record(s)", done.stdout)
        result = P.run(task)
        check_eq("the finding is gone once the record is in", car(result), [])
        pair = result["expectation_changes"]["pairs"][0]
        check_eq("the pair stays, with its record joined", pair["record"]["what_changed"], "400 -> 422")
        check_in("and a note says it is recorded and not judged yet",
                 "recorded in expectation_changes[], not judged yet", "\n".join(result["notes"]))
        # the critic's verdict is one more fragment for the same key; the author's fields survive
        verdict = {"expectation_changes": [{"function": KEY, "red_attempt": A1, "green_attempt": A4,
                                            "critic_verdict": "legitimate_correction",
                                            "critic_note": "the case fixes no status"}]}
        check_eq("a verdict patch is accepted", put(root, "QA-500", verdict).returncode, 0)
        rows = manifest_of(task)["expectation_changes"]
        check_eq("one record still, author's reason and critic's verdict together",
                 (len(rows), rows[0]["reason"][:20], rows[0]["critic_verdict"]),
                 (1, "the case leaves the ", "legitimate_correction"))
        result = P.run(task)
        check_in("the note carries the verdict", "the critic's verdict is legitimate_correction",
                 "\n".join(result["notes"]))
        check_eq("the joined record is what --json shows", result["expectation_changes"]["pairs"][0]
                 ["record"]["critic_verdict"], "legitimate_correction")
        # a record whose pair does not exist is history: accepted, counted nowhere
        stale = {"expectation_changes": [{"function": "test_x.T.test_other", "red_attempt": "zz1",
                                          "green_attempt": "zz2", "then_refs": [{"case": "TC-500", "then": 1}],
                                          "what_changed": "old", "reason": "an earlier window"}]}
        check_eq("a record with no matching pair is accepted", put(root, "QA-500", stale).returncode, 0)
        after = P.run(task)
        check_eq("and counted nowhere: same pairs, no finding, no note for it",
                 ([p["function"] for p in after["expectation_changes"]["pairs"]], car(after),
                  [n for n in after["notes"] if "test_other" in n]), ([KEY], [], []))
    finally:
        cleanup(root)


def a_bad_then_ref_is_a_finding() -> None:
    root = temp_project("qa-s5-refs-")
    try:
        task = filter_story(root)
        cmp1_shape(task)

        def with_refs(refs) -> dict:
            manifest = manifest_of(task)
            manifest["expectation_changes"] = [{"function": KEY, "red_attempt": A1, "green_attempt": A4,
                                                "then_refs": refs, "what_changed": "w", "reason": "r"}]
            (task / "work" / "automation-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            return P.run(task)

        for label, refs, wanted in (
                ("a Then the case file does not have", [{"case": "TC-500", "then": 9}], "has no Then 9"),
                ("a case outside this check's scope", [{"case": "TC-999", "then": 1}], "TC-999 is not a case of"),
                ("no ref at all", [], "`then_refs` is empty or missing"),
                ("a ref that is not an object", ["TC-500"], "is not an object")):
            result = with_refs(refs)
            found = car(result)
            check_eq(label + ": one finding, about the record", len(found), 1)
            check_in(label + ": it says what does not resolve", wanted, found[0]["message"])
            check("the finding is about the record, so the pair is not asked for a second record",
                  "nothing records" not in found[0]["message"])
        check_eq("a ref that resolves is no finding", car(with_refs([{"case": "TC-500", "then": 2}])), [])
    finally:
        cleanup(root)


def one_record_may_name_several_functions() -> None:
    root = temp_project("qa-s5-several-")
    try:
        task = filter_story(root, ticket="QA-580")
        one_run_two = [(FN, "TC-500"), (FN_B, "TC-501")]
        write_block(task, "20260930T050000000000Z-r1.json", "r1", "2026-09-30T05:00:00+00:00", "failed",
                    [brow(fn, "P-new", "failed", "tests", case, instance_code_sha="X") for fn, case in one_run_two],
                    junit(task, "r1", [(fn, "P-new", "failed") for fn, _c in one_run_two]))
        write_block(task, "20260930T051000000000Z-g1.json", "g1", "2026-09-30T05:10:00+00:00", "passed",
                    [brow(fn, "P-new", "passed", "tests", case, instance_code_sha="Y") for fn, case in one_run_two],
                    junit(task, "g1", [(fn, "P-new", "passed") for fn, _c in one_run_two]))
        result = P.run(task)
        check_eq("two functions changed between the same two runs: two owed pairs, two findings",
                 (len(result["expectation_changes"]["pairs"]), len(car(result))), (2, 2))
        check_in("each fix offers ONE record naming both (an edit of the module skeleton moves every sha)",
                 f'"functions": ["{KEY_B}", "{KEY}"]', car(result)[0]["fix"])
        record = {"functions": [KEY_B, KEY], "red_attempt": "r1", "green_attempt": "g1",
                  "then_refs": [{"case": "TC-500", "then": 1}], "what_changed": "conftest",
                  "reason": "the shared fixture changed"}
        manifest = manifest_of(task)
        manifest["expectation_changes"] = [record]
        (task / "work" / "automation-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        result = P.run(task)
        check_eq("one record answers both pairs, in any order of its functions", car(result), [])
        check_eq("and both pairs carry it", [p["record"] == record
                                              for p in result["expectation_changes"]["pairs"]], [True, True])
        manifest["expectation_changes"] = [dict(record, functions=[KEY])]
        (task / "work" / "automation-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        again = P.run(task)
        check_eq("a record naming ONE of them leaves the other owed", len(car(again)), 1)
        check_in("and it is the other one", "test_boundary_valid", car(again)[0]["message"])
    finally:
        cleanup(root)


def a_persons_word_passes_this_finding_only() -> None:
    import waiver as W
    root = temp_project("qa-s5-word-")
    try:
        task = filter_story(root)
        cmp1_shape(task)
        manifest = manifest_of(task)
        # another oracle finding in the same run: a deferral that disputes the approved case
        manifest["unresolved"] = [{"case": "TC-503", "reason": "deferred_by_decision:designer",
                                   "disputes": "case_expectation", "detail": "the case is wrong"}]
        (task / "work" / "automation-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        before = P.run(task)
        check("the run has both: the pair and another oracle finding",
              len(car(before)) == 1 and any(f["id"].endswith(":case-is-oracle") for f in before["findings"]))

        def with_word(block: str) -> dict:
            pipeline = {"task": "QA-500"}
            W.apply_stage_override(pipeline, "S5", block, "the person accepts the fixture change", W.now_iso())
            (task / "pipeline.json").write_text(json.dumps(pipeline), encoding="utf-8")
            return P.run(task)

        other = with_word("case-is-oracle")
        check_eq("a word for ANOTHER block does not pass this finding", len(car(other)), 1)
        passed = with_word("changed-after-red")
        check_eq("the person's word passes the changed-after-red finding", car(passed), [])
        check("and no other oracle finding: the deferral still stands",
              any(f["id"].endswith(":case-is-oracle") for f in passed["findings"]))
        check_eq("and every other finding of the run stands",
                 sorted(f["id"] for f in passed["findings"]),
                 sorted(f["id"] for f in before["findings"] if f not in car(before)))
        check_in("a note says which word passed it", "passed by the person's word: the person accepts",
                 "\n".join(passed["notes"]))
        pair = passed["expectation_changes"]["pairs"][0]
        check_eq("the pair stays in --json, marked as passed by the word",
                 (pair["function"], pair["passed_by_word"], pair["record"]), (KEY, True, None))
        check_eq("an unwaived pair is not marked", before["expectation_changes"]["pairs"][0]["passed_by_word"], False)
        narrow = with_word(f"changed-after-red-{KEY}")
        # the function key alone is no pair's own tag (`test_a` is inside `test_ab`, and one function can have two pairs): a word
        # naming only the function passes nothing; the pair's own tag does (`_pair_tag`)
        check_eq("a word naming only the function passes no pair (it is no pair's own tag)", len(car(narrow)), 1)
        check_eq("a word naming the pair's own tag passes it", car(with_word(P._pair_tag(passed['expectation_changes']['pairs'][0]))), [])
        wrong = with_word("changed-after-red-test_gone")
        check_eq("and a word naming another function does not", len(car(wrong)), 1)
    finally:
        cleanup(root)


def the_judge_may_not_downgrade_it() -> None:
    import judge
    root = temp_project("qa-s5-judge-")
    saved = (judge.settings, judge.active, judge.judged_refusal)
    try:
        task = filter_story(root)
        parsed, _problem = P.read_python(root / "tests" / "test_filter_mod.py")
        findings = [P._finding("oracle", "TC-500", "the pair", "fix", "changed-after-red-x-r1-g1"),
                    P._finding("bindings", "TC-500", "Then 1 of TC-500: a contradiction the judge IS asked about", "fix",
                               "contradicted-1")]
        asked: list = []
        judge.settings = lambda *_a, **_k: {"provider": "typesafe", "mode": "on"}
        judge.active = lambda *_a, **_k: True

        def passing(refusal, judgment, state, **_k):
            asked.append(refusal)
            return {"passed": True, "note": "stub says it passes"}
        judge.judged_refusal = passing
        hints, notes = [], []
        kept = P.passed_by_judge(task, findings, hints, notes, {"TC-500": [parsed]},
                                 {"TC-500": CASE_MD})
        check_eq("a judge that passes everything still leaves changed-after-red standing",
                 [f["id"].split(":", 2)[2] for f in kept], ["changed-after-red-x-r1-g1"])
        check_eq("the downgrade of the Then contradiction stays: it is the one family the judge is asked about (X7-2, F-P1 a)",
                 asked, ["s5_then_contradiction"])
        check_eq("and it became a hint", [h["id"].split(":", 2)[2] for h in hints], ["contradicted-1"])
        check_eq("F-P1 (a): the judged families are the `bindings contradicted-` line only",
                 [(row[0], row[1]) for row in P.JUDGED_FINDINGS], [("bindings", "contradicted-")])
        check_eq("X7-2: a case-is-oracle finding and a smell have no judge question any more",
                 [P._judge_plan(P._finding(check, "TC-500", "m", "f", tag), task, {"TC-500": [parsed]}, {"TC-500": CASE_MD})
                  for check, tag in (("oracle", "case-is-oracle"), ("smell", "sleep-x"), ("oracle", "relative-oracle-x"))],
                 [None, None, None])
    finally:
        judge.settings, judge.active, judge.judged_refusal = saved
        cleanup(root)


# --- TQ1-1 (t-684): `open-oracle-asserted` - a Then whose expected value nobody confirmed is never bound to an assert -------------
# The fixture is the cmp2 TC_014 case (the shared file is NOT edited): the temp story gets a `then_oracles` line and a dated `updated`.
OA_FIXTURES = Path(__file__).resolve().parent / "fixtures"
OA_PY = '''"""Tests for TC-500."""


def test_noproject(client):
    """@case TC-500 - P-noproject."""
    r = client.post("/v1/workflows/w/validate")
    assert r.status_code == 403
'''
OA_FN = "test_noproject"
OA_INSTANCE = f"{OA_FN}[P-new]"
OA_ASSERT = "tests/test_filter_mod.py:6"
OA_TAG = "open-oracle-asserted"


def oa_entry(then, source, ref) -> dict:
    return {"then": then, "source": source, "ref": ref}


def oa_oracles(two=("unknown", "Q4"), three=("unknown", "Q4")) -> list:
    return [oa_entry(1, "requirement", "R-16"), oa_entry(2, *two), oa_entry(3, *three),
            oa_entry(4, "requirement", "R-16"), oa_entry(5, "requirement", "R-16")]


OA_QTHENS = [{"question": "Q4", "then": 2, "readings": {"a": "403 Forbidden", "b": "401 Unauthorized"}, "not_needed": ""},
             {"question": "Q4", "then": 3, "readings": {"a": "403 Forbidden", "b": "401 Unauthorized"}, "not_needed": ""}]


def oa_readiness() -> str:
    """The register file: the fixture's Q1 re-numbered Q4, and its Q7 (a before/now question, `before` unknown)."""
    data = json.loads((OA_FIXTURES / "oracle-provenance" / "requirements-readiness.json").read_text(encoding="utf-8"))
    q4 = dict(next(q for q in data["open_questions"] if q["id"] == "Q1"), id="Q4")
    data["open_questions"] = [q4] + [q for q in data["open_questions"] if q["id"] == "Q7"]
    return json.dumps(data, indent=2)


def oa_story(root: Path, oracles="default", qthens="default", bind=(2,), extra=(), date="2026-10-02", register=True,
             raw_line=None, rows=None) -> Path:
    """TC-500 = cmp2 TC_014 with a `then_oracles` line; the test file asserts `== 403`; the manifest binds the Thens of
    `bind` covered to that instance (with `assertion_ref`) plus the `extra` rows (or exactly `rows`)."""
    import shutil
    shutil.rmtree(root / "qa-factory" / "artifacts" / "QA-500", ignore_errors=True)  # a recorded answer must not outlive its scenario
    task = filter_story(root, source=OA_PY, tests=((OA_FN, "TC-500"),))
    text = (OA_FIXTURES / "gate-a-answers" / "cmp2-TC_014.md").read_text(encoding="utf-8")
    text = text.replace("TP1-15045_TC_014", "TC-500").replace("updated: 2026-10-01", f"updated: {date}")
    oracles = oa_oracles() if oracles == "default" else oracles
    qthens = OA_QTHENS if qthens == "default" else qthens
    lines = ""
    if raw_line is not None:
        lines += raw_line + "\n"
    elif oracles is not None:
        lines += "then_oracles: " + json.dumps(oracles) + "\n"
    if qthens is not None and raw_line is None:
        lines += "question_thens: " + json.dumps(qthens) + "\n"
    text = text.replace("status: Draft\n", "status: Draft\n" + lines, 1)
    (task / "work" / "test-cases" / "TC-500.md").write_text(text, encoding="utf-8")
    if register:
        (task / "work" / "requirements-readiness.json").write_text(oa_readiness(), encoding="utf-8")
    manifest_path = task / "work" / "automation-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["then_bindings"] = list(rows) if rows is not None else (
        [{"case": "TC-500", "then": n, "instance_id": OA_INSTANCE, "assertion_ref": OA_ASSERT, "status": "covered"} for n in bind]
        + list(extra))
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return task


def oa_unconfirmed(then: int, question: str = "Q4") -> dict:
    """The row `manifest_from_tests.py` writes for `qa_unresolved(then=[n], reason="expectation_unconfirmed", question=...)`."""
    return {"case": "TC-500", "then": then, "instance_id": None, "assertion_ref": None, "status": "unresolved",
            "reason": "expectation_unconfirmed", "question": question, "observed": "403"}


def oa_fired(task: Path) -> list:
    return [f for f in P.run(task)["findings"] if _tag(f).startswith(OA_TAG)]


def _tag(finding: dict) -> str:
    return finding["id"].split(":", 2)[2]


def oa_answer(task: Path, letter: str = "a", question: str = "Q4", words: str = "") -> None:
    import question_register as QR
    row = {q["id"]: q for q in QR.load(task)["questions"]}[question]
    QR.record(task, question, "answered", words or f"{question}: {letter}", "gate A", "driver", row["row_hash"],
              **({"reading": letter} if letter else {}))


def the_open_oracle_gate_is_never_judged() -> None:
    """M6: the tag is outside the judge's reach, by the plan and through `passed_by_judge` with a judge that passes everything."""
    import judge
    root = temp_project("qa-s5-oa-judge-")
    saved = (judge.settings, judge.active, judge.judged_refusal)
    try:
        task = filter_story(root)
        parsed, _problem = P.read_python(root / "tests" / "test_filter_mod.py")
        finding = P._finding("oracle", "TC-500", "Then 2 of TC-500 ...", "fix", f"{OA_TAG}-2")
        check_eq("no judge plan for the gate's tag", P._judge_plan(finding, task, {"TC-500": [parsed]}, {"TC-500": CASE_MD}), None)
        judge.settings = lambda *_a, **_k: {"provider": "typesafe", "mode": "on"}
        judge.active = lambda *_a, **_k: True
        judge.judged_refusal = lambda *_a, **_k: {"passed": True, "note": "stub says it passes"}
        hints, notes = [], []
        kept = P.passed_by_judge(task, [finding], hints, notes, {"TC-500": [parsed]}, {"TC-500": CASE_MD})
        check_eq("a judge that passes everything leaves it standing, and makes no hint of it",
                 ([_tag(f) for f in kept], hints), ([f"{OA_TAG}-2"], []))
    finally:
        judge.settings, judge.active, judge.judged_refusal = saved
        cleanup(root)


def the_phrase_list_is_gone() -> None:
    """F-2 / FR-12: the four-phrase prose search is removed; a case heading `## Open oracle` with no `then_oracles` line is
    no oracle finding any more (the structural read replaces the phrase list)."""
    check("the phrase list and its reader are gone", not hasattr(P, "OPEN_ORACLE_RES") and not hasattr(P, "open_oracle_lines")
          and not hasattr(P, "check_oracle"))
    root = temp_project("qa-s5-oa-phrase-")
    try:
        task = filter_story(root)
        (task / "work" / "test-cases" / "TC-500.md").write_text(
            CASE_MD + "\n## Open oracle\nThe expected status is not fixed. [DEFERRED] NOT FIXED\n", encoding="utf-8")
        found = P.run(task)
        check_eq("no open-oracle finding from the prose", [_tag(f) for f in found["findings"] if _tag(f).startswith("open-oracle")], [])
    finally:
        cleanup(root)


def open_oracle_asserted_is_a_repair_with_a_door() -> None:
    """K-PAIR-RED / K-PAIR-GREEN / K-SETTLED / K-SPLIT / K-INVALID / K-NOT-IN-REGISTER / K-MISSING-STATE / K-LEGACY /
    K-NO-ASSERTREF / K-NULL-INSTANCE / K-DUP / zero Thens."""
    root = temp_project("qa-s5-oa-")
    try:
        task = oa_story(root)
        found = oa_fired(task)
        check_eq("K-PAIR-RED: exactly one finding, for Then 2, in the oracle family", [(f["check"], _tag(f)) for f in found],
                 [("oracle", f"{OA_TAG}-2")])
        if found:
            both = found[0]["message"] + " || " + found[0]["fix"]
            check_in("it names the Then and the instance", "Then 2 of TC-500", found[0]["message"])
            check_in("and the instance with its assertion line", f"{OA_INSTANCE} ({OA_ASSERT})", found[0]["message"])
            check_in("and why: the question is not answered", "the question is open", found[0]["message"])
            check_in("door A: the marker the automator writes", 'reason="expectation_unconfirmed", question="Q4"', found[0]["fix"])
            check_in("door A: a status range keeps its marker", "# oracle_unknown: Q4", found[0]["fix"])
            check_in("door A: the person settles it by answering, with the door's file form", "question_register.py --task QA-500 --answer Q4 --reading <letter>", found[0]["fix"])
            check_in("door A: and says no waiver passes it", "no waiver passes this finding", found[0]["fix"])
            check_not_in("no door names triage.json: the automator cannot write it (FR-2)", "triage.json", both)
        # K-DOORA: the marker the fix prints parses as the marker `manifest_from_tests.py` reads, and the row it writes is clean
        import ast
        import manifest_from_tests as MFT
        marker = re.search(r"@(pytest\.mark\.qa_unresolved\(.*?<what the test saw>\))", found[0]["fix"]).group(1) if found else ""
        node = ast.parse("@" + marker.replace("<what the test saw>", '"403"') + "\ndef test_x(): pass").body[0].decorator_list[0]
        mark, kwargs = MFT._marker(node, "tests/t.py:1 test_x")[:2]
        check_eq("K-DOORA: the printed marker is a qa_unresolved marker with the gate's reason, question and Then",
                 (mark, kwargs.get("reason"), kwargs.get("question"), kwargs.get("then")),
                 (MFT.MARK_UNRESOLVED, "expectation_unconfirmed", "Q4", [2]))

        # t-707 m-2: the answer is given after S5, in the chat; traceability marks "answered at gate A" exactly when
        # where == ANSWERED_WHERE, so door A must not print that word
        import traceability as TR
        where = re.search(r"--where (\S+)", found[0]["fix"]).group(1) if found else ""
        check_eq("K-DOORA-WHERE: the printed --where is the chat's `conductor`", where, "conductor")
        check("K-DOORA-WHERE: and it is not the word traceability reports as 'answered at gate A'", where != TR.ANSWERED_WHERE)

        # t-707 m-3: the lifecycle line (and its automator slice) routes `invalid` back to S4; the Lead NAMES the raise of
        # this line's cap from 200 B to 300 B (the plan critic's m1-1 clause made it longer)
        for rel in ("references/execution-lifecycle.md", "references/slices/qa-automator/execution-lifecycle.md"):
            lines = [ln for ln in (Path(P.__file__).resolve().parent.parent / rel).read_text(encoding="utf-8").splitlines()
                     if ln.startswith("S5 exit `open-oracle-asserted`")]
            check_eq(f"K-DOC {rel}: one line", len(lines), 1)
            if lines:
                check_in(f"K-DOC {rel}: invalid goes back to S4", "`invalid` or no register question: back to S4", lines[0])
                check_not_in(f"K-DOC {rel}: no qa_unresolved route for invalid", "`open` or `invalid`", lines[0])
                check(f"K-DOC {rel}: within the named cap 300 B", len(lines[0].encode("utf-8")) <= 300)

        task = oa_story(root, bind=(), extra=(oa_unconfirmed(2),))
        check_eq("K-PAIR-GREEN: Then 2 bound only by the expectation_unconfirmed row is clean", oa_fired(task), [])
        task = oa_story(root, bind=(2,), extra=(oa_unconfirmed(2),))
        check_eq("K-SPLIT: a covered row BESIDE the unconfirmed row of the same Then is clean (F-1, Then-level)", oa_fired(task), [])
        task = oa_story(root, bind=(2, 3))
        check_eq("two Thens bound the same way: one finding each", [_tag(f) for f in oa_fired(task)], [f"{OA_TAG}-2", f"{OA_TAG}-3"])
        task = oa_story(root, bind=(2, 3), extra=(oa_unconfirmed(2),))
        check_eq("the unconfirmed row of Then 2 does not clear Then 3 (the exclusion is per Then)", [_tag(f) for f in oa_fired(task)], [f"{OA_TAG}-3"])

        task = oa_story(root)
        oa_answer(task, "a")
        check_eq("K-SETTLED: an answered question (a reading letter) settles Then 2: clean", oa_fired(task), [])

        task = oa_story(root, oracles=oa_oracles(two=("code", "x")))
        found = oa_fired(task)
        check_eq("K-INVALID: `code` is not an oracle word: a finding", [_tag(f) for f in found], [f"{OA_TAG}-2"])
        check_in("K-INVALID: it says so", "`code` (x) is not an oracle word", found[0]["message"])
        check_in("K-INVALID: door B is the one route - back to S4", "goes back to S4", found[0]["fix"])
        check_not_in("K-INVALID: and not door A", "qa_unresolved", found[0]["fix"])
        task = oa_story(root, oracles=oa_oracles(two=("unknown", "Q9")))
        found = oa_fired(task)
        check_eq("K-NOT-IN-REGISTER: a ref the register does not hold: a finding", [_tag(f) for f in found], [f"{OA_TAG}-2"])
        check_in("K-NOT-IN-REGISTER: door B", "goes back to S4", found[0]["fix"])
        check_not_in("K-NOT-IN-REGISTER: not door A (the marker would be refused: the question is not in the register)", "qa_unresolved", found[0]["fix"])
        task = oa_story(root, register=False)
        found = oa_fired(task)
        check_eq("K-NOT-IN-REGISTER: no register file at all: still a finding (the firing direction)", [_tag(f) for f in found], [f"{OA_TAG}-2"])
        check_in("and door B (door A is refused by manifest_from_tests.py without the register)", "goes back to S4", found[0]["fix"])

        task = oa_story(root, oracles=[e for e in oa_oracles() if e["then"] != 2])
        found = oa_fired(task)
        check_eq("K-MISSING-STATE: a then_oracles line with no entry for Then 2: a finding", [_tag(f) for f in found], [f"{OA_TAG}-2"])
        check_in("K-MISSING-STATE: it names what could not be read", "has no entry for Then 2", found[0]["message"])
        check_in("K-MISSING-STATE: door B", "goes back to S4", found[0]["fix"])
        task = oa_story(root, raw_line="then_oracles: [broken", bind=(2, 3))
        found = oa_fired(task)
        check_eq("K-MISSING-STATE: an unreadable line: a finding for EVERY asserted Then", [_tag(f) for f in found],
                 [f"{OA_TAG}-2", f"{OA_TAG}-3"])
        check_in("K-MISSING-STATE: and the parse problem is in the message", "not valid JSON on ONE line", found[0]["message"])

        task = oa_story(root, oracles=None, qthens=None, date="2026-10-01")
        result = P.run(task)
        check_eq("K-LEGACY: no then_oracles line (a legacy case): no finding of this gate",
                 [_tag(f) for f in result["findings"] if _tag(f).startswith(OA_TAG)], [])
        check_in("K-LEGACY: and one note says the check read nothing", "TC-500: no then_oracles line; the open-oracle check had no oracle to read",
                 "\n".join(result["notes"]))

        task = oa_story(root, rows=[{"case": "TC-500", "then": 2, "instance_id": OA_INSTANCE, "status": "covered"}])
        found = oa_fired(task)
        check_eq("K-NO-ASSERTREF: a covered row with an instance and no assertion_ref still fires (F-4)", [_tag(f) for f in found], [f"{OA_TAG}-2"])
        check_in("K-NO-ASSERTREF: the message says the line is not named", "assertion line not named", found[0]["message"])
        task = oa_story(root, rows=[{"case": "TC-500", "then": 2, "instance_id": OA_INSTANCE, "assertion_ref": OA_ASSERT}])
        check_eq("M8: a row with no `status` at all reads covered (the check's own default) and fires", len(oa_fired(task)), 1)
        task = oa_story(root, rows=[{"case": "TC-500", "then": 2, "instance_id": None, "assertion_ref": None, "status": "covered"}])
        check_eq("K-NULL-INSTANCE: a covered row with instance_id null: this gate is silent (`bindings` owns unbound)", oa_fired(task), [])
        task = oa_story(root, rows=[{"case": "TC-500", "then": 2, "instance_id": OA_INSTANCE, "assertion_ref": OA_ASSERT, "status": "unresolved",
                                     "reason": "impossible"}])
        check_eq("an `unresolved` row is no proof: silent", oa_fired(task), [])
        task = oa_story(root, bind=())
        check_eq("a Then with no bound instance at all is silent", oa_fired(task), [])

        both_orders = (oa_oracles()[:1] + [oa_entry(2, "requirement", "R-16"), oa_entry(2, "unknown", "Q4")],
                       oa_oracles()[:1] + [oa_entry(2, "unknown", "Q4"), oa_entry(2, "requirement", "R-16")])
        for label, entries in zip(("settled first", "open first"), both_orders):
            check_eq(f"K-DUP: two entries for Then 2, {label}: the non-settled one wins and fires",
                     [_tag(f) for f in oa_fired(oa_story(root, oracles=entries))], [f"{OA_TAG}-2"])

        text_no_then = (task / "work" / "test-cases" / "TC-500.md").read_text(encoding="utf-8")
        (task / "work" / "test-cases" / "TC-500.md").write_text(text_no_then.split("## Then")[0], encoding="utf-8")
        zero = P.run(task)
        check_eq("a case with no Then section: no finding of this gate and no note of it",
                 ([f for f in zero["findings"] if _tag(f).startswith(OA_TAG)], [n for n in zero["notes"] if "then_oracles line" in n]), ([], []))
    finally:
        cleanup(root)


def open_oracle_asserted_errs_toward_firing() -> None:
    """K-ADVERSARIAL: every input the resolver reads `open`/`invalid` fires; every sourced Then stays silent."""
    import question_register as QR
    root = temp_project("qa-s5-oa-adv-")
    try:
        def fires(label: str, task: Path) -> None:
            check_eq(f"K-ADVERSARIAL fires: {label}", [_tag(f) for f in oa_fired(task)], [f"{OA_TAG}-2"])
        task = oa_story(root)
        oa_answer(task, "")
        fires("answered in the person's own wording (no reading letter)", task)
        task = oa_story(root)
        oa_answer(task, "a")
        path = task / "work" / "requirements-readiness.json"
        path.write_text(path.read_text(encoding="utf-8").replace('"severity": "major"', '"severity": "critical"', 1), encoding="utf-8")
        check("(control) the row did change after the answer", {q["id"]: q for q in QR.load(task)["questions"]}["Q4"]["changed_since_answer"] is True)
        fires("answered, then the readiness row edited (changed_since_answer)", task)
        task = oa_story(root, qthens=[{"question": "Q4", "then": 2, "readings": {"b": "401 Unauthorized"}, "not_needed": ""}])
        oa_answer(task, "a")
        fires("a reading letter question_thens has no text for", task)
        fires("(source 'Unknown', capitalised)", oa_story(root, oracles=oa_oracles(two=("Unknown", "Q4"))))
        fires("source ' unknown ' (stripped: open)", oa_story(root, oracles=oa_oracles(two=(" unknown ", "Q4"))))
        fires("ref '' (no question named)", oa_story(root, oracles=oa_oracles(two=("unknown", ""))))
        fires("`then` written as the string '2' (maps to Then 2 through C.then_number)",
              oa_story(root, oracles=[dict(e, then=str(e["then"])) if e["then"] == 2 else e for e in oa_oracles()]))
        # a before/now question answered with the regression reading while `before` is unknown (before_value_needed)
        task = oa_story(root, oracles=oa_oracles(two=("unknown", "Q7")),
                        qthens=[{"question": "Q7", "then": 2, "readings": {"a": "HTTP 400", "b": ""}, "not_needed": ""}])
        oa_answer(task, "b", "Q7")
        fires("the regression reading on a before/now question whose `before` is unknown", task)
        for source, ref in (("requirement", "R-16"), ("ac", "R-16"), ("spec", "R-16"), ("precedent", "base:b9c0c4e:w.py:989"),
                            ("person", "Q4")):
            check_eq(f"K-ADVERSARIAL silent: source {source} (a settled Then is never refused)",
                     oa_fired(oa_story(root, oracles=oa_oracles(two=(source, ref)))), [])
    finally:
        cleanup(root)


def no_word_passes_the_open_oracle_gate() -> None:
    """K-WORD / M5: a stage-wide word (`*`), a word naming the tag and a word naming the family all leave the finding; `report()`
    prints its WORDS_REFUSED_AT_SOURCE line (cause `family`)."""
    import waiver as W
    root = temp_project("qa-s5-oa-word-")
    try:
        task = oa_story(root)
        finding_id = oa_fired(task)[0]["id"]
        for label, match in (("`*`", "*"), ("the tag", OA_TAG), ("the whole finding id", finding_id), ("the family", "oracle")):
            pipeline = {"task": "QA-500"}
            W.apply_stage_override(pipeline, "S5", match, "the person said so", W.now_iso())
            (task / "pipeline.json").write_text(json.dumps(pipeline), encoding="utf-8")
            check_eq(f"a word naming {label} does not pass it", [f["id"] for f in oa_fired(task)], [finding_id])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            P.report(P.run(task))
        check_in("report() prints the finding's refusal line, cause family", f"WORDS_REFUSED_AT_SOURCE: {finding_id} family", out.getvalue())
    finally:
        cleanup(root)


def a_test_written_to_the_owners_norm_is_not_refused() -> None:
    """The critic's F-1-norm walk-through (t-652 Q1, shape A): the refusal split into TWO Thens - Then 2 the 4xx range with the SAME
    account's allowed call (its requirement is the oracle), Then 3 the exact code, `unknown` with Q4, bound `expectation_unconfirmed` -
    is not refused by this gate. The test asserts `400 <= status < 500  # oracle_unknown: Q4` and a positive call by the same actor."""
    root = temp_project("qa-s5-oa-norm-")
    try:
        oracles = [oa_entry(1, "requirement", "R-16"), oa_entry(2, "requirement", "R-16"), oa_entry(3, "unknown", "Q4"),
                   oa_entry(4, "requirement", "R-16"), oa_entry(5, "requirement", "R-16")]
        qthens = [{"question": "Q4", "then": 3, "readings": {"a": "403 Forbidden", "b": "401 Unauthorized"}, "not_needed": ""}]
        task = oa_story(root, oracles=oracles, qthens=qthens, bind=(2,), extra=(oa_unconfirmed(3),))
        (root / "tests" / "test_filter_mod.py").write_text(
            OA_PY.replace("    assert r.status_code == 403\n",
                          '    assert call(READONLY_TOKEN, "GET", "/v1/workflows/w") == 200\n'
                          "    assert 400 <= r.status_code < 500  # oracle_unknown: Q4\n"), encoding="utf-8")
        result = P.run(task)
        check_eq("shape A (split Thens): no open-oracle-asserted finding",
                 [_tag(f) for f in result["findings"] if _tag(f).startswith(OA_TAG)], [])
        mixed = oa_story(root, bind=(2,))
        check_eq("shape B (ONE mixed `unknown` Then bound covered, no unconfirmed row) IS refused - the split is what the norm asks for",
                 [_tag(f) for f in oa_fired(mixed)], [f"{OA_TAG}-2"])
    finally:
        cleanup(root)


def a_measurement_error_is_unmeasured_not_a_crash() -> None:
    root = temp_project("qa-s5-crash-")
    try:
        task = filter_story(root)
        cmp1_shape(task)
        (task / "work" / "run-blocks" / "20260930T050000000000Z-broken.json").write_text(
            "{this is not json", encoding="utf-8")
        (task / "work" / "run-blocks" / "20260930T050100000000Z-list.json").write_text("[1, 2]", encoding="utf-8")
        (task / "work" / "run-blocks" / "20260930T050200000000Z-odd.json").write_text(
            json.dumps({"results": "not a list", "evidence": "nor this"}), encoding="utf-8")
        result = P.run(task)
        got = result["expectation_changes"]
        check_eq("a corrupt block does not hide the pair the other blocks show",
                 [p["function"] for p in got["pairs"]], [KEY])
        check("but it is named: what is unmeasured says which files were not read",
              any("broken.json" in u for u in got["unmeasured"]) and any("list.json" in u for u in got["unmeasured"]),
              str(got["unmeasured"]))
        check_in("and a note carries it to the person reading the run", "expectation changes not measured",
                 "\n".join(result["notes"]))
        check("the other checks still report", len(result["findings"]) > len(car(result)))

        # an exception inside the measurement: R1a - unmeasured, and the rest of run() goes on
        # the detector moved to run_history.py (F5): the name it calls lives there now
        import run_history as RH
        saved = RH._function_identity

        def boom(*_a, **_k):
            raise RuntimeError("boom")
        RH._function_identity = boom
        try:
            crashed = P.run(task)
        finally:
            RH._function_identity = saved
        got = crashed["expectation_changes"]
        check_eq("a crash inside expectation_changes: no pairs, one unmeasured entry naming it",
                 (got["pairs"], len(got["unmeasured"]), "RuntimeError" in got["unmeasured"][0]), ([], 1, True))
        check("and the rest of run() goes on: the bindings check still reports",
              any(f["check"] == "bindings" for f in crashed["findings"]))
        check_eq("the detector says nothing about a pair it could not compute: no finding",
                 car(crashed), [])
    finally:
        cleanup(root)


def the_fragment_battery() -> None:
    """E16: what manifest_put takes and refuses for `expectation_changes`."""
    problems = M.expectation_change_problems
    good = {"function": KEY, "red_attempt": A1, "green_attempt": A4,
            "then_refs": [{"case": "TC-500", "then": 2}], "what_changed": "w", "reason": "r"}
    check_eq("an empty list is a no-op", problems([]), [])
    check_eq("an absent key is no problem", problems(None), [])
    check_eq("a well formed row is accepted", problems([good]), [])
    check_eq("a null green attempt (the test was renamed or deleted) is accepted",
             problems([dict(good, green_attempt=None)]), [])
    check_eq("the several-functions form is accepted",
             problems([{k: v for k, v in dict(good, functions=[KEY, KEY_B]).items() if k != "function"}]), [])
    for field in ("function", "red_attempt", "green_attempt"):
        row = {k: v for k, v in good.items() if k != field}
        got = problems([row])
        check(f"a row missing `{field}` is refused, naming it", len(got) == 1 and field in got[0], str(got))
    for label, row, wanted in (
            ("then_refs empty", dict(good, then_refs=[]), "then_refs"),
            ("then_refs not a list", dict(good, then_refs="TC-500#2"), "then_refs"),
            ("then_refs of strings, not objects", dict(good, then_refs=["TC-500"]), "then_refs"),
            ("then as a string", dict(good, then_refs=[{"case": "TC-500", "then": "2"}]), "`then` must be an integer"),
            ("then as a bool", dict(good, then_refs=[{"case": "TC-500", "then": True}]), "`then` must be an integer"),
            ("an unknown verdict", dict(good, critic_verdict="fine"), "legitimate_correction"),
            ("an object where a string is wanted", dict(good, reason={"text": "r"}), "`reason` must be a non-empty string"),
            ("an object as the function", dict(good, function={"a": 1}), "`function` must be a non-empty string"),
            ("an empty reason", dict(good, reason="  "), "`reason`"),
            ("a list of numbers as functions", {**{k: v for k, v in good.items() if k != "function"},
                                                "functions": [1, 2]}, "`functions`")):
        got = problems([row])
        check(f"refused: {label}", bool(got) and wanted in " ".join(got), str(got))
    check("the refusal lists the verdict words it expects",
          all(word in " ".join(problems([dict(good, critic_verdict="x")]))
              for word in ("legitimate_correction", "fitted_to_code", "could_not_judge")))
    check_eq("a patch onto an existing key may carry a subset (the critic's verdict alone)",
             problems([{"function": KEY, "red_attempt": A1, "green_attempt": A4,
                        "critic_verdict": "fitted_to_code"}], existing=[good]), [])
    check_eq("but a NEW key must carry the author's fields",
             len(problems([{"function": KEY, "red_attempt": A1, "green_attempt": A4}])), 3)
    # F6: a VERDICT for a key no record holds is one refusal that names the key and the records
    # that exist, not three complaints about fields the critic does not write
    got = problems([{"function": KEY, "red_attempt": A1, "green_attempt": A4, "critic_verdict": "fitted_to_code"}])
    check("a verdict for a key no record holds: ONE refusal, naming the key and saying none exists",
          len(got) == 1 and KEY in got[0] and A1 in got[0] and A4 in got[0]
          and "no expectation_changes[] record yet" in got[0], str(got))
    check_eq("a fragment that is not a list is refused", len(problems({"function": KEY})), 1)

    kb = "x" * 10240
    tokens = "café → ≥ 5 ± 日本語"
    merged, summary = M.merge({}, {"expectation_changes": [dict(good, reason=kb), dict(good, reason=kb)]})
    check_eq("a duplicate row inside one fragment is de-duplicated", (len(merged["expectation_changes"]),
                                                                       summary.get("duplicate")), (1, 1))
    check_eq("a 10 KB reason is kept whole", len(merged["expectation_changes"][0]["reason"]), 10240)
    check_eq("an empty list changes nothing and creates no key", M.merge({}, {"expectation_changes": []})[0], {})
    check_eq("the merge key ignores the order of the functions",
             M.merge(M.merge({}, {"expectation_changes": [dict({k: v for k, v in good.items() if k != "function"},
                                                               functions=[KEY, KEY_B])]})[0],
                     {"expectation_changes": [{"functions": [KEY_B, KEY], "red_attempt": A1, "green_attempt": A4,
                                               "critic_verdict": "could_not_judge"}]})[0]["expectation_changes"][0]["critic_verdict"],
             "could_not_judge")

    root = temp_project("qa-s5-frag-")
    try:
        task = filter_story(root)
        before = manifest_of(task)
        refused = put(root, "QA-500", {"expectation_changes": [dict(good, then_refs=[])]})
        check_eq("end to end: a malformed row is refused with the bad-fragment exit", refused.returncode, 3)
        check_in("the refusal names the field and what it expected", "`then_refs` must be a non-empty list",
                 refused.stderr)
        check_in("and says it is a repair, with the person's door", 'changed-after-red', refused.stderr)
        check_eq("and nothing was written", manifest_of(task), before)
        noop = put(root, "QA-500", {"expectation_changes": []})
        check_eq("an empty list is accepted", noop.returncode, 0)
        check("and writes no record key", "expectation_changes" not in manifest_of(task))
        wrote = put(root, "QA-500", {"expectation_changes": [dict(good, reason=kb + tokens)]})
        check_eq("a 10 KB reason with non-ASCII text is accepted", wrote.returncode, 0)
        raw_bytes = (task / "work" / "automation-manifest.json").read_bytes().decode("utf-8")
        check("and the non-ASCII text round-trips byte for byte, not escaped", tokens in raw_bytes)
        check_eq("the reason read back is what was sent", manifest_of(task)["expectation_changes"][0]["reason"],
                 kb + tokens)
        again = put(root, "QA-500", {"expectation_changes": [dict(good, reason=kb + tokens), good]})
        check_eq("the same key twice: accepted", again.returncode, 0)
        check_eq("and one row: the later fields win, nothing is doubled",
                 [r["reason"] for r in manifest_of(task)["expectation_changes"]], ["r"])
    finally:
        cleanup(root)


# --- t-149 (critic's verdict on B-194 pieces A, B, D): F1 ... F8 ---------------------------------

def cli(root: Path, *args, stdin=None) -> "subprocess.CompletedProcess":
    """manifest_put.py as a subprocess, argv exactly as given (no shell)."""
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(root), "PYTHONDONTWRITEBYTECODE": "1"}
    return subprocess.run([sys.executable, "-B", str(Path(__file__).resolve().parents[1] / "manifest_put.py"),
                           *[str(a) for a in args]], capture_output=True, text=True, encoding="utf-8",
                          cwd=str(root), env=env, input=stdin, timeout=300)


def the_printed_door_runs() -> None:
    """F1: the command the finding prints, placeholders filled, run as an argv list."""
    import shlex
    root = temp_project("qa-s5-door-")
    try:
        task = filter_story(root)
        cmp1_shape(task)
        finding = car(P.run(task))[0]
        printed = re.search(r"`(manifest_put\.py --task [^`]*)`", finding["fix"]).group(1)
        filled = (printed.replace('"<the Then number>"', "1")
                  .replace("<what you changed in the test, before -> after>", "400 -> 422")
                  .replace("<why the approved case allows it>", "the case leaves the status open"))
        argv = shlex.split(filled)
        check_eq("the printed command is manifest_put.py --task T --fragment <inline JSON>",
                 (argv[0], argv[1], argv[3], argv[4][:1]), ("manifest_put.py", "--task", "--fragment", "{"))
        check("no placeholder is left in it", "<" not in filled, filled)
        done = cli(root, *argv[1:])
        check_eq("F1: the exact printed command exits 0 (it was FileNotFoundError, exit 3)", done.returncode, 0)
        check_not_in("and no traceback or FileNotFoundError", "FileNotFoundError", done.stderr)
        check_eq("the record is in the manifest", [r["what_changed"] for r in
                                                   manifest_of(task).get("expectation_changes", [])], ["400 -> 422"])
        after = P.run(task)
        check_eq("the finding is gone", car(after), [])
        check_in("and it is the 'recorded, not judged yet' note", "recorded in expectation_changes[], not judged yet",
                 "\n".join(after["notes"]))

        bad = cli(root, "--task", "QA-500", "--fragment", '{"expectation_changes": [}')
        check_eq("inline JSON that does not parse: exit 3", bad.returncode, 3)
        check_in("and says it is not valid JSON", "not valid JSON", bad.stderr)
        check_not_in("not a FileNotFoundError", "FileNotFoundError", bad.stderr)
        (root / "{frag.json").write_text(json.dumps({"run_witness": "from-a-file.json"}), encoding="utf-8")
        before = manifest_of(task)
        never = cli(root, "--task", "QA-500", "--fragment", "{frag.json")
        check_eq("an argument that starts with { is never tried as a path, even when such a file exists",
                 (never.returncode, "not valid JSON" in never.stderr, manifest_of(task)), (3, True, before))
        spaced = cli(root, "--task", "QA-500", "--fragment", '  {"run_witness": "inline.json"}  ')
        check_eq("leading and trailing blanks around the inline JSON are fine",
                 (spaced.returncode, manifest_of(task).get("run_witness")), (0, "inline.json"))
        piped = cli(root, "--task", "QA-500", "--fragment", "-", stdin=json.dumps({"run_witness": "stdin.json"}))
        check_eq("stdin still works", (piped.returncode, manifest_of(task).get("run_witness")), (0, "stdin.json"))
        viafile = put(root, "QA-500", {"run_witness": "file.json"})
        check_eq("and so does a path", (viafile.returncode, manifest_of(task).get("run_witness")), (0, "file.json"))
        empty = cli(root, "--task", "QA-500", "--fragment", "{}")
        check_eq("an empty inline object carries nothing: refused, naming the inline fragment",
                 (empty.returncode != 0, "the inline fragment carries no manifest keys" in empty.stderr), (True, True))
    finally:
        cleanup(root)


def a_word_for_another_finding_does_not_pass_it() -> None:
    """F2: `split_overridden` matches by substring over id + message + fix; a finding passable by
    tag takes only a word that names the tag (or `*`)."""
    import waiver as W
    root = temp_project("qa-s5-word2-")
    try:
        task = filter_story(root)
        cmp1_shape(task)
        finding_id = car(P.run(task))[0]["id"]

        def words(*matches) -> list:
            pipeline = {"task": "QA-500"}
            for match in matches:
                W.apply_stage_override(pipeline, "S5", match, "the person said so", W.now_iso())
            (task / "pipeline.json").write_text(json.dumps(pipeline), encoding="utf-8")
            return car(P.run(task))
        for label, match in (("the case id", "TC-500"), ("the ticket id (it is in the fix text)", "QA-500"),
                             ("the family", "oracle"), ("the function key alone", KEY),
                             ("the script name (it is in the fix text)", "manifest_put.py")):
            check_eq(f"F2: a word naming {label} does not pass it", len(words(match)), 1)
        for label, match in (("`*`", "*"), ("the tag", "changed-after-red"), ("the tag in capitals", "CHANGED-AFTER-RED"),
                             ("the whole finding id", finding_id)):
            check_eq(f"F2: a word naming {label} passes it", words(match), [])
        check_eq("a word for another finding beside a word for the tag: passed (the tag's word counts)",
                 words("TC-500", "changed-after-red"), [])
        check_eq("and the other word alone still passes nothing", len(words("TC-500", "oracle")), 1)
    finally:
        cleanup(root)


def the_detector_lives_in_run_history() -> None:
    """F5: both import paths name the same objects, and the new module stands on its own."""
    import run_history as RH
    for name in ("read_run_blocks", "function_key", "expectation_changes", "expectation_records",
                 "record_functions", "record_for"):
        check(f"F5: s5_precheck.{name} is run_history.{name}", getattr(P, name) is getattr(RH, name))
    scripts = str(Path(__file__).resolve().parents[1])
    work = temp_dir("qa-s5-rh-")
    try:
        out = subprocess.run([sys.executable, "-B", "-c",
                              "import sys; sys.path.insert(0, sys.argv[1]); import run_history as R; "
                              "print(R.expectation_changes(sys.argv[2], [], {}))", scripts, str(work)],
                             capture_output=True, text=True, encoding="utf-8", timeout=120)
        check_eq("run_history imports before s5_precheck does (no circular import at the top) and "
                 "answers for a story with no run block", (out.returncode, out.stdout.strip()),
                 (0, "{'pairs': [], 'unmeasured': [], 'unmeasured_tool': []}"))
    finally:
        cleanup(work)


def param_run(task: Path, attempt: str, minute: int, outcome: str, param: str, sha: str,
              fn: str = FN, case: str = "TC-500", bare: bool = False) -> None:
    """One attempt that ran ONE parameter of a function, with its own junit."""
    row = brow(fn, param, outcome, "tests", case, instance_code_sha=sha)
    if bare:
        row["test_id"] = ""
    write_block(task, f"20260930T05{minute:02d}00000000Z-{attempt}.json", attempt,
                f"2026-09-30T05:{minute:02d}:00+00:00", "passed" if outcome == "passed" else "failed",
                [row], junit(task, attempt, [(fn, param, outcome)]))


def the_three_silent_passes_are_owed_pairs() -> None:
    root = temp_project("qa-s5-silent-")
    try:
        def pairs_of(ticket: str, *runs, **kwargs) -> list:
            task = filter_story(root, ticket=ticket)
            for run in runs:
                param_run(task, *run, **kwargs) if isinstance(run, tuple) else run(task)
            return changes_of(task)["pairs"]

        # F3a: a bare key (a row with no reporter id) and the qualified key of the same test
        got = pairs_of("QA-610", ("r1", 0, "failed", "P-new", "X", FN, "TC-500", True), ("g1", 10, "passed", "P-new", "Y"))
        check_eq("F3a: red with an EMPTY test_id, green with one: ONE pair, under the qualified key",
                 [(p["function"], p["red_attempt"], p["green_attempt"], p["red_basis"]) for p in got],
                 [(KEY, "r1", "g1", "report")])
        got = pairs_of("QA-611", ("r1", 0, "failed", "P-new", "X"), ("g1", 10, "passed", "P-new", "Y", FN, "TC-500", True))
        check_eq("F3a: red with a test_id, green with an empty one: ONE pair",
                 [(p["function"], p["red_attempt"], p["green_attempt"]) for p in got], [(KEY, "r1", "g1")])
        got = pairs_of("QA-612", ("r1", 0, "failed", "P-new", "X", FN, "TC-500", True), ("g1", 10, "passed", "P-new", "X"))
        check_eq("F3a: the same bytes under the two spellings: still no pair", got, [])
        got = pairs_of("QA-613", ("r1", 0, "failed", "P-new", "X", FN, "TC-500", True),
                       ("g1", 10, "passed", "P-new", "Y", FN, "TC-500", True))
        check_eq("F3a: a bare key with no qualified twin stays alone, as before (one pair, bare key)",
                 [p["function"] for p in got], [FN])

        # F3b: a pass of ANOTHER parameter does not clear the red parameter
        got = pairs_of("QA-620", ("r1", 0, "failed", "P1", "X"), ("p2", 5, "passed", "P2", "Z"),
                       ("g1", 10, "passed", "P1", "Y"))
        check_eq("F3b: P1 red on X, P2 alone passes, P1 passes on Y: ONE pair, r1 -> g1",
                 [(p["red_attempt"], p["green_attempt"], p["red_sha"], p["green_sha"]) for p in got],
                 [("r1", "g1", "X", "Y")])
        check_eq("F3b: and the pass in between is listed as intermediate", [p["intermediate_shas"] for p in got], [["Z"]])
        got = pairs_of("QA-626", ("r1", 0, "failed", "P1", "X"), ("p2", 5, "passed", "P2", "X"),
                       ("g1", 10, "passed", "P1", "Y"))
        check_eq("F3b (the critic's exact shape): P1 red on X, P2 ALONE passes on the SAME bytes X, P1 passes "
                 "on changed bytes Y: ONE pair, r1 -> g1 (the pass of P2 cleared the red and hid the change)",
                 [(p["red_attempt"], p["green_attempt"], p["red_sha"], p["green_sha"]) for p in got],
                 [("r1", "g1", "X", "Y")])
        got = pairs_of("QA-621", ("r1", 0, "failed", "P1", "X"), ("g1", 10, "passed", "P1", "X"))
        check_eq("F3b: a pass of the SAME parameter on the same bytes clears the red: no pair", got, [])
        got = pairs_of("QA-622", ("r1", 0, "failed", "P1", "X"), ("g1", 10, "passed", "P1", "Y"))
        check_eq("F3b: the same parameter on changed bytes: one pair", [(p["red_attempt"], p["green_attempt"]) for p in got],
                 [("r1", "g1")])
        got = pairs_of("QA-623", ("r1", 0, "failed", "P1", "X"), ("g1", 10, "passed", "P-renamed", "Y"))
        check_eq("F3b: a parameter renamed and never seen again is retired, so the pass of its new name "
                 "clears it (the cmp1 shape)", [(p["red_attempt"], p["green_attempt"]) for p in got], [("r1", "g1")])
        got = pairs_of("QA-624", ("r1", 0, "failed", "P1", "X"), ("p2", 5, "passed", "P2", "X"))
        check_eq("F3b: P2 passes on the same bytes and P1 is never run again: nothing changed, no pair", got, [])
        got = pairs_of("QA-625", ("r1", 0, "failed", "P1", "X"), ("p2", 5, "passed", "P2", "Z"),
                       ("p1", 7, "failed", "P1", "W"), ("g1", 10, "passed", "P1", "Y"))
        check_eq("F3b: red, another parameter passes, red again, green: one pair from the first red",
                 [(p["red_attempt"], p["green_attempt"], p["intermediate_shas"]) for p in got],
                 [("r1", "g1", ["Z", "W"])])

        # F3c: the row says failed, the report is readable and does not name the function
        def other_function_named(ticket: str, row: dict) -> list:
            task = filter_story(root, ticket=ticket)
            write_block(task, "20260930T050000000000Z-r1.json", "r1", "2026-09-30T05:00:00+00:00", "failed",
                        [{**row, "instance_code_sha": "X"}], junit(task, "r1", [(FN_B, "P-new", "passed")]))
            one_run(task, "g1", 10, "passed", {"instance_code_sha": "Y"})
            return changes_of(task)["pairs"]
        got = other_function_named("QA-630", brow(FN, "P-new", "failed", "tests", "TC-500"))
        check_eq("F3c: a `failed` row the readable report does not name is the row's own word",
                 [(p["red_status"], p["red_basis"]) for p in got], [("failed", "row")])
        got = other_function_named("QA-631", unmapped(FN, "P-new", "pkg_h.tests", "TC-500"))
        check_eq("F3c: an unmapped row of a failed block the report does not name: red_unconfirmed",
                 [(p["red_status"], p["red_basis"]) for p in got], [("red_unconfirmed", "unconfirmed")])
        task = filter_story(root, ticket="QA-632")
        write_block(task, "20260930T050000000000Z-r1.json", "r1", "2026-09-30T05:00:00+00:00", "failed",
                    [brow(FN, "P-new", "failed", "tests", "TC-500", instance_code_sha="X")],
                    junit(task, "r1", [(FN, "P-new", "passed")]))
        one_run(task, "g1", 10, "passed", {"instance_code_sha": "Y"})
        check_eq("F3c vs R5a: when the report NAMES the function and it passed there, the report wins: no pair",
                 changes_of(task)["pairs"], [])
    finally:
        cleanup(root)


def a_long_path_is_not_an_unreadable_report() -> None:
    """F8: on Windows `resolve()` of a long path carries `\\\\?\\`; the other side does not."""
    plain, unc = RH_prefix("\\\\?\\C:\\work\\x.xml"), RH_prefix("\\\\?\\UNC\\host\\share\\x.xml")
    check_eq("F8: the extended prefix is stripped", str(plain), "C:\\work\\x.xml")
    check_eq("F8: and the UNC form becomes a UNC path", str(unc), "\\\\host\\share\\x.xml")
    check_eq("F8: a path without the prefix is returned as it is", str(RH_prefix("C:\\work\\x.xml")), "C:\\work\\x.xml")
    if os.name != "nt":
        check("F8: the end-to-end check needs Windows path semantics (skipped on this platform)", True)
        return
    root = temp_project("qa-s5-long-")
    saved = Path.resolve
    try:
        task = filter_story(root)
        cmp1_shape(task)

        def long_form(self, *args, **kwargs):
            got = saved(self, *args, **kwargs)
            text = str(got)
            return Path("\\\\?\\" + text) if got.is_file() and not text.startswith("\\\\?\\") else got
        Path.resolve = long_form
        try:
            pairs = changes_of(task)["pairs"]
        finally:
            Path.resolve = saved
        check_eq("F8: a report whose path resolves with the prefix is READ: cmp1 is still exactly one pair, "
                 "confirmed by the report (it was three, two of them red_unconfirmed)",
                 [(p["function"], p["red_basis"]) for p in pairs], [(KEY, "report")])
    finally:
        Path.resolve = saved
        cleanup(root)


def RH_prefix(text: str) -> Path:
    import run_history as RH
    return RH._without_extended_prefix(Path(text))


VERDICT_ROW = {"functions": [KEY, KEY_B], "red_attempt": "r1", "green_attempt": "g1",
               "then_refs": [{"case": "TC-500", "then": 1}], "what_changed": "400 -> 422",
               "reason": "the case leaves it open", "critic_verdict": "legitimate_correction",
               "critic_note": "read the case"}
VERDICT_KEY = {"functions": [KEY, KEY_B], "red_attempt": "r1", "green_attempt": "g1"}


def the_verdict_follows_the_authors_words() -> None:
    def patched(patch: dict, base: dict = VERDICT_ROW) -> tuple:
        merged, summary = M.merge({"expectation_changes": [dict(base)]}, {"expectation_changes": [patch]})
        return merged["expectation_changes"], summary
    for field, value in (("reason", "a different reason"), ("what_changed", "403 -> 422"),
                         ("then_refs", [{"case": "TC-500", "then": 2}])):
        rows, summary = patched({**VERDICT_KEY, field: value})
        check_eq(f"F4: a changed `{field}` drops the verdict and its note and keeps the author's new words",
                 (len(rows), rows[0].get("critic_verdict"), rows[0].get("critic_note"), rows[0][field]),
                 (1, None, None, value))
        check_eq("F4: and the merge says so (the record's functions)", summary.get("verdicts_dropped"),
                 [f"{KEY}, {KEY_B}"])
    rows, summary = patched({**VERDICT_KEY, "reason": VERDICT_ROW["reason"], "what_changed": "400 -> 422",
                             "critic_note": "a second reading"})
    check_eq("F4: a patch with IDENTICAL author fields keeps the verdict (and takes the new note)",
             (rows[0]["critic_verdict"], rows[0]["critic_note"], "verdicts_dropped" in summary),
             ("legitimate_correction", "a second reading", False))
    rows, summary = patched({**VERDICT_KEY, "reason": "new words", "critic_verdict": "fitted_to_code"})
    check_eq("F4: a patch that changes the words AND carries its own verdict: the patch's verdict stands",
             (rows[0]["critic_verdict"], rows[0]["reason"], "verdicts_dropped" in summary),
             ("fitted_to_code", "new words", False))
    rows, summary = patched({**VERDICT_KEY, "reason": "new words"},
                            base={k: v for k, v in VERDICT_ROW.items() if k not in ("critic_verdict", "critic_note")})
    check_eq("F4: a record with no verdict has nothing to drop", ("verdicts_dropped" in summary, rows[0]["reason"]),
             (False, "new words"))
    rows, summary = patched({**VERDICT_KEY, "reason": "new words"},
                            base={k: v for k, v in VERDICT_ROW.items() if k != "critic_verdict"})
    check_eq("F4: a note with no verdict beside it is not dropped", (rows[0].get("critic_note"), "verdicts_dropped" in summary),
             ("read the case", False))
    # F4 with F6: a critic's subset patch that carries only the verdict never drops anything
    rows, summary = patched({"function": KEY, "red_attempt": "r1", "green_attempt": "g1",
                             "critic_verdict": "fitted_to_code", "critic_note": "restore the value"})
    check_eq("F4+F6: a subset patch carrying only critic fields drops nothing", (
        rows[0]["critic_verdict"], rows[0]["critic_note"], rows[0]["reason"], "verdicts_dropped" in summary),
        ("fitted_to_code", "restore the value", "the case leaves it open", False))
    rows, summary = patched({"function": KEY, "red_attempt": "r1", "green_attempt": "g1", "reason": "x"})
    check_eq("F4+F6: a subset patch that changes the shared reason drops the record's verdict, and the "
             "record keeps all its functions", (rows[0].get("critic_verdict"), rows[0]["reason"], rows[0]["functions"]),
             (None, "x", [KEY, KEY_B]))

    # end to end: the line the author reads
    root = temp_project("qa-s5-drop-")
    try:
        task = filter_story(root)
        cmp1_shape(task)
        record = {"function": KEY, "red_attempt": A1, "green_attempt": A4, "then_refs": [{"case": "TC-500", "then": 1}],
                  "what_changed": "400 -> 422", "reason": "the case leaves it open"}
        check_eq("the record goes in", put(root, "QA-500", {"expectation_changes": [record]}).returncode, 0)
        verdict = {"expectation_changes": [{"function": KEY, "red_attempt": A1, "green_attempt": A4,
                                            "critic_verdict": "legitimate_correction", "critic_note": "ok"}]}
        done = put(root, "QA-500", verdict)
        check_eq("the critic's verdict goes in, and nothing is said about a drop",
                 (done.returncode, "was dropped" in done.stdout), (0, False))
        same = put(root, "QA-500", {"expectation_changes": [dict(record, critic_note="still ok")]})
        check_eq("the author re-sends the SAME words: the verdict stays",
                 (same.returncode, manifest_of(task)["expectation_changes"][0]["critic_verdict"], "was dropped" in same.stdout),
                 (0, "legitimate_correction", False))
        changed = put(root, "QA-500", {"expectation_changes": [dict(record, reason="another reason")]})
        lines = [l for l in changed.stdout.splitlines() if "was dropped" in l]
        check_eq("F4: the author changes the reason: exit 0, ONE plain line says the verdict was dropped and why",
                 (changed.returncode, len(lines)), (0, 1))
        check("the line names the test and the cause", bool(lines) and KEY in lines[0]
              and "the author's words" in lines[0], "\n".join(lines))
        row = manifest_of(task)["expectation_changes"][0]
        check_eq("and the manifest row holds the new words and no verdict or note",
                 (row["reason"], "critic_verdict" in row, "critic_note" in row), ("another reason", False, False))
        check_in("the finding says it is not judged yet again", "not judged yet", "\n".join(P.run(task)["notes"]))
    finally:
        cleanup(root)


def a_verdict_patch_finds_its_record() -> None:
    problems = M.expectation_change_problems
    host = dict(VERDICT_ROW, functions=[KEY, KEY_B], critic_verdict="legitimate_correction")
    host.pop("critic_verdict")
    host.pop("critic_note")
    sub = {"function": KEY, "red_attempt": "r1", "green_attempt": "g1", "critic_verdict": "fitted_to_code"}
    merged, summary = M.merge({"expectation_changes": [host]}, {"expectation_changes": [sub]})
    check_eq("F6: a patch `function: a` against a record `functions: [a, b]` lands on that record, which "
             "keeps its functions", ([(r.get("functions"), r.get("critic_verdict")) for r in merged["expectation_changes"]],
                                     summary.get("replaced"), summary.get("added")),
             ([([KEY, KEY_B], "fitted_to_code")], 1, 0))
    check_eq("F6: and it is accepted (it was refused, about `then_refs`)", problems([sub], existing=[host]), [])
    two = [KEY_B, KEY, "test_z.T.test_z"]
    host3 = dict(host, functions=two)
    merged, _s = M.merge({"expectation_changes": [host3]}, {"expectation_changes": [dict(sub, function=KEY_B)]})
    check_eq("F6: a subset of a THREE-function record: still one record, all three functions kept",
             [(r.get("functions"), r.get("critic_verdict")) for r in merged["expectation_changes"]],
             [(two, "fitted_to_code")])
    merged, _s = M.merge({"expectation_changes": [host3]}, {"expectation_changes": [dict(sub, functions=[KEY_B, KEY])]})
    check_eq("F6: two of the three: the same record", len(merged["expectation_changes"]), 1)

    other = dict(host, functions=[KEY, "test_q.T.test_q"])
    got = problems([sub], existing=[host, other])
    check("F6: two records hold the function: ONE refusal, naming the key and BOTH records' keys",
          len(got) == 1 and "inside 2 records" in got[0] and KEY in got[0] and "r1" in got[0]
          and "test_q.T.test_q" in got[0] and KEY_B in got[0], str(got))
    got = problems([dict(sub, function="test_nowhere")], existing=[host])
    check("F6: no record holds it: ONE refusal, naming the asked key and listing the existing keys",
          len(got) == 1 and "matches no record" in got[0] and "test_nowhere" in got[0] and KEY_B in got[0], str(got))
    got = problems([dict(sub, green_attempt="g9")], existing=[host])
    check("F6: the same function with ANOTHER green attempt is not that record", len(got) == 1 and "g9" in got[0], str(got))
    got = problems([dict(sub, functions=[KEY, "test_nowhere"])], existing=[host])
    check("F6: a set that is not a subset (one function the record does not hold) is not that record",
          len(got) == 1 and "matches no record" in got[0], str(got))
    many = [dict(host, functions=[f"test_m.T.test_{n}", f"test_m.T.test_{n}b"]) for n in range(8)]
    got = problems([dict(sub, function="test_nowhere")], existing=many)
    check("the refusal lists six keys and counts the rest", len(got) == 1 and "and 2 more" in got[0]
          and "test_m.T.test_5" in got[0] and "test_m.T.test_6" not in got[0], str(got))
    check_eq("a verdict that carries the author's fields too is a NEW record, not a verdict patch: accepted "
             "with them", problems([dict(sub, function="test_new", then_refs=[{"case": "TC-500", "then": 1}],
                                         what_changed="w", reason="r")], existing=[host]), [])

    # end to end, on the two-function story of `one_record_may_name_several_functions`
    root = temp_project("qa-s5-host-")
    try:
        task = filter_story(root, ticket="QA-590")
        pair = [(FN, "TC-500"), (FN_B, "TC-501")]
        write_block(task, "20260930T050000000000Z-r1.json", "r1", "2026-09-30T05:00:00+00:00", "failed",
                    [brow(fn, "P-new", "failed", "tests", case, instance_code_sha="X") for fn, case in pair],
                    junit(task, "r1", [(fn, "P-new", "failed") for fn, _c in pair]))
        write_block(task, "20260930T051000000000Z-g1.json", "g1", "2026-09-30T05:10:00+00:00", "passed",
                    [brow(fn, "P-new", "passed", "tests", case, instance_code_sha="Y") for fn, case in pair],
                    junit(task, "g1", [(fn, "P-new", "passed") for fn, _c in pair]))
        record = {"functions": [KEY_B, KEY], "red_attempt": "r1", "green_attempt": "g1",
                  "then_refs": [{"case": "TC-500", "then": 1}], "what_changed": "conftest", "reason": "shared fixture"}
        check_eq("the record naming both goes in", put(root, "QA-590", {"expectation_changes": [record]}).returncode, 0)
        verdict = {"expectation_changes": [{"function": KEY, "red_attempt": "r1", "green_attempt": "g1",
                                            "critic_verdict": "fitted_to_code", "critic_note": "restore"}]}
        done = put(root, "QA-590", verdict)
        check_eq("F6: the critic judges ONE of its functions: exit 0", done.returncode, 0)
        rows = manifest_of(task)["expectation_changes"]
        check_eq("F6: one record, its functions not shrunk, the verdict on it",
                 [(r.get("functions"), r.get("critic_verdict")) for r in rows], [([KEY_B, KEY], "fitted_to_code")])
        notes = "\n".join(P.run(task)["notes"])
        check_eq("F6: and the detector shows the verdict on BOTH pairs",
                 notes.count("the critic's verdict is fitted_to_code"), 2)
        second = dict(record, functions=[KEY, "test_q.T.test_q"])
        check_eq("a second record that shares one function goes in (another key)",
                 put(root, "QA-590", {"expectation_changes": [second]}).returncode, 0)
        before = manifest_of(task)
        refused = put(root, "QA-590", {"expectation_changes": [dict(verdict["expectation_changes"][0],
                                                                    critic_verdict="could_not_judge")]})
        check_eq("F6: two records hold the function: exit 3", refused.returncode, 3)
        check("F6: the refusal names the key and both records", "inside 2 records" in refused.stderr
              and '"r1"' in refused.stderr and "test_q.T.test_q" in refused.stderr and KEY_B in refused.stderr,
              refused.stderr)
        check_eq("and nothing was written", manifest_of(task), before)
        none = put(root, "QA-590", {"expectation_changes": [{"function": "test_nowhere", "red_attempt": "r1",
                                                             "green_attempt": "g1", "critic_verdict": "could_not_judge"}]})
        check_eq("F6: no record holds it: exit 3, the key is named and the records are listed",
                 (none.returncode, "test_nowhere" in none.stderr, "matches no record" in none.stderr,
                  KEY_B in none.stderr), (3, True, True, True))
    finally:
        cleanup(root)


# --- t-149 attempt 2 (critic's second verdict on B-194): B1, B2, F4, F-cj, F-door, F-shell --------

def a_retired_red_is_not_cleared_by_the_same_bytes() -> None:
    """B2: a red whose parameters were only RETIRED (renamed or dropped, never covered by a pass) stays
    pending when a pass of another parameter on the SAME bytes clears nothing; the next pass on changed
    bytes of the function pairs with it."""
    root = temp_project("qa-s5-retired-")
    try:
        def pairs_of(ticket: str, *runs, fn: str = FN) -> list:
            task = filter_story(root, ticket=ticket)
            for attempt, minute, outcome, param, sha in runs:
                param_run(task, attempt, minute, outcome, param, sha, fn=fn)
            return changes_of(task)["pairs"]

        def shape(got: list) -> list:
            return [(p["red_attempt"], p["green_attempt"], p["red_sha"], p["green_sha"]) for p in got]
        got = pairs_of("QA-640", ("r1", 0, "failed", "P1", "X"), ("p2", 5, "passed", "P2", "X"),
                       ("g1", 10, "passed", "P1-renamed", "Y"))
        check_eq("B2: P1 red on X, P2 alone passes on X, P1 RENAMED passes on Y: ONE pair, r1 -> g1 "
                 "(it was none: the pass of P2 cleared the retired red and hid the change)",
                 shape(got), [("r1", "g1", "X", "Y")])
        check_eq("B2: the pass of P2 on the red's own bytes adds nothing to the intermediate list",
                 [p["intermediate_shas"] for p in got], [[]])
        got = pairs_of("QA-641", ("r1", 0, "failed", "P1", "X"), ("p2", 5, "passed", "P2", "X"),
                       ("g1", 10, "passed", "P1", "Y"))
        check_eq("B2 control (no rename): the same three runs give the same pair", shape(got), [("r1", "g1", "X", "Y")])
        got = pairs_of("QA-642", ("r1", 0, "failed", "P1", "X"), ("p2", 5, "passed", "P2", "X"),
                       ("g1", 10, "passed", "P1-renamed", "X"))
        check_eq("B2: the renamed pass on the SAME bytes changes nothing: no pair", got, [])
        got = pairs_of("QA-643", ("r1", 0, "failed", "P1", "X"), ("p2", 5, "passed", "P2", "X"),
                       ("p3", 7, "passed", "P3", "X"), ("g1", 10, "passed", "P1-renamed", "Y"))
        check_eq("B2: two same-bytes passes of other parameters in between: still one pair, r1 -> g1",
                 shape(got), [("r1", "g1", "X", "Y")])
        got = pairs_of("QA-644", ("r1", 0, "failed", "P1", "X"), ("p2", 5, "passed", "P2", "Z"),
                       ("g1", 10, "passed", "P1-renamed", "Y"))
        check_eq("B2: the pass in between on OTHER bytes pairs with the red by itself (as before)",
                 [(p["red_attempt"], p["green_attempt"]) for p in got], [("r1", "p2")])
        got = pairs_of("QA-645", ("r1", 0, "failed", "P1", "X"), ("p2", 5, "passed", "P2", "X"))
        check_eq("B2: retired red, same-bytes pass, the function (still in its file) never runs again: "
                 "no pair, as before", got, [])
        # the function is gone from its file: the orphan form - the window gets green_attempt null
        got = pairs_of("QA-646", ("r1", 0, "failed", "P1", "X"), ("p2", 5, "passed", "P2", "X"), fn="test_gone")
        check_eq("B2: the same runs of a function that is gone from its file: an owed orphan pair "
                 "(green_attempt null) from the first red",
                 [(p["function"], p["red_attempt"], p["green_attempt"], p["orphan"], p["owed"]) for p in got],
                 [("test_filter_mod.TestFilters.test_gone", "r1", None, True, True)])
    finally:
        cleanup(root)


def a_word_marks_the_pair_it_names_and_the_pair_stays_visible() -> None:
    """B1 + F-door: the helper returns the pairs a person's word passed; the pair's own tag passes that pair
    only, the stage-wide word every pair; the pair is never dropped; a record answers it instead."""
    import waiver as W
    root = temp_project("qa-s5-mark-")
    try:
        task = filter_story(root)
        param_run(task, "r1", 0, "failed", "P-new", "X")
        param_run(task, "g1", 10, "passed", "P-new", "Y")

        def word(*matches: str) -> None:
            pipeline = {"task": "QA-500"}
            for match in matches:
                W.apply_stage_override(pipeline, "S5", match, "the person lets the test stand", W.now_iso())
            (task / "pipeline.json").write_text(json.dumps(pipeline), encoding="utf-8")

        def state() -> tuple:
            result = P.run(task)
            pairs = result["expectation_changes"]["pairs"]
            return result, pairs, [(p["red_attempt"], p["passed_by_word"]) for p in pairs]
        result, pairs, flags = state()
        check_eq("no word: one pair, not passed, one finding", (flags, len(car(result))), ([("r1", False)], 1))
        fix = car(result)[0]["fix"]
        own = re.search(r'--block "([^"]+)"', fix).group(1)
        check_eq("F-door: the first word the fix prints is THIS pair's own tag", own, P._pair_tag(pairs[0]))
        check("and it names the function and both attempts, not only the word of the stage",
              own.startswith("changed-after-red-") and KEY in own and "r1" in own and "g1" in own, own)
        check_in("F-door: the stage-wide word is still printed, as the broad form",
                 '`--block "changed-after-red"` passes every such pair of the stage', fix)
        check_in("F-door: and says the own tag is for this pair only", "(this pair only;", fix)
        check_in("F-shell: the fix prints the file form of the command too",
                 "`manifest_put.py --task QA-500 --fragment <path to that file>`", fix)
        check_in("F-shell: with the one sentence on PowerShell 5.1", "PowerShell 5.1 strips the inner quotes of the "
                 "inline form, so the file form is the safe one there", fix)

        cases = P.scope_cases(task, manifest_of(task), None)
        word(own)
        result, pairs, flags = state()
        check_eq("B1: the pair's own tag passes it: no finding, the pair is still listed, marked",
                 (flags, len(car(result))), ([("r1", True)], 0))
        changes = P.expectation_changes(task, cases, manifest_of(task))
        check_eq("B1: the helper returns the pairs a word passed (and marks them in place)",
                 ([p["red_attempt"] for p in P.word_passed_pairs(task, changes, cases)],
                  [p["passed_by_word"] for p in changes["pairs"]]), (["r1"], [True]))
        # a NEW pair of the same function in a later attempt: owed; the pair passed before stays passed
        param_run(task, "r2", 20, "failed", "P-new", "W")
        param_run(task, "g2", 30, "passed", "P-new", "V")
        result, pairs, flags = state()
        check_eq("edge: a word given for pair X only, then a NEW pair Y (the same function, later attempts): "
                 "Y is owed and its finding stands, X stays passed", (flags, len(car(result))),
                 ([("r1", True), ("r2", False)], 1))
        changes = P.expectation_changes(task, cases, manifest_of(task))
        check_eq("the helper agrees with run()", [p["red_attempt"] for p in
                                                   P.word_passed_pairs(task, changes, cases)], ["r1"])
        word("changed-after-red")
        result, pairs, flags = state()
        check_eq("edge: the stage-wide word: every pair passed, all visible, none owed",
                 (flags, len(car(result))), ([("r1", True), ("r2", True)], 0))
        check("and the pass is in the notes, once per pair",
              "\n".join(result["notes"]).count("passed by the person's word") == 2, str(result["notes"]))
        # a record for the pair beside the word: the record stands, the pair is marked by it, not by the word
        record = {"function": KEY, "red_attempt": "r1", "green_attempt": "g1", "then_refs": [{"case": "TC-500", "then": 1}],
                  "what_changed": "400 -> 422", "reason": "the case leaves it open"}
        check_eq("the record goes in", put(root, "QA-500", {"expectation_changes": [record]}).returncode, 0)
        result, pairs, flags = state()
        check_eq("edge: a word given, then the author records a row for the same pair anyway: the record "
                 "stands (joined to the pair), the pair is not marked as passed by the word, the other still is",
                 ([p["record"] is not None for p in pairs], flags), ([True, False], [("r1", False), ("r2", True)]))
        # the error direction: a helper that cannot tell marks nothing and says so
        real = P.passed_by_word
        P.passed_by_word = lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("no pipeline"))
        try:
            changes = P.expectation_changes(task, cases, manifest_of(task))
            got = P.word_passed_pairs(task, changes, cases)
        finally:
            P.passed_by_word = real
        check_eq("a helper that cannot read the words marks no pair", (got, [p["passed_by_word"] for p in changes["pairs"]]),
                 ([], [False, False]))
        check("and adds the reason to `unmeasured` (FR-41)", any("RuntimeError: no pipeline" in u
                                                                  for u in changes["unmeasured"]), str(changes["unmeasured"]))
        (task / "pipeline.json").unlink()
        changes = P.expectation_changes(task, cases, manifest_of(task))
        check_eq("with no pipeline.json no pair is marked (a word cannot be invented)",
                 (P.word_passed_pairs(task, changes, cases), changes["unmeasured"]), ([], []))
    finally:
        cleanup(root)


def a_verdict_takes_its_note_with_it() -> None:
    """F4: a note explained the OLD verdict; a patch that changes the verdict without a note of its own drops it."""
    def patched(patch: dict, base: dict = VERDICT_ROW) -> dict:
        merged, _summary = M.merge({"expectation_changes": [dict(base)]}, {"expectation_changes": [patch]})
        return merged["expectation_changes"][0]
    row = patched({**VERDICT_KEY, "critic_verdict": "fitted_to_code"})
    check_eq("F4: a DIFFERENT verdict with no note of its own: the old note is gone",
             (row["critic_verdict"], "critic_note" in row), ("fitted_to_code", False))
    row = patched({**VERDICT_KEY, "critic_verdict": "fitted_to_code", "critic_note": "restore the value"})
    check_eq("F4: a different verdict WITH its note: the new note stands", row["critic_note"], "restore the value")
    row = patched({**VERDICT_KEY, "critic_verdict": VERDICT_ROW["critic_verdict"]})
    check_eq("F4: the SAME verdict sent again with no note: nothing changed, the note stays",
             row["critic_note"], "read the case")
    row = patched({**VERDICT_KEY, "critic_note": "a second reading"})
    check_eq("F4: a note alone replaces the note", (row["critic_verdict"], row["critic_note"]),
             ("legitimate_correction", "a second reading"))
    row = patched({**VERDICT_KEY, "critic_verdict": "fitted_to_code"},
                  base={k: v for k, v in VERDICT_ROW.items() if k != "critic_verdict"})
    check_eq("F4: a note with no verdict beside it is not 'about the old verdict': a first verdict keeps it",
             row["critic_note"], "read the case")
    row = patched({**VERDICT_KEY, "critic_verdict": "fitted_to_code"},
                  base={k: v for k, v in VERDICT_ROW.items() if k != "critic_note"})
    check_eq("F4: a verdict change on a record that had no note has nothing to drop", "critic_note" in row, False)


def could_not_judge_needs_its_note() -> None:
    """F-cj: one road - the critic's note is the reason the conductor records the window as unresolved."""
    problems = M.expectation_change_problems
    sub = {"function": KEY, "red_attempt": "r1", "green_attempt": "g1", "critic_verdict": "could_not_judge"}
    host = dict(VERDICT_ROW, functions=[KEY, KEY_B])
    host.pop("critic_verdict")
    host.pop("critic_note")
    for label, extra in (("no note at all", {}), ("an empty note", {"critic_note": ""}),
                         ("a whitespace note", {"critic_note": " \t\n "})):
        got = problems([{**sub, **extra}], existing=[host])
        check(f"F-cj: could_not_judge with {label} is refused, and the refusal says a note is required",
              len(got) == 1 and "`critic_note` is required" in got[0] and "could_not_judge" in got[0]
              and "unresolved" in got[0], str(got))
    got = problems([{**sub, "critic_note": 5}], existing=[host])
    check("F-cj: a note that is not a string gets the type refusal only (one problem)",
          len(got) == 1 and "must be a string" in got[0], str(got))
    check_eq("F-cj: with a note it is accepted", problems([{**sub, "critic_note": "the red report names no Then"}],
                                                          existing=[host]), [])
    for verdict in ("legitimate_correction", "fitted_to_code"):
        check_eq(f"F-cj: {verdict} needs no note (the rule is for could_not_judge alone)",
                 problems([{**sub, "critic_verdict": verdict}], existing=[host]), [])
    new_row = dict(sub, then_refs=[{"case": "TC-500", "then": 1}], what_changed="w", reason="r", function="test_new")
    check_eq("F-cj: a NEW record carrying could_not_judge with no note is refused too", len(problems([new_row], existing=[])), 1)
    root = temp_project("qa-s5-cj-")
    try:
        task = filter_story(root)
        cmp1_shape(task)
        record = {"function": KEY, "red_attempt": A1, "green_attempt": A4, "then_refs": [{"case": "TC-500", "then": 1}],
                  "what_changed": "400 -> 422", "reason": "the case leaves it open"}
        check_eq("the record goes in", put(root, "QA-500", {"expectation_changes": [record]}).returncode, 0)
        before = manifest_of(task)
        bare = put(root, "QA-500", {"expectation_changes": [{"function": KEY, "red_attempt": A1, "green_attempt": A4,
                                                              "critic_verdict": "could_not_judge", "critic_note": "  "}]})
        check_eq("F-cj end to end: exit 3, the refusal names the field, and nothing was written",
                 (bare.returncode, "`critic_note` is required" in bare.stderr, manifest_of(task)), (3, True, before))
        done = put(root, "QA-500", {"expectation_changes": [{"function": KEY, "red_attempt": A1, "green_attempt": A4,
                                                              "critic_verdict": "could_not_judge",
                                                              "critic_note": "the red report does not name the Then"}]})
        check_eq("F-cj end to end: with its note the verdict is written", (done.returncode, manifest_of(task)[
            "expectation_changes"][0]["critic_verdict"]), (0, "could_not_judge"))
    finally:
        cleanup(root)


def the_merged_record_keeps_its_note() -> None:
    """t-149 fix 1: the note is checked on the MERGED record, not on the patch."""
    problems = M.expectation_change_problems
    base = {**VERDICT_KEY, "then_refs": [{"case": "TC-500", "then": 1}], "what_changed": "w", "reason": "r",
            "critic_verdict": "could_not_judge", "critic_note": "the red report names no Then"}
    key = {"function": KEY, "red_attempt": "r1", "green_attempt": "g1"}
    host = dict(base, functions=[KEY, KEY_B])
    host.pop("function", None)
    for label, patch in (("a blank note", {"critic_note": "   "}), ("an empty note", {"critic_note": ""})):
        got = problems([{**key, **patch}], existing=[host])
        check(f"fix 1: {label} patched onto a recorded could_not_judge is refused (the merged record would hold none)",
              len(got) == 1 and "`critic_note` is required" in got[0], str(got))
    check_eq("fix 1: a new note is accepted", problems([{**key, "critic_note": "a second reading"}], existing=[host]), [])
    check_eq("fix 1: the same verdict sent again with no note: the merged record keeps its note, accepted",
             problems([{**key, "critic_verdict": "could_not_judge"}], existing=[host]), [])
    check_eq("fix 1: a patch with no critic field at all is not judged on the note",
             problems([{**key, "what_changed": "w2"}], existing=[host]), [])
    check_eq("fix 1: a blank note beside ANOTHER verdict is fine (the verdict needs none)",
             problems([{**key, "critic_verdict": "fitted_to_code", "critic_note": " "}], existing=[host]), [])
    legit = dict(host, critic_verdict="legitimate_correction", critic_note="ok")
    check("fix 1: a change to could_not_judge with no note drops the old note and is refused",
          len(problems([{**key, "critic_verdict": "could_not_judge"}], existing=[legit])) == 1)
    root = temp_project("qa-s5-merged-")
    try:
        task = filter_story(root)
        cmp1_shape(task)
        record = {"function": KEY, "red_attempt": A1, "green_attempt": A4, "then_refs": [{"case": "TC-500", "then": 1}],
                  "what_changed": "400 -> 422", "reason": "the case leaves it open"}
        check_eq("the record goes in", put(root, "QA-500", {"expectation_changes": [record]}).returncode, 0)
        ident = {"function": KEY, "red_attempt": A1, "green_attempt": A4}
        check_eq("could_not_judge with its note goes in", put(root, "QA-500", {"expectation_changes": [
            {**ident, "critic_verdict": "could_not_judge", "critic_note": "the red report names no Then"}]}).returncode, 0)
        before = manifest_of(task)
        blank = put(root, "QA-500", {"expectation_changes": [{**ident, "critic_note": "   "}]})
        row = manifest_of(task)["expectation_changes"][0]
        check_eq("fix 1 end to end: patching a blank note exits 3, names the field, and the stored note is unchanged",
                 (blank.returncode, "`critic_note` is required" in blank.stderr, row["critic_verdict"], row["critic_note"],
                  manifest_of(task) == before), (3, True, "could_not_judge", "the red report names no Then", True))
    finally:
        cleanup(root)


def the_refusal_prints_the_pairs_own_door_or_none() -> None:
    """t-149 fix 2: the manifest_put refusal's person's-word sentence is the pair's own tag, and when a word already
    passed the pair it says so and prints no --block (P13)."""
    import waiver as W
    root = temp_project("qa-s5-door2-")
    try:
        task = filter_story(root)
        cmp1_shape(task)
        pair = P.expectation_changes(task, ["TC-500"], manifest_of(task))["pairs"][0]
        own = P._pair_tag(pair)
        verdict_only = {"expectation_changes": [{"function": KEY, "red_attempt": A1, "green_attempt": A4,
                                                 "critic_verdict": "legitimate_correction"}]}
        bare = put(root, "QA-500", verdict_only)
        check_eq("no record, no word: the verdict-only patch is refused", bare.returncode, 3)
        check_in("fix 2: the refusal prints the pair's OWN tag, with the real ticket", f'--task QA-500 --stage S5 --block "{own}"',
                 bare.stderr)
        check_in("fix 2: the broad form is printed after it, as the stage's form", '`--block "changed-after-red"` passes every pair',
                 bare.stderr)
        check_not_in("fix 2: and no placeholder ticket", "<TICKET>", bare.stderr)
        check("fix 2: the own tag comes before the broad form", bare.stderr.find(own) < bare.stderr.find('--block "changed-after-red"'))
        pipeline = {"task": "QA-500"}
        W.apply_stage_override(pipeline, "S5", own, "the person lets the test stand", W.now_iso())
        (task / "pipeline.json").write_text(json.dumps(pipeline), encoding="utf-8")
        passed = put(root, "QA-500", verdict_only)
        check_eq("an own-tag word exists: the verdict-only patch is still refused (nothing is owed, no record)",
                 passed.returncode, 3)
        check_in("fix 2: the refusal says the pair is already passed by a person's word", "already passed by a person's word",
                 passed.stderr)
        check_not_in("fix 2: and prints NO --block at all: the word is never asked for twice", "--block", passed.stderr)
        check_not_in("nor a waiver command", "waiver.py", passed.stderr)
        # a row that names no pair: the stage's broad form, with the real ticket
        odd = put(root, "QA-500", {"expectation_changes": [{"function": KEY}]})
        check("a row naming no attempts: refused, and the broad form is printed with the real ticket",
              odd.returncode == 3 and '--task QA-500 --stage S5 --block "changed-after-red"' in odd.stderr, odd.stderr)
    finally:
        cleanup(root)


def the_verdict_is_one_line_per_finding() -> None:
    """C2-1: `report` prints the contract of `detector_verdict` - `REJECT — N` with the label that says the recorded
    words were judged HERE, then N lines, one finding each, the finding id in its label; a finding refused to every
    word has its own `WORDS_REFUSED_AT_SOURCE` line ABOVE the header; the footer names the door only for what a word
    can pass. The label never depends on what `passed_by_word` reached (an early return, a failed import)."""
    import detector_verdict as DETV
    import tempfile
    env = P._finding("environment", "TC-1", "the stand lacks a login", "name the variable", "stand-login")
    mani = P._finding("manifest", "TC-1", "the manifest row has no file", "write the file", "no-file")
    oracle = P._finding("oracle", "TC-1", "the Then left open", "assert the value", "open-then")
    out = printed({"ok": False, "findings": [env, mani, oracle], "hints": [{"check": "smell", "message": "twins",
                   "fix": "parametrize"}], "notes": ["a note"], "cases": ["TC-1"]})
    lines = out.splitlines()
    heads = [i for i, line in enumerate(lines) if line.startswith("REJECT")]
    check_eq("report: one header, with the count and the label", [lines[i].startswith("REJECT — 3 finding(s) for the "
             "author before the code critic " + DETV.WORDS_AT_SOURCE) for i in heads], [True])
    check_eq("report: exactly 3 lines under it, each one finding, none a second `  fix:` line",
             [line.startswith("- [") and " — fix: " in line for line in lines[heads[0] + 1:heads[0] + 4]], [True] * 3)
    check_not_in("report: no line of its own for a fix", "\n  fix:", out)
    check_in("report: the id is in the label of the finding line", "- [environment environment:TC-1:stand-login] ", out)
    verdict = DETV.parse(1, out, "")
    check_eq("parse reads the same 3 findings, no defect, no unmigrated, the repair marker",
             (len(verdict["findings"]), verdict["defects"], verdict["unmigrated"], verdict["marker"], verdict["words"]),
             (3, [], "", "repair", "source"))
    check_eq("the families no word passes carry their line, the passable one does not",
             verdict["refused"], ["", "family", "family"])
    check("the refusal lines stand ABOVE the header", all(i < heads[0] for i, line in enumerate(lines)
          if line.startswith(DETV.WORDS_REFUSED_AT_SOURCE)) and out.count(DETV.WORDS_REFUSED_AT_SOURCE) == 2, out[:300])
    # the footer joins every tag of WORD_PASSABLE_TAGS (sides-undeclared and provisional-open-on-real joined changed-after-red later)
    check_in("the footer names the door for the passable families and the tags", "an [environment] or [obligations] "
             "finding or a " + " or ".join(P.WORD_PASSABLE_TAGS) + " one", out)
    check_in("...the first tag is still changed-after-red", "finding or a changed-after-red or ", out)
    check_in("...and says no word passes the rest, `*` included", "no recorded word, `*` included, passes any other "
             "finding", out)
    check_not_in("...and never names `--block \"*\"` as a door", '--block "*"', out)
    # no passable family at all: passed_by_word returns before it imports the waiver; the label and the tags stay
    only = [mani, P._finding("smell", "TC-1", "sleep", "poll", "sleep-1")]
    out = printed({"ok": False, "findings": P.passed_by_word(Path(tempfile.gettempdir()), only, []), "hints": [],
                   "notes": [], "cases": []})
    check_in("zero passable families: the label is in the header", DETV.WORDS_AT_SOURCE, out)
    check_eq("...and every finding has its family line", [line for line in out.splitlines()
             if line.startswith(DETV.WORDS_REFUSED_AT_SOURCE)],
             [f"{DETV.WORDS_REFUSED_AT_SOURCE} {f['id']} family" for f in only])
    # the waiver cannot be imported: the passable finding is printed as it is (no verdict, no line), the other keeps its tag
    saved = sys.modules.get("waiver")
    sys.modules["waiver"] = None
    try:
        kept = P.passed_by_word(Path(tempfile.gettempdir()), [env, mani], [])
    finally:
        if saved is None:
            sys.modules.pop("waiver", None)
        else:
            sys.modules["waiver"] = saved
    out = printed({"ok": False, "findings": kept, "hints": [], "notes": [], "cases": []})
    check_eq("no waiver: label there, the passable finding untagged, the other tagged `family`",
             (DETV.WORDS_AT_SOURCE in out, DETV.parse(1, out, "")["refused"]), (True, ["", "family"]))
    empty = printed({"ok": False, "findings": [], "hints": [], "notes": [], "cases": []})
    parsed = DETV.parse(1, empty, "")
    with contextlib.redirect_stdout(io.StringIO()):
        empty_code = P.report({"ok": False, "findings": [], "hints": [], "notes": [], "cases": []})
    check_eq("a result that is not ok yet lists no finding is read by the classifier as a DEFECT of the check, never as "
             "unmigrated output (t-772 m3)",
             (bool(parsed["defects"]), parsed["unmigrated"], parsed["findings"],
              empty_code), (True, "", [], 1))
    # a word copied from the PRINTED line passes the finding here (it is judged against the line, not only the old text)
    import waiver as W
    root = temp_project("qa-s5-line-word-")
    try:
        pipeline = {"task": "QA-500"}
        W.apply_stage_override(pipeline, "S5", "[environment environment:TC-1:stand-login] the stand lacks",
                               "the person lets it stand", "2026-10-01T10:00:00+00:00")
        (root / "pipeline.json").write_text(json.dumps(pipeline), encoding="utf-8")
        left = P.passed_by_word(root, [env, mani], [])
        check_eq("a word taken from the printed line passes its finding and leaves the other", [f["id"] for f in left],
                 [mani["id"]])
    finally:
        cleanup(root)


def a_broad_word_covers_only_what_existed() -> None:
    """t-149 fix 3: a stage-wide `changed-after-red` word passes the pairs whose green run existed when the word was
    given; a pair whose green came later stops again, and its finding says the word predates it."""
    import waiver as W
    root = temp_project("qa-s5-broad-")
    try:
        task = filter_story(root)
        cmp1_shape(task)
        manifest = manifest_of(task)
        cases = P.scope_cases(task, manifest, None)
        pair = P.expectation_changes(task, cases, manifest)["pairs"][0]
        check_eq("the pair carries the clock of its green run", pair["pair_at"], "2026-09-30T04:56:13.929353+00:00")

        def word(match: str, at: str) -> tuple:
            pipeline = {"task": "QA-500"}
            W.apply_stage_override(pipeline, "S5", match, "the person lets the test stand", at)
            (task / "pipeline.json").write_text(json.dumps(pipeline), encoding="utf-8")
            result = P.run(task)
            return result, result["expectation_changes"]["pairs"][0]["passed_by_word"]
        result, flag = word("changed-after-red", "2026-09-30T06:00:00+00:00")
        check_eq("fix 3: a broad word given AFTER the green run passes the pair", (flag, len(car(result))), (True, 0))
        result, flag = word("changed-after-red", "2026-09-30T04:56:13.929353+00:00")
        check_eq("fix 3: a broad word given at the very moment of the green run passes it (not later than the word)",
                 (flag, len(car(result))), (True, 0))
        result, flag = word("changed-after-red", "2026-09-30T04:00:00+00:00")
        check_eq("fix 3: a broad word given BEFORE the green run does not pass it: the finding stands",
                 (flag, len(car(result))), (False, 1))
        said = car(result)[0]["message"] if car(result) else ""  # a missing finding fails the check above, not here
        check("fix 3: and the finding says the earlier stage-wide word predates the run",
              "the stage-wide word `changed-after-red` (given 2026-09-30T04:00:00+00:00) predates this run" in said, said)
        # C2-1 pin (§L-4): the source's refusal by `predating` is a line ABOVE the header, and the text names the word
        # as it was recorded; the behaviour of the source itself (the comparison with the green run) is unchanged
        import detector_verdict as DETV
        shown = printed(result)
        check_in("fix 3: and the refusal is tagged `predating` for the gate", f"{DETV.WORDS_REFUSED_AT_SOURCE} "
                 f"{car(result)[0]['id']} predating", shown)
        check("fix 3: ...above the header", shown.index(DETV.WORDS_REFUSED_AT_SOURCE) < shown.index("REJECT"), shown[:300])
        read = DETV.parse(1, shown, "")
        check_eq("fix 3: ...and the gate ties it to that finding alone (the others of this fixture are families)",
                 [(f.split("] ")[0], r) for f, r in zip(read["findings"], read["refused"]) if r == "predating"],
                 [(f"[oracle {car(result)[0]['id']}", "predating")])
        changes = P.expectation_changes(task, cases, manifest)
        check_eq("fix 3: the helper of the window and the brief agrees with run()", P.word_passed_pairs(task, changes, cases), [])
        for label, match in (("the pair's own tag", P._pair_tag(pair)), ("`*`", "*")):
            result, flag = word(match, "2026-09-30T04:00:00+00:00")
            check_eq(f"fix 3: {label} given before the green run is not compared: it passes", (flag, len(car(result))), (True, 0))
        result, flag = word(f"changed-after-red-{KEY}", "2026-09-30T04:00:00+00:00")
        check_eq("fix 3: a function word is no pair's own tag: it passes nothing, early or late", (flag, len(car(result))), (False, 1))
        result, flag = word("CHANGED-AFTER-RED", "2026-09-30T04:00:00+00:00")
        check_eq("fix 3: the broad word in capitals is the same word", (flag, len(car(result))), (False, 1))
        result, flag = word("changed-after-red", "not a time")
        check_eq("fix 3: a word whose clock cannot be read is honoured, as before", (flag, len(car(result))), (True, 0))
        # two pairs of one function: the word is given between their green runs
        task2 = filter_story(root, ticket="QA-501")
        for run in (("r1", 0, "failed", "P-new", "X"), ("g1", 10, "passed", "P-new", "Y"),
                    ("r2", 20, "failed", "P-new", "W"), ("g2", 30, "passed", "P-new", "V")):
            param_run(task2, *run)
        pipeline = {"task": "QA-501"}
        W.apply_stage_override(pipeline, "S5", "changed-after-red", "the person lets the test stand",
                               "2026-09-30T05:15:00+00:00")
        (task2 / "pipeline.json").write_text(json.dumps(pipeline), encoding="utf-8")
        result = P.run(task2)
        check_eq("fix 3: a broad word between two green runs: the first pair passed, the LATER pair stops again",
                 ([p["passed_by_word"] for p in result["expectation_changes"]["pairs"]], len(car(result))),
                 ([True, False], 1))
        check_in("fix 3: and its finding says the earlier word predates it", "predates this run",
                 car(result)[0]["message"] if car(result) else "")
    finally:
        cleanup(root)


def the_could_not_judge_road_is_said_the_same_everywhere() -> None:
    """F-cj (FR-10): ONE road, one sentence, in every place that states it: the vocabulary, the rubric dim 9,
    the critic's charter (the changed-after-red bullet), the window's gap row, the brief's line and the writer's refusal."""
    road = "the conductor records the window as unresolved with the reason"
    package = Path(__file__).resolve().parents[2]

    def flat(text: str) -> str:
        return " ".join(text.split())
    import brief_pack
    import handoff
    import window_record
    places = {
        "vocabulary.yaml (could_not_judge)": handoff.vocabulary()["expectation_change_verdicts"]["could_not_judge"],
        "code-review-rubric.md (dim 9)": (package / "references" / "code-review-rubric.md").read_text(encoding="utf-8"),
        "qa-code-critic.md (the changed-after-red bullet)": (package / "agents" / "qa-code-critic.md").read_text(encoding="utf-8"),
        "window_record.GAP_ORIGIN": " ".join(window_record.change_origin("could_not_judge")),
        "manifest_put refusal": " ".join(M.expectation_change_problems([{
            "function": KEY, "red_attempt": "r1", "green_attempt": "g1", "critic_verdict": "could_not_judge"}],
            existing=[{"function": KEY, "red_attempt": "r1", "green_attempt": "g1", "then_refs": [{"case": "TC-500", "then": 1}],
                       "what_changed": "w", "reason": "r"}])),
        "brief_pack.EXPECTATION_COULD_NOT_JUDGE_ROAD": brief_pack.EXPECTATION_COULD_NOT_JUDGE_ROAD,
    }
    for place, text in places.items():
        check_in(f"F-cj: {place} says the road in the same words", road, flat(text))
    check_not_in("F-cj: and no place sends the critic to a person's word for it any more",
                 "a person's word decides", flat(places["code-review-rubric.md (dim 9)"]))


# TP2-2406 S5-6 (19.10.2026): the live manifest row, binding and scope, copied as data.
OB3_INSTANCE = ("BrownEvents.Tests.AttendeeDashboardIntegrationTests."
                "SubmitFeedback_ReturnsClearPreEndError_AndDoesNotPersistFeedback")
OB3_ROW = {"instance_id": OB3_INSTANCE, "case": "feedback-api/TC-003", "covers": ["feedback-api/TC-003"],
           "file": "backend/BrownEvents.Tests/AttendeeDashboardIntegrationTests.cs", "status": "red",
           "case_version_links": [{"case_id": "TC-003", "version": "cv_f128c110b97c91eb7962"}]}
OB3_BINDING = {"obligation_id": "OB-3", "instance_ids": [OB3_INSTANCE], "design_assessment": "sufficient",
               "assertion_refs": ["backend/BrownEvents.Tests/AttendeeDashboardIntegrationTests.cs:225"],
               "change_disposition": "new_or_changed", "change_basis_ref": "manifest:feedback-api/TC-003",
               "code_validity": "unverified", "sensitivity": "missing"}
OB3_SCOPE = ["TC-001", "TC-002", "TC-004", "feedback-api/TC-003"]


def obligation_story(plan_row: str = "TS-3") -> tuple:
    """(root, task): a schema-2 plan whose row `plan_row` holds OB-3, decision `new`."""
    root = temp_project("qa-ob3-")
    task = root / "qa-factory" / "artifacts" / "TP2-2406"
    (task / "work").mkdir(parents=True)
    plan = {"rows": [{"id": plan_row, "schema_version": 2, "coverage_obligations": [
        {"obligation_id": "OB-3", "decision": "new", "execution_scope": "current_task"}]}]}
    (task / "work" / "test-plan.json").write_text(json.dumps(plan), encoding="utf-8")
    return root, task


def obligation_findings(task: Path, manifest: dict, scope: list, plan_row: str = "TS-3") -> list:
    findings: list = []
    # Only TC-003 belongs to the plan row that holds OB-3; the other scope cases name no row.
    texts = {case: f"Plan row: {plan_row}\n" for case in scope if case.endswith("TC-003")}
    P.check_obligations(task, manifest, scope, texts, set(), findings)
    return [f for f in findings if "OB-3" in f["message"]]


def a_qualified_scope_case_binds_its_obligation() -> None:
    """t-044 item 2: `instances_of_case` answers the case in the ASKER's spelling, so a binding that
    names the instance of `feedback-api/TC-003` binds OB-3 (it read as unbound before)."""
    root, task = obligation_story()
    try:
        manifest = {"tests": [OB3_ROW], "obligation_bindings": [OB3_BINDING]}
        check_eq("OB-3: the real 2406 shape (qualified scope, qualified covers) leaves no OB-3 finding",
                 obligation_findings(task, manifest, OB3_SCOPE), [])
        check_eq("OB-3: instances_of_case finds the row of the qualified case",
                 [e["instance_id"] for e in P.instances_of_case(manifest, "feedback-api/TC-003")],
                 [OB3_INSTANCE])
        check_in("OB-3: and the instance's spelling is among the covering ids", OB3_INSTANCE,
                 P._covering_ids(manifest, "feedback-api/TC-003"))
        check_eq("OB-3: a bare ask still finds the row through its pinned bare link (case_version_links)",
                 P.instances_of_case(manifest, "TC-003"), [OB3_ROW])
        other = dict(OB3_BINDING, instance_ids=["Some.Other.Instance"])
        found = obligation_findings(task, {"tests": [OB3_ROW], "obligation_bindings": [other]}, OB3_SCOPE)
        check_eq("OB-3: a binding that names ANOTHER instance still leaves the finding", len(found), 1)
        check_in("OB-3: and the finding names the qualified case", "feedback-api/TC-003",
                 found[0]["message"] if found else "")
        check_eq("OB-3: no binding at all is the finding too",
                 len(obligation_findings(task, {"tests": [OB3_ROW], "obligation_bindings": []}, OB3_SCOPE)),
                 1)

        bare_row = {"instance_id": "test_three", "case": "TC-003", "covers": ["TC-003"],
                    "file": "tests/t.py", "status": "green"}
        bare_binding = {"obligation_id": "OB-3", "instance_ids": ["test_three"]}
        check_eq("OB-3: a bare binding on a bare row still binds",
                 obligation_findings(task, {"tests": [bare_row], "obligation_bindings": [bare_binding]},
                                     ["TC-003"]), [])

        # A bare ask over a number two areas hold: non-strict, both rows answer, the check reads both.
        rows = [dict(OB3_ROW, instance_id="test_a", covers=["alpha/TC-003"], case="alpha/TC-003"),
                dict(OB3_ROW, instance_id="test_b", covers=["beta/TC-003"], case="beta/TC-003")]
        both = {"tests": rows}
        check_eq("OB-3: a bare ask over two areas returns both rows (non-strict, today's answer)",
                 [e["instance_id"] for e in P.instances_of_case(both, "TC-003")], ["test_a", "test_b"])
        for instance in ("test_a", "test_b"):
            bound = dict(both, obligation_bindings=[{"obligation_id": "OB-3", "instance_ids": [instance]}])
            check_eq(f"OB-3: the check reads both rows - a binding of {instance} binds the bare ask",
                     obligation_findings(task, bound, ["TC-003"]), [])
        check_eq("OB-3: and a qualified ask picks only its own area's row",
                 [e["instance_id"] for e in P.instances_of_case(both, "beta/TC-003")], ["test_b"])
    finally:
        cleanup(root)


def check_manifest_sees_the_qualified_scope_case() -> None:
    """t-044 item 2(c), the sweep of the same artifact: `check_manifest` selected rows by
    `set(manifest_test_links) & set(cases)` and grouped them by bare link, so a row of a
    qualified scope case was invisible to its own invariants."""
    twin = {"instance_id": "test_x", "case": "feedback-api/TC-003", "covers": ["feedback-api/TC-003"],
            "file": "tests/t.py", "status": "green"}
    findings: list = []
    P.check_manifest({"tests": [twin, dict(twin)]}, ["TC-001", "feedback-api/TC-003"], findings)
    check_in("sweep: two rows of one instance id are found under a qualified scope case",
             "two tests[] entries carry the instance id", " ".join(f["message"] for f in findings))
    findings = []
    both_lists = {"tests": [twin], "unresolved": [{"case": "feedback-api/TC-003", "reason": "x",
                                                   "partitions": []}]}
    P.check_manifest(both_lists, ["feedback-api/TC-003"], findings)
    check_in("sweep: a qualified case in tests[] and unresolved[] at once is the both-lists finding",
             "both-lists", " ".join(f["id"] for f in findings))
    findings = []
    P.check_manifest({"tests": [dict(twin, covers=["TC-003"], case="TC-003"),
                                dict(twin, covers=["TC-003"], case="TC-003")]}, ["TC-003"], findings)
    check_in("sweep: a bare scope case is judged as before", "two tests[] entries carry the instance id",
             " ".join(f["message"] for f in findings))


def write_area_cases(task: Path, areas: dict) -> None:
    """The story's case store, `work/test-cases/<area>/<case>.md`: {area: {case id: text of the Then section}}."""
    for area, cases in areas.items():
        for cid, then in cases.items():
            path = task / "work" / "test-cases" / area / f"{cid}.md"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"---\nid: {cid}\ntask: {task.name}\n---\n# {cid} of {area}\n## Then\n{then}\n",
                            encoding="utf-8")


def a_then_ref_is_checked_against_its_own_areas_case_file() -> None:
    """t-1249 F4: `_then_ref_problems` read the case file by `case.split("/")[-1]`, so in a two-area story a
    `then_ref` to `session-feedback/TC-003` was checked against the OTHER area's Then numbers (the first file by name)."""
    root, task = obligation_story()
    try:
        write_area_cases(task, {"feedback-api": {"TC-003": "1. a\n2. b"},
                               "session-feedback": {"TC-003": "1. a\n2. b\n3. c"}})
        scope = ["feedback-api/TC-003", "session-feedback/TC-003"]

        def problems(case: str, then: int) -> list:
            return P._then_ref_problems(task, {"then_refs": [{"case": case, "then": then}]}, scope)

        check_eq("F4: a ref to the second area's Then 3 resolves against ITS file (was: refused against the first)",
                 problems("session-feedback/TC-003", 3), [])
        refused = problems("feedback-api/TC-003", 3)
        check_eq("F4: the first area has no Then 3 - one problem", len(refused), 1)
        check_in("F4: and it names that area's own Then numbers", "numbered [1, 2]", " ".join(refused))
        unknown = P._then_ref_problems(task, {"then_refs": [{"case": "other-area/TC-003", "then": 1}]},
                                       scope + ["other-area/TC-003"])
        check_eq("F4: an area the store does not hold finds no case file (a problem, never the other area's file)",
                 len(unknown), 1)
        check_in("F4: and says so", "no case file with numbered Then clauses was found", " ".join(unknown))
        check_eq("F4: a bare ref keeps the lookup by name",
                 P._then_ref_problems(task, {"then_refs": [{"case": "TC-003", "then": 1}]}, ["TC-003"]), [])
    finally:
        cleanup(root)


def a_missing_case_file_says_where_it_looked() -> None:
    """EP1-38 item 3: the refusal of a `then_ref` whose case file was not found names the files and the folders looked under;
    the older substring stays (the pin above)."""
    root, task = obligation_story()
    try:
        cfg = json.loads((root / "qa-factory" / "config.json").read_text(encoding="utf-8"))
        cfg["cases_root"] = "cases"
        (root / "qa-factory" / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
        got = " ".join(P._then_ref_problems(task, {"then_refs": [{"case": "TC-044", "then": 1}]}, ["TC-044"]))
        check_in("EP1-38: the old words are still there", "no case file with numbered Then clauses was found", got)
        check_in("EP1-38: ... then the names looked for", "looked for TC-044.md and TC-044-*.md under:", got)
        roots = P.case_search_roots(task)
        check_eq("EP1-38: three roots (the store is the third)", len(roots), 3)
        for folder in roots:
            check_in(f"EP1-38: ... and the folder {folder.name} is named", str(folder), got)
    finally:
        cleanup(root)


# --- EP1-38 (B-10): a soft red does not stop the test --------------------------------------------------------------------
SOFT_SRC = "\n".join([
    "import { test, expect } from '@playwright/test';",       # 1
    "test('cart', async () => {",                              # 2
    "  expect.soft(a).toBe(1);",                               # 3  Then 1 (red)
    "  expect(c).toBe(9);",                                    # 4
    "  await go();",                                           # 5
    "  expect.soft(b).toBe(2);",                               # 6  Then 2
    "});", ""])
SOFT_IID = "cart"
SOFT_ID = "cart.spec.ts::cart"


def soft_story(root: Path, ticket: str, source: str = SOFT_SRC, file: str = "tests/cart.spec.ts", spans=("3-3", "6-6"),
               stacks=(("{file}:3:18",),), report: str = "ok", status: str = "failed", report_id: str = SOFT_ID,
               tail: str = "") -> tuple:
    """(task, manifest): a Playwright-style story whose one test is red by its own `contradicts_requirement` row at Then 1 and
    holds Then 2 `covered` behind it. `stacks`: one tuple of frame spellings per run block (oldest first; `{file}` is the
    project file, absolute); `report`: ok | none | badsha."""
    task = root / "qa-factory" / "artifacts" / ticket
    (task / "work" / "run-blocks").mkdir(parents=True, exist_ok=True)
    (root / file).parent.mkdir(parents=True, exist_ok=True)
    (root / file).write_text(source, encoding="utf-8")
    shown = str(root / file)
    for number, frames in enumerate(stacks):
        attempt = f"a{number}"
        body = "\n".join(f"        at {f.replace('{file}', shown)}" for f in frames)
        xml = ('<testsuites><testsuite name="cart.spec.ts" tests="1"><testcase classname="cart.spec.ts" name="cart">'
               f'<failure message="expect(received).toBe(expected)"><![CDATA[    Error: expect(received).toBe(expected)\n\n{body}\n{tail}]]>'
               '</failure></testcase></testsuite></testsuites>').encode("utf-8")
        relative = f"evidence/runs/{attempt}/report.xml"
        (task / relative).parent.mkdir(parents=True, exist_ok=True)
        (task / relative).write_bytes(xml)
        proof = {"reporter": "junit-xml", "report_path": relative,
                 "report_sha256": "0" * 64 if report == "badsha" else hashlib.sha256(xml).hexdigest()}
        write_block(task, f"20260930T05{number:02d}00000000Z-{attempt}.json", attempt, f"2026-09-30T05:{number:02d}:00+00:00",
                    "failed", [{"instance_id": SOFT_IID, "test_id": report_id, "status": status, "report_matched": True}],
                    None if report == "none" else proof)
    refs = [f"{file}:{spans[0]}", f"{file}:{spans[1]}"]
    manifest = {
        "tests": [{"case": "TC-001", "covers": ["TC-001"], "file": file, "instance_id": SOFT_IID, "status": "red"}],
        "unresolved": [{"case": "TC-001", "reason": "contradicts_requirement", "instance_ids": [SOFT_IID], "thens": [1],
                        "detail": "d"}],
        "then_bindings": [{"case": "TC-001", "then": n, "instance_id": SOFT_IID, "assertion_ref": ref, "status": "covered"}
                          for n, ref in ((1, refs[0]), (2, refs[1]))]}
    return task, manifest


def soft_ids(task: Path, manifest: dict, store=True) -> list:
    found: list = []
    P.check_manifest(manifest, ["TC-001"], found, store_root=task if store else None)
    return sorted(f["id"].split(":")[-1].split("-" + SOFT_IID)[0] for f in found if "red-own-" in f["id"])


def a_soft_red_does_not_stop_the_test() -> None:
    """E-soft-red: `red-own-behind` is lifted ONLY when the red Then is made of soft asserts, the newest run's own report is
    readable and every failure frame of it lies inside the red lines. Every other input keeps the finding (FR-18, FR-59)."""
    behind = ["red-own-behind"]
    root = temp_project("qa-s5-soft-")
    try:
        n = iter(range(100))

        def story(**kw):
            return soft_story(root, f"QA-{next(n)}", **kw)

        task, manifest = story()
        check_eq("E-soft-red: soft red, report holds only the red's frame -> the finding is lifted", soft_ids(task, manifest), [])
        check_eq("E-soft-red: ... the same story with no project root (store_root=None) -> behind as today",
                 soft_ids(task, manifest, store=False), behind)
        # B-10: a throw after the soft red - the later asserts never ran
        task, manifest = story(stacks=(("{file}:3:18", "{file}:5:9"),))
        check_eq("E-soft-red (B-10): a frame outside the red lines (the throw) -> behind", soft_ids(task, manifest), behind)
        task, manifest = story(stacks=(("{file}:3:18", "{file}:4:3"),))
        check_eq("E-soft-red: a later HARD assert that failed (frame on its line) -> behind", soft_ids(task, manifest), behind)
        task, manifest = story(stacks=(("{file}:3:18", "/work/proj/helpers/cart.ts:10:5"),))
        check_eq("E-soft-red: a frame in a helper file -> behind (the test went elsewhere)", soft_ids(task, manifest), behind)
        task, manifest = story(stacks=(("{file}:3:18", "{file}:3:18"),))
        check_eq("E-soft-red: several errors, all inside the red lines -> lifted", soft_ids(task, manifest), [])
        task, manifest = story(stacks=(("tests/cart.spec.ts:3:18",),))
        check_eq("E-soft-red: a frame spelled as the span spells it (relative) -> lifted", soft_ids(task, manifest), [])
        task, manifest = story(stacks=(("src/tests/cart.spec.ts:3:18",),))
        check_eq("E-soft-red: a relative frame that is not the span's path -> behind (the cwd is never guessed)",
                 soft_ids(task, manifest), behind)
        task, manifest = story(stacks=(("{file}:3:18", "{file}:5:9"), ("{file}:3:18",)))
        check_eq("E-soft-red: the NEWEST block decides (its report shows the red only) -> lifted", soft_ids(task, manifest), [])
        task, manifest = story(stacks=(("{file}:3:18",), ("{file}:3:18", "{file}:5:9")))
        check_eq("E-soft-red: ... and a newer block with a throw -> behind", soft_ids(task, manifest), behind)
        # F-2 (t-555): a test that STOPPED leaves only the soft frame; the text's integrity says so (real Playwright 1.64.1 texts)
        task, manifest = story(tail="\n    Test timeout of 1500ms exceeded.\n")
        check_eq("E-soft-red (F-2): the soft frame, then `Test timeout` -> behind (the hang)", soft_ids(task, manifest), behind)
        task, manifest = story(tail="\n    Error: nostack\n")
        check_eq("E-soft-red (F-2): the soft frame, then an error with no frame (a stackless throw) -> behind",
                 soft_ids(task, manifest), behind)
        task, manifest = story(tail="\n    Error Context: ../test-results/x/error-context.md\n")
        check_eq("E-soft-red (F-2): the soft frame, then only `Error Context:` -> still lifted", soft_ids(task, manifest), [])
        task, manifest = story(tail="\n    attachment #1: screenshot\n")
        check_eq("E-soft-red (F-2): text after the frame that the data does not know -> behind (the safe side)",
                 soft_ids(task, manifest), behind)
        # the red lines
        task, manifest = story(source=SOFT_SRC.replace("expect.soft(a)", "expect(a)"))
        check_eq("E-soft-red: a HARD red with a soft later assert -> behind", soft_ids(task, manifest), behind)
        task, manifest = story(spans=("3-4", "6-6"))
        check_eq("E-soft-red: a mixed span (soft and hard heads) -> behind", soft_ids(task, manifest), behind)
        task, manifest = story(source=SOFT_SRC.replace("  expect.soft(a).toBe(1);", "  expect(a).toBe(1); // expect.soft(x)"))
        check_eq("E-soft-red: a soft form named only in a comment beside a hard head -> hard -> behind",
                 soft_ids(task, manifest), behind)
        task, manifest = story(source=SOFT_SRC.replace("  expect.soft(a).toBe(1);", "  log(\"expect.soft(\");"))
        check_eq("E-soft-red: a soft form inside a string, no head at all -> not soft -> behind", soft_ids(task, manifest), behind)
        task, manifest = story(spans=("3-6", "3-6"))
        check_eq("E-soft-red: one shared range for every Then -> `red-own-order-unknown` as today, never lifted",
                 soft_ids(task, manifest), ["red-own-order-unknown"])
        # the run
        task, manifest = story(report="none")
        check_eq("E-soft-red: a block with no evidence -> behind", soft_ids(task, manifest), behind)
        task, manifest = story(report="badsha")
        check_eq("E-soft-red: a report whose sha256 is not the recorded one -> behind", soft_ids(task, manifest), behind)
        task, manifest = story(status="passed")
        check_eq("E-soft-red: the newest row of the instance is not `failed` -> behind", soft_ids(task, manifest), behind)
        task, manifest = story(report_id="cart.spec.ts::another")
        check_eq("E-soft-red: the report holds no row of the row's test_id -> behind", soft_ids(task, manifest), behind)
        # the file and the language
        task, manifest = story(file="tests/cart.spec.rb")
        check_eq("E-soft-red: a language with no entry in detectors.json -> behind", soft_ids(task, manifest), behind)
        task, manifest = story()
        check_eq("E-soft-red: _all_soft of no span -> False", P._all_soft(None, task), False)
        check_eq("E-soft-red: _all_soft of the soft line (3) -> True, of a line with no assert (5) -> False, of no project -> False",
                 (P._all_soft(("tests/cart.spec.ts", 3, 3), task), P._all_soft(("tests/cart.spec.ts", 5, 5), task),
                  P._all_soft(("tests/cart.spec.ts", 3, 3), None)), (True, False, False))
        (root / "tests" / "cart.spec.ts").unlink()
        check_eq("E-soft-red: a file that cannot be read -> behind", soft_ids(task, manifest), behind)
        task, manifest = story(source="def test_cart():\n    assert 1 == 2\n    assert 3 == 4\n", file="tests/test_cart.py",
                               spans=("2-2", "3-3"))
        check_eq("E-soft-red: a .py file -> behind as today", soft_ids(task, manifest), behind)
    finally:
        cleanup(root)


def failure_frames_walk_every_frame() -> None:
    """`reporters.failure_frames` (E-soft-red, item 7): ALL frames of ALL failure problems, in order; None when unknown."""
    import reporters as R
    import assertion_detectors as AD
    entry = next(e for e in AD.assertion_detectors().values() if ".ts" in e["suffixes"])
    frames, skip, _how = AD.grammar_of(entry)
    fixture = Path(__file__).resolve().parent / "fixtures" / "playwright-junit" / "soft-errors.xml"
    rows = {r["test_id"]: r for r in R.read_rows(fixture, "junit-xml")}
    check_eq("failure_frames: two soft errors in one <failure> -> both frames (the first-frame reader saw one)",
             R.failure_frames(rows["soft.spec.js::two soft"], frames, skip),
             [("/work/proj/tests/soft.spec.js", 3), ("/work/proj/tests/soft.spec.js", 4)])
    check_eq("failure_frames: the B-10 text (soft failure, then a throw) -> lines 7 and 8",
             R.failure_frames(rows["soft.spec.js::b10"], frames, skip),
             [("/work/proj/tests/soft.spec.js", 7), ("/work/proj/tests/soft.spec.js", 8)])
    head, ok = AD.soft_report_of(entry)
    check_eq("F-2: the typescript entry declares its soft report", head is not None and bool(ok), True)
    check_eq("F-2: real Playwright 1.64.1 text, two soft errors, the integrity check on -> both frames still",
             R.failure_frames(rows["soft.spec.js::two soft"], frames, skip, head, ok),
             [("/work/proj/tests/soft.spec.js", 3), ("/work/proj/tests/soft.spec.js", 4)])
    check_eq("F-2: the B-10 text (soft, then a throw with its frame), integrity on -> lines 7 and 8",
             R.failure_frames(rows["soft.spec.js::b10"], frames, skip, head, ok),
             [("/work/proj/tests/soft.spec.js", 7), ("/work/proj/tests/soft.spec.js", 8)])
    check_eq("F-2: real text of a soft red then a HANG (`Test timeout of 1500ms exceeded.`) -> None with the check on",
             R.failure_frames(rows["h.spec.ts::hang"], frames, skip, head, ok), None)
    check_eq("F-2: ... and the same row without the check reads one frame (why the check exists)",
             R.failure_frames(rows["h.spec.ts::hang"], frames, skip), [("/work/proj/tests/h.spec.ts", 3)])
    check_eq("F-2: real text of a soft red then a throw with no stack frame -> None with the check on",
             R.failure_frames(rows["h.spec.ts::stackless"], frames, skip, head, ok), None)
    check_eq("F-2: an error_head that does not compile -> None, no exception",
             R.failure_frames(rows["soft.spec.js::b10"], frames, skip, "(", ok), None)
    check_eq("failure_frames: a row that did not fail -> None", R.failure_frames({"status": "passed", "problems": []}, frames, skip), None)
    check_eq("failure_frames: a failed row with no frame in its text -> None",
             R.failure_frames({"status": "failed", "problems": [{"kind": "failure", "text": "boom"}]}, frames, skip), None)
    check_eq("failure_frames: a grammar that does not compile -> None, no exception",
             R.failure_frames(rows["soft.spec.js::b10"], ["("], skip), None)
    check_eq("failure_frames: a grammar without the named groups -> None",
             R.failure_frames(rows["soft.spec.js::b10"], ["at (.*)"], skip), None)
    check_eq("failure_frames: a skipped frame is skipped", R.failure_frames(
        {"status": "failed", "problems": [{"kind": "failure", "text": "  at /a/node_modules/x.js:1:2\n  at /a/t.ts:5:6"}]},
        frames, skip), [("/a/t.ts", 5)])


def an_unresolved_row_is_found_by_the_qualified_scope_case() -> None:
    """t-1249 F5: `check_manifest` looked an `unresolved[]` row up by the exact scope string, so a bare row of the
    number was skipped under a qualified scope case. It is found while the number is held under ONE area and is
    a finding that names every spelling when it is held under two - never a skip."""
    root, task = obligation_story()
    try:
        twin = {"instance_id": "test_x", "case": "feedback-api/TC-003", "covers": ["feedback-api/TC-003"],
                "file": "tests/t.py", "status": "green"}
        other = dict(twin, instance_id="test_y", case="session-feedback/TC-003", covers=["session-feedback/TC-003"])
        bare_row = {"case": "TC-003", "reason": "x", "partitions": []}

        def ids(manifest: dict, scope: list, store=None) -> str:
            found: list = []
            P.check_manifest(manifest, scope, found, store_root=store)
            return " ".join(f["id"] for f in found)

        one = {"tests": [twin], "unresolved": [bare_row]}
        check_in("F5: a bare unresolved row is found by the qualified scope case (the both-lists finding)",
                 "both-lists", ids(one, ["feedback-api/TC-003"]))
        write_area_cases(task, {"feedback-api": {"TC-003": "1. a"}})
        check_in("F5: and with a store that holds ONE area", "both-lists", ids(one, ["feedback-api/TC-003"], task))
        check_eq("F5: a row that names ANOTHER area is not found for it",
                 ids({"tests": [twin], "unresolved": [dict(bare_row, case="session-feedback/TC-003")]},
                     ["feedback-api/TC-003"], task), "")
        two = {"tests": [twin, other], "unresolved": [bare_row]}
        refused = ids(two, ["feedback-api/TC-003", "session-feedback/TC-003"])
        check_in("F5: two qualified scope cases of the number - the bare row is a finding, not a skip",
                 "unresolved-area-TC-003", refused)
        check_not_in("F5: and no both-lists finding is made from a guess", "both-lists", refused)
        write_area_cases(task, {"feedback-api": {"TC-003": "1. a"}, "session-feedback": {"TC-003": "1. a"}})
        refused = ids(one, ["feedback-api/TC-003"], task)
        check_in("F5: one scope case, but the STORE holds two areas - the same finding", "unresolved-area-TC-003", refused)
        found: list = []
        P.check_manifest(one, ["feedback-api/TC-003"], found, store_root=task)
        message = " ".join(f["message"] for f in found)
        check_in("F5: the finding names every spelling", "feedback-api/TC-003, session-feedback/TC-003", message)
        check_eq("F5: a bare scope case with a bare row is the old path (both-lists)",
                 "both-lists" in ids({"tests": [dict(twin, case="TC-003", covers=["TC-003"])],
                                      "unresolved": [bare_row]}, ["TC-003"]), True)
    finally:
        cleanup(root)


def a_qualified_ask_finds_the_binding_rows_that_name_it() -> None:
    """t-044 fix round (critic t-045 B1 and F2): `bindings_of_case` and the shape check compare in the
    ASKER's spelling too. The live shape: two `then_bindings` rows of `feedback-api/TC-003` naming the
    instance, the manifest row `covers: ["feedback-api/TC-003"]`."""
    def binding(then: int, line: int, **extra) -> dict:
        return dict({"case": "feedback-api/TC-003", "then": then, "instance_id": OB3_INSTANCE,
                     "assertion_ref": f"backend/BrownEvents.Tests/AttendeeDashboardIntegrationTests.cs:{line}",
                     "status": "covered"}, **extra)

    rows = [binding(1, 225), binding(2, 230)]
    manifest = {"tests": [OB3_ROW], "then_bindings": rows}
    text = "## Then\n1. a clear pre-end error is returned\n2. nothing is persisted\n"

    def findings_for(case: str, data: dict) -> list:
        found: list = []
        P.check_bindings(data, case, text, [], [], found)
        return [P._finding_tag(f) for f in found]

    check_eq("B1: a qualified ask returns both rows that name it (was: [])",
             P.bindings_of_case(manifest, "feedback-api/TC-003"), rows)
    check_eq("B1: check_bindings reports nothing over the two exact bindings (was: no-bindings)",
             findings_for("feedback-api/TC-003", manifest), [])
    check_eq("B1: the bare ask keeps returning the same rows",
             P.bindings_of_case(manifest, "TC-003"), rows)
    check_eq("B1: a row naming ANOTHER area is not returned for the qualified ask",
             P.bindings_of_case({"tests": [OB3_ROW], "then_bindings": [binding(1, 225, case="beta/TC-003")]},
                                "feedback-api/TC-003"), [])
    check_eq("B1: and the finding is the honest no-bindings one",
             [i for i in findings_for("feedback-api/TC-003",
                                      {"tests": [OB3_ROW], "then_bindings": [binding(1, 225, case="beta/TC-003")]})
              if i == "no-bindings"], ["no-bindings"])
    check_eq("B1: a qualified ask does not take a row naming the bare number (today's answer)",
             P.bindings_of_case({"tests": [OB3_ROW], "then_bindings": [binding(1, 225, case="TC-003")]},
                                "feedback-api/TC-003"), [])
    check_eq("B1: a row naming no case still answers through its instance (the fallback stays)",
             P.bindings_of_case({"tests": [OB3_ROW], "then_bindings": [binding(1, 225, case="")]},
                                "feedback-api/TC-003"),
             [binding(1, 225, case="")])
    check_eq("B1: a row naming no case and another instance is not returned",
             P.bindings_of_case({"tests": [OB3_ROW], "then_bindings": [binding(1, 225, case="",
                                                                              instance_id="Other.Test")]},
                                "feedback-api/TC-003"), [])
    legacy = {k: v for k, v in binding(1, 225).items() if k != "case"}
    legacy["case_id"] = "feedback-api/TC-003"
    check_eq("B1: the `case_id` spelling of a row is read like `case`",
             P.bindings_of_case({"tests": [OB3_ROW], "then_bindings": [legacy]}, "feedback-api/TC-003"),
             [legacy])

    # F2: the "instance id names the case" shape finding, in the qualified spelling.
    def shape_ids(instance: str, covers: str) -> list:
        row = {"instance_id": instance, "case": covers, "covers": [covers], "file": "tests/t.py",
               "status": "green"}
        found: list = []
        P.check_manifest({"tests": [row]}, [covers], found)
        return [P._finding_tag(f) for f in found if P._finding_tag(f).startswith("shape-")]

    check_eq("F2: the bare pair gives the shape finding", shape_ids("TC-003", "TC-003"), ["shape-TC-003"])
    check_eq("F2: the qualified pair gives the same finding, not silence (was: [])",
             shape_ids("feedback-api/TC-003", "feedback-api/TC-003"), ["shape-feedback-api/TC-003"])
    check_eq("F2: an instance id that is a real test name gives none",
             shape_ids(OB3_INSTANCE, "feedback-api/TC-003"), [])
    check_eq("F2: a qualified instance id of ANOTHER area than the row's covers gives none",
             shape_ids("beta/TC-003", "feedback-api/TC-003"), [])


RED_THEN_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "run-12586-red-then"
RT_IID3 = "test_put_project_change_into_project_with_ms_teams_is_rejected"
RT_IID2 = "test_put_project_change_moves_ms_teams_integration"
RT_FILE3 = "testproject1_test_harness/tests/integrations/project/test_ms_teams_integration.py"


def _rt_manifest() -> dict:
    """The REAL TP1-12586 manifest rows of TC-002/TC-003 (fixture `run-12586-red-then`): two tests, each red by its own
    `contradicts_requirement` row (TC-002 at Then 1, TC-003 at Then 2), every Then bound `covered` with the test's ONE range."""
    return json.loads((RED_THEN_FIXTURE / "work" / "automation-manifest.json").read_text(encoding="utf-8"))


def _rt_pin(manifest: dict, case: str, pins: dict) -> dict:
    """The same manifest with `then={n: "a-b"}` pins of `case` applied to its covered `then_bindings` (what
    `manifest_from_tests._assertion_ref` writes for a marker that pins the Then lines)."""
    for row in manifest["then_bindings"]:
        if row["case"] == case and row["then"] in pins:
            row["assertion_ref"] = f"{RT_FILE3}:{pins[row['then']]}"
    return manifest


def _rt_found(manifest: dict, cases=("TC-002", "TC-003")) -> dict:
    found: list = []
    P.check_manifest(manifest, list(cases), found)
    return {f["id"]: f for f in found}


def a_then_behind_its_own_red_is_named() -> None:
    """K-R5-*: the Thens of a test that is red by its own row (R5, t-1508). Data: the real 12586 rows."""
    own3 = lambda got, kind: sorted(i.rsplit("-", 1)[1] for i in got if f"manifest:TC-003:red-own-{kind}-{RT_IID3}-" in i)
    # K-R5-1 / K-R5-S (unpinned): the live shape - one shared range - names the order unknown for every Then but the red one
    live = _rt_found(_rt_manifest())
    check_eq("K-R5-1: shared range -> `red-own-order-unknown` for Thens 1, 3, 4 of TC-003 (2 is the red one)",
             own3(live, "order-unknown"), ["1", "3", "4"])
    check_eq("K-R5-1: ... and for Thens 2, 3, 4 of TC-002 (red at Then 1)",
             sorted(i.rsplit("-", 1)[1] for i in live if f"manifest:TC-002:red-own-order-unknown-{RT_IID2}-" in i),
             ["2", "3", "4"])
    check_eq("K-R5-1: no `red-links-unbound` for a test red by its own row (the branch is unreachable for it)",
             [i for i in live if "red-links-unbound" in i], [])
    check_eq("K-R5-1: the level is `repair` (a finding, not a hint)", {f["level"] for f in live.values()}, {"repair"})
    door = live[f"manifest:TC-003:red-own-order-unknown-{RT_IID3}-3"]
    check_in("K-R5-11: the door says when to move the assert", "does not wait for", door["fix"])
    check_in("K-R5-11: ... when not to (the Then waits for the defect)", "blocking_check", door["fix"])
    check_in("K-R5-11: ... and the pin", 'then={3: "a-b"', door["fix"])
    check_in("K-R5-1: the message says the order is not established", "not established", door["message"])

    # K-R5-S (pinned) / K-R5-2 / K-R5-3: pinned apart, Then 2 is the red one
    pins = {1: "345-349", 2: "350-354", 3: "355-359", 4: "360-364"}
    pinned = _rt_found(_rt_pin(_rt_manifest(), "TC-003", pins))
    check_eq("K-R5-2: Thens 3 and 4 are pinned AFTER the red Then 2 -> `red-own-behind`",
             own3(pinned, "behind"), ["3", "4"])
    check_eq("K-R5-3: Then 1 pinned BEFORE the red Then -> nothing for it", [i for i in pinned if i.endswith(f"{RT_IID3}-1")], [])
    check_eq("K-R5-2: no `order-unknown` once pinned", own3(pinned, "order-unknown"), [])
    check_in("K-R5-2: the message names the lines", "355-359", pinned[f"manifest:TC-003:red-own-behind-{RT_IID3}-3"]["message"])
    # boundaries AT the comparison: m starting on the very line n ends is an overlap (unknown), not behind; m ending on the
    # line n starts is an overlap too, not "before"
    edge = _rt_found(_rt_pin(_rt_manifest(), "TC-003", {1: "345-350", 2: "350-354", 3: "354-359", 4: "360-364"}))
    check_eq("K-R5-3: m=3 starts on the last line of n=2 -> unknown, NOT behind", own3(edge, "behind"), ["4"])
    check_eq("K-R5-3: ... m=1 ends on the first line of n=2 -> unknown, not silent", own3(edge, "order-unknown"), ["1", "3"])
    # K-R5-6: a pin that overlaps the red Then's lines
    lap = _rt_found(_rt_pin(_rt_manifest(), "TC-003", {1: "352-356", 2: "350-354", 3: "355-359", 4: "360-364"}))
    check_eq("K-R5-6: overlapping lines -> unknown for the overlapping Then, behind for the clear ones",
             (own3(lap, "order-unknown"), own3(lap, "behind")), (["1"], ["3", "4"]))
    other_file = _rt_manifest()
    _rt_pin(other_file, "TC-003", pins)
    next(b for b in other_file["then_bindings"] if b["case"] == "TC-003" and b["then"] == 3)["assertion_ref"] = "other/test_x.py:355-359"
    check_eq("K-R5-6: another file for the Then -> unknown, never behind",
             (own3(_rt_found(other_file), "order-unknown"), own3(_rt_found(other_file), "behind")), (["3"], ["4"]))
    unreadable = _rt_manifest()
    next(b for b in unreadable["then_bindings"] if b["case"] == "TC-003" and b["then"] == 1).pop("assertion_ref")
    check_eq("K-R5-6: a binding with no `assertion_ref` -> unknown", "1" in own3(_rt_found(unreadable), "order-unknown"), True)

    # K-R5-4: a Then recorded `blocked_by_check` is not asked again
    blocked = _rt_manifest()
    blocked["then_bindings"] = [b for b in blocked["then_bindings"] if not (b["case"] == "TC-003" and b["then"] in (3, 4))]
    blocked["then_bindings"] += [{"case": "TC-003", "then": n, "instance_id": RT_IID3, "status": "unresolved",
                                  "reason": "blocked_by_check", "blocking_check": "TC-002", "detail": "behind the red"}
                                 for n in (3, 4)]
    check_eq("K-R5-4: Thens 3, 4 recorded `blocked_by_check` -> only Then 1 is named", own3(_rt_found(blocked), "order-unknown"), ["1"])

    # K-R5-5: red only by ANOTHER case's row -> `red-links-unbound` (as before), no `red-own-*` for the bystander
    foreign = _rt_manifest()
    next(t for t in foreign["tests"] if t["instance_id"] == RT_IID3)["covers"] = ["TC-003", "TC-004"]
    got = _rt_found(foreign, ("TC-003", "TC-004"))
    check_eq("K-R5-5: the bystander case TC-004 gets `red-links-unbound` and nothing from the new check",
             sorted(i for i in got if ":TC-004:" in i), ["manifest:TC-004:red-links-unbound"])

    # K-R5-7: a row that names no Then -> one finding per instance, no order findings
    unnamed = _rt_manifest()
    next(u for u in unnamed["unresolved"] if u["case"] == "TC-003").pop("thens")
    got = _rt_found(unnamed)
    check_eq("K-R5-7: no `thens` -> exactly one `red-own-thens-unnamed` for TC-003, no order findings",
             sorted(i for i in got if ":TC-003:" in i), [f"manifest:TC-003:red-own-thens-unnamed-{RT_IID3}"])

    # K-R5-12 (t-1532 R5-2): TC-002's row also lands on TC-003's instance -> the instance is red for two cases: only
    # `red-two-cases` (keep one row), no `red-own-*` (name the Then in the row) - one row never gets two opposite doors
    two = _rt_manifest()
    next(t for t in two["tests"] if t["instance_id"] == RT_IID3)["covers"] = ["TC-003", "TC-002"]
    two["then_bindings"].append({"case": "TC-002", "then": 1, "instance_id": RT_IID3, "assertion_ref": f"{RT_FILE3}:345-349",
                                 "status": "covered"})
    next(u for u in two["unresolved"] if u["case"] == "TC-002")["instance_ids"].append(RT_IID3)
    got = _rt_found(two, ("TC-002", "TC-003"))
    check("K-R5-12: the setup makes the instance red for two cases", any("red-two-cases" in i for i in got))
    check_eq("K-R5-12: red for two cases -> `red-two-cases` and no `red-own-*` for THAT instance (TC-002's other instance, "
             "red for one case only, still speaks)",
             [i for i in got if "red-own-" in i and RT_IID3 in i], [])
    # K-R5-13 (t-1532 R5-1): a test with `status: green` and its own row without `thens` -> no `red-own-*` for it
    green = _rt_manifest()
    next(t for t in green["tests"] if t["instance_id"] == RT_IID3)["status"] = "green"
    next(u for u in green["unresolved"] if u["case"] == "TC-003").pop("thens")
    got = _rt_found(green)
    check_eq("K-R5-13: a green test gets no `red-own-*` for TC-003", sorted(i for i in got if "red-own-" in i and ":TC-003:" in i), [])

    # K-R5-9: the case is outside the scope -> nothing
    scoped = _rt_found(_rt_manifest(), ("TC-002",))
    check_eq("K-R5-9: scope TC-002 only -> no finding for TC-003", [i for i in scoped if ":TC-003:" in i], [])
    check("K-R5-9: ... and TC-002 still speaks", any(":TC-002:" in i for i in scoped))

    # K-R5-8: a `blocked_by_check` row for a Then that RAN and failed
    case_md = (RED_THEN_FIXTURE / "work" / "test-cases" / "integrations" / "TC-003.md").read_text(encoding="utf-8")
    ran = _rt_manifest()
    ran["then_bindings"].append({"case": "TC-003", "then": 2, "instance_id": RT_IID3, "status": "unresolved",
                                 "reason": "blocked_by_check", "blocking_check": "TC-002", "detail": "behind TC-002"})
    side: list = []
    P.check_then_remainders(RED_THEN_FIXTURE, ran, ["TC-003"], {"TC-003": case_md}, side, [])
    tags = sorted(f["id"] for f in side)
    check_eq("K-R5-8: blocked_by_check on the red Then 2 -> `blocked-check-ran-2` and nothing else", tags,
             ["bindings:TC-003:blocked-check-ran-2"])
    check_in("K-R5-8: the message says it ran", "ran and failed", side[0]["message"] if side else "")
    fine = _rt_manifest()
    fine["then_bindings"].append({"case": "TC-003", "then": 3, "instance_id": RT_IID3, "status": "unresolved",
                                  "reason": "blocked_by_check", "blocking_check": "TC-002", "detail": "behind TC-002"})
    side = []
    P.check_then_remainders(RED_THEN_FIXTURE, fine, ["TC-003"], {"TC-003": case_md}, side, [])
    check_eq("K-R5-8: a blocked Then that did NOT run (3) is not `ran`", [f["id"] for f in side if "ran-" in f["id"]], [])

    # K-R5-10: an S7 repair round ("S7 fix: ...") hears the same words as hints; any other reason is a finding
    import shutil
    import s7_reorder  # the carrier of the repair review's reason (t-593 F-7, AR-13)
    for reason, soft in (("S7 fix: test_x - verdict TEST_BUG", True), ("S7 reorder: test_x", False), ("", False),
                         (s7_reorder.REPAIR_REVIEW_REASON.format(test="test_x"), False)):
        root = temp_dir()
        task = root / "task"
        shutil.copytree(RED_THEN_FIXTURE, task)
        (task / "state").mkdir()
        (task / "state" / "controller.json").write_text(json.dumps({"dispatches": {"S5-qa-automator-9": {
            "id": "S5-qa-automator-9", "scope": ["TC-003"], "reason": reason}}}), encoding="utf-8")
        result = P.run(task, "S5-qa-automator-9")
        in_findings = [f["id"] for f in result["findings"] if "red-own-" in f["id"]]
        in_hints = [f["id"] for f in result["hints"] if "red-own-" in f["id"]]
        check_eq(f"K-R5-10: reason {reason!r} -> the three `red-own-*` words are "
                 f"{'hints, not findings' if soft else 'findings, not hints'}",
                 (len(in_findings), len(in_hints)), (0, 3) if soft else (3, 0))
        cleanup(root)


SLEEP_SNIPPETS = (
    # (label, function source, allow_poll, a bare sleep is found)
    ("sleep(2)", "def f():\n    sleep(2)\n", False, True),
    ("time.sleep(DELAY): a name is an argument too", "def f():\n    time.sleep(DELAY)\n", False, True),
    ("asyncio.sleep(2)", "async def f():\n    await asyncio.sleep(2)\n", False, True),
    ("a finalizer after yield", "def f():\n    yield 1\n    time.sleep(2)\n", True, True),
    ("for without a condition", "def f():\n    for _ in range(3):\n        sleep(2)\n", True, True),
    ("while True with one exit", "def f():\n    while True:\n        sleep(1)\n", True, True),
    ("while not ready() has no ceiling", "def f():\n    while not ready():\n        sleep(1)\n", True, True),
    ("a poll in a TEST body is still a smell", "def f():\n    for _ in range(9):\n        if ready():\n            break\n"
                                                "        sleep(1)\n", False, True),
    ("from time import sleep as pause: the NAMED residual, not seen", "def f():\n    pause(2)\n", False, False),
    ("a comment and a docstring", "def f():\n    '''sleep(2)'''\n    # sleep(2)\n    return 1\n", False, False),
    ("not_a_sleep(2)", "def f():\n    not_a_sleep(2)\n", False, False),
    ("for + if + return + sleep: a poll with a ceiling", "def f():\n    for _ in range(30):\n        if ready():\n            return 1\n"
                                                          "        sleep(1)\n", True, False),
    ("while on a deadline", "def f():\n    while time.time() < deadline:\n        poll()\n        sleep(1)\n", True, False),
    ("while True with two ways out", "def f():\n    while True:\n        if ok():\n            return 1\n"
                                     "        if late():\n            raise TimeoutError\n        sleep(1)\n", True, False),
)

FIXTURE_CONFTEST = '''import time

import pytest


@pytest.fixture
def slow_old():
    time.sleep(2)
    return 1
'''


def _git_in(cwd, *args) -> None:
    done = subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "-c", "commit.gpgsign=false", *args],
                          cwd=str(cwd), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
    if done.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {done.stderr.strip()}")


def _smells(task, project, relative, text="", case="TC-1", stub=None, function=None):
    """`check_smells` over one test of the file `relative`; `stub` replaces `_fixture_changed` (and records its calls)."""
    parsed, _problem = P.read_python(project / relative)
    name = function or next(iter(parsed.functions))
    findings, notes, calls = [], [], []
    saved = P._fixture_changed
    if stub is not None:
        P._fixture_changed = lambda *a: (calls.append(a), (stub if isinstance(stub, tuple) else stub(*a)))[1]
    try:
        P.check_smells(case, text, [parsed], [(parsed, name, parsed.functions[name])], findings, task, notes)
    finally:
        P._fixture_changed = saved
    return findings, [], notes, calls       # the advice list takes what the findings and the hints held before X7-2


def a_sleep_in_the_fixtures_of_a_test_is_the_windows_code_only_when_it_changed() -> None:
    """TQ1-16 AK1-AK3, AK5. Kills: a closure without transitivity; `unknown` read as a finding or as silence; a poll without
    a ceiling accepted; autouse / `usefixtures` / `name=` not read; an id without the path (two conftests merge)."""
    import ast
    for label, source, allow_poll, expected in SLEEP_SNIPPETS:
        check_eq(f"_bare_sleep: {label}", P._bare_sleep(ast.parse(source).body[0], allow_poll=allow_poll) is not None, expected)

    # -- a real repository: the base is S0, and `measure_many` answers for a function of a conftest -----------------------
    import test_repo_base
    repo = temp_dir("qa-s5-fx-")
    try:
        proj = repo / "proj"
        task = proj / "qa-factory" / "artifacts" / "QA-600"
        (proj / "tests").mkdir(parents=True)
        (task / "state").mkdir(parents=True)
        (proj / "qa-factory" / "config.json").write_text("{}", encoding="utf-8")
        (repo / ".gitignore").write_text("qa-factory/\n", encoding="utf-8")
        (proj / "tests" / "conftest.py").write_text(FIXTURE_CONFTEST, encoding="utf-8")
        (proj / "tests" / "test_x.py").write_text(
            "import pytest\n\n\n@pytest.fixture\ndef mid(deep):\n    return deep\n\n\n"
            "def test_via(mid):\n    assert mid\n\n\ndef test_old(slow_old):\n    assert slow_old\n", encoding="utf-8")
        _git_in(repo, "init", "-q", "-b", "main")
        _git_in(repo, "add", "-A")
        _git_in(repo, "commit", "-q", "-m", "base")
        test_repo_base.record(task, proj, {"tests_root": "tests"})

        # AK2: the conftest is as it was at S0 -> the sleep of the old fixture is nobody's finding
        findings, hints, notes, _calls = _smells(task, proj, "tests/test_x.py", function="test_old")
        check_eq("AK2: an unchanged project fixture with a sleep is no finding", [f["id"] for f in findings], [])
        check_eq("AK2: ... and no hint (the measure answered `unchanged`)", [h["id"] for h in hints], [])

        # AK1: the story adds `deep` (a sleep) to the conftest; the test reaches it through ANOTHER fixture (`mid`)
        (proj / "tests" / "conftest.py").write_text(
            FIXTURE_CONFTEST + "\n\n@pytest.fixture\ndef deep():\n    time.sleep(2)\n    return 2\n", encoding="utf-8")
        parsed, _p = P.read_python(proj / "tests" / "test_x.py")
        via = [(parsed, "test_via", parsed.functions["test_via"])]
        findings, notes = [], []
        P.check_smells("TC-1", "", [parsed], via, findings, task, notes)
        check_eq("AK1: a new conftest fixture with sleep(2), reached through another fixture, is a `smell` ADVICE",
                 [(f["check"], f["level"], f["id"]) for f in findings],
                 [("smell", "advice", "smell:TC-1:sleep-tests.conftest.py-deep")])
        check_in("AK1: the message names the file and the fixture", "tests/conftest.py: `deep` waits with sleep()",
                 findings[0]["message"] if findings else "")
        check_not_in("X7-2: advice carries no door - it blocks nothing, so there is nothing to open", "the gate stays closed",
                     findings[0]["fix"] if findings else "")
        check("F3: advice asks nothing (no `?` in the fix)", bool(findings) and "?" not in findings[0]["fix"])
        # X7-2: advice is not a finding of the gate - no recorded word applies to it, and no judge is asked about it
        sleeper = findings[0]
        check("X7-2: ... it is not word-passable and has no word door", not P._passable(sleeper) and "word_door" not in sleeper)
        check_eq("X7-2: ... and no judge question exists for a smell any more", P._judge_plan(sleeper, task, {"TC-1": [parsed]}, {"TC-1": CASE_MD}), None)
        check("X7-2: ... and it carries no code excerpt for a judge", "code_excerpt" not in sleeper)
        check_eq("AK1: nothing else is said", notes, [])
        # a fixture the story did not write but whose conftest it edited reads `changed`: the safe direction (named residual)
        again, _h, _n, _c = _smells(task, proj, "tests/test_x.py", function="test_old")
        check_eq("measure_many on a conftest function answers new/changed/unchanged against S0: the OLD fixture reads `changed` "
                 "once its file was edited (the safe direction, a named residual)",
                 [f["id"].split(":", 2)[2] for f in again], ["sleep-tests.conftest.py-slow_old"])
    finally:
        cleanup(repo)

    # -- F4: the project is found by its marker, not by the depth of the story folder (a non-default artifact root) --------
    repo = temp_dir("qa-s5-fx-root-")
    try:
        proj = repo / "proj"
        task = proj / "stories" / "QA-700"                       # `artifact_root: stories`: parents[2] would be `repo`
        (proj / "tests").mkdir(parents=True)
        (task / "state").mkdir(parents=True)
        (proj / "qa-factory").mkdir()
        (proj / "qa-factory" / "config.json").write_text('{"artifact_root": "stories"}', encoding="utf-8")
        (repo / ".gitignore").write_text("qa-factory/\nstories/\n", encoding="utf-8")
        (proj / "tests" / "conftest.py").write_text("import pytest\n", encoding="utf-8")
        (proj / "tests" / "test_x.py").write_text("def test_via(deep):\n    assert deep\n", encoding="utf-8")
        _git_in(repo, "init", "-q", "-b", "main")
        _git_in(repo, "add", "-A")
        _git_in(repo, "commit", "-q", "-m", "base")
        test_repo_base.record(task, proj, {"tests_root": "tests"})
        (proj / "tests" / "conftest.py").write_text(
            "import time\n\nimport pytest\n\n\n@pytest.fixture\ndef deep():\n    time.sleep(2)\n    return 2\n", encoding="utf-8")
        (repo / "conftest.py").write_text("import time\n\nimport pytest\n\n\n@pytest.fixture\ndef above():\n    time.sleep(3)\n",
                                          encoding="utf-8")
        check_eq("F4: _project_of finds the folder with the marker, whatever the artifact root", P._project_of(task), proj.resolve())
        findings, hints, notes, _calls = _smells(task, proj, "tests/test_x.py", function="test_via")
        check_eq("F4: a story under a non-default artifact root still gets `new` for the added fixture",
                 [f["id"].split(":", 2)[2] for f in findings], ["sleep-tests.conftest.py-deep"])
        check_eq("F4: ... as a finding, not a hint, and with the project-relative name", (hints, "tests/conftest.py" in findings[0]["message"]),
                 ([], True))
        rows, cnotes = P._conftest_files(proj / "tests" / "test_x.py", proj)
        check_eq("F4: the climb stops at the project: a conftest above it is not read, and no note is owed",
                 ([p.parent.name for p, _x in rows], cnotes), (["tests"], []))
        rows, _n = P._conftest_files(proj / "tests" / "test_x.py")
        check_eq("F4: without a project the climb is as before", len(rows), 2)
    finally:
        cleanup(repo)

    # -- the own file: a fixture the test does not ask for by argument is reached, and carries the door ---------------------
    root = temp_project("qa-s5-fx-own-")
    try:
        task = root / "qa-factory" / "artifacts" / "QA-600"
        task.mkdir(parents=True)
        (root / "tests" / "test_o.py").write_text(
            "import time\nimport pytest\n\n\n@pytest.fixture(autouse=True)\ndef settle():\n    time.sleep(1)\n\n\n"
            "@pytest.fixture\ndef inner():\n    time.sleep(1)\n\n\n@pytest.fixture\ndef outer(inner):\n    return 1\n\n\n"
            "@pytest.fixture\ndef direct():\n    time.sleep(1)\n\n\n"
            "def test_a(outer, direct):\n    assert True\n", encoding="utf-8")
        out, hints, notes, _calls = _smells(task, root, "tests/test_o.py", function="test_a")
        by_tag = {f["id"].split(":", 2)[2]: f for f in out}
        check_eq("own file: the autouse and the transitive fixture are found, the direct one too",
                 sorted(by_tag), ["sleep-test_o.py-direct", "sleep-test_o.py-inner", "sleep-test_o.py-settle"])
        check_eq("own file: all three are ADVICE, none carries a door (X7-2: advice blocks nothing)",
                 sorted((k, f["level"], bool(f.get("word_door"))) for k, f in by_tag.items()),
                 [("sleep-test_o.py-direct", "advice", False), ("sleep-test_o.py-inner", "advice", False),
                  ("sleep-test_o.py-settle", "advice", False)])
        check("own file: no `?` in any of them", not any("?" in f["fix"] for f in out))
    finally:
        cleanup(root)

    # -- the answers of the measure that are NOT `changed`: a hint and a note, never a finding, never silence -----------------
    root = temp_project("qa-s5-fx-unk-")
    try:
        task = root / "qa-factory" / "artifacts" / "QA-600"
        task.mkdir(parents=True)
        (root / "tests" / "conftest.py").write_text(
            "import time\nimport pytest\n\n\n@pytest.fixture\ndef waits():\n    time.sleep(2)\n", encoding="utf-8")
        (root / "tests" / "test_w.py").write_text("def test_w(waits):\n    assert True\n", encoding="utf-8")

        import test_novelty

        def measure_answers(value):
            return lambda *a, **k: [{"value": value, "basis": "canned", "base": {"kind": "s0", "sha": "a" * 40}, "measured_on": {}}]

        def measure_raises(*_a, **_k):
            raise RuntimeError("the measure fell over")
        saved = test_novelty.measure_many
        try:
            for label, replacement in (("`unknown`", measure_answers("unknown")), ("an exception inside the measure", measure_raises),
                                       ("a value outside the vocabulary", measure_answers("maybe")),
                                       ("an empty answer list", lambda *a, **k: [])):
                test_novelty.measure_many = replacement
                findings, hints, notes, _c = _smells(task, root, "tests/test_w.py")
                check_in(f"{label}: advice says the change could not be established",
                         "could not establish whether fixture `waits` changed; the code critic reads it",
                         "\n".join(h["message"] for h in findings))
                check_eq(f"{label}: it is the one advice and says it once", [h["level"] for h in findings], ["advice"])
                check_in(f"{label}: ... and so is a note", "could not establish whether fixture `waits` changed", "\n".join(notes))
        finally:
            test_novelty.measure_many = saved
        findings, hints, notes, _c = _smells(None, root, "tests/test_w.py")
        check_eq("task_root=None: no base to read -> one piece of advice", len(findings), 1)
        # the real measure with no S0 record and no repository: `unknown`, same road
        findings, hints, notes, _c = _smells(task, root, "tests/test_w.py")
        check_eq("no base at all (no record, no git): one piece of advice", len(findings), 1)
    finally:
        cleanup(root)

    # -- the closure: autouse, usefixtures, name=, nearer overrides farther, a circle, a fixture nobody asks for --------------
    root = temp_project("qa-s5-fx-clo-")
    try:
        task = root / "qa-factory" / "artifacts" / "QA-600"
        task.mkdir(parents=True)
        yes = ("yes", "new")
        (root / "tests" / "conftest.py").write_text(
            "import time\nimport pytest\n\n\n"
            "@pytest.fixture(autouse=True)\ndef auto_wait():\n    time.sleep(2)\n\n\n"
            "@pytest.fixture\ndef marked_wait():\n    time.sleep(2)\n\n\n"
            "@pytest.fixture(name=\"renamed\")\ndef _impl():\n    yield\n    time.sleep(2)\n\n\n"
            "@pytest.fixture\ndef nobody_asks():\n    time.sleep(2)\n\n\n"
            "@pytest.fixture\ndef polled():\n    for _ in range(30):\n        if ready():\n            break\n"
            "        time.sleep(1)\n\n\n"
            "@pytest.fixture\ndef x():\n    time.sleep(2)\n\n\n"
            "@pytest.fixture\ndef c1(c2):\n    return c2\n\n\n@pytest.fixture\ndef c2(c1):\n    time.sleep(2)\n", encoding="utf-8")
        (root / "tests" / "test_c.py").write_text(
            "import pytest\n\n\n"
            "@pytest.fixture\ndef x(x):\n    return x\n\n\n"
            "@pytest.mark.usefixtures(\"marked_wait\")\ndef test_marked():\n    assert True\n\n\n"
            "def test_renamed(renamed):\n    assert True\n\n\ndef test_poll(polled):\n    assert True\n\n\n"
            "def test_x(x):\n    assert True\n\n\ndef test_circle(c1):\n    assert True\n", encoding="utf-8")
        parsed, _p = P.read_python(root / "tests" / "test_c.py")

        def ids(function):
            out, notes = [], []
            P.check_smells("TC-1", "", [parsed], [(parsed, function, parsed.functions[function])], out, task, notes)
            return sorted(f["id"].split(":", 2)[2] for f in out)
        saved = P._fixture_changed
        P._fixture_changed = lambda *a: yes
        try:
            auto = "sleep-tests.conftest.py-auto_wait"
            check_eq("autouse: a conftest autouse fixture is in every test's closure", ids("test_poll"), [auto])
            check_eq("usefixtures: named on the function", ids("test_marked"), [auto, "sleep-tests.conftest.py-marked_wait"])
            check_eq("name=: the test asks for `renamed`, the finding names the function", ids("test_renamed"),
                     ["sleep-tests.conftest.py-_impl", auto])
            check_not_in("a fixture no test of the case reaches is not judged", "nobody_asks",
                         " ".join(ids("test_marked") + ids("test_renamed") + ids("test_poll") + ids("test_x")))
            check_not_in("AK3: a poll with a ceiling in a fixture is no finding", "polled", " ".join(ids("test_poll")))
            check_eq("def x(x): the nearer one asks for the farther one, which is judged; the circle ends",
                     ids("test_x"), [auto, "sleep-tests.conftest.py-x"])
            check_eq("a circle c1 <-> c2 ends, and the sleeper is found once", ids("test_circle"),
                     [auto, "sleep-tests.conftest.py-c2"])
        finally:
            P._fixture_changed = saved
    finally:
        cleanup(root)

    # -- the same file: as today (no `changed` question), plus the poll rule ---------------------------------------------------
    root = temp_project("qa-s5-fx-same-")
    try:
        task = root / "qa-factory" / "artifacts" / "QA-600"
        task.mkdir(parents=True)
        (root / "tests" / "test_s.py").write_text(
            "import time\nimport pytest\n\n\n@pytest.fixture\ndef own():\n    time.sleep(2)\n\n\n"
            "@pytest.fixture\ndef own_poll():\n    for _ in range(9):\n        if ready():\n            break\n        time.sleep(1)\n\n\n"
            "def test_own(own):\n    assert True\n\n\ndef test_poll(own_poll):\n    assert True\n", encoding="utf-8")
        for function, expected in (("test_own", ["sleep-test_s.py-own"]), ("test_poll", [])):
            parsed, _p = P.read_python(root / "tests" / "test_s.py")
            out, notes, calls = [], [], []
            saved = P._fixture_changed
            P._fixture_changed = lambda *a: (calls.append(a), ("no", ""))[1]
            try:
                P.check_smells("TC-1", "", [parsed], [(parsed, function, parsed.functions[function])], out, task, notes)
            finally:
                P._fixture_changed = saved
            check_eq(f"{function}: a fixture of the test's own file keeps today's id and needs no `changed`",
                     [f["id"].split(":", 2)[2] for f in out], expected)
            check_eq(f"{function}: ... and the measure is never asked", calls, [])
    finally:
        cleanup(root)

    # -- the chain: 5 levels are read, the 6th is not; the nearer conftest overrides; two conftests do not merge ---------------
    root = temp_project("qa-s5-fx-lvl-")
    try:
        task = root / "qa-factory" / "artifacts" / "QA-600"
        task.mkdir(parents=True)
        deep = root / "a" / "b" / "c" / "d" / "e"
        deep.mkdir(parents=True)
        sleeper = "import time\nimport pytest\n\n\n@pytest.fixture\ndef {n}():\n    time.sleep(2)\n"
        (root / "a" / "conftest.py").write_text(sleeper.format(n="lvl5"), encoding="utf-8")      # the 5th folder up: read
        (root / "conftest.py").write_text(sleeper.format(n="lvl6"), encoding="utf-8")            # the 6th: not read
        (deep / "test_d.py").write_text("def test_5(lvl5):\n    assert True\n\n\ndef test_6(lvl6):\n    assert True\n", encoding="utf-8")
        parsed, _p = P.read_python(deep / "test_d.py")
        saved = P._fixture_changed
        P._fixture_changed = lambda *a: ("yes", "new")
        try:
            out5, notes5 = [], []
            P.check_smells("TC-1", "", [parsed], [(parsed, "test_5", parsed.functions["test_5"])], out5, task, notes5)
            out6, notes6 = [], []
            P.check_smells("TC-1", "", [parsed], [(parsed, "test_6", parsed.functions["test_6"])], out6, task, notes6)
        finally:
            P._fixture_changed = saved
        check_eq("5 levels: the conftest of the 5th folder is read", [f["id"].split(":", 2)[2] for f in out5], ["sleep-a.conftest.py-lvl5"])
        check_eq("6 levels: the conftest of the 6th is NOT read", out6, [])
        check_in("... and the unread part is NAMED, not 'clean'", "conftest above a not read (5 levels)", "\n".join(notes6))
        check_in("... the same note at 5 (the climb stopped below the project root)", "not read", "\n".join(notes5))
        shallow = P._conftest_files(root / "tests" / "test_s.py", root)[1]
        check_eq("a climb that reached the project root names nothing", shallow, [])

        # an unparsable conftest: named with its path, nothing found, nothing raised
        broken = root / "tests" / "broken"
        broken.mkdir()
        (broken / "conftest.py").write_text("def (:\n", encoding="utf-8")
        (broken / "test_b.py").write_text("def test_b(any_fx):\n    assert True\n", encoding="utf-8")
        parsed, _p = P.read_python(broken / "test_b.py")
        out, notes = [], []
        P.check_smells("TC-1", "", [parsed], [(parsed, "test_b", parsed.functions["test_b"])], out, task, notes)
        check_eq("an unparsable conftest is no finding", out, [])
        check_in("... and a note names it, with its path and the reason", "tests/broken/conftest.py does not parse as Python", "\n".join(notes))

        # two conftest.py with the same fixture name in two folders: two findings (the ids carry the path)
        for sub in ("p", "q"):
            (root / "tests" / sub).mkdir()
            (root / "tests" / sub / "conftest.py").write_text(sleeper.format(n="waiter"), encoding="utf-8")
            (root / "tests" / sub / f"test_{sub}.py").write_text(f"def test_{sub}(waiter):\n    assert True\n", encoding="utf-8")
        both, targets = [], []
        for sub in ("p", "q"):
            parsed, _p = P.read_python(root / "tests" / sub / f"test_{sub}.py")
            both.append(parsed)
            targets.append((parsed, f"test_{sub}", parsed.functions[f"test_{sub}"]))
        out = []
        P._fixture_changed, saved = (lambda *a: ("yes", "new")), P._fixture_changed
        try:
            P.check_smells("TC-1", "", both, targets, out, task, [])
        finally:
            P._fixture_changed = saved
        check_eq("two conftest.py: two findings, ids with the path", sorted(f["id"].split(":", 2)[2] for f in out),
                 ["sleep-tests.p.conftest.py-waiter", "sleep-tests.q.conftest.py-waiter"])
        check_eq("... and `run`'s dedup (the id) keeps both", len({f["id"] for f in out}), 2)

        # a nearer conftest overrides the farther one: the NEAR one is judged
        (root / "tests" / "near").mkdir()
        (root / "tests" / "near" / "conftest.py").write_text("import pytest\n\n\n@pytest.fixture\ndef lvl_far():\n    return 1\n", encoding="utf-8")
        (root / "conftest.py").write_text(sleeper.format(n="lvl_far"), encoding="utf-8")
        (root / "tests" / "near" / "test_n.py").write_text("def test_n(lvl_far):\n    assert True\n", encoding="utf-8")
        parsed, _p = P.read_python(root / "tests" / "near" / "test_n.py")
        out = []
        P._fixture_changed, saved = (lambda *a: ("yes", "new")), P._fixture_changed
        try:
            P.check_smells("TC-1", "", [parsed], [(parsed, "test_n", parsed.functions["test_n"])], out, task, [])
        finally:
            P._fixture_changed = saved
        check_eq("the nearer conftest wins: it has no sleep, the farther one is not judged", out, [])
    finally:
        cleanup(root)

    # -- through `run`: the hint reaches the result, the window is not blocked by it ---------------------------------------------
    root = temp_project("qa-s5-fx-run-")
    try:
        manifest = {"tests": [{"instance_id": "test_status_ok", "case": "TC-500", "covers": ["TC-500"],
                               "file": "tests/test_validate.py", "test_function": "test_status_ok"}]}
        task = make_story(root, manifest)
        (root / "tests" / "conftest.py").write_text(
            "import time\nimport pytest\n\n\n@pytest.fixture\ndef client():\n    time.sleep(2)\n", encoding="utf-8")
        result = P.run(task)
        check_in("run: the plumbing hands `check_smells` the story root and the notes: a piece of advice comes out",
                 "could not establish whether fixture `client` changed", "\n".join(h["message"] for h in result["advice"]))
        check_not_in("run: ... and the conftest sleep is no finding", "tests/conftest.py: `client`",
                     "\n".join(f["message"] for f in result["findings"]))
    finally:
        cleanup(root)


def a_new_helper_is_asked_for_its_trail_to_the_analogue() -> None:
    """TQ1-7 (D1-K1/K2/K5, D1-4, D1-5): a row of `introduced_helpers[]` with no `searched` / `similar_found`, and a method that
    shares a word with another method of its class, give a HINT (never a finding: `ok` does not move). A filled row with no
    sibling gives none; an old manifest without the key, a Java layout with no conftest and no Python, a row that is not an
    object: no crash, no hint, a note where something could not be read. Killing test of M-D1-3 (a hint put into findings)."""
    root = temp_project("qa-s5-helper-")
    try:
        (root / "tests").mkdir(exist_ok=True)
        (root / "tests" / "pages.py").write_text(
            "class PO:\n    def read_editor_yaml(self):\n        return 1\n\n    def read_yaml(self):\n        return 2\n\n"
            "    def click_save(self):\n        return 3\n\n\ndef make_thing():\n    return 4\n", encoding="utf-8")
        base = {"tests": [{"instance_id": "test_status_ok", "case": "TC-500", "covers": ["TC-500"],
                           "file": "tests/test_validate.py", "test_function": "test_status_ok"}]}
        task = make_story(root, dict(base))
        without = P.run(task)
        rows = [{"file": "tests/pages.py", "name": "PO.read_editor_yaml", "purpose": "", "searched": "", "similar_found": "",
                 "keep": "", "novelty": "new"},
                {"file": "tests/pages.py", "name": "PO.click_save", "purpose": "saves", "searched": "tests/", "similar_found": "none",
                 "keep": "", "novelty": "new"},
                {"file": "tests/pages.py", "name": "make_thing", "purpose": "", "searched": "tests/", "similar_found": "",
                 "keep": "", "novelty": "changed"}]
        hints: list = []
        P.helper_twin_hint({"introduced_helpers": rows}, hints, task, [])
        said = {h["message"].split("`")[1]: h for h in hints}
        check_eq("K1: the empty row and the half-empty row are named, the filled row with no sibling is not",
                 sorted(said), ["PO.read_editor_yaml", "make_thing"])
        check_in("K1: the method names the sibling that shares a word with it (read_yaml), not the one that does not",
                 "`read_yaml`", said["PO.read_editor_yaml"]["message"])
        check_not_in("K1: ... and not click_save", "click_save", said["PO.read_editor_yaml"]["message"])
        check_in("K1: the empty fields are named", "`searched, similar_found`", said["PO.read_editor_yaml"]["message"])
        check_in("K1: a half-empty row names its empty field", "`similar_found` of its", said["make_thing"]["message"])
        check_eq("D1-5: every one is a hint", {h["level"] for h in hints}, {"hint"})
        check_in("K1: the fix names the door", "manifest_put.py", said["PO.read_editor_yaml"]["fix"])
        # through `run`: the hint reaches the result, `ok` does not move, the findings stay as they were
        C.artifact(task, "automation-manifest.json").write_text(
            json.dumps(dict(base, introduced_helpers=rows)), encoding="utf-8")
        with_rows = P.run(task)
        check("D1-5: through `run` the hints come out", any("PO.read_editor_yaml" in h["message"] for h in with_rows["hints"]),
              str([h["message"] for h in with_rows["hints"]]))
        check_eq("D1-5: `ok` and the findings are those of the manifest without the key",
                 (with_rows["ok"], [f["id"] for f in with_rows["findings"]]),
                 (without["ok"], [f["id"] for f in without["findings"]]))
        # D1-2: an old manifest (no key), a key that is no list, rows that are no objects
        for odd in ({}, {"introduced_helpers": None}, {"introduced_helpers": "x"}, {"introduced_helpers": [None, 3, "x", {}]}):
            out: list = []
            P.helper_twin_hint(odd, out, task, [])
            check_eq(f"D1-2: {str(odd)[:40]} gives no hint and no crash", out, [])
        P.helper_twin_hint(None, [], task, [])
        # D1-4: a Java layout - no Python, no conftest: a note, not a hint on the class, no crash
        notes: list = []
        out = []
        P.helper_twin_hint({"introduced_helpers": [{"file": "src/test/java/EditorPage.java", "name": "EditorPage.readYaml",
                                                    "purpose": "p", "searched": "s", "similar_found": "none", "novelty": "new"}]},
                           out, task, notes)
        check_eq("D1-4: a filled Java row gives no hint", out, [])
        check("D1-4: and says it did not read the methods beside it (not a clean bill)",
              any("EditorPage.java" in n and "not read" in n for n in notes), str(notes))
        out = []
        P.helper_twin_hint({"introduced_helpers": [{"file": "src/test/java/EditorPage.java", "name": "EditorPage.readYaml",
                                                    "novelty": "unknown"}]}, out, task, [])
        check_eq("D1-4: an empty Java row still gets the trail hint", len(out), 1)
    finally:
        cleanup(root)


COPY_PAGES = ("def make_user(client, name):\n    data = {'name': name, 'role': 'user'}\n    reply = client.post('/users', data)\n"
              "    return reply.json()['id']\n\n\n"
              "def test_first(api):\n    r = api.get('/a')\n    assert r.status_code == 200\n    assert r.json()['k'] == 1\n")
COPY_MORE = ("def create_account(api, title):\n    payload = {'name': title, 'role': 'admin'}\n    answer = api.post('/accounts', payload)\n"
             "    return answer.json()['id']\n\n\n"
             "def test_second(api):\n    s = api.get('/b')\n    assert s.status_code == 404\n    assert s.json()['k'] == 2\n")


def copy_story(root: Path, rows=None, extra_tests=()) -> tuple:
    (root / "tests").mkdir(exist_ok=True)
    (root / "tests" / "pages.py").write_text(COPY_PAGES, encoding="utf-8")
    (root / "tests" / "more.py").write_text(COPY_MORE, encoding="utf-8")
    manifest = {"tests": [{"instance_id": "test_first", "case": "TC-500", "covers": ["TC-500"], "file": "tests/pages.py",
                           "test_function": "test_first"},
                          {"instance_id": "test_second", "case": "TC-500", "covers": ["TC-500"], "file": "tests/more.py",
                           "test_function": "test_second"}, *extra_tests]}
    if rows is not None:
        manifest["introduced_helpers"] = rows
    return make_story(root, manifest), manifest


def copies_of(task, manifest, novelty="new", **kw) -> tuple:
    """`(helper copies, test-body copies, notes)`: X7-2 puts every copy into ONE advice list; the two views are the helper/fixture
    copies (what was a finding) and the `test*` body copies (what was a hint), told apart by the message."""
    advice, notes = [], []
    P.check_copies(task, manifest, advice, notes, novelty=lambda tops: [novelty] * len(tops), **kw)
    tests = [a for a in advice if "code critic judges whether one parametrized test" in a["message"]]
    return [a for a in advice if a not in tests and not _soft_copy(a)], [a for a in advice if a in tests or _soft_copy(a)], notes


def _soft_copy(entry: dict) -> bool:
    """A copy advice that says why it is softer: a repair round of S7, an unplaced novelty, a stated `keep`, the file limit."""
    return any(part in entry["message"] for part in ("a repair round of S7", "could not be established", "says why it is kept",
                                                       "beyond the limit"))


def a_copy_of_existing_code_is_advice_for_the_critic() -> None:
    """TQ1-19 (D2-K1..K9, D2-1..D2-5, D2-7), X7-2: a helper that repeats another under other names is ADVICE that names the existing
    one; a `test*` body, a `keep` of its scaffold row, a repair round of S7 and an `unknown` novelty make it a softer piece of advice;
    `unchanged` code gives nothing; the file limit and a broken table are named. NOTHING blocks: `ok` stays True and no door exists.
    Kills M-D2-3 (`keep` read as truth without strip), M-D2-4 (the advice is a finding)."""
    root = temp_project("qa-s5-copy-")
    try:
        task, manifest = copy_story(root)
        findings, hints, notes = copies_of(task, manifest)
        check_eq("K1: ONE advice for the helper (the new one repeats `make_user`); the pair is not reported twice",
                 [f["id"] for f in findings], ["smell:-:copy-tests.more.py-create_account"])
        finding = findings[0]
        check_eq("K1: advice with no door", (finding["level"], finding.get("word_door")), ("advice", None))
        check_in("K1: the message names the existing code and where", "`make_user` (tests/pages.py:1)", finding["message"])
        check_in("K1: the fix says what to do", "call or extend `make_user`", finding["fix"])
        check_not_in("advice blocks nothing, so it names no door", "the person's word", finding["fix"])
        check_not_in("Q-1 (c): no row, no promise of `keep`", "keep", finding["fix"])
        check_eq("K3 (F-16 a): the `test*` body is advice that says it reads like its neighbours",
                 [h["id"] for h in hints], ["smell:-:copy-tests.more.py-test_second"])
        check_in("... that the critic reads", "code critic judges", hints[0]["message"])
        check_not_in("the old exact-twin tag is gone", "dup-helper", json.dumps(findings + hints))

        # the keep door lives on the scaffold row of a helper, new or changed (Q-1 c, F-9)
        row = {"file": "tests/more.py", "name": "create_account", "purpose": "", "searched": "", "similar_found": "", "keep": "",
               "novelty": "new"}
        findings, hints, notes = copies_of(task, manifest | {"introduced_helpers": [row]})
        check_in("a NEW helper with a scaffold row is told about `keep`", "`keep` of its `introduced_helpers[]` row", findings[0]["fix"])
        findings, hints, notes = copies_of(task, manifest | {"introduced_helpers": [row]}, novelty="changed")
        check_eq("a CHANGED helper is still a finding ...", len(findings), 1)
        check_in("F-9: ... and its fix names `keep`: the code honours it on any row, so the door is shown on any row",
                 "`keep` of its `introduced_helpers[]` row", findings[0]["fix"])
        # D2-K8a: the door works end to end for a `changed` row - the role's `keep` goes through the REAL fragment merge
        import manifest_put as MP
        scaffold = dict(row, novelty="changed")
        merged, _summary = MP.merge({"introduced_helpers": [scaffold]}, {"introduced_helpers": [
            {"file": "tests/more.py", "name": "create_account", "keep": "the admin API takes another auth"}]})
        findings, hints, notes = copies_of(task, manifest | {"introduced_helpers": merged["introduced_helpers"]}, novelty="changed")
        check_eq("D2-K8a: a `keep` written through the real merge lifts the finding of a CHANGED helper", findings, [])
        for blank in ("", "   ", "\n\t "):
            findings, hints, notes = copies_of(task, manifest | {"introduced_helpers": [dict(row, keep=blank)]})
            check_eq(f"D2-K9 / M-D2-3: a blank `keep` ({blank!r}) leaves the finding", len(findings), 1)
        findings, hints, notes = copies_of(task, manifest | {"introduced_helpers": [dict(row, keep="the admin API takes another auth")]})
        check_eq("D2-K8: a non-blank `keep` lifts the finding ...", findings, [])
        check_in("... and the hint stays, for the critic", "its `introduced_helpers[]` row says why it is kept",
                 "\n".join(h["message"] for h in hints))
        findings, hints, notes = copies_of(task, manifest | {"introduced_helpers": ["x", None, {"file": 3}]})
        check_eq("a row that is no object / has no name: no crash, the finding stands", len(findings), 1)

        findings, hints, notes = copies_of(task, manifest, s7_round=True)
        check_eq("D2-7 / M-D2-4: in an S7 repair round the copy is a hint, never a finding", (findings, len(hints)), ([], 2))
        findings, hints, notes = copies_of(task, manifest, novelty="unknown")
        check_eq("D2-3: an `unknown` novelty is a hint ...", (findings, len(hints)), ([], 2))
        check("... and a note, not silence", any("could not be placed as new or unchanged" in n for n in notes), str(notes))
        findings, hints, notes = copies_of(task, manifest, novelty="unchanged")
        check_eq("K7: copy between code the story did not touch: nothing", (findings, hints), ([], []))

        # D2-1: the file limit; D2-2: the table
        table = root / "limits.json"
        table.write_text(json.dumps({"copy_detector": {"min_function_statements": 3, "fragment_window": 3, "max_files": 1}}),
                         encoding="utf-8")
        findings, hints, notes = copies_of(task, manifest, limits_path=table)
        check("D2-1 BEYOND the limit: the file left out is named in a note and a hint (not silence)",
              any("beyond the limit of 1" in n for n in notes) and any(h["id"].endswith("copy-limit") for h in hints), str(notes))
        table.write_text("{broken", encoding="utf-8")
        findings, hints, notes = copies_of(task, manifest, limits_path=table)
        check("D2-2: a broken table: a note, the defaults, the gate still refuses",
              any("cannot be read" in n for n in notes) and len(findings) == 1, str(notes))

        # D2-4 / D2-5: no rows; a file that is not Python
        check_eq("D2-5: a manifest with no rows: nothing, no note", copies_of(task, {})[::2], ([], []))
        check_eq("D2-5: `tests: []`: nothing", copies_of(task, {"tests": []})[::2], ([], []))
        (root / "tests" / "Page.java").write_text("class Page {}\n", encoding="utf-8")
        java = manifest | {"tests": manifest["tests"] + [{"instance_id": "t", "case": "TC-500", "file": "tests/Page.java"}]}
        findings, hints, notes = copies_of(task, java)
        check("D2-4: a file that is not Python is a note, the Python files are still checked",
              any("Page.java is not a Python file" in n for n in notes) and len(findings) == 1, str(notes))
        (root / "tests" / "more.py").write_text("def broken(:\n", encoding="utf-8")
        findings, hints, notes = copies_of(task, manifest)
        check("D2-4: a file that does not parse is a note, no crash", findings == [] and any("not parsed" in n for n in notes), str(notes))
        (root / "tests" / "more.py").write_text(COPY_MORE, encoding="utf-8")

        # through `run`: the copy reaches the result as ADVICE and `ok` does not move; the advice block carries it (X7-2)
        real = P._copy_novelty
        P._copy_novelty = lambda _task, _project: (lambda tops: ["new"] * len(tops))
        try:
            ran = P.run(task)
            tag = "copy-tests.more.py-create_account"
            check("D2-K2: through `run` the helper copy is ADVICE, never a finding",
                  any(f["id"].endswith(tag) for f in ran["advice"]) and not any("copy-" in f["id"] for f in ran["findings"]),
                  str([f["id"] for f in ran["advice"]]))
            block = P.advice_block(ran)
            check("X7-2: ... and the ADVICE block names it, one `- ` line per piece, the count in the header",
                  block[0] == f"ADVICE — {len(block) - 1}" and all(line.startswith("- ") for line in block[1:])
                  and any(tag in line for line in block[1:]), str(block))
            check_eq("X7-2: a result with no advice prints no block", P.advice_block({"advice": []}), [])
        finally:
            P._copy_novelty = real
        # the REAL measurer in a project with no git: `unknown`, so advice and a note, never a finding (D2-3 through `run`)
        no_base = P.run(task)
        check("D2-3: with no story base the real measurer cannot tell: no finding, advice, a note",
              not any("copy-" in f["id"] for f in no_base["findings"])
              and any("copy-" in h["id"] for h in no_base["advice"]) and any("could not be placed" in n for n in no_base["notes"]),
              str(no_base["notes"][-3:]))
    finally:
        cleanup(root)


REL_HEAD = "def _o(api):\n    return ('http', api.status)\n\n\n"
REL_ACT = "    api.move()\n"


def rel_run(root: Path, name: str, body: str, novelty="new", extra_files=None, **kw) -> tuple:
    """`(findings, hints, notes)` of `check_relative_oracle` over the one test `body` (a function named `test_x`)."""
    task = root / "qa-factory" / "artifacts" / "QA-500"
    if not task.exists():
        make_story(root, {"tests": []})
    path = root / "tests" / f"{name}.py"
    path.write_text(REL_HEAD + body, encoding="utf-8")
    for rel, text in (extra_files or {}).items():
        (root / rel).write_text(text, encoding="utf-8")
    parsed, _problem = P.read_python(path)
    targets = [(parsed, n, node) for n, node in parsed.functions.items()]
    advice, notes = [], []
    P.check_relative_oracle("TC-500", "", targets, advice, task, notes, novelty=lambda tops: [novelty] * len(tops), **kw)
    return advice, [], notes        # X7-2: what was a finding (or a hint in an S7 round) is ADVICE for the code critic


def a_relative_oracle_on_an_unasserted_base_is_refused() -> None:
    """TQ1-18 (D3-K1..K10, K14, D3-1..D3-6): a value taken before an action and compared after it, with nothing asking the base to be
    a working answer, is a FINDING with a word door; a base asserted above the comparison, a helper, a `base_checked` marker naming an
    existing function and `before + 1` are clean. Kills M-D3-1 (structure dropped: `structure_pair`), M-D3-2 (tokens dropped:
    `fixture_arg`, `other_function`), M-D3-3 (an assert AFTER the comparison counts: `checked_after`), M-D3-4 (the call inside
    `if text`: the empty-case run below), M-D3-6 (`base_checked` not looked up: `unknown_function`)."""
    import ast as _ast
    nested = _ast.parse("assert_that(after, is_(equal_to(before)))").body[0].value
    check_eq("the right fix of `_compared_values`: a nested matcher is unwrapped to its value, every level",
             [v.id for v in P._compared_values(nested)], ["after", "before"])
    pair = "    before = _o(api)\n" + REL_ACT + "    after = _o(api)\n"
    cases = {
        "sample": (pair + "    assert_that(after, equal_to(before))\n", 1),
        "eq_order": (pair + "    assert after == before\n", 1),
        "swapped": (pair + "    assert before == after\n", 1),
        "nested": (pair + "    assert_that(after, is_(equal_to(before)))\n", 1),
        "attribute": ("    before = _o(api)\n" + REL_ACT + "    after = _o(api)\n    assert after.status == before.status\n", 1),
        "structure_pair": ("    first = _o(api)\n" + REL_ACT + "    second = _o(api)\n    assert second == first\n", 1),
        "other_function": ("    x_before = _o(api)\n" + REL_ACT + "    now = _p(api)\n    assert now == x_before\n", 1),
        "fixture_arg": ("def test_x(api, before_state):\n" + REL_ACT + "    now = _o(api)\n    assert now == before_state\n", 1),
        "truthy_is_no_check": (pair.replace("    api.move()\n", "    assert before\n    api.move()\n")
                               + "    assert after == before\n", 1),
        "none_is_no_check": (pair.replace("    api.move()\n", "    assert before is not None\n    api.move()\n")
                             + "    assert after == before\n", 1),
        "checked": (pair.replace("    api.move()\n", "    assert_that(before[0], equal_to('ok'))\n    api.move()\n")
                    + "    assert_that(after, equal_to(before))\n", 0),
        "checked_by_helper": (pair.replace("    api.move()\n", "    assert_ok(before)\n    api.move()\n")
                              + "    assert after == before\n", 0),
        "checked_after": (pair + "    assert after == before\n    assert_that(before[0], equal_to('ok'))\n", 1),
        "plus_one": ("    before = len(api.items)\n" + REL_ACT + "    after = len(api.items)\n    assert after == before + 1\n", 0),
        "mask": (pair + "    assert after[1] == '******'\n", 0),
        "no_action_between": ("    first = _o(api)\n    second = _o(api)\n    assert second == first\n", 0),
        # F-2: the other side of the comparison is a call (no `after` variable), or a plain call wraps either side
        "call_vs_base": ("    before = _o(api)\n" + REL_ACT + "    assert _o(api) == before\n", 1),
        "call_hamcrest": ("    before = _o(api)\n" + REL_ACT + "    assert_that(_o(api), equal_to(before))\n", 1),
        "len_of_calls": ("    before = _o(api)\n" + REL_ACT + "    assert len(_o(api)) == len(before)\n", 1),
        "sorted_names": (pair + "    assert sorted(after) == sorted(before)\n", 1),
        "set_matcher": (pair + "    assert_that(set(after), equal_to(set(before)))\n", 1),
        "tuple_unpack": ("    a, b = _o(api)\n" + REL_ACT + "    x, y = _o(api)\n    assert a == x\n", 1),
        "matcher_is_no_value": ("    before_items = _o(api)\n    assert_that(before_items, is_(has_length(3)))\n", 0),
        "literal_is_a_base_check": ("    before = _o(api)\n    assert before == ('http', 200)\n", 0),
        # F-3: a SHAPE of the base is no proof it is a working answer (the owner's refusal is a tuple of two too)
        "shape_isinstance": (pair.replace(REL_ACT, "    assert isinstance(before, tuple)\n" + REL_ACT) + "    assert after == before\n", 1),
        "shape_len": (pair.replace(REL_ACT, "    assert len(before) == 2\n" + REL_ACT) + "    assert after == before\n", 1),
        "shape_has_length": (pair.replace(REL_ACT, "    assert_that(before, has_length(2))\n" + REL_ACT) + "    assert after == before\n", 1),
        "shape_not": (pair.replace(REL_ACT, "    assert not before\n" + REL_ACT) + "    assert after == before\n", 1),
        "shape_len_matcher": (pair.replace(REL_ACT, "    assert_that(len(before), equal_to(2))\n" + REL_ACT) + "    assert after == before\n", 1),
        "value_index_counts": (pair.replace(REL_ACT, "    assert before[0] == 'http'\n" + REL_ACT) + "    assert after == before\n", 0),
        "value_attribute_counts": (pair.replace(REL_ACT, "    assert before.status == 200\n" + REL_ACT) + "    assert after == before\n", 0),
        "literal_equality_counts": (pair.replace(REL_ACT, "    assert before == ('http', 200)\n" + REL_ACT) + "    assert after == before\n", 0),
    }
    root = temp_project("qa-s5-rel-")
    try:
        for name, (body, expected) in cases.items():
            text = body if body.startswith("def ") else "def test_x(api):\n" + body
            findings, hints, notes = rel_run(root, f"t_{name}", text)
            check_eq(f"{name}: {expected} finding(s)", len(findings), expected)
            if expected:
                finding = findings[0]
                check_eq(f"{name}: tag, family, ADVICE with no door (it blocks nothing)",
                         (finding["id"].startswith("oracle:TC-500:relative-oracle-t_"), finding["check"], finding["level"],
                          finding.get("word_door")), (True, "oracle", "advice", None))
                check_in(f"{name}: the fix names the test's own marker", "base_checked", finding["fix"])
                check_not_in(f"{name}: no person's-word door in advice", "the person's word", finding["fix"])
                check(f"{name}: the message never reads an empty name", "``" not in finding["message"], finding["message"])
                if name == "call_vs_base":
                    check_in("F-2: the call is rendered as its source text", "`_o(api)`", finding["message"])
        # the test's own door: a marker naming a function that exists is clean, one that does not is a finding that says why
        mark = "@pytest.mark.qa(case='TC-500', base_checked='%s')\ndef test_x(api):\n" + pair + "    assert after == before\n"
        helper = {"tests/chk.py": "def check_base(api):\n    assert api.ok\n"}
        findings, _h, _n = rel_run(root, "t_door_ok", mark % "tests/chk.py::check_base", extra_files=helper)
        check_eq("D3-K10: `base_checked` on an existing function is clean", findings, [])
        findings, _h, _n = rel_run(root, "t_door_bad", mark % "tests/chk.py::nope", extra_files=helper)
        check_eq("D3-K10 (M-D3-6): on a function that is not there the finding stays", len(findings), 1)
        check_in("... and says why", "does not count", findings[0]["message"])
        # D3-3: only the story's own tests; `unknown` is judged as changed and said; D3-6: an S7 round hints
        body = "def test_x(api):\n" + pair + "    assert after == before\n"
        findings, _h, notes = rel_run(root, "t_old", body, novelty="unchanged")
        check_eq("D3-3: an unchanged test of the file is not paid for", (findings, notes), ([], []))
        findings, _h, notes = rel_run(root, "t_unk", body, novelty="unknown")
        check("D3-3: `unknown` is a finding and a note", len(findings) == 1 and any("could not tell whether" in n for n in notes), str(notes))
        findings, _h, _n = rel_run(root, "t_s7", body, s7_round=True)
        check("D3-6: in an S7 round the advice says the window and the critic already saw it",
              len(findings) == 1 and "a repair round of S7" in findings[0]["message"], str(findings))
        # D3-K14: no `baseline_names` key: a note, the structural pair still judged, the token alone not
        bare = root / "no-detectors.json"
        bare.write_text("{}", encoding="utf-8")
        findings, _h, notes = rel_run(root, "t_nokey_pair", "def test_x(api):\n    first = _o(api)\n" + REL_ACT
                                      + "    second = _o(api)\n    assert second == first\n", detectors_path=bare)
        check("D3-K14: the pair works without the key, and the note says what is not judged",
              len(findings) == 1 and any("baseline_names" in n for n in notes), str(notes))
        findings, _h, notes = rel_run(root, "t_nokey_token", "def test_x(api, before_state):\n" + REL_ACT
                                      + "    now = _o(api)\n    assert now == before_state\n", detectors_path=bare)
        check_eq("D3-K14: a token alone is not judged without the key", findings, [])
    finally:
        cleanup(root)
    # D3-4 (M-D3-4): a story with NO case file is still judged, through `run`, never switched off by an empty text
    root = temp_project("qa-s5-rel-run-")
    try:
        task = make_story(root, {"tests": [{"instance_id": "test_x", "case": "TC-500", "covers": ["TC-500"],
                                            "file": "tests/t_run.py", "test_function": "test_x"}]})
        (root / "tests" / "t_run.py").write_text(REL_HEAD + "def test_x(api):\n" + pair + "    assert after == before\n",
                                                 encoding="utf-8")
        (task / "work" / "test-cases" / "TC-500.md").unlink()
        result = P.run(task)
        check("D3-4: the empty case text does not switch the gate off (the call is outside `if text`)",
              any("relative-oracle-" in f["id"] for f in result["advice"])
              and not any("relative-oracle-" in f["id"] for f in result["findings"]), str([f["id"] for f in result["advice"]]))
    finally:
        cleanup(root)


def a_then_row_does_not_swallow_the_thens_behind_a_red() -> None:
    """EP1-39 M-3 (AR-27): a `contradicts_requirement` row naming only Thens of a case that ran is not a whole-case row, so
    the `blocked_by_check` rows of that case stay in `then_remainder_rows` (the road EP1-38 sends the role down)."""
    blocked = {"case": "TC-009", "then": 3, "status": "unresolved", "reason": C.BLOCKED_BY_CHECK, "instance_id": "t[a]",
               "blocking_check": "TC-009", "detail": "check once the red is fixed"}
    then_row = {"case": "TC-009", "reason": "contradicts_requirement", "thens": [2], "detail": "d"}
    whole = {"case": "TC-009", "reason": "contradicts_requirement", "detail": "d"}
    both = C.THEN_REMAINDER_REASONS
    check_eq("M-3: the Then row (thens [2], no slice) leaves the case's blocked row in the list",
             C.then_remainder_rows({"unresolved": [then_row], "then_bindings": [blocked]}, reasons=both), [blocked])
    check_eq("M-3: a whole-case row (no thens) still ends the case's remainders",
             C.then_remainder_rows({"unresolved": [whole], "then_bindings": [blocked]}, reasons=both), [])
    check_eq("M-3: a `thens: []` row is a whole-case row, as today",
             C.then_remainder_rows({"unresolved": [dict(then_row, thens=[])], "then_bindings": [blocked]}, reasons=both), [])
    check_eq("M-3: a Then row beside a whole-case row of the same case: the whole one ends them",
             C.then_remainder_rows({"unresolved": [then_row, whole], "then_bindings": [blocked]}, reasons=both), [])
    check_eq("M-3: the default call still lists the hand-off rows only",
             C.then_remainder_rows({"unresolved": [then_row], "then_bindings": [blocked]}), [])
    check_eq("M-3: and the pooled check of `manifest_put` judges it (the row is well formed -> no problem)",
             M.then_remainder_problems(Path("/nonexistent-root"), {"then_bindings": [blocked], "unresolved": [then_row]}), [])


def main() -> None:
    a_then_row_does_not_swallow_the_thens_behind_a_red()
    a_relative_oracle_on_an_unasserted_base_is_refused()
    a_copy_of_existing_code_is_advice_for_the_critic()
    a_new_helper_is_asked_for_its_trail_to_the_analogue()
    a_sleep_in_the_fixtures_of_a_test_is_the_windows_code_only_when_it_changed()
    a_then_behind_its_own_red_is_named()
    a_then_ref_is_checked_against_its_own_areas_case_file()
    a_missing_case_file_says_where_it_looked()
    a_soft_red_does_not_stop_the_test()
    failure_frames_walk_every_frame()
    an_unresolved_row_is_found_by_the_qualified_scope_case()
    a_qualified_ask_finds_the_binding_rows_that_name_it()
    a_qualified_scope_case_binds_its_obligation()
    check_manifest_sees_the_qualified_scope_case()
    the_merged_record_keeps_its_note()
    the_refusal_prints_the_pairs_own_door_or_none()
    a_broad_word_covers_only_what_existed()
    the_could_not_judge_road_is_said_the_same_everywhere()
    a_retired_red_is_not_cleared_by_the_same_bytes()
    a_word_marks_the_pair_it_names_and_the_pair_stays_visible()
    a_verdict_takes_its_note_with_it()
    could_not_judge_needs_its_note()
    the_printed_door_runs()
    a_word_for_another_finding_does_not_pass_it()
    the_detector_lives_in_run_history()
    the_three_silent_passes_are_owed_pairs()
    a_long_path_is_not_an_unreadable_report()
    the_verdict_follows_the_authors_words()
    a_verdict_patch_finds_its_record()
    the_cmp1_shape_is_found()
    the_sha_chain_decides_same_or_changed()
    the_reused_function_lands_on_the_safe_side()
    several_reds_and_a_change_that_was_undone()
    a_reparse_is_ordered_by_time_not_by_name()
    a_red_is_confirmed_by_its_own_report()
    an_orphaned_red_and_a_test_handed_over_red()
    pairs_of_another_stage_are_listed_not_owed()
    a_record_answers_the_finding()
    a_bad_then_ref_is_a_finding()
    one_record_may_name_several_functions()
    a_persons_word_passes_this_finding_only()
    the_judge_may_not_downgrade_it()
    the_open_oracle_gate_is_never_judged()
    the_phrase_list_is_gone()
    open_oracle_asserted_is_a_repair_with_a_door()
    open_oracle_asserted_errs_toward_firing()
    no_word_passes_the_open_oracle_gate()
    a_test_written_to_the_owners_norm_is_not_refused()
    a_measurement_error_is_unmeasured_not_a_crash()
    the_fragment_battery()
    identity()
    manifest_invariants()
    validator_names_the_command()
    precheck_findings()
    one_instance_may_prove_several_cases()
    the_automator_chooses_the_shape()
    a_contradicted_requirement_has_an_outcome()
    a_blocked_instance_is_the_third_allowed_shape()
    a_green_is_compared_with_its_own_slice()
    the_approved_case_is_the_oracle()
    the_oldest_manifest_row_is_named()
    precheck_is_project_agnostic()
    precheck_cli()
    batched_schedule()
    sandbox()
    the_verdict_is_one_line_per_finding()
    request_template_is_complete()
    probe_publication_reads_the_author_record()
    red_probe_holds_the_dashboard()
    a_measured_number_is_not_a_status()
    finish("test_s5_precheck")


if __name__ == "__main__":
    main()
