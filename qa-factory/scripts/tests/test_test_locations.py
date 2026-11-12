#!/usr/bin/env python3
"""The project names where its tests live (D-0030, 06.10.2026, B-415).

`test_locations` in the config is the project's own word: folders or file patterns relative to app_root. A place
listed there is not application code, so the app-boundary guard lets any role write test files there, and keeps
protecting everything else under `protected_app_paths` (P-00). This file tests the places that rule lives:

  (a) the one reader, `test_locations.is_test_path`: the six keys it always returns and never raises (K1), the
      project's folders and file patterns and their boundary siblings (K2), inside application code only the
      project's word answers (K3), the edges (K4: malformed values, grammar, alternate data streams, a whole
      protected root, a nested root, a path outside everything, markers' base) and the three recognition-only
      carriers `run.levels`, `profiles[].roots.test`, `tests_root` (E22-E24) that recognise and never grant;
  (b) the guard (`guard_app_under_test.check`, in-process): who is opened and what is not (K5, K6), the position
      of the carve-out (K7), the warnings (K8), a whole-root conflict (K15);
  (c) `--suggest` / `--check` and the walk cap (K11), through the real CLI;
  (d) the permanent door end to end in a temp project: `project_decisions.py add` + `resolve --words-file
      --field-values` records the words and the list, and the guard then lets the place through (K14).

A permission is narrower than recognition: the guard opens a write only for `source == "test_locations"`.
"""
import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import uuid
from contextlib import redirect_stderr
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import (SCRIPTS, check_eq, check_in, check_not_in, cleanup, finish,  # noqa: E402
                     run_script, temp_dir, use_project)

sys.path.insert(0, str(SCRIPTS))

import test_locations as TL  # noqa: E402

SIX = {"test", "by", "source", "kind", "where", "reason"}
TICKET = "QA-1"
WORDS = "Yes: the legacy checks folder is where we keep our tests, for every story."

# The sentences the guard says, written out here so a change to the text is a change to this file too.
PERMANENT = (" If this is where the project keeps its tests for every story, say so in your handover too: the "
             "orchestrator shows the person what that place holds and, on their word, records it in "
             "test_locations, and no story asks again.")
SHELL = ("A shell command on a whole folder, or on a name the shell expands (a wildcard, a variable, braces), "
         "inside the application tree stays closed even when it is one of the project's test locations: write "
         "or remove the files by name.")
HARDLINK = ("This file has more than one name on disk (a hard link), so writing it could change application "
            "code: write the test as a new file.")
STAT_ERROR = ("The guard could not read this file's entry on disk, so it cannot tell whether writing it would "
              "change application code: write the test as a new file.")
BOUNDARY = "APP-UNDER-TEST BOUNDARY: writing to '"


def whole_root(root_shown: str) -> str:
    return (f"test_locations names all of '{root_shown}', which is also application code in protected_app_paths; "
            f"the orchestrator asks the person which part of '{root_shown}' holds the application code.")


# --- a project -----------------------------------------------------------------------------------------

def project(prefix: str, protected=("src",), locations="absent", extra=None, files=True) -> Path:
    """`src/app`, `src/__checks__` (not a usual test name), `src/legacy/checks` and `tests/` in a temp project,
    with qa-factory/config.json. `locations` is written as `test_locations` unless it is "absent"."""
    root = temp_dir(prefix).resolve()
    for folder in ("src/app", "src/__checks__", "src/legacy/checks", "tests", "qa-factory"):
        (root / folder).mkdir(parents=True)
    if files:
        for rel in ("src/app/x.py", "src/__checks__/a.py", "src/legacy/checks/c.py"):
            (root / rel).write_text("x = 1\n", encoding="utf-8")
    write_config(root, protected, locations, extra)
    return root


