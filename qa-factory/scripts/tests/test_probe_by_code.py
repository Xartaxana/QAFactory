"""probe_by_code.py: the critic's red probe by code.

A temp project with a tiny test file and a stub in place of `run_suite.py` (`PROBE_RUN_SUITE`).
The stub reads the typed request the script wrote, imports the test module AS IT LIES ON DISK
at that moment and calls the one function the request selects, then writes pytest-shaped
junit evidence and the summary `run_suite.py` prints — so every verdict below comes from the
mutated bytes really running, not from a canned answer, and pytest is never launched.
"""
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness import (SCRIPTS, check, check_eq, check_in, check_not_in, cleanup, finish, run_script,  # noqa: E402
                     mark_project, temp_dir, use_project)

import acceptance  # noqa: E402
import assertion_detectors as AD  # noqa: E402
import contract as C  # noqa: E402
import probe_by_code as PBC  # noqa: E402
import proof_level as PL  # noqa: E402
import probe_entries as PE  # noqa: E402
from event_store import content_hash  # noqa: E402

PY = sys.executable
TASK = "PROBE-2"
DISPATCH = "S5-qa-code-critic-1"
TEST_FILE_REL = "tests/test_calc.py"

FAKE_RUN_SUITE = r'''
"""A stand-in for `run_suite.py --request FILE`: runs the ONE selected node in-process."""
import hashlib
import importlib.util
import json
import os
import sys
import traceback
from pathlib import Path

if os.environ.get("PROBE_STUB_LOG"):  # one line per launch: how often the runner really ran
    with open(os.environ["PROBE_STUB_LOG"], "a", encoding="utf-8") as log:
        log.write(sys.argv[-1] + "\n")
if os.environ.get("PROBE_STUB_CRASH") == "1":
    print("stub: boom, no summary today")
    sys.exit(1)
if any(a.endswith("pytest") or a == "pytest" for a in sys.argv[1:]):
    print(json.dumps({"status": "stub_refused", "error": "the stub never launches pytest"}))
    sys.exit(2)
request = json.loads(Path(sys.argv[sys.argv.index("--request") + 1]).read_text(encoding="utf-8"))
if request.get("purpose") != "red_probe":
    print(json.dumps({"status": "stub_refused", "error": "purpose must be red_probe, got " + str(request.get("purpose"))}))
    sys.exit(2)
iid = request["selected_instance_ids"][0]
node = request["command"]["selector_args"][iid][0]
cwd = Path(request["command"]["cwd"]).resolve()
file_part, tail = node.split("::", 1)
parts = tail.split("::")
func_name = parts[-1].split("[")[0]
test_path = (cwd / file_part).resolve()
sys.path.insert(0, str(cwd))
sys.path.insert(0, str(test_path.parent))   # pytest's own `prepend` import mode: the test file's folder, so a sibling helper imports
spec = importlib.util.spec_from_file_location("probe_target_module", test_path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
target = module
for name in parts[:-1]:
    target = getattr(target, name)
    if isinstance(target, type):
        target = target()
function = getattr(target, func_name)


def frame_lines(exc):
    frames = [f for f in traceback.extract_tb(exc.__traceback__)
              if Path(f.filename).resolve() != Path(__file__).resolve()]
    lines = []
    for index, frame in enumerate(frames):
        try:
            shown = Path(frame.filename).resolve().relative_to(cwd).as_posix()
        except ValueError:
            shown = frame.filename
        tail = f"{type(exc).__name__}" if index == len(frames) - 1 else ""
        lines.append(f"{shown}:{frame.lineno}: {tail}".rstrip())
    return lines


status, message, text = "passed", "", ""
try:
    function()
except BaseException as exc:  # noqa: BLE001 — the stub reports whatever fired
    status = "failed"
    message = f"{type(exc).__name__}: {exc}"
    text = "\n".join(frame_lines(exc))

classname = file_part.replace("/", ".")[:-3] + ("." + ".".join(parts[:-1]) if parts[:-1] else "")
name = parts[-1]
if status == "passed":
    row = f'<testcase classname="{classname}" name="{name}"/>'
else:
    from xml.sax.saxutils import escape, quoteattr
    row = (f'<testcase classname="{classname}" name="{name}"><failure message={quoteattr(message)}>'
           f'{escape(text)}</failure></testcase>')
xml = (f'<testsuite tests="1" failures="{0 if status == "passed" else 1}" errors="0" skipped="0">'
       + row + "</testsuite>")
job = hashlib.sha256(request["idempotency_key"].encode()).hexdigest()[:20]
# The task's artifacts live under the PROJECT, which is not the run directory when the profile
# runs in a subdirectory (the run-directory test below).
project = Path(os.environ.get("CLAUDE_PROJECT_DIR") or cwd).resolve()
task_root = project / "qa-factory" / "artifacts" / request["task"]
run_dir = task_root / "evidence" / "runs" / job
run_dir.mkdir(parents=True, exist_ok=True)
report = run_dir / "report.junit.xml"
report.write_text(xml, encoding="utf-8")
label = f"red_probe-{job}"
summary_path = run_dir / f"{label}.json"
seen = test_path.read_bytes()
summary = {"task": request["task"], "label": label, "exit_code": 0 if status == "passed" else 1,
           "execution_status": status, "purpose": "red_probe",
           "summary_path": summary_path.relative_to(project).as_posix(),
           "report_evidence": {"path": report.relative_to(task_root).as_posix(),
                               "sha256": hashlib.sha256(report.read_bytes()).hexdigest()},
           "stub_seen_sha256": hashlib.sha256(seen).hexdigest(),
           # t-2064 P4b: the walk's aggregate carries no statement text, so the stub keeps the mutated text it ran for a test to read
           "stub_seen_text": seen.decode("utf-8", "replace"),
           # t-2045 N2: the Python marker is joined at run time (`'-'.join(['qa-probe', '<token>'])`), so the mutated bytes hold
           # `'qa-probe'` and no longer the contiguous `probe-`; either spelling says the stub ran the mutated file
           "stub_seen_marker": b"probe-" in seen or b"'qa-probe'" in seen}
if os.environ.get("PROBE_STUB_REPORTER"):  # the real run_suite names its reporter; the default stub does not
    summary["reporter"] = os.environ["PROBE_STUB_REPORTER"]
summary_path.write_text(json.dumps(summary, indent=1), encoding="utf-8")
print("MINE (note): stub")
print(json.dumps(summary))
sys.exit(summary["exit_code"])
'''

TEST_FILE = '''\
from calc import add
from hamcrest import assert_that, equal_to


def test_add():
    assert add(2, 2) == 4, "sum must be 4"


def test_dead_assert():
    total = add(1, 1)
    if total > 100:
        assert total == 2


def test_raises_first():
    raise RuntimeError("setup exploded")
    assert add(1, 1) == 2


def test_no_assert():
    add(1, 1)


class TestCalc:
    def test_method(self):
        result = add(3, 3)
        assert result in [6, 7]


def test_hamcrest():
    assert_that(add(2, 2), equal_to(4))


def test_multiline():
    assert add(
        2, 2
    ) == 4, (
        "sum must be 4"
    )
    assert True


def test_via_helper():
    from expectations import expect_sum
    expect_sum(add(2, 2), 4)
'''
CALC = "def add(a, b):\n    return a + b\n"
# The oracle outside the test: a helper module several tests share, which is how a real suite
# is written and what left `probe_by_code` with nothing to mutate on TP1-13797.
EXPECTATIONS = ('def expect_sum(actual, expected):\n'
                '    assert actual == expected, "sum must match"\n')
# A local stand-in for PyHamcrest: the assertion fires INSIDE this module, so pytest's last
# traceback line names hamcrest.py and the test's own line is an earlier frame — the shape
# every hamcrest-written project (TP1-13797's harness among them) reports.
HAMCREST = '''\
class _Matcher:
    def __init__(self, expected, negate=False):
        self.expected, self.negate = expected, negate

    def matches(self, actual):
        return (actual == self.expected) != self.negate

    def describe(self):
        return ("not " if self.negate else "") + repr(self.expected)


def equal_to(value):
    return _Matcher(value)


def is_not(matcher):
    return _Matcher(matcher.expected, not matcher.negate)


def assert_that(actual, matcher, reason=""):
    if not matcher.matches(actual):
        raise AssertionError(f"{reason}\\nExpected: {matcher.describe()}\\n     but: was {actual!r}")
'''
PROVENANCE = {"profile_id": "unit", "timestamp": "2026-09-24T10:00:00Z", "environment_id": "local",
              "expected_source_revision": "source-1", "observed_runtime_identity": "build-1",
              "evidence_refs": ["probe"], "result": "matched",
              "provenance": {"technical_verification": True, "source_linkage": "exact",
                             "deployed_source_revision": "source-1"}}
OBLIGATION_REFS = [{"obligation_id": "OB-ADD-1", "obligation_hash": "ob-hash-1"}]


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=1), encoding="utf-8")


def entry(case: str, test: str, instance: str, **extra) -> dict:
    return {"case": case, "covers": [case], "file": TEST_FILE_REL, "test": test, "instance_id": instance,
            "selector": test,  # what `--mine` builds a node id from (the run the author's job came from)
            "case_version_links": [{"case_id": case, "version": "cv_1"}], **extra}


def seed_author_job(root: Path, profile_id: str = "") -> dict:
    """The author's run of TC-100 as a job in the story's job store, built by `build_mine_request` - the
    producer of `instance_contracts` - and never typed: the probe measures a test's identity from it.
    `profile_id` is what the author's call named: with two profiles over one test root and a manifest that names
    none, the author's own `--mine` is the one that needs `--profile` (EP1-16)."""
    import execution_request as ER
    cfg = json.loads((root / "qa-factory" / "config.json").read_text(encoding="utf-8"))
    request, _notes, _reuse, _verified = ER.build_mine_request(
        root, ["TC-100"], cfg=cfg, task=TASK, dispatch_id=DISPATCH, probe=lambda spec: PROVENANCE,
        profile_id=profile_id)
    store = ER.JobStore(root / "qa-factory" / "artifacts" / TASK / "state" / "execution-jobs")
    _action, job = store.begin(request)
    store.update(job, status="completed", execution_status="passed", freshness="fresh")
    return request


def project(provenance: bool = True, *, shared_second: bool = False, row_profile: str = "") -> Path:
    """`shared_second`: a second profile `ui` over the SAME test root and the same cwd (the 12586 shape: the path
    cannot tell the profiles apart, and `_profile_cwd` still has one directory to give). `row_profile`: the profile
    every manifest row names (`profile_id`)."""
    root = temp_dir("qa-probe-code-")
    (root / "tests").mkdir()
    (root / "tests" / "test_calc.py").write_text(TEST_FILE, encoding="utf-8")
    (root / "calc.py").write_text(CALC, encoding="utf-8")
    (root / "hamcrest.py").write_text(HAMCREST, encoding="utf-8")
    (root / "tests" / "expectations.py").write_text(EXPECTATIONS, encoding="utf-8")   # a helper under the test root: a product-side one is never hopped into (B1)
    bin_dir = root.parent / (root.name + "-bin")
    bin_dir.mkdir()
    fake_pytest = bin_dir / "pytest"  # named pytest: the request builder's own pytest check
    fake_pytest.write_text("import sys; sys.exit(3)\n", encoding="utf-8")
    probe_script = root.parent / (root.name + "-runtime-probe.py")
    probe_script.write_text("import json\nprint(json.dumps(" + repr(PROVENANCE) + "))\n", encoding="utf-8")
    profiles = [{"profile_id": "unit", "selected": True, "roots": {"test": "tests"},
                 "commands": {"one_test": {"argv": [PY, str(fake_pytest), "--junitxml", "{report_path}"],
                                           "cwd": "."}},
                 "reporter": {"kind": "junit-xml"}, "selectors": {"verified": True}}]
    if shared_second:
        profiles.append(dict(json.loads(json.dumps(profiles[0])), profile_id="ui"))
    write_json(root / "qa-factory" / "config.json", {
        "tests_root": "tests", "app_root": ".",
        "profiles": profiles,
        "execution": {"runtime_probes": {"unit": {"argv": [PY, str(probe_script)], "cwd": ".",
                                                   "timeout_s": 20}}}})
    task_root = root / "qa-factory" / "artifacts" / TASK
    write_json(task_root / "pipeline.json", {"stages": {"S5": {"status": "running"}},
                                             "first_test_run_at": "2026-09-24T09:00:00+00:00"})
    scope = ["TC-100", "TC-101", "TC-102", "TC-103", "TC-104", "TC-105", "TC-106", "TC-107"]
    write_json(task_root / "state" / "controller.json", {
        "schema_version": "2", "revision": "1", "source_revision": "source-1",
        "dispatches": {DISPATCH: {"id": DISPATCH, "stage": "S5", "role": "qa-code-critic",
                                  "status": "running", "scope": scope, "budget": {"requests": 50}}}})
    # test_add is bound to its bytes the way manifest_from_tests.py binds every row: the raw sha256
    # of the file (`TestFile.content_sha`), which is also what validate_artifacts enforces.
    bound = {"test_content_sha": PBC.sha256((root / TEST_FILE_REL).read_bytes())}
    named = {"profile_id": row_profile} if row_profile else {}
    write_json(task_root / "work" / "automation-manifest.json", {"tests": [
        entry("TC-100", "test_add", "test_add", obligation_refs=OBLIGATION_REFS, trace_binding=bound,
              obligation_ids=["OB-ADD-1"], defect_location="calc.py:2", assertion_id="add_returns_sum", **named),
        entry("TC-101", "test_dead_assert", "test_dead_assert"),
        entry("TC-102", "test_raises_first", "test_raises_first"),
        entry("TC-103", "test_no_assert", "test_no_assert"),
        entry("TC-104", "test_method", "test_method"),
        entry("TC-105", "test_hamcrest", "test_hamcrest"),
        entry("TC-106", "test_multiline", "test_multiline"),
        entry("TC-107", "test_via_helper", "test_via_helper"),
    ]})
    # The author's green run block over exactly these bytes of test_add: the probe binds its
    # `input_hash` to it through the function's own sha, never to a whole-file guess. That sha is the
    # one the author's job carries (`instance_contracts`): one derivation, and the probe's identity
    # of the test is measured from the same job.
    request = seed_author_job(root, "unit" if shared_second else "")
    sha = request["instance_contracts"]["test_add"]["instance_content_sha"]
    # `runtime_provenance` is where a receipt's `build_id` comes from (proof_level.binding_facts);
    # a project whose author run block carries none has no receipt to write, and says so.
    block = {"schema_version": 2, "dispatch_id": "S5-qa-automator-1", "purpose": "initial",
             "results": [{"instance_id": "test_add", "status": "passed", "instance_content_sha": sha,
                          "source_fingerprint": {"source_sha": "source-1", "test_content_sha": "author-tcs-1"}}]}
    if provenance:
        block["runtime_provenance"] = {"observed_runtime_identity": "build-1", "environment_id": "env-1"}
    write_json(task_root / "work" / "run-blocks" / "20260924T090000000000Z-author1.json", block)
    return root


def env_for(root: Path, stub: Path, **extra) -> dict:
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(root), PROBE_RUN_SUITE=str(stub))
    env.pop("PROBE_STUB_CRASH", None)
    env.update(extra)
    return env


def model_entries(root: Path, stub, test: str, instance: str, dispatch: str = DISPATCH, task: str = TASK) -> None:
    """t-2064 P4b: a call with no `--at` and no `--oracle` walks every check and needs a model entry per check. This writes the
    window's model file (`work/probe-models/<dispatch>.json`) with one `invert` entry per key `--plan` lists, so the wrappers below keep
    taking the inversion road through the loader a critic's file goes through. NOT used by `run_close` (S6 is no role: it inverts by itself)."""
    try:
        env = env_for(root, stub) if stub else dict(os.environ, CLAUDE_PROJECT_DIR=str(root))
        keys = PE.plan_keys(["--task", task, "--instance", instance, "--test", test], root=root, env=env)
        if keys:    # an EMPTY plan is the probe's refusal to read: a file of no entries would be a byte the wrapper wrote, not the probe
            PE.write_invert_entries(root / "qa-factory" / "artifacts" / task, dispatch, keys=keys)
    except RuntimeError:
        pass    # `--plan` refuses (no such instance, a file that is not there): no world to write entries for; the probe's own refusal is what the test reads


def run(root: Path, stub: Path, test: str, instance: str, mutation: str = "invert", **extra):
    model_entries(root, stub, test, instance)
    proc = run_script("probe_by_code.py", "--task", TASK, "--dispatch", DISPATCH, "--test", test,
                      "--instance", instance, "--mutation", mutation, "--json",
                      cwd=root, env=env_for(root, stub, **extra))
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    try:
        payload = json.loads("\n".join(lines)) if lines and lines[0].startswith("{") else {}
    except ValueError:
        payload = {}
    return proc, payload


def mutated_line(root: Path, record: dict, line: int) -> str:
    """Line `line` (1-based) of the mutated bytes the stub ran for the walk's first run (`stub_seen_text` of its evidence summary)."""
    task_root = root / "qa-factory" / "artifacts" / TASK
    ref = record.get("evidence_ref")
    summary = json.loads((task_root / ref).read_text(encoding="utf-8")) if ref else {}
    lines = str(summary.get("stub_seen_text") or "").splitlines()
    return lines[line - 1] if len(lines) >= line else ""


def read_check_record(root: Path, instance: str, which: int = 0) -> dict:
    """The `which`-th per-check record of the instance (`work/probes/checks/`, in file name order): what a walk writes beside its aggregate."""
    directory = root / "qa-factory" / "artifacts" / TASK / "work" / "probes" / "checks"
    files = sorted(directory.glob(f"{instance}--*.json")) if directory.is_dir() else []
    return json.loads(files[which].read_text(encoding="utf-8")) if len(files) > which else {}


def read_record(root: Path, instance: str) -> dict:
    path = root / "qa-factory" / "artifacts" / TASK / "work" / "probes" / f"{instance}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


# --- comparing two receipts -----------------------------------------------------------------------
# Two runs of one scenario differ in the time, the job id the idempotency key hashes, the fingerprint
# over temp paths and the evidence file that names the job: `normalised` takes those out, so a receipt
# can be compared with the receipt of the same scenario read another way (`reporter_in_the_summary`).
# The golden receipts that once pinned a byte-for-byte digest of whole receipts are gone: they were
# taken from code that wrote `mutation_kind: real_behavior`, which 0.8.1 changed to `assertion`.


def normalised(root: Path, returncode: int, record: dict) -> dict:
    """The receipt with what differs between two runs of the SAME code taken out."""
    text = json.dumps({"rc": returncode, "record": record}, sort_keys=True)
    text = text.replace(str(root).replace("\\", "\\\\"), "<ROOT>").replace(str(root), "<ROOT>")
    # t-2045 N2: a Python plan now carries a per-run probe token (`qa-probe-<12 hex>` in the message, `'<12 hex>'` inside the
    # joined expression); only those two spellings are masked, so the rest of the statement still compares byte for byte.
    text = re.sub(r"qa-probe-[0-9a-f]{12}\b", "qa-probe-<TOKEN>", text)
    text = re.sub(r"(\['qa-probe', ')[0-9a-f]{12}('\])", r"\1<TOKEN>\2", text)
    # t-2064 TR2-14: a receipt file named inside the notes carries the project's hash (`<check>-live-<16 hex>.json`): masked, the rest of the note compares.
    text = re.sub(r"-live-[0-9a-f]{16}", "-live-<HASH>", text)
    value = json.loads(re.sub(r"\b[0-9a-f]{20}\b", "<JOB>", text))
    rec = value["record"]
    rec.pop("recorded_at", None)
    # The receipt's file name carries a hash of the project it was written in, and so do the manifest
    # revision and the publication line that name it: each comparison here runs in a project of its own
    # (a repeat in one project is answered `already_probed`), so those are taken out too.
    for key in ("binding", "publish", "receipt"):
        rec.pop(key, None)
    if str(rec.get("input_hash_source") or "").startswith("fingerprint:"):
        rec["input_hash"] = "<varies with the temp paths>"
        rec["window_probe"]["input_hash"] = "<varies with the temp paths>"
    for ref in rec.get("evidence_refs") or []:
        if ref["path"].endswith(".json"):
            ref["sha256"] = "<varies with the job id>"
        else:
            ref["sha256"] = "<varies with the token>"     # the report file holds the failure text, which holds the token
    return value


def snapshot(root: Path) -> dict:
    """{path: sha256 or 'dir'} of everything a probe can write inside the story - records, requests,
    receipts, jobs, the manifest - so 'nothing was written' is compared, not asserted."""
    task = task_of(root)
    found = {}
    for sub in ("work/probes", "work/probe-requests", "work/sensitivity-receipts", "state/execution-jobs"):
        base = task / sub
        found[sub] = "dir" if base.is_dir() else "absent"
        for path in sorted(base.rglob("*")) if base.is_dir() else []:
            found[path.relative_to(task).as_posix()] = PBC.sha256(path.read_bytes()) if path.is_file() else "dir"
    manifest = task / "work" / "automation-manifest.json"
    found["manifest"] = PBC.sha256(manifest.read_bytes()) if manifest.is_file() else "absent"
    return found


def give_word(root: Path, at: str, match: str = "already probed on these bytes") -> None:
    """A person's recorded word for the repeat block, said at `at` (orchestrator: waiver.py)."""
    path = task_of(root) / "pipeline.json"
    pipeline = json.loads(path.read_text(encoding="utf-8"))
    pipeline["stage_overrides"] = [{"stage": "S5", "match": match, "decision": "probe it again, I asked", "at": at}]
    write_json(path, pipeline)


def clear_word(root: Path) -> None:
    path = task_of(root) / "pipeline.json"
    pipeline = json.loads(path.read_text(encoding="utf-8"))
    pipeline.pop("stage_overrides", None)
    write_json(path, pipeline)


def author_job(root: Path) -> dict:
    """The one job the fixture's story holds: the author's run."""
    import execution_request as ER
    return ER.JobStore(root / "qa-factory" / "artifacts" / TASK / "state" / "execution-jobs").jobs()[0]


