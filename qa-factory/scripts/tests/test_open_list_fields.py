"""X7-5: the list fields of the S5-S9 forms. A ROUTE field (code branches on its word, E-16) stays closed - `new:` is refused;
the five fields no code reads take `new: <word> -- <why>`. `OPEN_LIST_CONTRACTS` is an explicit tuple, not an alias of
`TRIED_CONTRACTS` (AR-20). Also the report-id shapes, the oracle kinds of a bug and the red test that travels with the bug.

Run: `python -B -m pytest scripts/tests/test_open_list_fields.py -q`.
"""
import sys
import pytest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import SCRIPTS  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import artifact_producer as AP  # noqa: E402
import contract as C  # noqa: E402
import handoff as H  # noqa: E402
import handoff_check as HC  # noqa: E402
import validate_artifacts as V  # noqa: E402

WHY = "two writers of one row"
S5, S7, S8, S9 = ("s5-automator-to-runner", "s7-analyst-to-automator", "s8-bug-reporter-to-scribe", "s9-retro-to-project")


def problems(contract: str, text: str, tmp_path, path: str) -> list:
    doc = H.parse(f"contract: {contract}\n{text}")
    return [p for p in HC.check(doc, contract, HC.Artifacts(tmp_path))[2] if p.path == path]


def test_the_alias_is_broken(monkeypatch):
    assert HC.OPEN_LIST_CONTRACTS is not HC.TRIED_CONTRACTS
    before = HC.OPEN_LIST_CONTRACTS
    monkeypatch.setattr(HC, "TRIED_CONTRACTS", ())
    assert HC.OPEN_LIST_CONTRACTS == before and S9 in HC.OPEN_LIST_CONTRACTS


def test_the_open_fields_of_s5_s8_s9_take_the_door(tmp_path):
    new = f"new: seam-race -- {WHY}"
    cases = ((S5, f"scope:\n  - id: a\n    stale_because: {new}\n", "scope[0].stale_because"),
             (S8, f"filed:\n  - draft: d\n    action: {new}\n", "filed[0].action"),
             (S9, f"knowledge_fold:\n  - fact: f\n    kind: {new}\n", "knowledge_fold[0].kind"),
             (S9, f"numbers:\n  estimation_ledger_line: {new}\n", "numbers.estimation_ledger_line"),
             (S9, f"delivery_bookkeeping:\n  post_s9_update: {new}\n", "delivery_bookkeeping.post_s9_update"))
    for contract, text, path in cases:
        assert problems(contract, text, tmp_path, path) == [], path


def test_a_route_field_stays_closed(tmp_path):
    # a triage verdict (S7), a row state (S9, S8), the freshness word (S5): code branches on each
    for contract, text, path in ((S7, f"scope:\n  - id: a\n    state: new: maybe_bug -- {WHY}\n", "scope[0].state"),
                                 (S9, f"scope:\n  - id: a\n    state: new: seam-race -- {WHY}\n", "scope[0].state"),
                                 (S8, f"scope:\n  - id: a\n    state: new: seam-race -- {WHY}\n", "scope[0].state"),
                                 (S5, f"scope:\n  - id: a\n    freshness: new: seam-race -- {WHY}\n", "scope[0].freshness")):
        found = problems(contract, text, tmp_path, path)
        assert len(found) == 1 and "is not a value of this field" in found[0].text and "new: <word>" not in found[0].text, path


def test_a_word_outside_an_open_s8_field_names_the_door(tmp_path):
    found = problems(S8, "filed:\n  - draft: d\n    action: vibes\n", tmp_path, "filed[0].action")
    assert len(found) == 1 and "new: <word> -- <why>" in found[0].text


def test_every_open_field_is_a_field_of_its_form():
    for contract, paths in HC.OPEN_LIST_FIELDS.items():
        assert contract in HC.OPEN_LIST_CONTRACTS
        assert set(paths) <= set(H.spec(contract)), contract


# --- the report: shapes of ids, never a phrase --------------------------------------------------------------------------
def report_errors(tmp_path, text: str) -> list:
    path = tmp_path / "test-report.md"
    path.write_text("# T\n\n" + text + "\n", encoding="utf-8")
    errors: list = []
    V.check_report_forbidden(path, errors)
    return errors


def test_report_id_shapes(tmp_path):
    assert report_errors(tmp_path, "case version cv_12ab here") != []
    assert report_errors(tmp_path, "instance ti_4fa2889035ca") != []
    assert report_errors(tmp_path, "see work/ledger.json") != []


# --- the bug form: oracle kinds are a route, the severity is the reporter's, the red test is with the bug ----------------
FORM = {"id": "BUG-1", "title": "t", "status": "open", "severity": "minor", "violates": "requirement:R-5", "impact": "degraded",
        "confirmation": "unconfirmed", "created": "2026-11-05", "source_draft": "work/bug-drafts/a.json", "cases": "[TC-1]",
        "requirements": "[R-5]", "red_test_none": "manual check only"}

