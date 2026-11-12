"""FB-32: a scheduler child must finish even when both output streams exceed pipe capacity - and a reader
that fails, or a pipe held after the exit, never holds the lease or the schedule.

`execute_schedule` starts each runner with PIPE on both streams. Before the fix it called `communicate()` only
once `poll()` reported an exit, so a child that printed more than the pipe buffer (64 KiB) blocked on its write
while the coordinator waited for its exit, and the lease stayed held forever. Now the readers run from the moment
of the launch, the group closes when the exit code AND the streams are known, a reader that dies with the child
still alive kills the child (F-5/M-3), and a pipe a grandchild keeps open after the exit waits one grace period.
Expectations come from the requirement (FB-32, t-958 section 5 edge 21 as rewritten by L-2 M-3), not from the
code's output. Every child here is a fixture script of this file; only fixture children are ever terminated.
"""
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import check, check_eq, finish  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import test_execution_scheduler as fixture  # noqa: E402  (importing runs none of its cases)
import execution_scheduler as scheduler  # noqa: E402

WATCHDOG_S = 12
BYTES_PER_STREAM = 2 * 1024 * 1024
root = fixture.ROOT


def summary(text: str) -> str:
    """The last line of a fixture child's stdout: a JSON object, which is what a finished run prints (M-4, t-1057 F1:
    a child that exits 0 with anything else last reads `unknown`, and these cases are about draining, not results)."""
    return '{"summary": "%s"}' % text


def runner(name: str, body: str) -> Path:
    path = root / name
    path.write_text(body, encoding="utf-8")
    return path


def execute(requests, script, watchdog=WATCHDOG_S, **kw):
    """(result, errors, finished_in_time, children): execute_schedule on a thread with a watchdog; fixture
    children still alive afterwards are terminated (a regression must not leave them running)."""
    real_popen = scheduler.subprocess.Popen
    children, result, errors = [], [], []

    def tracked(*args, **kwargs):
        child = real_popen(*args, **kwargs)
        children.append(child)
        return child

    def run():
        try:
            result.append(scheduler.execute_schedule({"requests": requests, "min_selected_instances": 2, "max_workers": 2},
                                                     root, script, **kw))
        except BaseException as error:  # noqa: BLE001 - reported as a FAIL line below
            errors.append(error)

    with patch.object(scheduler.subprocess, "Popen", side_effect=tracked):
        worker = threading.Thread(target=run, daemon=True)
        started = time.monotonic()
        worker.start()
        worker.join(watchdog)
        in_time = not worker.is_alive()
        elapsed = time.monotonic() - started
        for child in children:
            if child.poll() is None:
                child.terminate()
        worker.join(5)
    return (result[0] if result else {}), errors, in_time, children, elapsed


def leases() -> list:
    return scheduler.LeaseRegistry(root).snapshot()["leases"]


def kill_pid(path: Path) -> None:
    if path.exists():
        pid = path.read_text(encoding="utf-8").strip()
        subprocess.run(["taskkill", "/PID", pid, "/F"] if os.name == "nt" else ["kill", "-9", pid], capture_output=True)


def noisy_cases() -> None:
    noisy = runner("noisy_runner.py",
                   "import sys\n"
                   f"sys.stdout.write('x' * {BYTES_PER_STREAM} + '\\n{summary('stdout-final')}\\n')\nsys.stdout.flush()\n"
                   f"sys.stderr.write('y' * {BYTES_PER_STREAM} + '\\nstderr-final\\n')\nsys.stderr.flush()\n")
    result, errors, in_time, _children, _took = execute([fixture.request("noisy", "noisy-once")], noisy)
    group = (result.get("groups") or [{}])[0]
    check("a child printing 2 MiB on each stream completes without forced exit", in_time,
          "the scheduler waited for the exit before draining full child pipes")
    check("execute_schedule raised nothing", not errors, repr(errors))
    check_eq("the child's exit code is the ordinary zero", group.get("exit_code"), 0)
    check_eq("the stdout tail is the child's final stdout line", group.get("stdout_tail"), [summary("stdout-final")])
    check_eq("...and a child that ended with a JSON summary is `completed`", group.get("status"), "completed")
    check_eq("the stderr tail ends with the child's final stderr line", (group.get("stderr_tail") or [""])[-1], "stderr-final")
    check_eq("the tails are bounded lines: the huge line is cut and marked, not carried whole",
             [(len(row) < 300000, row.startswith("...")) for row in group.get("stderr_tail")[:1]], [(True, True)])
    check("a clean close carries no output_error", "output_error" not in group)
    check_eq("the lease is released after the exit is observed", leases(), [])

    result, errors, in_time, _children, _took = execute(
        [fixture.request("noisy-a", "noisy-par-a"), fixture.request("noisy-b", "noisy-par-b")], noisy)
    check("two parallel talkative children both complete inside the watchdog", in_time and not errors, repr(errors))
    check_eq("...both groups are closed with their own exit code and last line",
             sorted((g["status"], g["exit_code"], tuple(g["stdout_tail"])) for g in result.get("groups", [])),
             [("completed", 0, (summary("stdout-final"),))] * 2)
    check_eq("...and no lease is left", leases(), [])


