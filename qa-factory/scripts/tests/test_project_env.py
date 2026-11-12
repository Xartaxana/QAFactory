#!/usr/bin/env python3
"""project_env.py (C3-18 part 1): the environment of a project's tests is chosen by code, the
overlay reaches a subprocess only through `launch_argv`, and a source outside the project is
refused. Starts nothing but a tiny shim script; `poetry env info -p` is an injected `run`.

Folder layouts are pinned through the `os_name` argument of `resolve` ("nt" -> Scripts,
"posix" -> bin); the shim executables are the HOST's kind (`.cmd` on Windows, an executable
file elsewhere), because `shutil.which` and `Popen` are the host's."""
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import project_env

FAILS = 0
CHECKS = 0
TMP = []
NT = os.name == "nt"


def check(name, ok, detail=""):
    global FAILS, CHECKS
    print(("PASS " if ok else "FAIL ") + name + (f" — {detail}" if not ok else ""))
    CHECKS += 1
    FAILS += not ok


def tmp() -> Path:
    path = Path(os.path.realpath(tempfile.mkdtemp(prefix="project-env-")))
    TMP.append(path)
    return path


def shim(folder: Path, name="pytest", text="overlay-shim") -> Path:
    """An executable `name` in `folder` that prints `text` (the host's kind of launcher)."""
    folder.mkdir(parents=True, exist_ok=True)
    if NT:
        path = folder / (name + ".cmd")
        path.write_bytes(("@echo off\r\necho " + text + "\r\n").encode("ascii"))
    else:
        path = folder / name
        path.write_bytes(("#!/bin/sh\necho " + text + "\n").encode("ascii"))
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


def make_env(env_dir: Path, os_name=None, pytest=True) -> Path:
    """A fake virtual environment: `<env>/Scripts` (nt) or `<env>/bin` with a python and, by
    default, a pytest shim. Returns the executable folder."""
    os_name = os_name or os.name
    folder = env_dir / ("Scripts" if os_name == "nt" else "bin")
    folder.mkdir(parents=True, exist_ok=True)
    fake_python = folder / ("python.exe" if os_name == "nt" else "python")
    fake_python.write_bytes(b"")
    fake_python.chmod(fake_python.stat().st_mode | stat.S_IXUSR)
    if pytest:
        shim(folder)
    return folder


def profile(*commands, manager=None) -> dict:
    """A profile row: commands are (name, argv, kind[, cwd])."""
    out = {"commands": {}}
    for item in commands:
        name, argv, kind = item[:3]
        out["commands"][name] = {"argv": list(argv), "kind": kind, "cwd": item[3] if len(item) > 3 else "."}
    if manager:
        out["execution_prerequisites"] = {"package_manager": manager}
    return out


def pins(root: Path, *extra):
    """`environ` for a test: a PATH of an empty folder (nothing the test did not make)."""
    empty = root / "empty-path"
    empty.mkdir(exist_ok=True)
    env = {"PATH": str(empty)}
    env.update(dict(extra))
    return env


def first_path(env) -> str:
    return env["PATH"].split(os.pathsep)[0]


def no_poetry(cmd, path=None):
    return None


def poetry_at(exe="poetry-fake"):
    return lambda cmd, path=None: exe if cmd == "poetry" else None


class Run:
    """An injected `subprocess.run` for `poetry env info -p`."""

    def __init__(self, stdout="", returncode=0, raises=None):
        self.stdout, self.returncode, self.raises, self.calls = stdout, returncode, raises, []

    def __call__(self, cmd, **kwargs):
        self.calls.append((list(cmd), kwargs))
        if self.raises:
            raise self.raises
        return SimpleNamespace(returncode=self.returncode, stdout=self.stdout, stderr="")


