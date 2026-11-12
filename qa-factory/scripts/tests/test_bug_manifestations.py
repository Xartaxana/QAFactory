"""test_bug_manifestations.py - node N1 of spec t-2187 (one bug, many manifestations): the closed words of `contract.py`, the
readers and problem lists of `bug_records.py` (`draft_cases`, `draft_requirements`, `manifestation_refs`, `manifestation_summary`,
`mechanism_problems`, `manifestation_problems`) and the public `place_answers.capture_stands`.

Run: python -B -m pytest scripts/tests/test_bug_manifestations.py -q

Each test builds its own temp story: a project root with `src/BookDetailPage.tsx`, a task folder, captures written the way the
recorder writes them (a row of `captures.jsonl` with `path` and `content_hash`). Every boundary has a test AT it and BEYOND it
(spec 3.2, 4, 6). Mutation -> the test meant to kill it (named, not run in this node):
  `mechanism_problems` reads `status` through `.strip().lower()`  -> test_status_is_matched_exactly
  `capture_stands` skips the hash comparison                        -> test_capture_changed_after_hashing_does_not_stand
  `_capture_list` stops calling `capture_stands`                    -> test_capture_list_calls_the_public_reader
"""
import atexit
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import harness  # noqa: E402

import bug_records as BR  # noqa: E402
import contract as C  # noqa: E402
import place_answers as PA  # noqa: E402

ROOTS: list = []
LINE = "setQuantity(Math.max(1, parseInt(e.target.value) || 1))"
CODE = ["// the book page", "const a = 1;", "  " + LINE + "  ", "export default a;"]     # LINE is line 3, with spaces around it
CASE = "settle-new-qty-start"
ROW_A = {"instance_id": "TC-5#obs1", "attempt_id": "a1"}
ROW_B = {"instance_id": "TC-7#obs1", "attempt_id": "a1"}
ROWS = [{**ROW_A, "verdict": "APP_BUG"}, {**ROW_B, "verdict": "APP_BUG"},
        {"instance_id": "TC-9#obs1", "attempt_id": "a1", "verdict": "NO_DEFECT"}]


def _cleanup_all() -> None:
    while ROOTS:
        harness.cleanup(ROOTS.pop())


atexit.register(_cleanup_all)


def world() -> Path:
    """A task folder inside a project that holds `src/BookDetailPage.tsx` (LINE on line 3)."""
    root = harness.temp_project()
    ROOTS.append(root)
    (root / "src").mkdir(exist_ok=True)
    (root / "src" / "BookDetailPage.tsx").write_text("\n".join(CODE) + "\n", encoding="utf-8")
    task = root / "qa-factory" / "artifacts" / "T-1"
    (task / "work" / "bug-drafts").mkdir(parents=True)
    return task


def capture(task: Path, text: str = "1 11 focus=yes", case: str = CASE, attempt: str = "a1", name: str = "012-fill.txt",
            index: bool = True) -> str:
    """A capture the way the recorder writes it: the file and its row of `captures.jsonl`; returns the task-relative path."""
    folder = task / "work" / "evidence" / "manual" / case / attempt
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_bytes(text if isinstance(text, bytes) else text.encode("utf-8"))
    rel = path.relative_to(task).as_posix()
    if index:
        row = {"path": rel, "content_hash": hashlib.sha256(path.read_bytes()).hexdigest(), "kind": "page"}
        with (folder / "captures.jsonl").open("a", encoding="utf-8") as out:
            out.write(json.dumps(row) + "\n")
    return rel


def code_basis(bid: str = "b1", **over) -> dict:
    return {"id": bid, "kind": "code_line", "path": "src/BookDetailPage.tsx", "line": 3, "quote": LINE, **over}


def run_basis(task: Path, bid: str = "b2", quote: str = "1 11 focus=yes", **over) -> dict:
    return {"id": bid, "kind": "run", "case": CASE, "capture": capture(task), "quote": quote, "start_state": "field erased first", **over}


def mech(status: str = "confirmed", basis=None, claims=None, **over) -> dict:
    out = {"statement": "the field turns an invalid value into 1", "status": status, "basis": [] if basis is None else basis,
           "claims": [] if claims is None else claims, "why": ""}
    out.update(over)
    return out


def man(**over) -> dict:
    out = {"action": "type -1 one key at a time", "start_state": "field shows 1, selected", "seen": "11", "requirement": "R-9",
           "case": "TC-5", "triage_row": dict(ROW_A), "evidence": "work/evidence/manual/TC-5/a1/006-fill.txt",
           "red_test": {"path": "tests/a.py::t", "command": "pytest tests/a.py::t"}}
    out.update(over)
    return {k: v for k, v in out.items() if v is not None}


def draft(**over) -> dict:
    out = {"title": "t", "impact": "degraded", "violates": "requirement:R-8", "case": "TC-5", "triage_ref": dict(ROW_A),
           "manual_steps": ["open the book"], "red_test_none": "manual check only"}
    out.update(over)
    return out


def codes(problems: list) -> list:
    return [reason for reason, _detail in problems]


# --- the closed words (AR-1) -----------------------------------------------------------------------------------------------

def test_constants():
    assert C.MECHANISM_STATUSES == ("confirmed", "unverified", "unknown")
    assert C.MECHANISM_BASIS_KINDS == ("code_line", "run", "person")      # F-6 (a): the person's word is a basis kind
    assert C.BUG_MECHANISM_CUTOFF == "2026-11-10"                          # the day N8 lands the phase text (spec 3.2, world 3)


def test_mechanism_owed_boundary_day():
    """I2: the one reader of the cutoff: AT the day is asked, the day before is not; `created` wins over the file's day."""
    assert C.mechanism_owed({"created": "2026-11-10"}) and C.mechanism_owed({"created": "2026-11-10T08:00:00"})
    assert not C.mechanism_owed({"created": "2026-11-09"}) and not C.mechanism_owed({"created": "2026-11-09T23:59:59"})
    assert C.mechanism_owed({}, "2026-11-10") and not C.mechanism_owed({}, "2026-11-09")     # an undated draft: the file's day
    assert C.mechanism_owed({"created": "2026-11-12"}, "2026-01-01") and not C.mechanism_owed({"created": "2026-11-01"}, "2026-11-12")
    assert not C.mechanism_owed({}) and not C.mechanism_owed(None, "")                         # no readable day: not asked
    held = C.BUG_MECHANISM_CUTOFF
    try:
        C.BUG_MECHANISM_CUTOFF = None
        assert not C.mechanism_owed({"created": "2099-01-01"})                                 # world 2: nobody is asked
    finally:
        C.BUG_MECHANISM_CUTOFF = held


