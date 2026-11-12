"""probe_by_code.py: the durable byte copy, the per-file lock and the recovery of a killed probe (B-373 R9).

The failure these pin: the probe held the author's original bytes only in its own memory, mutated the
file and ran for up to 31 minutes; a role's shell call is killed long before that, a killed process
never runs its `finally`, and the author's file stayed mutated with the only copy of the original gone.
Here the probe is really killed (its stand-in runner kills its parent), the lock is really taken by a
second process, and the recovery is read from the bytes on disk - not from a function's return value.

The runner is the stand-in of `test_probe_by_code.py` with a preamble: it snapshots the copy folder
WHILE the file is mutated (so "the copy was on disk before the first write" is observed, not assumed),
and it can kill the probe that launched it or make the mutated file read-only so a restore fails.
"""
import errno
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness import (SCRIPTS, check, check_eq, check_in, check_not_in, cleanup, finish, run_script,  # noqa: E402
                     temp_dir)

import install_paths  # noqa: E402
import probe_by_code as PBC  # noqa: E402
from test_probe_by_code import (DISPATCH, FAKE_RUN_SUITE, TASK, TEST_FILE_REL, cleanup_beside,  # noqa: E402
                                env_for, model_entries, mutated_line, project, read_record)

PY = sys.executable
TEST_ABS_NAME = "test_calc.py"
STATEMENT = 'assert add(2, 2) == 4, "sum must be 4"'
OLD_NS = 1_600_000_000 * 10 ** 9  # 2020: far enough from "now" that a mtime rule shows

PREAMBLE = r'''
import json as _json
import os as _os
import signal as _signal
import sys as _sys
from pathlib import Path as _Path

_sys.path.insert(0, _os.environ["PROBE_SCRIPTS_DIR"])
if _os.environ.get("PROBE_COPY_SNAPSHOT"):
    import probe_by_code as _pbc
    _dir = _Path(_os.environ["CLAUDE_PROJECT_DIR"]) / "qa-factory" / "state" / "probe-copies"
    _seen = {}
    for _f in sorted(_dir.glob("*")):
        if _f.suffix == ".orig":
            _seen[_f.name] = _f.read_bytes().hex()
        elif _f.suffix == ".meta":
            _seen[_f.name] = _json.loads(_f.read_text(encoding="utf-8"))
            _state, _h = _pbc.try_lock(_dir, _f.stem)  # this runner is a child of the probe: the lock is the probe's
            _seen[_f.stem + ".lock-state"] = _state
            if _h is not None:
                _pbc.release_locks([_h])
    _Path(_os.environ["PROBE_COPY_SNAPSHOT"]).write_text(_json.dumps(_seen), encoding="utf-8")
if _os.environ.get("PROBE_STUB_DIR_OVER"):
    # Make the restore fail in a way no privilege bypasses (a chmod does not stop root, and CI runs as
    # root): when this runner exits, the mutated file is replaced by a same-named DIRECTORY, and a write
    # to a directory path fails for everyone. The bytes it held are kept aside for the test.
    import atexit as _atexit
    import shutil as _shutil

    def _dir_over(_target=_Path(_os.environ["PROBE_STUB_DIR_OVER"]), _keep=_Path(_os.environ["PROBE_STUB_KEEP"])):
        _shutil.copyfile(_target, _keep)
        _target.unlink()
        _target.mkdir()

    _atexit.register(_dir_over)
if _os.environ.get("PROBE_STUB_KILL_PARENT") == "1":
    _os.kill(_os.getppid(), _signal.SIGTERM)  # the role's shell call is killed: no `finally` ever runs
    _sys.exit(3)
'''

HOLDER = r'''
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import probe_by_code as P
root, target = Path(sys.argv[2]), Path(sys.argv[3])
key, shown = P.copy_key(target, root)
state, handle = P.try_lock(P.copy_dir(root), key)
print(state, flush=True)
sys.stdin.read()
'''


def crun(root: Path, stub: Path, test: str, instance: str, **extra):
    """The CLI, as a role runs it. Returns (process, parsed JSON of stdout or {}). t-2064 P4b: the plain call walks every check and needs a
    model entry per check; the window's model file is written first (`model_entries`)."""
    model_entries(root, stub, test, instance)
    proc = run_script("probe_by_code.py", "--task", TASK, "--dispatch", DISPATCH, "--test", test,
                      "--instance", instance, "--mutation", "invert", "--json", cwd=root,
                      env=env_for(root, stub, PROBE_SCRIPTS_DIR=str(SCRIPTS), **extra))
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    try:
        payload = json.loads("\n".join(lines)) if lines and lines[0].startswith("{") else {}
    except ValueError:
        payload = {}
    return proc, payload


def said(record: dict) -> str:
    """Everything the aggregate says in words: its notes and the note of each check row (t-2064 P4b: the old record's `notes` were both)."""
    return " ".join(list(record.get("notes") or []) + [str(r.get("note") or "") for r in record.get("checks") or []])


def release_cli(root: Path, what: str):
    proc = run_script("probe_by_code.py", "--release-copy", what, "--json", cwd=root,
                      env=dict(os.environ, CLAUDE_PROJECT_DIR=str(root)))
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    try:
        payload = json.loads("\n".join(lines)) if lines else {}
    except ValueError:
        payload = {}
    return proc, payload


