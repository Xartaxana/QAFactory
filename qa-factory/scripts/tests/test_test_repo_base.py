#!/usr/bin/env python3
"""The test repository's base is recorded once, at the S0 exit (B-207, piece P5-A).

A test the story wrote and committed at delivery equals HEAD, so "compare with HEAD now" reads
`unchanged` for the newest test there is. The base has to be taken before the story touches
anything, by code, once. One named check per edge of the spec, on throwaway git repositories
under the OS temp dir - nothing here touches this repository or a live project.

Git is REQUIRED: a machine with no git fails this file by name instead of skipping it, because
a test that passes by skipping is the silent pass FR-4 forbids.
"""
import contextlib
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import (SCRIPTS, check, check_eq, check_in, check_not_in, cleanup,  # noqa: E402
                     finish, run_script, temp_dir, temp_project, use_project)

sys.path.insert(0, str(SCRIPTS))

# The repositories built here must not read this machine's git configuration: a global
# `core.autocrlf` or `status.showUntrackedFiles` would change what the test observes.
os.environ["GIT_CONFIG_GLOBAL"] = os.devnull
os.environ["GIT_CONFIG_NOSYSTEM"] = "1"
os.environ["GIT_AUTHOR_NAME"] = os.environ["GIT_COMMITTER_NAME"] = "tester"
os.environ["GIT_AUTHOR_EMAIL"] = os.environ["GIT_COMMITTER_EMAIL"] = "tester@example.com"

import test_repo_base as TRB  # noqa: E402
import stage_done  # noqa: E402
from controller import Controller  # noqa: E402

TASK = "QA-BASE"
SUB = "test-harness"
CYR = "".join(chr(c) for c in (0x43A, 0x43E, 0x434))      # a non-ASCII name, built from code points
ACCENT = "caf" + chr(0xE9)


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


def make_repo(repo):
    Path(repo).mkdir(parents=True, exist_ok=True)
    git(repo, "init", "-q", "-b", "main")
    write(Path(repo) / ".gitignore", "qa-factory/\n")     # the story's own files are not "dirty"
    return Path(repo)


def make_project(repo, sub=SUB, tests_root="tests", files=(), commit=True):
    """A project in `repo/sub` (or AT the top when sub is ""), with its tests and a helper
    outside the tests root, committed. Returns (project, cfg)."""
    repo = make_repo(repo)
    project = repo / sub if sub else repo
    write(project / "qa-factory" / "config.json", json.dumps({"tests_root": tests_root}))
    write(project / "tests" / "test_a.py", "def test_a():\n    pass\n")
    write(project / "helper" / "util.py", "VALUE = 1\n")
    for name, data in files:
        write(project / name, data)
    if commit:
        commit_all(repo, "base")
    return project, {"tests_root": tests_root}


def task_root(project, name=TASK):
    root = Path(project) / "qa-factory" / "artifacts" / name
    root.mkdir(parents=True, exist_ok=True)
    return root


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def tree(root):
    return sorted((str(p.relative_to(root)), sha(p) if p.is_file() else "")
                  for p in Path(root).rglob("*"))


def short_form(path):
    """The 8.3 spelling of a Windows path (DEV1~1-style), or the path itself elsewhere."""
    if os.name != "nt":
        return str(path)
    import ctypes
    buf = ctypes.create_unicode_buffer(1024)
    n = ctypes.windll.kernel32.GetShortPathNameW(str(path), buf, 1024)
    return buf.value if n else str(path)


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


# --- edge 2: repo_prefix comes from git, from the project root -------------------------------

def a_subdirectory_project_gets_its_prefix_from_git(tmp, project, cfg):
    # the real shape: repository `testproject1-sdk-cmp1`, project `test-harness` in it, tests_root "."
    repo = project.parent
    rec = TRB.record(task_root(project), project, cfg)
    check_eq("git answered", rec["git"], "ok")
    check_eq("repo_prefix is `git rev-parse --show-prefix` from the project root, posix, no slash",
             rec["repo_prefix"], SUB)
    check_eq("it is what git itself prints", rec["repo_prefix"] + "/",
             git(project, "rev-parse", "--show-prefix"))
    check_eq("head is the repository's HEAD", rec["head"], git(repo, "rev-parse", "HEAD"))
    check_eq("branch", rec["branch"], "main")
    check_eq("schema_version", rec["schema_version"], 1)
    check_eq("recorded_by", rec["recorded_by"], "stage_done.py S0")
    check("the file is state/test-repo-base.json under the task root",
          (task_root(project) / "state" / "test-repo-base.json").is_file())
    check_eq("and load returns the same record", TRB.load(task_root(project)), rec)
    # Windows short names (DEV1~1): the string arithmetic between two spellings breaks on them
    short = short_form(project)
    check_eq("a project handed over by its 8.3 short name gets the same prefix",
             TRB.measure_git(short, cfg)["repo_prefix"], SUB)
    # tests_root is a subdirectory of the project: the prefix is still the PROJECT ROOT's
    deep, deep_cfg = make_project(tmp / "deep", sub="a/b")
    measured = TRB.measure_git(deep, deep_cfg)
    check_eq("two levels down, tests_root inside the project: the PROJECT root's prefix, posix, "
             "no trailing slash", measured["repo_prefix"], "a/b")
    check_eq("and it is the same repository", measured["other_repository"], False)


