#!/usr/bin/env python3
"""A person may open TEST files inside the application tree for the automator (legacy-2406
migration, wave 4, node W4-G, M15; the wave 4 spec is the branch author's word, D-0025; since D-0030,
06.10.2026, a name that is not a usual test name is advised, not refused).

P-00 (the factory never modifies application code) stays absolute for everything but one thing:
the person's recorded word `protected test path: <folder/ or pattern>` lets the automator of THAT
story write test files matching the pattern. This file tests the five places that rule lives:

  (a) the grammar and the boundary refusals (`test_path_grants.pattern_errors`), against the five
      admitted examples, the refused ones, and every marker list once - the markers only advise
      (`pattern_notes`): a pattern with no usual test name is admitted and noted;
  (b) the same function at READ time: a grant that no longer passes is ignored (fail closed);
  (c) `waiver.py` through the real CLI: the boundary refusals verbatim, the grant line with the door to
      `test_locations`, the advisory note, revocation, and the refusal of a stand-gap record that names
      no gap;
  (d) the guard (`guard_app_under_test.check`): who and what is opened, and the invariants - Bash
      and PowerShell, the critic, the orchestrator, another story, deletes, moves and a write that
      empties a file are never opened;
  (e) the legacy port (the Codex run's test, adapted to the key `protected test path: src/tests/`)
      through the real hook process, the first-word re-record door of the apply grant, and the guard's
      reading of a stand-gap answer through `contract.stand_gap_decisions` (the decision's FIRST word).
"""
import io
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
from contextlib import redirect_stderr
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import (SCRIPTS, check, check_eq, check_in, check_not_in, cleanup, finish,  # noqa: E402
                     run_script, temp_dir, use_project)

sys.path.insert(0, str(SCRIPTS))

try:
    import test_path_grants as TPG  # noqa: E402
except ImportError as exc:  # red first: the module does not exist yet
    TPG = None
    print(f"FAIL test_path_grants cannot be imported - {exc}")

TICKET = "QA-1"
WORDS = "Yes: the automator may put its tests in the test folders of the app."
AT = "2026-10-03T10:00:00+00:00"
BLOCK = "protected test path: "
FILE = "test-path-markers.json"


# --- a project with an application tree ----------------------------------------------------------

def grant_entry(pattern: str, words: str = WORDS, at: str = AT, stage: str = "S5", **extra) -> dict:
    entry = {"stage": stage, "match": BLOCK + pattern, "decision": words, "at": at, "by": "human"}
    entry.update(extra)
    return entry


def project(prefix: str, protected=("src",), stories=None, config_extra=None) -> Path:
    """`src/tests`, `src/app` and `tests/` in a temp project; one story QA-1 holding `overrides`."""
    root = temp_dir(prefix)
    for folder in ("src/tests", "src/app", "tests"):
        (root / folder).mkdir(parents=True)
    (root / "src" / "app" / "x.py").write_text("x = 1\n", encoding="utf-8")
    (root / "src" / "tests" / "test_old.py").write_text("def test_a():\n    assert 1\n", encoding="utf-8")
    cfg = {"schema_version": 1, "tests_root": "tests", "app_root": ".",
           "protected_app_paths": list(protected)}
    cfg.update(config_extra or {})
    (root / "qa-factory").mkdir()
    (root / "qa-factory" / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
    for ticket, overrides in (stories if stories is not None else {TICKET: []}).items():
        task = root / "qa-factory" / "artifacts" / ticket
        (task / "state" / "words").mkdir(parents=True)
        (task / "pipeline.json").write_text(json.dumps(
            {"ticket": ticket, "stages": {"S5": {"status": "running"}}, "stage_overrides": overrides}),
            encoding="utf-8")
    return root


def pipeline_of(root: Path, ticket: str = TICKET) -> dict:
    return json.loads((root / "qa-factory" / "artifacts" / ticket / "pipeline.json").read_text(encoding="utf-8"))


def words_file(root: Path, text: str = WORDS, ticket: str = TICKET) -> str:
    path = root / "qa-factory" / "artifacts" / ticket / "state" / "words" / "w.txt"
    path.write_bytes(text.encode("utf-8"))
    return str(path)


def waiver(root: Path, *args, ticket: str = TICKET):
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(root), PYTHONDONTWRITEBYTECODE="1")
    return run_script("waiver.py", "--task", ticket, *args, cwd=root, env=env)


def config_of(root: Path) -> dict:
    return json.loads((root / "qa-factory" / "config.json").read_text(encoding="utf-8"))


# --- (a) the grammar and the test-specific rule --------------------------------------------------

def errors(pattern, root: Path, protected=("src",)) -> list:
    cfg = {"protected_app_paths": list(protected)}
    return TPG.pattern_errors(pattern, cfg, root) if TPG else ["test_path_grants is missing"]


# The five examples of the wave 4 spec (the branch author's word, D-0025); the last two are written under
# the protected root.
ADMITTED = ("src/tests/**", "src/**/*.spec.ts", "src/**/*.test.ts", "src/**/test_*.py", "src/**/*_test.py")


def notes(pattern, root: Path, protected=("src",)) -> list:
    cfg = {"protected_app_paths": list(protected)}
    return TPG.pattern_notes(pattern, cfg, root) if TPG else ["test_path_grants is missing"]


def part_admitted(root: Path) -> None:
    for pattern in ADMITTED:
        check_eq(f"example admitted: {pattern}", errors(pattern, root), [])
        check_eq(f"and carries a usual test name, so nothing to advise: {pattern}", notes(pattern, root), [])
    check_eq("`src/tests/` (the example of the first refusal) is admitted", errors("src/tests/", root), [])
    check_eq("and so is a backslash spelling, in any case (lower-cased like hooklib.norm)",
             errors("SRC\\Tests\\", root), [])
    check_eq("a test folder below another folder is admitted", errors("src/app/tests/", root), [])
    check_eq("and a wildcard folder in front of a test folder", errors("src/*/tests/**", root), [])
    check_eq("a dot segment and a doubled slash are dropped, not refused", errors("src/./tests//", root), [])
    # each marker list is hit once (the lists are in references/test-path-markers.json, D-0030: advice)
    for name in ("test", "tests", "__tests__", "spec", "specs", "e2e"):
        check_eq(f"dir_names `{name}`: a folder of that name is a test folder",
                 (errors(f"src/{name}/", root), notes(f"src/{name}/", root)), ([], []))
    for suffix in (".tests", ".test"):
        check_eq(f"dir_suffixes `{suffix}`: `myapp{suffix}/` is a test project folder",
                 (errors(f"src/myapp{suffix}/", root), notes(f"src/myapp{suffix}/", root)), ([], []))
    check_eq("stem_prefixes `test_`: `test_*.py`",
             (errors("src/**/test_*.py", root), notes("src/**/test_*.py", root)), ([], []))
    for suffix, pattern in ((".spec", "src/**/*.spec.ts"), (".test", "src/**/*.test.ts"),
                            ("_test", "src/**/*_test.py"), ("_spec", "src/**/*_spec.rb")):
        check_eq(f"stem_suffixes `{suffix}`: `{pattern}`", (errors(pattern, root), notes(pattern, root)), ([], []))
    check_eq("the extension may be a wildcard too: `*.spec.*`",
             (errors("src/**/*.spec.*", root), notes("src/**/*.spec.*", root)), ([], []))


