"""Shared scaffolding for the C0 unit tests (not a test itself — selftest.py runs test_*.py).

Every test file here is runnable on its own (`python scripts/tests/test_x.py`) and prints one
PASS/FAIL line per assertion, so a failure names the rule that broke rather than a traceback.
"""
import atexit
import contextlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

# Nothing a test writes may land inside the package. A marketplace whose source is a local
# directory copies the package as it lies on disk, and .gitignore is a git rule, not a copy
# rule: one leftover directory here ships into every install made from that clone, and an
# EMPTY one is invisible to `git status`, so nothing in the review would ever mention it.
# Bytecode caches are the same litter; a child process inherits the setting with the rest.
sys.dont_write_bytecode = True
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"

# The few tests that reach a real pytest reach it to collect node ids, and a measured
# `--collect-only` cost 3.11 s with this machine's installed plugins autoloading and 1.12 s
# without them. It is also the more honest run: node_ids.py states that pytest-playwright "is
# never needed", the temp project's conftest simulates what that plugin does to parameter ids,
# and the real plugin loading on top of it would parametrize the same fixture twice. Set here
# rather than in each of those files so it holds however a test file is started; a project's
# own pytest plugins are the project's business, and run_suite.py and the other runtime
# scripts never touch this variable.
os.environ["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"

# No test may start a real `claude -p`. story_run's Driver takes its executable from
# STORY_RUN_CLAUDE and, when that is unset, from whatever `claude` lies on PATH: a conductor
# round trip in test_human_questions did exactly that, and every run launched a paid session
# acting in a temp project. Unless a test already names its own stub, every test process (and
# the children it starts, which inherit the environment) gets no_claude.py, which refuses.
# (An EMPTY value counts as unset: the driver falls back to PATH on it too.)
if not os.environ.get("STORY_RUN_CLAUDE"):
    os.environ["STORY_RUN_CLAUDE"] = str(Path(__file__).resolve().parent / "no_claude.py")
# The same for the Codex host (`story_run.py --host codex`, CX1-15): STORY_RUN_CODEX, else the `codex` on PATH.
if not os.environ.get("STORY_RUN_CODEX"):
    os.environ["STORY_RUN_CODEX"] = str(Path(__file__).resolve().parent / "no_claude.py")

PLUGIN_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = PLUGIN_ROOT / "scripts"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
TEST_CODE = FIXTURES / "test-code"
DRIVER_MAP = FIXTURES / "driver-layers.json"


def driver_sources(root: Path = PLUGIN_ROOT, exempt=None) -> list:
    """The ONE reader of the driver source set (AR-13): [(Path, text)] of scripts/story_run.py first, then the sorted
    scripts/driver_*.py, minus the stems the map lists as `not_driver` (read from driver-layers.json; the layer test passes
    the stems of the map under test as `exempt`). A missing map or a missing story_run.py raises with the path: an empty set
    would make every 'no such form anywhere in the driver' census pass."""
    root = Path(root)
    if exempt is None:
        if not DRIVER_MAP.is_file():
            raise FileNotFoundError(f"driver_sources: the layer map {DRIVER_MAP} is missing; expected driver-layers.json there")
        exempt = {row["module"] for row in json.loads(DRIVER_MAP.read_text(encoding="utf-8")).get("not_driver", [])}
    main = root / "scripts" / "story_run.py"
    if not main.is_file():
        raise FileNotFoundError(f"driver_sources: {main} is missing; expected the driver's entry file there")
    files = [main] + [p for p in sorted((root / "scripts").glob("driver_*.py")) if p.stem not in exempt]
    return [(p, p.read_text(encoding="utf-8")) for p in files]


def driver_text(root: Path = PLUGIN_ROOT) -> str:
    """The driver source set as one text (the texts of driver_sources joined with a newline)."""
    return "\n".join(text for _p, text in driver_sources(root))

# Test scripts historically passed GOOD/BAD directly to writers such as ledger.py. Give
# every test process private copies so generated ledgers never dirty tracked fixtures.
#
# Copied on FIRST USE, not at import. 91 test files import this module and six name GOOD or
# BAD, so two copytrees at import time were paid 85 times for nothing (~24 s of one selftest),
# and with no atexit each of those processes left its workspace standing: %TEMP% held 4727
# `qa-fixtures-*` trees, ~184k files, when the selftest duration was measured on 24.09.
# Module-level __getattr__ (PEP 562) keeps `from harness import GOOD, BAD` and `harness.GOOD`
# handing back the same plain Path they always did, so no call site changes.
_FIXTURE_WORKSPACE: Path | None = None


def _fixture_copy(name: str) -> Path:
    global _FIXTURE_WORKSPACE
    if _FIXTURE_WORKSPACE is None:
        _FIXTURE_WORKSPACE = Path(tempfile.mkdtemp(prefix="qa-fixtures-"))
        atexit.register(shutil.rmtree, _FIXTURE_WORKSPACE, True)
    target = _FIXTURE_WORKSPACE / name
    if not target.exists():
        shutil.copytree(FIXTURES / name, target)
    return target


def __getattr__(name: str) -> Path:
    """GOOD and BAD, built on first use — see the note above."""
    if name == "GOOD":
        return _fixture_copy("artifacts-good")
    if name == "BAD":
        return _fixture_copy("artifacts-bad")
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

RESULTS: list = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    RESULTS.append((bool(ok), name))
    print(("PASS " if ok else "FAIL ") + name + (f" — {detail}" if detail and not ok else ""))
    return bool(ok)


def release_note(fragment: Path, marker: str, changelog: Path | None = None) -> str:
    """The text of one release note: the fragment while the file exists, else the CHANGELOG.md block that carries `marker`.

    A release folds changelog.d/ fragments into CHANGELOG.md (changelog_assemble.py); the block (lines up to the next blank line)
    holding `marker` is then the note. Returns "" when the fragment is gone and no block carries the marker, or the changelog
    cannot be read - the caller's check goes red on the empty text. Two blocks carrying the marker raise ValueError naming both.
    """
    if fragment.is_file():
        return fragment.read_text(encoding="utf-8")
    path = changelog or PLUGIN_ROOT / "CHANGELOG.md"
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return ""
    blocks, start = [], 0
    for i, line in enumerate(lines + [""]):
        if not line.strip():
            if i > start:
                blocks.append((start + 1, "\n".join(lines[start:i])))
            start = i + 1
    hits = [(first, text) for first, text in blocks if marker in text]
    if len(hits) > 1:
        raise ValueError(f"the marker {marker!r} is carried by two blocks of {path.name}: lines {hits[0][0]} and {hits[1][0]}")
    return hits[0][1] if hits else ""


def check_eq(name: str, got, expected) -> bool:
    return check(name, got == expected, f"expected {expected!r}, got {got!r}")


def check_in(name: str, needle: str, haystack) -> bool:
    text = "\n".join(haystack) if isinstance(haystack, (list, tuple)) else str(haystack)
    return check(name, needle in text, f"{needle!r} not found in:\n{text[:600]}")


def check_not_in(name: str, needle: str, haystack) -> bool:
    text = "\n".join(haystack) if isinstance(haystack, (list, tuple)) else str(haystack)
    return check(name, needle not in text, f"{needle!r} unexpectedly found in:\n{text[:600]}")


def dead_cwd() -> bool:
    """True when the process's working directory no longer exists. Linux lets a directory be deleted under a
    process standing in it (Windows refuses), and the NEXT `os.getcwd()` of the process then raises."""
    try:
        os.getcwd()
    except OSError:
        return True
    return False


def guard_cwd(test_name: str) -> bool:
    """The guard (C4-6, FR-31): after a test, the process's cwd must exist. A test that leaves the process in a
    deleted directory is the defect, so it is named HERE with a FAIL line, not by the next test that dies in
    `os.getcwd()`. The cwd is then moved back (to the recorded base, see `remember_cwd`) so that ONE offender
    costs ONE line. A healthy cwd prints nothing and records nothing - on Windows, where a cwd is never deleted,
    this is always so. Returns True when the cwd was fine."""
    if not dead_cwd():
        return True
    check(f"cwd: {test_name} left the process in a deleted directory", False,
          "the test chdir'd into a directory and deleted it without going back; restore the cwd BEFORE "
          "the delete (`harness.cleanup(root)` does it for a project a Driver was built over)")
    _go_back()
    return False


# The cwd a test file started a Driver from. `story_run.Driver.__init__` chdirs into the project it is given,
# and the fixture deletes that project afterwards: Windows refuses to delete the cwd, Linux does not.
_CWD_BASE: str | None = None


def remember_cwd() -> None:
    """Record the cwd to come back to (`story_run_common.driver_for` calls this before it builds a Driver).
    The OUTERMOST caller's cwd wins: a nested call (a cwd that is already a project) records nothing while a
    recorded base still exists. A cwd that is already dead records the plugin root."""
    global _CWD_BASE
    if _CWD_BASE is not None and os.path.isdir(_CWD_BASE):
        return
    try:
        _CWD_BASE = os.getcwd()
    except OSError:
        _CWD_BASE = str(PLUGIN_ROOT)


def _go_back() -> None:
    global _CWD_BASE
    target = _CWD_BASE if _CWD_BASE and os.path.isdir(_CWD_BASE) else str(PLUGIN_ROOT)
    os.chdir(target)
    _CWD_BASE = None


def _cwd_in(root: Path) -> bool:
    """True when the cwd is inside `root` or is already gone (a deleted dir has no path to compare)."""
    try:
        here = os.getcwd()
    except OSError:
        return True
    def norm(p):
        return os.path.normcase(os.path.realpath(p))
    try:
        return os.path.commonpath([norm(here), norm(root)]) == norm(root)
    except ValueError:        # another drive
        return False


def finish(label: str) -> None:
    guard_cwd(f"{label} (end of file)")
    bad = sum(1 for ok, _ in RESULTS if not ok)
    print(f"\n=== {label}: {len(RESULTS) - bad}/{len(RESULTS)} ok ===")
    sys.exit(1 if bad else 0)


def run_script(name: str, *args, cwd: Path | None = None, env: dict | None = None):
    # -B and the variable, even when the caller hands over a scrubbed env (a test that wants
    # nothing but CLAUDE_PROJECT_DIR set): otherwise that child writes __pycache__ into the
    # package, and what lies in the package is what a marketplace installs.
    child_env = dict(env if env is not None else os.environ)
    child_env["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run([sys.executable, "-B", str(SCRIPTS / name), *[str(a) for a in args]],
                          capture_output=True, text=True, encoding="utf-8", errors="replace",
                          cwd=str(cwd) if cwd else None, env=child_env, timeout=300)


def run_capture(root: Path, session: str, transcript: Path):
    """Run `cost_capture.py` as the Stop hook does for one session of the project at `root`; the
    CompletedProcess. The one shared Stop-subprocess helper of the capture tests (QUEUE-1)."""
    event = {"hook_event_name": "Stop", "session_id": session, "transcript_path": str(transcript), "cwd": str(root)}
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(root), PYTHONPATH=str(SCRIPTS))
    return subprocess.run([sys.executable, "-B", str(SCRIPTS / "cost_capture.py")], input=json.dumps(event), text=True,
                          capture_output=True, encoding="utf-8", cwd=str(root), env=env, timeout=120)


