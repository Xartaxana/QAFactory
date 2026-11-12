"""stand_lease: one run at a time on a stand that cannot take two.

TP1-15045: `run.parallel: false`, and five UI runs started within two seconds on a stand
with one account — five false failures and a $8 dispatch proving the tests innocent. These
tests hold the lease for real across processes; nothing here sleeps on the clock (the poll
and the clock are injected), except the one test that waits for a real child to die.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import SCRIPTS, check, check_eq, check_in, cleanup, finish, run_script, temp_project  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import stand_lease  # noqa: E402


class FakeClock:
    """A clock that only moves when somebody sleeps; `on_sleep` lets a test change the world
    between two polls."""

    def __init__(self, on_sleep=None):
        self.now, self.sleeps, self.on_sleep = 0.0, [], on_sleep

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds
        if self.on_sleep:
            self.on_sleep(len(self.sleeps))


def with_clock(clock):
    stand_lease._sleep, stand_lease._monotonic = clock.sleep, clock.monotonic


def lease_file(root) -> dict:
    return json.loads((root / "qa-factory" / "state" / "stand-lease.json").read_text(encoding="utf-8"))


def write_lease(root, environment, holder, notes=None):
    path = root / "qa-factory" / "state" / "stand-lease.json"
    path.write_text(json.dumps({"schema_version": 1, "leases": {environment: {"holders": [holder]}},
                                "notes": notes or []}), encoding="utf-8")


HOLDER = """
import sys, time
sys.path.insert(0, sys.argv[1])
import stand_lease
with stand_lease.hold(sys.argv[2], "child-job", sys.argv[3], wait_s=0):
    print("held", flush=True)
    time.sleep(120)
