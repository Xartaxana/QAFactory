"""The blast-radius index by code (G1-2): `work/blast-radius.json` from the implementation diff, the manifest, git OBJECTS of the recorded
commit and the project's test roots.

Edges (spec t-1190 sections 2, 3, 4, L): a symbol comes from the new tree by `ast` (the hunk header is never read), a caller needs a
found site, an empty list only after a search that ran to its end (else `unmeasured: <reason>` + `tests_gap` + `shared_path`), the
join and the sha form are the table's, ids are kept by key and never reissued, ONE writer, the file the table reads (`grounding_table`).
Mutation killers (one test file, this one, except M13 / M14 / M15): see the tail of the section names (M1..M12).
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import SCRIPTS, check, check_eq, cleanup, finish, run_script, temp_project, use_project  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import blast_radius as BR  # noqa: E402
import diff_pass as DP  # noqa: E402
import grounding_table as GT  # noqa: E402
import planning_contract as PC  # noqa: E402
import test_novelty as TN  # noqa: E402

REAL = Path(__file__).resolve().parents[4] / "experiments" / "TP1-13877"
GIT_ENV = dict(os.environ, GIT_TERMINAL_PROMPT="0", GIT_CONFIG_NOSYSTEM="1", GIT_AUTHOR_NAME="ci", GIT_AUTHOR_EMAIL="ci@x",
               GIT_COMMITTER_NAME="ci", GIT_COMMITTER_EMAIL="ci@x")
REAL_GIT = TN._git
CALLS: list = []


def git(cwd, *args, stdin=None) -> bytes:
    env = {k: v for k, v in GIT_ENV.items() if k not in ("GIT_DIR", "GIT_WORK_TREE")}
    done = subprocess.run(["git", "-c", "core.autocrlf=false", *args], cwd=str(cwd), env=env, input=stdin, capture_output=True)
    assert done.returncode == 0, (args, done.stderr)
    return done.stdout


def watch(handler=None) -> None:
    """Record every git call of `test_novelty._git` (the one runner); `handler(cwd, args, stdin)` may answer instead (None = run it)."""
    def wrapped(cwd, args, stdin=None):
        CALLS.append((Path(str(cwd)).resolve(), list(args)))
        if handler is not None:
            answer = handler(cwd, args, stdin)
            if answer is not None:
                return answer
        return REAL_GIT(cwd, args, stdin)
    TN._git = wrapped
    CALLS.clear()


def unwatch() -> None:
    TN._git = REAL_GIT
    CALLS.clear()


def calls_in(repo) -> list:
    return [args for cwd, args in CALLS if cwd == Path(str(repo.dir)).resolve()]


class Repo:
    def __init__(self, parent=None, sha256=False):
        self.dir = Path(tempfile.mkdtemp(prefix="qa-br-repo-", dir=parent))
        self.shared = False
        git(self.dir, "init", "-q", *(["--object-format=sha256"] if sha256 else []))

    def head(self) -> str:
        """HEAD's commit read from the loose ref the commit just wrote (a process fewer: a git call costs ~0.3 s on a slow machine)."""
        ref = (self.dir / ".git" / "HEAD").read_text(encoding="ascii").strip()
        return (self.dir / ".git" / ref[5:]).read_text(encoding="ascii").strip() if ref.startswith("ref: ") else ref

    def commit(self, files: dict, message="c") -> str:
        for name, data in files.items():
            target = self.dir / name
            if data is None:
                target.unlink()
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data if isinstance(data, bytes) else data.encode("utf-8"))
        git(self.dir, "add", "-A")
        git(self.dir, "commit", "-q", "--allow-empty", "-m", message)
        return self.head()

    def diff(self, a, b) -> bytes:
        return git(self.dir, "diff", "-M", a, b)


class Story:
    """A temporary project with one story `T-1`: pipeline, diffs, manifest, config (the checkouts), no register."""

    def __init__(self, source="diff", tests_root="tests"):
        self.root = temp_project("qa-br-")
        use_project(self.root)
        self.task = self.root / "qa-factory" / "artifacts" / "T-1"
        (self.task / "work").mkdir(parents=True)
        pipe = {"ticket": "T-1", "stages": {}}
        if source is not None:
            pipe["implementation_source"] = source
        (self.task / "pipeline.json").write_bytes(json.dumps(pipe).encode())
        self.cfg = {"implementation_repos": [], "tests_root": tests_root}
        self.entries = {}

    def checkout(self, repo_id, path):
        self.cfg["implementation_repos"] = [r for r in self.cfg["implementation_repos"] if r["repo_id"] != repo_id] + [
            {"repo_id": repo_id, "local_path": str(path)}]

    def set_diff(self, diff, sha, name="impl-diff.txt", repo_id="backend", **extra):
        (self.task / "work" / name).write_bytes(diff if isinstance(diff, bytes) else diff.encode("utf-8"))
        entry = {"repo_id": repo_id, "source": "diff", "diff_path": f"qa-factory/artifacts/T-1/work/{name}", "source_sha": sha}
        entry.update(extra)
        self.entries[name] = entry
        self.manifest(list(self.entries.values()))

    def manifest(self, entries):
        (self.task / "work" / "context-manifest.json").write_bytes(json.dumps({"implementations": entries}).encode())

    def write(self, rel, data):
        target = self.task / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data if isinstance(data, bytes) else data.encode("utf-8"))

    def build(self, prior=None):
        return BR.build(self.task, prior, project=self.root, cfg=self.cfg)

    def ensure(self, **kw):
        return BR.ensure(self.task, project=self.root, cfg=self.cfg, **kw)

    @property
    def file(self) -> Path:
        return self.task / "work" / "blast-radius.json"

    def run(self, *args, task="T-1"):
        env = dict(os.environ, CLAUDE_PROJECT_DIR=str(self.root), PYTHONDONTWRITEBYTECODE="1")
        return run_script("blast_radius.py", "--task", task, *args, cwd=self.root, env=env)

    def done(self):
        cleanup(self.root)


def area(doc, path, nth=0):
    found = [a for a in doc["areas"] if a["touched"]["file"] == path]
    return found[nth] if len(found) > nth else {"touched": {"symbols": []}, "callers": None, "tests": None, "path_kind": None}


def names(doc, path):
    symbols = area(doc, path)["touched"]["symbols"]
    return [s["name"] for s in symbols] if isinstance(symbols, list) else symbols


def starts(value, text):
    """A mutated builder may return a list where the text belongs: that is a failed check, not a crash."""
    return isinstance(value, str) and value.startswith(text)


def sites(a, field="callers"):
    value = a[field]
    return [(c["file"] if "file" in c else c["ref"], c["line"]) for c in value] if isinstance(value, list) else value


def one(base_files, impl_files, tests_root="tests", sha256=False, **extra):
    """A repo with two commits and a story over `git diff base impl`: (repo, story, base, impl)."""
    repo = Repo(sha256=sha256)
    base = repo.commit(base_files)
    impl = repo.commit(impl_files)
    story = Story(tests_root=tests_root)
    story.checkout("backend", repo.dir)
    story.set_diff(repo.diff(base, impl), impl, **extra)
    return repo, story, base, impl


def done_all(*items):
    for item in items:
        if isinstance(item, Story):
            item.done()
        elif not item.shared:
            cleanup(item.dir)


MOD ="def f(x):\n    return x\n\n\ndef g(x):\n    return x\n"
USE1 = "from mod import f\n\n\ndef a():\n    return f(1)\n"
USE2 = "import mod\n\n\ndef b():\n    return mod.f(2)\n"
TEST = "from mod import f\n\n\ndef test_f():\n    assert f(1) == 1\n"

# --- B1 / M12: a modified function with two callers and a test; the pattern file does not stay behind -------------------------
private = Path(tempfile.mkdtemp(prefix="qa-br-tmp-"))
repo, story, base, impl = one({"src/mod.py": MOD, "src/use1.py": USE1, "src/use2.py": USE2, "tests/test_mod.py": TEST},
                              {"src/mod.py": MOD.replace("    return x\n\n\ndef g", "    return x + 1\n\n\ndef g")})
old_tmp, tempfile.tempdir = tempfile.tempdir, str(private)
try:
    before = sorted(p.name for p in private.iterdir())
    doc = story.build()
    after = sorted(p.name for p in private.iterdir())
finally:
    tempfile.tempdir = old_tmp
check_eq("B1: the temp folder listing is equal before and after the build (M12: the pattern file is removed)", after, before)
a = area(doc, "src/mod.py")
check_eq("B1: ONE area, the symbol f modified (by ast, not the header)", (len(doc["areas"]), names(doc, "src/mod.py"), a["touched"]["symbols"][0]["status"]),
         (1, ["f"], "modified"))
