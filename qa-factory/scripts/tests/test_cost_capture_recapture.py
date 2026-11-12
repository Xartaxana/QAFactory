"""cost_capture.py --recapture / --all-stale: recompute a state/cost/<session>.json
that predates `has_factory_activity`, or is older than its own activity file (a backfill
landed after the original capture — 58e0f9dc: has_factory_activity stayed False, $4.56 of
$6.62 stayed outside the story). A session whose transcript is gone is marked
"not_recomputed", never treated as an error that stops the batch.
"""
import hashlib
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import cost_capture as C
from harness import temp_project, cleanup, use_project, check, check_eq, finish

SESSION = "fixture-recapture-session"
TASK = "TP1-RECAP"


def _row(**kw):
    return json.dumps(kw, ensure_ascii=False)


def _write_transcript(path: Path, tokens: int):
    usage = {"input_tokens": tokens, "output_tokens": 50, "cache_read_input_tokens": 0,
             "cache_creation": {"ephemeral_5m_input_tokens": 0, "ephemeral_1h_input_tokens": 0}}
    lines = [
        _row(type="assistant", isSidechain=False, requestId="req-1", uuid="u1",
             timestamp="2026-09-20T19:00:00Z",
             message={"model": "claude-sonnet-5", "usage": usage, "content": [
                 {"type": "tool_use", "id": "toolu_marker", "name": "Write",
                  "input": {"file_path": f"qa-factory/artifacts/{TASK}/understanding.md"}}]}),
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    root = temp_project()
    use_project(root)
    try:
        transcripts_root = root / "transcripts"
        transcripts_root.mkdir()
        transcript = transcripts_root / f"{SESSION}.jsonl"
        _write_transcript(transcript, 1000)

        cost_dir = root / "qa-factory" / "state" / "cost"
        cost_dir.mkdir(parents=True, exist_ok=True)

        # --- Case 1: old-format file (no has_factory_activity at all, like b156530d) ---
        old_format = {"session_id": SESSION, "transcript": str(transcript),
                      "generated": "2026-09-20T19:05:00+00:00", "total_cost_usd": None,
                      "by_task": {}, "requests": []}
        out_path = cost_dir / f"{SESSION}.json"
        out_path.write_text(json.dumps(old_format), encoding="utf-8")

        stale, reason = C._stale_reason(old_format, root / "qa-factory" / "state" / "activities" / f"{SESSION}.json")
        check("an old-format file (no has_factory_activity) is flagged stale", stale, reason)

        outcome = C.recapture_session(root, SESSION)
        check_eq("recapture reports 'recomputed'", outcome["status"], "recomputed")
        recomputed = json.loads(out_path.read_text(encoding="utf-8"))
        check("the recomputed file now carries has_factory_activity",
              "has_factory_activity" in recomputed, recomputed)
        check("the recomputed file has a real total (not the old None)",
              recomputed.get("total_cost_usd") is not None, recomputed.get("total_cost_usd"))

        # --- Case 2: fresh (new-format, has_factory_activity present) file is NOT stale ---
        fresh_stale, fresh_reason = C._stale_reason(recomputed,
            root / "qa-factory" / "state" / "activities" / f"{SESSION}.json")
        check_eq("a just-recomputed file is no longer stale", fresh_stale, False)

        # --- Case 3: activity file changed AFTER the capture (backfill landed later) ---
        activities_dir = root / "qa-factory" / "state" / "activities"
        activities_dir.mkdir(parents=True, exist_ok=True)
        activity_file = activities_dir / f"{SESSION}.json"
        activity_file.write_text(json.dumps({
            "schema_version": 1, "session_id": SESSION,
            "activities": [{"activity_id": "act1", "type": "story", "task": TASK,
                "start_event_id": "e1", "start_time": "2026-09-20T18:59:00Z",
                "end_event_id": None, "end_time": None, "status": "open",
                "segments": [{"segment_id": "seg1", "start_event_id": "e1",
                    "start_time": "2026-09-20T18:59:00Z", "end_event_id": None, "end_time": None}]}],
            "active_stack": ["act1"], "processed_events": {}, "usage_completeness": "unknown",
        }), encoding="utf-8")
        # Force the activity file's mtime after the recorded "generated" timestamp.
        future = time.time() + 5
        os.utime(activity_file, (future, future))
        backfilled_stale, backfilled_reason = C._stale_reason(recomputed, activity_file)
        check("a backfilled activity file newer than the capture is flagged stale",
              backfilled_stale, backfilled_reason)

        outcome2 = C.recapture_session(root, SESSION)
        check_eq("recapture after a backfill reports 'recomputed'", outcome2["status"], "recomputed")
        after_backfill = json.loads(out_path.read_text(encoding="utf-8"))
        check_eq("has_factory_activity now flips True once the activity shows a story",
                 after_backfill.get("has_factory_activity"), True)
        check_eq("the recomputed by_task now attributes to the real story task",
                 TASK in after_backfill.get("by_task", {}), True)

        # --- Case 3b (t-459): freshness by CONTENT, not by a same-second mtime. `generated` is written
        # rounded down to the whole second, so an activity file written in the capture's own second
        # (before the capture, with the very content it read) has mtime > `generated`. ---
        generated_ts = C.parse_ts(after_backfill["generated"]).timestamp()
        same_second = generated_ts + 0.5
        # (a) unchanged content, mtime half a second past the rounded-down `generated`: current.
        os.utime(activity_file, (same_second, same_second))
        same_stale, same_reason = C._stale_reason(after_backfill, activity_file)
        check_eq("(a) same content, mtime = floor(generated) + 0.5 s is NOT stale",
                 (same_stale, same_reason), (False, ""))
        check("(a) the capture stored the sha256 of the activity file it read",
              after_backfill.get("activities_hash") == hashlib.sha256(activity_file.read_bytes()).hexdigest(),
              after_backfill.get("activities_hash"))
        check_eq("(a) a capture that found no activity file stored an empty hash",
                 recomputed.get("activities_hash"), "")
        # (b) the same mtime, changed content: stale, for the activity reason.
        original_bytes = activity_file.read_bytes()
        activity_file.write_bytes(original_bytes + b"\n")
        os.utime(activity_file, (same_second, same_second))
        changed_stale, changed_reason = C._stale_reason(after_backfill, activity_file)
        check("(b) same mtime, changed content is stale with the activity reason",
              changed_stale and "activity file changed" in changed_reason, changed_reason)
        os.utime(activity_file, (generated_ts - 5, generated_ts - 5))
        skew_stale, skew_reason = C._stale_reason(after_backfill, activity_file)
        check("(b) changed content with an OLDER mtime (clock skew) is stale too",
              skew_stale and "activity file changed" in skew_reason, skew_reason)
        activity_file.write_bytes(original_bytes)
        # (c) a document written before the field existed keeps the mtime rule: newer mtime is stale.
        legacy = {k: v for k, v in after_backfill.items() if k != "activities_hash"}
        os.utime(activity_file, (same_second, same_second))
        legacy_stale, legacy_reason = C._stale_reason(legacy, activity_file)
        check("(c) no activities_hash and mtime > generated is stale as before",
              legacy_stale and "activity file changed" in legacy_reason, legacy_reason)
        # (d) the same document, mtime not past `generated`: current.
        os.utime(activity_file, (generated_ts - 5, generated_ts - 5))
        legacy_current = C._stale_reason(legacy, activity_file)
        check_eq("(d) no activities_hash and mtime <= generated is current",
                 legacy_current, (False, ""))

        # --- Case 4: transcript gone -> "not_recomputed", file untouched otherwise, marker written ---
        missing_session = "fixture-recapture-missing"
        missing_path = cost_dir / f"{missing_session}.json"
        missing_doc = {"session_id": missing_session,
                       "transcript": str(transcripts_root / "does-not-exist.jsonl"),
                       "total_cost_usd": 3.14}
        missing_path.write_text(json.dumps(missing_doc), encoding="utf-8")
        outcome3 = C.recapture_session(root, missing_session)
        check_eq("a session whose transcript is gone is not_recomputed",
                 outcome3["status"], "not_recomputed")
        marked = json.loads(missing_path.read_text(encoding="utf-8"))
        check_eq("the original figures are preserved when the transcript is gone",
                 marked["total_cost_usd"], 3.14)
        check_eq("a recapture_status marker is written for the dashboard to show",
                 marked.get("recapture_status", {}).get("status"), "not_recomputed")

        # --- --all-stale sweeps every stale file in one call ---
        results = C.recapture_stale(root)
        by_session = {r["session_id"]: r for r in results}
        check_eq("--all-stale still reports the missing-transcript session as not_recomputed",
                 by_session.get(missing_session, {}).get("status"), "not_recomputed")
    finally:
        cleanup(root)
    finish("test_cost_capture_recapture")


if __name__ == "__main__":
    main()
