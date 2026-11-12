#!/usr/bin/env python3
"""Which environment a project's tests should run in, chosen from the project (C3-18, part 1).

A test command such as `pytest` resolves on the PATH of whatever process launches it. On a
machine where the project's libraries live in the project's own virtual environment, that is
the wrong interpreter: the run dies on an ImportError and the factory used to call it a stand
gap. This module only CHOOSES the environment and builds the environment variables a launch
would use; it does not launch tests, install anything or write anything (FR-45). The one
process it starts is `poetry env info -p`, and a failure of that process is a rejected source,
never a traceback.

    resolve(project_root, profile=None, environ=None, *, timeout=20) -> dict
    launch_argv(argv, env) -> list
    checked_launch(argv, env) -> list   (raises CmdUnsafe; cmd_unsafe(resolved_argv) -> tokens)
    python -B scripts/project_env.py <project_root> [--profile <config.json>] [--json]

The command line prints what `resolve` would choose for a root (`source:`, `where:`, `python:`,
then one `rejected: <source> - <reason>` line each); exit 2 with one stderr line for a root that
is not a directory. `--profile` takes the project's `qa-factory/config.json` (its selected
profile, else the first).

`resolve` returns exactly this shape (FR-14, a contract the launch sites will read):

    {"source":   "profile_wrapper" | "active_venv" | "package_manager" | "dir" | "inherited",
     "where":    where the environment is: a path relative to `project_root` (forward slashes)
                 when it lies inside the project, else "<source>:<dir name>" (never an absolute
                 path, audit A20); "" for inherited,
     "env":      the overlay, a COPY of `environ` (never the dict passed in, never os.environ
                 itself): for `active_venv`, `package_manager` and `dir` the environment's
                 executable folder (Scripts on Windows, bin elsewhere) is FIRST on PATH and
                 VIRTUAL_ENV names the environment; for `profile_wrapper` and `inherited` the
                 copy is unchanged (a wrapper such as `poetry run` brings its own environment,
                 and the profile is never overridden by a guess),
     "rejected": [(source, reason), ...] for every source that was tried and refused, in the
                 order tried; the reasons are `foreign`, `not installed`, `timeout`,
                 `not found`, `no project root`, `mixed commands`}

Source order (spec t-846 section L, F2): (i) the profile's wrapper, (ii) the active virtual
environment of the PROJECT, (iii) the package manager the profile names, (iv) a `.venv` or
`venv` folder, (v) inherited. A source that finds nothing is skipped; a source that finds
something it must not use (an environment outside the project) is recorded in `rejected`.

Profile keys read (the shape of a `profiles[]` row of `qa-factory/config.json`, as in the
cmp3gb copy): `commands.<name>.argv`, `commands.<name>.cwd` and `commands.<name>.kind` (only
the commands of kind `test` or `collect` count: a `poetry run ruff` lint command says nothing
about how the tests are started), and `execution_prerequisites.package_manager` (prose such
as "poetry 2.4.1": its first word is compared with the launchers of `launch-causes.json`
`wrappers`, no phrase list). Nothing else of the profile is read.

`project_root` must be the ORIGINAL project root. A caller that works in a clone (the
`red_sandbox` probes copy tracked files into a temp folder) passes the root of the project the
clone came from, not the clone: the `.venv` is not copied and Poetry keys its environment by
the project's path, so the clone's own root would resolve to `inherited` (spec section L-2,
F3). The environment belongs to the project; the clone is only sources.

`launch_argv` is the ONLY way the overlay reaches a subprocess on Windows: `Popen` looks up a
bare `argv[0]` on the PARENT's PATH, and `env=` does not change that, so the overlay's
`Scripts` folder is never searched (the t-848 probe: `Popen(["zzprobe"], env=overlay)` raised
FileNotFoundError, `Popen` of the `shutil.which` result ran). Every launch site passes its
profile argv through `launch_argv(argv, env)` for the call only; the record, the digest and the
rehearsal key keep the profile's own argv. `checked_launch(argv, env)` is `launch_argv` plus a refusal
(`CmdUnsafe`, an OSError) of an argument a Windows `.cmd` wrapper would corrupt. The sites that use it:
`node_ids._run` and `node_ids.run_captured` (the report probe of gate_preflight, `run_suite.probe_runtime`,
`execution_request.rehearsal_probe`, `runtime_probe.do_suggest`), and `run_suite.run`. NOT yet: `story_run`
`build_run_probe` and `run_argv` (a remainder named in the EP1-35 report), and `dependency_drift`
(`launch_argv` alone).

`environ`, `os_name`, `run` and `which` are injectable (the same habit as
`launch_check.probe`), so a test starts nothing and pins both folder layouts: `os_name` is
"nt" or "posix" and chooses the folder name only; PATH entries are always joined with the
separator of the machine this runs on.
"""
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import launch_check  # the wrappers table and strip_activation: one recogniser, no twin

