"""Shared hook code: stdin event reading, frontmatter parsing, config, root resolution."""
import bisect
import contextlib
import functools
import json
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path, PurePath
from typing import NamedTuple

# Windows console codepages (cp1251/cp866) cannot fit all message characters;
# a guard that crashes while printing would fail to block the write (F-2).
# Force UTF-8 with replacement. The import is guarded for the same reason: a missing
# console_io.py must not make a guard fail open.
try:
    import console_io
    console_io.utf8_stdio(stdin=True)
except ImportError:
    pass

# Two roots (unified-factory-design v0): the plugin ships CODE (scripts/, agents/,
# references/) and never writes into the project it is installed into; the project
# carries only its own STATE under <project>/qa-factory/. Nothing else finds files —
# every path in every script goes through one of PLUGIN_ROOT, project_root(), state_dir()
# or ref().
PLUGIN_ROOT = Path(__file__).resolve().parents[1]  # .../ai-packages/qa-factory

_PROJECT_ROOT_CACHE: Path | None = None


def _carries_project(candidate) -> bool:
    """A directory is the project root when it carries `qa-factory/config.json` — the file
    onboarding writes and nothing else creates. This is the only positive marker there is."""
    try:
        return (Path(candidate) / "qa-factory" / CONFIG_PATH_NAME).is_file()
    except Exception:
        return False


def _nearest_project(start) -> Path | None:
    """The nearest ancestor of `start` (inclusive) that carries the marker, or None.

    A delegate of `runtime_paths.nearest_project`, the ONE walk (B-309 (d), t-622); `runtime_paths` imports this
    module lazily, so the lazy import here forms no cycle. `project_root` below is a different question: the
    project THIS PROCESS works in (env first, never None)."""
    from runtime_paths import nearest_project
    return nearest_project(start)


def project_root(event: dict | None = None) -> Path:
    """The project this plugin instance is currently working in.

    **The marker decides, not the repository.** `$CLAUDE_PROJECT_DIR` is set by the harness
    for hook calls only — a script a role runs through `Bash` never sees it — and the old
    fallback was `git rev-parse --show-toplevel`. In a monorepo with the project nested
    (`testproject1-sdk/test-harness/qa-factory/`) that resolves to somebody else's root: on
    TP1-14336 every `log_append.py` call from gate A onward wrote into a sibling
    `qa-factory/` created at the monorepo root, `check_witness.py` reported a real evidence
    file as missing, and gate B carried a false `delivery_ready: no`.

    Order: `$CLAUDE_PROJECT_DIR` when it carries the marker -> the nearest ancestor of the
    tool-call cwd (`event["cwd"]`) or of `Path.cwd()` that carries it -> `$CLAUDE_PROJECT_DIR`
    as the harness gave it -> `event["cwd"]` -> `git rev-parse --show-toplevel` -> `Path.cwd()`.
    The last three keep a not-yet-onboarded project working, where no marker exists yet.
    Cached per process: a hook is a short-lived script and the project does not move
    mid-call."""
    global _PROJECT_ROOT_CACHE
    if _PROJECT_ROOT_CACHE is not None:
        return _PROJECT_ROOT_CACHE

    env_dir = os.environ.get("CLAUDE_PROJECT_DIR")
    cwd_hint = (event or {}).get("cwd") if event else None

    # The env dir is asked for the marker FIRST, as the docstring has always promised. Until
    # 0.7.12 the code went straight to the cwd walk, so a caller that pinned the root by
    # setting `CLAUDE_PROJECT_DIR` (every `--selftest` that builds a temp project does) pinned
    # nothing: on the macOS 0.7.11 install whose plugin clone sat inside an onboarded project,
    # the walk found the user's real `qa-factory/config.json` above the plugin and four
    # selftests read and wrote against his live stories. The 14336 case still resolves the way
    # the docstring describes: there the harness sets the env var to the monorepo root, which
    # carries no marker, so this branch does not fire and the cwd walk wins.
    if env_dir and _carries_project(env_dir):
        # Resolved, exactly as `_nearest_project` returns the cwd's answer: on Windows the
        # variable often carries the 8.3 short form of a directory while everything the walk
        # produced was the long one, and two spellings of one root are two state trees to
        # every caller that compares paths as strings (it cost test_execution_request its
        # whole run block the first time this branch went in unresolved).
        try:
            _PROJECT_ROOT_CACHE = Path(env_dir).resolve()
        except Exception:
            _PROJECT_ROOT_CACHE = Path(env_dir)
        return _PROJECT_ROOT_CACHE

    for start in (cwd_hint, Path.cwd()):
        if not start:
            continue
        found = _nearest_project(start)
        if found is not None:
            _PROJECT_ROOT_CACHE = found
            return _PROJECT_ROOT_CACHE

    if env_dir:
        _PROJECT_ROOT_CACHE = Path(env_dir)
        return _PROJECT_ROOT_CACHE

    if cwd_hint:
        _PROJECT_ROOT_CACHE = Path(cwd_hint)
        return _PROJECT_ROOT_CACHE

    try:
        out = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            cwd=str(Path.cwd()), timeout=10,
        )
        if out.returncode == 0 and out.stdout.strip():
            _PROJECT_ROOT_CACHE = Path(out.stdout.strip())
            return _PROJECT_ROOT_CACHE
    except Exception:
        pass

    _PROJECT_ROOT_CACHE = Path.cwd()
    return _PROJECT_ROOT_CACHE


def pin_project_root(root) -> Path:
    """Make `root` the answer for this process and for any child it spawns. Two callers: `--selftest` (below) and
    `controller._gate_decision_call` (F-1), which pins the project the STORY belongs to (the nearest marker above its task
    root) for the length of one gate decision, inside `selftest_root_restored`, so the decision's side writes land where the
    story lives and not where the shell happens to be. Never call it with a root nobody found.

    One method for every selftest that builds a throwaway project (0.7.12). They used to
    disagree: `archive_task`/`stage_done`/`turn_budget` pinned the cache, while
    `external_writes`/`run_suite`/`guard_pre_tool`/`stage_guard` only cleared it and let the
    walk from cwd decide again. On the macOS 0.7.11 install whose plugin clone sat inside an
    onboarded project that walk found the user's real `qa-factory/config.json` first, and
    four selftests read and wrote against his live stories. The env var is set as well
    because a child process (external_writes' tracker stub, run_suite's runner) starts with
    an empty cache and resolves the root on its own."""
    global _PROJECT_ROOT_CACHE
    _PROJECT_ROOT_CACHE = Path(root)
    os.environ["CLAUDE_PROJECT_DIR"] = str(root)
    return _PROJECT_ROOT_CACHE


@contextlib.contextmanager
def selftest_root_restored():
    """Remember the root this process had — cache and `CLAUDE_PROJECT_DIR`
    — and put both back in `finally`, whatever was pinned in between. A selftest that leaves
    a deleted temp project pinned would hand it to everything that runs after it; a gate decision
    pinned to its story's project (F-1) gives it back the same way."""
    global _PROJECT_ROOT_CACHE
    saved_cache = _PROJECT_ROOT_CACHE
    saved_env = os.environ.get("CLAUDE_PROJECT_DIR")
    try:
        yield
    finally:
        _PROJECT_ROOT_CACHE = saved_cache
        if saved_env is None:
            os.environ.pop("CLAUDE_PROJECT_DIR", None)
        else:
            os.environ["CLAUDE_PROJECT_DIR"] = saved_env


def state_dir(event: dict | None = None) -> Path:
    """Project-side state: config.json, strategy/, artifacts/, state/, bugs/,
    obligations.md, factory-backlog.md. Created by onboarding, never by the plugin's git."""
    return project_root(event) / "qa-factory"


EXIT_NO_PROJECT = 3


def require_project(purpose: str, event: dict | None = None) -> Path:
    """The state directory of an onboarded project, or a refusal on stderr.

    A writer never brings a `qa-factory/` tree into existence: onboarding does, once, and
    everything else writes into the one it finds. The rule exists because the opposite is
    silent — `mkdir(parents=True)` under a root resolved by guess produced a whole sibling
    state tree at a monorepo root, and nobody learned of it until a human read the journal
    (TP1-14336). A resolved root with no `qa-factory/config.json` means the resolution
    is wrong or the project is not onboarded; either way it is not a place to write."""
    root = project_root(event)
    if _carries_project(root):
        return root / "qa-factory"
    print(f"{purpose}: no qa-factory/config.json under {root} — refusing to create one.\n"
          f"This is either a project that was never onboarded (run "
          f"/qa-factory:qa-onboarding), or a wrong project root: the factory looks for "
          f"qa-factory/config.json in the current directory and its ancestors. Run the "
          f"command from inside the project, or set CLAUDE_PROJECT_DIR to it.",
          file=sys.stderr)
    sys.exit(EXIT_NO_PROJECT)


def ref(rel: str) -> Path:
    """Plugin-side reference file (rules, templates, checklists, inject map),
    shipped in the plugin's own git — never generated by onboarding or a story."""
    return PLUGIN_ROOT / "references" / rel


CONFIG_PATH_NAME = "config.json"

# The values of `pipeline.stop_after` that stop a story (GW1-19, AR-13): the ONE list. `controller.STOP_GATES` keys it,
# `config_contract.stop_after_problem` names it to the person; any other value stops nothing.
STOP_VALUES = ("gate_A", "gate_B")

# The config schema this build of the plugin speaks. A project whose qa-factory/config.json
# carries a different schema_version is not "broken" — it was onboarded by an older plugin;
# readiness.py reports config_schema as stale and names the missing top-level keys
# (migration_hint), and S0 halts with that list instead of guessing.
REQUIRED_SCHEMA_VERSION = 1


def config_path(event: dict | None = None) -> Path:
    return state_dir(event) / CONFIG_PATH_NAME


def is_one_component(name) -> bool:
    """True for a name that is one path component: a non-empty string, not `.` or `..`, with no `/`, `\\` or `:`.
    THE one filter of a story's name (AR-15): `artifacts_dir`, the story-key check below it and the controller's receipt names read it."""
    return isinstance(name, str) and bool(name) and name not in (".", "..") and not any(c in name for c in "/\\:")


def artifacts_dir(ticket: str, event: dict | None = None) -> Path:
    """<project>/qa-factory/artifacts/<TICKET>/ — the one home of a story's artifacts."""
    if not ticket or not is_one_component(str(ticket)):
        raise ValueError("task id must be a single path component")
    return artifact_root(event) / str(ticket)


def _name_alias(name: str) -> str:
    """The spelling a case-blind, trailing-dot-and-space-blind file system (NTFS) would read as `name`."""
    return name.rstrip(" .").casefold()


def is_dir_or_no(path) -> bool:
    """`Path.is_dir()` that reads an error of the stat (a name over the file system's limit, a bad byte) as "no"."""
    try:
        return Path(path).is_dir()
    except OSError:
        return False


class StoryRootError(ValueError):
    """A refusal of the story-root drivers; `str(exc)` is the finished text (what is wrong, what was expected, the
    door: FR-1). The ONE typed exception a library creator raises for a story folder that is not there (CX1-18), so
    a CLI names it in its own except tuple and `role_cli.run_guarded` prints it as a refusal. A `ValueError`:
    the call's fault, not the story's (FR-46)."""


def is_story_folder(parent, name) -> bool:
    """THE leaf of the question "is the folder `name` under `parent` a story?" (CX1-18, SIBLING_MAP axis 8).

    True only for a string that is one clean path component (not empty, no blank at either end, not `.` or `..`, none
    of `/ \\ : NUL`), whose exact spelling is in the LISTING of `parent`, and which is a directory. The listing, not a
    stat of the joined path, because NTFS answers `is_dir()` for `tp3-1`, `TP3-1 ` and the 8.3 short name; the name is
    therefore matched letter for letter, and a name absent from the listing (an over-long one included) costs no stat.
    A junction or a symlink with the EXACT name is a story: the name is the key, the target is not checked.

    The error direction is "no": a failed listing (rights, a bad byte) is False, never an exception, because a hook
    must get an answer and not a door (E-8). It may call a real story "no" (the consumer then refuses, skips or asks);
    it never calls a file, an alias or a missing folder "yes". Nothing is created, ever."""
    if (not isinstance(name, str) or not name.strip() or name != name.strip() or name in (".", "..")
            or any(c in name for c in "/\\:\0") or parent is None or not str(parent).strip()):
        return False
    return name in _listing(parent) and is_dir_or_no(Path(parent) / name)


def _listing(parent) -> list[str]:
    """The names in `parent`, or `[]` when it cannot be listed: absent, not a folder, no rights (OSError), a NUL or a
    wildcard-like byte the file system refuses (ValueError), a type it cannot read (TypeError). The ONE listing read of
    the story-root drivers: the leaf asks it, and so does the refusal that names a near miss, so no input is an
    exception in one of them and an answer in the other (critic t-1145 F-2)."""
    if parent is None:                     # `os.listdir(None)` lists the CURRENT folder: never an answer here
        return []
    try:
        return os.listdir(parent)
    except (OSError, TypeError, ValueError):
        return []


def _no_story(program: str, shown: str, why: str, asked: str, parent, name: str, tail: str) -> StoryRootError:
    """The ONE "names no story" refusal (R2 of a key, R2' of a path): what is wrong, that nothing is created, the door.

    `parent` is listed once more here, to name the folder an alias-blind file system would have read as `name`
    (FR-1): a near miss is named, never guessed (FR-59)."""
    names = sorted(_listing(parent))
    alias = _name_alias(name)
    near = [n for n in names if alias and n != name and _name_alias(n) == alias]
    hint = f" A folder {near[0]!r} exists: the {'key' if asked == 'key' else 'name'} is matched exactly." if near else ""
    return StoryRootError(f"{program} {shown} names no story: {why}, and a story folder is never created here "
                          f"(S0 creates it). Pass the {asked} of a story that exists.{hint}{tail}")


def story_root(key: str, program: str, door: str = "", event: dict | None = None, *,
               project=None) -> Path:
    """The folder of the EXISTING story `key` names, or a `StoryRootError` (a ValueError: the call's fault) saying why not.

    The one rule "ticket key -> story folder": a key is ONE path component; the project is required (exit
    `EXIT_NO_PROJECT`, the shared contract of `require_project`); the folder must be a directory of the artifact
    root whose name IS the key, letter for letter. Nothing is created and nothing is written, ever.

    `project=None` is the project of this process. A given `project` (the explicit `--root` / `--project-root` of
    `report_facts`, `traceability`, `judge_results`, `sizing`; CX1-18 L-2 F-7) is the project the key resolves under
    (`artifact_root(root=project)`); it must be an onboarded project (`qa-factory/config.json` under it), and an empty
    or blank one is refused, never read as the current folder. A project that is not one is a `StoryRootError`, not
    the exit of `require_project`, because the caller's own word named it (critic t-1145 F-3).

    The decision is `is_story_folder` (the listing of the artifact root, the exact name, an error from the stat is
    "not a folder"); this function only adds the project and the key's shape, and reads the listing a second time
    on a refusal, to name a near miss (FR-1), never to guess one (FR-59).

    `program` opens every refusal and names the caller; `door` is a sentence the caller adds when it has a door
    of its own to offer (the controller's `--task-root`); a script with none passes nothing."""
    text = str(key)
    tail = f" {door}" if door else ""
    if not text.strip() or not is_one_component(text):
        raise StoryRootError(f"{program} requires a story's ticket key, the name of one folder under the "
                             f"artifact root, e.g. TP2-2406 (got {text!r}).{tail}")
    if project is None:
        require_project(program, event)
        path = artifacts_dir(text, event)
    elif str(project).strip() and _carries_project(project):
        path = artifact_root(root=Path(project)) / text
    else:
        raise StoryRootError(f"{program} was given the project {str(project)!r}, which is not an onboarded project "
                             f"(no qa-factory/config.json under it; an empty value would be the current folder), so "
                             f"nothing was read or written. Pass the root of the project that holds the story.{tail}")
    if is_story_folder(path.parent, text):
        return path
    raise _no_story(program, repr(text), f"{path} is not a folder of this project", "key", path.parent, text, tail)


def _example_folder() -> str:
    """`<artifact root>/<KEY>` of THIS project when there is one (the root is configurable: FR-37), else the placeholder."""
    try:
        if _carries_project(project_root()):
            return str(artifact_root() / "<KEY>")
    except (OSError, ValueError):
        pass
    return "<artifact root>/<KEY>"


