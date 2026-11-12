"""Fail-silent, content-free latency spans for factory-owned operations."""
from __future__ import annotations
import json, os, time, uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

KINDS = {"hook", "command", "tool_roundtrip", "approval", "queue", "agent", "validation", "accept"}

def envelope(*, event_id, phase, span_kind, source, timestamp=None, duration_ms=None,
             session_id=None, task=None, dispatch_id=None, tool_call_id=None,
             parent_span_id=None, outcome=None, retry_of=None, reason_code=None, bytes=None):
    # `bytes` (t-267 K10): how much a REST call carried. Optional, and dropped like every None field,
    # so a span that does not know it (every older caller) writes the line it always wrote.
    if phase not in {"start", "end"} or span_kind not in KINDS:
        raise ValueError("invalid telemetry phase or span_kind")
    return {k:v for k,v in {"event_id":event_id,"timestamp":timestamp or datetime.now(timezone.utc).isoformat(),
        "duration_ms":duration_ms,"session_id":session_id,"task":task,"dispatch_id":dispatch_id,
        "tool_call_id":tool_call_id,"parent_span_id":parent_span_id,"span_kind":span_kind,"phase":phase,
        "outcome":outcome,"retry_of":retry_of,"reason_code":reason_code,"source":source,
        "bytes":bytes}.items() if v is not None}

def append(path: Path, event: dict) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(event, sort_keys=True, separators=(",", ":"))+"\n")
        return True
    except OSError:
        return False

class Span:
    def __init__(self, path, *, span_kind, source, **ids):
        self.path,self.kind,self.source,self.ids=Path(path),span_kind,source,ids
        self.default_reason=self.ids.pop("reason_code",None)
        # Popped like reason_code: the size is known only when the call ends, so it rides on the END
        # event; passed to the constructor or set on `.bytes` before the span closes, never both keywords.
        self.bytes=self.ids.pop("bytes",None)
        self.span_id,self.started=uuid.uuid4().hex,None
    def __enter__(self):
        self.started=time.monotonic_ns()
        append(self.path,envelope(event_id=self.span_id+":start",phase="start",span_kind=self.kind,source=self.source,**self.ids))
        return self
    def finish(self,outcome="ok",reason_code=None):
        duration=None if self.started is None else (time.monotonic_ns()-self.started)/1_000_000
        append(self.path,envelope(event_id=self.span_id+":end",phase="end",span_kind=self.kind,source=self.source,
            duration_ms=round(duration,3) if duration is not None else None,outcome=outcome,
            reason_code=reason_code or self.default_reason,bytes=self.bytes,**self.ids))
    def __exit__(self,typ,value,tb):
        normal_exit = typ is None or (typ is SystemExit and getattr(value,"code",0) in (0,None))
        self.finish("ok" if normal_exit else "error",None if normal_exit else typ.__name__)

def reduce(events):
    """Deduplicate and summarize effort; nested spans are never presented as wall time."""
    unique={e.get("event_id"):e for e in events if isinstance(e,dict) and e.get("event_id")}
    completed=[e for e in unique.values() if e.get("phase")=="end" and isinstance(e.get("duration_ms"),(int,float))]
    starts={e["event_id"].rsplit(":",1)[0] for e in unique.values() if e.get("phase")=="start"}
    ends={e["event_id"].rsplit(":",1)[0] for e in unique.values() if e.get("phase")=="end"}
    vals=sorted(max(0.0,float(e["duration_ms"])) for e in completed)
    pct=lambda p: vals[min(len(vals)-1,int((len(vals)-1)*p))] if vals else None
    reasons={e.get("reason_code","unknown") for e in completed if e.get("retry_of")}
    return {"event_count":len(unique),"completed_spans":len(completed),"incomplete_spans":len(starts-ends),
        "measured_effort_ms":round(sum(vals),3),"wall_time_ms":None,
        "overlap_note":"wall time requires a same-process root span; nested durations are not summed",
        "p50_ms":pct(.5),"p95_ms":pct(.95),
        "retries_by_reason":{r:sum(1 for e in completed if e.get("retry_of") and e.get("reason_code","unknown")==r) for r in reasons},
        "top_slow_spans":[{"event_id":e["event_id"],"span_kind":e.get("span_kind"),"duration_ms":e["duration_ms"]}
                          for e in sorted(completed,key=lambda x:-x["duration_ms"])[:10]]}

