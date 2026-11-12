"""B-413: the standard streams are set to UTF-8 in ONE place (scripts/console_io.py).

A Windows console or pipe is cp1251, cp866 or ascii. A script that prints its own text there
either died with UnicodeEncodeError or printed the wrong bytes (U+2014 is byte 0x97 in cp1251,
so the person read garbage where an em dash was). The cases here run children under `ascii`,
`ascii:replace` and `cp1251` and compare their BYTES with a UTF-8 control run of the same child:
U+2014 sits inside cp1251, U+2192 sits outside it. Children run with -B, with PYTHONUTF8 and
PYTHONLEGACYWINDOWSSTDIO removed and PYTHONIOENCODING set per case.

K1 console_io itself: adversarial streams, call-time lookup, line buffering, errors.
K2 install_smoke --help and its --reuse-within path, K2b selftest --help (red before B-413).
K3 the launcher routes (entry, cmd shell, pwsh, sh), the layout without the helper, a real hook.
K4 hooklib at import: stdout, stderr and stdin.
K5 the setup call is the first statement everywhere it was put (AST), and no loop remains.
K6 install_smoke.run() children carry PYTHONIOENCODING=utf-8, no other child does.
K7 the residue scan: no script that prints non-ASCII text starts without the setup.
"""
import ast
import io
import json
import os
import shutil
import subprocess
import sys
import tokenize
import unittest.mock as mock
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import SCRIPTS, check, check_eq, cleanup, finish, temp_dir  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import console_io  # noqa: E402
import install_smoke  # noqa: E402
import test_install_smoke_layout as SMOKE  # noqa: E402
import test_launcher_argv as LA  # noqa: E402

WIN = os.name == "nt"
DASH = "\u2014"
ARROW = "\u2192"
DASH_UTF8 = DASH.encode("utf-8")
ENCODINGS = ("ascii", "ascii:replace", "cp1251")
TIMEOUT = 300
SCOPE_ENV = ("PYTHONUTF8", "PYTHONLEGACYWINDOWSSTDIO", "PYTHONIOENCODING", "QA_FACTORY_LAUNCHER",
             "CLAUDE_PROJECT_DIR", "CLAUDE_ENV_FILE")


def child_env(encoding: str | None) -> dict:
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", QA_FACTORY_PYTHON=sys.executable)
    for name in SCOPE_ENV:
        env.pop(name, None)
    if encoding:
        env["PYTHONIOENCODING"] = encoding
    return env


def run_py(args: list, encoding: str | None, *, cwd: Path | None = None, stdin: bytes = b""):
    return subprocess.run([sys.executable, "-B", *[str(a) for a in args]], input=stdin,
                          capture_output=True, cwd=cwd, env=child_env(encoding), timeout=TIMEOUT)


def same_bytes(label: str, make_run) -> None:
    """`make_run(encoding)` -> a finished process. Every legacy encoding must give the control's
    exit code and the control's stdout and stderr bytes."""
    control = make_run("utf-8")
    for encoding in ENCODINGS:
        got = make_run(encoding)
        check(f"{label} under {encoding}: exit {control.returncode}, stdout and stderr bytes equal the "
              "utf-8 control",
              (got.returncode, got.stdout, got.stderr) == (control.returncode, control.stdout, control.stderr),
              f"exit {got.returncode} vs {control.returncode}; stdout {got.stdout[:160]!r} vs "
              f"{control.stdout[:160]!r}; stderr {got.stderr[-300:]!r}")


# --- K1 ----------------------------------------------------------------------------------------

def wrapper(encoding: str = "ascii", *, line_buffering: bool = False, errors: str = "strict"):
    raw = io.BytesIO()
    return io.TextIOWrapper(raw, encoding=encoding, errors=errors, line_buffering=line_buffering,
                            newline="\n"), raw


def with_streams(out, err, inp, call):
    saved = (sys.stdout, sys.stderr, sys.stdin)
    sys.stdout, sys.stderr, sys.stdin = out, err, inp
    try:
        call()
    finally:
        sys.stdout, sys.stderr, sys.stdin = saved


