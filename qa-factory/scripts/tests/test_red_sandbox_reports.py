"""red_sandbox.py --probe: what the legacy-2406 migration added to upstream's cases.

`test_red_sandbox_probe.py` keeps upstream's own cases (the ask-first, one-launch-per-case flow of
0.8.1). This file holds the checks the branch added on top of it, split out because one file of both
outgrew its ceiling (B-155 class: a file that outgrows its ceiling is split, the ceiling is not raised):

  * a runner that is not pytest - TRX and non-pytest JUnit probes in a profile subdirectory of the
    clone, rows bound by the job request's `report_test_id`, an unread failure site (`incomplete`);
  * the F1 matrix: a pytest command under a `junit-xml` / `pytest` profile, with and without
    `report_test_id` on the manifest row;
  * the binding and the proof at unit level (`bind_row`, `target_result`, `verify`);
  * the request status of several targets (`request_status`), a survivor never masked by another
    target's tooling state, an `incomplete` record that blocks no repeat;
  * `--node-id` only for a pytest node, a case of any other node launched whole, never `--cwd`;
  * B-314 at the head of `probe()`, and the volatile set including `records/` (M20, L7).

The fixtures are upstream's: this file IMPORTS them from `test_red_sandbox_probe.py` (importing it runs
none of its cases: its `main()` is guarded), and adds only what the branch needs - a stand-in test
command that takes both `--junitxml` spellings, and a `project()` that can declare another reporter.
Both files run alone, in either order; every project they make is a temp directory of its own.
"""
import inspect
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness import (check, check_eq, check_in, check_not_in, cleanup, finish, run_script,  # noqa: E402
                     temp_dir, use_project)

import execution_request as ER  # noqa: E402
import proof_level as PL  # noqa: E402
import red_sandbox as RS  # noqa: E402
import window_record  # noqa: E402
from test_red_sandbox_probe import (ASSERT_LINE, CALC2_BROKEN, CALC2_OK, CALC_BROKEN, CALC_OK,  # noqa: E402
                                    DISPATCH, MULTI, MULTI_LINES, PROVENANCE, PY, TASK,
                                    counting_prepare, entry_of, finish_project, git,
                                    launches, manifest_of, mutation_request, probe, row_of,
                                    sandboxes, seed_green, task_of, write_json)
from test_red_sandbox_probe import FAKE_PYTEST as UPSTREAM_FAKE_PYTEST  # noqa: E402
from test_red_sandbox_probe import project as upstream_project  # noqa: E402

# Upstream's stand-in test command takes `--junitxml PATH` (a profile that writes its own flag); a profile
# that declares the `pytest` reporter is equipped by run_suite.py itself with `--junitxml=PATH`. Both
# spellings, so the F1 matrix can run the same stand-in under either profile.
_ONE_SPELLING = 'report = args[args.index("--junitxml") + 1] if "--junitxml" in args else ""\n'
FAKE_PYTEST = UPSTREAM_FAKE_PYTEST.replace(
    _ONE_SPELLING,
    '# Both spellings: `--junitxml PATH` (a profile that writes its own flag) and `--junitxml=PATH`\n'
    '# (what run_suite.py appends for a profile that declares `pytest`).\n'
    'report = next((a.split("=", 1)[1] for a in args if a.startswith("--junitxml=")), "")\n'
    'if not report and "--junitxml" in args:\n'
    '    report = args[args.index("--junitxml") + 1]\n')


def fake() -> Path:
    path = temp_dir("qa-probe-fake-pytest-") / "pytest"
    path.write_text(FAKE_PYTEST, encoding="utf-8")
    return path


def project(fake_pytest: Path, kind: str = "junit-xml", *, report_test_id: bool = False, **kwargs) -> Path:
    """Upstream's git project, with the profile's declared reporter `kind`. Every row is bound by the
    `report_test_id` of the JOB REQUEST (the request builder writes it for a pytest node; for a runner that
    is not pytest it comes from the manifest row). `manifest.tests[].report_test_id` is written only when
    `report_test_id` is asked for: `manifest_from_tests.py` never writes it, so the default is the fixture
    as it was before the field was added to it (the F1 invariant)."""
    root = upstream_project(fake_pytest, **kwargs)
    config_path = root / "qa-factory" / "config.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    profile = config["profiles"][0]
    profile["reporter"] = {"kind": kind}
    if kind == "pytest":  # a pytest profile is equipped by run_suite.py itself (it appends `--junitxml=<path>`)
        profile["commands"]["one_test"]["argv"] = [PY, str(fake_pytest)]
    write_json(config_path, config)
    if report_test_id:
        manifest_path = task_of(root) / "work" / "automation-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for row in manifest["tests"]:  # what the stand-in's junit reports: `<file as a dotted module>::<function>`
            row["report_test_id"] = "tests.test_calc::" + row["instance_id"]
        write_json(manifest_path, manifest)
    return root


def accepted_matrix(kind: str = "junit-xml", *, report_test_id: bool = False) -> None:
    """F1: a pytest command under a `junit-xml` profile is bound and proven exactly as under the
    `pytest` reporter, with or without `report_test_id` on the manifest row."""
    root = project(fake(), kind, report_test_id=report_test_id)
    task_root = task_of(root)
    kind = f"{kind} profile, manifest row {'with' if report_test_id else 'without'} report_test_id"
    try:
        seed_green(root, "TC-100")
        seeded = len(launches(root))
        request = mutation_request(root)
        result = probe(root, request)
        check_eq(f"a mutation that breaks the product is accepted ({kind})", result["status"], "accepted")
        check_eq("no sandbox is left behind", sandboxes(root), [])
        instance = result["instances"].get("test_add", {})
        check_eq("the instance is valid", instance.get("valid"), True)
        mutated = instance.get("mutated") or {}
        check_eq("the mutated run's own location matches the pinned one",
                 mutated.get("location"), f"tests/test_calc.py:{ASSERT_LINE}")
        check_eq("and its failure kind is assertion, read from pytest's own traceback line",
                 mutated.get("failure_kind"), "assertion")
        check_eq("the reason is the real message, not a re-typed copy",
                 mutated.get("reason"), "AssertionError: sum must be 4")
        # AC3: the author's green IS the baseline - exactly one launch, of the target's node, in the mutated sandbox
        after = launches(root)
        check_eq("ONE launch for the whole probe: the mutated run, no baseline run", len(after) - seeded, 1)
        cwd, nodes = after[-1]
        check("...in the mutated sandbox, never a baseline one", "-redprobe-" in cwd and "baseline" not in cwd, cwd)
        check_eq("...selecting only the target's node", nodes, ["tests/test_calc.py::test_add"])
        baseline = instance.get("baseline") or {}
        check_eq("the baseline is the author's green, by its job", (baseline.get("status"), baseline.get("source")),
                 ("passed", "author"))
        check_in("...and the note names that job and that no baseline ran",
                 f"baseline: the author's green {baseline.get('job_id')} on the same bytes (no baseline run)",
                 " ".join(result["notes"]))
        check_eq("one sensitivity receipt was published", len(result["receipts"]), 1)
        receipt_path = task_root / result["receipts"][0]["path"]
        check("the receipt is on disk", receipt_path.is_file())
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        check_eq("it is bound to this instance", receipt.get("instance_id"), "test_add")
        check_eq("and to the test's raw bytes, never the run's fingerprint (binding_facts)",
                 receipt.get("test_content_hash"), RS.digest(root / "tests" / "test_calc.py"))
        # D-0010: a deliberate break of the product is the HIGHER level, and the receipt says so.
        check_eq("it names its level: it caught a broken product",
                 (receipt.get("proof_level"), receipt.get("probe_tool")), ("catches_broken_product", "red_sandbox.py"))
        check_eq("and the one reader agrees", PL.level_of(receipt), "catches_broken_product")
        now = PL.instance_identity(entry_of(root), task_root, root)
        check_eq("t-043 C: it carries the code sha and the per-test identity of the bytes it read (D2)",
                 (receipt.get("test_code_sha"), receipt.get("instance_identity")),
                 (now["test_code_sha"], now["instance_identity"]))
        # t-2064 fix round G, B3 (EP-W): the python test's receipt is `one_check`; nothing is published to the manifest (the critic
        # names it with a `product` entry), so neither a binding nor a row ref appears and no level is reached for the test.
        check_eq("the receipt proves the one check it names", receipt.get("scope"), "one_check")
        manifest = manifest_of(root)
        check_eq("the manifest carries no obligation binding for a one-check receipt", manifest.get("obligation_bindings"), None)
        row = next(t for t in manifest["tests"] if t.get("instance_id") == "test_add")
        check_eq("the instance row names no receipt", row.get("sensitivity_proof"), None)
        check_eq("and the author's row keeps its file", row.get("file"), "tests/test_calc.py")
        check_eq("and its case links", row.get("covers"), ["TC-100"])
        check_eq("one instance row, not two", len([t for t in manifest["tests"]
                                                   if t.get("instance_id") == "test_add"]), 1)
        check_eq("so reached() reads no level for the test as a whole", PL.reached(row, manifest, task_root)["level"], None)
        # D11: the verdict of a launched run is on record, with what it mutated
        record = json.loads(PL.probe_record_path(task_root, "test_add", "product").read_text(encoding="utf-8"))
        check_eq("the product record says intended_failure, with the identity measured BEFORE the sandbox",
                 (record["verdict"], record["probe_tool"], record["test_file_sha256"], record["test_code_sha"],
                  record["instance_identity"], record["dispatch_id"]),
                 ("intended_failure", "red_sandbox.py", now["input_hash"], now["test_code_sha"],
                  now["instance_identity"], DISPATCH))
        check_eq("...and the product file the mutation touched, with the bytes it held (before_sha256) and their code",
                 record["mutated_files"], [{"path": "calc.py", "sha256": RS.digest(root / "calc.py"),
                                            "code_sha": PL.code_sha((root / "calc.py").read_bytes(), "calc.py")}])
        # fix round H: the repeat is answered by the one-check receipt (see test_red_sandbox_probe.accepted).
        again = probe(root, mutation_request(root))
        check_eq("a second probe of the same bytes: already_probed", again["status"], "already_probed")
        check_eq("...and publishes nothing either", manifest_of(root), manifest)
    finally:
        finish_project(root)