def form_errors(**over) -> list:
    errors: list = []
    fm = {**FORM, **over}
    fm = {k: v for k, v in fm.items() if v is not None}
    V.check_bug_form(Path("BUG-1.md"), fm, _body(), errors)
    return errors


def _body() -> str:
    return "\n".join(f"{heading}\n\nx\n" for heading in V.BUG_FORM_SECTIONS)


def test_violates_code_is_refused_naming_p20_and_the_kinds():
    found = [e for e in form_errors(violates="code:calculateTotal") if "violates" in e]
    assert len(found) == 1 and "P20" in found[0] and all(k in found[0] for k in
                                                         ("requirement:R-n", "invariant:", "consistency:", "history:", "impact:", "external:"))


def test_an_unknown_violates_kind_is_refused():
    found = [e for e in form_errors(violates="vibes:the page feels slow") if "violates" in e]
    assert len(found) == 1 and "oracle kinds" in found[0] and "P20" not in found[0]


def test_the_six_kinds_pass():
    for value in ("requirement:R-4", "invariant:totals add up", "consistency:list vs detail", "history:before 4.2",
                  "impact:data loss", "external:RFC 7231"):
        assert [e for e in form_errors(violates=value) if "violates" in e] == [], value


def test_a_severity_differing_from_the_scale_is_not_refused():
    assert [e for e in form_errors(severity="blocker", impact="degraded") if "severity" in e] == []
    assert form_errors() == []


def test_the_red_test_travels_with_the_bug():
    found = [e for e in form_errors(red_test_none=None) if "red_test" in e]
    assert len(found) == 1 and "`red_test`" in found[0] and "`red_test_none`" in found[0]
    assert form_errors(red_test_none="manual check only") == []
    assert form_errors(red_test_none=None, red_test="{path: tests/a.py, command: pytest tests/a.py}") == []
    # a bug created before the day the rule starts, and a bug with no draft, are not asked
    assert [e for e in form_errors(red_test_none=None, created="2026-11-03") if "red_test" in e] == []
    assert [e for e in form_errors(red_test_none=None, source_draft=None) if "red_test" in e] == []


def test_the_bug_file_refusal_names_the_flat_form_and_the_draft_one_the_mapping():
    flat = [e for e in form_errors(red_test_none=None) if "red_test" in e]
    assert len(flat) == 1 and "<path of the failing test> -- <command that runs it>" in flat[0] and "{path" not in flat[0]
    draft = C.red_test_problems({})
    assert len(draft) == 1 and "{path: <the failing test>, command: <how to run it>}" in draft[0]
    # a draft's `red_test` is a mapping: a plain text or a list is refused there, and a bug file's flat text passes
    assert len(C.red_test_problems({"red_test": "yes"})) == 1 and len(C.red_test_problems({"red_test": ["x"]})) == 1
    assert C.red_test_problems({"red_test": "tests/a.py -- pytest tests/a.py"}, flat=True) == []


def test_the_skeleton_carries_the_red_test_keys_and_a_filled_one_passes():
    skeleton = AP.prepare("bug")["frontmatter"]
    assert "red_test" in skeleton and "red_test_none" in skeleton
    fm = {**dict.fromkeys(skeleton, ""), **FORM, "red_test_none": "", "red_test": "tests/a.py -- pytest tests/a.py"}   # as the reporter fills it
    assert AP.render({"frontmatter": fm, "body": _body()}).count("red_test: tests/a.py -- pytest tests/a.py") == 1
    errors: list = []
    V.check_bug_form(Path("BUG-1.md"), fm, _body(), errors)
    assert [e for e in errors if "red_test" in e] == []


def test_the_cutoff_has_one_reader_and_one_copy():
    assert not hasattr(V, "BUG_RED_TEST_CUTOFF")
    assert not C.red_test_owed({"created": "2026-11-03"}) and C.red_test_owed({"created": "2026-11-04T10:00:00"})
    assert C.red_test_owed({}, "2026-11-04") and not C.red_test_owed({}, "2026-11-03") and not C.red_test_owed({})
    assert C.red_test_owed({"created": "2026-11-05"}, "2026-11-01")           # the record's own day wins over the fallback


def test_the_factory_defects_section_refuses_ids_and_lets_a_phrase_about_a_tool_run_pass(tmp_path):
    def found(text: str) -> list:
        path = tmp_path / "test-report.md"
        path.write_text("# T\n\n## Verdict\n\n`delivery_ready: yes`\n\n## Factory defects\n\n" + text + "\n", encoding="utf-8")
        errors: list = []
        V.check_report_human_text(path, errors)
        return errors
    assert found("The helper story_run.py stopped.") != []
    assert found("The helper stopped with exit 3.") == []


if __name__ == "__main__": raise SystemExit(pytest.main([__file__, "-q", "-p", "no:cacheprovider"]))
