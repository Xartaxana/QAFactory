"""TR4-2 part A: the package's one file lock (`event_store.take_file_lock` / `hold_file_lock`) and its copy ratchet.

Timing never depends on wall-clock speed (FR-31): waits run on an injected clock and sleep; the one thread test uses a lower bound
and a generous ceiling. Platform branches run on fake `msvcrt` / `fcntl` modules, so a patched seam never imports the real one.
"""
import ast
import errno
import json
import math
import os
from pathlib import Path
import socket
import stat
import sys
import threading
import time
import types

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import event_store as ES
from event_store import EventStore, LockBroken, LockBusy, StateConflict, file_lock_state, hold_file_lock, lock_holder, take_file_lock

SCRIPTS = Path(__file__).resolve().parents[1]

# The copy ratchet (shrink-only): every file of the package outside event_store.py that still calls `msvcrt.locking` / `fcntl.flock`.
# Parts B, C and D each delete their own lines; the last merge leaves it empty and the test then demands zero.
REMAINING_COPY_FILES = frozenset()


class FakeTime:
    """An injected clock and sleep: the sleep advances the clock, nothing really waits."""

    def __init__(self):
        self.now = 100.0
        self.sleeps = []

    def clock(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


def proxy_os(monkeypatch, **overrides):
    """`event_store.os` replaced by a view of the real `os` with some functions overridden (no global patch of `os`)."""

    class View:
        def __getattr__(self, name):
            return overrides[name] if name in overrides else getattr(os, name)

    monkeypatch.setattr(ES, "os", View())


def lock_path(tmp_path, name="x.lock"):
    return tmp_path / "state" / name


def test_lock_is_taken_and_released(tmp_path):
    path = lock_path(tmp_path)
    with hold_file_lock(path):
        with pytest.raises(LockBusy):
            take_file_lock(path)
    again = take_file_lock(path)
    again.release()


def test_second_handle_wait_zero_is_busy_at_once(tmp_path):
    path, fake = lock_path(tmp_path), FakeTime()
    with hold_file_lock(path):
        with pytest.raises(LockBusy):
            take_file_lock(path, 0, clock=fake.clock, sleep=fake.sleep)
    assert fake.sleeps == []


def test_busy_after_the_wait_with_an_injected_clock(tmp_path):
    path, fake = lock_path(tmp_path), FakeTime()
    with hold_file_lock(path):
        with pytest.raises(LockBusy) as caught:
            take_file_lock(path, 2.0, poll_s=0.5, clock=fake.clock, sleep=fake.sleep)
    assert caught.value.waited_s >= 2.0
    assert fake.sleeps == [0.5] * 4
    assert isinstance(caught.value, TimeoutError)


def test_busy_names_file_seconds_holder_and_door(tmp_path):
    path, fake = lock_path(tmp_path), FakeTime()
    with hold_file_lock(path, purpose="a test", record_holder=True):
        with pytest.raises(LockBusy) as caught:
            take_file_lock(path, 1.0, poll_s=0.25, clock=fake.clock, sleep=fake.sleep)
    said = str(caught.value)
    assert str(path) in said
    assert "held for over 1 s" in said
    assert "process %d" % os.getpid() in said
    assert "frees itself" in said
    assert "stop it" not in said.lower()
    assert caught.value.holder["pid"] == os.getpid() and caught.value.holder["purpose"] == "a test"


def test_busy_without_a_holder_record_says_none_recorded(tmp_path):
    path = lock_path(tmp_path)
    with hold_file_lock(path):
        with pytest.raises(LockBusy) as caught:
            take_file_lock(path)
    assert caught.value.holder == {}
    assert "no holder recorded" in str(caught.value).lower() and "wait and repeat" in str(caught.value)
    assert "held by process" not in str(caught.value)


def test_released_when_the_block_raises(tmp_path):
    path = lock_path(tmp_path)
    with pytest.raises(KeyError) as caught:
        with hold_file_lock(path):
            raise KeyError("the block's own")
    assert caught.value.args == ("the block's own",)
    take_file_lock(path).release()


def test_another_thread_waits_then_gets_it(tmp_path):
    path = lock_path(tmp_path)
    taken, release = threading.Event(), threading.Event()

    def holder():
        with hold_file_lock(path):
            taken.set()
            release.wait(5)

    thread = threading.Thread(target=holder)
    thread.start()
    try:
        assert taken.wait(5)
        timer = threading.Timer(0.2, release.set)
        timer.start()
        started = time.monotonic()
        got = take_file_lock(path, 5.0)
        elapsed = time.monotonic() - started
        got.release()
        timer.cancel()
        assert elapsed >= 0.1
        assert elapsed < 4.0
        assert got.waited_s >= 0.1
    finally:
        release.set()
        thread.join(5)


def test_same_thread_second_acquire_is_busy(tmp_path):
    path = lock_path(tmp_path)
    with hold_file_lock(path):
        with hold_file_lock(path.parent / "other.lock"):
            pass
        with pytest.raises(LockBusy):
            with hold_file_lock(path):
                raise AssertionError("a nested acquire of the same lock must not run its block")


def test_first_write_permission_error_is_busy_not_a_crash(tmp_path, monkeypatch):
    path, fake, real_write, seen = lock_path(tmp_path), FakeTime(), os.write, []

    def write_once_refused(fd, data):
        seen.append(data)
        if len(seen) == 1:
            raise PermissionError(errno.EACCES, "the first byte is locked by another process")
        return real_write(fd, data)

    proxy_os(monkeypatch, write=write_once_refused)
    with hold_file_lock(path, 1.0, clock=fake.clock, sleep=fake.sleep):
        pass
    assert seen[:2] == [b"0", b"0"]                 # refused once (busy, waited out), then written and locked
    assert len(fake.sleeps) == 1
    with pytest.raises(LockBusy):                   # and a first write that stays refused is a refusal, never "acquired"
        proxy_os(monkeypatch, write=lambda fd, data: (_ for _ in ()).throw(PermissionError(errno.EACCES, "locked")))
        take_file_lock(lock_path(tmp_path, "y.lock"), 0.2, clock=fake.clock, sleep=fake.sleep)


def test_broken_primitive_is_not_acquired(tmp_path):
    path = lock_path(tmp_path)

    def invalid(fd):
        raise OSError(errno.EINVAL, "invalid argument")

    def missing(fd):
        raise ImportError("no msvcrt")

    for call in (invalid, missing):
        with pytest.raises(LockBroken):
            take_file_lock(path, 1.0, lock_call=call)
    take_file_lock(path).release()                  # the failed tries left no handle holding it


def test_folder_at_the_path_is_broken(tmp_path):
    folder = tmp_path / "dir.lock"
    folder.mkdir()
    with pytest.raises(LockBroken) as caught:
        take_file_lock(folder)
    assert caught.value.stage == "open"
    assert "not another writer" in str(caught.value) and "writable file" in str(caught.value)
    assert "held for" not in str(caught.value) and "try again" not in str(caught.value)


def test_missing_parent_is_made(tmp_path):
    path = tmp_path / "a" / "b" / "c.lock"
    with hold_file_lock(path):
        assert path.parent.is_dir()
    assert path.exists()


def test_both_platform_branches(tmp_path, monkeypatch):
    calls = []
    fake_msvcrt = types.SimpleNamespace(LK_UNLCK=0, LK_LOCK=1, LK_NBLCK=2, locking=lambda fd, mode, n: calls.append(("msvcrt", mode, n)))
    fake_fcntl = types.SimpleNamespace(LOCK_EX=2, LOCK_NB=4, LOCK_UN=8, flock=lambda fd, flags: calls.append(("fcntl", flags)))
    monkeypatch.setitem(sys.modules, "msvcrt", fake_msvcrt)
    monkeypatch.setitem(sys.modules, "fcntl", fake_fcntl)
    monkeypatch.setattr(ES, "_is_windows", lambda: not os.name == "nt")     # the replace-retry seam is NOT the lock platform seam
    for index, windows in enumerate((True, False)):
        calls.clear()
        monkeypatch.setattr(ES, "_lock_platform_is_windows", lambda value=windows: value)
        with hold_file_lock(lock_path(tmp_path, "p%d.lock" % index)):
            pass
        if windows:
            assert calls == [("msvcrt", fake_msvcrt.LK_NBLCK, 1), ("msvcrt", fake_msvcrt.LK_UNLCK, 1)]
            assert fake_msvcrt.LK_LOCK not in [c[1] for c in calls]
        else:
            assert calls == [("fcntl", fake_fcntl.LOCK_EX | fake_fcntl.LOCK_NB), ("fcntl", fake_fcntl.LOCK_UN)]
            assert all(c[1] != fake_fcntl.LOCK_EX for c in calls)           # a bare LOCK_EX would block


def test_holder_record_of_a_dead_process_is_replaced(tmp_path):
    path = lock_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_bytes(b"0" + json.dumps({"pid": 2147483000, "since": "2001-01-01T00:00:00", "purpose": "dead"}).encode())
    assert lock_holder(path)["pid"] == 2147483000
    with hold_file_lock(path, purpose="alive", record_holder=True):
        assert lock_holder(path)["pid"] == os.getpid()
        assert lock_holder(path)["purpose"] == "alive"
    assert path.read_bytes() == b"0"                # cleared at release: no record of a finished holder


def test_holder_record_has_no_path_or_host(tmp_path):
    path = lock_path(tmp_path)
    with hold_file_lock(path, purpose="plain words", record_holder=True):
        with open(path, "rb") as stream:
            stream.seek(1)                          # byte 0 of a held file is never read (Windows refuses it)
            raw = stream.read()
    record = json.loads(raw.decode("utf-8"))
    assert set(record) == {"pid", "since", "purpose"}
    assert str(tmp_path) not in raw.decode("utf-8") and socket.gethostname().lower() not in raw.decode("utf-8").lower()


def test_lock_file_is_never_deleted_and_byte_zero_stays(tmp_path):
    path = lock_path(tmp_path)
    inodes = []
    for _ in range(2):
        with hold_file_lock(path, record_holder=True):
            assert path.stat().st_size >= 1
        inodes.append(path.stat().st_ino)
        assert path.read_bytes()[:1] == b"0"
    assert inodes[0] == inodes[1]


def test_file_lock_state_free_held_unknown_and_never_creates(tmp_path):
    missing = lock_path(tmp_path, "missing.lock")
    assert file_lock_state(missing) == "unknown"
    assert not missing.exists() and not missing.parent.exists()
    empty = tmp_path / "empty.lock"
    empty.write_bytes(b"")
    assert file_lock_state(empty) == "free"
    assert empty.stat().st_size == 0                # a probe writes nothing: a 0-byte lock stays 0 bytes
    path = lock_path(tmp_path)
    take_file_lock(path).release()
    assert file_lock_state(path) == "free"
    with hold_file_lock(path):
        assert file_lock_state(path) == "held"
    assert file_lock_state(path) == "free"
    folder = tmp_path / "folder.lock"
    folder.mkdir()
    assert file_lock_state(folder) == "unknown"


def test_wait_flag_and_non_finite_are_refused(tmp_path):
    path = lock_path(tmp_path)
    for bad in (True, False, math.nan, math.inf, -math.inf):
        with pytest.raises(ValueError):
            take_file_lock(path, bad)
    fake = FakeTime()
    with hold_file_lock(path):
        for one_try in (None, -5, 0):
            with pytest.raises(LockBusy):
                take_file_lock(path, one_try, clock=fake.clock, sleep=fake.sleep)
    assert fake.sleeps == []


def test_holder_record_is_read_from_offset_one_while_held(tmp_path):
    path = lock_path(tmp_path)                      # the REAL primitive: no monkeypatch, on the Windows run and on Linux CI
    with hold_file_lock(path, purpose="real", record_holder=True):
        holder = lock_holder(path)
    assert holder["pid"] == os.getpid() and holder["purpose"] == "real"
    assert lock_holder(lock_path(tmp_path, "none.lock")) == {}


def test_release_truncates_before_unlock(tmp_path, monkeypatch):
    path, events, real_truncate, real_unlock = lock_path(tmp_path), [], os.ftruncate, ES._os_unlock

    def truncate(fd, size):
        events.append(("ftruncate", size))
        return real_truncate(fd, size)

    def unlock(fd):
        events.append(("unlock",))
        return real_unlock(fd)

    proxy_os(monkeypatch, ftruncate=truncate)
    monkeypatch.setattr(ES, "_os_unlock", unlock)
    held = take_file_lock(path, record_holder=True)
    events.clear()
    held.release()
    assert events == [("ftruncate", 1), ("unlock",)]
    held.release()                                  # idempotent: nothing runs twice
    assert events == [("ftruncate", 1), ("unlock",)]


def test_failed_record_write_leaves_no_stale_holder(tmp_path, monkeypatch):
    path = lock_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_bytes(b"0" + json.dumps({"pid": 4242, "since": "then", "purpose": "stale"}).encode())
    assert lock_holder(path)["pid"] == 4242

    def full_disk(fd, data):
        raise OSError(errno.ENOSPC, "no space left")

    proxy_os(monkeypatch, write=full_disk)
    with hold_file_lock(path, record_holder=True):  # the lock is still held: the record failing never refuses a lock that was got
        assert lock_holder(path) == {}
        with pytest.raises(LockBusy):
            take_file_lock(path)


def test_record_holder_false_leaves_one_byte(tmp_path):
    path = lock_path(tmp_path)
    take_file_lock(path).release()
    assert path.read_bytes() == b"0"
    with hold_file_lock(path, purpose="never written"):
        assert path.stat().st_size == 1
        with pytest.raises(LockBusy):
            take_file_lock(path)
    assert path.read_bytes() == b"0"


def test_broken_stages(tmp_path):
    folder = tmp_path / "f.lock"
    folder.mkdir()
    with pytest.raises(LockBroken) as opened:
        take_file_lock(folder)
    assert opened.value.stage == "open"
    with pytest.raises(LockBroken) as platform:
        take_file_lock(lock_path(tmp_path), lock_call=lambda fd: (_ for _ in ()).throw(ImportError("no fcntl")))
    assert platform.value.stage == "platform"
    with pytest.raises(LockBroken) as locked:
        take_file_lock(lock_path(tmp_path), lock_call=lambda fd: (_ for _ in ()).throw(OSError(errno.EINVAL, "bad")))
    assert locked.value.stage == "lock"
    for exc in (opened.value, platform.value, locked.value):
        assert not isinstance(exc, TimeoutError)    # never read as "another writer"


def test_event_store_lock_on_a_folder_raises_not_conflicts(tmp_path):
    store = EventStore(tmp_path / "QA-1")
    (store.state / "events.lock").mkdir(parents=True)
    with pytest.raises(LockBroken) as caught:
        with store.lock():
            raise AssertionError("a folder at events.lock must not read as acquired")
    assert not isinstance(caught.value, StateConflict)
    assert caught.value.stage == "open"


def test_event_store_lock_busy_keeps_today_text_and_chains_the_helper(tmp_path):
    store = EventStore(tmp_path / "QA-1")
    with store.lock():
        with pytest.raises(StateConflict) as caught:
            with EventStore(tmp_path / "QA-1").lock():
                raise AssertionError("a held lock must not run the block")
    assert str(caught.value) == "task has an active state writer"
    assert isinstance(caught.value.__cause__, LockBusy)
    assert (store.state / "events.lock").read_bytes() == b"0"      # C1 records no holder: a refused waiter changed no byte


def _os_lock_files(root):
    hits = set()
    names = {"msvcrt", "fcntl"}
    funcs = {"locking", "flock"}
    for source in sorted(Path(root).rglob("*.py")):
        relative = source.relative_to(root)
        if relative.parts[0] == "tests":
            continue
        text = source.read_text(encoding="utf-8")
        if "msvcrt" not in text and "fcntl" not in text:      # a call names the module: skip the parse of every other file
            continue
        tree = ast.parse(text)
        modules, bare = set(), set()                          # names bound to the module / to the lock function
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.update(a.asname or a.name for a in node.names if a.name in names)
            elif isinstance(node, ast.ImportFrom) and node.module in names:
                bare.update(a.asname or a.name for a in node.names if a.name in funcs)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if (isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) and func.value.id in modules
                    and func.attr in funcs) or (isinstance(func, ast.Name) and func.id in bare):
                hits.add(relative.as_posix())
    return hits


