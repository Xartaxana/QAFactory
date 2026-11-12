"""probe_by_code.py: `cause: judgment` - the code critic judges the facts of a probe the tool cannot read (t-1968 N2).

A mutation probe whose inverted check failed AT the mutated statement with a text neither the factory's marker nor a
`fires_as` row reads used to be "the factory's data to correct" (`cause: data_row`) and ended in a person's question. The place
of a failure is never a proof (a throw inside the statement's arguments sits on the same line), so now the record is
`incomplete` with `cause: judgment` and `judgment_facts` (the statement, the frame, the whole message, the failure text, cut),
and the code critic's `--judge ... --verdict fires|other_failure|cannot_judge --quote "<a line of the text>"` closes it:
`fires` -> `intended_failure` (`proved_by: critic`, a live receipt carrying the quote), `other_failure` -> `wrong_location`,
`cannot_judge` -> the record stays `incomplete` with the judgment written. The tool checks only DATA: the record exists, is of
these bytes, owes the judgment, the quote is a substring of the stored text after whitespace folding, the dispatch is open; whether
the quote proves the firing is the critic's word and the acceptor's to read (AR-29). A `cause: judgment` record is never "could
not run", judged or not.

Fast: tmp task root, no run; the judge is called as a function over a real controller state (its dispatch refusals are pinned unstubbed, F2).
Runnable alone (`python -B scripts/tests/test_probe_marker_judgment.py`) and collected by pytest."""
import hashlib
import json
import re
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness import GOOD, SCRIPTS, cleanup, temp_project  # noqa: E402

import assertion_detectors as AD  # noqa: E402
import contract as C  # noqa: E402
import probe_by_code as PBC  # noqa: E402
import proof_level as PL  # noqa: E402
import window_record as WR  # noqa: E402
from test_probe_marker import MARK, judge, row, ts_detail  # noqa: E402

IID = "cart_adds"
FILE = "tests/cart.spec.ts"
BYTES = b"test('adds', () => {});\n"
SHA = hashlib.sha256(BYTES).hexdigest()
TEXT = "Error: step 1: badge empty\n\n  Call log:\n    - waiting for locator('.badge')\n    - expected 0, received 1\n"
MESSAGE = "step 1: badge empty"


def facts(text: str = TEXT, message: str = MESSAGE, frame: str = "    at tests/cart.spec.ts:43:79") -> dict:
    return PBC.judgment_facts(
        {"evidence_ref": "work/ev.xml"},
        {"status": "failed", "problems": [{"kind": "failure", "message": message, "text": text}]},
        {"frame": frame, "location": FILE + ":43", "failure_kind": "assertion"},
        {"file": FILE, "line": 43, "end_line": 43, "statement_before": "expect(a).toHaveCount(0);",
         "statement_after": "expect(a, ['qa-probe', 'abc'].join('-') + ' ' + m).not.toHaveCount(0);",
         "statement_inverted": "expect(a, m).not.toHaveCount(0);", "message_marker": MARK, "pair_id": "T2", "fires_as": "x"})


CRITIC = {"id": "D1", "status": "running", "stage": "S5", "role": "qa-code-critic", "scope": ["TC-1"]}


def controller_state(root: Path, *rows: dict, story: str = "T-1") -> None:
    """The REAL `state/controller.json` of the story under the project's artifact root: what `find_active_dispatch` reads (F2)."""
    path = root / "qa-factory" / "artifacts" / story / "state" / "controller.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"dispatches": {row["id"]: row for row in rows}}), encoding="utf-8")


def world(tmp_path, monkeypatch, *, verdict="incomplete", cause="judgment", judgment=None, text=TEXT, restore=True, open_dispatch=True,
          dispatches=None):
    """A project with the test file, a task root with a manifest row, the probe record and (unstubbed) the story's controller state with
    the critic's open dispatch `D1` (`dispatches` replaces its rows; `open_dispatch=False` leaves it closed); returns (root, task, record path)."""
    root, task = tmp_path / "proj", tmp_path / "task"
    (root / "tests").mkdir(parents=True)
    (root / FILE).write_bytes(BYTES)
    (task / "work").mkdir(parents=True)
    (task / "work" / "automation-manifest.json").write_text(
        json.dumps({"tests": [{"instance_id": IID, "file": FILE, "case": "TC-1"}]}), encoding="utf-8")
    path = PL.probe_record_path(task, IID)
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {"schema_version": 1, "probe_tool": "probe_by_code.py", "task": "T-1", "dispatch_id": "D1", "instance_id": IID,
              "case": "TC-1", "test_node": FILE + "::adds", "verdict": verdict, "mutation": "invert", "mutation_kind": "assertion",
              "proof_level": "live", "failure_kind": None, "expected_location": FILE + ":43", "actual_location": None,
              "expected_reason": "probe-cart_adds invert: expect(a)", "actual_reason": None, "observed": {},
              "test_file_sha256": SHA, "mutation_detail": {"file": FILE}, "notes": ["the run failed at the mutated statement"],
              "restore": {"verified": True, "sha256": SHA} if restore else None, "language": "typescript",
              "record": path.relative_to(task).as_posix(), "evidence_refs": [], "cause": cause, "judgment_facts": facts(text)}
    if judgment:
        record["judgment"] = judgment
    path.write_text(json.dumps(record), encoding="utf-8")

    controller_state(root, *(dispatches if dispatches is not None else [CRITIC if open_dispatch else dict(CRITIC, status="done")]))
    monkeypatch.setattr(PL, "binding_facts", lambda *a, **k: {"case_version": "1", "test_content_hash": SHA,
                                                              "source_revision": "r1", "build_id": "b1"})
    return root, task, path


def judge_it(root, task, verdict="fires", quote="badge empty", why="", dispatch="D1"):
    return PBC.judge_record(task, root, IID, dispatch, verdict, quote, why)


def refusal(root, task, **kw) -> str:
    try:
        judge_it(root, task, **kw)
    except PBC.Refusal as exc:
        return str(exc)
    raise AssertionError("expected a refusal")


