"""HF4-7 (t-1479): an answer to a before/now question is tied to the Then's text by the reading's MEANING, not by letter.

Live run 12586, Q7: the case designer wrote `question_thens` for a question the code was still to raise, with `a` = "rejected
with 4xx" and `b` = "answers 2xx"; the code's fixed pair has `a` = "the behaviour now is expected". Gate A printed the 4xx text
under `a) Intended: the behaviour now is the expected one`, and the person's answer would have carried the wrong Then. Now a
before/now question's entry is keyed `now` / `before` and ONE reader (`contract.question_then_text`) turns the person's letter
into the key through the question itself (`contract.claim_reading_index`).

Fixture: `fixtures/run-12586-q7/` (README.txt names the sources). The stand's Q7 is raised by the code (no `claim` on its
readings, recognised by the equality with `claim_readings`), Q5 was written by the role at S2 (no `claim`, not recognised).

K7 (the words `now`, `before`, `claim` in the role texts) is rows of design/role-rules.json.
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import (  # noqa: E402
    SCRIPTS, check, check_eq, check_in, check_not_in, cleanup, finish, run_script, temp_dir, temp_project, use_project,
)

sys.path.insert(0, str(SCRIPTS))

import contract as C  # noqa: E402
import gate_brief as GB  # noqa: E402
import gate_preflight  # noqa: E402
import planning_contract as PC  # noqa: E402
import question_register as QR  # noqa: E402

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "run-12586-q7"
READINESS = (FIXTURE / "requirements-readiness.json").read_text(encoding="utf-8")
CASE_RAISE_LETTERS = (FIXTURE / "TC-014-raise-letters.md").read_text(encoding="utf-8")
CASE_GATE_A_LETTERS = (FIXTURE / "TC-014-gate-a-letters.md").read_text(encoding="utf-8")
CASE_MEANING = (FIXTURE / "TC-014-raise-meaning.md").read_text(encoding="utf-8")
RECORDED_CARD = (FIXTURE / "gate-a-brief-q7-card.txt").read_text(encoding="utf-8")

NOW_TEXT = "If a user-scope move needs no target permission: the PUT answers 2xx and the integration is in the target"
BEFORE_TEXT = "If U has no admin role on the target: the PUT is rejected with 4xx and the integration stays in its origin"
UNMARKED = "the question does not mark which reading is the behaviour now"


def stand_questions(*, drop=()) -> dict:
    """{id: the register's question, as `question_register.load` returns it} of the stand's readiness file."""
    root = temp_dir("qa-claim-keys-register-")
    try:
        data = json.loads(READINESS)
        data["open_questions"] = [q for q in data["open_questions"] if q["id"] not in drop]
        (root / "work").mkdir()
        (root / "work" / "requirements-readiness.json").write_text(json.dumps(data), encoding="utf-8")
        return {q["id"]: q for q in QR.load(root)["questions"]}
    finally:
        cleanup(root)


def entry_of(case_text: str) -> dict:
    return C.question_thens_from_text(case_text)[0][0]


def case_for_variants(case_text: str, cid: str = "TC-014") -> dict:
    return {"case": cid, "readable": True, "question_thens": C.front_line(case_text, "question_thens"), "thens": [1, 2, 3]}


def answered(question: dict, letter: str, **more) -> dict:
    return dict(question, status="answered", reading=letter, changed_since_answer=False, **more)


def kinds(found: list) -> list:
    return [(f["kind"], f["owner"], f["where"], f["question"]) for f in found]


def test_k1_the_seam_through_the_s4_exit_to_the_card() -> None:
    """K1 (N7-4): the S4 exit raises Q7 from the by-meaning TC-014 (the form the role does not write yet - the README says so),
    and the card prints the 2xx text under a) Intended-now and the 4xx text under b) - the swap of run 12586, reversed."""
    import case_versions as V
    project = temp_project("qa-claim-keys-seam-")
    try:
        use_project(project)
        task = project / "qa-factory" / "artifacts" / "TP1-12586"
        (task / "work").mkdir(parents=True)
        data = json.loads(READINESS)
        data["open_questions"] = [q for q in data["open_questions"] if q["id"] != "Q7"]   # the register BEFORE the S4 exit raised it
        (task / "work" / "requirements-readiness.json").write_text(json.dumps(data), encoding="utf-8")
        source = task / "work" / "test-cases" / "integrations" / "TC-014.md"
        source.parent.mkdir(parents=True)
        source.write_text(CASE_MEANING, encoding="utf-8", newline="\n")
        V.pin(task, V.create_version(task / "work" / "test-cases", source))
        proc = run_script("critic_rollcall.py", "--apply-fixes", "--task-root", task, env=dict(os.environ, CLAUDE_PROJECT_DIR=str(project)))
        payload = json.loads(proc.stdout)
        check_eq("K1: the real S4 exit raised the question for (TC-014, Then 1), nothing skipped",
                 (payload.get("raised"), payload.get("skipped"), proc.returncode), ([{"case": "TC-014", "then": 1, "question": "Q7"}], [], 0))
        questions = {q["id"]: q for q in QR.load(task)["questions"]}
        q7 = questions["Q7"]
        check_eq("K1: the code wrote the meaning on each reading of the question it raised",
                 [r.get("claim") for r in q7["readings"]], ["now", "before"])
        check_eq("K1: the case on disk was rewritten to the new id, its keys untouched",
                 sorted(entry_of(source.read_text(encoding="utf-8"))["readings"]), ["before", "now"])
        effects, problems = GB.question_effects(task, [], list(questions.values()))
        check_eq("K1: the case store was read whole", problems, [])
        card = GB.question_card(q7, 1, effects)
        at_a = next(i for i, line in enumerate(card) if line.startswith("  - a) "))
        at_b = next(i for i, line in enumerate(card) if line.startswith("  - b) "))
        under_a, under_b = "\n".join(card[at_a:at_b]), "\n".join(card[at_b:])
        check_in("K1: under a) Intended-now stands the 2xx text", f'would read: "{NOW_TEXT}"', under_a)
        check_not_in("K1: ... and not the 4xx text", BEFORE_TEXT, under_a)
        check_in("K1: under b) the regression stands the 4xx text", f'would read: "{BEFORE_TEXT}"', under_b)
        check_not_in("K1: ... and not the 2xx text", NOW_TEXT, under_b)
        check_in("K1 control: the recorded card of the run shows the swap this fixes (4xx under a)",
                 "Intended: the behaviour now is the expected one", RECORDED_CARD)
        recorded_a = RECORDED_CARD.split("b) A regression")[0]
        check_in("K1 control: ... the 4xx text under a) in the recorded card", "rejected with 4xx", recorded_a)
        # the resolver and the late-answer applier read the same entry, the same way (FR-10)
        entry = entry_of(source.read_text(encoding="utf-8"))
        oracle = {"then": 1, "source": "unknown", "ref": "Q7"}
        got = C.resolve_then_oracle(oracle, answered(q7, "a"), entry)
        check_eq("K1/K3: answered a - the Then's expected value is the `now` text", (got["state"], got["expected"]), ("settled", NOW_TEXT))
        check_eq("K1: the applier's door agrees", PC.case_entry_answers(entry, "a", answered(q7, "a")), True)
    finally:
        cleanup(project)


def test_k2_the_letters_of_the_run_are_refused_with_a_door() -> None:
    """K2: the gate-A version (letters on Q7, Q7 open) is a finding of the case designer, named by case, Then and question;
    the `raise` version with letters is a FORM error at the write (N7-1); the by-meaning version passes both."""
    q7 = stand_questions()["Q7"]
    found = PC.variant_errors([], [q7], [case_for_variants(CASE_GATE_A_LETTERS)], plan_created="2026-10-28")
    check_eq("K2: one finding, the designer's, on TC-014 / Q7", kinds(found), [("bad_branch", "designer", "TC-014", "Q7")])
    message = found[0]["message"]
    check_in("K2: it names the case, the Then and the question", "TC-014: Then 1 asks Q7", message)
    check_in("K2: it says what is wrong", "letters on a before/now question: the reading order is fixed by the factory, not by the case", message)
    check_in("K2: it says what is expected (the two keys)", "`now`", message)
    check_in("K2: ... and `before`", "`before`", message)
    check_in("K2: the door is the designer's rework", "rework", message)
    check_eq("K2 control: the by-meaning version on the same open Q7 is no finding",
             PC.variant_errors([], [q7], [case_for_variants(CASE_MEANING.replace('"question": "raise"', '"question": "Q7"'))],
                               plan_created="2026-10-28"), [])

    def form_errors(case_text: str) -> list:
        return C.then_oracle_errors("TC-014.md", C.front_line(case_text, "then_oracles"), C.front_line(case_text, "question_thens"),
                                    [1, 2, 3], raw_raise_questions=C.front_line(case_text, "raise_questions"))
    got = form_errors(CASE_RAISE_LETTERS)
    check_eq("K2/N7-1: the `raise` version with letters is ONE FORM error", len(got), 1)
    check_in("K2/N7-1: ... of the write, naming the keys the line must use", "keyed `now` and `before`", got[0])
    check_in("K2/N7-1: ... and the letters it found", "`a`, `b`", got[0])
    check_eq("K2/N7-1 control: the by-meaning `raise` version is clean", form_errors(CASE_MEANING), [])


def test_k3_the_resolver_reads_the_meaning() -> None:
    q = stand_questions()
    oracle = {"then": 1, "source": "unknown", "ref": "Q7"}
    entry = entry_of(CASE_MEANING)
    got = C.resolve_then_oracle(oracle, answered(q["Q7"], "a"), entry)
    check_eq("K3: Q7 (the code's pair, no `claim` on the stand) answered a - expected is the `now` text",
             (got["source"], got["state"], got["expected"], got["reading"]), ("person", "settled", NOW_TEXT, "a"))
    got = C.resolve_then_oracle(oracle, answered(q["Q7"], "b"), entry)
    check_eq("K3: answered b with a `before` nobody knows - open, the person's value is needed (O2, unchanged)",
             (got["state"], got["expected"]), ("open", None))
    marked = dict(q["Q7"], readings=[dict(r, claim=k) for r, k in zip(reversed(q["Q7"]["readings"]), C.CLAIM_KEYS[::-1])])
    check_eq("K3 (letters differ from positions): readings listed before-first carry `claim`; letter a is then `before`",
             C.question_then_text(marked, entry, "a"), (BEFORE_TEXT, ""))
    check_eq("K3: ... and letter b is `now`", C.question_then_text(marked, entry, "b"), (NOW_TEXT, ""))
    got = C.resolve_then_oracle(oracle, answered(marked, "b"), entry)
    check_eq("K3: the resolver follows the claim, not the position - b is `now` here", (got["state"], got["expected"]), ("settled", NOW_TEXT))


def test_k4_an_ordinary_question_keeps_its_letters() -> None:
    q1 = stand_questions()["Q1"]
    entry = {"question": "Q1", "then": 1, "readings": {"a": "HTTP 200", "b": "HTTP 400"}, "not_needed": ""}
    check_eq("K4: Q1 letter a", C.question_then_text(q1, entry, "a"), ("HTTP 200", ""))
    check_eq("K4: Q1 letter b", C.question_then_text(q1, entry, "b"), ("HTTP 400", ""))
    check_eq("K4: Q1 not_needed", C.question_then_text(q1, entry, "not_needed"), ("", ""))
    check_eq("K4: the keys of Q1 are its letters", C.question_then_keys(q1), ["a", "b"])
    check_eq("K4: the applier's door reads Q1 by letter", PC.case_entry_answers(entry, "b", answered(q1, "b")), True)
    check_eq("K4: no variant finding on Q1 for a lettered entry",
             PC.variant_errors([], [q1], [{"case": "TC-1", "readable": True, "question_thens": json.dumps([entry]), "thens": [1]}],
                               plan_created="2026-10-28"), [])
    mirrored = dict(entry, readings={"now": "x", "before": "y"})
    found = PC.variant_errors([], [q1], [{"case": "TC-1", "readable": True, "question_thens": json.dumps([mirrored]), "thens": [1]}],
                              plan_created="2026-10-28")
    check_eq("K4/p.6 mirror: `now` / `before` on an ordinary question is the same finding", kinds(found), [("bad_branch", "designer", "TC-1", "Q1")])
    check_in("K4/p.6 mirror: ... says the question is lettered", "does not mark which reading is the behaviour now", found[0]["message"])


def test_k5_awkward_inputs_stay_on_the_safe_side() -> None:
    q = stand_questions()
    q7, q5 = q["Q7"], q["Q5"]
    check_eq("K5: Q5 (written by the role, no `claim`) - no meaning for either word",
             (C.claim_reading_index(q5, "now"), C.claim_reading_index(q5, "before")), (None, None))
    check_eq("K5: Q5's text is 'no text' with the reason, not a guess",
             C.question_then_text(q5, entry_of(CASE_MEANING), "a"), (None, UNMARKED))

    def with_claims(question, *claims):
        return dict(question, readings=[dict(r, claim=c) if c is not None else dict(r) for r, c in zip(question["readings"], claims)])
    for label, question in (("an unknown claim word", with_claims(q7, "later", "before")),
                            ("two readings with one claim", with_claims(q7, "now", "now")),
                            ("a claim on one reading only", with_claims(q7, "now", None)),
                            ("a claim in another case", with_claims(q7, "Now", "Before")),
                            ("three readings", dict(q7, readings=q7["readings"] + [dict(q7["readings"][0], claim="now")])),
                            ("a claim that is no string", with_claims(q7, ["now"], "before"))):
        check_eq(f"K5: {label} - no meaning, no text",
                 (C.claim_reading_index(question, "now"), C.question_then_text(question, entry_of(CASE_MEANING), "a")[0]), (None, None))
    first = q7["readings"][0]["reading"]
    for label, question in (("a pair differing by a space", dict(q7, readings=[dict(q7["readings"][0], reading=first + " "), q7["readings"][1]])),
                            ("a pair differing by one byte", dict(q7, readings=[dict(q7["readings"][0], reading=first[:-1]), q7["readings"][1]])),
                            ("another before.value", dict(q7, before=dict(q7["before"], value="400")))):
        check_eq(f"K5: {label} is not the code's pair (case iii)", C.claim_reading_index(question, "now"), None)
    check_eq("K5: a letter past the readings has no text", C.question_then_text(q7, entry_of(CASE_MEANING), "c")[0], None)
    check_eq("K5: a key in another case is no key (`Now`) - open question, no text",
             C.question_then_text(q7, {"readings": {"Now": "x", "Before": "y"}}, "a")[0], None)
    check_eq("K5: no readings object at all - no text", C.question_then_text(q7, {"readings": None}, "a")[0], None)
    check_eq("K5: an entry that is no object - no text", C.question_then_text(q7, "x", "a")[0], None)
    check_eq("K5: an empty text is a text", C.question_then_text(q7, {"readings": {"now": "", "before": "y"}}, "a"), ("", ""))
    check_eq("K5: both kinds in one entry on an open question - the finding of p.6",
             len(PC._claim_key_errors({"readings": {"a": "x", "now": "y"}}, q7)), 1)
    check_in("K5: ... naming the mix", "not mixed with `now`", PC._claim_key_errors({"readings": {"a": "x", "now": "y"}}, q7)[0])


def test_k6_legacy_a_world_before_the_update() -> None:
    q7 = stand_questions()["Q7"]
    letters_entry = entry_of(CASE_GATE_A_LETTERS)
    # (a) the question is OPEN, the case has letters: no text under a letter it was not written for
    effect = GB._then_effect({"id": "TC-014", "title": "t", "then_numbers": [1, 2, 3]}, letters_entry, "a", q7)
    check_eq("K6a: the card puts no text under the letter", effect["text"], None)
    line = GB.render_effect(effect)
    check_in("K6a: it says so", "no text is written for this answer", line)
    check_in("K6a: ... with the reason and the case's texts, tied to no reading", "tied to no reading", line)
    check_in("K6a: ... the designer's texts are shown unbound", "rejected with 4xx", line)
    found = PC.variant_errors([], [q7], [case_for_variants(CASE_GATE_A_LETTERS)], plan_created="2026-10-28")
    check_eq("K6a: the rehearsal names it before the person sees the question", [f["kind"] for f in found], ["bad_branch"])
    # (b) answered BY LETTER a before the update, the case keeps letters: read by letter, as shown (B7-2)
    q7a = answered(q7, "a")
    oracle = {"then": 1, "source": "unknown", "ref": "Q7"}
    got = C.resolve_then_oracle(oracle, q7a, letters_entry)
    check_eq("K6b: the resolver reads the letter the person chose on the card they saw",
             (got["state"], got["expected"]), ("settled", letters_entry["readings"]["a"]))
    check_eq("K6b: the applier's door says resolved - the two readers agree (FR-10)", PC.case_entry_answers(letters_entry, "a", q7a), True)
    check_eq("K6b: no finding for an answered question of the legacy world",
             PC.variant_errors([], [q7a], [case_for_variants(CASE_GATE_A_LETTERS)], plan_created="2026-10-28"), [])
    check_eq("K6b: the late-answer rework asks nothing of this case",
             PC._case_rework({"TC-014": {"thens": [letters_entry]}}, q7a, "a", "Q7: a", "2026-10-28"), [])
    check_eq("K6b control: another letter (b) was not the one chosen - the entry's text for it is not read",
             C.question_then_text(q7a, letters_entry, "b")[0], None)
    # (c) answered in the person's own words: nothing changes
    words = answered(q7, "")
    check_eq("K6c: own words - the Then stays unknown", C.resolve_then_oracle(oracle, words, letters_entry)["state"], "open")
    check_eq("K6c: ... and the branch finding is the existing `settled_question`, not the new one",
             [f["kind"] for f in PC.variant_errors([], [words], [case_for_variants(CASE_GATE_A_LETTERS)], plan_created="2026-10-28")],
             ["settled_question"])


def test_k8_one_reader_for_the_resolver_the_card_and_the_applier() -> None:
    q7 = stand_questions()["Q7"]
    meaning = CASE_MEANING.replace('"question": "raise"', '"question": "Q7"')
    case = case_for_variants(meaning)
    q7a = answered(q7, "a")
    check_eq("K8: Q7 in the new form, answered a - no finding", PC.variant_errors([], [q7a], [case], plan_created="2026-10-28"), [])
    check_eq("K8: ... and no rework", PC._case_rework({"TC-014": {"thens": [entry_of(meaning)]}}, q7a, "a", "Q7: a", "2026-10-28"), [])
    found = PC.variant_errors([], [q7], [case], plan_created="2026-10-28")
    check_eq("K8: the OPEN Q7 in the new form - neither `missing_reading_text` nor `bad_branch`", [f["kind"] for f in found], [])
    check_eq("K8: the keys the branch check wants are the meanings", C.question_then_keys(q7), ["now", "before"])
    check_eq("K8: ... and for the ref `raise`", C.question_then_keys("raise"), ["now", "before"])
    gone = json.dumps([dict(entry_of(meaning), question="Q7", readings={"now": NOW_TEXT})])
    found = PC.variant_errors([], [q7], [{"case": "TC-014", "readable": True, "question_thens": gone, "thens": [1]}], plan_created="2026-10-28")
    check_eq("K8: a missing `before` text IS `missing_reading_text`, said for `before`",
             [(f["kind"], "before" in f["message"]) for f in found], [("missing_reading_text", True)])


def test_k9_a_question_the_role_wrote_without_claim() -> None:
    """The rehearsal of gate A names the tester's finding ONLY when a case keys its texts by meaning on that question."""
    import case_versions as V
    q = stand_questions()
    check_eq("K9: Q7 (the code's) is recognised by the equality of its pair: now = position 0",
             (C.claim_reading_index(q["Q7"], "now"), C.claim_reading_index(q["Q7"], "before")), (0, 1))
    check_eq("K9: Q5 has a mark problem, Q7 and Q1 do not", [bool(C.claim_mark_problem(q[i])) for i in ("Q5", "Q7", "Q1")], [True, False, False])
    project = temp_project("qa-claim-keys-q5-")
    try:
        use_project(project)
        task = project / "qa-factory" / "artifacts" / "TP1-12586"
        (task / "work").mkdir(parents=True)
        (task / "work" / "requirements-readiness.json").write_text(READINESS, encoding="utf-8")
        rehearsal = gate_preflight.Rehearsal(task, "A")
        rehearsal.check_open_questions()
        check_eq("K9: Q5 with NO case keyed by meaning on it - no finding", rehearsal.findings, [])
        case_text = CASE_MEANING.replace('"question": "raise"', '"question": "Q5"')
        source = task / "work" / "test-cases" / "integrations" / "TC-014.md"
        source.parent.mkdir(parents=True)
        source.write_text(case_text, encoding="utf-8", newline="\n")
        V.pin(task, V.create_version(task / "work" / "test-cases", source))
        rehearsal = gate_preflight.Rehearsal(task, "A")
        rehearsal.check_open_questions()
        check_eq("K9: a case keyed `now` / `before` on Q5 - ONE finding", len(rehearsal.findings), 1)
        finding = rehearsal.findings[0]
        check_in("K9: ... of Q5, to the requirements tester", "Q5 cannot be answered as it stands", finding["message"])
        check_in("K9: ... saying what to add", "claim: now|before", finding["message"])
        check_in("K9: ... and whom it goes back to", "qa-requirements-tester", finding["message"])
        check_eq("K9: the finding is the factory's, never the person's", finding["class"], gate_preflight.FACTORY_FIXABLE)
    finally:
        cleanup(project)


