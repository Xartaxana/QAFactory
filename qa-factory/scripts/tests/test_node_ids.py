"""node_ids.py — the ids a run names are checked against what pytest really collects.

The literal ids are the ones of TP1-15045, job 071bcb794f4e10520240: asked
`[buffer-R3-vs-selected-R1]`, collected `[chromium-buffer-R3-vs-selected-R1]`, exit 4, nothing
ran. `match()` is tested on literal lists, so pytest-playwright is never needed; `collect()`
runs against a tiny temp project whose conftest prepends the browser the way that plugin does.
Where pytest is not importable at all, a stub `pytest.py` in the project answers instead, so
the subprocess plumbing and the parsing are still exercised.
"""
import importlib.util
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness import (check, check_eq, check_in, cleanup, finish, run_script,  # noqa: E402
                     temp_dir)

import node_ids as N  # noqa: E402

HAVE_PYTEST = importlib.util.find_spec("pytest") is not None
PYTEST = [sys.executable, "-B", "-m", "pytest", "-p", "no:cacheprovider"]

FILE = "tests/ui/workflows/test_workflow_visual_diff.py"
FN = f"{FILE}::test_visual_diff_markers_follow_the_selected_pair_not_a_stale_pair"
COLLECTED = [
    f"{FN}[chromium-buffer-R3-vs-selected-R1]",
    f"{FN}[chromium-saved-R2-vs-R1]",
    f"{FILE}::test_visual_diff_is_read_only[chromium]",
    "tests/ui/workflows/test_workflow_restore.py::"
    "test_restore_valid_revision_shows_no_issues_and_persists_nothing[chromium-yaml]",
    "tests/api/test_limits.py::TestLimits::test_region[eu]",
    "tests/api/test_limits.py::TestLimits::test_region[api-us]",
]

CONFTEST = '''\
def pytest_generate_tests(metafunc):
    # What pytest-playwright does with `browser_name`: the plugin parametrizes before the
    # test's own marks, so the browser LEADS every parameter id. The fixture is named
    # neutrally because an interpreter that HAS the plugin refuses a second parametrization.
    if "engine_name" in metafunc.fixturenames:
        metafunc.parametrize("engine_name", ["chromium"])
'''
TEST_FILE = '''\
import pytest


@pytest.mark.parametrize("pair", ["buffer-R3-vs-selected-R1", "saved-R2-vs-R1"])
def test_markers_follow_the_selected_pair(engine_name, pair):
    assert pair


def test_read_only(engine_name):
    assert engine_name


def test_plain():
    assert True
'''
STUB = '''\
import sys
from pathlib import Path
here = Path(__file__).resolve().parent
sys.stdout.write((here / "_canned.txt").read_text(encoding="utf-8"))
sys.exit(int((here / "_canned_rc.txt").read_text(encoding="utf-8")))
'''


def project() -> Path:
    root = temp_dir("qa-node-ids-")
    (root / "tests").mkdir()
    (root / "conftest.py").write_text(CONFTEST, encoding="utf-8")
    (root / "tests" / "test_diff.py").write_text(TEST_FILE, encoding="utf-8")
    if not HAVE_PYTEST:
        (root / "pytest.py").write_text(STUB, encoding="utf-8")
        canned(root, "tests/test_diff.py::test_markers_follow_the_selected_pair"
                     "[chromium-buffer-R3-vs-selected-R1]\n"
                     "tests/test_diff.py::test_markers_follow_the_selected_pair"
                     "[chromium-saved-R2-vs-R1]\n"
                     "tests/test_diff.py::test_read_only[chromium]\n"
                     "tests/test_diff.py::test_plain\n\n4 tests collected in 0.01s\n", 0)
    return root


def canned(root: Path, text: str, code: int) -> None:
    """Only the stub reads these; with a real pytest they are inert."""
    (root / "_canned.txt").write_text(text, encoding="utf-8")
    (root / "_canned_rc.txt").write_text(str(code), encoding="utf-8")


def matching() -> None:
    asked = f"{FN}[buffer-R3-vs-selected-R1]"
    got = N.match([asked], COLLECTED)
    check_eq("the TP1-15045 id is resolved to its chromium spelling",
             got["resolved"], {asked: COLLECTED[0]})
    check_eq("nothing is missing then", got["missing"], [])
    check_in("and the note names the real spelling", "chromium-buffer-R3-vs-selected-R1",
             got["notes"])

    bare = N.match([FN], COLLECTED)
    check_eq("an id without parameters matches when the function exists",
             bare, {"resolved": {FN: FN}, "missing": [], "notes": []})
    exact = N.match([COLLECTED[1]], COLLECTED)
    check_eq("an exact id is resolved to itself, silently",
             exact, {"resolved": {COLLECTED[1]: COLLECTED[1]}, "missing": [], "notes": []})

    suffix = "tests/api/test_limits.py::TestLimits::test_region[us]"
    got = N.match([suffix], COLLECTED)
    check_eq("a single sibling ending with -<asked params> is resolved (class-based id too)",
             got["resolved"], {suffix: COLLECTED[5]})

    stripped = f"{FILE}::test_visual_diff_is_read_only[chromium-x]"
    check_eq("an unknown parameter id is never resolved by guessing",
             list(N.match([stripped], COLLECTED)["resolved"]), [])
    reverse = N.match(["tests/api/test_limits.py::TestLimits::test_region[chromium-eu]"],
                      COLLECTED)
    check_eq("a browser token the project does not add is dropped",
             list(reverse["resolved"].values()), [COLLECTED[4]])

    gone = N.match([f"{FN}[buffer-R9]"], COLLECTED)
    check_eq("an id pytest does not collect is missing", len(gone["missing"]), 1)
    check_eq("with at most three nearest ids", len(gone["missing"][0]["nearest"]), 3)
    check_eq("siblings of the same function first, the closest one leading",
             gone["missing"][0]["nearest"][:2], COLLECTED[:2])
    nowhere = N.match(["tests/ui/test_gone.py::test_x"], COLLECTED)
    check_eq("a function that does not exist is missing",
             [m["asked"] for m in nowhere["missing"]], ["tests/ui/test_gone.py::test_x"])

    two = COLLECTED + [f"{FN}[firefox-buffer-R3-vs-selected-R1]"]
    both = N.match([asked], two)
    check_eq("two browsers are not guessed between", list(both["resolved"]), [])
    check_eq("both candidates are offered instead",
             sorted(both["missing"][0]["nearest"]), sorted([two[0], two[-1]]))

    windows = "C:\\qsbx-critic6\\testproject1_test_harness\\" + asked.replace("/", "\\")
    got = N.match([windows], COLLECTED)
    check_eq("an absolute sandbox prefix and backslashes do not break matching",
             list(got["resolved"]), [windows])
    check("the real id keeps the path spelling the caller asked with",
          got["resolved"][windows].startswith("C:\\qsbx-critic6\\")
          and got["resolved"][windows].endswith("[chromium-buffer-R3-vs-selected-R1]"),
          got["resolved"][windows])
    above = N.match([f"testproject1_test_harness/{FN}[chromium-saved-R2-vs-R1]"], COLLECTED)
    check_eq("a rootdir below the asked path does not break matching", above["missing"], [])

    check_eq("a file id is present when anything was collected in it",
             N.match([FILE], COLLECTED)["missing"], [])
    check_eq("a directory id likewise", N.match(["tests/api"], COLLECTED)["missing"], [])
    check_eq("nothing collected means everything asked is missing",
             len(N.match([asked, FN], [])["missing"]), 2)
    check_eq("the shape is fixed even when nothing was asked",
             N.match([], COLLECTED), {"resolved": {}, "missing": [], "notes": []})
    check_eq("parameters holding brackets and colons are split at the first bracket",
             N.split_id("a.py::test_x[x::y[0]-z]"), ("a.py", "test_x", "x::y[0]-z"))


