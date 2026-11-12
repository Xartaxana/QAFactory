"""Open vocabularies of S2-S4 (spec t-1765 X2-4 and the handoff part of X2-3, decision F-3 (b)).

A proposed list: a word of it passes, `new: <word> -- <why>` passes the form and is judged by the stage critic, anything else
is refused with that door. `code` as a Then oracle has NO door (P20, FR-58). The judge of `handoff_check` only advises.

Plain asserts, so `python -B -m pytest scripts/tests/test_open_vocabularies.py -q -p no:cacheprovider` is the witness.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from harness import PLUGIN_ROOT  # noqa: E402

sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))
import check_witness as CW  # noqa: E402
import contract as C  # noqa: E402
import grammar as G  # noqa: E402
import handoff as H  # noqa: E402
import handoff_check as HC  # noqa: E402
import validate_artifacts as VA  # noqa: E402

WORDS = ["boundary", "state", "seam"]
REASON = "two writers of one row"          # 22 characters


def door(value, vocabulary="defect_class", words=WORDS, **kw):
    return C.open_word_errors(value, words, vocabulary, **kw)


# --- the door: contract.open_word_errors -----------------------------------------------------------------------------

def test_a_word_of_the_list_passes():
    assert door("seam") == []


def test_the_door_with_a_word_and_a_reason_passes():
    assert door(f"new: seam-race -- {REASON}") == []


@pytest.mark.parametrize("value", ["new: x -- y", "new: x -- " + REASON])
def test_a_one_character_word_is_refused(value):
    assert door(value), value


def test_the_reason_boundary_is_ten_characters():
    assert door("new: seam-race -- " + "r" * 9) != []
    assert door("new: seam-race -- " + "r" * 10) == []


def test_the_word_boundary_is_forty_characters():
    word = "a" + "b" * 39
    assert len(word) == 40 and door(f"new: {word} -- {REASON}") == []          # AT the limit
    assert door(f"new: {word}b -- {REASON}") != []                              # BEYOND it (41)
    assert door(f"new: ab -- {REASON}") == []                                   # the other end: two characters
    assert door(f"new: a -- {REASON}") != []


@pytest.mark.parametrize("value", ["new: seam-race", "new: seam-race --", "new: seam-race -- ", "new:", "new: -- " + REASON,
                                   "new: seam-race --" + REASON])
def test_a_door_without_a_reason_or_a_word_is_refused_as_form(value):
    assert door(value), value


def test_a_word_outside_the_list_without_the_door_is_refused_naming_the_door():
    problems = door("vibes")
    assert len(problems) == 1 and "new: <word> -- <why>" in problems[0] and "seam" in problems[0]
    assert door("") and door(None)


@pytest.mark.parametrize("value", ["new: Seam -- " + REASON, "new: se am -- " + REASON, "new: 1seam -- " + REASON,
                                   "NEW: seam-race -- " + REASON])
def test_a_word_of_the_wrong_shape_is_refused(value):
    assert door(value), value


# --- `code` has no door -----------------------------------------------------------------------------------------------

ORACLES = ("requirement", "ac", "spec", "precedent", "person", "unknown")


@pytest.mark.parametrize("value", ["code", "Code", "new: code -- read it from the diff", "new: Code -- read it from the diff",
                                   "new: CODE -- read it from the diff"])
def test_code_is_refused_always_as_an_oracle(value):
    problems = door(value, "then_oracle", ORACLES)
    assert len(problems) == 1 and "never" in problems[0], problems


def test_the_never_branch_is_not_the_shape_branch():
    lower = door("new: code -- read it from the diff", "then_oracle", ORACLES)[0]
    upper = door("new: Code -- read it from the diff", "then_oracle", ORACLES)[0]
    shaped = door("new: Seam -- read it from the diff", "then_oracle", ORACLES)[0]
    assert "never" in lower and "never" in upper and "never" not in shaped and "must match" in shaped


def test_code_is_not_banned_in_a_list_that_has_no_such_ban():
    assert door("new: code -- the name of a class of defects") == []


def test_the_floor_ban_holds_when_the_data_file_loses_it(monkeypatch, tmp_path):
    bare = tmp_path / "open-vocabularies.json"
    data = json.loads(C.OPEN_VOCABULARIES_PATH.read_text(encoding="utf-8"))
    data["vocabularies"]["then_oracle"].pop("never")
    bare.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(C, "OPEN_VOCABULARIES_PATH", bare)
    errors = C.then_oracle_errors("TC.md", '[{"then": 1, "source": "new: code -- read from the diff", "ref": "R-1"}]',
                                  None, [1], known_r={"R-1"})
    assert errors and "never" in errors[0]


# --- the data file ------------------------------------------------------------------------------------------------------

def test_the_file_is_missing_a_word_outside_the_list_is_unreadable_not_a_pass(monkeypatch, tmp_path):
    monkeypatch.setattr(C, "OPEN_VOCABULARIES_PATH", tmp_path / "absent.json")
    problems = door(f"new: seam-race -- {REASON}")
    assert len(problems) == 1 and "unreadable" in problems[0]
    assert door("seam") == []                                    # a word of the list needs no file
    assert "never" in door("code", "then_oracle", ORACLES, never=("code",))[0]


def test_the_file_is_broken_json(monkeypatch, tmp_path):
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(C, "OPEN_VOCABULARIES_PATH", broken)
    assert "unreadable" in door(f"new: seam-race -- {REASON}")[0]


def test_an_unknown_vocabulary_is_unreadable_not_a_pass():
    assert "unreadable" in door(f"new: seam-race -- {REASON}", "no_such_list")[0]


def test_a_closed_vocabulary_has_no_door():
    problems = door(f"new: seam-race -- {REASON}", "fit")
    assert len(problems) == 1 and "closed" in problems[0]
    assert door("seam", "fit") == []


def test_the_shipped_file_names_what_the_spec_names():
    data = json.loads(C.OPEN_VOCABULARIES_PATH.read_text(encoding="utf-8"))
    assert data["door"]["prefix"] == "new:" and data["door"]["separator"] == " -- " and data["door"]["min_reason_chars"] == 10
    assert data["vocabularies"]["then_oracle"]["never"] == ["code"]
    assert data["vocabularies"]["s2_verdict"]["words"] == ["ready", "blocked"]
    assert data["vocabularies"]["fit"]["open"] is False
    assert set(data["vocabularies"]["s2_verdict"]) == {"open", "words"}                  # M5: a field no code reads is not there


# --- then_oracles ------------------------------------------------------------------------------------------------------

def oracles(source, ref="R-1", **kw):
    raw = json.dumps([{"then": 1, "source": source, "ref": ref}])
    return C.then_oracle_errors("TC.md", raw, None, [1], **kw)


def test_a_word_of_the_oracle_list_passes_as_before():
    assert oracles("requirement", known_r={"R-1"}, impl_only=set()) == []


def test_a_new_oracle_word_with_a_register_requirement_passes():
    assert oracles(f"new: contract-doc -- {REASON}", known_r={"R-1"}, impl_only=set()) == []


def test_a_new_oracle_word_gets_the_strictest_ref_rule():
    only_code = oracles(f"new: implementation -- {REASON}", known_r={"R-1"}, impl_only={"R-1"})
    assert len(only_code) == 1 and "implementation-only" in only_code[0]                 # the critic rejects the WORD; the ref holds
    assert "not in the register" in oracles(f"new: contract-doc -- {REASON}", known_r={"R-2"})[0]
    assert "needs the question id" in oracles(f"new: contract-doc -- {REASON}", ref="")[0]


def test_a_new_oracle_word_may_name_a_question_of_the_register():
    asked = {"Q-1": {"status": "answered"}}
    assert oracles(f"new: person-note -- {REASON}", ref="Q-1", questions=asked) == []
    assert "not in `open_questions`" in oracles(f"new: person-note -- {REASON}", ref="Q-9", questions=asked)[0]
    assert "missing or unreadable" in oracles(f"new: person-note -- {REASON}", ref="Q-1", questions=None)[0]


@pytest.mark.parametrize("source", ["code", "new: code -- read it from the diff", "new: Code -- read it from the diff"])
def test_code_is_refused_as_a_then_oracle_in_every_spelling(source):
    errors = oracles(source, known_r={"R-1"}, impl_only=set())
    assert len(errors) == 1 and "never" in errors[0] and "`code` is never an oracle" in errors[0], errors


def test_a_new_oracle_word_without_a_reason_is_a_form_problem():
    assert oracles("new: contract-doc --", known_r={"R-1"})
    assert oracles("new: contract-doc", known_r={"R-1"})


# --- defect_class: grammar, case, plans -------------------------------------------------------------------------------

def test_the_defect_class_pattern_carries_the_door_and_the_place():
    plain = G.DEFECT_CLASS_RE.match("state @ subscription.end_date")
    assert plain.group("cls") == "state" and plain.group("new") is None
    reg = G.DEFECT_CLASS_RE.match("regression:BUG-12 @ checkout")
    assert reg.group("cls") == "regression:BUG-12"
    new = G.DEFECT_CLASS_RE.match(f"new: seam-race -- {REASON} @ checkout")
    assert new.group("cls") is None and new.group("new") == f"new: seam-race -- {REASON}"
    assert not G.DEFECT_CLASS_RE.match(f"new: seam-race -- {REASON}")                    # no `@ <place>`: not a class cell
    assert G.negative_outcome(new.group("new")) is None                                    # an unknown class answers None


CASE = ("---\nid: TC-001\ntitle: t\narea: api\npriority: P2\nstatus: Draft\nchannel: auto\nreuse_decision: new\n"
        "updated: 2026-09-20\ntask: QA-26\ncovers: [R-1]\ndefect_class: {klass}\nbasis: requirement:R-1\n---\nbody\n")


def case_errors(tmp_path, klass):
    case = tmp_path / "TC-001.md"
    case.write_text(CASE.format(klass=klass), encoding="utf-8")
    errors: list = []
    VA.check_case(case, errors)
    return [e for e in errors if "defect_class" in e]


def test_a_case_may_carry_a_new_class(tmp_path):
    assert case_errors(tmp_path, "seam") == []
    assert case_errors(tmp_path, f"new: seam-race -- {REASON}") == []


def test_a_case_with_an_unknown_class_or_a_bad_door_is_refused_with_the_door(tmp_path):
    outside = case_errors(tmp_path, "regression")
    assert len(outside) == 1 and "defect_class 'regression'" in outside[0] and "new: <word> -- <why>" in outside[0]
    assert case_errors(tmp_path, "new: seam-race --")
    assert case_errors(tmp_path, "new: x -- " + REASON)


PLAN_V1 = ("---\ntask: QA-26\ncreated: 2026-09-20\nscenarios_total: 1\nsmoke: 0\nby_defect_class: {{}}\nby_priority: {{}}\n"
           "requirements_total: 1\n---\n\n## Scenarios\n\n| TS | R | what can go wrong | impact | priority | experiment | observation | basis |\n"
           "|---|---|---|---|---|---|---|---|\n| TS-1 | R-1 | {risk} | degraded | P2 | e | an independent channel | requirement:R-1 |\n")


def plan_errors(tmp_path, risk):
    plan = tmp_path / "test-plan.md"
    plan.write_text(PLAN_V1.format(risk=risk), encoding="utf-8")
    errors: list = []
    VA.check_plan(plan, errors)
    return [e for e in errors if "what can go wrong" in e]


def test_a_plan_row_may_carry_a_new_class(tmp_path):
    assert plan_errors(tmp_path, "seam @ the checkout") == []
    assert plan_errors(tmp_path, f"new: seam-race -- {REASON} @ the checkout") == []


def test_a_plan_row_with_a_bad_door_or_an_unknown_class_is_refused(tmp_path):
    unknown = plan_errors(tmp_path, "vibes @ the checkout")
    assert len(unknown) == 1 and "new: <word> -- <why> @ <place>" in unknown[0]
    assert plan_errors(tmp_path, "new: x -- y @ the checkout")
    assert plan_errors(tmp_path, "new: seam-race @ the checkout")


PLAN_V0 = ("---\ntask: QA-26\ncreated: 2026-09-20\n---\n\n# Test plan\n\n## Plan\n\n"
           "| TS | what we verify | R | defect hypothesis | impact class | priority | observable | oracle | disposition + reason | fit | level |\n"
           "|---|---|---|---|---|---|---|---|---|---|---|\n"
           "| TS-1 | versioning is unchanged | R-1 | {klass} | degraded | P2 | diff:src/a.py:1 | requirement:R-1 | `automate` — main path | new | api |\n")


def plan_v0_errors(tmp_path, klass):
    root = tmp_path / "qa-factory" / "artifacts" / "QA-26"
    root.mkdir(parents=True, exist_ok=True)
    plan = root / "test-plan.md"
    plan.write_text(PLAN_V0.format(klass=klass), encoding="utf-8")
    errors: list = []
    VA.check_plan_v0(plan, errors)
    return [e for e in errors if "defect hypothesis" in e]


def test_a_v0_plan_row_may_carry_a_new_class(tmp_path):
    assert plan_v0_errors(tmp_path, "seam @ the checkout") == []
    assert plan_v0_errors(tmp_path, f"new: seam-race -- {REASON} @ the checkout") == []


def test_a_v0_plan_row_with_a_bad_door_or_an_unknown_class_is_refused(tmp_path):
    unknown = plan_v0_errors(tmp_path, "regression @ the checkout")
    assert len(unknown) == 1 and "regression:BUG-NNN" in unknown[0] and "new: <word> -- <why> @ <place>" in unknown[0]
    assert plan_v0_errors(tmp_path, "new: x -- y @ the checkout")
    assert plan_v0_errors(tmp_path, "new: seam-race @ the checkout")


# --- the S2 verdict ----------------------------------------------------------------------------------------------------

def readiness(verdict, open_questions=None):
    return {"verdict": verdict, "goal_summary": "the goal in my own words, long enough to pass",
            "aspects": {"a": {"status": "ready"}}, "open_questions": open_questions or []}


def test_the_two_verdict_words_pass_the_form():
    assert CW._readiness_form(readiness("ready")) == [] and CW._readiness_form(readiness("blocked")) == []


def test_a_new_verdict_word_passes_the_form_and_no_rule_reads_it(tmp_path):
    data = readiness("new: partial -- waiting for one answer")
    assert CW._readiness_form(data) == []
    assert CW.readiness_rules(data, tmp_path) == []                       # F-X2-3: nothing routes on the word
    assert CW._readiness_rules_unrooted(data) == ([], [])


def test_a_verdict_word_outside_the_list_is_refused_with_the_door():
    problems = CW._readiness_form(readiness("maybe"))
    assert len(problems) == 1 and problems[0].startswith("verdict 'maybe'") and "new: <word> -- <why>" in problems[0]
    assert CW._readiness_form(readiness(None)) and CW._readiness_form(readiness("new: partial --"))


def test_a_new_verdict_word_beside_a_blocker_question_is_not_judged_by_code(tmp_path):
    blocker = [{"question": "q", "severity": "blocker", "owner_role": "po_ba"}]
    data = readiness("new: partial -- waiting for one answer", blocker)
    assert CW._readiness_form(data) == [] and CW.readiness_rules(data, tmp_path) == []
    assert CW.readiness_check(data)["errors"] == [e for e in CW.readiness_check(data)["errors"] if "verdict" not in e]


# --- handoff_check: the proposed lists of the stage forms, and the judge that only advises -------------------------------

S2 = "s2-tester-to-strategist"


def form(state, contract=S2):
    return H.parse(f"contract: {contract}\nstage: S2\nheader:\n  role: qa-requirements-tester\nscope:\n  - id: R-1\n"
                   f"    state: {state}\n    reason: because\n")


class Judge:
    def __init__(self, value="found"):
        self.value, self.asked = value, 0

    def active(self, *a, **k):
        return True

    def ask(self, state, questions, **kw):
        self.asked += 1
        return {"status": "ok", "advisory": False,
                "answers": {"q": {"value": self.value, "decided": True, "confidence": 0.9}}}


def state_problems(doc, **kw):
    out = HC.check(doc, S2 if "contract" not in kw else kw.pop("contract"), HC.Artifacts(Path(kw.pop("root"))), **kw)
    return out, [p for p in out[2] if p.path == "scope[0].state"]


def test_a_stage_word_of_the_list_passes_the_handoff_check(tmp_path):
    _out, found = state_problems(form("found"), root=tmp_path)
    assert found == []


def test_a_new_word_passes_the_form_and_is_proposed_for_the_stage_critic(tmp_path):
    out, found = state_problems(form("new: seam-race -- two writers of one row"), root=tmp_path, fix=True)
    assert found == []
    proposed = [row for row in out[3] if row.get("kind") == "proposed"]
    assert proposed == [{"kind": "proposed", "field": "scope[0].state", "word": "seam-race", "why": "two writers of one row"}]
    doc = HC.record_judged(out[0], out[3])
    assert doc.get("scope[0].state") == "new: seam-race -- two writers of one row"          # the role's word, untouched
    assert doc.data["proposed"][0]["word"] == "seam-race"
    again = HC.record_judged(doc, out[3])                                                    # recorded once
    assert len(again.data["proposed"]) == 1


def test_a_bad_door_is_refused_as_form_with_the_repair_marker(tmp_path):
    _out, found = state_problems(form("new: seam-race --"), root=tmp_path)
    assert len(found) == 1 and "reason" in found[0].text and "new: <word> -- <why>" in found[0].text
    assert "new:" in found[0].text and found[0].text.rstrip().endswith(".")


def test_a_word_outside_the_list_is_refused_with_the_door(tmp_path):
    _out, found = state_problems(form("vibes"), root=tmp_path)
    assert len(found) == 1 and "is not a value of this field" in found[0].text and "new: <word> -- <why>" in found[0].text


def test_the_judge_advises_and_never_writes_the_role_word(tmp_path):
    judge, saved = Judge("found"), HC.judge
    HC.judge = judge
    try:
        out, found = state_problems(form("vibes"), root=tmp_path, fix=True, use_judge=True)
    finally:
        HC.judge = saved
    assert judge.asked == 1
    assert out[0].get("scope[0].state") == "vibes"                                          # the field is NOT changed
    assert len(found) == 1 and "nearest to `found`" in found[0].text                        # still refused, advice beside it
    assert [r["nearest"] for r in out[3] if r.get("kind") == "suggested"] == ["found"]
    doc = HC.record_judged(out[0], out[3])
    assert doc.data["suggested"][0]["as_written"] == "vibes" and doc.get("scope[0].state") == "vibes"
    assert "judged" not in doc.data


def test_the_judge_is_not_asked_without_fix_and_not_for_a_valid_door(tmp_path):
    judge, saved = Judge(), HC.judge
    HC.judge = judge
    try:
        state_problems(form("vibes"), root=tmp_path, fix=False, use_judge=True)
        state_problems(form("new: seam-race -- two writers of one row"), root=tmp_path, fix=True, use_judge=True)
    finally:
        HC.judge = saved
    assert judge.asked == 0


def test_a_later_stage_keeps_its_list_closed(tmp_path):
    five = "s5-automator-to-critic"
    doc = H.parse(f"contract: {five}\nstage: S5\nheader:\n  role: qa-automator\nscope:\n  - id: a\n    state: new: seam-race -- two writers of one row\n")
    found = [p for p in HC.check(doc, five, HC.Artifacts(tmp_path))[2] if p.path == "scope[0].state"]
    assert len(found) == 1 and "is not a value of this field" in found[0].text and "new: <word>" not in found[0].text


def test_the_old_judged_rows_are_still_recorded_as_judged():
    doc = H.parse("contract: s5-automator-to-critic\nscope:\n  - id: a\n    state: green\n")
    doc = HC.record_judged(doc, [{"field": "scope[0].state", "value": "unverified", "as_written": "x",
                                  "confidence": 0.9, "judgment": "form_row_state"}])
    assert doc.data["judged"][0]["value"] == "unverified"


def test_a_second_section_lands_inside_its_own_block():
    doc = H.parse("contract: s2-tester-to-strategist\nscope:\n  - id: a\n    state: found\n")
    doc = HC.record_judged(doc, [{"kind": "suggested", "field": "a", "as_written": "x", "nearest": "found", "confidence": 1, "judgment": "j"}])
    doc = HC.record_judged(doc, [{"kind": "proposed", "field": "a", "word": "w-1", "why": "a long enough reason"}])
    doc = HC.record_judged(doc, [{"kind": "suggested", "field": "b", "as_written": "y", "nearest": "found", "confidence": 1, "judgment": "j"}])
    assert [r["field"] for r in doc.data["suggested"]] == ["a", "b"] and len(doc.data["proposed"]) == 1


if __name__ == "__main__": raise SystemExit(pytest.main([__file__, "-q", "-p", "no:cacheprovider"]))