def reader_failure_cases() -> None:
    """F-5 (a) / M-3: a reader that dies while the child is ALIVE kills the child, closes the group `failed`,
    releases the lease, and the schedule goes on."""
    stuck = runner("stuck_runner.py",
                   "import json, sys, time\nr = json.loads(open(sys.argv[2]).read())\n"
                   "if r['idempotency_key'].startswith('reader-dies'):\n    time.sleep(120)\n"
                   f"print('{summary('second group ran')}')\n")
    seen = []
    real_pump = scheduler._ChildOutput._pump

    class Broken:
        def readline(self, limit=-1):
            raise OSError("reader broke")

    def pump(self, name, stream):
        if not seen:
            seen.append(self)
        return real_pump(self, name, Broken() if seen[0] is self else stream)

    with patch.object(scheduler._ChildOutput, "_pump", pump):
        result, errors, in_time, children, took = execute(
            [fixture.request("rd-a", "reader-dies-a"), fixture.request("rd-b", "reader-b")], stuck, pipe_grace_s=5)
    check("a dead reader with a live child does not hang the schedule", in_time and not errors, repr(errors))
    by_key = {g["selected_ids"][0]: g for g in result.get("groups", [])}
    failed = by_key.get("rd-a", {})
    check_eq("the group is `failed` and says which reader failure", (failed.get("status"), failed.get("output_error")),
             ("failed", "OSError"))
    check_eq("...its tails are empty (nothing was read reliably)", (failed.get("stdout_tail"), failed.get("stderr_tail")), ([], []))
    check("...the exit code of the killed child is a fact, not None", failed.get("exit_code") is not None, str(failed))
    check("...and the child was killed (a child nobody reads would wait on a full pipe forever)",
          bool(children) and children[0].poll() is not None)
    check_eq("...the lease is released (the child is dead)", leases(), [])
    check("...and the lease release is not reported as failed", "lease_released" not in failed)
    check_eq("the other group still ran and closed normally", (by_key.get("rd-b", {}).get("status"), by_key.get("rd-b", {}).get("stdout_tail")),
             ("completed", [summary("second group ran")]))

    # The lease is released even when building the row raises (release is in a finally).
    ok = runner("ok_runner.py", "print('ok')\n")
    with patch.object(scheduler, "_child_row", side_effect=RuntimeError("row broke")):
        _result, errors, _in_time, _children, _took = execute([fixture.request("fin-a", "finally-a")], ok)
    check_eq("a row that cannot be built still releases its lease, and the failure is not swallowed",
             (bool(errors) and isinstance(errors[0], RuntimeError), leases()), (True, []))


def held_pipe_cases() -> None:
    """The child exits, a grandchild keeps the pipes open: the group waits the grace, closes with what was read, says so."""
    holder = runner("holder_runner.py",
                    "import json, subprocess, sys, pathlib\nr = json.loads(open(sys.argv[2]).read())\n"
                    "if r['idempotency_key'].startswith('holds'):\n"
                    "    p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])\n"
                    "    pathlib.Path('grandchild-' + r['idempotency_key'] + '.pid').write_text(str(p.pid))\n"
                    f"print('{summary('child-final')}')\n")
    try:
        result, errors, in_time, _children, took = execute(
            [fixture.request("hold-a", "holds-a"), fixture.request("hold-b", "plain-b")], holder, watchdog=40, pipe_grace_s=1)
        check("a grandchild holding the pipe does not hold the loop (the grace passes and the group closes)",
              in_time and not errors and took < 25, f"took {took:.1f} s {errors!r}")
        by_key = {g["selected_ids"][0]: g for g in result.get("groups", [])}
        held = by_key.get("hold-a", {})
        check_eq("the group is closed with the child's own exit code and last line",
                 (held.get("exit_code"), held.get("stdout_tail")), (0, [summary("child-final")]))
        check_eq("...and says the pipe was held after the exit", held.get("output_error"), "pipe held after exit")
        check_eq("the other group closed normally, with no output_error", ("output_error" in by_key.get("hold-b", {}), by_key["hold-b"]["status"]),
                 (False, "completed"))
        check_eq("the lease of the held group is released (the child is dead)", leases(), [])
    finally:
        for pid_file in root.glob("grandchild-*.pid"):
            kill_pid(pid_file)


def main() -> None:
    (root / "qa-factory" / "state").mkdir(parents=True, exist_ok=True)
    (root / "qa-factory" / "config.json").write_text("{}", encoding="utf-8")
    (root / "test.py").write_text("# fingerprint fixture", encoding="utf-8")
    noisy_cases()
    reader_failure_cases()
    held_pipe_cases()
    finish("test_scheduler_output_drain")


if __name__ == "__main__":
    main()
