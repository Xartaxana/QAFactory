"""Append an idempotent S9 estimate record bound to current retro evidence."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from detector_verdict import compound
import event_store
from event_store import content_hash, hold_file_lock
import runtime_paths as RP


def _rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"estimation ledger line {number} is invalid JSON") from exc
        if not isinstance(row, dict):
            raise ValueError(f"estimation ledger line {number} must be an object")
        rows.append(row)
    return rows


def active_records(rows: list[dict], task: str) -> list[dict]:
    current = [row for row in rows if row.get("task") == task and row.get("schema_version") == 1]
    superseded = {str(value) for row in current for value in row.get("supersedes") or []}
    return [row for row in current if str(row.get("record_id") or "") not in superseded]


def task_binding(project_root: Path, task: str) -> dict:
    from hooklib import artifact_root
    if not task or task in {'.','..'} or '/' in task or '\\' in task:
        raise ValueError('task must be a single task identifier')
    task_root = artifact_root(root=project_root) / task
    retro = task_root / "retro.md"
    if not retro.is_file():
        raise ValueError("retro.md must exist before recording the final estimate")
    controller_path = task_root / "state" / "controller.json"
    try:
        controller = json.loads(controller_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError("current controller state is required") from exc
    except json.JSONDecodeError as exc:
        raise ValueError("current controller state is invalid JSON") from exc
    source_revision = controller.get("source_revision")
    if not isinstance(source_revision, str) or not source_revision:
        raise ValueError("controller source_revision is required")
    return {"task_root": task_root, "retro_path": retro,
            "retro_sha256": hashlib.sha256(retro.read_bytes()).hexdigest(),
            "task_revision": source_revision,
            "controller_revision_at_write": controller.get("revision")}


# The keys of a facts file (AR-13: the one list; the retro analyst's card tells it before the work, t-1355 N2-K7).
# `forecast` and `actual` are required objects; `drivers` is an optional array (absent = []).
FACTS_REQUIRED = ("forecast", "actual")
FACTS_OPTIONAL = ("drivers",)
FACTS_KEYS = FACTS_REQUIRED + FACTS_OPTIONAL


def facts_problems(facts) -> list[str]:
    """Every problem of a facts file, in key order; `[]` when it is acceptable. A non-object is told alone (nothing
    in it can be read); an absent `drivers` is legal, an absent `forecast` or `actual` is not."""
    if not isinstance(facts, dict):
        return ["estimate facts must be an object"]
    problems = [f"estimate facts {key} must be an object" for key in FACTS_REQUIRED if not isinstance(facts.get(key), dict)]
    if not isinstance(facts.get("drivers", []), list):
        problems.append("estimate facts drivers must be an array")
    return problems


def append_record(project_root: Path, task: str, facts: dict) -> tuple[str, dict]:
    problems = facts_problems(facts)
    if problems:      # positional: before task_binding, the lock and the ledger directory (nothing is read or made for a bad file)
        raise ValueError(compound(problems))
    binding = task_binding(project_root, task)
    ledger = RP.record(project_root, "estimation-ledger.jsonl")
    ledger.parent.mkdir(parents=True, exist_ok=True)
    # The lock is machine-local: it lives in `state/` (ignored), not beside the tracked ledger.
    lock_path = RP.state_file(project_root, "estimation-ledger.lock")   # the helper makes the folder
    # A lock held past the wait raises the helper's LockBusy / LockBroken (an OSError naming the lock file and the
    # holder); `main` prints it as `invalid_estimate`. The ledger is never read or written unlocked.
    with hold_file_lock(lock_path, event_store.SHORT_RMW_LOCK_WAIT_S, purpose="estimation ledger", record_holder=True):
        rows = _rows(ledger)
        active = active_records(rows, task)
        material = {"schema_version": 1, "task": task,
                    "task_revision": binding["task_revision"],
                    "retro_sha256": binding["retro_sha256"], "facts": facts}
        record_id = content_hash(material)
        existing = next((row for row in rows if row.get("record_id") == record_id), None)
        if existing:
            return "reused", existing
        record = {**material, "record_id": record_id,
                  "forecast": facts["forecast"], "actual": facts["actual"],
                  "drivers": facts.get("drivers", []),
                  "controller_revision_at_write": binding["controller_revision_at_write"],
                  "retro_path": os.path.relpath(binding['retro_path'],project_root).replace('\\','/'),
                  "supersedes": sorted(str(row["record_id"]) for row in active if row.get("record_id")),
                  "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        with ledger.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
            stream.flush(); os.fsync(stream.fileno())
        return "appended", record


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--task", required=True)
    parser.add_argument("--facts", type=Path, required=True,
                        help="JSON object containing the computed forecast/fact fields")
    args = parser.parse_args()
    try:
        action, record = append_record(args.project_root.resolve(), args.task,
                                       json.loads(args.facts.read_text(encoding="utf-8")))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "invalid_estimate", "error": str(exc)}))
        raise SystemExit(2)
    print(json.dumps({"status": action, "record": record}, ensure_ascii=False))


if __name__ == "__main__":
    main()
