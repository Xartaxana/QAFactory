"""red_sandbox.py — pinned node ids are checked inside the prepared sandbox, and the expected
reason tolerates pytest's `AssertionError: ` prefix.

Two incidents of TP1-15045. Job 071bcb794f4e10520240: a probe pinned
`[buffer-R3-vs-selected-R1]`, pytest collects `[chromium-buffer-R3-vs-selected-R1]`, exit 4,
the sandbox was burned. S5-qa-code-critic-5: the pinned reason lacked `AssertionError: `, the
probe failed exactly as intended and was refused, and a second sandbox was prepared for it.
pytest-playwright is never needed: the temp repository's conftest prepends the browser itself,
and where pytest is not importable a stub `pytest.py` answers the collect.
"""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness import (check, check_eq, check_in, cleanup, finish, run_script,  # noqa: E402
                     temp_dir)

import red_sandbox as RS  # noqa: E402

HAVE_PYTEST = importlib.util.find_spec("pytest") is not None
PYTEST = [sys.executable, "-B", "-m", "pytest", "-p", "no:cacheprovider"]
TEST = "tests/test_diff.py"
ASKED = f"{TEST}::test_markers_follow_the_selected_pair[buffer-R3-vs-selected-R1]"
REAL = f"{TEST}::test_markers_follow_the_selected_pair[chromium-buffer-R3-vs-selected-R1]"

CONFTEST = '''\
def pytest_generate_tests(metafunc):
    # pytest-playwright's habit under a neutral fixture name: the browser leads the id.
    if "engine_name" in metafunc.fixturenames:
        metafunc.parametrize("engine_name", ["chromium"])
'''
TEST_FILE = '''\
import pytest

from helper import visible


@pytest.mark.parametrize("pair", ["buffer-R3-vs-selected-R1", "saved-R2-vs-R1"])
def test_markers_follow_the_selected_pair(engine_name, pair):
    assert visible(pair), "Locator expected to be visible"
'''
STUB = f'''\
import sys
print("{REAL}")
print("{TEST}::test_markers_follow_the_selected_pair[chromium-saved-R2-vs-R1]")
print()
print("2 tests collected in 0.01s")
sys.exit(0)
'''


def repository() -> Path:
    repo = temp_dir("qa-probe-ids-repo-")
    subprocess.run(["git", "init", "-q"], cwd=str(repo), capture_output=True, timeout=60)
    (repo / "tests").mkdir()
    (repo / "conftest.py").write_text(CONFTEST, encoding="utf-8")
    (repo / "helper.py").write_text("def visible(pair):\n    return True\n", encoding="utf-8")
    (repo / TEST).write_text(TEST_FILE, encoding="utf-8")
    if not HAVE_PYTEST:
        (repo / "pytest.py").write_text(STUB, encoding="utf-8")
    return repo


def request(repo: Path, node_id=None, collect=True, **extra) -> dict:
    target = {"path": "helper.py", "before_sha256": RS.digest(repo / "helper.py"),
              "replacement_utf8": "def visible(pair):\n    return False\n",
              "instance_id": "TC-007", "expected_location": f"{TEST}:8",
              "expected_reason": "Locator expected to be visible", **extra}
    if node_id:
        target["node_id"] = node_id
    out = {"mutations": [target]}
    if collect:
        out["collect"] = {"argv": PYTEST, "cwd": ".", "timeout_s": 120}
    return out


