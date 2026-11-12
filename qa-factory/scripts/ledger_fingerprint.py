"""Deterministic freshness binding for the four inputs that produce the delivery ledger."""
import hashlib
from pathlib import Path

import contract as C
from event_store import content_hash

INPUTS = ("test-plan.json", "run-report.json", "automation-manifest.json", "triage.json")


def snapshot(task_root):
    task = Path(task_root).resolve()
    files = {}
    for name in INPUTS:
        path = C.artifact(task, name)
        try:
            relative = path.resolve().relative_to(task).as_posix()
        except ValueError:
            relative = name
        files[name] = {"path": relative, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()} \
            if path.is_file() else {"path": relative, "missing": True}
    return {"schema_version": 1, "files": files, "fingerprint": content_hash(files)}
