#!/usr/bin/env python3
"""The seven header lines of a charter role's brief (spec t-1765 X1-6, section 3.4, node B-A).

The lines (goal, DoD, given, owns, non-goals, handoff, questions) go to a role whose agent file IS a charter and to no other.
Until the charters land (node B-C) no shipped role is one, so the charter files here are synthetic: the test points
`brief_pack.HERE` at a temp plugin copy whose `agents/` holds them.

Mutations, each killed by the ONE test named (builder-rules 7a):
  `head[2:2]` replaced by `head.append`                                      -> test_seven_lines_sit_right_after_the_title
  the empty-reason branch of `_form_line` returns ""                         -> test_empty_inputs_print_the_dash_and_the_reason
  `len(value) + len(keep) > limit` changed to `>=`                           -> test_line_chars_at_and_beyond
  `_input_names` replaced by a second formula in `sd_head_lines`             -> test_given_names_the_snapshot_and_follows_the_file_list
Run: python -B -m pytest scripts/tests/test_brief_pack_sd_head.py -q
"""
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from test_brief_pack import seed  # noqa: E402  (the fixture task root, not copied)
from test_charter_form import charter_text  # noqa: E402

sys.path.insert(0, str(harness.SCRIPTS))
import brief_pack  # noqa: E402
import judge  # noqa: E402

TASK = "QA-9"
ROLES = {"qa-scout": "S1", "qa-requirements-tester": "S2", "qa-test-strategist": "S3", "qa-case-designer": "S4"}
ROLES.update({"qa-automator": "S5", "qa-code-critic": "S5"})                      # X7-1
# X7-3 adds its roles on its own line here (qa-runner S6, qa-failure-analyst S7)

# X7-4 adds its roles on its own line here (qa-bug-reporter S8, qa-doc-scribe S8, qa-retro-analyst S9)
KEYS = ["goal:", "DoD:", "given:", "owns:", "non-goals:", "handoff:", "questions:"]


@pytest.fixture
def world(tmp_path):
    """(project root, fake plugin 'scripts' dir) : a story fixture and a plugin copy with a synthetic charter for every role."""
    root = harness.temp_project("sd-head-")
    harness.use_project(root)
    seed(root, TASK)
    plugin = tmp_path / "plugin"
    (plugin / "scripts").mkdir(parents=True)
    (plugin / "agents").mkdir()
    for role in ROLES:
        (plugin / "agents" / f"{role}.md").write_text(charter_text(), encoding="utf-8")
    try:
        yield root, plugin / "scripts"
    finally:
        harness.cleanup(root)


def render(role: str, here: Path = None, stage: str = None) -> str:
    stage = stage or ROLES[role]
    with patch.object(judge, "active", return_value=False):
        if here is None:
            return brief_pack.build(TASK, stage, role, f"{stage}-{role}-1", write=False)["markdown"]
        with patch.object(brief_pack, "HERE", here):
            return brief_pack.build(TASK, stage, role, f"{stage}-{role}-1", write=False)["markdown"]


def head_of(text: str) -> list:
    return text.split("\n")[2:9]


@pytest.mark.parametrize("role", list(ROLES))
def test_seven_lines_sit_right_after_the_title(world, role):
    _, here = world
    lines = render(role, here).split("\n")
    assert lines[0].startswith("# Brief - ")
    assert [line.split(" ")[0] for line in lines[2:9]] == KEYS
    assert lines[9] == "" and lines[10].startswith("Scope: ")          # then one blank line, then the story head


def test_lines_carry_their_data(world):
    _, here = world
    s1 = {line.split(":")[0]: line for line in head_of(render("qa-scout", here))}
    assert s1["goal"] == "goal: - A line of text."                 # the body of the synthetic `## Outcome`
    assert s1["DoD"].startswith("DoD: Lead 1; Lead 2; Lead 3; Lead 4; witness: per item and the tried table, agents/qa-scout.md")
    assert "work/context-manifest.json" in s1["owns"] and "work/context-bundle.json" not in s1["owns"]   # code's artifact is not the role's
    assert "work/impl-diff.txt" in s1["owns"] and "work/handoffs/S1-qa-scout-1.yaml" in s1["owns"]
    assert "never edit application or test code" in s1["non-goals"]
    assert "unresolved_facts" in s1["questions"]


