"""Question branches: what an answer to an open register question DOES, checked before gate A.

TP1-13797 (cmp1, B-216): the person answered four of five register questions by letter at gate
A, and nothing in the plan or the cases said what an answer does - TS-6's disposition and TC_006's
Then stayed as authored and the row's reason went on naming a settled question. A row now carries
`question_refs` and `if_answered`, a case carries `question_thens`; `planning_contract.
variant_errors` is the pure check, `gate_preflight.Rehearsal.check_question_branches` reads the
story and calls it.

One named check per override (O1 the `*` key and the closed patch keys, O2 the empty reading text,
O3 the pure checks, O4 factory-owned findings that write nothing) and per edge of the dispatch.
"""
import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import (PLUGIN_ROOT, SCRIPTS, check, check_eq, check_in, check_not_in,  # noqa: E402
                     cleanup, finish, temp_dir, use_project)

sys.path.insert(0, str(SCRIPTS))

import gate_preflight  # noqa: E402
import planning_contract as PC  # noqa: E402

TICKET = "TP1-13797"


# --- fixtures --------------------------------------------------------------------------------

def q(qid, readings=2, status="open"):
    """A register question as `question_register.load` returns it (the fields the check reads)."""
    return {"id": qid, "status": status, "letters": "abcdefgh"[:readings],
            "readings": [{"reading": f"reading {n}"} for n in range(readings)]}


QUESTIONS = [q("Q1"), q("Q2"), q("Q3", 3), q("Q10")]


def row(rid, **extra):
    """A plan row that satisfies the planning contract, so a finding here is the one asked for."""
    return dict({"id": rid, "requirement_ids": ["R-1"], "level": "api", "disposition": "automate",
                 "impact": "moderate", "likelihood": "medium", "design_review_required": False,
                 "confidence": "medium", "risk_rationale": "a permission seam",
                 "risk_source_refs": ["strategy/test-strategy.md@2026-09-14"],
                 "risk_policy_revision": "factory-starter-v1", "coverage_refs": [], "unknowns": [],
                 "verification_depth": "normal", "defect_hypothesis": "seam @ validate vs update",
                 "required_scenarios": ["a denied caller"],
                 "test_level_rationale": "HTTP contract, no UI involved"}, **extra)


def obligation(oid="OB-1"):
    return {"obligation_id": oid, "behavior": "a disallowed event is refused",
            "observation_boundary": "the HTTP response", "completion_condition": "status is asserted",
            "requirement_refs": [{"ref": "R-1", "revision": "1"}], "applicable_scenarios": ["s1"],
            "oracle_status": "resolved", "oracle_source_ref": "requirement:R-1", "decision": "new",
            "execution_scope": "current_task", "coverage_links": [], "planned_check_refs": ["t::x"],
            "sufficiency_review": {"author_dispatch_id": "d1", "input_hash": "h1", "rationale": "r"}}


def v2_row(rid, **extra):
    return row(rid, schema_version=2, coverage_obligations=[obligation(f"OB-{rid}")], **extra)


def case(cid="TC-001", thens=(1, 2, 3), thens_line=None, readable=True):
    return {"case": cid, "readable": readable, "question_thens": thens_line, "thens": list(thens)}


def qt(question="Q1", then=1, readings=None, **extra):
    return dict({"question": question, "then": then,
                 "readings": {"a": "200, nothing runs", "b": "400"} if readings is None else readings},
                **extra)


def first(found):
    """The first finding, or an empty one: a missing finding is a FAIL line, never a traceback."""
    return found[0] if found else {"kind": "", "owner": "", "where": "", "question": "", "message": "", "fix": ""}


def kinds(found):
    return [f["kind"] for f in found]


def of_kind(found, kind):
    return [f for f in found if f["kind"] == kind]


def run_pure(rows, questions=None, cases=(), missing=False, **kwargs):
    """The findings of the pure check. `missing_branch` (t-227b, F14) is left out unless asked for:
    most checks below use a row that merely NAMES a question (`question_refs=["Q1"]`) as the neutral
    fixture for some other finding, and that row has no branch for every answer by construction.
    The `missing_branch` checks themselves pass `missing=True` or call `PC.variant_errors` directly."""
    found = PC.variant_errors(rows, QUESTIONS if questions is None else questions, cases, **kwargs)
    return found if missing else [f for f in found if f["kind"] != "missing_branch"]


# --- the contract of the closed list and of `*` (O1) -------------------------------------------

def test_o1_the_patch_keys_are_a_closed_list_in_a_data_file() -> None:
    data = json.loads((PLUGIN_ROOT / "references" / "question-branch-keys.json").read_text(encoding="utf-8"))
    check_eq("the data file holds the eight keys, coverage_obligations and rung_basis included",
             data["patch_keys"], ["disposition", "level", "fit", "reason", "oracle_unknown",
                                  "test_level_rationale", "coverage_obligations", "rung_basis"])
    check_eq("the code reads that file", list(PC.branch_patch_keys()), data["patch_keys"])
    found = run_pure([row("TS-1", question_refs=["Q1"],
                          if_answered={"Q1": {"a": {"impact": "low"}, "b": {"level": "api"}}})])
    check_eq("a key outside the list is a finding", kinds(found), ["bad_branch"])
    check_in("and it names the key and the closed list", "`impact`", first(found)["message"])
    check_in("...and the list", "disposition", first(found)["message"])
    check_eq("an impostor list passed in decides, not a list written in code",
             kinds(run_pure([row("TS-1", question_refs=["Q1"],
                                 if_answered={"Q1": {"*": {"level": "api"}}})], allow_keys=("disposition",))),
             ["bad_branch"])
    check_eq("the same patch is fine under the real list",
             run_pure([row("TS-1", question_refs=["Q1"], if_answered={"Q1": {"*": {"level": "api"}}})]), [])
    doc = (PLUGIN_ROOT / "references" / "artifact-contract-plan.md").read_text(encoding="utf-8")
    check("the plan contract names every key of the data file",
          all(f"`{key}`" in doc or key in doc for key in data["patch_keys"]))
    check("negative control: a key that is not in the data file is not in the document",
          "impossible_patch_key" not in doc)


def test_o1_a_letter_key_is_laid_over_the_star_key() -> None:
    # t-227b C5: ONE resolver, MERGE semantics: `*` first, the letter over it. Until then the S3 check
    # and the applier REPLACED (a letter patch dropped the `*` keys) while the gate card MERGED.
    good = {"disposition": "automate", "level": "api"}
    bad = {"test_level_rationale": ""}
    check_eq("resolve_patch: a letter key is laid over `*`: both patches' keys, the letter winning",
             PC.resolve_patch({"a": {"level": "api", "reason": "r1"}, "*": {"level": "unit", "fit": "new"}}, "a"),
             {"level": "api", "reason": "r1", "fit": "new"})
    check_eq("resolve_patch: `*` stands for a reading with no key of its own",
             PC.resolve_patch({"a": good, "*": bad}, "b"), bad)
    check_eq("resolve_patch: `*` never covers not_needed", PC.resolve_patch({"*": bad}, "not_needed"), None)
    check_eq("resolve_patch: not_needed is its own key, and `*` is not merged into it",
             PC.resolve_patch({"*": bad, "not_needed": good}, "not_needed"), good)
    check_eq("resolve_patch: a reading nobody patches leaves the row as authored",
             PC.resolve_patch({"a": good}, "b"), None)
    check_eq("resolve_patch: an empty patch is a patch (the row stays as written, and it IS written)",
             PC.resolve_patch({"a": {}}, "a"), {})
    check_eq("resolve_patch: a value that is no object is no patch", PC.resolve_patch({"a": "x"}, "a"), None)
    got = PC.resolve_patch({"a": good}, "a")
    got["level"] = "unit"
    check_eq("resolve_patch returns a NEW dict: the authored patch is never aliased", good["level"], "api")
    found = run_pure([row("TS-1", question_refs=["Q1"], if_answered={"Q1": {"a": good, "*": bad}})])
    check_eq("the merged `a` carries the `*` key too: BOTH readings fall to the broken `*` patch",
             sorted(f["message"].split("(")[1][:1] for f in found), ["a", "b"])
    check_eq("...each as its own finding, since the merged patches differ", kinds(found),
             ["invalid_variant", "invalid_variant"])
    check_eq("`*` written ONCE serves every reading",
             run_pure([row("TS-1", question_refs=["Q1"],
                           if_answered={"Q1": {"*": {"disposition": "automate", "level": "api"}}})]), [])
    mended = dict(good, test_level_rationale="HTTP contract, no UI involved")
    check_eq("a letter patch that sets every key of the `*` patch leaves nothing of it to judge",
             run_pure([row("TS-1", question_refs=["Q1"],
                           if_answered={"Q1": {"a": mended, "b": mended, "*": bad}})]), [])
    check_eq("not_needed alone is a variant like any other",
             kinds(run_pure([row("TS-1", question_refs=["Q1"],
                                 if_answered={"Q1": {"not_needed": bad}})])), ["invalid_variant"])


def test_o1_apply_patch_is_pure_and_replaces_the_whole_obligation_list() -> None:
    authored = v2_row("TS-2")
    before = copy.deepcopy(authored)
    patch = {"coverage_obligations": [obligation("OB-NEW")], "disposition": "manual-human"}
    patched = PC.apply_patch(authored, patch)
    check_eq("the authored row is not changed", authored, before)
    check_eq("the list is replaced whole, not merged",
             [ob["obligation_id"] for ob in patched["coverage_obligations"]], ["OB-NEW"])
    patched["coverage_obligations"][0]["behavior"] = "changed"
    check_eq("and the patch is not aliased", patch["coverage_obligations"][0]["behavior"],
             "a disallowed event is refused")


# --- the empty reading text (O2) --------------------------------------------------------------

def test_o2_an_empty_reading_text_is_a_valid_reading() -> None:
    rows = [row("TS-6", question_refs=["Q1"])]
    check_eq("an empty text for one reading is valid: the Then keeps its number",
             run_pure(rows, cases=[case(thens_line=json.dumps([qt(readings={"a": "", "b": "HTTP 400"})]))]), [])
    check_eq("a whitespace-only text is as empty",
             run_pure(rows, cases=[case(thens_line=json.dumps([qt(readings={"a": "  ", "b": ""})]))]), [])
    found = run_pure(rows, cases=[case(thens_line=json.dumps([qt(readings={"a": "HTTP 200"})]))])
    check_eq("a reading with NO entry is a finding", kinds(found), ["missing_reading_text"])
    check_in("it names the missing letter and the case", "TC-001: Then 1 asks Q1 but has no text for reading b",
             first(found)["message"])
    check_in("and says an empty text is allowed", "empty text is allowed", first(found)["message"])
    found = run_pure(rows, cases=[case(thens_line=json.dumps([qt(readings={"a": "x", "b": None})]))])
    check_eq("null is not a text", kinds(found), ["missing_reading_text"])
    found = run_pure(rows, cases=[case(thens_line=json.dumps([qt("Q3", readings={"a": "x"})]))])
    check_in("three readings: every absent letter is listed", "reading b, c", first(found)["message"])
    check_eq("not_needed is optional", run_pure(rows, cases=[case(thens_line=json.dumps([qt()]))]), [])
    check_eq("not_needed given as a text (empty too) is valid",
             run_pure(rows, cases=[case(thens_line=json.dumps([qt(**{"not_needed": ""})]))]), [])
    check_eq("not_needed given as a number is a finding",
             kinds(run_pure(rows, cases=[case(thens_line=json.dumps([qt(**{"not_needed": 3})]))])),
             ["bad_branch"])
    found = run_pure(rows, cases=[case(thens_line=json.dumps([qt(readings={"a": "x", "b": "y", "c": "z"})]))])
    check_eq("a reading letter the question does not have is a finding", kinds(found), ["bad_branch"])
    check_in("...naming the letter", "names c", first(found)["message"])


# --- the pure checks (O3) ---------------------------------------------------------------------

def test_o3_each_variant_is_applied_in_memory_and_must_pass_the_plan_contract() -> None:
    rows = [row("TS-1", question_refs=["Q1"],
                if_answered={"Q1": {"a": {"disposition": "automate", "level": "api"},
                                    "b": {"test_level_rationale": ""}}}), row("TS-2")]
    found = run_pure(rows)
    check_eq("a variant that breaks validate_plan is flagged", kinds(found), ["invalid_variant"])
    check_in("naming the row, the question and the answer", "TS-1: if Q1 is answered (b)", first(found)["message"])
    check_in("and what broke", "empty test_level_rationale", first(found)["message"])
    check_eq("it is the strategist's", first(found)["owner"], "strategist")
    check_in("the message ends with the author's rework, in plain words",
             "the strategist's rework repairs this row", first(found)["message"])
    check_eq("the authored rows are not changed by the check", rows[0]["test_level_rationale"],
             "HTTP contract, no UI involved")
    v2 = [v2_row("TS-2", question_refs=["Q1"], if_answered={"Q1": {
        "a": {"coverage_obligations": [obligation("OB-A")]},
        "b": {"coverage_obligations": [{"obligation_id": "OB-B"}]}}})]
    found = run_pure(v2)
    check_eq("the coverage contract judges a replaced obligation list too", kinds(found), ["invalid_variant"])
    check_in("...for reading b", "(b)", first(found)["message"])
    check_in("...with the contract's own words", "OB-B: missing behavior", first(found)["message"])
    broken_authored = [row("TS-1", question_refs=["Q1"], risk_rationale="",
                           if_answered={"Q1": {"a": {"level": "api"}}})]
    check_eq("an error the AUTHORED row already had is not charged to the variant",
             run_pure(broken_authored), [])
    check_eq("a variant identical to the authored row is valid (E-18)",
             run_pure([row("TS-1", question_refs=["Q1"], if_answered={"Q1": {
                 "a": {"disposition": "automate", "level": "api", "test_level_rationale":
                       "HTTP contract, no UI involved"}, "b": {}}})]), [])
    check_eq("a variant that is not validated because it cannot be is still a finding, not a traceback",
             kinds(run_pure([v2_row("TS-2", question_refs=["Q1"],
                                    if_answered={"Q1": {"a": {"coverage_obligations": 5}}})])),
             ["invalid_variant"])


def test_o3_an_oracle_unknown_row_carries_question_refs() -> None:
    rows = [row("TS-1", question_refs=["Q1"]),
            row("TS-6", oracle_unknown=True, design_review_required=True)]
    found = run_pure(rows)
    check_eq("an oracle_unknown row with no refs is a finding", kinds(found), ["missing_refs"])
    check_eq("...on the row", first(found)["where"], "TS-6")
    check_in("...in words", "names no question in `question_refs`", first(found)["message"])
    rows[1]["question_refs"] = []
    check_eq("an empty list is no ref", kinds(run_pure(rows)), ["missing_refs"])
    rows[1]["question_refs"] = ["Q2"]
    check_eq("with a ref the row is fine", run_pure(rows), [])
    check_eq("an oracle_unknown row that is not flagged is not asked for refs",
             run_pure([row("TS-1", question_refs=["Q1"]), row("TS-7", oracle_unknown=False)]), [])
    check_eq("question_refs that is not a list is a finding",
             kinds(run_pure([row("TS-1", question_refs="Q1")])), ["bad_branch"])


def test_o3_two_questions_patching_one_field_or_one_then_are_a_dependent_pair() -> None:
    rows = [row("TS-1", question_refs=["Q1", "Q2"], if_answered={
        "Q1": {"a": {"disposition": "automate", "level": "api"}},
        "Q2": {"a": {"disposition": "manual-human", "fit": "new"}}})]
    found = run_pure(rows)
    check_eq("the same row field patched by two questions is one finding", kinds(found), ["dependent_pair"])
    check_in("it says DEPENDENT", "DEPENDENT pair", first(found)["message"])
    check_in("names both questions", "Q1 and Q2", first(found)["message"])
    check_in("and the shared field", "`disposition`", first(found)["message"])
    check_not_in("not the fields they do not share", "`fit`", first(found)["message"])
    rows = [row("TS-1", question_refs=["Q1", "Q2"], if_answered={
        "Q1": {"a": {"disposition": "automate", "level": "api"}},
        "Q2": {"a": {"fit": "new"}}})]
    check_eq("different fields are independent", run_pure(rows), [])
    rows = [row("TS-1", question_refs=["Q1"], if_answered={"Q1": {"a": {"level": "api"}}}),
            row("TS-2", question_refs=["Q2"], if_answered={"Q2": {"a": {"level": "api"}}})]
    check_eq("the same field on two DIFFERENT rows is independent", run_pure(rows), [])
    rows = [row("TS-1", question_refs=["Q1"], if_answered={"Q1": {"a": {"level": "api"}}})]
    cases = [case(thens_line=json.dumps([qt("Q1", 1), qt("Q2", 1)]))]
    found = run_pure(rows, cases=cases)
    check_eq("the same Then asked by two questions is a dependent pair", kinds(found), ["dependent_pair"])
    check_eq("...owned by the designer", first(found)["owner"], "designer")
    check_in("...naming the case and the Then", "TC-001: Q1 and Q2 both give Then 1", first(found)["message"])
    cases = [case(thens_line=json.dumps([qt("Q1", 1), qt("Q2", 2)]))]
    check_eq("two questions on two Thens are independent", run_pure(rows, cases=cases), [])


def test_o3_a_variants_reason_never_names_its_own_question() -> None:
    def reason_kinds(reason, qid="Q1", readings=2):
        rows = [row("TS-7", question_refs=[qid], if_answered={qid: {"a": {"reason": reason}}})]
        return kinds(run_pure(rows, questions=[q(qid, readings), q("Q2"), q("Q10")]))
    check_eq("the reason naming its own id is a finding", reason_kinds("Then rests on Q1"), ["stale_reason"])
    check_eq("...inside brackets", reason_kinds("rests on an open question (Q1)"), ["stale_reason"])
    check_eq("...at a sentence end", reason_kinds("see Q1."), ["stale_reason"])
    check_eq("an exact token: Q10 is not Q1", reason_kinds("rests on Q10"), [])
    check_eq("an exact token: Q1-b is not Q1", reason_kinds("rests on Q1-b"), [])
    check_eq("another question's id is allowed", reason_kinds("also waits for Q2"), [])
    check_eq("E-19: the other reason alone is valid", reason_kinds("25 MB body is a poor fit for an e2e check"), [])
    check_eq("a reason that is not a text is left to the plan contract, not crashed on",
             reason_kinds(["Q1"]), [])
    found = run_pure([row("TS-7", question_refs=["Q1"], if_answered={"Q1": {"*": {"reason": "Q1 stands"}}})])
    check_in("the finding says why, in plain words", "a question that is settled by then", first(found)["message"])
    check_eq("...and one finding per distinct patch, not per letter", len(found), 1)


def test_e19_a_variant_that_moves_a_row_repairs_the_reason_that_names_the_question() -> None:
    """E-19 (t-156's follow-up): TS-7 is manual for Q1 AND for the 25 MB body. A variant that changes the
    disposition must carry only the other reason. Invariant: after the answer no reason names Q1."""
    both = "rests on Q1, and the 25 MB body is a poor fit for an e2e check"
    move = {"disposition": "automate", "level": "api"}

    def found_for(patch, reason=both, *, qid="Q1", key="a", authored="manual-human", **extra):
        rows = [row("TS-7", disposition=authored, reason=reason, question_refs=[qid],
                    if_answered={qid: {key: patch}}, **extra)]
        return run_pure(rows)

    found = found_for(dict(move))
    check_eq("the disposition changes and the authored reason still names Q1: one finding", kinds(found), ["stale_reason"])
    check_in("it says the disposition changes", "the row's disposition changes", first(found)["message"])
    check_in("...that the authored reason still names the question", "authored `reason` still names Q1", first(found)["message"])
    check_in("...and what to write", "patch `reason` with the reason that remains", first(found)["message"])
    check_eq("...the strategist's", first(found)["owner"], "strategist")
    check_eq("...on the row and the question", (first(found)["where"], first(found)["question"]), ("TS-7", "Q1"))
    check_eq("the patch carrying ONLY the other reason is valid",
             found_for({**move, "reason": "the 25 MB body is a poor fit for an e2e check"}), [])
    twice = found_for({**move, "reason": "rests on Q1 still"})
    check_eq("a patched reason that names Q1 is the existing finding, said once", kinds(twice), ["stale_reason"])
    check_in("...in the existing words", "once Q1 is answered (a) the row's `reason` still names Q1", first(twice)["message"])
    check_eq("not_needed that moves the row is judged the same",
             kinds(found_for(dict(move), key="not_needed")), ["stale_reason"])
    check_eq("`*` is ONE finding for every reading it covers", len(found_for(dict(move), key="*")), 1)
    check_eq("a variant that does not change the disposition is not this finding (the spec's limit)",
             found_for({"level": "api"}), [])
    check_eq("...nor one that sets the disposition the row already has",
             found_for({"disposition": "manual-human", "level": "api"}), [])
    check_eq("an authored reason that does not name the question is left alone",
             found_for(dict(move), reason="the 25 MB body is a poor fit"), [])
    check_eq("an authored row with no reason at all is left alone", run_pure(
        [row("TS-7", disposition="manual-human", question_refs=["Q1"], if_answered={"Q1": {"a": dict(move)}})]), [])
    check_eq("an exact token: Q10 is not Q1", found_for(dict(move), reason="rests on Q10"), [])
    check_eq("an authored reason that is not a text is left to the plan contract",
             found_for(dict(move), reason=["Q1"]), [])
    # a reason naming two questions and an answer covering one: the other stays
    two = "waits for Q1 and for Q2"
    check_eq("the answer to Q1 leaves the reason that names Q2 - and only that one",
             found_for({**move, "reason": "waits for Q2"}, reason=two), [])
    check_eq("...a patch that drops Q1 but keeps the row's reason untouched is the finding",
             kinds(found_for(dict(move), reason=two)), ["stale_reason"])
    check_eq("...the same reason read for Q2 when only Q2 is answered",
             found_for({**move, "reason": "waits for Q1"}, reason=two, qid="Q2"), [])


def test_o3_ids_resolve_exactly_against_the_register() -> None:
    for name, ref in (("an alias", "Q-R14"), ("a prefix of a real id", "Q"), ("a substring", "Q1x"),
                      ("a lower-case id", "q1"), ("a longer id", "Q100")):
        found = run_pure([row("TS-1", question_refs=[ref])])
        check_eq(f"{name} resolves nowhere", kinds(found), ["unresolved_ref"])
    found = run_pure([row("TS-1", question_refs=["Q-R14"])])
    check_in("the finding lists the ids that do exist", "Q1, Q2, Q3, Q10", first(found)["message"])
    check_in("...and says aliases are no ids", "an alias such as Q-R14 is no id", first(found)["message"])
    check_eq("surrounding whitespace is trimmed, nothing else",
             run_pure([row("TS-1", question_refs=[" Q1 "])]), [])
    check_eq("Q1 is not Q10: a register that has only Q10 does not resolve Q1",
             kinds(run_pure([row("TS-1", question_refs=["Q1"])], questions=[q("Q10")])), ["unresolved_ref"])
    check_eq("an if_answered key is resolved the same way",
             kinds(run_pure([row("TS-1", if_answered={"Q-1": {"a": {"level": "api"}}})])), ["unresolved_ref"])
    check_eq("a question_thens id too",
             kinds(run_pure([row("TS-1", question_refs=["Q1"])],
                            cases=[case(thens_line=json.dumps([qt("Q-R15")]))])), ["unresolved_ref"])
    check_eq("an empty question id in question_thens is named as empty, not crashed on",
             kinds(run_pure([row("TS-1", question_refs=["Q1"])],
                            cases=[case(thens_line=json.dumps([qt("")]))])), ["unresolved_ref"])


def test_e2_an_answered_question_never_stays_as_a_branch() -> None:
    for status in ("answered", "not_needed"):
        questions = [q("Q1", status=status), q("Q2")]
        rows = [row("TS-1", question_refs=["Q1"], if_answered={"Q1": {"a": {"level": "api"}}})]
        found = run_pure(rows, questions=questions)
        check_eq(f"a {status} question still branching a row is a finding", kinds(found), ["settled_question"])
        check_in("...saying it is settled", "already answered", first(found)["message"])
        found = run_pure([row("TS-1", question_refs=["Q2"])], questions=questions,
                         cases=[case(thens_line=json.dumps([qt("Q1")]))])
        check_eq(f"a {status} question still in a conditional Then is a finding", kinds(found),
                 ["settled_question"])
        check_eq("...the designer's", first(found)["owner"], "designer")
    for status in ("open", "named", "with_designer"):
        rows = [row("TS-1", question_refs=["Q1"], if_answered={"Q1": {"a": {"test_level_rationale": ""}}})]
        check_eq(f"a {status} question is unsettled: its variants are checked",
                 kinds(run_pure(rows, questions=[q("Q1", status=status)])), ["invalid_variant"])


# --- edges of the dispatch --------------------------------------------------------------------

def test_e9_a_story_with_no_branch_field_is_never_a_finding() -> None:
    legacy = [row("TS-1"), row("TS-6", oracle_unknown=True, design_review_required=True, risk_rationale="")]
    check_eq("legacy plan, legacy cases: nothing, even an oracle_unknown row without refs",
             run_pure(legacy, cases=[case(), case("TC-002")]), [])
    check_eq("empty placeholders are not branch fields", run_pure(
        [row("TS-6", oracle_unknown=True, design_review_required=True, question_refs=[], if_answered={})]), [])
    check_eq("an oracle_unknown row without refs is not asked for them while the PLAN carries no "
             "question_refs at all, even when a case branches",
             run_pure([legacy[1]], cases=[case(thens_line=json.dumps([qt("Q1", 1)]))]), [])
    check_eq("has_branch_fields says so", PC.has_branch_fields(legacy, [case()]), False)
    check_eq("a branch on a case alone makes the story a branching one",
             PC.has_branch_fields(legacy, [case(thens_line="[]")]), True)
    check_eq("a blank `question_thens:` line counts: a nested block is a defect to say",
             kinds(run_pure(legacy, cases=[case(thens_line="")])), ["bad_branch"])
    for garbage in (None, [], {}, "x", 5, [None, 7, "r"]):
        try:
            got = PC.variant_errors(garbage, garbage, garbage)
            check_eq(f"garbage input {type(garbage).__name__} raises nothing and finds nothing", got, [])
        except Exception as exc:  # the no-exception edge
            check(f"garbage input {type(garbage).__name__} raises nothing", False, repr(exc))