# --- a runner that is not pytest: TRX, a profile directory under the clone, exact row binding ---
#
# A stand-in for `dotnet test`. It reads the product (`Calc.txt`) and the test file from ITS OWN
# working directory, so a run that started in the wrong directory finds nothing and a mutation's
# real effect - not a canned answer - decides red or green. Its failure carries a real xUnit stack
# frame, an absolute path inside whatever tree it ran in.
FAKE_XUNIT = r'''
import sys
from pathlib import Path

args = sys.argv[1:]
report = next((a.split("=", 1)[1] for a in args if a.startswith("trx;LogFileName=")), "")
chosen = args[args.index("--filter") + 1] if "--filter" in args else ""
names = [part.split("=", 1)[1] for part in chosen.split("|") if "=" in part]
here = Path.cwd()
product = (here / "Calc.txt").read_text(encoding="utf-8").strip()
test_file = here / "Tests" / "XTests.cs"
lines = test_file.read_text(encoding="utf-8").splitlines()
line = next(n for n, text in enumerate(lines, 1) if "Assert.Equal" in text)
results, definitions, failed = [], [], 0
for index, name in enumerate(names):
    uid = f"id-{index}"
    owner, _, method = name.rpartition(".")
    definitions.append(f'<UnitTest id="{uid}"><TestMethod className="{owner}" name="{method}"/></UnitTest>')
    if product == "broken":
        failed += 1
        results.append(
            f'<UnitTestResult testId="{uid}" testName="{name}" outcome="Failed"><Output><ErrorInfo>'
            f'<Message>Assert.Equal() Failure\nExpected: 4\nActual:   0</Message>'
            f'<StackTrace>   at {name}() in {test_file}:line {line}</StackTrace></ErrorInfo></Output>'
            f'</UnitTestResult>')
    else:
        results.append(f'<UnitTestResult testId="{uid}" testName="{name}" outcome="Passed"/>')
# A real TRX carries the run's own counters: without them the runner reads zero tests and calls the
# run `not_executed`, so the author's green (the probe's baseline) would never stand.
counters = (f'<ResultSummary><Counters total="{len(names)}" executed="{len(names)}" '
            f'passed="{len(names) - failed}" failed="{failed}" error="0" notExecuted="0"/></ResultSummary>')
xml = ('<TestRun xmlns="http://microsoft.com/schemas/VisualStudio/TeamTest/2010"><Results>'
       + "".join(results) + "</Results><TestDefinitions>" + "".join(definitions)
       + "</TestDefinitions>" + counters + "</TestRun>")
if report:
    Path(report).parent.mkdir(parents=True, exist_ok=True)
    Path(report).write_text(xml, encoding="utf-8")
sys.exit(1 if failed else 0)
'''

# The same stand-in for a runner that writes JUnit XML but is not pytest (Jest, Java JUnit, the .NET
# JUnit logger): the failure body is a Jest-shaped frame, which the pytest last-traceback rule reads
# as a garbage location (F2). `--report PATH` is where it writes.
FAKE_JUNIT_RUNNER = r'''
import sys
from pathlib import Path

args = sys.argv[1:]
report = args[args.index("--report") + 1]
chosen = args[args.index("--filter") + 1] if "--filter" in args else ""
name = chosen.split("=", 1)[1] if "=" in chosen else chosen
here = Path.cwd()
product = (here / "Calc.txt").read_text(encoding="utf-8").strip()
test_file = here / "Tests" / "XTests.cs"
lines = test_file.read_text(encoding="utf-8").splitlines()
line = next(n for n, text in enumerate(lines, 1) if "Assert.Equal" in text)
owner, _, method = name.rpartition(".")
if product == "broken":
    body = ("Error: expect(received).toBe(expected)\n\n    Expected: 4\n    Received: 0\n\n"
            f"      at Object.&lt;anonymous&gt; ({test_file}:{line}:20)")
    case = (f'<testcase classname="{owner}" name="{method}"><failure message="expect(received).toBe(expected)">'
            f"{body}</failure></testcase>")
    failed = 1
else:
    case, failed = f'<testcase classname="{owner}" name="{method}"/>', 0
Path(report).parent.mkdir(parents=True, exist_ok=True)
Path(report).write_text(f'<testsuite tests="1" failures="{failed}">{case}</testsuite>', encoding="utf-8")
sys.exit(1 if failed else 0)
'''

XTESTS = '''\
// XTests.One: Calc must add
public class XTests {
    public void One() {
        var sum = Calc.Add(2, 2);
        Assert.Equal(4, sum);
    }
}
'''
XTESTS_ASSERT_LINE = 5
XTESTS_LOCATION = f"backend/Tests/XTests.cs:{XTESTS_ASSERT_LINE}"


def trx_project(fake_runner: Path, *, report_test_id: bool = True, kind: str = "trx",
                ignore_test_file: bool = False) -> Path:
    """A .NET-shaped project: the profile runs in `backend/` (its own directory, not the root),
    the manifest's file is project-relative, and the row says what the runner calls the test.
    `kind` is the declared reporter: `trx` or `junit-xml` (a runner that is not pytest).
    `ignore_test_file` makes git ignore the test file: it exists in the author's tree and the clone
    `red_sandbox` prepares does not hold it.

    Upstream's fixture shape (0.8.1): a git project with its product COMMITTED, so the author's green
    run (`seed_green`) has a source revision the product file can be compared at, and the process
    works in this project (`use_project`) because the probe asks the story what it already holds."""
    root = temp_dir("qa-probe-trx-project-")
    (root / "backend" / "Tests").mkdir(parents=True)
    (root / "backend" / "Tests" / "XTests.cs").write_text(XTESTS, encoding="utf-8")
    (root / "backend" / "Calc.txt").write_text("ok\n", encoding="utf-8")
    if ignore_test_file:
        (root / ".gitignore").write_text("backend/Tests/XTests.cs\n", encoding="utf-8")
    git(root, "init", "-q")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "author")
    revision = git(root, "rev-parse", "HEAD").stdout.strip()
    provenance = dict(PROVENANCE, profile_id="xunit", expected_source_revision=revision,
                      provenance=dict(PROVENANCE["provenance"], deployed_source_revision=revision))
    tail_argv = (["--logger", "trx;LogFileName={report_path}"] if kind == "trx"
                 else ["--report", "{report_path}"])
    probe_script = root.parent / (root.name + "-probe.py")
    probe_script.write_text("import json\nprint(json.dumps(" + repr(provenance) + "))\n", encoding="utf-8")
    (root / "qa-factory" / "state").mkdir(parents=True)
    write_json(root / "qa-factory" / "config.json", {
        "profiles": [{"profile_id": "xunit", "selected": True, "roots": {"test": "backend"},
                     "commands": {"one_test": {"argv": [PY, str(fake_runner), "test", *tail_argv],
                                               "cwd": "backend"}},
                     "reporter": {"kind": kind}, "selectors": {"verified": True}}],
        "execution": {"runtime_probes": {"xunit": {"argv": [PY, str(probe_script)], "cwd": ".",
                                                    "timeout_s": 20}}}})
    task_root = root / "qa-factory" / "artifacts" / TASK
    write_json(task_root / "pipeline.json", {"stages": {"S5": {"status": "running"}},
                                             "first_test_run_at": "2026-09-22T09:00:00+00:00"})
    write_json(task_root / "state" / "controller.json", {
        "schema_version": "2", "revision": "1", "source_revision": revision,
        "dispatches": {DISPATCH: {"id": DISPATCH, "stage": "S5", "role": "qa-code-critic", "status": "running",
                                  "scope": ["TC-100"], "budget": {"requests": 50}}}})
    row = {"case": "TC-100", "covers": ["TC-100"], "file": "backend/Tests/XTests.cs",
           "selector": "XTests.One", "instance_id": "XTests.One", "report_id_source": "catalog",
           "selector_args": ["--filter", "FullyQualifiedName=XTests.One"],
           "case_version_links": [{"case_id": "TC-100", "version": "cv1"}],
           # the raw sha256 of the file, as manifest_from_tests.py binds it (t-016 Amendment 2)
           "trace_binding": {"test_content_sha": RS.digest(root / "backend" / "Tests" / "XTests.cs")}}
    if report_test_id:
        row["report_test_id"] = "XTests.One" if kind == "trx" else "XTests::One"  # classname::name in JUnit
    write_json(task_root / "work" / "automation-manifest.json", {"tests": [row]})
    write_json(task_root / "work" / "run-blocks" / "block1.json", {
        "results": [{"instance_id": "XTests.One",
                    "source_fingerprint": {"source_sha": "src-1", "test_content_sha": "fp-of-test-and-helpers"}}],
        "runtime_provenance": {"observed_runtime_identity": "build-1", "environment_id": "env-1"}})
    use_project(root)
    PL._reset()
    return root


def trx_request(root: Path, *, location: str = XTESTS_LOCATION,
                reason: str = "Assert.Equal() Failure") -> Path:
    target = {"path": "backend/Calc.txt", "before_sha256": RS.digest(root / "backend" / "Calc.txt"),
              "replacement_utf8": "broken\n", "instance_id": "XTests.One",
              "expected_location": location, "expected_reason": reason,
              "obligation_id": "OB-ADD-1", "defect_location": "backend/Calc.txt:1",
              "assertion_id": "add_returns_sum"}
    path = root / "mutations.json"
    write_json(path, {"mutations": [target], "cases": ["TC-100"]})
    return path


def probe_cli(root: Path, request: Path, task_root: Path) -> dict:
    """`red_sandbox.py --probe` as the critic runs it: the JSON it prints plus `_exit_code`."""
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(root))
    proc = run_script("red_sandbox.py", "--probe", "--repo", root, "--request", request,
                      "--task-root", task_root, "--dispatch", "S5-qa-code-critic-1", cwd=root, env=env)
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip().startswith("{")]
    result = json.loads(lines[-1]) if lines else {"status": "no JSON printed", "stderr": proc.stderr[-400:]}
    return dict(result, _exit_code=proc.returncode)


def trx_run(*, report_test_id: bool = True, kind: str = "trx", ignore_test_file: bool = False,
            cli: bool = False, seed: bool = True, **request_kwargs) -> tuple:
    """(root, task_root, result, seeded): the project, its story, the probe's answer, and what the
    author's own green run left behind before the probe began (`seeded`: its requests and jobs), so a
    test can tell the probe's own launches from it. `seed=False` is for a row the runner cannot build
    a request for (no `report_test_id`): there is no green to seed, and the probe runs its own baseline."""
    fake_runner = temp_dir("qa-probe-fake-xunit-") / "runner.py"
    fake_runner.write_text(FAKE_XUNIT if kind == "trx" else FAKE_JUNIT_RUNNER, encoding="utf-8")
    root = trx_project(fake_runner, report_test_id=report_test_id, kind=kind,
                       ignore_test_file=ignore_test_file)
    task_root = root / "qa-factory" / "artifacts" / TASK
    if seed:
        seed_green(root, "TC-100")
    jobs = task_root / "state" / "execution-jobs"
    seeded = {"requests": len(mine_requests(task_root)), "jobs": len(list(jobs.glob("*.json"))) if jobs.is_dir() else 0}
    request = trx_request(root, **request_kwargs)
    if cli:
        return root, task_root, probe_cli(root, request, task_root), seeded
    return root, task_root, probe(root, request), seeded


def mine_requests(task_root: Path) -> list:
    paths = sorted((task_root / "work" / "requests").glob("mine-*.json"),
                   key=lambda p: p.stat().st_mtime)
    return [json.loads(p.read_text(encoding="utf-8")) for p in paths]


class recording_run_mine:
    """Records what `probe()` hands `_run_mine` (the cases, the clone, the node selection), and still runs it."""
    def __enter__(self):
        self.real, self.calls = RS._run_mine, []

        def wrapped(run_suite_path, repo, cases, **kwargs):
            self.calls.append(dict(kwargs, cases=list(cases)))
            return self.real(run_suite_path, repo, cases, **kwargs)
        RS._run_mine = wrapped
        return self

    def __exit__(self, *_exc):
        RS._run_mine = self.real


