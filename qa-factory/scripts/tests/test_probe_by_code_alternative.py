"""probe_by_code.py --alternative <case>:ALT-n: the red probe walks a case's declared reading B on the one road (TQ1-25; t-2064 P5).

A temp project, the stub `PROBE_RUN_SUITE` of test_probe_by_code (it really imports and runs the mutated test), a case that declares
`alternatives`, and tests of the same Then: the night TC-001 shape `update_date > stamp` (passes under a completion stamp: the weak oracle)
and the manual shape `stamp <= t_done - tolerance` (fails under it: the strong one). The model file is the road's own: entries of
`{"models": [{"check": "<file>:<line>", "alternative": "TC-001:ALT-1", "supposes": ..., "actual": ...}]}`.
Keys K10-K31 keep the numbers of the first version of this file (t-739), rewritten for the one road in t-2064 P5; the old road's
semantics (the one-object model with `find`, the reach rule, the judge table, `--supersede`, the target lock) are gone with their code
and their keys. The fast pins of the road itself are in test_probe_alternative_road.py, of the model file's guards in
test_probe_every_check.py (`test_models_file_guards_are_the_alternatives`)."""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness import check, check_eq, check_in, cleanup, finish, run_script, temp_dir  # noqa: E402
from harness import mark_project, use_project  # noqa: E402

import contract as C  # noqa: E402
import probe_by_code as PBC  # noqa: E402
import proof_level as PL  # noqa: E402
from test_probe_by_code import (DISPATCH, FAKE_RUN_SUITE, PROVENANCE, PY, TASK, _calls, _main_in_process,  # noqa: E402
                                _streams, cleanup_beside, env_for, snapshot, task_of, write_json)

STAMP_REL = "tests/test_stamp.py"
STAMP = '''\
T_DONE = 160.0
TOLERANCE = 5.0
LABEL = "été"  # éè


def read_stamp():
    return 100.5


def unused():
    stamp = read_stamp()
    return stamp


def test_weak():
    stamp = read_stamp()
    update_date = T_DONE + 1.0
    assert update_date > stamp, "Then 2: the stamp precedes the completion"


def test_strong():
    stamp = read_stamp()
    assert stamp <= T_DONE - TOLERANCE, "Then 2: the stamp is the trigger, not the completion"


def test_both():
    stamp = read_stamp()
    assert stamp <= T_DONE - TOLERANCE, "Then 2: the stamp is the trigger, not the completion"


def test_untaken():
    stamp = read_stamp()
    if T_DONE < 0:
        marker = read_stamp()
    assert stamp <= T_DONE - TOLERANCE, "Then 2: untaken"


def test_after():
    stamp = read_stamp()
    assert stamp <= T_DONE - TOLERANCE, "Then 2: after"
    later = read_stamp()


def test_nested():
    stamp = read_stamp()

    def inner():
        return read_stamp()
    assert stamp <= T_DONE - TOLERANCE, "Then 2: nested"


def test_helper():
    helper_assert(read_stamp())


def helper_assert(stamp):
    assert stamp <= T_DONE - TOLERANCE, "Then 2: in a helper"
'''
HELPERS = "def reader():\n    return 100.5\n"
TS_REL = "tests/stamp.spec.ts"
INSTANCES = ("test_weak", "test_strong", "test_both", "test_untaken", "test_after", "test_nested")
ALT = '[{"id": "ALT-1", "then": 2, "reading": "the stamp is taken at completion", "ref": "R-2"}]'
TOKEN = "TC-001:ALT-1"
STRONG, WEAK = "160.0", "161.0"       # the value the check would read under B: the strong oracle fails on both, the weak one passes on both


def case_text(case: str, alternatives=ALT) -> str:
    key = f"alternatives: {alternatives}\n" if alternatives is not None else ""
    return f"---\nid: {case}\n{key}---\n# {case}\n\n## Then\n1. the request is accepted\n2. the stamp is the trigger time\n"


def assert_line(text: str, function: str) -> int:
    lines = text.splitlines()
    start = next(i for i, ln in enumerate(lines) if ln.startswith(f"def {function}("))
    return next(i + 1 for i in range(start, len(lines)) if lines[i].strip().startswith("assert "))


def entry(iid: str, file: str = STAMP_REL, covers=("TC-001",)) -> dict:
    return {"case": covers[0], "covers": list(covers), "file": file, "test": iid, "instance_id": iid, "selector": iid,
            "case_version_links": [{"case_id": c, "version": "cv_1"} for c in covers]}


