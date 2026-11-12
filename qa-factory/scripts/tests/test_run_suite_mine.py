"""run_suite 0.7.8: error_head, --detail under a dispatch, --mine, and the three wirings.

Session 57cf578c on TP1-15045 (0.7.6): 106 hand-written request files for 16 S5
dispatches, an exit-4 run whose one-line cause no role could read, `--detail` unreachable in
both spellings, a single-account stand hit by parallel runs. Every case below is one of those.

The node-id, lease and health modules belong to other packages; they are FAKES here, put into
`sys.modules`, so this file tests the runner's side of the interface and nothing else.
"""
import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import types
from pathlib import Path

from harness import PLUGIN_ROOT, check, check_eq, check_in, check_not_in, finish

sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))
import hooklib  # noqa: E402
import launch_check  # noqa: E402
import run_suite  # noqa: E402
import execution_request as er  # noqa: E402

# Outside the package: a local-directory marketplace copies whatever lies in it.
ROOT = Path(tempfile.mkdtemp(prefix="qa-run-suite-mine-")).resolve()
TASK = "MINE-1"
TASK_ROOT = ROOT / "qa-factory" / "artifacts" / TASK
TASK2 = "MINE-2"
TASK2_ROOT = ROOT / "qa-factory" / "artifacts" / TASK2
PY = sys.executable

# A stand-in for pytest, named `pytest` so the runner treats the command as pytest: it writes
# the junit report the runner asked for, one row per node id, spelled the way pytest spells it.
FAKE_PYTEST = r'''
import sys
from pathlib import Path
args = sys.argv[1:]
report = next((a.split("=", 1)[1] for a in args if a.startswith("--junitxml=")), "")
nodes = [a for a in args if "::" in a]
Path("launches.txt").open("a", encoding="utf-8").write(" ".join(nodes) + "\n")
if any("ghost" in n for n in nodes):
    print("ERROR: not found: " + nodes[0])
    print("(no match in any of [<Module test_a.py>])")
    sys.exit(4)
rows = []
failed = 0
for node in nodes:
    parts = node.replace("\\", "/").split("::")
    classname = ".".join([parts[0][:-3].replace("/", ".")] + parts[1:-1])
    if "red" in parts[-1]:
        failed += 1
        rows.append(f'<testcase classname="{classname}" name="{parts[-1]}"><failure message="AssertionError: boom">trace of {parts[-1]}</failure></testcase>')
    else:
        rows.append(f'<testcase classname="{classname}" name="{parts[-1]}"/>')
if report:
    Path(report).parent.mkdir(parents=True, exist_ok=True)
    Path(report).write_text(f'<testsuite tests="{len(rows)}" failures="{failed}" errors="0" skipped="0">' + "".join(rows) + "</testsuite>", encoding="utf-8")
sys.exit(1 if failed else 0)
'''

PROVENANCE = {"profile_id": "api", "timestamp": "2026-09-22T10:00:00Z", "environment_id": "localhost",
              "expected_source_revision": "source-1", "observed_runtime_identity": "build-1",
              "evidence_refs": ["probe"], "result": "matched",
              "provenance": {"technical_verification": True, "source_linkage": "exact",
                             "deployed_source_revision": "source-1"}}


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=1), encoding="utf-8")


def config(parallel=None) -> dict:
    cfg = {"profiles": [{"profile_id": "api", "selected": True, "roots": {"test": "tests"},
                         "commands": {"one_test": {"argv": [PY, str(ROOT / "fake" / "pytest"), "<test-file>"],
                                                   "cwd": "."}},
                         "reporter": {"kind": "pytest"}, "selectors": {"verified": True}}],
           "execution": {"runtime_probes": {"api": {"argv": [PY, str(ROOT / "probe.py")], "cwd": ".",
                                                    "timeout_s": 20}}}}
    if parallel is not None:
        cfg["run"] = {"parallel": parallel, "stand_wait_s": 7}
    return cfg


def controller(status="running", scope=("TC-001", "TC-002", "TC-003")) -> dict:
    return {"schema_version": "2", "revision": "41", "source_revision": "source-1",
            "dispatches": {"S5-qa-automator-1": {"id": "S5-qa-automator-1", "stage": "S5",
                                                 "role": "qa-automator", "status": status,
                                                 "scope": list(scope), "budget": {"requests": 150}}}}


def setup_project() -> None:
    (ROOT / "fake").mkdir(parents=True)
    (ROOT / "fake" / "pytest").write_text(FAKE_PYTEST, encoding="utf-8")
    (ROOT / "probe.py").write_text("import json\nprint(json.dumps(" + repr(PROVENANCE) + "))\n", encoding="utf-8")
    (ROOT / "tests").mkdir()
    (ROOT / "tests" / "conftest.py").write_text("# fixtures\n", encoding="utf-8")
    (ROOT / "tests" / "test_a.py").write_text(
        "def test_green():\n    pass\n\n\ndef test_red():\n    assert False\n\n\n"
        "# TC-003: the manifest names only this file\ndef test_marked():\n    pass\n\n\n"
        "def test_other():\n    pass\n", encoding="utf-8")
    write_json(ROOT / "qa-factory" / "config.json", config())
    (ROOT / "qa-factory" / "state").mkdir(parents=True, exist_ok=True)
    write_json(TASK_ROOT / "pipeline.json", {"stages": {"S5": {"status": "running"}}})
    write_json(TASK_ROOT / "state" / "controller.json", controller())
    write_json(TASK_ROOT / "work" / "automation-manifest.json", {"tests": [
        {"case": "TC-001", "file": "tests/test_a.py", "selector": "test_green",
         "case_version_links": [{"case_id": "TC-001", "version": "cv_1"}]},
        {"case": "TC-002", "file": "tests/test_a.py", "selector": "test_red | test_green[p1|p2]"},
        {"case": "TC-003", "file": "tests/test_a.py"},
        {"case": "TC-009", "file": "tests/test_a.py", "selector": "test_other"}]})


def second_window() -> None:
    """A second story whose one window is three tests of one file, under a dispatch that
    resumed an earlier one (`parent_retry`) — the shape of TP1-15045's window 1."""
    (ROOT / "tests" / "conftest.py").write_text("def shared_client():\n    return 1\n", encoding="utf-8")
    (ROOT / "tests" / "test_b.py").write_text(
        "def test_one(shared_client):\n    assert shared_client\n\n\n"
        "def test_two():\n    assert True\n\n\n"
        "def test_three():\n    assert True\n", encoding="utf-8")
    write_json(TASK2_ROOT / "pipeline.json", {"stages": {"S5": {"status": "running"}}})
    write_json(TASK2_ROOT / "state" / "controller.json", {
        "schema_version": "2", "revision": "7", "source_revision": "source-1", "dispatches": {
            "S5-qa-automator-8": {"id": "S5-qa-automator-8", "stage": "S5", "role": "qa-automator",
                                  "status": "superseded", "scope": ["TC-101", "TC-102"]},
            "S5-qa-automator-9": {"id": "S5-qa-automator-9", "stage": "S5", "role": "qa-automator",
                                  "status": "running", "parent_retry": "S5-qa-automator-8",
                                  "scope": ["TC-101", "TC-102"], "budget": {"requests": 150}}}})
    write_json(TASK2_ROOT / "work" / "automation-manifest.json", {"tests": [
        {"case": "TC-101", "file": "tests/test_b.py", "selector": "test_one | test_two"},
        {"case": "TC-102", "file": "tests/test_b.py", "selector": "test_three"}]})


TASK3 = "MINE-3"
TASK3_ROOT = ROOT / "qa-factory" / "artifacts" / TASK3
TASK4 = "MINE-4"
TASK4_ROOT = ROOT / "qa-factory" / "artifacts" / TASK4
JOIN = {"option": "--filter", "separator": "|"}


def clone_of(name: str, files=("tests/test_c.py", "tests/conftest.py")) -> Path:
    """A copy of the author's files, the way red_sandbox.py prepares one."""
    clone = ROOT / name
    for rel in files:
        (clone / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / rel, clone / rel)
    return clone.resolve()


def red_probe_story() -> None:
    """A story that so far has only red probes on record: the precedent of its next probe used
    to be the latest earlier probe, with the absolute directory of a clone already thrown away."""
    (ROOT / "tests" / "test_c.py").write_text("def test_alpha():\n    pass\n", encoding="utf-8")
    write_json(TASK3_ROOT / "pipeline.json", {"stages": {"S5": {"status": "running"}}})
    write_json(TASK3_ROOT / "state" / "controller.json", {
        "schema_version": "2", "revision": "3", "source_revision": "source-1", "dispatches": {
            "S5-qa-automator-20": {"id": "S5-qa-automator-20", "stage": "S5", "role": "qa-automator",
                                   "status": "running", "scope": ["TC-201"],
                                   "budget": {"requests": 150}}}})
    write_json(TASK3_ROOT / "work" / "automation-manifest.json", {"tests": [
        {"case": "TC-201", "file": "tests/test_c.py", "selector": "test_alpha"}]})


def launched_in(directory: Path) -> list:
    """What the fake pytest recorded in the directory it was launched in."""
    path = directory / "launches.txt"
    return path.read_text(encoding="utf-8").split() if path.exists() else []


def requests_of(task_root: Path) -> list:
    paths = sorted((task_root / "work" / "requests").glob("mine-*.json"), key=lambda p: p.stat().st_mtime)
    return [json.loads(p.read_text(encoding="utf-8")) for p in paths]


def xunit_config(join="absent", cwd="backend") -> dict:
    """A profile whose runner is not pytest: its selection is ONE option, and the report path
    rides inside a token. `join` is the profile's `selectors.join` rule."""
    selectors = {"verified": True}
    if join != "absent":
        selectors["join"] = join
    return {"profiles": [{"profile_id": "xunit", "selected": True, "roots": {"test": "backend"},
                          "commands": {"one_test": {
                              "argv": [PY, str(ROOT / "fake" / "runner.py"), "test", "--logger",
                                       "trx;LogFileName={report_path}"], "cwd": cwd}},
                          "reporter": {"kind": "trx"}, "selectors": selectors}],
            "execution": {"runtime_probes": {"xunit": {"argv": [PY, str(ROOT / "probe.py")], "cwd": ".",
                                                      "timeout_s": 20}}}}


def xunit_story() -> None:
    write_json(TASK4_ROOT / "pipeline.json", {"stages": {"S5": {"status": "running"}}})
    write_json(TASK4_ROOT / "state" / "controller.json", {
        "schema_version": "2", "revision": "4", "source_revision": "source-1", "dispatches": {
            "S5-qa-automator-30": {"id": "S5-qa-automator-30", "stage": "S5", "role": "qa-automator",
                                   "status": "running", "scope": ["TC-301", "TC-302"],
                                   "budget": {"requests": 150}}}})
    entries = []
    for case, name in (("TC-301", "One"), ("TC-302", "Two")):
        entries.append({"case": case, "file": "backend/Tests/XTests.cs", "selector": f"XTests.{name}",
                        "instance_id": f"XTests.{name}", "report_test_id": f"XTests.{name}",
                        "report_id_source": "catalog",
                        "selector_args": ["--filter", f"FullyQualifiedName=XTests.{name}"]})
    write_json(TASK4_ROOT / "work" / "automation-manifest.json", {"tests": entries})
    for root, text in ((ROOT, "author bytes"), (ROOT / "clone-x", "clone bytes")):
        (root / "backend" / "Tests").mkdir(parents=True, exist_ok=True)
        (root / "backend" / "Tests" / "XTests.cs").write_text(text + "\n", encoding="utf-8")


def build_xunit(cfg: dict, **kwargs) -> dict:
    provenance = dict(PROVENANCE, profile_id="xunit")
    request, _notes, _reuse, _verified = er.build_mine_request(
        ROOT, ["TC-301", "TC-302"], cfg=cfg, task=TASK4, probe=lambda spec: dict(provenance),
        again=True, **kwargs)
    return request


def refusal_of(cfg: dict, **kwargs) -> str:
    try:
        build_xunit(cfg, **kwargs)
    except er.MineRefusal as exc:
        return str(exc)
    return ""


def call(*argv) -> tuple:
    """run_suite.main() in this process: (exit code, stdout, stderr)."""
    hooklib._PROJECT_ROOT_CACHE = None
    out, err = io.StringIO(), io.StringIO()
    old_argv, old_cwd = sys.argv, os.getcwd()
    sys.argv = ["run_suite.py", *[str(a) for a in argv]]
    os.chdir(ROOT)
    code = 0
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                run_suite.main()
            except SystemExit as exc:
                code = exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 2)
    finally:
        sys.argv = old_argv
        os.chdir(old_cwd)
    return code, out.getvalue(), err.getvalue()


def last_json(text: str) -> dict:
    lines = [line for line in text.strip().splitlines() if line.startswith("{")]
    return json.loads(lines[-1]) if lines else {}


def launches() -> list:
    path = ROOT / "launches.txt"
    return path.read_text(encoding="utf-8").splitlines() if path.exists() else []


_REAL_NODE_IDS = []


