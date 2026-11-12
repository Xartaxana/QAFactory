#!/usr/bin/env python3
"""HF2-9 (CD1-14): `cost_capture` leaves the hot path.

Measured (t-080, a 150 MB factory session): a `--debounced` PostToolUse capture paid a full dashboard
render (26 to 42 s of a 44 to 67 s process), the 30 s window was asked INSIDE `_capture` after the whole cost
file was parsed, and the Stop capture held the host's turn. What this file pins:

- K1/K2: the debounced form never renders; the Stop form renders ONCE, with no lock of its own held, whatever
  its capture did (finished, unchanged, deferred); the early exits (foreign session, no transcript, project not
  onboarded) render nothing; K3 the one switch (`QA_FACTORY_SKIP_DASHBOARD_REFRESH`) silences the Stop render
  and its notice.
- K5/K6/E10/E16: the Stop writes a "started" marker AFTER the onboarding/ownership checks and BEFORE the lock; a
  killed Stop leaves it; a finished capture removes it; a lock give-up replaces it with "gave_up"; the reason text
  is chosen by `kind`, a marker without `kind` reads as "gave_up".
- K7/E7/E15: the catch-up of other sessions' markers (not live, not another project's, one attempt at the lock,
  an ordinary incremental capture that keeps pinned valuations), always before a render that no lock surrounds.
- K8 and the consequential-role inputs of `_debounce_window_open`: the window is a `stat` before the lock; its
  error direction is "capture later", never "lose".
- K10: no unit of usage is lost between a debounced run, three runs inside the window, and the next Stop.
- K12: `validate_artifacts.main` no longer renders. K13 (F-7, fixed in the fix round): a SubagentStop event of
  the Claude host never lowers the parent's file (requests, cost, main-transcript checkpoint); a subagent file
  outside `subagents/` is noted and the parent still captured; a Codex child (own `session_meta.id`) is still
  its own session.
- Catch-up cap: at most ONE session is caught up per Stop, the oldest marker first.
"""
import contextlib
import io
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import SCRIPTS, check, check_eq, check_in, check_not_in, cleanup, finish, temp_dir, temp_project, use_project  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import cost_capture as C  # noqa: E402
import dashboard_refresh  # noqa: E402
import hooklib  # noqa: E402
import metric_signals  # noqa: E402
import telemetry_capture  # noqa: E402
from event_store import EventStore  # noqa: E402
from test_cost_capture_lock_scope import NO_EXIT, Probe  # noqa: E402

ENV = {}
USAGE = {"input_tokens": 1000, "output_tokens": 50, "cache_read_input_tokens": 0,
         "cache_creation": {"ephemeral_5m_input_tokens": 0, "ephemeral_1h_input_tokens": 0}}
OLD_GAVE_UP = "a capture gave up on the lock at {at}: the transcript may hold requests the file lacks"
STARTED = ("a Stop capture started at {at} did not finish (still running or stopped): "
           "the transcript may hold requests the file lacks")


# ---------------------------------------------------------------- fixtures
def request_line(i):
    return json.dumps({"type": "assistant", "isSidechain": False, "requestId": f"req-{i}", "uuid": f"u{i}",
                       "timestamp": f"2026-09-20T19:{i % 60:02d}:00Z",
                       "message": {"model": "claude-sonnet-5", "usage": USAGE, "content": []}})


def append_requests(path, first, count):
    with Path(path).open("a", encoding="utf-8") as stream:
        for i in range(first, first + count):
            stream.write(request_line(i) + "\n")


def age(path, seconds=3600):
    stamp = time.time() - seconds
    os.utime(path, (stamp, stamp))


def give_activity(sid):
    """A story activity, so the session keeps one row per request (and scans incrementally)."""
    activities = ENV["root"] / "qa-factory" / "state" / "activities"
    activities.mkdir(parents=True, exist_ok=True)
    stamp = "2026-09-01T00:00:00Z"
    (activities / f"{sid}.json").write_text(json.dumps({
        "schema_version": 1, "session_id": sid,
        "activities": [{"activity_id": "act1", "type": "story", "task": "TP1-HOT", "start_event_id": "e1",
                        "start_time": stamp, "end_event_id": None, "end_time": None, "status": "open",
                        "segments": [{"segment_id": "seg1", "start_event_id": "e1", "start_time": stamp,
                                      "end_event_id": None, "end_time": None}]}],
        "active_stack": ["act1"], "processed_events": {}, "usage_completeness": "unknown"}), encoding="utf-8")


def new_session(name, n=3, factory=True, folder=None):
    sid = f"hp-{name}"
    directory = folder or ENV["work"]
    directory.mkdir(parents=True, exist_ok=True)
    transcript = directory / f"{sid}.jsonl"
    transcript.write_text("", encoding="utf-8")
    append_requests(transcript, 1, n)
    age(transcript)
    if factory:
        give_activity(sid)
    event = {"hook_event_name": "Stop", "session_id": sid, "transcript_path": str(transcript),
             "cwd": str(ENV["root"])}
    return sid, transcript, event


def lock_of(sid):
    return ENV["cost"] / ".writers" / sid


def cost_file(sid):
    return ENV["cost"] / f"{sid}.json"


def marker_of(sid):
    return C._read_pending(C._pending_path(ENV["cost"], sid))


def load(sid):
    return json.loads(cost_file(sid).read_text(encoding="utf-8"))


def requests_in(doc):
    return sum(v["requests"] for v in doc["by_model"].values())


@contextlib.contextmanager
def probed_many(*lock_roots):
    """`refresh_project` stand-ins, one `Probe` per lock: was each lock free when the render ran?"""
    original = dashboard_refresh.refresh_project
    probes = [Probe(root) for root in lock_roots]

    def render(project):
        for probe in probes:
            probe(project)
        return {"status": "current"}

    dashboard_refresh.refresh_project = render
    try:
        yield probes
    finally:
        dashboard_refresh.refresh_project = original


