"""Sticky activity attribution: a gap between two segments of the SAME story, with no
other activity's segment between them, belongs to that story; so does the tail after the
session's last segment. Regression: the orchestrator closes the story activity before every
stop (`activity_capture.py --action end --after-response`), the person answers, work
continues with no new start — everything between segments used to be nobody's. On
TP1-15045 (session 57cf578c) three of five role dispatches opened their first request
in exactly such a gap and were billed "(no task)" though the story never actually stopped.

Also covers the role-attribution order this fix changes: a role's OWN markers win, then the
ticket its own prompt names (`hooklib.subagent_meta`), then the activity it ran inside
(sticky), then "(no task)".
"""
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import cost_capture as C
from harness import temp_project, cleanup, check, check_eq, finish, SCRIPTS

SESSION = "fixture-sticky-session"
TASK = "TP1-STICKY"


def _ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def unit_tests():
    # Two closed segments of the SAME story, with a gap between them.
    activities = [{"activity_id": "act-story", "type": "story", "task": TASK, "segments": [
        {"segment_id": "seg1", "start_time": "2026-09-20T10:00:00Z", "end_time": "2026-09-20T10:10:00Z"},
        {"segment_id": "seg2", "start_time": "2026-09-20T10:20:00Z", "end_time": None},
    ]}]
    inside = C.sticky_activity_binding(activities, _ts("2026-09-20T10:05:00Z"))
    check_eq("ts inside a segment resolves exactly as before", inside, ("act-story", "seg1"))
    gap = C.sticky_activity_binding(activities, _ts("2026-09-20T10:15:00Z"))
    check_eq("a gap between two segments of the SAME story belongs to it",
             gap, ("act-story", "seg1"))
    tail = C.sticky_activity_binding(activities, _ts("2026-09-20T10:25:00Z"))
    check_eq("inside the still-open tail segment resolves normally", tail, ("act-story", "seg2"))
    check_eq("sticky_activity_at returns just the activity id",
             C.sticky_activity_at(activities, _ts("2026-09-20T10:15:00Z")), "act-story")

    # A gap between segments of TWO DIFFERENT activities belongs to neither.
    two_activities = [
        {"activity_id": "act-a", "type": "story", "task": "A", "segments": [
            {"segment_id": "a1", "start_time": "2026-09-20T09:00:00Z", "end_time": "2026-09-20T09:10:00Z"}]},
        {"activity_id": "act-b", "type": "story", "task": "B", "segments": [
            {"segment_id": "b1", "start_time": "2026-09-20T09:20:00Z", "end_time": None}]},
    ]
    cross = C.sticky_activity_binding(two_activities, _ts("2026-09-20T09:15:00Z"))
    check_eq("a gap between two DIFFERENT activities stays unclassified",
             cross, ("unclassified", "unclassified"))

    # A tail after the session's last (closed) STORY segment belongs to that segment's story.
    closed_story = [{"activity_id": "act-c", "type": "story", "task": "C", "segments": [
        {"segment_id": "c1", "start_time": "2026-09-20T08:00:00Z", "end_time": "2026-09-20T08:05:00Z"}]}]
    late_tail = C.sticky_activity_binding(closed_story, _ts("2026-09-20T09:00:00Z"))
    check_eq("the tail after the whole session's last STORY segment belongs to it",
             late_tail, ("act-c", "c1"))

    # ts before any segment ever started: unclassified, same as before.
    early = C.sticky_activity_binding(closed_story, _ts("2026-09-20T07:00:00Z"))
    check_eq("before any segment ever started stays unclassified",
             early, ("unclassified", "unclassified"))

    check_eq("ts=None stays unclassified, never raises",
             C.sticky_activity_binding(closed_story, None), ("unclassified", "unclassified"))
    check_eq("no activities at all stays unclassified",
             C.sticky_activity_binding([], _ts("2026-09-20T09:00:00Z")), ("unclassified", "unclassified"))

    # A doctor/onboarding tail is NOT swept forward (the rule restricts sticky to type=="story"):
    # test_codex_host.py pins a doctor run's post-segment silence staying Unclassified.
    closed_doctor = [{"activity_id": "act-d", "type": "doctor", "segments": [
        {"segment_id": "d1", "start_time": "2026-09-20T08:00:00Z", "end_time": "2026-09-20T08:05:00Z"}]}]
    doctor_tail = C.sticky_activity_binding(closed_doctor, _ts("2026-09-20T09:00:00Z"))
    check_eq("a doctor session's tail stays unclassified, not swept forward",
             doctor_tail, ("unclassified", "unclassified"))
    doctor_gap = [{"activity_id": "act-d", "type": "doctor", "segments": [
        {"segment_id": "d1", "start_time": "2026-09-20T08:00:00Z", "end_time": "2026-09-20T08:05:00Z"},
        {"segment_id": "d2", "start_time": "2026-09-20T08:10:00Z", "end_time": None}]}]
    doctor_gap_binding = C.sticky_activity_binding(doctor_gap, _ts("2026-09-20T08:07:00Z"))
    check_eq("a gap between two doctor segments stays unclassified too",
             doctor_gap_binding, ("unclassified", "unclassified"))


def _row(**kw):
    return json.dumps(kw, ensure_ascii=False)


def run_capture(root: Path, transcript: Path):
    event = {"hook_event_name": "Stop", "session_id": SESSION, "transcript_path": str(transcript),
              "cwd": str(root)}
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(root))
    result = subprocess.run([sys.executable, "-B", str(SCRIPTS / "cost_capture.py")],
                            input=json.dumps(event), text=True, capture_output=True,
                            encoding="utf-8", cwd=str(root), env=env, timeout=60)
    check("cost_capture.py exits 0", result.returncode == 0, result.stderr)
    return result