def real_node_ids():
    """The shipped `node_ids` under another name: `sys.modules` holds a fake of it in this file, and the keys of
    HF2-10 need its REAL `match` (the one reader of a collect's list) and its REAL `CollectError`."""
    if not _REAL_NODE_IDS:
        import importlib.util
        spec = importlib.util.spec_from_file_location("node_ids_real", PLUGIN_ROOT / "scripts" / "node_ids.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _REAL_NODE_IDS.append(module)
    return _REAL_NODE_IDS[0]


def fake_modules(*, collected=None, missing=None, resolved=None, busy=False, signal=None, log=None):
    """Install the three foreign modules as fakes coded to the brief's interfaces.

    The collect models the CONTRACT of HF2-10: `collected=None` is a collect that CANNOT answer (it raises the real
    `CollectError`, as an unparsed or timed-out collect does) - it no longer means "answered, nothing collected";
    `collected=[]` is a successful empty collect; a list is the collected ids; an exception instance is raised as it
    is. `match` is the real one over the list the collect gave, unless `missing`/`resolved` pin its answer;
    `check_request` (the hand-written request's own check, B-E14) keeps answering from `missing`/`resolved`."""
    log = log if log is not None else []
    node_ids = types.ModuleType("node_ids")
    real = real_node_ids()

    def check_request(argv, cwd, asked, timeout_s=180, form=None, **_more):
        log.append(("check_request", list(argv), list(asked)))
        return {"resolved": dict(resolved or {a: a for a in asked if not missing}),
                "missing": list(missing or []), "notes": []}

    def collect(argv, cwd, timeout_s=180, files=(), form=None):
        log.append(("collect", list(argv) + [str(f) for f in files]))   # the files are logged as they were: in the command
        if collected is None:
            raise real.CollectError("pytest collected 3 test(s) but none could be parsed from its output", "banner")
        if isinstance(collected, BaseException):
            raise collected
        return list(collected)

    def match(asked, collected_ids, **_more):
        log.append(("match", list(asked), list(collected_ids)))
        if missing or resolved:
            return {"resolved": dict(resolved or {a: a for a in asked if not missing}),
                    "missing": list(missing or []), "notes": []}
        return real.match(asked, collected_ids)
    node_ids.check_request, node_ids.collect, node_ids.match = check_request, collect, match
    node_ids.match_partial, node_ids.broken_sentence = real.match_partial, real.broken_sentence  # RH1-3: the real readers
    node_ids.same_file = real.same_file                                                           # the owner of a broken path (F4)
    node_ids.missing_sentence = lambda rows: "; ".join(str(r.get("asked")) + " is not collected" for r in rows)

    stand_lease = types.ModuleType("stand_lease")

    class StandBusy(Exception):
        def __init__(self, holder):
            super().__init__("the stand is held by " + str(holder.get("job_id")))
            self.holder = holder

    @contextlib.contextmanager
    def hold(project_root, job_id, environment="", wait_s=1800, poll_s=5):
        log.append(("hold", job_id, environment, wait_s))
        if busy:
            raise StandBusy({"job_id": "other-job", "pid": 4242})
        try:
            yield {"waited_s": 3, "queued_behind": "other-job"}
        finally:
            log.append(("released", job_id))
    stand_lease.StandBusy, stand_lease.hold = StandBusy, hold

    stand_health = types.ModuleType("stand_health")

    def observe(project_root, task, summary):
        log.append(("observe", task, summary.get("purpose"), summary.get("environment")))
        return signal
    stand_health.observe = observe
    node_ids.is_pytest, node_ids.run_captured = real.is_pytest, real.run_captured   # execution_request binds both at import (EP1-1, EP1-35)
    sys.modules.update({"node_ids": node_ids, "stand_lease": stand_lease, "stand_health": stand_health})
    return log


def absent_modules() -> None:
    for name in ("node_ids", "stand_lease", "stand_health"):
        sys.modules[name] = None  # `import name` now raises ImportError


PT = "PREC-1"
PT_ROOT = ROOT / "qa-factory" / "artifacts" / PT
PROFILE_ARGV = [PY, str(ROOT / "fake" / "pytest")]  # `config()` argv, its `<test-file>` placeholder removed
# What a summary file holds. A job record carries no totals: they live in the summary it names.
SUMMARIES = {
    "no_totals": {"exit_code": 4, "execution_status": "broken_run",
                  "log_tail": ["pytest: error: unrecognized arguments: --reruns"]},
    # exit 0 and no totals: run_suite's "it ran and produced nothing to report"
    "no_totals_exit_0": {"exit_code": 0, "execution_status": "not_executed"},
    # the reporter-less profile (reporter other than pytest, no report written): green and red
    # both carry `parse_gap`; a red run there is `broken_run` by exit code alone
    "reporterless_green": {"exit_code": 0, "execution_status": "not_executed",
                           "no_junitxml": "nothing to parse", "parse_gap": "no report the factory can read"},
    "reporterless_red": {"exit_code": 1, "execution_status": "broken_run",
                         "no_junitxml": "nothing to parse", "parse_gap": "no report the factory can read"},
    "no_totals_no_status": {"exit_code": 4},
    "red": {"exit_code": 1, "execution_status": "failed",
            "totals": {"tests": 2, "failures": 1, "errors": 0, "skipped": 0, "passed": 1}},
    "green": {"exit_code": 0, "execution_status": "passed",
              "totals": {"tests": 2, "failures": 0, "errors": 0, "skipped": 0, "passed": 2}},
    # a collection error counts one test and one error in junit: a run WITH totals
    "collection_error": {"exit_code": 2, "execution_status": "broken_run",
                         "totals": {"tests": 1, "failures": 0, "errors": 1, "skipped": 0}},
    "zero_collected": {"exit_code": 0, "execution_status": "not_executed",
                       "totals": {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}},
}


def precedent_battery() -> None:
    """R-A3 / K6: a typed run that never ran a test is not copied as the story's command.

    What the code guards against: a typed run that never got as far as running a test (exit 4,
    no junit, no totals; or a launch that failed) being copied as the story's command. It must
    never refuse a run that worked before, so every doubt stays a precedent: `not_executed` (run_suite
    gives it to a summary with no totals only when the process exited 0), a summary with a
    `parse_gap`, an unreadable summary, an unknown status. Synthetic job records and summary
    files in a temp project; each job's command carries `from_job`, the name of the job it was
    copied from, so the source of the built command is readable (an argv equal to the profile's
    cannot tell the two apart)."""
    write_json(PT_ROOT / "pipeline.json", {"stages": {"S5": {"status": "running"}}})
    write_json(PT_ROOT / "state" / "controller.json", controller())
    write_json(PT_ROOT / "work" / "automation-manifest.json", {"tests": [
        {"case": "TC-001", "file": "tests/test_a.py", "selector": "test_green"}]})
    helper = ROOT / "tests" / "helper_marker.py"
    helper.write_text("MARK = 1\n", encoding="utf-8")
    jobs_dir, summaries = PT_ROOT / "state" / "execution-jobs", ROOT / "prec-summaries"
    store = er.JobStore(jobs_dir)

    def build(cfg=None, **kw) -> tuple:
        try:
            request, notes, _reuse, _verified = er.build_mine_request(
                ROOT, ["TC-001"], task=PT, cfg=cfg if cfg is not None else config(), again=True,
                probe=lambda spec: dict(PROVENANCE), **kw)
            return request, notes, ""
        except er.MineRefusal as exc:
            return None, [], str(exc)

    def reset() -> None:
        for path in jobs_dir.glob("*.json"):
            path.unlink()

    base, _notes, _refusal = build()  # no job yet: built from the profile alone

    def make(name, n, *, status="completed", state="passed", summary="green", argv=None,
             purpose="initial", helper_file=False, absolute=False) -> str:
        """Write job `job-<name>`, the n-th of the story. `summary` is a SUMMARIES key or one of
        absent / garbage / list / nokey; `state` None leaves `execution_status` out."""
        request = json.loads(json.dumps(base))
        request["purpose"] = purpose
        request["idempotency_key"] = "prec-" + name
        request["command"] = {**request["command"], "argv": list(argv or PROFILE_ARGV),
                              "from_job": "job-" + name}
        request["runtime_probe"] = dict(request.get("runtime_probe") or {}, timeout_s=100 + n)
        if helper_file:
            request["fingerprint_files"] = list(request["fingerprint_files"]) + [
                {"path": str(helper), "sha256": "0" * 64, "kind": "helper_files"}]
        job = {"job_id": "job-" + name, "idempotency_key": request["idempotency_key"],
               "request_digest": "d" * 64, "status": status, "request": request,
               "created_at": f"2026-09-30T04:00:{n:02d}+00:00"}
        if state:
            job["execution_status"] = state
        path = summaries / f"job-{name}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        if summary in SUMMARIES:
            write_json(path, SUMMARIES[summary])
        elif summary == "garbage":
            path.write_text("{not json", encoding="utf-8")
        elif summary == "list":
            path.write_text("[]", encoding="utf-8")
        if summary != "nokey":
            job["summary"] = str(path) if absolute else "prec-summaries/" + path.name
            if summary == "absent":
                job["summary"] = "prec-summaries/never-written.json"
        store.write(job)
        return "job-" + name

    def source(request) -> str:
        return ((request or {}).get("command") or {}).get("from_job", "<profile>")

    def argv_of(request):
        return ((request or {}).get("command") or {}).get("argv")

    def scenario(*jobs, cfg=None, **kw) -> tuple:
        reset()
        for spec in jobs:
            make(**spec)
        return build(cfg, **kw)

    no_command = config()
    del no_command["profiles"][0]["commands"]

    # --- edge 1: a run that never ran a test is walked past --------------------------------
    request, notes, refusal = scenario(
        dict(name="good", n=1, state="failed", summary="red"),
        dict(name="broken", n=2, state="broken_run", summary="no_totals", helper_file=True))
    check_eq("edge 1: the newest typed run never ran a test - the command is the earlier run's",
             (source(request), refusal), ("job-good", ""))
    check_in("edge 1: the note names the skipped run and its state in words",
             "job-broken (broken_run)", notes)
    check_in("edge 1: and says why - it never ran a test", "never ran a test", notes)
    check_in("edge 1: and names the run the command came from",
             "the command is that of typed run job-good, the latest that ran tests", notes)
    check_eq("position: the stand probe is still the NEWEST run's (the skipped one's)",
             ((request or {}).get("runtime_probe") or {}).get("timeout_s"), 102)
    check("position: the fingerprint file list is still the NEWEST run's",
          str(helper) in [f["path"] for f in (request or {}).get("fingerprint_files") or []])

    request, notes, _ = scenario(
        dict(name="old", n=1, state="passed", summary="green"),
        dict(name="mid", n=2, state="failed", summary="red"),
        dict(name="launch", n=3, status="failed_to_launch", state="broken_run", summary="no_totals",
             absolute=True),
        dict(name="broken", n=4, state="broken_run", summary="no_totals"))
    check_eq("edge 1: it walks back over several - to the LATEST run that ran tests, not the first",
             source(request), "job-mid")
    for jid, word in (("job-launch", "failed_to_launch"), ("job-broken", "broken_run")):
        check_in(f"edge 6: the note names {jid} with its state", f"{jid} ({word})", notes)
    check_eq("edge 6: a run that did produce a result is not named as skipped",
             any("job-mid (" in n or "job-old (" in n for n in notes), False)

    # R-A3 amendment (K6): `not_executed` with exit 0 and no totals is "it ran and produced
    # nothing to report" (run_suite.execution_status) - a precedent, never a never-ran run.
    request, notes, refusal = scenario(
        dict(name="old", n=1, state="passed", summary="green"),
        dict(name="quiet", n=2, state="not_executed", summary="no_totals_exit_0"))
    check_eq("K6: a job with no totals, exit 0 and `not_executed` IS a precedent",
             (source(request), refusal), ("job-quiet", ""))
    check_eq("K6: and it is not named as skipped", any("job-quiet" in n and "never ran" in n for n in notes), False)
    request, notes, _ = scenario(
        dict(name="mid", n=1, state="failed", summary="red"),
        dict(name="quiet", n=2, state="not_executed", summary="no_totals_exit_0"),
        dict(name="launch", n=3, status="failed_to_launch", state="broken_run", summary="no_totals"),
        dict(name="broken", n=4, state="broken_run", summary="no_totals"))
    check_eq("K6: walking back over never-ran jobs stops at `quiet`, the newest that may have run",
             source(request), "job-quiet")
    check_eq("K6: the walked-past jobs are named, `quiet` is not",
             (any("job-launch (failed_to_launch)" in n for n in notes),
              any("job-broken (broken_run)" in n for n in notes),
              any("job-quiet (" in n for n in notes)), (True, True, False))

    # The critic's replay: a reporter-less profile with no `one_test` in it. HEAD copied the
    # typed run's command; the first version of this piece refused with a false "never ran a test".
    for label, name, state, summary in (("green", "rl-green", "not_executed", "reporterless_green"),
                                        ("red", "rl-red", "broken_run", "reporterless_red")):
        request, notes, refusal = scenario(dict(name=name, n=1, state=state, summary=summary),
                                           cfg=no_command)
        check_eq(f"replay: a reporter-less {label} run, no one_test in the profile - the precedent is copied",
                 (source(request), refusal), ("job-" + name, ""))
        check_eq(f"replay: {label} - nothing is said to be skipped",
                 any("never ran a test" in n for n in notes), False)
    # a parse_gap is doubt even in a state the list names (a red run there is `broken_run` by exit code)
    request, notes, refusal = scenario(
        dict(name="older", n=1, state="passed", summary="green"),
        dict(name="gap", n=2, state="broken_run", summary="reporterless_red"))
    check_eq("edge 2: a summary carrying a parse_gap stays a precedent even as broken_run",
             (source(request), refusal), ("job-gap", ""))
    # a broken_run job WITH a totals dict is result-bearing: a precedent (edge 3 holds it too,
    # here in the no-one_test profile, where a wrong skip would be a refusal)
    request, notes, refusal = scenario(dict(name="ce", n=1, state="broken_run", summary="collection_error"),
                                       cfg=no_command)
    check_eq("edge 3: a broken_run job with totals, no one_test in the profile - still copied, no refusal",
             (source(request), refusal), ("job-ce", ""))
    request, notes, _ = scenario(dict(name="launch", n=1, status="failed_to_launch", state="broken_run",
                                      summary="no_totals", absolute=True))
    check_eq("edge 1: a summary named by an ABSOLUTE path is read (failed_to_launch)",
             (source(request), any("job-launch (failed_to_launch)" in n for n in notes)),
             ("<profile>", True))

    # --- edge 2: any doubt leaves the job a precedent, as before ------------------------------
    for label, spec in (
            ("its summary file is absent", dict(state="broken_run", summary="absent")),
            ("its summary is not JSON", dict(state="broken_run", summary="garbage")),
            ("its summary is not a record", dict(state="broken_run", summary="list")),
            ("the job names no summary", dict(state="broken_run", summary="nokey")),
            ("its status is unknown", dict(state="weird_state", summary="no_totals")),
            ("its status is absent", dict(state=None, summary="no_totals_no_status")),
            ("it is still in flight", dict(status="running", state=None, summary="nokey"))):
        request, notes, refusal = scenario(
            dict(name="older", n=1, state="passed", summary="green"), dict(name="doubt", n=2, **spec))
        check_eq(f"edge 2: {label} - the job is still the precedent",
                 (source(request), refusal), ("job-doubt", ""))
        check_eq(f"edge 2: {label} - nothing is said to be skipped",
                 any("never ran a test" in n for n in notes), False)
        check_in(f"edge 2: {label} - today's note stands",
                 "command, fingerprint file list and runtime probe are those of this story's "
                 "last typed run on profile api", notes)

    # --- edge 3: tests ran (even red, even a collection error) -> a normal precedent -----------
    for label, spec in (("red", dict(state="failed", summary="red")),
                        ("a collection error (tests=1 errors=1)", dict(state="broken_run", summary="collection_error")),
                        ("zero collected, with a totals record", dict(state="not_executed", summary="zero_collected"))):
        request, notes, _ = scenario(dict(name="older", n=1, state="passed", summary="green"),
                                     dict(name="ran", n=2, **spec))
        check_eq(f"edge 3: a run that finished WITH totals ({label}) is a precedent, never skipped",
                 source(request), "job-ran")
        check_eq(f"edge 3: {label} - not named as skipped", any("never ran a test" in n for n in notes), False)

    # --- edge 4: every precedent skipped ---------------------------------------------------------
    request, notes, refusal = scenario(
        dict(name="b1", n=1, state="broken_run", summary="no_totals"),
        dict(name="b2", n=2, status="failed_to_launch", state="broken_run", summary="no_totals"))
    check_eq("edge 4: every run skipped, the profile has a command - the profile's is used",
             (source(request), argv_of(request), refusal), ("<profile>", PROFILE_ARGV, ""))
    check_in("edge 4: and the note says no run of the story ran a test",
             "no typed run of this story on profile api ran a test", notes)
    request, notes, refusal = scenario(
        dict(name="b1", n=1, state="broken_run", summary="no_totals"),
        dict(name="b2", n=2, status="failed_to_launch", state="broken_run", summary="no_totals"),
        cfg=no_command)
    check_eq("edge 4: every run skipped and the profile has no one_test - a refusal", request, None)
    check_in("edge 4: it says the earlier typed runs never ran a test, with their ids",
             "the earlier typed runs of this story never ran a test (job-b2, job-b1)", refusal)
    check_eq("edge 4: it never says there was no earlier typed run", "no earlier typed run" in refusal, False)
    check_in("edge 4: it says whose gap it is and what to do",
             "gap of the onboarding, not of your test: report it in your digest", refusal)

    # --- edge 5: the profile's command wins over a result-bearing precedent that differs -------
    request, notes, refusal = scenario(
        dict(name="old", n=1, state="failed", summary="red", argv=[PY, "old-runner"]))
    check_eq("edge 5: the precedent's argv differs from the profile's - the PROFILE wins",
             (source(request), argv_of(request), refusal), ("<profile>", PROFILE_ARGV, ""))
    check_in("edge 5: the note says the precedent's command was not reused and why, in plain words",
             "the command of typed run job-old was not reused because it differs from the profile's "
             "command in qa-factory/config.json, and the profile's is the command of record (", notes)
    check_in("edge 5: it shows both argvs", "(the run's argv: " + PY + " old-runner; profile api's "
             "commands.one_test.argv: " + " ".join(PROFILE_ARGV) + ")", notes)
    check_in("edge 5: the door - a wrong profile command is an onboarding gap said in the digest, "
             "and this run is written with --template request",
             "If the profile's command is the wrong one, a role does not change that file: say so in "
             "your digest as an onboarding gap, and write this one run with --template request.", notes)
    check_in("edge 5: the fingerprint file list and runtime probe sentence stays",
             "The fingerprint file list and runtime probe are still those of this story's last typed "
             "run on the profile", notes)
    check_eq("edge 5: the note does not claim a fixed profile took effect",
             any("takes effect" in n or "fixed" in n for n in notes), False)
    # the argv shown in a note is cut at 160 characters, and a cut one says so
    for length, cut in ((160, False), (161, True)):
        long_arg = "x" * length
        request, notes, _ = scenario(dict(name="long", n=1, state="failed", summary="red",
                                          argv=[long_arg]))
        shown = "(the run's argv: " + "x" * 160 + ("..." if cut else "") + "; profile api's"
        check_in(f"argv cut: a run argv of {length} characters is {'cut with a mark' if cut else 'shown whole, no mark'}",
                 shown, notes)
        check_eq(f"argv cut: at {length} no more than 160 characters of it are shown",
                 any("x" * 161 in n for n in notes), False)
    long_profile = config()
    long_profile["profiles"][0]["commands"]["one_test"]["argv"] = ["pytest", "y" * 155, "<test-file>"]
    request, notes, refusal = scenario(dict(name="same", n=1, state="failed", summary="red"),
                                       cfg=long_profile)
    check_in("argv cut: the profile's argv of 162 characters is cut with a mark too",
             "commands.one_test.argv: " + ("pytest " + "y" * 155)[:160] + "...)", notes + [refusal])
    check_eq("edge 5: the old 'those of the last run' note is not printed for a command not copied",
             any(n.startswith("command, fingerprint") for n in notes), False)
    request, notes, _ = scenario(dict(name="same", n=1, state="failed", summary="red"))
    check_eq("edge 5: an equal command - the precedent is used exactly as today",
             source(request), "job-same")
    check_eq("edge 5: with today's note and no other",
             [n for n in notes if "typed run" in n],
             ["command, fingerprint file list and runtime probe are those of this story's last typed "
              "run on profile api"])
    fixed = config()
    fixed["profiles"][0]["commands"]["one_test"]["argv"] = ["poetry", "run", "pytest", "<test-file>"]
    request, notes, _ = scenario(dict(name="bare", n=1, state="failed", summary="red"), cfg=fixed)
    check_eq("edge 5: a profile fixed AFTER a run that ran tests takes effect (placeholder dropped)",
             (source(request), argv_of(request)), ("<profile>", ["poetry", "run", "pytest"]))
    request, notes, _ = scenario(
        dict(name="good", n=1, state="failed", summary="red", argv=[PY, "old-runner"]),
        dict(name="broken", n=2, state="broken_run", summary="no_totals"))
    check_eq("edge 5 with 1: the run walked back to differs too - the profile wins, both are said",
             (source(request), any("job-broken (broken_run)" in n for n in notes),
              any("job-good was not reused" in n for n in notes)), ("<profile>", True, True))
    request, notes, refusal = scenario(dict(name="old", n=1, state="failed", summary="red"),
                                       cfg=no_command)
    check_eq("edge 5: the profile has no command to compare with - the precedent is used as today",
             (source(request), refusal), ("job-old", ""))
    check_in("edge 5: and the note says the two were not compared",
             "the two commands were not compared", notes)

    # --- edge 7: no precedent at all is today's behaviour --------------------------------------
    request, notes, refusal = scenario()
    check_eq("edge 7: no typed run - the command is the profile's",
             (source(request), argv_of(request), refusal), ("<profile>", PROFILE_ARGV, ""))
    check_eq("edge 7: and no word about typed runs is added",
             [n for n in notes if "typed run" in n or "not reused" in n], [])
    request, notes, refusal = scenario(cfg=no_command)
    check_in("edge 7: no typed run and no profile command - today's refusal, word for word",
             "and this story has no earlier typed run to copy the command from. That is a gap of "
             "the onboarding, not of your test: report it in your digest, and write this one run "
             "with --template request. To record the command once and for all: "
             "`/qa-factory:qa-onboarding` (execution batch).", refusal)

    # --- invariant: a red probe never runs in the author's tree --------------------------------
    request, notes, refusal = scenario(
        dict(name="rp", n=1, purpose="red_probe", state="broken_run", summary="no_totals"),
        purpose="red_probe")
    check_in("a red probe whose only precedent never ran: the command is the profile's, so the sandbox "
             "is asked for", "--cwd <the exact sandbox directory>", refusal)
    # L3 (ours' invariant on upstream's `command_job`): a red-probe job is never a precedent, so a
    # red probe with no directory of its own is refused whatever red-probe jobs are on record.
    request, notes, refusal = scenario(
        dict(name="rp", n=1, purpose="red_probe", state="failed", summary="red"), purpose="red_probe")
    check_eq("a red probe whose only precedent is a red probe that ran tests is refused, not copied",
             (source(request), request is None), ("<profile>", True))
    check_in("with the clone option named", "--sandbox-root", refusal)
    request, notes, refusal = scenario(
        dict(name="rp", n=1, purpose="red_probe", state="failed", summary="red", argv=[PY, "old-runner"]),
        purpose="red_probe")
    check_in("a red probe whose precedent's argv differs from the profile's is not run in the "
             "author's tree either", "--cwd <the exact sandbox directory>", refusal)
    sandbox_dir = str(ROOT)
    request, notes, refusal = scenario(
        dict(name="ord", n=1, state="failed", summary="red"),
        dict(name="rp", n=2, purpose="red_probe", state="failed", summary="red", argv=[PY, "clone-runner"]),
        purpose="red_probe", cwd=sandbox_dir)
    check_eq("a red probe is never the precedent for the command: the newest ORDINARY run's is copied, "
             "though a red probe is newer", (source(request), refusal), ("job-ord", ""))
    request, notes, refusal = scenario(
        dict(name="rp", n=1, purpose="red_probe", state="failed", summary="red", argv=[PY, "clone-runner"]),
        purpose="red_probe", cwd=sandbox_dir)
    check_eq("with only red probes on record the command is the profile's (no ordinary job to copy)",
             (source(request), refusal), ("<profile>", ""))
    reset()


# ---------------------------------------------------------------------------------------------------------------------
# t-300 N2: the person's word reaches the role's run (K-N2.4, K-N2.6, K-TE2)
# ---------------------------------------------------------------------------------------------------------------------
N2_AT = "2026-10-03T08:00:00+00:00"


def n2_probe_script() -> None:
    """A probe whose answers are a QUEUE (`n2-queue.json`): the n-th call prints the n-th record, the last one sticks. A
    `--mine` asks it twice (HF2-10; it was three times) - to build the request (the reading the launch stands on, S2a),
    and after the run (S2b) - so a queue says what the stand showed at each moment. `n2-count.txt` counts the calls."""
    (ROOT / "probe_n2.py").write_text(
        "import json\nfrom pathlib import Path\nhere = Path(__file__).parent\n"
        "queue = json.loads((here / 'n2-queue.json').read_text(encoding='utf-8'))\n"
        "counter = here / 'n2-count.txt'\nn = int(counter.read_text()) if counter.exists() else 0\n"
        "counter.write_text(str(n + 1))\nprint(json.dumps(queue[min(n, len(queue) - 1)]))\n", encoding="utf-8")


def n2_queue(*records) -> None:
    write_json(ROOT / "n2-queue.json", list(records))
    counter = ROOT / "n2-count.txt"
    if counter.exists():
        counter.unlink()


def n2_config(profile: str = "api") -> dict:
    cfg = config()
    api = cfg["profiles"][0]
    # Its own root: two profiles over one `tests/` is the shape `_profile_for` refuses since EP1-10 (the first used
    # to win in silence), and this battery is about the person's word, not about which profile runs the row.
    cfg["profiles"] = [api, {**api, "profile_id": "e2e-ui", "roots": {"test": "tests-ui"}}]
    cfg["execution"]["runtime_probes"] = {name: {"argv": [PY, str(ROOT / "probe_n2.py")], "cwd": ".", "timeout_s": 20}
                                          for name in ("api", "e2e-ui")}
    return cfg


def n2_task(name: str, cases=("TC-001", "TC-009")) -> Path:
    root = ROOT / "qa-factory" / "artifacts" / name
    write_json(root / "pipeline.json", {"stages": {"S5": {"status": "running"}}})
    write_json(root / "state" / "controller.json", controller(scope=cases))
    write_json(root / "work" / "automation-manifest.json", {"tests": [
        {"case": "TC-001", "file": "tests/test_a.py", "selector": "test_green"},
        {"case": "TC-009", "file": "tests/test_a.py", "selector": "test_other"},
        {"case": "TC-010", "file": "tests/test_a.py", "selector": "test_marked"},
        {"case": "TC-011", "file": "tests/test_a.py", "selector": "test_red"}]})
    return root


def n2_word(task: str, identity: str, **more) -> dict:
    """A person's word with NO docker: the identity is the word's own time (`person-confirmed:<at>`)."""
    record = {"profile_id": "api", "timestamp": "2026-10-03T09:00:00+00:00", "environment_id": "localhost",
              "expected_source_revision": "source-1", "observed_runtime_identity": identity, "evidence_refs": ["probe/pc"],
              "result": "person_confirmed", "provenance": {"technical_verification": False, "identity_kind": "person_confirmed"},
              "person_confirmation": {"words": "yes, it is deployed", "at": N2_AT, "task": task, "kind": "deployed",
                                      "revision": "source-1"}}
    record.update(more)
    return record


def n2_block(root: Path) -> dict:
    return json.loads(sorted((root / "work" / "run-blocks").glob("*.json"), key=lambda p: p.stat().st_mtime)[-1]
                      .read_text(encoding="utf-8"))


def n2_battery() -> None:
    """K-N2.4 (S2) and K-N2.6 (S6) on the real `--mine` flow with a scripted probe."""
    n2_probe_script()
    write_json(ROOT / "qa-factory" / "config.json", n2_config())
    here = "person-confirmed:" + N2_AT
    elsewhere = "person-confirmed:2026-10-03T09:30:00+00:00"
    matched = dict(PROVENANCE, timestamp="2026-10-03T09:00:00+00:00")

    # --- K-N2.4: the compare of the stand before the launch (S2a) and after the run (S2b) --------------------------------
    root = n2_task("N2-a")
    n2_queue(n2_word("N2-a", here), n2_word("N2-a", elsewhere))  # HF2-10: the build's reading, then the post-run one
    code, out, err = call("--mine", "TC-001", "--task", "N2-a")
    summary = last_json(out)
    check_eq("B-K6: runtime probes per one `--mine`: was 3 (build, before launch, after run) -> now 2 (build, after run)",
             (ROOT / "n2-count.txt").read_text(encoding="utf-8"), "2")
    check_eq("K-N2.4: the word `person-confirmed:A` before, `person-confirmed:B` after: the run is inconclusive",
             (summary.get("execution_status"), summary.get("runtime_change_error")),
             ("inconclusive", "runtime identity/source changed during execution"))
    check_eq("K-N2.4: and the run block says `person_confirmed` (never `matched`), nothing verified",
             (n2_block(root)["runtime_provenance"]["result"], n2_block(root)["equivalence_verified"]), ("person_confirmed", False))
    root = n2_task("N2-b")
    n2_queue(n2_word("N2-b", here))
    code, out, err = call("--mine", "TC-001", "--task", "N2-b")
    summary = last_json(out)
    check_eq("K-N2.4: the same word before and after: the run completes (passed), and says the stand was not read",
             (code, summary.get("execution_status"), summary.get("runtime_identity_unread")), (0, "passed", True))
    check_eq("K-N2.4: the run block carries the word and no equivalence",
             (n2_block(root)["runtime_provenance"]["result"], n2_block(root)["equivalence_verified"]), ("person_confirmed", False))
    # HF2-10, by design: `--mine` reads the stand ONCE before the launch - the reading it took while it built the request
    # is the one the launch stands on (B-K5) - so a redeploy BETWEEN the build and the launch is no longer seen by a second
    # probe; it is seen by the probe after the run, and such a run is never green (B-E12). The S2a refusal of a stand that
    # moved since the request was built stays for a request that was NOT built here (B-E14): a request file.
    root = n2_task("N2-c")
    n2_queue(n2_word("N2-c", here), n2_word("N2-c", elsewhere))
    code, out, err = call("--mine", "TC-001", "--task", "N2-c")
    summary = last_json(out)
    check_eq("B-E12: the stand moved after the build: the run is inconclusive (post-run probe), never passed",
             (summary.get("execution_status"), summary.get("runtime_change_error")),
             ("inconclusive", "runtime identity/source changed during execution"))
    root = n2_task("N2-c2")
    n2_queue(n2_word("N2-c2", here))
    built, _notes, _reuse, _verified = er.build_mine_request(ROOT, ["TC-001"], cfg=n2_config(), task="N2-c2",
                                                             probe=run_suite.probe_runtime)
    request_file = er.write_mine_request(ROOT, built)
    n2_queue(n2_word("N2-c2", elsewhere))
    before = len(launches())
    code, out, err = call("--request", request_file)
    refusal = json.loads(err.strip().splitlines()[-1])
    check_eq("K-N2.4: the identity moved between the request and the launch: invalid_request, exit 2, nothing launched",
             (code, refusal["status"], len(launches())), (2, "invalid_request", before))
    check_in("K-N2.4 (S2a): and it NAMES the field that moved", "observed_runtime_identity moved since the request was built", refusal["error"])
    root = n2_task("N2-d")
    n2_queue(matched)
    code, out, err = call("--mine", "TC-001", "--task", "N2-d")
    summary = last_json(out)
    check_eq("K-N2.4 CONTROL: a `matched` stand, equal before and after: completed, and NO flag",
             (code, summary.get("execution_status"), "runtime_identity_unread" in summary), (0, "passed", False))
    check_eq("K-N2.4 CONTROL: and its run block IS equivalence-eligible only with a seed (here none): `matched`, flag absent",
             n2_block(root)["runtime_provenance"]["result"], "matched")

    # --- K-N2.6: the stand's refusal, said as that (S6) --------------------------------------------------------------------
    unknown = dict(PROVENANCE, result="unknown", evidence_refs=[], observed_runtime_identity="image:sha256:" + "b" * 64,
                   provenance={"technical_verification": False}, asks_person="how",
                   error="which build the stand runs could not be read", remedy="tell me how to read it")
    mismatched = dict(PROVENANCE, observed_runtime_identity="image:sha256:" + "b" * 64,
                      result="mismatched", provenance={**PROVENANCE["provenance"], "deployed_source_revision": "d" * 40})
    for label, shape, needle in (("an `unknown`", unknown, "which build the stand runs could not be read. tell me how to read it"),
                                 ("a proven mismatch", mismatched, "the stand does not run this story's build")):
        n2_task("N2-e")
        for stale in (ROOT / "qa-factory" / "artifacts" / "N2-e" / "state" / "execution-jobs").glob("*.json"):
            stale.unlink()
        n2_queue(unknown if shape is unknown else mismatched)
        code, out, err = call("--mine", "TC-001", "--task", "N2-e")
        said = last_json(out)
        check_eq(f"K-N2.6 first run: {label}: `mine_refused`, exit 2 - the stand's refusal, not `mine_unavailable`",
                 (code, said.get("status"), "hint" in said), (2, "mine_refused", False))
        check_in(f"K-N2.6 first run: {label}: the sentence says what the probe said", needle, said.get("error", ""))
        check_not_in(f"K-N2.6 first run: {label}: and never the `--template request` door", "--template request", out)
    check_in("K-N2.6 X9: a proven mismatch names both builds and the door (`test deployed`)",
             "runtime probe returned mismatched: the stand runs " + "d" * 12 + " and this story is source-1", said.get("error", ""))
    check_not_in("K-N2.6 X9: and never `cannot be observed` (that is false for a stand that answered)", "cannot be observed", said.get("error", ""))
    # the PRECEDENT branch: a story that already ran on the stand, and now the stand shows something else
    root = n2_task("N2-f")
    n2_queue(matched)
    code, out, err = call("--mine", "TC-001", "--task", "N2-f")
    check_eq("K-N2.6 setup: the first run on a `matched` stand passes", (code, last_json(out).get("execution_status")), (0, "passed"))
    n2_queue(mismatched)
    code, out, err = call("--mine", "TC-009", "--task", "N2-f")
    said = last_json(out)
    check_eq("K-N2.6 precedent: a stand that now proves another build: `mine_refused` with the build_refused sentence",
             (code, said.get("status"), "the stand does not run this story's build" in said.get("error", ""),
              "cannot be observed" in said.get("error", "")), (2, "mine_refused", True, False))
    n2_queue(unknown)
    code, out, err = call("--mine", "TC-009", "--task", "N2-f")
    said = last_json(out)
    check_eq("K-N2.6 precedent: an `unknown` keeps `cannot be observed`, with the probe's own words quoted",
             (code, said.get("status"), "cannot be observed right now" in said.get("error", ""),
              "which build the stand runs could not be read. tell me how to read it" in said.get("error", "")),
             (2, "mine_refused", True, True))
    n2_queue(n2_word("N2-f", here))
    code, out, err = call("--mine", "TC-009", "--task", "N2-f")
    check_eq("K-N2.6 control: the person's word on that story is a stand the run can start on (the S6 word table has no refusal for it)",
             (code, last_json(out).get("execution_status")), (0, "passed"))
    # F6: with no run budget readable (policy None) there is no word table to say it with: the refusal's own sentence stands
    policy, _note = er.load_run_budget()
    refused = er.ProvenanceRefused(mismatched)
    check_eq("F6: policy None - the refusal's own sentence (it already names the build and the door)",
             er._stand_refusal(None, refused), str(refused))
    check_eq("F6: policy None - an `unknown` too", er._stand_refusal(None, er.ProvenanceRefused(unknown)),
             str(er.ProvenanceRefused(unknown)))
    check_eq("F6 control: with the budget the same mismatch is the build_refused word",
             er._stand_refusal(policy, refused).startswith("the stand does not run this story's build, so no run was started"), True)
    check_eq("F6 control: and the same `unknown` is `not_observed`",
             er._stand_refusal(policy, er.ProvenanceRefused(unknown)).startswith("the stand's version cannot be observed right now"), True)


def te2_the_persons_word_reaches_the_runs_mine() -> None:
    """K-TE2 (t-300 N2, THE RELEASE BLOCKER): a person's `test deployed` word recorded at the stand question reaches
    `run_suite --mine`. The record is produced IN-PROCESS by the REAL ladder (`runtime_probe.main` over the fake docker of
    test_runtime_probe_onboarding K14: label D, a `test_deployed` confirmation with revision D and story_revision HEAD); a stub
    `runtime_probe.py` only freezes and prints it, so S1, S4, S6, S7 and the S2 compares run for real. TWO `--mine` calls
    (F2): the first run, and the precedent path. Controls: a later record that is `matched` never inherits the build the
    word chose (F2), and the same story with the word withdrawn (`unconfirm`) is `mismatched` and refused with the stand's
    sentence (F1)."""
    import test_runtime_probe_onboarding as T
    import hooklib
    import stand_identity as SI
    saved_env = os.environ.get("CLAUDE_PROJECT_DIR")
    world = T.World(git=True)
    try:
        d, head = world.commits                       # D: the build the stand runs; HEAD: this story's commit
        world.confirm(kind="test_deployed", revision=d, story_revision=head, image=T.IDENT, words="test what is deployed")
        code, word, _said = world.probe(T.Stand(labels={T.LABEL: d}), expected=head)
        check_eq("K-TE2 (the real ladder): label D + the `test_deployed` word: person_confirmed, tested_build D",
                 (code, word["result"], word["tested_build"], word["person_confirmation"]["story_revision"]), (0, "person_confirmed", d, head))
        SI.add_confirmation(world.root, world.task, task="QA-1", environment_id="localhost", profile_id="e2e-ui", kind="withdrawn",
                            words="I was wrong")
        code, withdrawn, _said = world.probe(T.Stand(labels={T.LABEL: d}), expected=head)
        check_eq("K-TE2 (the real ladder) F1: the word WITHDRAWN (`unconfirm`): plain `mismatched`, no `voided`",
                 (withdrawn["result"], "voided" in withdrawn), ("mismatched", False))
        code, reading, _said = world.probe(T.Stand(labels={T.LABEL: head}), expected=head)
        check_eq("K-TE2 (the real ladder): and a stand that runs this story's commit reads `matched`", reading["result"], "matched")
    finally:
        world.close()
        if saved_env is None:
            os.environ.pop("CLAUDE_PROJECT_DIR", None)
        else:
            os.environ["CLAUDE_PROJECT_DIR"] = saved_env
        os.environ["CLAUDE_PROJECT_DIR"] = str(ROOT)
        hooklib._PROJECT_ROOT_CACHE = None
    write_json(ROOT / "qa-factory" / "config.json", n2_config())

    def frozen(record) -> None:
        n2_queue(record)

    def source_of(root: Path, case: str) -> str:
        built = sorted((root / "work" / "requests").glob(f"mine-*{case}*.json"), key=lambda p: p.stat().st_mtime)[-1]
        return json.loads(built.read_text(encoding="utf-8"))["fingerprint_components"]["source_sha"]
    root = n2_task("QA-1", cases=("TC-001", "TC-009", "TC-010", "TC-011"))
    frozen(word)
    code, out, err = call("--mine", "TC-001", "--task", "QA-1", "--profile", "e2e-ui")
    summary = last_json(out)
    check_eq("K-TE2: `--mine` on the person's `test deployed` word exits 0 and launches", (code, summary.get("execution_status")), (0, "passed"))
    block = n2_block(root)
    check_eq("K-TE2: the run block says `person_confirmed` and the build under test is D",
             (block["runtime_provenance"]["result"], block["runtime_provenance"]["tested_build"]), ("person_confirmed", d))
    check_eq("K-TE2: the word is never `matched`: equivalence is not verified", block["equivalence_verified"], False)
    check_eq("K-TE2 X11: the fingerprint's source_sha is D, not this story's commit", source_of(root, "TC-001"), d)
    check_eq("K-TE2: the pre-run and post-run compares passed (no runtime_change_error)", "runtime_change_error" in summary, False)
    # the precedent path (F2)
    code, out, err = call("--mine", "TC-009", "--task", "QA-1", "--profile", "e2e-ui")
    check_eq("K-TE2 F2: the SECOND `--mine` (the precedent path) takes the word too", (code, last_json(out).get("execution_status")), (0, "passed"))
    check_eq("K-TE2 F2: and a fresh `tested_build` D overrides the inherited source_sha (still D)", source_of(root, "TC-009"), d)
    # a fresh record WITHOUT a tested_build never inherits D
    frozen(reading)
    code, out, err = call("--mine", "TC-010", "--task", "QA-1", "--profile", "e2e-ui")
    check_eq("K-TE2 F2: a later `matched` reading of this story's commit runs", (code, last_json(out).get("execution_status")), (0, "passed"))
    check_eq("K-TE2 F2: and its source_sha is THIS STORY's commit - a fresh record without a tested_build never inherits D",
             source_of(root, "TC-010"), head)
    # F3 (t-395): the OTHER order - a `matched` precedent on HEAD, THEN a fresh `test_deployed` D: the fresh tested_build overrides
    # the inherited source_sha (the first `--mine` of this story ran on D, the one just above on HEAD; a mutant that takes the
    # inherited value first gives HEAD here)
    frozen(word)
    code, out, err = call("--mine", "TC-011", "--task", "QA-1", "--profile", "e2e-ui")
    check_eq("K-TE2 F3: the person's word after a `matched` precedent runs (the red test fails, the run still happens)",
             (last_json(out).get("execution_status"), "mine_refused" in out), ("failed", False))
    check_eq("K-TE2 F3: a fresh `test_deployed` D after a `matched` precedent on HEAD: source_sha is D (the fresh tested_build overrides)",
             source_of(root, "TC-011"), d)
    # NEGATIVE CONTROL (F1): the word withdrawn: mismatched, the stand's sentence, nothing launched
    n2_task("QA-2")
    frozen(withdrawn)
    before = len(launches())
    code, out, err = call("--mine", "TC-001", "--task", "QA-2", "--profile", "e2e-ui")
    said = last_json(out)
    check_eq("K-TE2 NEGATIVE CONTROL (F1): the word withdrawn gives `mismatched`: `mine_refused`, nothing launched",
             (code, said.get("status"), len(launches())), (2, "mine_refused", before))
    check_in("K-TE2 F1: with the build_refused sentence", "the stand does not run this story's build", said.get("error", ""))
    check_in("K-TE2 F1: naming the build the stand runs and the person's door",
             "the stand runs " + d[:12] + " and this story is " + head[:12], said.get("error", ""))
    check_not_in("K-TE2 F1: and never `cannot be observed`", "cannot be observed", said.get("error", ""))


# --- B-407 B-run: runner rows (launch-causes.json) read by exit_reading, nothing_ran, verify_node_ids ----

def with_runner_data(content, fn):
    """Run `fn` with launch_check's data file pointed at `content` (bytes or dict), then restore."""
    path = ROOT / "runner-rows-under-test.json"
    path.write_bytes(content if isinstance(content, bytes) else json.dumps(content).encode("utf-8"))
    saved = launch_check.CAUSES_PATH
    launch_check.CAUSES_PATH = path
    try:
        return fn()
    finally:
        launch_check.CAUSES_PATH = saved


def shipped_runner_data() -> dict:
    return json.loads(launch_check.CAUSES_PATH.read_text(encoding="utf-8"))


def with_forms(rows, fn):
    """`fn` under the shipped data with `collect_forms` replaced by `rows`."""
    return with_runner_data(dict(shipped_runner_data(), collect_forms=rows), fn)


def c8_battery() -> None:
    """C8 (t-2181 PC-9b, rewritten t-2277 W1): `run_suite.py --request` no longer refuses at entry a request aimed at a stand that runs the OLD
    version of a side of the story (it goes on, the run is a sample); it still refuses at ENTRY - `run_refused`, exit 2, nothing begun
    (no job store) - the record that names the story's own stand also as the reference. A request on the story's own stand, or on a story
    with no reference, goes on to the ordinary validation (negative controls)."""
    import subprocess
    pipeline = TASK_ROOT / "pipeline.json"
    saved = pipeline.read_text(encoding="utf-8") if pipeline.exists() else None

    def call(stand):
        path = ROOT / "c8-request.json"
        path.write_text(json.dumps({"task": TASK, "purpose": "initial", "idempotency_key": "c8-" + stand,
                                    "runtime_provenance": {"environment_id": stand}}), encoding="utf-8")
        env = dict(os.environ, CLAUDE_PROJECT_DIR=str(ROOT), QA_FACTORY_SKIP_DASHBOARD_REFRESH="1")
        return subprocess.run([PY, str(PLUGIN_ROOT / "scripts" / "run_suite.py"), "--request", str(path)], cwd=ROOT, env=env,
                              capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=90)
    try:
        sides = {"ui": {"reality": "real", "deliverable": True, "reference": "old", "source": "person"}}
        pipeline.write_text(json.dumps({"ticket": TASK, "environment": "dev", "sides": sides}), encoding="utf-8")
        jobs = TASK_ROOT / "state" / "execution-jobs"
        before = sorted(str(p) for p in jobs.rglob("*")) if jobs.exists() else []
        got = call("old")
        check("C8 (t-2277 W1): a request aimed at the reference stand is NOT run_refused at entry - it goes on to the ordinary validation "
              "(invalid_request: this request is a bare stub)", "run_refused" not in got.stdout and "invalid_request" in got.stderr,
              got.stdout[-300:] + got.stderr[-300:])
        pipeline.write_text(json.dumps({"ticket": TASK, "environment": "old", "sides": sides}), encoding="utf-8")
        before = sorted(str(p) for p in jobs.rglob("*")) if jobs.exists() else []
        got = call("old")
        check("C8: the record that names the story's own stand ALSO as the reference is still run_refused at entry (exit 2), the record is the door",
              got.returncode == 2 and "run_refused" in got.stdout and "both as its own stand" in got.stdout, got.stdout[-300:] + got.stderr[-300:])
        check_eq("C8: ... and nothing was begun (the job store is as it was)", sorted(str(p) for p in jobs.rglob("*")) if jobs.exists() else [], before)
        pipeline.write_text(json.dumps({"ticket": TASK, "environment": "dev", "sides": sides}), encoding="utf-8")
        own = call("dev")
        check("C8 negative control: the story's own stand goes on to the ordinary validation (invalid_request, not run_refused)",
              "run_refused" not in own.stdout and "invalid_request" in own.stderr, own.stdout[-200:] + own.stderr[-200:])
        pipeline.write_text(json.dumps({"ticket": TASK, "environment": "dev"}), encoding="utf-8")
        none = call("old")
        check("C8: a story with no reference reads the rule nowhere (as before)", "run_refused" not in none.stdout, none.stdout[-200:])
    finally:
        if saved is None:
            pipeline.unlink(missing_ok=True)
        else:
            pipeline.write_text(saved, encoding="utf-8")


def request_for(argv, tokens=("tests/test_a.py::test_green",)) -> dict:
    """The part of a typed request `verify_node_ids` reads: one selected instance and its tokens."""
    return {"task": TASK, "command": {"argv": list(argv), "cwd": ".", "selector_args": {"i1": list(tokens or ())}},
            "selected_instance_ids": ["i1"] if tokens is not None else []}


def b_run_battery() -> None:
    pytest_row = shipped_runner_data()["collect_forms"][0]
    check_eq("B-run: the shipped pytest row states its exits and its node-id checker",
             (pytest_row.get("not_executed_exits"), pytest_row.get("node_ids")), ([2, 3, 4, 5], "pytest"))

    # K-R1: the shipped data reads as the rule did before the data existed
    for argv in (["pytest"], ["poetry", "run", "pytest", "-x"], [PY, "-m", "pytest"]):
        for code, expected in ((0, False), (1, False), (2, True), (3, True), (4, True), (5, True)):
            check_eq(f"K-R1 {argv[-1]} exit {code}: exit_means_not_executed",
                     run_suite.exit_reading(argv, code), {"exit_means_not_executed": expected})
        for code in (124, 127):  # run_suite's own codes: no runner fact, never False, and the note says so
            got = run_suite.exit_reading(argv, code)
            check_eq(f"F3 {argv[-1]} exit {code}: no fact, never False", got["exit_means_not_executed"], None)
            check_in(f"F3 {argv[-1]} exit {code}: the note names the code and that it is not a runner fact",
                     f"run_suite's own code {code}", got["exit_note"])
            check_in(f"F3 {argv[-1]} exit {code}: ... not a runner fact", "not a runner fact", got["exit_note"])
    import importlib.util  # the real stand_health: sys.modules holds a fake of it in this file
    spec = importlib.util.spec_from_file_location("stand_health_real", PLUGIN_ROOT / "scripts" / "stand_health.py")
    stand_health = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(stand_health)
    for code, totals in ((124, {"tests": 3}), (124, None), (127, {"tests": 3})):
        legacy = {"exit_code": code, **({"totals": totals} if totals else {})}
        stated = dict(legacy, **run_suite.exit_reading(["pytest"], code))
        check_eq(f"F3 verdicts do not move: nothing_ran for exit {code} totals {totals} is the legacy rule's",
                 run_suite.nothing_ran(stated), run_suite.nothing_ran(legacy))
        check_eq(f"F3 ... and stand-health's count agrees (exit {code} totals {totals})",
                 stand_health._record("T", dict(stated, label="initial-x"))["counts"],
                 stand_health._record("T", dict(legacy, label="initial-x"))["counts"])
    for code, totals, expected in ((4, None, True), (2, {"tests": 3}, True), (0, {"tests": 0}, True),
                                   (1, {"tests": 2}, False), (124, None, False), (1, None, True)):
        summary = {"exit_code": code, **run_suite.exit_reading(["pytest"], code)}
        if totals is not None:
            summary["totals"] = totals
        check_eq(f"K-R1 pytest exit {code} totals {totals}: nothing_ran as before the rows", run_suite.nothing_ran(summary), expected)

    # K-R2: the data drives it. A pytest row that lists only 4: exit 2 with totals executed
    only_four = dict(pytest_row, not_executed_exits=[4])
    summary = {"exit_code": 2, "totals": {"tests": 3}}
    summary.update(with_forms([only_four], lambda: run_suite.exit_reading(["pytest"], 2)))
    check_eq("K-R2 monkeypatched row [4]: pytest exit 2 is False", summary["exit_means_not_executed"], False)
    check("K-R2 and the run with totals counts as executed", not run_suite.nothing_ran(summary))
    check_eq("K-R2 exit 4 on that row is still not executed",
             with_forms([only_four], lambda: run_suite.exit_reading(["pytest"], 4)), {"exit_means_not_executed": True})
    check_eq("K-R2 an empty list is a fact: nothing is 'not executed' for that runner",
             with_forms([dict(pytest_row, not_executed_exits=[])],
                        lambda: run_suite.exit_reading(["pytest"], 4)), {"exit_means_not_executed": False})

    # None is "no fact": the legacy rule, never False (the mutation: None read as False)
    for label, field in (("absent", {}), ("None", {"exit_means_not_executed": None})):
        for code, totals, expected in ((2, {"tests": 3}, True), (5, {"tests": 3}, True),
                                       (1, {"tests": 3}, False), (124, {"tests": 3}, False)):
            check_eq(f"B2 field {label}, exit {code}, totals {totals}: nothing_ran",
                     run_suite.nothing_ran({"exit_code": code, "totals": totals, **field}), expected)
    check("B2 a field that is not a bool (a string) is no fact either: the legacy rule",
          run_suite.nothing_ran({"exit_code": 2, "totals": {"tests": 3}, "exit_means_not_executed": "yes"}))

    # E-B-run-1/3: no row, no fact, unreadable data, a recogniser that cannot load: None + a note
    for label, argv in (("a Maven wrapper", ["mvn", "test"]), ("dotnet test", ["dotnet", "test"]),
                        ("a shell script", ["./run-tests.sh"]), ("an empty argv", [])):
        got = run_suite.exit_reading(argv, 2)
        check_eq(f"E-B-run-1 {label}: no fact", got["exit_means_not_executed"], None)
        check_in(f"E-B-run-1 {label}: the note says no row recognises it", "no runner row recognises", got["exit_note"])
        check_in(f"E-B-run-1 {label}: and that the legacy rule reads the exit", "legacy rule", got["exit_note"])
    got = with_runner_data(b"{not json", lambda: run_suite.exit_reading(["pytest"], 2))
    check_eq("E-B-run-3 unreadable data: no fact, the legacy rule applies", got["exit_means_not_executed"], None)
    check_in("E-B-run-3 and the note carries the problem", "not valid JSON", got["exit_note"])
    check("E-B-run-3 a verdict does not change silently: pytest exit 4 stays nothing_ran",
          run_suite.nothing_ran({"exit_code": 4, **got}))
    saved_shapes = launch_check._SHAPES

    def gone(_tokens):
        raise launch_check._ShapeUnavailable("ImportError: gone")
    launch_check._SHAPES = {"pytest": gone}
    try:
        got = run_suite.exit_reading(["pytest"], 4)
    finally:
        launch_check._SHAPES = saved_shapes
    check_eq("K-R3 through run_suite: a recogniser that cannot load is no fact", got["exit_means_not_executed"], None)
    check_in("K-R3 and the note says so", "recogniser", got["exit_note"])
    got = with_forms([{k: v for k, v in pytest_row.items() if k != "not_executed_exits"}],
                     lambda: run_suite.exit_reading(["pytest"], 4))
    check_eq("a row that states no exits is no fact (the legacy rule), named in the note",
             (got["exit_means_not_executed"], "states no `not_executed_exits`" in got["exit_note"]), (None, True))

    # node ids (B4, K-R4): the pytest path is gated by is_pytest_command alone
    cfg = {}
    got = run_suite.verify_node_ids(request_for(["dotnet", "test"], ("--filter", "X.One")), cfg)
    check_in("K-R4 a non-pytest launch with selector tokens: the note says the ids were not verified",
             "node ids were not verified", " ".join(got["notes"]))
    check_in("K-R4 naming the runners that have a checker", "(pytest)", got["notes"][0])
    check_in("K-R4 and the program that ran the ids as written", "`dotnet` ran the ids as written", got["notes"][0])
    check_eq("K-R4 nothing is resolved", got["resolved"], {})
    check_eq("B4 a whole-suite run (no selected instance) asks for no id and gets no note",
             run_suite.verify_node_ids(request_for(["dotnet", "test"], None), cfg), None)
    check_eq("B4 ... nor does a selected instance with no selector tokens",
             run_suite.verify_node_ids(request_for(["dotnet", "test"], ()), cfg), None)
    check_eq("B4 a pytest launch with file-only selectors has nothing to verify and says nothing",
             run_suite.verify_node_ids(request_for(["pytest"], ("tests/test_a.py",)), cfg), None)
    got = run_suite.verify_node_ids(request_for(["dotnet", "test"], ("--filter", "X")),
                                    {"execution": {"verify_node_ids": False}})
    check_in("B4 the person's off switch is named, whatever the runner", "execution.verify_node_ids", got["notes"][0])
    got = run_suite.verify_node_ids(request_for(["pytest"]), {"execution": {"verify_node_ids": False}})
    check_in("B4 ... for pytest too (a note, no launch refused)", "execution.verify_node_ids", got["notes"][0])
    got = with_runner_data(b"{nope", lambda: run_suite.verify_node_ids(request_for(["dotnet", "test"], ("--filter", "X")), cfg))
    check_in("E-B-run-3 an unreadable table: still a note for a non-pytest launch, naming the problem",
             "the runner table could not be read", got["notes"][0])
    mocha = {"tool": "mocha", "append": ["--dry-run"], "ok_exits": [0], "node_ids": "mocha-list"}
    launch_check._SHAPES = {"pytest": saved_shapes["pytest"], "mocha": lambda tokens: "mocha" in tokens}
    try:
        got = with_forms([pytest_row, mocha], lambda: run_suite.verify_node_ids(request_for(["npx", "mocha"], ("--grep", "x")), cfg))
    finally:
        launch_check._SHAPES = saved_shapes
    check_in("B4 a row naming a checker this version cannot run for the command: the note names the checker",
             "`mocha-list`", got["notes"][0])

    # E-B-run-5: an unreadable table never switches the pytest id check off
    log = fake_modules(missing=[{"asked": "tests/test_a.py::test_gone", "nearest": []}])
    refused = []
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            with_runner_data(b"{nope", lambda: run_suite.verify_node_ids(
                request_for(["pytest"], ("tests/test_a.py::test_gone",)), cfg))
    except SystemExit as exc:
        refused.append(exc.code)
    check_eq("E-B-run-5 with the runner table unreadable, a pytest id that is not collected still exits 2", refused, [2])
    check("E-B-run-5 and the collect was asked", any(e[0] == "check_request" for e in log))
    fake_modules()
    got = with_runner_data(b"{nope", lambda: run_suite.verify_node_ids(request_for(["pytest"], ("tests/test_a.py::test_green",)), cfg))
    check_eq("E-B-run-5 an unreadable table: the pytest ids are checked as ever (nothing to correct here), and the note says "
             "the collect stayed all-or-nothing (m1, E3-12)",
             ([("the runner table could not be read" in n) for n in got["notes"]], got["resolved"]), ([True], {}))
    absent_modules()
    got = run_suite.verify_node_ids(request_for(["pytest"]), cfg)
    check_in("B4 an absent node_ids module is a note, not silence", "node_ids module could not be imported", got["notes"][0])

    # K-R4 in the run record: a launch that is not pytest, run for real, carries the note and the exit_note
    fake_modules()
    (ROOT / "fake" / "runner.py").write_text(FAKE_PYTEST, encoding="utf-8")
    cfg_runner = config(parallel=True)
    cfg_runner["profiles"][0]["commands"]["one_test"]["argv"] = [PY, str(ROOT / "fake" / "runner.py"), "<test-file>"]
    write_json(ROOT / "qa-factory" / "config.json", cfg_runner)
    write_json(TASK_ROOT / "work" / "automation-manifest.json", {"tests": [  # a runner's own selector, no pytest id
        {"case": "TC-001", "file": "tests/test_a.py", "selector": "test_green",
         "instance_id": "tests/test_a.py::test_green", "report_test_id": "tests.test_a::test_green",
         "report_id_source": "catalog", "selector_args": ["--only", "tests/test_a.py::test_green"]}]})
    try:
        code, out, err = call("--mine", "TC-001", "--again", "--task", TASK, "--dispatch", "S5-qa-automator-1")
        summary = last_json(out)
        check_eq("K-R4 live: the run of a non-pytest command happened", code, 0)
        check_in("K-R4 live: the run record carries the not-verified note",
                 "node ids were not verified", " ".join(summary.get("node_id_notes") or []))
        check_in("K-R4 live: and it is printed", "NODE IDS (note): node ids were not verified", err)
        check_eq("K-R4 live: no fact for this runner, in the record", summary.get("exit_means_not_executed"), None)
        check_in("K-R4 live: with the exit note", "no runner row recognises", summary.get("exit_note", ""))
    finally:
        write_json(ROOT / "qa-factory" / "config.json", config())


# --- t-042: an area-qualified ask finds its manifest row (FB-19) ---------------------------------------------------
# TP2-2406 S5-5 (19.10.2026): the dispatch handed out `feedback-api/TC-003`, manifest revision 9 held the row
# under that spelling, and `--mine feedback-api/TC-003` answered "cannot tell which execution profile" because the
# row was never found (the old test compared the ask with the BARE links). The row below is the live one, as data.

TASK5 = "MINE-5"
TASK5_ROOT = ROOT / "qa-factory" / "artifacts" / TASK5
LIVE_ID = ("BrownEvents.Tests.AttendeeDashboardIntegrationTests."
           "SubmitFeedback_ReturnsClearPreEndError_AndDoesNotPersistFeedback")
LIVE_FILE = "backend/BrownEvents.Tests/AttendeeDashboardIntegrationTests.cs"
LIVE_PIN = "cv_f128c110b97c91eb7962"
LIVE_ROW = {"instance_id": LIVE_ID, "case": "feedback-api/TC-003", "covers": ["feedback-api/TC-003"],
            "file": LIVE_FILE, "selector": LIVE_ID,
            "selector_args": ["--filter", "FullyQualifiedName=" + LIVE_ID], "report_test_id": LIVE_ID,
            "status": "red", "case_version_links": [{"case_id": "TC-003", "version": LIVE_PIN}]}
LIVE_SCOPE = ["TC-001", "TC-002", "TC-004", "feedback-api/TC-003"]
PROFILES_OF_2406 = ("backend-xunit", "frontend-jest", "e2e-playwright")


def live_row(case: str = "feedback-api/TC-003", name: str = "", **changes) -> dict:
    """The 2406 row, re-spelled for another area (and another test name) or edited."""
    row = json.loads(json.dumps(LIVE_ROW))
    ident = LIVE_ID + name
    row.update(instance_id=ident, selector=ident, report_test_id=ident, case=case, covers=[case],
               selector_args=["--filter", "FullyQualifiedName=" + ident])
    row.update(changes)
    return row


def three_profile_config() -> dict:
    """The profiles of the 2406 project: three, so a row that is not found cannot be rescued by the only profile."""
    base = xunit_config()["profiles"][0]
    profiles = []
    for pid, root in zip(PROFILES_OF_2406, ("backend", "frontend", "e2e")):
        profiles.append(dict(json.loads(json.dumps(base)), profile_id=pid, roots={"test": root}))
    probe = {"argv": [PY, str(ROOT / "probe.py")], "cwd": ".", "timeout_s": 20}
    return {"profiles": profiles, "execution": {"runtime_probes": {pid: dict(probe) for pid in PROFILES_OF_2406}}}


def write_case_store(store: dict | None) -> None:
    """The story's case store, `work/test-cases/<area>/<case>.md` (what `stage-scope` indexes): {area: [case ids]};
    `{}`/None leaves the story with no cases. Whatever an earlier check left there goes first."""
    shutil.rmtree(TASK5_ROOT / "work" / "test-cases", ignore_errors=True)
    for area, ids in (store or {}).items():
        for cid in ids:
            path = TASK5_ROOT / "work" / "test-cases" / area / f"{cid}.md"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"---\nid: {cid}\ntask: {TASK5}\n---\n# {cid} of {area}\n", encoding="utf-8")


