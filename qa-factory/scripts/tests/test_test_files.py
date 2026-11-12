#!/usr/bin/env python3
"""B-407 A: `test_files.py`, the one question "is this a test file", answered per consumer.

The unsafe error differs by consumer (the table in the module's docstring): a commit that skips a rule, a
production row that is lost, noise in advice. This file pins that table row by row with the verdict replaced by a
table of facts (K-A3), the unreadable names (E-A1), the folder / empty / backslash spellings (E-A9), the extras
that may be absent or malformed (E-A13), and the superset claim against the recognizers this module replaced
(K-A2). The handoff's own rule, and the mutation "a handoff that accepts a `run.levels` match as a test" - they
are killed here by the production rows.
"""
import contextlib
import io
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import SCRIPTS, check, check_eq, check_in, cleanup, finish, temp_dir  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import hooklib  # noqa: E402
import test_files as TF  # noqa: E402


def fact(test: bool, source: str = "test_locations", kind: str = "folder") -> dict:
    """A six-key verdict the way `test_locations.is_test_path` shapes it."""
    return {"test": test, "by": ("markers" if source == "markers" else "config") if test else "none",
            "source": source if test else "", "kind": kind if test else "", "where": "", "reason": "stub"}


@contextlib.contextmanager
def said(**verdicts):
    """Replace `TF.verdict`: `verdicts` maps a path to its fact; any other path is no test."""
    real = TF.verdict
    TF.verdict = lambda path, cfg, *, base=None, root=None: verdicts.get(str(path), fact(False))
    try:
        yield
    finally:
        TF.verdict = real


@contextlib.contextmanager
def markers_file(content=None):
    """The markers file replaced: None = no file at all, a dict = its JSON. stderr is captured (the note)."""
    real_ref = hooklib.ref
    folder = Path(tempfile.mkdtemp(prefix="qa-tf-markers-"))
    err = io.StringIO()
    TF._NOTED.clear()
    try:
        hooklib.ref = lambda rel: folder / rel
        if content is not None:
            (folder / TF.MARKERS_FILE).write_text(json.dumps(content), encoding="utf-8")
        with contextlib.redirect_stderr(err):
            yield err
    finally:
        hooklib.ref = real_ref
        TF._NOTED.clear()
        cleanup(folder)


FOUR = {"dir_names": ["tests", "test-harness", "spec"], "dir_suffixes": [".tests"], "stem_prefixes": ["test_"],
        "stem_suffixes": [".spec", "_test"]}
FULL = dict(FOUR, stem_camel_suffixes=["Tests", "IT"], code_extensions=[".py", ".cs", ".ts"])