check_eq("B1: the two callers as file:line (own def line skipped)", sites(a), [("src/use1.py", 1), ("src/use1.py", 5), ("src/use2.py", 5)])
check_eq("B1: the test site in the checkout (repo_scan), the test's own name is no site", sites(a, "tests"), [("tests/test_mod.py", 1), ("tests/test_mod.py", 5)])
check_eq("B1: shared_path / callers_found, no gap, one repo matched at the commit",
         (a["path_kind"], a["path_kind_why"], a["tests_gap"], a["truncated"], doc["index"]["repos"][0]["state"]), ("shared_path", "callers_found", "", "no", "match"))
check_eq("B1: callers carry repo, symbol and in_diff", a["callers"][0], {"file": "src/use1.py", "line": 1, "symbol": "f", "repo": "", "in_diff": "no"})
check_eq("B1: tests carry their source", [t["source"] for t in a["tests"]], ["repo_scan", "repo_scan"])
check_eq("B1: the index records the commit state, the head and the diff sha",
         (doc["index"]["repos"][0]["head"], doc["index"]["diffs"][0]["sha256"] == hashlib.sha256((story.task / "work" / "impl-diff.txt").read_bytes()).hexdigest(),
          doc["index"]["schema"], doc["retired_ids"], [x["id"] for x in doc["areas"]]), (impl, True, 1, [], ["B-1"]))
done_all(repo, story)
shutil.rmtree(private, ignore_errors=True)

# --- B2: a new file imported only by a diff file is additive; the importer is not --------------------------------------------------
A_BASE = "def run():\n    return 1\n"
repo, story, base, impl = one({"src/a.py": A_BASE}, {"src/a.py": "from newmod import helper\n\n\ndef run():\n    return helper()\n",
                                                        "src/newmod.py": "def helper():\n    return 1\n"})
doc = story.build()
n = area(doc, "src/newmod.py")
check_eq("B2: the new file is additive (every symbol new, its only callers sit on added lines)", (n["path_kind"], n["path_kind_why"], n["touched"]["change"]),
         ("additive", "new_no_outside_caller", "added"))
check_eq("B2: ...its callers are in_diff: added", sorted({c["in_diff"] for c in n["callers"]}), ["added"])
check_eq("B2: ...and the importer (a modified existing file) is shared_path", (area(doc, "src/a.py")["path_kind"], area(doc, "src/a.py")["path_kind_why"]),
         ("shared_path", "modified_existing"))
done_all(repo, story)

# --- B3 / B4 (M3): a decorator line belongs to its function; the hunk header naming the PREVIOUS function is never read ---------
DEC = ("def one():\n    return 1\n\n\n@router.get('/x')\ndef endpoint():\n    return 2\n")
repo, story, base, impl = one({"src/api.py": DEC, "src/o.py": "pass\n"}, {"src/api.py": DEC.replace("'/x'", "'/y'"), "src/o.py": "pass\n"})
doc = story.build()
a = area(doc, "src/api.py")
check_eq("B3: a decorator-line change belongs to the function; 0 sites -> callers [] (searched, found none), modified_existing",
         (names(doc, "src/api.py"), a["callers"], a["path_kind"], a["path_kind_why"]), (["endpoint"], [], "shared_path", "modified_existing"))
done_all(repo, story)
TWO = "def one():\n    return 1\n\n\ndef two():\n    return 2\n\n\ndef three():\n    return 3\n"
repo, story, base, impl = one({"src/two.py": TWO}, {"src/two.py": TWO.replace("return 2", "return 22")})
text = (story.task / "work" / "impl-diff.txt").read_text(encoding="utf-8")
check("B4 setup: the hunk header names the PREVIOUS function (one)", "@@" in text and "def one" in text.split("@@")[2].splitlines()[0], text[:300])
doc = story.build()
check_eq("B4: the symbol is two (by ast), never one (the header)", names(doc, "src/two.py"), ["two"])
done_all(repo, story)

# --- B5: a deleted function with references; B5b a deleted FILE with no checkout ----------------------------------------------------
OLD = "def old():\n    return 1\n\n\ndef keep():\n    return 2\n"
repo, story, base, impl = one({"src/mod.py": OLD, "src/user.py": "from mod import old\n\n\ndef go():\n    return old()\n"},
                              {"src/mod.py": "def keep():\n    return 2\n", "src/user.py": "from mod import old\n\n\ndef go():\n    return old()\n"})
doc = story.build()
a = area(doc, "src/mod.py")
check_eq("B5: a deleted function: status deleted, its references are the sites, shared_path / deleted",
         ([(s["name"], s["status"]) for s in a["touched"]["symbols"]], sites(a), a["path_kind"], a["path_kind_why"]),
         ([("old", "deleted")], [("src/user.py", 1), ("src/user.py", 5)], "shared_path", "deleted"))
done_all(repo, story)
repo = Repo()
base = repo.commit({"src/gone.py": "def vanish():\n    return 1\n\n\nclass Old:\n    pass\n", "src/keep.py": "x = 1\n"})
impl = repo.commit({"src/gone.py": None})
story = Story()
story.set_diff(repo.diff(base, impl), impl)
doc = story.build()
a = area(doc, "src/gone.py")
check_eq("B5b: a deleted FILE with no checkout: symbols from the - lines, callers unmeasured, shared_path",
         ([s["name"] for s in a["touched"]["symbols"]], starts(a["callers"], "unmeasured: no checkout of backend"), a["path_kind"], a["touched"]["change"]),
         (["vanish", "Old", "gone"], True, "shared_path", "deleted"))
done_all(repo, story)

# --- B6: a pure rename: no lines, moved (the old module name is searched too: its importers are the callers that break) -----------
repo, story, base, impl = one({"src/old_name.py": "def keep():\n    return 1\n", "src/imp.py": "import old_name\n"},
                              {"src/old_name.py": None, "src/new_name.py": "def keep():\n    return 1\n", "src/imp.py": "import old_name\n"})
doc = story.build()
a = area(doc, "src/new_name.py")
check_eq("B6: a pure rename: lines 0, change renamed, every symbol moved, the OLD module name has its importer as a caller",
         (a["touched"]["lines"], a["touched"]["change"], sorted({s["status"] for s in a["touched"]["symbols"]}), sites(a), a["path_kind"], a["path_kind_why"]),
         (0, "renamed", ["moved"], [("src/imp.py", 1)], "shared_path", "moved"))
done_all(repo, story)

# --- B6b (X1, X2; t-1224): a renamed AND edited Python file is measured (its blob is asked at the NEW path), alone and beside a modified neighbour ---
RBASE = "def f(x):\n    return x\n\n\ndef g(x):\n    return x\n\n\ndef h(x):\n    return x\n"
RUSER = "from new_name import f\n\n\ndef other():\n    return f(2)\n"
for label, extra_base, extra_impl in (("alone", {}, {}), ("beside a modified neighbour", {"src/neighbour.py": "VALUE = 1\n"}, {"src/neighbour.py": "VALUE = 2\n"})):
    repo, story, base, impl = one({"src/old_name.py": RBASE, "src/imp.py": RUSER, "src/old_user.py": "import old_name\n", **extra_base},
                                  {"src/old_name.py": None, "src/new_name.py": RBASE.replace("return x\n\n\ndef g", "return x + 1\n\n\ndef g"), **extra_impl})
    doc = story.build()
    a = area(doc, "src/new_name.py")
    symbols = a["touched"]["symbols"]
    check_eq(f"B6b ({label}): rename + edit: the symbols are MEASURED - f modified, the old module name moved (no `unmeasured: ... not a file of commit`)",
             (a["touched"]["change"], [(s["name"], s["status"]) for s in symbols] if isinstance(symbols, list) else symbols),
             ("renamed", [("f", "modified"), ("old_name", "moved")]))
    check_eq(f"B6b ({label}): ...the callers of the edited function (imp.py:1, imp.py:5) and of the old module name (old_user.py:1) are found",
             (sites(a), "is not a file of commit" in json.dumps(a), a["path_kind"], a["path_kind_why"]),
             ([("src/imp.py", 1), ("src/imp.py", 5), ("src/old_user.py", 1)], False, "shared_path", "callers_found"))
    done_all(repo, story)
