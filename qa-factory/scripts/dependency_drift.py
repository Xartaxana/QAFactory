#!/usr/bin/env python3
"""Does what is installed in the PROJECT's environment match the project's own lock? (RH1-4)

The live case (run 12586, 27.10): the lock pins testproject1-sdk 0.1.704, the project's environment has
0.1.700, the tests die on an import and the factory called it a stand gap. This module only
COMPARES and NAMES: the pair of versions and the project's install command. It installs nothing
and writes nothing, not even the environment a wrapper such as `poetry run` or `uv run` would
create on first use (C3-18 part 2 owns running an install; the doctor prints the command, FR-48).

    check(project_root, profile, *, environ=None, run=None, timeout=60) -> dict
    install_command(profile, lock_dir=".") -> {"argv", "cwd", "source"}
    load_table() -> (table, problem)        references/project-dependencies.json, the one reader
    drift_sentence(result) -> str            the one sentence the gate and the doctor say
    check_profiles(root, profiles) -> list   one check per distinct environment, each naming the profiles it covers
    python -B scripts/dependency_drift.py <project_root> [--profile <config.json>] [--json]

`check` returns exactly this shape (FR-14):

    {"state":       "in_sync" | "differs" | "missing_only" | "unknown",
     "lock":        the lock file(s) read, relative to the project root ("" when none),
     "checked":     how many packages of the lock were compared,
     "differs":     [{"name", "installed", "locked", "direction"}], direction `older` / `newer` for plain
                    numeric versions, "" when the order is not known (or the spellings are one number),
     "absent":      [{"name", "locked"}] unconditional packages of the lock that are not installed,
     "conditional": how many packages carry `markers` or `optional = true` and are not installed
                    (they are counted, never required: whether they belong here depends on the platform),
     "why":         one sentence of what was found (or why nothing could be said),
     "environment": {"source", "where", "rejected"}  the PE source of the environment that was read,
     "command":     {"argv", "cwd", "source": "profile" | "table" | "none"}}

Only Poetry locks are read (`toml_packages`). A `uv.lock` or `pdm.lock` is `unknown` with the reason "this lock format is
not read yet": their markers and forks are not Poetry's (a faithful `uv sync` on Linux never installs a win32-only package
that uv marks on the dependency link), so reading them with Poetry's rules would make a `missing_only` that never clears.
Per-format readers, tested on real lock files, are a finding of the run-honesty pile. A readable lock in the same folder
still gets its answer; the unread one is named in `why`.

`unknown` is the answer whenever the installed set was not read from the PROJECT's own environment:
no lock, a lock that cannot be read, an inherited environment, a wrapper the factory has no read-only
probe for, a python outside the environment folder, a timeout, an empty or unparsable answer (a valid `[]` is another fact: the interpreter proved it has no distributions, so every
unconditional package is absent). It is never turned
into `in_sync` (I6) and the environment of the factory is never taken for the project's (I5).
Error direction everywhere: toward `unknown`, then toward advice (a difference), never toward a
silent pass and never toward a write.

How the environment is found (PE `resolve`): `active_venv`, `package_manager` and `dir` give a folder,
and the python read is the one on that folder's PATH overlay, accepted only when it lies INSIDE the
folder. `profile_wrapper` over a venv python is that python; over a launcher the environment comes from
the launcher's read-only probe (`project_env.manager_env`), and the payload never runs through the
launcher. `inherited` is `unknown`. The one write on the Poetry probe path is Poetry's own `envs.toml` (its config
folder, when a stale entry is dropped); nothing is written into the project's environment (I7).
"""
import json
import os
import re
import shlex
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hooklib
import node_ids
import project_env as PE

