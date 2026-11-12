"""telemetry_capture.sweep_closed: the `.closed` cleanup is one directory pass, not one glob
per raw file (TP1-15045: 5038 span files x a 10076-entry directory = ten minutes on
every Stop hook). maintain() keeps its default sweep for a single caller and skips it with
sweep=False for the batch caller in cost_capture."""
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import check, check_eq, cleanup, finish, temp_dir  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import telemetry_capture as T  # noqa: E402


def touch(path: Path, age_days: float = 0, text: str = "") -> Path:
    path.write_text(text, encoding="utf-8")
    if age_days:
        stamp = time.time() - age_days * 86400
        os.utime(path, (stamp, stamp))
    return path


def span_file(path: Path) -> Path:
    start = T.envelope(event_id="s:1", phase="start", span_kind="hook", source="test",
                       timestamp="2026-09-20T10:00:00+00:00")
    end = T.envelope(event_id="s:1", phase="end", span_kind="hook", source="test",
                     timestamp="2026-09-20T10:00:01+00:00", duration_ms=1000)
    path.write_text(json.dumps(start) + "\n" + json.dumps(end) + "\n", encoding="utf-8")
    return path


def main() -> None:
    d = temp_dir("qa-telemetry-sweep-")
    try:
        old = touch(d / "a.jsonl.20260801T000000Z.closed", age_days=45)
        fresh = touch(d / "a.jsonl.20260920T000000Z.closed", age_days=2)
        other_old = touch(d / "b.jsonl.20260801T000000Z.closed", age_days=45)
        raw = span_file(d / "a.jsonl")
        keep = touch(d / "notes.txt", age_days=45, text="x")

        removed = T.sweep_closed(d, prefix="a.jsonl")
        check("a prefix-bound sweep removes only that file's old .closed", not old.exists() and other_old.exists())
        check("a fresh .closed survives", fresh.exists())
        check_eq("the removed list names the file", [str(old)], removed)

        removed = T.sweep_closed(d)
        check("a directory sweep removes every old .closed", not other_old.exists())
        check("files that are not .closed are never touched", keep.exists() and raw.exists())
        check_eq("sweep of a missing directory is empty", [], T.sweep_closed(d / "nope"))

        old2 = touch(d / "a.jsonl.20260701T000000Z.closed", age_days=60)
        result = T.maintain(raw, raw.with_suffix(".aggregate.json"), sweep=False)
        check("maintain(sweep=False) writes the aggregate", (d / "a.aggregate.json").exists())
        check("the aggregate carries the source stamp that lets an unchanged file be skipped (SC1-4a)",
              set(json.loads((d / "a.aggregate.json").read_text(encoding="utf-8")).get("source_stamp", {})) == {"size", "mtime_ns"})
        check("maintain(sweep=False) leaves the old .closed to the batch sweep", old2.exists())
        result = T.maintain(raw, raw.with_suffix(".aggregate.json"))
        check("maintain() by default still sweeps its own old .closed", not old2.exists())
        check("and reports it", str(old2) in result["removed"])
    finally:
        cleanup(d)
    bytes_field()
    finish("test_telemetry_sweep")


def bytes_field() -> None:
    """t-267 C15: the envelope takes an optional `bytes` (what a REST call carried). Optional means: the
    older callers write the same line they always wrote, and a caller that passes it - to `envelope`, to the
    Span's constructor, or by setting `.bytes` before the span closes - never meets a TypeError."""
    plain = T.envelope(event_id="s:1", phase="end", span_kind="command", source="test", timestamp="2026-10-01T10:00:00+00:00")
    check("envelope without bytes writes no bytes key (older callers are unchanged)", "bytes" not in plain)
    sized = T.envelope(event_id="s:1", phase="end", span_kind="command", source="test", duration_ms=3, bytes=8168,
                       timestamp="2026-10-01T10:00:00+00:00")
    check_eq("envelope with bytes carries it", sized["bytes"], 8168)
    check_eq("bytes=0 is a real size and is kept (only None is dropped)",
             T.envelope(event_id="s:1", phase="end", span_kind="command", source="test", bytes=0).get("bytes"), 0)
    d = temp_dir("qa-telemetry-bytes-")
    try:
        path = d / "command-1.jsonl"
        with T.Span(path, span_kind="command", source="plugin:ticket_adapter.py", task="QA-1", reason_code="jira_rest_read") as span:
            span.bytes = 120
        events = T.load_events(path)
        check_eq("a span whose .bytes is set before it closes writes it on the END event only",
                 [(e["phase"], e.get("bytes")) for e in events], [("start", None), ("end", 120)])
        path2 = d / "command-2.jsonl"
        with T.Span(path2, span_kind="command", source="test", bytes=7):
            pass
        check_eq("a Span given bytes= in its constructor: no TypeError, same place",
                 [(e["phase"], e.get("bytes")) for e in T.load_events(path2)], [("start", None), ("end", 7)])
        path3 = d / "command-3.jsonl"
        try:
            with T.Span(path3, span_kind="command", source="test") as span:
                span.bytes = 5
                raise RuntimeError("the call failed")
        except RuntimeError:
            pass
        end = [e for e in T.load_events(path3) if e["phase"] == "end"][0]
        check_eq("a failing call still closes its span, outcome error, with the bytes it had", (end["outcome"], end.get("bytes")), ("error", 5))
        summary = T.reduce(T.load_events(path))
        check_eq("reduce() reads spans that carry bytes as it always did", (summary["completed_spans"], summary["incomplete_spans"]), (1, 0))
        blocker = d / "blocker"
        blocker.write_text("a file", encoding="utf-8")
        with T.Span(blocker / "command-4.jsonl", span_kind="command", source="test") as span:
            span.bytes = 1
        check("a span in an unwritable place is fail-silent: the call it wraps is not affected", True)
    finally:
        cleanup(d)


if __name__ == "__main__":
    main()
