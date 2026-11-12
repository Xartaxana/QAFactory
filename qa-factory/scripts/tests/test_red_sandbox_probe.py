"""red_sandbox.py --probe: ask, prepare, run the mutated targets, verify, record, publish, clean — one call.

A critic used to run roughly thirty manual commands for one red probe (prepare, two
`run_suite.py` launches, `--detail` per failing test to read the traceback by hand, verify,
`manifest_put.py`) — the sequence named in the S5-122 transcripts this change automates.
`run_suite.py` belongs to another package edited at the same time as this one, so every run
below goes through it as a real subprocess, never an import; a tiny stand-in test command
(named `pytest` so `run_suite`'s own pytest detection recognises it) actually imports and
calls the product function, so a mutation's real behaviour — not a canned answer — decides
red or green, exactly as a live probe would.

t-043 C: the unmutated baseline is the AUTHOR'S green run of the same test over the same bytes
(`execution_request.fresh_evidence`), not a second run in a second sandbox; a test nobody ran green is
`not_executed` before a sandbox exists; a target already probed over these bytes answers the whole request
`already_probed`; the mutated run is ONE launch per distinct case among the targets, selecting only their
nodes; a mutated row that gave no result is `probe_defect`, never `survived`. So the fixtures below seed the
author's green with a real `run_suite.py --mine`, and the stand-in test command counts its own launches
(`FAKE_PYTEST_LOG`; a `--collect-only` is not a launch).
"""
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness import check, check_eq, check_in, check_not_in, cleanup, finish, temp_dir, use_project  # noqa: E402

import execution_request as ER  # noqa: E402
import probe_by_code as PBC  # noqa: E402
import proof_level as PL  # noqa: E402
import red_sandbox as RS  # noqa: E402

PY = sys.executable
TASK = "PROBE-1"
DISPATCH = "S5-qa-code-critic-1"
RUN_SUITE = Path(__file__).resolve().parents[1] / "run_suite.py"

# A stand-in test command, real enough to matter: it imports the product module fresh off
# disk (so a mutated copy in the sandbox behaves differently from the original) and calls the
# named function, building a genuine pytest-shaped junit failure — location and message —
# from whatever AssertionError actually fires. Named `pytest` (no extension) so
# `execution_request.is_pytest_command` recognises it and `run_suite.py --mine` builds the
# request straight from node ids, the same path a real pytest install would take.
FAKE_PYTEST = r'''
import importlib.util
import os
import re
import sys
import traceback
import unittest
from pathlib import Path

sys.path.insert(0, os.getcwd())  # the product module (`import calc`) lives beside the tests
args = sys.argv[1:]
if "--collect-only" in args:
    # node_ids.py's own collect: one real `path::function` line per `def test_*` found in
    # each `.py` file named on the command line — enough for the mismatch check this fake
    # stands in for, without a real pytest install.
    for f in [a for a in args if a.endswith(".py")]:
        text = Path(f).read_text(encoding="utf-8")
        for name in re.findall(r"^def (test_\w+)", text, re.M):
            print(f"{f}::{name}")
    sys.exit(0)

if os.environ.get("FAKE_PYTEST_LOG"):  # one line per LAUNCH: where it ran and which nodes it was given
    with open(os.environ["FAKE_PYTEST_LOG"], "a", encoding="utf-8") as log:
        log.write(os.getcwd() + "|" + " ".join(a for a in args if "::" in a) + "\n")

report = args[args.index("--junitxml") + 1] if "--junitxml" in args else ""
nodes = [a for a in args if "::" in a]


def run_one(node):
    file_part, func_part = node.split("::", 1)
    path = Path(file_part).resolve()
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    try:
        getattr(module, func_part)()
        return "passed", "", ""
    except unittest.SkipTest:
        return "skipped", "", ""
    except AssertionError as exc:
        frames = traceback.extract_tb(exc.__traceback__)
        frame = next((f for f in reversed(frames) if Path(f.filename).resolve() == path), frames[-1])
        loc = f"{file_part}:{frame.lineno}"
        message = f"AssertionError: {exc}" if str(exc) else "AssertionError: assert False"
        return "failed", message, f"{loc}: AssertionError"
    except Exception as exc:  # a broken import/setup — never counted as an assertion
        return "error", f"{type(exc).__name__}: {exc}", f"{type(exc).__name__}: {exc}"


rows, failures = [], 0
for node in nodes:
    file_part, func_part = node.split("::", 1)
    status, message, text = run_one(node)
    classname = file_part.replace("/", ".").replace("\\", ".")
    classname = classname[:-3] if classname.endswith(".py") else classname
    if status == "passed":
        rows.append(f'<testcase classname="{classname}" name="{func_part}"/>')
    elif status == "skipped":
        rows.append(f'<testcase classname="{classname}" name="{func_part}"><skipped message="skipped"/></testcase>')
    else:
        failures += 1
        tag = "failure" if status == "failed" else "error"
        rows.append(f'<testcase classname="{classname}" name="{func_part}"><{tag} '
                    f'message="{message}">{text}</{tag}></testcase>')

xml = (f'<testsuite tests="{len(rows)}" failures="{failures}" errors="0" skipped="0">'
      + "".join(rows) + "</testsuite>")
if report:
    Path(report).parent.mkdir(parents=True, exist_ok=True)
    Path(report).write_text(xml, encoding="utf-8")
sys.exit(1 if failures else 0)
'''

TEST_FILE = '''\
from calc import add


def test_add():
    assert add(2, 2) == 4, "sum must be 4"
'''
# Three tests of one file, over two product files: the shapes of "two targets in one case" and of "two cases".
MULTI = '''\
from calc import add
from calc2 import sub


def test_add():
    assert add(2, 2) == 4, "sum must be 4"


def test_sub():
    assert sub(5, 2) == 3, "difference must be 3"


def test_mul():
    assert 2 * 3 == 6
'''
CALC_OK = "def add(a, b):\n    return a + b\n"
CALC_BROKEN = "def add(a, b):\n    return a - b\n"
CALC2_OK = "def sub(a, b):\n    return a - b\n"
CALC2_BROKEN = "def sub(a, b):\n    return a + b\n"
ASSERT_LINE = 5  # 1-indexed line of the `assert` in TEST_FILE
MULTI_LINES = {"test_add": 6, "test_sub": 10}


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=1), encoding="utf-8")


