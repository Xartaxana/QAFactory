#!/usr/bin/env python3
"""manifest_from_tests.py: the fragment is built from the markers, never typed.

A temp project the way test_story_step.py builds one, with a story that has pinned case
links, a plan with obligations, a controller dispatch with a scope, one run block, and a
manifest another window already wrote. What is proved:
  * a plain function, a parametrized one, pytest.param marks in a data module, class-based
    tests, a module-level `qa_unresolved` — each lands as the contract's row shape
  * `obligations` are checked against the case's plan row and hashed the plan's way
  * `then_bindings` rows of another window survive the merge; rows about this window's
    instances are replaced
  * the status of an instance comes from the run block, not from the marker
  * an obligation not on the plan row, a case outside the scope, an unknown keyword — each
    is a refusal that names the line and the fix
  * a second identical run changes nothing (manifest_put's idempotency key)
  * B-207 piece P5-D (the switch): every row carries the measured `novelty` and `generated_from`,
    one `measure_many` call per build, one measurement per function; against a base that is not a
    recorded S0 record only `new`/`changed` are stored (V2); the time the measure adds is bounded
    (V3); a dry run writes nothing. The git repositories are built under the OS temp dir.
"""
import contextlib
import copy
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import check, check_eq, check_in, check_not_in  # noqa: E402

# The repositories built here must not read this machine's git configuration.
os.environ["GIT_CONFIG_GLOBAL"] = os.devnull
os.environ["GIT_CONFIG_NOSYSTEM"] = "1"
os.environ["GIT_AUTHOR_NAME"] = os.environ["GIT_COMMITTER_NAME"] = "tester"
os.environ["GIT_AUTHOR_EMAIL"] = os.environ["GIT_COMMITTER_EMAIL"] = "tester@example.com"

sys.path.insert(0, str(harness.SCRIPTS))
import contract as C  # noqa: E402
from event_store import content_hash  # noqa: E402

TICKET = "QA-700"
DISPATCH = "S5-qa-automator-1"

CASE_MD = """---
id: {cid}
title: {cid}
area: coupon
priority: P1
status: Draft
channel: auto
reuse_decision: new
updated: 2026-09-24
task: QA-700
plan_row: {row}
---

Requirements: R-{n}
Plan row: {row}

## Given
Partitions: P-empty, P-full.

## When
Call the client.

## Then
1. The body carries `status_ok`.
2. The `count` is one.
3. The `items` list matches the partition.
"""

TEST_PY = '''"""Coupon tests."""
import pytest
from tests.data_coupon import LIMIT_CASES

pytestmark = [pytest.mark.qa_unresolved(case="TC-004", reason="impossible",
                                        detail="no black-box channel reads the cache")]


@pytest.mark.qa(case="TC-001", then=[1, 2], obligations=["TS-1-O1"], note="one call, two reads")
def test_limit(client):
    body = client.get()
    assert body["status_ok"] is True
    assert body["count"] == 1


@pytest.mark.qa(case="TC-002", then=[1])
@pytest.mark.parametrize("region", ["eu", "us"])
def test_region(client, region):
    assert client.region(region) == region


@pytest.mark.parametrize("value, expected", LIMIT_CASES)
def test_from_data(client, value, expected):
    assert client.limit(value) == expected


class TestGroup:
    @pytest.mark.qa(case="TC-003", then=[1], partition="P-empty")
    def test_empty(self, client):
        assert client.items() == []

    @pytest.mark.qa(case="TC-003", then={3: "40-41"})
    def test_full(self, client):
        with pytest.raises(ValueError):
            client.items(full=True)

    def test_ignored(self, client):
        assert True
'''

DATA_PY = '''import pytest

LIMIT_CASES = [
    pytest.param(0, False, id="zero", marks=pytest.mark.qa(case="TC-002", then=[2])),
    pytest.param(5, True, id="five", marks=[pytest.mark.qa(case="TC-003", then=[2])]),
]
'''


def seed(root: Path) -> Path:
    task = root / "qa-factory" / "artifacts" / TICKET
    (task / "work" / "test-cases").mkdir(parents=True)
    (task / "work" / "run-blocks").mkdir(parents=True)
    (task / "state").mkdir(parents=True)
    links = []
    for n in (1, 2, 3, 4):
        cid = f"TC-00{n}"
        path = task / "work" / "test-cases" / f"{cid}.md"
        path.write_text(CASE_MD.format(cid=cid, row=f"TS-{n}", n=n), encoding="utf-8")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        links.append({"case_id": cid, "version": "cv_" + digest[:20], "content_hash": digest,
                      "path": f"work/test-cases/{cid}.md", "area": "coupon"})
    (task / "state" / "story-case-links.json").write_text(
        json.dumps({"schema_version": 2, "task_id": TICKET, "links": links}), encoding="utf-8")
    rows = [{"id": f"TS-{n}", "disposition": "automate",
             "coverage_obligations": [{"obligation_id": f"TS-{n}-O1", "behavior": f"row {n}",
                                       "decision": "new"}]} for n in (1, 2, 3, 4)]
    (task / "work" / "test-plan.json").write_text(json.dumps({"rows": rows}), encoding="utf-8")
    (task / "state" / "controller.json").write_text(json.dumps({"dispatches": {
        DISPATCH: {"id": DISPATCH, "stage": "S5", "role": "qa-automator", "status": "running",
                   "scope": ["TC-001", "TC-002", "TC-003", "TC-004"]}}}), encoding="utf-8")
    (task / "work" / "run-blocks" / "20260924T100000000000Z-abc.json").write_text(json.dumps({
        "purpose": "initial", "results": [
            {"instance_id": "test_limit", "status": "passed"},
            {"instance_id": "test_region[us]", "status": "failed"}]}), encoding="utf-8")
    # another window's rows: a test of TC-009 and a stale binding of TC-001 Then 1 to an old id
    (task / "work" / "automation-manifest.json").write_text(json.dumps({
        "revision": 3,
        "tests": [{"case": "TC-009", "covers": ["TC-009"], "file": "tests/test_other.py",
                   "test": "test_other", "instance_id": "test_other", "status": "green"}],
        "then_bindings": [
            {"case": "TC-009", "then": 1, "instance_id": "test_other",
             "assertion_ref": "tests/test_other.py:9", "status": "covered"},
            {"case": "TC-001", "then": 1, "instance_id": "test_limit_old",
             "assertion_ref": "tests/test_coupon.py:1", "status": "covered"}]}), encoding="utf-8")
    (root / "tests" / "test_coupon.py").write_text(TEST_PY, encoding="utf-8")
    (root / "tests" / "data_coupon.py").write_text(DATA_PY, encoding="utf-8")
    return task


def run(root: Path, *extra, files=("tests/test_coupon.py", "tests/data_coupon.py")):
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(root))
    args = ["--task", TICKET, "--dispatch", DISPATCH]
    for f in files:
        args += ["--file", f]
    return harness.run_script("manifest_from_tests.py", *args, *extra, cwd=root, env=env)


def tq1_18_the_marker_takes_base_checked() -> None:
    """TQ1-18 (D3 p. 4): `base_checked` is a key of the `qa` marker (the marker form the brief prints is read from `QA_KWARGS`), so a
    test that names where its base is asserted is not refused as an unknown keyword; the generator only carries it, `s5_precheck` judges it."""
    import ast
    import manifest_from_tests as MFT
    check("`base_checked` is in the marker's keys", "base_checked" in MFT.QA_KWARGS, str(MFT.QA_KWARGS))
    node = ast.parse("@pytest.mark.qa(case='TC-1', base_checked='tests/a.py::check_base')\ndef test_x(): pass").body[0].decorator_list[0]
    found = MFT._marker(node, "tests/t.py:1 test_x")
    check_eq("the marker is read, not refused", (found[0], found[1].get("base_checked")), (MFT.MARK_QA, "tests/a.py::check_base"))


def main() -> None:
    tq1_18_the_marker_takes_base_checked()
    root = harness.temp_project("qa-manifest-from-tests-")
    try:
        task = seed(root)

        # --- dry run: the fragment, nothing written ---------------------------------------
        dry = run(root, "--dry-run", "--json")
        check("dry run exits 0", dry.returncode == 0, dry.stderr + dry.stdout[-600:])
        out = json.loads(dry.stdout)
        fragment = out["fragment"]
        by_id = {t["instance_id"]: t for t in fragment["tests"]}
        check_eq("one row per instance, the unmarked test ignored",
                 sorted(by_id), ["test_empty", "test_from_data[five]", "test_from_data[zero]",
                                 "test_full", "test_limit", "test_region[eu]", "test_region[us]"])
        manifest_after = json.loads((task / "work" / "automation-manifest.json").read_text(encoding="utf-8"))
        check_eq("a dry run writes no manifest", manifest_after["revision"], 3)
        check("and no fragment file", not (task / "work" / "manifest-fragments").exists())

        plain = by_id["test_limit"]
        check_eq("a plain function covers its case", plain["covers"], ["TC-001"])
        check_eq("the pinned version comes from story-case-links", plain["case_version_links"][0]["case_id"], "TC-001")
        check("and is the link's version", plain["case_version_links"][0]["version"].startswith("cv_"))
        check_eq("plan row and requirements come from the case file",
                 (plain["plan_row"], plain["requirements"]), ("TS-1", ["R-1"]))
        check_eq("the obligation id is validated and kept", plain["obligation_ids"], ["TS-1-O1"])
        plan = json.loads((task / "work" / "test-plan.json").read_text(encoding="utf-8"))
        expected_hash = content_hash(plan["rows"][0]["coverage_obligations"][0])
        check_eq("the obligation hash is the plan's content hash",
                 plain["obligation_refs"], [{"obligation_id": "TS-1-O1", "obligation_hash": expected_hash}])
        check_eq("status comes from the run block, not the marker", plain["status"], "green")
        check_eq("the note becomes fit_note", plain["fit_note"], "one call, two reads")
        check_eq("a single-instance function is shape new", (plain["shape"], plain["consolidates"]), ("new", ["TC-001"]))
        check_eq("file is project-relative with forward slashes", plain["file"], "tests/test_coupon.py")
        check_eq("the id is the contract's", plain["instance_id"], C.instance_id("test_limit"))
        # Coverage v2, and `window_record.py` refuses a review receipt without the sha. The
        # generator emitted none of this until 27.09, so the S5 review window was blocked on
        # two of three windows of TP1-13797 for a field the role's own tool could not make.
        import hashlib
        sha = hashlib.sha256((root / "tests" / "test_coupon.py").read_bytes()).hexdigest()
        check_eq("trace_binding carries the file's exact bytes",
                 plain["trace_binding"]["test_content_sha"], sha)
        check_eq("and the selector it was collected by",
                 plain["trace_binding"]["selector"], plain["selector"])
        check("and the assertion refs of this instance, not of the file",
              all(ref.startswith("tests/test_coupon.py:")
                  for ref in plain["trace_binding"]["assertion_refs"]),
              str(plain["trace_binding"]["assertion_refs"]))
        check("change_disposition stays the role's judgement, never guessed here",
              "change_disposition" not in plain and "change_basis_ref" not in plain,
              str(sorted(plain)))
        import window_record as WR
        by_hand = [f for f, spec in WR.REQUIRED_ROW_FIELDS.items() if spec.filled_by == "automator"]
        check_eq("HF2-12 K7 (c): no row of the fragment carries a field the automator writes (the carrier's list, not a literal one):"
                 " the printed form is the only place they are asked for",
                 sorted((row["instance_id"], f) for row in fragment["tests"] for f in by_hand if f in row), [])

        eu, us = by_id["test_region[eu]"], by_id["test_region[us]"]
        check_eq("a parametrize id becomes the partition", eu["partitions"], ["eu"])
        check_eq("and the parameter", eu["parameter"], "eu")
        check_eq("a parametrized single-case function is shape parameterize", eu["shape"], "parameterize")
        check_eq("a failed run block row reads red", us["status"], "red")
        check_eq("an instance nothing ran is pending_run", eu["status"], "pending_run")

        zero, five = by_id["test_from_data[zero]"], by_id["test_from_data[five]"]
        check_eq("pytest.param marks in the data module bind their own case", zero["covers"], ["TC-002"])
        check_eq("each param its own", five["covers"], ["TC-003"])
        check_eq("a function whose params cover two cases is a consolidate",
                 (zero["shape"], zero["consolidates"]), ("consolidate", ["TC-002", "TC-003"]))

        empty, _ = by_id["test_empty"], by_id["test_full"]
        check_eq("a class method is an instance by function name", empty["selector"],
                 "tests/test_coupon.py::TestGroup::test_empty")
        check_eq("an explicit partition wins", empty["partitions"], ["P-empty"])
        check("a class method with no marker is ignored", "test_ignored" not in by_id)

        bindings = fragment["then_bindings"]
        rows = {(b["case"], b["then"], b.get("instance_id")): b for b in bindings}
        check("TC-001 Then 1 and 2 are bound to test_limit",
              ("TC-001", 1, "test_limit") in rows and ("TC-001", 2, "test_limit") in rows)
        ref = rows[("TC-001", 1, "test_limit")]["assertion_ref"]
        check_eq("assertion_ref is the function's assert span", ref, "tests/test_coupon.py:12-13")
        check_eq("a then dict pins its own lines", rows[("TC-003", 3, "test_full")]["assertion_ref"],
                 "tests/test_coupon.py:40-41")
        check("a with pytest.raises counts as an assertion span",
              rows[("TC-003", 1, "test_empty")]["assertion_ref"].startswith("tests/test_coupon.py:"))
        check("another window's binding survives the merge", ("TC-009", 1, "test_other") in rows)
        check("the stale binding of this window's clause is replaced", ("TC-001", 1, "test_limit_old") not in rows)
        check_eq("param-level then rows are bound to the param instance",
                 rows[("TC-002", 2, "test_from_data[zero]")]["status"], "covered")

        unresolved = fragment["unresolved"]
        check_eq("a module-level qa_unresolved is a whole-case row",
                 [(u["case"], u["reason"]) for u in unresolved], [("TC-004", "impossible")])
        check_eq("with the case's links and plan row",
                 (unresolved[0]["plan_row"], unresolved[0]["case_version_links"][0]["case_id"]), ("TS-4", "TC-004"))
        check_eq("the case picture names what is still unbound", out["cases"]["TC-002"]["unbound"], [3])
        check_eq("a whole-case unresolved marker answers for every Then clause of the case",
                 sorted((b["then"], b["reason"]) for b in bindings if b["case"] == "TC-004"),
                 [(1, "impossible"), (2, "impossible"), (3, "impossible")])
        check_eq("and what is covered", out["cases"]["TC-001"]["covered"], [1, 2])

        # --- the write: one manifest_put, the other window kept ---------------------------
        first = run(root)
        check("the write exits 0", first.returncode == 0, first.stderr + first.stdout)
        check_in("and reports manifest_put's receipt", "automation-manifest.json: revision", first.stdout)
        merged = json.loads((task / "work" / "automation-manifest.json").read_text(encoding="utf-8"))
        ids = sorted(C.test_instance_id(t) for t in merged["tests"])
        check("the other window's test survives", "test_other" in ids)
        check_eq("and this window's seven are added", len(ids), 8)
        check_eq("the whole-case unresolved row landed", [u["case"] for u in merged["unresolved"]], ["TC-004"])
        fragments = sorted((task / "work" / "manifest-fragments").glob("*.json"))
        check_eq("the fragment is kept as a witness", len(fragments), 1)
        check("named after the dispatch", fragments[0].name.startswith(DISPATCH))
        revision = merged["revision"]

        second = run(root)
        check("a second identical run exits 0", second.returncode == 0, second.stderr)
        again = json.loads((task / "work" / "automation-manifest.json").read_text(encoding="utf-8"))
        check_eq("and changes nothing", (again["revision"], len(again["tests"]), len(again["then_bindings"])),
                 (revision, len(merged["tests"]), len(merged["then_bindings"])))

        import s5_precheck as P
        findings = []
        P.check_manifest(again, ["TC-001", "TC-002", "TC-003", "TC-004"], findings)
        check_eq("s5_precheck's manifest invariants hold on what was written", findings, [])
        check_eq("and it finds the bindings of a case",
                 sorted(b["then"] for b in P.bindings_of_case(again, "TC-001")), [1, 2])

        # --- refusals -----------------------------------------------------------------------
        test_py = root / "tests" / "test_coupon.py"
        original = test_py.read_text(encoding="utf-8")
        test_py.write_text(original.replace('obligations=["TS-1-O1"]', 'obligations=["TS-9-O1"]'), encoding="utf-8")
        bad = run(root, "--dry-run")
        check_eq("an obligation not on the plan row is refused", bad.returncode, 2)
        check_in("with the row and what it has", "TS-9-O1 is not an obligation of TC-001's plan row TS-1 (it has: TS-1-O1)", bad.stderr)
        check_in("and where", "tests/test_coupon.py:9", bad.stderr)

        test_py.write_text(original.replace('case="TC-001"', 'case="TC-030"'), encoding="utf-8")
        bad = run(root, "--dry-run")
        check_eq("a case the story does not have is refused", bad.returncode, 2)
        check_in("naming the story records", "not a case of QA-700", bad.stderr)

        test_py.write_text(original.replace('then=[1, 2]', 'thens=[1, 2]'), encoding="utf-8")
        bad = run(root, "--dry-run", "--json")
        check_eq("an unknown keyword is refused", bad.returncode, 2)
        check_in("naming the keywords it takes", "does not take `thens`", json.loads(bad.stdout)["refusal"])
        test_py.write_text(original, encoding="utf-8")

        # EP1-25: a parameter list imported from a module of the PROJECT is found by the script itself; the pins below are about
        # a list the import does not lead to (a name from outside the project: the code cannot read it, and says so)
        outside = original.replace("from tests.data_coupon import LIMIT_CASES", "from vendored_data import LIMIT_CASES")
        test_py.write_text(outside, encoding="utf-8")
        ignored = run(root, "--dry-run", "--json", files=("tests/test_coupon.py",))
        check_eq("an UNMARKED function whose parameter list is elsewhere is ignored, not refused",
                 ignored.returncode, 0)
        check_in("with a note saying so", "test_from_data: not marked, parameter list not read",
                 "\n".join(json.loads(ignored.stdout)["notes"]))
        test_py.write_text(outside.replace('@pytest.mark.parametrize("value, expected", LIMIT_CASES)',
                                           '@pytest.mark.qa(case="TC-002")\n'
                                           '@pytest.mark.parametrize("value, expected", LIMIT_CASES)'),
                           encoding="utf-8")
        bad = run(root, "--dry-run", files=("tests/test_coupon.py",))
        check_eq("a MARKED function whose parameter list is in a module not given is refused", bad.returncode, 2)
        check_in("and the fix is another --file", "add that module with another --file", bad.stderr)
        test_py.write_text(original, encoding="utf-8")

        env = dict(os.environ, CLAUDE_PROJECT_DIR=str(root))
        bad = harness.run_script("manifest_from_tests.py", "--task", TICKET, "--dispatch", "S5-qa-automator-9",
                                 "--file", "tests/test_coupon.py", "--file", "tests/data_coupon.py",
                                 "--dry-run", cwd=root, env=env)
        check_eq("an unknown dispatch is refused", bad.returncode, 2)
        check_in("by name", "no dispatch 'S5-qa-automator-9'", bad.stderr)

        # blocked_by_env without a remedy
        test_py.write_text(original.replace('reason="impossible"', 'reason="blocked_by_env"'), encoding="utf-8")
        bad = run(root, "--dry-run")
        check_eq("blocked_by_env without a remedy is refused", bad.returncode, 2)
        check_in("asking for the remedy shape", "remedy={kind, where, change", bad.stderr)
        test_py.write_text(original, encoding="utf-8")

        helped = harness.run_script("manifest_from_tests.py", "--help", cwd=root, env=env)
        check_in("--help tells the project how to register the markers", "addinivalue_line", helped.stdout)

        # --- FR-16: the id written is the id pytest collects ------------------------------
        # The source is not the last word on a parameter id: a project's own plugins rename it
        # before pytest collects it. On TP1-15045 the manifest kept the author's spelling and
        # 15 of 27 run rows never joined it, which surfaced at S8.
        unverified = json.loads(run(root, "--dry-run", "--json").stdout)
        check("without --collect the output says the ids are unverified",
              any("NOT verified against pytest" in note for note in unverified["notes"]),
              str(unverified["notes"]))
        check_in("and names the flag that verifies them", "--collect -- <your test command>",
                 " ".join(unverified["notes"]))
        needs_command = harness.run_script(
            "manifest_from_tests.py", "--task", TICKET, "--dispatch", DISPATCH,
            "--file", "tests/test_coupon.py", "--dry-run", "--collect", cwd=root, env=env)
        check_eq("--collect without a test command is refused", needs_command.returncode, 2)
        check_in("naming the shape", "-- python -m pytest", needs_command.stderr)

        import manifest_from_tests as MFT
        import node_ids
        fragment = {"tests": [{"instance_id": "test_region[eu]", "case": "TC-002",
                               "file": "tests/test_coupon.py"},
                              {"instance_id": "test_limit", "case": "TC-001",
                               "file": "tests/test_coupon.py"}],
                    "then_bindings": [{"case": "TC-002", "then": 1,
                                       "instance_id": "test_region[eu]"}]}
        collected = ["tests/test_coupon.py::test_region[chromium-eu]",
                     "tests/test_coupon.py::test_limit"]
        kept = node_ids.collect
        node_ids.collect = lambda *a, **k: list(collected)
        try:
            notes = []
            MFT.resolve_through_pytest(fragment, ["python", "-m", "pytest"], str(root), notes)
            check_eq("the collected spelling replaces the author's in tests[]",
                     [row["instance_id"] for row in fragment["tests"]],
                     ["test_region[chromium-eu]", "test_limit"])
            check_eq("and in then_bindings, so the join at S6 finds the row",
                     fragment["then_bindings"][0]["instance_id"], "test_region[chromium-eu]")
            check("the rewrite is reported, not silent",
                  any("pytest collects test_region[eu] as test_region[chromium-eu]" in n
                      for n in notes), str(notes))

            # An id pytest does not collect at all is a refusal: writing it is the run-5 defect.
            node_ids.collect = lambda *a, **k: ["tests/test_coupon.py::test_limit"]
            try:
                MFT.resolve_through_pytest(
                    {"tests": [{"instance_id": "test_typo[eu]", "file": "tests/test_coupon.py"}]},
                    ["python", "-m", "pytest"], str(root), [])
                check("an uncollected id refuses", False, "no refusal raised")
            except MFT.Refusal as exc:
                check_in("an uncollected id refuses, with the nearest real ids",
                         "is not collected by pytest", str(exc))
                check_in("and says it is a repair, not a question for the person",
                         "This is a repair", str(exc))
        finally:
            node_ids.collect = kept
    finally:
        harness.cleanup(root)
    the_marker_names_come_from_data()
    p20_expectation_unconfirmed()
    novelty_switch()
    a_measured_novelty_is_never_lowered_nor_written_by_a_role()
    hf2_12b()
    ep1_25()
    tq1_7()
    ep1_37()
    harness.finish("test_manifest_from_tests")