def alt_project(*, extra_tests=(), alternatives=ALT) -> Path:
    import execution_request as ER
    root = temp_dir("qa-probe-alt-")
    (root / "tests").mkdir()
    (root / STAMP_REL).write_bytes(STAMP.encode("utf-8"))   # LF on every platform
    (root / "tests" / "helpers.py").write_text(HELPERS, encoding="utf-8")
    (root / TS_REL).write_text("test('stamp', () => { expect(1).toBe(1); });\n", encoding="utf-8")
    (root / "calc.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    bin_dir = root.parent / (root.name + "-bin")
    bin_dir.mkdir()
    fake_pytest = bin_dir / "pytest"
    fake_pytest.write_text("import sys; sys.exit(3)\n", encoding="utf-8")
    probe_script = root.parent / (root.name + "-runtime-probe.py")
    probe_script.write_text("import json\nprint(json.dumps(" + repr(PROVENANCE) + "))\n", encoding="utf-8")
    profiles = [{"profile_id": "unit", "selected": True, "roots": {"test": "tests"},
                 "commands": {"one_test": {"argv": [PY, str(fake_pytest), "--junitxml", "{report_path}"], "cwd": "."}},
                 "reporter": {"kind": "junit-xml"}, "selectors": {"verified": True}}]
    write_json(root / "qa-factory" / "config.json", {
        "tests_root": "tests", "app_root": ".", "profiles": profiles,
        "execution": {"runtime_probes": {"unit": {"argv": [PY, str(probe_script)], "cwd": ".", "timeout_s": 20}}}})
    task = root / "qa-factory" / "artifacts" / TASK
    write_json(task / "pipeline.json", {"stages": {"S5": {"status": "running"}},
                                        "first_test_run_at": "2026-09-24T09:00:00+00:00"})
    write_json(task / "state" / "controller.json", {
        "schema_version": "2", "revision": "1", "source_revision": "source-1",
        "dispatches": {DISPATCH: {"id": DISPATCH, "stage": "S5", "role": "qa-code-critic", "status": "running",
                                  "scope": ["TC-001", "TC-002"], "budget": {"requests": 50}}}})
    (task / "work" / "test-cases").mkdir(parents=True)
    (task / "work" / "test-cases" / "TC-001.md").write_text(case_text("TC-001", alternatives), encoding="utf-8")
    (task / "work" / "test-cases" / "TC-002.md").write_text(case_text("TC-002", alternatives), encoding="utf-8")
    tests = [entry(iid) for iid in INSTANCES if iid != "test_both"]
    tests.append(entry("test_both", covers=("TC-001", "TC-002")))
    tests.extend(extra_tests)
    bindings = [{"case": "TC-001", "then": 2, "instance_id": iid, "assertion_ref": f"{STAMP_REL}:{assert_line(STAMP, iid)}",
                 "status": "covered"} for iid in INSTANCES]
    bindings.append({"case": "TC-002", "then": 2, "instance_id": "test_both", "status": "covered",
                     "assertion_ref": f"{STAMP_REL}:{assert_line(STAMP, 'test_both')}"})
    write_json(task / "work" / "automation-manifest.json", {"tests": tests, "then_bindings": bindings})
    cfg = json.loads((root / "qa-factory" / "config.json").read_text(encoding="utf-8"))
    request, _n, _r, _v = ER.build_mine_request(root, ["TC-001", "TC-002"], cfg=cfg, task=TASK, dispatch_id=DISPATCH,
                                                probe=lambda spec: PROVENANCE)
    store = ER.JobStore(task / "state" / "execution-jobs")
    _action, job = store.begin(request)
    store.update(job, status="completed", execution_status="passed", freshness="fresh")
    rows = [{"instance_id": iid, "status": "passed", "instance_content_sha": c["instance_content_sha"],
             "source_fingerprint": {"source_sha": "source-1", "test_content_sha": "author-" + iid}}
            for iid, c in request["instance_contracts"].items()]
    write_json(task / "work" / "run-blocks" / "20260924T090000000000Z-author1.json", {
        "schema_version": 2, "dispatch_id": "S5-qa-automator-1", "purpose": "initial", "results": rows,
        "runtime_provenance": {"observed_runtime_identity": "build-1", "environment_id": "env-1"}})
    return root


def key_of(iid: str, text: str = STAMP) -> str:
    """The check key `--plan` lists for the test's one assert: `<file>:<line>`."""
    return f"{STAMP_REL}:{assert_line(text, iid)}"


def ent(iid: str, actual: str = STRONG, token: str = TOKEN, **more) -> dict:
    return {"check": key_of(iid), "alternative": token, "supposes": "B", "actual": actual, **more}


def put_model(root: Path, name: str, doc) -> str:
    path = task_of(root) / "work" / "probe-models" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(doc if isinstance(doc, str) else json.dumps(doc), encoding="utf-8")
    return "work/probe-models/" + name


def put_entries(root: Path, entries: list, name: str = "m.json") -> str:
    return put_model(root, name, {"models": entries})


def parse(proc) -> dict:
    text = proc.stdout.strip()
    try:
        return json.loads(text) if text.startswith("{") else {}
    except ValueError:
        return {}


def alt(root: Path, stub: Path, iid: str = "test_strong", token: str = TOKEN, model="m.json", extra=(), test=None, env=None):
    argv = ["--task", TASK, "--dispatch", DISPATCH, "--test", test or f"{STAMP_REL}::{iid}", "--instance", iid, "--json", *extra]
    if token is not None:
        argv += ["--alternative", token]
    if model is not None:
        argv += ["--model", "work/probe-models/" + model if "/" not in model else model]
    proc = run_script("probe_by_code.py", *argv, cwd=root, env=env_for(root, stub, **(env or {})))
    return proc, parse(proc)


def record_of(root: Path, iid: str, case: str = "TC-001", alt_id: str = "ALT-1") -> dict:
    path = PBC.alternative_record_path(task_of(root), iid, case, alt_id)
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def report(root: Path, stub: Path, *extra) -> list:
    proc = run_script("probe_by_code.py", "--task", TASK, "--alternatives", "--json", *extra, cwd=root, env=env_for(root, stub))
    check_eq("report: exit 0", proc.returncode, 0)
    try:
        return json.loads(proc.stdout)
    except ValueError:
        return []


def row_of(rows: list, iid: str, token: str = TOKEN) -> dict:
    return next((r for r in rows if r["instance"] == iid and r["alternative"] == token), {})


def stat_text(root: Path) -> bytes:
    return (root / STAMP_REL).read_bytes()


def with_stub(body) -> None:
    stub_dir = temp_dir("qa-probe-alt-stub-")
    stub = stub_dir / "fake_run_suite.py"
    stub.write_text(FAKE_RUN_SUITE, encoding="utf-8")
    root = alt_project()
    try:
        body(root, stub)
    finally:
        cleanup(root)
        cleanup_beside(root)
        cleanup(stub_dir)


def stub_log_lines(root: Path) -> int:
    log = root / "stub.log"
    return len(log.read_text(encoding="utf-8").splitlines()) if log.is_file() else 0


def k10_the_pair(root: Path, stub: Path) -> None:
    original = stat_text(root)
    env = {"PROBE_STUB_LOG": str(root / "stub.log")}
    put_entries(root, [ent("test_weak", WEAK)])
    proc, weak = alt(root, stub, "test_weak", env=env)
    check_eq("K10 weak oracle: exit 0, no_failure (it passes under a completion stamp)", (proc.returncode, weak.get("verdict")),
             (0, "no_failure"))
    check_eq("K10 weak: the author's bytes are back (sha equal before/after)", PBC.sha256(stat_text(root)), PBC.sha256(original))
    check_eq("K10 weak: restore verified", (weak.get("restore") or {}).get("verified"), True)
    put_entries(root, [ent("test_strong", STRONG)])
    proc, strong = alt(root, stub, "test_strong", env=env)
    check_eq("K10 strong oracle: exit 0, intended_failure (it fails under a completion stamp)",
             (proc.returncode, strong.get("verdict")), (0, "intended_failure"))
    check_eq("K10 strong: the bytes are back", PBC.sha256(stat_text(root)), PBC.sha256(original))
    check_eq("K10 strong: the failure is AT the Then's own assert", strong.get("actual_location"), key_of("test_strong"))
    check_eq("K10 strong: proved by the marker, restore verified", (strong.get("proved_by"), (strong.get("restore") or {}).get("verified")),
             ("marker", True))
    print("witness K10: sha256 before", PBC.sha256(original), "after", PBC.sha256(stat_text(root)))
    # B-2 record shape: the names the exit and print paths read
    for key in ("mutated_file", "test_file_sha256", "expected_reason", "record", "test_node", "instance_content_sha"):
        check(f"B-2 the record carries `{key}`", key in strong and strong[key] is not None, str(sorted(strong)))
    check_eq("B-2 mutated_file names the test file here", (strong["mutated_file"] or {}).get("path"), STAMP_REL)
    check_eq("K11 mutation_kind alternative_model, proof_level null (never a level the window reads)",
             (strong.get("mutation_kind"), strong.get("proof_level"), strong.get("receipt")), ("alternative_model", None, None))


def k11_no_live_receipt(root: Path, stub: Path) -> None:
    put_entries(root, [ent("test_strong")])
    before = snapshot(root)
    invert_path = task_of(root) / "work" / "probes" / "test_strong.json"
    proc, got = alt(root, stub, "test_strong")
    check_eq("K11 alternative probe ran", got.get("verdict"), "intended_failure")
    after = snapshot(root)
    new = sorted(set(after) - set(before))
    check("K11 only alternative-owned files appeared (record, per-check records, job): no receipt, no plain aggregate",
          all(("alternative" in p or "--ALT-" in p or "execution-jobs" in p or p.startswith("work/probes")) for p in new
              if p not in ("work/probe-requests", "work/probes")), str(new))
    check("K11 work/probes/<IID>.json (the plain aggregate) was not written", not invert_path.exists())
    check("K11 no live receipt", not any("sensitivity-receipts" in p and after[p] not in ("dir", "absent") for p in after),
          str(after))
    check_eq("K11 the manifest is untouched", after["manifest"], before["manifest"])
    check_eq("K11 the record stands where the reading says", got.get("record"),
             PBC.alternative_record_path(task_of(root), "test_strong", "TC-001", "ALT-1").relative_to(task_of(root)).as_posix())


def k12_unknown_answers(root: Path, stub: Path) -> None:
    put_entries(root, [ent("test_strong")])
    env = {"PROBE_STUB_LOG": str(root / "stub.log")}

    def unknown(label: str, **kw) -> None:
        before = snapshot(root)
        files = (root / STAMP_REL).read_bytes()
        proc, got = alt(root, stub, env=env, **kw)
        check_eq(f"K12 {label}: exit 1, an unknown ANSWER", (proc.returncode, got.get("verdict")), (1, "unknown"))
        check_eq(f"K12 {label}: work/ and the test are unchanged", (snapshot(root), (root / STAMP_REL).read_bytes()),
                 (before, files))
        check(f"K12 {label}: it says why", bool(got.get("why")), str(got))

    unknown("an undeclared ALT", token="TC-001:ALT-9")
    case1 = task_of(root) / "work" / "test-cases" / "TC-001.md"
    text = case1.read_text(encoding="utf-8")
    case1.write_text(case_text("TC-001", None), encoding="utf-8")
    unknown("a case without the key")
    case1.write_text(case_text("TC-001", "not json"), encoding="utf-8")
    unknown("a malformed key")
    case1.write_text(text, encoding="utf-8")
    case1.rename(case1.with_name("TC-001.md.gone"))
    unknown("the case file is absent")
    case1.with_name("TC-001.md.gone").rename(case1)
    case1.write_text(text.replace('"then": 2', '"then": 5'), encoding="utf-8")
    unknown("a Then that is not in the case")
    case1.write_text(text.replace(', "ref": "R-2"', ""), encoding="utf-8")
    unknown("t-768 B-2: an ALT with no `ref` (the report's `case_unreadable` too: ONE validity rule)")
    case1.write_text(case_text("TC-001", ALT[:-1] + ", " + ALT[1:]), encoding="utf-8")     # ALT-1 twice
    unknown("t-768 B-2: a duplicate ALT id")
    case1.write_text(text, encoding="utf-8")
    check_eq("K12 the stub never ran", stub_log_lines(root), 0)
    # no covered binding: the road refuses (a Refusal, exit 2) naming the way to list the checks, nothing written
    manifest = task_of(root) / "work" / "automation-manifest.json"
    data = json.loads(manifest.read_text(encoding="utf-8"))
    kept = list(data["then_bindings"])
    data["then_bindings"] = [r for r in kept if r["instance_id"] != "test_strong"]
    write_json(manifest, data)
    before = snapshot(root)
    proc, got = alt(root, stub, env=env)
    check_eq("K12 no covered binding: exit 2, refused, nothing written, the stub never ran",
             (proc.returncode, got.get("status"), snapshot(root), stub_log_lines(root)), (2, "refused", before, 0))
    check_in("K12 ... the refusal names Then 2 and the --plan door", "--plan", got.get("error", ""))
    data["then_bindings"] = kept
    write_json(manifest, data)


def k14_refusals(root: Path, stub: Path) -> None:
    env = {"PROBE_STUB_LOG": str(root / "stub.log")}
    original = stat_text(root)
    put_entries(root, [ent("test_strong")])

    def refused(label: str, *, want=None, **kw) -> None:
        before = snapshot(root)
        proc, got = alt(root, stub, env=env, **kw)
        check_eq(f"K14 {label}: exit 2, refused", (proc.returncode, got.get("status")), (2, "refused"))
        if want:
            check_in(f"K14 {label}: the text names the problem", want, got.get("error", ""))
        check_eq(f"K14 {label}: the tree is snapshot-equal and the stub never ran", (snapshot(root), stat_text(root),
                                                                                    stub_log_lines(root)), (before, original, 0))

    refused("a bare ALT-1 token", token="ALT-1", want="<case>:ALT-<n>")
    refused("a case the instance does not cover", token="TC-002:ALT-1", want="does not cover")
    refused("--oracle with alternative", extra=("--oracle", "x::y"), want="--oracle or --at")
    refused("--at with alternative", extra=("--at", "3"), want="--oracle or --at")
    refused("--supersede is removed (a changed entry runs again by itself)", extra=("--supersede", "why"), want="--supersede")
    refused("--supersede with an empty reason", extra=("--supersede", ""), want="--supersede")
    refused("--model without --alternative", token=None, want="belongs to --alternative")
    refused("--model of a file that is not there", model="absent.json", want="no model file")
    outside = temp_dir("qa-probe-alt-out-")
    (outside / "m.json").write_text(json.dumps({"models": [ent("test_strong")]}), encoding="utf-8")
    link = task_of(root) / "work" / "probe-models" / "link.json"
    try:
        os.symlink(outside / "m.json", link)
        refused("a symlink out of work/probe-models", model="link.json", want="not under")
    except (OSError, NotImplementedError):
        check("K14 symlink: not creatable on this machine (the resolve() check of the model loader is the same code path as the outside "
              "file, pinned by test_models_file_guards_are_the_alternatives)", True)
    cleanup(outside)
    # CLI misuse (K22): nothing read
    before = snapshot(root)
    proc, got = alt(root, stub, token=None, model=None, extra=("--supersede", "why"), env=env)
    check_eq("K22 --supersede without --alternative: exit 2, refused, nothing read or written", (proc.returncode, got.get("status"),
                                                                                              snapshot(root)), (2, "refused", before))


def k16_encoding(root: Path, stub: Path) -> None:
    env = {"PROBE_STUB_LOG": str(root / "stub.log")}
    path = task_of(root) / "work" / "probe-models" / "bom.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\xef\xbb\xbf" + json.dumps({"models": [ent("test_strong")]}).encode("utf-8"))
    proc, got = alt(root, stub, "test_strong", model="bom.json", env=env)
    check_eq("K16 a model file with a BOM is read and the reading proved", (proc.returncode, got.get("verdict")), (0, "intended_failure"))
    # the test file holds non-ASCII text BEFORE the edited line (`LABEL`): bytes and characters differ there, the edit still lands on the
    # check, the failure is at its own assert and the author's bytes are back
    check("K16 the test file is not ASCII (LABEL holds non-ASCII text above every check)", len(stat_text(root)) != len(stat_text(root).decode("utf-8")))
    check_eq("K16 ... and the reading is proved at the check's own assert", got.get("actual_location"), key_of("test_strong"))
    check_eq("K16 ... and the author's bytes are back", (root / STAMP_REL).read_bytes(), STAMP.encode("utf-8"))