def a_project_that_is_the_repository_top_has_an_empty_prefix(tmp):
    project, cfg = make_project(tmp / "top", sub="")
    rec = TRB.record(task_root(project), project, cfg)
    check_eq("git ok at the top", rec["git"], "ok")
    check_eq("repo_prefix is the empty string, not '.'", rec["repo_prefix"], "")
    head = rec["head"]
    git(project, "checkout", "-q", "--detach")
    detached = TRB.measure_git(project, cfg)
    check_eq("edge 8: a detached HEAD is named", detached["branch"], "(detached)")
    check_eq("and the head is still the commit", detached["head"], head)


def a_git_worktree_is_a_repository_too(tmp, project, cfg):
    main_head = git(project.parent, "rev-parse", "HEAD")
    worktree = tmp / "the-worktree"
    git(project.parent, "worktree", "add", "-q", "--detach", str(worktree))
    wt_project = worktree / SUB
    write(wt_project / "qa-factory" / "config.json", json.dumps(cfg))    # ignored by git: not tracked
    check("the worktree's `.git` is a file, not a directory", (worktree / ".git").is_file())
    rec = TRB.record(task_root(wt_project), wt_project, cfg)
    check_eq("git ok from a worktree", rec["git"], "ok")
    check_eq("its prefix is the project's place in the worktree", rec["repo_prefix"], SUB)
    check_eq("edge 8: a detached HEAD is named", rec["branch"], "(detached)")
    check_eq("and the head is still the commit", rec["head"], main_head)


# --- edge 3: which repository -----------------------------------------------------------------

def a_tests_root_in_another_repository_is_recorded_as_that_repository(tmp):
    project, cfg = make_project(tmp / "outer", tests_root="tests-repo")
    inner = project / "tests-repo"
    git(inner.parent, "init", "-q", "-b", "trunk", str(inner))
    write(inner / "test_own.py", "def test_own():\n    pass\n")
    commit_all(inner, "inner base")
    rec = TRB.record(task_root(project), project, cfg)
    check_eq("git ok", rec["git"], "ok")
    check_eq("the record is of the tests root's repository: its head",
             rec["head"], git(inner, "rev-parse", "HEAD"))
    check("and not of the project's", rec["head"] != git(project.parent, "rev-parse", "HEAD"))
    check_eq("its branch", rec["branch"], "trunk")
    check_eq("and the record says so in a field", rec["other_repository"], True)
    check_eq("naming where the repository was found", rec["found_from"], "tests_root")


def a_missing_tests_root_falls_back_to_the_project_root(project):
    rec = TRB.measure_git(project, {"tests_root": "no-such-dir"})
    check_eq("the project root's repository is recorded", rec["head"],
             git(project.parent, "rev-parse", "HEAD"))
    check_eq("found from the project root", rec["found_from"], "project_root")
    check_eq("with the project's own prefix", rec["repo_prefix"], SUB)


# --- edge 4: the dirty list covers the whole repository ---------------------------------------

def the_dirty_list_covers_the_whole_repository(tmp):
    crlf = b"line one\r\nline two\r\n"
    project, cfg = make_project(
        tmp / "dirty", files=[("tests/test_gone.py", "gone\n"), ("tests/test_old_name.py", "old\n")])
    check_eq("a clean repository has an empty dirty list",
             TRB.measure_git(project, cfg)["dirty"], [])
    edited = write(project / "helper" / "util.py", "VALUE = 2\n")     # OUTSIDE the tests root, tracked
    (project / "tests" / "test_gone.py").unlink()
    git(project, "mv", "tests/test_old_name.py", "tests/test_new_name.py")
    write(project / "tests" / "test spaced name.py", "s = 1\n")
    write(project / "tests" / f"test_{ACCENT}.py", "e = 1\n")
    cyr = write(project / "tests" / f"{CYR}.py", "c = 1\n")
    write(project / "tests" / "crlf.py", crlf)
    rec = TRB.record(task_root(project), project, cfg)
    by = {d["path"]: d for d in rec["dirty"]}
    base = SUB + "/"
    check_in("a helper OUTSIDE the tests root that was dirty at S0 is listed, not read as clean",
             base + "helper/util.py", list(by))
    check_eq("its status is git's XY", by.get(base + "helper/util.py", {}).get("status"), " M")
    check_eq("its sha256 is the working-tree bytes'", by.get(base + "helper/util.py", {}).get("sha256"), sha(edited))
    check_eq("a deleted file has sha256 ''", by.get(base + "tests/test_gone.py", {}).get("sha256"), "")
    check_eq("and its status", by.get(base + "tests/test_gone.py", {}).get("status"), " D")
    check_eq("a rename is recorded as its two paths",
             sorted(p for p in by if "test_new_name" in p or "test_old_name" in p),
             [base + "tests/test_new_name.py", base + "tests/test_old_name.py"])
    check_eq("the new name carries its hash",
             by.get(base + "tests/test_new_name.py", {}).get("sha256"), sha(project / "tests" / "test_new_name.py"))
    check_eq("the old name no longer exists as a file", by.get(base + "tests/test_old_name.py", {}).get("sha256"), "")
    check_eq("a rename keeps git's status on both", by.get(base + "tests/test_old_name.py", {}).get("status"), "R ")
    check_in("a file name with spaces survives", base + "tests/test spaced name.py", list(by))
    check_eq("an untracked path is `??`", by.get(base + "tests/test spaced name.py", {}).get("status"), "??")
    check_in("a non-ASCII (accented) name survives", base + f"tests/test_{ACCENT}.py", list(by))
    check_in("a non-ASCII (Cyrillic, built from code points) name survives", base + f"tests/{CYR}.py", list(by))
    check_eq("the hash of a non-ASCII name's file is right", by.get(base + f"tests/{CYR}.py", {}).get("sha256"), sha(cyr))
    check_eq("CRLF bytes are hashed raw, not normalised",
             by.get(base + "tests/crlf.py", {}).get("sha256"), hashlib.sha256(crlf).hexdigest())
    check_eq("paths are repository-relative posix, never absolute",
             [p for p in by if p.startswith("/") or "\\" in p or ":" in p], [])
    check_eq("dirty_total counts every entry", rec["dirty_total"], len(rec["dirty"]))