def invert_plain_assert(root: Path, stub: Path) -> dict:
    original = (root / TEST_FILE_REL).read_bytes()
    proc, record = run(root, stub, f"{TEST_FILE_REL}::test_add", "test_add")
    check("invert: exit 0", proc.returncode == 0, proc.stdout + proc.stderr)
    check_eq("invert: the verdict is intended_failure", record.get("verdict"), "intended_failure")
    check_eq("invert: expected_location is the assert's line", record.get("expected_location"),
             f"{TEST_FILE_REL}:6")
    check_eq("invert: actual_location equals it", record.get("actual_location"), record.get("expected_location"))
    # t-2064 P4b: the answer is the walk's aggregate; its reason says how many checks of the plan were proved (it was the marker's id
    # when one line was probed by the old default)
    check_eq("invert: expected_reason says the plan's checks were proved", record.get("expected_reason"),
             "1 of 1 checks of the plan proved")
    check_eq("invert: actual_reason equals it", record.get("actual_reason"), record.get("expected_reason"))
    check_eq("invert: failure_kind assertion", record.get("failure_kind"), "assertion")
    # D-0010: this tool mutates the assertion, so what it proves is that the check is live; it used
    # to claim `real_behavior`, a product mutation it never makes.
    check_eq("invert: mutation_kind assertion", record.get("mutation_kind"), "assertion")
    check_eq("invert: proof_level live", record.get("proof_level"), "live")
    # t-2064 P4b: the aggregate no longer carries the mutated statement (`mutation_detail` is `{file, line, end_line, checks}`); the
    # statement is read from the bytes the stub ran (`mutated_line`), the marker's identity from the per-check record's failing text.
    detail = record.get("mutation_detail", {})
    check_eq("invert: the detail names the file and the check the walk mutated", (detail.get("file"), detail.get("checks")),
             (TEST_FILE_REL, [f"{TEST_FILE_REL}:6"]))
    row = (record.get("checks") or [{}])[0]
    check_eq("invert: the check row is the inversion, proved by its marker", (row.get("probe_kind"), row.get("proved_by"), row.get("verdict")),
             ("invert", "marker", "intended_failure"))
    joined = re.fullmatch(r"    assert not \(add\(2, 2\) == 4\), '-'\.join\(\['qa-probe', '([0-9a-f]{12})'\]\)", mutated_line(root, record, 6))
    check("invert: the mutated statement carries the marker joined at run time (t-2045 N2)", joined is not None, mutated_line(root, record, 6))
    check_eq("invert: the run's failing text names that marker, and it is in no contiguous byte of the statement",
             (read_check_record(root, "test_add").get("observed") or {}).get("message_head"),
             "AssertionError: qa-probe-" + (joined.group(1) if joined else "?"))
    check_eq("invert: obligation_ids copied from the manifest", record.get("obligation_ids"), ["OB-ADD-1"])
    check_eq("invert: obligation_hash is content_hash(obligation_refs)", record.get("obligation_hash"),
             content_hash(OBLIGATION_REFS))
    check_eq("invert: defect_location copied", record.get("defect_location"), "calc.py:2")
    check_eq("invert: assertion_id copied", record.get("assertion_id"), "add_returns_sum")
    check_eq("invert: nothing missing from the manifest entry", record.get("manifest_fields_missing"), [])
    check_eq("invert: input_hash bound to the author's run block", record.get("input_hash"), "author-tcs-1")
    check_eq("invert: and says whose it is (the walk's request carries the author's binding)", record.get("input_hash_source"),
             "the walk's request")
    task_root = root / "qa-factory" / "artifacts" / TASK
    evidence = record.get("evidence_ref")
    check("invert: evidence_ref is a task-relative file", bool(evidence) and (task_root / evidence).is_file())
    refs = {r["path"]: r["sha256"] for r in record.get("evidence_refs") or []}
    check("invert: evidence_refs carry the evidence_ref with its sha256",
          evidence in refs and refs[evidence] == PBC.sha256((task_root / evidence).read_bytes()))
    # t-2064 P4b: a walk's requests are per RUN: work/probe-requests/probe-walk-<IID>-<run>.json; the aggregate names no one request
    request_path = task_root / "work" / "probe-requests" / "probe-walk-test_add-1.json"
    check("invert: the request is under work/probe-requests/probe-walk-<IID>-<run>.json", request_path.is_file())
    request = json.loads(request_path.read_text(encoding="utf-8")) if request_path.is_file() else {}
    check_eq("invert: purpose red_probe", request.get("purpose"), "red_probe")
    check_eq("invert: exactly this instance", request.get("selected_instance_ids"), ["test_add"])
    check_in("invert: the reason names the probe", "probe-test_add", request.get("reason", ""))
    check_eq("invert: built_by names the tool", (request.get("built_by") or {}).get("tool"), "probe_by_code.py")
    check_eq("invert: the aggregate names no single request", record.get("request"), None)
    summary = json.loads((task_root / evidence).read_text(encoding="utf-8")) if evidence else {}
    check("invert: the stub ran the MUTATED bytes", summary.get("stub_seen_marker") is True
          and summary.get("stub_seen_sha256") != PBC.sha256(original))
    check_eq("invert: the file is byte-identical after the probe", (root / TEST_FILE_REL).read_bytes(), original)
    check_eq("invert: restore verified by sha256", (record.get("restore") or {}).get("verified"), True)
    # B-373 R9: the restore reads the byte copy on disk, and the copy goes only after that is verified
    # (test_probe_by_code_copy.py pins the rest: the lock, the kill, the recovery)
    # t-2064 P4b: the walk's `restore` is `{verified, sha256, runs}` (one restore for the whole walk); where it came from is the copy
    # folder's business, pinned by the next check (nothing left under state/probe-copies) and by test_probe_by_code_copy.py
    check_eq("invert: the walk restored once, after its one run", ((record.get("restore") or {}).get("runs"),
             (record.get("restore") or {}).get("sha256")), (1, PBC.sha256(original)))
    check_eq("invert: no copy or record of one is left under state/probe-copies",
             sorted(p.name for p in (root / "qa-factory" / "state" / "probe-copies").glob("*") if p.suffix != ".lock"), [])
    check_eq("invert: the record is on disk", read_record(root, "test_add").get("verdict"), "intended_failure")
    # t-043 C: the record carries the per-test identity the author's job wrote (`instance_contracts`),
    # re-measured over the bytes the probe read BEFORE it mutated anything - never a derivation of its own
    job = author_job(root)
    contract = job["request"]["instance_contracts"]["test_add"]
    check_eq("identity: the record's instance_identity is the job's contract shas, re-measured",
             record.get("instance_identity"),
             {"instance_content_sha": contract["instance_content_sha"],
              "instance_code_sha": contract["instance_code_sha"], "job_id": job["job_id"]})
    check_eq("identity: the flat instance_content_sha says the same, under the name run blocks use",
             record.get("instance_content_sha"), contract["instance_content_sha"])
    check_eq("identity: the mutated file is recorded with the bytes it held (here the test itself)",
             record.get("mutated_file"),
             {"path": TEST_FILE_REL, "sha256": PBC.sha256(original), "code_sha": PL.code_sha(original, "test_calc.py")})
    window_probe = record.get("window_probe") or {}
    check_eq("invert: window_probe repeats the verdict and hash", (window_probe.get("verdict"), window_probe.get("input_hash")),
             ("intended_failure", "author-tcs-1"))
    check_eq("invert: window_probe carries the level and the assertion mutation",
             (window_probe.get("proof_level"), window_probe.get("mutation_kind")), ("live", "assertion"))
    return record


def class_method(root: Path, stub: Path) -> None:
    proc, record = run(root, stub, f"{TEST_FILE_REL}::TestCalc::test_method", "test_method", "invert")
    check("class method: exit 0", proc.returncode == 0, proc.stdout + proc.stderr)
    check_eq("class method: intended_failure", record.get("verdict"), "intended_failure")
    # t-2064 P4b: the aggregate holds no statement text; it is read from the bytes the stub ran
    check_in("class method: the method's assert is inverted", "assert not (result in [6, 7])", mutated_line(root, record, 27))
    check_eq("class method: location is the method's assert", record.get("expected_location"), f"{TEST_FILE_REL}:27")
    # No run block ever executed this instance: the source and build identity a receipt binds are
    # the author's record, not the probe's to type - so no receipt, and the record names each fact
    # that was missing (the exit stays 0: a verdict was recorded). Its row binds no bytes, and that
    # is no longer a missing fact: the test file's own bytes are read (Amendment 2, one reader).
    check_eq("class method: no receipt without the facts it binds", record.get("receipt"), None)
    check_eq("class method: and every missing fact is named", record.get("receipt_missing"),
             ["source_revision", "build_id"])
    check_in("class method: the note says whose record it is", "the author's record",
             " ".join(record.get("notes") or []))
    check_in("class method: nothing was published", "nothing published", str(record.get("binding")))
    check_eq("class method: no receipt file for it",
             list((root / "qa-factory" / "artifacts" / TASK / "work" / "sensitivity-receipts")
                  .glob("test_method-live-*")), [])


def hamcrest_style(root: Path, stub: Path) -> None:
    proc, record = run(root, stub, f"{TEST_FILE_REL}::test_hamcrest", "test_hamcrest", "invert")
    check("hamcrest invert: exit 0", proc.returncode == 0, proc.stdout + proc.stderr)
    check_eq("hamcrest invert: intended_failure", record.get("verdict"), "intended_failure")
    # t-2064 P4b: the statement is read from the bytes the stub ran; what the run saw is read from the per-check record (the
    # aggregate's `observed` is `{}`)
    check_in("hamcrest invert: is_not around the matcher", 'is_not(equal_to(4))', mutated_line(root, record, 31))
    observed = read_check_record(root, "test_hamcrest").get("observed") or {}
    check("hamcrest invert: the last traceback line is inside hamcrest",
          str(observed.get("location", "")).startswith("hamcrest.py:"))
    check_eq("hamcrest invert: the test file frame decides the location", record.get("actual_location"),
             f"{TEST_FILE_REL}:31")


def dead_assert(root: Path, stub: Path) -> None:
    proc, record = run(root, stub, f"{TEST_FILE_REL}::test_dead_assert", "test_dead_assert")
    check("dead assert: exit 0 (a verdict was recorded)", proc.returncode == 0, proc.stdout + proc.stderr)
    check_eq("dead assert: no_failure", record.get("verdict"), "no_failure")
    check_eq("dead assert: no actual location", record.get("actual_location"), None)


def raises_first(root: Path, stub: Path) -> None:
    proc, record = run(root, stub, f"{TEST_FILE_REL}::test_raises_first", "test_raises_first")
    check("raises first: exit 1 (an `incomplete` verdict was recorded, as for any probe that is not proved)", proc.returncode == 1,
          proc.stdout + proc.stderr)
    # N3b: a throw before the check is not proved by its place: no token in its text, so the code critic judges it (a fact: where it fell)
    check_eq("raises first: incomplete, owed a judgment", (record.get("verdict"), record.get("cause")), ("incomplete", "judgment"))
    check_eq("raises first: nothing is proved", record.get("proved_by"), None)
    # t-2064 P4b: the facts of a walk's judgment live in the per-check record's `observed` (the aggregate has no `judgment_facts`); "outside
    # the mutated statement" is the observed place against the check's own key (it was `location_hit: False`)
    seen = read_check_record(root, "test_raises_first").get("observed") or {}
    check_eq("raises first: the facts hold the place of the raise", seen.get("location"), f"{TEST_FILE_REL}:16")
    check_eq("raises first: and that it is outside the mutated statement", seen.get("location") == (record.get("checks") or [{}])[0].get("key"), False)
    check_eq("raises first: failure_kind is not assertion", seen.get("failure_kind"), "exception")


def no_assert(root: Path, stub: Path) -> None:
    original = (root / TEST_FILE_REL).read_bytes()
    stamp = (root / TEST_FILE_REL).stat().st_mtime_ns
    proc, payload = run(root, stub, f"{TEST_FILE_REL}::test_no_assert", "test_no_assert")
    check("no assert: exit 2", proc.returncode == 2, proc.stdout + proc.stderr)
    check_eq("no assert: refused", payload.get("status"), "refused")
    # t-2064 P4b item 2: a walk with an empty plan is a refusal (EP-A: an empty list is never read as proved) that names the detector table and
    # the `--at` door; it takes no lock and is a tool refusal that DOES leave the `refused: tool` record (t-2143 N4: `main` writes it through
    # `_record_tool_refusal`; it was the `no assert` text on the old first-check road, which `--at` still is)
    check_in("no assert: the message says no check of a known form was found", "no check of a form the factory reads was found", payload.get("error", ""))
    check_in("no assert: and names the door (the detector table, and --at for a check in a helper)", "--at <file>:<line>", payload.get("error", ""))
    check_eq("no assert: the file was never touched", (root / TEST_FILE_REL).stat().st_mtime_ns, stamp)
    check_eq("no assert: bytes unchanged", (root / TEST_FILE_REL).read_bytes(), original)
    refusal_record = read_record(root, "test_no_assert")
    check_eq("no assert: a refusal of the tool, with the record (refused: tool, not_executed)",
             (refusal_record.get("refused"), refusal_record.get("verdict")), ("tool", "not_executed"))
    proc, payload = run(root, stub, f"{TEST_FILE_REL}::test_nowhere", "test_nowhere")
    check_eq("unknown instance: refused before any file", (proc.returncode, payload.get("status")), (2, "refused"))


def restore_on_failure(stub: Path) -> None:
    root = project()  # its own: the shared project's test_add already holds a receipt (answered, not run)
    try:
        _restore_on_failure(root, stub)
    finally:
        cleanup(root)
        cleanup_beside(root)


def _restore_on_failure(root: Path, stub: Path) -> None:
    original = (root / TEST_FILE_REL).read_bytes()
    proc, record = run(root, stub, f"{TEST_FILE_REL}::test_add", "test_add", PROBE_STUB_CRASH="1")
    check("runner crash: exit 1", proc.returncode == 1, proc.stdout + proc.stderr)
    check_eq("runner crash: not_executed", record.get("verdict"), "not_executed")
    check_in("runner crash: the note says the runner left no report evidence (was: printed no summary)", "no report evidence",
             " ".join(record.get("notes") or []))
    check_eq("runner crash: the bytes are back", (root / TEST_FILE_REL).read_bytes(), original)
    check_eq("runner crash: restore verified", (record.get("restore") or {}).get("verified"), True)
    proc = run_script("probe_by_code.py", "--task", TASK, "--dispatch", "S5-qa-code-critic-9",
                      "--test", f"{TEST_FILE_REL}::test_add", "--instance", "test_add", "--json",
                      cwd=root, env=env_for(root, stub))
    record = json.loads(proc.stdout) if proc.stdout.strip().startswith("{") else {}
    # RH1-8 B3: the open dispatch is asked BEFORE the first byte, so a bad id is a refusal (exit 2), not a
    # `not_executed` after a mutation; the bytes were never touched.
    check("bad dispatch: exit 2", proc.returncode == 2, proc.stdout + proc.stderr)
    check_eq("bad dispatch: refused", record.get("status"), "refused")
    check_in("bad dispatch: the refusal names the id", "S5-qa-code-critic-9", record.get("error", ""))
    check_eq("bad dispatch: the bytes are untouched", (root / TEST_FILE_REL).read_bytes(), original)


def a_run_that_executed_nothing_keeps_the_standing_record(stub: Path) -> None:
    """t-177: an `intended_failure` record is replaced only by the record of a run that executed the test.
    A `not_executed` attempt (a stand that was down, a refused request) used to overwrite it, and the
    evidence that a probe had passed - what probe_debt.py settles - was gone."""
    root = project()
    try:
        path = root / "qa-factory" / "artifacts" / TASK / "work" / "probes" / "test_add.json"
        standing = {"schema_version": 1, "verdict": "intended_failure", "instance_id": "test_add",
                    "test_file_sha256": "f" * 64, "recorded_at": "2026-09-30T05:02:39+00:00",
                    "publish": {"published": False}, "receipt": None}
        write_json(path, standing)
        original = (root / TEST_FILE_REL).read_bytes()
        proc, record = run(root, stub, f"{TEST_FILE_REL}::test_add", "test_add", PROBE_STUB_CRASH="1")
        kept = read_record(root, "test_add")
        check_eq("kept: the run itself reports not_executed", (proc.returncode, record.get("verdict")), (1, "not_executed"))
        check_eq("kept: the stored verdict is still intended_failure", kept.get("verdict"), "intended_failure")
        check_eq("kept: and its measured bytes", kept.get("test_file_sha256"), "f" * 64)
        check_eq("kept: every other stored key is as it was",
                 {k: v for k, v in kept.items() if k != "last_attempt"}, standing)
        attempt = kept.get("last_attempt") or {}
        check_eq("kept: last_attempt names the verdict", attempt.get("verdict"), "not_executed")
        check("kept: last_attempt carries the time and the cause",
              bool(attempt.get("at")) and "no row of the junit-xml report" in str(attempt.get("why")), str(attempt))   # the walk's check-row note
        check_eq("kept: the test bytes are back", (root / TEST_FILE_REL).read_bytes(), original)
        # a run that executed replaces it, whatever it found
        write_json(root / "qa-factory" / "artifacts" / TASK / "work" / "probes" / "test_dead_assert.json",
                   dict(standing, instance_id="test_dead_assert"))
        proc, record = run(root, stub, f"{TEST_FILE_REL}::test_dead_assert", "test_dead_assert")
        now = read_record(root, "test_dead_assert")
        check_eq("an executed run (no_failure) replaces the intended_failure record",
                 (record.get("verdict"), now.get("verdict"), "last_attempt" in now), ("no_failure", "no_failure", False))
        proc, record = run(root, stub, f"{TEST_FILE_REL}::test_add", "test_add")
        now = read_record(root, "test_add")
        check_eq("an executed run (intended_failure) replaces it too: new bytes, no last_attempt",
                 (now.get("verdict"), now.get("test_file_sha256") == PBC.sha256(original), "last_attempt" in now),
                 ("intended_failure", True, False))
    finally:
        cleanup(root)
        cleanup_beside(root)
    path = temp_dir("qa-keep-record-") / "r.json"
    try:
        attempt = {"verdict": "not_executed", "recorded_at": "t", "notes": ["a", "the stand is down"]}
        check_eq("no stored record: nothing is kept", PBC.keep_standing_record(path, attempt), False)
        write_json(path, {"verdict": "no_failure"})
        check_eq("a stored no_failure is replaced as before", PBC.keep_standing_record(path, attempt), False)
        path.write_text("{broken", encoding="utf-8")
        check_eq("a stored record that cannot be read is replaced as before", PBC.keep_standing_record(path, attempt), False)
        write_json(path, {"verdict": "intended_failure"})
        check_eq("an executed verdict is never kept away", PBC.keep_standing_record(path, dict(attempt, verdict="no_failure")),
                 False)
        check_eq("a stored intended_failure is kept against not_executed", PBC.keep_standing_record(path, attempt), True)
        check_eq("...with the LAST note as the cause", json.loads(path.read_text(encoding="utf-8"))["last_attempt"],
                 {"at": "t", "verdict": "not_executed", "why": "the stand is down"})
        # B-373 R10 / E23: `incomplete` (the tool could not read the run) judged nothing about the test either,
        # so it never replaces an intended_failure; its last_attempt names ITS verdict
        write_json(path, {"verdict": "intended_failure"})
        incomplete = dict(attempt, verdict="incomplete", notes=["a", "the library's wording differs"])
        check_eq("an incomplete answer never replaces an intended_failure record",
                 PBC.keep_standing_record(path, incomplete), True)
        check_eq("...and last_attempt says incomplete, with the cause",
                 json.loads(path.read_text(encoding="utf-8"))["last_attempt"],
                 {"at": "t", "verdict": "incomplete", "why": "the library's wording differs"})
        write_json(path, {"verdict": "no_failure"})
        check_eq("an incomplete answer over a stored no_failure is not 'kept' (nothing to protect)",
                 PBC.keep_standing_record(path, incomplete), False)
    finally:
        cleanup(path.parent)


def multiline_keeps_line_count() -> None:
    data = TEST_FILE.encode("utf-8")
    spec = PBC.parse_node(f"{TEST_FILE_REL}::test_multiline")
    mutated, detail = PBC.plan_mutation(data, spec, "invert", "test_multiline")
    check_eq("multiline invert: the file keeps its line count", mutated.count(b"\n"), data.count(b"\n"))
    check_eq("multiline invert: the assert's first line is the location", detail["line"], 35)
    try:
        PBC.plan_mutation(data, spec, "expected", "test_multiline")
        check("expected is no mutation any more (N7)", False)
    except PBC.Refusal as exc:
        check_in("expected is refused by the plan with the one that remains", "--mutation is one of invert", str(exc))
    try:
        PBC.plan_mutation(b"def test_g():\n    assert size() > 1\n", PBC.parse_node("t.py::test_h"), "invert", "i")
        check("an unknown function is refused", False)
    except PBC.Refusal as exc:
        check_in("an unknown function is refused by name", "test_h", str(exc))


SRC_HAMCREST_MULTILINE = (b"from hamcrest import assert_that, equal_to\n\n\ndef test_h():\n    x = 1\n    assert_that(\n"
                          b"        add(2, 2),\n        equal_to(\n            4\n        ),\n    )\n    assert True\n")
SRC_LITERAL_MULTILINE = (b"def test_l():\n    assert name(\n    ) == [\n        1,\n        2,\n    ], 'msg'\n"
                         b"    assert True\n")
SRC_ORACLE_HELPER = b"def helper():\n    assert got == want, 'm'\n\n\ndef test_o():\n    helper()\n"
# (label, source, node, mutation, extra arguments, the statement after, the marker, the literal pair,
#  sha256[:16] over the mutated bytes + the sorted-key JSON of the detail). The digest is the byte golden;
#  the readable columns say which part of it a failure is about (t-667 D7, E13: characterised BEFORE the move).
PLAN_GOLDEN = [
    ("add invert", TEST_FILE.encode(), "test_add", "invert", {},
     'assert not (add(2, 2) == 4), "probe-IID invert: add(2, 2) == 4"', "probe-IID invert: add(2, 2) == 4",
     (None, None), "9c9aa8bd02ea3963"),
    ("method invert", TEST_FILE.encode(), "TestCalc::test_method", "invert", {},
     'assert not (result in [6, 7]), "probe-IID invert: result in [6, 7]"', "probe-IID invert: result in [6, 7]",
     (None, None), "cec6844c3379146e"),
    ("multiline invert", TEST_FILE.encode(), "test_multiline", "invert", {},
     'assert not (add(\n        2, 2\n    ) == 4\n\n), "probe-IID invert: add( 2, 2 ) == 4"',
     "probe-IID invert: add( 2, 2 ) == 4", (None, None), "67219c94a9f69b61"),
    ("hamcrest invert", TEST_FILE.encode(), "test_hamcrest", "invert", {},
     'assert_that(add(2, 2), __import__("hamcrest").is_not(equal_to(4)), "probe-IID invert: equal_to(4)")',
     "probe-IID invert: equal_to(4)", (None, None), "172ee75ac819028a"),
    ("hamcrest multiline invert", SRC_HAMCREST_MULTILINE, "test_h", "invert", {},
     'assert_that(add(2, 2), __import__("hamcrest").is_not(equal_to(\n            4\n        ))\n\n\n, '
     '"probe-IID invert: equal_to( 4 )")', "probe-IID invert: equal_to( 4 )", (None, None), "15b7817f941490fd"),
    ("literal over several lines, invert", SRC_LITERAL_MULTILINE, "test_l", "invert", {},
     'assert not (name(\n    ) == [\n        1,\n        2,\n    ]), "probe-IID invert: name( ) == [ 1, 2, ]"',
     "probe-IID invert: name( ) == [ 1, 2, ]", (None, None), "f30684423a999bb9"),
    ("a BOM stays: invert", b"\xef\xbb\xbf" + TEST_FILE.encode(), "test_add", "invert", {},
     'assert not (add(2, 2) == 4), "probe-IID invert: add(2, 2) == 4"', "probe-IID invert: add(2, 2) == 4",
     (None, None), "cba702e7c2fc510a"),
    ("an oracle function", SRC_ORACLE_HELPER, "test_o", "invert", {"oracle_function": "helper",
                                                                    "oracle_note": "via helper"},
     'assert not (got == want), "probe-IID invert: got == want"', "probe-IID invert: got == want", (None, None),
     "dc6a95fdb21b33f1"),
]
# (label, source, node, mutation, extra arguments, what the refusal says)
PLAN_REFUSALS = [
    ("expected is no mutation any more", TEST_FILE.encode(), "test_add", "expected", {}, "--mutation is one of invert"),
    ("a source that does not parse", b"def test_s(:\n", "test_s", "invert", {}, "tests/test_calc.py does not parse"),
    ("no assert", TEST_FILE.encode(), "test_no_assert", "invert", {}, "the function body has no assert"),
    ("an unknown mutation", TEST_FILE.encode(), "test_add", "other", {}, "--mutation is one of invert"),
]


def plan_mutation_is_pinned() -> None:
    """t-667 D7, characterisation: `plan_mutation` over assert and assert_that statements, one line and
    several, both mutations, a BOM, an oracle function, and every refusal it raises itself: the mutated
    bytes and the detail are a byte golden, and the file keeps its line count and its BOM."""
    for label, data, node, mutation, extra, after, marker, pair, digest in PLAN_GOLDEN:
        mutated, detail = PBC.plan_mutation(data, PBC.parse_node(f"{TEST_FILE_REL}::{node}"), mutation, "IID", **extra)
        check_eq(f"D7 {label}: the statement after", detail["statement_after"], after)
        check_eq(f"D7 {label}: the marker", detail["marker"], marker)
        check_eq(f"D7 {label}: no token, no factory marker (t-2045 N2)", (detail["message_marker"], detail["message_form"]), ("", ""))
        check_eq(f"D7 {label}: the literal pair", (detail.get("literal_before"), detail.get("literal_after")), pair)
        check_eq(f"D7 {label}: line count and BOM are the source's",
                 (mutated.count(b"\n"), mutated.startswith(b"\xef\xbb\xbf")),
                 (data.count(b"\n"), data.startswith(b"\xef\xbb\xbf")))
        check_eq(f"D7 {label}: the byte golden (mutated bytes + detail)",
                 hashlib.sha256(mutated + json.dumps(detail, sort_keys=True).encode()).hexdigest()[:16], digest)
        if extra:
            check_eq(f"D7 {label}: the oracle is named in the detail",
                     (detail.get("oracle_function"), detail.get("oracle_note")),
                     (extra["oracle_function"], extra["oracle_note"]))
        else:
            check_eq(f"D7 {label}: no oracle keys in the detail", "oracle_function" in detail, False)
    for label, data, node, mutation, extra, words in PLAN_REFUSALS:
        try:
            PBC.plan_mutation(data, PBC.parse_node(f"{TEST_FILE_REL}::{node}"), mutation, "IID", **extra)
            check(f"D7 refusal {label}: refused", False)
        except PBC.Refusal as exc:
            check_in(f"D7 refusal {label}: the words", words, str(exc))