PROVENANCE = {"profile_id": "unit", "timestamp": "2026-09-22T10:00:00Z", "environment_id": "local",
             "expected_source_revision": "source-1", "observed_runtime_identity": "build-1",
             "evidence_refs": ["probe"], "result": "matched",
             "provenance": {"technical_verification": True, "source_linkage": "exact",
                            "deployed_source_revision": "source-1"}}


def git(root: Path, *args):
    return subprocess.run(["git", "-C", str(root), "-c", "user.email=t@t", "-c", "user.name=t", *args],
                          capture_output=True, text=True, timeout=60)


def row_of(root: Path, iid: str, case: str, file: str = "tests/test_calc.py") -> dict:
    return {"case": case, "covers": [case], "file": file, "selector": iid, "instance_id": iid,
            "case_version_links": [{"case_id": case, "version": "cv_1"}],
            # the raw sha256 of the file, as manifest_from_tests.py binds it (t-016 Amendment 2)
            "trace_binding": {"test_content_sha": RS.digest(root / file)}}


def project(fake_pytest: Path, *, tests: str = TEST_FILE, products: dict | None = None, rows=None,
            scope=("TC-100",)) -> Path:
    """A git project (its product files COMMITTED, so the author's green has a source revision the product
    file can be compared at), a story with a running critic dispatch, and the manifest of `rows`."""
    root = temp_dir("qa-probe-project-")
    (root / "tests").mkdir()
    (root / "tests" / "test_calc.py").write_text(tests, encoding="utf-8")
    for name, text in (products or {"calc.py": CALC_OK}).items():
        (root / name).write_text(text, encoding="utf-8")
    git(root, "init", "-q")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "author")
    revision = git(root, "rev-parse", "HEAD").stdout.strip()
    provenance = dict(PROVENANCE, expected_source_revision=revision,
                      provenance=dict(PROVENANCE["provenance"], deployed_source_revision=revision))
    probe_script = root.parent / (root.name + "-probe.py")
    probe_script.write_text("import json\nprint(json.dumps(" + repr(provenance) + "))\n", encoding="utf-8")

    (root / "qa-factory" / "state").mkdir(parents=True)
    write_json(root / "qa-factory" / "config.json", {
        "profiles": [{"profile_id": "unit", "selected": True, "roots": {"test": "tests"},
                     "commands": {"one_test": {"argv": [PY, str(fake_pytest), "--junitxml",
                                                        "{report_path}"], "cwd": "."}},
                     "reporter": {"kind": "junit-xml"}, "selectors": {"verified": True}}],
        "execution": {"runtime_probes": {"unit": {"argv": [PY, str(probe_script)], "cwd": ".",
                                                   "timeout_s": 20}}}})

    task_root = root / "qa-factory" / "artifacts" / TASK
    # Realistic S5 state: the automator's own initial run already stamped `first_test_run_at`
    # (`run_suite.stamp_first_run`), so the critic's probe — which may be the first `--mine`
    # this test process makes — does not race that one-time write against the author-tree
    # byte comparison `verify()` performs.
    write_json(task_root / "pipeline.json", {"stages": {"S5": {"status": "running"}},
                                             "first_test_run_at": "2026-09-22T09:00:00+00:00"})
    write_json(task_root / "state" / "controller.json", {
        "schema_version": "2", "revision": "1", "source_revision": revision,
        "dispatches": {DISPATCH: {"id": DISPATCH, "stage": "S5", "role": "qa-code-critic", "status": "running",
                                  "scope": list(scope), "budget": {"requests": 50}}}})
    rows = rows if rows is not None else [row_of(root, "test_add", "TC-100")]
    write_json(task_root / "work" / "automation-manifest.json", {"tests": rows})
    # A run block's test_content_sha is a fingerprint over test and helper files - another
    # quantity, never what a receipt binds.
    write_json(task_root / "work" / "run-blocks" / "block1.json", {
        "results": [{"instance_id": r["instance_id"],
                    "source_fingerprint": {"source_sha": "src-1", "test_content_sha": "fp-of-test-and-helpers"}}
                    for r in rows],
        "runtime_provenance": {"observed_runtime_identity": "build-1", "environment_id": "env-1"}})
    os.environ["FAKE_PYTEST_LOG"] = str(root.parent / (root.name + "-launches.log"))
    use_project(root)
    PL._reset()
    return root


def fake() -> Path:
    path = temp_dir("qa-probe-fake-pytest-") / "pytest"
    path.write_text(FAKE_PYTEST, encoding="utf-8")
    return path


def task_of(root: Path) -> Path:
    return root / "qa-factory" / "artifacts" / TASK


def seed_green(root: Path, *cases: str) -> None:
    """The author's own run of these cases: a real `run_suite.py --mine`, so the story holds a job, a run block
    and a stand observation exactly as the automator leaves them."""
    proc = subprocess.run([PY, "-B", str(RUN_SUITE), "--mine", *cases], cwd=str(root), capture_output=True,
                          text=True, encoding="utf-8", errors="replace", timeout=300,
                          env=dict(os.environ, CLAUDE_PROJECT_DIR=str(root), QA_FACTORY_SKIP_DASHBOARD_REFRESH="1",
                                   PYTHONDONTWRITEBYTECODE="1"))
    check(f"seed: the author's run of {', '.join(cases)} is green", proc.returncode == 0, proc.stdout + proc.stderr)
    PL._reset()


def launches(root: Path) -> list:
    """[(cwd, [nodes])] of every launch of the stand-in test command so far."""
    path = root.parent / (root.name + "-launches.log")
    if not path.is_file():
        return []
    return [(line.split("|", 1)[0], line.split("|", 1)[1].split()) for line in
            path.read_text(encoding="utf-8").splitlines() if line.strip()]