class Recorder:
    def __init__(self, real):
        self.real, self.calls, self.results = real, [], []

    def __call__(self, *args, **kwargs):
        self.calls.append(args)
        result = self.real(*args, **kwargs)
        self.results.append(result)
        return result


@contextlib.contextmanager
def recording(module, name):
    recorder = Recorder(getattr(module, name))
    with patch.object(module, name, recorder):
        yield recorder


def drive(event, sid, debounced=False):
    """`_capture_with_wait` the way `main` calls it: (outcome, exit code)."""
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        try:
            return C._capture_with_wait(dict(event), sid, lock_of(sid), debounced), NO_EXIT
        except SystemExit as exc:
            return None, exc.code


def run_main(event, debounced=False):
    """`cost_capture.main()` with this event on stdin: (exit code or NO_EXIT, stdout, stderr)."""
    argv, reader = sys.argv, C.read_event
    sys.argv = ["cost_capture.py", *(["--debounced"] if debounced else [])]
    C.read_event = lambda: dict(event)
    out, err = io.StringIO(), io.StringIO()
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                C.main()
                code = NO_EXIT
            except SystemExit as exc:
                code = exc.code
        return code, out.getvalue(), err.getvalue()
    finally:
        sys.argv, C.read_event = argv, reader


@contextlib.contextmanager
def held(sid):
    """Another capture of `sid` holds its lock (a thread; the OS lock is per handle)."""
    release, acquired = threading.Event(), threading.Event()

    def hold():
        with EventStore(lock_of(sid)).lock():
            acquired.set()
            release.wait(30)

    thread = threading.Thread(target=hold)
    thread.start()
    try:
        check(f"fixture: another capture holds the lock of {sid}", acquired.wait(5))
        yield
    finally:
        release.set()
        thread.join(10)


class OwnLocks:
    """How many capture locks of THIS process are held right now (the render must see none)."""

    def __init__(self):
        self.depth, self.real, self.at_render = 0, C._capture_lock, []

    @contextlib.contextmanager
    def lock(self, lock_root):
        with self.real(lock_root):
            self.depth += 1
            try:
                yield
            finally:
                self.depth -= 1

    @contextlib.contextmanager
    def watching(self):
        original = dashboard_refresh.refresh_project

        def render(project):
            self.at_render.append(self.depth)
            return {"status": "current"}

        dashboard_refresh.refresh_project = render
        with patch.object(C, "_capture_lock", self.lock):
            try:
                yield self
            finally:
                dashboard_refresh.refresh_project = original


# ---------------------------------------------------------------- K1, K2, K3
def part_render_sites():
    sid, transcript, event = new_session("render", factory=False)
    with probed_many(lock_of(sid)) as (probe,), recording(C, "_after_capture") as after:
        result = drive(event, sid, debounced=True)
    check_eq("K1: a debounced capture that finished leaves through SystemExit(0), renders nothing, prints no notice",
             (result, probe.free + probe.busy, len(after.calls)), ((None, 0), 0, 0))
    debounced_doc = load(sid)
    cost_file(sid).unlink()
    with probed_many(lock_of(sid)) as (probe,):
        stop_result = drive(event, sid)
    stop_doc = load(sid)
    skip = ("generated", "usage_as_of")
    check_eq("K1: the debounced document is the Stop document, field for field (only the stamps differ)",
             {k: v for k, v in debounced_doc.items() if k not in skip}, {k: v for k, v in stop_doc.items() if k not in skip})
    check_eq("K2: a Stop that finished leaves through SystemExit(0) and renders once, the lock free",
             (stop_result, probe.free, probe.busy), ((None, 0), 1, 0))
    with probed_many(lock_of(sid)) as (probe,):
        result = drive(event, sid)
    check_eq("K2 (M2): a Stop over an UNCHANGED capture renders once, the lock free",
             (result, probe.free, probe.busy), (("captured", NO_EXIT), 1, 0))

    sid2, transcript2, event2 = new_session("deferred")
    wait_was = C.LOCK_WAIT_S
    C.LOCK_WAIT_S = 0.3
    try:
        with held(sid2), OwnLocks().watching() as own:
            result = drive(event2, sid2)
    finally:
        C.LOCK_WAIT_S = wait_was
    check_eq("K2 (M3): a deferred Stop renders ONCE, with no lock of its own held (the holder's is not ours)",
             (result, own.at_render), (("deferred", NO_EXIT), [0]))
    check_eq("K2: ... and it left the 'gave_up' marker", (marker_of(sid2) or {}).get("kind"), "gave_up")
    sid3, transcript3, event3 = new_session("debounced-deferred")
    with held(sid3), probed_many(lock_of(sid3)) as (probe,):
        result = drive(event3, sid3, debounced=True)
    check_eq("K2: a deferred DEBOUNCED capture renders nothing and leaves no marker",
             (result, probe.free + probe.busy, marker_of(sid3)), (("deferred", NO_EXIT), 0, None))

    # early exits render nothing
    foreign_sid, foreign, foreign_event = new_session("foreign", folder=ENV["work"] / "projects" / "C--Elsewhere-else")
    gone_event = dict(event, transcript_path=str(ENV["work"] / "missing.jsonl"))
    with probed_many(lock_of(sid)) as (probe,):
        results = [drive(foreign_event, foreign_sid), drive(gone_event, sid)]
        with patch.object(C, "state_dir", return_value=ENV["bare"] / "qa-factory"):
            results.append(drive(event, sid))
    check_eq("K2: a foreign session, a missing transcript and a project that is not onboarded exit 0 and render nothing",
             (results, probe.free + probe.busy), ([(None, 0)] * 3, 0))

    # K3: the one switch
    sid4, transcript4, event4 = new_session("switch")
    flag = os.environ.get("QA_FACTORY_SKIP_DASHBOARD_REFRESH")
    os.environ["QA_FACTORY_SKIP_DASHBOARD_REFRESH"] = "1"
    try:
        with recording(metric_signals, "context") as notice, recording(dashboard_refresh, "refresh_project") as refresh:
            result = drive(event4, sid4)
    finally:
        if flag is None:
            os.environ.pop("QA_FACTORY_SKIP_DASHBOARD_REFRESH", None)
        else:
            os.environ["QA_FACTORY_SKIP_DASHBOARD_REFRESH"] = flag
    check_eq("K3: with QA_FACTORY_SKIP_DASHBOARD_REFRESH=1 a Stop writes the file, renders nothing and prints no notice",
             (result, cost_file(sid4).is_file(), [r.get("status") for r in refresh.results], len(notice.calls)),
             ((None, 0), True, ["skipped"], 0))