def part_refused(root: Path) -> None:
    # D-0030: a pattern with no usual test name is ADMITTED (the markers are a suggestion): it is noted, once,
    # and nothing is refused. Each of these used to be a refusal.
    for pattern in ("src/**/*.ts", "src/*.ts", "src/app/*.ts", "src/app/", "src/app/foo.ts",
                    "src/**/*test.py", "src/tests", "src/**/spec*.ts", "src/**/t?st_*.py"):
        found = errors(pattern, root)
        check_eq(f"no usual test name, admitted: {pattern}", found, [])
        check_eq(f"and advised, not refused: {pattern}", notes(pattern, root), [note_1(pattern)])
    for pattern in ("src/**/*", "src", "src/", "src/**", "src/*", "src/*.*", "src/**/**", "src/*?*", "src/**/*.*"):
        found = errors(pattern, root)
        check(f"the whole of the root, refused: {pattern}",
              len(found) == 1 and "would open the whole of 'src'" in found[0], str(found))
        check_eq(f"a refused pattern has nothing to advise: {pattern}", notes(pattern, root), [])
    for pattern in ("src/.tests/", "src/te*s/**", "src/tests.py/"):
        check_eq(f"a marker that does not count (no character before the suffix, a wildcard in it, the stem "
                 f"of a folder) is noted, not refused: {pattern}",
                 (errors(pattern, root), notes(pattern, root)), ([], [note_1(pattern)]))
    check("a pattern outside the root: `lib/tests/`",
          "lies inside no protected_app_paths entry (src)" in " ".join(errors("lib/tests/", root)))
    # F5: a pattern whose FIRST FOLDER holds a wildcard cannot start with the protected folder it
    # opens; it used to be told it "lies inside no protected_app_paths entry ... needs no permission",
    # which is false (a leading wildcard reaches into the root) and leaves the person nowhere to go.
    # R3 (t-076): and a SINGLE segment has no first folder - `test_*.py` starts with a literal, so
    # "starts with a wildcard" was untrue of it; it names files directly in app_root.
    for pattern in ("**/tests/**", "**/*.spec.ts", "*/tests/", "?rc/tests/", "t*st/x_test.py"):
        found = errors(pattern, root)
        check_eq(f"a wildcard in the first folder gets its own refusal: {pattern}", found,
                 [refusal_5(pattern, root, "src")])
        check_not_in(f"and is not told it needs no permission: {pattern}", "needs no permission", " ".join(found))
    for pattern in ("test_*.py", "*_test.py", "foo_test.py", "*.spec.ts"):
        found = errors(pattern, root)
        check_eq(f"a single segment is told it names files in app_root: {pattern}", found,
                 [refusal_5b(pattern, root, "src")])
        check_not_in(f"and is not told it starts with a wildcard: {pattern}", "wildcard", " ".join(found))
        check_not_in(f"nor that it needs no permission: {pattern}", "needs no permission", " ".join(found))
    check_in("the boundary reading still comes first: `**/` opens the boundary, it is not a wildcard-first case",
             "would open the folder that holds 'src'", " ".join(errors("**/", root)))
    check_eq("with a nested root the example names the first protected_app_paths entry",
             errors("**/*.spec.ts", root, ("app/src", "lib")), [refusal_5("**/*.spec.ts", root, "app/src")])
    check_eq("and so does the single-segment text", errors("test_*.py", root, ("app/src", "lib")),
             [refusal_5b("test_*.py", root, "app/src")])
    check_eq("no protected root under app_root: nothing to name, the old refusal stands",
             len(errors("**/*.spec.ts", root, ())) == 1 and "lies inside no protected_app_paths entry (none)"
             in " ".join(errors("**/*.spec.ts", root, ())), True)
    check_eq("EXCEPTION: when app_root itself is a protected root, such patterns are judged as before (admitted)",
             [errors(p, root, (".",)) for p in ("**/*.spec.ts", "**/tests/**", "test_*.py", "*_test.py",
                                                "*/tests/", "t*st/x_test.py")], [[]] * 6)
    check_eq("and the one that names the protected folder is admitted with the folder in front",
             errors("src/**/test_*.py", root), [])
    check_eq("and an ordinary application pattern carries no usual test name there: advised, admitted",
             (errors("**/*.ts", root, (".",)), notes("**/*.ts", root, (".",))), ([], [note_1("**/*.ts")]))


def part_grammar(root: Path) -> None:
    def reason(pattern):
        found = errors(pattern, root)
        return found[0] if found else ""
    check_in("empty is refused (grammar text)", "'' is empty. Write it the way protected_app_paths are written",
             reason(""))
    check_in("whitespace-only is empty too", "is empty", reason("  \t "))
    check_in("a slash alone is an absolute path", "is an absolute path", reason("/"))
    check_in("absolute (posix)", "'/etc/tests/' is an absolute path", reason("/etc/tests/"))
    check_in("absolute (drive)", "is an absolute path", reason("C:/proj/src/tests/"))
    check_in("absolute (drive, backslash)", "is an absolute path", reason("C:\\proj\\src\\tests\\"))
    check_in("absolute (UNC)", "is an absolute path", reason("\\\\server\\share\\src\\tests\\"))
    check_in("a `..` segment", "outside it ('..')", reason("src/../tests/"))
    check_in("a leading `..`", "outside it ('..')", reason("../src/tests/"))
    for char in "[]{}!":
        check_in(f"`{char}` is not in this pattern language",
                 f"using '{char}', which this pattern language does not have (only *, ** and ?)",
                 reason(f"src/tests{char}x/"))
    check_in("the grammar text names app_root", f"relative to app_root ({root})", reason(""))
    check_in("and the example", 'for example "src/tests/", and record again.', reason("src/../x"))


def part_roots(root: Path) -> None:
    # a root that is NOT the whole app, a parent of one, and a pattern inside / at / above it
    nested = ("app/src",)

    def found(pattern):
        return " ".join(errors(pattern, root, nested))
    check_eq("inside a nested root, a test folder is admitted", errors("app/src/tests/", root, nested), [])
    for pattern in ("app/src", "app/src/", "app/src/**", "app/src/*", "app/src/**/*", "**", "**/"):
        check_in(f"the whole of the root, refused: {pattern}", "would open the whole of 'app/src'", found(pattern))
    for pattern in ("app", "app/", "app/**", "app/*", "*", "app/*.*"):
        check_in(f"the folder that holds the root, refused: {pattern}",
                 "would open the folder that holds 'app/src'", found(pattern))
    check_in("the refusal names the boundary and the way on",
             'that is the boundary itself, not a place for tests. Name the folder or file pattern the tests '
             'live in, inside it (for example "src/tests/" or "src/**/*.spec.ts"), and record again with the '
             "person's words.", found("app/"))
    check_in("a pattern next to the root lies inside no protected path", "lies inside no protected_app_paths "
             "entry (app/src)", found("app/other/tests/"))
    # a marker segment that IS the protected root, or above it, does not count
    inverse = ("tests/src",)
    check("a marker that is above the root does not count: `tests/src/**` with root `tests/src`",
          errors("tests/src/**", root, inverse) != [])
    check_eq("a marker above the root does not count either: `tests/src/app/` with root `tests/src` is noted",
             (errors("tests/src/app/", root, inverse), notes("tests/src/app/", root, inverse)),
             ([], [note_1("tests/src/app/")]))
    check_eq("below that root a marker counts: `tests/src/tests/`",
             (errors("tests/src/tests/", root, inverse), notes("tests/src/tests/", root, inverse)), ([], []))
    check("a root that IS a test folder cannot be opened whole: `src/tests/**` with root `src/tests`",
          "would open the whole of 'src/tests'" in " ".join(errors("src/tests/**", root, ("src/tests",))))
    check_eq("two roots: the innermost one decides what is below it (the `tests` above it does not count)",
             (errors("src/tests/x/", root, ("src", "src/tests")), notes("src/tests/x/", root, ("src", "src/tests"))),
             ([], [note_1("src/tests/x/")]))
    check("no protected_app_paths at all: nothing to open, refused with `none`",
          "lies inside no protected_app_paths entry (none)" in " ".join(errors("src/tests/", root, ())))
    check_eq("a protected root of `.` (the app itself): a test folder is admitted", errors("tests/", root, (".",)), [])
    check_in("and the whole of it is refused", "would open the whole of '.'", " ".join(errors("**", root, ("."))))