def k18_author_unknown(root: Path, stub: Path) -> None:
    put_entries(root, [ent("test_strong")])
    bound = PBC.author_binding(task_of(root), "test_strong", C.load_json(task_of(root) / "work" / "run-blocks"
                                                                             / "20260924T090000000000Z-author1.json")
                               ["results"][1]["instance_content_sha"])
    check_eq("K18 author_binding returns the row's status", (bound or {}).get("status"), "passed")
    # a red author row -> the reading does not prove even though the model fails at the assert
    block = task_of(root) / "work" / "run-blocks" / "20260924T090000000000Z-author1.json"
    data = json.loads(block.read_text(encoding="utf-8"))
    for row in data["results"]:
        if row["instance_id"] == "test_strong":
            row["status"] = "failed"
    write_json(block, data)
    proc, got = alt(root, stub, "test_strong")
    check("K18 a red author row + a failing run: never intended_failure, never a receipt",
          got.get("verdict") != "intended_failure" and got.get("receipt") is None, str((proc.returncode, got.get("verdict"), got.get("why"))))
    check("K18 ... and the verdict is not a proof in the report either",
          row_of(report(root, stub), "test_strong").get("state") != "proven", "proven on a red author")
    block.unlink()
    proc, got = alt(root, stub, "test_strong")
    check("K18 no run block at all (the author's state unknown): never intended_failure",
          got.get("verdict") != "intended_failure" and got.get("receipt") is None, str((proc.returncode, got.get("verdict"), got.get("why"))))