@pytest.mark.parametrize("role", list(ROLES))
def test_handoff_line_names_the_tried_table(world, role):
    _, here = world
    line = head_of(render(role, here))[5]
    assert line.startswith("handoff: `work/handoffs/") and "tried among them" in line and ".yaml`" in line


def test_given_names_the_snapshot_and_follows_the_file_list(world):
    _, here = world
    text = render("qa-scout", here)
    given = head_of(text)[2]
    assert given.startswith("given: ") and "work/ticket-snapshot.json" in given
    stage_def = brief_pack._stages()["S1"]
    for name in brief_pack._input_names(stage_def, "qa-scout", ""):
        assert name in given                                    # one formula: the `given:` line and the file list agree


def test_note_stays_first_after_the_title(world):
    _, here = world
    with patch.object(brief_pack, "SLICE_BYTES", 1500):
        lines = render("qa-scout", here).split("\n")
    assert lines[2].startswith("This brief is ") and "over the 30 KB whole-read limit" in lines[2]
    assert [line.split(" ")[0] for line in lines[4:11]] == KEYS


def test_empty_inputs_print_the_dash_and_the_reason(world, tmp_path):
    _, here = world
    (here.parent / "agents" / "qa-scout.md").write_text(charter_text().replace("## Outcome", "## Aim"), encoding="utf-8")
    lines = head_of(render("qa-scout", here))
    assert len(lines) == 7 and lines[0] == "goal: — (the charter has no Outcome section)"
    # a form with no row for the role: non-goals and questions print the dash and the reason
    with patch.object(brief_pack, "brief_form", return_value={"roles": {}, "order": ["goal", "DoD", "given", "owns", "non-goals", "handoff", "questions"],
                                                              "empty": json.loads((Path(brief_pack.HERE).parent / "references" / "brief-form.json").read_text(encoding="utf-8"))["empty"]}):
        lines = head_of(render("qa-test-strategist", here))
    assert lines[4] == "non-goals: — (the brief form names none for this role)"
    assert lines[6] == "questions: — (the brief form names no road for this role)"
    # an unreadable form: every line is still there, with the generic reason
    with patch.object(brief_pack, "brief_form", return_value={}):
        lines = head_of(render("qa-scout", here))
    assert [line.split(" ")[0] for line in lines] == KEYS and "could not be read" in lines[4]
    # a stage with no registered contract for the role
    with patch("handoff.contract_of", return_value=""):
        lines = head_of(render("qa-scout", here))
    assert lines[5] == "handoff: — (no handoff contract is registered for this stage and role)"
    # the five other lines are untouched by the three cases above
    assert all(line.split(" ")[0] in KEYS for line in lines)


@pytest.mark.parametrize("extra,cut", [(0, False), (1, True)])
def test_line_chars_at_and_beyond(extra, cut):
    form = {"line_chars": 300, "empty": {}}
    at = "a" * 300
    got = brief_pack._form_line("goal", at[:300 - 0] if not extra else at + "b" * extra, "agents/x.md ## Outcome", form)
    value = got[len("goal: "):]
    assert len(value) <= 300
    assert value.endswith(" ... (whole: agents/x.md ## Outcome)") is cut
    if not cut:
        assert value == at


def test_a_cut_value_keeps_its_suffix():
    form = {"line_chars": 120, "empty": {}}
    got = brief_pack._form_line("DoD", "x" * 400, "agents/x.md ## Good outcome", form, keep="; witness: the tried table")
    value = got[len("DoD: "):]
    assert len(value) <= 120 and value.endswith("(whole: agents/x.md ## Good outcome); witness: the tried table")


def build_of(role: str, here: Path = None, stage: str = None) -> dict:
    stage = stage or ROLES[role]
    with patch.object(judge, "active", return_value=False), patch.object(brief_pack, "HERE", here or brief_pack.HERE):
        return brief_pack.build(TASK, stage, role, f"{stage}-{role}-1", write=False)