TABLE_PATH = Path(__file__).resolve().parents[1] / "references" / "project-dependencies.json"
DRIFT_SHOWN = 5          # pairs named in a sentence; the rest is counted ("(+N more)"); the result holds all
PAYLOAD_TIMEOUT_S = 60
# worst first: a difference is acted on, a missing package too, an unreadable half never lets the whole be `in_sync`
_RANK = {"differs": 0, "missing_only": 1, "unknown": 2, "in_sync": 3}
# The installed set, read by the project's own interpreter: [[name, version], ...] as JSON. Fixed text, never built from
# project data. `-I` keeps the working directory and the PYTHON* variables out of the interpreter's path.
PAYLOAD = ("import importlib.metadata as m, json; "
           "print(json.dumps([[(d.metadata['Name'] or ''), d.version or ''] for d in m.distributions()]))")
_PLAIN_VERSION = re.compile(r"^\d+(?:\.\d+)*$")


# --- the table --------------------------------------------------------------------------------------

def load_table(path=None):
    """`(table, problem)`: `{"locks": [...], "install_commands": {...}}` read and checked, or `(None, why)`. The one
    reader of references/project-dependencies.json (hooklib.read_json); a row it cannot trust makes the whole file
    unusable, and the callers say `unknown` / `none`."""
    target = Path(path) if path else Path(TABLE_PATH)
    raw = hooklib.read_json(target, None, kind=dict)
    if raw is None:
        return None, f"{target.name} is unreadable or not a JSON object: the lock table cannot be read"
    locks, commands = raw.get("locks"), raw.get("install_commands")
    if not isinstance(locks, list):
        return None, f"{target.name} has no `locks` list"
    clean = []
    for index, row in enumerate(locks):
        ok = isinstance(row, dict) and all(isinstance(row.get(k), str) and row[k] for k in ("file", "format", "manager"))
        if not ok or os.path.basename(row["file"]) != row["file"]:
            return None, f"{target.name} locks[{index}] needs a plain file name, a `format` and a `manager`"
        clean.append({"file": row["file"], "format": row["format"], "manager": row["manager"]})
    if not isinstance(commands, dict):
        return None, f"{target.name} has no `install_commands` object"
    out = {}
    for manager, argv in commands.items():
        if not isinstance(argv, list) or not argv or any(not isinstance(a, str) or not a for a in argv):
            return None, f"{target.name} install_commands[{manager!r}] must be a non-empty list of strings"
        out[str(manager).lower()] = list(argv)
    return {"locks": clean, "install_commands": out}, ""


# --- the install command ----------------------------------------------------------------------------

def _profile_install(profile):
    import profile_contract as PC     # the ONE reader of the `commands` shape (OH3-27, AR-13)
    spec, problem = PC.profile_command(profile, "install")
    if problem:           # a shape that cannot be read names no install command (as no `install` at all)
        return None
    words, problem = PC.command_argv(spec)
    if problem or not words:
        return None
    return words, str(spec.get("cwd") or "")


def install_command(profile, lock_dir=".", table=None) -> dict:
    """The project's install command: the profile's `commands.install` first, else the table row of the first word of
    `execution_prerequisites.package_manager`, else none. `cwd` is the profile's own, else the folder of the lock.
    `table` is the one `load_table` answer when the caller already holds it. Shown, never run."""
    got = _profile_install(profile)
    if got:
        return {"argv": got[0], "cwd": got[1] or lock_dir, "source": "profile"}
    table = table or load_table()[0]
    manager = PE.package_manager(profile if isinstance(profile, dict) else {})
    argv = table["install_commands"].get(manager) if table and manager else None
    if argv:
        return {"argv": list(argv), "cwd": lock_dir, "source": "table"}
    return {"argv": [], "cwd": lock_dir, "source": "none"}


def command_text(command) -> str:
    """The command as a person types it (`uv sync`); an empty string when there is none."""
    return shlex.join([str(a) for a in command.get("argv") or []])


# --- the lock and the installed set -----------------------------------------------------------------

def _name(text) -> str:
    """PEP 503: runs of `-`, `_`, `.` are one dash, lower case. `Testproject1_SDK` is `testproject1-sdk`; `testproject1-sdk-extra` is not."""
    return re.sub(r"[-_.]+", "-", str(text)).strip().lower()


