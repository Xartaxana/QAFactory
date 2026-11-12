#!/usr/bin/env python3
"""t-622 (forge batch 4, F4-2 = B-309 (d)): ONE search for the project root.

Before this, six places walked up from a story to the nearest `qa-factory/config.json` each in its own words
(controller, judge, bug_records, dashboard_refresh, `resolve_runtime`, `project_for_task`), `critic_rollcall` and
`hooklib` had a seventh and an eighth, and the controller's walk answered the TASK ROOT when it found nothing - so
`{project_root}` of a dispatch packet could become the story's own folder. Now `runtime_paths.nearest_project` is the
one leaf; the old names stay as one-line delegates.

What this file proves (keys from docs/tasks/specs/t-617-f4-2-project-root.md, section 8 last):
  K1  the leaf: a marker AT the start, at the parent, nowhere (None); nested markers (the nearest wins); the marker is
      a FILE (a folder `config.json`, a `qa-factory` that is a file, `.git` in any form decide nothing); a file start;
      trailing slash and dot; a symlink / junction; an 8.3 start; the adversarial inputs (None, blank, NUL, a number,
      bytes, a 40 kB path, the drive root, a bare drive, a UNC path on Windows) never raise and never answer a folder
      without the marker - and never the working directory;
  K2  the names that delegate (`hooklib._nearest_project`, `critic_rollcall.project_root_of`) answer what the leaf
      answers; `names_project` (the controller's RUN gate asks it);
  K3  the census (AST over `scripts/*.py`): the only walk for the marker is `nearest_project`, plus the shrink-only
      allowlist of the walks outside this node. A walk restored inline anywhere in the package turns this red.

The census is also a command: `python -B test_runtime_paths.py --census <scripts dir>` prints the walks it finds there
and exits 1 when one is outside the allowlist (that is how the pre-fold tree is shown red).
"""
import ast
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import check, cleanup, finish, temp_dir  # noqa: E402

sys.path.insert(0, str(harness.SCRIPTS))
import critic_rollcall  # noqa: E402
import hooklib  # noqa: E402
import runtime_paths as RP  # noqa: E402

CLEAN: list = []
CWD0 = os.getcwd()
CONFIG = "config.json"


def scratch() -> Path:
    base = temp_dir("qa-rp-").resolve()
    CLEAN.append(base)
    return base


def mark(folder: Path) -> Path:
    """Make `folder` a project: `qa-factory/config.json` as a file (the harness's one writer of the marker)."""
    return harness.mark_project(folder)


def has_marker(folder: Path) -> bool:
    try:
        return (folder / "qa-factory" / CONFIG).is_file()
    except OSError:
        return False


def short_name(path) -> str | None:
    """The 8.3 spelling of an existing path, or None where the platform or the volume has none."""
    if os.name != "nt":
        return None
    import ctypes
    buffer = ctypes.create_unicode_buffer(2048)
    if not ctypes.windll.kernel32.GetShortPathNameW(str(path), buffer, 2048):
        return None
    return buffer.value if buffer.value.lower() != str(path).lower() else None


def link(target: Path, where: Path) -> bool:
    """A directory link where..: a junction on Windows (no privilege needed), a symlink elsewhere. False when the OS
    refuses (the caller prints a reason and the key does not run)."""
    try:
        if os.name == "nt":
            done = subprocess.run(["cmd", "/c", "mklink", "/J", str(where), str(target)], capture_output=True, text=True)
            return done.returncode == 0 and where.exists()
        os.symlink(target, where, target_is_directory=True)
        return True
    except (OSError, ValueError):
        return False


def skipped(key: str, reason: str) -> None:
    """A key that cannot run here says so; it is never a PASS."""
    print(f"skipped: {key} - {reason}")


# --- K1: the leaf -------------------------------------------------------------------------------------------------------

