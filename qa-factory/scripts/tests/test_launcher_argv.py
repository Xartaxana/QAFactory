"""The launcher (hooks/run-py.cmd + scripts/run_py_entry.py) hands the caller's arguments to the
target script exactly as the caller encoded them (legacy-2406 wave 3, node W3-L, defect M7).

Two defects stood in the old launcher, both measured on the Codex run TP2-2406:
  * both halves put `scripts/` in front of the first argument, so an ABSOLUTE script path became
    `...\\hooks\\..\\scripts\\C:\\...` and the interpreter could not open it;
  * the Windows half rebuilt argv with `set ARGS=%ARGS% %1`. Batch splits an unquoted
    `--set key=value` into two `%n` at the `=`, and `if "%~1"==""` stopped the collect loop at
    the first empty argument, so everything after `--notes ""` vanished silently.
The fix passes the RAW tail (`%*`, `"$@"`) to one small Python entry that resolves the script and
runs it in the same interpreter. This file is the battery: every argv case runs on Windows TWICE,
through pwsh exactly as hooks/codex.json's `commandWindows` calls the launcher and through
`subprocess.run(<string>, shell=True)` exactly as install_smoke.py calls it, and through `sh` where
one exists. A copy of the legacy launcher is kept below as a RED CONTROL: the same battery must
catch the old defects, or this file would pass on a launcher that does nothing.

KNOWN LIMITS of the cmd route (documented in the launcher header, pinned here, not fixable there):
a newline inside an argument (cmd.exe cuts the command line at it before the launcher runs; a
multi-line text travels by file), `%NAME%` of a defined variable (the outer shell expands it), an
UNQUOTED caret (cmd's escape character, consumed before the launcher sees it), and a command line
beyond cmd's limit of 8191 characters, counted after the launcher adds the interpreter and entry
paths in front of the tail (refused with a non-zero exit, never run with part of its argv).

Run directly: python scripts/tests/test_launcher_argv.py
"""
import json
import os
import shutil
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import PLUGIN_ROOT, check, cleanup, finish  # noqa: E402

WIN = os.name == "nt"
LAUNCHER_SRC = PLUGIN_ROOT / "hooks" / "run-py.cmd"
ENTRY_SRC = PLUGIN_ROOT / "scripts" / "run_py_entry.py"
PWSH = shutil.which("pwsh") or shutil.which("powershell")
SH = shutil.which("sh")
TIMEOUT = 120
# The two Windows entries: install_smoke's string through the shell, and codex.json's
# `commandWindows` through pwsh. Without a PowerShell the second one is skipped out loud.
WIN_ROUTES = ("shell", "pwsh") if PWSH else ("shell",)

# The launcher as it stood at 0.7.19, byte for byte apart from the line endings (written with
# CRLF below, as a Windows checkout has it). Used for the red control and as the latency baseline.
LEGACY_LAUNCHER = """: << 'CMDBLOCK'
@echo off
REM Cross-platform polyglot launcher for qa-factory Python scripts.
REM On Windows: cmd.exe runs the batch portion and calls the Python interpreter.
REM On Unix: the shell interprets this file as a script (: is a no-op).
REM
REM Usage: run-py.cmd <script.py> [args...]
REM Stdin is passed through untouched (hooks read their JSON event from stdin).

if "%~1"=="" (
    echo run-py.cmd: missing script name >&2
    exit /b 1
)

set "HOOK_DIR=%~dp0"
set "SCRIPT=%HOOK_DIR%..\\scripts\\%~1"
set "SCRIPT_NAME=%~1"
shift

set "ARGS="
:collect
if "%~1"=="" goto run
set ARGS=%ARGS% %1
shift
goto collect

:run
if defined QA_FACTORY_PYTHON goto configured
where py >nul 2>nul
if %ERRORLEVEL% equ 0 goto pylauncher
where python >nul 2>nul
if %ERRORLEVEL% equ 0 goto pythonlauncher
where python3 >nul 2>nul
if %ERRORLEVEL% equ 0 goto python3launcher
echo run-py.cmd: no Python interpreter found on PATH >&2
exit /b 1
:configured
"%QA_FACTORY_PYTHON%" "%SCRIPT%" %ARGS%
exit /b %ERRORLEVEL%
:pylauncher
py -3 "%SCRIPT%" %ARGS%
exit /b %ERRORLEVEL%
:pythonlauncher
python "%SCRIPT%" %ARGS%
exit /b %ERRORLEVEL%
:python3launcher
python3 "%SCRIPT%" %ARGS%
exit /b %ERRORLEVEL%
CMDBLOCK

# Unix: run the named script with python3 (fall back to python)
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SCRIPT_NAME="$1"
shift
if [ -n "${QA_FACTORY_PYTHON:-}" ]; then
  exec "${QA_FACTORY_PYTHON}" "${SCRIPT_DIR}/../scripts/${SCRIPT_NAME}" "$@"
fi
if command -v python3 >/dev/null 2>&1; then
  exec python3 "${SCRIPT_DIR}/../scripts/${SCRIPT_NAME}" "$@"
fi
exec python "${SCRIPT_DIR}/../scripts/${SCRIPT_NAME}" "$@"
"""

# The target of every argv case: prints what it received as ASCII-only JSON (so a console code
# page cannot change the evidence), reads stdin as BYTES, and reports what the launcher marker
# looks like from inside. ECHO_EXIT is the exit code, ECHO_MARKER a file proving it ran at all,
# ECHO_CHILD asks it to start a child process and report the marker the child inherited.
ECHO = '''import json, os, sys
data = sys.stdin.buffer.read()
try:
    import run_py_entry
    via = run_py_entry.VIA_CMD
except ImportError:
    via = None
marker = os.environ.get("ECHO_MARKER")
if marker:
    with open(marker, "w") as f:
        f.write("ran")
child = None
if os.environ.get("ECHO_CHILD"):
    import subprocess
    child = subprocess.run([sys.executable, "-c",
        "import os; print(os.environ.get('QA_FACTORY_LAUNCHER'))"],
        capture_output=True, text=True).stdout.strip()
print(json.dumps({"argv": sys.argv[1:], "argv0": sys.argv[0], "stdin_hex": data.hex(),
                  "via_cmd": via, "marker_env": os.environ.get("QA_FACTORY_LAUNCHER"),
                  "path0": sys.path[0], "child_marker": child, "name": __name__,
                  "file": __file__, "pycache_env": os.environ.get("QA_FACTORY_PYCACHE")}))
sys.exit(int(os.environ.get("ECHO_EXIT", "0")))
'''
DECOY = 'import json\nprint(json.dumps({"decoy": True}))\n'
NOOP = "pass\n"
EXIT_MODES = '''import os, sys
mode = os.environ["MODE"]
if mode == "int":
    sys.exit(int(os.environ.get("CODE", "0")))
if mode == "none":
    sys.exit(None)
if mode == "text":
    sys.exit("boom message")
if mode == "raise":
    raise RuntimeError("kaboom")
'''
# The target of the interpreter-cache cases: prints ONE fixed line (so two runs can be compared
# byte for byte), appends a line to APPEND_TO each time it runs (a target that ran twice is
# visible), and exits with APPEND_EXIT.
APPEND_ONCE = '''import os, sys
path = os.environ.get("APPEND_TO")
if path:
    with open(path, "a") as f:
        f.write("run\\n")
sys.stdout.write('{"fixed": true}\\n')
sys.exit(int(os.environ.get("APPEND_EXIT", "0")))
'''
FIXED_OUT = '{"fixed": true}'


# One launch costs about a second on a machine with a real-time virus scanner (measured: 0.5 s
# for the bare interpreter, 1 s through cmd), and the battery is about two hundred launches. The
# batteries therefore run as independent tasks in a thread pool; each records its checks into its
# own list (`rec`) and main replays them in a fixed order, so the printed result does not depend
# on which task finished first. Nothing here is timed (FR-31): the pool only shortens the wait,
# and every launch keeps its own generous timeout.
_SINK = threading.local()