# --- EP1-25 (0.10.7): the parameter-list module is found through the test file's import; every marker problem of a file
# --- is one refusal; the marker form is told before the work -----------------------------------------------------------

def _w(root: Path, rel: str, text, raw: bytes = None) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    if raw is not None:
        path.write_bytes(raw)
    else:
        path.write_text(text, encoding="utf-8")


def _param_test(import_line: str, name: str = "LIMIT", extra: str = "") -> str:
    """A test file with one marked, parametrized function whose list comes from `import_line`."""
    return (f"import pytest\n{import_line}\n{extra}\n\n"
            f'@pytest.mark.qa(case="TC-002", then=[1])\n@pytest.mark.parametrize("v", {name})\n'
            "def test_p(v):\n    assert v\n")


def _list_module(*ids, case="TC-002") -> str:
    rows = ", ".join(f'pytest.param({i}, id="p{i}")' for i in ids)
    return f"import pytest\n\nLIMIT = [{rows}]\n"


def _dry(root: Path, *files):
    """(exit code, parsed --json stdout or None, stderr) of a dry run over `files`."""
    done = run(root, "--dry-run", "--json", files=tuple(files))
    return done.returncode, (json.loads(done.stdout) if done.stdout.strip() else None), done.stderr


def ep1_25() -> None:
    import ast
    import manifest_from_tests as MFT
    root = harness.temp_project("qa-mft-ep125-")
    try:
        task = seed(root)
        # --- AK1: the module of the list is found by the import; the fragment is the one an explicit --file gives ---------
        print("-- EP1-25 AK1: a list imported from a project module needs no second --file")
        code, auto, err = _dry(root, "tests/test_coupon.py")
        check_eq("AK1: the file with `from tests.data_coupon import LIMIT_CASES` is read alone", code, 0)
        code, explicit, _ = _dry(root, "tests/test_coupon.py", "tests/data_coupon.py")

        def bare(out):    # the measured `novelty` carries the clock of the call; everything else must be the same bytes
            rows = copy.deepcopy(out["fragment"])
            for row in rows["tests"]:
                row.pop("novelty", None)
            return json.dumps(rows, ensure_ascii=False, sort_keys=False)
        check_eq("AK1: the fragment is the same bytes as with the module given by --file, generated_from included",
                 bare(auto), bare(explicit))
        by_auto = {t["instance_id"]: t for t in auto["fragment"]["tests"]}
        check_eq("AK1: the rows of the imported list are there, with the data module's own marks",
                 (by_auto["test_from_data[zero]"]["covers"], by_auto["test_from_data[five]"]["covers"]),
                 (["TC-002"], ["TC-003"]))
        check_eq("AK1: generated_from names the module the list was read from, after the files",
                 by_auto["test_limit"]["generated_from"], ["tests/test_coupon.py", "tests/data_coupon.py"])

        print("-- EP1-25: the module's own tests and markers are not the call's work")
        _w(root, "tests/data_scan.py", _list_module(1, 2)
           + '\n\n@pytest.mark.qa(case="TC-003", then=[1])\ndef test_in_data():\n    assert 1\n'
           + '\npytestmark = [pytest.mark.qa_unresolved(case="TC-004", reason="impossible", detail="x")]\n')
        _w(root, "tests/test_scan.py", _param_test("from tests.data_scan import LIMIT"))
        code, out, err = _dry(root, "tests/test_scan.py")
        ids = sorted(t["instance_id"] for t in out["fragment"]["tests"])
        check_eq("module not scanned: only the function of the test file, not `test_in_data`", ids, ["test_p[p1]", "test_p[p2]"])
        check("module not scanned: and its module-level unresolved marker writes no row", "unresolved" not in out["fragment"],
              str(out["fragment"].keys()))
        code, out, _ = _dry(root, "tests/test_scan.py", "tests/data_scan.py")
        check("control: given by --file, the same module IS scanned (its test and its marker are rows)",
              "test_in_data" in {t["instance_id"] for t in out["fragment"]["tests"]} and "unresolved" in out["fragment"],
              str(sorted(t["instance_id"] for t in out["fragment"]["tests"])))
        check_eq("control: ... and given twice by name and by import it is read once, listed once",
                 out["fragment"]["tests"][0]["generated_from"], ["tests/test_scan.py", "tests/data_scan.py"])

        print("-- EP1-25: `as` names, relative imports, a package")
        _w(root, "tests/test_as.py", _param_test("from tests.data_scan import LIMIT as CASES", "CASES"))
        code, out, err = _dry(root, "tests/test_as.py")
        check("from m import x as y: the name the test uses is the one looked up (asname)", code == 0, err)
        _w(root, "tests/test_rel.py", _param_test("from .data_scan import LIMIT"))
        code, out, err = _dry(root, "tests/test_rel.py")
        check("from .m import x: counted from the folder of the test file", code == 0, err)
        _w(root, "tests/pkgdata/__init__.py", _list_module(7))
        _w(root, "tests/test_pkg.py", _param_test("from tests.pkgdata import LIMIT"))
        code, out, err = _dry(root, "tests/test_pkg.py")
        check_eq("a package's __init__.py holds the list", (code, [t["instance_id"] for t in out["fragment"]["tests"]]),
                 (0, ["test_p[p7]"]))
        _w(root, "tests/test_ids.py", "import pytest\nfrom tests.data_scan import LIMIT\nfrom tests.data_ids import IDS\n\n\n"
           '@pytest.mark.qa(case="TC-002", then=[1])\n@pytest.mark.parametrize("v", LIMIT, ids=IDS)\ndef test_i(v):\n    assert v\n')
        _w(root, "tests/data_ids.py", 'IDS = ["one", "two"]\n')
        code, out, err = _dry(root, "tests/test_ids.py")
        check_eq("ids=<name> goes the same way", (code, [t["instance_id"] for t in out["fragment"]["tests"]]),
                 (0, ["test_i[one]", "test_i[two]"]))

        # --- not found / not trusted: the refusal keeps its door -------------------------------------------------------
        print("-- EP1-25: what the code cannot read is a refusal with a door, never an empty list")
        door = "add that module with another --file"
        _w(root, "tests/test_third.py", _param_test("from vendored_pkg.cases import LIMIT"))
        code, out, err = _dry(root, "tests/test_third.py")
        check_eq("a third-party module: refused", code, 2)
        check_in("... with the old door", door, out["refusal"])
        _w(root, "tests/test_star.py", _param_test("from tests.data_scan import *"))
        code, out, err = _dry(root, "tests/test_star.py")
        check_eq("import *: refused with the old door", (code, door in out["refusal"]), (2, True))
        _w(root, "tests/test_attr.py", _param_test("import tests.data_scan as d", "d.LIMIT"))
        code, out, err = _dry(root, "tests/test_attr.py")
        check_eq("d.LIST: refused as before (only a literal list)", (code, "only a literal list" in out["refusal"]), (2, True))
        _w(root, "tests/data_noname.py", "OTHER = [1]\n")
        _w(root, "tests/test_noname.py", _param_test("from tests.data_noname import LIMIT"))
        code, out, err = _dry(root, "tests/test_noname.py")
        check_eq("a module without that name: not found, the old door", (code, door in out["refusal"]), (2, True))
        _w(root, "tests/data_empty.py", "")
        _w(root, "tests/test_empty.py", _param_test("from tests.data_empty import LIMIT"))
        code, out, err = _dry(root, "tests/test_empty.py")
        check_eq("an empty module: not found, the old door", (code, door in out["refusal"]), (2, True))
        _w(root, "tests/data_nonlit.py", "A = [1]\nB = [2]\nLIMIT = A + B\n")
        _w(root, "tests/test_nonlit.py", _param_test("from tests.data_nonlit import LIMIT"))
        code, out, err = _dry(root, "tests/test_nonlit.py")
        check_eq("a value that is not a literal: refused, naming the module that holds it",
                 (code, "only a literal list" in out["refusal"], "(in tests/data_nonlit.py)" in out["refusal"]), (2, True, True))
        _w(root, "tests/data_broken.py", "LIMIT = [1,\n")
        _w(root, "tests/test_broken.py", _param_test("from tests.data_broken import LIMIT"))
        code, out, err = _dry(root, "tests/test_broken.py")
        check_eq("a module that does not parse: a line `<file>:<line>`", (code, "tests/data_broken.py:" in out["refusal"],
                                                                         "does not parse" in out["refusal"]), (2, True, True))
        _w(root, "outside_mod.py", "X = [1]\n")
        holder = MFT.TestFile(root / "tests" / "test_third.py", "tests/test_third.py", root, scan=False)
        node = ast.parse("from ..outside_mod import X").body[0]
        check_eq("control: the sibling module of the tests folder is a candidate when the root holds it",
                 [p.name for p in MFT._module_files(node, holder, root)], ["outside_mod.py"])
        check_eq("a module outside the project root is never a candidate (audit A20)",
                 MFT._module_files(node, holder, root / "tests"), [])

        print("-- EP1-25: two modules the import can mean: refused, naming both and the door; --file settles it")
        _w(root, "tests/data/x.py", _list_module(1))
        _w(root, "data/x.py", _list_module(2))
        _w(root, "tests/test_two.py", _param_test("from data.x import LIMIT"))
        code, out, err = _dry(root, "tests/test_two.py")
        check_eq("two candidates: refused", code, 2)
        check("... naming both modules", "tests/data/x.py" in out["refusal"] and "data/x.py" in out["refusal"], out["refusal"])
        check_in("... and the door --file", "--file", out["refusal"])
        code, out, err = _dry(root, "tests/test_two.py", "data/x.py")
        check_eq("--file of the one meant settles it: the given file wins over the import", (code, [t["instance_id"] for t in out["fragment"]["tests"]]),
                 (0, ["test_p[p2]"]))

        print("-- EP1-25: the re-export chain: 3 modules read, the 4th refused; a circle is a refusal, not a hang")
        _w(root, "tests/m1.py", "from .m2 import LIMIT\n")
        _w(root, "tests/m2.py", "from .m3 import LIMIT\n")
        _w(root, "tests/m3.py", _list_module(3))
        _w(root, "tests/test_chain3.py", _param_test("from .m1 import LIMIT"))
        code, out, err = _dry(root, "tests/test_chain3.py")
        check_eq("AT the limit (3 imports followed): read", (code, [t["instance_id"] for t in out["fragment"]["tests"]]), (0, ["test_p[p3]"]))
        check_eq("... and generated_from names the chain, in order",
                 out["fragment"]["tests"][0]["generated_from"],
                 ["tests/test_chain3.py", "tests/m1.py", "tests/m2.py", "tests/m3.py"])
        _w(root, "tests/m3.py", "from .m4 import LIMIT\n")
        _w(root, "tests/m4.py", _list_module(4))
        code, out, err = _dry(root, "tests/test_chain3.py")
        check_eq("BEYOND the limit (4): refused", code, 2)
        check("... with the chain in the text and the door", "more than 3 modules" in out["refusal"] and "tests/m4.py" in out["refusal"]
              and "--file" in out["refusal"], out["refusal"])
        _w(root, "tests/c1.py", "from .c2 import LIMIT\n")
        _w(root, "tests/c2.py", "from .c1 import LIMIT\n")
        _w(root, "tests/test_circle.py", _param_test("from .c1 import LIMIT"))
        code, out, err = _dry(root, "tests/test_circle.py")
        check_eq("a circle of imports: refused, in a circle", (code, "in a circle" in out["refusal"]), (2, True))

        print("-- EP1-25: encodings")
        non_ascii = "".join(chr(code) for code in (0x43F, 0x440, 0x438, 0x43C, 0x435, 0x440))   # a word in Cyrillic, built: the package is English
        _w(root, "tests/data_cp.py", None, raw=(f"# comment: {non_ascii}\nimport pytest\n"
                                                  'LIMIT = [pytest.param(1, id="cp")]\n').encode("cp1251"))
        _w(root, "tests/test_cp.py", _param_test("from tests.data_cp import LIMIT"))
        code, out, err = _dry(root, "tests/test_cp.py")
        check_eq("a module in cp1251 with non-ASCII: read, nothing crashes", (code, [t["instance_id"] for t in out["fragment"]["tests"]]),
                 (0, ["test_p[cp]"]))
        _w(root, "tests/data_bom.py", None, raw=chr(0xFEFF).encode("utf-8") + (f"# {non_ascii}\nLIMIT = [1]\n").encode("utf-8"))
        _w(root, "tests/test_bom.py", _param_test("from tests.data_bom import LIMIT"))
        code, out, err = _dry(root, "tests/test_bom.py")
        check_eq("a module with a BOM: read", (code, [t["instance_id"] for t in out["fragment"]["tests"]]), (0, ["test_p[1]"]))
        _w(root, "tests/test_bomself.py", None, raw=chr(0xFEFF).encode("utf-8") + _param_test("from tests.data_bom import LIMIT").encode("utf-8"))
        code, out, err = _dry(root, "tests/test_bomself.py")
        check("a test file with a BOM: read", code == 0, err)
        _w(root, "tests/data_nul.py", None, raw=b"LIMIT = [1]\n\x00\n")
        _w(root, "tests/test_nul.py", _param_test("from tests.data_nul import LIMIT"))
        code, out, err = _dry(root, "tests/test_nul.py")
        check_eq("a module with a NUL byte: a refusal naming it, no traceback", (code, "tests/data_nul.py" in out["refusal"], "Traceback" in err),
                 (2, True, False))

        # --- AK2/AK3/AK4: every problem of a file in one refusal ---------------------------------------------------------
        print("-- EP1-25 AK2-AK4: one refusal, one line per problem")
        three = ('import pytest\n\n\n@pytest.mark.qa(case="TC-001", consolidates=["TC-001"])\ndef test_a():\n    assert 1\n\n\n'
                 '@pytest.mark.qa(then=[1])\ndef test_b():\n    assert 1\n\n\n'
                 '@pytest.mark.qa(case="TC-030", then=[1])\ndef test_c():\n    assert 1\n')
        _w(root, "tests/test_three.py", three)
        before = (task / "work" / "automation-manifest.json").read_bytes()
        done = run(root, files=("tests/test_three.py",))
        lines = [l for l in done.stderr.splitlines() if l.strip()]
        check_eq("AK2: exit 2", done.returncode, 2)
        check_eq("AK2: three problems, three lines", len(lines), 3)
        check("AK2: each names its file and line, in the order of the file",
              [("test_three.py:4" in lines[0]), ("test_three.py:9" in lines[1]), ("test_three.py:14" in lines[2])] == [True] * 3,
              "\n".join(lines))
        check_in("AK2: the first is the unknown keyword", "does not take `consolidates`", lines[0])
        check("AK2: nothing was written (no fragment folder, the manifest is the same bytes)",
              not (task / "work" / "manifest-fragments").exists()
              and (task / "work" / "automation-manifest.json").read_bytes() == before)
        code, out, _ = _dry(root, "tests/test_three.py")
        check_eq("AK4: --json: `refusal` is a string, `problems` the list", (type(out["refusal"]).__name__, len(out["problems"])), ("str", 3))
        check_eq("AK4: the string is the lines joined", out["refusal"], "\n".join(out["problems"]))
        _w(root, "tests/test_one.py", 'import pytest\n\n\n@pytest.mark.qa(then=[1])\ndef test_b():\n    assert 1\n')
        code, one, err = _dry(root, "tests/test_one.py")
        check_eq("AK3: one problem: `problems` is exactly [refusal]", (code, one["problems"]), (2, [one["refusal"]]))
        check_in("AK3: and stderr carries the same text", one["refusal"], run(root, "--dry-run", files=("tests/test_one.py",)).stderr)

        _w(root, "tests/test_nonlit.py", 'import pytest\n\nCASE_ID = "TC-001"\n\n\n@pytest.mark.qa(case=CASE_ID)\ndef test_n():\n    assert 1\n')
        code, nonlit, _ = _dry(root, "tests/test_nonlit.py")
        check_eq("F1: a `case=` that is not a literal is ONE problem, today's text, not also a false `needs case=`",
                 (code, len(nonlit["problems"]), "a marker argument must be a literal" in nonlit["refusal"],
                  "needs `case=" in nonlit["refusal"], "`CASE_ID`" in nonlit["refusal"]), (2, 1, True, False, True))
        _w(root, "tests/test_nocase.py", 'import pytest\n\n\n@pytest.mark.qa(then=[1])\ndef test_n():\n    assert 1\n')
        code, nocase, _ = _dry(root, "tests/test_nocase.py")
        check_eq("F1: a marker with no `case=` at all still says so", (code, len(nocase["problems"]), "needs `qa` " in nocase["refusal"] or "needs `case=" in nocase["refusal"]),
                 (2, 1, True))

        print("-- EP1-25: several markers wrong on ONE function; several files; a class mark once; a file that does not parse")
        _w(root, "tests/test_many.py", 'import pytest\n\n\n@pytest.mark.qa(case="TC-001", shape="nope")\n@pytest.mark.qa(then=[1])\n'
           '@pytest.mark.qa(case="TC-030")\ndef test_m():\n    assert 1\n')
        code, many, _ = _dry(root, "tests/test_many.py")
        check_eq("two wrong markers and a wrong shape on one function: three problems", (code, len(many["problems"])), (2, 3))
        _w(root, "tests/test_cls.py", 'import pytest\n\n\n@pytest.mark.qa(case="TC-030", then=[1])\nclass TestK:\n'
           '    def test_a(self):\n        assert 1\n\n    def test_b(self):\n        assert 1\n\n    def test_c(self):\n        assert 1\n')
        code, cls, _ = _dry(root, "tests/test_cls.py")
        check_eq("a class mark that is wrong is ONE problem, not one per method", (code, len(cls["problems"])), (2, 1))
        code, both, _ = _dry(root, "tests/test_one.py", "tests/test_cls.py")
        check_eq("two files: the problems of both", (code, len(both["problems"])), (2, 2))
        _w(root, "tests/test_syntax.py", "def test_x(:\n")
        code, mix, _ = _dry(root, "tests/test_syntax.py", "tests/test_one.py")
        check("a file that does not parse and a marker problem of another file: both, one refusal",
              code == 2 and len(mix["problems"]) == 2 and "test_syntax.py:1" in mix["problems"][0], str(mix and mix["problems"]))
        done = run(root, "--dry-run", files=("",))
        check("an empty --file '': one line, at once, no such file", done.returncode == 2 and "no such file" in done.stderr
              and len([l for l in done.stderr.splitlines() if l.strip()]) == 1, done.stderr)
        done = run(root, "--dry-run", files=("tests/test_one.py", "tests/not_there.py"))
        check("a --file that is no file: at once, one line, no marker problem beside it",
              done.returncode == 2 and "no such file" in done.stderr and "needs `case=" not in done.stderr, done.stderr)

        print("-- EP1-25: the limit of the refusal text: 20 lines, the 21st becomes a count; `problems` is whole")
        for count in (20, 21, 45):
            _w(root, f"tests/test_n{count}.py", "import pytest\n" + "".join(
                f'\n\n@pytest.mark.qa(case="TC-0{i + 30}", then=[1])\ndef test_n{i}():\n    assert 1\n' for i in range(count)))
            code, out, _ = _dry(root, f"tests/test_n{count}.py")
            text = out["refusal"].splitlines()
            check_eq(f"{count} problems: `problems` lists all of them", len(out["problems"]), count)
            check_eq(f"{count} problems: the lines of the text", len(text), 20 if count == 20 else 21)
            if count > 20:
                check_eq(f"{count} problems: the 21st line is the count", text[-1], f"... and {count - 20} more (--json lists all)")
            else:
                check_not_in("20 problems: no tail", "more (--json", out["refusal"])
        done = run(root, "--dry-run", files=("tests/test_n21.py",))
        check("21 problems on stderr: 20 lines and the tail", len([l for l in done.stderr.splitlines() if l.strip()]) == 21
              and "... and 1 more (--json lists all)" in done.stderr, done.stderr[-300:])
        check("the refusal helper keeps a single problem whole", MFT._aggregate(["only"]).args == ("only",)
              and MFT._aggregate(["a", "a", "b"]).problems == ["a", "b"])
        check("a Refusal raised the old way has its own text as its only problem",
              MFT.Refusal("x").problems == ["x"] and MFT.Refusal("x", ["a", "b"]).problems == ["a", "b"])
    finally:
        harness.cleanup(root)