def finish_project(root: Path) -> None:
    cleanup(root)
    for extra in root.parent.glob(root.name + "-*"):
        cleanup(extra) if extra.is_dir() else extra.unlink(missing_ok=True)


def mutation_request(root: Path, *, cases=("TC-100",), replacement: str = CALC_BROKEN,
                     node_id: str = "tests/test_calc.py::test_add", collect: dict | None = None,
                     expected_reason: str = "sum must be 4", targets=None) -> Path:
    if targets is None:
        targets = [{"path": "calc.py", "before_sha256": RS.digest(root / "calc.py"),
                    "replacement_utf8": replacement, "instance_id": "test_add", "node_id": node_id,
                    "expected_location": f"tests/test_calc.py:{ASSERT_LINE}",
                    "expected_reason": expected_reason, "obligation_id": "OB-ADD-1",
                    "defect_location": "calc.py:2", "assertion_id": "add_returns_sum"}]
    path = root / "mutations.json"
    doc = {"mutations": targets, "cases": list(cases)}
    if collect:
        doc["collect"] = collect
    write_json(path, doc)
    return path


def probe(root: Path, request: Path, **kwargs) -> dict:
    return RS.probe(root, request, task_of(root), dispatch=DISPATCH, timeout=300, **kwargs)


def give_word(root: Path, at: str, match: str = PL.PROBE_BLOCK) -> None:
    path = task_of(root) / "pipeline.json"
    pipeline = json.loads(path.read_text(encoding="utf-8"))
    pipeline["stage_overrides"] = [{"stage": "S5", "match": match, "decision": "probe it again, I asked", "at": at}]
    write_json(path, pipeline)


def clear_word(root: Path) -> None:
    path = task_of(root) / "pipeline.json"
    pipeline = json.loads(path.read_text(encoding="utf-8"))
    pipeline.pop("stage_overrides", None)
    write_json(path, pipeline)


def manifest_of(root: Path) -> dict:
    return json.loads((task_of(root) / "work" / "automation-manifest.json").read_text(encoding="utf-8"))


def entry_of(root: Path, iid: str = "test_add") -> dict:
    return next(t for t in manifest_of(root)["tests"] if t.get("instance_id") == iid)


class counting_prepare:
    """Counts the calls of `red_sandbox.prepare`: a sandbox is what a refusal must not create."""
    def __enter__(self):
        self.real, self.calls = RS.prepare, []

        def wrapped(repo, destination, request, task_root=None):
            self.calls.append(str(destination))
            return self.real(repo, destination, request, task_root)
        RS.prepare = wrapped
        return self

    def __exit__(self, *_exc):
        RS.prepare = self.real


def sandboxes(root: Path) -> list:
    return list(root.parent.glob(f"{root.name}-redprobe-*"))


def accepted() -> None:
    root = project(fake())
    task_root = task_of(root)
    try:
        seed_green(root, "TC-100")
        seeded = len(launches(root))
        request = mutation_request(root)
        result = probe(root, request)
        check_eq("a mutation that breaks the product is accepted", result["status"], "accepted")
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
        # t-2064 fix round G, B3 (EP-W): the python test has a check reader, so the receipt is `one_check`: it proves the one check it
        # names, and NOTHING is published to the manifest - no binding, no row ref (the critic names it with a `product` entry).
        check_eq("the receipt proves the one check it names", (receipt.get("scope"), [c["key"] for c in receipt.get("checks") or []]),
                 ("one_check", [f"tests/test_calc.py:{ASSERT_LINE}"]))
        manifest = manifest_of(root)
        check_eq("the manifest carries no obligation binding for a one-check receipt", manifest.get("obligation_bindings"), None)
        row = next(t for t in manifest["tests"] if t.get("instance_id") == "test_add")
        check_eq("the instance row names no receipt", row.get("sensitivity_proof"), None)
        check_eq("and the author's row keeps its file", row.get("file"), "tests/test_calc.py")
        check_eq("and its case links", row.get("covers"), ["TC-100"])
        check_eq("one instance row, not two", len([t for t in manifest["tests"]
                                                   if t.get("instance_id") == "test_add"]), 1)
        check_eq("so reached() reads no level for the test as a whole", PL.reached(row, manifest, task_root)["level"], None)
        check_in("and the note names the door: the `product` entry in the probe's model file",
                 "`product` entry", " ".join(result["notes"]))
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
        # fix round H: a one-check receipt has no level, yet the same product probe again is answered by `already_probed` (item 4 of
        # `proof_level.already_probed`, kind="product"). Killing mutation: drop the `kind="product"` argument in red_sandbox.probe.
        receipt_file = task_root / result["receipts"][0]["path"]
        before_receipt = receipt_file.read_bytes()
        again = probe(root, mutation_request(root))
        check_eq("a second probe of the same bytes: already_probed, no second run", again["status"], "already_probed")
        check_eq("...and the receipt file is untouched", receipt_file.read_bytes(), before_receipt)
        check_eq("...and publishes nothing either", manifest_of(root), manifest)
    finally:
        finish_project(root)


