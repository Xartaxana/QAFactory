"""red_sandbox.py --diagnostic: ONE run of a red test without the asserts of the Thens behind its red one, in a copy.

(t-1508 R4, B1.) The failure analyst of S7 asks whether the Thens that wait behind a red assert would hold. The test is run
once in a disposable copy of the tree with the lines of the dropped Thens removed; the repository is never changed and
nothing is published: no receipt, no `work/probes/`, no manifest row, no run block, no ordinary job a later run could copy
its `cwd` from. The only trace is `evidence/diagnostic-<label>.json`, written by `diagnostic()` alone. Every run goes through
`run_suite.py` as a real subprocess with the stand-in test command of `test_red_sandbox_probe.py`, so the variant's real
behaviour (not a canned answer) decides the status.

Killing test per mutant (each is a different line of `diagnostic()` or `variant_shape`):
  - no "only removal" check            -> `refusals_before_a_copy_exists` (added line, changed line, moved lines, zero removed)
  - no count of the earlier run        -> `a_second_run_over_the_same_bytes` (already_run, zero launches)
  - no `finally` around the copy       -> `the_copy_goes_on_every_path` (the clone existed when `_run_mine` raised, and is gone)
  - `--purpose` other than red_probe   -> `nothing_is_published` (the job is not an ordinary one, the precedent is the same)
  - `thens` written on a red variant   -> `a_red_variant_leaves_the_thens_to_the_analyst`
  - a stand that fell read as `held`   -> `a_run_without_a_row_is_not_executed_and_not_reached`
  - a taken label overwritten          -> `a_taken_label_is_not_overwritten`
"""
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness import check, check_eq, check_in, check_not_in, finish  # noqa: E402

import contract as C  # noqa: E402
import execution_request as ER  # noqa: E402
import red_sandbox as RS  # noqa: E402
import test_red_sandbox_probe as P  # noqa: E402

TEST_RED = '''\
from calc import add


def test_add():
    assert add(2, 2) == 4, "then 1"
    assert add(1, 1) == 3, "then 2"
    assert add(0, 5) == 5, "then 3"
    assert add(3, 3) == 6, "then 4"
'''
TEST_GREEN = TEST_RED.replace("add(1, 1) == 3", "add(1, 1) == 2")
THEN_LINES = {1: 5, 2: 6, 3: 7, 4: 8}      # 1-based line of each Then's assert in TEST_RED
SELF = Path(RS.__file__).resolve()
DISPATCH = "S7-qa-failure-analyst-1"
PYTHON = sys.executable


def dispatches(root: Path, *rows) -> None:
    """Replace the story's open dispatches by `rows` = (id, stage, role, scope)."""
    path = P.task_of(root) / "state" / "controller.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["dispatches"] = {i: {"id": i, "stage": stage, "role": role, "status": "running", "scope": list(scope),
                             "budget": {"requests": 50}} for i, stage, role, scope in rows}
    P.write_json(path, doc)


def world(tests: str, *, green: bool = False, iid: str = "test_add", case: str = "TC-100") -> Path:
    """A git project whose one test (`test_add` of TC-100, four Thens) has a recorded author's run, red or green, and an
    open S7 dispatch of the failure analyst."""
    root = P.project(P.fake(), tests=tests, scope=(case,))
    manifest = P.manifest_of(root)
    manifest["tests"] = [P.row_of(root, iid, case)]
    manifest["then_bindings"] = [{"case": case, "then": n, "instance_id": iid, "assertion_ref": None,
                                  "status": "covered"} for n in (1, 2, 3, 4)]
    P.write_json(P.task_of(root) / "work" / "automation-manifest.json", manifest)
    dispatches(root, ("S5-qa-automator-1", "S5", "qa-automator", [case]))
    if green:
        P.seed_green(root, case)
    else:
        proc = subprocess.run([PYTHON, "-B", str(P.RUN_SUITE), "--mine", case], cwd=str(root), capture_output=True,
                              text=True, encoding="utf-8", errors="replace", timeout=300,
                              env=dict(os.environ, CLAUDE_PROJECT_DIR=str(root), QA_FACTORY_SKIP_DASHBOARD_REFRESH="1",
                                       PYTHONDONTWRITEBYTECODE="1"))
        check("seed: the author's run is RED (Then 2 asserts a wrong value)", proc.returncode != 0, proc.stdout + proc.stderr)
        P.PL._reset()
    dispatches(root, (DISPATCH, "S7", "qa-failure-analyst", [case]))
    return root


