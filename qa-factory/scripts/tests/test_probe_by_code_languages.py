"""probe_by_code.py: the live probe of a test in ANY language (B-373 part c, D-0028).

A temp project per language (C# xUnit/TRX, Java JUnit5/AssertJ/surefire, TypeScript Jest/jest-junit) and a
stand-in runner (`PROBE_RUN_SUITE`) that reads the bytes on disk, fails the bound row ONLY when the declared
line holds the inverted statement, and writes a TRX, surefire or jest-junit report with a sample message and
stack - so every verdict below comes from the mutated bytes really running, not from a canned answer. The
messages and stacks are ESTIMATES (measurement M2/M3 captures real ones); what is pinned is the tool's reading
of them: the one inverted form at the one position, the verdict table (R8), the refusals before the first
write (R6, E3-E12, E14, E21, E22), the data-gap refusals (K3, K4), the receipt and the window (K1a), and that a
factory error is `incomplete` and never a verdict on the test (E15, E26).

Runner modes (the `mode` key of LANG_STUB): normal, pass_anyway, no_frames, lib_frames_first, wrong_line,
error_row, drifted_message, no_row, two_rows, skipped_row, kill_holding_lock.
"""
import copy
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness import (FIXTURES, SCRIPTS, check, check_eq, check_in, check_not_in, cleanup, finish, run_script,  # noqa: E402
                     temp_dir)

import acceptance  # noqa: E402
import probe_entries as PE  # noqa: E402
import assertion_detectors as AD  # noqa: E402
import contract as C  # noqa: E402
import probe_by_code as PBC  # noqa: E402
import proof_level as PL  # noqa: E402
from test_probe_by_code import (DISPATCH, OBLIGATION_REFS, PROVENANCE, TASK, cleanup_beside, env_for,  # noqa: E402
                                model_entries, mutated_line, read_check_record, seed_author_job, write_json)
from test_probe_by_code import tree_state as _tree_state  # noqa: E402

PY = sys.executable
FIX = FIXTURES / "probe-languages"
OLD_NS = 1_600_000_000 * 10 ** 9  # 2020: far from "now", so a mtime rule shows

# --- the stand-in runner -------------------------------------------------------------------------------

LANG_RUN_SUITE = r'''
"""A stand-in for `run_suite.py --request FILE` for a test that is not Python."""
import hashlib
import json
import os
import signal
import sys
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

request = json.loads(Path(sys.argv[sys.argv.index("--request") + 1]).read_text(encoding="utf-8"))
cfg = json.loads(os.environ["LANG_STUB"])
mode = cfg.get("mode", "normal")
if os.environ.get("PROBE_STUB_LOG"):
    with open(os.environ["PROBE_STUB_LOG"], "a", encoding="utf-8") as log:
        log.write(sys.argv[-1] + "\n")
if mode == "kill_holding_lock":
    os.kill(os.getppid(), signal.SIGTERM)  # the role's shell call is killed: no `finally` ever runs
    sys.exit(3)
if request.get("purpose") != "red_probe":
    print(json.dumps({"status": "stub_refused", "error": "purpose must be red_probe"}))
    sys.exit(2)
cwd = Path(request["command"]["cwd"]).resolve()
project = Path(os.environ.get("CLAUDE_PROJECT_DIR") or cwd).resolve()
test_path = (project / cfg["file"]).resolve()
raw = test_path.read_bytes()
lines = raw.decode("utf-8-sig").splitlines()
hit = cfg.get("hit", cfg["after"]) in lines[cfg["line"] - 1]   # t-1968 N1: a marked statement is not `after` byte for byte
# t-2064 P4b: a walk runs EVERY check of the body, one inverted at a time; `also` lists the other checks of the fixture ([line, after]): the
# row fails when any of them holds its inverted statement, so each check of the plan meets the failure the first one always met
hit = hit or any(n <= len(lines) and a in lines[n - 1] for n, a in cfg.get("also", []))
status = "failed" if hit else "passed"
if mode == "pass_anyway":
    status = "passed"
if mode == "error_row" and hit:
    status = "error"
if mode == "skipped_row":
    status = "skipped"
site_line = cfg["line"] + (3 if mode == "wrong_line" else 0)
stack = cfg["lib"] + cfg["stack"] if mode == "lib_frames_first" else ([] if mode == "no_frames" else cfg["stack"])
stack = [s.replace("{path}", test_path.as_posix()).replace("{line}", str(site_line)) for s in stack]
message = cfg["drift"] if mode == "drifted_message" else cfg["message"]
# t-2064 N3b: the runner prints the token the way the mutated check would (the marker is joined at run time, so it is in the
# message and in no echo of the source): read from the bytes this stub was handed. `drifted_message` and `wrong_line` print none -
# the failure text a library wrote, which only the code critic judges
import re
found = re.search(r"qa-probe[\"',\s]+([0-9a-f]{12})", raw.decode("utf-8-sig"))
if found and mode not in ("drifted_message", "wrong_line"):
    message = "qa-probe-" + found.group(1) + " " + message
ids = [cfg["report_id"]]
if mode == "no_row":
    ids = ["Some.Other.Test"]
if mode == "two_rows":
    ids = ids * 2


def trx_row(test_id):
    outcome = {"passed": "Passed", "failed": "Failed", "error": "Error", "skipped": "NotExecuted"}[status]
    info = ""
    if status in ("failed", "error", "skipped"):
        info = ("<Output><ErrorInfo><Message>" + escape(message) + "</Message><StackTrace>" + escape("\n".join(stack))
                + "</StackTrace></ErrorInfo></Output>")
    return f'<UnitTestResult testName={quoteattr(test_id)} outcome="{outcome}" testId="g-1">{info}</UnitTestResult>'


def junit_row(test_id):
    classname, _, name = test_id.partition("::")
    body = ""
    if status == "failed":
        body = (f"<failure message={quoteattr(message)} type={quoteattr(cfg.get('type', 'Error'))}>"
                + escape(cfg.get("text_prefix", "").replace("{message}", message) + "\n".join(stack)) + "</failure>")
    elif status == "error":
        body = f"<error message={quoteattr(message)} type=\"RuntimeError\">{escape(chr(10).join(stack))}</error>"
    elif status == "skipped":
        body = "<skipped message=\"not run\"/>"
    return f"<testcase classname={quoteattr(classname)} name={quoteattr(name)}>{body}</testcase>"


reporter = cfg["reporter"]
if reporter == "trx":
    xml = ('<TestRun xmlns="http://microsoft.com/schemas/VisualStudio/TeamTest/2010"><Results>'
           + "".join(trx_row(i) for i in ids) + "</Results><TestDefinitions><UnitTest id=\"g-1\"><TestMethod "
           + f'className={quoteattr(cfg["report_id"].rpartition(".")[0])} name={quoteattr(cfg["report_id"].rpartition(".")[2])}/>'
           + "</UnitTest></TestDefinitions></TestRun>")
else:
    xml = "<testsuites><testsuite name=\"s\">" + "".join(junit_row(i) for i in ids) + "</testsuite></testsuites>"
job = hashlib.sha256(request["idempotency_key"].encode()).hexdigest()[:20]
task_root = project / "qa-factory" / "artifacts" / request["task"]
run_dir = task_root / "evidence" / "runs" / job
run_dir.mkdir(parents=True, exist_ok=True)
report = run_dir / ("report.trx" if reporter == "trx" else "report.junit.xml")
report.write_text(xml, encoding="utf-8")
label = f"red_probe-{job}"
summary_path = run_dir / f"{label}.json"
summary = {"task": request["task"], "label": label, "exit_code": 0 if status == "passed" else 1,
           "execution_status": status, "purpose": "red_probe", "reporter": reporter,
           "summary_path": summary_path.relative_to(project).as_posix(),
           "report_evidence": {"path": report.relative_to(task_root).as_posix(),
                               "sha256": hashlib.sha256(report.read_bytes()).hexdigest()},
           "stub_seen_sha256": hashlib.sha256(raw).hexdigest(), "stub_seen_prefix": raw[:3].hex(), "stub_seen_text": raw.decode("utf-8-sig"),
           "stub_seen_crlf": raw.count(b"\r\n"), "stub_hit": hit,
           "stub_selected": request.get("selected_instance_ids"),
           "stub_argv": request["command"].get("argv"), "stub_selector_args": request["command"].get("selector_args")}
summary_path.write_text(json.dumps(summary, indent=1), encoding="utf-8")
print(json.dumps(summary))
sys.exit(summary["exit_code"])
'''

# --- the languages ---------------------------------------------------------------------------------------

LANGS = {
    "csharp": dict(
        marker=False,     # xunit `Assert.Equal` takes no message: no token, so the critic judges (N3b)
        fixture="CalcTests.cs", file="tests/CalcTests.cs", root_test="tests", iid="Adds", test="CalcTests.Adds",
        selector="CalcTests.Adds", selector_args=["--filter", "FullyQualifiedName~CalcTests.Adds"],
        report_id="Acme.Tests.CalcTests.Adds", reporter="trx",
        argv=["dotnet", "test", "--logger", "trx;LogFileName={report_path}"],
        first="            Assert.Equal(4, Calc.Add(2, 2));", after="Assert.NotEqual(4, Calc.Add(2, 2));",
        # t-2064 P4b: the fixture's body has a SECOND check, one line below (the walk runs it): (lines below the first, its inverted text, takes a
        # marker). `Assert.True(cond)` takes a message in xunit, so the factory's token rides on it where `Assert.Equal` of the first takes none
        also=[(1, "Assert.False(note.Length > 0", True)],
        message="Assert.NotEqual() Failure: Values are equal\nExpected: Not 4\nActual:   4",
        drift="Assert.NotEqual() has failed: the values were equal", type="Xunit.Sdk.NotEqualException",
        text_prefix="",
        stack=["   at Acme.Tests.CalcTests.Adds() in {path}:line {line}"],
        lib=["   at Xunit.Assert.NotEqual[T](T expected, T actual) in /_/src/xunit.assert/Asserts/EqualityAsserts.cs:line 372",
             "   at System.RuntimeMethodHandle.InvokeMethod(Object target, Signature sig)"]),
    "java": dict(
        marker=True,      # JUnit `assertEquals(.., message)` takes one (M-J5): the stub reads the token from the mutated bytes
        fixture="CalcTest.java", file="src/test/java/com/acme/CalcTest.java", root_test="src/test", iid="adds",
        test="CalcTest.adds", selector="CalcTest#adds", selector_args=["-Dtest=CalcTest#adds"],
        report_id="com.acme.CalcTest::adds()", reporter="junit-xml",
        argv=["mvn", "-q", "test", "-Dsurefire.reportsFile={report_path}"],
        first="        assertEquals(4, Calc.add(2, 2));", after="assertNotEquals(4, Calc.add(2, 2));",
        hit="assertNotEquals(4, Calc.add(2, 2)",    # the real run carries the factory's message marker after the last argument (N1)
        message="expected: not equal but was: <4>", drift="the values should have been different",
        type="org.opentest4j.AssertionFailedError", text_prefix="org.opentest4j.AssertionFailedError: {message}\n",
        stack=["\tat com.acme.CalcTest.adds(CalcTest.java:{line})",
               "\tat java.base/java.lang.reflect.Method.invoke(Method.java:568)"],
        lib=["\tat org.junit.jupiter.api.AssertionUtils.fail(AssertionUtils.java:55)",
             "\tat org.junit.jupiter.api.AssertNotEquals.failEqual(AssertNotEquals.java:179)"]),
    "typescript": dict(
        marker=False,     # jest `expect(..).toBe` outside @playwright/test takes none (M-TS2 has a `source` condition)
        fixture="sum.test.ts", file="src/sum.test.ts", root_test="src", iid="adds", test="adds",
        selector="adds", selector_args=["src/sum.test.ts", "-t", "adds"],
        report_id="calc adds::calc adds", reporter="junit-xml",
        argv=["npx", "jest", "--ci", "--outputFile={report_path}"],
        first="    expect(sum(1, 2)).toBe(3);", after="expect(sum(1, 2)).not.toBe(3);",
        message="expect(received).not.toBe(expected) // Object.is equality\n\nExpected: not 3\nReceived: 3",
        drift="the received value was 3, which must not be", type="Error", text_prefix="Error: {message}\n\n",
        stack=["      at Object.<anonymous> ({path}:{line}:20)",
               "      at Promise.then.completed (/x/node_modules/jest-circus/build/utils.js:298:28)",
               "      at new Promise (<anonymous>)"],
        lib=["      at Object.toBe (/x/node_modules/expect/build/index.js:1:1)",
             "      at node:internal/process/task_queues:95:5"]),
}


def first_line(lang: str, data: bytes = None) -> int:
    """The 1-based line of the fixture's first assertion (found, not typed: the fixture may be edited)."""
    spec = LANGS[lang]
    text = (data if data is not None else (FIX / spec["fixture"]).read_bytes()).decode("utf-8-sig")
    return text.splitlines().index(spec["first"]) + 1


def stub_cfg(lang: str, mode: str = "normal", **over) -> dict:
    spec = LANGS[lang]
    cfg = {key: spec[key] for key in ("file", "after", "message", "drift", "type", "text_prefix", "stack", "lib",
                                      "reporter", "report_id", "hit") if key in spec}
    cfg.update(mode=mode, line=first_line(lang))
    cfg["also"] = [[cfg["line"] + offset, text] for offset, text, _marker in spec.get("also", [])]
    cfg.update(over)
    return cfg


def check_lines(lang: str) -> list:
    """The 1-based lines of the fixture body's checks, in the order the plan walks them (t-2064 P4b: every check, not the first only)."""
    first = first_line(lang)
    return [first] + [first + offset for offset, _text, _marker in LANGS[lang].get("also", [])]


def check_markers(lang: str) -> list:
    """Per check of `check_lines`: does its form take the factory's message marker (the fixture's, never read back from a record)?"""
    return [LANGS[lang]["marker"]] + [marker for _offset, _text, marker in LANGS[lang].get("also", [])]


def lang_project(lang: str, *, data: bytes = None, argv=None, verified: bool = True, extra_entries=(),
                 protected=None, files: dict = None, entry_extra: dict = None, mtime_ns=None) -> Path:
    """A project whose manifest names ONE test of `lang` (instance `spec["iid"]`, case TC-100), bound to the raw
    sha256 of its file as manifest_from_tests.py binds every row, with the author's green run block."""
    spec = LANGS[lang]
    root = temp_dir("qa-probe-lang-")
    target = root / spec["file"]
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data if data is not None else (FIX / spec["fixture"]).read_bytes())
    if mtime_ns is not None:
        os.utime(target, ns=(mtime_ns, mtime_ns))
    for name, content in (files or {}).items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_bytes(content)
    probe_script = root.parent / (root.name + "-runtime-probe.py")
    probe_script.write_text("import json\nprint(json.dumps(" + repr(PROVENANCE) + "))\n", encoding="utf-8")
    config = {
        "tests_root": spec["root_test"], "app_root": ".",
        "profiles": [{"profile_id": "unit", "selected": True, "roots": {"test": spec["root_test"]},
                      "commands": {"one_test": {"argv": list(argv or spec["argv"]), "cwd": "."}},
                      "reporter": {"kind": spec["reporter"]}, "selectors": {"verified": verified}}],
        "execution": {"runtime_probes": {"unit": {"argv": [PY, str(probe_script)], "cwd": ".", "timeout_s": 20}}}}
    if protected is not None:
        config["protected_app_paths"] = protected
    write_json(root / "qa-factory" / "config.json", config)
    task_root = root / "qa-factory" / "artifacts" / TASK
    write_json(task_root / "pipeline.json", {"stages": {"S5": {"status": "running"}},
                                             "first_test_run_at": "2026-09-24T09:00:00+00:00"})
    ids = ["TC-100"] + [e["case"] for e in extra_entries]
    write_json(task_root / "state" / "controller.json", {
        "schema_version": "2", "revision": "1", "source_revision": "source-1",
        "dispatches": {DISPATCH: {"id": DISPATCH, "stage": "S5", "role": "qa-code-critic", "status": "running",
                                  "scope": ids, "budget": {"requests": 50}}}})
    bound = {"test_content_sha": PBC.sha256(target.read_bytes())}
    entry = {"case": "TC-100", "covers": ["TC-100"], "file": spec["file"], "test": spec["test"],
             "instance_id": spec["iid"], "selector": spec["selector"], "selector_args": list(spec["selector_args"]),
             "report_test_id": spec["report_id"], "case_version_links": [{"case_id": "TC-100", "version": "cv_1"}],
             "obligation_refs": OBLIGATION_REFS, "trace_binding": bound, "obligation_ids": ["OB-ADD-1"],
             "defect_location": "calc:2", "assertion_id": "add_returns_sum"}
    entry.update(entry_extra or {})
    write_json(task_root / "work" / "automation-manifest.json", {"tests": [entry]})
    seed_author_job(root)  # the author's run of THIS test; rows that would make that refuse come after it
    write_json(task_root / "work" / "automation-manifest.json", {"tests": [entry] + list(extra_entries)})
    block = {"schema_version": 2, "dispatch_id": "S5-qa-automator-1", "purpose": "initial",
             "results": [{"instance_id": spec["iid"], "status": "passed",
                          "source_fingerprint": {"source_sha": "source-1", "test_content_sha": "author-tcs-1"}}],
             "runtime_provenance": {"observed_runtime_identity": "build-1", "environment_id": "env-1"}}
    write_json(task_root / "work" / "run-blocks" / "20260924T090000000000Z-author1.json", block)
    return root


def write_entries(root: Path, keys: list) -> None:
    """The window's model file with one `invert` entry per key, written only when its bytes differ (a refusal test takes its tree
    snapshot AFTER calling this, and a rewrite of the same bytes would move the mtime the snapshot compares)."""
    path = root / "qa-factory" / "artifacts" / TASK / "work" / "probe-models" / f"{DISPATCH}.json"
    wanted = json.dumps({"models": [{"check": key, "invert": PE.DEFAULT_REASON} for key in keys]})
    if not path.is_file() or path.read_text(encoding="utf-8") != wanted:
        PE.write_invert_entries(root / "qa-factory" / "artifacts" / TASK, DISPATCH, keys=list(keys))


def lrun(root: Path, stub: Path, node: str, instance: str, cfg: dict, *args, **env):
    """The CLI, as a role runs it: (process, parsed JSON of stdout or {}). t-2064 P4b: a call with no `--at` and no `--oracle` walks every
    check and needs a model entry per check, so the window's model file is written first (`model_entries`). `--at <line>` is a plan of the
    one selected row on the same road and needs the entry of THAT key (`<file of the node>:<line>`, written by hand: `--plan` need not list
    it, a line of an ambiguous declaration is not on the plan); `--oracle` needs the keys of the helper's checks, which the section that
    passes it writes (none here)."""
    if "--oracle" not in args:
        if "--at" in args:
            at = str(args[args.index("--at") + 1])
            write_entries(root, [at if ":" in at else f"{node.split('::')[0]}:{at}"])
        else:
            model_entries(root, stub, node, instance)
    proc = run_script("probe_by_code.py", "--task", TASK, "--dispatch", DISPATCH, "--test", node, "--instance", instance,
                      "--json", *args, cwd=root,
                      env=env_for(root, stub, LANG_STUB=json.dumps(cfg), PROBE_SCRIPTS_DIR=str(SCRIPTS), **env))
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    try:
        payload = json.loads("\n".join(lines)) if lines and lines[0].startswith("{") else {}
    except ValueError:
        payload = {}
    return proc, payload


def tree_state(root: Path) -> dict:
    """Every file under the project with its bytes' sha256 and mtime, but for the lock files of
    `qa-factory/state/probe-copies/`: a lock is taken BEFORE the test is first read and is never deleted (the
    `event_store.lock` convention, B-373 a), so a refusal that comes after it leaves an empty lock file - not a
    change of anything the author or the story owns, which is what a refusal must leave alone."""
    return {k: v for k, v in _tree_state(root).items()
            if not (k.startswith("qa-factory/state/probe-copies/") and k.endswith(".lock")) and not _tool_refusal_file(root, k)}


def tree_state_with_entries(root: Path, stub: Path, node: str, instance: str) -> dict:
    """`tree_state` taken AFTER the window's model file is written (TR2-14): `lrun` writes that file before the call, which is world and not
    the probe's work (same bytes, `model_entries`), so a snapshot taken before it would report the file as a change the refusal made."""
    model_entries(root, stub, node, instance)
    return tree_state(root)


def refusal_record_of(root: Path, instance: str) -> tuple:
    """(`refused`, `verdict`) of the instance's record on disk, or (None, None): the positive half of "the tree is unchanged" for a refusal of
    the TOOL, which `tree_state` leaves out (TR2-14)."""
    path = task_of(root) / "work" / "probes" / f"{instance}.json"
    try:
        body = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return (None, None)
    return (body.get("refused"), body.get("verdict"))


def _tool_refusal_file(root: Path, rel: str) -> bool:
    """Is `rel` the record `refused: tool` that a refusal of the TOOL leaves (EP1-36)? It is the one file a refusal may add; a
    test that says "the tree is unchanged" means the author's file, the copies and the story's other files. Those records have
    their own tests (`tool_refusal_record`)."""
    if "/work/probes/" not in rel or not rel.endswith(".json"):
        return False
    try:
        return json.loads((root / rel).read_text(encoding="utf-8")).get("refused") == "tool"
    except (OSError, ValueError, AttributeError):
        return False