def a_status_line_with_a_newline_in_a_name_is_read_whole():
    # A newline cannot be created in a Windows file name, so the -z parser is proved on git's
    # own byte format: NUL-terminated entries, a rename as `to NUL from NUL`.
    text = "## main...origin/main [ahead 1]\0 M dir/a\nb.txt\0?? c d.txt\0R  new\0old\0MM x\0"
    check_eq("newline, space, rename and a leading-space status all parse",
             TRB.parse_status(text),
             [(" M", "dir/a\nb.txt"), ("??", "c d.txt"), ("R ", "new"), ("R ", "old"), ("MM", "x")])
    check_eq("a header alone is a clean tree", TRB.parse_status("## main\0"), [])
    for name, bad in (("no header, so the first entry could have lost its space", " M a\0"),
                      ("an entry that is not `XY path`", "## main\0garbage\0"),
                      ("a rename with no source", "## main\0R  new\0")):
        try:
            TRB.parse_status(bad)
            got = "no error"
        except ValueError:
            got = "ValueError"
        check_eq(f"a shape it cannot read raises, never guesses: {name}", got, "ValueError")


# --- edge 5: DIRTY_LIMIT -----------------------------------------------------------------------

def the_dirty_limit_is_2000_exactly(project, cfg):
    check_eq("the limit is the spec's", TRB.DIRTY_LIMIT, 2000)
    # 2000 real files cost 158 s of this test on the machine it was written on (measured), so
    # git's status listing is the one thing stood in for: a real repository answers everything
    # else, and the listing is built in git's own `-z` byte format, which `parse_status` reads in
    # the tests above and in the dirty test on real files.
    real_git = TRB._git

    def listing(count):
        def fake(root, *args, **kwargs):
            if args and args[0] == "status":
                return "## main\0" + "".join(f"?? {SUB}/tests/bulk/t{i:04d}.py\0" for i in range(count))
            return real_git(root, *args, **kwargs)
        return fake

    TRB._git = listing(2000)
    try:
        rec = TRB.measure_git(project, cfg)
    finally:
        TRB._git = real_git
    check_eq("exactly 2000: all recorded", len(rec["dirty"]), 2000)
    check_eq("exactly 2000: not truncated", rec["dirty_truncated"], False)
    check_eq("exactly 2000: the total is 2000", rec["dirty_total"], 2000)
    check_eq("exactly 2000: everything is kept", rec["dirty_kept"], "all")
    TRB._git = listing(2001)
    try:
        rec = TRB.measure_git(project, cfg)
    finally:
        TRB._git = real_git
    check_eq("2001: the flag is set", rec["dirty_truncated"], True)
    check_eq("2001: 2000 are kept", len(rec["dirty"]), 2000)
    check_eq("2001: the whole count is stated", rec["dirty_total"], 2001)
    check_in("2001: what is kept is stated", "first 2000 of 2001", rec["dirty_kept"])
    check_eq("2001: what is kept is the head of git's order", rec["dirty"][0]["path"],
             SUB + "/tests/bulk/t0000.py")


# --- t-187 3e: the factory's own folder is not the test repository ------------------------------------
# cmp1's worktree held 4063 dirty paths, 2825 of them under qa-factory/state/telemetry: a second story's
# S0 would have crossed DIRTY_LIMIT, the record would read `dirty_truncated`, and every measurement
# would have fallen back to "HEAD now". The folder is not counted, is named in the record, and
# nothing else is left out.