def k19_repeat(root: Path, stub: Path) -> None:
    put_entries(root, [ent("test_strong")])
    env = {"PROBE_STUB_LOG": str(root / "stub.log")}
    proc, first = alt(root, stub, "test_strong", env=env)
    check_eq("K19 first probe", first.get("verdict"), "intended_failure")
    runs = stub_log_lines(root)
    proc, again = alt(root, stub, "test_strong", env=env)
    check_eq("K19 a second identical call: the same verdict and no new run (a proved check of the same entry and bytes is skipped)",
             (proc.returncode, again.get("verdict"), stub_log_lines(root)), (0, "intended_failure", runs))
    put_entries(root, [ent("test_strong", "161.5")])
    proc, third = alt(root, stub, "test_strong", env=env)
    check_eq("K19 a changed entry runs again by itself, no flag", (proc.returncode, third.get("verdict"), stub_log_lines(root)),
             (0, "intended_failure", runs + 1))
    check_eq("K19 ... under the new value", [c["entry"]["actual"] for c in third.get("checks") or []], ["161.5"])


def k20_report(root: Path, stub: Path) -> None:
    put_entries(root, [ent("test_strong")])
    alt(root, stub, "test_strong")
    put_entries(root, [ent("test_weak", WEAK)])
    alt(root, stub, "test_weak")
    put_entries(root, [{"alternative": TOKEN, "gap": "the stamp is read inside the product"}], "g.json")
    alt(root, stub, "test_both", model="g.json")
    rows = report(root, stub)
    strong, weak, both, never = (row_of(rows, i) for i in ("test_strong", "test_weak", "test_both", "test_untaken"))
    check_eq("K20 proven", strong.get("state"), "proven")
    check_eq("K20 not_separated (the weak oracle passes under the reading)", weak.get("state"), "not_separated")
    check_eq("K20 gap", both.get("state"), "gap")
    check_in("K20 the gap row says why", "inside the product", both.get("why", ""))
    check_eq("K20 unknown: declared, never probed", never.get("state"), "unknown")
    check_eq("K20 the unknown row carries the new flags to add",
             never.get("flags"), f"--alternative {TOKEN} [--model work/probe-models/<any name>.json]")
    check_in("K20 and the entry skeleton", '"check"', never.get("skeleton", ""))
    proc = run_script("probe_by_code.py", "--task", TASK, "--alternatives", cwd=root, env=env_for(root, stub))
    check_in("K20 the human line: <instance> <case>:<ALT> Then <n>: <state> - <why>", "test_strong TC-001:ALT-1 Then 2: proven",
             proc.stdout)
    # a case without the key -> no row; a malformed key -> case_unreadable
    case1 = task_of(root) / "work" / "test-cases" / "TC-001.md"
    case2 = task_of(root) / "work" / "test-cases" / "TC-002.md"
    case1.write_text(case_text("TC-001", None), encoding="utf-8")
    case2.write_text(case_text("TC-002", "not json"), encoding="utf-8")
    rows = report(root, stub)
    check("K20 a case without the key has no row", not [r for r in rows if r["case"] == "TC-001"], str(rows))
    check_eq("K20 a malformed key is case_unreadable (never 'nothing owed')",
             [r["state"] for r in rows if r["case"] == "TC-002"], ["case_unreadable"])
    case1.write_text(case_text("TC-001"), encoding="utf-8")
    case2.write_text(case_text("TC-002"), encoding="utf-8")