def variant_of(root: Path, drop) -> str:
    lines = (root / "tests" / "test_calc.py").read_text(encoding="utf-8").splitlines()
    return "\n".join(line for number, line in enumerate(lines, 1) if number not in set(drop)) + "\n"


def request(root: Path, *, label="d1", drop=(THEN_LINES[2],), dropped=(2,), text=None, name="diag.json", **over) -> Path:
    doc = {"label": label, "instance_id": "test_add", "cases": ["TC-100"], "thens_dropped": list(dropped),
           "mutation": {"path": "tests/test_calc.py", "before_sha256": RS.digest(root / "tests" / "test_calc.py"),
                        "replacement_utf8": text if text is not None else variant_of(root, drop)}}
    doc.update(over)
    path = root / name
    P.write_json(path, doc)
    return path


def run(root: Path, path: Path, **kwargs) -> dict:
    return RS.diagnostic(root, path, P.task_of(root), timeout=300, **kwargs)


def tree_hash(root: Path) -> dict:
    """The author's tree: every file the project holds outside the factory's own state."""
    return {p.relative_to(root).as_posix(): RS.digest(p) for p in sorted(root.rglob("*"))
            if p.is_file() and ".git" not in p.parts and "qa-factory" not in p.parts and p.name != "diag.json"
            and "__pycache__" not in p.parts}


def published(root: Path) -> dict:
    """What a probe would publish: `work/probes/`, the manifest, the run blocks - bytes."""
    task = P.task_of(root)
    paths = [task / "work" / "automation-manifest.json"] + [
        p for base in ("probes", "run-blocks") for p in sorted((task / "work" / base).rglob("*")) if p.is_file()]
    return {p.relative_to(task).as_posix(): p.read_bytes() for p in paths if p.is_file()}


def evidence_of(root: Path, result: dict) -> dict:
    return json.loads((P.task_of(root) / result["evidence"]["path"]).read_text(encoding="utf-8"))


class counting_prepare:
    def __enter__(self):
        self.real, self.calls = RS.prepare, []

        def wrapped(repo, destination, req, task_root=None, **kw):
            self.calls.append(str(destination))
            return self.real(repo, destination, req, task_root, **kw)
        RS.prepare = wrapped
        return self

    def __exit__(self, *_exc):
        RS.prepare = self.real


def refused(label: str, root: Path, path: Path, needle: str, **kwargs) -> None:
    got = run(root, path, **kwargs)
    check_eq(f"{label}: refused", got["status"], "refused")
    check_in(f"{label}: and the refusal says {needle!r}", needle, got.get("message", ""))