# X2: the old path comes from `BS._old_path`, not a `[2:]` slice - a top-level folder named `a` is not a diff prefix
PKG = "def keep():\n    return 1\n"
repo, story, base, impl = one({"a/__init__.py": PKG, "use.py": "import a\n"}, {"a/__init__.py": None, "b/__init__.py": PKG})
a = area(story.build(), "b/__init__.py")
check_eq("B6b (X2): a package `a/__init__.py` renamed to `b/__init__.py`: the old module name is `a` (not `__init__`), its importer is the caller",
         ([(s["name"], s["level"]) for s in a["touched"]["symbols"]], sites(a)), ([("b", "module"), ("a", "module")], [("use.py", 1)]))
done_all(repo, story)

# --- B7 (M4): caps AT and BEYOND --------------------------------------------------------------------------------------------------
def calls_file(n, name="f", per_line=1):
    return "".join(f"{name}({i})\n" for i in range(n))


def capped(**uses):
    base_files = {"src/m.py": "".join(f"def {n}():\n    return 1\n\n\n" for n in uses) + "x = 1\n"}
    impl_files = {"src/m.py": "".join(f"def {n}():\n    return 2\n\n\n" for n in uses) + "x = 1\n"}
    for n, count in uses.items():
        base_files[f"src/use_{n}.py"] = impl_files[f"src/use_{n}.py"] = calls_file(count, n)
    repo, story, _b, _i = one(base_files, impl_files)
    return repo, story


repo, story = capped(f=25)
a = area(story.build(), "src/m.py")
check_eq("B7: 25 sites of one symbol -> all shown, no `more`, truncated no, callers_more 0",
         (len(a["callers"]), "more" in a["touched"]["symbols"][0], a["truncated"], a["callers_more"]), (25, False, "no", 0))
done_all(repo, story)
repo, story = capped(f=26)
a = area(story.build(), "src/m.py")
check_eq("B7: 26 sites -> 25 shown, more 1, callers_more 1, truncated yes, shared_path / truncated",
         (len(a["callers"]), a["touched"]["symbols"][0].get("more"), a["callers_more"], a["truncated"], a["path_kind"], a["path_kind_why"]),
         (25, 1, 1, "yes", "shared_path", "truncated"))
done_all(repo, story)
repo, story = capped(f=20, g=20, h=20)
a = area(story.build(), "src/m.py")
check_eq("B7: the area cap AT 60 -> 60 shown, nothing cut", (len(a["callers"]), a["callers_more"], a["truncated"]), (60, 0, "no"))
done_all(repo, story)
repo, story = capped(f=20, g=20, h=21)
a = area(story.build(), "src/m.py")
check_eq("B7: BEYOND 61 -> 60 shown, callers_more 1, truncated yes", (len(a["callers"]), a["callers_more"], a["truncated"], a["path_kind"]),
         (60, 1, "yes", "shared_path"))
done_all(repo, story)
repo, story = capped(f=1000, g=3)
a = area(story.build(), "src/m.py")
check_eq("B7: a 1 000-site symbol beside a 3-site one: all 3 shown (round-robin), the big one counted in `more`",
         (sum(1 for c in a["callers"] if c["symbol"] == "g"), a["touched"]["symbols"][0].get("more"), a["callers_more"], len(a["callers"])), (3, 975, 975, 28))
done_all(repo, story)
base_files = {"src/m.py": "def f():\n    return 1\n\n\nx = 1\n", "src/many.py": "".join(f"from m import f  # m {i}\n" for i in range(40))}
impl_files = {"src/m.py": "def f():\n    return 2\n\n\nx = 2\n", "src/many.py": base_files["src/many.py"]}
repo, story, _b, _i = one(base_files, impl_files)
a = area(story.build(), "src/m.py")
check_eq("B7: symbol-level names come before module-level ones (f's 25 sites all shown beside the module name's 40)",
         (sum(1 for c in a["callers"] if c["symbol"] == "f"), [s["level"] for s in a["touched"]["symbols"]]), (25, ["symbol", "module"]))
done_all(repo, story)

MODX = MOD.replace("    return x\n\n\ndef g", "    return x + 1\n\n\ndef g")
DPATH = "qa-factory/artifacts/T-1/work/impl-diff.txt"


SHARED: list = []


def mini(fresh=False, **extra):
    """The small story (f modified, one caller): ONE repository shared by every test that only READS it (a git call costs ~0.3 s on a
    slow machine); `fresh=True` or a sha256 repository gets its own."""
    if fresh or extra.get("sha256"):
        return one({"src/mod.py": MOD, "src/use1.py": USE1}, {"src/mod.py": MODX}, **extra)
    if not SHARED:
        repo = Repo()
        base = repo.commit({"src/mod.py": MOD, "src/use1.py": USE1})
        impl = repo.commit({"src/mod.py": MODX})
        repo.shared = True
        SHARED.append((repo, base, impl, repo.diff(base, impl)))
    repo, base, impl, diff = SHARED[0]
    story = Story()
    story.checkout("backend", repo.dir)
    story.set_diff(diff, impl, **extra)
    return repo, story, base, impl


def states(doc):
    return [(r["repo"], r["state"], r["reason"]) for r in doc["index"]["repos"]]


def all_unmeasured(doc, text):
    return all(isinstance(a["callers"], str) and a["callers"].startswith("unmeasured: " + text) and (a["path_kind"], a["path_kind_why"]) == ("shared_path", "unmeasured")
               for a in doc["areas"])


# --- B8 (M1, M6): one case per row of the join table, exact reasons ------------------------------------------------------------------
repo, story, base, impl = mini()
story.checkout("testproject1-backend", repo.dir)
story.manifest([{"repo": "testproject1-backend", "diff_path": DPATH, "source_sha": impl}, {"repo": "testproject1-ui", "diff_path": None, "source_sha": "e" * 40},
                {"repo": "testproject1-onboarding", "diff_path": None, "source_sha": "d" * 40}])
doc = story.build()
check_eq("B8: the 13877 shape (3 entries, two with a null diff_path): the diff joins backend by its basename, measured (not _impl_checkout)",
         (states(doc), isinstance(area(doc, "src/mod.py")["callers"], list), doc["index"]["repos"][0]["id"]), ([("", "match", "")], True, "testproject1-backend"))
done_all(repo, story)
ra, rb = Repo(), Repo()
a0 = ra.commit({"src/mod.py": MOD, "src/use1.py": USE1})
a1 = ra.commit({"src/mod.py": MODX})
b0 = rb.commit({"web/view.py": "def view():\n    return 1\n"})
b1 = rb.commit({"web/view.py": "def view():\n    return 2\n"})
story = Story()
story.checkout("be", ra.dir)
story.checkout("ui", rb.dir)
story.set_diff(ra.diff(a0, a1), a1, name="impl-diff-be.txt", repo_id="be")
story.set_diff(rb.diff(b0, b1), b1, name="impl-diff-ui.txt", repo_id="ui")
story.manifest([{"repo_id": "be", "diff_path": None, "source_sha": a1}, {"repo_id": "ui", "diff_path": None, "source_sha": b1}])
doc = story.build()
check_eq("B8: the 15045 shape (two suffixed diffs, null diff_path): both measured, each in its own checkout (M6: not _impl_checkout)",
         (states(doc), sites(area(doc, "src/mod.py")), sites(area(doc, "web/view.py"))), ([("be", "match", ""), ("ui", "match", "")], [("src/use1.py", 1), ("src/use1.py", 5)], []))
story.cfg["implementation_repos"] = [r for r in story.cfg["implementation_repos"] if r["repo_id"] == "be"]
doc = story.build()
v = area(doc, "web/view.py")
check_eq("B8: one without a checkout: ONLY it is no_checkout; its areas unmeasured with the reason; the other is measured",
         (states(doc), v["callers"], v["path_kind"], v["path_kind_why"], isinstance(area(doc, "src/mod.py")["callers"], list)),
         ([("be", "match", ""), ("ui", "no_checkout", "no checkout of ui on this machine")], "unmeasured: no checkout of ui on this machine", "shared_path", "unmeasured", True))
done_all(ra, rb, story)
for label, entries, expect in (
        ("two entries, one basename", [{"repo": "a", "diff_path": DPATH, "source_sha": "a" * 40}, {"repo": "b", "diff_path": "x/impl-diff.txt", "source_sha": "b" * 40}],
         "2 manifest entries name impl-diff.txt"),
        ("`repo: null` joined by basename", [{"repo": None, "diff_path": DPATH, "source_sha": "a" * 40}], "no repository id for impl-diff.txt"),
        ("no entry names the diff", [], "no manifest entry for impl-diff.txt")):
    repo, story, base, impl = mini()
    story.manifest(entries)
    watch()
    doc = story.build()
    check_eq(f"B8: {label}: reason verbatim, areas present, no git call in the checkout",
             (states(doc), len(doc["areas"]), len(calls_in(repo)), all_unmeasured(doc, expect)), ([("", "unknown_repo", expect)], 1, 0, True))
    unwatch()
    done_all(repo, story)