def k1_console_io() -> None:
    probes = {}

    def never_raises(name, out, err, inp, **kw):
        try:
            with_streams(out, err, inp, lambda: console_io.utf8_stdio(**kw))
            probes[name] = None
        except Exception as exc:  # noqa: BLE001 - the point of the case
            probes[name] = repr(exc)

    closed, _ = wrapper()
    closed.close()
    read, raw = wrapper("ascii")
    raw.write(b"abc")
    raw.seek(0)
    read.read()  # a stdin that was already read: the encoding can no longer change
    never_raises("StringIO", io.StringIO(), io.StringIO(), io.StringIO(), stdin=True)
    never_raises("None (pythonw)", None, None, None, stdin=True)
    never_raises("closed stream", closed, closed, closed, stdin=True)
    never_raises("stdin already read", io.StringIO(), io.StringIO(), read, stdin=True)
    never_raises("object without reconfigure", object(), object(), object(), stdin=True)
    for name, problem in probes.items():
        check(f"K1 utf8_stdio never raises on: {name}", problem is None, str(problem))

    # The next stream is still tried after one that fails (a StringIO in front of a real wrapper).
    err, err_raw = wrapper("ascii")
    with_streams(io.StringIO(), err, None, lambda: console_io.utf8_stdio())
    check_eq("K1 a failing stdout does not stop stderr", err.encoding, "utf-8")

    # E5: the streams are looked up at CALL time (a stream swapped in before the call is handled).
    out, _ = wrapper("cp1251")
    err, _ = wrapper("cp1251")
    inp, _ = wrapper("cp1251")
    with_streams(out, err, inp, lambda: console_io.utf8_stdio())
    check("K1 stdout and stderr swapped in before the call are handled; stdin is left alone by default",
          (out.encoding, err.encoding, inp.encoding) == ("utf-8", "utf-8", "cp1251"),
          str((out.encoding, err.encoding, inp.encoding)))
    with_streams(out, err, inp, lambda: console_io.utf8_stdio(stdin=True))
    check_eq("K1 stdin=True reconfigures stdin", inp.encoding, "utf-8")

    # errors: the default is "replace" (a missing default resets the stream to strict).
    out, _ = wrapper("ascii")
    with_streams(out, io.StringIO(), None, lambda: console_io.utf8_stdio())
    check_eq("K1 errors default is replace", out.errors, "replace")
    out, _ = wrapper("ascii")
    with_streams(out, io.StringIO(), None, lambda: console_io.utf8_stdio(errors="strict"))
    check_eq("K1 errors is passed through", out.errors, "strict")

    # line_buffering: only when asked, and never to stdin.
    out, _ = wrapper("ascii")
    inp, _ = wrapper("ascii")
    with_streams(out, io.StringIO(), inp, lambda: console_io.utf8_stdio(stdin=True))
    check("K1 line_buffering None leaves buffering alone", out.line_buffering is False)
    with_streams(out, io.StringIO(), inp, lambda: console_io.utf8_stdio(stdin=True, line_buffering=True))
    check("K1 line_buffering True reaches stdout and never stdin",
          out.line_buffering is True and inp.line_buffering is False,
          str((out.line_buffering, inp.line_buffering)))

    # A lone surrogate written after the call is replaced, not raised.
    out, raw = wrapper("ascii")
    with_streams(out, io.StringIO(), None, lambda: console_io.utf8_stdio())
    try:
        out.write("a\ud800" + DASH)
        out.flush()
        got = raw.getvalue()
    except Exception as exc:  # noqa: BLE001
        got = repr(exc).encode()
    check_eq("K1 a lone surrogate after the call becomes ? and the dash stays UTF-8", got,
             b"a?" + DASH_UTF8)

    # Importing the module has no side effect on the streams.
    code = ("import sys; sys.path.insert(0, sys.argv[1]); import console_io; "
            "print(sys.stdout.encoding, sys.stderr.encoding)")
    proc = run_py(["-c", code, str(SCRIPTS)], "ascii")
    check_eq("K1 importing console_io leaves the streams as they were", proc.stdout.decode().strip(),
             "ascii ascii")


# --- K2 / K2b ----------------------------------------------------------------------------------