def reasons() -> None:
    pinned = "Expected the modified node's border to be the aborted-primary amber, got rgb(0, 0, 0)"
    check("pytest's AssertionError prefix on the actual reason is tolerated",
          RS.reason_matches("AssertionError: " + pinned, pinned))
    check("and on the expected one", RS.reason_matches(pinned, "AssertionError: " + pinned))
    check("and on both",
          RS.reason_matches("AssertionError: " + pinned, "AssertionError: " + pinned))
    check("whitespace runs are folded", RS.reason_matches("AssertionError:  a\n  b", "a b"))
    check("a different assertion is still a different assertion",
          not RS.reason_matches("AssertionError: Locator expected to have count '1'", pinned))
    check("another exception type is not an assertion",
          not RS.reason_matches("TimeoutError: " + pinned, pinned))
    check("an empty expectation matches nothing", not RS.reason_matches("", ""))
    # One rule with window_record (`reporters.assertion_reason`): the headline of a .NET assertion
    # is the pin; the Expected/Actual lines under it are the reporter's.
    check("a .NET headline pinned alone matches the reporter's headline plus detail",
          RS.reason_matches("Assert.Equal() Failure\nExpected: 4\nActual:   0", "Assert.Equal() Failure"))
    check("another headline is another assertion",
          not RS.reason_matches("Assert.Equal() Failure\nExpected: 4", "Assert.IsType() Failure"))
    check("whole-text equality still decides first (a receipt written before the shared rule)",
          RS.reason_matches("AssertionError:  line one\n line two", "line one line two"))
    check("an empty actual matches nothing", not RS.reason_matches("", "Assert.Equal() Failure"))


def preparing() -> None:
    repo = repository()
    destination = Path(str(repo) + "-sandbox")
    task = temp_dir("qa-probe-ids-task-")
    try:
        receipt = RS.prepare(repo, destination, request(repo, ASKED))
        check_eq("the pinned id is re-pinned in its real spelling",
                 receipt["targets"][0]["node_id"], REAL)
        check_eq("the check is recorded as verified", receipt["node_id_check"]["status"],
                 "verified")
        check_in("with the note that says what the factory did", "chromium-buffer-R3",
                 receipt["node_id_check"]["notes"])
        stored = json.loads((destination / ".qa-probe.json").read_text(encoding="utf-8"))
        check_eq("and the stored receipt carries the real spelling too",
                 (stored["status"], stored["targets"][0]["node_id"]), ("prepared", REAL))
        check("the collect left no bytecode inside the sandbox",
              not list(destination.rglob("__pycache__")))

        row = {"instance_id": "TC-007", "status": "failed", "failure_kind": "assertion",
               "location": f"{TEST}:8", "semantic_verdict": "intended_failure",
               "reason": "AssertionError: Locator expected to be visible"}
        check_eq("the probe is accepted although the pinned reason had no AssertionError prefix",
                 RS.verify(receipt, [row])["status"], "accepted")
        check_eq("while a different failure is still refused",
                 RS.verify(receipt, [{**row, "reason": "AssertionError: Locator expected to "
                                                       "have count '1'"}])["status"], "incomplete")
        cleanup(destination)

        wrong = f"{TEST}::test_markers_follow_the_selected_pair[buffer-R9]"
        try:
            RS.prepare(repo, destination, request(repo, wrong))
            check("an id pytest does not collect fails the preparation", False)
        except RS.NodeIdMismatch as exc:
            check_in("an id pytest does not collect fails the preparation, nearest ids named",
                     "chromium-buffer-R3-vs-selected-R1", str(exc))
            check_in("the refusal is not the person's to repair", "not the person's", str(exc))
            check_in("and names how a person's word passes it", "--stage S5", str(exc))
            check_eq("the missing rows travel with the exception",
                     [m["asked"] for m in exc.missing], [wrong])
        check("the destination is free again: no sandbox is burned on a wrong id",
              not destination.exists())
        again = RS.prepare(repo, destination, request(repo, REAL))
        check_eq("so the corrected request prepares under the same destination",
                 again["status"], "prepared")
        cleanup(destination)

        (task / "pipeline.json").write_text(json.dumps({"stage_overrides": [
            {"stage": "S5", "match": "not collected by pytest",
             "decision": "run it as pinned, the id is generated at run time"}]}), encoding="utf-8")
        passed = RS.prepare(repo, destination, request(repo, wrong), task)
        check_eq("a person's recorded S5 decision passes the refusal",
                 passed["node_id_check"]["status"], "passed_by_person")
        check_in("in their own words", "generated at run time", passed["node_id_check"]["notes"])
        check_eq("and the id stays as pinned", passed["targets"][0]["node_id"], wrong)
        cleanup(destination)

        legacy = RS.prepare(repo, destination, request(repo, None))
        check_eq("a request that pins no id is prepared exactly as before",
                 (legacy["status"], legacy["node_id_check"]),
                 ("prepared", {"status": "no_pinned_ids"}))
        cleanup(destination)
        unchecked = RS.prepare(repo, destination, request(repo, ASKED, collect=False))
        check_eq("an id without a collect command is not verified and blocks nothing",
                 (unchecked["status"], unchecked["node_id_check"]["status"],
                  unchecked["targets"][0]["node_id"]), ("prepared", "not_checked", ASKED))
        cleanup(destination)

        broken = request(repo, ASKED)
        broken["collect"]["argv"] = [str(repo / "no-such-venv" / "pytest")]
        errored = RS.prepare(repo, destination, broken)
        check_eq("a collect that cannot answer fails nothing",
                 (errored["status"], errored["node_id_check"]["status"]),
                 ("prepared", "collect_error"))
        check("and its head is kept for the role", bool(errored["node_id_check"]["collect_error"]))
        cleanup(destination)

        outside = request(repo, ASKED)
        outside["collect"]["cwd"] = ".."
        try:
            RS.prepare(repo, destination, outside)
            check("a collect cwd outside the sandbox is refused", False)
        except ValueError as exc:
            check_in("a collect cwd outside the sandbox is refused", "inside the sandbox", str(exc))
        check("and leaves no sandbox behind either", not destination.exists())

        spec = task / "mutations.json"
        spec.write_text(json.dumps(request(repo, wrong)), encoding="utf-8")
        cli = run_script("red_sandbox.py", "--repo", repo, "--destination", destination,
                         "--request", spec)
        check_eq("the CLI exits 2 on a wrong id", cli.returncode, 2)
        printed = json.loads(cli.stdout)
        check_eq("with the runner's refusal shape",
                 (printed["status"], [m["asked"] for m in printed["missing"]]),
                 ("node_id_mismatch", [wrong]))
        spec.write_text(json.dumps(request(repo, ASKED)), encoding="utf-8")
        cli = run_script("red_sandbox.py", "--repo", repo, "--destination", destination,
                         "--request", spec)
        check_eq("the CLI prints the real spelling per instance",
                 json.loads(cli.stdout).get("node_ids"), {"TC-007": [REAL]})
    finally:
        cleanup(destination) if destination.exists() else None
        cleanup(task)
        cleanup(repo)