def stored(path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


# --- the judge table: the place is never a proof -----------------------------------------------------------

def test_unknown_text_is_judgment_not_a_phrase_match():
    detail, spec = ts_detail()
    for text in ("Error: step 1: x\n\nan unknown wording nobody listed", "Error: boom", "the check fired as planned"):
        got = judge(row("failed", "", text), detail, spec)
        assert got["verdict"] == "incomplete" and got["cause"] == "judgment" and "proved_by" not in got, text
        assert PBC.JUDGE_DOOR in got["note"]
    empty = judge(row("failed", "", ""), detail, spec)       # no text at all: nothing to judge - the tool's gap (the caller writes `tooling`)
    assert empty["verdict"] == "incomplete" and "cause" not in empty and "proved_by" not in empty, empty
    fires = AD.assertion_detectors()["typescript"]["assertions"][0]["invert"][0]["fires_as"]
    library = judge(row("failed", "", "Error: expect(locator).toHaveCount(expected) failed"), dict(detail, fires_as=fires), spec)
    assert library["verdict"] == "incomplete" and library["cause"] == "judgment" and "proved_by" not in library   # N3b: a matching library wording is judgment
    control = judge(row("failed", "", f"Error: {MARK} step 1: x"), detail, spec)
    assert (control["verdict"], control["proved_by"]) == ("intended_failure", "marker")      # the positive control: the token proves


def test_place_alone_is_not_a_proof():
    """E2.1/E2.2: a failure AT the statement's line with a throw inside its arguments or an action's timeout is judgment, never proof."""
    detail, spec = ts_detail()
    for message, text in (("", "TimeoutError: locator.click: Timeout 30000ms exceeded.\n  at tests/cart.spec.ts:43:12"),
                          ("step 1: badge empty", ""),
                          ("", "boom\n  > 43 | expect(catalog.cartBadge, m).not.toHaveCount(0);\n     at tests/cart.spec.ts:43:79")):
        got = judge(row("failed", message, text), detail, spec)
        assert (got["verdict"], got.get("cause")) == ("incomplete", "judgment"), (message, text)
    errored = judge(row("error", "boom", "setup failed", kind="error"), detail, spec)
    assert (errored["verdict"], errored.get("cause")) == ("incomplete", "judgment")            # N4 (F3): an error row WITH text goes to the critic too


def test_judgment_facts_shape_and_cut():
    got = facts()
    assert set(got) == {"file", "line", "end_line", "statement_before", "statement_after", "statement_inverted", "frame", "location",
                        "column", "location_hit", "frames", "status", "message", "failure_text", "message_marker", "fires_as_pair",
                        "evidence_ref", "rows", "rows_cut", "check_key", "model", "author_green"}
    assert (got["check_key"], got["model"], got["author_green"]) == (None, None, None)     # N4: written null; their producer is P4a (t-2064 par.11.3)
    assert got["rows"] == [{"test_id": None, "status": "failed", "message": MESSAGE, "failure_text": TEXT}] and got["rows_cut"] == 0
    assert got["location_hit"] is True and got["frames"] == []        # N3b: `_location_hits`' answer (43 is inside 43..43), a fact; no entry: no frames
    assert PBC.judgment_facts({}, {"status": "failed", "problems": []}, {"location": FILE + ":99"},
                              {"file": FILE, "line": 43, "end_line": 43})["location_hit"] is False
    assert PBC.judgment_facts({}, {"status": "failed", "problems": []}, {}, {})["location_hit"] is False     # no location, no line: never a crash
    assert got["statement_inverted"] == "expect(a, m).not.toHaveCount(0);" and "qa-probe" in got["statement_after"]   # F5: the plain one too
    assert (got["column"], got["location"], got["message"], got["failure_text"]) == (79, FILE + ":43", MESSAGE, TEXT)
    assert "verdict" not in got and facts(frame="")["column"] is None
    at = facts(text="x" * PBC.FAILURE_TEXT_MAX)["failure_text"]
    beyond = facts(text="x" * (PBC.FAILURE_TEXT_MAX + 1))["failure_text"]
    assert len(at) == PBC.FAILURE_TEXT_MAX and "…" not in at                                     # AT the limit: whole
    assert len(beyond) == PBC.FAILURE_TEXT_MAX and beyond.count("…") == 1                        # BEYOND: cut around ONE mark, the mark counts
    assert PBC.facts_sha(got) == PBC.facts_sha(dict(got)) and PBC.facts_sha(got) != PBC.facts_sha(facts(text="other"))


def test_rows_record_cause_judgment_with_facts():
    """`_judge_rows`: the row that is owed a judgment makes the record `cause: judgment` + facts; any other `incomplete` is tooling."""
    spec = PBC.parse_node("src/sum.test.ts::adds")
    detail = {"language": "typescript", "candidates": [3], "at": None, "line": 3, "end_line": 5}
    request = {"instance_contracts": {"adds": {"file": "src/sum.test.ts", "report_test_id": "sum.test.ts::adds", "classname_match": "file_suffix"}},
               "command": {"argv": ["npx", "playwright", "test"]}}
    old_judge, old_site = PBC.judge_probe_row, PBC.reporters.assertion_site

    def run(cause):
        record = {"task": "T", "notes": [], "expected_location": "src/sum.test.ts:3", "expected_reason": "m", "verdict": "not_executed"}

        def stub(r, site, entry, detail_, *, among, argv):
            got = {"verdict": "incomplete", "actual_location": None, "actual_reason": None, "mismatches": [], "note": "", "observed": {}}
            if cause:
                got["cause"] = cause
            return got
        PBC.judge_probe_row, PBC.reporters.assertion_site = stub, lambda *a, **k: {"location": "src/sum.test.ts:3", "frame": "at a.ts:3:9"}
        try:
            PBC._judge_rows(Path("."), record, [{"test_id": "sum.test.ts::adds", "status": "failed",
                                                          "problems": [{"kind": "failure", "message": "m", "text": "t"}]}],
                                     "junit-xml", spec, detail, request, Path("x"), ["adds"], True)
        finally:
            PBC.judge_probe_row, PBC.reporters.assertion_site = old_judge, old_site
        return record
    owed = run("judgment")
    assert (owed["cause"], owed["language"], owed["judgment_facts"]["failure_text"], owed["judgment_facts"]["column"]) == ("judgment", "typescript", "t", 9)
    other = run(None)
    assert other["cause"] == "tooling" and "judgment_facts" not in other                         # the tool's gap carries no facts


# --- the judge: effects ------------------------------------------------------------------------------------

def test_judge_fires_writes_receipt_and_proved_by_critic(tmp_path, monkeypatch):
    root, task, path = world(tmp_path, monkeypatch)
    got = judge_it(root, task, "fires", "waiting for  locator('.badge')")
    assert (got["verdict"], got["proved_by"], got["failure_kind"]) == ("intended_failure", "critic", "assertion")
    assert (got["actual_location"], got["actual_reason"]) == (got["expected_location"], got["expected_reason"])
    judgment = got["judgment"]
    assert (judgment["verdict"], judgment["by"], judgment["quote"], judgment["facts_sha"]) == (
        "fires", "D1", "waiting for  locator('.badge')", PBC.facts_sha(got["judgment_facts"]))
    receipt = json.loads((task / got["receipt"]["path"]).read_text(encoding="utf-8"))
    assert (receipt["proved_by"], receipt["judgment_quote"]) == ("critic", "waiting for  locator('.badge')")
    assert stored(path)["verdict"] == "intended_failure" and PL.probe_owes_judgment(task, IID, SHA) == ""
    assert got["window_probe"]["proved_by"] == "critic"


def test_judge_other_failure_is_wrong_location(tmp_path, monkeypatch):
    root, task, path = world(tmp_path, monkeypatch)
    got = judge_it(root, task, "other_failure", "expected 0, received 1")
    assert (got["verdict"], got["actual_location"], got["actual_reason"], got["mismatches"]) == (
        "wrong_location", FILE + ":43", "expected 0, received 1", ["reason"])
    assert got["judgment"]["verdict"] == "other_failure" and got["receipt"] is None


def test_cannot_judge_is_not_could_not_run(tmp_path, monkeypatch):
    root, task, path = world(tmp_path, monkeypatch)
    got = judge_it(root, task, "cannot_judge", "", why="the text names no check")
    assert (got["verdict"], got["cause"], got["judgment"]["why"], got["receipt"]) == ("incomplete", "judgment", "the text names no check", None)
    assert PL.probe_could_not_run(task, IID, SHA) is False                                      # R5: judged or not, never "could not run"
    assert PL.probe_owes_judgment(task, IID, SHA) == "cannot_judge"
    assert PL.probe_record_state(task, IID, SHA)["judgment"] == "cannot_judge"


def test_unjudged_is_not_could_not_run(tmp_path, monkeypatch):
    root, task, path = world(tmp_path, monkeypatch)
    assert PL.probe_could_not_run(task, IID, SHA) is False and PL.probe_owes_judgment(task, IID, SHA) == "unjudged"
    assert PL.probe_owes_judgment(task, IID, "0" * 64) == "" and PL.probe_owes_judgment(task, IID, "") == ""     # other bytes / empty hash
    world_tooling = stored(path)
    world_tooling["cause"] = "tooling"
    path.write_text(json.dumps(world_tooling), encoding="utf-8")
    assert PL.probe_could_not_run(task, IID, SHA) is True and PL.probe_owes_judgment(task, IID, SHA) == ""    # the control: tooling still is


def test_could_not_run_reads_judgment_through_record_state(tmp_path, monkeypatch):
    """The predicate takes the cause from `probe_record_state` (AR-13), not from a record read of its own."""
    seen = []

    def state(cause):
        def stub(*a, **k):
            seen.append(cause)
            return {"state": "incomplete", "cause": cause, "refused": "", "judgment": ""}
        return stub
    for cause, expected in (("judgment", False), ("tooling", True)):
        monkeypatch.setattr(PL, "probe_record_state", state(cause))
        assert PL.probe_could_not_run(tmp_path / "no-such-task", IID, SHA) is expected
    assert seen == ["judgment", "tooling"]


def test_judgment_writes_no_receipt_until_fires(tmp_path, monkeypatch):
    for verdict, quote, why in (("cannot_judge", "", "unclear"), ("other_failure", "badge empty", "")):
        root, task, path = world(tmp_path / verdict, monkeypatch)
        judge_it(root, task, verdict, quote, why)
        assert not (task / "work" / "sensitivity-receipts").exists(), verdict
    root, task, path = world(tmp_path / "unverified", monkeypatch, restore=False)
    got = judge_it(root, task, "fires", "badge empty")
    assert got["verdict"] == "intended_failure" and got["receipt"] is None                      # an unverified restore: no receipt (as the probe)


# --- the judge: refusals -----------------------------------------------------------------------------------

def test_judge_refusals_name_the_door(tmp_path, monkeypatch):
    messages = {}
    root, task, path = world(tmp_path / "a", monkeypatch)
    path.unlink()
    messages["no record"] = refusal(root, task)
    root, task, path = world(tmp_path / "b", monkeypatch)
    (root / FILE).write_bytes(BYTES + b"// edited\n")
    messages["other bytes"] = refusal(root, task)
    root, task, path = world(tmp_path / "c", monkeypatch, verdict="no_failure", cause="")
    messages["owes none"] = refusal(root, task)
    root, task, path = world(tmp_path / "d", monkeypatch, judgment={"verdict": "cannot_judge", "why": "w"})
    messages["second"] = refusal(root, task)
    root, task, path = world(tmp_path / "e", monkeypatch)
    messages["verdict word"] = refusal(root, task, verdict="maybe")
    messages["empty quote"] = refusal(root, task, quote="  ")
    messages["long quote"] = refusal(root, task, quote="x" * (PBC.JUDGE_QUOTE_MAX + 1))
    messages["quote not in text"] = refusal(root, task, quote="a line the run never printed")
    messages["cannot_judge without why"] = refusal(root, task, verdict="cannot_judge", quote="")
    messages["long why"] = refusal(root, task, verdict="cannot_judge", quote="", why="w" * (PBC.JUDGE_WHY_MAX + 1))
    root, task, path = world(tmp_path / "f", monkeypatch, open_dispatch=False)
    messages["dispatch"] = refusal(root, task)
    assert len(messages) == 11
    before = path.read_bytes()
    for name, text in messages.items():
        assert "Nothing was written" in text and "probe_by_code.py" in text, (name, text)       # every refusal names a command and the state
    assert path.read_bytes() == before                                                          # and nothing was written


def test_quote_not_in_text_refused(tmp_path, monkeypatch):
    root, task, path = world(tmp_path, monkeypatch)
    before = path.read_bytes()
    assert "not in the stored message or failure text" in refusal(root, task, quote="a line the run never printed")
    assert "not in the stored message" in refusal(root, task, quote="expected 0, received 2")   # a near miss is a miss
    assert path.read_bytes() == before


def test_quote_whitespace_folded(tmp_path, monkeypatch):
    root, task, path = world(tmp_path, monkeypatch)
    got = judge_it(root, task, "other_failure", "  - expected 0,\n   received   1  ")          # both sides folded
    assert got["verdict"] == "wrong_location"
    # limits AT and BEYOND: the text is stored whole up to the cut; a quote from beyond it is refused
    long_text = "head line\n" + "y" * (PBC.FAILURE_TEXT_MAX - 20) + "\nTAIL-MARK"
    root, task, path = world(tmp_path / "at", monkeypatch, text=long_text)
    assert len(stored(path)["judgment_facts"]["failure_text"]) == len(long_text) <= PBC.FAILURE_TEXT_MAX
    assert judge_it(root, task, "other_failure", "TAIL-MARK")["verdict"] == "wrong_location"      # AT the limit: the last line is there
    middle = "head line\n" + "y" * 9000 + "\nMIDDLE-MARK\n" + "y" * 9000 + "\nTAIL-MARK"
    root, task, path = world(tmp_path / "beyond", monkeypatch, text=middle)
    assert "not in the stored" in refusal(root, task, quote="MIDDLE-MARK")                       # BEYOND: the middle is cut, a quote from it is gone
    assert judge_it(root, task, "other_failure", "TAIL-MARK")["verdict"] == "wrong_location"      # ...and the tail (the raising line) survives (N4)
    root, task, path = world(tmp_path / "q300", monkeypatch, text="q" * PBC.JUDGE_QUOTE_MAX)
    assert judge_it(root, task, "other_failure", "q" * PBC.JUDGE_QUOTE_MAX)["verdict"] == "wrong_location"   # AT 300
    root, task, path = world(tmp_path / "w300", monkeypatch)
    assert judge_it(root, task, "cannot_judge", "", "w" * PBC.JUDGE_WHY_MAX)["judgment"]["why"] == "w" * PBC.JUDGE_WHY_MAX


def test_second_judgment_refused(tmp_path, monkeypatch):
    root, task, path = world(tmp_path, monkeypatch)
    judge_it(root, task, "cannot_judge", "", "unclear")
    written = path.read_bytes()
    assert "never rewritten" in refusal(root, task, verdict="fires")
    assert path.read_bytes() == written                                                         # a written judgment is never rewritten
    root, task, path = world(tmp_path / "fired", monkeypatch)
    judge_it(root, task, "fires")
    assert "owes no judgment" in refusal(root, task, verdict="other_failure")


def test_other_bytes_refused(tmp_path, monkeypatch):
    root, task, path = world(tmp_path, monkeypatch)
    (root / FILE).write_bytes(BYTES + b"// a later edit\n")
    assert "other bytes" in refusal(root, task)
    (root / FILE).unlink()
    assert "other bytes" in refusal(root, task)                                                 # a test that cannot be read counts for nothing


@pytest.mark.parametrize("rows,needle", [
    ([dict(CRITIC, id="S5-qa-automator-1", role="qa-automator")], "qa-automator dispatch, not the code critic's"),   # the test's author
    ([dict(CRITIC, stage="S6")], "S6 dispatch"),                                                                        # an S6 one (`s6_reprove`)
    ([dict(CRITIC, scope=["OTHER"])], "does not cover case TC-1"),                                                      # a critic of another window
    ([dict(CRITIC, scope=[])], "does not cover case TC-1"),
    ([{"id": "D1", "status": "running"}], "cannot be read"),                                                            # an unreadable row
    ([dict(CRITIC, role="", stage="")], "cannot be read"),
    ([dict(CRITIC, scope="TC-1")], "cannot be read"),                                                                   # a scope that is no list
    ([], "is not open"),                                                                                                # no running dispatch at all
])
def test_judge_dispatch_must_be_the_critics_open_s5_one(tmp_path, monkeypatch, rows, needle):
    """F2: the answer of `find_active_dispatch` is only "there is one"; the row must be the code critic's S5 dispatch of the record's case.
    Unstubbed: the world writes a real controller state. Each refusal names the door and writes nothing."""
    root, task, path = world(tmp_path, monkeypatch, dispatches=rows)
    before = path.read_bytes()
    text = refusal(root, task, dispatch=rows[0]["id"] if rows else "D1")
    assert needle in text and PBC.JUDGE_DOOR in text and "Nothing was written" in text, text
    assert path.read_bytes() == before


def test_judge_dispatch_other_story_or_unreadable_controller_refused(tmp_path, monkeypatch):
    root, task, path = world(tmp_path, monkeypatch, dispatches=[])
    controller_state(root, CRITIC, story="T-2")                                                  # the critic runs in ANOTHER story
    assert "is not open" in refusal(root, task)
    broken = root / "qa-factory" / "artifacts" / "T-1" / "state" / "controller.json"
    broken.parent.mkdir(parents=True, exist_ok=True)
    broken.write_text("{not json", encoding="utf-8")                                             # an unreadable controller refuses, never passes
    assert "Nothing was written" in refusal(root, task)
    assert stored(path)["verdict"] == "incomplete" and "judgment" not in stored(path)


def test_judge_through_parent_retry_ancestor_still_passes(tmp_path, monkeypatch):
    """F2 edge: the critic's own id was resumed as a `parent_retry` dispatch; the reader resolves it and the row checked is the open one's."""
    rows = [dict(CRITIC, id="D1", status="stale"), dict(CRITIC, id="D2", parent_retry="D1")]
    root, task, path = world(tmp_path, monkeypatch, dispatches=rows)
    assert judge_it(root, task, "fires", dispatch="D1")["verdict"] == "intended_failure"          # the control: the same chain, a critic
    other = [dict(CRITIC, id="D1", status="stale", role="qa-automator"), dict(CRITIC, id="D2", role="qa-automator", parent_retry="D1")]
    root, task, path = world(tmp_path / "author", monkeypatch, dispatches=other)
    assert "qa-automator" in refusal(root, task, dispatch="D1")                                  # an author's chain is still the author's


def test_publish_binding_off_target_is_not_proven(tmp_path, monkeypatch):
    """F3: a probe of another line publishes its receipt on the row but binds NO `proven`; an on-target probe binds it."""
    root, task, path = world(tmp_path, monkeypatch)
    got = judge_it(root, task, "fires")
    seen = []

    def put(task_id, fragment):
        seen.append(fragment)
        return SimpleNamespace(returncode=0, stdout="ok\n", stderr="")
    monkeypatch.setattr(PBC, "_put_fragment", put)
    off = dict(got, obligation_ids=["O1"], target={"is_assertion_id": False, "line": 43, "assertion_id": "tests/cart.spec.ts:9"})
    on = dict(got, obligation_ids=["O1"], target={"is_assertion_id": True, "line": 43, "assertion_id": "tests/cart.spec.ts:43"})
    for record in (off, on):
        PBC.publish_binding("T-1", task, record)
    off_fragment, on_fragment = seen
    assert "sensitivity" not in off_fragment["obligation_bindings"][0] and "probe_receipt_ref" not in off_fragment["obligation_bindings"][0]
    assert off_fragment["tests"][0]["sensitivity_proof"]["receipt_ref"]["path"]                  # the row keeps its proof: the window's off-target door
    assert off["publish"]["bindings"][0]["receipt"].startswith("not bound as proven: the probe broke line 43")
    assert on_fragment["obligation_bindings"][0]["sensitivity"] == "proven" and on["publish"]["bindings"][0]["receipt"] == "set"


def test_judge_cli_refuses_s6_close_and_missing_flags(capsys):
    for args, needle in ((SimpleNamespace(s6_close=True, task="T-1", dispatch="", judge=IID), "--s6-close"),
                         (SimpleNamespace(s6_close=False, task="", dispatch="", judge=IID), "required")):
        try:
            PBC._judge_cli(args)
        except SystemExit as exc:
            assert exc.code == 2
        out = json.loads(capsys.readouterr().out)
        assert out["status"] == "refused" and needle in out["error"] and PBC.JUDGE_DOOR in out["error"]


# --- the window, the delivery, S6 --------------------------------------------------------------------------

def test_window_note_names_judge_door():
    """`build`: an owed green item whose record is unjudged gets the critic's door as the tail of the `probe is missing` line."""
    import test_probe_gap_word as G
    project = G.temp_project("qa-probe-n2-note-")
    G.use_project(project)
    try:
        task = G.gap_story(project, record=None, word=None)
        G.probe_record(task, verdict="incomplete", cause="judgment")
        _window, notes = G.built(task)
        tails = [n[2] for n in notes if n[0] == G.IID and n[1] == "probe"]
        assert tails and all(PBC.JUDGE_DOOR in t and WR.UNJUDGED_NOTE in t for t in tails), tails
        assert "probe_gap" not in G.item_of(_window)                                            # the factory names no gap
        G.probe_record(task, verdict="incomplete", cause="tooling", language="typescript")      # the control: tooling keeps the old door
        tails = [n[2] for n in G.built(task)[1] if n[0] == G.IID and n[1] == "probe"]
        assert tails and all(PBC.JUDGE_DOOR not in t for t in tails)
    finally:
        G.cleanup(project)


def test_sent_back_receipt_still_written_with_unjudged_record():
    """E2.12 / t-1603: a rejected instance's `probe is missing` line still matches with its new tail."""
    line = f"{IID}: {C.PROBE_MISSING_ERROR} — {WR.UNJUDGED_NOTE}{PBC.JUDGE_DOOR}"
    window = {"instances": [{"instance_id": IID, "review": {"verdict": "rejected"}},
                            {"instance_id": "other", "review": {"verdict": "approved"}}]}
    assert WR._sent_back_lines(window, [line]) == [line]
    assert WR._sent_back_lines(window, [line.replace(IID, "other", 1)]) == []                   # the control: not a rejected instance


def test_window_closes_on_fires_without_person_word(tmp_path, monkeypatch):
    root, task, path = world(tmp_path, monkeypatch)
    got = judge_it(root, task, "fires")
    block = WR._probe_from_receipt(json.loads((task / got["receipt"]["path"]).read_text(encoding="utf-8")),
                                   got["receipt"], {"obligation_ids": []})
    assert (block["verdict"], block["proved_by"]) == ("intended_failure", "critic")
    item = {"instance_id": IID, "input_hash": SHA, "outcome": "passed"}
    assert WR.probe_gap_block(task, item, ["TC-1"], {}) is None                                 # no word, no gap: the receipt is the proof
    assert PL.probe_could_not_run(task, IID, SHA) is False


def test_cannot_judge_left_item_is_factory_owned():
    import check_delivery
    root = temp_project("qa-n2-owned-")
    try:
        art = root / "qa-factory" / "artifacts" / "QA-1"
        shutil.copytree(GOOD, art)
        mpath = art / "work" / "automation-manifest.json"
        data = json.loads(mpath.read_text(encoding="utf-8"))
        test = data["tests"][0]
        test["critic_verdict"] = "unverified"
        test["sensitivity_proof_missing_reason"] = "probe_by_code.py: incomplete - judged cannot_judge"
        mpath.write_text(json.dumps(data), encoding="utf-8")
        source = b"def test_coupon():\n    assert 1 + 1 == 2\n"
        (root / test["file"]).write_bytes(source)
        iid = C.test_instance_id(test)
        record = {"schema_version": 1, "probe_tool": "probe_by_code.py", "instance_id": iid, "verdict": "incomplete",
                  "cause": "judgment", "judgment": {"verdict": "cannot_judge", "why": "unclear"},
                  "test_file_sha256": hashlib.sha256(source).hexdigest(), "notes": ["x"], "recorded_at": "2026-11-05T10:00:00+00:00"}
        out = PL.probe_record_path(art, iid)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(record), encoding="utf-8")
        doc = check_delivery.assess(art)
        assert [(i["kind"], len(i["tests"])) for i in doc["left_items"] if i["counts"]] == [("review_unverified_factory", 1)]
        assert [(f["code"], f["entity"], f["owner"]) for f in doc["factory_findings"] if f["code"] == "PROBE_NOT_JUDGED"] == [
            ("PROBE_NOT_JUDGED", iid, "factory")]
        assert (doc["delivery_verdict"], doc["delivery_ready"]) == ("after_checks", False)
    finally:
        cleanup(root)