def command() -> None:
    check_eq("a report path, workers and the asked ids never reach a collect",
             N._collect_argv(["pytest", "-n", "4", "--junitxml=r.xml", "--junitxml", "r.xml",
                              "-nauto", "{report_path}", "a.py::t[x]", "--ui-headless"],
                             ["a.py::t[x]"]),
             ["pytest", "--ui-headless"])
    check_eq("pytest is recognised bare, behind a wrapper and as a module",
             [N.is_pytest(["pytest"]), N.is_pytest(["poetry", "run", "pytest", "-q"]),
              N.is_pytest(["C:/venv/Scripts/python.exe", "-m", "pytest"]),
              N.is_pytest(["C:\\venv\\Scripts\\pytest.exe"]),
              N.is_pytest(["npx", "playwright", "test"])],
             [True, True, True, True, False])
    skipped = N.check_request(["npx", "playwright", "test"], ".", ["a.spec.ts::x"])
    check_eq("a command that is not pytest is never blocked",
             (skipped["resolved"], skipped["missing"]), ({}, []))
    check_eq("collected ids are read up to the first section, warnings ignored",
             N.parse_collected("tests/a.py::test_a[chromium-1]\ntests/a.py::T::test_b\n\n"
                               "2 tests collected in 0.01s\n==== warnings summary ====\n"
                               "tests/b.py::test_c\n  w.py:1: DeprecationWarning\n"),
             ["tests/a.py::test_a[chromium-1]", "tests/a.py::T::test_b"])


def collecting() -> None:
    root = project()
    try:
        ids = N.collect(PYTEST, str(root), 120, files=["tests/test_diff.py"])
        check_eq("collect returns the full node ids, browser first, as the plugin spells them",
                 ids, ["tests/test_diff.py::test_markers_follow_the_selected_pair"
                       "[chromium-buffer-R3-vs-selected-R1]",
                       "tests/test_diff.py::test_markers_follow_the_selected_pair"
                       "[chromium-saved-R2-vs-R1]",
                       "tests/test_diff.py::test_read_only[chromium]",
                       "tests/test_diff.py::test_plain"])
        check("a collect leaves no bytecode in the tree it read",
              not list(root.rglob("__pycache__")), [str(p) for p in root.rglob("__pycache__")])

        asked = ("tests/test_diff.py::test_markers_follow_the_selected_pair"
                 "[buffer-R3-vs-selected-R1]")
        windows = str(root / "tests" / "test_diff.py") + "::test_plain"
        got = N.check_request(PYTEST + ["--junitxml=" + str(root / "r.xml"), asked], str(root),
                              [asked, windows], 120)
        check_eq("check_request resolves the role's spelling to the collected one",
                 got["resolved"].get(asked), ids[0])
        check_eq("an absolute path to the same file is matched", got["resolved"].get(windows),
                 windows)
        check_eq("no id is missing and no error is reported",
                 (got["missing"], "collect_error" in got), ([], False))
        check("the collect wrote no report into the run's place", not (root / "r.xml").exists())

        if not HAVE_PYTEST:
            return
        gone = N.check_request(PYTEST, str(root), ["tests/test_diff.py::test_read_only[webkit]"],
                               120)
        check_eq("an uncollected id is missing", [m["asked"] for m in gone["missing"]],
                 ["tests/test_diff.py::test_read_only[webkit]"])
        check_eq("and the nearest id is its real sibling",
                 gone["missing"][0]["nearest"][0], "tests/test_diff.py::test_read_only[chromium]")

        (root / "pytest.ini").write_text("[pytest]\naddopts = -q\n", encoding="utf-8")
        check_eq("a project whose addopts already carry -q still yields ids, not counts",
                 len(N.collect(PYTEST, str(root), 120, files=["tests/test_diff.py"])), 4)
        (root / "pytest.ini").unlink()

        # a project whose addopts carry -v cancels our -q (net verbosity 0), and
        # pytest prints the <Module>/<Function> tree instead of ids — the real case that
        # stopped the first live 0.7.8 run on S5.
        (root / "pytest.ini").write_text("[pytest]\naddopts = -v\n", encoding="utf-8")
        tree_ids = N.collect(PYTEST, str(root), 120, files=["tests/test_diff.py"])
        check_eq("a project whose addopts carry -v still yields ids, not an empty list",
                 sorted(tree_ids), sorted(ids))
        (root / "pytest.ini").unlink()

        cli = run_script("node_ids.py", "--cwd", root, "--ids", asked, "--", *PYTEST)
        check_eq("the CLI exits 0 when every id has a real spelling", cli.returncode, 0)
        check_eq("and prints the dict", json.loads(cli.stdout)["resolved"], {asked: ids[0]})
        cli = run_script("node_ids.py", "--cwd", root, "--ids",
                         "tests/test_diff.py::test_gone", "--", *PYTEST)
        check_eq("the CLI exits 2 on a missing id", cli.returncode, 2)
    finally:
        cleanup(root)


def collect_errors() -> None:
    root = project()
    try:
        (root / "tests" / "test_broken.py").write_text("import not_a_module_anywhere\n",
                                                       encoding="utf-8")
        canned(root, "ERROR tests/test_broken.py\nE   ModuleNotFoundError: No module named "
                     "'not_a_module_anywhere'\n", 2)
        try:
            N.collect(PYTEST, str(root), 120, files=["tests/test_diff.py", "tests/test_broken.py"])
            check("a collection error raises CollectError", False)
        except N.CollectError as exc:
            check_in("a collection error raises CollectError with the cause in its head",
                     "not_a_module_anywhere", exc.head)
            check("the head is capped", len(exc.head.encode("utf-8")) <= N.HEAD_MAX_BYTES)

        got = N.check_request(PYTEST, str(root),
                              ["tests/test_diff.py::test_plain", "tests/test_broken.py::test_x"],
                              120)
        check_eq("check_request then blocks nothing: nothing resolved, nothing missing",
                 (got["resolved"], got["missing"]), ({}, []))
        check_in("and hands the head over as collect_error", "not_a_module_anywhere",
                 got.get("collect_error", ""))
        check("with the reason in notes", bool(got["notes"]))

        canned(root, "ERROR: file or directory not found: tests/test_nowhere.py\n", 4)
        got = N.check_request(PYTEST, str(root), ["tests/test_nowhere.py::test_x"], 120)
        check_in("a file that does not exist is a collect error, in pytest's own words",
                 "not found", got.get("collect_error", ""))

        got = N.check_request([str(root / "no-such-venv" / "pytest")], str(root),
                              ["tests/test_diff.py::test_plain"], 5)
        check("a command that cannot start is a collect error, never an exception",
              "collect_error" in got and not got["missing"], got)
    finally:
        cleanup(root)