def part_data_file(root: Path) -> None:
    import hooklib
    real_ref = hooklib.ref
    empty = Path(tempfile.mkdtemp(prefix="qa-markers-missing-"))
    try:
        hooklib.ref = lambda rel: empty / rel
        # D-0030: a broken list is the factory's own defect and blocks nothing - the pattern is admitted and
        # the person is told the name was not checked (a broken data file never refuses a person's word)
        for pattern in ("src/tests/", "src/**/*.spec.ts", "src/**/test_*.py"):
            check_eq(f"the data file is missing: `{pattern}` is admitted, and the note names the file",
                     (errors(pattern, root), notes(pattern, root)), ([], [note_2(pattern, "missing, unreadable or empty")]))
        check_in("the note names the file", FILE, notes("src/tests/", root)[0])
        check_eq("a pattern with another problem is refused for that problem alone, and the file is not named",
                 [FILE in e for e in errors("src/**/*", root)], [False])
        (empty / FILE).write_text("{not json", encoding="utf-8")
        check_eq("an unreadable file is the same note, no refusal",
                 (errors("src/tests/", root), len(notes("src/tests/", root))), ([], 1))
        (empty / FILE).write_text(json.dumps({"dir_names": "tests", "dir_suffixes": [], "stem_prefixes": [],
                                               "stem_suffixes": []}), encoding="utf-8")
        check_eq("a list that is not a list of strings: noted, the file named, nothing refused",
                 (errors("src/tests/", root), FILE in " ".join(notes("src/tests/", root))), ([], True))
        (empty / FILE).write_text(json.dumps({"dir_names": ["tests"]}), encoding="utf-8")
        check_eq("a file with a list missing: noted, nothing refused",
                 (errors("src/tests/", root), FILE in " ".join(notes("src/tests/", root))), ([], True))
        (empty / FILE).write_text(json.dumps({"dir_names": ["tests", ""], "dir_suffixes": [],
                                               "stem_prefixes": [], "stem_suffixes": []}), encoding="utf-8")
        check_eq("an empty marker would match everything: the file is unusable, noted",
                 (errors("src/tests/", root), FILE in " ".join(notes("src/tests/", root))), ([], True))
        (empty / FILE).write_text(json.dumps({"dir_names": ["Tests"], "dir_suffixes": [],
                                               "stem_prefixes": [], "stem_suffixes": [], "later_list": ["x"]}),
                                  encoding="utf-8")
        check_eq("a shape that is right: markers are lower-cased, only those markers count, a key it does "
                 "not know is ignored",
                 (errors("src/tests/", root), notes("src/tests/", root), bool(notes("src/**/test_*.py", root))),
                 ([], [], True))
        four = {"dir_names": ["tests"], "dir_suffixes": [], "stem_prefixes": ["test_"], "stem_suffixes": []}
        for label, extra in (("absent (the file before B-407 A)", {}),
                             ("malformed", {"stem_camel_suffixes": "Tests", "code_extensions": [3, ""]})):
            (empty / FILE).write_text(json.dumps(dict(four, **extra)), encoding="utf-8")
            check_eq(f"K-A6: the extras {label} change no grant: a usual name is admitted with no note, a name that is "
                     "not one gets the same note as before, a refusal is still a refusal",
                     (errors("src/tests/", root), notes("src/tests/", root), notes("src/**/*.ts", root) != [],
                      errors("src/**", root) != []), ([], [], True, True))
        check_eq("the guard-side reader does not raise on any of this",
                 TPG.active_grants({"stage_overrides": [grant_entry("src/tests/")]},
                                   {"protected_app_paths": ["src"]}, root) != [], True)
    finally:
        hooklib.ref = real_ref
        cleanup(empty)
    check_eq("the real data file holds exactly the four lists of usual test names (`test-harness` is the handoff's "
             "historical exclusion, B-407 A3)",
             {k: json.loads((SCRIPTS.parent / "references" / FILE).read_text(encoding="utf-8")).get(k)
              for k in ("dir_names", "dir_suffixes", "stem_prefixes", "stem_suffixes")},
             {"dir_names": ["test", "tests", "__tests__", "spec", "specs", "e2e", "test-harness"],
              "dir_suffixes": [".tests", ".test"], "stem_prefixes": ["test_"],
              "stem_suffixes": [".spec", ".test", "_test", "_spec"]})
    check_eq("and the two B-407 A lists beside them, exactly (the camel list keeps its case)",
             {k: json.loads((SCRIPTS.parent / "references" / FILE).read_text(encoding="utf-8")).get(k)
              for k in ("stem_camel_suffixes", "code_extensions")},
             {"stem_camel_suffixes": ["Test", "Tests", "Spec", "Specs", "IT"],
              "code_extensions": [".py", ".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx", ".java", ".kt", ".kts", ".groovy",
                                  ".scala", ".cs", ".fs", ".vb", ".go", ".rb", ".php", ".swift", ".rs"]})


# --- (b) the same function at read time ----------------------------------------------------------

def part_read_time(root: Path) -> None:
    if not TPG:
        return
    cfg = {"protected_app_paths": ["src"]}
    old = {"stage_overrides": [
        grant_entry("src/**/*.ts"),                       # no usual test name: D-0030, it is the person's word
        grant_entry("src/app/", at="2026-10-01T00:00:00+00:00"),
        grant_entry("src/tests/", revoked_at="2026-10-04T00:00:00+00:00"),
        grant_entry("src/e2e/", words=" "),               # no words: no permission
        {"stage": "S5", "match": "stand gap: PC-1", "decision": "apply", "at": AT},
        "not a dict", {"match": None},
        grant_entry("src/specs/"),
        grant_entry("src/**"),                            # the boundary itself: still dead
    ]}
    check_eq("read time: the grants that still pass are active (a name with no usual marker is one of them); "
             "revoked, wordless, other blocks and the boundary itself are not",
             [g["pattern"] for g in TPG.active_grants(old, cfg, root)], ["src/**/*.ts", "src/app/", "src/specs/"])
    check_eq("read time: a revoked grant is history, not a permission",
             TPG.active_grants({"stage_overrides": [grant_entry("src/tests/", revoked_at=AT)]}, cfg, root), [])
    grant = TPG.grant_for({"stage_overrides": [grant_entry("src/tests/")]},
                          str(root / "src" / "tests" / "deep" / "test_x.py"), cfg, root)
    check_eq("a target inside the pattern finds its grant, with the words and the date",
             (grant.get("pattern"), grant.get("words"), grant.get("at")), ("src/tests/", WORDS, AT))
    check_eq("a target outside the pattern finds none",
             TPG.grant_for({"stage_overrides": [grant_entry("src/tests/")]},
                           str(root / "src" / "app" / "x.py"), cfg, root), {})
    check_eq("a target outside app_root finds none",
             TPG.grant_for({"stage_overrides": [grant_entry("src/tests/")]},
                           str(root.parent / "elsewhere" / "src" / "tests" / "t.py"), cfg, root), {})
    check_eq("the config changed so the pattern IS a root: the grant is dead",
             TPG.active_grants({"stage_overrides": [grant_entry("src/tests/")]},
                               {"protected_app_paths": ["src/tests"]}, root), [])
    check_eq("a grant in a quoted block text is read the same",
             [g["pattern"] for g in TPG.active_grants(
                 {"stage_overrides": [dict(grant_entry("x"), match='Protected  Test Path: "src/tests/"')]},
                 cfg, root)], ["src/tests/"])
    check_eq("no pipeline, no grants", TPG.active_grants(None, cfg, root), [])


# --- (c) waiver.py: the record ---------------------------------------------------------------------

def refusal_1(p: str, what: str) -> str:
    return (f'waiver: "protected test path: {p}" would open {what} - that is the boundary itself, not a place '
            'for tests. Name the folder or file pattern the tests live in, inside it (for example '
            '"src/tests/" or "src/**/*.spec.ts"), and record again with the person\'s words.')


def refusal_2(p: str, why: str, app_root) -> str:
    return (f"waiver: a protected test path is a folder or pattern relative to app_root ({app_root}); "
            f"'{p}' is {why}. Write it the way protected_app_paths are written, for example "
            '"src/tests/", and record again.')


def refusal_3(p: str, listed: str) -> str:
    return (f"waiver: '{p}' lies inside no protected_app_paths entry ({listed}), so writing there needs no "
            "permission. Nothing was recorded.")


def note_1(p: str) -> str:
    """D-0030: the advisory line for a pattern with no usual test name (it is recorded, never refused)."""
    return (f'waiver: note - "protected test path: {p}" does not carry a usual test name '
            f"(references/{FILE} is a suggestion, not a rule); it was recorded as the person said it. "
            "Application code outside the pattern stays closed.")


def note_2(p: str, why: str) -> str:
    """D-0030: the advisory line when the list of usual test names cannot be read."""
    return (f"waiver: note - the list of usual test names (references/{FILE}) is {why}, so the name of "
            f'"protected test path: {p}" was not checked; it was recorded as the person said it.')


DOOR = ("To keep it for every story: the orchestrator shows the person what test_locations.py --check "
        "--candidate '{p}' counts there and, on their word, records it in test_locations through "
        "project_decisions.py (references/conductor.md); this permission is then no longer needed.")