def qualified_story(rows: list, scope=LIVE_SCOPE, store: dict | None = None) -> None:
    write_case_store(store)
    write_json(TASK5_ROOT / "pipeline.json", {"stages": {"S5": {"status": "running"}}})
    write_json(TASK5_ROOT / "state" / "controller.json", {
        "schema_version": "2", "revision": "9", "source_revision": "source-1", "dispatches": {
            "S5-qa-automator-5": {"id": "S5-qa-automator-5", "stage": "S5", "role": "qa-automator",
                                  "status": "running", "scope": list(scope), "budget": {"requests": 150}}}})
    write_json(TASK5_ROOT / "work" / "automation-manifest.json", {"tests": rows})
    target = ROOT / LIVE_FILE
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("// the test file of the 2406 row\n", encoding="utf-8")


def mine_q(rows: list, cases: list, scope=LIVE_SCOPE, store: dict | None = None, **kwargs) -> tuple:
    """(request, notes) of `--mine` on the 2406 shape, or (None, the refusal's text). `store` is the case store."""
    qualified_story(rows, scope, store)
    provenance = dict(PROVENANCE, profile_id="backend-xunit")
    cfg = kwargs.pop("cfg", None) or three_profile_config()
    try:
        request, notes, _reuse, _verified = er.build_mine_request(
            ROOT, cases, cfg=cfg, task=TASK5, probe=lambda spec: dict(provenance),
            again=True, **kwargs)
    except er.MineRefusal as exc:
        return None, str(exc)
    return request, notes


