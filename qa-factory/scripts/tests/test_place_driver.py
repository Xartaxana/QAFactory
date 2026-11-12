"""test_place_driver.py - the S7 driver without the walker: lines, closers, scribe line, investigation line (spec t-1991, node U3a).

Run: python -B -m pytest -p no:cacheprovider scripts/tests/test_place_driver.py -q      or      python -B scripts/tests/test_place_driver.py

The Driver is stubbed the way test_manual_window.py does it (`Driver.__new__`, the few attributes the method reads); the stories are those of
test_place_answers.py (a register whose rows R-1 and R-2 contradict the code, the investigation fixture for the open targets). Fast: no role runs.
Mutation -> killing test (named, run once in the node's report):
  `s7_close_places` moved after `s7_investigation_gate` in `s7_close` -> test_close_places_before_investigation_gate
"""
import atexit
import contextlib
import io
import json
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import harness  # noqa: E402

import exploratory_findings as EF  # noqa: E402
import investigation as INV  # noqa: E402
import place_answers as PA  # noqa: E402
import s7_pretriage  # noqa: E402
import story_run  # noqa: E402
import test_place_answers as TPA  # noqa: E402

WALKER = "S7-qa-failure-analyst-1"
INVESTIGATION = "S7-qa-failure-analyst-2"
DISPATCHES = {WALKER: {"id": WALKER, "stage": "S7", "role": "qa-failure-analyst", "status": "accepted"},
              INVESTIGATION: {"id": INVESTIGATION, "stage": "S7", "role": "qa-failure-analyst", "status": "accepted",
                              "request_binding": {"purpose": "investigation"}}}
TEXTS = json.loads(PA.DATA_PATH.read_text(encoding="utf-8"))["gap_reasons"]


def driver(task: Path, dispatches=None, walk=None, gate=None):
    """A Driver that has nothing but what the S7 place methods read; `gate` replaces the investigation gate (a recorder)."""
    d = story_run.Driver.__new__(story_run.Driver)
    d.task_root, d.task, d.plugin = task, task.name, harness.PLUGIN_ROOT
    d.state = {"s7_walk": walk} if walk else {}
    shown = {"dispatches": dict(DISPATCHES if dispatches is None else dispatches)}
    d.controller_state = lambda: shown
    d.pipeline = lambda: {}
    if gate is not None:
        d.s7_investigation_gate = gate
    return d


def said(call):
    """(result, printed lines) of a call."""
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        result = call()
    return result, [line for line in out.getvalue().splitlines() if line]


def gaps(task: Path) -> dict:
    return {pid: line for pid, line in EF.read(task)["active"].items() if line["kind"] == "coverage_gap"}


class Gate:
    """A stand-in for `s7_investigation_gate`: it records the settle gaps the register held when it was called."""

    def __init__(self, task: Path, verdict: str = "wait"):
        self.task, self.verdict, self.seen = task, verdict, None

    def __call__(self):
        self.seen = sorted(gaps(self.task))
        return self.verdict, ""


class Rig:
    """The stage_S7 entry with a story that needs no analyst: the closer is recorded, nothing is closed."""

    def __init__(self, task: Path, gate: Gate, reasons: str, pre=None):
        self.driver = driver(task, dispatches={}, gate=gate)
        d = self.driver
        d.s7_closed_by_scribe = lambda state: False
        d.failures_to_triage = lambda: reasons
        d.closed = []
        d.close_by_code = lambda stage, reason, evidence, **kw: d.closed.append((kw.get("site"), reason)) or True
        self.pre, self.saved = pre, s7_pretriage.pretriage

    def run(self):
        s7_pretriage.pretriage = lambda root: self.pre
        try:
            return said(self.driver.stage_S7)
        finally:
            s7_pretriage.pretriage = self.saved


# --- the closers ------------------------------------------------------------------------------------------------------------------