def trx_end_to_end() -> None:
    """A red probe of a non-pytest runner through the real run_suite.py: the clone is passed as
    --sandbox-root, so the profile's `backend/` directory is kept INSIDE it; the TRX is read by
    the shared reader; the row is the one whose test_id is the manifest's report_test_id. The
    unmutated run is the author's green (seeded), so the probe launches ONE run: the mutated one."""
    root, task_root, result, seeded = trx_run()
    try:
        check_eq("a TRX probe in a profile subdirectory is accepted", result.get("status"), "accepted")
        instance = (result.get("instances") or {}).get("XTests.One", {})
        mutated = instance.get("mutated") or {}
        check_eq("the failure site is read from the TRX stack frame, clone-relative",
                 (mutated.get("location"), mutated.get("failure_kind")), (XTESTS_LOCATION, "assertion"))
        check_eq("the unmutated run is the author's green, passed",
                 ((instance.get("baseline") or {}).get("status"), (instance.get("baseline") or {}).get("source")),
                 ("passed", "author"))
        check_eq("one receipt", len(result.get("receipts") or []), 1)
        requests = mine_requests(task_root)[seeded["requests"]:]
        check_eq("the probe launched ONE run, the mutated one: no baseline run", len(requests), 1)
        for label, request in zip(("mutated",), requests):
            cwd = Path(request["command"]["cwd"])
            check(f"the {label} run's directory is `backend` INSIDE its clone",
                  cwd.name == "backend" and "redprobe" in cwd.parent.name
                  and not cwd.is_relative_to(root.resolve()), str(cwd))
            files = [Path(f["path"]) for f in request["fingerprint_files"] if f["kind"] == "test_files"]
            check(f"the {label} fingerprint covers the clone's test file, never the author's",
                  len(files) == 1 and "redprobe" in str(files[0]) and not files[0].is_relative_to(root.resolve()),
                  str(files))
        check_eq("no sandbox is left behind", list(root.parent.glob(f"{root.name}-redprobe-*")), [])
    finally:
        finish_project(root)


def non_pytest_nodes_are_never_node_ids() -> None:
    """L9: `--node-id` is passed only for a pytest node (`<file>.py::<name>`). A `--node-id` row of the
    request carries no `report_test_id`, so for a runner that is not pytest it would drop the runner's
    own identity of the test and every row would be refused at the binding; such a case is launched
    WHOLE. A case that mixes the two is whole too. The red probe never passes `--cwd`: it always runs in
    the profile's directory inside the clone (`--sandbox-root`)."""
    # the selection, as a pure function
    placed = {"a": {"case": "TC-1", "node": "tests/t.py::test_a"}, "b": {"case": "TC-1", "node": "tests/t.py::test_b"},
              "c": {"case": "TC-2", "node": "backend/Tests/XTests.cs::XTests.One"},
              "d": {"case": "TC-3", "node": "tests/t.py::test_d"}, "e": {"case": "TC-3", "node": "Suite.Checks.One"}}
    check_eq("pytest nodes only: each is selected", RS._case_nodes(placed, "TC-1"),
             ["tests/t.py::test_a", "tests/t.py::test_b"])
    check_eq("a non-pytest node: the whole case, no selection", RS._case_nodes(placed, "TC-2"), [])
    check_eq("a case that mixes pytest and non-pytest nodes: whole", RS._case_nodes(placed, "TC-3"), [])
    check_eq("a case no target is in: nothing selected", RS._case_nodes(placed, "TC-9"), [])

    # the argv, as `_run_mine` builds it
    def argv_for(nodes) -> list:
        seen, real = {}, subprocess.run

        def capture(argv, **_kwargs):
            seen["argv"] = list(argv)
            return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")
        subprocess.run = capture
        try:
            RS._run_mine(Path("run_suite.py"), Path("."), ["TC-1"], dispatch="", sandbox_root=Path("the-clone"),
                         reason="r", again=False, timeout=5, node_ids=nodes)
        finally:
            subprocess.run = real
        return seen["argv"]

    argv = argv_for(("tests/t.py::test_a", "tests/t.py::test_b"))
    check_eq("two pytest nodes: one `--node-id` each, after the cases",
             [argv[i + 1] for i, a in enumerate(argv) if a == "--node-id"], ["tests/t.py::test_a", "tests/t.py::test_b"])
    check("the clone is `--sandbox-root`, and `--cwd` is never passed",
          argv[argv.index("--sandbox-root") + 1] == "the-clone" and "--cwd" not in argv, " ".join(argv))
    check("the red probe purpose is named", argv[argv.index("--purpose") + 1] == "red_probe", " ".join(argv))
    check("`node_ids=()` runs the whole case: no `--node-id` at all", "--node-id" not in argv_for(()))
    check("and the function takes no `cwd` at all", "cwd" not in inspect.signature(RS._run_mine).parameters)

    # the whole probe: a pytest target selects its node, a TRX target launches its case whole
    root = project(fake())
    try:
        seed_green(root, "TC-100")
        with recording_run_mine() as launched:
            probe(root, mutation_request(root))
        check_eq("a pytest target: its node is selected",
                 [(c["cases"], list(c["node_ids"])) for c in launched.calls], [(["TC-100"], ["tests/test_calc.py::test_add"])])
        check("...in a clone, with no `cwd` handed over",
              all("redprobe" in str(c["sandbox_root"]) and "cwd" not in c for c in launched.calls), str(launched.calls))
    finally:
        finish_project(root)
    with recording_run_mine() as launched:
        root, task_root, result, seeded = trx_run()
    try:
        check_eq("a TRX target: accepted", result.get("status"), "accepted")
        check_eq("...its case launched whole: no node selected", [(c["cases"], list(c["node_ids"])) for c in launched.calls],
                 [(["TC-100"], [])])
        check("...in a clone, with no `cwd` handed over",
              all("redprobe" in str(c["sandbox_root"]) and "cwd" not in c for c in launched.calls), str(launched.calls))
        # the runner's own request carries the identity of the TRX test: it would not with a `--node-id` row
        request = mine_requests(task_root)[seeded["requests"]:][0]
        check_eq("...and its request names the test by the manifest's own report_test_id",
                 {iid: c.get("report_test_id") for iid, c in (request.get("instance_contracts") or {}).items()},
                 {"XTests.One": "XTests.One"})
    finally:
        finish_project(root)


def trx_wrong_assertion_line_is_incomplete() -> None:
    root, task_root, result, _seeded = trx_run(location="backend/Tests/XTests.cs:4")
    try:
        check("an expected line the assertion is not on is not proof", result.get("status") == "survived",
              json.dumps(result)[:800])
        instance = (result.get("instances") or {}).get("XTests.One", {})
        check_eq("the instance is not valid", instance.get("valid"), False)
        check_eq("and the observed location is still reported",
                 (instance.get("mutated") or {}).get("location"), XTESTS_LOCATION)
        check_eq("nothing is published", result.get("receipts"), [])
    finally:
        finish_project(root)


def trx_without_report_test_id() -> None:
    """A non-pytest runner with no `report_test_id` on the manifest row: the runner itself refuses
    to build the request and names the door; nothing ran, so the probe says so (`not_executed`)
    instead of reading rows of a run that never happened. There is no author's green to ask for
    (the same refusal stops the request that would classify it): the probe runs its own baseline, and
    that run is the one the runner refuses."""
    root, task_root, result, _seeded = trx_run(report_test_id=False, seed=False)
    try:
        check_eq("no report_test_id on the row: nothing ran, never accepted by default",
                 result.get("status"), "not_executed")
        notes = " ".join(result.get("notes") or [])
        check_in("the note says the runner refused", "refused", notes)
        check_in("names the field", "report_test_id", notes)
        check_in("and the door that records it", "manifest_put.py", notes)
        check_eq("no sandbox is left behind", list(root.parent.glob(f"{root.name}-redprobe-*")), [])
    finally:
        finish_project(root)


# A pytest stand-in whose report spells every test one prefix further than the request predicts
# (`renamed.tests.test_calc::test_add`, where the request's `report_test_id` is
# `tests.test_calc::test_add`): the run is real, and no report row is the one the request named.
FAKE_PYTEST_RENAMED = FAKE_PYTEST.replace(
    '    classname = classname[:-3] if classname.endswith(".py") else classname\n',
    '    classname = classname[:-3] if classname.endswith(".py") else classname\n'
    '    classname = "renamed." + classname\n')


def junit_unmatched_report_id_is_the_probes_defect() -> None:
    """L2: a MUTATED target that no report row answers to is upstream's `probe_defect` (the probe's own
    run gave the test no result), exit 1, with the id the request named in the note - never `survived`
    and exit 0: the critic read "the test lets a mutation through" and filed test_defect for a gap of
    the factory (FR-41, FR-19, FR-46). The author's green stands for the unmutated run, so the stand-in
    is swapped for the renamed one AFTER the green was seeded: the mutated run alone is the one whose
    report no request id can find."""
    check("the renamed stand-in really spells the class differently", FAKE_PYTEST_RENAMED != FAKE_PYTEST)
    fake_pytest = fake()
    root = project(fake_pytest)
    task_root = task_of(root)
    try:
        seed_green(root, "TC-100")
        fake_pytest.write_text(FAKE_PYTEST_RENAMED, encoding="utf-8")
        result = probe_cli(root, mutation_request(root), task_root)
        check_eq("no row answers to the request's id on the mutated side: probe_defect, never survived",
                 result.get("status"), "probe_defect")
        check_eq("and the exit code says so", result.get("_exit_code"), 1)
        notes = " ".join(result.get("notes") or [])
        check_in("the note names the instance", "test_add", notes)
        check_in("and the id the request named", "tests.test_calc::test_add", notes)
        check_in("and says it is the probe's own run, not the test", "the probe's own run, not the test", notes)
        check_eq("nothing is published", result.get("receipts"), [])
        instance = (result.get("instances") or {}).get("test_add", {})
        check_eq("the mutated run is not_run (not a verdict on the mutation); the author's green is the baseline",
                 ((instance.get("mutated") or {}).get("status"), (instance.get("baseline") or {}).get("status")),
                 ("not_run", "passed"))
        check_eq("the proof says owner factory", (instance.get("verdict"), instance.get("owner")),
                 ("probe_defect", "factory"))
        check_eq("no sandbox is left behind", sandboxes(root), [])
    finally:
        finish_project(root)


# A pytest stand-in that spells the test one prefix further ONLY inside a baseline clone: the unmutated
# run's report has no row the request names, the mutated run's has.
FAKE_PYTEST_BASELINE_RENAMED = FAKE_PYTEST.replace(
    '    classname = classname[:-3] if classname.endswith(".py") else classname\n',
    '    classname = classname[:-3] if classname.endswith(".py") else classname\n'
    '    classname = ("renamed." + classname) if "-redprobe-baseline-" in os.getcwd() else classname\n')


