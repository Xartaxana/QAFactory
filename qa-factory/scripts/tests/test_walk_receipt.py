"""test_walk_receipt.py - the walk receipt in the bug's step (spec t-1991, node U2).

Run: python -B -m pytest -p no:cacheprovider scripts/tests/test_walk_receipt.py -q      or      python -B scripts/tests/test_walk_receipt.py

A draft whose `reproduction` holds `{kind: walk, evidence: evidence/place-answer-<id>.json}` is lifted to `reproduced_by_factory` only when
the record stands NOW (`place_answers.answer_problems` == []), is of THIS draft and its place, and the draft-wide facts hold per entry kind
(`bug_records.reproduction_problems`). Every error goes DOWN: a doubtful record leaves the draft `unconfirmed`.
Mutation -> killing test (named, run once in the node's report):
  the APP_BUG fact skipped for every walk entry (not only a code-reading draft) -> test_walk_on_no_defect_observation_void
"""
import json
import re
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import bug_records as BR  # noqa: E402
import contract as C  # noqa: E402
import place_answers as PA  # noqa: E402
import test_place_answers as TP  # noqa: E402  (its fixtures: a story with a register, drafts, captures the way the recorder writes them)

PLACE = "req-R-1"
DRAFT = "d.json"
QUOTE = "The total is shown with two decimals."
FRESH = {"kind": "fresh_data_rerun", "evidence": "evidence/rerun.log", "attempt_id": "a2", "observed": "again"}


def entry() -> dict:
    return {"kind": "walk", "evidence": PA.record_rel(PLACE), "observed": "Total: 10.5 EUR"}


def _json(task: Path, rel: str, data) -> None:
    path = task / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def world(shape: str = "result", *, verdict: str = "APP_BUG", status: str = "failed", walk: bool = True, extra=None) -> Path:
    """A story with one draft `d.json` of the place `req-R-1` (the register row R-1 contradicts F-1), its triage row and run report
    for the shape (`result` | `manual` | `observation` | `code`), and, when `walk`, the record `place_answers.write` keeps."""
    task = TP.story()
    over = {"reproduction": [entry()]}
    if shape == "code":
        over.update(evidence="code-reading", violates="requirement:R-1", oracle={"requirement": "R-1", "quote": QUOTE},
                    fact={"id": "F-1", "path": "app.py", "line": 10}, check_state="not_executed",
                    red_test_none="no factory test spoke: read from the code", created="2026-11-05")
        for gone in ("case", "triage_ref"):
            over[gone] = None
        _json(task, "work/context-bundle.json", {"facts": [{"id": "F-1", "path": "app.py", "line": 10}]})
    else:
        ref = {"result": "TC-1", "manual": "TC-1", "observation": "TC-1#obs1"}[shape]
        over["triage_ref"] = f"{ref}@a1"
        _json(task, "work/triage.json", {"triage": [{"instance_id": ref, "attempt_id": "a1", "case": "TC-1", "verdict": verdict}]})
        if shape == "result":
            _json(task, "work/run-report.json", {"current_results": [{"instance_id": "TC-1", "attempt_id": "a1", "status": status}],
                                                 "results": [{"instance_id": "TC-1", "attempt_id": "a1", "status": status}]})
        else:
            check = {"case": "TC-1", "attempt_id": "a1", "result": "inconclusive" if shape == "manual" else "pass"}
            if shape == "observation":
                check["observations"] = [{"text": "the total looks off"}]
            _json(task, "work/run-report.json", {"current_results": [], "current_manual_checks": [check]})
    over.update(extra or {})
    TP.draft(task, DRAFT, **over)
    if walk:
        TP.write(task, TP.ans(PLACE, "bug", task, source="requirement", draft=DRAFT, expectation=TP.req("R-1", QUOTE)))
    return task


def step(task: Path) -> tuple:
    draft = json.loads((task / "work" / "bug-drafts" / DRAFT).read_text(encoding="utf-8"))
    return BR.confirmation_of(task, draft)


def lifted(task: Path) -> bool:
    word, kinds, problems = step(task)
    return word == BR.REPRODUCED and kinds == ["walk"] and problems == []


def void(task: Path, code: str) -> None:
    word, kinds, problems = step(task)
    assert (word, kinds) == ("unconfirmed", []) and code in problems, (word, kinds, problems)


def record_path(task: Path) -> Path:
    return task / PA.record_rel(PLACE)


