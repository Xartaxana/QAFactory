"""test_place_answers.py - the places of S7, the analyst's answer per place, settled / unsettled, the gaps (spec t-1991, node U1).

Run: python -B -m pytest scripts/tests/test_place_answers.py -q      or      python -B scripts/tests/test_place_answers.py

Each test builds its own temp story (a register with a `code_says` column, bug drafts, captures written the way `manual_capture` writes
them: a row of `captures.jsonl` with `path` and `content_hash` under `work/evidence/manual/settle-<id>/a1/`). The `open` source and the
resolution (iv) use the investigation fixture. Mutation -> killing test (named, run once each in the node's report):
  E1.5's check (`bug` with source none) removed  -> test_bug_without_source_refused
  resolution (iv) removed from unresolved_targets -> test_settled_open_target_resolved_iv
"""
import atexit
import contextlib
import hashlib
import io
import json
import shutil
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import harness  # noqa: E402

import bug_records as BR  # noqa: E402
import controller as CT  # noqa: E402
import exploratory_findings as EF  # noqa: E402
import investigation as INV  # noqa: E402
import place_answers as PA  # noqa: E402

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "investigation-14857" / "TP1-14857"
DISPATCH = "S7-qa-failure-analyst-1"
ROOTS: list = []


def _cleanup_all() -> None:
    while ROOTS:
        harness.cleanup(ROOTS.pop())


atexit.register(_cleanup_all)
REG ="""---
task: T-1
created: 2026-11-01
ids: [R-1, R-2, R-3]
---

## Register

| R | Requirement (one verifiable statement) | source | derived_from | verifiable | ac_ref | observable | impact | delta | code_says |
|---|---|---|---|---|---|---|---|---|---|
| R-1 | The total is shown with two decimals. | ac | - | yes | AC-1 | diff:app.py:10 | degraded | new | contradicts: F-1 |
| R-2 | Orders over the limit are refused. | derived | - | yes | - | current-code:app.py:20 | degraded | new | contradicts: F-2 |
| R-3 | The cart can be emptied. | ac | - | yes | AC-2 | diff:app.py:30 | degraded | new | meets: F-3 |
"""


def story(register: str = REG) -> Path:
    root = harness.temp_project()
    ROOTS.append(root)
    task = root / "qa-factory" / "artifacts" / "T-1"
    (task / "work" / "bug-drafts").mkdir(parents=True)
    (task / "pipeline.json").write_text(json.dumps({"ticket": "T-1", "stages": {}}), encoding="utf-8")
    if register:
        (task / "work" / "requirements-register.md").write_text(register, encoding="utf-8")
    return task


def fixture_story() -> Path:
    root = harness.temp_project()
    ROOTS.append(root)
    task = root / "qa-factory" / "artifacts" / "TP1-14857"
    shutil.copytree(FIXTURE, task)
    return task


def draft(task: Path, name: str, **over) -> str:
    body = {"title": "Total has one decimal", "impact": "degraded", "violates": "R-1", "case": "TC-1", "triage_ref": "TC-1@a1",
            "manual_steps": "open the cart", "confirmation": "unconfirmed"}     # a draft with no `confirmation` reads as confirmed_by_person
    body.update(over)
    (task / "work" / "bug-drafts").mkdir(parents=True, exist_ok=True)
    (task / "work" / "bug-drafts" / name).write_text(json.dumps(body), encoding="utf-8")
    return name


def capture(task: Path, place: str, text: str = "Total: 10.5 EUR", attempt: str = "a1", name: str = "001-page.txt") -> str:
    """A capture the way the recorder writes it: the file and its row of `captures.jsonl` (path, content_hash)."""
    folder = task / "work" / "evidence" / "manual" / f"settle-{place}" / attempt
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_text(text, encoding="utf-8")
    rel = (folder / name).relative_to(task).as_posix()
    row = {"path": rel, "content_hash": hashlib.sha256((folder / name).read_bytes()).hexdigest(), "kind": "page", "phase": "post_action"}
    with (folder / "captures.jsonl").open("a", encoding="utf-8") as out:
        out.write(json.dumps(row) + "\n")
    return rel


def ans(place: str, answer: str, task: Path = None, quote: str = "Total: 10.5", source: str = "none", **over) -> dict:
    record = {"place": place, "answer": answer, "expectation": {"source": source, "id": "", "quote": ""},
              "seen": {"quote": quote, "capture": capture(task, place) if task is not None else ""}}
    if answer == "requirement_silent":
        record["question"] = "Should the total show two decimals?"
    if answer in ("not_a_bug", "impossible"):
        record["why"] = "the page shows what the requirement says" if answer == "not_a_bug" else "the stand has no such page"
    record.update(over)
    return record


def req(rid: str, quote: str) -> dict:
    return {"source": "requirement", "id": rid, "quote": quote}


def write(task: Path, record: dict, replace: bool = False, dispatch: str = DISPATCH) -> dict:
    return PA.write(task, dispatch, record["place"], record, replace=replace)


def refused(call) -> str:
    try:
        call()
    except ValueError as exc:
        return str(exc)
    raise AssertionError("expected a refusal")


def ids(found) -> list:
    return [p["id"] for p in found["places"]]


def line_of(task: Path, place: str):
    return EF.read(task)["active"].get(place)


# --- the places ---------------------------------------------------------------------------------------------------------------

def test_places_is_a_join_only():
    task = story()
    draft(task, "d1.json")
    found = PA.places(task)
    assert ids(found) == ["req-R-1", "req-R-2"], ids(found)           # rows R-1 and R-2 contradict; the draft joins req-R-1
    one = found["places"][0]
    assert one["sources"] == ["register", "draft"] and one["refs"]["draft"] == ["d1.json"] and one["expectation_hint"] == "R-1"
    assert found["unreadable"] == []


def test_empty_says_none():
    task = story(register="")
    found = PA.places(task)
    assert found == {"places": [], "unreadable": []}
    assert "Places to settle: none in this run" in PA._list_lines(found, {})


def test_unreadable_source_never_none():
    task = story(register="## Register\n\n| R | Notes |\n|---|---|\n| R-1 | x |\n")      # no Requirement column: register_rows refuses
    found = PA.places(task)
    assert found["places"] == [] and found["unreadable"], found
    text = "\n".join(PA._list_lines(found, {}))
    assert "could not be computed whole" in text and "none in this run" not in text
    task = story()
    (task / "work" / "bug-drafts" / "broken.json").write_text("{not json", encoding="utf-8")        # a draft that does not parse
    assert any(rec.endswith("broken.json") for rec, _ in PA.places(task)["unreadable"])


def test_draft_listing_unreadable_folder_named():
    task = story(register="")
    original = BR.draft_listing
    BR.draft_listing = lambda t: ([], ["work/bug-drafts: cannot list: boom"])
    try:
        found = PA.places(task)
    finally:
        BR.draft_listing = original
    assert found["places"] == [] and found["unreadable"] == [("work/bug-drafts", "work/bug-drafts: cannot list: boom")]