def k1_boundaries_and_nesting() -> None:
    base = scratch()
    outer = mark(base / "outer")
    deep = outer / "a" / "b" / "c"
    deep.mkdir(parents=True)
    check("K1 AT: a marker at the start itself returns the start", RP.nearest_project(outer) == outer)
    check("K1 BEYOND: a marker only at the parent returns the parent", RP.nearest_project(outer / "a") == outer)
    check("K1 BEYOND: ...and three levels up", RP.nearest_project(deep) == outer)
    lone = base / "lone" / "x"
    lone.mkdir(parents=True)
    check("K1 none: no marker up to the root is None, not the start and not a cwd answer", RP.nearest_project(lone) is None)
    inner1 = mark(outer / "a" / "inner1")
    (inner1 / "z").mkdir()
    check("K1 nested (depth 1): the NEAREST marker wins over the outer one", RP.nearest_project(inner1 / "z") == inner1)
    inner3 = mark(outer / "a" / "b" / "c" / "d")
    (inner3 / "e" / "f").mkdir(parents=True)
    check("K1 nested (depth 3): the nearest wins, the outer one is never reached", RP.nearest_project(inner3 / "e" / "f") == inner3)
    os.chdir(outer)
    try:
        check("K1 no cwd fallback: a start outside every project is None even when the working directory is inside one",
              RP.nearest_project(lone) is None)
        check("K1 no cwd fallback: a relative start is read against the working directory (inside the project)",
              RP.nearest_project(Path("a")) == outer)
    finally:
        os.chdir(CWD0)


def k1_the_fixture_helpers_make_a_project_by_the_marker_alone() -> None:
    """t-774 (the class behind the red CI after F4-2): a test fixture is a project exactly when it carries the marker. The
    negative control pins only `nearest_project` is None: the marker taken out of a `temp_project` root, nothing else
    touched, and neither the root nor a story below it is a project. The "unknown" road a consumer takes on that None
    (t-617 section 8.2: no project is `unknown`, not a closure) is pinned elsewhere: `test_controller_rework_jobs_guard` (a story under
    no project closes nothing) and `test_controller_paths` (no project at all)."""
    root = harness.temp_project("qa-rp-helper-").resolve()
    CLEAN.append(root)
    story = root / "qa-factory" / "artifacts" / "TASK-1"
    story.mkdir(parents=True)
    check("K1 helper: a `temp_project` root is a project, seen from the root and from a story below it",
          RP.nearest_project(root) == root and RP.nearest_project(story) == root)
    plain = scratch() / "plain"
    plain.mkdir()
    check("K1 helper: a plain folder is no project, and `mark_project` makes it one (the `TemporaryDirectory` form of a fixture)",
          RP.nearest_project(plain) is None and RP.nearest_project(harness.mark_project(plain)) == plain)
    (root / "qa-factory" / CONFIG).unlink(missing_ok=True)      # missing_ok: a helper that wrote no marker fails the checks, it does not crash the run
    check("K1 helper, negative control: the marker removed, the same root and story are no project - whatever else `temp_project` built",
          (root / "qa-factory" / "state").is_dir() and RP.nearest_project(root) is None and RP.nearest_project(story) is None)


def k1_the_marker_is_a_file() -> None:
    base = scratch()
    only_home = base / "only-home"
    (only_home / "qa-factory").mkdir(parents=True)
    check("K1 file only: `qa-factory/` without a config is not a project", RP.nearest_project(only_home) is None)
    as_dir = base / "dir-config"
    (as_dir / "qa-factory" / CONFIG).mkdir(parents=True)
    check("K1 file only: `config.json` that is a DIRECTORY is not a project", RP.nearest_project(as_dir) is None)
    outer = mark(base / "outer")
    inner = outer / "inner"
    (inner / "qa-factory" / CONFIG).mkdir(parents=True)
    check("K1 file only: ...and the walk goes on to the real project above it", RP.nearest_project(inner) == outer)
    home_file = outer / "file-home"
    home_file.mkdir()
    (home_file / "qa-factory").write_text("x", encoding="utf-8")
    check("K1 file only: a `qa-factory` that is a FILE is not a project (the walk goes on)", RP.nearest_project(home_file) == outer)
    git_file = outer / "with-git-file"
    git_file.mkdir()
    (git_file / ".git").write_text("gitdir: ../elsewhere", encoding="utf-8")
    check("K1 .git as a FILE: ignored, the marker decides", RP.nearest_project(git_file) == outer)
    nested_git = base / "unmarked" / ".git" / ".git"
    nested_git.mkdir(parents=True)
    check("K1 .git inside .git, no marker anywhere: None - git is never read", RP.nearest_project(nested_git) is None)
    marked_git = mark(base / "marked-git")
    (marked_git / ".git" / ".git").mkdir(parents=True)
    check("K1 .git inside .git under a marker: the marker's folder, git is never read",
          RP.nearest_project(marked_git / ".git" / ".git") == marked_git)
    afile = outer / "a-story.md"
    afile.write_text("x", encoding="utf-8")
    check("K1 a start that is a FILE: the project above it", RP.nearest_project(afile) == outer)
    check("K1 a start that does not exist: the project above where it would be", RP.nearest_project(outer / "no" / "such") == outer)