def task_of(root: Path) -> Path:
    return root / "qa-factory" / "artifacts" / TASK


def node_of(lang: str) -> str:
    return f"{LANGS[lang]['file']}::{LANGS[lang]['test']}"


def refused(label: str, proc, payload, *needles: str) -> str:
    check_eq(f"{label}: exit 2, refused", (proc.returncode, payload.get("status")), (2, "refused"))
    text = payload.get("error", "")
    for needle in needles:
        check_in(f"{label}: says {needle!r}", needle, text)
    check_in(f"{label}: and that nothing was changed", "Nothing was changed", text)
    return text


def copies_left(root: Path) -> list:
    folder = root / "qa-factory" / "state" / "probe-copies"
    return sorted(p.name for p in folder.glob("*") if p.suffix != ".lock") if folder.is_dir() else []


def window_gaps(root: Path, record: dict, iid: str) -> list:
    """The record's `window_probe` dropped into a schema-2 window instance: the gaps `validate_window` finds."""
    item = {"schema_version": 2, "instance_id": iid, "input_hash": record["input_hash"], "outcome": "passed",
            "execution_fingerprint": "fp-1", "review": {"verdict": "approved", "input_hash": record["input_hash"]},
            "obligation_ids": record["obligation_ids"], "obligation_refs": OBLIGATION_REFS,
            "obligation_hash": record["obligation_hash"], "assertion_id": record["assertion_id"],
            "defect_location": record["defect_location"], "change_disposition": "new_or_changed",
            "change_basis_ref": "manifest:TC-100", "probe": record["window_probe"], "evidence_refs": record["evidence_refs"]}
    window = {"schema_version": 2, "input_hash": "window-1", "required_quality_checks": [], "quality_receipts": [],
              "instances": [item]}
    return acceptance.validate_window(window, task_of(root))


# --- the plan, unit level: every pair at its position (the seed table, E3-E9) -------------------------------

WRAP = {
    "csharp": ("using Xunit;\n\nnamespace Acme\n{\n    public class T\n    {\n        [Fact]\n        public void Adds()\n        {\n"
               "            {stmt}\n        }\n    }\n}\n", "t/T.cs::T.Adds"),
    "java": ("package com.acme;\n\nclass CalcTest {\n    @Test\n    void adds() {\n        {stmt}\n    }\n}\n",
             "t/CalcTest.java::CalcTest.adds"),
    "typescript": ("describe('c', () => {\n  test('adds', () => {\n    {stmt}\n  });\n});\n", "t/x.test.ts::adds"),
}

# (language, pair id, statement, the statement after the inversion)
SEED_PLANS = [
    ("csharp", "X1", "Assert.Equal(4, x);", "Assert.NotEqual(4, x);"),
    ("csharp", "X2", "Assert.NotEqual(4, x);", "Assert.Equal(4, x);"),
    ("csharp", "X3", "Assert.True(x > 0);", "Assert.False(x > 0);"),
    ("csharp", "X4", "Assert.False(x);", "Assert.True(x);"),
    ("csharp", "X5", "Assert.Null(x);", "Assert.NotNull(x);"),
    ("csharp", "X6", "Assert.NotNull(x);", "Assert.Null(x);"),
    ("csharp", "X7", "Assert.Empty(xs);", "Assert.NotEmpty(xs);"),
    ("csharp", "X8", "Assert.NotEmpty(xs);", "Assert.Empty(xs);"),
    ("csharp", "X9", 'Assert.Contains("a", xs);', 'Assert.DoesNotContain("a", xs);'),
    ("csharp", "X10", 'Assert.DoesNotContain("a", xs);', 'Assert.Contains("a", xs);'),
    ("csharp", "X1", "Assert.Equal<int>(4, x);", "Assert.NotEqual<int>(4, x);"),
    ("csharp", "N1", "Assert.That(x, Is.EqualTo(3));", "Assert.That(x, Is.Not.EqualTo(3));"),
    ("csharp", "N2", "Assert.That(x, Is.Not.EqualTo(3));", "Assert.That(x, Is.EqualTo(3));"),
    ("csharp", "N1", 'Assert.That(Foo(1, "a,b"), Is.EqualTo(3));', 'Assert.That(Foo(1, "a,b"), Is.Not.EqualTo(3));'),
    ("csharp", "N3", "ClassicAssert.AreEqual(3, x);", "ClassicAssert.AreNotEqual(3, x);"),
    ("csharp", "N4", "Assert.AreNotEqual(3, x);", "Assert.AreEqual(3, x);"),
    ("java", "J1", "assertEquals(4, x);", "assertNotEquals(4, x);"),
    ("java", "J1", "Assertions.assertEquals(4, x);", "Assertions.assertNotEquals(4, x);"),
    ("java", "J2", "assertNotEquals(4, x);", "assertEquals(4, x);"),
    ("java", "J3", "assertTrue(x > 0);", "assertFalse(x > 0);"),
    ("java", "J4", "Assert.assertFalse(x);", "Assert.assertTrue(x);"),
    ("java", "J5", "assertNull(x);", "assertNotNull(x);"),
    ("java", "J6", "assertNotNull(x);", "assertNull(x);"),
    ("java", "A1", "assertThat(x).isEqualTo(3);", "assertThat(x).isNotEqualTo(3);"),
    ("java", "A1", 'assertThat(x).as("sum").isEqualTo(3);', 'assertThat(x).as("sum").isNotEqualTo(3);'),
    ("java", "A1", 'assertThat(f(a, (b))).describedAs("s(%s)", y).isEqualTo(3);',
     'assertThat(f(a, (b))).describedAs("s(%s)", y).isNotEqualTo(3);'),
    ("java", "A2", "assertThat(x).isNotEqualTo(3);", "assertThat(x).isEqualTo(3);"),
    ("java", "A3", "assertThat(b).isTrue();", "assertThat(b).isFalse();"),
    ("java", "A4", "assertThat(b).isFalse();", "assertThat(b).isTrue();"),
    ("java", "A5", "assertThat(o).isNull();", "assertThat(o).isNotNull();"),
    ("java", "A6", "assertThat(o).isNotNull();", "assertThat(o).isNull();"),
    ("java", "A7", 'assertThat(xs).contains("a");', 'assertThat(xs).doesNotContain("a");'),
    ("java", "A8", 'assertThat(xs).doesNotContain("a");', 'assertThat(xs).contains("a");'),
    ("typescript", "T1", "expect(x).not.toBe(3);", "expect(x).toBe(3);"),
    ("typescript", "T1", "await expect(p).resolves.not.toBe(3);", "await expect(p).resolves.toBe(3);"),
    ("typescript", "T2", "expect(x).toBe(3);", "expect(x).not.toBe(3);"),
    ("typescript", "T2", "expect.soft(x).toBe(3);", "expect.soft(x).not.toBe(3);"),
    ("typescript", "T2", "await expect(p).rejects.toThrow('x');", "await expect(p).rejects.not.toThrow('x');"),
    ("typescript", "T2", "expect(x).toBe(3)", "expect(x).not.toBe(3)"),
]


def plan(lang: str, text, *, at=None, node: str = None, oracle: str = "", instance: str = "IID", entry=None):
    """`plan_detector_mutation` over `text` (str or bytes) as the language `lang` reads `node`: (mutated str, detail, context)."""
    spec = PBC.parse_node(node or WRAP[lang][1])
    if entry is not None:
        spec["entry"] = entry
    data = text if isinstance(text, bytes) else text.encode("utf-8")
    mutated, detail, context = PBC.plan_detector_mutation(data, spec, instance, at, oracle, "", "t/file")
    return mutated, detail, context


def refusal_of(fn) -> str:
    try:
        fn()
    except PBC.Refusal as exc:
        return str(exc)
    return ""


def seed_table_plans() -> None:
    """Every pair of the seed table is applied at its position, on its own shape, and only there."""
    covered = set()
    for lang, pair_id, stmt, after in SEED_PLANS:
        source = WRAP[lang][0].replace("{stmt}", stmt)
        mutated, detail, _ctx = plan(lang, source)
        label = f"{lang} {pair_id}: {stmt}"
        # the statement starts at the HEAD: a leading `await` is outside it (and untouched)
        check_eq(f"{label}: the inverted statement", detail["statement_after"], after.replace("await ", "", 1) if stmt.startswith("await ") else after)
        check_eq(f"{label}: the pair of the table (by its id)", detail["pair_id"], pair_id)
        check_eq(f"{label}: only that statement changed", mutated.decode("utf-8").replace(after, stmt, 1), source)
        check_eq(f"{label}: the same number of lines", mutated.count(b"\n"), source.count("\n"))
        check_eq(f"{label}: style, language and the invert mutation", (detail["style"], detail["language"], detail["mutation"]),
                 ("detector", lang, "invert"))
        check_in(f"{label}: the marker carries the instance, the statement and the fires_as", "probe-IID invert: " + stmt.replace("await ", "", 1)[:20],
                 detail["marker"])
        check_in(f"{label}: ...and `fires as /`", " fires as /", detail["marker"])
        check_eq(f"{label}: the fires_as of the record is the pair's own",
                 detail["fires_as"], next(p["fires_as"] for _l, e in AD.assertion_detectors().items() for f in e["assertions"]
                                          for p in (f["invert"] or []) if p.get("id") == pair_id))
        covered.add(pair_id)
    every = {p["id"] for e in AD.assertion_detectors().values() for f in e["assertions"] for p in (f["invert"] or [])}
    check_eq("every pair of the table has a plan above", sorted(every - covered), [])


# --- the lexer and the body (E3, E4, E8) -----------------------------------------------------------------------

def lexer_and_body() -> None:
    cs_body = "        {\n            %s\n            Assert.Equal(4, x);\n        }\n"

    def cs(first: str, name: str = "Adds") -> str:
        return ("namespace A\n{\n    public class T\n    {\n        // Assert.Null(a);\n        /* Assert.Null(b);\n           \" */\n"
                f"        public void {name}()\n" + cs_body % first + "    }\n}\n")

    # E8: an assertion in a comment or a string is never the first assertion
    for label, first in (("a line comment", "// Assert.Null(a);"), ("a block comment", "/* Assert.Null(a); */"),
                         ("a string", 'var s = "Assert.Null(a);";'), ("a verbatim string with a doubled quote",
                                                                      'var s = @"x ""Assert.Null(a);"" y";'),
                         ("a raw string", 'var s = """Assert.Null(a); " quotes """;'), ("a char literal", "var c = '{';")):
        _m, detail, _c = plan("csharp", cs(first), node="t/T.cs::T.Adds")
        check_eq(f"E8 ({label}): the first assertion is the real one", detail["statement_after"], "Assert.NotEqual(4, x);")
    # an apostrophe in a comment does not open a char literal; a brace in a string is not a brace
    _m, detail, _c = plan("csharp", cs("// it's here\n            var b = \"}{\";"), node="t/T.cs::T.Adds")
    check_eq("an apostrophe in a comment and braces in a string do not move the body", detail["statement_after"],
             "Assert.NotEqual(4, x);")
    # a declaration inside a comment or a string is not a candidate
    text = cs("var a = 1;").replace("// Assert.Null(a);", "// public void Adds() {")
    check_eq("E3: a declaration in a comment is not a candidate", plan("csharp", text, node="t/T.cs::T.Adds")[1]["candidates"],
             [8])
    # a file the lexer cannot read to its end, or whose brackets do not balance, is refused
    text = cs("var a = 1;") + '\n/* never closed'
    check_in("an unterminated block comment is refused", "inside a block comment", refusal_of(lambda: plan("csharp", text, node="t/T.cs::T.Adds")))
    text = cs("var a = 1;") + '\nvar s = "never closed;'
    check_in("an unterminated string is refused", "inside a string literal", refusal_of(lambda: plan("csharp", text, node="t/T.cs::T.Adds")))
    text = cs("var a = 1;").replace("        }\n    }\n}\n", "        }\n    }\n")
    check_in("unbalanced brackets are refused, naming the line", "do not balance at line",
             refusal_of(lambda: plan("csharp", text, node="t/T.cs::T.Adds")))
    # TypeScript (F1b): a regex literal is lexed as one - its quote opens no string
    ts = "describe('c', () => {\n  test('adds', () => {\n    const r = /\"/;\n    expect(x).toBe(3);\n  });\n});\n"
    check_eq("TS: a regex literal holding a quote is a literal (the lexer reads it, no refusal)",
             plan("typescript", ts)[1]["statement_after"], "expect(x).not.toBe(3);")
    ts ="describe('c', () => {\n  test('adds', () => {\n    const s = `a ${b} }`;\n    expect(x).toBe(3);\n  });\n});\n"
    check_eq("TS: a template literal with a brace in it is one string", plan("typescript", ts)[1]["statement_after"],
             "expect(x).not.toBe(3);")

    # F1 (i): a quote the lexer takes for an opener that is none (a regex literal `/can't/`) pairs up with the NEXT
    # quote, and everything between is misread: a head can then sit "in code" that is really a string. A `'` or `"`
    # string cannot cross a line break (`multiline: false`), which is how that misreading shows
    # (the regex literal itself is lexed as one since F1b; an apostrophe in text the lexer does not know - JSX text -
    # still opens a "string", and that string crosses the line)
    ts_trap = ("describe('c', () => {\n  test('adds', () => {\n    const t = <b>don't</b>;\n"
               "    const label = 'expect(a).toBe(1)'; // don't\n    expect(sum(1, 2)).toBe(3);\n  });\n});\n")
    message = refusal_of(lambda: plan("typescript", ts_trap))
    check_in("F1 (i): an apostrophe in JSX text (a string the lexer cannot know) is refused", "single-line string that crosses a line break", message)
    check_in("F1 (i): naming the line the string opens at", "opens at line 3", message)
    check_in("F1 (i): and that nothing was changed", "Nothing was changed", message)
    # F1b: the critic's input on ONE line. The regex literal `/can't/` is a literal, so the apostrophe opens no
    # string, `'expect(a).toBe(1)'` stays a string, and no head is ever planned INSIDE it
    def body(*lines):
        return "describe('c', () => {\n  test('adds', () => {\n" + "".join(f"    {line}\n" for line in lines) + "  });\n});\n"

    trap = "const r = /can't/; const label = 'expect(a).toBe(1)'; // don't"
    message = refusal_of(lambda: plan("typescript", body(trap)))
    check_in("F1b (i): the string holds the only `expect`: no head at all, a refusal - never a write inside the string",
             "no recognised assertion", message)
    source = body(trap, "expect(x).toBe(2);")
    mutated, detail, _c = plan("typescript", source)
    check_eq("F1b (ii): a real head after the one-line trap is found and planned", detail["statement_after"], "expect(x).not.toBe(2);")
    check_eq("F1b (ii): the string literal is byte-identical in the plan, only the real statement changed",
             (mutated.decode().count("'expect(a).toBe(1)'"), mutated.decode().replace("expect(x).not.toBe(2);", "expect(x).toBe(2);")),
             (1, source))
    division = "const h = a / b; const s = 'expect(a).toBe(1)'; expect(h).toBe(2);"
    mutated, detail, _c = plan("typescript", body(division))
    check_eq("F1b (iii): a division stays a division: the plan targets `expect(h).toBe(2)`, never the string",
             detail["statement_before"], "expect(h).toBe(2);")
    check_eq("F1b (iii): ...and the string is intact", "'expect(a).toBe(1)'" in mutated.decode(), True)
    check_eq("F1b (iv): `x = y /g/ 2` is division after an identifier, then a division again: code",
             plan("typescript", body("const x = y /g/ 2; const s = 'expect(a).toBe(1)'; expect(x).toBe(2);"))[1]["statement_before"],
             "expect(x).toBe(2);")
    check_eq("F1b (iv): a division after `)` and after `]` too",
             plan("typescript", body("const k = (a) / 2 + b[0] / 3; const s = 'expect(a).toBe(1)'; expect(k).toBe(2);"))[1]["statement_before"],
             "expect(k).toBe(2);")
    check_eq("F1b (v): a class holding a slash does not close the literal (`/[/]'/`)",
             plan("typescript", body("const r = /[/]'/; const s = 'expect(a).toBe(1)'; expect(r).toBe(2);"))[1]["statement_before"],
             "expect(r).toBe(2);")
    check_eq("F1b (v): an escaped slash does not close it either (`/a\\/'b/`)",
             plan("typescript", body("const r = /a\\/'b/; const s = 'expect(a).toBe(1)'; expect(r).toBe(2);"))[1]["statement_before"],
             "expect(r).toBe(2);")
    check_eq("F1b: after the word `return` a `/` opens a literal",
             plan("typescript", body("const f = () => { return /it's/.test(s); }; const s = 'expect(a).toBe(1)'; expect(f).toBe(2);"))[1]
             ["statement_before"], "expect(f).toBe(2);")
    message = refusal_of(lambda: plan("typescript", body("const r = /abc", "expect(x).toBe(2);")))
    check_in("F1b (vi): an unterminated regex literal is refused, naming its line", "regex literal that opens at line 3 and does not "
             "close on its line", message)
    check_in("F1b (vi): and that nothing was changed", "Nothing was changed", message)
    check_eq("F1b: the regex rule is TS's: a `/` in a C# file is a division (no regex_literal key)",
             plan("csharp", WRAP["csharp"][0].replace("{stmt}", "var h = a / b; var q = (a) /c/ d; Assert.Equal(4, h);"))[1][
                 "statement_before"], "Assert.Equal(4, h);")
    cs_trap = ("namespace A\n{\n  class T\n  {\n    public void Adds()\n    {\n      var s = \"opens here;\n"
               "      and closes there\";\n      Assert.Equal(4, x);\n    }\n  }\n}\n")
    check_in("F1 (i): a C# string that crosses a line break is refused too", "single-line string that crosses a line break",
             refusal_of(lambda: plan("csharp", cs_trap, node="t/T.cs::T.Adds")))
    java_trap = "class C {\n  @Test void adds() {\n    char c = '\n';\n    assertEquals(4, x);\n  }\n}\n"
    check_in("F1 (i): a Java char literal that crosses a line break is refused too", "single-line string that crosses a line break",
             refusal_of(lambda: plan("java", java_trap, node="t/C.java::C.adds")))
    ok_strings = ("describe('c', () => {\n  test('adds', () => {\n    const a = 'one \\\n two';\n    const t = `x\n y ${a}`;\n"
                  "    expect(sum(1, 2)).toBe(3);\n  });\n});\n")
    check_eq("F1 (i) control: a backslash-newline continuation and a template literal MAY cross lines",
             plan("typescript", ok_strings)[1]["statement_after"], "expect(sum(1, 2)).not.toBe(3);")
    check_eq("F1 (i) control: a C# verbatim string may cross lines",
             plan("csharp", WRAP["csharp"][0].replace("{stmt}", 'var s = @"a\nb"; Assert.Equal(4, x);'))[1]["statement_after"],
             "Assert.NotEqual(4, x);")
    # F1 (ii): a conditional-compilation directive: every branch lexes as code, one is compiled
    cs_if = ("namespace A\n{\n  class T\n  {\n    public void Adds()\n    {\n#if NET6\n      Assert.Equal(4, x);\n#else\n"
             "      Assert.Equal(5, x);\n#endif\n    }\n  }\n}\n")
    for at in (None, 8, 10):
        message = refusal_of(lambda: plan("csharp", cs_if, node="t/T.cs::T.Adds", at=at))
        check_in(f"F1 (ii): #if/#else/#endif is refused, naming the directive and its line (--at {at})",
                 "conditional-compilation directive `#if NET6` at line 7", message)
    check_in("F1 (ii): the door is the data row / the product probe, not --at", "red_sandbox.py --probe", message)
    check_in("F1 (ii): and it is not a verdict on the test", "not a verdict on the test", message)
    check_in("F1 (ii): a directive OUTSIDE the test is refused too (the whole method may be inactive)", "`#if DEBUG` at line 1",
             refusal_of(lambda: plan("csharp", "#if DEBUG\n" + WRAP["csharp"][0].replace("{stmt}", "Assert.Equal(4, x);") + "#endif\n")))
    region = WRAP["csharp"][0].replace("{stmt}", "#region r\n            Assert.Equal(4, x);\n            #endregion // #if Y")
    check_eq("F1 (ii) control: `#region` and a `#if` inside a comment are no directive",
             plan("csharp", region)[1]["statement_after"], "Assert.NotEqual(4, x);")
    # E4: the body is the block that opens right after the parameter list - never the first `{`
    java = "class C {\n    @Test(expected = {X.class})\n    void adds(int[] a, Map<String, int[]> m) throws Exception, Other {\n        assertEquals(4, x);\n    }\n}\n"
    check_eq("method style: the body opens after the balanced parameter list and a `throws` list",
             plan("java", java, node="t/C.java::C.adds")[1]["statement_after"], "assertNotEquals(4, x);")
    for label, text in (("a C# `=>` expression body", "class T {\n  public void Adds() => Assert.Equal(1, 1);\n}\n"),
                        ("an interface declaration", "interface T {\n  void Adds();\n}\n")):
        lang, node = ("csharp", "t/T.cs::T.Adds") if "C#" in label else ("java", "t/T.java::T.Adds")
        message = refusal_of(lambda: plan(lang, text, node=node))
        check_in(f"E4 ({label}): refused, naming the shape", "no block opens where the body", message)
        check_in(f"E4 ({label}): and that nothing was mutated", "never mutated", message)
    # call style: the first body_open at depth 1; the Playwright destructuring brace is not the body (the first `{`)
    pw = "test('adds', async ({ page }) => {\n  await expect(page).toHaveTitle('x');\n});\n"
    _m, detail, _c = plan("typescript", pw)
    check_eq("E4 (call style): `({ page }) => {` - the body is the block after `=>`, not the first `{`",
             (detail["statement_after"], detail["line"]), ("expect(page).not.toHaveTitle('x');", 2))
    tag = "test('adds', { tag: '@smoke' }, async ({ page }) => {\n  await expect(page).toHaveTitle('x');\n});\n"
    check_eq("E4 (call style): an options object with a tag does not move the body",
             plan("typescript", tag)[1]["statement_after"], "expect(page).not.toHaveTitle('x');")
    fn = "test('adds', async function () {\n  expect(x).toBe(3);\n});\n"
    check_eq("E4 (call style): a `function` callback is a body too", plan("typescript", fn)[1]["line"], 2)
    for label, text in (("a concise arrow", "test('adds', () => expect(x).toBe(3));\n"),
                        ("a nested arrow at depth 2", "test('adds', wrap(() => {\n  expect(x).toBe(3);\n}));\n"),
                        ("no callback", "test('adds');\n")):
        message = refusal_of(lambda: plan("typescript", text))
        check_in(f"E4 ({label}): refused, naming the shape", "no block opens where the body", message)
    # `test.each` / a template title with a substitution are not a literal title
    # EP1-36 (named to the critic): the pin was a refusal for EVERY `${` title. It now holds for an entry WITHOUT `title_template`
    # (the old behaviour, kept); the typescript entry has one, so its templated title is a pattern and `template` is set.
    real = AD.assertion_detectors

    def without_template():
        doc = copy.deepcopy(real())
        doc["typescript"].pop("title_template", None)
        return doc
    AD.assertion_detectors = without_template
    try:
        check_in("a title with a `${` substitution is refused by an entry that has no `title_template`", "template substitution",
                 refusal_of(lambda: PBC.parse_node("t/x.test.ts::adds ${n}")))
    finally:
        AD.assertion_detectors = real
    check_eq("EP1-36: the typescript entry reads the title as a pattern", PBC.parse_node("t/x.test.ts::adds ${n}").get("template"), True)