def qualified_case_battery() -> None:
    name = "t-042 (FB-19)"
    ask = "feedback-api/TC-003"
    # (a) the live shape: the qualified ask builds the request of the row
    request, notes = mine_q([live_row()], [ask])
    check(f"{name} (a): a qualified ask that has a row builds a request, not a refusal [{notes}]", request is not None)
    check_not_in(f"{name} (h): the 'which execution profile' refusal is gone for a qualified ask with a row",
                 "cannot tell which execution profile", "" if request is not None else str(notes))
    request = request or {"selected_instance_ids": [], "command": {}, "instance_contracts": {}, "built_by": {}}
    check_eq(f"{name} (a): one instance, the row's own", request["selected_instance_ids"], [LIVE_ID])
    check_eq(f"{name} (a): its selector_args are the manifest row's, untouched",
             request["command"].get("selector_args"), {LIVE_ID: LIVE_ROW["selector_args"]})
    check_eq(f"{name} (e): the qualified id travels into built_by.cases", request["built_by"].get("cases"), [ask])
    check_eq(f"{name} (e): the pin of the matched row is in the contract, unchanged",
             request["instance_contracts"].get(LIVE_ID, {}).get("case_version_links"),
             [{"case_id": "TC-003", "version": LIVE_PIN}])
    check_eq(f"{name} (h): the profile comes from the row's file, not from a question about profiles",
             request.get("profile_id"), "backend-xunit")

    # (b) two areas hold TC-003: the qualified ask selects its own row only; the bare ask is refused naming both
    other = live_row("session-feedback/TC-003", "_InSession")
    rows2 = [live_row(), other]
    wide = LIVE_SCOPE + ["TC-003", "session-feedback/TC-003"]
    request, notes = mine_q(rows2, [ask], scope=wide)
    check_eq(f"{name} (b): a qualified ask selects only the row of its own area",
             (request or {}).get("selected_instance_ids"), [LIVE_ID])
    request, why = mine_q(rows2, ["session-feedback/TC-003"], scope=wide)
    check_eq(f"{name} (b): and the other area's ask selects the other row",
             (request or {}).get("selected_instance_ids"), [other["instance_id"]])
    request, why = mine_q(rows2, ["TC-003"], scope=wide)
    check(f"{name} (d): a bare number held under two areas is refused, not run for both", request is None)
    check_in(f"{name} (d): the refusal names both spellings", "feedback-api/TC-003, session-feedback/TC-003", str(why))
    check_in(f"{name} (d): and the door - the qualified ask to type", "name the one you mean: --mine feedback-api/TC-003",
             str(why))
    check_in(f"{name} (d): and, for a dispatch given the bare id, the hand-back (finding (zh), F3)",
             "if your dispatch was given the bare id, hand it back in your digest", str(why))
    # F4: the count is not "two" - three areas hold it, the text says "more than one area" and names all three
    rows3 = rows2 + [live_row("third-area/TC-003", "_InThird")]
    request, why = mine_q(rows3, ["TC-003"], scope=wide + ["third-area/TC-003"])
    check(f"{name} (d): a bare number held under three areas is refused too", request is None)
    check_in(f"{name} (d): it says 'more than one area', never 'two'", "TC-003 is held under more than one area (", str(why))
    check_not_in(f"{name} (d): and no count that is wrong for three", "two areas", str(why))
    check_in(f"{name} (d): and it names all three spellings",
             "feedback-api/TC-003, session-feedback/TC-003, third-area/TC-003", str(why))

    # (c) unapproved asks stay outside the scope, in today's words
    request, why = mine_q([live_row()], ["TC-003"])
    check(f"{name} (c): a bare TC-003 is not in a scope that holds only the qualified one", request is None)
    check_in(f"{name} (c): the outside-scope refusal, today's words",
             f"TC-003 is {er.SCOPE_BLOCK}: dispatch S5-qa-automator-5 was given TC-001, TC-002, TC-004, "
             "feedback-api/TC-003", str(why))
    request, why = mine_q([live_row()], ["other-area/TC-003"])
    check(f"{name} (c): another area's TC-003 is outside the scope", request is None)
    check_in(f"{name} (c): and says so", f"other-area/TC-003 is {er.SCOPE_BLOCK}", str(why))

    # rule (c) of the predicate: the scope and the manifest disagree on the area
    held_elsewhere = [live_row("session-feedback/TC-003", "_InSession")]
    request, why = mine_q(held_elsewhere, [ask])
    check(f"{name} (d) wrong area: a number held only under another area is refused, never run on a guess",
          request is None)
    check_in(f"{name} (d) wrong area: the refusal names the asked id", ask + ": the manifest holds TC-003", str(why))
    check_in(f"{name} (d) wrong area: and the area the manifest holds", "only under session-feedback/TC-003", str(why))
    check_in(f"{name} (d) wrong area: and the door (FR-1, FR-2)", "manifest_put.py", str(why))
    check_not_in(f"{name} (d) wrong area: it is no longer a refusal about profiles",
                 "cannot tell which execution profile", str(why))

    # (e) a 0.7.x row names no area anywhere: compatibility, with a note
    legacy = live_row("TC-003", covers=["TC-003"], case_version_links=[])
    request, notes = mine_q([legacy], [ask])
    check(f"{name} (e) 0.7.x row: a row that names no area answers a qualified ask [{notes}]", request is not None)
    check_in(f"{name} (e) 0.7.x row: and the note says the area was not named",
             f"{ask}: the manifest names no area for TC-003; ran its rows", "\n".join(notes) if request else str(notes))
    check_eq(f"{name} (e) 0.7.x row: the asked spelling is kept in built_by.cases",
             (request or {"built_by": {}})["built_by"].get("cases"), [ask])
    # ... but one row with an area makes every bare row of that number strict
    request, why = mine_q([legacy, live_row("session-feedback/TC-003", "_InSession")], [ask])
    check(f"{name} compatibility vs strictness: one row with an area makes the bare rows of that number strict",
          request is None)
    check_in(f"{name} compatibility vs strictness: the refusal says a row with no area is not run on a guess",
             "names no area is not run on a guess", str(why))
    # a bare covers with an area on the pinned link: the key holds the qualified spelling, (a)/(c) apply, never (b)
    pinned = live_row("TC-003", covers=["TC-003"], case_version_links=[
        {"case_id": "TC-003", "area": "feedback-api", "version": LIVE_PIN}])
    request, notes = mine_q([pinned], [ask])
    check(f"{name} edge: a bare covers with an area on its pinned link answers the qualified ask [{notes}]",
          request is not None)
    check_not_in(f"{name} edge: by its key, so no 'names no area' note", "names no area",
                 "\n".join(notes) if request else "")
    request, why = mine_q([pinned], ["other-area/TC-003"], scope=LIVE_SCOPE + ["other-area/TC-003"])
    check(f"{name} edge: and that key keeps another area out (strict, never compatible)", request is None)
    check_in(f"{name} edge: and the refusal says which area the manifest holds",
             "other-area/TC-003: the manifest holds TC-003 only under feedback-api/TC-003", str(why))

    # F2 (t-043): rule (b) is gated by the case store. One bare row is never credited to two areas (FR-18, FR-58).
    bare_row = live_row("TC-003", covers=["TC-003"], case_version_links=[])
    sibling = live_row("feedback-api/TC-001", "_One")
    both = [ask, "session-feedback/TC-003"]
    both_scope = LIVE_SCOPE + ["session-feedback/TC-003"]
    two_areas = {"feedback-api": ["TC-001", "TC-003"], "session-feedback": ["TC-003"]}
    request, why = mine_q([sibling, bare_row], both, scope=both_scope, store=two_areas)
    check(f"{name} F2: one area-less row is not run for both areas of a number the store holds under two", request is None)
    check_in(f"{name} F2: the refusal names the asked id and that the row names no area",
             f"{ask}: the manifest row names no area and the story holds TC-003 under feedback-api and session-feedback",
             str(why))
    check_in(f"{name} F2: and the door", "correct the row's covers through manifest_put.py", str(why))
    request, why = mine_q([sibling, bare_row], [ask], scope=both_scope, store=two_areas)
    check(f"{name} F2: nor for the one asked area alone - another dispatch's area-less row is no evidence for it",
          request is None)
    request, why = mine_q([sibling, bare_row], ["session-feedback/TC-003"], scope=both_scope, store=two_areas)
    check_in(f"{name} F2: the other area's ask is refused the same way", "session-feedback/TC-003: the manifest row names no area",
             str(why))
    three_areas = dict(two_areas, **{"third-area": ["TC-003"]})
    request, why = mine_q([bare_row], [ask], store=three_areas)
    check_in(f"{name} F2: three areas are named 'a, b and c'", "under feedback-api, session-feedback and third-area",
             str(why))
    one_area = {"feedback-api": ["TC-001", "TC-003"]}
    request, notes = mine_q([sibling, bare_row], [ask], store=one_area)
    check(f"{name} F2 control: the same rows with a store that holds TC-003 under ONE area still match [{notes}]",
          request is not None)
    check_in(f"{name} F2 control: with the compatibility note",
             f"{ask}: the manifest names no area for TC-003; ran its rows", "\n".join(notes) if request else str(notes))
    check_eq(f"{name} F2 control: and credit the row to the asked area once",
             (request or {"built_by": {}})["built_by"].get("cases"), [ask])
    request, notes = mine_q([bare_row], [ask], store={})
    check(f"{name} F2 edge: a story with no case store reads as one area - today's compatibility [{notes}]",
          request is not None)
    # an index that cannot be built (a case file declaring another id) counts as one area, not as a new refusal
    write_case_store(two_areas)
    (TASK5_ROOT / "work" / "test-cases" / "feedback-api" / "TC-003.md").write_text(
        f"---\nid: TC-009\ntask: {TASK5}\n---\n", encoding="utf-8")
    quiet, _files = er.manifest_rows({"tests": [bare_row]}, ask, strict=True, store_root=TASK5_ROOT)
    check_eq(f"{name} F2 edge: a store that cannot be indexed gates nothing", len(quiet), 1)
    write_case_store(two_areas)
    quiet, _files = er.manifest_rows({"tests": [bare_row]}, ask, store_root=TASK5_ROOT)
    check_eq(f"{name} F2 callers: a reader that is not strict gets no row for it and no exception", quiet, [])
    # F1 (t-1247): a caller that names no store has no 0.7.x compatibility - the answer before t-1243, the safe
    # default (FR-59): red_sandbox, probe_by_code and window_neighbours reach here
    quiet, _files = er.manifest_rows({"tests": [bare_row]}, ask)
    check_eq(f"{name} F1 callers: one that names no store gets no area-less row for a qualified ask (the pre-diff [])",
             quiet, [])
    quiet, _files = er.manifest_rows({"tests": [bare_row]}, ask, strict=True)
    check_eq(f"{name} F1 callers: nor does the strict path without a store (no exception either)", quiet, [])
    quiet, _files = er.manifest_rows({"tests": [bare_row]}, "TC-003")
    check_eq(f"{name} F1 callers: and a bare ask over the same row is unchanged", len(quiet), 1)
    write_case_store(None)

    # (f) the bare ask, one area or none: today's rule
    request, notes = mine_q([live_row()], ["TC-003"], scope=LIVE_SCOPE + ["TC-003"])
    check_eq(f"{name} (f): a bare ask on a number held under ONE area matches as before",
             (request or {}).get("selected_instance_ids"), [LIVE_ID])
    check_eq(f"{name} (f): and keeps the asked spelling",
             (request or {"built_by": {}})["built_by"].get("cases"), ["TC-003"])
    request, notes = mine_q([legacy], ["TC-003"], scope=LIVE_SCOPE + ["TC-003"])
    check_eq(f"{name} (f): a bare ask on a row with no area matches as before",
             (request or {}).get("selected_instance_ids"), [LIVE_ID])

    # --node-id: the rows are the node ids, the case keeps the asked spelling (the non-pytest refusal speaks of it)
    request, why = mine_q([live_row()], [ask], node_ids=[LIVE_FILE + "::" + LIVE_ID], profile_id="backend-xunit")
    check_in(f"{name} edge: --node-id with a qualified case keeps the asked spelling",
             ask + ": profile backend-xunit", str(why))

    # (g) the pytest path with a bare ask is what it was: rows, nodes and bare files read by the old predicate
    pytest_manifest = {"tests": [
        {"case": "TC-001", "file": "tests/test_a.py", "selector": "test_green"},
        {"case": "TC-002", "file": "tests/test_a.py", "selector": "test_red | test_green[p1|p2]"},
        {"case": "TC-003", "file": "tests/test_a.py"}]}
    rows, files = er.manifest_rows(pytest_manifest, "TC-002")
    check_eq(f"{name} (g): a bare ask on the pytest manifest finds the same nodes as before",
             [r["node"] for r in rows],
             ["tests/test_a.py::test_red", "tests/test_a.py::test_green[p1]", "tests/test_a.py::test_green[p2]"])
    check_eq(f"{name} (g): a case whose entry names no test still answers with its file",
             er.manifest_rows(pytest_manifest, "TC-003"), ([], ["tests/test_a.py"]))
    check_eq(f"{name} (g): a case nobody holds answers with nothing",
             er.manifest_rows(pytest_manifest, "TC-777"), ([], []))

    # the callers other than --mine (a probe, a sandbox, a scope walk) never get an exception from an ambiguous ask
    quiet, _files = er.manifest_rows({"tests": rows2}, "TC-003")
    check_eq(f"{name} callers: a bare number held under two areas gives a probe today's rows, not an exception",
             len(quiet), 2)
    quiet, _files = er.manifest_rows({"tests": held_elsewhere}, ask)
    check_eq(f"{name} callers: a qualified ask held under another area gets no row and no exception", quiet, [])

    # a broken sibling must not take the runner down: with `contract` unimportable the bare path still matches
    saved = sys.modules.get("contract")
    sys.modules["contract"] = None
    try:
        broken_bare, _f = er.manifest_rows({"tests": [{"case": "TC-003", "file": LIVE_FILE, "selector": "T.a"}]}, "TC-003")
        broken_qualified, _f = er.manifest_rows({"tests": [{"case": ask, "file": LIVE_FILE, "selector": "T.a"}]}, ask)
    finally:
        if saved is not None:
            sys.modules["contract"] = saved
        else:
            sys.modules.pop("contract", None)
    check_eq(f"{name} fallback: without the contract module a bare ask still matches its row",
             [r["node"] for r in broken_bare], [LIVE_FILE + "::T.a"])
    check_eq(f"{name} fallback: and a qualified ask matches the row spelled the same way",
             [r["node"] for r in broken_qualified], [LIVE_FILE + "::T.a"])


def qualified_edge_battery() -> None:
    """t-1243 (CX2-22): the edges of the one reader, at the `--mine` seam (E1-E4 of the transfer spec)."""
    name = "t-1243 edges"
    ask = "feedback-api/TC-003"
    legacy = live_row(case="TC-003")
    two_areas = {"feedback-api": ["TC-003"], "session-feedback": ["TC-003"]}
    one_area = {"feedback-api": ["TC-003"]}
    # E1: an area-less row answers a qualified ask when the story holds the number under ONE area; under two
    # the refusal names BOTH areas (never the first)
    request, notes = mine_q([legacy], [ask], store=one_area)
    check(f"{name} E1: one area in the store, an area-less row matches [{notes}]", request is not None)
    request, why = mine_q([legacy], [ask], store=two_areas)
    check(f"{name} E1: two areas in the store, the area-less row is refused", request is None)
    check_in(f"{name} E1: the refusal names both areas, not the first", "feedback-api and session-feedback", str(why))
    # E2: the area is in the manifest, the row of THIS case is not: the case is simply not there. With one profile the
    # refusal is the caller's own, "the manifest names no test for <case>", with the door - never a "foreign area"
    # text (that one is for a number held under ANOTHER area) and never a pin of another case read as this one.
    one_profile = dict(three_profile_config())
    one_profile["profiles"] = one_profile["profiles"][:1]
    other_number = live_row(case="feedback-api/TC-004", name="Four",
                            case_version_links=[{"case_id": "TC-004", "version": LIVE_PIN}])
    request, why = mine_q([other_number], [ask], store=one_area, cfg=one_profile)
    check(f"{name} E2: a case with no row at all is not run", request is None)
    check_in(f"{name} E2: the refusal says the manifest names no test for it, and the door",
             f"the manifest names no test for {ask} yet", str(why))
    check_in(f"{name} E2: (the door)", "manifest_put.py", str(why))
    check_not_in(f"{name} E2: and it is not called a foreign area", "disagree on the area", str(why))
    check_not_in(f"{name} E2: nor held under another area", "only under", str(why))
    # (v) a person's word never invents coverage (FR-18): a word that passes the SCOPE block does not pass the identity
    # refusals - a bare number two areas hold, and a qualified ask whose number only another area holds, stay refused
    saved_word = er.person_passed
    er.person_passed = lambda task_root, stage, message: "run it anyway"
    try:
        rows_two = [live_row(), live_row(case="session-feedback/TC-003", name="Other")]
        request, why = mine_q(rows_two, ["TC-003"])
        check(f"{name} (v): a person's word on the scope does not choose between two areas for a bare ask", request is None)
        check_in(f"{name} (v): the refusal still names both spellings", "feedback-api/TC-003, session-feedback/TC-003",
                 str(why))
        request, why = mine_q([live_row(case="session-feedback/TC-003", name="Other")], ["feedback-api/TC-003"])
        check(f"{name} (v): nor does it run the other area's row for a qualified ask", request is None)
        check_in(f"{name} (v): the refusal names the area the manifest holds", "only under session-feedback/TC-003", str(why))
    finally:
        er.person_passed = saved_word
    # E3: the row's area is one nothing else knows (a typo): it is another area, the refusal names it and the door
    typo = live_row(case="feedbak-api/TC-003", name="Typo")
    request, why = mine_q([typo], [ask], store=one_area)
    check(f"{name} E3: a row under an area the dispatch never named is refused", request is None)
    check_in(f"{name} E3: the refusal names the area the row holds", "only under feedbak-api/TC-003", str(why))
    check_in(f"{name} E3: and the door is the manifest row", "correct the row's covers through manifest_put.py", str(why))
    # E4: an empty manifest, an absent one: the reader answers with the empty outcome, no raise
    check_eq(f"{name} E4: no manifest at all", er.manifest_rows({}, ask, strict=True), ([], []))
    check_eq(f"{name} E4: a manifest with no tests", er.manifest_rows({"tests": []}, ask, strict=True), ([], []))
    check_eq(f"{name} E4: None", er.manifest_rows(None, ask, strict=True), ([], []))
    # ... and through the caller, with the one profile: the refusal names the artifact's gap and the door, for an
    # empty manifest and for a manifest file that is not there
    request, why = mine_q([], [ask], store=one_area, cfg=one_profile)
    check_in(f"{name} E4: an empty manifest - the caller's refusal says the manifest names no test",
             f"the manifest names no test for {ask} yet", str(why))
    qualified_story([], LIVE_SCOPE, one_area)
    (TASK5_ROOT / "work" / "automation-manifest.json").unlink()
    try:
        er.build_mine_request(ROOT, [ask], cfg=one_profile, task=TASK5,
                              probe=lambda spec: dict(PROVENANCE, profile_id="backend-xunit"), again=True)
        absent = "built"
    except er.MineRefusal as exc:
        absent = str(exc)
    check_in(f"{name} E4: no manifest file - the same refusal, never a build", f"the manifest names no test for {ask} yet",
             absent)
    write_case_store(None)


def qualified_fix_round_battery() -> None:
    """t-1249 (the fix round of t-1243, critic t-1247): B1 the refusal order, B2 the foreign-area door, B3 the
    bare ask over a two-area store, F6 the backslash spelling. F1 is pinned in `qualified_case_battery`."""
    name = "t-1249 fix round"
    ask = "feedback-api/TC-003"
    other_ask = "session-feedback/TC-003"
    two_areas = {"feedback-api": ["TC-003"], "session-feedback": ["TC-003"]}
    both_scope = LIVE_SCOPE + [other_ask]
    one_profile = dict(three_profile_config())
    one_profile["profiles"] = one_profile["profiles"][:1]
    session_row = live_row(case=other_ask, name="_InSession")

    # B1: several profiles, a case with no row and no file - the refusal names the missing TEST, not the profile
    request, why = mine_q([], [ask], store=two_areas, scope=both_scope)
    check(f"{name} B1: three profiles, an empty manifest - refused", request is None)
    check_in(f"{name} B1: and it says the manifest names no test for the case",
             f"the manifest names no test for {ask} yet", str(why))
    check_in(f"{name} B1: with the door", "manifest_put.py", str(why))
    check_not_in(f"{name} B1: and it is not a refusal about profiles", "execution profile", str(why))
    request, why = mine_q([live_row(case="feedback-api/TC-004", name="Four",
                                    case_version_links=[{"case_id": "TC-004", "version": LIVE_PIN}])], [ask])
    check_in(f"{name} B1: a manifest that holds only another case - the same sentence",
             f"the manifest names no test for {ask} yet", str(why))
    check_not_in(f"{name} B1: and no profile question", "execution profile", str(why))
    # the position invariant: a case that HAS a file still reaches the profile choice (the refusal moved, not the gate)
    request, why = mine_q([live_row(selector="", file="shared/Other.cs")], [ask])
    check(f"{name} B1 control: a case with a file no profile owns is still refused", request is None)
    check_in(f"{name} B1 control: about the profile, which is reachable for a case that has a file",
             "cannot tell which execution profile", str(why))
    # ... and it is ONE sentence: the helper's text is what both sites raise
    check_eq(f"{name} B1: one text for both sites", er._no_test_refusal(ask, []).split(" yet")[0],
             f"the manifest names no test for {ask}")

    # B2: the asked area exists in the store, its row is not there, and another area's row is: the case has no test yet
    request, why = mine_q([session_row], [ask], scope=both_scope, store=two_areas, cfg=one_profile)
    check(f"{name} B2: nothing is run for a case whose own row is missing", request is None)
    check_in(f"{name} B2: the refusal says the manifest names no test for it", f"the manifest names no test for {ask} yet",
             str(why))
    check_not_in(f"{name} B2: not that the scope and the manifest disagree on the area (that door rewrites a correct row)",
                 "disagree on the area", str(why))
    check_not_in(f"{name} B2: nor that the manifest holds it only under the other area", "only under", str(why))
    request, why = mine_q([session_row], [ask], scope=both_scope, store=two_areas)
    check_in(f"{name} B2: with several profiles too (B1)", f"the manifest names no test for {ask} yet", str(why))
    # the controls: an area the store never holds, and an area-less row beside the other area's row, stay refusals
    third = "third-area/TC-003"
    request, why = mine_q([session_row], [third], scope=both_scope + [third], store=two_areas, cfg=one_profile)
    check_in(f"{name} B2 control: an area the store never holds is the foreign-area refusal",
             f"{third}: the manifest holds TC-003 only under {other_ask}", str(why))
    request, why = mine_q([live_row(case="TC-003", covers=["TC-003"], case_version_links=[]), session_row], [ask],
                          scope=both_scope, store=two_areas, cfg=one_profile)
    check_in(f"{name} B2 control: an area-less row beside another area's row is not run on a guess",
             "names no area is not run on a guess", str(why))

    # B3: a bare ask over a number the STORE holds under two areas is refused, whatever the manifest holds
    bare_scope = LIVE_SCOPE + ["TC-003"]
    saved_word = er.person_passed
    er.person_passed = lambda task_root, stage, message: "run it anyway"
    try:
        for label, rows in (("one qualified row", [live_row()]),
                            ("one area-less row", [live_row(case="TC-003", covers=["TC-003"], case_version_links=[])])):
            request, why = mine_q(rows, ["TC-003"], scope=LIVE_SCOPE, store=two_areas)
            check(f"{name} B3: {label}, the store holds two areas - a person's word on the scope does not pass it",
                  request is None)
            check_in(f"{name} B3: {label} - the refusal names every spelling", f"({ask}, {other_ask})", str(why))
            check_in(f"{name} B3: {label} - and the door", "name the one you mean: --mine " + ask, str(why))
    finally:
        er.person_passed = saved_word
    request, why = mine_q([live_row()], ["TC-003"], scope=bare_scope, store=two_areas)
    check(f"{name} B3: a legacy dispatch scope that holds the bare id, no word - refused", request is None)
    check_in(f"{name} B3: naming both areas of the store", f"({ask}, {other_ask})", str(why))
    three = dict(two_areas, **{"third-area": ["TC-003"]})
    request, why = mine_q([live_row()], ["TC-003"], scope=bare_scope, store=three)
    check_in(f"{name} B3: a third area in the store is named too", f"({ask}, {other_ask}, third-area/TC-003)", str(why))
    request, notes = mine_q([live_row()], ["TC-003"], scope=bare_scope, store={"feedback-api": ["TC-003"]})
    check_eq(f"{name} B3 control: a store that holds ONE area leaves the bare ask as it was",
             (request or {}).get("selected_instance_ids"), [LIVE_ID])
    write_case_store(None)

    # F6: the backslash spelling is the same key (split_case_key normalises it); the refusal never names the asked
    # area as "only under" itself
    backslash = "feedback-api\\TC-003"
    qualified_story([live_row()], LIVE_SCOPE, None)
    rows, _files = er.manifest_rows({"tests": [live_row()]}, backslash, strict=True, store_root=TASK5_ROOT)
    check_eq(f"{name} F6: a backslash-spelled qualified ask finds its row", len(rows), 1)
    try:
        er.manifest_rows({"tests": [session_row]}, backslash, strict=True, store_root=TASK5_ROOT)
        refusal = "no refusal"
    except er.MineRefusal as exc:
        refusal = str(exc)
    check_in(f"{name} F6: and over another area's row the refusal names that area", f"only under {other_ask}", refusal)
    check_not_in(f"{name} F6: never the asked area as the other one", f"only under {ask}", refusal)
    write_case_store(None)


# --- HF2-10 (EP1-17): one collect and one probe before the launch ---------------------------------------------------
# t-1221 measured 1397 s for 11 `--mine` calls on run 12586, ~20 s of them tests. A `--mine` collected twice (the
# builder's collect, then the runner's own check when the builder's was not clean) and probed the stand three times.
# Now the collect the build took is the only one (its list is matched by `node_ids.match`; an unreadable one leaves the
# ids to the run, whose `not found` is `node_id_mismatch`), and the stand reading the build took is the one before
# the launch.

OC, OC2 = "OC-1", "OC-2"
OC_ROOT = ROOT / "qa-factory" / "artifacts" / OC
OC2_ROOT = ROOT / "qa-factory" / "artifacts" / OC2
OC_CASES = {f"TC-9{n}": (f"tests/test_oc{n}.py", f"test_oc{n}") for n in range(1, 10)}
OC_CASES["TC-95"] = ("tests/test_oc5.py", "test_ghost5")


def oc_setup() -> None:
    for n in range(1, 10):
        (ROOT / "tests" / f"test_oc{n}.py").write_text(f"def test_oc{n}():\n    pass\n", encoding="utf-8")
    write_json(ROOT / "qa-factory" / "config.json", config(parallel=True))
    write_json(OC_ROOT / "pipeline.json", {"stages": {"S5": {"status": "running"}}})
    write_json(OC_ROOT / "state" / "controller.json", controller(scope=tuple(OC_CASES)))
    write_json(OC_ROOT / "work" / "automation-manifest.json", {"tests": [
        {"case": case, "file": file, "selector": selector} for case, (file, selector) in OC_CASES.items()]})


def oc_counts(log) -> tuple:
    """(collects, check_requests, matches) the fakes were asked in this call."""
    return tuple(len([e for e in log if e[0] == name]) for name in ("collect", "check_request", "match"))