def test_s6_reprove_judgment_record_is_a_digest_line():
    """E2.11: the S6 close asks nothing and does not stop; the test is said as NOT proved. The Driver is a stub as in test_probe_gap_door."""
    import story_run as SR
    replay = {IID: {"test": FILE + "::adds", "instance": IID, "mutation": "invert"}}

    def driver(record, code):
        return SimpleNamespace(controller_state=lambda: {"dispatches": {}}, task="T-1", S6_LEFT="left {n}", CUT="...",
                               py=lambda *a: (code, json.dumps(record)))
    unjudged = {"verdict": "incomplete", "cause": "judgment", "record": "work/probes/cart_adds.json"}
    lines, proved, _seconds, records = SR.Driver.s6_reprove(driver(unjudged, 1), replay, ["TC-1"], no_stand=False, unrun=[])
    assert proved == 0 and records == ["work/probes/cart_adds.json"]
    assert lines[1] == (f"{IID}: the probe failed at the mutated line with a text the factory cannot read; nobody judges it at the "
                        "S6 close, so the test is not proved again"), lines
    tooling = dict(unjudged, cause="tooling", error="no frame")
    lines, *_ = SR.Driver.s6_reprove(driver(tooling, 1), replay, ["TC-1"], no_stand=False, unrun=[])
    assert "nobody judges" not in " ".join(lines) and "probe_by_code exit 1" in lines[1]       # the control: the tooling road is as before


