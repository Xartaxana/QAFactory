"""SC1-4b: the collect pack's telemetry count (set B8, `collect_pack._sum_telemetry`) shares the merge lock with the
Stop-time pass (`telemetry_capture.maintain_dir`) and counts every span line ONCE across all files.

Why: the Stop pass now moves lines from `hook-<pid>.jsonl` into one `hook-merged-<UTC date>.jsonl` and deletes the source.
A count that read the directory while that happened could see a line twice (source and day) or not at all. Both sides take
one OS lock; a count that cannot get it in COLLECT_MERGE_WAIT_S counts without it, still deduplicating by
`line_key`, and says `merge_lock: "busy"` (an unknown is named, FR-41); a lock that cannot be made says
`"unavailable"` (F-7). Keys: K2b-symlink and K2b-dir (F-2), K2b-badonce (F-4), K2b-unavailable (F-7), K2b-lines (F-3), K2b-lock, K2b-wait, K2b-dedup, K2b-vanish,
K2b-merging, K2b-dup, K2 (days before and after a merge), K2b-proc (a second PROCESS), K2b-race (a merge running while
the count runs), K8b (empty inputs). Waits are driven by events; the only clock reading is the lower bound of a wait."""
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import check, check_eq, cleanup, finish, temp_dir  # noqa: E402

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
import collect_pack as CP  # noqa: E402
import telemetry_capture as T  # noqa: E402

QUICK = 0.05   # the wait of a count that is expected to find the lock busy


def tel_dir(root: Path) -> Path:
    return root / "state" / "telemetry"


def ev(tag: str, phase: str = "end", day: str = "2026-10-27", reason=None) -> dict:
    return T.envelope(event_id=f"{tag}:{phase}", phase=phase, span_kind="hook", source="test",
                      timestamp=f"{day}T10:00:00+00:00", duration_ms=5 if phase == "end" else None, outcome="ok",
                      reason_code=reason)


def put(directory: Path, name: str, *events, age: int = 3600) -> Path:
    path = directory / name
    for item in events:
        T.append(path, item)
    stamp = time.time() - age
    os.utime(path, (stamp, stamp))
    return path


def count(directory: Path, files=None) -> dict:
    """What the collect pass does: hands the summariser every file of the set (aggregates included)."""
    return CP._sum_telemetry(None, sorted(directory.iterdir()) if files is None else files, {})


def snapshot(directory: Path) -> dict:
    return {p.name: p.read_bytes() for p in sorted(directory.iterdir())}


class Holder:
    """Another thread owns the merge lock until `release()`. The OS lock is per handle, so a thread is a second owner."""

    def __init__(self, directory: Path):
        self.directory, self.got, self._release = directory, threading.Event(), threading.Event()
        self.thread = threading.Thread(target=self._run)

    def _run(self):
        with T.merge_lock(self.directory) as state:
            if state == "held":
                self.got.set()
                self._release.wait(60)

    def __enter__(self):
        self.thread.start()
        check("fixture: another owner holds the merge lock", self.got.wait(10))
        return self

    def release(self):
        self._release.set()

    def __exit__(self, *exc):
        self.release()
        self.thread.join(30)


def k2_days_parity() -> None:
    """m-6: only `days` has to be the same before and after the merge; `files` and `bytes` change by design."""
    root = temp_dir("qa-tc-k2-")
    try:
        d = tel_dir(root)
        for i in range(40):
            day = "2026-10-26" if i % 2 else "2026-10-27"
            put(d, f"hook-{100 + i}.jsonl", ev(f"p{i}", "start", day), ev(f"p{i}", "end", day, reason=f"r{i % 3}"))
        before = count(d)
        report = T.maintain_dir(d)
        after = count(d)
        check_eq("K2: the Stop pass merged all 40 files", report["merge"]["merged"], 40)
        check_eq("K2: `days` before the merge equal `days` after it", after["days"], before["days"])
        check("K2: the merge moved lines but counted none anew", sum(sum(c.values()) for c in after["days"].values()) == 80,
              str(after["days"]))
        check("K2: `files` fell (40 per-process files became daily ones) - by design", after["files"] < before["files"],
              f"{before['files']} -> {after['files']}")
        check_eq("K2: both counts took the lock", (before["merge_lock"], after["merge_lock"]), ("held", "held"))
        check_eq("K2: the summary names the vanished files (none)", (before["vanished_files"], after["vanished_files"]), (0, 0))
    finally:
        cleanup(root)