def k2_install_smoke() -> None:
    script = SCRIPTS / "install_smoke.py"
    now = datetime.now(timezone.utc).isoformat()
    base = temp_dir("qa-console-k2-")
    counter = {"n": 0}

    def reuse_run(encoding: str):
        # A fresh directory per run: the reuse path writes a report beside the seed, and a second
        # run in the same directory would find it and name a different file.
        counter["n"] += 1
        folder = base / f"run-{counter['n']}"
        folder.mkdir()
        (folder / "doctor-install-smoke-seed.json").write_text(json.dumps({
            "status": "passed", "package_fingerprint": install_smoke.package_fingerprint(),
            "plugin_root": str(install_smoke.PLUGIN_ROOT), "completed_at": now}), encoding="utf-8")
        return run_py([script, "--report", folder / "doctor-install-smoke-new.json",
                       "--reuse-within", "1"], encoding)

    try:
        same_bytes("K2 install_smoke.py --help", lambda enc: run_py([script, "--help"], enc))
        same_bytes("K2 install_smoke.py --reuse-within", reuse_run)
        for label, make_run in (("--help", lambda enc: run_py([script, "--help"], enc)),
                                ("--reuse-within", reuse_run)):
            proc = make_run("ascii")
            check(f"K2 install_smoke.py {label} under ascii exits 0 and carries the dash as UTF-8",
                  proc.returncode == 0 and DASH_UTF8 in proc.stdout,
                  f"exit {proc.returncode} stdout {proc.stdout[:200]!r} stderr {proc.stderr[-300:]!r}")
        selftest = SCRIPTS / "selftest.py"
        same_bytes("K2b selftest.py --help", lambda enc: run_py([selftest, "--help"], enc))
        proc = run_py([selftest, "--help"], "ascii")
        check("K2b selftest.py --help under ascii exits 0 and carries the dash as UTF-8",
              proc.returncode == 0 and DASH_UTF8 in proc.stdout,
              f"exit {proc.returncode} stderr {proc.stderr[-300:]!r}")
    finally:
        cleanup(base)


# --- K3 ----------------------------------------------------------------------------------------

TARGET = ('print("a \\u2014 b \\u2192 caf\\u00e9")\n'
          '__import__("sys").stderr.write("e \\u2014 f \\u2192\\n")\n')


def k3_layouts(base: Path):
    """(layout with the helper for cmd, for sh, without the helper for cmd/sh): the throwaway
    plugin roots of test_launcher_argv plus console_io.py and a target that imports nothing."""
    made = {}
    for key, helper, eol in (("cmd", True, "\r\n"), ("sh", True, "\n"),
                             ("cmd-nohelper", False, "\r\n"), ("sh-nohelper", False, "\n")):
        if key.startswith("cmd") and not WIN:
            continue
        if key.startswith("sh") and not LA.SH:
            continue
        root = LA.make_layout(base, key, eol=eol)
        (root / "scripts" / "utf8_target.py").write_text(TARGET, encoding="utf-8")
        if helper:
            shutil.copyfile(SCRIPTS / "console_io.py", root / "scripts" / "console_io.py")
        made[key] = root
    return made


def route_makers(roots: dict, suffix: str = "") -> list:
    """[(route, make_run(encoding))] for every launcher route this machine has."""
    def entry(encoding):
        root = roots.get("cmd" + suffix) or roots["sh" + suffix]
        return subprocess.run([sys.executable, "-B", str(root / "scripts" / "run_py_entry.py"),
                               "utf8_target.py"], input=b"{}", capture_output=True, cwd=root,
                              env=child_env(encoding), timeout=LA.TIMEOUT)

    routes = [("entry", entry)]
    if "cmd" + suffix in roots:
        root = roots["cmd" + suffix]
        # `r=root` binds the layout per lambda: a bare `root` is looked up when the lambda runs,
        # after the next block has rebound it to the sh layout (critic t-523 F2).
        routes.append(("shell", lambda enc, r=root: LA.run_shell(r, "utf8_target.py", env=child_env(enc))))
        if LA.PWSH:
            routes.append(("pwsh", lambda enc, r=root: LA.run_pwsh(r, "utf8_target.py", env=child_env(enc))))
    if "sh" + suffix in roots:
        root = roots["sh" + suffix]
        routes.append(("sh", lambda enc, r=root: LA.run_sh(r, ["utf8_target.py"], env=child_env(enc))))
    return routes


def k3_route_binding() -> None:
    """Each route runs ITS layout: with the launcher runners stubbed to name the root they got, the
    shell and pwsh routes name the cmd layout and the sh route names the sh layout."""
    saw = {}
    stubs = {name: (lambda root, *a, _n=name, **k: saw.setdefault(_n, root))
             for name in ("run_shell", "run_pwsh", "run_sh")}
    cmd_root, sh_root = Path("CMD-LAYOUT-crlf"), Path("SH-LAYOUT-lf")
    with mock.patch.multiple(LA, PWSH="pwsh", **stubs):
        for route, make_run in route_makers({"cmd": cmd_root, "sh": sh_root}):
            if route != "entry":
                make_run("ascii")
    check("K3 the shell and pwsh routes run the cmd layout, the sh route the sh layout",
          saw == {"run_shell": cmd_root, "run_pwsh": cmd_root, "run_sh": sh_root}, str(saw))