# --- t-227c (P20): a Then whose expected value nobody confirmed is written, never asserted ---------------------------

P20_PY = '''import pytest


@pytest.mark.qa(case="TC-001", then=[1, 2])
@pytest.mark.qa_unresolved(case="TC-001", then=[3], reason="expectation_unconfirmed", question="Q7", observed="403")
def test_put(client):
    assert client.put()["count"] == 1
'''


P20_WHOLE_PY = '''import pytest

pytestmark = [pytest.mark.qa_unresolved(case="TC-001", reason="expectation_unconfirmed", question="Q7", observed="403")]
'''


def p20_expectation_unconfirmed():
    """cmp2 TC_015: Then 4 had no source for its expected value and the automator wrote the value it saw. The marker
    `qa_unresolved(then=[n], reason="expectation_unconfirmed", question=..., observed=...)` is the way not to: it writes
    ONE `then_bindings` row (no `unresolved[]` row, no instance), and refuses what the row cannot stand without."""
    import manifest_from_tests as MFT
    import stage_guard as SG
    root = harness.temp_project("qa-manifest-p20-")
    try:
        task = seed(root)
        fixtures = Path(__file__).resolve().parent / "fixtures" / "oracle-provenance"
        (task / "work" / "requirements-readiness.json").write_text(
            (fixtures / "requirements-readiness.json").read_text(encoding="utf-8"), encoding="utf-8")
        source = root / "tests" / "test_p20.py"
        source.write_text(P20_PY, encoding="utf-8")

        def dry(text=None, **kwargs):
            if text is not None:
                source.write_text(text, encoding="utf-8")
            return run(root, "--dry-run", "--json", files=("tests/test_p20.py",), **kwargs)

        done = dry()
        check_eq("the marker is accepted", done.returncode, 0)
        out = json.loads(done.stdout)
        rows = {(b["case"], b["then"]): b for b in out["fragment"]["then_bindings"]}
        check_eq("Thens 1 and 2 are bound to the test", [rows[("TC-001", n)]["status"] for n in (1, 2)], ["covered", "covered"])
        check_eq("Then 3 is the unresolved binding, as the spec writes it",
                 rows[("TC-001", 3)], {"case": "TC-001", "then": 3, "instance_id": None, "assertion_ref": None,
                                       "status": "unresolved", "reason": "expectation_unconfirmed",
                                       "question": "Q7", "observed": "403"})
        check("and it makes no `unresolved[]` row (the reason is not a whole-case reason)", "unresolved" not in out["fragment"])
        check_eq("the case picture counts it unresolved, not unbound", (out["cases"]["TC-001"]["unresolved"], out["cases"]["TC-001"]["unbound"]), ([3], []))
        # observed: absent is allowed (the test may not have reached the value) - and is not invented
        no_value = json.loads(dry(P20_PY.replace(', observed="403"', "")).stdout)
        silent = {(b["case"], b["then"]): b for b in no_value["fragment"]["then_bindings"]}[("TC-001", 3)]
        check_eq("an absent `observed` is allowed and the row carries no key for it", "observed" in silent, False)
        # the refusals, each naming the field
        for label, text, needle in (
                ("no `question`", P20_PY.replace(', question="Q7"', ""), "needs `question="),
                ("a question the readiness file does not hold", P20_PY.replace('"Q7"', '"Q99"'), "not in `open_questions`"),
                ("no `then` and no `question` (the reason is one Then's, or a whole case that names its question)",
                 P20_PY.replace("then=[3], ", "").replace(', question="Q7"', ""), "or of a whole case that names its question"),
                ("`question` beside another reason", P20_PY.replace("expectation_unconfirmed", "impossible"), "belong to `reason=\"expectation_unconfirmed\"` only")):
            bad = dry(text)
            check_eq(f"refused: {label}", bad.returncode, 2)
            check_in(f"refused: {label} - and says what is wrong and what to write", needle, json.loads(bad.stdout)["refusal"])
        check_in("a question that is not there lists the ids it does hold", "it holds: Q1, Q7", json.loads(dry(P20_PY.replace('"Q7"', '"Q99"')).stdout)["refusal"])
        (task / "work" / "requirements-readiness.json").unlink()
        gone = dry(P20_PY)
        check_eq("refused: no readiness file at all (an `unknown` never travels without its door)", gone.returncode, 2)
        check_in("and it says so", "requirements-readiness.json is missing", json.loads(gone.stdout)["refusal"])
        # the write: manifest_put takes the row and the manifest still passes its own invariants
        (task / "work" / "requirements-readiness.json").write_text(
            (fixtures / "requirements-readiness.json").read_text(encoding="utf-8"), encoding="utf-8")
        source.write_text(P20_PY, encoding="utf-8")
        wrote = run(root, files=("tests/test_p20.py",))
        check_eq("manifest_put accepts the manifest with the new row", wrote.returncode, 0)
        merged = json.loads((task / "work" / "automation-manifest.json").read_text(encoding="utf-8"))
        check_eq("and it stands in then_bindings, once", [b["reason"] for b in merged["then_bindings"] if b["case"] == "TC-001" and b["then"] == 3],
                 ["expectation_unconfirmed"])
        # the neighbour that reads `then_bindings` per function (judge_code) tolerates a row with no instance
        import judge_code as JC
        check_eq("judge_code.bound_clauses: the bound Thens are the test's own, the unconfirmed Then belongs to no function",
                 (JC.bound_clauses(merged, "TC-001", "test_put"), JC.bound_clauses(merged, "TC-001", "test_other")), ({1, 2}, set()))
        # ONE source for the closed list: stage_guard reads it from here, so the two can never diverge
        check_eq("stage_guard's closed list IS manifest_from_tests'", SG.closed_unresolved_reasons(), tuple(MFT.UNRESOLVED_REASON_WORDS))
        check_eq("and the module attribute some caller may still read is the same set", SG.UNRESOLVED_REASONS, set(MFT.UNRESOLVED_REASON_WORDS))
        check_eq("the list IS the contract's (t-271 D2: the word moved there, one home) and holds it exactly once",
                 (tuple(MFT.UNRESOLVED_REASON_WORDS) == tuple(C.UNRESOLVED_REASONS),
                  list(MFT.UNRESOLVED_REASON_WORDS).count("expectation_unconfirmed")), (True, 1))
        # D2: a WHOLE-case row with `question=` is accepted now (the door t-255 asked for); without it, as before
        whole = dry(P20_WHOLE_PY)
        check_eq("D2: a whole-case `expectation_unconfirmed` with its question is accepted", whole.returncode, 0)
        wrote_whole = json.loads(whole.stdout)["fragment"]
        check_eq("D2: ...as an `unresolved[]` row that carries the question and the value seen",
                 [(u["case"], u["reason"], u.get("question"), u.get("observed")) for u in wrote_whole["unresolved"]],
                 [("TC-001", "expectation_unconfirmed", "Q7", "403")])
        check("D2: ...and every clause of the case is bound unresolved with the same reason and question",
              wrote_whole["then_bindings"] and all((b["reason"], b["question"]) == ("expectation_unconfirmed", "Q7")
                                                   for b in wrote_whole["then_bindings"] if b["case"] == "TC-001"))
        for label, text, needle in (("a whole case with no question", P20_WHOLE_PY.replace(', question="Q7"', ""), "names its question"),
                                    ("a whole case with a question the readiness file does not hold", P20_WHOLE_PY.replace('"Q7"', '"Q99"'),
                                     "not in `open_questions`")):
            bad = dry(text)
            check_eq(f"D2 refused: {label}", bad.returncode, 2)
            check_in(f"D2 refused: {label} - says what to write", needle, json.loads(bad.stdout)["refusal"])
        check_eq("stage_guard has no literal copy any more (a copy is what drifts)", "handed_to_person" in Path(SG.__file__).read_text(encoding="utf-8").split("def closed_unresolved_reasons")[0], False)
        check_eq("the manifest rule accepts the new word and still refuses an invented one",
                 SG.unresolved_rows_without_decision({"unresolved": [{"case": "TC-1", "reason": "expectation_unconfirmed"},
                                                                       {"case": "TC-2", "reason": "wishful"}]}), ["TC-2 (wishful)"])
    finally:
        harness.cleanup(root)