def test_delivery_reason_names_owed_judgment(tmp_path, monkeypatch):
    """`PL.reached` (what `check_delivery` prints as «requires current sensitivity proof: <issue>») says WHY: the judgment is owed."""
    root, task, path = world(tmp_path, monkeypatch)
    entry = {"instance_id": IID, "file": FILE}
    got = PL.reached(entry, {}, task, now={"input_hash": SHA})
    assert got["level"] is None and any("owes the code critic's judgment (`cause: judgment`)" in i for i in got["issues"]), got
    record = stored(path)
    record["cause"] = "tooling"
    path.write_text(json.dumps(record), encoding="utf-8")
    assert PL.reached(entry, {}, task, now={"input_hash": SHA})["issues"] == ["no sensitivity receipt"]      # the control


# --- one reader, one writer, one door ----------------------------------------------------------------------

def scan(needle: str, files: list) -> list:
    return sorted(f.name for f in files if needle in f.read_text(encoding="utf-8", errors="replace"))


def test_no_reader_of_data_row_left():
    files = sorted(SCRIPTS.glob("*.py")) + sorted((SCRIPTS.parent / "references").glob("*.json"))
    assert len(files) > 50
    assert scan("data_row", files) == [] and scan("FACTORY_DATA_GAP", files) == []
    assert scan('startswith("factory:")', files) == [] and scan("by_factory = ", files) == []        # F6: the readers of the removed producer (AR-22)
    assert "window_record.py" in scan('startswith("class:")', files)                             # the control: the same scan finds a live prefix reader
    assert "probe_by_code.py" in scan("cause: tooling", files)                                   # the positive control: the same scan finds a live word


