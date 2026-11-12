"""A10 uses exact-revision, repository-qualified scheduler reuse receipts."""
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import metrics_projection  # noqa: E402
from metrics_projection import project  # noqa: E402

# project() takes no clock: it reads datetime.now() once and windows every attempt to the 30 days
# before it, and the fixture below is stamped 2026-09-18, so the wall clock turned this red from
# 2026-10-18 (B-396). Patched in as the module's `datetime`, FixedClock answers now() with PINNED_NOW
# (timezone-aware UTC, three days after the stamp) and leaves fromisoformat/fromtimestamp/min alone.
PINNED_NOW = datetime(2026, 9, 21, tzinfo=timezone.utc)


class FixedClock(datetime):
    @classmethod
    def now(cls, tz=None):
        return PINNED_NOW if tz is None else PINNED_NOW.astimezone(tz)


def metric(snapshot, key):
    return next(row for row in snapshot["metrics"] if row["id"] == key)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="qa-execution-metrics-") as td:
        root = Path(td)
        task_root = root / "qa-factory" / "artifacts" / "T-1"
        (task_root / "work" / "run-blocks").mkdir(parents=True)
        (task_root / "work" / "run-blocks" / "attempt.json").write_text(json.dumps({
            "block_id": "attempt", "purpose": "initial", "profile_id": "p",
            "attempt_started_at": "2026-09-18T00:00:00Z", "attempt_ended_at": "2026-09-18T00:00:01Z",
            "results": [{"instance_id": "other", "repo_id": "repo-b", "status": "failed",
                         "input_fingerprint": "fp"}]}), encoding="utf-8")
        (task_root / "pipeline.json").write_text("{}", encoding="utf-8")
        receipts = root / "qa-factory" / "state" / "scheduler-receipts"
        receipts.mkdir(parents=True)
        receipt = {"schema_version": 1, "source_revision": "rev-current", "groups": [
            {"status": "reused", "task": "T-1", "revision": "rev-current",
             "qualified_selected_ids": ["repo-a::same"]},
            {"status": "completed", "task": "T-1", "revision": "rev-current",
             "qualified_selected_ids": ["repo-b::other"]},
            {"status": "reused", "task": "T-1", "revision": "rev-stale",
             "qualified_selected_ids": ["repo-b::same"]}]}
        (receipts / "reuse.json").write_text(json.dumps(receipt), encoding="utf-8")
        task = {"task": "T-1", "artifact_path": str(task_root), "archived": False,
                "manifest_entries": [
                    {"instance_id": "same", "repo_id": "repo-a", "case": "A"},
                    {"instance_id": "other", "repo_id": "repo-b", "case": "B"}],
                "report": {"source_revision": "rev-current", "current_results": [
                    {"instance_id": "same", "repo_id": "repo-a", "profile_id": "p", "status": "passed"},
                    {"instance_id": "other", "repo_id": "repo-b", "profile_id": "p", "status": "passed"}]}}
        with mock.patch.object(metrics_projection, "datetime", FixedClock):
            snapshot = project(root, [task], [], [], [], [], {"metrics": {}})
        a10 = metric(snapshot, "A10")
        a05, a09 = metric(snapshot, "A05"), metric(snapshot, "A09")
        # A09: mark_duplicate_executions now stamps every attempt, so with a single,
        # first-ever executed attempt for its identity there is nothing to be a duplicate OF —
        # 0 of 1, "available", not the old permanent "unavailable".
        ok = (a10["numerator"] == 1 and a10["denominator"] == 2 and a10["value"] == 50
              and a05["status"] == "unavailable" and "not recorded" in a05["reason"]
              and a09["status"] == "available" and a09["numerator"] == 0 and a09["denominator"] == 1)
        print(("PASS" if ok else "FAIL") + " exact revision/repository scheduler reuse maps to A10 only")
        return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