def the_marker_names_come_from_data():
    """t-016 Amendments 4-5: the case marker names live in references/case-markers.json (one
    source with diff_scope); a broken file is a named refusal with the door, and the registration
    lines a project pastes are formatted from the same data."""
    import manifest_from_tests as MFT
    data = json.loads(MFT.MARKERS_FILE.read_text(encoding="utf-8"))["pytest"]
    check_eq("the names are the data file's", (MFT.MARK_QA, MFT.MARK_UNRESOLVED), (data["case"], data["unresolved"]))
    check_in("the registration help names the case marker from data", f"{data['case']}(case, then,", MFT.REGISTRATION_HELP)
    check_in("...and the unresolved one", f"{data['unresolved']}(case, reason,", MFT.REGISTRATION_HELP)
    tmp = harness.temp_dir("qa-case-markers-")
    try:
        cases = {"absent": None, "not json": "{ nope", "no pytest names": "{}",
                 "a name that is not an identifier": json.dumps({"pytest": {"case": "q a", "unresolved": "x"}})}
        for label, body in cases.items():
            path = tmp / (label.replace(" ", "_") + ".json")
            if body is not None:
                path.write_text(body, encoding="utf-8")
            try:
                MFT.load_case_markers(path)
                said = ""
            except MFT.MarkersUnavailable as exc:
                said = str(exc)
            check_in(f"{label}: a named refusal, naming the file", "references/case-markers.json", said)
            check_in(f"{label}: ...and the door", "reinstall the plugin", said)
        check("MarkersUnavailable is a ValueError, as LevelsUnavailable is", issubclass(MFT.MarkersUnavailable, ValueError))
    finally:
        harness.cleanup(tmp)


# --- B-207 P5-D: the stored novelty and generated_from ---------------------------------------------

ROW_KEYS = {"value", "basis", "base", "measured_on", "measured_by", "measured_at"}
TWENTY = "import pytest\n" + "".join(
    f'\n\n@pytest.mark.qa(case="TC-001", then=[1])\ndef test_twenty_{i}():\n    assert {i} == {i}\n'
    for i in range(20))
ONLY_UNRESOLVED = ('import pytest\n\npytestmark = [pytest.mark.qa_unresolved(case="TC-004", '
                   'reason="impossible", detail="no channel reads it")]\n')
ADDED = '\n\n@pytest.mark.qa(case="TC-002", then=[1])\ndef test_added(client):\n    assert client.added()\n'


def _git(cwd, *args):
    done = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=120)
    if done.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed in {cwd}: {done.stderr.strip()}")
    return done.stdout.strip()


def fixture(mode, tests_py=None, made=None):
    """`(project, task)`: a project one folder inside its own repository, the seeded story, and
    - `s0`: the S0 record taken (what `stage_done` does at the S0 exit), nothing run yet;
    - `head_now`: a repository and no record;
    - `none`: no repository at all."""
    repo = harness.temp_dir("qa-mft-nov-")
    if made is not None:
        made.append(repo)
    project = repo / "proj"
    (project / "qa-factory" / "state").mkdir(parents=True)
    (project / "tests").mkdir()
    cfg = json.loads((harness.PLUGIN_ROOT / "references" / "templates" / "config.json")
                     .read_text(encoding="utf-8"))
    cfg["tests_root"], cfg["app_root"] = "tests", "."
    (project / "qa-factory" / "config.json").write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    task = seed(project)
    if tests_py is not None:
        (project / "tests" / "test_coupon.py").write_text(tests_py, encoding="utf-8")
    for block in (task / "work" / "run-blocks").glob("*.json"):
        block.unlink()            # a run block before the record would make the S0 record "late"
    if mode != "none":
        _git(repo, "init", "-q", "-b", "main")
        (repo / ".gitignore").write_text("qa-factory/\n", encoding="utf-8")
        _git(repo, "add", "-A")
        _git(repo, "-c", "commit.gpgsign=false", "commit", "-q", "-m", "base")
    if mode == "s0":
        import test_repo_base
        test_repo_base.record(task, project, {"tests_root": "tests"})
    return project, task


def edit_story(project):
    """What the story does after S0: changes `test_limit`, adds `test_added`."""
    path = project / "tests" / "test_coupon.py"
    text = path.read_text(encoding="utf-8")
    if 'assert body["count"] == 1' not in text:
        raise RuntimeError("the fixture test file is not the one this edit expects")
    path.write_text(text.replace('assert body["count"] == 1', 'assert body["count"] == 2') + ADDED,
                    encoding="utf-8")


def build_rows(project, task, files=("tests/test_coupon.py", "tests/data_coupon.py")):
    import manifest_from_tests as MFT
    story = MFT.Story(TICKET, task)
    return MFT.build(story, [MFT.TestFile(project / f, f) for f in files], DISPATCH, project=project)


def canned(kind, value):
    sha = "a" * 40 if kind != "none" else ""
    return lambda items: [{"value": value, "basis": "canned words", "base": {"kind": kind, "sha": sha},
                           "measured_on": {"tests/test_coupon.py": "b" * 64}} for _ in items]


class Counting:
    """Stands in for `test_novelty.measure_many`: records every call, then answers (the real one, a
    canned table, or an exception)."""

    def __init__(self, answer=None, raises=None):
        import test_novelty
        self.real, self.answer, self.raises, self.calls = test_novelty.measure_many, answer, raises, []

    def __call__(self, project_root, items, base_record=None, run_cwd=None):
        items = list(items)
        self.calls.append({"items": items, "base_record": base_record, "run_cwd": run_cwd})
        if self.raises is not None:
            raise self.raises
        if self.answer is not None:
            return self.answer(items)
        return self.real(project_root, items, base_record=base_record, run_cwd=run_cwd)


@contextlib.contextmanager
def patched(stub):
    import test_novelty
    before = test_novelty.measure_many
    test_novelty.measure_many = stub
    try:
        yield stub
    finally:
        test_novelty.measure_many = before


def nov(row):
    """The row's stored novelty block, `{}` when it has none (a mutant that writes none must fail a
    check by name, not crash the file)."""
    block = row.get("novelty") if isinstance(row, dict) else None
    return block if isinstance(block, dict) else {}


def tree_hash(root):
    digest = hashlib.sha256()
    for path in sorted(p for p in Path(root).rglob("*") if p.is_file()):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def cli(project, *extra, files=("tests/test_coupon.py", "tests/data_coupon.py"), tmp=None):
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(project))
    if tmp is not None:
        env.update(TMP=str(tmp), TEMP=str(tmp), TMPDIR=str(tmp))
    args = ["--task", TICKET, "--dispatch", DISPATCH]
    for f in files:
        args += ["--file", f]
    return harness.run_script("manifest_from_tests.py", *args, *extra, cwd=project, env=env)


def novelty_switch():
    made: list = []
    try:
        _novelty_switch(made)
    finally:
        for folder in made:
            harness.cleanup(folder)


def _novelty_switch(made):
    import manifest_put
    import proof_level as PL
    import manifest_from_tests as MFT

    print("-- P5-D: the stored novelty, S0 base")
    project, task = fixture("s0", made=made)
    head = _git(project, "rev-parse", "HEAD")
    edit_story(project)
    counter = Counting()
    with patched(counter):
        out = build_rows(project, task)
    rows = out["fragment"]["tests"]
    by_id = {r["instance_id"]: r for r in rows}
    check_eq("R3: a row per instance as before", len(rows), 8)
    check("R3: every row carries novelty with exactly value/basis/base/measured_on/measured_by/measured_at",
          all(set(r.get("novelty") or ()) == ROW_KEYS for r in rows), str([sorted(r.get("novelty") or ()) for r in rows]))
    check("R3: base is {kind, sha}, measured_on a path->sha map, measured_by names this script",
          all(set(nov(r).get("base") or ()) == {"kind", "sha"} and isinstance(nov(r).get("measured_on"), dict)
              and nov(r).get("measured_by") == "manifest_from_tests.py" for r in rows))
    stamps = {nov(r).get("measured_at") for r in rows}
    check("R3: measured_at is one ISO stamp for the call",
          len(stamps) == 1 and isinstance(next(iter(stamps)), str)
          and datetime.fromisoformat(next(iter(stamps))) is not None)
    check_eq("R3: a function edited since S0 reads changed, against the recorded S0 commit",
             (nov(by_id["test_limit"]).get("value"), nov(by_id["test_limit"]).get("base")),
             ("changed", {"kind": "s0", "sha": head}))
    check_eq("R3: a function added since S0 reads new", nov(by_id["test_added"]).get("value"), "new")
    check_eq("R3: a function not touched reads unchanged - stored under S0, every value is written",
             sorted({nov(by_id[i]).get("value") for i in by_id if i not in ("test_limit", "test_added")}),
             ["unchanged"])
    check("R3: the measured files travel with the value",
          "tests/test_coupon.py" in (nov(by_id["test_limit"]).get("measured_on") or {}),
          str(nov(by_id["test_limit"]).get("measured_on")))
    print("-- R1/V3: one measure_many call, one item per function")
    check_eq("V3: measure_many is called exactly once per build", len(counter.calls), 1)
    names = sorted(i["function"] for i in counter.calls[0]["items"])
    check_eq("R1: one item per function key (8 rows, 6 functions), none for the data file",
             names, sorted(["test_limit", "test_region", "test_from_data", "test_empty", "test_full", "test_added"]))
    check("R1: no item names the data module", all(i["test_rel"] == "tests/test_coupon.py" for i in counter.calls[0]["items"]))
    check_eq("R1: a class method carries its class chain",
             sorted(tuple(i["class_chain"]) for i in counter.calls[0]["items"] if i["function"] == "test_empty"),
             [("TestGroup",)])
    check_eq("R1: the base record handed over is the one test_repo_base.load reads for this story",
             (counter.calls[0]["base_record"] or {}).get("head"), head)
    check_eq("vii: parametrized rows of one function carry the same block",
             nov(by_id["test_region[eu]"]), nov(by_id["test_region[us]"]))
    check("vii: ...each its own copy, so a later edit of one row cannot move the other",
          bool(nov(by_id["test_region[eu]"])) and nov(by_id["test_region[eu]"]) is not nov(by_id["test_region[us]"]))
    check_eq("vii: and the two params of the data module share theirs",
             nov(by_id["test_from_data[zero]"]), nov(by_id["test_from_data[five]"]))
    check_eq("viii: a story with no profile runs from the project root",
             Path(counter.calls[0]["run_cwd"]).resolve(), project.resolve())

    print("-- R5: generated_from")
    check("R5: every row names the --file paths of the call, project-relative, in the order given",
          all(r["generated_from"] == ["tests/test_coupon.py", "tests/data_coupon.py"] for r in rows),
          str(rows[0]["generated_from"]))
    with patched(Counting(answer=canned("s0", "unchanged"))):
        again = build_rows(project, task, files=("tests/data_coupon.py", "tests/test_coupon.py", "tests/data_coupon.py"))
    check_eq("R5: order as given and deduplicated",
             {tuple(r["generated_from"]) for r in again["fragment"]["tests"]},
             {("tests/data_coupon.py", "tests/test_coupon.py")})
    check("iii: a data file is in generated_from and is never a measurement item",
          "tests/data_coupon.py" in rows[0]["generated_from"]
          and all(i["test_rel"] != "tests/data_coupon.py" for i in counter.calls[0]["items"]))

    print("-- V2: a base that is not a recorded S0 record")
    matrix = {"s0": {"new": True, "changed": True, "unchanged": True, "unknown": True},
              "head_now": {"new": True, "changed": True, "unchanged": False, "unknown": False},
              "none": {"new": True, "changed": True, "unchanged": False, "unknown": False}}
    for kind, values in matrix.items():
        for value, written in values.items():
            with patched(Counting(answer=canned(kind, value))):
                got = build_rows(project, task, files=("tests/test_coupon.py",))["fragment"]["tests"]
            check_eq(f"V2: base {kind} measured {value} -> {'novelty written' if written else 'NO novelty key'}",
                     all("novelty" in r for r in got), written)
            check(f"V2: base {kind} measured {value} -> generated_from is written either way (the file, then the module its "
                  "parameter list was read from through its import - EP1-25)",
                  all(r.get("generated_from") == ["tests/test_coupon.py", "tests/data_coupon.py"] for r in got))

    proj_h, task_h = fixture("head_now", made=made)
    edit_story(proj_h)
    hcount = Counting()
    with patched(hcount):
        head_rows = {r["instance_id"]: r for r in build_rows(proj_h, task_h)["fragment"]["tests"]}
    check_eq("V2 (head_now, real measurer): only the new and the changed function carry a key",
             sorted(i for i, r in head_rows.items() if "novelty" in r), ["test_added", "test_limit"])
    check_eq("V2 (head_now): those keys say so", {(nov(head_rows[i]).get("base") or {}).get("kind") for i in ("test_added", "test_limit")},
             {"head_now"})
    check_eq("V2 (head_now): values", (nov(head_rows["test_limit"]).get("value"), nov(head_rows["test_added"]).get("value")),
             ("changed", "new"))
    check("i: no record on disk -> the measurer is handed None and decides the kind itself",
          hcount.calls[0]["base_record"] is None)
    malformed = {"schema_version": 1, "git": "ok", "head": "not-a-commit", "late": False,
                 "dirty_truncated": False, "dirty": []}
    (task_h / "state" / "test-repo-base.json").write_text(json.dumps(malformed), encoding="utf-8")
    bad = Counting()
    with patched(bad):
        bad_rows = {r["instance_id"]: r for r in build_rows(proj_h, task_h)["fragment"]["tests"]}
    check_eq("i: a record that loads but is malformed is passed through untouched", bad.calls[0]["base_record"], malformed)
    check_eq("i: ...and the measurer's own verdict (head_now) decides what is stored",
             sorted(i for i, r in bad_rows.items() if "novelty" in r), ["test_added", "test_limit"])

    proj_n, task_n = fixture("none", made=made)
    none_rows = build_rows(proj_n, task_n)
    check("V2 (no git, real measurer): no row has a novelty key and there is no note about it",
          all("novelty" not in r for r in none_rows["fragment"]["tests"])
          and not any("novelty" in n for n in none_rows["notes"]), str(none_rows["notes"]))
    check("...the rest of the row is what it was, generated_from included",
          all(r["generated_from"] == ["tests/test_coupon.py", "tests/data_coupon.py"] for r in none_rows["fragment"]["tests"]))

    print("-- edges")
    boom = Counting(raises=RuntimeError("the measurer blew up"))
    with patched(boom):
        failed = build_rows(project, task)
    check("ii: a measurer that raises leaves the rows without the key and the fragment whole",
          len(failed["fragment"]["tests"]) == 8 and all("novelty" not in r for r in failed["fragment"]["tests"])
          and failed["fragment"].get("then_bindings") and failed["fragment"].get("unresolved"))
    check_in("ii: one note names the class", "novelty could not be measured (RuntimeError)", failed["notes"])
    check_eq("ii: exactly one such note", sum(1 for n in failed["notes"] if "novelty could not be measured" in n), 1)
    with patched(Counting(answer=lambda items: [])):
        short = build_rows(project, task)
    check_in("ii: an answer of the wrong length is the same refusal of the measure, not a crash",
             "novelty could not be measured (ValueError)", short["notes"])

    (project / "tests" / "test_only_unresolved.py").write_text(ONLY_UNRESOLVED, encoding="utf-8")
    zero = Counting()
    with patched(zero):
        nothing = build_rows(project, task, files=("tests/test_only_unresolved.py",))
    check("vi: zero rows -> no measure_many call at all", zero.calls == [] and "tests" not in nothing["fragment"]
          and nothing["fragment"].get("unresolved"), str(zero.calls))

    outside = project.parent / "other"
    outside.mkdir()
    (outside / "test_out.py").write_text(
        'import pytest\n\n\n@pytest.mark.qa(case="TC-001", then=[1])\ndef test_out():\n    assert True\n', encoding="utf-8")
    out_tf = MFT.TestFile(outside / "test_out.py", "../other/test_out.py")
    with patched(Counting()):
        out_rows = MFT.build(MFT.Story(TICKET, task), [out_tf], DISPATCH, project=project)["fragment"]["tests"]
    check("iv: a test file outside the project root is never stored as unchanged",
          all(r.get("novelty", {}).get("value") != "unchanged" for r in out_rows), str(out_rows[0].get("novelty")))
    with patched(Counting(answer=canned("s0", "unknown"))):
        unk = build_rows(project, task, files=("tests/test_coupon.py",))["fragment"]["tests"]
    check("iv: an unknown measured on an S0 base is written (V2), and reads unknown",
          all(nov(r).get("value") == "unknown" and (nov(r).get("base") or {}).get("kind") == "s0" for r in unk))

    print("-- viii: the run's cwd")
    cfg_path = project / "qa-factory" / "config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    one = {"profile_id": "one", "roots": {"test": "tests"}, "commands": {"one_test": {"cwd": "app"}}}
    two = {"profile_id": "two", "roots": {"test": "tests2"}, "commands": {"one_test": {"cwd": "other"}}}
    (project / "tests2").mkdir()
    (project / "tests2" / "test_two.py").write_text(
        'import pytest\n\n\n@pytest.mark.qa(case="TC-001", then=[1])\ndef test_two():\n    assert True\n', encoding="utf-8")
    try:
        cfg["profiles"] = [one]
        cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
        C.case_config_reset()
        seen = Counting(answer=canned("s0", "unchanged"))
        with patched(seen):
            build_rows(project, task, files=("tests/test_coupon.py", "tests/data_coupon.py"))
        check_eq("viii: a profile that owns the files gives the run its own cwd",
                 Path(seen.calls[0]["run_cwd"]).resolve(), (project / "app").resolve())
        cfg["profiles"] = [one, two]
        cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
        C.case_config_reset()
        mixed = Counting(answer=canned("s0", "unchanged"))
        with patched(mixed):
            build_rows(project, task, files=("tests/test_coupon.py", "tests2/test_two.py"))
        check("viii: files of two profiles force no cwd - the measurer resolves each folder itself",
              mixed.calls[0]["run_cwd"] is None, str(mixed.calls[0]["run_cwd"]))
    finally:
        cfg["profiles"] = []
        cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
        C.case_config_reset()

    print("-- v: a re-generated row")
    stale = dict(by_id["test_limit"], novelty={
        "value": "new", "basis": "old words", "resolved": True, "base": {"kind": "head_now", "sha": ""},
        "measured_on": {"tests/old.py": "1" * 64}, "measured_by": "someone else",
        "measured_at": "2020-01-01T00:00:00+00:00"})
    merged, _summary = manifest_put.merge({"tests": [stale]}, {"tests": [by_id["test_limit"]]})
    row = [t for t in merged["tests"] if t.get("instance_id") == "test_limit"]
    check("v: the stored block is replaced whole by this call's, never merged key by key",
          len(row) == 1 and nov(row[0]) == nov(by_id["test_limit"]) != {}, str(row))
    with patched(Counting(answer=canned("s0", "unchanged"))):
        first = nov(build_rows(project, task, files=("tests/test_coupon.py",))["fragment"]["tests"][0])
        time.sleep(1.1)
        second = nov(build_rows(project, task, files=("tests/test_coupon.py",))["fragment"]["tests"][0])
    check("v: with nothing stored, measured_at moves with the call, everything else is the measurement's",
          first.get("measured_at") != second.get("measured_at") and bool(first)
          and {k: v for k, v in first.items() if k != "measured_at"} == {k: v for k, v in second.items() if k != "measured_at"})

    print("-- V3: the time the measure adds, 20 functions in one file")
    proj_t, task_t = fixture("s0", tests_py=TWENTY, made=made)
    path = proj_t / "tests" / "test_coupon.py"
    path.write_text(path.read_text(encoding="utf-8").replace("assert 3 == 3", "assert 3 == 3\n    assert 4 == 4"),
                    encoding="utf-8")
    files = ("tests/test_coupon.py",)
    stub = Counting(answer=canned("s0", "unchanged"))
    with patched(stub):
        started = time.monotonic()
        build_rows(proj_t, task_t, files=files)
        bare = time.monotonic() - started
    real = Counting()
    with patched(real):
        started = time.monotonic()
        timed = build_rows(proj_t, task_t, files=files)
        measured = time.monotonic() - started
    values = sorted(str(nov(r).get("value")) for r in timed["fragment"]["tests"])
    print(f"   V3 timing: build with the measure stubbed {bare:.2f} s, with the real measure {measured:.2f} s, "
          f"added {measured - bare:.2f} s (bound 10 s)")
    check_eq("V3: one measure_many call for 20 functions, 20 items", (len(real.calls), len(real.calls[0]["items"])), (1, 20))
    check_eq("V3: the real measure found the one edited function among the 20", values, ["changed"] + ["unchanged"] * 19)
    check("V3: the measure adds at most 10 s to a build of 20 functions", measured - bare <= 10.0, f"{measured - bare:.2f} s")

    print("-- the CLI: dry run writes nothing; a write is read back by the reader")
    before = tree_hash(task)
    private = harness.temp_dir("qa-mft-priv-")
    made.append(private)
    dry = cli(project, "--dry-run", "--json", tmp=private)
    check("4: dry run exits 0", dry.returncode == 0, dry.stderr + dry.stdout[-400:])
    fragment = json.loads(dry.stdout)["fragment"]
    check("4: a dry run prints the rows WITH novelty",
          fragment["tests"] and all("novelty" in r and r["generated_from"] for r in fragment["tests"]), dry.stdout[:300])
    check_eq("4: the task folder's tree hash is equal before and after a dry run", tree_hash(task), before)
    check("4: no fragment folder appeared", not (task / "work" / "manifest-fragments").exists())
    check_eq("4: the mirror lived in the OS temp dir and is gone afterwards", sorted(p.name for p in private.iterdir()), [])

    written = cli(project)
    check("the write exits 0", written.returncode == 0, written.stderr + written.stdout[-400:])
    manifest = json.loads((task / "work" / "automation-manifest.json").read_text(encoding="utf-8"))
    mine = {t["instance_id"]: t for t in manifest["tests"] if t["instance_id"] != "test_other"}
    check("the stored rows carry the block", mine and all("novelty" in t for t in mine.values()))
    read = {i: PL.novelty_of(t, project) for i, t in mine.items()}
    check_eq("the reader accepts what the writer stored: same value back, nothing degraded",
             {i: v[0] for i, v in read.items()}, {i: nov(t).get("value") for i, t in mine.items()})
    # The predicate re-hashes `measured_on` under the PROCESS's project (the same place the
    # validator reads it), so this process is pointed at the fixture for the two calls.
    kept_env = os.environ.get("CLAUDE_PROJECT_DIR")
    harness.use_project(project)
    try:
        needs = (PL.proof_required(mine["test_limit"], manifest),
                 PL.proof_required(mine["test_region[eu]"], manifest))
    finally:
        if kept_env is None:
            os.environ.pop("CLAUDE_PROJECT_DIR", None)
        else:
            os.environ["CLAUDE_PROJECT_DIR"] = kept_env
        import hooklib
        hooklib._PROJECT_ROOT_CACHE = None
    check_eq("the predicate reads it: a changed function needs a live check, an untouched one does not",
             needs, (True, False))

    print("-- a re-run: the same measurement keeps its stamp, a stale block is dropped, a role cannot touch it")
    proj2, task2 = fixture("s0", made=made)
    edit_story(proj2)

    def stored(_label=""):
        doc = json.loads((task2 / "work" / "automation-manifest.json").read_text(encoding="utf-8"))
        return {t["instance_id"]: t for t in doc["tests"]}

    first_run = cli(proj2)
    check("first run exits 0", first_run.returncode == 0, first_run.stderr + first_run.stdout[-300:])
    rows1, hash1 = stored("1"), tree_hash(task2)
    check("the first run stored the S0 blocks", nov(rows1["test_limit"]).get("value") == "changed"
          and nov(rows1["test_region[eu]"]).get("value") == "unchanged")
    second_run = cli(proj2)
    check("second run exits 0", second_run.returncode == 0, second_run.stderr + second_run.stdout[-300:])
    check_eq("idempotence: two identical runs on an S0 fixture leave the task folder's tree hash equal",
             tree_hash(task2), hash1)
    check_eq("...and every stored measured_at is the first run's",
             {i: nov(t).get("measured_at") for i, t in stored("2").items() if i != "test_other"},
             {i: nov(t).get("measured_at") for i, t in rows1.items() if i != "test_other"})
    time.sleep(1.1)
    region = proj2 / "tests" / "test_coupon.py"
    region.write_text(region.read_text(encoding="utf-8").replace("== region", "== region  # edited\n    assert True"),
                      encoding="utf-8")
    third_run = cli(proj2)
    check("third run exits 0", third_run.returncode == 0, third_run.stderr + third_run.stdout[-300:])
    rows3 = stored("3")
    check_eq("an edit between runs moves measured_at of the function it changed",
             nov(rows3["test_region[eu]"]).get("value"), "changed")
    check("...a moved stamp, with the file's new sha in measured_on (the file is part of the measurement)",
          nov(rows3["test_region[eu]"]).get("measured_at") != nov(rows1["test_region[eu]"]).get("measured_at")
          and nov(rows3["test_region[eu]"]).get("measured_on") != nov(rows1["test_region[eu]"]).get("measured_on"))

    # a critic's patch (no generated_from) cannot remove or alter a measured block
    block = nov(rows3["test_limit"])
    critic = {"instance_id": "test_limit", "file": "tests/test_coupon.py", "critic_verdict": "approved"}
    after, _s = manifest_put.merge({"tests": [dict(rows3["test_limit"])]}, {"tests": [critic]})
    check("a role's patch leaves the measured block as it was",
          nov(after["tests"][0]) == block and after["tests"][0]["critic_verdict"] == "approved", str(after["tests"][0]))
    forged = dict(critic, novelty={"value": "unchanged", "basis": "by hand"})
    after, _s = manifest_put.merge({"tests": [dict(rows3["test_limit"])]}, {"tests": [forged]})
    check("a patch with a novelty of its own replaces it whole, as any field does today (the F-2 trust)",
          nov(after["tests"][0]) == {"value": "unchanged", "basis": "by hand"})
    writer_no_key = dict(rows3["test_limit"], fit_note="re-sent")
    writer_no_key.pop("novelty")
    standing = dict(rows3["test_limit"], critic_verdict="approved")
    after, _s = manifest_put.merge({"tests": [standing]}, {"tests": [writer_no_key]})
    check("the writer's own patch (generated_from, no novelty) drops the stale block in the merge",
          "novelty" not in after["tests"][0] and after["tests"][0].get("generated_from"), str(after["tests"][0]))
    check_eq("...and every other field is shallow-updated as before (a role's field stays, the patch's wins)",
             (after["tests"][0].get("critic_verdict"), after["tests"][0].get("fit_note")), ("approved", "re-sent"))

    # the real road: commit the story's edits and lose the S0 record -> head_now, equal to HEAD -> no key
    repo = proj2.parent
    _git(repo, "add", "-A")
    _git(repo, "-c", "commit.gpgsign=false", "commit", "-q", "-m", "delivery")
    (task2 / "state" / "test-repo-base.json").unlink()
    fourth_run = cli(proj2)
    check("re-run under head_now exits 0", fourth_run.returncode == 0, fourth_run.stderr + fourth_run.stdout[-300:])
    rows4 = stored("4")
    check("re-run under head_now: a row that held a stored `changed` block from the S0 run has no key after the merge",
          nov(rows3["test_limit"]).get("value") == "changed" and "novelty" not in rows4["test_limit"],
          str(rows4["test_limit"].get("novelty")))
    check("...and the rows keep their generated_from",
          all(t.get("generated_from") for i, t in rows4.items() if i != "test_other"))