def a_baseline_target_with_no_row_is_not_executed() -> None:
    """L2, the other side: when the probe runs its OWN baseline (the story cannot say what the author's
    green was) and no report row answers for the BASELINE target, nothing is proved either way:
    `not_executed`, with the instance and the side named; the verdict on record is `incomplete`, which
    never blocks a repeat (only a real survivor does)."""
    check("the baseline-only stand-in really differs", FAKE_PYTEST_BASELINE_RENAMED != FAKE_PYTEST)
    fake_pytest = fake()
    fake_pytest.write_text(FAKE_PYTEST_BASELINE_RENAMED, encoding="utf-8")
    root = project(fake_pytest)
    task_root = task_of(root)
    saved = ER.RUN_BUDGET_FILE
    ER.RUN_BUDGET_FILE = "no-such-run-budget.json"  # the story cannot say: today's own baseline
    try:
        result = probe(root, mutation_request(root))
        check_eq("a baseline target with no row: not_executed", result["status"], "not_executed")
        words = " ".join(result["notes"])
        check_in("the note names the instance and the baseline side", "test_add (baseline)", words)
        instance = result["instances"].get("test_add", {})
        check_eq("the mutated run failed as intended; the baseline read nothing",
                 ((instance.get("mutated") or {}).get("status"), (instance.get("baseline") or {}).get("status")),
                 ("failed", "not_run"))
        check_eq("nothing is published", result["receipts"], [])
        record = json.loads(PL.probe_record_path(task_root, "test_add", "product").read_text(encoding="utf-8"))
        check_eq("the record says incomplete, not survived", record["verdict"], "incomplete")
        check_eq("and an incomplete record does not block a repeat",
                 PL.already_probed(entry_of(root), manifest_of(root), task_root, project=root)["probed"], False)
        check_eq("no sandbox is left behind", sandboxes(root), [])
    finally:
        ER.RUN_BUDGET_FILE = saved
        finish_project(root)


def a_baseline_that_is_not_a_pass_is_incomplete() -> None:
    """FR-35: the answer and the product record say the same word. When the probe runs its own baseline
    and that run has a row that is NOT a pass (here: the unmutated product raises, an `error`), a failure
    of the mutated run is not the mutation's doing and nothing was shown about the test either way: the
    status is `incomplete` with the baseline status as the typed reason - it was `survived`, while the
    record already said `incomplete` - and nothing blocks a repeat."""
    root = project(fake(), products={"calc.py": "def add(a, b):\n    raise ValueError('the product is broken')\n"})
    task_root = task_of(root)
    saved = ER.RUN_BUDGET_FILE
    ER.RUN_BUDGET_FILE = "no-such-run-budget.json"  # the story cannot say: today's own baseline
    try:
        result = probe(root, mutation_request(root))
        check_eq("an unmutated run that errored: incomplete, never survived", result["status"], "incomplete")
        instance = result["instances"].get("test_add", {})
        check_eq("the mutated run failed as intended; the baseline row exists and is an error",
                 ((instance.get("mutated") or {}).get("status"), (instance.get("baseline") or {}).get("status")),
                 ("failed", "error"))
        check_eq("the typed reason is the baseline status", instance.get("baseline_status"), "error")
        check_in("and the notes say the unmutated run did not pass", "the unmutated run of this instance ended 'error'",
                 " ".join(result["notes"]))
        check_eq("nothing is published", result["receipts"], [])
        record = json.loads(PL.probe_record_path(task_root, "test_add", "product").read_text(encoding="utf-8"))
        check_eq("the record says the same word as the answer", record["verdict"], result["status"])
        check_eq("an incomplete record does not block a repeat",
                 PL.already_probed(entry_of(root), manifest_of(root), task_root, project=root)["probed"], False)
        again = probe(root, mutation_request(root))
        check_eq("the repeat is run, not answered", again["status"], "incomplete")
        check_eq("no sandbox is left behind", sandboxes(root), [])
    finally:
        ER.RUN_BUDGET_FILE = saved
        finish_project(root)


def junit_runner_that_is_not_pytest_is_incomplete() -> None:
    """F2: a failing row of a non-pytest `junit-xml` runner has a site nobody reads yet (B-337). The
    pytest last-traceback rule gave a Jest frame a garbage location and kind `exception`, and the
    probe ended `survived`, exit 0. It is `incomplete` with the typed reason, exit 1, no receipt."""
    root, task_root, result, _seeded = trx_run(kind="junit-xml", cli=True)
    try:
        check_eq("a non-pytest junit-xml probe whose failure site is unread is incomplete",
                 result.get("status"), "incomplete")
        check_eq("the exit code is 1", result.get("_exit_code"), 1)
        check_eq("nothing is published", result.get("receipts"), [])
        instance = (result.get("instances") or {}).get("XTests.One", {})
        mutated = instance.get("mutated") or {}
        check_eq("the mutated run failed, as the mutation intends", mutated.get("status"), "failed")
        check_eq("the instance is not valid, and says why", (instance.get("valid"), instance.get("verdict")),
                 (False, "incomplete_or_wrong_failure"))
        check("the unread site is typed, with the reporter and the runner's launcher",
              str(mutated.get("site_unread", "")).startswith("junit-xml/"), json.dumps(mutated))
        check_eq("no garbage location is claimed", (mutated.get("location"), mutated.get("failure_kind")), (None, None))
        # B-373 c (R12): the target is a `.cs` file, which now has an `assertion_probes` entry: its grammar reads the
        # row, and this runner's Jest-shaped frame is not a C# frame, so the site is still unread - now by the
        # reader that says WHY ("no frame matched"), not by the blanket "not read yet (B-337)"
        check_in("the proof's reason says the site was not read", "was not read: no frame of its stack matched the declared frame grammar",
                 instance.get("reason", ""))
        check_in("and the notes carry it too", "was not read: no frame of its stack matched the declared frame grammar",
                 " ".join(result.get("notes") or []))
        check_eq("the unmutated run is the author's green: passed", (instance.get("baseline") or {}).get("status"),
                 "passed")
        check_eq("no sandbox is left behind", list(root.parent.glob(f"{root.name}-redprobe-*")), [])
        # an `incomplete` proof is on record as `incomplete`: it blocks nothing, and a repeat is RUN again
        # (only a real survivor is answered `already_probed`, see `survived`)
        PL._reset()
        record = json.loads(PL.probe_record_path(task_root, "XTests.One", "product").read_text(encoding="utf-8"))
        check_eq("the product record says incomplete, never survived", record["verdict"], "incomplete")
        check_eq("an incomplete record does not block a repeat",
                 PL.already_probed(entry_of(root, "XTests.One"), manifest_of(root), task_root, project=root)["probed"],
                 False)
        again = probe(root, trx_request(root))
        check_eq("the repeat is run, not answered: incomplete again, by the same reason",
                 again.get("status"), "incomplete")
        check_eq("...and the record still says incomplete",
                 json.loads(PL.probe_record_path(task_root, "XTests.One", "product").read_text(encoding="utf-8"))["verdict"],
                 "incomplete")
    finally:
        finish_project(root)


def non_pytest_test_file_absent_from_the_clone_is_refused() -> None:
    """F3: under --sandbox-root a non-pytest test file is looked up in the clone ONLY. A file git
    ignores is in the author's tree and not in the clone; resolving it to the author's copy made the
    fingerprint cover the author's bytes (Fact 3). The run is refused before launch with a door."""
    root, task_root, result, seeded = trx_run(ignore_test_file=True)
    try:
        check_eq("a test file the clone does not hold is not run", result.get("status"), "not_executed")
        notes = " ".join(result.get("notes") or [])
        check_in("the runner refused it", "refused", notes)
        check_in("naming the file", "backend/Tests/XTests.cs", notes)
        check_in("and why: it is not in the clone", "is not in the sandbox clone", notes)
        check_in("with the door", "add it to the repository or run the probe on a tracked copy", notes)
        check_eq("no request was written after the author's own, so no fingerprint covers the author's bytes",
                 len(mine_requests(task_root)), seeded["requests"])
        jobs = task_root / "state" / "execution-jobs"
        check_eq("no job was begun after the author's own",
                 len(list(jobs.glob("*.json"))) if jobs.is_dir() else 0, seeded["jobs"])
    finally:
        finish_project(root)


# --- unit level: the reader's rows, the binding, the proof ----------------------------------------

TRX_HEAD = '<TestRun xmlns="http://microsoft.com/schemas/VisualStudio/TeamTest/2010">'


def trx_failed(test_id: str, frame: str, message: str = "Assert.Equal() Failure\nExpected: 4\nActual:   0",
               outcome: str = "Failed", uid: str = "one") -> str:
    stack = f"   at {test_id}() in {frame}" if frame else ""
    return (f'<UnitTestResult testId="{uid}" testName="{test_id}" outcome="{outcome}"><Output><ErrorInfo>'
            f"<Message>{message}</Message><StackTrace>{stack}</StackTrace></ErrorInfo></Output>"
            "</UnitTestResult>")


def rows_of(root: Path, name: str, body: str, reporter: str = "trx") -> list:
    path = root / "evidence" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(TRX_HEAD + "<Results>" + body + "</Results></TestRun>", encoding="utf-8")
    notes: list = []
    rows = RS._report_rows(root, {"reporter": reporter, "report_evidence": {"path": f"evidence/{name}"}},
                           notes, "mutated")
    return rows if not notes else rows + [("notes", notes)]


def target_of(**extra) -> dict:
    target = {"instance_id": "Suite.Checks.critical_check", "expected_location": "backend/Tests/ChecksTests.cs:42",
              "expected_reason": "Assert.Equal() Failure", "obligation_id": "OB-1",
              "defect_location": "backend/Calc.cs:3", "assertion_id": "a-1"}
    target.update(extra)
    return target


def contracts_for(target: dict, report_id: str) -> dict:
    """The job request's `instance_contracts`, as `bind_row` reads them: instance id -> contract."""
    return {target["instance_id"]: {"report_test_id": report_id, "parameters": {}}}