"""


def start_holder(root, environment=""):
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    proc = subprocess.Popen([sys.executable, "-B", "-c", HOLDER, str(SCRIPTS), str(root), environment],
                            stdout=subprocess.PIPE, text=True, env=env)
    line = proc.stdout.readline().strip()
    return proc, line


def test_a_held_lease_lock_runs_unprotected_with_the_holder_named():
    """TR4-2 C: the lease lock held past the wait is the helper's LockBusy; `hold` keeps its fail-open policy (the run goes on
    unprotected) and says why with the holder sentence, `status` answers its `error` key the same way."""
    import event_store as ES
    from event_store import take_file_lock
    root = temp_project("qa-stand-lease-held-")
    path, lock_path = stand_lease._paths(root)
    holder = take_file_lock(lock_path, 0, purpose="test holder", record_holder=True)
    saved = ES.SHORT_RMW_LOCK_WAIT_S
    ES.SHORT_RMW_LOCK_WAIT_S = 0.2
    try:
        with stand_lease.hold(root, "job-held", "", wait_s=0) as lease:
            error = lease.get("lease_error", "")
            assert "LockBusy" in error and "held by process %d" % os.getpid() in error.lower(), error
        answer = stand_lease.status(root)
        assert "held by process %d" % os.getpid() in answer.get("error", "").lower(), answer
    finally:
        ES.SHORT_RMW_LOCK_WAIT_S = saved
        holder.release()
        cleanup(root)


def _lease_bytes(root):
    path, _ = stand_lease._paths(root)
    return path.read_bytes() if path.exists() else None


class _BusyLock:
    """The lease lock held by a second handle, the wait cut to a fifth of a second; restores both on exit."""

    def __init__(self, root, wait_s=0.2):
        self.root, self.wait_s = root, wait_s

    def __enter__(self):
        import event_store as ES
        self.es, self.saved = ES, ES.SHORT_RMW_LOCK_WAIT_S
        ES.SHORT_RMW_LOCK_WAIT_S = self.wait_s
        self.lock = ES.take_file_lock(stand_lease._paths(self.root)[1], 0, purpose="test holder", record_holder=True)
        return self

    def __exit__(self, *_exc):
        self.lock.release()
        self.es.SHORT_RMW_LOCK_WAIT_S = self.saved


def _seed_live_lease(root):
    """A lease of a live process of another job (this one), so every path has a record to read and decide from."""
    write_lease(root, "default", {"job": "other", "pid": os.getpid(), "started": "", "mode": "exclusive",
                                  "acquired_at": "2026-01-01T00:00:00+00:00"})


def test_busy_lock_take_refuses_and_writes_nothing():
    from event_store import LockBusy
    for wait in (0, 0.2):                      # at the helper's limit (one try) and just beyond it
        root = temp_project("qa-stand-lease-busy-take-")
        try:
            _seed_live_lease(root)
            before = _lease_bytes(root)
            with _BusyLock(root, wait):
                try:
                    stand_lease._try_acquire(root, "job-new", "default")
                    raise AssertionError("take under a busy lock must refuse")
                except LockBusy as busy:
                    assert "held by process %d" % os.getpid() in str(busy).lower(), str(busy)
            assert _lease_bytes(root) == before
        finally:
            cleanup(root)


def test_busy_lock_release_refuses_and_writes_nothing():
    from event_store import LockBusy
    root = temp_project("qa-stand-lease-busy-release-")
    try:
        with stand_lease.hold(root, "job-r", "", wait_s=0):
            before = _lease_bytes(root)
            with _BusyLock(root):
                try:
                    stand_lease._release(root, "job-r", "default")
                    raise AssertionError("release under a busy lock must refuse")
                except LockBusy:
                    pass
            assert _lease_bytes(root) == before
    finally:
        cleanup(root)


def test_busy_lock_release_by_person_refuses_and_writes_nothing():
    root = temp_project("qa-stand-lease-busy-person-")
    try:
        _seed_live_lease(root)
        before = _lease_bytes(root)
        import contextlib
        import io
        saved_argv, err, code = sys.argv, io.StringIO(), None
        sys.argv = ["stand_lease.py", "--project-root", str(root), "--release", "--reason", "gone"]
        try:
            with _BusyLock(root), contextlib.redirect_stderr(err):     # in-process: the wait is the cut seam, not 10 s
                try:
                    stand_lease.main()
                except SystemExit as exit_:
                    code = exit_.code
        finally:
            sys.argv = saved_argv
        assert code == 3, (code, err.getvalue())
        text = err.getvalue()
        assert "wait a moment and repeat the same command" in text and "held by process %d" % os.getpid() in text, text
        assert "Traceback" not in text and "qa-factory" not in text and ".lock" not in text, text
        assert _lease_bytes(root) == before
    finally:
        cleanup(root)


def test_busy_lock_status_reports_the_error_and_writes_nothing():
    root = temp_project("qa-stand-lease-busy-status-")
    try:
        _seed_live_lease(root)
        before = _lease_bytes(root)
        with _BusyLock(root):
            answer = stand_lease.status(root)
        assert answer["leases"] == [] and "held by process %d" % os.getpid() in answer["error"].lower(), answer
        assert _lease_bytes(root) == before
    finally:
        cleanup(root)


def test_broken_lock_surfaces():
    """A lock that cannot be TRIED is not another writer: every path raises the helper's LockBroken, `status` names it."""
    from event_store import LockBroken
    root = temp_project("qa-stand-lease-broken-")
    try:
        _seed_live_lease(root)
        before = _lease_bytes(root)
        _, lock_path = stand_lease._paths(root)
        lock_path.mkdir()                       # a directory where the lock file must be: the open fails
        for name, call in (("take", lambda: stand_lease._try_acquire(root, "job-b", "default")),
                           ("release", lambda: stand_lease._release(root, "job-b", "default")),
                           ("release_by_person", lambda: stand_lease.release_by_person(root, "", "gone"))):
            try:
                call()
                raise AssertionError(name + " must surface LockBroken")
            except LockBroken:
                pass
        assert "LockBroken" in stand_lease.status(root)["error"]
        assert _lease_bytes(root) == before
    finally:
        cleanup(root)


def test_a_held_lock_with_an_absent_empty_or_corrupt_lease_reads_as_no_lease():
    """Today's behaviour kept: with the lock HELD, a missing, empty or non-JSON lease file is an empty record."""
    for label, content in (("absent", None), ("empty", ""), ("not_json", "{half")):
        root = temp_project("qa-stand-lease-bad-file-")
        try:
            path, _ = stand_lease._paths(root)
            path.parent.mkdir(parents=True, exist_ok=True)
            if content is not None:
                path.write_text(content, encoding="utf-8")
            with stand_lease.hold(root, "job-" + label, "", wait_s=0) as lease:
                assert "lease_error" not in lease, (label, lease)
                assert stand_lease.status(root)["leases"][0]["holders"][0]["job"] == "job-" + label
        finally:
            cleanup(root)


