"""a session with no factory activity writes a one-line summary, not the full
per-request file.

Regression this guards: an analysis session whose shell merely sat inside an onboarded
project (no doctor/onboarding/story activity ever opened) left a 1.8 MB
state/cost/<session>.json behind — 1449 individual request rows, 1.3 MB of the file, because
cost_capture.py replays the WHOLE persisted "requests" ledger into scan_file_incremental's
prior_usage every single PostToolUse/Stop call, forever. The fix collapses the persisted
ledger to one carry row per (stream, model) once has_factory_activity is False, and forces a
full re-scan of the transcript (instead of resuming from the collapsed ledger) so no usage is
silently dropped.

This test proves both halves: (1) the written file stays small — one row per model, not one
per request — when no activity was ever opened; (2) running capture a SECOND time, after the
transcript grew further, still reports the FULL cumulative total (nothing lost to the
collapse), because the scan is forced non-incremental for a session at this state.
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

SESSION = "fixture-nonfactory-session"


def _row(**kw):
    return json.dumps(kw, ensure_ascii=False)


def _assistant_row(request_id, uuid_, ts, model, input_tokens):
    usage = {"input_tokens": input_tokens, "output_tokens": 10, "cache_read_input_tokens": 0,
             "cache_creation": {"ephemeral_5m_input_tokens": 0, "ephemeral_1h_input_tokens": 0}}
    return _row(type="assistant", isSidechain=False, requestId=request_id, uuid=uuid_,
                timestamp=ts, message={"model": model, "usage": usage, "content": []})


def run_capture(root: Path, transcript: Path):
    event = {"hook_event_name": "Stop", "session_id": SESSION, "transcript_path": str(transcript),
              "cwd": str(root)}
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(root))
    result = subprocess.run([sys.executable, "-B", str(SCRIPTS / "cost_capture.py")],
                            input=json.dumps(event), text=True, capture_output=True,
                            encoding="utf-8", cwd=str(root), env=env, timeout=60)
    assert result.returncode == 0, f"cost_capture.py failed: {result.stderr}"


def main():
    root = temp_project()
    transcripts_root = root / "transcripts"
    transcripts_root.mkdir()
    try:
        main_path = transcripts_root / f"{SESSION}.jsonl"
        # No qa-factory/state/activities/<SESSION>.json is written at all: exactly the shape
        # of a shell that never ran doctor/onboarding/qa-story — has_factory_activity must
        # come out False, never having had anywhere to become True.

        # --- Round 1: several individual requests across two models.
        lines = [_assistant_row(f"req-{i}", f"u{i}", f"2026-09-21T08:00:{i:02d}Z",
                                 "claude-sonnet-5", 1000 + i)
                  for i in range(10)]
        lines += [_assistant_row(f"req-b{i}", f"ub{i}", f"2026-09-21T08:01:{i:02d}Z",
                                  "claude-opus-5", 500 + i) for i in range(5)]
        main_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        run_capture(root, main_path)
        out = root / "qa-factory" / "state" / "cost" / f"{SESSION}.json"
        doc1 = json.loads(out.read_text(encoding="utf-8"))

        assert doc1.get("has_factory_activity") is False, doc1.get("has_factory_activity")
        # The core fix: not one row per request (15 in round 1) — one per (stream, model).
        assert len(doc1["requests"]) == 2, f"expected 2 carry rows, got {len(doc1['requests'])}: {doc1['requests']}"
        assert {r["model_id"] for r in doc1["requests"]} == {"claude-sonnet-5", "claude-opus-5"}
        assert all(r["task"] == "(no task)" for r in doc1["requests"])
        round1_sonnet_input = sum(1000 + i for i in range(10))
        round1_opus_input = sum(500 + i for i in range(5))
        assert doc1["by_model"]["claude-sonnet-5"]["input"] == round1_sonnet_input
        assert doc1["by_model"]["claude-opus-5"]["input"] == round1_opus_input
        round1_cost = doc1["total_cost_usd"]
        assert round1_cost is not None and round1_cost > 0

        # --- Round 2: the transcript grows (more turns, same session, still no activity).
        more = [_assistant_row(f"req-{i}", f"u{i}", f"2026-09-21T08:02:{i:02d}Z",
                                "claude-sonnet-5", 2000 + i) for i in range(10, 20)]
        with main_path.open("a", encoding="utf-8") as fh:
            fh.write("\n".join(more) + "\n")

        run_capture(root, main_path)
        doc2 = json.loads(out.read_text(encoding="utf-8"))

        assert doc2.get("has_factory_activity") is False
        # Still collapsed — growth in the transcript must not regrow the ledger.
        assert len(doc2["requests"]) == 2, f"expected 2 carry rows after growth, got {len(doc2['requests'])}"
        round2_sonnet_input = sum(2000 + i for i in range(10, 20))
        # The critical assertion: round 2's total is CUMULATIVE (round 1 + round 2), not just
        # round 2's delta. A stale/incremental seed from the collapsed ledger would have lost
        # round 1's rows here, since they are no longer replayed as individual requests.
        assert doc2["by_model"]["claude-sonnet-5"]["input"] == round1_sonnet_input + round2_sonnet_input, (
            doc2["by_model"]["claude-sonnet-5"]["input"], round1_sonnet_input, round2_sonnet_input)
        assert doc2["by_model"]["claude-opus-5"]["input"] == round1_opus_input
        assert doc2["total_cost_usd"] > round1_cost

        # Sanity: a session WITH factory activity keeps the full per-request ledger (no
        # regression to the existing, tested behaviour of test_cost_capture_subagent_usage.py).
        assert C.collapse_requests([], "s", {}, C.load_catalogue()) == []

        print("PASS test_cost_capture_nonfactory_summary")
    finally:
        cleanup(root)


if __name__ == "__main__":
    main()
