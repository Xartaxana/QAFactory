"""SC1-4a: the Stop-time telemetry pass. `maintain` skips a raw file whose stamp (size + mtime_ns, taken BEFORE the
read) still matches its aggregate; `maintain_dir` merges closed `hook-<pid>.jsonl` files into one file per UTC day under
the one merge lock the collect pack shares, and never rotates by size.

TP1-12586 (0.10.2): 1750 per-process files, every capture re-read and re-wrote all 1338+ aggregates, ~5 s a wave
every 40 s. Keys K1..K8 are the ones the spec names; each mutation in its DoD is killed by one of them (named below).
The timing in K4 is printed, never judged (FR-31): the key is that pass 2 reads no raw file."""
import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import check, check_eq, cleanup, finish, temp_dir  # noqa: E402

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
import telemetry_capture as T  # noqa: E402

NOW = datetime(2026, 10, 27, 12, 0, 0, tzinfo=timezone.utc)
NOW_S = int(NOW.timestamp())


class patched:
    """Swap an attribute for the length of a with-block (a plain monkeypatch, restored on any exit)."""
    def __init__(self, obj, name, value):
        self.obj, self.name, self.value = obj, name, value

    def __enter__(self):
        self.old = getattr(self.obj, self.name)
        setattr(self.obj, self.name, self.value)
        return self.old

    def __exit__(self, *exc):
        setattr(self.obj, self.name, self.old)


class counting_loads:
    """Counts the calls of telemetry_capture.load_events - the one reader of a raw file inside `maintain`."""
    def __enter__(self):
        self.calls = 0
        self.old = T.load_events

        def wrapper(path):
            self.calls += 1
            return self.old(path)
        T.load_events = wrapper
        return self

    def __exit__(self, *exc):
        T.load_events = self.old


def set_age(path: Path, seconds: int) -> Path:
    """mtime = NOW - seconds, in whole seconds and integer nanoseconds (so an AT/BEYOND boundary is exact)."""
    stamp = (NOW_S - int(seconds)) * 1_000_000_000
    os.utime(path, ns=(stamp, stamp))
    return path


def event(tag: str, phase: str, **extra) -> dict:
    return T.envelope(event_id=f"{tag}:{phase}", phase=phase, span_kind="hook", source="test",
                      timestamp="2026-10-27T10:00:00+00:00", duration_ms=5 if phase == "end" else None, **extra)


def put(directory: Path, name: str, tag: str, age: int, closed: bool = True) -> Path:
    path = directory / name
    path.parent.mkdir(parents=True, exist_ok=True)
    T.append(path, event(tag, "start"))
    if closed:
        T.append(path, event(tag, "end"))
    return set_age(path, age)


def tel_dir(root: Path) -> Path:
    """<root>/state/telemetry - the lock root is its sibling <root>/state/.telemetry-merge."""
    return root / "state" / "telemetry"


def lines_of(path: Path) -> list:
    return [x for x in path.read_text(encoding="utf-8").split("\n") if x]


def hook_lines(directory: Path) -> list:
    """Every line still held by a hook file of any kind: raw, claimed (.merging) or daily."""
    out = []
    for p in sorted(directory.iterdir()):
        if p.name.startswith("hook-") and (p.name.endswith(".jsonl") or p.name.endswith(".jsonl.merging")):
            out += lines_of(p)
    return out


def names(directory: Path) -> list:
    return sorted(p.name for p in directory.iterdir())


def once_each(label: str, directory: Path, expected_ids: set) -> None:
    lines = hook_lines(directory)
    keys = [T.line_key(x) for x in lines]
    check(f"{label}: every line sits in exactly one place, once", len(keys) == len(set(keys)),
          f"{len(keys)} lines, {len(set(keys))} distinct")
    check_eq(f"{label}: and none is lost", set(keys), expected_ids)


def ids_for(*tags) -> set:
    return {f"{t}:{ph}" for t in tags for ph in ("start", "end")}