def test_edges_malformed_branch_fields_are_findings_naming_the_row_or_case() -> None:
    check_eq("if_answered that is not an object",
             kinds(run_pure([row("TS-1", question_refs=["Q1"], if_answered=["Q1"])])), ["bad_branch"])
    check_eq("if_answered for a question that is not an object",
             kinds(run_pure([row("TS-1", if_answered={"Q1": "a"})])), ["bad_branch"])
    found = run_pure([row("TS-1", if_answered={"Q1": {"c": {"level": "api"}}})])
    check_eq("a letter that is not a reading of the question", kinds(found), ["bad_branch"])
    check_in("...says which readings there are", "its readings are a, b", first(found)["message"])
    check_eq("a patch that is not an object",
             kinds(run_pure([row("TS-1", if_answered={"Q1": {"a": "automate"}})])), ["bad_branch"])
    check_eq("a question that has no readings has no letter to patch",
             kinds(run_pure([row("TS-1", if_answered={"Q1": {"a": {"level": "api"}}})], questions=[q("Q1", 0)])),
             ["bad_branch"])
    for name, line, needle in (("not JSON", "[{question: Q1}]", "ONE line of JSON"),
                               ("an object, not a list", '{"question": "Q1"}', "ONE line of JSON"),
                               ("a blank value", "", "ONE line of JSON"),
                               ("an entry that is not an object", "[5]", "must be an object")):
        found = run_pure([row("TS-1", question_refs=["Q1"])], cases=[case("TC-009", thens_line=line)])
        check_eq(f"question_thens {name}: one finding", kinds(found), ["bad_branch"])
        check_in("...naming the case", "TC-009", first(found)["message"])
        check_in("...and what is expected", needle, first(found)["message"])
        check_in("...and the designer's rework", "the case designer's rework repairs this case",
                 first(found)["message"])
    for name, then in (("a string", "1"), ("a bool", True), ("zero", 0), ("beyond the Then list", 4),
                       ("a float", 1.5), ("absent", None)):
        found = run_pure([row("TS-1", question_refs=["Q1"])],
                         cases=[case("TC-009", thens=(1, 2, 3), thens_line=json.dumps([qt(then=then)]))])
        check_eq(f"`then` {name} is a finding", of_kind(found, "bad_branch") != [], True)
    found = run_pure([row("TS-1", question_refs=["Q1"])],
                     cases=[case("TC-009", thens=(), thens_line=json.dumps([qt(then=1)]))])
    check_in("a case with no numbered Then names the empty list", "this case has none", first(found)["message"])
    found = run_pure([row("TS-1", question_refs=["Q1"])], cases=[case("TC-009", readable=False)])
    check_eq("an unreadable case is a finding when the story branches elsewhere", kinds(found), ["case_unreadable"])
    check_eq("...and is silent in a legacy story", run_pure([row("TS-1")], cases=[case("TC-009", readable=False)]), [])
    check_eq("readings that is not an object",
             kinds(run_pure([row("TS-1", question_refs=["Q1"])],
                            cases=[case(thens_line=json.dumps([{"question": "Q1", "then": 1, "readings": "a"}]))])),
             ["bad_branch"])
    deep = "[" * 100000
    check_eq("a deeply nested value is a finding, not a RecursionError",
             kinds(run_pure([row("TS-1", question_refs=["Q1"])], cases=[case(thens_line=deep)])), ["bad_branch"])
    check_eq("200 KB of garbage is one finding",
             len(run_pure([row("TS-1", question_refs=["Q1"])], cases=[case(thens_line="x" * 200000)])), 1)


def test_o3_the_pure_check_reads_nothing_and_changes_nothing() -> None:
    rows = [row("TS-1", question_refs=["Q1", "Q2"], oracle_unknown=True, if_answered={
        "Q1": {"a": {"disposition": "automate", "level": "api", "reason": "Q1"}, "*": {"level": "api"}},
        "Q2": {"a": {"disposition": "x"}}})]
    cases = [case(thens_line=json.dumps([qt("Q1", 1), qt("Q2", 1)]))]
    questions = copy.deepcopy(QUESTIONS)
    before = copy.deepcopy((rows, cases, questions))
    first = PC.variant_errors(rows, questions, cases)
    check_eq("inputs are untouched", (rows, cases, questions), before)
    check_eq("the same inputs give the same findings", PC.variant_errors(rows, questions, cases), first)
    check("the findings carry only the documented kinds", set(kinds(first)) <= set(PC.BRANCH_KINDS))
    check("every finding has the documented fields (and `lacking`, only on a missing_branch, t-256 O11)",
          all(set(f) - {"lacking"} == {"kind", "owner", "where", "question", "message"}
              and ("lacking" not in f or f["kind"] == "missing_branch") for f in first))
    check("every owner is the strategist or the designer",
          all(f["owner"] in ("strategist", "designer") for f in first))


# --- the rehearsal (O3 reads the story; O4 findings are the factory's, and write nothing) -----

def story(prefix, *, plan, questions=None, cases=None, links=None, pipeline_extra=None):
    root = temp_dir(prefix)
    task = root / "qa-factory" / "artifacts" / TICKET
    (task / "work" / "test-cases" / "webhook").mkdir(parents=True)
    (task / "state").mkdir(parents=True)
    (root / "qa-factory" / "config.json").write_text(json.dumps(
        {"schema_version": 1, "tests_root": "tests", "app_root": "."}), encoding="utf-8")
    (task / "work" / "test-plan.json").write_text(json.dumps({"rows": plan}), encoding="utf-8")
    if questions is not None:
        (task / "work" / "requirements-readiness.json").write_text(
            json.dumps({"verdict": "blocked", "open_questions": questions}), encoding="utf-8")
    for name, text in (cases or {}).items():
        (task / "work" / "test-cases" / "webhook" / f"{name}.md").write_text(text, encoding="utf-8")
    if links is not None:
        (task / "state" / "story-case-links.json").write_text(json.dumps({"task_id": TICKET, "links": links}),
                                                            encoding="utf-8")
    (task / "pipeline.json").write_text(json.dumps(dict({"ticket": TICKET, "stages": {}}, **(pipeline_extra or {}))),
                                        encoding="utf-8")
    return root, task


def case_text(cid, thens_line=None, then_style="{n}."):
    front = f"---\nid: {cid}\nplan_row: TS-6\n" + (f"question_thens: {thens_line}\n" if thens_line is not None else "") + "---\n"
    items = "".join(f"{then_style.format(n=n)} Then number {n}.\n" for n in (1, 2, 3))
    return front + "\n## Then\n" + items


def register(qid="Q1", readings=2):
    return {"id": qid, "question": f"Which behaviour for {qid}?", "severity": "major",
            "readings": [{"reading": f"r{n}", "from": "description", "if_chosen": "x"} for n in range(readings)]}


def branch_findings(task):
    r = gate_preflight.Rehearsal(task, "A")
    r.check_question_branches()
    return r


def snapshot(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


FULL = {"*": {}, "not_needed": {}}   # a branch for every answer that leaves the row as written (t-227b)
BAD_PLAN = [row("TS-6", question_refs=["Q1"], if_answered={"Q1": {"a": {"level": "api"},
                                                                  "b": {"test_level_rationale": ""},
                                                                  "not_needed": {}}})]


def test_o4_findings_are_factory_owned_with_the_authors_door() -> None:
    root, task = story("qa-branches-findings-", plan=BAD_PLAN, questions=[register("Q1")], cases={
        "TC-001": case_text("TC-001", json.dumps([qt("Q1", 1, {"a": "200"})]))})
    try:
        use_project(root)
        r = branch_findings(task)
        rows = [f for f in r.findings if f["check"] == "question_branches"]
        check_eq("one finding per defect: the row's variant and the case's missing reading", len(rows), 2)
        check("every one is factory_fixable, never a question for the person",
              all(f["class"] == gate_preflight.FACTORY_FIXABLE for f in rows))
        row_f = first(of_kind(rows, "invalid_variant"))
        case_f = first(of_kind(rows, "missing_reading_text"))
        check_in("the message opens with the block's name, so a waiver can match it",
                 "question branches - TS-6", row_f["message"])
        # t-357: the doors are said in words (no script, no flag): the role, the stage and the place are all there
        check_in("the row's door is a strategist rework on that row",
                 "rows TS-6 go back to qa-test-strategist at S3, with this finding as the reason", row_f["fix"])
        check_in("the case's door is a designer rework on that case",
                 "cases TC-001 go back to qa-case-designer at S4, with this finding as the reason", case_f["fix"])
        check_in("the fix says it is not the person's", "not a question for you", row_f["fix"])
        check_in("a person's word passes it, as a line they write",
                 f"write `{row_f['id']}: accept` with your reason", row_f["fix"])
        check_eq("...against the block and the stage that refuses to close",
                 [(d["stage"], d["block"]) for d in row_f["waives"]], [("S4", "question branches")])
        check_eq("the finding carries its kind, place and question for the packet",
                 (row_f["kind"], row_f["where"], row_f["question"]), ("invalid_variant", "TS-6", "Q1"))
        check_eq("the rehearsal is not ready while one is open",
                 gate_preflight.run(task, "A")["gate_ready"], False)
        full = [f for f in gate_preflight.run(task, "A")["findings"] if f["check"] == "question_branches"]
        check_eq("registered: the full gate-A rehearsal carries them", len(full), 2)
    finally:
        cleanup(root)


def test_o4_the_rehearsal_writes_nothing() -> None:
    root, task = story("qa-branches-readonly-", plan=BAD_PLAN, questions=[register("Q1")], cases={
        "TC-001": case_text("TC-001", json.dumps([qt("Q1", 1, {"a": "200"})]))})
    try:
        use_project(root)
        before = snapshot(root)
        branch_findings(task)
        check_eq("the check added no file", sorted(snapshot(root)), sorted(before))
        check_eq("and changed none", [k for k, v in before.items() if snapshot(root).get(k) != v], [])
        gate_preflight.run(task, "A")
        check_eq("the whole gate-A rehearsal adds no file either", sorted(snapshot(root)), sorted(before))
    finally:
        cleanup(root)


def test_e19_the_rehearsal_carries_the_stale_reason_of_a_moved_row() -> None:
    plan = [row("TS-7", disposition="manual-human", reason="rests on Q1 and a 25 MB body", question_refs=["Q1"],
                if_answered={"Q1": {"a": {"disposition": "automate", "level": "api"}, "b": {}, "not_needed": {}}})]
    root, task = story("qa-branches-e19-", plan=plan, questions=[register("Q1")])
    try:
        use_project(root)
        rows = [f for f in branch_findings(task).findings if f["check"] == "question_branches"]
        check_eq("the moved row that keeps its reason is one factory_fixable finding",
                 [(f["kind"], f["class"]) for f in rows], [("stale_reason", gate_preflight.FACTORY_FIXABLE)])
        check_in("...on the row, with the strategist's door (t-357: in words)",
                 "rows TS-7 go back to qa-test-strategist at S3", first(rows)["fix"])
    finally:
        cleanup(root)


def test_e9_a_legacy_story_is_never_a_finding_in_the_rehearsal() -> None:
    plan = [row("TS-6", oracle_unknown=True, design_review_required=True, source_conflict=True)]
    root, task = story("qa-branches-legacy-", plan=plan, questions=[register("Q1")],
                       cases={"TC-001": case_text("TC-001")})
    try:
        use_project(root)
        r = branch_findings(task)
        check_eq("no finding", r.findings, [])
        check_eq("and nothing said either", r.info, [])
        full = gate_preflight.run(task, "A")
        check_eq("the full rehearsal has no question_branches finding",
                 [f for f in full["findings"] if f["check"] == "question_branches"], [])
        check_eq("nor an INFO line", [i for i in full["info"] if i["check"] == "question_branches"], [])
    finally:
        cleanup(root)


def test_edge_an_unreadable_register_is_one_printed_line_and_no_finding() -> None:
    plan = [row("TS-1", question_refs=["Q1"], if_answered={"Q1": {"a": {"test_level_rationale": ""}}})]
    variants = {
        "absent": dict(questions=None),
        "empty": dict(questions=[]),
        "not valid JSON": dict(questions=None),
    }
    for name, kwargs in variants.items():
        root, task = story("qa-branches-register-", plan=plan, **kwargs)
        try:
            use_project(root)
            if name == "not valid JSON":
                (task / "work" / "requirements-readiness.json").write_text("{not json", encoding="utf-8")
            try:
                r = branch_findings(task)
            except Exception as exc:
                check(f"register {name}: no exception", False, repr(exc))
                continue
            check_eq(f"register {name}: no finding", r.findings, [])
            check_eq(f"register {name}: one printed line", len(r.info), 1)
            check_in("...saying the questions could not be read", "could not be read", " ".join(i["message"] for i in r.info))
        finally:
            cleanup(root)
    root, task = story("qa-branches-register-raise-", plan=plan, questions=[register("Q1")])
    try:
        use_project(root)
        import question_register
        real = question_register.load

        def boom(_root):
            raise RuntimeError("the vocabulary is unusable")
        question_register.load = boom
        try:
            r = branch_findings(task)
        finally:
            question_register.load = real
        check_eq("load raising: no finding", r.findings, [])
        check_eq("load raising: one printed line", len(r.info), 1)
        check_in("...that carries the reason", "the vocabulary is unusable", " ".join(i["message"] for i in r.info))
    finally:
        cleanup(root)


def test_edge_the_then_list_is_the_one_s5_binds_and_a_missing_case_is_a_finding() -> None:
    root, task = story("qa-branches-thens-", plan=[row("TS-1", question_refs=["Q1"], if_answered={"Q1": FULL})],
                       questions=[register("Q1")], cases={
                           "TC-001": case_text("TC-001", json.dumps([qt("Q1", 3, {"a": "x", "b": ""})]), "{n})"),
                           "TC-002": case_text("TC-002", json.dumps([qt("Q1", 4, {"a": "x", "b": ""})]))})
    try:
        use_project(root)
        found = branch_findings(task).findings
        check_eq("Then 3 of a `3)` list exists (S5's reader counts `N.` and `N)`), Then 4 does not",
                 [(f["where"], f["kind"]) for f in found], [("TC-002", "bad_branch")])
    finally:
        cleanup(root)
    links = [{"case_id": "TC-777", "version": "cv_x", "path": "state/case-versions/TC-777/cv_x.md"}]
    root, task = story("qa-branches-missing-", plan=[row("TS-1", question_refs=["Q1"], if_answered={"Q1": FULL})],
                       questions=[register("Q1")], links=links)
    try:
        use_project(root)
        found = branch_findings(task).findings
        check_eq("a pinned case whose file is gone is a finding naming it",
                 [(f["where"], f["kind"]) for f in found], [("TC-777", "case_unreadable")])
    finally:
        cleanup(root)
    root, task = story("qa-branches-missing-legacy-", plan=[row("TS-1")], questions=[register("Q1")], links=links)
    try:
        use_project(root)
        check_eq("...and in a legacy story it is silent (case_versions says it)",
                 branch_findings(task).findings, [])
    finally:
        cleanup(root)
    root, task = story("qa-branches-body-", plan=[row("TS-1")], questions=[register("Q1")],
                       cases={"TC-001": "---\nid: TC-001\n---\n\n## Then\n1. x\n\nquestion_thens: not front matter\n"})
    try:
        use_project(root)
        check_eq("a `question_thens:` line in the BODY is no branch", branch_findings(task).findings, [])
    finally:
        cleanup(root)


def test_o4_a_persons_word_at_s4_passes_the_block_and_is_not_asked_twice() -> None:
    word = [{"stage": "S4", "match": "question branches", "decision": "go on anyway", "at": "2026-09-30T10:00:00",
             "by": "human"}]
    root, task = story("qa-branches-waiver-", plan=BAD_PLAN, questions=[register("Q1")],
                       pipeline_extra={"stage_overrides": word})
    try:
        use_project(root)
        check_eq("the recorded word passes the finding", branch_findings(task).findings, [])
    finally:
        cleanup(root)
    other = [dict(word[0], match="something else")]
    root, task = story("qa-branches-waiver-other-", plan=BAD_PLAN, questions=[register("Q1")],
                       pipeline_extra={"stage_overrides": other})
    try:
        use_project(root)
        check_eq("a word about another block does not", len(branch_findings(task).findings), 1)
    finally:
        cleanup(root)


MANUAL_NO_RATIONALE = [row("TS-5", question_refs=["Q1"], if_answered={"Q1": {
    "a": {"disposition": "manual-agent", "reason": "r"}, "b": {}, "not_needed": {}}})]


def s3_word_findings(match, stage="S3"):
    """The S4 rehearsal's findings over a plan with ONE missing_branch finding, after a word recorded at `stage` that
    quotes `match` (None: no word at all)."""
    word = ([{"stage": stage, "match": match, "decision": "go on anyway", "at": "2026-10-14T10:00:00", "by": "human"}]
            if match else [])
    root, task = story("qa-branches-s3-word-", plan=MANUAL_NO_RATIONALE, questions=[register("Q1")],
                       pipeline_extra={"stage_overrides": word} if word else None)
    try:
        use_project(root)
        return branch_findings(task).findings
    finally:
        cleanup(root)


def test_t721_one_record_passes_the_finding_wherever_it_was_recorded() -> None:
    """t-721 C2-3 (T11, T11b, section 3.6): S3 prints a missing-branch finding in two forms - the message, and the
    `where: it rests on <question>` line - and a person quotes either. The S4 rehearsal reads BOTH (and the S4 word), so
    the person records ONE word, not two."""
    found = s3_word_findings(None)
    check_eq("T11 control: with no word the plan has one finding, a missing_branch", [f["kind"] for f in found],
             ["missing_branch"])
    item = found[0]
    message = item["message"].removeprefix("question branches - ")
    line = PC.missing_branch_line(item)
    check_eq("T11: the line is `where: it rests on <question>`, built by the ONE formatter",
             line, f"{item['where']}: it rests on {item['question']}")
    check_eq("T11: a word at S3 quoting the `where: it rests on` line passes the finding at S4", s3_word_findings(line), [])
    check_eq("T11b: a word at S3 quoting the message form passes it too", s3_word_findings(message), [])
    check_eq("T11b: a word at S4 quoting the block name passes it (as before)",
             s3_word_findings("question branches", stage="S4"), [])
    check_eq("T11b: a word at S3 about something else does not", len(s3_word_findings("something else")), 1)
    check_eq("T11b: the S3 word at the line's form does not pass a DIFFERENT finding's line",
             len(s3_word_findings("TS-9: it rests on Q9")), 1)
    text = (Path(PC.__file__)).read_text(encoding="utf-8")
    check("T11b: the S3 text still offers the word (control of the same grep)", "A person's word passes any of these" in text)
    check("T11b: and no longer asks to record it twice", "record it twice" not in text)


# --- SC1-1 part A: every finding of a branch in ONE round (TP1-12586: six S3 repair rounds) ----------------

A1_DROPPED = ("observation_boundary", "applicable_scenarios", "decision", "execution_scope",
              "sufficiency_review", "coverage_links", "requirement_refs")


def sc11_branch_row(patch_ob, rid="TS-2"):
    """A valid v2 row whose reading `a` swaps in `patch_ob` as its obligation; `b` and `not_needed` leave the row as
    written, so nothing is `missing_branch` (m2: a fixture that names every letter and `not_needed`)."""
    return v2_row(rid, question_refs=["Q1"],
                  if_answered={"Q1": {"a": {"coverage_obligations": [patch_ob]}, "b": {}, "not_needed": {}}})


def sc11_new_errors(rows_, index=0, label="a"):
    """What the plan contract says of the variant that is NOT already said of the authored plan (the expected text)."""
    entry = rows_[index]["if_answered"]["Q1"]
    patched = list(rows_)
    patched[index] = PC.apply_patch(rows_[index], PC.resolve_patch(entry, label))
    base = set(PC.gate_plan_errors(rows_))
    return [e for e in PC.gate_plan_errors(patched) if e not in base]


def test_sc1_1_invalid_variant_names_every_contract_error() -> None:
    bad = obligation("OB-TS-2")
    for field in A1_DROPPED:
        bad.pop(field)
    rows_ = [sc11_branch_row(bad)]
    expected = sc11_new_errors(rows_)
    found = of_kind(run_pure(rows_), "invalid_variant")
    check_eq("A1: the obligation without seven fields is ONE invalid_variant finding", len(found), 1)
    check_eq("A1: the contract names seven errors on it (the control value of this key)", len(expected), 7)
    message = first(found)["message"]
    for error in expected:
        check_in(f"A1: the message names `{error[:48]}`", error, message)
    check_eq("A1: the message lists them all, in the contract's order, joined by `; `",
             message.split("break the plan contract: ", 1)[1].rsplit(" - ", 1)[0], "; ".join(expected))
    one = obligation("OB-TS-2")
    one.pop("applicable_scenarios")
    rows_ = [sc11_branch_row(one)]
    found = of_kind(run_pure(rows_), "invalid_variant")
    check_eq("A1 negative control: one omission gives exactly the one error in the message",
             (len(sc11_new_errors(rows_)), first(found)["message"].count("; ")), (1, 0))


def test_sc1_1_a_bad_key_hides_nothing_else() -> None:
    rows_ = [row("TS-1", question_refs=["Q1"], reason="rests on Q1",
                 if_answered={"Q1": {"a": {"coverage_delta": 1, "reason": "per Q1 and nothing else"},
                                     "b": {}, "not_needed": {}}})]
    found = run_pure(rows_)
    check_eq("A2: the key outside the list AND the stale reason of the same branch are both found",
             kinds(found), ["bad_branch", "stale_reason"])
    check_in("A2: the bad_branch names the key", "`coverage_delta`", first(found)["message"])
    check_in("A2: the stale_reason is the reading `a`'s", "once Q1 is answered (a)", found[1]["message"])
    rows_[0]["if_answered"]["Q1"]["a"].pop("reason")
    check_eq("A2 control: without the reason the bad key alone is found", kinds(run_pure(rows_)), ["bad_branch"])
    entry = {"c": {"level": "api"}, "a": {"reason": "per Q1"}, "b": {}, "not_needed": {}}
    check_eq("A2: a key that is no reading hides the rest of the branch no more",
             kinds(run_pure([row("TS-1", question_refs=["Q1"], if_answered={"Q1": entry})])),
             ["bad_branch", "stale_reason"])
    entry = {"a": "automate", "b": {"reason": "per Q1"}, "not_needed": {}}
    check_eq("A2: nor does a patch that is no object",
             kinds(run_pure([row("TS-1", question_refs=["Q1"], if_answered={"Q1": entry})])),
             ["bad_branch", "stale_reason"])
    check_eq("A2: a branch left with no patch object at all is judged no further (nothing to apply)",
             kinds(run_pure([row("TS-1", question_refs=["Q1"], if_answered={"Q1": {"c": {"level": "api"}, "a": "x"}})])),
             ["bad_branch", "bad_branch"])


def test_sc1_1_a_key_outside_the_list_is_never_applied() -> None:
    real = PC.apply_patch
    seen: list = []

    def spy(row_, patch):
        seen.append(copy.deepcopy(patch))
        return real(row_, patch)

    PC.apply_patch = spy
    try:
        found = run_pure([row("TS-1", question_refs=["Q1"],
                              if_answered={"Q1": {"a": {"coverage_delta": 1, "level": "api"},
                                                  "b": {"level": "api"}, "not_needed": {}}})])
    finally:
        PC.apply_patch = real
    check_eq("A3: one bad key and a right remainder: bad_branch and nothing more", kinds(found), ["bad_branch"])
    check("A3: the spy saw the patches (control: it is wired)", len(seen) >= 1)
    check("A3: a patch reached apply_patch with the right remainder", {"level": "api"} in seen)
    check_eq("A3: no patch reaching apply_patch carries a key outside the closed list",
             [p for p in seen if set(p) - set(PC.branch_patch_keys())], [])
    check("A3: the real function is back", PC.apply_patch is real)


def test_sc1_1_message_head_unchanged() -> None:
    bad = obligation("OB-TS-2")
    for field in A1_DROPPED:
        bad.pop(field)
    message = first(of_kind(run_pure([sc11_branch_row(bad)]), "invalid_variant"))["message"]
    head = "TS-2: if Q1 is answered (a) the row would break the plan contract: "
    check("A4: the head is byte for byte the old template", message.startswith(head))
    check("A4: the first error follows it at once", message[len(head):].startswith("OB-TS-2: missing observation_boundary"))
    check("A4: the tail is the author's rework, in place", message.endswith(" - the strategist's rework repairs this row"))
    check_eq("A4: the finding keeps its documented keys, none new",
             sorted(first(of_kind(run_pure([sc11_branch_row(bad)]), "invalid_variant"))),
             ["kind", "message", "owner", "question", "where"])


def sc11_observation(ref="t::x"):
    return {"claim_kind": ["ordinary"], "oracle_ref": {"ref": "R-1", "revision": "1"},
            "surfaces": [{"id": "S1", "boundary": "the HTTP response", "status": "planned", "assertion_ref": ref}],
            "controls": [], "completion_ref": ref, "source_conflicts": [],
            "independent_expectations": [{"partition_ref": "p1", "expected_ref": "e1",
                                          "attribution_assertion_ref": ref}]}


def sc11_delta(oid):
    return {"entries": [{"obligation_id": oid, "disposition": "gap", "rationale": "r", "gap_reason": "g"}],
            "counts": {"logical_cases_before": 0, "logical_cases_after": 1,
                       "executable_instances_before": 0, "executable_instances_after": 1},
            "baseline_kind": "initial", "initial_scope_rationale": "first plan", "planned_instance_ids": ["i1"]}


def sc11_12586_plan():
    """The shape of the 12586 loop. TS-2: the strategist's variants swap in OB-3 (six fields short), while the row's
    `coverage_delta` maps OB-2. TS-12: its variants swap in OB-17 short of the fields the plan contract names in the
    order the run saw them (observation_boundary, applicable_scenarios, execution_scope, coverage_links, a surface
    assertion_ref, a completion_ref, an expectation attribution) plus `decision`, whose value later asks for
    `planned_check_refs`: the conditional second round of review M2."""
    def authored(rid, oid):
        ob = dict(obligation(oid), observation_contract=sc11_observation())
        return row(rid, schema_version=2, coverage_contract_revision="coverage-observation-v1",
                   coverage_obligations=[ob], coverage_delta=sc11_delta(oid), question_refs=["Q1"])

    stub3 = obligation("OB-3")
    for field in ("observation_boundary", "applicable_scenarios", "execution_scope", "sufficiency_review",
                  "coverage_links"):
        stub3.pop(field)
    stub17 = dict(obligation("OB-17"), observation_contract=sc11_observation("t::gone"))
    for field in ("observation_boundary", "applicable_scenarios", "decision", "execution_scope",
                  "coverage_links", "planned_check_refs"):
        stub17.pop(field)
    rows_ = [authored("TS-2", "OB-2"), authored("TS-12", "OB-17")]
    for rid, stub in (("TS-2", stub3), ("TS-12", stub17)):
        target = next(r for r in rows_ if r["id"] == rid)
        target["if_answered"] = {"Q1": {"a": {"coverage_obligations": [copy.deepcopy(stub)]},
                                        "b": {"coverage_obligations": [copy.deepcopy(stub)]}, "not_needed": {}}}
    return rows_


def sc11_errors_of(finding, keep=None):
    """The contract errors a finding's message names; `keep` limits the view (the old two-error cut, on a COPY of
    the text: the module is not mutated)."""
    body = finding["message"].split("break the plan contract: ", 1)[1].rsplit(" - the strategist's rework", 1)[0]
    errors = body.split("; ")
    return errors if keep is None else errors[:keep]


def _sc11_set(field, value):
    return lambda ob, m: ob.__setitem__(field, copy.deepcopy(value))


def _sc11_observation_ref(part):
    def fix(ob, m):
        contract = ob["observation_contract"]
        if part == "surfaces":
            for surface in contract["surfaces"]:
                surface["assertion_ref"] = "t::x"
        elif part == "completion_ref":
            contract["completion_ref"] = "t::x"
        else:
            for item in contract["independent_expectations"]:
                item["attribution_assertion_ref"] = "t::x"
    return fix


_SC11_GOOD = obligation("OB-G")
# error text (after `<obligation id>: `) -> the fix: the table of the repairer, "text of the error -> field -> good value"
SC11_TABLE = (
    (r"missing (\w+):", lambda ob, m: ob.__setitem__(m.group(1), copy.deepcopy(_SC11_GOOD[m.group(1)]))),
    (r"(requirement_refs|applicable_scenarios) needs",
     lambda ob, m: ob.__setitem__(m.group(1), copy.deepcopy(_SC11_GOOD[m.group(1)]))),
    (r"decision: not filled", _sc11_set("decision", "new")),
    (r"execution_scope: not filled", _sc11_set("execution_scope", "current_task")),
    (r"sufficiency_review required", _sc11_set("sufficiency_review", _SC11_GOOD["sufficiency_review"])),
    (r"coverage_links needs a list", _sc11_set("coverage_links", [])),
    (r"planned_check_refs needs", _sc11_set("planned_check_refs", ["t::x"])),
    (r"observation_contract required", lambda ob, m: ob.__setitem__("observation_contract", sc11_observation())),
    (r"surface assertion_ref must", _sc11_observation_ref("surfaces")),
    (r"completion_ref must", _sc11_observation_ref("completion_ref")),
    (r"expectation attribution must", _sc11_observation_ref("attribution")),
)


def sc11_fix(rows_, finding, errors, unhandled, trapped):
    """The repairer: does EXACTLY what the viewed errors name (`SC11_TABLE`). Two moves are the run's own: with no
    way out in the text, a `coverage delta` error sends it to put `coverage_delta` into the patch (the trap of
    round 2, once per row), and the conductor's hand-made explanation of the closed list is the `bad_branch` move."""
    import re
    target = next(r for r in rows_ if r["id"] == finding["where"])
    patches = [p for p in target["if_answered"][finding["question"]].values() if "coverage_obligations" in p]
    mapped_ids = [e["obligation_id"] for e in target["coverage_delta"]["entries"]]

    def rename(ids):
        for patch in patches:
            for ob, oid in zip(patch["coverage_obligations"], ids):
                ob["obligation_id"] = oid

    if finding["kind"] == "bad_branch":
        for patch in patches:
            patch.pop("coverage_delta", None)
        rename(mapped_ids)
        return
    hinted = [m.group(1).split(", ") for m in (re.search(r"keep the obligation ids it maps \(([^)]*)\)", e)
                                               for e in errors) if m]
    for error in errors:
        owner, _, rest = error.partition(": ")
        if "keep the obligation ids it maps" in error:
            continue
        if owner == finding["where"] and rest.startswith("coverage delta"):
            if not hinted and finding["where"] not in trapped:
                trapped.add(finding["where"])
                for patch in patches:
                    patch["coverage_delta"] = sc11_delta(patch["coverage_obligations"][0]["obligation_id"])
            continue
        done = False
        for patch in patches:
            for ob in patch["coverage_obligations"]:
                for pattern, fix in SC11_TABLE:
                    m = re.match(pattern, rest)
                    if ob["obligation_id"] == owner and m:
                        fix(ob, m)
                        done = True
                        break
        if not done:
            unhandled.append(error)
    if hinted:
        rename(hinted[0])


def sc11_rounds(keep=None):
    """Rounds until the plan is clean, the repairer driven by the findings of each round. Returns (rounds, unhandled)."""
    rows_ = sc11_12586_plan()
    unhandled: list = []
    trapped: set = set()
    rounds = 0
    while rounds < 12:
        found = run_pure(rows_)
        if not found:
            return rounds, unhandled
        rounds += 1
        for finding in found:
            sc11_fix(rows_, finding, sc11_errors_of(finding, keep) if finding["kind"] == "invalid_variant" else [],
                     unhandled, trapped)
    return rounds, unhandled


def test_sc1_1_rounds_to_clean() -> None:
    rows_ = sc11_12586_plan()
    base = [e for e in PC.gate_plan_errors(rows_)]
    check_eq("A5: the authored plan of the fixture is valid (every finding is the variants')", base, [])
    found = run_pure(rows_)
    check_eq("A5: round 1 names one invalid_variant per row (a and b are one patch)",
             [(f["kind"], f["where"]) for f in found], [("invalid_variant", "TS-2"), ("invalid_variant", "TS-12")])
    check_eq("A5: TS-12's first round names all eight errors the run met two at a time",
             len(sc11_errors_of(found[1])), 8)
    check_in("A5: TS-2's round 1 carries the way out of the coverage_delta trap",
             "keep the obligation ids it maps (OB-2)", found[0]["message"])
    rounds, unhandled = sc11_rounds()
    check_eq("A5: the repairer left no error unhandled (the table covers what the messages name)", unhandled, [])
    check("A5 (measure, review M2): the 12586-shaped plan is clean in at most 2 rounds (was 6)", 1 <= rounds <= 2)
    print(f"A5 measure: rounds to clean = {rounds}")
    old_rounds, old_unhandled = sc11_rounds(keep=2)
    check("A5 control: the same repairer, shown only the first two errors of each message (the old cut, a COPY of "
          "the text), needs 4 rounds or more", old_rounds >= 4)
    print(f"A5 measure: rounds to clean with the old two-error view = {old_rounds}")


def test_sc1_1_a_head_word_still_passes() -> None:
    import waiver
    bad = obligation("OB-TS-2")
    for field in A1_DROPPED:
        bad.pop(field)
    message = first(of_kind(run_pure([sc11_branch_row(bad)]), "invalid_variant"))["message"]
    pipeline = {"stage_overrides": [{"stage": "S4", "decision": "go on", "match": "TS-2: if Q1 is answered (a)"}]}
    blocking, passed = waiver.split_overridden([message], pipeline, "S4")
    check_eq("A6: a word quoting the head of the message passes the new, long finding", (blocking, len(passed)), ([], 1))
    elsewhere = {"stage_overrides": [{"stage": "S4", "decision": "go on", "match": "TS-9: if Q1 is answered (a)"}]}
    blocking, passed = waiver.split_overridden([message], elsewhere, "S4")
    check_eq("A6 control: a word about another row does not", (len(blocking), passed), (1, []))


def test_sc1_1_the_coverage_delta_trap_has_a_way_out_in_the_message() -> None:
    rows_ = sc11_12586_plan()
    message = first(of_kind(run_pure(rows_), "invalid_variant"))["message"]
    check_in("A7: a patch under other obligation ids names the delta's ids",
             "the row's coverage_delta is not patchable: keep the obligation ids it maps (OB-2)", message)
    check("A7: the hint comes after the contract's errors and before the author's rework",
          message.index("must include every obligation") < message.index("not patchable")
          < message.index("the strategist's rework"))
    same = sc11_12586_plan()
    same[0]["if_answered"]["Q1"]["a"]["coverage_obligations"][0]["obligation_id"] = "OB-2"
    same[0]["if_answered"]["Q1"]["b"]["coverage_obligations"][0]["obligation_id"] = "OB-2"
    check_not_in("A7 control: the same ids as the delta's: no hint",
                 "not patchable", " ".join(f["message"] for f in run_pure(same)))
    plain = [sc11_branch_row(dict(obligation("OB-9"), requirement_refs=[]))]
    check_not_in("A7 control: a row with no coverage_delta: no hint",
                 "not patchable", " ".join(f["message"] for f in run_pure(plain)))
    odd = sc11_12586_plan()
    odd[0]["coverage_delta"] = {"entries": "x"}
    check_not_in("A7 control: a delta that is not a list of entries: no hint, no traceback",
                 "not patchable", " ".join(f["message"] for f in run_pure(odd)))
    odd[0]["if_answered"]["Q1"]["a"]["coverage_obligations"] = 5
    check_eq("A7: a garbage obligation list is still a finding, not a traceback",
             "invalid_variant" in kinds(run_pure(odd)), True)


def test_sc1_1_the_revision_is_read_from_the_constant_never_a_literal() -> None:
    import coverage_contract as CC
    delta_row = sc11_12586_plan()[0]
    patch = delta_row["if_answered"]["Q1"]["a"]
    hint = "keep the obligation ids it maps (OB-2)"
    check_in("A9: the hint is given for the contract's own revision", hint, PC._delta_hint(delta_row, patch))
    real = CC.COVERAGE_CONTRACT_REVISION
    CC.COVERAGE_CONTRACT_REVISION = "coverage-observation-v9"
    try:
        check_eq("A9: under another revision the row of the old one gets no hint (the constant is read, not a literal)",
                 PC._delta_hint(delta_row, patch), "")
        delta_row["coverage_contract_revision"] = "coverage-observation-v9"
        check_in("A9: and a row of that revision gets it", hint, PC._delta_hint(delta_row, patch))
    finally:
        CC.COVERAGE_CONTRACT_REVISION = real
    check("A9: the real constant is back", CC.COVERAGE_CONTRACT_REVISION == real)


def sc11_oracle_row(**extra):
    """A valid row that rests on Q1 and, on reading `a`, becomes `oracle_unknown` (the answer leaves the result unknown)."""
    return row("TS-1", question_refs=["Q1"],
               if_answered={"Q1": {"a": {"oracle_unknown": True}, "b": {}, "not_needed": {}}}, **extra)


def test_sc1_1_an_oracle_unknown_patch_names_the_row_side_way_out() -> None:
    message = first(of_kind(run_pure([sc11_oracle_row()]), "invalid_variant"))["message"]
    check_in("A8: the variant breaks the contract on the review the patch cannot set",
             "TS-1: independent design review required", message)
    check_in("A8: the finding says design_review_required is no patch key and where to set it",
             "`design_review_required` is not patchable: set `design_review_required: true` on the row itself, "
             "outside the branch", message)
    check("A8: the hint comes after the contract's error and before the author's rework",
          0 <= message.find("independent design review required") < message.find("is not patchable")
          < message.find("the strategist's rework"))
    check_not_in("A8: this finding carries no coverage_delta hint", "coverage_delta", message)
    check_eq("A8 control: a row already marked for review has no finding",
             of_kind(run_pure([sc11_oracle_row(design_review_required=True)]), "invalid_variant"), [])
    already = of_kind(run_pure([sc11_oracle_row(oracle_unknown=True)]), "invalid_variant")
    check_not_in("A8 control: a row that already needed the review (the error is the authored plan's, not the "
                 "variant's) gets no hint", "is not patchable", " ".join(f["message"] for f in already))
    other = sc11_oracle_row()
    other["if_answered"]["Q1"]["a"] = {"oracle_unknown": False}
    check_eq("A8 control: a patch that does not make the result unknown has no finding",
             of_kind(run_pure([other]), "invalid_variant"), [])
    open_list = of_kind(run_pure([sc11_oracle_row()], allow_keys=[*PC.branch_patch_keys(), "design_review_required"]),
                        "invalid_variant")
    check_not_in("A8 control: when the key IS in the closed list the hint is not given (it would be false)",
                 "is not patchable", " ".join(f["message"] for f in open_list))


def test_o3_the_register_ids_come_from_the_register_not_from_the_plan() -> None:
    plan = [row("TS-1", question_refs=["Q1"], if_answered={"Q1": FULL}), row("TS-2", question_refs=["Q-R14"])]
    root, task = story("qa-branches-ids-", plan=plan, questions=[register("Q1")])
    try:
        use_project(root)
        found = branch_findings(task).findings
        check_eq("only the alias is unresolved", [(f["where"], f["kind"]) for f in found], [("TS-2", "unresolved_ref")])
    finally:
        cleanup(root)
    root, task = story("qa-branches-answered-", plan=[row("TS-1", question_refs=["Q1"], if_answered={
        "Q1": {"a": {"level": "api"}}})], questions=[register("Q1")])
    try:
        use_project(root)
        (task / "work" / "question-answers.jsonl").write_text(json.dumps(
            {"kind": "question", "id": "Q1", "status": "answered", "reading": "a", "words": "Q1: a",
             "by": "person", "where": "gate A", "at": "2026-09-30T10:00:00+00:00"}) + "\n", encoding="utf-8")
        found = branch_findings(task).findings
        check_eq("a question the answers file settled still branching is a finding",
                 [f["kind"] for f in found], ["settled_question"])
    finally:
        cleanup(root)


def test_f_cmp2_15_a_row_names_its_requirements_in_every_spelling_the_plan_uses() -> None:
    # cmp2 (TP1-15045): TS-3 carried `requirement_refs: ["R-4"]` and `register:R-4`, and the
    # S3 exit gate refused "no plan row covers R-4" because the reader knew neither spelling.
    rr = PC.row_requirements
    check_eq("requirement_refs as strings", rr({"requirement_refs": ["R-4", "R-8"]}), ["R-4", "R-8"])
    check_eq("requirement_refs as {ref, revision} objects",
             rr({"requirement_refs": [{"ref": "R-4", "revision": "r1"}, {"ref": "R-8"}]}), ["R-4", "R-8"])
    check_eq("requirement_refs as one string", rr({"requirement_refs": "R-4"}), ["R-4"])
    check_eq("requirement_refs as one object", rr({"requirement_refs": {"ref": "R-4", "revision": "1"}}), ["R-4"])
    check_eq("`register:R-n` and `requirement:R-n` both read",
             rr({"risk_source_refs": ["register:R-4", "requirement:R-8"]}), ["R-4", "R-8"])
    check_eq("cmp1's `requirement_ids` still works", rr({"requirement_ids": ["R-2", "R-3"]}), ["R-2", "R-3"])
    check_eq("the older keys still work",
             rr({"requirements": "R-1", "covers": ["R-2"], "r": "R-3, R-5", "R": ["`R-6`"]}),
             ["R-1", "R-2", "R-3", "R-5", "R-6"])
    check_eq("ids are deduplicated across keys, the order of first appearance kept (keys read in the "
             "order requirements, requirement_ids, requirement_refs, ..., risk_source_refs)",
             rr({"requirement_refs": ["R-8", "R-4"], "risk_source_refs": ["register:R-4", "register:R-9"],
                 "requirement_ids": ["R-9", "R-8"]}), ["R-9", "R-8", "R-4"])
    check_eq("within one key the order is the row's own",
             rr({"requirement_refs": ["R-8", "R-4", {"ref": "R-8"}, "R-1"]}), ["R-8", "R-4", "R-1"])
    check_eq("a token that is not an R- id is ignored, and nothing is invented",
             rr({"requirement_refs": ["AC-4", "EXT-UI-1", {"ref": None}, {"revision": "r"}, 7],
                 "risk_source_refs": ["register:Reading forks Q6", "TP1-14482:AC4", "diff:a.py:5",
                                      "requirement:AC-1", 3, None]}), [])
    check_eq("the real id of a mixed `risk_source_refs` list is still found",
             rr({"risk_source_refs": ["TP1-14482:AC4", "register:R-4"]}), ["R-4"])
    check_eq("R-4 is not R-40", "R-4" in rr({"requirement_refs": ["R-40"]}), False)
    check_eq("R-40 is not R-4", "R-40" in rr({"requirement_refs": ["R-4"]}), False)
    for bad in (None, "R-4", ["R-4"], 7, ("R-4",)):
        check_eq(f"a row that is not a dict gives [] ({bad!r})", rr(bad), [])
    check_eq("an unreadable key value is skipped, not a crash",
             rr({"requirement_refs": 5, "requirements": None, "covers": ["R-2"]}), ["R-2"])
    # The gate that refused cmp2: the register contradicts R-4 and R-8, TS-3 and TS-6 cover them.
    register = ("## Contradiction matrix\n\n| R | parent | cases |\n|---|---|---|\n"
                '| R-4 | contradicts:"parent says 401" | silent |\n'
                '| R-8 | contradicts:"comment says 403" | silent |\n')
    rows = [{"id": "TS-3", "requirement_refs": ["R-4"], "risk_source_refs": ["register:R-4"],
             "source_conflict": True},
            {"id": "TS-6", "requirement_refs": [{"ref": "R-8", "revision": "r1"}], "oracle_unknown": True}]
    check_eq("the S3 gate finds TS-3 for R-4 and TS-6 for R-8", PC.contradiction_errors(rows, register), [])
    check_in("and still refuses when no row names the id in any spelling", "no plan row covers R-8",
             PC.contradiction_errors(rows[:1], register))


# --- t-227b: what the person's gate-A words DO (F14-F17, C1, C4, C5, C10, the stand cards) ------------------
# TP1-15045 (cmp2): six answers at gate A, no record of any, no row moved, two `accept as blocked` cards
# nobody read. `planning_contract.apply_gate_answers` is the executor; `story_run.record_by_code` calls it
# BEFORE the gate decision. The inputs of K3 are the real cmp2 files, copied byte for byte.

import hashlib  # noqa: E402

import question_register as QR  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "gate-a-answers"
CMP2 = "TP1-15045"
CMP2_CASES = {f"{CMP2}_TC_004": ("TS-4", "YAML-panel Version History button is still found"),
              f"{CMP2}_TC_008": ("TS-8", "Canvas shortcuts and drags with the history popup open"),
              f"{CMP2}_TC_014": ("TS-14", "Validate endpoint refuses unknown workflow, missing access"),
              f"{CMP2}_TC_017": ("TS-20", "Refactored history popup keeps defaults and WRITE-gated Restore")}


def read_lines(path: Path) -> list:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()] \
        if path.is_file() else []