def visible_project(repo, sub=SUB, tests_root="tests"):
    """Like `make_project`, but `qa-factory/` is NOT git-ignored - the shape of a worktree that ran a
    story. `qa-factory/config.json` is committed at the base, so editing it reads as a tracked change."""
    repo = Path(repo)
    repo.mkdir(parents=True, exist_ok=True)
    git(repo, "init", "-q", "-b", "main")
    project = repo / sub if sub else repo
    write(project / "tests" / "test_a.py", "def test_a():\n    pass\n")
    write(project / "helper" / "util.py", "VALUE = 1\n")
    write(project / "qa-factory" / "config.json", json.dumps({"tests_root": tests_root}))
    commit_all(repo, "base")
    return project, {"tests_root": tests_root}


def story_leftovers(project):
    """What a story leaves under the factory folder: untracked telemetry and artifacts, and a tracked
    file edited."""
    for n in range(3):
        write(project / "qa-factory" / "state" / "telemetry" / f"t{n}.jsonl", f"{n}\n")
    write(project / "qa-factory" / "artifacts" / "QA-1" / "work" / "a.json", "{}")
    write(project / "qa-factory" / "config.json", json.dumps({"tests_root": "edited"}))


def the_factory_folder_is_not_counted(tmp):
    project, cfg = visible_project(tmp / "vis", tests_root=".")
    story_leftovers(project)
    write(project / "helper" / "util.py", "VALUE = 2\n")                       # outside: counted
    write(project / "qa-factory-notes" / "n.md", "a lookalike name\n")          # outside: counted
    write(project / "tests" / "test_new.py", "def test_new():\n    pass\n")     # outside: counted
    rec = TRB.record(task_root(project), project, cfg)
    paths = sorted(d["path"] for d in rec["dirty"])
    check_eq("3e: only the paths OUTSIDE the factory folder are listed, a lookalike name included",
             paths, [f"{SUB}/helper/util.py", f"{SUB}/qa-factory-notes/n.md", f"{SUB}/tests/test_new.py"])
    check_eq("3e: dirty_total counts those and nothing under the folder", rec["dirty_total"], 3)
    check_eq("3e: the record names the folder, repo-relative like the paths of `dirty`",
             rec["dirty_excluded"], f"{SUB}/qa-factory")
    check_eq("3e: and says nothing was refused", rec["dirty_excluded_why"], "")
    check_eq("3e: the file on disk carries it", json.loads(
        (task_root(project) / "state" / "test-repo-base.json").read_text(encoding="utf-8"))["dirty_excluded"],
        f"{SUB}/qa-factory")
    check_in("3e: a person reading the record is told what is left out",
             f"{SUB}/qa-factory", " ".join(TRB.describe(rec)))
    real = TRB.FACTORY_FOLDER
    TRB.FACTORY_FOLDER = "no-such-folder"
    try:
        whole = TRB.measure_git(project, cfg)
    finally:
        TRB.FACTORY_FOLDER = real
    check("3e control: with nothing excluded the same tree reads more dirty paths (and carries the folder's)",
          whole["dirty_total"] > 3 and any("/qa-factory/state/telemetry/" in d["path"] for d in whole["dirty"]),
          f"{whole['dirty_total']}")

    # a project that IS the repository top: the folder's repo-relative path has no prefix
    top, top_cfg = visible_project(tmp / "vis-top", sub="", tests_root=".")
    story_leftovers(top)
    write(top / "helper" / "util.py", "VALUE = 2\n")
    got = TRB.measure_git(top, top_cfg)
    check_eq("3e: at the repository top the excluded folder is `qa-factory`", got["dirty_excluded"], "qa-factory")
    check_eq("3e: and only the helper is counted", [d["path"] for d in got["dirty"]], ["helper/util.py"])

    # no such folder: nothing excluded, and a path that only LOOKS like it is counted
    bare, bare_cfg = visible_project(tmp / "vis-bare", tests_root=".")
    shutil.rmtree(bare / "qa-factory")
    got = TRB.measure_git(bare, bare_cfg)
    check_eq("3e: a project with no factory folder excludes nothing", got["dirty_excluded"], "")
    check_eq("3e: ...and its deleted tracked file under that name is counted",
             [d["path"] for d in got["dirty"]], [f"{SUB}/qa-factory/config.json"])

    # the tests root lies INSIDE the folder: excluding would hide a dirty test, so it is refused
    inner, inner_cfg = visible_project(tmp / "vis-in", tests_root="qa-factory/tests")
    write(inner / "qa-factory" / "tests" / "test_in.py", "def test_in():\n    pass\n")
    story_leftovers(inner)
    got = TRB.measure_git(inner, inner_cfg)
    check_eq("3e: a tests root inside the factory folder: nothing is excluded", got["dirty_excluded"], "")
    check_in("3e: ...the dirty test there is listed", f"{SUB}/qa-factory/tests/test_in.py",
             [d["path"] for d in got["dirty"]])
    check_in("3e: ...and the record says why", "tests root lies inside qa-factory/", got["dirty_excluded_why"])
    same, same_cfg = visible_project(tmp / "vis-same", tests_root="qa-factory")
    write(same / "qa-factory" / "test_same.py", "def test_same():\n    pass\n")
    got = TRB.measure_git(same, same_cfg)
    check_eq("3e: a tests root that IS the factory folder is refused the same way",
             (got["dirty_excluded"], f"{SUB}/qa-factory/test_same.py" in [d["path"] for d in got["dirty"]]),
             ("", True))

    # the other repository: the project's folder is not in the recorded repository at all
    outer, outer_cfg = visible_project(tmp / "vis-outer", tests_root="tests-repo")
    inner_repo = outer / "tests-repo"
    git(inner_repo.parent, "init", "-q", "-b", "trunk", str(inner_repo))
    write(inner_repo / "test_own.py", "def test_own():\n    pass\n")
    commit_all(inner_repo, "inner base")
    write(inner_repo / "test_dirty.py", "def test_dirty():\n    pass\n")
    got = TRB.measure_git(outer, outer_cfg)
    check_eq("3e: a tests root in another repository: nothing is excluded, its dirty test is listed",
             (got["other_repository"], got["dirty_excluded"], [d["path"] for d in got["dirty"]]),
             (True, "", ["test_dirty.py"]))