def refusal_5(p: str, app_root, root: str) -> str:
    """A pattern of several segments whose first folder is a wildcard (t-076 R3, text (a))."""
    return (f"waiver: a protected test path is read from app_root ({app_root}), so it has to start with the "
            f"protected folder it opens; the first folder of '{p}' is a wildcard. Write it as, for example, "
            f'"{root}/**/*.spec.ts" or "{root}/tests/", and record again with the person\'s words.')


def refusal_5b(p: str, app_root, root: str) -> str:
    """A single-segment pattern, with app_root itself not protected (t-076 R3, text (b))."""
    return (f"waiver: '{p}' names files directly in app_root ({app_root}), outside the protected folder "
            f"'{root}', so it opens nothing there. Write it with the folder, for example "
            f'"{root}/**/{p}", and record again with the person\'s words.')


def part_record() -> None:
    root = project("qa-tpg-record-")
    try:
        app_root = str(root.resolve())
        before = pipeline_of(root)
        for label, pattern, expected in (
                ("the whole root", "src/", refusal_1("src/", "the whole of 'src'")),
                ("the root itself, no slash", "src", refusal_1("src", "the whole of 'src'")),
                ("a wildcard-only last segment", "src/*.*", refusal_1("src/*.*", "the whole of 'src'")),
                ("empty (the --block carries nothing after the colon)", " ", refusal_2(" ".strip(), "empty", app_root)),
                ("absolute", "/etc/tests/", refusal_2("/etc/tests/", "an absolute path", app_root)),
                ("outside it", "src/../tests/", refusal_2("src/../tests/", "outside it ('..')", app_root)),
                ("a character the language does not have", "src/te[st]/",
                 refusal_2("src/te[st]/", "using '[', which this pattern language does not have "
                           "(only *, ** and ?)", app_root)),
                ("inside no protected root", "lib/tests/", refusal_3("lib/tests/", "src")),
                ("a wildcard first (F5)", "**/*.spec.ts", refusal_5("**/*.spec.ts", app_root, "src")),
                ("a wildcard in the first folder of a nested pattern (R3)", "t*st/x_test.py",
                 refusal_5("t*st/x_test.py", app_root, "src")),
                ("a bare file pattern names files in app_root (R3)", "test_*.py",
                 refusal_5b("test_*.py", app_root, "src"))):
            done = waiver(root, "--stage", "S5", "--block", BLOCK + pattern.strip(), "--words-file", words_file(root))
            check_eq(f"refused ({label}): exit 2", done.returncode, 2)
            check_in(f"refused ({label}): the text, verbatim", expected, done.stderr)
            check_eq(f"refused ({label}): nothing was recorded", pipeline_of(root), before)
        # the blank pattern really is empty: the person's words are there, the block names nothing
        done = waiver(root, "--stage", "S5", "--block", "protected test path:", "--words-file", words_file(root))
        check_in("`--block \"protected test path:\"` is the empty pattern", refusal_2("", "empty", app_root),
                 done.stderr)

        done = waiver(root, "--stage", "S5", "--block", BLOCK + "src/tests/", "--words-file", words_file(root))
        check_eq("an admitted pattern is recorded (exit 0)", done.returncode, 0)
        check_in("and the grant line is printed, verbatim",
                 f"protected test path: test files under 'src/tests/' are open to the automator of {TICKET} "
                 f'from now on: "{WORDS}". Application code outside that pattern stays closed.', done.stdout)
        check_in("and the door to keep it for every story is named, verbatim (D-0030)",
                 " " + DOOR.format(p="src/tests/"), done.stdout)
        check_not_in("a usual test name carries no advisory note", "waiver: note", done.stdout)
        check_not_in("instead of the dispatch recheck", "block lifted", done.stdout)
        check_not_in("and nothing says the block was not lifted", "block NOT lifted", done.stdout)
        entries = pipeline_of(root).get("stage_overrides") or []
        check_eq("the record is the pipeline entry: stage, block, the person's words, no option",
                 [(e["stage"], e["match"], e["decision"], "option" in e) for e in entries],
                 [("S5", BLOCK + "src/tests/", WORDS, False)])
        # 0.8.1 keeps the journal under records/ (an older project: state/)
        journals = [root / "qa-factory" / sub / "journal.jsonl" for sub in ("records", "state")]
        text = "".join(j.read_text(encoding="utf-8") for j in journals if j.is_file())
        check("and the human_answer journal line", '"human_answer"' in text and "protected test path" in text, text[-300:])
        # recording the same pattern again replaces the entry, as every override does
        waiver(root, "--stage", "S5", "--block", BLOCK + "src/tests/", "--words-file", words_file(root, "Again, yes."))
        check_eq("a second record of the same pattern replaces the first",
                 [e["decision"] for e in pipeline_of(root)["stage_overrides"]], ["Again, yes."])
        # the way out: revocation
        done = waiver(root, "--revoke", "--stage", "S5", "--block", BLOCK + "src/tests/",
                      "--words-file", words_file(root, "No, take it back."))
        check_eq("a person takes it back (exit 0)", done.returncode, 0)
        revoked = pipeline_of(root)["stage_overrides"][0]
        check("the entry stays, marked revoked", bool(revoked.get("revoked_at")), str(revoked))
        check_eq("and the reader no longer sees a permission",
                 TPG.active_grants(pipeline_of(root), config_of(root), root) if TPG else None, [])
        # K9 (D-0030): a pattern with no usual test name is the person's word - recorded, with an advisory note
        for pattern in ("src/app/", "src/**/*.ts"):
            done = waiver(root, "--stage", "S5", "--block", BLOCK + pattern, "--words-file", words_file(root))
            check_eq(f"no usual test name, recorded (exit 0): {pattern}", done.returncode, 0)
            check_in(f"{pattern}: the advisory note is printed, verbatim", note_1(pattern), done.stdout)
            check_in(f"{pattern}: and the grant line with its door", " " + DOOR.format(p=pattern), done.stdout)
            check_not_in(f"{pattern}: nothing was refused", "does not say by its own path", done.stderr)
            check_in(f"{pattern}: the record is on disk", BLOCK + pattern,
                     [e["match"] for e in pipeline_of(root)["stage_overrides"]])
        check_eq("the boundary refusal is unchanged next to them", waiver(root, "--stage", "S5", "--block",
                 BLOCK + "src/", "--words-file", words_file(root)).returncode, 2)
    finally:
        cleanup(root)


def part_record_without_markers() -> None:
    """K9, in-process (the waiver as a child cannot be given another references folder): with the list of
    usual test names missing, the record is made AND the note says the name was not checked."""
    import hooklib
    import waiver as W
    root = project("qa-tpg-record-nodata-")
    real_ref = hooklib.ref
    empty = Path(tempfile.mkdtemp(prefix="qa-markers-record-"))
    out = io.StringIO()
    try:
        use_project(root)
        hooklib.ref = lambda rel: empty / rel
        from contextlib import redirect_stdout
        with redirect_stdout(out):
            code = W.run_stage(TICKET, "S5", BLOCK + "src/app/", WORDS, "human")
        check_eq("the markers file is missing: the record is made (exit 0)", code, 0)
        check_in("and the note says the name was not checked, verbatim",
                 note_2("src/app/", "missing, unreadable or empty"), out.getvalue())
        check_in("and the door is still named", " " + DOOR.format(p="src/app/"), out.getvalue())
        check_eq("the record is on disk", [e["match"] for e in pipeline_of(root)["stage_overrides"]],
                 [BLOCK + "src/app/"])
    finally:
        hooklib.ref = real_ref
        cleanup(empty)
        cleanup(root)