def story_root_at(path, program: str, door: str = "") -> Path:
    """The folder of the EXISTING story `path` names, or a `StoryRootError`: the path twin of `story_root` (CX1-18).

    An empty or blank `path` is refused (R1'), never read as the current folder. Otherwise the decision is
    `is_story_folder` over the last component, found through `os.path.abspath` for the parent only: on Windows
    `abspath` drops a trailing blank or dot, so the NAME is read from the lexical form (`normpath`), and `TP3-1 `
    stays what it is (refused, with the real folder named). `.`, `..` and `a/..` are read through `abspath`: the
    caller's explicit word for the folder it stands in. A trailing slash is fine. The project is NOT required (a root
    outside one is legal, CX1-10 K2e). The RETURN is `Path(path)` as given: the relative form the doctor passes and
    `root.name` stay what the caller wrote.

    The form as given must reach the folder the decision looked at (`os.path.samefile`, an `OSError` is "no"): POSIX
    reads `a/../TP3-1` through the real `a`, so an absent `a`, or a link `a` that leads elsewhere, names a folder the
    lexical decision never saw, and the caller would open nothing or another story (FR-59, critic t-1145 F-1).
    Windows reads `..` lexically, so there the detour is the same folder and passes.

    Scope (critic m-1): the answer is "an exactly named, existing folder", not "a folder directly under the artifact
    root" - the artifact root itself and `.` pass. What is promised is the absent folder, never the right parent."""
    raw = "" if path is None else str(path)
    tail = f" {door}" if door else ""
    if not raw.strip():
        raise StoryRootError(f"{program} requires the story's folder, {_example_folder()} (got {raw!r}): an empty "
                             f"value would be the current folder, so nothing was read or written.{tail}")
    absolute = Path(os.path.abspath(raw))
    leaf = os.path.basename(os.path.normpath(raw))
    name = leaf if leaf not in ("", ".", "..") else absolute.name
    shown = f"{raw!r} (resolved: {absolute})"
    if not is_story_folder(absolute.parent, name):
        raise _no_story(program, shown, "it is not a folder", "folder", absolute.parent, name, tail)
    try:
        same = os.path.samefile(raw, absolute.parent / name)
    except (OSError, TypeError, ValueError):
        same = False
    if not same:
        raise _no_story(program, shown, "the path reaches another folder, or none, through `..`", "folder",
                        absolute.parent, name, tail)
    return Path(path)


def story_of(program: str, key=None, root=None, door: str = "", *, project=None, key_flag: str | None = "--task",
             root_flag: str | None = "--task-root") -> Path:
    """The story folder a pair of CLI flags names, or a `StoryRootError` (CX1-18, F-8).

    `None` is an absent flag; a given empty value goes to the driver (R1 for a key, R1' for a path) and is never
    R0, and when both are given empty ONE refusal carries R1 and R1', key first. Neither flag: R0, whose door names
    only the flags THIS script has (`key_flag`/`root_flag`, None for one it lacks: FR-2); a value given for a flag
    declared absent (`None`) is a `TypeError`, the caller's defect. Only a key: `story_root`; only a path:
    `story_root_at`. Both: each is resolved, the same folder (`os.path.samefile`) gives the path as the caller gave
    it, different folders are R-both, and when both are phantoms ONE refusal carries both sentences, key first, and
    the caller's `door` once, at the end. `program` gets the flag name appended per driver.

    `project` is the explicit project root a script's `--root` / `--project-root` names (L-2 F-7): the KEY resolves
    under it (`story_root(project=)`); a path names its own folder and does not read it. `None` is this process's
    project. `story_root_at` has answered through the kernel by now, so an `OSError` in the final `samefile` is a
    race, read as "different"."""
    for given, flag, what in ((key, key_flag, "key"), (root, root_flag, "root")):
        if given is not None and flag is None:
            raise TypeError(f"story_of: a {what} value {given!r} was given for a flag the script declares absent")
    tail = f" {door}" if door else ""
    if key is None and root is None:
        wanted = " or ".join(f"{flag} {what}" for flag, what in (
            (key_flag, "<KEY> (the name of its folder under the artifact root)"),
            (root_flag, "<the story's folder>")) if flag)
        raise StoryRootError(f"{program} requires the story: {wanted}; neither was given, so nothing was read or "
                             f"written.{tail}")
    found, refused = [], []
    for given, flag, resolve in ((key, key_flag, lambda k, p, d: story_root(k, p, d, project=project)),
                                 (root, root_flag, story_root_at)):
        if given is None:
            continue
        try:
            found.append(resolve(given, f"{program} {flag}", ""))
        except StoryRootError as exc:
            refused.append(str(exc))
    if refused:
        raise StoryRootError(" ".join(refused) + tail)
    try:
        same = len(found) < 2 or os.path.samefile(*found)
    except OSError:
        same = False
    if not same:
        raise StoryRootError(f"{program} got {key_flag} {str(key)!r} and {root_flag} {str(root)!r}, and they name "
                             f"different folders ({found[0]} and {found[1]}); pass one of them")
    return found[-1]


def story_cli(program: str, key=None, root=None, door: str = "", *, exit: bool = True, **flags) -> Path:
    """`story_of` for a script's `main`: the story folder, or the refusal on the script's channel (CX1-18, F-9).

    With `exit=True` (a script with no channel of its own) a refusal is ONE line on stderr, `{"error": "<text>"}`
    (`json.dumps`, so a Cyrillic homoglyph shows as `\\u0415`), nothing on stdout, nothing on disk, exit 2.
    With `exit=False` (a script that runs under `role_cli.run_guarded`) the `StoryRootError` is re-raised and the
    guard prints it in the shape of the registered command. The caller says which: a stack walk for `run_guarded`
    would be a hidden dependency on that function's name. `require_project` keeps its exit 3 and its text.
    `flags` are `story_of`'s `project` / `key_flag` / `root_flag`."""
    try:
        return story_of(program, key, root, door, **flags)
    except StoryRootError as exc:
        if not exit:
            raise
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        sys.exit(2)


def exact_options(parser):
    """`parser` with abbreviations of long flags OFF, and the same on every subparser that exists NOW; returns `parser`.

    argparse reads `--task` as `--task-root` when no other flag starts that way, so a key became a relative root and
    a phantom story folder (CX1-10). One helper, not a literal in 34 constructors (P2). The form of the call is the
    contract: `exact_options(ap).parse_args(argv)`, so no subparser can be added after it."""
    import argparse
    parser.allow_abbrev = False
    for action in parser._actions:
        for sub in (action.choices.values() if isinstance(action, argparse._SubParsersAction) else ()):
            exact_options(sub)
    return parser


_JSONL_LOCK = threading.Lock()


def append_jsonl_line(path, line_text: str, *, header: str | None = None) -> None:
    """Append ONE `\\n`-terminated line to the jsonl file `path` (the folder and the file are created when absent).

    The write is one `O_APPEND` write, never a truncation. A torn tail (the file does not end in `\\n`) gets one `\\n` first,
    in the same write, so the new line starts on its own line. `header` (a line of its own) goes first in the SAME write
    when the file is absent or empty: a header without a line after it cannot exist. `line_text` and `header` are single
    lines (a `\\n` inside is a `ValueError`, nothing written). Two processes at once are not locked; the readers detect
    what that can leave. What the caller still decides: what the line says."""
    texts = [t.rstrip("\n") for t in (line_text, header) if t is not None]
    if any("\n" in text for text in texts):
        raise ValueError("append_jsonl_line: a jsonl line holds no line break")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = line_text.rstrip("\n") + "\n"
    with _JSONL_LOCK:      # the C runtime's O_APPEND is not atomic on Windows: threads of ONE process must not interleave
        descriptor = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_BINARY", 0), 0o644)
        try:
            if os.fstat(descriptor).st_size == 0:
                if header is not None:
                    payload = header.rstrip("\n") + "\n" + payload
            else:
                with open(path, "rb") as handle:
                    handle.seek(-1, os.SEEK_END)
                    if handle.read(1) != b"\n":
                        payload = "\n" + payload
            data = memoryview(payload.encode("utf-8"))
            while data:
                data = data[os.write(descriptor, data):]
        finally:
            os.close(descriptor)


CLOSED_AT = "closed_at"         # pipeline.json: when the story closed (gate B decided, S8 done)
REOPENED_AT = "reopened_at"      # pipeline.json: when a person's word reopened it, with `reopened_by_words`
ORDERS_DUE = "orders_due"        # pipeline.json gates.B: the orders of gate B still owed, written by the controller's projection
DECIDED_AT = "decided_at"        # pipeline.json gates.B: when gate B was decided (UTC, the form of `closed_at`)
UNKNOWN_ORDER = "unknown"        # the one name `due` holds when `orders_due` cannot be read (FR-59)


_ORDERS_MEMO: dict = {}          # {"key": (mtime_ns, size) of stages.json, "orders": the parsed table}


def gate_orders(model: dict | None = None) -> dict:
    """The orders a gate decision gives to executors, from `references/stages.json` - the ONE reader (AR-1, AR-13).

    `{order: {"gate": "B", "executor": {"stage", "role"} | "delivery"}}`, merged over the stages that carry a `gate_orders`
    key (S8 today). A table that cannot be read, or an entry that is not an object, is simply absent: `{}` is "the table
    names no order", and a caller that needs an order it does not find says so (it never reads the gap as "nothing is
    owed" for a decision that already recorded orders). `model` is a parsed `stages.json` for a caller that holds one."""
    if model is None:        # the projection asks per event: parse the file again only when it changed
        try:
            stat = ref("stages.json").stat()
            key = (stat.st_mtime_ns, stat.st_size)
        except OSError:
            key = None
        if key is not None and _ORDERS_MEMO.get("key") == key:
            return dict(_ORDERS_MEMO["orders"])
        orders = gate_orders(load_ref_json("stages.json"))
        _ORDERS_MEMO.clear()
        if key is not None:
            _ORDERS_MEMO.update(key=key, orders=orders)
        return dict(orders)
    out: dict = {}
    for stage in (model.get("stages") or []) if isinstance(model, dict) else []:
        table = stage.get("gate_orders") if isinstance(stage, dict) else None
        for name, spec in (table.items() if isinstance(table, dict) else ()):
            if isinstance(name, str) and isinstance(spec, dict):
                out[name] = spec
    return out


def moment(text):
    """An ISO time as a moment (UTC when it names no zone), or None when it is not one. The ONE parser of the closure
    comparisons: `decided_at`, `closed_at` and `reopened_at` are compared as MOMENTS, never as strings."""
    from datetime import datetime, timezone
    try:
        value = datetime.fromisoformat(str(text).strip())
    except (TypeError, ValueError):
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _not_before(left: str, right: str) -> bool:
    """`left` is the same moment as `right` or later. Two readable times are compared as moments; when either cannot be
    read the strings decide, as they did before this existed."""
    a, b = moment(left), moment(right)
    return a >= b if a is not None and b is not None else str(left) >= str(right)


def _orders_due(gate_b: dict):
    """`gates.B.orders_due` as a list of order names; `None` when the key is absent (a file written before 0.10.5);
    `[UNKNOWN_ORDER]` when it is there and cannot be read (not a list, an element that is not a name). ERROR DIRECTION
    (FR-59): a damaged record is never read as "nothing is owed"."""
    if ORDERS_DUE not in gate_b:
        return None
    raw = gate_b[ORDERS_DUE]
    if not isinstance(raw, list) or any(not isinstance(item, str) or not item.strip() for item in raw):
        return [UNKNOWN_ORDER]
    return list(raw)


def story_closure(pipeline: dict | None) -> dict:
    """The ONE reading of "this story is closed": `{"state": "open" | "executing" | "closed", "closed_at": str, "due": [..]}`.

    `closed`: gate B has a decision, S8 is done and nothing the decision ordered is still owed (the retro, S9, may still
    run). `executing`: the same, but `gates.B.orders_due` names orders whose executors have not finished (the bug
    reporter, the MR) - the story is not finished and not open to other work either. `open`: anything else. A person's
    word reopens a story (`reopened_at` as late as `closed_at`, or as late as the decision while it is executing).

    A file with no `orders_due` (written before 0.10.5, not yet re-projected) is read the old way: `closed_at`, else gate B
    answered and S8 done. A file whose `orders_due` is damaged reads `executing` with `due == ["unknown"]`; the controller
    recomputes the truth from its own state (`orders_due`) and the next projection overwrites the file. `[]` while the file
    says an order is `due` is trusted here on purpose: a second derivation in a reader would be a second reading (AR-13).
    Readers: `story_closed` (the time), the stage guard, the doctor, archive, and the controller's `closure_view`."""
    shut = {"state": "open", "closed_at": "", "due": []}
    if not isinstance(pipeline, dict):
        return shut
    closed = str(pipeline.get(CLOSED_AT) or "")
    reopened = str(pipeline.get(REOPENED_AT) or "")
    gates = pipeline.get("gates") if isinstance(pipeline.get("gates"), dict) else {}
    stages = pipeline.get("stages") if isinstance(pipeline.get("stages"), dict) else {}
    gate_b = gates.get("B") if isinstance(gates.get("B"), dict) else {}
    s8 = stages.get("S8") if isinstance(stages.get("S8"), dict) else {}
    # "Was the person put in front of gate B" is `contract.gate_answered`, and it is the one reader of that field:
    # `decision` is what the orchestrator wrote by hand before the controller existed, `status` is the controller's own
    # word, and a story closed by an older build carries only one of them. Reading `decision` alone here would make
    # exactly the class of miss that TP1-15045 cost (one field, two vocabularies). A decline is an answer: a story
    # delivered with known gaps, or not delivered at all, is finished either way.
    try:
        import contract
        answered = contract.gate_answered(pipeline, "B")
    except Exception:  # a partial checkout must never jam a reader of this fact
        answered = bool(str(gate_b.get("decision") or gate_b.get("status") or "").strip())
    finished = answered and s8.get("status") == "done"
    due = _orders_due(gate_b) if finished else None
    if due:
        decided, word = moment(gate_b.get(DECIDED_AT)), moment(reopened)
        if decided is not None and word is not None and word >= decided:
            return shut       # a person's word came after the decision: open (an unreadable time is not a word)
        return {"state": "executing", "closed_at": closed, "due": due}
    if not closed and finished:
        # the time of the closure: the last order settled, else the decision, else what the older chain knows
        settled = gate_b.get("orders_settled") if isinstance(gate_b.get("orders_settled"), dict) else {}
        times = [str(entry.get("at")) for entry in settled.values() if isinstance(entry, dict) and moment(entry.get("at"))]
        closed = (max(times, key=moment) if times
                  else str(gate_b.get(DECIDED_AT) or gate_b.get("at") or s8.get("finished") or "legacy"))
    if closed and reopened and _not_before(reopened, closed):
        return shut
    return {"state": "closed", "closed_at": closed, "due": []} if closed else shut


def story_closed(pipeline: dict | None) -> str:
    """The ISO time this story closed, or "" while it is open or still executing the orders of gate B - the wrapper of
    `story_closure`, the ONE reading of "closed".

    A story is closed when gate B has a decision, S8 is done and every order of that decision is settled (S9, the retro,
    may still run on a closed story); a person's word may reopen it (`reopened_at` as late as `closed_at`). Stories
    written before 0.7.14 carry no `closed_at`: the same facts are read from `gates` and `stages`, so they need no
    migration - a `running` stage does NOT reopen them, which is the whole point. TP2-2534 was S1-S8 done, gate B
    approved, MR merged and the suite green, yet a stage reopened to `running` made it "the second running story" for two
    days, so every Codex dispatch of the live story was refused as ambiguous (I-92). Readers: the stage guard's fallback,
    the doctor's story list, archive candidates. Writers stamp `closed_at` in `stage_done.apply_stage` and the
    controller's projection; `release`/`rework` on a closed story write `reopened_at` with the words."""
    closure = story_closure(pipeline)
    return closure["closed_at"] if closure["state"] == "closed" else ""


def artifact_root(event: dict | None = None, root: Path | None = None) -> Path:
    """Resolve the configurable artifact root once for writers and consumers alike."""
    project = Path(root).resolve() if root is not None else project_root(event).resolve()
    config = project / "qa-factory" / CONFIG_PATH_NAME
    # `utf-8-sig`, but the exception stays: a broken config must raise here, not become `{}` (through `read_json`) and
    # silently put the artifacts into the default root (AR-28, AR-4).
    cfg = json.loads(config.read_text(encoding="utf-8-sig")) if config.exists() else {}
    value = cfg.get("artifact_root")
    if value is None:
        return project / "qa-factory" / "artifacts"
    if not isinstance(value, str) or not value.strip():
        raise ValueError("artifact_root must be a non-empty path")
    path = Path(value)
    return (path if path.is_absolute() else project / path).resolve()


def load_ref_json(name: str) -> dict:
    """A plugin-side reference table (stages.json, detectors.json). Missing/broken -> {}:
    callers MUST treat an empty table as "no rule to enforce", never as an error — these
    files are authored in the plugin's own git and a partial checkout must not jam a hook."""
    try:
        return json.loads(ref(name).read_text(encoding="utf-8"))
    except Exception:
        return {}


def read_answer(out):
    """THE reader of a script's one-line JSON answer in its stdout+stderr text (t-2020; AR-13, AR-18, AR-28): the LAST line that
    parses as a JSON object, else None. A warning a script prints to stderr before or after the answer stays in the text and does not
    hide it; no readable answer is `None`, never an empty dict (the caller names what came back)."""
    for text in reversed(str(out or "").splitlines()):
        if text.strip().startswith("{"):
            try:
                found = json.loads(text)
            except ValueError:
                continue
            if isinstance(found, dict):
                return found
    return None


def read_document(out):
    """The same for a script whose answer is a PRETTY-PRINTED object (several lines, `indent=`): the first object that starts a line
    at column 0 and parses (raw decode from there; text after it is left alone), else None. A warning with a `{` inside a line is
    skipped, and so is one that is no object."""
    text, offset = str(out or ""), 0
    for line in text.splitlines(keepends=True):
        if line.startswith("{"):
            try:
                found = json.JSONDecoder().raw_decode(text[offset:])[0]
            except ValueError:
                found = None
            if isinstance(found, dict):
                return found
        offset += len(line)
    return None


