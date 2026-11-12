#!/usr/bin/env python3
"""dependency_drift.py (RH1-4): the environment of the PROJECT against the project's lock.

Nothing real is installed or started: the project's environment is a fake folder (a python file that is
never executed), the installed set is the answer of an injected `run`, and `poetry env info -p` is an
injected `probe_run`. What is pinned is the DECISION: which environment is read, what is compared, what the
answer says, and that the direction of every doubt is `unknown`, never `in_sync`, never the factory's own
environment, never a write. The keys K-4.3-*, K-4.1-* are named in the labels."""
import io
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import dependency_drift as DD
import project_env

FAILS = 0
CHECKS = 0
TMP = []
NT = os.name == "nt"


def check(name, ok, detail=""):
    global FAILS, CHECKS
    print(("PASS " if ok else "FAIL ") + name + (f" - {detail}" if not ok else ""))
    CHECKS += 1
    FAILS += not ok


def tmp() -> Path:
    path = Path(os.path.realpath(tempfile.mkdtemp(prefix="dep-drift-")))
    TMP.append(path)
    return path


def make_env(env_dir: Path, python=True) -> Path:
    """A fake virtual environment: `<env>/Scripts` (nt) or `<env>/bin` with a python that is never executed."""
    folder = env_dir / ("Scripts" if NT else "bin")
    folder.mkdir(parents=True, exist_ok=True)
    if python:
        fake = folder / ("python.exe" if NT else "python")
        fake.write_bytes(b"")
        fake.chmod(fake.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return folder


UV_LOCK = """version = 1
requires-python = ">=3.12"

[[package]]
name = "anyio"
version = "4.0"
source = { registry = "https://pypi.org/simple" }

[[package]]
name = "colorama"
version = "0.4.6"
source = { registry = "https://pypi.org/simple" }

[[package]]
name = "pydantic"
version = "2.0"
source = { registry = "https://pypi.org/simple" }
dependencies = [
    { name = "anyio" },
    { name = "colorama", marker = "sys_platform == 'win32'" },
]
"""


def lock_text(*packages) -> str:
    """packages: (name, version[, extra toml line])."""
    out = ""
    for item in packages:
        out += f'[[package]]\nname = "{item[0]}"\nversion = "{item[1]}"\n' + (item[2] + "\n" if len(item) > 2 else "") + "\n"
    return out


def profile(argv=("pytest",), manager="poetry 2.4.1", cwd=".", install=None) -> dict:
    out = {"commands": {"one_test": {"argv": list(argv), "kind": "test", "cwd": cwd}},
           "execution_prerequisites": {"package_manager": manager}}
    if install is not None:
        out["commands"]["install"] = install
    return out


def environ_of(root: Path, *extra) -> dict:
    empty = root / "empty-path"
    empty.mkdir(exist_ok=True)
    env = {"PATH": str(empty)}
    env.update(dict(extra))
    return env


class Run:
    """An injected `node_ids.run_bounded`: answers with the packages it is given and records every launch."""

    def __init__(self, installed=None, code=0, raw=None, raises=None):
        self.installed, self.code, self.raw, self.raises, self.calls = installed, code, raw, raises, []

    def __call__(self, argv, cwd, env, timeout_s, grace_s=10):
        self.calls.append({"argv": list(argv), "cwd": str(cwd), "env": dict(env), "timeout": timeout_s})
        if self.raises:
            raise self.raises
        if self.raw is not None:
            return self.code, self.raw
        return self.code, json.dumps([list(p) for p in self.installed or []]).encode("utf-8")


class Probe:
    """An injected `subprocess.run` for the manager's read-only probe."""

    def __init__(self, stdout="", returncode=0):
        self.stdout, self.returncode, self.calls = stdout, returncode, []

    def __call__(self, cmd, **kwargs):
        self.calls.append(list(cmd))
        return SimpleNamespace(returncode=self.returncode, stdout=self.stdout, stderr="")


def poetry_at(cmd, path=None):
    return "poetry-fake" if cmd == "poetry" else None


def project(lock=None, name="poetry.lock", venv=True):
    root = tmp()
    if lock is not None:
        (root / name).write_text(lock, encoding="utf-8")
    if venv:
        make_env(root / ".venv")
    return root


def drift(root, prof=None, installed=(), **kw):
    run = kw.pop("run", None) or Run(installed)
    got = DD.check(root, prof if prof is not None else profile(), environ=kw.pop("environ", None) or environ_of(root),
                   run=run, which=kw.pop("which", poetry_at), **kw)
    return got, run


# --- the table (4.1) --------------------------------------------------------------------------------

def table():
    got, problem = DD.load_table()
    check("K-4.1-table: the shipped table reads", got is not None and not problem, problem)
    check("K-4.1-table: locks name poetry.lock / uv.lock / pdm.lock with a managers each",
          sorted(r["file"] for r in got["locks"]) == ["pdm.lock", "poetry.lock", "uv.lock"]
          and all(r["manager"] for r in got["locks"]))
    check("K-4.1-table: only the poetry lock has a format the code reads (B1); uv and pdm are named so they are found, not read",
          {r["file"]: r["format"] for r in got["locks"]} == {"poetry.lock": "toml_packages", "uv.lock": "uv_lock", "pdm.lock": "pdm_lock"}, got["locks"])
    check("K-4.1-table: install_commands has poetry -> poetry install", got["install_commands"].get("poetry") == ["poetry", "install"])
    check("K-4.1-table (m1): uv installs from the lock and never re-locks: uv sync --locked",
          got["install_commands"].get("uv") == ["uv", "sync", "--locked"], got["install_commands"])
    root = tmp()
    broken = root / "t.json"
    for label, text in (("not JSON", "{no"), ("a list", "[]"), ("no locks", '{"install_commands": {}}'),
                        ("a lock path with a folder", '{"locks": [{"file": "a/b.lock", "format": "x", "manager": "m"}], "install_commands": {}}'),
                        ("an empty argv", '{"locks": [], "install_commands": {"m": []}}')):
        broken.write_text(text, encoding="utf-8")
        got, problem = DD.load_table(broken)
        check(f"K-4.1-table: {label} -> (None, problem), no traceback", got is None and problem, (got, problem))
    check("K-4.1-table: a missing file -> (None, problem)", DD.load_table(root / "absent.json")[0] is None)
    saved = DD.TABLE_PATH
    try:
        DD.TABLE_PATH = broken
        broken.write_text("{no", encoding="utf-8")
        base = project(lock_text(("a", "1")))
        got, _run = drift(base, installed=[("a", "1")])
        check("K-4.1-table: an unreadable table -> unknown with the reason, never in_sync",
              got["state"] == "unknown" and "lock table" in got["why"], got)
        check("K-4.1-table: ...and no command from it", DD.install_command(profile())["source"] == "none")
    finally:
        DD.TABLE_PATH = saved


# --- the comparison (4.3) ---------------------------------------------------------------------------

def comparison():
    root = project(lock_text(("testproject1-sdk-python", "0.1.704"), ("requests", "2.0.0")))
    got, run = drift(root, installed=[("testproject1-sdk-python", "0.1.700"), ("requests", "2.0.0"), ("extra-one", "9")])
    check("K-4.3-older: lock newer than installed -> differs, direction older, the pair named",
          got["state"] == "differs" and got["differs"] == [{"name": "testproject1-sdk-python", "installed": "0.1.700",
                                                            "locked": "0.1.704", "direction": "older"}], got)
    check("K-4.3-older: the project's install command comes from the table",
          got["command"]["argv"] == ["poetry", "install"] and got["command"]["source"] == "table" and got["command"]["cwd"] == ".", got["command"])
    check("K-4.3-older: the sentence names both versions and the command",
          DD.drift_sentence(got) == "installed testproject1-sdk-python 0.1.700, the lock says 0.1.704; the project's install command: `poetry install`",
          DD.drift_sentence(got))
    check("K-4.3-older: an installed package the lock does not name is ignored", got["checked"] == 2 and not got["absent"], got)
    check("K-4.3-older: lock and environment are reported", got["lock"] == "poetry.lock" and got["environment"]["source"] == "dir"
          and got["environment"]["where"] == ".venv", got)
    inside = Path(run.calls[0]["argv"][0])
    check("K-4.3-older: the interpreter read is the one INSIDE the project's .venv, started with -I and the fixed payload",
          DD._under(inside, root / ".venv") and run.calls[0]["argv"][1:3] == ["-I", "-c"] and run.calls[0]["argv"][3] == DD.PAYLOAD
          and run.calls[0]["cwd"] == str(root), run.calls)
    check("K-4.3-older: a PATH overlay with the project's environment first, bytecode writing off",
          run.calls[0]["env"]["PYTHONDONTWRITEBYTECODE"] == "1" and run.calls[0]["env"]["PATH"].split(os.pathsep)[0] == str(inside.parent))

    got, _ = drift(root, installed=[("testproject1-sdk-python", "0.2.0"), ("requests", "2.0.0")])
    check("K-4.3-newer: installed newer than the lock -> differs, direction newer",
          got["state"] == "differs" and got["differs"][0]["direction"] == "newer", got)

    got, _ = drift(root, installed=[("testproject1-sdk-python", "0.1.704"), ("requests", "2.0.0")])
    check("K-4.3-equal: every version equal -> in_sync with checked", got["state"] == "in_sync" and got["checked"] == 2
          and not got["differs"] and not got["absent"] and DD.drift_sentence(got) == "", got)

    got, _ = drift(root, installed=[("testproject1-sdk-python", "0.1.704")])
    check("K-4.3-absent: an unconditional package of the lock that is not installed -> missing_only (never in_sync)",
          got["state"] == "missing_only" and got["absent"] == [{"name": "requests", "locked": "2.0.0"}] and not got["differs"], got)
    check("K-4.3-absent: the sentence says it is not installed and gives the command",
          DD.drift_sentence(got) == "requests is not installed, the lock says 2.0.0; the project's install command: `poetry install`",
          DD.drift_sentence(got))
    got, _ = drift(root, installed=[("testproject1-sdk-python", "0.1.700")])
    check("K-4.3-absent: a difference and an absent package together -> differs (the worse), both listed",
          got["state"] == "differs" and len(got["differs"]) == 1 and len(got["absent"]) == 1, got)

    mk = project(lock_text(("colorama", "0.4.6", 'markers = "sys_platform == \\"win32\\""'), ("old-extra", "1.0", "optional = true"),
                           ("plain", "1.0", "optional = false")))
    got, _ = drift(mk, installed=[("plain", "1.0")])
    check("K-4.3-markers: packages with markers / optional = true that are not installed are counted, not absent",
          got["state"] == "in_sync" and got["conditional"] == 2 and not got["absent"] and got["checked"] == 1, got)
    check("K-4.3-markers: the sentence says how many were not checked", "2 conditional packages were not checked" in got["why"], got["why"])
    got, _ = drift(mk, installed=[("plain", "1.0"), ("colorama", "0.4.5")])
    check("K-4.3-markers: a conditional package that IS installed is compared", got["state"] == "differs"
          and got["differs"][0]["name"] == "colorama" and got["conditional"] == 1, got)
    one = project(lock_text(("opt", "1.0", "optional = true")))
    got, _ = drift(one, installed=[("other", "1")])
    check("K-4.3-markers: one conditional package -> singular", got["conditional"] == 1 and "1 conditional package was not checked" in got["why"], got["why"])

    sp = project(lock_text(("testproject1-sdk", "1.0"), ("testproject1-sdk-extra", "2.0")))
    got, _ = drift(sp, installed=[("Testproject1_SDK", "1.0"), ("testproject1.sdk.extra", "2.0")])
    check("K-4.3-names: Testproject1_SDK is testproject1-sdk (PEP 503), dots and underscores alike", got["state"] == "in_sync", got)
    got, _ = drift(sp, installed=[("Testproject1_SDK", "1.0")])
    check("K-4.3-names: testproject1-sdk-extra is a different package from testproject1-sdk", got["state"] == "missing_only"
          and got["absent"][0]["name"] == "testproject1-sdk-extra", got)

    sl = project(lock_text(("a", "1.0"), ("b", "2"), ("c", "1.2.3"), ("d", "1.0.0rc1"), ("e", "1.0")))
    got, _ = drift(sl, installed=[("a", "1.0.0"), ("b", "2.0"), ("c", "1.2.10"), ("d", "1.0.0"), ("e", "1.0")])
    by = {d["name"]: d["direction"] for d in got["differs"]}
    check("K-4.3-spell: 1.0 against 1.0.0 -> differs with NO direction (the spellings are one number)", by["a"] == "" and by["b"] == "", by)
    check("K-4.3-spell: an unproven order is never named (pre-release against a plain version)", by["d"] == "", by)
    check("K-4.3-spell: a real numeric order still is (1.2.10 is newer than 1.2.3)", by["c"] == "newer", by)
    check("K-4.3-spell: ...and an equal pair is not listed", "e" not in by, by)

    for count in (5, 6, 7):
        names = [f"p{n}" for n in range(count)]
        many = project(lock_text(*[(n, "2") for n in names]))
        got, _ = drift(many, installed=[(n, "1") for n in names])
        sentence = DD.drift_sentence(got)
        shown = sentence.split("; the project's install command")[0]
        check(f"K-4.3-5/6: {count} pairs -> the result holds all, the sentence names at most {DD.DRIFT_SHOWN}",
              len(got["differs"]) == count and shown.count("installed p") == min(count, DD.DRIFT_SHOWN), sentence)
        check(f"K-4.3-5/6: {count} pairs -> " + ("no pointer" if count == 5 else f"(+{count - 5} more)"),
              ("more)" not in sentence) if count == 5 else (f"(+{count - 5} more)" in shown), sentence)

    two = project(lock_text(("a", "1")))
    (two / "uv.lock").write_text(lock_text(("a", "2"), ("b", "1")), encoding="utf-8")
    got, _ = drift(two, installed=[("a", "1")])
    check("K-4.3-mixed-folder: poetry.lock is read and uv.lock is not; the poetry answer stands (the unread lock hides nothing)",
          got["state"] == "in_sync" and got["lock"] == "poetry.lock" and not got["differs"] and not got["absent"], got)
    check("K-4.3-mixed-folder: ...and the unread lock is named in the why", "uv.lock: this lock format is not read yet" in got["why"], got["why"])
    two2 = project(lock_text(("a", "2")))
    (two2 / "uv.lock").write_text(lock_text(("a", "1")), encoding="utf-8")
    got, _ = drift(two2, installed=[("a", "1")])
    check("K-4.3-mixed-folder: a correct poetry `differs` is not outvoted by a uv.lock that would say in_sync",
          got["state"] == "differs" and got["differs"][0]["locked"] == "2", got)

    uv_only = project(UV_LOCK, name="uv.lock")
    got, run = drift(uv_only, profile(manager="uv 0.5"), installed=[("pydantic", "2.0"), ("anyio", "4.0")])
    check("K-4.3-uv-edge-marker: the stand's uv.lock shape (colorama only on a win32 link, not installed) is NEVER missing_only",
          got["state"] == "unknown" and not got["absent"] and not got["differs"], got)
    check("K-4.3-uv-edge-marker: ...it is unknown, and the why names the format", "uv.lock: this lock format is not read yet" in got["why"]
          and not run.calls, got)
    check("K-4.3-uv-edge-marker: ...the install command is still the table's `uv sync --locked`",
          got["command"]["argv"] == ["uv", "sync", "--locked"], got["command"])
    pdm_only = project('[[package]]\nname = "cryptography"\nversion = "1"\nmarker = "sys_platform == \'linux\'"\n', name="pdm.lock")
    got, _ = drift(pdm_only, profile(manager="pdm 2"), installed=[("other", "1")])
    check("K-4.3-pdm: a pdm.lock row with a `marker` key is never read as unconditional -> unknown, not missing_only",
          got["state"] == "unknown" and not got["absent"] and "pdm.lock: this lock format is not read yet" in got["why"], got)

    fork = project(lock_text(("beartype", "0.22.9"), ("beartype", "0.23.0rc2"), ("other", "1")))
    for have, state in (("0.22.9", "in_sync"), ("0.23.0rc2", "in_sync"), ("0.20", "differs")):
        got, _ = drift(fork, installed=[("beartype", have), ("other", "1")])
        check(f"K-4.3-fork: one name at two locked versions, installed {have} -> {state} (differs only when NONE matches)",
              got["state"] == state and got["checked"] == 2, got)
    cond = project(lock_text(("pywin", "1", 'markers = "sys_platform == \\"win32\\""'), ("pywin", "2")))
    got, _ = drift(cond, installed=[("x", "1")])
    check("K-4.3-fork: a name with one conditional and one plain row is absent when not installed (the plain row decides)",
          got["state"] == "missing_only" and got["absent"][0]["name"] == "pywin", got)
    empty = project(lock_text())
    got, _ = drift(empty, installed=[("anything", "1")])
    check("K-4.3-empty: a lock with no packages -> in_sync, checked 0", got["state"] == "in_sync" and got["checked"] == 0, got)
    nopkg = project("# only a comment\n")
    got, _ = drift(nopkg, installed=[("x", "1")])
    check("K-4.3-empty: a lock with no `package` key at all -> in_sync, checked 0", got["state"] == "in_sync" and got["checked"] == 0, got)


# --- unknown, in every direction of doubt -----------------------------------------------------------

def doubts():
    root = project(None)
    got, run = drift(root, installed=[("a", "1")])
    check("K-4.3-nolock: no lock file -> unknown 'no lock file the factory reads', never in_sync",
          got["state"] == "unknown" and got["why"] == "no lock file the factory reads" and got["lock"] == "" and not run.calls, got)
    node = tmp()
    (node / "package-lock.json").write_text("{}", encoding="utf-8")
    (node / "package.json").write_text("{}", encoding="utf-8")
    got, run = drift(node, profile(("npx", "playwright", "test"), manager="npm 10"), installed=[("a", "1")])
    check("K-4.3-node: a project that is not Python -> unknown, nothing started", got["state"] == "unknown" and not run.calls, got)
    check("K-4.3-node: ...and no command either (npm has no row)", got["command"]["source"] == "none" and got["command"]["argv"] == [], got["command"])

    inh = project(lock_text(("a", "2")), venv=False)
    got, run = drift(inh, installed=[("a", "1")])
    check("K-4.3-inherited: no environment of the project -> unknown, the interpreter of the factory is NOT read (M4)",
          got["state"] == "unknown" and not run.calls and got["environment"]["source"] == "inherited", got)
    check("K-4.3-inherited: ...the reasons that were tried are in the answer", "no environment of the project" in got["why"], got["why"])
    foreign = tmp() / "factory-venv"
    make_env(foreign)
    got, run = drift(inh, installed=[("a", "1")], environ=environ_of(inh, ("VIRTUAL_ENV", str(foreign))))
    check("K-4.3-inherited: a VIRTUAL_ENV of the factory outside the project is refused, never read",
          got["state"] == "unknown" and not run.calls and ["active_venv", "foreign"] in got["environment"]["rejected"], got)

    nopy = project(lock_text(("a", "2")), venv=False)
    make_env(nopy / ".venv", python=False)
    got, run = drift(nopy, installed=[("a", "1")])
    check("a .venv with no python is not an environment -> unknown", got["state"] == "unknown" and not run.calls, got)

    wr = project(lock_text(("a", "2")), venv=False)
    for argv in (["npx", "playwright", "test"], ["xvfb-run", "pytest"]):
        got, run = drift(wr, profile(argv), installed=[("a", "1")])
        check(f"K-4.3-wrapper-unknown: {argv[0]} -> unknown, never started", got["state"] == "unknown" and not run.calls, got)

    bad = project("[[package]\nname = ", name="poetry.lock")
    got, run = drift(bad, installed=[("a", "1")])
    check("K-4.3-bad: a lock that is not TOML -> unknown with the file named", got["state"] == "unknown" and "poetry.lock" in got["why"]
          and not run.calls, got)
    noname = project('[[package]]\nversion = "1"\n')
    got, _ = drift(noname, installed=[("a", "1")])
    check("K-4.3-bad: a package with no name -> unknown", got["state"] == "unknown", got)
    listless = project("package = 3\n")
    got, _ = drift(listless, installed=[("a", "1")])
    check("K-4.3-bad: `package` that is not a list -> unknown", got["state"] == "unknown", got)
    good = project(lock_text(("a", "1")))
    import builtins
    real_import = builtins.__import__

    def no_tomllib(name, *args, **kwargs):
        if name == "tomllib":
            raise ImportError("no tomllib")
        return real_import(name, *args, **kwargs)

    builtins.__import__ = no_tomllib
    try:
        got, run = drift(good, installed=[("a", "1")])
    finally:
        builtins.__import__ = real_import
    check("K-4.3-bad: no tomllib (python < 3.11) -> unknown, never in_sync", got["state"] == "unknown" and "tomllib" in got["why"] and not run.calls, got)
    fmt = tmp()
    (fmt / "poetry.lock").write_text(lock_text(("a", "1")), encoding="utf-8")
    make_env(fmt / ".venv")
    saved = DD.TABLE_PATH
    try:
        alt = fmt / "alt.json"
        alt.write_text(json.dumps({"locks": [{"file": "poetry.lock", "format": "yaml_nobody_reads", "manager": "poetry"}],
                                   "install_commands": {}}), encoding="utf-8")
        DD.TABLE_PATH = alt
        got, _ = drift(fmt, installed=[("a", "1")])
    finally:
        DD.TABLE_PATH = saved
    check("K-4.3-bad: a lock format the code does not read -> unknown", got["state"] == "unknown" and "this lock format is not read yet" in got["why"], got)

    for label, run in (("timeout", Run(raises=DD.node_ids.BoundedRunError("timeout", "timed out after 60s"))),
                       ("not started", Run(raises=DD.node_ids.BoundedRunError("not_started", "no such file"))),
                       ("exit 1", Run(code=1, raw=b"Traceback")),
                       ("empty answer", Run(raw=b"")),
                       ("not JSON", Run(raw=b"hello")),
                       ("a list with only blank names", Run(raw=b'[["", ""]]')),
                       ("not a list", Run(raw=b'{"a": 1}')),
                       ("a launcher that raises", Run(raises=RuntimeError("boom")))):
        got, _ = drift(good, run=run)
        check(f"K-4.3-timeout: the python's answer is '{label}' -> unknown with a reason, never in_sync/missing_only",
              got["state"] == "unknown" and got["why"] and not got["absent"], got)
    got, run = drift(good, installed=[])
    check("Q3: a valid `[]` (the interpreter proved it has no distributions) -> missing_only with the install command, not unknown",
          got["state"] == "missing_only" and got["absent"] == [{"name": "a", "locked": "1"}]
          and DD.drift_sentence(got).endswith("the project's install command: `poetry install`"), got)
    got, _ = drift(project(lock_text(("opt", "1", "optional = true"))), installed=[])
    check("Q3: a valid `[]` against a lock of only conditional packages -> in_sync (nothing required is absent), counted",
          got["state"] == "in_sync" and got["conditional"] == 1, got)
    got, run = drift(good, timeout=7, installed=[("a", "1")])
    check("K-4.3-timeout: the limit given reaches the launcher", run.calls[0]["timeout"] == 7, run.calls)
    noisy = Run(raw=b'warning: something\n[["a", "1"]]\n')
    got, _ = drift(good, run=noisy)
    check("the answer is the last line (a site warning before it does not break the read)", got["state"] == "in_sync", got)

    root_missing = DD.check(str(tmp() / "nowhere"), profile())
    check("a project root that is not a directory -> unknown, no traceback", root_missing["state"] == "unknown"
          and "not a directory" in root_missing["why"])
    check("a root of None -> unknown", DD.check(None, None)["state"] == "unknown")


def not_the_factory():
    """I5 / M7: the python read for a `profile_wrapper` is the project's, never a copy of the factory's PATH."""
    root = tmp()
    (root / "pyproject.toml").write_text('[project]\nname = "demo"\n', encoding="utf-8")
    (root / "poetry.lock").write_text(lock_text(("a", "2")), encoding="utf-8")
    store = tmp() / "pypoetry" / "virtualenvs"
    own = store / "demo-AbCd1234-py3.12"
    make_env(own)
    decoy = tmp() / "factory-python"
    decoy_folder = make_env(decoy)
    environ = environ_of(root)
    environ["PATH"] = str(decoy_folder) + os.pathsep + environ["PATH"]
    prof = profile(("poetry", "run", "pytest"))
    probe = Probe(stdout=str(own))
    got, run = drift(root, prof, installed=[("a", "1")], environ=environ, probe_run=probe)
    check("K-4.3-wrapper: `poetry run` -> the environment is the one `poetry env info -p` names", got["state"] == "differs"
          and got["environment"]["source"] == "profile_wrapper", got)
    check("K-4.3-wrapper (M7): the python read lies inside THAT environment, not the factory's python on PATH",
          run.calls and DD._under(run.calls[0]["argv"][0], own) and not DD._under(run.calls[0]["argv"][0], decoy), run.calls)
    check("K-4.3-wrapper (I7): the only process the probe starts is `env info -p`; `poetry run` is never run",
          probe.calls == [["poetry-fake", "env", "info", "-p"]], probe.calls)
    check("K-4.3-wrapper: the payload never runs through the wrapper", run.calls[0]["argv"][1:3] == ["-I", "-c"]
          and "poetry" not in os.path.basename(run.calls[0]["argv"][0]).lower())

    other = tmp() / "pypoetry" / "virtualenvs" / "another-AbCd1234-py3.12"
    make_env(other)
    got, run = drift(root, prof, installed=[("a", "1")], environ=environ, probe_run=Probe(stdout=str(other)))
    check("K-4.3-wrapper: another project's `poetry env info -p` -> unknown (foreign), nothing read",
          got["state"] == "unknown" and not run.calls and "behind the launcher `poetry`" in got["why"], got)
    probe = Probe(stdout="", returncode=1)
    got, run = drift(root, prof, installed=[("a", "1")], environ=environ, probe_run=probe)
    check("K-4.3-wrapper: the project's environment does not exist yet -> unknown; nothing is created (poetry run is not run)",
          got["state"] == "unknown" and not run.calls and probe.calls == [["poetry-fake", "env", "info", "-p"]], got)
    got, run = drift(root, prof, installed=[("a", "1")], environ=environ, probe_run=Probe(stdout=str(own)), which=lambda c, path=None: None)
    check("K-4.3-wrapper: poetry not installed -> the wrapper is not found, nothing read", got["state"] == "unknown" and not run.calls, got)
    for argv in (["uv", "run", "pytest"],):
        probe = Probe(stdout=str(own))
        got, run = drift(root, profile(argv, manager="uv 0.5"), installed=[("a", "1")], environ=environ, probe_run=probe,
                         which=lambda c, path=None: "x")
        check(f"K-4.3-wrapper: `{' '.join(argv[:2])}` has no read-only probe -> unknown, the launcher is never started",
              got["state"] == "unknown" and not run.calls and not probe.calls and "no read-only probe" in got["why"], got)

    vroot = tmp()
    (vroot / "poetry.lock").write_text(lock_text(("a", "2")), encoding="utf-8")
    make_env(vroot / ".venv")
    novenv = project(lock_text(("a", "2")), venv=False)
    inside = vroot / ".venv" / ("Scripts" if NT else "bin") / ("python.exe" if NT else "python")
    got, run = drift(vroot, profile((str(inside), "-m", "pytest")), installed=[("a", "1")])
    check("a profile that starts the project's own venv python -> that python is the one read",
          got["state"] == "differs" and DD._under(run.calls[0]["argv"][0], vroot / ".venv"), got)
    elsewhere = tmp() / "py" / ("Scripts" if NT else "bin")
    elsewhere.mkdir(parents=True)
    (elsewhere / ("python.exe" if NT else "python")).write_bytes(b"")
    got, run = drift(novenv, profile((str(elsewhere / ("python.exe" if NT else "python")), "-m", "pytest")), installed=[("a", "1")])
    check("a venv-python launcher outside the project -> unknown (foreign), never read", got["state"] == "unknown" and not run.calls, got)

    # the interpreter found on the overlay is outside the environment folder: unknown, not read
    dirroot = project(lock_text(("a", "2")))
    outside = tmp() / "py2"
    outside_folder = make_env(outside)
    real_launch = project_env.launch_argv
    project_env.launch_argv = lambda argv, env: [str(outside_folder / ("python.exe" if NT else "python"))] + list(argv[1:])
    try:
        got, run = drift(dirroot, installed=[("a", "1")])
    finally:
        project_env.launch_argv = real_launch
    check("a python that is not inside the environment folder -> unknown, never read", got["state"] == "unknown" and not run.calls
          and "inside" in got["why"], got)


# --- the command (4.2 side) -------------------------------------------------------------------------

def commands():
    check("install_command: the profile's commands.install first",
          DD.install_command(profile(install={"argv": ["make", "deps"], "cwd": "backend", "kind": "setup"}))
          == {"argv": ["make", "deps"], "cwd": "backend", "source": "profile"})
    check("install_command: no profile row -> the table row of the first word of package_manager",
          DD.install_command(profile(manager="Poetry 2.4.1"), "svc") == {"argv": ["poetry", "install"], "cwd": "svc", "source": "table"})
    check("install_command: the profile's cwd, else the folder of the lock",
          DD.install_command(profile(install={"argv": ["make"], "kind": "setup"}), "svc")["cwd"] == "svc")
    for label, prof in (("no row for the manager", profile(manager="npm 10")), ("no manager", {}), ("a manager that is prose only", profile(manager="")),
                        ("None", None)):
        check(f"install_command: {label} -> source none, no argv", DD.install_command(prof)["source"] == "none"
              and DD.install_command(prof)["argv"] == [], label)
    for label, install in (("empty argv", {"argv": [], "kind": "setup"}), ("blank tokens", {"argv": ["", " "], "kind": "setup"}),
                           ("a string argv", {"argv": "poetry install", "kind": "setup"}), ("a bool token", {"argv": [True], "kind": "setup"})):
        check(f"install_command: a commands.install with {label} falls through to the table",
              DD.install_command(profile(install=install))["source"] == "table", label)
    root = project(lock_text(("a", "2")))
    got, _ = drift(root, profile(install={"argv": ["make", "deps"], "cwd": "backend", "kind": "setup"}), installed=[("a", "1")])
    check("check: the profile's install command beats the table and is the one printed",
          got["command"]["source"] == "profile" and "`make deps`" in DD.drift_sentence(got), got["command"])
    got, _ = drift(root, profile(manager="npm 10"), installed=[("a", "1")])
    check("K-4.4-nocmd (data side): no command -> the sentence says to record it at onboarding",
          got["state"] == "differs" and got["command"]["source"] == "none"
          and DD.drift_sentence(got).endswith("no install command is recorded for this project; record it at onboarding"), DD.drift_sentence(got))
    check("a command with spaces is quoted the way a person types it", DD.command_text({"argv": ["make", "a b"]}) == "make 'a b'"
          or DD.command_text({"argv": ["make", "a b"]}) == 'make "a b"', DD.command_text({"argv": ["make", "a b"]}))
    nested = tmp()
    (nested / "svc" / "tests").mkdir(parents=True)
    (nested / "svc" / "poetry.lock").write_text(lock_text(("a", "2")), encoding="utf-8")
    make_env(nested / "svc" / ".venv")
    got, _ = drift(nested, profile(cwd="svc/tests"), installed=[("a", "1")])
    check("the lock is the nearest one from the test command's folder; the table command runs in its folder",
          got["lock"] == "svc/poetry.lock" and got["command"]["cwd"] == "svc" and got["environment"]["where"] == "svc/.venv", got)
    check("m1: the install command of a uv project is `uv sync --locked`",
          DD.install_command(profile(manager="uv 0.5"))["argv"] == ["uv", "sync", "--locked"])


def profiles():
    """F1 and Q1: which profiles take part (one reading), and one check per distinct environment."""
    import profile_contract
    rows = [{"profile_id": "api", "selected": False}, {"profile_id": "ui"}]
    check("F1: a profile with no `selected` key is selected, `selected: false` sits out (the pair of the critic's trace)",
          [p["profile_id"] for p in profile_contract.selected_profiles({"profiles": rows})] == ["ui"])
    check("F1: no profile selected -> all of them (the reading of execution_request._selected_profiles)",
          [p["profile_id"] for p in profile_contract.selected_profiles(
              {"profiles": [{"profile_id": "a", "selected": False}, {"profile_id": "b", "selected": False}]})] == ["a", "b"])
    root = tmp()
    (root / "cfg.json").write_text(json.dumps({"profiles": [dict(profile(), profile_id="api", selected=False),
                                                              dict(profile(manager="npm"), profile_id="ui")]}), encoding="utf-8")
    check("F1: project_env.profile_from takes the profile the one reading takes (ui), not the deselected api",
          project_env.profile_from(root / "cfg.json").get("profile_id") == "ui")
    (root / "bare.json").write_text(json.dumps({"profiles": [{"commands": {}}]}), encoding="utf-8")
    check("F1: a lone row without profile_id is still returned (a bare profile file)", project_env.profile_from(root / "bare.json") == {"commands": {}})

    base = project(lock_text(("a", "2")))
    api, ui = dict(profile(), profile_id="api"), dict(profile(), profile_id="ui")
    run = Run([("a", "1")])
    entries = DD.check_profiles(base, [api, ui], environ=environ_of(base), run=run, which=poetry_at)
    check("Q1: two profiles over one environment cost one check and one launch, each result names both profiles",
          len(entries) == 1 and entries[0]["profiles"] == ["api", "ui"] and len(run.calls) == 1, entries)
    nested = tmp()
    (nested / "svc").mkdir()
    (nested / "poetry.lock").write_text(lock_text(("a", "2")), encoding="utf-8")
    (nested / "svc" / "poetry.lock").write_text(lock_text(("a", "1")), encoding="utf-8")
    make_env(nested / ".venv")
    make_env(nested / "svc" / ".venv")
    run = Run([("a", "1")])
    entries = DD.check_profiles(nested, [dict(profile(cwd="svc"), profile_id="svc"), api], environ=environ_of(nested), run=run, which=poetry_at)
    check("Q1: two profiles over two environments -> two checks, worst first (differs before in_sync)",
          [e["profiles"] for e in entries] == [["api"], ["svc"]] and [e["result"]["state"] for e in entries] == ["differs", "in_sync"], entries)
    check("Q1: the text of the drifted group names the profiles it covers when more than one was checked",
          DD.drift_text(entries).startswith("(api) installed a 1, the lock says 2"), DD.drift_text(entries))
    check("Q1: a single profile checked -> no profile prefix in the sentence",
          not DD.drift_text(DD.check_profiles(base, [api], environ=environ_of(base), run=Run([("a", "1")]), which=poetry_at)).startswith("("))
    check("Q1: no profile at all -> one check with an empty profile (the project itself)",
          len(DD.check_profiles(base, [], environ=environ_of(base), run=Run([("a", "1")]), which=poetry_at)) == 1)
    check("Q1: an unknown group never lets the whole be in_sync (worst first puts it before in_sync)",
          DD.check_profiles(tmp(), [api, ui])[0]["result"]["state"] == "unknown")


def minors():
    """m2 (the probe runs in the lock's folder), m3 (no private name of project_env), m4 (the table is read once)."""
    root = tmp()
    svc = root / "svc"
    svc.mkdir()
    (svc / "pyproject.toml").write_text('[project]\nname = "demo"\n', encoding="utf-8")
    (svc / "poetry.lock").write_text(lock_text(("a", "2")), encoding="utf-8")
    own = svc / ".venv"
    make_env(own)
    probe = Probe(stdout=str(own))
    seen = []

    def spy(cmd, **kwargs):
        seen.append(kwargs.get("cwd"))
        return probe(cmd, **kwargs)

    got, _ = drift(root, profile(("poetry", "run", "pytest"), cwd="svc"), installed=[("a", "1")], environ=environ_of(root),
                   probe_run=spy)
    check("m2: `poetry env info -p` runs in the folder of the lock (svc), not in the project root",
          got["state"] == "differs" and seen and all(Path(c) == svc for c in seen[-1:]), (seen, got))
    source = Path(DD.__file__).read_text(encoding="utf-8")
    check("m3: dependency_drift reaches no private name of project_env (they are published)", "PE._" not in source)
    calls = []
    real = DD.load_table
    DD.load_table = lambda *a, **k: (calls.append(1), real(*a, **k))[1]
    try:
        drift(project(lock_text(("a", "2"))), installed=[("a", "1")])
    finally:
        DD.load_table = real
    check("m4: one `check` reads the table once", len(calls) == 1, calls)
    check("m4: STATES, which nothing read, is gone", not hasattr(DD, "STATES"))


# --- no write ---------------------------------------------------------------------------------------

def reads_only():
    root = project(lock_text(("a", "2")))
    environ_of(root)
    before = sorted(str(p.relative_to(root)) for p in root.rglob("*"))
    drift(root, installed=[("a", "1")])
    check("check writes nothing into the project (I7)", before == sorted(str(p.relative_to(root)) for p in root.rglob("*")))


# --- command line -----------------------------------------------------------------------------------

def command_line():
    script = Path(__file__).resolve().parents[1] / "dependency_drift.py"

    def cli(*args):
        return subprocess.run([sys.executable, "-B", str(script), *map(str, args)], capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=120)

    root = tmp()
    done = cli(root)
    check("cli: a project with no lock -> exit 0, `state: unknown`", done.returncode == 0 and "state: unknown" in done.stdout, done)
    done = cli(root, "--json")
    check("cli --json: exit 0 and the documented shape", done.returncode == 0 and sorted(json.loads(done.stdout)) == sorted(
        ["state", "lock", "checked", "differs", "absent", "conditional", "why", "environment", "command"]), done.stdout)
    done = cli(root / "nowhere")
    check("cli: a root that is not a directory -> exit 2, one stderr line", done.returncode == 2 and len(done.stderr.splitlines()) == 1
          and "Traceback" not in done.stderr, done)
    (root / "broken.json").write_text("{no", encoding="utf-8")
    done = cli(root, "--profile", root / "broken.json")
    check("cli: a broken --profile -> exit 2, one stderr line", done.returncode == 2 and "Traceback" not in done.stderr, done)
    done = cli()
    check("cli: no argument -> usage, exit 2", done.returncode == 2)
    sync = project(lock_text(("a", "1")))
    out = io.StringIO()
    DD_check = DD.check
    DD.check = lambda r, p=None, **kw: DD_check(r, p or profile(), environ=environ_of(sync), run=Run([("a", "1")]), which=poetry_at)
    try:
        code = DD.main([str(sync)], out=out)
    finally:
        DD.check = DD_check
    check("cli: in_sync prints `state: in_sync`, exit 0", code == 0 and "state: in_sync" in out.getvalue(), out.getvalue())
    drifted = project(lock_text(("a", "2")))
    out = io.StringIO()
    DD.check = lambda r, p=None, **kw: DD_check(r, p or profile(), environ=environ_of(drifted), run=Run([("a", "1")]), which=poetry_at)
    try:
        code = DD.main([str(drifted)], out=out)
    finally:
        DD.check = DD_check
    check("cli: differs prints the sentence's pieces and the command, exit 0", code == 0 and "state: differs" in out.getvalue()
          and "command: poetry install (table)" in out.getvalue() and "installed a 1, the lock says 2" in out.getvalue(), out.getvalue())


def main():
    try:
        table()
        comparison()
        doubts()
        not_the_factory()
        commands()
        profiles()
        minors()
        reads_only()
        command_line()
    finally:
        for path in TMP:
            shutil.rmtree(path, ignore_errors=True)
    print(f"=== test_dependency_drift: {CHECKS - FAILS}/{CHECKS} ok ===")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