# --- draft_cases / draft_requirements / manifestation_refs / manifestation_summary ------------------------------------------

def test_draft_cases_union_keeps_order_without_repeats():
    d = draft(case="A", cases=["A", "B"], manifestations=[man(case="C"), man(case="B"), man(case=None)])
    assert BR.draft_cases(d) == ["A", "B", "C"]
    assert BR.draft_cases({"cases": ["X", "Y"]}) == ["X", "Y"]             # a draft with no `case`
    assert BR.draft_cases({"case": ["P", "Q"]}) == ["P", "Q"]               # a list in `case` is read as well
    assert BR.draft_cases({"case": " A "}) == ["A"]


def test_draft_cases_old_draft_is_its_case():
    assert BR.draft_cases(draft()) == ["TC-5"]
    assert BR.draft_cases({"case": "A/B"}) == ["A/B"]                       # an area-qualified spelling is kept whole


def test_draft_cases_empty_and_broken_inputs():
    for bad in (None, "x", [], 7, {}, {"case": None, "cases": None}, {"case": 5, "cases": [1, None, ""]},
                {"manifestations": "x"}, {"manifestations": ["x", 3]}, {"manifestations": [{"case": 4}]}):
        assert BR.draft_cases(bad) == [], bad


def test_draft_requirements_adds_manifestations():
    d = draft(requirements=["R-8"], manifestations=[man(requirement="R-9"), man(requirement="R-10"), man(requirement="R-8")])
    assert BR.draft_requirements(d) == ["R-10", "R-8", "R-9"]
    only_violates = draft(manifestations=[man(requirement="R-9")])
    assert BR.draft_requirements(only_violates) == ["R-8", "R-9"]          # `violates` is not dropped by a manifestation's id
    assert BR.draft_requirements(draft()) == ["R-8"]                        # an old draft reads as before
    junk = draft(manifestations=[man(requirement="not an id"), man(requirement=None), "x", man(requirement=9)])
    assert BR.draft_requirements(junk) == ["R-8"]


def test_manifestation_refs_shapes_and_boundaries():
    d = draft(manifestations=[man(), man(triage_row="TC-7#obs1@a2"), man(triage_row="TC-9#obs1"),
                              man(triage_row=dict(ROW_A)), man(triage_row=None, probe={"case": CASE}), "x", man(triage_row=[1]),
                              man(triage_row={"instance_id": "", "attempt_id": "a1"})])
    assert BR.manifestation_refs(d) == [("TC-5#obs1", "a1"), ("TC-7#obs1", "a2"), ("TC-9#obs1", "")]
    assert BR.manifestation_refs(draft()) == []
    assert BR.manifestation_refs({"manifestations": "x"}) == []
    assert BR.manifestation_refs(None) == []


def test_manifestation_summary():
    d = draft(manifestations=[man(), man(action="type 1.5", start_state="", seen="11 after erasing"), "x"])
    assert BR.manifestation_summary(d) == ["type -1 one key at a time; start: field shows 1, selected; seen: 11",
                                           "type 1.5; seen: 11 after erasing"]
    assert BR.manifestation_summary(draft()) == []
    assert BR.manifestation_summary({"manifestations": 4}) == []


# --- capture_stands: the public reader (spec 6) ----------------------------------------------------------------------------

def stands(task: Path, rel: str, quote: str = "1 11 focus=yes", case: str = CASE) -> list:
    return PA.capture_stands(task, case, rel, quote)


def test_capture_stands_at_and_beyond_the_boundary():
    task = world()
    rel = capture(task)
    assert stands(task, rel) == []                                          # AT: in the index, unchanged, quote inside
    assert stands(task, rel, quote="1  11\nfocus=yes") == []                # whitespace is squashed on both sides
    assert any("is not in" in line for line in stands(task, rel, quote="1 11 focus=yes!"))      # BEYOND: one char more
    assert any("is not in" in line for line in stands(task, rel, quote="   "))                  # whitespace only: no quote
    assert any("is not in" in line for line in stands(task, rel, quote=""))
    assert any("is not in" in line for line in PA.capture_stands(task, CASE, rel, None))
    assert stands(task, "") and "missing" in stands(task, "")[0]
    assert "`basis.capture` is missing" in PA.capture_stands(task, CASE, "", "x", field="basis")[0]
    assert "`seen.capture` is missing" in stands(task, "")[0]


def test_capture_of_another_case_does_not_stand():
    task = world()
    other = capture(task, case="settle-other")
    assert any("no capture of this place exists yet" in line for line in stands(task, other))        # THIS case has no capture at all
    capture(task, name="013-own.txt")                                                                # now it has one, not that file
    assert any("not in the capture index of this place" in line for line in stands(task, other))      # named under THIS case
    assert stands(task, other, case="settle-other") == []                                              # under its own case: stands


def test_capture_changed_after_hashing_does_not_stand():
    task = world()
    rel = capture(task)
    (task / rel).write_text("1 11 focus=yes - edited", encoding="utf-8")
    assert any("changed after the recorder hashed it" in line for line in stands(task, rel))


def test_capture_not_in_index_does_not_stand():
    task = world()
    rel = capture(task, index=False)
    capture(task, name="013-other.txt")                                     # the case has an attempt and an index, without this file
    assert any("not in the capture index" in line for line in stands(task, rel))
    fresh = world()
    assert any("no capture of this place exists yet" in line for line in stands(fresh, "work/evidence/manual/x/a1/1.txt"))