def read_json(path, default=None, *, errors=(OSError, ValueError), kind=None):
    """THE JSON file reader of the package (B-309 e: ten private `_read_json` copies became this one). The parsed value, or
    `default` when `path` cannot be read: absent, a directory, unreadable (OSError), not UTF-8 or not JSON (ValueError).
    An empty file is not JSON, so it is `default` too. A leading BOM is part of the encoding (`utf-8-sig`), never a parse error.

    The caller owns the ERROR DIRECTION, as before the merge: `default` is what its callers read as "nothing there" (None, {},
    []), and `errors` is the exception class it treats that way. The default pair is exactly what `json.loads` and
    `read_text` raise on a bad file; a caller that must also swallow anything else (a nesting too deep for the parser, a
    `path` that is not a path at all) passes `errors=Exception` and says so at its definition. The value is returned as
    parsed, a list or a number included, unless the caller names the type it needs: with `kind=dict` (any type, or a
    tuple of types) a document of another type is `default` too, the same "nothing there". `kind` is checked after a
    successful parse and does not touch `errors`. A caller that wants a fresh `{}` for every answer writes the
    `default` literal in its own `def`: one `{}` shared through a `partial` would be mutated by the first caller."""
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except errors:
        return default
    return default if kind is not None and not isinstance(value, kind) else value


def _posix_sort_key(item):
    if not isinstance(item, PurePath):
        raise TypeError(f"sorted_paths orders Path objects only, got {type(item).__name__}: {item!r} - "
                        "a str among them would sort by the platform's separator, so convert it first")
    return item.as_posix()


def sorted_paths(paths) -> list:
    """THE order of every walk (`glob`, `rglob`, `iterdir`) whose result reaches a refusal, a report or a written
    file (t-892 / C4-7, after t-887): the list sorted by `Path.as_posix()`, i.e. by code point of the whole
    '/'-separated path string. The order is the same on every platform.

    Why not `sorted(paths)`: `Path` ordering compares the path PARTS with the platform's flavour - case-folded on
    Windows (`a/` before `TC-001.md`), case-sensitive on Linux (`TC-001.md` before `a/`) - so a list built from
    it, and the order of the lines of a refusal built from that list, differed between a developer's machine and
    CI. An unsorted walk is worse: it is the order of the directory on disk (Linux), arbitrary.

    Uppercase sorts before lowercase (`B/x` before `a/x`, `TC-001` before `tc-001`), `TC-0001` before `TC-001`
    ('0' 0x30 < '1' 0x31), and `a.md` before `a/x.md` ('.' 0x2e < '/' 0x2f). A Path walk only: an item that is
    not a `PurePath` (a str - on Windows its separator is `\\`, which would sort differently from a Path's) is
    refused with a TypeError rather than ordered by a different rule; names (`p.name`) are plain strings and are
    sorted with plain `sorted`. Equal keys keep their input order (stable); an empty walk is `[]`."""
    return sorted(paths, key=_posix_sort_key)


def resolve_app_root(cfg: dict, event: dict | None = None) -> Path:
    """Root against which protected_app_paths are resolved.

    Application code does not have to live inside the project root (field lesson:
    factory installed in a test repo while the code lives in sibling workspace repos).
    config.json sets app_root as an absolute path or relative to project_root() (e.g.
    ".." or "../.."); default is project_root()."""
    raw = str(cfg.get("app_root", "") or ".").strip()
    p = Path(raw)
    try:
        return (p if p.is_absolute() else project_root(event) / p).resolve()
    except Exception:
        return project_root(event)


def read_event() -> dict | None:
    """None = stdin could not be parsed. Safety guards MUST treat this fail-closed."""
    try:
        from host_adapter import normalize
        from host_dispatch import enrich
        return enrich(normalize(json.load(sys.stdin)))
    except Exception:
        return None


def role_name(raw: str) -> str:
    """A dispatch's role with its plugin namespace stripped: `qa-factory:qa-scout` -> `qa-scout`.

    The harness addresses a plugin's agents by a namespaced id, while every map in this
    factory — `references/inject-map.json`, `references/stages.json`, the witness and
    detector gates — is keyed by the bare role. Looking the raw id up in those maps finds
    nothing *silently*, and each guard keyed on it degrades to "not a factory role".
    Measured on the TP1-13958 pilot: with `qa-factory:qa-scout`, injection delivered
    0 bytes where the bare name delivers 39,111, and the stage guard returned ALLOW
    without printing a word. One owner for the normalization; every hook that looks a role
    up in a map calls this first. The raw id is still what gets journaled — provenance is
    not normalized away, only lookups are."""
    return str(raw or "").strip().rpartition(":")[2].strip()


def subagent_type(event: dict | None) -> str:
    """The subagent type from a SubagentStop event (agent_type / agent_name), "" if absent.

    An empty type = an internal service request of the Claude Code harness (e.g. the
    next-message suggestion generator in remote/mobile sessions), not a subagent launched
    via Agent. Explicitly launched subagents — both factory roles and built-ins
    (general-purpose, Explore) — arrive with a name. SubagentStop hooks MUST skip such
    events: otherwise the journal fills up with "unknown" records and the exit gate
    checks artifacts after every suggestion."""
    event = event or {}
    return str(event.get("agent_type") or event.get("agent_name") or "").strip()


def load_config(event: dict | None = None) -> dict:
    """The project's qa-factory/config.json. Missing (project not onboarded) -> {}: every
    caller MUST treat an empty config as "no-op here", not as an error. A leading BOM is part of the encoding
    (`utf-8-sig`), never a parse error: a BOM config is the project's config, not a project that is not onboarded."""
    return read_json(config_path(event), {}, errors=Exception, kind=dict)  # empty, broken or not an object: {} (no-op)


TRAPPED = ("If you cannot do what this names — the way out is not available to you, or it does not "
           "cover what you need — do NOT try the same call again: write what you were trying to do "
           "and why you could not in your findings, put it in your handover, and halt. A refusal "
           "with no way out is a factory defect, and repeating the call only spends your turns.")


def block(message: str) -> None:
    """Exit 2 = PreToolUse block / PostToolUse feedback; stderr is shown to the model.

    Every refusal carries the same last line, because the one thing a role must never do with a
    refusal it cannot satisfy is retry it. TP1-13797, 27.09: a rewrite guard named `Edit` to a
    role whose session had no Edit, and the role made the same blocked call four times. Nothing
    here decides for the role what to do instead — it says where an impossible refusal goes."""
    print(message.rstrip() + "\n" + TRAPPED, file=sys.stderr)
    sys.exit(2)


def parse_frontmatter(text: str) -> dict | None:
    """Minimal YAML-frontmatter parser (key: value, inline lists). No external deps."""
    m = re.match(r"^---\s*\n(.*?)\n---", text, re.DOTALL)
    if not m:
        return None
    fm: dict = {}
    for line in m.group(1).splitlines():
        line = line.rstrip()
        if not line or line.lstrip().startswith("#") or ":" not in line:
            continue
        if line.startswith((" ", "\t")):  # nesting unsupported — factory schemas do not need it
            continue
        key, _, value = line.partition(":")
        fm[key.strip()] = _unquote(value.strip())
    return fm


def _unquote(value: str) -> str:
    """Strip quotes only when the value is quoted as a WHOLE.

    `.strip('"')` applied blindly eats the closing quote of a value that merely ends in one:
    `parent: QA-EPIC-1 "Inventory tagging"` came back as `QA-EPIC-1 "Inventory tagging`
    (legacy migration). Harmless while nothing read `parent`; visible in a dashboard
    heading from 0.3.0, where the feature group is named by it."""
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("\"", "'"):
        return value[1:-1]
    return value


def is_seeded() -> bool:
    """Drill/training run of factory mechanisms: env QA_FACTORY_SEEDED=1.
    Journal records get seeded:true so a drill and a real incident stay
    distinguishable (finding C-3)."""
    return os.environ.get("QA_FACTORY_SEEDED", "") in ("1", "true", "yes")


def norm(path_str: str) -> str:
    try:
        return str(Path(path_str).resolve()).replace("\\", "/").lower()
    except Exception:
        return path_str.replace("\\", "/").lower()


# --- Write markers in a shell command (shared by the guard) ---
# Redirecting stderr is not a write to an application file: "2>&1", "2>/dev/null",
# "2>$null", "2>NUL". They used to fall under the ">" marker - and a read-only command
# that merely mentioned a protected path was blocked as a write (measured on a live
# session: 60% of commands counted as "writing", actually writing - 10%).
STDERR_REDIRECTS = re.compile(r"2>\s*&\s*1|2>\s*/dev/null|2>\s*\$null|2>\s*NUL")
WRITE_CMD_MARKERS = re.compile(
    r"(>>?|\bSet-Content\b|\bAdd-Content\b|\bOut-File\b|\bRemove-Item\b|\bMove-Item\b|"
    r"\bCopy-Item\b|\brm\b|\bmv\b|\bcp\b|\bdel\b|\btee\b|\bsed\s+-i\b|\btouch\b)",
    re.IGNORECASE,
)

# --- Direct test launches from a role's shell (quiet runs, 2026-09-11; B-404) ----------------
# Suites run ONLY through run_suite.py (the raw log goes to evidence/, the context gets a
# summary). Until B-404 the one form the guard knew was `pytest`, written as a regex here; a
# project on dotnet, jest or gradle was not guarded at all (the prefilter below did not even
# load the guard for it). The FORMS of a launch are closed variety (FR-13), so they live in
# references/launch-causes.json `run_forms`; what stays here is shell grammar only: the quoting
# rules of the two dialects, the flag styles of the shells, assignments, comments, exe suffixes.
# Diagnostics that run nothing (--collect-only, --version, ...) are not a launch.
RUN_FORMS_PATH = PLUGIN_ROOT / "references" / "launch-causes.json"
_RUN_FORMS_CACHE: tuple | None = None  # (path, effective data); reloaded when the path moves

# Everything the tokenizer can take out of a word: quotes and escapes. The prefilter deletes
# the same set from the command, and no form word may hold one of them, so a form name that
# the matcher finds as a token is always a substring of the command the prefilter reads
# (direct_test_form(c) implies needs_guard(c): runs_check sits behind needs_guard, B-404 E2).
_STRIPPED_CHARS = "\"'`\\\r\n"
_STRIP_TABLE = str.maketrans("", "", _STRIPPED_CHARS)
_FLAG_STYLES = ("posix", "powershell", "cmd", "none")
_DIALECTS = ("bash", "powershell")
_EXE_SUFFIXES = (".exe", ".cmd", ".bat", ".com", ".ps1")
_ASSIGNMENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=")
_VERSION_TAIL_RE = re.compile(r"[\d.]+")
_POSIX_PAYLOAD_FLAG_RE = re.compile(r"-[A-Za-z]*c[A-Za-z]*")
_MAX_PAYLOAD_DEPTH = 3  # the text is depth 0; each payload hop (a shell's quoted argument, `eval`) is one deeper, 1..3; a region adds none

# The declared safe default (FR-59): with no readable data, or no valid pytest row in it, the
# guard still knows today's pytest launch - never fewer forms than before the data existed.
_FALLBACK_PYTEST = {"id": "pytest", "argv": ["pytest"],
                    "diagnostics": ["--collect-only", "--co", "--fixtures", "--fixtures-per-test", "--markers"],
                    "negators": []}
_FALLBACK_DIAGNOSTICS = ("--version", "--help", "-h")
_FALLBACK_VERBS = ("run",)
_FALLBACK_LAUNCHERS = (("python", ("-m",)), ("python3", ("-m",)))
# The shells too: today's regex saw `pytest` after a ; & | ( inside `bash -c "x; pytest"`, so the
# superset-of-today invariant (key 13) holds without the data as well. (program, flag_style, dialect)
_FALLBACK_SHELLS = (("bash", "posix", "bash"), ("sh", "posix", "bash"), ("zsh", "posix", "bash"),
                    ("pwsh", "powershell", "powershell"), ("powershell", "powershell", "powershell"),
                    ("cmd", "cmd", "bash"))