repo, story, base, impl = mini()
(story.task / "work" / "context-manifest.json").unlink()
doc = story.build()
check_eq("B8: no manifest at all: no entry for the diff, manifest_sha256 null", (states(doc), doc["index"]["manifest_sha256"]), ([("", "unknown_repo", "no manifest entry for impl-diff.txt")], None))
junk = b"{ not json"
story.write("work/context-manifest.json", junk)
doc = story.build()
check_eq("B8: an unreadable manifest: the same reason, manifest_sha256 is the bytes' sha (a repair rebuilds)",
         (states(doc), doc["index"]["manifest_sha256"]), ([("", "unknown_repo", "no manifest entry for impl-diff.txt")], hashlib.sha256(junk).hexdigest()))
done_all(repo, story)

# --- B9 (M5): source_sha AT 40 / 64 hex measures; BEYOND is no_record with GT's text and ZERO git calls in the checkout --------------
repo, story, base, impl = mini()
doc = story.build()
check_eq("B9: 40 lower hex (the commit): measured", states(doc), [("", "match", "")])
done_all(repo, story)
repo, story, base, impl = mini(sha256=True)
doc = story.build()
check_eq("B9: 64 lower hex (a sha256 repository's commit): measured", (len(impl), states(doc)), (64, [("", "match", "")]))
done_all(repo, story)
for label, value in (("39 hex", "a" * 39), ("40 UPPER", "A" * 40), ("HEAD", "HEAD"), ("main", "main"), ("empty", ""), ("int 7", 7), ("65 hex", "a" * 65)):
    repo, story, base, impl = mini()
    story.manifest([{"repo_id": "backend", "diff_path": DPATH, "source_sha": value}])
    expect = GT.commit_value({"repo_id": "backend", "source_sha": value}, "impl-diff.txt")[len("unmeasured: "):]
    watch()
    doc = story.build()
    check_eq(f"B9: BEYOND ({label}): no_record, GT's text, no git call in the checkout, areas unmeasured",
             (states(doc), len(calls_in(repo)), all_unmeasured(doc, expect)), ([("", "no_record", expect)], 0, True))
    unwatch()
    done_all(repo, story)

# --- B10: a commit absent from the checkout; a checkout whose HEAD is elsewhere is read AT the recorded commit (I3) -----------------
repo, story, base, impl = mini(source_sha="f" * 40)
doc = story.build()
state = doc["index"]["repos"][0]
check_eq("B10: commit absent: the state, both shas named (the recorded one and HEAD)",
         (state["state"], "commit " + "f" * 12 + " is not in" in state["reason"], f"(HEAD {impl[:12]})" in state["reason"], state["head"]), ("commit_absent", True, True, impl))
check_eq("B10: ...and the areas are unmeasured", all_unmeasured(doc, state["reason"]), True)
done_all(repo, story)
repo, story, base, impl = mini(fresh=True)
later = repo.commit({"src/use1.py": "def a():\n    return 0\n", "src/mod.py": "def other():\n    return 3\n"}, "moves HEAD and the tree")
doc = story.build()
a = area(doc, "src/mod.py")
check_eq("B10: HEAD moved on, the object present: measured from the OBJECT (f and its callers, not the working tree)",
         (doc["index"]["repos"][0]["state"], doc["index"]["repos"][0]["head"] == later, names(doc, "src/mod.py"), sites(a)), ("match", True, ["f"], [("src/use1.py", 1), ("src/use1.py", 5)]))
done_all(repo, story)


# --- B11 (M2): the exit code of `git grep` ---------------------------------------------------------------------------------------------
def answer_grep(code, out=b""):
    def handler(cwd, args, stdin):
        return (code, out) if "grep" in args else None
    return handler


repo, story, base, impl = mini()


def line_of(path, n, text):
    return impl.encode() + b":" + path.encode() + bytes([0]) + str(n).encode() + bytes([0]) + text.encode() + b"\n"


watch(answer_grep(0, line_of("src/zz.py", 7, "f(1)") + line_of("src/yy.py", 3, "x = f")))
a = area(story.build(), "src/mod.py")
check_eq("B11: exit 0 -> the output is parsed (two sites, sorted)", sites(a), [("src/yy.py", 3), ("src/zz.py", 7)])
watch(answer_grep(1))
a = area(story.build(), "src/mod.py")
check_eq("B11: exit 1 -> measured zero: callers [] (searched, none found), modified_existing", (a["callers"], a["path_kind"], a["path_kind_why"]), ([], "shared_path", "modified_existing"))
watch(answer_grep(128, line_of("src/zz.py", 7, "f(1)")))
doc = story.build()
a = area(doc, "src/mod.py")
check_eq("B11: exit 128 -> NOT zero, not parsed: unmeasured with the code; the repo may be retried (git_failed)",
         (starts(a["callers"], "unmeasured: git grep exited 128 in"), a["path_kind"], a["path_kind_why"], doc["index"]["repos"][0]["state"], a["tests_gap"] != ""),
         (True, "shared_path", "unmeasured", "git_failed", True))
watch(answer_grep(None, line_of("src/zz.py", 7, "f(1)")))
a = area(story.build(), "src/mod.py")
check_eq("B11: a timeout (None) with partial output: the partial output is DROPPED",
         (starts(a["callers"], "unmeasured: git did not run or did not finish in 60 s in"), a["path_kind"]), (True, "shared_path"))
watch(answer_grep(0, b"garbage without separators\n"))
a = area(story.build(), "src/mod.py")
check_eq("B11: a line this reader does not know: unmeasured, never a guess", starts(a["callers"], "unmeasured: git grep answered a line this reader does not know"), True)
unwatch()
done_all(repo, story)

# --- B12: another language: the module-level name is searched; no definitions are claimed ---------------------------------------------
repo, story, base, impl = one({"web/Comp.tsx": "export const x = 1;\n", "web/use.tsx": "import Comp from './Comp';\n"}, {"web/Comp.tsx": "export const x = 2;\n"})
doc = story.build()
a = area(doc, "web/Comp.tsx")
check_eq("B12: .tsx -> the module-level name only, language tsx, importers are callers, no same_name_defs",
         (names(doc, "web/Comp.tsx"), a["language"], sites(a), a["same_name_defs"], a["path_kind"]), (["Comp"], "tsx", [("web/use.tsx", 1)], [], "shared_path"))
done_all(repo, story)

# --- B13: what ast cannot read at the commit: unmeasured symbols + ONE module-level name (still searched) -------------------------------
bad = {"src/syn.py": "def f(:\n    pass\n", "src/cr.py": "x = 1\rdef g():\n    return 1\n", "src/lat.py": b"# \xe9\ndef h():\n    return 1\n", "src/imp.py": "import syn, cr, lat\n"}
good = {"src/syn.py": "def f(:\n    pass\n    #\n", "src/cr.py": "x = 2\rdef g():\n    return 1\n", "src/lat.py": b"# \xe9\ndef h():\n    return 2\n", "src/imp.py": "import syn, cr, lat\n"}
repo, story, base, impl = one(bad, good)
doc = story.build()
for path, why in (("src/syn.py", "cannot be parsed as Python (SyntaxError)"), ("src/cr.py", "holds a lone CR line break"), ("src/lat.py", "is not UTF-8 text")):
    a = area(doc, path)
    mod = path.split("/")[1][:-3]
    check_eq(f"B13: {path}: symbols unmeasured ({why}), the module name {mod} is still searched, shared_path / unmeasured",
             (isinstance(a["touched"]["symbols"], str) and a["touched"]["symbols"].startswith(f"unmeasured: {path} {why} at {impl[:12]}"),
              [c["symbol"] for c in a["callers"]], a["path_kind"], a["path_kind_why"]), (True, [mod], "shared_path", "unmeasured"))
done_all(repo, story)

# --- B14: nothing to search for -> no git grep at all ----------------------------------------------------------------------------------
repo, story, base, impl = one({"docs/readme.md": "one\n"}, {"docs/readme.md": "two\n"})
watch()
doc = story.build()
check_eq("B14: only a docs file: no symbol name, so no `git grep` (and no more than the join's calls)",
         ([x for x in calls_in(repo) if "grep" in x], len(calls_in(repo)) <= 2, doc["areas"][0]["path_kind"]), ([], True, "not_applicable"))