def write_config(root: Path, protected=("src",), locations="absent", extra=None) -> dict:
    cfg = {"schema_version": 1, "app_root": ".", "tests_root": ".", "protected_app_paths": list(protected)}
    if locations != "absent":
        cfg["test_locations"] = locations
    cfg.update(extra or {})
    (root / "qa-factory" / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
    return cfg


def verdict(path, cfg, root, **kw) -> dict:
    return TL.is_test_path(path, cfg, root=root, **kw)


# --- (a) the reader --------------------------------------------------------------------------------------

def part_shape(root: Path) -> None:
    """K1: six keys, always, and never an exception - one malformed value per shape of every config key the
    reader reads, against paths of every shape."""
    configs = [None, [], "x", 5, {}, {"test_locations": "src"}, {"test_locations": 5},
               {"test_locations": [None, 3, "", "  ", ["x"], {"a": 1}]}, {"test_locations": {"a": 1}},
               {"test_locations": ["src/**/*.[ab]", "src/{x,y}/", "src/x!/", "/abs/", "C:/x/", "..", "../x/"]},
               {"app_root": 5}, {"app_root": ["x"]}, {"app_root": "  "}, {"protected_app_paths": "src"},
               {"protected_app_paths": [None, 3, ""]}, {"run": []}, {"run": {"levels": 5}},
               {"run": {"levels": {"unit": [None, 3, {}, ""], "api": 7}}}, {"profiles": "x"},
               {"profiles": [None, 3, {"roots": 3}, {"roots": {"test": 5}}, {"roots": {"test": "[["}}]},
               {"tests_root": 7}, {"tests_root": None}, {"tests_root": "[["}]
    paths = ["src/app/x.py", "src/tests/", "", "   ", None, root / "src" / "a.py", "C:/", "/", "x" * 400,
             "src/a:b.ts", "src/*", "src/\x00x", 5]
    bad = []
    for cfg in configs:
        for path in paths:
            try:
                found = TL.is_test_path(path, cfg, root=root)
            except Exception as exc:  # the contract: never raises
                bad.append((cfg, path, f"raised {type(exc).__name__}"))
                continue
            ok = (isinstance(found, dict) and set(found) == SIX and isinstance(found["test"], bool)
                  and found["by"] in ("config", "markers", "none") and found["source"] in TL.SOURCES
                  and found["kind"] in ("folder", "file", "") and isinstance(found["where"], str)
                  and isinstance(found["reason"], str) and found["reason"] != ""
                  and found["test"] == (found["by"] != "none") and (found["by"] == "none") == (found["source"] == ""))
            if not ok:
                bad.append((cfg, path, found))
    check_eq(f"K1: six keys, never raises ({len(configs)} configs x {len(paths)} paths)", bad, [])
    real = TL._Ctx

    class Broken:
        def __init__(self, *a, **k):
            raise RuntimeError("boom")
    TL._Ctx = Broken
    try:
        found = TL.is_test_path("src/x.py", {}, root=root)
    finally:
        TL._Ctx = real
    check_eq("K1: an exception inside is test=False, by=none, source empty, and the reason names its type",
             (set(found), found["test"], found["by"], found["source"], "RuntimeError" in found["reason"]),
             (SIX, False, "none", "", True))
    check_eq("K1: location_problems answers a list for a broken config, and for none at all",
             (isinstance(TL.location_problems({"test_locations": [None, 1]}, None), list),
              TL.location_problems(None, None)), (True, []))
    check_eq("K1: whole_root_conflict never raises either", TL.whole_root_conflict(None, None, root), None)


def part_locations() -> None:
    """K2: a place the project named, whatever it is called; and its boundary siblings are not."""
    root = project("qa-tl-loc-", locations=["src/**/__checks__/", "src/legacy/checks"])
    try:
        cfg = json.loads((root / "qa-factory" / "config.json").read_text(encoding="utf-8"))
        found = verdict("src/f/__checks__/a.ts", cfg, root)
        check_eq("K2: a folder with no usual test name, named by the project, is a test place",
                 (found["test"], found["by"], found["source"], found["kind"], found["where"]),
                 (True, "config", "test_locations", "folder", "src/**/__checks__/"))
        check_eq("K2: `**` also matches no folder at all: `src/__checks__/a.py`",
                 verdict("src/__checks__/a.py", cfg, root)["test"], True)
        for sibling in ("src/f/__checks__x/a.ts", "src/f/__check__/a.ts", "src/__checks__x/a.py", "src/a__checks__/b.py"):
            found = verdict(sibling, cfg, root)
            check_eq(f"K2: the boundary sibling is not a test place: {sibling}",
                     (found["test"], found["by"], found["source"]), (False, "none", ""))
        # F8: a last segment with no wildcard and no slash means that folder and everything below it
        for p in ("src/legacy/checks/c.py", "src/legacy/checks/deep/er/x.py", "src/legacy/checks", "src/legacy/checks/"):
            found = verdict(p, cfg, root)
            check_eq(f"F8: `src/legacy/checks` covers {p}", (found["test"], found["source"], found["kind"]),
                     (True, "test_locations", "folder"))
        for p in ("src/legacy/checksum/c.py", "src/legacy/check/c.py", "src/legacy/c.py", "src/legacy"):
            check_eq(f"F8: and not its sibling {p}", verdict(p, cfg, root)["test"], False)
        # case folds like hooklib.norm; a backslash separator is a separator on Windows only
        check_eq("E7: case does not matter (hooklib.norm folds it)",
                 verdict("SRC/Legacy/CHECKS/c.py", cfg, root)["test"], True)
        if os.name == "nt":
            check_eq("E7: nor does a backslash on Windows", verdict("src\\legacy\\checks\\c.py", cfg, root)["test"], True)
        # E10: a `..` is resolved before matching
        check_eq("E10: `src/legacy/checks/../../app/x.py` is src/app/x.py: not a test place",
                 verdict("src/legacy/checks/../../app/x.py", cfg, root)["test"], False)
        check_eq("E10: and `src/app/../__checks__/a.py` is one",
                 verdict("src/app/../__checks__/a.py", cfg, root)["test"], True)
        check_eq("a relative path is taken from `base`",
                 verdict("legacy/checks/c.py", cfg, root, base=root / "src")["test"], True)
        check_eq("an absolute path is taken as it is", verdict(root / "src" / "__checks__" / "a.py", cfg, root)["test"],
                 True)
    finally:
        cleanup(root)
    root = project("qa-tl-pattern-", locations=["*.spec.ts", "src/*.ts", "**/*.cy.ts"], protected=("src",))
    try:
        cfg = json.loads((root / "qa-factory" / "config.json").read_text(encoding="utf-8"))
        for p, expected in (("a.spec.ts", True), ("src/a.spec.ts", True), ("src/a.ts", True), ("src/app/a.ts", False),
                            ("src/app/deep/a.cy.ts", True), ("a.cy.ts", True), ("src/app/a.cy.tsx", False)):
            found = verdict(p, cfg, root)
            check_eq(f"E6: file patterns keep the waiver language (`*` is one folder, `**` crosses): {p}",
                     found["test"], expected)
        only = dict(cfg, test_locations=["*.spec.ts"])
        check_eq("E6: `*.spec.ts` alone is only files directly in app_root: `src/a.spec.ts` is not one of them",
                 (verdict("a.spec.ts", only, root)["test"], verdict("src/a.spec.ts", only, root)["by"]), (True, "none"))
        check_eq("a file pattern is kind `file`", verdict("src/a.ts", cfg, root)["kind"], "file")
        check_eq("and its `where` is the entry as written", verdict("src/a.ts", cfg, root)["where"], "src/*.ts")
    finally:
        cleanup(root)


def part_inside_application_code() -> None:
    """K3 (F2 b): inside a protected root, once the project has named any location, only that word answers;
    outside the roots the usual names stay the fallback; run.levels alone is not "the project's word"."""
    root = project("qa-tl-f2-", locations=["src/__checks__/"])
    try:
        (root / "tests").mkdir(exist_ok=True)
        cfg = json.loads((root / "qa-factory" / "config.json").read_text(encoding="utf-8"))
        found = verdict("src/app/test_x.py", cfg, root)
        check_eq("K3: a usual test name inside application code is not a test once the project named locations",
                 (found["test"], found["by"], found["source"]), (False, "none", ""))
        check_in("K3: and the reason says why", "inside application code 'src' and in none of the project's test "
                 "locations", found["reason"])
        found = verdict("tests/test_x.py", cfg, root)
        check_eq("K3: outside the protected roots the usual names stay the fallback",
                 (found["test"], found["by"], found["source"], found["kind"]), (True, "markers", "markers", "folder"))
        check_eq("K3: a name marker: `src` is protected, `lib/foo.spec.ts` is not",
                 (verdict("lib/foo.spec.ts", cfg, root)["by"], verdict("lib/foo.spec.ts", cfg, root)["where"]),
                 ("markers", "stem_suffixes:.spec"))
        none = {k: v for k, v in cfg.items() if k != "test_locations"}
        for p in ("src/app/test_x.py", "tests/test_x.py"):
            check_eq(f"K3: with no test_locations both are markers (today's behaviour): {p}",
                     (verdict(p, none, root)["test"], verdict(p, none, root)["by"]), (True, "markers"))
        empty = dict(cfg, test_locations=[])
        check_eq("K3: `[]` is the same as the key absent: markers inside application code",
                 verdict("src/app/test_x.py", empty, root)["by"], "markers")
        levels = dict(none, run={"levels": {"unit": ["tests/**"]}})
        found = verdict("src/app/test_x.py", levels, root)
        check_eq("K3: a config with `run.levels` only: step 3 does not count it, the markers still answer",
                 (found["test"], found["by"], found["source"]), (True, "markers", "markers"))
        malformed = dict(cfg, test_locations="src/__checks__/")
        check_eq("E3: a value that is not a list is not the project's word: markers inside application code",
                 verdict("src/app/test_x.py", malformed, root)["by"], "markers")
        junk = dict(cfg, test_locations=["", None, 3, "/abs/", "src/../x/"])
        check_eq("E3/E4: entries that cannot be read give no 'project's word' either",
                 verdict("src/app/test_x.py", junk, root)["by"], "markers")
        check_eq("E1: no config at all: the usual names", verdict("tests/test_x.py", {}, root)["by"], "markers")
    finally:
        cleanup(root)


def part_edges() -> None:
    root = project("qa-tl-edges-", locations=["src/__checks__/"])
    try:
        cfg = json.loads((root / "qa-factory" / "config.json").read_text(encoding="utf-8"))
        # E11: a colon after the drive is an alternate data stream: no config carrier matches
        found = verdict(str(root / "src" / "app" / "x.py") + ":y.spec.ts", cfg, root)
        check_eq("E11: a stream of an application file is never a test place", found["test"], False)
        found = verdict(str(root / "src" / "__checks__" / "a.py") + ":stream", cfg, root)
        check_eq("E11: not even inside a test location", (found["test"], found["source"]), (False, ""))
        # E12: an entry covering a whole protected root (or the folder that holds one) opens nothing there
        for entry in ("src/", "src", "src/**", "**", "*", "./src/", "SRC\\", "src//", "src/**/*", "src/*.*", "**/"):
            c = dict(cfg, test_locations=[entry])
            for target in ("src/app/x.py", "src/x.py"):
                found = verdict(target, c, root)
                check_eq(f"E12/E20: an entry that covers the whole root opens nothing in it: {entry!r} / {target}",
                         (found["test"], found["by"]), (False, "none"))
            # where the entry does match the target the guard is told the root; `*` and `src/*.*` match fewer
            # segments, so for a deep target they simply are not a test location (and not a conflict either)
            deep = TL.whole_root_conflict(root / "src" / "app" / "x.py", c, root)
            flat = TL.whole_root_conflict(root / "src" / "x.py", c, root)
            check_eq(f"E12: the conflict names the entry and the root where the entry matches: {entry!r}",
                     (deep and deep[1], flat and flat[1]),
                     (None, None) if entry == "*" else (None, "src") if entry == "src/*.*" else ("src", "src"))
            check_eq(f"E12: location_problems says so, once: {entry!r}", len(TL.location_problems(c, root)), 1)
        check_eq("E12: the sentence is the Amendment 5 text",
                 TL.location_problems(dict(cfg, test_locations=["src/"]), root),
                 ["test_locations names all of 'src' ('src/'), which is also application code in protected_app_paths; "
                  "the orchestrator asks the person which part of 'src' holds the application code and records the "
                  "answer with their words (project_decisions.py)."])
        check_eq("E12: a narrower entry next to the whole-root one still counts",
                 verdict("src/__checks__/a.py", dict(cfg, test_locations=["src/", "src/__checks__/"]), root)["test"], True)
        # F1 (critic t-529): a folder segment of nothing but wildcards holding a `*` matches any folder, so these
        # shapes cover the whole root like `**` does; a lone `?` and a segment with a literal do not
        for entry in ("src/*/", "src/?*/", "src/*/**", "src/**/*/", "src/*/*/"):
            c = dict(cfg, test_locations=[entry])
            check_eq(f"F1/E12: {entry!r} covers the whole root: named once, opens nothing in it",
                     (len(TL.location_problems(c, root)), verdict("src/app/x.py", c, root)["test"],
                      verdict("src/x.py", c, root)["test"],
                      (TL.whole_root_conflict(root / "src" / "app" / "x.py", c, root) or ("", ""))[1]),
                     (1, False, False, "src"))
            import test_path_grants as TPG
            refusal = TPG.pattern_errors(entry, {"protected_app_paths": ["src"]}, root)
            check_eq(f"F1: and the waiver refuses the same shape as the boundary: {entry!r}",
                     (len(refusal), "would open the whole of 'src'" in " ".join(refusal)), (1, True))
        for entry in ("src/?/", "src/*/tests/", "src/a*/", "src/*/x.py"):
            c = dict(cfg, test_locations=[entry])
            check_eq(f"F1 control: {entry!r} does not cover the whole root (stays a live entry)",
                     (TL.location_problems(c, root), TPG.pattern_errors(entry, {"protected_app_paths": ["src"]}, root)),
                     ([], []))
        # the real hook: the automator's write inside the root is blocked for the three new shapes
        use_project(root)
        for entry in ("src/*/", "src/?*/", "src/*/**"):
            write_config(root, ("src",), [entry])
            code, said = guarded(call("Write", root, "src/app/m.py"))
            check_eq(f"F1: through the guard, a write under the root is blocked for {entry!r}", code, 2)
        write_config(root, ("src",), ["src/__checks__/"])
        # the whole-root entry that is a HOLDER (protected root is below it)
        nested = dict(cfg, protected_app_paths=["app/src"], test_locations=["app/"])
        (root / "app" / "src").mkdir(parents=True, exist_ok=True)
        check_eq("E12: an entry that covers the folder that holds a root opens nothing inside the root",
                 verdict("app/src/x.py", nested, root)["test"], False)
        check_eq("E12: but opens what is in the holder and not in a root",
                 verdict("app/docs/test_x.py", nested, root)["by"], "config")
        # E13: a protected root nested inside a test location stays protected
        deep = dict(cfg, protected_app_paths=["src", "src/__checks__/fixtures/app"], test_locations=["src/__checks__/"])
        check_eq("E13: the nested root stays protected (the more specific protection wins)",
                 verdict("src/__checks__/fixtures/app/x.py", deep, root)["test"], False)
        check_eq("E13: the rest of the location is still a test place",
                 verdict("src/__checks__/a.py", deep, root)["test"], True)
        # E17: a path outside both app_root and the project root
        other = temp_dir("qa-tl-elsewhere-").resolve()
        try:
            found = verdict(other / "tests" / "test_x.py", cfg, root)
            check_eq("E17: an unknown place is never a test place",
                     (found["test"], found["by"], found["reason"]), (False, "none", "outside the project and the application"))
        finally:
            cleanup(other)
        # E4: a grammar problem opens nothing, and is named
        for entry, why in (("/abs/tests/", "an absolute path"), ("C:/x/tests/", "an absolute path"),
                           ("\\\\server\\share\\t\\", "an absolute path"), ("src/../x/", "outside it ('..')"),
                           ("src/te[st]/", "using '['"), ("src/{a,b}/", "using '{'"), ("src/x!/", "using '!'"),
                           ("", "not a non-empty text")):
            c = dict(cfg, test_locations=[entry])
            found = TL.location_problems(c, root)
            check_eq(f"E4: `{entry}` is named once", len(found), 1)
            check_in(f"E4: with its fault: `{entry}`", why, found[0])
            check_eq(f"E4: and opens nothing: `{entry}`", verdict("src/x/tests/a.py", c, root)["source"], "markers")
        found = TL.location_problems(dict(cfg, test_locations="src/tests/"), root)
        check_eq("E3: a value that is not a list is named, once", (len(found), "not a list" in found[0]), (1, True))
        check_eq("E1/E2: no key, `[]`, no config: nothing to say",
                 [TL.location_problems(c, root) for c in ({}, {"test_locations": []}, None, {"test_locations": None})],
                 [[], [], [], []])
        check_eq("a good entry next to a bad one is used",
                 verdict("src/__checks__/a.py", dict(cfg, test_locations=["/abs/", "src/__checks__/"]), root)["test"],
                 True)
    finally:
        cleanup(root)
    # E18: the folders above the deepest root never count: a checkout under .../tests/...
    base = temp_dir("qa-tl-above-").resolve()
    try:
        proj = base / "tests" / "work" / "proj"
        (proj / "src" / "app").mkdir(parents=True)
        (proj / "qa-factory").mkdir()
        cfg = {"app_root": ".", "protected_app_paths": []}
        found = verdict(proj / "src" / "app" / "x.py", cfg, proj)
        check_eq("E18: a project that lives under a folder named `tests` is not made of tests by that",
                 (found["test"], found["by"]), (False, "none"))
        check_eq("E18: its own tests folder still is", verdict(proj / "tests" / "x.py", cfg, proj)["by"], "markers")
        # the markers base is the DEEPEST of app_root and the project root that holds the path
        (base / "ws" / "th" / "qa-factory").mkdir(parents=True)
        (base / "ws" / "app" / "src").mkdir(parents=True)
        wcfg = {"app_root": "..", "protected_app_paths": []}
        thr = base / "ws" / "th"
        check_eq("S9: relative to app_root for a path in the application (a `th` folder above does not count)",
                 verdict(base / "ws" / "app" / "src" / "x.py", wcfg, thr)["test"], False)
        check_eq("S9: and a usual folder inside the project root counts from the project root",
                 verdict(thr / "tests" / "x.py", wcfg, thr)["by"], "markers")
    finally:
        cleanup(base)
    # E16: a broken markers file: recognition from config only, the reason names the file
    import hooklib
    real_ref = hooklib.ref
    empty = Path(tempfile.mkdtemp(prefix="qa-tl-nomarkers-"))
    root = project("qa-tl-e16-", locations=["src/__checks__/"])
    try:
        hooklib.ref = lambda rel: empty / rel
        cfg = json.loads((root / "qa-factory" / "config.json").read_text(encoding="utf-8"))
        found = verdict("tests/test_x.py", cfg, root)
        check_eq("E16: markers missing: no recognition by name, the reason names the file",
                 (found["test"], "test-path-markers.json" in found["reason"]), (False, True))
        check_eq("E16: the project's word still answers", verdict("src/__checks__/a.py", cfg, root)["test"], True)
        check_eq("E16: markers() says why", TL.markers()[1], "missing, unreadable or empty")
        (empty / "test-path-markers.json").write_text(json.dumps(
            {"dir_names": ["Tests"], "dir_suffixes": [], "stem_prefixes": [], "stem_suffixes": [],
             "stem_camel_suffixes": ["Test"], "code_extensions": [".py"], "skip_dirs": ["x"],
             "later_list": ["y"]}), encoding="utf-8")
        check_eq("a key the loader does not know (a later node's list) is ignored, not rejected; the two B-407 A "
                 "lists are known and the camel list keeps its case",
                 (TL.markers()[1], TL.markers()[0].get("dir_names"), "later_list" in TL.markers()[0],
                  TL.markers()[0].get("stem_camel_suffixes")), ("", ["tests"], False, ["Test"]))
        check_eq("and `skip_dirs` is its own reader", TL.skip_dirs(), ["x"])
    finally:
        hooklib.ref = real_ref
        cleanup(empty)
        cleanup(root)


def part_camel() -> None:
    """B-407 A1 (K-A1, K-A1b, E-A8, E-A13): ONE matcher of a file name (`name_marker`) with the CamelCase endings,
    read by step 4, `suggest` and `check`; it obeys step 3 because it is step 4; the extras never touch the four
    lists a grant depends on."""
    table, why = TL.markers()
    check_eq("K-A1: the shipped table carries the camel list as written (case kept) and the extensions, no problem",
             (why, table["stem_camel_suffixes"], table["extras_problem"], ".cs" in table["code_extensions"],
              ".py" in table["code_extensions"]), ("", ["Test", "Tests", "Spec", "Specs", "IT"], "", True, True))
    check_eq("K-A1: test-harness is a test folder name (the historical handoff exclusion)",
             "test-harness" in table["dir_names"], True)
    yes = ("FooTests.cs", "FooTest.java", "UITest.cs", "FooIT.java", "FooSpec.scala", "BarSpecs.kt")
    no = ("Test.java", "AUDIT.java", "Latest.java", "MyTEST.cs", "Contest.cs", "Tests.cs", "SUBMIT.java", "IT.java")
    check_eq("E-A8: the camel boundary: True for", [TL.name_marker(n, table) != "" for n in yes], [True] * len(yes))
    check_eq("E-A8: ... False for", [TL.name_marker(n, table) != "" for n in no], [False] * len(no))
    check_eq("E-A8: the marker and its list are named", (TL.name_marker("FooTests.cs", table), TL.name_marker("UITest.cs", table)),
             ("stem_camel_suffixes:Tests", "stem_camel_suffixes:Test"))
    check_eq("K-A1: the four lists still answer through the same matcher, lower-cased",
             (TL.name_marker("TEST_x.PY", table), TL.name_marker("a.spec.ts", table), TL.name_marker("a_test.go", table)),
             ("stem_prefixes:test_", "stem_suffixes:.spec", "stem_suffixes:_test"))
    root = temp_dir("qa-tl-camel-").resolve()
    try:
        (root / "lib").mkdir()
        (root / "qa-factory").mkdir()
        # K-A1b: the camel name is `markers` in the verdict itself (the original case reaches step 4)
        found = verdict(root / "lib" / "FooTests.cs", {}, root)
        check_eq("K-A1b: FooTests.cs outside protected code with no config is a test by the usual names",
                 (found["test"], found["by"], found["source"], found["kind"], found["where"]),
                 (True, "markers", "markers", "file", "stem_camel_suffixes:Tests"))
        check_eq("K-A1b: and by its RELATIVE spelling too (taken from `base`)",
                 verdict("lib/FooTests.cs", {}, root)["by"], "markers")
        check_eq("E-A8: Latest.java / AUDIT.java / MyTEST.cs are not",
                 [verdict(root / "lib" / n, {}, root)["test"] for n in ("Latest.java", "AUDIT.java", "MyTEST.cs")],
                 [False, False, False])
        # K-A1: the camel rule is step 4, so step 3 holds it back inside application code the project has spoken for
        cfg = {"protected_app_paths": ["lib"], "test_locations": ["lib/checks/"]}
        found = verdict(root / "lib" / "FooTests.cs", cfg, root)
        check_eq("K-A1: inside application code with a live test_locations that does not cover it, FooTests.cs is no test",
                 (found["test"], found["by"]), (False, "none"))
        check_eq("K-A1: ... and with no test_locations it is a usual name again (step 3 counts only that carrier)",
                 verdict(root / "lib" / "FooTests.cs", {"protected_app_paths": ["lib"]}, root)["by"], "markers")
        check_eq("K-A1: the project's word still opens it",
                 verdict(root / "lib" / "checks" / "FooTests.cs", cfg, root)["source"], "test_locations")
        # suggest / check read the same matcher on the names as written
        (root / "lib" / "FooTests.cs").write_text("x\n", encoding="utf-8")
        (root / "lib" / "Latest.cs").write_text("x\n", encoding="utf-8")
        found = TL.suggest({"app_root": ".", "protected_app_paths": ["lib"]}, root)
        check_eq("K-A1: suggest proposes the camel ending, with the ending as written in the pattern",
                 [(c["pattern"], c["marker"], c["files"]) for c in found["candidates"]],
                 [("lib/**/*Tests.cs", "stem_camel_suffixes:Tests", 1)])
        counted = TL.check({"app_root": ".", "protected_app_paths": ["lib"], "test_locations": ["lib/"]}, root)
        check_eq("K-A1: check counts FooTests.cs as carrying a usual name, Latest.cs as not",
                 (counted["entries"][0]["files"], counted["entries"][0]["without_marker"]), (2, 1))
    finally:
        cleanup(root)
    # E-A13 and the temporal edge: the world before the extras existed, and malformed extras
    import hooklib
    real_ref = hooklib.ref
    fake = Path(tempfile.mkdtemp(prefix="qa-tl-extras-"))
    base = {"dir_names": ["tests"], "dir_suffixes": [], "stem_prefixes": ["test_"], "stem_suffixes": []}
    try:
        hooklib.ref = lambda rel: fake / rel
        for label, extra in (("absent (the file before B-407 A)", {}),
                             ("not lists", {"stem_camel_suffixes": "Tests", "code_extensions": 5}),
                             ("empty items", {"stem_camel_suffixes": ["Tests", ""], "code_extensions": [None]})):
            (fake / "test-path-markers.json").write_text(json.dumps(dict(base, **extra)), encoding="utf-8")
            table, why = TL.markers()
            check_eq(f"E-A13: extras {label}: the four lists and `problem` are untouched",
                     (why, table["dir_names"], table["stem_prefixes"]), ("", ["tests"], ["test_"]))
            check_eq(f"E-A13: extras {label}: both are [] and `extras_problem` names them",
                     (table["stem_camel_suffixes"], table["code_extensions"],
                      "stem_camel_suffixes" in table["extras_problem"], "code_extensions" in table["extras_problem"]),
                     ([], [], True, True))
            check_eq(f"E-A13: extras {label}: a usual name is still read and the camel one is not",
                     (TL.name_marker("test_a.py", table) != "", TL.name_marker("FooTests.cs", table) != ""), (True, False))
        (fake / "test-path-markers.json").write_text(json.dumps(
            dict(base, stem_camel_suffixes=["Tests"], code_extensions=["PY", ".Cs"])), encoding="utf-8")
        check_eq("the extensions are lower-cased and carry their dot (a camel ending keeps its case)",
                 (TL.markers()[0]["code_extensions"], TL.markers()[0]["stem_camel_suffixes"], TL.markers()[0]["extras_problem"]),
                 ([".py", ".cs"], ["Tests"], ""))
        (fake / "test-path-markers.json").write_text(json.dumps(dict(base, dir_names="tests", stem_camel_suffixes=["Tests"])),
                                                     encoding="utf-8")
        check_eq("E-A13: a malformed FOUR-list file is still the one `problem` (unchanged), and no table",
                 (TL.markers()[0], "dir_names" in TL.markers()[1]), ({}, True))
    finally:
        hooklib.ref = real_ref
        cleanup(fake)


def reference_shaped(prefix: str) -> tuple:
    """The shape the 19 reference configs have: the project sits beside the application checkouts, app_root points
    up to them, and `run.levels` already names test folders INSIDE the protected roots (project-root-relative,
    with `..`)."""
    base = temp_dir(prefix).resolve()
    for folder in ("testproject1/tests", "testproject1/src/app", "testproject1-ui/src/a", "testproject1-ui/e2e", "th/qa-factory"):
        (base / folder).mkdir(parents=True)
    cfg = {"schema_version": 1, "app_root": "..", "tests_root": ".", "protected_app_paths": ["testproject1", "testproject1-ui"],
           "run": {"levels": {"unit": ["../testproject1/tests/**", "../testproject1-ui/src/**/*.test.*"]}},
           "profiles": [{"profile_id": "web", "roots": {"test": "../testproject1-ui/e2e"}}]}
    (base / "th" / "qa-factory" / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
    return base, base / "th", cfg


def part_recognition() -> None:
    """E22-E24: the other carriers of where tests live are recognised, never a permission."""
    base, th, cfg = reference_shaped("qa-tl-ref-")
    try:
        found = verdict(base / "testproject1" / "tests" / "x.py", cfg, th)
        check_eq("E22: a run.levels pattern INSIDE a protected root recognises the place, and says which carrier",
                 (found["test"], found["by"], found["source"], found["kind"], found["where"]),
                 (True, "config", "run.levels", "folder", "run.levels:unit ../testproject1/tests/**"))
        found = verdict(base / "testproject1-ui" / "src" / "a" / "b.test.ts", cfg, th)
        check_eq("E24: `..` patterns are matched by their absolute form, with `*` crossing folders (level_for)",
                 (found["test"], found["source"], found["kind"]), (True, "run.levels", "file"))
        check_eq("E24: the second `level_for` form: `<pattern>/*` for a literal folder",
                 verdict(base / "testproject1" / "tests" / "deep" / "y.py", dict(cfg, run={"levels": {"api": ["../testproject1/tests"]}}),
                         th)["source"], "run.levels")
        check_eq("and the wildcard remainder must match: `src/a.test.ts` has no folder between (as level_for): "
                 "this carrier does not recognise it (the usual name does)",
                 (verdict(base / "testproject1-ui" / "src" / "a.test.ts", cfg, th)["source"]), "markers")
        check_eq("application code beside it is not recognised", verdict(base / "testproject1" / "src" / "app" / "x.py", cfg, th)["test"],
                 False)
        found = verdict(base / "testproject1-ui" / "e2e" / "login.ts", cfg, th)
        check_eq("roots.test is a literal folder prefix",
                 (found["test"], found["source"], found["kind"], found["where"]),
                 (True, "roots.test", "folder", "profiles[web].roots.test"))
        found = verdict(base / "testproject1-ui" / "e2e" / "login.ts", dict(cfg, run={}, profiles=[],
                                                                       tests_root="../testproject1-ui/e2e"), th)
        check_eq("tests_root is a literal folder prefix too", (found["test"], found["source"], found["where"]),
                 (True, "tests_root", "tests_root"))
        check_eq("case does not matter: both sides are lower-cased (Windows and Linux agree)",
                 verdict(str(base / "testproject1" / "tests" / "x.py").upper(), cfg, th)["source"], "run.levels")
        # E24: values that name the whole project or application are ignored
        for label, c in (("tests_root '.'", dict(cfg, run={}, profiles=[], tests_root=".")),
                         ("tests_root ''", dict(cfg, run={}, profiles=[], tests_root="")),
                         ("tests_root '..' (the application root)", dict(cfg, run={}, profiles=[], tests_root="..")),
                         ("roots.test '.'", dict(cfg, run={}, profiles=[{"roots": {"test": "."}}])),
                         ("roots.test '../..' (above both)", dict(cfg, run={}, profiles=[{"roots": {"test": "../.."}}])),
                         ("run.levels '**'", dict(cfg, run={"levels": {"unit": ["**"]}}, profiles=[])),
                         ("run.levels '../**'", dict(cfg, run={"levels": {"unit": ["../**"]}}, profiles=[])),
                         ("run.levels '../*.*'", dict(cfg, run={"levels": {"unit": ["../*.*"]}}, profiles=[])),
                         ("run.levels ''", dict(cfg, run={"levels": {"unit": [""]}}, profiles=[]))):
            check_eq(f"E24/S12: {label} never makes everything a test",
                     (verdict(base / "testproject1-ui" / "src" / "a" / "x.ts", c, th)["test"],
                      verdict(base / "testproject1" / "src" / "app" / "x.py", c, th)["test"]), (False, False))
        # S13: a carrier that covers a whole protected root does not make that root's code a test
        for label, c in (("run.levels covering testproject1", dict(cfg, run={"levels": {"unit": ["../testproject1/**"]}}, profiles=[])),
                         ("run.levels naming the folder alone", dict(cfg, run={"levels": {"unit": ["../testproject1/"]}}, profiles=[])),
                         ("roots.test = the protected root", dict(cfg, run={}, profiles=[{"roots": {"test": "../testproject1"}}])),
                         ("tests_root = the protected root", dict(cfg, run={}, profiles=[], tests_root="../testproject1"))):
            check_eq(f"S13: {label}: application code in that root is not recognised",
                     verdict(base / "testproject1" / "src" / "app" / "x.py", c, th)["test"], False)
        # step 3 counts only test_locations; a recognition carrier is not "the project's word" for the markers
        found = verdict(base / "testproject1" / "src" / "app" / "test_x.py", dict(cfg, run={}, profiles=[]), th)
        check_eq("K3/E22: with a carrier but no test_locations, a usual name inside application code is markers",
                 (found["by"], found["source"]), ("markers", "markers"))
        # E23: test_locations is checked first: a permission is never hidden by a recognition carrier
        both = dict(cfg, test_locations=["testproject1/tests/"])
        found = verdict(base / "testproject1" / "tests" / "x.py", both, th)
        check_eq("E23: a place named by both is reported as test_locations", (found["source"], found["where"]),
                 ("test_locations", "testproject1/tests/"))
        # a pattern that resolves OUTSIDE app_root still matches by its absolute form
        far = dict(cfg, app_root=".", protected_app_paths=[])
        found = verdict(base / "testproject1" / "tests" / "y.py", far, th)
        check_eq("E24: with app_root = the project, a pattern that leaves it (`..`) still matches by its project-root "
                 "form: the place is outside both app_root and the project root and is recognised all the same",
                 (found["test"], found["source"]), (True, "run.levels"))
    finally:
        cleanup(base)


# --- (b) the guard ----------------------------------------------------------------------------------------

def guarded(event: dict) -> tuple:
    """(exit code or None, what the guard said) for one call: the guard is a function here, so its stderr is seen
    as a hook's would be. What it said is its stderr plus the notes of the `hook_signal` rows it wrote during the call
    (RH1-5: a warning goes to the person's journal, not to stderr at exit 0)."""
    import guard_app_under_test
    from hooklib import load_config
    before = len(journal_signals(Path(event["cwd"])))
    err = io.StringIO()
    code = None
    try:
        with redirect_stderr(err):
            guard_app_under_test.check(event, load_config(event))
    except SystemExit as exc:
        code = exc.code
    return code, "\n".join([err.getvalue()] + [str(r.get("notes") or "") for r in journal_signals(Path(event["cwd"]))[before:]])


def journal_signals(root: Path) -> list:
    """The `hook_signal` rows of THIS project's journal, in order."""
    from hooklib import read_json
    import runtime_paths as RP
    path = RP.configured(root, read_json(root / "qa-factory" / "config.json", {}, kind=dict).get("journal_path"), "journal.jsonl")
    lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
    return [r for r in (json.loads(x) for x in lines if x.strip()) if r.get("event") == "hook_signal"]


def call(tool: str, root: Path, rel, role="qa-automator", ticket=TICKET, **tool_input) -> dict:
    key = "notebook_path" if tool == "NotebookEdit" else "file_path"
    target = rel if isinstance(rel, Path) else root / rel
    event = {"tool_name": tool, "cwd": str(root), "tool_input": dict({key: str(target)}, **tool_input)}
    if tool == "Write":
        event["tool_input"].setdefault("content", "def test_new():\n    assert True\n")
    if role:
        event["agent_type"] = role
    if ticket:
        event["task_id"] = ticket
    return event


def shell(root: Path, command: str, role="qa-automator", tool="Bash", ticket=TICKET) -> dict:
    event = {"tool_name": tool, "cwd": str(root), "tool_input": {"command": command}}
    if role:
        event["agent_type"] = role
    if ticket:
        event["task_id"] = ticket
    return event


ROLES = (("qa-automator", "the automator"), ("qa-code-critic", "the critic"), ("", "the orchestrator"),
         ("qa-scout", "another role"))


def part_guard_write() -> None:
    root = project("qa-tl-guard-", locations=["src/__checks__/", "src/legacy/checks"])
    try:
        use_project(root)
        # K5: any role, any of the three tools, silently
        for role, label in ROLES:
            code, said = guarded(call("Write", root, "src/__checks__/new_one.py", role=role))
            check_eq(f"K5: {label} writes a test into a test location", code, None)
            check_eq(f"K5: {label}: and the pass is silent", said, "")
        for tool, extra, rel in (("Edit", {"old_string": "x = 1", "new_string": "x = 2"}, "src/__checks__/a.py"),
                                 ("NotebookEdit", {"new_source": "x"}, "src/__checks__/n.ipynb")):
            for role, label in ROLES:
                code, said = guarded(call(tool, root, rel, role=role, **extra))
                check_eq(f"K5: {label}: {tool} into a test location passes, silently", (code, said), (None, ""))
        code, said = guarded(call("Write", root, "src/legacy/checks/deep/er/new.py", role=""))
        check_eq("K5: a slashless folder entry covers what is below it", code, None)
        code, said = guarded(call("Write", root, "src/__checks__/a.py", role="", ticket="", content="x = 'new'\n"))
        check_eq("K5: no story needed: a pass is not read from a story", code, None)
        # delete and move inside a test location pass too (a test location is not application code)
        code, said = guarded(call("Edit", root, "src/__checks__/a.py", patch_operation="delete"))
        check_eq("K5: a delete inside a test location passes (the carve-out says it is not application code)", code, None)
        code, said = guarded(call("Edit", root, "src/__checks__/a.py", patch_operation="update", patch_move=True))
        check_eq("K5: and so does a move inside it", code, None)
        # the boundary sibling and application code stay blocked; the automator is told the permanent door
        for rel in ("src/__checks__x/a.py", "src/app/x.py", "src/legacy/checksum/c.py"):
            code, said = guarded(call("Write", root, rel))
            check_eq(f"K5: the boundary sibling stays blocked: {rel}", code, 2)
            check_in(f"K5: {rel}: the base text", BOUNDARY, said)
            check_in(f"K5: {rel}: the automator gets the permanent door, verbatim (R4)", PERMANENT, said)
            check_in(f"K5: {rel}: and the per-story door, unchanged", "waiver.py --task <TICKET> --stage S5 --block "
                     '"protected test path: <folder/ or pattern>" --words-file <file>', said)
        for role, label in ROLES[1:]:
            code, said = guarded(call("Write", root, "src/app/x.py", role=role))
            check_eq(f"K5: {label} is blocked in application code", code, 2)
            check_not_in(f"K5: {label} is not shown the automator's door", PERMANENT, said)
        # E8: a symlink or junction inside a test location that leads into application code
        link = root / "src" / "__checks__" / "link.py"
        try:
            os.symlink(root / "src" / "app" / "x.py", link)
        except (OSError, NotImplementedError, AttributeError):
            junction = root / "src" / "__checks__" / "jlink"
            made = os.name == "nt" and subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(junction), str(root / "src" / "app")], capture_output=True).returncode == 0
            if made:
                for role, label in ROLES:
                    code, said = guarded(call("Write", root, "src/__checks__/jlink/x.py", role=role))
                    check_eq(f"K6/E8: a junction in a test location cannot lead into application code ({label})", code, 2)
                subprocess.run(["cmd", "/c", "rmdir", str(junction)], capture_output=True)
            else:
                print("SKIPPED: no symlink and no junction can be made here (the `..` case proves the resolved target)")
        else:
            code, said = guarded(call("Write", root, "src/__checks__/link.py", role=""))
            check_eq("K6/E8: a symlink in a test location cannot lead into application code", code, 2)
        # E10: `..` out of the location
        code, said = guarded(call("Write", root, "src/__checks__/../app/x.py", role=""))
        check_eq("K6/E10: a `..` out of a test location is judged on the resolved target", code, 2)
        code, said = guarded(call("Write", root, "src/__checks__/../app/x.py"))
        check_in("K6/E10: and the automator is told the permanent door", PERMANENT, said)
        # E11: a stream of an application file
        code, said = guarded(call("Write", root, "src/app/x.py:y.spec.ts", role=""))
        check_eq("K6/E11: an alternate data stream is not a test-location write", code, 2)
        # outside every protected path is not this guard's business
        code, said = guarded(call("Write", root, "tests/test_ok.py"))
        check_eq("a write outside protected_app_paths passes untouched", (code, said), (None, ""))
    finally:
        cleanup(root)