def test_capture_path_with_dotdot_or_absolute_does_not_stand():
    task = world()
    rel = capture(task)
    for bad in ("../" + rel, rel.replace("work/", "work/../work/"), (task / rel).as_posix(), "/etc/passwd", "C:/Windows/win.ini"):
        assert stands(task, bad), bad
    (task.parent / "secret.txt").write_text("1 11 focus=yes", encoding="utf-8")
    assert stands(task, "../secret.txt")


def test_capture_picture_holds_no_quote():
    task = world()
    png = capture(task, text=b"\x89PNG\r\n\x1a\n1 11 focus=yes", name="020-shot.png")
    assert any("is not in" in line for line in stands(task, png))


def test_capture_case_that_cannot_name_a_root_does_not_stand():
    task = world()
    rel = capture(task)
    for bad in ("", "..", "../x", "/abs", "a//b", "has space", "a__b", ".", "x/..", "C:\\x"):
        got = stands(task, rel, case=bad)
        assert got and "cannot name a capture case" in got[0], (bad, got)


def test_capture_index_that_is_not_jsonl_does_not_stand():
    task = world()
    rel = capture(task)
    index = task / "work" / "evidence" / "manual" / CASE / "a1" / "captures.jsonl"
    index.write_text('{"path": "x"}\nnot json{\n', encoding="utf-8")
    got = stands(task, rel)
    assert got and "is not JSON" in got[0], got


def test_capture_indexed_file_deleted_does_not_stand():
    task = world()
    rel = capture(task)
    (task / rel).unlink()
    assert any("cannot be read" in line for line in stands(task, rel))


def test_capture_list_calls_the_public_reader(monkeypatch=None):
    task = world()
    seen_calls = []
    original = PA.capture_stands
    PA.capture_stands = lambda *a, **k: seen_calls.append((a, k)) or []
    try:
        assert PA._capture_list(task, "new-qty-start", {"capture": "work/evidence/manual/x", "quote": "q"}, True) == []
    finally:
        PA.capture_stands = original
    assert len(seen_calls) == 1 and seen_calls[0][0][1] == "settle-new-qty-start" and seen_calls[0][0][3] == "q"
    # the old behaviour of the list stays: nothing required and nothing named is `[]`; required and nothing named is a refusal
    assert PA._capture_list(task, "p", {}, False) == []
    assert "`seen.capture` is missing" in PA._capture_list(task, "p", {}, True)[0]


# --- mechanism_problems ----------------------------------------------------------------------------------------------------

def test_old_draft_yields_no_problems():
    task = world()
    assert BR.mechanism_problems(task, draft()) == []
    assert BR.manifestation_problems(task, draft(), ROWS) == []
    assert BR.mechanism_problems(task, None) == [] and BR.manifestation_problems(task, "x", ROWS) == []
    assert BR.draft_cases(draft()) == ["TC-5"]


def test_unknown_mechanism_with_one_manifestation_is_valid():
    task = world()
    d = draft(mechanism={"status": "unknown", "why": "no access to the application code"}, manifestations=[man()])
    assert BR.mechanism_problems(task, d) == [] and BR.manifestation_problems(task, d, ROWS) == []
    d["mechanism"] = {"status": "unknown", "why": "x", "basis": []}
    assert BR.mechanism_problems(task, d) == []
    for status in ("unknown", "unverified"):
        # t-2187 A2: `statement` is required for `unverified` (and `confirmed`), optional for `unknown`; the statement is given here
        stated = {"status": status, "statement": "the field turns input into 1"}
        assert codes(BR.mechanism_problems(task, draft(mechanism=dict(stated)))) == [BR.R_MECH_WHY], status       # BEYOND
        assert codes(BR.mechanism_problems(task, draft(mechanism={**stated, "why": "  "}))) == [BR.R_MECH_WHY], status
        assert BR.mechanism_problems(task, draft(mechanism={**stated, "why": "one start state was run"})) == [], status   # AT
    assert BR.mechanism_problems(task, draft(mechanism={"status": "unknown", "why": "one start state was run"})) == []   # unknown: no statement owed
    assert codes(BR.mechanism_problems(task, draft(mechanism={"status": "unverified", "why": "w"}))) == [BR.R_MECH_STATEMENT]
    assert codes(BR.mechanism_problems(task, draft(mechanism={"status": "unverified", "statement": "  ", "why": "w"}))) == [BR.R_MECH_STATEMENT]
    assert codes(BR.mechanism_problems(task, draft(mechanism=mech("confirmed", [code_basis()], statement="")))) == [BR.R_MECH_STATEMENT]
    assert codes(BR.mechanism_problems(task, draft(mechanism=mech("confirmed", [code_basis()], statement=None)))) == [BR.R_MECH_STATEMENT]


def test_status_is_matched_exactly():
    task = world()
    basis = [code_basis()]
    assert BR.mechanism_problems(task, draft(mechanism=mech("confirmed", basis))) == []
    for typo in ("Confirmed", "CONFIRMED", " confirmed", "confirmed ", "confirm", "", None, 1, ["confirmed"]):
        got = BR.mechanism_problems(task, draft(mechanism=mech(typo, basis)))
        assert BR.R_MECH_STATUS in codes(got), (typo, got)
    for word in C.MECHANISM_STATUSES:                                       # AT the list: each closed word is accepted as written
        assert BR.R_MECH_STATUS not in codes(BR.mechanism_problems(task, draft(mechanism=mech(word, basis, why="w"))))


def test_mechanism_not_an_object():
    task = world()
    for bad in (None, "confirmed", [], 5, True):
        assert codes(BR.mechanism_problems(task, draft(mechanism=bad))) == [BR.R_MECH_SHAPE], bad
    assert codes(BR.mechanism_problems(task, draft(mechanism=mech("unknown", statement=5, why="w")))) == [BR.R_MECH_SHAPE]