def edit_record(task: Path, **changes) -> None:
    data = json.loads(record_path(task).read_text(encoding="utf-8"))
    data.update(changes)
    record_path(task).write_text(json.dumps(data), encoding="utf-8")


# --- the walk lifts the three drafts that have no run of their own ----------------------------------------------------------------

def test_code_reading_draft_lifted_by_walk():
    assert lifted(world("code"))


def test_manual_check_draft_lifted_by_walk():
    assert lifted(world("manual"))


def test_observation_draft_lifted_by_walk():
    assert lifted(world("observation"))


def test_register_place_bug_has_a_draft_form():
    task = world("code")
    draft = json.loads((task / "work" / "bug-drafts" / DRAFT).read_text(encoding="utf-8"))
    assert draft["check_state"] == "not_executed" and BR.is_code_reading(draft)
    found = BR.code_reading_problems(task, draft, drafts=[(DRAFT, draft)])       # the draft is found among them by identity
    assert found == [], found
    assert lifted(task)


# --- TR1-11 / F13: two drafts of one place are raised by one answer -----------------------------------------------------------------

def second_draft(task: Path, name: str = "e.json", **over) -> None:
    body = {"reproduction": [entry()]}
    body.update(over)
    TP.draft(task, name, **body)


def step_of(task: Path, name: str) -> tuple:
    return BR.confirmation_of(task, json.loads((task / "work" / "bug-drafts" / name).read_text(encoding="utf-8")))


def test_two_drafts_of_one_place_lifted_by_one_answer():
    task = world("manual")                                                 # the answer names d.json
    second_draft(task, "e.json", title="Total drops the cents on the summary page")      # a second, different draft of the SAME place req-R-1
    assert lifted(task)
    word, kinds, problems = step_of(task, "e.json")
    assert (word, kinds, problems) == (BR.REPRODUCED, ["walk"], []), (word, kinds, problems)


def test_second_draft_of_another_place_not_lifted_by_the_answer():
    task = world("manual")
    _json(task, "work/triage.json", {"triage": [{"instance_id": i, "attempt_id": "a1", "case": i, "verdict": "APP_BUG"} for i in ("TC-1", "TC-2")]})
    _json(task, "work/run-report.json", {"current_results": [], "current_manual_checks": [
        {"case": i, "attempt_id": "a1", "result": "inconclusive"} for i in ("TC-1", "TC-2")]})        # f.json passes every check but the place
    second_draft(task, "f.json", violates="R-2", case="TC-2", triage_ref="TC-2@a1")      # another place: its own answer is needed
    word, kinds, problems = step_of(task, "f.json")
    assert (word, kinds) == ("unconfirmed", []) and BR.R_WALK_PLACE in problems, (word, kinds, problems)


def test_a_bug_answer_does_not_settle_a_place_with_an_unconfirmed_sibling():
    task = world("manual")
    TP.draft(task, "e.json", title="Another defect of R-1")                  # the same place, no `walk` entry: it stays unconfirmed
    assert step_of(task, "e.json")[0] == "unconfirmed" and PA.place_of_draft(task, "e.json", {"violates": "R-1", "case": "TC-1"}) == PLACE
    _record, state, why = PA.settled_answer(task, PLACE)
    assert state == "carrier missing" and "e.json" in why and PA.record_rel(PLACE) in why, (state, why)


def test_a_bug_answer_settles_a_place_when_every_draft_carries_the_receipt():
    task = world("manual")
    second_draft(task, "e.json", title="Another defect of R-1")              # the entry in the sibling too
    assert PA.settled_answer(task, PLACE)[1] == "settled"


def test_answer_naming_a_draft_of_another_place_lifts_nothing():
    task = world("manual")
    TP.draft(task, "other.json", violates="R-2", case="TC-2", triage_ref="TC-2@a1")      # exists, belongs to req-R-2
    edit_record(task, draft="other.json")
    void(task, BR.R_WALK_PLACE)


# --- everything that must stay unconfirmed (the error goes down) ------------------------------------------------------------------

def test_walk_on_no_defect_observation_void():
    # the draft's own triage row says NO_DEFECT: a triage-road draft keeps the APP_BUG fact whatever the walk says
    task = world("observation", verdict="NO_DEFECT")
    void(task, BR.R_NO_TRIAGE)
    void(world("manual", verdict="NO_DEFECT"), BR.R_NO_TRIAGE)