def _read_run_forms_file(path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def _word_ok(word, strict: bool = False) -> bool:
    if not isinstance(word, str) or not word or any(c.isspace() for c in word):
        return False
    return not (strict and any(c in _STRIPPED_CHARS for c in word))


def _words(raw, key: str, where: str, problems: list, strict: bool = False) -> list:
    items = raw.get(key, [])
    if not isinstance(items, list):
        problems.append(f"{where}`{key}` is not a list")
        return []
    kept = []
    for item in items:
        if _word_ok(item, strict):
            kept.append(item)
        else:
            problems.append(f"{where}`{key}` holds {item!r}: a word is non-empty, holds no whitespace"
                            + (" and no quote or escape character" if strict else ""))
    return kept


def _launcher_rows(rows, where: str, problems: list) -> list:
    if not isinstance(rows, list):
        problems.append(f"{where} is not a list")
        return []
    out = []
    for index, row in enumerate(rows):
        subs = row.get("subcommands") if isinstance(row, dict) else None
        if (not isinstance(row, dict) or not _word_ok(row.get("program")) or not isinstance(subs, list)
                or not all(_word_ok(s) for s in subs)):
            problems.append(f"{where}[{index}] needs a `program` word and a list `subcommands` of words")
            continue
        out.append((row["program"].lower(), [s.lower() for s in subs]))
    return out


def _join_launchers(target: dict, rows: list) -> None:
    """wrappers and launchers are one family: the subcommands are the union, and an empty list
    in EITHER means the launcher is passed over unconditionally (None)."""
    for program, subs in rows:
        if program in target and target[program] is None:
            continue
        if not subs:
            target[program] = None
        else:
            target[program] = set(target.get(program) or ()) | set(subs)


# The declared safe default of the "a reader runs a program" table (FR-59): with no readable data the guards still know
# today's ripgrep flags and the find ones - never fewer than before the data existed.
_FALLBACK_READER_FLAGS = {"rg": ("--pre", "--pre-glob"), "find": ("-exec", "-execdir", "-ok", "-okdir")}


def _load_reader_runs(raw, problems: list) -> dict:
    """The table of commands that a READ command (rg, find, awk, sed) can make run another program, from
    launch-causes.json `reader_runs` (FR-13, one table for the runner guard, the read guard and the launch matcher):
    `flags` {head: [flag, ...]} - a flag after which the next words are a program (`find -exec`, `rg --pre`);
    `patterns` {head: [regex, ...]} - a word of the command that is itself a script that runs one (`awk` system(),
    `sed` e). Returns {"flags": {head: frozenset}, "words": every flag, "patterns": {head: [compiled]}}."""
    flags: dict = {}
    patterns: dict = {}
    section = raw if isinstance(raw, dict) else {}
    if raw is not None and not isinstance(raw, dict):
        problems.append("`reader_runs` is not an object")
    for head, words in (section.get("flags") or {}).items() if isinstance(section.get("flags"), dict) else ():
        if isinstance(words, list) and all(_word_ok(w) for w in words):
            flags[str(head).lower()] = frozenset(w.lower() for w in words)
        else:
            problems.append(f"reader_runs.flags[{head}] is not a list of words")
    for head, rows in (section.get("patterns") or {}).items() if isinstance(section.get("patterns"), dict) else ():
        try:
            patterns[str(head).lower()] = [re.compile(r) for r in rows]
        except (re.error, TypeError):
            problems.append(f"reader_runs.patterns[{head}] holds an invalid pattern")
    if not flags:
        flags = {head: frozenset(words) for head, words in _FALLBACK_READER_FLAGS.items()}
    return {"flags": flags, "words": frozenset(w for words in flags.values() for w in words), "patterns": patterns}


def reader_runs_words(data: dict) -> frozenset:
    """Every flag of the table: the word after one of them is a program (`-exec pytest`)."""
    return data["reader_runs"]["words"]


def reader_runs(words: list, head: str | None = None, data: dict | None = None):
    """None when this read command (`words` of ONE segment, the program first) runs nothing else. Otherwise
    (marker, program words): the flag or script that makes it run something, and the words from the program it runs
    (`find . -exec L {} +` -> L's words; [] when the program is not named: an `awk` system() script). Only the rows of
    the command's own head apply (`rg -n -e foo`, `rg -- -exec` and `sed -n 1,40p` run nothing). The words after
    `-exec` are judged by the caller as a NEW head."""
    table = (data or run_forms())["reader_runs"]
    name = _name(head if head is not None else (words[0] if words else ""))
    flags = table["flags"].get(name, ())
    for at, word in enumerate(words[1:], 1):
        low = cleaned_word(word).lower()
        if any(low == flag or low.startswith(flag + "=") for flag in flags):
            return low, ([] if "=" in low and not low.endswith("=") else list(words[at + 1:]))
        if any(rule.search(cleaned_word(word)) for rule in table["patterns"].get(name, ())):
            return "script", []
    return None


def _load_run_forms(path) -> dict:
    problems: list = []
    raw: dict = {}
    try:
        loaded = _read_run_forms_file(path)
        raw = loaded if isinstance(loaded, dict) else {}
        if not isinstance(loaded, dict):
            problems.append("the file is not a JSON object")
    except Exception as exc:
        problems.append(f"the file could not be read: {type(exc).__name__}")
    rf = raw.get("run_forms")
    if not isinstance(rf, dict):
        if raw:
            problems.append("`run_forms` is absent or not an object")
        rf = {}
    forms: list = []
    rows = rf.get("forms", [])
    if not isinstance(rows, list):
        problems.append("`run_forms.forms` is not a list")
        rows = []
    for index, row in enumerate(rows):
        where = f"run_forms.forms[{index}] "
        sub: list = []
        if (not isinstance(row, dict) or not isinstance(row.get("id"), str) or not row["id"].strip()
                or not isinstance(row.get("argv"), list) or not row["argv"]):
            problems.append(where + "needs a string `id` and a non-empty list `argv`")
            continue
        argv = _words(row, "argv", where, sub, strict=True)
        diagnostics = _words(row, "diagnostics", where, sub)
        negators = _words(row, "negators", where, sub)
        if sub:  # `_words` appends to `sub` for every word it drops: a dropped argv word is in it
            problems.extend(sub)
            continue
        forms.append({"id": row["id"], "argv": argv, "diagnostics": diagnostics, "negators": negators})
    diagnostics = _words(rf, "diagnostics", "run_forms.", problems)
    sub_diagnostics = _words(rf, "subcommand_diagnostics", "run_forms.", problems)
    verbs = _words(rf, "verbs", "run_forms.", problems)
    launchers: dict = {}
    _join_launchers(launchers, _launcher_rows(raw.get("wrappers", []), "wrappers", problems))
    _join_launchers(launchers, _launcher_rows(rf.get("launchers", []), "run_forms.launchers", problems))
    shells: dict = {}
    shell_rows = rf.get("shells", [])
    if not isinstance(shell_rows, list):
        problems.append("`run_forms.shells` is not a list")
        shell_rows = []
    for index, row in enumerate(shell_rows):
        if (not isinstance(row, dict) or not _word_ok(row.get("program"))
                or row.get("flag_style") not in _FLAG_STYLES or row.get("dialect") not in _DIALECTS):
            problems.append(f"run_forms.shells[{index}] needs a `program` word, a `flag_style` of "
                            f"{'/'.join(_FLAG_STYLES)} and a `dialect` of {'/'.join(_DIALECTS)}")
            continue
        shells[row["program"].lower()] = (row["flag_style"], row["dialect"])
    reader_runs = _load_reader_runs(raw.get("reader_runs"), problems)
    fallback = not any([f["argv"] == ["pytest"] for f in forms])
    if fallback:
        forms.append(dict(_FALLBACK_PYTEST))
        diagnostics = list(diagnostics) + list(_FALLBACK_DIAGNOSTICS)
        verbs = list(verbs) + list(_FALLBACK_VERBS)
        _join_launchers(launchers, [(p, list(s)) for p, s in _FALLBACK_LAUNCHERS])
        for program, style, sdialect in _FALLBACK_SHELLS:
            shells.setdefault(program, (style, sdialect))
    global_diagnostics = frozenset(w.lower() for w in diagnostics)
    for form in forms:
        form["_argv"] = [w.lower() for w in form["argv"]]
        form["_diagnostics"] = frozenset(w.lower() for w in form["diagnostics"])
        form["_all_diagnostics"] = form["_diagnostics"] | global_diagnostics  # built once, keys a cache
        form["_negators"] = frozenset(w.lower() for w in form["negators"])
    prefilter = tuple(dict.fromkeys(tuple(f["_argv"]) for f in forms))
    return {"forms": forms, "diagnostics": global_diagnostics,
            "_diagnostics_text": list(diagnostics),
            "subcommand_diagnostics": frozenset(w.lower() for w in sub_diagnostics),
            "launchers": launchers, "verbs": frozenset(w.lower() for w in verbs), "shells": shells,
            "reader_runs": reader_runs, "problems": problems, "fallback": fallback, "prefilter": prefilter}


def run_forms() -> dict:
    """The effective launch data: read once per process (per path), validated, with the built-in
    pytest form added when the file offers none. An invalid item is skipped and named in
    run_forms_problems(); the hook never fails on the data."""
    global _RUN_FORMS_CACHE
    path = str(RUN_FORMS_PATH)
    if _RUN_FORMS_CACHE is None or _RUN_FORMS_CACHE[0] != path:
        _RUN_FORMS_CACHE = (path, _load_run_forms(path))
    return _RUN_FORMS_CACHE[1]


def run_forms_problems() -> list:
    return list(run_forms()["problems"])


def launch_prefilter_tokens() -> tuple:
    """One tuple of lowercased argv words per effective form (cached with the data)."""
    return run_forms()["prefilter"]


def _name(token: str) -> str:
    """A program's name: basename, lowercased, one executable suffix off."""
    base = re.split(r"[\\/]", token)[-1].lower()
    for suffix in _EXE_SUFFIXES:
        if base.endswith(suffix) and len(base) > len(suffix):
            return base[:-len(suffix)]
    return base


_REGION_MASK = "QASUB"   # stands for a substitution in a masked view: no blank, not a `$`, no reader, launcher, form or hint


class Word(str):
    """A word of a segment that holds a substitution: its text is RAW (`$(true)cat` stays so), `wild` says an UNQUOTED
    substitution (or PowerShell group) is in it - the word may stand for any word - and `clean` is the word with every
    substitution deleted (`py$(true)test` -> `pytest`). A word without one is a plain str."""
    wild = False
    clean = ""


def cleaned_word(word: str) -> str:
    """The one cleaned view of a word: substitutions deleted (`Word.clean`) and every quote/escape character the tokenizer
    can take out of a word deleted (`_STRIP_TABLE`). A plain word is its own view minus those characters."""
    return (word.clean if isinstance(word, Word) else word).translate(_STRIP_TABLE)


def is_wild(word) -> bool:
    return isinstance(word, Word) and word.wild


class Unit(NamedTuple):
    """One body the shell reads as commands, flat: the text itself (`kind` top), a substitution/group/block region at any
    depth (`region`, `form` says which), a payload hop of a shell (`payload`: `text` is the dequoted payload, offsets are
    its own) or a payload past the depth cap (`opaque`: not read). `segments`/`spans` run 1:1; a span is the RAW slice
    `text[a:b]`; `kids` are the (open, close) extents of the regions directly inside, the places a masked view cuts.
    `quoted_bs` (the top unit only, else empty; OH3-32): the sorted offsets of every backslash this reading read INSIDE a
    quoted run - a `'...'` that closed, or a `"..."` frame - with no bash backtick region open (`quoted_backslash`)."""
    kind: str
    form: str
    dialect: str
    depth: int
    text: str
    start: int
    end: int
    segments: list
    spans: list
    kids: list
    quoted: bool
    quoted_bs: tuple = ()


class _Frame:
    __slots__ = ("kind", "open_at", "start", "limit", "depth", "tokens", "segments", "spans", "kids", "buf", "cbuf",
                 "started", "quoted", "wild", "subbed", "seg_start", "comment_at", "mark", "in_dq")

    def __init__(self, kind: str, open_at: int, start: int, limit: int = -1, in_dq: bool = False, mark: int = 0):
        self.kind, self.open_at, self.start, self.limit, self.in_dq, self.mark = kind, open_at, start, limit, in_dq, mark
        self.depth, self.seg_start, self.comment_at = 0, start, -1
        self.tokens, self.segments, self.spans, self.kids, self.buf, self.cbuf = [], [], [], [], [], []
        self.started = self.quoted = self.wild = self.subbed = False

    def end_word(self) -> None:
        if self.started:
            raw = "".join(self.buf)
            if self.subbed:
                word = Word(raw)
                word.wild, word.clean = self.wild, "".join(self.cbuf)
                self.tokens.append((word, self.quoted))
            else:
                self.tokens.append((raw, self.quoted))
        self.buf, self.cbuf, self.started, self.quoted, self.wild, self.subbed = [], [], False, False, False, False

    def end_segment(self, at: int) -> None:
        self.end_word()
        if self.tokens:
            self.segments.append(self.tokens)
            self.spans.append((self.seg_start, at if self.comment_at < 0 else self.comment_at))
        self.tokens, self.comment_at = [], -1

    def add(self, piece: str, clean: str | None = None) -> None:
        self.buf.append(piece)
        self.cbuf.append(piece if clean is None else clean)
        self.started = True


def argv_text(command) -> str:
    """The ONE line every reader of a shell command reads (CX1-20 F-9): an argv list (a Codex host's `command`) is its
    elements joined by a blank, each through str(); None is ""; any other value is its str(). Never `str(list)`:
    `['git', 'commit', ...]` hides the words `git commit` from every reader of words (Q-9). An element holding a blank
    or a quote is grouped by the readers' tokenizer, not by the argv - as the host's shell would read the joined line."""
    if isinstance(command, (list, tuple)):
        return " ".join(str(part) for part in command)
    return "" if command is None else str(command)


class WalkerError(RuntimeError):
    """The command walker failed on a text - a defect of the guard, never of the command. Every guard that reads a
    command BLOCKS on it with `WALKER_DOOR` (FR-1, FR-59: an unread command is never a pass); a hook that let it escape
    would exit 1, which the host reads as "not blocked" (CX1-20 N-1)."""


WALKER_DOOR = ("the guard could not read this command ({reason}), and it does not let a command it could not read "
               "through. The fault is the guard's command reader, not the command: split it into several simpler "
               "commands, or write the long or complex text to a file with the Write tool and name the file in the "
               "command.")


_PAREN_FORMS = {"cmd": "$(", "arith": "$((", "proc": "<(", "group": "("}


class _Reader:
    """The one pass over a command text (`walk`): a stack of frames - the text itself, every region (`$( )`, `$(( )`,
    `<( )`/`>( )`, a bash backtick pair, PowerShell `( )` `@( )` `{ }`) and every `"..."` run - read once, character by
    character, with no recursion. Each region is its own flat Unit; a word that holds one keeps its RAW text."""

    def __init__(self, text: str, dialect: str):
        self.text, self.dialect, self.ps, self.n = text, dialect, dialect == "powershell", len(text)
        self.i = 0
        self.stack = [_Frame("top", 0, 0)]
        self.done: list = []
        self.dq_dead = False
        self.no_tick = -1   # the backtick at this index has no partner after it, so no backtick at or after it has one
        self.tick = None    # the open bash backtick region, if any (there is at most one: see run)
        self.glued_hash = -1   # the index of a `#` that follows a backslash-escaped cut character: part of the word
        self.budget = 4 * self.n + 65536   # characters the quoted words may copy raw (see _close)
        self.qbs: list = []   # offsets of the backslashes read inside a quoted run, ascending (see _note_quoted)

    def run(self) -> list:
        """The Units of the text. Any failure inside is a `WalkerError`: a guard that reads the command blocks on it with
        a door, it never lets the call through unread (CX1-20 N-1: an IndexError here made the hook exit 1, fail-open)."""
        try:
            return self._run()
        except Exception as exc:
            raise WalkerError(f"{type(exc).__name__}: {exc}") from exc

    def _run(self) -> list:
        text, n = self.text, self.n
        while True:
            tick = self.tick
            if tick is not None and self.i >= tick.limit:
                # Bash cuts a backquoted text at its first unescaped backtick BEFORE it reads what is inside, so a `$(`,
                # `"` or `'` opened inside the pair ends at its partner too: every frame above the tick closes there.
                # (A tick opened inside a tick cannot exist: the partner is the first backtick after the opener.)
                # Tested BEFORE the end of the input: an escaped partner as the last character (`\`` read as one pair)
                # jumps past both, and the tick still closes at its partner - never left open across an E8 rewind.
                frame = self.stack[-1]
                self._close(frame, tick.limit, tick.limit + (frame is tick))
                continue
            if self.i >= n:
                if not self._rewind_unclosed_quote():
                    break
                continue
            frame = self.stack[-1]
            if frame.kind == "dq":
                self._dq(frame, text[self.i])
            else:
                self._code(frame, text[self.i])
        while len(self.stack) > 1:
            self._close(self.stack[-1], n, n)
        self._close(self.stack[0], n, n)
        return sorted(self.done, key=lambda unit: unit.start)

    def _open(self, kind: str, oplen: int, limit: int = -1) -> None:
        parent = self.stack[-1]
        parent.subbed = True
        if parent.kind != "dq":
            parent.wild = True
        frame = _Frame(kind, self.i, self.i + oplen, limit, parent.kind == "dq" or parent.in_dq, len(self.done))
        self.stack.append(frame)
        if kind == "tick":
            self.tick = frame
        self.i += oplen

    def _close(self, frame: "_Frame", body_end: int, resume: int) -> None:
        """Pop `frame` (its body ends at `body_end`, reading goes on at `resume`) and record its Unit."""
        self.stack.pop()
        if frame is self.tick:
            self.tick = None
        if frame.kind == "dq":
            parent = self.stack[-1]
            parent.buf.append("".join(frame.buf))
            parent.cbuf.append("".join(frame.cbuf))
            parent.kids.extend(frame.kids)
            parent.started = parent.quoted = True
            parent.subbed = parent.subbed or frame.subbed
            self.i = resume
            return
        frame.end_segment(body_end)
        top = frame.kind == "top"
        self.done.append(Unit("top" if top else "region", frame.kind, self.dialect, 0, self.text, frame.start, body_end,
                              frame.segments, frame.spans, frame.kids, frame.in_dq, tuple(self.qbs) if top else ()))
        if not top:
            parent = self.stack[-1]
            # The word keeps the substitution RAW (`$(true)cat`) so a quoted argument that is a payload is read whole; the
            # regions inside it are masked in the word unless the budget (4 x the text) allows the full copy: a chain
            # of N nested openers must not cost N^2 characters.
            size = resume - frame.open_at
            if parent.kind == "dq" and size <= self.budget:
                self.budget -= size
                raw = self.text[frame.open_at:resume]
            else:
                raw = self.text[frame.open_at:frame.start] + masked_text(self.done[-1]) + self.text[body_end:resume]
            parent.buf.append(raw)
            parent.cbuf.append("")
            parent.kids.append((frame.open_at, resume))
            parent.started = True
        self.i = resume

    def _rewind_unclosed_quote(self) -> bool:
        """The input ended inside a `"..."` run: the outermost such quote has no partner - drop it, read what follows it
        as unquoted, and every later `"` is dropped too (E8). False when no quote is open."""
        at = next((k for k, frame in enumerate(self.stack) if frame.kind == "dq"), None)
        if at is None:
            return False
        frame = self.stack[at]
        del self.stack[at:]
        if self.tick is not None and not any(kept is self.tick for kept in self.stack):
            self.tick = None   # no state outlives its frame: a stale limit would end a comment of the re-read (N-1)
        del self.done[frame.mark:]
        del self.qbs[bisect.bisect_left(self.qbs, frame.start):]   # the dropped quote quoted nothing: what it held is re-read bare
        self.dq_dead = True
        self.i = frame.start
        return True

    def _dq(self, frame: "_Frame", ch: str) -> None:
        text, n, i = self.text, self.n, self.i
        if ch == '"':
            self._close(frame, i, i + 1)
        elif self.ps and ch == "`" and i + 1 < n:
            frame.add(text[i + 1])
            self.i += 2
        elif not self.ps and ch == "\\" and i + 1 < n and text[i + 1] in "$`\"\\\n":
            self._note_quoted(i, i + 1)   # both characters of the pair: `\\|` quotes the second backslash too
            frame.add("" if text[i + 1] == "\n" else text[i + 1])
            self.i += 2
        elif ch == "$" and text.startswith("(", i + 1):
            self._open("arith" if not self.ps and text.startswith("((", i + 1) else "cmd", 3 if not self.ps and text.startswith("((", i + 1) else 2)
        elif not self.ps and ch == "`":
            self._tick(frame)
        else:
            self._note_quoted(i)
            frame.add(ch)
            self.i += 1

    def _note_quoted(self, *at: int) -> None:
        """Record the backslashes among the offsets `at` as read inside a quoted run (OH3-32). Not while a bash backtick
        region is open: bash cuts the text at the backtick pair before it reads a quote, so a quote inside one is not a
        quote of the text. Offsets come in ascending order (a run is read left to right; a rewind drops the tail first)."""
        if self.tick is None:
            self.qbs.extend(k for k in at if self.text[k] == "\\")

    def _tick(self, frame: "_Frame") -> None:
        """A bash backtick at self.i: a region up to the next backtick; with none after it the backtick is dropped (E8).
        `no_tick` is the index of a backtick found to have no partner: it is the LAST backtick of the text, so a backtick
        at or after it has none without a search, and one before it (read again after an E8 rewind) has at least that one."""
        j = -1 if 0 <= self.no_tick <= self.i else self.text.find("`", self.i + 1)
        if j == -1:
            self.no_tick = self.i
            self.i += 1
        else:
            self._open("tick", 1, limit=j)

    def _code(self, f: "_Frame", ch: str) -> None:
        text, n, i, ps = self.text, self.n, self.i, self.ps
        if ch in _BLANKS:
            f.end_word()
            self.i += 1
        elif ch in ";&|\n":
            f.end_segment(i)
            f.seg_start = i + 1
            self.i += 1
        elif ch == "(":
            if ps:
                self._open("group", 1)
            else:
                f.depth += 1 if f.kind in _PAREN_FORMS else 0
                f.end_segment(i)
                f.seg_start = i + 1
                self.i += 1
        elif ch == ")":
            if f.kind in _PAREN_FORMS and f.depth == 0:
                resume = i + 2 if f.kind == "arith" and text.startswith("))", i) else i + 1
                self._close(f, i, resume)
            else:
                f.depth -= 1 if f.depth > 0 else 0
                f.end_segment(i)
                f.seg_start = i + 1
                self.i += 1
        elif ch == "#" and not f.started and i != self.glued_hash:
            f.comment_at = i
            end = n if self.tick is None else self.tick.limit   # a comment inside a backtick pair ends at its partner
            j = text.find("\n", i, end)
            self.i = end if j == -1 else j
        elif ch == '"' and self.dq_dead:
            self.i += 1
        elif ch == '"':
            self.stack.append(_Frame("dq", i, i + 1, mark=len(self.done), in_dq=f.in_dq))
            self.i += 1
        elif ch == "'":
            self._single(f)
        elif ch == "$":
            self._dollar(f)
        elif ch == "`":
            if ps:
                if i + 1 < n:
                    f.add(text[i + 1])
                self.i += 2
            else:
                self._tick(f)
        elif ch == "\\" and not ps:
            step = _read_backslash(text, i)
            if step == 1 and text[i + 1:i + 2] and text[i + 1] in _BASH_CUTS_AFTER_BACKSLASH:
                self.glued_hash = i + 2   # bash keeps the escaped character in the word: a `#` right after it is no comment
            f.add(text[i:i + step])
            self.i += step
        elif ps:
            self._ps_char(f, ch)
        elif ch in "<>" and text.startswith("(", i + 1):
            self._open("proc", 2)
        else:
            f.add(ch)
            self.i += 1

    def _single(self, f: "_Frame") -> None:
        text, ps = self.text, self.ps
        n = self.n if self.tick is None else self.tick.limit   # inside a backtick pair a quote ends at the partner
        piece: list = []
        bare: list = []   # the backslashes of the run: quoted only when the run closes (OH3-32)
        k = self.i + 1
        while k < n:
            if text[k] == "'":
                if ps and k + 1 < n and text[k + 1] == "'":
                    piece.append("'")
                    k += 2
                    continue
                f.add("".join(piece))
                f.quoted = True
                self._note_quoted(*bare)
                self.i = k + 1
                return
            if text[k] == "\\":
                bare.append(k)
            piece.append(text[k])
            k += 1
        self.i += 1   # no partner: the quote is dropped, the text after it is read as unquoted (E8)

    def _dollar(self, f: "_Frame") -> None:
        text, i = self.text, self.i
        if text.startswith("(", i + 1):
            double = not self.ps and text.startswith("((", i + 1)
            self._open("arith" if double else "cmd", 3 if double else 2)
        elif self.ps and text.startswith("{", i + 1):
            j = text.find("}", i + 2)
            end = self.n if j == -1 else j + 1   # `${name}` is a variable, no region
            f.add(text[i:end])
            self.i = end
        else:
            f.add("$")
            self.i += 1

    def _ps_char(self, f: "_Frame", ch: str) -> None:
        """The PowerShell-only forms: `@( )` and `{ }` regions, `<# #>`, `--%`, the braces of a block."""
        text, i = self.text, self.i
        if ch == "@" and text.startswith("(", i + 1):
            self._open("group", 2)
        elif ch == "{" and not (i and text[i - 1] == "@"):
            self._open("block", 1)
        elif ch in "{}" and f.kind == "block":
            f.depth += 1 if ch == "{" else -1
            if f.depth < 0:
                self._close(f, i, i + 1)
            else:
                f.add(ch)
                self.i += 1
        elif ch == "<" and not f.started and text.startswith("<#", i):
            k, unclosed = _read_ps_comment(text, i)  # only at a word start: `a<#x#>b` is one word to PowerShell
            if unclosed and f.comment_at < 0:
                f.comment_at = i
            self.i = k
        elif ch == "-" and not f.started and (stop := _read_ps_stop_parsing(text, i))[0]:
            f.tokens.extend((word, False) for word in stop[0])
            self.i = stop[1]
        else:
            f.add(ch)
            self.i += 1


_BASH_ESCAPABLE = "$\\()\"'` "  # what a bash backslash JOINS into the word here (POSIX 2.2.1 keeps ANY escaped character)
# What a bash backslash also keeps in the word but the walker still CUTS at (the finer side, CX1-19: a Codex host labels
# PowerShell commands `Bash`, and there `\;` and a blank end the word). The cut stays; the one thing the shell's reading
# changes is a `#` right after it - bash has it mid-word (no comment), so it must not hide the text behind it (CX1-20 F-3).
_BASH_CUTS_AFTER_BACKSLASH = "\t\r\x0b\x0c;&|\n"
_BLANKS = " \t\r\x0b\x0c"  # the one spelling of the blanks `_scan` ends a word at (the line end is a separator, not a blank)
_PS_BLANKS = _BLANKS + "\n"  # the same plus the line end, on purpose: `--%` is a token before either
_BLANK_RUN = re.compile("[" + re.escape(_BLANKS) + "]+")


def hint_gate(text, hints, groups: bool = False) -> bool:
    """The ONE gate rule of the cheap prefilters in front of the readers (CX1-20 M-4; the stage guard's `git commit` and
    `run_suite.py` hints, the hook's `needs_stage_guard`): a hint passes when it is in the raw text, OR in the cleaned
    view (the quote and escape characters out, blank runs collapsed to one blank: `gi"t" commit`, `run_sui\\te.py`), OR
    when the text holds a `$(` or a backtick (a substitution may build any word - `git com$(true)mit`, `git $(true)
    commit` - and only the walker deletes it). `groups` adds the PowerShell reading: every WORD of a hint in the text,
    anywhere (`git (echo commit)`). The error direction is True: a false admit costs one walk, a miss would make a
    reader unreachable. The hook's `stage_check` hands this gate the RAW command (CX1-20 F-1); the `$` + LF clause is a
    CRUTCH for any caller that still hands it the output of `guard_pre_tool.command_text_parts` (B-434, queued), which
    turns `$(` into `$` + LF: when that cutter is replaced the clause goes."""
    text = str(text or "")
    if any(hint in text for hint in hints) or "$(" in text or "`" in text or "$\n" in text:   # "$\n": the B-434 crutch
        return True
    if any(hint in _BLANK_RUN.sub(" ", text.translate(_STRIP_TABLE)) for hint in hints):
        return True
    return groups and any(all(word in text for word in hint.split()) for hint in hints)


def _read_backslash(text: str, i: int) -> int:
    """Length of the run the bash backslash at text[i] opens: 2 when it escapes a character of `_BASH_ESCAPABLE` -
    `$`, another backslash, `( ) " ' ` ` and a blank - the pair is ONE part of the word, so no substitution, group,
    quote or backtick region starts there and the second backslash escapes nothing further (POSIX 2.2.1; CX1-19 for
    `$` and the backslash, CX1-20 for the rest) - else 1, the backslash alone. The join is safe for the readers
    because every command is read in BOTH dialects (`_first_form`, the delivery and commit readers): a Codex host labels
    PowerShell commands `Bash`, where `C:\\p\\"a b"; pytest -q` runs a second command that the bash reading hides, and
    the PowerShell reading finds it. A backslash before `; & |`, a line end, a TAB, VT, FF or CR stays a plain character
    here (the walker cuts or ends the word there, the finer side); only a `#` right after one is no comment (`_code`)."""
    if i + 1 < len(text) and text[i + 1] in _BASH_ESCAPABLE:
        return 2
    return 1


def _read_ps_comment(text: str, i: int) -> tuple:
    """(k, unclosed): `k` is the index just after the PowerShell block comment `<# ... #>` that opens at text[i]
    (about_Comments); a comment with no `#>` runs to the end of the input (`k` = len(text), `unclosed` True).
    Its body, newlines and `;` included, is not text."""
    close = text.find("#>", i + 2)
    return (len(text), True) if close == -1 else (close + 2, False)


def _read_ps_stop_parsing(text: str, i: int) -> tuple:
    """(words, k) when the PowerShell stop-parsing token `--%` stands at text[i] as a word of its own (followed by a
    blank or the end; about_Parsing): `words` are `--%` and the rest of the run split on blanks, read LITERALLY -
    a single quote, `;`, `&`, `#`, `(` in it is text - and `k` is the index that closes the run (len(text) when
    none). The run ends at the first of: a line end, an UNQUOTED `|` (a pipeline), `&&` (`||` is two pipes; both
    measured in PowerShell 5.1 and 7.6). A `|` inside a double-quoted pair does not end it; a double quote with
    no partner on its line opens nothing (the safe side: the pipe after it ends the run, as an unclosed quote
    never hides a separator from `_scan`). ([], i) when it is not the token (`--%x`)."""
    after = i + 3
    if not text.startswith("--%", i) or (after < len(text) and text[after] not in _PS_BLANKS):
        return [], i
    line_end = text.find("\n", i)
    line_end = len(text) if line_end == -1 else line_end
    end = after
    while end < line_end:
        c = text[end]
        if c == '"':
            close = text.find('"', end + 1, line_end)
            end = end + 1 if close == -1 else close + 1
        elif c == "|" or text.startswith("&&", end):
            break
        else:
            end += 1
    return [word for word in _BLANK_RUN.split(text[i:end]) if word], end


@functools.lru_cache(maxsize=32)
def _read_units(source: str, dialect: str) -> tuple:
    """THE one read of a text in a dialect (SC1-5b, AR-15): the Units the reader class makes of it, cached for the
    life of the process, because one hook call reads the same command more than once (`walk` for the delivery, commit
    and runner shapes, `_scan` for the read guard) and the answer for a pair (text, dialect) never changes. The cache
    changes only the price: a pair that left it is read again and gives the same Units (32 pairs, then the oldest goes).
    Every Unit is frozen all the way down - `segments` a tuple of tuples, `spans` and `kids` tuples - so one reader's
    edit cannot reach another (a `Word`'s `wild`/`clean` are still plain attributes: a reader leaves them alone, and
    `test_hooklib_scan.py` and the audit of the SC1-5b report hold that). A failure is a `WalkerError` and `lru_cache`
    remembers no exception, so an unread command is read, and refused, again on every call (CX1-20 N-1, AR-28)."""
    return tuple(unit._replace(segments=tuple(tuple(segment) for segment in unit.segments),
                               spans=tuple(unit.spans), kids=tuple(unit.kids), quoted_bs=tuple(unit.quoted_bs))
                 for unit in _Reader(source, dialect).run())


def quoted_backslash(text, at: int, either: bool = False) -> bool:
    """Whether the backslash at `text[at]` lies inside a quoted run in BOTH shell readings (OH3-32): a `'...'` that
    closed, or a `"..."` run, with no bash backtick region open. The bash and the PowerShell reading each record it
    (`Unit.quoted_bs`), so a run one dialect reads as quotes and the other does not (PowerShell's backtick-escaped
    quote) frees nothing: the answer is the intersection, the error direction is False. `either=True` is the union,
    for advice only (the door of a refusal), never for freeing a hit. A text the reader cannot read raises
    `WalkerError`, which the caller lets through to its guard's door (AR-25, AR-28)."""
    source = str(text or "")
    found = []
    for dialect in _DIALECTS:
        recorded = _read_units(source, dialect)[0].quoted_bs
        k = bisect.bisect_left(recorded, at)
        found.append(k < len(recorded) and recorded[k] == at)
    return any(found) if either else all(found)


def _scan(text: str, dialect: str, spans: bool = False) -> tuple:
    """Cut `text` into command segments of tokens, read in one shell dialect.

    A view of `walk` (the one walker, CX1-20): the top unit's segments, and every region's masked body. Returns
    (segments, regions): a segment is a list of (word, came_from_a_quoted_run); a region is the body of a `$( )`,
    `$(( ))`, `<( )` / `>( )`, a bash backtick pair, or a PowerShell `( )`, `@( )`, `{ }`, at ANY depth, with the regions
    directly inside it masked - inspected in addition by the caller, never a reason to stop the outer text from
    splitting; a word that holds a region keeps it raw. With `spans=True` the answer is
    (segments, regions, spans) and `spans[i] = (start, end)` is the RAW slice of `text` behind
    `segments[i]`: `start` is the index just after the last separator before the segment (0 for the
    first), `end` is the index of the separator that closed it, of the `#` that began a comment, or
    len(text). A slice holds neither its separators nor a trailing `#` comment (the shell does not run
    one); a closed `<# #>` block stays inside its slice, an unclosed one ends it; an
    empty segment has no slice, so the two lists run 1:1. The first two members equal the `spans=False`
    answer, which no existing reader sees change. Quote rules (A2): bash - in
    "..." a backslash escapes $ ` " \\ and newline, elsewhere a backslash is literal (Windows
    paths stay readable), '...' has no escapes; powershell - a backtick escapes the next
    character, '' inside '...' is a quote, a backslash is literal. An unbalanced quote is
    dropped and the text after it is read as unquoted, so it never hides a separator (E8).
    Outside quotes (`_read_backslash` / `_read_ps_comment` / `_read_ps_stop_parsing`): bash - a backslash before
    `$`, a backslash, `( ) " ' `` ` and a blank keeps that character in the word (the word text stays raw: POSIX 2.2.1);
    before `; & |`, a line end, TAB, VT, FF or CR it is a plain character and the walker cuts or ends the word there
    (a `#` right after such a pair is no comment); a bash backtick pair ends at its FIRST unescaped partner whatever is
    open inside it (a `$(`, `"` or `'` opened in it ends there); powershell - `<# ... #>` at the START of a word is a
    comment (unclosed: to the end of the input; it holds no separator; inside a word `<#` is text) and a word `--%`
    makes the rest of the line literal up to a line end, an unquoted `|` or `&&` (split on blanks, one segment).

    Work stays linear on hostile text: the reader walks a stack of frames once with no recursion, a region is a flat
    unit of its own (found where it opens, so its real nesting depth costs nothing), and once a double quote has been
    found unclosed every later one is too (every later quote of the same text is an escaped pair, so its tail reads
    exactly as the first one did)."""
    top, *kids = _read_units(str(text or ""), dialect)
    regions = [masked_text(unit) for unit in kids]
    segments = [list(segment) for segment in top.segments]   # new lists on every call: a reader's edit never reaches the cache
    return (segments, regions, list(top.spans)) if spans else (segments, regions)


def masked_slices(unit: Unit) -> list:
    """[(a, b, masked, has_region)] for every slice of `unit`: `masked` is the raw slice with each region directly inside
    it replaced by `_REGION_MASK` (a region's own text is judged as its own unit). Linear: the kids are sorted."""
    out, kids, k = [], unit.kids, 0
    for a, b in unit.spans:
        parts, pos, has = [], a, False
        while k < len(kids) and kids[k][0] < b:
            opened, closed = kids[k]
            k += 1
            if opened >= a:
                parts += [unit.text[pos:opened], _REGION_MASK]
                pos, has = min(closed, b), True
        parts.append(unit.text[pos:b])
        out.append((a, b, "".join(parts), has))
    return out


def masked_text(unit: Unit) -> str:
    """The body of a region with the regions directly inside it masked (`echo $(a $(b) c)` -> `a QASUB c`, `b`)."""
    parts, pos = [], unit.start
    for opened, closed in unit.kids:
        parts += [unit.text[pos:opened], _REGION_MASK]
        pos = min(closed, unit.end)
    parts.append(unit.text[pos:unit.end])
    return "".join(parts)


def walk(text, dialect: str, payloads=None) -> list:
    """The one walker of a command text (CX1-20): the flat list of Units that `text` makes the shell read as commands -
    the text itself, every substitution/group/block region at any depth (a region adds no depth), and, when `payloads`
    is given, the payload hops it names: `payloads(tokens, dialect)` -> [(text, dialect)] for one segment (a shell's
    quoted argument, `eval`), read the same way one hop deeper. A hop past `_MAX_PAYLOAD_DEPTH` is one `opaque` Unit
    (not read: the reader judges it). Each character of a text is read once; a payload is its own, shorter text."""
    out, todo = [], [(str(text or ""), dialect if dialect in _DIALECTS else "bash", 0)]
    while todo:
        source, reading, depth = todo.pop()
        if not source.strip():
            continue
        for unit in _read_units(source, reading):
            unit = unit._replace(depth=depth, kind="payload" if depth and unit.kind == "top" else unit.kind)
            out.append(unit)
            if payloads is None:
                continue
            for tokens in unit.segments:
                for inner, inner_dialect in payloads(tokens, reading):
                    if depth + 1 > _MAX_PAYLOAD_DEPTH:
                        out.append(Unit("opaque", "opaque", inner_dialect, depth + 1, inner, 0, len(inner), (), (), (), False))
                    else:
                        todo.append((inner, inner_dialect, depth + 1))
    return out


# --- the bodies a command only CARRIES: heredocs and here-strings (OH3-22, AR-15: the ONE scan) --------------------------
#
# Two readers decide what such a body is: the advice reader (`guard_pre_tool._split_off_bodies`: `command_text_parts`, the
# quiet-runs check) and the stage guard's gate (`stage_guard._executable_text`). They differ in WHAT they take out, never
# in where a body starts and ends, so that is read once, here, and each reader decides on the records (a reader of text
# in a gate role takes a body out only when it is sure the shell stores it: the error direction is a body that stays).
HEREDOC_RE = re.compile(r"<<-?[ \t]*(['\"]?)([A-Za-z_][A-Za-z0-9_.-]*)\1")
HERESTRING_RE = re.compile(r"<<<[ \t]*('[^']*'|\"[^\"]*\"|[^\s;&|<>()]+)")
PS_HERESTRING_RE = re.compile(r"@(['\"])[ \t]*\r?\n")
EXPANSION_RE = re.compile(r"\$\(|\$\{|`")   # text the shell will expand is not text: `$(..)`, `${..}`, a backtick


class Body(NamedTuple):
    """One heredoc or here-string found in a text. All offsets index the text the scan was given. `kind`: `heredoc`
    (`<<E`; `head_end` is the line feed ending the operator's line, `body_start` the first body character, `body_end`
    where the closer line begins, `closer_end` where it ends), `herestring` (`<<< word`; the word is
    `[body_start:body_end]`), `ps_herestring` (`@'`..`'@`, the same for `@"`). `closed`: a closer line was found.
    `quoted_delimiter`: `<<'E'` / `@'`, whose body the shell hands over as it stands. `inline`: written in the middle of
    a line, so the pieces around it join with a blank, not a line feed."""
    kind: str
    op_at: int
    head_end: int
    body_start: int
    body_end: int
    closer_end: int
    closed: bool
    quoted_delimiter: bool
    inline: bool


def body_of(src: str, record: Body) -> str:
    """The text of a record's body: a record holds offsets, never a copy."""
    return src[record.body_start:record.body_end]


def scan_bodies(src: str, herestring_ok=None) -> list:
    """Every heredoc and here-string of `src`, in order, as `Body` records. The advance of the scan is the one
    `guard_pre_tool._split_off_bodies` always had, byte for byte: a body is skipped whole whether or not a reader takes it
    out (a quote inside it never flips the state of what follows), a quote opens a run no operator is read in, and a
    `<<<` that `herestring_ok(src, at, word)` refuses is no record and is re-read one character later as `<<` (so `python
    <<< "a"` / `b` / `a` / `c` is a heredoc with the delimiter `a`: a quirk the advice reader keeps and the gate avoids by
    passing no test). `herestring_ok` None accepts every `<<<` that has a word. The scan knows neither comments nor `$'..'`
    nor a continuation: its records are CANDIDATES, and the reader that takes one out checks those itself."""
    out: list = []
    i, n, quote = 0, len(src), ""
    while i < n:
        ch = src[i]
        if quote:
            if ch == "\\" and quote == '"' and i + 1 < n:
                i += 2
                continue
            if ch == quote:
                quote = ""
            i += 1
            continue
        if ch == "@" and i + 1 < n and src[i + 1] in "'\"":
            m = PS_HERESTRING_RE.match(src, i)
            if m:
                end = re.compile(r"^[ \t]*" + re.escape(src[i + 1] + "@"), re.M).search(src, m.end())
                after = end.end() if end else n
                out.append(Body("ps_herestring", i, i, m.end(), end.start() if end else n, after, end is not None,
                                src[i + 1] == "'", True))
                i = after
                continue
        if ch in "'\"":
            quote = ch
            i += 1
            continue
        if src.startswith("<<<", i):
            m = HERESTRING_RE.match(src, i)
            if m and (herestring_ok is None or herestring_ok(src, i, m.group(1))):
                out.append(Body("herestring", i, i, m.start(1), m.end(), m.end(), True, False, True))
                i = m.end()
                continue
        elif src.startswith("<<", i):
            m = HEREDOC_RE.match(src, i)
            newline = src.find("\n", m.end()) if m else -1
            if m and newline != -1:
                end = re.compile(r"^[ \t]*" + re.escape(m.group(2)) + r"[ \t]*$", re.M).search(src, newline + 1)
                after = end.end() if end else n
                out.append(Body("heredoc", i, newline, newline + 1, end.start() if end else n, after, end is not None,
                                bool(m.group(1)), False))
                i = after
                continue
        i += 1
    return out


def cut_bodies(src: str, taken: list) -> tuple:
    """(text, ops): `src` with the body of each record in `taken` (in source order) taken out, and `ops[k]` the offset
    in `text` where the operator of `taken[k]` stands (an inline body leaves the offset where it was cut). The pieces
    around a heredoc join with a line feed, as the text did; the pieces around an inline body (`cat <<< "a" pytest`, a
    here-string's closer is followed by an ARGUMENT) join with a blank, so the removal never creates a command position
    (B-404 E17). Nothing taken: `src` itself."""
    if not taken:
        return src, []
    parts: list = []
    size, glue, kept, ops = 0, "\n", 0, []

    def put(piece: str) -> int:
        nonlocal size, glue
        start = size + (len(glue) if size else 0)
        if piece:
            parts.append((glue if size else "") + piece)
            size += len(parts[-1])
            glue = "\n"
        return start if piece else size

    for record in taken:
        start = put(src[kept:record.head_end])
        ops.append(start + record.op_at - kept)
        if record.inline:
            glue = " "
        kept = record.closer_end
    put(src[kept:])
    return "".join(parts), ops


# The shell tokenizer's public name (B-407 A): a consumer that reads command segments (the stage guard's commit
# shape) takes it from here, not from `_scan`. Since CX1-20 it is a VIEW of `walk`: the top unit's segments, the masked
# bodies of the regions in source order, and (spans=True) the top unit's raw slices.
command_segments = _scan

# What `command_segments` cannot see as the shell does, and the two command guards (the runner guard in stage_guard,
# the read guard in host_adapter) therefore refuse WHOLE, never read: the tokenizer cuts or joins where the shell that
# will run the command does not, so a guard that judges the cut pieces (a reader-headed piece is exempt, a piece with
# a flag is exempt) can be handed a launch hidden in one (t-941 G-1: `python -X a\&cat run_suite.py --task X` is one
# command to bash and three pieces here). A backslash before any of `; & | ( ) ' "` or a line end (bash escapes and
# continuation; PowerShell reads the quote as closing), the PowerShell block comment `<#` and stop-parsing token
# `--%`, the typographic quotes U+2018..U+201E (PowerShell quotes; `_scan` is ASCII-only: CX2-12), and a CR with no LF
# after it (PowerShell: a line end; `_scan`: a blank). Three more members are the COMMENT rule (t-947 F-1): `_scan` starts
# a comment at any `#` it has not yet seen a word byte before, and the slice ends there, so text bash RUNS drops out of
# every slice. Bash keeps the `#` inside the word after a backslash-escaped blank (`a\ #`) and after the `)` that closes
# `$( )`, `$(( ))` or `<( )` (`$(true)#`), and does not split words on a vertical tab or form feed (`a<FF>#`). Every
# member only REFUSES; the root fix is `_scan` cutting no finer and no coarser than the shell (CX1-19), after which this
# list shrinks.
# ONE exemption (OH3-32, `shell_opaque_found`): a backslash before `|`, `;` or `&` that lies inside a quoted run in BOTH
# readings (`grep "a\|b"`: bash keeps the backslash in `'...'` and before these characters in `"..."`, PowerShell has no
# backslash escape) is text, and is not a hit - only when the text holds no `<<`, no here-string opener and no `${` (the
# walker does not know bodies and reads the quotes of a `${ }` by its own rules), and a hit never frees one behind it: every hit is judged in turn. A backslash before `( ) ' "`
# or a line end, and every other member, is never exempt.
SHELL_OPAQUE_BAN = re.compile(r"\\[;&|()'\"\r\n]|<#|--%|[\u2018-\u201e]|\r(?!\n)|\\[ \t]#|\)#|[\x0b\x0c]")

_DOOR_BACKSLASH = ("put the text in ASCII quotes ('...' or \"...\") instead of escaping it with a backslash (in a regex "
                   "write a class such as [(] for \\(), write a Windows path with forward slashes (C:/p/(1)/x), end a "
                   "path without a trailing backslash, and put each command on its own line with no backslash at the "
                   "end of a line")
_DOOR_BACKSLASH_QUOTED = ("the text is already in quotes, and this backslash stays a problem there: in a regex write a "
                          "class such as [(] for \\(, write a Windows path with forward slashes (C:/p/(1)/x), use single "
                          "quotes for a double quote, and end a path without a trailing backslash; end a line without the "
                          "backslash, or put a multi-line text in a file with the Write tool and name the file; a regex "
                          "alternation in such a command goes into a character class or into a file")
# the text holds a heredoc, a here-string or a `${ }`: the guard cannot tell what is quoted there, so the way out is a command
# that holds none of them
_DOOR_SPLIT = ("; if the command also holds a heredoc, a here-string or a ${...}, give that part its own command (or write "
               "the text to a file with the Write tool and name the file), so that the part with the backslash can be read alone")
_DOOR_COMMENT = ("put a plain blank before a `#` comment, or write the `#` inside quotes (in a pattern write a class "
                 "such as [)] for a closing parenthesis)")


def shell_opaque_found(command: str) -> tuple:
    """(what, door) for the first member of SHELL_OPAQUE_BAN in `command`, or ("", "") when it holds none.

    `what` names the sequence a person or a role can find in its own text; `door` says how to write the command
    without it. Both guards build their refusal from these two strings, so the wording lives once."""
    text = str(command or "")
    # The quote fact comes from the walker, which does not know a heredoc or a here-string body, and which reads the quotes
    # of a `${ }` expansion by its own rules (`"${a"} "` is closed to it, open to the shell): past one it is unreliable, so a
    # text that holds an opener or a `${` frees no hit and gets no quote door (OH3-32; error direction: refusal).
    reliable = "<<" not in text and "${" not in text and not PS_HERESTRING_RE.search(text)
    for hit in SHELL_OPAQUE_BAN.finditer(text):
        found = hit.group()
        member = found.startswith("\\") and not found.endswith("#")   # backslash + one of ; & | ( ) ' " CR LF
        if member and reliable and found[1] in ";&|" and quoted_backslash(text, hit.start()):
            continue   # text in both readings; the NEXT hit is judged on its own, a first hit frees nothing behind it
        return _opaque_member(found, member and reliable and quoted_backslash(text, hit.start(), either=True),
                              member and not reliable)
    return "", ""


def _opaque_member(found: str, in_quotes: bool, unreliable: bool = False) -> tuple:
    """(what, door) for one member `found` of SHELL_OPAQUE_BAN; `in_quotes`: its backslash lies in a quoted run;
    `unreliable`: the text holds a heredoc, a here-string opener or a `${`, so the guard cannot say what is quoted."""
    if found.startswith("\\") and found.endswith("#"):
        return "a backslash-escaped blank before `#`", _DOOR_COMMENT
    if found == ")#":
        return "`#` right after `)`", _DOOR_COMMENT
    if found in ("\x0b", "\x0c"):
        return "a vertical tab or form feed", "separate words with a plain blank, never a vertical tab or form feed"
    if found.startswith("\\"):
        after = found[1]
        what = "a backslash before " + (f"`{after}`" if after not in "\r\n" else "a line end")
        if in_quotes:
            return what, _DOOR_BACKSLASH_QUOTED
        return what, _DOOR_BACKSLASH + (_DOOR_SPLIT if unreliable else "")
    if found == "<#":
        return "`<#` (a PowerShell block comment)", "remove the <# ... #> comment"
    if found == "--%":
        return "`--%` (the PowerShell stop-parsing token)", "write the arguments plainly, without --%"
    if found == "\r":
        return "a lone carriage return (CR with no LF after it)", "end each line with LF (or CR LF), never a lone CR"
    return f"the typographic quote U+{ord(found):04X}", "use plain ASCII quotes (' or \")"


def _launcher_subs(name: str, launchers: dict):
    """(is_launcher, subcommands or None for unconditional); `python3.11` is `python`."""
    if name in launchers:
        return True, launchers[name]
    for program, subs in launchers.items():
        if name.startswith(program) and _VERSION_TAIL_RE.fullmatch(name[len(program):]):
            return True, subs
    return False, None


def _payload_flag(style: str, word: str) -> bool:
    low = word.lower()
    if style == "posix":
        return bool(_POSIX_PAYLOAD_FLAG_RE.fullmatch(word))
    if style == "powershell":
        return len(low) >= 2 and low.startswith("-") and "-command".startswith(low)
    if style == "cmd":
        return low in ("/c", "/k")
    return False


class _SegmentWords:
    """The lowercased words of ONE command segment and the lookups a form match needs.

    The heads and the next-`--` index are built once per segment, when it is created; every other
    lookup (a next-index table per (word, negators), the last diagnostic per diagnostics set) once,
    on first use. So matching a segment costs a pass over it per form that has a candidate - not a
    scan to the segment's end per candidate position (B-404 F2: `run mvn ` x 5000 took 11 s with
    the scan)."""

    def __init__(self, low: list, data: dict):
        self.low = low
        self.data = data
        n = len(low)
        self._heads = [t.split("=", 1)[0] for t in low]
        # next_dash[i]: the first literal `--` at or after i (n when none). A word after `--` is an
        # argument of the program, never its subcommand (`cargo run -- test`).
        self._next_dash = [n] * (n + 1)
        for p in range(n - 1, -1, -1):
            self._next_dash[p] = p if low[p] == "--" else self._next_dash[p + 1]
        self._next_counting: dict = {}  # (word, negators) -> table: first index >= i where the word counts
        self._last_diagnostic: dict = {}  # diagnostics -> index of the last diagnostic token, -1 for none

    def _table(self, word: str, negators: frozenset) -> list:
        table = self._next_counting.get((word, negators))
        if table is None:
            low = self.low
            table = [None] * (len(low) + 1)
            for p in range(len(low) - 1, -1, -1):
                counts = low[p] == word and not (p > 0 and low[p - 1] in negators)
                table[p] = p if counts else table[p + 1]
            self._next_counting[(word, negators)] = table
        return table

    def subcommand_at(self, word: str, negators: frozenset, pos: int, c: int):
        """Index of the first token at or after `pos` that is `word` as a subcommand of the program
        at `c` - not right after a negator (the word right after the program is never after one) and
        not after a literal `--` - or None."""
        low = self.low
        if pos == c + 1 and pos < len(low) and low[pos] == word:
            return pos
        found = self._table(word, negators)[pos]  # pos <= len(low): the table has one slot more
        if found is None or found >= self._next_dash[c + 1]:
            return None
        return found

    def diagnostic_follows(self, diagnostics: frozenset, c: int) -> bool:
        last = self._last_diagnostic.get(diagnostics)
        if last is None:
            last = -1
            for p, token in enumerate(self.low):
                if token in diagnostics or (self._heads[p] != token and self._heads[p] in diagnostics):
                    last = p
            self._last_diagnostic[diagnostics] = last
        return last > c

    def matches(self, form: dict, c: int) -> bool:
        low = self.low
        pos = c + 1
        for word in form["_argv"][1:]:
            p = self.subcommand_at(word, form["_negators"], pos, c)
            if p is None:
                return False
            pos = p + 1
        if self.diagnostic_follows(form["_all_diagnostics"], c):
            return False
        return not (len(form["argv"]) >= 2 and c + 1 < len(low)
                    and low[c + 1] in self.data["subcommand_diagnostics"])


def _earlier_form(best, found):
    """Of two form indexes (None = no form) the one that comes first in data order."""
    if found is None:
        return best
    return found if best is None or found < best else best


def _wild_positions(texts: list) -> list:
    """Which words of a segment hold an UNQUOTED substitution (CX1-20 `Word.wild`): such a word may stand for any word,
    or for none - the shell fills it in - so the reader treats its slot as matching."""
    return [is_wild(t) for t in texts]


def _segment_form(tokens: list, dialect: str, data: dict):
    """(index of the first form this ONE segment launches or None, the payload hops it opens: [(text, dialect)])."""
    texts = [t for t, _ in tokens]
    low = [t.lower() for t in texts]
    names = [_name(t) for t in texts]
    wild = _wild_positions(texts)
    n = len(texts)
    start = 0
    while start < n and (_ASSIGNMENT_RE.match(texts[start]) or texts[start] in ("{", "}")):
        start += 1

    def skip_options(j: int) -> int:
        while j < n and (low[j].startswith("-") or "=" in low[j] or low[j][:1].isdigit()):
            j += 1
        return j

    chain: list = []
    idx = start
    while idx < n:
        chain.append(idx)
        if wild[idx]:   # (ii) a substitution in the program slot may give nothing: the next word is the program too
            idx = skip_options(idx + 1)
            continue
        is_launcher, subs = _launcher_subs(names[idx], data["launchers"])
        if not is_launcher:
            break
        if subs is None:
            idx = skip_options(idx + 1)
            continue
        j = idx + 1
        while j < n and not wild[j] and low[j].startswith("-") and low[j] not in subs:
            j += 1
        if j < n and (wild[j] or low[j] in subs):   # (i) a wild word in the slot matches any subcommand
            idx = skip_options(j + 1)
            continue
        break
    candidates = set(chain)
    # A reader's flag launches only under its own program (`find -exec pytest`; `echo -exec pytest` runs nothing): the
    # flags of the programs in the chain - and of every program when a substitution may stand for one (F-5, NM-1).
    table = data["reader_runs"]
    flags = (reader_runs_words(data) if any(wild[at] for at in chain)
             else frozenset().union(*(table["flags"].get(names[at], ()) for at in chain)))
    for k in range(n):
        if low[k] in data["verbs"] or low[k] in flags:
            j = k + 1
            if j < n and low[j] == "--":
                j += 1
            if j < n:
                candidates.add(j)
    by_name: dict = {}
    for c in sorted(candidates):
        by_name.setdefault(names[c], []).append(c)
        if isinstance(texts[c], Word):   # (iii) the word with its substitutions deleted is also tried as the program
            by_name.setdefault(_name(cleaned_word(texts[c])), []).append(c)
    words = _SegmentWords(low, data)
    suite = next((k for k in range(n) if names[k] in ("run_suite.py", "run_suite")), None)
    best = None
    for fi, form in enumerate(data["forms"]):
        for c in by_name.get(form["_argv"][0], ()):
            if suite is not None and suite < c:
                continue  # F4: this segment goes through the door
            if words.matches(form, c):
                best = fi
                break
        if best is not None:
            break
    hops: list = []
    for pos in chain:
        shell = data["shells"].get(names[pos])
        if shell is None:
            continue
        style, sdialect = shell
        flag = next((k for k in range(pos + 1, n) if _payload_flag(style, texts[k])), None)
        if flag is not None:
            # The shell's real semantics: PowerShell -Command and cmd /c, /k run the REST OF THE
            # LINE (`pwsh -Command dotnet test`), bash -c takes ONE argument (`bash -c npm test`
            # runs `npm` alone).
            if style in ("powershell", "cmd"):
                payloads = [" ".join(texts[flag + 1:])] if flag + 1 < n else []
            else:
                payloads = [texts[flag + 1]] if flag + 1 < n else []
        else:
            payloads = [texts[k] for k in range(pos + 1, n) if tokens[k][1]]
        hops.extend((payload, sdialect) for payload in payloads)
    return best, hops


def _first_form(text: str, data: dict, dialects: tuple = _DIALECTS):
    """Index (data order) of the first form launched in `text`, or None. The text is read by `walk` in BOTH dialects
    (the host label decides nothing, F-3): its regions at any depth, and the payload hops of the shells in it down to
    `_MAX_PAYLOAD_DEPTH`; past that a payload is an opaque unit, not inspected (F-4, as before)."""
    best = None

    def hops(tokens, reading):
        nonlocal best
        found, payloads = _segment_form(tokens, reading, data)
        best = _earlier_form(best, found)
        return payloads

    for reading in dialects:
        walk(text, reading, hops)
    return best


def launch_readings(command) -> tuple:
    """The shell readings ("bash", "powershell") in which `command` launches a test form: () when none does. A refusal
    names the reading that found the launch (`guard_pre_tool.RUNS_MSG`'s door): a command the bash reading passes
    and only the PowerShell reading blocks is the one a role can write differently."""
    text = argv_text(command)
    data = run_forms()
    return tuple(reading for reading in _DIALECTS if _first_form(text, data, (reading,)) is not None)


def direct_test_form(command, dialect: str = "bash") -> dict | None:
    """The `run_forms` row of a test launch outside run_suite.py, or None (diagnostics do not count).

    A runner's name inside QUOTED TEXT or a comment is a mention, not a call (guard_pre_tool.py
    :124-128): only a form at a command position, behind a launcher, after a verb, inside a shell
    payload, a `$( )` or a bash backtick pair is a launch. `run_suite.py` before the form exempts
    its own segment only; a diagnostic flag exempts its own segment only."""
    text = argv_text(command)
    data = run_forms()
    found = _first_form(text, data)   # `dialect` is kept for the callers: both dialects are read (CX1-20 F-3)
    return None if found is None else data["forms"][found]


def is_direct_test_run(command, dialect: str = "bash") -> bool:
    """A test launch outside run_suite.py (diagnostics-only invocations do not count)."""
    return direct_test_form(command, dialect) is not None


def run_forms_diagnostics_text(form: dict) -> str:
    """The no-run flags a refusal lists for this form: its own, then the global ones."""
    return ", ".join(dict.fromkeys(list(form.get("diagnostics") or []) + run_forms()["_diagnostics_text"]))


def has_write_marker(command: str) -> bool:
    """The command is capable of writing to a file (stderr redirections do not count)."""
    return bool(WRITE_CMD_MARKERS.search(STDERR_REDIRECTS.sub(" ", command or "")))


# Bash/PowerShell prefilter substrings (guard_pre_tool.py, Python-only now — the plugin
# ships no settings.json, so there is no shell layer to prefilter ahead of Python; the
# fast exit is the FIRST thing guard_pre_tool.py's main() does for these tool names).
#
# The runner words are NOT in this tuple any more (B-404): `pytest` was the only one, and a
# project on another runner was never guarded. They come from run_forms() - every argv word of
# some form must occur in the command, read lower-cased with the characters the tokenizer can
# remove from inside a word deleted (py"test" and py`test are `pytest` to the shell). A false
# admit costs one full guard run; a miss would make runs_check unreachable, so the error
# direction of this gate is toward True.
PREFILTER_SUBSTRINGS = (
    "touch", "Set-Content", "Add-Content", "Out-File", "Remove-Item",
    "Move-Item", "Copy-Item", ">", "rm ", "del ", "mv ", "cp ", "tee ", "sed -i",
)


def needs_guard(command: str, cfg: dict, event: dict | None = None) -> bool:
    """True when a Bash/PowerShell command is worth running the full guard over: it
    contains a write-capable marker, a direct test launch, or an app_root path fragment.
    False -> guard_pre_tool.py exits 0 immediately without loading config-derived regexes."""
    cmd = command or ""
    if any(s in cmd for s in PREFILTER_SUBSTRINGS):
        return True
    if "$(" in cmd or "`" in cmd:
        return True   # a substitution may build a word (`py$(true)test`): the cleaned view needs the walker (CX1-20 F-6)
    norm = cmd.lower().translate(_STRIP_TABLE)
    if any(all(word in norm for word in words) for words in launch_prefilter_tokens()):
        return True
    try:
        resolve_app_root(cfg, event)
        for p_rel in cfg.get("protected_app_paths", []):
            if str(p_rel).strip() and str(p_rel).lower() in cmd.replace("\\", "/").lower():
                return True
    except Exception:
        return True  # doubt -> run the full guard
    return False


def session_has_factory_activity(session_id: str, event: dict | None = None) -> bool:
    """True when this session ever opened a doctor/onboarding/story activity: the guard's
    read-size limit and turn counter apply only inside real factory work, never to a session
    that merely sits with its cwd inside the project (a Git Bash `cd`, an unrelated analysis
    session) — that was exactly what left `state/cost/` and `state/turns/` files behind for
    sessions the factory never touched. Reads the activity file cost_capture.py already reads
    (activity_capture.load(activity_capture.activity_path(...))) directly — no subprocess, no
    controller import: this runs on every guarded tool call, so hook latency matters. Any
    failure (module missing, file missing, bad JSON) reads as False, same as "no activity yet".
    """
    if not session_id:
        return False
    try:
        from activity_capture import activity_path, load
    except Exception:
        return False
    try:
        doc = load(activity_path(event, session_id), session_id)
    except Exception:
        return False
    return any(isinstance(a, dict) and a.get("type") in ("doctor", "onboarding", "story")
               for a in doc.get("activities") or [])


_SUBAGENT_ROLE_RE = re.compile(r"You are\s+([\w-]+)")
_SUBAGENT_TICKET_RE = re.compile(r"\bTicket:\s*([\w-]+)")
_SUBAGENT_DISPATCH_RE = re.compile(r"\bDispatch(?: id)?:\s*([\w\-]+(?:\.[\w\-]+)*)")   # `story_step._prompt` writes `Dispatch: <id>.`; the final dot is no part of the id


def subagent_meta(transcript: Path) -> dict:
    """{"role", "ticket", "dispatch_id", "first_at", "last_at"} read from one subagent
    transcript (subagents/agent-*.jsonl): role/ticket/dispatch id come from the FIRST user
    message — the orchestrator's own "You are <role>. Ticket: <TICKET>. Dispatch id: <id>..."
    prompt (`skills/qa-story/phases/*.md` all use this wording); first_at/last_at are epoch
    seconds spanning every timestamped record in the file. cost_capture.py uses `ticket` to
    attribute a role dispatch that opens with no workflow marker of its own ("a role
    with no marker: ticket from its prompt, then the activity, then '(no task)'" — on
    TP1-15045 three of five role dispatches in 57cf578c fell into a gap between two
    activity segments and were billed to nobody). Any value that cannot be found stays None.
    Never raises: an unreadable or malformed transcript reads as "nothing known", same as a
    role dispatched with no context at all."""
    result = {"role": None, "ticket": None, "dispatch_id": None, "first_at": None, "last_at": None}
    try:
        from datetime import datetime
        first_at = last_at = None
        prompt_text = None
        for line in Path(transcript).read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            ts = rec.get("timestamp")
            if ts:
                try:
                    epoch = datetime.fromisoformat(str(ts).replace("Z", "+00:00")).timestamp()
                except ValueError:
                    epoch = None
                if epoch is not None:
                    first_at = epoch if first_at is None else min(first_at, epoch)
                    last_at = epoch if last_at is None else max(last_at, epoch)
            if prompt_text is None and rec.get("type") == "user":
                content = (rec.get("message") or {}).get("content")
                if isinstance(content, str):
                    prompt_text = content
                elif isinstance(content, list):
                    parts = [b.get("text", "") for b in content
                             if isinstance(b, dict) and b.get("type") == "text"]
                    if parts:
                        prompt_text = "\n".join(parts)
        result["first_at"] = first_at
        result["last_at"] = last_at
        if prompt_text:
            m = _SUBAGENT_ROLE_RE.search(prompt_text)
            if m:
                result["role"] = m.group(1)
            m = _SUBAGENT_TICKET_RE.search(prompt_text)
            if m:
                result["ticket"] = m.group(1)
            m = _SUBAGENT_DISPATCH_RE.search(prompt_text)
            if m:
                result["dispatch_id"] = m.group(1)
    except Exception:
        pass
    return result


def story_subagent_transcripts(project_root_dir: Path) -> list:
    """Every subagent transcript (subagents/agent-*.jsonl) of sessions that touched this
    project: derived from `state/cost/*.json`'s own `transcript` field and that file's
    sibling `subagents/` directory — the exact layout `cost_capture.py` already reads, no new
    tracking file and no guess at the host's project-directory encoding. A cost file that
    predates the `transcript` field, or whose transcript no longer exists on disk, simply
    contributes nothing: this is best-effort inventory for dispatch_liveness and the
    controller, never a source of truth. Never raises."""
    out: list = []
    try:
        cost_dir = Path(project_root_dir) / "qa-factory" / "state" / "cost"
        if not cost_dir.is_dir():
            return out
        for f in sorted_paths(cost_dir.glob("*.json")):
            try:
                doc = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            transcript = doc.get("transcript")
            if not transcript:
                continue
            tpath = Path(transcript)
            sub_dir = tpath.parent / tpath.stem / "subagents"
            if not sub_dir.is_dir():
                continue
            out.extend(sorted_paths(sub_dir.glob("agent-*.jsonl")))
    except Exception:
        pass
    return out


def _safe_mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _remove_telemetry_pair(raw: Path) -> int:
    """Delete a raw span file and its `.aggregate.json` companion (cost_capture.py's Stop-time
    telemetry_capture.maintain() writes one next to every *.jsonl with at least one event, so
    almost every raw file has one by the time rotation runs). Missing companion is not an
    error — most command files never got maintain()'d before the newest N pushed them out."""
    removed = 0
    for f in (raw, raw.with_suffix(".aggregate.json")):
        try:
            f.unlink()
            removed += 1
        except OSError:
            pass
    return removed


def rotate_telemetry(telemetry_dir: Path, cfg: dict | None, *, keep_paths=(), now: float | None = None,
                      interval_s: float = 60.0) -> dict:
    """Prune `qa-factory/state/telemetry/` so a multi-day session does not leave thousands of
    files for a person to `git status` past one by one (7375 hook-<pid>.jsonl files and
    127 command-<pid>.jsonl/.aggregate.json pairs, 27 MB, from five days — telemetry_hook.py
    never reuses a pid, so every hook process leaves its own file, and cost_capture.py's own
    maintenance only rotates a single file past 10 MB or deletes it past 30 days: neither
    limits how many small per-process files pile up between those events).

    Called from telemetry_hook.py on EVERY hook event, so it must cost near nothing on a
    normal call: a `.rotated-at` marker file's mtime gates the real work (two glob()s over the
    directory) to once per `interval_s` (default 60s, i.e. "once a minute" — the brief's other
    option, once per N writes, would need its own counter file stat()ed just as often for no
    cheaper a check). A burst of PreToolUse/PostToolUse/SubagentStop/Stop calls in that window
    costs one extra stat() each and nothing more.

    Keeps `telemetry.keep_days` (default 7) worth of hook-*.jsonl files by mtime, and the
    newest `telemetry.keep_commands` (default 200) command-*.jsonl files by mtime; each raw
    file removed takes its `.aggregate.json` companion with it. `keep_paths` is never removed
    even if it would otherwise be a victim (the CURRENT hook's own span file, passed in before
    it necessarily exists) — belt-and-suspenders alongside the fact that a just-written file is
    always the newest and so never last in a keep-N or before-cutoff selection. Never raises:
    a telemetry directory is disposable, and a rotation bug must never turn a hook into a
    blocked tool call."""
    result = {"ran": False, "removed": 0}
    try:
        telemetry_dir = Path(telemetry_dir)
        now = time.time() if now is None else now
        keep = {str(Path(p)) for p in keep_paths}
        marker = telemetry_dir / ".rotated-at"
        try:
            due = (now - marker.stat().st_mtime) >= interval_s
        except OSError:
            due = True  # no marker yet (first run, or directory just created) -> rotate once
        if not due:
            return result
        telemetry_dir.mkdir(parents=True, exist_ok=True)
        try:
            marker.write_text(str(now), encoding="utf-8")
        except OSError:
            pass

        telemetry_cfg = (cfg or {}).get("telemetry") or {}
        try:
            keep_days = max(0, int(telemetry_cfg.get("keep_days", 7)))
        except (TypeError, ValueError):
            keep_days = 7
        try:
            keep_commands = max(0, int(telemetry_cfg.get("keep_commands", 200)))
        except (TypeError, ValueError):
            keep_commands = 200

        removed = 0
        cutoff = now - keep_days * 86400
        hooks = sorted((f for f in telemetry_dir.glob("hook-*.jsonl") if str(f) not in keep),
                       key=_safe_mtime, reverse=True)
        for f in hooks:
            if _safe_mtime(f) < cutoff:
                removed += _remove_telemetry_pair(f)

        commands = sorted((f for f in telemetry_dir.glob("command-*.jsonl") if str(f) not in keep),
                           key=_safe_mtime, reverse=True)
        for f in commands[keep_commands:]:
            removed += _remove_telemetry_pair(f)

        result["ran"] = True
        result["removed"] = removed
    except Exception:
        pass
    return result


# --- the ONE catcher of a hook's advice and signals (RH1-5, AR-15) ----------------------------------------------
# A hook that exits 0 and prints its advice to stderr, or prints bare stdout on PostToolUse, says it to nobody on
# Claude Code (experiment E-1, review t-1318 B1): the text is lost and the hook "warned". Two roads reach somebody:
# the model that reads the call's result (`notice`, delivered by `take_notices` through the host adapter's
# `notice_output`), and the person (`person_signal`, an event `hook_signal` in the journal that the run report reads,
# `report_facts._hook_signals`). Nothing else may carry an advice at exit 0.
MODEL_CHANNEL_EVENTS = ("PreToolUse", "PostToolUse", "SessionStart", "UserPromptSubmit", "SubagentStart")
NOTICE_READERS = ("role", "orchestrator", "person")
_NOTICES: list = []          # (text, reader) of this process, in the order they were said
_SIGNAL_LAST_RESORT = "factory signal (no journal could be written)"


def _once_flag(event, key: str):
    """The marker file of "said once in this session" (OS temp: session state, not factory state, not git), or None
    when the event has no session id (then the notice is said every time: noise beats silence)."""
    import hashlib
    import tempfile

    sid = str((event or {}).get("session_id") or "").strip()
    if not sid:
        return None
    tag = hashlib.sha1(f"{sid}|{key}".encode("utf-8")).hexdigest()[:16]
    return Path(tempfile.gettempdir()) / f"qa-factory-warn-{tag}"


def notice(event, text, *, reader: str = "role", once_key: str = "") -> None:
    """Queue an advice for whoever must read it: `reader` is `role` (the model that made the call, or the
    subagent), `orchestrator` (the session that called an Agent/Task) or `person` (nobody on the model side: it goes
    to the journal as a signal). `take_notices` delivers it at the end of the hook. Empty text says nothing (E22).

    `once_key`: said once per session. The marker is set AFTER the text is queued (E20): a marker that could not be
    written means it is said again, never lost. No session id: every time (as `warn_once` always did)."""
    text = str(text or "").strip()
    if not text:
        return
    if reader not in NOTICE_READERS:
        reader = "role"
    flag = _once_flag(event, once_key) if once_key else None
    try:
        if flag is not None and flag.exists():
            return
    except Exception:
        pass
    _NOTICES.append((text, reader))
    if flag is not None:
        try:
            flag.write_text("1", encoding="utf-8")
        except Exception:
            pass  # fail-open: the marker is not written - it is said again next time


def drain_notices() -> list:
    """Take and forget what `notice` queued, as (text, reader) pairs in the order said (the public reader of the queue).

    For a caller that hands the advice to the host itself (inject_context's `rewrite_output`) instead of
    `take_notices`; nobody else touches `_NOTICES`."""
    queued, _NOTICES[:] = list(_NOTICES), []
    return queued


def take_notices(event, code: int = 0, *, default_event: str = "PreToolUse") -> str:
    """Deliver and forget what `notice` queued; returns the text said to the MODEL (or "").

    Exit 0: ONE `notice_output` object with the texts joined by a newline (K7, E19) - to the model, for the readers
    `role`/`orchestrator` on an event that has a model channel; a `person` notice, and any notice of an event with no
    model reader (SubagentStop, Stop, PreCompact, async hooks), goes to the journal as `person_signal` (E18).
    Exit 2 (another rule refused this call) and any other exit: stderr AFTER the refusal, marked as not part of it.
    `default_event`: the name for an event that carries none (the guard is hooked on PreToolUse only)."""
    queued = drain_notices()
    if not queued:
        return ""
    event = dict(event or {})
    name = event.get("hook_event_name") or default_event
    event["hook_event_name"] = name
    model_ok = name in MODEL_CHANNEL_EVENTS
    said = [text for text, reader in queued if reader != "person" and model_ok]
    for text, reader in queued:
        if reader == "person" or not model_ok:
            person_signal(event, "notice", text)
    if not said:
        return ""
    body = "\n".join(said)
    try:
        if code == 0:
            from host_adapter import notice_output
            notice_output(event, body)
        else:
            print(("(Not part of the refusal above.) " if code == 2 else "") + body, file=sys.stderr)
    except Exception:
        pass      # a notice never changes the way the hook ended
    return body


def append_journal_line(event, rec: dict) -> None:
    """THE one writer of a line into the project's journal from a hook (RH1-5 fix round, N8; AR-18): stamps `ts` (UTC,
    ISO, `+00:00`, seconds) and `seeded` (a drill), creates the folder, appends one JSON line. Raises on a failed write:
    the caller decides (`person_signal` never lets it out; `exit_gate.journal_gate` lets it fail as it always did)."""
    from datetime import datetime, timezone
    import runtime_paths as RP
    line = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), **rec}
    if is_seeded():
        line["seeded"] = True
    journal = RP.configured(project_root(event), load_config(event).get("journal_path"), "journal.jsonl")
    journal.parent.mkdir(parents=True, exist_ok=True)
    with journal.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(line, ensure_ascii=False) + "\n")