def test_confirmed_needs_a_standing_entry():
    task = world()
    assert codes(BR.mechanism_problems(task, draft(mechanism=mech("confirmed", [])))) == [BR.R_MECH_NO_BASIS]
    no_key = mech("confirmed")
    del no_key["basis"]
    assert codes(BR.mechanism_problems(task, draft(mechanism=no_key))) == [BR.R_MECH_NO_BASIS]
    assert BR.mechanism_problems(task, draft(mechanism=mech("confirmed", [code_basis()]))) == []                # AT: one standing entry
    broken = code_basis(quote="return null;")
    assert codes(BR.mechanism_problems(task, draft(mechanism=mech("confirmed", [broken])))) == [BR.R_MECH_CODE_LINE, BR.R_MECH_NO_BASIS]
    assert codes(BR.mechanism_problems(task, draft(mechanism=mech("confirmed", [broken, run_basis(task)])))) == [BR.R_MECH_CODE_LINE]
    assert BR.mechanism_problems(task, draft(mechanism=mech("unverified", [], why="no access to the application code"))) == []


def test_basis_not_a_list_or_entry_not_an_object_or_unknown_kind():
    task = world()
    for bad in ("b1", {"id": "b1"}, 4, None):
        got = BR.mechanism_problems(task, draft(mechanism={**mech("unknown", why="w"), "basis": bad}))
        assert codes(got) == [BR.R_MECH_BASIS_SHAPE], (bad, got)
    assert BR.R_MECH_BASIS_SHAPE in codes(BR.mechanism_problems(task, draft(mechanism=mech("unknown", ["x", 3], why="w"))))
    for kind in ("Code_Line", "code-line", "", None, "file", 3):
        got = BR.mechanism_problems(task, draft(mechanism=mech("unknown", [code_basis(kind=kind)], why="w")))
        assert codes(got) == [BR.R_MECH_BASIS_KIND], (kind, got)
    assert codes(BR.mechanism_problems(task, draft(mechanism=mech("unknown", [code_basis(id="")], why="w")))) == [BR.R_MECH_BASIS_ID]
    assert codes(BR.mechanism_problems(task, draft(mechanism=mech("unknown", [code_basis(id=None)], why="w")))) == [BR.R_MECH_BASIS_ID]
    twice = mech("confirmed", [code_basis("b1"), code_basis("b1")])
    assert BR.R_MECH_BASIS_ID in codes(BR.mechanism_problems(task, draft(mechanism=twice)))


def test_code_line_boundaries():
    task = world()

    def got(**over):
        return BR.mechanism_problems(task, draft(mechanism=mech("confirmed", [code_basis(**over)])))

    assert got() == []                                                      # AT: the whole line, whitespace around it ignored
    assert got(quote="setQuantity(Math.max(1,   parseInt(e.target.value)  ||  1))") == []     # inner whitespace normalised
    assert BR.R_MECH_CODE_LINE in codes(got(quote="setQuantity(Math.max(1, parseInt(e.target.value) || 1)"))   # BEYOND: part of the line
    assert BR.R_MECH_CODE_LINE in codes(got(quote="setQuantity"))
    assert BR.R_MECH_CODE_LINE in codes(got(quote=""))
    assert BR.R_MECH_CODE_LINE in codes(got(line=2))                        # another line
    assert got(line=4, quote="export default a;") == []                     # AT the last text line
    assert got(line=5, quote="") != []                                      # the empty tail after the final newline: no quote
    assert BR.R_MECH_CODE_LINE in codes(got(line=6, quote="x"))             # BEYOND the end
    for line in (0, -1, "3", None, 3.0, True):
        assert BR.R_MECH_CODE_LINE in codes(got(line=line)), line
    for path in ("src/Nope.tsx", "../outside.ts", "/etc/hostname", "C:/Windows/win.ini", "src/../../x", "", None, "src/"):
        assert BR.R_MECH_CODE_LINE in codes(got(path=path)), path


def test_code_line_outside_the_repo_root_is_never_read():
    task = world()
    outside = task.parents[2].parent / "outside-n1-probe.ts"                # beside the project root, not in it
    outside.write_text(LINE + "\n", encoding="utf-8")
    try:
        assert outside.read_text(encoding="utf-8").strip() == LINE          # positive control: the file is there and holds the line
        for path in ("../outside-n1-probe.ts", "../../outside-n1-probe.ts", outside.as_posix()):
            got = BR.mechanism_problems(task, draft(mechanism=mech("confirmed", [code_basis(path=path, line=1)])))
            assert BR.R_MECH_CODE_LINE in codes(got), path
    finally:
        outside.unlink()


def test_run_basis_boundaries():
    task = world()

    def got(basis):
        return BR.mechanism_problems(task, draft(mechanism=mech("confirmed", [basis])))

    good = run_basis(task)
    assert got(good) == []                                                  # AT
    assert BR.R_MECH_RUN in codes(got({**good, "quote": "1 11 focus=yes!"}))               # BEYOND
    assert BR.R_MECH_RUN in codes(got({**good, "quote": " "}))
    assert BR.R_MECH_RUN in codes(got({**good, "case": "settle-other"}))                    # a capture of another case
    assert BR.R_MECH_RUN in codes(got({**good, "case": ""}))
    assert BR.R_MECH_RUN in codes(got({**good, "case": None}))
    assert BR.R_MECH_RUN in codes(got({**good, "capture": ""}))
    assert BR.R_MECH_RUN in codes(got({**good, "capture": "../" + good["capture"]}))
    assert BR.R_MECH_RUN in codes(got({**good, "capture": (task / good["capture"]).as_posix()}))
    assert BR.R_MECH_RUN in codes(got({**good, "capture": None}))
    png = capture(task, text=b"\x89PNG\r\n\x1a\n1 11 focus=yes", name="020-shot.png")
    assert BR.R_MECH_RUN in codes(got({**good, "capture": png}))
    (task / good["capture"]).write_text("edited after hashing", encoding="utf-8")
    assert BR.R_MECH_RUN in codes(got(good))


def test_run_basis_with_an_index_that_is_not_jsonl():
    task = world()
    entry = run_basis(task)
    (task / "work" / "evidence" / "manual" / CASE / "a1" / "captures.jsonl").write_text("not json", encoding="utf-8")
    assert BR.R_MECH_RUN in codes(BR.mechanism_problems(task, draft(mechanism=mech("confirmed", [entry]))))