def refusals_before_a_copy_exists() -> None:
    root = world(TEST_RED)
    try:
        before = (tree_hash(root), len(P.launches(root)))
        with counting_prepare() as counted:
            lines = (root / "tests" / "test_calc.py").read_text(encoding="utf-8").splitlines()
            # K-R4-2 a line ADDED, K-R4-3 a line CHANGED, a swap, K-R4-4 nothing removed
            refused("K-R4-2 an added line", root, request(root, text=variant_of(root, [6]) + "    assert True\n"),
                    "only REMOVES lines")
            changed = "\n".join(lines).replace('"then 2"', '"then 2 (edited)"') + "\n"
            refused("K-R4-3 a changed line", root, request(root, text=changed), "adds or changes lines")
            swapped = lines[:]
            swapped[4], swapped[5] = swapped[5], swapped[4]
            refused("lines moved", root, request(root, text="\n".join(swapped) + "\n"), "moves lines")
            refused("K-R4-4 nothing removed", root, request(root, text="\n".join(lines) + "\n"), "removes no line")
            refused("a line outside the function", root, request(root, text="\n".join(lines[1:]) + "\n"), "outside")
            refused("a removed line of the declaration", root, request(root, text="\n".join(lines[:3] + lines[4:]) + "\n"),
                    "outside")
            refused("before_sha256 is not the file's bytes", root, request(
                root, mutation={"path": "tests/test_calc.py", "before_sha256": "0" * 64,
                                "replacement_utf8": variant_of(root, [6])}), "before_sha256")
            refused("thens_dropped empty", root, request(root, dropped=()), "thens_dropped")
            refused("thens_dropped names a Then the instance does not hold", root, request(root, dropped=(9,)), "does not hold")
            refused("thens_dropped has a duplicate", root, request(root, dropped=(2, 2)), "thens_dropped")
            refused("thens_dropped is a string", root, request(root, dropped=["2"]), "thens_dropped")
            refused("a replacement that is not UTF-8 text", root, request(root, text="\ud800 lone surrogate\n"), "UTF-8")
            refused("a label that is a path", root, request(root, label="../x"), "label")
            refused("a request of another shape", root, request(root, extra=1), "exactly the keys")
            refused("an unknown instance", root, request(root, instance_id="test_nope"), "test_nope")
            refused("a file that is not the instance's own", root, request(root, mutation={
                "path": "calc.py", "before_sha256": RS.digest(root / "calc.py"), "replacement_utf8": "x = 1\n"}),
                "own test file")
            refused("a path outside the project", root, request(root, mutation={
                "path": "../x.py", "before_sha256": "0" * 64, "replacement_utf8": ""}), "mutation.path")
            # K-R4-11 / role / stage
            dispatches(root, (DISPATCH, "S7", "qa-failure-analyst", ["TC-100"]), ("S7-qa-failure-analyst-2", "S7",
                                                                                  "qa-failure-analyst", ["TC-100"]))
            refused("K-R4-11 two open dispatches and none named", root, request(root), "--dispatch")
            dispatches(root, ("S5-qa-code-critic-1", "S5", "qa-code-critic", ["TC-100"]))
            refused("a critic's S5 dispatch", root, request(root), "qa-failure-analyst")
            dispatches(root, ("S7-qa-failure-analyst-1", "S7", "qa-failure-analyst", ["TC-100"]))
            refused("a dispatch name that is not open", root, request(root), "no open dispatch", dispatch="S7-nope")
            dispatches(root)
            refused("no dispatch open", root, request(root), "no dispatch is open")
            # t-114 m7: a RUNNING S7 investigation is never the host of a diagnostic run (kill: drop the `_without_investigation` call)
            path = P.task_of(root) / "state" / "controller.json"
            doc = json.loads(path.read_text(encoding="utf-8"))
            doc["dispatches"] = {"S7-qa-failure-analyst-9": {
                "id": "S7-qa-failure-analyst-9", "stage": "S7", "role": "qa-failure-analyst", "status": "running",
                "scope": [], "budget": {"requests": 50}, "request_binding": {"purpose": "investigation"}}}
            P.write_json(path, doc)
            refused("t-114 m7 a running investigation is not a host", root, request(root), "INVESTIGATION")
            refused("...named by --dispatch too", root, request(root), "INVESTIGATION", dispatch="S7-qa-failure-analyst-9")
        check_eq("none of those created a copy (prepare never called)", counted.calls, [])
        check_eq("...no neighbour of the repository", P.sandboxes(root), [])
        check_eq("...the author's tree is byte-identical and nothing was launched",
                 (tree_hash(root), len(P.launches(root))), before)
        check_eq("...and no diagnostic evidence file exists", sorted((P.task_of(root) / "evidence").glob("diagnostic-*")), [])
    finally:
        P.finish_project(root)


def a_taken_label_is_not_overwritten() -> None:
    root = world(TEST_RED)
    try:
        taken = P.task_of(root) / "evidence" / "diagnostic-x.json"
        taken.parent.mkdir(parents=True, exist_ok=True)
        taken.write_bytes(b'{"instance_id": "another", "keep": "me"}\n')
        before, launched = taken.read_bytes(), len(P.launches(root))
        got = run(root, request(root, label="x"))
        check_eq("K-R4-9 a label whose file exists: refused", got["status"], "refused")
        check_in("...naming the file as 'label taken'", "label taken: evidence/diagnostic-x.json", got["message"])
        check_eq("...the other file is byte-for-byte as it was", taken.read_bytes(), before)
        check_eq("...and nothing was launched", len(P.launches(root)), launched)
    finally:
        P.finish_project(root)


def a_green_test_is_not_diagnosed() -> None:
    root = world(TEST_GREEN, green=True)
    try:
        launched = len(P.launches(root))
        got = run(root, request(root, text=variant_of(root, [6])))
        check_eq("a test whose newest result is green: refused", got["status"], "refused")
        check_in("...saying it is green", "is green", got["message"])
        check_eq("...with no launch and no copy", (len(P.launches(root)) - launched, P.sandboxes(root)), (0, []))
    finally:
        P.finish_project(root)