def person_signal(event, kind: str, text, *, task=None, once_key: str = "") -> bool:
    """Write one `hook_signal` line to the project's journal (the file `exit_gate.journal_gate` writes: one durable
    stream) and return whether it landed. The run report reads these lines (`report_facts._hook_signals`), so a
    default the factory took without a person (a guard that crashed and allowed, a config it could not check) is never
    silent (FR-4, FR-59). Empty text says nothing (E22). A write that fails goes to stderr as the last resort and
    NEVER raises: a signal must not change how the hook ends (E16)."""
    text = str(text or "").strip()
    if not text:
        return False
    flag = _once_flag(event, f"signal|{kind}|{once_key}") if once_key else None
    try:
        if flag is not None and flag.exists():
            return False
    except Exception:
        pass
    line = {"event": "hook_signal", "agent": Path(sys.argv[0] or "hook").name or "hook", "kind": kind,
            "task": task if task is not None else _signal_task(event), "session": str((event or {}).get("session_id") or ""),
            "notes": text}
    landed = False
    try:
        if not _carries_project(project_root(event)):
            # No factory marker: a journal folder is not created in a project that never onboarded (E16, the last resort).
            raise FileNotFoundError("no onboarded project")
        append_journal_line(event, line)
        landed = True
    except Exception as exc:
        try:
            print(f"{_SIGNAL_LAST_RESORT}: {kind}: {text} ({type(exc).__name__})", file=sys.stderr)
        except Exception:
            pass
    if landed and flag is not None:
        try:
            flag.write_text("1", encoding="utf-8")
        except Exception:
            pass
    return landed