def k1_spellings_and_links() -> None:
    base = scratch()
    project = mark(base / "my project with spaces")
    (project / "sub").mkdir()
    for label, spelled in (("a trailing separator", str(project / "sub") + os.sep), ("a trailing dot", str(project / "sub") + os.sep + "."),
                           ("a dotted detour", str(project / "sub" / ".." / "sub")), ("a str with spaces", str(project / "sub"))):
        check(f"K1 spelling ({label}): the same project as the plain spelling", RP.nearest_project(spelled) == project, str(RP.nearest_project(spelled)))
    short = short_name(project)
    if short is None:
        skipped("K1 8.3 start", "no 8.3 alias for the scratch folder on this platform or volume")
    else:
        check("K1 8.3 start: resolved to the long spelling, the same project", RP.nearest_project(Path(short) / "sub") == project,
              str(RP.nearest_project(Path(short) / "sub")))
    outside = base / "outside"
    outside.mkdir()
    pointer = base / "pointer-into-project"
    if link(project / "sub", pointer):
        check("K1 link: a link that lands INSIDE a project answers that project (the real path's ancestors)", RP.nearest_project(pointer) == project)
    else:
        skipped("K1 link into a project", "the OS refused to make a directory link")
    escape = project / "escape"
    if link(outside, escape):
        check("K1 link: a link INSIDE a project that lands outside every project is None - the project it sits in is not adopted",
              RP.nearest_project(escape) is None, str(RP.nearest_project(escape)))
    else:
        skipped("K1 link out of a project", "the OS refused to make a directory link")