def banners() -> None:
    """EP1-9: a harness that greets the run with a `=` banner before the ids no longer reads as zero tests."""
    ids = N.parse_collected("=== My Harness v2 ===\ntests/api/test_a.py::test_x\ntests/api/test_a.py::test_y\n"
                            "\n2 tests collected in 0.01s\n")
    check_eq("a `=` banner before the ids is skipped and every id parses",
             ids, ["tests/api/test_a.py::test_x", "tests/api/test_a.py::test_y"])
    ids = N.parse_collected("tests/api/test_a.py::test_x\n==== warnings summary ====\ntests/api/test_a.py::test_z\n"
                            "  DeprecationWarning: x\n2 tests collected in 0.01s\n")
    check_eq("a `=` section after the ids still ends the parse (its id-looking lines are not ids)",
             ids, ["tests/api/test_a.py::test_x"])
    check_eq("a plain banner line without `::` is ignored as before",
             N.parse_collected("My Harness v2\ntests/a.py::test_a\n"), ["tests/a.py::test_a"])
    real_run = N._run
    N._run = lambda *a, **k: (0, "=== banner ===\n3 tests collected in 0.01s\n")
    try:
        N.collect(["pytest"], ".", 5)
        check("an exit 0 with a count pytest parsed but no id read is a refusal, never zero tests", False)
    except N.CollectError as exc:
        check_in("an exit 0 with a count but no id read is a refusal that names the count",
                 "collected 3 test(s) but none could be parsed", str(exc))
        check_in("and hands the output's head over", "=== banner ===", exc.head)
    finally:
        N._run = real_run
    # A1 (critic): pytest's deselected form `3/4 tests collected (1 deselected)` is a count too
    N._run = lambda *a, **k: (0, "=== banner ===\n3/4 tests collected (1 deselected) in 0.06s\n")
    try:
        N.collect(["pytest"], ".", 5)
        check("the deselected form with no id read is a refusal, never zero tests", False)
    except N.CollectError as exc:
        check_in("the deselected form is refused and names the 3 that were collected",
                 "collected 3 test(s) but none could be parsed", str(exc))
    finally:
        N._run = real_run
    # A2 (critic): the count verdict is ONE function, shared with the gate's collect
    check_eq("unread_count: exit 0, no id, `N tests collected` -> N", N.unread_count(0, "x\n7 tests collected in 1s\n"), 7)
    check_eq("unread_count: one test (singular)", N.unread_count(0, "1 test collected in 0.01s\n"), 1)
    check_eq("unread_count: the deselected form -> the collected side", N.unread_count(0, "3/4 tests collected (1 deselected)\n"), 3)
    check_eq("unread_count: a `==` decorated count line", N.unread_count(0, "==== 5 tests collected in 0.1s ====\n"), 5)
    check_eq("unread_count: ids were read -> 0", N.unread_count(0, "a/test_a.py::t\n1 test collected\n"), 0)
    check_eq("unread_count: a non-zero exit is not this verdict -> 0", N.unread_count(2, "3 tests collected\n"), 0)
    check_eq("unread_count: exit 5 -> 0", N.unread_count(5, "3 tests collected\n"), 0)
    check_eq("unread_count: empty output, no count line -> 0 (nothing collected, as before)", N.unread_count(0, ""), 0)
    check_eq("unread_count: `0 tests collected` -> 0", N.unread_count(0, "0 tests collected in 0.01s\n"), 0)
    check_eq("unread_count: `no tests collected` has no number -> 0", N.unread_count(0, "no tests collected in 0.01s\n"), 0)
    N._run = lambda *a, **k: (0, "")
    try:
        check_eq("exit 0 with empty output and no count line is still an empty list", N.collect(["pytest"], ".", 5), [])
    finally:
        N._run = real_run
    N._run = lambda *a, **k: (5, "no tests ran\n")
    try:
        check_eq("an exit 5 with nothing collected is still an empty list", N.collect(["pytest"], ".", 5), [])
    finally:
        N._run = real_run
    # EP1-9 (2): the gate's own reader of the same output is this parser, so the two cannot disagree (AR-13)
    import gate_preflight
    out = "=== My Harness v2 ===\napi/test_a.py::test_x\nui/test_b.py::test_y\n==== warnings summary ====\nui/test_c.py::test_z\n"
    check_eq("the gate's first_collected_node reads through parse_collected: the banner is skipped",
             gate_preflight.first_collected_node(out), "api/test_a.py::test_x")
    check_eq("and the prefix still narrows it to the profile's own tests",
             gate_preflight.first_collected_node(out, "ui"), "ui/test_b.py::test_y")
    check_eq("an id inside the warnings section is not offered", gate_preflight.first_collected_node(out, "nowhere"), "")


FLAG = "--continue-on-collection-errors"


def _broken_project() -> Path:
    """A real project with `addopts = -v`: a healthy module (one `api` test), a broken MODULE (i), a broken FOLDER
    whose conftest cannot import (ii)."""
    root = temp_dir("qa-node-ids-broken-")
    (root / "pytest.ini").write_text("[pytest]\naddopts = -v\nmarkers =\n    api: the api level\n", encoding="utf-8")
    tests = root / "tests"
    (tests / "sub").mkdir(parents=True)
    (tests / "test_ok.py").write_text("import pytest\n\n\n@pytest.mark.api\ndef test_a():\n    pass\n\n\n"
                                      "def test_b():\n    pass\n", encoding="utf-8")
    (tests / "test_bad.py").write_text("import module_nobody_has_zz\n\n\ndef test_c():\n    pass\n",
                                       encoding="utf-8")
    (tests / "sub" / "conftest.py").write_text("import conftest_module_nobody_has_zz\n", encoding="utf-8")
    (tests / "sub" / "test_s.py").write_text("def test_s():\n    pass\n", encoding="utf-8")
    return root


def _raw(root: Path, *args) -> tuple:
    """(exit code, text) of a bare `pytest --collect-only` over `root` - no factory code between."""
    import os
    import subprocess
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8")
    done = subprocess.run(PYTEST + ["--collect-only", *args], cwd=str(root), env=env, capture_output=True,
                          text=True, encoding="utf-8", errors="replace", timeout=180)
    return done.returncode, "\n".join((done.stdout + "\n" + done.stderr).splitlines())