def test_the_head_is_form_outside_the_body_budget(world):
    """t-1765 X1 fix-3 (lead decision a): the budget counts the body only. With the head or without it the body budget is
    the same number, while the brief is longer by exactly the head. Kills: `- sd_cost` removed from `budget_of`."""
    _, here = world
    with_head = build_of("qa-scout", here)
    with patch.object(brief_pack, "sd_head_lines", return_value=[]):
        without = build_of("qa-scout", here)
    head = brief_pack.head_bytes(with_head["markdown"].split("\n")[2:10])
    assert with_head["budget_bytes"] == without["budget_bytes"]
    assert with_head["bytes"] - without["bytes"] == head


def test_head_cap_at_and_beyond(world):
    """AT the cap the head is whole (all four DoD leads); one byte BEYOND it the DoD leads are cut first and the `tried` witness
    suffix stays. Kills: `>` changed to `>=` in the cut loop; the cut loop removed."""
    _, here = world
    whole = head_of(render("qa-scout", here))
    size = brief_pack.head_bytes(whole + [""])                        # the cap counts the blank line after the head too
    assert size <= brief_pack.SD_HEAD_MAX_BYTES                       # the shipped form fits its own cap
    with patch.object(brief_pack, "SD_HEAD_MAX_BYTES", size):
        at = head_of(render("qa-scout", here))
    assert at == whole
    with patch.object(brief_pack, "SD_HEAD_MAX_BYTES", size - 1):
        beyond = head_of(render("qa-scout", here))
    assert brief_pack.head_bytes(beyond + [""]) < size and beyond[1].startswith("DoD: Lead 1;")
    assert "Lead 4" not in beyond[1] and "witness: per item and the tried table" in beyond[1]
    assert [line.split(" ")[0] for line in beyond] == KEYS            # no line is lost, only leads


def test_head_cap_is_hard_given_names_then_the_marker(world):
    """t-1765 X1 fix-4 (F3): the cap is HARD. With one DoD lead left, one byte BEYOND the head cuts the `given` names (`... and N more`);
    below the shortest head the head is rendered with a last `head over cap` line, the brief says so in `over_ceiling`, and the bytes
    over the cap count against the body (never outside the budget). Kills: the `given` cut loop removed; `min(..., SD_HEAD_MAX_BYTES)`
    in `sd_cost` removed; the marker line removed."""
    _, here = world
    with patch.object(brief_pack, "SD_HEAD_MAX_BYTES", 1):          # nothing fits: every cut is taken
        floor_build = build_of("qa-scout", here)
    floor = floor_build["markdown"].split("\n")[2:11]
    assert [line.split(" ")[0] for line in floor[:7]] == KEYS
    assert floor[1].startswith("DoD: Lead 1;") and "Lead 2" not in floor[1]                  # one lead is the floor
    assert " ... and " in floor[2] and floor[2].endswith(" more")                           # the given names were cut
    assert floor[7].startswith("head: \u2014 (head over cap: ") and floor[7].endswith(" B)")   # the marker names the size
    size = brief_pack.head_bytes(floor[:7] + [""])
    assert f"head over cap: {size} B" in floor[7]
    assert "sd head" in floor_build["over_ceiling"]
    # the overflow is in the budget: with the cap at 1 B the whole head but 1 B is counted against the body
    with patch.object(brief_pack, "sd_head_lines", return_value=[]):
        without = build_of("qa-scout", here)
    assert floor_build["budget_bytes"] - without["budget_bytes"] >= size - 1
    # AT the floor size the marker is gone (the head fits) and `over_ceiling` does not name the head
    with patch.object(brief_pack, "SD_HEAD_MAX_BYTES", size):
        at = build_of("qa-scout", here)
    assert "head over cap" not in at["markdown"] and "sd head" not in at["over_ceiling"]
    with patch.object(brief_pack, "SD_HEAD_MAX_BYTES", size - 1):
        beyond = build_of("qa-scout", here)
    assert "head over cap" in beyond["markdown"] and "sd head" in beyond["over_ceiling"]
    # the negative control: the shipped cap leaves the head whole, no marker
    whole = build_of("qa-scout", here)
    assert "head over cap" not in whole["markdown"] and "sd head" not in whole["over_ceiling"]
    assert whole["budget_bytes"] == without["budget_bytes"]


if __name__ == "__main__": raise SystemExit(pytest.main([__file__, "-q", "-p", "no:cacheprovider"]))