def part_empty_gap_id() -> None:
    root = project("qa-tpg-gapid-")
    try:
        before = pipeline_of(root)
        for label, words in (("first word an option", "accept - the person wrote: TC-7: accept"),
                             ("in the person's own words", WORDS)):
            done = waiver(root, "--stage", "S9", "--block", "stand gap:", "--words-file", words_file(root, words))
            check_eq(f"a NEW stand-gap record that names no gap is refused ({label}): exit 2", done.returncode, 2)
            check_in(f"{label}: what is wrong", 'waiver: "stand gap:" names no gap', done.stderr)
            check_in(f"{label}: what is expected", "the id of the card after \"stand gap:\"", done.stderr)
            check_in(f"{label}: how to satisfy it", '--block "stand gap: <id>"', done.stderr)
            check_in(f"{label}: the words go in a file whose first word is the answer",
                     "--words-file <file>), the file starting with their answer: \"<apply | theirs | handed | "
                     "accept> - the person wrote: <their words>\"", done.stderr)
            check_in(f"{label}: and that nothing was recorded", "Nothing was recorded.", done.stderr)
            check_eq(f"{label}: no override was written", pipeline_of(root), before)
        # an EXISTING record with an empty id stays on disk and is skipped by the reader, not refused:
        # a revocation of it is not a new record
        path = root / "qa-factory" / "artifacts" / TICKET / "pipeline.json"
        data = pipeline_of(root)
        data["stage_overrides"] = [{"stage": "S9", "match": "stand gap:", "decision": "old", "at": AT, "by": "human"}]
        path.write_text(json.dumps(data), encoding="utf-8")
        import contract
        check_eq("an existing record with an empty id is skipped by the reader",
                 contract.stand_gap_decisions(pipeline_of(root)), {})
        done = waiver(root, "--revoke", "--stage", "S9", "--block", "stand gap:", "--words-file", words_file(root))
        check_eq("and it can still be revoked (not refused)", done.returncode, 0)
        done = waiver(root, "--stage", "S9", "--block", "stand gap: TC-7",
                      "--words-file", words_file(root, "accept - the person wrote: TC-7: accept"))
        check_eq("a record that names its gap is unchanged (exit 0)", done.returncode, 0)
    finally:
        cleanup(root)


# --- (d) the guard -----------------------------------------------------------------------------------

def journal_rows(root: Path) -> list:
    """The `hook_signal` rows of the project's journal (RH1-5: a pass, a warning goes to the person's journal, not to stderr at exit 0)."""
    import hooklib
    import runtime_paths as RP
    cfg = hooklib.read_json(root / "qa-factory" / "config.json", {}, kind=dict)      # THIS project's, whatever the process root is
    path = RP.configured(root, cfg.get("journal_path"), "journal.jsonl")
    if not path.is_file():
        return []
    rows = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
    return [r for r in rows if r.get("event") == "hook_signal"]


def guarded(event: dict) -> tuple:
    """(exit code or None, what the guard said) for one call. The guard is a function here: a test
    that shelled out would not see its stderr as a hook does. What it SAID is its stderr plus the notes of the
    `hook_signal` rows it wrote during the call (RH1-5, H8/H9: a pass is recorded for the person, not printed);
    the rows themselves are in `guarded.rows` for a check on kind and task."""
    import guard_app_under_test
    from hooklib import load_config
    root = Path(event["cwd"])
    before = len(journal_rows(root))
    err = io.StringIO()
    code = None
    try:
        with redirect_stderr(err):
            guard_app_under_test.check(event, load_config(event))
    except SystemExit as exc:
        code = exc.code
    guarded.rows = journal_rows(root)[before:]
    guarded.err = err.getvalue()
    return code, "\n".join([err.getvalue()] + [str(r.get("notes") or "") for r in guarded.rows])


guarded.rows = []
guarded.err = ""


def call(tool: str, root: Path, rel: str, role="qa-automator", ticket=TICKET, **tool_input) -> dict:
    key = "notebook_path" if tool == "NotebookEdit" else "file_path"
    event = {"tool_name": tool, "cwd": str(root), "tool_input": dict({key: str(root / rel)}, **tool_input)}
    if tool == "Write":
        event["tool_input"].setdefault("content", "def test_new():\n    assert True\n")
    if role:
        event["agent_type"] = role
    if ticket:
        event["task_id"] = ticket
    return event


HOW = ("If this file is a test that has to live inside the application tree, do not write it another way: "
       "name the path in your handover and halt. The person can open test files there for the automator; "
       "only when they agreed to that, the orchestrator records their words as they were given: waiver.py "
       "--task <TICKET> --stage S5 --block \"protected test path: <folder/ or pattern>\" --words-file <file> "
       "(when they did not agree, nothing is recorded under this block).")
DELETE_MOVE = ("Deleting or moving a file inside the application tree is never opened by a permission; only "
               "writing test files is.")
PASSED = "APP-UNDER-TEST BOUNDARY: passed by the person's recorded permission for test files under"


def part_guard() -> None:
    root = project("qa-tpg-guard-", stories={TICKET: [grant_entry("src/tests/")]})
    try:
        use_project(root)
        code, said = guarded(call("Write", root, "src/tests/test_new.py"))
        check_eq("the automator writes a test inside the granted folder", code, None)
        check_in("and the guard says so, verbatim, with the person's words, the pattern and the date",
                 f"{PASSED} 'src/tests/' ({TICKET}, 2026-10-03): \"{WORDS}\" - the automator writes "
                 f"'{root / 'src' / 'tests' / 'test_new.py'}'. Application code outside that pattern stays "
                 "closed, and deleting or moving files stays closed.", said)
        check_eq("...and it is ONE journal signal of kind pass_recorded for this story (not a line on stderr)",
                 [(r.get("kind"), r.get("task")) for r in guarded.rows], [("pass_recorded", TICKET)])
        for tool, extra in (("Edit", {"old_string": "assert 1", "new_string": "assert 2"}),
                            ("NotebookEdit", {"new_source": "x"})):
            rel = "src/tests/test_old.py" if tool == "Edit" else "src/tests/n.ipynb"
            code, said = guarded(call(tool, root, rel, **extra))
            check_eq(f"{tool} is opened by the same permission", code, None)
        code, said = guarded(call("Write", root, "src/tests/deep/er/test_deeper.py"))
        check_eq("a file deeper inside the granted folder is opened", code, None)
        code, said = guarded(call("Write", root, "src/tests/test_new.py", role="qa-factory:qa-automator"))
        check_eq("the role is read without its plugin namespace", code, None)
        code, said = guarded(call("Write", root, "src/tests/test_old.py", content="def test_b():\n    pass\n"))
        check_eq("a write that REPLACES an existing test with content is a write, not a delete", code, None)
        code, said = guarded(call("Write", root, "src/tests/test_empty_new.py", content=""))
        check_eq("an empty Write to a file that does not exist yet creates nothing to lose", code, None)

        # a target outside the pattern stays blocked, with the base text and what to do
        code, said = guarded(call("Write", root, "src/app/x.py"))
        check_eq("application code outside the pattern stays blocked", code, 2)
        check_in("the base text is what it always was", "APP-UNDER-TEST BOUNDARY: writing to '", said)
        check_in("and says it is forbidden for test phases", "Test phases never modify application code", said)
        check_in("the automator is told the way out, verbatim", HOW, said)
        # S1: the record under this block IS the consent (`active_grants` reads any non-empty decision), so
        # the door must not prescribe a first word - a refusal written as directed would open the pattern
        check_not_in("the M15 door prescribes no `apply -` first word", "apply -", said)
        check_in("and says the record is made only when the person agreed", "only when they agreed", said)
        check_in("and that a refusal records nothing", "when they did not agree, nothing is recorded", said)
        for refusal in ("apply - the person wrote: no, keep it closed", "theirs - the person wrote: no"):
            check_eq(f"the grammar reads the record as the consent whatever its words ({refusal!r}), "
                     "which is why only agreement is ever recorded",
                     bool(TPG.grant_for({"stage_overrides": [grant_entry("src/tests/", words=refusal)]},
                                        str(root / "src" / "tests" / "test_new.py"),
                                        {"protected_app_paths": ["src"]}, root)), True)
        check_not_in("it is not told a permission was used", PASSED, said)
        check_not_in("nor that a story could not be named", "could not be tied to one story", said)
        check_not_in("nor about deletes", "Deleting or moving", said)
        code, said = guarded(call("Write", root, "src/tests/../app/x.py"))
        check_eq("a `..` out of the test folder is judged on the RESOLVED target", code, 2)
        link = root / "src" / "tests" / "link.py"
        try:
            os.symlink(root / "src" / "app" / "x.py", link)
        except (OSError, NotImplementedError, AttributeError):
            print("symlinks cannot be made here without a privilege: trying a directory junction")
            junction = root / "src" / "tests" / "jlink"
            made = os.name == "nt" and subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(junction), str(root / "src" / "app")],
                capture_output=True).returncode == 0
            if made:
                code, said = guarded(call("Write", root, "src/tests/jlink/x.py"))
                check_eq("a junction inside the test folder cannot lead into application code", code, 2)
                subprocess.run(["cmd", "/c", "rmdir", str(junction)], capture_output=True)
            else:
                print("SKIPPED: no symlink and no junction here (the `..` case above proves the resolved target)")
        else:
            code, said = guarded(call("Write", root, "src/tests/link.py"))
            check_eq("a symlink inside the test folder cannot lead into application code", code, 2)

        # delete and move: never opened (7a item 7), even for a file inside the pattern
        code, said = guarded(call("Edit", root, "src/tests/test_old.py", patch_operation="delete"))
        check_eq("a delete of a test inside the pattern is refused", code, 2)
        check_in("with the sentence that says why", DELETE_MOVE, said)
        check_in("and the way out", HOW, said)
        for label, rel in (("source", "src/tests/test_old.py"), ("destination", "src/tests/test_moved.py")):
            code, said = guarded(call("Edit", root, rel, patch_operation="update", patch_move=True))
            check_eq(f"a move ({label}) is refused", code, 2)
            check_in(f"a move ({label}) says why", DELETE_MOVE, said)
        code, said = guarded(call("Write", root, "src/tests/test_old.py", content=""))
        check_eq("a Write with empty content over an EXISTING file is refused like a delete", code, 2)
        check_in("with the delete sentence", DELETE_MOVE, said)
        code, said = guarded(call("Write", root, "src/tests/test_old.py", content="  \n\n"))
        check_eq("a Write of nothing but whitespace is empty too", code, 2)
        whole = (root / "src" / "tests" / "test_old.py").read_text(encoding="utf-8")
        code, said = guarded(call("Edit", root, "src/tests/test_old.py", old_string=whole, new_string=""))
        check_eq("an Edit that leaves an existing file empty is refused like a delete", code, 2)
        check_in("with the delete sentence", DELETE_MOVE, said)
        code, said = guarded(call("Edit", root, "src/tests/test_old.py", old_string="assert 1", new_string=""))
        check_eq("an Edit that leaves other text in the file is an edit", code, None)

        # Bash and PowerShell are never opened, and the block says which tools cover the permission
        for tool in ("Bash", "PowerShell"):
            target = str(root / "src" / "tests" / "test_shell.py")
            code, said = guarded({"tool_name": tool, "cwd": str(root), "agent_type": "qa-automator",
                                  "task_id": TICKET, "tool_input": {"command": f"echo x > {target}"}})
            check_eq(f"{tool} writing a test inside the granted folder stays blocked", code, 2)
            check_in(f"{tool}: the block names Write and Edit as the covered tools, verbatim",
                     "The recorded permission for 'src/tests/' covers Write and Edit only: write the test "
                     "with one of them.", said)
        code, said = guarded({"tool_name": "Bash", "cwd": str(root), "agent_type": "qa-automator", "task_id": TICKET,
                              "tool_input": {"command": f"echo x > {root / 'src' / 'app' / 'x.py'}"}})
        check_eq("a shell write outside the pattern is blocked", code, 2)
        check_not_in("and carries no sentence about a permission it does not have", "covers Write and Edit only", said)
        code, said = guarded({"tool_name": "Bash", "cwd": str(root), "tool_input": {
            "command": f"echo x > {root / 'src' / 'tests' / 'test_shell.py'}"}})
        check_eq("a shell write by the orchestrator is blocked", code, 2)
        check_not_in("and is not told about the automator's permission", "covers Write and Edit only", said)

        # nobody else is opened
        for role, label in (("qa-code-critic", "the critic"), ("qa-scout", "another role"), ("", "the orchestrator"),
                            ("general-purpose", "a built-in agent")):
            code, said = guarded(call("Write", root, "src/tests/test_new.py", role=role))
            check_eq(f"{label} is never opened", code, 2)
            check_not_in(f"{label}: and is not shown the automator's way out", HOW, said)
        code, said = guarded(call("Write", root, "src/tests/test_new.py", role="", ticket=""))
        check_eq("a Codex child with no binding (no role, no story) fails closed", code, 2)

        # a write outside every protected path is not this guard's business
        code, said = guarded(call("Write", root, "tests/test_ok.py"))
        check_eq("a write outside protected_app_paths passes untouched", (code, said), (None, ""))
    finally:
        cleanup(root)