def window_validates(root: Path, record: dict) -> None:
    """The record's `window_probe` dropped into a schema-2 window instance passes
    `acceptance.validate_window` with no gap at all."""
    task_root = root / "qa-factory" / "artifacts" / TASK
    probe = record["window_probe"]
    item = {"schema_version": 2, "instance_id": "test_add", "input_hash": record["input_hash"],
            "outcome": "passed", "execution_fingerprint": "fp-1",
            "review": {"verdict": "approved", "input_hash": record["input_hash"]},
            "obligation_ids": record["obligation_ids"], "obligation_refs": OBLIGATION_REFS,
            "obligation_hash": record["obligation_hash"], "assertion_id": record["assertion_id"],
            "defect_location": record["defect_location"],
            "change_disposition": "new_or_changed", "change_basis_ref": "manifest:TC-100",
            "probe": probe, "evidence_refs": record["evidence_refs"]}
    window = {"schema_version": 2, "input_hash": "window-1", "required_quality_checks": [],
              "quality_receipts": [], "instances": [item]}
    gaps = acceptance.validate_window(window, task_root)
    check_eq("validate_window: no gap on a window built from the record", gaps, [])
    broken = json.loads(json.dumps(window))
    broken["instances"][0]["probe"]["verdict"] = "no_failure"
    check_in("validate_window: a no_failure probe is a sensitivity gap", "sensitivity:test_add",
             acceptance.validate_window(broken, task_root))


def through_real_run_suite() -> None:
    """The real `run_suite.py --request` accepts the request the script writes: a fresh
    project whose `pytest` is the red_sandbox test's stand-in (it imports the product and runs
    the function; no real pytest anywhere) — the typed request validates, the job store takes
    it, the evidence lands under the task, and the verdict comes back through the same reader."""
    from test_red_sandbox_probe import FAKE_PYTEST
    root = project()
    fake_pytest = root.parent / (root.name + "-bin") / "pytest"
    fake_pytest.write_text(FAKE_PYTEST, encoding="utf-8")
    original = (root / TEST_FILE_REL).read_bytes()
    try:
        env = dict(os.environ, CLAUDE_PROJECT_DIR=str(root))
        env.pop("PROBE_RUN_SUITE", None)
        model_entries(root, None, f"{TEST_FILE_REL}::test_add", "test_add")
        proc = run_script("probe_by_code.py", "--task", TASK, "--dispatch", DISPATCH, "--test",
                          f"{TEST_FILE_REL}::test_add", "--instance", "test_add", "--json",
                          cwd=root, env=env)
        record = json.loads(proc.stdout) if proc.stdout.strip().startswith("{") else {}
        check("real run_suite: exit 0", proc.returncode == 0, proc.stdout + proc.stderr)
        check_eq("real run_suite: intended_failure through the real runner", record.get("verdict"), "intended_failure")
        # t-2064 P4b: the aggregate has no `run` block; the run's label is the name of the evidence file it names
        check_eq("real run_suite: the label is a red_probe run (the evidence file's name)",
                 Path(str(record.get("evidence_ref") or "")).name[:10], "red_probe-")
        task_root = root / "qa-factory" / "artifacts" / TASK
        check("real run_suite: no run block was written for the red probe",
              not list((task_root / "work" / "run-blocks").glob("*")) or
              all("author1" in p.name for p in (task_root / "work" / "run-blocks").glob("*")))
        jobs = list((task_root / "state" / "execution-jobs").glob("*.json"))
        check("real run_suite: the job store holds the probe's job", len(jobs) >= 1)
        check_eq("real run_suite: the bytes are back", (root / TEST_FILE_REL).read_bytes(), original)
    finally:
        cleanup(root)
        cleanup_beside(root)


def two_profiles_over_one_root(stub: Path) -> None:
    """EP1-16 (A-K4, A-K5): the 12586 shape - profiles `unit` and `ui` over one `tests/` root and one cwd. The probe
    used to hand the builder no profile, so a row that NAMED `unit` still met "profiles share the test root" and the
    mutation probe never ran. Now the row's profile reaches the builder (A-K1) and the probe runs and judges; a row
    that names none is still refused, not run under the first profile, and the refusal names the row door only -
    this tool has no `--profile` (FR-2)."""
    root = project(shared_second=True, row_profile="unit")
    try:
        proc, record = run(root, stub, f"{TEST_FILE_REL}::test_add", "test_add")
        check("A-K4 two profiles, the row names `unit`: exit 0", proc.returncode == 0, proc.stdout + proc.stderr)
        check_eq("A-K4 the probe is built, run and judged: intended_failure", record.get("verdict"), "intended_failure")
        check_not_in("A-K4 no refusal note", "MineRefusal", " ".join(str(n) for n in record.get("notes") or []))
        request = json.loads((root / "qa-factory" / "artifacts" / TASK / "work" / "probe-requests"
                              / "probe-walk-test_add-1.json").read_text(encoding="utf-8"))   # t-2064 P4b: a walk's request, per run
        check_eq("A-K4 the request runs under the profile the row names", request.get("profile_id"), "unit")
    finally:
        cleanup(root)
        cleanup_beside(root)
    root = project(shared_second=True)
    try:
        original_k5 = (root / TEST_FILE_REL).read_bytes()
        proc, record = run(root, stub, f"{TEST_FILE_REL}::test_add", "test_add")
        notes = " ".join(str(n) for n in record.get("notes") or [])
        check_eq("A-K5 two profiles, the row names none: not executed (nothing is proven by a refused run)",
                 record.get("verdict"), "not_executed")
        check_in("A-K5 the note says the profiles share the root", "profiles unit, ui share the test root `tests`", notes)
        check_in("A-K5 and names the manifest-row door", "`profile_id`", notes)
        check_not_in("A-K5 and NOT --profile, which this tool does not accept", "--profile", notes)
        check("A-K5 no request was written: nothing ran under the first profile",
              not list((root / "qa-factory" / "artifacts" / TASK / "work" / "probe-requests").glob("probe-*")))   # any name: a walk's are probe-walk-<IID>-<run>
        # RH1-8 F4: this is a LATE refusal (profile, in `build_mine_request`, after the mutant is written): the bytes must be back
        check_eq("A-K5 the bytes are back after the late refusal", (root / TEST_FILE_REL).read_bytes(), original_k5)
    finally:
        cleanup(root)
        cleanup_beside(root)
    root = project(shared_second=True, row_profile="ghost")
    try:
        proc, record = run(root, stub, f"{TEST_FILE_REL}::test_add", "test_add")
        text = " ".join([proc.stdout, proc.stderr] + [str(n) for n in record.get("notes") or []])
        check_in("A-K6 a profile the config does not hold is refused naming it", "`ghost`", text)
        check_in("A-K6 and the profile_ids the config does hold", "unit, ui", text)
        check_not_in("A-K6 not as a gap of the onboarding", "gap of the onboarding", text)
        check("A-K6 and no verdict of a run", record.get("verdict") != "intended_failure", str(record.get("verdict")))
    finally:
        cleanup(root)
        cleanup_beside(root)


def cleanup_beside(root: Path) -> None:
    for extra in root.parent.glob(root.name + "-*"):
        if extra.is_dir():
            cleanup(extra)
        else:
            extra.unlink(missing_ok=True)


def oracle_in_a_helper(root: Path, stub: Path) -> None:
    """The expectation lives in a module several tests share, and the test body asserts nothing.

    This is the shape that made `probe_by_code` refuse nine times on TP1-13797 and send one
    tooling defect back to the author in four windows. The probe now follows the oracle one hop
    out, mutates it there, says where it went, and puts the helper back.
    """
    helper = root / "tests" / "expectations.py"
    original, stamp = helper.read_bytes(), helper.stat().st_mtime_ns
    test_original = (root / TEST_FILE_REL).read_bytes()
    proc, record = run(root, stub, f"{TEST_FILE_REL}::test_via_helper", "test_via_helper")
    check("helper oracle: exit 0", proc.returncode == 0, proc.stdout + proc.stderr)
    check_eq("helper oracle: the mutated expectation fires", record.get("verdict"),
             "intended_failure")
    check_eq("helper oracle: the expected location is in the helper, not the test",
             record.get("expected_location"), "tests/expectations.py:2")
    # t-2064 P4b: the walk's record names the check it mutated by its key, `<helper file>:<line>`, not by `oracle_function` / `oracle_note`
    # (the aggregate's `mutation_detail` is `{file, line, end_line, checks}`); the old pins on those two keys are replaced by the key, and
    # the lost shared-file warning is a question in the report
    check_eq("helper oracle: the record names the check it mutated, in the helper", [c.get("key") for c in record.get("checks") or []],
             ["tests/expectations.py:2"])
    check_eq("helper oracle: the helper is restored byte for byte", helper.read_bytes(), original)
    check_eq("helper oracle: and its mtime is put back", helper.stat().st_mtime_ns, stamp)
    check_eq("helper oracle: the test file was never touched",
             (root / TEST_FILE_REL).read_bytes(), test_original)
    check_eq("helper oracle: the restore is verified",
             (record.get("restore") or {}).get("verified"), True)
    check_eq("helper oracle: the probe's identity is still the test file's sha",
             record.get("test_file_sha256"), PBC.sha256(test_original))


# --- the reader of the run's report ----------------------------------------------------------------

def junit_file(directory: Path, name: str, body: str) -> Path:
    path = directory / name
    path.write_text('<?xml version="1.0" encoding="utf-8"?>\n' + body, encoding="utf-8")
    return path


def report_rows_as_before() -> None:
    """`report_rows` gives the row the private JUnit reader gave, whichever way the shared reader
    shapes its own: the failure outranks the error, the failure's own message and stack decide,
    a skip beside a failure is still a failure, a skip alone stays a skip."""
    if not hasattr(PBC, "report_rows"):
        check("report rows: the probe reads its report through one function that wraps the shared reader", False)
        return
    directory = temp_dir("qa-probe-rows-")
    try:
        both = junit_file(directory, "both.xml",
                          '<testsuites><testsuite name="s">'
                          '<testcase classname="a.b" name="t_both"><error message="E1">tb-error</error>'
                          '<failure message=" F1 ">tb-failure</failure></testcase>'
                          '<testcase classname="a.b" name="t_error"><error message="E2">tb-error-2</error></testcase>'
                          '<testcase classname="a.b" name="t_skip_fail"><skipped message="why"/>'
                          '<failure message="F3">tb-3</failure></testcase>'
                          '<testcase classname="a.b" name="t_skip"><skipped message="not now"/></testcase>'
                          '<testcase classname="" name="t_bare"/>'
                          '<testcase classname="a.b" name="t_two_failures"><failure message="first">one</failure>'
                          '<failure message="second">two</failure></testcase>'
                          '</testsuite></testsuites>')
        rows = {r["test_id"]: r for r in PBC.report_rows(both, "junit-xml")}
        want = {
            "a.b::t_both": ("failed", "F1", "tb-failure"),
            "a.b::t_error": ("error", "E2", "tb-error-2"),
            "a.b::t_skip_fail": ("failed", "F3", "tb-3"),
            "a.b::t_skip": ("skipped", "", ""),
            "t_bare": ("passed", "", ""),
            "a.b::t_two_failures": ("failed", "first", "one"),
        }
        check_eq("report rows: the same tests, once each", sorted(rows), sorted(want))
        for test_id, expected in want.items():
            row = rows.get(test_id) or {}
            check_eq(f"report rows {test_id}: status, message, text as the private reader read them",
                     (row.get("status"), row.get("message"), row.get("text")), expected)
        same = PBC.report_rows(both, "pytest")
        check_eq("report rows: `pytest` is read the same as `junit-xml`", same, PBC.report_rows(both, "junit-xml"))
        try:
            PBC.report_rows(both, "cucumber")
            check("report rows: an unknown reporter is refused", False)
        except ValueError as exc:
            check_in("report rows: the refusal names the reporter and what is known", "cucumber", str(exc))
            check_in("report rows: and the readers there are", "junit-xml", str(exc))
        try:
            PBC.report_rows(junit_file(directory, "broken.xml", "<testsuite><testcase"), "junit-xml")
            check("report rows: broken XML propagates", False)
        except ET.ParseError:
            check("report rows: broken XML still raises the parse error the probe notes", True)
    finally:
        cleanup(directory)


def reporter_in_the_summary(stub: Path) -> None:
    """The run's summary says which reporter wrote the report, and the probe reads it with that
    reader. A summary that names none is read as JUnit, as before; one the reader does not know is
    `not_executed` with the reason, not a crash and not a guess.

    Every probe here runs in a project of its own: a second probe of test_add over the same bytes is
    ANSWERED (`already_probed`, D-0018), not run, so one shared project would test the repeat answer
    and never the reader. The receipt of a run that names no reporter is the base the others are
    compared with."""
    def probed(name: str):
        root = project()
        try:
            original = (root / TEST_FILE_REL).read_bytes()
            proc, record = run(root, stub, f"{TEST_FILE_REL}::test_add", "test_add", PROBE_STUB_REPORTER=name)
            written = normalised(root, proc.returncode, read_record(root, "test_add"))
            return proc, record, written, (root / TEST_FILE_REL).read_bytes() == original
        finally:
            cleanup(root)
            cleanup_beside(root)

    _proc, _record, base, _back = probed("")
    for name, label in (("junit-xml", "junit-xml"), ("pytest", "pytest"), ("", "no reporter")):
        proc, _record, written, _back = probed(name)
        check(f"summary names {label}: exit 0", proc.returncode == 0, proc.stdout + proc.stderr)
        check_eq(f"summary names {label}: the receipt is the one written with no reporter named", written, base)
    for name in ("cucumber", "none"):
        proc, record, _written, back = probed(name)
        notes = " ".join(record.get("notes") or [])
        check(f"reporter {name!r}: exit 1, a verdict was recorded", proc.returncode == 1, proc.stdout + proc.stderr)
        check_eq(f"reporter {name!r}: not_executed", record.get("verdict"), "not_executed")
        check_in(f"reporter {name!r}: the note carries the reason and the reporter", f"unknown reporter '{name}'", notes)
        check_in(f"reporter {name!r}: and says what the reader knows", "expected one of", notes)
        check_not_traceback(f"reporter {name!r}", proc)
        check_eq(f"reporter {name!r}: the bytes are back", back, True)
        check_eq(f"reporter {name!r}: restore verified", (record.get("restore") or {}).get("verified"), True)


def check_not_traceback(label: str, proc) -> None:
    check(f"{label}: no traceback", "Traceback" not in (proc.stderr or "") and "Traceback" not in (proc.stdout or ""),
          proc.stderr[-300:])


# --- a test that is not Python -----------------------------------------------------------------------

def tree_state(root: Path) -> dict:
    """Every file under the project with its bytes' sha256 and mtime: a refusal changes none."""
    return {p.relative_to(root).as_posix(): (sha256_of(p), p.stat().st_mtime_ns)
            for p in sorted(root.rglob("*")) if p.is_file()}


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def refusal_text(path: str, suffix: str, directory: bool = False) -> str:
    """B-373 c (K3): the refusal of a file whose suffix has no `assertion_probes` entry, verbatim up to the
    entry shape: what is wrong (a gap of the factory's DATA), what it expected (one entry, its shape), and the
    door that exists today with its arguments inline (no pointer to a brief the role does not have open)."""
    what = (f"{path} is a directory, not a test file" if directory
            else f"no assertion probe for {suffix or 'a file with no suffix'} ({path})")
    return (f"probe_by_code: {what} - factory data gap: references/detectors.json `assertion_probes` has entries for "
            "(csharp: .cs; java: .java; typescript: .ts .tsx .js .jsx .mjs .cjs .mts .cts) and none for this suffix, "
            "so this probe reads no test of it (it never guesses a grammar). The row to add is one entry in that "
            f"file, the factory's data and not the author's test: {AD.ENTRY_SHAPE}. Return it as a tooling finding. "
            "Until the row exists the probe that breaks the product in a throwaway copy works for any language: "
            "red_sandbox.py --probe --repo <project root> --request <mutations.json> --task-root <task root>. "
            "Nothing was changed.")


def non_python_test_refused(root: Path, stub: Path) -> None:
    (root / "tests" / "Calc.kt").write_text("class CalcTests { fun adds() {} }\n", encoding="utf-8")
    (root / "tests" / "CalcTests.cs").write_text("public class CalcTests { }\n", encoding="utf-8")
    (root / "tests" / "calc.spec.ts").write_text("it('adds', () => {});\n", encoding="utf-8")
    (root / "tests" / "runner").write_text("#!/bin/sh\n", encoding="utf-8")
    # K3: a suffix with no entry is a refusal that names the data gap, the entry shape and the door
    cases = (("tests/Calc.kt::CalcTests.adds", "tests/Calc.kt", ".kt", False),
             ("tests\\Calc.kt::CalcTests.adds", "tests/Calc.kt", ".kt", False),
             ("tests/runner::test_x", "tests/runner", "", False),
             ("tests::test_x", "tests", "", True))
    for spec, shown, suffix, directory in cases:
        before = tree_state(root)
        proc, payload = run(root, stub, spec, "test_add")
        label = f"no entry {spec!r}"
        check_eq(f"{label}: exit 2", proc.returncode, 2)
        check_eq(f"{label}: refused", payload.get("status"), "refused")
        check_eq(f"{label}: the text says what is wrong, what it expected and the door",
                 payload.get("error"), refusal_text(shown, suffix, directory))
        check_in(f"{label}: the door is the product-breaking probe, with its arguments inline",
                 "red_sandbox.py --probe --repo <project root> --request <mutations.json> --task-root <task root>",
                 payload.get("error", ""))
        check_in(f"{label}: and the reason is worded as the data gap it is", "factory data gap", payload.get("error", ""))
        check_not_in(f"{label}: no pointer to a brief", "brief", payload.get("error", ""))
        check_not_in(f"{label}: no doubled space where a suffix was", "read  source", payload.get("error", ""))
        check_eq(f"{label}: no file changed, none written (no request, no receipt)", tree_state(root), before)
    # A language that HAS an entry reaches the detector path and is refused for its own reason (no such test in
    # this file) - never for "not Python"; the tree is unchanged all the same.
    def kept(tree: dict) -> dict:  # the lock a probe takes before it reads the test is never deleted (B-373 a)
        # (and the window's model file the wrapper writes: world, not the probe's work; `run` rewrites the same bytes at a new mtime)
        return {k: v for k, v in tree.items() if not k.endswith(".lock") and "/work/probe-models/" not in k}

    # t-2064 P4b: the default road lists the checks first; a test whose body holds none the factory reads (no such declaration, no
    # recognised assertion) is the EMPTY-PLAN refusal, for either reason, and the same words
    for spec, why in (("tests/CalcTests.cs::CalcTests.Adds", "no check of a form the factory reads was found"),
                      ("tests/calc.spec.ts::adds", "no check of a form the factory reads was found")):
        model_entries(root, stub, spec, "test_add")     # world, written before the snapshot: the call itself must change nothing
        before = kept(tree_state(root))
        proc, payload = run(root, stub, spec, "test_add")
        check_eq(f"entry {spec!r}: exit 2, refused", (proc.returncode, payload.get("status")), (2, "refused"))
        check_in(f"entry {spec!r}: the refusal is about the test's own shape ({why})", why, payload.get("error", ""))
        check_not_in(f"entry {spec!r}: it is not the old `not a Python test`", "not a Python test", payload.get("error", ""))
        check_eq(f"entry {spec!r}: no file changed", kept(tree_state(root)), before)
    # t-2045 N1: `--at` is read for every language. On a Python node a line that holds no check (the `def` line, 5) is refused
    # like any other language's: the text names the nearest check below (line 6) and the doors, and nothing is changed.
    before = kept(tree_state(root))
    proc = run_script("probe_by_code.py", "--task", TASK, "--dispatch", DISPATCH, "--test",
                      f"{TEST_FILE_REL}::test_add", "--instance", "test_add", "--at", "5", "--json",
                      cwd=root, env=env_for(root, stub))
    payload = json.loads(proc.stdout) if proc.stdout.strip().startswith("{") else {}
    check_eq("--at on a Python node: exit 2, refused", (proc.returncode, payload.get("status")), (2, "refused"))
    check_in("--at on a line with no check: the text says so", "holds no check of a form the factory reads", payload.get("error", ""))
    check_in("...and names the nearest check below as the door", "`--at 6`", payload.get("error", ""))
    check_not_in("...and is no longer the old `not Python`", "not Python", payload.get("error", ""))
    check_eq("--at on a Python node: nothing changed", kept(tree_state(root)), before)
    # A path that IS Python but is not shaped like a node keeps its own refusal.
    proc, payload = run(root, stub, "tests/test_calc.py", "test_add")
    check_eq("no `::` at all: still refused with the shape wanted", (proc.returncode, payload.get("status")), (2, "refused"))
    check_in("no `::` at all: and the shape is named", "<file>::<function>", payload.get("error", ""))


# --- the run directory -------------------------------------------------------------------------------

LAUNCHER = '''
"""Runs probe_by_code.main() with every call of the request builder written to a log."""
import json
import os
import sys

sys.path.insert(0, os.environ["PROBE_SCRIPTS_DIR"])
import execution_request as ER

real = ER.build_mine_request


def recording(*args, **kwargs):
    entry = {"cwd": kwargs.get("cwd") or "", "sandbox_root": kwargs.get("sandbox_root") or "",
             "purpose": kwargs.get("purpose") or ""}
    try:
        return real(*args, **kwargs)
    except Exception as exc:
        entry["refused"] = type(exc).__name__ + ": " + str(exc)
        raise
    finally:
        with open(os.environ["PROBE_CALL_LOG"], "a", encoding="utf-8") as log:
            log.write(json.dumps(entry) + "\\n")


ER.build_mine_request = recording
import probe_by_code

sys.argv = ["probe_by_code.py"] + sys.argv[1:]
probe_by_code.main()
'''


def run_recorded(root: Path, stub: Path, test: str, instance: str) -> tuple:
    """(process, the calls the probe made to the request builder, in order)."""
    model_entries(root, stub, test, instance)
    launcher = stub.parent / "launcher.py"
    launcher.write_text(LAUNCHER, encoding="utf-8")
    log = stub.parent / "calls.jsonl"
    log.unlink(missing_ok=True)
    env = env_for(root, stub, PROBE_CALL_LOG=str(log), PROBE_SCRIPTS_DIR=str(SCRIPTS),
                  PYTHONDONTWRITEBYTECODE="1")
    proc = subprocess.run([PY, "-B", str(launcher), "--task", TASK, "--dispatch", DISPATCH, "--test", test,
                           "--instance", instance, "--json"],
                          capture_output=True, text=True, encoding="utf-8", errors="replace",
                          cwd=str(root), env=env, timeout=300)
    calls = [json.loads(ln) for ln in log.read_text(encoding="utf-8").splitlines() if ln.strip()] \
        if log.is_file() else []
    return proc, calls


def run_directory_is_given(root: Path, stub: Path, label: str, wanted: Path) -> None:
    proc, calls = run_recorded(root, stub, f"{TEST_FILE_REL}::test_add", "test_add")
    record = json.loads(proc.stdout) if proc.stdout.strip().startswith("{") else {}
    check(f"{label}: exit 0", proc.returncode == 0, proc.stdout + proc.stderr)
    check_eq(f"{label}: the request builder is called once", len(calls), 1)
    check(f"{label}: no call is made without the run directory", all(c.get("cwd") for c in calls), json.dumps(calls))
    check_eq(f"{label}: the first call carries the profile's run directory",
             (calls[0].get("cwd") if calls else None), str(wanted.resolve()))
    check(f"{label}: and no call goes through a refusal",
          not any(c.get("refused") for c in calls), json.dumps(calls))
    check(f"{label}: it is --cwd, never --sandbox-root (the probe has no clone)",
          all(not c.get("sandbox_root") for c in calls))
    check_eq(f"{label}: the probe still ran, in that directory", record.get("verdict"), "intended_failure")
    request_path = root / "qa-factory" / "artifacts" / TASK / "work" / "probe-requests" / "probe-walk-test_add-1.json"
    request = json.loads(request_path.read_text(encoding="utf-8")) if request_path.is_file() else {}
    check_eq(f"{label}: the request's command runs in the same directory",
             str(Path((request.get("command") or {}).get("cwd") or "").resolve()), str(wanted.resolve()))