def measurement() -> None:
    """3.0 (RH1-3): the pytest facts the collect classifier stands on, measured on the REAL pytest. Without it the
    function prints `skipped` and exits 0, but no key counts. The values are those of the plan review's table
    (pytest 8.3.3); a divergence on another pytest is a line of the report, the values of 3.1 come from this run."""
    if not HAVE_PYTEST:
        print("skipped: no pytest (the measurement keys K-3.0-* are not counted)")
        return
    import pytest
    print("K-3.0 pytest.__version__ =", pytest.__version__)
    root = _broken_project()
    try:
        for label, extra in (("without the flag", []), ("with the flag", [FLAG])):
            code, text = _raw(root, *extra, "-q", "-q")
            ids = N.parse_collected(text)
            check_eq(f"K-3.0-i {label}: the healthy ids are printed", sorted(ids),
                     ["tests/test_ok.py::test_a", "tests/test_ok.py::test_b"])
            check_in(f"K-3.0-i {label}: the count line carries the errors", "2 tests collected, 2 errors", text)
            check_in(f"K-3.0-i {label}: a broken module is `ERROR <path>` with no cause", "\nERROR tests/test_bad.py\n",
                     "\n" + text + "\n")
            check_in(f"K-3.0-ii {label}: a broken folder's conftest names the FOLDER, with its cause",
                     "ERROR tests/sub - ModuleNotFoundError", text)
        code, text = _raw(root, "-q", "-q")
        check_eq("K-3.0-viii without the flag the exit is 2 and the run is `Interrupted`", code, 2)
        check_in("K-3.0-viii the interruption is printed", "Interrupted: 2 errors during collection", text)
        code, text = _raw(root, FLAG, "-q", "-q")
        check_eq("K-3.0-i with the flag the exit is 1", code, 1)
        check("K-3.0-i with the flag there is no interruption line", "Interrupted" not in text)

        code, text = _raw(root, FLAG, "-q", "-q", "-x")
        check_eq("K-3.0-iv `-x` stops the collect: exit 1", code, 1)
        check_in("K-3.0-iv and says so", "stopping after 1 failures", text)
        check_in("K-3.0-iv one error only", "1 error", text)

        for label, extra in (("without the flag", []), ("with the flag", [FLAG])):
            code, text = _raw(root, *extra, "-q", "-q", "-m", "api")
            check_eq(f"K-3.0-v {label}: `-m` keeps the one api test", N.parse_collected(text),
                     ["tests/test_ok.py::test_a"])
            check_in(f"K-3.0-v {label}: the deselected form with the errors", "1/2 tests collected (1 deselected), 2 errors",
                     text)
        for label, extra in (("without the flag", []), ("with the flag", [FLAG])):
            code, text = _raw(root, *extra, "-q", "-q", "-m", "nosuchlevel")
            check_eq(f"K-3.0-v-b {label}: `-m` that takes every healthy test reads no id", N.parse_collected(text), [])
            check_in(f"K-3.0-v-b {label}: the REAL line is `no tests collected (2 deselected), 2 errors`, never `0/2`",
                     "no tests collected (2 deselected), 2 errors", text)
        verdict = N.collect_verdict(1, text, _form())
        check_eq("K-3.0-v-b the real line reads none_selected (selected 0, total 2), never all_broken",
                 (verdict["kind"], verdict["selected"], verdict["total"]), ("none_selected", 0, 2))
        code, text = _raw(root, FLAG, "-q")
        check_eq("K-3.0-vi net verbosity 0 (our -q and addopts -v): exit 1", code, 1)
        check_eq("K-3.0-vi the tree, not flat ids: no id is read", N.parse_collected(text), [])
        check("K-3.0-vi the tree tag is there", bool(N.TREE_TAG_RE.search(text)), text[:200])
        check_in("K-3.0-vi the count line is still there", "2 tests collected, 2 errors", text)
        code, text = _raw(root, FLAG, "-q", "-q", "-q")
        check_eq("K-3.0-vii net verbosity -2: exit 1", code, 1)
        check_eq("K-3.0-vii `file.py: N` lines, no flat id", N.parse_collected(text), [])
        check("K-3.0-vii there is a `file.py: N` line", "tests/test_ok.py: 2" in text, text[-300:])
        check("K-3.0-vii and no count line", "tests collected" not in text, text[-300:])

        (root / "tests" / "conftest.py").write_text("import root_conftest_nobody_has_zz\n", encoding="utf-8")
        for label, extra in (("without the flag", []), ("with the flag", [FLAG])):
            code, text = _raw(root, *extra, "-q", "-q")
            check_eq(f"K-3.0-iii a broken ROOT conftest {label}: exit 4", code, 4)
            check_in(f"K-3.0-iii {label}: `ImportError while loading conftest`", "ImportError while loading conftest",
                     text)
    finally:
        cleanup(root)

    # (ix) B2: a CLASS whose collection fails is named as the class node, while its file still gives other ids
    root = temp_dir("qa-node-ids-class-")
    try:
        (root / "tests").mkdir()
        (root / "tests" / "test_a.py").write_text(
            "import pytest\n\n\ndef test_ok():\n    pass\n\n\nclass TestX:\n"
            "    @pytest.mark.parametrize('v', [1], ids=['one', 'two'])\n    def test_n(self, v):\n        pass\n",
            encoding="utf-8")
        code, text = _raw(root, FLAG, "-q")      # no addopts here: one -q is the flat list
        check_eq("K-3.0-ix the file still gives its healthy id", N.parse_collected(text), ["tests/test_a.py::test_ok"])
        check_in("K-3.0-ix pytest names the CLASS node, not the file", "ERROR tests/test_a.py::TestX", text)
        verdict = N.collect_verdict(code, text, _form())
        check_eq("K-3.0-ix the verdict is partial, the broken path is the class node",
                 (verdict["kind"], [b["path"] for b in verdict["broken"]]), ("partial", ["tests/test_a.py::TestX"]))
        got = N.match_partial(["tests/test_a.py::TestX::test_n[one]", "tests/test_a.py::test_ok", "tests/test_a.py::test_gone"],
                              verdict["ids"], verdict["broken"])
        check_eq("K-3.0-ix B2 a test under the broken class is unverified, never missing with a nearest id; a healthy one resolves; "
                 "a test absent from the healthy part is still missing",
                 ([u["asked"] for u in got["unverified"]], list(got["resolved"]), [m["asked"] for m in got["missing"]]),
                 (["tests/test_a.py::TestX::test_n[one]"], ["tests/test_a.py::test_ok"], ["tests/test_a.py::test_gone"]))
    finally:
        cleanup(root)


def _form() -> dict:
    import launch_check
    row, problem = launch_check.runner_row(["pytest"])
    check("the shipped pytest row is readable", row is not None, problem)
    return row


GOOD = "tests/test_ok.py::test_a\ntests/test_ok.py::test_b\n"
SUMMARY = ("\n==== short test summary info ====\nERROR tests/test_bad.py\n"
           "ERROR tests/sub - ModuleNotFoundError: No module named 'x'\n"
           "!!!!!!!!!! Interrupted: 2 errors during collection !!!!!!!!!!\n")
COUNT2 = "2 tests collected, 2 errors in 1.2s\n"


