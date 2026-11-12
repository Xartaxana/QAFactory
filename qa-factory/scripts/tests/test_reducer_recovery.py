#!/usr/bin/env python3
"""Semantic reducer/consumer checks: current truth must not depend on filenames."""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import check_delivery as D  # noqa: E402
import contract as C  # noqa: E402
import finalize_task as F  # noqa: E402
import ledger as L  # noqa: E402
from event_store import EventStore  # noqa: E402


FAILS = 0


def check(name, value, detail=""):
    global FAILS
    print(("PASS " if value else "FAIL ") + name + (f" — {detail}" if not value else ""))
    FAILS += not value


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def block(task, name, started, results=None, manual=None):
    write(task / "work" / "run-blocks" / name, {
        "block_id": name, "attempt_started_at": started,
        "attempt_ended_at": started.replace("00Z", "30Z"),
        "results": results or [], "manual_checks": manual or []})


def main():
    with tempfile.TemporaryDirectory(prefix="qa-reducer-recovery-") as td:
        root = Path(td)
        temporal = root / "QA-TEMPORAL"
        block(temporal, "z-old.json", "2026-09-17T10:00:00Z",
              [{"instance_id": "i1", "case": "TC-1", "status": "failed"}])
        block(temporal, "a-new.json", "2026-09-17T11:00:00Z",
              [{"instance_id": "i1", "case": "TC-1", "status": "passed"}])
        F.refresh(temporal)
        report = C.load_json(temporal / "work" / "run-report.json")
        check("latest temporal attempt wins despite reversed filenames",
              report.get("execution_status") == "passed"
              and report.get("current_results", [{}])[0].get("status") == "passed", report)
        check("historical repaired failure does not demand current triage",
              D.triage_reasons(temporal) == [], D.triage_reasons(temporal))
        state, _ = L.test_state({"instance_id": "i1", "case": "TC-1", "file": "test.py",
                                 "marker": "test_one", "critic_verdict": "approved"}, report, {})
        check("ledger uses the reducer current result rather than historical failures",
              state == "passed_green", state)

        ambiguous = root / "QA-AMBIGUOUS"
        stamp = "2026-09-17T12:00:00Z"
        block(ambiguous, "one.json", stamp,
              [{"instance_id": "i2", "case": "TC-2", "status": "failed"}],
              [{"case": "TC-M", "result": "failed"}])
        block(ambiguous, "two.json", stamp,
              [{"instance_id": "i2", "case": "TC-2", "status": "passed"}],
              [{"case": "TC-M", "result": "passed"}])
        F.refresh(ambiguous)
        report = C.load_json(ambiguous / "work" / "run-report.json")
        current_manual = report.get("current_manual_checks", [{}])[0]
        check("ambiguous automated and manual attempts cannot become green",
              report.get("execution_status") == "not_executed"
              and report.get("current_results", [{}])[0].get("status") == "partial"
              and current_manual.get("result") == "inconclusive", report)
        check("compatibility readers consume current manual projection",
              C.run_results(report).get("TC-M") != "passed", C.run_results(report))

        concurrent = root / "QA-CONCURRENT"
        block(concurrent, "left.json", stamp,
              [{"instance_id": "left", "case": "TC-L", "status": "passed"}])
        block(concurrent, "right.json", stamp,
              [{"instance_id": "right", "case": "TC-R", "status": "passed"}])
        F.refresh(concurrent)
        report = C.load_json(concurrent / "work" / "run-report.json")
        check("equal-time disjoint parallel results reduce without false ambiguity",
              report.get("execution_status") == "passed"
              and report.get("attempt_order") == "ordered_by_attempt_started_at"
              and len(report.get("current_results", [])) == 2, report)

        invalidated = root / "QA-INVALIDATED"
        block(invalidated, "two-scopes.json", "2026-09-17T12:30:00Z",
              [{"instance_id": "i-a", "case": "TC-A", "status": "passed", "dispatch_id": "dispatch-a"},
               {"instance_id": "i-b", "case": "TC-B", "status": "passed", "dispatch_id": "dispatch-b"}])
        EventStore(invalidated).commit(
            "invalidate", {"dispatch_ids": ["dispatch-a"], "affected_scope": ["TC-A"],
                           "reason": "source changed for TC-A"}, "invalidate-a")
        F.refresh(invalidated)
        report = C.load_json(invalidated / "work" / "run-report.json")
        current = {row.get("instance_id"): row for row in report.get("current_results", [])}
        check("scoped invalidation removes only the affected instance's old green",
              current.get("i-a", {}).get("status") == "not_run"
              and current.get("i-a", {}).get("current_reason") == "invalidated_evidence"
              and current.get("i-b", {}).get("status") == "passed"
              and report.get("execution_status") != "passed", report)
        block(invalidated, "repair-a.json", "2026-09-17T12:31:00Z",
              [{"instance_id": "i-a", "case": "TC-A", "status": "passed",
                "dispatch_id": "dispatch-a-fresh"}])
        F.refresh(invalidated)
        report = C.load_json(invalidated / "work" / "run-report.json")
        current = {row.get("instance_id"): row for row in report.get("current_results", [])}
        check("fresh affected evidence restores green without rerunning unaffected scope",
              report.get("execution_status") == "passed"
              and current.get("i-a", {}).get("dispatch_id") == "dispatch-a-fresh"
              and current.get("i-b", {}).get("dispatch_id") == "dispatch-b"
              and sum(1 for row in report.get("results", []) if row.get("instance_id") == "i-b") == 1,
              report)

        malformed = root / "QA-MALFORMED"
        block(malformed, "unknown.json", "2026-09-17T13:00:00Z",
              [{"instance_id": "i3", "case": "TC-3", "status": "invented"}])
        F.refresh(malformed)
        report = C.load_json(malformed / "work" / "run-report.json")
        check("unknown result vocabulary never produces a green report",
              report.get("execution_status") == "not_executed", report)

        triaged = root / "QA-TRIAGE"
        block(triaged, "fail.json", "2026-09-17T14:00:00Z",
              [{"instance_id": "i4", "case": "TC-4", "status": "failed"}])
        F.refresh(triaged)
        triage_path = triaged / "work" / "triage.json"
        write(triage_path, {"triage": [{"instance_id": "i4", "test": "i4", "verdict": "APP_BUG"}]})
        F.refresh(triaged)
        check("repeated refresh preserves analyst triage for a current failure",
              C.load_json(triage_path).get("triage", [{}])[0].get("verdict") == "APP_BUG")
        block(triaged, "repair.json", "2026-09-17T15:00:00Z",
              [{"instance_id": "i4", "case": "TC-4", "status": "passed"}])
        F.refresh(triaged)
        archived = list((triaged / "state" / "migration").glob("stale-triage-*.json"))
        check("repair archives stale triage instead of overwriting it silently",
              C.load_json(triage_path).get("triage") == [] and bool(archived))

    print(f"=== test_reducer_recovery: {11 - FAILS}/11 ok ===")
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