def part_consumers() -> None:
    """K-A3: one case per row of the consumer table, verdict replaced."""
    real = TF.verdict
    # --- commit: v.test or markers; unreadable markers are None (the guard checks) ---
    with said(**{"x/word.txt": fact(True)}):
        check_eq("commit: the project's word is a test", TF.is_test_for("commit", "x/word.txt"), True)
        check_eq("commit: the usual names are one too, past the verdict", TF.is_test_for("commit", "tests/a.py"), True)
        check_eq("commit: neither is not", TF.is_test_for("commit", "src/a.py"), False)
    # --- test_code: a code file, then names, or the project's word unless it names a folder ---
    with said(**{"qa/helpers/latest.py": fact(True, "tests_root"), "qa/helpers/roots.py": fact(True, "roots.test"),
                 "qa/spec_data/x.py": fact(True, "test_locations"), "qa/notes.md": fact(True, "test_locations")}):
        check_eq("test_code: a helper under tests_root is not test code (F-3)", TF.is_test_for("test_code", "qa/helpers/latest.py"), False)
        check_eq("test_code: nor one under roots.test", TF.is_test_for("test_code", "qa/helpers/roots.py"), False)
        check_eq("test_code: the person's test_locations word is", TF.is_test_for("test_code", "qa/spec_data/x.py"), True)
        check_eq("test_code: a usual name is, on any carrier", TF.is_test_for("test_code", "qa/helpers/test_latest.py"), True)
        check_eq("test_code: a file that is no code is not, whatever the word", TF.is_test_for("test_code", "qa/notes.md"), False)
        check_eq("test_code: no verdict, no name: no", TF.is_test_for("test_code", "src/a.py"), False)
    # --- production: the verdict; a carrier that names a folder only with the file's own name ---
    with said(**{"src/contest_service.py": fact(True, "run.levels"), "tests/test_a.py": fact(True, "run.levels"),
                 "src/helpers.py": fact(True, "roots.test"), "src/lib/test_b.py": fact(True, "roots.test"),
                 "src/c.py": fact(True, "tests_root"), "src/d.py": fact(True, "test_locations"),
                 "src/e.py": fact(True, "markers", "file")}):
        check_eq("production: a file matched ONLY by run.levels stays production (E-A7; the mutation of a handoff that "
                 "accepts run.levels is killed here)", TF.is_test_for("production", "src/contest_service.py"), False)
        check_eq("production: run.levels AND a usual name is a test (K-A4b)", TF.is_test_for("production", "tests/test_a.py"), True)
        check_eq("production: roots.test names a folder that may hold helpers: only with its own name",
                 [TF.is_test_for("production", p) for p in ("src/helpers.py", "src/lib/test_b.py")], [False, True])
        check_eq("production: so does tests_root (the safe direction: an extra row, never a lost one)",
                 TF.is_test_for("production", "src/c.py"), False)
        check_eq("production: the project's test_locations word excludes alone; a markers verdict whose own name and "
                 "folder say nothing (the stub) does not", [TF.is_test_for("production", p) for p in ("src/d.py", "src/e.py")],
                 [True, False])
        check_eq("production: no verdict is production", TF.is_test_for("production", "src/f.py"), False)
    # --- F2 (critic t-557): a recognizer NEW in B-407 A excludes only when a new name and a new folder agree ---
    check_eq("F2: camel endings alone and a new folder alone are production ROWS (they were rows before)",
             [TF.is_test_for("production", p) for p in ("src/main/java/UserSpecs.java", "src/ABTest.java", "src/SpeedTest.ts",
                                                        "api/spec/openapi.py", "src/Foo.Tests/Bar.cs", "e2e/login.py")],
             [False] * 6)
    check_eq("G1-1 (retires 'classic names exclude alone', L-2 F-1): a classic FOLDER is a test place by itself: tests/, test/, "
             "__tests__/, test-harness/",
             [TF.is_test_for("production", p) for p in ("tests/x/test_a.py", "__tests__/a.test.tsx", "src/__tests__/b.ts",
                                                        "test-harness/x.py", "test/y.py", "a/tests/b.py")], [True] * 6)
    check_eq("G1-1: a test-looking NAME alone is application code: test_*, *_test.*, .test. / .spec. outside a test place "
             "(the package's own scripts/test_files.py among them) stay production rows",
             [TF.is_test_for("production", p) for p in ("src/test_a.py", "src/a_test.go", "src/a.test.ts", "src/a.spec.ts",
                                                        "test_x.py", "scripts/test_files.py", "src/app/test_mode.py")], [False] * 7)
    check_eq("F2: an agreeing pair excludes: a new name in a new folder, in any case",
             [TF.is_test_for("production", p) for p in ("tests/UserSpecs.java", "spec/foo.spec.ts", "spec/UserSpecs.java",
                                                        "backend/Tests/XTests.cs", "Tests/FooTest.java", "spec/user_spec.rb")],
             [True] * 6)
    check_eq("F2: a classic folder with a new name is excluded by the classic folder alone; `Tests/` is NOT classic (case)",
             [TF.is_test_for("production", p) for p in ("tests/UserSpecs.java", "Tests/helper.py")], [True, False])
    # --- test_body / test_place (advice) ---
    with said(**{"pages/a.ts": fact(True, "test_locations", "file"), "pages/dir/b.ts": fact(True, "test_locations", "folder")}):
        check_eq("test_body: a file the project names one by one is a test body whatever its name",
                 TF.is_test_for("test_body", "pages/a.ts"), True)
        check_eq("test_body: a file under a named folder is not (it may be a helper); a usual name is",
                 [TF.is_test_for("test_body", p) for p in ("pages/dir/b.ts", "pages/dir/b.spec.ts")], [False, True])
        check_eq("test_place: any place the project named or the usual names give",
                 [TF.is_test_for("test_place", p) for p in ("pages/dir/b.ts", "pages/a.ts", "src/x.ts")], [True, True, False])
    # --- name: a segment that names a test or is a test folder name ---
    check_eq("name: test_login, tests, FooTests are; contest_url, Latest, API_BASE_URL are not",
             [TF.is_test_for("name", s) for s in ("test_login", "tests", "FooTests", "contest_url", "Latest", "API_BASE_URL")],
             [True, True, True, False, False, False])
    check_eq("the verdict function is put back", TF.verdict is real, True)
    try:
        TF.is_test_for("everything", "x")
        refused = False
    except ValueError:
        refused = True
    check_eq("an unknown consumer is a programming error, not a quiet False", refused, True)

    def boom(*_a, **_k):
        raise RuntimeError("boom")
    TF.verdict = boom
    try:
        check_eq("an exception inside is None (unknown), never a raise", TF.is_test_for("commit", "tests/a.py"), None)
    finally:
        TF.verdict = real