# ---------------------------------------------------------------- K5, K6, E5, E10, E16
KILLER = '''
import os, sys
sys.path.insert(0, {scripts!r})
import cost_capture as C
C._capture = lambda event: os._exit(9)      # the host cuts the async Stop off inside the capture
sys.argv = ["cost_capture.py"]
C.main()
'''


def run_killed(event, project):
    wrapper = ENV["work"] / "killed_stop.py"
    wrapper.write_text(KILLER.format(scripts=str(SCRIPTS)), encoding="utf-8")
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(project), PYTHONDONTWRITEBYTECODE="1")
    return subprocess.run([sys.executable, "-B", str(wrapper)], input=json.dumps(event), capture_output=True, text=True,
                          encoding="utf-8", errors="replace", cwd=str(project), env=env, timeout=120)


def part_markers():
    sid, transcript, event = new_session("killed")
    done = run_killed(event, ENV["root"])
    marker = marker_of(sid) or {}
    check_eq("K5 (M4): a Stop killed inside its capture (exit 9) leaves the 'started' marker, with every field",
             (done.returncode, marker.get("kind"), marker.get("transcript"), sorted(marker)),
             (9, "started", str(transcript), ["at", "at_epoch", "kind", "reason", "session_id", "transcript"]))
    reason = C._stale_reason({"has_factory_activity": True}, ENV["work"] / "none.json", marker)
    check_eq("K6 (M14): the killed Stop's marker is shown stale with the 'did not finish' text",
             reason, (True, STARTED.format(at=marker.get("at"))))
    check_eq("K6: a 'gave_up' marker keeps today's text verbatim",
             C._pending_reason({"kind": "gave_up", "at": "T"}), OLD_GAVE_UP.format(at="T"))
    check_eq("E16/K6: a marker without `kind` (written before the field) reads as 'gave_up'",
             C._pending_reason({"at": "T"}), OLD_GAVE_UP.format(at="T"))
    check_eq("K6: no time recorded", C._pending_reason({"kind": "started"}),
             STARTED.format(at="an unrecorded time"))
    with probed_many(lock_of(sid)):
        result = drive(event, sid)
    check_eq("K5: the next capture of the session (started after the marker) records the tail and removes it",
             (result, marker_of(sid), requests_in(load(sid))), ((None, 0), None, 3))
    # a capture that FINDS the file current removes the marker too
    C._write_pending(event, sid, transcript, "test", "started")
    with probed_many(lock_of(sid)):
        drive(event, sid)
    check_eq("K5: ... and so does a capture that finds the file current", marker_of(sid), None)

    # E10: a second Stop of a session whose lock is held waits, then replaces its own 'started' with 'gave_up'
    sid2, transcript2, event2 = new_session("overlap")
    wait_was = C.LOCK_WAIT_S
    C.LOCK_WAIT_S = 0.3
    try:
        with held(sid2), probed_many(lock_of(sid2)):
            code, out, err = run_main(event2)
    finally:
        C.LOCK_WAIT_S = wait_was
    check_eq("E10: two Stops of one session overlapping: the second defers, exit 0, and leaves 'gave_up' (not 'started')",
             (code, (marker_of(sid2) or {}).get("kind")), (NO_EXIT, "gave_up"))

    # E5 (M5): nothing is written for a project that is not onboarded, nor for a foreign session
    bare_event = dict(event, cwd=str(ENV["bare"]))
    with patch.object(C, "state_dir", return_value=ENV["bare"] / "qa-factory"):
        C._mark_started(bare_event, sid, transcript)
    check_eq("E5 (M5): no file under a project that is not onboarded", sorted(ENV["bare"].rglob("*")), [])
    foreign_sid, foreign, foreign_event = new_session("foreign-mark", folder=ENV["work"] / "projects" / "C--Elsewhere-else")
    C._mark_started(foreign_event, foreign_sid, foreign)
    check_eq("E5: no marker for a session opened above the project", marker_of(foreign_sid), None)
    done = subprocess.run([sys.executable, "-B", str(SCRIPTS / "cost_capture.py")], input=json.dumps(
        dict(event, cwd=str(ENV["bare"]))), capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=str(ENV["bare"]), timeout=120, env=dict(os.environ, CLAUDE_PROJECT_DIR=str(ENV["bare"]), PYTHONDONTWRITEBYTECODE="1"))
    written = sorted(p.name for p in ENV["bare"].rglob("*") if p.is_file())
    check("E5: the real hook process in a project that is not onboarded writes no marker and no cost file "
          "(only the lock file the hook has always created is tolerated)",
          done.returncode == 0 and set(written) <= {"events.lock"}, f"exit {done.returncode}, files {written}")