def gate_a_story(prefix, plan, readiness, cases, *, ticket=CMP2, bare=False, plan_md=None, case_texts=None):
    """A story at gate A: the plan (`{"rows": ...}`, or a bare array), the register, the case files.
    `case_texts` {case id: whole file text} replaces the minimal file of that case (t-256 O7: TC_014 with its
    real `preconditions`)."""
    root = temp_dir(prefix)
    task = root / "qa-factory" / "artifacts" / ticket
    (task / "work" / "test-cases" / "area").mkdir(parents=True)
    (task / "state").mkdir(parents=True)
    (root / "qa-factory" / "config.json").write_text(json.dumps(
        {"schema_version": 1, "tests_root": "tests", "app_root": ".", "case_id_form": "{ticket}_TC_{nnn}"}),
        encoding="utf-8")
    (task / "work" / "test-plan.json").write_text(json.dumps(plan if bare else {"rows": plan}), encoding="utf-8")
    if isinstance(readiness, (bytes, str)):
        (task / "work" / "requirements-readiness.json").write_bytes(
            readiness if isinstance(readiness, bytes) else readiness.encode("utf-8"))
    else:
        (task / "work" / "requirements-readiness.json").write_text(
            json.dumps({"verdict": "blocked", "open_questions": readiness}), encoding="utf-8")
    for cid, (plan_row, title) in (cases or {}).items():
        (task / "work" / "test-cases" / "area" / f"{cid}.md").write_text(
            f"---\nid: {cid}\ntitle: {title}\nplan_row: {plan_row}\n---\n\n## Then\n1. x.\n", encoding="utf-8")
    for cid, text in (case_texts or {}).items():
        (task / "work" / "test-cases" / "area" / f"{cid}.md").write_text(text, encoding="utf-8", newline="\n")
    (task / "pipeline.json").write_text(json.dumps({"ticket": ticket, "stages": {}}), encoding="utf-8")
    if plan_md is not None:
        (task / "test-plan.md").write_bytes(plan_md.encode("utf-8"))
    use_project(root)
    return root, task


def manifest_of(task: Path) -> dict:
    """The automation manifest, or an empty one: a missing file is a FAIL line below, never a traceback."""
    path = task / "work" / "automation-manifest.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {"unresolved": []}


def manifest_bytes(task: Path) -> bytes:
    path = task / "work" / "automation-manifest.json"
    return path.read_bytes() if path.is_file() else b""


def plan_of(task: Path):
    return json.loads((task / "work" / "test-plan.json").read_text(encoding="utf-8"))


def rows_of(task: Path) -> dict:
    document = plan_of(task)
    return {r["id"]: r for r in (document["rows"] if isinstance(document, dict) else document)}


def repaired_cmp2_rows() -> list:
    """The cmp2 plan as S3 would have to leave it: a branch for every answer on the five rows that named a
    question and had none (TS-1/Q3, TS-3/Q2, TS-6/Q1, TS-11/Q5, TS-13/Q6) and `not_needed` on TS-4/Q4."""
    rows = json.loads((FIXTURES / "cmp2-test-plan.json").read_text(encoding="utf-8-sig"))["rows"]
    by = {r["id"]: r for r in rows}
    # t-256 O10 (F22): all six rows are `oracle_unknown: true`, so every reading's branch says the answer
    # settles it (`oracle_unknown: false`); TS-4's `b` sets a manual disposition and names its P19 rung.
    for rid, qid in (("TS-1", "Q3"), ("TS-3", "Q2"), ("TS-6", "Q1"), ("TS-13", "Q6")):
        by[rid]["if_answered"] = {qid: {"*": {"oracle_unknown": False}, "not_needed": {}}}
    by["TS-11"]["if_answered"] = {"Q5": {
        "a": {"disposition": "automate", "level": "api", "oracle_unknown": False,
              "reason": "The stored state is read through the API around a UI restore; the owner confirmed reading a."},
        "b": {"oracle_unknown": False}, "not_needed": {}}}
    by["TS-4"]["if_answered"]["Q4"]["not_needed"] = {}
    by["TS-4"]["if_answered"]["Q4"]["a"]["oracle_unknown"] = False
    # E-19 (an older check, found by this very fixture): TS-4's `b` moves the row to a check by an agent and
    # leaves the authored reason, which names Q4; the strategist patches the reason that remains.
    by["TS-4"]["if_answered"]["Q4"]["b"].update(
        reason="The label assertion is checked by an agent by hand.", oracle_unknown=False,
        test_level_rationale="P19 rung 3: a label is brittle at e2e and no lower level reads it; an agent shows it.")
    return rows