def part_unreadable() -> None:
    """E-A1: the usual names cannot be read - each consumer's table default, one note naming the file."""
    with said(**{"x/word.txt": fact(True), "run/a.py": fact(True, "run.levels"), "src/b.ts": fact(True, "test_locations", "file")}):
        with markers_file(None) as err:
            check_eq("commit: the project's word still answers, a usual name cannot: unknown (the guard checks)",
                     [TF.is_test_for("commit", p) for p in ("x/word.txt", "tests/a.py")], [True, None])
            check_eq("production: a name cannot rescue a run.levels match (stays a row); the word of test_locations holds",
                     [TF.is_test_for("production", p) for p in ("run/a.py", "x/word.txt", "src/f.py")], [None, True, None])
            check_eq("test_code / test_place / name: unknown",
                     [TF.is_test_for("test_code", "a.py"), TF.is_test_for("test_place", "a.py"), TF.is_test_for("name", "test_x")],
                     [None, None, None])
            check_eq("test_body: a file the project named is a body, any other is unknown",
                     [TF.is_test_for("test_body", "src/b.ts"), TF.is_test_for("test_body", "tests/a.py")], [True, None])
            check_eq("names_a_test / in_test_folder / is_code_file: unknown",
                     (TF.names_a_test("test_a.py"), TF.in_test_folder("tests/a.py"), TF.is_code_file("a.py")), (None, None, None))
            lines = [line for line in err.getvalue().splitlines() if line.strip()]
            check_eq("one stderr note for the whole run, and it names the file", len(lines), 1)
            check_in("... naming the markers file", TF.MARKERS_FILE, lines[0] if lines else "")
        with markers_file({"dir_names": "tests"}) as err:
            check_eq("a file of the wrong shape is the same unknown", TF.names_a_test("test_a.py"), None)
            check_in("... with its one note", TF.MARKERS_FILE, err.getvalue())


