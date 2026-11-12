#!/usr/bin/env python3
"""Whether a test is new, changed or unchanged since the story's base (B-207, piece P5-B).

`unchanged` is the one answer that skips a live check, so it is returned only against a recorded S0
base with every file of the measured set equal; every doubt is `new`, `changed` or `unknown`. One
named check per requirement and edge of the spec (R2, overrides V2-V4), on real git repositories
built under the OS temp dir - nothing here touches this repository or a live project. The S0
record itself comes from `test_repo_base.record`, so the two halves are tested against each other.

Git is REQUIRED: a machine with no git fails this file by name instead of skipping it (FR-4).
"""
import os
import subprocess
import sys
import tempfile
import time
import json
import contextlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import (SCRIPTS, check, check_eq, check_in, check_not_in, cleanup,  # noqa: E402
                     finish, temp_dir)

sys.path.insert(0, str(SCRIPTS))

# The repositories built here must not read this machine's git configuration.
os.environ["GIT_CONFIG_GLOBAL"] = os.devnull
os.environ["GIT_CONFIG_NOSYSTEM"] = "1"
os.environ["GIT_AUTHOR_NAME"] = os.environ["GIT_COMMITTER_NAME"] = "tester"
os.environ["GIT_AUTHOR_EMAIL"] = os.environ["GIT_COMMITTER_EMAIL"] = "tester@example.com"

import test_novelty as NV  # noqa: E402
import test_repo_base as TRB  # noqa: E402
import execution_fingerprint as FP  # noqa: E402

ALL_MIRRORS = []
_mkdtemp_before_spy = tempfile.mkdtemp


def _recording_mkdtemp(*a, **k):
    """Every mirror this file's calls create, to prove at the end that none was left behind."""
    path = _mkdtemp_before_spy(*a, **k)
    name = os.path.basename(path)
    if name.startswith("qa-novelty-") and not name.startswith("qa-novelty-test-"):
        ALL_MIRRORS.append(path)
    return path


tempfile.mkdtemp = _recording_mkdtemp

SUB = "proj"
TEST_A = """import pytest
from helper.util import VALUE


def test_one(fx):
    # a comment
    assert fx == VALUE


def test_two():
    assert 2 + 2 == 4
"""
CONFTEST = "import pytest\n\n\n@pytest.fixture\ndef fx():\n    return 1\n"
STD = {
    "tests/__init__.py": "",
    "tests/conftest.py": CONFTEST,
    "tests/test_a.py": TEST_A,
    "tests/sub/test_deep.py": "def test_deep(fx):\n    assert fx == 1\n",
    "helper/util.py": "VALUE = 1\n",
    "conftest.py": "import pytest\n\n\n@pytest.fixture\ndef root_fx():\n    return 0\n",
}
OLD_BASE = "deadbeef" * 5
WORKDIRS = []


def git(cwd, *args):
    result = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True,
                            encoding="utf-8", errors="replace", timeout=120)
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed in {cwd}: {result.stderr.strip()}")
    return result.stdout.strip()


def write(path, data="x"):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data if isinstance(data, bytes) else data.encode("utf-8"))
    return path


def commit_all(repo, message="c"):
    git(repo, "add", "-A")
    git(repo, "-c", "commit.gpgsign=false", "commit", "-q", "-m", message)


class Scn:
    """A throwaway repository with a project in `repo/proj`, committed, and (unless told not to)
    the S0 record taken at once - the state a story begins from."""

    def __init__(self, files=None, sub=SUB, record=True, gitignore="qa-factory/\n", autocrlf=False):
        self.base = temp_dir("qa-novelty-test-")
        WORKDIRS.append(self.base)
        self.repo = self.base / "repo"
        self.repo.mkdir()
        git(self.repo, "init", "-q", "-b", "main")
        if autocrlf:          # set BEFORE the first commit: blobs are LF, the checkout is CRLF
            git(self.repo, "config", "core.autocrlf", "true")
        write(self.repo / ".gitignore", gitignore)
        self.project = self.repo / sub if sub else self.repo
        write(self.project / "qa-factory" / "config.json", json.dumps({"tests_root": "tests"}))
        for name, data in (STD if files is None else files).items():
            if autocrlf and isinstance(data, str):
                data = data.replace("\n", "\r\n")
            write(self.project / name, data)
        commit_all(self.repo, "base")
        self.head = git(self.repo, "rev-parse", "HEAD")
        self.rec = self.take_record() if record else None

    def take_record(self):
        task = self.project / "qa-factory" / "artifacts" / "T-1"
        task.mkdir(parents=True, exist_ok=True)
        self.rec = TRB.record(task, self.project, {"tests_root": "tests"})
        self.head = self.rec.get("head") or self.head
        return self.rec

    def w(self, name, data):
        return write(self.project / name, data)

    def commit(self, message="story"):
        commit_all(self.repo, message)

    def m(self, test="tests/test_a.py", fn="test_one", record="rec", **kw):
        return NV.measure(self.project, test, fn, base_record=self.rec if record == "rec" else record,
                          **kw)


@contextlib.contextmanager
def without_git():
    empty = temp_dir("qa-nogit-")
    old = os.environ.get("PATH", "")
    os.environ["PATH"] = str(empty)
    try:
        yield
    finally:
        os.environ["PATH"] = old
        cleanup(empty)


def shape_ok(res):
    return (isinstance(res, dict) and set(res) == {"value", "basis", "base", "measured_on"}
            and res["value"] in ("new", "changed", "unchanged", "unknown")
            and isinstance(res["basis"], str) and res["basis"]
            and set(res["base"]) == {"kind", "sha"} and isinstance(res["measured_on"], dict))


def words_of(res):
    return res["basis"]


