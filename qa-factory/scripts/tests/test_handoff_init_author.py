"""t-1936 F1 (B-2, B-11): the stage critic's form skeleton - the author's path filled by code, optional lists emptied in the role's copy.

Run: `python -B -m pytest <this file> -q`. Fast: no controller, no subprocess; the controller state is a stub.
"""
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))
import handoff  # noqa: E402
import handoff_check  # noqa: E402
import handoff_init  # noqa: E402

CRITIC_CONTRACTS = ("s2-stage-critic-to-tester", "s3-stage-critic-to-strategist", "s4-case-critic-to-designer")
S5_CONTRACTS = ("s5-critic-to-automator", "s5-critic-plan-to-automator")
TOKEN = "<the author's dispatch>"
AUTHOR = "S2-qa-requirements-tester-3"


def contract_text(name: str) -> str:
    return (handoff.CONTRACTS / f"{name}.yaml").read_text(encoding="utf-8")


def head(name: str, **over) -> str:
    kw = dict(task="QA-1", dispatch="S2-qa-case-critic-1", role="qa-case-critic", stage="S2", scope="R-1")
    kw.update(over)
    return handoff_init.fill_head(contract_text(name), **kw)


@pytest.mark.parametrize("name", CRITIC_CONTRACTS)
def test_author_token_filled_s2_s3_s4(name):
    text = head(name, author_dispatch=AUTHOR)
    doc = handoff.parse(text)
    assert TOKEN not in text
    assert doc.get("inputs[0].path") == f"work/handoffs/{AUTHOR}.yaml"
    assert doc.get("inputs_read[0].path") == f"work/handoffs/{AUTHOR}.yaml"
    assert handoff.is_placeholder(doc.get("inputs_read[1].path")), "the second row keeps the template for the other inputs"


def test_author_comment_line_written_when_filled():
    text = head("s2-stage-critic-to-tester", author_dispatch=AUTHOR)
    lines = text.splitlines()
    at = lines.index("inputs_read:")
    assert lines[at - 1] == handoff_init.AUTHOR_NOTE
    assert "change it if you reviewed another" in lines[at - 1]
    assert "inputs_read[0] names the author's form" in text


@pytest.mark.parametrize("name", CRITIC_CONTRACTS)
def test_author_token_left_when_unknown(name):
    text = head(name, author_dispatch="")
    assert TOKEN in text, "a guessed author never stands in a form"
    assert handoff_init.AUTHOR_NOTE not in text


@pytest.mark.parametrize("name", S5_CONTRACTS)
def test_s5_contracts_get_no_author_arg(name, monkeypatch):
    import story_step
    assert TOKEN not in contract_text(name)
    monkeypatch.setattr("acceptance.stage_author_dispatch", lambda state, stage_def: AUTHOR)
    assert story_step._author_argv("S5", "qa-code-critic", name, Path(".")) == []


def test_no_author_arg_without_token(monkeypatch):
    import story_step
    monkeypatch.setattr("acceptance.stage_author_dispatch", lambda state, stage_def: AUTHOR)
    assert TOKEN not in contract_text("s6-runner-to-analyst")
    assert story_step._author_argv("S6", "qa-runner", "s6-runner-to-analyst", Path(".")) == []


def test_author_arg_given_when_token_and_known(monkeypatch, tmp_path):
    import controller
    import story_step

    class Stub:
        def __init__(self, root):
            pass

        def state(self):
            return {}
    monkeypatch.setattr(controller, "Controller", Stub)
    monkeypatch.setattr("acceptance.stage_author_dispatch", lambda state, stage_def: AUTHOR)
    assert story_step._author_argv("S2", "qa-case-critic", "s2-stage-critic-to-tester", tmp_path) == ["--author-dispatch", AUTHOR]
    monkeypatch.setattr("acceptance.stage_author_dispatch", lambda state, stage_def: "")
    assert story_step._author_argv("S2", "qa-case-critic", "s2-stage-critic-to-tester", tmp_path) == []
    monkeypatch.setattr(controller, "Controller", lambda root: (_ for _ in ()).throw(OSError("no state")))
    assert story_step._author_argv("S2", "qa-case-critic", "s2-stage-critic-to-tester", tmp_path) == [], "an unreadable state is an unknown author"


def skeleton(name: str, **over) -> str:
    return handoff_init.empty_optional_lists(head(name, **over), name)


@pytest.mark.parametrize("name", CRITIC_CONTRACTS)
def test_empty_optional_lists_questions_findings(name):
    text = skeleton(name)
    doc = handoff.parse(text)
    assert doc.data.get("questions") == [] and doc.data.get("findings") == []
    assert "questions: []" in text and "findings: []" in text
    assert '#   - question: "<' in text, "the sample row stays as a comment"
    assert "#   - id: <F-n>" in text