def sources_one_each():
    # (i) the profile's wrapper
    root = tmp()
    bindir = root / "tools"
    shim(bindir, "poetry")
    environ = pins(root)
    environ["PATH"] = str(bindir) + os.pathsep + environ["PATH"]
    make_env(root / ".venv")
    prof = profile(("one_test", ["poetry", "run", "pytest", "<test-file>"], "test"),
                   ("lint", ["poetry", "run", "ruff", "check"], "lint"))
    got = project_env.resolve(root, prof, environ)
    check("wrapper: `poetry run` on the PATH wins over a .venv", got["source"] == "profile_wrapper", got)
    check("wrapper: where names the launcher, no path", got["where"] == "profile_wrapper:poetry", got["where"])
    check("wrapper: the env is an unchanged copy (a wrapper brings its own environment)",
          got["env"] == environ and got["env"] is not environ and "VIRTUAL_ENV" not in got["env"])
    check("wrapper: nothing rejected", got["rejected"] == [], got["rejected"])

    # a wrapper whose launcher is not on the PATH is refused and the walk goes on
    got = project_env.resolve(root, prof, pins(root))
    check("wrapper not on PATH: rejected `not found`, the walk continues to the dir",
          got["source"] == "dir" and ("profile_wrapper", "not found") in got["rejected"], got)

    # a venv python as argv[0]
    root = tmp()
    folder = make_env(root / ".venv", pytest=False)
    py = folder / ("python.exe" if NT else "python")
    prof = profile(("one_test", [str(py), "-m", "pytest"], "test"))
    got = project_env.resolve(root, prof, pins(root))
    check("venv python as argv[0]: profile_wrapper, relative where",
          got["source"] == "profile_wrapper" and got["where"] == ".venv/" + folder.name + "/" + py.name, got)
    other = tmp()
    foreign_py = make_env(other / ".venv", pytest=False) / ("python.exe" if NT else "python")
    got = project_env.resolve(root, profile(("one_test", [str(foreign_py), "-m", "pytest"], "test")), pins(root))
    check("venv python outside the project: rejected `foreign`, source is not the wrapper",
          ("profile_wrapper", "foreign") in got["rejected"] and got["source"] != "profile_wrapper", got)

    # cmp3gb shape: bare pytest for tests, `poetry run ruff` for lint -> the lint wrapper does not choose
    root = tmp()
    prof = profile(("one_test", ["pytest", "<test-file>"], "test"),
                   ("lint", ["poetry", "run", "ruff", "check"], "lint"), manager="poetry 2.4.1")
    got = project_env.resolve(root, prof, pins(root), which=no_poetry)
    check("cmp3gb shape: a lint-only wrapper is not the test environment",
          got["source"] == "inherited" and not any(s == "profile_wrapper" for s, _r in got["rejected"]), got)
    mixed = profile(("one_test", ["poetry", "run", "pytest"], "test"), ("suite", ["pytest", "-n", "4"], "test"))
    got = project_env.resolve(root, mixed, pins(root))
    check("mixed test commands: rejected `mixed commands`", ("profile_wrapper", "mixed commands") in got["rejected"], got)

    # (ii) the active venv of the project
    root = tmp()
    folder = make_env(root / ".venv")
    environ = pins(root, ("VIRTUAL_ENV", str(root / ".venv") + os.sep))
    got = project_env.resolve(root, {}, environ)
    check("active venv under the root (trailing slash): active_venv, relative where",
          got["source"] == "active_venv" and got["where"] == ".venv", got)
    check("active venv: its folder first on PATH, VIRTUAL_ENV set, original PATH kept",
          first_path(got["env"]) == str(folder) and got["env"]["PATH"].endswith(environ["PATH"])
          and got["env"]["VIRTUAL_ENV"] == str(root / ".venv"), got["env"])
    check("active venv: the dict passed in is untouched", environ["PATH"] == pins(root)["PATH"]
          and environ["VIRTUAL_ENV"].endswith(os.sep))
    if NT:
        loud = pins(root, ("VIRTUAL_ENV", str(root / ".venv").upper()))
        check("active venv: different case on Windows compares equal",
              project_env.resolve(root, {}, loud)["source"] == "active_venv")
    outside = tmp()
    make_env(outside / "venv")
    got = project_env.resolve(root, {}, pins(root, ("VIRTUAL_ENV", str(outside / "venv"))))
    check("foreign active venv: rejected `foreign`, not used",
          ("active_venv", "foreign") in got["rejected"] and got["source"] == "dir", got)
    got = project_env.resolve(root, {}, pins(root, ("VIRTUAL_ENV", str(root / "nothing-here"))))
    check("active venv with no executable folder: rejected `not found`",
          ("active_venv", "not found") in got["rejected"], got)

    # (iii) the package manager the profile names
    root = tmp()
    (root / "pyproject.toml").write_text('[tool.poetry]\nname = "Testproject1-SDK"\n', encoding="utf-8")
    store = tmp() / "pypoetry" / "virtualenvs"
    env_dir = store / "testproject1-sdk-AbCd1234-py3.12"
    folder = make_env(env_dir)
    prof = profile(("one_test", ["pytest"], "test"), manager="poetry 2.4.1")
    run = Run(stdout=str(env_dir) + "\n")
    got = project_env.resolve(root, prof, pins(root, ("VIRTUAL_ENV", str(tmp())), ("POETRY_ACTIVE", "1")),
                              run=run, which=poetry_at())
    check("poetry in the cache with the pyproject name: package_manager",
          got["source"] == "package_manager" and got["where"] == "package_manager:" + env_dir.name, got)
    check("poetry: where carries no absolute path", not os.path.isabs(got["where"]) and str(store) not in got["where"])
    check("poetry: overlay folder first, VIRTUAL_ENV the environment",
          first_path(got["env"]) == str(folder) and got["env"]["VIRTUAL_ENV"] == str(env_dir), got["env"])
    cmd, kwargs = run.calls[0]
    check("poetry probe: `env info -p`, cwd the project, timeout 20",
          cmd[1:] == ["env", "info", "-p"] and kwargs["cwd"] == str(root) and kwargs["timeout"] == 20, (cmd, kwargs))
    check("poetry probe: run WITHOUT VIRTUAL_ENV / POETRY_ACTIVE (a foreign activated venv is not the answer)",
          "VIRTUAL_ENV" not in kwargs["env"] and "POETRY_ACTIVE" not in kwargs["env"], kwargs["env"])

    # (iv) dirs
    root = tmp()
    folder = make_env(root / ".venv")
    got = project_env.resolve(root, {}, pins(root))
    check("dir: .venv at the root", got["source"] == "dir" and got["where"] == ".venv"
          and first_path(got["env"]) == str(folder), got)

    # (v) inherited
    root = tmp()
    environ = pins(root)
    got = project_env.resolve(root, {}, environ)
    check("inherited: nothing found, env equal to environ, where empty, nothing rejected",
          got["source"] == "inherited" and got["where"] == "" and got["env"] == environ
          and got["env"] is not environ and got["rejected"] == [], got)