def stage_timings(events):
    """Project stage wall spans from work-start and accepted-output facts."""
    result={}
    for e in sorted(events,key=lambda x:str(x.get("timestamp",""))):
        stage=e.get("stage")
        if not stage: continue
        row=result.setdefault(stage,{"stage_started":None,"stage_finished":None,"provenance":"observed"})
        if e.get("kind") in {"dispatch_started","work_started"} and row["stage_started"] is None:
            row["stage_started"]=e.get("timestamp")
        if e.get("kind")=="output_accepted": row["stage_finished"]=e.get("timestamp")
    for row in result.values():
        try:
            start=datetime.fromisoformat(row["stage_started"].replace("Z","+00:00"))
            end=datetime.fromisoformat(row["stage_finished"].replace("Z","+00:00"))
            row["wall_seconds"]=max(0,(end-start).total_seconds())
        except (AttributeError,ValueError,TypeError): row["wall_seconds"]=None
    return result

def load_events(path):
    rows=[]
    try:
        for line in Path(path).read_text(encoding="utf-8",errors="replace").splitlines():
            try: rows.append(json.loads(line))
            except json.JSONDecodeError: continue
    except OSError: pass
    return rows

def sweep_closed(directory, *, retain_days=30, now=None, prefix=None):
    """Delete rotated `*.closed` files older than retain_days — one directory listing.

    This used to run inside maintain(), once per raw file: on TP1-15045 the Stop hook
    called maintain() for 5038 span files and each call globbed a 10076-entry directory
    (50 million pattern matches, ten minutes per capture). The sweep is the same for every
    file in a directory, so it runs once per directory."""
    directory = Path(directory)
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=retain_days)
    removed = []
    if not directory.is_dir():
        return removed
    with os.scandir(directory) as entries:
        for entry in entries:
            name = entry.name
            if not name.endswith(".closed") or (prefix and not name.startswith(prefix + ".")):
                continue
            try:
                if datetime.fromtimestamp(entry.stat().st_mtime, timezone.utc) < cutoff:
                    os.unlink(entry.path); removed.append(entry.path)
            except OSError:
                continue
    return removed

def _stamp_of(path):
    """What a raw file looked like BEFORE it was read: its size and `st_mtime_ns`. The stamp is taken
    first, so a line appended while the file is being read can only make the stamp look OLDER than
    the aggregate - the next pass then recomputes, never skips (the error runs towards more work)."""
    try:
        st=path.stat()
    except OSError:
        return None
    return {"size":st.st_size,"mtime_ns":st.st_mtime_ns}

def _aggregate_if_current(aggregate_path, stamp):
    """The stored summary when it was computed from a raw file with exactly this stamp, else None.
    An aggregate with no `source_stamp` (written before the stamp existed) is never current."""
    if stamp is None:
        return None
    try:
        stored=json.loads(aggregate_path.read_text(encoding="utf-8"))
    except (OSError,ValueError):
        return None
    if isinstance(stored,dict) and stored.get("source_stamp")==stamp and "incomplete_spans" in stored:
        return {k:v for k,v in stored.items() if k!="source_stamp"}
    return None

def maintain(path, aggregate_path, *, max_bytes=10*1024*1024, retain_days=30, now=None, sweep=True):
    """Write an aggregate before rotating/deleting closed raw spans. `sweep=False` leaves the
    `.closed` cleanup to one sweep_closed() call per directory (the batch caller's job).

    The aggregate carries `source_stamp` (size + mtime_ns of the raw file at the moment before it was
    read). A raw file whose stamp still matches is not read and its aggregate is not rewritten: on
    TP1-12586 every capture re-read and re-wrote all 1338+ aggregates (about 5 s a wave, every 40 s).
    `max_bytes=None` turns the size rotation off (the directory pass uses it: a daily merged file must
    never move to `.closed`, where the collect count and the merge key set would no longer see it)."""
    path,aggregate_path=Path(path),Path(aggregate_path)
    now=now or datetime.now(timezone.utc)
    stamp=_stamp_of(path)
    summary=_aggregate_if_current(aggregate_path,stamp)
    unchanged=summary is not None
    if not unchanged:
        summary=reduce(load_events(path))
        if summary["event_count"]:
            aggregate_path.parent.mkdir(parents=True,exist_ok=True)
            tmp=aggregate_path.with_suffix(aggregate_path.suffix+".tmp")
            stored=dict(summary,source_stamp=stamp) if stamp else summary
            tmp.write_text(json.dumps(stored,sort_keys=True,indent=2)+"\n",encoding="utf-8")
            os.replace(tmp,aggregate_path)
    rotated=None
    if max_bytes is not None and path.exists() and path.stat().st_size>max_bytes and summary["incomplete_spans"]==0:
        rotated=path.with_name(path.name+"."+now.strftime("%Y%m%dT%H%M%SZ")+".closed")
        os.replace(path,rotated)
    removed=[]; cutoff=now-timedelta(days=retain_days)
    if (path.exists() and summary["incomplete_spans"]==0 and
            datetime.fromtimestamp(path.stat().st_mtime,timezone.utc)<cutoff):
        historical=aggregate_path.with_name(path.name+"."+now.strftime("%Y%m%dT%H%M%SZ")+".aggregate.json")
        tmp=historical.with_suffix(historical.suffix+".tmp")
        tmp.write_text(json.dumps(summary,sort_keys=True,indent=2)+"\n",encoding="utf-8")
        os.replace(tmp,historical); path.unlink(); removed.append(str(path))
    if sweep and aggregate_path.exists():
        removed.extend(sweep_closed(path.parent, retain_days=retain_days, now=now, prefix=path.name))
    return {"aggregate":summary,"rotated":str(rotated) if rotated else None,"removed":removed,"unchanged":unchanged}