def k2b_lock() -> None:
    root = temp_dir("qa-tc-lock-")
    try:
        d = tel_dir(root)
        for i in range(3):
            put(d, f"hook-{10 + i}.jsonl", ev(f"l{i}", "start"), ev(f"l{i}"))
        before = snapshot(d)
        started, go, real = threading.Event(), threading.Event(), Path.read_bytes

        def slow(self):
            if self.parent == d and not started.is_set():
                started.set()
                go.wait(30)
            return real(self)

        out = []
        with patch.object(Path, "read_bytes", slow):
            counter = threading.Thread(target=lambda: out.append(count(d)))
            counter.start()
            check("K2b-lock: the count is in the middle of its read", started.wait(10))
            report = T.maintain_dir(d)
            during = snapshot(d)
            go.set()
            counter.join(30)
        check_eq("K2b-lock: the Stop pass finds the lock busy while the count holds it", report, {"ran": False, "busy": True})
        check_eq("K2b-lock: and changes no file", during, before)
        check_eq("K2b-lock: the count says it held the lock", out[0]["merge_lock"], "held")
        check_eq("K2b-lock: and counted every line", sum(sum(c.values()) for c in out[0]["days"].values()), 6)
        control = T.maintain_dir(d)
        check("K2b-lock control: once the count is done the same pass merges", control["ran"] and control["merge"]["merged"] == 3,
              str(control))
    finally:
        cleanup(root)


def k2b_wait() -> None:
    root = temp_dir("qa-tc-wait-")
    try:
        d = tel_dir(root)
        put(d, "hook-1.jsonl", ev("w1", "start"), ev("w1"))
        expected = count(d)["days"]
        with patch.object(CP, "COLLECT_MERGE_WAIT_S", 5.0), Holder(d) as holder:
            threading.Timer(0.1, holder.release).start()
            within = count(d)
        check_eq("K2b-wait (AT, released inside the budget): the count got the lock", within["merge_lock"], "held")
        check_eq("K2b-wait: and counted the same", within["days"], expected)
        with patch.object(CP, "COLLECT_MERGE_WAIT_S", 0.2), Holder(d):
            started = time.monotonic()
            beyond = count(d)
            waited = time.monotonic() - started
        check_eq("K2b-wait (BEYOND, the owner keeps it): the count says busy", beyond["merge_lock"], "busy")
        check("K2b-wait: it waited at least the budget before giving up", waited >= 0.19, f"{waited:.3f} s")
        check_eq("K2b-wait: and counted without the lock, the same days", beyond["days"], expected)
        check_eq("K2b-wait: the default budget is 30 s (F-13)", CP.COLLECT_MERGE_WAIT_S, 30.0)
    finally:
        cleanup(root)


def dedup_fixture(root: Path) -> Path:
    d = tel_dir(root)
    put(d, "hook-1.jsonl", ev("A"), ev("B", reason="x"))
    put(d, "hook-merged-20261027.jsonl", ev("C"))
    return d


def k2b_dedup() -> None:
    base_root, race_root = temp_dir("qa-tc-dd0-"), temp_dir("qa-tc-dd1-")
    try:
        expected = count(dedup_fixture(base_root))["days"]
        check_eq("K2b-dedup: the baseline counts A, B and C once each", sum(sum(c.values()) for c in expected.values()), 3)
        d = dedup_fixture(race_root)
        source, day, real = d / "hook-1.jsonl", d / "hook-merged-20261027.jsonl", Path.read_bytes
        moved = []

        def read_then_merge(self):
            data = real(self)
            if self == source and not moved:   # the merge of hook-1 into the day lands between the two reads
                day.write_bytes(real(day) + data)
                source.unlink()
                moved.append(True)
            return data

        with patch.object(CP, "COLLECT_MERGE_WAIT_S", QUICK), Holder(d), patch.object(Path, "read_bytes", read_then_merge):
            result = count(d)
        check("K2b-dedup: the merge did run between the reads", bool(moved) and not source.exists())
        check_eq("K2b-dedup: the lines are in two files now, and `days` are the days before the merge", result["days"], expected)
        check_eq("K2b-dedup: the lock was busy and the summary says so", result["merge_lock"], "busy")
        check("K2b-dedup: vanished_files is a count, here 0", result["vanished_files"] == 0, str(result["vanished_files"]))
    finally:
        cleanup(base_root)
        cleanup(race_root)


