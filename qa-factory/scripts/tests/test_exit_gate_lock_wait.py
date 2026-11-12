#!/usr/bin/env python3
"""The exit gate's state lock under parallel S5 sessions (spec t-1937 3.3, node TR3-6; spec t-2148 part D, node TR4-2): it is an OS
byte lock on the lock file (event_store.take_file_lock), it waits 10 s, says so when the wait was used, and a lock that stays busy
RAISES - never "gate passed". A killed hook's leftover file does not block, and the file is never deleted. Busy is simulated by a held
OS lock on another handle. `_state_path` and the step are replaced; no subprocess."""
import contextlib
import io
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import SCRIPTS, check, check_eq, check_in, finish  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import event_store as ES  # noqa: E402
import exit_gate as EG  # noqa: E402


def with_state(run):
    folder = Path(tempfile.mkdtemp(prefix="eglock-"))
    path = folder / ".exit_gate_blocks.json"
    original = EG._state_path
    EG._state_path = lambda: path
    try:
        return run(path, path.with_suffix(path.suffix + ".lock"))
    finally:
        EG._state_path = original


def lock_wait_is_ten_seconds():
    check_eq("the wait is 1000 steps of 10 ms", (EG.LOCK_WAIT_STEPS, EG.LOCK_STEP_S), (1000, 0.01))


def busy_lock_released_late_is_waited_for():
    def run(path, lock):
        other = ES.take_file_lock(lock, 0.0)                                    # another hook's handle holds the OS lock
        threading.Timer(1.3, other.release).start()                             # past the old 1 s, well inside 10 s
        err = io.StringIO()
        started = time.time()
        with contextlib.redirect_stderr(err):
            data = EG._mutate_state(lambda d: d.update(done=True))
        return data, err.getvalue(), time.time() - started
    data, said, took = with_state(run)
    check("a lock freed after 1.3 s (the old wait would have failed) is waited for and the update is written", data.get("done") is True and took >= 1.0)
    check_in("... and the wait is printed", "exit gate state lock was busy", said)


def busy_lock_forever_raises_and_never_passes():
    def run(path, lock):
        other = ES.take_file_lock(lock, 0.0, purpose="a hook", record_holder=True)
        EG.LOCK_WAIT_STEPS = 20
        try:
            EG._mutate_state(lambda d: d.update(done=True))
            return None, path
        except RuntimeError as exc:
            return str(exc), path
        finally:
            EG.LOCK_WAIT_STEPS = 1000
            other.release()
    text, path = with_state(run)
    check("a lock that stays busy raises, naming the lock", text is not None and "remained busy" in text and ".lock" in text)
    check("... with the holder clause (a recorded holder is advice, never a pass)",
          text is not None and "held by process" in text and "if that process is gone the lock frees itself" in text, str(text))
    check("... and nothing was written (never read as a pass)", not path.exists())


def test_a_leftover_lock_file_of_a_dead_hook_does_not_block():
    """D3: the file of a killed hook stays (the old generation's O_EXCL file, or an OS lock file nobody holds): the update goes through
    at once, and the lock file is left in place (a lock file is never deleted)."""
    def run(path, lock):
        lock.write_text("held", encoding="utf-8")                               # a leftover with no holder
        err = io.StringIO()
        started = time.time()
        with contextlib.redirect_stderr(err):
            data = EG._mutate_state(lambda d: d.update(done=True))
        return data, err.getvalue(), time.time() - started, lock.exists()
    data, said, took, left = with_state(run)
    check_eq("a leftover lock file does not block: the update is written at once, nothing is printed, the file stays",
             (data.get("done"), said, took < 1.0, left), (True, "", True, True))


def free_lock_is_silent():
    def run(path, lock):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            EG._mutate_state(lambda d: d.update(done=True))
        return err.getvalue(), lock.exists(), lock.stat().st_size if lock.exists() else None
    said, left, size = with_state(run)
    check_eq("a free lock prints nothing and leaves the lock file (never deleted), cut back to its one byte", (said, left, size), ("", True, 1))


if __name__ == "__main__":
    lock_wait_is_ten_seconds()
    busy_lock_released_late_is_waited_for()
    busy_lock_forever_raises_and_never_passes()
    test_a_leftover_lock_file_of_a_dead_hook_does_not_block()
    free_lock_is_silent()
    finish("test_exit_gate_lock_wait")
