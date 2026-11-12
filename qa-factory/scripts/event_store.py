"""Single-writer task events with revision checks and recoverable projections.

The journal is authoritative; callers validate before append. Snapshots are caches.
Never infer a successful operation from a lost process or an incomplete last line.
"""
import contextlib
import errno
import hashlib
import json
import math
import os
from pathlib import Path
import stat
import threading
import time
import uuid


class StateConflict(ValueError):
    pass


class IdempotencyKeyReused(StateConflict):
    """A key that already holds a different request. `key` is the idempotency key and `fields` the names of the
    payload fields that differ (a type difference is `type`), so a caller that owns a door for that key
    (`story_step start` for `dispatch:<id>`; the controller's N-2 for a scope) tells it by TYPE and fields, never
    by reading the message (FR-12); the message names the key, the fields and both values and no door."""

    def __init__(self, message, key="", fields=()):
        super().__init__(message)
        self.key = str(key)
        self.fields = tuple(fields)


class EventCommitted(StateConflict):
    """The event IS committed and durable; something that follows the commit did not finish.

    ONE type for every refusal that says "event committed; ... do not repeat", so a caller tells
    it from a conflict where nothing committed by its TYPE, never by reading the message (FR-12).
    `story_step finish` owes a committed accept its tail (the host receipt released, the stage
    recorded) for every member; any other StateConflict means nothing was written. The message
    text of every member is unchanged by the type: it is what callers and the driver print.

    `stale_view`: in plain words, a clause saying what is left out of date (a person reads it in
    a note). `recorded_in`: the task-relative file that records the stale view, or "" when
    nothing on disk does - set by the raiser, which is the only one that knows whether its write
    landed."""

    stale_view = "a view derived from the journal was not refreshed"

    def __init__(self, message, recorded_in=""):
        super().__init__(message)
        self.recorded_in = str(recorded_in or "")


class ProjectionStale(EventCommitted):
    """The event IS committed, but the projection written under the writer lock failed; the
    store's stale marker (`state/projection-stale.json` unless the store names its own) records
    it and `recover` re-projects. The derived views are not refreshed either: they would render
    the stale projection."""

    stale_view = "the story's state view (state/controller.json) and the dashboard were not refreshed"


class DerivedViewStale(EventCommitted):
    """The event IS committed and the story's own projection is current; only a view derived
    from it (the dashboard) could not be refreshed after the writer lock was released.

    A StateConflict on purpose: every caller that already treats "event committed, say so,
    do not repeat" as a StateConflict keeps working. The subclass lets the one caller that must
    not retry a conflict (the SubagentStop hook: a repeat would write the fact twice) tell
    the two apart."""

    stale_view = "the dashboard was not refreshed"


def shared_file(path):
    """True for a file the factory writes but never holds exclusively.

    Hook and command processes of the live session append their own telemetry spans and
    rotate their aggregates next to ours. On Windows an open handle there is an ordinary
    race between two of our own processes, not a corrupt task state.
    """
    text = str(path or "").replace("\\", "/")
    return "/state/telemetry/" in text or text.endswith(".aggregate.json")


def retry_shared(action, attempts=4, delay=0.05):
    """Run `action`, retrying a PermissionError raised over a file we do not own alone.

    TP1-15045 (21.09): `controller.py --operation recover` died with PermissionError on
    `qa-factory/state/telemetry/hook-*.aggregate.json` while a hook process still held it.
    The lifecycle event was already committed and durable; the only casualty was a dashboard
    refresh, and the caller was told to recover a state that was never damaged. A
    PermissionError over anything else is still a real failure and is re-raised at once.
    """
    for attempt in range(attempts):
        try:
            return action()
        except PermissionError as exc:
            if attempt + 1 >= attempts or not shared_file(getattr(exc, "filename", "")):
                raise
            time.sleep(delay * (attempt + 1))


def content_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=False).encode("utf-8")).hexdigest()


def _is_windows():
    # One seam for "is this Windows": tests flip it without changing os.name, which would
    # make pathlib build the wrong flavour of Path under them.
    return os.name == "nt"


