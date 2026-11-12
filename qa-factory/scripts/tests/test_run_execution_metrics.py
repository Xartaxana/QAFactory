"""test-run volume and duplicate-execution metrics, computed from work/run-blocks/*.json.

metrics_projection.mark_duplicate_executions feeds A09 ("Duplicate execution", the dashboard's
existing run widget) and A07 ("Run duration and volume") gains a jobs_by_window breakdown, both
reused rows/columns, no new widget. retro_numbers.run_block_metrics computes the same
"runs per S5 window" + "share of unchanged-green executions" for one story's S9 retro.
"""
import json
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import check, check_eq, finish
import metrics_projection as M
import retro_numbers as R

# The clock these tests read, pinned: compute() windows every job and attempt to the 30 days before
# `now`, and the fixtures below are stamped in September 2026, so an unpinned compute() (the default
# is the wall clock) turned them red from 2026-10-20 (B-396). One day after the newest fixture stamp,
# timezone-aware UTC like test_metrics_contract's values().
PINNED_NOW = datetime(2026, 9, 21, tzinfo=timezone.utc)


class FixedClock(datetime):
    """metrics_projection.project() takes no clock: it reads datetime.now() once and hands it to
    compute(). Patched in as the module's `datetime`, this answers now() with PINNED_NOW and leaves
    fromisoformat/fromtimestamp/min (the module's other uses) to datetime itself."""
    @classmethod
    def now(cls, tz=None):
        return PINNED_NOW if tz is None else PINNED_NOW.astimezone(tz)


def test_mark_duplicate_executions_flags_only_a_repeat_of_an_unchanged_green_test():
    attempts = [
        {"task": "T-1", "instance_id": "TC-1", "repo_id": "r", "profile_id": "p",
         "status": "passed", "fingerprint": "fp-1", "purpose": "initial", "origin": "executed",
         "started_at": "2026-09-20T10:00:00Z"},
        # Same identity, SAME fingerprint, already passing -> duplicate.
        {"task": "T-1", "instance_id": "TC-1", "repo_id": "r", "profile_id": "p",
         "status": "passed", "fingerprint": "fp-1", "purpose": "initial", "origin": "executed",
         "started_at": "2026-09-20T10:05:00Z"},
        # A repair changed the fingerprint -> not a duplicate, even though it also passes.
        {"task": "T-1", "instance_id": "TC-1", "repo_id": "r", "profile_id": "p",
         "status": "passed", "fingerprint": "fp-2", "purpose": "repair_verify", "origin": "executed",
         "started_at": "2026-09-20T10:10:00Z"},
        # A DIFFERENT instance's first-ever attempt is never a duplicate.
        {"task": "T-1", "instance_id": "TC-2", "repo_id": "r", "profile_id": "p",
         "status": "failed", "fingerprint": "fp-3", "purpose": "initial", "origin": "executed",
         "started_at": "2026-09-20T10:02:00Z"},
        # An imported result is never counted, even re-running the same green fingerprint.
        {"task": "T-1", "instance_id": "TC-1", "repo_id": "r", "profile_id": "p",
         "status": "passed", "fingerprint": "fp-2", "purpose": "initial", "origin": "imported",
         "started_at": "2026-09-20T10:15:00Z"},
    ]
    M.mark_duplicate_executions(attempts)
    by_start = {a["started_at"]: a["duplicate_execution"] for a in attempts}
    check_eq("first execution of an identity is never a duplicate",
             by_start["2026-09-20T10:00:00Z"], False)
    check_eq("re-running the same green fingerprint IS a duplicate",
             by_start["2026-09-20T10:05:00Z"], True)
    check_eq("a fingerprint change (repair) clears duplicate status",
             by_start["2026-09-20T10:10:00Z"], False)
    check_eq("a different instance's first attempt is not a duplicate",
             by_start["2026-09-20T10:02:00Z"], False)
    check_eq("an imported row is never flagged duplicate",
             by_start["2026-09-20T10:15:00Z"], False)
    check("every attempt gets the field (compute()'s completeness gate)",
          all("duplicate_execution" in a for a in attempts))


