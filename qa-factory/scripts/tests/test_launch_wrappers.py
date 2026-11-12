#!/usr/bin/env python3
"""EP1-35: the launch of a command that may be a Windows `.cmd` wrapper, at the five report/probe places and the S5 run.

Pins: `node_ids.run_captured` (one bounded launcher: separate streams, `env=None` is the process environment, the tree is
killed at the limit, a missing head is the OS's own FileNotFoundError); `gate_preflight.run_probe` and
`Rehearsal._probe_reporter` over it (a timeout with a grandchild that holds the pipe returns inside `timeout + grace + 2`);
`CmdUnsafe` at each (`unreadable`, the "no report" move, `broken_run`); the "not found" sentence of `run_suite.run`.
A real `.cmd` shim is used on Windows; elsewhere the refusal is injected, because `cmd_unsafe` is `[]` off Windows by design."""
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from harness import check, check_eq, check_in, check_not_in, cleanup, finish, temp_project, use_project  # noqa: E402

import gate_preflight as GP  # noqa: E402
import node_ids as NI  # noqa: E402
import project_env as PE  # noqa: E402

NT = os.name == "nt"
GRACE_S = 10          # run_bounded's grace after the kill
HOLDER = ("import subprocess, sys, time\n"
          "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"   # the grandchild inherits the pipes
          "time.sleep(60)\n")


def holder_with_pid(pidfile: Path) -> str:
    """HOLDER that also writes the PID of its grandchild to `pidfile` (the tree-kill witness, t-555 F-7)."""
    return ("import subprocess, sys, time\n"
            "p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
            f"open({str(pidfile)!r}, 'w').write(str(p.pid))\n"
            "time.sleep(60)\n")


def pid_alive(pid: int) -> bool:
    if NT:
        shown = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True).stdout
        return f" {pid} " in shown
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def shim(folder: Path, name: str, marker: Path) -> Path:
    """An executable `name` in `folder` that records that it ran (the host's kind of launcher)."""
    folder.mkdir(parents=True, exist_ok=True)
    if NT:
        path = folder / (name + ".cmd")
        path.write_bytes(f'@echo off\r\necho ran> "{marker}"\r\necho shim-out\r\n'.encode("ascii"))
    else:
        path = folder / name
        path.write_text(f'#!/bin/sh\necho ran > "{marker}"\necho shim-out\n', encoding="utf-8")
        path.chmod(0o755)
    return path


def unsafe(token="a&b") -> "PE.CmdUnsafe":
    return PE.CmdUnsafe(token, "x.cmd")


def timed(fn):
    start = time.monotonic()
    try:
        return fn(), time.monotonic() - start
    except BaseException as exc:                           # noqa: BLE001 - the test reads what was raised
        return exc, time.monotonic() - start