def one_collect_battery() -> None:
    real = real_node_ids()
    oc_setup()
    probes, at_launch = [], []
    saved_probe, saved_run = run_suite.probe_runtime, run_suite.run

    def counting_probe(spec):
        probes.append(dict(spec))
        return dict(PROVENANCE)

    def run_spy(args):
        at_launch.append(len(probes))
        return saved_run(args)
    run_suite.probe_runtime, run_suite.run = counting_probe, run_spy

    def jobs() -> list:
        return er.JobStore(OC_ROOT / "state" / "execution-jobs").jobs()

    def mine_call(*argv):
        probes.clear()
        at_launch.clear()
        return call("--mine", *argv, "--task", OC)

    def notes_of(out) -> str:
        return " ".join(last_json(out).get("node_id_notes") or [])
    try:
        # B-K1 / M-B1 / B-E2: an unparsed collect is not repeated
        log = fake_modules(collected=None)
        before = len(launches())
        code, out, err = mine_call("TC-91")
        check_eq("M-B1: an unparsed collect is not repeated: one collect, no check_request, no match",
                 oc_counts(log), (1, 0, 0))
        check_eq("M-B1: ... the run was launched and ran", (code, len(launches()), launches()[-1:]),
                 (0, before + 1, ["tests/test_oc1.py::test_oc1"]))
        check_in("M-B1: ... and the note says the ids were not verified, and why",
                 "node ids were not verified: pytest collected 3 test(s) but none could be parsed", notes_of(out))
        check_in("M-B1: ... with the head of the collect", "collect failed: banner", notes_of(out))
        # B-K5 / B-K6: the cost, counted by the code
        check_eq("B-K5 / M-B5: ONE runtime probe before the launch, and the post-run probe: 2 in all (was 3)",
                 (at_launch, len(probes)), ([1], 2))
        print(f"COUNTS (one --mine, unparsed collect): collect calls was 2 -> now {oc_counts(log)[0]}; "
              f"runtime probes was 3 -> now {len(probes)} (before the launch: {at_launch[0]})")

        # B-E1: an empty successful collect gives the verdict a second collect gave, with one collect
        log = fake_modules(collected=[])
        before, jobs_before = len(launches()), len(jobs())
        code, out, err = mine_call("TC-92")
        answer = last_json(out)
        check_eq("B-E1: an empty successful collect: node_id_mismatch, exit 2, ONE collect, nothing launched, no key spent",
                 (code, answer.get("status"), oc_counts(log)[0], len(launches()), len(jobs())),
                 (2, "node_id_mismatch", 1, before, jobs_before))
        check_eq("B-E1: ... `nearest` is empty (nothing was collected), and the stand was read once",
                 (answer["missing"][0]["nearest"], len(probes)), ([], 1))

        # B-E3: the timeout, at and beyond the boundary - the stub raises what node_ids._run raises
        log = fake_modules(collected=["tests/test_oc7.py::test_oc7"])
        code, out, err = mine_call("TC-97")
        check_eq("B-E3 at the boundary (the collect answered in time): read as ever, verified, no note, one collect",
                 (code, oc_counts(log), last_json(out).get("node_id_notes")), (0, (1, 0, 0), None))
        log = fake_modules(collected=real.CollectError("collect timed out after 180s"))
        code, out, err = mine_call("TC-93")
        check_eq("B-E3 beyond it: not verified (never 'no tests'), the run goes, and the 180 s is waited for ONCE",
                 (code, oc_counts(log)), (0, (1, 0, 0)))
        check_in("B-E3: ... the note names the timeout", "node ids were not verified: collect timed out after 180s",
                 notes_of(out))

        # B-K2 / M-B8: an explicit --node-id without [...] in an existing file is not collected
        log = fake_modules(collected=["tests/test_oc4.py::test_oc4"])
        before = len(launches())
        code, out, err = mine_call("TC-94", "--node-id", "tests/test_oc4.py::test_oc4", "--again")
        check_eq("M-B8: --node-id of an existing file, no [...]: collect called ZERO times, the run launched",
                 (code, oc_counts(log), len(launches())), (0, (0, 0, 0), before + 1))
        check_in("B-K2: the request carries the note", "node ids were not verified: --node-id is checked by the run itself",
                 notes_of(out))
        # B-E4: a file that is not there is refused before the collect and before the stand
        log = fake_modules(collected=["tests/test_oc4.py::test_oc4"])
        before = len(launches())
        code, out, err = mine_call("TC-94", "--node-id", "tests/not_there.py::test_x", "--again")
        said = last_json(out)
        check_eq("B-E4: --node-id of a missing file: mine_refused, no collect, no probe, nothing launched",
                 (code, said.get("status"), oc_counts(log)[0], len(probes), len(launches())), (2, "mine_refused", 0, 0, before))
        check_in("B-E4: ... in today's words", "no such file is under", said.get("error", ""))

        # B-K3 / B-E5 / M-B3: the ids nobody proved are proved by the run - pytest's exit 4 `not found`
        log = fake_modules(collected=None)
        jobs_before, before = len(jobs()), len(launches())
        code, out, err = mine_call("TC-95")
        summary = last_json(out)
        check_eq("M-B3: an unreadable collect, then pytest's `not found`: node_id_mismatch, NOT EXECUTED, never passed or failed",
                 (code, summary.get("blocked"), summary.get("execution_status"), oc_counts(log)[0]),
                 (4, "node_id_mismatch", "not_executed", 1))
        check_eq("B-K3: the form is the contract (F-B5): missing = [{asked, nearest: []}]",
                 summary.get("missing"), [{"asked": "tests/test_oc5.py::test_ghost5", "nearest": []}])
        check_eq("B-E5: the key is spent (the run happened), the job is `not_executed`",
                 (len(jobs()), len(launches()), jobs()[-1].get("execution_status")), (jobs_before + 1, before + 1, "not_executed"))
        first_key = jobs()[-1]["idempotency_key"]
        code, out, err = mine_call("TC-95", "--node-id", "tests/test_oc5.py::test_oc5", "--again")
        check_eq("B-E5: the corrected id is another selector and another key (not `duplicate`), and it passes",
                 (code, last_json(out).get("execution_status"), len(jobs()), jobs()[-1]["idempotency_key"] != first_key),
                 (0, "passed", jobs_before + 2, True))

        # B-E6: an id with [...] still goes through ONE collect (TP1-15045)
        log = fake_modules(collected=["tests/test_oc6.py::test_oc6[chromium-p1]"])
        code, out, err = mine_call("TC-96", "--node-id", "tests/test_oc6.py::test_oc6[p1]", "--again")
        check_eq("B-E6: --node-id with [p1] is respelled from ONE collect and ran as the real id",
                 (code, oc_counts(log), launches()[-1]), (0, (1, 0, 0), "tests/test_oc6.py::test_oc6[chromium-p1]"))
        # ... and the id the build could not respell is matched, by the same `match`, against the SAME list
        log = fake_modules(collected=["tests/test_oc6.py::test_oc6[p2]"])
        code, out, err = mine_call("TC-96", "--node-id", "tests/test_oc6.py::test_oc6[chromium-p2]", "--again")
        check_eq("B-K1: the respelling `match` makes over the first list: collect 1, match 1, check_request 0, real id launched",
                 (code, oc_counts(log), launches()[-1]), (0, (1, 0, 1), "tests/test_oc6.py::test_oc6[p2]"))
        check_in("B-K1: ... said as a note of the run", "tests/test_oc6.py::test_oc6[chromium-p2] is collected as [p2]",
                 notes_of(out))

        # RH1-3 3.3a: a collect that went on past broken files (kind partial) is ONE collect, the run is not refused
        # for it, the broken files are named, and the story keeps them (collect-gaps.json, one writer)
        broken_one = [{"path": "tests/test_oc3.py", "head": "ImportError: gone"}]
        log = fake_modules(collected=real.CollectError("1 file(s) could not be collected", "head", kind="partial",
                                                       ids=["tests/test_oc4.py::test_oc4"], broken=broken_one))
        before = len(launches())
        code, out, err = mine_call("TC-92")           # a case nothing ran yet: the others answer `already run`
        check_eq("K-3.3-once a partial collect is ONE collect, no second, and the run is launched (not refused)",
                 (code, oc_counts(log), len(launches())), (0, (1, 0, 0), before + 1))
        check_in("K-3.3-note the note names the broken file", "1 file(s) could not be collected: tests/test_oc3.py", notes_of(out))
        check_in("K-3.3-note ... and says the asked id was not verified, with the reason",
                 "not verified, file tests/test_oc2.py yielded no test in this collect", notes_of(out))
        kept = json.loads((OC_ROOT / "state" / "collect-gaps.json").read_text(encoding="utf-8"))["rows"]
        profile = jobs()[-1]["request"]["profile_id"]
        check_eq("K-3.3-record the broken file is kept for the report: source s5_collect, the profile of the request",
                 (kept[0]["source"], kept[0]["profile"] == profile, kept[0]["broken"]),
                 ("s5_collect", True, [dict(broken_one[0], owner="project")]))     # F4: a file the request does not name is the project's
        mined_own = {"collects": [{"files": {"tests/test_oc3.py"}, "ids": None, "error": real.CollectError(
            "x", kind="partial", ids=[], broken=[{"path": "tests/test_oc3.py", "head": ""}, {"path": "tests/sub", "head": ""}])}]}
        run_suite._record_collect_gaps({"task": OC, "profile_id": profile}, mined_own, ["tests/test_oc3.py::test_x"],
                                       {"notes": [], "broken": [{"path": "tests/test_oc3.py", "head": ""}, {"path": "tests/sub", "head": ""}]})
        import collect_gaps as _CG
        check_eq("F4-owner a broken path that IS a test file the request names is the story's; a folder is the project's",
                 [(b["path"], b["owner"]) for b in _CG.read(OC_ROOT)["rows"][0]["broken"]],
                 [("tests/test_oc3.py", "story"), ("tests/sub", "project")])
        import collect_gaps
        asked_one = ["tests/test_oc1.py::test_oc1"]
        answered = {"collects": [{"files": {"tests/test_oc1.py"}, "ids": ["tests/test_oc1.py::test_oc1"], "error": None}]}
        timed_out = {"collects": [{"files": {"tests/test_oc1.py"}, "ids": None, "error": real.CollectError("t", kind="timeout")}]}
        run_suite._record_collect_gaps({"task": OC, "profile_id": profile}, timed_out, asked_one, {"notes": []})
        check_eq("K-3.3-record a collect that did not answer leaves the record as it was (nothing was learned)",
                 len(collect_gaps.read(OC_ROOT)["rows"]), 1)
        run_suite._record_collect_gaps({"task": OC, "profile_id": profile}, answered, asked_one, {"notes": []})
        check_eq("K-3.3-record a later collect that found nothing broken erases the row of that profile",
                 collect_gaps.read(OC_ROOT)["rows"], [])

        # E3-10: BROKEN_SHOWN = 10 files are named, the 11th is counted; the record keeps them all
        def partial_note(count: int) -> str:
            rows = [{"path": f"tests/broken_{n:02d}.py", "head": ""} for n in range(count)]
            exc = real.CollectError("x", kind="partial", ids=["tests/test_oc2.py::test_oc2"], broken=rows)
            mined = {"collects": [{"files": {"tests/test_oc1.py"}, "ids": None, "error": exc}], "unasked": "x"}
            return run_suite._checked_by_the_first_collect(mined, ["tests/test_oc1.py::test_oc1"], real)["notes"][0]
        ten, eleven = partial_note(10), partial_note(11)
        check_eq("K-3.3-10 ten broken files are all named, nothing is counted away",
                 ("(+" in ten, ten.count("tests/broken_"), ten.startswith("10 file(s) could not be collected")),
                 (False, 10, True))
        check_eq("K-3.3-11 eleven: ten named and `(+1 more)`, the count in the head is 11",
                 (eleven.count("tests/broken_"), "(+1 more)" in eleven, eleven.startswith("11 file(s)")), (10, True, True))
        check_eq("K-3.3-11 the limit is the constant", run_suite.BROKEN_SHOWN, 10)

        # E3-12: a runner table that cannot be read is form=None, as before, with a note - and no flag from the code
        seen_forms = []
        stub = types.ModuleType("node_ids")

        def stub_collect(argv, cwd, timeout, files=(), form=None):
            seen_forms.append((list(argv), form))
            return ["tests/test_oc1.py::test_oc1"]
        stub.collect = stub_collect
        saved_module = sys.modules.get("node_ids")
        sys.modules["node_ids"] = stub
        try:
            notes_list = []
            ids = with_runner_data(b"{nope", lambda: run_suite.collect_files(["pytest", "-q"], str(ROOT), ["tests/test_oc1.py"],
                                                                             config(), notes_list))
            check_eq("K-3.3-table an unreadable runner table: the collect runs with form=None and no flag of the code's own",
                     (ids, seen_forms[-1]), (["tests/test_oc1.py::test_oc1"], (["pytest", "-q"], None)))
            check_in("K-3.3-table ... and a note says why", "the runner table could not be read", " ".join(notes_list))
            run_suite.collect_files(["pytest", "-q"], str(ROOT), ["tests/test_oc1.py"], config())
            row = seen_forms[-1][1]
            check_eq("K-3.3-table the shipped table hands the pytest row to node_ids (its flag lives there, not here)",
                     (row or {}).get("continue_tokens"), ["--continue-on-collection-errors"])
            check_not_in("K-3.3-table the code carries no flag literal of its own",
                         "continue-on-collection-errors", (PLUGIN_ROOT / "scripts" / "run_suite.py").read_text(encoding="utf-8"))
        finally:
            if saved_module is not None:
                sys.modules["node_ids"] = saved_module

        # B-K4 / M-B4 / B-E7 / B-E8: the refusal that does not depend on the collect is given BEFORE it, and before
        # anything the collect reads. A fresh story: no earlier request to copy the probe from.
        no_probes = config()
        no_probes["execution"] = {}
        write_json(OC2_ROOT / "pipeline.json", {"stages": {"S5": {"status": "running"}}})
        write_json(OC2_ROOT / "state" / "controller.json", controller(scope=("TC-91", "TC-92")))
        write_json(OC2_ROOT / "work" / "automation-manifest.json", {"tests": [
            {"case": "TC-91", "file": "tests/test_oc1.py", "selector": "test_oc1"},
            {"case": "TC-92", "file": "tests/test_oc2.py"}]})
        seen = []

        def counting_collect(argv, cwd, files):
            seen.append(list(files))
            return ["tests/test_oc1.py::test_oc1", "tests/test_oc2.py::test_oc2"]

        def refused(cases, **kwargs):
            seen.clear()
            probes.clear()
            try:
                er.build_mine_request(ROOT, cases, cfg=no_probes, task=OC2, again=True, collect=counting_collect,
                                      probe=kwargs.pop("probe", counting_probe), **kwargs)
            except er.MineRefusal as exc:
                return str(exc)
            return ""
        why = refused(["TC-91"])
        check_in("M-B4: no runtime_probes and no precedent: refused, naming the factory's gap",
                 "first typed run on profile api", why)
        check_eq("M-B4: no runtime_probes, no precedent: refused, and the collect stub was called ZERO times", seen, [])
        why = refused(["TC-91"], probe=None)
        check_in("B-E7: no probe given to the builder: the same refusal", "first typed run on profile api", why)
        check_eq("B-E7: ... the collect stub called zero times", seen, [])
        why = refused(["TC-92"])
        check_in("B-E8: a bare file (a collect would read it) with no probe to take: the stand's refusal comes first",
                 "first typed run on profile api", why)
        check_eq("B-E8: ... collect zero times", seen, [])
        why = refused(["TC-91"], node_ids=["tests/not_there.py::test_x"])
        check_in("B-E8: a static refusal (a file that is not there) comes before the stand's", "no such file is under", why)
        check_eq("B-E8: ... no collect, no probe", (seen, probes), ([], []))
        why = refused(["TC-91"], profile_id="ghost-profile")
        check_in("B-E8: the profile refusal comes before the stand's", "ghost-profile", why)
        check_eq("B-E8: ... no collect, no probe", (seen, probes), ([], []))
        er.build_mine_request(ROOT, ["TC-91"], cfg=config(), task=OC2, again=True, collect=counting_collect,
                              probe=counting_probe)
        check_eq("B-E7 control: the same story with a registered probe is built: ONE probe, ONE collect",
                 (len(probes), len(seen)), (1, 1))

        # B-E10: the person's switch keeps switching everything off - the first list's check and the run's
        off = config(parallel=True)
        off["execution"] = dict(off["execution"], verify_node_ids=False)
        write_json(ROOT / "qa-factory" / "config.json", off)
        log = fake_modules(collected=["tests/test_oc8.py::other"])
        before = len(launches())
        code, out, err = mine_call("TC-98", "--node-id", "tests/test_oc8.py::test_oc8[x]", "--again")
        check_eq("M-B9: verify_node_ids: false, an id the first list lacks: launched as asked, no refusal",
                 (code, len(launches()), last_json(out).get("status")), (0, before + 1, None))
        check_in("M-B9: ... with the note naming the switch", "execution.verify_node_ids", notes_of(out))
        code, out, err = mine_call("TC-98", "--node-id", "tests/test_oc8.py::test_ghost8", "--again")
        summary = last_json(out)
        check_eq("M-B9: ... and the run's own `not found` is no node_id_mismatch either (exit 4 is the run's, as ever)",
                 (code, summary.get("blocked"), summary.get("missing"), summary.get("execution_status")),
                 (4, None, None, "broken_run"))
        write_json(ROOT / "qa-factory" / "config.json", config(parallel=True))

        # B-E14 / B-E11: a request that was NOT built by `--mine` in this process is checked in full
        built, _notes, _reuse, _verified = er.build_mine_request(ROOT, ["TC-99"], cfg=config(), task=OC, again=True,
                                                                  probe=counting_probe)
        request_file = er.write_mine_request(ROOT, built)
        probes.clear()
        log = fake_modules(missing=[{"asked": "tests/test_oc9.py::test_oc9", "nearest": []}])
        code, out, err = call("--request", request_file)
        check_eq("B-E14: a request file: its own collect-check runs (check_request) and refuses, and the stand is read for it",
                 (code, last_json(out).get("status"), oc_counts(log)[1], len(probes)), (2, "node_id_mismatch", 1, 1))
        args = types.SimpleNamespace(mine_memo={"collects": [], "probes": [({**built["runtime_probe"], "cwd": str(ROOT)},
                                                                              {"marker": 1})]})
        spec = dict(built["runtime_probe"], cwd=".")
        check_eq("B-E11: the reading of the build is taken for the same probe (a relative cwd is the project root's)",
                 run_suite._observed_while_building(args, {"runtime_probe": spec}), {"marker": 1})
        check_eq("B-E11: ... never for a stand the build did not observe (`runtime_observed: false`)",
                 run_suite._observed_while_building(args, {"runtime_probe": spec, "runtime_observed": False}), None)
        check_eq("B-E11: ... never for another probe command",
                 run_suite._observed_while_building(args, {"runtime_probe": dict(spec, argv=["other"])}), None)
        check_eq("B-E11: ... never for a request that was not built here (no memo)",
                 run_suite._observed_while_building(types.SimpleNamespace(), {"runtime_probe": spec}), None)

        # a collect over other files says nothing about these ids (AR-28): not verified, never "found"
        fake_modules()
        asked_request = request_for([PY, str(ROOT / "fake" / "pytest")], ("tests/test_oc9.py::test_oc9",))
        got = run_suite.verify_node_ids(asked_request, config(), mined={"collects": [
            {"files": {"tests/test_oc1.py"}, "ids": ["tests/test_oc1.py::test_oc1"], "error": None}], "unasked": "x"})
        check_in("AR-28: a collect that did not list this id's file is no answer: not verified, no refusal",
                 "node ids were not verified", " ".join(got["notes"]))
    finally:
        run_suite.probe_runtime, run_suite.run = saved_probe, saved_run
        write_json(ROOT / "qa-factory" / "config.json", config())


def phases_battery() -> None:
    """EP1-23 B1 (t-207): `phases_s` in the run summary and the PHASES line on stderr.

    AK1 the six keys, numbers with one decimal; AK2 stdout stays ONE json (the line is stderr's); AK3 `collect_s` and
    `stand_probe_s` are SUMS of the calls made; AK4 the line is printed on an answer without a launch (no `pytest_s`).
    Edges: a phase that did not happen is null, never 0; measuring never raises; the summary of a launch that failed
    keeps its `phases_s` with `pytest_s` null."""
    import time
    import subprocess
    oc_setup()
    saved = run_suite.probe_runtime, run_suite.collect_files, subprocess.Popen
    slow = 0.35

    def slow_probe(spec):
        time.sleep(slow)
        return dict(PROVENANCE)

    def slow_collect(argv, cwd, files, cfg, notes=None):
        time.sleep(slow)
        return saved[1](argv, cwd, files, cfg, notes)
    run_suite.probe_runtime, run_suite.collect_files = slow_probe, slow_collect
    keys = {"build_s", "stand_probe_s", "collect_s", "before_launch_s", "pytest_s", "after_s"}

    def mine_call(*argv):
        return call("--mine", *argv, "--task", OC)
    try:
        # AK1 / AK3 / AK2: a launched --mine call
        fake_modules(collected=["tests/test_oc6.py::test_oc6[chromium-ph1]"])
        code, out, err = mine_call("TC-96", "--node-id", "tests/test_oc6.py::test_oc6[ph1]", "--again")
        phases = last_json(out).get("phases_s")
        check_eq("AK1: the summary of a --mine run carries phases_s with exactly the six keys",
                 (code, set(phases or {})), (0, keys))
        check("AK1: every phase is a number with one decimal",
              all(isinstance(v, float) and v == round(v, 1) and v >= 0 for v in (phases or {}).values()), str(phases))
        check("AK3: collect_s is the time of the collect (>= its 0.35 s)", (phases or {}).get("collect_s", 0) >= 0.3, str(phases))
        check("AK3: stand_probe_s is the time of the build's stand probe (>= its 0.35 s)",
              (phases or {}).get("stand_probe_s", 0) >= 0.3, str(phases))
        check("AK1: build_s is the build WITHOUT its collect and probe (they are not counted twice)",
              (phases or {}).get("build_s", 99) < 0.3, str(phases))
        # F6: the clock starts BEFORE the module import, so the load of `execution_request` is in build_s and total_s
        import importlib.abc

        class SlowImport(importlib.abc.MetaPathFinder):
            def find_spec(self, name, path=None, target=None):
                if name == "execution_request":
                    time.sleep(0.4)
                return None                                   # the ordinary finders then load the module
        finder = SlowImport()
        sys.modules.pop("execution_request", None)
        sys.meta_path.insert(0, finder)
        try:
            fake_modules(collected=["tests/test_oc6.py::test_oc6[chromium-ph1]"])
            _code, slow_out, slow_err = mine_call("TC-96", "--node-id", "tests/test_oc6.py::test_oc6[ph1]", "--again")
        finally:
            sys.meta_path.remove(finder)
            sys.modules["execution_request"] = er
        slow_line = next((ln for ln in slow_err.splitlines() if ln.startswith("PHASES:")), "")
        total = float(slow_line.split("total_s=")[1].split()[0]) if "total_s=" in slow_line else 0.0
        build = float(slow_line.split("build_s=")[1].split()[0]) if "build_s=" in slow_line else 0.0
        check("F6: a slow import of the build's module is counted in build_s (>= 0.35 s; the PHASES line, the call may be `reused`)",
              build >= 0.35, slow_line)
        check("F6: ... and in total_s", total >= 0.35, slow_line)
        clock = {}
        # FR-31: no absolute floor from sleep(): the sum is compared with the same clock read outside each block, and a
        # tolerance (0.04) well under one block's length (0.1) tells the sum from the last call's time alone
        outer = 0.0
        for _ in range(2):
            began = time.monotonic()
            with run_suite._phase(clock, "collect_s"):
                time.sleep(0.1)
            outer += time.monotonic() - began
        check("AK3: collect_s is SUMMED over the calls, not the last call's time",
              outer - 0.04 <= clock["collect_s"] <= outer, f"{clock} outer={outer}")
        try:
            whole = json.loads(out)
        except ValueError:
            whole = None
        check("AK2: stdout stays ONE json document", isinstance(whole, dict), out[:200])
        check_not_in("AK2: no PHASES line in stdout", "PHASES:", out)
        line = next((ln for ln in err.splitlines() if ln.startswith("PHASES:")), "")
        check("AK2: the PHASES line is on stderr, with the phases and total_s",
              all(f"{k}=" in line for k in keys | {"total_s"}), line)

        # AK4: answered without a launch (green result over the same bytes) - the line, no pytest_s
        code, out, err = mine_call("TC-96", "--node-id", "tests/test_oc6.py::test_oc6[ph1]")
        answer = last_json(out)
        line = next((ln for ln in err.splitlines() if ln.startswith("PHASES:")), "")
        check_eq("AK4: the second call is answered without a launch", (code, answer.get("status") in ("reused", "already_run")),
                 (0, True))
        # (the `--again` calls above now write the collect memo (F-1), so this plain call plays the list back: no collect
        # happened in it, and `collect_s` is null by the existing null rule)
        check("AK4: ... and the PHASES line is printed, with the build but without pytest_s",
              "build_s=" in line and "total_s=" in line and "pytest_s" not in line, line)
        check_not_in("AK4: ... and, the list being played back from the memo, without collect_s", "collect_s=", line)
        check_not_in("AK4: ... stdout carries no PHASES line", "PHASES:", out)
        # a refusal while building also says where the time went
        fake_modules(collected=["tests/test_oc4.py::test_oc4"])
        code, out, err = mine_call("TC-94", "--node-id", "tests/not_there.py::test_x", "--again")
        check_eq("AK4: a refusal at the build prints the line too (exit 2, no pytest_s)",
                 (code, last_json(out).get("status"), "PHASES:" in err, "pytest_s" in err), (2, "mine_refused", True, False))

        # --request: nothing was built here - the build phases are null, not 0
        fake_modules()
        run_suite.probe_runtime = saved[0]
        built, _notes, _reuse, _verified = er.build_mine_request(ROOT, ["TC-99"], cfg=config(), task=OC, again=True,
                                                                  probe=lambda spec: dict(PROVENANCE))
        code, out, err = call("--request", er.write_mine_request(ROOT, built))
        phases = last_json(out).get("phases_s") or {}
        check_eq("--request: build_s, stand_probe_s and collect_s are null (they did not happen)",
                 (code, phases.get("build_s"), phases.get("stand_probe_s"), phases.get("collect_s")), (0, None, None, None))
        check_eq("--request: collect_s is null", phases.get("collect_s"), None)
        check("--request: the phases that did happen are numbers",
              all(isinstance(phases.get(k), float) for k in ("before_launch_s", "pytest_s", "after_s")), str(phases))

        # a launch that failed: the summary is written with phases_s, pytest_s null
        built, _notes, _reuse, _verified = er.build_mine_request(ROOT, ["TC-98"], cfg=config(), task=OC, again=True,
                                                                  probe=lambda spec: dict(PROVENANCE))
        request_file = er.write_mine_request(ROOT, built)
        real_popen = subprocess.Popen

        def broken_popen(cmd, *a, **kw):
            if "fake" in str(cmd) and "pytest" in str(cmd):
                raise PermissionError("denied")
            return real_popen(cmd, *a, **kw)
        subprocess.Popen = broken_popen
        try:
            code, out, err = call("--request", request_file)
        finally:
            subprocess.Popen = real_popen
        phases = last_json(out).get("phases_s") or {}
        check_eq("failed_to_launch: exit 127, the summary keeps phases_s, pytest_s and after_s are null",
                 (code, set(phases), phases.get("pytest_s"), phases.get("after_s")), (127, keys, None, None))
        check("failed_to_launch: the PHASES line is printed, without pytest_s", "PHASES:" in err and "pytest_s" not in err, err[-300:])

        # measuring never raises: a broken clock loses the field, not the run
        saved_phases = run_suite._phases_s

        def boom(*_a, **_k):
            raise RuntimeError("clock broke")
        run_suite._phases_s = boom
        try:
            fake_modules(collected=["tests/test_oc6.py::test_oc6[chromium-ph2]"])
            code, out, err = mine_call("TC-96", "--node-id", "tests/test_oc6.py::test_oc6[ph2]", "--again")
        finally:
            run_suite._phases_s = saved_phases
        check_eq("a failing measurement: the run still completes, no phases_s, a note on stderr",
                 (code, "phases_s" in last_json(out), "PHASES (note): not measured" in err), (0, False, True))
    finally:
        run_suite.probe_runtime, run_suite.collect_files, subprocess.Popen = saved
        write_json(ROOT / "qa-factory" / "config.json", config())