def test_contradiction_read_by_code_says_contradicts():
    task = story()
    assert ids(PA.places(task)) == ["req-R-1", "req-R-2"]               # R-3 says `meets`: no place
    import branch_accounting as BA
    assert [r["r"] for r in PA._register(task)[0] if BA.code_says_contradicts(r)] == ["R-1", "R-2"]


def test_deleting_code_reading_draft_keeps_place_settled():
    task = story()
    name = draft(task, "cr.json", evidence="code-reading", violates="requirement:R-2")
    assert PA.place_of_draft(task, name, json.loads((task / "work/bug-drafts/cr.json").read_text()), PA._register(task)[0]) == "req-R-2"
    write(task, ans("req-R-2", "not_a_bug", task))
    (task / "work" / "bug-drafts" / "cr.json").unlink()
    assert PA.settled_answer(task, "req-R-2")[1] == "settled" and "req-R-2" in ids(PA.places(task))


def test_id_stable_when_draft_written_for_open_place():
    task = fixture_story()
    before = ids(PA.places(task))
    draft(task, "late.json", case="TC-006", violates="R-4", triage_ref="TC-006@a1")
    found = PA.places(task)
    assert ids(found) == before and "draft" in next(p for p in found["places"] if p["id"] == "case-TC-006")["sources"]
    assert "draft-late" not in ids(found)


def test_two_places_never_merged():
    task = story()
    draft(task, "both.json", case="TC-9", violates="R-1")
    found = PA.places(task)
    assert ids(found) == ["req-R-1", "req-R-2"]                              # a draft touching R-1 joins only req-R-1
    task = fixture_story()
    (task / "work" / "requirements-register.md").write_text(REG.replace("R-1", "R-4"), encoding="utf-8")
    draft(task, "both.json", case="TC-006", violates="R-4")
    got = ids(PA.places(task))
    assert "case-TC-006" in got and "req-R-4" in got and "draft-both" not in got


def test_reproduced_draft_not_a_place():
    task = story(register="")
    draft(task, "person.json", confirmation="confirmed_by_person")
    draft(task, "rerun.json", confirmation="confirmed_by_rerun")
    assert PA.places(task)["places"] == []


def test_role_word_without_receipt_is_a_place():
    task = story(register="")
    draft(task, "typed.json", confirmation="reproduced_by_factory", violates="R-9")
    assert ids(PA.places(task)) == ["draft-typed"]


# --- the keys of an answer ----------------------------------------------------------------------------------------------------

def test_bug_without_source_refused():
    task = story()
    d = draft(task, "d1.json")
    problems = PA.answer_problems(task, ans("req-R-1", "bug", task, draft=d))
    assert any("bug needs the requirement it breaks" in line and "requirement_silent" in line for line in problems), problems
    assert "bug needs the requirement" in refused(lambda: write(task, ans("req-R-1", "bug", task, draft=d)))


def test_bug_on_unconfirmed_requirement_refused():
    task = story()
    d = draft(task, "d2.json", violates="R-2")
    record = ans("req-R-2", "bug", task, source="requirement", draft=d)
    record["expectation"] = req("R-2", "Orders over the limit are refused.")
    assert any("no confirmed source" in line and "`person`" in line for line in PA.answer_problems(task, record))
    good = ans("req-R-1", "bug", task, draft=draft(task, "d1.json"))
    good["expectation"] = req("R-1", "The total is shown with two decimals.")
    assert PA.answer_problems(task, good) == []                              # R-1 has an AC: confirmed
    for bad in ("r-1", "R-012"):                                             # not the register's R
        good["expectation"] = req(bad, "The total is shown with two decimals.")
        assert any("is not in the register" in line for line in PA.answer_problems(task, good))
    good["expectation"] = req("R-1", "Totals are in euros.")
    assert any("not in the text of R-1" in line for line in PA.answer_problems(task, good))


def question_story(status: str = "answered") -> Path:
    task = story()
    (task / "work" / "requirements-readiness.json").write_text(json.dumps({"open_questions": [
        {"id": "Q7", "question": "How many decimals does the total show?", "status": "open"}]}), encoding="utf-8")
    return task


def test_unsettled_question_refused():
    task = question_story()
    d = draft(task, "d1.json")
    record = ans("req-R-1", "bug", task, draft=d)
    record["expectation"] = {"source": "question", "id": "Q7", "quote": "two decimals"}
    problems = PA.answer_problems(task, record)
    assert problems and any("Q7" in line for line in problems), problems


def person_world(reason: str = "The total must show two decimals, I confirm."):
    task = story()
    (task / "state" / "words").mkdir(parents=True)
    (task / "state" / "events.jsonl").write_text("", encoding="utf-8")
    words = task / "state" / "words" / "driver-answer-1.txt"
    words.write_text(reason, encoding="utf-8", newline="")
    return task, "state/words/driver-answer-1.txt", reason


class State:
    def __init__(self, dispatches):
        self.dispatches, self.original = dispatches, CT.Controller.state

    def __enter__(self):
        mine = self.dispatches
        CT.Controller.state = lambda self: {"dispatches": mine}

    def __exit__(self, *exc):
        CT.Controller.state = self.original


def person_record(task, rel, quote, d):
    record = ans("req-R-2", "bug", task, draft=d)
    record["expectation"] = {"source": "person", "id": rel, "quote": quote}
    return record


def test_bug_on_person_words_after_gate_b_accepted():
    task, rel, reason = person_world()
    d = draft(task, "d2.json", violates="R-2")
    dispatches = {DISPATCH: {"id": DISPATCH, "stage": "S7", "person_words": True,
                             "request_binding": {"purpose": "rework", "reason": reason}}}
    with State(dispatches):
        record = person_record(task, rel, "must show two decimals", d)
        assert PA.answer_problems(task, record, dispatch=DISPATCH) == []     # F-D never refuses `person` (R-2 is unconfirmed)
        assert PA.answer_problems(task, record) != []                        # no dispatch named: refused with its door


def test_person_quote_not_in_words_refused():
    task, rel, reason = person_world()
    d = draft(task, "d2.json", violates="R-2")
    dispatches = {DISPATCH: {"id": DISPATCH, "stage": "S7", "person_words": True, "request_binding": {"reason": reason}}}
    with State(dispatches):
        problems = PA.answer_problems(task, person_record(task, rel, "three decimals", d), dispatch=DISPATCH)
    assert any("not in the person's words" in line for line in problems), problems