def test_judgment_written_only_by_probe_by_code():
    files = sorted(SCRIPTS.glob("*.py"))
    writers = sorted(f.name for f in files if re.search(r"""\[['"]judgment['"]\]\s*=[^=]""", f.read_text(encoding="utf-8", errors="replace")))
    assert writers == ["probe_by_code.py"], writers                                              # AR-14: and the control is the one writer found
    assert [m.start() for m in re.finditer(r"def judge_record\b", (SCRIPTS / "probe_by_code.py").read_text(encoding="utf-8"))]


def test_judge_door_is_one_constant():
    flags = set(re.findall(r"--[a-z]+", PBC.JUDGE_DOOR))
    assert flags == {"--task", "--dispatch", "--judge", "--verdict", "--quote", "--why"}
    taken = {option for action in PBC._build_parser()._actions for option in action.option_strings}
    assert flags <= taken                                                                        # the door names only flags the tool takes
    detail, spec = ts_detail()
    assert PBC.JUDGE_DOOR in judge(row("failed", "", "an unknown wording"), detail, spec)["note"]
    assert WR.UNJUDGED_NOTE.endswith(": ")
    sources = {f.name: f.read_text(encoding="utf-8", errors="replace") for f in SCRIPTS.glob("*.py")}
    assert [n for n, t in sources.items() if "--judge \"<instance>\"" in t] == ["probe_by_code.py"]      # the text is defined once