def k3_launcher() -> None:
    base = temp_dir("qa-console-k3-")
    try:
        roots = k3_layouts(base)
        for route, make_run in route_makers(roots):
            same_bytes(f"K3 launcher route {route}, non-ASCII target", make_run)
            proc = make_run("ascii")
            if route != "pwsh":  # pwsh re-encodes a native command's output with its own page
                check(f"K3 route {route} under ascii writes the dash as UTF-8 and exits 0",
                      proc.returncode == 0 and DASH_UTF8 in proc.stdout and DASH_UTF8 in proc.stderr,
                      f"exit {proc.returncode} stdout {proc.stdout[:120]!r} stderr {proc.stderr[-200:]!r}")
        # No helper: the launcher still launches, and the target sees what a direct run sees.
        nohelper = {k: v for k, v in roots.items() if k.endswith("nohelper")}
        direct_root = next(iter(nohelper.values()), None)
        for route, make_run in route_makers(nohelper, "-nohelper"):
            if route == "pwsh":
                continue  # pwsh rewrites the bytes the direct run does not pass through
            for encoding in ("utf-8", "ascii:replace"):
                direct = run_py([direct_root / "scripts" / "utf8_target.py"], encoding)
                got = make_run(encoding)
                check(f"K3 no console_io.py, route {route} under {encoding}: exit and bytes equal a "
                      "direct run",
                      (got.returncode, got.stdout, got.stderr) == (direct.returncode, direct.stdout,
                                                                   direct.stderr),
                      f"exit {got.returncode} vs {direct.returncode}; stderr {got.stderr[-300:]!r}")
        k3_real_hook(base)
    finally:
        cleanup(base)


def k3_real_hook(base: Path) -> None:
    """A real hook through the launcher, from a marker-free cwd with no CLAUDE_PROJECT_DIR and no
    CLAUDE_ENV_FILE (session_env appends to that file). Green before and after B-413: it proves the
    entry's call does not disturb a hook that reads its stdin as bytes (telemetry_hook, E10/E11)."""
    root = base / "real package"
    (root / "hooks").mkdir(parents=True)
    LA.write_launcher(root / "hooks" / "run-py.cmd", None, "\r\n" if WIN else "\n")
    shutil.copytree(SCRIPTS, root / "scripts",
                    ignore=shutil.ignore_patterns("tests", "__pycache__", "*.pyc"))
    cwd = base / "marker-free cwd"
    cwd.mkdir()
    env = child_env("ascii")
    if WIN:
        proc = LA.run_shell(root, "telemetry_hook.py session_env.py", cwd=cwd, env=env)
    elif LA.SH:
        proc = LA.run_sh(root, ["telemetry_hook.py", "session_env.py"], cwd=cwd, env=env)
    else:
        return
    check("K3 a real hook (telemetry_hook.py session_env.py) through run-py.cmd under ascii exits 0 "
          "(green before and after B-413)", proc.returncode == 0,
          f"exit {proc.returncode} stderr {proc.stderr[-300:]!r}")


# --- K3b: the role CLIs that only call role_cli.run_guarded (critic t-523 F1) ----------------------

def k3b_run_guarded() -> None:
    """context_bundle.py has no setup of its own: its refusal (role_cli.py's dash) is printed by
    run_guarded, so the guard at run_guarded's entry is the only thing that sets the stream."""
    base = temp_dir("qa-console-k3b-")
    try:
        missing = base / "no-such-bundle.json"
        script = SCRIPTS / "context_bundle.py"
        control = run_py([script, "--validate", missing], "utf-8")
        check("K3b control: the refusal under utf-8 carries the UTF-8 dash",
              DASH_UTF8 in control.stderr and control.returncode != 0,
              f"exit {control.returncode} stderr {control.stderr[-200:]!r}")
        for encoding in ("cp1251", "ascii"):
            got = run_py([script, "--validate", missing], encoding)
            check(f"K3b context_bundle.py refusal under {encoding}: the UTF-8 dash bytes, never byte 0x97",
                  DASH_UTF8 in got.stderr and b"\x97" not in got.stderr
                  and got.returncode == control.returncode,
                  f"exit {got.returncode} stderr {got.stderr[-300:]!r}")
    finally:
        cleanup(base)


# --- K4 ----------------------------------------------------------------------------------------