def test_person_file_not_the_dispatch_reason_refused():
    task, rel, reason = person_world()
    d = draft(task, "d2.json", violates="R-2")
    forged = task / "state" / "words" / "role-wrote-this.txt"
    forged.write_text("I confirm everything.", encoding="utf-8")
    dispatches = {DISPATCH: {"id": DISPATCH, "stage": "S7", "person_words": True, "request_binding": {"reason": reason}},
                  "S7-x-2": {"id": "S7-x-2", "stage": "S7", "request_binding": {"reason": reason}}}
    with State(dispatches):
        forged_problems = PA.answer_problems(task, person_record(task, "state/words/role-wrote-this.txt", "confirm", d), dispatch=DISPATCH)
        no_mark = PA.answer_problems(task, person_record(task, rel, "two decimals", d), dispatch="S7-x-2")
        outside = PA.answer_problems(task, person_record(task, "work/requirements-register.md", "two", d), dispatch=DISPATCH)
    assert any("not the reason this dispatch was given" in line for line in forged_problems), forged_problems
    assert any("carries no person_words mark" in line for line in no_mark), no_mark
    assert any("no file under state/words" in line for line in outside), outside


def test_person_bug_with_no_words_path_checks_the_dispatch_reason():
    """t-2027 F3 (t-2010 F15): no brief carries the words file's path, so `id` may be empty: the quote is read against the dispatch's `reason`."""
    task, rel, reason = person_world()
    d = draft(task, "d2.json", violates="R-2")
    dispatches = {DISPATCH: {"id": DISPATCH, "stage": "S7", "person_words": True, "request_binding": {"purpose": "rework", "reason": reason}},
                  "S7-x-2": {"id": "S7-x-2", "stage": "S7", "request_binding": {"reason": reason}},
                  "S7-x-3": {"id": "S7-x-3", "stage": "S7", "person_words": True, "request_binding": {"reason": ""}}}
    with State(dispatches):
        assert PA.answer_problems(task, person_record(task, "", "must show two decimals", d), dispatch=DISPATCH) == []
        wrong = PA.answer_problems(task, person_record(task, "", "three decimals", d), dispatch=DISPATCH)
        no_mark = PA.answer_problems(task, person_record(task, "", "two decimals", d), dispatch="S7-x-2")
        no_words = PA.answer_problems(task, person_record(task, "", "two decimals", d), dispatch="S7-x-3")
        no_dispatch = PA.answer_problems(task, person_record(task, "", "two decimals", d))
        outside = PA.answer_problems(task, person_record(task, "work/requirements-register.md", "two", d), dispatch=DISPATCH)
    assert any("not in the person's words" in line for line in wrong), wrong
    assert any("carries no person_words mark" in line for line in no_mark), no_mark
    assert any("carries no person" in line for line in no_words), no_words
    assert no_dispatch, "no dispatch named: refused with its door"
    assert any("no file under state/words" in line for line in outside), "a path that is given stays checked"


def test_capture_of_other_place_refused():
    task = story()
    other = capture(task, "req-R-2")
    record = ans("req-R-1", "not_a_bug", task)
    record["seen"]["capture"] = other
    assert any("not in the capture index of this place" in line for line in PA.answer_problems(task, record))


def test_capture_not_in_index_refused():
    task = story()
    record = ans("req-R-1", "not_a_bug", task)
    folder = task / "work" / "evidence" / "manual" / "settle-req-R-1" / "a1"
    (folder / "handmade.txt").write_text("Total: 10.5", encoding="utf-8")        # a file the role wrote, no row in the index
    record["seen"]["capture"] = (folder / "handmade.txt").relative_to(task).as_posix()
    assert any("not in the capture index" in line for line in PA.answer_problems(task, record))
    fresh = story()
    problems = PA.answer_problems(fresh, ans("req-R-1", "not_a_bug", None, why="x"))
    assert any("`seen.capture` is missing" in line for line in problems)
    record = ans("req-R-1", "not_a_bug")
    record["seen"]["capture"] = "work/evidence/manual/settle-req-R-1/a1/001-page.txt"
    assert any("capture first" in line for line in PA.answer_problems(fresh, record))


def test_capture_bytes_changed_refused():
    task = story()
    record = ans("req-R-1", "not_a_bug", task)
    assert PA.answer_problems(task, record) == []
    (task / record["seen"]["capture"]).write_text("Total: 10.5 EUR - edited", encoding="utf-8")
    assert any("changed after the recorder hashed it" in line for line in PA.answer_problems(task, record))


def test_http_capture_of_place_accepted():
    task = story()
    record = ans("req-R-1", "not_a_bug", task, quote='"total": 10.5')
    path = task / "work" / "evidence" / "manual" / "settle-req-R-1" / "a1" / "002-response.json"
    path.write_text(json.dumps({"status": 200, "body": '{"total": 10.5}'}), encoding="utf-8")
    row = {"path": path.relative_to(task).as_posix(), "content_hash": hashlib.sha256(path.read_bytes()).hexdigest(), "kind": "request_response"}
    with (path.parent / "captures.jsonl").open("a", encoding="utf-8") as out:
        out.write(json.dumps(row) + "\n")
    record["seen"]["capture"] = row["path"]
    assert PA.answer_problems(task, record) == []


def test_quote_not_in_capture_refused():
    task = story()
    problems = PA.answer_problems(task, ans("req-R-1", "not_a_bug", task, quote="Total: 99.99"))
    assert any("`seen.quote` is not in" in line for line in problems), problems


def test_answer_keys_required():
    task = story()
    cases = [("answer", dict(answer="maybe")), ("expectation.source", dict(expectation={"source": "guess"})),
             ("question", dict(answer="requirement_silent", question="")), ("why", dict(answer="impossible", why="")),
             ("why", dict(answer="not_a_bug", why="")), ("draft", dict(answer="bug", draft="", expectation=req("R-1", "The total")))]
    for needle, over in cases:
        record = ans("req-R-1", "not_a_bug", task, why="ok")
        record.update(over)
        problems = PA.answer_problems(task, record)
        assert problems and any(needle in line for line in problems), (needle, problems)
    record = ans("req-R-1", "not_a_bug", task, quote="")
    assert any("`seen.quote` is empty" in line for line in PA.answer_problems(task, record))
    record = ans("req-R-1", "bug", task, draft="nothing.json")
    record["expectation"] = req("R-1", "The total")
    assert any("no draft file of the story" in line for line in PA.answer_problems(task, record))
    other = draft(task, "other.json", case="TC-9", violates="R-9")                # draft of place draft-other, not req-R-1
    record["draft"] = other
    assert any("belongs to place draft-other" in line for line in PA.answer_problems(task, record))
    assert PA.answer_problems(task, "not an object")


def test_second_write_needs_replace():
    task = story()
    write(task, ans("req-R-1", "not_a_bug", task))
    assert "--replace" in refused(lambda: write(task, ans("req-R-1", "not_a_bug", task)))
    out = write(task, ans("req-R-1", "not_a_bug", task, why="a second look says the same"), replace=True)
    record = json.loads((task / out["record"]).read_text())
    assert len(record["replaces"]) == 64 and record["writer"] == "place_answers.py" and record["dispatch"] == DISPATCH and record["written_at"]