def order_of_sources():
    root = tmp()
    (root / "pyproject.toml").write_text('[project]\nname = "demo"\n', encoding="utf-8")
    env_dir = tmp() / "virtualenvs" / "demo-12345678-py3.12"
    make_env(env_dir)
    make_env(root / ".venv")
    active = root / "venv"
    make_env(active)
    prof = profile(("one_test", ["pytest"], "test"), manager="poetry")
    run = Run(stdout=str(env_dir))
    environ = pins(root, ("VIRTUAL_ENV", str(active)))
    got = project_env.resolve(root, prof, environ, run=run, which=poetry_at())
    check("order: the active venv beats the package manager and the dirs",
          got["source"] == "active_venv" and not run.calls, got)
    got = project_env.resolve(root, prof, pins(root), run=run, which=poetry_at())
    check("order: the package manager beats the dirs", got["source"] == "package_manager", got)
    got = project_env.resolve(root, prof, pins(root), run=Run(returncode=1), which=poetry_at())
    check("order: a refused package manager falls through to the dir",
          got["source"] == "dir" and ("package_manager", "not found") in got["rejected"], got)
    shim(root / "w", "poetry")
    wrapped = profile(("one_test", ["poetry", "run", "pytest"], "test"), manager="poetry")
    env2 = pins(root, ("VIRTUAL_ENV", str(active)))
    env2["PATH"] = str(root / "w") + os.pathsep + env2["PATH"]
    got = project_env.resolve(root, wrapped, env2, run=run, which=None)
    check("order: the profile's wrapper beats the active venv", got["source"] == "profile_wrapper", got)
    both = project_env.resolve(root, {}, pins(root))
    check("order: `.venv` is preferred to `venv` in one folder", both["where"] == ".venv", both)