def k1_stamp() -> None:
    d = temp_dir("qa-tm-k1-")
    try:
        raw, agg = d / "a.jsonl", d / "a.aggregate.json"
        T.append(raw, event("s1", "start")); T.append(raw, event("s1", "end"))
        first = T.maintain(raw, agg, sweep=False)
        stored = json.loads(agg.read_text(encoding="utf-8"))
        st = raw.stat()
        check_eq("K1: the aggregate carries the stamp taken before the read",
                 stored["source_stamp"], {"size": st.st_size, "mtime_ns": st.st_mtime_ns})
        check_eq("K1: the stamp is not part of the summary maintain returns", "source_stamp" in first["aggregate"], False)
        mtime = agg.stat().st_mtime_ns
        with counting_loads() as c:
            second = T.maintain(raw, agg, sweep=False)
        check_eq("K1: pass 2 on an unchanged file reads nothing", c.calls, 0)
        check_eq("K1: and does not rewrite the aggregate", agg.stat().st_mtime_ns, mtime)
        check_eq("K1: it still reports the same summary", second["aggregate"], first["aggregate"])
        T.append(raw, event("s2", "start"))
        with counting_loads() as c:
            third = T.maintain(raw, agg, sweep=False)
        check_eq("K1: a line appended makes the next pass read again", c.calls, 1)
        check_eq("K1: and the aggregate counts it", third["aggregate"]["event_count"], 3)
        legacy = d / "legacy.aggregate.json"
        legacy.write_text(json.dumps(first["aggregate"]), encoding="utf-8")
        with counting_loads() as c:
            T.maintain(raw, legacy, sweep=False)
        check_eq("K1: an aggregate with no stamp (written before it existed) counts as changed", c.calls, 1)
        check("K1: and is rewritten with one", "source_stamp" in json.loads(legacy.read_text(encoding="utf-8")))
    finally:
        cleanup(d)


def k1r_race() -> None:
    d = temp_dir("qa-tm-k1r-")
    try:
        # (a) a line lands AFTER the read: the stamp was taken before it, so the next pass must read again.
        raw, agg = d / "a.jsonl", d / "a.aggregate.json"
        T.append(raw, event("s1", "start")); T.append(raw, event("s1", "end"))
        real = T.load_events

        def late_append(path):
            rows = real(path)
            T.append(Path(path), event("late", "start"))
            return rows
        with patched(T, "load_events", late_append):
            T.maintain(raw, agg, sweep=False)
        with counting_loads() as c:
            after = T.maintain(raw, agg, sweep=False)
        check_eq("K1r: a line appended after the read is read by the next pass", c.calls, 1)
        check_eq("K1r: and counted", after["aggregate"]["event_count"], 3)
        # (b) the literal race: stat reports the size BEFORE the append, the file already holds the line.
        raw2, agg2 = d / "b.jsonl", d / "b.aggregate.json"
        T.append(raw2, event("s1", "start")); T.append(raw2, event("s1", "end"))
        before = raw2.stat()
        T.append(raw2, event("late", "start"))
        real_stat = Path.stat

        def stale_stat(self, *a, **k):
            st = real_stat(self, *a, **k)
            if str(self) == str(raw2):
                return SimpleNamespace(st_size=before.st_size, st_mtime_ns=before.st_mtime_ns, st_mtime=st.st_mtime)
            return st
        with patched(Path, "stat", stale_stat):
            T.maintain(raw2, agg2, sweep=False)
        with counting_loads() as c:
            again = T.maintain(raw2, agg2, sweep=False)
        check_eq("K1r: stat that lied by one append - the next pass recomputes", (c.calls, again["aggregate"]["event_count"]), (1, 3))
    finally:
        cleanup(d)


def k1r_b_mtime_held() -> None:
    d = temp_dir("qa-tm-k1rb-")
    try:
        raw, agg = d / "a.jsonl", d / "a.aggregate.json"
        T.append(raw, event("s1", "start")); T.append(raw, event("s1", "end"))
        T.maintain(raw, agg, sweep=False)
        held = json.loads(agg.read_text(encoding="utf-8"))["source_stamp"]["mtime_ns"]
        T.append(raw, event("s2", "start"))
        real_stat = Path.stat

        def same_mtime(self, *a, **k):
            st = real_stat(self, *a, **k)
            if str(self) == str(raw):
                return SimpleNamespace(st_size=st.st_size, st_mtime_ns=held, st_mtime=st.st_mtime)
            return st
        with patched(Path, "stat", same_mtime), counting_loads() as c:
            after = T.maintain(raw, agg, sweep=False)
        check_eq("K1r-b: an append with the mtime_ns unchanged is caught by the size", c.calls, 1)
        check_eq("K1r-b: and counted", after["aggregate"]["event_count"], 3)
    finally:
        cleanup(d)