def part_guard_links() -> None:
    root = project("qa-tl-links-", locations=["src/__checks__/"])
    try:
        use_project(root)
        app_file = root / "src" / "app" / "x.py"
        link = root / "src" / "__checks__" / "linked.py"
        try:
            os.link(app_file, link)
        except (OSError, NotImplementedError, AttributeError) as exc:
            print(f"SKIPPED: this OS refused to make a hard link ({exc}); the hard-link cases did not run")
        else:
            check_eq("control: one file with two names", os.stat(app_file).st_nlink, 2)
            for role, label in ROLES:
                for tool, extra in (("Write", {"content": "x = 'changed'\n"}),
                                    ("Edit", {"old_string": "x = 1", "new_string": "x = 2"})):
                    code, said = guarded(call(tool, root, "src/__checks__/linked.py", role=role, **extra))
                    check_eq(f"K6/E9: {label}: a {tool} through a hard link in a test location is refused", code, 2)
                    check_in(f"K6/E9: {label}: and says why, verbatim", HARDLINK, said)
            check_eq("nothing wrote the application file", app_file.read_text(encoding="utf-8"), "x = 1\n")
            code, said = guarded(shell(root, f"rm {link}", role=""))
            check_eq("K6/E9: a shell command on the hard link is refused too", code, 2)
            check_in("K6/E9: with the same sentence", HARDLINK, said)
            os.unlink(link)
            code, said = guarded(call("Write", root, "src/__checks__/linked.py", role=""))
            check_eq("after the link is gone the name is an ordinary new file", code, None)
        # E9: a stat that fails is a refusal, never a pass
        real_stat = os.stat

        def faulty(path, *args, **kwargs):
            if str(path).replace("\\", "/").endswith("src/__checks__/a.py"):
                raise PermissionError(13, "Permission denied")
            return real_stat(path, *args, **kwargs)
        os.stat = faulty
        try:
            code, said = guarded(call("Write", root, "src/__checks__/a.py", role="", content="x = 3\n"))
        finally:
            os.stat = real_stat
        check_eq("K6/E9: a stat error on a target in a test location is a refusal", code, 2)
        check_in("K6/E9: and says the guard could not read the entry, verbatim", STAT_ERROR, said)
        check_not_in("K6/E9: and does not claim a hard link it cannot see", HARDLINK, said)
    finally:
        cleanup(root)