def k25_two_cases(root: Path, stub: Path) -> None:
    put_entries(root, [ent("test_both")])
    proc, got = alt(root, stub, "test_both")
    check_eq("K25 TC-001:ALT-1 of the two-case instance is proven", got.get("verdict"), "intended_failure")
    rows = report(root, stub)
    check_eq("K25 the unmodelled case's row is unknown", row_of(rows, "test_both", "TC-002:ALT-1").get("state"), "unknown")
    p1 = PBC.alternative_record_path(task_of(root), "test_both", "TC-001", "ALT-1")
    p2 = PBC.alternative_record_path(task_of(root), "test_both", "TC-002", "ALT-1")
    check("K25 the two records live at different paths", p1 != p2 and p1.is_file() and not p2.exists())
    p2.write_bytes(p1.read_bytes())
    rows = report(root, stub)
    check_eq("K25 a record copied over TC-002's path keeps its `case` field: unknown (names another case)",
             row_of(rows, "test_both", "TC-002:ALT-1").get("state"), "unknown")
    check_in("K25 ... and says so", "another case", row_of(rows, "test_both", "TC-002:ALT-1").get("why", ""))


def k26_stale(root: Path, stub: Path) -> None:
    put_entries(root, [ent("test_strong")])
    env = {"PROBE_STUB_LOG": str(root / "stub.log")}
    alt(root, stub, "test_strong", env=env)
    check_eq("K26 proven first", row_of(report(root, stub), "test_strong").get("state"), "proven")
    original = stat_text(root)
    # (a) the test function's bytes change (a weakened assert)
    (root / STAMP_REL).write_bytes(original.replace(b"T_DONE - TOLERANCE, \"Then 2: the stamp is the trigger",
                                                    b"T_DONE + TOLERANCE, \"Then 2: the stamp is the trigger", 1))
    check_eq("K26 (a) the test's bytes changed -> stale, never proven", row_of(report(root, stub), "test_strong").get("state"),
             "stale")
    (root / STAMP_REL).write_bytes(original)
    check_eq("K26 restored bytes -> proven again", row_of(report(root, stub), "test_strong").get("state"), "proven")
    # (b) the case's reading changes
    case1 = task_of(root) / "work" / "test-cases" / "TC-001.md"
    text = case1.read_text(encoding="utf-8")
    case1.write_text(text.replace("taken at completion", "taken at the end of the run"), encoding="utf-8")
    check_eq("K26 (b) the reading changed -> stale", row_of(report(root, stub), "test_strong").get("state"), "stale")
    case1.write_text(text, encoding="utf-8")
    # (c) the Then is rebound to another assert line
    manifest = task_of(root) / "work" / "automation-manifest.json"
    data = json.loads(manifest.read_text(encoding="utf-8"))
    saved = json.dumps(data)
    for row in data["then_bindings"]:
        if row["instance_id"] == "test_strong":
            row["assertion_ref"] = f"{STAMP_REL}:12"
    write_json(manifest, data)
    check_eq("K26 (c) the Then is rebound -> stale", row_of(report(root, stub), "test_strong").get("state"), "stale")
    manifest.write_text(saved, encoding="utf-8")
    # a stale record is not an answer: the call runs again; the author's green is for the OLD bytes, so it does not prove
    runs = stub_log_lines(root)
    (root / STAMP_REL).write_bytes(original.replace(b"T_DONE - TOLERANCE, \"Then 2: the stamp is the trigger",
                                                    b"T_DONE - TOLERANCE - 1.0, \"Then 2: the stamp is the trigger", 1))
    proc, got = alt(root, stub, "test_strong", env=env)
    check("K26 a stale record does not answer: the call walked again, and the author's green (for the OLD bytes) does not prove it",
          stub_log_lines(root) == runs + 1 and got.get("verdict") != "intended_failure",
          str((got.get("verdict"), got.get("why"), stub_log_lines(root), runs)))
    (root / STAMP_REL).write_bytes(original)
    # m-4: a gap goes stale too
    put_entries(root, [{"alternative": TOKEN, "gap": "cannot model it"}], "g.json")
    alt(root, stub, "test_untaken", model="g.json")
    check_eq("K26 a gap is a gap while the reading and the test stand", row_of(report(root, stub), "test_untaken").get("state"), "gap")
    case1.write_text(text.replace("taken at completion", "taken at some other time"), encoding="utf-8")
    check_eq("K26 m-4 a gap goes stale when the reading changes", row_of(report(root, stub), "test_untaken").get("state"), "stale")
    case1.write_text(text, encoding="utf-8")