# ---------------------------------------------------------------- K7, E7, E15
def part_catch_up():
    pin_sid, pin_t, pin_event = new_session("k7pin")
    with probed_many(lock_of(pin_sid)):
        drive(pin_event, pin_sid)
    doc = load(pin_sid)
    rows = doc.get("requests") or []
    check_eq("K7 fixture: the factory session keeps one row per request", len(rows), 3)
    rows[0]["valuation"]["subtotal_usd"] = "123.456"
    cost_file(pin_sid).write_text(json.dumps(doc), encoding="utf-8")
    append_requests(pin_t, 4, 1)
    age(pin_t)
    C._leave_pending(pin_event, pin_sid, pin_t, "x")
    ok_sid, ok_t, ok_event = new_session("k7ok", factory=False)
    C._write_pending(ok_event, ok_sid, ok_t, "x", "started")
    big_sid, big_t, big_event = new_session("k7big")
    C._leave_pending(big_event, big_sid, big_t, "x")
    live_sid, live_t, live_event = new_session("k7live")
    os.utime(live_t)
    C._leave_pending(live_event, live_sid, live_t, "x")
    gone_sid, gone_t, gone_event = new_session("k7gone")
    gone_t.unlink()
    C._leave_pending(gone_event, gone_sid, gone_t, "x")
    par_sid, par_t, par_event = new_session("k7parent", folder=ENV["work"] / "projects" / "C--Elsewhere-else")
    C._leave_pending(par_event, par_sid, par_t, "x")
    busy_sid, busy_t, busy_event = new_session("k7busy")
    C._leave_pending(busy_event, busy_sid, busy_t, "x")
    main_sid, main_t, main_event = new_session("k7main")
    real_footprint = C.transcript_footprint

    def footprint(path):
        size, seen = real_footprint(path)
        return (200 * 1048576, seen) if Path(path).name == big_t.name else (size, seen)

    # The cap: ONE catch-up per Stop, the oldest marker first. The busy session's marker is the oldest of all,
    # and a busy lock is no catch-up (it does not use the turn); then pin, ok, big.
    base = time.time() - 7200
    for offset, other_sid in enumerate((busy_sid, pin_sid, ok_sid, big_sid)):
        stamped = marker_of(other_sid)
        stamped["at_epoch"] = base + offset
        C._pending_path(ENV["cost"], other_sid).write_text(json.dumps(stamped), encoding="utf-8")

    def recorded():
        return [name for name, sid in (("pin", pin_sid), ("ok", ok_sid), ("big", big_sid)) if marker_of(sid) is None]

    with held(busy_sid), patch.object(C, "transcript_footprint", footprint), \
            probed_many(lock_of(main_sid), lock_of(ok_sid), lock_of(pin_sid), lock_of(big_sid)) as probes:
        result = drive(main_event, main_sid)
        check_eq("K7 cap: three stale markers (and a busy older one) -> exactly ONE caught up on the first Stop, the oldest",
                 recorded(), ["pin"])
        drive(main_event, main_sid)
        check_eq("K7 cap: the second Stop catches up the next oldest, still only one", recorded(), ["pin", "ok"])
        drive(main_event, main_sid)
        check_eq("K7 cap: the third Stop catches up the last", recorded(), ["pin", "ok", "big"])
    check_eq("K7: the Stop's own capture is written first", (result, cost_file(main_sid).is_file()), ((None, 0), True))
    check_eq("K7/E15: a marker with NO cost file is caught up (a cold capture)",
             (cost_file(ok_sid).is_file(), marker_of(ok_sid), requests_in(load(ok_sid)) if cost_file(ok_sid).is_file() else None),
             (True, None, 3))
    pinned = load(pin_sid)
    check_eq("K7 (M11): the catch-up is the ordinary incremental capture: the pinned valuation survives, the new request is added",
             (marker_of(pin_sid), len(pinned["requests"]), pinned["requests"][0]["valuation"]["subtotal_usd"]),
             (None, 4, "123.456"))
    check_eq("E15: a transcript past the 64 MB recapture limit is caught up all the same (no size limit)",
             (cost_file(big_sid).is_file(), marker_of(big_sid)), (True, None))
    check_eq("K7 (M10): a LIVE transcript is left alone, marker kept, nothing written",
             (cost_file(live_sid).is_file(), (marker_of(live_sid) or {}).get("kind")), (False, "gave_up"))
    check_eq("K7: a marker whose transcript is gone stays", (cost_file(gone_sid).is_file(), bool(marker_of(gone_sid))), (False, True))
    check_eq("K7: a session opened above the project is not caught up", (cost_file(par_sid).is_file(), bool(marker_of(par_sid))), (False, True))
    check_eq("K7: a session whose lock is held is not waited for, its marker stays",
             (cost_file(busy_sid).is_file(), bool(marker_of(busy_sid))), (False, True))
    check_eq("E7: the one render ran after the catch-up with every capture lock free (own, caught-up, pinned, big)",
             [(p.free, p.busy) for p in probes], [(3, 0)] * 4)   # three Stops, three renders