# --- t-187: the two ways a measured `new`/`changed` could read "not required" ---------------------------
# The owner's rule: a test is proven by a live check unless it was measured `unchanged` against the
# story's S0 base; the forbidden direction is a required test reading not required. The critic of
# B-207 found two roads to it: (F-A) the measurer fails on a re-run, the writer's patch carries
# `generated_from` and no `novelty`, and `manifest_put.merge` drops the stored block; (F-B) a role
# fragment `{"value":"unchanged","resolved":true}` on a `tests[]` row, which `novelty_of` reads as a
# window item's form.

@contextlib.contextmanager
def in_project(project):
    """This process reads the fixture as its project (the predicate re-hashes under it), then goes back."""
    import hooklib
    import proof_level as PL
    kept = os.environ.get("CLAUDE_PROJECT_DIR")
    harness.use_project(project)
    PL._reset()
    try:
        yield
    finally:
        if kept is None:
            os.environ.pop("CLAUDE_PROJECT_DIR", None)
        else:
            os.environ["CLAUDE_PROJECT_DIR"] = kept
        hooklib._PROJECT_ROOT_CACHE = None
        PL._reset()


def a_measured_novelty_is_never_lowered_nor_written_by_a_role():
    made: list = []
    try:
        _never_lowered(made)
    finally:
        for folder in made:
            harness.cleanup(folder)


def _never_lowered(made):
    import manifest_put
    import proof_level as PL

    def rows_of(manifest):
        return {C.test_instance_id(t): t for t in C.manifest_tests(manifest)}

    def stored(task):
        return json.loads((task / "work" / "automation-manifest.json").read_text(encoding="utf-8"))

    print("-- t-187 F-A: a measurer that fails on a re-run never erases what an earlier run measured")
    project, task = fixture("s0", made=made)
    edit_story(project)
    first = cli(project)
    check("F-A: the first run (real measurer) exits 0", first.returncode == 0, first.stderr + first.stdout[-300:])
    before = stored(task)
    rows_before = rows_of(before)
    with in_project(project):
        needs_before = {i: PL.proof_required(rows_before[i], before)
                        for i in ("test_limit", "test_added", "test_region[eu]")}
    check_eq("F-A precondition: changed and new are required, an untouched function is not",
             needs_before, {"test_limit": True, "test_added": True, "test_region[eu]": False})
    blocks = {i: nov(rows_before[i]) for i in needs_before}

    for label, stub in (("the measurer raises", Counting(raises=RuntimeError("boom"))),
                        ("the measurer answers the wrong length", Counting(answer=lambda items: []))):
        with patched(stub):
            out = build_rows(project, task)
        frag = {r["instance_id"]: r for r in out["fragment"]["tests"]}
        check_eq(f"F-A ({label}): each row carries the block the manifest already held, unchanged",
                 {i: nov(frag[i]) for i in blocks}, blocks)
        check(f"F-A ({label}): ...as its own copy, not the manifest's object",
              all("novelty" in frag[i] and frag[i]["novelty"] is not rows_before[i]["novelty"] for i in blocks))
        check_eq(f"F-A ({label}): the note naming the failure stays, once",
                 sum(1 for n in out["notes"] if "novelty could not be measured" in n), 1)
        check(f"F-A ({label}): and a second note says the stored measurement was not refreshed",
              any("kept as it was, not refreshed" in n for n in out["notes"]), str(out["notes"]))
        merged, _s = manifest_put.merge(before, out["fragment"])
        rows_after = rows_of(merged)
        check_eq(f"F-A ({label}): after the merge every block is what it was, its measured_at too",
                 {i: rows_after[i].get("novelty") for i in blocks}, {i: rows_before[i]["novelty"] for i in blocks})
        with in_project(project):
            needs_after = {i: PL.proof_required(rows_after[i], merged) for i in blocks}
        check_eq(f"F-A ({label}): a required test is still required, an untouched one still is not",
                 needs_after, needs_before)
        check("F-A: every row keeps its generated_from (the writer's re-run is still the writer's)",
              all(r.get("generated_from") for r in frag.values()))

    print("-- t-187 F-A edge (i): nothing stored for the row - it stays keyless and carries generated_from")
    proj_n, task_n = fixture("s0", made=made)
    edit_story(proj_n)
    with patched(Counting(raises=RuntimeError("boom"))):
        empty = build_rows(proj_n, task_n)
    check("F-A (i): no stored block -> no row carries the key, every row carries generated_from",
          all("novelty" not in r and r.get("generated_from") for r in empty["fragment"]["tests"]))
    check_eq("F-A (i): ...and only the failure note is written (nothing was kept)",
             [n for n in empty["notes"] if "novelty" in n], ["novelty could not be measured (RuntimeError)"])
    merged_n, _s = manifest_put.merge(stored(task_n), empty["fragment"])
    check("F-A (i): the merge has nothing to drop: no row of the manifest gained or kept a block",
          all("novelty" not in r for r in merged_n["tests"]))
    # the stored block of ONE row: only that row gets it back
    one = stored(task_n)
    rows_of(one)
    kept_block = {"value": "changed", "basis": "stored earlier", "base": {"kind": "s0", "sha": "a" * 40},
                  "measured_on": {"tests/test_coupon.py": "b" * 64}, "measured_by": "manifest_from_tests.py",
                  "measured_at": "2026-09-30T00:00:00+00:00"}
    with patched(Counting(answer=canned("s0", "unchanged"))):
        ok_rows = build_rows(proj_n, task_n)
    merged_one, _s = manifest_put.merge(one, ok_rows["fragment"])        # the manifest now holds blocks
    target = rows_of(merged_one)["test_limit"]
    target["novelty"] = copy.deepcopy(kept_block)                         # one row's block is a known one
    (task_n / "work" / "automation-manifest.json").write_text(json.dumps(merged_one), encoding="utf-8")
    with patched(Counting(raises=RuntimeError("boom"))):
        partial = build_rows(proj_n, task_n)
    got = {r["instance_id"]: r for r in partial["fragment"]["tests"]}
    check_eq("F-A (ii): the stored block is copied onto the row unchanged - its own measured_at kept",
             nov(got["test_limit"]), kept_block)

    print("-- t-187 Q1/Q2: a stored block F-B would refuse is not copied - no loop on the writer's own fragment")
    proj_f, task_f = fixture("s0", made=made)
    edit_story(proj_f)
    check_eq("Q1: the writer's first run exits 0", cli(proj_f).returncode, 0)
    doc = stored(task_f)
    forged_blocks = {"test_limit": {"value": "new", "resolved": True},          # the item form on a row
                     "test_added": "changed",                                   # not an object (Q2)
                     "test_region[eu]": {k: v for k, v in nov(rows_of(doc)["test_region[eu]"]).items()
                                         if k != "measured_by"}}                # lacks a key
    for iid, block in forged_blocks.items():
        rows_of(doc)[iid]["novelty"] = block
    (task_f / "work" / "automation-manifest.json").write_text(json.dumps(doc), encoding="utf-8")
    with patched(Counting(raises=RuntimeError("boom"))):
        forged_out = build_rows(proj_f, task_f)
    fr = {r["instance_id"]: r for r in forged_out["fragment"]["tests"]}
    check("Q1: a forged stored block is not copied: the row stays keyless, with generated_from",
          all("novelty" not in fr[i] and fr[i].get("generated_from") for i in forged_blocks), str(forged_blocks))
    check("Q1: a sound stored block of another row is still copied",
          "novelty" in fr["test_region[us]"], str(sorted(fr["test_region[us]"])))
    env_f = dict(os.environ, CLAUDE_PROJECT_DIR=str(proj_f))
    sent = harness.run_script("manifest_put.py", "--task", TICKET, "--fragment", json.dumps(forged_out["fragment"]),
                              cwd=proj_f, env=env_f)
    check_eq("Q1: manifest_put takes the writer's fragment - no refusal, no loop", sent.returncode, 0)
    after_f = rows_of(stored(task_f))
    check("Q1: and the merge dropped the forged blocks (old manifests only)",
          all("novelty" not in after_f[i] for i in forged_blocks), str({i: after_f[i].get("novelty") for i in forged_blocks}))

    print("-- t-187 F-B: a role never writes novelty on a row")
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(project))

    def put(fragment):
        return harness.run_script("manifest_put.py", "--task", TICKET, "--fragment", json.dumps(fragment),
                                  cwd=project, env=env)

    row_full = copy.deepcopy(blocks["test_limit"])
    hash_before = tree_hash(task)
    refused = {
        "the spec's fragment: value unchanged, resolved true": {"value": "unchanged", "resolved": True},
        "resolved false beside a full row form": dict(row_full, resolved=False),
        "resolved true beside a full row form": dict(row_full, resolved=True),
        "a row form without measured_by": {k: v for k, v in row_full.items() if k != "measured_by"},
        "a row form without measured_on": {k: v for k, v in row_full.items() if k != "measured_on"},
        "the item form with a basis": {"value": "unchanged", "basis": "by hand", "resolved": True},
        "a block that is not an object (a string)": "unchanged",
        "a block that is null": None,
        "a block that is a list": ["unchanged"],
    }
    for label, block in refused.items():
        result = put({"tests": [{"instance_id": "test_limit", "file": "tests/test_coupon.py", "novelty": block}]})
        check_eq(f"F-B: {label} -> exit 3", result.returncode, 3)
        check(f"F-B: {label}: the refusal names the field, the row and the door",
              all(w in result.stderr for w in ("`novelty`", "test_limit", "manifest_from_tests.py",
                                               "a role never writes novelty", "This is a repair")),
              result.stderr[-400:])
        check_eq(f"F-B: {label}: the task folder (manifest and event log) is byte for byte as it was",
                 tree_hash(task), hash_before)
    mixed = put({"tests": [{"instance_id": "test_added", "novelty": dict(row_full)},
                           {"instance_id": "test_limit", "novelty": {"value": "unchanged", "resolved": True}}]})
    check_eq("F-B: one bad row refuses the whole fragment, the good row is not half-written",
             (mixed.returncode, tree_hash(task)), (3, hash_before))
    check_in("F-B: and the refusal names only the bad row", "test_limit", mixed.stderr)
    check_not_in("F-B: the good row is not named", "test_added", mixed.stderr)
    with in_project(project):
        forged_needs = PL.proof_required(rows_of(stored(task))["test_limit"], stored(task))
    check_eq("F-B: test_limit stayed required through every refused fragment", forged_needs, True)

    accepted = put({"tests": [{"instance_id": "test_limit", "file": "tests/test_coupon.py",
                               "novelty": dict(row_full, basis="a full row form, as the writer writes it")}]})
    check_eq("F-B control: a full row-form block is accepted as today (the F-2 trust)", accepted.returncode, 0)
    check_eq("F-B control: ...and is stored as sent", nov(rows_of(stored(task))["test_limit"]).get("basis"),
             "a full row form, as the writer writes it")
    critic = put({"tests": [{"instance_id": "test_limit", "file": "tests/test_coupon.py",
                             "critic_verdict": "approved"}]})
    check_eq("F-B control: a role's patch with no `novelty` key at all is accepted", critic.returncode, 0)
    check_eq("F-B control: ...and leaves the measured block as it was",
             nov(rows_of(stored(task))["test_limit"]).get("basis"), "a full row form, as the writer writes it")