HARDLINK = ("This file has more than one name on disk (a hard link), so writing it could change application "
            "code: write the test as a new file.")
STAT_ERROR = ("The guard could not read this file's entry on disk, so it cannot tell whether writing it would "
              "change application code: write the test as a new file.")


def part_hard_link() -> None:
    """F4: a hard link inside the test folder IS the application file under a test name; the resolved
    path cannot tell (a link is not a symlink), so an existing target with more than one name is refused."""
    root = project("qa-tpg-hardlink-", stories={TICKET: [grant_entry("src/tests/")]})
    try:
        use_project(root)
        app_file = root / "src" / "app" / "x.py"
        link = root / "src" / "tests" / "test_x_link.py"
        try:
            os.link(app_file, link)
        except (OSError, NotImplementedError, AttributeError) as exc:
            print(f"SKIPPED: this OS refused to make a hard link ({exc}); F4's hard-link cases did not run")
            return
        check_eq("control: it is one file with two names", os.stat(app_file).st_nlink, 2)
        for tool, extra in (("Write", {"content": "x = 'changed by the automator'\n"}),
                            ("Edit", {"old_string": "x = 1", "new_string": "x = 2"})):
            code, said = guarded(call(tool, root, "src/tests/test_x_link.py", **extra))
            check_eq(f"F4: a {tool} through a hard link is refused", code, 2)
            check_in(f"{tool}: with the one appended sentence, verbatim", HARDLINK, said)
            check_in(f"{tool}: and the way out the automator always gets", HOW, said)
            check_not_in(f"{tool}: no permission is quoted as used", PASSED, said)
        check_eq("nothing wrote the application file", app_file.read_text(encoding="utf-8"), "x = 1\n")
        # the same call for an ordinary existing test (one name) is still opened: the refusal is the link's
        code, said = guarded(call("Write", root, "src/tests/test_old.py", content="def test_b():\n    pass\n"))
        check_eq("control: an existing test with one name is written", (code, HARDLINK in said), (None, False))
        # a target that does not exist yet has no second name: unchanged
        code, said = guarded(call("Write", root, "src/tests/test_brand_new.py"))
        check_eq("a target that does not exist yet is opened as before", code, None)
        # the link is gone: the same file is an ordinary file again
        os.unlink(link)
        code, said = guarded(call("Write", root, "src/tests/test_x_link.py"))
        check_eq("after the link is removed the name is an ordinary new file", code, None)
        # a stat that fails is a refusal, never a pass (fail closed)
        real_stat = os.stat

        def faulty(path, *args, **kwargs):
            if str(path).replace("\\", "/").endswith("src/tests/test_old.py"):
                raise PermissionError(13, "Permission denied")
            return real_stat(path, *args, **kwargs)
        os.stat = faulty
        try:
            code, said = guarded(call("Write", root, "src/tests/test_old.py", content="def test_c():\n    pass\n"))
        finally:
            os.stat = real_stat
        check_eq("a stat error on the target is a refusal", code, 2)
        check_not_in("and does not claim a hard link it cannot see", HARDLINK, said)
        # R9 (t-076): a refusal for a reason the automator cannot see says what the guard could not do
        check_in("R9: the refusal says the guard could not read the file's entry, and what to do, verbatim",
                 STAT_ERROR, said)
        check_in("R9: and the way out the automator always gets", HOW, said)
        check_not_in("R9: no permission is quoted as used", PASSED, said)
        check_not_in("R9: the sentence is for a failed stat only: the ordinary refusal does not carry it",
                     STAT_ERROR, guarded(call("Write", root, "src/app/x.py"))[1])
    finally:
        cleanup(root)


