#!/usr/bin/env python3
"""regression_scope.py - the checks of the plan's `## Recommended regression` section (RG1-2, RG1-1, P24).

The strategist WRITES the list, this module only checks it (FR-47, FR-49): the code never composes a regression list and never
runs one. The section's shape is

    ## Recommended regression
    Command: <the project's own test command, as the project runs it> <target> <target>
    - `<path>` (blast:B-3, blast:B-5) - stand: <what it needs | no stand requirements>
    Developers: <component checks>

or `No regression: <reason>` alone. Item paths are relative to `tests_root`. The section is read through
`delivery_verdict.regression_lines` (AR-13), the one reader.

Direction of the error (FR-59): naming as regression a test that is not on the main branch is refused; letting a file pass because
the main branch could not be read is allowed. An unknown main branch silences check 8 and nothing else, and the report (S8) says so.
A regression list never holds a delivery (it is a recommendation to the person, P24).

    regression_scope.py --task <id> --check     # exit 0 (the section holds) / 1 (problems, one line each) / 3 (could not run)
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

COMMAND = re.compile(r"^\s*(?:[-*]\s+)?Command:\s*(.*?)\s*$", re.IGNORECASE)
NO_REGRESSION = re.compile(r"^\s*(?:[-*]\s+)?No regression:\s*(.*?)\s*$", re.IGNORECASE)
ITEM = re.compile(r"^\s*[-*]\s+`([^`]+)`(.*)$")
STAND = re.compile(r"\bstand:\s*(\S.*)$", re.IGNORECASE)
ABSOLUTE = re.compile(r"^(?:/|~|\\\\|[A-Za-z]:[\\/])")
FALLBACK_REFS = ("origin/main", "origin/master")


# --- the main branch ----------------------------------------------------------------------------------------------

def _git(root, *args):
    import gate_preflight
    return gate_preflight._git(root, *args)


def base_root(project_root, cfg) -> Path:
    """The folder git is asked from: `tests_root` when it is a directory, else the project (as `test_repo_base.measure_git`)."""
    project = Path(project_root).resolve()
    configured = str((cfg if isinstance(cfg, dict) else {}).get("tests_root") or ".")
    tests = (project / configured).resolve()
    return tests if tests.is_dir() else project


def _exists(root, ref: str) -> bool:
    return bool(ref) and _git(root, "rev-parse", "--verify", "--quiet", ref) is not None


def _declared_branch(root: Path, project_root, cfg) -> str:
    """The declared default branch of the repository `root` lies in: `project_inventory`'s `declared_default_branch`, the one
    reader (a string only; a list or None is no declaration). Local reads only."""
    try:
        import project_inventory
        repos = project_inventory.build_inventory(cfg if isinstance(cfg, dict) else {}, Path(project_root))["repositories"]
    except Exception:  # noqa: BLE001 - no inventory is no declaration; the fallbacks follow
        return ""
    names = [r for r in repos if isinstance(r.get("declared_default_branch"), str) and r["declared_default_branch"].strip()]
    inside = [r for r in names if r.get("path") and (Path(r["path"]) == root or Path(r["path"]) in root.parents)]
    chosen = (inside or names or [{}])[0]
    return str(chosen.get("declared_default_branch") or "").strip()


def main_ref(project_root, cfg) -> tuple:
    """`(ref, why)`: the remote-tracking ref of the main branch, or `("", why)`. Order: `origin/HEAD`, the declared default branch
    as `origin/<b>`, `origin/main`, `origin/master`; each must resolve locally. No fetch, no network."""
    root = base_root(project_root, cfg)
    head = _git(root, "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD")
    if head and _exists(root, head):
        return head, "origin/HEAD"
    declared = _declared_branch(root, project_root, cfg)
    if declared and _exists(root, f"origin/{declared}"):
        return f"origin/{declared}", "the declared default branch"
    for ref in FALLBACK_REFS:
        if _exists(root, ref):
            return ref, "a conventional name"
    return "", ("git could not name the main branch (no origin/HEAD, no declared default branch, no origin/main or origin/master "
                f"in {root})")


def on_main(root, ref: str, paths) -> dict:
    """`{path: True | False | None}`: is each path in the tree of `ref`. `None` is unknown (no ref, git cannot answer, a path outside
    the repository), never False: `ls-tree` answers an absent path with an empty line and a failure with None, so the two stay apart
    (`cat-file` collapsed them into one). `ls-tree` reads paths from the cwd, so a tests root below the repository's top works."""
    out = {}
    for path in paths:
        text = normalize(path)
        if not ref or not text or ".." in text.split("/") or ABSOLUTE.match(text):
            out[path] = None
            continue
        answer = _git(root, "ls-tree", "--name-only", ref, "--", text)
        out[path] = None if answer is None else bool(answer)
    return out