def k1_never_raises() -> None:
    base = scratch()
    project = mark(base / "proj")
    answers = {}
    for label, value in (("None", None), ("an empty string", ""), ("a blank string", "   "), ("a tab and a newline", "\t\n"),
                         ("a NUL", "\0"), ("a NUL inside a path", str(project) + "\0x"), ("a number", 5), ("a float", 1.5),
                         ("bytes", b"proj"), ("a list", [str(project)]), ("a dict", {"a": 1}), ("an object", object())):
        try:
            answers[label] = RP.nearest_project(value)
        except Exception as exc:                                              # noqa: BLE001
            answers[label] = exc
    check("K1 adversarial: None, blank, NUL, a number, bytes, a list, a dict and an object are None - nothing raises, nothing is guessed",
          all(got is None for got in answers.values()), str({k: v for k, v in answers.items() if v is not None}))
    os.chdir(project)
    try:
        check("K1 blank start with the working directory INSIDE a marked project: still None - a blank is not the cwd",
              RP.nearest_project("") is None and RP.nearest_project("   ") is None and RP.nearest_project(None) is None)
    finally:
        os.chdir(CWD0)
    long_path = str(project) + os.sep + os.sep.join(["segment-" + "x" * 30] * 1000)
    try:
        got = RP.nearest_project(long_path)
        raised = ""
    except Exception as exc:                                                  # noqa: BLE001
        got, raised = None, repr(exc)
    check("K1 adversarial: a 40 kB path does not raise, and answers None or a folder with the marker",
          not raised and (got is None or has_marker(got)), raised or str(got)[:200])
    anchor = Path(Path.cwd().anchor)
    if has_marker(anchor):
        skipped("K1 drive root", f"{anchor} itself carries qa-factory/config.json on this machine")
    else:
        check("K1 adversarial: the drive root (no marker there) is None", RP.nearest_project(anchor) is None)
    if os.name == "nt":
        drive = Path.cwd().drive
        try:
            got = RP.nearest_project(drive)
            raised = ""
        except Exception as exc:                                              # noqa: BLE001
            got, raised = None, repr(exc)
        check("K1 adversarial: a bare drive (`C:`) does not raise, and answers None or a folder with the marker",
              not raised and (got is None or has_marker(got)), raised or str(got))
    else:
        skipped("K1 bare drive", "a bare `C:` is a Windows spelling")
    if os.name != "nt":
        skipped("K1 UNC path", "a UNC share is a Windows spelling")
    elif os.environ.get("CI") or os.environ.get("GITLAB_CI"):
        skipped("K1 UNC path", "CI runners pay a network timeout on a host that does not answer")
    else:
        unc = "\\\\" + "qa-no-such-host-t622" + "\\share\\story"
        began = time.monotonic()
        try:
            got = RP.nearest_project(unc)
            raised = ""
        except Exception as exc:                                              # noqa: BLE001
            got, raised = None, repr(exc)
        check("K1 adversarial: a UNC path of a host that does not exist is None (no exception; the wait is the network's, measured "
              f"{time.monotonic() - began:.1f} s)", not raised and got is None, raised or str(got))


# --- K2: the names that delegate, and the gate's question -------------------------------------------------------------

def k2_delegates() -> None:
    base = scratch()
    project = mark(base / "proj")
    story = project / "qa-factory" / "artifacts" / "QA-1"
    story.mkdir(parents=True)
    outside = base / "outside" / "QA-2"
    outside.mkdir(parents=True)
    afile = story / "state.json"
    afile.write_text("{}", encoding="utf-8")
    for name, find in (("hooklib._nearest_project", hooklib._nearest_project), ("critic_rollcall.project_root_of", critic_rollcall.project_root_of)):
        check(f"K2 {name}: the story's project", find(story) == project and find(str(story)) == project and find(afile) == project)
        check(f"K2 {name}: a story outside every project is None", find(outside) is None)
        check(f"K2 {name}: no start at all is None (never the working directory)", find(None) is None and find("") is None)
    os.chdir(project)
    try:
        check("K2 hooklib._nearest_project: a blank start is None even with the working directory inside a project (it was the cwd before)",
              hooklib._nearest_project("") is None)
    finally:
        os.chdir(CWD0)
    check("K2 resolve_runtime: finds the story's project through the leaf", RP.resolve_runtime(story)["project_root"] == str(project))
    try:
        RP.resolve_runtime(outside)
        refused = ""
    except ValueError as exc:
        refused = str(exc)
    check("K2 resolve_runtime: a story outside every project is still the same refusal", "qa-factory/config.json" in refused, refused)


def k2_names_project() -> None:
    cases = [("a {project_root} token", {"project_root": "{project_root}"}, True),
             ("a {project_root} path in another key", {"root": "{task_root}", "scripts_root": "{project_root}/x/y"}, True),
             ("a token nested in a map", {"entrypoints": {"controller": "{project_root}/c.py"}}, True),
             ("an absolute project_root (forward slashes)", {"project_root": "C:/proj"}, True),
             ("an absolute project_root (POSIX)", {"project_root": "/srv/proj"}, True),
             ("an absolute project_root (backslashes)", {"project_root": "C:" + chr(92) + "proj"}, True),
             ("no project at all (the driver's own packet)", {"root": "/srv/task"}, False),
             ("a task token only", {"root": "{task_root}", "project_root": "{task_root}/.."}, False),
             ("a relative project_root", {"project_root": "proj"}, False),
             ("a list where a path should be", {"project_root": []}, False),
             ("an empty map", {}, False), ("not a map: None", None, False), ("not a map: a string", "{project_root}", False),
             ("not a map: a list", ["{project_root}"], False)]
    for label, packet, expected in cases:
        check(f"K2 names_project ({label}): {expected}", RP.names_project(packet) is expected, str(RP.names_project(packet)))