REPLACE_ATTEMPTS = 8
LOCK_POLL_SECONDS = 0.05
# The wait of every short read-modify-write lock of the package's state files (lease registry, claims, stand lease,
# stand health, estimation ledger): the same 10 s on both platforms, never infinite. A lock held longer is a refusal
# that names the lock file and the holder (LockBusy), not a hang. Callers read it as `event_store.SHORT_RMW_LOCK_WAIT_S`
# at call time, so one patch of this attribute reaches every site.
SHORT_RMW_LOCK_WAIT_S = 10
# The marker every store writes when a projection fails after its commit, unless the store names its
# own. The controller's projection owns this name; `controller --operation recover` removes it.
STALE_MARKER = "projection-stale.json"
# How long a lifecycle COMMAND (the CLI of controller, stage_done, manifest_put, story_step)
# waits for an in-flight writer before it gives up. It is read by those CLIs' `main` and by
# SubagentStop's `record_return` (TR3-14: with parallel windows a sibling's commit holds the lock
# for a moment; its worst case is 3 tries x 10 s + 1.2 s = 31.2 s). The telemetry and cost hooks
# do NOT inherit it and keep failing at once, because a hook that waits stalls the host's own tool call.
LIFECYCLE_WAIT_SECONDS = 10


def atomic_json(path, value):
    """Publish JSON by replace, riding out a brief Windows reader-handle race.

    The journal is already durable when a projection is written. On Windows a reader that
    still holds the target (WinError 5 access denied, 32 sharing violation) makes
    `os.replace` fail for a moment; one failure used to turn a committed event into
    "projection stale" (a full selftest under load, test_resume_packet, hit exactly this).
    Only that pair of codes, only on Windows, is retried (8 attempts, 0.025 * n s apart);
    any other failure is real and is re-raised on the first attempt.
    """
    def write(stream):
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    _publish(path, write)


def atomic_text(path, text):
    """Publish a text file the way `atomic_json` publishes JSON (unique temp name, fsync, the same Windows retry).

    The bytes on disk are the bytes of `text` (no newline translation, so a caller may name their count); a lone
    surrogate is written as `?` rather than raised, so a derived file never turns a hidden part into a crash. Any
    other failure is raised for the caller to say in words (SC1-8: `config_view.py`, `controller.py --brief`)."""
    def write(stream):
        stream.write(text)
    _publish(path, write, errors="replace", newline="")