def the_exclusion_does_not_move_the_dirty_limit(project, cfg):
    """The limit is the count of what is RECORDED: paths under the folder neither fill it nor hide
    that it was crossed. The listing is git's own `-z` format, stood in as the limit test does."""
    real_git = TRB._git

    def listing(outside, inside):
        def fake(root, *args, **kwargs):
            if args and args[0] == "status":
                lines = [f"?? {SUB}/tests/bulk/t{i:04d}.py\0" for i in range(outside)]
                lines += [f"?? {SUB}/qa-factory/state/telemetry/e{i:04d}.jsonl\0" for i in range(inside)]
                return "## main\0" + "".join(lines)
            return real_git(root, *args, **kwargs)
        return fake

    def measured(outside, inside):
        TRB._git = listing(outside, inside)
        try:
            return TRB.measure_git(project, cfg)
        finally:
            TRB._git = real_git

    rec = measured(1, 4062)
    check_eq("3e: 4063 dirty paths, 4062 of them under the folder: the one other is counted, not truncated",
             (rec["dirty_total"], len(rec["dirty"]), rec["dirty_truncated"], rec["dirty_kept"]), (1, 1, False, "all"))
    rec = measured(TRB.DIRTY_LIMIT, 500)
    check_eq("3e AT the limit: 2000 outside + 500 inside is 2000 recorded, not truncated",
             (rec["dirty_total"], rec["dirty_truncated"]), (2000, False))
    rec = measured(TRB.DIRTY_LIMIT + 1, 500)
    check_eq("3e BEYOND the limit: 2001 outside + 500 inside is still truncated, and the total is 2001",
             (rec["dirty_total"], rec["dirty_truncated"], len(rec["dirty"])), (2001, True, 2000))


# --- edge 6: late recording ---------------------------------------------------------------------

def a_late_recording_is_labelled_and_still_written(project, cfg):
    # The matrix runs on the detector (no git); one real record proves the label reaches the file.
    def why_for(name, prepare=lambda root: None):
        root = task_root(project, "late-" + name)
        prepare(root)
        return TRB.late_reasons(root)

    def pipeline(status):
        return lambda r: write(r / "pipeline.json", json.dumps({"stages": {"S5": {"status": status}}}))

    check_eq("nothing produced yet: not late", why_for("fresh"), [])
    blocks = why_for("blocks", lambda r: write(r / "work" / "run-blocks" / "b1.json", "{}"))
    check_eq("a run block: late", len(blocks), 1)
    check_in("the reason names it", "run-blocks", blocks)
    jobs = why_for("jobs", lambda r: write(r / "state" / "execution-jobs" / "j1.json", "{}"))
    check_eq("an execution job: late", len(jobs), 1)
    check_in("the reason names it", "execution-jobs", jobs)
    check_eq("S5 pending: not late", why_for("s5-pending", pipeline("pending")), [])
    running = why_for("s5-running", pipeline("running"))
    check_eq("S5 running: late", len(running), 1)
    check_in("the reason names the stage", "S5", running)
    check_eq("S5 done: late", len(why_for("s5-done", pipeline("done"))), 1)
    check_eq("S5 absent from the pipeline: not late",
             why_for("s5-absent", lambda r: write(r / "pipeline.json", json.dumps({"stages": {"S0": {}}}))), [])
    check_eq("an empty run-blocks folder is not evidence",
             why_for("empty-blocks", lambda r: (r / "work" / "run-blocks").mkdir(parents=True)), [])
    check_eq("a run block AND S5 running: both reasons",
             len(why_for("both", lambda r: (pipeline("running")(r),
                                            write(r / "work" / "run-blocks" / "b.json", "{}")))), 2)
    root = task_root(project, "late-real")
    pipeline("running")(root)
    write(root / "work" / "run-blocks" / "b1.json", "{}")
    rec = TRB.record(root, project, cfg)
    check("the file is written even when late", (root / "state" / "test-repo-base.json").is_file())
    check_eq("and labelled late", rec["late"], True)
    check_in("with the reasons", "run-blocks", rec["late_why"])
    check_in("all of them", "S5", rec["late_why"])
    check_eq("a late record still carries its git facts", rec["git"], "ok")
    fresh = TRB.record(task_root(project, "late-fresh"), project, cfg)
    check_eq("an early record is not late", (fresh["late"], fresh["late_why"]), (False, ""))