def k4_hooklib() -> None:
    code = ("import sys; sys.path.insert(0, sys.argv[1]); import hooklib\n"
            "sys.stdout.write('o:\\u2014\\n'); sys.stderr.write('e:\\u2014\\n')\n"
            "sys.stdout.write(ascii(sys.stdin.read()) + chr(10))\n"
            "sys.stdout.write(','.join((sys.stdout.encoding, sys.stderr.encoding, sys.stdin.encoding)))\n")
    for encoding in ENCODINGS:
        proc = run_py(["-c", code, str(SCRIPTS)], encoding, stdin=DASH_UTF8)
        out, err = proc.stdout.replace(b"\r\n", b"\n"), proc.stderr.replace(b"\r\n", b"\n")  # Windows text mode
        check(f"K4 import hooklib under {encoding}: UTF-8 on stdout, stderr and stdin",
              proc.returncode == 0
              and out == (b"o:" + DASH_UTF8 + b"\n'\\u2014'\nutf-8,utf-8,utf-8")
              and err == b"e:" + DASH_UTF8 + b"\n",
              f"exit {proc.returncode} stdout {proc.stdout!r} stderr {proc.stderr[-300:]!r}")


# --- K5 ----------------------------------------------------------------------------------------

MODULE, MAIN_BLOCK, MAIN_BLOCK_AFTER_MODULES = "module", "main-block", "main-block-after-sys.modules"
# file -> where its setup call lives (the 17 converted scripts, hooklib, contract, the launcher
# entry and install_smoke).
WHERE = {
    "hooklib.py": MODULE, "check_witness.py": MODULE, "check_coverage.py": MODULE,
    "contract.py": "force_utf8",
    "artifact_supersede.py": "main", "gate_registry.py": "main", "plan_row.py": "main",
    "source_exclusions.py": "main", "onboarding_probe.py": "main", "question_register.py": "main",
    "story_run.py": "main", "diff_pass.py": "main", "diff_scope.py": "main",
    "planning_contract.py": "main", "role_cli.py": "main", "runtime_probe.py": "main",
    "selftest.py": "main",
    # the files the relaxed K7 scan still flagged (Lead, t-474): one insertion at the top of main()
    "contract_slices.py": "main", "migrate_artifacts.py": "main", "project_gitignore.py": "main",
    "red_sandbox.py": "main", "sizing.py": "main", "stage_status.py": "main",
    "story_version.py": "main", "tracker_write.py": "main", "postcompact_reload.py": "main",
    "onboarding_notes.py": "main",
    "source_preflight.py": MAIN_BLOCK,
    "critic_rollcall.py": MAIN_BLOCK, "launch_check.py": MAIN_BLOCK, "install_smoke.py": MAIN_BLOCK,
    "run_py_entry.py": MAIN_BLOCK_AFTER_MODULES,
}


def _is_helper_call(node) -> bool:
    func = getattr(node, "func", None)
    if isinstance(func, ast.Attribute):
        return func.attr == "utf8_stdio" and isinstance(func.value, ast.Name) and func.value.id == "console_io"
    return isinstance(func, ast.Name) and func.id == "utf8_stdio"


def is_setup(stmt) -> bool:
    """The `Try` node of the guarded form, or a bare call to utf8_stdio / console_io.utf8_stdio."""
    if isinstance(stmt, ast.Try):
        imports = any(isinstance(s, ast.Import) and any(a.name == "console_io" for a in s.names)
                      for s in stmt.body)
        calls = any(isinstance(n, ast.Call) and _is_helper_call(n) for s in stmt.body for n in ast.walk(s))
        guarded = any(isinstance(h.type, ast.Name) and h.type.id == "ImportError" for h in stmt.handlers)
        return imports and calls and guarded
    return isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call) and _is_helper_call(stmt.value)


def _docstring(stmt) -> bool:
    return (isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant)
            and isinstance(stmt.value.value, str))


def _sys_path(node) -> bool:
    return (isinstance(node, ast.Attribute) and node.attr == "path"
            and isinstance(node.value, ast.Name) and node.value.id == "sys")


def _allowed_before_setup(stmt) -> bool:
    """A module docstring, an import, or a sys.path edit: nothing that could print."""
    if isinstance(stmt, (ast.Import, ast.ImportFrom)) or _docstring(stmt):
        return True
    if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
        func = stmt.value.func
        return isinstance(func, ast.Attribute) and func.attr in ("insert", "append") and _sys_path(func.value)
    targets = stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target] if isinstance(stmt, ast.AugAssign) else []
    return bool(targets) and all(_sys_path(t) or (isinstance(t, ast.Subscript) and _sys_path(t.value))
                                 for t in targets)


def _main_block(tree):
    for stmt in tree.body:
        if (isinstance(stmt, ast.If) and isinstance(stmt.test, ast.Compare)
                and isinstance(stmt.test.left, ast.Name) and stmt.test.left.id == "__name__"):
            return stmt.body
    return None