# ---------------------------------------------------------------- the window
def part_window():
    sid, transcript, event = new_session("window")
    path = cost_file(sid)
    base = 1_700_000_000.0
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{}", encoding="utf-8")
    os.utime(path, (base, base))
    marks = {"29.9 s old": (base + 29.9, True), "exactly 30.0 s old": (base + 30.0, False), "30.1 s old": (base + 30.1, False),
             "brand new (0 s)": (base, True), "mtime in the FUTURE": (base - 5.0, False)}
    for label, (now, expected) in marks.items():
        check_eq(f"window: {label} -> {'skip' if expected else 'capture'}", C._debounce_window_open(path, now), expected)
    check_eq("window input 1: no file (a cold session) -> capture", C._debounce_window_open(path.with_name("no-such.json"), base), False)
    with patch.object(Path, "stat", side_effect=PermissionError("denied")):
        check_eq("window input 4: stat raises PermissionError -> capture", C._debounce_window_open(path, base), False)
    check_eq("window input 4: the path under a FILE (NotADirectoryError) -> capture",
             C._debounce_window_open(path / "x.json", base), False)
    for kind in ("gave_up", "started", None):
        pending = C._pending_path(ENV["cost"], sid)
        pending.write_text(json.dumps({"session_id": sid, "at_epoch": 1.0, **({"kind": kind} if kind else {})}), encoding="utf-8")
        check_eq(f"window input 5 (M9): a marker of kind {kind!r} overrides a fresh file -> capture",
                 C._debounce_window_open(path, base + 1.0), False)
        pending.unlink()
    check_eq("window: the control of input 5 - no marker, the same fresh file -> skip", C._debounce_window_open(path, base + 1.0), True)
    # input 6: a file rewritten by something that is not a capture (stale `generated`, fresh mtime) skips: "later"
    path.write_text(json.dumps({"generated": "2000-01-01T00:00:00+00:00"}), encoding="utf-8")
    check_eq("window input 6: fresh mtime over a stale `generated` skips (later: allowed direction)",
             C._debounce_window_open(path, time.time() + 1.0), True)

    # K8: main() asks the window BEFORE the lock, before any parse of the cost file
    sid2, transcript2, event2 = new_session("window-main")
    with probed_many(lock_of(sid2)):
        run_main(event2, debounced=True)
    text = cost_file(sid2).read_text(encoding="utf-8")
    with patch.object(json, "loads", wraps=json.loads) as loads, recording(C, "_capture_with_wait") as waits, \
            recording(C, "_capture_lock") as locks, probed_many(lock_of(sid2)) as (probe,):
        code, out, err = run_main(event2, debounced=True)
    parsed = sum(1 for call in loads.call_args_list if call.args and call.args[0] == text)
    check_eq("K8 (M6): a debounced run inside the window: returns, no lock, no wait, ZERO parses of the cost file, no marker, no render",
             (code, len(waits.calls), len(locks.calls), parsed, marker_of(sid2), probe.free + probe.busy),
             (NO_EXIT, 0, 0, 0, None, 0))
    with held(sid2), recording(C, "_capture_with_wait") as waits:
        code, out, err = run_main(event2, debounced=True)
    check_eq("K8: with the lock HELD by another capture the outcome is still the window's (not 'deferred', no marker)",
             (code, len(waits.calls), marker_of(sid2)), (NO_EXIT, 0, None))
    age(cost_file(sid2))
    with held(sid2), recording(C, "_capture_with_wait") as waits, probed_many(lock_of(sid2)):
        run_main(event2, debounced=True)
    check_eq("K8 control: an aged file and a held lock DO reach the lock (and defer)", waits.results, ["deferred"])
    # input 7: the Stop form does not read the window
    sid3, transcript3, event3 = new_session("window-stop")
    with probed_many(lock_of(sid3)):
        run_main(event3, debounced=True)
        append_requests(transcript3, 4, 2)
        code, out, err = run_main(event3)
    check_eq("window input 7 / E6: a Stop over a FRESH file still captures (the window is the debounced form's)",
             (code, requests_in(load(sid3))), (0, 5))


# ---------------------------------------------------------------- K10
def part_no_loss():
    sid, transcript, event = new_session("noloss", n=3)
    with probed_many(lock_of(sid)):
        run_main(event, debounced=True)
        append_requests(transcript, 4, 5)
        with recording(C, "_capture_with_wait") as waits:
            for _ in range(3):
                run_main(event, debounced=True)
        check_eq("K10: three debounced runs inside the window capture nothing", len(waits.calls), 0)
        run_main(event)
    doc = load(sid)
    check_eq("K10: after the next Stop the document holds every request of the transcript (8), one row each",
             (requests_in(doc), len(doc["requests"]), marker_of(sid)), (8, 8, None))


# ---------------------------------------------------------------- K12, K13
def part_validate_artifacts():
    import validate_artifacts
    note = ENV["root"] / "qa-factory" / "state" / "hot-path-note.md"
    note.write_text("a note\n", encoding="utf-8")
    signals = ENV["root"] / "qa-factory" / "state" / "metric-signals.json"
    signals.write_text(json.dumps({"signals": [{"id": "SIG-1", "status": "open", "evaluation": "e", "title": "a title",
                                                "current": 1, "baseline": 2, "sample_size": 3, "next_action": "look"}]}),
                       encoding="utf-8")
    event = {"hook_event_name": "PostToolUse", "tool_name": "Write", "cwd": str(ENV["root"]),
             "tool_input": {"file_path": str(note), "content": "a note\n"}}
    out = io.StringIO()
    with patch.object(validate_artifacts, "read_event", lambda: dict(event)), recording(dashboard_refresh, "refresh_project") as refresh, \
            contextlib.redirect_stdout(out):
        try:
            validate_artifacts.main()
            code = NO_EXIT
        except SystemExit as exc:
            code = exc.code
    check_eq("K12: validate_artifacts on a Write under qa-factory/ exits 0 and renders NOTHING", (code, len(refresh.calls)), (0, 0))
    # K6 (SC1-4b, F-3 (a)): the synchronous hook of every Write/Edit no longer re-tells the open signals.
    check_not_in("K6: ... and it prints no metric signal (SIG-1 stays in metric-signals.json)", "SIG-1", out.getvalue())
    check_not_in("K6: ... nor the heading of the notice", "Recorded metric signals", out.getvalue())
    hinted = io.StringIO()
    with patch.object(validate_artifacts, "read_event", lambda: dict(event)), \
            patch.dict(validate_artifacts.NEXT_STEPS, {note.name: "next: HOT-PATH-HINT"}), contextlib.redirect_stdout(hinted):
        try:
            validate_artifacts.main()
        except SystemExit:
            pass
    check_in("K6: the next-step hint of the written file is still printed", "next: HOT-PATH-HINT", hinted.getvalue())
    check_not_in("K6: ... and the signal is still absent beside it", "SIG-1", hinted.getvalue())
    # The control of the absence above: the same signals file DOES reach the model where it is meant to (the Stop capture).
    stop_out = io.StringIO()
    with patch.object(dashboard_refresh, "refresh_project", lambda project: {"status": "current"}), contextlib.redirect_stdout(stop_out):
        C._after_capture({"hook_event_name": "Stop", "cwd": str(ENV["root"])})
    check_in("K6 control: the Stop capture still prints the notice from the same metric-signals.json", "SIG-1", stop_out.getvalue())


