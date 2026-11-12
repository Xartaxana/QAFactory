#!/usr/bin/env python3
"""repo_map.py against a small synthetic test tree: a conftest with fixtures, two utils
modules, two areas of tests and one case whose Given/When name the coupon area.

What is proved:
  * the nouns come from the case's Given/When (backticked names weigh more than prose);
  * the tests of the area are found by their path, with their test function names;
  * conftest fixtures come with their signatures and scope, the ones the cases name first;
  * the util named after the cases' nouns outranks the one that merely mentions them;
  * the example is the head of the area's first test file, at most 60 lines;
  * `--area` overrides the frontmatter; `--json` writes nothing; a tree with nothing to
    match says so in words (the one case where searching is the right move);
  * the map is written under work/briefs/repo-map-<hash>.md with a stable hash.

B-407 A-map, on top of that (every key below is a test of the one leaf `test_files`, not of a private rule):
  * K-M1 a Java project: the test class is listed with its language note and no names, the helper beside it is
    ranked as a util, the example fence says `java`; a Python-looking line in a Java file is never read as a test;
  * K-M2 an empty map says why: the roots (a missing one marked), the files read, the top 3 extensions left out,
    the files that could not be read, the markers problem; the non-empty Python map has no `empty_reason` key;
  * K-M3 the Python map above is unchanged: its keys, its entries and its text up to the example;
  * K-M4 a test body is never a util, a helper in a test place is one, `LoginTest.java` is a test by the camel rule;
  * K-M5 the folders the markers file says to skip are skipped, and a failing or empty list leaves `SKIP_DIRS` only.
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import check, check_eq, check_in, check_not_in  # noqa: E402

sys.path.insert(0, str(harness.SCRIPTS))
import repo_map  # noqa: E402

CASE = """---
id: TC-001
title: A coupon past its usage limit is refused
area: coupon
task: QA-7
plan_row: TS-1
---

## Given
- A `coupon` created through `CouponUtils.create_coupon(limit=1)` and one prior redemption.

## When
Call `CouponUtils.apply_coupon(order, coupon)` a second time.

## Then
1. The `discount` is zero and the response names `limit_reached`.
"""

CONFTEST = '''import pytest


@pytest.fixture(scope="session")
def client():
    """The API client every test takes."""
    return object()


@pytest.fixture
def coupon_session(client, request):
    """A coupon-scoped session with its own cleanup."""
    yield client


@pytest.fixture()
def unrelated_thing():
    return 1
'''

COUPON_UTILS = '''class CouponUtils:
    """Helpers around coupons."""

    def create_coupon(self, limit=1):
        return {"limit": limit}

    def apply_coupon(self, order, coupon):
        return {"discount": 0}

    def _private(self):
        pass
'''

OTHER_UTILS = '''def make_order(client):
    """An order; a coupon may be attached later, discount applies."""
    return {}
'''

COUPON_TEST = '''import pytest


class TestCouponLimit:
    def test_limit_reached_refuses(self, coupon_session):
        assert True

    def test_first_use_passes(self, coupon_session):
        assert True
''' + "\n".join(f"# filler line {i}" for i in range(80)) + "\n"

OTHER_TEST = '''def test_orders_list(client):
    assert True
'''


# What main rendered for the Python fixture above (sizes normalised to `<n> B`: the files carry the platform's newlines).
PY_MAP_HEAD = "\n".join([
    "# Repo map - coupon (TC-001)",
    "",
    "Test roots: `tests`. Nouns from the cases' Given/When: coupon, couponutils, limit, order, utils, apply_coupon, "
    "create_coupon, apply, create, created, prior, redemption, second, through, time.",
    "",
    "## Existing tests of the area",
    "",
    "- `tests/coupon/test_coupon_limit.py` (2 tests, <n> B, matched by area): test_limit_reached_refuses, "
    "test_first_use_passes",
    "",
    "## Fixtures (conftest) - 3 of 3, ranked by the nouns",
    "",
    "- `coupon_session(client)` in `tests/conftest.py` - A coupon-scoped session with its own cleanup.",
    "- `client()` [session] in `tests/conftest.py` - The API client every test takes.",
    "- `unrelated_thing()` in `tests/conftest.py`",
    "",
    "## Utils, page objects and test data, ranked",
    "",
    "- `tests/utils/coupon_utils.py` (<n> B): CouponUtils, create_coupon, apply_coupon",
    "- `tests/utils/order_utils.py` (<n> B): make_order",
    "",
    ""])

JAVA_CASE = CASE.split("## Given")[0].replace("area: coupon", "area: foo").replace("task: QA-7", "task: QA-8") + """## Given
- The `Pages` helper opens the `FooTest` login screen.