def part_spellings() -> None:
    """E-A9: a trailing slash is a folder; empty and `.` mean nothing; a backslash is a separator."""
    with markers_file(FULL):
        check_eq("a trailing `/` makes the last segment a folder", TF.in_test_folder("src/tests/"), True)
        check_eq("without it the last segment is a FILE named tests", TF.in_test_folder("src/tests"), False)
        check_eq("a folder has no file name", TF.names_a_test("src/test_x/"), False)
        check_eq("empty, `.` and `/` name nothing",
                 [(TF.names_a_test(p), TF.in_test_folder(p), TF.is_code_file(p)) for p in ("", ".", "/", None)],
                 [(False, False, False)] * 4)
        check_eq("a leading ./ is nothing; backslashes separate", (TF.in_test_folder("./tests/x.py"),
                 TF.in_test_folder("src\\tests\\x.py"), TF.names_a_test("src\\FooTests.cs"), TF.names_a_test("src\\x.py")),
                 (True, True, True, False))
        check_eq("a folder suffix needs a character before it (`.tests` alone is no folder)",
                 [TF.in_test_folder(p) for p in ("a.tests/x", ".tests/x", "foo/Bar.Tests/x.cs")], [True, False, True])
        check_eq("case: folder names are lower-cased, camel endings are not",
                 [TF.in_test_folder("src/TESTS/x"), TF.names_a_test("a/FOOTESTS.cs"), TF.names_a_test("a/FooTests.cs")],
                 [True, False, True])
        check_eq("an extension: lower-cased, a name without one is no code",
                 [TF.is_code_file(p) for p in ("a/B.CS", "a/Makefile", "a/notes.md", "a/x.test.ts", "src/")],
                 [True, False, False, True, False])


def part_extras() -> None:
    """E-A13 and the world before the lists existed: absent or malformed extras are unknown or narrower, never a
    crash and never a changed grant."""
    with markers_file(FOUR) as err:
        check_eq("extras absent: a camel name is not recognised, the four lists still are",
                 (TF.names_a_test("FooTests.cs"), TF.names_a_test("test_a.py"), TF.in_test_folder("tests/x")), (False, True, True))
        check_eq("extras absent: `is_code_file` is an UNKNOWN (an empty list is not 'no file is code')",
                 TF.is_code_file("a.py"), None)
        check_eq("extras absent: test_code is unknown", TF.is_test_for("test_code", "tests/test_a.py"), None)
        check_eq("extras absent: commit / production / name are unaffected",
                 (TF.is_test_for("commit", "tests/a.py"), TF.is_test_for("name", "test_x")), (True, True))
        check_in("extras absent: one note names the file and the lists", "stem_camel_suffixes", err.getvalue())
    with markers_file(dict(FOUR, stem_camel_suffixes="Tests", code_extensions=[1])) as err:
        check_eq("extras malformed: the same", (TF.names_a_test("FooTests.cs"), TF.is_code_file("a.py"),
                                                 TF.names_a_test("test_a.py")), (False, None, True))
        check_in("extras malformed: named once", "code_extensions", err.getvalue())
    with markers_file(FULL) as err:
        check_eq("full table: camel and code files answer", (TF.names_a_test("FooTests.cs"), TF.is_code_file("a.cs"),
                                                             TF.is_test_for("test_code", "lib/FooTests.cs")), (True, True, True))
        check_eq("... and no note at all", err.getvalue(), "")