# --- EP1-23 B2: the collect is not called when its answer is already known -----------------------------------------
# A `--mine` after "edit the body of the test, run it" asked pytest for the same list again (60-100 s). The list is now
# remembered under a key of what a collect depends on - the SKELETON of the test files (bodies emptied), the conftest
# chain, configuration, imported project modules, argv, environment, the stand - and played back through the one
# `_spell_as_collected`. Every awkward input below is gathered by a REAL collect (counter 1); a body edit is 0.

MM, MM_CASE = "MEMO-1", "TC-71"
MM_ROOT = ROOT / "qa-factory" / "artifacts" / MM
MM_FILE = ROOT / "tests" / "test_mm.py"
MM_BODY = "def test_mm_a{args}:\n    assert {n}\n"
MM_PARAM = 'import pytest\n\n\n@pytest.mark.parametrize("x", {values})\n'


def memo_battery() -> None:
    saved_probe = run_suite.probe_runtime
    run_suite.probe_runtime = lambda spec: dict(PROVENANCE)
    write_json(MM_ROOT / "pipeline.json", {"stages": {"S5": {"status": "running"}}})
    write_json(MM_ROOT / "state" / "controller.json", controller(scope=(MM_CASE,)))
    write_json(MM_ROOT / "work" / "automation-manifest.json", {"tests": [
        {"case": MM_CASE, "file": "tests/test_mm.py", "selector": "test_mm_a"}]})
    conftest = ROOT / "tests" / "conftest.py"
    conftest_before = conftest.read_bytes()
    truth = {"ids": ["tests/test_mm.py::test_mm_a"]}
    log = []

    def install() -> None:
        sys.modules["node_ids"] = None
        fake_modules(collected=[], log=log)

        def collect(argv, cwd, timeout_s=180, files=(), form=None):
            log.append(("collect", list(argv)))
            return list(truth["ids"])
        sys.modules["node_ids"].collect = collect

    def write(n: int, values=None, source=None) -> None:
        text = source if source is not None else (
            (MM_PARAM.format(values=values) + MM_BODY.format(args="(x)", n=n)) if values is not None
            else MM_BODY.format(args="()", n=n))
        MM_FILE.write_text(text, encoding="utf-8")

    def mine(*more):
        """(collects asked, launches made, the last job's request, notes, code) of one `--mine`."""
        install()
        before = len(launches())
        jobs_before = len(er.JobStore(MM_ROOT / "state" / "execution-jobs").jobs())
        log.clear()
        code, out, err = call("--mine", MM_CASE, "--task", MM, *more)
        jobs = er.JobStore(MM_ROOT / "state" / "execution-jobs").jobs()
        request = jobs[-1]["request"] if len(jobs) > jobs_before else {}
        return len([e for e in log if e[0] == "collect"]), len(launches()) - before, request, err, code

    def build(no_collect=False, **more):
        """(collects asked, request, notes) of one `build_mine_request` on the story: the doors that are not on the CLI."""
        install()
        asked: list = []

        def counting(argv, cwd, files):
            asked.append(1)
            return list(truth["ids"])
        request, notes, _reuse, _verified = er.build_mine_request(
            ROOT, [MM_CASE], cfg=config(), task=MM, collect=None if no_collect else counting,
            probe=lambda spec: dict(PROVENANCE), **more)
        return len(asked), request, notes

    try:
        # no job at all: as in 0.10.6, one collect - and the list is kept on the request
        write(1)
        asked, ran, first, err, code = mine()
        check_eq("memo-1 no earlier job: ONE real collect, the run launched (as 0.10.6)", (code, asked, ran), (0, 1, 1))
        memo = first.get("collect_memo") or {}
        check_eq("memo-1 ... and the request keeps the list it was spelled from",
                 (bool(memo.get("key")), memo.get("ids")), (True, ["tests/test_mm.py::test_mm_a"]))

        # the window: only the BODY of the test is edited
        write(2)
        asked, ran, second, err, code = mine()
        check_eq("memo-2 a body edit: NO collect, the run launched", (code, asked, ran), (0, 0, 1))
        check_in("memo-2 ... and the note says whose list it is", "node ids are those of the collect of job", err)
        check_in("memo-2 ... and the door", "--again collects afresh", err)
        check_eq("memo-2 ... the memo is carried on", second.get("collect_memo"), memo)
        check_eq("memo-2 ... the id is the collected one", launches()[-1], "tests/test_mm.py::test_mm_a")

        # F-4: every way round the memory is a collect (counter 1), and the plain build next to them is free (counter 0)
        asked, request, _notes = build()
        check_eq("memo-2b control: the plain build of the same story asks no collect and keeps the memory",
                 (asked, request.get("collect_memo")), (0, memo))
        # the third value: a real collect under the door writes the memory (F-1) - except a freshness read and a red probe
        # (the S6 close is a red probe by definition and refuses while a dispatch is open: not reachable from this story)
        for label, more, written in (("`again`", {"again": True}, True), ("`cwd`", {"cwd": str(ROOT)}, True),
                                     ("`sandbox_root`", {"sandbox_root": str(ROOT)}, True),
                                     ("`evidence_only`", {"evidence_only": True}, False),
                                     ("a red probe", {"purpose": "red_probe", "cwd": str(ROOT)}, False)):
            asked, request, _notes = build(**more)
            check_eq(f"memo-2b {label} reads no memory: ONE collect; writes it: {written}",
                     (asked, "collect_memo" in request), (1, written))
        asked, request, _notes = build(no_collect=True)
        check_eq("memo-2b no collect injected: nothing is asked, no memory is read or written",
                 (asked, "collect_memo" in request), (0, False))
        # F-3: a stand nobody could look at (the run budget unreadable, `policy is None`) gets no key and no memory
        saved_budget = er.load_run_budget
        er.load_run_budget = lambda *a, **k: (None, "the run budget could not be read")
        try:
            asked, request, _notes = build()
        finally:
            er.load_run_budget = saved_budget
        check_eq("memo-2c an unreadable run budget: ONE collect, no memory is read or written", (asked, "collect_memo" in request),
                 (1, False))

        # every input a collect depends on, edited: a REAL collect (counter 1)
        truth["ids"] = ["tests/test_mm.py::test_mm_a[1]"]
        write(3, values="[1]")
        asked, ran, third, err, code = mine()
        check_eq("memo-3 a decorator and signature edit (new parametrization): ONE collect, the run launched",
                 (code, asked, ran), (0, 1, 1))
        truth["ids"] = ["tests/test_mm.py::test_mm_a[1]", "tests/test_mm.py::test_mm_a[2]"]
        write(3, values="[1, 2]")
        asked, ran, fourth, err, code = mine()
        check_eq("memo-3 a new value in a literal list: ONE collect, both instances launched", (code, asked, ran), (0, 1, 1))
        write(4, values="[1, 2]")
        asked, ran, fifth, err, code = mine()
        check_eq("memo-3 ... and a body edit after it is free again", (code, asked, ran), (0, 0, 1))
        write(4, source=MM_PARAM.format(values="[1, 2]") + MM_BODY.format(args="(x)", n=4)
              + "\n\ndef test_mm_new():\n    pass\n")
        asked, ran, _req, err, code = mine()
        check_eq("memo-4 a NEW test in the file: ONE collect (the file's skeleton moved)", (code, asked), (0, 1))
        write(4, values="[1, 2]")
        conftest.write_text(conftest_before.decode("utf-8") + "def helper_touched():\n    return 1\n", encoding="utf-8")
        asked, ran, sixth, err, code = mine()
        check_eq("memo-5 an edit of the conftest (any): ONE collect, the run launched", (code, asked, ran), (0, 1, 1))
        write(5, values="[1, 2]")
        asked, ran, _req, err, code = mine()
        check_eq("memo-5 ... and the body edit after it is free (the conftest is in the key, unchanged now)",
                 (code, asked, ran), (0, 0, 1))
        write(6, values="[1, 2]")
        asked, ran, _req, err, code = mine("--again")
        check_eq("memo-6 `--again` collects afresh, whatever is remembered", (code, asked), (0, 1))
        write(7, values="[1, 2]")
        asked, ran, _req, err, code = mine("--cwd", str(ROOT))
        check_eq("memo-6 `--cwd` reads no memory: ONE collect", (code, asked), (0, 1))
        asked, ran, _req, err, code = mine()
        check_eq("memo-6 ... and the plain call after it is free again (nothing but the cwd flag differed)",
                 (code, asked), (0, 0))
        # F-1: a collect made under `--again` / `--cwd` is the NEWEST answer: the next plain call plays IT back, never an
        # older list (the stand moved: the same key, a collect that now answers one parameter more)
        three = [f"tests/test_mm.py::test_mm_a[{n}]" for n in (1, 2, 3)]
        truth["ids"] = three
        write(60, values="[1, 2]")
        asked, ran, again_req, err, code = mine("--again")
        check_eq("memo-6 `--again` after the stand moved: ONE collect, and it writes the memory",
                 (code, asked, (again_req.get("collect_memo") or {}).get("ids")), (0, 1, three))
        write(61, values="[1, 2]")
        asked, ran, plain_req, err, code = mine()
        check_eq("memo-6 ... the next plain call replays the `--again` list (3 parameters), not the older one (2)",
                 (code, asked, (plain_req.get("collect_memo") or {}).get("ids")), (0, 0, three))
        truth["ids"] = three[:2]
        write(62, values="[1, 2]")
        asked, ran, cwd_req, err, code = mine("--cwd", str(ROOT))
        check_eq("memo-6 `--cwd` after the stand moved again: ONE collect, and it writes the memory",
                 (code, asked, (cwd_req.get("collect_memo") or {}).get("ids")), (0, 1, three[:2]))
        write(63, values="[1, 2]")
        asked, ran, plain_req, err, code = mine()
        check_eq("memo-6 ... the next plain call replays the `--cwd` list (2 parameters)",
                 (code, asked, (plain_req.get("collect_memo") or {}).get("ids")), (0, 0, three[:2]))

        # values that may come from the stand: never remembered
        truth["ids"] = ["tests/test_mm.py::test_mm_a[0]", "tests/test_mm.py::test_mm_a[1]"]
        for label, n, text in (("a comprehension", 8, "[n for n in range(2)]"), ("a call", 9, "make_values()"),
                               ("a name", 10, "VALUES")):
            write(n, values=text)
            asked, ran, request, err, code = mine()
            check_eq(f"memo-7 parametrize with {label}: ONE collect", (code, asked), (0, 1))
            write(n + 10, values=text)
            asked, ran, request, err, code = mine()
            check_eq("memo-7 ... and again after a body edit: ONE collect, no memory is written",
                     (code, asked, "collect_memo" in request), (0, 1, False))
        write(30, values="[0, 1]")
        conftest.write_text(conftest_before.decode("utf-8") + "def pytest_generate_tests(metafunc):\n    pass\n",
                            encoding="utf-8")
        for n in (30, 31):
            write(n, values="[0, 1]")
            asked, ran, request, err, code = mine()
            check_eq(f"memo-8 pytest_generate_tests in the conftest, call {n}: ONE collect, no memory",
                     (code, asked, "collect_memo" in request), (0, 1, False))
        conftest.write_bytes(conftest_before)

        # a list gone stale: pytest says `not found`, the NEXT launch collects, and then it is free again
        def manifest(selector: str) -> None:
            write_json(MM_ROOT / "work" / "automation-manifest.json", {"tests": [
                {"case": MM_CASE, "file": "tests/test_mm.py", "selector": selector}]})
        manifest("test_mm_ghost")
        write(40)
        truth["ids"] = ["tests/test_mm.py::test_mm_ghost"]
        asked, ran, stale, err, code = mine()
        check_eq("memo-9 the first list names a test that is not there (a stand fact the key cannot see): "
                 "one collect, pytest's `not found` (exit 4)", (code, asked), (4, 1))
        manifest("test_mm_a")
        truth["ids"] = ["tests/test_mm.py::test_mm_a"]
        write(41)
        asked, ran, healed, err, code = mine()
        check_eq("memo-9 STALE memory is not played back: the next launch collects for real and runs the real id",
                 (code, asked, launches()[-1]), (0, 1, "tests/test_mm.py::test_mm_a"))
        write(42)
        asked, ran, _req, err, code = mine()
        check_eq("memo-9 ... and then it is free again: the stale -> not found -> stale loop is not reachable",
                 (code, asked), (0, 0))
        # F-4: the SAME row (the ghost one) on every side - the stale list is in the memory and the row finds itself in
        # it; pytest says `not found`; without the stale check the next call would replay it (asked 0, exit 4 again)
        extra = MM_BODY.format(args="()", n=50) + "\n\ndef test_mm_c():\n    pass\n"
        manifest("test_mm_ghost")
        truth["ids"] = ["tests/test_mm.py::test_mm_ghost"]
        write(50, source=extra)
        asked, ran, _req, err, code = mine()
        check_eq("memo-9b the ghost row, first call: ONE collect, pytest's `not found` (exit 4)", (code, asked, ran), (4, 1, 1))
        for n in (51, 52):
            write(n, source=extra.replace("assert 50", f"assert {n}"))
            asked, ran, _req, err, code = mine()
            check_eq(f"memo-9b ... call {n - 49}: the same row, the same key, a stale list: ONE collect and a launch again "
                     "(never a replay)", (code, asked, ran), (4, 1, 1))
        manifest("test_mm_a")
        # F-4: the key is the same, the memory holds a list that does not hold the row: the playback is thrown away
        two = MM_BODY.format(args="()", n=1) + "\n\ndef test_mm_b():\n    pass\n"
        write(0, source=two)
        truth["ids"] = ["tests/test_mm.py::test_mm_a"]
        asked, ran, _req, err, code = mine()
        check_eq("memo-9c a new file shape: ONE collect", (code, asked), (0, 1))
        manifest("test_mm_b")
        truth["ids"] = ["tests/test_mm.py::test_mm_b"]
        asked, ran, _req, err, code = mine()
        check_eq("memo-9c same key, a row the remembered list does not hold: the REAL collect runs and its id is launched",
                 (code, asked, launches()[-1]), (0, 1, "tests/test_mm.py::test_mm_b"))
        manifest("test_mm_a")

        # the share of plain calls that still get the speed-up on a test file with literal parameters (measured by the counter)
        truth["ids"] = ["tests/test_mm.py::test_mm_a[1]", "tests/test_mm.py::test_mm_a[2]"]
        counts = []
        for n in range(80, 90):
            write(n, values="[1, 2]")
            asked, ran, _req, err, code = mine()
            counts.append(asked)
        print(f"MEASURED plain calls on a literal-parametrized file: collects per call {counts}; "
              f"{counts.count(0)} of {len(counts)} without a collect (the shape was remembered by the calls above)")
        check_eq("memo-11 ten body edits in a row on literal parameters: no collect at all", counts, [0] * 10)

        # the digest: a repeat of the same request stays a repeat
        plain = {k: v for k, v in healed.items() if k != "collect_memo"}
        check_eq("memo-10 `collect_memo` is not in the digest: the same request with and without it is the same",
                 er.request_digest(dict(plain, collect_memo={"key": "k", "ids": ["a"]})), er.request_digest(plain))
        check("memo-10 ... and another field still moves it",
              er.request_digest(dict(plain, purpose="initial" if plain.get("purpose") != "initial" else "repair_verify"))
              != er.request_digest(plain))
    finally:
        conftest.write_bytes(conftest_before)
        run_suite.probe_runtime = saved_probe
        for name in ("node_ids", "stand_lease", "stand_health"):
            sys.modules.pop(name, None)
    memo_key_battery()
    memo_key_real_pytest_battery()


# F-2: the key against REAL pytest. Each input is a project that a real collect answers differently after ONE edit;
# the real key function must then be "" (not computed) or moved - never the same non-empty key. The new parameter
# is in the list the real collect gives after the edit.
_F2_BODY = "def test_a(p):\n    pass\n"
_F2_FIXTURE = ("import json, os\nimport pytest\nfrom pathlib import Path\n\n\n"
               "@pytest.fixture(params=json.loads(Path('cases.json').read_text()))\ndef p(request):\n    return request.param\n")
_F2_CASES = (
    # name, files before, edit (file -> new text), env after, why the collect moves
    ("P1 fixture params from a JSON file in the test file",
     {"test_x.py": _F2_FIXTURE + "\n\n" + _F2_BODY, "cases.json": "[1]"}, {"cases.json": "[1, 2]"}, None),
    ("P1b the same fixture in the conftest",
     {"conftest.py": _F2_FIXTURE, "test_x.py": _F2_BODY, "cases.json": "[1]"}, {"cases.json": "[1, 2]"}, None),
    ("P2 pytest_plugins, literal params edited in the plugin",
     {"conftest.py": "pytest_plugins = ['plug_data']\n", "test_x.py": _F2_BODY,
      "plug_data.py": "import pytest\n\n\n@pytest.fixture(params=[1])\ndef p(request):\n    return request.param\n"},
     {"plug_data.py": "import pytest\n\n\n@pytest.fixture(params=[1, 2])\ndef p(request):\n    return request.param\n"}, None),
    ("P3 pythonpath = src, a marker imported from src",
     {"pytest.ini": "[pytest]\npythonpath = src\n", "src/pkg/__init__.py": "",
      "src/pkg/data.py": "import pytest\nPARAMS = pytest.mark.parametrize('x', [1])\n",
      "test_x.py": "from pkg.data import PARAMS\n\n\n@PARAMS\ndef test_a(x):\n    pass\n"},
     {"src/pkg/data.py": "import pytest\nPARAMS = pytest.mark.parametrize('x', [1, 2])\n"}, None),
    ("P4 a helper named test*, params=testdata(), its body edited",
     {"test_x.py": "import pytest\n\n\ndef testdata():\n    return [1]\n\n\n@pytest.fixture(params=testdata())\n"
                   "def p(request):\n    return request.param\n\n\n" + _F2_BODY},
     {"test_x.py": "import pytest\n\n\ndef testdata():\n    return [1, 2]\n\n\n@pytest.fixture(params=testdata())\n"
                   "def p(request):\n    return request.param\n\n\n" + _F2_BODY}, None),
    ("P5 params from the environment",
     {"test_x.py": "import os\nimport pytest\n\n\n@pytest.fixture(params=os.environ['MEMO_BROWSERS'].split(','))\n"
                   "def p(request):\n    return request.param\n\n\n" + _F2_BODY}, {}, {"MEMO_BROWSERS": "a,b"}),
    ("P6 parametrize under an alias, the values from a file",
     {"test_x.py": "import json\nimport pytest\nfrom pathlib import Path\n\nP = pytest.mark.parametrize\n\n\n"
                   "@P('x', json.loads(Path('v.json').read_text()))\ndef test_a(x):\n    pass\n", "v.json": "[1]"},
     {"v.json": "[1, 2]"}, None),
    ("P7 literal values, ids= from a file",
     {"test_x.py": "import json\nimport pytest\nfrom pathlib import Path\n\n\n"
                   "@pytest.mark.parametrize('x', [1], ids=json.loads(Path('ids.json').read_text()))\n"
                   "def test_a(x):\n    pass\n", "ids.json": '["one"]'}, {"ids.json": '["uno"]'}, None),
    ("P8 a collection hook in the conftest deselecting by a file",
     {"conftest.py": "from pathlib import Path\n\n\ndef pytest_collection_modifyitems(items):\n"
                     "    gone = Path('gone.txt').read_text().split()\n"
                     "    items[:] = [i for i in items if i.name not in gone]\n",
      "test_x.py": "def test_a():\n    pass\n\n\ndef test_b():\n    pass\n", "gone.txt": "zzz"},
     {"gone.txt": "test_b"}, None),
)


def memo_key_real_pytest_battery() -> None:
    import subprocess
    base = Path(tempfile.mkdtemp(prefix="qa-memo-real-")).resolve()
    runtime = {"runtime_required": False, "runtime_provenance": {}}

    def lay(root: Path, files: dict) -> None:
        for name, text in files.items():
            (root / name).parent.mkdir(parents=True, exist_ok=True)
            (root / name).write_text(text, encoding="utf-8")

    def collected(root: Path, env=None) -> list:
        done = subprocess.run([sys.executable, "-B", "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider"],
                              cwd=root, capture_output=True, text=True, env=dict(os.environ, **(env or {})))
        return sorted(line for line in done.stdout.splitlines() if "::" in line)

    def key_of(root: Path) -> str:
        py = sorted(root.glob("test_x.py"))
        confs = [str(p) for p in root.glob("conftest.py")]
        configs = sorted(str(p) for p in [*root.glob("pytest.ini"), *root.glob("conftest.py")])
        return er._collect_memo_key(["pytest"], root, [str(p) for p in py], confs, [], configs, runtime, project_root=root)
    try:
        for n, (name, files, edit, env_after) in enumerate(_F2_CASES):
            root = base / f"c{n}"
            root.mkdir()
            lay(root, files)
            env_before = {"MEMO_BROWSERS": "a"} if env_after else None
            before_ids, before_key = collected(root, env_before), key_of(root)
            lay(root, edit)
            after_ids, after_key = collected(root, env_after), key_of(root)
            check(f"F-2 {name}: a real collect answers differently after the edit ({before_ids} -> {after_ids})",
                  before_ids != after_ids and bool(before_ids) and bool(after_ids))
            check_eq(f"F-2 {name}: the real key function gives no key (a real collect runs, the new parameter is listed)",
                     (before_key, after_key), ("", ""))
        # controls: a literal edit moves the key; a body edit of a literal-parametrized test does not, and a key exists
        root = base / "ctl"
        root.mkdir()
        lit = "import pytest\n\n\n@pytest.mark.parametrize('x', {v})\ndef test_a(x):\n    {b}\n"
        lay(root, {"test_x.py": lit.format(v="[1]", b="pass")})
        first_key, first_ids = key_of(root), collected(root)
        lay(root, {"test_x.py": lit.format(v="[1]", b="assert x == 1")})
        check_eq("F-2 control: a body edit of a literal-parametrized test: the same non-empty key, the same real collect",
                 (bool(first_key), key_of(root) == first_key, collected(root) == first_ids), (True, True, True))
        lay(root, {"test_x.py": lit.format(v="[1, 2]", b="pass")})
        check("F-2 control: a literal value edit moves the key, and the real collect moves with it",
              key_of(root) not in ("", first_key) and collected(root) != first_ids)
    finally:
        shutil.rmtree(base, ignore_errors=True)