## When
Call `Pages.open_login()`.

## Then
1. The title is shown.
"""
JAVA_APP = "package app;\n\npublic class App {\n}\n"
# the `def test_...` and `class` lines are Python-looking text inside a Java file: the Python readers must never see them
JAVA_TEST = ("package app;\n\nclass FooTest {\n    @Test void opens() {}\n}\n"
             "def test_looks_like_python():\nclass LooksLikePython:\n")
JAVA_PAGES = "package app.support;\n\nclass Pages {\n    void openLogin() {}\n}\n"


def seed_task(root: Path, ticket: str, case: str, area: str) -> Path:
    task = root / "qa-factory/artifacts" / ticket
    cases = task / "work/test-cases" / area
    cases.mkdir(parents=True)
    (cases / "TC-001.md").write_text(case, encoding="utf-8")
    (task / "pipeline.json").write_text(json.dumps({"ticket": ticket, "stages": {}}), encoding="utf-8")
    return task


def put(root: Path, rel: str, text: str = "x\n") -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def java_fixture() -> None:
    """K-M1 and E-M5: a Java project, with the test places named by the config and without."""
    for label, cfg in (("no test_locations", {"tests_root": "src"}),
                       ("test_locations names the folder", {"tests_root": "src", "test_locations": ["src/test/java/"]}),
                       ("an empty config", {})):
        root = harness.temp_project("qa-repo-map-java-")
        try:
            harness.use_project(root)
            task = seed_task(root, "QA-8", JAVA_CASE, "foo")
            put(root, "src/main/java/App.java", JAVA_APP)
            put(root, "src/test/java/FooTest.java", JAVA_TEST)
            put(root, "src/test/java/support/Pages.java", JAVA_PAGES)
            doc = repo_map.build(task, root, cfg, ["TC-001"])
            text = repo_map.render(doc)
            tag = f"K-M1 ({label}): "
            check_eq(tag + "the Java test class is the area's test file", [e["path"] for e in doc["existing_tests"]],
                     ["src/test/java/FooTest.java"])
            entry = (doc["existing_tests"] or [{}])[0]
            check_eq(tag + "listed with no test names and no classes", (entry.get("tests"), entry.get("classes"),
                                                                       entry.get("test_count")), ([], [], 0))
            check_eq(tag + "and with its language note", entry.get("language_note"),
                     "not a Python file: its test names are not listed")
            check_in(tag + "the text says so instead of 'no test functions'",
                     "`src/test/java/FooTest.java` (", text.split("## Fixtures")[0])
            check_in(tag + "with the note", "not a Python file: its test names are not listed", text)
            check_not_in(tag + "and never 'no test functions'", "no test functions", text)
            check_eq(tag + "the helper beside it is ranked as a util", [u["path"] for u in doc["utils"]],
                     ["src/test/java/support/Pages.java"])
            check_eq(tag + "its members are not guessed", (doc["utils"] or [{}])[0].get("defs"), [])
            check_eq(tag + "F1: the util entry carries the language note", (doc["utils"] or [{}])[0].get("language_note"),
                     "not a Python file: its definitions are not listed")
            util_text = text.split("## Utils")[1].split("## How a test")[0]
            check_in(tag + "F1: and the text prints it", "not a Python file: its definitions are not listed", util_text)
            check_not_in(tag + "F1: never 'module-level code' for it", "module-level code", util_text)
            check_eq(tag + "the main source is not a util and the test body is not one either",
                     [p for p in (u["path"] for u in doc["utils"]) if p.endswith(("App.java", "FooTest.java"))], [])
            check_in(tag + "the example fence says java", "```java\npackage app;", text)
            check_eq(tag + "the map is not empty, so it carries no empty_reason", "empty_reason" in doc, False)
        finally:
            harness.cleanup(root)


def empty_fixture() -> None:
    """K-M2 and E-M6: an empty map names the roots (one missing), the files read, the top 3 extensions left out."""
    root = harness.temp_project("qa-repo-map-empty-")
    try:
        harness.use_project(root)
        task = seed_task(root, "QA-9", CASE, "coupon")
        for rel in ("tests/a.md", "tests/b.md", "tests/c.md", "tests/d.json", "tests/e.json", "tests/f.txt",
                    "tests/g.yml", "tests/node_modules/skipped.md"):
            put(root, rel)
        put(root, "tests/noise.py", "VALUE = 1\n")
        cfg = {"profiles": [{"roots": {"test": "qa_missing"}}, {"roots": {"test": "tests"}}], "tests_root": "elsewhere"}
        doc = repo_map.build(task, root, cfg, ["TC-001"])
        why = doc.get("empty_reason") or {}
        check_eq("K-M2: the map is empty", doc["empty"], True)
        check_eq("K-M2: it names the roots read, the missing one marked", why.get("roots"),
                 [{"path": "qa_missing", "exists": False}, {"path": "tests", "exists": True}])
        check_eq("K-M2: only the existing root was read", doc["test_roots"], ["tests"])
        check_eq("K-M2: the files read are the code files", why.get("files_read"), 1)
        check_eq("K-M2: the top 3 extensions left out, with counts (a pruned folder is not counted, a tie goes by name)",
                 why.get("skipped_by_extension"),
                 [{"extension": ".md", "count": 3}, {"extension": ".json", "count": 2}, {"extension": ".txt", "count": 1}])
        check_eq("K-M2: no file was unreadable", why.get("files_skipped"), {})
        check_eq("K-M2: the markers problem is none", why.get("markers_problem"), "none")
        text = repo_map.render(doc)
        check("K-M2: the text prints the reason after the empty-map sentence",
              "**The map is empty**" in text and text.index("Why: roots read") > text.index("**The map is empty**"))
        check_in("K-M2: with the missing root named as missing", "`qa_missing` (missing), `tests` (exists)", text)
        check_in("K-M2: and the extensions with counts", "`.md` x3, `.json` x2, `.txt` x1", text)

        # E-M6: a root that is missing and the only one named is listed, not raised; an unreadable file is counted
        only_missing = repo_map.build(task, root, {"profiles": [{"roots": {"test": "qa_missing"}}],
                                                   "tests_root": "nowhere"}, ["TC-001"])
        check_eq("E-M6: a missing tests_root is listed as missing and the map is empty with its reason",
                 (only_missing["empty"], only_missing["empty_reason"]["roots"]),
                 (True, [{"path": "qa_missing", "exists": False}, {"path": "nowhere", "exists": False}]))
        real_open = repo_map.open if hasattr(repo_map, "open") else None

        def deny(path, *args, **kwargs):
            if str(path).endswith("noise.py"):
                raise PermissionError("denied")
            return open(path, *args, **kwargs)
        repo_map.open = deny
        try:
            unread = repo_map.build(task, root, cfg, ["TC-001"])
        finally:
            if real_open is None:
                del repo_map.open
            else:
                repo_map.open = real_open
        check_eq("E-M6: an unreadable file is counted with its reason, not raised",
                 unread["empty_reason"]["files_skipped"], {"unreadable (PermissionError)": 1})

        # F2: an empty code_extensions list is as blind as a missing file, and the map says so (never "none")
        real_markers = repo_map.test_files.markers
        table, _ = real_markers()
        repo_map.test_files.markers = lambda: (dict(table, code_extensions=[], extras_problem=""), "")
        try:
            no_ext = repo_map.build(task, root, cfg, ["TC-001"])
        finally:
            repo_map.test_files.markers = real_markers
        check_eq("F2: empty code_extensions gives an empty map that names the cause",
                 (no_ext["empty"], no_ext["empty_reason"]["markers_problem"], no_ext["empty_reason"]["files_read"]),
                 (True, "code_extensions is empty in references/test-path-markers.json: no file counts as code", 0))
        check_eq("F2: and the files left out are counted by extension", no_ext["empty_reason"]["skipped_by_extension"][0],
                 {"extension": ".md", "count": 3})
        size = (Path(repo_map.__file__)).stat().st_size
        check("F3: repo_map.py stays under 29,000 B (guard_pre_tool's whole-read limit is 30,000, CRLF adds a byte a line)",
              size < 29000, f"{size} B")

        # a markers file that cannot be read: nothing is a code file, the walk does not raise, the map says why
        real_markers = repo_map.test_files.markers
        repo_map.test_files.markers = lambda: ({}, "missing, unreadable or empty")
        try:
            blind = repo_map.build(task, root, cfg, ["TC-001"])
        finally:
            repo_map.test_files.markers = real_markers
        check_eq("E-M1: unreadable markers give an empty map that names the problem",
                 (blind["empty"], blind["empty_reason"]["markers_problem"], blind["empty_reason"]["files_read"]),
                 (True, "references/test-path-markers.json is missing, unreadable or empty", 0))
    finally:
        harness.cleanup(root)


def walk_checks() -> None:
    """K-M5 (E-M2): the markers' skip_dirs are added to SKIP_DIRS once per walk; a failing or empty list is no break."""
    tmp = harness.temp_dir("qa-repo-map-walk-")
    try:
        for rel in ("a.py", "node_modules/n.py", "target/t.py", "sub/b.java", "sub/readme.md", "sub/data.json", "notes.md"):
            put(tmp, rel)
        names = lambda files: sorted(p.relative_to(tmp).as_posix() for p in files)  # noqa: E731
        counted: dict = {}
        check_eq("R1: every code file is walked, SKIP_DIRS and the markers' skip_dirs pruned",
                 names(repo_map._walk(tmp, skipped=counted)), ["a.py", "sub/b.java"])
        check_eq("R1: the files left out by extension are counted", counted, {".md": 2, ".json": 1})
        real = repo_map.test_locations.skip_dirs
        calls = []

        def counting():
            calls.append(1)
            return real()
        repo_map.test_locations.skip_dirs = counting
        try:
            list(repo_map._walk(tmp))
        finally:
            repo_map.test_locations.skip_dirs = real
        check_eq("R1: the skip list is read once per walk, not per file", len(calls), 1)

        def broken():
            raise RuntimeError("the markers file is gone")
        for label, replacement in (("returns nothing", lambda: []), ("raises", broken)):
            repo_map.test_locations.skip_dirs = replacement
            try:
                got = names(repo_map._walk(tmp))
            finally:
                repo_map.test_locations.skip_dirs = real
            check_eq(f"K-M5: skip_dirs() that {label} leaves SKIP_DIRS only (node_modules still skipped)", got,
                     ["a.py", "sub/b.java", "target/t.py"])
    finally:
        harness.cleanup(tmp)