def upgrades_a_live_receipt_and_keeps_the_other_instances() -> None:
    """Live then product (edge row 7), since t-2064 fix round G (B3): the product receipt of a test whose checks the factory can list is
    `one_check` and publishes NOTHING, so the live ref and the binding (and its `instance_ids`) stay as they were - a receipt that proves
    one check is neither a downgrade of the live one nor a proof of the obligation. (A `whole_unlisted` receipt still replaces and unions:
    `test_probe_product_publish.py`.) Since t-043 C a live receipt on the same bytes ANSWERS the probe (F6 a); the probe runs again only
    on new bytes or with a person's word."""
    root = project(fake())
    task_root = task_of(root)
    try:
        seed_green(root, "TC-100")
        seeded = len(launches(root))
        live = {"instance_id": "test_add", "case_version": "cv_1",
                "test_content_hash": RS.digest(root / "tests" / "test_calc.py"),
                "source_revision": "src-1", "build_id": "build-1", "mutation": "invert",
                "expected_assertion_failure": "x", "actual_failure": "x", "assertion_location": "t.py:5",
                "restoration_evidence": "r", "failure_kind": "assertion", "proof_level": "live",
                "probe_tool": "probe_by_code.py", "mutation_kind": "assertion", "immutable": True,
                "receipt_hash": "h-live", "probe_record": "work/probes/test_add.json"}
        write_json(task_root / "work" / "sensitivity-receipts" / "test_add-live-held.json", live)
        write_json(task_root / "work" / "probes" / "test_add.json", {
            "schema_version": 1, "probe_tool": "probe_by_code.py", "instance_id": "test_add",
            "verdict": "intended_failure", "recorded_at": "2026-09-20T10:00:00+00:00",
            "receipt": {"path": "work/sensitivity-receipts/test_add-live-held.json"},
            "test_file_sha256": RS.digest(root / "tests" / "test_calc.py"), "mutation_detail": {"line": 5}})
        held = {"path": "work/sensitivity-receipts/test_add-live-held.json",
                "sha256": RS.digest(task_root / "work" / "sensitivity-receipts" / "test_add-live-held.json")}
        manifest_path = task_root / "work" / "automation-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["tests"][0]["sensitivity_proof"] = {"receipt_ref": held}
        manifest["retracted_instances"] = ["gone"]  # a row taken out on purpose must not come back
        manifest["obligation_bindings"] = [{"obligation_id": "OB-ADD-1", "instance_ids": ["gone", "other"],
                                            "sensitivity": "proven", "proof_kind": "executed_red_probe",
                                            "probe_receipt_ref": held["path"], "design_assessment": "sufficient"}]
        write_json(manifest_path, manifest)
        check_eq("before: the row is at the live level",
                 PL.reached(manifest["tests"][0], manifest, task_root)["level"], "live")
        answered = probe(root, mutation_request(root))
        check_eq("F6 a: a live receipt on the same bytes answers the product probe too",
                 (answered["status"], answered["instances"]["test_add"]["by"], len(launches(root)) - seeded),
                 ("already_probed", "receipt", 0))
        check_eq("...and the manifest is untouched", json.loads(manifest_path.read_text(encoding="utf-8")), manifest)
        give_word(root, "2999-01-01T00:00:00+00:00")
        result = probe(root, mutation_request(root))
        check_eq("with a person's word the product probe is accepted", result["status"], "accepted")
        after = json.loads(manifest_path.read_text(encoding="utf-8"))
        # t-2064 fix round G, B3: the python test's product receipt is `one_check` - it proves one check and has no level for the test,
        # so it publishes NOTHING: the live ref and the binding stay exactly as they were (never a downgrade, never a false proof)
        check_eq("live then product: a one-check receipt moves nothing in the manifest", after, manifest)
        check_eq("and a receipt was still written, as a one-check one",
                 json.loads((task_root / result["receipts"][0]["path"]).read_text(encoding="utf-8")).get("scope"), "one_check")
        got = PL.reached(after["tests"][0], after, task_root)
        check_eq("after: the row still reaches the live level", (got["level"], got["issues"]), ("live", []))
        check_in("...and the word is on record in the notes", "probe it again, I asked", " ".join(result["notes"]))
        # a second product probe of the same instance changes nothing either (the word still stands)
        result = probe(root, mutation_request(root))
        check_eq("a second product probe moves nothing", json.loads(manifest_path.read_text(encoding="utf-8")), manifest)
    finally:
        finish_project(root)


def survived() -> None:
    """A red run that does not match the pinned oracle (wrong expected reason — the mutation
    fired, but not the way the mutation file claims): the probe says so, publishes nothing,
    and still cleans up. `verify()`'s own vocabulary calls this `incomplete`; the probe's
    vocabulary calls it `survived` — no proof the mutation was caught as claimed. It leaves its verdict on
    record, and a repeat of it - by either tool - is ANSWERED."""
    root = project(fake())
    task_root = task_of(root)
    try:
        seed_green(root, "TC-100")
        seeded = len(launches(root))
        request = mutation_request(root, expected_reason="a completely different assertion message")
        result = probe(root, request)
        check_eq("an unmatched red is reported as survived, never accepted", result["status"], "survived")
        check_eq("nothing is published", result["receipts"], [])
        check_eq("no sandbox is left behind", sandboxes(root), [])
        manifest_path = task_root / "work" / "automation-manifest.json"
        before = manifest_path.read_text(encoding="utf-8")
        check("the manifest is untouched", "obligation_bindings" not in json.loads(before))
        path = PL.probe_record_path(task_root, "test_add", "product")
        check_eq("the verdict is on record: work/probes/product/test_add.json says survived",
                 json.loads(path.read_text(encoding="utf-8"))["verdict"], "survived")
        frozen = path.read_bytes()
        check_eq("that took ONE launch (the author's green was the baseline)", len(launches(root)) - seeded, 1)
        # a repeat of the same request: answered, no launch, nothing rewritten
        again = probe(root, request)
        check_eq("a repeat of a survivor over the same bytes: already_probed", again["status"], "already_probed")
        check_eq("...by the product record, saying what it said", (again["instances"]["test_add"]["by"],
                                                                 again["instances"]["test_add"]["prior_verdict"]),
                 ("product_record", "survived"))
        check_in("...and the request is answered whole: take it out of mutations[]", "take it out of mutations[] "
                 "and probe the rest", again["words"])
        check_eq("...with no launch, no sandbox, and the record byte-identical",
                 (len(launches(root)) - seeded, sandboxes(root), path.read_bytes()), (1, [], frozen))
        # ...and probe_by_code, asked about the same test over the same bytes, answers from the same record
        got = PBC.probe(TASK, DISPATCH, "tests/test_calc.py::test_add", "test_add", "invert")
        check_eq("then probe_by_code: answered by the product record too",
                 (got.get("verdict"), got.get("by"), got.get("prior_verdict")), ("already_probed", "product_record", "survived"))
        check_eq("...and it wrote nothing: no live record, no request", (
            (task_root / "work" / "probes" / "test_add.json").exists(), (task_root / "work" / "probe-requests").exists()),
            (False, False))
        # AC2: the record is read, not trusted: a corrupt one is treated as absent, with a note
        path.write_text("{not json", encoding="utf-8")
        result = probe(root, request)
        check_eq("a corrupt product record: the probe runs", result["status"], "survived")
        check_in("...with a note that it was not read", "cannot be read", " ".join(result["notes"]))
        check_eq("...and the new record replaces it", json.loads(path.read_text(encoding="utf-8"))["verdict"], "survived")
        # a probe_defect after a person's word LIFTS the survivor's block (the newest record decides)
        give_word(root, "2999-01-01T00:00:00+00:00")
        nothing = probe(root, mutation_request(root, replacement=CALC_OK))
        check_eq("with a word, a mutation that changes nothing is the probe's defect", nothing["status"], "probe_defect")
        check_in("...naming why", "mutated and unmutated runs both ended 'passed'", " ".join(nothing["notes"]))
        check_eq("...on record as probe_defect", json.loads(path.read_text(encoding="utf-8"))["verdict"], "probe_defect")
        clear_word(root)
        entry = entry_of(root)
        check_eq("the survivor's block is lifted: probe_defect never blocks, and neither does the word gone",
                 PL.already_probed(entry, manifest_of(root), task_root, project=root)["probed"], False)
        before = len(launches(root))
        request = mutation_request(root, expected_reason="a completely different assertion message")
        third = probe(root, request)
        check_eq("...so the next probe runs (a launch was made)", (third["status"], len(launches(root)) - before),
                 ("survived", 1))
    finally:
        finish_project(root)