def k2_merge() -> None:
    root = temp_dir("qa-tm-k2-")
    try:
        d = tel_dir(root)
        tags = []
        for i in range(30):  # today
            put(d, f"hook-{1000 + i}.jsonl", f"t{i}", age=120 + i)
            tags.append(f"t{i}")
        for i in range(10):  # yesterday: 30 h old, closed, so merged into YESTERDAY's file
            put(d, f"hook-{2000 + i}.jsonl", f"y{i}", age=30 * 3600 + i)
            tags.append(f"y{i}")
        for n in (1000, 1001, 2000):  # per-process aggregates written earlier by the old loop
            T.maintain(d / f"hook-{n}.jsonl", d / f"hook-{n}.aggregate.json", sweep=False)
        put(d, "command-1.jsonl", "cmd", age=120)
        report = T.maintain_dir(d, now=NOW)
        check_eq("K2: the pass ran and merged all 40 sources", (report["ran"], report["merge"]["merged"]), (True, 40))
        check_eq("K2: two UTC days, two daily files", report["merge"]["days"], ["20261026", "20261027"])
        day_files = sorted(p.name for p in d.glob("hook-merged-*.jsonl"))
        check_eq("K2: the daily files", day_files, ["hook-merged-20261026.jsonl", "hook-merged-20261027.jsonl"])
        check_eq("K2: today's file holds the sum of today's sources", len(lines_of(d / "hook-merged-20261027.jsonl")), 60)
        check_eq("K2: yesterday's file holds yesterday's", len(lines_of(d / "hook-merged-20261026.jsonl")), 20)
        check_eq("K2: the key set is the union of the sources", {T.line_key(x) for x in hook_lines(d)}, ids_for(*tags))
        left = [n for n in names(d) if n.startswith("hook-") and "merged" not in n]
        check_eq("K2: sources, claims and their aggregates are gone", left, [])
        check("K2: the daily files got aggregates of their own", (d / "hook-merged-20261027.aggregate.json").exists())
        check("K2: command-* files are not merged", (d / "command-1.jsonl").exists())
        check_eq("K2: the pass wrote no .closed", [n for n in names(d) if n.endswith(".closed")], [])
        again = T.maintain_dir(d, now=NOW)
        check_eq("K2: a second pass merges nothing", again["merge"]["merged"], 0)
    finally:
        cleanup(root)


def k2c_crash() -> None:
    for label, make_crash in (("after the claim, before the append", "append"), ("after the fsync, before the removal", "unlink")):
        root = temp_dir("qa-tm-k2c-")
        try:
            d = tel_dir(root)
            tags = [f"c{i}" for i in range(6)]
            for i, tag in enumerate(tags):
                put(d, f"hook-{300 + i}.jsonl", tag, age=200 + i)
            if make_crash == "append":
                def boom(*a, **k):
                    raise RuntimeError("killed after the claim")
                with patched(T, "_append_new", boom):
                    first = T.maintain_dir(d, now=NOW)
                check("K2c(a): the crash does not escape maintain_dir", first["ran"] and first["errors"] >= 1)
                check_eq("K2c(a): the claims wait as .merging", sum(1 for n in names(d) if n.endswith(".merging")), 6)
                check_eq("K2c(a): nothing was appended", list(d.glob("hook-merged-*.jsonl")), [])
            else:
                real_unlink = os.unlink

                def refuse(path, *a, **k):  # an antivirus holding the claimed file (edge 15)
                    if str(path).endswith(".merging"):
                        raise PermissionError("held")
                    return real_unlink(path, *a, **k)
                with patched(os, "unlink", refuse):
                    T.maintain_dir(d, now=NOW)
                check("K2c(b): the appended lines are on disk", len(lines_of(next(d.glob("hook-merged-*.jsonl")))) == 12)
                check_eq("K2c(b): the claims stay (the removal was refused)", sum(1 for n in names(d) if n.endswith(".merging")), 6)
            T.maintain_dir(d, now=NOW)
            once_each(f"K2c ({label})", d, ids_for(*tags))
            check_eq(f"K2c ({label}): the next pass left no .merging", [n for n in names(d) if n.endswith(".merging")], [])
        finally:
            cleanup(root)
    root = temp_dir("qa-tm-k2c-")
    try:  # a pass killed mid-write left the daily file without its final newline
        d = tel_dir(root)
        put(d, "hook-1.jsonl", "n1", age=300)
        day = d / "hook-merged-20261027.jsonl"
        day.write_text(json.dumps(event("old", "start")) + "\n" + '{"event_id":"torn', encoding="utf-8")
        T.maintain_dir(d, now=NOW)
        parsed = [x for x in lines_of(day) if '"event_id":"n1:' in x]
        check_eq("K2c: a torn last line does not swallow the next appended one", len(parsed), 2)
        check("K2c: every appended line still parses", all(json.loads(x) for x in parsed))
    finally:
        cleanup(root)