def memo_key_battery() -> None:
    """`_collect_memo_key` and `_memo_of_jobs` on their own: what moves the key, what makes it ''."""
    base = Path(tempfile.mkdtemp(prefix="qa-memo-key-")).resolve()
    try:
        (base / "tests").mkdir()
        (base / "lib").mkdir()
        test = base / "tests" / "test_k.py"
        helper = base / "lib" / "data.py"
        conf = base / "tests" / "conftest.py"
        helper.write_text("VALUES = [1, 2]\n", encoding="utf-8")
        conf.write_text("# c\n", encoding="utf-8")
        runtime = {"runtime_required": True, "runtime_provenance": {"observed_runtime_identity": "build-1"}}

        def put(text: str) -> None:
            test.write_text(text, encoding="utf-8")

        def key(*, argv=("pytest",), cwd=base, files=None, runtime=runtime, deps=(), configs=()):
            return er._collect_memo_key(list(argv), cwd, [str(test)] if files is None else files, [str(conf)],
                                        list(deps), list(configs), runtime, project_root=base)

        source = 'import pytest\nfrom lib.data import VALUES\n\n\n@pytest.mark.parametrize("x", [1, 2])\ndef test_a(x):\n    {body}\n'
        put(source.format(body="assert x"))
        first = key()
        check("key-1 a key is computed for a plain file", bool(first) and len(first) == 64)
        put(source.format(body="assert x == x  # edited"))
        check_eq("key-2 a body edit does not move the key", key(), first)
        put(source.replace("[1, 2]", "[1, 2, 3]").format(body="assert x"))
        check("key-3 a literal list edit moves it", key() not in ("", first))
        put(source.replace("(x)", "(x, tmp_path)").format(body="assert x"))
        check("key-3 a new argument of the test moves it", key() not in ("", first))
        put(source.replace("def test_a", "@pytest.mark.slow\ndef test_a").format(body="assert x"))
        check("key-3 a new decorator moves it", key() not in ("", first))
        put(source.format(body="assert x") + "\n\ndef test_b():\n    pass\n")
        check("key-3 a new test moves it", key() not in ("", first))
        put(source.format(body="assert x"))
        check_eq("key-3 ... and the key comes back with the bytes", key(), first)
        conf.write_text("# c edited\n", encoding="utf-8")
        check("key-4 the conftest, any edit, moves it", key() not in ("", first))
        conf.write_text("# c\n", encoding="utf-8")
        helper.write_text("VALUES = [1, 2, 3]\n", encoding="utf-8")
        check("key-4 an imported project module moves it", key() not in ("", first))
        helper.write_text("VALUES = [1, 2]\n", encoding="utf-8")
        ini = base / "pytest.ini"
        ini.write_text("[pytest]\naddopts = -q\n", encoding="utf-8")
        with_ini = key(configs=[str(ini)])
        ini.write_text("[pytest]\naddopts = -v\n", encoding="utf-8")
        check("key-4 a configuration file moves it", key(configs=[str(ini)]) not in ("", with_ini))
        dep = base / "requirements.txt"
        dep.write_text("a==1\n", encoding="utf-8")
        before_dep = key(deps=[str(dep)])
        dep.write_text("a==2\n", encoding="utf-8")
        check("key-4 a dependency file moves it", key(deps=[str(dep)]) not in ("", before_dep))
        check("key-5 another argv moves it", key(argv=("pytest", "-m", "x")) not in ("", first))
        check("key-5 another run directory moves it", key(cwd=base / "tests") not in ("", first))
        check("key-5 another stand identity moves it",
              key(runtime={"runtime_provenance": {"observed_runtime_identity": "build-2"}}) not in ("", first))
        old = os.environ.get("PYTEST_ADDOPTS")
        os.environ["PYTEST_ADDOPTS"] = "-k something"
        try:
            check("key-5 PYTEST_ADDOPTS moves it", key() not in ("", first))
        finally:
            if old is None:
                os.environ.pop("PYTEST_ADDOPTS", None)
            else:
                os.environ["PYTEST_ADDOPTS"] = old
        # "": not computed
        for label, text in (("a call", 'make()'), ("a name", "VALUES"), ("a comprehension", "[n for n in range(3)]"),
                            ("pytest.param", "[pytest.param(1, id='one')]")):
            put(source.replace("[1, 2]", text).format(body="assert x"))
            check_eq(f"key-6 parametrize with {label} gives ''", key(), "")
        put(source.format(body="pass") + "\n\ndef pytest_generate_tests(metafunc):\n    pass\n")
        check_eq("key-6 pytest_generate_tests in the test file gives ''", key(), "")
        put(source.format(body="assert x"))
        conf.write_text("def pytest_generate_tests(metafunc):\n    pass\n", encoding="utf-8")
        check_eq("key-6 pytest_generate_tests in the conftest gives ''", key(), "")
        conf.write_text("# c\n", encoding="utf-8")
        put("def test_a(:\n")
        check_eq("key-6 a file that does not parse gives ''", key(), "")
        put(source.format(body="assert x"))
        check_eq("key-6 a test file that is not there gives ''", key(files=[str(base / "tests" / "gone.py")]), "")
        check_eq("key-6 no test file at all gives ''", key(files=[]), "")
        check_eq("key-6 a stand that was not observed gives ''",
                 key(runtime=dict(runtime, runtime_observed=False)), "")
        check_eq("key-6 an identity that was not read, on a stand that is required, gives ''",
                 key(runtime={"runtime_required": True, "runtime_provenance": {}}), "")
        check("key-6 ... a stand that is not required needs no identity",
              bool(key(runtime={"runtime_required": False, "runtime_provenance": {}})))
        bad = base / "lib" / "broken.py"
        bad.write_text("def (:\n", encoding="utf-8")
        put("from lib.broken import x\n" + source.format(body="assert x"))
        check_eq("key-6 an imported module that does not parse gives ''", key(), "")
        put(source.format(body="assert x"))

        # F-2 neighbours: what the key reads besides the code
        init = base / "lib" / "__init__.py"
        init.write_text("X = 1\n", encoding="utf-8")
        with_init = key()
        init.write_text("X = 2\n", encoding="utf-8")
        check("key-7 the `__init__.py` of an imported package moves it", key() not in ("", with_init))
        init.unlink()
        before_tests_init = key()
        (base / "tests" / "__init__.py").write_text("", encoding="utf-8")
        check("key-7 a new `tests/__init__.py` moves it", key() not in ("", before_tests_init))
        (base / "tests" / "__init__.py").unlink()
        check_eq("key-7 ... and the key comes back without it", key(), before_tests_init)
        check_eq("key-7 a plugin named in argv (`-p x`) gives ''", key(argv=("pytest", "-p", "myplug")), "")
        check_eq("key-7 a plugin named in argv (`-pmyplug`) gives ''", key(argv=("pytest", "-pmyplug")), "")
        check("key-7 `-p no:cacheprovider` only switches one off: a key", bool(key(argv=("pytest", "-p", "no:cacheprovider"))))
        check_eq("key-7 a `-c` configuration file in argv gives ''", key(argv=("pytest", "-c", "other.ini")), "")
        check_eq("key-7 `--pyargs` gives ''", key(argv=("pytest", "--pyargs", "pkg")), "")
        ini.write_text("[pytest]\npythonpath = src\n", encoding="utf-8")
        check_eq("key-7 `pythonpath` in the configuration gives '' (the modules may live where the key does not look)",
                 key(configs=[str(ini)]), "")
        ini.write_text("[pytest]\naddopts = -q\n", encoding="utf-8")
        for label, text in (("pytest_plugins", "pytest_plugins = ['x']\n"), ("a collection hook", "def pytest_collection_modifyitems(items):\n    pass\n"),
                            ("sys.path", "import sys\nsys.path.insert(0, 'src')\n"), ("a dynamic import", "import importlib\nm = importlib.import_module('x')\n"),
                            ("an aliased parametrize", "import pytest\nP = pytest.mark.parametrize\n"),
                            ("getattr of parametrize", "import pytest\nP = getattr(pytest.mark, 'parametrize')\n"),
                            ("a fixture with non-literal params", "import pytest\n\n\n@pytest.fixture(params=make())\ndef p(request):\n    pass\n"),
                            ("ids that are not a literal", "import pytest\n\n\n@pytest.mark.parametrize('x', [1], ids=make())\ndef test_q(x):\n    pass\n")):
            conf.write_text(text, encoding="utf-8")
            check_eq(f"key-7 {label} in the conftest gives ''", key(), "")
        conf.write_text("# c\n", encoding="utf-8")
        # a `test*` function that is a fixture or is referenced is a helper: its body is part of the key
        helper_src = "import pytest\n\n\ndef testdata():\n    return {v}\n\n\ndef test_a():\n    assert testdata()\n"
        put(helper_src.format(v="[1]"))
        used = key()
        put(helper_src.format(v="[1, 2]"))
        check("key-7 a referenced `test*` helper: its body edit moves the key", key() not in ("", used))
        fx_src = "import pytest\n\n\n@pytest.fixture\ndef test_fx():\n    return {v}\n\n\ndef test_a(test_fx):\n    pass\n"
        put(fx_src.format(v="1"))
        used = key()
        put(fx_src.format(v="2"))
        check("key-7 a `test*` fixture: its body edit moves the key", key() not in ("", used))
        put(source.format(body="assert x"))

        # `_memo_of_jobs`
        def job(job_id, key_, *, purpose="repair_verify", ids=("a",), memo=True, **more):
            request = {"purpose": purpose, **({"collect_memo": {"key": key_, "ids": list(ids)}} if memo else {})}
            return dict({"job_id": job_id, "request": request}, **more)
        check_eq("jobs-1 no job: None", er._memo_of_jobs([], "k", base), None)
        check_eq("jobs-1 an empty key: None", er._memo_of_jobs([job("j1", "k")], "", base), None)
        check_eq("jobs-1 an old record with no collect_memo: None", er._memo_of_jobs([job("j1", "k", memo=False)], "k", base), None)
        check_eq("jobs-1 another key: None", er._memo_of_jobs([job("j1", "other")], "k", base), None)
        check_eq("jobs-2 the newest job with the key decides",
                 er._memo_of_jobs([job("j1", "k", ids=("old",)), job("j2", "k", ids=("new",))], "k", base), ("j2", ["new"]))
        check_eq("jobs-2 a red probe is never the source",
                 er._memo_of_jobs([job("j1", "k"), job("probe", "k", purpose="red_probe", ids=("clone",))], "k", base),
                 ("j1", ["a"]))
        check_eq("jobs-2 an empty list is no answer", er._memo_of_jobs([job("j1", "k", ids=())], "k", base), None)
        summary = base / "summary.json"
        summary.write_text(json.dumps({"exit_code": 4, "blocked": "node_id_mismatch"}), encoding="utf-8")
        check_eq("jobs-3 a job whose run said `not found` (node_id_mismatch) is a stale list: None, no fallback to an older one",
                 er._memo_of_jobs([job("j0", "k"), job("j1", "k", summary=str(summary))], "k", base), None)
        summary.write_text(json.dumps({"exit_code": 127}), encoding="utf-8")
        check_eq("jobs-3 a job that never ran a test (failed_to_launch, no totals) is stale too",
                 er._memo_of_jobs([job("j1", "k", summary=str(summary), status="failed_to_launch")], "k", base), None)
        summary.write_text(json.dumps({"exit_code": 0, "totals": {"tests": 1}}), encoding="utf-8")
        check_eq("jobs-3 a run that ran tests keeps its list",
                 er._memo_of_jobs([job("j1", "k", summary=str(summary), status="completed")], "k", base), ("j1", ["a"]))
        check_eq("jobs-3 an unreadable summary is not a reason to refuse the list (nothing proves it stale)",
                 er._memo_of_jobs([job("j1", "k", summary=str(base / "nope.json"))], "k", base), ("j1", ["a"]))
    finally:
        shutil.rmtree(base, ignore_errors=True)


def collect_only_battery() -> None:
    """t-2181 PC-4 (B6): `--collect-only` takes ONE collect (`collect_files`) of the files `--tests` names and prints the `runs[]`
    row `kind: collect`; a partial collect (a file failed to import) says `partial: true` and lists the broken file; neither is a
    run - nothing is launched, no run block, no job - and a collect that gave no id is a refusal, never a row."""
    real = real_node_ids()
    saved = run_suite.collect_files
    seen = []
    argv = ("--task", TASK, "--collect-only", "--tests", "tests/test_a.py::test_green", "tests/test_a.py::test_red", "--",
            PY, str(ROOT / "fake" / "pytest"))
    before = (len(launches()), len(list((TASK_ROOT / "work" / "run-blocks").glob("*.json"))))
    try:
        def full(cmd, cwd, files, cfg, notes=None):
            seen.append(list(files))
            return ["tests/test_a.py::test_green", "tests/test_a.py::test_red"]
        run_suite.collect_files = full
        code, out, _err = call(*argv)
        row = last_json(out).get("runs_row", {})
        check_eq("collect-only: exit 0 and a row of kind collect, the files named once, no partial key",
                 (code, row.get("kind"), seen, "partial" in row), (0, "collect", [["tests/test_a.py"]], False))
        check_eq("collect-only: the row's scope is the collected node ids", row.get("scope"),
                 ["tests/test_a.py::test_green", "tests/test_a.py::test_red"])

        def partial(cmd, cwd, files, cfg, notes=None):
            raise real.CollectError("1 file(s) could not be collected", "head", kind="partial",
                                    ids=["tests/test_a.py::test_green"], broken=[{"path": "tests/test_b.py", "head": "ImportError"}])
        run_suite.collect_files = partial
        code, out, _err = call(*argv)
        row = last_json(out).get("runs_row", {})
        check_eq("collect-only: a partial collect is `partial: true`, its healthy ids and the broken file named",
                 (code, row.get("kind"), row.get("partial"), row.get("scope"), row.get("broken")),
                 (0, "collect", True, ["tests/test_a.py::test_green"], ["tests/test_b.py"]))
        check_eq("collect-only: a partial collect is never a run: the status says so, no `results`, no run_witness key",
                 (last_json(out).get("status"), "results" in row, "run_witness" in row), ("collected_partial", False, False))

        def nothing(cmd, cwd, files, cfg, notes=None):
            raise real.CollectError("collect timed out after 180s", kind="timeout")
        run_suite.collect_files = nothing
        code, out, err = call(*argv)
        check_eq("collect-only: a collect that gave nothing is exit 2 and no row", (code, "runs_row" in out), (2, False))
        check_in("collect-only: and the refusal says what to do", "run --collect-only again", err)
        run_suite.collect_files = lambda *a, **k: []
        code, out, err = call(*argv)
        check_eq("collect-only: a collect that listed no id is no evidence: exit 2", (code, "runs_row" in out), (2, False))
        code, _out, _err = call("--task", TASK, "--collect-only", "--tests", "tests/test_a.py::test_green")
        check_eq("collect-only: without the test command it is a usage error (exit 2)", code, 2)
    finally:
        run_suite.collect_files = saved
    check_eq("collect-only: nothing was launched and no run block was written",
             (len(launches()), len(list((TASK_ROOT / "work" / "run-blocks").glob("*.json")))), before)