def _read_lock(path, form):
    """`(packages, problem)`: `[{"name", "key", "version", "conditional"}]` of a lock file."""
    if form != "toml_packages":
        return None, f"{path.name}: this lock format is not read yet"
    try:
        import tomllib
    except ImportError:
        return None, f"{path.name} cannot be read here: this python has no tomllib (3.11 or newer)"
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        return None, f"{path.name} cannot be read ({type(exc).__name__})"
    rows = data.get("package") if isinstance(data, dict) else None
    if rows is None:
        return [], ""
    if not isinstance(rows, list):
        return None, f"{path.name} has a `package` entry that is not a list"
    out = []
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("name"), str) or not isinstance(row.get("version"), str):
            return None, f"{path.name} has a package with no name or no version"
        out.append({"name": row["name"], "key": _name(row["name"]), "version": row["version"],
                    "conditional": bool(row.get("markers")) or row.get("optional") is True})
    return out, ""


def _direction(installed, locked) -> str:
    """`older` / `newer` (the installed one against the lock) for two plain numeric versions that are different numbers;
    `` for anything else - an order nobody can prove is not named (E4-13)."""
    if not (_PLAIN_VERSION.match(installed) and _PLAIN_VERSION.match(locked)):
        return ""
    a, b = tuple(int(p) for p in installed.split(".")), tuple(int(p) for p in locked.split("."))
    width = max(len(a), len(b))
    a, b = a + (0,) * (width - len(a)), b + (0,) * (width - len(b))
    return "" if a == b else ("older" if a < b else "newer")


def _compare(locked, installed) -> dict:
    """The lock's packages against `{key: version}`: the pieces of the result, nothing decided yet."""
    differs, absent, conditional, checked = [], [], 0, 0
    by_name = {}
    for pkg in locked:                        # a lock may carry one name at several versions (forks): the first row speaks
        by_name.setdefault(pkg["key"], []).append(pkg)
    for key, rows in by_name.items():
        pkg, have = rows[0], installed.get(key)
        if have is None:
            if all(r["conditional"] for r in rows):
                conditional += 1
            else:
                checked += 1
                absent.append({"name": pkg["name"], "locked": pkg["version"]})
            continue
        checked += 1
        if have not in {r["version"] for r in rows}:        # differs only when the installed version is NONE of them
            differs.append({"name": pkg["name"], "installed": have, "locked": pkg["version"],
                            "direction": _direction(have, pkg["version"])})
    return {"differs": differs, "absent": absent, "conditional": conditional, "checked": checked}


def _installed(raw):
    """`{normalised name: version}` from the payload's text. `{}` for a valid `[]` (the interpreter proved it has no
    distributions); None for an answer that is not a list of pairs, or a list none of whose pairs is usable (empty or
    unparsable output is `unknown`, never "nothing installed"). The first of a name wins: it is the one an import sees."""
    try:
        rows = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(rows, list):
        return None
    if not rows:
        return {}
    out = {}
    for row in rows:
        if isinstance(row, list) and len(row) == 2 and isinstance(row[0], str) and isinstance(row[1], str) and row[0] and row[1]:
            out.setdefault(_name(row[0]), row[1])
    return out or None


# --- the sentences ----------------------------------------------------------------------------------

def _pairs(result) -> str:
    items = [f"installed {d['name']} {d['installed']}, the lock says {d['locked']}" for d in result.get("differs") or []]
    items += [f"{a['name']} is not installed, the lock says {a['locked']}" for a in result.get("absent") or []]
    shown = "; ".join(items[:DRIFT_SHOWN])
    return shown + (f" (+{len(items) - DRIFT_SHOWN} more)" if len(items) > DRIFT_SHOWN else "")


def _conditional(count) -> str:
    return (f"{count} conditional package{'s were' if count != 1 else ' was'} not checked") if count else ""