def test_empty_findings_s5():
    """`s5-critic-to-automator` has `findings`; the plan contract has `remarks` instead and is left as it is."""
    doc = handoff.parse(skeleton("s5-critic-to-automator", role="qa-code-critic", stage="S5"))
    assert doc.data.get("findings") == []
    plan = skeleton("s5-critic-plan-to-automator", role="qa-code-critic", stage="S5")
    assert handoff.parse(plan).data.get("remarks") == handoff.parse(head("s5-critic-plan-to-automator")).data.get("remarks")


def test_scope_never_emptied():
    for name in CRITIC_CONTRACTS + S5_CONTRACTS:
        doc = handoff.parse(skeleton(name))
        rows = doc.data.get("scope")
        assert isinstance(rows, list) and rows, f"{name}: the required list scope keeps its template row"


def test_carry_survives_emptying():
    text = head("s2-stage-critic-to-tester")
    doc = handoff.parse(text)
    handoff.set_value(doc, "findings[0].problem", "the limit is missing")
    out = handoff_init.empty_optional_lists(doc.text(), "s2-stage-critic-to-tester")
    parsed = handoff.parse(out)
    assert parsed.get("findings[0].problem") == "the limit is missing", "a row with a real value is never emptied"
    assert parsed.data.get("questions") == [], "the other untouched section is still emptied"


def test_unknown_contract_text_unchanged():
    text = head("s2-stage-critic-to-tester")
    assert handoff_init.empty_optional_lists(text, "s6-runner-to-analyst") == text


EMPTIED_PATHS = ("questions", "findings")


def verdicts(name: str, text: str, root: Path, verdict: str = "") -> list:
    doc = handoff.parse(text)
    if verdict:
        handoff.set_value(doc, "header.verdict", verdict)
        doc = handoff.parse(doc.text())
    problems = handoff_check.check(doc, name, handoff_check.Artifacts(root))[2]
    return sorted((p.path, p.text, p.fix) for p in problems)


@pytest.mark.parametrize("verdict", ["", "ok", "concerns"])
@pytest.mark.parametrize("name", CRITIC_CONTRACTS + S5_CONTRACTS)
def test_check_verdict_unchanged_by_emptying(name, verdict, tmp_path):
    """Every problem outside the emptied sections is byte-identical before and after (the required `scope` is still refused as
    'no rows'); inside them the only difference is that the untouched SAMPLE rows no longer read as 'not filled' (they are not rows)."""
    before = head(name)
    after = handoff_init.empty_optional_lists(before, name)
    old, new = verdicts(name, before, tmp_path, verdict), verdicts(name, after, tmp_path, verdict)
    outside = lambda rows: [r for r in rows if not r[0].startswith(EMPTIED_PATHS)]
    assert outside(old) == outside(new)
    # `rows_owed_when` (FU1: S2-S4 and the S5 critic; the plan critic does not carry it): a send-back owes findings rows,
    # so its emptied `findings` is refused as 'no rows'.
    owed = ["findings"] if verdict == "concerns" and name != "s5-critic-plan-to-automator" else []
    assert [r[0] for r in new if r[0].startswith(EMPTIED_PATHS)] == owed, "an emptied section raises no problem of its own"
    assert any(r[0] == "scope" for r in new) or not any(r[0] == "scope" for r in old), "the required list is still refused"


def test_values_row_opens_in_emptied_section():
    name = "s2-stage-critic-to-tester"
    doc = handoff.parse(skeleton(name))
    out, applied, problems, _notes = handoff_check.apply_values(doc, name, [("questions[0].question", "Is it 100?", 0, "")])
    assert not problems and applied == 1
    assert handoff.parse(out.text()).get("questions[0].question") == "Is it 100?"


def test_second_row_without_first_refused_in_emptied_section():
    name = "s2-stage-critic-to-tester"
    doc = handoff.parse(skeleton(name))
    out, applied, problems, _notes = handoff_check.apply_values(doc, name, [("questions[1].question", "Is it 100?", 0, "")])
    assert applied == 0 and problems
    assert "questions[0]" in " ".join(f"{p.path} {p.text} {p.fix}" for p in problems)


# TR4-12 (2): the consumer forms (S7 analyst reviews the runner's S6 dispatch, S8 scribe reviews the analyst's S7 dispatch) get the
# reviewed dispatch's path from code, by the one reader the brief line uses (`brief_pack.reviewed_dispatch_id`).
CONSUMERS = (("S7", "qa-failure-analyst", "s7-analyst-to-scribe", "S6-qa-runner-2"),
             ("S8", "qa-doc-scribe", "s8-scribe-to-gate-b", "S7-qa-failure-analyst-1"))