SOURCES = ("profile_wrapper", "active_venv", "package_manager", "dir", "inherited")
ENV_DIRS = (".venv", "venv")      # candidate folders of source (iv); the spec's list
TEST_KINDS = ("test", "collect")  # profile command kinds that start tests
POETRY_TIMEOUT_S = 20
CMD_UNSAFE_CHARS = "&|<>^%!\"\n\r"  # what cmd.exe reads in an argument of a .cmd/.bat wrapper (shell form, not project variety)
_DEFAULT_ACTIVATION_VARIABLES = ("VIRTUAL_ENV", "POETRY_ACTIVE")
_DEFAULT_FOLDERS = ("Scripts", "bin")


# --- small helpers ---------------------------------------------------------------------------

# The key of a variable in an environment dict: exact, or any case on Windows. The one copy is
# launch_check's (the clone ratchet refuses a second); it is borrowed, not renamed, because
# launch_check is not this node's file.
_key = launch_check._env_key


def _norm(path) -> str:
    return os.path.normcase(os.path.realpath(str(path)))


def _inside(path, root) -> bool:
    """`path` is `root` or lies under it; both realpath'd and case-normalised."""
    p, r = _norm(path), _norm(root)
    return p == r or p.startswith(r.rstrip(os.sep) + os.sep)


def _rel(path, root) -> str:
    """`path` relative to `root`, forward slashes. The folder holding `path` is realpath'd (a
    short Windows spelling of the same folder must not read as another place), the last name is
    kept as written (a linked `.venv` is still called `.venv`)."""
    parent, name = os.path.split(os.path.normpath(str(path)))
    real = os.path.join(os.path.realpath(parent), name)
    return os.path.relpath(real, os.path.realpath(str(root))).replace("\\", "/")


def _base(token) -> str:
    return re.split(r"[\\/]", str(token).strip())[-1]


def _exe_folder_name(os_name: str) -> str:
    return "Scripts" if os_name == "nt" else "bin"


def _executable_folder(env_dir, os_name: str):
    """`<env>/Scripts` (nt) or `<env>/bin` when it exists and holds a python, else None. A
    folder with no python (a broken link, the other platform's layout) is not an environment."""
    folder = Path(env_dir) / _exe_folder_name(os_name)
    names = ("python.exe",) if os_name == "nt" else ("python", "python3")
    if folder.is_dir() and any((folder / name).is_file() for name in names):
        return folder
    return None


def _overlay(environ: dict, env_dir, folder) -> dict:
    """A copy of `environ` with `folder` first on PATH and VIRTUAL_ENV set; a missing PATH
    becomes the folder alone."""
    env = dict(environ)
    key = _key(env, "PATH") or "PATH"
    old = env.get(key)
    env[key] = str(folder) + (os.pathsep + str(old) if old else "")
    env[_key(env, "VIRTUAL_ENV") or "VIRTUAL_ENV"] = os.path.normpath(str(env_dir))
    return env