def test_claims():
    task = world()
    b1, b2 = code_basis("b1"), run_basis(task, "b2")

    def got(claims, basis=(b1, b2), status="confirmed"):
        return BR.mechanism_problems(task, draft(mechanism=mech(status, list(basis), claims)))

    assert got([{"says": "a", "confirmed_by": ["b1", "b2"]}]) == []
    assert got([{"says": "pasting behaves the same", "confirmed_by": []}]) == []              # NOT verified is not a problem (FR-41)
    assert got([{"says": "x"}]) == []                                                          # absent confirmed_by reads as not verified
    assert codes(got([{"says": "a", "confirmed_by": ["b9"]}])) == [BR.R_MECH_CLAIM]            # an id that is not in `basis`
    assert codes(got([{"says": "a", "confirmed_by": [7]}])) == [BR.R_MECH_CLAIM]
    assert codes(got([{"says": "a", "confirmed_by": "b1"}])) == [BR.R_MECH_CLAIM]
    assert codes(got([{"says": "", "confirmed_by": []}])) == [BR.R_MECH_CLAIM]
    assert codes(got(["x"])) == [BR.R_MECH_CLAIM]
    claims = mech("confirmed", [b1], {"says": "a"})
    assert BR.R_MECH_CLAIM in codes(BR.mechanism_problems(task, draft(mechanism=claims)))      # claims not a list
    bad = code_basis("b3", quote="nope")
    both = got([{"says": "a", "confirmed_by": ["b1", "b3"]}], basis=(b1, bad))
    assert BR.R_MECH_CLAIM in codes(both) and BR.R_MECH_CODE_LINE in codes(both)               # cites an entry that does not stand
    person = {"id": "p1", "kind": "person", "quote": "they are one bug"}
    only = BR.mechanism_problems(task, draft(mechanism=mech("confirmed", [person], [{"says": "a", "confirmed_by": ["p1"]}])))
    assert codes(only) == [BR.R_MECH_NO_BASIS, BR.R_MECH_CLAIM]      # a `person` entry that names no dispatch does not stand (M1)
    assert BR.mechanism_problems(task, draft(mechanism=mech("unknown", [person], why="w"))) == []


def _with_dispatches(task, dispatches, call):
    """Run `call()` with the controller's state patched to hold `dispatches` (a story with an empty event journal)."""
    import controller as CT
    (task / "state").mkdir(exist_ok=True)
    (task / "state" / "events.jsonl").write_text("", encoding="utf-8")
    original = CT.Controller.state
    CT.Controller.state = lambda self: {"dispatches": dispatches}
    try:
        return call()
    finally:
        CT.Controller.state = original


def _said(reason="Merge 2 and 4: they are one bug, please.", scope=("TC-5", "TC-7"), **over) -> dict:
    return {"id": "S7-a-2", "stage": "S7", "person_words": True, "request_binding": {"reason": reason, "scope": list(scope)}, **over}


def _merged(entry):
    """A draft with two manifestations (cases TC-5, TC-7) and a confirmed cause on `entry` (a basis entry or a list of them)."""
    return draft(mechanism=mech("confirmed", entry if isinstance(entry, list) else [entry]),
                 manifestations=[man(), man(triage_row=ROW_B, case="TC-7")])


def test_person_basis_stands_only_on_the_named_dispatch():
    """M1 (I3, A1): a `person` entry NAMES its dispatch and stands only when (i) that dispatch is an S7 rework marked as the person's words,
    (ii) its scope covers the draft's cases, (iii) the quote (12+ non-space characters, squashed, casefolded) is in THAT dispatch's words.
    Invariant: a merge is accepted on the person's word only when the words were spoken about these bugs; the error goes toward split."""
    task = world()
    person = {"id": "p1", "kind": "person", "dispatch": "S7-a-2", "quote": "They  are\none BUG"}

    def got(entry, dispatches, **_):
        return codes(_with_dispatches(task, dispatches, lambda: BR.mechanism_problems(task, _merged(entry))))
    said = {"S7-a-2": _said()}
    assert got(person, said) == []                                                    # a covering scope and a real quote stand, alone
    assert got([person, code_basis("b9", quote="nope")], said) == [BR.R_MECH_CODE_LINE]     # a broken code_line is still a problem
    assert got(dict(person, quote=""), said) == [BR.R_MECH_NO_BASIS]                  # an empty quote
    assert got(dict(person, quote="   "), said) == [BR.R_MECH_NO_BASIS]
    assert got(dict(person, quote="they are two bugs"), said) == [BR.R_MECH_NO_BASIS]      # not in the record
    assert got(person, {}) == [BR.R_MECH_NO_BASIS]                                    # no record at all
    assert got(person, {"S7-a-2": _said(person_words=False, request_binding={"reason": "they are one bug"})}) == [BR.R_MECH_NO_BASIS]
    assert got(person, {"S7-a-2": _said(stage="S6")}) == [BR.R_MECH_NO_BASIS]         # only a rework of S7
    # the critic's two probes: words AGAINST the merge, a short quote
    against = {"S7-a-2": _said("split 2: these are different bugs, not one bug")}
    assert got(dict(person, quote="one bug"), against) == [BR.R_MECH_NO_BASIS]
    assert got(dict(person, quote="e"), against) == [BR.R_MECH_NO_BASIS]
    # the boundary AT and BEYOND the minimum: 11 non-space characters do not stand, 12 do (spaces do not count)
    twelve = "abcdefghijkl"
    spoken = {"S7-a-2": _said(f"Merge 2 and 4: {twelve} please")}
    assert got(dict(person, quote=twelve), spoken) == [] and got(dict(person, quote=twelve[:11]), spoken) == [BR.R_MECH_NO_BASIS]
    assert got(dict(person, quote="ab cd ef gh ij k"), {"S7-a-2": _said("x ab cd ef gh ij k x")}) == [BR.R_MECH_NO_BASIS]   # 11 + spaces
    # a right quote in the WRONG dispatch
    two = {"S7-a-2": _said("nothing about the merge here"), "S7-b-3": _said("Merge 2 and 4: they are one bug, please.", id="S7-b-3")}
    assert got(person, two) == [BR.R_MECH_NO_BASIS]                                   # S7-a-2 holds no such words, S7-b-3 does but is not named
    assert got(dict(person, dispatch="S7-b-3"), two) == []
    # a dispatch whose cases do not cover the draft
    assert got(person, {"S7-a-2": _said(scope=("TC-5",))}) == [BR.R_MECH_NO_BASIS]
    assert got(person, {"S7-a-2": _said(scope=())}) == [BR.R_MECH_NO_BASIS]
    # the old shape: no dispatch named -> does not stand, and the problem line says what is expected (FR-1)
    old = {"id": "p1", "kind": "person", "quote": "They are one BUG"}
    found = _with_dispatches(task, said, lambda: BR.mechanism_problems(task, _merged(old)))
    assert codes(found) == [BR.R_MECH_NO_BASIS] and "names no `dispatch`" in found[0][1] and "12 non-space" in found[0][1], found
    # a draft that names no case is covered by nothing
    nocase = draft(mechanism=mech("confirmed", [person]), case=None, triage_ref=None)
    assert codes(_with_dispatches(task, said, lambda: BR.mechanism_problems(task, nocase))) == [BR.R_MECH_NO_BASIS]
    (task / "state" / "events.jsonl").unlink()
    assert codes(BR.mechanism_problems(task, _merged(person))) == [BR.R_MECH_NO_BASIS]   # no event journal