def verdicts() -> None:
    """3.2: `collect_verdict` - one reading of the outcome; the uncomfortable inputs of the spec's section 5."""
    form = _form()
    v = N.collect_verdict(1, GOOD + SUMMARY + COUNT2, form)
    check_eq("K-3.2-partial a finished collect, a count that equals the broken files named: partial",
             (v["kind"], v["ids"], [b["path"] for b in v["broken"]], v["selected"], v["errors"]),
             ("partial", ["tests/test_ok.py::test_a", "tests/test_ok.py::test_b"], ["tests/test_bad.py", "tests/sub"], 2, 2))
    check_eq("K-3.2-nohead a module line with no ` - cause` has an empty head, a folder line keeps its cause",
             [b["head"] for b in v["broken"]], ["", "ModuleNotFoundError: No module named 'x'"])
    section = ("____ ERROR collecting tests/test_bad.py ____\nImportError while importing\nTraceback:\n"
               "E   ModuleNotFoundError: No module named 'zz'\n")
    v = N.collect_verdict(1, GOOD + section + SUMMARY + COUNT2, form)
    check_eq("K-3.2-nohead the head of a module line comes from the `E   ` line of its section",
             v["broken"][0], {"path": "tests/test_bad.py", "head": "ModuleNotFoundError: No module named 'zz'"})
    long_cause = "ERROR tests/test_bad.py - " + "x" * 400 + "\n"
    check_eq("K-3.2-nohead a head is capped", len(N.collect_verdict(
        1, GOOD + long_cause + "ERROR tests/sub\n1 test collected, 2 errors in 1s\n", form)["broken"][0]["head"]), 180)

    # M1: the count must equal the number of broken files named
    banner = GOOD + "ERROR tests/test_bad.py\nERROR HARNESS-V2\n" + "2 tests collected, 1 error in 1s\n"
    v = N.collect_verdict(1, banner, form)
    check_eq("K-3.2-count a count that disagrees with the paths named (a banner `ERROR ...`) is unread, never partial",
             v["kind"], "unread")
    check_eq("K-3.2-count no count line at all: unread", N.collect_verdict(1, GOOD + "ERROR tests/test_bad.py\n", form)["kind"],
             "unread")
    check_eq("K-3.2-count exit 1 with no broken file named and nothing to explain it: unread",
             N.collect_verdict(1, GOOD + "2 tests collected in 1s\n", form)["kind"], "unread")
    check_eq("K-3.2-count empty output, exit 1: unread", N.collect_verdict(1, "", form)["kind"], "unread")
    check_eq("K-3.2-count tests counted but none read: unread",
             N.collect_verdict(1, "ERROR tests/test_bad.py\n3 tests collected, 1 error in 1s\n", form)["kind"], "unread")

    check_eq("K-3.2-all nothing collected and a broken file: all_broken (never `no tests`)",
             N.collect_verdict(1, "ERROR tests/test_bad.py - ImportError: x\nno tests collected, 1 error in 1s\n", form)["kind"],
             "all_broken")
    check_eq("K-3.2-all ... also `0 tests collected, 1 error`",
             N.collect_verdict(1, "ERROR tests/test_bad.py\n0 tests collected, 1 error in 1s\n", form)["kind"], "all_broken")
    check_eq("K-3.2-all exit 5 stays the filter's fact, not all_broken",
             N.collect_verdict(5, "no tests collected in 0.1s\n", form)["kind"], "complete")
    v = N.collect_verdict(1, "ERROR tests/test_bad.py\nno tests collected (5 deselected), 1 error in 1s\n", form)
    check_eq("K-3.2-deselected the REAL line when a filter took every healthy test with one broken file: none_selected, "
             "not all_broken (B1)", (v["kind"], v["selected"], v["total"]), ("none_selected", 0, 5))
    check_eq("K-3.2-deselected ... and `no tests collected, 1 error` (nothing deselected) is still all_broken",
             N.collect_verdict(1, "ERROR tests/test_bad.py\nno tests collected, 1 error in 1s\n", form)["kind"], "all_broken")
    check_eq("K-3.2-deselected ... plural `2 errors` with the deselected group",
             N.collect_verdict(1, "ERROR a.py\nERROR b.py\nno tests collected (3 deselected), 2 errors in 1s\n", form)["kind"],
             "none_selected")
    v = N.collect_verdict(1, "tests/a.py::t\nERROR tests/test_bad.py\n1/6 tests collected (5 deselected), 1 error in 1s\n", form)
    check_eq("K-3.2-deselected a filter that left some: partial", v["kind"], "partial")

    stopped = "tests/a.py::t\nERROR tests/test_bad.py\n!!!! stopping after 1 failures !!!!\n1 test collected, 1 error in 1s\n"
    check_eq("K-3.2-stopped a collect cut short by -x is stopped, never partial",
             N.collect_verdict(1, stopped, form)["kind"], "stopped")

    check_eq("K-3.2-root a root conftest that cannot load (exit 4) is failed",
             N.collect_verdict(4, "ImportError while loading conftest\n", form)["kind"], "failed")
    check_eq("K-3.2-noform without a form exit 1 is failed, as before",
             N.collect_verdict(1, GOOD + SUMMARY + COUNT2, None)["kind"], "failed")
    check_eq("K-3.2-noform ... exit 2 too, and 0 / 5 complete",
             [N.collect_verdict(c, GOOD, None)["kind"] for c in (2, 0, 5)], ["failed", "complete", "complete"])
    check_eq("K-3.2-noform a row with no partial_exits reads exit 1 as failed",
             N.collect_verdict(1, GOOD + SUMMARY + COUNT2, {"ok_exits": [0, 5]})["kind"], "failed")
    check_eq("K-3.2-noform exit 0 with a count and no id read is unread (EP1-9, folded in)",
             N.collect_verdict(0, "=== banner ===\n3 tests collected in 1s\n", form)["kind"], "unread")
    check_eq("K-3.2-backslash a path printed with backslashes is kept with `/`",
             N.collect_verdict(1, "a.py::t\nERROR tests\\test_bad.py\n1 test collected, 1 error in 1s\n", form)["broken"][0]["path"],
             "tests/test_bad.py")
    check_eq("K-3.2-dup the same path twice is one broken file (and the count then disagrees: unread)",
             [N.collect_verdict(1, "a.py::t\nERROR t/x.py\nERROR t/x.py\n1 test collected, 2 errors in 1s\n", form)[k]
              for k in ("kind",)] + [len(N.collect_verdict(
                  1, "a.py::t\nERROR t/x.py\nERROR t/x.py\n1 test collected, 2 errors in 1s\n", form)["broken"])],
             ["unread", 1])
    check_eq("unread_count reads a partial exit like exit 0 when the form lists it",
             (N.unread_count(1, "ERROR x\n3 tests collected, 1 error in 1s\n", form),
              N.unread_count(1, "ERROR x\n3 tests collected, 1 error in 1s\n"),
              N.unread_count(1, "a.py::t\n3 tests collected\n", form)), (3, 0, 0))