def _path_of(env: dict) -> str:
    key = _key(env, "PATH")
    return str(env[key]) if key is not None and env[key] else ""


def _found(source, where, env, rejected) -> dict:
    return {"source": source, "where": where, "env": env, "rejected": rejected}


# --- the profile -----------------------------------------------------------------------------

def _test_commands(profile) -> list:
    """`[(name, argv, cwd)]` of the profile's commands that start tests, in file order."""
    import profile_contract as PC     # the ONE reader of the `commands` shape (OH3-27, AR-13)
    commands, problem = PC.profile_commands(profile)
    if problem:           # a shape it cannot read starts no test here (as no commands)
        return []
    out = []
    for name, spec in commands.items():
        if not isinstance(spec, dict) or spec.get("kind") not in TEST_KINDS:
            continue
        argv, problem = PC.command_argv(spec)
        if problem or not argv:
            continue
        out.append((str(name), argv, str(spec.get("cwd") or ".")))
    return out


def _package_manager(profile) -> str:
    """The first word of `execution_prerequisites.package_manager`, lower case, or ''."""
    prereq = profile.get("execution_prerequisites") if isinstance(profile, dict) else None
    text = prereq.get("package_manager") if isinstance(prereq, dict) else None
    words = text.split() if isinstance(text, str) else []
    return words[0].lower() if words else ""


# --- (i) the profile's wrapper ---------------------------------------------------------------

def wrapped_kind(argv, wrappers=None) -> str:
    """`wrapper` (`poetry run ...`, a `wrappers` row with a subcommand), `venv_python` (argv[0]
    is a path to a python in a `Scripts`/`bin` folder) or `bare`. `wrappers` is the table of
    `launch-causes.json`; omitted, it is read from there (an unreadable table: no wrapper)."""
    if wrappers is None:
        data, _note = launch_check.load_data()
        wrappers = data["wrappers"] if data else {}
    head = argv[0]
    subs = wrappers.get(os.path.splitext(_base(head))[0])
    if subs and len(argv) > 1 and argv[1] in subs:
        return "wrapper"
    parent = re.split(r"[\\/]", head.strip())
    if (len(parent) > 1 and _base(head).lower().startswith("python")
            and parent[-2].lower() in {n.lower() for n in _DEFAULT_FOLDERS}):
        return "venv_python"
    return "bare"


_wrapped_kind = wrapped_kind  # the old private name (tests and t-850 read it)


def _wrapper_source(profile, root, environ, wrappers, which, rejected):
    """`(where, env)` when every test command of the profile starts through a wrapper or a
    venv python that exists, else None (a reason is recorded when one was tried and refused).
    A profile with a bare `pytest` among its test commands leaves that command to the later
    sources: `poetry run ruff` as the lint command, or a wrapper on one command only, does not
    choose the environment of the others."""
    commands = _test_commands(profile)
    if not commands:
        return None
    kinds = [_wrapped_kind(argv, wrappers) for _name, argv, _cwd in commands]
    if all(k == "bare" for k in kinds):
        return None
    if any(k == "bare" for k in kinds):
        rejected.append(("profile_wrapper", "mixed commands"))
        return None
    path = _path_of(environ)
    for (_name, argv, cwd), kind in zip(commands, kinds):
        if kind == "wrapper":
            if not which(argv[0], path=path):
                rejected.append(("profile_wrapper", "not found"))
                return None
            continue
        target = python_target(root, cwd, argv[0])
        if not _inside(target, root):
            rejected.append(("profile_wrapper", "foreign"))
            return None
        if not target.is_file():
            rejected.append(("profile_wrapper", "not found"))
            return None
    _name, argv, cwd = commands[0]
    if kinds[0] == "wrapper":
        where = "profile_wrapper:" + os.path.splitext(_base(argv[0]))[0]
    else:
        where = _rel(os.path.normpath(os.path.join(root, cwd, argv[0])), root)
    return where, dict(environ)