def _signal_task(event) -> str:
    """The story a signal is about: what the dispatch names (`stage_guard.requested_ticket`), else ""."""
    try:
        import stage_guard
        return stage_guard.requested_ticket(event or {}) or ""
    except Exception:
        return ""


def warn_once(event: dict | None, key: str, message: str) -> None:
    """Say a warning once per session instead of on every tool call (now `notice(once_key=key)`: the old body printed
    to stderr at exit 0, which nobody reads).

    Measurement lesson: the guard printed "protected paths not found" on EVERY Bash/Edit
    call - 330 repeats over one story run. Repetition does not strengthen the signal, it
    only clogs the context and the log. The marker lives in the OS temp directory: this is
    session state, not factory state, and has no business in git. No session_id - say it
    every time (noise beats silence). The reader is the model that made the call; a caller whose
    reader is the person uses `person_signal(..., once_key=key)`."""
    notice(event, message, reader="role", once_key=key)


# --- version coherence (t-232 F-VERSION) -------------------------------------------------------
# Four places carry "which version is this": the plugin that RUNS (the cache copy), the marketplace
# it was installed from, the install manifest the project's last onboarding wrote, and the
# readiness report. They drift apart silently: on one machine the cache held 0.7.9 (installed
# 22.09) while the marketplace source was at 0.7.19 and the project's readiness said 0.7.4, and
# nobody was told. ONE function reads them, and two callers print its line (FR-17): the SessionStart
# hook (`session_start_version_line`) and onboarding's preflight (`onboard_apply.py --preflight`).
# Reading never raises: a carrier that cannot be read is the word `unknown` in the line (FR-41).
VERSION_PLUGIN = "qa-factory"
# The marketplace of a copy outside the plugin cache (a frozen copy); a cached copy reports the name in its own install path (O5).
VERSION_MARKETPLACE = "qafactory"