# --- candidates, --at, the heads (E3, E5, E6, E7) --------------------------------------------------------------

def candidates_and_heads() -> None:
    def many(n: int) -> str:
        body = "".join(f"    public class C{i}\n    {{\n        public void Adds()\n        {{\n            Assert.Equal({i}, x);\n        }}\n    }}\n"
                       for i in range(n))
        return "namespace A\n{\n" + body + "}\n"

    node = "t/T.cs::Adds"
    message = refusal_of(lambda: plan("csharp", many(1) + "", node=node)) or "ok"
    check_eq("one declaration: no refusal", message, "ok")
    for count in (2, 5, 6, 9):
        message = refusal_of(lambda: plan("csharp", many(count), node=node))
        listed = len(re.findall(r"line \d+", message))
        check_in(f"E3 ({count} declarations): refused, with the door --at <line>", "--at <line>", message)
        check_eq(f"E3 ({count} declarations): at most 5 candidate lines are listed", listed, min(count, 5))
        check_eq(f"E3 ({count} declarations): 'and N more' only beyond 5",
                 re.search(r"and (\d+) more", message).group(1) if "more" in message else "", "" if count <= 5 else str(count - 5))
        check_in(f"E3 ({count} declarations): nothing was changed", "Nothing was changed", message)
    _m, detail, _c = plan("csharp", many(3), node=node, at=14)
    check_eq("--at picks the candidate whose body holds the line (and the head that starts there)",
             (detail["statement_after"], detail["at"], detail["candidates"]), ("Assert.NotEqual(1, x);", 14, [5, 12, 19]))
    check_eq("...the first body", plan("csharp", many(3), node=node, at=7)[1]["statement_after"], "Assert.NotEqual(0, x);")
    check_in("--at in no body is refused", "lies in 0 of the 3 bodies", refusal_of(lambda: plan("csharp", many(3), node=node, at=1)))
    check_in("--at on a line that starts no assertion is refused", "no recognised assertion starts on line 13",
             refusal_of(lambda: plan("csharp", many(3), node=node, at=13)))
    check_in("no declaration: refused, saying which pattern and where the row is", "no declaration of 'Nope'",
             refusal_of(lambda: plan("csharp", many(2), node="t/T.cs::Nope")))
    # E6: no recognised assertion
    body = "class T {\n  void Adds() {\n    var a = 1;\n    Helpers.Expect(a);\n  }\n}\n"
    message = refusal_of(lambda: plan("csharp", body, node="t/T.cs::T.Adds"))
    check_in("E6: no assertion in the body: refused, naming --oracle", "--oracle", message)
    check_in("E6: ... and the data door (add a head)", "references/detectors.json assertion_probes.csharp", message)
    # E7: the first assertion is a form with invert null: refused, never a later one
    text = "class T {\n  void Adds() {\n    Assert.Throws<E>(() => Foo());\n    Assert.Equal(4, x);\n  }\n}\n"
    message = refusal_of(lambda: plan("csharp", text, node="t/T.cs::T.Adds"))
    check_in("E7: the first assertion has no inversion: refused, naming it", "`Assert.Throws` at line 3", message)
    check_in("E7: ... and that it never skips to a later one", "never skips to a later assertion", message)
    _m, detail, _c = plan("csharp", text, node="t/T.cs::T.Adds", at=4)
    check_eq("E7 door: --at names the later assertion", detail["statement_after"], "Assert.NotEqual(4, x);")
    # E7: a recognised form with no pair at its position: refused (Hamcrest assertThat(x, is(y)), a chain)
    text = "class C {\n  @Test void adds() {\n    assertThat(x, is(3));\n    assertEquals(1, 1);\n  }\n}\n"
    message = refusal_of(lambda: plan("java", text, node="t/C.java::C.adds"))
    check_in("E7: Hamcrest assertThat(x, is(y)): no pair matches at its position - refused", "no inversion pair", message)
    text = "class C {\n  @Test void adds() {\n    assertThat(x).extracting(\"a\").isEqualTo(3);\n  }\n}\n"
    check_in("E7 (`find` is matched AT the position, never searched over the statement): a later `.isEqualTo` is not inverted",
             "no inversion pair", refusal_of(lambda: plan("java", text, node="t/C.java::C.adds")))
    text = "describe('c', () => {\n  it('adds', () => {\n    expect(x).toEqual(3);\n    expect(y).not.toBe(2);\n  });\n});\n"
    check_eq("E7: Chai-free TS `.toEqual` is a plain pair", plan("typescript", text, node="t/x.test.ts::adds")[1]["statement_after"],
             "expect(x).not.toEqual(3);")
    text = "describe('c', () => {\n  it('adds', () => {\n    expect(x).to.equal(3);\n  });\n});\n"
    check_in("E7: Chai `.to.equal` matches no pair: refused", "no inversion pair",
             refusal_of(lambda: plan("typescript", text, node="t/x.test.ts::adds")))
    # a multi-line chain: `find`'s `\\s*` would eat the line break - refused with the pair named (a known data gap)
    text = "class C {\n  @Test void adds() {\n    assertThat(x)\n        .isEqualTo(3);\n  }\n}\n"
    message = refusal_of(lambda: plan("java", text, node="t/C.java::C.adds"))
    check_in("a chain split over lines: refused because the pair would move a line", "would change the line breaks", message)
    check_in("...naming the pair", "pair A1", message)
    # the statement extents: `;` outside any bracket; a TS newline that no continuation covers
    text = "class T {\n  void Adds() {\n    Assert.Equal(4,\n        Foo(1, 2));\n    Assert.True(y);\n  }\n}\n"
    _m, detail, _c = plan("csharp", text, node="t/T.cs::T.Adds")
    check_eq("a statement over two lines: extent and the line count kept", (detail["line"], detail["end_line"]), (3, 4))
    ts = "describe('c', () => {\n  it('adds', () => {\n    expect(a)\n      .toBe(3)\n    expect(b).toBe(4)\n  });\n});\n"
    _m, detail, _c = plan("typescript", ts)
    check_eq("TS: a chain continued on the next line is ONE statement; the newline after it ends it",
             (detail["line"], detail["end_line"], detail["statement_after"]), (3, 4, "expect(a).not\n      .toBe(3)"))
    ts = "describe('c', () => {\n  it('adds', () => {\n    expect(a).toBe(3) // note\n    expect(b).toBe(4)\n  });\n});\n"
    check_eq("TS: a trailing comment is not part of the statement", plan("typescript", ts)[1]["statement_after"],
             "expect(a).not.toBe(3)")
    ts = "describe('c', () => {\n  it('adds', () => {\n    expect(a).toBe(3)\n  });\n});\n"
    check_eq("TS: the last statement of the block, with no `;`", plan("typescript", ts)[1]["statement_after"],
             "expect(a).not.toBe(3)")
    check_in("C#: a statement the block closes over is refused (`;` demanded)", "is not ended by `;`",
             refusal_of(lambda: plan("csharp", "class T {\n  void Adds() {\n    Assert.Equal(4, x)\n  }\n}\n", node="t/T.cs::T.Adds")))


# --- the guards of the plan (A2, E9, E21) ------------------------------------------------------------------------

def plan_guards() -> None:
    doc = AD.assertion_detectors()
    # A2: a fires_as that matches the mutated statement itself is refused (the run's own text could fire it)
    entry = copy.deepcopy(doc["typescript"])
    entry["assertions"][0]["invert"][1]["fires_as"] = "^expect"
    text = WRAP["typescript"][0].replace("{stmt}", "expect(x).toBe(3);")
    message = refusal_of(lambda: plan("typescript", text, entry=entry))
    check_in("A2: refused when fires_as matches statement_after", "would also match the mutated statement's own text", message)
    check_in("A2: naming the pair", "pair T2", message)
    check_eq("A2 control: the shipped pair is fine on the same text", plan("typescript", text)[1]["pair_id"], "T2")
    # A2, the real-world shape: a subject named `received`
    text = WRAP["typescript"][0].replace("{stmt}", "expect(received).toBe(3);")
    check_in("A2: a subject literally named `received` makes T2's text match the mutated statement: refused",
             "would also match the mutated statement's own text", refusal_of(lambda: plan("typescript", text)))
    text = WRAP["typescript"][0].replace("{stmt}", "expect(page).toHaveTitle('x');")
    check_eq("A2 control: `expect(page)` is not `expect(received)`: planned", plan("typescript", text)[1]["pair_id"], "T2")
    # R5: `find` is applied with `re.match` at exactly the form's position - even a `find` the data wrote WITHOUT
    # the `^` the seed rows carry is never searched for over the rest of the statement
    entry = copy.deepcopy(doc["csharp"])
    form = next(f for f in entry["assertions"] if f["matcher_at"] == "second_arg")
    form["invert"][0]["find"] = "Is\\.(?!Not\\b)"
    nested = WRAP["csharp"][0].replace("{stmt}", "Assert.That(x, Foo(Is.EqualTo(1)));")
    check_in("R5: a `find` with no `^` is matched at the position, not found later in the statement",
             "no inversion pair", refusal_of(lambda: plan("csharp", nested, entry=entry)))
    plain = WRAP["csharp"][0].replace("{stmt}", "Assert.That(x, Is.EqualTo(1));")
    check_eq("R5 control: the same `find` at the second argument itself is applied",
             plan("csharp", plain, entry=entry)[1]["statement_after"], "Assert.That(x, Is.Not.EqualTo(1));")
    # E9: the newline count / the breaks / the brackets
    entry = copy.deepcopy(doc["csharp"])
    entry["assertions"][0]["invert"][0]["replace"] = "Assert.NotEqual(\n"
    text = WRAP["csharp"][0].replace("{stmt}", "Assert.Equal(4, x);")
    check_in("E9: a replacement that adds a line break is refused", "would change the line breaks",
             refusal_of(lambda: plan("csharp", text, entry=entry)))
    entry = copy.deepcopy(doc["csharp"])
    entry["assertions"][0]["invert"][0]["replace"] = "Assert.NotEqual(("
    check_in("E9: a replacement that unbalances the brackets is refused", "bracket balance",
             refusal_of(lambda: plan("csharp", text, entry=entry)))
    entry = copy.deepcopy(doc["csharp"])
    entry["assertions"][0]["invert"][0]["replace"] = "Assert.NotEqual /* "
    check_in("E9: a replacement that opens a comment (lexical state) is refused", "bracket balance or the lexical state",
             refusal_of(lambda: plan("csharp", text, entry=entry)))
    # E21: BOM and CRLF kept; a non-UTF-8 file refused
    source = WRAP["csharp"][0].replace("{stmt}", "Assert.Equal(4, x);")
    crlf = source.replace("\n", "\r\n").encode("utf-8")
    mutated, detail, _c = plan("csharp", crlf)
    check_eq("E21: CRLF line ends are kept byte for byte", mutated, crlf.replace(b"Assert.Equal", b"Assert.NotEqual", 1))
    check_eq("E21: and the line numbers read `\\r\\n` as one break", detail["line"], 10)
    bom = b"\xef\xbb\xbf" + crlf
    mutated, detail, _c = plan("csharp", bom)
    check_eq("E21: a BOM is kept", mutated, bom.replace(b"Assert.Equal", b"Assert.NotEqual", 1))
    check_eq("E21: and does not move a line", detail["line"], 10)
    lone = source.replace("\n", "\r").encode("utf-8")
    check_eq("E21: a lone CR is a line break too", plan("csharp", lone)[1]["line"], 10)
    check_in("E21: a file that is not UTF-8 is refused", "is not UTF-8",
             refusal_of(lambda: plan("csharp", b"class T {\n  void Adds() {\n    Assert.Equal(1, \xff);\n  }\n}\n", node="t/T.cs::T.Adds")))
    check_in("E21: a non-UTF-8 file is named, nothing was changed", "Nothing was changed",
             refusal_of(lambda: plan("csharp", b"\xff\xfe", node="t/T.cs::T.Adds")))


# --- the report-id tail and the run shape (R6), unit level ---------------------------------------------------------

def tail_and_names() -> None:
    cs = AD.assertion_detectors()["csharp"]
    java = AD.assertion_detectors()["java"]
    ts = AD.assertion_detectors()["typescript"]
    ok = PBC._tail_matches
    check("R6(c): the id ends with the tail, after a dot", ok("Acme.Tests.CalcTests.Adds", "CalcTests.Adds", cs))
    check("R6(c): the id IS the tail", ok("CalcTests.Adds", "CalcTests.Adds", cs))
    check("R6(c): a method name alone", ok("Acme.CalcTests.Adds", "Adds", cs))
    check("R6(c): a trailing (...) of the id is stripped", ok("Acme.CalcTests.Adds(a: 1, b: (2))", "CalcTests.Adds", cs))
    check("R6(c): `::` of a JUnit id is the tail's join", ok("com.acme.CalcTest::adds()", "CalcTest.adds", java))
    check("R6(c): a TS id `a b::a b` ends with the title after a space", ok("calc adds::calc adds", "adds", ts))
    check("R6(c): a Vitest row name with ` > ` separators", ok("Calc > adds", "Calc adds", ts))
    check("R6(c): whitespace is folded on both sides", ok("calc   adds", "calc adds", ts))
    check("R6(c) the boundary is a character of `.  /:`: `/` counts", ok("src/sum.test.ts/adds", "adds", ts))
    check("R6(c) the boundary: `:` counts", ok("file.cs:Adds", "Adds", cs))
    check("R6(c): a different method does not match", not ok("Acme.CalcTests.AddsMore", "Adds", cs))
    check("R6(c): a longer method name ending in the tail does not match (no boundary)", not ok("Acme.CalcTests.MyAdds", "Adds", cs))
    check("R6(c): the class decides when it is given", not ok("Acme.OtherTests.Adds", "CalcTests.Adds", cs))
    check("R6(c): an empty id matches nothing", not ok("", "Adds", cs))
    check("R6(c): a title that really ends in `)` is still found (both spellings are tried)", ok("calc returns f()", "returns f()", ts))
    # F2: for a call-style entry the join and the boundary are both a space, so the id of `calc does not adds` also
    # "ends with" `adds`; another test of the file whose LONGER title the id ends with is refused
    two = ("describe('calc', () => {\n  test('adds', () => {\n    expect(a).toBe(1);\n  });\n"
           "  test('does not adds', () => {\n    expect(a).toBe(1);\n  });\n  it('more things', () => {\n    expect(a).toBe(1);\n  });\n});\n")
    longer = PBC._longer_title
    check("F2 (the premise): the plain tail check passes for the OTHER test's id", ok("calc does not adds::calc does not adds", "adds", ts))
    check_eq("F2: the report id of the longer-titled test is caught, with the title and its line",
             longer(two, ts, "adds", "calc does not adds::calc does not adds"), ("does not adds", 5))
    check_eq("F2 control: the id of the test itself is not", longer(two, ts, "adds", "calc adds::calc adds"), ("", 0))
    check_eq("F2 control: another title that does not end with the tail is not", longer(two, ts, "adds", "calc more things::calc more things"), ("", 0))
    check_eq("F2 control: a file with one title has no other", longer(two.split("  test('does not adds'")[0] + "});\n", ts, "adds",
                                                                      "calc does not adds::x"), ("", 0))
    check_eq("F2: the longer title is found by its own tail too (`does not adds` is not refused for itself)",
             longer(two, ts, "does not adds", "calc does not adds::calc does not adds"), ("", 0))
    check_eq("F2: a comment or a string holding a declaration is no other test",
             longer(two.replace("  test('does not adds', () => {\n    expect(a).toBe(1);\n  });\n",
                                "  // test('does not adds', () => {\n  //   expect(a).toBe(1);\n  // });\n"),
                    ts, "adds", "calc does not adds::x"), ("", 0))
    # parse_node: the tail, the name and the segments
    spec = PBC.parse_node("tests\\CalcTests.cs::Acme.Tests.CalcTests.Adds")
    check_eq("parse: backslashes are slashes, the name is the last segment", (spec["file"], spec["function"], spec["language"]),
             ("tests/CalcTests.cs", "Adds", "csharp"))
    check_eq("parse: the tail is the segments joined by tail_join", spec["tail"], "Acme.Tests.CalcTests.Adds")
    spec = PBC.parse_node("t/Outer.cs::Outer+Inner.Adds(a: 1)")
    check_eq("parse: `+` separates nested classes; a trailing (...) of the name is stripped", (spec["function"], spec["tail"]),
             ("Adds", "Outer.Inner.Adds"))
    spec = PBC.parse_node("t/CalcTest.java::CalcTest#adds")
    check_eq("parse: `#` separates a Java class from its method", (spec["function"], spec["chain"]), ("adds", ["CalcTest"]))
    spec = PBC.parse_node("t/x.test.ts::adds two  numbers")
    check_eq("parse: a TS title keeps its words (folded), no separator splits it", (spec["function"], spec["tail"]),
             ("adds two numbers", "adds two numbers"))
    check_in("parse: a method name that is not an identifier is refused", "not an identifier",
             refusal_of(lambda: PBC.parse_node("t/T.cs::T.Adds Two")))
    check_in("parse: nothing after `::` is refused", "nothing follows", refusal_of(lambda: PBC.parse_node("t/T.cs::::")))
    check_eq("parse: a Python node carries its language, entry and tail since N3b (reader stays `ast`)",
             (lambda s: (s["language"], s["reader"], s["tail"], bool(s["entry"]["forms"])))(PBC.parse_node("tests/test_calc.py::TestX::test_y[p]")),
             ("python", "ast", "TestX::test_y", True))
    check_eq("parse: .PY (upper case) is not Python's path and has no entry",
             "no assertion probe" in refusal_of(lambda: PBC.parse_node("tests/test_calc.PY::test_y")), True)
    check_eq("E10 (the interim rule): a file under roots.test and no protected path",
             PBC._in_test_root({"profiles": [{"roots": {"test": "tests"}}], "app_root": ".", "protected_app_paths": ["src"]},
                               "tests/Helpers.cs"), True)
    for label, cfg, rel in (("outside every test root", {"profiles": [{"roots": {"test": "tests"}}]}, "src/Calc.cs"),
                            ("under a protected path", {"profiles": [{"roots": {"test": "tests"}}], "protected_app_paths": ["tests/app"]},
                             "tests/app/Calc.cs"),
                            ("under a protected path given relative to app_root",
                             {"profiles": [{"roots": {"test": "backend/tests"}}], "app_root": "backend", "protected_app_paths": ["tests/app"]},
                             "backend/tests/app/x.cs"),
                            ("with no test root at all", {"profiles": []}, "tests/x.cs"),
                            ("when everything is protected", {"profiles": [{"roots": {"test": "tests"}}], "protected_app_paths": ["."]},
                             "tests/x.cs"),
                            ("only a prefix of a root's name", {"profiles": [{"roots": {"test": "tests"}}]}, "tests2/x.cs")):
        check_eq(f"E10: {label} is not an oracle place", PBC._in_test_root(cfg, rel), False)