def test_f14_a_row_that_rests_on_a_question_carries_a_branch_for_every_answer() -> None:
    """F14/F15 as a pure check. A row RESTS on Q when Q is in `question_refs` or Q's id stands as a whole token
    in its `reason`; then `if_answered[Q]` needs a key for every reading letter (or `*`) plus `not_needed`."""
    def missing(rows, questions=None, **kw):
        return of_kind(run_pure(rows, questions, missing=True, **kw), "missing_branch")

    one = row("TS-5", question_refs=["Q1"])
    found = missing([one])
    check_eq("a row that names Q1 and says nothing about it: one finding", [(f["where"], f["question"]) for f in found],
             [("TS-5", "Q1")])
    check_in("it names the answers that have no branch, `not_needed` among them", "no branch for a, b, not_needed",
             first(found)["message"])
    check_eq("...and it is the strategist's", first(found)["owner"], "strategist")
    check_in("...with the way out for 'the row stays as written'", "an empty object `{}` says the row stays as written",
             first(found)["message"])
    for name, entry, lacking in (("{} (an empty entry)", {}, "a, b, not_needed"),
                                 ("only a of two readings", {"a": {}, "not_needed": {}}, "b"),
                                 ("a and b, no not_needed", {"a": {}, "b": {}}, "not_needed"),
                                 ("`*` alone", {"*": {}}, "not_needed"),
                                 ("`not_needed` alone", {"not_needed": {}}, "a, b")):
        got = missing([row("TS-5", question_refs=["Q1"], if_answered={"Q1": entry})])
        check_eq(f"{name}: refused, naming what is lacking",
                 [f["message"].split("no branch for ")[1].split(" - ")[0] for f in got], [lacking])
    for name, entry in (("a, b, not_needed", {"a": {}, "b": {}, "not_needed": {}}), ("`*` and not_needed", {"*": {}, "not_needed": {}}),
                        ("a letter over `*`", {"a": {"level": "api"}, "*": {}, "not_needed": {}})):
        check_eq(f"{name}: complete", missing([row("TS-5", question_refs=["Q1"], if_answered={"Q1": entry})]), [])
    # three readings: every letter is asked for
    check_in("Q3 has three readings: a, b and c", "no branch for c, not_needed",
             first(missing([row("TS-5", question_refs=["Q3"], if_answered={"Q3": {"a": {}, "b": {}}})]))["message"])
    check_in("a question with NO readings only owes `not_needed`", "no branch for not_needed -",
             first(missing([row("TS-5", question_refs=["Q1"])], questions=[q("Q1", 0)]))["message"])
    # the id token: a reason that names the question rests on it, with no question_refs at all
    got = missing([row("TS-5", reason="expected value per Q10.", question_refs=["Q1"],
                       if_answered={"Q1": {"*": {}, "not_needed": {}}})])
    check_eq("a reason naming Q10 rests on Q10 (and Q1, branched, is fine)", [(f["where"], f["question"]) for f in got],
             [("TS-5", "Q10")])
    check_eq("`Q1` in a reason is not `Q10`: a reason naming Q10 does not make the row rest on Q1",
             [f["question"] for f in missing([row("TS-5", reason="see Q10", question_refs=["Q10"],
                                                  if_answered={"Q10": {"*": {}, "not_needed": {}}})])], [])
    check_eq("a reason in lower case (`q1`) is no id token: the row rests on nothing",
             missing([row("TS-5", reason="see q1"), row("TS-6", question_refs=["Q2"],
                                                      if_answered={"Q2": {"*": {}, "not_needed": {}}})]), [])
    check_eq("`Q-R14` and `q1` as a ref are unresolved refs, never branches asked for",
             kinds(run_pure([row("TS-5", question_refs=["q1", "Q-R14"])], missing=True)), ["unresolved_ref", "unresolved_ref"])
    check_eq("Q50 is not Q5: a reason that names Q50 does not rest on Q5",
             [f["question"] for f in missing([row("TS-5", reason="rests on Q50", question_refs=["Q50"])],
                                             [q("Q5"), q("Q50", 3)])], ["Q50"])
    # C4: a settled question is never asked for a branch
    for status in ("answered", "not_needed"):
        check_eq(f"a {status} question needs no branch (C4): the row that names it is not refused",
                 missing([row("TS-5", question_refs=["Q1"])], [q("Q1", status=status)]), [])
    check_eq("an open one beside it still is", [f["question"] for f in missing(
        [row("TS-5", question_refs=["Q1", "Q2"])], [q("Q1", status="answered"), q("Q2")])], ["Q2"])
    # position/invariants: a story with no branch field is never refused; a malformed `if_answered` is bad_branch's
    check_eq("a plan where only a REASON names a question is a story with no branch field: never refused",
             run_pure([row("TS-5", reason="rests on Q1")], missing=True), [])
    got = run_pure([row("TS-5", question_refs=["Q1"], if_answered=["Q1"])], missing=True)
    check_eq("an `if_answered` that is no object is `bad_branch` and not also a missing branch", kinds(got), ["bad_branch"])
    got = run_pure([row("TS-5", question_refs=["Q1"], if_answered={"Q1": "a"})], missing=True)
    check_eq("an entry that is no object is `bad_branch` only", kinds(got), ["bad_branch"])
    check_eq("a row that names no question and whose reason names none is never touched",
             missing([row("TS-5", question_refs=["Q1"], if_answered={"Q1": {"*": {}, "not_needed": {}}}), row("TS-6")]), [])
    check_eq("the S3 exit reads the same finding (`s3_branch_refusals`, RN1-2)", True,
             PC.s3_branch_refusals is not None and "missing_branch" in PC.S3_EXIT_KINDS and "missing_branch" in PC.BRANCH_KINDS)


def test_k3_the_s3_exit_names_the_five_rows_and_the_one_branch_the_cmp2_plan_lacks() -> None:
    plan = json.loads((FIXTURES / "cmp2-test-plan.json").read_text(encoding="utf-8-sig"))["rows"]
    root, task = gate_a_story("qa-k3-s3-", plan, (FIXTURES / "cmp2-requirements-readiness.json").read_bytes(),
                              CMP2_CASES)
    try:
        questions = QR.load(task)["questions"]
        check_eq("the cmp2 register reads: six open questions of two readings",
                 [(q["id"], q["status"], q["letters"]) for q in questions], [(f"Q{n}", "open", "ab") for n in range(1, 7)])
        refused, unread = PC.s3_branch_refusals(task, plan)
        check_eq("K3: the register is read (nothing unread)", unread, "")
        found = [f for f in refused if f["kind"] == "missing_branch"]
        check_eq("K3: the S3 exit finds exactly TS-1/Q3, TS-3/Q2, TS-6/Q1, TS-11/Q5, TS-13/Q6 and TS-4/Q4",
                 sorted({(f["where"], f["question"]) for f in found}),
                 [("TS-1", "Q3"), ("TS-11", "Q5"), ("TS-13", "Q6"), ("TS-3", "Q2"), ("TS-4", "Q4"), ("TS-6", "Q1")])
        said = {f["where"]: f["message"] for f in found}
        check_in("TS-11 lacks a, b and not_needed", "no branch for a, b, not_needed", said.get("TS-11", ""))
        ts4 = [f["message"] for f in found if f["where"] == "TS-4"]
        check_in("TS-4 has a and b and lacks not_needed", "no branch for not_needed -", " | ".join(ts4))
        check_not_in("...and is not blamed for a missing a or b branch", "no branch for a", " | ".join(ts4))
        # t-256 O10, the K3 consequence: TS-4's branches also have to say what the answer settles - the row is
        # `oracle_unknown` and its `a`/`b` did not clear it (the cmp2 "the answer changed nothing" class), and its
        # `b` sets a manual disposition with no `test_level_rationale`.
        check_eq("O10: TS-4 is refused three ways until repaired (not_needed, oracle_unknown, rationale)",
                 sorted(f.get("lacking", "") for f in found if f["where"] == "TS-4"),
                 ["`oracle_unknown: false` for a, b", "`test_level_rationale` for b", "not_needed"])
        check_eq("every finding is the strategist's", {f["owner"] for f in found}, {"strategist"})
        check_eq("no row the plan has without a question is named", {f["where"] for f in found} & {"TS-2", "TS-5", "TS-10"},
                 set())
        check_eq("repaired as the strategist must: no missing branch, and no other finding either",
                 PC.variant_errors(repaired_cmp2_rows(), questions, ()), [])
    finally:
        cleanup(root)


def test_k3_the_six_cmp2_answers_move_ts_11_and_record_q1_to_q6() -> None:
    # t-256 O6: the cmp2 answers file as the person wrote it (line 20 is PROSE: "accept as blocked on localhost; S5
    # reports exactly those partitions") applies no stand card - see the negative test below. The token form of the
    # same two cards (`<case id>: accept as blocked`, one case per line, full or short id) is the fixture used here.
    answers = (FIXTURES / "cmp2-s4-gate-a-tokens.md").read_text(encoding="utf-8")
    tc14 = (FIXTURES / "cmp2-TC_014.md").read_text(encoding="utf-8")
    root, task = gate_a_story("qa-k3-apply-", repaired_cmp2_rows(),
                              (FIXTURES / "cmp2-requirements-readiness.json").read_bytes(), CMP2_CASES,
                              case_texts={f"{CMP2}_TC_014": tc14})
    try:
        plan_path = task / "work" / "test-plan.json"
        before_doc = plan_of(task)
        before_rows = rows_of(task)
        check("temporal: the answers file does not exist yet (every story before this change)",
              not (task / "work" / "question-answers.jsonl").exists())
        lines = PC.apply_gate_answers(task, answers)
        after_doc = plan_of(task)
        after_rows = rows_of(task)
        check_eq("C1: the plan's top-level key set is the same before and after (a row-level patch only)",
                 (sorted(before_doc), sorted(after_doc)), (["rows"], ["rows"]))
        check_eq("K3: TS-11 moved by its Q5:a branch (a check by an agent -> an automated test)",
                 (before_rows["TS-11"]["disposition"], after_rows["TS-11"]["disposition"]), ("manual-agent", "automate"))
        check_eq("...with its whole patch laid over it", (after_rows["TS-11"]["level"], after_rows["TS-11"]["oracle_unknown"]),
                 ("api", False))
        check_eq("K3: TS-4 stays automate (answer a is the row as authored)",
                 (before_rows["TS-4"]["disposition"], after_rows["TS-4"]["disposition"]), ("automate", "automate"))
        check("C4: an applied question leaves question_refs and if_answered (TS-11, TS-4)",
              all("question_refs" not in after_rows[r] and "if_answered" not in after_rows[r] for r in ("TS-11", "TS-4", "TS-1")))
        # t-261: a row checked by an agent by hand is no longer "untouched" - its obligations are made executable
        # (the pass, see the t-261 section below); every other row that rests on no question is byte for byte as it was
        untouched = [rid for rid in before_rows if rid not in ("TS-1", "TS-3", "TS-4", "TS-6", "TS-11", "TS-13")
                     and before_rows[rid]["disposition"] != "manual-agent"]
        check_eq("a row that rests on no question and is not checked by hand is byte for byte as it was",
                 [after_rows[r] for r in untouched], [before_rows[r] for r in untouched])
        view = QR.load(task)
        check_eq("K3: Q1-Q6 are `answered`, each with its letter, at gate A, by the driver",
                 [(q["id"], q["status"], q["reading"], q["where"]) for q in view["questions"]],
                 [(f"Q{n}", "answered", letter, "gate A") for n, letter in enumerate("abaaaa", 1)])
        records = read_lines(task / "work" / "question-answers.jsonl")
        applied = [r for r in records if r.get("kind") == "answers_applied"]
        check_eq("the file was CREATED: six answers and, beside each, one `answers_applied` record",
                 ([r.get("kind", "question") for r in records].count("question"), len([r for r in applied if r["what"] == "question"])),
                 (6, 6))
        by_id = {r["id"]: r for r in applied if r["what"] == "question"}
        check_eq("the record of Q5 says which row it moved and by which letter",
                 (by_id["Q5"]["answer"], by_id["Q5"]["rows"], by_id["Q5"]["by"], by_id["Q5"]["where"]),
                 ("a", ["TS-11"], "driver", "gate A"))
        check_eq("the record of Q4 names TS-4 (the branch was applied, nothing moved)", by_id["Q4"]["rows"], ["TS-4"])
        printed = [ln for ln in lines if ln.startswith("gate A: Q")]
        moved = [ln for ln in printed if " - " in ln]
        check_eq("the person reads ONE line per row an answer changed: the six rows (t-256 O10: each branch now clears "
                 "`oracle_unknown`, so every one of them changed)", len(moved), 6)
        moved = [ln for ln in moved if "becomes" in ln]
        check_eq("...and only TS-11 changes HOW it is checked", len(moved), 1)
        check("...it says the row (with what it verifies, in the strategist's own words), the answer and the change",
              moved[0].startswith("gate A: Q5 = `a` - TS-11 (Restoring a revision") and
              moved[0].endswith("): a check by an agent, by hand becomes an automated test."), moved[0])
        check_in("and one line that the six answers were recorded",
                 "gate A: answers recorded by code - Q1: a, Q2: b, Q3: a, Q4: a, Q5: a, Q6: a", lines)
        # the stand cards of the same words (Lead's addition of 14:00)
        manifest = manifest_of(task)
        check_eq("K3: TC_014 got a `blocked_by_env` row, with no instance named (the automator names them, t-219)",
                 [(r["case"], r["reason"], "instance_ids" in r) for r in manifest["unresolved"]],
                 [(f"{CMP2}_TC_014", "blocked_by_env", False)])
        check_in("...whose detail is the person's own token line", "accepted as blocked by the person at gate A: "
                 f"{CMP2}_TC_014: accept as blocked", " ".join(r.get("detail", "") for r in manifest["unresolved"]))
        # O6/O7: the row carries the CARD'S partitions (2 of the 4) and a remedy derived from the case's own items
        row14 = manifest["unresolved"][0]
        check_eq("O6: the row names the two partitions the TC_014 card named, not the whole case (P-unknown/P-owner run)",
                 row14.get("partitions"), ["P-nowrite", "P-noproject"])
        check_eq("O7: the remedy is derived from the two `account` items: kind credential, where names the case and "
                 "its precondition ids, change is what the items say",
                 row14.get("remedy"),
                 {"kind": "credential", "where": f"{CMP2}_TC_014 preconditions PC-1, PC-2",
                  "change": "a non-admin user inside W's project with read-only ability (no WRITE); a non-admin user "
                            "outside W's project"})
        import acceptance as AC
        import contract as C
        refused: list = []
        got = AC.blocked_instances({"tests": [{"instance_id": "i1", "case": f"{CMP2}_TC_014", "covers": [f"{CMP2}_TC_014"]}],
                                    "unresolved": manifest["unresolved"]}, [{"instance_id": "i1"}],
                                   {f"{CMP2}_TC_014": ["i1"]}, task, runs={}, refused=refused)
        check_eq("O7: `acceptance.blocked_instances` does NOT answer `no_remedy` for the applier's row: it blocks i1",
                 (sorted(got), [kind for kind, _id, _text in refused]), (["i1"], []))
        check_eq("...and the remedy is one the contract accepts", C.remedy_errors(row14["remedy"]), [])
        check_eq("K3: TC_004 and TC_008 (answered later, in S5) are untouched",
                 [r["case"] for r in manifest["unresolved"] if r["case"].endswith(("_TC_004", "_TC_008"))], [])
        # O8: TS-20 is `manual-agent`: the S6 agent WILL try it, so "nothing to block" was a false promise
        check_in("TC_017 is on TS-20, a check by an agent by hand: S5 blocks nothing and the agent still tries it (O8)",
                 f"gate A: {CMP2}_TC_017 (Refactored history popup keeps defaults and WRITE-gated Restore) is not run by "
                 "an automated test (a check by an agent, by hand), so S5 blocks nothing for it, and the agent that checks "
                 "it by hand will still try it on the stand as it is; your word is recorded", lines)
        check_not_in("...and does not say there is nothing to block", "there is nothing to block", "\n".join(lines))
        check_in("TC_014 is told to the person, with the two partitions", f"gate A: {CMP2}_TC_014: accepted as blocked "
                 "for P-nowrite, P-noproject - S5 reports those partitions as not executed instead of running them.", lines)
        check_eq("both cards are on the file (`accept_as_blocked`), the case that is not run included",
                 sorted(r["id"] for r in applied if r["what"] == "accept_as_blocked"),
                 [f"{CMP2}_TC_014", f"{CMP2}_TC_017"])
        # idempotent: the same words again (a decision that did not record, a relaunch)
        stamp = (plan_path.read_bytes(), len(read_lines(task / "work" / "question-answers.jsonl")),
                 manifest_bytes(task))
        again = PC.apply_gate_answers(task, answers)
        check_eq("the same words applied twice: no line, no second record, no second plan write, no second manifest row",
                 (again, plan_path.read_bytes(), len(read_lines(task / "work" / "question-answers.jsonl")),
                  manifest_bytes(task)), ([],) + stamp)
    finally:
        cleanup(root)
    # the same cards when the row IS automated: TC_017 gets its row too
    plan = repaired_cmp2_rows()
    next(r for r in plan if r["id"] == "TS-20")["disposition"] = "automate"
    root, task = gate_a_story("qa-k3-apply-auto-", plan, (FIXTURES / "cmp2-requirements-readiness.json").read_bytes(),
                              CMP2_CASES)
    try:
        PC.apply_gate_answers(task, answers)
        manifest = manifest_of(task)
        check_eq("a card on an automated row is written as a row: TC_014 and TC_017, never TC_004 or TC_008",
                 sorted(r["case"] for r in manifest["unresolved"]), [f"{CMP2}_TC_014", f"{CMP2}_TC_017"])
    finally:
        cleanup(root)


def test_c1_the_decision_binds_the_patched_plan_because_the_call_stands_before_it() -> None:
    """DC1-19: the executor of a gate A answer is the controller's `gate-decision` (the driver and the conductor call the same one):
    the answers are laid over the plan first, then the request is built, which reads the plan file (`plan_content_hash`). A patch placed
    after it leaves the decision binding the unpatched plan, and every S5 dispatch then refuses "plan content changed". The calls here
    are the real `controller.main` on the throwaway gate A story of `test_gate_words_road` (Q10 branching TS-1)."""
    import test_gate_words_road as GW
    from event_store import content_hash
    g = GW.GateA()
    try:
        plan = GW.MP.plan_of(g.task)
        row_ = {r["id"]: r for r in plan["rows"]}["TS-1"]
        row_["disposition"] = "manual-agent"
        row_["if_answered"]["Q10"]["a"] = {"disposition": "automate", "reason": "Q10 a: the first reading holds."}
        g.plan_path.write_text(json.dumps(plan, indent=1), encoding="utf-8")
        unpatched = content_hash(GW.MP.plan_of(g.task))
        code, out, _ = g.call("approve as is\nQ10: a\n")
        final = content_hash(GW.MP.plan_of(g.task))
        check_eq("the decision is recorded", (code, out.get("recorded")), (0, True))
        bound = out["decision"]["payload"]["plan_content_hash"]
        check("the hash the decision reads is the PATCHED plan's (the answers were laid over the plan first)",
              bound == final and final != unpatched, f"{bound[:8]} {final[:8]} {unpatched[:8]}")
        check_eq("the applied row says what the person decided", g.row()["disposition"], "automate")
        check_in("the person reads what moved, in the controller's own answer", "gate A: Q10 = `a` - TS-1",
                 " | ".join(out["questions"]["lines"]))
        # gate B applies no answer to the plan: `test_gate_words_road` d7 (the plan bytes of a gate B call are equal)
        # an applier that fails: its line stands in the answer, the decision is still recorded (P1)
        held = PC._apply_gate_answers

        def boom(*args, **kwargs):
            raise RuntimeError("the register broke")

        PC._apply_gate_answers = boom
        try:
            code, out, _ = g.call("approve as is\nQ11: a\n")
        finally:
            PC._apply_gate_answers = held
        check_eq("a failure in the applier does not stop the decision", (code, out.get("recorded")), (0, True))
        check_in("...and its line is in the answer", "the answers could not all be applied (RuntimeError: the register broke); the decision is still recorded",
                 " | ".join(out["questions"]["lines"]))
    finally:
        cleanup(g.root)


def test_the_stand_card_rows_go_through_the_callers_own_manifest_put() -> None:
    """The driver passes `put` (its own `self.py`, so the script runs from the project root with the driver's
    environment); the fragment is the one `manifest_put.py --fragment` reads."""
    cases = {f"{CMP2}_TC_014": ("TS-14", "Validate endpoint refuses unknown workflow"),
             f"{CMP2}_TC_015": ("TS-15", "Validate endpoint answers like the update")}
    plan = [row("TS-14", disposition="automate"), row("TS-15", disposition="automate")]
    root, task = gate_a_story("qa-stand-put-", plan, [register("Q1")], cases)
    try:
        calls = []
        PC.apply_gate_answers(task, "TC_014: accept as blocked.",
                              put=lambda fragment: calls.append(fragment) or (0, "automation-manifest.json: revision 1"))
        fragment = json.loads(calls[0])
        check_eq("one call, one fragment, the case's FULL id, no instance named",
                 (len(calls), list(fragment), [(r["case"], r["reason"]) for r in fragment["unresolved"]]),
                 (1, ["unresolved"], [(f"{CMP2}_TC_014", "blocked_by_env")]))
        records = [r for r in read_lines(task / "work" / "question-answers.jsonl") if r.get("kind") == "answers_applied"]
        check_eq("and the card is on the file", [(r["what"], r["id"]) for r in records],
                 [("accept_as_blocked", f"{CMP2}_TC_014")])
        # a manifest_put that refuses: said in one line, nothing recorded as applied, the story goes on
        lines = PC.apply_gate_answers(task, "TC_015: accept as blocked,", put=lambda fragment: (1, "no manifest here"))
        check_in("a failed write is said, with what then happens", "the blocked cases could not be written to the "
                 f"automation manifest (no manifest here); S5 will run {CMP2}_TC_015 unless the automator is told",
                 "\n".join(lines))
        check_eq("...and a card that was not written is not on the file as applied (a rerun writes it)",
                 sorted(r["id"] for r in read_lines(task / "work" / "question-answers.jsonl")
                        if r.get("kind") == "answers_applied"), [f"{CMP2}_TC_014"])
        # t-1253 F-3: exit 4 = the rows ARE in the journal and only the manifest's projection is stale: the line names
        # the replay, and does not say the cases "could not be written"
        lines = "\n".join(PC.apply_gate_answers(
            task, "TC_015: accept as blocked,",
            put=lambda fragment: (4, "manifest_put: event committed; projection stale - the fragment is in the journal")))
        check_in("t-1253 F-3: a stale projection names the replay as the move",
                 f"unless `manifest_put.py --task {task.name} --recover` is run first", lines)
        check("t-1253 F-3: ... and does not call the committed rows unwritten",
              "could not be written" not in lines and "unless the automator is told" not in lines, lines)
    finally:
        cleanup(root)


def test_edge_own_wording_two_answers_a_letter_beyond_and_q50_are_never_applied() -> None:
    qs = [register("Q5"), register("Q50", 3), register("Q1")]
    ifa = {"a": {"disposition": "automate"}, "b": {}, "not_needed": {}}
    plan = [row("TS-5", disposition="manual-agent", question_refs=["Q5"], if_answered={"Q5": ifa}),
            row("TS-1", disposition="manual-agent", question_refs=["Q1"], if_answered={"Q1": ifa})]
    root, task = gate_a_story("qa-edges-", plan, qs, {})
    try:
        plan_path = task / "work" / "test-plan.json"
        before = plan_path.read_bytes()
        # (F16) the person's OWN wording: no token, nothing applied, one line per question that has a row
        lines = PC.apply_gate_answers(task, "Both of these are fine as they stand, go on.")
        check_eq("own wording: the plan is untouched", plan_path.read_bytes(), before)
        check_eq("...and nothing is recorded", read_lines(task / "work" / "question-answers.jsonl"), [])
        check_in("...one line names Q5 and what stays", "gate A: Q5 has no answer of the form `Q5: <letter>` or "
                 "`Q5: not needed`, so nothing is applied for it: TS-5 stay as planned and the question stays open", lines)
        # t-261: the manual-agent pass says one more line for each `manual-agent` row that lists no obligation
        # (these rows are plan rows of the old shape); the lines about the QUESTIONS are the two below
        check_eq("...and one for Q1 (a question no row rests on, Q50, gets none)",
                 len([ln for ln in lines if ln.startswith("gate A: Q")]), 2)
        check_eq("...and the pass names the two rows it could not make executable (they list no obligation)",
                 len([ln for ln in lines if "plan lists nothing the check must prove" in ln]), 2)
        # two answers for one question: nothing for it
        lines = PC.apply_gate_answers(task, "Q5: a\nQ5: b")
        check_eq("two answers for one question: the plan is untouched", plan_path.read_bytes(), before)
        check_in("...and the line says so", "gate A: Q5 has two different answers (a, b); nothing is applied for it "
                 "and it stays open", lines)
        # a letter beyond the readings
        lines = PC.apply_gate_answers(task, "Q5: c")
        check_eq("a letter beyond the two readings: nothing applied", plan_path.read_bytes(), before)
        check_in("...said", "gate A: Q5: the letter c is beyond its 2 readings; nothing is applied for it and it "
                 "stays open", lines)
        # `Q50: a` answers Q50 (3 readings, no row), never Q5
        lines = PC.apply_gate_answers(task, "Q50: a")
        check_eq("`Q50: a` is not an answer to Q5: its row stays as authored", rows_of(task)["TS-5"]["disposition"], "manual-agent")
        view = {q["id"]: q["status"] for q in QR.load(task)["questions"]}
        check_eq("...and Q5 is still open while Q50 is answered", (view["Q5"], view["Q50"]), ("open", "answered"))
        # an id that is not in the register at all
        lines = PC.apply_gate_answers(task, "Q9: a")
        check_in("an id that is no question of the story is named", "not questions of this story, so nothing is "
                 "recorded for them: Q9", lines)
        # `not needed` applies the not_needed patch (the row stays as written) and strips the question
        lines = PC.apply_gate_answers(task, "Q5: not needed")
        row5 = rows_of(task)["TS-5"]
        check_eq("`Q5: not needed`: the row keeps its disposition and loses the question",
                 (row5["disposition"], "question_refs" in row5, "if_answered" in row5), ("manual-agent", False, False))
        check_eq("...and Q5 is `not_needed` in the register", {q["id"]: q["status"] for q in QR.load(task)["questions"]}["Q5"],
                 "not_needed")
        # a letter, then the other one for the same question: the first answer stands (FR-7: nothing is re-asked or re-applied)
        lines = PC.apply_gate_answers(task, "Q1: a")
        check_eq("Q1: a moves TS-1", rows_of(task)["TS-1"]["disposition"], "automate")
        lines = PC.apply_gate_answers(task, "Q1: b")
        check_eq("a later `Q1: b` changes nothing: the plan keeps following the first answer",
                 rows_of(task)["TS-1"]["disposition"], "automate")
        check_in("...and says so", "gate A: Q1 was already settled (`a`), so what you wrote now for it changes nothing",
                 "\n".join(lines))
    finally:
        cleanup(root)


def test_edge_the_answers_file_is_created_or_appended() -> None:
    plan = [row("TS-1", disposition="manual-agent", question_refs=["Q1"],
                if_answered={"Q1": {"a": {"disposition": "automate"}, "b": {}, "not_needed": {}}})]
    root, task = gate_a_story("qa-append-", plan, [register("Q1"), register("Q2")], {})
    try:
        path = task / "work" / "question-answers.jsonl"
        old = {"kind": "question", "id": "Q2", "status": "answered", "reading": "b", "words": "Q2: b",
               "by": "person", "where": "S3 stop", "at": "2026-10-01T09:00:00+00:00",
               "row_hash": hashlib.sha256(b"x").hexdigest()}
        path.write_text(json.dumps(old) + "\n", encoding="utf-8")
        PC.apply_gate_answers(task, "Q1: a\nQ2: a")
        records = read_lines(path)
        check_eq("an existing file is APPENDED to: its record is the first line, unchanged", records[0], old)
        check_eq("Q2, settled at the S3 stop, keeps that answer: nothing more is recorded for it",
                 [r["id"] for r in records[1:] if r.get("kind") == "question"], ["Q1"])
        check_eq("...and the register still reads Q2 as the S3 stop's `b`",
                 {q["id"]: (q["status"], q["reading"], q["where"]) for q in QR.load(task)["questions"]}["Q2"],
                 ("answered", "b", "S3 stop"))
    finally:
        cleanup(root)