def drift_sentence(result) -> str:
    """The pair(s) of versions and the project's install command in one sentence, for a person (the gate note, the card
    phrase, the doctor): "installed testproject1-sdk-python 0.1.700, the lock says 0.1.704; the project's install command:
    `<command>`". Without a command it says what to record. Empty for a state that has nothing to say."""
    if result.get("state") not in ("differs", "missing_only"):
        return ""
    command = result.get("command") or {}
    text = command_text(command)
    tail = (f"the project's install command: `{text}`" if text
            else "no install command is recorded for this project; record it at onboarding")
    return f"{_pairs(result)}; {tail}"


# --- the environment --------------------------------------------------------------------------------

def _env_dir_of(got):
    key = PE.env_key(got["env"], "VIRTUAL_ENV")
    return str(got["env"][key]) if key is not None and got["env"][key] else ""


def _environment(root, lock_root, profile, got, environ, timeout, os_name, probe_run, which):
    """`(env_dir, env, why)`: the project's environment folder and the environment variables to launch with, or
    `("", None, reason)` when the installed set cannot be read from the project's own environment. A launcher is asked in
    `lock_root`, the folder of the lock that is compared (a profile whose folder holds its own project is not read as the
    root's)."""
    source = got["source"]
    if source == "inherited":
        why = "no environment of the project was found"
        if got["rejected"]:
            why += " (" + ", ".join(f"{s}: {r}" for s, r in got["rejected"]) + ")"
        return "", None, why
    if source in ("active_venv", "package_manager", "dir"):
        env_dir = _env_dir_of(got)
        return (env_dir, got["env"], "") if env_dir else ("", None, "the environment folder is not known")
    commands = PE.test_commands(profile)
    argv, cwd = (commands[0][1], commands[0][2]) if commands else ([], ".")
    kind = PE.wrapped_kind(argv) if argv else "bare"
    if kind == "venv_python":
        target = PE.python_target(root, cwd, argv[0])
        env_dir = str(Path(os.path.normpath(str(target))).parent.parent)
        folder = PE.executable_folder(env_dir, os_name)
        if folder is None or not PE.inside(env_dir, root):
            return "", None, "the python the profile starts is not in an environment folder of the project"
        return env_dir, PE.overlay(environ, env_dir, folder), ""
    program = os.path.splitext(PE.base_name(argv[0]))[0] if argv else ""
    env_dir, reason = PE.manager_env(lock_root, program, environ, timeout=timeout, os_name=os_name, run=probe_run, which=which)
    folder = PE.executable_folder(env_dir, os_name) if env_dir else None
    if env_dir is None or folder is None:
        return "", None, (f"the environment lives behind the launcher `{program}`; not read ({reason or 'no python in it'})")
    return env_dir, PE.overlay(environ, env_dir, folder), ""


def _under(path, folder) -> bool:
    """`path` lies under `folder` BY ITS NAME. Not by realpath: a venv's `python` is a link to the interpreter it was made
    from, and that link resolved is outside the folder - the folder a launch finds it in is what says whose it is."""
    p, f = os.path.normcase(os.path.abspath(str(path))), os.path.normcase(os.path.abspath(str(folder)))
    return p.startswith(f.rstrip(os.sep) + os.sep)


def _read_installed(root, env_dir, env, run, timeout):
    """`(installed, why)`: the packages the interpreter INSIDE `env_dir` reports (`{}` when it proved there are none), or
    `(None, reason)`."""
    env = dict(env)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    argv = PE.launch_argv(["python", "-I", "-c", PAYLOAD], env)
    if not os.path.dirname(argv[0]) or not _under(argv[0], env_dir):
        return None, "no python inside the project's environment folder"
    try:
        code, raw = (run or node_ids.run_bounded)(argv, str(root), env, timeout)
    except node_ids.BoundedRunError as exc:
        return None, f"the project's python did not answer ({exc.kind}: {exc})"
    except Exception as exc:  # an injected or unexpected launcher: unknown, never a traceback
        return None, f"the project's python did not answer ({type(exc).__name__})"
    text = raw.decode("utf-8", errors="replace") if isinstance(raw, (bytes, bytearray)) else str(raw or "")
    if code != 0:
        return None, f"the project's python ended with exit {code} while listing its packages"
    installed = _installed(text.strip().splitlines()[-1] if text.strip() else "")
    return (installed, "") if installed is not None else (None, "the project's python gave no readable list of packages")