def trx_report_rows_are_usable_for_red_proof() -> None:
    """The .NET xUnit adapter writes TRX, not the JUnit XML a Python profile uses (the legacy run
    TP2-2406). The row is bound by the request's exact report_test_id - the legacy
    port matched a SUFFIX of the name, which is a guess and binds the wrong test the day two
    classes share a method name."""
    root = temp_dir("qa-probe-trx-")
    try:
        clone = root / "clone"
        author = root / "author"
        frame = str(clone / "backend" / "Tests" / "ChecksTests.cs") + ":line 42"
        rows = rows_of(root, "report.trx",
                       trx_failed("Suite.Checks.critical_check", frame)
                       + '<UnitTestResult testId="two" testName="Suite.Checks.green_check" outcome="Passed"/>')
        check_eq("TRX needs no parse-gap note", [r for r in rows if isinstance(r, tuple)], [])
        failed, passed = rows
        check_eq("the row keeps the runner's own test name", failed["test_id"], "Suite.Checks.critical_check")
        entry = contracts_for(target_of(), "Suite.Checks.critical_check")
        row, note = RS.bind_row(target_of(), entry, rows, "trx")
        check_eq("the exact report_test_id binds the row", (row, note), (failed, ""))
        result = RS.target_result(target_of(), row, "trx", clone)
        check_eq("TRX preserves the failing outcome", result["status"], "failed")
        check_in("and the reporter's own failure message", "Assert.Equal() Failure", result["reason"])
        check_eq("the stack frame in the clone is the clone-relative location",
                 (result.get("location"), result.get("failure_kind")),
                 ("backend/Tests/ChecksTests.cs:42", "assertion"))
        check_eq("an assertion in the expected file is the intended failure", result.get("semantic_verdict"),
                 "intended_failure")
        receipt = {"repo": str(root), "original_hashes": {}, "targets": [target_of()]}
        baseline = [{"instance_id": target_of()["instance_id"], "status": "passed"}]
        check_eq("with a passed baseline the probe is accepted",
                 RS.verify(receipt, [result], baseline)["status"], "accepted")
        check("a TRX headline plus the reporter's Expected/Actual detail still matches the pinned headline",
              RS.reason_matches("Assert.IsType() Failure\nExpected: x\nActual: y", "Assert.IsType() Failure"))
        check("a different assertion headline does not",
              not RS.reason_matches("Assert.IsType() Failure\nExpected: x", "Assert.Equal() Failure"))

        # a frame outside the clone: the AUTHOR's build ran, which proves nothing about the clone
        foreign = str(author / "backend" / "Tests" / "ChecksTests.cs") + ":line 42"
        rows = rows_of(root, "foreign.trx", trx_failed("Suite.Checks.critical_check", foreign))
        row, _ = RS.bind_row(target_of(), entry, rows, "trx")
        result = RS.target_result(target_of(), row, "trx", clone)
        # B-373 c (R12): `.cs` has an `assertion_probes` entry, so its frame grammar reads the row (R11): a frame
        # that does not resolve to a project file of THIS clone is never turned into a location - not even as
        # an `exception` at the author's path - and the typed unread answer takes its place
        check_eq("a frame in the author's tree is UNREAD, never a location (the entry's grammar, R11)",
                 (result.get("site_unread"), result.get("location"), result.get("failure_kind")),
                 ("trx/unknown runtime", None, None))
        check_in("...with the reason it was not resolved", "is not inside the clone", result.get("site_unread_reason", ""))
        check_eq("so the probe stays incomplete",
                 RS.verify(receipt, [result], baseline)["status"], "incomplete")

        # an assertion on another line, in the right file
        wrong = str(clone / "backend" / "Tests" / "ChecksTests.cs") + ":line 41"
        rows = rows_of(root, "wrong.trx", trx_failed("Suite.Checks.critical_check", wrong))
        row, _ = RS.bind_row(target_of(), entry, rows, "trx")
        result = RS.target_result(target_of(), row, "trx", clone)
        check_eq("the observed line is reported", result.get("location"), "backend/Tests/ChecksTests.cs:41")
        check_eq("a wrong assertion line is incomplete",
                 RS.verify(receipt, [result], baseline)["status"], "incomplete")

        # a failure with no located frame at all
        rows = rows_of(root, "bare.trx", trx_failed("Suite.Checks.critical_check", ""))
        row, _ = RS.bind_row(target_of(), entry, rows, "trx")
        result = RS.target_result(target_of(), row, "trx", clone)
        check_eq("no located frame: no location, no failure kind", (result.get("location"), result.get("failure_kind")),
                 (None, None))
        check_eq("and the probe is incomplete", RS.verify(receipt, [result], baseline)["status"], "incomplete")

        # a timeout is an error row, never an assertion
        rows = rows_of(root, "timeout.trx", trx_failed("Suite.Checks.critical_check", frame, outcome="Timeout"))
        row, _ = RS.bind_row(target_of(), entry, rows, "trx")
        result = RS.target_result(target_of(), row, "trx", clone)
        check_eq("a timeout is an error", (result["status"], result.get("failure_kind")), ("error", "error"))
        check_eq("and no semantic verdict is claimed", result.get("semantic_verdict"), None)
    finally:
        cleanup(root)


def row_binding() -> None:
    """Every row is bound by the JOB REQUEST's `instance_contracts[iid].report_test_id` (FR-16: the
    identity the runner produced), EXACT. None carried: a pytest command falls back to the pinned
    node's tail, any other runner is `not_run` with the door. Nothing matched, or more than one, is
    `not_run` with the reason - never a guess."""
    root = temp_dir("qa-probe-binding-")
    try:
        rows = rows_of(root, "b.trx",
                       '<UnitTestResult testId="1" testName="A.Checks.Total" outcome="Passed"/>'
                       '<UnitTestResult testId="2" testName="B.Checks.Total" outcome="Passed"/>'
                       '<UnitTestResult testId="3" testName="Total" outcome="Failed"/>'
                       '<UnitTestResult testId="4" testName="Dup.Total" outcome="Passed"/>'
                       '<UnitTestResult testId="5" testName="Dup.Total" outcome="Failed"/>')
        target = {"instance_id": "inst-1"}

        def bind(report_id, reporter="trx", ticket="", **kwargs):
            return RS.bind_row(target, contracts_for(target, report_id), rows, reporter, ticket, **kwargs)

        row, note = bind("A.Checks.Total")
        check_eq("trx: the exact id binds", (row["test_id"], note), ("A.Checks.Total", ""))
        row, note = bind("Checks.Total")
        check_eq("trx: a SUFFIX of a name is not a match (the legacy endswith is a guess)", row, None)
        check_in("and the note says nothing was named so", "Checks.Total", note)
        row, note = bind("Total")
        check_eq("trx: a name that is a suffix of others binds only the row that IS that name",
                 (row["test_id"], row["status"]), ("Total", "failed"))
        row, note = bind("Dup.Total", "junit-xml")
        check_eq("an ambiguous id binds nothing", row, None)
        check_in("and names the id", "Dup.Total", note)
        check_in("and says it is ambiguous", "ambiguous", note)
        check_in("and how many rows carry it", "2", note)

        # a request that names no id for the target: edges
        for label, contracts in (("no instance_contracts at all", None), ("an empty mapping", {}),
                                 ("another instance's contract only", {"other": {"report_test_id": "Total"}}),
                                 ("a contract with an empty report_test_id", contracts_for(target, "")),
                                 ("a blank report_test_id", contracts_for(target, "  ")),
                                 ("a contract that is not an object", {"inst-1": "Total"})):
            row, note = RS.bind_row(target, contracts, rows, "trx", "QA-1")
            check_eq(f"{label}: nothing is bound", row, None)
            check_in(f"{label}: the note names the instance", "inst-1", note)
            check_in(f"{label}: and the door that records the id", "manifest_put.py", note)
            check_in(f"{label}: with the ticket", "QA-1", note)
        row, note = RS.bind_row(target, None, rows, "junit-xml")
        check_eq("a non-pytest junit-xml runner with no id is the same refusal, with no tail guess",
                 (row, "manifest_put.py" in note), (None, True))

        # two contracts carry one id: which instance owns the row is unknown
        shared = {"inst-1": {"report_test_id": "A.Checks.Total"}, "inst-2": {"report_test_id": "A.Checks.Total"}}
        row, note = RS.bind_row(target, shared, rows, "trx")
        check_eq("an id carried by two contracts binds nothing", row, None)
        check_in("the note says ambiguous", "ambiguous", note)
        check_in("and names both instances", "inst-1, inst-2", note)

        # pytest: the request's id decides; the node tail is the fallback when the request has none
        pytest_rows = [{"test_id": "tests.test_calc::test_add", "status": "failed", "problems": []},
                       {"test_id": "tests.test_other::test_sub", "status": "passed", "problems": []}]
        pinned = {"instance_id": "i", "node_id": "tests/test_calc.py::test_add"}
        row, note = RS.bind_row(pinned, contracts_for(pinned, "tests.test_calc::test_add"), pytest_rows,
                                "junit-xml", pytest_command=True)
        check_eq("a pytest command under junit-xml: the request's id binds", (row["test_id"], note),
                 ("tests.test_calc::test_add", ""))
        row, note = RS.bind_row({"instance_id": "i"}, contracts_for({"instance_id": "i"}, "tests.test_other::test_sub"),
                                pytest_rows, "junit-xml", pytest_command=True)
        check_eq("and it binds with no pinned node id at all: the id decides, not the tail",
                 (row["test_id"], note), ("tests.test_other::test_sub", ""))
        row, note = RS.bind_row(pinned, contracts_for(pinned, "tests.test_other::test_sub"), pytest_rows,
                                "junit-xml", pytest_command=True)
        check_eq("the request's id wins over the pinned node's tail", row["test_id"], "tests.test_other::test_sub")
        row, note = RS.bind_row(pinned, contracts_for(pinned, "renamed.tests.test_calc::test_add"), pytest_rows,
                                "junit-xml", pytest_command=True)
        check_eq("an id no report row carries binds nothing, even when the tail would have", row, None)
        check_in("and the note names the id", "renamed.tests.test_calc::test_add", note)
        for label, contracts in (("no instance_contracts", None), ("an empty mapping", {}),
                                 ("an empty report_test_id", contracts_for(pinned, ""))):
            row, note = RS.bind_row(pinned, contracts, pytest_rows, "junit-xml", pytest_command=True)
            check_eq(f"pytest, {label}: the node tail binds (the fallback)", (row["test_id"], note),
                     ("tests.test_calc::test_add", ""))
            row, note = RS.bind_row(pinned, contracts, pytest_rows, "pytest")
            check_eq(f"the `pytest` reporter, {label}: the same, with no flag", row["test_id"],
                     "tests.test_calc::test_add")
        row, note = RS.bind_row({"instance_id": "i"}, {}, pytest_rows, "pytest")
        check_eq("pytest: no pinned node id binds nothing, as before", row, None)
        check_in("and says why", "no pinned node_id", note)
        row, note = RS.bind_row({"instance_id": "i", "node_ids": ["t.py::test_sub"]}, {}, pytest_rows, "pytest")
        check_eq("pytest: node_ids[0] is read when node_id is absent", row["test_id"], "tests.test_other::test_sub")
        twice = pytest_rows + [{"test_id": "tests.other::test_add", "status": "passed", "problems": []}]
        row, note = RS.bind_row({"instance_id": "i", "node_id": "t.py::test_add"}, {}, twice, "pytest")
        check_eq("pytest: two rows with one tail are ambiguous, as before", (row, "ambiguous" in note), (None, True))
        row, note = RS.bind_row(pinned, {}, twice, "junit-xml")
        check_eq("a junit-xml run that is not a pytest command never falls back to the tail", row, None)
    finally:
        cleanup(root)