def merge_summaries(summaries):
    """Combine retained aggregates without inventing cross-file percentiles or wall time."""
    rows=[x for x in summaries if isinstance(x,dict)]
    retries={}
    for row in rows:
        for reason,count in (row.get("retries_by_reason") or {}).items(): retries[reason]=retries.get(reason,0)+count
    slow=sorted((x for row in rows for x in row.get("top_slow_spans") or []),
                key=lambda x:-float(x.get("duration_ms",0)))[:10]
    return {"event_count":sum(x.get("event_count",0) for x in rows),
        "completed_spans":sum(x.get("completed_spans",0) for x in rows),
        "incomplete_spans":sum(x.get("incomplete_spans",0) for x in rows),
        "measured_effort_ms":sum(x.get("measured_effort_ms",0) for x in rows),
        "wall_time_ms":None,"p50_ms":None,"p95_ms":None,"retries_by_reason":retries,
        "top_slow_spans":slow,"overlap_note":"retained aggregates do not support a global percentile or wall-time reconstruction"}

# --- the Stop-time directory pass (SC1-4): merge closed per-process files into one file per UTC day ---
# Why: a hook writes one `hook-<pid>.jsonl` per PROCESS - 1750 of them on TP1-12586, +300..450 an hour - and every
# capture used to re-read and re-write an aggregate for each. The pass below runs on Stop only, under one OS lock that the
# collect pack shares, and touches only what changed.

_EPOCH=datetime(1970,1,1,tzinfo=timezone.utc)
_MERGING=".merging"

def split_lines(text):
    """The ONE definition of "a line" of a telemetry file: split on "\\n" only, "\\r" stripped, blank lines dropped. The
    merge (what it keys and writes) and the collect pack's count both read through it, so a line that moved to the daily
    file keeps its key (AR-13)."""
    return [x.rstrip("\r") for x in text.split("\n") if x.strip()]

_PARSE=object()  # `line_key(line)` parses the line itself; `line_key(line, event=row)` takes a row the caller already parsed

def line_key(line, event=_PARSE):
    """The identity of one telemetry line: its `event_id` (what `reduce` deduplicates by), else the sha1 of the line.
    The merge and the collect pack's count use this one function, so they agree on what "the same line" is. The line
    is normalised here (trailing CR/LF dropped), whoever split it. `event` is the parsed row, or None when the line
    did not parse."""
    line=line.rstrip("\r\n")
    if event is _PARSE:
        try:
            event=json.loads(line)
        except (ValueError,RecursionError):
            event=None
    event_id=event.get("event_id") if isinstance(event,dict) else None
    if isinstance(event_id,str) and event_id:
        return event_id
    import hashlib  # off the hot path: only the merge and the count need a hash
    return "sha1:"+hashlib.sha1(line.encode("utf-8","replace")).hexdigest()

LOCK_HELD,LOCK_BUSY,LOCK_UNAVAILABLE="held","busy","unavailable"