# --- the verdict table (R8), unit level --------------------------------------------------------------------------------

def verdict_table() -> None:
    entry = AD.assertion_detectors()["csharp"]
    detail = {"line": 11, "end_line": 12, "language": "csharp", "candidates": [8], "at": None, "pair": 0, "pair_id": "X1",
              "fires_as": "^Assert\\.NotEqual\\(\\) Failure"}
    msg = "Assert.NotEqual() Failure: Values are equal\nExpected: Not 4"

    def row(status, message=msg, text="", kind="failure"):
        # a skipped row holds no failure or error problem (a row that does is `failed`, never read as not executed, t-2045 E-P)
        problems = [] if status in ("passed", "not_run", "skipped") else [{"kind": kind, "message": message, "text": text}]
        return {"test_id": "x", "status": status, "problems": problems}

    def site(line=11, kind="assertion", **extra):
        return dict({"location": f"tests/CalcTests.cs:{line}", "failure_kind": kind, "frame": "  at X"}, **extra)

    unread = {"site_unread": "trx/csharp", "reason": "no frame matched"}
    dotnet, wrapper = ["dotnet", "test", "--filter", "x"], ["bash", "run.sh"]

    def judge(r, s, d=None, *, among=False, argv=dotnet, e=entry):
        return PBC.judge_probe_row(r, s, e, d or detail, among=among, argv=argv)

    cells = [
        ("passed + --at among 2+ candidates", judge(row("passed"), {}, dict(detail, candidates=[8, 20], at=15), among=True), "incomplete"),
        ("passed + compiled + a wrapper launcher (F9)", judge(row("passed"), {}, argv=wrapper), "incomplete"),
        ("passed + compiled + no launcher at all", judge(row("passed"), {}, argv=[]), "incomplete"),
        ("passed + compiled + launcher builds by default", judge(row("passed"), {}), "no_failure"),
        ("passed + .exe launcher is the same launcher", judge(row("passed"), {}, argv=["C:\\Program Files\\dotnet\\dotnet.exe", "test"]), "no_failure"),
        ("error", judge(row("error", kind="error"), {}), "incomplete"),
        ("failed + site unread", judge(row("failed"), unread), "incomplete"),
        ("failed + no location and no marker", judge(row("failed"), {}), "incomplete"),
        # N3b: only the marker proves; the place and the library's wording (`fires_as`) are facts, never a verdict
        ("failed in the statement + the marker in its text", judge(row("failed", msg, "qa-probe-t1"), site(), dict(detail, message_marker="qa-probe-t1", fires_as=None)), "intended_failure"),
        ("failed on the statement's last line + the marker", judge(row("failed", msg, "qa-probe-t1"), site(12), dict(detail, message_marker="qa-probe-t1", fires_as=None)), "intended_failure"),
        ("failed in the statement + fires_as does not match", judge(row("failed", "Assert.NotEqual() has failed"), site()), "incomplete"),
        ("failed one line above the statement", judge(row("failed"), site(10)), "incomplete"),
        ("failed one line below the statement", judge(row("failed"), site(13)), "incomplete"),
        ("failed in another project file (exception)", judge(row("failed"), site(11, "exception")), "incomplete"),
        ("failed in the statement + fires_as matches, no marker", judge(row("failed"), site()), "incomplete"),
        ("skipped", judge(row("skipped"), {}), "not_executed"),
        ("not_run", judge(row("not_run"), {}), "not_executed"),
    ]
    for label, got, verdict in cells:
        check_eq(f"R8: {label} -> {verdict}", got["verdict"], verdict)
    check("R8: every non-verdict says what it could not read (a note)",
          all(got["note"] for _l, got, v in cells if v in ("incomplete", "not_executed")))
    check("R8: an intended_failure carries no note and no mismatch",
          cells[8][1]["note"] == "" and cells[8][1]["mismatches"] == [])
    check_in("F9: the wrapper note names the launcher and the builders", "bash run.sh", cells[1][1]["note"])
    check_in("F9: the no_failure note names the launcher that builds by default", "builds by default (`dotnet test`)",
             judge(row("passed"), {})["note"])
    check_in("E5: the --at note says a pass does not tell which body ran", "does not say which body ran", cells[0][1]["note"])
    # t-1968 N2 (spec "Required behaviour" item 1) replaced the old note: the pair travels in `judgment_facts.fires_as_pair` (pinned in test_probe_marker_judgment.py)
    check_in("E15: the drift note says the factory cannot read the text and the code critic judges it", "the code critic judges it",
             cells[10][1]["note"])
    check_eq("E15: ...and the cause is judgment", cells[10][1].get("cause"), "judgment")
    check_eq("R8 N3b: a failure at another place is judgment, never wrong_location, whatever the wording says",
             [(cells[i][1]["verdict"], cells[i][1].get("cause"), cells[i][1]["actual_location"]) for i in (11, 12, 13, 14)],
             [("incomplete", "judgment", None)] * 4)
    check_eq("R8: observed keeps the message head, the frame and the site",
             (cells[8][1]["observed"]["message_head"], cells[8][1]["observed"]["frame"], cells[8][1]["observed"]["location"]),
             ("Assert.NotEqual() Failure: Values are equal", "  at X", "tests/CalcTests.cs:11"))
    # TS: not compiled - a pass is a no_failure through any launcher, with the residual risk said in `observed`
    ts = AD.assertion_detectors()["typescript"]
    tdetail = dict(detail, language="typescript")
    got = PBC.judge_probe_row(row("passed"), {}, ts, tdetail, among=False, argv=["bash", "run.sh"])
    check_eq("E14: TypeScript is not compiled: a pass through any launcher is a no_failure", got["verdict"], "no_failure")
    check_in("E14: ... with the residual risk said in `observed`", "compiled output", got["observed"].get("residual", ""))
    # the message and the text: message first; the text above the first frame when the message is empty or misses
    ts_detail = dict(tdetail, fires_as=AD.assertion_detectors()["typescript"]["assertions"][0]["invert"][1]["fires_as"])
    jest_text = ("Error: expect(received).not.toBe(expected) // Object.is equality\n\nExpected: not 3\nReceived: 3\n"
                 "      at Object.<anonymous> (/clone/src/sum.test.ts:11:20)")
    for label, message, text, expected in (("empty message, matching text", "", jest_text, True),
                                           ("a message that does not match, a text that does", "src/sum.test.ts:11:20 adds", jest_text, True),
                                           ("a matching message, no text", "expect(received).not.toBe(expected)", "", True),
                                           ("neither matches", "boom", "Error: boom\n      at x (/a.ts:1:1)", False),
                                           ("a code frame echoing the statement is not the start of the text",
                                            "", "boom\n  > 11 |   expect(received).not.toBe(3);\n      at Object.<anonymous> (/clone/src/sum.test.ts:11:20)", False)):
        got = PBC.judge_probe_row(row("failed", message, text), site(), ts, dict(ts_detail, language="typescript"), among=False, argv=[])
        check_eq(f"R8 (L8) N3b: {label}: the wording alone proves nothing", got["verdict"] == "intended_failure", False)
        check_eq(f"R8 (L8): {label}: `fires_on` still reads it (the `missed` note's fact)",
                 PBC.fires_on(row("failed", message, text), ts, ts_detail["fires_as"]), expected)
    check_eq("the text above the first frame: stops at a frame or a skipped line",
             PBC.text_head("a\nb\n      at x (/p/a.ts:1:2)\nc", ts), "a\nb")
    check_eq("the launcher words: basenames, .exe/.cmd/.bat stripped, joined by spaces",
             PBC.launcher_words(["C:\\x\\mvn.cmd", "/usr/bin/dotnet", "'npx.exe'"]), "mvn dotnet npx")
    check_eq("builds_by_default is matched at a token boundary", (PBC.builds_by_default(["dotnet", "test"], entry),
                                                                   PBC.builds_by_default(["dotnetx", "test"], entry),
                                                                   PBC.builds_by_default(["dotnet"], entry)), ("dotnet test", "", ""))
    check_eq("...and a prefix of several words", PBC.builds_by_default(["dotnet", "test", "--no-restore"], entry), "dotnet test")
    check_eq("...java's launchers", [PBC.builds_by_default([l, "test"], AD.assertion_detectors()["java"]) for l in ("mvn", "mvnw.cmd", "gradle", "gradlew")],
             ["mvn", "mvnw", "gradle", "gradlew"])


# --- through the CLI: the verdict, the receipt, the window, the bytes (K1a, K2, K6, E13-E15, E20, E21) -------------

def one_language(stub: Path, lang: str) -> None:
    spec = LANGS[lang]
    old = OLD_NS
    root = lang_project(lang, mtime_ns=old)
    try:
        target = root / spec["file"]
        original = target.read_bytes()
        proc, record = lrun(root, stub, node_of(lang), spec["iid"], stub_cfg(lang))
        label = f"{lang}"
        lines, markers = check_lines(lang), check_markers(lang)
        keys = [f"{spec['file']}:{n}" for n in lines]
        rows = record.get("checks") or []
        # F5: the expectation is the FIXTURE's (`marker` in LANGS), never read back from the record: a marker lost on a form that must
        # carry one is a red here, not a quiet turn onto the judgment branch. t-2064 P4b (old -> new): `mutation_detail.message_marker` of the one
        # mutation -> `proved_by == "marker"` of each CHECK row of the walk (the aggregate has one row per check, the fixture says per check)
        check_eq(f"{lang} F5: each check row carries a marker exactly where the fixture's form takes one",
                 [r.get("proved_by") == "marker" for r in rows], markers)
        if not all(markers):
            # t-2064 N3b: a form that takes no message (xunit `Assert.Equal`) carries no token, so no runner text proves the probe:
            # the code critic judges it (INV: only our own text proves without a role). The rest of the case goes on after that judgment.
            check_eq(f"{label} N3b: no token in the form, so the failure at the statement is judgment, not proved",
                     (proc.returncode, record.get("verdict"), [r.get("verdict") for r in rows], [r.get("cause") for r in rows],
                      [r.get("proved_by") for r in rows]),
                     (1, "incomplete", ["intended_failure" if m else "incomplete" for m in markers],
                      [None if m else "judgment" for m in markers], ["marker" if m else None for m in markers]))
            judged = run_script("probe_by_code.py", "--task", TASK, "--dispatch", DISPATCH, "--judge", spec["iid"], "--verdict", "fires",
                                "--quote", spec["message"].splitlines()[0], "--json", cwd=root, env=env_for(root, stub, PROBE_SCRIPTS_DIR=str(SCRIPTS)))
            try:
                answer = json.loads(judged.stdout)
            except ValueError:
                answer = {}
            check_eq(f"{label} N3b: the critic's `fires` proves it", (answer.get("verdict"), answer.get("proved_by")),
                     ("intended_failure", "critic"))
            # t-2064 fix Q7 (repin): the judgment re-folds the aggregate ON DISK (the product did that already: verdict, receipt, publish); this
            # case kept reading `record` and `proc` of the walk BEFORE the judgment, so every pin below read the owed state. From here the call
            # is the judging call (`proc`) and the record is the one the judgment left (the same file `--judge` answered from)
            proc = judged
            record = json.loads((task_of(root) / "work" / "probes" / f"{spec['iid']}.json").read_text(encoding="utf-8"))
        check(f"{label}: exit 0", proc.returncode == 0, proc.stdout + proc.stderr)
        check_eq(f"{label} K1a: intended_failure", record.get("verdict"), "intended_failure")
        line = lines[0]
        check_eq(f"{label}: expected_location is the project-relative path and the statement's line",
                 record.get("expected_location"), f"{spec['file']}:{line}")
        check_eq(f"{label}: actual_location equals it", record.get("actual_location"), record.get("expected_location"))
        # t-2064 P4b (old -> new): the reason was the marker (`fires as /`) of the one mutation; the aggregate's reason counts the plan
        check_eq(f"{label}: the reason says every check of the plan proved", record.get("expected_reason"),
                 f"{len(lines)} of {len(lines)} checks of the plan proved")
        check_eq(f"{label}: actual_reason equals it", record.get("actual_reason"), record.get("expected_reason"))
        check_eq(f"{label}: failure_kind assertion, mutation_kind assertion, level live",
                 (record.get("failure_kind"), record.get("mutation_kind"), record.get("proof_level")), ("assertion", "assertion", "live"))
        detail = record.get("mutation_detail") or {}
        # old: style, language, line, end_line of the detector's mutation -> the aggregate's `mutation_detail` is {file, line, end_line, checks}
        # (the first check's place and the keys of the plan); style and language are not carried (they were the detector's, not a fact of the run)
        check_eq(f"{label}: the detail names the file, the first check's line and the plan's keys",
                 (detail.get("file"), detail.get("line"), detail.get("end_line"), detail.get("checks")), (spec["file"], line, line, keys))
        # old: `statement_inverted` of the record == the fixture's inverted text; new: the bytes the runner saw (stub_seen_text of its first
        # run's evidence) hold that text at the first check's line (N1: a marked statement is not `after` byte for byte, so the fixture's `hit`)
        check_in(f"{label}: the statement after the inversion is what the runner saw on the first check's line",
                 spec.get("hit", spec["after"]), mutated_line(root, record, line))
        # old: at is None and the one declaration is the one candidate -> the plan is exactly the body's checks, each run once, none left
        check_eq(f"{label}: the plan is the body's checks, each run once, none left", (len(rows), record.get("plan_runs"), record.get("plan_remaining")),
                 (len(lines), len(lines), []))
        # old: the detail carried head, pair, pair_id, fires_as, marker, form, matcher_at -> each check has its own record naming its key, its kind
        # (`invert`) and the entry it ran
        own = [read_check_record(root, spec["iid"], i) for i in range(len(lines))]
        check_eq(f"{label}: every check has its own record: its key, `invert`, its entry's hash, its target",
                 [(r.get("check_key"), r.get("probe_kind"), bool(r.get("entry_sha")), (r.get("target") or {}).get("line")) for r in own],
                 [(k, "invert", True, n) for k, n in zip(keys, lines)])
        check_eq(f"{label}: the file is byte-identical afterwards", target.read_bytes(), original)
        # old: `restore.restored_from == "copy"` (the aggregate has no such key) -> the restore's sha is the author's, and one restore per run
        check_eq(f"{label}: the restore is verified, to the author's bytes, once per run, and no copy is left",
                 ((record.get("restore") or {}).get("verified"), (record.get("restore") or {}).get("sha256"), (record.get("restore") or {}).get("runs"),
                  copies_left(root)), (True, PBC.sha256(original), len(lines), []))
        # E20: a file that is not Python gets mtime "now" - the author's next build rebuilds it
        check(f"{label} E20: the restored file's mtime is NOW, not the old one", target.stat().st_mtime_ns > old + 10 ** 15)
        evidence = (task_of(root) / record["evidence_ref"]) if record.get("evidence_ref") else None
        summary = json.loads(evidence.read_text(encoding="utf-8")) if evidence and evidence.suffix == ".json" else {}
        check(f"{label}: the runner saw the MUTATED bytes", summary.get("stub_hit") is True and summary.get("stub_seen_sha256") != PBC.sha256(original))
        # old: the one request `record["request"]` (None on the walk) -> one request per run, `work/probe-requests/probe-walk-<iid>-<n>.json`
        requests = [json.loads((task_of(root) / "work" / "probe-requests" / f"probe-walk-{spec['iid']}-{n}.json").read_text(encoding="utf-8"))
                    for n in range(1, len(lines) + 1)]
        check_eq(f"{label} R7: every request is for the whole case, never a node id", [(r.get("purpose"), r.get("selected_instance_ids")) for r in requests],
                 [("red_probe", [spec["iid"]])] * len(lines))
        check_eq(f"{label} R7: with the manifest's own selector arguments", [r["command"]["selector_args"] for r in requests],
                 [{spec["iid"]: spec["selector_args"]}] * len(lines))
        check_eq(f"{label}: the requests are built by this tool", [(r.get("built_by") or {}).get("tool") for r in requests],
                 ["probe_by_code.py"] * len(lines))
        # the receipt, the publish and the window
        receipt = record.get("receipt") or {}
        check(f"{label} K1a: the live receipt is written and on disk", bool(receipt.get("path")) and (task_of(root) / receipt["path"]).is_file(), str(record.get("receipt_missing")))
        check_eq(f"{label} K1a: and published", (record.get("publish") or {}).get("published"), True)
        manifest = json.loads((task_of(root) / "work" / "automation-manifest.json").read_text(encoding="utf-8"))
        row = next(t for t in manifest["tests"] if t["instance_id"] == spec["iid"])
        check_eq(f"{label} K1a: the contract takes the receipt unchanged", C.sensitivity_proof_issues(row, task_of(root)), [])
        on_disk = task_of(root) / str(receipt.get("path") or "no-receipt")
        check_eq(f"{label} K1a: the receipt's bytes are the raw sha of the file the probe measured",
                 json.loads(on_disk.read_text(encoding="utf-8")).get("test_content_hash") if on_disk.is_file() else None, PBC.sha256(original))
        check_eq(f"{label} K1a: the window built from the record has no gap", window_gaps(root, record, spec["iid"]), [])
        broken = dict(record["window_probe"], verdict="incomplete")
        item_gaps = window_gaps(root, dict(record, window_probe=broken), spec["iid"])
        check(f"{label}: an `incomplete` probe in a window is a gap (the critic's 'could not verify')",
              any(g.startswith("sensitivity:") for g in item_gaps), str(item_gaps))
        # M1's reading (L5): the window binds by the raw file sha: same_test is `raw`, and the row has a trace binding
        identity = PL.instance_identity(row, task_of(root), root)
        # typescript is read by `test_source` since EP1-37 (B-3): its identity is MEASURED once a typed run selected the test, so
        # its `why` is "" there; C# and Java stay unmeasured
        check(f"{label} M1: the identity of a non-pytest instance is unmeasured, so the raw rule applies (why is one of the two)",
              identity.get("why") in (PL.WHY_NO_REQUEST, PL.WHY_UNMEASURED)
              or (lang == "typescript" and identity.get("why") == "" and bool(identity.get("instance_identity"))),
              f"{identity.get('why')!r} {sorted(identity.get('instance_identity') or {})}")
        check_eq(f"{label} M1: input_hash is the raw sha256 of the file", identity.get("input_hash"), PBC.sha256(original))
        check_eq(f"{label} M1: same_test says `raw` for the probe's record and the window's item",
                 PL.same_test(PL.proof_identity({"input_hash": PBC.sha256(original)}), PL.proof_identity({"input_hash": PBC.sha256(original)})), "raw")
        check_eq(f"{label} M1 (E24): the row has a trace_binding.test_content_sha", bool((row.get("trace_binding") or {}).get("test_content_sha")), True)
        check_eq(f"{label}: the record on disk is the one returned",
                 json.loads((task_of(root) / "work" / "probes" / f"{spec['iid']}.json").read_text(encoding="utf-8")).get("verdict"),
                 "intended_failure")
        # K2/E13: the same test, a pass through the launcher
        proc, got = lrun(root, stub, node_of(lang), spec["iid"], stub_cfg(lang, "pass_anyway"))
        # PRODUCT QUESTION 1 (t-2064-p4b2t2-report.md): a repeat answers the aggregate, not `already_probed`
        check_eq(f"{label}: a second probe of the same bytes is answered, not run (PRODUCT QUESTION 1)", got.get("verdict"), "already_probed")
        # t-2064 TR2-14 (B3): the second call is answered `already_probed` (the repeat on the same bytes and the same model launches nothing), and the
        # proved verdict stands on disk: the pass of the stub did not unprove it
        check_eq(f"{label}: the second call keeps the proved verdict (answered `already_probed`), a pass does not unprove it",
                 (got.get("verdict"), json.loads((task_of(root) / "work" / "probes" / f"{spec['iid']}.json").read_text(encoding="utf-8")).get("verdict")),
                 ("already_probed", "intended_failure"))
    finally:
        cleanup(root)
        cleanup_beside(root)

    # K2 / E13 / E14: the dead check, through the launcher that builds by default
    root = lang_project(lang)
    try:
        original = (root / spec["file"]).read_bytes()
        proc, record = lrun(root, stub, node_of(lang), spec["iid"], stub_cfg(lang, "pass_anyway"))
        check_eq(f"{label} K2: a passed row after a verified mutation is no_failure, exit 0", (proc.returncode, record.get("verdict")), (0, "no_failure"))
        check_eq(f"{label}: the bytes are back, no receipt, nothing published", ((root / spec["file"]).read_bytes() == original,
                                                                                record.get("receipt"), record.get("publish")), (True, None, None))
        # t-2064 P4b (old -> new): the notes of the one record -> the note of each CHECK row (the aggregate's `notes` hold the command notes only),
        # and the residual of `observed` -> `observed` of each check's own record
        check_rows = [r.get("note", "") for r in record.get("checks") or []]
        if LANGS[lang]["argv"][0] in ("dotnet", "mvn"):
            check_eq(f"{label}: every check's note names the launcher that builds by default",
                     ["the launcher builds by default" in n for n in check_rows], [True] * len(check_markers(lang)))
        else:
            check_in(f"{label}: not compiled - the residual risk is said in `observed`", "compiled output",
                     (read_check_record(root, spec["iid"]).get("observed") or {}).get("residual", ""))
    finally:
        cleanup(root)
        cleanup_beside(root)
    # F9: the same pass through a wrapper launcher: incomplete for a compiled language, still no_failure for TS
    root = lang_project(lang, argv=["bash", "run-tests.sh", "{report_path}"])
    try:
        proc, record = lrun(root, stub, node_of(lang), spec["iid"], stub_cfg(lang, "pass_anyway"))
        wanted = "no_failure" if lang == "typescript" else "incomplete"
        check_eq(f"{label} F9: a pass through a wrapper launcher gives {wanted}", (record.get("verdict"), proc.returncode),
                 (wanted, 0 if wanted == "no_failure" else 1))
        if wanted == "incomplete":
            check_in(f"{label} F9: and says the launcher may not rebuild", "may never have reached the build",
                     " ".join(r.get("note", "") for r in record.get("checks") or []))   # t-2064 P4b: the note is on the check rows
    finally:
        cleanup(root)
        cleanup_beside(root)