def temp_dir(prefix: str = "qa-factory-test-") -> Path:
    """A throwaway directory OUTSIDE the package — see the note at the top of this file."""
    return Path(tempfile.mkdtemp(prefix=prefix))


def mark_project(root: Path) -> Path:
    """Write the project marker, `qa-factory/config.json` from the shipped template, into an
    existing folder and return it. THE one place a test fixture gets its marker (t-774, the class
    behind the red CI after F4-2): `runtime_paths.nearest_project` finds a project by that FILE
    alone, so a story folder built without it has no project, and every branch the controller
    guards with `_project_root()` (the host-binding veto, liveness, the RUN gate, the dashboard)
    silently takes its "no project" road. A fixture that models a project calls this, or builds
    its root with `temp_project`; a hand-written `config.json` beside a test is a second copy.
    A fixture that deliberately models NO project says so in a comment and calls neither.

    The marker carries the template's keys, not an empty `{}`: `nearest_project` needs only the
    file, but the next reader of the same folder (`hooklib.artifact_root`, `contract._config_location`,
    `resolve_runtime`) reads its keys, and a fixture should not be the one place they are absent."""
    root = Path(root)
    (root / "qa-factory").mkdir(parents=True, exist_ok=True)
    cfg = json.loads((PLUGIN_ROOT / "references" / "templates" / "config.json").read_text(encoding="utf-8"))
    cfg["tests_root"] = "tests"
    cfg["app_root"] = "."
    (root / "qa-factory" / "config.json").write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    return root


