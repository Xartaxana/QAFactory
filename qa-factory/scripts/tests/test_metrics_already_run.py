"""A10 and `already_run`: a completed key that did not pass is a result answered without a launch.

Before the run budget the scheduler labelled every completed key `reused`. It now says `already_run`
for one that ended any other way, and the metrics projection must not lose the instances behind it:
they are classified as reuse (so `reuse_classification_complete` stays true) exactly as `reused` ones
are. A group that was refused (`run_refused`) ran nothing and answered nothing: it stays unclassified.
"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from harness import check, check_eq, finish  # noqa: E402
from metrics_projection import project  # noqa: E402


def metric(snapshot, key):
    return next(row for row in snapshot["metrics"] if row["id"] == key)


def snapshot_of(groups):
    with tempfile.TemporaryDirectory(prefix="qa-metrics-already-run-") as td:
        root = Path(td)
        task_root = root / "qa-factory" / "artifacts" / "T-1"
        (task_root / "work" / "run-blocks").mkdir(parents=True)
        (task_root / "pipeline.json").write_text("{}", encoding="utf-8")
        receipts = root / "qa-factory" / "state" / "scheduler-receipts"
        receipts.mkdir(parents=True)
        (receipts / "r.json").write_text(json.dumps({"schema_version": 1, "source_revision": "rev",
                                                      "groups": groups}), encoding="utf-8")
        task = {"task": "T-1", "artifact_path": str(task_root), "archived": False,
                "manifest_entries": [{"instance_id": "green", "repo_id": "r", "case": "A"},
                                     {"instance_id": "red", "repo_id": "r", "case": "B"}],
                "report": {"source_revision": "rev", "current_results": [
                    {"instance_id": "green", "repo_id": "r", "profile_id": "p", "status": "passed"},
                    {"instance_id": "red", "repo_id": "r", "profile_id": "p", "status": "failed"}]}}
        return project(root, [task], [], [], [], [], {"metrics": {}})


def group(status, *ids):
    return {"status": status, "task": "T-1", "revision": "rev",
            "qualified_selected_ids": [f"r::{i}" for i in ids]}


def main() -> None:
    both = snapshot_of([group("reused", "green"), group("already_run", "red")])
    a10 = metric(both, "A10")
    check_eq("A10 counts a `reused` and an `already_run` instance as reused (2 of 2)",
             (a10["numerator"], a10["denominator"]), (2, 2))
    check("and every selected instance is classified, so the ratio is stated", a10["status"] == "available")
    refused = snapshot_of([group("reused", "green"), group("run_refused", "red")])
    check("a refused group ran nothing and answered nothing: its instance stays unclassified",
          metric(refused, "A10")["status"] != "available")
    finish("test_metrics_already_run")


if __name__ == "__main__":
    main()