def main() -> None:
    test_a_held_lease_lock_runs_unprotected_with_the_holder_named()
    check("a held lease lock runs unprotected with the holder named (hold, status)", True)
    test_busy_lock_take_refuses_and_writes_nothing()
    check("busy_lock_take_refuses_and_writes_nothing", True)
    test_busy_lock_release_refuses_and_writes_nothing()
    check("busy_lock_release_refuses_and_writes_nothing", True)
    test_busy_lock_release_by_person_refuses_and_writes_nothing()
    check("busy_lock_release_by_person_refuses_and_writes_nothing", True)
    test_busy_lock_status_reports_the_error_and_writes_nothing()
    check("busy_lock_status_reports_the_error_and_writes_nothing", True)
    test_broken_lock_surfaces()
    check("broken_lock_surfaces", True)
    test_a_held_lock_with_an_absent_empty_or_corrupt_lease_reads_as_no_lease()
    check("a held lock with an absent, empty or corrupt lease reads as no lease", True)
    real_sleep, real_clock = stand_lease._sleep, stand_lease._monotonic
    root = temp_project("qa-stand-lease-")
    try:
        # --- a free stand ---------------------------------------------------------------
        clock = FakeClock()
        with_clock(clock)
        with stand_lease.hold(root, "job-a", "") as lease:
            check_eq("a free stand is taken at once", (lease["waited_s"], lease["queued_behind"]), (0, None))
            check_eq("no environment name is the `default` stand", lease["environment"], "default")
            held = lease_file(root)["leases"]["default"]["holders"][0]
            check_eq("the lease names the job and this process", (held["job"], held["pid"], held["mode"]),
                     ("job-a", os.getpid(), "exclusive"))
            check("the holder's birth identity is recorded", bool(held.get("started")))
            with stand_lease.hold(root, "job-a", "") as inner:
                check_eq("the same job re-enters its own lease", inner["waited_s"], 0)
            check_in("re-entering does not release the outer lease", "default", lease_file(root)["leases"])
            with stand_lease.hold(root, "job-x", "preview", wait_s=0):
                check_eq("one lease per environment name", sorted(lease_file(root)["leases"]),
                         ["default", "preview"])
        check_eq("leaving the block releases the lease", lease_file(root)["leases"], {})
        check_eq("nobody slept for a free stand", clock.sleeps, [])

        try:
            with stand_lease.hold(root, "job-err", ""):
                raise RuntimeError("the run blew up")
        except RuntimeError:
            pass
        check_eq("an exception inside the block still releases", lease_file(root)["leases"], {})

        # --- a live holder in another process -------------------------------------------
        child, line = start_holder(root)
        try:
            check_eq("the child process holds the stand", line, "held")
            clock = FakeClock()
            with_clock(clock)
            try:
                with stand_lease.hold(root, "job-b", "", wait_s=12, poll_s=5):
                    check("a busy stand is not entered", False)
            except stand_lease.StandBusy as busy:
                check_eq("StandBusy carries the holder", (busy.holder.get("job_id"), busy.holder.get("pid")),
                         ("child-job", child.pid))
                check_eq("it waited the allowed time and not a poll longer", clock.sleeps, [5, 5, 2])
                check_in("the refusal says nothing was launched", "nothing was launched", str(busy))
                check_in("the refusal names the person's way through", "--release --env default", str(busy))
            check_eq("the holder's lease is untouched by the refusal",
                     lease_file(root)["leases"]["default"]["holders"][0]["job"], "child-job")

            with stand_lease.hold(root, "job-c", "another-stand", wait_s=0) as lease:
                check_eq("a different environment is free while this one is held", lease["waited_s"], 0)

            status = stand_lease.status(root)
            check_eq("--status calls a live holder alive",
                     [(h["job"], h["state"]) for row in status["leases"] for h in row["holders"]], [("child-job", "alive")])
            # FR-41: three words, because there are three states. A lease with no recorded birth
            # time cannot be checked against a recycled pid, so its holder is `unknown` and the
            # report says so - while the decision stays conservative and keeps the stand.
            import os as _os
            check_eq("a holder with no recorded birth time is unknown, not alive",
                     stand_lease._holder_state({"pid": _os.getpid()}), "unknown")
            check_eq("and it still holds the stand",
                     stand_lease._holder_alive({"pid": _os.getpid()}), True)
            check_eq("a pid nobody is running is gone", stand_lease._holder_state({"pid": 0}), "gone")

            # The second request WAITS IN LINE: the holder finishes during the third poll.
            def holder_finishes(poll):
                if poll == 3:
                    child.kill()
                    child.wait(timeout=30)
            clock = FakeClock(on_sleep=holder_finishes)
            with_clock(clock)
            with stand_lease.hold(root, "job-d", "", wait_s=1800, poll_s=5) as lease:
                check_eq("the queued run gets the stand when the holder is gone", lease["waited_s"], 15)
                check_eq("it says whom it waited behind", lease["queued_behind"], "child-job")
                check_eq("a killed holder's lease is taken over, and said so",
                         (lease.get("took_over") or {}).get("job_id"), "child-job")
            notes = lease_file(root)["notes"]
            check("the takeover is noted in the file",
                  any(n.get("event") == "takeover" and n.get("from") == "child-job"
                      and n.get("by") == "job-d" for n in notes))
        finally:
            if child.poll() is None:
                child.kill()
                child.wait(timeout=30)
            child.stdout.close()

        # --- dead and damaged records -----------------------------------------------------
        clock = FakeClock()
        with_clock(clock)
        write_lease(root, "default", {"job": "ghost", "pid": os.getpid(), "mode": "exclusive",
                                      "started": "winfiletime:1", "acquired_at": "2026-09-21T16:54:05+00:00"})
        with stand_lease.hold(root, "job-e", "", wait_s=0) as lease:
            check_eq("a recycled pid is not the holder (birth identity differs)",
                     (lease.get("took_over") or {}).get("job_id"), "ghost")
        check_eq("t-2070 F5: a scheduler row's `process_started_at` is read as the birth (recycled pid is gone)",
                 stand_lease._holder_state({"pid": os.getpid(), "process_started_at": "winfiletime:1"}), "gone")
        (root / "qa-factory" / "state" / "stand-lease.json").write_text("{ not json", encoding="utf-8")
        with stand_lease.hold(root, "job-f", "", wait_s=0) as lease:
            check_eq("a corrupt lease file does not close the stand", lease["waited_s"], 0)
        check_eq("and is rewritten clean", lease_file(root)["leases"], {})

        write_lease(root, "default", {"job": "old", "pid": 0}, notes=[{"n": i} for i in range(50)])
        with stand_lease.hold(root, "job-g", "", wait_s=0):
            pass
        check("the notes do not grow without bound", len(lease_file(root)["notes"]) <= stand_lease.NOTES_KEPT)

        # A defect of the lease machinery is the factory's, and must not cost the person a run.
        real_try = stand_lease._try_acquire

        def broken(*_args):
            raise OSError("lock file is unreachable")
        stand_lease._try_acquire = broken
        try:
            with stand_lease.hold(root, "job-h", "", wait_s=0) as lease:
                check_in("a broken lease file lets the run through, and says so",
                         "lock file is unreachable", lease.get("lease_error", ""))
        finally:
            stand_lease._try_acquire = real_try

        # --- config and the person's word -------------------------------------------------
        check_eq("run.stand_wait_s defaults to 1800 (a 0.7.x config has no such key)",
                 stand_lease.configured_wait_s(root), 1800)
        cfg_path = root / "qa-factory" / "config.json"
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        cfg.setdefault("run", {})["stand_wait_s"] = 7
        cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
        check_eq("run.stand_wait_s is read", stand_lease.configured_wait_s(root), 7)
        check_eq("a project with no config at all still gets the default",
                 stand_lease.configured_wait_s(root / "nowhere"), 1800)

        child, line = start_holder(root, "preview")
        try:
            clock = FakeClock()
            with_clock(clock)
            try:
                with stand_lease.hold(root, "job-i", "preview", wait_s=None, poll_s=5):
                    check("wait_s=None waits the configured time", False)
            except stand_lease.StandBusy as busy:
                check_eq("wait_s=None waits the configured time", (clock.sleeps, busy.waited_s), ([5, 2], 7))
            refused = run_script("stand_lease.py", "--project-root", root, "--release", "--env", "preview")
            check("a release without a reason is refused", refused.returncode != 0)
            released = run_script("stand_lease.py", "--project-root", root, "--release", "--env", "preview",
                                  "--reason", "the run was stopped by hand")
            check_eq("a person's word frees the stand", json.loads(released.stdout).get("status"), "released")
            with stand_lease.hold(root, "job-j", "preview", wait_s=0) as lease:
                check_eq("and the next run enters", lease["waited_s"], 0)
            check("the person's reason is kept",
                  any(n.get("event") == "released_by_person" and n.get("reason") == "the run was stopped by hand"
                      for n in lease_file(root)["notes"]))
            check("t-2070 F6: the release note carries no `pid` key (held_pid), so no reader takes it for a holder",
                  all("pid" not in n and n.get("held_pid") is not None
                      for n in lease_file(root)["notes"] if n.get("event") == "released_by_person"))
        finally:
            child.kill()
            child.wait(timeout=30)
            child.stdout.close()

        shown = run_script("stand_lease.py", "--project-root", root, "--status")
        check("--status prints JSON", isinstance(json.loads(shown.stdout).get("leases"), list))
        stand_lease._sleep, stand_lease._monotonic = real_sleep, real_clock
        selftest = run_script("stand_lease.py", "--selftest")
        check("--selftest passes", selftest.returncode == 0 and "FAIL" not in selftest.stdout)
        check("nothing was written into the package",
              not (SCRIPTS.parent / "qa-factory").exists())
    finally:
        stand_lease._sleep, stand_lease._monotonic = real_sleep, real_clock
        cleanup(root)
    finish("test_stand_lease")


if __name__ == "__main__":
    main()
