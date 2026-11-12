"""TR4-1 (t-2145): the stage critic's form names the dispatch it reviewed, and the role learns that BEFORE the work.

`stage_done.record_acceptance` refuses a critic form with no `inputs_read` row naming an author dispatch (the refusal names the value to
write and who acts); the brief of the role (`brief_pack.reviewed_dispatch_lines`, the `Reviewed dispatch:` line) carries that value.
Run: `python -B -m pytest <this file> -q`. Fast: a temp story, no subprocess.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_controller_stage_acceptance as T  # noqa: E402  (story, dispatch, Patched, quiet, FORM)
from harness import SCRIPTS, cleanup  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import brief_pack  # noqa: E402
import hooklib  # noqa: E402
import stage_done  # noqa: E402

NO_PATH = ("inputs_read:\n  - path: work/requirements-register.md\n    version: abc\n"
           "header:\n  role: qa-case-critic\n  stage: S2\n  window_or_scope: S2\n  verdict: approve\n")


@pytest.fixture()
def world():
    old = hooklib._PROJECT_ROOT_CACHE
    root, task, c = T.story()
    hooklib._PROJECT_ROOT_CACHE = root
    (task / "work" / "handoffs").mkdir(parents=True)
    try:
        with T.Patched():
            yield task, c
    finally:
        hooklib._PROJECT_ROOT_CACHE = old
        cleanup(root)


def write_form(task, text):
    (task / "work" / "handoffs" / "dC.yaml").write_text(text, encoding="utf-8")


def test_form_without_the_path_is_refused_and_names_the_value(world):
    task, c = world
    T.accept(c, T.dispatch(c, task, "dA", T.AUTHOR), False)
    T.dispatch(c, task, "dC", T.CRITIC)
    write_form(task, NO_PATH)
    code, said = T.quiet(stage_done.record_acceptance, "QA-1", "S2", "work/handoffs/dC.yaml")
    assert code == 2
    assert "does not say which dispatch of qa-requirements-tester it reviewed" in said
    assert "path: work/handoffs/dA.yaml" in said and "Reviewed dispatch:" in said      # the value to write, and where the brief names it


def test_no_author_dispatch_refusal_names_who_acts(world):
    task, c = world
    T.dispatch(c, task, "dC", T.CRITIC)
    write_form(task, NO_PATH)
    code, said = T.quiet(stage_done.record_acceptance, "QA-1", "S2", "work/handoffs/dC.yaml")
    assert code == 2
    assert "no accepted dispatch of qa-requirements-tester exists at S2 yet" in said
    assert "the conductor dispatches qa-requirements-tester first" in said


def two_forms(first: str, second: str) -> str:
    nl = chr(10)
    row = "  - path: work/handoffs/{}.yaml" + nl + "    version: abc" + nl
    return "inputs_read:" + nl + row.format(first) + row.format(second) + T.FORM.split("version: abc" + nl, 1)[1].format(word="approve", failure="null")


def test_named_dispatch_not_last_is_refused_and_the_refusal_says_which_row_counts(world):
    task, c = world
    T.accept(c, T.dispatch(c, task, "dA", T.AUTHOR), False)
    T.accept(c, T.dispatch(c, task, "dA2", T.AUTHOR), False)
    T.dispatch(c, task, "dC", T.CRITIC)
    write_form(task, two_forms("dA2", "dA"))                  # the named one first, an older one last: the last row counts
    code, said = T.quiet(stage_done.record_acceptance, "QA-1", "S2", "work/handoffs/dC.yaml")
    assert code == 2
    assert stage_done.reviewed_row_rule("dA2", T.AUTHOR) in said
    assert "the last row of the form that names a dispatch of qa-requirements-tester is 'dA'" in said


def test_named_dispatch_last_is_taken(world):
    task, c = world
    T.accept(c, T.dispatch(c, task, "dA", T.AUTHOR), False)
    T.accept(c, T.dispatch(c, task, "dA2", T.AUTHOR), False)
    T.dispatch(c, task, "dC", T.CRITIC)
    write_form(task, two_forms("dA", "dA2"))
    code, said = T.quiet(stage_done.record_acceptance, "QA-1", "S2", "work/handoffs/dC.yaml")
    assert code == 0, said


def test_following_the_refusal_literally_ends_in_an_accepted_form(world):
    task, c = world
    T.accept(c, T.dispatch(c, task, "dA", T.AUTHOR), False)
    T.accept(c, T.dispatch(c, task, "dA2", T.AUTHOR), False)
    T.dispatch(c, task, "dC", T.CRITIC)
    write_form(task, two_forms("dA2", "dA"))
    code, said = T.quiet(stage_done.record_acceptance, "QA-1", "S2", "work/handoffs/dC.yaml")
    assert code == 2
    # the refusal's door: the named path as the LAST row, the other form above it
    write_form(task, two_forms("dA", "dA2"))
    code, said = T.quiet(stage_done.record_acceptance, "QA-1", "S2", "work/handoffs/dC.yaml")
    assert code == 0, said


def test_s7_template_comment_says_the_rule_in_the_same_words():
    # the s8 template carries no such line: the scribe's role-load process ratchet has slack 0 (see the report, Round 2)
    text = (SCRIPTS.parent / "handoffs" / "s7-analyst-to-scribe.yaml").read_text(encoding="utf-8")
    assert stage_done.reviewed_row_rule("<the runner's dispatch>", "qa-runner") in text


def test_form_with_the_path_is_taken(world):
    task, c = world
    T.accept(c, T.dispatch(c, task, "dA", T.AUTHOR), False)
    T.dispatch(c, task, "dC", T.CRITIC)
    write_form(task, T.FORM.format(reviewed="dA", word="approve", failure="null"))
    code, _ = T.quiet(stage_done.record_acceptance, "QA-1", "S2", "work/handoffs/dC.yaml")
    assert code == 0


def test_brief_line_carries_the_path_substituted_for_the_story(world):
    # the line `build` puts in the head (`head += reviewed_dispatch_lines(...)`); `brief_pack.build` itself measured ~20 min per call on
    # this fixture, so the unit is driven on the real controller state of the story, not through a whole brief
    task, c = world
    T.accept(c, T.dispatch(c, task, "dA", T.AUTHOR), False)
    T.dispatch(c, task, "dC", T.CRITIC)
    lines = brief_pack.reviewed_dispatch_lines("S2", T.CRITIC, c.state(), {})
    assert len(lines) == 1
    assert lines[0] == f"Reviewed dispatch: {stage_done.reviewed_row_rule('dA', T.AUTHOR)}."      # the one wording, no second copy


def test_brief_line_without_an_author_dispatch_says_so(world):
    task, c = world
    T.dispatch(c, task, "dC", T.CRITIC)
    lines = brief_pack.reviewed_dispatch_lines("S2", T.CRITIC, c.state(), {})
    assert len(lines) == 1
    assert "none yet - no accepted dispatch of qa-requirements-tester exists at S2" in lines[0]
    assert "path: work/handoffs/" not in lines[0]      # never an empty or guessed value


def test_build_places_the_line_in_the_head():
    src = (SCRIPTS / "brief_pack.py").read_text(encoding="utf-8")
    assert "head += reviewed_dispatch_lines(stage, role, controller, pipeline)" in src


def test_several_author_dispatches_name_the_last_accepted_one(world):
    task, c = world
    T.accept(c, T.dispatch(c, task, "dA", T.AUTHOR), False)
    T.accept(c, T.dispatch(c, task, "dA2", T.AUTHOR), False)       # a rework round
    state = c.state()
    lines = brief_pack.reviewed_dispatch_lines("S2", T.CRITIC, state, {})
    assert len(lines) == 1 and "work/handoffs/dA2.yaml" in lines[0] and "dA.yaml" not in lines[0]


def test_roles_that_review_nothing_get_no_line(world):
    task, c = world
    state = c.state()
    assert brief_pack.reviewed_dispatch_lines("S2", T.AUTHOR, state, {}) == []
    assert brief_pack.reviewed_dispatch_lines("S7", "qa-failure-analyst", state, {}) == []      # nothing awaits its acceptance


def test_consumer_with_an_accepted_runner_nothing_awaiting_gets_no_line(world):
    # kills swapping `awaits_acceptance` for `stage_author_dispatch` in the consumer branch: the runner is accepted, but no word awaits
    task, c = world
    state = {"dispatches": {"S6-qa-runner-13": {"id": "S6-qa-runner-13", "stage": "S6", "role": "qa-runner", "status": "accepted"}},
             "stages": {"S6": {"status": "running"}}}
    assert brief_pack.reviewed_dispatch_lines("S7", "qa-failure-analyst", state, {}) == []


def test_consumer_analyst_gets_the_runner_row(world):
    task, c = world
    state = {"dispatches": {"S6-qa-runner-13": {"id": "S6-qa-runner-13", "stage": "S6", "role": "qa-runner", "status": "accepted",
                                                 "unresolved": [{"reason": "stage_awaits_acceptance"}]}},
             "stages": {"S6": {"status": "running"}}}
    pipeline = {"acceptance_awaits": {"S6": "S6-qa-runner-13"}}
    lines = brief_pack.reviewed_dispatch_lines("S7", "qa-failure-analyst", state, pipeline)
    assert len(lines) == 1 and "path: work/handoffs/S6-qa-runner-13.yaml" in lines[0]


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-q", "-p", "no:cacheprovider"]))