def test_hand_written_record_source_none_void():
    task = world("manual")
    record = TP.ans(PLACE, "bug", task, draft=DRAFT)                      # expectation.source none: a bug needs a source
    record.update(writer="place_answers.py", dispatch=TP.DISPATCH)
    record_path(task).write_text(json.dumps(record), encoding="utf-8")
    void(task, BR.R_WALK_ANSWER)


def test_record_capture_not_in_index_void():
    task = world("manual")
    folder = task / "work" / "evidence" / "manual" / f"settle-{PLACE}" / "a1"
    (folder / "handmade.txt").write_text("Total: 10.5 EUR", encoding="utf-8")            # no row in captures.jsonl
    seen = {"quote": "Total: 10.5", "capture": (folder / "handmade.txt").relative_to(task).as_posix()}
    edit_record(task, seen=seen)
    void(task, BR.R_WALK_ANSWER)


def test_walk_capture_changed_void():
    task = world("manual")
    record = json.loads(record_path(task).read_text(encoding="utf-8"))
    (task / record["seen"]["capture"]).write_text("Total: 10.5 EUR - edited", encoding="utf-8")
    void(task, BR.R_WALK_ANSWER)


def test_walk_of_other_draft_void():
    task = world("manual")
    edit_record(task, draft="other.json")
    void(task, BR.R_WALK_PLACE)
    task = world("manual")
    edit_record(task, place="req-R-2")                                                    # a record of another place
    void(task, BR.R_WALK_PLACE)


def test_walk_answer_not_bug_void():
    task = world("manual")
    record = TP.ans(PLACE, "not_a_bug", task)
    record.update(writer="place_answers.py", dispatch=TP.DISPATCH)
    record_path(task).write_text(json.dumps(record), encoding="utf-8")
    void(task, BR.R_WALK_ANSWER)


def test_walk_record_unreadable_void():
    task = world("manual")
    record_path(task).write_text("{not json", encoding="utf-8")
    void(task, BR.R_WALK_RECORD)
    task = world("manual")
    data = json.loads(record_path(task).read_text(encoding="utf-8"))
    data.pop("writer")
    record_path(task).write_text(json.dumps(data), encoding="utf-8")
    void(task, BR.R_WALK_RECORD)
    void(world("manual", walk=False), BR.R_NO_FILE)                                       # no record at all


def test_walk_outside_evidence_void():
    task = world("manual")
    _json(task, "work/place-answer.json", json.loads(record_path(task).read_text(encoding="utf-8")))
    draft = json.loads((task / "work" / "bug-drafts" / DRAFT).read_text(encoding="utf-8"))
    draft["reproduction"] = [dict(entry(), evidence="work/place-answer.json")]
    (task / "work" / "bug-drafts" / DRAFT).write_text(json.dumps(draft), encoding="utf-8")
    void(task, BR.R_OUTSIDE)


# --- the position: what each entry kind still has to pass -------------------------------------------------------------------------

def test_result_draft_keeps_current_red_fact():
    assert lifted(world("result", status="failed"))                                       # red now: the walk lifts it
    void(world("result", status="passed"), BR.R_GREEN)                                    # green now: a walk never overrides
    void(world("result", verdict="NO_DEFECT"), BR.R_NO_TRIAGE)


def test_walk_without_a_readable_report_void_except_code_reading():
    # F9: a draft with a triage row but no readable run report is not lifted by a walk (the old rule held for `own_script`); a code-reading
    # draft has no run by construction, so its walk needs no report
    for shape in ("result", "manual", "observation"):
        task = world(shape)
        assert lifted(task)
        (task / "work" / "run-report.json").unlink()
        void(task, BR.R_NO_REPORT)
    assert lifted(world("code"))


def test_replace_to_bug_with_a_receipt_that_stands_withdraws_the_question():
    # F1 (lifting half): question first, then the bug whose receipt stands -> the chain is withdrawn (gate B asks nothing)
    task = world("manual", walk=False)
    TP.write(task, TP.ans(PLACE, "requirement_silent", task))
    assert TP.line_of(task, PLACE)["kind"] == "unresolved_question"
    out = TP.write(task, TP.ans(PLACE, "bug", task, source="requirement", draft=DRAFT, expectation=TP.req("R-1", QUOTE)), replace=True)
    assert out["withdrawn"] and TP.line_of(task, PLACE) is None and PA.settled_answer(task, PLACE)[1] == "settled"