def run_contracts_are_read_from_the_job() -> None:
    """The contracts come from the job record of THAT run (`state/execution-jobs`), found by its
    summary path or by its label - the request as it was launched, respelled node ids included."""
    root = temp_dir("qa-probe-jobs-")
    try:
        jobs = root / "state" / "execution-jobs"
        jobs.mkdir(parents=True)
        mine = {"idempotency_key": "k1", "job_id": "abc123", "summary": "ev/red_probe-abc123-1.json",
                "request": {"instance_contracts": {"a": {"report_test_id": "x::a"}}}}
        other = {"idempotency_key": "k2", "job_id": "def456", "summary": "ev/red_probe-def456-1.json",
                 "request": {"instance_contracts": {"a": {"report_test_id": "y::a"}}}}
        for job in (mine, other):
            write_json(jobs / (job["job_id"] + ".json"), job)
        (jobs / "corrupt.json").write_text("{", encoding="utf-8")
        notes: list = []
        found = RS._run_contracts(root, {"summary_path": "ev/red_probe-abc123-1.json", "label": "x"}, notes, "mutated")
        check_eq("found by the summary path", (found, notes), ({"a": {"report_test_id": "x::a"}}, []))
        found = RS._run_contracts(root, {"label": "red_probe-def456"}, notes, "mutated")
        check_eq("else by the job id the label carries", (found, notes), ({"a": {"report_test_id": "y::a"}}, []))
        found = RS._run_contracts(root, {"summary_path": "elsewhere.json", "label": "red_probe-zzz"}, notes, "baseline")
        check_eq("a run no job answers to has no contracts", found, {})
        check_in("and the note says which run", "baseline run", " ".join(notes))
        notes = []
        no_store = RS._run_contracts(root / "absent", {"summary_path": "ev/x.json"}, notes, "mutated")
        check_eq("no job store at all is the same, never a crash", (no_store, len(notes)), ({}, 1))
        write_json(jobs / "bare.json", {"idempotency_key": "k3", "job_id": "bare", "summary": "ev/bare.json",
                                         "request": {"purpose": "red_probe"}})
        check_eq("a job whose request has no instance_contracts has none",
                 RS._run_contracts(root, {"summary_path": "ev/bare.json"}, [], "mutated"), {})
    finally:
        cleanup(root)


def baseline_must_pass() -> None:
    """Fact 7: `verify()` never asked the unmutated run to be green, so a test that failed
    anyway - or never ran - could be 'proved sensitive' by a mutation. Only a baseline that
    PASSED lets a failure be read as the mutation's doing."""
    receipt = {"repo": "unused", "original_hashes": {}, "targets": [{
        "instance_id": "i-1", "expected_location": "tests/t.py:3", "expected_reason": "boom"}]}
    red = {"instance_id": "i-1", "status": "failed", "failure_kind": "assertion",
           "location": "tests/t.py:3", "reason": "AssertionError: boom", "semantic_verdict": "intended_failure"}

    def verdict(base):
        return RS.verify(receipt, [red], base)

    check_eq("a passed baseline and a matching red: accepted",
             verdict([{"instance_id": "i-1", "status": "passed"}])["status"], "accepted")
    check_eq("no baseline supplied: unchanged, accepted", RS.verify(receipt, [red])["status"], "accepted")
    for status in ("not_run", "skipped", "error"):
        answer = verdict([{"instance_id": "i-1", "status": status}])
        proof = answer["proofs"][0]
        check_eq(f"a baseline that is {status} is incomplete, never valid", (answer["status"], proof["valid"]),
                 ("incomplete", False))
        check_in(f"and names the baseline status ({status})", status, json.dumps(proof))
    answer = verdict([{"instance_id": "i-1", "status": "failed"}])
    check_eq("both runs failed is still a probe defect, as today", answer["status"], "probe_defect")
    answer = verdict([])
    check_eq("a baseline with no row for the instance is incomplete", answer["status"], "incomplete")
    check_in("naming that it is absent", "absent", json.dumps(answer["proofs"][0]))
    nothing = {"instance_id": "i-1", "status": "not_run"}
    answer = RS.verify(receipt, [nothing], [{"instance_id": "i-1", "status": "not_run"}])
    # L2: a MUTATED run that gave the test no result is upstream's `probe_defect` (D8), not an
    # incomplete proof - and never "a mutation that changed nothing" (the words say it is the probe's run)
    check_eq("a mutated run that read nothing is the probe's own defect", answer["status"], "probe_defect")
    check_in("...said in upstream's words", "the mutated run gave this test no result (not_run)",
             json.dumps(answer["proofs"][0]))
    # Generic text is never proof: every part must hold.
    for label, change in (("a generic failure kind", {"failure_kind": "exception"}),
                          ("another location", {"location": "tests/t.py:4"}),
                          ("another reason", {"reason": "something else entirely"})):
        answer = RS.verify(receipt, [{**red, **change}], [{"instance_id": "i-1", "status": "passed"}])
        check_eq(f"{label} is not proof even with a passed baseline", answer["status"], "incomplete")
    answer = RS.verify(receipt, [{**red, "status": "error"}], [{"instance_id": "i-1", "status": "passed"}])
    check_eq("a mutated error is no result either: probe_defect, never proof", answer["status"], "probe_defect")


def site_unread_is_incomplete() -> None:
    """F2 at the unit level: `target_result` carries the typed `site_unread`, never a garbage location,
    never overwrites the failure's own reason; `verify` turns it into an incomplete proof with that
    reason - the status the wrong-line case already uses - and `probe_defect` still outranks it."""
    # a suffix with NO `assertion_probes` entry (B-373 c, R12: `.ts` has one now and is read, see
    # `frames_from_the_table`): its site stays typed unread, as it was before the table
    target = target_of(expected_location="tests/x.test.kt:5")
    jest = {"test_id": "XTests::One", "status": "failed", "problems": [{
        "kind": "failure", "message": "expect(received).toBe(expected)",
        "text": "Error: expect(received).toBe(expected)\n\n      at Object.<anonymous> (/clone/tests/x.test.ts:5:20)"}]}
    result = RS.target_result(target, jest, "junit-xml", "/clone", command=["npx", "jest", "--ci"])
    check_eq("the status is the row's own", result["status"], "failed")
    check_eq("the failure's own message stays the reason", result["reason"], "expect(received).toBe(expected)")
    check_eq("the site is typed unread, with the reporter and the launcher", result.get("site_unread"), "junit-xml/npx")
    check_in("and carries the reason it is not read", "the assertion site of a junit-xml/npx report is not read yet (B-337)",
             result.get("site_unread_reason", ""))
    check_eq("no location, no failure kind, no semantic verdict",
             (result.get("location"), result.get("failure_kind"), result.get("semantic_verdict")), (None, None, None))
    result_unknown = RS.target_result(target, jest, "junit-xml", "/clone", command=[])
    check_eq("a command that names no launcher is an unknown runtime", result_unknown.get("site_unread"),
             "junit-xml/unknown runtime")

    receipt = {"repo": "unused", "original_hashes": {}, "targets": [target]}
    passed = [{"instance_id": target["instance_id"], "status": "passed"}]
    verdict = RS.verify(receipt, [result], passed)
    proof = verdict["proofs"][0]
    check_eq("verify: incomplete, never valid", (verdict["status"], proof["valid"]), ("incomplete", False))
    check_in("with that reason in the proof", "not read yet (B-337)", proof.get("reason", ""))
    check_eq("and the typed marker", proof.get("site_unread"), "junit-xml/npx")
    check_eq("the same with no baseline supplied", RS.verify(receipt, [result])["status"], "incomplete")
    mutation_unseen = dict(result, mutation_observed=False)
    check_eq("a mutation that changed nothing is still a probe defect, first",
             RS.verify(receipt, [mutation_unseen], passed)["status"], "probe_defect")

    # pytest keeps its rule: the same row of a pytest command is read by the last traceback line
    pytest_row = {"test_id": "tests.x::t", "status": "failed", "problems": [{
        "kind": "failure", "message": "AssertionError: boom", "text": "tests/x.py:3: AssertionError"}]}
    for command in (["python", "-m", "pytest", "-q"], None):
        read = RS.target_result(target_of(expected_location="tests/x.py:3"), pytest_row, "junit-xml", "/clone",
                                command=command)
        check_eq(f"a pytest command ({command}): the site is read as it always was",
                 (read.get("location"), read.get("failure_kind"), read.get("site_unread")),
                 ("tests/x.py:3", "assertion", None))
    # a passed row has no site to read, whatever the runner is
    green = RS.target_result(target, {"test_id": "a", "status": "passed", "problems": []}, "junit-xml", "/c",
                             command=["npx", "jest"])
    check_eq("a passed row of a non-pytest runner is not 'unread'", (green["status"], "site_unread" in green),
             ("passed", False))


def no_reporter_no_rows() -> None:
    root = temp_dir("qa-probe-noreporter-")
    try:
        (root / "evidence").mkdir()
        (root / "evidence" / "r.xml").write_text("<testsuite><testcase classname='a' name='b'/></testsuite>",
                                                  encoding="utf-8")
        for label, summary in (("no reporter", {"report_evidence": {"path": "evidence/r.xml"}}),
                               ("reporter none", {"reporter": "none", "report_evidence": {"path": "evidence/r.xml"}}),
                               ("an unknown reporter", {"reporter": "tap", "report_evidence": {"path": "evidence/r.xml"}})):
            notes: list = []
            rows = RS._report_rows(root, summary, notes, "mutated")
            check_eq(f"{label}: no rows are read", rows, [])
            check_in(f"{label}: the receipt says the proof is incomplete and why", "reporter", " ".join(notes))
        notes = []
        rows = RS._report_rows(root, {"reporter": "junit-xml", "report_evidence": {"path": "evidence/r.xml"}},
                               notes, "mutated")
        check_eq("a declared reporter reads the same file", ([r["test_id"] for r in rows], notes), (["a::b"], []))
    finally:
        cleanup(root)


def the_door_is_a_command_the_cli_takes() -> None:
    """item 8: `window_record.py` names the probe command; every flag in it must be one the script it
    names accepts, and the ones that script requires must all be there. Upstream's door (O4 = b) is the
    default probe, `probe_by_code.py`; `red_sandbox.py --probe` is the critic's doubt, and the
    door `probe_by_code` gives for a test that is not a Python file."""
    door = window_record.ORIGIN["probe"][1]
    flags = [part for part in door.replace("`", " ").split() if part.startswith("--")]
    script = "probe_by_code.py" if "probe_by_code.py" in door else "red_sandbox.py"
    helped = run_script(script, "--help").stdout
    check("the door names one of the two probes", script in door, door)
    for flag in flags:
        check_in(f"{script} takes {flag}", flag, helped)
    for needed in (("--task", "--dispatch", "--test", "--instance") if script == "probe_by_code.py"
                   else ("--repo", "--request", "--task-root")):
        check_in(f"the door names {needed}, which {script} requires", needed, door)
    check_not_in("and does not name --cwd or --sandbox-root, which neither probe takes", "--sandbox-root", door)
    check_not_in("...nor --cwd", "--cwd", door)
    sandbox_help = run_script("red_sandbox.py", "--help").stdout
    for flag in ("--probe", "--repo", "--request", "--task-root"):
        check_in(f"red_sandbox.py takes {flag} (the door of a non-Python test)", flag, sandbox_help)