# --- the check --------------------------------------------------------------------------------------

def _answer(state, why, *, lock="", checked=0, parts=None, environment=None, command=None) -> dict:
    parts = parts or {}
    return {"state": state, "lock": lock, "checked": checked if not parts else parts.get("checked", checked),
            "differs": parts.get("differs", []), "absent": parts.get("absent", []),
            "conditional": parts.get("conditional", 0), "why": why,
            "environment": environment or {"source": "", "where": "", "rejected": []},
            "command": command or {"argv": [], "cwd": ".", "source": "none"}}


def _find_locks(root, profile, table):
    """The lock file(s) of the nearest folder (from the test commands' folders up to the root) that holds any: `[(path,
    form)]`, and that folder relative to the root."""
    by_name = {row["file"]: row for row in table["locks"]}
    for folder in PE.walk_dirs(root, profile):
        found = [(Path(folder) / name, by_name[name]["format"]) for name in by_name if (Path(folder) / name).is_file()]
        if found:
            rel = PE.rel_path(folder, root)
            return found, ("." if rel in ("", ".") else rel)
    return [], "."


def check(project_root, profile=None, *, environ=None, run=None, timeout=PAYLOAD_TIMEOUT_S, which=None, os_name=None,
          probe_run=None) -> dict:
    """The drift of the project's environment against its lock; see the module docstring for the shape and the rules.
    Never raises for a missing root, a missing lock, a broken file or a missing tool: the answer is `unknown` with the
    reason. `run` replaces `node_ids.run_bounded` (argv, cwd, env, timeout -> code, bytes) and `probe_run` replaces the
    `subprocess.run` of the manager probe - both for tests; `environ` defaults to a copy of `os.environ`."""
    os_name = os_name or os.name
    environ = dict(os.environ) if environ is None else dict(environ)
    profile = profile if isinstance(profile, dict) else {}
    table, problem = load_table()
    command = install_command(profile, ".", table or {"install_commands": {}})
    if not project_root or not os.path.isdir(str(project_root)):
        return _answer("unknown", "the project root is not a directory", command=command)
    root = os.path.abspath(str(project_root))
    if table is None:
        return _answer("unknown", problem, command=command)
    locks, lock_dir = _find_locks(root, profile, table)
    command = install_command(profile, lock_dir, table)
    if not locks:
        return _answer("unknown", "no lock file the factory reads", command=command)
    packages, unread, read = [], [], []
    for path, form in locks:                   # an unread lock never hides a readable one in its folder
        rows, problem = _read_lock(path, form)
        if rows is None:
            unread.append(problem)
        else:
            packages.append(rows)
            read.append(PE.rel_path(path, root))
    lock_names = ", ".join(read or [PE.rel_path(p, root) for p, _form in locks])
    got = PE.resolve(root, profile, environ, os_name=os_name, run=probe_run, which=which)
    environment = {"source": got["source"], "where": got["where"], "rejected": [list(r) for r in got["rejected"]]}
    here = dict(lock=lock_names, environment=environment, command=command)
    if not packages:
        return _answer("unknown", "; ".join(unread), **here)
    lock_root = os.path.normpath(os.path.join(root, lock_dir))
    env_dir, env, why = _environment(root, lock_root, profile, got, environ, PE.POETRY_TIMEOUT_S, os_name, probe_run, which)
    if env is None:
        return _answer("unknown", why, **here)
    installed, why = _read_installed(root, env_dir, env, run, timeout)
    if installed is None:
        return _answer("unknown", why, **here)
    parts = {"differs": [], "absent": [], "conditional": 0, "checked": 0}
    states = []
    for rows in packages:                      # two locks in one folder: both are read, the worst outcome stands
        one = _compare(rows, installed)
        for key in ("differs", "absent"):
            parts[key] += one[key]
        parts["conditional"] += one["conditional"]
        parts["checked"] += one["checked"]
        states.append("differs" if one["differs"] else "missing_only" if one["absent"] else "in_sync")
    state = min(states, key=_RANK.__getitem__)
    result = _answer(state, "", parts=parts, **here)
    note = _conditional(parts["conditional"])
    if state == "in_sync":
        base = f"all {parts['checked']} packages of the lock are installed at the locked version"
    else:
        base = _pairs(result)
    result["why"] = base + (f"; {note}" if note else "") + "".join(f"; {p}" for p in unread)
    return result


