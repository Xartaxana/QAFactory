"""critic_rollcall.py --apply-fixes: the last round's exact replacements land by code.

TP1-15045: the critic's `approve_with_fixes` verdict for TC-012 and TC-014 carried exact
replacement text twice, and both times it needed a `qa-case-designer` dispatch to land — which
was then blocked. This exercises the fix against a synthetic case pair (fast, isolated)
and against a COPY of the real `critic-findings.md`/TC-012.md/TC-014.md that produced the incident (the
shapes a hand-built fixture would not reliably reproduce).

Runnable on its own: `python -B scripts/tests/test_critic_rollcall_apply_fixes.py`.
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import check, check_eq, cleanup, finish, temp_project, use_project  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import case_versions as V  # noqa: E402
import contract as C  # noqa: E402
import critic_rollcall as R  # noqa: E402

LIVE_SAMPLE_ENV = "QA_FACTORY_LIVE_SAMPLE"


def live_sample(value):
    """(folder, ""), or (None, reason): the live sample is an absolute path to an artifacts folder such as
    <project>/qa-factory/artifacts/TP1-15045, given in QA_FACTORY_LIVE_SAMPLE. Unset or empty is
    unset; the reason names the variable and never the value."""
    if not value:
        return None, f"{LIVE_SAMPLE_ENV} is not set"
    path = Path(value)
    if not path.is_absolute():
        return None, f"{LIVE_SAMPLE_ENV}: absolute path expected"
    if path.is_file():
        return None, f"{LIVE_SAMPLE_ENV} is not a folder"
    if not path.is_dir():
        return None, f"{LIVE_SAMPLE_ENV} does not exist"
    return path, ""


def skip(reason: str) -> None:
    """A visible skip in BOTH runners: pytest.skip when pytest is loaded IN THIS PROCESS (`"pytest" in sys.modules`:
    PYTEST_CURRENT_TEST would also be inherited by a child process of a pytest test, which has no pytest to skip
    with); a `SKIP:` line in the script runner / selftest, where it is neither a pass nor a fail. Edge: a script
    that imports pytest without running under it gets pytest.skip's uncaught Skipped (non-zero), not a SKIP line."""
    if "pytest" in sys.modules:
        import pytest
        pytest.skip(reason)
    print(f"SKIP: {reason}")


def write_case(path: Path, case_id: str, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"---\nid: {case_id}\nstatus: Draft\ntask: QA-1\n---\nRequirements: R-1\nPlan row: TS-1\n"
        f"{body}\n", encoding="utf-8")


def pin(task: Path, store: Path, source: Path) -> dict:
    record = V.create_version(store, source)
    V.pin(task, record)
    return record


def test_synthetic_fix_lands_and_reports_json() -> None:
    root = temp_project("qa-factory-critic-apply-")
    try:
        use_project(root)
        task = root / "qa-factory" / "artifacts" / "QA-1"
        store = task / "work" / "test-cases"
        source = task / "work" / "test-cases" / "area" / "TC-100.md"
        write_case(source, "TC-100", "Given a widget.\nWhen clicked.\nThen it turns blue.\n")
        record = pin(task, store, source)
        findings = task / "work" / "test-cases" / "area" / "critic-findings.md"
        findings.parent.mkdir(parents=True, exist_ok=True)
        findings.write_text(
            "## Roll-call\n\n| plan row | case | reviewed | note |\n|---|---|---|---|\n"
            "| TS-1 | TC-100 | yes | concern C-1 |\n\n1 of 1 reviewed.\n\n"
            "## Fixes without a new round\n\n```json\n[\n"
            '  {"case_id": "TC-100", "locator": "Then", "find": "it turns blue.", '
            f'"replace": "it turns green.", "reviewed_version": "{record["version"]}"}}\n'
            "]\n```\n\nVerdict: approve_with_fixes\n", encoding="utf-8")

        result = R.apply_fixes(findings, task)
        check_eq("one fix applied, none skipped", (len(result["applied"]), len(result["skipped"])), (1, 0))
        new_text = source.read_text(encoding="utf-8")
        check("the source case file itself carries the replacement", "it turns green." in new_text)
        links = {l["case_id"]: l for l in C.story_case_links(task)}
        check("the pin moved off the reviewed version", links["TC-100"]["version"] != record["version"])
        check_eq("no debt remains once the fix landed", R.findings_errors(findings, task_root=task), [])
    finally:
        cleanup(root)


def test_ambiguous_find_stays_a_reported_debt() -> None:
    root = temp_project("qa-factory-critic-apply-")
    try:
        use_project(root)
        task = root / "qa-factory" / "artifacts" / "QA-2"
        store = task / "work" / "test-cases"
        source = task / "work" / "test-cases" / "area" / "TC-200.md"
        # "status" appears twice below — the exact replacement the critic supplied is
        # ambiguous, and an ambiguous edit must never be guessed at.
        write_case(source, "TC-200", "Then 1: status matches.\nThen 2: status matches.\n")
        record = pin(task, store, source)
        findings = task / "work" / "test-cases" / "area" / "critic-findings.md"
        findings.write_text(
            "## Fixes without a new round\n\n```json\n[\n"
            '  {"case_id": "TC-200", "locator": "Then", "find": "status matches.", '
            f'"replace": "status is 200.", "reviewed_version": "{record["version"]}"}}\n'
            "]\n```\n", encoding="utf-8")

        result = R.apply_fixes(findings, task)
        check_eq("nothing applied, one skipped as ambiguous",
                 (len(result["applied"]), len(result["skipped"])), (0, 1))
        check_in_reason = "2 matches" in result["skipped"][0]["reason"]
        check("the skip reason names the match count", check_in_reason, str(result["skipped"]))
        links = {l["case_id"]: l for l in C.story_case_links(task)}
        check_eq("the pin never moved", links["TC-200"]["version"], record["version"])
    finally:
        cleanup(root)