def author_baseline_collect() -> None:
    """3.3b: the author's-baseline lookup collects through `run_suite.collect_files` - the one S5 collect, which
    hands the runner's row to `node_ids` - and keeps no copy of it (AR-15)."""
    import execution_request as ER
    import hooklib
    import run_suite
    repo = temp_dir("qa-rsb-baseline-")
    seen = []
    saved = (ER.load_run_budget, ER.fresh_evidence, run_suite.collect_files)
    try:
        task_root = hooklib.artifact_root(root=repo) / "T-1"
        task_root.mkdir(parents=True)
        ER.load_run_budget = lambda: ({}, "")

        def fresh(root, task, cases, cfg=None, probe=None, collect=None):
            collect(["pytest", "-q"], str(root), ["tests/test_a.py"])     # what the evidence lookup does
            return {"instances": {}}
        ER.fresh_evidence = fresh
        run_suite.collect_files = lambda argv, cwd, files, cfg, notes=None: (
            seen.append((list(argv), str(cwd), list(files))) or ["tests/test_a.py::test_x"])
        got = RS._author_baseline(repo, task_root, [], [], {}, [])
        check_eq("K-3.3b-once the lookup's collect is run_suite.collect_files, once, with the files it was asked about",
                 seen, [(["pytest", "-q"], str(repo), ["tests/test_a.py"])])
        check_eq("K-3.3b-once ... and the lookup still ends as it did (nothing placed, nothing to refuse)",
                 got[0], "covered")
        check("K-3.3b-nocopy red_sandbox keeps no collect of its own: node_ids.collect is not called there",
              "node_ids.collect(" not in (Path(RS.__file__).read_text(encoding="utf-8")))
    finally:
        ER.load_run_budget, ER.fresh_evidence, run_suite.collect_files = saved
        cleanup(repo)


def main() -> None:
    reasons()
    author_baseline_collect()
    preparing()
    finish("test_red_sandbox_node_ids")


if __name__ == "__main__":
    main()
