"""TR2-9 (B-12): gate A reads the status of an open question from the question register, the one reader (AR-13).

Observed on the rehearsal of arm B: three questions the person had ANSWERED at S2 were shown at gate A as "cannot be answered as
it stands", because the shape check skipped a question only when its own dict carried `answer` / `answered` / `resolution`; an
answer recorded in the register (`work/question-answers.jsonl`) was invisible to it. These tests pin: a question settled in the
register is not listed; an open one is; a row changed since the answer is checked again; a register that cannot be read, or an
unknown status, never turns into a pass (FR-59) - the question is checked as it stands and a note names what could not be read.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import SCRIPTS, check, check_eq, cleanup, finish, use_project  # noqa: E402

sys.path.insert(0, str(SCRIPTS))

import gate_preflight  # noqa: E402
import question_register  # noqa: E402
import test_gate_preflight as T  # noqa: E402  (the story rig - imported, never copied)

BARE = {"id": "Q-1", "question": "Where must a removed node appear?"}      # no quote, no readings: refused as it stands


def rig(prefix: str, *rows):
    root = T.story(prefix)
    use_project(root)
    task_root = root / "qa-factory" / "artifacts" / "TP1-15045"
    (task_root / "work" / "requirements-readiness.json").write_text(json.dumps({"open_questions": list(rows)}), encoding="utf-8")
    return root, task_root


def rehearse(task_root):
    r = gate_preflight.Rehearsal(task_root, "A")
    r.check_open_questions()
    return r, [f for f in r.findings if f["check"] == "open_questions"]


def answer(task_root, qid="Q-1", status="not_needed", words="not needed, the ticket says so"):
    row = next(q for q in question_register.load(task_root)["questions"] if q["id"] == qid)
    question_register.record(task_root, qid, status, words, "S2 stop", "person", row["row_hash"])


def test_a_question_open_in_the_register_is_listed() -> None:
    """The control: with no record the bare question is refused as before (without it the next tests prove nothing)."""
    root, task_root = rig("qa-qstatus-open-", BARE)
    try:
        _r, found = rehearse(task_root)
        check("B-12 control: an open bare question -> one finding naming Q-1", len(found) == 1 and "Q-1" in found[0]["message"], str(found))
    finally:
        cleanup(root)


def test_a_question_answered_in_the_register_is_not_listed() -> None:
    """RED before the fix: the answer lives in the register, the shape check did not look there."""
    root, task_root = rig("qa-qstatus-answered-", BARE, dict(BARE, id="Q-2"))
    try:
        answer(task_root, "Q-1")
        _r, found = rehearse(task_root)
        check_eq("B-12 Q-1 settled in the register is not listed; Q-2, open, still is", [f["message"].split()[0] for f in found], ["Q-2"])
        answer(task_root, "Q-2", "answered", "Under the parent node, as the developer's comment says")
        _r, found = rehearse(task_root)
        check_eq("B-12 an `answered` record settles the second one as well: nothing is listed", found, [])
    finally:
        cleanup(root)


def test_a_row_changed_after_the_answer_is_checked_again() -> None:
    """The answer was given on other bytes: the register says it does not hold, so the question is asked as it stands (FR-7 is for
    the same text; a changed row is a new question)."""
    root, task_root = rig("qa-qstatus-changed-", BARE)
    try:
        answer(task_root, "Q-1")
        path = task_root / "work" / "requirements-readiness.json"
        path.write_text(json.dumps({"open_questions": [dict(BARE, question="Where must a moved node appear?")]}), encoding="utf-8")
        _r, found = rehearse(task_root)
        check("B-12 a row changed since the answer -> listed again", len(found) == 1 and "Q-1" in found[0]["message"], str(found))
    finally:
        cleanup(root)


def test_a_register_that_cannot_be_read_is_a_note_and_never_a_pass() -> None:
    """FR-59: the status could not be established -> the question is checked as it stands, and a note names what was not read."""
    root, task_root = rig("qa-qstatus-unreadable-", BARE)
    real = question_register.load
    try:
        answer(task_root, "Q-1")

        def broken(_root):
            raise OSError("disk gone")
        question_register.load = broken
        r, found = rehearse(task_root)
        check("B-12 an unreadable register -> the question is still listed", len(found) == 1, str(found))
        check("B-12 ... and a note says the status could not be read",
              any("could not be read from the question register" in i["message"] for i in r.info), str(r.info))
    finally:
        question_register.load = real
        cleanup(root)


def test_a_record_with_an_unknown_status_is_set_aside_with_a_note() -> None:
    """An answers line whose status the vocabulary does not know is counted as set aside by the register: the question stays open
    here, never settled by it, and the note names the count."""
    root, task_root = rig("qa-qstatus-unknown-", BARE)
    try:
        row = question_register.load(task_root)["questions"][0]
        line = {"kind": "question", "id": "Q-1", "status": "resolved-ish", "words": "yes", "by": "person",
                "where": "S2 stop", "at": "2026-11-06T10:00:00+00:00", "row_hash": row["row_hash"]}
        (task_root / "work" / "question-answers.jsonl").write_text(json.dumps(line) + "\n", encoding="utf-8")
        r, found = rehearse(task_root)
        check("B-12 an unknown status is no answer: the question is listed", len(found) == 1, str(found))
        check("B-12 ... and the note names the set-aside record",
              any("record(s) set aside" in i["message"] for i in r.info), str(r.info))
    finally:
        cleanup(root)


def test_a_question_absent_from_the_register_is_checked_as_it_stands() -> None:
    """An answer recorded for an id the register does not hold is not read as an answer of Q-1."""
    root, task_root = rig("qa-qstatus-absent-", BARE, dict(BARE, id="Q-2"))
    try:
        answer(task_root, "Q-2")
        _r, found = rehearse(task_root)
        check_eq("B-12 only the question with a record is skipped; Q-1 is listed", [f["message"].split()[0] for f in found], ["Q-1"])
    finally:
        cleanup(root)


def test_the_answer_inside_the_question_still_passes_it() -> None:
    """The earlier rule is kept: a non-empty `answer` in the question's own dict skips it, register or not."""
    root, task_root = rig("qa-qstatus-own-answer-", dict(BARE, answer="Under the parent"))
    try:
        _r, found = rehearse(task_root)
        check_eq("B-12 the own-dict answer still passes", found, [])
    finally:
        cleanup(root)


