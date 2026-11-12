#!/usr/bin/env python3
"""E07/E23 reducer seams: planned visibility, 0/N manual blocks, and parameter retention."""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import contract as C  # noqa: E402
import factory_dashboard as D  # noqa: E402
import finalize_task as F  # noqa: E402

FAILS = 0


def check(name, ok, detail=""):
    global FAILS
    print(("PASS " if ok else "FAIL ") + name + (f" — {detail}" if not ok else ""))
    FAILS += not ok


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="qa-finalize-") as root_s:
        root = Path(root_s)
        task = root / "qa-factory" / "artifacts" / "QA-900"
        one = {"block_id": "automation-1", "execution_status": "passed", "results": [
            {"case": "TC-900", "instance_id": "pg", "status": "passed"},
            {"case": "TC-900", "instance_id": "my", "status": "passed"},
            {"case": "TC-900", "instance_id": "ms", "status": "skipped"},
            {"case": "TC-900", "instance_id": "pg", "status": "failed", "red_probe": True},
        ]}
        manual = {"block_id": "manual-1", "manual_checks": [{"case": "TC-901", "result": "passed"}]}
        write(task / "work" / "run-blocks" / "one.json", one)
        write(task / "work" / "manual-blocks" / "one.json", manual)
        first = F.refresh(task)
        second = F.refresh(task)
        report = C.load_json(task / "work" / "run-report.json")
        triage = C.load_json(task / "work" / "triage.json")
        check("all parameter instances and red evidence are retained", len(report["results"]) == 4, report)
        check("product case rollup stays partial", C.run_results(report).get("TC-900") == "partial")
        check("repeated finalization does not duplicate blocks", first == second and len(report["reducer"]["sources"]) == 2)
        check("no product failure creates deterministic empty triage", triage.get("triage") == [] and triage.get("reason"))
        check("N manual blocks remain in the whole-story report", len(report["manual_checks"]) == 1)

        repair = {"block_id": "automation-repair", "results": [
            {"case": "TC-900", "instance_id": "pg", "status": "failed"},
            {"case": "TC-900", "instance_id": "pg", "status": "passed"},
        ]}
        write(task / "work" / "run-blocks" / "repair.json", repair)
        repaired = F.refresh(task)
        check("current instance outcome uses repaired final attempt", repaired["execution_status"] == "not_executed",
              C.load_json(task / "work" / "run-report.json").get("current_totals"))

        old = root / "qa-factory" / "artifacts" / "QA-OLD"
        write(old / "run-report.json", {"block_id": "old", "results": [{"case": "TC-1", "status": "passed"}]})
        F.refresh(old)
        F.refresh(old)
        old_report = C.load_json(old / "work" / "run-report.json")
        check("legacy report is captured once as immutable reducer input", len(old_report["reducer"]["sources"]) == 1)
        check("flat legacy report is archived before canonical projection", not (old / "run-report.json").exists()
              and any((old / "state" / "migration").glob("run-report-legacy-*.json")))

        planned = root / "qa-factory" / "artifacts" / "QA-901"
        write(planned / "work" / "automation-manifest.json", {"tests": [
            {"case": "TC-902", "repository_id": "repo", "profile_id": "p", "test": "t::x",
             "selector": "x", "parameters": {"db": "postgres"}, "critic_verdict": "approved"}]})
        tasks = D.parse_taskruns(root)
        entry = next(item for item in tasks if item["task"] == "QA-901")
        check("approved planned task is visible without run-report", entry["planned_only"] and len(entry["manifest_entries"]) == 1)
    print(f"=== test_finalization_flow: {9 - FAILS}/9 ok ===")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