def run_directory(stub: Path) -> None:
    """Two projects of their own: a second probe of test_add over the same bytes is ANSWERED
    (`already_probed`), and an answer launches nothing to record."""
    root = project()
    try:
        run_directory_is_given(root, stub, "run directory '.'", root)
    finally:
        cleanup(root)
        cleanup_beside(root)
    # A profile that runs in a subdirectory: the directory the retry used to work out after the
    # refusal is the one handed over on the first call.
    root = project()
    try:
        app = root / "app"
        app.mkdir()
        for name in ("tests", "calc.py", "hamcrest.py"):
            (root / name).rename(app / name)
        config_path = root / "qa-factory" / "config.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config["profiles"][0]["commands"]["one_test"]["cwd"] = "app"
        write_json(config_path, config)
        run_directory_is_given(root, stub, "run directory 'app'", app)
    finally:
        cleanup(root)
        cleanup_beside(root)


# --- the live receipt (D-0010): written, accepted unchanged, published, never downgrading -----------

def task_of(root: Path) -> Path:
    return root / "qa-factory" / "artifacts" / TASK


def manifest_of(root: Path) -> dict:
    return json.loads((task_of(root) / "work" / "automation-manifest.json").read_text(encoding="utf-8"))


def row_of(root: Path, iid: str = "test_add") -> dict:
    return next(t for t in manifest_of(root)["tests"] if t.get("instance_id") == iid)


def binding_of(root: Path, oid: str = "OB-ADD-1") -> dict:
    return next((b for b in manifest_of(root).get("obligation_bindings") or []
                 if b.get("obligation_id") == oid), {})


def receipt_files(root: Path, stem: str = "test_add") -> list:
    directory = task_of(root) / "work" / "sensitivity-receipts"
    return sorted(directory.glob(f"{stem}-live-*.json")) if directory.is_dir() else []


def live_receipt_and_publish(root: Path, stub: Path) -> dict:
    """An `intended_failure` writes an immutable live receipt that `contract.sensitivity_proof_issues`
    accepts UNCHANGED, and publishes it in `tests[]` and in the obligation binding."""
    task = task_of(root)
    proc, record = run(root, stub, f"{TEST_FILE_REL}::test_add", "test_add")
    check("live receipt: exit 0", proc.returncode == 0, proc.stdout + proc.stderr)
    ref = record.get("receipt") or {}
    path = task / str(ref.get("path") or "missing")
    check("live receipt: the record says where the receipt is and it is on disk", path.is_file(), str(ref))
    check("live receipt: named <stem>-live-<16 hex>.json under work/sensitivity-receipts/",
          re.fullmatch(r"test_add-live-[0-9a-f]{16}\.json", path.name) is not None
          and path.parent == task / "work" / "sensitivity-receipts", path.as_posix())
    check_eq("live receipt: the ref's sha256 is the file's", ref.get("sha256"), PBC.sha256(path.read_bytes()))
    body = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    check_eq("live receipt: every PROOF_FIELDS is present and non-empty",
             [k for k in C.PROOF_FIELDS if not body.get(k)], [])
    check_eq("live receipt: the facts come from the author's record",
             (body.get("case_version"), body.get("test_content_hash"), body.get("source_revision"),
              body.get("build_id")), ("cv_1", row_of(root)["trace_binding"]["test_content_sha"], "source-1", "build-1"))
    check_eq("live receipt: its bytes are the raw file hash the probe measured, not the run's fingerprint",
             (body.get("test_content_hash"), body.get("test_content_hash") == record.get("input_hash")),
             (record.get("test_file_sha256"), False))
    check_eq("live receipt: and the code of those bytes (diff_scope.executable_sha), for comment-only edits",
             (body.get("test_code_sha"), record.get("test_code_sha")),
             (PL.code_sha((root / TEST_FILE_REL).read_bytes()),) * 2)
    check_eq("live receipt: it carries what the probe mutated, so a later record cannot change it (t-075 A)",
             (body.get("mutated_file"), bool(body.get("mutated_file"))), (record.get("mutated_file"), True))
    check_eq("live receipt: level, tool and mutation kind",
             (body.get("proof_level"), body.get("probe_tool"), body.get("mutation_kind"), body.get("mutation")),
             ("live", "probe_by_code.py", "assertion", "invert"))
    check_eq("live receipt: the failure is the probe's own",
             (body.get("expected_assertion_failure"), body.get("actual_failure"), body.get("assertion_location"),
              body.get("failure_kind")),
             (record.get("expected_reason"), record.get("actual_reason"), f"{TEST_FILE_REL}:6", "assertion"))
    check("live receipt: restoration evidence says what was restored and how it was verified",
          str(body.get("restoration_evidence")).startswith(f"probe_by_code: {TEST_FILE_REL} sha256 ")
          and str(body.get("restoration_evidence")).endswith(" verified restored"), str(body.get("restoration_evidence")))
    check_eq("live receipt: it points at the probe's record and carries the run evidence",
             (body.get("probe_record"), body.get("evidence_refs")), ("work/probes/test_add.json", record.get("evidence_refs")))
    check_eq("live receipt: obligation fields", (body.get("obligation_ids"), body.get("defect_location"),
                                                  body.get("assertion_id")),
             (["OB-ADD-1"], "calc.py:2", "add_returns_sum"))
    check_eq("live receipt: immutable, with its own hash", (body.get("immutable"), len(str(body.get("receipt_hash")))),
             (True, 64))
    check_eq("live receipt: the hash is the hash of the rest, the run evidence excluded",
             body.get("receipt_hash"), content_hash({k: v for k, v in body.items()
                                                     if k not in ("receipt_hash", "evidence_refs")}))
    check_eq("live receipt: the record on disk names the receipt too", read_record(root, "test_add").get("receipt"), ref)
    row = row_of(root)
    check_eq("published: the row's sensitivity_proof.receipt_ref is the receipt",
             (row.get("sensitivity_proof") or {}).get("receipt_ref"), ref)
    check_eq("published: the author's row keeps its file and case", (row.get("file"), row.get("case")),
             (TEST_FILE_REL, "TC-100"))
    # THE acceptance key: the contract's own validator takes the receipt as it is.
    check_eq("contract.sensitivity_proof_issues accepts the live receipt unchanged",
             C.sensitivity_proof_issues(row, task), [])
    reached = PL.reached(row, manifest_of(root), task)
    check_eq("reached(): the check is live", (reached["level"], reached["words"], reached["issues"]),
             ("live", "the check is live", []))
    binding = binding_of(root)
    check_eq("published: the obligation binding lists the instance, proven by an executed probe",
             (binding.get("instance_ids"), binding.get("sensitivity"), binding.get("proof_kind"),
              binding.get("probe_receipt_ref")), (["test_add"], "proven", "executed_red_probe", ref["path"]))
    publish = record.get("publish") or {}
    check_eq("FR-14: the record says what the publish did", (publish.get("published"), publish.get("row")),
             (True, "added"))
    check_eq("...binding by binding", [(b["obligation_id"], b["receipt"]) for b in publish.get("bindings") or []],
             [("OB-ADD-1", "set")])
    check_eq("...and the record on disk carries it", (read_record(root, "test_add").get("publish") or {}).get("row"),
             "added")
    check_eq("the fragment was scratch: nothing landed in the story's work folder",
             sorted(p.name for p in (task / "work").glob("probe-binding-*")), [])
    check_eq("the receipt files of the instance: one", len(receipt_files(root)), 1)
    return record


def a_rerun_is_idempotent_and_new_bytes_are_a_new_receipt(root: Path, stub: Path, first: dict) -> None:
    task = task_of(root)
    before = receipt_files(root)[0]
    frozen = before.read_bytes()
    # t-043 C: a second probe of the same bytes is ANSWERED, not run (D-0018) - exit 0, nothing written
    quiet = snapshot(root)
    proc, answered = run(root, stub, f"{TEST_FILE_REL}::test_add", "test_add")
    check("rerun: exit 0", proc.returncode == 0, proc.stdout + proc.stderr)
    # t-2064 P4b, what holds on the walk road: the repeat launches NOTHING (no run, no new request, job or check record, the same one receipt).
    # Only the aggregate is rebuilt (its rows say "the run was skipped"). The three pins after it are the spec's (t-2064 section on the
    # receipt, item 4: "all proved and the aggregate standing: `already_probed` as today") and the road does not meet them: PRODUCT QUESTION
    # 1 of t-2064-p4b2t2-report.md - they stay red, unbent.
    aggregate = "work/probes/test_add.json"
    moved = snapshot(root)
    check_eq("rerun: nothing LAUNCHED or written but the aggregate (requests, jobs, check records, receipts, manifest)",
             {k: v for k, v in moved.items() if k != aggregate}, {k: v for k, v in quiet.items() if k != aggregate})
    # t-2064 TR2-14 (B3): the repeat on the same bytes and the same model is answered `already_probed`: no walk ran, so the answer carries
    # no `plan_runs` and no `restore.runs` (it used to rebuild the aggregate with every row skipped, 0 and 0)
    check_eq("rerun: answered `already_probed`, the walk ran no check (no plan_runs, no restore.runs)",
             (answered.get("verdict"), answered.get("plan_runs"), (answered.get("restore") or {}).get("runs")), ("already_probed", None, None))
    check_eq("rerun on identical bytes: answered, not probed (spec; PRODUCT QUESTION 1)", answered.get("verdict"), "already_probed")
    check_eq("rerun: by the receipt it holds (spec; PRODUCT QUESTION 1)", (answered.get("by"), answered.get("level")), ("receipt", "live"))
    check_eq("rerun: nothing on disk moved (record, manifest, requests, jobs, receipts) (spec; PRODUCT QUESTION 1)", moved, quiet)
    # ...and a person's word passes ONE repeat: the probe runs, and lands on the same receipt
    give_word(root, "2999-01-01T00:00:00+00:00")
    proc, again = run(root, stub, f"{TEST_FILE_REL}::test_add", "test_add")
    clear_word(root)
    check("rerun with a word: exit 0", proc.returncode == 0, proc.stdout + proc.stderr)
    # the road never blocks a repeat, so the person's word is not read on it any more: the door that named "probe it again" is gone
    # (spec: "only a person's word repeats it", D-0018) - PRODUCT QUESTION 1, red, unbent.
    check_in("rerun with a word: the note records the word (PRODUCT QUESTION 1)", "probe it again", " ".join(again.get("notes") or []))
    check_eq("rerun on identical bytes: the same path", (again.get("receipt") or {}).get("path"),
             first["receipt"]["path"])
    check_eq("rerun on identical bytes: still one receipt file", len(receipt_files(root)), 1)
    check_eq("rerun on identical bytes: the receipt is untouched", before.read_bytes(), frozen)
    check_in("rerun: the note says the proof is already there", "already holds this proof",
             " ".join(again.get("notes") or []))
    check_eq("rerun: the row still names it", (row_of(root).get("sensitivity_proof") or {}).get("receipt_ref"),
             first["receipt"])
    # New bytes: the test's function changed. The manifest still binds the OLD bytes, and this probe
    # MEASURES the new ones (the raw sha256 of the file, before it mutates anything): the receipt
    # would claim bytes nobody compared with what ran, so there is none - and the note names the door.
    bound_before = row_of(root)["trace_binding"]["test_content_sha"]
    (root / TEST_FILE_REL).write_bytes((root / TEST_FILE_REL).read_bytes().replace(b'"sum must be 4"', b'"sum must be four"'))
    proc, stale = run(root, stub, f"{TEST_FILE_REL}::test_add", "test_add")
    check("stale binding: exit 0 (a verdict was recorded)", proc.returncode == 0, proc.stdout + proc.stderr)
    check_eq("stale binding: the probe itself is fine", stale.get("verdict"), "intended_failure")
    measured = str(stale.get("test_file_sha256"))
    check_eq("stale binding: the measured bytes are the file's raw sha256 now, not the manifest's claim",
             (measured, measured != bound_before), (PBC.sha256((root / TEST_FILE_REL).read_bytes()), True))
    check_eq("stale binding: no receipt", stale.get("receipt"), None)
    check_eq("stale binding: the stale fact is named", stale.get("receipt_missing"), ["test_content_hash"])
    notes = " ".join(stale.get("notes") or [])
    check_in("stale binding: the note names both hashes", f"(sha256 {measured}) is not the bytes the manifest "
             f"binds (trace_binding.test_content_sha {bound_before})", notes)
    check_in("stale binding: and the door (the author rebinds through manifest_put, then probe again)",
             "It is the author's to rebind, through `manifest_put.py` (no run needed): "
             "trace_binding.test_content_sha is the sha256 of the file's bytes", notes)
    check_in("stale binding: and warns off the run's fingerprint", "never a run block's source_fingerprint", notes)
    check_eq("stale binding: still one receipt file, the old one untouched",
             (len(receipt_files(root)), before.read_bytes()), (1, frozen))
    check_eq("stale binding: the row still names the old receipt (nothing was replaced)",
             (row_of(root).get("sensitivity_proof") or {}).get("receipt_ref"), first["receipt"])
    check_eq("stale binding: and nothing was published", (stale.get("publish") or {}).get("published"), False)
    scratch = temp_dir("qa-probe-frag-")
    try:  # through manifest_put, as the automator does: it is event-sourced, a hand edit would be projected away
        write_json(scratch / "f.json", {"tests": [{"instance_id": "test_add",
                                                   "trace_binding": {"test_content_sha": measured}}]})
        put = run_script("manifest_put.py", "--task", TASK, "--fragment", scratch / "f.json", cwd=root,
                         env=env_for(root, stub))
        check("new bytes: the author binds them through manifest_put", put.returncode == 0, put.stdout + put.stderr)
    finally:
        cleanup(scratch)
    got = PL.reached(row_of(root), manifest_of(root), task)
    check_eq("BYTES RULE: the old receipt is no longer valid for the row - no level is shown",
             (got["level"], got["words"]), (None, "not probed"))
    check_in("BYTES RULE: and the issue names the door", "probe the current bytes again", got["issues"])
    proc, changed = run(root, stub, f"{TEST_FILE_REL}::test_add", "test_add")
    check("new bytes: exit 0", proc.returncode == 0, proc.stdout + proc.stderr)
    new_ref = changed.get("receipt") or {}
    check("new bytes: a new receipt file", new_ref.get("path") not in (None, first["receipt"]["path"]), str(new_ref))
    check_eq("new bytes: two receipt files now, the first one untouched", (len(receipt_files(root)),
                                                                          before.read_bytes()), (2, frozen))
    check_eq("new bytes: live then live REPLACES the row's ref (equal rank)",
             (row_of(root).get("sensitivity_proof") or {}).get("receipt_ref"), new_ref)
    check_eq("new bytes: ...and the binding's", binding_of(root).get("probe_receipt_ref"), new_ref.get("path"))
    check_eq("new bytes: the instance is listed once", binding_of(root).get("instance_ids"), ["test_add"])
    check_eq("new bytes: the receipt binds the new test hash",
             json.loads((task / new_ref["path"]).read_text(encoding="utf-8")).get("test_content_hash"), measured)
    check_eq("new bytes: the row still validates", C.sensitivity_proof_issues(row_of(root), task), [])
    check_eq("new bytes: the record says it replaced", (changed.get("publish") or {}).get("row"), "replaced")
    check_eq("new bytes: reached() shows the live level again, for the current bytes only",
             PL.reached(row_of(root), manifest_of(root), task)["level"], "live")


def fabricate(task: Path, level: str, tag: str, iid: str = "test_add", sha: str = "") -> dict:
    """A valid receipt of a level, as the OTHER tool would have left it - by default for the bytes the
    test file holds now (its raw sha256: the one reader, Amendment 2)."""
    sha = sha or PBC.sha256((task.parents[2] / TEST_FILE_REL).read_bytes())
    body = {"instance_id": iid, "case_version": "cv_1", "test_content_hash": sha,
            "source_revision": "source-1", "build_id": "build-1", "expected_assertion_failure": "x",
            "actual_failure": "x", "assertion_location": f"{TEST_FILE_REL}:6", "failure_kind": "assertion",
            "restoration_evidence": "r", "immutable": True, "receipt_hash": "h-" + tag}
    if level == "live":
        body.update(mutation="invert", proof_level="live", probe_tool="probe_by_code.py", mutation_kind="assertion")
    else:
        body.update(mutation="real_behavior", proof_level="catches_broken_product", probe_tool="red_sandbox.py")
    path = task / "work" / "sensitivity-receipts" / f"{tag}.json"
    write_json(path, body)
    return {"path": path.relative_to(task).as_posix(), "sha256": PBC.sha256(path.read_bytes())}


def publish_orders() -> None:
    """Edge row 7: never downgrade, union the instance ids, replace at equal rank.

    Every scenario is a FRESH project: `manifest_put.py` is event-sourced, so a manifest written by
    hand over a story that already had a patch is projected away by the next one."""
    made: list = []
    try:
        _publish_orders(made)
    finally:
        for path in made:
            cleanup(path)


def _publish_orders(made: list) -> None:
    root = project()
    made.append(root)
    task = task_of(root)
    use_project(root)
    base = manifest_of(root)
    new = fabricate(task, "live", "new-live")
    product = fabricate(task, "product", "held-product")
    old_live = fabricate(task, "live", "held-live")
    record = {"verdict": "intended_failure", "instance_id": "test_add", "receipt": new,
              "obligation_ids": ["OB-ADD-1"], "restore": {"verified": True}}

    def scenario(name, row_ref, binding_ref, ids=("other",), record_over=None, plan=False, trap=False,
                 retracted=None):
        nonlocal root, task
        root = project()
        made.append(root)
        task = task_of(root)
        use_project(root)
        for level, tag, iid in (("live", "new-live", "test_add"), ("product", "held-product", "test_add"),
                                ("live", "held-live", "test_add"), ("product", "other-instance-product", "other")):
            fabricate(task, level, tag, iid)
        manifest = json.loads(json.dumps(base))
        manifest.pop("obligation_bindings", None)
        if retracted:
            manifest["retracted_instances"] = list(retracted)
        if trap:
            # The critic's trap: the test now holds bytes 2 (the file), and the row holds a
            # HIGHER-level receipt for bytes 1.
            row_ref = fabricate(task, "product", "held-product-bytes1", sha="bytes1")
            binding_ref = row_ref["path"]
            fresh_live = fabricate(task, "live", "new-live-bytes2")
            record_over = dict({"receipt": fresh_live}, **(record_over or {}))
        for test in manifest["tests"]:
            if test.get("instance_id") == "test_add":
                test.pop("sensitivity_proof", None)
                if row_ref:
                    test["sensitivity_proof"] = {"receipt_ref": row_ref}
        if binding_ref is not None:
            manifest["obligation_bindings"] = [{"obligation_id": "OB-ADD-1", "instance_ids": list(ids),
                                               "sensitivity": "proven", "proof_kind": "executed_red_probe",
                                               "probe_receipt_ref": binding_ref, "design_assessment": "sufficient"}]
        write_json(task / "work" / "automation-manifest.json", manifest)
        if plan:  # a plan that names other obligations: manifest_put refuses ours
            write_json(task / "work" / "test-plan.json", {"rows": [{
                "id": "TS-1", "schema_version": 2, "coverage_obligations": [
                    {"obligation_id": "OB-OTHER", "text": "x"}]}]})
        rec = dict(record, **(record_over or {}))
        said = PBC.publish_binding(TASK, task, rec)
        return rec, said

    rec, said = scenario("product then live", product, product["path"])
    check_eq("product then live: the row keeps the product receipt",
             (row_of(root).get("sensitivity_proof") or {}).get("receipt_ref"), product)
    check_eq("product then live: the binding keeps the product receipt", binding_of(root).get("probe_receipt_ref"),
             product["path"])
    check_eq("product then live: and the instance ids are the UNION", binding_of(root).get("instance_ids"),
             ["other", "test_add"])
    check_eq("product then live: an existing binding's other fields survive", binding_of(root).get("design_assessment"),
             "sufficient")
    check_in("product then live: the record says it kept the higher level", "kept", rec["publish"]["row"])
    check_in("product then live: for the binding too", "kept", rec["publish"]["bindings"][0]["receipt"])
    check_in("product then live: and what it said was not a claim of having bound it", "published", said)
    check_eq("product then live: the row still validates as the product level",
             PL.reached(row_of(root), manifest_of(root), task)["level"], "catches_broken_product")

    # F2: a receipt for OTHER bytes shields nothing (BYTES RULE), so the live probe of the bytes the row
    # binds now is published, and the window can bind - never "kept" behind a receipt for old bytes.
    rec, said = scenario("the critic's trap", None, None, trap=True)
    fresh = rec["receipt"]
    check_eq("bytes rule: the live receipt for bytes 2 IS published on the row",
             (row_of(root).get("sensitivity_proof") or {}).get("receipt_ref"), fresh)
    check_eq("bytes rule: ...and in the binding, with the union", (binding_of(root).get("probe_receipt_ref"),
                                                                    binding_of(root).get("instance_ids")),
             (fresh["path"], ["other", "test_add"]))
    check_eq("bytes rule: the record says it replaced, not kept", rec["publish"]["row"], "replaced")
    got = PL.reached(row_of(root), manifest_of(root), task)
    check_eq("bytes rule: the row reaches the live level for the current bytes",
             (got["level"], got["issues"]), ("live", []))
    import window_record as WR
    check_eq("bytes rule: and the window picks that receipt (through reached)",
             WR._window_receipt_ref(row_of(root), manifest_of(root), task)["path"], fresh["path"])
    rec, said = scenario("the trap, and only the old receipt is left", None, None, trap=True,
                         record_over={"receipt": None, "receipt_missing": ["test_content_hash"]})
    check_eq("bytes rule: with no new receipt the row reaches no level (FR-41)",
             PL.reached(row_of(root), manifest_of(root), task)["level"], None)
    check_eq("bytes rule: and the window picks nothing for other bytes",
             WR._window_receipt_ref(row_of(root), manifest_of(root), task), {})

    # retracted rows are not resurrected by the union
    rec, said = scenario("retracted", old_live, old_live["path"], ids=("gone", "other"), retracted=["gone"])
    check_eq("retracted ids leave the union", binding_of(root).get("instance_ids"), ["other", "test_add"])

    rec, said = scenario("live then live", old_live, old_live["path"])
    check_eq("live then live: the row's ref is replaced (equal rank)",
             (row_of(root).get("sensitivity_proof") or {}).get("receipt_ref"), new)
    check_eq("live then live: the binding's too", binding_of(root).get("probe_receipt_ref"), new["path"])
    check_eq("live then live: union again", binding_of(root).get("instance_ids"), ["other", "test_add"])
    check_eq("live then live: the record says replaced", rec["publish"]["row"], "replaced")

    rec, _ = scenario("row product, binding live", product, old_live["path"])
    check_eq("mixed: the product row stays", (row_of(root).get("sensitivity_proof") or {}).get("receipt_ref"), product)
    check_eq("mixed: the live binding is replaced", binding_of(root).get("probe_receipt_ref"), new["path"])
    rec, _ = scenario("row live, binding product", old_live, product["path"])
    check_eq("mixed: the live row is replaced", (row_of(root).get("sensitivity_proof") or {}).get("receipt_ref"), new)
    check_eq("mixed: the product binding stays", binding_of(root).get("probe_receipt_ref"), product["path"])

    tampered = {"path": product["path"], "sha256": "0" * 64}
    rec, _ = scenario("an invalid higher receipt holds nothing", tampered, "work/sensitivity-receipts/gone.json")
    check_eq("invalid product row ref (hash moved): replaced",
             (row_of(root).get("sensitivity_proof") or {}).get("receipt_ref"), new)
    check_eq("binding naming a file that is gone: replaced", binding_of(root).get("probe_receipt_ref"), new["path"])
    other = fabricate(task, "product", "other-instance-product", iid="other")
    rec, _ = scenario("a product receipt of another instance", None, other["path"])
    check_eq("a product receipt that is valid for ANOTHER instance holds nothing for this one",
             binding_of(root).get("probe_receipt_ref"), new["path"])
    check_eq("and the row is added", rec["publish"]["row"], "added")

    rec, _ = scenario("nothing there", None, None)
    check_eq("nothing before: the binding is created", (binding_of(root).get("instance_ids"),
                                                        binding_of(root).get("sensitivity")), (["test_add"], "proven"))
    rec, said = scenario("instance already listed under an alias", None, old_live["path"], ids=("test_add", "x"))
    check_eq("an instance already in the list is not listed twice", binding_of(root).get("instance_ids"),
             ["test_add", "x"])

    rec, said = scenario("no obligations", None, None, record_over={"obligation_ids": []})
    check_eq("empty obligation_ids: the row is published", (row_of(root).get("sensitivity_proof") or {}).get("receipt_ref"),
             new)
    check_eq("empty obligation_ids: no binding was made", manifest_of(root).get("obligation_bindings"), None)
    check_in("empty obligation_ids: the note is kept", "no obligation_ids", rec["publish"].get("bindings_note", ""))
    check_in("empty obligation_ids: and the printed line says so", "no obligation ids", said)

    # nothing to put at all: a higher receipt on the row and no obligations
    rec, said = scenario("only a higher row", product, None, record_over={"obligation_ids": []})
    check_in("a higher receipt on the row and nothing to bind: nothing is put", "nothing to put", said)

    # restore not verified / no receipt: nothing is published
    manifest = json.loads(json.dumps(base))
    write_json(task / "work" / "automation-manifest.json", manifest)
    stale = dict(record, receipt=None, receipt_missing=["build_id"])
    said = PBC.publish_binding(TASK, task, stale)
    check_in("no receipt: nothing published, and the missing fact is named", "build_id", said)
    check_eq("no receipt: the manifest is as it was", manifest_of(root), base)
    check_eq("another verdict publishes nothing and says nothing",
             PBC.publish_binding(TASK, task, dict(record, verdict="no_failure")), "")
    # manifest_put refuses: the plan names other obligations
    rec, said = scenario("refused", None, None, plan=True)
    check_eq("manifest_put refused: the record says so", rec["publish"]["published"], False)
    check_in("manifest_put refused: the printed line names the receipt that stays", new["path"], said)
    check("manifest_put refused: the receipt file stays", (task / new["path"]).is_file())
    check_eq("manifest_put refused: the row was not touched", "sensitivity_proof" in row_of(root), False)