def temp_project(prefix: str = "qa-factory-test-") -> Path:
    """A throwaway project root with qa-factory/config.json from the shipped template (`mark_project`).
    The caller is responsible for cleanup (use make_project() in a try/finally)."""
    root = mark_project(Path(tempfile.mkdtemp(prefix=prefix)))
    (root / "qa-factory" / "state").mkdir(parents=True)
    (root / "tests").mkdir(parents=True)
    return root


def install_artifacts(root: Path, source: Path, ticket: str) -> Path:
    """Copy a fixture artifact set into <root>/qa-factory/artifacts/<ticket>/."""
    target = root / "qa-factory" / "artifacts" / ticket
    shutil.copytree(source, target)
    return target


def use_project(root: Path) -> None:
    """Point the hook layer at this project, inside this process. hooklib caches the project
    root per process, so the cache is cleared too — a test that moves the root and forgets
    this would silently validate the plugin's own repository."""
    os.environ["CLAUDE_PROJECT_DIR"] = str(root)
    sys.path.insert(0, str(SCRIPTS))
    import hooklib
    hooklib._PROJECT_ROOT_CACHE = None


@contextlib.contextmanager
def reader_patched(attr: str, make):
    """Replace `hooklib._Reader.<attr>` with `make(real)` for the block, reading from an EMPTY cache both ways (SC1-5b, AR-15).

    `hooklib._read_units` keeps a reading per (text, dialect) for the process: a text read earlier is a cache hit that never
    reaches the reader, so a test that patches or counts the reader sees nothing, or too little, when it starts warm (a counter's
    own control goes falsely red; "no reader was built" is masked). The cache is cleared on entry, so the patched reader is the
    one that reads, and on exit, so no later row inherits a reading made through the patch. This is the ONE place that rule is
    written: every test that patches or counts the reader goes through it. Needs `scripts/` on `sys.path` (every caller has it).
    Yields the real attribute, for a wrapper that calls it."""
    import hooklib
    real = getattr(hooklib._Reader, attr)
    hooklib._read_units.cache_clear()
    setattr(hooklib._Reader, attr, make(real))
    try:
        yield real
    finally:
        setattr(hooklib._Reader, attr, real)
        hooklib._read_units.cache_clear()


