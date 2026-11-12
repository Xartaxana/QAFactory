"""Evidence is stale per TEST FUNCTION, not per file (execution_fingerprint.function_sha).

TP1-15045, window 1: the automator edited one test of a seven-test file and the file-level
`test_content_sha` declared the evidence of the other six stale, so all seven ran a second
time — part of the 20 pytest launches that window spent on 4 cases. Every case below is one
half of the rule the fix has to keep: an edit to one test leaves its neighbours' evidence
valid, and an edit to something they share invalidates all of them.
"""
import shutil
import sys
import tempfile
from pathlib import Path

from harness import PLUGIN_ROOT, check, check_eq, finish

sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))
from execution_fingerprint import function_sha  # noqa: E402

ROOT = Path(tempfile.mkdtemp(prefix="qa-instance-fingerprint-")).resolve()

CONFTEST = '''
import pytest


@pytest.fixture
def client():
    return {"kind": "client", "retries": 1}


@pytest.fixture
def seed():
    return 42
'''

HELPERS = '''
LIMIT = 10


def build_payload(size=1):
    return {"size": size}
'''

TEST_FILE = '''
import pytest

from helpers import LIMIT, build_payload


def test_alpha(client):
    assert build_payload()["size"] == 1
    assert client["retries"] == 1


def test_beta(client, seed):
    assert seed < LIMIT


class TestGroup:
    ATTEMPTS = 3

    @pytest.fixture
    def local(self):
        return "local"

    def test_gamma(self, local):
        assert local and self.ATTEMPTS


    def test_delta(self):
        assert True
'''


def write(directory: Path) -> Path:
    tests = directory / "tests"
    tests.mkdir(parents=True, exist_ok=True)
    (tests / "conftest.py").write_text(CONFTEST, encoding="utf-8")
    (tests / "helpers.py").write_text(HELPERS, encoding="utf-8")
    (tests / "test_a.py").write_text(TEST_FILE, encoding="utf-8")
    return tests


def shas(tests: Path) -> dict:
    """The fingerprint of every test of the file, as the request builder takes them: the
    conftest chain as the helper list, nearest first."""
    helpers = [str(tests / "conftest.py"), str(tests / "helpers.py")]
    cache: dict = {}
    out = {}
    for name, chain in (("test_alpha", ()), ("test_beta", ()),
                        ("test_gamma", ("TestGroup",)), ("test_delta", ("TestGroup",))):
        out[name] = function_sha(tests / "test_a.py", name, chain, helpers, cache)["sha"]
    return out