# ---------------------------------------------------------------- K5 (SC1-4b)
class MaintainProbe:
    """Stands in for `telemetry_capture.maintain_dir`: what ran before it, whether the session's cost lock and the
    cost file were in the state the price needs, and then the real pass (so a Stop test also sees a real merge)."""

    def __init__(self, sid, trace, real, raises=False):
        self.sid, self.trace, self.real, self.raises = sid, trace, real, raises
        self.calls, self.lock_free, self.cost_written = 0, [], []

    def __call__(self, directory, **kwargs):
        self.calls += 1
        self.trace.append("maintain")
        try:
            with EventStore(lock_of(self.sid)).lock():
                self.lock_free.append(True)
        except Exception:  # noqa: BLE001 - StateConflict: the session lock is held
            self.lock_free.append(False)
        self.cost_written.append(cost_file(self.sid).is_file())
        if self.raises:
            raise RuntimeError("the pass broke")
        return self.real(directory, **kwargs)


@contextlib.contextmanager
def maintenance_watched(sid, raises=False):
    """Patch `maintain_dir` with a probe and `_after_capture` with a tracer (the dashboard render stubbed, as above)."""
    trace, real_after = [], C._after_capture
    probe = MaintainProbe(sid, trace, telemetry_capture.maintain_dir, raises)

    def traced_after(event):
        trace.append("after")
        real_after(event)

    with probed_many(lock_of(sid)), patch.object(telemetry_capture, "maintain_dir", probe), patch.object(C, "_after_capture", traced_after):
        yield probe, trace


def price_keys(doc):
    return {k: doc.get(k) for k in ("requests", "orchestrator", "agents", "total_cost_usd", "by_model") if k in doc}


def part_telemetry_maintenance():
    """K5 (SC1-4b): the telemetry pass runs on Stop (and on SubagentStop, F-11), once, AFTER the dashboard and notice,
    with the cost lock free and the cost file already written; never in a PostToolUse sample, never inside `_capture`."""
    tdir = ENV["root"] / "qa-factory" / "state" / "telemetry"
    post = {"hook_event_name": "PostToolUse"}

    sid, transcript, event = new_session("tm-post")
    with maintenance_watched(sid) as (probe, trace):
        result = drive(dict(event, **post), sid, debounced=True)
    check_eq("K5: a PostToolUse sample (debounced) captures and does NOT run the telemetry pass",
             (result, probe.calls, trace), ((None, 0), 0, []))

    sid, transcript, event = new_session("tm-sub")
    with maintenance_watched(sid) as (probe, trace):
        result = drive(dict(event, hook_event_name="SubagentStop"), sid, debounced=True)
    check_eq("K5 (F-11): a SubagentStop (same debounced form) runs the pass once, the cost lock free, the cost file written",
             (result, probe.calls, probe.lock_free, probe.cost_written), ((None, 0), 1, [True], [True]))

    sid, transcript, event = new_session("tm-stop")
    with maintenance_watched(sid) as (probe, trace):
        result = drive(event, sid)
    check_eq("K5: a Stop runs the pass ONCE, after `_after_capture`, the cost lock free, the cost file already written",
             (result, probe.calls, trace, probe.lock_free, probe.cost_written), ((None, 0), 1, ["after", "maintain"], [True], [True]))

    sid, transcript, event = new_session("tm-unchanged")
    with probed_many(lock_of(sid)):
        drive(event, sid)
    with maintenance_watched(sid) as (probe, trace):
        result = drive(event, sid)
    check_eq("K5: a Stop over an UNCHANGED capture (outcome 'captured') runs the pass once as well",
             (result, trace), (("captured", NO_EXIT), ["after", "maintain"]))

    sid, transcript, event = new_session("tm-deferred")
    wait_was = C.LOCK_WAIT_S
    C.LOCK_WAIT_S = 0.3
    try:
        with held(sid), maintenance_watched(sid) as (probe, trace):
            result = drive(event, sid)
    finally:
        C.LOCK_WAIT_S = wait_was
    check_eq("K5: a DEFERRED Stop (the cost lock was not got) runs the pass once, after `_after_capture`",
             (result, probe.calls, trace), (("deferred", NO_EXIT), 1, ["after", "maintain"]))

    sid, transcript, event = new_session("tm-capture")
    with maintenance_watched(sid) as (probe, trace):
        C._capture(dict(event))
    check_eq("K5: `_capture` itself (the recapture and the catch-up call it) no longer runs the pass", (probe.calls, trace), (0, []))

    sid, transcript, event = new_session("tm-broken")
    with maintenance_watched(sid, raises=True) as (probe, trace):
        result = drive(event, sid)
    check_eq("K5: a pass that raises does not fail the Stop, and the cost file is written",
             (result, probe.calls, cost_file(sid).is_file()), ((None, 0), 1, True))

    # P18: the maintenance cannot change the price record. The same session, the same transcript, once with the pass
    # replaced by nothing and once with the real one: the price keys are equal.
    sid, transcript, event = new_session("tm-price", n=5)
    with probed_many(lock_of(sid)), patch.object(telemetry_capture, "maintain_dir", lambda directory, **kw: {"ran": False}):
        drive(event, sid)
    without = price_keys(load(sid))
    cost_file(sid).unlink()
    with probed_many(lock_of(sid)):
        drive(event, sid)
    check_eq("K5 (P18): the price record is equal, by its price keys, with the real pass and without it",
             price_keys(load(sid)), without)
    check("K5 (P18): ... and it holds the five requests (the fixture is not empty)", requests_in(load(sid)) == 5)

    # A session that died without a Stop: its closed per-process files are merged by the next Stop of ANY session.
    dead = tdir / "hook-777.jsonl"
    live = tdir / "hook-778.jsonl"
    for path, tag in ((dead, "dead"), (live, "live")):
        telemetry_capture.append(path, telemetry_capture.envelope(event_id=tag + ":start", phase="start", span_kind="hook", source="t"))
        telemetry_capture.append(path, telemetry_capture.envelope(event_id=tag + ":end", phase="end", span_kind="hook", source="t",
                                                                 duration_ms=1.0))
    age(dead, 7200)
    sid, transcript, event = new_session("tm-dead")
    with probed_many(lock_of(sid)):
        drive(dict(event, **post), sid, debounced=True)
    check_eq("K5: a PostToolUse sample leaves the dead session's file where it is", dead.is_file(), True)
    with probed_many(lock_of(sid)):
        cost_file(sid).unlink()
        drive(event, sid)
    merged = sorted(p.name for p in tdir.glob("hook-merged-*.jsonl"))
    check_eq("K5: the next Stop (another session) merged the dead session's closed file into a daily one",
             (dead.is_file(), len(merged)), (False, 1))
    check_eq("K5: ... and left the file of a process that wrote seconds ago (inside the quiet window)", live.is_file(), True)
    daily = (tdir / merged[0]).read_text(encoding="utf-8") if merged else ""
    check_in("K5: ... with its lines in the daily file", "dead:end", daily)