def test_edge_manual_cards_and_blocked_cards_on_rows_that_are_not_run() -> None:
    cases = {"QA-9_TC_001": ("TS-1", "first"), "QA-9_TC_002": ("TS-2", "second"), "QA-9_TC_003": ("TS-3", "third"),
             "QA-9_TC_004": ("TS-4", "fourth"), "QA-9_TC_005": ("TS-4", "fifth"), "QA-9_TC_006": ("TS-9", "sixth")}
    plan = [row("TS-1", disposition="automate"), row("TS-2", disposition="manual-human"),
            row("TS-3", disposition="automate"), row("TS-4", disposition="automate")]
    root, task = gate_a_story("qa-cards-", plan, [register("Q1")], cases, ticket="QA-9")
    try:
        words = ("QA-9_TC_001: manual\n"
                 "- TC_002: accept as blocked\n"
                 "TC_003: accept as blocked.\n"
                 "QA-9_TC_099: accept as blocked\n"
                 "QA-9_TC_004: manual\n"
                 "QA-9_TC_006: accept as blocked\n"
                 "accept as blocked\n"
                 "> QA-9_TC_001: accept as blocked (a quoted line is no answer)\n")
        puts = []
        lines = PC.apply_gate_answers(task, words, put=lambda fragment: puts.append(json.loads(fragment)) or (0, ""))
        text = "\n".join(lines)
        rows = rows_of(task)
        check_eq("`<case>: manual` on an automated row with no sibling case: the row is checked by an agent by hand",
                 rows["TS-1"]["disposition"], "manual-agent")
        check_in("...said in one line", "gate A: QA-9_TC_001: TS-1 stays checked by hand: an automated test becomes a "
                 "check by an agent, by hand.", lines)
        check_eq("`<case>: manual` on a row that holds TWO cases: the row is left (a row is checked one way for all)",
                 rows["TS-4"]["disposition"], "automate")
        check_in("...and the line names the other case", "its row TS-4 also holds QA-9_TC_005", text)
        check_eq("a case that is on a row the person already keeps by hand: nothing to do for the blocked card",
                 [r["case"] for p in puts for r in p["unresolved"]], ["QA-9_TC_003"])
        check_in("TC_002 (manual-human) is not run: no row, one line", "QA-9_TC_002 (second) is not run by an automated test "
                 "(a check by a person, by hand), so there is nothing to block; your word is recorded", text)
        check_in("an id of the same form that is no case of the story is named, nothing written for it",
                 "`QA-9_TC_099` is not a case of this story, so nothing is applied for it", text)
        check_in("TC_006 is a case whose row (TS-9) is not in the plan: not blocked, said",
                 "QA-9_TC_006 (sixth) is not in the plan (no row holds it), so nothing is blocked for it", text)
        check_in("a bare `accept as blocked` with no case on its line is told the form (one line, nothing applied)",
                 "gate A: \"accept as blocked\" is not an answer the factory reads, so nothing is blocked for it; to "
                 "accept a case as blocked write `<full case id>: accept as blocked` on a line of its own, with nothing "
                 "else on it", text)
        check_not_in("a quoted line is no answer", "QA-9_TC_001: accepted as blocked", text)
        applied = {(r["what"], r["id"]) for r in read_lines(task / "work" / "question-answers.jsonl")
                   if r.get("kind") == "answers_applied"}
        check_eq("the file carries each card applied (and nothing for the ones that were refused)",
                 sorted(applied), [("accept_as_blocked", "QA-9_TC_002"), ("accept_as_blocked", "QA-9_TC_003"),
                                   ("case_manual", "QA-9_TC_001"), ("case_manual", "QA-9_TC_004")])
        check_eq("the register reads the two manual words as the person's case decisions",
                 sorted(QR.load(task)["case_decisions"]), ["QA-9_TC_001", "QA-9_TC_004"])
    finally:
        cleanup(root)
    # a row authored manual-human that an answer moves to automate: the case's own `manual` restores the AUTHORED word
    cases = {"QA-9_TC_001": ("TS-1", "first")}
    plan = [row("TS-1", disposition="manual-human", question_refs=["Q1"],
                if_answered={"Q1": {"a": {"disposition": "automate"}, "b": {}, "not_needed": {}}})]
    root, task = gate_a_story("qa-cards-restore-", plan, [register("Q1")], cases, ticket="QA-9")
    try:
        PC.apply_gate_answers(task, "Q1: a\nQA-9_TC_001: manual")
        check_eq("the answer moved the row and the case's word brought it back to the AUTHORED manual-human",
                 rows_of(task)["TS-1"]["disposition"], "manual-human")
    finally:
        cleanup(root)


def test_c10_a_letter_branch_lands_its_obligations_and_the_plan_md_cell_is_rewritten() -> None:
    plan = [v2_row("TS-2", disposition="manual-agent", level="e2e-ui", reason="rests on open Q1", question_refs=["Q1"],
                   if_answered={"Q1": {"a": {"disposition": "automate", "level": "api", "reason": "read through the API",
                                             "coverage_obligations": [dict(obligation("OB-TS-2"), oracle_status="resolved")]},
                                       "b": {}, "not_needed": {}}}),
            row("TS-3", disposition="automate")]
    md = ("# Plan\n\n## Plan\n\n| TS | what we verify | R | disposition + reason | fit |\n|---|---|---|---|---|\n"
          "| TS-2 | the stored state | R-1 | per Q1: a -> automate api; b -> manual | new |\r\n"
          "| TS-3 | another | R-2 | `automate` — a reason | new |\n\n## Recommended regression\n\n| TS-2 | x |\n")
    plan[0]["coverage_obligations"][0]["oracle_status"] = "unresolved"
    plan[0]["coverage_obligations"][0]["decision"] = "unresolved"
    root, task = gate_a_story("qa-c10-", plan, [register("Q1")], {}, plan_md=md)
    try:
        before_md = (task / "test-plan.md").read_bytes().decode("utf-8")
        PC.apply_gate_answers(task, "Q1: a")
        row2 = rows_of(task)["TS-2"]
        check_eq("C10: the obligations the branch carries replace the list: the answered row is `resolved`",
                 [(o["obligation_id"], o["oracle_status"]) for o in row2["coverage_obligations"]], [("OB-TS-2", "resolved")])
        after_md = (task / "test-plan.md").read_bytes().decode("utf-8")
        check_in("the conditional cell of TS-2 is rewritten from the JSON, line ending kept",
                 "| TS-2 | the stored state | R-1 | `automate` — read through the API | new |\r\n", after_md)
        check_eq("every other line of the plan file is byte for byte as it was",
                 [ln for ln in after_md.splitlines(keepends=True) if "TS-2 | the stored" not in ln],
                 [ln for ln in before_md.splitlines(keepends=True) if "TS-2 | the stored" not in ln])
        # no md at all, a bare-array plan, and a row the md does not hold: all fine
    finally:
        cleanup(root)
    plan = [row("TS-2", disposition="manual-agent", question_refs=["Q1"],
                if_answered={"Q1": {"a": {"disposition": "automate"}, "b": {}, "not_needed": {}}})]
    root, task = gate_a_story("qa-c1-bare-", plan, [register("Q1")], {}, bare=True)
    try:
        PC.apply_gate_answers(task, "Q1: a")
        document = plan_of(task)
        check_eq("a plan written as a bare array stays a bare array (nothing is added to it)",
                 (type(document).__name__, document[0]["disposition"]), ("list", "automate"))
    finally:
        cleanup(root)


def doc_keys_missing(text: str, keys) -> list:
    """The doc-witness: which of `keys` the document does not carry (case-sensitive; a wrapped line is one)."""
    flat = " ".join(text.split())
    return [key for key in keys if " ".join(key.split()) not in flat]


def test_t227b_role_text_doc_witness() -> None:
    """The keys are quoted VERBATIM from spec t-227 section 3 'Role text' ("every reading plus `not_needed`,
    `oracle_unknown: false` per letter, P19 words") and from the contract's own sentences, as they were written
    BEFORE this run; the negative control is a key that cannot be there. FR-38: the strategist is told the
    requirement in the document it works from, before the S3 exit refuses."""
    agent = (PLUGIN_ROOT / "agents" / "qa-test-strategist.md").read_text(encoding="utf-8")
    contract = (PLUGIN_ROOT / "references" / "artifact-contract-plan.md").read_text(encoding="utf-8")
    slice_text = (PLUGIN_ROOT / "references" / "slices" / "qa-test-strategist" / "artifact-contract-plan.md").read_text(
        encoding="utf-8")
    # "manifesto ladder": the word agents/qa-test-strategist.md carries now (line 25, "on the manifesto ladder"); the charter no longer says P19.
    agent_keys = ("`question_refs`", "manifesto ladder", "`test_level_rationale`", "the S3 exit refuses")
    # t-1685 N3 moved the exit-judged letter-branch rule out of the charter into the strategist's ahead-card: the
    # witness reads the place the role now receives it (a missing or unreadable card fails, naming the file).
    card_keys = ("`oracle_unknown: false`", "`oracle_status: resolved`")
    cards_file = PLUGIN_ROOT / "references" / "ahead-cards.json"
    try:
        card = json.loads(cards_file.read_text(encoding="utf-8"))["cards"]["qa-test-strategist"]["text"]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        card = ""
        check(f"{cards_file.name}: the strategist's card is readable", False, repr(exc))
    contract_keys = ("`if_answered`", "EVERY reading letter", "`not_needed`", "`question-branch-keys.json`",
                     "`*` and a letter merge, the letter winning", "`*` never covers `not_needed`", "`{}`")
    check_eq("the strategist's charter carries every key", doc_keys_missing(agent, agent_keys), [])
    check_eq("the strategist's ahead-card carries every key", doc_keys_missing(card, card_keys), [])
    check_eq("NEGATIVE CONTROL: a card key deliberately absent is reported",
             doc_keys_missing(card, card_keys + ("`impossible_key_t227b`",)), ["`impossible_key_t227b`"])
    check_eq("the plan contract carries every key", doc_keys_missing(contract, contract_keys), [])
    check_eq("...and so does the slice the strategist is actually handed (A9 keeps it fresh)",
             doc_keys_missing(slice_text, contract_keys), [])
    check_eq("NEGATIVE CONTROL: a key deliberately absent is reported (the witness can fail)",
             doc_keys_missing(agent, agent_keys + ("`impossible_key_t227b`",)), ["`impossible_key_t227b`"])
    check_eq("NEGATIVE CONTROL: an emptied document fails every key", len(doc_keys_missing("", contract_keys)), len(contract_keys))


def test_edge_no_plan_no_register_and_no_branch_say_one_thing_and_never_raise() -> None:
    root, task = gate_a_story("qa-nothing-", [row("TS-1")], [], {})
    try:
        (task / "work" / "test-plan.json").unlink()
        check_eq("no plan, no question, no token: nothing to say", PC.apply_gate_answers(task, "Approved."), [])
        check_eq("a token for a question the story does not have is named, not swallowed",
                 PC.apply_gate_answers(task, "Q1: a"),
                 ["gate A: not questions of this story, so nothing is recorded for them: Q1"])
        for words in (None, "", "   ", "\x00￾" * 3, "Q1: a" * 50000):
            try:
                got = PC.apply_gate_answers(task, words)
                check(f"words {str(words)[:12]!r} raise nothing and answer in lines", isinstance(got, list))
            except Exception as exc:
                check(f"words {str(words)[:12]!r} raise nothing", False, repr(exc))
        check_eq("a task root that does not exist is one line, not a traceback",
                 len(PC.apply_gate_answers(task / "nowhere", "Q1: a")) <= 1, True)
    finally:
        cleanup(root)


# --- t-256: the fix wave after the critic of t-245/t-246 (spec t-227 section 0d): O6-O10, O12 ------------------
# One named check per item; the mutation that kills each lives in the report, not here.

READINESS = (FIXTURES / "cmp2-requirements-readiness.json").read_bytes()
O6_CASES = {"QA-9_TC_001": ("TS-1", "first"), "QA-9_TC_002": ("TS-2", "second"), "QA-9_TC_003": ("TS-3", "third")}
O6_PLAN = [row("TS-1", disposition="automate"), row("TS-2", disposition="automate"), row("TS-3", disposition="automate")]


def blocked_by(words: str, cases=None, plan=None, texts=None) -> tuple:
    """([unresolved rows the applier sent to manifest_put], [printed lines], [applied records]) for `words`."""
    root, task = gate_a_story("qa-o6-", plan or O6_PLAN, [register("Q1")], cases or O6_CASES, ticket="QA-9",
                              case_texts=texts)
    try:
        puts = []
        lines = PC.apply_gate_answers(task, words, put=lambda fragment: puts.append(json.loads(fragment)) or (0, ""))
        applied = [r for r in read_lines(task / "work" / "question-answers.jsonl") if r.get("kind") == "answers_applied"]
        return [r for p in puts for r in p["unresolved"]], lines, applied
    finally:
        cleanup(root)


def test_o6_the_cmp2_prose_line_blocks_nothing_and_names_the_form() -> None:
    """cmp2 answers line 20 is PROSE that mentions the words: the old reading took the substring and blocked every
    case id on the line. Now it is no token: nothing is written, and ONE line names the form."""
    answers = (FIXTURES / "cmp2-s4-gate-a.md").read_text(encoding="utf-8")
    check_in("the fixture keeps cmp2's line 20 verbatim: the prose negative",
             "TC_017 (P-readonly) (a second non-admin user): accept as blocked on localhost; S5 reports exactly those "
             "partitions as not executed.", answers.splitlines()[19])
    plan = repaired_cmp2_rows()
    next(r for r in plan if r["id"] == "TS-20")["disposition"] = "automate"   # even an AUTOMATED row is not blocked by prose
    root, task = gate_a_story("qa-o6-cmp2-", plan, READINESS, CMP2_CASES)
    try:
        puts = []
        lines = PC.apply_gate_answers(task, answers, put=lambda fragment: puts.append(fragment) or (0, ""))
        check_eq("no manifest write at all: TC_014 and TC_017 are not blocked by the prose", puts, [])
        check_eq("no `accept_as_blocked` record either",
                 [r for r in read_lines(task / "work" / "question-answers.jsonl") if r.get("what") == "accept_as_blocked"], [])
        said = [ln for ln in lines if "is not an answer the factory reads" in ln]
        check_eq("ONE printed line names the form", len(said), 1)
        check_in("...it quotes the start of the line and says what to write", "to accept a case as blocked write "
                 "`<full case id>: accept as blocked` on a line of its own, with nothing else on it", said[0])
        check("...and the six question answers of the same words are applied as before",
              any(ln.startswith("gate A: answers recorded by code") for ln in lines))
    finally:
        cleanup(root)


def test_o6_only_a_whole_line_token_blocks_a_case() -> None:
    """`<case id>: accept as blocked` is the WHOLE line (full or short id, one case per line); a negation, a second
    case on the line, the card's old words and a wrong case are told the form or the case, and nothing is applied."""
    for label, words in (("the card's own old words (`accept them as blocked`)", "TC_001: accept them as blocked"),
                         ("a negation on the line", "TC_001: do not accept as blocked"),
                         ("another case on the same line", "TC_001: accept as blocked; TC_002 runs"),
                         ("two tokens glued on one line", "TC_001: accept as blocked, TC_002: accept as blocked"),
                         ("upper case", "TC_001: Accept As Blocked"),
                         ("a trailing explanation", "TC_001: accept as blocked because the stand has no second user")):
        rows_out, lines, applied = blocked_by(words)
        check_eq(f"{label}: nothing is applied", (rows_out, applied), ([], []))
        check_eq(f"{label}: ONE line names the form", len([ln for ln in lines if "is not an answer the factory reads" in ln]), 1)
    rows_out, lines, applied = blocked_by("QA-9_TC_001: accept as blocked\nTC_002: accept as blocked")
    check_eq("two tokens on two lines make two rows (a full id and a short one)",
             sorted(r["case"] for r in rows_out), ["QA-9_TC_001", "QA-9_TC_002"])
    rows_out, lines, applied = blocked_by("- **TC_003**: accept as blocked.")
    check_eq("a list marker, emphasis and one closing full stop are still the whole line", [r["case"] for r in rows_out],
             ["QA-9_TC_003"])
    rows_out, lines, applied = blocked_by("TC_009: accept as blocked")
    check_eq("a case that is not in the story: nothing, one line naming it", (rows_out, lines),
             ([], ["gate A: `TC_009` is not a case of this story, so nothing is applied for it"]))
    rows_out, lines, applied = blocked_by("TC_001: manual\nTC_001: accept as blocked")
    check_eq("two different words for one case: nothing is applied for it", rows_out, [])
    check_in("...and one line says so", "gate A: QA-9_TC_001 has two different words (manual, accept as blocked); "
             "nothing is applied for it", lines)
    rows_out, lines, applied = blocked_by("> TC_001: accept as blocked\n```\nTC_002: accept as blocked\n```")
    check_eq("a quoted line and a fenced one are never tokens", rows_out, [])
    # a short id two cases end with: nothing, and the candidates are named
    rows_out, lines, applied = blocked_by("TC_001: accept as blocked", cases={"QA-9_TC_001": ("TS-1", "a"), "QA-9a_TC_001": ("TS-2", "b")})
    check_eq("a short id of two cases is not guessed", rows_out, [])
    check_in("...the candidates are named", "`TC_001` is 2 cases (QA-9_TC_001, QA-9a_TC_001), so nothing is applied for it; "
             "write the full case id", lines)


def _preconditions_case(cid: str, row_id: str, items) -> str:
    front = f"---\nid: {cid}\ntitle: t {cid}\nplan_row: {row_id}\n"
    if items is not None:
        front += "preconditions: " + (items if isinstance(items, str) else json.dumps(items)) + "\n"
    return front + "---\n\n## Then\n1. x.\n"


def _pc(pid, kind, what, check, partitions=None):
    return dict({"id": pid, "kind": kind, "what": what, "check": check}, **({"partitions": partitions} if partitions is not None else {}))


def test_o7_the_remedy_comes_from_the_precondition_items_behind_the_card() -> None:
    """Without a remedy `acceptance.blocked_instances` answers `no_remedy` and the case the person accepted as blocked
    is still run and judged. The remedy is derived: kind by the item's kind, where `<case> preconditions <ids>`,
    change = what the items say; partitions = the items' (the whole case when one names none)."""
    cases = {f"QA-9_TC_00{n}": (f"TS-{n}", f"case {n}") for n in range(1, 9)}
    plan = [row(f"TS-{n}", disposition="automate") for n in range(1, 9)]
    env = {"env": "SOME_VAR"}
    texts = {
        "QA-9_TC_001": _preconditions_case("QA-9_TC_001", "TS-1", [_pc("PC-1", "feature_flag", "sub-workflows are on", env, ["P-a"])]),
        "QA-9_TC_002": _preconditions_case("QA-9_TC_002", "TS-2", [_pc("PC-1", "data", "guardrail data exists", env, ["P-b"])]),
        "QA-9_TC_003": _preconditions_case("QA-9_TC_003", "TS-3", [_pc("PC-1", "account", "a second user", env, ["P-c"]),
                                                                  _pc("PC-2", "account", "an outsider", {"none": "only a person knows"}, ["P-d"])]),
        "QA-9_TC_004": _preconditions_case("QA-9_TC_004", "TS-4", [_pc("PC-1", "env", "the AWS profile is set", env, ["P-e"])]),
        "QA-9_TC_005": _preconditions_case("QA-9_TC_005", "TS-5", [_pc("PC-1", "service", "the preview stand is up", {"http": {"path": "/health"}})]),
        # the `none` card's item is an item like the others (it carries a kind and a what)
        "QA-9_TC_006": _preconditions_case("QA-9_TC_006", "TS-6", [_pc("PC-1", "data", "needs the preview stand", {"none": "needs the preview stand"})]),
        # never asked of a stand: they made no card, so they make no remedy; the person's own line is the change
        "QA-9_TC_007": _preconditions_case("QA-9_TC_007", "TS-7", [_pc("PC-1", "data", "the case seeds it", {"case_seeds": "its own workflow"}, ["P-f"])]),
        "QA-9_TC_008": _preconditions_case("QA-9_TC_008", "TS-8", '[{"id": "PC-1", "kind": "bogus"}]'),
    }
    words = "\n".join(f"QA-9_TC_00{n}: accept as blocked" for n in range(1, 9))
    root, task = gate_a_story("qa-o7-", plan, [register("Q1")], cases, ticket="QA-9", case_texts=texts)
    try:
        puts = []
        PC.apply_gate_answers(task, words, put=lambda fragment: puts.append(json.loads(fragment)) or (0, ""))
        rows_out = [r for p in puts for r in p["unresolved"]]
        _o7_checks(rows_out, cases, task)
    finally:
        cleanup(root)


def test_t279_k_remedy_comes_from_the_unmet_items_only_and_says_when_it_cannot() -> None:
    """t-218 F4 / t-279 K-REMEDY. The card for a case lists what the stand lacks; the remedy of the blocked row is
    derived from the same classification (`gate_preflight`'s `_check_one_precondition`), so an item the stand holds
    is never blocked with the one it lacks. PC-1 `MET_VAR` is set where the runner reads it (met); PC-2 `LACKED_VAR`
    is not (unmet): only PC-2's partition is blocked and the kind is PC-2's. A case whose items are all met or
    seeded has no unmet item: the kind is not derivable, nothing is blocked, one line says so (FR-41)."""
    import acceptance as AC
    import contract as C
    cases = {f"QA-9_TC_00{n}": (f"TS-{n}", f"case {n}") for n in range(1, 6)}
    plan = [row(f"TS-{n}", disposition="automate") for n in range(1, 6)]
    met, lacked = {"env": "MET_VAR"}, {"env": "LACKED_VAR"}
    texts = {
        "QA-9_TC_001": _preconditions_case("QA-9_TC_001", "TS-1", [_pc("PC-1", "data", "the data exists", met, ["P-a"]),
                                                                  _pc("PC-2", "account", "a second user", lacked, ["P-b"])]),
        "QA-9_TC_002": _preconditions_case("QA-9_TC_002", "TS-2", [_pc("PC-1", "data", "the data exists", met, ["P-a"]),
                                                                  _pc("PC-2", "data", "more data", met, ["P-b"])]),
        "QA-9_TC_003": _preconditions_case("QA-9_TC_003", "TS-3", [_pc("PC-1", "data", "the data exists", met, ["P-a"]),
                                                                  _pc("PC-2", "feature_flag", "the flag", {"case_seeds": "its own"}, ["P-b"])]),
        # the unmet item names no partition: the whole case is blocked, and the met item's partition is not named
        "QA-9_TC_004": _preconditions_case("QA-9_TC_004", "TS-4", [_pc("PC-1", "data", "the data exists", met, ["P-a"]),
                                                                  _pc("PC-2", "service", "the preview stand", lacked)]),
        # control: nothing met - both unmet items are blocked, as before
        "QA-9_TC_005": _preconditions_case("QA-9_TC_005", "TS-5", [_pc("PC-1", "data", "the data exists", lacked, ["P-a"]),
                                                                  _pc("PC-2", "account", "a second user", lacked, ["P-b"])]),
    }
    words = "\n".join(f"QA-9_TC_00{n}: accept as blocked" for n in range(1, 6))
    root, task = gate_a_story("qa-k-remedy-", plan, [register("Q1")], cases, ticket="QA-9", case_texts=texts)
    try:
        cfg_path = root / "qa-factory" / "config.json"
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        cfg["environment"] = {"env_file": "tests/.env"}
        cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
        (root / "tests").mkdir(exist_ok=True)
        (root / "tests" / ".env").write_text("MET_VAR=1\n", encoding="utf-8")
        puts = []
        lines = PC.apply_gate_answers(task, words, put=lambda fragment: puts.append(json.loads(fragment)) or (0, ""))
        by_case = {r["case"]: r for p in puts for r in p["unresolved"]}
        short = lambda case: case[-6:]
        check_eq("K-REMEDY: PC-1 met + PC-2 unmet: only PC-2's partition is blocked, the kind is PC-2's (account -> credential)",
                 (by_case["QA-9_TC_001"].get("partitions"), by_case["QA-9_TC_001"]["remedy"]["kind"],
                  by_case["QA-9_TC_001"]["remedy"]["where"], by_case["QA-9_TC_001"]["remedy"]["change"]),
                 (["P-b"], "credential", "QA-9_TC_001 preconditions PC-2", "a second user"))
        check_eq("K-REMEDY: the unmet item names no partition: the whole case (no `partitions`), the kind is the unmet item's",
                 (by_case["QA-9_TC_004"].get("partitions"), by_case["QA-9_TC_004"]["remedy"]["kind"],
                  by_case["QA-9_TC_004"]["remedy"]["where"]), (None, "service", "QA-9_TC_004 preconditions PC-2"))
        check_eq("K-REMEDY control: both items unmet: both are blocked, in order (the old derivation)",
                 (by_case["QA-9_TC_005"].get("partitions"), by_case["QA-9_TC_005"]["remedy"]["where"]),
                 (["P-a", "P-b"], "QA-9_TC_005 preconditions PC-1, PC-2"))
        check_not_in("K-REMEDY: no unmet item (all met, or met + seeded): NO row for those cases", "TC_002 TC_003",
                     " ".join(short(c) for c in by_case))
        check_eq("K-REMEDY: ... and no row means no guessed kind: exactly the three cases that lack something have one",
                 sorted(by_case), ["QA-9_TC_001", "QA-9_TC_004", "QA-9_TC_005"])
        for case in ("QA-9_TC_002", "QA-9_TC_003"):
            check_in(f"K-REMEDY: {case}: ONE line says the kind is not derivable and nothing is blocked",
                     f"gate A: {case} (t {case}): the kind of what the stand lacks is not derivable (every "
                     "precondition of the case is met or created by the case itself, or they cannot be read), so "
                     "nothing is blocked for it and S5 runs it; your word is recorded", lines)
        records = [(r["id"], r["what"]) for r in read_lines(task / "work" / "question-answers.jsonl")
                   if r.get("what") == "accept_as_blocked"]
        check_eq("K-REMEDY: the person's word on those two cases is still recorded (nothing is lost, FR-9)",
                 sorted(c for c, _ in records), [f"QA-9_TC_00{n}" for n in range(1, 6)])
        check_eq("K-REMEDY: every row written is a remedy the contract accepts",
                 [C.remedy_errors(r["remedy"]) for r in by_case.values()], [[]] * 3)
        refused: list = []
        scope = {c: [f"i{n}"] for n, c in enumerate(cases, 1)}
        tests = [{"instance_id": f"i{n}", "case": c, "covers": [c]} for n, c in enumerate(cases, 1)]
        got = AC.blocked_instances({"tests": tests, "unresolved": list(by_case.values())},
                                   [{"instance_id": f"i{n}"} for n in range(1, 6)], scope, task, runs={}, refused=refused)
        check_eq("K-REMEDY: S5 blocks the three, runs the two it was told nothing about, and no_remedy is answered for none",
                 (len(got), [kind for kind, _id, _text in refused]), (3, []))
    finally:
        cleanup(root)