def repaste_appendix(task: Path) -> None:
    """The scribe's move when the report's appendix no longer matches the story (HF2-6b `report_facts._appendix_problems`):
    `traceability.py --render` of the story AS IT STANDS NOW, pasted under `## Appendix`. A key that changes the story after
    its fixture report was written (a red run, an added `## Then`) calls this at the point where the story's state is final.
    The one helper of the report-checking test files; needs `scripts/` on `sys.path` (every one of them has put it there).
    The report's line endings are kept (a CRLF report stays CRLF: the CRLF keys test those bytes)."""
    import report_facts as RF
    import traceability as T
    path = task / "test-report.md"
    raw = path.read_bytes().decode("utf-8")
    eol = "\r\n" if "\r\n" in raw else "\n"
    text = raw.replace("\r\n", "\n")
    begin, end = RF._section_span(text, "## Appendix")
    text = text[:begin] + "## Appendix — traceability\n\n" + T.render(T.build(task.parents[1], task)) + "\n" + text[end:]
    path.write_bytes(text.replace("\n", eol).encode("utf-8"))


def s5_plan_ready(controller, task_root, cases, ids=("S5-plan-author-1", "S5-plan-critic-1")) -> dict:
    """SC1-14 B1b (t-1317): make the plan order of S5 hold for a story, so that its fixture may dispatch the S5 WINDOWS.

    On the plan form (the default of a desktop process, `s5_plan.mode`) a window is dispatched only against a plan that is
    there, clean, reviewed, not blocked and still the one reviewed. This helper does, through the controller and the A1a/A1b
    writers, what the author and the plan critic do: the author's dispatch (`purpose: s5_plan`) and the skeleton
    `work/s5-plan.json` (`s5_plan.init`) with one `new` test over every Then of each case, its accept; the critic's dispatch,
    an `approved` review form, the stamp (`s5_plan.stamp_review`), its accept. Neither accept closes S5 (a plan never does).
    `ids` are the two dispatch ids (author, critic); the defaults are not `S5-<role>-<n>`, the ids the windows of a fixture carry.

    `cases` is the story's S5 scope and is required: a plan with no case is not a plan (E7), so an empty `cases`, or a scope
    other than the one the controller derives for S5, is an AssertionError (the test passed the wrong cases). A test about the
    legacy form or the driver does not call this; it sets its mode (`QA_FACTORY_RUN_MODE`) or its records itself. Returns the
    plan as written. Needs `scripts/` on `sys.path` (every caller has put it there)."""
    import hashlib
    import s5_plan as SP
    from event_store import atomic_json
    task_root = Path(task_root)
    cases = [str(case) for case in cases or []]
    if not cases:
        raise AssertionError("s5_plan_ready needs the S5 cases of the story: a plan with no case is not a plan (pass `cases`)")
    derived = [str(case) for case in controller.stage_scope("S5").get("scope") or []]
    if sorted(derived) != sorted(cases):
        raise AssertionError(f"s5_plan_ready: the S5 scope of the story is {derived}, the test passed {cases}; pass the scope")

    def send(identifier, role):
        controller.apply("dispatch", {"id": identifier, "stage": "S5", "role": role, "scope": cases, "purpose": "s5_plan",
                                      "input_hash": "plan-ready", "budget": {}, "known_paths": {}, "idempotency_key": identifier})

    def accept(identifier):
        path = task_root / f"{identifier}.txt"
        path.write_text("receipt", encoding="utf-8")
        controller.apply("accept", {"id": identifier, "status": "accepted", "idempotency_key": identifier + "-ok",
                                    "evidence_refs": [{"path": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}]})

    author, critic = ids
    send(author, "qa-automator")
    plan = SP.init(task_root, controller)
    plan["tests"] = [
        {"id": f"T-{n}", "file": f"tests/test_t_{n}.py", "function": "test_it", "cases": [row["case"]],
         "thens": [f"{row['case']}#{then['n']}" for then in row["thens"]], "level": "api", "shape": "new", "extends": "",
         "consolidates": [], "params": None, "uses": [], "data": "own", "assert": "the response is 200", "deviation": []}
        for n, row in enumerate(plan["cases"], 1)]
    atomic_json(task_root / SP.PLAN_REL, plan)
    accept(author)
    send(critic, "qa-code-critic")
    form = task_root / "work" / "handoffs" / f"{critic}.yaml"
    form.parent.mkdir(parents=True, exist_ok=True)
    form.write_text("schema_version: 1\ncontract: s5-critic-plan-to-automator\nreview:\n  outcome: approved\nremarks: []\n",
                    encoding="utf-8")
    SP.stamp_review(task_root, critic)
    accept(critic)
    return plan