def part_other_stories() -> None:
    root = project("qa-tpg-stories-", stories={TICKET: [], "QA-2": [grant_entry("src/tests/")]})
    try:
        use_project(root)
        code, said = guarded(call("Write", root, "src/tests/test_new.py", ticket="QA-2"))
        check_eq("the story that holds the permission is opened", code, None)
        code, said = guarded(call("Write", root, "src/tests/test_new.py", ticket=TICKET))
        check_eq("another story, with no permission of its own, is not", code, 2)
        check_not_in("and no permission is quoted for it", PASSED, said)
        code, said = guarded(call("Write", root, "src/tests/test_new.py", ticket="QA-9"))
        check_eq("a story that does not exist is not opened by anyone's permission", code, 2)
    finally:
        cleanup(root)
    root = project("qa-tpg-two-running-", stories={TICKET: [grant_entry("src/tests/")], "QA-2": [grant_entry("src/tests/")]})
    try:
        use_project(root)
        code, said = guarded(call("Write", root, "src/tests/test_new.py", ticket=""))
        check_eq("two running stories and no id: no ticket, so nothing opens", code, 2)
        check_in("the block says the story could not be named, with how many and which",
                 "A recorded permission is read per story, and this write could not be tied to one story "
                 "(2 stories are running: ", said)
        check("the ids are named", TICKET in said and "QA-2" in said, said)
        check_in("and the automator still gets the way out", HOW, said)
        code, said = guarded(call("Write", root, "src/tests/test_new.py", ticket="", role=""))
        check_eq("the orchestrator in the same situation is blocked as before", code, 2)
        check_not_in("and is not shown that sentence", "could not be tied to one story", said)
    finally:
        cleanup(root)
    root = project("qa-tpg-one-running-", stories={TICKET: [grant_entry("src/tests/")]})
    try:
        use_project(root)
        code, said = guarded(call("Write", root, "src/tests/test_new.py", ticket=""))
        check_eq("one running story and no id: that story is the ticket (the compatibility path)", code, None)
    finally:
        cleanup(root)


def part_dead_grants() -> None:
    revoked = project("qa-tpg-revoked-", stories={TICKET: [grant_entry("src/tests/", revoked_at="2026-10-04T00:00:00+00:00")]})
    try:
        use_project(revoked)
        code, said = guarded(call("Write", revoked, "src/tests/test_new.py"))
        check_eq("a revoked permission opens nothing", code, 2)
    finally:
        cleanup(revoked)
    moved = project("qa-tpg-config-", protected=("src/tests",), stories={TICKET: [grant_entry("src/tests/")]})
    try:
        use_project(moved)
        code, said = guarded(call("Write", moved, "src/tests/test_new.py"))
        check_eq("a config change made the pattern equal a protected root: the grant is dead", code, 2)
    finally:
        cleanup(moved)
    old = project("qa-tpg-old-", stories={TICKET: [grant_entry("src/app/*.ts"), grant_entry("src/**/*.ts")]})
    try:
        use_project(old)
        (old / "src" / "app" / "view.ts").write_text("export {}\n", encoding="utf-8")
        code, said = guarded(call("Write", old, "src/app/view.ts"))
        check_eq("D-0030: a grant with no usual test name is the person's recorded word, and the guard opens "
                 "it for that story's automator", code, None)
        code, said = guarded(call("Write", old, "src/app/new.ts"))
        check_eq("and so is the one that covers every .ts file (the person was shown its count when it "
                 "mattered; the markers do not gate it)", code, None)
        code, said = guarded(call("Write", old, "src/app/x.py"))
        check_eq("what no grant covers stays closed", code, 2)
        code, said = guarded(call("Write", old, "src/app/new.ts", role="qa-code-critic"))
        check_eq("and another role is still not opened by a per-story grant", code, 2)
    finally:
        cleanup(old)
    nodata = project("qa-tpg-nodata-", stories={TICKET: [grant_entry("src/tests/")]})
    import hooklib
    real_ref = hooklib.ref
    empty = Path(tempfile.mkdtemp(prefix="qa-markers-guard-"))
    try:
        use_project(nodata)
        hooklib.ref = lambda rel: empty / rel
        code, said = guarded(call("Write", nodata, "src/tests/test_new.py"))
        check_eq("the data file missing: the grant is the person's word and still opens (D-0030), "
                 "and the guard does not raise", code, None)
        code, said = guarded(call("Write", nodata, "src/app/x.py"))
        check_eq("and what no grant covers stays closed", code, 2)
    finally:
        hooklib.ref = real_ref
        cleanup(empty)
        cleanup(nodata)


def part_stage_is_not_read() -> None:
    root = project("qa-tpg-s7-", stories={TICKET: [grant_entry("src/tests/")]})
    try:
        use_project(root)
        data = pipeline_of(root)
        data["stages"] = {"S7": {"status": "running"}}
        (root / "qa-factory" / "artifacts" / TICKET / "pipeline.json").write_text(json.dumps(data), encoding="utf-8")
        code, said = guarded(call("Write", root, "src/tests/test_new.py"))
        check_eq("S7 (a repair after triage) is opened by the same permission: the stage is not read", code, None)
    finally:
        cleanup(root)


# --- the first-word re-record door of the apply grant ----------------------------------------------------

def part_first_word_door() -> None:
    import contract
    import stand_gaps
    root = project("qa-tpg-door-")
    real = (stand_gaps.apply_grant, stand_gaps.grant_used)
    try:
        use_project(root)
        grant = {"gap": "PC-1", "task": TICKET, "stage": "S5", "file": "src/app/x.py", "words": "apply",
                 "at": AT, "task_root": str(root / "qa-factory" / "artifacts" / TICKET)}
        stand_gaps.apply_grant = lambda *a, **k: dict(grant)
        stand_gaps.grant_used = lambda *a, **k: {"at": "2026-10-03T11:00:00+00:00"}
        code, said = guarded({"tool_name": "Write", "cwd": str(root),
                              "tool_input": {"file_path": str(root / "src" / "app" / "x.py"), "content": "x = 2\n"}})
        check_eq("an apply decision that was already used blocks the second write", code, 2)
        check_in("the re-record names the words file and what its first word must be",
                 f'`waiver.py --task {TICKET} --stage S5 --block "stand gap: PC-1" --words-file <file>`, the file '
                 "holding `apply - the person wrote: <what to change>`", said)
        check_not_in("no typed --option door is left", "--option", said)
        check_not_in("no inline --decision door is left", '--decision "apply, once more', said)
        spans = [s for s in re.findall(r"`(waiver\.py[^`]*)`", said) if "--words-file" in s]
        if not spans:
            check("the printed door can be opened (a waiver command with --words-file is printed)", False, said[-300:])
            return
        span = spans[-1]
        argv = shlex.split(span[:span.index("--words-file")])
        said_again = "apply - the person wrote: once more: under features"
        done = run_script(argv[0], *argv[1:], "--words-file", words_file(root, said_again),
                          cwd=root, env=dict(os.environ, CLAUDE_PROJECT_DIR=str(root)))
        check_eq("the door as printed is opened by the real waiver.py (exit 0)", done.returncode, 0)
        entries = pipeline_of(root)["stage_overrides"]
        check_eq("and records the person's words, whose first word is the answer",
                 [(e["match"], e["decision"], "option" in e) for e in entries],
                 [("stand gap: PC-1", said_again, False)])
        check_eq("which the one reader reads as apply", contract.stand_gap_decisions(pipeline_of(root))["PC-1"]["option"],
                 "apply")
    finally:
        stand_gaps.apply_grant, stand_gaps.grant_used = real
        cleanup(root)


def part_first_word_reading() -> None:
    """The guard opens ONE application file for the orchestrator on a stand-gap answer, and the answer is
    read by `contract.stand_gap_decisions`: the FIRST word of the decision, a revoked record never."""
    import stand_gaps
    gap = {"id": "PC-1", "stage": "S5", "remedy": {"kind": "data", "where": "src/app/x.py:1", "change": "set x to 2"}}
    real = stand_gaps.collect
    stand_gaps.collect = lambda *a, **k: [dict(gap)]  # the card's remedy is not what this part tests
    try:
        for label, extra, words, opens in (
                ("an `apply - ...` decision", {}, "apply - the person wrote: set x to 2", True),
                ("a bare `apply`", {}, "apply", True),
                ("`Apply, once more: ...`", {}, "Apply, once more: under features", True),
                ("`please apply` (the option is not the first word)", {}, "please apply", False),
                ("`applied` (a word that merely starts like one)", {}, "applied - the person wrote: x", False),
                ("a revoked `apply`", {"revoked_at": "2026-10-04T00:00:00+00:00"}, "apply - the person wrote: x", False)):
            entry = {"stage": "S5", "match": "stand gap: PC-1", "decision": words, "at": AT, "by": "human"}
            entry.update(extra)
            root = project("qa-tpg-first-", stories={TICKET: [entry]})
            try:
                use_project(root)
                code, said = guarded(call("Write", root, "src/app/x.py", role=None, ticket=""))
                check_eq(f"{label}: the orchestrator's write to the file the card names "
                         + ("passes" if opens else "stays blocked"), code, None if opens else 2)
                if opens:
                    check_in(f"{label}: and the guard says whose decision passed it",
                             f"passed by your decision on stand gap PC-1 ({TICKET})", said)
                    check_eq(f"{label}: ...as a journal signal of kind pass_recorded",
                             [r.get("kind") for r in guarded.rows], ["pass_recorded"])
                code, said = guarded(call("Write", root, "src/app/other.py", role=None, ticket=""))
                check_eq(f"{label}: another application file stays closed", code, 2)
            finally:
                cleanup(root)
    finally:
        stand_gaps.collect = real