unwatch()
done_all(repo, story)

# --- B15: a story whose source is not `diff` -> off_diff, no file, an earlier file untouched; a source that disagrees with the disk is refused ----
story = Story(source="current-code")
how = story.ensure()
check_eq("B15: source current-code, no diff: (None, off_diff), no file written", (how, story.file.exists()), ((None, "off_diff"), False))
story.write("work/blast-radius.json", b"EARLIER BYTES")
before = hashlib.sha256(story.file.read_bytes()).hexdigest()
how = story.ensure(rebuild=True, force=True)
check_eq("B15: ...an earlier file stays byte-equal", (how, hashlib.sha256(story.file.read_bytes()).hexdigest() == before), ((None, "off_diff"), True))
story.done()
repo, story, base, impl = mini()
(story.task / "pipeline.json").write_bytes(json.dumps({"ticket": "T-1", "stages": {}, "implementation_source": "current-code"}).encode())
try:
    story.ensure()
    refused = ""
except GT.Refusal as exc:
    refused = exc.text
check("B15: a diff on disk with source current-code: refused with GT's words, nothing written", "implementation_source current-code while impl-diff.txt is on disk" in refused and not story.file.exists(), refused)
try:
    BR._compute_only(story.task)
    dry_refused = ""
except GT.Refusal as exc:
    dry_refused = exc.text
check_eq("B15 (X4): `--json` (_compute_only) refuses a source/disk mismatch with the SAME text as `ensure`, the stage_done door included",
         (dry_refused == refused, "stage_done --set implementation_source=" in dry_refused), (True, True))
done_all(repo, story)
story = Story(source="current-code")
check_eq("B15 (X4): off_diff through both entries: `ensure` says (None, off_diff), `_compute_only` says None", (story.ensure(), BR._compute_only(story.task)), ((None, "off_diff"), None))
story.done()

# --- B16: an empty diff is the one legal empty ------------------------------------------------------------------------------------------
repo = Repo()
base = repo.commit({"src/mod.py": MOD})
story = Story()
story.checkout("backend", repo.dir)
story.set_diff(b"", base)
doc = story.build()
check_eq("B16: an empty diff: areas [], the repository named and measured, the diff read", (doc["areas"], states(doc), doc["index"]["diffs"][0]["state"]), ([], [("", "match", "")], "read"))
done_all(repo, story)

# --- B17: a combined diff (@@@) and a path-uncertain section: one area each, never read from git ------------------------------------------
repo, story, base, impl = mini()
weird = "diff --cc src/m.py\nindex 1,2..3\n--- a/src/m.py\n+++ b/src/m.py\n@@@ -1,2 -1,2 +1,3 @@@\n x\n++y\ndiff --git foo bar\n@@ -1 +1 @@\n-a\n+b\n"
story.set_diff(repo.diff(base, impl) + weird.encode(), impl)
asked = []


def spy_stdin(cwd, args, stdin):
    asked.append(stdin or b"")
    return None


watch(spy_stdin)
doc = story.build()
unwatch()
c, u, m = area(doc, "src/m.py"), area(doc, "foo bar"), area(doc, "src/mod.py")
check_eq("B17: three areas (every DP record); the combined one is `refused`, the other `uncertain`", (len(doc["areas"]), c["touched"]["change"], u["touched"]["change"]), (3, "refused", "uncertain"))
check_eq("B17: ...both shared_path / unmeasured, callers and symbols unmeasured strings",
         [(x["path_kind"], x["path_kind_why"], isinstance(x["callers"], str), isinstance(x["touched"]["symbols"], str)) for x in (c, u)], [("shared_path", "unmeasured", True, True)] * 2)
check_eq("B17: ...never read from git (no blob was asked for them), the normal section is measured",
         (b"src/m.py" in b"".join(asked), b"foo bar" in b"".join(asked), isinstance(m["callers"], list)), (False, False, True))
done_all(repo, story)

# --- B18: an unreadable diff is named (F-2), never a silent `areas: []` ----------------------------------------------------------------
repo, story, base, impl = mini()
real_read = DP.read_diff


def refuse_read(path):
    raise OSError("access denied")


DP.read_diff = refuse_read
try:
    doc = story.build()
finally:
    DP.read_diff = real_read
d = doc["index"]["diffs"][0]
check_eq("B18: index.state stays built; the diff is `unreadable` with its reason; the repository is diff_unreadable naming it; areas []",
         (doc["index"]["state"], d["state"], "access denied" in d["reason"], states(doc)[0][1], "access denied" in states(doc)[0][2], doc["areas"]),
         ("built", "unreadable", True, "diff_unreadable", True, []))
done_all(repo, story)

# --- B19 (M7): tests need a SITE; the forms of `tests` / `tests_gap` -----------------------------------------------------------------------
CALC = "def compute(x):\n    return x\n"
CALCX = "def compute(x):\n    return x + 1\n"
CALCU = "from calc import compute\n\n\ndef go():\n    return compute(1)\n"


def calc_story(extra_base=None, extra_impl=None, **kw):
    return one({"src/calc.py": CALC, "src/use.py": CALCU, **(extra_base or {})}, {"src/calc.py": CALCX, **(extra_impl or {})}, **kw)


repo, story, base, impl = calc_story()
(story.root / "tests" / "test_calc.py").write_bytes(b"def test_compute_basic():\n    assert True\n")
doc = story.build()
a = area(doc, "src/calc.py")
check_eq("B19: a test that shares only nouns/path: advice (suggested_tests), NOT a test; both parts ran, 0 sites -> [] and tests_gap ''",
         (a["tests"], a["tests_gap"], [x["path"] for x in a["suggested_tests"]]), ([], "", ["tests/test_calc.py"]))
(story.root / "tests" / "test_calc2.py").write_bytes(b"from calc import compute\n\n\ndef test_c():\n    assert compute(1) == 2\n")
story.write("work/context-bundle.json", json.dumps({"existing_test_candidates": [
    {"path": "tests/test_calc2.py", "repo": "", "candidate_id": "TC-1"}, {"path": "tests/test_ghost.py", "repo": "", "candidate_id": "TC-2"}]}))
doc = story.build()
a = area(doc, "src/calc.py")
check_eq("B19: a root site is a test (source test_root -> bundle when a candidate names the file, with its id); a siteless candidate is absent",
         ([(t["ref"], t["line"], t["source"], t["candidate_id"]) for t in a["tests"]], a["tests_gap"]),
         ([("tests/test_calc2.py", 1, "bundle", "TC-1"), ("tests/test_calc2.py", 5, "bundle", "TC-1")], ""))
shutil.rmtree(story.root / "tests")
doc = story.build()
a = area(doc, "src/calc.py")
check_eq("B19: a missing root, no site anywhere: tests is the `unmeasured: <reason>` string AND tests_gap says it; shared_path / unmeasured",
         (a["tests"], a["tests_gap"], a["path_kind"], a["path_kind_why"]),
         ("unmeasured: the test root tests is not a folder", "the test root tests is not a folder", "shared_path", "unmeasured"))
done_all(repo, story)
repo, story, base, impl = calc_story({"tests/test_calc.py": "from calc import compute\n\n\ndef test_c():\n    assert compute(1) == 1\n"})
shutil.rmtree(story.root / "tests")
doc = story.build()
a = area(doc, "src/calc.py")
check_eq("B19: a missing root but sites in the implementation repo: the sites are shown AND the gap is named",
         ([(t["ref"], t["line"], t["source"]) for t in a["tests"]], a["tests_gap"]), ([("tests/test_calc.py", 1, "repo_scan"), ("tests/test_calc.py", 5, "repo_scan")], "the test root tests is not a folder"))
done_all(repo, story)
repo, story, base, impl = calc_story()
story.cfg["implementation_repos"] = []
shutil.rmtree(story.root / "tests")
doc = story.build()
a = area(doc, "src/calc.py")
check("B19: ...naming both causes", "no checkout of backend on this machine" in a["tests"] and "the test root tests is not a folder" in a["tests"] and a["tests"] == "unmeasured: " + a["tests_gap"], str(a["tests"]))
done_all(repo, story)
story = Story(tests_root="co/tests")
repo = Repo(parent=story.root)
story.cfg["tests_root"] = f"{repo.dir.name}/tests"
base = repo.commit({"src/calc.py": CALC, "src/use.py": CALCU, "tests/test_calc.py": "from calc import compute\n\n\ndef test_c():\n    assert compute(1) == 1\n"})
impl = repo.commit({"src/calc.py": CALCX})
story.checkout("backend", repo.dir)
story.set_diff(repo.diff(base, impl), impl)
doc = story.build()
a = area(doc, "src/calc.py")
check_eq("B19: a test root INSIDE the checkout: the commit read wins, one entry per site (no second copy from the working tree)",
         ([(t["ref"], t["line"], t["source"]) for t in a["tests"]], a["tests_gap"]), ([("tests/test_calc.py", 1, "repo_scan"), ("tests/test_calc.py", 5, "repo_scan")], ""))