def partial_matching() -> None:
    """3.2: `match_partial` - toward "not verified", never toward `missing` for a file that did not collect."""
    ids = ["tests/test_ok.py::test_a", "tests/test_ok.py::test_b[x]"]
    broken = [{"path": "tests/test_bad.py", "head": "ImportError: gone"},
              {"path": "tests/servicenow_budget", "head": "ModuleNotFoundError: no such sdk"}]
    got = N.match_partial(["tests/test_ok.py::test_a", "tests/test_ok.py::test_gone", "tests/test_bad.py::test_c",
                           "tests/servicenow_budget/test_x.py::test_d", "tests/servicenow_budget_x/test_y.py::test_e",
                           "other/test_z.py::test_f"], ids, broken)
    check_eq("K-3.2-dir a healthy file is resolved", got["resolved"], {"tests/test_ok.py::test_a": "tests/test_ok.py::test_a"})
    check_eq("K-3.2-root a test absent from a HEALTHY file is still missing",
             [m["asked"] for m in got["missing"]], ["tests/test_ok.py::test_gone"])
    reasons = {u["asked"]: u["reason"] for u in got["unverified"]}
    check_eq("K-3.2-root an id of a broken file is unverified with the cause, never missing",
             reasons["tests/test_bad.py::test_c"], "file tests/test_bad.py could not be collected: ImportError: gone")
    check_eq("K-3.2-dir an id under a broken FOLDER is unverified with the folder's cause",
             reasons["tests/servicenow_budget/test_x.py::test_d"],
             "file tests/servicenow_budget could not be collected: ModuleNotFoundError: no such sdk")
    check_eq("K-3.2-dir a neighbour with a common prefix is NOT covered by the folder (whole components)",
             reasons["tests/servicenow_budget_x/test_y.py::test_e"],
             "file tests/servicenow_budget_x/test_y.py yielded no test in this collect")
    check_eq("K-3.2-root a file nobody named yielded nothing: unverified, never missing",
             reasons["other/test_z.py::test_f"], "file other/test_z.py yielded no test in this collect")
    check_eq("K-3.2-root the notes say what is not verified and why", len(got["notes"]), 4)
    check_eq("K-3.2-root a rootdir-relative broken path against a cwd-relative asked path is not compared: no test",
             N.match_partial(["sub/test_s.py::t"], ids, [{"path": "tests/sub", "head": ""}])["unverified"][0]["reason"],
             "file sub/test_s.py yielded no test in this collect")
    check_eq("K-3.2-root a broken file nothing asked for changes nothing",
             N.match_partial(["tests/test_ok.py::test_a"], ids, broken)["unverified"], [])
    win = N.match_partial(["tests\\test_bad.py::test_c"], ids, broken)
    check_eq("K-3.2-backslash an asked path with backslashes is covered by the broken path",
             win["unverified"][0]["reason"].startswith("file tests/test_bad.py could not be collected"), True)
    check_eq("K-3.2-all with no ids at all every asked id is unverified (nothing is missing)",
             (N.match_partial(["tests/test_ok.py::test_a"], [], broken)["missing"],
              len(N.match_partial(["tests/test_ok.py::test_a"], [], broken)["unverified"])), ([], 1))
    check_eq("K-3.2-dir an asked directory with a healthy file under it is present",
             N.match_partial(["tests"], ids, broken)["missing"], [])

    # B2: a broken CLASS node of a file that gave other ids (pytest names `file.py::TestX`, not the file)
    node = [{"path": "tests/test_a.py::TestX", "head": ""}, {"path": "tests/test_a.py::TestY::TestInner", "head": ""}]
    healthy = ["tests/test_a.py::test_ok", "tests/test_a.py::TestZ::test_z"]
    got = N.match_partial(["tests/test_a.py::TestX::test_n", "tests/test_a.py::TestX::test_n[p-1]",
                           "tests/test_a.py::TestY::TestInner::test_i", "tests/test_a.py::TestXtra::test_q",
                           "tests/test_a.py::TestZ::test_z", "tests\\test_a.py::TestX::test_w"], healthy, node)
    check_eq("K-3.2-class an id under a broken class (its own, a parametrized one, a nested one, backslashes) is unverified; "
             "a class that merely shares the prefix is NOT covered; a healthy one resolves",
             ([u["asked"] for u in got["unverified"]], [m["asked"] for m in got["missing"]], list(got["resolved"])),
             (["tests/test_a.py::TestX::test_n", "tests/test_a.py::TestX::test_n[p-1]", "tests/test_a.py::TestY::TestInner::test_i",
               "tests\\test_a.py::TestX::test_w"], ["tests/test_a.py::TestXtra::test_q"], ["tests/test_a.py::TestZ::test_z"]))
    check_eq("K-3.2-class the unverified reason names the class node",
             got["unverified"][0]["reason"], "file tests/test_a.py::TestX could not be collected")
    check_eq("K-3.2-class the head of a class node comes from the section of its file",
             N.collect_verdict(1, "tests/test_a.py::test_ok\nERROR tests/test_a.py::TestX\n____ ERROR collecting tests/test_a.py ____\n"
                                  "E   ValueError: duplicate ids\n1 test collected, 1 error in 1s\n", _form())["broken"][0]["head"],
             "ValueError: duplicate ids")


def siblings() -> None:
    """Critic answer 6 (fix round t-1450): the callers of `check_request` that had no runner row - the CLI, the sandbox
    (`red_sandbox.check_node_ids`) and the manifest writer (`manifest_from_tests.resolve_through_pytest`) - pass it, so their ONE
    collect carries the continue flag (killing: a call without the row has no flag on the command)."""
    import contextlib
    import io
    row, note = N.runner_form(["pytest"])
    check_eq("runner_form: the pytest row, no note", (row is not None and row.get("partial_exits"), note), ([1], ""))
    check_eq("runner_form: a command no row recognises has no row and no note", N.runner_form(["go", "test"]), (None, ""))
    out = "tests/test_ok.py::test_a\nERROR tests/test_bad.py\n1 test collected, 1 error in 1s\n"
    calls = []
    real_run = N._run
    N._run = lambda command, cwd, timeout_s: (calls.append(list(command)) or (1, out))
    saved_argv = sys.argv
    try:
        sys.argv = ["node_ids.py", "--ids", "tests/test_ok.py::test_a", "tests/test_bad.py::test_c", "--", "pytest"]
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = N.main()
        got = json.loads(buf.getvalue())
        check_eq("sibling CLI: the flag is on the collect, the broken file's id is unverified and nothing is missing",
                 (N_FLAG in calls[0], rc, got["missing"], [u["asked"] for u in got["unverified"]]),
                 (True, 0, [], ["tests/test_bad.py::test_c"]))
        import red_sandbox as RSB
        calls.clear()
        dest = temp_dir("qa-node-ids-sibling-")
        try:
            done = RSB.check_node_ids(dest.resolve(), {"collect": {"argv": ["pytest"], "cwd": "."}},
                                      [{"node_id": "tests/test_ok.py::test_a"}, {"node_id": "tests/test_bad.py::test_c"}])
            check_eq("sibling red_sandbox.check_node_ids: the flag is on the collect, the verdict is verified",
                     (N_FLAG in calls[0], done["status"]), (True, "verified"))
        finally:
            cleanup(dest)
        import manifest_from_tests as MFT
        calls.clear()
        MFT.resolve_through_pytest({"tests": [{"instance_id": "test_a", "file": "tests/test_ok.py"},
                                              {"instance_id": "test_c", "file": "tests/test_bad.py"}]}, ["pytest"], ".", [])
        check_eq("sibling manifest_from_tests.resolve_through_pytest: the flag is on the collect", N_FLAG in calls[0], True)
    finally:
        N._run = real_run
        sys.argv = saved_argv
    check_eq("broken_names: the one names text, K more counted", (N.broken_names([{"path": "a"}, {"path": "b"}, {"path": "c"}], 2),
             N.broken_names([{"path": "a"}])), ("a, b (+1 more)", "a"))