@pytest.mark.parametrize("stage,role,name,author", CONSUMERS)
def test_consumer_form_prefilled_when_id_known(stage, role, name, author):
    text = head(name, role=role, stage=stage, author_dispatch=author)
    doc = handoff.parse(text)
    assert TOKEN not in text
    assert doc.get("inputs_read[0].path") == f"work/handoffs/{author}.yaml"
    assert handoff_init.AUTHOR_NOTE in text


@pytest.mark.parametrize("stage,role,name,author", CONSUMERS)
def test_consumer_form_keeps_placeholder_when_no_id(stage, role, name, author):
    text = head(name, role=role, stage=stage, author_dispatch="")
    assert TOKEN in text and handoff_init.AUTHOR_NOTE not in text
    assert handoff.parse(text).get("inputs_read[0].path") == f"work/handoffs/{TOKEN}.yaml"


@pytest.mark.parametrize("stage,role,name,author", CONSUMERS)
def test_consumer_author_argv_uses_the_brief_reader(stage, role, name, author, monkeypatch, tmp_path):
    import controller
    import story_step

    class Stub:
        def __init__(self, root):
            pass

        def state(self):
            return {}
    monkeypatch.setattr(controller, "Controller", Stub)
    monkeypatch.setattr("acceptance.awaits_acceptance", lambda state, stage_, pipeline=None, table=None: author)
    assert story_step._author_argv(stage, role, name, tmp_path) == ["--author-dispatch", author]
    monkeypatch.setattr("acceptance.awaits_acceptance", lambda state, stage_, pipeline=None, table=None: "")
    assert story_step._author_argv(stage, role, name, tmp_path) == [], "nothing awaits the consumer: the token stays"


@pytest.mark.parametrize("stage,role,name,author", CONSUMERS)
def test_consumer_existing_form_is_untouched(stage, role, name, author, monkeypatch, tmp_path):
    out = tmp_path / "form.yaml"
    out.write_text("the role's own words\n", encoding="utf-8")
    monkeypatch.setattr(handoff_init, "task_root", lambda task, root=None: tmp_path)
    monkeypatch.setattr(sys, "argv", ["handoff_init.py", "--task", "QA-1", "--stage", stage, "--role", role,
                                      "--out", str(out), "--author-dispatch", author])
    assert handoff_init.main() == 0
    assert out.read_text(encoding="utf-8") == "the role's own words\n"


@pytest.mark.parametrize("stage,role,name,author", CONSUMERS)
def test_bom_pipeline_brief_and_prefill_name_the_same_dispatch(stage, role, name, author, monkeypatch, tmp_path):
    """A pipeline.json with a BOM is read by the prefill as the brief reads it (utf-8-sig): both see the same pipeline."""
    import brief_pack
    import controller
    import story_step

    class Stub:
        def __init__(self, root):
            pass

        def state(self):
            return {}
    monkeypatch.setattr(controller, "Controller", Stub)
    (tmp_path / "pipeline.json").write_bytes(b"\xef\xbb\xbf" + b'{"acceptance_awaits": "yes"}')
    monkeypatch.setattr("acceptance.awaits_acceptance",
                        lambda state, stage_, pipeline=None, table=None: author if (pipeline or {}).get("acceptance_awaits") else "")
    assert brief_pack.reviewed_dispatch_id(stage, role, {}, brief_pack._load(tmp_path / "pipeline.json")) == author
    assert story_step._author_argv(stage, role, name, tmp_path) == ["--author-dispatch", author]


def test_brief_line_and_prefill_name_the_same_dispatch(monkeypatch):
    import brief_pack
    monkeypatch.setattr("acceptance.awaits_acceptance", lambda state, stage_, pipeline=None, table=None: "S6-qa-runner-2")
    assert brief_pack.reviewed_dispatch_id("S7", "qa-failure-analyst", {}, {}) == "S6-qa-runner-2"
    lines = brief_pack.reviewed_dispatch_lines("S7", "qa-failure-analyst", {}, {})
    assert lines and "work/handoffs/S6-qa-runner-2.yaml" in lines[0]
    monkeypatch.setattr("acceptance.awaits_acceptance", lambda state, stage_, pipeline=None, table=None: "")
    assert brief_pack.reviewed_dispatch_id("S7", "qa-failure-analyst", {}, {}) == ""
    assert brief_pack.reviewed_dispatch_lines("S7", "qa-failure-analyst", {}, {}) == []


if __name__ == "__main__": raise SystemExit(pytest.main([__file__, "-q", "-p", "no:cacheprovider"]))