def no_author_green_is_not_executed_before_a_sandbox_exists() -> None:
    root = project(fake())
    try:
        with counting_prepare() as prepared:
            result = probe(root, mutation_request(root))
        check_eq("no green run of the author on record: not_executed", result["status"], "not_executed")
        words = (result["instances"].get("test_add") or {}).get("words", "")
        check_eq("with the instance's words", words, "no green run of test_add on these bytes is on record: the "
                 "author's run comes first; a product probe breaks the product under a green test")
        check_in("...which are in the notes too", words, " ".join(result["notes"]))
        check_eq("no launch, no sandbox prepared, none on disk", (launches(root), prepared.calls, sandboxes(root)),
                 ([], [], []))
        check_eq("nothing is written for a not_executed: no product record",
                 PL.probe_record_path(task_of(root), "test_add", "product").exists(), False)
    finally:
        finish_project(root)


def a_green_that_does_not_stand() -> None:
    """MC6's sibling: an older green with a NEWER red over the same bytes is not the author's green."""
    root = project(fake())
    task_root = task_of(root)
    try:
        seed_green(root, "TC-100")
        store = ER.JobStore(task_root / "state" / "execution-jobs")
        green = store.jobs()[-1]
        red_block = None
        for number in (1, 2):  # the policy's `covers_after_failures` is 2: two reds are the answer
            block_path = root / green["run_block"]
            block = json.loads(block_path.read_text(encoding="utf-8"))
            block["results"][0]["status"] = "failed"
            red_block = block_path.with_name(f"9999999999999{number}-red.json")
            write_json(red_block, block)
            red = json.loads(json.dumps(green))
            red.update(job_id=f"red-job-{number}", idempotency_key=f"red-key-{number}", execution_status="failed",
                       created_at=f"2999-01-01T00:00:0{number}+00:00", updated_at=f"2999-01-01T00:00:0{number}+00:00",
                       run_block=red_block.relative_to(root).as_posix())
            store.write(red)
        PL._reset()
        with counting_prepare() as prepared:
            result = probe(root, mutation_request(root))
        words = (result["instances"].get("test_add") or {}).get("words", "")
        check_eq("an older green and a newer red: not_executed", (result["status"], prepared.calls),
                 ("not_executed", []))
        check_in("...naming the red result and what to do with it", "test_add: its newest result over these bytes "
                 "is red (red-job-", words)
        check_in("...the red goes to triage", "a probe needs a green test; the red goes to triage", words)
    finally:
        finish_project(root)


def a_green_on_other_code_is_stale_and_a_comment_keeps_it() -> None:
    root = project(fake())
    try:
        seed_green(root, "TC-100")
        test = root / "tests" / "test_calc.py"
        original = test.read_bytes()
        test.write_bytes(original.replace(b'"sum must be 4"', b'"sum must be four"'))
        PL._reset()
        with counting_prepare() as prepared:
            result = probe(root, mutation_request(root))
        words = (result["instances"].get("test_add") or {}).get("words", "")
        check_eq("a green on other CODE bytes: not_executed, nothing prepared", (result["status"], prepared.calls),
                 ("not_executed", []))
        check_in("...it does not stand, and the author runs it on these bytes first", "its earlier result does not "
                 "stand (", words)
        check_in("...naming the bytes", "the author runs it on these bytes first", words)
        test.write_bytes(original + b"\n# a comment since the green\n")
        PL._reset()
        before = len(launches(root))
        result = probe(root, mutation_request(root))
        check_eq("a comment-only edit since the green: the author's green stands, the probe runs",
                 (result["status"], len(launches(root)) - before), ("accepted", 1))
        receipt = json.loads((task_of(root) / result["receipts"][0]["path"]).read_text(encoding="utf-8"))
        check_eq("t-043 C D2: the test file hashes X and the manifest binds Y: the receipt has NO code or identity "
                 "fields", ("test_code_sha" in receipt, "instance_identity" in receipt), (False, False))
        check_in("...and the note says it binds raw bytes only", "the receipt binds raw bytes only",
                 " ".join(result["notes"]))
        check_eq("...still bound to what the manifest binds", receipt["test_content_hash"],
                 PBC.sha256(original))
    finally:
        finish_project(root)