def one_check_data(lang: str) -> bytes:
    """The language's fixture with the body's EXTRA checks cut off (t-2064 P4b: the walk runs every check of a body, and the fixture's C# `Adds`
    has two). A section that pins the reading of ONE failing row takes this data: a plan of one check, so the call's verdict is that row's."""
    spec = LANGS[lang]
    data = (FIX / spec["fixture"]).read_bytes()
    first = first_line(lang, data)
    cut = {first + offset for offset, _text, _marker in spec.get("also", [])}
    return b"".join(ln for n, ln in enumerate(data.splitlines(keepends=True), 1) if n not in cut)


def said(record: dict) -> str:
    """Everything the aggregate says in words: its notes and the note of each check row (t-2064 P4b: the old record's `notes` were both)."""
    return " ".join(list(record.get("notes") or []) + [str(r.get("note") or "") for r in record.get("checks") or []])


def r8_through_the_cli(stub: Path) -> None:
    """Every mode of the runner at the CLI level, for the language whose frames are the least forgiving."""
    for lang in ("csharp", "java", "typescript"):
        spec = LANGS[lang]
        for mode, verdict, exit_code, needle in (
                ("lib_frames_first", "intended_failure", 0, ""),
                ("wrong_line", "incomplete", 1, "the code critic judges it"),     # N3b: a failure elsewhere with no token is judgment
                ("error_row", "incomplete", 1, "the run's row is an error"),
                ("no_frames", "incomplete", 1, "the code critic judges it"),     # N4: a row with text and no readable place is the critic's
                ("drifted_message", "incomplete", 1, "the factory cannot read its text; the code critic judges it"),
                ("no_row", "not_executed", 1, "no row of the"),
                ("two_rows", "not_executed", 1, "ambiguous"),
                ("skipped_row", "not_executed", 1, "report status")):
            if lang != "csharp" and mode in ("no_row", "two_rows", "skipped_row"):
                continue
            # N3b: only a row holding the token is proved by the code. Java's form takes a marker (the stub prints it), so a row of any
            # shape and place is proved there; the csharp xunit and the typescript `toBe` forms take none, so the same run is judgment
            if lang == "java":
                if mode == "no_frames":
                    verdict, exit_code, needle = "intended_failure", 0, ""     # the marker outranks the place (step 1 before step 3)
            elif mode == "lib_frames_first":
                verdict, exit_code = "incomplete", 1
            if mode == "drifted_message":
                needle = "the code critic judges it"
            # t-2064 P4b: the walk runs EVERY check of a body; the section pins the reading of ONE failing row, so it takes the body with one
            # check (`one_check_data`: the fixture's second C# assertion cut) and the call's verdict is that row's
            root = lang_project(lang, data=one_check_data(lang))
            try:
                original = (root / spec["file"]).read_bytes()
                proc, record = lrun(root, stub, node_of(lang), spec["iid"], stub_cfg(lang, mode))
                # PRODUCT QUESTION 8 (t-2064-p4b2t3-report.md): a report with NO row of the test: the walk's row note says "report status None",
                # the old "no row of the ... report" is gone, and the verdict stays not_executed. PRODUCT QUESTION 9: a report with TWO rows of the
                # test is read as ONE failed row (`incomplete`, judgment) where the old road said `not_executed`, "ambiguous". Both pins stay RED
                question = {"no_row": " (PRODUCT QUESTION 8)", "two_rows": " (PRODUCT QUESTION 9)"}.get(mode, "")
                label = f"{lang} {mode}"
                red = question if lang == "csharp" else ""    # the question's pins are the verdict and the note, on the csharp rows only
                check_eq(f"{label}: {verdict}, exit {exit_code}{red if mode == 'two_rows' else ''}", (record.get("verdict"), proc.returncode),
                         (verdict, exit_code))
                check_eq(f"{label}: the bytes are back and no copy is left", ((root / spec["file"]).read_bytes() == original, copies_left(root)),
                         (True, []))
                if needle:
                    check_in(f"{label}: the note says why{red if mode in ('no_row', 'two_rows') else ''}", needle, said(record))   # old: the record's notes; new: the notes and the check row's note
                if verdict != "intended_failure":
                    check_eq(f"{label}: no receipt, nothing published", (record.get("receipt"), record.get("publish")), (None, None))
                if verdict == "incomplete":
                    check_eq(f"{label}: a verdict on the test is never claimed (no mismatches list)",
                             record.get("mismatches"), None)
                if mode == "wrong_line":
                    # t-2064 P4b (old -> new): `judgment_facts.location` / `.location_hit` of the one record -> `observed.location` of the check's own
                    # record, and "the place is not the check's" = that location differs from the check's key (no `location_hit` field is carried)
                    seen = read_check_record(root, spec["iid"]).get("observed") or {}
                    check_eq(f"{label}: the place is a fact for the critic, not a verdict", (record.get("cause"), record.get("actual_location"),
                             seen.get("location"), seen.get("location") == f"{spec['file']}:{first_line(lang)}"),
                             ("judgment", None, f"{spec['file']}:{first_line(lang) + 3}", False))
                if mode == "error_row":
                    check_eq(f"{label}: the error row is never wrong_location", record.get("actual_location"), None)
            finally:
                cleanup(root)
                cleanup_beside(root)


def a_standing_record_survives_incomplete(stub: Path) -> None:
    """E23 / K6: a stored intended_failure is kept when a later probe of other bytes is `incomplete`."""
    lang = "csharp"
    spec = LANGS[lang]
    root = lang_project(lang)
    try:
        path = task_of(root) / "work" / "probes" / f"{spec['iid']}.json"
        standing = {"schema_version": 1, "verdict": "intended_failure", "instance_id": spec["iid"], "test_file_sha256": "f" * 64,
                    "recorded_at": "2026-09-30T05:02:39+00:00", "publish": {"published": False}, "receipt": None}
        write_json(path, standing)
        proc, record = lrun(root, stub, node_of(lang), spec["iid"], stub_cfg(lang, "drifted_message"))
        kept = json.loads(path.read_text(encoding="utf-8"))
        check_eq("E23: the run is incomplete", (record.get("verdict"), proc.returncode), ("incomplete", 1))
        check_eq("E23: the stored verdict is still intended_failure", kept.get("verdict"), "intended_failure")
        check_eq("E23: every other stored key is as it was", {k: v for k, v in kept.items() if k != "last_attempt"}, standing)
        # PRODUCT QUESTION 10 (t-2064-p4b2t3-report.md): the standing record's `last_attempt.why` is the aggregate's FIRST NOTE (the command note
        # "command, fingerprint file list and runtime probe are those of this story's last typed run"), not the check row's reason: the cause
        # ("the code critic judges it") is lost from it. The pin stays RED
        check_eq("E23: last_attempt names incomplete and the cause (PRODUCT QUESTION 10)", ((kept.get("last_attempt") or {}).get("verdict"),
                                                                       "the code critic judges it" in str((kept.get("last_attempt") or {}).get("why"))),
                 ("incomplete", True))
        proc, record = lrun(root, stub, node_of(lang), spec["iid"], stub_cfg(lang, "pass_anyway"))
        check_eq("E23: an executed no_failure replaces it as before", (record.get("verdict"),
                 json.loads(path.read_text(encoding="utf-8")).get("verdict")), ("no_failure", "no_failure"))
    finally:
        cleanup(root)
        cleanup_beside(root)


def bom_and_crlf_through_the_run(stub: Path) -> None:
    """E21: a BOM and CRLF line ends - built at runtime (B-409) - reach the run's runner unchanged but for the
    statement, and come back byte for byte."""
    lang = "csharp"
    spec = LANGS[lang]
    # t-2064 P4b: the body with ONE check (`one_check_data`): the walk runs every check, and this case pins the line the one failing run reached
    base = one_check_data(lang)
    for label, data in (("a BOM and CRLF", b"\xef\xbb\xbf" + base.replace(b"\n", b"\r\n")),
                        ("CRLF alone", base.replace(b"\n", b"\r\n")),
                        ("a BOM alone", b"\xef\xbb\xbf" + base)):
        root = lang_project(lang, data=data)
        try:
            line = first_line(lang, data)
            proc, record = lrun(root, stub, node_of(lang), spec["iid"], stub_cfg(lang, line=line))
            # N3b: the csharp xunit form takes no marker, so the run is judgment, not proved; what is pinned is the line and the bytes
            # t-2064 P4b (old -> new): `expected_location` of the one failing record (the aggregate of an unproved check carries none) -> the check
            # row's key and the place its own record says the run failed at: the run reached the right line
            row_key = ((record.get("checks") or [{}])[0]).get("key")
            reached = (read_check_record(root, spec["iid"]).get("observed") or {}).get("location")
            check_eq(f"E21 ({label}): the run reached the right line (judgment: no token in this form)", (record.get("verdict"), row_key, reached),
                     ("incomplete", f"{spec['file']}:{line}", f"{spec['file']}:{line}"))
            check_eq(f"E21 ({label}): the bytes are identical afterwards", (root / spec["file"]).read_bytes(), data)
            evidence = task_of(root) / record["evidence_ref"]
            summary = json.loads(evidence.read_text(encoding="utf-8")) if evidence.suffix == ".json" else {}
            check_eq(f"E21 ({label}): the runner saw the BOM kept", summary.get("stub_seen_prefix") == "efbbbf", data.startswith(b"\xef\xbb\xbf"))
            check_eq(f"E21 ({label}): and every CRLF kept", summary.get("stub_seen_crlf"), data.count(b"\r\n"))
        finally:
            cleanup(root)
            cleanup_beside(root)
    root = lang_project(lang, data=b"namespace A { class T { void Adds() { Assert.Equal(1, \xff); } } }\n")
    try:
        before = tree_state(root)
        proc, payload = lrun(root, stub, node_of(lang), spec["iid"], stub_cfg(lang))
        refused("E21: a file that is not UTF-8", proc, payload, "is not UTF-8")
        check_eq("E21: and the tree is unchanged", tree_state(root), before)
    finally:
        cleanup(root)
        cleanup_beside(root)


TWO = (b"namespace Acme.Tests\n{\n    public class CalcTests\n    {\n        public void Adds()\n        {\n"
       b"            Assert.Equal(4, Calc.Add(2, 2));\n        }\n    }\n\n    public class MoreTests\n    {\n"
       b"        public void Adds()\n        {\n            Assert.Equal(6, Calc.Add(3, 3));\n        }\n    }\n}\n")


def at_among_two_declarations(stub: Path) -> None:
    """E3 / E5 / A5: a name declared twice is refused without --at; with --at, an `intended_failure` is
    attributable (the run failed at that very line), but a pass among two candidates is `incomplete`."""
    lang = "csharp"
    spec = LANGS[lang]
    root = lang_project(lang, data=TWO)
    try:
        before = tree_state(root)
        proc, payload = lrun(root, stub, node_of(lang), spec["iid"], stub_cfg(lang, line=7, after="Assert.NotEqual(4, Calc.Add(2, 2));"))
        # t-2064 P4b: a name declared twice has no located body, so the plan is EMPTY and the plain call is the empty-plan refusal, whose door is
        # `--at <file>:<line>`; it no longer counts the declarations nor names their lines (the old "declared 2 times ... line 5, line 13")
        refused("E3 (two declarations, no --at)", proc, payload, "no check of a form the factory reads was found", "--at <file>:<line>",
                "Nothing was changed")
        check_eq("E3: the tree is unchanged", tree_state(root), before)
        proc, record = lrun(root, stub, node_of(lang), spec["iid"], stub_cfg(lang, line=15, after="Assert.NotEqual(6, Calc.Add(3, 3));"), "--at", "15")
        # t-2064 P4b: `--at 15` is a plan of the ONE row `<file>:15` (its entry written by `lrun`); the aggregate names that row: its verdict is
        # judgment (no token in the xunit form, N3b) and the call's verdict is `incomplete`. The aggregate keeps the selected key, not `--at`
        # and the candidates [5, 13] (a replay reads the key; the old `mutation_detail.at/candidates` are not in the aggregate).
        rows = record.get("checks") or [{}]
        check_eq("--at 15 picks the second body: judgment (no token in the xunit form, N3b) at line 15",
                 (record.get("verdict"), rows[0].get("key"), rows[0].get("verdict"), rows[0].get("cause")),
                 ("incomplete", f"{spec['file']}:15", "incomplete", "judgment"))
        detail = record.get("mutation_detail") or {}
        check_eq("the record keeps the selected check (what a replay needs)", (detail.get("checks"), len(rows)), ([f"{spec['file']}:15"], 1))
    finally:
        cleanup(root)
        cleanup_beside(root)
    root = lang_project(lang, data=TWO)
    try:
        proc, record = lrun(root, stub, node_of(lang), spec["iid"], stub_cfg(lang, "pass_anyway", line=15, after="x"), "--at", "15")
        # t-2064 P4b: the first two A5 pins below are the old record's and stay RED, unbent - PRODUCT QUESTION 4 of t-2064-p4b2t2-report.md: on the
        # walk road a pass of the run when `--at` names one of TWO declarations of the name answers `no_failure` (exit 0, a survivor of the
        # selected row) with no note that the pass cannot say which body ran; the old road said `incomplete` (exit 1) and why
        check_eq("A5: a pass among two candidates is incomplete, never no_failure (PRODUCT QUESTION 4)", (record.get("verdict"), proc.returncode), ("incomplete", 1))
        check_in("A5: the note says a pass does not tell which body ran (PRODUCT QUESTION 4)", "does not say which body ran", said(record))   # TR2-14 (B2): the E5 note is on the check row
        # the one-declaration control: the same pass IS a no_failure
        proc, record = lrun(root, stub, node_of(lang), spec["iid"], stub_cfg(lang, "pass_anyway", line=7, after="x"), "--at", "7")
        check_eq("A5: --at among two candidates again (first body): still incomplete", record.get("verdict"), "incomplete")
    finally:
        cleanup(root)
        cleanup_beside(root)
    root = lang_project("csharp")
    try:
        proc, record = lrun(root, stub, node_of("csharp"), "Adds", stub_cfg("csharp", "pass_anyway"), "--at", str(first_line("csharp")))
        check_eq("A5 control: --at on a name declared ONCE does not make a pass incomplete", record.get("verdict"), "no_failure")
    finally:
        cleanup(root)
        cleanup_beside(root)


def refusals_before_the_write(stub: Path) -> None:
    """K5: every refusal of R6, E10, E12, E14, E22: exit 2, and the tree byte-identical (files and mtimes)."""
    lang = "csharp"
    spec = LANGS[lang]

    def extra(n: int, **fields) -> list:
        return [{"case": f"TC-{200 + i}", "covers": [f"TC-{200 + i}"], "file": spec["file"], "test": f"T{i}", "instance_id": f"T{i}",
                 "selector": f"CalcTests.T{i}", **fields} for i in range(n)]

    # R6 (a): the whole case runs - every row of THIS case must carry its selector and report id. Rows of the
    # same case: the case id is shared with the instance under probe.
    for count in (4, 5, 6, 8):
        rows = [dict(r, case="TC-100", covers=["TC-100"]) for r in extra(count, selector_args=["x"], report_test_id="")]
        root = lang_project(lang, extra_entries=rows)
        try:
            before = tree_state_with_entries(root, stub, node_of(lang), spec["iid"])
            proc, payload = lrun(root, stub, node_of(lang), spec["iid"], stub_cfg(lang))
            text = refused(f"R6 a ({count} offending rows)", proc, payload, "no selector of their own", "manifest_put.py --task",
                           "--fragment", "selector_args", "report_test_id")
            # t-2064 P4b, PRODUCT QUESTION 5 of t-2064-p4b2t2-report.md: the R6 (a) refusal is not what the walk road answers (exit 1, no
            # refusal text) - every R6 (a) pin stays red and unbent; the split below is guarded so the rest of the section still runs
            listed = (text.split("no selector of their own:")[1].split(". A non-pytest")[0]
                      if "no selector of their own:" in text else "")
            check_in(f"R6 a ({count} rows): the count of offenders is told", f"{count} instance(s)", text)
            check_eq(f"R6 a ({count} rows with no report_test_id): at most 5 are listed",
                     len(re.findall(r"T\d+ \(no `", listed)), min(count, 5))
            check_eq(f"R6 a ({count} rows): 'and N more' only beyond the cap of 5, with the right N",
                     re.search(r"and (\d+) more", listed).group(1) if "more" in listed else "", "" if count <= 5 else str(count - 5))
            check_eq(f"R6 a ({count} rows): the tree is unchanged", tree_state(root), before)
            check_eq(f"R6 a ({count} rows): and the refusal of the tool left its `refused: tool` record", refusal_record_of(root, spec["iid"]),
                     ("tool", "not_executed"))
        finally:
            cleanup(root)
            cleanup_beside(root)
    rows = [{"case": "TC-100", "covers": ["TC-100"], "file": "tests/Bare.cs"}]
    root = lang_project(lang, extra_entries=rows)
    try:
        before = tree_state_with_entries(root, stub, node_of(lang), spec["iid"])
        proc, payload = lrun(root, stub, node_of(lang), spec["iid"], stub_cfg(lang))
        refused("R6 a (a bare file of the case)", proc, payload, "tests/Bare.cs (names no test)")
        check_eq("R6 a (a bare file): the tree is unchanged", tree_state(root), before)
        check_eq("R6 a (a bare file): and the refusal of the tool left its `refused: tool` record", refusal_record_of(root, spec["iid"]),
                 ("tool", "not_executed"))
    finally:
        cleanup(root)
        cleanup_beside(root)
    root = lang_project(lang, verified=False)
    try:
        before = tree_state_with_entries(root, stub, node_of(lang), spec["iid"])
        proc, payload = lrun(root, stub, node_of(lang), spec["iid"], stub_cfg(lang))
        refused("R6 a (selectors.verified is false)", proc, payload, "selector contract is verified", "selectors.verified")
        check_eq("R6 a (not verified): the tree is unchanged", tree_state(root), before)
        check_eq("R6 a (not verified): and the refusal of the tool left its `refused: tool` record", refusal_record_of(root, spec["iid"]),
                 ("tool", "not_executed"))
    finally:
        cleanup(root)
        cleanup_beside(root)
    # R6 (b): --test names another file than the manifest row
    two_tests = (FIX / spec["fixture"]).read_bytes().replace(
        b"        [Fact]\n        public void Throws()", b"        [Fact]\n        public void Other()\n        {\n            Assert.Equal(1, 1);\n        }\n\n"
        b"        [Fact]\n        public void Throws()")
    root = lang_project(lang, data=two_tests, files={"tests/Other.cs": two_tests})
    try:
        before = tree_state_with_entries(root, stub, "tests/Other.cs::CalcTests.Adds", spec["iid"])
        proc, payload = lrun(root, stub, "tests/Other.cs::CalcTests.Adds", spec["iid"], stub_cfg(lang))
        refused("R6 b (another file than the manifest row's)", proc, payload, "the manifest row of 'Adds' names tests/CalcTests.cs")
        check_eq("R6 b: the tree is unchanged", tree_state(root), before)
        # R6 (c): the report id does not end with the tail (its own model file is written first: the entries are those of THIS node)
        before = tree_state_with_entries(root, stub, "tests/CalcTests.cs::CalcTests.Other", spec["iid"])
        proc, payload = lrun(root, stub, "tests/CalcTests.cs::CalcTests.Other", spec["iid"], stub_cfg(lang))
        text = refused("R6 c (the tail is another test than the report id)", proc, payload, "does not end with 'CalcTests.Other'",
                       "manifest_put.py --fragment")
        check_not_in("R6 c: no DisplayName words for a C# test", "display name", text)
        check_eq("R6 c: the tree is unchanged", tree_state(root), before)
    finally:
        cleanup(root)
        cleanup_beside(root)
    # R6 (c), Java: a @DisplayName before the declaration adds the words about the runner's id for the method
    java = (FIX / "CalcTest.java").read_bytes().replace(b"    @Test\n    void adds()", b'    @Test\n    @DisplayName("adds two numbers")\n    void adds()')
    root = lang_project("java", data=java, entry_extra={"report_test_id": "com.acme.CalcTest::adds two numbers"})
    try:
        before = tree_state_with_entries(root, stub, node_of("java"), "adds")
        proc, payload = lrun(root, stub, node_of("java"), "adds", stub_cfg("java"))
        refused("R6 c (surefire reports a @DisplayName)", proc, payload, "does not end with 'CalcTest.adds'",
                "and the report may name this test by it", "must be the runner's id for the method")
        check_eq("R6 c (DisplayName): the tree is unchanged", tree_state(root), before)
        # control: the same id with no DisplayName on the declaration does not carry the DisplayName words
        proc, payload = lrun(root, stub, "src/test/java/com/acme/CalcTest.java::CalcTest.assertjAdds", "adds", stub_cfg("java"))
        text = refused("R6 c (no DisplayName on the declaration)", proc, payload, "does not end with")
        check_not_in("R6 c control: no display name words", "display name", text)
    finally:
        cleanup(root)
        cleanup_beside(root)
    # R6 (d): a compiled entry whose one-test command forbids the rebuild
    for token in ("--no-build",):
        root = lang_project(lang, argv=["dotnet", "test", token, "--logger", "trx;LogFileName={report_path}"])
        try:
            before = tree_state_with_entries(root, stub, node_of(lang), spec["iid"])
            proc, payload = lrun(root, stub, node_of(lang), spec["iid"], stub_cfg(lang))
            refused(f"R6 d ({token} in the profile's command)", proc, payload, token, "stops the csharp build")
            check_eq(f"R6 d ({token}): the tree is unchanged", tree_state(root), before)
        finally:
            cleanup(root)
            cleanup_beside(root)
    root = lang_project("java", argv=["mvn", "surefire:test", "-Dsurefire.reportsFile={report_path}"])
    try:
        proc, payload = lrun(root, stub, node_of("java"), "adds", stub_cfg("java"))
        refused("R6 d (surefire:test)", proc, payload, "surefire:test", "stops the java build")
    finally:
        cleanup(root)
        cleanup_beside(root)
    root = lang_project("typescript", argv=["npx", "jest", "--no-build", "--outputFile={report_path}"])
    try:
        proc, payload = lrun(root, stub, node_of("typescript"), "adds", stub_cfg("typescript"))
        check_eq("R6 d: TypeScript is not compiled - a `--no-build` token is not a refusal there", proc.returncode == 2, False)
    finally:
        cleanup(root)
        cleanup_beside(root)
    # E22: --mutation expected on a test that is not Python
    root = lang_project(lang)
    try:
        before = tree_state(root)
        proc = run_script("probe_by_code.py", "--task", TASK, "--dispatch", DISPATCH, "--test", node_of(lang), "--instance",
                          spec["iid"], "--mutation", "expected", "--json", cwd=root, env=env_for(root, stub, LANG_STUB=json.dumps(stub_cfg(lang))))
        payload = json.loads(proc.stdout) if proc.stdout.strip().startswith("{") else {}
        refused("E22 (--mutation expected)", proc, payload, "--mutation expected was removed", "an `invert` entry for the check in the model file")
        check_eq("E22: the tree is unchanged", tree_state(root), before)
    finally:
        cleanup(root)
        cleanup_beside(root)
    # E6 / E7 through the CLI: no assertion, an invert-null first assertion
    root = lang_project(lang, data=b"namespace A\n{\n  class CalcTests\n  {\n    public void Adds()\n    {\n      Helpers.Expect(4);\n    }\n  }\n}\n")
    try:
        before = tree_state(root)
        proc, payload = lrun(root, stub, node_of(lang), spec["iid"], stub_cfg(lang))
        # t-2064 P4b: a body with no check is an EMPTY plan - the refusal of the plain call, whose door is `--at <file>:<line>` (it no longer
        # names `--oracle`, nor "no recognised assertion")
        refused("E6 (no recognised assertion)", proc, payload, "no check of a form the factory reads was found", "--at <file>:<line>")
        check_eq("E6: the tree is unchanged", tree_state(root), before)
    finally:
        cleanup(root)
        cleanup_beside(root)
    root = lang_project(lang)
    try:
        write_entries(root, [f"{spec['file']}:14"])     # the entry of the selected key, written before the snapshot: the refusal that follows writes nothing
        before = tree_state(root)
        proc, payload = lrun(root, stub, "tests/CalcTests.cs::CalcTests.Adds", spec["iid"], stub_cfg(lang, "pass_anyway"),
                             "--at", "14")
        refused("E5/E7 (--at on a line that starts no assertion)", proc, payload, "line 14 of tests/CalcTests.cs holds no check of a form the factory reads")
        check_eq("E7: the tree is unchanged", tree_state(root), before)
    finally:
        cleanup(root)
        cleanup_beside(root)