def test_close_places_before_investigation_gate():
    task = TPA.story()
    gate = Gate(task)
    d = driver(task, gate=gate)
    said(lambda: d.s7_close([], "L"))
    assert gate.seen == ["req-R-1", "req-R-2"], gate.seen                      # E3.1: the gaps stood when the gate was asked
    assert gaps(task)["req-R-1"]["missing_prerequisite"] == "not settled by the analyst - " + TEXTS[0]
    assert gaps(task)["req-R-1"]["recorded_by"] == "code:place_answers.close_unsettled" and not INV.is_code_line(gaps(task)["req-R-1"])


def test_no_failures_gaps_register_places():
    task = TPA.story()
    gate = Gate(task)
    rig = Rig(task, gate, reasons="")
    _, printed = rig.run()
    assert gate.seen == ["req-R-1", "req-R-2"], gate.seen                      # E3.3, and before the gate (E3.1)
    for pid in ("req-R-1", "req-R-2"):
        assert gaps(task)[pid]["missing_prerequisite"] == "not settled by the analyst - " + TEXTS[3]
    gate.verdict = "proceed"
    rig.run()
    assert rig.driver.closed and rig.driver.closed[-1][0] == "s7.no_failures"
    assert len(gaps(task)) == 2 and len(EF.read(task)["lines"]) == 2          # a second entry writes nothing again


def test_pretriaged_gap_text():
    task = TPA.story()
    TPA.draft(task, "d1.json")
    gate = Gate(task, verdict="proceed")
    rig = Rig(task, gate, reasons="TC-1", pre={"closes": True, "kept": ["TC-1"], "left": {}, "notes": []})
    rig.run()
    assert rig.driver.closed[-1][0] == "s7.pretriaged" and gate.seen == ["req-R-1", "req-R-2"], (rig.driver.closed, gate.seen)
    assert gaps(task)["req-R-1"]["missing_prerequisite"] == "not settled by the analyst - " + TEXTS[4]
    assert gaps(task)["req-R-1"]["evidence_refs"][0]["path"] == "work/bug-drafts/d1.json"      # the draft stays beside the gap


def test_gap_reason_default_and_session_failure():
    task = TPA.story()
    assert driver(task).s7_gap_reason() == TEXTS[0]                              # text 1: the default
    assert driver(task, dispatches={}).s7_gap_reason() == TEXTS[0]
    assert driver(task, walk={WALKER: {"state": "ready"}}).s7_gap_reason() == TEXTS[0]
    assert driver(task, walk={WALKER: {"failed": "stand", "why": "down"}}).s7_gap_reason() == TEXTS[1]
    assert driver(task, walk={WALKER: {"failed": "session", "why": "x"}}).s7_gap_reason() == TEXTS[2]
    assert driver(task, walk={INVESTIGATION: {"failed": "stand"}}).s7_gap_reason() == TEXTS[0]   # an investigation is no triage
    assert driver(task, walk={"older": {"failed": "stand"}}).s7_gap_reason() == TEXTS[0]         # only the LAST triage dispatch counts
    assert driver(task).s7_gap_reason("no_failures") == TEXTS[3] and driver(task).s7_gap_reason("pretriaged") == TEXTS[4]
    assert all(t in PA._data()["gap_reasons"] for t in TEXTS)                    # close_unsettled accepts each


def test_places_error_one_line_and_close_still_runs():
    task = TPA.story()
    original = PA.places
    PA.places = lambda root: (_ for _ in ()).throw(RuntimeError("boom"))
    try:
        written, printed = said(lambda: driver(task).s7_close_places(TEXTS[0]))
        brief, brief_printed = said(lambda: driver(task).s7_place_lines(None))
    finally:
        PA.places = original
    assert written == [] and len(printed) == 1 and "boom" in printed[0] and "S7 goes on" in printed[0], printed
    assert len(brief_printed) == 1 and any("could not be computed whole" in line and "boom" in line for line in brief)
    assert not any("none in this run" in line for line in brief)                 # an exception never reads as none
    # an unreadable source: ONE printed line, the brief says so, and the close still gaps what it read (a draft; no register)
    task = TPA.story(register="## Register\n\n| R | Notes |\n|---|---|\n| R-1 | x |\n")       # no Requirement column: the register is unreadable
    TPA.draft(task, "d1.json")
    written, printed = said(lambda: driver(task).s7_close_places(TEXTS[0]))
    assert len([line for line in printed if "could not be computed whole" in line]) == 1, printed
    assert len(written) == 1 and list(gaps(task)) == ["draft-d1"], (written, list(gaps(task)))
    brief, brief_printed = said(lambda: driver(task).s7_place_lines(None))
    assert brief[0].startswith("The list of places could not be computed whole") and "draft-d1 | draft | open" in " ".join(brief)
    # the texts cannot be chosen / are wrong: one line, S7 goes on
    written, printed = said(lambda: driver(task).s7_close_places(""))
    assert written == [] and len([line for line in printed if "S7 goes on" in line]) == 1, printed