def _publish(path, write, **open_options):
    """The one temp-file-then-replace publisher behind `atomic_json` and `atomic_text`."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with tmp.open("w", encoding="utf-8", **open_options) as stream:
            write(stream)
            stream.flush()
            os.fsync(stream.fileno())
        replace_file(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def replace_file(src, dst):
    """`os.replace(src, dst)`, riding out a brief Windows reader-handle race (B-333).

    The one retrying replace: only WinError 5 (access denied) and 32 (sharing violation), only on
    Windows, REPLACE_ATTEMPTS tries 0.025 * n s apart; any other failure is raised on the first try."""
    for attempt in range(1, REPLACE_ATTEMPTS + 1):
        try:
            os.replace(src, dst)
            return
        except PermissionError as exc:
            if (not _is_windows() or getattr(exc, "winerror", None) not in (5, 32)
                    or attempt == REPLACE_ATTEMPTS):
                raise
            time.sleep(0.025 * attempt)


def _wait_budget(wait_seconds):
    """Seconds a writer may wait: None or negative is 0 (immediate), non-finite is refused, and
    so is a bool - `float(True)` is a second and `float(False)` none, so a flag that reached a
    wait parameter by mistake used to change the wait without a word."""
    if wait_seconds is None:
        return 0.0
    if isinstance(wait_seconds, bool):
        raise ValueError("wait_seconds must be a number of seconds, got the flag %r; pass 0 to "
                         "fail at once or a number such as 10 to wait" % (wait_seconds,))
    wait = float(wait_seconds)
    if not math.isfinite(wait):
        raise ValueError("wait_seconds must be a finite number of seconds, got %r; "
                         "pass 0 to fail at once or a number such as 10 to wait"
                         % (wait_seconds,))
    return max(0.0, wait)


# --------------------------------------------------------------------------------------------
# the one file lock of the package (TR4-2): one byte of one file, a timeout on both platforms
# --------------------------------------------------------------------------------------------

# The errno values a non-blocking lock call answers while ANOTHER handle holds the byte (moved from
# probe_by_code.py): every other errno is a primitive that cannot run, never "held".
HELD_ERRNOS = frozenset({errno.EACCES, errno.EAGAIN, errno.EWOULDBLOCK, errno.EDEADLK})
_HOLDER_READ_BYTES = 4096


def _lock_platform_is_windows():
    # The lock primitive's OWN platform seam: `_is_windows` stays the replace-retry seam only, so a test
    # that flips this one on Linux supplies a fake `msvcrt` and never imports the real one.
    return os.name == "nt"


class LockBusy(TimeoutError):
    """The lock stayed held for the whole wait. `.path` (Path), `.waited_s` (float), `.holder` (dict, `{}` when
    none is recorded). `str()` is a whole sentence naming the lock file, the seconds, the recorded holder (or that
    none is recorded) and the door."""

    def __init__(self, path, waited_s=0.0, holder=None):
        self.path = Path(path)
        self.waited_s = float(waited_s)
        self.holder = dict(holder) if isinstance(holder, dict) else {}
        clause = self.holder_clause
        super().__init__("%s is held for over %g s: nothing was done under it. %s%s."
                         % (self.path, round(self.waited_s, 2), clause[:1].upper(), clause[1:]))

    @property
    def holder_clause(self):
        """The holder words a caller appends to its own busy head (`"; " + clause`). A recorded holder is advice, never proof."""
        pid = self.holder.get("pid")
        if pid is not None:
            return ("held by process %s since %s, if that process is gone the lock frees itself"
                    % (pid, self.holder.get("since") or "an unknown time"))
        return "no holder recorded - released when that process ends: wait and repeat"


class LockBroken(OSError):
    """The lock could not be TRIED. `.path`, `.reason` (str), `.stage` in {"open", "platform", "lock"}: "open" = the
    file or its folder cannot be opened or made; "platform" = msvcrt/fcntl cannot be imported; "lock" = the lock call
    failed with an errno outside HELD_ERRNOS. This is not another writer."""

    def __init__(self, path, reason="", stage="lock"):
        self.path = Path(path)
        self.reason = str(reason)
        self.stage = stage
        super().__init__("%s cannot be locked (%s): nothing was done under it. This is not another writer: %s must be a "
                         "writable file." % (self.path, self.reason, self.path))


def os_try_lock(fd):
    """THE one primitive: one NON-blocking try on byte 0 of `fd`. Raises OSError (errno in HELD_ERRNOS when held) or
    ImportError. The only code in the package that calls `msvcrt.locking(.., LK_NBLCK, 1)` / `fcntl.flock(.., LOCK_NB)`."""
    os.lseek(fd, 0, 0)
    if _lock_platform_is_windows():
        import msvcrt
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
    else:
        import fcntl
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)


def _os_unlock(fd):
    os.lseek(fd, 0, 0)
    if _lock_platform_is_windows():
        import msvcrt
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    else:
        import fcntl
        fcntl.flock(fd, fcntl.LOCK_UN)


def _open_lock_fd(path, flags):
    return os.open(str(path), flags | getattr(os, "O_BINARY", 0), 0o666)   # umask makes it 0o644, as the old copies did


def lock_holder(path):
    """The recorded holder `{pid, since, purpose}` of a lock file, or `{}`; never raises. The ONE reader of the holder
    bytes: it reads from offset 1 and never byte 0 (a held byte raises PermissionError on Windows). A record is advice
    for a reader, never a condition of holding, and the pid is never probed for liveness."""
    try:
        fd = _open_lock_fd(path, os.O_RDONLY)
    except OSError:
        return {}
    try:
        os.lseek(fd, 1, 0)
        raw = os.read(fd, _HOLDER_READ_BYTES)
        value = json.loads(raw.decode("utf-8"))
    except (OSError, ValueError):
        return {}
    finally:
        with contextlib.suppress(OSError):
            os.close(fd)
    pid = value.get("pid") if isinstance(value, dict) else None
    if not isinstance(pid, int) or isinstance(pid, bool):
        return {}
    since, purpose = value.get("since"), value.get("purpose")
    return {"pid": pid, "since": since if isinstance(since, str) else "", "purpose": purpose if isinstance(purpose, str) else ""}


def file_lock_state(path):
    """"held" | "free" | "unknown" for a lock file; it opens read-only and never creates or writes (a missing file or a
    folder is "unknown": it did not try, so it never says "free")."""
    try:
        fd = _open_lock_fd(path, os.O_RDONLY)
    except OSError:
        return "unknown"
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            return "unknown"
        try:
            os_try_lock(fd)
        except OSError as exc:
            return "held" if exc.errno in HELD_ERRNOS else "unknown"
        except ImportError:
            return "unknown"
        with contextlib.suppress(Exception):
            _os_unlock(fd)
        return "free"
    except OSError:
        return "unknown"
    finally:
        with contextlib.suppress(OSError):
            os.close(fd)


class FileLock:
    """A held lock: `.path`, `.waited_s`. `release()` is idempotent and never raises (an unlock error is dropped: closing
    the handle releases the lock anyway); it may be called from another thread, the fd is swapped out under a guard so a
    double release never double-closes."""

    def __init__(self, path, fd, waited_s, record_holder):
        self.path = Path(path)
        self.waited_s = float(waited_s)
        self._fd = fd
        self._record_holder = bool(record_holder)
        self._guard = threading.Lock()

    def release(self):
        with self._guard:
            fd, self._fd = self._fd, None
        if fd is None:
            return
        if self._record_holder:                     # the truncate comes BEFORE the unlock: the next holder's record must not be cut
            with contextlib.suppress(Exception):
                os.ftruncate(fd, 1)
        with contextlib.suppress(Exception):
            _os_unlock(fd)
        with contextlib.suppress(OSError):
            os.close(fd)


def _record_holder_bytes(fd, purpose):
    """Step 1 of the byte order: truncate to byte 0 FIRST, then write the record at offset 1. A failure of either step is
    dropped: the lock stays held and a failed write leaves "no holder recorded", never the previous holder."""
    record = {"pid": os.getpid(), "since": time.strftime("%Y-%m-%dT%H:%M:%S"), "purpose": str(purpose or "")}
    with contextlib.suppress(Exception):
        os.ftruncate(fd, 1)
        os.lseek(fd, 1, 0)
        os.write(fd, json.dumps(record, separators=(",", ":")).encode("utf-8"))


def _try_once(path, fd, lock_call):
    """One try. Returns True when taken, False when busy; raises LockBroken when the lock cannot be tried."""
    try:
        if not os.fstat(fd).st_size:                # byte 0 exists before the try; a PermissionError of this first write is "busy" (D2)
            os.lseek(fd, 0, 0)
            os.write(fd, b"0")
    except PermissionError:
        return False
    except OSError as exc:
        raise LockBroken(path, exc, "open") from exc
    try:
        lock_call(fd)
        return True
    except ImportError as exc:
        raise LockBroken(path, exc, "platform") from exc
    except OSError as exc:
        if exc.errno in HELD_ERRNOS:
            return False
        raise LockBroken(path, exc, "lock") from exc


def take_file_lock(path, wait_s=0.0, *, purpose="", record_holder=False, poll_s=LOCK_POLL_SECONDS,
                   clock=None, sleep=None, lock_call=None):
    """Take the lock of `path`, polling a NON-blocking try every `poll_s` until a monotonic deadline; returns a `FileLock`
    the caller releases (a lock held across calls). `wait_s` None/negative = one try; a flag or a non-finite number is a
    ValueError. Raises `LockBusy` when held for the whole wait, `LockBroken` (never "acquired") when the lock cannot be
    tried. A holder is recorded only where `record_holder` is True (locks under qa-factory/state/): a lock file in a
    project's tracked tree stays the single byte "0". The lock file is never deleted, renamed or replaced."""
    budget = _wait_budget(wait_s)
    clock = clock or time.monotonic
    sleep = sleep or time.sleep
    lock_call = lock_call or os_try_lock
    path = Path(path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = _open_lock_fd(path, os.O_RDWR | os.O_CREAT)
    except OSError as exc:
        raise LockBroken(path, exc, "open") from exc
    started = clock()
    deadline = started + budget
    try:
        while not _try_once(path, fd, lock_call):
            now = clock()
            if now >= deadline:
                raise LockBusy(path, now - started, lock_holder(path))
            sleep(poll_s)
        if record_holder:
            _record_holder_bytes(fd, purpose)
    except BaseException:
        with contextlib.suppress(OSError):
            os.close(fd)
        raise
    return FileLock(path, fd, clock() - started, record_holder)


@contextlib.contextmanager
def hold_file_lock(path, wait_s=0.0, *, purpose="", record_holder=False, poll_s=LOCK_POLL_SECONDS,
                   clock=None, sleep=None, lock_call=None):
    """`take_file_lock` as a block; released in `finally`, the block's own exception goes on."""
    lock = take_file_lock(path, wait_s, purpose=purpose, record_holder=record_holder, poll_s=poll_s,
                          clock=clock, sleep=sleep, lock_call=lock_call)
    try:
        yield lock
    finally:
        lock.release()


class EventStore:
    def __init__(self, task_root, after_commit=None, wait_seconds=0.0, stale_marker=STALE_MARKER):
        """`after_commit`: a no-argument step run AFTER the writer lock is released, on every
        successful `commit` (replay included) and every `recover` of this store. It is how a
        view derived from the journal (the dashboard) is refreshed without being rendered
        under the lock: while the lock was held for a render, an observer stalled the story's
        own lifecycle (TP2-2406: dispatch and recover kept reporting an active state
        writer). One mechanism on the store, not a call at each site, so a new commit site
        cannot forget it. Absent (the default), the store behaves exactly as it always did.

        `wait_seconds`: how long this store's `commit` and `recover` wait for an in-flight
        writer when the call does not say. Default 0 (immediate). Only a CLI entry sets it;
        `lock()` itself never inherits it.

        `stale_marker`: the file name, under `state/`, that records a projection which failed after
        its commit and that a successful projection (commit replay or `recover`) removes. A
        projection that is not the controller's names its own: the manifest's marker shared
        `projection-stale.json` with the controller's, so `controller --operation recover` removed
        the manifest's only trace without rebuilding the manifest (TP2-2406 S5-4, 19.10.2026,
        journal seq 115: the live state had no marker and a manifest stuck at revision 5)."""
        marker = stale_marker
        if not isinstance(marker, str) or not marker or marker != Path(marker).name or marker in (".", ".."):
            raise ValueError("stale_marker must be a plain file name under state/ (default %r), got %r"
                             % (STALE_MARKER, marker))
        self.stale_marker = marker
        self.root = Path(task_root)
        self.state = self.root / "state"
        self.log = self.state / "events.jsonl"
        self.after_commit = after_commit
        self.wait_seconds = _wait_budget(wait_seconds)
        self._deferral = 0
        self._pending = False

    def _wait(self, wait_seconds):
        return self.wait_seconds if wait_seconds is None else wait_seconds

    def _require_root(self):
        """The journal of a story is written only into a story folder that EXISTS (CX1-18, R-lock): S0 creates a story
        folder, a write to its journal never does. The guard sits in `commit` and `recover`, the two entries of a
        story's journal, and NOT in `lock`: five project-level mutexes (the dashboard, the journal, the stand identity,
        the cost capture, the native context) take `lock()` on a folder this very call brings into being. The refusal
        is the one typed `StoryRootError` (the call's fault), imported here only on this path, so the store stays a
        leaf of the standard library while nothing is refused."""
        try:
            if self.root.is_dir():
                return
        except OSError:
            pass
        from hooklib import StoryRootError
        raise StoryRootError(f"the story folder {self.root} does not exist, so nothing was written: a story folder is "
                             "created by S0, never by a write to its journal. Pass the folder of a story that exists")

    def _committed(self):
        """A commit or recover just left the lock. Run the step now, or note it for the end
        of the `deferred_after_commit` block that is open."""
        if self.after_commit is None:
            return
        if self._deferral:
            self._pending = True
            return
        self._run_after_commit()

    def _run_after_commit(self):
        try:
            self.after_commit()
        except StateConflict:
            raise
        except Exception as exc:
            raise DerivedViewStale(
                "event committed; the step that follows it did not finish (%s: %s); "
                "do not repeat the action" % (type(exc).__name__, exc)) from exc

    @contextlib.contextmanager
    def deferred_after_commit(self):
        """Run the after-commit step ONCE, when this block ends, instead of after each commit.

        For an operation that commits several times (recover) or has work of its own to do
        between the commit and the derived views (apply's `_after_commit`): the step still runs
        after the lock is free, only later. It runs if anything inside committed, also when the
        block raised — a committed event deserves its views — and then its own failure is not
        allowed to mask the error that is already in flight."""
        self._deferral += 1
        try:
            yield
        except BaseException:
            self._deferral -= 1
            if not self._deferral and self._pending:
                self._pending = False
                with contextlib.suppress(Exception):
                    self._run_after_commit()
            raise
        else:
            self._deferral -= 1
            if not self._deferral and self._pending:
                self._pending = False
                self._run_after_commit()

    @contextlib.contextmanager
    def lock(self, wait_seconds=0.0):
        """OS lock releases on process death; never remove another writer's lock file.

        The default is IMMEDIATE (one non-blocking attempt): hooks and debounced writers
        rely on a conflict meaning "someone else is writing, skip". A lifecycle command
        that would rather wait for an in-flight writer passes `wait_seconds` > 0: the lock
        is polled every 50 ms until a monotonic deadline, then the same StateConflict is
        raised. The lock file is only ever opened, never deleted or truncated. The mechanics
        are the package's one file lock (`take_file_lock`); a lock that cannot be opened or
        opened (a folder at the path) or whose platform module is missing is re-raised as the
        helper's `LockBroken`; a lock call failing with an errno outside HELD_ERRNOS stays
        the same `StateConflict` as a busy lock, as before.
        """
        try:
            held = take_file_lock(self.state / "events.lock", wait_seconds, record_holder=False)
        except LockBusy as exc:
            raise StateConflict("task has an active state writer") from exc
        except LockBroken as exc:
            if exc.stage == "lock":
                raise StateConflict("task has an active state writer") from exc
            raise
        try:
            yield
        finally:
            held.release()

    def read(self, repair_tail=False):
        raw = self.log.read_bytes() if self.log.exists() else b""
        if raw and not raw.endswith(b"\n"):
            if not repair_tail:
                raise StateConflict("incomplete final event; recover under writer lock")
            boundary = raw.rfind(b"\n") + 1
            tail = raw[boundary:]
            (self.state / ("recovery-" + uuid.uuid4().hex + ".bin")).write_bytes(tail)
            with self.log.open("r+b") as f:
                f.truncate(boundary)
                f.flush()
                os.fsync(f.fileno())
            raw = raw[:boundary]
        events = []
        seen = set()
        previous = ""
        for i, line in enumerate(raw.splitlines(), 1):
            try:
                event = json.loads(line)
                digest = event.pop("event_hash")
                if (event["sequence"] != i or event["expected_revision"] != i - 1
                        or event["task_id"] != self.root.name
                        or event["previous_hash"] != previous
                        or event["idempotency_key"] in seen or content_hash(event) != digest):
                    raise ValueError("event chain conflict")
                seen.add(event["idempotency_key"])
                event["event_hash"] = digest
                events.append(event)
                previous = digest
            except (ValueError, KeyError, TypeError) as exc:
                raise StateConflict(f"corrupt event {i}; writes blocked") from exc
        return events

    def commit(self, kind, payload, key, expected_revision=None, validate=None, project=None,
               *, wait_seconds=None):
        """Append one event and run `project` under the lock; return the event.

        `wait_seconds` None means the store's own default (0 unless a CLI set it); a number
        overrides it for this call. After the lock is released the store's `after_commit` step
        runs; if it fails the event STAYS committed and `DerivedViewStale` (a StateConflict)
        is raised instead of returning. A failing `project` raises the old "projection stale"
        text as `ProjectionStale` and the step does not run: the views would render a stale
        projection. Both are `EventCommitted`: the type, not the text, says the event is in."""
        if not kind or not key or not isinstance(payload, dict):
            raise ValueError("type, idempotency key and object payload are required")
        self._require_root()
        with self.lock(self._wait(wait_seconds)):
            event = self._commit_locked(kind, payload, key, expected_revision, validate, project)
        self._committed()
        return event

    REUSE_VALUE_LIMIT = 200   # characters of one value shown in the refusal; a longer one ends in `…`

    def _reuse_refusal(self, event, kind, payload, key):
        """The refusal of a key that already holds a different request, in words that name the key, the fields
        that differ and BOTH values (TP2-2406 S3-3, 15.10.2026: `story_step start --id <committed id>` was
        refused with the bare sentence, no field and no value). The guard itself is unchanged: it still refuses,
        and the head text is the old sentence (callers and tests match it). It spells NO door: the caller that owns
        one for the key appends it. A mapping field is named by the keys that differ (its values can be a page
        long); every other value is shown whole up to REUSE_VALUE_LIMIT characters, and a value that is not JSON
        is shown as text, never a TypeError (a refusal must still be a StateConflict)."""
        absent = object()
        limit = self.REUSE_VALUE_LIMIT

        def shown(value):
            try:
                text = ("<absent>" if value is absent
                        else json.dumps(value, ensure_ascii=False, sort_keys=True, default=str))
            except (TypeError, ValueError):   # keys of mixed types, a cycle: the refusal still refuses
                text = str(value)
            return text if len(text) <= limit else text[:limit] + "…"

        parts, fields = [], []
        if event["type"] != kind:
            parts.append(f"type: committed={event['type']} | now={kind}")
            fields.append("type")
        old = event["payload"] if isinstance(event["payload"], dict) else {}
        for field in sorted(set(old) | set(payload)):
            before, now = old.get(field, absent), payload.get(field, absent)
            if before == now:
                continue
            fields.append(field)
            if isinstance(before, dict) and isinstance(now, dict):
                keys = sorted(k for k in set(before) | set(now) if before.get(k, absent) != now.get(k, absent))
                parts.append(f"{field}: differs in keys {keys}")
            else:
                parts.append(f"{field}: committed={shown(before)} | now={shown(now)}")
        return IdempotencyKeyReused(
            f"idempotency key reused with different inputs: key {key!r} already holds a {event['type']} "
            "request that differs in " + ("; ".join(parts) or "its form"), key, fields)

    def _commit_locked(self, kind, payload, key, expected_revision, validate, project):
        """The body of `commit`, run with the writer lock held."""
        events = self.read(repair_tail=True)
        for event in events:
            if event["idempotency_key"] == key:
                if event["type"] != kind or event["payload"] != payload:
                    raise self._reuse_refusal(event, kind, payload, key)
                if project:
                    try:
                        project(events)
                        (self.state / self.stale_marker).unlink(missing_ok=True)
                    except Exception as exc:
                        raise self._projection_stale("event already committed", len(events), exc) from exc
                return event
        if expected_revision is not None and expected_revision != len(events):
            raise StateConflict("stale expected revision")
        if validate:
            validate(events, payload)
        event = {"schema_version": 2, "event_id": uuid.uuid4().hex,
                 "task_id": self.root.name, "sequence": len(events) + 1,
                 "expected_revision": len(events), "idempotency_key": key,
                 "previous_hash": events[-1]["event_hash"] if events else "",
                 "created_at": time.time(), "type": kind, "payload": payload}
        from record_schema import validate_record
        validate_record("Event", event)
        event["event_hash"] = content_hash(event)
        with self.log.open("ab") as f:
            f.write((json.dumps(event, ensure_ascii=False) + "\n").encode("utf-8"))
            f.flush()
            os.fsync(f.fileno())
        if project:
            try:
                project(events + [event])
                (self.state / self.stale_marker).unlink(missing_ok=True)
            except Exception as exc:
                raise self._projection_stale("event committed", event["sequence"], exc) from exc
        return event

    def _projection_stale(self, head, revision, failure):
        """The refusal for a committed event whose projection failed, with its marker written if it can be.

        The event is durable by now, so whatever the marker write raises (an Exception; a
        KeyboardInterrupt or SystemExit still goes through) must not replace this refusal: a bare
        OSError used to escape a committed accept, and `story_step finish`, which runs the accept's
        tail by the `EventCommitted` type, skipped it (t-434, critic re-check). The text claims no
        record the write did not make (FR-41), the same rule as `controller.refresh_derived`."""
        text = head + "; projection stale; recover, do not repeat action"
        recorded = "state/" + self.stale_marker
        try:
            atomic_json(self.state / self.stale_marker, {"revision": revision, "error": str(failure)})
        except Exception:
            stale = ProjectionStale(text + " (nothing on disk records that the projection is stale: "
                                           + recorded + " could not be written either)")
            stale.stale_view = (ProjectionStale.stale_view + ", and nothing on disk records that "
                                "(" + recorded + " could not be written)")
            return stale
        return ProjectionStale(text, recorded_in=recorded)

    def recover(self, project, wait_seconds=None):
        """Re-project the journal under the lock; return the number of events. The after-commit
        step runs once the lock is free — also when there was nothing to recover, which is what
        makes `recover` the door for a view that was left unrefreshed."""
        self._require_root()
        with self.lock(self._wait(wait_seconds)):
            events = self.read(repair_tail=True)
            project(events)
            (self.state / self.stale_marker).unlink(missing_ok=True)
            count = len(events)
        self._committed()
        return count
