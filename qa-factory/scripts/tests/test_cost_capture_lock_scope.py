#!/usr/bin/env python3
"""cost_capture.py refreshes the dashboard AFTER the cost writer lock is released.

`_capture` used to end with `refresh_project`, and every caller holds the per-session cost
writer lock around `_capture`: a dashboard render of any length held that lock, and a
concurrent capture of the same session (a `--debounced` PostToolUse, the Stop hook) either
gave up or spun on it. The same observer-stalls-the-writer defect as the story lock
(TP2-2406). Since 0.8.1 the Stop hook also POLLS that lock for `LOCK_WAIT_S`, so a render
inside it would stall every waiter for as long as the render takes.

The cases drive `_capture_with_wait`, the one place the lock is taken and released, the way `main`
calls it. The `--debounced` form makes one attempt and never renders (HF2-9: the render moved to the Stop form,
`test_cost_capture_hot_path.py`). A finished capture still leaves through `SystemExit(0)`. The Stop form renders
once, with its own lock free, whatever its capture did: a finished one, an unchanged one and a deferred one (the
holder's lock is still held there, which is the holder's, not the Stop's).
"""
import contextlib
import io
import json
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import SCRIPTS, check, check_eq, cleanup, finish, temp_project, use_project  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import cost_capture as C  # noqa: E402
import dashboard_refresh  # noqa: E402
import hooklib  # noqa: E402
from event_store import EventStore, StateConflict  # noqa: E402

SESSION = "fixture-lock-scope-session"
TASK = "TP1-LOCK"
NO_EXIT = "returned, no exit"


def write_transcript(path: Path):
    usage = {"input_tokens": 1000, "output_tokens": 50, "cache_read_input_tokens": 0,
             "cache_creation": {"ephemeral_5m_input_tokens": 0, "ephemeral_1h_input_tokens": 0}}
    row = {"type": "assistant", "isSidechain": False, "requestId": "req-1", "uuid": "u1",
           "timestamp": "2026-09-20T19:00:00Z",
           "message": {"model": "claude-sonnet-5", "usage": usage, "content": [
               {"type": "tool_use", "id": "toolu_marker", "name": "Write",
                "input": {"file_path": f"qa-factory/artifacts/{TASK}/understanding.md"}}]}}
    path.write_text(json.dumps(row) + "\n", encoding="utf-8")


class Probe:
    """A `refresh_project` stand-in: was the cost writer lock free when the refresh ran?"""

    def __init__(self, lock_root):
        self.lock_root = lock_root
        self.free, self.busy = 0, 0

    def __call__(self, project):
        try:
            with EventStore(self.lock_root).lock(wait_seconds=0):
                self.free += 1
        except StateConflict:
            self.busy += 1
        return {"status": "current"}


@contextlib.contextmanager
def probed(lock_root):
    original = dashboard_refresh.refresh_project
    probe = Probe(lock_root)
    dashboard_refresh.refresh_project = probe
    try:
        yield probe
    finally:
        dashboard_refresh.refresh_project = original


def drive(event, lock_root, debounced=False):
    """`_capture_with_wait` the way `main` calls it. Returns (outcome, exit code): a finished capture
    leaves through SystemExit, so its outcome is None and its code is the exit code; a run that
    returns has no exit (NO_EXIT). The 30 s window is `main`'s (`_debounce_window_open`, asked before the lock),
    so this driver never meets it; `sys.argv` carries the flag as the hook entry has it."""
    argv = sys.argv
    sys.argv = ["cost_capture.py", *(["--debounced"] if debounced else [])]
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            try:
                return C._capture_with_wait(dict(event), SESSION, lock_root, debounced), NO_EXIT
            except SystemExit as exc:
                return None, exc.code
    finally:
        sys.argv = argv