# --- edge 7 and 8: every git state is named, nothing is guessed --------------------------------

def every_git_state_is_named_and_nothing_is_guessed(tmp):
    def nothing_guessed(label, rec, state):
        check_eq(f"{label}: git", rec["git"], state)
        check_eq(f"{label}: head is empty", rec["head"], "")
        check_eq(f"{label}: branch is empty", rec["branch"], "")
        check_eq(f"{label}: no dirty list is invented", rec["dirty"], [])
        check(f"{label}: `why` says what happened", bool(rec["why"]))

    plain = tmp / "not-a-repo"
    write(plain / "x.txt")
    check("precondition: git itself says the plain directory is not a repository",
          subprocess.run(["git", "rev-parse"], cwd=str(plain), capture_output=True).returncode != 0)
    cfg = {"tests_root": "."}
    root = task_root(plain, "absent")
    with without_git():
        check_eq("the fixture really hides git", shutil.which("git"), None)
        absent = TRB.record(root, plain, cfg)
    nothing_guessed("no git on PATH", absent, "absent")
    check("no git: the file is still written", (root / "state" / "test-repo-base.json").is_file())
    check_eq("no git: and once - a second call keeps it", TRB.record(root, plain, cfg), absent)

    root = task_root(plain, "plain")
    nothing_guessed("not a repository", TRB.record(root, plain, {"tests_root": "."}), "not_a_repository")
    check("not a repository: the file is still written", (root / "state" / "test-repo-base.json").is_file())

    broken = tmp / "broken"
    (broken / ".git").mkdir(parents=True)                      # a `.git` that is not a repository
    nothing_guessed("git answers with an error", TRB.record(task_root(broken, "broken"), broken,
                                                            {"tests_root": "."}), "error")

    empty_repo = make_repo(tmp / "empty-repo")                 # initialised, no commit
    empty = TRB.record(task_root(empty_repo, "empty"), empty_repo, {"tests_root": "."})
    nothing_guessed("an empty repository (no commit)", empty, "error")
    check_in("edge 8: an empty repository is `error`, and the reason says it has no commit",
             "no commit", empty["why"])


# --- edge 1, 10, 12: once, load, atomic --------------------------------------------------------

def a_second_close_keeps_the_base_byte_for_byte(project, cfg):
    root = task_root(project, "once")
    target = root / "state" / "test-repo-base.json"
    line = TRB.s0_line(root, project, cfg)
    check("the first close prints the base line",
          bool(re.fullmatch(r"test repository base: [0-9a-f]{12} on main, 0 uncommitted path\(s\)", line)), line)
    first_bytes = target.read_bytes()
    first = TRB.load(root)
    # the story now edits: a new commit and a dirty test - the base must not move to include them
    write(project / "tests" / "test_story.py", "def test_story():\n    pass\n")
    commit_all(project.parent, "the story's own commit")
    write(project / "tests" / "test_more.py", "m = 1\n")
    again = TRB.s0_line(root, project, cfg)
    check_eq("a second S0 close says it is already recorded, and when",
             again, f"test repository base: already recorded at {first['recorded_at']}")
    check_eq("the file is kept byte for byte", target.read_bytes(), first_bytes)
    check_eq("record() returns the kept record", TRB.record(root, project, cfg), first)
    check_eq("and the head did not move forward", TRB.load(root)["head"], first["head"])
    check("(the repository really moved)", git(project, "rev-parse", "HEAD") != first["head"])
    target.write_bytes(b"\x00 not json")
    try:
        TRB.s0_line(root, project, cfg)
        got = "no error"
    except ValueError as exc:
        got = str(exc)
    check_in("an existing file nobody can read is reported, not replaced", "exists but is not a record", got)
    check_eq("and it is kept as it is", target.read_bytes(), b"\x00 not json")


def load_never_raises(tmp):
    root = tmp / "load-root"
    target = root / "state" / "test-repo-base.json"
    check_eq("absent: None", TRB.load(root), None)
    good = {"schema_version": 1, "git": "ok"}
    for label, payload, expected in (
            ("a valid record: the dict", json.dumps(good).encode(), good),
            ("unreadable bytes: None", b"\xff\xfe\x00garbage", None),
            ("not JSON: None", b"{oops", None),
            ("a JSON list: None", b"[1, 2]", None),
            ("a JSON string: None", b'"text"', None),
            ("an unknown schema_version: None", json.dumps({"schema_version": 2}).encode(), None),
            ("a string schema_version: None", json.dumps({"schema_version": "1"}).encode(), None),
            ("a bool schema_version (True == 1 in Python): None", b'{"schema_version": true}', None),
            ("no schema_version: None", b"{}", None)):
        write(target, payload)
        check_eq(label, TRB.load(root), expected)
    target.unlink()
    target.mkdir()
    check_eq("a directory where the file should be: None", TRB.load(root), None)