# --- N4 (t-2143): step 4 reaches every read failure; the critic reads every unsettled row ---------------------------------------

N0_ROWS = json.loads((Path(__file__).resolve().parent / "fixtures" / "probe-languages" / "pytest-n0-rows.json").read_text(encoding="utf-8"))


def n0(name: str) -> dict:
    row_ = N0_ROWS["rows"][name]
    return {"test_id": f"py/test_n0.py::{name}", "status": row_["status"], "problems": [dict(p) for p in row_["problems"]]}


def py_judge(row_: dict, site: dict) -> dict:
    """`judge_probe_row` over a real pytest row with the REAL python entry (the plan's token is N0's `qa-probe-tok`)."""
    entry = AD.ast_entry(".py")[1]
    detail = {"language": "python", "line": 3, "end_line": 5, "message_marker": N0_ROWS["token"], "fires_as": None, "pair": None}
    return PBC.judge_probe_row(row_, site, entry, detail, among=False, argv=["python", "-m", "pytest", "tests"])


def test_site_unread_is_judgment():
    """Item 1: a failed row WITH text and no readable place (`site_unread`, or no location) is the critic's, not the tool's gap; the
    row without text stays `tooling` (item 2, the control)."""
    detail, spec = ts_detail()
    for site in ({"site_unread": "mystery/typescript", "reason": "the reporter has no reader"}, {}, {"frame": "at x"}):
        got = judge(row("failed", "", "Error: something threw"), detail, spec, site=site)
        assert (got["verdict"], got["cause"]) == ("incomplete", "judgment") and "proved_by" not in got, (site, got)
        assert PBC.JUDGE_DOOR in got["note"] and "site was not read" not in got["note"], got["note"]
        quiet = judge(row("failed", "", ""), detail, spec, site=site)
        assert quiet["verdict"] == "incomplete" and "cause" not in quiet, (site, quiet)       # no text: the tool's gap, as before


def test_pytest_failed_row_without_site_is_judgment():
    """par.12 (a): N0 p3 (a ValueError thrown in a helper: the trace-tail reader gives site `{}`) and p2 (a foreign AssertionError): the
    row's text is the fact, the record is the critic's, never `incomplete` + `tooling`."""
    assert not N0_ROWS["sites"].get("p3") and not N0_ROWS["sites"].get("p2")        # the premise: the real reader found no place for them
    for name in ("p3", "p2"):
        got = py_judge(n0(name), {})
        assert (got["verdict"], got["cause"]) == ("incomplete", "judgment") and "proved_by" not in got, (name, got)
        facts_ = PBC.judgment_facts({}, n0(name), {}, {"file": "py/test_n0.py", "line": 3, "end_line": 5}, AD.ast_entry(".py")[1])
        assert facts_["failure_text"] == n0(name)["problems"][0]["text"] and facts_["location"] is None, name