# --- the section --------------------------------------------------------------------------------------------------

def normalize(value) -> str:
    """A path or a command word in one spelling: quotes off, `\\` as `/`, no leading `./`, no trailing `/`."""
    text = str(value or "").strip().strip("\"'`").replace("\\", "/")
    while text.startswith("./"):
        text = text[2:]
    return text.rstrip("/")


def parse(lines) -> dict:
    """The parts of the section: `runs` (the `Command:` lines' text after `Command:`), `items` ((path as written, the rest of the line)), `none`
    (the text after each `No regression:`). A line of another shape is not read (`Developers:`, prose)."""
    out = {"runs": [], "items": [], "none": []}
    for line in lines or []:
        for key, pattern in (("runs", COMMAND), ("none", NO_REGRESSION)):
            hit = pattern.match(line)
            if hit:
                out[key].append(hit.group(1))
                break
        else:
            item = ITEM.match(line)
            if item:
                out["items"].append((item.group(1).strip(), item.group(2)))
    return out


def targets(lines) -> list:
    """The paths of the section's ITEMS, normalized, never taken from a command (the runner's syntax is not parsed, AR-1)."""
    return [normalize(path) for path, _rest in parse(lines)["items"]]


def _words(command: str) -> list:
    return [normalize(word) for word in command.split()]


def _shape(sec: dict) -> list:
    """The problems of the section's parts: an empty section, the `No regression:` line and what must not stand with it."""
    out, mixed = [], bool(sec["runs"] or sec["items"])
    for reason in sec["none"]:
        if not reason:
            out.append("`No regression:` has no reason. Expected: `No regression: <why nothing existing defends this change>`.")
    if sec["none"] and mixed:
        out.append("The section has `No regression:` and also a `Command:` or an item. Expected: either the list or "
                   "`No regression: <reason>`, not both; drop the one that is wrong.")
    if not sec["none"] and not mixed:
        out.append("The section names no test and no `No regression: <reason>` line. Expected: `Command:` plus an item per test "
                   "path, or `No regression: <reason>`; silence is not an answer.")
    elif not sec["none"] and not (sec["runs"] and sec["items"]):
        out.append("The section has " + ("items but no `Command:` line" if sec["items"] else "a `Command:` line but no items")
                   + ". Expected: one `Command:` per runner and one `- `<path>` ... - stand: ...` item per test path.")
    return out


def _lists(sec: dict) -> list:
    """The problems of the paths against the `Command:` lines: a repeat, a file under another item's folder, a path in no command
    or in two, two equal commands, the factory's own scripts in a command, an absolute path."""
    out, paths = [], [(raw, normalize(raw)) for raw, _rest in sec["items"]]
    forms = [p for _raw, p in paths]
    for index, (raw, path) in enumerate(paths):
        base, _sep, node = path.partition("::")
        for other in forms[:index]:
            ob, _s, on = other.partition("::")
            if other == path or (ob == base and (not node or not on)):
                out.append(f"`{raw}` is listed twice (`a.py` and `a.py::t` count as one). Expected: each file once; drop the repeat.")
                break
        for other in forms:
            if other and "::" not in other and other != path and base.startswith(other + "/"):
                out.append(f"`{raw}` lies under the folder `{other}`, which is an item too. Expected: a file once; keep the folder "
                           "or the file.")
                break
    words = [w for command in sec["runs"] for w in _words(command)]
    for raw, path in paths:
        count = words.count(path)
        if ABSOLUTE.match(raw.strip()):
            out.append(f"`{raw}` is an absolute path. Expected: a path from the tests root (the report is read on another machine).")
        elif count == 0:
            out.append(f"`{raw}` stands in no `Command:` line. Expected: every item is a word of its runner's command, "
                       "and the command is a `Command:` line, not an item.")
        elif count > 1:
            out.append(f"`{raw}` stands in the commands {count} times. Expected: every file once.")
    squeezed = [" ".join(c.split()) for c in sec["runs"]]
    if len(set(squeezed)) < len(squeezed):
        out.append("Two `Command:` lines are the same. Expected: one line per runner.")
    if any("CLAUDE_PLUGIN_ROOT" in c or "run_suite.py" in c for c in sec["runs"]):
        out.append("A `Command:` runs the factory's scripts (`run_suite.py`, `CLAUDE_PLUGIN_ROOT`): the plugin is not on the "
                   "reader's machine. Expected: the project's own test command, as the project runs it.")
    return out