def poetry_refusals():
    root = tmp()
    (root / "pyproject.toml").write_text('[project]\nname = "demo"\n', encoding="utf-8")
    prof = profile(("one_test", ["pytest"], "test"), manager="poetry 2.4.1")
    store = tmp() / "pypoetry" / "virtualenvs"
    own = store / "demo-AbCd1234-py3.12"
    make_env(own)
    stranger = store / "another-AbCd1234-py3.12"
    make_env(stranger)
    elsewhere = tmp() / "somewhere" / "demo-AbCd1234-py3.12"
    make_env(elsewhere)

    def reasons(run, which=poetry_at(), environ=None):
        return project_env.resolve(root, prof, environ or pins(root), run=run, which=which)["rejected"]

    check("poetry missing: rejected `not installed`", reasons(Run(), which=no_poetry) == [("package_manager", "not installed")])
    check("poetry timeout: rejected `timeout`, never read as found",
          reasons(Run(raises=subprocess.TimeoutExpired("poetry", 20))) == [("package_manager", "timeout")])
    check("poetry vanished after the lookup: rejected `not installed`",
          reasons(Run(raises=FileNotFoundError())) == [("package_manager", "not installed")])
    check("poetry OSError: rejected `not found`, no traceback",
          reasons(Run(raises=PermissionError())) == [("package_manager", "not found")])
    check("poetry non-zero exit: rejected `not found`", reasons(Run(returncode=1, stdout=str(own))) == [("package_manager", "not found")])
    check("poetry empty output: rejected `not found`", reasons(Run(stdout="")) == [("package_manager", "not found")])
    check("poetry non-path output: rejected `not found`", reasons(Run(stdout="Creating virtualenv...")) == [("package_manager", "not found")])
    check("poetry missing dir: rejected `not found`", reasons(Run(stdout=str(store / "gone"))) == [("package_manager", "not found")])
    check("poetry env of another project's name: rejected `foreign`",
          reasons(Run(stdout=str(stranger))) == [("package_manager", "foreign")])
    check("poetry env outside the poetry store, outside the project: rejected `foreign`",
          reasons(Run(stdout=str(elsewhere))) == [("package_manager", "foreign")])
    got = project_env.resolve(root, prof, pins(root), run=Run(stdout="Creating virtualenv...\n" + str(own) + "\n"),
                              which=poetry_at())
    check("poetry printing two lines: the first that is an existing dir", got["source"] == "package_manager"
          and got["where"] == "package_manager:" + own.name, got)
    custom = tmp() / "my-envs"
    make_env(custom / "demo-ZZZZ9999-py3.12")
    got = project_env.resolve(root, prof, pins(root, ("POETRY_VIRTUALENVS_PATH", str(custom))),
                              run=Run(stdout=str(custom / "demo-ZZZZ9999-py3.12")), which=poetry_at())
    check("poetry with POETRY_VIRTUALENVS_PATH: that folder is the store", got["source"] == "package_manager", got)
    local = make_env(root / ".venv")
    got = project_env.resolve(root, prof, pins(root), run=Run(stdout=str(root / ".venv")), which=poetry_at())
    check("poetry env inside the project: accepted, relative where",
          got["source"] == "package_manager" and got["where"] == ".venv" and first_path(got["env"]) == str(local), got)
    nopy = tmp() / "virtualenvs" / "demo-AbCd1234-py3.12"
    nopy.mkdir(parents=True)
    got = project_env.resolve(root, prof, pins(root), run=Run(stdout=str(nopy)), which=poetry_at())
    check("poetry env with no executable folder: rejected `not found`",
          ("package_manager", "not found") in got["rejected"] and got["source"] == "dir", got)
    other = profile(("one_test", ["pytest"], "test"), manager="uv 0.5")
    run = Run(stdout=str(own))
    got = project_env.resolve(root, other, pins(root), run=run, which=poetry_at())
    check("a manager other than poetry is not probed (part 1)", not run.calls and got["source"] == "dir", got)