# =====================================================================================================
# 0. The measured function is the one the package already has; the record is the one P5-A writes
# =====================================================================================================
print("-- R2 shape and the S0 base")
s = Scn()
r = s.m()
check("R2: the answer has exactly value, basis, base{kind,sha}, measured_on", shape_ok(r))
check_eq("R2.1/V2: untouched since S0 -> unchanged", r["value"], "unchanged")
check_eq("R2.1: the base is the recorded S0 base with its commit", r["base"], {"kind": "s0", "sha": s.head})
check("R2.2: measured_on holds the test, its conftests and the project module it resolved, "
      "project-relative",
      {"tests/test_a.py", "tests/conftest.py", "helper/util.py"} <= set(r["measured_on"]),
      str(sorted(r["measured_on"])))
check("R2.2: measured_on holds the __init__ chain and the project-root conftest (V4)",
      {"tests/__init__.py", "conftest.py"} <= set(r["measured_on"]), str(sorted(r["measured_on"])))
check_eq("R2.2: measured_on is the RAW sha256 of each file's bytes",
         r["measured_on"]["helper/util.py"], NV._sha256_file(s.project / "helper" / "util.py"))
check_in("basis (unchanged): the words a person reads", "the test and everything it uses are the "
         f"same as at the story's base {s.head[:12]} (comments, blank lines and case markers do "
         "not count)", r["basis"])
UNCHANGED_WORDS = r["basis"]

# edits that change nothing the test runs
s.w("tests/test_a.py", TEST_A.replace("# a comment", "# another comment\n    # and one more")
    + "\n\n# trailing remark\n")
check_eq("R2.6/D-0017: a comment-only edit is unchanged (code_sha equal)", s.m()["value"], "unchanged")
s.w("tests/test_a.py", TEST_A.replace("def test_one", "@pytest.mark.qa(case=\"TC-1\", then=\"x\")\n"
                                      "def test_one"))
check_eq("R2.6/D-0019: a case-marker-only edit is unchanged", s.m()["value"], "unchanged")
s.w("tests/test_a.py", TEST_A.replace("assert 2 + 2 == 4", "assert 2 + 2 == 5"))
check_eq("R2.6 (per function): another test of the same file edited -> this one is unchanged",
         s.m(fn="test_one")["value"], "unchanged")
check_eq("R2.6: ... and the edited one is changed", s.m(fn="test_two")["value"], "changed")
# FB-10 (identity v2): the same measure follows the identity
s.w("tests/test_a.py", TEST_A + "\n\n# a new test\ndef test_three():\n    assert 3 == 3\n")
check_eq("K-N1: base vs now differing by an appended test only -> unchanged (both tests)",
         (s.m(fn="test_one")["value"], s.m(fn="test_two")["value"]), ("unchanged", "unchanged"))
s.w("tests/test_a.py", TEST_A + "\n\nimport pytest\n\n\n@pytest.fixture\ndef extra():\n    return 1\n"
    "\n\ndef test_three():\n    assert 3 == 3\n")
check_eq("K-N2: base vs now differing by an added module fixture (and a test) -> changed",
         (s.m(fn="test_one")["value"], s.m(fn="test_two")["value"]), ("changed", "changed"))
s.w("tests/test_a.py", TEST_A.replace("assert fx == VALUE", "assert fx == VALUE + 1"))
r = s.m()
check_eq("R2.6: a body edit is changed", r["value"], "changed")
check_in("basis (changed): names the first differing file", "first difference: tests/test_a.py",
         r["basis"])
CHANGED_WORDS = r["basis"]
s.w("tests/test_a.py", TEST_A)

# =====================================================================================================
print("-- V4 the measured set")
s.w("helper/util.py", "VALUE = 2\n")
r = s.m()
check_eq("R2.2: a project module the test imports, changed -> changed", r["value"], "changed")
check_in("basis names the module", "helper/util.py", r["basis"])
s.w("helper/util.py", "VALUE = 1\n")

s.w("tests/conftest.py", CONFTEST.replace("return 1", "return 2"))
r = s.m()
check_eq("V4: a conftest of the chain changed -> changed", r["value"], "changed")
check_in("V4: the basis names the conftest", "tests/conftest.py", r["basis"])
s.w("tests/conftest.py", CONFTEST)

# a conftest TWO levels above the test, outside the run's own chain (the run's cwd is the test's folder)
s.w("conftest.py", "import pytest\n\n\n@pytest.fixture\ndef root_fx():\n    return 99\n")
cwd = s.project / "tests" / "sub"
r = s.m(test="tests/sub/test_deep.py", fn="test_deep", run_cwd=cwd)
check_eq("V4: a conftest two levels up, above the run's cwd, changed -> changed", r["value"], "changed")
check_in("V4: the basis names it", "conftest.py", r["basis"])
chain = __import__("execution_request")._conftest_chain([cwd / "test_deep.py"], cwd)
check("V4 (why it matters): the run's own chain does NOT list that conftest", not any(
    Path(p) == s.project / "conftest.py" for p in chain), str(chain))
s.w("conftest.py", STD["conftest.py"])

s.w("tests/__init__.py", "MARK = 1\n")
r = s.m()
check_eq("V4: an __init__.py of the package path changed -> changed", r["value"], "changed")
check_in("V4: the basis names it", "tests/__init__.py", r["basis"])
s.w("tests/__init__.py", "")

# pytest configuration
s.w("pytest.ini", "[pytest]\naddopts = -q\n")
r = s.m()
check_eq("V4: a pytest.ini that did not exist at the base -> changed", r["value"], "changed")
check_in("V4: the basis names the configuration file", "pytest.ini", r["basis"])
s.w("pyproject.toml", "[project]\nname = \"x\"\n")
s.w("pytest.ini", "")
os.remove(s.project / "pytest.ini")
check_eq("V4: a pyproject.toml WITHOUT a pytest section is not pytest configuration -> unchanged",
         s.m()["value"], "unchanged")
os.remove(s.project / "pyproject.toml")

