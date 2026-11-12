"""Plan and explicitly apply an active task's coverage contract v1 -> v2 migration.

Dry-run is the default. Historical tasks without active controller state are never rewritten.
The migration creates an immutable backup, writes unresolved obligations without inventing
semantic proof, and records one controller event that invalidates old Gate A.
"""
import argparse
import json
import os
from pathlib import Path
import uuid

from controller import Controller
from coverage_contract import validate_obligations
from event_store import atomic_json, content_hash


def _plan_path(root):
    return Path(root).resolve() / "work" / "test-plan.json"


def _atomic_bytes(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        temporary.write_bytes(value)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _read_plan(root):
    path = _plan_path(root)
    if not path.is_file():
        raise ValueError("coverage migration requires work/test-plan.json")
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    rows = value.get("rows") if isinstance(value, dict) else value
    if not isinstance(rows, list):
        raise ValueError("structured test plan rows must be a list")
    return path, value, rows


def _version(rows):
    versions = {row.get("schema_version", 1) for row in rows if isinstance(row, dict)}
    if not versions:
        return 1
    if not versions.issubset({1, 2}) or len(versions) != 1:
        raise ValueError("unknown or mixed coverage schema versions; migration fails closed")
    return versions.pop()


def _migrated_row(row, source_revision, migration_id):
    upgraded = dict(row)
    upgraded["schema_version"] = 2
    refs = row.get("coverage_refs") or row.get("risk_source_refs") or ["unmapped"]
    obligation = {
        "obligation_id": f"MIG-{row.get('id', 'ROW')}",
        "requirement_refs": [{"ref": str(ref), "revision": "unknown"} for ref in refs],
        "behavior": row.get("what_we_verify") or f"Reassess migrated row {row.get('id', 'unknown')}",
        "oracle_source_ref": "",
        "oracle_status": "unresolved",
        "applicable_scenarios": [{"kind": "unknown", "rationale": "legacy design requires reassessment"}],
        "observation_boundary": "unresolved during migration",
        "completion_condition": "unresolved during migration",
        "coverage_links": [],
        "decision": "unresolved",
        "remaining_gap": "legacy assessment unavailable; review only affected current scope",
        "planned_check_refs": [],
        "execution_scope": "current_task",
        "sufficiency_review": {
            "author_dispatch_id": migration_id,
            "input_hash": content_hash(row),
            "rationale": "mechanical migration preserved history and made missing assessment explicit",
        },
    }
    upgraded["coverage_obligations"] = [obligation]
    return upgraded


def plan(task_root):
    root = Path(task_root).resolve()
    path, document, rows = _read_plan(root)
    version = _version(rows)
    events = Controller(root).store.read() if (root / "state/events.jsonl").exists() else []
    if not events:
        return {"status": "historical_unchanged", "from_version": version,
                "reason": "no active controller lifecycle; historical artifacts remain byte-for-byte unchanged"}
    state = Controller(root).state()
    negotiated = state.get("coverage_contract_version")
    if negotiated not in {1, 2}:
        raise ValueError("unknown negotiated coverage contract version")
    if version == 2 and negotiated == 2:
        return {"status": "already_migrated", "from_version": 2, "to_version": 2,
                "plan_content_hash": content_hash(document)}
    if version != 1 or negotiated != 1:
        raise ValueError("plan/controller coverage versions disagree; migration fails closed")
    migration_id = "coverage-v1-v2-" + content_hash(document)[:12]
    migrated = dict(document) if isinstance(document, dict) else {}
    migrated["rows"] = [_migrated_row(row, state["source_revision"], migration_id) for row in rows]
    errors = validate_obligations(migrated["rows"], require_v2=True)
    if errors:
        raise ValueError("generated migration invalid: " + "; ".join(errors))
    backup = root / "state" / "coverage-migrations" / migration_id / "test-plan.v1.json"
    return {"status": "planned", "migration_id": migration_id, "from_version": 1, "to_version": 2,
            "source_revision": state["source_revision"], "source_plan_hash": content_hash(document),
            "plan_content_hash": content_hash(migrated), "backup_ref": str(backup.relative_to(root)),
            "plan_path": str(path), "document": migrated}


def migrate(task_root, wait_seconds=0.0):
    """`wait_seconds`: how long the migration event waits for an in-flight story writer. Only
    `main` (the command line) chooses it; every other caller keeps 0 and fails at once."""
    root = Path(task_root).resolve()
    report = plan(root)
    if report["status"] in {"historical_unchanged", "already_migrated"}:
        return report
    path = _plan_path(root)
    current = json.loads(path.read_text(encoding="utf-8-sig"))
    if content_hash(current) != report["source_plan_hash"]:
        raise ValueError("coverage plan changed after migration planning")
    backup = root / report["backup_ref"]
    if backup.exists():
        if content_hash(json.loads(backup.read_text(encoding="utf-8-sig"))) != report["source_plan_hash"]:
            raise ValueError("coverage migration backup conflict")
    else:
        _atomic_bytes(backup, path.read_bytes())
    atomic_json(path, report["document"])
    Controller(root, wait_seconds=wait_seconds).apply("coverage_migration", {
        "migration_id": report["migration_id"], "from_version": 1, "to_version": 2,
        "source_revision": report["source_revision"], "plan_content_hash": report["plan_content_hash"],
        "backup_ref": report["backup_ref"],
        "dry_run": {"plan_content_hash": report["plan_content_hash"], "valid": True},
        "idempotency_key": report["migration_id"],
    })
    result = dict(report)
    result.pop("document", None)
    result["status"] = "completed"
    return result


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("task_root")
    parser.add_argument("--apply", action="store_true", help="write backup/plan and record migration event")
    args = parser.parse_args()
    import event_store
    result = (migrate(args.task_root, wait_seconds=event_store.LIFECYCLE_WAIT_SECONDS)
              if args.apply else plan(args.task_root))
    printable = dict(result)
    printable.pop("document", None)
    print(json.dumps(printable, ensure_ascii=False))


if __name__ == "__main__":
    main()