def partial_collect() -> None:
    """3.2: `collect_output` / `collect` / `check_request` with the shipped form: the flag, the shape retries at a
    partial exit (B2), the error kinds, and the real pytest end to end."""
    form = _form()
    calls = []
    real_run = N._run

    def fake(code, text):
        def run(command, cwd, timeout_s):
            calls.append(list(command))
            return code, text
        return run

    try:
        N._run = fake(1, GOOD + SUMMARY + COUNT2)
        try:
            N.collect(["pytest"], ".", 5, form=form)
            check("K-3.2-partial a partial collect raises", False)
        except N.CollectError as exc:
            check_eq("K-3.2-partial the error is kind partial, with the healthy ids and the broken files",
                     (exc.kind, exc.ids, [b["path"] for b in exc.broken]),
                     ("partial", ["tests/test_ok.py::test_a", "tests/test_ok.py::test_b"], ["tests/test_bad.py", "tests/sub"]))
            check_in("K-3.2-partial the message names the files", "tests/test_bad.py, tests/sub", exc.message)
        check_eq("K-3.2-flag the flag from the row is added to the one collect", calls[0][-1], N_FLAG)
        calls.clear()
        N.collect_output(["pytest", N_FLAG], ".", 5, form=form)
        check_eq("K-3.2-dup a flag already in argv is not added twice", calls[0].count(N_FLAG), 1)
        calls.clear()
        N.collect_output(["pytest"], ".", 5)
        check("K-3.2-noform with no form no flag is added (the code carries no flag of its own)", N_FLAG not in calls[0], calls)

        for label, code, text, kind in (
                ("all_broken", 1, "ERROR tests/test_bad.py - E: x\nno tests collected, 1 error in 1s\n", "exit"),
                ("stopped", 1, "a.py::t\nERROR tests/test_bad.py\n!!! stopping after 1 failures !!!\n1 test collected, 1 error in 1s\n",
                 "stopped"),
                ("unread", 1, "a.py::t\nERROR tests/test_bad.py\n", "unread"),
                ("none_selected", 1, "ERROR tests/test_bad.py\nno tests collected (5 deselected), 1 error in 1s\n", "partial"),
                ("a usage error", 4, "ERROR: file or directory not found\n", "exit")):
            N._run = fake(code, text)
            try:
                N.collect(["pytest"], ".", 5, form=form)
                check(f"K-3.2-{label} raises", False)
            except N.CollectError as exc:
                check_eq(f"K-3.2-{label} the kind of the error", exc.kind, kind)
        N._run = fake(1, "")
        try:
            N.collect(["pytest"], ".", 5, form=form)
            check("K-3.2-count empty output, exit 1: an error", False)
        except N.CollectError as exc:
            check_eq("K-3.2-count empty output, exit 1: unread, never an empty list", exc.kind, "unread")
        N._run = fake(0, GOOD)
        check_eq("K-3.2-complete exit 0 still returns the list", N.collect(["pytest"], ".", 5, form=form),
                 ["tests/test_ok.py::test_a", "tests/test_ok.py::test_b"])

        # B2 (M6): the shape retries run at the partial exit too
        outputs = iter([(1, "<Dir x>\n  <Module test_ok.py>\n    <Function test_a>\nERROR tests/test_bad.py\n"
                            "==== 2 tests collected, 1 error in 1s ====\n"),
                        (1, "tests/test_ok.py::test_a\ntests/test_ok.py::test_b\nERROR tests/test_bad.py\n"
                            "2 tests collected, 1 error in 1s\n")])
        calls.clear()
        N._run = lambda command, cwd, timeout_s: (calls.append(list(command)) or next(outputs))
        code, text = N.collect_output(["pytest"], ".", 5, form=form)
        check_eq("K-3.2-tree-partial a tree at exit 1 is retried with one more -q",
                 (len(calls), calls[1][-1], N.collect_verdict(code, text, form)["kind"]), (2, "-q", "partial"))
        outputs = iter([(1, "tests/test_ok.py: 2\nERROR tests/test_bad.py\n"),
                        (1, "tests/test_ok.py::test_a\nERROR tests/test_bad.py\n2 tests collected, 1 error in 1s\n")])
        calls.clear()
        code, text = N.collect_output(["pytest"], ".", 5, form=form)
        check_eq("K-3.2-qq-partial `file.py: N` at exit 1 is retried with -v, then read",
                 (len(calls), calls[1][-1], N.collect_verdict(code, text, form)["kind"]), (2, "-v", "partial"))
        outputs = iter([(1, "tests/test_ok.py: 2\nERROR tests/test_bad.py\n")] * 2)
        calls.clear()
        code, text = N.collect_output(["pytest"], ".", 5, form=form)
        check_eq("K-3.2-qq-partial still no count line after the retry: unread",
                 (len(calls), N.collect_verdict(code, text, form)["kind"]), (2, "unread"))
        outputs = iter([(1, "<Dir x>\n  <Module test_ok.py>\n")])
        calls.clear()
        N.collect_output(["pytest"], ".", 5)
        check_eq("K-3.2-noform with no form a tree at exit 1 is not retried (exit 0 only, as before)", len(calls), 1)

        N._run = lambda *a, **k: (_ for _ in ()).throw(N.CollectError("collect timed out after 1s", kind="timeout"))
        try:
            N.collect(["pytest"], ".", 1, form=form)
            check("K-3.2-timeout a timeout raises", False)
        except N.CollectError as exc:
            check_eq("K-3.2-timeout a timeout stays a timeout, no partial output is read", (exc.kind, exc.ids), ("timeout", []))
        N._run = fake(1, GOOD + SUMMARY + COUNT2)
        got = N.check_request(["pytest"], ".", ["tests/test_ok.py::test_a", "tests/test_bad.py::test_c"], 5, form=form)
        check_eq("K-3.2-check check_request with a form: the healthy id resolved, the broken file unverified, nothing missing",
                 (list(got["resolved"]), got["missing"], [u["asked"] for u in got["unverified"]], "collect_error" in got),
                 (["tests/test_ok.py::test_a"], [], ["tests/test_bad.py::test_c"], False))
        got = N.check_request(["pytest"], ".", ["tests/test_ok.py::test_a"], 5)
        check_eq("K-3.2-check check_request without a form: exit 1 is a collect error, nothing resolved, as before",
                 (got["resolved"], got["missing"], "collect_error" in got), ({}, [], True))
    finally:
        N._run = real_run

    if not HAVE_PYTEST:
        return
    root = _broken_project()
    try:
        got = N.check_request(PYTEST, str(root), ["tests/test_ok.py::test_a", "tests/test_ok.py::test_zz",
                                                  "tests/test_bad.py::test_c"], 120, form=form)
        check_eq("K-3.2-live addopts -v (the tree) and a broken module: the healthy id is resolved",
                 list(got["resolved"]), ["tests/test_ok.py::test_a"])
        check_eq("K-3.2-live a test absent from the healthy file is missing",
                 [m["asked"] for m in got["missing"]], ["tests/test_ok.py::test_zz"])
        check_eq("K-3.2-live the module's id is not verified, never missing",
                 [u["asked"] for u in got["unverified"]], ["tests/test_bad.py::test_c"])
        # Measured (RH1-3): an explicit FILE under a folder whose conftest cannot import is a usage error, exit 4 -
        # the flag does not help; the whole collect is lost, which is the safe direction (nothing verified).
        got = N.check_request(PYTEST, str(root), ["tests/test_ok.py::test_a", "tests/sub/test_s.py::test_s"], 120, form=form)
        check_eq("K-3.2-live-conftest an asked file inside a folder with a broken conftest: not verified at all (exit 4)",
                 (got["resolved"], got["missing"], "ImportError while loading conftest" in got.get("collect_error", "")),
                 ({}, [], True))
        whole = N.collect_output(PYTEST, str(root), 120, ["tests"], form)
        check_eq("K-3.2-live a whole-folder collect names the broken folder as well as the module",
                 [b["path"] for b in N.collect_verdict(*whole, form)["broken"]], ["tests/sub", "tests/test_bad.py"])
        try:
            N.collect(PYTEST, str(root), 120, files=["tests"])
            check("K-3.2-live without the form the same project is an exit error", False)
        except N.CollectError as exc:
            check_eq("K-3.2-live without the form: exit, the whole collect lost (as before)", exc.kind, "exit")
        (root / "tests" / "test_bad.py").unlink()
        (root / "tests" / "sub" / "conftest.py").unlink()
        check_eq("K-3.2-live a healthy project through the form is a plain list",
                 len(N.collect(PYTEST, str(root), 120, files=["tests"], form=form)), 3)
    finally:
        cleanup(root)