s2 = Scn(files=dict(STD, **{"pytest.ini": "[pytest]\naddopts = -q\n"}))
check_eq("V4: a committed pytest.ini, untouched -> unchanged", s2.m()["value"], "unchanged")
s2.w("pytest.ini", "[pytest]\naddopts = -q -x\n")
r = s2.m()
check_eq("V4: a pytest.ini that adds an option -> changed", r["value"], "changed")
check_in("V4: the basis names the configuration", "pytest.ini (the pytest configuration) changed",
         r["basis"])
s2.w("pytest.ini", "[pytest]\naddopts = -q\n")
check_eq("V4: the option removed again -> unchanged", s2.m()["value"], "unchanged")

s3 = Scn(files=dict(STD, **{"pyproject.toml": "[tool.pytest.ini_options]\naddopts = \"-q\"\n"}))
s3.w("pyproject.toml", "[tool.pytest.ini_options]\naddopts = \"-q\"\nmarkers = [\"a\"]\n")
check_eq("V4: a pyproject.toml with [tool.pytest...] edited -> changed", s3.m()["value"], "changed")

# files the base had and the tree no longer has
s4 = Scn()
os.remove(s4.project / "tests" / "conftest.py")
check_eq("V4: a conftest DELETED since the base -> changed (the mirror holds what the tree lost)",
         s4.m()["value"], "changed")
s4.commit("the story deletes it and commits the deletion")
check_eq("V4: ... and the deletion COMMITTED mid-story is still seen -> changed", s4.m()["value"],
         "changed")
s5 = Scn()
os.remove(s5.project / "helper" / "util.py")
check_eq("V4: an imported project module DELETED since the base -> changed", s5.m()["value"], "changed")
s6 = Scn()
os.remove(s6.project / "tests" / "__init__.py")
check_eq("V4: an __init__.py DELETED since the base -> changed", s6.m()["value"], "changed")

s7 = Scn(files=dict(STD, **{"conftest.py": "pytest_plugins = [\"some.plugin\"]\n"}))
r = s7.m()
check_eq("V4: a pytest_plugins module is a named residual: still unchanged", r["value"], "unchanged")
check_in("V4: ... and the basis says it is not covered", "pytest plugin modules (pytest_plugins) are "
         "not compared", r["basis"])
check_not_in("V4: the residual sentence is absent when no measured file names pytest_plugins",
             "pytest_plugins", UNCHANGED_WORDS)

# =====================================================================================================
print("-- R2.3 and R2.5: the file or function the base did not have")
s8 = Scn()
s8.w("tests/test_a.py", TEST_A + "\n\ndef test_three():\n    assert True\n")
r = s8.m(fn="test_three")
check_eq("R2.5: a function added to a tracked file -> new", r["value"], "new")
check_in("basis (new function)", f"the test function did not exist in its file at the story's "
         f"base {s8.head[:12]}", r["basis"])
NEW_FUNCTION_WORDS = r["basis"]
s8.w("tests/test_a.py", TEST_A.replace("def test_two", "def test_renamed"))
check_eq("R2.5: a renamed function -> new", s8.m(fn="test_renamed")["value"], "new")
s8.w("tests/test_a.py", TEST_A + "\n\nclass TestGroup:\n    def test_m(self, fx):\n        assert fx\n")
check_eq("R2.5: a method of a class the base did not have (class chain present now, absent at "
         "the base) -> new", s8.m(fn="test_m", class_chain=("TestGroup",))["value"], "new")
check_eq("R2.2: a class chain that is absent NOW is not measurable -> unknown",
         s8.m(fn="test_one", class_chain=("TestNothing",))["value"], "unknown")
s8.w("tests/test_b.py", "def test_b():\n    assert True\n")
r = s8.m(test="tests/test_b.py", fn="test_b")
check_eq("R2.3: a test file the base did not have (untracked) -> new", r["value"], "new")
check_in("basis (new file)", f"the test file did not exist at the story's base {s8.head[:12]}",
         r["basis"])
NEW_FILE_WORDS = r["basis"]
s8.commit("the story commits its own test")
r = s8.m(test="tests/test_b.py", fn="test_b")
check_eq("R2.3/V2: a test the story wrote AND COMMITTED is still new (it equals HEAD now, which "
         "is the trap)", r["value"], "new")
check_eq("R2.3: the same test against a HEAD-now base gives unknown, not unchanged",
         s8.m(test="tests/test_b.py", fn="test_b", record=None)["value"], "unknown")

# the base file does not parse
s9 = Scn(files=dict(STD, **{"tests/test_a.py": "def test_one(:\n"}))
s9.w("tests/test_a.py", TEST_A)
r = s9.m()
check_eq("R2.5: the base file does not parse -> unknown", r["value"], "unknown")
check_in("basis (base does not parse)", "does not parse as Python", r["basis"])

# =====================================================================================================
top = Scn(sub="")
check_eq("R2.1: a project at the repository top (prefix empty) -> unchanged", top.m()["value"], "unchanged")
top.w("helper/util.py", "VALUE = 2\n")
check_eq("R2.1: ... and its helper changed -> changed", top.m()["value"], "changed")
top.w("helper/util.py", "VALUE = 1\n")
os.remove(top.project / "tests" / "conftest.py")
check_eq("V4: ... and a deleted conftest at the repository top -> changed", top.m()["value"], "changed")

print("-- R2.1 which base; V2")
s = Scn()
check_eq("V2: no record -> head_now, and equal to HEAD -> unknown, never unchanged",
         s.m(record=None)["value"], "unknown")
r = s.m(record=None)
check_eq("R2.1: no record -> base kind head_now with the HEAD sha", r["base"],
         {"kind": "head_now", "sha": s.head})
check_eq("R2.7: the words for equal-to-HEAD-now", r["basis"], NV.WORDS_HEAD_NOW_EQUAL)
check_eq("R2.7: the words, verbatim", r["basis"], "equal to HEAD now, but no base was recorded when "
         "the story began: a test committed during the story would look the same")