def an_interrupted_write_never_leaves_half_a_file(tmp):
    project, cfg = tmp / "atomic", {"tests_root": "."}
    root = task_root(project)
    real_replace, real_measure = os.replace, TRB.measure_git
    TRB.measure_git = lambda *a, **k: TRB._empty(".", "project_root", "absent", "a stand-in for git")

    def dying_replace(src, dst, *args, **kwargs):
        raise OSError("the process died before the rename")

    os.replace = dying_replace
    try:
        try:
            TRB.record(root, project, cfg)
            got = "no error"
        except OSError:
            got = "OSError"
    finally:
        os.replace = real_replace
    check_eq("the interruption surfaces", got, "OSError")
    state = root / "state"
    check("no record file exists", not (state / "test-repo-base.json").exists())
    check_eq("no temp file is left behind either",
             [p.name for p in state.iterdir()] if state.exists() else [], [])
    check_eq("so nothing reads as recorded", TRB.load(root), None)
    check_eq("and the next S0 close records normally", TRB.record(root, project, cfg)["git"], "absent")
    TRB.measure_git = real_measure


# --- edge 9: the hook in stage_done.run --------------------------------------------------------

def s0_story(root, task):
    art = root / "qa-factory" / "artifacts" / task
    (art / "work").mkdir(parents=True, exist_ok=True)
    write(art / "pipeline.json", json.dumps({
        "ticket": task, "parent_feature": None, "size": None, "environment": "local",
        "environment_pending": False, "implementation_source": None, "warnings": [],
        "stages": {"S0": {"status": "running", "role": None, "digest": ""}},
        "gates": {}, "halts": []}))
    return art


def close_stage(task, status="done", stage="S0"):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = stage_done.run(task, stage, status, None, "preflight green, env=local", True)
        except Exception as exc:          # an exception that escapes the hook is a named failure here
            code = f"raised {type(exc).__name__}: {exc}"
    return code, out.getvalue(), err.getvalue()


def pipeline_stage(art, stage="S0"):
    return json.loads((art / "pipeline.json").read_text(encoding="utf-8"))["stages"][stage]["status"]


def base_file(art):
    return art / "state" / "test-repo-base.json"


def the_hook_in_stage_done_run():
    root = temp_project("qa-base-hook-")           # the project ROOT is the repository top
    real_line, real_measure = TRB.s0_line, TRB.measure_git
    try:
        make_repo(root)
        write(root / "tests" / "test_x.py", "def test_x():\n    pass\n")
        commit_all(root, "base")
        use_project(root)

        # the baseline: S0 closed with the hook doing nothing at all
        s0_story(root, "HK-BASE")
        TRB.s0_line = lambda *a, **k: "no-op"
        try:
            base_code, _, _ = close_stage("HK-BASE")
        finally:
            TRB.s0_line = real_line
        check_eq("(baseline: S0 closes with exit 0 when the hook does nothing)", base_code, 0)

        art = s0_story(root, "HK-OK")
        code, out, _ = close_stage("HK-OK")
        check_eq("S0 closes", code, base_code)
        check_eq("and the pipeline says so", pipeline_stage(art), "done")
        lines = [ln for ln in out.splitlines() if ln.startswith("test repository base")]
        check_eq("exactly one line about the base", len(lines), 1)
        check("it reads `test repository base: <head12> on <branch>, <n> uncommitted path(s)`",
              bool(re.fullmatch(r"test repository base: [0-9a-f]{12} on main, \d+ uncommitted path\(s\)", lines[0])),
              lines[0])
        check("the record exists", base_file(art).is_file())
        first = base_file(art).read_bytes()
        code, out, _ = close_stage("HK-OK")
        check_eq("a second S0 close still succeeds", code, base_code)
        check_in("and says the base is already recorded", "test repository base: already recorded at", out)
        check_eq("and keeps the file byte for byte", base_file(art).read_bytes(), first)

        art = s0_story(root, "HK-NOT-DONE")
        code, out, _ = close_stage("HK-NOT-DONE", status="running")
        check_eq("S0 `running` is not a close", code, 0)
        check("and records nothing", not base_file(art).exists())
        check_not_in("and prints nothing about the base", "test repository base", out)
        close_stage("HK-NOT-DONE", stage="S1", status="running")
        check("another stage records nothing", not base_file(art).exists())

        # a refused S0: the controller is initialised, so `done` is refused by the check at ~:480-502
        art = s0_story(root, "HK-REFUSED")
        Controller(art).apply("initialize", {
            "scope": [], "source_revision": "snapshot-hash",
            "known_paths": {"task_root": str(art)}, "idempotency_key": "init"})
        code, out, err = close_stage("HK-REFUSED")
        check_eq("the controller-managed S0 is refused as before", code, stage_done.EXIT_BAD_ARGS)
        check_in("with its own remedy", "code_only", err)
        check("a refused S0 records nothing: no file", not base_file(art).exists())
        check_not_in("and prints nothing about the base", "test repository base", out)

        def boom(*args, **kwargs):
            raise RuntimeError("boom")

        art = s0_story(root, "HK-BOOM")
        TRB.s0_line = boom
        try:
            code, out, err = close_stage("HK-BOOM")
        finally:
            TRB.s0_line = real_line
        check_eq("any exception in the hook: S0 closes with the exit code it would have had", code, base_code)
        check_eq("any exception in the hook: the stage is done", pipeline_stage(art), "done")
        check_in("any exception in the hook: one line says why",
                 "test repository base not recorded: RuntimeError: boom", out)
        check_eq("any exception in the hook: nothing was written", base_file(art).exists(), False)

        art = s0_story(root, "HK-NOGIT")
        with without_git():
            code, out, err = close_stage("HK-NOGIT")
        check_eq("no git on PATH: S0 closes with the same exit code as with git", code, base_code)
        check_eq("no git on PATH: and is done", pipeline_stage(art), "done")
        check_in("no git on PATH: the line says no commit was recorded and why",
                 "no commit recorded (git absent", out)
        rec = TRB.load(art)
        check_eq("no git on PATH: the record says git is absent, once", (rec or {}).get("git"), "absent")
        check_eq("no git on PATH: with no head", (rec or {}).get("head"), "")
    finally:
        TRB.s0_line, TRB.measure_git = real_line, real_measure
        cleanup(root)