N_FLAG = "--continue-on-collection-errors"

# EP1-1: the two batteries of the one predicate, pinned verbatim (the predicate gates the pytest path: a false "pytest"
# spoils another runner's command, a false "not pytest" loses a real pytest report).
PYTEST_TRUE = [
    ".venv/bin/python .venv/bin/pytest tests", "xvfb-run -a /v/bin/pytest",
    "docker compose exec web /app/.venv/bin/pytest", "env A=1 /v/bin/pytest",
    "poetry run --directory x /v/bin/pytest", "uv run --frozen /v/bin/pytest", "dotenv run -- /v/bin/pytest",
    "timeout 600 /v/bin/pytest", "C:\\v\\pytest.exe", '"pytest"', "python -m PYTEST", "pytest.cmd",
    "poetry run C:\\v\\pytest.exe", "python -m pytest", "poetry run python -m pytest --reruns 0",
    "tox -e pytest", "pytest --help",
]
PYTEST_FALSE = [
    "npx playwright test tests/pytest", "npx playwright test a/py.test", "npx playwright test pytest",
    "npx playwright test --grep pytest", "npx playwright test --list tests/pytest", "npx jest --rootDir pytest",
    "npm test -- pytest", "node scripts/run-playwright.mjs",
]


def pytest_hostile() -> None:
    """E-pytest-hostile: both batteries through the one predicate, and the edges around it."""
    for line in PYTEST_TRUE:
        check_eq(f"E-pytest-hostile: {line!r} is pytest", N.is_pytest(line.split()), True)
    for line in PYTEST_FALSE:
        check_eq(f"E-pytest-hostile: {line!r} is not pytest", N.is_pytest(line.split()), False)
    check_eq("E-pytest-hostile: no command is not pytest", [N.is_pytest([]), N.is_pytest(None)], [False, False])
    check_eq("E-pytest-hostile: the named remainder, a node on a path named pytest, counts as before",
             N.is_pytest(["node", "C:\\x\\pytest"]), True)
    check_eq("E-pytest-hostile: C:\\v\\pytest.exe at position 0 always counts (the slice to its left is empty)",
             N.is_pytest(["C:\\v\\pytest.exe", "--list"]), True)
    check_eq("E-pytest-hostile: pytest.bat and a quoted launcher with .cmd count",
             [N.is_pytest(["pytest.bat"]), N.is_pytest(["'C:\\v\\pytest.CMD'"])], [True, True])
    check_eq("E-pytest-hostile: -m with nothing after it is not pytest", N.is_pytest(["python", "-m"]), False)
    check_eq("E-pytest-hostile: another runner to the left is seen at its own prefix, not one slice",
             N._left_is_other_runner(["npx", "playwright", "test", "--list", "tests/pytest"], 4), True)
    import hooklib
    real = hooklib.direct_test_form

    def broken(_command, dialect="bash"):
        raise RuntimeError("reader down")
    hooklib.direct_test_form = broken
    try:
        check_eq("E-pytest-hostile: a reader that fails counts the command as before (False = no runner to the left)",
                 N.is_pytest(["npx", "playwright", "test", "tests/pytest"]), True)
    finally:
        hooklib.direct_test_form = real


def two_functions_one_battery() -> None:
    """The second name of the predicate (`execution_request.is_pytest_command`, 15+ importers) answers the same."""
    import execution_request as ER
    for line in PYTEST_TRUE + PYTEST_FALSE:
        check_eq(f"two functions on the battery: {line!r}", ER.is_pytest_command(line.split()),
                 N.is_pytest(line.split()))


def launch_and_streams() -> None:
    """EP1-35: `_run` launches through `project_env.checked_launch` (a refusal is `launch_failed`, not a missing runner), and
    `run_bounded(merge_stderr=False)` reads stdout and stderr apart."""
    import project_env as PE
    from unittest import mock
    script = "import sys; sys.stdout.write('out'); sys.stderr.write('err'); sys.exit(4)"
    merged = N.run_bounded([sys.executable, "-c", script], ".", None, 30)
    check_eq("run_bounded default: one stream (code, merged bytes)", (merged[0], len(merged), sorted(merged[1].decode())), (4, 2, sorted("outerr")))
    apart = N.run_bounded([sys.executable, "-c", script], ".", None, 30, merge_stderr=False)
    check_eq("run_bounded merge_stderr=False: (code, stdout, stderr) apart", apart, (4, b"out", b"err"))
    with mock.patch.object(PE, "checked_launch", side_effect=PE.CmdUnsafe("a&b", "x.cmd")):
        try:
            N._run(["x.cmd", "a&b"], ".", 5)
            kind = None
        except N.CollectError as exc:
            kind = (exc.kind, "cannot be passed safely" in str(exc))
    check_eq("_run: CmdUnsafe is a CollectError launch_failed carrying the refusal", kind, ("launch_failed", True))
    with mock.patch.object(PE, "checked_launch", return_value=[sys.executable, "-c", "print('hello')"]) as launched:
        code, text = N._run(["bare-name"], ".", 30)
    check_eq("_run: the process is the one checked_launch resolved", (launched.call_args.args[0], code, text), (["bare-name"], 0, "hello"))


def main() -> None:
    launch_and_streams()
    pytest_hostile()
    two_functions_one_battery()
    measurement()
    verdicts()
    partial_matching()
    partial_collect()
    siblings()
    matching()
    command()
    banners()
    collecting()
    collect_errors()
    selftest = run_script("node_ids.py", "--selftest")
    check_eq("node_ids.py --selftest passes", selftest.returncode, 0)
    finish("test_node_ids")


if __name__ == "__main__":
    main()