HEAD_NOW_WORDS = r["basis"]
usable = dict(s.rec)
variants = {
    "an empty record {}": {},
    "git != ok (absent)": dict(usable, git="absent"),
    "git != ok (error)": dict(usable, git="error"),
    "an empty head": dict(usable, head=""),
    "late true": dict(usable, late=True),
    "dirty_truncated true": dict(usable, dirty_truncated=True),
    "a head that is not a commit name": dict(usable, head="--output=x"),
    "a dirty list that is not a list": dict(usable, dirty="nope"),
    "a dirty entry that is not an entry": dict(usable, dirty=[1]),
    "no `late` key at all": {k: v for k, v in usable.items() if k != "late"},
    "a non-dict record": ["not", "a", "dict"],
}
for label, rec in variants.items():
    r = s.m(record=rec)
    check(f"R2.1: {label} -> head_now, never unchanged", r["base"]["kind"] == "head_now"
          and r["value"] == "unknown" and shape_ok(r), str(r))
s.w("tests/test_a.py", TEST_A.replace("assert fx == VALUE", "assert fx == VALUE + 1"))
check_eq("R2.7: a changed test stays changed against HEAD now", s.m(record=None)["value"], "changed")
s.w("tests/test_a.py", TEST_A.replace("def test_two", "def test_renamed"))
check_eq("R2.7: a new function stays new against HEAD now", s.m(fn="test_renamed", record=None)["value"],
         "new")
s.w("tests/test_a.py", TEST_A)

print("-- R2.1 none: git does not answer")
s = Scn()
with without_git():
    r = s.m()
check_eq("R2.1: no git program -> unknown", r["value"], "unknown")
check_eq("R2.1: ... base kind none, no sha", r["base"], {"kind": "none", "sha": ""})
check_in("R2.1: the words", "git is not available here, so whether this test is new cannot be "
         "measured", r["basis"])
NONE_WORDS = r["basis"]
plain = temp_dir("qa-norepo-")
WORKDIRS.append(plain)
write(plain / "tests" / "test_a.py", "def test_one():\n    pass\n")
r = NV.measure(plain, "tests/test_a.py", "test_one", base_record=s.rec)
check("R2.1: a folder that is not a repository -> unknown, kind none",
      r["value"] == "unknown" and r["base"]["kind"] == "none" and "not inside a git repository"
      in r["basis"], str(r))
empty_repo = temp_dir("qa-emptyrepo-")
WORKDIRS.append(empty_repo)
git(empty_repo, "init", "-q", "-b", "main")
write(empty_repo / "tests" / "test_a.py", "def test_one():\n    pass\n")
r = NV.measure(empty_repo, "tests/test_a.py", "test_one", base_record=None)
check("R2.1: a repository with no commit -> unknown, kind none", r["value"] == "unknown"
      and r["base"]["kind"] == "none" and "no commit" in r["basis"], str(r))
r = s.m(record=dict(s.rec, head=OLD_BASE))
check_eq("R2.1: a base commit git cannot show -> unknown", r["value"], "unknown")
check_eq("R2.1: ... the kind stays s0 and names the commit", r["base"], {"kind": "s0", "sha": OLD_BASE})
check_in("R2.1: the words", "git cannot show the story's base " + OLD_BASE[:12], r["basis"])
BASE_GONE_WORDS = r["basis"]

# =====================================================================================================
print("-- R2.4 and V4 order: what was uncommitted at S0")
d = Scn(record=False)
d.w("tests/test_a.py", TEST_A.replace("assert fx == VALUE", "assert fx == VALUE + 10"))  # dirty at S0
d.w("helper/util.py", "VALUE = 5\n")                                                   # dirty helper
d.take_record()
check("R2.4: the record lists the files dirty at S0", {e["path"] for e in d.rec["dirty"]}
      >= {"proj/tests/test_a.py", "proj/helper/util.py"}, str(d.rec["dirty"]))
check_eq("R2.4: dirty at S0 and the same bytes now -> unchanged (the S0 bytes are the base)",
         d.m()["value"], "unchanged")
d.w("tests/test_a.py", TEST_A.replace("assert fx == VALUE", "assert fx == VALUE + 11"))
r = d.m()
check_eq("R2.4: dirty at S0 and different now -> changed", r["value"], "changed")
check_in("R2.4: the words", "tests/test_a.py changed since the story began", r["basis"])
DIRTY_WORDS = r["basis"]
d.w("tests/test_a.py", TEST_A)
check_eq("R2.4: dirty at S0, then reverted to HEAD -> changed (it is not what it was at S0)",
         d.m()["value"], "changed")
d.w("tests/test_a.py", TEST_A.replace("assert fx == VALUE", "assert fx == VALUE + 10"))
d.w("helper/util.py", "VALUE = 6\n")
r = d.m()
check_eq("R2.4: a DIRTY HELPER changed since S0 -> changed", r["value"], "changed")
check_in("R2.4: the words name the helper", "helper/util.py changed since the story began", r["basis"])

u = Scn(record=False)
u.w("tests/conftest.py", CONFTEST.replace("return 1", "return 3"))          # modified, uncommitted
u.w("tests/conftest2_helper.py", "X = 1\n")
u.w("tests/test_c.py", "def test_c(fx):\n    assert fx\n")                   # untracked at S0
u.take_record()
check_eq("V4: a test untracked at S0 and unchanged since -> new (it did not exist at the base)",
         u.m(test="tests/test_c.py", fn="test_c")["value"], "new")
u.commit("mid-story commit")
r = u.m(test="tests/test_c.py", fn="test_c")
check_eq("V4/R2.3: untracked at S0, NOW TRACKED and equal to HEAD -> new, never unchanged",
         r["value"], "new")
check_eq("R2.4: a tracked file modified at S0, committed mid-story with the same bytes -> unchanged",
         u.m()["value"], "unchanged")