def _group_key(root, profile, table):
    """What makes two profiles ONE environment, read before any probe: the folder of the lock, the launcher (wrapper
    program, or the venv python as written) and the cwd of the first test command."""
    _locks, lock_dir = _find_locks(root, profile, table)
    commands = PE.test_commands(profile)
    argv, cwd = (commands[0][1], commands[0][2]) if commands else ([], ".")
    kind = PE.wrapped_kind(argv) if argv else "bare"
    launcher = {"wrapper": os.path.splitext(PE.base_name(argv[0]))[0] if argv else "",
                "venv_python": os.path.normcase(argv[0]) if argv else ""}.get(kind, "")
    return lock_dir, kind, launcher, os.path.normcase(os.path.normpath(cwd))


def check_profiles(project_root, profiles, **kwargs) -> list:
    """`[{"profiles": [ids], "result": check(...)}]`, worst first: ONE check per distinct environment (a key computed
    before any probe, so two profiles over one environment cost one probe), each naming the profiles it covers. No profile
    at all is one check of the project with an empty profile. `kwargs` go to `check`."""
    rows = [p for p in (profiles or []) if isinstance(p, dict)] or [{}]
    table, _problem = load_table()
    root = os.path.abspath(str(project_root)) if project_root and os.path.isdir(str(project_root)) else ""
    groups = {}
    for profile in rows:
        key = _group_key(root, profile, table) if root and table else ()
        groups.setdefault(key, []).append(profile)
    out = [{"profiles": [str(p["profile_id"]) for p in members if p.get("profile_id")],
            "result": check(project_root, members[0], **kwargs)} for members in groups.values()]
    return sorted(out, key=lambda entry: _RANK[entry["result"]["state"]])


def drift_text(entries, of=None) -> str:
    """The sentence of every group that differs or misses packages, joined; each is led by the profiles it covers when more
    than one profile was checked (`of`: all the groups of the check, when `entries` is a part of them). Empty when nothing
    drifted."""
    many = sum(len(e["profiles"]) for e in (of or entries)) > 1
    parts = []
    for entry in entries:
        sentence = drift_sentence(entry["result"])
        if sentence:
            parts.append(f"({', '.join(entry['profiles'])}) {sentence}" if many and entry["profiles"] else sentence)
    return " | ".join(parts)


# --- command line -----------------------------------------------------------------------------------

def main(argv=None, *, out=None, err=None) -> int:
    """`dependency_drift.py <project_root> [--profile <config.json>] [--json]`: print whether the project's environment
    matches its lock. Reads only; exit 0 whatever the answer, 2 with one stderr line for a root that is not a directory
    or a profile file that cannot be read."""
    out, err = out or sys.stdout, err or sys.stderr
    args, profile, code = PE.cli_input("dependency_drift", main.__doc__.split(":")[0], argv, err)
    if code is not None:
        return code
    result = check(args.project_root, profile)
    if args.json:
        print(json.dumps(result, indent=2), file=out)
        return 0
    print(f"state: {result['state']}\nlock: {result['lock'] or '-'}\nchecked: {result['checked']}\nwhy: {result['why']}", file=out)
    text = command_text(result["command"])
    if result["state"] in ("differs", "missing_only"):
        print(f"command: {text or 'none recorded'} ({result['command']['source']})", file=out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