def test_person_words_of_is_the_one_reader():
    """M1/K3: `place_answers.person_words_of` carries the mark test both the place answer and the merge basis use."""
    task = world()
    got = lambda d, name: _with_dispatches(task, d, lambda: PA.person_words_of(task, name))   # noqa: E731
    assert got({"S7-a-2": _said()}, "S7-a-2") == ({"stage": "S7", "words": "Merge 2 and 4: they are one bug, please.", "scope": ["TC-5", "TC-7"]}, "")
    assert got({"S7-a-2": _said(person_words=False, request_binding={"reason": "x"})}, "S7-a-2") == (None, "no_mark")
    assert got({"S7-a-2": _said(person_words=False, request_binding={"reason": "x", "person_words": True})}, "S7-a-2")[0]["words"] == "x"
    assert got({}, "S7-a-2") == (None, "no_record")


def test_cause_view_is_the_one_reader():
    """M3: the effective status, the one run-counting rule, the person's word and the links, from one reader."""
    task = world()
    b1, b2 = code_basis("b1"), run_basis(task, "b2")
    b3 = run_basis(task, "b3", start_state="")                                       # a run with no start state
    b4 = run_basis(task, "b4", start_state="FIELD erased  first")                   # the same state as b2, other spelling
    view = BR.cause_view(task, _merged([b1, b2, b3, b4]))
    assert (view["status"], view["by_code"], view["runs"], view["by_person"]) == ("confirmed", True, 1, False), view
    assert BR.cause_how_words(view) == "by the line of the application code that does it and by trying it from one starting state"
    b5 = run_basis(task, "b5", start_state="selected")
    assert BR.cause_how_words(BR.cause_view(task, _merged([b2, b5]))) == "by trying it from two starting states"
    only_empty = BR.cause_view(task, _merged([run_basis(task, "b6", start_state="")]))
    assert only_empty["runs"] == 0 and BR.cause_how_words(only_empty) == ""             # no start state is not a distinct start state
    # a confirmed cause whose basis stopped standing is NOT confirmed, with the one sentence
    lost = BR.cause_view(task, _merged([code_basis("b1", quote="nope")]))
    assert (lost["status"], lost["why"], lost["by_code"], lost["written"]) == ("unknown", BR.LOST_EVIDENCE, False, "confirmed"), lost
    # the person's word counts only when it stands
    person = {"id": "p1", "kind": "person", "dispatch": "S7-a-2", "quote": "they are one bug"}
    said = {"S7-a-2": _said()}
    view = _with_dispatches(task, said, lambda: BR.cause_view(task, _merged([person])))
    assert view["status"] == "confirmed" and view["by_person"] and BR.cause_how_words(view) == "on your word at gate B", view
    view = _with_dispatches(task, said, lambda: BR.cause_view(task, _merged([b1, dict(person, quote="short")])))
    assert view["status"] == "confirmed" and not view["by_person"], view               # confirmed by the line; the person's word does not count
    # no task root: written as written, a person entry never counts; no mechanism: {}; links read whatever the mechanism
    assert BR.cause_view(None, _merged([b1, person]))["by_person"] is False
    assert BR.cause_view(task, draft()) == {} and BR.cause_view(task, None) == {}
    assert BR.cause_links(draft(possibly_same_cause=[{"draft": "b.json", "why": " w  x "}, {"draft": ""}, "x"])) == [{"draft": "b.json", "why": "w x"}]
    assert BR.cause_view(task, draft(mechanism=mech("unverified", statement=""), why="w"))["status"] == "unknown"


def test_the_three_carriers_agree_on_the_run_count_and_the_standing():
    """M3 (a), (b): two `run` entries, one with a start state and one with none: the bug text, the packet row and the report record all say
    one starting state (a run with no start state is no distinct one); a basis that does not stand is unestablished in all three."""
    import gate_brief
    import traceability as T
    task = world()
    d = _merged([run_basis(task, "b2"), run_basis(task, "b3", start_state="")])
    text = BR.bug_text(d, cause=BR.cause_view(task, d))
    row = gate_brief._mechanism_row(task, d)
    _shows, cause, _linked = T._draft_cause_facts(task, d, [], {}, [])
    assert "Confirmed by trying it from one starting state." in text, text
    assert row["status"] == "confirmed" and row["how"]["runs"] == 1 and cause["runs"] == 1 and cause["status"] == "confirmed", (row, cause)
    d = _merged([code_basis("b1", quote="nope")])
    text = BR.bug_text(d, cause=BR.cause_view(task, d))
    _shows, cause, _linked = T._draft_cause_facts(task, d, [], {}, [])
    assert "Confirmed" not in text and gate_brief._mechanism_row(task, d)["status"] == "unknown" and cause["status"] == "unknown"