v = Scn(record=False)
v.w("tests/conftest.py", CONFTEST.replace("fx", "fx").replace("return 1", "return 1\n"))
write(v.project / "tests" / "sub" / "conftest.py", "import pytest\n")            # untracked helper at S0
v.take_record()
r = v.m(test="tests/sub/test_deep.py", fn="test_deep")
check_eq("V4 ORDER: a HELPER untracked at S0, unchanged since -> changed, never unchanged",
         r["value"], "changed")
check_in("V4 ORDER: the words say it did not exist at the base", "did not exist at the story's base "
         + v.head[:12], r["basis"])
UNTRACKED_WORDS = r["basis"]
v.commit("mid-story commit")
r = v.m(test="tests/sub/test_deep.py", fn="test_deep")
check_eq("V4 ORDER: that helper NOW TRACKED and equal to HEAD -> changed (it did not exist at the "
         "base)", r["value"], "changed")

g = Scn(record=False)
os.remove(g.project / "helper" / "util.py")                                    # deleted at S0
g.take_record()
check_eq("R2.4: a file deleted at S0 and still deleted -> the S0 state is absent: unchanged here "
         "(the test does not use it)", g.m(test="tests/sub/test_deep.py", fn="test_deep")["value"],
         "unchanged")
g.w("helper/util.py", "VALUE = 1\n")
check_eq("R2.4: ... restored since S0 and imported by the test -> changed",
         g.m()["value"], "changed")

lost = Scn(record=False)
lost.w("helper/other.py", "Y = 1\n")
lost.commit("other")
lost.w("helper/other.py", "Y = 2\n")                                            # modified at S0
lost.take_record()
os.remove(lost.project / "helper" / "other.py")
r = lost.m()
check("R2.4: a file modified at S0 and deleted since: its S0 bytes are gone -> changed (costly "
      "direction, never unchanged)", r["value"] == "changed" and "helper/other.py" in r["basis"],
      str(r))

# =====================================================================================================
print("-- R2.2 and R2.3: the file is not measurable, ignored, a link, outside")
s = Scn(files=dict(STD, **{
    "tests/test_dyn.py": "for _i in range(2):\n    globals()[f'test_g{_i}'] = lambda: None\n",
    "tests/test_x.js": "test('x', () => {})\n",
    "tests/test_bad.py": b"def test_bad():\n    x = '\xff\xfe'\n    assert x\n",
    "tests/test_syntax.py": "def test_s(:\n"}))
r = s.m(test="tests/test_dyn.py", fn="test_g0")
check_eq("R2.2: a function pytest generates at import time (scope file) -> unknown", r["value"],
         "unknown")
check_in("R2.2: the words", "the test's code cannot be measured (not Python, not UTF-8, or it does "
         "not tokenize)", r["basis"])
UNMEASURABLE_WORDS = r["basis"]
r = s.m(test="tests/test_x.js", fn="x")
check("R2.2: a non-Python file -> unknown", r["value"] == "unknown" and r["basis"] == UNMEASURABLE_WORDS,
      str(r))
r = s.m(test="tests/test_bad.py", fn="test_bad")
check("R2.2: a file that is not UTF-8 -> unknown", r["value"] == "unknown"
      and r["basis"] == UNMEASURABLE_WORDS, str(r))
r = s.m(test="tests/test_syntax.py", fn="test_s")
check("R2.2: a file that does not parse -> unknown", r["value"] == "unknown"
      and r["basis"] == UNMEASURABLE_WORDS, str(r))
r = s.m(test="tests/test_missing.py", fn="test_s")
check("R2.2: a test file that does not exist now -> unknown, with the reason", r["value"] == "unknown"
      and "does not exist now" in r["basis"], str(r))

ig = Scn(gitignore="qa-factory/\ntest_ignored.py\n")
write(ig.project / "tests" / "test_ignored.py", "def test_i():\n    assert True\n")
r = ig.m(test="tests/test_ignored.py", fn="test_i")
check_eq("R2.3: a test file ignored by git -> unknown (not new: an ignored file has no base)",
         r["value"], "unknown")
check_eq("R2.3: the words", r["basis"], "the file is ignored by git; its state before the story is "
         "unknown")
IGNORED_WORDS = r["basis"]
write(ig.project / "tests" / "test_fresh.py", "def test_f():\n    assert True\n")
check_eq("R2.3: a file that is NOT ignored and absent at the base is new (the control of the "
         "previous check: the same call shape, a different verdict)",
         ig.m(test="tests/test_fresh.py", fn="test_f")["value"], "new")

# symlink
sl = Scn()
linked = False
try:
    os.symlink(str(sl.project / "tests" / "test_a.py"), str(sl.project / "tests" / "test_link.py"))
    linked = True
except (OSError, NotImplementedError, AttributeError):
    pass
if linked:
    r = sl.m(test="tests/test_link.py", fn="test_one")
    check("edge: a symlinked test file -> unknown with the reason, no exception",
          r["value"] == "unknown" and "symbolic link" in r["basis"], str(r))
else:
    real_islink = os.path.islink
    target = str(sl.project / "tests" / "test_a.py")
    # compared by real path: a TEMP given as a Windows 8.3 short name (C:\Users\DEV2~1\...) reaches the product in its long form
    real_target = os.path.normcase(os.path.realpath(target))
    NV.os.path.islink = lambda p: os.path.normcase(os.path.realpath(str(p))) == real_target or real_islink(p)
    try:
        r = sl.m(test="tests/test_a.py", fn="test_one")
    finally:
        NV.os.path.islink = real_islink
    check("edge: a symlinked test file (this machine cannot create links: the link test is forced) "
          "-> unknown with the reason", r["value"] == "unknown" and "symbolic link" in r["basis"], str(r))
SYMLINK_WORDS = r["basis"]