def end_to_end():
    root = temp_project()
    transcripts_root = root / "transcripts"
    transcripts_root.mkdir()
    try:
        main_path = transcripts_root / f"{SESSION}.jsonl"
        sub_dir = transcripts_root / SESSION / "subagents"
        sub_dir.mkdir(parents=True)

        main_usage = {"input_tokens": 100, "output_tokens": 20, "cache_read_input_tokens": 0,
                      "cache_creation": {"ephemeral_5m_input_tokens": 0, "ephemeral_1h_input_tokens": 0}}
        main_path.write_text(_row(type="assistant", isSidechain=False, requestId="req-main-1",
            uuid="u1", timestamp="2026-09-20T19:15:00Z",
            message={"model": "claude-sonnet-5", "usage": main_usage, "content": []}) + "\n",
            encoding="utf-8")

        # Role A: dispatched with its FIRST request inside the GAP between two closed story
        # segments, no ticket line in its own prompt, no own markers — must inherit the story
        # via sticky attribution, not fall to "(no task)".
        gap_usage = {"input_tokens": 40000, "output_tokens": 800, "cache_read_input_tokens": 0,
                     "cache_creation": {"ephemeral_5m_input_tokens": 0, "ephemeral_1h_input_tokens": 0}}
        gap_file = sub_dir / "agent-gap0001.jsonl"
        gap_file.write_text("\n".join([
            _row(type="user", isSidechain=True, uuid="g-u0", timestamp="2026-09-20T19:16:00Z",
                 message={"role": "user", "content": "synthetic role prompt, no markers"}),
            _row(type="assistant", isSidechain=True, requestId="req-gap-1", uuid="g-1",
                 timestamp="2026-09-20T19:16:05Z",
                 message={"model": "claude-sonnet-5", "usage": gap_usage, "content": []}),
        ]) + "\n", encoding="utf-8")
        (sub_dir / "agent-gap0001.meta.json").write_text(json.dumps({
            "agentType": "qa-factory:qa-case-critic", "description": "qa-case-critic gap dispatch"}),
            encoding="utf-8")

        # Role B: dispatched inside that same gap, but its OWN prompt names the ticket
        # directly — must attribute from the prompt, no activity lookup needed.
        ticket_usage = {"input_tokens": 15000, "output_tokens": 300, "cache_read_input_tokens": 0,
                        "cache_creation": {"ephemeral_5m_input_tokens": 0, "ephemeral_1h_input_tokens": 0}}
        ticket_file = sub_dir / "agent-tick0002.jsonl"
        ticket_file.write_text("\n".join([
            _row(type="user", isSidechain=True, uuid="t-u0", timestamp="2026-09-20T19:17:00Z",
                 message={"role": "user", "content": f"You are qa-runner. Ticket: {TASK}. "
                          "Dispatch id: S6-qa-runner-1. Return your digest line only."}),
            _row(type="assistant", isSidechain=True, requestId="req-tick-1", uuid="t-1",
                 timestamp="2026-09-20T19:17:05Z",
                 message={"model": "claude-sonnet-5", "usage": ticket_usage, "content": []}),
        ]) + "\n", encoding="utf-8")
        (sub_dir / "agent-tick0002.meta.json").write_text(json.dumps({
            "agentType": "qa-factory:qa-runner", "description": "qa-runner ticket dispatch"}),
            encoding="utf-8")

        # Story activity: segment 1 closed at 19:15:30 (before the gap dispatches), segment 2
        # reopens at 19:18:00 (after them) and stays open — the exact "closed before every
        # stop, reopened only on the next explicit marker" shape of the real defect.
        activities_dir = root / "qa-factory" / "state" / "activities"
        activities_dir.mkdir(parents=True)
        (activities_dir / f"{SESSION}.json").write_text(json.dumps({
            "schema_version": 1, "session_id": SESSION,
            "activities": [{"activity_id": "act1", "type": "story", "task": TASK,
                "start_event_id": "e1", "start_time": "2026-09-20T19:14:00Z",
                "end_event_id": None, "end_time": None, "evidence_ref": None, "status": "open",
                "segments": [
                    {"segment_id": "seg1", "start_event_id": "e1", "start_time": "2026-09-20T19:14:00Z",
                     "end_event_id": "e2", "end_time": "2026-09-20T19:15:30Z"},
                    {"segment_id": "seg2", "start_event_id": "e3", "start_time": "2026-09-20T19:18:00Z",
                     "end_event_id": None, "end_time": None},
                ]}],
            "active_stack": ["act1"], "processed_events": {}, "usage_completeness": "unknown",
        }), encoding="utf-8")

        run_capture(root, main_path)
        doc = json.loads((root / "qa-factory" / "state" / "cost" / f"{SESSION}.json").read_text())

        agents = {a["agent"]: a for a in doc["agents"]}
        check_eq("the gap dispatch (no marker) is attributed to the story, not '(no task)'",
                 agents["qa-factory:qa-case-critic"]["task"], TASK)
        check_eq("the ticket dispatch is attributed straight from its own prompt",
                 agents["qa-factory:qa-runner"]["task"], TASK)
        check_eq("by_task folds both gap-attributed roles in", TASK in doc["by_task"], True)
        task_tokens = doc["by_task"][TASK]["tokens"]
        check("the story's by_task total includes both marker-less dispatches",
              task_tokens > 40000, f"got {task_tokens}")
    finally:
        cleanup(root)


def main() -> None:
    unit_tests()
    end_to_end()
    finish("test_cost_capture_sticky_attribution")


if __name__ == "__main__":
    main()