def test_k10_the_neighbours_that_read_a_letter_as_a_meaning() -> None:
    """N7-2: `claim_confirmed`, `before_value_needed` and the O2 branch ask the QUESTION which letter is which."""
    q = stand_questions()
    q7, q5 = q["Q7"], q["Q5"]
    check("K10: Q7 (the code's pair) answered a confirms the claim", C.claim_confirmed(answered(q7, "a")))
    check("K10: Q7 answered b does not", not C.claim_confirmed(answered(q7, "b")))
    check("K10: Q5 (unmarked) answered a confirms nothing - the safe side", not C.claim_confirmed(answered(q5, "a")))
    reordered = dict(q7, readings=[dict(r, claim=k) for r, k in zip(reversed(q7["readings"]), reversed(C.CLAIM_KEYS))])
    check("K10: readings listed before-first, marked: letter b is the behaviour now", C.claim_confirmed(answered(reordered, "b")))
    check("K10: ... and letter a is not", not C.claim_confirmed(answered(reordered, "a")))
    blank = dict(q5, before=dict(q5["before"], value="unknown"))
    check("K10: Q5 with an unknown before, answered a - the value is needed (cannot tell it was not the regression)",
          C.before_value_needed(answered(blank, "a")))
    check("K10: Q7 (unknown before) answered b - needed", C.before_value_needed(answered(q7, "b")))
    check("K10: Q7 answered a - not needed (it is the behaviour now)", not C.before_value_needed(answered(q7, "a")))
    check("K10: Q5 with a KNOWN before - nothing is needed", not C.before_value_needed(answered(q5, "b")))
    oracle = {"then": 1, "source": "unknown", "ref": "Q5"}
    for letter in ("a", "b"):
        got = C.resolve_then_oracle(oracle, answered(q5, letter), entry_of(CASE_MEANING))
        check_eq(f"K10/O2: Q5 answered {letter}, the case keyed by meaning - open, with the reason",
                 (got["state"], got["expected"], UNMARKED in got["why"]), ("open", None, True))
    known = dict(reordered, before=dict(reordered["before"], value="400"))
    got = C.resolve_then_oracle(oracle, answered(known, "a"), entry_of(CASE_MEANING))
    check_eq("K10/O2: marked readings, letter a is `before` - the person's value is the question's `before`",
             (got["state"], got["expected"]), ("settled", "400"))
    got = C.resolve_then_oracle(oracle, answered(known, "b"), entry_of(CASE_MEANING))
    check_eq("K10/O2 control: ... and letter b (`now`) is the case's `now` text", (got["state"], got["expected"]), ("settled", NOW_TEXT))