# outside the repository top
out = Scn()
elsewhere = temp_dir("qa-elsewhere-")
WORKDIRS.append(elsewhere)
write(elsewhere / "shared_helper.py", "Z = 1\n")
out.w("tests/test_a.py", TEST_A)
r = out.m(extra_files=[str(elsewhere / "shared_helper.py")])
check("edge: an extra file outside the repository top -> unknown, words say so",
      r["value"] == "unknown" and "lies outside the test repository" in r["basis"], str(r))
OUTSIDE_WORDS = r["basis"]
r = out.m(extra_files=[str(out.project / "helper" / "util.py")])
check_eq("edge: an extra file INSIDE the repository is part of the measured set (control)",
         r["value"], "unchanged")
out.w("helper/util.py", "VALUE = 7\n")
check_eq("edge: ... and its change is seen", out.m(extra_files=[str(out.project / "helper" / "util.py")])["value"],
         "changed")

# =====================================================================================================
print("-- edges: paths")
sp = Scn(files={"my tests/__init__.py": "", "my tests/test a.py": "def test_one():\n    assert 1 == 1\n"})
check_eq("edge: a path with spaces -> measured (unchanged)", sp.m(test="my tests/test a.py")["value"],
         "unchanged")
sp.w("my tests/test a.py", "def test_one():\n    assert 1 == 2\n")
check_eq("edge: a path with spaces -> measured (changed)", sp.m(test="my tests/test a.py")["value"],
         "changed")
sp2 = Scn(files={"my tests/test a.py": "def test_one():\n    assert 1 == 1\n"})
sp2.w("my tests/test b.py", "def test_b():\n    assert True\n")
check_eq("edge: a path with spaces, untracked -> new", sp2.m(test="my tests/test b.py", fn="test_b")["value"],
         "new")
win = Scn()
if os.name == "nt":
    r = win.m(test="tests\\test_a.py")
    check_eq("edge: a Windows relative path with backslashes -> measured", r["value"], "unchanged")
    absolute = str(win.project / "tests" / "test_a.py")
    check("edge: the path has a drive letter and backslashes", absolute[1:3] == ":\\", absolute)
    r = win.m(test=absolute)
    check_eq("edge: a Windows absolute path with a drive letter -> measured", r["value"], "unchanged")
    r = win.m(test="Z:\\no\\such\\dir\\test_a.py")
    check("edge: a drive that is not there -> unknown with the reason, no exception",
          r["value"] == "unknown" and shape_ok(r), str(r))
    check_eq("edge: a Windows path spelled in the other case -> measured",
             win.m(test=absolute.upper())["value"], "unchanged")
else:
    check_eq("edge: an absolute path -> measured", win.m(test=str(win.project / "tests" / "test_a.py"))["value"],
             "unchanged")
check_eq("edge: a path with an embedded NUL -> unknown, no exception",
         win.m(test="tests/test_a.py\0x")["value"], "unknown")
check("edge: a test path that climbs out of the project into another folder -> unknown, no exception",
      win.m(test="../../../../nothing/there.py")["value"] == "unknown")

print("-- edges: malformed requests never raise")
bad_items = [None, 5, "x", {}, {"test_rel": ""}, {"test_rel": "tests/test_a.py"},
             {"test_rel": "tests/test_a.py", "function": ""},
             {"test_rel": "tests/test_a.py", "function": "test_one", "class_chain": "TestA"},
             {"test_rel": "tests/test_a.py", "function": "test_one", "class_chain": [1]},
             {"test_rel": "tests/test_a.py", "function": "test_one", "extra_files": [None]},
             {"test_rel": 5, "function": "test_one"}]
rs = NV.measure_many(win.project, bad_items, base_record=win.rec)
check("edge: malformed items -> one unknown each, in order, never an exception",
      len(rs) == len(bad_items) and all(x["value"] == "unknown" and shape_ok(x) for x in rs),
      str(rs)[:400])
check_eq("edge: measure_many of an empty list -> []", NV.measure_many(win.project, [], base_record=win.rec), [])
check_eq("edge: measure_many of an empty tuple -> []", NV.measure_many(win.project, (), base_record=win.rec), [])
rs = NV.measure_many(win.project, [{"test_rel": "tests/test_a.py", "function": "test_one"}, None,
                                   {"test_rel": "tests/test_a.py", "function": "test_two"}],
                     base_record=win.rec)
check("edge: one bad item among good ones does not hide the others, order kept",
      [x["value"] for x in rs] == ["unchanged", "unknown", "unchanged"], str([x["value"] for x in rs]))
check_eq("edge: measure_many over a non-iterable -> one unknown, no exception",
         len(NV.measure_many(win.project, 5, base_record=win.rec)), 1)
check_eq("edge: a project root that is not a string -> unknown, no exception",
         NV.measure(None, "tests/test_a.py", "test_one")["value"], "unknown")
check_eq("edge: a project root that does not exist -> unknown, no exception",
         NV.measure(win.base / "nope", "tests/test_a.py", "test_one")["value"], "unknown")

real_git = NV._git


def exploding_git(*a, **k):
    raise RuntimeError("boom")


NV._git = exploding_git
try:
    r = win.m()
finally:
    NV._git = real_git
check("R2: an exception anywhere -> unknown with the exception class in the basis",
      r["value"] == "unknown" and "RuntimeError" in r["basis"] and shape_ok(r), str(r))
real_fs = FP.function_sha


def exploding_fs(*a, **k):
    raise ValueError("boom")


FP.function_sha = exploding_fs
made = []
real_mkdtemp = tempfile.mkdtemp


def spy_mkdtemp(*a, **k):
    path = real_mkdtemp(*a, **k)
    made.append(path)
    return path


NV.tempfile.mkdtemp = spy_mkdtemp
try:
    r = win.m()
finally:
    FP.function_sha = real_fs
    NV.tempfile.mkdtemp = real_mkdtemp
check("R2: an exception inside the measurement -> unknown with its class", r["value"] == "unknown"
      and "ValueError" in r["basis"], str(r))