def test_new_place_accepted_and_slug_boundary():
    task = story()
    ok = "new-" + "a" * 36                                                   # 40 chars of slug incl. the "new-"? slug is 36 here
    assert len(ok) - 4 == 36
    for slug, accepted in (("a" * 40, True), ("a" * 41, False), ("Bad_Slug", False), ("", False)):
        place = "new-" + slug
        record = ans(place, "impossible", task)
        problems = PA.answer_problems(task, record) if accepted else PA.answer_problems(task, dict(record, place=place))
        assert (problems == []) == accepted, (slug, problems)
    out = write(task, ans("new-" + "a" * 40, "impossible", task))
    assert (task / out["record"]).is_file() and "new-" + "a" * 40 in ids(PA.places(task))
    assert "not a place of this run" in refused(lambda: write(task, ans("req-R-77", "impossible", task)))
    assert "place_answers.py list" in refused(lambda: write(task, ans("req-R-77", "impossible", task)))


# --- the register line --------------------------------------------------------------------------------------------------------

def test_requirement_silent_line_fields():
    task = story()
    out = write(task, ans("req-R-1", "requirement_silent", task))
    line = line_of(task, "req-R-1")
    assert out["line"] == line["id"] and line["kind"] == "unresolved_question" and line["oracle_status"] == "owner_question"
    assert line["question"] == "Should the total show two decimals?" and line["owner_role"] == INV.OWNER_WORDS
    assert line["origin"] == {"dispatch": DISPATCH, "target": "req-R-1"} and line["recorded_by"] == DISPATCH
    assert line["statement"] == "Total: 10.5" and "R-1" in line["refs"] and line["evidence_refs"][0]["path"] == PA.record_rel("req-R-1")
    assert PA.settled_answer(task, "req-R-1")[1] == "settled"


def test_not_a_bug_writes_observation_line():
    task = story()
    write(task, ans("req-R-1", "not_a_bug", task))
    line = line_of(task, "req-R-1")
    assert line["kind"] == "observation" and line["why_not_a_bug"] == "the page shows what the requirement says"
    assert "question" not in line and PA.settled_answer(task, "req-R-1")[1] == "settled"


def test_impossible_writes_gap_line():
    task = story()
    write(task, ans("req-R-1", "impossible", None, quote=""))
    line = line_of(task, "req-R-1")
    assert line["kind"] == "coverage_gap" and line["missing_prerequisite"] == "the stand has no such page"
    assert line["statement"] == "the stand could not show this place" and PA.settled_answer(task, "req-R-1")[1] == "settled"


def test_write_corrects_existing_chain():
    task = fixture_story()
    INV.project(task, "S7-qa-failure-analyst-9")                              # the investigation's own line for case-TC-006
    first = line_of(task, "case-TC-006")
    out = write(task, ans("case-TC-006", "not_a_bug", task))
    lines = EF.read(task)["lines"]
    new = next(line for line in lines if line["id"] == out["line"])
    assert new["op"] == "correct" and new["corrects"]["id"] == first["id"] and line_of(task, "case-TC-006")["id"] == out["line"]


class Lifts:
    """The step reads a walk receipt that stands (the walk receipt itself is judged in test_walk_receipt.py)."""

    def __enter__(self):
        self.saved = BR.confirmation_of
        BR.confirmation_of = lambda *a, **k: ("reproduced_by_factory", ["walk"], [])

    def __exit__(self, *_exc):
        BR.confirmation_of = self.saved


def bug_over_question(task, lifting: bool):
    """A question line written first, then the answer replaced by `bug`; the receipt stands (`lifting`) or does not."""
    d = draft(task, "d1.json")
    write(task, ans("req-R-1", "requirement_silent", task))
    record = ans("req-R-1", "bug", task, draft=d)
    record["expectation"] = req("R-1", "The total is shown with two decimals.")
    if lifting:
        with Lifts():
            return write(task, record, replace=True)
    return write(task, record, replace=True)


def test_replace_withdraws_question_line_when_the_receipt_stands():
    task = story()
    out = bug_over_question(task, True)
    assert out["withdrawn"] and line_of(task, "req-R-1") is None              # gate B never asks a withdrawn question
    with Lifts():
        assert PA.settled_answer(task, "req-R-1")[1] == "settled"


def test_replace_to_bug_with_void_receipt_keeps_the_question_until_the_gap():
    # F1: the receipt does not stand (no `reproduction` in the draft): the question line is NOT withdrawn, and the close turns it into a gap
    task = story()
    out = bug_over_question(task, False)
    assert out["withdrawn"] is None and line_of(task, "req-R-1")["kind"] == "unresolved_question"
    assert PA.settled_answer(task, "req-R-1")[1] == "carrier missing"
    written = PA.close_unsettled(task, PA._data()["gap_reasons"][0])
    gap = line_of(task, "req-R-1")
    assert written and gap["kind"] == "coverage_gap" and gap["missing_prerequisite"].startswith("the analyst's answer did not reach its record")
    assert gap["question"] == "Should the total show two decimals?"           # F5: the person's question travels with the gap


def test_withdrawn_chain_replace_refused_with_door():
    task = story()
    bug_over_question(task, True)
    before = (task / PA.record_rel("req-R-1")).read_bytes()
    text = refused(lambda: write(task, ans("req-R-1", "not_a_bug", task), replace=True))
    assert "withdrawn when you answered bug" in text and "new-<slug>" in text
    assert "impossible" not in text                                            # F7: the door must be one the refused party can use
    assert (task / PA.record_rel("req-R-1")).read_bytes() == before            # refused BEFORE anything was written


def test_withdrawn_chain_unsettled_again_still_gets_a_gap_line():
    # F1(c): the chain was withdrawn on a settled bug; the receipt then stops standing: the gap goes under its own target, never printed only
    task = story()
    bug_over_question(task, True)
    assert line_of(task, "req-R-1") is None
    printed = []
    written = PA.close_unsettled(task, PA._data()["gap_reasons"][0], printed)         # the receipt is void now (no patch)
    gap = EF.read(task)["active"].get("place-gap-req-R-1")
    assert gap and gap["kind"] == "coverage_gap" and gap["origin"]["target"] == "place-gap-req-R-1" and gap["id"] in written, (written, printed)
    again = PA.close_unsettled(task, PA._data()["gap_reasons"][0])
    assert "req-R-1" not in [EF.target_of(line) for line in EF.read(task)["lines"] if line["id"] in again]      # the same text: no second line


def test_gap_under_place_gap_is_withdrawn_once_the_place_is_settled():
    # t-2027 F10: the chain was withdrawn, the receipt went void and the gap went under `place-gap-<id>`; the receipt stands again: no stale gap text stays active
    task = story()
    bug_over_question(task, True)
    PA.close_unsettled(task, PA._data()["gap_reasons"][0])
    assert "place-gap-req-R-1" in EF.read(task)["active"]
    printed = []
    with Lifts():
        assert PA.settled_answer(task, "req-R-1")[1] == "settled"
        PA.close_unsettled(task, PA._data()["gap_reasons"][0], printed)
        assert "place-gap-req-R-1" not in EF.read(task)["active"], printed
        assert any("place-gap-req-R-1" in line and "withdrawn" in line for line in printed), printed
        assert PA.close_unsettled(task, PA._data()["gap_reasons"][0]) == []          # and a second close writes and withdraws nothing


