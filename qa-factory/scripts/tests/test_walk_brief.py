#!/usr/bin/env python3
"""t-1957 N3 (second part): the walk brief `brief_pack.walk_brief_lines` and the manual branch of `brief_pack.build` (AR-8, AR-11, AR-13, AR-23).

Keys: a manual qa-runner dispatch with `state/walks/<dispatch>.json` gets the thin brief: `Walk:`, `App card:`, every item's Given, steps and
Thens VERBATIM, the `walk_session.py step` command, `fill-account` when the walk is unsigned, the rule line; and none of `manifest_view`,
`env_probe`, `finalize_task`, `Read these files`. The first lane of the story keeps the exploration lines, later lanes do not (no cell dropped,
none repeated). With no walk record the brief is today's plus the PATH of references/manual-evidence.md. An item with no Then is named, not
rendered as an empty list. A temp task, no repo map.

Mutations this file kills: an item's Thens dropped or reworded | the unsigned line lost | a card line of the old brief left in | the exploration
lines dropped from the first lane or repeated in a later one | the fallback without the grammar path.

Run: python -B scripts/tests/test_walk_brief.py    or    python -m pytest -p no:cacheprovider scripts/tests/test_walk_brief.py -q
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import harness  # noqa: E402
import brief_pack  # noqa: E402
import hooklib  # noqa: E402

TASK = "QA-9"
LANE1, LANE2 = "S6-qa-runner-1", "S6-qa-runner-2"
THENS = {"TC-001": ["The order total shows 12.50 after the coupon.", "The coupon is marked used on the account page."],
         "TC-002": ["The second use of the coupon is refused with the word \"expired\"."]}
FORBIDDEN = ("manifest_view", "env_probe", "finalize_task", "Read these files")


def case_text(cid: str, thens: list, teardown: str = "") -> str:
    body = f"---\nid: {cid}\ntitle: {cid} title\narea: coupon\ntask: {TASK}\nplan_row: TS-1\n---\n\n## Given\n- a signed-in reader with a coupon\n\n"
    body += "## When\n1. open the cart\n2. apply the coupon\n\n## Then\n" + "".join(f"{n}. {t}\n" for n, t in enumerate(thens, 1))
    return body + (f"\n## Teardown\n{teardown}\n" if teardown else "")


def seed(tmp: Path, monkeypatch, thens=None, walks=("S6-qa-runner-1",), signed=True) -> Path:
    thens = THENS if thens is None else thens
    root = harness.mark_project(tmp / "proj")
    task = root / "qa-factory" / "artifacts" / TASK
    (task / "work" / "test-cases" / "coupon").mkdir(parents=True)
    (task / "state" / "walks").mkdir(parents=True)
    (task / "pipeline.json").write_text(json.dumps({"ticket": TASK, "size": "S", "environment": "local", "implementation_source": "diff",
                                                    "stages": {"S0": {"status": "pending"}}, "gates": {}, "halts": []}), encoding="utf-8")
    (task / "state" / "story-case-links.json").write_text(json.dumps({"schema_version": 2, "links": []}), encoding="utf-8")
    for cid, items in thens.items():
        (task / "work" / "test-cases" / "coupon" / f"{cid}.md").write_text(
            case_text(cid, items, "delete the coupon you created" if cid == "TC-001" else ""), encoding="utf-8")
    dispatches = {d: {"id": d, "stage": "S6", "role": "qa-runner", "status": "running", "scope": list(thens), "execution_kind": "manual",
                      "manual_case_ids": list(thens)} for d in (LANE1, LANE2)}
    (task / "state" / "controller.json").write_text(json.dumps({"scope": list(thens), "revision": 1, "dispatches": dispatches}), encoding="utf-8")
    for d in walks:
        (task / "state" / "walks" / f"{d}.json").write_text(json.dumps(
            {"walk": d, "state": "ready", "actors": ["reader"] if signed else ["guest"], "items": list(thens), "signed_in": signed,
             "landed_on": "/books" if signed else ""}), encoding="utf-8")
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(root))
    monkeypatch.setattr(hooklib, "_PROJECT_ROOT_CACHE", None)       # restored at the end of the test
    hooklib.pin_project_root(root)                                   # the cache would keep the first test's project
    return task


def brief(dispatch=LANE1) -> str:
    return brief_pack.build(TASK, "S6", "qa-runner", dispatch, write=False)["markdown"]


def test_walk_and_card_lines_present(tmp_path, monkeypatch):
    seed(tmp_path, monkeypatch)
    text = brief()
    assert "Walk: S6-qa-runner-1, account(s) reader, signed in: yes on /books" in text
    assert "App card: qa-factory/artifacts/QA-9/work/app-card.md" in text
    assert "walk_session.py step" in text and "walk_session.py done" in text
    assert "Do not read the application's sources" in text


def test_item_thens_present(tmp_path, monkeypatch):
    seed(tmp_path, monkeypatch)
    text = brief()
    for cid, items in THENS.items():
        assert f"### Item {cid}" in text
        for n, then in enumerate(items, 1):
            assert f"{n}. {then}" in text, (cid, n)
    assert "1. open the cart" in text and "delete the coupon you created" in text      # steps and teardown of the case
    assert "Teardown: none named" in text                                               # TC-002 names none: said, not silent


def test_pinned_story_brief_carries_case_and_teardown(tmp_path, monkeypatch):
    """t-2024: a REAL pinned story (`case_versions`): the case lives at state/case-versions/<case>/cv_<hash>.md, whose file name is no case id;
    the brief used to say 'Case file: not found' for every item. Red when `_case_file_of` re-derives the id from the file name."""
    import case_versions
    task = seed(tmp_path, monkeypatch)
    records = []
    for cid in THENS:
        source = task / "work" / "test-cases" / "coupon" / f"{cid}.md"
        records.append(case_versions.create_version(task / "store", source))
    case_versions.pin_batch(task, records)
    shutil_rmtree = __import__("shutil").rmtree
    shutil_rmtree(task / "work" / "test-cases")                    # only the pinned copies are left, as in a live story
    text = brief()
    assert "not found in this story" not in text
    assert "state/case-versions/TC-001/cv_" in text
    for cid, items in THENS.items():
        for n, then in enumerate(items, 1):
            assert f"{n}. {then}" in text, (cid, n)
    assert "1. open the cart" in text and "- a signed-in reader with a coupon" in text
    assert brief_pack.case_teardown(task, "TC-001") == "delete the coupon you created"
    assert brief_pack.case_teardown(task, "TC-002") == ""


def test_item_without_thens_is_named_not_empty(tmp_path, monkeypatch):
    seed(tmp_path, monkeypatch, thens={"TC-001": [], "TC-002": ["A then."]})
    text = brief()
    assert "Thens: NONE FOUND in" in text and "1. A then." in text


def test_unsigned_walk_names_fill_account(tmp_path, monkeypatch):
    seed(tmp_path, monkeypatch, signed=False)
    text = brief()
    assert "signed in: no: sign in with fill-account" in text and "account(s) guest" in text


def test_thin_brief_has_no_old_card(tmp_path, monkeypatch):
    seed(tmp_path, monkeypatch)
    text = brief()
    for word in FORBIDDEN:
        assert word not in text, word


def test_first_lane_keeps_cells_later_lanes_do_not(tmp_path, monkeypatch):
    task = seed(tmp_path, monkeypatch, walks=(LANE1, LANE2))
    first = brief(LANE1)
    assert "Exploration charter:" in first and "Exploration cells" in first
    tried = task / "work" / "evidence" / "manual" / "TC-001"
    tried.mkdir(parents=True)
    (tried / "tried.md").write_text("# tried\n", encoding="utf-8")       # the first lane has run
    later = brief(LANE2)
    assert "Exploration charter:" not in later and "Exploration cells" not in later
    assert "Walk: S6-qa-runner-2" in later and "### Item TC-001" in later


def test_fallback_brief_names_manual_evidence_path(tmp_path, monkeypatch):
    seed(tmp_path, monkeypatch, walks=())
    text = brief()
    line = next(ln for ln in text.splitlines() if ln.startswith("Recorder grammar:"))
    assert line.split(": ", 1)[1].split(" - ")[0].endswith("references/manual-evidence.md")
    assert "Walk:" not in text and "Read these files" in text        # today's brief otherwise


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-q", "-p", "no:cacheprovider"]))