def part_guard_shell() -> None:
    root = project("qa-tl-shell-", locations=["src/__checks__/"])
    try:
        use_project(root)
        loc = root / "src" / "__checks__"
        for tool in ("Bash", "PowerShell"):
            for role, label in ROLES:
                code, said = guarded(shell(root, f"echo x > {loc / 'new.py'}", role=role, tool=tool))
                check_eq(f"K6: {label}/{tool}: a shell write to a FILE named in a test location passes", (code, said), (None, ""))
        code, said = guarded(shell(root, f"rm {loc / 'a.py'}", role=""))
        check_eq("K6: `rm` of a named test file passes", code, None)
        code, said = guarded(shell(root, "rm src/__checks__/a.py", role=""))
        check_eq("K6: a relative name is read from the project root", code, None)
        code, said = guarded(shell(root, f"cp x.py {loc / 'copy.py'}", role=""))
        check_eq("K6: `cp` into a test location passes (the destination is the target)", code, None)
        code, said = guarded(shell(root, f"mv {loc / 'a.py'} {loc / 'b.py'}", role=""))
        check_eq("K6: `mv` inside a test location passes", code, None)
        # an existing directory stays blocked, with the sentence
        for role, label in ROLES:
            code, said = guarded(shell(root, f"rm -rf {loc}", role=role))
            check_eq(f"K6/E15: {label}: a directory target in a test location stays blocked", code, 2)
            check_in(f"K6/E15: {label}: with the R3 sentence, verbatim", SHELL, said)
        code, said = guarded(shell(root, f"rm -rf {loc}/", role=""))
        check_eq("K6/E15: the same with a trailing slash", (code, SHELL in said), (2, True))
        # E25: a name the shell expands is a path the guard cannot see
        for label, command in (
                ("a glob", "rm -rf src/__checks__/*"),
                ("a glob, PowerShell form", "Remove-Item -Recurse src/__checks__/*"),
                ("`?`", "rm src/__checks__/a?.py"),
                ("`[`", "rm src/__checks__/[ab].py"),
                ("braces that leave the folder", "rm src/__checks__/{a,../../app/x}.py"),
                ("a variable", "rm src/__checks__/$NAME"),
                ("a PowerShell variable", "Remove-Item src/__checks__/$name"),
                ("a backtick", "rm src/__checks__/`echo a`.py"),
                ("a cmd variable", "del src/__checks__/%NAME%.py"),
                ("a tilde", "rm src/__checks__/~old.py")):
            for role in ("", "qa-automator"):
                code, said = guarded(shell(root, command, role=role))
                check_eq(f"K6/E25: {label} ({role or 'orchestrator'}) stays blocked", code, 2)
                check_in(f"K6/E25: {label}: with the R3 sentence", SHELL, said)
        code, said = guarded(shell(root, f"echo x > {root / 'src' / 'app' / 'x.py'}", role=""))
        check_eq("a shell write into application code is blocked as before", code, 2)
        check_not_in("and carries no test-location sentence", SHELL, said)
        # `mv` INTO application code
        code, said = guarded(shell(root, f"mv {loc / 'a.py'} {root / 'src' / 'app' / 'moved.py'}", role=""))
        check_eq("K6: `mv` out of a test location into application code is blocked", code, 2)
        check_in("K6: and names the target that is application code", "src/app/moved.py", said.replace("\\", "/"))
        code, said = guarded(shell(root, f"cp {loc / 'a.py'} {root / 'src' / 'app' / 'copied.py'}", role=""))
        check_eq("K6: `cp` into application code is blocked", code, 2)
    finally:
        cleanup(root)