def part_classic() -> None:
    """E-6 (FR-13): the classic lists are the `classic` sub-table of the markers file; the CLASSIC_* constants are only the
    floor, used together when that sub-table cannot be read. The shipped file says what the constants say."""
    probe = ("a/tests/b.py", "tests/x/test_a.py", "src/a_test.go", "src/a.spec.ts", "test-harness/x.py", "a/__tests__/b.ts")
    classic = {"prefixes": ["test_"], "suffixes": ["_test", ".test", ".spec"], "folders": ["test", "tests", "__tests__", "test-harness"]}
    check_eq("the shipped `classic` table is the floor, key by key",
             {k: tuple(v) for k, v in hooklib.load_ref_json(TF.MARKERS_FILE)["classic"].items()},
             {"prefixes": TF.CLASSIC_PREFIXES, "suffixes": TF.CLASSIC_SUFFIXES, "folders": TF.CLASSIC_FOLDERS})
    wide = dict(FULL, dir_names=["tests", "test", "__tests__", "test-harness"], stem_suffixes=["_test", ".test", ".spec"])
    folder_only = [True, True, False, False, True, True]       # the classic FOLDERS exclude; a classic NAME alone does not (G1-1)
    with markers_file(dict(wide, classic=classic)):
        check_eq("the data as the floor: a classic folder excludes alone, a classic name alone does not",
                 [TF.is_test_for("production", p) for p in probe], folder_only)
    with markers_file(dict(wide, classic=dict(classic, folders=["test", "__tests__", "test-harness"]))):
        check_eq("MUTATION: `tests` dropped from the data: `a/tests/b.py` (no usual name, only the folder) is a row; "
                 "`tests/x/test_a.py` is still excluded by the agreeing pair (a name AND a folder)",
                 [TF.is_test_for("production", p) for p in probe], [False, True, False, False, True, True])
    with markers_file(dict(wide, classic=dict(classic, suffixes=[], prefixes=[], folders=[]))):
        check_eq("an empty list is readable: it narrows (the safe direction, an extra row) and never falls back to the floor; "
                 "only the agree rule (a usual name AND a usual folder: `tests/x/test_a.py`) still excludes",
                 [TF.is_test_for("production", p) for p in probe], [False, True, False, False, False, False])
    for label, broken in (("absent", None), ("not an object", ["tests"]), ("a key missing", {"folders": ["tests"]}),
                          ("a key that is not a list of strings", dict(classic, suffixes="_test"))):
        table = dict(wide) if broken is None else dict(wide, classic=broken)
        with markers_file(table):
            check_eq(f"classic {label}: all three floors together, so the classic folders hold",
                     [TF.is_test_for("production", p) for p in probe], folder_only)