def public_helpers():
    """RH1-4 4.3a: `walk_dirs`, `wrapped_kind`, `manager_env` are public; the old private names are the same objects."""
    check("aliases: _walk_dirs / _wrapped_kind are the public functions",
          project_env._walk_dirs is project_env.walk_dirs and project_env._wrapped_kind is project_env.wrapped_kind)
    check("wrapped_kind folds the venv folder case on every OS (Bin / SCRIPTS)",
          project_env.wrapped_kind(["Proj/.venv/Bin/python", "-m", "pytest"]) == "venv_python"
          and project_env.wrapped_kind(["Proj\\.venv\\SCRIPTS\\python.exe", "-m", "pytest"]) == "venv_python"
          and project_env.wrapped_kind(["Proj/other/python"]) == "bare")
    check("wrapped_kind reads the wrappers table when none is given",
          project_env.wrapped_kind(["poetry", "run", "pytest"]) == "wrapper"
          and project_env.wrapped_kind(["pytest"]) == "bare"
          and project_env.wrapped_kind([".venv/Scripts/python", "-m", "pytest"]) == "venv_python"
          and project_env.wrapped_kind(["poetry", "run", "pytest"], {}) == "bare")
    root = tmp()
    (root / "sub" / "deep").mkdir(parents=True)
    prof = profile(("one_test", ["pytest"], "test", "sub/deep"))
    chain = [Path(p) for p in project_env.walk_dirs(root, prof)]
    check("walk_dirs: nearest first, up to and including the root",
          chain == [root / "sub" / "deep", root / "sub", root], chain)
    (root / "pyproject.toml").write_text('[project]\nname = "demo"\n', encoding="utf-8")
    store = tmp() / "pypoetry" / "virtualenvs"
    own, stranger = store / "demo-AbCd1234-py3.12", store / "another-AbCd1234-py3.12"
    make_env(own)
    make_env(stranger)

    def asks(program, run, which=poetry_at()):
        return project_env.manager_env(root, program, pins(root), timeout=5, run=run, which=which)

    check("manager_env poetry: the project's own environment -> (dir, '')", asks("poetry", Run(stdout=str(own))) == (str(own), ""))
    run = Run(stdout=str(own))
    asks("poetry", run)
    check("manager_env: only the read-only `env info -p` is started",
          [c[0][1:] for c in run.calls] == [["env", "info", "-p"]], run.calls)
    check("manager_env: another project's environment -> (None, 'foreign'), never the dir",
          asks("poetry", Run(stdout=str(stranger))) == (None, "foreign"))
    check("manager_env: a launcher with no read-only probe is never started (it would create or sync an environment)",
          [asks(p, run2)[0] for p, run2 in (("uv", Run(stdout=str(own))), ("npx", Run(stdout=str(own))))] == [None, None]
          and asks("uv", Run(stdout=str(own))) == (None, "no read-only probe"))
    uv_run = Run(stdout=str(own))
    asks("uv", uv_run)
    check("manager_env: nothing is run for such a program", not uv_run.calls)
    check("manager_env: poetry missing -> (None, 'not installed')", asks("poetry", Run(), which=no_poetry) == (None, "not installed"))
    check("manager_env: a program written as a path is read by its name",
          asks(os.path.join("tools", "poetry.exe"), Run(stdout=str(own))) == (str(own), ""))


def dir_walk():
    base = tmp()
    root = base / "proj"
    root.mkdir()
    make_env(base / ".venv")
    got = project_env.resolve(root, {}, pins(base))
    check("walk: a .venv ONE LEVEL ABOVE the project root is not taken", got["source"] == "inherited", got)
    up = profile(("one_test", ["pytest"], "test", ".."))
    got = project_env.resolve(root, up, pins(base))
    check("walk: a command cwd outside the project is ignored, the parent's .venv still not taken",
          got["source"] == "inherited", got)
    make_env(root / ".venv")
    check("walk: .venv AT the project root is taken", project_env.resolve(root, {}, pins(base))["where"] == ".venv")
    sub = root / "backend"
    sub.mkdir()
    deep = profile(("one_test", ["pytest"], "test", "backend"))
    got = project_env.resolve(root, deep, pins(base))
    check("walk: from the command cwd up to the root, the root's .venv is found", got["where"] == ".venv", got)
    make_env(sub / "venv")
    got = project_env.resolve(root, deep, pins(base))
    check("walk: the nearest environment wins (backend/venv over the root's .venv)", got["where"] == "backend/venv", got)
    # a folder with no python is not an environment (E3), and the other platform's layout is skipped
    lone = tmp()
    (lone / ".venv" / "Scripts").mkdir(parents=True)
    check("a .venv with no python in it is skipped",
          project_env.resolve(lone, {}, pins(lone), os_name="nt")["source"] == "inherited")
    for os_name, folder in (("nt", "Scripts"), ("posix", "bin")):
        root = tmp()
        got_folder = make_env(root / ".venv", os_name)
        got = project_env.resolve(root, {}, pins(root), os_name=os_name)
        check(f"{os_name}: the executable folder is {folder}",
              got["source"] == "dir" and got_folder.name == folder and first_path(got["env"]) == str(got_folder), got)
        other = "posix" if os_name == "nt" else "nt"
        check(f"{os_name} layout is not an environment when looking for {other}",
              project_env.resolve(root, {}, pins(root), os_name=other)["source"] == "inherited")