def test_cli_apply_fixes_prints_json_and_exits_clean() -> None:
    root = temp_project("qa-factory-critic-apply-")
    try:
        use_project(root)
        task = root / "qa-factory" / "artifacts" / "QA-3"
        store = task / "work" / "test-cases"
        source = task / "work" / "test-cases" / "area" / "TC-300.md"
        write_case(source, "TC-300", "Then it is red.\n")
        record = pin(task, store, source)
        findings = task / "work" / "test-cases" / "area" / "critic-findings.md"
        findings.write_text(
            "## Fixes without a new round\n\n```json\n[\n"
            '  {"case_id": "TC-300", "locator": "Then", "find": "it is red.", '
            f'"replace": "it is blue.", "reviewed_version": "{record["version"]}"}}\n'
            "]\n```\n", encoding="utf-8")

        from harness import run_script
        proc = run_script("critic_rollcall.py", "--apply-fixes", "--task-root", task)
        check_eq("CLI exits 0 on a clean apply", proc.returncode, 0)
        payload = json.loads(proc.stdout)
        check_eq("CLI reports one applied fix", len(payload["applied"]), 1)
    finally:
        cleanup(root)


def test_live_findings_sample_is_machine_applicable() -> None:
    """A COPY of the real TP1-15045 critic-findings.md/TC-012.md/TC-014.md: the shape the
    live critic actually wrote, not a hand-built fixture. The sample lives outside the package,
    read-only; QA_FACTORY_LIVE_SAMPLE names its folder. Skips (never fails) when that is unset or
    unusable, saying why."""
    sample, reason = live_sample(os.environ.get(LIVE_SAMPLE_ENV))
    if sample is None:
        skip(reason)
        return
    root = temp_project("qa-factory-critic-apply-live-")
    try:
        use_project(root)
        task = root / "qa-factory" / "artifacts" / "TP1-15045"
        shutil.copytree(sample, task)
        findings = task / "work" / "test-cases" / "workflows" / "critic-findings.md"
        check("the live sample carries a Fixes block", findings.is_file())
        if not findings.is_file():
            return
        before = R.parse_fixes(findings.read_text(encoding="utf-8"))
        check_eq("the live round supplies 4 exact replacements", len(before), 4)

        result = R.apply_fixes(findings, task)
        check_eq("every live replacement is unambiguous and applies",
                 (len(result["applied"]), len(result["skipped"])), (4, 0))
        check_eq("no debt remains for TC-012/TC-014 once applied",
                 R.findings_errors(findings, task_root=task), [])
    finally:
        cleanup(root)


def test_live_sample_variable_is_read_strictly() -> None:
    """The live sample's door: unset/empty, relative, a file, a missing path and a folder each get
    their own answer, and a reason never carries the value."""
    folder = temp_project("qa-factory-critic-apply-door-")
    try:
        a_file = folder / "not-a-folder.txt"
        a_file.write_text("x", encoding="utf-8")
        for label, value, word in (("unset", None, "is not set"), ("empty", "", "is not set"),
                                   ("relative", "artifacts/TP1-15045", "absolute path expected"),
                                   ("a file", str(a_file), "is not a folder"),
                                   ("missing", str(folder / "absent"), "does not exist")):
            got, reason = live_sample(value)
            check(f"door {label}: no folder, the reason says {word!r} and names the variable",
                  got is None and word in reason and reason.startswith(LIVE_SAMPLE_ENV), reason)
            check(f"door {label}: the reason does not echo the value", not value or value not in reason)
        got, reason = live_sample(str(folder))
        check_eq("door folder: the folder comes back with no reason", (got, reason), (folder, ""))
    finally:
        cleanup(folder)


def test_skip_prints_a_skip_line_in_a_child_process_that_inherited_the_pytest_variable() -> None:
    """F-9: a child process of a pytest test inherits PYTEST_CURRENT_TEST but has no pytest loaded: skip() must print
    its `SKIP:` line and exit 0, not call pytest.skip (an uncaught Skipped = a false FAIL)."""
    here = str(Path(__file__).resolve().parent)
    child_env = dict(os.environ, PYTEST_CURRENT_TEST="tests/x.py::test_x (call)")
    proc = subprocess.run(
        [sys.executable, "-B", "-c", "import sys; sys.path.insert(0, sys.argv[1]); "
         "import test_critic_rollcall_apply_fixes as t; t.skip('why')", here],
        capture_output=True, text=True, encoding="utf-8", errors="replace", env=child_env, timeout=120)
    check_eq("the child exits 0 with the variable inherited", proc.returncode, 0)
    check("the child prints the SKIP line", "SKIP: why" in proc.stdout, proc.stdout + proc.stderr)


if __name__ == "__main__":
    test_synthetic_fix_lands_and_reports_json()
    test_ambiguous_find_stays_a_reported_debt()
    test_cli_apply_fixes_prints_json_and_exits_clean()
    test_live_findings_sample_is_machine_applicable()
    test_live_sample_variable_is_read_strictly()
    test_skip_prints_a_skip_line_in_a_child_process_that_inherited_the_pytest_variable()
    finish("critic_rollcall_apply_fixes")