def test_bug_text_prints_from_the_view_and_round_trips_through_the_form_check():
    """M3 (b)/(c) and M4: the bug text never prints "Confirmed" for a basis that does not stand, says the person's word, and its
    `## Manifestations` lines carry each case so the filed bug passes `check_bug_form` (the text is what its refusal says to copy from)."""
    import validate_artifacts as V
    task = world()
    d = _merged([code_basis("b1", quote="nope")])
    text = BR.bug_text(d, cause=BR.cause_view(task, d))
    assert "Confirmed" not in text and "Cause not established: " + BR.LOST_EVIDENCE + "." in text, text
    person = {"id": "p1", "kind": "person", "dispatch": "S7-a-2", "quote": "they are one bug"}
    d = _merged([person])
    text = _with_dispatches(task, {"S7-a-2": _said()}, lambda: BR.bug_text(d, cause=BR.cause_view(task, d)))
    assert "Confirmed on your word at gate B." in text, text
    section = text.split("## Manifestations\n", 1)[1].splitlines()
    assert section[0].startswith("1. case TC-5; ") and section[1].startswith("2. case TC-7; "), section
    # bug text of a merged draft -> bug file -> check_bug_form clean
    fm = {"source_draft": "work/bug-drafts/m.json", "cases": ["TC-5", "TC-7"]}

    def form(body):
        errors: list = []
        V.check_bug_form(Path("BUG-1.md"), fm, body, errors, draft=d)
        return [e for e in errors if "Manifestations" in e or "Cause" in e or "'cases'" in e]
    assert form(text) == [], form(text)
    assert any("does not name the case TC-7" in e for e in form(text.replace("case TC-7; ", ""))), \
        "the negative control: a line without its case is refused"


def test_an_absorbed_manifestation_needs_no_seen_and_is_marked():
    """m4: an entry absorbed from a code-reading draft (from_draft, no row, no probe) is not asked for `start_state` and `seen`, and its
    summary line says it was found by reading the code."""
    task = world()
    absorbed = {"action": "reads the code at the line", "from_draft": "cr.json", "evidence": "src/BookDetailPage.tsx:3", "case": "TC-9",
                "red_test_none": "found by reading"}
    items = [man(), absorbed]
    assert mp(task, items) == [], mp(task, items)
    got = mp(task, [man(), {k: v for k, v in absorbed.items() if k != "evidence"}])
    assert BR.R_MAN_FIELDS in codes(got) and "evidence" in got[0][1]
    lines = BR.manifestation_summary(draft(manifestations=items))
    assert lines[1].endswith("(found by reading the code, not run)") and "found by reading" not in lines[0], lines
    run_entry = man(from_draft="cr.json", seen=None, start_state=None)       # a row entry is still asked for both
    assert BR.R_MAN_FIELDS in codes(mp(task, [run_entry]))


def test_must_not_be_refused_judgment_stays_with_the_role():
    task = world()
    cap = capture(task)
    entry = {"id": "b2", "kind": "run", "case": CASE, "capture": cap, "quote": "1 11 focus=yes", "start_state": "s"}
    probe = {"case": CASE, "capture": cap, "quote": "1 11 focus=yes"}
    d = draft(mechanism=mech("confirmed", [entry], [{"says": "a", "confirmed_by": ["b2"]}, {"says": "b", "confirmed_by": []}]),
              manifestations=[man(), man(triage_row=None, probe=probe, evidence=cap)])
    assert BR.mechanism_problems(task, d) == []                             # a run whose capture is also a manifestation's evidence
    assert BR.manifestation_problems(task, d, ROWS) == []                   # ... and some claims unverified, status still confirmed
    assert BR.mechanism_problems(task, draft(mechanism=mech("confirmed", [code_basis()]))) == []          # one code line, no run


# --- manifestation_problems ------------------------------------------------------------------------------------------------

def mp(task, items, rows=ROWS, **over):
    return BR.manifestation_problems(task, draft(manifestations=items, **over), rows)


def test_manifestations_shape():
    task = world()
    assert mp(task, [man()]) == [] and mp(task, [man(), man(triage_row=ROW_B, case="TC-7")]) == []
    assert BR.manifestation_problems(task, draft(manifestations=[]), ROWS) == []
    for bad in ("x", {"a": 1}, 3, None):
        assert codes(BR.manifestation_problems(task, draft(manifestations=bad), ROWS)) == [BR.R_MAN_SHAPE], bad
    assert codes(mp(task, [man(), "x"])) == [BR.R_MAN_SHAPE]
    for key in ("action", "start_state", "seen", "evidence"):
        got = mp(task, [man(**{key: ""})])
        assert codes(got) == [BR.R_MAN_FIELDS] and key in got[0][1], (key, got)
        assert codes(mp(task, [man(**{key: 5})])) == [BR.R_MAN_FIELDS], key


def test_manifestation_triage_row():
    task = world()
    assert mp(task, [man(triage_row="TC-5#obs1@a1")]) == []                  # the string form
    assert mp(task, [man(triage_row="TC-5#obs1")], triage_ref="TC-5#obs1") == []        # a bare instance covers every attempt
    assert codes(mp(task, [man(triage_row={"instance_id": "TC-5#obs1", "attempt_id": "a9"})])) == [BR.R_MAN_NO_ROW, BR.R_MAN_PRIMARY]
    assert codes(mp(task, [man(), man(triage_row={"instance_id": "TC-5#obsX", "attempt_id": "a1"})])) == [BR.R_MAN_NO_ROW]
    assert codes(mp(task, [man(), man(triage_row={"instance_id": "TC-9#obs1", "attempt_id": "a1"})])) == [BR.R_MAN_NOT_APP_BUG]
    assert codes(mp(task, [man()], rows=[])) == [BR.R_MAN_NO_ROW]
    assert codes(mp(task, [man()], rows="x")) == [BR.R_MAN_NO_ROW]
    assert codes(mp(task, [man(), man(triage_row=[1, 2])])) == [BR.R_MAN_NO_ROW]