def a_passing_variant_and_nothing_published() -> None:
    root = world(TEST_RED)
    try:
        task = P.task_of(root)
        tree, rows = tree_hash(root), published(root)
        seeded = len(P.launches(root))
        jobs = list(ER.JobStore(task / "state" / "execution-jobs").jobs())
        precedent = ER.ordinary_precedent(jobs, "unit")
        with counting_prepare() as counted:
            got = run(root, request(root))
        check_eq("K-R4-1 the variant without Then 2 is green: passed", got["status"], "passed")
        check_eq("...one copy was prepared and ONE launch made, in it",
                 (len(counted.calls), len(P.launches(root)) - seeded), (1, 1))
        cwd, nodes = P.launches(root)[-1]
        check("...the launch ran in the copy, selecting the instance's node", "-redprobe-" in cwd and nodes ==
              ["tests/test_calc.py::test_add"], f"{cwd} {nodes}")
        evidence = evidence_of(root, got)
        check_eq("...evidence/diagnostic-d1.json is the account", got["evidence"]["path"], "evidence/diagnostic-d1.json")
        check_eq("...Then 1, 3 and 4 are held (the unambiguous outcome)", evidence["thens"],
                 [{"then": 1, "outcome": "held"}, {"then": 3, "outcome": "held"}, {"then": 4, "outcome": "held"}])
        check_eq("...the removed line is named with its original number and text",
                 evidence["removed_lines"], [{"line": 6, "text": '    assert add(1, 1) == 3, "then 2"'}])
        check_eq("...the hashes: the test bytes before, and the variant's", (evidence["original_sha256"] == RS.digest(
            root / "tests" / "test_calc.py"), len(evidence["variant_sha256"])), (True, 64))
        check_eq("...the dropped Thens, the status and no failure line",
                 (evidence["thens_dropped"], evidence["status"], evidence["failure_line"]), ([2], "passed", None))
        check_eq("...the run summary is kept, reduced", evidence["run_summary"].get("purpose"), "red_probe")
        check_eq("...the dispatch is the analyst's", evidence["dispatch_id"], DISPATCH)
        # K-R4-1: the author's tree is untouched
        check_eq("the author's tree has the same hash before and after", tree_hash(root), tree)
        # K-R4-7: no neighbour
        check_eq("K-R4-7 no *-redprobe-* neighbour is left", P.sandboxes(root), [])
        # K-R4-8: nothing published
        check_eq("K-R4-8 no receipt, no work/probes/, no manifest change, no run block (bytes before == after)",
                 published(root), rows)
        check_eq("...and no probes folder at all", (task / "work" / "probes").exists(), False)
        # K-R4-6 / B1
        after = list(ER.JobStore(task / "state" / "execution-jobs").jobs())
        diag_jobs = [j for j in after if "diagnostic variant" in str(j["request"].get("reason") or "")
                     or j["request"].get("purpose") == "red_probe"]
        check("K-R4-6 the diagnostic run IS recorded as a red_probe job", len(diag_jobs) == 1, str(len(diag_jobs)))
        ordinary = ER.ordinary_jobs(after, "unit")
        check("...it is not among the ordinary jobs of the profile", all(
            j["request"].get("purpose") != "red_probe" for j in ordinary))
        check_eq("...the ordinary precedent is the seed's, unchanged", ER.ordinary_precedent(after, "unit"), precedent)
        check_not_in("...and its command.cwd is not the copy's", "redprobe",
                     json.dumps((ER.ordinary_precedent(after, "unit") or {}).get("command", {}).get("cwd")))
        mine = subprocess.run([PYTHON, "-B", str(P.RUN_SUITE), "--mine", "TC-100", "--dispatch", DISPATCH, "--again"],
                              cwd=str(root), capture_output=True, text=True, encoding="utf-8", errors="replace",
                              timeout=300, env=dict(os.environ, CLAUDE_PROJECT_DIR=str(root),
                                                    QA_FACTORY_SKIP_DASHBOARD_REFRESH="1", PYTHONDONTWRITEBYTECODE="1"))
        newest = list(ER.JobStore(task / "state" / "execution-jobs").jobs())[-1]["request"]
        check("...the next ordinary --mine ran (an ordinary job, newest)", newest.get("purpose") != "red_probe",
              mine.stdout[-300:] + mine.stderr[-300:])
        check_not_in("...and its command.cwd is not built from the removed copy", "redprobe",
                     json.dumps((newest.get("command") or {}).get("cwd")))
        # the account is the evidence file: a second request over these bytes
        a_second_run_over_the_same_bytes(root, got)
    finally:
        P.finish_project(root)