# --- the brief ------------------------------------------------------------------------------------------------------------------

def test_brief_names_places_and_answer_keys():
    task = TPA.story()
    TPA.write(task, TPA.ans("req-R-2", "not_a_bug", task))
    lines, _ = said(lambda: driver(task).s7_place_lines(None))
    text = "\n".join(lines)
    assert lines[0] == "Places to settle (2):", lines[0]
    assert any(line.startswith("req-R-1 | register | open | ") and "expectation named by the record: R-1 | where: " in line for line in lines)
    assert any(line.startswith("req-R-2 | register | settled | ") for line in lines)
    answers_line = next(line for line in lines if "`bug`" in line)               # the four answers and the four sources, one line
    for key in ("bug", "not_a_bug", "requirement_silent", "impossible", "requirement", "question", "person", "none"):
        assert f"`{key}`" in answers_line, key
    assert "settle-<place id>" in text and "manual_capture.py" in text and "ui|http" in text
    assert "place_answers.py\" list" in text and "--dispatch <your dispatch id>" in text
    # F10: the keys of the answer file and the walk entry are in the brief; the capture command carries its required flags (AR-8, AR-10)
    for words in ("`expectation` {`source`, `id`, `quote`}", "`seen` {`capture`", "`question`", "`why`", "`draft`", "kind: walk", "--steps-file",
                  "--method", "manual_capture.py\" ui|http --task-root"):
        assert words in text, words
    again, _ = said(lambda: driver(task).s7_place_lines("S7-qa-failure-analyst-9"))
    assert "--dispatch S7-qa-failure-analyst-9" in "\n".join(again)
    empty, _ = said(lambda: driver(TPA.story(register="## Register\n\n| R | Requirement (one verifiable statement) |\n|---|---|\n")).s7_place_lines(None))
    assert empty == ["Places to settle: none in this run"], empty              # the empty outcome is named, not silent


class Fake:
    """`places` / `settled_answer` replaced by n fake places (the cut is judged on the number, not on a story of 41 places)."""

    def __init__(self, n, width=0, state="open"):
        self.places = [{"id": "new-" + f"{i:02d}" + "x" * width, "sources": ["new"], "refs": {}, "title": f"t{i}", "expectation_hint": ""}
                       for i in range(n)]
        self.state = state

    def __enter__(self):
        self.saved = (PA.places, PA.settled_answer)
        PA.places = lambda root: {"places": self.places, "unreadable": []}
        PA.settled_answer = lambda root, pid: (None, self.state, "")
        return self

    def __exit__(self, *_exc):
        PA.places, PA.settled_answer = self.saved


def test_brief_cut_at_40():
    task = TPA.story()
    with Fake(40):
        whole, _ = said(lambda: driver(task).s7_place_lines(None))
    rows = [line for line in whole if line.startswith("new-")]
    assert len(rows) == 40 and not any(line.startswith("[and") for line in whole), (len(rows), whole[:3])     # at 40: whole
    with Fake(41):
        cut, _ = said(lambda: driver(task).s7_place_lines(None))
    rows = [line for line in cut if line.startswith("new-")]
    assert len(rows) == 40 and "[and 1 more: place_answers.py list]" in cut and "new-40" not in " ".join(cut)       # at 41: cut
    with Fake(55):
        many, _ = said(lambda: driver(task).s7_place_lines(None))
    assert "[and 15 more: place_answers.py list]" in many and "Places to settle (55):" in many