done_all(repo, story)

# --- B20: docs / test files: the radius does not apply, the area is still there --------------------------------------------------------
repo, story, base, impl = one({"src/mod.py": MOD, "docs/readme.md": "a\n", "tests/test_mod.py": TEST}, {"src/mod.py": MODX, "docs/readme.md": "b\n", "tests/test_mod.py": TEST + "\n\ndef test_x():\n    assert True\n"})
doc = story.build()
check_eq("B20: docs and test files: not_applicable, callers [], tests [], symbols []; the production area is measured",
         ([(area(doc, p)["path_kind"], area(doc, p)["callers"], area(doc, p)["tests"], area(doc, p)["touched"]["symbols"]) for p in ("docs/readme.md", "tests/test_mod.py")],
          len(doc["areas"]), area(doc, "src/mod.py")["path_kind"]), ([("not_applicable", [], [], [])] * 2, 3, "shared_path"))
done_all(repo, story)

# --- B20b (F-A, t-1224): docs and tests are not_applicable by FILE KIND in EVERY repository state; a code file stays unmeasured ------------------
repo, story, base, impl = one({"src/mod.py": MOD, "docs/readme.md": "a\n", "tests/test_mod.py": TEST}, {"src/mod.py": MODX, "docs/readme.md": "b\n", "tests/test_mod.py": TEST + "\n\ndef test_x():\n    assert True\n"})
diff20 = repo.diff(base, impl)
for state in ("match", "no_checkout", "commit_absent", "no_record", "unknown_repo"):
    story.checkout("backend", repo.dir)
    story.set_diff(diff20, impl, **({"source_sha": "f" * 40} if state == "commit_absent" else {"source_sha": "not-a-sha"} if state == "no_record" else {}))
    if state == "no_checkout":
        story.cfg["implementation_repos"] = []
    if state == "unknown_repo":
        story.manifest([])
    doc = story.build()
    code = area(doc, "src/mod.py")
    check_eq(f"B20b ({state}): docs and tests are not_applicable by kind - no callers, no tests, no tests_gap, no symbols, no unmeasured text anywhere",
             (states(doc)[0][1], [(area(doc, p)["path_kind"], area(doc, p)["path_kind_why"], area(doc, p)["callers"], area(doc, p)["tests"], area(doc, p)["tests_gap"],
                                   area(doc, p)["touched"]["symbols"]) for p in ("docs/readme.md", "tests/test_mod.py")]),
             (state, [("not_applicable", "", [], [], "", [])] * 2))
    check_eq(f"B20b ({state}): the CODE area is never not_applicable: measured when the commit was read, else `unmeasured` with its reason (never a bare list)",
             (code["path_kind"], code["path_kind_why"] if state != "match" else None, isinstance(code["callers"], list)),
             ("shared_path", None, True) if state == "match" else ("shared_path", "unmeasured", False))
done_all(repo, story)

# --- B21: magnitude: 300 files / 3 000 hunks -> an area per DP record, at most 4 git processes in the checkout (no time assertion, FR-31) ---
def big_module(i, value):
    return "".join(f"def f{i}_{k}(x):\n" + "".join(f"    v{j} = x\n" for j in range(9)) + f"    c = {value}\n" for k in range(10))


repo, story, base, impl = one({f"src/m{i}.py": big_module(i, 1) for i in range(300)}, {f"src/m{i}.py": big_module(i, 2) for i in range(300)})
watch()
doc = story.build()
check_eq("B21: 300 files / 3 000 hunks -> 300 areas, 3 000 hunk positions, every area with symbols",
         (len(doc["areas"]), sum(len(a["touched"]["hunks"]) for a in doc["areas"]), all(isinstance(a["touched"]["symbols"], list) for a in doc["areas"])), (300, 3000, True))
check_eq("B21: ...git processes in the checkout: cat-file -t, rev-parse HEAD, cat-file --batch, grep: at most 4", (len(calls_in(repo)) <= 4, len(calls_in(repo))), (True, len(calls_in(repo))))
unwatch()
done_all(repo, story)

# --- B22: a dunder method is searched as its class; a package's __init__.py by the folder name -------------------------------------------------
WIDGET = "class Widget:\n    def __init__(self):\n        self.v = 1\n\n    def other(self):\n        return 1\n"
repo, story, base, impl = one({"src/widget.py": WIDGET, "pkg/__init__.py": "x = 1\n", "src/user.py": "from widget import Widget\nimport pkg\n\n\ndef make():\n    return Widget()\n"},
                              {"src/widget.py": WIDGET.replace("self.v = 1", "self.v = 2"), "pkg/__init__.py": "x = 2\n"})
doc = story.build()
w, p = area(doc, "src/widget.py"), area(doc, "pkg/__init__.py")
check_eq("B22: a change inside __init__ -> the class is the symbol (searched), its call sites are callers",
         (names(doc, "src/widget.py"), w["touched"]["symbols"][0]["level"], {c["line"] for c in w["callers"] if c["symbol"] == "Widget"}), (["Widget"], "symbol", {1, 6}))
check_eq("B22: pkg/__init__.py -> the module-level name is the FOLDER's; `import pkg` is the caller",
         (names(doc, "pkg/__init__.py"), p["touched"]["symbols"][0]["level"], sites(p)), (["pkg"], "module", [("src/user.py", 2)]))
done_all(repo, story)

# --- B23 (E12, FR-31): the time budget AT 240 s runs, BEYOND it every repository is `budget` and no partial result is complete -------------------
def two_repos():
    ra, rb = Repo(), Repo()
    a0 = ra.commit({"src/mod.py": MOD, "src/use1.py": USE1})
    a1 = ra.commit({"src/mod.py": MODX})
    b0 = rb.commit({"web/view.py": "def view():\n    return 1\n"})
    b1 = rb.commit({"web/view.py": "def view():\n    return 2\n"})
    story = Story()
    story.checkout("be", ra.dir)
    story.checkout("ui", rb.dir)
    story.set_diff(ra.diff(a0, a1), a1, name="impl-diff-be.txt", repo_id="be")
    story.set_diff(rb.diff(b0, b1), b1, name="impl-diff-ui.txt", repo_id="ui")
    return ra, rb, story


clock = [0.0]
BR._clock = lambda: clock[0]
ra, rb, story = two_repos()
try:
    ticks = [0]

    def stepping(after):
        def now():
            ticks[0] += 1
            return 0.0 if ticks[0] == 1 else after
        return now

    BR._clock = stepping(240.0)
    ticks[0] = 0
    watch()
    doc = story.build()
    check_eq("B23: the clock AT 240 s after t0: both repositories run and are measured", [s[1] for s in states(doc)], ["match", "match"])
    BR._clock = stepping(240.5)
    ticks[0] = 0
    watch()
    doc = story.build()
    check_eq("B23: BEYOND 240 s from the start: every repository `budget`, no git call at all, every area unmeasured",
             ([s[1] for s in states(doc)], len(calls_in(ra)) + len(calls_in(rb)), all_unmeasured(doc, "the index time budget of 240 s ran out before")), (["budget", "budget"], 0, True))
    clock[0] = 0.0
    BR._clock = lambda: clock[0]
    seen = []

    def jump_after_first(cwd, args, stdin):
        seen.append(args[:2])
        if len(seen) == 1:
            clock[0] = 241.0
        return None

    watch(jump_after_first)
    doc = story.build()
    check_eq("B23: the budget runs out after the first repository's first call: no area claims a measured radius it did not finish",
             ([s[1] for s in states(doc)], all_unmeasured(doc, "the index time budget of 240 s ran out before")), (["budget", "budget"], True))
finally:
    BR._clock = __import__("time").monotonic
    unwatch()
    done_all(ra, rb, story)

# --- B24 (M9): ids by key, never renumbered, a retired id never reissued ------------------------------------------------------------------
def body(n):
    return f"def f():\n    return {n}\n"