# What a script that runs through the launcher may rely on, because it relies on it when the
# interpreter runs it directly: `__name__ == "__main__"`, its own `__file__`, a sibling module
# from its own directory, and `sys.modules["__main__"]` being the module that holds its globals
# (a dataclass looks its module up there; pickle resolves a top-level function through it).
EDGE_TARGET = '''import dataclasses, json, os, pickle, sys
import edge_sibling


@dataclasses.dataclass
class Box:
    n: int


def top():
    return 1


main = sys.modules["__main__"]
info = {"name": __name__, "file": __file__, "sibling": edge_sibling.VALUE,
        "main_holds_globals": getattr(main, "Box", None) is Box,
        "main_file": getattr(main, "__file__", None), "box": dataclasses.asdict(Box(3)),
        "pickle_function": pickle.loads(pickle.dumps(top)) is top,
        "pickle_class": pickle.loads(pickle.dumps(Box(5))) == Box(5),
        "builtins": "len" in (__builtins__ if isinstance(__builtins__, dict)
                              else vars(__builtins__))}
if __name__ == "__main__":
    print(json.dumps(info))
'''
EDGE_SIBLING = 'VALUE = "sibling-ok"\n'
# PEP 263: a UTF-8 BOM, and a coding line for a non-UTF-8 source, are read the way the
# interpreter reads a script. The non-ASCII literals are written as bytes so this file stays ASCII.
BOM_TARGET = (b"\xef\xbb\xbf" + b'import json\nprint(json.dumps({"text": "caf\xc3\xa9"}))\n')
LATIN1_TARGET = (b"# -*- coding: latin-1 -*-\nimport json\n"
                 b'print(json.dumps({"text": "caf\xe9"}))\n')


def rec(name: str, ok, detail: str = "") -> None:
    _SINK.items.append((name, bool(ok), detail))


def rec_eq(name: str, got, expected) -> None:
    rec(name, got == expected, f"expected {expected!r}, got {got!r}")


def collect(func, *args) -> list:
    _SINK.items = []
    try:
        func(*args)
    except Exception as exc:  # a crashed battery is a red line, not a lost traceback
        rec(f"{func.__name__} ran to the end", False, repr(exc))
    return _SINK.items


def write_launcher(path: Path, text: str | None, eol: str) -> None:
    """The launcher written with ONE line-ending form: the polyglot depends on it (CRLF for
    cmd.exe on a Windows checkout, LF for sh, which is what git stores and a POSIX clone has)."""
    if text is None:
        raw = LAUNCHER_SRC.read_bytes().replace(b"\r\n", b"\n")
    else:
        raw = text.encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw.replace(b"\n", eol.encode("ascii")))


def make_layout(base: Path, name: str, *, legacy: bool = False, eol: str = "\r\n") -> Path:
    """A throwaway plugin root: hooks/run-py.cmd + scripts/ with the echo targets. The directory
    name carries a space on purpose (the package path of a real install may)."""
    root = base / f"qa factory {name}"
    write_launcher(root / "hooks" / "run-py.cmd", LEGACY_LAUNCHER if legacy else None, eol)
    scripts = root / "scripts"
    (scripts / "tests").mkdir(parents=True)
    if not legacy and ENTRY_SRC.exists():
        shutil.copyfile(ENTRY_SRC, scripts / "run_py_entry.py")
    for rel, text in (("echo_args.py", ECHO), ("tests/echo_sub.py", ECHO), ("noop.py", NOOP),
                      ("exit_modes.py", EXIT_MODES), ("append_once.py", APPEND_ONCE)):
        (scripts / rel).write_text(text, encoding="utf-8")
    (scripts / "edge_target.py").write_text(EDGE_TARGET, encoding="utf-8")
    (scripts / "edge_sibling.py").write_text(EDGE_SIBLING, encoding="utf-8")
    (scripts / "bom_target.py").write_bytes(BOM_TARGET)
    (scripts / "latin1_target.py").write_bytes(LATIN1_TARGET)
    return root


def env_for(extra: dict | None = None) -> dict:
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", QA_FACTORY_PYTHON=sys.executable)
    env.pop("QA_FACTORY_LAUNCHER", None)
    env.update(extra or {})
    return env


def decode(proc) -> dict | None:
    try:
        return json.loads(proc.stdout)
    except ValueError:
        return None


def run_shell(root: Path, tail: str, *, stdin: bytes = b"{}", cwd: Path | None = None,
              env: dict | None = None):
    """install_smoke's form: ONE string, shell=True, the launcher quoted."""
    line = f'"{root / "hooks" / "run-py.cmd"}" {tail}'
    return subprocess.run(line, shell=True, input=stdin, capture_output=True, cwd=cwd or root,
                          env=env or env_for(), timeout=TIMEOUT)


def run_pwsh(root: Path, tail: str, *, stdin: bytes = b"{}", cwd: Path | None = None,
             env: dict | None = None):
    """codex.json's `commandWindows` form, with the root in CLAUDE_PLUGIN_ROOT."""
    command = '& "$env:CLAUDE_PLUGIN_ROOT/hooks/run-py.cmd" ' + tail + "; exit $LASTEXITCODE"
    return subprocess.run([PWSH, "-NoProfile", "-Command", command], input=stdin,
                          capture_output=True, cwd=cwd or root,
                          env=dict(env or env_for(), CLAUDE_PLUGIN_ROOT=str(root)), timeout=TIMEOUT)


def run_sh(root: Path, argv: list, *, stdin: bytes = b"{}", cwd: Path | None = None,
           env: dict | None = None):
    """The POSIX half: `sh run-py.cmd <script> <args>`. The launcher path is given with forward
    slashes, which both a POSIX shell and Git Bash take."""
    launcher = (root / "hooks" / "run-py.cmd").as_posix()
    return subprocess.run([SH, launcher, *argv], input=stdin, capture_output=True,
                          cwd=cwd or root, env=env or env_for(), timeout=TIMEOUT)


def text(proc) -> tuple:
    return (proc.stdout.decode("utf-8", "replace"), proc.stderr.decode("utf-8", "replace"))


def psq(arg: str) -> str:
    """One PowerShell single-quoted literal."""
    return "'" + arg.replace("'", "''") + "'"


# Each case: the argv the target must receive AFTER the script name, and, where the plain
# derivation (list2cmdline for a command line, single-quoted literals for PowerShell) is not the
# way a caller encodes that argument, the explicit text. `sh_win` False = not applicable to sh
# on Windows: why is named next to the case.
LONG_WORD = "w" * 40
CASES = [
    dict(name="plain words", argv=["alpha", "beta"]),
    dict(name="--set key=value is two elements, = intact", argv=["--set", "key=value"]),
    dict(name="comma and semicolon intact", argv=["a,b;c"]),
    dict(name="all three separators in one element", argv=["--set", "k=v,w;x=y"]),
    dict(name="quoted words with a space", argv=["x y", "two  spaces"]),
    # sh_win False: Git Bash's own runtime splits the Windows command line it is started with
    # differently from the C runtime (measured: `a\"b` arrives as `a\b`) - the launcher is not
    # in that path. On a POSIX host the list reaches sh exactly, so the case runs there.
    dict(name="an embedded double quote", argv=['a"b'], ps="'a" + chr(92) + '"b' + "'", sh_win=False),
    dict(name="a trailing backslash", argv=["C:" + chr(92) + "d" + chr(92)]),
    dict(name="a caret inside a quoted word", argv=["x^y z"]),
    dict(name="a quoted ampersand", argv=["a & b", "c&d e"]),
    dict(name="an exclamation mark", argv=["hello!", "!x! y"]),
    dict(name="a percent sign that names nothing", argv=["100%", "50% off"]),
    dict(name="non-ASCII text (Latin, symbol, Cyrillic)",
         argv=["caf\u00e9 \u2713 \u0436\u0443\u043a"]),
    dict(name="an empty argument in the middle keeps the rest", argv=["a", "", "b", "c"],
         win='a "" b c', ps="'a' '\"\"' 'b' 'c'"),
    dict(name="an empty argument first", argv=["", "x"], win='"" x', ps="'\"\"' 'x'"),
    dict(name="an empty argument last", argv=["x", ""], win='x ""', ps="'x' '\"\"'"),
    dict(name="two empty arguments in a row", argv=["", "", "tail"], win='"" "" tail',
         ps="'\"\"' '\"\"' 'tail'"),
    dict(name="--flag=value with spaces in the value", argv=["--notes=two words here"]),
]