def part_guard_reference_shape() -> None:
    """K6 (new): the reference-shaped config. `run.levels` names `testproject1/tests/**` INSIDE a protected root; it is
    a recognition carrier, never a permission, so a write there is blocked for every role."""
    base, th, cfg = reference_shaped("qa-tl-refguard-")
    try:
        use_project(th)
        check_eq("the verdict for that place says run.levels (recognised) - and that is all it is",
                 verdict(base / "testproject1" / "tests" / "x.py", cfg, th)["source"], "run.levels")
        for role, label in ROLES:
            for rel in ("testproject1/tests/x.py", "testproject1-ui/e2e/login.ts", "testproject1-ui/src/a/b.test.ts"):
                code, said = guarded(call("Write", th, base / rel, role=role))
                check_eq(f"K6/E22: {label}: a write to {rel} (recognised by a carrier) is blocked", code, 2)
        code, said = guarded(shell(th, f"rm {base / 'testproject1' / 'tests' / 'x.py'}", role=""))
        check_eq("K6/E22: and a shell command on it", code, 2)
        # the person's word then opens exactly the place named
        cfg["test_locations"] = ["testproject1/tests/"]
        (th / "qa-factory" / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
        for role, label in ROLES:
            code, said = guarded(call("Write", th, base / "testproject1" / "tests" / "x.py", role=role))
            check_eq(f"once the person names it in test_locations, {label} writes there", code, None)
        code, said = guarded(call("Write", th, base / "testproject1-ui" / "e2e" / "login.ts", role=""))
        check_eq("and the other recognised carrier place stays closed", code, 2)
        code, said = guarded(call("Write", th, base / "testproject1" / "src" / "app" / "x.py", role=""))
        check_eq("and application code stays closed", code, 2)
    finally:
        cleanup(base)


def part_position() -> None:
    """K7: the carve-out never uses up a person's one-time apply grant, and `[]` / an absent key behaves exactly
    as before."""
    import stand_gaps
    root = project("qa-tl-pos-", locations=["src/__checks__/"])
    real = stand_gaps.apply_grant
    calls = []

    def spy(*a, **k):
        calls.append(1)
        return {}
    try:
        use_project(root)
        stand_gaps.apply_grant = spy
        code, said = guarded(call("Write", root, "src/__checks__/new.py", role=""))
        check_eq("K7/E14: an orchestrator write into a test location passes", code, None)
        check_eq("K7/E14: without ever asking for a stand-gap apply grant", calls, [])
        code, said = guarded(call("Write", root, "src/app/x.py", role=""))
        check_eq("control: the same spy sees an ordinary application write", (code, calls), (2, [1]))
    finally:
        stand_gaps.apply_grant = real
        cleanup(root)
    # `[]` and an absent key: exactly today's behaviour, byte for byte, on one existing scenario
    grant = {"stage": "S5", "match": "protected test path: src/tests/", "decision": "yes", "at": "2026-10-03T10:00:00+00:00",
             "by": "human"}
    results = {}
    for label, locations in (("absent", "absent"), ("empty list", [])):
        root = project("qa-tl-same-", locations=locations)
        try:
            (root / "src" / "tests").mkdir()
            task = root / "qa-factory" / "artifacts" / TICKET
            (task / "state" / "words").mkdir(parents=True)
            (task / "pipeline.json").write_text(json.dumps({"ticket": TICKET, "stages": {"S5": {"status": "running"}},
                                                            "stage_overrides": [grant]}), encoding="utf-8")
            use_project(root)
            out = []
            for rel, role in (("src/tests/test_new.py", "qa-automator"), ("src/tests/test_new.py", "qa-code-critic"),
                              ("src/app/x.py", "qa-automator"), ("src/__checks__/a.py", ""), ("tests/t.py", "")):
                code, said = guarded(call("Write", root, rel, role=role))
                out.append((rel, role, code, said.replace(str(root), "<root>")))
            out.append(("shell",) + tuple(guarded(shell(root, f"echo x > {root / 'src' / 'tests' / 't.py'}", role="")))[:1])
            results[label] = out
        finally:
            cleanup(root)
    check_eq("K7/E2: `[]` gives exactly the behaviour of an absent key", results["empty list"], results["absent"])
    absent = results["absent"]
    check_eq("K7/E2: and that behaviour is today's: the grant opens its story, nothing else (control)",
             [(r[0], r[1], r[2]) for r in absent[:5]],
             [("src/tests/test_new.py", "qa-automator", None), ("src/tests/test_new.py", "qa-code-critic", 2),
              ("src/app/x.py", "qa-automator", 2), ("src/__checks__/a.py", "", 2), ("tests/t.py", "", None)])
    check_in("K7: and the automator's refusal now carries the permanent door", PERMANENT, absent[2][3])


def part_warnings() -> None:
    root = project("qa-tl-warn-", locations=["/abs/tests/", "src/", 5, "src/__checks__/"])
    sid = "tl-" + uuid.uuid4().hex
    try:
        use_project(root)
        cfg = json.loads((root / "qa-factory" / "config.json").read_text(encoding="utf-8"))
        problems = TL.location_problems(cfg, root)
        check_eq("K8: three entries open nothing", len(problems), 3)
        check_in("K8: the absolute one is named with its place in the list", "test_locations[0] '/abs/tests/' is an absolute path",
                 problems)
        check_in("K8: the whole-root one carries the Amendment 5 text", "test_locations names all of 'src' ('src/'), which "
                 "is also application code in protected_app_paths; the orchestrator asks the person which part of 'src' "
                 "holds the application code and records the answer with their words (project_decisions.py).", problems)
        check_in("K8: the non-text one", "test_locations[2] is not a non-empty text", problems)
        # Amendment 6: the guard asks with the project root of THIS event (a hook's own cwd is not the project's)
        seen = []
        real_problems = TL.location_problems

        def spy(cfg_arg, root_arg=None):
            seen.append(root_arg)
            return real_problems(cfg_arg, root_arg)
        TL.location_problems = spy
        try:
            guarded(call("Write", root, "tests/test_ok.py", role=""))
        finally:
            TL.location_problems = real_problems
        check_eq("Amendment 6: the guard passes the event's project root to location_problems", [str(r) for r in seen],
                 [str(root)])
        event = call("Write", root, "tests/test_ok.py", role="")
        code, said = guarded(event)
        expected = ("APP-UNDER-TEST BOUNDARY, WARNING: test_locations in qa-factory/config.json - "
                    + "; ".join(problems) + ". Those entries open nothing; the other entries are used. "
                    "(Recorded once per session.)")
        check_eq("K8: the warning text, verbatim (a write outside the protected paths still says it)", (code, said.strip()),
                 (None, expected))
        check_eq("K8: ...recorded as a journal signal of kind config (the pin moved from stderr to the journal)",
                 [r.get("kind") for r in journal_signals(root)[-1:]], ["config"])
        # once per session: with a session id the second call is silent (Q4: the pin on the NEW once-flag,
        # `hooklib.person_signal` keys it `sid|signal|<kind>|<once_key>`)
        before = len(journal_signals(root))
        event = dict(call("Write", root, "tests/test_ok.py", role=""), session_id=sid)
        first = guarded(event)[1]
        second = guarded(event)[1]
        key = "signal|config|test-locations:" + "; ".join(sorted(problems))
        flag = Path(tempfile.gettempdir()) / ("qa-factory-warn-" + hashlib.sha1(f"{sid}|{key}".encode("utf-8")).hexdigest()[:16])
        try:
            check_eq("K8: once per session: the first call records it, the second does not",
                     (expected in first, second), (True, ""))
            check_eq("K8: ...one journal row for the two calls", len(journal_signals(root)) - before, 1)
            check_eq("K8: ...and the once-flag file exists under the new key", flag.exists(), True)
        finally:
            flag.unlink(missing_ok=True)
        # nothing to say: no warning at all
        for label, locations in (("absent", "absent"), ("empty", []), ("good", ["src/__checks__/"])):
            write_config(root, ("src",), locations)
            check_eq(f"K8: {label}: no warning", guarded(call("Write", root, "tests/test_ok.py", role=""))[1], "")
        # Amendment 5 in the block: protection wins per target
        write_config(root, ("src",), ["src/"])
        for role, label in (("qa-automator", "the automator"), ("", "the orchestrator"), ("qa-code-critic", "the critic")):
            code, said = guarded(call("Write", root, "src/app/x.py", role=role))
            check_eq(f"K15: {label}: an entry that covers the whole root opens nothing in it", code, 2)
            check_in(f"K15: {label}: the block says which part must be asked about, verbatim", whole_root("src"), said)
        code, said = guarded(call("Write", root, "src/app/x.py"))
        check_not_in("K15: the automator is NOT sent to the permanent door that is already taken", PERMANENT, said)
        check_in("K15: but keeps the per-story door", 'waiver.py --task <TICKET> --stage S5 --block "protected test path:', said)
        code, said = guarded(shell(root, f"rm {root / 'src' / 'app' / 'x.py'}", role=""))
        check_in("K15: a shell target in the covered root gets the same sentence", whole_root("src"), said)
        write_config(root, ("src",), ["src/__checks__/"])
        code, said = guarded(call("Write", root, "src/app/x.py"))
        check_in("control: without the conflict the automator does get the permanent door", PERMANENT, said)
        check_not_in("control: and no conflict sentence", "names all of", said)
    finally:
        cleanup(root)


def part_real_hook() -> None:
    """The same thing through the real hook process (`guard_pre_tool.py`), as the legacy port of the per-story permission
    runs it: a process of its own, the project named by CLAUDE_PROJECT_DIR, the event on stdin."""
    root = project("qa-tl-hook-", locations=["/abs/x/", "src/__checks__/"])
    try:
        env = dict(os.environ, CLAUDE_PROJECT_DIR=str(root), PYTHONDONTWRITEBYTECODE="1")

        def hook(rel: str, role: str = ""):
            event = {"tool_name": "Write", "cwd": str(root), "session_id": "tl-hook-" + uuid.uuid4().hex,
                     "tool_input": {"file_path": str(root / rel), "content": "def test_x():\n    pass\n"}}
            if role:
                event["agent_type"] = role
            return subprocess.run([sys.executable, "-B", str(SCRIPTS / "guard_pre_tool.py")], input=json.dumps(event),
                                  text=True, capture_output=True, encoding="utf-8", env=env, cwd=str(root), timeout=120)
        done = hook("src/__checks__/new.py")
        check_eq("hook: the orchestrator's write into a test location passes (exit 0)", done.returncode, 0)
        check_in("hook: and the entry that opens nothing is named in the person's journal (a signal, not stderr at exit 0)",
                 "test_locations[0] '/abs/x/' is an absolute path", [str(r.get("notes")) for r in journal_signals(root)])
        check_not_in("hook: ...and not on stderr", "is an absolute path", done.stderr)
        done = hook("src/__checks__/new.py", role="qa-code-critic")
        check_eq("hook: and so is the critic's", done.returncode, 0)
        done = hook("src/app/x.py", role="qa-automator")
        check_eq("hook: application code stays closed (exit 2)", done.returncode, 2)
        check_in("hook: and the automator is told the permanent door, verbatim", PERMANENT, done.stderr)
    finally:
        cleanup(root)


# --- (c) suggest, check and the cap ---------------------------------------------------------------------

def tree(prefix: str, files: list, protected=("src",), locations="absent", extra=None) -> Path:
    root = temp_dir(prefix).resolve()
    (root / "qa-factory").mkdir()
    for rel in files:
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x\n", encoding="utf-8")
    write_config(root, protected, locations, extra)
    return root


def cli(root: Path, *args):
    return run_script("test_locations.py", "--root", root, *args, cwd=root)


def part_suggest() -> None:
    files = ["src/app/x.py", "src/app/__tests__/a.ts", "src/app/__tests__/b.ts", "src/feature/__tests__/c.ts",
             "src/app/foo.spec.ts", "src/pkg/test_y.py", "src/app/node_modules/dep/test_dep.py", "src/app/skip.test.js"]
    root = tree("qa-tl-suggest-", files)
    try:
        found = TL.suggest(json.loads((root / "qa-factory" / "config.json").read_text(encoding="utf-8")), root)
        check_eq("K11: the keys of the answer", sorted(found), ["candidates", "truncated", "unreadable", "walked"])
        check_eq("K11: node_modules is skipped (skip_dirs is data), everything else is walked", found["walked"], 7)
        check_eq("K11: not truncated", found["truncated"], False)
        check_eq("K11: a marker folder seen twice becomes `<root>/**/<name>/`; a marker file name is grouped by "
                 "its marker and extension; sorted by files, then by pattern",
                 [(c["pattern"], c["kind"], c["files"], c["marker"]) for c in found["candidates"]],
                 [("src/**/__tests__/", "folder", 3, "dir_names:__tests__"),
                  ("src/**/*.spec.ts", "file", 1, "stem_suffixes:.spec"),
                  ("src/**/*.test.js", "file", 1, "stem_suffixes:.test"),
                  ("src/**/test_*.py", "file", 1, "stem_prefixes:test_")])
        once = TL.suggest({"app_root": ".", "protected_app_paths": ["src"]}, tree_without(root, "src/feature"))
        check_eq("K11: a marker folder seen ONCE is proposed as its literal path",
                 [c["pattern"] for c in once["candidates"]][:1], ["src/app/__tests__/"])
        # the CLI (onboarding runs before any config: --app-root and --protected override it)
        bare = temp_dir("qa-tl-bare-").resolve()
        try:
            for rel in ("code/src/__tests__/a.ts", "code/src/b.ts"):
                (bare / rel).parent.mkdir(parents=True, exist_ok=True)
                (bare / rel).write_text("x\n", encoding="utf-8")
            done = cli(bare, "--app-root", ".", "--protected", "code/src", "--suggest", "--json")
            check_eq("K11: --suggest --json on a project with no config (exit 0)", done.returncode, 0)
            data = json.loads(done.stdout)
            check_eq("K11: FR-14: stdout is the JSON and nothing else", [c["pattern"] for c in data["candidates"]],
                     ["code/src/__tests__/"])
            plain = cli(bare, "--app-root", ".", "--protected", "code/src", "--suggest")
            check_in("K11: the human form says what it found, with its count", "code/src/__tests__/  (folder, 1 files, "
                     "marker dir_names:__tests__)", plain.stdout)
            gone = cli(bare, "--app-root", ".", "--protected", "nope", "--suggest", "--json")
            check_eq("K11: a protected path that is not on disk is reported, not a crash (FR-47)",
                     (gone.returncode, json.loads(gone.stdout)["candidates"], "nope" in " ".join(json.loads(gone.stdout)["unreadable"])),
                     (0, [], True))
            check_eq("`--suggest` and `--check` together or neither is refused", cli(bare, "--json").returncode, 2)
            check_eq("`--candidate` goes with `--check`", cli(bare, "--suggest", "--candidate", "x/").returncode, 2)
        finally:
            cleanup(bare)
        # a broken list of usual names: nothing is proposed and the answer says why
        import hooklib
        real_ref = hooklib.ref
        empty = Path(tempfile.mkdtemp(prefix="qa-tl-sug-nomarkers-"))
        try:
            hooklib.ref = lambda rel: empty / rel
            found = TL.suggest({"app_root": ".", "protected_app_paths": ["src"]}, root)
            check_eq("E16: markers unreadable: no candidate, and `unreadable` names the file",
                     (found["candidates"], "test-path-markers.json" in " ".join(found["unreadable"])), ([], True))
        finally:
            hooklib.ref = real_ref
            cleanup(empty)
    finally:
        cleanup(root)


def part_before_the_config() -> None:
    """F2 (the temporal edge, FR-41): at onboarding p2/p3 config.json does not exist yet (p4 writes it). A count made
    with no protected root named is an unknown, not "0 files"; passing p1's overrides gives the real count."""
    bare = temp_dir("qa-tl-noconfig-").resolve()
    try:
        for rel in ("src/checks/a.py", "src/checks/b.py"):
            (bare / rel).parent.mkdir(parents=True, exist_ok=True)
            (bare / rel).write_text("x\n", encoding="utf-8")
        line = "no protected root was walked (no config yet: pass --app-root and --protected)"
        for flag in ("--check", "--suggest"):
            args = (flag, "--candidate", "src/checks/") if flag == "--check" else (flag,)
            data = json.loads(cli(bare, *args, "--json").stdout)
            check_in(f"F2: {flag} with no config and no overrides says nothing was walked", line, data["unreadable"])
            check_eq(f"F2: {flag}: and the count is not presented as a fact", data["walked"], 0)
        data = json.loads(cli(bare, "--app-root", ".", "--protected", "src", "--check", "--candidate", "src/checks/",
                              "--json").stdout)
        check_eq("F2: with p1's overrides the candidate is counted (2 files, 2 without a usual name) and nothing is unknown",
                 (data["entries"][-1]["files"], data["entries"][-1]["without_marker"], data["unreadable"]), (2, 2, []))
        data = json.loads(cli(bare, "--app-root", ".", "--protected", "nope", "--check", "--json").stdout)
        check_in("F2: a protected path that is not on disk still says nothing was walked", "no protected root was walked",
                 " ".join(data["unreadable"]))
    finally:
        cleanup(bare)


def tree_without(root: Path, rel: str) -> Path:
    import shutil
    shutil.rmtree(root / rel)
    return root


def part_cap() -> None:
    """E19 / K11: exactly N files walked is complete; N+1 is truncated and says "at least"."""
    root = tree("qa-tl-cap-", [f"src/app/f{i}.py" for i in range(5)] + [], locations=["src/app/"])
    try:
        cfg = json.loads((root / "qa-factory" / "config.json").read_text(encoding="utf-8"))
        at = TL.check(cfg, root, max_files=5)
        beyond = TL.check(cfg, root, max_files=4)
        check_eq("E19: at N: everything walked, not truncated", (at["walked"], at["truncated"]), (5, False))
        check_eq("E19: at N: the count is the total", (at["entries"][0]["files"],), (5,))
        check_eq("E19: at N-1 (one file more than the cap): truncated, a lower bound", (beyond["walked"], beyond["truncated"]), (4, True))
        check_eq("E19: and the count is the lower bound", beyond["entries"][0]["files"], 4)
        sug_at, sug_beyond = TL.suggest(cfg, root, 5), TL.suggest(cfg, root, 4)
        check_eq("E19: suggest has the same boundary", ((sug_at["walked"], sug_at["truncated"]),
                                                       (sug_beyond["walked"], sug_beyond["truncated"])),
                 ((5, False), (4, True)))
        done = cli(root, "--check", "--max-files", "4")
        check_in("E19/FR-41: the human form says `at least` when truncated", "at least 4 files", done.stdout)
        check_in("E19: and that every count is a lower bound", "every count above is a lower bound", done.stdout)
        done = cli(root, "--check", "--max-files", "5")
        check_not_in("E19: a complete walk does not say `at least`", "at least", done.stdout)
        check_in("E19: it says the total", "src/app/: 5 files, 5 without a usual test name", done.stdout)
        check_eq("E19: --json carries truncated", json.loads(cli(root, "--check", "--max-files", "4", "--json").stdout)["truncated"],
                 True)
        two = tree("qa-tl-cap2-", [f"a/f{i}.py" for i in range(3)] + [f"b/f{i}.py" for i in range(3)], protected=("a", "b"))
        try:
            c2 = json.loads((two / "qa-factory" / "config.json").read_text(encoding="utf-8"))
            check_eq("E19: the cap is for the whole walk, across protected roots",
                     (TL.check(c2, two, max_files=6)["truncated"], TL.check(c2, two, max_files=5)["truncated"]), (False, True))
        finally:
            cleanup(two)
    finally:
        cleanup(root)


def part_check() -> None:
    files = ["src/app/x.py", "src/app/__tests__/a.ts", "src/app/__tests__/b.ts", "src/app/foo.spec.ts", "src/legacy/checks/c.py"]
    root = tree("qa-tl-check-", files, locations=["src/app/", "src/legacy/checks", "src/", "/abs/", 7])
    try:
        cfg = json.loads((root / "qa-factory" / "config.json").read_text(encoding="utf-8"))
        found = TL.check(cfg, root)
        rows = {r["entry"]: r for r in found["entries"]}
        check_eq("K11: the keys of the answer", sorted(found), ["entries", "proposed_value", "truncated", "unreadable", "walked"])
        check_eq("K11: an entry's count and how many of them carry no usual test name",
                 (rows["src/app/"]["files"], rows["src/app/"]["without_marker"], rows["src/app/"]["live"], rows["src/app/"]["problem"]),
                 (4, 1, True, ""))
        check_eq("K11: a slashless folder entry", (rows["src/legacy/checks"]["files"], rows["src/legacy/checks"]["without_marker"]),
                 (1, 1))
        check_eq("K11/E12: a whole-root entry is counted and carries its sentence",
                 (rows["src/"]["files"], rows["src/"]["live"], rows["src/"]["problem"].startswith("test_locations names all of 'src'")),
                 (5, True, True))
        check_eq("K11/E4: a grammar problem is not live, has no files, and says why",
                 (rows["/abs/"]["live"], rows["/abs/"]["files"], "an absolute path" in rows["/abs/"]["problem"]),
                 (False, 0, True))
        check_eq("K11/E3: an item that is not a text is a row too", (rows["7"]["live"], rows["7"]["problem"] != ""), (False, True))
        # --candidate and proposed_value: the whole list to record, nothing dropped
        good = tree("qa-tl-prop-", files, locations=["src/legacy/checks", "src/app/__tests__/"])
        try:
            gc = json.loads((good / "qa-factory" / "config.json").read_text(encoding="utf-8"))
            found = TL.check(gc, good, candidates=["src/**/*.spec.ts"])
            check_eq("K11/E26: proposed_value is the current list plus the candidate, order kept",
                     found["proposed_value"], ["src/legacy/checks", "src/app/__tests__/", "src/**/*.spec.ts"])
            check_eq("K11: the candidate is counted as an entry of its own",
                     [(r["entry"], r["files"], r["without_marker"]) for r in found["entries"]][-1], ("src/**/*.spec.ts", 1, 0))
            check_eq("K11/E26: a candidate already in the list is not added twice and not counted twice",
                     (TL.check(gc, good, candidates=["src/legacy/checks"])["proposed_value"],
                      len(TL.check(gc, good, candidates=["src/legacy/checks"])["entries"])),
                     (["src/legacy/checks", "src/app/__tests__/"], 2))
            check_eq("K11/E26: two candidates, one repeated",
                     TL.check(gc, good, candidates=["a/", "a/", "b/"])["proposed_value"],
                     ["src/legacy/checks", "src/app/__tests__/", "a/", "b/"])
            check_eq("K11: with no candidate the proposed value is the current list",
                     TL.check(gc, good)["proposed_value"], ["src/legacy/checks", "src/app/__tests__/"])
            bad = TL.check(gc, good, candidates=["/abs/x/"])
            check_eq("K11/E26: a candidate with a grammar problem: proposed_value is null and the problem is named",
                     (bad["proposed_value"], bad["entries"][-1]["live"], "an absolute path" in bad["entries"][-1]["problem"]),
                     (None, False, True))
            check_eq("K11/E26: a current value that is not a list: null, and the answer says why",
                     (TL.check(dict(gc, test_locations="src/x/"), good, candidates=["a/"])["proposed_value"],
                      "not a list" in " ".join(TL.check(dict(gc, test_locations="src/x/"), good)["unreadable"])), (None, True))
            check_eq("K11/E2/E26: the key absent is the empty list: the candidate alone",
                     TL.check({k: v for k, v in gc.items() if k != "test_locations"}, good, candidates=["a/"])["proposed_value"],
                     ["a/"])
            whole = TL.check(gc, good, candidates=["src/", "src/**/*.spec.ts"])
            check_eq("F3/E26: a whole-root candidate has a `problem` row and is NOT in proposed_value (it is said "
                     "to the person, never recorded); a good candidate next to it is",
                     (whole["entries"][-2]["problem"].startswith("test_locations names all of 'src' ('src/')"),
                      whole["entries"][-1]["problem"], whole["proposed_value"]),
                     (True, "", ["src/legacy/checks", "src/app/__tests__/", "src/**/*.spec.ts"]))
            check_eq("F3: the shapes the detector now sees (a wildcard folder segment) are left out too",
                     TL.check(gc, good, candidates=["src/*/", "src/?*/", "src/*/**"])["proposed_value"],
                     ["src/legacy/checks", "src/app/__tests__/"])
            done = cli(good, "--check", "--candidate", "src/**/*.spec.ts", "--json")
            data = json.loads(done.stdout)
            check_eq("K11: through the CLI, --json is parseable and carries the value to record",
                     (done.returncode, data["proposed_value"]), (0, ["src/legacy/checks", "src/app/__tests__/", "src/**/*.spec.ts"]))
            plain = cli(good, "--check", "--candidate", "src/**/*.spec.ts")
            check_in("K11: the human form prints the value too", 'proposed value: ["src/legacy/checks", "src/app/__tests__/", '
                     '"src/**/*.spec.ts"]', plain.stdout)
            # unreadable markers: counts are unknown, not zero (FR-41)
            import hooklib
            real_ref = hooklib.ref
            empty = Path(tempfile.mkdtemp(prefix="qa-tl-check-nomarkers-"))
            try:
                hooklib.ref = lambda rel: empty / rel
                found = TL.check(gc, good)
                check_eq("FR-41: markers unreadable: `without_marker` is null, never 0",
                         [r["without_marker"] for r in found["entries"]], [None, None])
                check_in("and the answer says why", "test-path-markers.json", " ".join(found["unreadable"]))
            finally:
                hooklib.ref = real_ref
                cleanup(empty)
        finally:
            cleanup(good)
    finally:
        cleanup(root)


# --- (d) the permanent door, end to end ------------------------------------------------------------------

def part_door() -> None:
    """K14: the conductor's route in a temp project: check (counts + the value to record), the person's words in a
    file, `project_decisions.py add` and `resolve --words-file --field-values` - then the guard lets the place through."""
    root = project("qa-tl-door-")
    try:
        env = dict(os.environ, CLAUDE_PROJECT_DIR=str(root), PYTHONDONTWRITEBYTECODE="1")
        use_project(root)
        place = "src/__checks__/"
        code, said = guarded(call("Write", root, "src/__checks__/new.py"))
        check_eq("before: the automator is stopped there, and told the permanent door", (code, PERMANENT in said), (2, True))
        counted = json.loads(cli(root, "--check", "--candidate", place, "--json").stdout)
        row = [r for r in counted["entries"] if r["entry"] == place][0]
        check_eq("the conductor reads the counts from the check", (row["files"], row["without_marker"]), (1, 1))
        value = counted["proposed_value"]
        check_eq("and the value to record", value, [place])
        words = root / "qa-factory" / "artifacts" / TICKET / "state" / "words"
        words.mkdir(parents=True)
        words_file = words / "test-location-20261006-101500.txt"
        words_file.write_bytes(WORDS.encode("utf-8"))
        added = run_script("project_decisions.py", "--root", root, "add", "--field-ref", "/test_locations", "--essence",
                           f"test location {place}", "--asked", f"Is {place} where your project keeps its tests for every story, "
                           "or only for this story? There are 1 files there, 1 of them without a usual test name",
                           cwd=root, env=env)
        check_eq("K14: `project_decisions.py add --field-ref /test_locations` (exit 0)", added.returncode, 0)
        row_id = json.loads(added.stdout)["id"]
        done = run_script("project_decisions.py", "--root", root, "resolve", "--id", row_id, "--words-file", words_file,
                          "--resolution-ref", f"{TICKET} S5", "--field-values", json.dumps({"/test_locations": value}),
                          cwd=root, env=env)
        check_eq("K14: `resolve --words-file --field-values` (exit 0)", done.returncode, 0)
        cfg = json.loads((root / "qa-factory" / "config.json").read_text(encoding="utf-8"))
        check_eq("K14: config.json holds the list", cfg.get("test_locations"), [place])
        receipt = json.loads((root / "qa-factory" / "state" / "decision-transactions" / f"{row_id}.json").read_text(encoding="utf-8"))
        check_eq("K14: the receipt holds the person's words, as given, and the value", (receipt["decision"], receipt["status"],
                 receipt["field_values"]), (WORDS, "complete", {"/test_locations": [place]}))
        registry = (root / "qa-factory" / "factory-backlog.md").read_text(encoding="utf-8")
        line = [ln for ln in registry.splitlines() if f"| {row_id} " in ln][0]
        check_in("K14: the registry row is closed with the words", "closed", line)
        check_in("K14: and carries the person's words", "Yes: the legacy checks folder", line)
        check_in("K14: and the resolution reference", f"{TICKET} S5", line)
        code, said = guarded(call("Write", root, "src/__checks__/new.py"))
        check_eq("K14: after: the guard lets the automator write there (no story permission, no waiver)", (code, said), (None, ""))
        code, said = guarded(call("Write", root, "src/__checks__/new.py", role="", ticket=""))
        check_eq("K14: and the orchestrator too", code, None)
        code, said = guarded(call("Write", root, "src/app/x.py"))
        check_eq("K14: application code next to it stays closed", code, 2)
        again = json.loads(cli(root, "--check", "--candidate", place, "--json").stdout)
        check_eq("K14/E26: the next check proposes the same list: nothing duplicated, nothing dropped",
                 again["proposed_value"], [place])
        second = "src/legacy/checks/"
        added = run_script("project_decisions.py", "--root", root, "add", "--field-ref", "/test_locations", "--essence",
                           f"test location {second}", "--asked", "the question as put", cwd=root, env=env)
        row2 = json.loads(added.stdout)["id"]
        value2 = json.loads(cli(root, "--check", "--candidate", second, "--json").stdout)["proposed_value"]
        done = run_script("project_decisions.py", "--root", root, "resolve", "--id", row2, "--words-file", words_file,
                          "--resolution-ref", f"{TICKET} S5", "--field-values", json.dumps({"/test_locations": value2}),
                          cwd=root, env=env)
        check_eq("E26: a second place is recorded WITH the first (the copied value never drops one)",
                 (done.returncode, json.loads((root / "qa-factory" / "config.json").read_text(encoding="utf-8"))["test_locations"]),
                 (0, [place, second]))
    finally:
        cleanup(root)


def main() -> None:
    os.environ.pop("QA_FACTORY_TASK", None)  # a person's word for the story would name one: not here
    root = temp_dir("qa-tl-shape-").resolve()
    (root / "src").mkdir()
    try:
        part_shape(root)
    finally:
        cleanup(root)
    part_locations()
    part_inside_application_code()
    part_edges()
    part_camel()
    part_recognition()
    part_guard_write()
    part_guard_links()
    part_guard_shell()
    part_guard_reference_shape()
    part_position()
    part_warnings()
    part_real_hook()
    part_suggest()
    part_before_the_config()
    part_cap()
    part_check()
    part_door()
    finish("test_test_locations")


if __name__ == "__main__":
    main()