def test_a09_becomes_available_once_duplicate_execution_is_populated():
    attempts = [
        {"task": "T-1", "instance_id": "TC-1", "repo_id": "r", "profile_id": "p",
         "status": "passed", "fingerprint": "fp-1", "purpose": "initial", "origin": "executed",
         "started_at": "2026-09-20T10:00:00Z"},
        {"task": "T-1", "instance_id": "TC-1", "repo_id": "r", "profile_id": "p",
         "status": "passed", "fingerprint": "fp-1", "purpose": "initial", "origin": "executed",
         "started_at": "2026-09-20T10:05:00Z"},
    ]
    M.mark_duplicate_executions(attempts)
    data = {"attempts": attempts, "jobs": [], "attempt_history_known": True, "window_days": 30}
    metrics = {m["id"]: m for m in M.compute(data, PINNED_NOW)}
    check_eq("A09 is available once every attempt carries duplicate_execution",
             metrics["A09"]["status"], "available")
    check_eq("A09 numerator counts the one duplicate execution",
             metrics["A09"]["numerator"], 1)
    check_eq("A09 denominator is every executed local attempt", metrics["A09"]["denominator"], 2)


def test_a07_gains_jobs_by_window_without_a_new_widget():
    jobs = [{"start": "2026-09-20T10:00:00Z", "end": "2026-09-20T10:01:00Z", "id": "b1", "window": 1},
            {"start": "2026-09-20T10:05:00Z", "end": "2026-09-20T10:06:00Z", "id": "b2", "window": 1},
            {"start": "2026-09-20T10:10:00Z", "end": "2026-09-20T10:11:00Z", "id": "b3", "window": 2},
            {"start": "2026-09-20T10:15:00Z", "end": "2026-09-20T10:16:00Z", "id": "b4", "window": None}]
    data = {"attempts": [], "jobs": jobs, "attempt_history_known": True, "window_days": 30}
    metrics = {m["id"]: m for m in M.compute(data, PINNED_NOW)}
    a07 = metrics["A07"]
    check_eq("A07 stays 'available' (an existing, reused widget)", a07["status"], "available")
    check_eq("jobs_by_window buckets by the controller's dispatch.window",
             a07["value"]["jobs_by_window"], {"window 1": 2, "window 2": 1, "unscoped": 1})
    check_eq("the existing jobs count is untouched", a07["value"]["jobs"], 4)


def test_the_30_day_window_edge_is_pinned_by_the_clock_not_the_calendar():
    # window = [midnight(now) - 29 days, now]: the production semantics, pinned here so a change to the
    # window fails this test instead of waiting for the calendar to move a fixture out of it.
    start = PINNED_NOW.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=29)

    def job(job_id, at):
        stamp = at.isoformat().replace("+00:00", "Z")
        return {"start": stamp, "end": stamp, "id": job_id, "window": 1}
    jobs = [job("on-start", start), job("one-second-before", start - timedelta(seconds=1)),
            job("one-second-after", start + timedelta(seconds=1))]
    data = {"attempts": [], "jobs": jobs, "attempt_history_known": True, "window_days": 30}
    a07 = {m["id"]: m for m in M.compute(data, PINNED_NOW)}["A07"]
    check_eq("the window opens at midnight(now) - 29 days", start.isoformat(), "2026-08-23T00:00:00+00:00")
    check_eq("a stamp exactly on the start is counted, one second before it is not",
             a07["value"]["jobs"], 2)
    check_eq("the counted two are the one on the start and the one after it",
             a07["value"]["jobs_by_window"], {"window 1": 2})