def degenerate_inputs():
    gone = tmp() / "does-not-exist"
    environ = pins(tmp())
    for label, value in (("missing", gone), ("None", None), ("empty", "")):
        got = project_env.resolve(value, {"commands": {}}, environ)
        check(f"project root {label}: inherited, rejected no project root, no raise",
              got["source"] == "inherited" and got["where"] == "" and got["rejected"] == [("dir", "no project root")]
              and got["env"] == environ, got)
    root = tmp()
    for label, value in (("None", None), ("empty dict", {}), ("a string", "poetry"), ("commands a list", {"commands": []}),
                         ("argv a string", {"commands": {"a": {"argv": "pytest", "kind": "test"}}}),
                         ("argv empty", {"commands": {"a": {"argv": [], "kind": "test"}}}),
                         ("spec not a dict", {"commands": {"a": 5}})):
        got = project_env.resolve(root, value, pins(root))
        check(f"profile {label}: inherited, no raise", got["source"] == "inherited" and got["rejected"] == [], got)
    make_env(root / ".venv")
    bare = {"PATH": ""}
    got = project_env.resolve(root, None, {})
    check("environ with no PATH at all: the overlay PATH is the executable folder alone",
          got["source"] == "dir" and got["env"]["PATH"] == str(root / ".venv" / ("Scripts" if NT else "bin")), got["env"])
    empty = tmp()
    check("environ with no PATH at all and nothing found: inherited, still no PATH key",
          project_env.resolve(empty, {}, {})["env"] == {})
    check("environ with an empty PATH: the folder alone, no trailing separator",
          not project_env.resolve(root, None, bare)["env"]["PATH"].endswith(os.pathsep))

    snapshot = dict(os.environ)
    got = project_env.resolve(root)
    check("environ=None copies os.environ and mutates nothing",
          dict(os.environ) == snapshot and got["env"] is not os.environ and "VIRTUAL_ENV" in got["env"])
    given = pins(root)
    before = dict(given)
    project_env.resolve(root, None, given)
    check("the environ passed in is never mutated", given == before)


def clone_root():
    original = tmp()
    clone = tmp()
    make_env(original / ".venv")
    (clone / "tests").mkdir()
    check("clone root pin: the clone has no .venv, so resolve(clone) is inherited",
          project_env.resolve(clone, {}, pins(clone))["source"] == "inherited")
    got = project_env.resolve(original, {}, pins(original))
    check("clone root pin: resolve(original root) finds the dir", got["source"] == "dir" and got["where"] == ".venv", got)


def launching():
    root = tmp()
    folder = make_env(root / ".venv")
    environ = pins(root)
    overlay = project_env.resolve(root, {}, environ)["env"]
    want = shutil.which("pytest", path=str(folder))
    argv = ["pytest", "tests/a.py", "-q"]
    got = project_env.launch_argv(argv, overlay)
    check("launch_argv found: argv[0] is the absolute path from the overlay PATH",
          os.path.isabs(got[0]) and os.path.normcase(got[0]) == os.path.normcase(want) and got[1:] == argv[1:], got)
    check("launch_argv does not mutate its argument", argv == ["pytest", "tests/a.py", "-q"])
    check("launch_argv not found: argv unchanged (readiness decides)",
          project_env.launch_argv(["nosuchtool-xyz", "x"], overlay) == ["nosuchtool-xyz", "x"])
    check("launch_argv with a folder in the head: unchanged", project_env.launch_argv(["./pytest", "x"], overlay) == ["./pytest", "x"])
    check("launch_argv empty argv: empty list", project_env.launch_argv([], overlay) == [])
    check("launch_argv with an env that has no PATH finds nothing (never the process's)",
          project_env.launch_argv(["pytest"], {}) == ["pytest"] and project_env.launch_argv(["python"], {}) == ["python"])
    check("launch_argv with env=None finds nothing", project_env.launch_argv(["pytest"], None) == ["pytest"])

    # NEGATIVE control: a pytest OUTSIDE the overlay folder is not found through the overlay PATH
    stray = tmp() / "stray"
    shim(stray, "pytest", "stray-shim")
    plain = {"PATH": str(root / "empty-path")}
    check("negative control: a pytest outside the overlay folder and its PATH is not found",
          project_env.launch_argv(["pytest"], plain) == ["pytest"])
    both = dict(overlay, PATH=overlay["PATH"] + os.pathsep + str(stray))
    check("negative control: with the stray folder LAST on PATH the overlay's pytest still wins",
          os.path.normcase(project_env.launch_argv(["pytest"], both)[0]) == os.path.normcase(want))
    put_first = dict(both, PATH=str(stray) + os.pathsep + both["PATH"])
    check("negative control: a stray pytest FIRST on PATH wins (the order is the PATH's)",
          os.path.normcase(project_env.launch_argv(["pytest"], put_first)[0]).startswith(os.path.normcase(str(stray))))

    # M13: a launch through Popen must carry an absolute argv[0] when the overlay is the only place it is
    seen = []

    def popen(cmd, *args, **kwargs):
        seen.append(list(cmd))
        if not os.path.isabs(str(cmd[0])):
            raise FileNotFoundError(2, "bare argv[0] looked up on the parent's PATH", cmd[0])
        return SimpleNamespace(returncode=0)

    with mock.patch.object(subprocess, "Popen", popen):
        try:
            subprocess.Popen(project_env.launch_argv(["pytest", "-q"], overlay), env=overlay)
            launched = True
        except FileNotFoundError:
            launched = False
    check("M13: Popen receives an absolute argv[0] resolved on the overlay PATH", launched and os.path.isabs(seen[0][0]), seen)
    if NT:
        # the t-848 probe: an .exe that exists ONLY in the overlay folder; Popen of the bare name
        # looks on the parent's PATH, Popen of the which-resolved path finds it
        probe = folder / "zzprobe-project-env.exe"
        shutil.copyfile(sys.executable, probe)
        bare_fails = resolved_ok = False
        try:
            subprocess.Popen(["zzprobe-project-env", "-c", "pass"], env=overlay, stdout=subprocess.DEVNULL)
        except FileNotFoundError:
            bare_fails = True
        try:
            proc = subprocess.Popen(project_env.launch_argv(["zzprobe-project-env", "-c", "pass"], overlay),
                                    env=overlay, stdout=subprocess.DEVNULL)
            proc.wait(timeout=30)
            resolved_ok = True
        except FileNotFoundError:
            pass
        check("windows: a bare argv[0] with env=overlay is NOT found, the launch_argv result is",
              bare_fails and resolved_ok, (bare_fails, resolved_ok))
    done = subprocess.run(project_env.launch_argv(["pytest"], overlay), capture_output=True, text=True)
    check("a real launch through launch_argv runs the overlay's executable",
          done.returncode == 0 and "overlay-shim" in done.stdout, (done.returncode, done.stdout, done.stderr))