def tails(case: dict) -> tuple:
    argv = case["argv"]
    win = case.get("win")
    if win is None:
        win = subprocess.list2cmdline(argv)
    ps = case.get("ps")
    if ps is None:
        ps = " ".join(psq(a) for a in argv)
    return win, ps


def norm(p) -> str:
    return os.path.normcase(os.path.normpath(str(p)))


def run_case(route: str, root: Path, case: dict, **kw):
    win, ps = tails(case)
    if route == "shell":
        return run_shell(root, "echo_args.py " + win, **kw)
    if route == "pwsh":
        return run_pwsh(root, "echo_args.py " + ps, **kw)
    return run_sh(root, ["echo_args.py", *case["argv"]], **kw)


def routes(root_cmd: Path, root_sh: Path | None) -> list:
    out = []
    if WIN:
        out += [(route, root_cmd) for route in WIN_ROUTES]
    if root_sh is not None:
        out.append(("sh", root_sh))
    return out


def argv_battery(label: str, route_list: list) -> None:
    for route, root in route_list:
        for case in CASES:
            if route == "sh" and WIN and case.get("sh_win") is False:
                continue
            proc = run_case(route, root, case)
            out = decode(proc)
            got = out["argv"] if out else None
            rec(f"{label}[{route}] {case['name']}", proc.returncode == 0 and got == case["argv"],
                  f"exit {proc.returncode}, expected {case['argv']!r}, got {got!r}, "
                  f"stderr {text(proc)[1][-300:]!r}")


def resolution_battery(label: str, route_list: list, base: Path) -> None:
    other = base / "other tools"
    other.mkdir(parents=True)
    (other / "abs_echo.py").write_text(ECHO, encoding="utf-8")
    decoy_cwd = base / "decoy cwd"
    (decoy_cwd / "tests").mkdir(parents=True)
    (decoy_cwd / "echo_args.py").write_text(DECOY, encoding="utf-8")
    (decoy_cwd / "tests" / "echo_sub.py").write_text(DECOY, encoding="utf-8")
    ghost = base / "no such dir" / "ghost.py"

    def call(route, root, script, args=("one", "--set", "k=v"), cwd=None, env=None):
        win = subprocess.list2cmdline([script, *args])
        ps = " ".join(psq(a) for a in (script, *args))
        if route == "shell":
            return run_shell(root, win, cwd=cwd, env=env)
        if route == "pwsh":
            return run_pwsh(root, ps, cwd=cwd, env=env)
        return run_sh(root, [script, *args], cwd=cwd, env=env)

    for route, root in route_list:
        tag = f"{label}[{route}]"
        scripts = root / "scripts"
        # a bare name resolves under scripts/
        out = decode(proc := call(route, root, "echo_args.py"))
        rec(f"{tag} a bare name resolves under scripts/",
              proc.returncode == 0 and out is not None
              and norm(out["argv0"]) == norm(scripts / "echo_args.py") and out["argv"] == ["one", "--set", "k=v"],
              f"{text(proc)}")
        # a subdirectory is kept
        out = decode(proc := call(route, root, "tests/echo_sub.py"))
        rec(f"{tag} a name with a subdirectory keeps it (scripts/tests/echo_sub.py)",
              proc.returncode == 0 and out is not None
              and norm(out["argv0"]) == norm(scripts / "tests" / "echo_sub.py"), f"{text(proc)}")
        if route != "sh":
            out = decode(proc := call(route, root, "tests" + chr(92) + "echo_sub.py"))
            rec(f"{tag} a backslash subdirectory keeps it too",
                  proc.returncode == 0 and out is not None
                  and norm(out["argv0"]) == norm(scripts / "tests" / "echo_sub.py"), f"{text(proc)}")
        # an absolute path that exists is used as given, with its own directory first on sys.path
        for shape, given in (("native", str(other / "abs_echo.py")),
                             ("forward slashes", (other / "abs_echo.py").as_posix())):
            out = decode(proc := call(route, root, given))
            rec(f"{tag} an absolute path that exists runs and gets its arguments ({shape})",
                  proc.returncode == 0 and out is not None and out["argv"] == ["one", "--set", "k=v"]
                  and norm(out["argv0"]) == norm(given) and norm(out["path0"]) == norm(other),
                  f"{text(proc)} {out}")
        # an absolute path that does not exist: exit 2, the path as given, no prefixed path
        given = str(ghost)
        proc = call(route, root, given)
        err = text(proc)[1]
        rec(f"{tag} an absolute path that does not exist exits 2 and names it as given",
              proc.returncode == 2 and f"run-py.cmd: script not found: {given}" in err,
              f"exit {proc.returncode} {err!r}")
        rec(f"{tag} the not-found message never carries a prefixed path",
              ("scripts" + os.sep + given[:2]) not in err and ("scripts/" + given[:2]) not in err,
              err)
        # a missing first argument: exit 1 with the launcher's own message, as before
        proc = (run_shell(root, "") if route == "shell" else
                run_pwsh(root, "") if route == "pwsh" else run_sh(root, []))
        rec(f"{tag} no script name exits 1 with the missing-script message",
              proc.returncode == 1 and "run-py.cmd: missing script name" in text(proc)[1],
              f"exit {proc.returncode} {text(proc)}")
        # a project file named like a script must NOT be the one that runs
        for script, expect in (("echo_args.py", scripts / "echo_args.py"),
                               ("tests/echo_sub.py", scripts / "tests" / "echo_sub.py")):
            out = decode(proc := call(route, root, script, cwd=decoy_cwd))
            rec(f"{tag} a file in the cwd named like {script} is not the one that runs",
                  proc.returncode == 0 and out is not None and "decoy" not in out
                  and norm(out["argv0"]) == norm(expect), f"{text(proc)}")
        # a bare name that exists nowhere under scripts/ fails, and never falls back to the cwd
        (decoy_cwd / "only_in_cwd.py").write_text(DECOY, encoding="utf-8")
        proc = call(route, root, "only_in_cwd.py", cwd=decoy_cwd)
        rec(f"{tag} a bare name present only in the cwd is not run",
              proc.returncode != 0 and not proc.stdout.strip(), f"exit {proc.returncode} {text(proc)}")
        (decoy_cwd / "only_in_cwd.py").unlink()


def exit_and_stdin_battery(label: str, route_list: list, base: Path) -> None:
    for route, root in route_list:
        tag = f"{label}[{route}]"
        for code in (0, 2):
            proc = call_echo(route, root, env=env_for({"ECHO_EXIT": str(code)}))
            rec_eq(f"{tag} the target's exit code {code} is the launcher's", proc.returncode, code)
        payload = json.dumps({"hook_event_name": "PreToolUse", "message": "Unicode: \u2713 \u0436",
                              "nested": {"a": [1, 2, {"b": "c d"}]}}).encode("utf-8")
        proc = call_echo(route, root, stdin=payload)
        out = decode(proc)
        rec(f"{tag} the stdin JSON arrives intact",
              out is not None and bytes.fromhex(out["stdin_hex"]) == payload, text(proc)[1])
        if route != "pwsh":
            # PowerShell hands a native command its own text encoding of the input; the raw-bytes
            # claim is the launcher's, so it is made on the routes that add no host between.
            raw = b'{"x": 1}\r\n\x00\xff\x1a end\n'
            proc = call_echo(route, root, stdin=raw)
            out = decode(proc)
            rec(f"{tag} stdin bytes (CRLF, NUL, 0xFF, Ctrl-Z) pass through untouched",
                  out is not None and bytes.fromhex(out["stdin_hex"]) == raw, text(proc)[1])
        proc = call_echo(route, root, script="exit_modes.py", env=env_for({"MODE": "raise"}))
        err = text(proc)[1]
        rec(f"{tag} a raising target prints its traceback and exits 1",
              proc.returncode == 1 and "RuntimeError: kaboom" in err and "Traceback" in err, err[-300:])
        proc = call_echo(route, root, script="exit_modes.py", env=env_for({"MODE": "text"}))
        rec(f"{tag} SystemExit with a string prints it and exits 1 (the interpreter's own rule)",
              proc.returncode == 1 and "boom message" in text(proc)[1], text(proc)[1][-200:])
        proc = call_echo(route, root, script="exit_modes.py", env=env_for({"MODE": "none"}))
        rec_eq(f"{tag} SystemExit(None) exits 0", proc.returncode, 0)