def test_project_wires_dispatch_window_into_run_block_jobs():
    with tempfile.TemporaryDirectory(prefix="qa-run-exec-metrics-") as td:
        root = Path(td)
        task_root = root / "qa-factory" / "artifacts" / "T-1"
        (task_root / "work" / "run-blocks").mkdir(parents=True)
        (task_root / "work" / "run-blocks" / "attempt.json").write_text(json.dumps({
            "block_id": "attempt", "purpose": "initial", "profile_id": "p",
            "dispatch_id": "S5-qa-automator-1",
            "attempt_started_at": "2026-09-18T00:00:00Z", "attempt_ended_at": "2026-09-18T00:00:01Z",
            "results": [{"instance_id": "TC-1", "repo_id": "r", "status": "passed",
                         "input_fingerprint": "fp-1"}]}), encoding="utf-8")
        (task_root / "pipeline.json").write_text(json.dumps({
            "lifecycle": {"dispatches": {"S5-qa-automator-1": {"stage": "S5", "status": "accepted",
                                                                "window": 3}}}}), encoding="utf-8")
        task = {"task": "T-1", "artifact_path": str(task_root), "archived": False,
                "manifest_entries": [], "report": {},
                "lifecycle": {"dispatches": {"S5-qa-automator-1": {"stage": "S5", "status": "accepted",
                                                                    "window": 3}}}}
        with mock.patch.object(M, "datetime", FixedClock):
            snapshot = M.project(root, [task], [], [], [], [], {"metrics": {}})
        a07 = next(m for m in snapshot["metrics"] if m["id"] == "A07")
        check_eq("the run-block's dispatch_id resolves to its controller window",
                 a07["value"]["jobs_by_window"], {"window 3": 1})


def test_retro_numbers_run_block_metrics():
    with tempfile.TemporaryDirectory(prefix="qa-retro-run-blocks-") as td:
        troot = Path(td) / "artifacts" / "T-1"
        (troot / "work" / "run-blocks").mkdir(parents=True)
        (troot / "state").mkdir(parents=True)
        (troot / "state" / "controller.json").write_text(json.dumps({
            "dispatches": {"S5-qa-automator-1": {"stage": "S5", "window": 1},
                           "S5-qa-automator-2": {"stage": "S5", "window": 2}}}), encoding="utf-8")

        def block(name, dispatch_id, instance, status, fp, started):
            (troot / "work" / "run-blocks" / name).write_text(json.dumps({
                "block_id": name, "purpose": "initial", "dispatch_id": dispatch_id,
                "attempt_started_at": started,
                "results": [{"instance_id": instance, "status": status, "input_fingerprint": fp}]}),
                encoding="utf-8")

        block("b1.json", "S5-qa-automator-1", "TC-1", "passed", "fp-1", "2026-09-20T10:00:00Z")
        # Same instance, same fingerprint, already green -> a duplicate/redundant run.
        block("b2.json", "S5-qa-automator-1", "TC-1", "passed", "fp-1", "2026-09-20T10:05:00Z")
        block("b3.json", "S5-qa-automator-2", "TC-2", "failed", "fp-2", "2026-09-20T10:10:00Z")

        result = R.run_block_metrics(troot)
        check_eq("jobs are bucketed by S5 window", result["windows"], {"window 1": 2, "window 2": 1})
        check_eq("three jobs total", result["jobs"], 3)
        check_eq("three test executions total", result["executions"], 3)
        check_eq("exactly one re-ran an already-green, unchanged test",
                 result["duplicate_green_executions"], 1)
        check_eq("the share is one of three", result["duplicate_share_percent"], 33.3)

        text = R.render({"task": "T-1", "test_runs": result})
        check("the retro table names the job count", "Test-execution jobs" in text)
        check("and the window breakdown", "window 1: 2" in text)


def main() -> None:
    test_mark_duplicate_executions_flags_only_a_repeat_of_an_unchanged_green_test()
    test_a09_becomes_available_once_duplicate_execution_is_populated()
    test_a07_gains_jobs_by_window_without_a_new_widget()
    test_the_30_day_window_edge_is_pinned_by_the_clock_not_the_calendar()
    test_project_wires_dispatch_window_into_run_block_jobs()
    test_retro_numbers_run_block_metrics()
    finish("test_run_execution_metrics")


if __name__ == "__main__":
    main()