def run_captured_cases(tmp: Path) -> None:
    py = sys.executable
    done = NI.run_captured([py, "-c", "import sys; sys.stdout.buffer.write(b'a\\r\\nb\\r\\n'); sys.stderr.write('e'); sys.exit(3)"],
                           str(tmp), None, 30)
    check_eq("run_captured: the code, stdout (CRLF -> LF) and stderr apart", (done.returncode, done.stdout, done.stderr), (3, "a\nb\n", "e"))
    got, _ = timed(lambda: NI.run_captured(["lw-no-such-program-xyz"], str(tmp), None, 10))
    check("run_captured: a missing head is the OS's own FileNotFoundError, not a BoundedRunError", isinstance(got, FileNotFoundError), repr(got))
    done = NI.run_captured([py, "-c", "import time; time.sleep(1)"], str(tmp), None, 20)
    check_eq("run_captured AT the limit: a command shorter than it returns its code", done.returncode, 0)
    got, took = timed(lambda: NI.run_captured([py, "-c", HOLDER], str(tmp), None, 2))
    check("run_captured BEYOND the limit: a grandchild holding the pipe -> TimeoutExpired", isinstance(got, subprocess.TimeoutExpired), repr(got))
    check(f"and it returns inside timeout + grace + 2 s ({took:.1f} s)", took < 2 + GRACE_S + 2, f"{took:.1f}")
    # F-7: the tree is DEAD, not only the clock respected (a `proc.kill()` of the head alone leaves the grandchild alive)
    pidfile = tmp / "grandchild.pid"
    got, _ = timed(lambda: NI.run_captured([py, "-c", holder_with_pid(pidfile)], str(tmp), None, 3))
    check("run_captured: the tree-kill run timed out", isinstance(got, subprocess.TimeoutExpired), repr(got))
    check("the grandchild's PID was written", pidfile.exists() and pidfile.read_text().strip().isdigit(), str(pidfile))
    grandchild = int(pidfile.read_text().strip())
    for _ in range(50):
        if not pid_alive(grandchild):
            break
        time.sleep(0.1)
    check("the grandchild is gone (no orphan survives the limit)", not pid_alive(grandchild), f"pid {grandchild} is still alive")
    # env=None is the process environment: a bare head found on THAT PATH is launched (Windows Popen cannot find a .cmd bare)
    marker = tmp / "env-none.txt"
    folder = tmp / "bin"
    shim(folder, "lwshim", marker)
    with mock.patch.dict(os.environ, {"PATH": str(folder) + os.pathsep + os.environ.get("PATH", "")}):
        got, _ = timed(lambda: NI.run_captured(["lwshim"], str(tmp), None, 30))
    check("env=None: the process PATH finds the bare wrapper and it runs",
          not isinstance(got, BaseException) and got.returncode == 0 and "shim-out" in got.stdout and marker.exists(), repr(got))
    # a refusal launches nothing
    marker2 = tmp / "never.txt"
    folder2 = tmp / "bin2"
    shim(folder2, "lwunsafe", marker2)
    env = dict(os.environ, PATH=str(folder2) + os.pathsep + os.environ.get("PATH", ""))
    if NT:
        got, _ = timed(lambda: NI.run_captured(["lwunsafe", "a&b"], str(tmp), env, 30))
        check("a .cmd wrapper with `a&b`: CmdUnsafe (an OSError) and nothing was launched", isinstance(got, PE.CmdUnsafe) and not marker2.exists(), repr(got))
    else:
        print("SKIP .cmd wrapper with a real shim: not Windows (cmd_unsafe is [] by design); the injected refusals below cover the callers")


def run_probe_cases(tmp: Path) -> None:
    py = sys.executable
    ok = GP.run_probe([py, "-c", "print('{\"result\": \"matched\"}')"], tmp, 30)
    check_eq("run_probe: one JSON line is the record", ok, {"record": {"result": "matched"}})
    got, took = timed(lambda: GP.run_probe([py, "-c", HOLDER], tmp, 2))
    check_eq("run_probe: a probe whose grandchild holds the pipe is `timed_out`, the tree killed", got, {"timed_out": True})
    check(f"run_probe: inside timeout + grace + 2 s ({took:.1f} s)", took < 2 + GRACE_S + 2, f"{took:.1f}")
    with mock.patch.object(PE, "checked_launch", side_effect=unsafe()):
        got = GP.run_probe(["x.cmd", "a&b"], tmp, 5)
    check("run_probe: CmdUnsafe is `unreadable` with the refusal's sentence", set(got) == {"unreadable"} and "cannot be passed safely" in got["unreadable"], repr(got))