# --- (e) the legacy port: the Codex run's test through the real hook process ---------------------------

def run_hook(root: Path, event: dict):
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(root), PYTHONDONTWRITEBYTECODE="1")
    return subprocess.run([sys.executable, "-B", str(SCRIPTS / "guard_pre_tool.py")],
                          input=json.dumps(dict(event, cwd=str(root))), text=True, capture_output=True,
                          encoding="utf-8", env=env, cwd=str(root), timeout=120)


def part_legacy_port() -> None:
    """test_codex_host.test_s5_protected_test_path_requires_exact_recorded_authorization, with the
    key `protected test path: src/tests/` in place of the legacy `protected-path`."""
    root = temp_dir("qa-tpg-legacy-")
    try:
        (root / "qa-factory" / "artifacts" / "QA-1").mkdir(parents=True)
        (root / "src" / "tests").mkdir(parents=True)
        (root / "qa-factory" / "config.json").write_text(
            json.dumps({"schema_version": 1, "protected_app_paths": ["src"]}), encoding="utf-8")
        pipeline = {"stages": {"S5": {"status": "running"}}, "stage_overrides": [
            {"stage": "S5", "match": "protected test path: src/tests/",
             "decision": "authorized test automation path"}]}
        (root / "qa-factory" / "artifacts" / "QA-1" / "pipeline.json").write_text(json.dumps(pipeline), encoding="utf-8")
        allowed = {"tool_name": "Edit", "task_id": "QA-1", "agent_type": "qa-automator",
                   "tool_input": {"file_path": "src/tests/test_feature.py"}}
        result = run_hook(root, allowed)
        check_eq("legacy: the automator's Edit of a file under the recorded test path passes", result.returncode, 0)
        legacy_rows = journal_rows(root)
        check_in("legacy: the pass is recorded for the person (a journal signal, not stderr at exit 0)",
                 "passed by the person's recorded permission", [str(r.get("notes")) for r in legacy_rows])
        check_eq("legacy: ...of kind pass_recorded, for the story", [(r.get("kind"), r.get("task")) for r in legacy_rows],
                 [("pass_recorded", "QA-1")])
        production = {"tool_name": "Edit", "task_id": "QA-1", "agent_type": "qa-automator",
                      "tool_input": {"file_path": "src/service.py"}}
        check_eq("legacy: production code stays blocked", run_hook(root, production).returncode, 2)
        check_eq("legacy: the critic is blocked on the same path",
                 run_hook(root, dict(allowed, agent_type="qa-code-critic")).returncode, 2)
        patch = {"tool_name": "apply_patch", "turn_id": "t", "task_id": "QA-1", "agent_type": "qa-automator",
                 "tool_input": {"command": "*** Begin Patch\n*** Update File: src/tests/test_feature.py\n"
                                           "*** Move to: src/tests/test_renamed.py\n@@\n-a\n+b\n*** End Patch"}}
        result = run_hook(root, patch)
        check_eq("legacy: a Codex patch that MOVES a test file is refused (source and destination)",
                 result.returncode, 2)
        check_in("legacy: and says why", DELETE_MOVE, result.stderr)
        patch["tool_input"]["command"] = ("*** Begin Patch\n*** Delete File: src/tests/test_feature.py\n"
                                          "*** End Patch")
        check_eq("legacy: a Codex patch that deletes a test file is refused", run_hook(root, patch).returncode, 2)
        patch["tool_input"]["command"] = ("*** Begin Patch\n*** Add File: src/tests/test_added.py\n+def test_x():\n"
                                          "+    pass\n*** End Patch")
        result = run_hook(root, patch)
        check_eq("legacy: a Codex patch that ADDS a test file under the path passes", result.returncode, 0)
    finally:
        cleanup(root)


def part_notices_to_journal() -> None:
    """RH1-5 B8 (moved from test_app_boundary_notices): the guard's advice about the config, and a pass, go to the journal
    as a `hook_signal` and never to stderr at exit 0."""
    import test_locations as TL
    import uuid
    run = uuid.uuid4().hex[:8]       # the once-per-session marker lives in the OS temp: a fresh session id per run

    def raising(*_a, **_k):
        raise RuntimeError("cannot check")

    cases = (("H4 protected paths not on disk", ("no_such_dir",), None, None, "protected paths not found"),
             ("H7 protected_app_paths empty", (), None, None, "protected_app_paths is empty"),
             ("H6 test_locations problems", ("src",), {"test_locations": [""]}, None, "test_locations in qa-factory/config.json"),
             ("H5 location check raised", ("src",), {"test_locations": [""]}, raising, "could not be checked (RuntimeError)"))
    for label, protected, extra, patch, fragment in cases:
        root = project("qa-tpg-notice-", protected=protected, config_extra=extra)
        real = TL.location_problems
        try:
            use_project(root)
            event = call("Write", root, "tests/x.py", role="", ticket="")
            event["session_id"] = f"{label[:2]}-{run}"
            if patch:
                TL.location_problems = patch
            code, _said = guarded(event)
            rows = [r for r in guarded.rows if fragment in str(r.get("notes"))]
            check_eq(f"{label}: one config signal, nothing on stderr, no block", (len(rows), rows[0]["kind"] if rows else None, guarded.err, code),
                     (1, "config", "", None))
            if label.startswith("H4"):
                guarded(event)
                check_eq("H4: once per session: the second call adds none", len(guarded.rows), 0)
        finally:
            TL.location_problems = real
            cleanup(root)
    root = project("qa-tpg-notice-", stories={TICKET: [grant_entry("src/tests/")]})
    try:
        use_project(root)
        code, _said = guarded(call("Write", root, "src/tests/test_new.py"))
        check_eq("H8: a permission pass is a pass_recorded signal and nothing on stderr",
                 (code, [r.get("kind") for r in guarded.rows], guarded.err), (None, ["pass_recorded"], ""))
    finally:
        cleanup(root)


def part_patch_move_key() -> None:
    from host_adapter import mutation_events, normalize
    event = normalize({"tool_name": "apply_patch", "cwd": str(SCRIPTS), "tool_input": {"command": (
        "*** Begin Patch\n*** Update File: old.txt\n*** Move to: new.txt\n@@\n-old\n+new\n"
        "*** Update File: same.txt\n@@\n-a\n+b\n*** Delete File: gone.txt\n*** Add File: added.txt\n+data\n"
        "*** End Patch")}})
    marks = [(Path(o["tool_input"]["file_path"]).name, bool(o["tool_input"].get("patch_move")),
              o["tool_input"]["patch_operation"]) for o in mutation_events(event)]
    check_eq("host_adapter marks BOTH events of a move with `patch_move`, and nothing else",
             marks, [("old.txt", True, "update"), ("new.txt", True, "update"), ("same.txt", False, "update"),
                     ("gone.txt", False, "delete"), ("added.txt", False, "add")])


def main() -> None:
    os.environ.pop("QA_FACTORY_TASK", None)  # a person's word for the story would name one: not here
    root = temp_dir("qa-tpg-grammar-")
    (root / "src").mkdir()
    try:
        if TPG:
            part_admitted(root)
            part_refused(root)
            part_grammar(root)
            part_roots(root)
            part_data_file(root)
            part_read_time(root)
        else:
            check("the grammar cannot be tested without test_path_grants", False)
    finally:
        cleanup(root)
    part_record()
    part_record_without_markers()
    part_empty_gap_id()
    part_guard()
    part_hard_link()
    part_other_stories()
    part_dead_grants()
    part_stage_is_not_read()
    part_first_word_door()
    part_first_word_reading()
    part_legacy_port()
    part_notices_to_journal()
    part_patch_move_key()
    finish("test_protected_test_path")


if __name__ == "__main__":
    main()