def test_first_bug_answer_corrects_a_stale_gap():
    # F2: the close gapped the place; the rework's FIRST answer is a bug whose receipt stands: no stale "not settled" gap stays active
    task = story()
    d = draft(task, "d1.json")
    PA.close_unsettled(task, PA._data()["gap_reasons"][0])
    assert line_of(task, "req-R-1")["kind"] == "coverage_gap"
    record = ans("req-R-1", "bug", task, draft=d)
    record["expectation"] = req("R-1", "The total is shown with two decimals.")
    with Lifts():
        out = write(task, record)
        assert out["withdrawn"] and line_of(task, "req-R-1") is None
        PA.close_unsettled(task, PA._data()["gap_reasons"][0])
        assert line_of(task, "req-R-1") is None and line_of(task, "req-R-2")["kind"] == "coverage_gap"


def test_close_withdraws_the_line_of_a_bug_settled_after_the_write():
    # F1(b): the receipt did not stand at the write (line kept), the draft is repaired later: the close withdraws the line
    task = story()
    bug_over_question(task, False)
    assert line_of(task, "req-R-1") is not None
    with Lifts():
        assert PA.settled_answer(task, "req-R-1")[1] == "settled"
        PA.close_unsettled(task, PA._data()["gap_reasons"][0])
        assert line_of(task, "req-R-1") is None


def test_project_skips_a_place_settled_bug():
    # F3: the investigation's projection never puts a person's question on a place the analyst settled as a bug
    task = fixture_story()
    (task / "work" / "requirements-register.md").write_text(REG.replace("R-1", "R-4"), encoding="utf-8")
    d = draft(task, "late.json", case="TC-006", violates="R-4", triage_ref="TC-006@a1")
    record = ans("case-TC-006", "bug", task, draft=d)
    record["expectation"] = req("R-4", "The total is shown with two decimals.")
    with Lifts():
        write(task, record)
        assert PA.settled_answer(task, "case-TC-006")[1] == "settled"
        out = INV.project(task, "S7-qa-failure-analyst-9")
        assert line_of(task, "case-TC-006") is None and "case-TC-006" not in [EF.target_of(l) for l in EF.read(task)["lines"]], out
        assert line_of(task, "case-TC-007") is not None                         # the other targets are projected as ever


def test_append_refusal_keeps_place_unsettled():
    task = story()
    original = EF.append

    def refusing(task_root, line, *, by):
        raise ValueError("pipeline.json cannot be read")
    EF.append = refusing
    try:
        out = write(task, ans("req-R-1", "not_a_bug", task))
    finally:
        EF.append = original
    assert "pipeline.json cannot be read" in out["refusal"] and (task / out["record"]).is_file()
    state = PA.settled_answer(task, "req-R-1")
    assert state[0] is not None and state[1] == "carrier missing"             # presence of a record alone never settles a place
    err = io.StringIO()
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
        EF.append = refusing
        try:
            code = PA.main(["write", "--task-root", str(task), "--dispatch", DISPATCH, "--place", "req-R-1", "--replace",
                            "--file", str(_file(task, ans("req-R-1", "not_a_bug", task)))])
        finally:
            EF.append = original
    assert code == 2 and "pipeline.json cannot be read" in err.getvalue()


def _file(task: Path, record: dict) -> Path:
    path = task / "work" / "my-answer.json"
    path.write_text(json.dumps(record), encoding="utf-8")
    return path


def test_register_not_installed_keeps_record():
    task = story()
    original = INV._writer
    INV._writer = lambda: None
    try:
        out = write(task, ans("req-R-1", "not_a_bug", task))
        state = PA.settled_answer(task, "req-R-1")
    finally:
        INV._writer = original
    assert out["installed"] is False and (task / out["record"]).is_file() and state[1] == "carrier missing"


def test_conflict_draft_stands():
    task = story()
    draft(task, "d1.json")                                                   # unconfirmed draft joined to req-R-1
    write(task, ans("req-R-1", "not_a_bug", task))
    record, state, why = PA.settled_answer(task, "req-R-1")
    assert state == "conflict" and "d1.json" in why


def test_conflict_gap_text_is_not_not_walked():
    task = story()
    draft(task, "d1.json")
    write(task, ans("req-R-1", "not_a_bug", task))
    written = PA.close_unsettled(task, PA._data()["gap_reasons"][0])
    gap = {line["origin"]["target"]: line for line in EF.read(task)["lines"]}["req-R-1"]
    assert gap["kind"] == "coverage_gap" and gap["missing_prerequisite"].startswith("the analyst's answer and its own records disagree:")
    assert "not walked" not in gap["missing_prerequisite"] and written


def test_close_unsettled_once_per_place():
    task = story()
    draft(task, "d1.json")
    reasons = PA._data()["gap_reasons"]
    first = PA.close_unsettled(task, reasons[0])
    assert len(first) == 2                                                    # req-R-1 (register + draft) and req-R-2 (register)
    assert PA.close_unsettled(task, reasons[0]) == []                         # the same text: no second line
    again = PA.close_unsettled(task, reasons[1])
    assert len(again) == 2 and EF.read(task)["lines"][-1]["op"] == "correct"
    assert [l for l in EF.read(task)["active"].values() if l["kind"] == "coverage_gap"].__len__() == 2
    assert line_of(task, "req-R-1")["missing_prerequisite"] == "not settled by the analyst - " + reasons[1]


def test_close_unsettled_skips_plain_open_targets():
    task = fixture_story()
    assert len(PA.places(task)["places"]) == 8
    assert PA.close_unsettled(task, PA._data()["gap_reasons"][0]) == []       # plain open targets keep the investigation road
    original = INV._writer
    INV._writer = lambda: None
    try:
        printed = []
        assert PA.close_unsettled(task, PA._data()["gap_reasons"][0], printed) == [] and printed
    finally:
        INV._writer = original
    INV.project(task, DISPATCH)
    write(task, ans("case-TC-006", "not_a_bug", task))
    original_append = EF.append
    EF.append = lambda *a, **k: (_ for _ in ()).throw(ValueError("refused"))
    try:
        write(task, ans("case-TC-007", "not_a_bug", task))
    finally:
        EF.append = original_append
    assert PA.settled_answer(task, "case-TC-007")[1] == "carrier missing"
    assert len(PA.close_unsettled(task, PA._data()["gap_reasons"][0])) == 1   # the open place whose answer did not reach its record


def test_close_unsettled_unknown_why_refused():
    task = story()
    text = refused(lambda: PA.close_unsettled(task, "because"))
    for reason in PA._data()["gap_reasons"]:
        assert reason in text


def test_gap_line_prefix_outside_investigation():
    task = story()
    PA.close_unsettled(task, PA._data()["gap_reasons"][0])
    for line in EF.read(task)["lines"]:
        assert line["recorded_by"] == "code:place_answers.close_unsettled" and not INV.is_code_line(line)