class _MergeLock:
    """`with merge_lock(dir) as state:` - `state` is "held" when this process owns the directory's merge lock, "busy" when
    another process holds it (after the wait), "unavailable" when the lock could not be made at all (a read-only or
    broken state folder): nobody holds anything, and the caller must not say someone does (FR-41)."""
    def __init__(self, telemetry_dir, wait_seconds):
        self.root,self.wait,self._held=Path(telemetry_dir).parent/".telemetry-merge",wait_seconds,None
    def __enter__(self):
        # Imported here, not in the module header: this module is on the hot path of every hook (K7 pins it).
        from event_store import EventStore, StateConflict
        cm=EventStore(self.root).lock(self.wait)
        try:
            cm.__enter__()
        except StateConflict:  # held by another process: the pass is skipped, never failed
            return LOCK_BUSY
        except OSError:  # a folder that cannot take a lock: skipped as well, but it is not "busy"
            return LOCK_UNAVAILABLE
        self._held=cm
        return LOCK_HELD
    def __exit__(self,typ,value,tb):
        held,self._held=self._held,None
        return held.__exit__(typ,value,tb) if held is not None else False

def merge_lock(telemetry_dir, wait_seconds=0.0):
    """The ONE lock of the telemetry directory, taken by the Stop-time pass (no wait: busy means skip) and by the collect
    pack (waits up to its budget). An OS lock: it goes with the process that held it, so there is nothing to steal."""
    return _MergeLock(telemetry_dir,wait_seconds)

def _per_pid_kind(name):
    """'raw' for hook-<digits>.jsonl, 'merging' for hook-<digits>.jsonl.merging, None for every other name
    (command-*, hook-merged-*, aggregates, .closed are not this pass's business)."""
    is_merging=name.endswith(_MERGING)
    base=name[:-len(_MERGING)] if is_merging else name
    digits=base[5:-6] if base.startswith("hook-") and base.endswith(".jsonl") else ""
    if not (digits.isascii() and digits.isdigit()):
        return None
    return "merging" if is_merging else "raw"

def _read_lines(path):
    """The non-blank lines of a file (split on "\\n" only), or None when it cannot be read."""
    try:
        text=Path(path).read_text(encoding="utf-8",errors="replace")
    except OSError:
        return None
    return split_lines(text)

def _spans_closed(path):
    return reduce(load_events(path))["incomplete_spans"]==0

def _candidates(directory, now, quiet_s, stale_s, max_files):
    """Per-process files worth merging, oldest first, at most `max_files`. A `.merging` (an earlier pass died after its
    claim) is always taken. A raw file is taken when it is quiet for MORE than `quiet_s` and every span in it is closed,
    or when it is older than `stale_s` (a span that never closed will not close now)."""
    now_ns=(now-_EPOCH)//timedelta(microseconds=1)*1000
    quiet_ns,stale_ns=int(quiet_s*1_000_000_000),int(stale_s*1_000_000_000)
    picked=[]
    with os.scandir(directory) as entries:
        for entry in entries:
            kind=_per_pid_kind(entry.name)
            if kind is None:
                continue
            try:
                mtime=entry.stat().st_mtime_ns
            except OSError:
                continue
            age=now_ns-mtime
            if kind=="merging" or age>stale_ns or (age>quiet_ns and _spans_closed(entry.path)):
                picked.append((kind!="merging",mtime,entry.name,entry.path))
    picked.sort()
    return [Path(p[3]) for p in picked[:max_files]]

def _claim(path):
    """Take a file out of its writer's way by renaming it to `<name>.merging`. A pid can come back: a new `hook-<n>.jsonl`
    then starts a fresh file, and the old content is read from the claim. On Windows an open file cannot be renamed -
    None, and the file waits for the next pass. A fresh file is never claimed over a `.merging` that is still there."""
    path=str(path)
    if path.endswith(_MERGING):
        return Path(path)
    target=path+_MERGING
    if os.path.exists(target):
        return None
    try:
        os.replace(path,target)
    except OSError:
        return None
    return Path(target)

def _append_new(day_file, lines, keys):
    """Append the lines whose `line_key` is not in `keys` to `day_file`, and grow `keys`. Returns how many were written.
    Re-running it over lines already there writes nothing: that is what makes a crash after the append harmless."""
    fresh=[]
    for line in lines:
        key=line_key(line)
        if key not in keys:
            keys.add(key); fresh.append(line)
    if not fresh:
        return 0
    lead=""
    try:
        with open(day_file,"rb") as f:  # a pass killed mid-write may have left the last line without its newline
            if f.seek(0,2):
                f.seek(-1,2); lead="\n" if f.read(1)!=b"\n" else ""
    except OSError:
        pass
    with open(day_file,"ab") as f:
        f.write((lead+"\n".join(fresh)+"\n").encode("utf-8"))
    return len(fresh)