repo = Repo()
base = repo.commit({"src/0new.py": body(1), "src/a.py": body(1), "src/b.py": body(1)})
story = Story()
story.checkout("backend", repo.dir)
ids = []
chain = []
prior = None
for label, change in (("first", {"src/a.py": body(2), "src/b.py": body(2)}), ("a file inserted FIRST", {"src/0new.py": body(2)}),
                      ("a gone key", {"src/a.py": body(1)}), ("the key re-added", {"src/a.py": body(3)})):
    head = repo.commit(change)
    story.set_diff(repo.diff(base, head), head)
    prior = story.build(prior)
    chain.append((label, [(x["key"].split(":")[1], x["id"]) for x in prior["areas"]], prior["retired_ids"]))
check_eq("B24: first build: B-1.. in diff order", chain[0][1:], ([("src/a.py", "B-1"), ("src/b.py", "B-2")], []))
check_eq("B24: a file inserted FIRST: the old keys keep their ids, the new key is max+1", chain[1][1:], ([("src/0new.py", "B-3"), ("src/a.py", "B-1"), ("src/b.py", "B-2")], []))
check_eq("B24: a key that left is retired, the others keep their ids", chain[2][1:], ([("src/0new.py", "B-3"), ("src/b.py", "B-2")], ["B-1"]))
check_eq("B24: the key re-added later gets a NEW id (B-1 is never reissued); retired_ids carried whole",
         chain[3][1:], ([("src/0new.py", "B-3"), ("src/a.py", "B-4"), ("src/b.py", "B-2")], ["B-1"]))
done_all(repo, story)

# --- B25 (M10): ensure on the same bytes reuses and writes nothing; --rebuild keeps the ids; a manifest or diff change rebuilds -----------------
repo, story, base, impl = mini()
first, how1 = story.ensure()
sha1 = hashlib.sha256(story.file.read_bytes()).hexdigest()
mtime = story.file.stat().st_mtime_ns
second, how2 = story.ensure()
check_eq("B25: two ensure on the same bytes: built, then reused; the file's sha256 and mtime are unchanged",
         (how1, how2, hashlib.sha256(story.file.read_bytes()).hexdigest() == sha1, story.file.stat().st_mtime_ns == mtime), ("built", "reused", True, True))
third, how3 = story.ensure(rebuild=True)
sha1 = hashlib.sha256(story.file.read_bytes()).hexdigest()
check_eq("B25: --rebuild builds again with the same ids", (how3, [x["id"] for x in third["areas"]]), ("built", [x["id"] for x in first["areas"]]))
check_eq("B25: write=False on a fresh file reads it", story.ensure(write=False)[1], "reused")
story.write("work/context-manifest.json", json.dumps({"implementations": [{"repo_id": "backend", "diff_path": DPATH, "source_sha": impl, "note": "changed"}]}))
check_eq("B25: write=False after the manifest changed: stale, nothing built", (story.ensure(write=False)[1], hashlib.sha256(story.file.read_bytes()).hexdigest() == sha1), ("stale", True))
check_eq("B25: ensure after the manifest changed: rebuilt (the manifest bytes are part of freshness)", story.ensure()[1], "built")
story.set_diff(repo.diff(base, impl) + b"\n", impl)
check_eq("B25: ensure after the diff changed: rebuilt", story.ensure()[1], "built")
story.file.unlink()
check_eq("B25: write=False with no file: absent", story.ensure(write=False), (None, "absent"))
done_all(repo, story)


# --- B26: a prior file that does not read (F-5): refused, then --force keeps its bytes and numbers above the table's highest B-n --------------
def gt_run(story, *args):
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(story.root), PYTHONDONTWRITEBYTECODE="1")
    return run_script("grounding_table.py", *args, "--task", "T-1", cwd=story.root, env=env)


REG = ("# Register\n\n## Register\n\n| R | Requirement | source | derived_from | verifiable | ac_ref | observable | impact |\n"
       "|---|---|---|---|---|---|---|---|\n| R-1 | First thing | ac | - | yes | AC1 | diff:a.py:1 | access |\n\n## Contradiction matrix\n")
repo, story, base, impl = mini()
story.write("work/requirements-register.md", REG)
story.ensure()
done = gt_run(story, "--skeleton")
check_eq("B26 setup: the table is made from the index", done.returncode, 0)
table = GT.table_path(story.task)
data = PC.read_grounding(story.task)[0].data
data["blast_radius"]["areas"][0]["id"] = "B-7"
GT.write_yaml(table, data)
junk = b"not json at all"
story.file.write_bytes(junk)
for kwargs in ({}, {"rebuild": True}):
    try:
        story.ensure(**kwargs)
        text = ""
    except GT.Refusal as exc:
        text = exc.text
    check_eq(f"B26: an unreadable prior ({kwargs or 'plain'}): refused with the conductor's door, the bytes untouched",
             ("--rebuild --force" in text, story.file.read_bytes() == junk), (True, True))
doc, how = story.ensure(rebuild=True, force=True)
kept = story.task / "work" / f"blast-radius.unreadable-{hashlib.sha256(junk).hexdigest()[:8]}.json"
check_eq("B26: --force: the old bytes are kept beside the new file; the number is above the table's B-7", (how, [x["id"] for x in doc["areas"]], kept.read_bytes() == junk), ("built", ["B-8"], True))
done_all(repo, story)

# --- B27: `link` (the brief) never rebuilds a retry state; `prepare` (the driver) does -----------------------------------------------------
repo, story, base, impl = mini(source_sha="f" * 40)
check_eq("B27: prepare on a commit_absent repo: built", story.ensure(mode="prepare")[1], "built")
check_eq("B27: link with fresh bytes and a commit_absent repo: reused (no churn under a labelled table)", story.ensure(mode="link")[1], "reused")
check_eq("B27: prepare again: rebuilt (a fetched commit is measured at the next preparation)", story.ensure(mode="prepare")[1], "built")
story.set_diff(repo.diff(base, impl) + b"\n", impl, source_sha="f" * 40)
check_eq("B27: link when the diff bytes changed: built (E10: before G1-11 the brief is the only builder)", story.ensure(mode="link")[1], "built")
done_all(repo, story)

# --- B-GT (AR-22, I2, M8, M11): what the table does with the file ---------------------------------------------------------------------------------
RENAME = ({"src/old_name.py": "def keep():\n    return 1\n", "src/mod.py": MOD, "src/imp.py": "import old_name\n"},
          {"src/old_name.py": None, "src/new_name.py": "def keep():\n    return 1\n", "src/mod.py": MODX, "src/imp.py": "import old_name\n"})


def r8(story):
    return [f.text for f in GT.check(story.task) if f.rule == "R8"]


def set_area(story, number, **fields):
    doc = json.loads(story.file.read_text(encoding="utf-8"))
    doc["areas"][number].update(fields)
    story.file.write_bytes((json.dumps(doc, ensure_ascii=False, indent=1) + "\n").encode("utf-8"))


repo, story, base, impl = one(*RENAME)
story.write("work/requirements-register.md", REG)
story.ensure()
done = gt_run(story, "--skeleton")
data = PC.read_grounding(story.task)[0].data
file_of = {h["id"]: h["file"] for h in data["hunks"]}
check_eq("B-GT: --skeleton accepts the file: index.state built (not stale), every area has hunk ids that are the table's (pseudo included) and ALL lie in the area's OWN file",
         (done.returncode, data["blast_radius"]["index"]["state"], [bool(a["touched"]["hunks"]) and {file_of.get(i) for i in a["touched"]["hunks"]} == {a["touched"]["file"]}
                                                                      for a in data["blast_radius"]["areas"]]),
         (0, "built", [True] * len(data["blast_radius"]["areas"])))
built = json.loads(story.file.read_text(encoding="utf-8"))
files = [x["touched"]["file"] for x in built["areas"]]
check_eq("B-GT: ...the pure rename's pseudo-hunk position is (diff name, 0, 0)",
         [(h["diff"], h["old_start"], h["new_start"]) for h in built["areas"][files.index("src/new_name.py")]["touched"]["hunks"]], [("impl-diff.txt", 0, 0)])
mod_at = files.index("src/mod.py")
target = built["areas"][mod_at]["id"]
for n, a in enumerate(data["blast_radius"]["areas"]):
    a.update(matters="yes" if n == mod_at else "no", why="x", regression="pytest")