def test_stale_gap_corrected_by_later_answer():
    task = story()
    PA.close_unsettled(task, PA._data()["gap_reasons"][0])
    gap = line_of(task, "req-R-1")
    out = write(task, ans("req-R-1", "requirement_silent", task))
    now = line_of(task, "req-R-1")
    assert now["id"] == out["line"] and now["kind"] == "unresolved_question" and now["corrects"]["id"] == gap["id"]
    assert PA.settled_answer(task, "req-R-1")[1] == "settled"
    assert PA.close_unsettled(task, PA._data()["gap_reasons"][0]) == []         # req-R-2's gap already says the same: no second line
    assert line_of(task, "req-R-2")["kind"] == "coverage_gap"


def test_settled_open_target_resolved_iv():
    task = fixture_story()
    budget = INV.load_budget()[0]
    before = INV.open_targets(task, budget)
    assert "case-TC-006" in [t["id"] for t in before["unresolved"]] and before["settled"] == []
    write(task, ans("case-TC-006", "requirement_silent", task))
    after = INV.open_targets(task, budget)
    assert "case-TC-006" not in [t["id"] for t in after["unresolved"]]
    assert [t["id"] for t in after["settled"]] == ["case-TC-006"]
    why = dict(after["resolved"])["case-TC-006"]
    assert why == f"settled by {DISPATCH}: requirement_silent"
    assert "case-TC-006" in ids(PA.places(task))                                # still listed, as a settled place
    assert INV.decision(task, {}, json.loads((task / "pipeline.json").read_text()), budget)[0] == "dispatch"   # the others still wait


def test_carrier_missing_resolves_nothing():
    task = fixture_story()
    original = EF.append
    EF.append = lambda *a, **k: (_ for _ in ()).throw(ValueError("refused"))
    try:
        write(task, ans("case-TC-006", "requirement_silent", task))
    finally:
        EF.append = original
    after = INV.open_targets(task, INV.load_budget()[0])
    assert "case-TC-006" in [t["id"] for t in after["unresolved"]] and after["settled"] == []
    original_settled = PA.settled_answer
    PA.settled_answer = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
    try:
        broken = INV.open_targets(task, INV.load_budget()[0])
    finally:
        PA.settled_answer = original_settled
    assert "case-TC-006" in [t["id"] for t in broken["unresolved"]]
    assert "place answers: the analyst's answer could not be read" in broken["context"]["case-TC-006"]


def test_register_unreadable_names_doors():
    task = story(register="## Register\n\n| R | Notes |\n|---|---|\n| R-1 | x |\n")
    record = ans("req-R-1", "not_a_bug", task, source="requirement")
    record["expectation"] = req("R-1", "x")
    problems = PA.answer_problems(task, record)
    assert any("the register cannot be read" in line and "requirement_silent" in line and "`person`" in line for line in problems)


def test_investigation_dispatch_refused():
    task = story()
    dispatches = {"S7-inv-2": {"id": "S7-inv-2", "stage": "S7", "request_binding": {"purpose": "investigation"}}}
    (task / "state").mkdir(exist_ok=True)
    (task / "state" / "events.jsonl").write_text("", encoding="utf-8")
    with State(dispatches):
        problems = PA.answer_problems(task, ans("req-R-1", "not_a_bug", task), dispatch="S7-inv-2")
        text = refused(lambda: write(task, ans("req-R-1", "not_a_bug", task), dispatch="S7-inv-2"))
    assert any("investigation dispatch cannot answer a place" in line for line in problems)
    assert "investigation_probe.py record" in text and not (task / PA.record_rel("req-R-1")).exists()


def test_answer_never_judged_by_words():
    task = story()
    a = ans("req-R-1", "not_a_bug", task, why="it is fine")
    b = ans("req-R-1", "not_a_bug", task, why="this is a defect, the total is wrong, a clear bug")
    assert PA.answer_problems(task, a) == PA.answer_problems(task, b) == []
    a["seen"]["quote"] = b["seen"]["quote"] = "Total: 99"
    assert PA.answer_problems(task, a) == PA.answer_problems(task, b) != []


def test_every_refusal_names_a_door():
    task = story()
    battery = [ans("req-R-1", "bug", task), ans("nope", "not_a_bug", task), ans("req-R-1", "impossible", task, why=""),
               ans("req-R-1", "requirement_silent", task, question=""), ans("req-R-1", "not_a_bug", None),
               ans("req-R-1", "not_a_bug", task, quote="zzz"), ans("req-R-1", "x", task), "text", {},
               ans("req-R-1", "not_a_bug", task, expectation={"source": "person", "id": "state/words/x.txt", "quote": "q"}),
               ans("req-R-1", "not_a_bug", task, expectation={"source": "question", "id": "Q1", "quote": "q"}),
               ans("req-R-1", "not_a_bug", task, expectation=req("R-99", "q"))]
    for record in battery:
        problems = PA.answer_problems(task, record, dispatch=DISPATCH)
        assert problems and all(" Door: " in line for line in problems), (record, problems)
    text = refused(lambda: PA.close_unsettled(task, "no"))
    assert " Door: " in text
    # E1.18: before U2 a `bug` answer's walk receipt is refused by today's step -> `carrier missing`, honest in both worlds
    d = draft(task, "d1.json", reproduction=[{"kind": "walk", "evidence": PA.record_rel("req-R-1"), "observed": "Total: 10.5"}])
    record = ans("req-R-1", "bug", task, draft=d)
    record["expectation"] = req("R-1", "The total is shown with two decimals.")
    write(task, record)
    assert PA.settled_answer(task, "req-R-1")[1] == "carrier missing"
    original = BR.confirmation_of
    BR.confirmation_of = lambda *a, **k: ("reproduced_by_factory", ["walk"], [])      # after U2: the receipt stands
    try:
        assert PA.settled_answer(task, "req-R-1")[1] == "settled"
    finally:
        BR.confirmation_of = original


def test_list_cli_prints_states():
    task = story()
    write(task, ans("req-R-1", "not_a_bug", task))
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = PA.main(["list", "--task-root", str(task)])
    text = out.getvalue()
    assert code == 0 and "req-R-1 | register | settled |" in text and "req-R-2 | register | open |" in text


# --- the person's question is never lost (F5) ----------------------------------------------------------------------------------

def test_open_place_with_a_draft_keeps_the_investigation_question():
    task = fixture_story()
    INV.project(task, "S7-qa-failure-analyst-9")
    before = line_of(task, "case-TC-006")
    draft(task, "late.json", case="TC-006", violates="R-4", triage_ref="TC-006@a1")
    assert sorted(next(p for p in PA.places(task)["places"] if p["id"] == "case-TC-006")["sources"]) == ["draft", "open"]
    assert PA.close_unsettled(task, PA._data()["gap_reasons"][0]) == []        # the investigation road keeps a place that is still open
    assert line_of(task, "case-TC-006") == before