def a_budget_or_a_stand_that_cannot_answer_gives_the_own_baseline() -> None:
    root = project(fake())
    try:
        seed_green(root, "TC-100")
        seeded = len(launches(root))
        saved = ER.RUN_BUDGET_FILE
        ER.RUN_BUDGET_FILE = "no-such-run-budget.json"
        try:
            with counting_prepare() as prepared:
                result = probe(root, mutation_request(root))
        finally:
            ER.RUN_BUDGET_FILE = saved
        check_eq("no budget file: the probe runs its own baseline (2 launches: the baseline and the mutated run)",
                 (result["status"], len(launches(root)) - seeded, len(prepared.calls)), ("accepted", 2, 2))
        check_in("...with the budget's one note", "unreadable", " ".join(result["notes"]))
        check("...one of the launches ran in a baseline sandbox", any("baseline" in cwd for cwd, _n in launches(root)[seeded:]))
        check_eq("...and no author baseline claimed", (result["instances"]["test_add"]["baseline"] or {}).get("source"), None)
    finally:
        finish_project(root)
    # an unobservable stand: the decision is its own baseline, with the stand's words - never `not_executed`
    root = project(fake())
    try:
        seed_green(root, "TC-100")
        probe_script = next(root.parent.glob(root.name + "-probe.py"))
        probe_script.write_text("import sys\nsys.exit(3)\n", encoding="utf-8")
        with counting_prepare() as prepared:
            result = probe(root, mutation_request(root))
        check("the stand cannot be observed now: the probe went on to its own baseline (two sandboxes prepared)",
              len(prepared.calls) == 2, str(result))
        check_in("...saying it is the stand and not the test", "the stand's version cannot be observed now",
                 " ".join(result["notes"]))
        check_not_in("...and refused nothing for it", "no green run of", " ".join(result["notes"]))
    finally:
        finish_project(root)


def one_launch_per_distinct_case() -> None:
    """AC3 AT and BEYOND: two targets of ONE case are one launch (never one per target); two cases are two
    (never one) - each selecting only its targets' nodes, never the whole case (test_mul is in TC-100 too)."""
    products = {"calc.py": CALC_OK, "calc2.py": CALC2_OK}
    targets_of = lambda root: [  # noqa: E731
        {"path": "calc.py", "before_sha256": RS.digest(root / "calc.py"), "replacement_utf8": CALC_BROKEN,
         "instance_id": "test_add", "node_id": "tests/test_calc.py::test_add",
         "expected_location": f"tests/test_calc.py:{MULTI_LINES['test_add']}", "expected_reason": "sum must be 4",
         "obligation_id": "OB-ADD-1", "defect_location": "calc.py:2", "assertion_id": "add_returns_sum"},
        {"path": "calc2.py", "before_sha256": RS.digest(root / "calc2.py"), "replacement_utf8": CALC2_BROKEN,
         "instance_id": "test_sub", "node_id": "tests/test_calc.py::test_sub",
         "expected_location": f"tests/test_calc.py:{MULTI_LINES['test_sub']}", "expected_reason": "difference must be 3",
         "obligation_id": "OB-SUB-1", "defect_location": "calc2.py:2", "assertion_id": "sub_returns_difference"}]
    # two targets, one case
    root = project(fake(), tests=MULTI, products=products, scope=("TC-100",))
    write_json(task_of(root) / "work" / "automation-manifest.json", {"tests": [
        row_of(root, "test_add", "TC-100"), row_of(root, "test_sub", "TC-100"), row_of(root, "test_mul", "TC-100")]})
    try:
        seed_green(root, "TC-100")
        seeded = len(launches(root))
        result = probe(root, mutation_request(root, targets=targets_of(root)))
        check_eq("two targets of one case: accepted", result["status"], "accepted")
        run = launches(root)[seeded:]
        check_eq("...in ONE launch", len(run), 1)
        check_eq("...selecting the two targets' nodes and not test_mul", sorted(run[0][1]),
                 ["tests/test_calc.py::test_add", "tests/test_calc.py::test_sub"])
        check_eq("...two receipts", len(result["receipts"]), 2)
    finally:
        finish_project(root)
    # two cases
    root = project(fake(), tests=MULTI, products=products, scope=("TC-100", "TC-101"))
    write_json(task_of(root) / "work" / "automation-manifest.json", {"tests": [
        row_of(root, "test_add", "TC-100"), row_of(root, "test_mul", "TC-100"), row_of(root, "test_sub", "TC-101")]})
    try:
        seed_green(root, "TC-100", "TC-101")
        seeded = len(launches(root))
        result = probe(root, mutation_request(root, cases=("TC-100", "TC-101"), targets=targets_of(root)))
        check_eq("two targets of two cases: accepted", result["status"], "accepted")
        run = launches(root)[seeded:]
        check_eq("...in TWO launches, one per case, in the order of `cases`",
                 [nodes for _cwd, nodes in run], [["tests/test_calc.py::test_add"], ["tests/test_calc.py::test_sub"]])
    finally:
        finish_project(root)


def a_pre_existing_red_probe_key_still_launches() -> None:
    """MC8: the product file is not fingerprinted, so a second probe over the same sandbox path lands on the key
    of the first one's job. An earlier job that ended GREEN on that key (a mutation that changed nothing) would
    answer the new run - `reused` - and the real mutation would never be launched: `--again` makes it a run. (A
    red earlier job does not answer: `build_mine_request` never reuses a key whose job did not pass.)"""
    root = project(fake())
    try:
        seed_green(root, "TC-100")
        destination = root.parent / (root.name + "-redprobe-fixed")
        first = probe(root, mutation_request(root, replacement=CALC_OK), destination=destination)
        check_eq("the first probe: a mutation that changes nothing, whose mutated run PASSED on the key",
                 first["status"], "probe_defect")
        keys = {j["idempotency_key"]: j.get("execution_status") for j in
                ER.JobStore(task_of(root) / "state" / "execution-jobs").jobs()
                if j["request"].get("purpose") == "red_probe"}
        check_eq("...leaving one green red_probe job behind", sorted(keys.values()), ["passed"])
        before = len(launches(root))
        second = probe(root, mutation_request(root), destination=destination)
        check_eq("the second probe over the same sandbox path (the same red_probe key) launches its mutated run",
                 (second["status"], len(launches(root)) - before), ("accepted", 1))
        now = {j["idempotency_key"] for j in ER.JobStore(task_of(root) / "state" / "execution-jobs").jobs()
               if j["request"].get("purpose") == "red_probe"}
        check("...under a NEW key (again-2), the old one untouched", len(now) == len(keys) + 1
              and any(k.endswith(":again-2") for k in now - set(keys)), str(now))
    finally:
        finish_project(root)