def edge_battery(label: str, route_list: list) -> None:
    """The target runs as a script: `__main__`, its own file, a sibling import, a dataclass and
    a pickled top-level function that need `sys.modules["__main__"]` to hold its globals, and a
    source read per PEP 263."""
    for route, root in route_list:
        tag = f"{label}[{route}]"
        proc = call_echo(route, root, script="edge_target.py", args=())
        out = decode(proc)
        expect = norm(root / "scripts" / "edge_target.py")
        rec(f"{tag} the target runs under `if __name__ == \"__main__\"` and reads its own __file__",
            proc.returncode == 0 and out is not None and out["name"] == "__main__"
            and norm(out["file"]) == expect, str(text(proc)))
        rec(f"{tag} the target imports a sibling module from its own directory",
            out is not None and out["sibling"] == "sibling-ok", str(text(proc)))
        rec(f"{tag} sys.modules['__main__'] is the module that holds the target's globals",
            out is not None and out["main_holds_globals"] is True
            and norm(out["main_file"]) == expect, str(text(proc)))
        rec(f"{tag} a dataclass and a pickled top-level function work in the target",
            out is not None and out["box"] == {"n": 3} and out["pickle_function"] is True
            and out["pickle_class"] is True, str(text(proc)))
        rec(f"{tag} __builtins__ is available to the target",
            out is not None and out["builtins"] is True, str(text(proc)))
        for script, what in (("bom_target.py", "a UTF-8 BOM"),
                             ("latin1_target.py", "a latin-1 coding line")):
            proc = call_echo(route, root, script=script, args=())
            out = decode(proc)
            rec(f"{tag} a source with {what} is read the way the interpreter reads it",
                proc.returncode == 0 and out is not None and out["text"] == "caf" + chr(233),
                str(text(proc)))


def call_echo(route, root, *, script="echo_args.py", stdin=b"{}", env=None, args=("x",)):
    if route == "shell":
        return run_shell(root, subprocess.list2cmdline([script, *args]), stdin=stdin, env=env)
    if route == "pwsh":
        return run_pwsh(root, " ".join(psq(a) for a in (script, *args)), stdin=stdin, env=env)
    return run_sh(root, [script, *args], stdin=stdin, env=env)


def marker_battery(root_cmd: Path, root_sh: Path | None, base: Path) -> None:
    if WIN:
        for route in WIN_ROUTES:
            proc = call_echo(route, root_cmd, env=env_for({"ECHO_CHILD": "1"}))
            out = decode(proc)
            rec(f"marker[{route}] through the cmd half VIA_CMD is True inside the target",
                  out is not None and out["via_cmd"] is True, text(proc))
            rec(f"marker[{route}] QA_FACTORY_LAUNCHER is absent from the target's os.environ",
                  out is not None and out["marker_env"] is None, str(out))
            rec(f"marker[{route}] a child process the target starts does not inherit it",
                  out is not None and out["child_marker"] == "None", str(out))
        # the variable must not outlive the launcher in the CALLER'S shell (setlocal)
        wrapper = base / "leak.cmd"
        wrapper.write_text("@echo off\r\ncall \"" + str(root_cmd / "hooks" / "run-py.cmd")
                           + "\" noop.py\r\necho LEAK=[%QA_FACTORY_LAUNCHER%]\r\n", encoding="ascii")
        proc = subprocess.run(f'"{wrapper}"', shell=True, capture_output=True, env=env_for(),
                              cwd=root_cmd, timeout=TIMEOUT)
        rec("marker the caller's shell does not keep QA_FACTORY_LAUNCHER after the launcher",
              "LEAK=[]" in text(proc)[0], text(proc)[0])
    if root_sh is not None:
        proc = call_echo("sh", root_sh, env=env_for({"ECHO_CHILD": "1"}))
        out = decode(proc)
        rec("marker[sh] through the POSIX half VIA_CMD is False and the variable is absent",
              out is not None and out["via_cmd"] is False and out["marker_env"] is None
              and out["child_marker"] == "None", text(proc))
    # direct python: the entry itself, no launcher
    root = root_sh or root_cmd
    entry = root / "scripts" / "run_py_entry.py"
    proc = subprocess.run([sys.executable, "-B", str(entry), "echo_args.py", "x"], input=b"{}",
                          capture_output=True, env=env_for({"ECHO_CHILD": "1"}), timeout=TIMEOUT)
    out = decode(proc)
    rec("marker[direct] run without the launcher VIA_CMD is False",
          out is not None and out["via_cmd"] is False and out["marker_env"] is None, text(proc))
    proc = subprocess.run([sys.executable, "-B", str(entry), "echo_args.py", "x"], input=b"{}",
                          capture_output=True,
                          env=env_for({"ECHO_CHILD": "1", "QA_FACTORY_LAUNCHER": "cmd"}),
                          timeout=TIMEOUT)
    out = decode(proc)
    rec("marker[direct] the marker set by a cmd half is read, and removed before the target runs",
          out is not None and out["via_cmd"] is True and out["marker_env"] is None
          and out["child_marker"] == "None", text(proc))
    # a target located OUTSIDE scripts/ still imports the module the launcher ran as __main__
    other = base / "elsewhere"
    other.mkdir(exist_ok=True)
    (other / "far_echo.py").write_text(ECHO, encoding="utf-8")
    proc = subprocess.run([sys.executable, "-B", str(entry), str(other / "far_echo.py")],
                          input=b"{}", capture_output=True,
                          env=env_for({"QA_FACTORY_LAUNCHER": "cmd"}), timeout=TIMEOUT)
    out = decode(proc)
    rec("marker[direct] `import run_py_entry` works from a target outside scripts/",
          out is not None and out["via_cmd"] is True and out["name"] == "__main__"
          and norm(out["path0"]) == norm(other), text(proc))


def entry_battery(root: Path) -> None:
    entry = root / "scripts" / "run_py_entry.py"
    proc = subprocess.run([sys.executable, "-B", str(entry)], input=b"", capture_output=True,
                          env=env_for(), timeout=TIMEOUT)
    rec("entry with no arguments exits 1 with the missing-script message",
          proc.returncode == 1 and "run-py.cmd: missing script name" in text(proc)[1], str(text(proc)))
    for mode, code, expect in (("int", "0", ""), ("int", "2", ""), ("none", "0", ""),
                               ("text", "0", "boom message"), ("raise", "0", "kaboom")):
        env = env_for({"MODE": mode, "CODE": code})
        direct = subprocess.run([sys.executable, "-B", str(root / "scripts" / "exit_modes.py")],
                                input=b"", capture_output=True, env=env, timeout=TIMEOUT)
        via = subprocess.run([sys.executable, "-B", str(entry), "exit_modes.py"], input=b"",
                             capture_output=True, env=env, timeout=TIMEOUT)
        rec(f"entry mirrors the interpreter for a script's exit ({mode} {code}): "
              f"{direct.returncode}",
              via.returncode == direct.returncode and expect in text(via)[1], str((direct.returncode, text(via))))
    proc = subprocess.run([sys.executable, "-B", str(entry), "echo_args.py", "a", "", "b"],
                          input=b"{}", capture_output=True, cwd=root.parent, env=env_for(),
                          timeout=TIMEOUT)
    out = decode(proc)
    rec("entry sets sys.argv = [script, *rest] and the script's directory first on sys.path",
          out is not None and out["argv"] == ["a", "", "b"]
          and norm(out["argv0"]) == norm(root / "scripts" / "echo_args.py")
          and norm(out["path0"]) == norm(root / "scripts") and out["name"] == "__main__",
          str(text(proc)))