def test_only_the_first_row_of_an_id_takes_the_register_answer() -> None:
    """F1: the register keeps the first row of an id and its answer belongs to it; a later, different row of the same id
    is not answered by it and stays a finding. Two rows -> one finding; three rows -> two; a row answered in its own
    fields and in the register is skipped once."""
    other = dict(BARE, question="Where must a moved node appear?")
    root, task_root = rig("qa-qstatus-dup-", BARE, other)
    try:
        answer(task_root, "Q-1")
        _r, found = rehearse(task_root)
        check_eq("B-12 F1 two different rows Q-1, the answer is for the first: ONE finding, not zero", len(found), 1)
    finally:
        cleanup(root)
    third = dict(BARE, question="Where must a copied node appear?")
    root, task_root = rig("qa-qstatus-dup3-", BARE, other, third)
    try:
        answer(task_root, "Q-1")
        _r, found = rehearse(task_root)
        check_eq("B-12 F1 three rows of one id, the answer for the first: two findings", len(found), 2)
    finally:
        cleanup(root)
    root, task_root = rig("qa-qstatus-dup-own-", dict(BARE, answer="Under the parent"), other)
    try:
        answer(task_root, "Q-1")
        _r, found = rehearse(task_root)
        check_eq("B-12 F1 a row answered in its own fields keeps the first place: the second row is a finding", len(found), 1)
    finally:
        cleanup(root)


