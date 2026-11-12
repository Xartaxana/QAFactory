#!/usr/bin/env python3
"""Regression for the live-run defect of 2026-09-11 (QA-1): ten tests in one file, one APP_BUG in
triage — the ledger coloured all ten as failed because it matched triage rows by file substring.
The ledger must match by case id or by the exact test id, never by the file path."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ledger  # noqa: E402

FAILS = 0


def check(name, ok, detail=""):
    global FAILS
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f" — {detail}"))
    if not ok:
        FAILS += 1


def main() -> int:
    file = "tests/test_items.py"
    manifest = {"tests": [
        {"case": "TC-006", "file": file, "marker": "TC-006", "test": f"{file}::test_a", "critic_verdict": "approved"},
        {"case": "TC-015", "file": file, "marker": "TC-015", "test": f"{file}::test_sixth_tag", "critic_verdict": "approved"},
        {"case": "TC-01", "file": file, "marker": "TC-01", "test": f"{file}::test_prefix", "critic_verdict": "approved"},
    ]}
    report = {"execution_status": "failed", "results": [
        {"case": "TC-006", "test": f"{file}::test_a", "result": "passed"},
        {"case": "TC-015", "test": f"{file}::test_sixth_tag", "result": "failed"},
        {"case": "TC-01", "test": f"{file}::test_prefix", "result": "passed"},
    ]}
    triage = {"triage": [{"test": f"{file}::test_sixth_tag", "case": "TC-015", "verdict": "APP_BUG"}]}

    states = {t["case"]: ledger.test_state(t, report, triage)[0] for t in manifest["tests"]}
    check("the triaged test is failed:APP_BUG", states["TC-015"] == "failed:APP_BUG", str(states))
    check("a green test in the same file stays passed_green", states["TC-006"] == "passed_green", str(states))
    check("a case id that is a prefix of the failed one is not matched", states["TC-01"] == "passed_green", str(states))

    v = ledger._verdict_for_cases(["TC-006"], manifest, triage)
    check("plan-row verdict for a green case is untriaged (no row)", v == "untriaged", v)
    v = ledger._verdict_for_cases(["TC-015"], manifest, triage)
    check("plan-row verdict for the failed case is APP_BUG", v == "APP_BUG", v)

    triage_flaky = {"triage": [{"test": f"{file}::test_sixth_tag", "case": "TC-015", "verdict": "FLAKY", "mechanism": "timing"}]}
    unfixed = ledger._unfixed_flaky(["TC-006", "TC-015", "TC-01"], manifest, triage_flaky)
    check("only the flaky test itself is reported unfixed", unfixed == ["TC-015"], str(unfixed))

    # a triage row without a case id still matches by the exact test id
    triage_noid = {"triage": [{"test": f"{file}::test_sixth_tag", "verdict": "TEST_BUG"}]}
    states = {t["case"]: ledger.test_state(t, report, triage_noid)[0] for t in manifest["tests"]}
    check("exact test id matches without a case id", states["TC-015"] == "failed:TEST_BUG", str(states))
    check("and still leaves the neighbours green", states["TC-006"] == "passed_green", str(states))

    # A compound case cell is refused on write now, but one already on disk must still
    # read: on TP1-14501 "TC-001/TC-002/TC-003" matched no case and three green tests
    # reached the ledger as not_executed.
    import contract as C
    compound = {"results": [{"test": f"{file}::test_chained", "case": "TC-001/TC-002/TC-003",
                             "result": "passed"}]}
    got = C.run_results(compound)
    check("a compound case cell resolves to each case", 
          all(got.get(c) == "passed" for c in ("TC-001", "TC-002", "TC-003")), str(got))

    print(f"=== test_ledger_matching: {9 - FAILS}/9 ok ===")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