def k2p_pid_reuse() -> None:
    root = temp_dir("qa-tm-k2p-")
    try:
        d = tel_dir(root)
        put(d, "hook-77.jsonl", "old", age=400)
        real_append = T._append_new
        state = {"done": False}

        def reuse_pid(day_file, lines, keys):
            if not state["done"]:  # the pid comes back after the claim: a NEW hook-77.jsonl starts
                state["done"] = True
                put(d, "hook-77.jsonl", "new", age=400)
            return real_append(day_file, lines, keys)
        with patched(T, "_append_new", reuse_pid):
            T.maintain_dir(d, now=NOW)
        check("K2p: the new file written after the claim is still there, unread", (d / "hook-77.jsonl").exists())
        check_eq("K2p: and holds its lines", len(lines_of(d / "hook-77.jsonl")), 2)
        T.maintain_dir(d, now=NOW)
        once_each("K2p: after the next pass", d, ids_for("old", "new"))
        check("K2p: the new file was merged by that pass", not (d / "hook-77.jsonl").exists())
        # a fresh file never replaces a claim that is still there
        put(d, "hook-88.jsonl.merging", "claimA", age=500)
        put(d, "hook-88.jsonl", "claimB", age=500)
        T.maintain_dir(d, now=NOW)
        check_eq("K2p: a claim and a fresh file of one pid both survive to a merge", len(hook_lines(d)), 4 + 4)
        T.maintain_dir(d, now=NOW)
        once_each("K2p: a claim and a fresh file of one pid", d, ids_for("old", "new", "claimA", "claimB"))
    finally:
        cleanup(root)


def k2i_unclosed() -> None:
    root = temp_dir("qa-tm-k2i-")
    try:
        d = tel_dir(root)
        put(d, "hook-1.jsonl", "young", age=2 * 3600, closed=False)
        put(d, "hook-2.jsonl", "stale", age=25 * 3600, closed=False)
        T.maintain_dir(d, now=NOW)
        check("K2i: an unclosed span younger than a day is not merged", (d / "hook-1.jsonl").exists())
        check("K2i: one older than a day is merged as it is", not (d / "hook-2.jsonl").exists())
        day = d / "hook-merged-20261026.jsonl"
        check("K2i: into its own day's file", day.exists())
        check("K2i: the day's aggregate shows the unclosed span",
              json.loads((d / "hook-merged-20261026.aggregate.json").read_text(encoding="utf-8"))["incomplete_spans"] >= 1)
    finally:
        cleanup(root)


def exact_size_file(path: Path, size: int) -> Path:
    """A closed-span file of exactly `size` bytes (padding rides in an extra field of the start line)."""
    start, end = event("pad", "start"), event("pad", "end")
    base = len(json.dumps(start, sort_keys=True, separators=(",", ":"))) + len(json.dumps(end, sort_keys=True, separators=(",", ":"))) + 2
    start["pad"] = "x" * (size - base - len(',"pad":""'))
    text = json.dumps(start, sort_keys=True, separators=(",", ":")) + "\n" + json.dumps(end, sort_keys=True, separators=(",", ":")) + "\n"
    path.write_text(text, encoding="utf-8", newline="\n")
    assert path.stat().st_size == size, (path.stat().st_size, size)
    return path