def holder(root: Path, target: Path, scratch: Path):
    """A live process holding the lock of `target`: -> (Popen, the state it reports)."""
    script = scratch / "holder.py"
    script.write_text(HOLDER, encoding="utf-8")
    proc = subprocess.Popen([PY, "-B", str(script), str(SCRIPTS), str(root), str(target)], stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, text=True, env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
    return proc, (proc.stdout.readline() or "").strip()


def stop(proc) -> None:
    proc.kill()
    proc.wait(timeout=30)
    for stream in (proc.stdin, proc.stdout):
        try:
            stream.close()
        except OSError:
            pass


def lock_state(root: Path, target: Path) -> str:
    key, _shown = PBC.copy_key(target, root)
    state, handle = PBC.try_lock(PBC.copy_dir(root), key)
    if handle is not None:
        PBC.release_locks([handle])
    return state


def copies_in(root: Path) -> list:
    directory = PBC.copy_dir(root)
    return sorted(p.name for p in directory.glob("*") if p.suffix in (".orig", ".meta")) if directory.is_dir() else []


def tree_without_locks(root: Path) -> dict:
    return {p.relative_to(root).as_posix(): (PBC.sha256(p.read_bytes()), p.stat().st_mtime_ns)
            for p in sorted(root.rglob("*")) if p.is_file() and p.suffix != ".lock"}


def stale_copy(root: Path, rel: str, original: bytes, mutated: bytes, *, started: datetime = None,
               timeout_s: int = 60, mtime_ns: int = OLD_NS, extra: dict = None, file_bytes: bytes = None) -> str:
    """The state a killed probe leaves: the file as it stood when the probe died, its `.orig` and `.meta`.
    -> the key. `file_bytes` overrides what the file holds now (an author's later edit)."""
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(mutated if file_bytes is None else file_bytes)
    os.utime(path, ns=(mtime_ns + 5, mtime_ns + 5))
    key, shown = PBC.copy_key(path, root)
    directory = PBC.copy_dir(root)
    directory.mkdir(parents=True, exist_ok=True)
    orig, meta = PBC.copy_files(directory, key)
    orig.write_bytes(original)
    record = {"path": shown, "original_sha": PBC.sha256(original), "mutated_sha": PBC.sha256(mutated),
              "original_mtime_ns": mtime_ns,
              "started_at": (started or datetime.now(timezone.utc)).isoformat(timespec="seconds"),
              "timeout_s": timeout_s, "statement_before": "assert x == 1", "statement_after": "assert not (x == 1)",
              "line": 7}
    record.update(extra or {})
    meta.write_text(json.dumps(record), encoding="utf-8")
    return key


# --- the key -------------------------------------------------------------------------------------------

def keys_are_per_path() -> None:
    root = temp_dir("qa-copy-keys-")
    try:
        a, b = root / "tests" / "a" / "conftest.py", root / "tests" / "b" / "conftest.py"
        for p in (a, b):
            p.parent.mkdir(parents=True)
            p.write_text("x = 1\n", encoding="utf-8")
        key_a, shown_a = PBC.copy_key(a, root)
        key_b, shown_b = PBC.copy_key(b, root)
        check("key: two conftest.py in two folders get distinct keys (a name is no key)", key_a != key_b)
        check_eq("key: 16 hex characters", len(key_a), 16)
        check("key: hex only", all(c in "0123456789abcdef" for c in key_a))
        check_eq("key: the shown path is project-relative POSIX", shown_a, "tests/a/conftest.py")
        check_eq("key: another spelling of the same file is the same key",
                 PBC.copy_key(root / "tests" / "b" / ".." / "a" / "conftest.py", root)[0], key_a)
        check_eq("key: the key is the sha256 of the path, not of the bytes",
                 key_a, PBC.sha256(b"tests/a/conftest.py")[:16])
        if os.name == "nt":
            check_eq("key: on Windows `Tests/X.py` and `tests/x.py` are one file, so one key",
                     PBC.copy_key(root / "Tests" / "X.py", root)[0], PBC.copy_key(root / "tests" / "x.py", root)[0])
        directory = PBC.copy_dir(root)
        check_eq("folder: resolved through runtime_paths, under the project's state/",
                 directory, root / "qa-factory" / "state" / "probe-copies")
        orig, meta = PBC.copy_files(directory, key_a)
        check_eq("files: `<k>.orig` and `<k>.meta`, and `.meta` is deliberately not `.json`",
                 (orig.name, meta.name, meta.suffix), (key_a + ".orig", key_a + ".meta", ".meta"))
    finally:
        cleanup(root)


def the_folder_is_in_the_install_table() -> None:
    for name in ("abc.orig", "abc.meta", "abc.lock"):
        found = install_paths.classify("qa-factory/state/probe-copies/" + name)
        check_eq(f"install-paths: {name} is a carried, machine-local path the manifest does not refuse",
                 (found["class"], found["machine_local"], found["reader"]), ("carried", True, "probe_by_code.py"))
    root = temp_dir("qa-copy-table-")
    try:
        path = root / "qa-factory" / "state" / "probe-copies" / "abc.orig"
        path.parent.mkdir(parents=True)
        path.write_bytes(b"x")
        written = install_paths.write_manifest(root, [{"rel_path": "qa-factory/state/probe-copies/abc.orig"}])
        check_eq("install-paths: write_manifest takes the copy (refused[] empty)", written.get("refused"), [])
    finally:
        cleanup(root)


# --- restore FROM the copy -------------------------------------------------------------------------------

def restore_reads_the_copy() -> None:
    root = temp_dir("qa-copy-restore-")
    try:
        target = root / "t.py"
        original = b"def test_a():\n    assert 1 == 1\n"
        copy = root / "t.orig"
        copy.write_bytes(original)
        target.write_bytes(b"mutated\n")
        os.utime(target, ns=(OLD_NS, OLD_NS))
        stat_result = target.stat()
        # memory says something ELSE than the copy: only a restore that reads the copy comes out verified
        wrong_memory = b"not what the copy holds\n"
        got = PBC.restore(target, wrong_memory, PBC.sha256(original), stat_result, copy=copy)
        check_eq("restore: from the copy, the sha256 of the copy is what is verified", got["verified"], True)
        check_eq("restore: the file holds the copy's bytes, not memory's", target.read_bytes(), original)
        check_eq("restore: and the result says it came from the copy", got.get("restored_from"), "copy")
        check_eq("restore: a .py keeps its old mtime", target.stat().st_mtime_ns, OLD_NS)
        # a copy that no longer matches the sha it was made with is not written over the author's file
        target.write_bytes(b"mutated\n")
        copy.write_bytes(b"damaged copy\n")
        got = PBC.restore(target, original, PBC.sha256(original), stat_result, copy=copy)
        check_eq("restore: a damaged copy falls back to memory, verified", (got["verified"], got.get("restored_from")),
                 (True, "memory"))
        check_in("restore: and says why", "differs", got.get("copy_unreadable", ""))
        check_eq("restore: the author's bytes are back", target.read_bytes(), original)
        # no copy given: the old way, memory
        target.write_bytes(b"mutated\n")
        got = PBC.restore(target, original, PBC.sha256(original), stat_result)
        check_eq("restore: no copy named -> memory, as before, with no `restored_from`",
                 (got["verified"], "restored_from" in got), (True, False))
        # an unreadable copy
        target.write_bytes(b"mutated\n")
        got = PBC.restore(target, original, PBC.sha256(original), stat_result, copy=root / "gone.orig")
        check_eq("restore: a copy that cannot be read falls back to memory", (got["verified"], got.get("restored_from")),
                 (True, "memory"))
        check_in("restore: and names the OS error", "FileNotFoundError", got.get("copy_unreadable", ""))
        # mtime rule: any other file gets "now"
        other = root / "Calc.cs"
        other.write_bytes(b"mutated\n")
        os.utime(other, ns=(OLD_NS, OLD_NS))
        got = PBC.restore(other, b"class C {}\n", PBC.sha256(b"class C {}\n"), other.stat())
        check_eq("mtime: a non-.py file is restored", got["verified"], True)
        check("mtime: and gets 'now', not the old stamp (an incremental build must rebuild it)",
              other.stat().st_mtime_ns > OLD_NS + 10 ** 9 * 3600)
        check_not_in("mtime: no bytecode list for a file that is not Python", "bytecode_dropped", list(got))
    finally:
        cleanup(root)


def begin_copy_is_verified_or_refuses() -> None:
    root = project()
    try:
        path = root / TEST_FILE_REL
        original = path.read_bytes()
        stat_result = path.stat()
        detail = {"statement_before": STATEMENT, "statement_after": "assert not (...)", "line": 6}
        real_sha = PBC.sha256(original)
        made = PBC.begin_copy(root, path, original, real_sha, stat_result, "m" * 64, detail, 77)
        check_eq("begin: `.orig` holds the original bytes", made["orig"].read_bytes(), original)
        meta = json.loads(made["meta"].read_text(encoding="utf-8"))
        check_eq("begin: the record names what recovery needs",
                 {k: meta[k] for k in ("path", "original_sha", "mutated_sha", "original_mtime_ns", "timeout_s",
                                       "statement_before", "statement_after", "line")},
                 {"path": TEST_FILE_REL, "original_sha": real_sha, "mutated_sha": "m" * 64,
                  "original_mtime_ns": stat_result.st_mtime_ns, "timeout_s": 77, "statement_before": STATEMENT,
                  "statement_after": "assert not (...)", "line": 6})
        check("begin: and when the probe started", PBC.copy_deadline(meta) is not None)
        for stale in (made["orig"], made["meta"]):
            stale.unlink()
        # the copy read back does not match: a refusal, nothing left behind
        real = PBC.sha256
        PBC.sha256 = lambda data: "0" * 64
        try:
            try:
                PBC.begin_copy(root, path, original, real_sha, stat_result, "m" * 64, detail, 77)
                check("begin: a copy that does not verify is refused", False)
            except PBC.Refusal as exc:
                check_in("begin: the refusal says the file is not mutated without a copy", "not mutated without one", str(exc))
        finally:
            PBC.sha256 = real
        check_eq("begin: and it leaves no half-made copy", copies_in(root), [])
    finally:
        cleanup(root)
        cleanup_beside(root)


# --- the lock: held is not broken ------------------------------------------------------------------------

def held_is_not_broken() -> None:
    root = temp_dir("qa-copy-lock-")
    real = PBC._os_lock
    try:
        directory = PBC.copy_dir(root)
        state, first = PBC.try_lock(directory, "a" * 16)
        check_eq("lock: a free lock is taken", state, "locked")
        check_eq("lock: the same file again, same process, is HELD", PBC.try_lock(directory, "a" * 16)[0], "held")
        state, other = PBC.try_lock(directory, "b" * 16)
        check_eq("lock: another file is free", state, "locked")
        PBC.release_locks([other])
        PBC.release_locks([first])
        state, again = PBC.try_lock(directory, "a" * 16)
        check_eq("lock: released, it can be taken again", state, "locked")
        PBC.release_locks([again])
        check("lock: the lock file stays (never deleted, as event_store.lock)", (directory / ("a" * 16 + ".lock")).is_file())

        def raising(exc):
            def lock(handle):
                raise exc
            return lock

        for name, code in (("EACCES", errno.EACCES), ("EAGAIN", errno.EAGAIN), ("EWOULDBLOCK", errno.EWOULDBLOCK),
                           ("EDEADLK", errno.EDEADLK)):
            PBC._os_lock = raising(OSError(code, name))
            check_eq(f"lock: OSError {name} means HELD", PBC.try_lock(directory, "c" * 16)[0], "held")
        for name, exc in (("EBADF", OSError(errno.EBADF, "EBADF")), ("ENOSPC", OSError(errno.ENOSPC, "ENOSPC")),
                          ("EIO", OSError(errno.EIO, "EIO")), ("ImportError", ImportError("no msvcrt"))):
            PBC._os_lock = raising(exc)
            check_eq(f"lock: {name} means the PRIMITIVE failed, not that someone holds it",
                     PBC.try_lock(directory, "c" * 16)[0], "broken")
        PBC._os_lock = real
        blocker = root / "qa-factory" / "state" / "blocked"
        blocker.write_text("a file where the folder should be", encoding="utf-8")
        check_eq("lock: a folder that cannot be made is the primitive failing too",
                 PBC.try_lock(blocker / "probe-copies", "d" * 16)[0], "broken")
    finally:
        PBC._os_lock = real
        cleanup(root)


# --- the fallback deadline (only when the lock primitive itself fails) ------------------------------------

def fallback_deadline() -> None:
    root = temp_dir("qa-copy-deadline-")
    real = PBC._os_lock
    try:
        original = b"def test_a():\n    assert x == 1\n"
        mutated = b"def test_a():\n    assert not (x == 1)\n"
        started = datetime(2026, 10, 6, 12, 0, 0, tzinfo=timezone.utc)
        deadline = started + timedelta(seconds=100 + 120)

        def no_primitive(handle):
            raise ImportError("the lock module is missing here")

        key = stale_copy(root, "tests/t.py", original, mutated, started=started, timeout_s=100)
        path = root / "tests" / "t.py"
        shown = "tests/t.py"
        PBC._os_lock = no_primitive
        notes: list = []
        try:
            PBC.claim_key(root, key, shown, own=True, notes=notes, now=deadline)
            check("deadline: AT the deadline the probe is still running: refused", False)
        except PBC.Refusal as exc:
            check_in("deadline: AT the deadline: refused, naming the file and the deadline",
                     "a probe of tests/t.py is running until 2026-10-06T12:03:40", str(exc))
        check_eq("deadline: and nothing was touched", (path.read_bytes(), copies_in(root)),
                 (mutated, [key + ".meta", key + ".orig"]))
        check_eq("deadline: another file's claim at the deadline skips quietly (no refusal, no note)",
                 (PBC.claim_key(root, key, shown, own=False, notes=notes, now=deadline), notes), (None, []))
        got = PBC.claim_key(root, key, shown, own=True, notes=notes, now=deadline + timedelta(seconds=1))
        check_eq("deadline: ONE SECOND beyond it the probe is dead: recovered, no handle in fallback mode", got, None)
        check_eq("deadline: the author's bytes are back", path.read_bytes(), original)
        check_eq("deadline: the copy is gone", copies_in(root), [])
        check_eq("deadline: one note says what was recovered", len(notes), 1)
        check_in("deadline: and which file", "recovered tests/t.py", notes[0])

        # L2: an OSError that says HELD is never the fallback, however old the record
        key = stale_copy(root, "tests/t.py", original, mutated, started=started, timeout_s=100)
        notes = []

        def held(handle):
            raise OSError(errno.EACCES, "locked by another process")

        PBC._os_lock = held
        try:
            PBC.claim_key(root, key, shown, own=True, notes=notes, now=deadline + timedelta(days=30))
            check("held: an EACCES lock is a running probe even past the record's deadline", False)
        except PBC.Refusal as exc:
            check_in("held: refused as running", "a probe of tests/t.py is running", str(exc))
            check_not_in("held: and no deadline is quoted (the lock, not the clock, decided)", " until ", str(exc))
        check_eq("held: the mutated file was left alone", path.read_bytes(), mutated)

        def broken(handle):
            raise OSError(errno.ENOSPC, "no space")

        PBC._os_lock = broken
        PBC.claim_key(root, key, shown, own=True, notes=notes, now=deadline + timedelta(seconds=1))
        check_eq("broken: any other errno IS the fallback: past the deadline it recovers", path.read_bytes(), original)

        # a record the clock cannot read: the lock cannot say either - unresolved, never a guess
        key = stale_copy(root, "tests/t.py", original, mutated, extra={"started_at": "not a time"})
        PBC._os_lock = no_primitive
        try:
            PBC.claim_key(root, key, shown, own=True, notes=[], now=deadline)
            check("deadline: no readable start time and no lock: refused", False)
        except PBC.Refusal as exc:
            check_in("deadline: refused, saying the OS lock cannot tell", "cannot say whether that probe is alive", str(exc))
        check_eq("deadline: and the file is untouched", path.read_bytes(), mutated)
    finally:
        PBC._os_lock = real
        cleanup(root)


# --- recovery: what a dead probe left ---------------------------------------------------------------------

def recovery_cases() -> None:
    root = temp_dir("qa-copy-recover-")
    try:
        original = b"def test_a():\n    assert x == 1\n"
        mutated = b"def test_a():\n    assert not (x == 1)\n"
        # the file already holds the original: only the copy goes, and nothing is said
        key = stale_copy(root, "tests/same.py", original, mutated, file_bytes=original)
        notes: list = []
        handle = PBC.claim_key(root, key, "tests/same.py", own=True, notes=notes)
        check_eq("recovery: a file that already holds the original loses only its copy", (copies_in(root), notes), ([], []))
        check("recovery: and the lock is taken", handle is not None)
        PBC.release_locks([handle])

        # the file holds the mutated bytes: restored from the copy, the old mtime back (a .py)
        key = stale_copy(root, "tests/mut.py", original, mutated)
        notes = []
        handle = PBC.claim_key(root, key, "tests/mut.py", own=True, notes=notes)
        PBC.release_locks([handle])
        target = root / "tests" / "mut.py"
        check_eq("recovery: the mutated file is restored from the copy", target.read_bytes(), original)
        check_eq("recovery: a .py gets the mtime it had", target.stat().st_mtime_ns, OLD_NS)
        check_eq("recovery: the copy is deleted after the verification", copies_in(root), [])
        check_eq("recovery: one note, naming the file and the statement the probe left", len(notes), 1)
        check_in("recovery: the note names the line's mutated text", "assert not (x == 1)", notes[0])

        # any other file gets "now"
        key = stale_copy(root, "tests/Calc.cs", b"class A {}\n", b"class B {}\n")
        PBC.release_locks([PBC.claim_key(root, key, "tests/Calc.cs", own=True, notes=[])])
        cs = root / "tests" / "Calc.cs"
        check_eq("recovery: a non-Python file is restored too", cs.read_bytes(), b"class A {}\n")
        check("recovery: with mtime 'now', not the old stamp", cs.stat().st_mtime_ns > OLD_NS + 10 ** 9 * 3600)

        # liveness is never a pid: a record that names a LIVE pid, with a free lock, is recovered
        key = stale_copy(root, "tests/pid.py", original, mutated, extra={"pid": os.getpid()})
        PBC.claim_key(root, key, "tests/pid.py", own=True, notes=[])
        check_eq("recovery: a live pid in the record changes nothing - only the lock says alive",
                 (root / "tests" / "pid.py").read_bytes(), original)

        # the author edited the file after the crash: refused for this probe's own file, copy kept
        edited = b"def test_a():\n    assert x == 2  # the author's newer edit\n"
        key = stale_copy(root, "tests/edit.py", original, mutated, file_bytes=edited)
        orig, meta = PBC.copy_files(PBC.copy_dir(root), key)
        try:
            PBC.claim_key(root, key, "tests/edit.py", own=True, notes=[])
            check("edit: an edited file is refused for the probe's own file", False)
        except PBC.Refusal as exc:
            text = str(exc)
            check_in("edit: names the file", "tests/edit.py", text)
            check_in("edit: names the file's sha", PBC.sha256(edited), text)
            check_in("edit: and the original sha", PBC.sha256(original), text)
            check_in("edit: and the mutated sha", PBC.sha256(mutated), text)
            check_in("edit: and the copy's path", str(orig), text)
            check_in("edit: the line and what it reads if the mutation is still there", "line 7 still reads `assert not (x == 1)`", text)
            check_in("edit: what to put back", "put back `assert x == 1`", text)
            check_in("edit: or copy the copy over", f"copy {orig} over the file", text)
            check_in("edit: the door", "probe_by_code.py --release-copy tests/edit.py", text)
            check_in("edit: the addressee is the test's author, through a tooling finding", "tooling finding to return to the test's author", text)
            check_in("edit: and the critic is told it does not edit test code", "not an edit for the critic to make", text)
            check_in("edit: nothing changed", "Nothing was changed", text)
        check_eq("edit: the author's newer edit wins: bytes untouched", (root / "tests" / "edit.py").read_bytes(), edited)
        check_eq("edit: the copy is kept", copies_in(root), sorted([meta.name, orig.name]))
        # ... and for ANY OTHER file the same copy is a note, and the scan goes on (P1)
        notes = []
        PBC.scan_copies(root, skip_keys=set(), notes=notes)
        check_eq("edit: another probe's scan leaves it and says so in ONE note", len(notes), 1)
        check_in("edit: the note carries the door", "--release-copy tests/edit.py", notes[0])
        check_eq("edit: and still overwrites nothing", (root / "tests" / "edit.py").read_bytes(), edited)
        for stale in (orig, meta):
            stale.unlink()

        # the file is gone
        key = stale_copy(root, "tests/gone.py", original, mutated)
        (root / "tests" / "gone.py").unlink()
        try:
            PBC.claim_key(root, key, "tests/gone.py", own=True, notes=[])
            check("gone: a deleted file is refused", False)
        except PBC.Refusal as exc:
            check_in("gone: the file cannot be read", "cannot be read now", str(exc))
        PBC.scan_copies(root, skip_keys=set(), notes=[])
        for name in copies_in(root):
            (PBC.copy_dir(root) / name).unlink()

        # a damaged copy is never written over the file
        key = stale_copy(root, "tests/dmg.py", original, mutated)
        orig, meta = PBC.copy_files(PBC.copy_dir(root), key)
        orig.write_bytes(b"damaged")
        try:
            PBC.claim_key(root, key, "tests/dmg.py", own=True, notes=[])
            check("damaged: a copy whose bytes do not match its sha is refused", False)
        except PBC.Refusal as exc:
            check_in("damaged: says so", "no longer match", str(exc))
        check_eq("damaged: the file is untouched", (root / "tests" / "dmg.py").read_bytes(), mutated)
        for stale in (orig, meta):
            stale.unlink()

        # a record that cannot be read: the door takes the key when no file can be named
        key = stale_copy(root, "tests/bad.py", original, mutated)
        orig, meta = PBC.copy_files(PBC.copy_dir(root), key)
        meta.write_text("{not json", encoding="utf-8")
        notes = []
        PBC.scan_copies(root, skip_keys=set(), notes=notes)
        check_eq("unreadable record: a note, not a crash", len(notes), 1)
        check_in("unreadable record: the door names the key", f"--release-copy {key}", notes[0])
        try:
            PBC.claim_key(root, key, "tests/bad.py", own=True, notes=[])
            check("unreadable record: refused for the probe's own file", False)
        except PBC.Refusal as exc:
            check_in("unreadable record: the own file's door names the file", "--release-copy tests/bad.py", str(exc))
        for stale in (orig, meta):
            stale.unlink()

        # an orphan `.orig` (a probe that died before its record: nothing was mutated yet) is not a copy
        directory = PBC.copy_dir(root)
        (directory / ("f" * 16 + ".orig")).write_bytes(b"orphan")
        notes = []
        PBC.scan_copies(root, skip_keys=set(), notes=notes)
        check_eq("orphan: a scan ignores a `.orig` with no record and says nothing", (notes, (directory / ("f" * 16 + ".orig")).is_file()),
                 ([], True))
        # nothing to scan: nothing is created
        empty = temp_dir("qa-copy-empty-")
        try:
            PBC.scan_copies(empty, skip_keys=set(), notes=[])
            check("scan: with no copy folder it makes none", not PBC.copy_dir(empty).exists())
        finally:
            cleanup(empty)
    finally:
        cleanup(root)


# --- the whole probe -----------------------------------------------------------------------------------------

def the_copy_is_on_disk_during_the_run(stub: Path) -> None:
    root = project()
    snap = stub.parent / "snapshot.json"
    try:
        path = root / TEST_FILE_REL
        original = path.read_bytes()
        os.utime(path, ns=(OLD_NS, OLD_NS))
        proc, record = crun(root, stub, f"{TEST_FILE_REL}::test_add", "test_add", PROBE_COPY_SNAPSHOT=str(snap))
        check("normal: exit 0", proc.returncode == 0, proc.stdout + proc.stderr)
        check_eq("normal: intended_failure", record.get("verdict"), "intended_failure")
        seen = json.loads(snap.read_text(encoding="utf-8"))
        key, _shown = PBC.copy_key(path, root)
        check_eq("during: the original bytes were on disk while the file was mutated", seen.get(key + ".orig"), original.hex())
        meta = seen.get(key + ".meta") or {}
        check_eq("during: the record names the file", meta.get("path"), TEST_FILE_REL)
        check_eq("during: and the original sha", meta.get("original_sha"), PBC.sha256(original))
        check("during: and a DIFFERENT mutated sha", meta.get("mutated_sha") not in (None, PBC.sha256(original)))
        check_eq("during: and the original mtime", meta.get("original_mtime_ns"), OLD_NS)
        # PRODUCT QUESTION 14 (t-2064-p4b2t3-report.md): the walk's copy record carries `statement_before` None (begin_copy's `details[0]` of an
        # invert check, probe_by_code.py:6353 -> :3763), and the recovery text of :3620 says "put back `None`"; the old road wrote the statement
        check_eq("during: the statement before (PRODUCT QUESTION 14)", meta.get("statement_before"), STATEMENT)
        # t-2045 N2: the Python marker is the joined expression, its token this run's own
        check("during: the statement after is the mutated one",
              re.fullmatch(r"assert not \(add\(2, 2\) == 4\), '-'\.join\(\['qa-probe', '[0-9a-f]{12}'\]\)",
                           str(meta.get("statement_after"))) is not None, str(meta.get("statement_after")))
        check_eq("during: the line", meta.get("line"), 6)
        # t-2064 P4b (old -> new): the timeout of the one run (RUN_TIMEOUT_S) -> what is LEFT of the walk's one shared budget when the row starts,
        # rounded up to the second (`int(left) + 1`, probe_by_code.py:6353, EP-J): the first row of a plan sees the whole budget, plus that second
        check("during: the timeout the probe runs under (the walk's budget left, rounded up)",
              PBC.RUN_TIMEOUT_S <= (meta.get("timeout_s") or 0) <= PBC.RUN_TIMEOUT_S + 1, str(meta.get("timeout_s")))
        check("during: and when it started", PBC.copy_deadline(meta) is not None)
        check_eq("during: the lock was HELD by the probe while its runner ran", seen.get(key + ".lock-state"), "held")
        check_eq("after: the file is byte-identical", path.read_bytes(), original)
        check_eq("after: a .py has its old mtime back", path.stat().st_mtime_ns, OLD_NS)
        check_eq("after: no copy is left", copies_in(root), [])
        restore = record.get("restore") or {}
        # t-2064 P4b (old -> new): the aggregate's `restore` is {verified, sha256, runs}: `restored_from == "copy"`, `copy_kept` and `copy` (where the
        # copy was) are not carried. The reason this pin keeps: the restore is VERIFIED to the author's bytes and the copy is gone (`no copy is
        # left` just above; `during:` pinned where the copy stood, by the file name the runner saw)
        check_eq("after: the restore is verified to the author's bytes, once", (restore.get("verified"), restore.get("sha256"), restore.get("runs")),
                 (True, PBC.sha256(original), 1))
        check_eq("after: the lock is free", lock_state(root, path), "locked")
    finally:
        cleanup(root)
        cleanup_beside(root)


def a_killed_probe_is_recovered(stub: Path) -> None:
    root = project()
    try:
        path = root / TEST_FILE_REL
        original = path.read_bytes()
        original_sha = PBC.sha256(original)
        os.utime(path, ns=(OLD_NS, OLD_NS))
        key, _shown = PBC.copy_key(path, root)
        proc, payload = crun(root, stub, f"{TEST_FILE_REL}::test_add", "test_add", PROBE_STUB_KILL_PARENT="1")
        check("killed: the probe died with its runner's signal (no exit 0, no answer)", proc.returncode != 0 and not payload,
              f"{proc.returncode} {proc.stdout[:200]}")
        left = path.read_bytes()
        # t-2045 N2: the mutated statement carries the joined marker expression (the same shape as `invert_plain_assert`)
        check("killed: the author's file was left MUTATED (the failure this node fixes)",
              re.search(rb"assert not \(add\(2, 2\) == 4\), '-'\.join\(\['qa-probe', '[0-9a-f]{12}'\]\)", left) is not None)
        orig, meta = PBC.copy_files(PBC.copy_dir(root), key)
        check_eq("killed: but the original bytes are on disk", orig.read_bytes(), original)
        left_meta = json.loads(meta.read_text(encoding="utf-8"))
        check_eq("killed: with a record that says what the mutated bytes are", left_meta["mutated_sha"], PBC.sha256(left))
        check_eq("killed: the dead probe's lock was released by the OS", lock_state(root, path), "locked")
        proc, record = crun(root, stub, f"{TEST_FILE_REL}::test_add", "test_add")
        check("recovery: the next probe runs", proc.returncode == 0, proc.stdout + proc.stderr)
        check_eq("recovery: and answers intended_failure", record.get("verdict"), "intended_failure")
        check_in("recovery: with a note about what it recovered", f"recovered {TEST_FILE_REL}", said(record))
        check_eq("recovery: the author's bytes are back", path.read_bytes(), original)
        check_eq("recovery: with the old mtime", path.stat().st_mtime_ns, OLD_NS)
        check_eq("recovery: and no copy left", copies_in(root), [])
        # POSITION: the scan came BEFORE the first read, so no mutated byte was taken for the author's
        check_eq("position: test_file_sha256 is the author's bytes, not the dead probe's", record.get("test_file_sha256"), original_sha)
        check_eq("position: the mutated file's recorded original is the author's", (record.get("mutated_file") or {}).get("sha256"),
                 original_sha)
        # t-2064 P4b (old -> new): `mutation_detail.statement_before` / `.marker` are not in the aggregate; the bytes the runner saw are: its
        # first run's mutated line is the inversion of the AUTHOR'S statement, ONCE (the marker is of the author's expression, and no `not (not`)
        seen_line = mutated_line(root, record, 6).strip()
        check("position: the statement mutated is the author's, not an inversion of an inversion",
              re.fullmatch(r"assert not \(add\(2, 2\) == 4\), '-'\.join\(\['qa-probe', '[0-9a-f]{12}'\]\)", seen_line) is not None, seen_line)
    finally:
        cleanup(root)
        cleanup_beside(root)


def a_running_probe_blocks_only_its_own_file(stub: Path) -> None:
    root = project()
    scratch = temp_dir("qa-copy-holder-")
    try:
        path = root / TEST_FILE_REL
        original = path.read_bytes()
        proc_h, state = holder(root, path, scratch)
        try:
            check_eq("running: a second process holds the lock of the test file", state, "locked")
            check_eq("running: and it is held for the first", lock_state(root, path), "held")
            model_entries(root, stub, f"{TEST_FILE_REL}::test_add", "test_add")    # t-2064 P4b: the wrapper's own file, before the snapshot
            before = tree_without_locks(root)
            proc, payload = crun(root, stub, f"{TEST_FILE_REL}::test_add", "test_add")
            check_eq("running: the second probe is refused (exit 2)", (proc.returncode, payload.get("status")), (2, "refused"))
            check_in("running: naming the file", f"a probe of {TEST_FILE_REL} is running", payload.get("error", ""))
            check_in("running: and saying nothing was changed", "Nothing was changed", payload.get("error", ""))
            check_eq("running: no file changed, none written (the lock file is the only trace)", tree_without_locks(root), before)
            check_eq("running: the bytes are the author's", path.read_bytes(), original)
        finally:
            stop(proc_h)
        check_eq("running: when that process dies the lock is free (the OS released it)", lock_state(root, path), "locked")
        # the lock of ANOTHER file does not block this one
        other = root / "tests" / "other.py"
        other.write_text("x = 1\n", encoding="utf-8")
        proc_h, state = holder(root, other, scratch)
        try:
            proc, record = crun(root, stub, f"{TEST_FILE_REL}::test_add", "test_add")
            check("other: a lock on another file does not stop this probe", proc.returncode == 0, proc.stdout + proc.stderr)
            check_eq("other: and it answers", record.get("verdict"), "intended_failure")
        finally:
            stop(proc_h)
    finally:
        cleanup(scratch)
        cleanup(root)
        cleanup_beside(root)


def a_stale_copy_of_another_file_does_not_stop_this_probe(stub: Path) -> None:
    """L3: the copies are project-wide, so a stale copy of file X left in story A refuses story B's probe
    of file Y only if X is Y - or Y's oracle."""
    root = project()
    try:
        original = b"def f():\n    assert 1 == 1\n"
        mutated = b"def f():\n    assert not (1 == 1)\n"
        edited = b"def f():\n    assert 2 == 2  # the author's edit\n"
        stale_copy(root, "tests/other.py", original, mutated, file_bytes=edited)
        helper = root / "tests" / "expectations.py"
        helper_original = helper.read_bytes()
        helper_edited = helper_original + b"# the author edited this after the crash\n"
        stale_copy(root, "tests/expectations.py", helper_original, helper_original + b"# mutated\n", file_bytes=helper_edited)
        key_other, _ = PBC.copy_key(root / "tests" / "other.py", root)
        key_helper, _ = PBC.copy_key(helper, root)
        model_entries(root, stub, f"{TEST_FILE_REL}::test_via_helper", "test_via_helper")    # t-2064 P4b: the wrapper's own file, before the snapshot
        before = tree_without_locks(root)
        # (1) the oracle of this probe is the helper whose stale copy cannot be applied: a refusal, nothing changed
        proc, payload = crun(root, stub, f"{TEST_FILE_REL}::test_via_helper", "test_via_helper")
        check_eq("oracle: a stale copy of THIS probe's oracle refuses it (exit 2)", (proc.returncode, payload.get("status")),
                 (2, "refused"))
        check_in("oracle: naming the helper", "tests/expectations.py", payload.get("error", ""))
        check_in("oracle: and the door", "--release-copy tests/expectations.py", payload.get("error", ""))
        check_eq("oracle: nothing in the tree changed", tree_without_locks(root), before)
        # (2) a test that never touches either file goes on, with a note
        proc, record = crun(root, stub, f"{TEST_FILE_REL}::test_add", "test_add")
        check("other: a stale copy of an UNRELATED file is a note, and the probe goes on", proc.returncode == 0,
              proc.stdout + proc.stderr)
        check_eq("other: it answered", record.get("verdict"), "intended_failure")
        notes = said(record)
        check_in("other: the note names that file", "tests/other.py", notes)
        check_in("other: and its door", "--release-copy tests/other.py", notes)
        check_eq("other: that file is untouched", (root / "tests" / "other.py").read_bytes(), edited)
        check_eq("other: and its copy is kept", [n for n in copies_in(root) if n.startswith(key_other)],
                 sorted([key_other + ".meta", key_other + ".orig"]))
        check_eq("other: so is the helper's", [n for n in copies_in(root) if n.startswith(key_helper)],
                 sorted([key_helper + ".meta", key_helper + ".orig"]))
    finally:
        cleanup(root)
        cleanup_beside(root)


def a_live_probe_of_the_oracle_blocks_the_probe_that_needs_it(stub: Path) -> None:
    root = project()
    scratch = temp_dir("qa-copy-oracle-")
    try:
        helper = root / "tests" / "expectations.py"
        proc_h, state = holder(root, helper, scratch)
        try:
            check_eq("oracle lock: another process holds the helper's lock", state, "locked")
            model_entries(root, stub, f"{TEST_FILE_REL}::test_via_helper", "test_via_helper")    # t-2064 P4b: the wrapper's own file, before the snapshot
            before = tree_without_locks(root)
            proc, payload = crun(root, stub, f"{TEST_FILE_REL}::test_via_helper", "test_via_helper")
            check_eq("oracle lock: the probe whose oracle that is is refused", (proc.returncode, payload.get("status")), (2, "refused"))
            check_in("oracle lock: naming the helper", "a probe of tests/expectations.py is running", payload.get("error", ""))
            check_eq("oracle lock: tree unchanged", tree_without_locks(root), before)
            proc, record = crun(root, stub, f"{TEST_FILE_REL}::test_add", "test_add")
            check_eq("oracle lock: a test that does not need it is not blocked", (proc.returncode, record.get("verdict")),
                     (0, "intended_failure"))
        finally:
            stop(proc_h)
    finally:
        cleanup(scratch)
        cleanup(root)
        cleanup_beside(root)


def an_unverified_restore_keeps_the_copy_and_names_it(stub: Path) -> None:
    root = project()
    try:
        path = root / TEST_FILE_REL
        original = path.read_bytes()
        key, _shown = PBC.copy_key(path, root)
        orig, meta = PBC.copy_files(PBC.copy_dir(root), key)
        kept = stub.parent / "mutated-bytes.bin"
        proc, record = crun(root, stub, f"{TEST_FILE_REL}::test_add", "test_add",
                            PROBE_STUB_DIR_OVER=str(path), PROBE_STUB_KEEP=str(kept))
        check_eq("unverified: the exit is 1", proc.returncode, 1)
        check("unverified: the restore had a DIRECTORY at the file's path to write to (no privilege bypasses that)",
              path.is_dir())
        restore = record.get("restore") or {}
        # t-2064 P4b (old -> new): `restore.copy_kept` is not in the aggregate's `restore` ({verified, sha256, runs, error}); that the copy was kept
        # is the next pin (both files are on disk). What this pin keeps: the restore says it was NOT verified
        check_eq("unverified: the restore says it was not verified", restore.get("verified"), False)
        check_eq("unverified: both files are kept (never deleted before the verification)", (orig.is_file(), meta.is_file()),
                 (True, True))
        check_eq("unverified: the copy still holds the original", orig.read_bytes(), original)
        # the probe resolves the project root (a temp dir may be spelled 8.3 on Windows); so does this
        # PRODUCT QUESTION 15 (t-2064-p4b2t3-report.md): the walk's stderr line says "could not be verified restored (sha256 None) - stop and restore
        # <file> by hand": it names neither the copy to put back (`copy <orig> over <file>`) nor the sha of the author's bytes (it prints None);
        # the old road's line named both (FR-1: what to do and how). Both pins stay RED
        check_in("unverified: stderr names the one move that undoes it (PRODUCT QUESTION 15)", f"copy {orig.resolve()} over {path.resolve()}",
                 proc.stderr)
        check_in("unverified: and the sha of the bytes it could not put back (PRODUCT QUESTION 15)", PBC.sha256(original), proc.stderr)
        check_eq("unverified: no receipt (a receipt vouching for a restore nobody verified)", record.get("receipt"), None)
        check("unverified: the mutated bytes the runner saw are not the author's", kept.read_bytes() != original)
        # the file is not there to probe: a refusal, and the copy stays
        proc, payload = crun(root, stub, f"{TEST_FILE_REL}::test_add", "test_add")
        check_eq("unverified: a probe with no file at the path is a refusal", (proc.returncode, payload.get("status")), (2, "refused"))
        check_in("unverified: saying so", f"no file {TEST_FILE_REL}", payload.get("error", ""))
        check_eq("unverified: and the copy is still there", (orig.is_file(), meta.is_file()), (True, True))
        # the author's file is back as the killed probe left it (mutated): the next probe puts it right
        path.rmdir()
        path.write_bytes(kept.read_bytes())
        proc, answer = crun(root, stub, f"{TEST_FILE_REL}::test_add", "test_add")
        check("unverified: writable again, the next probe goes on", proc.returncode == 0, proc.stdout + proc.stderr)
        check_in("unverified: and says it recovered the file", f"recovered {TEST_FILE_REL}", said(answer))
        check_eq("unverified: the author's bytes are back", path.read_bytes(), original)
        check_eq("unverified: and the copy is gone", copies_in(root), [])
    finally:
        cleanup(root)
        cleanup_beside(root)


def no_copy_no_mutation(stub: Path) -> None:
    """The invariant: the author's file is never mutated without a verified copy on disk. Here the
    folder for the copies cannot be made (a FILE stands where it should be)."""
    root = project()
    try:
        path = root / TEST_FILE_REL
        original = path.read_bytes()
        folder = PBC.copy_dir(root)
        folder.parent.mkdir(parents=True, exist_ok=True)
        folder.write_text("a file where the folder of copies should be", encoding="utf-8")
        model_entries(root, stub, f"{TEST_FILE_REL}::test_add", "test_add")    # t-2064 P4b: the wrapper's own file, before the snapshot
        before = tree_without_locks(root)
        proc, payload = crun(root, stub, f"{TEST_FILE_REL}::test_add", "test_add")
        # PRODUCT QUESTION 16 (t-2064-p4b2t3-report.md): `begin_copy` failing (probe_by_code.py:3755, a FILE where the folder should be) is caught
        # per row by the walk (:6353): exit 1, the row `incomplete` cause `tooling` with the failure in its note, the aggregate and the check's
        # record WRITTEN, no refusal "not mutated without one" and no "Nothing was changed". The invariant itself holds (the bytes below are the
        # author's; `restore.runs` 0: nothing was mutated). The pins about the REFUSAL stay RED
        check_eq("no copy: refused before any write (exit 2) (PRODUCT QUESTION 16)", (proc.returncode, payload.get("status")), (2, "refused"))
        check_in("no copy: the refusal says the file is not mutated without one (PRODUCT QUESTION 16)", "not mutated without one", payload.get("error", ""))
        check_in("no copy: and ends 'Nothing was changed' (PRODUCT QUESTION 16)", "Nothing was changed", payload.get("error", ""))
        check_eq("no copy: the author's bytes and mtime are untouched, no record written (PRODUCT QUESTION 16)", tree_without_locks(root), before)
        check_eq("no copy: bytes", path.read_bytes(), original)
        check_eq("no copy: no probe record (PRODUCT QUESTION 16)", read_record(root, "test_add"), {})
    finally:
        cleanup(root)
        cleanup_beside(root)


# --- the door: --release-copy --------------------------------------------------------------------------------------

def release_copy_is_the_door(stub: Path) -> None:
    root = project()
    scratch = temp_dir("qa-copy-release-")
    try:
        original = b"def f():\n    assert 1 == 1\n"
        mutated = b"def f():\n    assert not (1 == 1)\n"
        edited = b"def f():\n    assert 2 == 2\n"
        key = stale_copy(root, "tests/other.py", original, mutated, file_bytes=edited)
        path = root / "tests" / "other.py"
        orig, meta = PBC.copy_files(PBC.copy_dir(root), key)
        # held: refused, nothing deleted
        proc_h, state = holder(root, path, scratch)
        try:
            proc, payload = release_cli(root, "tests/other.py")
            check_eq("release: while a probe holds the file it refuses (exit 2)", (proc.returncode, payload.get("status")),
                     (2, "refused"))
            check_in("release: naming the running probe", "a probe of tests/other.py is running", payload.get("error", ""))
            check_in("release: and its door (FR-1/FR-57)",
                     "Release it again once that probe has ended (a killed probe frees the lock).", payload.get("error", ""))
            check_eq("release: and deletes nothing", (orig.is_file(), meta.is_file()), (True, True))
        finally:
            stop(proc_h)
        proc, payload = release_cli(root, "tests/other.py")
        check_eq("release: with the lock free it exits 0", (proc.returncode, payload.get("status")), (0, "released"))
        check_eq("release: the copy and its record are deleted", (orig.exists(), meta.exists()), (False, False))
        check_eq("release: the record is printed first", (payload.get("record") or {}).get("original_sha"), PBC.sha256(original))
        check_eq("release: and the file is exactly as the author left it", path.read_bytes(), edited)
        # nothing to release
        proc, payload = release_cli(root, "tests/other.py")
        check_eq("release: with no copy held it says so and exits 0", (proc.returncode, payload.get("status")), (0, "no_copy"))
        # the 16-hex key names a copy whose record is unreadable
        key = stale_copy(root, "tests/bad.py", original, mutated)
        orig, meta = PBC.copy_files(PBC.copy_dir(root), key)
        meta.write_text("{broken", encoding="utf-8")
        proc, payload = release_cli(root, key)
        check_eq("release: a copy with an unreadable record is released by its key", (proc.returncode, payload.get("status")),
                 (0, "released"))
        check_in("release: saying the record was unreadable", "unreadable", json.dumps(payload.get("record")))
        check_eq("release: both files gone", (orig.exists(), meta.exists()), (False, False))
        # the other arguments are still required for a probe
        proc = run_script("probe_by_code.py", "--task", TASK, cwd=root, env=dict(os.environ, CLAUDE_PROJECT_DIR=str(root)))
        check_eq("release: a probe without its arguments is still an argument error (exit 2)", proc.returncode, 2)
        check_in("release: naming what is missing", "--dispatch", proc.stderr)
    finally:
        cleanup(scratch)
        cleanup(root)
        cleanup_beside(root)


def main() -> None:
    keys_are_per_path()
    the_folder_is_in_the_install_table()
    restore_reads_the_copy()
    begin_copy_is_verified_or_refuses()
    held_is_not_broken()
    fallback_deadline()
    recovery_cases()
    stub_dir = temp_dir("qa-probe-copy-stub-")
    stub = stub_dir / "fake_run_suite.py"
    stub.write_text(PREAMBLE + FAKE_RUN_SUITE, encoding="utf-8")
    try:
        the_copy_is_on_disk_during_the_run(stub)
        a_killed_probe_is_recovered(stub)
        a_running_probe_blocks_only_its_own_file(stub)
        a_stale_copy_of_another_file_does_not_stop_this_probe(stub)
        a_live_probe_of_the_oracle_blocks_the_probe_that_needs_it(stub)
        an_unverified_restore_keeps_the_copy_and_names_it(stub)
        no_copy_no_mutation(stub)
        release_copy_is_the_door(stub)
    finally:
        cleanup(stub_dir)
    finish("test_probe_by_code_copy")


if __name__ == "__main__":
    main()