check("R2.5: the mirror is removed in `finally` even when the measurement raised",
      len(made) == 1 and not os.path.exists(made[0]), str(made))

# =====================================================================================================
print("-- R2.1 the run's cwd")
root = win.project
path, how = NV.resolve_run_cwd(root, "tests/test_a.py", root / "tests")
check("run_cwd given -> used as it is, `given`", (path, how) == (Path(os.path.abspath(root / "tests")), "given"),
      str((path, how)))
path, how = NV.resolve_run_cwd(root, "tests/test_a.py")
check("run_cwd None, no configuration profile -> the project root, `project_root`",
      (path, how) == (Path(os.path.abspath(root)), "project_root"), str((path, how)))
cfg = {"profiles": [{"profile_id": "p", "roots": {"test": "tests"}, "commands": {"one_test": {"cwd": "tests"}}}]}
path, how = NV.resolve_run_cwd(root, "tests/test_a.py", None, cfg)
check("run_cwd None, a profile owns the file -> derived through probe_by_code._profile_cwd, `profile`",
      (path, how) == (Path(os.path.abspath(root / "tests")), "profile"), str((path, how)))
path, how = NV.resolve_run_cwd(root, "other/test_a.py", None, cfg)
check("run_cwd None, no profile owns the file -> the project root", how == "project_root", str((path, how)))
saved = sys.modules.get("probe_by_code")
sys.modules["probe_by_code"] = None          # an import of it now raises ImportError
try:
    path, how = NV.resolve_run_cwd(root, "tests/test_a.py", None, cfg)
finally:
    if saved is None:
        del sys.modules["probe_by_code"]
    else:
        sys.modules["probe_by_code"] = saved
check("run_cwd None, probe_by_code not importable -> the project root", how == "project_root",
      str((path, how)))

# =====================================================================================================
print("-- line endings")
cr = Scn(autocrlf=True, files=dict(STD, **{"pytest.ini": "[pytest]\naddopts = -q\n"}))
blob = git(cr.repo, "show", "HEAD:proj/tests/test_a.py")
check("CRLF (setup): the working file is CRLF and the committed blob is LF",
      b"\r\n" in (cr.project / "tests" / "test_a.py").read_bytes() and "\r" not in blob)
check_eq("CRLF: a CRLF checkout of an LF blob (autocrlf, a clean tree) is the same test -> "
         "unchanged (the base is fetched raw)", cr.m()["value"], "unchanged")
check("CRLF: the clean autocrlf tree has nothing dirty at S0", cr.rec["dirty"] == [], str(cr.rec["dirty"]))
cr.w("pytest.ini", "[pytest]\r\naddopts = -q\r\n")
check_eq("CRLF: a pytest.ini with different line endings only is the same configuration -> unchanged",
         cr.m()["value"], "unchanged")
cr.w("pytest.ini", "[pytest]\r\naddopts = -q -x\r\n")
check_eq("CRLF: ... and a real option change is still changed", cr.m()["value"], "changed")
cr2 = Scn()
cr2.w("tests/test_a.py", TEST_A.replace("\n", "\r\n"))
check_eq("CRLF: only the line endings of the file changed -> unchanged (read_text normalises)",
         cr2.m()["value"], "unchanged")

# =====================================================================================================
print("-- V3: one mirror, one batch process, one parse per file")
many = {"tests/__init__.py": "", "tests/conftest.py": CONFTEST, "helper/util.py": "VALUE = 1\n",
        "tests/test_many.py": "from helper.util import VALUE\n\n\n" + "\n\n".join(
            f"def test_f{i:03d}(fx):\n    assert fx == VALUE\n" for i in range(20))}
b = Scn(files=many)
items20 = [{"test_rel": "tests/test_many.py", "function": f"test_f{i:03d}"} for i in range(20)]
b.m(test="tests/test_many.py", fn="test_f000")          # warm-up: imports are paid by neither side
# Best of three / two: a wall-clock bound on a busy machine is measured on the run the machine
# disturbed least (FR-31) - the bound itself is not loosened.
single, t_single = None, 1e9
for _ in range(3):
    t0 = time.perf_counter()
    single = b.m(test="tests/test_many.py", fn="test_f000")
    t_single = min(t_single, time.perf_counter() - t0)
batch, t_many = None, 1e9
for _ in range(2):
    t0 = time.perf_counter()
    batch = NV.measure_many(b.project, items20, base_record=b.rec)
    t_many = min(t_many, time.perf_counter() - t0)
print(f"     measure (1 function, best of 3): {t_single:.3f} s   measure_many (20 functions, one "
      f"file, best of 2): {t_many:.3f} s   ratio {t_many / t_single:.2f}")


def counted(call):
    """-> (result, sorted git subcommands run, mirror directories made) of one call."""
    git_seen, mirrors, real_g, real_mk = [], [], NV._git, NV.tempfile.mkdtemp

    def g(cwd, args, stdin=None):
        git_seen.append(args[0])
        return real_g(cwd, args, stdin)

    def mk(*a, **k):
        mirrors.append(real_mk(*a, **k))
        return mirrors[-1]
    NV._git, NV.tempfile.mkdtemp = g, mk
    try:
        out = call()
    finally:
        NV._git, NV.tempfile.mkdtemp = real_g, real_mk
    return out, sorted(git_seen), len(mirrors)