def k27_helper_assert(root: Path, stub: Path) -> None:
    manifest = task_of(root) / "work" / "automation-manifest.json"
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["tests"].append(entry("test_helper"))
    data["then_bindings"].append({"case": "TC-001", "then": 2, "instance_id": "test_helper", "status": "covered",
                                  "assertion_ref": "tests/helpers.py:2"})
    write_json(manifest, data)
    put_entries(root, [ent("test_helper")])
    before = snapshot(root)
    proc, got = alt(root, stub, "test_helper", env={"PROBE_STUB_LOG": str(root / "stub.log")})
    check_eq("K27 the Then's binding lives in a helper file the test body holds no check of: refused, nothing written, nothing ran",
             (proc.returncode, got.get("status"), snapshot(root), stub_log_lines(root)), (2, "refused", before, 0))
    check_in("K27 the refusal names Then 2 and the way to list the checks", "Then 2", got.get("error", ""))
    check_in("K27 ... and the --plan door", "--plan", got.get("error", ""))


def k29_k30_exit_and_print(root: Path) -> None:
    """B-2: the exit and print paths read the alternative record without an exception, and an unverified restore of a HELPER
    target names the helper. `probe` is replaced by records, so the branch no stub run reaches is pinned too."""
    mark_project(root)
    use_project(root)
    argv = ["--task", TASK, "--dispatch", DISPATCH, "--test", f"{STAMP_REL}::test_strong", "--instance", "test_strong",
            "--alternative", TOKEN, "--model", "work/probe-models/m.json"]
    full = {"instance_id": "test_strong", "alternative": TOKEN, "verdict": "intended_failure", "why": "",
            "expected_location": f"{STAMP_REL}:20", "expected_reason": "alternative TC-001:ALT-1",
            "actual_location": f"{STAMP_REL}:20", "actual_reason": "AssertionError: m", "record": "work/probes/alternative/x.json",
            "evidence_ref": "evidence/e.json", "restore": {"verified": True}, "notes": ["n1"],
            "test_node": f"{STAMP_REL}::test_strong", "test_file_sha256": "f" * 64,
            "mutated_file": {"path": STAMP_REL, "sha256": "a" * 64}}
    answers = {"unknown": {"verdict": "unknown", "instance_id": "test_strong", "alternative": TOKEN, "why": "a why",
                           "notes": []},
               "gap": {"verdict": "gap", "instance_id": "test_strong", "alternative": TOKEN, "why": "a gap",
                       "record": "work/probes/alternative/x.json", "door": "red_sandbox.py --probe", "notes": ["n"],
                       "restore": None},
               "intended_failure": full}
    wanted = {"unknown": 1, "gap": 1, "intended_failure": 0}
    for name, record in answers.items():
        for extra in ((), ("--json",)):
            code, log = _main_in_process(argv + list(extra), dict(record, notes=list(record.get("notes") or [])))
            out, err = _streams(log)
            check_eq(f"K30 {name} {'--json' if extra else 'text'}: exit {wanted[name]}, prints, no exception, never published",
                     (code, bool(out.strip()), "Traceback" in err, "publish" in _calls(log)),
                     (wanted[name], True, False, False))
    # K29: an unverified restore with a helper target prints the helper's path and exits 1 with no traceback
    helper = dict(full, restore={"verified": False, "copy": "qa-factory/state/probe-copies/k.orig"},
                  mutated_file={"path": "tests/helpers.py", "sha256": "b" * 64})
    code, log = _main_in_process(argv, helper)
    out, err = _streams(log)
    check_eq("K29 an unverified restore of a helper target: exit 1, the HELPER is named, not the test",
             (code, "tests/helpers.py" in err, "Traceback" in err, "publish" in _calls(log)), (1, True, False, False))
    check_in("K29 the undo names the copy over the helper", "tests", err.split("stop and")[-1] if "stop and" in err else err)