def test_close_never_corrects_a_line_of_another_owner():
    task = story()
    draft(task, "d1.json")
    EF.append(task, {"op": "add", "kind": "observation", "title": "t", "statement": "the probe saw it", "refs": ["R-1"],
                     "evidence_refs": [{"path": "work/requirements-register.md"}], "probe": None, "verification_status": "unverified",
                     "why_not_a_bug": "w", "origin": {"dispatch": "S7-x-2", "target": "req-R-1"}}, by="S7-x-2")
    before = line_of(task, "req-R-1")
    printed = []
    PA.close_unsettled(task, PA._data()["gap_reasons"][0], printed)
    assert line_of(task, "req-R-1") == before and any("req-R-1" in line for line in printed), printed


def test_conflict_twice_writes_one_line_and_keeps_the_question():
    task = story()
    draft(task, "d1.json")
    write(task, ans("req-R-1", "requirement_silent", task))
    assert PA.settled_answer(task, "req-R-1")[1] == "conflict"
    reason = PA._data()["gap_reasons"][0]
    first = PA.close_unsettled(task, reason)
    assert PA.settled_answer(task, "req-R-1")[1] == "conflict"                  # the gap line does not flip the state
    second = PA.close_unsettled(task, reason)
    assert len(first) == 2 and second == []                                      # req-R-1 and req-R-2 the first time; nothing the second
    gap = line_of(task, "req-R-1")
    assert gap["kind"] == "coverage_gap" and gap["question"] == "Should the total show two decimals?" and gap["oracle_status"] == "owner_question"


# --- an unknown never vanishes (F6, F8, F11) -------------------------------------------------------------------------------------

def test_draft_without_confirmation_is_a_place_with_a_door():
    task = story()
    name = draft(task, "nc.json")
    path = task / "work" / "bug-drafts" / name
    body = json.loads(path.read_text(encoding="utf-8"))
    body.pop("confirmation")
    path.write_text(json.dumps(body), encoding="utf-8")
    place = next(p for p in PA.places(task)["places"] if p["id"] == "req-R-1")
    assert "draft" in place["sources"]
    record = ans("req-R-1", "bug", task, draft=name)
    record["expectation"] = req("R-1", "The total is shown with two decimals.")
    write(task, record)
    state = PA.settled_answer(task, "req-R-1")
    assert state[1] == "carrier missing" and "confirmation: unconfirmed" in state[2], state
    other = story()
    draft(other, "nc.json")
    body = json.loads((other / "work/bug-drafts/nc.json").read_text(encoding="utf-8"))
    body.pop("confirmation")
    (other / "work/bug-drafts/nc.json").write_text(json.dumps(body), encoding="utf-8")
    write(other, ans("req-R-1", "not_a_bug", other))
    assert PA.settled_answer(other, "req-R-1")[1] == "conflict"                  # a draft with no word is unconfirmed for the join, as in the list


def test_corrupt_record_of_a_new_place_is_unreadable_not_none():
    task = story(register="")
    out = write(task, ans("new-odd", "impossible", task))
    (task / out["record"]).write_text("{not json", encoding="utf-8")
    found = PA.places(task)
    assert found["places"] == [] and [rec for rec, _why in found["unreadable"]] == [out["record"]], found
    assert "Places to settle: none in this run" not in PA._list_lines(found, {})


def test_unknown_dispatch_refused_when_the_story_state_reads():
    task = story()
    (task / "state").mkdir(exist_ok=True)
    (task / "state" / "events.jsonl").write_text("", encoding="utf-8")
    with State({DISPATCH: {"id": DISPATCH, "stage": "S7"}}):
        problems = PA.answer_problems(task, ans("req-R-1", "not_a_bug", task), dispatch="no-such-dispatch")
        assert any("no-such-dispatch" in line and " Door: " in line for line in problems), problems
        assert "no-such-dispatch" in refused(lambda: write(task, ans("req-R-1", "not_a_bug", task), dispatch="no-such-dispatch"))
        assert PA.answer_problems(task, ans("req-R-1", "not_a_bug", task), dispatch=DISPATCH) == []
    original = CT.Controller.state
    CT.Controller.state = lambda self: (_ for _ in ()).throw(RuntimeError("state unreadable"))
    try:
        assert PA.answer_problems(task, ans("req-R-1", "not_a_bug", task), dispatch="no-such-dispatch") == []      # an unreadable state locks nobody
    finally:
        CT.Controller.state = original


def absorbed_story(**merged_over):
    """A `bug` answer written for d1.json (place req-R-1); d1.json is then gone and merged.json names it in `from_draft`."""
    task = story()
    d = draft(task, "d1.json")
    record = ans("req-R-1", "bug", task, draft=d)
    record["expectation"] = req("R-1", "The total is shown with two decimals.")
    write(task, record)
    (task / "work" / "bug-drafts" / d).unlink()
    return task, record


def merged(task, name="merged.json", from_draft="d1.json", evidence="work/evidence/other.txt", **over):
    over.setdefault("case", "TC-2")
    over.setdefault("triage_ref", "TC-2@a1")
    over.setdefault("violates", "R-2")
    return draft(task, name, manifestations=[{"action": "a", "from_draft": from_draft, "evidence": evidence}], **over)


def test_absorbed_draft_settled_through_the_merged_draft_walk():
    task, _record = absorbed_story()
    assert PA.settled_answer(task, "req-R-1")[1] == "invalid"        # nobody carries it yet: refused as today, a gap at the close
    merged(task)
    assert PA.settled_answer(task, "req-R-1")[1] == "carrier missing"        # the merged draft's own step does not hold
    with Lifts():
        assert PA.settled_answer(task, "req-R-1")[1] == "settled"
        assert "req-R-1" in ids(PA.places(task))
        assert "req-R-1" not in [p["id"] for p in PA.unsettled(task)]


def test_absorbed_draft_settled_when_the_manifestation_evidence_is_the_answers_capture():
    task, record = absorbed_story()
    merged(task, evidence=record["seen"]["capture"])
    assert PA.settled_answer(task, "req-R-1")[1] == "settled"


def test_gone_draft_without_a_manifestation_stays_a_gap():
    task, _record = absorbed_story()
    draft(task, "other.json", case="TC-2", triage_ref="TC-2@a1", violates="R-2")       # a live draft that names nothing
    with Lifts():
        assert PA.settled_answer(task, "req-R-1")[1] == "invalid"


def test_from_draft_naming_another_file_settles_nothing():
    task, record = absorbed_story()
    merged(task, from_draft="never-existed.json", evidence=record["seen"]["capture"])
    with Lifts():
        assert PA.settled_answer(task, "req-R-1")[1] == "invalid"


def test_two_merged_drafts_naming_one_from_draft_settle_nothing():
    task, record = absorbed_story()
    merged(task, evidence=record["seen"]["capture"])
    merged(task, name="merged2.json", case="TC-3", triage_ref="TC-3@a1", violates="R-3")
    with Lifts():
        state = PA.settled_answer(task, "req-R-1")
    assert state[1] == "carrier missing" and "merged.json" in state[2] and "merged2.json" in state[2]