def traps_through_the_cli(stub: Path) -> None:
    """The critic's t-551 findings F1 and F2 as a role meets them: each input is refused before any write (exit 2,
    the author's file byte-identical, no copy made), never planned onto a string or onto an inactive branch, and
    never run - a false `no_failure` against the author is the dangerous direction."""
    ts_trap = ("describe('c', () => {\n  test('adds', () => {\n    const t = <b>don't</b>;\n"
               "    const label = 'expect(a).toBe(1)'; // don't\n    expect(sum(1, 2)).toBe(3);\n  });\n});\n").encode()
    ts_unclosed = ("describe('c', () => {\n  test('adds', () => {\n    const r = /abc\n    expect(sum(1, 2)).toBe(3);\n"
                   "  });\n});\n").encode()
    cs_if = (b"namespace Acme.Tests\n{\n  public class CalcTests\n  {\n    public void Adds()\n    {\n#if NET6\n"
             b"      Assert.Equal(4, Calc.Add(2, 2));\n#else\n      Assert.Equal(5, Calc.Add(2, 2));\n#endif\n    }\n  }\n}\n")
    ts_two = ("describe('calc', () => {\n  test('adds', () => {\n    expect(sum(1, 2)).toBe(3);\n  });\n"
              "  test('does not adds', () => {\n    expect(sum(1, 2)).toBe(3);\n  });\n});\n").encode()
    for lang, label, data, extra, needles in (
            ("typescript", "F1 (i): an apostrophe in JSX text", ts_trap, None,
             ("single-line string that crosses a line break", "opens at line 3")),
            ("typescript", "F1b (vi): an unterminated regex literal", ts_unclosed, None,
             ("regex literal that opens at line 3 and does not close on its line",)),
            # PRODUCT QUESTION 11 (t-2064-p4b2t3-report.md): `_refuse_conditional_compilation` is called by `_located` (probe_by_code.py:5066), whose
            # ToolRefusal the walk catches PER CHECK: the plan lists both branches (lines 8 and 10), both rows are `incomplete`, cause `tooling`, exit 1,
            # and the walk has written (copy, requests, record) - where plan_detector_mutation (:1962) refused before any write. PRODUCT QUESTION 12:
            # `run_shape_checks` (:2770, the longer-title refusal) is not on the walk road: the test is walked and its row is `not_executed`. Both red
            ("csharp", "F1 (ii): #if/#else/#endif (PRODUCT QUESTION 11)", cs_if, None, ("conditional-compilation directive `#if NET6` at line 7",)),
            ("typescript", "F2: the id of another test with a longer title (PRODUCT QUESTION 12)", ts_two,
             {"report_test_id": "calc does not adds::calc does not adds"},
             ("also ends with the longer title 'does not adds'", "declared at line 5"))):
        spec = LANGS[lang]
        root = lang_project(lang, data=data, entry_extra=extra)
        try:
            before = tree_state_with_entries(root, stub, node_of(lang), spec["iid"])   # TR2-14: after the window's model file `lrun` writes
            proc, payload = lrun(root, stub, node_of(lang), spec["iid"], stub_cfg(lang))
            refused(label, proc, payload, *needles)
            check_eq(f"{label}: the author's file is byte-identical and the tree unchanged",
                     ((root / spec["file"]).read_bytes() == data, tree_state(root) == before), (True, True))
            # the lexer cannot read the file: the TOOL's refusal leaves its one record (`refused: tool`), no other
            # (t-2167 F4: the conditional-compilation refusal is a ToolRefusal too, so it leaves its record)
            lexer = label.startswith(("F1 (i)", "F1b (vi)", "F1 (ii)"))   # the lexer's refusals (a record of the tool); F2 is the id's, and leaves none
            check_eq(f"{label}: no copy was made, no runner launched, and a record only for a refusal of the tool",
                     (copies_left(root), (task_of(root) / "work" / "probes").is_dir(), (task_of(root) / "evidence").is_dir()),
                     ([], lexer, False))
            if label.startswith(("F1 (i)", "F1b (vi)", "F1 (ii)")):
                # TR2-14: `tree_state` leaves the `refused: tool` record out of "unchanged"; this is the positive pin that the record exists
                # and says so (one record, the refusal's own: the instance, `refused: tool`, `not_executed`)
                found = [json.loads(p.read_text(encoding="utf-8")) for p in sorted((task_of(root) / "work" / "probes").glob("*.json"))]
                check_eq(f"{label}: the refusal left the one `refused: tool` record",
                         [(r.get("instance_id"), r.get("refused"), r.get("verdict")) for r in found], [(spec["iid"], "tool", "not_executed")])
        finally:
            cleanup(root)
            cleanup_beside(root)
    # control: the same TS file with the right report id plans and runs (the refusal is the id's, not the file's)
    root = lang_project("typescript", data=ts_two)
    try:
        proc, record = lrun(root, stub, node_of("typescript"), "adds", stub_cfg("typescript", "pass_anyway", line=3,
                                                                                 after="expect(sum(1, 2)).not.toBe(3);"))
        check_eq("F2 control: the test's own report id is not refused", record.get("verdict"), "no_failure")
    finally:
        cleanup(root)
        cleanup_beside(root)


def oracle_in_a_helper(stub: Path) -> None:
    """The expectation lives in a helper: `--oracle <file>::<name>` names it (E6's door); the helper file must be
    in the test tree and in no protected product path (E10); it is mutated, restored and recorded as the mutated file."""
    lang = "csharp"
    spec = LANGS[lang]
    test_src = (b"namespace Acme.Tests\n{\n    public class CalcTests\n    {\n        public void Adds()\n        {\n"
                b"            Helpers.ExpectSum(2, 2, 4);\n        }\n    }\n}\n")
    helper = (b"namespace Acme.Tests\n{\n    public static class Helpers\n    {\n        public static void ExpectSum(int a, int b, int s)\n"
              b"        {\n            Assert.Equal(s, a + b);\n        }\n    }\n}\n")
    root = lang_project(lang, data=test_src, files={"tests/Helpers.cs": helper, "src/Product.cs": helper})
    try:
        before = tree_state(root)
        node = node_of(lang)
        cfg = stub_cfg(lang, file="tests/Helpers.cs", line=7, after="Assert.NotEqual(s, a + b);", stack=[
            "   at Acme.Tests.Helpers.ExpectSum(Int32 a, Int32 b, Int32 s) in {path}:line {line}"])
        proc, payload = lrun(root, stub, node, spec["iid"], cfg)
        refused("an oracle with no --oracle: the test body asserts nothing", proc, payload, "no check of a form the factory reads was found",
                "--at <file>:<line>")
        # t-2064 P4b: `--oracle <file>::<name>` selects the checks of that function (its row `tests/Helpers.cs:7`), which needs ITS entry
        # (written here: `lrun` writes none for `--oracle`); the record is the aggregate, its row names the helper's line, `mutation_detail`
        # names the file; `oracle_function` and `oracle_note` ("named by hand") are not in it any more (PRODUCT QUESTION 3 of the report)
        write_entries(root, ["tests/Helpers.cs:7"])
        proc, record = lrun(root, stub, node, spec["iid"], cfg, "--oracle", "tests/Helpers.cs::ExpectSum")
        rows = record.get("checks") or [{}]
        check_eq("--oracle: judgment (no token in the xunit form, N3b) at the helper's line", (record.get("verdict"), rows[0].get("key"), rows[0].get("cause")),
                 ("incomplete", "tests/Helpers.cs:7", "judgment"))
        detail = record.get("mutation_detail") or {}
        # RED, unbent - PRODUCT QUESTION 6: `mutation_detail.file` says tests/CalcTests.cs (the test file) while `mutated_file.path` and the row
        # name the helper the check lives in (the same mismatch is noticed in test_probe_by_code.py's oracle_in_a_helper)
        check_eq("--oracle: the record names the file it mutated (PRODUCT QUESTION 6)", (detail.get("file"), (record.get("mutated_file") or {}).get("path")),
                 ("tests/Helpers.cs", "tests/Helpers.cs"))
        check_eq("--oracle: the helper is back byte for byte and the test file was never touched",
                 ((root / "tests" / "Helpers.cs").read_bytes(), (root / spec["file"]).read_bytes()), (helper, test_src))
        check_eq("--oracle: the probe's identity is still the test file's sha", record.get("test_file_sha256"), PBC.sha256(test_src))
        check_eq("--oracle: no copy left", copies_left(root), [])
    finally:
        cleanup(root)
        cleanup_beside(root)
    root = lang_project(lang, data=test_src, files={"tests/Helpers.cs": helper, "src/Product.cs": helper, "tests/notes.txt": b"x"},
                        protected=["tests/app"])
    try:
        node = node_of(lang)
        cfg = stub_cfg(lang)
        for label, oracle, needle in (
                ("E10: a helper outside every test root (the product tree)", "src/Product.cs::ExpectSum", "is not under a test root"),
                ("E10: a helper in no file that exists", "tests/Nope.cs::ExpectSum", "no such file"),
                ("E10: a helper of another language", "tests/notes.txt::ExpectSum", "is not a csharp file")):
            before = tree_state(root)
            proc, payload = lrun(root, stub, node, spec["iid"], cfg, "--oracle", oracle)
            refused(label, proc, payload, needle)
            check_eq(f"{label}: the tree is unchanged", tree_state(root), before)
        (root / "tests" / "app").mkdir()
        (root / "tests" / "app" / "H.cs").write_bytes(helper)
        before = tree_state(root)
        proc, payload = lrun(root, stub, node, spec["iid"], cfg, "--oracle", "tests/app/H.cs::ExpectSum")
        refused("E10: a helper under protected_app_paths", proc, payload, "not under a test root", "protected_app_paths", "red_sandbox.py --probe")
        check_eq("E10 (protected): the tree is unchanged", tree_state(root), before)
        # the helper of the test's own file needs no root check
        proc, payload = lrun(root, stub, node, spec["iid"], cfg, "--oracle", "Nope")
        check_in("a helper name with no file is looked for in the test's own file",
                 "no declaration named `Nope` in tests/CalcTests.cs holds a check of a form the factory reads", payload.get("error", ""))
        check_in("...and a selection that selects nothing is a refusal, never a pass", "Nothing was changed", payload.get("error", ""))
    finally:
        cleanup(root)
        cleanup_beside(root)


def data_gaps(stub: Path) -> None:
    """K3 / K4 / E2: a language with no row, an unreadable table, an absent key and a malformed entry are four
    different refusals that all say 'factory data gap', and none changes the tree."""
    lang = "csharp"
    spec = LANGS[lang]
    root = lang_project(lang)
    scratch = temp_dir("qa-probe-gaps-")
    try:
        before = tree_state(root)
        (root / "tests" / "Calc.kt").write_text("class CalcTests { fun adds() {} }\n", encoding="utf-8")
        before = tree_state(root)
        proc, payload = lrun(root, stub, "tests/Calc.kt::CalcTests.adds", spec["iid"], stub_cfg(lang))
        text = refused("K3 (.kt: no entry)", proc, payload, "no assertion probe for .kt", "factory data gap", '"assertion_probes"',
                       "red_sandbox.py --probe --repo <project root>")
        check_in("K3: the entry shape names the fields a row needs", "fires_as", text)
        check_eq("K3: the tree is byte-identical", tree_state(root), before)
        good = json.loads(Path(AD.DETECTORS_FILE).read_text(encoding="utf-8"))
        cases = {}
        cases["unreadable"] = scratch / "missing.json"
        broken = scratch / "broken.json"
        broken.write_text("{nope", encoding="utf-8")
        cases["not json"] = broken
        absent = scratch / "absent.json"
        absent.write_text(json.dumps({k: v for k, v in good.items() if k != "assertion_probes"}), encoding="utf-8")
        cases["absent key"] = absent
        malformed = scratch / "malformed.json"
        bad = copy.deepcopy(good)
        bad["assertion_probes"]["csharp"]["assertions"][0]["invert"][0]["fires_as"] = "(unclosed"
        malformed.write_text(json.dumps(bad), encoding="utf-8")
        cases["malformed entry"] = malformed
        needles = {"unreadable": "cannot be read", "not json": "cannot be read", "absent key": "has no `assertion_probes` key",
                   "malformed entry": "assertion_probes.csharp.assertions[0].invert[0].fires_as (X1)"}
        model_entries(root, stub, node_of(lang), spec["iid"])   # t-2064 P4b: the wrapper's own file (with the shipped table), before the snapshots
        for label, path in cases.items():
            before = tree_state(root)
            proc, payload = lrun(root, stub, node_of(lang), spec["iid"], stub_cfg(lang), ASSERTION_DETECTORS_FILE=str(path))
            refused(f"K4 ({label})", proc, payload, "factory data gap", needles[label], "red_sandbox.py --probe")
            check_eq(f"K4 ({label}): the tree is unchanged", tree_state(root), before)
        texts = {l: lrun(root, stub, node_of(lang), spec["iid"], stub_cfg(lang), ASSERTION_DETECTORS_FILE=str(p))[1].get("error", "")
                 for l, p in cases.items()}
        check_eq("K4: the unreadable, the absent and the malformed refusals are three different texts",
                 len({texts["unreadable"], texts["absent key"], texts["malformed entry"]}), 3)
        # E2 (temporal): a table that is read again after the data file is repaired - nothing is remembered
        proc, record = lrun(root, stub, node_of(lang), spec["iid"], stub_cfg(lang))
        check_eq("E2: with the shipped table back, the probe runs (judgment: no token in the xunit form, N3b)", record.get("verdict"), "incomplete")
    finally:
        cleanup(root)
        cleanup_beside(root)
        cleanup(scratch)


def kill_and_recover(stub: Path) -> None:
    """E18 / E20 on the detector path: a probe killed while its file is mutated leaves the way back on disk; the
    next probe puts the author's bytes back (mtime NOW for a file that is not Python) and goes on."""
    lang = "csharp"
    spec = LANGS[lang]
    root = lang_project(lang, mtime_ns=OLD_NS)
    try:
        target = root / spec["file"]
        original = target.read_bytes()
        proc, payload = lrun(root, stub, node_of(lang), spec["iid"], stub_cfg(lang, "kill_holding_lock"))
        check("killed: the probe died (no JSON answer)", proc.returncode != 0 and not payload, proc.stdout[-200:] + proc.stderr[-200:])
        left = target.read_bytes()
        check("killed: the file was left MUTATED", left != original and spec["after"].encode() in left)
        folder = root / "qa-factory" / "state" / "probe-copies"
        check_eq("killed: a copy and its record are on disk", sorted(p.suffix for p in folder.glob("*") if p.suffix != ".lock"),
                 [".meta", ".orig"])
        proc, record = lrun(root, stub, node_of(lang), spec["iid"], stub_cfg(lang))
        check_eq("recovered: the next probe runs (judgment: no token in the xunit form, N3b)", (record.get("verdict"), proc.returncode), ("incomplete", 1))
        check_in("recovered: the note says what was recovered", "recovered tests/CalcTests.cs", said(record))   # t-2064 P4b: `said` = the notes and the check rows' notes
        check_eq("recovered: the author's bytes are back and no copy is left", (target.read_bytes() == original, copies_left(root)), (True, []))
        check("E20: the recovered file's mtime is NOW (a file that is not Python)", target.stat().st_mtime_ns > OLD_NS + 10 ** 15)
    finally:
        cleanup(root)
        cleanup_beside(root)


# --- EP1-36: a templated or tagged TypeScript test, the aggregate of several rows, the tool's refusal ---------------------

TS_TITLES = ("describe('c', () => {\n  test('adds ${n}', async () => {\n    expect(sum(1, 2)).toBe(3);\n  });\n"
             "  test('adds 5', async () => {\n    expect(sum(1, 2)).toBe(3);\n  });\n"
             "  test('tagged @smoke', async () => {\n    expect(sum(1, 2)).toBe(3);\n  });\n});\n")
TS_ENTRY = AD.assertion_detectors()["typescript"]
TS_FILE = "src/sum.test.ts"


def refusal_class(fn):
    """(class name, name_unproved) of the refusal `fn` raises; ("", None) when it raises none."""
    try:
        fn()
    except PBC.Refusal as exc:
        return type(exc).__name__, getattr(exc, "name_unproved", None)
    return "", None