def request_status_of_proofs() -> None:
    """The status of a request of several targets (F1 of the review): a REAL survivor - an invalid proof
    that is neither the probe's defect nor a proof that could not be judged - is the request's answer,
    whatever another target's tooling state is, so the status never contradicts the `survived` record
    `_write_product_records` writes for it. One predicate (`product_verdict`) serves both. A target
    that could not be judged is alone what it was: `incomplete` / `not_executed`. The probe's own
    defect keeps upstream's precedence over everything."""
    def target(name: str, line: int = 3) -> dict:
        return {"instance_id": name, "expected_location": f"tests/t.py:{line}", "expected_reason": "boom"}

    def failed(name: str, line: int = 3, **extra) -> dict:
        return {"instance_id": name, "status": "failed", "failure_kind": "assertion", "reason": "AssertionError: boom",
                "location": f"tests/t.py:{line}", "semantic_verdict": "intended_failure", **extra}

    def passed(name: str) -> dict:
        return {"instance_id": name, "status": "passed"}

    def judged(*parts) -> tuple:
        """(request status, the words of the records) of targets given as (result, baseline, unread-baseline?)."""
        receipt = {"repo": "unused", "original_hashes": {}, "targets": [target(r["instance_id"]) for r, _b, _u in parts]}
        verdict = RS.verify(receipt, [r for r, _b, _u in parts], [b for _r, b, _u in parts])
        unrun = [(r["instance_id"], "baseline") for r, _b, unread in parts if unread]
        return RS.request_status(verdict, unrun), [RS.product_verdict(p) for p in verdict["proofs"]]

    survivor = (failed("A", line=9), passed("A"), False)  # failed at tests/t.py:9, not :3: a plain survivor
    skipped = (failed("B"), {"instance_id": "B", "status": "skipped"}, False)
    no_row = (failed("B"), {"instance_id": "B", "status": "not_run"}, True)
    unread = ({"instance_id": "B", "status": "failed", "reason": "boom", "site_unread": "junit-xml/npx",
               "site_unread_reason": "the assertion site of a junit-xml/npx report is not read yet (B-337)"},
              passed("B"), False)
    check_eq("a survivor alone: survived, and its record says so", judged(survivor), ("survived", ["survived"]))
    for label, tooling, alone, word in (("a baseline that was skipped", skipped, "incomplete", "incomplete"),
                                        ("a baseline with no row", no_row, "not_executed", "incomplete"),
                                        ("a failure site nobody reads", unread, "incomplete", "incomplete")):
        check_eq(f"{label} alone: {alone}, unchanged", judged(tooling), (alone, [word]))
        status, words = judged(survivor, tooling)
        check_eq(f"a survivor beside {label}: survived (it is not masked)", status, "survived")
        check_eq("...and the records agree: the survivor `survived`, the other `incomplete`", words,
                 ["survived", "incomplete"])
        status, _words = judged(tooling, survivor)
        check_eq(f"...in either order ({label})", status, "survived")
    check_eq("a survivor and an accepted target: survived", judged(survivor, (failed("B"), passed("B"), False))[0],
             "survived")
    defect = ({"instance_id": "C", "status": "not_run"}, passed("C"), False)
    check_eq("upstream's order is unchanged: the probe's defect outranks a survivor",
             judged(survivor, defect)[0], "probe_defect")
    skipped_run = ({"instance_id": "D", "status": "skipped"}, passed("D"), False)
    check_eq("every invalid proof a defect: probe_defect", judged(defect, skipped_run)[0], "probe_defect")
    check_eq("all valid: accepted", judged((failed("A"), passed("A"), False), (failed("B"), passed("B"), False))[0],
             "accepted")


def two_targets_one_survivor_beside_a_baseline_that_proves_nothing() -> None:
    """F1 through the real probe: test_add's mutated run fails at the right place for the wrong reason
    (a survivor), test_sub's baseline run is `skipped` / has no report row. The probe runs its own
    baseline (the story cannot say), so the baseline of test_sub is the one the stand-in spoils. The
    request answers `survived`; test_sub's record says `incomplete` and blocks nothing; test_sub alone
    is `incomplete` / `not_executed`, as before."""
    spoil_skip = FAKE_PYTEST.replace(
        "def run_one(node):\n    file_part, func_part = node.split(\"::\", 1)\n",
        "def run_one(node):\n    file_part, func_part = node.split(\"::\", 1)\n"
        "    if \"-redprobe-baseline-\" in os.getcwd() and func_part == \"test_sub\":\n"
        "        return \"skipped\", \"\", \"\"\n")
    spoil_row = FAKE_PYTEST.replace(
        '    classname = classname[:-3] if classname.endswith(".py") else classname\n',
        '    classname = classname[:-3] if classname.endswith(".py") else classname\n'
        '    if "-redprobe-baseline-" in os.getcwd() and func_part == "test_sub":\n'
        '        classname = "renamed." + classname\n')
    check("the two spoiled stand-ins really differ", len({FAKE_PYTEST, spoil_skip, spoil_row}) == 3)
    products = {"calc.py": CALC_OK, "calc2.py": CALC2_OK}

    def targets_of(root: Path) -> dict:
        return {
            "survivor": {"path": "calc.py", "before_sha256": RS.digest(root / "calc.py"),
                         "replacement_utf8": CALC_BROKEN, "instance_id": "test_add",
                         "node_id": "tests/test_calc.py::test_add",
                         "expected_location": f"tests/test_calc.py:{MULTI_LINES['test_add']}",
                         "expected_reason": "a completely different assertion message",
                         "obligation_id": "OB-ADD-1", "defect_location": "calc.py:2", "assertion_id": "add_returns_sum"},
            "other": {"path": "calc2.py", "before_sha256": RS.digest(root / "calc2.py"),
                      "replacement_utf8": CALC2_BROKEN, "instance_id": "test_sub",
                      "node_id": "tests/test_calc.py::test_sub",
                      "expected_location": f"tests/test_calc.py:{MULTI_LINES['test_sub']}",
                      "expected_reason": "difference must be 3",
                      "obligation_id": "OB-SUB-1", "defect_location": "calc2.py:2", "assertion_id": "sub_returns_difference"}}

    saved = ER.RUN_BUDGET_FILE
    ER.RUN_BUDGET_FILE = "no-such-run-budget.json"  # the story cannot say: today's own baseline
    try:
        for label, source, alone_status in (("a baseline that was skipped", spoil_skip, "incomplete"),
                                            ("a baseline with no report row", spoil_row, "not_executed")):
            for which, wanted in (("beside a survivor", ("survived", {"test_add": "survived", "test_sub": "incomplete"})),
                                  ("alone", (alone_status, {"test_sub": "incomplete"}))):
                fake_pytest = fake()
                fake_pytest.write_text(source, encoding="utf-8")
                root = project(fake_pytest, tests=MULTI, products=products)
                write_json(task_of(root) / "work" / "automation-manifest.json", {"tests": [
                    row_of(root, "test_add", "TC-100"), row_of(root, "test_sub", "TC-100"),
                    row_of(root, "test_mul", "TC-100")]})
                try:
                    targets = targets_of(root)
                    chosen = [targets["survivor"], targets["other"]] if which == "beside a survivor" else [targets["other"]]
                    result = probe(root, mutation_request(root, targets=chosen))
                    check_eq(f"{label}, {which}: the request's status", result["status"], wanted[0])
                    records = {}
                    for iid in wanted[1]:
                        path = PL.probe_record_path(task_of(root), iid, "product")
                        records[iid] = json.loads(path.read_text(encoding="utf-8"))["verdict"] if path.is_file() else None
                    check_eq(f"{label}, {which}: the records, and the status never contradicts a `survived` one",
                             records, wanted[1])
                    check_eq(f"{label}, {which}: nothing is published", result["receipts"], [])
                    check_eq(f"{label}, {which}: no sandbox is left behind", sandboxes(root), [])
                finally:
                    finish_project(root)
    finally:
        ER.RUN_BUDGET_FILE = saved


def two_differing_mutations_of_one_path_are_refused_before_anything() -> None:
    """B-314 at the head of `probe()`: two mutations that rewrite one path with different text are refused
    before the manifest is read, an `already_probed` answer is given, a sandbox is prepared or a record
    is written - `prepare()` would refuse it too, but only after all of that. Identical replacements
    lose nothing and pass."""
    root = project(fake())
    task_root = task_of(root)
    try:
        seed_green(root, "TC-100")
        seeded = len(launches(root))
        first = json.loads(mutation_request(root).read_text(encoding="utf-8"))["mutations"][0]
        second = dict(first, instance_id="test_other", replacement_utf8=CALC_BROKEN + "# and then some\n")
        request = mutation_request(root, targets=[first, second])
        manifest_path = task_root / "work" / "automation-manifest.json"
        manifest_path.unlink()  # a manifest read would say "names no such test": the refusal comes first
        with counting_prepare() as prepared:
            result = probe(root, request)
        check_eq("two differing mutations of one file: not_executed", result["status"], "not_executed")
        words = " ".join(result["notes"])
        check_in("the note names the two mutations and the one file", "both rewrite calc.py with different text", words)
        check_in("and the door: one probe per mutation, or one combined replacement", "one combined replacement", words)
        check_not_in("no manifest was read: its absence is not what was said", "names no such test", words)
        check_eq("nothing was prepared, launched, left on disk or recorded",
                 (prepared.calls, len(launches(root)) - seeded, sandboxes(root),
                  PL.probe_record_path(task_root, "test_add", "product").exists()), ([], 0, [], False))
        # the same file twice with IDENTICAL text is not a conflict
        twin = dict(first, instance_id="test_twin")
        try:
            RS.refuse_same_path(root, [first, twin])
            passed = True
        except RS.MutationConflict:
            passed = False
        check("identical replacements of one path pass the check", passed)
        try:
            RS.refuse_same_path(root, [first, second])
            refused = False
        except RS.MutationConflict:
            refused = True
        check("and differing ones are the refusal", refused)
    finally:
        finish_project(root)


