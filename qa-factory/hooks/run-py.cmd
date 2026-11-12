: << 'CMDBLOCK'
@echo off
REM Cross-platform polyglot launcher for qa-factory Python scripts.
REM On Windows: cmd.exe runs the batch portion and calls the Python interpreter.
REM On Unix: the shell interprets this file as a script (: is a no-op).
REM
REM Usage: run-py.cmd <script> [args...]
REM   script is a name under scripts/ (subdirectories kept: tests/x.py), or an absolute path to
REM   an existing file, which is used as given. A bare name is never looked up in the current
REM   directory. A missing absolute path exits 2 and says so.
REM Stdin is passed through untouched (hooks read their JSON event from stdin).
REM
REM Arguments: the RAW tail of the command line goes to scripts/run_py_entry.py, which resolves
REM the script and runs it in this same interpreter, so the target sees exactly what the caller
REM encoded. The launcher used to rebuild the list one argument at a time; batch splits an
REM unquoted argument at an equals sign, a comma or a semicolon before any loop runs, and the
REM loop stopped at the first empty argument (TP2-2406, defect M7).
REM
REM Marker: the interpreter is started with QA_FACTORY_LAUNCHER=cmd (set under setlocal, so it
REM does not leak into the caller's shell). run_py_entry reads it into VIA_CMD and removes it
REM from the environment before the target runs. The POSIX half does not set it.
REM
REM What the cmd route cannot carry (cmd.exe's own rules, applied before this file runs):
REM   - a newline inside an argument: cmd.exe cuts the command line at the first newline, so
REM     everything after it is lost. Multi-line text travels by file, never as an argument.
REM   - a percent-wrapped name of a DEFINED variable: the outer shell expands it first.
REM   - a command line beyond cmd.exe's limit of 8191 characters, counted AFTER this file puts
REM     the interpreter and entry paths in front of the tail: cmd.exe refuses it (non-zero exit,
REM     measured 1 or 255), the target is never started with part of its arguments.
REM   - an unquoted caret, ampersand, bar or angle bracket is the caller's shell syntax, not an
REM     argument (a bare caret is consumed: the word a-caret-b arrives as ab). Quote the word.
REM   test_launcher_argv.py pins each of these.

if "%~1"=="" (
    echo run-py.cmd: missing script name >&2
    exit /b 1
)

setlocal DisableDelayedExpansion
set "ENTRY=%~dp0..\scripts\run_py_entry.py"
set "QA_FACTORY_LAUNCHER=cmd"

REM Interpreter cache (SC1-5a): the search below (three `where` calls, about a second) is paid
REM once. The first call that finds an interpreter by search gets scripts/run_py_entry.py to
REM remember the BASE interpreter in %LOCALAPPDATA%\qa-factory\python-path.txt (the variable
REM QA_FACTORY_PYCACHE names the file; the entry removes it before the target runs); every
REM later call starts that path directly. The file is a hint, never a verdict: a missing,
REM empty or garbage file, or a path that does not exist, drops back to the search; a path
REM that exists but ends with an exit code other than 0 or 2 is probed with `-c pass`, and a
REM probe that fails deletes the file and repeats the call through the search (the target
REM never started, so nothing runs twice). Exit codes are compared as strings, never with
REM `if errorlevel` (NTSTATUS codes are negative). Nothing here prints to stdout. One exception,
REM on stderr: a cached path that cannot start (the file exists but is not an executable) makes
REM cmd print its own error line once, before the search; it cannot be silenced, because the
REM target's stderr on the same line is the hook's refusal channel, and the file is deleted then.
REM The door: delete the file, or set QA_FACTORY_PYTHON (the cache is then neither read nor
REM written). A venv interpreter is never remembered (the entry checks sys.prefix).
set "QA_FACTORY_PYCACHE="
set "QA_PY="
if defined QA_FACTORY_PYTHON goto configured
if not defined LOCALAPPDATA goto resolve
set "QA_PYCACHE=%LOCALAPPDATA%\qa-factory\python-path.txt"
if not exist "%QA_PYCACHE%" goto build
set /p QA_PY=<"%QA_PYCACHE%"
if not defined QA_PY goto drop
if not exist "%QA_PY%" goto drop
"%QA_PY%" "%ENTRY%" %*
set "QA_RC=%ERRORLEVEL%"
if "%QA_RC%"=="0" exit /b 0
if "%QA_RC%"=="2" exit /b 2
"%QA_PY%" -c "pass" <nul >nul 2>nul
if "%ERRORLEVEL%"=="0" exit /b %QA_RC%
:drop
del /f /q "%QA_PYCACHE%" >nul 2>nul
:build
set "QA_FACTORY_PYCACHE=%QA_PYCACHE%"
:resolve
where py >nul 2>nul
if %ERRORLEVEL% equ 0 goto pylauncher
where python >nul 2>nul
if %ERRORLEVEL% equ 0 goto pythonlauncher
where python3 >nul 2>nul
if %ERRORLEVEL% equ 0 goto python3launcher
echo run-py.cmd: no Python interpreter found on PATH >&2
exit /b 1
:configured
"%QA_FACTORY_PYTHON%" "%ENTRY%" %*
exit /b %ERRORLEVEL%
:pylauncher
py -3 "%ENTRY%" %*
exit /b %ERRORLEVEL%
:pythonlauncher
python "%ENTRY%" %*
exit /b %ERRORLEVEL%
:python3launcher
python3 "%ENTRY%" %*
exit /b %ERRORLEVEL%
CMDBLOCK

# Unix: run the entry with python3 (fall back to python); it resolves the script itself and
# the arguments travel as the caller's own "$@" (see the cmd half above for why).
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ENTRY="${SCRIPT_DIR}/../scripts/run_py_entry.py"
if [ -n "${QA_FACTORY_PYTHON:-}" ]; then
  exec "${QA_FACTORY_PYTHON}" "${ENTRY}" "$@"
fi
if command -v python3 >/dev/null 2>&1; then
  exec python3 "${ENTRY}" "$@"
fi
exec python "${ENTRY}" "$@"