def test_t279_k_fence_a_blocked_token_in_a_code_block_is_said_once() -> None:
    rows_out, lines, applied = blocked_by("```\nQA-9_TC_001: accept as blocked\n```")
    check_eq("K-FENCE: nothing is blocked by a token inside a code block", (rows_out, applied), ([], []))
    check_eq("K-FENCE: and it is said once, in the register's words",
             [ln for ln in lines if "code block" in ln],
             ["gate A: a decision inside a code block is not read: QA-9_TC_001: accept as blocked"])


def _o7_checks(rows_out: list, cases: dict, task) -> None:
    import acceptance as AC
    import contract as C
    by_case = {r["case"]: r for r in rows_out}
    table = {"TC_" + c[-3:]: (r["remedy"]["kind"], r["remedy"]["where"].split(" preconditions ")[-1], r["remedy"]["change"],
                              r.get("partitions")) for c, r in by_case.items()}
    check_eq("feature_flag -> flag", table["TC_001"], ("flag", "PC-1", "sub-workflows are on", ["P-a"]))
    check_eq("data -> data", table["TC_002"], ("data", "PC-1", "guardrail data exists", ["P-b"]))
    check_eq("account -> credential, two askable items: ids and whats joined, partitions united",
             table["TC_003"], ("credential", "PC-1, PC-2", "a second user; an outsider", ["P-c", "P-d"]))
    check_eq("env -> credential", table["TC_004"], ("credential", "PC-1", "the AWS profile is set", ["P-e"]))
    check_eq("service -> service; an item naming no partition blocks the WHOLE case (no `partitions` key)",
             table["TC_005"], ("service", "PC-1", "the preview stand is up", None))
    check_eq("the `none` card's item gets the same derivation (it has a kind and a what)",
             table["TC_006"][:3], ("data", "PC-1", "needs the preview stand"))
    check_not_in("t-279 K-REMEDY: only items the case seeds itself (case_seeds): no item is unmet, so the kind is not "
                 "derivable and NOTHING is blocked - no row, no guessed kind `data`", "QA-9_TC_007", " ".join(by_case))
    check_eq("preconditions that cannot be read: the old fallback, never a crash (stories in flight)",
             by_case["QA-9_TC_008"]["remedy"]["kind"], "data")
    check_eq("every derived remedy is one the contract accepts", [C.remedy_errors(r["remedy"]) for r in rows_out], [[]] * 7)
    check_eq("the `where` of a derived remedy is `<case> preconditions <PC ids>`",
             by_case["QA-9_TC_003"]["remedy"]["where"], "QA-9_TC_003 preconditions PC-1, PC-2")
    refused: list = []
    scope = {c: [f"i{n}"] for n, c in enumerate(cases, 1)}
    tests = [{"instance_id": f"i{n}", "case": c, "covers": [c]} for n, c in enumerate(cases, 1)]
    got = AC.blocked_instances({"tests": tests, "unresolved": rows_out}, [{"instance_id": f"i{n}"} for n in range(1, 9)],
                               scope, task, runs={}, refused=refused)
    check_eq("`acceptance.blocked_instances` blocks the seven that carry a row (TC_007 has none) and answers `no_remedy` for none",
             (len(got), [kind for kind, _id, _text in refused]), (7, []))


def test_o8_the_nothing_to_block_line_is_true_only_for_a_check_by_a_person() -> None:
    plan = [row("TS-1", disposition="manual-agent"), row("TS-2", disposition="manual-human"), row("TS-3", disposition="automate")]
    rows_out, lines, applied = blocked_by("TC_001: accept as blocked\nTC_002: accept as blocked", plan=plan)
    text = "\n".join(lines)
    check_in("manual-agent: S5 blocks nothing, and the agent will still try it on the stand", "QA-9_TC_001 (first) is not "
             "run by an automated test (a check by an agent, by hand), so S5 blocks nothing for it, and the agent that "
             "checks it by hand will still try it on the stand as it is; your word is recorded", text)
    check_in("manual-human: nobody tries it on the stand, so there IS nothing to block", "QA-9_TC_002 (second) is not run by "
             "an automated test (a check by a person, by hand), so there is nothing to block; your word is recorded", text)
    check_eq("neither is a row for the manifest", rows_out, [])


PLAN_MD_O9 = ("# Plan\n\n## Plan\n\n| TS | what we verify | R | disposition + reason | fit | level |\n|---|---|---|---|---|---|\n"
              "| TS-2 | the stored state | R-1 | per Q1: a -> automate api; b -> manual | extend t | `e2e-ui` |\r\n"
              "| TS-3 | another | R-2 | `automate` — a reason | new | api |\n"
              "| TS-4 | a third | R-3 | `automate` — kept | new | unit |\n\n## Totals\n\nTotal: 3 rows\n")


def test_o9_every_md_column_a_changed_key_maps_to_is_rewritten() -> None:
    """The patch keys include `level` and `fit`, which are md columns: the plan JSON moved and the md the person reads
    at gate A kept the old value (the E-13 class). Only the columns of the keys that CHANGED are rewritten."""
    plan = [row("TS-2", disposition="manual-agent", level="e2e-ui", fit="extend t", question_refs=["Q1"],
                if_answered={"Q1": {"a": {"disposition": "automate", "level": "api", "fit": "param t", "reason": "read through the API"},
                                    "b": {}, "not_needed": {}}}),
            row("TS-3", disposition="automate", level="api", fit="new"), row("TS-4", disposition="automate", level="unit", fit="new")]
    root, task = gate_a_story("qa-o9-", plan, [register("Q1")], {}, plan_md=PLAN_MD_O9)
    try:
        PC.apply_gate_answers(task, "Q1: a")
        after = (task / "test-plan.md").read_bytes().decode("utf-8")
        check_in("the level cell is rewritten, and kept in its backticks", "| `api` |\r\n", after)
        check_in("the disposition + reason cell is rewritten as before, the fit cell with the key that changed",
                 "| TS-2 | the stored state | R-1 | `automate` — read through the API | param t | `api` |\r\n", after)
        check_eq("every other line is byte for byte as it was (TS-3, TS-4, the totals, the row count)",
                 [ln for ln in after.splitlines(keepends=True) if not ln.startswith("| TS-2 ")],
                 [ln for ln in PLAN_MD_O9.splitlines(keepends=True) if not ln.startswith("| TS-2 ")])
    finally:
        cleanup(root)
    # a patch that changes ONLY `level`: the other cells of the row stay as the strategist wrote them
    plan = [row("TS-2", disposition="automate", level="e2e-ui", fit="extend t", question_refs=["Q1"],
                if_answered={"Q1": {"a": {"level": "api"}, "b": {}, "not_needed": {}}}),
            row("TS-3", disposition="automate", level="api", fit="new"), row("TS-4", disposition="automate", level="unit", fit="new")]
    md = PLAN_MD_O9.replace("per Q1: a -> automate api; b -> manual", "`automate` — kept")
    root, task = gate_a_story("qa-o9-level-", plan, [register("Q1")], {}, plan_md=md)
    try:
        PC.apply_gate_answers(task, "Q1: a")
        after = (task / "test-plan.md").read_bytes().decode("utf-8")
        check_eq("only the level cell of TS-2 changed", [ln for ln in after.splitlines(keepends=True) if ln.startswith("| TS-2 ")],
                 ["| TS-2 | the stored state | R-1 | `automate` — kept | extend t | `api` |\r\n"])
    finally:
        cleanup(root)


def test_o10_a_letter_branch_settles_the_oracle_and_a_manual_branch_names_its_rung() -> None:
    def missing(rows, questions=None):
        return of_kind(run_pure(rows, questions, missing=True), "missing_branch")
    unknown = dict(oracle_unknown=True, question_refs=["Q1"])
    got = missing([row("TS-5", if_answered={"Q1": {"a": {}, "b": {}, "not_needed": {}}}, **unknown)])
    check_eq("an `oracle_unknown` row whose only open question is Q1: a branch that leaves it unknown is a finding naming the key",
             [(f["where"], f["question"], f["lacking"]) for f in got], [("TS-5", "Q1", "`oracle_unknown: false` for a, b")])
    check_in("...in plain words, with the row and the question first", "TS-5: it rests on Q1 and is `oracle_unknown`, but its "
             "branch for a, b does not set `oracle_unknown: false`", first(got)["message"])
    for label, entry in (("a and b both clear it", {"a": {"oracle_unknown": False}, "b": {"oracle_unknown": False}, "not_needed": {}}),
                         ("`*` clears it for every reading", {"*": {"oracle_unknown": False}, "not_needed": {}}),
                         ("a letter laid over `*`", {"*": {"oracle_unknown": False}, "a": {"level": "api"}, "not_needed": {}})):
        check_eq(f"{label}: complete", missing([row("TS-5", if_answered={"Q1": entry}, **unknown)]), [])
    check_eq("only `a` clears it: b is named, a is not",
             [f["lacking"] for f in missing([row("TS-5", if_answered={"Q1": {"a": {"oracle_unknown": False}, "b": {}, "not_needed": {}}}, **unknown)])],
             ["`oracle_unknown: false` for b"])
    check_eq("`not_needed` keeps the row as written and is asked for nothing",
             missing([row("TS-5", if_answered={"Q1": {"*": {"oracle_unknown": False}, "not_needed": {}}}, **unknown)]), [])
    check_eq("a row that is NOT oracle_unknown is never asked", missing(
        [row("TS-5", question_refs=["Q1"], if_answered={"Q1": {"a": {}, "b": {}, "not_needed": {}}})]), [])
    check_eq("two open questions: one answer settles only half, so it is not asked",
             missing([row("TS-5", oracle_unknown=True, question_refs=["Q1", "Q2"],
                          if_answered={"Q1": {"a": {}, "b": {}, "not_needed": {}}, "Q2": {"a": {}, "b": {}, "not_needed": {}}})]), [])
    check_eq("the S3 exit's refusal sees the same finding (it filters on the kind)",
             {f["kind"] for f in missing([row("TS-5", if_answered={"Q1": {"a": {}, "b": {}, "not_needed": {}}}, **unknown)])},
             {"missing_branch"})
    # manual-*: the rung
    manual = {"a": {"disposition": "manual-agent", "reason": "r"}, "b": {}, "not_needed": {}}
    got = missing([row("TS-5", question_refs=["Q1"], if_answered={"Q1": manual})])
    check_eq("a branch that sets a manual-* disposition without a `test_level_rationale` is a finding naming the key",
             [(f["where"], f["lacking"]) for f in got], [("TS-5", "`test_level_rationale` for a")])
    manual["a"]["test_level_rationale"] = "P19 rung 3: no lower rung reads a label"
    check_eq("...and with it, no finding", missing([row("TS-5", question_refs=["Q1"], if_answered={"Q1": manual})]), [])
    check_eq("a BLANK rationale is no rationale", [f["lacking"] for f in missing([row("TS-5", question_refs=["Q1"], if_answered={
        "Q1": {"a": {"disposition": "manual-human", "test_level_rationale": "  "}, "b": {}, "not_needed": {}}})])
        if "rationale" in f["lacking"]], ["`test_level_rationale` for a"])
    # the cmp2 plan: TS-4's branches
    plan = repaired_cmp2_rows()
    ts4 = next(r for r in plan if r["id"] == "TS-4")
    del ts4["if_answered"]["Q4"]["b"]["test_level_rationale"]
    found = of_kind(PC.variant_errors(plan, [dict(q("Q%d" % n)) for n in range(1, 7)], ()), "missing_branch")
    check_eq("K3: TS-4's manual branch loses its rationale -> exactly that finding", [(f["where"], f["lacking"]) for f in found],
             [("TS-4", "`test_level_rationale` for b")])


def test_o12_a_plan_created_on_or_after_the_cutoff_is_checked_with_no_branch_field() -> None:
    qs = [q("Q5")]
    reason_only = [row("TS-5", disposition="manual-agent", reason="manual until Q5 is answered")]
    check_eq("legacy: no branch field anywhere and no date: silent (today's invariant)",
             PC.variant_errors(reason_only, qs, ()), [])
    check_eq("a plan created BEFORE the cutoff is the same story",
             PC.variant_errors(reason_only, qs, (), plan_created="2026-10-01"), [])
    got = PC.variant_errors(reason_only, qs, (), plan_created="2026-10-02")
    check_eq("created ON the cutoff: the reason-only row (`manual until Q5 is answered`) is a missing_branch finding",
             [(f["kind"], f["where"], f["question"]) for f in got], [("missing_branch", "TS-5", "Q5")])
    check_eq("...also later", len(PC.variant_errors(reason_only, qs, (), plan_created="2027-01-05T10:00")), 1)
    check_eq("an unreadable date is no date", PC.variant_errors(reason_only, qs, (), plan_created="tomorrow"), [])
    check("has_branch_fields says the same", PC.has_branch_fields(reason_only, (), "2026-10-02")
          and not PC.has_branch_fields(reason_only, (), "2026-10-01") and not PC.has_branch_fields(reason_only))


# --- t-261: the manual-agent pass (t-250 §1, C1, C2) and the three lines of the integration wave -----------
# TP1-15045 (cmp2): of its eleven `manual-agent` rows not one obligation had `decision: manual-agent`, so
# `manual_evidence.prepare` refused every one and the agent that checks by hand never ran. The pass in
# `planning_contract.apply_gate_answers` makes them executable, in the same atomic plan write and before the
# gate decision. The error direction is toward NOT executable: every case below that must stay as planned is
# named by the line the person reads.

import event_store  # noqa: E402

CMP2_ROWS = json.loads((FIXTURES / "cmp2-test-plan.json").read_text(encoding="utf-8-sig"))["rows"]
K1_CASES = {f"{CMP2}_TC_007": ("TS-7", "Zoom, fit-view and drag-to-pan respond"),
            f"{CMP2}_TC_008": ("TS-8", "Canvas shortcuts and drags with the history popup open")}


def cmp2_rows(*ids) -> list:
    """The cmp2 plan's own rows, verbatim (deep copies), in plan order."""
    return [copy.deepcopy(r) for r in CMP2_ROWS if r["id"] in ids]


def obligations_of(rows, rid):
    return {o["obligation_id"]: o for o in rows[rid]["coverage_obligations"]}


class CountPlanWrites:
    """Counts the atomic writes of `test-plan.json` made through `event_store.atomic_json` while it is active."""

    def __enter__(self):
        self.real, self.writes = event_store.atomic_json, []
        outer = self

        def counting(path, data, *args, **kwargs):
            outer.writes.append(Path(path).name)
            return outer.real(path, data, *args, **kwargs)
        event_store.atomic_json = counting
        return self

    def __exit__(self, *exc):
        event_store.atomic_json = self.real

    @property
    def plan_writes(self) -> int:
        return self.writes.count("test-plan.json")


def test_t261_k1_the_cmp2_rows_become_executable_and_the_controls_do_not() -> None:
    """K1: the real cmp2 rows TS-1, TS-7, TS-8, TS-13 + the person's gate-A file + `<TC_008>: manual`."""
    words = (FIXTURES / "cmp2-s4-gate-a.md").read_text(encoding="utf-8") + f"\n{CMP2}_TC_008: manual\n"
    root, task = gate_a_story("qa-t261-k1-", cmp2_rows("TS-1", "TS-7", "TS-8", "TS-13"),
                              (FIXTURES / "cmp2-requirements-readiness.json").read_bytes(), K1_CASES)
    try:
        before = rows_of(task)
        check_eq("setup: TS-8 is an automated row, OB-8 is `new` with no evidence rule and the row names none",
                 (before["TS-8"]["disposition"], obligations_of(before, "TS-8")["OB-8"]["decision"],
                  obligations_of(before, "TS-8")["OB-8"].get("evidence_policy"), before["TS-8"].get("evidence_policy"),
                  before["TS-8"]["level"]), ("automate", "new", None, None, "e2e-ui"))
        check_eq("setup: OB-7 is `new` (the S3 plan blocked every manual row)",
                 obligations_of(before, "TS-7")["OB-7"]["decision"], "new")
        with CountPlanWrites() as counter:
            lines = PC.apply_gate_answers(task, words)
        after = rows_of(task)
        ob7 = obligations_of(after, "TS-7")["OB-7"]
        check_eq("K1: OB-7 -> `manual-agent`, policy `ui`", (ob7["decision"], ob7["evidence_policy"]), ("manual-agent", "ui"))
        ob8 = obligations_of(after, "TS-8")["OB-8"]
        check_eq("K1: TS-8 -> disposition and decision `manual-agent`, policy `ui` from level `e2e-ui`",
                 (after["TS-8"]["disposition"], ob8["decision"], ob8["evidence_policy"]),
                 ("manual-agent", "manual-agent", "ui"))
        check("...the row itself names no policy: it came from the level table", "evidence_policy" not in after["TS-8"])
        check_eq("K1 control: TS-1 (decision `unresolved`, oracle unresolved) stays `unresolved`, obligation byte for byte",
                 obligations_of(after, "TS-1"), obligations_of(before, "TS-1"))
        check_eq("K1 control: TS-13 (a check by a person) is unchanged", after["TS-13"], before["TS-13"])
        check_eq("K1: the plan is written ONCE (the answers, the case word and the pass in one atomic write)",
                 counter.plan_writes, 1)
        check_in("the person reads one line for TS-7 and one for TS-8, each naming the evidence rule",
                 "OB-7 (evidence: ui).", " ".join(ln for ln in lines if "made executable" in ln))
        check_eq("...two such lines and no more", len([ln for ln in lines if "made executable" in ln]), 2)
        # idempotent: the same words again change nothing, write nothing, and say nothing about a conversion
        stamp = (task / "work" / "test-plan.json").read_bytes()
        with CountPlanWrites() as counter:
            again = PC.apply_gate_answers(task, words)
        check_eq("the same words again: the plan bytes are the same and nothing is written",
                 ((task / "work" / "test-plan.json").read_bytes() == stamp, counter.plan_writes), (True, 0))
        check_eq("...and no conversion is said again", [ln for ln in again if "made executable" in ln], [])
    finally:
        cleanup(root)


def test_t261_the_pass_writes_before_the_decision_and_no_byte_changes_after_it() -> None:
    """POSITIONAL invariant: the decision binds the plan the pass wrote (DC1-19: the pass runs inside the controller's `gate-decision`, before the
    request is built), and "Gate A plan content changed after approval" still fires on a later edit. The first call is the real controller
    on the recorded run of 12586 (`test_gate_decision_manual_pass.story`), whose manual rows stand `new`."""
    import test_gate_decision_manual_pass as MP
    from event_store import content_hash
    from harness import temp_project
    root = temp_project("qa-t261-seam-")
    try:
        task = MP.story(root)
        check_eq("setup: OB-13 stands `new`", MP.obligations(task)["OB-13"]["decision"], "new")
        code, result = MP.decide(root, task)
        final = content_hash(MP.plan_of(task))
        check_eq("the decision is recorded", (code, result.get("recorded")), (0, True))
        check_eq("the pass converted the row's obligation (it stood `new`)", MP.obligations(task)["OB-13"]["decision"], "manual-agent")
        check_eq("the plan hash the decision reads IS the final file's: no byte changes after the decision",
                 result["decision"]["payload"]["plan_content_hash"], final)
        check_in("the person reads the conversion in the controller's own answer", "made executable for the agent's check by hand",
                 " ".join(result.get("manual_pass") or []))
    finally:
        cleanup(root)
    # the real controller: a decision bound AFTER the pass stands; a plan edit after it is refused; and a pass
    # that came AFTER the decision (the mutation) is refused too - which is what the position protects
    import tempfile
    import test_controller_state as BASE
    from controller import Controller
    from event_store import StateConflict

    def story_at_gate_a(td):
        root_ = Path(td)
        c = Controller(root_)
        c.apply("initialize", {"scope": ["TC-1"], "source_revision": "src-1", "known_paths": {"root": str(root_)},
                               "idempotency_key": "init"})
        for number in range(5):
            BASE.accept_stage(c, root_, f"S{number}")
        BASE.seed_plan(root_, rows=[{"id": "TS-1", "impact": "low", "likelihood": "low", "confidence": "high",
                                     "risk_rationale": "bounded", "risk_source_refs": ["R-1"],
                                     "risk_policy_revision": "factory-starter-v1", "coverage_refs": ["R-1"],
                                     "unknowns": [], "verification_depth": "low", "required_scenarios": ["TC-1"],
                                     "test_level_rationale": "unit", "design_review_required": False,
                                     "bounded_reversible": True, "disposition": "manual-agent", "level": "api"}])
        path = root_ / "work" / "test-plan.json"
        document = json.loads(path.read_text(encoding="utf-8"))
        ob = document["rows"][0]["coverage_obligations"][0]
        ob.update(decision="new", planned_check_refs=["tests/test_one.py:2"])
        path.write_text(json.dumps(document), encoding="utf-8")
        return c, root_

    def decide(c):
        decision = {"id": "gate-a", "gate": "A", "action": "approve", "status": "approved",
                    "authorization_source": "human", "source_revision": "src-1", "scope": ["TC-1"],
                    "input_revision": "src-1", "idempotency_key": "gate-a"}
        decision.update(c.gate_inputs())
        c.apply("decision", decision)

    with tempfile.TemporaryDirectory(prefix="qa-t261-ctl-") as td:
        c, root_ = story_at_gate_a(td)
        lines = PC.apply_gate_answers(root_, "approved as it stands")
        check_in("the pass converted the real controller's row", "made executable", " ".join(lines))
        decide(c)
        c._validate_gate_a_content_current(c.state())
        check("K1: a decision bound after the pass is current (nothing raised)", True)
        path = root_ / "work" / "test-plan.json"
        document = json.loads(path.read_text(encoding="utf-8"))
        document["rows"][0]["coverage_obligations"][0]["behavior"] = "edited after approval"
        path.write_text(json.dumps(document), encoding="utf-8")
        try:
            c._validate_gate_a_content_current(c.state())
            check("a later plan edit still fires `Gate A plan content changed after approval`", False)
        except StateConflict as exc:
            check_in("a later plan edit still fires `Gate A plan content changed after approval`",
                     "Gate A plan content changed after approval", str(exc))
    with tempfile.TemporaryDirectory(prefix="qa-t261-ctl2-") as td:
        c, root_ = story_at_gate_a(td)
        decide(c)                                           # the mutation: the decision FIRST ...
        PC.apply_gate_answers(root_, "approved as it stands")   # ... then the pass writes the plan
        try:
            c._validate_gate_a_content_current(c.state())
            check("control: a pass AFTER the decision makes the approval stale", False)
        except StateConflict as exc:
            check_in("control: a pass AFTER the decision makes the approval stale (why the pass sits before it)",
                     "Gate A plan content changed after approval", str(exc))


def pass_story(rows, cases=None, prefix="qa-t261-pass-"):
    return gate_a_story(prefix, rows, [register("Q1")], cases or {}, ticket="QA-9")


def manual_row(rid="TS-5", obligations=None, **extra):
    """A `manual-agent` row of the new shape with one `new`, resolved, current-task obligation."""
    return v2_row(rid, disposition="manual-agent", **extra) if obligations is None else \
        row(rid, schema_version=2, disposition="manual-agent", coverage_obligations=obligations, **extra)


def run_pass(rows, cases=None) -> tuple:
    """(rows after, printed lines) of the applier over a gate A that says nothing about any question."""
    root, task = pass_story(rows, cases)
    try:
        lines = PC.apply_gate_answers(task, "go on")
        return rows_of(task), lines
    finally:
        cleanup(root)