def part_telemetry_dispatch_end():
    """K5 (B-1, F-11, through `main`): a SubagentStop runs the pass in EVERY debounced form - the capture ran, the 30 s window
    was open (no capture at all), the cost lock was another capture's (`deferred`) - and a PostToolUse sample runs it in none.
    Plus F-8: a dashboard refresh that raises never skips the pass of a Stop."""
    sub = {"hook_event_name": "SubagentStop"}
    post = {"hook_event_name": "PostToolUse"}

    sid, transcript, event = new_session("tm-win-sub")
    with probed_many(lock_of(sid)):
        run_main(dict(event, **post), debounced=True)          # a sample wrote the cost file: the window is open
    check("fixture: the window is open (cost file younger than 30 s)", C._debounce_window_open(cost_file(sid), time.time()))
    with maintenance_watched(sid) as (probe, trace), recording(C, "_capture_with_wait") as waits:
        code, _out, _err = run_main(dict(event, **sub), debounced=True)
    check_eq("K5 (B-1 a): a SubagentStop inside the window captures nothing and runs the pass ONCE, the cost lock free",
             (code, len(waits.calls), probe.calls, probe.lock_free), (NO_EXIT, 0, 1, [True]))

    age(cost_file(sid))
    with held(sid), maintenance_watched(sid) as (probe, trace), recording(C, "_capture_with_wait") as waits:
        code, _out, _err = run_main(dict(event, **sub), debounced=True)
    check_eq("K5 (B-1 b): a SubagentStop whose cost lock is another capture's is 'deferred' and runs the pass ONCE",
             (code, waits.results, probe.calls), (NO_EXIT, ["deferred"], 1))

    with maintenance_watched(sid) as (probe, trace), recording(C, "_capture_with_wait") as waits:
        code, _out, _err = run_main(dict(event, **sub), debounced=True)
    check_eq("K5 (B-1 c, control): a SubagentStop that does capture still runs the pass ONCE (the capture site)",
             (code, len(waits.calls), probe.calls), (NO_EXIT, 1, 1))

    # the negative rows: a PostToolUse sample runs no pass in any of the three states (kills a mutant that tests `debounced`)
    for label, aged, holds in (("window open", False, False), ("window closed", True, False), ("lock held", True, True)):
        sid, transcript, event = new_session("tm-win-post-" + label.replace(" ", "-"))
        with probed_many(lock_of(sid)):
            run_main(dict(event, **post), debounced=True)
        if aged:
            age(cost_file(sid))
        with maintenance_watched(sid) as (probe, trace):
            with held(sid) if holds else contextlib.nullcontext():
                run_main(dict(event, **post), debounced=True)
        check_eq(f"K5 (B-1 d): a PostToolUse sample ({label}) runs NO pass", (probe.calls, trace), (0, []))

    sid, transcript, event = new_session("tm-refresh-raises")
    boom_calls = []

    def boom(_event):
        boom_calls.append(1)
        raise ValueError("a malformed config.json")

    with maintenance_watched(sid) as (probe, trace), patch.object(C, "_after_capture", boom):
        raised = None
        try:
            drive(event, sid)
        except ValueError as exc:
            raised = type(exc).__name__
    check_eq("K5 (F-8): a refresh that raises still lets the pass run ONCE, the cost file is written, and the error is not hidden",
             (raised, len(boom_calls), probe.calls, probe.lock_free, cost_file(sid).is_file()), ("ValueError", 1, 1, [True], True))


def subagent_stop(name, place):
    """A parent session captured once, then a Claude SubagentStop (`--debounced`) whose `agent_transcript_path` is a
    subagent file: `place` = "outside" (a folder that is not the parent's `subagents/`) or "inside". Returns
    (parent's document before, after, main-transcript key, subagent file, stderr)."""
    sid, transcript, event = new_session(name, n=4)
    with probed_many(lock_of(sid)):
        drive(event, sid)
    before = load(sid)
    if place == "inside":
        sub = transcript.parent / transcript.stem / "subagents" / "agent-sub.jsonl"
        sub.parent.mkdir(parents=True, exist_ok=True)
    else:
        sub = ENV["work"] / f"agent-{name}.jsonl"
    sub.write_text("", encoding="utf-8")
    append_requests(sub, 40, 2)
    age(cost_file(sid))
    stop = {"hook_event_name": "SubagentStop", "session_id": sid, "transcript_path": str(transcript),
            "agent_transcript_path": str(sub), "agent_type": "qa-factory:qa-automator", "cwd": str(ENV["root"])}
    with probed_many(lock_of(sid)):
        _code, _out, err = run_main(stop, debounced=True)
    return sid, before, load(sid), str(transcript.resolve()), sub, err