def a_second_run_over_the_same_bytes(root: Path, first: dict) -> None:
    task = P.task_of(root)
    launched = len(P.launches(root))
    with counting_prepare() as counted:
        again = run(root, request(root, label="d2"))
    check_eq("K-R4-5 a second request over the same bytes: already_run", again["status"], "already_run")
    check_eq("...naming the first evidence", again["evidence"], first["evidence"]["path"])
    check_eq("...nothing started: no copy, no launch, no file", (counted.calls, len(P.launches(root)) - launched,
                                                               (task / "evidence" / "diagnostic-d2.json").exists()), ([], 0, False))
    check_in("...and the words name the door of a person's word", "diagnostic again: test_add", again["words"])
    first_at = evidence_of(root, first)["recorded_at"]
    said = datetime.fromisoformat(first_at) + timedelta(seconds=1)
    pipeline = json.loads((task / "pipeline.json").read_text(encoding="utf-8"))
    pipeline["stage_overrides"] = [{"stage": "S7", "match": "diagnostic again: test_add", "decision": "yes, once more",
                                    "at": said.isoformat()}]
    P.write_json(task / "pipeline.json", pipeline)
    time.sleep(2)
    word = run(root, request(root, label="d3"))
    check_eq("K-R4-5b the person's word 'diagnostic again' is recorded: the run happens", word["status"], "passed")
    check_eq("...one more launch", len(P.launches(root)) - launched, 1)
    check_in("...the word is quoted", "yes, once more", " ".join(word["notes"]))
    third = run(root, request(root, label="d4"))
    check_eq("...and the word is spent on that one repeat: the next request is already_run", third["status"], "already_run")
    # F4 (t-1556): the word is read by `contract.stage_override_values`, the id compared for EQUALITY
    later = (datetime.fromisoformat(evidence_of(root, word)["recorded_at"]) + timedelta(hours=1)).isoformat()
    for label, match in (("the word of an id that is a prefix of this one (test_ad)", "diagnostic again: test_ad"),
                         ("the word of an id that extends this one (test_add_back)", "diagnostic again: test_add_back"),
                         ("`*`", "diagnostic again: *")):
        pipeline["stage_overrides"] = [{"stage": "S7", "match": match, "decision": "yes, once more", "at": later}]
        P.write_json(task / "pipeline.json", pipeline)
        wrong = run(root, request(root, label="d4w"))
        check_eq(f"K-R4-5c {label} passes no repeat of test_add", wrong["status"], "already_run")
    pipeline["stage_overrides"] = [{"stage": "S7", "match": "diagnostic again: test_add", "decision": "no", "at": later,
                                    "revoked_at": later}]
    P.write_json(task / "pipeline.json", pipeline)
    check_eq("...a REVOKED word passes none", run(root, request(root, label="d4w"))["status"], "already_run")
    pipeline["stage_overrides"] = [{"stage": "S7", "match": "diagnostic again: test_add", "decision": "once more", "at": later}]
    P.write_json(task / "pipeline.json", pipeline)
    check_eq("...and the word of exactly this id (later than the last run) passes", run(root, request(root, label="d4x"))["status"],
             "passed")
    test_file = root / "tests" / "test_calc.py"
    test_file.write_text(test_file.read_text(encoding="utf-8") + "\n# edited\n", encoding="utf-8")
    fresh = run(root, request(root, label="d5"))
    check_eq("new bytes of the test file are a new key: the run happens without a word", fresh["status"], "passed")


def a_red_variant_leaves_the_thens_to_the_analyst() -> None:
    root = world(TEST_RED)
    try:
        got = run(root, request(root, label="r1", drop=(THEN_LINES[1],), dropped=(1,)))
        check_eq("K-R4-1b the variant without Then 1 still has the red Then 2: failed", got["status"], "failed")
        evidence = evidence_of(root, got)
        check_eq("...no `thens` key in the evidence (the analyst reads the failure line)", "thens" in evidence, False)
        check_in("...the failure line names the assert's message", "then 2", evidence["failure_line"])
        check_in("...and its location, with the variant's line number", "tests/test_calc.py:", evidence["failure_line"])
        check_eq("...the answer carries it too", got["failure_line"], evidence["failure_line"])
        check_eq("...no copy left", P.sandboxes(root), [])
    finally:
        P.finish_project(root)