def limit_battery(root_cmd: Path, base: Path, route: str) -> None:
    """Magnitude, and the limits the cmd route cannot carry, for ONE route. A line inside the
    limit arrives whole; one beyond it is refused and the target never runs with part of its
    argv."""
    base.mkdir(parents=True, exist_ok=True)
    py = f'"{sys.executable}" "{root_cmd / "hooks" / ".." / "scripts" / "run_py_entry.py"}" echo_args.py '
    orig = f'"{root_cmd / "hooks" / "run-py.cmd"}" echo_args.py '
    inside = "x" * (8000 - len(py))      # the line cmd expands ends up about 8000 characters
    beyond = "x" * (8300 - len(orig))    # the line the caller types is about 8300 characters
    marker = base / "ran.marker"
    for label, word, want_run in (("about 8000 characters (inside cmd's limit)", inside, True),
                                  ("about 8300 characters (beyond cmd's limit)", beyond, False)):
        if marker.exists():
            marker.unlink()
        env = env_for({"ECHO_MARKER": str(marker)})
        if route == "shell":
            proc = run_shell(root_cmd, f"echo_args.py {word}", env=env)
        else:
            proc = run_pwsh(root_cmd, f"echo_args.py {psq(word)}", env=env)
        out = decode(proc)
        if want_run:
            rec(f"limit[{route}] a command line of {label} arrives intact",
                proc.returncode == 0 and out is not None and out["argv"] == [word],
                f"exit {proc.returncode} {text(proc)[1][-200:]!r}")
        else:
            rec(f"limit[{route}] a command line of {label} exits non-zero and the target "
                "never runs with part of its argv",
                proc.returncode != 0 and not marker.exists() and out is None,
                f"exit {proc.returncode} marker={marker.exists()} {text(proc)}")
    # KNOWN LIMIT: a newline inside an argument. cmd.exe reads the command line up to the first
    # newline; what follows is not part of the command at all, before the launcher even starts.
    for shape, argv in (("plain", ["first", "line1\nline2", "last"]),
                        ("quoted", ["first", "line1 x\nline2 y", "last"])):
        proc = call_echo(route, root_cmd, args=argv)
        out = decode(proc)
        got = out["argv"] if out else []
        rec(f"known limit[{route}] a newline inside an argument cuts the command line there "
            f"({shape}): the text after it is lost",
            "line2" not in " ".join(got) and "line2 y" not in " ".join(got) and "last" not in got,
            f"got {got!r} exit {proc.returncode} {text(proc)[1][-200:]!r}")
    # KNOWN LIMIT: an UNQUOTED caret is cmd.exe's escape character; it is consumed by the outer
    # shell and again by the batch parser (measured: `a^b` -> `ab`, `a^^b` -> `ab`). Inside a
    # quoted word it survives (the "caret inside a quoted word" case above).
    proc = call_echo(route, root_cmd, args=["a^b", "c"])
    out = decode(proc)
    rec(f"known limit[{route}] an unquoted caret is consumed by cmd.exe (quote the word)",
        out is not None and out["argv"] == ["ab", "c"], str(text(proc)))
    if route == "shell":
        # KNOWN LIMIT: %NAME% of a DEFINED variable is expanded by the outer shell.
        env = env_for({"QA_LIMIT_PROBE": "expanded by the outer shell"})
        proc = run_shell(root_cmd, "echo_args.py %QA_LIMIT_PROBE%", env=env)
        out = decode(proc)
        rec("known limit[shell] %NAME% of a defined variable is expanded by the outer shell",
            out is not None and out["argv"] == ["expanded", "by", "the", "outer", "shell"],
            str(text(proc)))


# ---------------------------------------------------------------------------------------------
# The interpreter cache (SC1-5a, release 0.10.3). The cmd half used to run three `where` calls on
# every hook call (about a second, B-360). It now reads %LOCALAPPDATA%\qa-factory\python-path.txt,
# written by run_py_entry._remember_interpreter on the first call that found its interpreter by
# search. These cases pin: the file is built and used; every hostile or stale file falls back to
# the search; the door and the no-LOCALAPPDATA world are today's behaviour; the launcher adds
# nothing to a hook's stdout; a venv is never remembered; a cached interpreter that cannot start
# never turns the hooks off and never runs the target twice; parallel first calls and hostile
# directory names are safe. Labels used in the check names, against the spec's cases (spec 3.3):
#   a=1st  b=2nd  c=3rd(stale path)  d=4th(empty file, QA_PY)  d-env=5th(no LOCALAPPDATA)
#   e=6th(QA_FACTORY_PYTHON)  f=7th(stdout)  g=8th(venv)  h=9th(does not start)  i=10th(exit 1)
#   j=11th(exit 2)  k=12th(six parallel)  l=13th('a & b (x) %y%')  m=14th(2 lines, 1100 chars)
#   n=15th(inherited QA_FACTORY_PYCACHE); `unit ...` lines are the unit cases of 8th and 14th.
# ---------------------------------------------------------------------------------------------
CACHE_REL = Path("qa-factory") / "python-path.txt"
# A BASE interpreter to seed caches with: the one running this test, or the base of a venv.
GOOD_PY = (sys.executable if sys.prefix == sys.base_prefix
           else str(Path(sys.base_prefix) / "python.exe"))
SYSTEM32 = str(Path(os.environ.get("SystemRoot", r"C:\Windows")) / "system32")


def cache_env(local: Path | None, **extra) -> dict:
    """The environment of a cache case: NO QA_FACTORY_PYTHON (the cache lives on the path without
    it) and LOCALAPPDATA at a throwaway directory (None: not defined at all)."""
    env = env_for()
    env.pop("QA_FACTORY_PYTHON", None)
    if local is None:
        env.pop("LOCALAPPDATA", None)
    else:
        env["LOCALAPPDATA"] = str(local)
    env.update(extra)
    return env


def cache_file(local: Path) -> Path:
    return local / CACHE_REL


def seed_cache(local: Path, content: bytes) -> Path:
    path = cache_file(local)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def launch(root: Path, env: dict, script: str = "append_once.py", args=("x",)):
    return run_shell(root, subprocess.list2cmdline([script, *args]), env=env)


def fixed_ok(proc) -> bool:
    return proc.returncode == 0 and proc.stdout.decode("utf-8", "replace").strip() == FIXED_OUT


def cache_points_at_a_file(local: Path) -> bool:
    try:
        value = cache_file(local).read_bytes().decode("ascii")
    except (OSError, ValueError):
        return False
    return bool(value) and "\n" not in value and "\r" not in value and Path(value).is_file()


def tmp_leftovers(local: Path) -> list:
    folder = cache_file(local).parent
    return sorted(p.name for p in folder.glob("*.tmp")) if folder.is_dir() else []


def make_tripwire(base: Path, name: str) -> tuple:
    """A `.cmd` that records its own start. Named as the cached or inherited interpreter, it
    proves the launcher RAN that path (a cmd file called without `call` never returns, so the
    marker is the evidence, not the exit code)."""
    folder = base / name
    folder.mkdir(parents=True, exist_ok=True)
    marker = folder / "tripped"
    trip = folder / "trip.cmd"
    trip.write_text(f'@echo off\r\necho tripped> "{marker}"\r\n', encoding="ascii")
    return trip, marker


def run_lines(path: Path) -> int:
    return len(path.read_text().splitlines()) if path.exists() else 0