@contextlib.contextmanager
def run_mode(mode):
    """SC1-14 B1b (t-1317): the process asks as `mode` (`QA_FACTORY_RUN_MODE`: "driver" or "desktop") for the length of the block,
    and the variable is put back as it was. For a fixture whose S5 can NOT take the plan form - its plan rows carry no
    disposition, so the S5 scope is not derived (`stage_scope`: derived false) and there is no plan to write - and which therefore
    begins on the earlier form, the form the driver process keeps (E21): its FIRST S5 dispatch is made inside the block (the form
    is fixed by that first record, `s5_plan.mode`). A fixture whose S5 scope IS derived calls `s5_plan_ready` instead."""
    key, old = "QA_FACTORY_RUN_MODE", os.environ.get("QA_FACTORY_RUN_MODE")
    os.environ[key] = mode
    try:
        yield
    finally:
        if old is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = old


def s5_apply(controller, request):
    """`controller.apply("dispatch", request)`; a request of S5 inside `s5_window_form` (the story root is the controller's own),
    any other stage as it is - so a fixture may send every request it builds through here."""
    if request.get("stage") != "S5" or request.get("purpose") == "s5_plan":
        return controller.apply("dispatch", request)
    with s5_window_form(controller, controller.store.root):
        return controller.apply("dispatch", request)


