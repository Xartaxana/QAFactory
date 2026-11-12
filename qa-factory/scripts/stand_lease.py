"""One run at a time on a stand that cannot take two — a project-level lease on the stand.

Why. TP1-15045, 2026-09-21: the project's config said `run.parallel: false` (one
account on the stand; a second login ends the first session), and the code critic still
started five UI runs within the same two seconds. All five failed — four on
`Locator.fill: Timeout` in setup — and the next automator dispatch ($8.08, 62 minutes) was
spent proving the tests were not to blame. `run.parallel` was a fact every role had to
remember; a fact the factory knows is a fact the factory enforces.

`run_suite.py` wraps the execution of a request in `hold()`. The second request does not
fail and is not refused: it waits in line (`waited_s` lands in its summary), and only after
`wait_s` does it give up with `StandBusy`, having launched nothing.

The lease is a record in `qa-factory/state/stand-lease.json`, one per environment name,
written atomically under the same OS file lock the scheduler's lease registry uses. The record
holds `holders: [{job, pid, started, mode, acquired_at}]`: one `exclusive` holder (a suite, a
capture) or up to `max_shared` `walk` holders of distinct jobs (manual walkers), never both. A
holder whose process is gone is dropped at the next acquire and named in the notes: a killed
runner, or a dead walker, must never close the stand for the rest of the day. Each holder
releases only itself (job + pid + birth). Records of an older package version are not read.

A person's word passes this block: `stand_lease.py --release --env NAME --reason "..."`
removes EVERY holder of the stand, each named in the notes with the reason.

Usage:
    stand_lease.py --status [--project-root DIR]
    stand_lease.py --release [--env NAME] --reason "why" [--project-root DIR]
    stand_lease.py --selftest
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from event_store import LockBusy  # noqa: E402

DEFAULT_WAIT_S = 1800
DEFAULT_ENVIRONMENT = "default"
NOTES_KEPT = 20

# Injectable for tests: nothing here may really sleep five seconds in a unit test.
_sleep = time.sleep
_monotonic = time.monotonic


class StandBusy(Exception):
    """The stand stayed leased for the whole allowed wait. `holder` is the lease record."""

    def __init__(self, holder: dict, waited_s: int = 0, environment: str = DEFAULT_ENVIRONMENT):
        self.holder = dict(holder or {})
        self.waited_s = int(waited_s)
        self.environment = environment
        super().__init__(
            f"the stand `{environment}` is still held by run {self.holder.get('job_id') or '?'} "
            f"(pid {self.holder.get('pid') or '?'}, since {self.holder.get('acquired_at') or '?'}) "
            f"after waiting {self.waited_s}s; nothing was launched. Start the run again when that "
            "one finishes. If that run is known to be gone, a person releases the stand: "
            f"stand_lease.py --release --env {environment} --reason \"...\"")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _paths(project_root) -> tuple[Path, Path]:
    path = Path(project_root) / "qa-factory" / "state" / "stand-lease.json"
    return path, path.with_suffix(".lock")


def _env_name(environment) -> str:
    return str(environment or "").strip() or DEFAULT_ENVIRONMENT


def configured_wait_s(project_root) -> int:
    """`run.stand_wait_s` from qa-factory/config.json; optional, so a 0.7.x project keeps working."""
    try:
        config = json.loads((Path(project_root) / "qa-factory" / "config.json")
                            .read_text(encoding="utf-8-sig"))
        value = (config.get("run") or {}).get("stand_wait_s")
        if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0:
            return int(value)
    except (OSError, ValueError, AttributeError, TypeError):
        pass
    return DEFAULT_WAIT_S


def _holder_state(lease: dict) -> str:
    """`alive`, `gone`, or `unknown` — what is actually known about the holder's process.

    The scheduler's identity check (pid + birth time) is proof either way: a recycled pid is not
    the holder. Without a recorded birth time there is nothing to compare, so a pid that answers
    is `unknown` and not `alive` — the run may be long finished and its number reused. The
    DECISION does not change (see `_holder_alive`): an unknown holder keeps the stand, because
    taking it from a live run recreates the incident this module exists for. What changes is the
    report, which no longer states as a fact something nobody measured (FR-41).
    """
    try:
        pid = int(lease.get("pid") or 0)
    except (TypeError, ValueError):
        pid = 0
    if pid <= 0:
        return "gone"
    # This reader serves both lease files: stand-lease.json rows carry `started`, the scheduler's
    # execution-leases.json rows carry `process_started_at`; a recycled pid must not read as live in either.
    started = str(lease.get("started") or lease.get("process_started_at") or "")
    try:
        if started:
            from execution_scheduler import _same_process
            return "alive" if _same_process(pid, started) else "gone"
        import run_suite
        return "unknown" if run_suite.pid_alive(pid) else "gone"
    except Exception:
        return "unknown"


def _holder_alive(lease: dict) -> bool:
    """Does this lease still hold the stand? Anything but proof that the holder is gone does."""
    return _holder_state(lease) != "gone"


def _identity(pid: int) -> str:
    try:
        from execution_scheduler import _started
        return _started(pid)
    except Exception:
        return ""


@contextlib.contextmanager
def _locked(lock_path: Path):
    import event_store
    from event_store import hold_file_lock
    with hold_file_lock(lock_path, event_store.SHORT_RMW_LOCK_WAIT_S, purpose="stand lease", record_holder=True):
        yield


def _read(path: Path) -> dict:
    """A corrupt file is an empty one: a half-written lease must not close the stand."""
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(value, dict) and isinstance(value.get("leases"), dict):
            value.setdefault("notes", [])
            if not isinstance(value["notes"], list):
                value["notes"] = []
            return value
    except (OSError, ValueError):
        pass
    return {"schema_version": 1, "leases": {}, "notes": []}


def _write(path: Path, state: dict) -> None:
    from event_store import atomic_json
    state["notes"] = list(state.get("notes") or [])[-NOTES_KEPT:]
    state["updated_at"] = _now()
    atomic_json(path, state)


def _mode_of(mode) -> str:
    return "walk" if mode == "walk" else "exclusive"


def _holders_of(lease) -> list:
    """The holder rows of one environment's record: `[{job, pid, started, mode, acquired_at}]`. A record
    without `holders` (an older package's shape) is not read: it holds nothing."""
    rows = lease.get("holders") if isinstance(lease, dict) else None
    return [dict(h) for h in rows if isinstance(h, dict)] if isinstance(rows, list) else []


def _public(holder: dict) -> dict:
    """A holder as callers and the `stand_busy` answer see it (`job_id` is the long-standing key of that answer)."""
    return {"job_id": holder.get("job"), "pid": holder.get("pid"), "acquired_at": holder.get("acquired_at"),
            "mode": holder.get("mode") or "exclusive"}


def _is_me(holder: dict, job_id: str, started: str) -> bool:
    """Pid + birth: a holder row is ours only when job and pid agree and, if both sides recorded a birth, so does it."""
    try:
        pid = int(holder.get("pid") or 0)
    except (TypeError, ValueError):
        return False
    theirs = str(holder.get("started") or "")
    return (str(holder.get("job") or "") == job_id and pid == os.getpid()
            and (not theirs or not started or theirs == started))


def _try_acquire(project_root, job_id: str, environment: str, mode: str = "exclusive",
                 max_shared: int = 1) -> tuple[str, dict]:
    """One attempt. Returns `(outcome, record)`: acquired | reentered | busy, and the blocking holder
    row (busy), the first dead holder dropped on the way (acquired) or `{}`.

    `exclusive` needs the stand with no holder at all; `walk` needs no `exclusive` holder and fewer than
    `max_shared` `walk` holders, each of a distinct job. A holder whose process is gone is dropped here,
    each named in the notes (a dead walker never holds the stand); one that merely cannot be checked keeps it."""
    mode, limit = _mode_of(mode), max(1, int(max_shared or 1))
    path, lock_path = _paths(project_root)
    with _locked(lock_path):
        state = _read(path)
        holders = _holders_of(state["leases"].get(environment))
        started = _identity(os.getpid())
        live, dropped = [], []
        for holder in holders:
            (dropped if _holder_state(holder) == "gone" else live).append(holder)
        for holder in dropped:
            state["notes"].append({
                "at": _now(), "event": "takeover", "environment": environment, "by": job_id,
                "from": holder.get("job"), "dead_pid": holder.get("pid"), "held_since": holder.get("acquired_at")})
        if any(_is_me(h, job_id, started) and _mode_of(h.get("mode")) == mode for h in live):
            if dropped:
                state["leases"][environment] = {"environment": environment, "holders": live}
                _write(path, state)
            return "reentered", {}
        if mode == "exclusive":
            blocker = live[0] if live else None
        else:
            walkers = [h for h in live if _mode_of(h.get("mode")) == "walk"]
            blocker = next((h for h in live if _mode_of(h.get("mode")) == "exclusive"), None)
            if blocker is None and (len(walkers) >= limit or any(str(h.get("job") or "") == job_id for h in walkers)):
                blocker = walkers[0]
        if blocker is not None:
            if dropped:                         # the dead are dropped even when this attempt is refused
                state["leases"][environment] = {"environment": environment, "holders": live}
                _write(path, state)
            return "busy", _public(blocker)
        live.append({"job": job_id, "pid": os.getpid(), "started": started, "mode": mode, "acquired_at": _now()})
        state["leases"][environment] = {"environment": environment, "holders": live}
        _write(path, state)
        return "acquired", (_public(dropped[0]) if dropped else {})


def _release(project_root, job_id: str, environment: str) -> None:
    """Remove OUR holder row only (job + pid + birth); the others stay. The last one out removes the record."""
    path, lock_path = _paths(project_root)
    with _locked(lock_path):
        state = _read(path)
        holders = _holders_of(state["leases"].get(environment))
        started = _identity(os.getpid())
        kept = [h for h in holders if not _is_me(h, job_id, started)]
        if len(kept) == len(holders):
            return
        if kept:
            state["leases"][environment] = {"environment": environment, "holders": kept}
        else:
            del state["leases"][environment]
        _write(path, state)


@contextlib.contextmanager
def hold(project_root, job_id: str, environment: str = "", wait_s: int = DEFAULT_WAIT_S,
         poll_s: int = 5, mode: str = "exclusive", max_shared: int = 1):
    """Hold the stand for the duration of the block.

    `mode="exclusive"` (the default: suites, captures) shares the stand with nobody; `mode="walk"` shares it
    with up to `max_shared` walks of distinct jobs and with nothing else. `max_shared` is the caller's
    number: this module never reads the project to find it.

    Yields `{"waited_s": int, "queued_behind": job_id|None, "environment": name}` plus
    `took_over` when a dead holder's row was dropped and `lease_error` when the lease file
    itself could not be used. Raises `StandBusy` (with `.holder`) when the stand stayed
    leased for `wait_s` seconds; `wait_s=None` reads `run.stand_wait_s` from the config.

    A broken lease FILE never stops a run: the defect would be the factory's own, and the
    person's tests would be the ones not running. The run proceeds unprotected and says so.
    """
    job_id = str(job_id or "") or f"pid-{os.getpid()}"
    env = _env_name(environment)
    limit = configured_wait_s(project_root) if wait_s is None else max(0, int(wait_s))
    began = _monotonic()
    queued_behind = None
    result = {"waited_s": 0, "queued_behind": None, "environment": env}
    outcome = "unprotected"
    while True:
        try:
            outcome, record = _try_acquire(project_root, job_id, env, mode, max_shared)
        except Exception as exc:  # lock or disk trouble: the factory's defect, not the run's
            outcome, record = "unprotected", {}
            result["lease_error"] = f"{type(exc).__name__}: {exc}"
        if outcome != "busy":
            if record:
                result["took_over"] = {"job_id": record.get("job_id"), "pid": record.get("pid"),
                                       "acquired_at": record.get("acquired_at")}
            break
        if queued_behind is None:
            queued_behind = str(record.get("job_id") or "") or None
        waited = _monotonic() - began
        if waited >= limit:
            raise StandBusy(record, int(waited), env)
        _sleep(max(0.0, min(float(poll_s), limit - waited)))
    # Only a run that was kept in line has waited; the time a free stand took to be taken (cold
    # imports, a slow disk, a loaded machine) is not waiting and must not read as 1 s.
    result["waited_s"] = int(round(_monotonic() - began)) if queued_behind is not None else 0
    result["queued_behind"] = queued_behind
    try:
        yield result
    finally:
        if outcome == "acquired":
            try:
                _release(project_root, job_id, env)
            except Exception:
                pass  # a dead holder's lease is taken over by the next run; never mask the run's own error


def status(project_root) -> dict:
    """Every lease with a verdict on its holder. Read-only: nothing is taken over here."""
    path, lock_path = _paths(project_root)
    try:
        with _locked(lock_path):
            state = _read(path)
    except Exception as exc:
        return {"leases": [], "notes": [], "error": f"{type(exc).__name__}: {exc}"}
    rows = []
    for name, lease in sorted(state["leases"].items()):
        if isinstance(lease, dict):
            rows.append({"environment": name,
                         "holders": [{**h, "state": _holder_state(h)} for h in _holders_of(lease)]})
    return {"leases": rows, "notes": state.get("notes") or []}


def release_by_person(project_root, environment: str, reason: str) -> dict:
    """A person's decision to free the stand: EVERY holder of it goes, each named in the notes with the reason."""
    env = _env_name(environment)
    path, lock_path = _paths(project_root)
    with _locked(lock_path):
        state = _read(path)
        lease = state["leases"].pop(env, None)
        if lease is None:
            return {"status": "not_held", "environment": env}
        holders = _holders_of(lease)
        for holder in holders or [{}]:
            state["notes"].append({"at": _now(), "event": "released_by_person", "environment": env,
                                   "from": holder.get("job"), "held_pid": holder.get("pid"), "reason": reason})
        _write(path, state)
    return {"status": "released", "environment": env, "released": holders}


def selftest() -> int:
    import shutil
    import tempfile
    global _sleep
    root = Path(tempfile.mkdtemp(prefix="qa-stand-lease-"))
    failures = 0

    def case(name, ok):
        nonlocal failures
        failures += 0 if ok else 1
        print(("PASS " if ok else "FAIL ") + name)

    real_sleep = _sleep
    try:
        _sleep = lambda _s: None  # noqa: E731
        with hold(root, "job-a", "", wait_s=0) as lease:
            case("a free stand is taken without waiting", lease["waited_s"] == 0 and lease["queued_behind"] is None)
            case("the lease is on disk", status(root)["leases"][0]["holders"][0]["job"] == "job-a")
            try:
                with hold(root, "job-b", "", wait_s=0, poll_s=0):
                    case("a second run is kept out", False)
            except StandBusy as busy:
                case("a second run is kept out", busy.holder.get("job_id") == "job-a")
            with hold(root, "job-c", "other-stand", wait_s=0):
                case("another environment has its own lease", len(status(root)["leases"]) == 2)
        case("the lease is released", status(root)["leases"] == [])
        path, _ = _paths(root)
        _write(path, {"schema_version": 1, "notes": [], "leases": {DEFAULT_ENVIRONMENT: {
            "holders": [{"job": "dead", "pid": 0, "started": "", "mode": "exclusive", "acquired_at": _now()}]}}})
        with hold(root, "job-d", "", wait_s=0) as lease:
            case("a dead holder is taken over", (lease.get("took_over") or {}).get("job_id") == "dead")
        case("the takeover is noted", any(n.get("event") == "takeover" for n in status(root)["notes"]))
    finally:
        _sleep = real_sleep
        shutil.rmtree(root, ignore_errors=True)
    print(f"\n=== stand_lease selftest: {'ok' if not failures else str(failures) + ' failed'} ===")
    return 1 if failures else 0


def main() -> None:
    parser = argparse.ArgumentParser(description="The project's stand lease")
    parser.add_argument("--project-root", type=Path)
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--release", action="store_true")
    parser.add_argument("--env", default="")
    parser.add_argument("--reason", default="")
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    if args.selftest:
        raise SystemExit(selftest())
    if args.project_root:
        root = args.project_root.resolve()
    else:
        from hooklib import project_root
        root = project_root()
    if args.release:
        if not args.reason.strip():
            parser.error("--release needs --reason: the person's decision is kept with its reason")
        try:
            answer = release_by_person(root, args.env, args.reason.strip())
        except LockBusy as busy:     # nothing was changed: the record is untouched
            print(f"The stand's lease record is held by another process for over {busy.waited_s:g} s, so nothing was "
                  f"released. A release needs that record to itself: wait a moment and repeat the same command; "
                  f"{busy.holder_clause}.", file=sys.stderr)
            raise SystemExit(3)      # the exit code of `stand_busy`, the other try-again answer of this lease
        print(json.dumps(answer, ensure_ascii=False))
        return
    if args.status:
        print(json.dumps(status(root), ensure_ascii=False, indent=1))
        return
    parser.error("--status, --release or --selftest is required")


if __name__ == "__main__":
    main()
