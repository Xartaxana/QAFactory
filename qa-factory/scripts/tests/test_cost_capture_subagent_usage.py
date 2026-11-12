"""Regression (TP1-15045): subagent usage parsed as zero.

On a real session (b156530d, verified against the actual transcripts before this fix), every
one of six `agents[]` entries in `state/cost/<session>.json` showed `tokens: 0, cost: null`
although the six `subagents/agent-*.jsonl` files existed exactly where `cost_capture.py`
looks and carried 146 requests / 12.83M tokens between them. Cause: `scan_file()` dropped
every usage row whose record had `isSidechain: true` — correct for the MAIN transcript (a
defensive guard against ever double-billing a child's turns replayed inline there), wrong
for a `subagents/agent-*.jsonl` file, where current Claude Code tags every single row
`isSidechain: true` by construction (the whole file IS a sidechain). The guard zeroed 100%
of every subagent's usage, understating story cost by roughly half and making
"orchestrator share" always compute to 100%.

This fixture reproduces the row shape (structure only, no real conversation text) of that
session: a main-chain file with a task-marker write, an `Agent` tool_use dispatch, and its
own usage; a `subagents/agent-*.jsonl` with several `isSidechain: true` assistant rows
carrying `usage`, next to an `agent-*.meta.json` naming the role (the file the real
Claude Code writes and the shape `cost_capture.py` reads at ~line 578); and a second,
genuinely-empty dispatch to prove `incomplete_agents` still catches a REAL zero-usage
dispatch instead of going silent now that the false positives are gone.

Fails on the pre-fix code: agents[0]["tokens"] == 0 (assertion below expects it equal to
the fixture's own known sum) and "incomplete_agents" is absent from the document entirely
(KeyError) rather than naming only the one dispatch that is actually empty.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import cost_capture as C
from harness import temp_project, cleanup, SCRIPTS

SESSION = "fixture-i17-session"
TASK = "TEST-1"


def _row(**kw):
    return json.dumps(kw, ensure_ascii=False)


def build_transcripts(transcripts_root: Path):
    """Lay out <root>/<SESSION>.jsonl and <root>/<SESSION>/subagents/... like a real host."""
    main_path = transcripts_root / f"{SESSION}.jsonl"
    sub_dir = transcripts_root / SESSION / "subagents"
    sub_dir.mkdir(parents=True)

    main_usage = {"input_tokens": 100, "output_tokens": 50, "cache_read_input_tokens": 0,
                  "cache_creation": {"ephemeral_5m_input_tokens": 0, "ephemeral_1h_input_tokens": 0}}
    main_lines = [
        _row(type="user", isSidechain=False, promptId="p1", uuid="u0",
             timestamp="2026-09-20T19:22:00Z", message={"role": "user", "content": "synthetic prompt"}),
        # Same turn marks the task boundary (Write into artifacts/<TASK>/) and dispatches the role,
        # mirroring how a real orchestrator turn both writes an artifact and calls Agent.
        _row(type="assistant", isSidechain=False, requestId="req-main-1", uuid="u1",
             timestamp="2026-09-20T19:22:05Z",
             message={"model": "claude-sonnet-5", "usage": main_usage, "content": [
                 {"type": "tool_use", "id": "toolu_marker", "name": "Write",
                  "input": {"file_path": f"qa-factory/artifacts/{TASK}/understanding.md"}},
                 {"type": "tool_use", "id": "toolu_1", "name": "Agent",
                  "input": {"subagent_type": "qa-factory:qa-case-designer",
                             "description": f"qa-case-designer S4 {TASK}", "prompt": "synthetic"}},
             ]}),
    ]
    main_path.write_text("\n".join(main_lines) + "\n", encoding="utf-8")

    # --- Populated dispatch: real usage, tagged isSidechain like every row of a real
    # subagents/agent-*.jsonl file. This is the exact shape the bug zeroed.
    usage_1 = {"input_tokens": 40000, "output_tokens": 800, "cache_read_input_tokens": 0,
               "cache_creation": {"ephemeral_5m_input_tokens": 5000, "ephemeral_1h_input_tokens": 0}}
    usage_2 = {"input_tokens": 45000, "output_tokens": 1200, "cache_read_input_tokens": 40800,
               "cache_creation": {"ephemeral_5m_input_tokens": 0, "ephemeral_1h_input_tokens": 0}}
    agent_file = sub_dir / "agent-aaaa1111.jsonl"
    agent_lines = [
        _row(type="user", isSidechain=True, uuid="a-u0", timestamp="2026-09-20T19:22:10Z",
             message={"role": "user", "content": "synthetic role prompt"}),
        _row(type="assistant", isSidechain=True, requestId="req-agent-1", uuid="a-1",
             timestamp="2026-09-20T19:22:15Z",
             message={"model": "claude-sonnet-5", "usage": usage_1, "content": []}),
        _row(type="assistant", isSidechain=True, requestId="req-agent-2", uuid="a-2",
             timestamp="2026-09-20T19:22:40Z",
             message={"model": "claude-sonnet-5", "usage": usage_2, "content": []}),
    ]
    agent_file.write_text("\n".join(agent_lines) + "\n", encoding="utf-8")
    (sub_dir / "agent-aaaa1111.meta.json").write_text(json.dumps({
        "agentType": "qa-factory:qa-case-designer", "description": f"qa-case-designer S4 {TASK}",
        "toolUseId": "toolu_1", "spawnDepth": 1, "requestShape": "background",
        "requestNonInteractive": True}), encoding="utf-8")

    # --- Genuinely empty dispatch: no usage anywhere in its file. incomplete_agents must
    # still name THIS one after the fix stops naming every dispatch.
    empty_file = sub_dir / "agent-bbbb2222.jsonl"
    empty_file.write_text(_row(type="user", isSidechain=True, uuid="b-u0",
                                timestamp="2026-09-20T19:23:00Z",
                                message={"role": "user", "content": "synthetic role prompt"}) + "\n",
                           encoding="utf-8")
    (sub_dir / "agent-bbbb2222.meta.json").write_text(json.dumps({
        "agentType": "qa-factory:qa-scout", "description": f"qa-scout S1 {TASK}",
        "toolUseId": "toolu_2", "spawnDepth": 1, "requestShape": "background",
        "requestNonInteractive": True}), encoding="utf-8")

    return main_path, usage_1, usage_2, main_usage


def run_capture(root: Path, transcript: Path):
    event = {"hook_event_name": "Stop", "session_id": SESSION, "transcript_path": str(transcript),
              "cwd": str(root)}
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(root))
    result = subprocess.run([sys.executable, "-B", str(SCRIPTS / "cost_capture.py")],
                            input=json.dumps(event), text=True, capture_output=True,
                            encoding="utf-8", cwd=str(root), env=env, timeout=60)
    assert result.returncode == 0, f"cost_capture.py failed: {result.stderr}"
    return result


def main():
    root = temp_project()
    transcripts_root = root / "transcripts"
    transcripts_root.mkdir()
    try:
        main_path, usage_1, usage_2, main_usage = build_transcripts(transcripts_root)

        # A story activity, open-ended, covering every synthetic timestamp: exercises
        # has_factory_activity=True and the by_task["TEST-1"] reassignment path.
        activities_dir = root / "qa-factory" / "state" / "activities"
        activities_dir.mkdir(parents=True)
        (activities_dir / f"{SESSION}.json").write_text(json.dumps({
            "schema_version": 1, "session_id": SESSION,
            "activities": [{"activity_id": "act1", "type": "story", "task": TASK,
                "start_event_id": "e1", "start_time": "2026-09-20T19:21:00Z",
                "end_event_id": None, "end_time": None, "evidence_ref": None, "status": "open",
                "segments": [{"segment_id": "seg1", "start_event_id": "e1",
                    "start_time": "2026-09-20T19:21:00Z", "end_event_id": None, "end_time": None}]}],
            "active_stack": ["act1"], "processed_events": {}, "usage_completeness": "unknown",
        }), encoding="utf-8")

        run_capture(root, main_path)
        doc = json.loads((root / "qa-factory" / "state" / "cost" / f"{SESSION}.json").read_text())

        agents = {a["agent"]: a for a in doc["agents"]}
        assert set(agents) == {"qa-factory:qa-case-designer", "qa-factory:qa-scout"}, agents

        # --- The core defect: the populated dispatch's usage must be counted, not zeroed.
        expected_agg = C.zero()
        C.add_usage(expected_agg, usage_1)
        C.add_usage(expected_agg, usage_2)
        expected_tokens = sum(v for k, v in expected_agg.items() if k != "requests")
        designer = agents["qa-factory:qa-case-designer"]
        assert designer["tokens"] == expected_tokens, \
            f"expected {expected_tokens} tokens from the sidechain-tagged agent file, got {designer['tokens']}"
        assert designer["tokens"] > 0
        assert designer["cost"] is not None and designer["cost"] > 0, designer["cost"]

        # --- incomplete_agents: names the truly-empty dispatch, and only that one.
        assert "incomplete_agents" in doc, "field missing entirely — pre-fix document shape"
        assert doc["incomplete_agents"] == ["qa-factory:qa-scout"], doc["incomplete_agents"]
        assert agents["qa-factory:qa-scout"]["tokens"] == 0

        # --- has_factory_activity: the explicit story activity must flip it true.
        assert doc.get("has_factory_activity") is True, doc.get("has_factory_activity")

        # --- by_task includes role usage; orchestrator stays main-chain-only (design
        # already correct in by_task's fold-in — this asserts the two stay in sync once
        # agent usage is no longer zero).
        task = doc["by_task"][TASK]
        main_agg = C.zero()
        C.add_usage(main_agg, main_usage)
        main_tokens = sum(v for k, v in main_agg.items() if k != "requests")
        assert task["tokens"] == main_tokens + expected_tokens, (task["tokens"], main_tokens, expected_tokens)
        assert task["cost"] is not None and task["cost"] > doc["orchestrator"]["cost"], \
            "task cost must exceed the orchestrator-only cost once the role's spend is folded in"
        assert abs(task["priced_subtotal_usd"] - task["cost"]) < 0.001, \
            (task["priced_subtotal_usd"], task["cost"])

        print("PASS test_cost_capture_subagent_usage")
    finally:
        cleanup(root)


if __name__ == "__main__":
    main()