# The old key here was a wall-clock ratio (20 functions in under 3x one measure). It held on Windows
# only because there a process start is dear and the fixed cost of a call (the mirror, the git
# processes) dominates; on the Linux runner (B-301 d) the fixed cost is small, the per-function work
# shows, and the same code gave 4x on a quiet machine (0.018 s against 0.077 s) - the ratio measured
# the platform, not the batch. What "batched" means is that the fixed cost is paid once, whatever the
# number of functions: the same git subcommands, the same one mirror, for 1 function and for 20.
one_out, one_git, one_mirrors = counted(lambda: b.m(test="tests/test_many.py", fn="test_f000"))
many_out, many_git, many_mirrors = counted(lambda: NV.measure_many(b.project, items20, base_record=b.rec))
check("V3: measure_many of 20 functions of one file makes the git calls and the one mirror of a single "
      f"measure, not 20 times them (single {one_git} x{one_mirrors} mirror, many {many_git} x{many_mirrors} "
      f"mirror; wall clock for the record: single {t_single:.3f} s, many {t_many:.3f} s)",
      many_git == one_git and many_mirrors == one_mirrors == 1,
      f"{many_git} x{many_mirrors} vs {one_git} x{one_mirrors}")
check("V3: all 20 answers are unchanged, in order", [x["value"] for x in batch] == ["unchanged"] * 20)
check_eq("V3: measure is measure_many with one item", single, batch[0])
check_eq("V3: each item's measured_on is its own (the same files here)", batch[3]["measured_on"],
         batch[0]["measured_on"])

# The 1,000-item run uses a file with no imports and no fixtures: `function_sha` stats a dozen
# candidate paths per import per call (about a millisecond each here), which would make this one
# check a minute long without telling anything new about the mirror, the process or the cache.
lean = Scn(files={"tests/test_lean.py": "\n\n".join(
    f"def test_f{i:03d}():\n    assert {i} == {i}\n" for i in range(20))})
calls, made, parsed = [], [], {}
real_git, real_mkdtemp, real_module = NV._git, tempfile.mkdtemp, FP._Module


def spy_git(cwd, args, stdin=None):
    calls.append(args[0])
    return real_git(cwd, args, stdin)


class CountingModule(real_module):
    def __init__(self, path):
        parsed[str(path)] = parsed.get(str(path), 0) + 1
        super().__init__(path)


NV._git, NV.tempfile.mkdtemp, FP._Module = spy_git, spy_mkdtemp, CountingModule
try:
    items1000 = [{"test_rel": "tests/test_lean.py", "function": f"test_f{i % 20:03d}"}
                 for i in range(1000)]
    t0 = time.perf_counter()
    big = NV.measure_many(lean.project, items1000, base_record=lean.rec)
    t_big = time.perf_counter() - t0
finally:
    NV._git, NV.tempfile.mkdtemp, FP._Module = real_git, real_mkdtemp, real_module
print(f"     measure_many (1,000 items, one file): {t_big:.2f} s; git calls: {sorted(set(calls))} "
      f"x{len(calls)}; parsed files: {len(parsed)}")
check("V3: 1,000 items of one file -> all answered, all unchanged", len(big) == 1000
      and all(x["value"] == "unchanged" for x in big))
check_eq("V3/mutation h: ONE mirror for the whole call", len(made), 1)
check_eq("V3: ONE `cat-file --batch` process for the whole call", calls.count("cat-file"), 1)
check_eq("V3: ONE `ls-tree`, ONE `check-ignore`, ONE `diff` (deleted files) for the whole call",
         (calls.count("ls-tree"), calls.count("check-ignore"), calls.count("diff")), (1, 1, 1))
check("V3/mutation h: one parse cache shared by all items - no file is parsed twice on a side",
      parsed and max(parsed.values()) == 1, str(parsed))
check("V3: 1,000 items of one file finish in well under 1,000 single measures "
      f"({t_big:.1f} s against about {t_single * 1000:.0f} s)", t_big < 10 * t_single + 30,
      f"{t_big:.1f} s")
check("R2.5: the mirror of the 1,000-item call was removed", made and not os.path.exists(made[0]))

two = Scn()
other = temp_dir("qa-other-repo-")
WORKDIRS.append(other)
git(other, "init", "-q", "-b", "main")
write(other / "t" / "test_o.py", "def test_o():\n    assert True\n")
commit_all(other, "o")
made.clear()
NV.tempfile.mkdtemp = spy_mkdtemp
try:
    rs = NV.measure_many(two.project, [{"test_rel": "tests/test_a.py", "function": "test_one"},
                                       {"test_rel": str(other / "t" / "test_o.py"), "function": "test_o"}],
                         base_record=two.rec)
finally:
    NV.tempfile.mkdtemp = real_mkdtemp
check("V3: items of two repositories: each is judged against its own repository, ONE mirror root",
      rs[0]["value"] == "unchanged" and rs[1]["value"] == "unknown" and rs[1]["base"]["kind"] == "s0"
      and len(made) == 1, str(rs))

# =====================================================================================================
print("-- the words, one per outcome")
for name, words in [("unchanged", UNCHANGED_WORDS), ("changed (a file differs)", CHANGED_WORDS),
                    ("changed (dirty at S0)", DIRTY_WORDS), ("changed (untracked at S0)", UNTRACKED_WORDS),
                    ("new (file)", NEW_FILE_WORDS), ("new (function)", NEW_FUNCTION_WORDS),
                    ("unknown (head now)", HEAD_NOW_WORDS), ("unknown (no git)", NONE_WORDS),
                    ("unknown (base gone)", BASE_GONE_WORDS), ("unknown (ignored)", IGNORED_WORDS),
                    ("unknown (not measurable)", UNMEASURABLE_WORDS),
                    ("unknown (outside)", OUTSIDE_WORDS), ("unknown (link)", SYMLINK_WORDS)]:
    print(f"     {name}: {words}")
    check(f"FR-6: the {name} words carry no field name, script name or stage id",
          not any(bad in words for bad in ("novelty", "measured_on", ".py --", "S5", "S0", "P5", "R2")),
          words)

check(f"R2.5: every mirror of this whole file ({len(ALL_MIRRORS)} of them, one per measure call) was "
      "removed", ALL_MIRRORS and not any(os.path.exists(p) for p in ALL_MIRRORS),
      str([p for p in ALL_MIRRORS if os.path.exists(p)][:3]))
for scn in WORKDIRS:
    cleanup(scn)
finish("test_novelty")
