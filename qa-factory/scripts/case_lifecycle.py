"""Reviewable case retirement/migration; never erase historical case versions."""
import argparse
import json
from pathlib import Path

from event_store import content_hash, atomic_json


def validate_actions(actions):
    errors, ids = [], set()
    if not isinstance(actions, list):
        return ["lifecycle_actions must be an array"]
    for a in actions:
        if not isinstance(a, dict):
            errors.append("lifecycle action must be an object")
            continue
        aid = a.get("action_id")
        if not aid or aid in ids:
            errors.append("unique lifecycle action_id required")
        ids.add(aid)
        if a.get("kind") not in {"adapt", "migrate", "retire"}:
            errors.append(f"{aid}: invalid lifecycle kind")
        for field in ("reason", "case_refs", "authoritative_change_refs", "coverage_before", "coverage_after"):
            if not a.get(field):
                errors.append(f"{aid}: missing {field}")
        for field in ("test_refs", "replacement_refs", "shared_dependents", "proposed_code_changes"):
            if not isinstance(a.get(field), list):
                errors.append(f"{aid}: explicit {field} array required")
        if a.get("requirement_disposition") not in {"still_required", "replaced", "removed", "unresolved"}:
            errors.append(f"{aid}: requirement disposition required")
        if a.get("kind") == "retire" and a.get("requirement_disposition") != "removed":
            errors.append(f"{aid}: component disappearance is not requirement removal")
        if a.get("kind") == "retire" and not a.get("proposed_code_changes"):
            errors.append(f"{aid}: retirement requires reviewable proposed code removal")
        if a.get("kind") == "migrate" and not a.get("replacement_refs"):
            errors.append(f"{aid}: replacement required before migration")
        if a.get("proposed_tms_action") not in {"none", "update", "archive"}:
            errors.append(f"{aid}: TMS delete is forbidden; unsupported archive stays pending")
        for dep in a.get("shared_dependents") or []:
            if not isinstance(dep, dict) or dep.get("disposition") not in {"preserved", "migrated"} or not dep.get("evidence_ref"):
                errors.append(f"{aid}: shared dependent needs preserved/migrated evidence")
        for ref in a.get("case_refs") or []:
            if not isinstance(ref, dict) or not ref.get("case_id") or not ref.get("version"):
                errors.append(f"{aid}: exact case version required")
        for ref in a.get("test_refs") or []:
            if not isinstance(ref, dict) or not ref.get("path") or not ref.get("sha256"):
                errors.append(f"{aid}: test content hash required")
    return errors


def authorize(actions, decision, gate, source_revision):
    errors = validate_actions(actions)
    if (decision.get("status") != "approved" or decision.get("gate") != gate
            or decision.get("action") != "case_lifecycle" or decision.get("content_hash") != content_hash(actions)
            or decision.get("source_revision") != source_revision or not decision.get("authorization_source")):
        errors.append("exact current lifecycle decision required at Gate " + gate)
    return errors


def prepare_archive(action, decision, source_revision, capability, remote_revision):
    """Produce an ordinary conditional case proposal; adapter execution stays external_writes."""
    errors = authorize([action], decision, "B", source_revision)
    if errors:
        raise ValueError("; ".join(errors))
    if action.get("kind") != "retire" or action.get("proposed_tms_action") != "archive":
        raise ValueError("only approved retirement may archive")
    if not capability.get("archive") or not capability.get("conditional_updates"):
        return {"status": "pending", "reason": "adapter archive with conditional revision unavailable"}
    if not remote_revision or not action.get("external_id") or not decision.get("destination") or not decision.get("channel"):
        raise ValueError("archive binds destination/channel/remote ID/revision")
    payload = {"kind": "case", "action": "archive", "case_file": action.get("case_file"),
        "external_id": action["external_id"], "destination": decision["destination"],
        "channel": decision["channel"], "expected_remote_revision": remote_revision,
        "fields": {"archived": True, "reason": action["reason"]},
        "lifecycle_action": action, "lifecycle_decision_id": decision.get("id"),
        "lifecycle_key": content_hash({"action": action, "destination": decision["destination"],
                                       "remote_revision": remote_revision})}
    if not payload["case_file"]:
        raise ValueError("case_file required for reviewable archive proposal")
    return {"status": "ready_for_transport", "proposal": payload}


def main():
    p = argparse.ArgumentParser(__doc__)
    p.add_argument("input", type=Path)
    p.add_argument("--prepare-archive", action="store_true")
    p.add_argument("--output", type=Path)
    a = p.parse_args()
    data = json.loads(a.input.read_text(encoding="utf-8-sig"))
    result = prepare_archive(**data) if a.prepare_archive else {"errors": validate_actions(data)}
    if a.output:
        atomic_json(a.output, result.get("proposal", result))
    print(json.dumps(result, ensure_ascii=False))
    return int(bool(result.get("errors")))


if __name__ == "__main__":
    raise SystemExit(main())