PUBLISH_PUT_OK = re.compile(r"automation-manifest\.json: revision \d+, receipt [0-9a-f]{32}")
PUBLISH_KEPT_ROW = "kept: the row already names a valid receipt that catches a broken product"
PUBLISH_KEPT_BINDING = "kept: the binding already names a valid receipt that catches a broken product"
PUBLISH_NO_OBLIGATIONS = "no obligation_ids on this probe — the row is published, no binding"


def publish_dicts_are_pinned() -> None:
    """t-667 D5, characterisation (E13): what `publish_binding` writes into `record["publish"]` and returns,
    WHOLE, for every row case (added / replaced / kept), a binding kept by a higher-level receipt, no
    obligation ids, a refused `manifest_put`, the early exits, and a record that is not an
    `intended_failure` (returns "" and touches nothing: not the record, not the manifest, no scratch)."""
    made: list = []
    try:
        _publish_dicts(made)
        _publish_stale_projection(made)
    finally:
        for path in made:
            cleanup(path)
            cleanup_beside(path)


def _publish_stale_projection(made: list) -> None:
    """t-1253 F-3: `manifest_put.py` exit 4 = the fragment IS in the journal, only the manifest's projection is stale.
    The publish line names the replay and never says "refused"; the record says `published: False` (the manifest does
    not hold the receipt yet) with a `manifest_put` text of its own. Exit 3 keeps the refusal's words."""
    real = PBC._put_fragment
    try:
        for code, said in ((4, "manifest_put: event committed; projection stale - the fragment is in the journal"),
                           (3, "manifest_put: nothing was committed")):
            PBC._put_fragment = lambda task, fragment, _c=code, _s=said: subprocess.CompletedProcess([], _c, "", _s)
            rec, line, ref, _task = _publish_scenario(made)
            if code == 4:
                check_eq("D5 exit 4: published False, the record says committed and stale",
                         (rec["publish"]["published"], rec["publish"]["manifest_put"].startswith("committed, projection stale: ")),
                         (False, True))
                check_in("D5 exit 4: the line names the replay", f"`manifest_put.py --task {TASK} --recover`", line)
                check("D5 exit 4: and never says refused", "refused" not in line and "refused" not in rec["publish"]["manifest_put"],
                      line)
            else:
                check_eq("D5 exit 3 CONTROL: still the refusal's line",
                         line, f"manifest_put refused the publish, the receipt stays at {ref['path']}: {rec['publish']['manifest_put']}")
    finally:
        PBC._put_fragment = real


def _publish_scenario(made: list, row_tag=None, binding_tag=None, over=None, plan=False) -> tuple:
    """(the record after the publish, the line it returned, the new receipt's ref, the task folder)."""
    root = project()
    made.append(root)
    task = task_of(root)
    use_project(root)
    refs = {tag: fabricate(task, level, tag, iid) for tag, level, iid in (
        ("new-live", "live", "test_add"), ("held-product", "product", "test_add"),
        ("held-live", "live", "test_add"), ("other-product", "product", "other"))}
    manifest = manifest_of(root)
    manifest.pop("obligation_bindings", None)
    for test in manifest["tests"]:
        if test.get("instance_id") == "test_add":
            test.pop("sensitivity_proof", None)
            if row_tag:
                test["sensitivity_proof"] = {"receipt_ref": refs[row_tag]}
    if binding_tag:
        manifest["obligation_bindings"] = [{"obligation_id": "OB-ADD-1", "instance_ids": ["other"],
                                           "sensitivity": "proven", "proof_kind": "executed_red_probe",
                                           "probe_receipt_ref": refs[binding_tag]["path"],
                                           "design_assessment": "sufficient"}]
    write_json(task / "work" / "automation-manifest.json", manifest)
    if plan:  # a plan that names other obligations: manifest_put refuses ours
        write_json(task / "work" / "test-plan.json", {"rows": [{
            "id": "TS-1", "schema_version": 2, "coverage_obligations": [{"obligation_id": "OB-OTHER", "text": "x"}]}]})
    rec = dict({"verdict": "intended_failure", "instance_id": "test_add", "receipt": refs["new-live"],
                "obligation_ids": ["OB-ADD-1"], "restore": {"verified": True}}, **(over or {}))
    return rec, PBC.publish_binding(TASK, task, rec), refs["new-live"], task


def _publish_dicts(made: list) -> None:
    def pinned(label, rec, said, ref, row, bindings, line, note=None):
        put = rec["publish"].pop("manifest_put", None)
        want = {"published": True, "receipt": ref, "row": row, "bindings": bindings}
        if note:
            want["bindings_note"] = note
        check_eq(f"D5 {label}: the whole publish dict (manifest_put apart)", rec["publish"], want)
        check(f"D5 {label}: manifest_put says it put the fragment", PUBLISH_PUT_OK.fullmatch(str(put)) is not None,
              str(put))
        check_eq(f"D5 {label}: the line returned", said, line)

    def item(ids, receipt):
        return [{"obligation_id": "OB-ADD-1", "instance_ids": ids, "receipt": receipt}]

    rec, said, ref, _ = _publish_scenario(made)
    pinned("added", rec, said, ref, "added", item(["test_add"], "set"),
           f"published {ref['path']}: row added; bound OB-ADD-1")
    rec, said, ref, _ = _publish_scenario(made, "held-live", "held-live")
    pinned("replaced", rec, said, ref, "replaced", item(["other", "test_add"], "set"),
           f"published {ref['path']}: row replaced; bound OB-ADD-1")
    rec, said, ref, _ = _publish_scenario(made, "held-product", "held-product")
    pinned("kept (row and binding)", rec, said, ref, PUBLISH_KEPT_ROW, item(["other", "test_add"], PUBLISH_KEPT_BINDING),
           f"published {ref['path']}: row {PUBLISH_KEPT_ROW}; bound OB-ADD-1")
    rec, said, ref, _ = _publish_scenario(made, None, "held-product")
    pinned("a binding kept by a higher-level receipt", rec, said, ref, "added",
           item(["other", "test_add"], PUBLISH_KEPT_BINDING), f"published {ref['path']}: row added; bound OB-ADD-1")
    rec, said, ref, _ = _publish_scenario(made, None, "other-product")
    pinned("a higher receipt of ANOTHER instance holds nothing", rec, said, ref, "added",
           item(["other", "test_add"], "set"), f"published {ref['path']}: row added; bound OB-ADD-1")
    rec, said, ref, _ = _publish_scenario(made, over={"obligation_ids": []})
    pinned("no obligation ids", rec, said, ref, "added", [],
           f"published {ref['path']}: row added; no obligation ids to bind", note=PUBLISH_NO_OBLIGATIONS)
    rec, said, ref, task = _publish_scenario(made, "held-product", over={"obligation_ids": []})
    check_eq("D5 nothing to put: the whole publish dict",
             rec["publish"], {"published": True, "receipt": ref, "row": PUBLISH_KEPT_ROW, "bindings": [],
                              "bindings_note": PUBLISH_NO_OBLIGATIONS,
                              "manifest_put": "nothing to put: a receipt of a higher level is already published"})
    check_eq("D5 nothing to put: the line returned", said,
             "nothing to put: a receipt of a higher level is already published")
    rec, said, ref, task = _publish_scenario(made, plan=True)
    put = rec["publish"].pop("manifest_put")
    check_eq("D5 manifest_put refused: the publish dict (manifest_put apart)", rec["publish"],
             {"published": False, "receipt": ref, "row": "added", "bindings": item(["test_add"], "set")})
    check("D5 manifest_put refused: the refusal, cut to its last 300 characters",
          put.startswith("refused: ") and 0 < len(put) <= len("refused: ") + 300 and "waiver.py" in put, put)
    check_eq("D5 manifest_put refused: the line returned names the receipt that stays", said,
             f"manifest_put refused the publish, the receipt stays at {ref['path']}: {put}")
    # the early exits: nothing reaches the manifest
    for label, over, why in (
            ("restore not verified", {"receipt": None, "restore": {"verified": False}}, "the restore was not verified"),
            ("facts missing", {"receipt": None, "receipt_missing": ["build_id", "source_revision"]},
             "the facts a receipt binds are missing: build_id, source_revision"),
            ("no reason known", {"receipt": None}, "the receipt could not be written"),
            ("a receipt with no path", {"receipt": {"sha256": "x"}}, "the receipt could not be written")):
        rec, said, _ref, task = _publish_scenario(made, over=over)
        check_eq(f"D5 {label}: the publish dict", rec["publish"], {"published": False, "why": why})
        check_eq(f"D5 {label}: the line returned", said, f"no live receipt, nothing published ({why})")
    rec, said, _ref, task = _publish_scenario(made, over={"instance_id": "nowhere"})
    check_eq("D5 an instance the manifest does not hold: published False", rec["publish"]["published"], False)
    check_eq("D5 an instance the manifest does not hold: the refusal's own words are the reason, and the line",
             said, "nothing published: " + rec["publish"]["why"])
    check_in("D5 an instance the manifest does not hold: it names the instance", "nowhere", rec["publish"]["why"])
    # a record that is not an intended_failure: "" and nothing touched
    rec, _said, _ref, task = _publish_scenario(made)
    before_manifest = (task / "work" / "automation-manifest.json").read_bytes()
    scratch_before = sorted(p.name for p in Path(tempfile.gettempdir()).glob("qa-probe-binding-*"))
    for verdict in ("no_failure", "wrong_location", "not_executed", "incomplete", "already_probed", None):
        other = {k: v for k, v in rec.items() if k != "publish"}
        other["verdict"] = verdict
        frozen = json.loads(json.dumps(other))
        check_eq(f"D5 verdict {verdict}: returns the empty string", PBC.publish_binding(TASK, task, other), "")
        check_eq(f"D5 verdict {verdict}: the record is as it was (no publish key)", other, frozen)
    check_eq("D5 verdicts that publish nothing: the manifest bytes are as they were",
             (task / "work" / "automation-manifest.json").read_bytes(), before_manifest)
    check_eq("D5 no scratch folder is left behind, by a publish or a non-publish",
             sorted(p.name for p in Path(tempfile.gettempdir()).glob("qa-probe-binding-*")), scratch_before)


class _LoggedStream:
    """A stdout/stderr stand-in that writes into one shared list, so the ORDER of everything `main` does
    (the calls it makes and what it prints on which stream) is compared, not only the final text."""

    def __init__(self, log: list, tag: str):
        self.log, self.tag = log, tag

    def write(self, text: str) -> int:
        self.log.append((self.tag, text))
        return len(text)

    def flush(self) -> None:
        pass


def _main_in_process(argv: list, probe=None, publish=("", False), release=None) -> tuple:
    """(the exit code, the log) of `probe_by_code.main()` run in this process with `probe`, `publish_binding`
    and `release_copy` replaced: `probe` is the record it returns (or the exception it raises); `publish` is
    (the line it returns, whether it fills `record["publish"]`); `release` the dict (or exception) of the door."""
    import contextlib
    log: list = []

    def fake_probe(*args, **kwargs):
        log.append(("call", "probe", args, kwargs))
        if isinstance(probe, Exception):
            raise probe
        return probe

    def fake_publish(task, task_root, record):
        log.append(("call", "publish", (task, Path(task_root).as_posix())))
        if publish[1]:
            record["publish"] = {"published": True}
        return publish[0]

    def fake_release(root, what):
        log.append(("call", "release", (Path(root).as_posix(), what)))
        if isinstance(release, Exception):
            raise release
        return release

    saved = (PBC.probe, PBC.publish_binding, PBC.release_copy, sys.argv)
    PBC.probe, PBC.publish_binding, PBC.release_copy = fake_probe, fake_publish, fake_release
    sys.argv = ["probe_by_code.py", *argv]
    try:
        with contextlib.redirect_stdout(_LoggedStream(log, "out")), contextlib.redirect_stderr(_LoggedStream(log, "err")):
            try:
                PBC.main()
                code = "returned"
            except SystemExit as exc:
                code = exc.code
    finally:
        PBC.probe, PBC.publish_binding, PBC.release_copy, sys.argv = saved
    return code, log


def _streams(log: list) -> tuple:
    return ("".join(t for tag, t, *_ in log if tag == "out"), "".join(t for tag, t, *_ in log if tag == "err"))


def _calls(log: list) -> list:
    return [entry[1] for entry in log if entry[0] == "call"]


def _first(log: list, tag: str) -> int:
    return next((i for i, entry in enumerate(log) if entry[0] == tag), -1)


def _last(log: list, tag: str) -> int:
    return max((i for i, entry in enumerate(log) if entry[0] == tag), default=-1)


def main_exit_order_is_pinned() -> None:
    """t-667 D6, characterisation: the `sys.exit` order of `main` is already_probed -> publish -> print ->
    restore check -> verdict exit, and each exit code and printed byte is as before. `probe` is replaced by a
    record, so the unrestored branch, which no stub run reaches, is pinned too (the process is the real
    `main`, the argv the real CLI)."""
    root = temp_dir("qa-probe-main-")
    mark_project(root)                                               # the story below is a story of a project (CX1-18)
    (root / "qa-factory" / "artifacts" / "T-1").mkdir(parents=True)
    use_project(root)
    base = root.resolve()
    argv = ["--task", "T-1", "--dispatch", "D-1", "--test", "tests/t.py::test_x", "--instance", "iid"]
    record = {"instance_id": "iid", "verdict": "intended_failure", "expected_location": "t.py:6",
              "expected_reason": "marker", "actual_location": "t.py:7", "actual_reason": "word " * 40,
              "record": "work/probes/iid.json", "evidence_ref": "evidence/e.json", "restore": {"verified": True},
              "notes": ["n1", "n2"], "test_node": "tests/t.py::test_x", "test_file_sha256": "f" * 64}
    # the reason is folded to 120 characters: 119 and an ellipsis
    printed = ("probe iid: intended_failure — expected t.py:6 / 'marker'; actual t.py:7 / "
               + repr(("word " * 40).strip()[:119] + "…") + "\n"
               "record work/probes/iid.json; evidence evidence/e.json; restore verified\n")
    try:
        # already probed: answered before the publish and before the restore check, exit 0 either way
        answered = {"verdict": "already_probed", "instance_id": "iid", "words": "the words", "notes": ["a", "b"],
                    "restore": {"verified": False}}
        code, log = _main_in_process(argv, dict(answered), publish=("never", True))
        check_eq("D6 already_probed (text): exit 0, publish never called, calls are probe only",
                 (code, _calls(log)), (0, ["probe"]))
        check_eq("D6 already_probed (text): the bytes", _streams(log),
                 ("probe iid: already_probed — the words\nnote: a\nnote: b\n", ""))
        code, log = _main_in_process(argv + ["--json"], dict(answered), publish=("never", True))
        check_eq("D6 already_probed (json): exit 0, one JSON object, publish never called",
                 (code, _calls(log), _streams(log)),
                 (0, ["probe"], (json.dumps(answered, ensure_ascii=False, indent=1) + "\n", "")))
        args = next(entry[2] for entry in log if entry[0] == "call" and entry[1] == "probe")
        check_eq("D6 the probe is called with the CLI's values, positionally",
                 args, ("T-1", "D-1", "tests/t.py::test_x", "iid", "invert", PBC.RUN_TIMEOUT_S, "", None))
        code, log = _main_in_process(argv + ["--mutation", "invert", "--timeout", "7", "--oracle", "h::f",
                                             "--at", "12"], dict(answered))
        args = next(entry[2] for entry in log if entry[0] == "call" and entry[1] == "probe")
        check_eq("D6 the probe is called with --mutation --timeout --oracle --at as given",
                 args, ("T-1", "D-1", "tests/t.py::test_x", "iid", "invert", 7, "h::f", 12))
        # a verdict, text: probe -> publish -> print (the publish saw nothing printed) -> verdict exit
        for verdict, want in (("intended_failure", 0), ("no_failure", 0), ("wrong_location", 0),
                              ("not_executed", 1), ("incomplete", 1), ("unheard_of", 1)):
            code, log = _main_in_process(argv, dict(record, verdict=verdict, notes=list(record["notes"])),
                                         publish=("the binding line", True))
            out, err = _streams(log)
            check_eq(f"D6 {verdict}: exit {want}; probe then publish", (code, _calls(log)), (want, ["probe", "publish"]))
            check_eq(f"D6 {verdict}: published with the task and the task's artifacts folder",
                     next(e[2] for e in log if e[0] == "call" and e[1] == "publish"),
                     ("T-1", Path(PBC.artifacts_dir("T-1")).as_posix()))
            check(f"D6 {verdict}: the publish ran before the first byte was printed",
                  _first(log, "out") > max(i for i, e in enumerate(log) if e[:2] == ("call", "publish")))
            check_eq(f"D6 {verdict}: the text, binding line between the record line and the notes",
                     out, printed.replace("intended_failure —", verdict + " —")
                     + "binding: the binding line\nnote: n1\nnote: n2\n")
            check_eq(f"D6 {verdict}: nothing on stderr", err, "")
        # the publish goes back into the record's own file; with --json the whole of stdout is one object
        written = base / "qa-factory" / "artifacts" / "T-1" / "work" / "probes" / "iid.json"
        sent = dict(record, notes=list(record["notes"]))
        code, log = _main_in_process(argv + ["--json"], sent, publish=("bound it", True))
        out, _err = _streams(log)
        check_eq("D6 json: exit 0 and stdout is exactly the record, binding and publish in it",
                 (code, out), (0, json.dumps(dict(record, publish={"published": True}, binding="bound it"),
                                             ensure_ascii=False, indent=1) + "\n"))
        check_eq("D6 json: the publish was written into the record's file",
                 json.loads(written.read_text(encoding="utf-8")) if written.is_file() else None,
                 dict(record, binding="bound it", publish={"published": True}))
        written.unlink()
        code, log = _main_in_process(argv, dict(record, notes=list(record["notes"])), publish=("", False))
        check_eq("D6 nothing published: no binding line, no file written",
                 (_streams(log)[0], written.is_file()), (printed + "note: n1\nnote: n2\n", False))
        # the write of the publish fails: a note, never a crash, and the note is printed
        blocker = base / "qa-factory" / "artifacts" / "T-1" / "blocked"
        blocker.parent.mkdir(parents=True, exist_ok=True)
        blocker.write_text("a file where a folder should be", encoding="utf-8")
        code, log = _main_in_process(argv + ["--json"], dict(record, record="blocked/iid.json", notes=["n1"]),
                                     publish=("x", True))
        shown = json.loads(_streams(log)[0])
        check_eq("D6 an unwritable record: still exit 0", code, 0)
        check_eq("D6 an unwritable record: the note says so, after the earlier notes",
                 (shown["notes"][0], shown["notes"][1].startswith("the publish could not be written into the record: ")),
                 ("n1", True))
        # the restore check comes after the print and before the verdict exit
        mutated = {"path": "tests/helper.py", "sha256": "s" * 64}
        for label, over, undo in (
                ("a copy kept", {"restore": {"verified": False, "copy": "state/probe-copies/abc.orig"},
                                 "mutated_file": mutated},
                 f"copy {base / 'state/probe-copies/abc.orig'} over {base / 'tests/helper.py'}"),
                ("no copy", {"restore": {"verified": False}, "mutated_file": mutated}, "restore tests/helper.py by hand"),
                ("no restore at all, no mutated_file: the test's own file and sha", {"restore": None},
                 "restore tests/t.py by hand")):
            sha = mutated["sha256"] if "mutated_file" in over else record["test_file_sha256"]
            file_rel = mutated["path"] if "mutated_file" in over else "tests/t.py"
            code, log = _main_in_process(argv, dict(record, notes=list(record["notes"]), **over),
                                         publish=("the binding line", True))
            out, err = _streams(log)
            check_eq(f"D6 unrestored ({label}): exit 1 although the verdict is intended_failure", code, 1)
            check_eq(f"D6 unrestored ({label}): the whole record is printed first, and says NOT VERIFIED",
                     out, printed.replace("restore verified", "restore NOT VERIFIED")
                     + "binding: the binding line\nnote: n1\nnote: n2\n")
            check_eq(f"D6 unrestored ({label}): the stop line, on stderr, with the one move that undoes it",
                     err, f"PROBE: the author's bytes of {file_rel} could not be verified restored (sha256 {sha}) "
                          f"— stop and {undo}\n")
            check(f"D6 unrestored ({label}): publish, then stdout, then stderr",
                  _last(log, "out") < _first(log, "err")
                  and max(i for i, e in enumerate(log) if e[:2] == ("call", "publish")) < _first(log, "out"))
        # a refusal: one JSON line on stdout, exit 2, nothing published
        code, log = _main_in_process(argv, PBC.Refusal("no file x under the project root"))
        check_eq("D6 a refusal: exit 2, the JSON line, no publish",
                 (code, _calls(log), _streams(log)),
                 (2, ["probe"], (json.dumps({"status": "refused", "error": "no file x under the project root"},
                                             ensure_ascii=False) + "\n", "")))
        # a missing argument is the parser's: exit 2, naming every one, no probe
        code, log = _main_in_process(["--task", "T-1"])
        out, err = _streams(log)
        check_eq("D6 missing arguments: exit 2, nothing probed, nothing on stdout", (code, _calls(log), out), (2, [], ""))
        check_in("D6 missing arguments: all three are named", "the following arguments are required: --dispatch, "
                 "--test, --instance", err)
        check_not_in("A-K10 the role's text does not show the driver's door", "--s6-close",
                     err.split("required:")[-1])
        # A-K10 (HF3-6): the third form of the call. `s6_close` goes as a KEYWORD, so the positional pin above stays
        # as it was; one context per call; the dispatch id is "" in the close context.
        code, log = _main_in_process(argv, dict(answered))
        check_eq("A-K10 the ordinary call passes s6_close=False as a keyword",
                 next(e[3] for e in log if e[0] == "call" and e[1] == "probe"), {"s6_close": False})
        close_argv = ["--task", "T-1", "--s6-close", "--test", "tests/t.py::test_x", "--instance", "iid"]
        code, log = _main_in_process(close_argv, dict(answered))
        got = next(e for e in log if e[0] == "call" and e[1] == "probe")
        check_eq("A-K10 --s6-close: the probe is called with an empty dispatch and s6_close=True",
                 (code, got[2][:2], got[3]), (0, ("T-1", ""), {"s6_close": True}))
        code, log = _main_in_process(argv + ["--s6-close"], dict(answered))
        out, err = _streams(log)
        check_eq("A-K10 --dispatch with --s6-close: exit 2, nothing probed", (code, _calls(log), out), (2, [], ""))
        check_in("A-K10 --dispatch with --s6-close: 'use one' names both",
                 "use one: --dispatch <id> (an open dispatch) or --s6-close (the code close of S6)", err)
        # --release-copy: exits before anything else, refused 2, released 0, json or text
        code, log = _main_in_process(["--release-copy", "tests/x.py"], release=PBC.Refusal("a probe is running"))
        check_eq("D6 release refused: exit 2, JSON line, no probe", (code, _calls(log), _streams(log)),
                 (2, ["release"], (json.dumps({"status": "refused", "error": "a probe is running"},
                                              ensure_ascii=False) + "\n", "")))
        check_eq("D6 release is given the project root and the argument",
                 next(e[2] for e in log if e[0] == "call" and e[1] == "release"), (base.as_posix(), "tests/x.py"))
        released = {"status": "released", "file": "tests/x.py", "copy": "abc.orig", "record": {"a": 1}}
        code, log = _main_in_process(["--release-copy", "tests/x.py"] + argv, release=dict(released))
        check_eq("D6 release (text, no message): exit 0, the sentence, nothing probed",
                 (code, _calls(log), _streams(log)),
                 (0, ["release"], ('released the byte copy of tests/x.py (abc.orig); its record was {"a": 1}\n', "")))
        code, log = _main_in_process(["--release-copy", "tests/x.py"], release=dict(released, message="its message"))
        check_eq("D6 release (text, with a message): the message", (code, _streams(log)), (0, ("its message\n", "")))
        code, log = _main_in_process(["--release-copy", "tests/x.py", "--json"], release=dict(released))
        check_eq("D6 release (json): the dict, indented", (code, _streams(log)),
                 (0, (json.dumps(released, ensure_ascii=False, indent=1) + "\n", "")))
    finally:
        cleanup(root)