def s5_window_form(controller, task_root, ids=("S5-plan-author-1", "S5-plan-critic-1")):
    """SC1-14 B1b (t-1317): for a fixture that does not care which form its S5 has, only that its WINDOWS may be dispatched:
    `with s5_window_form(c, root): c.apply("dispatch", <a window>)`. Safe to put round every window dispatch of a fixture: the
    form is fixed by the FIRST live S5 record (`s5_plan.mode`), so a story that already has one is left as it is (a no-op block).
    The first one: a story that CAN have a plan gets it (`s5_plan_ready`): its S5 scope is derived and every case of it has its
    case file with a `## Then` (without one `s5_plan.check` finds a gap in every plan and the author's plan is not accepted).
    A story that cannot - the rows carry no disposition, or the cases have no files (most fixtures: they stop at the case's
    id and version) - is a story of the earlier form, and gets `run_mode("driver")` for the block, which fixes that form."""
    import controller as CT
    if any(isinstance(record, dict) and record.get("stage") == "S5" and record.get("status") not in CT.DISCOUNTED
           for record in controller.state()["dispatches"].values()):
        return contextlib.nullcontext()
    scope = controller.stage_scope("S5").get("scope")
    if scope:
        import s5_plan as SP
        index, _versions = SP._versions(task_root, scope)
        if all(SP._then_rows((index or {}).get(case)) for case in scope):
            s5_plan_ready(controller, task_root, scope, ids)
            return contextlib.nullcontext()
    return run_mode("driver")


def cleanup(root: Path) -> None:
    """rmtree that also removes a git object store: those files are read-only on Windows, and
    `ignore_errors=True` would leave the whole tree standing without saying so.

    The cwd goes back FIRST (C4-6): a Driver built through `story_run_common.driver_for` has chdir'd into this
    project, and a process standing in a deleted directory dies in its next `os.getcwd()` on Linux (Windows
    refuses the delete, so it only ever showed there). Only a cwd INSIDE `root` is moved: to the recorded base,
    or - for a Driver built without `driver_for` (`remember_cwd` never ran) - to the plugin root."""
    if _cwd_in(root):
        _go_back()

    def force(func, target, _info):
        try:
            os.chmod(target, stat.S_IWRITE)
            func(target)
        except OSError:
            pass

    if sys.version_info >= (3, 12):
        shutil.rmtree(root, onexc=force)
    else:
        shutil.rmtree(root, onerror=force)