def setup_position(source: str, where: str) -> str | None:
    """None when the setup stands where the first-statement rule wants it, else why not."""
    tree = ast.parse(source)
    if where == MODULE:
        for index, stmt in enumerate(tree.body):
            if is_setup(stmt):
                bad = [s for s in tree.body[:index] if not _allowed_before_setup(s)]
                return None if not bad else f"statement at line {bad[0].lineno} comes before the setup"
        return "no setup at module level"
    if where in (MAIN_BLOCK, MAIN_BLOCK_AFTER_MODULES):
        body = _main_block(tree)
        if body is None:
            return "no `if __name__ == \"__main__\":` block"
        skip = 1 if where == MAIN_BLOCK_AFTER_MODULES else 0
        if skip and not (isinstance(body[0], ast.Assign) and "sys.modules" in ast.unparse(body[0])):
            return "the block does not start with the sys.modules line"
        return None if len(body) > skip and is_setup(body[skip]) else "the setup is not the first statement of the block"
    for stmt in tree.body:
        if isinstance(stmt, ast.FunctionDef) and stmt.name == where:
            body = stmt.body[1:] if _docstring(stmt.body[0]) else stmt.body
            return None if body and is_setup(body[0]) else f"the setup is not the first statement of {where}()"
    return f"no function {where}"


def reconfigure_sites(root: Path) -> dict:
    found = {}
    for path in sorted(root.rglob("*.py")):
        if "tests" in path.relative_to(root).parts:
            continue
        count = path.read_text(encoding="utf-8").count("reconfigure(")
        if count:
            found[path.name] = count
    return found


def k5_first_statement() -> None:
    for name, where in WHERE.items():
        problem = setup_position((SCRIPTS / name).read_text(encoding="utf-8"), where)
        check(f"K5 {name}: the setup is first ({where})", problem is None, str(problem))
    problem = setup_position((SCRIPTS / "role_cli.py").read_text(encoding="utf-8"), "run_guarded")
    check("K5 role_cli.py: the setup is first in run_guarded() (critic t-523 F1)", problem is None, str(problem))
    # Negative controls: the same rule must refuse a misplaced or missing setup.
    guarded = "try: import console_io; console_io.utf8_stdio()\nexcept ImportError: pass\n"
    check("K5 control: a print before a module-level setup is refused",
          setup_position("import sys\nprint('x')\n" + guarded, MODULE) is not None)
    check("K5 control: a function whose setup is the second statement is refused",
          setup_position("def main():\n    x = 1\n    " + guarded.replace("\n", "\n    ").rstrip() + "\n",
                         "main") is not None)
    check("K5 control: a missing setup is refused",
          setup_position("def main():\n    pass\n", "main") is not None)
    check("K5 control: a docstring, imports and a sys.path edit before the setup are fine",
          setup_position('"""d"""\nimport sys\nsys.path.insert(0, "x")\n' + guarded, MODULE) is None)
    # One shape everywhere (FR-17): the multi-line guard, with `import console_io` on a line of its
    # own, which is the only form audit A1's IMPORT_RE reads.
    one_line = [p.name for p in sorted(SCRIPTS.glob("*.py"))
                if "try: import console_io" in p.read_text(encoding="utf-8") and p.name != "console_io.py"]
    check("K5 no one-line `try: import console_io` guard remains in the package scripts", not one_line,
          str(one_line))
    # No reconfigure loop remains outside the helper, the test harness and install_smoke's fallback.
    sites = reconfigure_sites(SCRIPTS)
    check("K5 control: the scan finds the reconfigure calls in console_io.py", "console_io.py" in sites)
    other = {k: v for k, v in sites.items() if k not in ("console_io.py", "install_smoke.py")}
    check("K5 no reconfigure( loop remains outside console_io.py and install_smoke's fallback",
          not other, str(other))


# --- K6 ----------------------------------------------------------------------------------------