def k2b_vanish() -> None:
    root = temp_dir("qa-tc-vanish-")
    try:
        d = tel_dir(root)
        keep = put(d, "hook-1.jsonl", ev("V1"))
        gone = put(d, "hook-2.jsonl", ev("V2"))
        handed = sorted(d.iterdir())
        gone.unlink()
        relisted = count(d, handed)
        check_eq("K2b-vanish: a file deleted before the call is simply not listed again (no exception)",
                 (relisted["files"], relisted["vanished_files"], sum(sum(c.values()) for c in relisted["days"].values())), (1, 0, 1))
        with patch.object(CP, "COLLECT_MERGE_WAIT_S", QUICK), Holder(d), patch.object(CP, "_telemetry_listing", lambda dirs: [keep, gone]):
            stale = count(d, handed)
        check_eq("K2b-vanish: a listing that still names it - the read fails, is counted, nothing raises",
                 (stale["files"], stale["vanished_files"], stale["merge_lock"]), (1, 1, "busy"))
        check_eq("K2b-vanish: and the other file is counted", sum(sum(c.values()) for c in stale["days"].values()), 1)
    finally:
        cleanup(root)


def k2b_merging() -> None:
    root = temp_dir("qa-tc-merging-")
    try:
        d = tel_dir(root)
        put(d, "hook-5.jsonl.merging", ev("A"), ev("B", reason="x"))
        only = count(d)
        check_eq("K2b-merging: a claimed `.merging` file is counted (its lines are in no other file yet)",
                 sum(sum(c.values()) for c in only["days"].values()), 2)
        put(d, "hook-merged-20261027.jsonl", ev("A"), ev("B", reason="x"), ev("C"))
        both = count(d)
        check_eq("K2b-merging: lines already in the daily file are counted once, not twice",
                 sum(sum(c.values()) for c in both["days"].values()), 3)
        check_eq("K2b-merging: both files are in the summary", both["files"], 2)
    finally:
        cleanup(root)


def k2b_dup() -> None:
    root = temp_dir("qa-tc-dup-")
    try:
        d = tel_dir(root)
        same = ev("S")
        put(d, "hook-1.jsonl", same, same, ev("T"))
        check_eq("K2b-dup: two lines with one event_id in ONE file are counted once (the meaning change, edge 12)",
                 sum(sum(c.values()) for c in count(d)["days"].values()), 2)
        keyless = {"timestamp": "2026-10-27T10:00:00+00:00", "span_kind": "hook", "outcome": "ok"}
        other = dict(keyless, reason_code="different")
        put(d, "hook-2.jsonl", keyless, other)
        check_eq("K2b-dup: two different lines with no event_id are both counted",
                 sum(sum(c.values()) for c in count(d)["days"].values()), 4)
        T.append(d / "hook-3.jsonl", keyless)
        check_eq("K2b-dup: the same keyless line again, in another file, is the same event: counted once",
                 sum(sum(c.values()) for c in count(d)["days"].values()), 4)
        with (d / "hook-4.jsonl").open("a", encoding="utf-8") as stream:
            stream.write("not json\n{\"timestamp\": \"2026-10-27\"}\n[1, 2]\n")
        broken = count(d)
        check_eq("K2b-dup: lines that do not parse, and rows with no timestamp, are unreadable_lines as before",
                 broken["unreadable_lines"], 2)
    finally:
        cleanup(root)