def k31_lost_on_purpose(root: Path, stub: Path) -> None:
    """LOST ON PURPOSE (the spec's Reuse paragraph of t-2064 P5): the old road's value-equivalence rule refused a model that changes the code
    but not the value (`x + 0`, `* 1`, `+x`) as `unknown`; the one road compares TEXT, so on Python such an entry runs, passes, and reads
    `no_failure` with the entry beside it - the critic sees it. The direction is not toward proof: it never reads `intended_failure`."""
    env = {"PROBE_STUB_LOG": str(root / "stub.log")}
    runs = 0
    for actual in ("stamp + 0", "(stamp) * 1", "+stamp"):
        put_entries(root, [ent("test_strong", actual)])
        proc, got = alt(root, stub, "test_strong", env=env)
        runs += 1
        check_eq(f"K31 {actual!r}: exit 0, no_failure beside the entry (NOT `unknown`, as the old road said; never a proof)",
                 (proc.returncode, got.get("verdict"), stub_log_lines(root)), (0, "no_failure", runs))
        check_eq(f"K31 {actual!r}: the entry is on the record", [c["entry"]["actual"] for c in got.get("checks") or []], [actual])
        check_eq(f"K31 {actual!r}: the report does not read it as proven", row_of(report(root, stub), "test_strong").get("state"),
                 "not_separated")