def k6_child_env() -> None:
    base = temp_dir("qa-console-k6-")
    try:
        root = SMOKE.fake_plugin_root(base, inside_project=False)
        with mock.patch.dict(os.environ):
            os.environ.pop("PYTHONIOENCODING", None)
            os.environ.pop("PYTHONUTF8", None)
            recorder, _ = SMOKE.drive(root)
        scripts = str(root / "scripts")
        run_children, other_children, git_calls, bad = [], [], [], []
        for cmd, kwargs in recorder.calls:
            env = kwargs.get("env")
            if isinstance(cmd, list) and cmd and cmd[0] == "git":
                git_calls.append(cmd)
                continue
            if env is None:
                bad.append(f"no env kwarg: {cmd}")
                continue
            if "PYTHONUTF8" in env:
                bad.append(f"PYTHONUTF8 in the env of {cmd}")
            is_run = (isinstance(cmd, list) and len(cmd) > 1 and str(cmd[1]).startswith(scripts)
                      and Path(str(cmd[1])).name != "inject_context.py")
            (run_children if is_run else other_children).append((cmd, env))
        check("K6 the drive spawned run() children and boundary children", bool(run_children)
              and len(other_children) >= 3, f"{len(run_children)} run(), {len(other_children)} other")
        check("K6 only a git call goes without an env", not bad, "; ".join(bad))
        check("K6 `git init` is the one call without an env (git is not Python)", len(git_calls) == 1)
        wrong = [cmd for cmd, env in run_children if env.get("PYTHONIOENCODING") != "utf-8"]
        check("K6 every run() child carries PYTHONIOENCODING=utf-8", not wrong, str(wrong[:2]))
        leaked = [cmd for cmd, env in other_children if "PYTHONIOENCODING" in env]
        check("K6 the hook loop, the launcher probe and the injection probe carry no PYTHONIOENCODING",
              not leaked, str(leaked[:2]))
        check("K6 the boundary children include the shell=True hooks and inject_context.py",
              any(isinstance(cmd, str) for cmd, _ in other_children)
              and any(isinstance(cmd, list) and Path(str(cmd[1])).name == "inject_context.py"
                      for cmd, _ in other_children))
    finally:
        cleanup(base)


# --- K7 ----------------------------------------------------------------------------------------

TRACKED_CALLS = {"print", "ArgumentParser", "add_argument", "add_parser", "error"}
TEXT_TOKENS = {tokenize.STRING}
if hasattr(tokenize, "FSTRING_MIDDLE"):
    TEXT_TOKENS.add(tokenize.FSTRING_MIDDLE)


def has_setup(source: str) -> bool:
    """A module-level `import hooklib` / `from hooklib import` (also inside a module-level try),
    or a call to utf8_stdio / force_utf8 anywhere in the file. Setup reached only through another
    module that imports hooklib is not recognised: that errs toward flagging."""
    tree = ast.parse(source)

    def module_level(stmts):
        for stmt in stmts:
            if isinstance(stmt, ast.Import) and any(a.name == "hooklib" for a in stmt.names):
                return True
            if isinstance(stmt, ast.ImportFrom) and stmt.module == "hooklib":
                return True
            if isinstance(stmt, ast.Try) and module_level(stmt.body):
                return True
        return False

    if module_level(tree.body):
        return True
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            if name in ("utf8_stdio", "force_utf8"):
                return True
    return False


def prints_non_ascii(source: str) -> list:
    """Line numbers where non-ASCII text goes to a print / argparse call, or `__doc__` (itself
    non-ASCII) goes to argparse. Tokenize-based, so a non-ASCII COMMENT or a docstring that is
    not passed on is never flagged; a continuation line of a multi-line call is."""
    doc = ast.get_docstring(ast.parse(source), clean=False) or ""
    doc_non_ascii = not doc.isascii()
    hits, stack, depth, previous = [], [], 0, None
    for tok in tokenize.generate_tokens(io.StringIO(source).readline):
        if tok.type == tokenize.OP and tok.string in "([{":
            depth += 1
            if (tok.string == "(" and previous is not None and previous.type == tokenize.NAME
                    and previous.string in TRACKED_CALLS):
                stack.append(depth)
        elif tok.type == tokenize.OP and tok.string in ")]}":
            if stack and stack[-1] == depth:
                stack.pop()
            depth -= 1
        elif stack and tok.type in TEXT_TOKENS and not tok.string.isascii():
            hits.append(tok.start[0])
        elif stack and tok.type == tokenize.NAME and tok.string == "__doc__" and doc_non_ascii:
            hits.append(tok.start[0])
        if tok.type not in (tokenize.NL, tokenize.COMMENT):
            previous = tok
    return hits


def _imports_helper(node) -> bool:
    if isinstance(node, ast.Import):
        return any(a.name in ("hooklib", "console_io") for a in node.names)
    return isinstance(node, ast.ImportFrom) and node.module in ("hooklib", "console_io")