def test_empty_evidence_never_matches():
    task, _record = absorbed_story()
    merged(task, evidence="")
    assert PA.settled_answer(task, "req-R-1")[1] == "carrier missing"


def test_replace_names_the_merged_draft_that_absorbed_the_places_draft():
    task, record = absorbed_story()
    merged(task)
    assert PA.answer_problems(task, dict(record, draft="merged.json")) == []


def test_replace_naming_a_draft_that_absorbed_nothing_of_the_place_is_refused():
    task, record = absorbed_story()
    merged(task, from_draft="never-existed.json")
    problems = PA.answer_problems(task, dict(record, draft="merged.json"))
    assert len(problems) == 1 and "belongs to place" in problems[0] and " Door: " in problems[0], problems


def test_replace_naming_a_missing_file_keeps_the_no_draft_file_refusal():
    task, record = absorbed_story()
    merged(task)
    problems = PA.answer_problems(task, dict(record, draft="nowhere.json"))
    assert len(problems) == 1 and "is no draft file" in problems[0], problems


def test_data_rows_and_no_dead_names():
    data = PA._data()
    assert data["scribe_line_max"] == 1500 and not hasattr(PA, "STATES")
    assert "capture_optional" not in data and "new_slug_pattern" not in data
    assert set(data["gap_reason_names"]) == {"unanswered", "stand", "session", "no_failures", "pretriaged"}
    assert sorted(data["gap_reason_names"].values()) == sorted(data["gap_reasons"])        # the names and the list say the same five texts


# --- TR1-11: the place of an observation with no pinned case; one JSON reader -------------------------------------------------------

def test_unpinned_observation_place_is_found_and_a_case_is_never_read_as_a_target_id():
    task = fixture_story()
    obs = "obs-S6-qa-runner-4-0"                                             # the row's case is a range, so no case is pinned: target.case is None
    assert obs in ids(PA.places(task))                                       # the place of an observation with no case is found
    name = draft(task, "o.json", case=obs, violates="", triage_ref="")
    body = json.loads((task / "work" / "bug-drafts" / name).read_text(encoding="utf-8"))
    assert PA.place_of_draft(task, name, body) != obs                        # `case` is a case id by the draft contract: no join on a target id
    assert PA.place_of_draft(task, name, body) == "draft-o"                  # the draft keeps its own place, nothing is dropped


class LiftsOnly:
    """Only the draft titled `title` holds a standing walk receipt; every other draft is read by the real step reader."""

    def __init__(self, title):
        self.title = title

    def __enter__(self):
        self.saved = real = BR.confirmation_of
        BR.confirmation_of = lambda task, data, *a, **k: (("reproduced_by_factory", ["walk"], [])
                                                          if data.get("title") == self.title else real(task, data, *a, **k))

    def __exit__(self, *_exc):
        BR.confirmation_of = self.saved


def sibling_world(**sibling):
    """A `bug` answer on req-R-1 carried by d1.json (lifted), and a second draft e.json of the same place."""
    task = story()
    d = draft(task, "d1.json", title="main")
    draft(task, "e.json", title="sibling", case="TC-5", triage_ref="TC-5@a1", **sibling)      # violates R-1: joins req-R-1
    record = ans("req-R-1", "bug", task, draft=d)
    record["expectation"] = req("R-1", "The total is shown with two decimals.")
    write(task, record)
    with LiftsOnly("main"):
        return PA.settled_answer(task, "req-R-1")


def test_sibling_with_its_walk_entry_names_its_own_reasons():
    # R1 (review probe 4): the sibling already cites the record, its triage row is no APP_BUG row: that reason is named, no false door
    state = sibling_world(reproduction=[{"kind": "walk", "evidence": PA.record_rel("req-R-1"), "observed": "Total: 10.5"}])
    assert state[1] == "carrier missing", state
    why = state[2]
    assert "e.json" in why and "(no APP_BUG triage row)" in why and "clear those reasons in it" in why, why
    assert "answer its own place" not in why and "add a `walk` entry" not in why, why
    assert "merge it into d1.json when it is the same bug" in why and why.endswith("the close names this place as a gap"), why


def test_sibling_without_a_walk_entry_is_told_to_add_one():
    state = sibling_world()
    assert state[1] == "carrier missing", state
    why = state[2]
    assert f"add a `walk` entry citing {PA.record_rel('req-R-1')} to it" in why, why
    assert "stands unconfirmed: add" in why and "()" not in why and "; ;" not in why, why      # no reasons: no dangling parenthesis
    assert "clear those reasons" not in why and "answer its own place" not in why, why


def test_word_less_sibling_gets_the_no_confirmation_door_never_the_walk_door():
    # L1: `confirmation_of(draft=True)` returns early for a draft with no word; a walk entry alone would not lift it
    walk = [{"kind": "walk", "evidence": PA.record_rel("req-R-1"), "observed": "Total: 10.5"}]
    for over in ({}, {"reproduction": walk}):
        task = story()
        d = draft(task, "d1.json", title="main")
        draft(task, "e.json", title="sibling", case="TC-5", triage_ref="TC-5@a1", **over)
        path = task / "work" / "bug-drafts" / "e.json"
        body = json.loads(path.read_text(encoding="utf-8"))
        body.pop("confirmation")
        path.write_text(json.dumps(body), encoding="utf-8")
        record = ans("req-R-1", "bug", task, draft=d)
        record["expectation"] = req("R-1", "The total is shown with two decimals.")
        write(task, record)
        with LiftsOnly("main"):
            state = PA.settled_answer(task, "req-R-1")
        why = state[2]
        assert state[1] == "carrier missing", (over, state)
        assert "(no `confirmation` word)" in why and PA._data()["line_texts"]["no_confirmation"] in why, (over, why)
        assert "add a `walk` entry" not in why and "clear those reasons" not in why, (over, why)
        assert "merge it into d1.json when it is the same bug" in why and why.endswith("the close names this place as a gap"), (over, why)


def test_one_json_object_reader_for_records_and_drafts():
    task = story(register="")
    bad = task / "work" / "bug-drafts" / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert PA._draft_json(bad)[0] is None and PA._draft_json(bad)[1]         # unreadable: no object, a why
    bad.write_text("[1]", encoding="utf-8")
    assert PA._draft_json(bad)[0] is None                                    # not an object: the same
    assert PA._draft_json(task / "work" / "bug-drafts" / "absent.json")[0] is None
    bad.write_bytes(b"\xef\xbb\xbf" + json.dumps({"title": "x"}).encode("utf-8"))      # a BOM is part of the encoding
    assert PA._draft_json(bad) == ({"title": "x"}, "")
    assert not hasattr(PA, "_json_object")                                   # no second reader named like bug_records' one
    assert PA._s(None) == "" and PA._squash(None) == "" and PA._squash(" a   b ") == "a b"


# --- the runner ---------------------------------------------------------------------------------------------------------------

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
        _cleanup_all()
    print(f"test_place_answers: {len(tests) - failed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