def probe_reporter_cases(tmp: Path) -> None:
    py = sys.executable
    rehearsal = GP.Rehearsal.__new__(GP.Rehearsal)
    report = tmp / "report.xml"
    read = (0, "no report file was written", "no_file", [], "")
    with mock.patch.object(GP.Rehearsal, "_read_probe_report", return_value=read):
        got, took = timed(lambda: rehearsal._probe_reporter([py, "-c", HOLDER], tmp, 2, report, "junit-xml"))
        check_eq("_probe_reporter: a command whose grandchild holds the pipe is `timed_out`", got, {"timed_out": True})
        check(f"_probe_reporter: inside timeout + grace + 2 s ({took:.1f} s)", took < 2 + GRACE_S + 2, f"{took:.1f}")
        got = rehearsal._probe_reporter(["lw-no-such-program-xyz"], tmp, 10, report, "junit-xml")
        check_eq("_probe_reporter: a missing head is still `launcher_missing`", got, {"launcher_missing": True})
        got = rehearsal._probe_reporter([py, "-c", "import sys; print('o'); sys.stderr.write('e'); sys.exit(2)"], tmp, 30, report, "junit-xml",
                                        {"LW_VAR": "1"})
        check_eq("_probe_reporter: stdout and stderr are read apart, as before", (got["returncode"], got["stdout"], got["stderr"]), (2, "o\n", "e"))
        with mock.patch.object(PE, "checked_launch", side_effect=unsafe()):
            got = rehearsal._probe_reporter(["x.cmd", "a&b"], tmp, 5, report, "junit-xml")
    check_eq("_probe_reporter: CmdUnsafe is the existing `no report` move (reason class no_file), nothing new",
             {k: got.get(k) for k in ("tests", "reason_class", "tried", "fit", "returncode", "stdout", "stderr")},
             {"tests": 0, "reason_class": "no_file", "tried": [], "fit": None, "returncode": None, "stdout": "", "stderr": ""})
    check_in("and its `why` is the refusal's sentence, which names the token and a door", "the argument 'a&b' of this command cannot be passed safely", got["why"])
    check_in("the door: start the runner directly", "start the runner directly", got["why"])


def other_places_use_the_one_launcher(tmp: Path) -> None:
    import execution_request as ER
    import run_suite as RS
    sentinel = SimpleNamespace(returncode=0, stdout='{"result": "matched"}', stderr="")
    with mock.patch.object(NI, "run_captured", return_value=sentinel) as call, \
            mock.patch.object(RS, "probe_record", return_value={"x": 1}), mock.patch.object(RS, "acceptable_provenance", return_value=True):
        RS.probe_runtime({"argv": ["probe"], "cwd": str(tmp), "timeout_s": 7})
    check_eq("run_suite.probe_runtime goes through run_captured with env None", call.call_args.args, (["probe"], str(tmp), None, 7))
    with mock.patch.object(NI, "run_captured", return_value=sentinel) as call, \
            mock.patch.object(ER, "probe_record", return_value={"x": 1}), mock.patch.object(ER, "acceptable_provenance", return_value=True):
        ER.rehearsal_probe({"argv": ["probe"], "cwd": str(tmp), "timeout_s": 9})
    check_eq("execution_request.rehearsal_probe goes through run_captured with env None", (len(call.call_args.args), call.call_args.args[2:]),
             (4, (None, 9)))
    check_eq("and its cwd is the spec's", call.call_args.args[1], str(tmp))


def drive_run(root: Path, argv: list, label: str):
    """`run_suite.run` on `argv` for story T-1 of `root`: (exit code or None, stdout, summary, log text)."""
    import run_suite as RS
    use_project(root)
    story = root / "qa-factory" / "artifacts" / "T-1"
    story.mkdir(parents=True, exist_ok=True)
    (story / "pipeline.json").write_text(json.dumps({"ticket": "T-1", "stages": {}}), encoding="utf-8")
    args = SimpleNamespace(cmd=list(argv), task="T-1", label=label, verbose=True, tests=None, command_env=None, cwd=str(root),
                           timeout=60, profile_id="p", mine=None, job_store=None, job=None, job_id="", reporter="other", wait=False)
    out, code = io.StringIO(), None
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
        try:
            RS.run(args)
        except SystemExit as exc:
            code = exc.code
    ev = story / "evidence"
    logs = sorted(ev.glob(f"{label}-*.log"))
    summaries = sorted(ev.glob(f"{label}-*.json"))
    return (code, out.getvalue(), json.loads(summaries[-1].read_text(encoding="utf-8")) if summaries else {},
            logs[-1].read_text(encoding="utf-8") if logs else "")