def k2r_rotation() -> None:
    d = temp_dir("qa-tm-k2r-")
    try:
        at = exact_size_file(d / "at.jsonl", 1000)
        beyond = exact_size_file(d / "beyond.jsonl", 1001)
        r_at = T.maintain(at, d / "at.aggregate.json", max_bytes=1000, sweep=False)
        r_beyond = T.maintain(beyond, d / "beyond.aggregate.json", max_bytes=1000, sweep=False)
        check_eq("K2r: a direct call at max_bytes does not rotate", (r_at["rotated"], at.exists()), (None, True))
        check("K2r: a direct call beyond max_bytes still rotates (the old behaviour)", r_beyond["rotated"] and not beyond.exists())
        none_rotates = exact_size_file(d / "none.jsonl", 1001)
        check_eq("K2r: max_bytes=None never rotates", T.maintain(none_rotates, d / "none.aggregate.json", max_bytes=None, sweep=False)["rotated"], None)
    finally:
        cleanup(d)
    root = temp_dir("qa-tm-k2r-")
    try:
        d = tel_dir(root)
        d.mkdir(parents=True)
        exact_size_file(d / "hook-merged-20261027.jsonl", 1001)
        exact_size_file(d / "hook-5.jsonl", 1001)
        set_age(d / "hook-5.jsonl", 5)  # young: stays a per-process file
        defaults = dict(T.maintain.__kwdefaults__)
        with patched(T.maintain, "__kwdefaults__", dict(defaults, max_bytes=1000)):
            T.maintain_dir(d, now=NOW)
        check_eq("K2r: the directory pass makes no .closed, on a daily and on a per-process file",
                 [n for n in names(d) if n.endswith(".closed")], [])
        check("K2r: both files are still where the count reads them",
              (d / "hook-merged-20261027.jsonl").exists() and (d / "hook-5.jsonl").exists())
    finally:
        cleanup(root)


def k3_limit() -> None:
    for extra, label in ((0, "AT max_files"), (1, "BEYOND max_files")):
        root = temp_dir("qa-tm-k3-")
        try:
            d = tel_dir(root)
            count = 5 + extra
            for i in range(count):  # i = 0 is the OLDEST
                put(d, f"hook-{10 + i}.jsonl", f"f{i}", age=1000 - i * 10)
            report = T.maintain_dir(d, now=NOW, max_files=5)
            check_eq(f"K3 ({label}): merged", report["merge"]["merged"], 5)
            left = sorted(n for n in names(d) if n.startswith("hook-1") and n.endswith(".jsonl") and "merged" not in n)
            check_eq(f"K3 ({label}): what waits is the newest", left, [f"hook-{10 + 5}.jsonl"] if extra else [])
            T.maintain_dir(d, now=NOW, max_files=5)
            once_each(f"K3 ({label}): after the next pass", d, ids_for(*[f"f{i}" for i in range(count)]))
        finally:
            cleanup(root)


def k3q_quiet_window() -> None:
    root = temp_dir("qa-tm-k3q-")
    try:
        d = tel_dir(root)
        put(d, "hook-30.jsonl", "at", age=30)
        put(d, "hook-31.jsonl", "beyond", age=31)
        T.maintain_dir(d, now=NOW)
        check_eq("K3q: a file quiet for exactly 30 s is not merged, 31 s is", [(d / "hook-30.jsonl").exists(), (d / "hook-31.jsonl").exists()], [True, False])
    finally:
        cleanup(root)