# --- edge 11: the CLI reads and prints ----------------------------------------------------------

def the_cli_only_reads_and_prints(project, cfg):
    root = project
    use_project(root)
    art = task_root(root, TASK)
    rec = TRB.record(art, root, cfg)
    before = tree(root / "qa-factory")
    result = run_script("test_repo_base.py", "--task", TASK, "--json", cwd=root)
    check_eq("--json exits 0", result.returncode, 0)
    try:
        parsed = json.loads(result.stdout)
    except ValueError:
        parsed = "stdout is not JSON only: " + result.stdout[:200]
    check_eq("under --json stdout is JSON only, and it is the record", parsed, rec)
    text = run_script("test_repo_base.py", "--task", TASK, cwd=root)
    check_eq("text mode exits 0", text.returncode, 0)
    check_in("text mode names the head", rec["head"][:12], text.stdout)
    check_eq("the CLI wrote nothing (FR-45)", tree(root / "qa-factory"), before)
    (art / "state" / "test-repo-base.json").unlink()
    none = run_script("test_repo_base.py", "--task", TASK, "--json", cwd=root)
    check_eq("no record under --json: `null`, still JSON only", json.loads(none.stdout), None)
    none_text = run_script("test_repo_base.py", "--task", TASK, cwd=root)
    check_in("no record in text mode: says so and names the fallback", "readers compare with HEAD now",
             none_text.stdout)
    unknown = run_script("test_repo_base.py", "--task", "NO-SUCH-STORY", "--json", cwd=root)
    check_eq("an unknown task exits 2", unknown.returncode, 2)
    check_in("naming what was looked for", "no story `NO-SUCH-STORY`", unknown.stderr)
    check_in("and where", "NO-SUCH-STORY", unknown.stderr.split("looked for")[-1])
    check_eq("with nothing on stdout", unknown.stdout, "")


def main():
    if shutil.which("git") is None:
        check("git is available on this machine (this file needs it and does not skip)", False,
              "git is not on PATH: install git, or run this file where it is")
        finish("test repository base")
    tmp = temp_dir("qa-trb-")
    try:
        # one repository shaped like the real one (repository > project `test-harness`, tests_root
        # ".") serves every check that only reads it; git costs about 0.7 s a call on this machine
        project, cfg = make_project(tmp / "testproject1-sdk-cmp1", tests_root=".")
        a_subdirectory_project_gets_its_prefix_from_git(tmp, project, cfg)
        a_project_that_is_the_repository_top_has_an_empty_prefix(tmp)
        a_git_worktree_is_a_repository_too(tmp, project, cfg)
        a_tests_root_in_another_repository_is_recorded_as_that_repository(tmp)
        a_missing_tests_root_falls_back_to_the_project_root(project)
        the_dirty_list_covers_the_whole_repository(tmp)
        a_status_line_with_a_newline_in_a_name_is_read_whole()
        the_dirty_limit_is_2000_exactly(project, cfg)
        the_exclusion_does_not_move_the_dirty_limit(project, cfg)
        the_factory_folder_is_not_counted(tmp)
        a_late_recording_is_labelled_and_still_written(project, cfg)
        every_git_state_is_named_and_nothing_is_guessed(tmp)
        load_never_raises(tmp)
        an_interrupted_write_never_leaves_half_a_file(tmp)
        the_hook_in_stage_done_run()
        a_second_close_keeps_the_base_byte_for_byte(project, cfg)
        the_cli_only_reads_and_prints(project, cfg)
    finally:
        cleanup(tmp)
    finish("test repository base")


if __name__ == "__main__":
    main()