def volatile_prefixes_cover_both_layouts() -> None:
    """M20 and `records/` (L7): the tracked journal, the ledger and the approvals moved from `state/` to
    `records/` in 0.8.1, so both folders - built from `runtime_paths`, never typed - are the factory's own
    live files: named in the receipt, neither copied nor compared. An old-layout project (its journal
    under `state/`), a new-layout one (`records/`) and one holding both are covered, and a mutation aimed
    at either folder is refused."""
    import runtime_paths
    check_eq("the state prefix is built from runtime_paths", RS.STATE_PREFIX,
             f"{runtime_paths.HOME}/{runtime_paths.STATE}/")
    check_eq("the records prefix is built from runtime_paths", RS.RECORDS_PREFIX,
             f"{runtime_paths.HOME}/{runtime_paths.RECORDS}/")
    for label, path in (("old layout: the journal under state/", "qa-factory/state/journal.jsonl"),
                        ("new layout: the journal under records/", "qa-factory/records/journal.jsonl"),
                        ("new layout: a nested record", "qa-factory/records/config-backups/config.1.json"),
                        ("a Windows spelling of a record", "qa-factory\\records\\journal.jsonl")):
        check(f"{label} is volatile", RS.is_generated(path))
    check("a records folder that is not the project's own home is an input", not RS.is_generated("src/qa-factory/records/x.py"))
    check("a file merely named like it is an input", not RS.is_generated("qa-factory/records.md"))
    check("with an artifact root outside the repo, records/ is still volatile", RS.is_generated("qa-factory/records/j.jsonl", ()))

    base = temp_dir("qa-volatile-records-")
    try:
        repo = base / "repo"
        for relative, text in (("calc.py", CALC_OK), ("qa-factory/records/journal.jsonl", "{}\n"),
                               ("qa-factory/state/journal.jsonl", "{}\n")):
            (repo / relative).parent.mkdir(parents=True, exist_ok=True)
            (repo / relative).write_text(text, encoding="utf-8")
        git(repo, "init", "-q")
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", "author")

        def mutation(path: str, replacement: str) -> dict:
            return {"path": path, "before_sha256": RS.digest(repo / path), "replacement_utf8": replacement,
                    "instance_id": "test_add", "expected_location": "tests/test_calc.py:5",
                    "expected_reason": "sum must be 4"}

        receipt = RS.prepare(repo, base / "clone-1", {"mutations": [mutation("calc.py", CALC_BROKEN)]})
        check_eq("both journals are named in the receipt as volatile",
                 sorted(receipt["volatile"]), ["qa-factory/records/journal.jsonl", "qa-factory/state/journal.jsonl"])
        check_eq("neither is copied into the clone",
                 [(base / "clone-1" / "qa-factory" / sub / "journal.jsonl").exists() for sub in ("records", "state")],
                 [False, False])
        for sub in ("records", "state"):  # a journal append while the probe runs
            with open(repo / "qa-factory" / sub / "journal.jsonl", "a", encoding="utf-8") as journal:
                journal.write('{"event": "appended during the probe"}\n')
        try:
            RS.verify(receipt, [], None)
            held = True
        except ValueError:
            held = False
        check("a journal append during the probe is not 'main-tree bytes changed'", held)
        (repo / "calc.py").write_text(CALC_OK + "# the author edited it\n", encoding="utf-8")
        try:
            RS.verify(receipt, [], None)
            caught = False
        except ValueError as exc:
            caught = "main-tree bytes changed" in str(exc)
        check("control: a changed product file still is", caught)
        (repo / "calc.py").write_text(CALC_OK, encoding="utf-8")

        for number, path in enumerate(("qa-factory/records/journal.jsonl", "qa-factory/state/journal.jsonl")):
            try:
                RS.prepare(repo, base / f"clone-aimed-{number}", {"mutations": [mutation(path, "{}\n")]})
                said = ""
            except ValueError as exc:
                said = str(exc)
            check_in(f"a mutation aimed at {path} is refused as a generated artefact",
                     "a generated factory artefact is not a mutation target", said)
    finally:
        cleanup(base)


def frames_from_the_table() -> None:
    """B-373 c, R12: `target_result` passes the frame grammar of the `assertion_probes` entry that owns the expected
    file's suffix, read through `assertion_detectors` (the one reader, FR-17). A suffix with no entry - or a table
    that cannot be read - passes NO keywords (never `frames=[]`: that says "a grammar was given" and would turn
    every TRX row of an entry-less suffix into an unread site, L11): the behaviour is what it was before."""
    import assertion_detectors as AD
    check_eq("_frame_grammar: .py has no entry", RS._frame_grammar("tests/test_x.py"), {})
    check_eq("_frame_grammar: no suffix has none", RS._frame_grammar("Makefile"), {})
    check_eq("_frame_grammar: .fs (no entry) gives {} - not frames=[] (L11)", RS._frame_grammar("backend/Tests/X.fs"), {})
    check_eq("_frame_grammar: a directory-ish or empty name gives {}", (RS._frame_grammar(""), RS._frame_grammar("tests/")), ({}, {}))
    java = RS._frame_grammar("src/test/java/com/acme/CalcTest.java")
    check_eq("_frame_grammar: .java gives the three keywords", sorted(java), ["frame_path", "frames", "skip_frames"])
    check_eq("...the Java frames are read by basename, with a `qual` group", (java["frame_path"], "(?P<qual>" in java["frames"][0]),
             ("basename", True))
    check_eq("...the table's own lists, as new lists", (java["frames"], java["skip_frames"]),
             (AD.grammar_of(AD.assertion_detectors()["java"])[0], AD.grammar_of(AD.assertion_detectors()["java"])[1]))
    check_eq("_frame_grammar: the suffix is read case-insensitively", sorted(RS._frame_grammar("X.CS")), ["frame_path", "frames", "skip_frames"])
    root = temp_dir("qa-probe-r12-")
    try:
        clone = root / "clone"
        (clone / "src").mkdir(parents=True)
        (clone / "src" / "sum.test.ts").write_text("// a test\n", encoding="utf-8")
        target = target_of(expected_location="src/sum.test.ts:11", instance_id="calc adds")
        jest = ("Error: expect(received).toBe(expected)\n\n    Expected: 4\n    Received: 0\n\n"
                f"      at Object.<anonymous> ({(clone / 'src' / 'sum.test.ts').as_posix()}:11:20)\n"
                "      at Promise.then.completed (/clone/node_modules/jest-circus/build/utils.js:298:28)\n"
                "      at new Promise (<anonymous>)")
        row = {"test_id": "calc adds::calc adds", "status": "failed", "problems": [
            {"kind": "failure", "message": "expect(received).toBe(expected)", "text": jest}]}
        got = RS.target_result(target, row, "junit-xml", clone, command=["npx", "jest", "--ci"])
        check_eq("R12: a Jest row of a `.ts` target is READ (it was unread before the table)",
                 (got.get("location"), got.get("failure_kind"), got.get("semantic_verdict"), "site_unread" in got),
                 ("src/sum.test.ts:11", "assertion", "intended_failure", False))
        check_in("R12: the answer carries the raw frame it was read from", "sum.test.ts:11:20", got.get("frame", ""))
        check_eq("R12: the failure's own message stays the reason", got.get("reason"), "expect(received).toBe(expected)")
        only_lib = dict(row, problems=[{"kind": "failure", "message": "m", "text":
                                        "Error: m\n      at Object.toBe (/clone/node_modules/expect/build/index.js:1:1)"}])
        got = RS.target_result(target, only_lib, "junit-xml", clone, command=["npx", "jest", "--ci"])
        check_eq("R12: a stack with only library frames is the typed unread answer, never a location",
                 (got.get("site_unread"), got.get("location"), got.get("semantic_verdict")), ("junit-xml/npx", None, None))
        check_in("...with the reader's reason", "no frame of its stack matched the declared frame grammar", got.get("site_unread_reason", ""))
        receipt = {"repo": str(root), "original_hashes": {}, "targets": [target]}
        check_eq("...and verify() calls it incomplete", RS.verify(receipt, [got], [{"instance_id": "calc adds", "status": "passed"}])["status"],
                 "incomplete")
        # the junit row of a PYTEST command is read by pytest's own rule, whatever the suffix says
        py_row = {"test_id": "a::b", "status": "failed", "problems": [{"kind": "failure", "message": "AssertionError: x",
                                                                         "text": "src/sum.test.ts:11: AssertionError"}]}
        got = RS.target_result(target, py_row, "junit-xml", clone, command=["python", "-m", "pytest"])
        check_eq("R12: a pytest command keeps pytest's rule even for a `.ts` target", (got.get("location"), got.get("failure_kind")),
                 ("src/sum.test.ts:11", "assertion"))
        # TRX of a suffix with an entry: the table's grammar; of a suffix without one: the built-in read, as before
        frame = f"{(clone / 'backend' / 'Tests' / 'ChecksTests.cs').as_posix()}:line 42"
        rows = rows_of(root, "cs.trx", trx_failed("Suite.Checks.critical_check", frame))
        row, _ = RS.bind_row(target_of(), contracts_for(target_of(), "Suite.Checks.critical_check"), rows, "trx")
        got = RS.target_result(target_of(), row, "trx", clone)
        check_eq("R12: a `.cs` TRX row is read by the table's grammar: the same site, plus the raw frame",
                 (got.get("location"), got.get("failure_kind"), "ChecksTests.cs:line 42" in got.get("frame", "")),
                 ("backend/Tests/ChecksTests.cs:42", "assertion", True))
        fs = target_of(expected_location="backend/Tests/ChecksTests.fs:42")
        frame_fs = f"{(clone / 'backend' / 'Tests' / 'ChecksTests.fs').as_posix()}:line 42"
        rows = rows_of(root, "fs.trx", trx_failed("Suite.Checks.critical_check", frame_fs))
        row, _ = RS.bind_row(fs, contracts_for(fs, "Suite.Checks.critical_check"), rows, "trx")
        got = RS.target_result(fs, row, "trx", clone)
        check_eq("R12 (L11): a `.fs` TRX row (no entry) keeps the built-in read - never an unread site",
                 (got.get("location"), got.get("failure_kind"), "site_unread" in got, "frame" in got),
                 ("backend/Tests/ChecksTests.fs:42", "assertion", False, False))
        # a table that cannot be read: today's behaviour for every suffix, not a crash and not an unread site
        broken = root / "broken.json"
        broken.write_text("{nope", encoding="utf-8")
        saved = os.environ.get(AD.ENV_FILE)
        os.environ[AD.ENV_FILE] = str(broken)
        try:
            check_eq("R12: an unreadable table gives no keywords", RS._frame_grammar("X.cs"), {})
            rows = rows_of(root, "cs2.trx", trx_failed("Suite.Checks.critical_check", frame))
            row, _ = RS.bind_row(target_of(), contracts_for(target_of(), "Suite.Checks.critical_check"), rows, "trx")
            got = RS.target_result(target_of(), row, "trx", clone)
            check_eq("R12: and a `.cs` TRX row is then read as it was before the table (no `frame`, no unread site)",
                     (got.get("location"), got.get("failure_kind"), "frame" in got, "site_unread" in got),
                     ("backend/Tests/ChecksTests.cs:42", "assertion", False, False))
        finally:
            if saved is None:
                os.environ.pop(AD.ENV_FILE, None)
            else:
                os.environ[AD.ENV_FILE] = saved
    finally:
        cleanup(root)


def main() -> None:
    frames_from_the_table()
    accepted_matrix(report_test_id=True)
    accepted_matrix("pytest")
    trx_report_rows_are_usable_for_red_proof()
    row_binding()
    run_contracts_are_read_from_the_job()
    baseline_must_pass()
    site_unread_is_incomplete()
    no_reporter_no_rows()
    the_door_is_a_command_the_cli_takes()
    trx_end_to_end()
    trx_wrong_assertion_line_is_incomplete()
    trx_without_report_test_id()
    junit_unmatched_report_id_is_the_probes_defect()
    a_baseline_target_with_no_row_is_not_executed()
    a_baseline_that_is_not_a_pass_is_incomplete()
    junit_runner_that_is_not_pytest_is_incomplete()
    non_pytest_test_file_absent_from_the_clone_is_refused()
    non_pytest_nodes_are_never_node_ids()
    request_status_of_proofs()
    two_targets_one_survivor_beside_a_baseline_that_proves_nothing()
    two_differing_mutations_of_one_path_are_refused_before_anything()
    volatile_prefixes_cover_both_layouts()
    finish("test_red_sandbox_reports")


if __name__ == "__main__":
    main()