def main():
    root = temp_project("qa-cost-lock-scope-")
    old = hooklib._PROJECT_ROOT_CACHE
    wait_was = C.LOCK_WAIT_S
    try:
        use_project(root)
        transcript = root / "transcripts" / f"{SESSION}.jsonl"
        transcript.parent.mkdir()
        write_transcript(transcript)
        cost_dir = root / "qa-factory" / "state" / "cost"
        lock_root = cost_dir / ".writers" / SESSION
        out_path = cost_dir / f"{SESSION}.json"
        event = {"hook_event_name": "Stop", "session_id": SESSION,
                 "transcript_path": str(transcript), "cwd": str(root)}

        # --- the capture path (Stop hook): refresh after the lock, then the exit the hook always had ---
        with probed(lock_root) as probe:
            outcome, code = drive(event, lock_root)
        check("the capture wrote the session's cost file", out_path.is_file())
        check_eq("capture path: a finished capture leaves through SystemExit(0)", (outcome, code), (None, 0))
        check_eq("capture path: refresh_project ran once, with the cost writer lock free",
                 (probe.free, probe.busy), (1, 0))

        # --- a debounced capture over an unchanged input has nothing to write: it renders nothing and
        # just returns (no exit) ---
        with probed(lock_root) as probe:
            outcome, code = drive(event, lock_root, debounced=True)
        check_eq("debounced over an unchanged capture: nothing captured, no exit, nothing refreshed",
                 (outcome, code, probe.free, probe.busy), ("captured", NO_EXIT, 0, 0))

        # --- the debounced path: a captured run writes the file and exits 0, and renders NOTHING (by design,
        # HF2-9: it refreshed before): change the transcript so this run really captures ---
        with transcript.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"type": "user", "uuid": "u2", "timestamp": "2026-09-20T19:01:00Z",
                                     "message": {"role": "user", "content": "go on"}}) + "\n")
        with probed(lock_root) as probe:
            outcome, code = drive(event, lock_root, debounced=True)
        check_eq("debounced path: a captured run exits 0 as before", (outcome, code), (None, 0))
        check_eq("debounced path: a captured run renders nothing (by design: only the Stop form renders)",
                 (probe.free, probe.busy), (0, 0))

        # --- a held cost writer lock: debounced is one attempt and renders nothing; a waiting Stop polls, then
        # defers, and renders ONCE (by design: the dashboard is never older than the last Stop) ---
        release = threading.Event()
        acquired = threading.Event()

        def hold():
            with EventStore(lock_root).lock():
                acquired.set()
                release.wait(10)
        holder = threading.Thread(target=hold)
        holder.start()
        try:
            check("the other capture holds the cost writer lock", acquired.wait(5))
            started = time.monotonic()
            with probed(lock_root) as probe:
                outcome, code = drive(event, lock_root, debounced=True)
            elapsed = time.monotonic() - started
            check_eq("debounced over a held lock: one attempt, deferred, no exit, nothing refreshed",
                     (outcome, code, probe.free, probe.busy), ("deferred", NO_EXIT, 0, 0))
            check("and it returned at once", elapsed < 5.0, f"{elapsed:.2f}s")
            check("the debounced attempt left no pending marker (it is a sample)",
                  not C._pending_path(cost_dir, SESSION).exists())

            C.LOCK_WAIT_S = 0.3
            started = time.monotonic()
            with probed(lock_root) as probe:
                outcome, code = drive(event, lock_root)
            elapsed = time.monotonic() - started
            check_eq("busy for the whole wait: deferred, no exit, rendered once (the busy count is the HOLDER's lock, "
                     "not the Stop's: its own lock is not held, see test_cost_capture_hot_path K2)",
                     (outcome, code, probe.free + probe.busy), ("deferred", NO_EXIT, 1))
            check("the waiting capture polled for the wait before it gave up", 0.25 <= elapsed < 10.0,
                  f"{elapsed:.2f}s")
            check("and it left the pending marker the recapture reads",
                  C._pending_path(cost_dir, SESSION).is_file())
        finally:
            C.LOCK_WAIT_S = wait_was
            release.set()
            holder.join(10)
        C._pending_path(cost_dir, SESSION).unlink(missing_ok=True)

        # --- the recapture path ---
        with probed(lock_root) as probe:
            outcome = C.recapture_session(root, SESSION)
        check_eq("recapture recomputed the session", outcome["status"], "recomputed")
        check_eq("recapture path: refresh_project ran once, with the cost writer lock free",
                 (probe.free, probe.busy), (1, 0))
    finally:
        C.LOCK_WAIT_S = wait_was
        hooklib._PROJECT_ROOT_CACHE = old
        cleanup(root)
    finish("test_cost_capture_lock_scope")


if __name__ == "__main__":
    main()