# --- HF2-12 part 12b (EP1-18 (a), TP1-12586): the marker writes the red rows, the writer keeps the hand-sent ones,
# --- and the row form says what each `tests[]` row still lacks ----------------------------------------------------------

def _hf_build(root, task, src, rel="tests/test_hf.py"):
    """`MFT.build` over one test file, with the novelty measure stubbed (the keys below are not about it)."""
    import manifest_from_tests as MFT
    (root / rel).write_text(src, encoding="utf-8")
    with patched(Counting(answer=canned("none", "new"))):
        return MFT.build(MFT.Story(TICKET, task), [MFT.TestFile(root / rel, rel)], DISPATCH, project=root)


def _hf_refusal(root, task, src) -> str:
    import manifest_from_tests as MFT
    try:
        _hf_build(root, task, src)
    except MFT.Refusal as exc:
        return str(exc)
    return ""


def _marker(kwargs: str, on="function") -> str:
    """A test file with a `qa` marker on `test_x` and one `qa_unresolved(case="TC-002", <kwargs>)` on the module, the
    class or the function."""
    mark = f'pytest.mark.qa_unresolved(case="TC-002", {kwargs})'
    head = 'import pytest\n\n\n'
    if on == "module":
        return head + f'pytestmark = [{mark}]\n\n\n@pytest.mark.qa(case="TC-001", then=[1])\ndef test_x(client):\n    assert client\n'
    if on == "class":
        return head + f'@{mark}\nclass TestK:\n    @pytest.mark.qa(case="TC-001", then=[1])\n    def test_x(self):\n        assert 1\n'
    return head + f'@pytest.mark.qa(case="TC-001", then=[1])\n@{mark}\ndef test_x(client):\n    assert client\n'


BLOCKED_KW = 'reason="blocked_by_check", then=[2, 3], blocking_check="TC-001", detail="check Then 2 and 3 once TC-001 is fixed"'
HF_PARAM_PY = '''import pytest


@pytest.mark.parametrize("v", [
    pytest.param(1, id="one", marks=[pytest.mark.qa(case="TC-001", then=[1]),
                                     pytest.mark.qa_unresolved(case="TC-001", then=[2], reason="blocked_by_check",
                                                               blocking_check="TC-002", detail="d")]),
    pytest.param(2, id="two", marks=pytest.mark.qa(case="TC-001", then=[1]))])
def test_p(v):
    assert v
'''


def hf2_12b() -> None:
    root = harness.temp_project("qa-mft-12b-")
    try:
        task = seed(root)
        hf_k1_k4(root, task)
        hf_k5_k6(root, task)
    finally:
        harness.cleanup(root)
    hf_k7()
    hf_k8()


def hf_k1_k4(root, task) -> None:
    import manifest_from_tests as MFT
    print("-- HF2-12b K1: one list of the keywords; the registration lines are made from it")
    for word in MFT.UNRESOLVED_KWARGS + MFT.QA_KWARGS:
        check_in(f"K1: `{word}` is in the registration help", word, MFT.REGISTRATION_HELP)
    check("K1: the three new keywords and `partitions` are in the line a project pastes",
          all(w in MFT._UNRESOLVED_LINE for w in ("instance_ids", "thens", "blocking_check", "partitions")), MFT._UNRESOLVED_LINE)
    check_eq("K1: the line IS the tuple (assembled from it, not a second list)", MFT._UNRESOLVED_LINE,
             f"{MFT.MARK_UNRESOLVED}({', '.join(MFT.UNRESOLVED_KWARGS)}): qa-factory unresolved case")

    print("-- HF2-12b K2: instance_ids is a slice of the case, never the case")
    src = _marker('reason="contradicts_requirement", instance_ids=["test_x"], thens=[3, 2, 3], detail="d"')
    out = _hf_build(root, task, src)
    row = out["fragment"]["unresolved"][0]
    check_eq("K2/K3: the row names its instances and its red Thens (sorted, no repeats)",
             (row["case"], row["reason"], row["instance_ids"], row["thens"]),
             ("TC-002", "contradicts_requirement", ["test_x"], [2, 3]))
    check_eq("K2: a slice is not the whole case: no whole-case flag", out["cases"]["TC-002"]["whole_case_unresolved"], False)
    check_eq("K2: ...and no echo row per clause is written for it",
             [b for b in out["fragment"]["then_bindings"] if b["case"] == "TC-002"], [])
    check("K2: the id the files hold raises no note", not any("instance_ids names" in n for n in out["notes"]), str(out["notes"]))
    one = _hf_build(root, task, _marker('reason="impossible", instance_ids="test_x", detail="d"'))
    check_eq("K2: one string is a list of one", one["fragment"]["unresolved"][0]["instance_ids"], ["test_x"])
    whole = _hf_build(root, task, _marker('reason="impossible", detail="d"'))
    check_eq("K2 control: the same row without the key IS the whole case (and echoes its clauses)",
             (whole["cases"]["TC-002"]["whole_case_unresolved"],
              len([b for b in whole["fragment"]["then_bindings"] if b["case"] == "TC-002"])), (True, 3))
    ghost = _hf_build(root, task, _marker('reason="impossible", instance_ids=["test_ghost"], detail="d"'))
    check_in("K2: an id neither the files nor the manifest hold is a note, not a refusal",
             "instance_ids names test_ghost, which neither these files nor the manifest hold", ghost["notes"])
    kept = _hf_build(root, task, _marker('reason="impossible", instance_ids=["test_other"], detail="d"'))
    check("K2: ...an id the MANIFEST holds (another window's test) is not", not any("instance_ids names" in n for n in kept["notes"]))
    got = _hf_refusal(root, task, _marker('reason="impossible", instance_ids=["a"], then=[1], detail="d"'))
    check_in("K2: with `then` -> refused, naming the line", "a row with `then=[n]` is one Then of the test the marker sits on - drop one of them", got)
    check_in("K2: ...and the file and line", "tests/test_hf.py:", got)
    for label, value in (("a number", "5"), ("an empty list", "[]"), ("an empty element", '[""]'), ("a non-string", "[1]"), ("a dict", '{"a": 1}')):
        got = _hf_refusal(root, task, _marker(f'reason="impossible", instance_ids={value}, detail="d"'))
        check_in(f"K2: {label} -> refused with the shape", "`instance_ids` lists instance ids as strings (`instance_ids=[\"test_x[a]\"]`), got", got)

    print("-- HF2-12b K3: thens belongs to contradicts_requirement alone")
    got = _hf_refusal(root, task, _marker('reason="impossible", thens=[1], detail="d"'))
    check_in("K3: another reason -> refused", "`thens` belongs to reason=\"contradicts_requirement\" (the red Then of the case), not to 'impossible'", got)
    got = _hf_refusal(root, task, _marker('reason="contradicts_requirement", thens=[1], then=[2], detail="d"'))
    check_in("K3: with `then` -> refused", "`thens=[n]` names, on the case's contradicts_requirement row, the Then that is red - use one of them", got)
    check_in("K3: a Then that is no number -> the number refusal", "lists the numbers of the case's Then clauses",
             _hf_refusal(root, task, _marker('reason="contradicts_requirement", thens=[0], detail="d"')))
    outside = _hf_build(root, task, _marker('reason="contradicts_requirement", thens=[9], detail="d"'))
    check_eq("K3: a number outside the case is written (D1 (iii) and the precheck catch it)",
             outside["fragment"]["unresolved"][0]["thens"], [9])

    print("-- B-M1 (t-1682): field_absent rides on the contradicts_requirement row and survives the manifest_put merge")
    import manifest_put
    block = '{"then": 2, "field": "price", "read_from": "GET /api/cart", "shape_ref": "src/api/cart.ts:14"}'
    out = _hf_build(root, task, _marker(f'reason="contradicts_requirement", thens=[2], field_absent={block}, detail="d"'))
    row = out["fragment"]["unresolved"][0]
    check_eq("B-M1: the marker writes the block onto the row, whole",
             row.get("field_absent"), {"then": 2, "field": "price", "read_from": "GET /api/cart", "shape_ref": "src/api/cart.ts:14"})
    merged, _s = manifest_put.merge({"tests": []}, out["fragment"])
    stored_row = [r for r in merged.get("unresolved") or [] if r.get("case") == "TC-002"]
    check_eq("B-M1 round trip: the stored row still carries the block (the automator's `field_absent` rule)",
             stored_row[0].get("field_absent") if stored_row else None, row["field_absent"])
    check_in("B-M1: another reason is refused", "`field_absent` belongs to the case's reason=\"contradicts_requirement\"",
             _hf_refusal(root, task, _marker(f'reason="impossible", field_absent={block}, detail="d"')))
    check_in("B-M1: a block without `shape_ref` is refused, naming it", "missing or empty: shape_ref",
             _hf_refusal(root, task, _marker('reason="contradicts_requirement", field_absent={"then": 2, "field": "p", "read_from": "x"}, detail="d"')))
    check_in("B-M1: a block that is no object is refused", "missing or empty: then, field, read_from, shape_ref",
             _hf_refusal(root, task, _marker('reason="contradicts_requirement", field_absent="price", detail="d"')))

    print("-- HF2-12b K4: blocked_by_check is a then_bindings row per instance that holds the Then")
    out = _hf_build(root, task, _marker(BLOCKED_KW))
    blocked = [b for b in out["fragment"]["then_bindings"] if b.get("reason") == "blocked_by_check"]
    check_eq("K4: one row per (Then, test): the shape of the spec, instance_id the test's own",
             blocked, [{"case": "TC-002", "then": n, "instance_id": "test_x", "assertion_ref": None, "status": "unresolved",
                        "reason": "blocked_by_check", "blocking_check": "TC-001",
                        "detail": "check Then 2 and 3 once TC-001 is fixed"} for n in (2, 3)])
    check_eq("K4: each row is well formed by the contract's own check", [C.then_remainder_errors(b) for b in blocked], [[], []])
    check("K4: and no unresolved[] row (the precheck refuses `blocked-check-row`)", "unresolved" not in out["fragment"])
    param = _hf_build(root, task, HF_PARAM_PY)
    check_eq("K4: on a pytest.param: the instance of THAT param only",
             [(b["then"], b["instance_id"]) for b in param["fragment"]["then_bindings"] if b.get("reason") == "blocked_by_check"],
             [(2, "test_p[one]")])
    many = _hf_build(root, task, _marker(BLOCKED_KW).replace("def test_x(client):", '@pytest.mark.parametrize("v", [1, 2])\ndef test_x(client, v):'))
    check_eq("K4: on a parametrized function: every instance holds it",
             sorted({b["instance_id"] for b in many["fragment"]["then_bindings"] if b.get("reason") == "blocked_by_check"}),
             ["test_x[1]", "test_x[2]"])
    for label, text, needle in (
            ("on a module", _marker(BLOCKED_KW, "module"), "a Then behind a red check is held by a test - put `qa_unresolved(case=, then=[n], reason=\"blocked_by_check\", blocking_check=, detail=)` on that test function"),
            ("on a class", _marker(BLOCKED_KW, "class"), "is held by a test - put `qa_unresolved("),
            ("without `then`", _marker('reason="blocked_by_check", blocking_check="TC-001", detail="d"'), "`blocked_by_check` is the reason of one Then - pass `then=[n]`"),
            ("with `blocking_check` of another reason", _marker('reason="impossible", blocking_check="TC-001", detail="d"'), "`blocking_check` belongs to reason=\"blocked_by_check\""),
            ("without `blocking_check`", _marker('reason="blocked_by_check", then=[2], detail="d"'), "a Then behind a red check is malformed: `blocking_check` must name the red check"),
            ("with a `blocking_check` of two words", _marker('reason="blocked_by_check", then=[2], blocking_check="a b", detail="d"'), "one word with no spaces"),
            ("without `detail`", _marker('reason="blocked_by_check", then=[2], blocking_check="TC-001"'), "`detail` must say what to check once the red is fixed"),
            ("with `instance_ids`", _marker(BLOCKED_KW + ', instance_ids=["test_x"]'), "a row with `then=[n]` is one Then of the test"),
            ("on a test no `qa` marker names",
             'import pytest\n\n\n@pytest.mark.qa_unresolved(case="TC-002", then=[2], reason="blocked_by_check", '
             'blocking_check="TC-001", detail="d")\ndef test_x(client):\n    assert client\n',
             "carries no `qa` marker")):
        got = _hf_refusal(root, task, text)
        check_in(f"K4 refused {label}", needle, got)
        check_in(f"K4 refused {label}: and the file and line", "tests/test_hf.py:", got)