# --- K3: the census ---------------------------------------------------------------------------------------------------
# A walk for the project marker = a loop over a `.parents` (not subscripted) or a `while` that climbs `x = x.parent`, with
# INSIDE that loop a `config.json` constant, a module / hooklib constant equal to it, or a call to a same-module helper
# that holds one. Keyed by (file, innermost function). A pair predicate (any `.parents` plus any `config.json` in one
# function) counted four functions that are not walks (config_contract.template_path, factory_dashboard.main,
# guard_pre_tool.case_store_check, host_probe.fingerprint) and missed `hooklib._nearest_project`; the negative controls
# below are those shapes.

# The walks that are NOT in this node and stay (t-617 section 8.4). SHRINK ONLY: an entry whose walk is gone must be
# deleted (a stale entry fails the key below), and a new walk is not added here - it calls `nearest_project`.
OUTSIDE_WALKS = {
    ("contract.py", "_config_location"), ("gate_brief.py", "_project_root_of"),
    ("host_probe.py", "_not_a_project"), ("launch_check.py", "_find_project_root"),
    ("manual_capture.py", "load_config"), ("migrate_artifacts.py", "_find_project_root"), ("question_stop.py", "_find_config"),
    ("stand_gaps.py", "project_of"), ("story_progress.py", "_project_of"),
}
OUTSIDE_WALKS_MAX = 9
THE_LEAF = ("runtime_paths.py", "nearest_project")


def _config_names(tree) -> set:
    """Module-level names bound to exactly "config.json"."""
    return {target.id for node in tree.body if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant)
            and node.value.value == CONFIG for target in node.targets if isinstance(target, ast.Name)}


def _holds_config(node, names) -> bool:
    for sub in ast.walk(node):
        if isinstance(sub, ast.Constant) and isinstance(sub.value, str) and CONFIG in sub.value:
            return True
        if isinstance(sub, ast.Name) and sub.id in names:
            return True
        if isinstance(sub, ast.Attribute) and sub.attr in names:          # `hooklib.CONFIG_PATH_NAME`
            return True
    return False


def walks_in(text: str, hook_names: set) -> set:
    """The names of the functions in `text` that walk up for the config marker, by the predicate above."""
    tree = ast.parse(text)
    names = _config_names(tree) | hook_names
    parent_of = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
    helpers = {node.name for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
               and _holds_config(node, names)}
    found = set()

    def over_parents(iterable) -> bool:
        for sub in ast.walk(iterable):
            if isinstance(sub, ast.Attribute) and sub.attr == "parents":
                up = parent_of.get(sub)
                if not (isinstance(up, ast.Subscript) and up.value is sub):
                    return True
        return False

    def climbs(loop) -> bool:
        for sub in ast.walk(loop):
            if (isinstance(sub, ast.Assign) and isinstance(sub.value, ast.Attribute) and sub.value.attr == "parent"
                    and isinstance(sub.value.value, ast.Name)
                    and any(isinstance(t, ast.Name) and t.id == sub.value.value.id for t in sub.targets)):
                return True
        return False

    def inside(nodes) -> bool:
        for node in nodes:
            if _holds_config(node, names):
                return True
            for sub in ast.walk(node):
                if isinstance(sub, ast.Call):
                    func = sub.func
                    if isinstance(func, ast.Name) and func.id in helpers:
                        return True
                    if (isinstance(func, ast.Attribute) and func.attr in helpers and isinstance(func.value, ast.Name)
                            and func.value.id in ("self", "cls")):
                        return True
        return False

    class Visitor(ast.NodeVisitor):
        def __init__(self):
            self.stack = []

        def where(self) -> str:
            return self.stack[-1] if self.stack else "<module>"

        def function(self, node):
            self.stack.append(node.name)
            self.generic_visit(node)
            self.stack.pop()

        visit_FunctionDef = visit_AsyncFunctionDef = function

        def visit_For(self, node):
            if over_parents(node.iter) and inside(node.body + node.orelse):
                found.add(self.where())
            self.generic_visit(node)

        def visit_While(self, node):
            if climbs(node) and inside([node.test] + node.body + node.orelse):
                found.add(self.where())
            self.generic_visit(node)

        def comprehension(self, node):
            parts = [node.key, node.value] if isinstance(node, ast.DictComp) else [node.elt]
            for generator in node.generators:
                if over_parents(generator.iter) and inside(parts + list(generator.ifs)):
                    found.add(self.where())
            self.generic_visit(node)

        visit_ListComp = visit_SetComp = visit_GeneratorExp = visit_DictComp = comprehension

    Visitor().visit(tree)
    return found