# --- (ii) the active virtual environment of the project --------------------------------------

def _active_source(root, environ, os_name, rejected):
    key = _key(environ, "VIRTUAL_ENV")
    value = str(environ[key]).strip().strip('"') if key is not None and environ[key] else ""
    if not value:
        return None
    if not os.path.isabs(value) or not _inside(value, root):
        rejected.append(("active_venv", "foreign"))
        return None
    folder = _executable_folder(value, os_name)
    if folder is None:
        rejected.append(("active_venv", "not found"))
        return None
    return _rel(value, root), _overlay(environ, value, folder)


# --- (iii) the package manager the profile names ---------------------------------------------

def _pyproject_name(root) -> str:
    """The `name` of the project's pyproject.toml (`project` or `tool.poetry`), or ''."""
    try:
        import tomllib
        data = tomllib.loads((Path(root) / "pyproject.toml").read_text(encoding="utf-8"))
    except (ImportError, OSError, ValueError):
        return ""
    for table in (data.get("project"), (data.get("tool") or {}).get("poetry")):
        name = table.get("name") if isinstance(table, dict) else None
        if isinstance(name, str) and name.strip():
            return name.strip()
    return ""


def _poetry_slug(name: str) -> str:
    """Poetry's own spelling of a project name inside its environment folder name."""
    slug = name.lower()
    for char in ' $`!*@"' + chr(92) + "\r\n\t":
        slug = slug.replace(char, "_")
    return slug[:42]


def _in_poetry_store(env_dir, environ) -> bool:
    parent = os.path.dirname(os.path.realpath(str(env_dir)))
    if os.path.basename(parent).lower() == "virtualenvs":
        return True
    key = _key(environ, "POETRY_VIRTUALENVS_PATH")
    return key is not None and bool(environ[key]) and _norm(parent) == _norm(environ[key])