def k23_record_path() -> None:
    task = Path("T")
    check_eq("K23 kind alternative", PL.probe_record_path(task, "i--TC-1--ALT-1", kind="alternative"),
             task / "work" / "probes" / "alternative" / "i--TC-1--ALT-1.json")
    check_eq("K23 kind product unchanged", PL.probe_record_path(task, "i", kind="product"), task / "work" / "probes" / "product" / "i.json")
    check_eq("K23 kind empty unchanged", PL.probe_record_path(task, "i"), task / "work" / "probes" / "i.json")
    check_eq("K23 a qualified case is one file name", PBC.alternative_record_path(task, "i", "feedback-api/TC-3", "ALT-1").name,
             "i--feedback-api-TC-3--ALT-1.json")


def main() -> None:
    k23_record_path()
    for body in (k10_the_pair, k11_no_live_receipt, k12_unknown_answers, k14_refusals, k16_encoding, k18_author_unknown,
                 k19_repeat, k20_report, k25_two_cases, k26_stale, k27_helper_assert, k31_lost_on_purpose):
        with_stub(body)
    root = alt_project()
    try:
        k29_k30_exit_and_print(root)
    finally:
        cleanup(root)
        cleanup_beside(root)
    finish("test_probe_by_code_alternative")


if __name__ == "__main__":
    main()