def head_not_found_cases() -> None:
    """F-6 (t-555): ONE sentence for a head that was not found, true for each kind of head, each with a door."""
    plain = PE.head_not_found("npx")
    check_eq("head_not_found: a bare head was looked up on PATH with PATHEXT",
             plain, "`npx` was looked up on PATH with PATHEXT and not found; install it, or correct argv[0] of the profile")
    for head in ("./gradlew", "tools\\run.cmd", "/opt/x/bin/runner"):
        said = PE.head_not_found(head)
        check_in(f"head_not_found: `{head}` carries a folder, run as written", "carries a folder and is run as written", said)
        check_not_in(f"head_not_found: `{head}` was never looked up on PATH", "was looked up on PATH", said)
        check_in(f"head_not_found: `{head}` has a door", "correct argv[0] of the profile", said)
    for head in ("build.ps1", "BUILD.PS1"):
        said = PE.head_not_found(head)
        check_in(f"head_not_found: `{head}` is a script that cannot start directly, with the pwsh door", "start it with pwsh -File", said)
    check_in("head_not_found: a `.ps1` WITH a folder was run as written (the folder branch comes first: it is the truer fact)",
             "carries a folder and is run as written", PE.head_not_found("./build.ps1"))
    check_in("head_not_found: no head at all still gives a sentence", "`?`", PE.head_not_found(""))


def run_suite_cases() -> None:
    root = temp_project()
    try:
        with mock.patch.object(PE, "checked_launch", side_effect=unsafe()):
            code, out, summary, log = drive_run(root, ["x.cmd", "a&b"], "unsafe")
        check_eq("run_suite.run: CmdUnsafe is a broken_run, exit 127", (code, summary.get("execution_status")), (127, "broken_run"))
        check_in("its launch_error carries the refusal", "cannot be passed safely", summary.get("launch_error", ""))
        check_eq("the record keeps the profile's own argv", summary.get("command"), ["x.cmd", "a&b"])
        code, out, summary, log = drive_run(root, ["lw-no-such-program-xyz", "--flag"], "missing")
        check_eq("run_suite.run: a head that is not found stays the question to the person (exit 3), not a broken_run",
                 (code, json.loads(out.strip().splitlines()[-1]).get("status")), (3, "executor_unavailable"))
        check_in("the log says the checked fact", "was looked up on PATH with PATHEXT and not found", log)
        check_not_in("and not the old unverified claim", "not found in this session", log)
        check_in("with the door", "correct argv[0] of the profile", log)
        code, out, summary, log = drive_run(root, ["./lw-no-such-folder-prog"], "folder")
        check_in("F-6: a head with a folder says it was run as written, not looked up", "carries a folder and is run as written", log)
        check_not_in("F-6: and does not claim a PATH lookup it never made", "was looked up on PATH", log)
        if NT:
            marker = root / "ran.txt"
            folder = root / "bin"
            shim(folder, "lwrun", marker)
            with mock.patch.dict(os.environ, {"PATH": str(folder) + os.pathsep + os.environ.get("PATH", "")}):
                code, out, summary, log = drive_run(root, ["lwrun"], "bare")
                unsafe_code, _, unsafe_summary, _ = drive_run(root, ["lwrun", "a&b"], "cmdamp")
            check("run_suite.run: a bare .cmd head on PATH is launched (resolved), the record keeps the bare name",
                  marker.exists() and summary.get("command") == ["lwrun"], f"{code} {summary.get('command')} {log[:80]}")
            check_eq("run_suite.run: a real .cmd head with `a&b` is refused as broken_run", (unsafe_code, unsafe_summary.get("execution_status")),
                     (127, "broken_run"))
    finally:
        cleanup(root)


def main() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="lw-"))
    try:
        run_captured_cases(tmp)
        run_probe_cases(tmp)
        probe_reporter_cases(tmp)
        other_places_use_the_one_launcher(tmp)
        head_not_found_cases()
        run_suite_cases()
    finally:
        cleanup(tmp)
    finish("test_launch_wrappers")


if __name__ == "__main__":
    main()
