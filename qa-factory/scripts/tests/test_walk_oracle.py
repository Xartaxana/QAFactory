"""test_walk_oracle.py - the requirement form of a code-reading draft's oracle accepts a standing walk receipt (spec t-1991, node U2b, fork F-J (a)).

Run: python -B -m pytest -p no:cacheprovider scripts/tests/test_walk_oracle.py -q      or      python -B scripts/tests/test_walk_oracle.py

A code-reading draft violating R-3 whose register row does NOT say `contradicts: <its fact id>` (R-3 says `meets: F-3`) passes the requirement
form of `bug_records._oracle_problems` only when a `walk` entry of THIS draft stands (`_walk_receipt_problem`) and its record's expectation is
source `requirement`, id R-3. The error goes DOWN: it may refuse a true bug, it never accepts a bug whose expectation is not a requirement.
Mutation -> killing test (named, run once in the node's report):
  the requirement-id compare removed from `_walk_stands_for` -> test_other_requirement_refused
"""
import json
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import bug_records as BR  # noqa: E402
import place_answers as PA  # noqa: E402
import test_place_answers as TP  # noqa: E402  (its fixtures: a story with a register, drafts, captures the way the recorder writes them)

PLACE = "req-R-3"
DRAFT = "d.json"
QUOTE = "The cart can be emptied."


def world(*, walk: bool = True, expectation=None, extra=None) -> Path:
    """A story: register row R-3 says `meets: F-3`, one code-reading draft `d.json` of R-3 with a walk entry, and (when `walk`) the record
    `place_answers.write` keeps."""
    task = TP.story()
    path = task / "work" / "context-bundle.json"
    path.write_text(json.dumps({"facts": [{"id": "F-3", "path": "app.py", "line": 30}]}), encoding="utf-8")
    over = dict(evidence="code-reading", violates="requirement:R-3", oracle={"requirement": "R-3", "quote": QUOTE},
                fact={"id": "F-3", "path": "app.py", "line": 30}, check_state="not_executed",
                red_test_none="no factory test spoke: read from the code", created="2026-11-05", case=None, triage_ref=None,
                reproduction=[{"kind": "walk", "evidence": PA.record_rel(PLACE), "observed": "the cart stays full"}])
    over.update(extra or {})
    TP.draft(task, DRAFT, **over)
    if walk:
        TP.write(task, TP.ans(PLACE, "bug", task, source="requirement", draft=DRAFT, expectation=expectation or TP.req("R-3", QUOTE)))
    return task


def draft_of(task: Path) -> dict:
    return json.loads((task / "work" / "bug-drafts" / DRAFT).read_text(encoding="utf-8"))


def oracle(task: Path) -> list:
    return BR._oracle_problems(task, draft_of(task), "R-3", None, None)


def record_path(task: Path) -> Path:
    return task / PA.record_rel(PLACE)


def edit_record(task: Path, **changes) -> None:
    data = json.loads(record_path(task).read_text(encoding="utf-8"))
    data.update(changes)
    record_path(task).write_text(json.dumps(data), encoding="utf-8")


def refused(task: Path) -> None:
    found = oracle(task)
    assert found and found[0][0] == BR.R_CR_NO_ORACLE, found


# --- the walk is the contradiction ----------------------------------------------------------------------------------------------------

def test_walk_receipt_stands_for_requirement_form():
    task = world()
    assert oracle(task) == [], oracle(task)
    draft = draft_of(task)
    assert BR.code_reading_problems(task, draft, drafts=[(DRAFT, draft)]) == []


def test_no_walk_entry_refused():
    refused(world(walk=False, extra={"reproduction": None}))


# --- adversarial inputs that stay refused ----------------------------------------------------------------------------------------------

def test_other_requirement_refused():
    task = world(expectation=TP.req("R-1", "The total is shown with two decimals."))     # a record that stands, of another requirement
    assert json.loads(record_path(task).read_text(encoding="utf-8"))["expectation"]["id"] == "R-1"
    refused(task)


def test_receipt_of_other_draft_refused():
    task = world()
    edit_record(task, draft="other.json")
    refused(task)


def test_receipt_of_other_place_refused():
    task = world()
    edit_record(task, place="req-R-2")
    refused(task)


def test_void_receipts_refused():
    # each void reason of U2: not bug, no writer, unreadable, capture changed, capture not in the recorder's index
    task = world()
    record = json.loads(record_path(task).read_text(encoding="utf-8"))
    (task / record["seen"]["capture"]).write_text("Total: 10.5 EUR - edited", encoding="utf-8")
    refused(task)
    task = world()
    edit_record(task, answer="not_a_bug")
    refused(task)
    task = world()
    data = json.loads(record_path(task).read_text(encoding="utf-8"))
    data.pop("writer")
    record_path(task).write_text(json.dumps(data), encoding="utf-8")
    refused(task)
    task = world()
    folder = task / "work" / "evidence" / "manual" / f"settle-{PLACE}" / "a1"
    (folder / "handmade.txt").write_text("Total: 10.5 EUR", encoding="utf-8")
    edit_record(task, seen={"quote": "Total: 10.5", "capture": (folder / "handmade.txt").relative_to(task).as_posix()})
    refused(task)


def test_other_sources_refused():
    for source in ("person", "question", "none"):
        task = world()
        edit_record(task, expectation={"source": source, "id": "R-3", "quote": QUOTE})
        refused(task)


def test_hand_written_record_refused():
    task = world(walk=False)
    record = TP.ans(PLACE, "bug", task, draft=DRAFT)                      # source none: a bug needs a source
    record.update(writer="place_answers.py", dispatch=TP.DISPATCH, expectation={"source": "requirement", "id": "R-3", "quote": QUOTE})
    record["seen"]["capture"] = "work/evidence/manual/settle-req-R-3/a1/nowhere.txt"
    record_path(task).parent.mkdir(parents=True, exist_ok=True)
    record_path(task).write_text(json.dumps(record), encoding="utf-8")
    refused(task)


def test_unreadable_file_refused():
    task = world()
    record_path(task).write_text("{not json", encoding="utf-8")
    refused(task)
    record_path(task).unlink()
    refused(task)


# --- the code_says road ----------------------------------------------------------------------------------------------------------------

def test_code_says_road_unchanged():
    task = TP.story()
    (task / "work" / "context-bundle.json").write_text(json.dumps({"facts": [{"id": "F-1", "path": "app.py", "line": 10}]}), encoding="utf-8")
    base = {"oracle": {"requirement": "R-1", "quote": "The total is shown with two decimals."}, "fact": {"id": "F-1"}}
    assert BR._oracle_problems(task, base, "R-1", None, None) == []                 # the row says contradicts: F-1
    other = dict(base, fact={"id": "F-9"})                                          # contradicts another fact, no walk
    found = BR._oracle_problems(task, other, "R-1", None, None)
    assert found and found[0][0] == BR.R_CR_NO_ORACLE and "contradicts" in found[0][1], found
    assert BR._oracle_problems(task, dict(base, oracle={"requirement": "R-1", "quote": "nope"}), "R-1", None, None)[0][0] == BR.R_CR_QUOTE
    assert BR._oracle_problems(task, dict(base, oracle={"requirement": "R-2", "quote": "x"}), "R-1", None, None)[0][0] == BR.R_CR_NO_ORACLE


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
    print(f"test_walk_oracle: {len(tests) - failed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