def uncovered_hits(source: str) -> list:
    """The non-ASCII print lines of a file that has no module-level setup and that no `hooklib` /
    `console_io` import covers. The ONE relaxation (Lead, t-474): such an import ANYWHERE in the
    module counts when it is executed before the print on that path. Approximation, and its
    direction: a print inside the entry point (`main()` or the `__main__` block) is covered only
    by an import inside that entry that stands on an earlier line; a print inside any other
    function is covered when the entry holds such an import (the function is assumed to be called
    from it); a print at module level, or with the import AFTER it, stays flagged."""
    hits = prints_non_ascii(source)
    if not hits or has_setup(source):
        return []
    tree = ast.parse(source)
    spans = [(n.lineno, n.end_lineno) for n in tree.body
             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]
    entries = [(n.lineno, n.end_lineno) for n in tree.body
               if (isinstance(n, ast.FunctionDef) and n.name == "main")
               or (isinstance(n, ast.If) and isinstance(n.test, ast.Compare)
                   and isinstance(n.test.left, ast.Name) and n.test.left.id == "__name__")]
    imports = sorted(n.lineno for n in ast.walk(tree) if _imports_helper(n))
    uncovered = []
    for hit in hits:
        entry = next((s for s in entries if s[0] <= hit <= s[1]), None)
        if entry:
            covered = any(entry[0] <= i < hit and i <= entry[1] for i in imports)
        elif any(a <= hit <= b for a, b in spans):
            covered = any(a <= i <= b for a, b in entries for i in imports)
        else:
            covered = False
        if not covered:
            uncovered.append(hit)
    return uncovered


def residue(root: Path) -> dict:
    flagged = {}
    for path in sorted(root.glob("*.py")):
        lines = uncovered_hits(path.read_text(encoding="utf-8"))
        if lines:
            flagged[path.name] = lines
    return flagged


def k7_residue() -> None:
    dash, arrow = DASH, ARROW
    cases = {
        "a plain print": (f'print("a {dash} b")\n', True),
        "a non-ASCII comment on a print line": (f'print("a")  # {dash}\n', False),
        "a non-ASCII docstring not passed to argparse": (f'"""x {dash}"""\nimport argparse\nargparse.ArgumentParser("p")\n', False),
        "description=__doc__ with a non-ASCII docstring": (f'"""x {dash}"""\nimport argparse\nargparse.ArgumentParser(description=__doc__)\n', True),
        "an f-string": (f'x = 1\nprint(f"a {{x}} {dash}")\n', True),
        "a multi-line print, the text on a continuation line": (f'print("a",\n      "b {arrow}")\n', True),
        "an add_argument help": (f'ap.add_argument("--x", help="a {dash}")\n', True),
        "text outside any tracked call": (f'x = "a {dash}"\n', False),
    }
    for label, (source, expected) in cases.items():
        check(f"K7 control: {label} is {'flagged' if expected else 'not flagged'}",
              bool(prints_non_ascii(source)) == expected)
    check("K7 control: a file with the setup is never flagged",
          has_setup("try: import console_io; console_io.utf8_stdio()\nexcept ImportError: pass\n")
          and has_setup("import hooklib\n") and not has_setup("import os\n"))
    # The relaxation: an import executed before the print covers it; an import AFTER it does not.
    before = f'def say():\n    print("a {dash}")\n\ndef main():\n    import hooklib\n    say()\n\nif __name__ == "__main__":\n    main()\n'
    inside = f'def main():\n    import hooklib\n    print("a {dash}")\n'
    after = f'def main():\n    print("a {dash}")\n    import hooklib\n'
    at_module = f'print("a {dash}")\ndef main():\n    import hooklib\n'
    in_main_block = f'if __name__ == "__main__":\n    print("a {dash}")\n    import hooklib\n'
    for label, source, expected in (
            ("a function-level import in main() before a print in another function", before, False),
            ("a function-level import before the print in the same entry", inside, False),
            ("an import AFTER the first print in main()", after, True),
            ("a module-level print with the import only inside main()", at_module, True),
            ("an import AFTER the print in the __main__ block", in_main_block, True)):
        check(f"K7 control: {label} is {'flagged' if expected else 'not flagged'}",
              bool(uncovered_hits(source)) == expected)
    flagged = residue(SCRIPTS)
    print(f"K7 residue scan of scripts/*.py: {len(flagged)} flagged {json.dumps(flagged)}")
    check_eq("K7 the residue count is 0 (a flagged file is an unprotected entry script: STOP, report it)",
             len(flagged), 0)


def main() -> None:
    k1_console_io()
    k2_install_smoke()
    k3_route_binding()
    k3_launcher()
    k3b_run_guarded()
    k4_hooklib()
    k5_first_statement()
    k6_child_env()
    k7_residue()
    finish("console encoding")


if __name__ == "__main__":
    main()