def _stands(sec: dict) -> list:
    return [f"`{raw}` has no `stand:`. Expected: `- `{raw}` (blast:B-n) - stand: <what it needs | no stand requirements>`."
            for raw, rest in sec["items"] if not STAND.search(rest)]


def _absent(sec: dict, project_root, cfg) -> list:
    """Check 8: an item whose file is NOT on the main branch (False; an unknown is silent, FR-59)."""
    ref, _why = main_ref(project_root, cfg)
    bases = list(dict.fromkeys(normalize(raw).partition("::")[0] for raw, _rest in sec["items"]))
    found = on_main(base_root(project_root, cfg), ref, bases)
    return [f"{base} is not on {ref}: regression names tests that already exist; drop it (a test of this story is listed by the "
            "report on its own)" for base in bases if found.get(base) is False]


def problems(task_root, project_root, cfg) -> list:
    """Every problem of the plan's regression section, one string each (what is wrong, what is expected, how to fix it, FR-1)."""
    import contract as C
    import delivery_verdict as DV
    lines = DV.regression_lines(C.read_text(C.artifact(Path(task_root), "test-plan.md")))
    if not lines:
        return ["no `## Recommended regression` in test-plan.md: write the list, or `No regression: <reason>`"]
    sec = parse(lines)
    out = _shape(sec)
    if sec["none"] and not (sec["runs"] or sec["items"]):
        return out
    return out + _lists(sec) + _stands(sec) + _absent(sec, project_root, cfg)


# --- the command line ---------------------------------------------------------------------------------------------

def project_config(project_root) -> dict:
    """The project's `qa-factory/config.json`; `{}` when absent or unreadable (every reader then takes its default, AR-3)."""
    import hooklib
    try:
        path = Path(project_root) / "qa-factory" / "config.json"
    except TypeError:         # a root that is no path at all: nothing there
        return {}
    return hooklib.read_json(path, {}, errors=Exception, kind=dict)      # THE reader (G5): any failure, or another type, is {}


def main(argv=None) -> int:
    import hooklib
    ap = argparse.ArgumentParser(description="Check the plan's Recommended regression section")
    ap.add_argument("--task", default=None, help="ticket id")
    ap.add_argument("--root", default=None, help="project root (default: the current project)")
    ap.add_argument("--task-root", dest="task_root", default=None, help="the story's artifacts dir")
    ap.add_argument("--check", action="store_true", required=True, help="exit 1 with one line per problem")
    args = hooklib.exact_options(ap).parse_args(argv)
    story = hooklib.story_cli("regression_scope.py", key=args.task, root=args.task_root, project=args.root)
    try:
        import runtime_paths
        project = runtime_paths.project_for_task(story, hint=args.root)
        cfg = project_config(project)
        found = problems(story, project, cfg)
        ref, why = main_ref(project, cfg)
    except Exception as exc:  # noqa: BLE001 - a check that could not run is said, never a pass
        print(f"UNREADABLE: regression_scope could not complete ({type(exc).__name__}: {exc})")
        return 3
    for line in found:
        print("- " + line)
    if not found:
        print("OK: the regression section holds" + ("" if ref else f"; main branch unknown ({why}), paths not checked against it"))
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
