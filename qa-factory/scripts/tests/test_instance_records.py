#!/usr/bin/env python3
"""Per-instance regression: parameters and red evidence must never collapse to green."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import contract as C  # noqa: E402
import ledger  # noqa: E402
import manifest_put as M  # noqa: E402

FAILS = 0


def check(name, condition, detail=""):
    global FAILS
    print(("PASS " if condition else "FAIL ") + name + (f" — {detail}" if not condition else ""))
    FAILS += not condition


def main() -> int:
    postgres = {"case": "TC-900", "repository_id": "repo", "profile_id": "db",
                "test": "tests/db.py::test_query", "selector": "query",
                "parameters": {"database": "postgres"}, "file": "tests/db.py"}
    mysql = dict(postgres, parameters={"database": "mysql"})
    mssql = dict(postgres, parameters={"database": "mssql"})
    merged, _ = M.merge({"revision": 4, "tests": [postgres]},
                        {"expected_revision": 4, "tests": [mysql, mssql]})
    check("parameterized tests retain separate instances", len(merged["tests"]) == 3, merged)
    check("stable identity distinguishes parameter dimensions",
          len({C.test_instance_id(item) for item in merged["tests"]}) == 3)

    report = {"results": [
        {"case": "TC-900", "instance_id": C.test_instance_id(postgres), "status": "passed"},
        {"case": "TC-900", "instance_id": C.test_instance_id(mysql), "status": "passed"},
        {"case": "TC-900", "instance_id": C.test_instance_id(mssql), "status": "skipped"},
        {"case": "TC-900", "instance_id": C.test_instance_id(postgres), "status": "failed",
         "purpose": "red_probe"},
    ]}
    check("legacy case projection is conservatively partial", C.run_results(report).get("TC-900") == "partial",
          C.run_results(report))
    instances = C.instance_results(report)
    check("red probe is excluded from product instance results", len(instances[C.test_instance_id(postgres)]) == 1)
    states = [ledger.test_state(entry, report, {"triage": []})[0] for entry in (postgres, mysql, mssql)]
    check("missing review stays separate from execution outcome", states[:2] == ["review_skipped", "review_skipped"], states)
    # Approval is a separate status. Applying it must not alter the result rows.
    approved = [dict(entry, critic_verdict="approved") for entry in (postgres, mysql, mssql)]
    states = [ledger.test_state(entry, report, {"triage": []})[0] for entry in approved]
    check("pass plus skip stays partial at the instance level", states == ["passed_green", "passed_green", "skipped:marked skipped in the run"], states)
    check("rejected review cannot become green",
          ledger.test_state(dict(postgres, critic_verdict="rejected"), report, {"triage": []})[0] == "review_rejected")
    # FR-35: each verdict its own word - per instance, so 3 rejected and 5 unverified never read as 8 rejections.
    check("an unverified review is its own state, not a rejection",
          ledger.test_state(dict(postgres, critic_verdict="unverified"), report, {"triage": []})[0] == "review_unverified")
    check("and it cannot become green either",
          ledger.test_state(dict(mysql, critic_verdict="unverified"), report, {"triage": []})[0] != "passed_green")
    check("a verdict nobody defined is unrecognised, never a rejection",
          ledger.test_state(dict(postgres, critic_verdict="Rejected"), report, {"triage": []})[0]
          == "review_unrecognised:Rejected")
    check("required sensitivity proof cannot be inferred from green execution",
          ledger.test_state(dict(postgres, critic_verdict="approved", sensitivity_proof_required=True), report,
                            {"triage": []})[0] == "not_verified:missing_sensitivity_proof")
    check("changed assertions require sensitivity proof without an opt-in flag",
          ledger.test_state(dict(postgres, critic_verdict="approved", new_or_changed=True), report,
                            {"triage": []})[0] == "not_verified:missing_sensitivity_proof")
    repaired = {"results": [{"case": "TC-900", "instance_id": C.test_instance_id(postgres), "status": "failed"},
                            {"case": "TC-900", "instance_id": C.test_instance_id(postgres), "status": "passed"}]}
    check("legacy result projection uses the repaired current instance outcome",
          C.run_results(repaired).get("TC-900") == "passed", C.run_results(repaired))

    patch, _ = M.merge({"tests": [postgres]}, {"tests": [{"instance_id": C.test_instance_id(postgres),
                                                                "critic_verdict": "approved"}]})
    item = patch["tests"][0]
    check("review patch preserves selector and parameter map",
          item.get("selector") == "query" and item.get("parameters") == {"database": "postgres"}, item)

    # identity is the test. A consolidated instance names no case at all, and the
    # cases it proves are its `covers` — the relationship, not the identity.
    consolidated = {"file": "tests/db.py", "test_function": "test_all", "status": "green",
                    "covers": ["TC-900", "TC-901"]}
    check("a consolidated instance id carries no case prefix",
          C.test_instance_id(consolidated) == "test_all", C.test_instance_id(consolidated))
    check("and every case it proves is readable from the entry",
          C.manifest_test_links(consolidated) == ["TC-900", "TC-901"],
          C.manifest_test_links(consolidated))
    patched, _ = M.merge({"tests": [consolidated]},
                         {"tests": [{"instance_id": "TC-901::test_all",
                                     "critic_verdict": "approved"}]})
    check("a 0.7.7 case-prefixed id still patches the row it meant",
          len(patched["tests"]) == 1 and patched["tests"][0].get("critic_verdict") == "approved",
          patched["tests"])
    print(f"=== test_instance_records: {17 - FAILS}/17 ok ===")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
