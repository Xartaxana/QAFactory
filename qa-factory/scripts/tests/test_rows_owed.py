#!/usr/bin/env python3
"""F4 (t-1936 N2, AR-10, AR-28, AR-29): a verdict that sends a window back owes at least one `findings` row.

`handoff.rows_owed(contract, verdict)` reads the contract's own `rows_owed_when` block (data, AR-1) and gives the sections owed
under that verdict; `handoff_check.check` refuses an owed section that is empty (nothing, or only the template row) once, naming
the missing field and the closed cause list. Presence only: what a row says is never read here.
Run: python -B -m pytest scripts/tests/test_rows_owed.py -q
"""
import sys
import pytest
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402

sys.path.insert(0, str(harness.SCRIPTS))
import handoff  # noqa: E402
import handoff_check as HC  # noqa: E402

CONTRACT = "s5-critic-to-automator"
HEADER = "header:\n  role: qa-code-critic\n  stage: S5\n  window: TC-1\n  verdict: {verdict}\n"
REAL_ROW = ("findings:\n  - id: F-1\n    file: tests/test_a.py\n    line: 3\n    problem: the assert reads the constant\n"
            "    expected: an assert on the response body\n    fix: assert the body\n    check: pytest\n    cause: test_defect\n"
            "    blocking: true\n")
TEMPLATE_ROW = "findings:\n  - id: <F-n>\n    file: <repo-relative path>\n    cause: <one of vocabulary.repair_causes>\n"


def problems_of(verdict, tail, contract=CONTRACT):
    task = Path(tempfile.mkdtemp(prefix="qa-rows-owed-"))
    try:
        doc = handoff.parse(HEADER.format(verdict=verdict) + tail)
        _doc, _fixed, problems, _j, _d = HC.check(doc, contract, HC.Artifacts(task, dispatch="S5-qa-code-critic-1"), use_judge=False)
        return [p for p in problems if p.path == "findings"]
    finally:
        harness.cleanup(task)


def test_rows_owed_reads_block():
    assert handoff.rows_owed(CONTRACT, "concerns") == {"findings"}
    assert handoff.rows_owed(CONTRACT, "review") == {"findings"}
    assert handoff.rows_owed(CONTRACT, " review ") == {"findings"}
    assert handoff.rows_owed(CONTRACT, "ok") == set()
    assert handoff.rows_owed(CONTRACT, "approved") == set()
    # S2-S4 critic contracts owe findings (FU1), not questions
    for contract in ("s2-stage-critic-to-tester", "s3-stage-critic-to-strategist", "s4-case-critic-to-designer"):
        assert handoff.rows_owed(contract, "concerns") == {"findings"}, contract
        assert handoff.rows_owed(contract, "review") == {"findings"}, contract
        assert handoff.rows_owed(contract, "ok") == set(), contract
    # absent world: a contract that carries no block owes nothing (today's behaviour)
    assert handoff.rows_owed("s5-critic-plan-to-automator", "concerns") == set()
    # an unfilled or missing verdict owes nothing (the 'not filled' check on the verdict itself refuses it)
    assert handoff.rows_owed(CONTRACT, None) == set()
    assert handoff.rows_owed(CONTRACT, "<one of vocabulary.header_verdicts>") == set()


def test_malformed_block_owes_nothing():
    original = handoff.template

    class Fake:
        def __init__(self, data):
            self.data = data

    try:
        for bad in ("concerns", ["concerns"], {"concerns": "findings"}, {"concerns": [5]}, {"concerns": [""]}, {"concerns": None}, {}):
            handoff.template = lambda contract_id, bad=bad: Fake({"rows_owed_when": bad})
            assert handoff.rows_owed(CONTRACT, "concerns") == set(), bad
        handoff.template = lambda contract_id: Fake({"rows_owed_when": {"concerns": ["findings"]}})
        assert handoff.rows_owed(CONTRACT, "concerns") == {"findings"}     # the control: a well-formed block is read
    finally:
        handoff.template = original


def test_check_refuses_empty_findings_under_concerns():
    for verdict in ("concerns", "review"):
        for label, tail in (("absent", ""), ("empty list", "findings: []\n"), ("template row only", TEMPLATE_ROW),
                            ("tooling_findings only (fork 6 A)", "findings: []\ntooling_findings:\n  - id: F-1\n    tool: probe_by_code.py\n"
                                                              "    backlog_row: '-'\n    instances: TC-1\n")):
            got = problems_of(verdict, tail)
            assert len(got) == 1 and "no rows" in got[0].text and verdict in got[0].text, (verdict, label, got)
    assert problems_of("concerns", REAL_ROW) == []         # a real row satisfies it (presence only)


def test_check_passes_empty_findings_under_ok():
    for verdict in ("ok", "approved"):
        assert problems_of(verdict, "findings: []\n") == [], verdict
        assert problems_of(verdict, "") == [], verdict


def test_refusal_names_cause_list():
    got = problems_of("concerns", "findings: []\n")[0]
    for cause in handoff.allowed("repair_causes"):
        assert cause in got.text, cause
    assert "tooling" in got.text and "findings[0]" in got.text + got.fix
    assert "cause is one of" in got.text



def test_s4_untouched_nested_template_row_is_not_a_filled_row():
    """M2: the S4 template `findings` row holds a nested `replacement:` map; `_is_empty_section` (one level) calls it filled."""
    s4 = "s4-case-critic-to-designer"
    template_rows = handoff.template(s4).text().split("\nfindings:\n", 1)[1].split("\n\n", 1)[0]
    got = problems_of("concerns", "findings:\n" + template_rows + "\n", s4)
    assert len(got) == 1 and "no rows" in got[0].text, got
    # the refusal names this stage's own row, not S5's: no repair cause clause, no S5 `.line` key
    assert "cause is one of" not in got[0].text and ".line" not in got[0].fix and "findings[0].case" in got[0].text + got[0].fix, got[0]
    assert len(problems_of("concerns", "findings: []\n", s4)) == 1
    assert problems_of("ok", "findings: []\n", s4) == []           # both worlds: a pass owes nothing


def test_s2_s3_owe_findings_under_concerns_and_nothing_under_ok():
    for contract in ("s2-stage-critic-to-tester", "s3-stage-critic-to-strategist"):
        got = problems_of("concerns", "", contract)
        assert len(got) == 1 and "no rows" in got[0].text, (contract, got)
        assert problems_of("ok", "", contract) == [], contract


if __name__ == "__main__": raise SystemExit(pytest.main([__file__, "-q", "-p", "no:cacheprovider"]))