def cache_core_battery(root: Path, base: Path) -> None:
    """(a) (b) (c) (d) (d-env) (e) (f): built, used, stale, empty, no LOCALAPPDATA, door, stdout."""
    # (a) no cache: the run succeeds and leaves a file naming an existing interpreter
    local = base / "a"
    local.mkdir()
    proc = launch(root, cache_env(local))
    rec("cache(a) no cache file: the run succeeds, the file appears and names an existing file",
        fixed_ok(proc) and cache_points_at_a_file(local) and not tmp_leftovers(local),
        f"exit {proc.returncode} {text(proc)} file={cache_file(local).exists()}")
    # (b) the file that (a) built, with PATH cut to system32: `where` cannot be what finds Python
    before = cache_file(local).read_bytes() if cache_file(local).exists() else b""
    proc = launch(root, cache_env(local, PATH=SYSTEM32))
    rec("cache(b) with the cache and a PATH cut to system32 the run succeeds (no `where` needed)",
        fixed_ok(proc) and cache_file(local).read_bytes() == before and before != b"",
        f"exit {proc.returncode} {text(proc)}")
    # (c) the file names a path that does not exist: search, success, file rewritten
    local = base / "c"
    gone = str(base / "no such dir" / "python.exe")
    seed_cache(local, gone.encode("ascii"))
    proc = launch(root, cache_env(local))
    rec("cache(c) a cached path that does not exist: the search runs, the file is rewritten",
        fixed_ok(proc) and cache_points_at_a_file(local)
        and cache_file(local).read_bytes().decode("ascii") != gone,
        f"exit {proc.returncode} {text(proc)} file={cache_file(local).read_bytes()!r}")
    # (d) an empty file while the PARENT's environment holds QA_PY: the inherited value must not
    # be used (set /p on an empty file leaves the variable alone, so the launcher clears it first)
    local = base / "d"
    seed_cache(local, b"")
    trip, marker = make_tripwire(base, "trip-d")
    proc = launch(root, cache_env(local, QA_PY=str(trip)))
    rec("cache(d) an empty cache file with QA_PY inherited: searched, inherited value not run",
        fixed_ok(proc) and not marker.exists() and cache_points_at_a_file(local)
        and not text(proc)[1].strip(), f"exit {proc.returncode} {text(proc)} tripped={marker.exists()}")
    # (d-env) LOCALAPPDATA not defined: today's path, the target runs
    proc = launch(root, cache_env(None))
    rec("cache(d-env) LOCALAPPDATA not defined: today's path, the run succeeds",
        fixed_ok(proc), f"exit {proc.returncode} {text(proc)}")
    # (e) QA_FACTORY_PYTHON set: the cache is neither read nor written
    local = base / "e1"
    local.mkdir()
    proc = launch(root, cache_env(local, QA_FACTORY_PYTHON=GOOD_PY))
    rec("cache(e) QA_FACTORY_PYTHON set and no file: the run succeeds and no file is written",
        fixed_ok(proc) and not (local / "qa-factory").exists(), f"exit {proc.returncode} {text(proc)}")
    local = base / "e2"
    trip, marker = make_tripwire(base, "trip-e")
    seed_cache(local, str(trip).encode("ascii"))
    proc = launch(root, cache_env(local, QA_FACTORY_PYTHON=GOOD_PY))
    rec("cache(e) QA_FACTORY_PYTHON set and a file naming a tripwire: the file is not read",
        fixed_ok(proc) and not marker.exists()
        and cache_file(local).read_bytes() == str(trip).encode("ascii"),
        f"exit {proc.returncode} {text(proc)} tripped={marker.exists()}")
    # (f) stdout of the run that BUILDS the cache equals stdout of a run that USES it, byte for
    # byte, and both stderrs are empty: the launcher adds nothing to a hook's JSON stdout
    local = base / "f"
    local.mkdir()
    built = launch(root, cache_env(local))
    used = launch(root, cache_env(local))
    rec("cache(f) stdout of the building run equals stdout of the cached run, stderr of both empty",
        fixed_ok(built) and fixed_ok(used) and built.stdout == used.stdout
        and built.stderr == b"" and used.stderr == b"" and cache_points_at_a_file(local),
        f"built {built.stdout!r} {built.stderr!r}; used {used.stdout!r} {used.stderr!r}")


def argv_cached_battery(root: Path, base: Path) -> None:
    """The argv cases through the CACHED route (run-py.cmd, the `"%QA_PY%" "%ENTRY%" %*` line),
    which is the route a hook call takes in production since SC1-5a. env_for() always sets
    QA_FACTORY_PYTHON, so the argv battery proper runs through `:configured` only. The cache is
    seeded with GOOD_PY and PATH is cut to system32, so only the cached line can have found Python.
    Each case is compared with the same case through the configured route, byte for byte."""
    local = base / "argv-cache"
    seed_cache(local, GOOD_PY.encode("ascii"))
    for case in CASES:
        win = tails(case)[0]
        configured = run_shell(root, "echo_args.py " + win)
        cached = run_shell(root, "echo_args.py " + win, env=cache_env(local, PATH=SYSTEM32))
        out = decode(cached)
        got = out["argv"] if out else None
        rec(f"argv[cmd-cache] {case['name']}", cached.returncode == 0 and got == case["argv"],
            f"exit {cached.returncode}, expected {case['argv']!r}, got {got!r}, "
            f"stderr {text(cached)[1][-300:]!r}")
        rec(f"argv[cmd-cache] {case['name']}: same bytes as the configured route",
            configured.returncode == cached.returncode and configured.stdout == cached.stdout
            and configured.stderr == cached.stderr,
            f"configured {configured.stdout[-200:]!r} {configured.stderr[-100:]!r}; "
            f"cached {cached.stdout[-200:]!r} {cached.stderr[-100:]!r}")
    rec("argv[cmd-cache] the cache file was used all along (still the seeded path, no rebuild)",
        cache_file(local).read_bytes() == GOOD_PY.encode("ascii") and not tmp_leftovers(local),
        repr(cache_file(local).read_bytes()))


def cache_hostile_battery(root: Path, base: Path) -> None:
    """(h) (i) (j) (l) (m) (n): a cached interpreter that cannot start, exit codes 1 and 2, a
    hostile directory name, a garbage or oversized file, a stale QA_FACTORY_PYCACHE."""
    # (h) the cached file exists and cannot start: the search finds Python, the target runs ONCE
    local = base / "h"
    bad = base / "bad" / "python.exe"
    bad.parent.mkdir()
    bad.write_text("this is not an executable\n", encoding="ascii")
    seed_cache(local, str(bad).encode("ascii"))
    log = base / "h.log"
    proc = launch(root, cache_env(local, APPEND_TO=str(log)))
    rec("cache(h) a cached interpreter that does not start: searched, rewritten, target ran once",
        fixed_ok(proc) and run_lines(log) == 1 and cache_points_at_a_file(local)
        and cache_file(local).read_bytes().decode("ascii") != str(bad),
        f"exit {proc.returncode} {text(proc)} runs={run_lines(log)}")
    # (i) a working cache, the target exits 1: code 1, ONE run, the cache stays
    local = base / "i"
    seed_cache(local, GOOD_PY.encode("ascii"))
    log = base / "i.log"
    proc = launch(root, cache_env(local, APPEND_TO=str(log), APPEND_EXIT="1"))
    rec("cache(i) a working cache and a target exiting 1: exit 1, one run, the cache stays",
        proc.returncode == 1 and run_lines(log) == 1
        and cache_file(local).read_bytes() == GOOD_PY.encode("ascii"),
        f"exit {proc.returncode} {text(proc)} runs={run_lines(log)}")
    # (j) the same with exit 2 (the hook's refusal code is never probed)
    local = base / "j"
    seed_cache(local, GOOD_PY.encode("ascii"))
    log = base / "j.log"
    proc = launch(root, cache_env(local, APPEND_TO=str(log), APPEND_EXIT="2"))
    rec("cache(j) a working cache and a target exiting 2: exit 2, one run, the cache stays",
        proc.returncode == 2 and run_lines(log) == 1
        and cache_file(local).read_bytes() == GOOD_PY.encode("ascii"),
        f"exit {proc.returncode} {text(proc)} runs={run_lines(log)}")
    # (l) LOCALAPPDATA with & ( ) % and spaces: built and used, nothing of the tail executed
    local = base / "a & b (x) %y%"
    local.mkdir()
    built = launch(root, cache_env(local))
    used = launch(root, cache_env(local, PATH=SYSTEM32))
    rec("cache(l) LOCALAPPDATA 'a & b (x) %y%': the cache is built and used, no tail executed",
        fixed_ok(built) and fixed_ok(used) and cache_points_at_a_file(local)
        and built.stderr == b"" and used.stderr == b"" and not tmp_leftovers(local),
        f"built {text(built)}; used {text(used)}")
    # (m) a cache file of two lines: the first is used; the PATH is cut so only it can work
    local = base / "m1"
    two = (GOOD_PY + "\r\nnot a path\r\n").encode("ascii")
    seed_cache(local, two)
    proc = launch(root, cache_env(local, PATH=SYSTEM32))
    rec("cache(m) a cache file of two lines: the first line is the interpreter",
        fixed_ok(proc) and cache_file(local).read_bytes() == two, f"exit {proc.returncode} {text(proc)}")
    # a line longer than set /p keeps (1023): the cut path does not exist, so: search and rewrite
    local = base / "m2"
    seed_cache(local, b"x" * 1100)
    proc = launch(root, cache_env(local))
    rec("cache(m) a line of 1100 characters: searched and rewritten with a real path",
        fixed_ok(proc) and cache_points_at_a_file(local), f"exit {proc.returncode} {text(proc)}")
    # (n) QA_FACTORY_PYCACHE in the CALLER's environment is cleared by the launcher: a call on the
    # cached path writes nothing, and neither does a call without LOCALAPPDATA (the :resolve path)
    evil = base / "evil.txt"
    local = base / "n"
    seed_cache(local, GOOD_PY.encode("ascii"))
    proc = launch(root, cache_env(local, QA_FACTORY_PYCACHE=str(evil)))
    rec("cache(n) QA_FACTORY_PYCACHE inherited, call by the cached path: nothing is written",
        fixed_ok(proc) and not evil.exists(), f"exit {proc.returncode} {text(proc)}")
    proc = launch(root, cache_env(None, QA_FACTORY_PYCACHE=str(evil)))
    rec("cache(n) QA_FACTORY_PYCACHE inherited, no LOCALAPPDATA: nothing is written",
        fixed_ok(proc) and not evil.exists(), f"exit {proc.returncode} {text(proc)}")