def k3l_lock() -> None:
    root = temp_dir("qa-tm-k3l-")
    holder = None
    try:
        d = tel_dir(root)
        for i in range(3):
            put(d, f"hook-{50 + i}.jsonl", f"l{i}", age=300)
        before = {n: (d / n).read_bytes() for n in names(d)}
        code = ("import sys, time\nsys.path.insert(0, sys.argv[1])\nfrom pathlib import Path\n"
                "from event_store import EventStore\nwith EventStore(Path(sys.argv[2])).lock():\n"
                "    print('locked', flush=True)\n    time.sleep(120)\n")
        holder = subprocess.Popen([sys.executable, "-B", "-c", code, str(SCRIPTS), str(root / "state" / ".telemetry-merge")],
                                  stdout=subprocess.PIPE, text=True)
        watchdog = threading.Timer(60, holder.kill)
        watchdog.start()
        check_eq("K3l: the holder process has the lock", holder.stdout.readline().strip(), "locked")
        report = T.maintain_dir(d, now=NOW)
        check_eq("K3l: another process holds the lock - busy, no exception", report, {"ran": False, "busy": True})
        check_eq("K3l: and no file was touched", {n: (d / n).read_bytes() for n in names(d)}, before)
        holder.kill(); holder.wait(); watchdog.cancel()
        after = T.maintain_dir(d, now=NOW)
        check("K3l: the holder died - the next pass goes", after["ran"] and after["merge"]["merged"] == 3)
        with T.merge_lock(d) as first:
            with T.merge_lock(d) as second:
                check_eq("K3l: merge_lock reports held / busy", (first, second), ("held", "busy"))
        with T.merge_lock(d) as again:
            check_eq("K3l: and is free again after the with-block", again, "held")
        # F-7: a lock that cannot be made is "unavailable", never "busy": nobody holds it, and nobody is named as holding it
        broken = tel_dir(temp_dir("qa-tm-k3u-"))
        broken.mkdir(parents=True)
        (broken.parent / ".telemetry-merge").write_text("a file where the lock folder should be", encoding="utf-8")
        with T.merge_lock(broken) as state:
            check_eq("F-7: a lock folder that is a file -> unavailable", state, "unavailable")
        put(broken, "hook-60.jsonl", "u0", age=300)
        check_eq("F-7: the pass over it reports unavailable (not busy), and touches nothing",
                 (T.maintain_dir(broken, now=NOW), names(broken)), ({"ran": False, "unavailable": True}, ["hook-60.jsonl"]))
        cleanup(broken.parent.parent)
    finally:
        if holder is not None and holder.poll() is None:
            holder.kill(); holder.wait()
        cleanup(root)


def k4_bench() -> None:
    root = temp_dir("qa-tm-k4-")
    try:
        d = tel_dir(root)
        d.mkdir(parents=True)
        for n in range(1750):
            path = d / f"hook-{n}.jsonl"
            path.write_text(json.dumps(event(f"b{n}", "start"), sort_keys=True) + "\n" + json.dumps(event(f"b{n}", "end"), sort_keys=True) + "\n", encoding="utf-8")
            set_age(path, 3600 + n)
        started = time.perf_counter()
        first = T.maintain_dir(d, now=NOW)
        pass1 = time.perf_counter() - started
        with counting_loads() as c:
            started = time.perf_counter()
            second = T.maintain_dir(d, now=NOW)
            pass2 = time.perf_counter() - started
        print(f"K4 bench (printed, not judged): 1750 per-process files - pass 1 {pass1:.2f} s, pass 2 {pass2:.2f} s, "
              f"raw reads in pass 2: {c.calls}, files left: {len(names(d))}")
        check_eq("K4: pass 1 merged all 1750 files into the day", (first["merge"]["merged"], first["merge"]["days"]), (1750, ["20261027"]))
        check_eq("K4: pass 2 reads no raw file", c.calls, 0)
        check_eq("K4: pass 2 merged nothing and maintained the one daily file", (second["merge"]["merged"], second["maintained"]), (0, 1))
        check_eq("K4: the directory shrank to the daily file and its aggregate", names(d), ["hook-merged-20261027.aggregate.json", "hook-merged-20261027.jsonl"])
    finally:
        cleanup(root)


def k6m_silence() -> None:
    root = temp_dir("qa-tm-k6m-")
    try:
        d = tel_dir(root)
        for name, tag in (("a.jsonl", "a"), ("bad.jsonl", "bad"), ("c.jsonl", "c")):
            put(d, name, tag, age=5)
        real = T.maintain

        def flaky(path, *a, **k):
            if Path(path).name == "bad.jsonl":
                raise RuntimeError("one file is broken")
            return real(path, *a, **k)
        with patched(T, "maintain", flaky):
            report = T.maintain_dir(d, now=NOW)
        check("K6m: a failing file does not stop the others",
              (d / "a.aggregate.json").exists() and (d / "c.aggregate.json").exists() and not (d / "bad.aggregate.json").exists())
        check_eq("K6m: maintain_dir returned, counting the failure", (report["ran"], report["maintained"], report["errors"]), (True, 2, 1))

        def merge_breaks(*a, **k):
            raise OSError("disk")
        with patched(T, "merge_closed", merge_breaks):
            report = T.maintain_dir(d, now=NOW)
        check_eq("K6m: a failing merge still lets the files be maintained", (report["ran"], report["errors"] >= 1, report["maintained"]), (True, True, 3))

        def lock_breaks(*a, **k):
            raise ImportError("no event_store")
        with patched(T, "merge_lock", lock_breaks):
            report = T.maintain_dir(d, now=NOW)
        check_eq("K6m: a failure around the whole pass is swallowed too", report, {"ran": False, "error": True})
    finally:
        cleanup(root)