def census(directory) -> set:
    """{(file name, function)} of every walk for the marker in `directory/*.py`."""
    directory = Path(directory)
    hook_names = _config_names(ast.parse((directory / "hooklib.py").read_text(encoding="utf-8")))
    out = set()
    for path in sorted(directory.glob("*.py")):
        out |= {(path.name, name) for name in walks_in(path.read_text(encoding="utf-8"), hook_names)}
    return out


def k3_controls() -> None:
    hook = {"CONFIG_PATH_NAME"}
    positives = {
        "a for loop over (root, *root.parents) with the literal (the controller's old walk)":
            "def f(root):\n    for c in (root, *root.parents):\n        if (c / 'qa-factory' / 'config.json').is_file():\n            return c\n",
        "a generator over task.parents inside next() (resolve_runtime's old walk)":
            "def f(task):\n    return next((p for p in (task, *task.parents) if (p / 'qa-factory/config.json').is_file()), None)\n",
        "a for loop over task.parents only (the dashboard's old fallback)":
            "def f(task):\n    for a in task.parents:\n        if (a / 'qa-factory/config.json').is_file():\n            return a\n",
        "a while loop climbing x = x.parent":
            "def f(p):\n    while p != p.parent:\n        if (p / 'qa-factory' / 'config.json').exists():\n            return p\n        p = p.parent\n",
        "a loop that calls a same-module helper holding the literal (hooklib's old shape)":
            "def _carries(c):\n    return (c / 'qa-factory' / 'config.json').is_file()\n\ndef f(s):\n    for c in (s, *s.parents):\n        if _carries(c):\n            return c\n",
        "a loop that uses a module constant equal to it":
            "NAME = 'config.json'\n\ndef f(s):\n    for c in s.parents:\n        if (c / NAME).is_file():\n            return c\n",
        "a loop that uses hooklib's constant":
            "def f(s):\n    for c in s.parents:\n        if (c / hooklib.CONFIG_PATH_NAME).is_file():\n            return c\n",
        "a method (self.helper) holding the literal":
            "class K:\n    def has(self, c):\n        return (c / 'qa-factory' / 'config.json').is_file()\n\n    def f(self, s):\n        for c in s.parents:\n            if self.has(c):\n                return c\n",
    }
    for label, source in positives.items():
        check(f"K3 census (positive control): {label} is a walk", walks_in(source, hook) != set())
    negatives = {
        "`.parents` subscripted and the literal outside any loop (config_contract.template_path)":
            "def f():\n    return Path(__file__).resolve().parents[1] / 'references' / 'templates' / 'config.json'\n",
        "a parents loop with the literal OUTSIDE the loop (factory_dashboard.main)":
            "def f(path):\n    cfg = path / 'qa-factory' / 'config.json'\n    for p in path.parents:\n        print(p)\n    return cfg\n",
        "a loop over a list that holds the literal, no parents (guard_pre_tool.case_store_check)":
            "def f(root):\n    for rel in ('qa-factory/config.json', 'x'):\n        if (root / rel).is_file():\n            return rel\n",
        "a parents loop that tests something else (host_probe.fingerprint)":
            "def f(p):\n    for a in p.parents:\n        if (a / '.git').exists():\n            return a\n    return load('config.json')\n",
        "`.parents[1]` inside a loop over a list of paths":
            "def f(paths):\n    for p in paths:\n        if (p.parents[1] / 'qa-factory' / 'config.json').is_file():\n            return p\n",
        "a while loop that climbs, with no marker in it":
            "def f(p):\n    while p != p.parent:\n        if (p / '.git').exists():\n            return p\n        p = p.parent\n",
    }
    for label, source in negatives.items():
        check(f"K3 census (negative control): {label} is NOT a walk", walks_in(source, hook) == set(), str(walks_in(source, hook)))