def _day_keys(day_file):
    """The keys already in a daily file: an empty set when there is no file yet, None when it exists but cannot be read
    (appending then could duplicate, so that day is left for the next pass)."""
    if not os.path.exists(day_file):
        return set()
    lines=_read_lines(day_file)
    return None if lines is None else {line_key(x) for x in lines}

def _discard(merging):
    """Remove a merged `.merging` and then its per-process aggregate; a refusal (antivirus holding the file) leaves it for
    the next pass, which reads it again and writes nothing new."""
    try:
        os.unlink(merging)
    except OSError:
        return
    try:
        os.unlink(Path(str(merging)[:-len(_MERGING)]).with_suffix(".aggregate.json"))
    except OSError:
        pass

def _merge_day(day_file, sources):
    """Merge the claimed files of one day: keys read once, one append, ONE fsync, and only then the removals."""
    keys=_day_keys(day_file)
    if keys is None:
        return 0
    _append_new(day_file,[x for _,lines in sources for x in lines],keys)
    if os.path.exists(day_file):
        with open(day_file,"ab") as f:
            f.flush(); os.fsync(f.fileno())
    for merging,_ in sources:
        _discard(merging)
    return len(sources)

def merge_closed(directory, *, now, quiet_s=30, stale_s=86400, max_files=5000):
    """Merge closed `hook-<pid>.jsonl` files into `hook-merged-<UTC date of the file's mtime>.jsonl`. CALLED UNDER
    `merge_lock` (maintain_dir holds it). Claim every chosen file, read, then per day: append what is new, fsync, remove.
    A crash anywhere leaves a `.merging`, and the next pass finishes it without writing a line twice."""
    directory,by_day=Path(directory),{}
    claimed=[_claim(p) for p in _candidates(directory,now,quiet_s,stale_s,max_files)]
    skipped=sum(1 for c in claimed if c is None)
    for merging in (c for c in claimed if c is not None):
        lines=_read_lines(merging)
        try:
            day=datetime.fromtimestamp(merging.stat().st_mtime,timezone.utc).strftime("%Y%m%d")
        except OSError:
            day=None
        if lines is None or day is None:
            skipped+=1
        else:
            by_day.setdefault(day,[]).append((merging,lines))
    merged=sum(_merge_day(directory/("hook-merged-%s.jsonl"%day),sources) for day,sources in sorted(by_day.items()))
    return {"merged":merged,"skipped":skipped,"days":sorted(by_day)}

def _maintain_each(directory, now, report):
    """Refresh the aggregate of every `*.jsonl` in the directory; one that fails is counted and does not stop the others."""
    with os.scandir(directory) as entries:
        names=sorted(e.name for e in entries if e.name.endswith(".jsonl"))
    for name in names:
        raw=directory/name
        try:  # max_bytes=None: the pass never rotates by size, so no `.closed` appears and no line leaves the count
            maintain(raw,raw.with_suffix(".aggregate.json"),max_bytes=None,now=now,sweep=False)
            report["maintained"]+=1
        except Exception:
            report["errors"]+=1

def _pass_under_lock(directory, now, max_files):
    """The body of `maintain_dir`, run while this process holds the merge lock."""
    report={"ran":True,"merge":None,"maintained":0,"errors":0}
    try:
        report["merge"]=merge_closed(directory,now=now,max_files=max_files)
    except Exception:
        report["errors"]+=1
    _maintain_each(directory,now,report)
    try:
        sweep_closed(directory,now=now)
    except Exception:
        report["errors"]+=1
    return report

def maintain_dir(directory, *, now=None, max_files=5000):
    """The whole Stop-time pass over the telemetry directory; nothing it does may fail its caller (a hook).
    No directory: nothing is created, not even the lock. Lock busy (the collect pack, or another Stop): skipped, and
    the report says `busy`; a lock that cannot be made says `unavailable` instead (nobody holds anything)."""
    directory=Path(directory)
    try:
        if not directory.is_dir():
            return {"ran":False}
        now=now or datetime.now(timezone.utc)
        with merge_lock(directory) as state:
            if state==LOCK_HELD:
                return _pass_under_lock(directory,now,max_files)
            return {"ran":False,state:True}
    except Exception:
        return {"ran":False,"error":True}