def ep1_36_titles() -> None:
    """Items 1-3: tags are taken out of both sides, a `${` title is a pattern, the candidates are what `test_source.matches` ties
    to the name, more than one is the old refusal with `--at`."""
    tail = PBC._tail_matches
    check("EP1-36 item 1: a tag the report keeps and the --test leaves out is no mismatch",
          tail("src/a.test.ts::adds @smoke", "adds", TS_ENTRY))
    check("EP1-36 item 1: ...nor the reverse", tail("src/a.test.ts::adds", "adds @smoke", TS_ENTRY))
    no_tag = dict(TS_ENTRY)
    no_tag.pop("title_tag")
    check_eq("EP1-36 item 1: an entry without `title_tag` behaves as today (the tag is part of the title)",
             tail("src/a.test.ts::adds @smoke", "adds", no_tag), False)
    check_eq("EP1-36 item 1 (BEYOND): a tag alone is not a title", tail("src/a.test.ts::adds @smoke", "@smoke", TS_ENTRY), False)
    check_eq("EP1-36 item 1: the same test with a tag is not 'another test' for the longer-title check",
             PBC._longer_title(TS_TITLES, TS_ENTRY, "tagged", "src/a.test.ts::c tagged @smoke")[0], "")
    # item 2: the title is a pattern when the entry reads templates; its literal text must be 3 characters or more
    spec = PBC.parse_node(f"{TS_FILE}::adds ${{n}}")
    check_eq("EP1-36 item 2: a `${` title sets `template`", spec.get("template"), True)
    check_eq("EP1-36 item 2: a title without it does not", PBC.parse_node(f"{TS_FILE}::adds").get("template"), None)
    check_eq("EP1-36 item 2 (AT): 3 literal characters are accepted", PBC.parse_node(f"{TS_FILE}::abc${{n}}").get("template"), True)
    check_in("EP1-36 item 2 (BEYOND): 2 literal characters are refused", "fewer than 3",
             refusal_of(lambda: PBC.parse_node(f"{TS_FILE}::ab${{n}}")))
    check_in("EP1-36 item 2: a title that is only substitutions is refused", "fewer than 3",
             refusal_of(lambda: PBC.parse_node(f"{TS_FILE}::${{a}}${{b}}")))
    # item 3: candidates
    src = PBC.Source(TS_TITLES, TS_ENTRY["lexer"], "t/x.test.ts")
    lines = lambda name: PBC._lines_of(src, PBC.declaration_candidates(src, TS_ENTRY, name, False, "t/x.test.ts"))
    check_eq("EP1-36 item 3: the raw template title is one candidate (the literal 'adds 5' is not it)", lines("adds ${n}"), [2])
    check_eq("EP1-36 item 3: a title the template renders to AND a literal one are two candidates", lines("adds 5"), [2, 5])
    check_eq("EP1-36 item 3: a tagged declaration is found by the title without its tag", lines("tagged"), [8])
    check_eq("EP1-36 item 3: ...and by the title with it (once)", lines("tagged @smoke"), [8])
    check_eq("EP1-36 item 3: a title nothing declares is no candidate", lines("zzz nothing"), [])
    message = refusal_of(lambda: plan("typescript", TS_TITLES, node=f"{TS_FILE}::adds 5"))
    check_in("EP1-36 item 3: two candidates are the old refusal with the door --at", "--at <line>", message)
    mutated, detail, _ctx = plan("typescript", TS_TITLES, node=f"{TS_FILE}::adds 5", at=3)
    mutated = mutated.decode("utf-8") if isinstance(mutated, bytes) else mutated
    check_eq("EP1-36 item 3: --at picks the template's body, and only its assertion changes",
             (detail["candidates"], detail["line"], mutated.count(".not.toBe(3)")), ([2, 5], 3, 1))
    changed = [n for n, (was, now) in enumerate(zip(TS_TITLES.splitlines(), mutated.splitlines())) if was != now]
    check_eq("EP1-36 mutation: one line changed in the one declaration, the other declarations are byte-identical",
             (changed, len(mutated.splitlines()) == len(TS_TITLES.splitlines())), ([2], True))
    tagged, detail, _ctx = plan("typescript", TS_TITLES, node=f"{TS_FILE}::tagged")
    check_eq("EP1-36 item 3: a tagged test is planned by its bare title", detail["declaration_line"], 8)
    # classes of refusal (the producer of `refused: tool`)
    check_eq("§6: no declaration is the tool's, and does not prove the name",
             refusal_class(lambda: plan("typescript", TS_TITLES, node=f"{TS_FILE}::zzz nothing")), ("ToolRefusal", True))
    check_eq("§6: no row for the suffix is the tool's", refusal_class(lambda: PBC.parse_node("t/x.zzz::a"))[0], "ToolRefusal")
    check_eq("§6: a directory is the call's", refusal_class(lambda: PBC.parse_node("tests::a", Path(SCRIPTS)))[0], "Refusal")
    check_eq("§6: the lexer that cannot read the file is the tool's",
             refusal_class(lambda: plan("typescript", "test('a', () => {\n  expect(1).toBe(1);\n"))[0], "ToolRefusal")
    check_eq("§6: no recognised assertion is the tool's", refusal_class(lambda: plan("typescript", "test('adds', () => { const x = 1; });\n", node="t/x.test.ts::adds"))[0], "ToolRefusal")
    check_eq("§6: ...but a wrong --at is the call's", refusal_class(lambda: plan("typescript", WRAP["typescript"][0].replace("{stmt}", "expect(1).toBe(1);"), at=99))[0], "Refusal")
    check_eq("§6: a --test without `::` is the call's", refusal_class(lambda: PBC.parse_node("src/sum.test.ts"))[0], "Refusal")
    check_eq("§6: two declarations are the call's", refusal_class(lambda: plan("typescript", TS_TITLES, node=f"{TS_FILE}::adds 5"))[0], "Refusal")


def judge_rows(rows: list, contract: dict, *, at=None, candidates=(3,), report_read=True, real=False):
    """`_judge_rows` over `rows` for a typescript test with `contract`: (record, the `among` values the judge saw). The
    judge and the frame reader are replaced by the row's own `v` unless `real` (the verdict table is tested elsewhere)."""
    spec = PBC.parse_node(f"{TS_FILE}::adds ${{n}}")
    # N3b: `among` reads the plan's target keys (`target_source`: `at` when --at chose; the check lies in the located body)
    detail = {"language": "typescript", "candidates": list(candidates), "at": at, "line": 3, "end_line": 5,
              "target_source": "at" if at is not None else None, "target_outside_body": False}
    record = {"task": TASK, "notes": [], "expected_location": f"{TS_FILE}:3", "expected_reason": "marker", "verdict": "not_executed"}
    request = {"instance_contracts": {"adds": contract}, "command": {"argv": ["npx", "playwright", "test"]}}
    seen = []
    old_judge, old_site = PBC.judge_probe_row, PBC.reporters.assertion_site

    def stub(row, site, entry, detail_, *, among, argv):
        seen.append(among)
        return {"verdict": row["v"], "actual_location": None, "actual_reason": None, "mismatches": [], "note": row.get("note", ""),
                "observed": {"status": row["status"]}}
    if not real:
        PBC.judge_probe_row = stub
        PBC.reporters.assertion_site = lambda *a, **k: {}
    try:
        PBC._judge_rows(Path("."), record, rows, "junit-xml", spec, detail, request, Path("x"), ["adds"], report_read)
    finally:
        PBC.judge_probe_row, PBC.reporters.assertion_site = old_judge, old_site
    return record, seen


def ep1_36_rows() -> None:
    """Items 4-6: several rows of one test, the worst speaks; no row, rows of two files and the unbound row stop BEFORE the
    aggregate; the tool's gap is written as `language` + `cause`."""
    pattern = {"file": TS_FILE, "report_test_id": "sum.test.ts::c adds ${n}", "report_match": {"pattern": "c\\ adds\\ .+"},
               "classname_match": "file_suffix"}
    row = lambda name, status, v, **extra: dict({"test_id": f"sum.test.ts::{name}", "status": status, "v": v}, **extra)
    two = [row("c adds 1", "failed", "intended_failure"), row("c adds 2", "failed", "intended_failure")]
    record, _ = judge_rows(two, pattern)
    check_eq("EP1-36 item 4: every row failed as intended -> intended_failure, both named", (record["verdict"], len(record["param_rows"])),
             ("intended_failure", 2))
    check_eq("EP1-36 item 4: ...and none of language/cause", ("cause" in record, "language" in record), (False, False))
    record, _ = judge_rows([row("c adds 1", "failed", "intended_failure"), row("c adds 2", "passed", "no_failure")], pattern)
    check_eq("EP1-36 item 4 (mutation: the first row speaks): one survivor outweighs the first row's intended_failure",
             record["verdict"], "no_failure")
    check_in("EP1-36 item 4: the survivor is named", "c adds 2", " ".join(record["notes"]))
    record, _ = judge_rows([row("c adds 1", "passed", "no_failure"), row("c adds 2", "failed", "intended_failure")], pattern)
    check_eq("EP1-36 item 4 (mutation: any instead of all): the order of rows does not matter", record["verdict"], "no_failure")
    record, _ = judge_rows([row("c adds 1", "failed", "intended_failure"), row("c adds 2", "skipped", "not_executed")], pattern)
    check_eq("EP1-36: a skipped row is not an intended failure", record["verdict"], "not_executed")
    record, _ = judge_rows([row("c adds 1", "passed", "no_failure"), row("c adds 2", "failed", "wrong_location")], pattern)
    check_eq("EP1-36: passed + wrong_location -> the mutation that never fired speaks", record["verdict"], "no_failure")
    record, _ = judge_rows([], pattern)
    check_eq("EP1-36 item 4 (M-5): no row at all is not_executed and says why, nothing raised",
             (record["verdict"], bool(record["notes"])), ("not_executed", True))
    check_eq("EP1-36 item 6 (F-1 of t-596): ...but a report that was read and held NO row is a stand that ran nothing: no cause, no language",
             ("cause" in record, "language" in record), (False, False))
    record, _ = judge_rows([row("other adds 1", "passed", "no_failure")], pattern)
    check_eq("EP1-36 item 6 (F-1 CONTROL): rows of the report and none of them this test: the tool could not bind",
             (record["verdict"], record.get("cause"), record.get("language")), ("not_executed", "tooling", "typescript"))
    record, _ = judge_rows([], {"file": TS_FILE, "report_test_id": "sum.test.ts::c adds 1"})
    check_eq("EP1-36 item 6 (F-1): the empty report through the hand-written id branch: no cause either",
             ("cause" in record, "language" in record), (False, False))
    record, _ = judge_rows([], pattern, report_read=False)
    check_eq("EP1-36 item 6: a stand that wrote no report is not a gap of the tool", ("cause" in record, "language" in record), (False, False))
    record, _ = judge_rows([{"test_id": "a/sum.test.ts::c adds 1", "status": "passed", "v": "no_failure"},
                            {"test_id": "b/sum.test.ts::c adds 1", "status": "passed", "v": "no_failure"}],
                           dict(pattern, file="a/sum.test.ts"))
    check_eq("EP1-36 item 4: rows of one file only are read (the neighbour's file is no row of this test)",
             record.get("param_rows"), None)
    record, _ = judge_rows([row("c adds 1", "passed", "no_failure")], dict(pattern, file="x/other.test.ts"), real=True)
    check_eq("EP1-36 item 4: rows that belong to another file than the contract's: not bound, not judged",
             (record["verdict"], record.get("cause")), ("not_executed", "tooling"))
    hand = {"file": TS_FILE, "report_test_id": "sum.test.ts::c adds 1"}
    record, _ = judge_rows([row("c adds 1", "passed", "no_failure"), row("c adds 1", "passed", "no_failure")], hand, real=True)
    check_eq("EP1-36 item 4: a hand-written id (no pattern, no file rule) names ONE row: two are ambiguous",
             (record["verdict"], record.get("cause")), ("not_executed", "tooling"))
    # M-4: `among` is computed, never a constant
    real_rows = [{"test_id": "sum.test.ts::c adds 1", "status": "passed", "message": "", "text": ""}]
    record, seen = judge_rows(real_rows, pattern, at=3, candidates=(2, 5), real=True)
    check_eq("EP1-36 M-4: --at among two declarations + a pass is incomplete, and a gap of the tool",
             (record["verdict"], record.get("cause"), record.get("language")), ("incomplete", "tooling", "typescript"))
    record, seen = judge_rows(real_rows, pattern, at=None, candidates=(2,), real=True)
    check_eq("EP1-36 M-4 (BEYOND): one candidate and a pass is no_failure, and no gap", (record["verdict"], "cause" in record), ("no_failure", False))
    record, seen = judge_rows([row("c adds 1", "failed", "intended_failure")], pattern, at=3, candidates=(2, 5))
    check_eq("EP1-36 M-4: the judge is told `among` from the candidates and --at", seen, [True])
    record, seen = judge_rows([row("c adds 1", "failed", "intended_failure")], pattern, at=None, candidates=(2, 5))
    check_eq("EP1-36 M-4: ...not when no --at chose", seen, [False])
    # no `file` in the contract: bind_row, as before
    # N3a's one binding: a contract with no `file` is read by `matching_rows(rows, spec["node"])`, so the row is the one the NODE names
    # (the tail after the last `::`), not the contract's `report_test_id`; a row with another name is not this test's (not_executed)
    plain = {"report_test_id": "sum.test.ts::c adds 1"}
    record, _ = judge_rows([row("adds ${n}", "failed", "intended_failure")], plain)
    check_eq("EP1-36 item 4: a contract without a file is bound by the node's own name, one row", (record["verdict"], "param_rows" in record), ("intended_failure", False))
    record, _ = judge_rows([row("c adds 1", "failed", "intended_failure")], plain)
    check_eq("EP1-36 item 4: ...and a row named only by the contract's `report_test_id` is not this node's", record["verdict"], "not_executed")
    # the shared aggregator (Python parametrised rows) keeps its behaviour
    probe: dict = {"notes": []}
    first = PBC._worst_of_rows([({"test_id": "t[1]"}, {"verdict": "intended_failure"}), ({"test_id": "t[2]"}, {"verdict": "wrong_location"})],
                               {"node": "t.py::t"}, probe)
    check_eq("EP1-36 item 5: _worst_of_rows is the one aggregator", (probe["param_rows"][1]["verdict"], probe["verdict"], first["verdict"]),
             ("wrong_location", "wrong_location", "wrong_location"))


def ts_profile_project(argv: list, rehearsed: bool = True, verified=None) -> tuple:
    """(root, cfg, manifest, spec, text) of a TypeScript project whose manifest row carries NO selector_args and NO report_test_id."""
    import onboarding_probe as OP
    root = temp_dir("qa-ep136-shape-")
    (root / "src").mkdir()
    text = "describe('c', () => {\n  test('adds', async () => {\n    expect(sum(1, 2)).toBe(3);\n  });\n});\n"
    (root / TS_FILE).write_text(text, encoding="utf-8")
    selectors = {} if verified is None else {"verified": verified}
    cfg = {"profiles": [{"profile_id": "pw", "roots": {"test": "src"}, "selectors": selectors,
                         "commands": {"one_test": {"argv": list(argv), "cwd": "."}}}]}
    if rehearsed:       # True: this command was rehearsed; a list: that command was
        proved = argv if rehearsed is True else rehearsed
        write_json(root / "qa-factory" / "state" / OP.G.REPORTER_REHEARSALS_FILE,
                   {"schema_version": 1, "rehearsals": {"k": {"profile_id": "pw", "argv_digest": OP.argv_digest(proved), "at": "2026-10-01T00:00:00"}}})
    row = {"case": "TC-1", "file": TS_FILE, "instance_id": "adds", "test": "adds", "selector": "adds"}
    return root, cfg, {"tests": [row]}, PBC.parse_node(f"{TS_FILE}::adds"), text


def shape(argv, **kw) -> tuple:
    root, cfg, manifest, spec, text = ts_profile_project(argv, **kw)
    try:
        PBC.run_shape_checks(cfg, manifest, "TC-1", manifest["tests"][0], spec, "adds", "", text, root)
        return "passed", ""
    except PBC.Refusal as exc:
        return type(exc).__name__, str(exc)
    finally:
        cleanup(root)


def ep1_36_shape() -> None:
    """Items 7-8: a row with no hand-written fields is built by `execution_request.code_selection`; a command that is the project's
    own script is refused by name and never passes; `selectors_verified` is the gate's."""
    pw = ["npx", "playwright", "test", "--reporter=junit"]
    check_eq("EP1-36 item 7+8: no hand-written fields, a rehearsed Playwright command: the row is built and the gate passes",
             shape(pw)[0], "passed")
    kind, said = shape(pw, rehearsed=False)
    check_eq("EP1-36 item 8: ...never rehearsed: the profile is not verified (the old refusal and door)", kind, "ToolRefusal")
    check_in("EP1-36 item 8: ...naming selectors.verified", "selector contract", said)
    kind, said = shape(pw, verified=False)
    check_eq("EP1-36 item 8: the literal False wins over a rehearsal on record", kind, "ToolRefusal")
    check_eq("EP1-36 item 8: ...and the literal True over none", shape(pw, rehearsed=False, verified=True)[0], "passed")
    kind, said = shape(["npx", "playwright", "test", "--reporter=line"], rehearsed=pw)
    check_eq("EP1-36 item 8: another argv than the rehearsed one is not verified (command_changed)", kind, "ToolRefusal")
    wrapper = ["node", "run-e2e.mjs"]
    kind, said = shape(wrapper, verified=True)
    check_eq("EP1-36 item 7: a wrapper script builds no selector: refused, and it is the tool's", kind, "ToolRefusal")
    check_in("EP1-36 item 7: ...BY NAME", "the project's own script", said)
    check_in("EP1-36 item 7: ...with the door", "the probe is not run on this profile; onboarding offers the direct form", said)
    # the role's own fields win and the check is as before
    root, cfg, manifest, spec, text = ts_profile_project(pw, rehearsed=False, verified=True)
    try:
        own = dict(manifest["tests"][0], selector_args=["x"], report_test_id="src/sum.test.ts::c adds")
        PBC.run_shape_checks(cfg, {"tests": [own]}, "TC-1", own, spec, "adds", "", text, root)
        check("EP1-36 item 7: hand-written fields pass as before", True)
    except PBC.Refusal as exc:
        check("EP1-36 item 7: hand-written fields pass as before", False, str(exc)[:200])
    finally:
        cleanup(root)


def tool_refusal_record(stub: Path) -> None:
    """§6: the record `refused: tool`, written only when the tool refused and the test is the instance's."""
    spec = LANGS["typescript"]
    no_assert = b"describe('calc', () => {\n  test('adds', async () => {\n    const x = 1;\n  });\n});\n"
    cases = (("E6 no recognised assertion", no_assert, node_of("typescript"), True),
             ("no declaration, the tail is the row's", no_assert.replace(b"'adds'", b"'other'"), node_of("typescript"), True),
             ("no declaration, the tail is NOT the row's", no_assert.replace(b"'adds'", b"'other'"), "src/sum.test.ts::nothing", False),
             ("a missing file", no_assert, "src/gone.test.ts::adds", False),
             ("a file that is not the row's", no_assert, "src/other.test.ts::adds", False))
    for label, data, node, wrote in cases:
        root = lang_project("typescript", data=data, files={"src/other.test.ts": data})
        try:
            before = (root / spec["file"]).read_bytes()
            proc, payload = lrun(root, stub, node, spec["iid"], stub_cfg("typescript"))
            check_eq(f"§6 {label}: exit 2, one JSON, refused", (proc.returncode, payload.get("status")), (2, "refused"))
            path = task_of(root) / "work" / "probes" / f"{spec['iid']}.json"
            # PRODUCT QUESTION 13 (t-2064-p4b2t3-report.md): the walk road's refusals ("no check of a form the factory reads was found", the
            # empty plan) write NO `refused: tool` record (t-2143 N4, EP1-36 §6; the same fork as question 2 of t-2064-p4b2t-report.md, which the
            # no_assert pin of test_probe_by_code.py took as "refusal, no record"): every pin of a `wrote` case below that reads the record is
            # RED for that one reason, and reads `{}` instead of crashing
            ask = " (PRODUCT QUESTION 13)" if wrote else ""
            check_eq(f"§6 {label}: the record exists only when the tool refused and the name is proved{ask}", path.is_file(), wrote)
            if wrote:
                def stored() -> dict:
                    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
                record = stored()
                check_eq(f"§6 {label}: not_executed, refused tool, the bytes read, the text of the refusal{ask}",
                         (record.get("verdict"), record.get("refused"), record.get("test_file_sha256"), record.get("notes"), record.get("instance_id")),
                         ("not_executed", "tool", PBC.sha256(before), [payload["error"]], spec["iid"]))
                # F-2 (t-596): the record says it is the tool's the way `_tooling_gap` does, so ONE reader (`tooling_gap_key`) answers for it
                check_eq(f"§6 {label}: the record names the tool and the language (cause, language){ask}",
                         (record.get("cause"), record.get("language")), ("tooling", "typescript"))
                check_eq(f"§6 {label}: ...and tooling_gap_key reads it for these bytes (and for no other){ask}",
                         (PL.tooling_gap_key(task_of(root), spec["iid"], PBC.sha256(before)), PL.tooling_gap_key(task_of(root), spec["iid"], "0" * 64)),
                         ("tooling:typescript", ""))
                check_eq(f"§6 {label}: ...and probe_could_not_run holds too{ask}", PL.probe_could_not_run(task_of(root), spec["iid"], PBC.sha256(before)), True)
                entry = next(t for t in json.loads((task_of(root) / "work" / "automation-manifest.json").read_text(encoding="utf-8"))["tests"]
                             if t["instance_id"] == spec["iid"])
                got = PL.already_probed(entry, {"tests": [entry]}, task_of(root), project=root)
                check_eq(f"§6 {label}: already_probed does not read it as probed", got.get("probed"), False)
                proc, payload = lrun(root, stub, node, spec["iid"], stub_cfg("typescript"))
                check_eq(f"§6 {label}: a repeat on the same bytes replaces it (idempotent){ask}",
                         stored().get("test_file_sha256"), PBC.sha256(before))
                (root / spec["file"]).write_bytes(before + b"// fixed\n")
                check(f"§6 other bytes after a fix: the record is of the old ones{ask}",
                      bool(record.get("test_file_sha256")) and record["test_file_sha256"] != PBC.sha256((root / spec["file"]).read_bytes()))
            check_eq(f"§6 {label}: the author's file is untouched", (root / spec["file"]).read_bytes() in (before, before + b"// fixed\n"), True)
        finally:
            cleanup(root)
            cleanup_beside(root)
    check_eq("§6 F-2: a .py file is no entry of the table ...",
             PBC.AD.entry_for_suffix(PBC.AD.assertion_detectors(), ".py"), (None, None))
    check_eq("§6 N4 (S4): ... so its refusal record takes the language from the AST reader's entry (the class word covers it)",
             PBC.AD.ast_entry(".py")[0], "python")
    # an intended_failure stands (E23); a write failure is a line on stderr and exit 2 (the answer never changes)
    for label, setup in (("an intended_failure stands", "stand"), ("a record that cannot be written", "block")):
        root = lang_project("typescript", data=no_assert)
        try:
            probes = task_of(root) / "work" / "probes"
            if setup == "stand":
                write_json(probes / f"{spec['iid']}.json", {"verdict": "intended_failure", "test_file_sha256": "abc"})
            else:
                probes.parent.mkdir(parents=True, exist_ok=True)
                probes.write_text("a file where the folder should be", encoding="utf-8")
            proc, payload = lrun(root, stub, node_of("typescript"), spec["iid"], stub_cfg("typescript"))
            check_eq(f"§6 {label}: exit 2 and one JSON", (proc.returncode, payload.get("status")), (2, "refused"))
            if setup == "stand":
                stored = json.loads((probes / f"{spec['iid']}.json").read_text(encoding="utf-8"))
                # the verdict and its bytes stay (green); the ATTEMPT is added only by the refusal's record: PRODUCT QUESTION 13 (no record on the
                # walk road's refusal), so `last_attempt` is absent and this pin is red for that one reason
                check_eq(f"§6 {label}: the verdict and its bytes stay, the attempt is added (PRODUCT QUESTION 13)",
                         (stored.get("verdict"), stored.get("test_file_sha256"), (stored.get("last_attempt") or {}).get("verdict")),
                         ("intended_failure", "abc", "not_executed"))
            else:
                # PRODUCT QUESTION 13 again: the walk's empty-plan refusal never tries to write a record, so there is no write failure to say
                check_in(f"§6 {label}: stderr says it (PRODUCT QUESTION 13)", "was not written", proc.stderr)
        finally:
            cleanup(root)
            cleanup_beside(root)
    root = lang_project("typescript", data=no_assert)
    try:
        proc, payload = lrun(root, stub, node_of("typescript"), "nobody", stub_cfg("typescript"))
        check_eq("§6 an instance the manifest does not name: refused (the call's), no record",
                 (proc.returncode, (task_of(root) / "work" / "probes").is_dir()), (2, False))
    finally:
        cleanup(root)
        cleanup_beside(root)


