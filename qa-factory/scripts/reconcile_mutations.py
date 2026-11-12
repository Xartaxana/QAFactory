"""Inspect actual mutation bytes after interruption without restoring or overwriting files."""
import argparse
import hashlib
import json
from pathlib import Path
from event_store import atomic_json


def reconcile(task_root, known_roots):
    task = Path(task_root).resolve()
    roots = [Path(root).resolve() for root in known_roots]
    if not roots:
        raise ValueError("explicit owned repository roots required")
    state = json.loads((task / "state/controller.json").read_text(encoding="utf-8"))
    groups = []
    for identity, mutation in state.get("mutations", {}).items():
        files = []
        for raw in mutation.get("paths", []):
            path = Path(raw)
            if not path.is_absolute():
                if len(roots) != 1:
                    raise ValueError("multi-repo mutation paths must be absolute")
                path = roots[0] / path
            path = path.resolve()
            if not any(path.is_relative_to(root) for root in roots):
                raise ValueError("mutation path escapes declared repository roots")
            actual = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
            before = mutation.get("before_hashes", {}).get(raw)
            after = mutation.get("after_hashes", {}).get(raw)
            disposition = ("unchanged" if actual == before else "written" if after and actual == after
                           else "changed_without_checkpoint" if actual else "missing")
            files.append({"path": raw, "actual_sha256": actual, "status": disposition})
        groups.append({"id": identity, "recorded_status": mutation.get("status"), "files": files,
                       "needs_reconciliation": any(f["status"] in {"changed_without_checkpoint", "missing"} for f in files)})
    result = {"task_id": task.name, "revision": state.get("revision"), "groups": groups,
              "instruction": "Inspect changed bytes and resume only remaining work; execution/review are not inferred."}
    atomic_json(task / "work/mutation-reconciliation.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("task_root")
    parser.add_argument("--repo-root", action="append", required=True)
    args = parser.parse_args()
    print(json.dumps(reconcile(args.task_root, args.repo_root)))


if __name__ == "__main__":
    main()