# --- the scribe ---------------------------------------------------------------------------------------------------------------

def test_scribe_brief_names_settled_and_unsettled():
    task = TPA.story()
    record = TPA.ans("req-R-1", "not_a_bug", task, source="requirement", expectation=TPA.req("R-1", "two decimals"))
    out = TPA.write(task, record)
    assert PA.settled_answer(task, "req-R-1")[1] == "settled", (out, PA.settled_answer(task, "req-R-1"))
    lines, _ = said(lambda: driver(task).s7_places_scribe_line())
    assert len(lines) == 1 and lines[0] == ("Places of S7 (2): settled 1 — req-R-1: not_a_bug (expectation: requirement R-1); "
                                           "not settled 1: req-R-2 (open)"), lines
    # the cut: whole AT 1500, cut BEYOND it (one place whose id is padded; the pointer replaces what does not fit)
    def line_with(width):
        with Fake(1, width=width):
            return said(lambda: driver(task).s7_places_scribe_line())[0][0]
    width = 0
    while len(line_with(width)) < 1500:
        width += 1
    assert len(line_with(width)) == 1500 and "[and" not in line_with(width), len(line_with(width))
    over = line_with(width + 1)
    assert "[and 1 more: place_answers.py list]" in over and len(over) < 1500
    with Fake(300, width=3):
        many = said(lambda: driver(task).s7_places_scribe_line())[0][0]
    shown = many.count("(open)")
    assert len(many) <= 1500 and many.endswith(f"[and {300 - shown} more: place_answers.py list]") and 0 < shown < 300, (shown, len(many))
    with Fake(0):
        assert said(lambda: driver(task).s7_places_scribe_line())[0] == ["Places of S7: none in this run"]
    original = PA.places
    PA.places = lambda root: (_ for _ in ()).throw(RuntimeError("boom"))
    try:
        broken, printed = said(lambda: driver(task).s7_places_scribe_line())
    finally:
        PA.places = original
    assert len(printed) == 1 and "could not be computed whole" in broken[0]


# --- the investigation ------------------------------------------------------------------------------------------------------------

def test_investigation_brief_excludes_settle():
    task = TPA.fixture_story()
    d = driver(task)
    TPA.write(task, TPA.ans("case-TC-006", "requirement_silent", task))
    lines, _ = said(d.investigation_lines)
    text = "\n".join(lines)
    assert ("The places of `place_answers.py list` were the triage's to settle; you do not walk the page for them and do not answer them."
            in lines)
    assert "- case-TC-006:" not in text, "a settled place is not offered to the investigation"
    assert "- case-TC-007:" in text, "a place nobody settled keeps the investigation road"


def test_settled_open_place_no_investigation_dispatch():
    task = TPA.fixture_story()
    budget = INV.load_budget()[0]
    pipeline = json.loads((task / "pipeline.json").read_text(encoding="utf-8"))
    assert INV.decision(task, {}, pipeline, budget)[0] == "dispatch"
    for target in INV.open_targets(task, budget)["unresolved"]:
        TPA.write(task, TPA.ans(target["id"], "requirement_silent", task))
    assert INV.decision(task, {}, pipeline, budget) == ("none", "")             # every open place settled: no pass, no "not investigated" gap
    launched = []
    d = driver(task)
    d.run_role = lambda *a, **k: launched.append((a, k))
    (verdict, suffix), _ = said(d.s7_investigation_gate)
    assert (verdict, suffix) == ("proceed", "") and launched == []


def main() -> int:
    tests = [(name, fn) for name, fn in sorted(globals().items()) if name.startswith("test_") and callable(fn) and fn.__module__ == __name__]
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
        TPA._cleanup_all()
    print(f"test_place_driver: {len(tests) - failed} passed, {failed} failed")
    return 1 if failed else 0


atexit.register(TPA._cleanup_all)

if __name__ == "__main__":
    sys.exit(main())