def predicate_checks() -> None:
    """K-M4 (E-M4): a test body is never a util; a helper in a test place is one; the camel rule comes from test_files."""
    root = harness.temp_project("qa-repo-map-pred-")
    try:
        harness.use_project(root)
        cfg = {"tests_root": "tests"}
        tests = root / "tests"

        def is_test(path: Path) -> bool:
            return repo_map._is_test_file(path, cfg, root)

        def kind(rel: str) -> tuple:
            path = root / rel
            return is_test(path), repo_map._is_util_file(path, tests, cfg, root, is_test)
        check_eq("K-M4: a helper with no test function in a test place is a util, not a test", kind("tests/helpers/latest.py"),
                 (False, True))
        check_eq("K-M4: tests/test_x.py is a test and never a util", kind("tests/test_x.py"), (True, False))
        check_eq("K-M4: tests/LoginTest.java is a test by the camel rule and never a util", kind("tests/LoginTest.java"),
                 (True, False))
        check_eq("K-M4: conftest.py and __init__.py stay out of the utils", (kind("tests/conftest.py"), kind("tests/__init__.py")),
                 ((False, False), (False, False)))
        check_eq("K-M4: today's util folder names still make a util outside a test place",
                 repo_map._is_util_file(root / "src/utils/db.py", root, cfg, root, is_test), True)
    finally:
        harness.cleanup(root)