def k2b_proc() -> None:
    """A key with two PROCESSES: another process holds the merge lock (the Stop hook of another session)."""
    root = temp_dir("qa-tc-proc-")
    holder = None
    try:
        d = tel_dir(root)
        for i in range(3):
            put(d, f"hook-{20 + i}.jsonl", ev(f"q{i}", "start"), ev(f"q{i}"))
        expected = count(d)["days"]
        code = ("import sys, time\nsys.path.insert(0, sys.argv[1])\nfrom pathlib import Path\n"
                "from event_store import EventStore\nwith EventStore(Path(sys.argv[2])).lock():\n"
                "    print('locked', flush=True)\n    time.sleep(120)\n")
        holder = subprocess.Popen([sys.executable, "-B", "-c", code, str(SCRIPTS), str(root / "state" / ".telemetry-merge")],
                                  stdout=subprocess.PIPE, text=True)
        watchdog = threading.Timer(60, holder.kill)
        watchdog.start()
        check_eq("K2b-proc: the other process holds the lock", holder.stdout.readline().strip(), "locked")
        with patch.object(CP, "COLLECT_MERGE_WAIT_S", 0.2):
            busy = count(d)
        check_eq("K2b-proc: held by another process -> busy, no exception, the same days", (busy["merge_lock"], busy["days"]),
                 ("busy", expected))
        holder.kill()
        holder.wait()
        watchdog.cancel()
        free = count(d)
        check_eq("K2b-proc: the holder died - the next count takes the lock", (free["merge_lock"], free["days"]), ("held", expected))
    finally:
        if holder is not None and holder.poll() is None:
            holder.kill()
            holder.wait()
        cleanup(root)


def k2b_race() -> None:
    """The Stop pass merges 60 files in a thread while the main thread counts again and again: whichever side runs first,
    each count shows the same days and took the lock."""
    root = temp_dir("qa-tc-race-")
    try:
        d = tel_dir(root)
        for i in range(60):
            put(d, f"hook-{300 + i}.jsonl", ev(f"r{i}", "start"), ev(f"r{i}"))
        expected = count(d)["days"]
        reports = []
        merger = threading.Thread(target=lambda: reports.append(T.maintain_dir(d)))
        merger.start()
        seen = [count(d) for _ in range(6)]
        merger.join(60)
        check_eq("K2b-race: every count, during the merge or around it, shows the same days", [r["days"] == expected for r in seen], [True] * 6)
        check_eq("K2b-race: and each took the lock", {r["merge_lock"] for r in seen}, {"held"})
        merged_or_busy = reports and (reports[0].get("ran") is False and reports[0].get("busy") or reports[0]["merge"]["merged"] == 60)
        check("K2b-race: the pass either merged the 60 files or found the lock busy (and the next one does)", bool(merged_or_busy), str(reports))
        again = T.maintain_dir(d)
        check_eq("K2b-race: after it every line sits once in the day files", count(d)["days"], expected)
        check("K2b-race: no per-process file is left", not any(p.name.startswith("hook-3") for p in d.iterdir()) or again.get("busy"),
              str(sorted(p.name for p in d.iterdir())[:5]))
    finally:
        cleanup(root)


def k8b_empty_inputs() -> None:
    root = temp_dir("qa-tc-empty-")
    try:
        check_eq("K8b: no files -> zeros and `merge_lock: none` (nothing was locked)", CP._sum_telemetry(None, [], {}),
                 {"files": 0, "bytes": 0, "unreadable_lines": 0, "vanished_files": 0, "merge_lock": "none", "days": {}})
        d = tel_dir(root)
        d.mkdir(parents=True)
        (d / "hook-1.aggregate.json").write_text("{}", encoding="utf-8")
        only_aggregate = count(d)
        check_eq("K8b: a set holding only an aggregate counts no file and no line", (only_aggregate["files"], only_aggregate["days"]), (0, {}))
        (d / "hook-9.jsonl").write_text("", encoding="utf-8")
        empty = count(d)
        check_eq("K8b: an empty span file is a file with no lines", (empty["files"], empty["bytes"], empty["days"]), (1, 0, {}))
        row = b'{"timestamp": "2026-10-27T10:00:00", "span_kind": "hook"}'
        (d / "hook-8.jsonl").write_bytes(row + b"\r\n" + row + b"\n" + b"\xff\xfe\n")
        crlf = count(d)
        check_eq("K8b: a CRLF line equals the same line with LF (one key), and bytes that do not decode are an unreadable line",
                 (crlf["unreadable_lines"], sum(sum(c.values()) for c in crlf["days"].values())), (1, 1))
        deep = "[" * 20000 + "]" * 20000
        (d / "hook-7.jsonl").write_text(deep + "\n", encoding="utf-8")
        check_eq("K8b: a line nested too deep for the parser is an unreadable line, not a crash",
                 count(d)["unreadable_lines"], 2)
    finally:
        cleanup(root)


