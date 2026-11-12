"""Retirement transport: exact B authorization, CAS, idempotency and unknown outcomes."""
import json
import os
import sys
from pathlib import Path

from harness import check, check_eq, check_in, cleanup, finish, run_script, temp_project

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from case_lifecycle import prepare_archive
from event_store import content_hash


def lifecycle_action(aid, external_id, case_file):
    return {"action_id": aid, "kind": "retire", "reason": "owner removed requirement",
            "case_refs": [{"case_id": "TC-1", "version": "cv1"}],
            "test_refs": [{"path": "tests/old.py", "sha256": "test-hash"}],
            "authoritative_change_refs": ["decision:R-1@2"], "requirement_disposition": "removed",
            "replacement_refs": [], "shared_dependents": [{"disposition": "preserved", "evidence_ref": "deps"}],
            "coverage_before": ["O-1"], "coverage_after": ["removed:R-1"],
            "proposed_code_changes": [{"path": "tests/old.py", "change": "delete"}],
            "proposed_tms_action": "archive", "decision_receipt_ref": "B",
            "external_id": external_id, "case_file": case_file}


def decision(did, action):
    return {"id": did, "status": "approved", "gate": "B", "action": "case_lifecycle",
            "content_hash": content_hash([action]), "source_revision": "src",
            "authorization_source": "owner at Gate B", "destination": "suite", "channel": "xray"}


def run(root):
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(root))
    return run_script("external_writes.py", "QA-1", "--phase", "after-b", "--yes", env=env)


def main():
    root = temp_project("qa-lifecycle-transport-")
    try:
        qf = root / "qa-factory"
        art = qf / "artifacts/QA-1"
        proposals = art / "work/proposals"; proposals.mkdir(parents=True)
        cases = qf / "test-cases"; cases.mkdir()
        case = cases / "TC-1.md"; case.write_text("# immutable local case\n", encoding="utf-8")
        original_case = case.read_bytes()
        calls = root / "calls.log"
        stub = root / "adapter.py"
        stub.write_text(
            "import json,sys\n"
            "p=json.loads(sys.argv[1])\n"
            f"open({json.dumps(str(calls))},'a',encoding='utf-8').write(p['external_id']+'\\n')\n"
            "print('{}' if p['external_id']=='EXT-U' else json.dumps({'external_id':p['external_id'],'remote_revision':'r2'}))\n",
            encoding="utf-8")
        config = json.loads((qf / "config.json").read_text(encoding="utf-8"))
        config["external_writes"] = {"bugs": "markdown", "cases": "xray",
            "write_scopes": ["archive_case"], "commands": {"xray": [sys.executable, str(stub)]},
            "channels": {"xray": {"archive": True, "conditional_updates": True}}}
        (qf / "config.json").write_text(json.dumps(config), encoding="utf-8")

        ok_action = lifecycle_action("LC-1", "EXT-1", "test-cases/TC-1.md")
        ok_decision = decision("B-LC-1", ok_action)
        ok = prepare_archive(ok_action, ok_decision, "src",
            {"archive": True, "conditional_updates": True}, "r1")["proposal"]
        ok_path = proposals / "case-archive.json"; ok_path.write_text(json.dumps(ok), encoding="utf-8")
        controller = {"source_revision": "src", "decisions": {ok_decision["id"]: ok_decision}}
        state = art / "state"; state.mkdir()
        (state / "controller.json").write_text(json.dumps(controller), encoding="utf-8")
        (art / "pipeline.json").write_text(json.dumps({"gates": {}}), encoding="utf-8")

        before = run(root)
        check_eq("archive before Gate B is rejected", before.returncode, 2)
        check("rejected archive never invokes adapter", not calls.exists())
        check("rejected archive does not mutate local case", case.read_bytes() == original_case)

        (art / "pipeline.json").write_text(json.dumps({"gates": {"B": {"status": "approved"}}}), encoding="utf-8")
        first = run(root)
        check_eq("exact after-B archive succeeds", first.returncode, 0)
        check_in("archive reports performed", "OK", first.stdout)
        check_eq("adapter called exactly once", calls.read_text(encoding="utf-8").splitlines(), ["EXT-1"])
        check("successful archive preserves local case bytes", case.read_bytes() == original_case)
        second = run(root)
        check_in("repeat archive is idempotently skipped", "SKIP", second.stdout)
        check_eq("repeat does not call adapter", calls.read_text(encoding="utf-8").splitlines(), ["EXT-1"])

        unknown_action = lifecycle_action("LC-U", "EXT-U", "test-cases/TC-1.md")
        unknown_decision = decision("B-LC-U", unknown_action)
        controller["decisions"][unknown_decision["id"]] = unknown_decision
        (state / "controller.json").write_text(json.dumps(controller), encoding="utf-8")
        unknown = prepare_archive(unknown_action, unknown_decision, "src",
            {"archive": True, "conditional_updates": True}, "r1")["proposal"]
        unknown_path = proposals / "case-unknown.json"; unknown_path.write_text(json.dumps(unknown), encoding="utf-8")
        uncertain = run(root)
        check_eq("missing archive revision is an unknown outcome", uncertain.returncode, 1)
        check_in("unknown outcome requires reconciliation", "outcome unknown", uncertain.stdout)
        calls_after_unknown = calls.read_text(encoding="utf-8").splitlines()
        retry = run(root)
        check_eq("unknown archive is not blindly retried", retry.returncode, 1)
        check_in("second attempt names prior unknown outcome", "unknown prior transport outcome", retry.stdout)
        check_eq("unknown outcome invokes adapter only once", calls.read_text(encoding="utf-8").splitlines(),
                 calls_after_unknown)
        check("unknown outcome also preserves local case", case.read_bytes() == original_case)
    finally:
        cleanup(root)
    finish("test_lifecycle_transport")


if __name__ == "__main__":
    main()