def the_copy_goes_on_every_path() -> None:
    root = world(TEST_RED)
    real_run, real_bind = RS._run_mine, RS.bind_row
    try:
        seen = {}

        def raising(*args, **kwargs):
            seen["root"] = Path(kwargs["sandbox_root"])
            seen["existed"] = seen["root"].is_dir()
            raise RuntimeError("the runner fell over")
        RS._run_mine = raising
        got = run(root, request(root, label="e1"))
        check_eq("K-R4-7 an exception inside the run: not_executed, with the words", got["status"], "not_executed")
        check_in("...naming what broke", "the runner fell over", " ".join(got["notes"]))
        check_eq("...the copy existed when it fell, and is gone", (seen["existed"], seen["root"].exists()), (True, False))
        check_eq("...no neighbour, no evidence", (P.sandboxes(root), sorted((P.task_of(root) / "evidence").glob("diagnostic-*"))), ([], []))

        def timing_out(*args, **kwargs):
            raise subprocess.TimeoutExpired("run_suite", 1)
        RS._run_mine = timing_out
        got = run(root, request(root, label="e2"))
        check_eq("a run that times out: not_executed, copy gone", (got["status"], P.sandboxes(root)), ("not_executed", []))
        RS._run_mine = real_run

        dispatches(root, (DISPATCH, "S7", "qa-failure-analyst", ["TC-999"]))
        got = run(root, request(root, label="e3"))
        check_eq("a case outside the dispatch's scope: the runner refuses, nothing ran, not_executed", got["status"], "not_executed")
        check_eq("...a run that never started is no evidence and spends no slot",
                 (P.task_of(root) / "evidence" / "diagnostic-e3.json").exists(), False)
        dispatches(root, (DISPATCH, "S7", "qa-failure-analyst", ["TC-100"]))

        RS.bind_row = lambda *a, **k: (None, "no report row for the test")
        got = run(root, request(root, label="e4"))
        check_eq("a run that started but no row answers for the test: not_executed", got["status"], "not_executed")
        evidence = evidence_of(root, got)
        check_eq("...the Thens it did not reach are not_reached, never held", evidence["thens"],
                 [{"then": 1, "outcome": "not_reached"}, {"then": 3, "outcome": "not_reached"},
                  {"then": 4, "outcome": "not_reached"}])
        check_eq("...copy gone", P.sandboxes(root), [])
    finally:
        RS._run_mine, RS.bind_row = real_run, real_bind
        P.finish_project(root)


def a_cli_refusal_is_one_json_line() -> None:
    root = world(TEST_RED)
    try:
        path = request(root, dropped=())
        env = dict(os.environ, CLAUDE_PROJECT_DIR=str(root), QA_FACTORY_SKIP_DASHBOARD_REFRESH="1", PYTHONDONTWRITEBYTECODE="1")
        proc = subprocess.run([PYTHON, "-B", str(SELF), "--diagnostic", "--repo", str(root), "--request", str(path),
                               "--task-root", str(P.task_of(root))], cwd=str(root), capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=120, env=env)
        out = json.loads(proc.stdout.strip().splitlines()[-1])
        check_eq("the command: a refusal is exit 2 and one JSON line", (proc.returncode, out["status"]), (2, "refused"))
        check_not_in("...no traceback", "Traceback", proc.stdout + proc.stderr)
        bare = subprocess.run([PYTHON, "-B", str(SELF), "--diagnostic", "--request", str(path)], cwd=str(root),
                              capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120, env=env)
        check_eq("without --repo and --task-root: a usage error, not a run", bare.returncode != 0, True)
        check_in("...which names what is needed", "--diagnostic requires", bare.stderr)
    finally:
        P.finish_project(root)