def test_error_row_is_judgment():
    """Item 1 (the flip of the old `error stays tooling` pin): an `error` row with text - an exception outside an assertion, a setup or
    fixture failure (N0 p7) - goes to the critic, one judgment each (F12 = A). A token on an error row proves nothing (still)."""
    detail, spec = ts_detail()
    got = judge(row("error", "boom", "setup failed", kind="error"), detail, spec)
    assert (got["verdict"], got["cause"]) == ("incomplete", "judgment") and PBC.JUDGE_DOOR in got["note"], got
    got = py_judge(n0("p7"), {})
    assert (got["verdict"], got["cause"]) == ("incomplete", "judgment"), got
    got = judge(row("error", MARK, MARK, kind="error"), detail, spec)
    assert (got["verdict"], got["cause"]) == ("incomplete", "judgment") and "proved_by" not in got, got
    facts_ = PBC.judgment_facts({}, row("error", "boom", "setup failed", kind="error"), {}, {})
    assert (facts_["status"], facts_["message"], facts_["failure_text"]) == ("error", "boom", "setup failed")


def test_error_row_no_text_is_tooling():
    """Item 2 and E-Q: an `error` row (or a failed one) with no message and no text stays the tool's gap - nothing for the critic to read."""
    detail, spec = ts_detail()
    for status, kind in (("error", "error"), ("failed", "failure")):
        got = judge(row(status, "", "", kind=kind), detail, spec)
        assert got["verdict"] == "incomplete" and "cause" not in got and "proved_by" not in got, (status, got)
    with_message = judge(row("error", "boom", "", kind="error"), detail, spec)      # a message alone is text enough to read
    assert with_message["cause"] == "judgment", with_message


def test_fires_refused_on_empty_text(tmp_path, monkeypatch):
    """E4.1: `fires` on a record whose stored message and text are both empty is refused, door `cannot_judge`; `cannot_judge` passes;
    nothing is written by the refusal."""
    root, task, path = world(tmp_path, monkeypatch)
    record = stored(path)
    record["judgment_facts"].update(message="", failure_text="", rows=[{"test_id": "t", "status": "failed", "message": "", "failure_text": ""}])
    path.write_text(json.dumps(record), encoding="utf-8")
    before = path.read_bytes()
    for quote in ("anything", ""):
        said = refusal(root, task, verdict="fires", quote=quote)
        assert "nothing to stand on" in said and "cannot_judge" in said and "Nothing was written" in said, said
    assert path.read_bytes() == before
    assert judge_it(root, task, "cannot_judge", "", "no text to read")["judgment"]["verdict"] == "cannot_judge"


def test_judge_on_python_record(tmp_path, monkeypatch):
    """Item 6: `--judge` on a Python record (N0 p3's facts, language python) writes `fires` -> `intended_failure`, `proved_by: critic`;
    INV: only the critic's open S5 dispatch writes it (F2), other bytes are refused (E2.7), a written judgment is never rewritten (E2.8)."""
    root, task, path = world(tmp_path, monkeypatch)
    record = stored(path)
    py_facts = PBC.judgment_facts({"evidence_ref": "work/ev.xml"}, n0("p3"), {}, {"file": FILE, "line": 3, "end_line": 5}, AD.ast_entry(".py")[1])
    record.update(language="python", judgment_facts=py_facts, test_node=FILE + "::adds")
    path.write_text(json.dumps(record), encoding="utf-8")
    before = path.read_bytes()
    assert "is not the open code-critic dispatch" in refusal(root, task, quote="invalid literal", dispatch="D-author")       # a dispatch that is not the critic's
    assert path.read_bytes() == before
    (root / FILE).write_bytes(BYTES + b"# a later edit\n")
    assert "other bytes" in refusal(root, task, quote="invalid literal")                                                      # E2.7
    (root / FILE).write_bytes(BYTES)
    got = judge_it(root, task, "fires", "invalid literal for int()")
    assert (got["verdict"], got["proved_by"], got["language"], got["judgment"]["by"]) == ("intended_failure", "critic", "python", "D1"), got
    assert "owes no judgment" in refusal(root, task, quote="invalid literal")                                                  # E2.8: judged, never rewritten


def row_of(test_id: str, status: str, message: str, text: str) -> dict:
    return {"test_id": test_id, "status": status, "problems": [{"kind": "error" if status == "error" else "failure", "message": message, "text": text}]}


def judged_rows(monkeypatch, rows: list, sites: dict) -> dict:
    """`_judge_rows` with the REAL row judge over python `rows`; `sites` maps a test id to the place the reader gives it."""
    spec = PBC.parse_node("tests/t.py::test_x")
    detail = {"language": "python", "candidates": [], "line": 3, "end_line": 5, "message_marker": "qa-probe-n4", "fires_as": None, "pair": None,
              "target_source": None, "target_outside_body": False, "file": "tests/t.py"}
    record = {"task": "T", "notes": [], "expected_location": "tests/t.py:3", "expected_reason": "m", "verdict": "not_executed"}
    monkeypatch.setattr(PBC.reporters, "assertion_site", lambda r, *a, **k: sites[r["test_id"]])
    PBC._judge_rows(Path("."), record, rows, "junit-xml", spec, detail, {"command": {"argv": ["python", "-m", "pytest"]}, "instance_contracts": {}},
                    Path("x"), ["x"], True)
    return record