def a_mutated_row_that_gave_no_result_is_the_probes_defect() -> None:
    """AC4 (MC7): skipped, an error, no report row at all - never `survived`."""
    cases = (("skipped", "import unittest\n\n\ndef add(a, b):\n    raise unittest.SkipTest('no')\n",
              "tests/test_calc.py::test_add", "the mutated run gave this test no result (skipped)"),
             ("an error", "def add(a, b):\n    raise ValueError('broken')\n", "tests/test_calc.py::test_add",
              "the mutated run gave this test no result (error)"),
             ("no report row", CALC_BROKEN, "tests/test_calc.py::test_add",
              "the mutated run gave this test no result (not_run)"))
    for name, replacement, node, words in cases:
        fake_pytest = fake()
        root = project(fake_pytest)
        try:
            seed_green(root, "TC-100")
            if name == "no report row":
                # The row is bound by the `report_test_id` the job request carries (the branch's M21), not by
                # a node the mutation pins: so "no row" is a report that spells the test other than the
                # request does. The stand-in is swapped AFTER the author's green was seeded.
                fake_pytest.write_text(FAKE_PYTEST.replace(
                    '    classname = classname[:-3] if classname.endswith(".py") else classname\n',
                    '    classname = classname[:-3] if classname.endswith(".py") else classname\n'
                    '    classname = "renamed." + classname\n'), encoding="utf-8")
            result = probe(root, mutation_request(root, replacement=replacement, node_id=node))
            check_eq(f"{name}: probe_defect, never survived", result["status"], "probe_defect")
            check_in(f"{name}: the words say it is the probe's own run", words + ": the probe's own run, not the test",
                     " ".join(result["notes"]))
            check_eq(f"{name}: the proof says owner factory", (result["instances"]["test_add"]["verdict"],
                                                                result["instances"]["test_add"].get("owner")),
                     ("probe_defect", "factory"))
            check_eq(f"{name}: nothing is published", result["receipts"], [])
            record = json.loads(PL.probe_record_path(task_of(root), "test_add", "product").read_text(encoding="utf-8"))
            check_eq(f"{name}: the record says probe_defect (which never blocks a repeat)", record["verdict"], "probe_defect")
        finally:
            finish_project(root)
    # the manual path follows the same rule: `verify` on a result with no status at all
    checked = RS.verify({"repo": ".", "original_hashes": {}, "targets": [{"instance_id": "i", "expected_location": "x:1",
                                                                          "expected_reason": "r"}]}, [], None)
    check_eq("verify --verify-receipt with no result for the target: probe_defect (D8)", checked["status"], "probe_defect")
    try:
        RS.write_sensitivity_receipts(Path("."), {"repo": ".", "original_hashes": {}, "targets": [
            {"instance_id": "i", "expected_location": "x:1", "expected_reason": "r"}]},
            [{"instance_id": "i", "status": "skipped"}], {})
        said = ""
    except ValueError as exc:
        said = str(exc)
    check_in("write_sensitivity_receipts quotes the defect in its refusal", "i: the mutated run gave this test no "
             "result (skipped)", said)


def a_request_that_cannot_be_probed_is_not_executed_before_prepare() -> None:
    root = project(fake())
    try:
        seed_green(root, "TC-100")
        request = mutation_request(root)
        doc = json.loads(request.read_text(encoding="utf-8"))
        with counting_prepare() as prepared:
            other = dict(doc, mutations=[dict(doc["mutations"][0], instance_id="test_nowhere")])
            write_json(root / "m1.json", other)
            got = probe(root, root / "m1.json")
            check_eq("a target the manifest does not name: not_executed", got["status"], "not_executed")
            check_in("...with the door: the automator's manifest_put", "manifest_put.py", " ".join(got["notes"]))
            write_json(root / "m2.json", dict(doc, cases=["TC-999"]))
            got = probe(root, root / "m2.json")
            check_eq("a case that is not among `cases`: not_executed", got["status"], "not_executed")
            check_in("...naming `cases` and the way to add the case", "add its case to `cases`", " ".join(got["notes"]))
            manifest = manifest_of(root)
            manifest["tests"][0].pop("selector")
            write_json(task_of(root) / "work" / "automation-manifest.json", manifest)
            got = probe(root, request)
            check_eq("a row with no test function (no selector, so no node): not_executed", got["status"], "not_executed")
            check_in("...naming the field", "names no test function (`selector`)", " ".join(got["notes"]))
        check_eq("none of them prepared a sandbox or launched anything", (prepared.calls, len(launches(root))), ([], 1))
        # not a JSON object; empty mutations; empty cases: today's answers
        write_json(root / "m3.json", [1, 2])
        check_eq("a request that is not a JSON object: not_executed, said", probe(root, root / "m3.json")["status"],
                 "not_executed")
        write_json(root / "m4.json", {"mutations": [], "cases": ["TC-100"]})
        got = probe(root, root / "m4.json")
        check_eq("empty mutations: prepare's own refusal, unchanged", got["status"], "not_executed")
        check_in("...naming the step", "prepare (mutated): red probe requires a specific mutation", " ".join(got["notes"]))
        write_json(root / "m5.json", {"mutations": doc["mutations"], "cases": []})
        check_in("empty cases: today's answer", "the request names no `cases`", " ".join(probe(root, root / "m5.json")["notes"]))
    finally:
        finish_project(root)


def another_stories_task_root_is_refused_with_its_words() -> None:
    root = project(fake())
    try:
        seed_green(root, "TC-100")
        elsewhere = root.parent / (root.name + "-elsewhere") / TASK
        (elsewhere / "work").mkdir(parents=True)
        (elsewhere / "work" / "automation-manifest.json").write_text(
            (task_of(root) / "work" / "automation-manifest.json").read_text(encoding="utf-8"), encoding="utf-8")
        with counting_prepare() as prepared:
            got = RS.probe(root, mutation_request(root), elsewhere, dispatch=DISPATCH, timeout=300)
        check_eq("a --task-root that is not this project's story: not_executed, nothing prepared",
                 (got["status"], prepared.calls), ("not_executed", []))
        check_in("...saying so", "is not this project's story", " ".join(got["notes"]))
    finally:
        finish_project(root)