def test_t261_error_direction_toward_not_executable() -> None:
    def ob(oid="OB-X", **over):
        return dict(obligation(oid), **over)

    def only(rows, rid, oid):
        return obligations_of(rows, rid)[oid]

    cases = [
        ("an unresolved oracle (decision `new`, status `unresolved`)",
         ob(oracle_status="unresolved", oracle_source_ref=""), "what the right answer is has not been settled"),
        ("`recommended_regression` scope", ob(execution_scope="recommended_regression"),
         "it is a recommendation for later"),
        ("an evidence rule that is none of the closed list", ob(evidence_policy="screenshots"),
         "its evidence rule `screenshots` is not one of"),
        ("a `reuse` obligation with no planned check (C1: the plan would stop passing its own check)",
         ob(decision="reuse", planned_check_refs=[], coverage_links=[
             {"test_ref": "t::x", "assessment": "sufficient", "assessment_reason": "r", "does_not_prove": [],
              "assertion_refs": ["t.py:1"], "proves": ["p"]}]),
         "would stop passing its own check"),
    ]
    for name, obligation_, said in cases:
        rows, lines = run_pass([manual_row("TS-5", [obligation_], level="api")])
        got = only(rows, "TS-5", "OB-X")
        check_eq(f"{name}: the obligation is NOT converted", got["decision"], obligation_["decision"])
        check_eq(f"{name}: and carries no evidence rule it did not have", got.get("evidence_policy"),
                 obligation_.get("evidence_policy"))
        check_in(f"{name}: ONE line names why", said, "\n".join(lines))
        check_eq(f"{name}: and says it for that obligation only", len([ln for ln in lines if "OB-X stays as planned" in ln]), 1)
    # C2-1 (site 36): a hand-made executable obligation that would break SEVERAL checks names all of them, with the count
    # (a person decides on the whole list); one problem reads as before; each is still cut to 200 characters (one line's length)
    import coverage_contract as CCON
    held = CCON.validate_obligations
    try:
        for problems, expected in ((["the first break", "the second break"],
                                    "(2 problem(s): the first break; the second break)"),
                                   (["only one break"], "(only one break)"),
                                   (["x" * 300, "y"], "(2 problem(s): " + "x" * 200 + "; y)")):
            CCON.validate_obligations = lambda _works, _p=problems: list(_p)
            rows, lines = run_pass([manual_row("TS-5", [ob("OB-X")], level="api")])
            check_eq(f"{len(problems)} broken check(s): the obligation is not converted",
                     only(rows, "TS-5", "OB-X")["decision"], ob("OB-X")["decision"])
            check_in(f"{len(problems)} broken check(s): the line says {expected[:30]}...", expected, "\n".join(lines))
    finally:
        CCON.validate_obligations = held
    # levels: component and unit are no manual level; a level the table does not hold stays as planned
    for level, said in (("component", "level `component`: not a manual level"), ("unit", "level `unit`: not a manual level"),
                        ("e2e-mobile", "the level `e2e-mobile` has no evidence rule in references/manual-policy-by-level.json"),
                        ("", "the level `unstated` has no evidence rule")):
        rows, lines = run_pass([manual_row("TS-5", [ob("OB-X")], level=level)])
        check_eq(f"level {level or '(none)'}: not converted", only(rows, "TS-5", "OB-X")["decision"], "new")
        check_in(f"level {level or '(none)'}: the line says why", said, "\n".join(lines))
    # the row's own rule outranks the level; the obligation's own outranks the row's
    rows, _ = run_pass([manual_row("TS-5", [ob("OB-X")], level="component", evidence_policy="static")])
    check_eq("a row that names its own evidence rule needs no level (component + `static`)",
             (only(rows, "TS-5", "OB-X")["decision"], only(rows, "TS-5", "OB-X")["evidence_policy"]),
             ("manual-agent", "static"))
    rows, _ = run_pass([manual_row("TS-5", [ob("OB-X", evidence_policy="cli")], level="api", evidence_policy="static")])
    check_eq("the obligation's own rule wins over the row's and the level's", only(rows, "TS-5", "OB-X")["evidence_policy"], "cli")
    # a row with no obligations: one line, nothing else
    rows, lines = run_pass([row("TS-5", disposition="manual-agent", level="e2e-ui")])
    check_eq("a row with no obligations: no obligation appears", "coverage_obligations" in rows["TS-5"], False)
    check_eq("...one line says the plan lists nothing the check must prove",
             len([ln for ln in lines if "plan lists nothing the check must prove" in ln]), 1)
    # decisions that are not the pass's to change
    for decision, extra in (("manual-human", {}), ("unresolved", {"remaining_gap": "waiting for the person"}),
                            ("manual-agent", {"evidence_policy": "ui"})):
        rows, lines = run_pass([manual_row("TS-5", [ob("OB-X", decision=decision, **extra)], level="api")])
        check_eq(f"decision `{decision}` is left exactly as it was", only(rows, "TS-5", "OB-X"),
                 ob("OB-X", decision=decision, **extra))
        # HF4-14 Q-2 (AR-19, one behaviour on both roads): `unresolved` is named only in a run that converted a row (below);
        # a run that changed nothing, like the same words applied again, prints nothing about it
        check_eq(f"decision `{decision}`: and no line is printed about it when the run changes nothing",
                 [ln for ln in lines if "OB-X" in ln], [])
    rows, lines = run_pass([manual_row("TS-5", [ob("OB-X", decision="unresolved", remaining_gap="waiting for the person"),
                                                ob("OB-Y")], level="api")])
    check_eq("HF4-14 Q-2: a run that converts OB-Y names the unresolved OB-X once, with the reason",
             len([ln for ln in lines if "OB-X stays as planned" in ln and "has not been settled" in ln]), 1)
    check_eq("...and OB-X itself is left exactly as it was", only(rows, "TS-5", "OB-X"),
             ob("OB-X", decision="unresolved", remaining_gap="waiting for the person"))
    # an obligation of an AUTOMATED row is never touched
    rows, lines = run_pass([v2_row("TS-5", disposition="automate")])
    check_eq("an automated row's obligation stays `new`", only(rows, "TS-5", "OB-TS-5")["decision"], "new")
    # the pass never takes the answers down: a plan that is no list of objects says nothing and raises nothing
    root, task = pass_story([manual_row("TS-5")])
    try:
        held = PC._manual_agent_pass

        def boom(*args, **kwargs):
            raise RuntimeError("the cases broke")
        PC._manual_agent_pass = boom
        try:
            lines = PC.apply_gate_answers(task, "go on")
        finally:
            PC._manual_agent_pass = held
        check_in("a pass that raises is one line, and the plan stays as planned",
                 "the checks by an agent were not made executable (RuntimeError: the cases broke)", "\n".join(lines))
        check_eq("...with the obligation as it was", obligations_of(rows_of(task), "TS-5")["OB-TS-5"]["decision"], "new")
    finally:
        cleanup(root)


def test_t261_the_policy_table_is_data_and_both_worlds_are_tested() -> None:
    """TEMPORAL: the file is created by this task. Present -> the pass converts; absent, unreadable, empty or
    with no usable level -> the pass converts nothing and says so in one line (FR-13)."""
    rows = [manual_row("TS-5", level="api"), manual_row("TS-6", level="e2e-ui")]
    table = json.loads(PC.MANUAL_POLICY_PATH.read_text(encoding="utf-8"))
    check_eq("the shipped table maps e2e-ui -> ui, api -> api, cli -> cli",
             {k: v.get("policy") for k, v in table["levels"].items() if v.get("policy")},
             {"e2e-ui": "ui", "api": "api", "cli": "cli"})
    check_eq("...and refuses component and unit as no manual level",
             sorted(k for k, v in table["levels"].items() if v.get("refused")), ["component", "unit"])
    done, lines = run_pass(copy.deepcopy(rows))
    check_eq("the table present: both rows are converted, with the rule of their level",
             [(r, obligations_of(done, r)[f"OB-{r}"]["decision"], obligations_of(done, r)[f"OB-{r}"]["evidence_policy"])
              for r in ("TS-5", "TS-6")], [("TS-5", "manual-agent", "api"), ("TS-6", "manual-agent", "ui")])
    held = PC.MANUAL_POLICY_PATH
    scratch = temp_dir(prefix="qa-t261-table-")
    try:
        variants = {"absent": scratch / "nothing.json", "unreadable": scratch / "broken.json",
                    "empty levels": scratch / "empty.json", "no usable level": scratch / "bad.json",
                    "levels is a list": scratch / "list.json", "a BOM-less empty file": scratch / "blank.json"}
        variants["unreadable"].write_text("{not json", encoding="utf-8")
        variants["empty levels"].write_text('{"levels": {}}', encoding="utf-8")
        variants["no usable level"].write_text('{"levels": {"api": {"policy": ""}, "ui": 3}}', encoding="utf-8")
        variants["levels is a list"].write_text('{"levels": ["api"]}', encoding="utf-8")
        variants["a BOM-less empty file"].write_text("", encoding="utf-8")
        for name, path in variants.items():
            PC.MANUAL_POLICY_PATH = path
            try:
                done, lines = run_pass(copy.deepcopy(rows))
            finally:
                PC.MANUAL_POLICY_PATH = held
            check_eq(f"table {name}: nothing is converted",
                     [obligations_of(done, r)[f"OB-{r}"]["decision"] for r in ("TS-5", "TS-6")], ["new", "new"])
            check_eq(f"table {name}: ONE line says the table is missing or empty",
                     len([ln for ln in lines if "the table of evidence rules by level" in ln]), 1)
    finally:
        PC.MANUAL_POLICY_PATH = held
        cleanup(scratch)
    check_eq("and the shipped table is back: the pass converts again", run_pass(copy.deepcopy(rows))[0]["TS-5"]
             ["coverage_obligations"][0]["decision"], "manual-agent")


def test_t261_c2_an_unconfirmed_expectation_is_never_made_executable() -> None:
    """C2 (P20): cmp2's TC_015 covers R-19, which exists only in the new code and was asked about nobody - the
    free negative control. Both ends refuse: the pass leaves OB-15 `new` (this test), `prepare` refuses it
    (test_manual_evidence.py)."""
    sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures" / "manual-evidence"))
    import scaffold as S
    t = S.make_task(manual=())
    try:
        use_project(t.project)
        words = "\n".join(f"{S.CASES[k]}: manual" for k in ("ui", "api", "impl"))
        before = {r["id"]: r for r in t.plan_rows}
        check_eq("setup: TS-15 is automated and OB-15 is `new`/resolved", (before["TS-15"]["disposition"],
                 before["TS-15"]["coverage_obligations"][0]["decision"],
                 before["TS-15"]["coverage_obligations"][0]["oracle_status"]), ("automate", "new", "resolved"))
        lines = PC.apply_gate_answers(t.task, words)
        after = rows_of(t.task)
        check_eq("TS-12 (AC-backed R-14): made executable, policy `api` from its level",
                 (obligations_of(after, "TS-12")["OB-12"]["decision"], obligations_of(after, "TS-12")["OB-12"]["evidence_policy"]),
                 ("manual-agent", "api"))
        check_eq("TS-7: made executable, policy `ui`", obligations_of(after, "TS-7")["OB-7"]["decision"], "manual-agent")
        check_eq("C2: TS-15's row is now checked by hand (the person's word) but OB-15 stays `new`",
                 (after["TS-15"]["disposition"], obligations_of(after, "TS-15")["OB-15"]["decision"]), ("manual-agent", "new"))
        said = [ln for ln in lines if "OB-15 stays as planned" in ln]
        check_eq("C2: ONE line says why", len(said), 1)
        check_in("C2: it names the requirement and that no question was raised",
                 "expectation unconfirmed: R-19 exists only in the new code and no question about it is linked in the register",
                 said[0] if said else "")
        # the same refusal is what `prepare` gives: one reader of the expectation, two ends
        import manual_evidence as ME
        with t.patched():
            try:
                ME.prepare_request(t.task, S.CASES["impl"], ["OB-15"])
                check("C2: prepare refuses the same obligation", False)
            except ME.Refused as exc:
                check_in("C2: prepare refuses the same obligation with the same words", "expectation unconfirmed", exc.reason)
    finally:
        S.cleanup(t)


def test_t261_the_plan_date_reaches_the_branch_checks_and_the_readiness_file_is_read_through_the_layout() -> None:
    """The four integration lines that are not story_run's: `plan_created` at the rehearsal's and the S3 exit's
    branch checks (O12), and `runtime_paths.readiness` for the stand check (both layouts)."""
    import stage_done
    reason_only = [row("TS-5", disposition="manual-agent", reason="manual until Q5 is answered")]
    for created, expected in (("2026-10-02", 1), ("2026-10-01", 0), (None, 0)):
        root, task = story("qa-t261-o12-", plan=reason_only, questions=[register("Q5")])
        try:
            use_project(root)
            if created:
                (task / "work" / "test-plan.json").write_text(json.dumps({"rows": reason_only, "created": created}),
                                                              encoding="utf-8")
            found = [f for f in branch_findings(task).findings if f["check"] == "question_branches"]
            check_eq(f"the rehearsal: a plan created {created or '(undated)'} -> {expected} missing-branch finding(s)",
                     len(found), expected)
            seen = []
            held = PC.variant_errors

            def spy(*args, **kwargs):
                seen.append(kwargs.get("plan_created"))
                return held(*args, **kwargs)
            PC.variant_errors = spy
            try:
                stage_done.s3_branch_line(task)
                branch_findings(task)
            finally:
                PC.variant_errors = held
            if created and created >= "2026-10-02":
                check_eq(f"the S3 exit and the rehearsal both hand the date ({created}) to variant_errors",
                         seen, [created, created])
            else:
                check_eq("an undated or earlier plan: the branch contract is not entered, so the check is not reached",
                         seen, [])
        finally:
            cleanup(root)
    # readiness through the layout: the new place, the old place, and none
    ready = json.dumps({"capabilities": {"environment": {"status": "missing", "note": "stand down"},
                                         "test_repo": {"status": "ok"}}})
    for label, where, said in (("new layout (state/)", ("qa-factory", "state", "readiness.json"), "the last probe of `environment`"),
                               ("old layout (beside the config)", ("qa-factory", "readiness.json"), "the last probe of `environment`"),
                               ("no file at all", None, "no readiness.json")):
        root, task = story("qa-t261-ready-", plan=reason_only)
        try:
            use_project(root)
            if where:
                target = root.joinpath(*where)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(ready, encoding="utf-8")
            r = gate_preflight.Rehearsal(task, "A")
            r.check_stand()
            check_in(f"the stand check reads the readiness file of the {label}", said,
                     " | ".join(f["message"] for f in r.findings))
        finally:
            cleanup(root)


# --- HF2-7 P3: an answer recorded AFTER the plan was written (TP1-12586) ---------------------------------------
# F-12586-plan: TS-3 and TS-10 branch on Q5 (a, b); TS-4 on Q1 with a branch for `a` only; TS-7 names Q5 and has no
# `if_answered`; TC-011 has Q5 text for `b` only, TC-012 for a and b, TC-013 for a (empty text) and b.

LATE_AT = "2026-10-26T10:00:00+00:00"
LATE_AT2 = "2026-10-26T11:00:00+00:00"
LATE_IDS = ("TS-3", "TS-10", "TS-4", "TS-7")


def late_plan() -> list:
    q5 = {"a": {"level": "e2e"}, "b": {"level": "ui"}}
    return [row("TS-3", question_refs=["Q5"], if_answered={"Q5": q5}),
            row("TS-10", question_refs=["Q5"], if_answered={"Q5": dict(q5)}),
            row("TS-4", question_refs=["Q1"], if_answered={"Q1": {"a": {"level": "e2e"}}}),
            row("TS-7", question_refs=["Q5"])]


def late_cases() -> dict:
    return {"TC-011": case_text("TC-011", json.dumps([qt("Q5", 1, {"b": "y"})])),
            "TC-012": case_text("TC-012", json.dumps([qt("Q5", 1, {"a": "x", "b": "y"})])),
            "TC-013": case_text("TC-013", json.dumps([qt("Q5", 1, {"a": "", "b": "z"})]))}


def late_story(prefix, plan=None, readiness=None, pipeline=None, cases=None):
    """A story at S3 with the F-12586-plan, a two-question register and the three cases; `plan=False`: no plan file."""
    root, task = gate_a_story(prefix, late_plan() if plan is None else (plan or []),
                              readiness if readiness is not None else [register("Q1"), register("Q5")], {},
                              case_texts=late_cases() if cases is None else cases)
    if plan is False:
        (task / "work" / "test-plan.json").unlink()
    if pipeline is not None:
        (task / "pipeline.json").write_text(json.dumps(dict({"ticket": CMP2, "stages": {}}, **pipeline)), encoding="utf-8")
    return root, task


def say(task, qid, letter=None, status="answered", at=LATE_AT, where="S3 stop") -> None:
    """Record the person's answer against the row as it stands now (a reopen: status `open`, no hash)."""
    shown = "" if status == "open" else {q["id"]: q for q in QR.load(task)["questions"]}[qid]["row_hash"]
    QR.record(task, qid, status, f"{qid}: {letter or status}", where, "person", shown, reading=letter or "", at=at)


def applied_of(task) -> list:
    return [r for r in read_lines(task / "work" / "question-answers.jsonl") if r.get("kind") == "answers_applied"]


def late(task, where="S3 stop") -> dict:
    return PC.apply_recorded_answers(task, where, "driver")


def work_of(res) -> set:
    return {(w["owner"], w["where"], w["question"], w["answer"]) for w in res["rework"]}


def set_register(task, questions) -> None:
    (task / "work" / "requirements-readiness.json").write_text(
        json.dumps({"verdict": "blocked", "open_questions": questions}), encoding="utf-8")


def plan_bytes(task) -> bytes:
    return (task / "work" / "test-plan.json").read_bytes()


def settled_findings(task) -> set:
    """(where, question) of every `settled_question` the gate-A rehearsal gives for the story."""
    return {(f["where"], f["question"]) for f in branch_findings(task).findings if f.get("kind") == "settled_question"}


def test_hf27_k2_k4_k6_k9_the_late_answer_patches_names_rework_and_the_rehearsal_agrees() -> None:
    root, task = late_story("qa-hf27-k2-")
    try:
        say(task, "Q5", "a")
        say(task, "Q1", "b")
        before = settled_findings(task)
        check_eq("K6 control: Q5 recorded, not applied - the rehearsal names TS-3, TS-10 and TC-011 (and TS-4 for Q1)",
                 before, {("TS-3", "Q5"), ("TS-10", "Q5"), ("TS-4", "Q1"), ("TC-011", "Q5")})
        res = late(task)
        rows = rows_of(task)
        original = {r["id"]: r for r in late_plan()}
        check_eq("K2: TS-3 is patched by `a` and Q5 leaves it", (rows["TS-3"].get("level"), "if_answered" in rows["TS-3"],
                 "question_refs" in rows["TS-3"]), ("e2e", False, False))
        check_eq("K2: TS-10 the same", (rows["TS-10"].get("level"), "if_answered" in rows["TS-10"]), ("e2e", False))
        check_eq("K2: TS-4 stays byte for byte (no branch for `b`)", rows["TS-4"], original["TS-4"])
        check_eq("K2: TS-7 (named, no branch) stays", rows["TS-7"], original["TS-7"])
        check_eq("K2: the rework is TS-4 for Q1=b and TS-7 (R5: it names Q5 and has no branch) to the strategist, TC-011 for Q5=a to the designer",
                 work_of(res), {("strategist", "TS-4", "Q1", "b"), ("strategist", "TS-7", "Q5", "a"), ("designer", "TC-011", "Q5", "a")})
        check_eq("K2: TC-012 and TC-013 (an empty text is a text) get no rework",
                 {w["where"] for w in res["rework"]} & {"TC-012", "TC-013"}, set())
        records = {r["id"]: r for r in applied_of(task)}
        check_eq("K2: answers_applied carries record_at and the rows moved",
                 (records["Q5"]["record_at"], sorted(records["Q5"]["rows"]), records["Q1"]["rows"]),
                 (LATE_AT, ["TS-10", "TS-3"], []))
        check_eq("K6: the rehearsal names exactly what `rework` named",
                 settled_findings(task), {("TS-4", "Q1"), ("TC-011", "Q5")})
        after = (plan_bytes(task), (task / "work" / "question-answers.jsonl").read_bytes())
        again = late(task)
        check_eq("K4: a second call is empty and writes nothing", (again, plan_bytes(task),
                 (task / "work" / "question-answers.jsonl").read_bytes()), ({"lines": [], "rework": [], "applied": []}, *after))
        # K9: the person changes their mind - reopen, answer Q5 = b
        say(task, "Q5", status="open", at=LATE_AT2)
        say(task, "Q5", "b", at="2026-10-26T12:00:00+00:00")
        res = late(task)
        check_eq("K9: no patch; the rows the first answer moved go back to the strategist",
                 {w["where"] for w in res["rework"] if w["owner"] == "strategist"}, {"TS-3", "TS-10", "TS-7"})
        check_in("K9: the line names both answers", "your answer is now `b`, but the test plan was written for `a`",
                 " ".join(res["lines"]))
        import human_text
        check_eq("K11: the line of edge 9 obeys the text rules", human_text.problems(" ".join(res["lines"]), kind="report"), [])
        check_eq("K9: the plan is as it was", plan_bytes(task), after[0])
        not_applied = [r for r in applied_of(task) if r.get("not_applied")]
        check_eq("K9: `not_applied` is written once", len(not_applied), 1)
        check_eq("K9: and a repeat is empty", late(task)["rework"], [])
    finally:
        cleanup(root)


def test_hf27_k3_1_a_changed_answer_or_a_missing_before_value_is_never_applied() -> None:
    changed = dict(register("Q5"), question="Which behaviour for Q5, asked differently?")
    root, task = late_story("qa-hf27-k3-1-")
    try:
        say(task, "Q5", "a")
        set_register(task, [register("Q1"), changed])
        original = plan_bytes(task)
        res = late(task)
        check_eq("(1) the plan is untouched and nothing is reworked", (plan_bytes(task), res["rework"]), (original, []))
        check_in("(1) one line: asked again", "Q5: its text changed after your answer, so it is asked again", res["lines"][0])
        check_eq("(1) one record, `changed_since_answer`", [(r["id"], r["not_applied"]) for r in applied_of(task)],
                 [("Q5", "changed_since_answer")])
        check_eq("(1) said once", (late(task)["lines"], len(applied_of(task))), ([], 1))
    finally:
        cleanup(root)
    unknown = dict(register("Q5", 2), before={"value": "unknown", "where": "x"})
    root, task = late_story("qa-hf27-k3-1b-", readiness=[register("Q1"), unknown])
    try:
        say(task, "Q5", "b")
        res = late(task)
        check_eq("(1) `b` on a before/now question with no `before` value is not applied either",
                 (rows_of(task)["TS-3"].get("level"), [r["not_applied"] for r in applied_of(task)]),
                 ("api", ["before_value_missing"]))
        check_in("(1) and the line says what is missing", "nobody knows what it was", res["lines"][0])
    finally:
        cleanup(root)


def test_d1a_k_a3_the_not_applied_label_says_which_cause() -> None:
    """RN1-11 A3: an unchanged row whose `before` value is missing is `before_value_missing`; a changed row stays `changed_since_answer`."""
    empty = dict(register("Q5", 2), before={"value": "", "where": "x"})
    root, task = late_story("qa-d1a-a3-", readiness=[register("Q1"), empty])
    try:
        say(task, "Q5", "b")
        res = late(task)
        check_eq("K-A3: unchanged row, `b`, empty before, no stamp -> before_value_missing",
                 [(r["id"], r["not_applied"]) for r in applied_of(task)], [("Q5", "before_value_missing")])
        check_in("K-A3: and the line is the gate's own before-value note", "nobody knows what it was", res["lines"][0])
    finally:
        cleanup(root)
    root, task = late_story("qa-d1a-a3b-", readiness=[register("Q1"), empty])
    try:
        say(task, "Q5", "b")
        set_register(task, [register("Q1"), dict(empty, question="Which behaviour for Q5, asked differently?")])
        late(task)
        check_eq("K-A3 pin: a changed row -> changed_since_answer", [r["not_applied"] for r in applied_of(task)], ["changed_since_answer"])
    finally:
        cleanup(root)


def test_d1a_k_a6_every_row_that_rests_on_the_answer_is_moved_or_named() -> None:
    """RN1-11 A6 / run-3 R5: a row with no prepared patch is NAMED (a line plus the strategist's rework), never left silent."""
    def lines_of(res):
        return [x for x in res["lines"] if "has no prepared change in the test plan" in x]
    patched = row("TS-1", question_refs=["Q1"], if_answered={"Q1": {"a": {"level": "e2e"}}})
    cases_ = (
        ("1 empty branch object", row("TS-2", question_refs=["Q1"], if_answered={"Q1": {}}), True),
        ("2 question_refs, no if_answered", row("TS-2", question_refs=["Q1"]), True),
        # (re-pinned, Q2 t-1752: `if_answered[Q1]` present and no object is the other half of a shape finding - not ours, like `if_answered` that is no object)
        ("2b if_answered[Q1] is no object: a shape finding, not named", row("TS-2", question_refs=["Q1"], if_answered={"Q1": "oops"}), False),
        ("2c if_answered holds another question's object only: named", row("TS-2", question_refs=["Q1"], if_answered={"Q5": {"a": {"level": "e2e"}}}), True),
        ("3 another question's row", row("TS-2", question_refs=["Q5"]), False),
    )
    for label, other, named in cases_:
        root, task = late_story("qa-d1a-a6-", plan=[patched, other], cases={})
        try:
            say(task, "Q1", "a")
            res = late(task)
            got = lines_of(res)
            check_eq(f"K-A6({label}): the patched row is moved and the other is named exactly when it rests on Q1",
                     (rows_of(task)["TS-1"].get("level"), work_of(res)),
                     ("e2e", {("strategist", "TS-2", "Q1", "a")} if named else set()))
            check_eq(f"K-A6({label}): one line for it, none otherwise", len(got), 1 if named else 0)
            if named:
                check_in(f"K-A6({label}): the line names the row, the answer and the owner",
                         "TS-2: your answer Q1 = `a` has no prepared change in the test plan, so the test planner reworks this row", got[0])
            check_eq(f"K-A6({label}): the moved row gets no line of this form", [x for x in got if x.startswith("TS-1:")], [])
        finally:
            cleanup(root)
    # E-A7: a row with both `question_refs` and an `if_answered[Q1]` object that yields no patch is named ONCE
    root, task = late_story("qa-d1a-a7-", plan=[row("TS-2", question_refs=["Q1"], if_answered={"Q1": {"b": {"level": "ui"}}})], cases={})
    try:
        say(task, "Q1", "a")
        res = late(task)
        check_eq("K-A6 (E-A7): named once, not twice", (len(lines_of(res)), len(res["rework"])), (1, 1))
    finally:
        cleanup(root)


def test_hf27_k3_2_3_4_10_17_other_statuses_missing_keys_odd_shapes_and_an_answer_in_words() -> None:
    root, task = late_story("qa-hf27-k3-2-")
    try:
        say(task, "Q5", status="deferred_to_report")
        original = plan_bytes(task)
        check_eq("(2) a deferred question applies nothing and writes nothing", (late(task), plan_bytes(task), applied_of(task)),
                 ({"lines": [], "rework": [], "applied": []}, original, []))
        say(task, "Q5", "a", at=LATE_AT2)
        say(task, "Q5", status="open", at="2026-10-26T12:00:00+00:00")
        check_eq("(2) a reopened (open) question the same", (late(task)["rework"], plan_bytes(task)), ([], original))
    finally:
        cleanup(root)
    root, task = late_story("qa-hf27-k3-3-")
    try:
        say(task, "Q1", status="not_needed")
        res = late(task)
        check_eq("(3) `not_needed` with no `not_needed` key: the row stays and goes to the strategist",
                 work_of(res), {("strategist", "TS-4", "Q1", "not_needed")})
    finally:
        cleanup(root)
    odd = [row("TS-A", question_refs=["Q5"], if_answered="oops"), row("TS-B", question_refs=["Q5"], if_answered={"Q5": "oops"}),
           row("TS-C", question_refs=["Q99"], if_answered={"Q99": {"a": {"level": "e2e"}}})]
    root, task = late_story("qa-hf27-k3-4-", plan=odd, cases={})
    try:
        say(task, "Q5", "a")
        original = plan_bytes(task)
        # (re-pinned, Q2 t-1752: TS-B's `if_answered[Q5]` is present and no object - the other half of the shape finding, so it is not named either)
        check_eq("(4)(10) a shape finding is not ours and an id the register lacks is not touched: no write; TS-A (`if_answered` is "
                 "no object), TS-B (`if_answered[Q5]` is no object: a shape finding) and TS-C (rests on Q99) are not named",
                 (work_of(late(task)), plan_bytes(task)),
                 (set(), original))
        check_eq("(4) the answer is still marked applied, with no rows", [r["rows"] for r in applied_of(task)], [[]])
    finally:
        cleanup(root)
    root, task = late_story("qa-hf27-k3-17-")
    try:
        say(task, "Q5")
        res = late(task)
        check_eq("(17) an answer in words patches nothing; both rows go to the strategist", (
                 {w["where"] for w in res["rework"] if w["owner"] == "strategist"}, rows_of(task)["TS-3"].get("level"),
                 {w["answer"] for w in res["rework"]}), ({"TS-3", "TS-10", "TS-7"}, "api", {""}))
        check_eq("(17) and every case with an entry on Q5 goes to the designer",
                 {w["where"] for w in res["rework"] if w["owner"] == "designer"}, {"TC-011", "TC-012", "TC-013"})
    finally:
        cleanup(root)


