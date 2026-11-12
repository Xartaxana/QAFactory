"""F01 source inventory blocks the legacy S1 completion and scout exit boundaries."""
import json
import sys

from harness import PLUGIN_ROOT, check, check_eq, cleanup, finish, temp_project

sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))
import exit_gate  # noqa: E402
import hooklib  # noqa: E402
import stage_done  # noqa: E402


def main():
    root = temp_project("qa-source-stage-")
    task = "APP-1"
    art = root / "qa-factory" / "artifacts" / task
    work = art / "work"
    work.mkdir(parents=True, exist_ok=True)
    pipeline = {"ticket": task, "source_inventory_required": True,
                "stages": {"S0": {"status": "done"}, "S1": {"status": "running"}}, "gates": {}}
    (art / "pipeline.json").write_text(json.dumps(pipeline), encoding="utf-8")
    old_root = hooklib._PROJECT_ROOT_CACHE
    old_artifact_root = exit_gate.artifact_root
    hooklib._PROJECT_ROOT_CACHE = root
    exit_gate.artifact_root = lambda: root / "qa-factory" / "artifacts"
    try:
        check_eq("new Jira task without inventory cannot finish S1",
                 stage_done.run(task, "S1", "done", "qa-scout", "done", True),
                 stage_done.EXIT_BAD_ARGS)
        pending = {"schema_version": 1, "sources": [{
            "source_id": "SRC-pending", "canonical_ref": "https://jira/browse/APP-2",
            "relation": "referenced", "relevance": "pending", "relevance_reason": "mentioned",
            "assessment_ref": None, "discovered_from": "SRC-task", "relation_evidence": "work/source.txt",
            "required": True, "status": "pending", "revision": None, "content_hash": None,
            "snapshot_ref": None, "fetched_at": "2026-09-19T00:00:00Z", "exclusion_or_error": None,
            "materials": {"comments": {"status": "unknown", "count": None},
                          "attachments": {"status": "unknown", "count": None, "items": []}}
        }]}
        (work / "source-inventory.json").write_text(json.dumps(pending), encoding="utf-8")
        check_eq("pending referenced source cannot finish S1",
                 stage_done.run(task, "S1", "done", "qa-scout", "done", True),
                 stage_done.EXIT_BAD_ARGS)
        check("scout exit gate reports pending inventory",
              any("remain pending" in e for e in exit_gate.scoped_errors("qa-scout", task)))
        unavailable = pending
        unavailable["sources"][0].update(relevance="unknown", relevance_reason="403 during assessment",
                                           status="unavailable", exclusion_or_error="HTTP 403")
        (work / "source-inventory.json").write_text(json.dumps(unavailable), encoding="utf-8")
        check_eq("explicit required unavailable source blocks handoff",
                 stage_done.run(task, "S1", "done", "qa-scout", "done with source gap", True), stage_done.EXIT_BAD_ARGS)

        # --- the person's word. TP1-15045 halted a third time on gaps its owner had
        # already accepted: nothing below this line existed.
        import source_inventory as SI
        from source_preflight import check_source_inventory
        inventory_path = work / "source-inventory.json"
        check("every source assessed and nobody asked yet = a handoff to the person",
              check_source_inventory(art, pipeline)["awaiting_review"])
        check("the scout may stop there", exit_gate.awaiting_source_review("qa-scout", task))
        check_eq("but S1 still cannot close",
                 stage_done.run(task, "S1", "done", "qa-scout", "done", True), stage_done.EXIT_BAD_ARGS)
        try:
            SI.record_gap_acceptance(inventory_path, ["SRC-pending"], "  ")
            refused = False
        except ValueError:
            refused = True
        check("a gap is never accepted without the person's words", refused)
        SI.record_source_review(inventory_path, "agreed with the list")
        result = check_source_inventory(art, pipeline)
        check("reviewed but unavailable still blocks a silent pass",
              any("not accepted by a person" in e for e in result["errors"]))
        SI.record_gap_acceptance(inventory_path, ["SRC-pending"], "go on without APP-2, it is behind a 403")
        result = check_source_inventory(art, pipeline)
        check_eq("the person's word removes the block", result["errors"], [])
        check("and the gap stays on the record with their words",
              any("go on without APP-2" in g for g in result["gaps"]))
        check_eq("the scout's gate no longer reports the source",
                 [e for e in exit_gate.scoped_errors("qa-scout", task) if "source-inventory" in e], [])
        try:
            SI.record_gap_acceptance(inventory_path, ["SRC-pending"], "again")
            SI.record_gap_acceptance(inventory_path, ["SRC-nope"], "x")
            unknown_refused = False
        except ValueError:
            unknown_refused = True
        check("an unknown source id is refused", unknown_refused)
        rows = SI.review_rows(SI.load_inventory(inventory_path))
        check_eq("the review names the ticket, not the hash", rows[0]["key"], "APP-2")
        check("and shows the open point as accepted", rows[0]["gap_accepted"] and rows[0]["open_points"])

        # --- any other block of a stage passes by `waiver.py --stage` the same way
        import waiver
        blocked = dict(pipeline)
        errors = ["context-manifest.json: acceptance_criteria is required"]
        check_eq("without a word the block stands", waiver.split_overridden(errors, blocked, "S1")[0], errors)
        waiver.apply_stage_override(blocked, "S1", "acceptance_criteria", "the ticket has no AC, go on", "T1")
        check_eq("with a word it does not", waiver.split_overridden(errors, blocked, "S1")[0], [])

        # --- a role cannot record the person's word for them
        import guard_pre_tool as G
        def refused_for(event):
            try:
                G.human_word_check(event, {})
                return False
            except SystemExit as exc:
                return exc.code == 2
        accept_cmd = {"command": "python scripts/ticket_adapter.py accept-gap --output x --all-unavailable --words ok"}
        check("a role is refused accept-gap",
              refused_for({"tool_name": "Bash", "agent_type": "qa-factory:qa-scout", "tool_input": accept_cmd}))
        check("a role is refused a stage override",
              refused_for({"tool_name": "Bash", "transcript_path": "C:/x/subagents/a.jsonl",
                           "tool_input": {"command": "python waiver.py --task T --stage S1 --block * --decision ok"}}))
        check("the orchestrator is not",
              not refused_for({"tool_name": "Bash", "tool_input": accept_cmd}))
        check("and a role may still print the review",
              not refused_for({"tool_name": "Bash", "agent_type": "qa-scout",
                               "tool_input": {"command": "python ticket_adapter.py review --output x"}}))
    finally:
        hooklib._PROJECT_ROOT_CACHE = old_root
        exit_gate.artifact_root = old_artifact_root
        cleanup(root)
    finish("test_source_stage_integration")


if __name__ == "__main__":
    main()