def _json_or_none(path):
    return read_json(path, kind=dict)


def _version_text(value):
    """The version as text when it looks like one (`0.7.19`), else None."""
    text = str(value).strip() if isinstance(value, (str, int, float)) and not isinstance(value, bool) else ""
    return text if re.match(r"^\d+(\.\d+)*$", text) else None


def _version_tuple(text) -> tuple:
    return tuple(int(part) for part in text.split(".")) if text else ()


def _claude_home(claude_home=None) -> Path:
    if claude_home:
        return Path(claude_home)
    env = os.environ.get("CLAUDE_CONFIG_DIR")
    return Path(env) if env else Path.home() / ".claude"


def _package_version_at(directory) -> tuple:
    """(version or None, state) of the plugin.json under a package directory."""
    path = Path(directory) / ".claude-plugin" / "plugin.json"
    if not path.is_file():
        return None, "absent"
    data = _json_or_none(path)
    version = _version_text(data.get("version")) if data else None
    return version, ("ok" if version else "unreadable")


def version_carriers(project=None, *, plugin_root=None, claude_home=None) -> dict:
    """The four carriers, each {version, state, ...}; state is `ok`, `absent` (nothing there to
    read: no manifest yet, no marketplace configured) or `unreadable`. Always the same keys (FR-14):

      running    the plugin this code belongs to (`plugin_root`); `frozen` is True when it does not
                 live under <claude home>/plugins/cache (an experiment's copy), `path` names it
      source     the marketplace's own copy of the package: `extraKnownMarketplaces.<name>` in
                 the user's settings.json, else known_marketplaces.json, then the plugin's `source`
                 in the marketplace's own marketplace.json
      manifest   `package_version` of <project>/qa-factory/install-manifest.json
      readiness  `runtime_paths.package_version` of the project's readiness.json (it is written
                 by readiness.py, regenerated at onboarding, and read here only to notice a stale one)
    """
    root = Path(plugin_root) if plugin_root else PLUGIN_ROOT
    home = _claude_home(claude_home)
    out = {"running": {"version": None, "state": "unreadable", "path": str(root), "frozen": True},
           "source": {"version": None, "state": "absent", "path": None},
           "manifest": {"version": None, "state": "absent"},
           "readiness": {"version": None, "state": "absent"}}
    try:
        version, state = _package_version_at(root)
        marketplace, plugin = VERSION_MARKETPLACE, VERSION_PLUGIN
        try:
            parts = root.resolve().relative_to((home / "plugins" / "cache").resolve()).parts
            if len(parts) >= 2:
                marketplace, plugin = parts[0], parts[1]
            out["running"]["frozen"] = False
        except (ValueError, OSError):
            pass
        out["running"].update({"version": version, "state": state})
        out["running"]["marketplace"], out["running"]["plugin"] = marketplace, plugin

        settings = _json_or_none(home / "settings.json") or {}
        entry = ((settings.get("extraKnownMarketplaces") or {}).get(marketplace) or {})
        where = (entry.get("source") or {}).get("path") or entry.get("path") if isinstance(entry, dict) else None
        if not where:
            known = (_json_or_none(home / "plugins" / "known_marketplaces.json") or {}).get(marketplace) or {}
            where = known.get("installLocation") if isinstance(known, dict) else None
        if where:
            listing = _json_or_none(Path(where) / ".claude-plugin" / "marketplace.json") or {}
            rows = [r for r in (listing.get("plugins") or []) if isinstance(r, dict) and r.get("name") == plugin]
            source = rows[0].get("source") if rows else None
            if isinstance(source, str):
                version, state = _package_version_at(Path(where) / source)
                out["source"] = {"version": version, "state": "unreadable" if state == "absent" else state, "path": str(Path(where) / source)}
            else:
                out["source"] = {"version": None, "state": "unreadable", "path": str(where)}
    except Exception:
        pass
    if project:
        try:
            base = Path(project) / "qa-factory"
            if (base / "install-manifest.json").exists():
                import install_paths
                manifest = install_paths.read_manifest(project)
                version = _version_text(manifest.get("package_version")) if manifest and manifest["status"] == "ok" else None
                out["manifest"] = {"version": version, "state": "ok" if version else "unreadable"}
            import runtime_paths
            ready_file = runtime_paths.readiness(project)   # state/readiness.json, or the old place beside the config
            if ready_file.exists():
                data = _json_or_none(ready_file) or {}
                version = _version_text((data.get("runtime_paths") or {}).get("package_version"))
                out["readiness"] = {"version": version, "state": "ok" if version else "unreadable"}
        except Exception:
            out["manifest"] = out["manifest"] if out["manifest"]["state"] != "absent" else {"version": None, "state": "unreadable"}
    return out