def hf_k5_k6(root, task) -> None:
    import manifest_from_tests as MFT
    print("-- HF2-12b K5: a hand-sent blocked / contradicts row outlives a writer run (C6)")
    hand = {"case": "TC-001", "then": 2, "instance_id": "test_limit", "assertion_ref": None, "status": "unresolved",
            "reason": "blocked_by_check", "blocking_check": "TC-002", "detail": "d"}
    red = dict(hand, then=3, reason="contradicts_requirement")
    handed = {"case": "TC-001", "then": 4, "instance_id": None, "assertion_ref": None, "status": "unresolved",
              "reason": "handed_to_person", "detail": "d"}
    stale = {"case": "TC-001", "then": 1, "instance_id": "test_limit_old", "assertion_ref": "x:1", "status": "covered"}
    mine = [{"case": "TC-001", "then": 1, "instance_id": "test_limit", "assertion_ref": "x:2", "status": "covered"}]
    notes: list = []
    harness.use_project(root)
    got = MFT._merge_bindings([hand, red, handed, stale], mine, {"test_limit"}, [], notes)
    check_eq("K5 (i): re-running the writer keeps a `blocked_by_check` row of one of its instances", hand in got, True)
    check_eq("K5 (ii): ...and a `contradicts_requirement` Then row", red in got, True)
    check_eq("K5 (iv): the stale covered row of a claimed Then goes; the handed row of ANOTHER Then stays as it did",
             got, [hand, red, handed] + mine)
    check_eq("K5 (vi): one note says how many stayed and of which reason",
             notes, ["kept 2 hand-sent then_bindings row(s) the markers do not write (blocked_by_check, contradicts_requirement)"])
    gone = MFT._merge_bindings([hand, handed], mine, {"test_limit"}, ["TC-001"], [])
    check_eq("K5 (iv): a case the markers declare wholly unresolved still drops a handed row, and keeps the hand-sent blocked one",
             gone, [hand] + mine)
    same = [dict(r, status="covered", reason=None, assertion_ref="x:9") for r in [hand]]
    replaced = MFT._merge_bindings([hand], same, {"test_limit"}, [], [])
    check_eq("K5 (iii): the author bound that Then on that very test: the hand row is replaced, not kept beside it", replaced, same)
    other = MFT._merge_bindings([hand], [dict(same[0], instance_id="test_other_one")], {"test_other_one"}, [], [])
    check_eq("K5: a covered row of the same Then on ANOTHER test is no conflict for the writer", other, [hand, dict(same[0], instance_id="test_other_one")])
    listed = dict(hand, then=[2])
    check_eq("K5 (v): a row whose `then` is a list stays in place and the writer does not crash on it",
             MFT._merge_bindings([listed], mine, {"test_limit"}, [], []), [listed] + mine)
    quiet: list = []
    MFT._merge_bindings([stale], mine, set(), [], quiet)
    check_eq("K5: no hand row -> no note", quiet, [])
    print("-- HF2-12b K5 through the CLI: the row is still in the manifest after the writer ran twice")
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(root))
    (root / "tests" / "test_coupon.py").write_text(TEST_PY, encoding="utf-8")
    (root / "tests" / "data_coupon.py").write_text(DATA_PY, encoding="utf-8")
    check_eq("K5 CLI: the first write", run(root).returncode, 0)
    put = harness.run_script("manifest_put.py", "--task", TICKET, "--fragment",
                             json.dumps({"then_bindings": [dict(hand, instance_id="test_limit", then=3)]}), cwd=root, env=env)
    check_eq("K5 CLI: a hand fragment puts the blocked row", put.returncode, 0)
    again = run(root, "--json")
    check_eq("K5 CLI: the writer runs again", again.returncode, 0)
    rows = json.loads((root / "qa-factory" / "artifacts" / TICKET / "work" / "automation-manifest.json").read_text(encoding="utf-8"))["then_bindings"]
    check("K5 CLI: ...and the hand-sent row is still there", any(r.get("reason") == "blocked_by_check" and r["then"] == 3 for r in rows), str(rows)[:300])
    check("K5 CLI: ...and the run said so", any(n.startswith("kept 1 hand-sent then_bindings row(s)") for n in json.loads(again.stdout)["notes"]))
    check_in("K5 CLI: the text mode prints the note", "note: kept 1 hand-sent then_bindings row(s) the markers do not write (blocked_by_check)",
             run(root).stdout)

    print("-- HF2-12b K6: the Then number has ONE reader")
    source = Path(MFT.__file__).read_text(encoding="utf-8")
    check("K6: no `int(row.get(\"then\")` and no `int(r[\"then\"])` in the writer", 'int(row.get("then")' not in source and 'int(r["then"])' not in source)
    check("K6 control: the same search finds the reader it was replaced by", source.count("C.then_number(") >= 1, str(source.count("C.then_number(")))
    check("K6: the writer does not keep a copy of the marker list - the lazy import keeps `window_record` out of the module",
          subprocess_modules("import sys, manifest_from_tests; print('window_record' in sys.modules, 'acceptance' in sys.modules)") == "False False")