# --- RN1-8: a REAL Playwright report is read per line; E15 is the factory's data, never the tool's gap ------------------

BIN_PW = ["npx", "playwright", "test"]


RN1_8_SPEC = "tests/api/cart/add-to-cart.spec.ts"
RN1_8_CASE = "LOCAL-1_TC_010"
RN1_8_PLACEHOLDER = "{project_root}"      # the fixtures' one substitution (E20): the stand's root, replaced here by the temp root


def rn1_8_real(name: str, root: Path) -> str:
    """The text of a REAL LOCAL-1 file (run 3, 02-03.11: the Playwright report and the probe record of TC_010) with the
    token `{project_root}` replaced by this test's temp root. In the JSON record the token sits in a JSON string, so a
    backslash of the root is doubled there (the record is read as JSON, never as text)."""
    text = (FIX / name).read_text(encoding="utf-8")
    return text.replace(RN1_8_PLACEHOLDER, json.dumps(str(root))[1:-1] if name.endswith(".json") else str(root))


class Rn1_8World:
    """The shared setup of the RN1-8 keys: the table entry, the pairs, the REAL Playwright report of LOCAL-1 run 3 (10 rows,
    `playwright-red-probe.junit.xml`, bytes of `evidence/runs/64d1d369a594bd0a73fd/red_probe-...junit.xml` with the stand's
    root as `{project_root}`) and the real probe record of TC_010 (`playwright-red-probe.record.json`), a project root holding
    the spec. The spec file's CONTENT is read by nothing under test (the site is read from the report's frame; the file only
    has to exist at the frame's path): it is a copy of `sum.test.ts`, the one TypeScript file of this fixture folder."""

    def __init__(self, root: Path) -> None:
        import reporters
        self.reporters = reporters
        self.root = root
        self.ts = AD.assertion_detectors()["typescript"]
        pairs = {p["id"]: p for p in self.ts["assertions"][0]["invert"]}
        self.t1, self.t2 = pairs["T1"], pairs["T2"]
        (root / "tests" / "api" / "cart").mkdir(parents=True)
        self.spec_file = root / "tests" / "api" / "cart" / "add-to-cart.spec.ts"
        self.spec_file.write_bytes((FIX / "sum.test.ts").read_bytes())
        report = root / "report.junit.xml"
        report.write_text(rn1_8_real("playwright-red-probe.junit.xml", root), encoding="utf-8")
        self.rows = reporters.read_rows(report, "junit-xml")
        self.record = json.loads(rn1_8_real("playwright-red-probe.record.json", root))
        self.red = next(r for r in self.rows if RN1_8_CASE in r["test_id"])
        d = self.record["mutation_detail"]
        # the probe's own detail for that instance, taken from the real record (line 109, candidates [106], T2)
        self.detail = {"line": d["line"], "end_line": d["end_line"], "language": d["language"], "candidates": list(d["candidates"]),
                       "at": d["at"], "pair": d["pair"], "pair_id": d["pair_id"], "fires_as": self.t2["fires_as"]}
        self.grammar = AD.grammar_of(self.ts)

    def site_of(self, row: dict) -> dict:
        frames, skip, frame_path = self.grammar
        return self.reporters.assertion_site(row, "junit-xml", self.root, self.spec_file, pytest_command=False,
                                             runtime="typescript", frames=frames, skip_frames=skip, frame_path=frame_path)

    def judge(self, row: dict, site: dict = None, argv=BIN_PW) -> dict:
        return PBC.judge_probe_row(row, site or self.site_of(row), self.ts, self.detail, among=False, argv=argv)

    def with_text(self, text: str) -> list:
        """The TC_010 row alone (a one-row list), its failure text replaced."""
        rows = [copy.deepcopy(self.red)]
        rows[0]["problems"][0]["text"] = text
        return rows

    def original_red(self) -> list:
        """The TC_010 row alone, with the ORIGINAL form's red (`.toBeLessThan`) - what a probe that did not invert would show."""
        rows = [copy.deepcopy(self.red)]
        problem = rows[0]["problems"][0]
        problem["text"] = problem["text"].replace("expect(received).not.toBeLessThan(expected)", "expect(received).toBeLessThan(expected)")
        return rows

    def record_of(self, report_rows: list) -> dict:
        """The record `_judge_rows` writes for TC_010 over `report_rows`. The contract is the one the code builds for a
        project command (file + `classname_match: file_suffix`), so the judgment does not depend on how an id is spelled."""
        spec = PBC.parse_node(RN1_8_SPEC + "::@regression " + RN1_8_CASE + " repeat add of the same book sums quantities in one line")
        record = {"task": TASK, "notes": [], "expected_location": RN1_8_SPEC + ":109", "expected_reason": "marker",
                  "verdict": "not_executed"}
        own = {"report_test_id": self.red["test_id"], "file": RN1_8_SPEC, "classname_match": "file_suffix"}
        request = {"instance_contracts": {"adds": own}, "command": {"argv": BIN_PW}}
        PBC._judge_rows(self.root, record, report_rows, "junit-xml", spec, self.detail, request, self.spec_file, ["adds"], True)
        return record


def rn1_8_k1_k2(world: Rn1_8World) -> None:
    rows, red = world.rows, world.red
    problem = red["problems"][0]
    check_eq("K-N4-3a premise: the REAL LOCAL-1 report has 10 rows, one failed (TC_010)",
             (len(rows), [r["status"] for r in rows].count("failed"), red["status"]), (10, 1, "failed"))
    check("K-N4-3a: the TC_010 message is a place and a title (the Playwright shape), not the assertion",
          problem["message"].startswith("add-to-cart.spec.ts:106:1 "))
    site = world.site_of(red)
    check_eq("K-N4-3a: the site is read at line 109 of the project's spec, an assertion",
             (site["location"], site["failure_kind"]), (RN1_8_SPEC + ":109", "assertion"))
    check_eq("K-N4-3b premise: the real record of that probe said incomplete / tooling (the defect RN1-8 fixed)",
             (world.record["verdict"], world.record["cause"]), ("incomplete", "tooling"))
    # the record is a snapshot of the real run: its `fires_as` is the T2 row as it stood THEN, so the premise pins the
    # place and the pair, never the row's text (the row grew an alternative in t-1953 and the snapshot did not)
    check_eq("K-N4-3b premise: ...its mutation detail is the probe's own: line 109, candidates [106], pair T2",
             (world.detail["line"], world.detail["candidates"], world.detail["pair_id"], bool(world.record["mutation_detail"]["fires_as"])),
             (109, [106], "T2", True))
    got = world.judge(red)
    check_eq("K-N4-3b N3b: the real report (recorded before the marker existed), failed at the mutated line with `.not.toBeLessThan`: "
             "judgment - the place and the wording prove nothing", (got["verdict"], got.get("cause"), "proved_by" in got),
             ("incomplete", "judgment", False))
    marked = copy.deepcopy(red)
    marked["problems"][0]["message"] = "qa-probe-rn18 " + marked["problems"][0]["message"]
    got = PBC.judge_probe_row(marked, world.site_of(marked), world.ts, dict(world.detail, message_marker="qa-probe-rn18"), among=False, argv=BIN_PW)
    check_eq("K-N4-3b N3b control: the same row holding the token is proved by the marker", (got["verdict"], got.get("proved_by")),
             ("intended_failure", "marker"))
    control = world.original_red()
    shown = control[0]["problems"][0]["text"].split("> 109")[0]       # the message part, before the code frame (which echoes the mutated line)
    check("K2 control premise: the text really changed", "not.toBeLessThan" not in shown and "expect(received).toBeLessThan(expected)" in shown)
    got = world.judge(control[0])
    check_eq("K2: the same report with `.toBeLessThan` (the original's own red) is NOT intended_failure", got["verdict"], "incomplete")
    check_eq("K4: ...it is E15, and the answer is the code critic's to judge (`cause: judgment`), not the tool's gap", got.get("cause"), "judgment")
    away = world.site_of(red)
    away["location"] = RN1_8_SPEC + ":30"
    check_eq("edge: the failing text fires but the failure is NOT at the mutated line: judgment, never intended_failure (N3b)",
             world.judge(red, away, argv=[])["verdict"], "incomplete")


def rn1_8_edges(world: Rn1_8World) -> None:
    fires_as = world.t2["fires_as"]
    empty = {"status": "failed", "problems": [{"kind": "failure", "message": "", "text": ""}]}
    check_eq("edge: an empty message and an empty text match nothing", PBC.fires_on(empty, world.ts, fires_as), False)
    blank = {"status": "failed", "problems": [{"kind": "failure", "message": "  \n\t\n", "text": "   \n\n  "}]}
    check_eq("edge: lines of whitespace only are skipped (no subject, no match)", PBC.fires_on(blank, world.ts, fires_as), False)
    text = world.red["problems"][0]["text"]
    check("E19 premise: the real text holds a `Retry #1` block, after the first block", "Retry #1" in text)
    first_block = world.with_text(text.split("    Retry #1")[0])
    check("E19 premise: the cut really removed the retry", "Retry #1" not in first_block[0]["problems"][0]["text"])
    check_eq("E19: the text cut at `Retry #1` gives the same verdict as the whole text (a retry does not change the verdict)",
             world.judge(first_block[0])["verdict"], world.judge(world.red)["verdict"])
    echo = {"problems": [{"kind": "failure", "message": "", "text": "boom\n  > 12 |   expect(received).not.toBe(3);\n      at a.ts:1:1"}]}
    check_eq("edge: a code frame line echoing the statement (`> 12 | expect(..)`) is not the start of a line",
             PBC.fires_on(echo, world.ts, fires_as), False)
    check_eq("edge: the first line alone still fires (the old whole-text case)",
             PBC.fires_on({"problems": [{"kind": "failure", "message": "expect(received).not.toBe(expected)", "text": ""}]},
                          world.ts, fires_as), True)


def rn1_8_k3_samples(world: Rn1_8World) -> None:
    """K3 / m-2: the Playwright-shaped samples live in `fires` / `not` of samples.json, one reading (AD.fires_in)."""
    samples = json.loads((FIX / "samples.json").read_text(encoding="utf-8"))["pairs"]
    for pair_id, pair in (("T1", world.t1), ("T2", world.t2)):
        for label, expected in (("fires", True), ("not", False)):
            shaped = [t for t in samples[pair_id][label] if "[chromium]" in t]
            check_eq(f"K3: {pair_id} has a Playwright-shaped sample in `{label}`", len(shaped), 1)
            for text in shaped:
                got = PBC.fires_on({"problems": [{"kind": "failure", "message": "cart.spec.ts:7:1 title", "text": text}]},
                                   world.ts, pair["fires_as"])
                check_eq(f"K3: {pair_id} {label}: the Playwright shape -> {expected}", got, expected)
                if expected:
                    check_eq(f"K3: {pair_id}: ...and the same sample by the WHOLE text does not fire (the old reading missed it)",
                             AD.fires_matches(pair["fires_as"], text), False)
    check_eq("K9: probe_by_code has no second reader of `fires_as` (the echo guard and fires_on go through AD.fires_in)",
             "AD.fires_matches" in Path(PBC.__file__).read_text(encoding="utf-8"), False)


def rn1_8_k8_author_message(world: Rn1_8World) -> None:
    """m-1: the author's own assertion message must never be what turns a red into `intended_failure`."""
    fires_as = world.t2["fires_as"]
    author = "add accepted\nexpected status not to be 500"      # a two-line author message; line 2 looks like a T2 message
    as_message = {"problems": [{"kind": "failure", "message": author, "text": ""}]}
    check_eq("K8: the author's two-line `message` attribute is matched WHOLE: it does not fire (never per line)",
             PBC.fires_on(as_message, world.ts, fires_as), False)
    check_eq("K8 control: the one-line `message` that IS the library's inverted text fires",
             PBC.fires_on({"problems": [{"kind": "failure", "message": "expect(received).not.toBe(expected)", "text": ""}]},
                          world.ts, fires_as), True)
    red = world.original_red()
    red[0]["problems"][0]["message"] = author
    got = world.judge(red[0])
    check_eq("K8: the original form's red with the two-line author message in `message`: incomplete (judgment), not intended_failure",
             (got["verdict"], got.get("cause")), ("incomplete", "judgment"))


def rn1_8_k4_k5_k10_records(world: Rn1_8World) -> None:
    rows, control = world.rows, world.original_red()
    record = world.record_of(rows)
    check_eq("K1 (record) N3b: the real report (no token) through _judge_rows: judgment, not intended_failure", (record["verdict"], record.get("cause")),
             ("incomplete", "judgment"))
    record = world.record_of(control)
    check_eq("K4: E15 through _judge_rows: incomplete, cause judgment, the language named",
             (record["verdict"], record.get("cause"), record.get("language")), ("incomplete", "judgment", "typescript"))
    check_eq("K4: ...with the facts the critic judges: the whole text and the place, never a verdict",
             (sorted(k for k in ("failure_text", "location") if record["judgment_facts"].get(k) is not None),
              "verdict" in record["judgment_facts"]), (["failure_text", "location"], False))
    task = world.root / "task"
    path = PL.probe_record_path(task, "adds")
    path.parent.mkdir(parents=True)
    record["test_file_sha256"] = "a" * 64
    path.write_text(json.dumps(record), encoding="utf-8")
    check_eq("K4: tooling_gap_key reads NO class from an E15 record, so `probe gap: tooling:typescript` is not asked",
             PL.tooling_gap_key(task, "adds", "a" * 64), "")
    path.write_text(json.dumps(dict(record, cause="tooling")), encoding="utf-8")
    check_eq("K4 control: the same record with `cause: tooling` DOES name the class",
             PL.tooling_gap_key(task, "adds", "a" * 64), "tooling:typescript")
    unread = world.with_text("Error: boom\n\n    no frame in this text")
    record = world.record_of(unread)
    check_eq("K5 (t-2143 N4): a failed row with TEXT and no readable frame is the critic's - the place is a fact he reads himself",
             (record["verdict"], record.get("cause"), record.get("language")), ("incomplete", "judgment", "typescript"))
    check_eq("K5: ... its text is the fact, and the place is null", ((record.get("judgment_facts") or {}).get("failure_text"),
             (record.get("judgment_facts") or {}).get("location")), ("Error: boom\n\n    no frame in this text", None))
    quiet = world.with_text("")
    quiet[0]["problems"][0]["message"] = ""
    record = world.record_of(quiet)
    check_eq("K5 control: a failed row with NO message and NO text is still the tool's gap: incomplete + cause tooling",
             (record["verdict"], record.get("cause"), record.get("language")), ("incomplete", "tooling", "typescript"))


def rn1_8_k10_several_rows(world: Rn1_8World) -> None:
    """m-3: with several report rows `judgment` is decided over ALL surviving incomplete rows, not the first."""
    e15, gap = world.original_red()[0], world.with_text("Error: boom\n\n    no frame in this text")[0]
    for label, pair in (("E15 first", [e15, gap]), ("gap first", [gap, e15])):
        record = world.record_of(pair)
        check_eq(f"K10 (N4): two rows ({label}): one E15 and one unread failure WITH text -> both are the critic's: cause judgment, both in rows",
                 (record["verdict"], record.get("cause"), len((record.get("judgment_facts") or {}).get("rows") or [])),
                 ("incomplete", "judgment", 2))
    quiet = world.with_text("")
    quiet[0]["problems"][0]["message"] = ""
    for label, pair in (("E15 first", [e15, quiet[0]]), ("gap first", [quiet[0], e15])):
        record = world.record_of(pair)
        check_eq(f"K10 control: two rows ({label}): one E15 and one failure with NO text -> cause tooling (judgment only if ALL are)",
                 (record["verdict"], record.get("cause")), ("incomplete", "tooling"))
    record = world.record_of([e15, copy.deepcopy(e15)])
    check_eq("K10 control: two E15 rows -> cause judgment", (record["verdict"], record.get("cause")), ("incomplete", "judgment"))


def rn1_8_playwright_report() -> None:
    for key in (rn1_8_k1_k2, rn1_8_edges, rn1_8_k3_samples, rn1_8_k8_author_message, rn1_8_k4_k5_k10_records, rn1_8_k10_several_rows):
        root = temp_dir("qa-probe-rn1-8-")
        try:
            key(Rn1_8World(root))
        finally:
            cleanup(root)


def main() -> None:
    # No argument runs everything (the witness). `unit` runs the pure half (the plan, the lexer, the verdict
    # table: seconds), `cli` the half that launches the probe as a role does (minutes under load).
    # A name of a CLI section (`languages`, `modes`, `standing`, `bom`, `at`, `refusals`, `oracle`, `gaps`, `kill`)
    # runs that one.
    only = set(sys.argv[1:])
    if not only or "unit" in only:
        seed_table_plans()
        lexer_and_body()
        candidates_and_heads()
        plan_guards()
        tail_and_names()
        verdict_table()
        ep1_36_titles()
        ep1_36_rows()
        ep1_36_shape()
        rn1_8_playwright_report()
    sections = [("languages", lambda stub: [one_language(stub, lang) for lang in LANGS]),
                ("modes", r8_through_the_cli), ("standing", a_standing_record_survives_incomplete),
                ("bom", bom_and_crlf_through_the_run), ("at", at_among_two_declarations),
                ("refusals", refusals_before_the_write), ("traps", traps_through_the_cli),
                ("oracle", oracle_in_a_helper), ("gaps", data_gaps),
                ("kill", kill_and_recover), ("refused_tool", tool_refusal_record)]
    wanted = [(name, fn) for name, fn in sections if not only or "cli" in only or name in only]
    if wanted:
        stub_dir = temp_dir("qa-probe-lang-stub-")
        stub = stub_dir / "fake_lang_run_suite.py"
        stub.write_text(LANG_RUN_SUITE, encoding="utf-8")
        try:
            for _name, fn in wanted:
                fn(stub)
        finally:
            cleanup(stub_dir)
    finish("test_probe_by_code_languages")


if __name__ == "__main__":
    main()