def test_hf27_k3_5_6_7_11_12_13_no_plan_unreadable_plan_gate_approved_a_crash_old_records_and_k7() -> None:
    root, task = late_story("qa-hf27-k3-5-", plan=False)
    try:
        say(task, "Q5", "a")
        res = late(task)
        check_eq("(5) no plan: one `before_plan` mark, nothing else", ([(r["id"], r.get("before_plan"), r["rows"]) for r in applied_of(task)],
                 res["rework"], story_plan_exists(task)), ([("Q5", True, [])], [], False))
        late(task)
        check_eq("(5) and the mark is not written twice", len(applied_of(task)), 1)
        (task / "work" / "test-plan.json").write_text(json.dumps({"rows": late_plan()}), encoding="utf-8")
        res = late(task)
        check_eq("(13) K7: the plan has appeared - the first pass applies; the mark is no key",
                 (rows_of(task)["TS-3"].get("level"), [(r.get("before_plan"), sorted(r["rows"])) for r in applied_of(task)][1:]),
                 ("e2e", [(None, ["TS-10", "TS-3"])]))
    finally:
        cleanup(root)
    root, task = late_story("qa-hf27-k3-6-")
    try:
        say(task, "Q5", "a")
        (task / "work" / "test-plan.json").write_text("{not json", encoding="utf-8")
        before = (task / "work" / "question-answers.jsonl").read_bytes()
        res = late(task)
        check_eq("(6) an unreadable plan: one line, nothing written", (len(res["lines"]), res["rework"], applied_of(task),
                 (task / "work" / "question-answers.jsonl").read_bytes() == before), (1, [], [], True))
    finally:
        cleanup(root)
    root, task = late_story("qa-hf27-k3-7-", pipeline={"gates": {"A": {"decision": "approve"}}})
    try:
        say(task, "Q5", "a")
        original = plan_bytes(task)
        res = late(task)
        check_eq("(7) H14: gate A approved - the plan is the approved one, no rework", (plan_bytes(task), res["rework"]), (original, []))
        check_eq("(7) T7 once", res["lines"], ["Q5: you have already approved the test plan at gate A, so your answer is recorded "
                                               "but does not change the plan."])
        import human_text
        check_eq("K11: T7 obeys the text rules", human_text.problems(res["lines"][0], kind="report"), [])
        check_eq("(7) one record `gate A approved`; a repeat is empty", ([r["not_applied"] for r in applied_of(task)],
                 late(task)["lines"]), (["gate A approved"], []))
    finally:
        cleanup(root)
    root, task = late_story("qa-hf27-k3-11-")
    try:
        say(task, "Q5", "a")
        original = plan_bytes(task)
        import event_store
        real = event_store.atomic_json

        def broken(*args, **kwargs):
            raise OSError("disk full")
        event_store.atomic_json = broken
        try:
            res = late(task)
        finally:
            event_store.atomic_json = real
        check_eq("(11) the plan write fails: the plan is whole as it was and no record says it was applied",
                 (plan_bytes(task), applied_of(task), len(res["lines"])), (original, [], 1))
        late(task)
        check_eq("(11) the next pass applies it", rows_of(task)["TS-3"].get("level"), "e2e")
    finally:
        cleanup(root)
    root, task = late_story("qa-hf27-k3-12-")
    try:
        say(task, "Q5", "a")
        QR._append(task, {"kind": "answers_applied", "what": "question", "id": "Q5", "answer": "a", "rows": ["TS-3"],
                          "where": "gate A", "by": "driver", "at": "2026-10-25T10:00:00+00:00"})
        original = plan_bytes(task)
        check_eq("(12) a record written by gate A (no record_at) matches by id and answer: nothing again",
                 (late(task), plan_bytes(task)), ({"lines": [], "rework": [], "applied": []}, original))
    finally:
        cleanup(root)


def story_plan_exists(task) -> bool:
    return (task / "work" / "test-plan.json").is_file()


def test_hf27_k3_15_the_same_answer_asked_again_on_a_changed_row_only_notes_it() -> None:
    root, task = late_story("qa-hf27-k3-15-")
    try:
        say(task, "Q5", "a")
        late(task)
        set_register(task, [register("Q1"), dict(register("Q5"), question="Q5 asked differently")])
        check_eq("(15) the row changed after the answer: the plan already followed it, nothing to say", late(task)["lines"], [])
        say(task, "Q5", "a", at=LATE_AT2)
        original = plan_bytes(task)
        res = late(task)
        check_eq("(15) answered again with the new bytes: one record with no rows, no patch, no rework",
                 (res["rework"], plan_bytes(task), [(r["record_at"], r["rows"]) for r in applied_of(task)][1:]),
                 ([], original, [(LATE_AT2, [])]))
    finally:
        cleanup(root)


def test_hf27_k6_n2_a_case_entry_with_the_recorded_key_is_resolved_and_the_rest_is_found() -> None:
    root, task = late_story("qa-hf27-k6-")
    try:
        say(task, "Q5", "a")
        late(task)
        cases = {"TC-011": case_text("TC-011", json.dumps([qt("Q5", 1, {"b": "y"})])),
                 "TC-012": case_text("TC-012", json.dumps([qt("Q5", 1, {"b": "y"})]))}
        for name, text in cases.items():
            (task / "work" / "test-cases" / "area" / f"{name}.md").write_text(text, encoding="utf-8", newline="\n")
        check_eq("K6 control: TC-012 with readings {b} only is a finding again", settled_findings(task),
                 {("TC-011", "Q5"), ("TC-012", "Q5")})
    finally:
        cleanup(root)
    # the same through the pure check: N2 (resolved), (16) the other checks of the entry still run, (18) an open question
    done = dict(q("Q1", 2, "answered"), reading="a")
    ok = [case("TC-1", thens_line=json.dumps([qt("Q1", 1, {"a": ""})]))]
    check_eq("(16) K6: the entry has the key (an empty text is one): no finding", run_pure([], [done], ok), [])
    nokey = [case("TC-1", thens_line=json.dumps([qt("Q1", 1, {"b": "y"})]))]
    check_eq("(16) no key for the recorded answer: settled_question", kinds(run_pure([], [done], nokey)), ["settled_question"])
    badthen = [case("TC-1", thens_line=json.dumps([qt("Q1", 9, {"a": "x"})]))]
    check_eq("(16) a resolved entry's `then` is still checked", kinds(run_pure([], [done], badthen)), ["bad_branch"])
    pair = [case("TC-1", thens_line=json.dumps([qt("Q1", 1, {"a": "x"}), qt("Q2", 1, {"a": "x", "b": "y"})]))]
    check_eq("(16) and a resolved entry still counts in the dependent pair",
             kinds(run_pure([], [done, q("Q2")], pair)), ["dependent_pair"])
    extra = [case("TC-1", thens_line=json.dumps([qt("Q1", 1, {"a": "x", "z": "?"})]))]
    check_eq("(16) the letter checks of a resolved entry do not run", run_pure([], [done], extra), [])
    gone = dict(q("Q1", 2, "not_needed"))
    check_eq("(16) `not_needed`: the entry needs a `not_needed` text",
             (kinds(run_pure([], [gone], [case("TC-1", thens_line=json.dumps([qt("Q1", 1, {"a": "x", "b": "y"})]))])),
              kinds(run_pure([], [gone], [case("TC-1", thens_line=json.dumps([qt("Q1", 1, {"a": "x", "b": "y"}, not_needed="")]))]))),
             (["settled_question"], []))
    words = dict(q("Q1", 2, "answered"))
    check_eq("(17) answered in words (no letter): the case entry is a finding", kinds(run_pure([], [words], ok)), ["settled_question"])
    moved = dict(done, changed_since_answer=True)
    rows = [row("TS-6", question_refs=["Q1"], if_answered={"Q1": {"a": {"level": "api"}}})]
    found = run_pure(rows, [moved], nokey, missing=True)
    check_eq("(18) a changed answer is not settled: the open-question checks run and `settled_question` is gone",
             ("settled_question" in kinds(found), "missing_branch" in kinds(found)), (False, True))
    check_eq("(18) K6 N3: the same for a `b` answer whose `before` value is missing",
             "settled_question" in kinds(run_pure(rows, [dict(done, reading="b", before={"value": "unknown"})], nokey)), False)
    old = [row("TS-6", question_refs=["Q1"], if_answered={"Q1": {"a": {"level": "api"}}})]
    check_eq("(16) a row with a branch on a settled question is still `settled_question`",
             kinds(run_pure(old, [done])), ["settled_question"])


def test_hf27_k1_one_patch_for_both_appliers_and_k8_gate_a_keeps_a_deferred_token() -> None:
    plain = row("TS-4", question_refs=["Q1", "Q2"], if_answered={"Q1": {"a": {"level": "e2e"}}, "Q2": {"*": {}}})
    patched = PC._apply_question_patch(plain, "Q1", "a")
    check_eq("K1: the patch is laid over, Q1 leaves the row and Q2 stays", (patched["level"], patched["question_refs"],
             sorted(patched["if_answered"])), ("e2e", ["Q2"], ["Q2"]))
    check_eq("K1: no branch for `b` is None and the row is not touched", (PC._apply_question_patch(plain, "Q1", "b"),
             plain["level"], sorted(plain["if_answered"])), (None, "api", ["Q1", "Q2"]))
    root, task = late_story("qa-hf27-k8-")
    try:
        lines = PC.apply_gate_answers(task, "Q1: until the report", where="gate A", by="driver")
        check_eq("K8: the deferred token is recorded and said, and is not an answer 'of the form'", (
                 [q["status"] for q in QR.load(task)["questions"] if q["id"] == "Q1"],
                 [line for line in lines if "until the report" in line]),
                 (["deferred_to_report"], ["gate A: Q1 is kept open until the report, on your word"]))
        check_not_in("K8: no `has no answer of the form` line for it", "Q1 has no answer", " ".join(lines))
        count = len(read_lines(task / "work" / "question-answers.jsonl"))
        again = PC.apply_gate_answers(task, "Q1: until the report", where="gate A", by="driver")
        check_eq("K8: a repeat records and says nothing about it", (any("kept open" in line for line in again),
                 len(read_lines(task / "work" / "question-answers.jsonl"))), (False, count))
        PC.apply_gate_answers(task, "Q5: a", where="gate A", by="driver")
        lines = PC.apply_gate_answers(task, "Q5: until the report", where="gate A", by="driver")
        check_eq("K8: a settled question keeps its answer", ([q["status"] for q in QR.load(task)["questions"] if q["id"] == "Q5"],
                 any("already settled" in line for line in lines)), (["answered"], True))
    finally:
        cleanup(root)


def at_hour(hour: int) -> str:
    return f"2026-10-27T{hour:02d}:00:00+00:00"


def strategist_of(res) -> set:
    return {w["where"] for w in res["rework"] if w["owner"] == "strategist"}


def test_hf310_a_changed_answer_reworks_from_the_last_answer_the_plan_was_asked_to_follow() -> None:
    import human_text
    root, task = late_story("qa-hf310-p1-")
    try:
        say(task, "Q5", "a", at=at_hour(1))
        late(task)
        # P1: reopen, answer `b`: the rows the first answer moved go back to the strategist, each saying what the plan was written for
        say(task, "Q5", status="open", at=at_hour(2))
        say(task, "Q5", "b", at=at_hour(3))
        res = late(task)
        check_eq("P1: TS-3 and TS-10 (moved) and TS-7 (named, R5) go to the strategist", strategist_of(res), {"TS-3", "TS-10", "TS-7"})
        check_eq("P1: each rework record says the answer it was written for (F5)",
                 {(w["answer"], w["was"]) for w in res["rework"]}, {("b", "a")})
        check_eq("P1 control: the branch is off the rows, so the rehearsal does not name them - the reader's blindness that "
                 "the pairs of the driver answer for", {w for w in settled_findings(task) if w[1] == "Q5" and w[0] in ("TS-3", "TS-10")},
                 set())
        check_eq("P1: the record of the change carries the rows it handed over",
                 sorted([r for r in applied_of(task) if r.get("not_applied")][-1]["rework_rows"]), ["TS-10", "TS-3", "TS-7"])
        # P2: back to the first answer - the plan was last asked to follow `b`, so this is a change too (E3)
        say(task, "Q5", status="open", at=at_hour(4))
        say(task, "Q5", "a", at=at_hour(5))
        res = late(task)
        check_eq("P2: TS-3, TS-10 and TS-7 go to the strategist, from `b` to `a`", (strategist_of(res), {(w["answer"], w["was"]) for w in res["rework"]
                 if w["owner"] == "strategist"}), ({"TS-3", "TS-10", "TS-7"}, {("a", "b")}))
        check_in("P2: the line names both answers", "your answer is now `a`, but the test plan was written for `b`", " ".join(res["lines"]))
        check_eq("P2: a repeat is empty", late(task), {"lines": [], "rework": [], "applied": []})
        # P3: the same answer again, a new record (the command line): no rework, one record with no rows
        count = len(applied_of(task))
        say(task, "Q5", "a", at=at_hour(6))
        res = late(task)
        check_eq("P3: the same answer again opens nothing", res["rework"], [])
        check_eq("P3: and is noted once, with no rows and no `not_applied`",
                 [(r["rows"], r.get("not_applied")) for r in applied_of(task)][count:], [([], None)])
        # P4: a change after that - the rows every earlier answer moved are still reachable (E5)
        say(task, "Q5", status="open", at=at_hour(7))
        say(task, "Q5", status="not_needed", at=at_hour(8))
        res = late(task)
        check_eq("P4: `not needed` after a rework: TS-3, TS-10 and TS-7 go to the strategist", strategist_of(res), {"TS-3", "TS-10", "TS-7"})
        check_in("P4: the line names the answer the plan was written for", "the test plan was written for `a`", " ".join(res["lines"]))
        check_eq("P4: `was` is `a`, the answer is `not_needed`", {(w["answer"], w["was"]) for w in res["rework"]}, {("not_needed", "a")})
        for line in res["lines"]:
            check_eq("K11: the line obeys the text rules", human_text.problems(line, kind="report"), [])
    finally:
        cleanup(root)
    # P5 (F4): a row the strategist was handed for the first answer (code could not patch it) is reworked at a change too
    root, task = late_story("qa-hf310-p5-")
    try:
        say(task, "Q1", "b", at=at_hour(1))
        res = late(task)
        check_eq("P5: TS-4 has no branch for `b`: handed to the strategist, no `was` yet", (strategist_of(res), [w.get("was") for w in res["rework"]]),
                 ({"TS-4"}, [None]))
        check_eq("P5: the record carries it as `rework_rows`", [r["rework_rows"] for r in applied_of(task) if r["id"] == "Q1"], [["TS-4"]])
        say(task, "Q1", status="open", at=at_hour(2))
        say(task, "Q1", "a", at=at_hour(3))
        res = late(task)
        check_eq("P5: a change to `a`: TS-4 is reworked although code never moved it", (strategist_of(res), {w["was"] for w in res["rework"]}),
                 ({"TS-4"}, {"b"}))
    finally:
        cleanup(root)
    # P6 (F7): an answer in the person's own words, twice
    root, task = late_story("qa-hf310-p6-")
    try:
        say(task, "Q5", at=at_hour(1))
        first = late(task)
        say(task, "Q5", at=at_hour(2))
        res = late(task)
        check_eq("P6: the words given again rework the rows and the cases once more, as the first time",
                 ({(w["owner"], w["where"]) for w in res["rework"]}, {w["was"] for w in res["rework"]}),
                 ({(w["owner"], w["where"]) for w in first["rework"]}, {""}))
        check_eq("P6: and there are rows and cases to rework", ({w["owner"] for w in res["rework"]}), {"strategist", "designer"})
        check_eq("P6: the line says it in the person's terms",
                 res["lines"], ["Q5: you answered in your own words again; the test planner reworks the parts that followed your earlier words."])
        check_eq("K11: and obeys the text rules", human_text.problems(" ".join(res["lines"]), kind="report"), [])
        check_eq("P6: a repeat of the same record is empty", late(task)["rework"], [])
    finally:
        cleanup(root)
    # P7 (E14): a record written before 0.10.3 (no `rework_rows`), and records with odd shapes
    root, task = late_story("qa-hf310-p7-")
    try:
        say(task, "Q5", "a", at=at_hour(1))
        QR._append(task, {"kind": "answers_applied", "what": "question", "id": "Q5", "answer": "a", "rows": ["TS-3", "TS-10"],
                          "record_at": at_hour(1), "where": "S3 stop", "by": "driver", "at": at_hour(1)})
        QR._append(task, {"kind": "answers_applied", "what": "question", "id": "Q5", "answer": "a", "rows": "TS-4",
                          "rework_rows": [5, None, "TS-7", ["TS-8"]], "record_at": at_hour(1), "where": "S3 stop", "by": "driver",
                          "at": at_hour(1)})
        check_eq("P7: the answer is already applied (the old record matches): nothing", late(task), {"lines": [], "rework": [], "applied": []})
        say(task, "Q5", status="open", at=at_hour(2))
        say(task, "Q5", "b", at=at_hour(3))
        res = late(task)
        check_eq("P7: only the rows that are lists of strings count: no exception, no non-string row",
                 strategist_of(res), {"TS-3", "TS-10", "TS-7"})
    finally:
        cleanup(root)
    # P8 (F2, E3 on the gate A road): the first answer came through gate A, whose record carried no `record_at`, so `_same_record`
    # took it for ANY later record of the same answer - a -> b -> a was read as "already applied"
    root, task = late_story("qa-hf310-p8-")
    try:
        PC.apply_gate_answers(task, "Q5: a")
        gate = [r for r in applied_of(task) if r["id"] == "Q5"]
        check_eq("P8: gate A writes the record of the answer it applied (`record_at`), as the late applier does",
                 [r.get("record_at") for r in gate], [{q["id"]: q for q in QR.load(task)["questions"]}["Q5"]["at"]])
        check_eq("P8: and the late applier finds that answer applied: nothing", late(task), {"lines": [], "rework": [], "applied": []})
        say(task, "Q5", status="open", at=at_hour(2))
        say(task, "Q5", "b", at=at_hour(3))
        res = late(task)
        check_eq("P8: a -> b: the rows gate A moved go to the strategist",
                 (strategist_of(res), {(w["answer"], w["was"]) for w in res["rework"] if w["owner"] == "strategist"}),
                 ({"TS-3", "TS-10"}, {("b", "a")}))
        say(task, "Q5", status="open", at=at_hour(4))
        say(task, "Q5", "a", at=at_hour(5))
        res = late(task)
        check_eq("P8: and back to `a` (the first was given at gate A): reworked from `b` to `a`, not read as applied",
                 (strategist_of(res), {(w["answer"], w["was"]) for w in res["rework"] if w["owner"] == "strategist"}),
                 ({"TS-3", "TS-10"}, {("a", "b")}))
    finally:
        cleanup(root)
    # P8b (E12): a gate A record of 0.10.2 and before has no `record_at` and still matches its own answer
    root, task = late_story("qa-hf310-p8b-")
    try:
        say(task, "Q5", "a", at=at_hour(1))
        QR._append(task, {"kind": "answers_applied", "what": "question", "id": "Q5", "answer": "a", "rows": ["TS-3", "TS-10"],
                          "where": "gate A", "by": "driver", "at": at_hour(1)})
        check_eq("P8b: an old gate A record (no record_at) matches by id and answer: nothing to apply",
                 late(task), {"lines": [], "rework": [], "applied": []})
    finally:
        cleanup(root)


def main() -> None:
    test_hf27_k2_k4_k6_k9_the_late_answer_patches_names_rework_and_the_rehearsal_agrees()
    test_hf310_a_changed_answer_reworks_from_the_last_answer_the_plan_was_asked_to_follow()
    test_hf27_k3_1_a_changed_answer_or_a_missing_before_value_is_never_applied()
    test_hf27_k3_2_3_4_10_17_other_statuses_missing_keys_odd_shapes_and_an_answer_in_words()
    test_hf27_k3_5_6_7_11_12_13_no_plan_unreadable_plan_gate_approved_a_crash_old_records_and_k7()
    test_hf27_k3_15_the_same_answer_asked_again_on_a_changed_row_only_notes_it()
    test_hf27_k6_n2_a_case_entry_with_the_recorded_key_is_resolved_and_the_rest_is_found()
    test_hf27_k1_one_patch_for_both_appliers_and_k8_gate_a_keeps_a_deferred_token()
    test_o1_the_patch_keys_are_a_closed_list_in_a_data_file()
    test_o1_a_letter_key_is_laid_over_the_star_key()
    test_o1_apply_patch_is_pure_and_replaces_the_whole_obligation_list()
    test_o2_an_empty_reading_text_is_a_valid_reading()
    test_o3_each_variant_is_applied_in_memory_and_must_pass_the_plan_contract()
    test_o3_an_oracle_unknown_row_carries_question_refs()
    test_o3_two_questions_patching_one_field_or_one_then_are_a_dependent_pair()
    test_o3_a_variants_reason_never_names_its_own_question()
    test_e19_a_variant_that_moves_a_row_repairs_the_reason_that_names_the_question()
    test_o3_ids_resolve_exactly_against_the_register()
    test_e2_an_answered_question_never_stays_as_a_branch()
    test_e9_a_story_with_no_branch_field_is_never_a_finding()
    test_edges_malformed_branch_fields_are_findings_naming_the_row_or_case()
    test_o3_the_pure_check_reads_nothing_and_changes_nothing()
    test_o4_findings_are_factory_owned_with_the_authors_door()
    test_o4_the_rehearsal_writes_nothing()
    test_e19_the_rehearsal_carries_the_stale_reason_of_a_moved_row()
    test_e9_a_legacy_story_is_never_a_finding_in_the_rehearsal()
    test_edge_an_unreadable_register_is_one_printed_line_and_no_finding()
    test_edge_the_then_list_is_the_one_s5_binds_and_a_missing_case_is_a_finding()
    test_o4_a_persons_word_at_s4_passes_the_block_and_is_not_asked_twice()
    test_sc1_1_invalid_variant_names_every_contract_error()
    test_sc1_1_a_bad_key_hides_nothing_else()
    test_sc1_1_a_key_outside_the_list_is_never_applied()
    test_sc1_1_message_head_unchanged()
    test_sc1_1_rounds_to_clean()
    test_sc1_1_a_head_word_still_passes()
    test_sc1_1_the_coverage_delta_trap_has_a_way_out_in_the_message()
    test_sc1_1_an_oracle_unknown_patch_names_the_row_side_way_out()
    test_sc1_1_the_revision_is_read_from_the_constant_never_a_literal()
    test_o3_the_register_ids_come_from_the_register_not_from_the_plan()
    test_f_cmp2_15_a_row_names_its_requirements_in_every_spelling_the_plan_uses()
    test_f14_a_row_that_rests_on_a_question_carries_a_branch_for_every_answer()
    test_k3_the_s3_exit_names_the_five_rows_and_the_one_branch_the_cmp2_plan_lacks()
    test_k3_the_six_cmp2_answers_move_ts_11_and_record_q1_to_q6()
    test_c1_the_decision_binds_the_patched_plan_because_the_call_stands_before_it()
    test_the_stand_card_rows_go_through_the_callers_own_manifest_put()
    test_edge_own_wording_two_answers_a_letter_beyond_and_q50_are_never_applied()
    test_edge_the_answers_file_is_created_or_appended()
    test_edge_manual_cards_and_blocked_cards_on_rows_that_are_not_run()
    test_c10_a_letter_branch_lands_its_obligations_and_the_plan_md_cell_is_rewritten()
    test_edge_no_plan_no_register_and_no_branch_say_one_thing_and_never_raise()
    test_t227b_role_text_doc_witness()
    test_o6_the_cmp2_prose_line_blocks_nothing_and_names_the_form()
    test_o6_only_a_whole_line_token_blocks_a_case()
    test_o7_the_remedy_comes_from_the_precondition_items_behind_the_card()
    test_t279_k_remedy_comes_from_the_unmet_items_only_and_says_when_it_cannot()
    test_t279_k_fence_a_blocked_token_in_a_code_block_is_said_once()
    test_o8_the_nothing_to_block_line_is_true_only_for_a_check_by_a_person()
    test_o9_every_md_column_a_changed_key_maps_to_is_rewritten()
    test_o10_a_letter_branch_settles_the_oracle_and_a_manual_branch_names_its_rung()
    test_o12_a_plan_created_on_or_after_the_cutoff_is_checked_with_no_branch_field()
    test_t261_k1_the_cmp2_rows_become_executable_and_the_controls_do_not()
    test_t261_the_pass_writes_before_the_decision_and_no_byte_changes_after_it()
    test_t261_error_direction_toward_not_executable()
    test_t261_the_policy_table_is_data_and_both_worlds_are_tested()
    test_t261_c2_an_unconfirmed_expectation_is_never_made_executable()
    test_t261_the_plan_date_reaches_the_branch_checks_and_the_readiness_file_is_read_through_the_layout()
    test_t721_one_record_passes_the_finding_wherever_it_was_recorded()
    test_d1a_k_a3_the_not_applied_label_says_which_cause()
    test_d1a_k_a6_every_row_that_rests_on_the_answer_is_moved_or_named()
    finish("question branches")


if __name__ == "__main__":
    main()