def test_no_os_lock_call_outside_the_helper(tmp_path):
    found = _os_lock_files(SCRIPTS)
    assert "event_store.py" in found, "the scan found no lock call in event_store.py: an empty scan is a miscall, not a pass"
    stray = sorted(found - {"event_store.py"} - REMAINING_COPY_FILES)
    assert not stray, "a lock call outside event_store.py (use take_file_lock / hold_file_lock): %s" % stray
    gone = sorted(REMAINING_COPY_FILES - found)
    assert not gone, "REMAINING_COPY_FILES names a file with no lock call any more (delete the line): %s" % gone
    # negative control: the same scan over a tree holding one extra file with a lock call reports that file
    (tmp_path / "tests").mkdir()
    (tmp_path / "event_store.py").write_text((SCRIPTS / "event_store.py").read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / "copy.py").write_text("import msvcrt\n\n\ndef f(fd):\n    msvcrt.locking(fd, 2, 1)\n", encoding="utf-8")
    (tmp_path / "tests" / "ignored.py").write_text("import fcntl\nfcntl.flock(1, 2)\n", encoding="utf-8")
    (tmp_path / "aliased.py").write_text("import fcntl as f\n\n\ndef g(fd):\n    f.flock(fd, f.LOCK_EX)\n", encoding="utf-8")
    (tmp_path / "frm.py").write_text("from msvcrt import locking\n\n\ndef h(fd):\n    locking(fd, 2, 1)\n", encoding="utf-8")
    assert _os_lock_files(tmp_path) == {"event_store.py", "copy.py", "aliased.py", "frm.py"}


def test_ratchet_sees_aliased_and_from_imports(tmp_path):
    cases = {
        "alias.py": "import msvcrt as m\n\n\ndef f(fd):\n    m.locking(fd, 2, 1)\n",
        "frm.py": "from fcntl import flock\n\n\ndef f(fd):\n    flock(fd, 6)\n",
        "frm_as.py": "from fcntl import flock as lk\n\n\ndef f(fd):\n    lk(fd, 6)\n",
        "clean.py": "import fcntl\n\n\ndef f(fd):\n    return fcntl.LOCK_EX\n",
    }
    for name, source in cases.items():
        (tmp_path / name).write_text(source, encoding="utf-8")
    assert _os_lock_files(tmp_path) == {"alias.py", "frm.py", "frm_as.py"}      # red on a copy in any import form; a mere constant is not a call


@pytest.mark.skipif(os.name == "nt", reason="POSIX file modes: Windows has no executable bit to check")
def test_new_lock_file_is_not_executable(tmp_path):
    path = lock_path(tmp_path)
    take_file_lock(path).release()
    assert stat.S_IMODE(path.stat().st_mode) & 0o111 == 0


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q", "-p", "no:cacheprovider"]))