def test_k11_the_critic_fixes_of_t_1493() -> None:
    qs = stand_questions()
    q7, q5 = qs["Q7"], qs["Q5"]
    # F1: a letter answer recorded but not `settled` (b with `before` unknown) gives no NEW finding - clean on 2b99d50f, clean now
    q7b = answered(dict(q7, before={"value": "unknown"}), "b")
    check_eq("K6d/F1: the premise - answered b, before unknown: needs a value, so not settled", (QR.settled(q7b), C.before_value_needed(q7b)), (False, True))
    check_eq("K6d/F1: no finding for the legacy letter entry", PC.variant_errors([], [q7b], [case_for_variants(CASE_GATE_A_LETTERS)], plan_created="2026-10-28"), [])
    # F2: an unmarked question answered a with `before` unknown - the note never says "before" for the person's choice
    q5a = answered(dict(q5, before={"value": "unknown"}), "a")
    note = GB.question_note(q5a)
    check_in("K11/F2: the note prints the letter's own reading text", " ".join(str(q5["readings"][0]["reading"]).split()), note)
    check_not_in("K11/F2: ... and does not claim the choice was the behaviour before", "you chose the behaviour before", note)
    # F4: one letters helper, one key, one alphabet
    check("K11/F4: planning_contract reads the letters and the key from contract", PC.NOT_NEEDED is C.NOT_NEEDED_KEY and PC._letters(q5) == C.reading_letters(q5))
    # F5: a letter past the readings of a marked question names the real cause
    reason = C.question_then_text(q7, entry_of(CASE_MEANING), "c")[1]
    check_not_in("K11/F5: not the 'not marked' cause", UNMARKED, reason)
    check_in("K11/F5: ... the letter has no meaning", "reading c has no meaning here", reason)
    # F6: a question that only SHOWS before/now is no before/now question for the keys; the rehearsal still names it
    check_eq("K11/F6: Q5 (shows before/now, no claim) is lettered, Q7 is by meaning", (C.is_claim_question(q5), C.is_claim_question(q7)), (False, True))


if __name__ == "__main__":
    test_k1_the_seam_through_the_s4_exit_to_the_card()
    test_k2_the_letters_of_the_run_are_refused_with_a_door()
    test_k3_the_resolver_reads_the_meaning()
    test_k4_an_ordinary_question_keeps_its_letters()
    test_k5_awkward_inputs_stay_on_the_safe_side()
    test_k6_legacy_a_world_before_the_update()
    test_k8_one_reader_for_the_resolver_the_card_and_the_applier()
    test_k9_a_question_the_role_wrote_without_claim()
    test_k10_the_neighbours_that_read_a_letter_as_a_meaning()
    test_k11_the_critic_fixes_of_t_1493()
    finish("question thens claim keys")