def cache_venv_race_battery(root: Path, base: Path) -> None:
    """(g) a venv interpreter is never remembered; (k) six parallel first calls."""
    # (g) python on PATH is a venv's (no `py` anywhere on the cut PATH): the call succeeds, no file
    venv = base / "venv"
    made = subprocess.run([GOOD_PY, "-m", "venv", "--without-pip", str(venv)],
                          capture_output=True, timeout=TIMEOUT)
    scripts = str(venv / "Scripts")
    cut = scripts + os.pathsep + SYSTEM32
    if made.returncode != 0:
        rec("cache(g) a venv could be created for the case", False, str(text(made)))
    elif shutil.which("py", path=cut):
        print(f"SKIPPED cache(g): a `py` launcher sits on the cut PATH ({shutil.which('py', path=cut)}), "
              "it would resolve to the base interpreter and cache it")
    else:
        local = base / "g"
        local.mkdir()
        proc = launch(root, cache_env(local, PATH=cut))
        rec("cache(g) the interpreter found is a venv's: the call succeeds and no file is written",
            fixed_ok(proc) and not cache_file(local).exists(),
            f"exit {proc.returncode} {text(proc)} file={cache_file(local).exists()}")
    # (k) six parallel first calls: all succeed with exactly the target's stdout, one cache file
    # naming a working path, no `.tmp` left behind
    local = base / "k"
    local.mkdir()
    env = cache_env(local)
    with ThreadPoolExecutor(max_workers=6) as pool:
        procs = [f.result() for f in [pool.submit(launch, root, env) for _ in range(6)]]
    rec("cache(k) six parallel first calls: every exit 0 with exactly the target's stdout",
        all(fixed_ok(p) and p.stderr == b"" for p in procs),
        str([(p.returncode, p.stdout, p.stderr) for p in procs]))
    rec("cache(k) six parallel first calls: one cache file naming a working path, no .tmp left",
        cache_points_at_a_file(local) and not tmp_leftovers(local),
        f"file={cache_file(local).exists()} tmp={tmp_leftovers(local)}")


def pycache_direct_battery(root: Path, base: Path) -> None:
    """The entry run directly with the marker and QA_FACTORY_PYCACHE set (what the cmd half does
    on a search call): the variable never reaches the target, and a base interpreter writes."""
    target = base / "direct" / "python-path.txt"
    entry = root / "scripts" / "run_py_entry.py"
    env = env_for({"QA_FACTORY_LAUNCHER": "cmd", "QA_FACTORY_PYCACHE": str(target)})
    proc = subprocess.run([sys.executable, "-B", str(entry), "echo_args.py", "x"], input=b"{}",
                          capture_output=True, env=env, timeout=TIMEOUT)
    out = decode(proc)
    rec("pycache[direct] QA_FACTORY_PYCACHE is removed from the environment before the target runs",
        out is not None and out["pycache_env"] is None, str(text(proc)))
    rec("pycache[direct] the cache is written only by a base interpreter (and only to the named file)",
        target.is_file() == (sys.prefix == sys.base_prefix)
        and (not target.is_file() or target.read_bytes() == sys.executable.encode("ascii", "replace")
             or not sys.executable.isascii()),
        f"exists={target.is_file()} base={sys.prefix == sys.base_prefix}")
    env.pop("QA_FACTORY_LAUNCHER")
    other = base / "direct2" / "python-path.txt"
    env["QA_FACTORY_PYCACHE"] = str(other)
    proc = subprocess.run([sys.executable, "-B", str(entry), "echo_args.py", "x"], input=b"{}",
                          capture_output=True, env=env, timeout=TIMEOUT)
    rec("pycache[direct] without the cmd marker (the POSIX route) nothing is written",
        proc.returncode == 0 and not other.exists(), str(text(proc)))


