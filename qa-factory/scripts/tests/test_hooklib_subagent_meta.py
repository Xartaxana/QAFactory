"""hooklib.subagent_meta / story_subagent_transcripts.

subagent_meta parses the orchestrator's own "You are <role>. Ticket: <TICKET>.
Dispatch id: <id>..." first-user-message prompt out of one subagents/agent-*.jsonl file;
cost_capture.py uses the ticket to attribute a marker-less role dispatch before falling
back to the activity it ran inside. story_subagent_transcripts inventories every subagent
transcript of sessions that touched a project, from state/cost/*.json's own `transcript`
field and that file's sibling subagents/ dir.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import hooklib as H
from harness import temp_dir, cleanup, check, check_eq, finish


def _row(**kw):
    return json.dumps(kw, ensure_ascii=False)


def main() -> None:
    root = temp_dir()
    try:
        # --- subagent_meta: role/ticket/dispatch id from the first user message ---
        transcript = root / "agent-aaaa1111.jsonl"
        lines = [
            _row(type="user", isSidechain=True, uuid="a-u0", timestamp="2026-09-20T19:22:10Z",
                 message={"role": "user", "content": "You are qa-code-critic. Ticket: "
                          "TP1-15045. Dispatch id: S5-qa-code-critic-2 (window 1, API, "
                          "round 2 — the last).\nArtifacts dir: qa-factory/artifacts/"
                          "TP1-15045/\nReturn your digest line only."}),
            _row(type="assistant", isSidechain=True, requestId="req-1", uuid="a-1",
                 timestamp="2026-09-20T19:22:15Z",
                 message={"model": "claude-sonnet-5", "content": []}),
            _row(type="assistant", isSidechain=True, requestId="req-2", uuid="a-2",
                 timestamp="2026-09-20T19:30:00Z",
                 message={"model": "claude-sonnet-5", "content": []}),
        ]
        transcript.write_text("\n".join(lines) + "\n", encoding="utf-8")
        meta = H.subagent_meta(transcript)
        check("role parsed from 'You are <role>.'", meta["role"], "qa-code-critic")
        check("ticket parsed from 'Ticket: <id>.'", meta["ticket"], "TP1-15045")
        check("dispatch id parsed even mid-line", meta["dispatch_id"], "S5-qa-code-critic-2")
        check("first_at is the earliest timestamp", meta["first_at"] is not None, True)
        check("last_at is the latest timestamp", meta["last_at"] > meta["first_at"], True)

        # --- K4-1: the REAL prompt `story_step._prompt` writes (`Dispatch: <id>.`, the line's own dot) ---
        import story_step
        real_prompt = story_step._prompt("QA-1", {"id": "S5", "inputs": []}, "qa-code-critic", "S5-qa-code-critic-3", [])
        check("K4-1 control: the real prompt carries the dispatch in the `Dispatch: <id>.` form",
              "Ticket: QA-1. Dispatch: S5-qa-code-critic-3." in real_prompt, real_prompt.splitlines()[0])
        real = root / "agent-real.jsonl"
        real.write_text(_row(type="user", isSidechain=True, uuid="r-u0", timestamp="2026-09-20T19:22:10Z",
                             message={"role": "user", "content": real_prompt}) + "\n", encoding="utf-8")
        meta_real = H.subagent_meta(real)
        check_eq("K4-1 the real prompt: the id has no final dot", meta_real["dispatch_id"], "S5-qa-code-critic-3")
        check_eq("K4-1 ... the ticket has none either", meta_real["ticket"], "QA-1")
        check_eq("K4-1 ... the role", meta_real["role"], "qa-code-critic")
        for text, expected in (("Dispatch id: S5-x-1.2 (window)", "S5-x-1.2"),       # an id with an inner dot keeps it
                               ("Dispatch: S5-x-1.2.", "S5-x-1.2"),                  # ... and the line's last dot is not its
                               ("Dispatch: S5-x-1.", "S5-x-1")):
            kept = root / "agent-dots.jsonl"
            kept.write_text(_row(type="user", uuid="d-u0", message={"role": "user", "content": "You are r. " + text}) + "\n",
                            encoding="utf-8")
            check_eq(f"K4-1 [{text}]", H.subagent_meta(kept)["dispatch_id"], expected)

        # --- no "Ticket:"/"Dispatch id:" line anywhere: everything reads None, not a crash ---
        bare = root / "agent-bbbb2222.jsonl"
        bare.write_text(_row(type="user", isSidechain=True, uuid="b-u0",
                             timestamp="2026-09-20T19:23:00Z",
                             message={"role": "user", "content": "synthetic role prompt"}) + "\n",
                        encoding="utf-8")
        meta2 = H.subagent_meta(bare)
        check_eq("no ticket line -> ticket is None", meta2["ticket"], None)
        check_eq("no dispatch line -> dispatch_id is None", meta2["dispatch_id"], None)

        # --- never raises: missing file, garbage content ---
        missing = H.subagent_meta(root / "does-not-exist.jsonl")
        check_eq("a missing transcript returns Nones, not an exception",
                 missing, {"role": None, "ticket": None, "dispatch_id": None,
                           "first_at": None, "last_at": None})
        garbage = root / "garbage.jsonl"
        garbage.write_text("not json at all\n{broken", encoding="utf-8")
        check_eq("unparseable lines never raise", H.subagent_meta(garbage)["role"], None)

        # --- story_subagent_transcripts: from state/cost/*.json's own transcript field ---
        project = root / "project"
        (project / "qa-factory" / "state" / "cost").mkdir(parents=True)
        main_transcript = root / "transcripts" / "sess-1.jsonl"
        sub_dir = main_transcript.parent / "sess-1" / "subagents"
        sub_dir.mkdir(parents=True)
        main_transcript.write_text("{}\n", encoding="utf-8")
        (sub_dir / "agent-c1.jsonl").write_text("{}\n", encoding="utf-8")
        (sub_dir / "agent-c2.jsonl").write_text("{}\n", encoding="utf-8")
        (project / "qa-factory" / "state" / "cost" / "sess-1.json").write_text(
            json.dumps({"session_id": "sess-1", "transcript": str(main_transcript)}),
            encoding="utf-8")
        # A second cost file with no transcript field (old format) contributes nothing.
        (project / "qa-factory" / "state" / "cost" / "sess-2.json").write_text(
            json.dumps({"session_id": "sess-2"}), encoding="utf-8")
        found = H.story_subagent_transcripts(project)
        check_eq("finds both subagent transcripts of the session with a transcript field",
                 sorted(p.name for p in found), ["agent-c1.jsonl", "agent-c2.jsonl"])

        # --- never raises: no state/cost/ directory at all ---
        empty_project = root / "empty-project"
        check_eq("no state/cost/ -> empty list, no exception",
                 H.story_subagent_transcripts(empty_project), [])
    finally:
        cleanup(root)
    finish("test_hooklib_subagent_meta")


if __name__ == "__main__":
    main()