def edit(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if old not in text:
        raise AssertionError("the fixture text changed; this edit no longer applies: " + old)
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def changed(before: dict, after: dict) -> list:
    return sorted(name for name in before if before[name] != after[name])


def moved(before: dict, after: dict) -> tuple:
    """(the raw sha moved, the code sha moved) between two measurements of one instance."""
    return before["sha"] != after["sha"], before["code_sha"] != after["code_sha"]


def round_two(directory: Path) -> None:
    """t-055 round 2 (critic t-066). function_sha is the identity both for reuse and for proof;
    its only allowed error is "different": a missed code change lets an old result cover changed
    code. Every case below is one edit and the answer to "did the code sha move"."""
    directory.mkdir(parents=True, exist_ok=True)
    CODE, COSMETIC = (True, True), (True, False)

    def case(label: str, before_text: str, after_text: str, expect: tuple, name="test_a", chain=(),
             file="test_r.py", helpers=(), extra: dict = None) -> None:
        for other, content in (extra or {}).items():
            (directory / other).parent.mkdir(parents=True, exist_ok=True)
            (directory / other).write_text(content, encoding="utf-8")
        path = directory / file
        path.write_text(before_text, encoding="utf-8")
        before = function_sha(path, name, chain, [directory / h for h in helpers])
        path.write_text(after_text, encoding="utf-8")
        after = function_sha(path, name, chain, [directory / h for h in helpers])
        check("R2 " + label + ": function scope, both shas present", before["scope"] == "function"
              and before["sha"] and before["code_sha"] and after["code_sha"])
        check_eq("R2 " + label, moved(before, after), expect)

    # --- fix 1: the lines the PARSER counts, not str.splitlines' ------------------------------------
    body = "def test_a():\n    x = 1\n    assert x == 1\n"
    for label, prefix in (("a form feed line above the test", "\x0c\n\n"),
                          ("U+2028 inside a comment above the test", "# a b\n"),
                          ("U+0085 inside a comment above the test", "# a\u0085b\n"),
                          ("a vertical tab, FS, GS and RS in comments", "# \x0b\x1c\x1d\x1e\n"),
                          ("U+2029 in a comment", "# a b\n")):
        case("a code edit with " + label, prefix + body, prefix + body.replace("== 1", "== 2"), CODE)
    inside = 'def test_a():\n    x = "a\u0085b"\n    assert x == 1\n'
    case("a code edit under U+0085 in a string of the test", inside, inside.replace("== 1", "== 2"), CODE)
    case("a code edit under U+2028 in a string of the test", inside.replace("\u0085", " "),
         inside.replace("\u0085", " ").replace("== 1", "== 2"), CODE)
    case("a comment edit under a form feed is still cosmetic", "\x0c\n\n" + body,
         "\x0c\n\n" + body.replace("    x = 1", "    # why\n    x = 1"), COSMETIC)

    # --- fix 2: the factory's own markers are cosmetic, any other decorator is code ------------------
    bare = "def test_a():\n    assert 1\n"
    marker = '@pytest.mark.qa(case="TC-1", then="TC-2")\n'
    case("a factory marker added to a test that never mentions pytest", bare, marker + bare, COSMETIC)
    case("the factory marker removed", marker + bare, bare, COSMETIC)
    case("the unresolved marker added", bare, '@pytest.mark.qa_unresolved(case="TC-1", reason="no api")\n' + bare,
         COSMETIC)
    case("@pytest.mark.skip added to the same test", bare, "@pytest.mark.skip\n" + bare, CODE)
    case("@pytest.mark.parametrize added", bare, '@pytest.mark.parametrize("a", [1])\n' + bare, CODE)
    case("@pytest.mark.usefixtures added", bare, '@pytest.mark.usefixtures("db")\n' + bare, CODE)
    case("a marker whose argument is code is code", bare, "@pytest.mark.qa(case=CASE)\n" + bare, CODE)
    case("a project's own decorator is code", bare, "@retry\n" + bare, CODE)

    # --- fix 3: every enclosing class of the chain, without its sibling tests -------------------------
    nested = ("import pytest\n\n\nclass Meta(type):\n    pass\n\n\nclass Meta2(type):\n    pass\n\n\n"
              "class TestOuter:\n    MODE = 1\n\n    @pytest.fixture(autouse=True)\n    def prep(self):\n"
              "        return 'a'\n\n    def test_sibling(self):\n        assert 1\n\n"
              "    class TestInner(metaclass=Meta):\n        def test_a(self):\n            assert True\n\n"
              "        def test_other(self):\n            assert 2\n")
    chain = ("TestOuter", "TestInner")

    def nest(label, old, new, expect, **kw):
        case("nested chain: " + label, nested, nested.replace(old, new, 1), expect, chain=chain, **kw)

    nest("the outer class gains @skip", "class TestOuter:", "@pytest.mark.skip\nclass TestOuter:", CODE)
    nest("the outer class gains a pytestmark", "    MODE = 1\n", "    MODE = 1\n    pytestmark = pytest.mark.skip\n", CODE)
    nest("the outer autouse fixture's body is edited", "return 'a'", "return 'b'", CODE)
    nest("the holder's metaclass is changed", "metaclass=Meta)", "metaclass=Meta2)", CODE)
    nest("the outer class's own data is edited", "MODE = 1", "MODE = 2", CODE)
    nest("a sibling test of the outer class is edited", "def test_sibling(self):\n        assert 1",
         "def test_sibling(self):\n        assert 3", (False, False))
    nest("a sibling test of the holder is edited", "def test_other(self):\n            assert 2",
         "def test_other(self):\n            assert 4", (False, False))
    nest("a comment in the outer class", "    MODE = 1\n", "    # a note\n    MODE = 1\n", (False, False))

    # --- fix 4: the bases of every class on the chain -------------------------------------------------
    same_file = ("class TestBase:\n    def setup_method(self, method):\n        self.v = 1\n\n\n"
                 "class TestChild(TestBase):\n    def test_a(self):\n        assert self.v\n")
    case("a same-file Test* base: its setup_method edited", same_file, same_file.replace("self.v = 1", "self.v = 2"),
         CODE, chain=("TestChild",))
    deep = ("class Root:\n    def setup_method(self, method):\n        self.v = 1\n\n\n"
            "class Mid(Root):\n    pass\n\n\nclass TestChild(Mid):\n    def test_a(self):\n        assert self.v\n")
    case("a base of a base, edited", deep, deep.replace("self.v = 1", "self.v = 2"), CODE, chain=("TestChild",))
    base_file = "class Base:\n    def setup_method(self, method):\n        self.v = 1\n"
    child_from = "from basemod import Base\n\n\nclass TestChild(Base):\n    def test_a(self):\n        assert self.v\n"
    child_import = "import basemod\n\n\nclass TestChild(basemod.Base):\n    def test_a(self):\n        assert self.v\n"
    child_star = "from basemod import *\n\n\nclass TestChild(Base):\n    def test_a(self):\n        assert self.v\n"
    for label, text in (("from x import B", child_from), ("import x; x.B", child_import),
                        ("from x import *", child_star)):
        (directory / "basemod.py").write_text(base_file, encoding="utf-8")
        path = directory / "test_b.py"
        path.write_text(text, encoding="utf-8")
        before = function_sha(path, "test_a", ("TestChild",), [])
        (directory / "basemod.py").write_text(base_file.replace("self.v = 1", "self.v = 2"), encoding="utf-8")
        after = function_sha(path, "test_a", ("TestChild",), [])
        check_eq("R2 a base in a project file, spelled `" + label + "`, edited (the file is NOT a listed helper)",
                 (before["scope"], moved(before, after)), ("function", CODE))
    (directory / "basemod.py").write_text(base_file, encoding="utf-8")
    pristine = function_sha(directory / "test_b.py", "test_a", ("TestChild",), [])
    (directory / "basemod.py").write_text(base_file + "# a note\n", encoding="utf-8")
    check_eq("R2 a comment in the base file: raw moves, code does not",
             moved(pristine, function_sha(directory / "test_b.py", "test_a", ("TestChild",), [])), COSMETIC)
    lost = "class TestChild(Missing):\n    def test_a(self):\n        assert 1\n"
    (directory / "test_c.py").write_text(lost, encoding="utf-8")
    gone = function_sha(directory / "test_c.py", "test_a", ("TestChild",), [])
    check_eq("R2 a base nothing binds: no identity, the test runs", (gone["sha"], gone["code_sha"]), ("", ""))
    for fine in ("object", "Exception", "unittest.TestCase"):
        (directory / "test_c.py").write_text(
            "import unittest\n\n\nclass TestChild(" + fine + "):\n    def test_a(self):\n        assert 1\n",
            encoding="utf-8")
        got = function_sha(directory / "test_c.py", "test_a", ("TestChild",), [])
        check("R2 control: a builtin or stdlib base (`" + fine + "`) still has an identity", got["sha"] and got["code_sha"])

    # --- fix 5: the conftest chain and the package's __init__ files -----------------------------------
    conftest = ("import pytest\n\n\n@pytest.fixture(autouse=True)\ndef around():\n    return 1\n\n\n"
                "def pytest_collection_modifyitems(items):\n    pass\n\n\n@pytest.fixture\ndef dbx():\n    return 5\n")
    plain = "def test_a():\n    assert 1\n"
    used = "import pytest\n\n\n@pytest.mark.usefixtures('dbx')\nclass TestU:\n    def test_a(self):\n        assert 1\n"
    for label, old, new in (("an autouse fixture edited", "return 1", "return 2"),
                            ("a hook edited", "items):\n    pass", "items):\n    items.clear()"),
                            ("a fixture only a class-level usefixtures names, edited", "return 5", "return 6")):
        sub = directory / "c5"
        sub.mkdir(exist_ok=True)
        (sub / "conftest.py").write_text(conftest, encoding="utf-8")
        (sub / "test_c.py").write_text(used if "class-level" in label else plain, encoding="utf-8")
        chain5 = ("TestU",) if "class-level" in label else ()
        before = function_sha(sub / "test_c.py", "test_a", chain5, [sub / "conftest.py"])
        (sub / "conftest.py").write_text(conftest.replace(old, new, 1), encoding="utf-8")
        after = function_sha(sub / "test_c.py", "test_a", chain5, [sub / "conftest.py"])
        check_eq("R2 conftest: " + label, moved(before, after), CODE)
    (sub / "conftest.py").write_text(conftest, encoding="utf-8")
    before = function_sha(sub / "test_c.py", "test_a", ("TestU",), [sub / "conftest.py"])
    (sub / "conftest.py").write_text("# a note\n" + conftest.replace("def dbx", "# about it\ndef dbx"), encoding="utf-8")
    check_eq("R2 conftest: comments only - raw moves, code does not",
             moved(before, function_sha(sub / "test_c.py", "test_a", ("TestU",), [sub / "conftest.py"])), COSMETIC)
    upper = directory / "c5" / "deeper"
    upper.mkdir(exist_ok=True)
    (upper / "test_d.py").write_text(plain, encoding="utf-8")
    (sub / "conftest.py").write_text(conftest, encoding="utf-8")
    before = function_sha(upper / "test_d.py", "test_a", (), [sub / "conftest.py"])
    (sub / "conftest.py").write_text(conftest.replace("return 1", "return 2"), encoding="utf-8")
    check_eq("R2 conftest: one in a directory ABOVE the test counts too",
             moved(before, function_sha(upper / "test_d.py", "test_a", (), [sub / "conftest.py"])), CODE)
    elsewhere = directory / "c5" / "aside"
    elsewhere.mkdir(exist_ok=True)
    (elsewhere / "conftest.py").write_text("X = 1\n", encoding="utf-8")
    before = function_sha(upper / "test_d.py", "test_a", (), [sub / "conftest.py", elsewhere / "conftest.py"])
    (elsewhere / "conftest.py").write_text("X = 2\n", encoding="utf-8")
    check_eq("R2 conftest: one of a directory the test is not under does not",
             moved(before, function_sha(upper / "test_d.py", "test_a", (), [sub / "conftest.py", elsewhere / "conftest.py"])),
             (False, False))
    package = directory / "pk"
    package.mkdir(exist_ok=True)
    (package / "__init__.py").write_text("import os\n", encoding="utf-8")
    (package / "test_p.py").write_text(plain, encoding="utf-8")
    before = function_sha(package / "test_p.py", "test_a", (), [])
    (package / "__init__.py").write_text("import sys\n", encoding="utf-8")
    check_eq("R2 an __init__.py of the test's package edited", moved(before, function_sha(package / "test_p.py", "test_a", (), [])), CODE)
    before = function_sha(package / "test_p.py", "test_a", (), [])
    (package / "__init__.py").write_text("# only a note\nimport sys\n", encoding="utf-8")
    check_eq("R2 ... a comment in it moves the raw sha and not the code sha",
             moved(before, function_sha(package / "test_p.py", "test_a", (), [])), COSMETIC)

    # --- fix 6: Python runs the LAST definition of a name --------------------------------------------
    twice = "def test_a():\n    assert 1\n\n\ndef test_a():\n    assert 2\n"
    case("the second (effective) test_a edited", twice, twice.replace("assert 2", "assert 3"), CODE)
    case("the shadowed first test_a edited", twice, twice.replace("assert 1", "assert 0"), CODE)
    case("a comment in a duplicate is cosmetic", twice, twice.replace("    assert 1", "    # first\n    assert 1"), COSMETIC)


def main() -> None:
    tests = write(ROOT)
    try:
        base = shas(tests)
        check_eq("every test of the file has its own fingerprint", len(set(base.values())), 4)
        check_eq("and it is the same on a second reading", shas(tests), base)

        # --- the half that cost the launches: a neighbour's edit ---------------------------
        edit(tests / "test_a.py", 'build_payload()["size"] == 1', 'build_payload()["size"] >= 1')
        check_eq("an edit inside one test invalidates that test alone",
                 changed(base, shas(tests)), ["test_alpha"])
        base = shas(tests)
        edit(tests / "test_a.py", "assert True", "assert 1 == 1")
        check_eq("and a test method invalidates no sibling method of its class",
                 changed(base, shas(tests)), ["test_delta"])

        # --- the half that must keep invalidating -----------------------------------------
        base = shas(tests)
        edit(tests / "conftest.py", '"retries": 1', '"retries": 3')
        # The conftest of the test's directory is part of EVERY instance under it (t-055 round 2,
        # critic t-066: an autouse fixture or a hook runs for tests that never name it), coarse by
        # design: a code edit in it invalidates all four. Per-name granularity lives in the
        # helper files below.
        check_eq("a code edit in the conftest invalidates every test under it",
                 changed(base, shas(tests)), ["test_alpha", "test_beta", "test_delta", "test_gamma"])
        base = shas(tests)
        edit(tests / "conftest.py", "return 42", "return 7")
        check_eq("a fixture only one test names is the conftest's edit too: every test",
                 changed(base, shas(tests)), ["test_alpha", "test_beta", "test_delta", "test_gamma"])
        base = shas(tests)
        edit(tests / "helpers.py", "return {\"size\": size}", "return {\"size\": size + 0}")
        check_eq("an imported helper invalidates the test that calls it",
                 changed(base, shas(tests)), ["test_alpha"])
        base = shas(tests)
        edit(tests / "helpers.py", "LIMIT = 10", "LIMIT = 11")
        check_eq("an imported constant invalidates the test that reads it",
                 changed(base, shas(tests)), ["test_beta"])
        base = shas(tests)
        edit(tests / "test_a.py", "ATTEMPTS = 3", "ATTEMPTS = 4")
        check_eq("class-level data invalidates every test of the class",
                 changed(base, shas(tests)), ["test_delta", "test_gamma"])
        base = shas(tests)
        edit(tests / "test_a.py", 'return "local"', 'return "local!"')
        check_eq("so does a fixture declared in the class", changed(base, shas(tests)),
                 ["test_delta", "test_gamma"])

        # --- the same bytes anywhere on disk ------------------------------------------------
        # A red probe fingerprints a copy of the tree in a sandbox; a fingerprint that carried
        # absolute paths would never match the author's, and every probe would look like an edit.
        copy = ROOT / "sandbox"
        shutil.copytree(ROOT / "tests", copy / "tests")
        check_eq("a copy of the tree elsewhere fingerprints identically", shas(copy / "tests"),
                 shas(tests))

        # --- what falls back to the whole file ----------------------------------------------
        gone = function_sha(tests / "test_a.py", "test_generated", (), [])
        check_eq("a test the reader cannot find in the source falls back to the file",
                 gone["scope"], "file")
        check_eq("a test of a class that is not there falls back too",
                 function_sha(tests / "test_a.py", "test_alpha", ("NoSuchClass",), [])["scope"],
                 "file")
        (ROOT / "broken.py").write_text("def test_x(:\n", encoding="utf-8")
        broken = function_sha(ROOT / "broken.py", "test_x", (), [])
        check_eq("an unparsable file falls back to its bytes", broken["scope"], "file")
        check("and those bytes still decide staleness",
              broken["sha"] != function_sha(ROOT / "missing.py", "test_x", (), [])["sha"])
        before = function_sha(tests / "test_a.py", "test_generated", (), [])["sha"]
        edit(tests / "test_a.py", "assert 1 == 1", "assert 2 == 2")
        check("a file-scope fingerprint is invalidated by any edit to the file",
              function_sha(tests / "test_a.py", "test_generated", (), [])["sha"] != before)
        check_eq("a test that is found keeps a function scope",
                 function_sha(tests / "test_a.py", "test_alpha", (),
                              [str(tests / "conftest.py")])["scope"], "function")

        # --- the code sha (the run budget, D-0017): the same parts, with what cannot execute
        # taken out. A comment, a docstring line or a blank line is not an edit; anything else is.
        fresh = write(ROOT / "code")

        def codes(directory: Path) -> dict:
            helpers = [str(directory / "conftest.py"), str(directory / "helpers.py")]
            cache: dict = {}
            found = {}
            for name, chain in (("test_alpha", ()), ("test_beta", ()),
                                ("test_gamma", ("TestGroup",)), ("test_delta", ("TestGroup",))):
                found[name] = function_sha(directory / "test_a.py", name, chain, helpers, cache)["code_sha"]
            return found

        base_code, base_raw = codes(fresh), shas(fresh)
        check_eq("every test has a code sha of its own", len(set(base_code.values())), 4)
        check("and it is not the raw sha", all(base_code[k] != base_raw[k] for k in base_code))
        edit(fresh / "test_a.py", "def test_alpha(client):\n", "def test_alpha(client):\n    # why this\n")
        check_eq("a comment inside a test moves its raw sha and not its code sha",
                 (changed(base_raw, shas(fresh)), changed(base_code, codes(fresh))), (["test_alpha"], []))
        base_code, base_raw = codes(fresh), shas(fresh)
        edit(fresh / "test_a.py", "def test_delta(self):\n", 'def test_delta(self):\n        """Checks delta."""\n')
        check_eq("a docstring line is not an edit either",
                 (changed(base_raw, shas(fresh)), changed(base_code, codes(fresh))), (["test_delta"], []))
        base_code, base_raw = codes(fresh), shas(fresh)
        edit(fresh / "test_a.py", "\n\ndef test_beta", "\n\n\n\n\ndef test_beta")
        check_eq("blank lines between tests are not an edit",
                 changed(base_code, codes(fresh)), [])
        edit(fresh / "test_a.py", "assert seed < LIMIT", "assert seed <= LIMIT")
        check_eq("an assert changed IS one, and only for that test", changed(base_code, codes(fresh)), ["test_beta"])
        base_code = codes(fresh)
        edit(fresh / "test_a.py", "def test_beta", "@pytest.mark.skip\ndef test_beta")
        check_eq("a decorator added is code: the decorator's own line is part of the test",
                 changed(base_code, codes(fresh)), ["test_beta"])
        base_code, base_raw = codes(fresh), shas(fresh)
        edit(fresh / "conftest.py", "def client():\n", "def client():\n    # a fixture note\n")
        check_eq("a comment in the conftest moves the raw sha of every test under it and no code sha",
                 (changed(base_raw, shas(fresh)), changed(base_code, codes(fresh))),
                 (["test_alpha", "test_beta", "test_delta", "test_gamma"], []))
        edit(fresh / "helpers.py", "LIMIT = 10", "# how many\nLIMIT = 10\n\n\n")
        check_eq("nor does a comment or blank line in a helper the test reads",
                 changed(base_code, codes(fresh)), [])
        edit(fresh / "helpers.py", "LIMIT = 10", "LIMIT = 11")
        check_eq("but a changed constant is code", changed(base_code, codes(fresh)), ["test_beta"])
        base_code = codes(fresh)
        edit(fresh / "test_a.py", "ATTEMPTS = 3", "# attempts\n    ATTEMPTS = 3")
        check_eq("a comment in the class body moves no code sha of its methods",
                 changed(base_code, codes(fresh)), [])
        copy_code = ROOT / "code-sandbox"
        shutil.copytree(fresh, copy_code / "tests")
        check_eq("the code sha is the same on a copy of the tree elsewhere", codes(copy_code / "tests"), codes(fresh))

        # --- the module skeleton (t-055): module-level code is part of every instance ------------
        # A module-wide `pytestmark` reaches no name a test uses, so the name-following above
        # never saw it; and another test's own body must stay out (fixing test_b never stales
        # test_a).
        skel = write(ROOT / "skel")
        every = ["test_alpha", "test_beta", "test_delta", "test_gamma"]
        base_code, base_raw = codes(skel), shas(skel)
        edit(skel / "test_a.py", "import pytest\n", "import pytest\n\npytestmark = pytest.mark.skip\n")
        check_eq("`pytestmark` added moves both shas of EVERY instance",
                 (changed(base_raw, shas(skel)), changed(base_code, codes(skel))), (every, every))
        base_code, base_raw = codes(skel), shas(skel)
        edit(skel / "test_a.py", "pytest.mark.skip", "pytest.mark.skipif(True, reason='x')")
        check_eq("and so does `pytestmark` edited",
                 (changed(base_raw, shas(skel)), changed(base_code, codes(skel))), (every, every))
        base_code, base_raw = codes(skel), shas(skel)
        edit(skel / "test_a.py", "\npytestmark", "\n# a module note\npytestmark")
        check_eq("a module-level comment moves the raw sha of every instance and no code sha",
                 (changed(base_raw, shas(skel)), changed(base_code, codes(skel))), (every, []))
        base_code, base_raw = codes(skel), shas(skel)
        edit(skel / "test_a.py", "from helpers import LIMIT, build_payload",
             "from helpers import LIMIT, build_payload, LIMIT as CAP")
        check_eq("an import edited moves both",
                 (changed(base_raw, shas(skel)), changed(base_code, codes(skel))), (every, every))
        base_code, base_raw = codes(skel), shas(skel)
        edit(skel / "test_a.py", "\n\ndef test_alpha", "\n\nDELAY = 5\n\n\ndef helper():\n    return DELAY\n\n\ndef test_alpha")
        check_eq("a module constant and helper added: both shas of every instance",
                 (changed(base_raw, shas(skel)), changed(base_code, codes(skel))), (every, every))
        base_code, base_raw = codes(skel), shas(skel)
        edit(skel / "test_a.py", "DELAY = 5", "DELAY = 6")
        check_eq("and a constant edited, whether the test reads it or not",
                 (changed(base_raw, shas(skel)), changed(base_code, codes(skel))), (every, every))
        base_code, base_raw = codes(skel), shas(skel)
        edit(skel / "test_a.py", "assert seed < LIMIT", "assert seed <= LIMIT")
        check_eq("ANOTHER test's body edited moves neither sha of this one (D5)",
                 (changed(base_raw, shas(skel)), changed(base_code, codes(skel))), (["test_beta"], ["test_beta"]))
        base_code, base_raw = codes(skel), shas(skel)
        base_code, base_raw = codes(skel), shas(skel)
        edit(skel / "test_a.py", "assert local and self.ATTEMPTS", "assert local")
        check_eq("nor does a method of a test class: only that method",
                 (changed(base_raw, shas(skel)), changed(base_code, codes(skel))), (["test_gamma"], ["test_gamma"]))

        # a class a test lives in that pytest collects without the `Test` prefix (unittest)
        (skel / "test_u.py").write_text(
            "import unittest\n\n\nclass Cases(unittest.TestCase):\n    def test_one(self):\n        assert 1\n\n"
            "    def test_two(self):\n        assert 2\n", encoding="utf-8")

        def pair() -> dict:
            return {n: function_sha(skel / "test_u.py", n, ("Cases",), [])
                    for n in ("test_one", "test_two")}

        before = pair()
        edit(skel / "test_u.py", "assert 2", "assert 3")
        after = pair()
        check_eq("a test class not named `Test*` does not bring its siblings back through the skeleton",
                 [n for n in before if before[n]["sha"] != after[n]["sha"]], ["test_two"])
        check_eq("(code sha too)", [n for n in before if before[n]["code_sha"] != after[n]["code_sha"]],
                 ["test_two"])

        # --- identity v2 (FB-10): an ADDED test function and its gap are not part of any identity ---------
        base_code, base_raw = codes(skel), shas(skel)
        every = ["test_alpha", "test_beta", "test_delta", "test_gamma"]
        text = (skel / "test_a.py").read_text(encoding="utf-8")
        (skel / "test_a.py").write_text(text.rstrip("\n") + "\n\n\n# about the new one\n\n@pytest.mark.skip\n"
                                        "async def test_new():\n    assert 1\n", encoding="utf-8")
        check_eq("K-S1 appended_test_and_its_gap_leave_the_skeleton: a test appended with its comment gap and "
                 "decorator moves no sha of any other test",
                 (changed(base_raw, shas(skel)), changed(base_code, codes(skel))), ([], []))
        (skel / "test_a.py").write_text(text, encoding="utf-8")
        edit(skel / "test_a.py", "\npytestmark", "\n# a module note\npytestmark")
        base_code, base_raw = codes(skel), shas(skel)
        edit(skel / "test_a.py", "# a module note\n", "# another module note\n")
        check_eq("K-S2 comment_before_a_non_test_statement_stays: that comment moves the raw sha of every instance",
                 (changed(base_raw, shas(skel)), changed(base_code, codes(skel))), (every, []))
        (skel / "test_s3.py").write_text(
            'DOC = """one\n\n\ntwo"""\n\n\ndef test_x():\n    assert DOC\n', encoding="utf-8")
        before_s3 = function_sha(skel / "test_s3.py", "test_x", (), [])
        (skel / "test_s3.py").write_text(
            'DOC = """one\n\ntwo"""\n\n\ndef test_x():\n    assert DOC\n', encoding="utf-8")
        after_s3 = function_sha(skel / "test_s3.py", "test_x", (), [])
        check("K-S3 blank_lines_inside_a_module_string_stay: two different literals never hash equal",
              before_s3["sha"] != after_s3["sha"] and before_s3["code_sha"] != after_s3["code_sha"])
        (skel / "test_s4.py").write_text("def test_x(tmp_path_factory):\n    assert 1\n", encoding="utf-8")
        before_s4 = function_sha(skel / "test_s4.py", "test_x", (), [])
        (skel / "test_s4.py").write_text(
            "import pytest\n\n\ndef test_x(tmp_path_factory):\n    assert 1\n\n\n@pytest.fixture\n"
            "def tmp_path_factory():\n    raise RuntimeError('x')\n\n\ndef test_y():\n    assert 2\n", encoding="utf-8")
        after_s4 = function_sha(skel / "test_s4.py", "test_x", (), [])
        check_eq("K-S4 plugin_fixture_override_moves_every_sha: an unreferenced override of a plugin fixture, "
                 "appended with a new test, moves both shas",
                 (before_s4["sha"] != after_s4["sha"], before_s4["code_sha"] != after_s4["code_sha"]), (True, True))

        # a skeleton the classifier cannot tell voids the code sha of every instance of the file
        (skel / "test_v.py").write_text(
            'UNUSED = "UNTOKENIZABLE"\n\n\ndef test_v():\n    assert True\n', encoding="utf-8")
        import execution_fingerprint as ef
        real_sha = ef.executable_sha
        ef.executable_sha = lambda text, name="": "" if "UNTOKENIZABLE" in text else real_sha(text, name)
        try:
            blind = function_sha(skel / "test_v.py", "test_v", (), [])
            check_eq("a skeleton that does not tokenize: no code sha, the raw sha stays",
                     (blind["code_sha"], bool(blind["sha"]), blind["scope"]), ("", True, "function"))
        finally:
            ef.executable_sha = real_sha
        check("control: the same file has a code sha while the skeleton can be told",
              bool(function_sha(skel / "test_v.py", "test_v", (), [])["code_sha"]))
        (skel / "test_w.py").write_text(
            "import pytest\n\npytestmark = pytest.mark.skip\n\n\nclass TestOuter:\n    class TestInner:\n"
            "        def test_deep(self):\n            assert True\n", encoding="utf-8")
        deep = function_sha(skel / "test_w.py", "test_deep", ("TestOuter", "TestInner"), [])
        check("a nested class: a function scope and both shas", deep["scope"] == "function"
              and deep["sha"] and deep["code_sha"])
        text = (skel / "test_w.py").read_text(encoding="utf-8")
        (skel / "test_w.py").write_text(text.replace("pytest.mark.skip", "pytest.mark.xfail"), encoding="utf-8")
        check("and its module-level `pytestmark` moves it",
              function_sha(skel / "test_w.py", "test_deep", ("TestOuter", "TestInner"), [])["code_sha"]
              != deep["code_sha"])

        round_two(ROOT / "r2")

        # what falls back, and what has no code sha
        whole = function_sha(fresh / "test_a.py", "test_generated", (), [])
        check("a file-scope fallback has a code sha of the whole file", whole["scope"] == "file" and whole["code_sha"])
        text = (fresh / "test_a.py").read_text(encoding="utf-8")
        (fresh / "test_a.py").write_text("# only a comment\n" + text, encoding="utf-8")
        check_eq("and a comment does not move it",
                 function_sha(fresh / "test_a.py", "test_generated", (), [])["code_sha"], whole["code_sha"])
        (fresh / "bytes.py").write_bytes(b"def test_x():\n    assert '\xff' == 1\n")
        odd = function_sha(fresh / "bytes.py", "test_x", (), [])
        check_eq("a file that is not UTF-8 has no code sha: the raw rule only", (odd["scope"], odd["code_sha"]),
                 ("function", ""))
        check_eq("a file-scope fallback of one has none either",
                 function_sha(fresh / "bytes.py", "test_missing", (), [])["code_sha"], "")
        check("but it still has its raw sha", bool(odd["sha"]))

        # Identity is never made of nothing (t-055): two DIFFERENT files that do not decode read
        # alike through `errors="replace"` (U+FFFD where their bad bytes are), and two files that
        # are missing hash alike as empty; neither pair may be one identity.
        (fresh / "bytes2.py").write_bytes(b"def test_x():\n    assert '\xfe' == 1\n")
        (fresh / "bytes3.py").write_bytes(b"def test_x():\n    assert '\xff' == 1\n")
        other, same = (function_sha(fresh / n, "test_x", (), []) for n in ("bytes2.py", "bytes3.py"))
        check_eq("two different files that do not decode have different raw shas",
                 (other["sha"] != odd["sha"], same["sha"] == odd["sha"], other["scope"]), (True, True, "function"))
        check_eq("(and neither has a code sha)", (other["code_sha"], same["code_sha"]), ("", ""))
        check("the same undecodable file twice has the same raw sha",
              function_sha(fresh / "bytes2.py", "test_x", (), [])["sha"] == other["sha"])
        (fresh / "mixed.py").write_bytes(b"import pytest\n\n\ndef test_x(h):\n    assert h\n")
        (fresh / "h1.py").write_bytes(b"def h():\n    return '\xff'\n")
        (fresh / "h2.py").write_bytes(b"def h():\n    return '\xfe'\n")
        first_helper, second_helper = (function_sha(fresh / "mixed.py", "test_x", (), [fresh / n]) for n in ("h1.py", "h2.py"))
        check("a fixture read from an undecodable helper is hashed as the helper's bytes too",
              first_helper["sha"] != second_helper["sha"] and first_helper["code_sha"] == "")
        missing_a = function_sha(fresh / "missing_a.py", "test_x", (), [])
        missing_b = function_sha(fresh / "missing_b.py", "test_x", (), [])
        check_eq("a test file that is not there has no identity: sha and code sha are empty",
                 (missing_a["sha"], missing_a["code_sha"], missing_b["sha"], missing_b["code_sha"]), ("", "", "", ""))
        gone = function_sha(fresh / "test_a.py", "test_alpha", (), [str(fresh / "no_such_conftest.py")])
        check_eq("a helper of the run that cannot be read voids the instance too",
                 (gone["sha"], gone["code_sha"]), ("", ""))
        check("control: the same instance with the helper listed and present has both",
              all(function_sha(fresh / "test_a.py", "test_alpha", (), [str(fresh / "conftest.py")])[k]
                  for k in ("sha", "code_sha")))

        # A part the classifier cannot tell makes the WHOLE code sha "" (t-023: `executable_sha`
        # answers "" for a fragment that does not tokenize or a file that is not `.py`).
        import execution_fingerprint as ef
        (fresh / "frag.py").write_text('MARK = "UNTOKENIZABLE"\n\n\ndef test_m():\n    assert MARK\n', encoding="utf-8")
        real_sha = ef.executable_sha
        whole = function_sha(fresh / "frag.py", "test_m", (), [])
        check("control: the same instance has a code sha while every part can be told", bool(whole["code_sha"]))
        ef.executable_sha = lambda text, name="": "" if "UNTOKENIZABLE" in text else real_sha(text, name)
        try:
            blind = function_sha(fresh / "frag.py", "test_m", (), [])
            check_eq("one part that cannot be told: no code sha for the instance", blind["code_sha"], "")
            check_eq("its raw sha and scope are untouched", (blind["sha"], blind["scope"]),
                     (whole["sha"], "function"))
            check("and a file-scope fallback whose file cannot be told has none either",
                  function_sha(fresh / "frag.py", "test_missing", (), [])["code_sha"] == "")
        finally:
            ef.executable_sha = real_sha
        (fresh / "notes.txt").write_text("assert 1\n", encoding="utf-8")
        check_eq("a file that is not `.py` has no code sha", function_sha(fresh / "notes.txt", "test_x", (), [])["code_sha"], "")
    finally:
        shutil.rmtree(ROOT, ignore_errors=True)
    finish("test_instance_fingerprint")


if __name__ == "__main__":
    main()
