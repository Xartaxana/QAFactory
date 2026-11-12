#!/usr/bin/env python3
"""X9 item 3 (F-6 a): the retro analyst's S9 brief names the project's last retro form and what its `tried` table holds
(`brief_pack.prior_retro_lines`). Data only: a path and a row count - what the rows mean is the retro analyst's to judge.

Keys (fixed before the run, quoted from the spec's checks):
  P1 one sibling with two `tried` rows -> the line names the sibling, its path and "2 row(s)"; the brief stays within BRIEF_MAX_BYTES (E3-7)
  P2 two siblings -> the one with the newer `last_activity` is named
  N1 (AR-23) no sibling -> `[]`, and the S9 brief has no "Last retro of this project"
  N2 (AR-28) the controller names the form but the file is absent -> the "cannot be read" line; a form that is not YAML -> the same
  N3 `tried: []` with `tried_note: "x"` -> the "is empty (x)" line
  N4 a sibling whose S9 dispatch is not `accepted` is not a candidate; the story's OWN accepted S9 form is never named
  N5 the S8 scribe's brief has no such line (other roles unchanged)
  N6 (FR-41) `tried` that is null, a string or a mapping -> the "cannot be read (`tried` is not a list)" line, never "empty"
Negative control: with `prior_retro_lines` patched to `[]`, P1's line is absent from the brief (the check can fail).
Kills: returning the own story from `siblings` -> N4; dropping the absent branch -> N1; ordering by folder name only -> P2.
Run: python -B scripts/tests/test_retro_prior_tried.py
"""
import json
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import check, check_eq, check_in, check_not_in, cleanup, finish, temp_project  # noqa: E402

sys.path.insert(0, str(harness.SCRIPTS))
import brief_pack  # noqa: E402
import judge  # noqa: E402
from test_brief_pack import seed  # noqa: E402  (the fixture task root, not copied)

TASK = "QA-9"
MARK = "Last retro of this project"
ROWS = ("tried:\n  - requirement: R-1\n    technique: boundary values\n    observation: the limit is not refused\n"
        "    evidence: work/requirements-register.md#R-1\n  - requirement: R-2\n    technique: error guessing\n"
        "    observation: nothing found\n    evidence: work/requirements-register.md#R-2\n")


def story(root: Path, name: str, form: str | None = None, status: str = "accepted", finished: str = "2026-10-01T10:00:00") -> Path:
    """A sibling story folder: a pipeline with one finished stage, an S9 dispatch in the controller, and the form text (None = no file)."""
    folder = root / "qa-factory" / "artifacts" / name
    (folder / "state").mkdir(parents=True, exist_ok=True)
    (folder / "work" / "handoffs").mkdir(parents=True, exist_ok=True)
    (folder / "pipeline.json").write_text(json.dumps({"ticket": name, "stages": {"S9": {"status": "done", "finished": finished}},
                                                      "gates": {}, "halts": []}), encoding="utf-8")
    ident = "S9-qa-retro-analyst-1"
    (folder / "state" / "controller.json").write_text(json.dumps({"dispatches": {ident: {
        "id": ident, "stage": "S9", "role": "qa-retro-analyst", "status": status}}}), encoding="utf-8")
    if form is not None:
        (folder / "work" / "handoffs" / f"{ident}.yaml").write_text(form, encoding="utf-8")
    return folder


def brief(role: str, stage: str) -> str:
    with patch.object(judge, "active", return_value=False):
        return brief_pack.build(TASK, stage, role, f"{stage}-{role}-9", write=False)["markdown"]


def lines(root: Path) -> list:
    return brief_pack.prior_retro_lines(root / "qa-factory" / "artifacts" / TASK, root)


def clean(root: Path, *names: str) -> None:
    import shutil
    for name in names:
        shutil.rmtree(root / "qa-factory" / "artifacts" / name, ignore_errors=True)