def main() -> None:
    os.environ["CLAUDE_PROJECT_DIR"] = str(ROOT)
    os.environ["QA_FACTORY_SKIP_DASHBOARD_REFRESH"] = "1"
    setup_project()
    try:
        # --- 1. error_head ----------------------------------------------------------------
        log_text = ("collected 0 items\nERROR: not found: tests/test_a.py::test_x[buffer-R3]\n"
                    "(no match in any of [<Module test_a.py>])\nE   ModuleNotFoundError: No module named 'x'\n"
                    "usage: pytest [options]\nplain line\nImportError while importing test module\n")
        head = run_suite.error_head(log_text)
        check_eq("error_head keeps ERROR, E, usage and import lines in order",
                 [line.split(":")[0].split()[0] for line in head], ["ERROR", "E", "usage", "ImportError"])
        check("error_head is capped at 25 lines", len(run_suite.error_head("ERROR x\n" * 80)) == 25)
        long_head = run_suite.error_head("\n".join("ERROR " + "y" * 400 for _ in range(20)))
        check("error_head is capped at 2500 bytes",
              sum(len(line.encode()) + 1 for line in long_head) <= 2500 and len(long_head) >= 6)
        check("a pytest usage error is a run in which nothing ran", run_suite.nothing_ran({"exit_code": 4}))
        check("zero collected tests is a run in which nothing ran",
              run_suite.nothing_ran({"exit_code": 0, "totals": {"tests": 0}}))
        check("a red run is not", not run_suite.nothing_ran({"exit_code": 1, "totals": {"tests": 2}}))
        check("a timeout is not", not run_suite.nothing_ran({"exit_code": 124}))

        # --- 3. --mine: refusals are plain sentences ------------------------------------------
        absent_modules()
        write_json(TASK_ROOT / "state" / "controller.json", controller(status="accepted"))
        code, out, _ = call("--mine", "TC-001")
        check_eq("--mine with no active dispatch exits 2", code, 2)
        check_in("and says so in a sentence", "no active dispatch", last_json(out).get("error", ""))
        check_eq("nothing was launched", launches(), [])
        write_json(TASK_ROOT / "state" / "controller.json", controller())
        code, out, _ = call("--mine", "TC-009")
        check_eq("--mine with a case outside the dispatch scope exits 2", code, 2)
        refusal = last_json(out).get("error", "")
        check_in("the refusal names the case and the scope", "TC-009 is outside its scope", refusal)
        check_in("it does not blame the role's test", "nothing is wrong with your test", refusal)
        check_in("it names the person's way through", "waiver.py", refusal)
        check_eq("still nothing launched", launches(), [])

        # --- 3. --mine: the first run of a story, built from config alone ---------------------
        code, out, err = call("--mine", "TC-001")
        summary = last_json(out)
        check_eq("--mine TC-001 runs the test and exits 0", code, 0)
        check_eq("the run passed", summary.get("execution_status"), "passed")
        check_eq("the launched node id comes from the manifest", launches()[-1:], ["tests/test_a.py::test_green"])
        requests = sorted((TASK_ROOT / "work" / "requests").glob("mine-*.json"))
        check_eq("the request is written under work/requests/", len(requests), 1)
        built = json.loads(requests[0].read_text(encoding="utf-8"))
        check_eq("dispatch id comes from controller.json", built["dispatch_id"], "S5-qa-automator-1")
        check_eq("revision comes from controller.json", built["revision"], "41")
        check_eq("a first run is `initial`", built["purpose"], "initial")
        check_eq("the instance id is the manifest's", built["selected_instance_ids"], ["test_green"])
        check_eq("report_test_id is spelled the way the junit report spells it",
                 built["instance_contracts"]["test_green"]["report_test_id"], "tests.test_a::test_green")
        check_eq("pinned case versions travel with the instance",
                 built["instance_contracts"]["test_green"]["case_version_links"],
                 [{"case_id": "TC-001", "version": "cv_1"}])
        check("the conftest next to the test is fingerprinted",
              any(r["path"].endswith("conftest.py") and r["kind"] == "helper_files" for r in built["fingerprint_files"]))
        check_eq("provenance is what the configured probe printed",
                 built["runtime_provenance"]["observed_runtime_identity"], "build-1")
        blocks = list((TASK_ROOT / "work" / "run-blocks").glob("*.json"))
        block = json.loads(blocks[-1].read_text(encoding="utf-8")) if blocks else {}
        check_eq("the immutable run block matched its reporter row",
                 [(r["instance_id"], r["status"], r["report_matched"]) for r in block.get("results", [])],
                 [("test_green", "passed", True)])
        check_in("stderr names the request file", "MINE: ", err)

        # a green run over the same bytes is the same run; `--again` no longer repeats it (the run
        # budget, D-0018): the only door for a repeat is a person's recorded word
        before = len(launches())
        code, out, _ = call("--mine", "TC-001")
        check_eq("a second --mine over unchanged green bytes is reused", last_json(out).get("status"), "reused")
        check("its answer is brief, not the whole job record", "request" not in last_json(out))
        check_eq("and launches nothing", len(launches()), before)
        requests_before = len(list((TASK_ROOT / "work" / "requests").glob("mine-*.json")))
        code, out, err = call("--mine", "TC-001", "--again")
        check_eq("--again no longer launches it", len(launches()), before)
        check_eq("and the answer is still exit 0, `reused`", (code, last_json(out).get("status")), (0, "reused"))
        check_in("the answer says `--again` repeats nothing", "--again", last_json(out).get("words", ""))
        check_eq("and writes no request", len(list((TASK_ROOT / "work" / "requests").glob("mine-*.json"))),
                 requests_before)
        RUN_BUDGET_WORD = {"stage": "S5", "match": "already run on these bytes",
                           "decision": "the fixture behind it changed; run it again", "at": "now"}
        write_json(TASK_ROOT / "pipeline.json", {"stages": {"S5": {"status": "running"}},
                                                 "stage_overrides": [RUN_BUDGET_WORD]})
        code, out, err = call("--mine", "TC-001")
        check_eq("a person's recorded word launches the repeat", len(launches()), before + 1)
        check_in("and the note repeats the word", "the fixture behind it changed", err)
        again = json.loads(sorted((TASK_ROOT / "work" / "requests").glob("mine-*.json"),
                                  key=lambda p: p.stat().st_mtime)[-1].read_text(encoding="utf-8"))
        check_eq("a rerun of an instance that already ran is repair_verify", again["purpose"], "repair_verify")
        check("under an idempotency key of its own", again["idempotency_key"] != built["idempotency_key"])
        write_json(TASK_ROOT / "pipeline.json", {"stages": {"S5": {"status": "running"}}})

        # a selector written for people expands to one instance per test
        code, out, _ = call("--mine", "TC-002")
        summary = last_json(out)
        check_eq("a run with a failing test exits 1", code, 1)
        check_eq("`test_red | test_green[p1|p2]` is three node ids", launches()[-1].split(),
                 ["tests/test_a.py::test_red", "tests/test_a.py::test_green[p1]", "tests/test_a.py::test_green[p2]"])
        check_eq("the summary carries the purpose", summary.get("purpose"), "initial")
        check_eq("and the environment of the request", summary.get("environment"), "localhost")
        before = len(launches())
        code, out, _ = call("--mine", "TC-002")
        check_eq("a run that did NOT pass is never answered with `duplicate`", len(launches()), before + 1)

        # the manifest names only a file: the case marker in the source decides
        code, out, err = call("--mine", "TC-003")
        check_eq("a file-only manifest entry runs the test the source marks with the case",
                 launches()[-1], "tests/test_a.py::test_marked")
        check_in("and says what it chose", "test_marked", err)
        code, out, _ = call("--mine", "TC-001", "--node-id", "tests/test_a.py::test_other", "--again")
        check_eq("--node-id names the test for one case", launches()[-1], "tests/test_a.py::test_other")

        # --- 2. --detail under an active dispatch, both spellings, no test executed -----------
        before = len(launches())
        red_job = next(j for j in er.JobStore(TASK_ROOT / "state" / "execution-jobs").jobs()
                       if "test_red" in j["request"]["selected_instance_ids"])
        label = f"{red_job['request']['purpose']}-{red_job['job_id']}"
        code, out, _ = call("--task", TASK, "--label", label, "--detail", "test_red")
        check_eq("--task --label --detail answers under an active dispatch", code, 0)
        check_in("with the failure text of the typed run", "trace of test_red", out)
        red_request = next(p for p in (TASK_ROOT / "work" / "requests").glob("mine-*TC-002*.json"))
        code, out, _ = call("--request", red_request, "--detail", "test_red")
        check_eq("--request FILE --detail answers instead of printing the duplicate job", code, 0)
        check_eq("with status ok", last_json(out).get("status"), "ok")
        fresh = json.loads(red_request.read_text(encoding="utf-8"))
        fresh["idempotency_key"] = "a-key-nobody-has-used"
        write_json(ROOT / "next-request.json", fresh)
        code, out, _ = call("--request", ROOT / "next-request.json", "--detail", "test_red")
        check_eq("a request with a FRESH idempotency key still finds the last run of its instances", code, 0)
        code, out, _ = call("--mine", "TC-002", "--detail", "test_red")
        check_eq("--mine CASE --detail reads the last run of the case", last_json(out).get("status"), "ok")
        check_eq("no spelling of --detail executed a test", len(launches()), before)
        check("and none of them began a job under the fresh key",
              er.JobStore(TASK_ROOT / "state" / "execution-jobs").read("a-key-nobody-has-used") is None)

        # --- 1. error_head in the summary of a run in which nothing ran ----------------------
        code, out, err = call("--mine", "TC-001", "--node-id", "tests/test_a.py::test_ghost")
        summary = last_json(out)
        check_eq("pytest's exit 4 is the run's exit code", code, 4)
        check_in("the summary names the cause", "ERROR: not found", " ".join(summary.get("error_head") or []))
        check_eq("K-R1 live: the summary says pytest's exit 4 means nothing was executed (the runner row's fact)",
                 (summary.get("exit_means_not_executed"), "exit_note" in summary), (True, False))
        stored = json.loads((ROOT / summary["summary_path"]).read_text(encoding="utf-8"))
        check("error_head is in the stored summary too", bool(stored.get("error_head")))
        # B-K3 (HF2-10): the ids were not proven before the launch (node_ids is absent here, and an `--node-id` without
        # `[...]` is never collected), so the run's own `not found` is the answer - `node_id_mismatch`, not executed.
        check_eq("M-B3: --node-id ghost after an unreadable collect: node_id_mismatch, not executed, never passed",
                 (summary.get("blocked"), summary.get("execution_status"), summary.get("missing")),
                 ("node_id_mismatch", "not_executed", [{"asked": "tests/test_a.py::test_ghost", "nearest": []}]))
        check_in("B-K3: the summary names the id and the door (FR-1, FR-2)", "tests/test_a.py::test_ghost", summary.get("hint", ""))
        check_in("B-K3: ... the door is the right id from the source, where it is recorded", "correct it where it is recorded",
                 summary.get("hint", ""))
        check_eq("B-K3: the stored summary says the same", (stored.get("blocked"), stored.get("execution_status")),
                 ("node_id_mismatch", "not_executed"))
        ghost_job = next(j for j in er.JobStore(TASK_ROOT / "state" / "execution-jobs").jobs()
                         if any("ghost" in t for ts in j["request"]["command"]["selector_args"].values() for t in ts))
        check_eq("B-E5: the job of that run is `not_executed`, a key spent and not a result (no pass, no fail)",
                 (ghost_job.get("status"), ghost_job.get("execution_status")), ("completed", "not_executed"))
        code, out, _ = call("--task", TASK, "--label", summary["label"], "--detail", "test_ghost")
        check_in("--detail of such a run hands over the cause instead of `read the log`",
                 "ERROR: not found", out)

        # --- 4. node ids ---------------------------------------------------------------------
        # HF2-10, by design: the keys below used to read the respelled id from the runner's SECOND collect
        # (`check_request`). The respelling now comes from the ONE collect the build took (`_spell_as_collected`), so
        # nobody collects twice; the id the build could not respell is matched by `node_ids.match` against the SAME list.
        events = fake_modules(collected=["tests/test_a.py::test_green[chromium-p1]"])
        write_json(TASK_ROOT / "work" / "automation-manifest.json", {"tests": [
            {"case": "TC-001", "file": "tests/test_a.py", "selector": "test_green[p1]"}]})
        code, out, err = call("--mine", "TC-001")
        summary = last_json(out)
        asked_argv = next(e for e in events if e[0] == "collect")[1]
        check("the collect command carries no node id and no report flag",
              not any("::" in a or "junit" in a for a in asked_argv))
        check_eq("B-K1: one collect, no second check, no second match",
                 [e[0] for e in events if e[0] in ("collect", "check_request", "match")], ["collect"])
        check_eq("the resolved id is what is launched", launches()[-1], "tests/test_a.py::test_green[chromium-p1]")
        check_in("the correction is said as a note of the build", "is collected as [chromium-p1]", err)
        check_eq("and the run needed no id check: no node-id note in the summary", summary.get("node_id_notes"), None)
        blocks = sorted((TASK_ROOT / "work" / "run-blocks").glob("*.json"), key=lambda p: p.stat().st_mtime)
        rows = json.loads(blocks[-1].read_text(encoding="utf-8"))["results"]
        check_eq("the reporter row follows the real spelling, so the instance is matched",
                 [(r["test_id"], r["report_matched"]) for r in rows],
                 [("tests.test_a::test_green[chromium-p1]", True)])

        before, jobs_before = len(launches()), len(er.JobStore(TASK_ROOT / "state" / "execution-jobs").jobs())
        # HF2-10, by design: an id with `[...]` is checked against the ONE collect before the launch (a missing one is
        # refused, `nearest` named, no key spent, ONE collect); an id without `[...]` in an existing file is not
        # collected - the run answers (see the B-K2/B-K3 battery below).
        events = fake_modules(collected=["tests/test_a.py::test_green[chromium-p1]", "tests/test_a.py::test_red"])
        code, out, _ = call("--mine", "TC-001", "--node-id", "tests/test_a.py::test_gone[x]")
        answer = last_json(out)
        check_eq("a missing node id exits 2", code, 2)
        check_eq("with status node_id_mismatch", answer.get("status"), "node_id_mismatch")
        check_eq("and the missing rows", answer.get("missing")[0]["asked"], "tests/test_a.py::test_gone[x]")
        check("and `nearest` names the collected ids", bool(answer.get("missing")[0]["nearest"]))
        check_eq("nothing is launched", len(launches()), before)
        check_eq("and no idempotency key is spent",
                 len(er.JobStore(TASK_ROOT / "state" / "execution-jobs").jobs()), jobs_before)
        check_eq("M-B2: a parsed collect missing an id refuses node_id_mismatch before launch, collect called once",
                 ([e[0] for e in events if e[0] == "collect"], [e[0] for e in events if e[0] == "check_request"]),
                 (["collect"], []))
        write_json(ROOT / "qa-factory" / "config.json",
                   dict(config(), execution=dict(config()["execution"], verify_node_ids=False)))
        # From here to the `--mine` helpers below, the calls that used `--again` to make a green
        # instance run once more are those of a person's standing word (the budget's only door
        # for a repeat); the rest of what each one proves is unchanged.
        write_json(TASK_ROOT / "pipeline.json", {"stages": {"S5": {"status": "running"}},
                                                 "stage_overrides": [RUN_BUDGET_WORD]})
        code, out, _ = call("--mine", "TC-001", "--node-id", "tests/test_a.py::test_other", "--again")
        check_eq("execution.verify_node_ids: false skips the check", len(launches()), before + 1)

        # --- 5. stand lease --------------------------------------------------------------------
        write_json(ROOT / "qa-factory" / "config.json", config(parallel=False))
        events = fake_modules()
        code, out, _ = call("--mine", "TC-001", "--again")
        summary = last_json(out)
        held = [e for e in events if e[0] == "hold"]
        check_eq("run.parallel false takes the stand lease once", len(held), 1)
        check_eq("for the environment of the request, with the configured wait", held[0][2:], ("localhost", 7))
        check_eq("the wait is in the summary", summary.get("stand_waited_s"), 3)
        check_eq("with what it queued behind", (summary.get("stand_lease") or {}).get("queued_behind"), "other-job")
        check("the lease is released after the run", ("released", held[0][1]) in events)
        before, jobs_before = len(launches()), len(er.JobStore(TASK_ROOT / "state" / "execution-jobs").jobs())
        fake_modules(busy=True)
        code, out, _ = call("--mine", "TC-001", "--again")
        answer = last_json(out)
        check_eq("a busy stand exits 3", code, 3)
        check_eq("with status stand_busy", answer.get("status"), "stand_busy")
        check_eq("and the holder", (answer.get("holder") or {}).get("job_id"), "other-job")
        check_eq("nothing is launched", len(launches()), before)
        check_eq("and no job is begun", len(er.JobStore(TASK_ROOT / "state" / "execution-jobs").jobs()), jobs_before)
        events = fake_modules()
        code, out, _ = call("--mine", "TC-001", "--again", "--purpose", "red_probe", "--cwd", ROOT)
        check_eq("a red probe takes the lease too", len([e for e in events if e[0] == "hold"]), 1)
        before = len(launches())
        code, out, _ = call("--mine", "TC-001", "--again", "--purpose", "red_probe")
        answer = last_json(out)
        check_eq("a red probe with no directory is refused although ordinary runs are on record",
                 (code, answer.get("status")), (2, "mine_refused"))
        check_in("the refusal names --cwd, the option that takes the exact sandbox directory", "--cwd", answer.get("error", ""))
        check_in("and names the option that takes a clone", "--sandbox-root", answer.get("error", ""))
        check_eq("nothing was launched by the refused probe", len(launches()), before)
        write_json(ROOT / "qa-factory" / "config.json", config(parallel=True))
        events = fake_modules()
        call("--mine", "TC-001", "--again")
        check_eq("a parallel stand takes no lease", [e for e in events if e[0] == "hold"], [])

        # --- 6. stand health -------------------------------------------------------------------
        signal = {"signal": "stand_suspect", "reason": "same_failure", "evidence": ["TC-001", "TC-002"],
                  "sentence": "3 different cases failed the same way in a row; the stand is suspect"}
        events = fake_modules(signal=signal)
        code, out, err = call("--mine", "TC-001", "--again")
        summary = last_json(out)
        check_eq("the signal is stored in the summary", summary.get("stand_signal"), signal)
        check_in("and printed on its own line", "STAND SIGNAL: 3 different cases", err)
        check_eq("stdout stays one JSON document", len([line for line in out.strip().splitlines() if line]), 1)
        stored = json.loads((ROOT / summary["summary_path"]).read_text(encoding="utf-8"))
        check_eq("the stored summary carries it for the controller", stored.get("stand_signal"), signal)
        check("observe got the task, the purpose and the environment",
              ("observe", TASK, "repair_verify", "localhost") in events)

        # --- all three modules absent: the runner works the way 0.7.7 did ---------------------
        absent_modules()
        write_json(ROOT / "qa-factory" / "config.json", config(parallel=False))
        before = len(launches())
        code, out, _ = call("--mine", "TC-001", "--again")
        check_eq("with node_ids, stand_lease and stand_health missing the run still happens",
                 (code, len(launches())), (0, before + 1))
        summary = last_json(out)
        check("and carries no field of the lease or the health observer",
              not {"stand_signal", "stand_waited_s"} & set(summary))
        check_in("but says the node ids were not verified, and why (B-407 B-run)",
                 "the node_ids module could not be imported", " ".join(summary.get("node_id_notes") or []))

        # --- --mine spells ids from a real collect: rootdir-relative, browser-prefixed --------
        # TP1-15045: `testproject1_test_harness/tests/ui/.../test_x.py::test_fn` was reported as
        # `tests.ui....test_x::test_fn[chromium]`; every hand-written report id missed its row.
        write_json(TASK_ROOT / "work" / "automation-manifest.json", {"tests": [
            {"case": "TC-001", "file": "tests/test_a.py", "selector": "test_green"},
            {"case": "TC-002", "file": "tests/test_a.py", "selector": "test_red[p1]"},
            {"case": "TC-003", "file": "tests/test_a.py", "selector": "test_other"}]})
        seen = []

        def rooted_collect(argv, cwd, files):
            seen.append((list(argv), list(files)))
            return ["test_a.py::test_green[chromium]", "test_a.py::test_red[chromium-p1]",
                    "test_a.py::test_red[chromium-p2]", "test_a.py::test_other[chromium-x]",
                    "test_a.py::test_other[chromium-y]"]
        request, notes, _reuse, verified = er.build_mine_request(
            ROOT, ["TC-001", "TC-002", "TC-003"], cfg=config(), again=True, collect=rooted_collect)
        check_eq("the builder collects once, over the files of the asked tests", [s[1] for s in seen], [["tests/test_a.py"]])
        check("every id was found in a PARSED collect, so nothing checks the ids again (`verified` is a proof, HF2-10)", verified)
        contracts = request["instance_contracts"]
        check_eq("an unparametrized test keeps its instance id and its selector",
                 request["command"]["selector_args"]["test_green"], ["tests/test_a.py::test_green"])
        check_eq("and gets the report id the collect spells, rootdir and browser included",
                 contracts["test_green"]["report_test_id"], "test_a::test_green[chromium]")
        check_eq("a parameter id is respelled to the collected one",
                 request["command"]["selector_args"]["test_red"], ["tests/test_a.py::test_red[chromium-p1]"])
        check_eq("with its report row", contracts["test_red"]["report_test_id"], "test_a::test_red[chromium-p1]")
        check_eq("a function named without parameters becomes one instance per collected parameter",
                 sorted(k for k in contracts if k.startswith("test_other")),
                 ["test_other[chromium-x]", "test_other[chromium-y]"])
        check_in("and the role is told why", "2 parametrized tests", " ".join(notes))
        try:
            er.validate_request(request, ROOT)
            valid = True
        except er.RequestError as exc:
            valid = str(exc)
        check_eq("the built request passes the validator", valid, True)

        def broken_collect(argv, cwd, files):
            raise RuntimeError("collect blew up")
        request, notes, _reuse, verified = er.build_mine_request(
            ROOT, ["TC-001"], cfg=config(), again=True, collect=broken_collect)
        check("a collect that fails never blocks the build; the run checks the ids itself (not verified)",
              not verified and request["instance_contracts"]["test_green"]["report_test_id"] == "tests.test_a::test_green")

        # --- helpers ---------------------------------------------------------------------------
        check_eq("node_report_id keeps classes", er.node_report_id("a/b/test_x.py::TestC::test_fn[p-1]"),
                 "a.b.test_x.TestC::test_fn[p-1]")

        # --- the report id is spelled from pytest's rootdir (TP1-13797) --------------------
        # cwd `test-harness`, node `testproject1_test_harness/tests/...`, pytest.ini in
        # `testproject1_test_harness`: the junit row is `tests....`, and the old spelling matched 0 of 24.
        def fixture(name, files):
            base = ROOT / "rootdir" / name
            for rel, text in files.items():
                (base / rel).parent.mkdir(parents=True, exist_ok=True)
                (base / rel).write_text(text, encoding="utf-8")
            return base
        node = "harness/tests/pkg/test_x.py::test_fn"
        spec = {"harness/tests/pkg/test_x.py": "def test_fn(): pass\n"}
        base = fixture("ini", {**spec, "harness/pytest.ini": "[pytest]\n"})
        check_eq("pytest.ini below the cwd is the rootdir", er.node_report_id(node, base), "tests.pkg.test_x::test_fn")
        check_eq("the same node without a cwd keeps the path as written",
                 er.node_report_id(node), "harness.tests.pkg.test_x::test_fn")
        check_eq("a class stays in the report id",
                 er.node_report_id("harness/tests/pkg/test_x.py::TestC::test_fn[p-1]", base),
                 "tests.pkg.test_x.TestC::test_fn[p-1]")
        base = fixture("none", spec)
        check_eq("no configuration anywhere: relative to the cwd",
                 er.node_report_id(node, base), "harness.tests.pkg.test_x::test_fn")
        base = fixture("above", {"harness/tests/pkg/test_x.py": "def test_fn(): pass\n", "pytest.ini": "[pytest]\n"})
        check_eq("a pytest.ini ABOVE the cwd is not used",
                 er.node_report_id("tests/pkg/test_x.py::test_fn", base / "harness"), "tests.pkg.test_x::test_fn")
        for label, name, text, counts in (
                ("setup.cfg with [tool:pytest]", "setup.cfg", "[tool:pytest]\nx = 1\n", True),
                ("setup.cfg without it", "setup.cfg", "[metadata]\nname = x\n", False),
                ("tox.ini with [pytest]", "tox.ini", "[pytest]\n", True),
                ("tox.ini with [tox] only", "tox.ini", "[tox]\n", False),
                ("pyproject.toml with the pytest table", "pyproject.toml", "[tool.pytest.ini_options]\n", True),
                ("pyproject.toml without it", "pyproject.toml", "[tool.poetry]\n", False)):
            base = fixture("cfg-" + label.replace(" ", "-").replace("[", "").replace("]", "").replace(":", ""),
                           {**spec, "harness/" + name: text})
            check_eq(f"{label} {'counts' if counts else 'does not count'}",
                     er.node_report_id(node, base),
                     "tests.pkg.test_x::test_fn" if counts else "harness.tests.pkg.test_x::test_fn")
        # end to end: a rootdir-relative junit row is matched by the id built from the cwd
        base = fixture("e2e", {"harness/pytest.ini": "[pytest]\n",
                               **{"harness/tests/pkg/test_x.py": "pass\n"}})
        nodes = [f"harness/tests/pkg/test_x.py::TestC::test_{i}" for i in range(3)]
        junit = base / "report.xml"
        junit.write_text('<testsuite tests="3">' + "".join(
            f'<testcase classname="tests.pkg.test_x.TestC" name="test_{i}"/>' for i in range(3)) + "</testsuite>",
            encoding="utf-8")
        request_e2e = {"selected_instance_ids": [f"i{i}" for i in range(3)], "purpose": "initial",
                       "instance_contracts": {f"i{i}": {"report_test_id": er.node_report_id(n, base)}
                                              for i, n in enumerate(nodes)}}
        block = run_suite.build_run_block(request_e2e, run_suite.parse_junitxml(junit), "att-e2e")
        check_eq("every row of a rootdir-relative report is matched",
                 [r["report_matched"] for r in block["results"]], [True, True, True])
        # build_mine_request: an id spelled by the old rule is replaced and named; another one stays
        (ROOT / "tests" / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
        try:
            write_json(TASK_ROOT / "work" / "automation-manifest.json", {"tests": [
                {"case": "TC-001", "file": "tests/test_a.py", "selector": "test_green",
                 "report_test_id": "tests.test_a::test_green"},
                {"case": "TC-002", "file": "tests/test_a.py", "selector": "test_red",
                 "report_test_id": "framework::own-id"}]})
            request, notes, _reuse, _verified = er.build_mine_request(
                ROOT, ["TC-001", "TC-002"], cfg=config(), again=True, collect=None)
            check_eq("an id written by the old rule gets the rootdir spelling",
                     request["instance_contracts"]["test_green"]["report_test_id"], "test_a::test_green")
            check_in("and the note names it", "test_a::test_green", " ".join(notes))
            check_eq("an id that is neither spelling stays as written",
                     request["instance_contracts"]["test_red"]["report_test_id"], "framework::own-id")
        finally:
            (ROOT / "tests" / "pytest.ini").unlink()
            write_json(TASK_ROOT / "work" / "automation-manifest.json", {"tests": [
                {"case": "TC-001", "file": "tests/test_a.py", "selector": "test_green"},
                {"case": "TC-002", "file": "tests/test_a.py", "selector": "test_red[p1]"},
                {"case": "TC-003", "file": "tests/test_a.py", "selector": "test_other"}]})
        check_eq("expand_selector splits functions and parameters",
                 er.expand_selector("test_a | test_b[x|y] | test_c"), ["test_a", "test_b[x]", "test_b[y]", "test_c"])
        check("`poetry run python -m pytest` is a pytest command",
              er.is_pytest_command(["poetry", "run", "python", "-m", "pytest", "--reruns", "0"]))
        check("`dotnet test` is not", not er.is_pytest_command(["dotnet", "test"]))
        check("a manifest row without parameters is carried by the ids it expands into",
              er.covered_by("test_other", ["test_other[chromium-x]", "test_other[chromium-y]"]))
        check("a row that names its own parameter is itself and nothing else",
              not er.covered_by("test_x[p1]", ["test_x[p2]", "test_x_extra[p1]"]))
        write_json(TASK_ROOT / "pipeline.json", {"stages": {"S5": {"status": "running"}}, "stage_overrides": [
            {"stage": "S5", "match": "outside its scope", "decision": "run TC-009 here", "at": "now"},
            RUN_BUDGET_WORD]})
        write_json(TASK_ROOT / "work" / "automation-manifest.json", {"tests": [
            {"case": "TC-009", "file": "tests/test_a.py", "selector": "test_other"}]})
        write_json(ROOT / "qa-factory" / "config.json", config())
        code, out, err = call("--mine", "TC-009", "--again")
        check_eq("a person's recorded word passes the scope refusal", code, 0)
        check_in("and the note repeats the word", "run TC-009 here", err)

        # --- one run per window, evidence per test function, the resumed dispatch id ---------
        # TP1-15045 window 1: 20 pytest launches for 4 cases. 15 of them ran ONE instance
        # while its neighbours in the same file had never run at all, and the other five were
        # the same tests again because a one-line edit in a neighbour had made the whole file's
        # fingerprint new. Both halves are answered here.
        second_window()
        before = len(launches())
        code, out, _ = call("--task", TASK2, "--mine", "TC-101", "--node-id", "tests/test_b.py::test_one")
        answer = last_json(out)
        check_eq("one instance while its neighbours have never run exits 2", code, 2)
        check_eq("with status run_the_window_first", answer.get("status"), "run_the_window_first")
        check_eq("naming the neighbours with no evidence at all",
                 sorted(answer.get("never_ran") or []), ["test_three", "test_two"])
        check_eq("and the one command that runs them together",
                 answer.get("command"), "run_suite.py --mine TC-101,TC-102")
        check_in("the sentence does not blame the test", "Nothing is wrong with these tests",
                 answer.get("error", ""))
        check_in("and names the person's way through", "waiver.py", answer.get("error", ""))
        check_eq("nothing was launched", len(launches()), before)
        check_eq("and no request was written", len(list((TASK2_ROOT / "work" / "requests").glob("*.json"))), 0)
        write_json(TASK2_ROOT / "pipeline.json", {"stages": {"S5": {"status": "running"}}, "stage_overrides": [
            {"stage": "S5", "match": "run the window first", "decision": "just this one, I am watching",
             "at": "now"}]})
        code, out, err = call("--task", TASK2, "--mine", "TC-101", "--node-id", "tests/test_b.py::test_two")
        check_eq("a person's recorded word passes it", code, 0)
        check_in("and the note repeats the word", "just this one, I am watching", err)
        write_json(TASK2_ROOT / "pipeline.json", {"stages": {"S5": {"status": "running"}}})
        code, out, _ = call("--task", TASK2, "--mine", "TC-101", "--node-id",
                            "tests/test_b.py::test_one", "--purpose", "repair_verify")
        check_eq("--purpose repair_verify runs only what the repair touched",
                 launches()[-1], "tests/test_b.py::test_one")
        code, out, _ = call("--task", TASK2, "--mine", "TC-101,TC-102")
        # The window is ONE pytest call, and (the run budget) it carries only what has no
        # result: test_one and test_two already ran green over these bytes above.
        check_eq("the window itself is ONE pytest call, of the one test with no result",
                 launches()[-1].split(), ["tests/test_b.py::test_three"])
        code, out, err = call("--task", TASK2, "--mine", "TC-101")
        check_eq("a whole case is never answered `run the window first`", code, 0)
        rows = [r for path in sorted((TASK2_ROOT / "work" / "run-blocks").glob("*.json"))
                for r in json.loads(path.read_text(encoding="utf-8"))["results"]]
        shas = {r["instance_id"]: r.get("instance_content_sha") for r in rows}
        check_eq("the run blocks record what each instance itself was over", sorted(shas),
                 ["test_one", "test_three", "test_two"])
        check("and the tests of one file have different fingerprints",
              all(shas.values()) and len(set(shas.values())) == 3)
        before = len(launches())
        code, out, _ = call("--task", TASK2, "--mine", "TC-101")
        check_eq("the same run over unchanged bytes is reused", last_json(out).get("status"), "reused")
        (ROOT / "tests" / "test_b.py").write_text(
            (ROOT / "tests" / "test_b.py").read_text(encoding="utf-8")
            .replace("def test_three():\n    assert True", "def test_three():\n    assert 1 == 1"),
            encoding="utf-8")
        code, out, _ = call("--task", TASK2, "--mine", "TC-101")
        check_eq("an edit to a NEIGHBOUR of the same file leaves this evidence valid",
                 last_json(out).get("status"), "reused")
        check_eq("so nothing ran a second time", len(launches()), before)
        (ROOT / "tests" / "conftest.py").write_text("def shared_client():\n    return 2\n", encoding="utf-8")
        code, out, _ = call("--task", TASK2, "--mine", "TC-101")
        check_eq("an edit to the fixture they share invalidates them and the run happens",
                 len(launches()), before + 1)
        check_eq("a conftest code edit reruns every test under it", launches()[-1],
                 "tests/test_b.py::test_one tests/test_b.py::test_two")
        after_conftest = len(launches())
        (ROOT / "tests" / "conftest.py").write_text(
            "# a note about the client\ndef shared_client():\n    return 2\n", encoding="utf-8")
        code, out, _ = call("--task", TASK2, "--mine", "TC-101")
        check_eq("a COMMENT-only conftest edit launches nothing",
                 (last_json(out).get("status"), len(launches())), ("reused", after_conftest))
        write_json(TASK2_ROOT / "pipeline.json", {"stages": {"S5": {"status": "running"}},
                                                  "stage_overrides": [RUN_BUDGET_WORD]})
        code, out, err = call("--task", TASK2, "--mine", "TC-101",
                              "--dispatch", "S5-qa-automator-8", "--again")
        check_eq("the id of a dispatch the open one resumed is accepted", code, 0)
        check_in("with a note saying which dispatch this run belongs to",
                 "was resumed as S5-qa-automator-9", err)
        built = json.loads(sorted((TASK2_ROOT / "work" / "requests").glob("*.json"),
                                  key=lambda p: p.stat().st_mtime)[-1].read_text(encoding="utf-8"))
        check_eq("and the run is recorded under the open dispatch", built["dispatch_id"], "S5-qa-automator-9")
        code, out, _ = call("--task", TASK2, "--mine", "TC-101", "--dispatch", "S5-qa-automator-1", "--again")
        check_eq("an id that is nobody's parent is still refused", last_json(out).get("status"), "mine_refused")

        # --- a red probe runs in its clone: --sandbox-root, end to end ----------------------------
        # TP1-15045 / the legacy run TP2-2406: the precedent of a probe was the latest
        # earlier probe, so a probe without a directory inherited a clone that was already gone;
        # a probe in a clone lost the profile's subdirectory; two clones could share one identity.
        red_probe_story()
        clone_a, clone_b = clone_of("clone-a"), clone_of("clone-b")
        probe = ("--task", TASK3, "--mine", "TC-201", "--purpose", "red_probe")
        code, out, err = call(*probe, "--sandbox-root", clone_a)
        check_eq("a red probe in a clone runs", (code, last_json(out).get("execution_status")), (0, "passed"))
        check_eq("and ran inside the clone", launched_in(clone_a), ["tests/test_c.py::test_alpha"])
        first = requests_of(TASK3_ROOT)[-1] if requests_of(TASK3_ROOT) else {"command": {}, "fingerprint_files": []}
        check_eq("the request's directory is the clone", first["command"].get("cwd"), str(clone_a))
        check("and the fingerprint covers the clone's test file",
              [r["path"] for r in first["fingerprint_files"] if r["kind"] == "test_files"]
              == [str(clone_a / "tests" / "test_c.py")])
        before = len(launches())
        code, out, _ = call(*probe)
        answer = last_json(out)
        check_eq("a second probe with no directory is refused, a red-probe precedent on record or not",
                 (code, answer.get("status")), (2, "mine_refused"))
        check_in("naming --cwd", "--cwd", answer.get("error", ""))
        check_in("and --sandbox-root", "--sandbox-root", answer.get("error", ""))
        check_eq("nothing ran", len(launches()), before)
        code, out, _ = call(*probe, "--sandbox-root", clone_b)
        check_eq("a probe in another clone runs", code, 0)
        second = requests_of(TASK3_ROOT)[-1] if requests_of(TASK3_ROOT) else {"command": {}}
        check_eq("in that clone, not in the discarded one", second["command"].get("cwd"), str(clone_b))
        check_eq("and ran there", launched_in(clone_b), ["tests/test_c.py::test_alpha"])
        check("the same instances over the same bytes in two clones are two attempts",
              bool(first.get("idempotency_key")) and first["idempotency_key"] != second.get("idempotency_key"))
        code, out, _ = call(*probe, "--sandbox-root", clone_a, "--cwd", clone_a)
        check_eq("--sandbox-root together with --cwd is refused", code, 2)
        check_in("naming both", "--sandbox-root", last_json(out).get("error", ""))
        code, out, _ = call(*probe, "--sandbox-root", ROOT / "no-such-clone")
        check_eq("a clone that is not there is refused", code, 2)
        check_in("naming it", "no-such-clone", last_json(out).get("error", ""))
        check_eq("--cwd keeps its meaning: the directory is taken as given",
                 (call(*probe, "--cwd", clone_b, "--again")[0],
                  requests_of(TASK3_ROOT)[-1]["command"]["cwd"]), (0, str(clone_b)))

        # --- the selector join and the profile's directory, builder level ----------------------
        xunit_story()
        shutil.copytree(ROOT / "backend", ROOT / "clone-y" / "backend")  # a second clone of the same bytes
        request = build_xunit(xunit_config(JOIN))
        check_eq("the profile's selectors.join is copied into the request", request["command"].get("selector_join"), JOIN)
        resolved = er.validate_request(request, ROOT)["resolved_argv"]
        check_eq("and the two selected tests become one option", (resolved.count("--filter"), resolved[-1]),
                 (1, "FullyQualifiedName=XTests.One|FullyQualifiedName=XTests.Two"))
        check("with the report placeholder still in its token, bound at launch",
              "trx;LogFileName={report_path}" in resolved)
        plain = build_xunit(xunit_config())
        check("a profile without a join rule leaves the request without one",
              "selector_join" not in plain["command"])
        check_eq("and the selectors are repeated, as before",
                 er.validate_request(plain, ROOT)["resolved_argv"].count("--filter"), 2)

        store = er.JobStore(TASK4_ROOT / "state" / "execution-jobs")
        _action, job = store.begin(er.validate_request(request, ROOT))
        store.update(job, status="completed", execution_status="passed", freshness="fresh")
        check("the profile decides: absent in the profile overrides a precedent that had a rule",
              "selector_join" not in build_xunit(xunit_config())["command"])
        other = {"option": "--filter", "separator": " OR ", "group": ["(", ")"]}
        check_eq("a different rule in the profile overrides the precedent's",
                 build_xunit(xunit_config(other))["command"].get("selector_join"), other)
        # (HF2-8 made a `--profile` the config does not hold a refusal naming the ids it holds, so this key no longer
        # NAMES the profile: with the config holding none, the story's precedent is what says which profile ran.)
        check_eq("no profile document: the precedent's rule is kept",
                 build_xunit({"execution": xunit_config()["execution"]})["command"].get("selector_join"),
                 JOIN)
        for label, bad in (("not an object", "|"), ("no separator", {"option": "--filter"}),
                           ("an empty option", {"option": "", "separator": "|"}),
                           ("a group of one", {**JOIN, "group": ["("]})):
            why = refusal_of(xunit_config(bad))
            check_in(f"a malformed rule in the profile ({label}) names where it lives",
                     "profiles[xunit].selectors.join", why)
            check_in(f"and the skill that corrects it ({label})", "qa-onboarding", why)

        author = str((ROOT / "backend" / "Tests" / "XTests.cs").resolve())
        check_eq("an ordinary run fingerprints the author's file",
                 [r["path"] for r in request["fingerprint_files"] if r["kind"] == "test_files"], [author])
        clone_x = (ROOT / "clone-x").resolve()
        probed = build_xunit(xunit_config(JOIN), purpose="red_probe", sandbox_root=str(clone_x))
        check_eq("a probe in a clone keeps the profile's subdirectory", probed["command"]["cwd"],
                 str(clone_x / "backend"))
        check_eq("and fingerprints the clone's bytes, not the author's",
                 [r["path"] for r in probed["fingerprint_files"] if r["kind"] == "test_files"],
                 [str(clone_x / "backend" / "Tests" / "XTests.cs")])
        check("a probe has a run directory in its identity: another clone is another key",
              build_xunit(xunit_config(JOIN), purpose="red_probe",
                          sandbox_root=str((ROOT / "clone-y").resolve()))["idempotency_key"]
              != probed["idempotency_key"])
        nodoc = build_xunit({"execution": xunit_config()["execution"]},
                            purpose="red_probe", sandbox_root=str(clone_x))
        check_eq("without a profile directory the ordinary precedent's, mapped under the clone, decides",
                 nodoc["command"]["cwd"], str(clone_x / "backend"))
        why = refusal_of(xunit_config(JOIN), purpose="red_probe")
        check_in("a probe with no directory is refused with an ordinary precedent on record", "--sandbox-root", why)
        check_in("keeping the literal the caller reads", "--cwd", why)
        outside = str(ROOT.parent / "elsewhere-dir")
        why = refusal_of(xunit_config(JOIN, cwd=outside), purpose="red_probe", sandbox_root=str(clone_x))
        check_in("an absolute profile directory outside the project is refused, naming it", outside, why)
        why = refusal_of(xunit_config(JOIN, cwd="../../outside"), purpose="red_probe", sandbox_root=str(clone_x))
        check_in("so is a `..` that escapes the project", "../../outside", why)

        # --- R-A3: a typed run that never ran a test is not the command precedent -------------
        # Last: its own task, removed after, so the calls above that name no task never see it.
        try:
            precedent_battery()
        finally:
            shutil.rmtree(PT_ROOT, ignore_errors=True)
        # --- t-300 N2: the person's word reaches the run -------------------------------------------------------------------
        n2_battery()
        te2_the_persons_word_reaches_the_runs_mine()
        b_run_battery()
        qualified_case_battery()
        qualified_edge_battery()
        qualified_fix_round_battery()
        one_collect_battery()
        phases_battery()
        memo_battery()
        collect_only_battery()
        c8_battery()
    finally:
        for name in ("node_ids", "stand_lease", "stand_health"):
            sys.modules.pop(name, None)
        shutil.rmtree(ROOT, ignore_errors=True)
    finish("test_run_suite_mine")


if __name__ == "__main__":
    main()