def hostile_instance_ids() -> None:
    """The receipt writer meets ids a file system does not: `::`, `[`, `/`, non-ASCII, and 120/121/300
    characters (AT and BEYOND the stem limit `contract.instance_file_stem` puts on a name)."""
    tmp = temp_dir("q-")
    try:
        ids = ["TC-1::test_x[a/b]", "test_é[ü-日本]", "a" * 119, "a" * 120, "a" * 121, "a" * 300,
               "a" * 299 + "b", "TC::x[" + "ü" * 300 + "]", "::", "///", "[[]]", "con", "x y\tz"]
        seen = {}
        for iid in ids:
            body = {"instance_id": iid, "case_version": "cv_1", "test_content_hash": "t", "proof_level": "live",
                    "probe_tool": "probe_by_code.py", "evidence_refs": [], "immutable": True}
            ref, note = PBC.write_receipt(tmp, body, iid)
            label = iid if len(iid) < 30 else f"{iid[:8]}...({len(iid)} chars)"
            check(f"battery {label}: written", ref is not None, note)
            if ref is None:
                continue
            path = tmp / ref["path"]
            check(f"battery {label}: on disk under sensitivity-receipts/ with a portable name",
                  path.is_file() and path.parent == tmp / "work" / "sensitivity-receipts"
                  and len(path.name) <= 255 and not any(ch in path.name for ch in '<>:"/\\|?*[]'), path.name)
            check_eq(f"battery {label}: the id survives the round trip",
                     json.loads(path.read_text(encoding="utf-8"))["instance_id"], iid)
            check_eq(f"battery {label}: the ref's hash is the file's", ref["sha256"], PBC.sha256(path.read_bytes()))
            again, _ = PBC.write_receipt(tmp, body, iid)
            check_eq(f"battery {label}: the same facts again are the same path", again, ref)
            check(f"battery {label}: its own file", ref["path"] not in seen.values(), ref["path"])
            seen[iid] = ref["path"]
        check_eq("ids that share their first 120 characters still get different files",
                 seen.get("a" * 300) != seen.get("a" * 299 + "b"), True)
        stem = C.instance_file_stem("a" * 120)
        check_eq("AT the stem limit the stem is the id itself", stem, "a" * 120)
        check("BEYOND it the stem is cut and told apart by a hash", len(C.instance_file_stem("a" * 121)) < 121 + 10
              and C.instance_file_stem("a" * 121) != "a" * 121)
        # An existing file under that very name with other content is never overwritten.
        body = {"instance_id": "clash", "proof_level": "live", "evidence_refs": [], "immutable": True}
        ref, _ = PBC.write_receipt(tmp, body, "clash")
        clash = tmp / ref["path"]
        clash.write_text('{"someone": "else"}', encoding="utf-8")
        got, note = PBC.write_receipt(tmp, body, "clash")
        check_eq("a same-name file with other content: no receipt", got, None)
        check_in("...and the note says nothing was overwritten", "never overwritten", note)
        check_eq("...and the file is as it was", clash.read_text(encoding="utf-8"), '{"someone": "else"}')
        # Same name, right hash field, changed content: also a collision, never a match.
        forged = dict(body, immutable=False, receipt_hash=PBC._hash_of(body))
        clash.write_text(json.dumps(forged), encoding="utf-8")
        got, note = PBC.write_receipt(tmp, body, "clash")
        check_eq("a file claiming this receipt's hash over other content: no receipt", got, None)
        # A file where the directory should be: the writer reports, it does not raise.
        blocker = temp_dir("q-")
        try:
            (blocker / "work").write_text("not a directory", encoding="utf-8")
            got, note = PBC.write_receipt(blocker, body, "clash")
            check_eq("an unwritable target: no receipt, a note, no traceback", (got, "could not be written" in note),
                     (None, True))
        finally:
            cleanup(blocker)
    finally:
        cleanup(tmp)
    # The run evidence differs on every run (a job summary, a junit file with its timings): the same
    # facts with other evidence are the same receipt, at the same path, and the first file stays.
    tmp2 = temp_dir("q-")
    try:
        body = {"instance_id": "ev", "proof_level": "live", "immutable": True,
                "evidence_refs": [{"path": "evidence/one", "sha256": "1" * 64}]}
        first, _ = PBC.write_receipt(tmp2, body, "ev")
        frozen = (tmp2 / first["path"]).read_bytes()
        second, note = PBC.write_receipt(tmp2, dict(body, evidence_refs=[{"path": "evidence/two", "sha256": "2" * 64}]), "ev")
        check_eq("other run evidence, same facts: the same path", second, first)
        check_eq("...and the first file is untouched", (tmp2 / first["path"]).read_bytes(), frozen)
        check_eq("...with no scratch file left behind",
                 sorted(p.name for p in (tmp2 / "work" / "sensitivity-receipts").iterdir()), [Path(first["path"]).name])
    finally:
        cleanup(tmp2)
    # An id with `::`, `[` and `/` through the PUBLISH too: the row and the binding find it again.
    root = project()
    try:
        task = task_of(root)
        use_project(root)
        iid = "TC-9::test_x[a/b-é]"
        manifest = manifest_of(root)
        manifest["tests"] = [entry("TC-100", "test_add", iid, obligation_ids=["OB-ADD-1"])]
        write_json(task / "work" / "automation-manifest.json", manifest)
        body = {"instance_id": iid, "case_version": "cv_1", "test_content_hash": "t", "source_revision": "s",
                "build_id": "b", "mutation": "invert", "expected_assertion_failure": "e", "actual_failure": "e",
                "assertion_location": "t.py:1", "restoration_evidence": "r", "failure_kind": "assertion",
                "proof_level": "live", "probe_tool": "probe_by_code.py", "mutation_kind": "assertion",
                "evidence_refs": [], "immutable": True}
        ref, _ = PBC.write_receipt(task, body, iid)
        rec = {"verdict": "intended_failure", "instance_id": iid, "receipt": ref, "obligation_ids": ["OB-ADD-1"],
               "restore": {"verified": True}}
        PBC.publish_binding(TASK, task, rec)
        row = next(t for t in manifest_of(root)["tests"] if t.get("instance_id") == iid)
        check_eq("hostile id: the row carries the receipt", (row.get("sensitivity_proof") or {}).get("receipt_ref"), ref)
        check_eq("hostile id: the binding lists the id", binding_of(root).get("instance_ids"), [iid])
    finally:
        cleanup(root)
        cleanup_beside(root)


def an_unverified_restore_writes_no_receipt(stub: Path) -> None:
    """The bytes of the author's file are the probe's promise; a receipt vouching for a restore nobody
    verified would be the tool's own failure dressed as a proof."""
    root = project()
    try:
        _unverified_restore(root, stub)
    finally:
        cleanup(root)
        cleanup_beside(root)


def _unverified_restore(root: Path, stub: Path) -> None:
    use_project(root)
    task = task_of(root)
    real = PBC.restore
    old_env = os.environ.get("PROBE_RUN_SUITE")
    os.environ["PROBE_RUN_SUITE"] = str(stub)
    PBC.restore = lambda *args, **kw: dict(real(*args, **kw), verified=False)
    model_entries(root, stub, f"{TEST_FILE_REL}::test_add", "test_add")
    try:
        record = PBC.probe(TASK, DISPATCH, f"{TEST_FILE_REL}::test_add", "test_add", "invert")
    finally:
        PBC.restore = real
        if old_env is None:
            os.environ.pop("PROBE_RUN_SUITE", None)
        else:
            os.environ["PROBE_RUN_SUITE"] = old_env
    # t-2064 P4b: the walk's aggregate does not call a plan with an unverified restore `intended_failure` at all (a failed restore ends the
    # walk): the verdict is `incomplete`, the restore says it was not verified, and `publish_binding` has nothing to publish (it publishes
    # `intended_failure` only) - the receipt is as absent as before, by one more gate.
    check_eq("unverified restore: the walk answers incomplete, with the restore unverified",
             (record.get("verdict"), (record.get("restore") or {}).get("verified")), ("incomplete", False))
    check_eq("unverified restore: no receipt", record.get("receipt"), None)
    check_eq("unverified restore: no receipt file", receipt_files(root), [])
    said = PBC.publish_binding(TASK, task, record)
    check_eq("unverified restore: nothing is published", (said, "published" in (record.get("publish") or {})), ("", False))
    check_eq("unverified restore: the manifest row is untouched", "sensitivity_proof" in row_of(root), False)


def missing_facts_and_a_refused_publish_do_not_change_the_exit() -> None:
    """Through the CLI: no build identity in any run block -> no receipt, `receipt_missing[]`, exit 0;
    a manifest_put that refuses -> the receipt stays, a note, exit 0."""
    stub_dir = temp_dir("qa-probe-stub-")
    stub = stub_dir / "fake_run_suite.py"
    stub.write_text(FAKE_RUN_SUITE, encoding="utf-8")
    bare = project(provenance=False)
    try:
        proc, record = run(bare, stub, f"{TEST_FILE_REL}::test_add", "test_add")
        check("no build identity: exit 0 (a verdict was recorded)", proc.returncode == 0, proc.stdout + proc.stderr)
        check_eq("no build identity: intended_failure", record.get("verdict"), "intended_failure")
        check_eq("no build identity: no receipt", record.get("receipt"), None)
        check_eq("no build identity: the missing fact is named", record.get("receipt_missing"), ["build_id"])
        check_in("no build identity: the note says where it belongs", "run block", " ".join(record.get("notes") or []))
        check_eq("no build identity: no receipt file", receipt_files(bare), [])
        check_eq("no build identity: nothing published on the row", "sensitivity_proof" in row_of(bare), False)
        check_eq("no build identity: no binding either", binding_of(bare), {})
        check_eq("no build identity: the record says why nothing was published",
                 ((record.get("publish") or {}).get("published"), "build_id" in str((record.get("publish") or {}).get("why"))),
                 (False, True))
    finally:
        cleanup(bare)
        cleanup_beside(bare)
    refused = project()
    try:
        write_json(task_of(refused) / "work" / "test-plan.json", {"rows": [{
            "id": "TS-1", "schema_version": 2, "coverage_obligations": [{"obligation_id": "OB-OTHER", "text": "x"}]}]})
        proc, record = run(refused, stub, f"{TEST_FILE_REL}::test_add", "test_add")
        check("manifest_put refuses: exit unchanged (0)", proc.returncode == 0, proc.stdout + proc.stderr)
        check("manifest_put refuses: the receipt stays on disk",
              len(receipt_files(refused)) == 1 and (task_of(refused) / record["receipt"]["path"]).is_file())
        check_eq("manifest_put refuses: the record says published False", (record.get("publish") or {}).get("published"),
                 False)
        check_in("manifest_put refuses: with the refusal", "refused", str((record.get("publish") or {}).get("manifest_put")))
        check_in("manifest_put refuses: and the printed line", "manifest_put refused", str(record.get("binding")))
        check_eq("manifest_put refuses: the row was not touched", "sensitivity_proof" in row_of(refused), False)
    finally:
        cleanup(refused)
        cleanup_beside(refused)
        cleanup(stub_dir)


def _probe_record(row: dict, measured: str, fingerprint: str, node: str, code: str = "") -> dict:
    """The record `probe()` hands `attach_receipt` after an intended failure with a verified restore:
    `test_file_sha256` is the raw file measured before the mutation, `input_hash` the run's
    fingerprint - two quantities over the same bytes."""
    fields, _missing = PBC.obligation_fields(row)
    return {"instance_id": row["instance_id"], "verdict": "intended_failure", "mutation": "invert",
            "expected_reason": "probe-x invert", "actual_reason": "probe-x invert",
            "expected_location": node.split("::")[0] + ":12", "failure_kind": "assertion",
            "record": "work/probes/x.json", "test_node": node, "mutation_detail": {"line": 12},
            "restore": {"verified": True, "sha256": measured}, "test_file_sha256": measured,
            "test_code_sha": code, "input_hash": fingerprint, "evidence_refs": [], "notes": [], **fields}


def raw_bytes_through_manifest_from_tests() -> None:
    """Amendment 2 of t-016 (critic t-035): `test_content_sha` is the RAW sha256 of the test file -
    what manifest_from_tests.py writes and validate_artifacts enforces - and a run block's
    `source_fingerprint.test_content_sha` is a fingerprint over the test AND helper files, another
    quantity. On driver3 the same bytes read 6992616693fc... and bd6d28d6aade..., and the gate that
    compared the fingerprint with the binding refused a receipt to every correctly bound row.

    Here the manifest is BUILT by manifest_from_tests.py and the run block carries a real
    fingerprint; the MEASURED BYTES gate writes the receipt for unchanged bytes and refuses it, with
    the door, once the file changed."""
    import test_manifest_from_tests as MFT
    from harness import temp_project
    root = temp_project("qa-probe-raw-")
    try:
        task = MFT.seed(root)
        use_project(root)
        wrote = MFT.run(root)
        check("raw bytes: manifest_from_tests.py writes the manifest", wrote.returncode == 0, wrote.stdout + wrote.stderr)
        manifest = json.loads((task / "work" / "automation-manifest.json").read_text(encoding="utf-8"))
        row = next(t for t in manifest["tests"] if t.get("instance_id") == "test_limit")
        test_file, helper = root / "tests" / "test_coupon.py", root / "tests" / "data_coupon.py"
        raw = PBC.sha256(test_file.read_bytes())
        check_eq("raw bytes: the manifest binds the file's raw sha256", row["trace_binding"]["test_content_sha"], raw)

        def fingerprint() -> str:  # execution_fingerprint.build's test_content_sha, over the same records
            return content_hash([{"path": str(test_file.resolve()), "sha256": PBC.sha256(test_file.read_bytes()),
                                  "kind": "test_files"},
                                 {"path": str(helper.resolve()), "sha256": PBC.sha256(helper.read_bytes()),
                                  "kind": "helper_files"}])
        run_fp = fingerprint()
        check("raw bytes: the run's fingerprint of the same bytes is another quantity", run_fp != raw, run_fp)
        components = {"source_sha": "src-9", "test_content_sha": run_fp}
        write_json(task / "work" / "run-blocks" / "20260929T090000000000Z-raw.json", {
            "schema_version": 2, "dispatch_id": "S5-qa-automator-1", "purpose": "initial",
            "input_fingerprint": "fp-raw", "source_fingerprint": components,
            "runtime_provenance": {"observed_runtime_identity": "build-9", "environment_id": "env-9"},
            "results": [{"instance_id": "test_limit", "status": "passed", "source_fingerprint": components}]})
        node = row["selector"]
        record = _probe_record(row, raw, run_fp, node, PL.code_sha(test_file.read_bytes()))
        PBC.attach_receipt(record, row, task)
        ref = record.get("receipt") or {}
        check("raw bytes, unchanged: the live receipt IS written", bool(ref.get("path")),
              json.dumps(record.get("notes")))
        check_eq("raw bytes, unchanged: nothing missing", record.get("receipt_missing"), [])
        body = json.loads((task / ref["path"]).read_text(encoding="utf-8")) if ref.get("path") else {}
        check_eq("raw bytes: the receipt binds the raw hash, never the fingerprint",
                 (body.get("test_content_hash"), body.get("source_revision"), body.get("build_id")),
                 (raw, "src-9", "build-9"))
        proven = dict(row, sensitivity_proof={"receipt_ref": ref})
        check_eq("raw bytes: the contract accepts it unchanged", C.sensitivity_proof_issues(proven, task), [])
        check_eq("raw bytes: and reached() shows the check is live", PL.reached(proven, manifest, task)["level"], "live")

        # The test file changes by a COMMENT; the manifest still binds the old bytes.
        test_file.write_bytes(test_file.read_bytes() + b"\n# edited after the review\n")
        changed = PBC.sha256(test_file.read_bytes())
        record = _probe_record(row, changed, fingerprint(), node, PL.code_sha(test_file.read_bytes()))
        PBC.attach_receipt(record, row, task)
        # MEASURED BYTES stays raw (Amendment 3): the claim must be the bytes measured.
        check_eq("raw bytes, changed: NO new receipt", record.get("receipt"), None)
        check_eq("raw bytes, changed: the stale fact is named", record.get("receipt_missing"), ["test_content_hash"])
        check_in("raw bytes, changed: the door is the author's rebind through manifest_put, no run",
                 "It is the author's to rebind, through `manifest_put.py` (no run needed): "
                 "trace_binding.test_content_sha is the sha256 of the file's bytes", " ".join(record["notes"]))
        # ...but the first receipt still counts: the change was comment-only (D-0017, Amendment 3)
        got = PL.reached(proven, manifest, task)
        check_eq("comment-only edit: the first receipt still counts, and says why",
                 (got["level"], got["words"]), ("live", "the check is live (the receipt holds over a comment-only change)"))
        # an executable line changed: other code, the receipt no longer counts
        test_file.write_bytes(test_file.read_bytes().replace(b'assert body["count"] == 1', b'assert body["count"] == 2'))
        check("raw bytes: the assert really changed", PBC.sha256(test_file.read_bytes()) != changed)
        check_eq("an assert changed: the first receipt no longer counts for the changed test",
                 PL.reached(proven, manifest, task)["level"], None)
        check_eq("raw bytes: still exactly one receipt file",
                 len(list((task / "work" / "sensitivity-receipts").glob("test_limit-live-*.json"))), 1)
    finally:
        cleanup(root)


# --- t-043 C: a second probe of the same bytes is answered (D-0018) -------------------------------------

class fresh:
    """A project of its own (`project()` plus `use_project`), removed with what lies beside it."""
    def __enter__(self) -> Path:
        self.root = project()
        use_project(self.root)
        return self.root

    def __exit__(self, *_exc) -> None:
        cleanup(self.root)
        cleanup_beside(self.root)


ANSWER_KEYS = ["verdict", "instance_id", "by", "level", "receipt_ref", "record", "prior_verdict",
               "recorded_at", "holds", "words", "block"]


def stamp_record(root: Path, instance: str, **fields) -> dict:
    """Rewrite fields of the probe's own record (a fixture's way to say 'recorded long ago', or 'said
    no_failure'): the record is plain JSON and the test file, not the tool, is under test here."""
    path = task_of(root) / "work" / "probes" / f"{instance}.json"
    body = json.loads(path.read_text(encoding="utf-8"))
    body.update(fields)
    write_json(path, body)
    return body


# t-2064 P4b: the key set of a WALK's aggregate (was the first-check record's: `author_run_block` and `run` are gone; the plan's `checks`,
# `mutated_files`, `plan_runs`, `plan_remaining`, `plan_unfinished` and `words` are new). `publish` / `binding` / `receipt*` are the
# receipt's: they stand until item 4 attaches a receipt to the aggregate. `judgment_owed` and `walk_ended` are the aggregate's own,
# each with a reader (named at its line below).
INVERT_RECORD_KEYS = [
    "actual_location", "actual_reason", "assertion_id", "binding", "case", "checks", "defect_location",
    "dispatch_id", "evidence_ref", "evidence_refs", "expected_location", "expected_reason", "failure_kind",
    "input_hash", "input_hash_source", "instance_content_sha", "instance_id", "instance_identity",
    "judgment_owed",     # `_judgment_fold`, always written; read by `proof_level.probe_record_state` -> `probe_plain_call_owed`
    "manifest_fields_missing", "mutated_file", "mutated_files", "mutation", "mutation_detail", "mutation_kind", "notes",
    "obligation_hash", "obligation_ids", "obligation_refs", "observed", "plan_remaining", "plan_runs", "plan_unfinished",
    "probe_tool", "proof_level",
    "proved_by",     # t-2064 N3b step 5: an `intended_failure` the code proved says how (`marker`, the token read in the row)
    "publish", "receipt", "receipt_missing", "record", "recorded_at", "request", "restore", "schema_version", "target",
    "task", "test_code_sha", "test_file_sha256", "test_node", "verdict",
    "walk_ended",        # `_aggregate_record`; read by `_refold` (the judge's rebuild of the aggregate: `walk["ended"]`)
    "window_probe", "words"]


def the_record_and_the_answer_are_pinned(stub: Path) -> None:
    """B-426 D1 characterisation: `_probe` is split into helpers, and what it hands back must not move. The
    written record's sorted key set and its notes on the invert path, the key set and notes of the
    `already_probed` answer, and the notes of a manifest row that names another file (the repeat check is not
    made, the record binds the bytes measured here) are compared with the values the unsplit function gave."""
    with fresh() as root:
        proc, first = run(root, stub, f"{TEST_FILE_REL}::test_add", "test_add")
        written = read_record(root, "test_add")
        check_eq("pinned invert: exit 0, intended_failure", (proc.returncode, written.get("verdict")),
                 (0, "intended_failure"))
        check_eq("pinned invert: the written record's key set", sorted(written), INVERT_RECORD_KEYS)
        check_eq("pinned invert: the answer printed is the record written", sorted(first), sorted(written))
        check_eq("pinned invert: its notes", written.get("notes"),
                 [# t-2064 P4b: no `assertion_id` note - the default road walks every check and never chooses a target by the id
                  "command, fingerprint file list and runtime probe are those of this story's last typed run on "
                  "profile unit"])
        proc, answer = run(root, stub, f"{TEST_FILE_REL}::test_add", "test_add")
        # t-2064 fix round A, B3: a second call over the same bytes and entries of a WHOLE walk (receipt on the row, every proved per-check
        # record readable) is answered `already_probed`: the walk's repeat is the old road's one question. These two checks add what the
        # "twice" check (a subset test) does not: the EXACT key set of that answer, `_repeat_answer`'s keys plus `notes`.
        check_eq("pinned answer: exit 0, the walk's repeat is answered already_probed (B3)", (proc.returncode, answer.get("verdict")),
                 (0, "already_probed"))
        check_eq("pinned answer: the key set is the already_probed answer's", sorted(answer), sorted(ANSWER_KEYS + ["notes"]))
    with fresh() as root:
        manifest = manifest_of(root)
        for row in manifest["tests"]:
            if row["instance_id"] == "test_dead_assert":
                row["file"] = "tests/nope.py"
        write_json(task_of(root) / "work" / "automation-manifest.json", manifest)
        proc, got = run(root, stub, f"{TEST_FILE_REL}::test_dead_assert", "test_dead_assert")
        check_eq("pinned mismatch: the probe runs", (proc.returncode, got.get("verdict")), (0, "no_failure"))
        # t-2064 P4b: the walk makes no repeat check (so no "not the file the row names" note), chooses no target by the id, and the
        # missing manifest fields are the aggregate's `manifest_fields_missing`, not a note
        check_eq("pinned mismatch: the notes, in order", read_record(root, "test_dead_assert").get("notes"), [
            "command, fingerprint file list and runtime probe are those of this story's last typed run on "
            "profile unit"])