def fence_checks() -> None:
    """R6 (E-M7): the fence word comes from the extension; an extension with no word gets a bare fence."""
    base = {"area": "x", "cases": [], "test_roots": ["tests"], "nouns": [], "existing_tests": [], "fixtures": [],
            "fixtures_total": 0, "utils": [], "empty": False}
    for path, fence in (("a/T.py", "```python"), ("a/T.tsx", "```typescript"), ("a/t.ts", "```typescript"),
                        ("a/t.JS", "```javascript"), ("a/t.jsx", "```javascript"), ("a/T.java", "```java"),
                        ("a/T.kt", "```kotlin"), ("a/T.cs", "```csharp"), ("a/t.go", "```go"), ("a/t.rb", "```ruby"),
                        ("a/T.scala", "```"), ("a/Makefile", "```")):
        text = repo_map.render(dict(base, example={"path": path, "lines": 1, "text": "body"}))
        check_in(f"E-M7: {path} gets the fence {fence!r}", f"\n{fence}\nbody\n```", text)
    # Q-b: the fence words are data (`fence_languages` in the markers file), read through test_files
    folder = harness.temp_dir("qa-repo-map-fence-")
    real_ref = repo_map.hooklib.ref
    got = []
    try:
        repo_map.hooklib.ref = lambda rel: folder / rel
        for content in ('{"fence_languages": {".scala": "scala"}}', '{"fence_languages": [".py"]}', "not json"):
            (folder / repo_map.test_files.MARKERS_FILE).write_text(content, encoding="utf-8")
            got.append([repo_map.test_files.fence_language(p) for p in ("a/T.scala", "a/T.py")])
    finally:
        repo_map.hooklib.ref = real_ref
        harness.cleanup(folder)
    check_eq("Q-b: a row in the data is a fence word, an unknown extension, a table of the wrong shape and an unreadable "
             "file all give a bare fence", got, [["scala", ""], ["", ""], ["", ""]])