def total_lines(summary: dict) -> int:
    return sum(sum(c.values()) for c in summary["days"].values())


def k2b_plain_files() -> None:
    """F-2: the re-listing reads regular files only - the pack's classifier never follows a symlink, and a directory named
    `*.jsonl` is not a file (so it is not a vanished one either)."""
    root, outside = temp_dir("qa-tc-plain-"), temp_dir("qa-tc-plain-out-")
    try:
        d = tel_dir(root)
        put(d, "hook-1.jsonl", ev("P1"))
        (d / "dir.jsonl").mkdir()
        (d / "dir.jsonl.merging").mkdir()
        target = put(Path(outside), "elsewhere.jsonl", ev("OUT"))
        try:
            os.symlink(target, d / "link.jsonl")
            linked = "a real symlink"
        except (OSError, NotImplementedError):  # no symlink right on this machine: the predicate is driven by a stub entry
            linked = "a stub entry"

            class Entry:
                name, path = "link.jsonl", str(target)
                asked = []

                def is_file(self, follow_symlinks=True):
                    Entry.asked.append(follow_symlinks)
                    return follow_symlinks
            check_eq("K2b-symlink (stub): the predicate asks with follow_symlinks=False and a link is refused",
                     (CP._is_plain_file(Entry()), Entry.asked), (False, [False]))
        result = count(d)
        check_eq(f"K2b-symlink ({linked}): the linked file's line is not counted, only the plain file's", total_lines(result), 1)
        check_eq("K2b-symlink: and the link is not read (files = 1)", result["files"], 1)
        check_eq("K2b-dir: a directory named *.jsonl / *.jsonl.merging is neither counted nor vanished",
                 (result["files"], result["vanished_files"]), (1, 0))
        check_eq("K2b-dir (control): the plain file alone gives the same count", total_lines(count(d, [d / "hook-1.jsonl"])), 1)
    finally:
        cleanup(root)
        cleanup(outside)


def k2b_bad_once() -> None:
    """F-4: an unreadable line that sits in two files (a `.merging` whose unlink keeps failing, after its content was
    appended to the day) is ONE unreadable line - the same 'never twice' the readable lines have."""
    root = temp_dir("qa-tc-badonce-")
    try:
        d = tel_dir(root)
        d.mkdir(parents=True)
        torn, good = '{"timestamp": "2026-10-27T10:00:00+00:00", "span_kin', ev("G")
        (d / "hook-5.jsonl.merging").write_text(torn + "\n" + json.dumps(good) + "\n", encoding="utf-8")
        alone = count(d)
        check_eq("K2b-badonce: one torn line and one good line in one file", (alone["unreadable_lines"], total_lines(alone)), (1, 1))
        (d / "hook-merged-20261027.jsonl").write_text(torn + "\n" + json.dumps(good) + "\n", encoding="utf-8")
        both = count(d)
        check_eq("K2b-badonce: the same two lines in a second file - still one unreadable line, one good one",
                 (both["unreadable_lines"], total_lines(both), both["files"]), (1, 1, 2))
        (d / "hook-merged-20261027.jsonl").write_text(torn + "\nanother torn line\n", encoding="utf-8")
        other = count(d)
        check_eq("K2b-badonce (control): a DIFFERENT torn line is counted on its own", other["unreadable_lines"], 2)
    finally:
        cleanup(root)