def test_both_readers_list_the_second_row_of_an_id_behind_an_answered_or_driver_owned_first() -> None:
    """F-1 (critic probe): row 1 of Q-1 is answered in its own fields (or is the conductor's), row 2 of Q-1 is a different
    unanswered question, the register settles Q-1 on row 1's bytes. Gate A names row 2; `still_open` LISTS row 2 (it used to
    vanish: the pre-filter made row 2 the "first" row of the id). Both readers agree."""
    import gate_brief
    other = dict(BARE, question="Where must a moved node appear?")
    variants = {"own-answered": dict(BARE, answer="Under the parent"),
                "driver-owned": dict(BARE, asked_by="S2 role")}
    for name, first in variants.items():
        root, task_root = rig(f"qa-qstatus-f1-{name}-", first, other)
        try:
            answer(task_root, "Q-1")
            _r, found = rehearse(task_root)
            check_eq(f"B-12 F-1 {name} first row: gate A names the second row", len(found), 1)
            view = question_register.load(task_root)
            listed = gate_brief.still_open([first, other], view, {}, task_root)
            check_eq(f"B-12 F-1 {name} first row: still_open lists the second row, with no register status",
                     [(i["question"], i.get("status")) for i in listed], [(other["question"], None)])
        finally:
            cleanup(root)


def test_still_open_keeps_its_other_outputs() -> None:
    """The edges that did NOT change: a non-dict row, a row with no id, an id absent from the register, a view that is None."""
    import gate_brief
    root = T.story("qa-qstatus-so-")
    use_project(root)
    task_root = root / "qa-factory" / "artifacts" / "TP1-15045"
    try:
        noid = {"question": "No id here?"}
        absent = {"id": "Q-9", "question": "Not in the register?"}
        rows = ["junk", None, noid, absent]
        got = gate_brief.still_open(rows, {"questions": [{"id": "Q-1", "status": "answered"}]}, {}, task_root)
        check_eq("B-12 still_open: non-dict rows dropped, no-id and absent-id rows listed as they stand", got, [noid, absent])
        got = gate_brief.still_open([absent], None, {}, task_root)
        check_eq("B-12 still_open: view None -> the row is listed as it stands", got, [absent])
        check_eq("B-12 still_open: rows not a list -> nothing", gate_brief.still_open(None, None, {}, task_root), [])
    finally:
        cleanup(root)


def test_row_answered_is_the_one_own_answer_test() -> None:
    check_eq("B-12 row_answered: answer / answered / resolution non-blank",
             [question_register.row_answered(r) for r in ({"answer": "x"}, {"answered": " y "}, {"resolution": "z"})], [True] * 3)
    check_eq("B-12 row_answered: blank, absent and non-dict are not answered",
             [question_register.row_answered(r) for r in ({"answer": "  "}, {"answer": None}, {}, "x", None)], [False] * 5)


def test_a_row_with_no_id_is_judged_by_its_own_fields() -> None:
    """A row with no id is never matched to the register: the bare one is a finding, the one with its own answer passes."""
    root, task_root = rig("qa-qstatus-noid-", {"question": "Where must a removed node appear?"})
    try:
        _r, found = rehearse(task_root)
        check_eq("B-12 a row with no id is checked as it stands", len(found), 1)
    finally:
        cleanup(root)


def test_matches_is_the_first_row_rule() -> None:
    """The shared helper itself: a view that is None or a register that holds nothing matches nothing."""
    rows = [{"id": "Q-1"}, {"id": " Q-1 "}, {"id": 7}, {}, "x"]
    view = {"questions": [{"id": "Q-1", "status": "answered"}]}
    got = question_register.matches(rows, view)
    check_eq("B-12 matches: the first Q-1 only", [bool(m) for m in got], [True, False, False, False, False])
    check_eq("B-12 matches: no view -> nothing", question_register.matches(rows, None), [None] * 5)


def main() -> None:
    test_a_question_open_in_the_register_is_listed()
    test_a_question_answered_in_the_register_is_not_listed()
    test_a_row_changed_after_the_answer_is_checked_again()
    test_a_register_that_cannot_be_read_is_a_note_and_never_a_pass()
    test_a_record_with_an_unknown_status_is_set_aside_with_a_note()
    test_a_question_absent_from_the_register_is_checked_as_it_stands()
    test_the_answer_inside_the_question_still_passes_it()
    test_only_the_first_row_of_an_id_takes_the_register_answer()
    test_both_readers_list_the_second_row_of_an_id_behind_an_answered_or_driver_owned_first()
    test_still_open_keeps_its_other_outputs()
    test_row_answered_is_the_one_own_answer_test()
    test_a_row_with_no_id_is_judged_by_its_own_fields()
    test_matches_is_the_first_row_rule()
    finish("gate A: question status from the register")


if __name__ == "__main__":
    main()