GT.write_yaml(GT.table_path(story.task), data)
need = "no tests and no add_tests"
set_area(story, mod_at, tests="unmeasured: some reason", tests_gap="some reason")
texts = r8(story)
check("B-GT: matters yes on `tests: unmeasured ...` + tests_gap and no add_tests -> R8 asks for add_tests", any(need in t and target in t for t in texts), str(texts))
set_area(story, mod_at, tests=[], tests_gap="")
check("B-GT: matters yes on `tests: []` -> the same R8 (measured none still needs add_tests)", any(need in t and target in t for t in r8(story)), str(r8(story)))
set_area(story, mod_at, tests=[{"ref": "tests/t.py", "line": 1, "symbol": "f", "source": "repo_scan", "candidate_id": ""}], tests_gap="")
check("B-GT: matters yes on a sited test -> no add_tests finding", not any(need in t for t in r8(story)), str(r8(story)))
story.ensure(rebuild=True)
texts = " ".join(r8(story))
check("B-GT: a rebuild keeping the ids: the judged table is still the index's (no `differs` / `missing` finding)", "differs from the index" not in texts and "missing from the table" not in texts and "do not match" not in texts, texts)
done_all(repo, story)
# Q-a (t-1224): new files all start at (0, 1) - each area must resolve to its OWN file's hunk (on 13877 ten areas shared one id)
repo, story, base, impl = one({"src/keep.py": "x = 1\n"}, {"src/n1.py": "def one():\n    return 1\n", "src/n2.py": "def two():\n    return 2\n", "src/n3.py": "def three():\n    return 3\n"})
story.write("work/requirements-register.md", REG)
story.ensure()
gt_run(story, "--skeleton")
data = PC.read_grounding(story.task)[0].data
file_of = {h["id"]: h["file"] for h in data["hunks"]}
areas3 = data["blast_radius"]["areas"]
check_eq("B-GT (Q-a): three new files at the same position: three distinct hunk ids, each in its area's own file, the index not stale",
         (data["blast_radius"]["index"]["state"], sorted(a["touched"]["file"] for a in areas3), len({i for a in areas3 for i in a["touched"]["hunks"]}),
          [[file_of[i] for i in a["touched"]["hunks"]] == [a["touched"]["file"]] for a in areas3]),
         ("built", ["src/n1.py", "src/n2.py", "src/n3.py"], 3, [True] * 3))
done_all(repo, story)
repo, story, base, impl = one(*RENAME)
story.write("work/requirements-register.md", REG)
story.cfg["implementation_repos"] = []
story.ensure()
gt_run(story, "--skeleton")
data = PC.read_grounding(story.task)[0].data
for a in data["blast_radius"]["areas"]:
    a.update(matters="yes", why="x", regression="gap:no checkout")
GT.write_yaml(GT.table_path(story.task), data)
built = json.loads(story.file.read_text(encoding="utf-8"))
check("B-GT (M8): a REAL build with no checkout: unmeasured tests AND a tests_gap on every area, so R8 demands add_tests on each",
      all(isinstance(a["tests"], str) and a["tests"].startswith("unmeasured: ") and a["tests_gap"] for a in built["areas"]) and
      len([t for t in r8(story) if need in t]) == 1 and all(a["id"] in " ".join(r8(story)) for a in built["areas"]), str(r8(story))[:300])
done_all(repo, story)

# --- B-ROLE (AR-7, FR-47): the file holds nothing the role writes, no stand, no second carrier of the commit -----------------------------------
repo, story, base, impl = one(*RENAME)
doc = story.build()
text = json.dumps(doc)
check_eq("B-ROLE: no area carries a role field (GT.ROLE_AREA_FIELDS), no `stand`, no `implementation_commit`",
         ([k for a in doc["areas"] for k in GT.ROLE_AREA_FIELDS if k in a], '"stand"' in text, '"implementation_commit"' in text), ([], False, False))
done_all(repo, story)

# --- B-13877: the real copy, no checkout --------------------------------------------------------------------------------------------------------
if REAL.is_dir():
    story = Story()
    shutil.rmtree(story.task)
    shutil.copytree(REAL, story.task, ignore=shutil.ignore_patterns("state"))
    pipe = json.loads((story.task / "pipeline.json").read_text(encoding="utf-8"))
    pipe["implementation_source"] = "diff"
    (story.task / "pipeline.json").write_bytes(json.dumps(pipe).encode())
    doc = story.build()
    check_eq("B-13877: 19 areas B-1..B-19, ONE repository, no_checkout with the reason by name",
             ([a["id"] for a in doc["areas"]] == [f"B-{i}" for i in range(1, 20)], states(doc)),
             (True, [("", "no_checkout", "no checkout of testproject1-backend on this machine")]))
    code_areas = [a for a in doc["areas"] if a["path_kind"] != "not_applicable"]
    check_eq("B-13877 (F-A): the docs (5) and test (3) files are not_applicable by KIND without a checkout; the other 11 (production 3, config 8) are code",
             (sorted((k, sum(1 for a in doc["areas"] if a["path_kind"] == "not_applicable" and a["touched"]["kind"] == k)) for k in ("docs", "test")), len(code_areas)),
             ([("docs", 5), ("test", 3)], 11))
    check_eq("B-13877: every CODE area is unmeasured with that reason, shared_path (an unmeasured radius is never `no radius`)",
             all_unmeasured({"areas": code_areas}, "no checkout of testproject1-backend on this machine"), True)
    check_eq("B-13877: the manifest's three entries joined backend by the basename; the commit is the recorded one",
             (doc["index"]["repos"][0]["id"], doc["index"]["manifest_sha256"] is not None), ("testproject1-backend", True))
    story.done()
else:
    print("SKIP the 13877 pins: experiments/TP1-13877 is not in this tree")


# --- the CLI: exit codes and lines ---------------------------------------------------------------------------------------------------------------
def with_config(story):
    path = story.root / "qa-factory" / "config.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data.update(story.cfg)
    path.write_bytes(json.dumps(data).encode("utf-8"))


repo, story, base, impl = mini()
with_config(story)
done = story.run()
ids_first = [x["id"] for x in json.loads(story.file.read_text(encoding="utf-8"))["areas"]]
check_eq("CLI: default -> built, exit 0, the one line", (done.returncode, done.stdout.strip()), (0, "blast radius: built work/blast-radius.json: 1 areas, 1 repositories, 0 unmeasured"))
done = story.run()
check_eq("CLI: again -> reused", (done.returncode, done.stdout.split(":")[0:2]), (0, ["blast radius", " reused work/blast-radius.json"]))
done = story.run("--rebuild")
check_eq("CLI: --rebuild -> built, the same ids", (done.returncode, done.stdout.startswith("blast radius: built"), [x["id"] for x in json.loads(story.file.read_text(encoding="utf-8"))["areas"]]), (0, True, ids_first))
story.file.unlink()
done = story.run("--json")
check_eq("CLI: --json prints the document and writes NOTHING", (done.returncode, len(json.loads(done.stdout)["areas"]), story.file.exists()), (0, 1, False))
done = story.run(task="NOPE-9")
check_eq("CLI: no such story -> exit 3, a message on stderr", (done.returncode, bool(done.stderr.strip())), (3, True))
story.run()
story.file.write_bytes(junk)
done = story.run()
check_eq("CLI: an unreadable index -> exit 2, stderr names the conductor's door, the bytes untouched", (done.returncode, "--rebuild --force" in done.stderr, story.file.read_bytes() == junk), (2, True, True))
done = story.run("--rebuild")
check_eq("CLI: --rebuild without --force on an unreadable index -> exit 2", (done.returncode, story.file.read_bytes() == junk), (2, True))
done = story.run("--rebuild", "--force")
check_eq("CLI: --rebuild --force -> exit 0, the old bytes kept beside the file", (done.returncode, len(list(story.task.glob("work/blast-radius.unreadable-*.json")))), (0, 1))
(story.task / "pipeline.json").write_bytes(json.dumps({"ticket": "T-1", "stages": {}, "implementation_source": "current-code"}).encode())
story.file.unlink()
done = story.run()
check_eq("CLI: a source that disagrees with the diff on disk -> exit 2, nothing written", (done.returncode, "implementation_source" in done.stderr, story.file.exists()), (2, True, False))
done_all(repo, story)
story = Story(source="current-code")
done = story.run()
check_eq("CLI: no implementation diff -> exit 0, off_diff, nothing written", (done.returncode, "off_diff" in done.stdout, story.file.exists()), (0, True, False))
story.done()
repo, story, base, impl = mini()
story.cfg["implementation_repos"] = []
with_config(story)
done = story.run()
check_eq("CLI: an unmeasured repository is content, not a failure: exit 0, the count and the first reason",
         (done.returncode, done.stdout.strip()), (0, "blast radius: built work/blast-radius.json: 1 areas, 1 repositories, 1 unmeasured (no checkout of backend on this machine)"))
done_all(repo, story)

# --- END ---
for shared in SHARED:
    cleanup(shared[0].dir)
finish("test_blast_radius")