def k3_census() -> None:
    found = census(harness.SCRIPTS)
    outside = found - {THE_LEAF}
    check("K3 census: the leaf itself is found (the predicate sees the one walk that is meant to exist)", THE_LEAF in found, str(sorted(found)))
    check("K3 census: every other walk in scripts/*.py is on the allowlist of walks outside this node - a walk restored inline "
          "(or a new one) calls `runtime_paths.nearest_project` instead", outside <= OUTSIDE_WALKS, str(sorted(outside - OUTSIDE_WALKS)))
    check("K3 census: shrink-only - an allowlisted walk that no longer exists is deleted from the list", OUTSIDE_WALKS <= outside,
          str(sorted(OUTSIDE_WALKS - outside)))
    check(f"K3 census: the allowlist never grows past {OUTSIDE_WALKS_MAX}", len(OUTSIDE_WALKS) <= OUTSIDE_WALKS_MAX, str(len(OUTSIDE_WALKS)))
    for name in ("controller.py", "judge.py", "bug_records.py", "dashboard_refresh.py", "critic_rollcall.py", "hooklib.py"):
        check(f"K3 census: {name} has no walk of its own", not any(file == name for file, _fn in found), str(sorted(found)))
    check("K3 census: runtime_paths.py has exactly one (`nearest_project`)", {fn for file, fn in found if file == "runtime_paths.py"} == {"nearest_project"})


def k4_known_artifacts_grounding() -> None:
    """G1-3 (t-988 L-2.K row, M-3 of the code critic t-1077): a role reaches the grounding table by the key `grounding`,
    and its path is the registry's (`work/grounding.yaml`), never spelled in the table."""
    check("K4 KNOWN_ARTIFACTS holds `grounding` -> grounding.yaml", RP.KNOWN_ARTIFACTS.get("grounding") == "grounding.yaml",
          str(RP.KNOWN_ARTIFACTS.get("grounding")))
    base = temp_dir("rp-grounding-")
    CLEAN.append(base)
    items = dict(RP._artifact_items(base))
    check("K4 the grounding path is the registry's work/grounding.yaml",
          Path(items.get("grounding", "")) == base / "work" / "grounding.yaml", str(items.get("grounding")))


def main() -> None:
    if len(sys.argv) == 3 and sys.argv[1] == "--census":
        found = census(sys.argv[2])
        for file, fn in sorted(found):
            print(f"{file}: {fn}" + ("" if (file, fn) in OUTSIDE_WALKS or (file, fn) == THE_LEAF else "   <- a walk inside the node"))
        extra = found - OUTSIDE_WALKS - {THE_LEAF}
        print(f"{len(found)} walk(s); {len(extra)} beyond the leaf and the allowlist")
        sys.exit(1 if extra else 0)
    try:
        k1_boundaries_and_nesting()
        k1_the_fixture_helpers_make_a_project_by_the_marker_alone()
        k1_the_marker_is_a_file()
        k1_spellings_and_links()
        k1_never_raises()
        k2_delegates()
        k2_names_project()
        k3_controls()
        k3_census()
        k4_known_artifacts_grounding()
    finally:
        os.chdir(CWD0)
        for base in CLEAN:
            cleanup(base)
    finish("test_runtime_paths")


if __name__ == "__main__":
    main()