def test_manifestation_source_exactly_one_except_the_absorbed_form():
    task = world()
    cap = capture(task)
    probe = {"case": CASE, "capture": cap, "quote": "1 11 focus=yes"}
    assert mp(task, [man(), man(triage_row=None, probe=probe, evidence=cap)]) == []
    assert codes(mp(task, [man(), man(probe=probe)])) == [BR.R_MAN_SOURCE]                  # both
    assert codes(mp(task, [man(), man(triage_row=None)])) == [BR.R_MAN_SOURCE]              # neither
    absorbed = man(triage_row=None, from_draft="qty-invalid-input-coerced.json", evidence="src/BookDetailPage.tsx:3",
                   red_test=None, red_test_none="read from the code")
    assert mp(task, [man(), absorbed]) == []                                                # the one exception (spec 3.2, last row)
    assert codes(mp(task, [man(), {**absorbed, "evidence": ""}])) == [BR.R_MAN_FIELDS, BR.R_MAN_SOURCE]    # no evidence: not absorbed
    assert codes(mp(task, [man(), {**absorbed, "from_draft": ""}])) == [BR.R_MAN_SOURCE]
    assert mp(task, [man(), {**absorbed, "probe": probe, "evidence": cap}]) == []            # from_draft may ride on a probe (spec 3.1)
    assert codes(mp(task, [man(), {**absorbed, "triage_row": ROW_B, "probe": probe}])) == [BR.R_MAN_SOURCE]


def test_manifestation_probe_boundaries():
    task = world()
    cap = capture(task)
    good = {"case": CASE, "capture": cap, "quote": "1 11 focus=yes"}

    def got(probe):
        return mp(task, [man(), man(triage_row=None, probe=probe, evidence=cap)])

    assert got(good) == []                                                  # AT
    assert codes(got({**good, "quote": "1 11 focus=yes!"})) == [BR.R_MAN_PROBE]            # BEYOND
    assert codes(got({**good, "case": "settle-other"})) == [BR.R_MAN_PROBE]
    assert codes(got({**good, "capture": "../" + cap})) == [BR.R_MAN_PROBE]
    assert codes(got({**good, "capture": ""})) == [BR.R_MAN_PROBE]
    for not_an_object in ("x", ["a"], 4):
        assert codes(got(not_an_object)) == [BR.R_MAN_PROBE], not_an_object
    (task / cap).write_text("edited after hashing", encoding="utf-8")
    assert codes(got(good)) == [BR.R_MAN_PROBE]


def test_manifestation_red_test():
    task = world()
    assert mp(task, [man(red_test=None, red_test_none="manual check only: not in the regression (P28)")]) == []
    assert codes(mp(task, [man(red_test=None)])) == [BR.R_MAN_RED_TEST]                     # neither
    assert codes(mp(task, [man(red_test_none="manual")])) == [BR.R_MAN_RED_TEST]            # both
    assert codes(mp(task, [man(red_test={"path": "t.py", "command": ""})])) == [BR.R_MAN_RED_TEST]
    assert codes(mp(task, [man(red_test={"path": "t.py"})])) == [BR.R_MAN_RED_TEST]
    assert codes(mp(task, [man(red_test="t.py -- pytest t.py")])) == [BR.R_MAN_RED_TEST]    # a draft's red test is a mapping
    assert codes(mp(task, [man(red_test=None, red_test_none="  ")])) == [BR.R_MAN_RED_TEST]


def test_first_manifestation_is_the_drafts_own_row():
    task = world()
    assert mp(task, [man()]) == []                                          # AT: equal keys
    got = mp(task, [man(triage_row=ROW_B), man()])
    assert codes(got) == [BR.R_MAN_PRIMARY] and "TC-5#obs1@a1" in got[0][1] and "TC-7#obs1@a1" in got[0][1], got
    cap = capture(task)
    probe_first = man(triage_row=None, probe={"case": CASE, "capture": cap, "quote": "1 11 focus=yes"}, evidence=cap)
    assert codes(mp(task, [probe_first, man()])) == [BR.R_MAN_PRIMARY]      # the first one is a probe, not the draft's row
    no_ref = BR.manifestation_problems(task, {**draft(manifestations=[man(triage_row=ROW_B)]), "triage_ref": None}, ROWS)
    assert no_ref == []                                                      # a draft with no `triage_ref` of its own: nothing to equal
    # t-2187 section 17: a bare instance and the full key of the same instance are ONE row (compare by instance when either side has no attempt)
    bare = draft(triage_ref="TC-5#obs1", manifestations=[man()])
    assert BR.manifestation_problems(task, bare, ROWS) == []
    bare_first = draft(manifestations=[man(triage_row="TC-5#obs1")])
    assert BR.manifestation_problems(task, bare_first, ROWS) == []
    other = draft(triage_ref="TC-7#obs1", manifestations=[man()])                             # another instance: still not the draft's own row
    assert codes(BR.manifestation_problems(task, other, ROWS)) == [BR.R_MAN_PRIMARY]
    other_attempt = draft(triage_ref="TC-5#obs1@a2", manifestations=[man()])                  # both name an attempt, and they differ
    assert codes(BR.manifestation_problems(task, other_attempt, ROWS)) == [BR.R_MAN_PRIMARY]


def test_code_reading_draft_is_not_asked_for_a_row_of_its_own():
    task = world()
    cr = {"title": "t", "impact": "money", "violates": "requirement:R-24", "evidence": "code-reading", "manifestations": []}
    assert BR.manifestation_problems(task, cr, ROWS) == [] and BR.mechanism_problems(task, cr) == []


def test_one_row_in_two_drafts_and_a_row_listed_twice_are_not_shape_errors():
    task = world()
    assert mp(task, [man(), man()]) == []                                    # one row listed twice in one draft: no error
    a = draft(manifestations=[man()])
    b = draft(manifestations=[man()], triage_ref=dict(ROW_B))
    assert BR.manifestation_problems(task, a, ROWS) == [] and BR.manifestation_refs(a) == BR.manifestation_refs(b) == [("TC-5#obs1", "a1")]


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-q", "-p", "no:cacheprovider"]))