def missing_cases() -> None:
    root = temp_dir("qa-probe-no-cases-")
    (root / "calc.py").write_text(CALC_OK, encoding="utf-8")
    write_json(root / "mutations.json", {"mutations": [
        {"path": "calc.py", "before_sha256": RS.digest(root / "calc.py"),
         "replacement_utf8": CALC_BROKEN, "instance_id": "test_add",
         "expected_location": "tests/test_calc.py:4", "expected_reason": "sum must be 4"}]})
    try:
        result = RS.probe(root, root / "mutations.json", root / "qa-factory" / "artifacts" / TASK)
        check_eq("a request with no `cases` is not_executed, nothing prepared",
                 result["status"], "not_executed")
        check_in("and says why", "cases", " ".join(result["notes"]))
    finally:
        cleanup(root)


def prepare_failure_reported() -> None:
    """A mechanical `prepare()` failure (bytes moved under the mutation) is reported in
    `notes` with the step's name — never a crash, never silently swallowed."""
    root = project(fake())
    try:
        seed_green(root, "TC-100")
        request = mutation_request(root)
        doc = json.loads(request.read_text(encoding="utf-8"))
        doc["mutations"][0]["before_sha256"] = "0" * 64
        write_json(request, doc)
        result = probe(root, request)
        check_eq("a mutation whose before_sha256 does not match current bytes is not_executed",
                 result["status"], "not_executed")
        check_in("naming the prepare step", "prepare", " ".join(result["notes"]))
        check_in("(the product file is not the one the green ran: its own baseline was the decision)",
                 "the product file changed since the author's green", " ".join(result["notes"]))
    finally:
        finish_project(root)


def node_id_mismatch_passthrough() -> None:
    """`--probe` answers a bad pinned node id exactly as plain `prepare()` always has — the
    runner's own refusal shape, never wrapped in the new `instances/receipts/notes` envelope."""
    fake_pytest = fake()
    root = project(fake_pytest)
    try:
        seed_green(root, "TC-100")
        collect = {"argv": [PY, str(fake_pytest), "--junitxml", "{report_path}"], "cwd": "."}
        request = mutation_request(root, node_id="tests/test_calc.py::test_add_typo", collect=collect)
        result = probe(root, request)
        check_eq("a pinned id the collect does not find is node_id_mismatch",
                 result.get("status"), "node_id_mismatch")
        check_eq("the missing id travels with it",
                 [m["asked"] for m in result.get("missing", [])], ["tests/test_calc.py::test_add_typo"])
        check_in("with the nearest real one", "test_add", json.dumps(result.get("missing")))
        check("the envelope is the runner's own shape, not instances/receipts/notes",
              not ({"instances", "receipts"} & set(result)))
        check_eq("no sandbox is left behind", sandboxes(root), [])
    finally:
        finish_project(root)


def two_profiles_over_one_root() -> None:
    """EP1-16 (A-K9, F-A2 (a)): profiles `unit` and `ui` over one `tests/` root. `red_sandbox --probe` has no profile
    choice of its own: its launch is `run_suite --mine CASE --node-id ...`, whose request builder takes the profile
    from the manifest row of the node's file (A-K2). A row that names `unit` reaches the launch; a row that names none
    is refused by that builder and nothing launches (the control: the same project, the name taken off the row)."""
    for named in (True, False):
        fake_pytest = fake()
        root = project(fake_pytest)
        try:
            config = json.loads((root / "qa-factory" / "config.json").read_text(encoding="utf-8"))
            config["profiles"].append(dict(json.loads(json.dumps(config["profiles"][0])), profile_id="ui"))
            write_json(root / "qa-factory" / "config.json", config)
            manifest = manifest_of(root)
            for test in manifest["tests"]:
                test["profile_id"] = "unit"
            write_json(task_of(root) / "work" / "automation-manifest.json", manifest)
            seed_green(root, "TC-100")
            if not named:
                for test in manifest["tests"]:
                    test.pop("profile_id")
                write_json(task_of(root) / "work" / "automation-manifest.json", manifest)
            seeded = len(launches(root))
            result = probe(root, mutation_request(root))
            label = "A-K9 (the row names `unit`)" if named else "A-K9 control (the row names none)"
            if named:
                check_eq(f"{label}: the probe reaches the launch and is accepted", result.get("status"), "accepted")
                check_eq(f"{label}: ONE launch, in the mutated sandbox", len(launches(root)) - seeded, 1)
            else:
                check(f"{label}: nothing is accepted", result.get("status") != "accepted", json.dumps(result)[:300])
                check_eq(f"{label}: and nothing launched", len(launches(root)) - seeded, 0)
                check_in(f"{label}: the refusal is the builder's (a shared root, no name)", "share the test root",
                         json.dumps(result))
            check_eq(f"{label}: no sandbox is left behind", sandboxes(root), [])
        finally:
            finish_project(root)


def main() -> None:
    accepted()
    upgrades_a_live_receipt_and_keeps_the_other_instances()
    survived()
    no_author_green_is_not_executed_before_a_sandbox_exists()
    a_green_that_does_not_stand()
    a_green_on_other_code_is_stale_and_a_comment_keeps_it()
    a_budget_or_a_stand_that_cannot_answer_gives_the_own_baseline()
    one_launch_per_distinct_case()
    a_pre_existing_red_probe_key_still_launches()
    a_mutated_row_that_gave_no_result_is_the_probes_defect()
    a_request_that_cannot_be_probed_is_not_executed_before_prepare()
    another_stories_task_root_is_refused_with_its_words()
    missing_cases()
    prepare_failure_reported()
    node_id_mismatch_passthrough()
    two_profiles_over_one_root()
    finish("test_red_sandbox_probe")


if __name__ == "__main__":
    main()