def test_replace_to_bug_with_a_void_receipt_leaves_a_register_line():
    # F1 (void half): the current result is green, the walk cannot lift the draft: the suspicion keeps a line (the gap, with the question)
    task = world("result", status="passed", walk=False)
    TP.write(task, TP.ans(PLACE, "requirement_silent", task))
    out = TP.write(task, TP.ans(PLACE, "bug", task, source="requirement", draft=DRAFT, expectation=TP.req("R-1", QUOTE)), replace=True)
    assert out["withdrawn"] is None and PA.settled_answer(task, PLACE)[1] == "carrier missing"
    PA.close_unsettled(task, PA._data()["gap_reasons"][0])
    gap = TP.line_of(task, PLACE)
    assert gap["kind"] == "coverage_gap" and gap["question"], gap


def test_first_bug_answer_after_a_gap_leaves_no_stale_gap():
    # F2 with the real receipt: the close gapped the place, the rework's first answer is a bug that lifts the draft
    task = world("manual", walk=False)
    PA.close_unsettled(task, PA._data()["gap_reasons"][0])
    assert TP.line_of(task, PLACE)["kind"] == "coverage_gap"
    TP.write(task, TP.ans(PLACE, "bug", task, source="requirement", draft=DRAFT, expectation=TP.req("R-1", QUOTE)))
    assert PA.settled_answer(task, PLACE)[1] == "settled"
    PA.close_unsettled(task, PA._data()["gap_reasons"][0])
    assert TP.line_of(task, PLACE) is None


def test_rerun_entry_still_needs_red_now():
    # a non-walk entry on a manual draft is judged exactly as before: no current row -> void, even next to a valid walk
    task = world("manual", extra={"reproduction": [FRESH, entry()]})
    (task / "evidence").mkdir(exist_ok=True)
    (task / "evidence" / "rerun.log").write_text("400\n", encoding="utf-8")
    word, kinds, problems = step(task)
    assert (word, kinds) == (BR.REPRODUCED, ["walk"]) and BR.R_NO_CURRENT in problems, (word, kinds, problems)
    only = world("manual", extra={"reproduction": [FRESH]})
    (only / "evidence").mkdir(exist_ok=True)
    (only / "evidence" / "rerun.log").write_text("400\n", encoding="utf-8")
    assert step(only) == ("unconfirmed", [], [BR.R_NO_CURRENT])


# --- the words and the vocabulary ---------------------------------------------------------------------------------------------------

def test_words_name_the_walk():
    text = BR.reproduction_words({"confirmation": BR.REPRODUCED, "reproduced_how": ["walk"]})
    assert "the analyst walked it on the stand" in text and "no person has confirmed it yet" in text, text
    both = BR.reproduction_words({"confirmation": BR.REPRODUCED, "reproduced_how": ["own_script", "walk"]})
    assert "own script reproduced it and the analyst walked it" in both, both
    assert "walked" not in BR.reproduction_words({"confirmation": BR.REPRODUCED, "reproduced_how": ["own_script"]})


def test_kinds_mirror_vocabulary():
    text = (Path(__file__).resolve().parents[2] / "handoffs" / "vocabulary.yaml").read_text(encoding="utf-8")
    match = re.search(r"^bug_reproduction_kinds: \[([^\]]*)\]", text, re.MULTILINE)
    assert match and tuple(w.strip() for w in match.group(1).split(",")) == tuple(C.BUG_REPRODUCTION_KINDS)
    assert "walk" in C.BUG_REPRODUCTION_KINDS


def test_check_state_refusal_names_the_walk():
    task = world("code", extra={"check_state": "executed"})
    draft = json.loads((task / "work" / "bug-drafts" / DRAFT).read_text(encoding="utf-8"))
    assert any(code == BR.R_CR_CHECK_STATE and "a walk of the analyst may be its receipt" in detail
               for code, detail in BR.code_reading_problems(task, draft, drafts=[(DRAFT, draft)]))


# --- the runner ---------------------------------------------------------------------------------------------------------------------

def main() -> int:
    tests = [(name, fn) for name, fn in sorted(globals().items()) if name.startswith("test_") and callable(fn)]
    failed = 0
    try:
        for name, fn in tests:
            try:
                fn()
                print(f"PASS {name}")
            except Exception:                                                 # noqa: BLE001
                failed += 1
                print(f"FAIL {name}\n{traceback.format_exc()}")
    finally:
        TP._cleanup_all()
    print(f"test_walk_receipt: {len(tests) - failed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