def part_subagent_stop():
    """K13 (F-7, fixed): a Claude SubagentStop event carries `agent_transcript_path` (the subagent) and the parent's
    `session_id`; the session's transcript stays the PARENT's. The parent's totals never shrink and its
    main-transcript checkpoint is never replaced by another file's."""
    sid, before, after, main_key, sub, err = subagent_stop("subagent", "outside")
    check("K13: SubagentStop does not lower the parent's request count (F-7)", requests_in(after) >= requests_in(before),
          f"{requests_in(before)} -> {requests_in(after)}")
    check("K13: ... nor its total cost (P18)", after["total_cost_usd"] >= before["total_cost_usd"],
          f"{before['total_cost_usd']} -> {after['total_cost_usd']}")
    check("K13: the parent's main-transcript checkpoint survives", main_key in (after.get("scan_checkpoints") or {}),
          f"checkpoints: {sorted((after.get('scan_checkpoints') or {}))}")
    check("K13: ... and it is the ONLY file the capture replaced it with (no other file took its place)",
          set(after.get("scan_checkpoints") or {}) == {main_key}, f"checkpoints: {sorted((after.get('scan_checkpoints') or {}))}")
    check_in("K13 (outside subagents/): the stray subagent file is NAMED in a note", str(sub), err)
    check_in("K13 (outside subagents/): ... and the parent is captured from its own transcript", "captured from its own transcript", err)
    check_eq("K13: the captured session is the parent (no other cost file was written)",
             sorted(p.name for p in ENV["cost"].glob("hp-subagent*.json")), ["hp-subagent.json"])

    sid, before, after, main_key, sub, err = subagent_stop("subin", "inside")
    check("K13 (inside subagents/): the parent's requests never shrink and the main checkpoint survives",
          requests_in(after) >= requests_in(before) and main_key in (after.get("scan_checkpoints") or {}),
          f"{requests_in(before)} -> {requests_in(after)}, checkpoints: {sorted((after.get('scan_checkpoints') or {}))}")
    check_eq("K13 (inside subagents/): the file is the parent's own sibling: no note", "outside" in err, False)
    check("K13 (inside subagents/): the capture reads the sibling (its checkpoint is the parent's)",
          str(sub.resolve()) in (after.get("scan_checkpoints") or {}), f"checkpoints: {sorted((after.get('scan_checkpoints') or {}))}")

    # A Codex child names its own session in its first row: it IS the session and is captured as its own file.
    parent_sid, parent_t, _event = new_session("codexparent", n=2)
    child = ENV["work"] / "child-rollout.jsonl"
    child.write_text(json.dumps({"type": "session_meta", "payload": {"id": "hp-codexchild", "parent_thread_id": parent_sid}})
                     + "\n", encoding="utf-8")
    with probed_many(lock_of("hp-codexchild")):
        code, _out, err = run_main({"hook_event_name": "SubagentStop", "session_id": parent_sid,
                                    "transcript_path": str(parent_t), "agent_transcript_path": str(child),
                                    "agent_type": "default", "cwd": str(ENV["root"])})
    check_eq("K13 (Codex form): a child with its own session id is captured as ITS session, the parent's file untouched",
             (cost_file("hp-codexchild").is_file(), cost_file(parent_sid).is_file()), (True, False))
    check_eq("K13 (Codex form): no note about a stray file", "outside" in err, False)

    # No agent file at all, or one that is gone: the parent is captured as the plain event it is.
    plain_sid, plain_t, plain = new_session("plainsub", n=2)
    run_main({**plain, "hook_event_name": "SubagentStop", "agent_transcript_path": str(ENV["work"] / "no-such-agent.jsonl")},
             debounced=True)
    check_eq("K13: an agent file that does not exist -> the parent is still captured (2 requests)",
             requests_in(load(plain_sid)) if cost_file(plain_sid).is_file() else None, 2)

    # The parent's transcript missing: today's early exit, nothing written, no marker - the agent file does not stand in.
    gone_sid, gone_t, gone = new_session("gonesub", n=2)
    gone_agent = ENV["work"] / "agent-gonesub.jsonl"
    gone_agent.write_text("", encoding="utf-8")
    append_requests(gone_agent, 40, 2)
    gone_t.unlink()
    run_main({**gone, "hook_event_name": "SubagentStop", "agent_transcript_path": str(gone_agent)}, debounced=True)
    check_eq("K13: the parent's transcript missing -> an early exit: no cost file, no marker",
             (cost_file(gone_sid).is_file(), marker_of(gone_sid)), (False, None))


def main():
    root = temp_project("qa-cost-hot-path-")
    work = temp_dir(prefix="qa-hot-path-")
    bare = temp_dir(prefix="qa-hot-path-bare-")          # a folder that is NOT an onboarded project
    old = hooklib._PROJECT_ROOT_CACHE
    wait_was = C.LOCK_WAIT_S
    try:
        use_project(root)
        ENV.update(root=root, work=work, bare=bare, cost=root / "qa-factory" / "state" / "cost")
        for part in (part_render_sites, part_markers, part_catch_up, part_window, part_no_loss, part_validate_artifacts,
                     part_telemetry_maintenance, part_telemetry_dispatch_end, part_subagent_stop):
            try:
                part()
            except Exception as exc:  # noqa: BLE001 - one part crashing must not hide the verdict of the others
                check(part.__name__ + " ran to the end", False, type(exc).__name__ + ": " + str(exc))
    finally:
        C.LOCK_WAIT_S = wait_was
        hooklib._PROJECT_ROOT_CACHE = old
        cleanup(root)
        cleanup(work)
        cleanup(bare)
    finish("test_cost_capture_hot_path")


if __name__ == "__main__":
    main()