def k2b_lines() -> None:
    """F-3 (AR-13): the count reads lines through the merge's splitter and key: a CRLF line and its LF twin in two files are
    one line, whichever file normalised it."""
    root = temp_dir("qa-tc-lines-")
    try:
        d = tel_dir(root)
        d.mkdir(parents=True)
        row = json.dumps(ev("L"), sort_keys=True)
        (d / "hook-1.jsonl").write_bytes(row.encode() + b"\r\n")
        (d / "hook-merged-20261027.jsonl").write_bytes(row.encode() + b"\n")
        check_eq("K2b-lines: a CRLF line and the same line with LF, in two files, are counted once", total_lines(count(d)), 1)
        keyless = '{"timestamp": "2026-10-27T10:00:00+00:00", "span_kind": "hook", "outcome": "ok"}'
        (d / "hook-2.jsonl").write_bytes(keyless.encode() + b"\r\n")
        (d / "hook-merged-20261027.jsonl").write_bytes(row.encode() + b"\n" + keyless.encode() + b"\n")
        check_eq("K2b-lines: and so is a keyless one (the sha1 key is taken of the normalised line)", total_lines(count(d)), 2)
    finally:
        cleanup(root)


def k2b_unavailable() -> None:
    """F-7: a lock that cannot be made is `unavailable`, never `busy`, and the count still goes on, without waiting."""
    root = temp_dir("qa-tc-unavail-")
    try:
        d = tel_dir(root)
        put(d, "hook-1.jsonl", ev("U1"))
        expected = count(d)["days"]
        shutil.rmtree(root / "state" / ".telemetry-merge")   # the first count made it; a FILE takes its place
        (root / "state" / ".telemetry-merge").write_text("a file where the lock folder should be", encoding="utf-8")
        started = time.monotonic()
        with patch.object(CP, "COLLECT_MERGE_WAIT_S", 30.0):
            result = count(d)
        waited = time.monotonic() - started
        check_eq("K2b-unavailable: a lock folder that is a file -> `unavailable`, and the same days", (result["merge_lock"], result["days"]),
                 ("unavailable", expected))
        check("K2b-unavailable: it did not wait out its budget (nobody holds anything)", waited < 5.0, f"{waited:.2f} s")
        check_eq("K2b-unavailable: the word of several directories - busy only when nothing is unavailable",
                 (CP._lock_word(["held", "held"]), CP._lock_word(["held", "busy"]), CP._lock_word(["busy", "unavailable"])),
                 ("held", "busy", "unavailable"))
    finally:
        cleanup(root)


def k2b_other_summaries() -> None:
    """The queued sibling of K2b-vanish: the other summarisers of the pack stat each file; one that vanished is counted by
    name, never an exception, and a run without a vanish has no such key."""
    root = temp_dir("qa-tc-others-")
    try:
        here, gone = root / "a.json", root / "b.json"
        here.write_text('{"status": "ok", "host": "h1"}', encoding="utf-8")
        for label, function in (("dir_stats", CP._sum_dir_stats), ("host_receipts", CP._sum_host_receipts),
                                ("artifacts_summary", CP._sum_artifacts)):
            plain = function(None, [here], {})
            lost = function(None, [here, gone], {})
            check_eq(f"K2b-vanish ({label}): a file that vanished is counted, the other still is",
                     (plain["files"], "vanished_files" in plain, lost["files"], lost["vanished_files"]), (1, False, 1, 1))
            check_eq(f"K2b-vanish ({label}): a set that all vanished is zero files, no exception", function(None, [gone], {})["files"], 0)
        check_eq("K2b-vanish (dir_stats): the vanished file adds no bytes", CP._sum_dir_stats(None, [here, gone], {})["bytes"],
                 here.stat().st_size)
    finally:
        cleanup(root)


def main() -> None:
    for step in (k2_days_parity, k2b_lock, k2b_wait, k2b_dedup, k2b_vanish, k2b_merging, k2b_dup, k2b_proc, k2b_race,
                 k2b_plain_files, k2b_bad_once, k2b_lines, k2b_unavailable, k2b_other_summaries,
                 k8b_empty_inputs):
        step()
    finish("test_telemetry_count")


if __name__ == "__main__":
    main()