def command_line():
    script = str(Path(__file__).resolve().parents[1] / "project_env.py")
    root = tmp()
    folder = make_env(root / ".venv")
    empty = root / "empty-path"
    empty.mkdir(exist_ok=True)
    env = {k: v for k, v in os.environ.items() if k.upper() not in ("VIRTUAL_ENV", "POETRY_ACTIVE")}
    env.update(PATH=str(empty), PYTHONIOENCODING="utf-8")

    def cli(*args):
        return subprocess.run([sys.executable, "-B", script, *args], capture_output=True, text=True,
                              encoding="utf-8", env=env)

    done = cli(str(root))
    lines = done.stdout.splitlines()
    check("cli: exit 0, the source / where / python lines", done.returncode == 0 and lines[:2] == [
        "source: dir", "where: .venv"] and lines[2].startswith("python: "), (done.returncode, done.stdout, done.stderr))
    check("cli: python is the one on the overlay PATH", os.path.normcase(lines[2][len("python: "):]).startswith(
        os.path.normcase(str(folder))), lines[2])
    check("cli: writes nothing to stderr, nothing into the project",
          done.stderr == "" and sorted(p.name for p in root.iterdir()) == [".venv", "empty-path"], done.stderr)

    as_json = json.loads(cli(str(root), "--json").stdout)
    check("cli --json: source, where, python, rejected; env cut to PATH and VIRTUAL_ENV",
          as_json["source"] == "dir" and as_json["where"] == ".venv" and as_json["rejected"] == []
          and as_json["python"].startswith(str(folder)) and set(as_json["env"]) <= {"PATH", "VIRTUAL_ENV"}
          and "PYTHONIOENCODING" not in as_json["env"], as_json)

    bare = tmp()
    done = cli(str(bare))
    check("cli: nothing found prints inherited, python `inherited` when no python is on PATH",
          done.stdout.splitlines()[:3] == ["source: inherited", "where: ", "python: inherited"], done.stdout)

    config = bare / "config.json"
    config.write_text(json.dumps({"profiles": [
        {"profile_id": "x", "selected": False, "commands": {"one_test": {"argv": ["pytest"], "kind": "test"}}},
        {"profile_id": "api", "selected": True,
         "commands": {"one_test": {"argv": ["poetry", "run", "pytest"], "kind": "test"}}}]}), encoding="utf-8")
    done = cli(str(bare), "--profile", str(config))
    check("cli --profile: the selected profile is read; a refused wrapper prints a rejected line",
          done.returncode == 0 and "rejected: profile_wrapper — not found" in done.stdout.splitlines(), done.stdout)

    missing = str(bare / "no-such-root")
    done = cli(missing)
    check("cli: a root that does not exist -> exit 2, ONE stderr line, no traceback, no stdout",
          done.returncode == 2 and len(done.stderr.splitlines()) == 1 and "Traceback" not in done.stderr
          and done.stdout == "", (done.returncode, done.stderr))
    done = cli(str(bare), "--profile", str(bare / "no-config.json"))
    check("cli: an unreadable --profile file -> exit 2, one stderr line",
          done.returncode == 2 and len(done.stderr.splitlines()) == 1 and "Traceback" not in done.stderr, done.stderr)
    (bare / "broken.json").write_text("{not json", encoding="utf-8")
    done = cli(str(bare), "--profile", str(bare / "broken.json"))
    check("cli: a broken --profile file -> exit 2, one stderr line",
          done.returncode == 2 and len(done.stderr.splitlines()) == 1 and "Traceback" not in done.stderr, done.stderr)
    check("cli: no argument -> argparse usage, exit 2", cli().returncode == 2)