def seed(root: Path, ticket: str) -> Path:
    task = seed_task(root, ticket, CASE, "coupon")
    tests = root / "tests"
    (tests / "utils").mkdir(parents=True)
    (tests / "coupon").mkdir()
    (tests / "orders").mkdir()
    (tests / "conftest.py").write_text(CONFTEST, encoding="utf-8")
    (tests / "utils" / "coupon_utils.py").write_text(COUPON_UTILS, encoding="utf-8")
    (tests / "utils" / "order_utils.py").write_text(OTHER_UTILS, encoding="utf-8")
    (tests / "coupon" / "test_coupon_limit.py").write_text(COUPON_TEST, encoding="utf-8")
    (tests / "orders" / "test_orders.py").write_text(OTHER_TEST, encoding="utf-8")
    return task


def main() -> None:
    nouns = repo_map.nouns_from_cases([CASE])
    check("a backticked identifier is a noun", "apply_coupon" in nouns)
    check("and so are its parts", "coupon" in nouns and "limit" in nouns)
    check_not_in("a Then-only word is not a noun: Given and When name the setup, Then the oracle", "discount", list(nouns))
    check("a backticked name outweighs a prose word", nouns["coupon"] > nouns.get("prior", 0))
    check_not_in("stopwords are not nouns", "given", list(nouns))

    root = harness.temp_project("qa-repo-map-")
    try:
        harness.use_project(root)
        task = seed(root, "QA-7")
        env = dict(harness.os.environ, CLAUDE_PROJECT_DIR=str(root))

        run = harness.run_script("repo_map.py", "--task", "QA-7", "--cases", "TC-001", cwd=root, env=env)
        check_eq("the CLI exits 0", run.returncode, 0, )
        check_in("and names the file it wrote", "work/briefs/repo-map-", run.stdout)
        written = sorted((task / "work/briefs").glob("repo-map-*.md"))
        check_eq("one map file exists", len(written), 1)
        text = written[0].read_text(encoding="utf-8") if written else ""
        check_in("the area comes from the case frontmatter", "Repo map - coupon (TC-001)", text)
        check_in("the area's test file is listed", "tests/coupon/test_coupon_limit.py", text)
        check_in("with its test function names", "test_limit_reached_refuses, test_first_use_passes", text)
        check_not_in("the other area's test is not", "test_orders.py", text.split("## Fixtures")[0])
        check_in("a fixture carries its signature", "`coupon_session(client)`", text)
        check_in("and its scope when it is not the default", "`client()` [session]", text)
        check_in("and its first doc line", "A coupon-scoped session", text)
        fixtures = text.split("## Fixtures")[1].split("## Utils")[0]
        check("the fixture the case names ranks above the unrelated one",
              fixtures.find("coupon_session") < fixtures.find("unrelated_thing"))
        utils = text.split("## Utils")[1].split("## How a test")[0]
        check_in("the util named after the nouns is listed", "tests/utils/coupon_utils.py", utils)
        check_in("with its class and public methods", "CouponUtils, create_coupon, apply_coupon", utils)
        check_not_in("private helpers are not shown", "_private", utils)
        check("and it outranks the util that merely mentions a coupon",
              utils.find("coupon_utils.py") < utils.find("order_utils.py"))
        check_in("the example is the area's first test file", "How a test is written here - `tests/coupon/test_coupon_limit.py`, first 60 lines", text)
        check_in("its head is inlined", "class TestCouponLimit:", text)
        check_not_in("and cut at 60 lines", "filler line 70", text)
        check_in("the closing rule tells the role to read, not search", "search the repository only when this map is empty", text)

        again = harness.run_script("repo_map.py", "--task", "QA-7", "--cases", "TC-001", "--json", cwd=root, env=env)
        doc = json.loads(again.stdout)
        check_eq("--json writes nothing new", len(sorted((task / "work/briefs").glob("repo-map-*.md"))), 1)
        check_eq("and the hash is stable", "repo-map-" + doc["hash"] + ".md", written[0].name)
        check_eq("the JSON says the map is not empty", doc["empty"], False)
        check_eq("and lists the test root the config names", doc["test_roots"], ["tests"])
        # K-M3: the Python map is what main produced (the same fixture built by the old module and by this one gave a
        # byte-identical document and text; here the document's shape and the text up to the example are pinned)
        check_eq("K-M3: a non-empty map carries no empty_reason key and no new key", sorted(doc),
                 sorted(["task", "cases", "area", "hash", "case_files", "test_roots", "nouns", "existing_tests",
                         "fixtures", "fixtures_total", "utils", "example", "empty", "markdown"]))
        check_eq("K-M3: a .py entry keeps its keys (no language note)", sorted(doc["existing_tests"][0]),
                 sorted(["path", "bytes", "classes", "tests", "test_count", "matched_by"]))
        check_eq("K-M3: and the example keeps its keys", sorted(doc["example"]), sorted(["path", "lines", "text"]))
        check_eq("K-M3: the text up to the example is the one main renders",
                 re.sub(r"[\d,]+ B\b", "<n> B", doc["markdown"].split("## How a test")[0]), PY_MAP_HEAD)
        check_in("K-M3: the example fence of a .py file is python", "```python\nimport pytest", doc["markdown"])

        forced = harness.run_script("repo_map.py", "--task", "QA-7", "--cases", "TC-001", "--area", "orders",
                                    "--json", cwd=root, env=env)
        forced_doc = json.loads(forced.stdout)
        check_eq("--area overrides the frontmatter", forced_doc["area"], "orders")
        check_eq("and picks that area's tests", [e["path"] for e in forced_doc["existing_tests"]],
                 ["tests/orders/test_orders.py"])

        # a tree with nothing to match: the words say so, and the JSON flag agrees
        for path in (root / "tests").rglob("*.py"):
            path.unlink()
        bare = harness.run_script("repo_map.py", "--task", "QA-7", "--cases", "TC-001", "--json", cwd=root, env=env)
        bare_doc = json.loads(bare.stdout)
        check_eq("an empty tree is an empty map", bare_doc["empty"], True)
        check_in("and the text says search is now the right move", "The map is empty", bare_doc["markdown"])

        missing = harness.run_script("repo_map.py", "--task", "QA-7", "--cases", "TC-999", "--json", cwd=root, env=env)
        check_eq("a case that does not exist is no crash", missing.returncode, 0)
        check_eq("its nouns are simply none", json.loads(missing.stdout)["nouns"], [])
    finally:
        harness.cleanup(root)
    java_fixture()
    empty_fixture()
    walk_checks()
    predicate_checks()
    fence_checks()
    harness.finish("test_repo_map")


if __name__ == "__main__":
    main()