def the_repeat_is_answered(stub: Path) -> None:
    logs = temp_dir("qa-probe-logs-")

    def go(root, name, node, iid, mutation="invert", **extra):
        return run(root, stub, f"{TEST_FILE_REL}::{node}", iid, mutation,
                   PROBE_STUB_LOG=str(logs / f"{name}.log"), **extra)

    def launches(name) -> int:
        path = logs / f"{name}.log"
        return len(path.read_text(encoding="utf-8").splitlines()) if path.is_file() else 0

    try:
        # AC1: the same bytes twice - the runner ran ONCE, and nothing was launched the second time.
        # t-2064 P4b: the subject is a PROVED check (`test_add`, `intended_failure`): the walk skips a check proved on the same bytes of its
        # file with the same entry (spec section 14), so the one launch and "nothing launched or written but the aggregate" hold. The ANSWER
        # of the repeat is `already_probed` by the receipt (t-2064 fix round A, B3; the spec's keys, `by`, block and words, one printed
        # line). The old subject, a `no_failure` check, is not a proof
        # and is walked again: see the "no_failure" group below (PRODUCT QUESTION 2).
        with fresh() as root:
            authored = (root / TEST_FILE_REL).read_bytes()
            aggregate = "work/probes/test_add.json"
            proc, first = go(root, "twice", "test_add", "test_add")
            check_eq("twice: the first probe runs and proves the check", (proc.returncode, first.get("verdict")),
                     (0, "intended_failure"))
            quiet = snapshot(root)
            proc, second = go(root, "twice", "test_add", "test_add")
            check("twice: exit 0", proc.returncode == 0, proc.stdout + proc.stderr)
            check_eq("twice: the fake runner was launched ONCE", launches("twice"), 1)
            check_eq("twice: nothing launched or written but the aggregate (requests, jobs, check records, receipts, manifest)",
                     {k: v for k, v in snapshot(root).items() if k != aggregate}, {k: v for k, v in quiet.items() if k != aggregate})
            check_eq("twice: the test file was never touched", (root / TEST_FILE_REL).read_bytes(), authored)
            check_eq("twice: answered, not probed (spec; PRODUCT QUESTION 1)", second.get("verdict"), "already_probed")
            check_eq("twice: the answer carries every key (spec; PRODUCT QUESTION 1)", [k for k in ANSWER_KEYS if k in second],
                     ANSWER_KEYS)
            check_eq("twice: by the receipt, saying what it said (spec; PRODUCT QUESTION 1)", (second.get("by"), second.get("prior_verdict")),
                     ("receipt", "intended_failure"))
            check_eq("twice: the block is the constant a person's word matches (spec; PRODUCT QUESTION 1)", second.get("block"),
                     PL.PROBE_BLOCK)
            check_in("twice: the words name the door (the person's word, the stage, the block) (spec; PRODUCT QUESTION 1)",
                     'waiver.py, stage S5, block "already probed on these bytes"', second.get("words", ""))
            # without --json it is ONE line (spec; the road prints the verdict's usual text)
            plain = run_script("probe_by_code.py", "--task", TASK, "--dispatch", DISPATCH, "--test",
                               f"{TEST_FILE_REL}::test_add", "--instance", "test_add",
                               cwd=root, env=env_for(root, stub, PROBE_STUB_LOG=str(logs / "twice.log")))
            check_eq("twice, no --json: exit 0 and one line (spec; PRODUCT QUESTION 1)",
                     (plain.returncode, len(plain.stdout.strip().splitlines())), (0, 1))
            check_in("twice, no --json: it says already_probed (spec; PRODUCT QUESTION 1)", "already_probed", plain.stdout)
            check_eq("twice: still one launch", launches("twice"), 1)
            # the non-JSON reader and the JSON reader see the same answer
            check_eq("twice: nothing launched or written after the printed answer either",
                     {k: v for k, v in snapshot(root).items() if k != aggregate}, {k: v for k, v in quiet.items() if k != aggregate})

        # AC1/AC2: a comment, or ANOTHER test edited, keeps the answer; the test's own code, or the module
        # skeleton, does not (D5: one test's fix never makes another test's proof stale)
        # t-2064 P4b: the walk skips a check by the sha256 of the WHOLE file it lives in (section 14), so a comment or another test's edit changes
        # that sha and the check runs again: the first two pins (a comment, another test edited) are the old repeat's (the instance's code,
        # D5) and stay red as PRODUCT QUESTION 3 of the report, unbent. An edit of the check itself, and a module-wide skip, run it: green,
        # counted as launches SINCE the previous call (the counts are no longer 1, 2, 3).
        with fresh() as root:
            proc, first = go(root, "edit", "test_add", "test_add")
            check_eq("edits: the first probe holds a receipt", (first.get("verdict"), bool(first.get("receipt"))),
                     ("intended_failure", True))
            test_file = root / TEST_FILE_REL
            body = test_file.read_bytes()
            test_file.write_bytes(body + b"\n# a comment at the end of the file\n")
            proc, got = go(root, "edit", "test_add", "test_add")
            check_eq("a comment: answered by the receipt (spec D5; PRODUCT QUESTION 3)", (got.get("verdict"), got.get("by")),
                     ("already_probed", "receipt"))
            check_eq("a comment: it holds by the code of the test (spec D5; PRODUCT QUESTION 3)", got.get("holds"), "instance_code")
            check_in("a comment: and the words say so (FR-41) (spec D5; PRODUCT QUESTION 3)", PL.code_unchanged_words(), got.get("words", ""))
            check_eq("a comment: no launch (spec D5; PRODUCT QUESTION 3)", launches("edit"), 1)
            test_file.write_bytes(body.replace(b"total = add(1, 1)", b"total = add(1, 1) + 0"))
            proc, got = go(root, "edit", "test_add", "test_add")
            check_eq("another test edited: answered, and it holds as the same test (spec D5; PRODUCT QUESTION 3)",
                     (got.get("verdict"), got.get("holds")), ("already_probed", "instance"))
            check_eq("another test edited: no comment-only words", PL.comment_only_words() in got.get("words", ""),
                     False)
            seen = launches("edit")
            test_file.write_bytes(body.replace(b'== 4, "sum must be 4"', b'== 5, "sum must be 4"'))
            proc, got = go(root, "edit", "test_add", "test_add")
            check_eq("an assert changed: the probe runs (its verdict is whatever the run says: the assert now "
                     "holds, so the inverted one never fires)", (got.get("verdict"), launches("edit") - seen),
                     ("no_failure", 1))
            seen = launches("edit")
            test_file.write_bytes(body + b"\npytestmark = []\n")
            proc, got = go(root, "edit", "test_add", "test_add")
            check_eq("pytestmark added: the probe runs (a module-wide skip is never kept)",
                     (got.get("verdict"), launches("edit") - seen), ("intended_failure", 1))

        # AC2: verdicts of the probe's own failure never block, and neither does a receipt-less intended failure
        with fresh() as root:
            proc, got = go(root, "notexec", "test_add", "test_add", PROBE_STUB_CRASH="1")
            check_eq("not_executed first", got.get("verdict"), "not_executed")
            proc, got = go(root, "notexec", "test_add", "test_add")
            check_eq("...does not block: the probe runs", (got.get("verdict"), launches("notexec")),
                     ("intended_failure", 2))
        with fresh() as root:
            # N3b: the judge no longer writes `wrong_location` (a throw before the check is `incomplete`, `cause: judgment`); the judged
            # survivor of the same shape is a pass of the dead assert, `no_failure`
            proc, got = go(root, "dead", "test_dead_assert", "test_dead_assert")
            check_eq("no_failure first", got.get("verdict"), "no_failure")
            proc, got = go(root, "dead", "test_dead_assert", "test_dead_assert")
            # t-2064 TR2-14 (F3): a survivor (`no_failure`) is carried by the walk, never answered `already_probed`: the repeat answers
            # `no_failure` again, with no `prior_verdict`, and the launches stay at the one of the first call
            check_eq("no_failure, then the same call on the same bytes and the same target: the survivor is carried, not answered (F3)",
                     (got.get("verdict"), got.get("prior_verdict"), launches("dead")),
                     ("no_failure", None, 1))
        with fresh() as root:
            write_json(task_of(root) / "work" / "automation-manifest.json", {"tests": [
                dict(next(t for t in manifest_of(root)["tests"] if t["instance_id"] == "test_add"),
                     trace_binding={"test_content_sha": "0" * 64})]})
            proc, got = go(root, "stale", "test_add", "test_add")
            check_eq("intended_failure with a stale trace_binding writes no receipt",
                     (got.get("verdict"), got.get("receipt")), ("intended_failure", None))
            proc, got = go(root, "stale", "test_add", "test_add")
            # t-2064 P4b: the check is PROVED (intended_failure on these bytes), so the repeat skips its run (launches stay 1) and answers
            # the aggregate; the receipt waits for the author's rebind (the a_rerun test pins that a complete walk then names one)
            check_eq("...and a repeat is not refused: the proved check is not run again and nothing is blocked (edge 16)",
                     (got.get("verdict"), got.get("receipt"), launches("stale")), ("intended_failure", None, 1))
        with fresh() as root:
            write_json(task_of(root) / "work" / "test-plan.json", {"rows": [{
                "id": "TS-1", "schema_version": 2, "coverage_obligations": [{"obligation_id": "OB-OTHER", "text": "x"}]}]})
            proc, got = go(root, "refused", "test_add", "test_add")
            check_eq("a publish refused by manifest_put leaves the receipt unpublished",
                     ((got.get("publish") or {}).get("published"), "sensitivity_proof" in row_of(root)), (False, False))
            proc, got = go(root, "refused", "test_add", "test_add")
            # t-2064 P4b: the proved check is not run again (launches stay 1); the call is not refused and answers the aggregate, and the
            # row is still unpublished (the manifest_put refusal stands: the plan names an obligation the row does not)
            check_eq("...and the repeat is not refused: the proved check is skipped, the publish is tried again",
                     (got.get("verdict"), launches("refused"), (got.get("publish") or {}).get("published")),
                     ("intended_failure", 1, False))

        # AC2: an oracle in a helper - the verdict was measured on other oracle bytes once the helper changed
        with fresh() as root:
            proc, got = go(root, "oracle", "test_via_helper", "test_via_helper")
            check_eq("oracle in a helper: recorded with the helper as the mutated file",
                     ((got.get("mutated_file") or {}).get("path"), got.get("verdict")),
                     ("tests/expectations.py", "intended_failure"))
            proc, got = go(root, "oracle", "test_via_helper", "test_via_helper")
            check_eq("the helper unchanged: the proved check is not run again", (got.get("verdict"), launches("oracle")),
                     ("intended_failure", 1))
            helper = root / "tests" / "expectations.py"
            helper.write_bytes(helper.read_bytes().replace(b'"sum must match"', b'"sum differs"'))
            proc, got = go(root, "oracle", "test_via_helper", "test_via_helper")
            check_eq("the helper (the oracle) changed: the probe runs", (got.get("verdict"), launches("oracle")),
                     ("intended_failure", 2))

        # AC2: a record nobody can read is absent, with a note
        with fresh() as root:
            # t-2064 P4b: the record that says a check is PROVED is the per-check record, so that is the one made unreadable (the old pin
            # corrupted the single record of a survivor, which is re-run anyway); an unreadable per-check record answers no repeat
            # (`_repeat_same_entries`, t-041 F2) and is not a proof on the walk (`_check_standing`, AR-28): the check runs again, and the
            # aggregate is rewritten readable
            go(root, "corrupt", "test_add", "test_add")
            checks_dir = task_of(root) / "work" / "probes" / "checks"
            for broken in checks_dir.glob("test_add--*.json"):
                broken.write_text("{not json", encoding="utf-8")
            proc, got = go(root, "corrupt", "test_add", "test_add")
            check_eq("a corrupt record: the check is not proved, so the probe runs again",
                     (got.get("verdict"), launches("corrupt")), ("intended_failure", 2))
            check_eq("...and the aggregate it leaves is readable", read_record(root, "test_add").get("verdict"), "intended_failure")

        # B-373 R10 / E23 + F3: a stored `incomplete` (the tool could not read the run) answers nothing, so the probe runs again; the walk
        # reads the PER-CHECK record, so that one is stamped too (a stored `incomplete` per-check record reruns; a survivor is carried);
        # only no_failure / wrong_location stand (a gap of the factory's is never a standing verdict on the test)
        with fresh() as root:
            go(root, "incompl", "test_dead_assert", "test_dead_assert")
            stamp_record(root, "test_dead_assert", verdict="incomplete")
            for one in (task_of(root) / "work" / "probes" / "checks").glob("test_dead_assert--*.json"):
                stored = json.loads(one.read_text(encoding="utf-8"))
                stored["verdict"] = "incomplete"
                write_json(one, stored)
            proc, got = go(root, "incompl", "test_dead_assert", "test_dead_assert")
            check_eq("an incomplete record does not answer a repeat: the probe runs",
                     (got.get("verdict"), launches("incompl")), ("no_failure", 2))

        # t-2064 P4b, THE GROUPS BELOW (levels and budget unavailable, a person's word, a product record, legacy records) pin the old repeat's
        # readers: `proof_level.already_probed` through `_repeat_check`, which the plain road no longer calls (the walk skips a check by its
        # per-check record, section 14, and never reads a person's word, a product record or a legacy aggregate). Their ANSWER pins stay
        # as they are: the answer is B3's `already_probed`; a `no_failure` is walked again on every call
        # (PRODUCT QUESTION 2). A pin of "the probe runs (no_failure, N)" that passes below passes ONLY because a survivor is re-run on
        # every call - not for the reason it names (the note it carries is the red pin next to it); the report lists them by name.
        # AC2: the vocabulary of levels, and the run budget, unavailable: the probe runs, with a note (in this
        # process: the file the two readers look at is a module setting)
        with fresh() as root:
            go(root, "unavail", "test_dead_assert", "test_dead_assert")
            saved_levels, saved_budget = PL.LEVELS_FILE, None
            import execution_request as ER
            os.environ["PROBE_RUN_SUITE"] = str(stub)
            os.environ["PROBE_STUB_LOG"] = str(logs / "unavail.log")
            try:
                PL.LEVELS_FILE = root / "no-such-levels.json"
                PL._reset()
                got = PBC.probe(TASK, DISPATCH, f"{TEST_FILE_REL}::test_dead_assert", "test_dead_assert", "invert")
                # t-2064 TR2-14 (F3): the survivor is carried, so the launches stay at the first call's one in every call below
                check_eq("LevelsUnavailable: the probe runs", (got.get("verdict"), launches("unavail")),
                         ("no_failure", 1))
                check_in("...with a note", "proof levels cannot be read", " ".join(got.get("notes") or []))
                PL.LEVELS_FILE = saved_levels
                PL._reset()
                saved_budget = ER.RUN_BUDGET_FILE
                ER.RUN_BUDGET_FILE = "no-such-run-budget.json"
                got = PBC.probe(TASK, DISPATCH, f"{TEST_FILE_REL}::test_dead_assert", "test_dead_assert", "invert")
                check_eq("an unreadable run-budget.json: the probe runs", (got.get("verdict"), launches("unavail")),
                         ("no_failure", 1))
                check_in("...with the budget's own note", "run-budget.json", " ".join(got.get("notes") or [])
                         .replace("no-such-run-budget.json", "run-budget.json"))
                ER.RUN_BUDGET_FILE = saved_budget
                got = PBC.probe(TASK, DISPATCH, f"{TEST_FILE_REL}::test_dead_assert", "test_dead_assert", "invert")
                check_eq("the budget back: the survivor is carried again (F3: no_failure, still one launch)",
                         (got.get("verdict"), launches("unavail")), ("no_failure", 1))
            finally:
                PL.LEVELS_FILE = saved_levels
                PL._reset()
                if saved_budget is not None:
                    ER.RUN_BUDGET_FILE = saved_budget
                os.environ.pop("PROBE_RUN_SUITE", None)
                os.environ.pop("PROBE_STUB_LOG", None)

        # A person's word passes ONE repeat: AT the record's time it is spent, one second after it passes, and
        # the repeat's own record (newer) spends it
        with fresh() as root:
            # t-2064 TR2-14 (B3/F3): the subject is a PROVED check (`test_add`): only a proved check is answered `already_probed`
            # (a survivor is carried, never answered), so the person's word has something to pass
            go(root, "word", "test_add", "test_add")
            stamp_record(root, "test_add", recorded_at="2026-09-01T00:00:00+00:00")
            give_word(root, "2026-09-01T00:00:00+00:00")
            proc, got = go(root, "word", "test_add", "test_add")
            check_eq("a word said AT the record's time is spent: answered", (got.get("verdict"), launches("word")),
                     ("already_probed", 1))
            give_word(root, "2026-09-01T00:00:01+00:00")
            proc, got = go(root, "word", "test_add", "test_add")
            check_eq("one second after: it passes, the probe runs", (got.get("verdict"), launches("word")),
                     ("intended_failure", 2))
            check_in("...and the note records the word", "probe it again, I asked", " ".join(got.get("notes") or []))
            proc, got = go(root, "word", "test_add", "test_add")
            check_eq("the third call: the repeat's own record spent the word, answered",
                     (got.get("verdict"), launches("word")), ("already_probed", 2))
            give_word(root, "2999-01-01T00:00:00+00:00", match="another block")
            proc, got = go(root, "word", "test_add", "test_add")
            check_eq("a word for another block passes nothing", got.get("verdict"), "already_probed")

        # AC2: the product level's record answers too - and it stops answering when the product file changed
        with fresh() as root:
            use_project(root)
            row = row_of(root, "test_dead_assert")
            now = PL.instance_identity(row, task_of(root), root)
            calc = root / "calc.py"
            product = {"schema_version": 1, "probe_tool": "red_sandbox.py", "instance_id": "test_dead_assert",
                       "verdict": "survived", "recorded_at": "2026-09-20T10:00:00+00:00",
                       "test_file_sha256": now["input_hash"], "test_code_sha": now["test_code_sha"],
                       "instance_identity": now["instance_identity"],
                       "mutated_files": [{"path": "calc.py", "sha256": PBC.sha256(calc.read_bytes()),
                                          "code_sha": PL.code_sha(calc.read_bytes(), "calc.py")}]}
            write_json(task_of(root) / "work" / "probes" / "product" / "test_dead_assert.json", product)
            proc, got = go(root, "product", "test_dead_assert", "test_dead_assert")
            check_eq("a product `survived` record on the same bytes answers the live probe",
                     (got.get("verdict"), got.get("by"), got.get("prior_verdict"), launches("product")),
                     ("already_probed", "product_record", "survived", 0))
            calc.write_bytes(calc.read_bytes().replace(b"a + b", b"b + a"))
            proc, got = go(root, "product", "test_dead_assert", "test_dead_assert")
            check_eq("...and the product file changed since: the probe runs", (got.get("verdict"), launches("product")),
                     ("no_failure", 1))
            calc.write_bytes(CALC.encode("utf-8"))

        # a record from before per-test binding: the raw file rule, or the file's code where it recorded one
        with fresh() as root:
            raw = PBC.sha256((root / TEST_FILE_REL).read_bytes())
            legacy = {"schema_version": 1, "probe_tool": "probe_by_code.py", "instance_id": "test_dead_assert",
                      "verdict": "no_failure", "recorded_at": "2026-09-20T10:00:00+00:00",
                      "test_file_sha256": raw, "instance_content_sha": "the-old-conftest-only-derivation",
                      "mutation_detail": {"line": 12}}
            write_json(task_of(root) / "work" / "probes" / "test_dead_assert.json", legacy)
            proc, got = go(root, "legacy", "test_dead_assert", "test_dead_assert")
            check_eq("a legacy record, raw bytes equal: answered", (got.get("verdict"), got.get("holds"), launches("legacy")),
                     ("already_probed", "raw", 0))
            test_file = root / TEST_FILE_REL
            test_file.write_bytes(test_file.read_bytes().replace(b"total > 100", b"total > 101"))
            proc, got = go(root, "legacy", "test_dead_assert", "test_dead_assert")
            check_eq("a legacy record, other bytes and no code sha: the probe runs",
                     (got.get("verdict"), launches("legacy")), ("no_failure", 1))
        with fresh() as root:
            body = (root / TEST_FILE_REL).read_bytes()
            raw = PBC.sha256(body)
            legacy = {"schema_version": 1, "probe_tool": "probe_by_code.py", "instance_id": "test_dead_assert",
                      "verdict": "no_failure", "recorded_at": "2026-09-20T10:00:00+00:00",
                      "test_file_sha256": raw, "test_code_sha": PL.code_sha(body, "test_calc.py"),
                      "mutation_detail": {"line": 12}}
            write_json(task_of(root) / "work" / "probes" / "test_dead_assert.json", legacy)
            (root / TEST_FILE_REL).write_bytes(body + b"\n# comment only\n")
            proc, got = go(root, "legacy2", "test_dead_assert", "test_dead_assert")
            check_eq("a legacy record that recorded test_code_sha holds over a comment (file_code)",
                     (got.get("verdict"), got.get("holds"), launches("legacy2")), ("already_probed", "file_code", 0))
        # a legacy record whose oracle lay OUTSIDE the test, with no mutated_file key: it cannot say which bytes
        # it measured, and never blocks
        with fresh() as root:
            body = (root / TEST_FILE_REL).read_bytes()
            legacy = {"schema_version": 1, "probe_tool": "probe_by_code.py", "instance_id": "test_via_helper",
                      "verdict": "no_failure", "recorded_at": "2026-09-20T10:00:00+00:00",
                      "test_file_sha256": PBC.sha256(body), "test_code_sha": PL.code_sha(body, "test_calc.py"),
                      "mutation_detail": {"line": 2, "file": "tests/expectations.py"}}
            write_json(task_of(root) / "work" / "probes" / "test_via_helper.json", legacy)
            proc, got = go(root, "outside", "test_via_helper", "test_via_helper")
            check_eq("a legacy record with an oracle outside the test and no mutated_file never blocks",
                     (got.get("verdict"), launches("outside")), ("intended_failure", 1))
    finally:
        cleanup(logs)


def the_receipt_flow() -> None:
    stub_dir = temp_dir("qa-probe-stub-")
    stub = stub_dir / "fake_run_suite.py"
    stub.write_text(FAKE_RUN_SUITE, encoding="utf-8")
    root = project()
    use_project(root)  # the in-process readers (reached) read the test's bytes under this project
    try:
        first = live_receipt_and_publish(root, stub)
        a_rerun_is_idempotent_and_new_bytes_are_a_new_receipt(root, stub, first)
    finally:
        cleanup(root)
        cleanup_beside(root)
    try:
        publish_orders()
        publish_dicts_are_pinned()
        hostile_instance_ids()
        an_unverified_restore_writes_no_receipt(stub)
    finally:
        cleanup(stub_dir)


def the_author_binding_is_the_latest_block_by_the_clock() -> None:
    """t-149 F-order: `author_binding` reads the blocks in the story's one order (the block's own clock, a
    reparse right after the block it supersedes), not file-name order: the reparse of an OLD attempt whose id
    starts with a letter sorts after every `2026...` block by name and used to be 'the latest' block."""
    task = temp_dir("qa-probe-binding-order-")
    try:
        runs = task / "work" / "run-blocks"
        runs.mkdir(parents=True)

        def block(name: str, attempt: str, started: str, test_sha: str, **extra) -> None:
            row = {"instance_id": "t[p]", "instance_content_sha": "fn-sha",
                   "source_fingerprint": {"test_content_sha": test_sha}}
            (runs / name).write_text(json.dumps({
                "attempt_id": attempt, "block_id": attempt, "attempt_started_at": started,
                "dispatch_id": "D-" + attempt, "results": [row], **extra}), encoding="utf-8")
        first = "20260930T050000000000Z-f302aa.json"
        block(first, "f302aa", "2026-09-30T05:00:00+00:00", "sha-old")
        block("20260930T051000000000Z-b2bb.json", "b2bb", "2026-09-30T05:10:00+00:00", "sha-new")
        block("f302aa-reparse-0123.json", "f302aa", "2026-09-30T05:00:00+00:00", "sha-old-reparse",
              reparse_of="work/run-blocks/" + first, supersedes_block_id="f302aa")
        got = PBC.author_binding(task, "t[p]", "fn-sha")
        check_eq("F-order: the latest block that ran this very function is the later ATTEMPT's, not the old "
                 "attempt's reparse (which sorts last by file name)",
                 got, {"run_block": "work/run-blocks/20260930T051000000000Z-b2bb.json",
                       "test_content_sha": "sha-new", "dispatch_id": "D-b2bb", "status": None})   # TQ1-25: the row's own status rides along
        check_eq("an empty function sha binds nothing", PBC.author_binding(task, "t[p]", ""), None)
        check_eq("a sha no block ran binds nothing", PBC.author_binding(task, "t[p]", "other"), None)
        check_eq("an instance no block ran binds nothing", PBC.author_binding(task, "other[p]", "fn-sha"), None)
        (runs / "20260930T052000000000Z-bad.json").write_text("{not json", encoding="utf-8")
        check_eq("an unreadable block is skipped, as before", PBC.author_binding(task, "t[p]", "fn-sha")["test_content_sha"],
                 "sha-new")
    finally:
        cleanup(task)