def main() -> None:
    root = temp_project("retro-prior-")
    try:
        harness.use_project(root)
        task = seed(root, TASK)
        # N1: no other story at all
        check_eq("N1: no sibling story -> no line (AR-23: absent, never a placeholder)", lines(root), [])
        check_not_in("N1: ... and the S9 brief has no such line", MARK, brief("qa-retro-analyst", "S9"))
        # N4 (own story): the story's OWN accepted S9 form is never named
        (task / "state").mkdir(exist_ok=True)
        (task / "work" / "handoffs").mkdir(parents=True, exist_ok=True)
        (task / "state" / "controller.json").write_text(json.dumps({"dispatches": {"S9-qa-retro-analyst-1": {
            "id": "S9-qa-retro-analyst-1", "stage": "S9", "role": "qa-retro-analyst", "status": "accepted"}}}), encoding="utf-8")
        (task / "work" / "handoffs" / "S9-qa-retro-analyst-1.yaml").write_text(ROWS, encoding="utf-8")
        check_eq("N4: the story's own accepted S9 form is never named", lines(root), [])
        # N4 (not accepted): a sibling whose S9 dispatch is not accepted is not a candidate
        story(root, "QA-1", ROWS, status="running")
        check_eq("N4: a sibling whose S9 dispatch is not accepted -> no line", lines(root), [])
        clean(root, "QA-1")
        # P1
        story(root, "QA-1", ROWS)
        got = lines(root)
        check_eq("P1: one sibling -> one line", len(got), 1)
        check_in("P1: ... naming the sibling", "(QA-1)", got[0])
        check_in("P1: ... its path", "qa-factory/artifacts/QA-1/work/handoffs/S9-qa-retro-analyst-1.yaml", got[0])
        check_in("P1: ... and the row count", "has 2 row(s)", got[0])
        retro = brief("qa-retro-analyst", "S9")
        check_in("P1: the S9 retro brief carries the line", got[0], retro)
        check("P1: ... and stays within BRIEF_MAX_BYTES (E3-7)", len(retro.encode("utf-8")) <= brief_pack.BRIEF_MAX_BYTES, str(len(retro.encode("utf-8"))))
        # N5: the S8 scribe's brief is not touched
        check_not_in("N5: the S8 scribe's brief has no such line", MARK, brief("qa-doc-scribe", "S8"))
        # negative control: with the function returning [] the line is gone from the brief
        with patch.object(brief_pack, "prior_retro_lines", return_value=[]):
            check_not_in("P1 negative control: with prior_retro_lines patched to [] the line is absent", MARK, brief("qa-retro-analyst", "S9"))
        # P2: two siblings, the newer by last_activity wins (the OLDER one has the later folder name, so a name sort would pick it)
        story(root, "QA-2", ROWS, finished="2026-09-01T10:00:00")
        story(root, "QA-0", ROWS, finished="2026-11-01T10:00:00")
        got = lines(root)
        check("P2: the sibling with the newer last_activity is named (not the later folder name)", "(QA-0)" in got[0] and "QA-2" not in got[0], str(got))
        clean(root, "QA-0", "QA-2")
        # N2: the controller names the form but the file is absent
        clean(root, "QA-1")
        story(root, "QA-1", None)
        got = lines(root)
        check("N2: a form that is absent -> one 'cannot be read' line, never 'nothing found'",
              len(got) == 1 and "cannot be read" in got[0] and "(QA-1)" in got[0], str(got))
        check_not_in("N2: ... and it does not say how many rows", "row(s)", got[0])
        clean(root, "QA-1")
        story(root, "QA-1", "this is not a form at all, just words\n")
        got = lines(root)
        check("N2: a form that is not YAML -> the same line", len(got) == 1 and "cannot be read" in got[0], str(got))
        clean(root, "QA-1")
        # N3: an empty table with its note
        story(root, "QA-1", 'tried: []\ntried_note: "x"\n')
        got = lines(root)
        check("N3: an empty table with a note -> 'is empty (x)'", len(got) == 1 and "its `tried` table is empty (x)" in got[0], str(got))
        clean(root, "QA-1")
        story(root, "QA-1", "tried: []\n")
        got = lines(root)
        check("N3: ... and with no note -> 'no tried_note'", len(got) == 1 and "is empty (no tried_note)" in got[0], str(got))
        clean(root, "QA-1")
        # N6 (FR-41, m-1): a `tried` that is not a list is unknown, never "empty"
        for label, text in (("null", "tried:\n"), ("a string", "tried: some words\n"), ("a mapping", "tried:\n  a: 1\n")):
            story(root, "QA-1", text)
            got = lines(root)
            check(f"N6: `tried` as {label} -> the 'cannot be read' line, never 'empty'",
                  len(got) == 1 and "cannot be read" in got[0] and "`tried` is not a list" in got[0] and "empty" not in got[0], str(got))
            clean(root, "QA-1")
    finally:
        cleanup(root)
    finish("test_retro_prior_tried")


if __name__ == "__main__":
    main()