def _poetry_dir(root, environ, timeout, run, which):
    """`(environment dir, '')` or `(None, reason)` from `poetry env info -p` run in the project,
    in an environment with the activation variables taken out (an activated venv of the factory
    or of another project would otherwise be the answer)."""
    exe = which("poetry", path=_path_of(environ))
    if not exe:
        return None, "not installed"
    data, _note = launch_check.load_data()
    variables = data["deactivated_variables"] if data else _DEFAULT_ACTIVATION_VARIABLES
    folders = data["environment_folders"] if data else _DEFAULT_FOLDERS
    clean = launch_check.strip_activation(environ, variables, folders=folders)[0]
    try:
        done = run([str(exe), "env", "info", "-p"], cwd=str(root), env=clean, capture_output=True,
                   text=True, encoding="utf-8", errors="replace", timeout=timeout,
                   stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return None, "timeout"
    except FileNotFoundError:
        return None, "not installed"
    except (OSError, ValueError):
        return None, "not found"
    if getattr(done, "returncode", 1) != 0:
        return None, "not found"
    for line in str(getattr(done, "stdout", "") or "").splitlines():
        line = line.strip().strip('"')
        if line and os.path.isdir(line):
            return line, ""
    return None, "not found"


def manager_env(root, program, environ, *, timeout=POETRY_TIMEOUT_S, os_name=None, run=None,
                which=None):
    """`(environment dir, '')` or `(None, reason)` of the PROJECT's environment as the package
    manager `program` reports it through a read-only probe (`poetry env info -p`). The dir is
    returned only when it is the project's own (inside the project, or in the Poetry store under
    the project's name); an environment of another project is `(None, 'foreign')`. A program
    with no read-only probe (`uv`, `pdm`, `npx`) is `(None, 'no read-only probe')`: its run
    subcommand would create or sync the environment, and this module writes nothing."""
    run = run or subprocess.run
    which = which or shutil.which
    environ = dict(os.environ) if environ is None else dict(environ)
    name = os.path.splitext(_base(program))[0].lower()
    if name != "poetry":
        return None, "no read-only probe"
    env_dir, reason = _poetry_dir(root, environ, timeout, run, which)
    if env_dir is None:
        return None, reason
    if _inside(env_dir, root):
        return env_dir, ""
    pyname = _pyproject_name(root)
    slug = _poetry_slug(pyname) if pyname else ""
    own = (bool(slug) and _in_poetry_store(env_dir, environ)
           and os.path.basename(os.path.realpath(env_dir)).lower().startswith(slug + "-"))
    return (env_dir, "") if own else (None, "foreign")


def _poetry_source(root, environ, timeout, os_name, run, which, rejected):
    env_dir, reason = manager_env(root, "poetry", environ, timeout=timeout, os_name=os_name,
                                  run=run, which=which)
    if env_dir is None:
        rejected.append(("package_manager", reason))
        return None
    if _inside(env_dir, root):
        where = _rel(env_dir, root)
    else:
        where = "package_manager:" + os.path.basename(os.path.realpath(env_dir))
    folder = _executable_folder(env_dir, os_name)
    if folder is None:
        rejected.append(("package_manager", "not found"))
        return None
    return where, _overlay(environ, env_dir, folder)


# --- (iv) a .venv / venv folder, from the commands' cwd up to the project root ---------------

def walk_dirs(root, profile) -> list:
    """The folders to look in, nearest first: each test command's cwd (when it lies inside the
    project) and every parent up to AND INCLUDING `project_root`, never above it."""
    starts = []
    for _name, _argv, cwd in _test_commands(profile):
        start = os.path.normpath(os.path.join(root, cwd))
        if _inside(start, root) and os.path.isdir(start):
            starts.append(start)
    starts.sort(key=lambda p: -len(_norm(p)))
    chain = []
    for start in starts + [os.path.normpath(str(root))]:
        current = start
        while _inside(current, root):
            if current not in chain:
                chain.append(current)
            parent = os.path.dirname(current)
            if _norm(current) == _norm(root) or parent == current:
                break
            current = parent
    return chain


_walk_dirs = walk_dirs  # the old private name


def _dir_source(root, profile, environ, os_name):
    for folder in walk_dirs(root, profile):
        for name in ENV_DIRS:
            env_dir = os.path.join(folder, name)
            exe = _executable_folder(env_dir, os_name)
            if exe is not None:
                return _rel(env_dir, root), _overlay(environ, env_dir, exe)
    return None


# --- the public functions --------------------------------------------------------------------

def resolve(project_root, profile=None, environ=None, *, timeout=POETRY_TIMEOUT_S,
            os_name=None, run=None, which=None) -> dict:
    """Choose the environment for the project's tests; see the module docstring for the result
    shape, the order and the profile keys. Never raises for a missing root, a missing tool or a
    malformed profile: the answer is `inherited` (or a later source) with the refusals listed.
    `environ` defaults to a copy of `os.environ`; neither is ever mutated.

    Pass the ORIGINAL project root, not a clone's (module docstring)."""
    os_name = os_name or os.name
    run = run or subprocess.run
    which = which or shutil.which
    environ = dict(os.environ) if environ is None else dict(environ)
    rejected = []
    if not project_root or not os.path.isdir(str(project_root)):
        rejected.append(("dir", "no project root"))
        return _found("inherited", "", environ, rejected)
    root = os.path.abspath(str(project_root))
    profile = profile if isinstance(profile, dict) else {}
    data, _note = launch_check.load_data()
    wrappers = data["wrappers"] if data else {}

    got = _wrapper_source(profile, root, environ, wrappers, which, rejected)
    if got:
        return _found("profile_wrapper", got[0], got[1], rejected)
    got = _active_source(root, environ, os_name, rejected)
    if got:
        return _found("active_venv", got[0], got[1], rejected)
    manager = _package_manager(profile)
    if manager == "poetry" and (not wrappers or manager in wrappers):
        got = _poetry_source(root, environ, timeout, os_name, run, which, rejected)
        if got:
            return _found("package_manager", got[0], got[1], rejected)
    got = _dir_source(root, profile, environ, os_name)
    if got:
        return _found("dir", got[0], got[1], rejected)
    return _found("inherited", "", environ, rejected)


def _profile_from(path) -> dict:
    """The profile a `--profile <config.json>` names: the selected row of `profiles` (else the
    first), or the file itself when it is a profile row. Raises ValueError with a sentence."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except OSError as exc:
        raise ValueError(f"{path} cannot be read ({type(exc).__name__}); pass the project's qa-factory/config.json")
    except ValueError as exc:
        raise ValueError(f"{path} is not valid JSON ({exc}); pass the project's qa-factory/config.json")
    rows = data.get("profiles") if isinstance(data, dict) else None
    if isinstance(rows, list):
        import profile_contract            # the one reading of `selected`: a row with no key is selected (AR-13)
        rows = [r for r in rows if isinstance(r, dict)]
        return (profile_contract.selected_profiles({"profiles": rows}) or rows or [{}])[0]
    return data if isinstance(data, dict) else {}


def python_target(root, cwd, argv0):
    """The file a venv-python `argv[0]` names: absolute as written, else under `root/cwd`. The one path rule of
    `_wrapper_source` and of `dependency_drift`."""
    return Path(argv0) if os.path.isabs(argv0) else Path(root) / cwd / argv0


def cli_input(prog, description, argv, err):
    """The command line `project_env.py` and `dependency_drift.py` share (`<project_root> [--profile <config.json>] [--json]`):
    `(args, profile, None)`, or `(None, None, 2)` after one stderr line for a root that is not a directory or a profile file
    that cannot be read."""
    try:
        import console_io
        console_io.utf8_stdio()
    except ImportError:
        pass
    import argparse
    parser = argparse.ArgumentParser(prog=f"{prog}.py", description=description)
    parser.add_argument("project_root")
    parser.add_argument("--profile", help="the project's qa-factory/config.json")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if not os.path.isdir(args.project_root):
        print(f"{prog}: {args.project_root} is not a directory; pass the project root", file=err)
        return None, None, 2
    try:
        return args, (_profile_from(args.profile) if args.profile else None), None
    except ValueError as exc:
        print(f"{prog}: {exc}", file=err)
        return None, None, 2


# The names the dependency check reads, published: no module imports a private name of this one (RH1-4 fix round, m3).
env_key, inside, rel_path, base_name, overlay = _key, _inside, _rel, _base, _overlay
executable_folder, package_manager, test_commands, profile_from = _executable_folder, _package_manager, _test_commands, _profile_from


def main(argv=None, *, out=None, err=None, environ=None) -> int:
    """`project_env.py <project_root> [--profile <config.json>] [--json]`: print the resolution
    the factory would use for that root (which interpreter its tests would run with). Reads only;
    exit 0, or 2 with one stderr line for a root that is not a directory or a profile file that
    cannot be read. `--json` prints the result with `env` cut to PATH and VIRTUAL_ENV (the whole
    environment can hold secrets) and `python`."""
    out, err = out or sys.stdout, err or sys.stderr
    args, profile, code = cli_input("project_env", main.__doc__.split(".")[0], argv, err)
    if code is not None:
        return code
    got = resolve(args.project_root, profile, environ)
    python = shutil.which("python", path=_path_of(got["env"])) or "inherited"
    if args.json:
        shown = {k: got["env"][k] for k in ("PATH", "VIRTUAL_ENV") if k in got["env"]}
        print(json.dumps({"source": got["source"], "where": got["where"], "python": python,
                          "env": shown, "rejected": got["rejected"]}, indent=2), file=out)
        return 0
    print(f"source: {got['source']}\nwhere: {got['where']}\npython: {python}", file=out)
    for source, reason in got["rejected"]:
        print(f"rejected: {source} — {reason}", file=out)
    return 0


def launch_argv(argv, env) -> list:
    """`argv` with `argv[0]` replaced by `shutil.which(argv[0], path=env's PATH)` when found
    (an absolute path, so the overlay's folder is searched on every platform), else unchanged:
    a head that is not found is left to the launch, whose FileNotFoundError readiness reports
    (spec section L, F9). A head that already carries a folder is left alone. An `env` with no
    PATH finds nothing (an empty search path, never the process's own)."""
    args = list(argv)
    if not args or not str(args[0]) or os.path.dirname(str(args[0])):
        return args
    found = shutil.which(str(args[0]), path=_path_of(env if isinstance(env, dict) else {}))
    return [found] + args[1:] if found else args


def head_not_found(head) -> str:
    """The ONE sentence for a launch head that was not found (EP1-35 F-6, AR-15): run_suite's log, the gate's note, the
    onboarding probe's two lines all say it through here. It tells what was really checked: a head with a folder is run
    as written (`launch_argv` never searches PATH for it), a `.ps1` cannot be started directly (the door: `pwsh -File`),
    any other head was looked up on PATH with PATHEXT. Every branch names a door."""
    head = str(head if head else "?")
    if os.path.dirname(head) or "/" in head or "\\" in head:
        return (f"`{head}` carries a folder and is run as written, it was not looked up on PATH, and it was not found; "
                "correct argv[0] of the profile")
    if head.lower().endswith(".ps1"):
        return (f"`{head}` is a PowerShell script and cannot be started directly; start it with pwsh -File, "
                "or correct argv[0] of the profile")
    return f"`{head}` was looked up on PATH with PATHEXT and not found; install it, or correct argv[0] of the profile"


def cmd_unsafe(resolved_argv, os_name=None) -> list:
    """The tokens of `resolved_argv[1:]` that cmd.exe would read as something else than an argument
    (`CMD_UNSAFE_CHARS`), when the head is a Windows `.cmd`/`.bat` wrapper (any case) and the
    platform is `nt`; else `[]`. Python starts such a wrapper through cmd.exe, which reads `&`, `|`,
    `<`, `>` as operators and silently eats `^`, expands `%X%`, cuts at a newline. Refusing too much
    (`!`, a lone `"`) is the safe direction; a token is never escaped."""
    args = [str(a) for a in resolved_argv or []]
    if (os_name or os.name) != "nt" or not args or not args[0].lower().endswith((".cmd", ".bat")):
        return []
    return [a for a in args[1:] if any(ch in a for ch in CMD_UNSAFE_CHARS)]


class CmdUnsafe(OSError):
    """A launch refused because a `.cmd` wrapper would corrupt an argument. Nothing was started."""

    def __init__(self, token, head):
        chars = " ".join(repr(c) for c in CMD_UNSAFE_CHARS if c in token) or "its special characters"
        super().__init__(
            f"the argument {token!r} of this command cannot be passed safely through {head} (a Windows "
            f".cmd wrapper: cmd.exe would read {chars}); nothing was launched. Correct the profile's argv "
            f"so the token holds none of them, or start the runner directly (node <path to its .js>).")


def checked_launch(argv, env) -> list:
    """`launch_argv(argv, env)`, or `CmdUnsafe` when the result is a `.cmd` wrapper with an argument
    cmd.exe would corrupt. The one entry of every launch that must not corrupt silently."""
    resolved = launch_argv(argv, env)
    bad = cmd_unsafe(resolved)
    if bad:
        raise CmdUnsafe(bad[0], resolved[0])
    return resolved


if __name__ == "__main__":
    sys.exit(main())