def _project_needs_migration(project) -> bool | None:
    """Does the project's configuration need a migration? False ONLY on a positive "ok" schema verdict
    (`readiness.check_config_schema`) over a config read through `config_contract.read_config_file`;
    True on any other verdict; None when that could not be established (no config.json, unreadable,
    any exception). The caller silences a line on False only, so every doubt errs toward printing."""
    try:
        import config_contract
        import readiness
        cfg = config_contract.read_config_file(Path(project))
        if cfg is None:
            return None
        return readiness.check_config_schema(config_contract.effective_config(cfg)).get("status") != "ok"   # the verdict readiness reports
    except Exception:
        return None


def version_line(project=None, *, plugin_root=None, claude_home=None) -> str:
    """ONE line when the carriers that CAN be read do not all say the same version, else "". An
    unreadable carrier is named `unknown` in the line (it never counts as agreeing, and never as a
    version); a carrier with nothing to read (no manifest yet) is not a disagreement. The line
    says what runs, what the marketplace has, what installed this project, and the one move that
    follows: update the plugin when it is the one behind, run the onboarding again when the project
    is. EXCEPTION (AR-3, an older project runs without re-onboarding): when the ONLY disagreement is
    that the project's own carriers (install manifest, readiness report) are older than the running
    plugin, the line is printed only when the project's configuration needs a migration or that
    could not be established; a positive "ok" schema verdict from a config that was read silences
    it. An UNREADABLE project carrier (install manifest or readiness report) is an unknown and is
    never silenced, whatever the config says (FR-59). A plugin that is behind, a frozen package that differs, or a marketplace older than the
    running copy always print."""
    c = version_carriers(project, plugin_root=plugin_root, claude_home=claude_home)
    seen = {k: v["version"] for k, v in c.items() if v["version"]}
    if len(set(seen.values())) < 2:
        return ""
    running, source, manifest, ready = c["running"], c["source"], c["manifest"], c["readiness"]
    path = str(running["path"]).replace("\\", "/")
    ours = f"{running['version']}" if running["version"] else "unknown"
    parts = [f"the factory running here is a frozen package: {path} ({ours})" if running["frozen"]
             else f"the factory running here is {ours}"]
    parts.append(f"the marketplace has {source['version'] or 'unknown'}")
    if project:
        if manifest["state"] == "absent":
            parts.append("this project has no record of an installation")
        else:
            parts.append(f"this project was installed by {manifest['version'] or 'unknown'}")
        if ready["state"] != "absent" and (ready["version"] is None or (
                ready["version"] != manifest["version"] and ready["version"] != running["version"])):
            parts.append(f"its readiness report was written by {ready['version'] or 'unknown'}")
    mine = _version_tuple(running["version"])
    ahead = [v for v in (_version_tuple(source["version"]), _version_tuple(manifest["version"])) if v]
    behind = [v for v in (_version_tuple(manifest["version"]), _version_tuple(ready["version"])) if v]
    plugin_behind = bool(mine) and any(v > mine for v in ahead)
    project_behind = bool(mine) and (any(v < mine for v in behind) or (manifest["state"] == "absent" and bool(ready["version"])))
    source_older = bool(mine) and bool(_version_tuple(source["version"])) and _version_tuple(source["version"]) < mine
    if (project and project_behind and not plugin_behind and not running["frozen"] and not source_older
            and "unreadable" not in (manifest["state"], ready["state"])
            and _project_needs_migration(project) is False):
        return ""
    plugin, market = running.get("plugin") or VERSION_PLUGIN, running.get("marketplace") or VERSION_MARKETPLACE
    advice = ""
    if plugin_behind:
        advice = (f" - update the plugin (`claude plugin uninstall {plugin}@{market}`, `claude plugin marketplace update "
                  f"{market}`, `claude plugin install {plugin}@{market}`), restart, and run the onboarding again")
    elif project_behind:
        advice = " - run the onboarding again"
    return "QA Factory versions differ: " + "; ".join(parts) + advice


def session_start_version_line(event: dict | None = None, *, plugin_root=None, claude_home=None) -> str:
    """The line for the SessionStart hook to print, ONCE per session: the hook fires on startup,
    resume, clear and compact, and the same session must not be told four times (same marker
    idea as warn_once, in the OS temp directory: session state, not factory state). "" when the
    versions agree, when this session already got the line, or when anything at all goes wrong -
    a version note must never stop a session from starting."""
    try:
        line = version_line(project_root(event) if _carries_project(project_root(event)) else None,
                            plugin_root=plugin_root, claude_home=claude_home)
        if not line:
            return ""
        import hashlib
        import tempfile
        sid = str((event or {}).get("session_id") or "").strip()
        if sid:
            flag = Path(tempfile.gettempdir()) / ("qa-factory-version-" + hashlib.sha1(sid.encode("utf-8")).hexdigest()[:16])
            if flag.exists():
                return ""
            try:
                flag.write_text("1", encoding="utf-8")
            except OSError:
                pass
        return line
    except Exception:
        return ""


def run_stop_hook(decide, name: str, crash_text: str) -> None:
    """THE runner of a Stop hook that decides `(exit code, text for stderr)` (AR-15; `conductor_stop`, `gate_shown`).

    Reads the event from stdin, calls `decide(event)`, prints the text to stderr, exits with the code. Any exception is
    exit 0 and ONE `gate_unreadable` signal carrying `crash_text` (a hook never blocks on its own defect, and says so;
    `once_key` = `name|<exception type>`). Never returns."""
    event = None
    try:
        raw = sys.stdin.read()
        event = json.loads(raw) if raw.strip() else None
        code, text = decide(event)
    except Exception as exc:  # noqa: BLE001 - a hook never blocks on its own defect, and says so
        code, text = 0, ""
        try:
            person_signal(event if isinstance(event, dict) else {}, "gate_unreadable",
                          crash_text.format(exc=type(exc).__name__), once_key=f"{name}|{type(exc).__name__}")
        except Exception:  # noqa: BLE001
            pass
    if text:
        print(text, file=sys.stderr)
    sys.exit(code)