def remember_unit_battery(base: Path) -> None:
    """Units of run_py_entry._remember_interpreter (cross-platform). They patch sys.prefix and
    sys.executable, which every other battery reads, so they run ALONE, after the pool."""
    import contextlib
    import importlib.util
    import io

    spec = importlib.util.spec_from_file_location("run_py_entry_unit", ENTRY_SRC)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    folder = base / "unit"
    folder.mkdir()
    exe = folder / "py.exe"
    exe.write_bytes(b"MZ")
    exe_nonascii = folder / ("py" + chr(233) + ".exe")
    exe_nonascii.write_bytes(b"MZ")

    @contextlib.contextmanager
    def facts(*, via=True, prefix="P", base_prefix="P", executable=str(exe)):
        saved = (mod.VIA_CMD, sys.prefix, sys.base_prefix, sys.executable)
        mod.VIA_CMD, sys.prefix, sys.base_prefix, sys.executable = via, prefix, base_prefix, executable
        try:
            yield
        finally:
            mod.VIA_CMD, sys.prefix, sys.base_prefix, sys.executable = saved

    def attempt(name, target, expect_written, **kw):
        out, err = io.StringIO(), io.StringIO()
        with facts(**kw), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                got = mod._remember_interpreter(str(target))
            except Exception as exc:  # the function must swallow everything
                got = repr(exc)
        written = Path(target).is_file()
        rec(f"unit {name}", got is expect_written and written is expect_written
            and out.getvalue() == "" and err.getvalue() == ""
            and not list(Path(target).parent.glob("*.tmp")),
            f"returned {got!r}, file {written}, stdout {out.getvalue()!r}, stderr {err.getvalue()!r}")

    n = [0]

    def fresh() -> Path:
        n[0] += 1
        return folder / f"c{n[0]}" / "python-path.txt"

    target = fresh()
    attempt("a base interpreter, through the cmd half: written", target, True)
    rec("unit the file holds the path alone, no line break", target.read_bytes() == str(exe).encode("ascii"),
        repr(target.read_bytes()))
    target = fresh()
    attempt("a venv (sys.prefix != sys.base_prefix) is never written", target, False, prefix="V")
    attempt("not through the cmd half (POSIX or direct): never written", fresh(), False, via=False)
    with facts():
        rec("unit an empty target writes nothing and returns False", mod._remember_interpreter("") is False)
    attempt("a non-ASCII sys.executable is never written", fresh(), False,
            executable=str(exe_nonascii))
    attempt("a sys.executable that is not a file is never written", fresh(), False,
            executable=str(folder / "missing.exe"))
    attempt("an empty sys.executable is never written", fresh(), False, executable="")
    # a target whose parent cannot be a directory: the failure is swallowed, nothing is left over
    blocker = folder / "blocker"
    blocker.write_text("a file, not a directory")
    attempt("a directory that cannot be created: swallowed, False", blocker / "sub" / "x.txt", False)
    # the temporary name carries the pid, and a refused replace leaves the old file and no .tmp
    target = fresh()
    target.parent.mkdir(parents=True)
    target.write_bytes(b"old")
    seen = []

    def refuse(src, dst):
        seen.append((str(src), str(dst)))
        raise PermissionError("another call is reading the file")

    real_replace = os.replace
    os.replace = refuse
    try:
        out, err = io.StringIO(), io.StringIO()
        with facts(), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            got = mod._remember_interpreter(str(target))
    finally:
        os.replace = real_replace
    rec("unit the temporary name is <target>.<pid>.tmp (parallel first calls cannot collide)",
        seen == [(f"{target}.{os.getpid()}.tmp", str(target))], str(seen))
    rec("unit a replace refused by a reader: False, silent, the old file stays, no .tmp left",
        got is False and target.read_bytes() == b"old" and not list(target.parent.glob("*.tmp"))
        and out.getvalue() == "" and err.getvalue() == "", f"{got!r} {target.read_bytes()!r}")
    # an existing cache is replaced whole
    attempt("an existing cache file is replaced", target, True)
    rec("unit the replaced file holds the new path whole", target.read_bytes() == str(exe).encode("ascii"),
        repr(target.read_bytes()))


def latency(root_new: Path, root_legacy: Path, base: Path) -> None:
    """Informational (FR-31, FR-55): nothing is asserted about the numbers. The launcher is on the
    path of every hook event, so what it adds is printed on every run. Four routes, labelled:
    the new launcher through the cache (what a hook pays since SC1-5a), the new launcher through
    the search (no LOCALAPPDATA: what every call paid before the cache, so the cache's gain is the
    difference), the new launcher through QA_FACTORY_PYTHON (env_for(): the route the argv cases
    take, no cache in it), and the legacy launcher through QA_FACTORY_PYTHON (the like-for-like
    baseline of the third). One untimed launch first: the first start of a script is dearer."""
    local = base / "latency-cache"
    seed_cache(local, GOOD_PY.encode("ascii"))

    def median_ms(root: Path, env: dict | None = None) -> float:
        run_shell(root, "noop.py", stdin=b"", env=env)
        samples = []
        for _ in range(10):
            t0 = time.perf_counter()
            proc = run_shell(root, "noop.py", stdin=b"", env=env)
            samples.append((time.perf_counter() - t0) * 1000)
            if proc.returncode != 0:
                return float("nan")
        return statistics.median(samples)

    print(f"LATENCY median of 10 launches of a no-op script: new launcher via the cache "
          f"{median_ms(root_new, cache_env(local)):.0f} ms, new launcher via the search "
          f"{median_ms(root_new, cache_env(None)):.0f} ms, new launcher via QA_FACTORY_PYTHON "
          f"{median_ms(root_new):.0f} ms, legacy launcher via QA_FACTORY_PYTHON "
          f"{median_ms(root_legacy):.0f} ms (informational, nothing asserted)")


def red_control(root_legacy: Path, base: Path) -> None:
    """The legacy launcher must FAIL the same battery where the defects were measured, or the
    battery would be passing on a launcher that never needed the fix."""
    other = base / "legacy other"
    other.mkdir()
    (other / "abs_echo.py").write_text(ECHO, encoding="utf-8")
    proc = run_shell(root_legacy, f'"{other / "abs_echo.py"}" one')
    rec("RED CONTROL legacy launcher cannot run an absolute script path", proc.returncode != 0,
          "the legacy launcher ran it - the absolute-path case is not testing the defect")
    proc = run_shell(root_legacy, "echo_args.py --set key=value")
    out = decode(proc)
    rec("RED CONTROL legacy launcher splits --set key=value",
        out is None or out["argv"] != ["--set", "key=value"],
          "the legacy launcher kept it - the = case is not testing the defect")
    proc = run_shell(root_legacy, 'echo_args.py a "" b c')
    out = decode(proc)
    rec("RED CONTROL legacy launcher loses everything after an empty argument",
          out is None or out["argv"] != ["a", "", "b", "c"],
          "the legacy launcher kept it - the empty-argument case is not testing the defect")


def main() -> None:
    base = Path(tempfile.mkdtemp(prefix="qa-launcher-argv-"))
    try:
        root_cmd = make_layout(base, "cmd", eol="\r\n") if WIN else None
        root_sh = make_layout(base, "sh", eol="\n") if SH else None
        if not SH:
            print("SKIPPED: no sh (the POSIX half of the launcher was not run)")
        if not WIN:
            print("SKIPPED: not Windows (the cmd and pwsh routes were not run)")
        elif not PWSH:
            print("SKIPPED: no pwsh (the commandWindows route was not run)")
        raw = LAUNCHER_SRC.read_bytes()
        crlf, lf = raw.count(b"\r\n"), raw.count(b"\n")
        check("the launcher and its entry exist in the package",
              LAUNCHER_SRC.is_file() and ENTRY_SRC.is_file(), f"{LAUNCHER_SRC} {ENTRY_SRC}")
        check("run-py.cmd keeps the polyglot first line and ONE line-ending form (all CRLF or all LF)",
              raw.startswith(b": << 'CMDBLOCK'") and (crlf == 0 or crlf == lf),
              f"CRLF lines {crlf}, LF {lf}")
        tasks = []
        for route, root in routes(root_cmd, root_sh):
            work = base / f"work-{route}"
            work.mkdir()
            tasks += [(argv_battery, "argv", [(route, root)]),
                      (resolution_battery, "path", [(route, root)], work),
                      (exit_and_stdin_battery, "io", [(route, root)], work),
                      (edge_battery, "edge", [(route, root)])]
        (base / "work-marker").mkdir()
        tasks += [(marker_battery, root_cmd, root_sh, base / "work-marker"),
                  (entry_battery, root_sh or root_cmd)]
        root_legacy = None
        if WIN:
            root_legacy = make_layout(base, "legacy", legacy=True)
            tasks += [(limit_battery, root_cmd, base / f"work-limit-{route}", route)
                      for route in WIN_ROUTES]
            tasks.append((red_control, root_legacy, base))
            for name, battery in (("core", cache_core_battery), ("hostile", cache_hostile_battery),
                                  ("argv", argv_cached_battery),
                                  ("venv-race", cache_venv_race_battery)):
                (base / f"work-cache-{name}").mkdir()
                tasks.append((battery, root_cmd, base / f"work-cache-{name}"))
        (base / "work-pycache").mkdir()
        tasks.append((pycache_direct_battery, root_sh or root_cmd, base / "work-pycache"))
        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = [pool.submit(collect, *task) for task in tasks]
            for future in futures:
                for name, ok, detail in future.result():
                    check(name, ok, detail)
        # alone, after the pool: these patch sys.prefix / sys.executable, which every battery reads
        (base / "work-unit").mkdir()
        for name, ok, detail in collect(remember_unit_battery, base / "work-unit"):
            check(name, ok, detail)
        if WIN:  # alone, after the batteries: a timing taken under load says nothing
            (base / "work-latency").mkdir()
            latency(root_cmd, root_legacy, base / "work-latency")
    finally:
        cleanup(base)
    finish("launcher argv")


if __name__ == "__main__":
    main()