def n2_k7_the_red_probe_reads_the_stand_as_the_run_does() -> None:
    """K-N2.7 (t-300 N2, S8): `probe_by_code.probe_runtime` is a delegate of `run_suite.probe_runtime`: ONE reader, ONE exception
    class, ONE message. It held a copy that took `matched` only, so a person's word reached the role's own `--mine` and not the
    critic's red probe, and a probe that compared nothing (`no_changed_file`) was refused here and taken there (B-255 a)."""
    import run_suite
    from execution_request import ProvenanceRefused
    work = temp_dir("qa-probe-n2-k7-")
    try:
        head = "a" * 40
        image = "image:sha256:" + "b" * 64
        base = {"profile_id": "api", "timestamp": "2026-10-02T12:00:00+00:00", "environment_id": "localhost",
                "expected_source_revision": head, "observed_runtime_identity": image, "evidence_refs": ["probe/x"],
                "result": "matched", "provenance": {"technical_verification": True, "source_linkage": "exact",
                                                    "deployed_source_revision": head}}
        shapes = {
            "M": base,
            "NA1": {**base, "result": "not_applicable", "observed_runtime_identity": "", "evidence_refs": [], "provenance": {},
                    "reason_code": "no_changed_file"},
            "PC": {**base, "result": "person_confirmed", "evidence_refs": ["probe/pc"],
                   "provenance": {"technical_verification": False, "identity_kind": "person_confirmed"},
                   "person_confirmation": {"words": "yes", "at": "2026-10-02T11:00:00+00:00", "task": "T-1", "kind": "deployed",
                                           "revision": head}},
            "U": {**base, "result": "unknown", "evidence_refs": [], "provenance": {"technical_verification": False},
                  "error": "which build the stand runs could not be read", "remedy": "tell me how to read it", "asks_person": "how"},
            "MM": {**base, "result": "mismatched", "provenance": {**base["provenance"], "deployed_source_revision": "d" * 40}},
            "NA2": {**base, "result": "not_applicable", "observed_runtime_identity": "", "evidence_refs": [], "provenance": {}}}

        def read(reader, shape):
            script = work / f"probe-{shape}.py"
            script.write_text("import json; print(json.dumps(" + repr(shapes[shape]) + "))", encoding="utf-8")
            try:
                return "returned", reader({"argv": [PY, str(script)], "cwd": str(work), "timeout_s": 30})["result"]
            except Exception as exc:  # the class and the text are what is compared
                return type(exc).__name__, str(exc)
        for shape in shapes:
            mine, theirs = read(PBC.probe_runtime, shape), read(run_suite.probe_runtime, shape)
            check_eq(f"K-N2.7 {shape}: the red probe's reader and the run's say the same thing (class and text)", mine, theirs)
        check_eq("K-N2.7 B-255 a: a probe that compared nothing (`no_changed_file`) is returned here too",
                 read(PBC.probe_runtime, "NA1"), ("returned", "not_applicable"))
        check_eq("K-N2.7: a person's word is returned (the role's `--mine` and the critic's probe agree)",
                 read(PBC.probe_runtime, "PC"), ("returned", "person_confirmed"))
        check_eq("K-N2.7: an `unknown` raises ProvenanceRefused, with the probe's own words",
                 (read(PBC.probe_runtime, "U")[0], "which build the stand runs could not be read. tell me how to read it"
                  in read(PBC.probe_runtime, "U")[1]), (ProvenanceRefused.__name__, True))
        check_eq("K-N2.7 control: `matched` is returned as it always was", read(PBC.probe_runtime, "M"), ("returned", "matched"))
        check_eq("K-N2.7 control: NA without its reason code raises (it compared nothing and did not say why)",
                 read(PBC.probe_runtime, "NA2")[0], ProvenanceRefused.__name__)
        scripts = Path(PBC.__file__).resolve().parent
        mine_text = (scripts / "probe_by_code.py").read_text(encoding="utf-8")
        other = (scripts / "execution_request.py").read_text(encoding="utf-8")
        check("K-N2.7 source control: the same search shape finds a `validate_runtime_provenance(` call in execution_request.py",
              "validate_runtime_provenance(" in other)
        check("K-N2.7: and probe_by_code.py has none of its own (the copy is gone)", "validate_runtime_provenance(" not in mine_text)
    finally:
        cleanup(work)


# --- HF3-6 part 6a: the probe of the code close of S6, with no dispatch open ----------------------------

def open_the_close(root: Path, **over) -> None:
    """The story's state AT the code close of S6: the critic's dispatch accepted, S0..S5 completed, S6 not started
    (the shape `s6_reprobed_close` meets after the runner and the critic are done). `over` replaces top-level keys."""
    path = task_of(root) / "state" / "controller.json"
    state = json.loads(path.read_text(encoding="utf-8"))
    state["dispatches"][DISPATCH]["status"] = "accepted"
    state["stages"] = {f"S{i}": {"status": "completed"} for i in range(6)}
    state["scope"] = list(state["dispatches"][DISPATCH]["scope"])
    state.update(over)
    write_json(path, state)


def run_close(root: Path, stub: Path, test: str, instance: str, **extra):
    proc = run_script("probe_by_code.py", "--task", TASK, "--s6-close", "--test", test, "--instance", instance,
                      "--json", cwd=root, env=env_for(root, stub, **extra))
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    try:
        payload = json.loads("\n".join(lines)) if lines and lines[0].startswith("{") else {}
    except ValueError:
        payload = {}
    return proc, payload


def project_bytes(root: Path) -> dict:
    """{path: sha256} of every file of the project outside the story's artifacts: the author's files and the state."""
    found = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            found[path.relative_to(root).as_posix()] = PBC.sha256(path.read_bytes())
    return found


def the_s6_close_context(stub: Path) -> None:
    node, iid = f"{TEST_FILE_REL}::test_add", "test_add"
    # A-K8: while a dispatch is running the context is refused BEFORE anything is read or mutated (position (g))
    with fresh() as root:
        before, story = project_bytes(root), snapshot(root)
        proc, got = run_close(root, stub, node, iid)
        check_eq("A-K8 running dispatch: exit 2, one JSON line, status refused", (proc.returncode, got.get("status")),
                 (2, "refused"))
        check_in("A-K8 the refusal names the open dispatch and its door", f"`--dispatch {DISPATCH}`",
                 got.get("error", ""))
        check_eq("A-K8 the test file, the oracle and the whole project are byte for byte as they were",
                 project_bytes(root), before)
        check("A-K8 no byte copy folder was made", not PBC.copy_dir(root).exists(), str(PBC.copy_dir(root)))
        check("A-K8 no request, no job, no record", not (task_of(root) / "work" / "probe-requests").exists()
              and not (task_of(root) / "work" / "probes" / f"{iid}.json").exists())
        check_eq("A-K8 the story's probe artifacts are the snapshot's", snapshot(root), story)
        # in-process: the refusal comes before the dead probes are settled, a lock is taken or the test is read
        calls = []
        saved = (PBC.scan_copies, PBC.claim_key, PBC._test_path)
        PBC.scan_copies = lambda *a, **k: calls.append("scan_copies")
        PBC.claim_key = lambda *a, **k: calls.append("claim_key")
        PBC._test_path = lambda *a, **k: calls.append("_test_path")
        try:
            try:
                PBC.probe(TASK, "", node, iid, "invert", s6_close=True)
                raised = False
            except PBC.Refusal:
                raised = True
        finally:
            PBC.scan_copies, PBC.claim_key, PBC._test_path = saved
        check_eq("A-K8 position: refused before _test_path, scan_copies and any lock", (raised, calls), (True, []))
    # A-K9: in the close context the probe runs under the context's id and answers as under a dispatch
    with fresh() as root:
        open_the_close(root)
        authored = (root / TEST_FILE_REL).read_bytes()
        proc, got = run_close(root, stub, node, iid)
        check_eq("A-K9 the close context: exit 0, the verdict of a probe under a dispatch, and the same places (F-4)",
                 (proc.returncode, got.get("verdict"), got.get("expected_location"), got.get("actual_location")),
                 (0, "intended_failure", f"{TEST_FILE_REL}:6", f"{TEST_FILE_REL}:6"))
        check_eq("A-K9 the record names the context", read_record(root, iid).get("dispatch_id"), "S6-close-r1")
        check_eq("A-K9 the author's test is back as it was", (root / TEST_FILE_REL).read_bytes(), authored)
        check_eq("A-K9 the request is the context's", json.loads(
            (task_of(root) / "work" / "probe-requests" / f"probe-walk-{iid}-1.json").read_text(encoding="utf-8")   # a walk's request, per run
        ).get("dispatch_id"), "S6-close-r1")
    with fresh() as root:
        proc, under = run(root, stub, node, iid)
        check_eq("A-K9 the same fixture under --dispatch gives the same verdict and places",
                 (under.get("verdict"), under.get("expected_location"), under.get("actual_location")),
                 ("intended_failure", f"{TEST_FILE_REL}:6", f"{TEST_FILE_REL}:6"))
    # the repeat over the same bytes is answered, and a person's word for it is looked up under S6
    # t-2064 P4b: the three repeat/stage groups below (this one and the two spies) pin `PL.already_probed(stage=...)`, which the walk road
    # does not call at all, and a survivor (`no_failure`) is walked again: they stay red and unbent - PRODUCT QUESTION 1 (the answer and
    # the person's-word door under S5 and S6) and 2 (a survivor repeat), see the report.
    with fresh() as root:
        open_the_close(root)
        # t-2064 TR2-14 (B3/F3): the subject is a PROVED check - a survivor is carried, never answered `already_probed`
        proc, first = run_close(root, stub, f"{TEST_FILE_REL}::test_add", "test_add")
        check_eq("A-K9 repeat: the first probe runs", (proc.returncode, first.get("verdict")), (0, "intended_failure"))
        proc, second = run_close(root, stub, f"{TEST_FILE_REL}::test_add", "test_add")
        check_eq("A-K9 repeat: answered, not probed", (proc.returncode, second.get("verdict")), (0, "already_probed"))
        check_in("A-K9 repeat: the person's word is asked for under stage S6", "waiver.py, stage S6,",
                 second.get("words", ""))
    with fresh() as root:
        open_the_close(root)
        seen = {}
        saved = PL.already_probed

        def spy(*args, **kwargs):
            seen.update(kwargs)
            return {"probed": False, "notes": []}
        PL.already_probed = spy
        try:
            os.environ["PROBE_RUN_SUITE"] = str(stub)
            PBC.probe(TASK, "", node, iid, "invert", s6_close=True)
        finally:
            PL.already_probed = saved
            os.environ.pop("PROBE_RUN_SUITE", None)
        check_eq("A-K9 already_probed is called with stage='S6' in the close context", seen.get("stage"), "S6")
    with fresh() as root:
        seen = {}
        saved = PL.already_probed

        def spy_plain(*args, **kwargs):
            seen.update(kwargs)
            return {"probed": False, "notes": []}
        PL.already_probed = spy_plain
        model_entries(root, stub, node, iid)
        try:
            os.environ["PROBE_RUN_SUITE"] = str(stub)
            PBC.probe(TASK, DISPATCH, node, iid, "invert")
        finally:
            PL.already_probed = saved
            os.environ.pop("PROBE_RUN_SUITE", None)
        check_eq("A-K9 under a dispatch the stage stays empty (as before)", seen.get("stage"), "")
    # the context is refused when S6 is closed, or the case is not the story's: nothing changes
    for label, over, needle in (
            ("S6 completed", {"stages": {**{f"S{i}": {"status": "completed"} for i in range(6)},
                                         "S6": {"status": "completed", "receipt_id": "S6-code-only-1"}}},
             "S6 is already closed (S6-code-only-1)"),
            ("S5 not completed", {"stages": {**{f"S{i}": {"status": "completed"} for i in range(5)},
                                             "S5": {"status": "running"}}}, "S6 has not started: S5 is running"),
            ("a case outside the scope", {"scope": ["TC-101"]}, "TC-100 is not in the story's approved scope"),
            ("an empty scope", {"scope": []}, "is not in the story's approved scope")):
        with fresh() as root:
            open_the_close(root)
            open_the_close(root, **over)
            before = project_bytes(root)
            proc, got = run_close(root, stub, node, iid)
            check_eq(f"{label}: exit 2, refused, the project is byte for byte as it was",
                     (proc.returncode, got.get("status"), project_bytes(root)), (2, "refused", before))
            check_in(f"{label}: the refusal says why", needle, got.get("error", ""))


# --- RH1-8 B3: the critic path asks for the open dispatch before its first byte ---------------------------

def run_dispatch(root: Path, stub: Path, test: str, instance: str, dispatch: str, task: str = TASK):
    # the model file is world, not the probe's work: a test that compares the project's bytes before and after the call writes it
    # first (`model_entries`, same bytes), so the comparison still covers everything the PROBE could write
    model_entries(root, stub, test, instance, dispatch, task)
    proc = run_script("probe_by_code.py", "--task", task, "--dispatch", dispatch, "--test", test,
                      "--instance", instance, "--mutation", "invert", "--json", cwd=root, env=env_for(root, stub))
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    try:
        payload = json.loads("\n".join(lines)) if lines and lines[0].startswith("{") else {}
    except ValueError:
        payload = {}
    return proc, payload


def set_dispatch_state(root: Path, mutate) -> None:
    path = task_of(root) / "state" / "controller.json"
    state = json.loads(path.read_text(encoding="utf-8"))
    mutate(state)
    write_json(path, state)


def rh1_8_dispatch_asked_first(stub: Path) -> None:
    node, iid = f"{TEST_FILE_REL}::test_add", "test_add"

    def close_it(state):
        state["dispatches"][DISPATCH]["status"] = "accepted"

    # P1, P1b, P1-text: nothing open -> refused before any byte
    with fresh() as root:
        set_dispatch_state(root, close_it)
        model_entries(root, stub, node, iid)
        before, story = project_bytes(root), snapshot(root)
        proc, got = run_dispatch(root, stub, node, iid, DISPATCH)
        check_eq("RH1-8 P1 no open dispatch: exit 2, status refused", (proc.returncode, got.get("status")),
                 (2, "refused"))
        check_eq("RH1-8 P1 the project is byte for byte as it was", project_bytes(root), before)
        check("RH1-8 P1 no copy dir, no request, no record", not PBC.copy_dir(root).exists()
              and not (task_of(root) / "work" / "probe-requests").exists()
              and not (task_of(root) / "work" / "probes" / f"{iid}.json").exists()
              and snapshot(root) == story)
        error = got.get("error", "")
        check("RH1-8 P1-text names cause: tooling, tooling_findings and unverified, and no reopen promise",
              all(s in error for s in ("cause: tooling", "tooling_findings", "unverified", "Nothing was read or changed",
                                       f"no open dispatch {DISPATCH} in story {TASK}"))
              and "reopen" not in error, error)
        check("RH1-8 F5 the Detail keeps the reason and names no door of the --mine caller (FR-2)",
              "Detail: no active dispatch in story" in error and not any(
                  s in error for s in ("controller.py", "--operation", "--task", "--label", "orchestrator opens")), error)
        calls = []
        saved = (PBC.scan_copies, PBC.claim_key, PBC._test_path)
        PBC.scan_copies = lambda *a, **k: calls.append("scan_copies")
        PBC.claim_key = lambda *a, **k: calls.append("claim_key")
        PBC._test_path = lambda *a, **k: calls.append("_test_path")
        prior = os.environ.get("CLAUDE_PROJECT_DIR")
        os.environ["CLAUDE_PROJECT_DIR"] = str(root)
        try:
            try:
                PBC.probe(TASK, DISPATCH, node, iid, "invert")
                raised = False
            except PBC.Refusal:
                raised = True
        finally:
            PBC.scan_copies, PBC.claim_key, PBC._test_path = saved
            if prior is None:
                os.environ.pop("CLAUDE_PROJECT_DIR", None)
            else:
                os.environ["CLAUDE_PROJECT_DIR"] = prior
        check_eq("RH1-8 P1b position: refused before _test_path, scan_copies and any lock", (raised, calls),
                 (True, []))
    # P1c, P14: a stored intended_failure record, then the dispatch closes
    with fresh() as root:
        proc, first = run_dispatch(root, stub, node, iid, DISPATCH)
        check_eq("RH1-8 P1c the first probe runs", (proc.returncode, first.get("verdict")), (0, "intended_failure"))
        record_path = task_of(root) / "work" / "probes" / f"{iid}.json"
        stored = record_path.read_bytes()
        set_dispatch_state(root, close_it)
        model_entries(root, stub, node, iid)
        before = project_bytes(root)
        proc, got = run_dispatch(root, stub, node, iid, DISPATCH)
        check_eq("RH1-8 P14 an already probed instance with no open dispatch -> refused, not already_probed",
                 (proc.returncode, got.get("status"), got.get("verdict")), (2, "refused", None))
        check_eq("RH1-8 P1c a stored intended_failure record is untouched",
                 (record_path.read_bytes(), project_bytes(root)), (stored, before))
    # P2: a parent_retry ancestor id still probes and keeps the passed id
    with fresh() as root:
        def resumed(state):
            state["dispatches"][DISPATCH]["parent_retry"] = "S5-qa-code-critic-0"
            state["dispatches"]["S5-qa-code-critic-0"] = {"id": "S5-qa-code-critic-0", "stage": "S5",
                                                          "role": "qa-code-critic", "status": "blocked"}
        set_dispatch_state(root, resumed)
        proc, got = run_dispatch(root, stub, node, iid, "S5-qa-code-critic-0")
        request = json.loads((task_of(root) / "work" / "probe-requests" / f"probe-walk-{iid}-1.json").read_text(
            encoding="utf-8"))   # a walk's request, per run
        check_eq("RH1-8 P2 a parent_retry ancestor id still probes, and the idempotency_key starts with the passed id",
                 (proc.returncode, got.get("verdict"),
                  str(request.get("idempotency_key", "")).startswith("S5-qa-code-critic-0:")),
                 (0, "intended_failure", True))
    # P3: two open; the case narrows
    with fresh() as root:
        def two_open(state):
            state["dispatches"]["S5-qa-code-critic-2"] = {"id": "S5-qa-code-critic-2", "stage": "S5",
                                                          "role": "qa-code-critic", "status": "running",
                                                          "scope": ["TC-999"], "budget": {"requests": 50}}
        set_dispatch_state(root, two_open)
        model_entries(root, stub, node, iid)
        os.environ["PROBE_RUN_SUITE"] = str(stub)
        try:
            # the model file is read by the PASSED dispatch id only (`_models_standing`: `if ctx.dispatch and file.is_file()`, P4b); an
            # empty id passes the context check by narrowing but finds no model, so the call names the open dispatch whose scope holds the case
            got = PBC.probe(TASK, DISPATCH, node, iid, "invert")
        finally:
            os.environ.pop("PROBE_RUN_SUITE", None)
        check_eq("RH1-8 P3 two open, the case narrows: probes", got.get("verdict"), "intended_failure")
    with fresh() as root:
        def two_wide(state):
            state["dispatches"]["S5-qa-code-critic-2"] = dict(state["dispatches"][DISPATCH],
                                                              id="S5-qa-code-critic-2")
        set_dispatch_state(root, two_wide)
        before = project_bytes(root)
        try:
            PBC.probe(TASK, "", node, iid, "invert")
            error = ""
        except PBC.Refusal as exc:
            error = str(exc)
        check_eq("RH1-8 P3 two open, the case does not narrow: refused early",
                 (bool(error), project_bytes(root)), (True, before))
        check_in("RH1-8 P3 the several-dispatches wording", f"several dispatches are open in story {TASK}", error)
        check("RH1-8 F5 and the several-dispatches Detail drops the --dispatch/--task door", "say which one" not in error
              and "--dispatch" not in error and "--task" not in error, error)
    # P4: unreadable controller.json
    for label, text in (("garbage", "{not json"), ("array", "[]")):
        with fresh() as root:
            (task_of(root) / "state" / "controller.json").write_text(text, encoding="utf-8")
            model_entries(root, stub, node, iid)
            before = project_bytes(root)
            proc, got = run_dispatch(root, stub, node, iid, DISPATCH)
            check_eq(f"RH1-8 P4 unreadable controller.json ({label}) -> refused before any byte",
                     (proc.returncode, got.get("status"), project_bytes(root)), (2, "refused", before))
    # P5: the dispatch belongs to another story
    with fresh() as root:
        set_dispatch_state(root, close_it)
        write_json(root / "qa-factory" / "artifacts" / "OTHER-1" / "state" / "controller.json", {
            "schema_version": "2", "revision": "1", "dispatches": {"S5-qa-code-critic-9": {
                "id": "S5-qa-code-critic-9", "stage": "S5", "role": "qa-code-critic", "status": "running",
                "scope": ["TC-100"], "budget": {"requests": 50}}}})
        model_entries(root, stub, node, iid, "S5-qa-code-critic-9")
        before = project_bytes(root)
        proc, got = run_dispatch(root, stub, node, iid, "S5-qa-code-critic-9")
        check_eq("RH1-8 P5 a dispatch of another story -> refused",
                 (proc.returncode, got.get("status"), project_bytes(root)), (2, "refused", before))


def second_hop_name_in_two_files_is_refused() -> None:
    """t-2162 fix round: the B2 rule at the second hop - a name with a check in two files two hops away is refused, naming each file:line and
    the `--at` door (one helper, `_declared_in_files`); with ONE such file the refusal is the single-door one, as before."""
    root = temp_dir("qa-probe-second-hop-")
    try:
        (root / "tests").mkdir()
        (root / "tests" / "test_x.py").write_text("from helpers import shop\n\n\ndef test_x():\n    shop(1)\n", encoding="utf-8")
        (root / "tests" / "helpers.py").write_text("import page_a\nimport page_b\n\n\ndef shop(n):\n    verify(n)\n", encoding="utf-8")
        (root / "tests" / "page_a.py").write_text("def verify(n):\n    assert n == 1, 'a'\n", encoding="utf-8")
        (root / "tests" / "page_b.py").write_text("def verify(n):\n    assert n == 2, 'b'\n", encoding="utf-8")
        spec = PBC.parse_node("tests/test_x.py::test_x", root)
        path = root / spec["file"]
        text = path.read_text(encoding="utf-8")
        cfg = {"tests_root": "tests"}
        try:
            PBC.find_oracle(text, spec, path, root, [], None, cfg)
            check("second hop, two files: refused", False, "no refusal")
        except PBC.ToolRefusal as refusal:
            for word in ("tests/page_a.py", "tests/page_b.py", "--at <file>:<line>", "no body is mutated"):
                check_in(f"second hop, two files: the refusal says {word}", word, str(refusal))
        (root / "tests" / "page_b.py").write_text("def other(n):\n    pass\n", encoding="utf-8")
        try:
            PBC.find_oracle(text, spec, path, root, [], None, cfg)
            check("second hop, one file: refused", False, "no refusal")
        except PBC.ToolRefusal as refusal:
            check_in("second hop, one file: the single door is kept", "one hop further, in `verify`", str(refusal))
            check_not_in("second hop, one file: no two-file refusal", "no body is mutated", str(refusal))
    finally:
        cleanup(root)


def main() -> None:
    second_hop_name_in_two_files_is_refused()
    n2_k7_the_red_probe_reads_the_stand_as_the_run_does()
    the_author_binding_is_the_latest_block_by_the_clock()
    stub_dir = temp_dir("qa-probe-stub-")
    stub = stub_dir / "fake_run_suite.py"
    stub.write_text(FAKE_RUN_SUITE, encoding="utf-8")
    root = project()
    try:
        record = invert_plain_assert(root, stub)
        class_method(root, stub)
        hamcrest_style(root, stub)
        dead_assert(root, stub)
        raises_first(root, stub)
        no_assert(root, stub)
        oracle_in_a_helper(root, stub)
        restore_on_failure(stub)
        a_run_that_executed_nothing_keeps_the_standing_record(stub)
        multiline_keeps_line_count()
        plan_mutation_is_pinned()
        if record:
            window_validates(root, record)
        # After the window check: the stub records no job, so a repeated probe of the same
        # instance and mutation rewrites the evidence file the first record's sha names.
        report_rows_as_before()
        reporter_in_the_summary(stub)
        non_python_test_refused(root, stub)
        run_directory(stub)
    finally:
        cleanup(root)
        cleanup_beside(root)
        cleanup(stub_dir)
    the_receipt_flow()
    stub_dir = temp_dir("qa-probe-stub-")
    stub = stub_dir / "fake_run_suite.py"
    stub.write_text(FAKE_RUN_SUITE, encoding="utf-8")
    try:
        the_record_and_the_answer_are_pinned(stub)
        the_repeat_is_answered(stub)
        the_s6_close_context(stub)
        rh1_8_dispatch_asked_first(stub)
    finally:
        cleanup(stub_dir)
    stub_dir = temp_dir("qa-probe-stub-")
    stub = stub_dir / "fake_run_suite.py"
    stub.write_text(FAKE_RUN_SUITE, encoding="utf-8")
    try:
        two_profiles_over_one_root(stub)
    finally:
        cleanup(stub_dir)
    main_exit_order_is_pinned()
    missing_facts_and_a_refused_publish_do_not_change_the_exit()
    raw_bytes_through_manifest_from_tests()
    through_real_run_suite()
    finish("test_probe_by_code")


if __name__ == "__main__":
    main()