def the_registry_and_the_block_reader() -> None:
    registry = json.loads((Path(RS.__file__).resolve().parents[1] / "references" / "artifact-writers.json")
                          .read_text(encoding="utf-8"))["artifacts"]
    row = registry.get("evidence/diagnostic-*.json") or {}
    check_eq("K-R4-10 artifact-writers.json names red_sandbox.py the writer of evidence/diagnostic-*.json",
             row.get("writer"), "red_sandbox.py")
    check_in("...with the reason", "never writes it", row.get("why", ""))
    task = Path(P.temp_dir("qa-diag-task-"))
    try:
        (task / "evidence").mkdir()
        (task / "evidence" / "diagnostic-a.json").write_text("{}", encoding="utf-8")
        (task / "work").mkdir()
        (task / "work" / "diagnostic-b.json").write_text("{}", encoding="utf-8")
        good = {"verdict": "APP_BUG", "diagnostic": {"evidence": "evidence/diagnostic-a.json", "observed": "held",
                                                     "thens": [{"then": 3, "outcome": "held"}]}}
        check_eq("K-R4-12 a well-formed block over a file under evidence/", C.triage_diagnostic_problems(good, task), [])
        check_eq("...a row with no block has none to judge", C.triage_diagnostic_problems({"verdict": "APP_BUG"}, task), [])
        for label, block, needle in (
                ("evidence outside evidence/", {"evidence": "work/diagnostic-b.json", "observed": "x"}, "not under evidence/"),
                ("a file that does not exist", {"evidence": "evidence/diagnostic-zz.json", "observed": "x"}, "is not a file"),
                ("a control experiment's name", {"evidence": "evidence/control-a.json", "observed": "x"}, "diagnostic-<label>.json"),
                ("an absolute path", {"evidence": str(task / "evidence" / "diagnostic-a.json"), "observed": "x"}, "absolute"),
                ("an escaping path", {"evidence": "evidence/../diagnostic-a.json", "observed": "x"}, "diagnostic"),
                ("no evidence", {"observed": "x"}, "`diagnostic.evidence` is empty"),
                ("no observed", {"evidence": "evidence/diagnostic-a.json"}, "`diagnostic.observed` is empty"),
                ("a bad outcome", {"evidence": "evidence/diagnostic-a.json", "observed": "x",
                                   "thens": [{"then": 3, "outcome": "green"}]}, "outcome"),
                ("a Then number of 0", {"evidence": "evidence/diagnostic-a.json", "observed": "x",
                                        "thens": [{"then": 0, "outcome": "held"}]}, "thens[0]"),
                ("thens not a list", {"evidence": "evidence/diagnostic-a.json", "observed": "x", "thens": "3"}, "list"),
                ("a block that is not an object", "yes", "must be an object")):
            got = C.triage_diagnostic_problems({"diagnostic": block}, task)
            check(f"K-R4-12 {label}: a problem naming {needle!r}", any(needle in p for p in got), str(got))
        check_eq("...with no task root the file's existence is not judged, the name still is",
                 C.triage_diagnostic_problems({"diagnostic": {"evidence": "evidence/diagnostic-zz.json", "observed": "x"}}), [])
        check("...and a null block is none", C.triage_diagnostic_problems({"diagnostic": None}, task) == [])
    finally:
        P.cleanup(task)


FIXTURE = Path(__file__).resolve().parent / "fixtures" / "run-12586-red-then"
FIXTURE_IID = "test_put_project_change_into_project_with_ms_teams_is_rejected"