def part_superset() -> None:
    """K-A2: every sample the replaced recognizers accepted stays a test for the consumer that used it, except the
    names pinned below, which were matches inside a longer word or a whole command text."""
    old_stage_guard = ("tests/a.py", "test/a.py", "spec/a.js", "e2e/a.ts", "x/tests/y/z.py", "test_a.py", "x/test_a-b.js",
                       "test_c.ts", "a_test.py", "a_test.go", "a_test.js", "a_test.ts", "a.spec.js", "a.spec.ts", "a.spec.tsx",
                       "test-harness/x.py", "src\\tests\\a.py", "tests\\test_a.py")
    check_eq("K-A2: every sample of the stage guard's old regex is still a commit-shape test",
             [p for p in old_stage_guard if TF.is_test_for("commit", p) is not True], [])
    old_handoff = ("tests/x.py", "test/x.py", "test-harness/x.py", "a/tests/b.py")
    check_eq("K-A2: every sample of the handoff's old filter UNDER a test folder is still not a production row",
             [p for p in old_handoff if TF.is_test_for("production", p) is not True], [])
    check_eq("K-A2 (L-2 F-1, G1-1): `test_x.py` and `src/test_y.py` WERE dropped by their name alone; that pinned a rule with a "
             "loss (scripts/test_files.py and src/app/test_mode.py are application code): they are production rows now",
             [TF.is_test_for("production", p) for p in ("test_x.py", "src/test_y.py")], [False, False])
    check_eq("K-A2: `backend/Tests/XTests.cs` was production before (a fixture of test_red_sandbox_reports) and is not now",
             (TF.is_test_for("production", "backend/Tests/XTests.cs"), TF.is_test_for("commit", "backend/Tests/XTests.cs")),
             (True, True))
    old_judge = ("test_login", "tests.api.client", "tests.ui.workflows")
    check_eq("K-A2: the quoted names judge_run skipped are still skipped",
             [n for n in old_judge if not any(TF.is_test_for("name", s) for s in n.split("."))], [])
    # the E-A4 names: a substring match before, a name or a folder now - pinned, each with its reason
    narrowed = {"contest_x.py": "`test_` inside `contest_x` was no prefix", "latest_report.py": "`test_` ... was no prefix",
                "my_test_foo.py": "`test_foo.py` found inside a longer name", "pytest_plugin.py": "ditto, `test_` after `py`",
                "protest_utils.py": "ditto", "foo_test.py.bak": "the name's stem is `foo_test.py`, not `foo_test`"}
    check_eq("E-A4 (F-3): the narrowed names are no test for the commit shape (and so are production rows)",
             {n: (TF.is_test_for("commit", n), TF.is_test_for("production", f"src/{n}")) for n in narrowed},
             {n: (False, False) for n in narrowed})
    # the real verdict, in a project with the project's own word
    root = temp_dir("qa-tf-real-").resolve()
    try:
        (root / "qa-factory").mkdir()
        (root / "src" / "legacy").mkdir(parents=True)
        cfg = {"app_root": ".", "protected_app_paths": ["src"], "test_locations": ["src/legacy/"],
               "run": {"levels": {"unit": ["src/legacy/**"]}}}
        (root / "qa-factory" / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
        got = [TF.is_test_for("commit", "src/legacy/a.py", cfg, root=root),
               TF.is_test_for("commit", "src/app/FooTests.cs", cfg, root=root),
               TF.is_test_for("commit", "lib/FooTests.cs", cfg, root=root),
               TF.is_test_for("production", "src/legacy/a.py", cfg, base=root, root=root)]
        check_eq("with the real verdict: the project's word is a commit test; a camel name in application code the project "
                 "has spoken for fails step 3 but the commit consumer asks the names directly; a test_locations entry "
                 "is a production-row exclusion even when run.levels names the place too", got, [True, True, True, True])
        check_eq("... and the verdict alone (step 3) says the camel name is no test there",
                 TF.verdict("src/app/FooTests.cs", cfg, root=root)["test"], False)
    finally:
        cleanup(root)


def part_kinds() -> None:
    """G1-1: `file_kind` is the one rule of "is this a production file", and `production_files` its filter. Every row of the
    spec's table (§4.1 as L-2 F-1 re-cut it), the intersections of kinds, None -> production, the project's word, and the
    control on the package's own scripts."""
    table = {
        "production": ["src/app/filter.py", "src/ABTest.java", "api/spec/openapi.py", "Tests/Helper.cs", "assets/logo.png",
                       "src/my module.py", "src/app/test_mode.py", "scripts/test_files.py", "Docs/guide.py", "docs/conf.py",
                       "docs/site/app.py", "src/a.test.ts", "src/foo_test.go", "src/test_a.py",
                       # F2 (t-1050): code under `docs/` whose extension no code list names is still production
                       "docs/db/schema.sql", "docs/build.sh", "docs/site/App.vue", "docs/native/main.c", "docs/Dockerfile",
                       "docs/site/index.html", "Docs/index.html", "docs/site/app.js", "docs/data.csv", "docs/noext"],
        "config": ["config/settings.yaml", "pyproject.toml", "requirements.txt", "package-lock.json", "a/b.jsonl", "x.ini",
                   "docs/x.yaml", "docs/data.json"],
        "generated": ["Cargo.lock", "web/yarn.lock", "docs/Cargo.lock"],
        # `docs` is the positive list DOC_FOLDER_EXTENSIONS under a docs folder, and `.md` anywhere: nothing else
        "docs": ["README.md", "docs/x.md", "docs/x.png", "docs/guide.txt", "docs/a.rst", "docs/a.adoc", "docs/a.pdf",
                 "docs/a.svg", "docs/a.jpg", "docs/a.jpeg", "docs/a.gif", "Docs/Logo.PNG", "a/docs/b/c.txt"],
        "test": ["tests/test_a.py", "a/tests/b.py", "test/FooTest.java", "src/__tests__/a.test.ts", "backend/Tests/XTests.cs",
                 "test-harness/conftest.py", "spec/UserSpecs.java"],
    }
    for kind, paths in table.items():
        check_eq(f"file_kind: {kind}", [TF.file_kind(p) for p in paths], [kind] * len(paths))
    check_eq("file_kind: the intersections are decided by the priority test > docs > generated > config (a test folder wins over "
             "a document, a docs folder over the `.txt` config extension; a lock file or a yaml under docs/ is not a document)",
             [TF.file_kind(p) for p in ("tests/README.md", "tests/data.json", "docs/x.txt", "docs/Cargo.lock", "docs/x.yaml")],
             ["test", "test", "docs", "generated", "config"])
    check_eq("file_kind: nothing is not a test, the backslash form reads like the slash form",
             [TF.file_kind(p) for p in (None, "", "src\\app\\filter.py", "tests\\a.py", "docs\\conf.py")],
             ["production", "production", "production", "test", "production"])
    with markers_file(None) as err:
        check_eq("file_kind: markers that cannot be read -> production for everything but a document by extension (an extra row)",
                 [TF.file_kind(p) for p in ("tests/a.py", "docs/x.png", "docs/conf.py", "docs/db/schema.sql", "README.md", "pyproject.toml")],
                 ["production", "docs", "production", "production", "docs", "config"])
        check_in("... with the one stderr note", TF.MARKERS_FILE, err.getvalue())
    with markers_file(dict(FULL, code_extensions=[])):
        check_eq("file_kind: a code list that cannot be read changes nothing: `docs` is the document list, not 'not code'",
                 [TF.file_kind(p) for p in ("docs/conf.py", "docs/db/schema.sql", "docs/x.png")], ["production", "production", "docs"])
    got = TF.production_files(["src/a.py", "tests/t.py", "src/a.py", "pyproject.toml", "docs/x.md", "src/b.py", "Cargo.lock"], {"production"})
    check_eq("production_files: the order of the input, each path once, only the kinds asked for", got, ["src/a.py", "src/b.py"])
    check_eq("... and {production, config} is the S2 handoff's set",
             TF.production_files(["pyproject.toml", "docs/x.md", "src/a.py"], {"production", "config"}), ["pyproject.toml", "src/a.py"])
    check_eq("production_files: no paths, no rows", TF.production_files([], {"production"}), [])
    # the project's word, with the checkout it is relative to
    root = temp_dir("qa-tf-kind-").resolve()
    try:
        (root / "qa-factory").mkdir()
        (root / "src" / "legacy").mkdir(parents=True)
        cfg = {"app_root": ".", "protected_app_paths": ["src"], "test_locations": ["src/legacy/"]}
        (root / "qa-factory" / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
        check_eq("file_kind: the project's test_locations word makes a file a test with the checkout; without the config it is production",
                 (TF.file_kind("src/legacy/a.py", cfg, base=root, root=root), TF.file_kind("src/legacy/a.py")), ("test", "production"))
    finally:
        cleanup(root)
    # control on the package itself: no module of scripts/ is a test (before G1-1 six were dropped by their names)
    modules = sorted(p.name for p in SCRIPTS.glob("*.py"))
    named = [m for m in modules if TF.names_a_test(m)]
    check_eq(f"CONTROL: 0 of {len(modules)} scripts/*.py is a test (and {len(named)} of them carry a test-looking name, the "
             "class the old rule lost)", [m for m in modules if TF.file_kind(f"scripts/{m}") == "test"], [])
    check("CONTROL: the control sees the class (at least one script carries a test-looking name)", len(named) >= 1)


def main() -> None:
    part_kinds()
    part_consumers()
    part_unreadable()
    part_spellings()
    part_extras()
    part_classic()
    part_superset()
    finish("test_test_files")


if __name__ == "__main__":
    main()