def subprocess_modules(code: str) -> str:
    done = subprocess.run([sys.executable, "-B", "-c", code], cwd=str(harness.SCRIPTS), capture_output=True, text=True,
                          env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"), timeout=120)
    return done.stdout.strip() or done.stderr.strip()


def _schema2_plan(task) -> None:
    path = task / "work" / "test-plan.json"
    plan = json.loads(path.read_text(encoding="utf-8"))
    for row in plan["rows"]:
        row["schema_version"] = 2
    path.write_text(json.dumps(plan), encoding="utf-8")


def _form_root(plan2=False, profiles=None):
    root = harness.temp_project("qa-mft-form-")
    task = seed(root)
    (root / "tests" / "test_coupon.py").write_text(TEST_PY, encoding="utf-8")
    (root / "tests" / "data_coupon.py").write_text(DATA_PY, encoding="utf-8")
    if plan2:
        _schema2_plan(task)
    if profiles:
        path = root / "qa-factory" / "config.json"
        cfg = json.loads(path.read_text(encoding="utf-8"))
        cfg["profiles"] = profiles
        path.write_text(json.dumps(cfg), encoding="utf-8")
    return root, task


FOUR = ("assertion_id", "defect_location", "change_disposition", "change_basis_ref")


def _filled(iid: str, **over) -> dict:
    return dict({"instance_id": iid, "assertion_id": "tests/test_coupon.py:9", "defect_location": "src/coupon.py:3",
                 "change_disposition": "new_or_changed", "change_basis_ref": "manifest:TC-001"}, **over)


def _manifest_rows(task) -> dict:
    doc = json.loads((task / "work" / "automation-manifest.json").read_text(encoding="utf-8"))
    return {C.test_instance_id(t): t for t in doc["tests"]}


def hf_k7() -> None:
    import manifest_from_tests as MFT
    import manifest_put
    import window_record as WR
    print("-- HF2-12b K7: the row form is printed after the write, from the saved manifest, and never sent")
    root, task = _form_root()
    try:
        env = dict(os.environ, CLAUDE_PROJECT_DIR=str(root))
        first = run(root, "--json")
        check_eq("K7: the write exits 0", first.returncode, 0)
        out = json.loads(first.stdout)
        ids = sorted(t["instance_id"] for t in out["fragment"]["tests"])
        form = out["row_form"]
        check_eq("K7 (a): a slot per row of THIS run, and only these (not the other window's `test_other`)",
                 sorted(t["instance_id"] for t in form["tests"]), ids)
        check_eq("K7 (a): each row asks for the four fields the automator writes, as null",
                 form["tests"][0], {"instance_id": form["tests"][0]["instance_id"], **dict.fromkeys(FOUR)})
        check_eq("K7 (a): the legend says what each holds, in the carrier's words",
                 form["legend"], {f: WR.REQUIRED_ROW_FIELDS[f].what for f in FOUR})
        check_eq("K7: --json gained one key, `row_form`",
                 sorted(out), sorted(["ok", "dry_run", "fragment", "fragment_path", "cases", "notes", "scope", "manifest_put", "row_form"]))
        check("K7 (c): the fragment on disk holds no automator field and no null (the form is never sent)",
              all(f not in row for row in json.loads((task / "work" / "manifest-fragments" / Path(out["fragment_path"]).name)
                                                     .read_text(encoding="utf-8"))["tests"] for f in FOUR))
        text = run(root)
        check_in("K7: the text mode prints the form after the summary", "row form - each null is a field", text.stdout)
        check("K7: ...after the summary of `tests[]` and the cases", text.stdout.index("cases:") < text.stdout.index("row form -"), text.stdout[:400])
        check_in("K7: ...naming the door with the task", "manifest_put.py --task QA-700 --fragment <file>", text.stdout)
        check_in("K7: ...and one legend line per field", "  `defect_location`: " + WR.REQUIRED_ROW_FIELDS["defect_location"].what, text.stdout)

        print("-- K7 (b): what the role wrote stays, and the form no longer lists it")
        put = harness.run_script("manifest_put.py", "--task", TICKET, "--fragment", json.dumps({"tests": [_filled("test_limit")]}), cwd=root, env=env)
        check_eq("K7 (b): the role's fragment is taken", put.returncode, 0)
        after = json.loads(run(root, "--json").stdout)
        check_eq("K7 (b): the writer ran again: the fields are still on the row (it never sent them)",
                 {f: _manifest_rows(task)["test_limit"].get(f) for f in FOUR}, {f: _filled("test_limit")[f] for f in FOUR})
        check_eq("K7 (b): ...and the form asks for the other rows only",
                 sorted(t["instance_id"] for t in after["row_form"]["tests"]), [i for i in ids if i != "test_limit"])

        print("-- K7 (g): a null left in the form is an empty field, named again; a filled form lays on the rows")
        nulls = {"tests": [dict(t) for t in after["row_form"]["tests"]]}
        view, _ = manifest_put.merge(json.loads((task / "work" / "automation-manifest.json").read_text(encoding="utf-8")), nulls)
        left = {C.test_instance_id(t): WR.row_field_gaps(t) for t in view["tests"] if C.test_instance_id(t) in ids}
        check_eq("K7 (f): the form sent as it is leaves every field empty: all four are missing again, the row is not dropped",
                 [f for f, _p in left["test_region[eu]"]], list(FOUR))
        fill = {"tests": [_filled(t["instance_id"]) for t in after["row_form"]["tests"]]}
        view, _ = manifest_put.merge(json.loads((task / "work" / "automation-manifest.json").read_text(encoding="utf-8")), fill)
        check_eq("K7 (h): the filled form lays on the rows: the same rows, nothing dropped, no gap left",
                 (len(view["tests"]), [WR.row_field_gaps(t) for t in view["tests"] if C.test_instance_id(t) in ids]),
                 (len(json.loads((task / "work" / "automation-manifest.json").read_text(encoding="utf-8"))["tests"]), [[]] * len(ids)))
        sent = harness.run_script("manifest_put.py", "--task", TICKET, "--fragment", json.dumps(fill), cwd=root, env=env)
        check_eq("K7 (h): ...and manifest_put takes it", sent.returncode, 0)
        done = json.loads(run(root, "--json").stdout)
        check_eq("K7 (d): everything filled -> an empty form", done["row_form"], {"tests": [], "legend": {}})
        check_in("K7 (d): ...and the text mode says so", "row fields: every row of this window carries them", run(root).stdout)

    finally:
        harness.cleanup(root)
    root, task = _form_root()      # a fresh story: no row of it is filled yet
    try:
        print("-- K7 (e): --collect rewrote an id: the form carries the new one")
        import node_ids
        story = MFT.Story(TICKET, task)
        with patched(Counting(answer=canned("none", "new"))):
            built = MFT.build(story, [MFT.TestFile(root / f, f) for f in ("tests/test_coupon.py", "tests/data_coupon.py")], DISPATCH, project=root)
        kept_collect = node_ids.collect
        node_ids.collect = lambda *a, **k: [f"{t['file']}::{t['instance_id'].replace('[eu]', '[chromium-eu]')}" for t in built["fragment"]["tests"]]
        try:
            fragment = MFT.resolve_through_pytest(built["fragment"], ["python", "-m", "pytest"], str(root), [])
        finally:
            node_ids.collect = kept_collect
        harness.use_project(root)
        notes: list = []
        form_dry, lines = MFT._form_after_write(task, story, fragment, True, 0, notes)
        check("K7 (e): the form names the id pytest collects and not the author's",
              "test_region[chromium-eu]" in json.dumps(form_dry["tests"]) and "test_region[eu]" not in json.dumps(form_dry["tests"]),
              json.dumps(form_dry["tests"])[:300])
        check_in("K7 (d'): a dry run says the rows are not in the manifest yet", "send it after the write: these rows are not in the manifest yet", notes)

        print("-- K7 (i): a fragment that was not written leaves no form")
        notes = []
        check_eq("K7 (i): put_code 3 -> no form", MFT._form_after_write(task, story, fragment, False, 3, notes), (None, []))
        check_eq("K7 (i): ...and the note says why", notes, ["row form skipped: the fragment was not written"])
    finally:
        harness.cleanup(root)

    print("-- K7 (d): --dry-run prints the form from the merge, writes nothing")
    root, task = _form_root(plan2=True)
    try:
        before = tree_hash(task)
        dry = json.loads(run(root, "--dry-run", "--json").stdout)
        check_eq("K7 (d): a dry run writes nothing", tree_hash(task), before)
        check("K7 (d): ...the form is there, from the merged view", len(dry["row_form"]["tests"]) == 7, str(dry["row_form"])[:300])
        check_in("K7 (d): ...with the note", "send it after the write: these rows are not in the manifest yet", dry["notes"])
        legend = dry["row_form"]["legend"]
        check_in("K7 (obligation_refs): a marker field is in the legend and names the marker", "qa(obligations=", legend["obligation_refs"])
        check("K7 (obligation_refs): ...and has NO slot (a hand value would not carry the plan's hash)",
              all("obligation_refs" not in t for t in dry["row_form"]["tests"]))
        check("K7 (obligation_refs): the row that has it (the marker wrote it) asks for the four only",
              [t for t in dry["row_form"]["tests"] if t["instance_id"] == "test_limit"] == [{"instance_id": "test_limit", **dict.fromkeys(FOUR)}])
    finally:
        harness.cleanup(root)

    print("-- K7 (f): two profiles on one test root: a `profile_id` slot, the candidates in the legend")
    shared = [{"profile_id": "api", "roots": {"test": "tests"}}, {"profile_id": "ui", "roots": {"test": "tests"}}]
    root, task = _form_root(profiles=shared)
    try:
        form = json.loads(run(root, "--json").stdout)["row_form"]
        check("K7 (f): every row has a `profile_id` slot", form["tests"] and all("profile_id" in t and t["profile_id"] is None for t in form["tests"]))
        check_in("K7 (f): the legend names both candidates", "one of: api, ui", form["legend"]["profile_id"])
        put = harness.run_script("manifest_put.py", "--task", TICKET, "--fragment",
                                 json.dumps({"tests": [_filled("test_limit", profile_id="ui")]}), cwd=root,
                                 env=dict(os.environ, CLAUDE_PROJECT_DIR=str(root)))
        check_eq("K7 (f): the role names the profile", put.returncode, 0)
        again = json.loads(run(root, "--json").stdout)["row_form"]
        check("K7 (f): ...and that row is not asked again", "test_limit" not in [t["instance_id"] for t in again["tests"]])
    finally:
        harness.cleanup(root)


def charter_missing(carrier) -> list:
    """The carrier fields the role writes (by fragment or by marker) that the charter does not name in backticks."""
    text = (harness.PLUGIN_ROOT / "agents" / "qa-automator.md").read_text(encoding="utf-8")
    return [f for f, spec in carrier.items() if spec.filled_by in ("automator", "marker") and f"`{f}`" not in text]


def hf_k8() -> None:
    import window_record as WR
    print("-- HF2-12b K8: the charter names every field the role writes (census against the carrier)")
    text = (harness.PLUGIN_ROOT / "agents" / "qa-automator.md").read_text(encoding="utf-8")
    check_eq("K8: every carrier field with filled_by automator or marker stands in the charter in backticks",
             charter_missing(WR.REQUIRED_ROW_FIELDS), [])
    check_eq("K8 negative control: a carrier with a field the charter never names fails the census, by name",
             charter_missing(dict(WR.REQUIRED_ROW_FIELDS, zzz_not_a_field=WR.REQUIRED_ROW_FIELDS["profile_id"])), ["zzz_not_a_field"])
    sentence = [para for para in text.split("\n") if "manifest_from_tests.py` prints" in para]
    tools = text.split("## Tools")[1].split("## When to ask")[0]            # X7-1: one bullet of the Tools section, no numbered item
    check("K8: ONE sentence names the writer's form and the four fields and `profile_id`, in one bullet of Tools",
          len(sentence) == 1 and all(f"`{f}`" in tools
                                     for f in ("assertion_id", "defect_location", "change_disposition", "change_basis_ref", "profile_id")))
    check("K8: the cut bytes did not take a duty with them: the window's own test (4 words quoted before the cut) still stands in the slice",
          "the control that shows the stand, not the product, blocked it" in " ".join(
              (harness.PLUGIN_ROOT / "references" / "slices" / "qa-automator" / "artifact-contract-automation.md")
              .read_text(encoding="utf-8").split()))


# --- TQ1-7: introduced_helpers[], the trail to the analogue ---------------------------------------------------------------

HELPER_SRC = '''import pytest


class PO:
    def __init__(self):
        self.x = 1

    def read_editor_yaml(self):
        return 1

    def read_yaml(self):
        return 2


def make_thing(x):
    return x


def _old():
    return 0


@pytest.fixture
def my_fixture():
    return 3


@pytest.mark.qa(case="TC-001", then=[1])
def test_one(client):
    assert client.x() == 1
'''
CONFTEST_SRC = '''import pytest


@pytest.fixture
def conf_fx():
    return 1
'''
ROLE = ("purpose", "searched", "similar_found", "keep")


def by_name(values: dict, default: str = "unchanged"):
    """A canned `measure_many`: the value per function NAME, one answer per item (tests and helpers alike)."""
    def answer(items):
        return [{"value": values.get(i["function"], default), "basis": "canned words",
                 "base": {"kind": "s0", "sha": "a" * 40}, "measured_on": {i["test_rel"]: "b" * 64}} for i in items]
    return answer


def _helper_rows(out) -> dict:
    return {(r["file"], r["name"]): r for r in out["fragment"].get("introduced_helpers", [])}


def tq1_7() -> None:
    import manifest_put as MP
    import manifest_from_tests as MFT
    import s5_precheck as S5
    made: list = []
    try:
        print("-- TQ1-7 D1-K1/K5: a row per new or changed helper, none for an unchanged one, one measure_many call")
        project, task = fixture("s0", tests_py=HELPER_SRC, made=made)
        (project / "tests" / "conftest.py").write_text(CONFTEST_SRC, encoding="utf-8")
        values = {"read_editor_yaml": "new", "read_yaml": "unchanged", "make_thing": "changed", "my_fixture": "unknown",
                  "conf_fx": "new"}
        counter = Counting(answer=by_name(values))
        with patched(counter):
            out = build_rows(project, task, files=("tests/test_coupon.py",))
        rows = _helper_rows(out)
        check_eq("K1: the rows are the new, changed and unknown helpers of the file and of its conftest, a method as Class.method",
                 sorted(rows), [("tests/conftest.py", "conf_fx"), ("tests/test_coupon.py", "PO.read_editor_yaml"),
                                ("tests/test_coupon.py", "make_thing"), ("tests/test_coupon.py", "my_fixture")])
        check_eq("K1: a row has the scaffold, the four role fields empty, and the novelty value",
                 rows[("tests/test_coupon.py", "PO.read_editor_yaml")],
                 {"file": "tests/test_coupon.py", "name": "PO.read_editor_yaml", **{f: "" for f in ROLE}, "novelty": "new"})
        check_eq("K5: an unchanged helper, a dunder method and a test have no row",
                 [n for (_f, n) in rows if n in ("PO.read_yaml", "_old", "PO.__init__", "test_one")], [])
        check_eq("V3: ONE measure_many call for the tests and the helpers", len(counter.calls), 1)
        asked = sorted(i["function"] for i in counter.calls[0]["items"])
        check("the helper units ride in that call (the method with its class chain)",
              "read_editor_yaml" in asked and any(i.get("class_chain") == ["PO"] for i in counter.calls[0]["items"]), str(asked))
        check_eq("D1-1: `unknown` is a row with that word and a note, not silence",
                 (rows[("tests/test_coupon.py", "my_fixture")]["novelty"],
                  any("novelty: unknown" in n and "my_fixture" in n for n in out["notes"])), ("unknown", True))

        print("-- TQ1-7 D1-1: the measurer raises -> every helper is a row `unknown` with a note")
        with patched(Counting(raises=RuntimeError("no git"))):
            broke = build_rows(project, task, files=("tests/test_coupon.py",))
        check_eq("D1-1: every helper is `unknown`, none dropped (a false 'new' is allowed, silence is not)",
                 sorted({r["novelty"] for r in _helper_rows(broke).values()}), ["unknown"])
        check_eq("D1-1: six helpers stand as rows (five of the file, one of the conftest; the unchanged ones too)",
                 len(_helper_rows(broke)), 6)
        check("D1-1: and the note says the helper novelty could not be measured",
              any("novelty could not be measured" in n for n in broke["notes"]), str(broke["notes"]))

        print("-- TQ1-7 D1-3: a re-run keeps the role's words; a function that is gone takes its row; other files stay")
        stored = [{"file": "tests/test_coupon.py", "name": "PO.read_editor_yaml", "purpose": "reads the editor yaml",
                   "searched": "tests/pages/", "similar_found": "none", "keep": "", "novelty": "new"},
                  {"file": "tests/test_coupon.py", "name": "gone_fn", "purpose": "was here", "searched": "x",
                   "similar_found": "none", "keep": "", "novelty": "new"},
                  {"file": "tests/test_other.py", "name": "other_helper", "purpose": "another window's", "searched": "y",
                   "similar_found": "none", "keep": "", "novelty": "new"}]
        path = task / "work" / "automation-manifest.json"
        manifest = json.loads(path.read_text(encoding="utf-8"))
        manifest["introduced_helpers"] = stored
        path.write_text(json.dumps(manifest), encoding="utf-8")
        with patched(Counting(answer=by_name(values))):
            again = build_rows(project, task, files=("tests/test_coupon.py",))
        kept = _helper_rows(again)[("tests/test_coupon.py", "PO.read_editor_yaml")]
        check_eq("K3: the role's words survive the re-run", {f: kept[f] for f in ROLE},
                 {"purpose": "reads the editor yaml", "searched": "tests/pages/", "similar_found": "none", "keep": ""})
        check("K3: the fragment carries no row for the function that is gone",
              ("tests/test_coupon.py", "gone_fn") not in _helper_rows(again), str(sorted(_helper_rows(again))))
        merged, _ = MP.merge(json.loads(path.read_text(encoding="utf-8")), again["fragment"])
        names = sorted((r["file"], r["name"]) for r in merged["introduced_helpers"])
        check("K4: through the merge the row of the vanished function is gone",
              ("tests/test_coupon.py", "gone_fn") not in names, str(names))
        check("D1-3: the row of another file is untouched, with its role words",
              ("tests/test_other.py", "other_helper") in names
              and [r for r in merged["introduced_helpers"] if r["name"] == "other_helper"][0]["purpose"] == "another window's",
              str(merged["introduced_helpers"]))
        check_eq("K3: the merge keeps the role's words on the row that stands",
                 [r["searched"] for r in merged["introduced_helpers"] if r["name"] == "PO.read_editor_yaml"], ["tests/pages/"])

        print("-- TQ1-7 D1-2: no helper found and no key held -> no key in the fragment")
        quiet_project, quiet_task = fixture("s0", made=made)
        with patched(Counting(answer=by_name({}))):
            quiet = build_rows(quiet_project, quiet_task)
        check("D1-2: a manifest that never had the key and a call that found no helper leave the key absent",
              "introduced_helpers" not in quiet["fragment"], str(sorted(quiet["fragment"])))

        print("-- TQ1-7 D1-4: a file that is not Python gives no row and a note that the count is not made")
        import types
        notes: list = []
        java = types.SimpleNamespace(rel="src/test/java/CouponTest.java", path=Path("CouponTest.java"), tree=None)
        check_eq("D1-4: no unit for a Java file", MFT._helper_units(project, [java], notes), [])
        check("D1-4: the note names the file and says the code critic reads it whole",
              any("CouponTest.java" in n and "not a Python file" in n and "reads it whole" in n for n in notes), str(notes))

        print("-- TQ1-7 D1-K7/K8: --dry-run writes nothing; a real write reaches helper_twin_hint through manifest_put")
        project2, task2 = fixture("s0", tests_py=HELPER_SRC, made=made)
        edit_helper = project2 / "tests" / "test_coupon.py"
        edit_helper.write_text(HELPER_SRC.replace("return x\n", "return x + 1\n"), encoding="utf-8")
        before = (task2 / "work" / "automation-manifest.json").read_bytes()
        dry = cli(project2, "--dry-run", "--json", files=("tests/test_coupon.py",))
        check("K7: the dry run exits 0", dry.returncode == 0, dry.stderr + dry.stdout[-400:])
        check_eq("K7: and writes nothing to the manifest", (task2 / "work" / "automation-manifest.json").read_bytes(), before)
        check("K7: the fragment it prints carries the changed helper row",
              any(r["name"] == "make_thing" and r["novelty"] == "changed"
                  for r in json.loads(dry.stdout)["fragment"].get("introduced_helpers", [])), dry.stdout[-500:])
        real = cli(project2, files=("tests/test_coupon.py",))
        check("K8: the real write goes through manifest_put (exit 0)", real.returncode == 0, real.stderr + real.stdout[-500:])
        held = json.loads((task2 / "work" / "automation-manifest.json").read_text(encoding="utf-8"))
        row = next((r for r in held.get("introduced_helpers") or [] if r["name"] == "make_thing"), {})
        check_eq("K8: the manifest holds the scaffold the writer wrote", (row.get("novelty"), row.get("purpose")),
                 ("changed", ""))
        hints: list = []
        S5.helper_twin_hint(held, hints, task2)
        check("K8: helper_twin_hint reads that stored value and names the row", any("make_thing" in h["message"] for h in hints),
              str(hints))
        check("K8: it is a hint, and the method row names its sibling method of the same class",
              all(h["level"] == "hint" for h in hints) or not hints, str(hints))
        fragment_path = task2 / "work" / "role-fragment.json"
        fragment_path.write_text(json.dumps({"introduced_helpers": [{
            "file": "tests/test_coupon.py", "name": "make_thing", "purpose": "builds a thing", "searched": "tests/",
            "similar_found": "none"}]}), encoding="utf-8")
        env = dict(os.environ, CLAUDE_PROJECT_DIR=str(project2))
        put = harness.run_script("manifest_put.py", "--task", TICKET, "--fragment", fragment_path, cwd=project2, env=env)
        check("K8: the role's four fields go in by the real `manifest_put --fragment`", put.returncode == 0, put.stderr + put.stdout[-400:])
        filled = json.loads((task2 / "work" / "automation-manifest.json").read_text(encoding="utf-8"))
        hints = []
        S5.helper_twin_hint(filled, hints, task2)
        check("K2: a filled row (`searched`, `similar_found: none`) gives no hint for it",
              not any("`make_thing`" in h["message"] for h in hints), str(hints))
        check("K3: and the role's words are in the stored row beside the scaffold",
              [(r["purpose"], r["novelty"]) for r in filled["introduced_helpers"] if r["name"] == "make_thing"]
              == [("builds a thing", "changed")], str(filled["introduced_helpers"]))
    finally:
        for folder in made:
            harness.cleanup(folder)


SPEC_TS = """import { test, expect } from '@playwright/test';
test.describe('g', () => {
  test('@api TC-002 adds one', async () => { expect(1).toBe(1); });
  test('not ours: no case id', async () => { expect(2).toBe(2); });
});
for (const p of rows) {
  test(`TC-003 loop [${p.id}]`, async () => { expect(p).toBeTruthy(); });
}
"""
NO_ROW_NOTE = "no reader for .kt in references/detectors.json assertion_probes"


def ep1_37() -> None:
    """EP1-37 p. 1 (t-544 section 3): a file that is not Python is read by `test_source` by the data of its language. A language with
    no row is a NOTE with a door (exit 0, no row, `manifest_put` not called), never a refusal and never a pass; a file with a row and a
    marker gives rows without Then bindings; a row and no marker is a note; a row and a part it could not read is ONE refusal; `.py`
    beside `.kt` keeps its rows; `--collect` with such a file is the pytest-only door."""
    root = harness.temp_project("qa-mft-ep137-")
    try:
        task = seed(root)
        _w(root, "tests/A.kt", "class A { fun adds() { assert(1 == 1) } }\n")
        _w(root, "tests/a.spec.ts", SPEC_TS)
        _w(root, "tests/none.spec.ts", "test('nothing named', async () => { expect(1).toBe(1); });\n")
        _w(root, "tests/bad.spec.ts", "const name = 'x';\ntest(name, async () => { expect(1).toBe(1); });\n")
        before = (task / "work" / "automation-manifest.json").read_bytes()
        # --- a language with no row: a note, a door, exit 0, nothing written -------------------------------------------------------
        print("-- EP1-37: a language with no row")
        code, out, err = _dry(root, "tests/A.kt")
        check_eq("no row for .kt: exit 0, not a refusal", code, 0)
        check_eq("no row for .kt: no rows", out["fragment"], {})
        note = " ".join(out["notes"])
        check_in("the note names the file and the missing row", "tests/A.kt: " + NO_ROW_NOTE, note)
        check_in("the note names the door", "manifest_put.py --fragment", note)
        check_in("and says the cases stay unbound", "stay unbound", note)
        real = run(root, files=("tests/A.kt",))
        check_eq("a real run is exit 0 as well", real.returncode, 0)
        check_in("it says manifest_put was not called", "manifest_put.py was not called", real.stdout)
        check_in("and prints the row form of a row to write by hand", '"instance_id"', real.stdout)
        check_eq("the manifest is the bytes it was", (task / "work" / "automation-manifest.json").read_bytes(), before)
        # E-6 (t-565): the note says "the row form is printed below"; --json prints it too, in the shape the other forms have
        form = out.get("row_form") or {}
        check_eq("E-6: --json carries the row form of a note-only run (a slot with an instance_id, and a legend)",
                 (bool(form.get("tests")) and "instance_id" in form["tests"][0], bool(form.get("legend"))), (True, True))
        # E-5: a broken table is NOT "a language with no row": the file that has a row is refused, never a note
        import manifest_from_tests as MFT
        import assertion_detectors as AD
        real_table = AD.assertion_detectors

        def broken():
            raise AD.DetectorsUnreadable("references/detectors.json cannot be parsed")
        AD.assertion_detectors = broken
        refusal = ""
        try:
            files = MFT._files([str(root / "tests" / "a.spec.ts")], root)
            MFT.build(MFT.Story(TICKET, task), files, DISPATCH, project=root)
        except MFT.Refusal as exc:
            refusal = str(exc) + " ".join(getattr(exc, "problems", None) or [])
        finally:
            AD.assertion_detectors = real_table
        check_in("E-5: a .ts file with the table unusable is a refusal that names the cause, not a note", "cannot be used", refusal)
        # --- .py beside .kt: the .py rows are written, the .kt is a note ------------------------------------------------------------
        code, mixed, err = _dry(root, "tests/test_coupon.py", "tests/data_coupon.py", "tests/A.kt")
        check_eq("py + kt: exit 0", code, 0)
        check("py + kt: the .py rows are there", any(r["file"] == "tests/test_coupon.py" for r in mixed["fragment"]["tests"]))
        check_in("py + kt: and the note on the .kt", NO_ROW_NOTE, " ".join(mixed["notes"]))
        # --- a row and a marker: rows, no Then bindings ----------------------------------------------------------------------------
        print("-- EP1-37: a language with a row")
        code, got, err = _dry(root, "tests/a.spec.ts")
        check_eq("ts: exit 0", code, 0)
        rows = {r["instance_id"]: r for r in got["fragment"]["tests"]}
        check_eq("ts: one row per test whose title names a case (the bare title is the id)", sorted(rows),
                 sorted(["TC-002 adds one", "TC-003 loop"]))
        check("ts: the tag is not in the instance id", all("@api" not in i for i in rows))
        check("ts: the looped test is generated", rows["TC-003 loop"].get("generated") is True)
        check_eq("ts: the case and the file", (rows["TC-002 adds one"]["covers"], rows["TC-002 adds one"]["file"]),
                 (["TC-002"], "tests/a.spec.ts"))
        check_eq("ts: no Then bindings are written", got["fragment"].get("then_bindings"), None)
        check_in("ts: and the note says whose they are", "Then bindings are the author's: this language has no marker", " ".join(got["notes"]))
        # --- a row, no case id in any title: a note, not a silent zero ----------------------------------------------------------------
        code, none, err = _dry(root, "tests/none.spec.ts")
        check_eq("a row and no marker: exit 0, no rows", (code, none["fragment"]), (0, {}))
        check_in("a row and no marker: the note", "read as typescript, no test carries a case id the brief names", " ".join(none["notes"]))
        # --- a row and a part it could not read: ONE refusal -----------------------------------------------------------------------
        code, bad, err = _dry(root, "tests/bad.spec.ts", "tests/a.spec.ts")
        check_eq("an unread test: refused", code, 2)
        check_in("an unread test: the file and line and the reason", "tests/bad.spec.ts:2: test not read: its title is not a string literal", err + json.dumps(bad))
        # --- --collect is pytest's ----------------------------------------------------------------------------------------------------
        done = run(root, "--collect", "--", sys.executable, "-m", "pytest", files=("tests/A.kt",))
        check_eq("--collect with a .kt: refused", done.returncode, 2)
        check_in("--collect with a .kt: the door", "applies to pytest only", done.stderr + done.stdout)
        done = run(root, "--collect", "--", sys.executable, "-m", "pytest", files=("tests/a.spec.ts",))
        check_eq("--collect with a .ts that has a row: refused too", done.returncode, 2)
        # --- the real write of ts rows goes through manifest_put ---------------------------------------------------------------------
        real = run(root, files=("tests/a.spec.ts",))
        check("ts: the real write is accepted by manifest_put", real.returncode == 0, real.stderr + real.stdout[-400:])
        held = json.loads((task / "work" / "automation-manifest.json").read_text(encoding="utf-8"))
        check("ts: the manifest holds the rows", {"TC-002 adds one", "TC-003 loop"} <= {t.get("instance_id") for t in held["tests"]},
              str([t.get("instance_id") for t in held["tests"]]))
    finally:
        harness.cleanup(root)


if __name__ == "__main__":
    main()