def cmd_wrapper_safety():
    """EP1-35: `cmd_unsafe` / `CmdUnsafe` / `checked_launch`. The battery is the spec's, verbatim (error direction: a refusal too many
    is safe, a silent corruption by cmd.exe is not)."""
    must_refuse = ["a&b", "a|b", "a<b", "a>b", "a^b", "%PATH%", "a\nb", 'x" & echo inj>f & "', "x&echo inj>f"]
    must_pass = ["plain", "tests/a.spec.ts:12", "with space", "(paren)", "a;b", "a,b", "a=b", "--grep=x y", "", "trailing\\", "*", "?", "a'b"]
    for token in must_refuse:
        check(f"cmd_unsafe refuses {token!r} behind npx.cmd", project_env.cmd_unsafe(["C:\\n\\npx.cmd", token], "nt") == [token])
    for token in must_pass:
        check(f"cmd_unsafe lets {token!r} through behind npx.cmd", project_env.cmd_unsafe(["C:\\n\\npx.cmd", token], "nt") == [])
    check("cmd_unsafe: a .EXE head with a&b is not a wrapper", project_env.cmd_unsafe(["C:\\n\\X.EXE", "a&b"], "nt") == [])
    check("cmd_unsafe: the head NPX.CMD (any case) is a wrapper", project_env.cmd_unsafe(["NPX.CMD", "a&b"], "nt") == ["a&b"])
    check("cmd_unsafe: a .bat head is a wrapper", project_env.cmd_unsafe(["x.bat", "a%b"], "nt") == ["a%b"])
    check("cmd_unsafe: os_name posix -> []", project_env.cmd_unsafe(["npx.cmd", "a&b"], "posix") == [])
    check("cmd_unsafe: empty and None argv -> []", project_env.cmd_unsafe([], "nt") == [] and project_env.cmd_unsafe(None, "nt") == [])
    check("cmd_unsafe: the head itself is never a token", project_env.cmd_unsafe(["a&b.cmd"], "nt") == [])
    check("CmdUnsafe is an OSError (every launch site already catches it)", issubclass(project_env.CmdUnsafe, OSError))
    text = str(project_env.CmdUnsafe("a%b", "npx.cmd"))
    check("CmdUnsafe text: token, head, 'nothing was launched', the door",
          all(part in text for part in ("'a%b'", "npx.cmd", "nothing was launched", "start the runner directly")), text)
    with mock.patch.object(project_env, "launch_argv", return_value=["C:\\n\\npx.cmd", "a&b"]), \
            mock.patch.object(project_env.os, "name", "nt"):
        try:
            project_env.checked_launch(["npx", "a&b"], {})
            raised = False
        except project_env.CmdUnsafe:
            raised = True
    check("checked_launch raises CmdUnsafe for a resolved .cmd head with an unsafe token", raised)
    with mock.patch.object(project_env, "launch_argv", return_value=["C:\\n\\npx.cmd", "ok"]), mock.patch.object(project_env.os, "name", "nt"):
        check("checked_launch returns launch_argv's result when it is safe", project_env.checked_launch(["npx", "ok"], {}) == ["C:\\n\\npx.cmd", "ok"])
    check("launch_argv itself is unchanged: it never refuses", project_env.launch_argv(["zz-none", "a&b"], {"PATH": ""}) == ["zz-none", "a&b"])


def main():
    try:
        cmd_wrapper_safety()
        command_line()
        sources_one_each()
        order_of_sources()
        poetry_refusals()
        public_helpers()
        dir_walk()
        degenerate_inputs()
        clone_root()
        launching()
    finally:
        for path in TMP:
            shutil.rmtree(path, ignore_errors=True)
    print(f"=== test_project_env: {CHECKS - FAILS}/{CHECKS} ok ===")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