def the_fixture_function_through_the_seam() -> None:
    """K-R4-S and K-R4-6 on the REAL function of TC-003 (fixture run-12586-red-then/test-code/, verbatim) over a stub of the
    product that answers `400 Project mismatch` (test-code/product_stub.py), and on the real jobs of the run (controller/)."""
    text = (FIXTURE / "test-code" / "product_stub.py").read_text(encoding="utf-8") \
        + (FIXTURE / "test-code" / "put_project_change_into_occupied_project.py").read_text(encoding="utf-8")
    lines = text.splitlines()
    at = next(i for i, line in enumerate(lines) if '"Then 2:' in line)
    check_eq("the Then 2 assert is the five lines around its message",
             (lines[at - 3].strip(), lines[at + 1].strip()), ("assert_that(", ")"))
    drop = list(range(at - 2, at + 3))                       # 1-based numbers of those five lines
    root = world(text, iid=FIXTURE_IID, case="TC-003")
    try:
        task = P.task_of(root)
        seeded = len(P.launches(root))
        tree, rows = tree_hash(root), published(root)
        jobs_before = list(ER.JobStore(task / "state" / "execution-jobs").jobs())
        red = [j for j in jobs_before if j["request"].get("selected_instance_ids") == [FIXTURE_IID]]
        check("K-R4-S the seed: the function is RED on the stub's `400 Project mismatch` (Then 2)", bool(red) and
              red[-1].get("execution_status") != "passed", str([j.get("execution_status") for j in jobs_before]))
        got = run(root, request(root, label="s1", instance_id=FIXTURE_IID, cases=["TC-003"], dropped=(2,),
                                text=variant_of(root, drop)))
        check_eq("K-R4-S the function without its Then 2 assert is green: passed", got["status"], "passed")
        evidence = evidence_of(root, got)
        check_eq("...Then 1, 3 and 4 are held", evidence["thens"],
                 [{"then": 1, "outcome": "held"}, {"then": 3, "outcome": "held"}, {"then": 4, "outcome": "held"}])
        check_eq("...the five lines of the assert are the removed ones (the diff may pair the closing bracket with another)",
                 sorted(x["text"] for x in evidence["removed_lines"]), sorted(lines[at - 3:at + 2]))
        check_eq("...one launch, in the copy", len(P.launches(root)) - seeded, 1)
        check_eq("...the author's tree and what a probe publishes are as they were, and no copy is left",
                 (tree_hash(root), published(root), P.sandboxes(root)), (tree, rows, []))
        # K-R4-6 on the run's real jobs: a diagnostic (red_probe) job among them does not move the ordinary precedent
        diag = [j for j in ER.JobStore(task / "state" / "execution-jobs").jobs() if j["request"].get("purpose") == "red_probe"]
        check_eq("K-R4-6 the diagnostic run left one red_probe job", len(diag), 1)
        copy = Path(P.temp_dir("qa-diag-jobs-")) / "execution-jobs"
        shutil.copytree(FIXTURE / "controller" / "TP1-12586" / "state" / "execution-jobs", copy)
        try:
            for path in copy.glob("*.json"):         # file order is the jobs' order: stamp each with its own time
                stamp = datetime.fromisoformat(json.loads(path.read_text(encoding="utf-8"))["created_at"]).timestamp()
                os.utime(path, (stamp, stamp))
            store = ER.JobStore(copy)
            before = ER.ordinary_jobs(store.jobs(), "api")
            check_eq("...the run's jobs: three ordinary ones of `api`, the newest a repair_verify",
                     (len(before), before[0]["request"]["purpose"]), (3, "repair_verify"))
            clone = json.loads(json.dumps(diag[0]))
            clone["request"]["profile_id"] = "api"
            store.write(clone)
            now = time.time() + 60
            os.utime(store._path(clone["idempotency_key"]), (now, now))
            after = store.jobs()
            check_eq("...control: the diagnostic job IS the newest job of the profile", after[-1]["job_id"], clone["job_id"])
            check_eq("...and the newest ORDINARY job is still the same one", ER.ordinary_jobs(after, "api")[0]["job_id"],
                     before[0]["job_id"])
            check_eq("...so is the precedent", ER.ordinary_precedent(after, "api"), ER.ordinary_precedent(store.jobs()[:-1], "api"))
        finally:
            P.cleanup(copy.parent)
    finally:
        P.finish_project(root)
    # control: the stub's answer is read by the real function - dropping Then 1 (not Then 2) leaves the function red at Then 2
    other = world(text, iid=FIXTURE_IID, case="TC-003")
    try:
        first = next(i for i, line in enumerate(lines) if '"Then 1 ' in line)
        still = run(other, request(other, label="s2", instance_id=FIXTURE_IID, cases=["TC-003"], dropped=(1,),
                                   text=variant_of(other, range(first - 2, first + 3))))
        check_eq("...control: a variant that keeps the Then 2 assert stays red", still["status"], "failed")
        check_in("...at Then 2", "Then 2", still.get("failure_line") or "")
    finally:
        P.finish_project(other)


def main() -> None:
    the_fixture_function_through_the_seam()
    the_registry_and_the_block_reader()
    refusals_before_a_copy_exists()
    a_taken_label_is_not_overwritten()
    a_green_test_is_not_diagnosed()
    a_passing_variant_and_nothing_published()
    a_red_variant_leaves_the_thens_to_the_analyst()
    the_copy_goes_on_every_path()
    a_cli_refusal_is_one_json_line()
    finish("test_red_sandbox_diagnostic")


if __name__ == "__main__":
    main()