def test_param_rows_all_shown_to_critic(monkeypatch):
    """B7, E-D, E-Q: `[a]` failed with its place unread and `[b]` an `error` row are BOTH in `rows`; the flat keys describe the first;
    a quote from `[b]` is accepted (and one from nowhere is not). A marked row is settled by code and is not shown."""
    rows = [row_of("tests.t::test_x[a]", "failed", "AssertionError: text of a", "text of a\nwith a long body"),
            row_of("tests.t::test_x[b]", "error", "setup of b exploded", "Traceback: setup of b exploded in fixture"),
            row_of("tests.t::test_x[c]", "failed", "qa-probe-n4 marked", "qa-probe-n4 marked")]
    sites = {"tests.t::test_x[a]": {"site_unread": "x", "reason": "no frame"}, "tests.t::test_x[b]": {},
             "tests.t::test_x[c]": {"location": "tests/t.py:4", "failure_kind": "assertion"}}
    record = judged_rows(monkeypatch, rows, sites)
    assert (record["verdict"], record["cause"], record["language"]) == ("incomplete", "judgment", "python"), record
    facts_ = record["judgment_facts"]
    assert [r["test_id"] for r in facts_["rows"]] == ["tests.t::test_x[a]", "tests.t::test_x[b]"] and facts_["rows_cut"] == 0, facts_["rows"]
    assert [r["status"] for r in facts_["rows"]] == ["failed", "error"]
    assert (facts_["message"], facts_["failure_text"]) == ("AssertionError: text of a", "text of a\nwith a long body")        # the flat keys: the first row
    assert PBC._judge_input("fires", "setup of b exploded in fixture", "", facts_)[0] == "setup of b exploded in fixture"       # a quote from [b]
    assert PBC._judge_input("fires", "with a long body", "", facts_)[0] == "with a long body"                                  # and from the flat keys
    with pytest.raises(PBC.Refusal, match="not in the stored message or failure text"):
        PBC._judge_input("fires", "nobody printed this", "", facts_)
    # a mix with a TOOLING row (an error with no text at all): the record is tooling, as today, and carries no facts
    mixed = judged_rows(monkeypatch, rows[:1] + [row_of("tests.t::test_x[d]", "error", "", "")],
                        {"tests.t::test_x[a]": {}, "tests.t::test_x[d]": {}})
    assert mixed["cause"] == "tooling" and "judgment_facts" not in mixed, mixed


def test_rows_cut_refuses_fires(tmp_path, monkeypatch):
    """The cap AT and BEYOND: `FACTS_ROWS_MAX` rows are stored whole (`rows_cut` 0); one more is counted, not stored, and `fires` is
    refused (door `cannot_judge`) while `cannot_judge` and `other_failure` still work. Nothing is written by the refusal."""
    many = lambda n: [row_of(f"t[{i}]", "failed", f"msg {i}", f"text {i}") for i in range(n)]
    at = PBC.judgment_facts({}, many(1)[0], {}, {}, None, rows=many(PBC.FACTS_ROWS_MAX))
    beyond = PBC.judgment_facts({}, many(1)[0], {}, {}, None, rows=many(PBC.FACTS_ROWS_MAX + 1))
    assert (len(at["rows"]), at["rows_cut"]) == (PBC.FACTS_ROWS_MAX, 0) and (len(beyond["rows"]), beyond["rows_cut"]) == (PBC.FACTS_ROWS_MAX, 1)
    assert PBC._judge_input("fires", "text 0", "", at)[0] == "text 0"                      # AT the cap: fires is open
    with pytest.raises(PBC.Refusal, match="cannot_judge"):
        PBC._judge_input("fires", "text 0", "", beyond)                                    # BEYOND: refused, the door names cannot_judge
    assert PBC._judge_input("cannot_judge", "", "twelve rows shown, one more cut", beyond)[1] == "twelve rows shown, one more cut"
    assert PBC._judge_input("other_failure", "text 0", "", beyond)[0] == "text 0"
    root, task, path = world(tmp_path, monkeypatch)
    record = stored(path)
    record["judgment_facts"] = beyond
    path.write_text(json.dumps(record), encoding="utf-8")
    before = path.read_bytes()
    said = refusal(root, task, verdict="fires", quote="text 0")
    assert "cannot_judge" in said and "Nothing was written" in said and "more were cut" in said, said
    assert path.read_bytes() == before
    assert judge_it(root, task, "cannot_judge", "", "rows were cut")["judgment"]["verdict"] == "cannot_judge"


def test_long_text_keeps_head_and_tail():
    """Item 4 (B7): a text beyond `FAILURE_TEXT_MAX` keeps its head and its tail around ONE `…` (the mark counts); pytest's raising line,
    the LAST, survives; AT the limit nothing is cut. The same cut is applied to every row."""
    raising = "py/test_n0.py:11: AssertionError"
    body = "head line: the message\n" + ("    frame line of a long traceback\n" * 1000) + "E   assert not 1 == 1\n" + raising
    assert len(body) > PBC.FAILURE_TEXT_MAX
    cut = PBC.cut_text(body)
    assert len(cut) == PBC.FAILURE_TEXT_MAX and cut.count("…") == 1, len(cut)
    assert cut.startswith("head line: the message") and cut.endswith(raising) and "E   assert not 1 == 1" in cut
    head, _mark, tail = cut.partition("…")
    assert body.startswith(head) and body.endswith(tail) and abs(len(head) - len(tail)) <= 1      # half each
    assert PBC.cut_text("x" * PBC.FAILURE_TEXT_MAX) == "x" * PBC.FAILURE_TEXT_MAX and PBC.cut_text("") == "" and PBC.cut_text(None) == ""
    record = {"status": "failed", "problems": [{"kind": "failure", "message": "m", "text": body}]}
    facts_ = PBC.judgment_facts({}, record, {}, {})
    assert facts_["failure_text"] == cut == facts_["rows"][0]["failure_text"]
    assert PBC._judge_input("fires", raising, "", facts_)[0] == raising                           # the raising line is quotable


def test_old_facts_no_rows_quote_ok():
    """E4.5: a record written before N4 (no `rows`, no `rows_cut`) is read by its flat keys; a malformed `rows` never crashes and never
    opens `fires` on a text that is not stored."""
    old = {"message": "old message", "failure_text": "old text line\nsecond"}
    assert PBC._judge_input("fires", "second", "", old)[0] == "second"
    assert PBC._judge_input("fires", "old message", "", dict(old, rows=None, rows_cut=None))[0] == "old message"
    for bad in ("x", 5, [None, "s", 3], {"a": 1}):
        assert PBC._judge_input("fires", "second", "", dict(old, rows=bad, rows_cut="x"))[0] == "second"
    with pytest.raises(PBC.Refusal, match="not in the stored"):
        PBC._judge_input("fires", "nothing", "", old)


ALL = [(name, fn) for name, fn in sorted(globals().items()) if name.startswith("test_") and callable(fn)]

if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-q", "-p", "no:cacheprovider"]))