def k7_import() -> None:
    code = "import sys; sys.path.insert(0, sys.argv[1]); import telemetry_capture; print('event_store' in sys.modules, 'contextlib' in sys.modules)"
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    out = subprocess.run([sys.executable, "-B", "-c", code, str(SCRIPTS)], capture_output=True, text=True, env=env, timeout=60)
    check_eq("K7: importing telemetry_capture loads neither event_store nor contextlib (the hot path)", out.stdout.strip(), "False False")


def k8_empty_inputs() -> None:
    root = temp_dir("qa-tm-k8-")
    try:
        d = tel_dir(root)
        check_eq("K8: no directory - nothing to do", T.maintain_dir(d, now=NOW), {"ran": False})
        check("K8: and nothing is created, neither the directory nor the lock", not (root / "state").exists())
        d.mkdir(parents=True)
        empty = d / "hook-1.jsonl"
        empty.write_bytes(b"")
        set_age(empty, 300)
        broken_a, broken_b = d / "hook-2.jsonl", d / "hook-3.jsonl"
        for path in (broken_a, broken_b):
            path.write_text("this is not json\n[1, 2]\n" + '{"event_id": 7}\n', encoding="utf-8")
            set_age(path, 300)
        report = T.maintain_dir(d, now=NOW)
        check_eq("K8: an empty raw file is merged away", (report["merge"]["merged"], empty.exists()), (3, False))
        check("K8: it left no aggregate", not (d / "hook-1.aggregate.json").exists())
        day = lines_of(d / "hook-merged-20261027.jsonl")
        check_eq("K8: unreadable and keyless lines are carried once (sha1 key), not twice", sorted(day), sorted(["this is not json", "[1, 2]", '{"event_id": 7}']))
        check("K8: their key is the hash of the line", T.line_key("this is not json").startswith("sha1:"))
        check_eq("K8: a line with an event_id is keyed by it, whatever else it says", T.line_key('{"event_id":"e:1","x":1}'), T.line_key('{"x":2,"event_id":"e:1"}'))
        check("K8: a line nested too deep for the parser still gets a key", T.line_key("[" * 200000).startswith("sha1:"))
        check("K8: an empty id is no id", T.line_key('{"event_id": ""}').startswith("sha1:"))
        # F-3 (AR-13): one definition of "a line" - the key normalises CR/LF itself, takes a parsed row, and the splitter is shared
        check_eq("F-3: a CRLF line and the same line without it have ONE key (keyless and keyed)",
                 (T.line_key("this is not json\r\n"), T.line_key('{"event_id":"e:2"}\r')), (T.line_key("this is not json"), "e:2"))
        check_eq("F-3: a pre-parsed row gives the key the parse would (keyed, keyless, unparseable)",
                 [T.line_key(x, event=y) for x, y in (('{"event_id":"e:3"}', {"event_id": "e:3"}), ("[1, 2]", [1, 2]), ("nope", None))],
                 [T.line_key('{"event_id":"e:3"}'), T.line_key("[1, 2]"), T.line_key("nope")])
        check_eq("F-3: split_lines splits on \\n only, strips \\r, drops blanks; the merge reader is that same function",
                 (T.split_lines("a\r\n\n  \nb\r\nc\x0bd\n"), T.split_lines("x\n\ny\r\n")), (["a", "b", "c\x0bd"], ["x", "y"]))
        crlf = d / "crlf.jsonl"
        crlf.write_bytes(b'{"event_id":"k:1"}\r\n\r\nplain\r\n')
        check_eq("F-3: the merge's own reader (_read_lines) is split_lines over the file", T._read_lines(crlf), T.split_lines(crlf.read_text(encoding="utf-8")))
    finally:
        cleanup(root)


def main() -> None:
    for step in (k1_stamp, k1r_race, k1r_b_mtime_held, k2_merge, k2c_crash, k2p_pid_reuse, k2i_unclosed, k2r_rotation,
                 k3_limit, k3q_quiet_window, k3l_lock, k4_bench, k6m_silence, k7_import, k8_empty_inputs):
        step()
    finish("test_telemetry_merge")


if __name__ == "__main__":
    main()
