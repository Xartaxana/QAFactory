"""B-16 of t-1955 (node N1): the S5 probe-gap door names the key the reader reads, and `go on` at the seam reaches it.

Arm B stood at S5: the door printed `probe gap: <instance id>`, an instance id is a phrase with spaces, `contract.prefix_value` reads one token
only, and the person's word was refused (`waiver.block_name_row`). The door now names the CASE KEY; `window_record.probe_gap_cases` joins the
ids by equality; the seam question carries the keys in `asked` and `seam_chosen` records one `probe gap: <case key>` word for each on `go on`.
Fast: the driver pieces run on a stub `self`; the window and probe records are real files in a temp dir.
"""
import json
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import SCRIPTS  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import acceptance  # noqa: E402
import contract as C  # noqa: E402
import controller  # noqa: E402
import proof_level  # noqa: E402
import story_run as SR  # noqa: E402
import waiver  # noqa: E402
import window_record as WR  # noqa: E402

PKG = SCRIPTS.parent
PHRASE = "@regression LOCAL-1_TC_001 in-stock add shows success toast, badge 1 and one cart line"


def probe(root: Path, iid: str, input_hash: str, how: str) -> None:
    """The probe record of `iid`: `tool` = the tool could not read the test (`incomplete`), `down` = a stand that was down, `judged`."""
    verdict = {"tool": "incomplete", "down": "not_executed", "judged": "no_failure"}[how]
    path = proof_level.probe_record_path(root, iid)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"verdict": verdict, "test_file_sha256": input_hash}), encoding="utf-8")


def window(root: Path, rows: list) -> dict:
    """rows: `(case, instance id, outcome, probe state or None)`; a probe state writes the record, None leaves the probe unrun."""
    scope, instances = {}, []
    for number, (case, iid, outcome, how) in enumerate(rows):
        scope.setdefault(case, []).append(iid)
        digest = f"hash-{number}"
        instances.append({"instance_id": iid, "input_hash": digest, "outcome": outcome, "change_disposition": "new_or_changed"})
        if how:
            probe(root, iid, digest, how)
    return {"scope_instances": scope, "instances": instances}


def test_cases_from_shape_line_green_could_not_run(tmp_path):
    win = window(tmp_path, [("LOCAL-1_TC_002", PHRASE + " two", "passed", "tool"), ("LOCAL-1_TC_001", PHRASE, "passed", "tool")])
    assert f"{PHRASE}: {C.PROBE_MISSING_ERROR}" in C.window_shape_errors(win)      # the door's own trigger: the shape line
    assert WR.probe_gap_cases(win, tmp_path) == [("LOCAL-1_TC_001", [PHRASE]), ("LOCAL-1_TC_002", [PHRASE + " two"])]   # sorted by case key


def test_cases_from_unnamed_probe_gap_block(tmp_path):
    win = window(tmp_path, [("CASE-A", "iid a", "passed", "tool")])
    win["instances"][0]["probe_gap"] = {"verdict": "incomplete"}                 # a block no word of the person names
    assert WR.probe_gap_cases(win, tmp_path) == [("CASE-A", ["iid a"])]
    (tmp_path / "pipeline.json").write_text(json.dumps({"stage_overrides": [
        {"stage": "S5", "match": "probe gap: CASE-A", "decision": "ok", "at": "2026-11-05T10:00:00+00:00"}]}), encoding="utf-8")
    assert acceptance.probe_gap_named(win, tmp_path)                             # the word names it now...
    assert WR.probe_gap_cases(win, tmp_path) == []                               # ...so it is not owed any more


def test_red_instance_gives_no_case(tmp_path):
    win = window(tmp_path, [("CASE-A", "iid a", "failed", "tool"), ("CASE-B", "iid b", "passed", "tool")])
    assert WR.probe_gap_cases(win, tmp_path) == [("CASE-B", ["iid b"])]          # a red test is never closed by a word (FR-18)


def test_instance_in_two_cases_gives_both(tmp_path):
    win = window(tmp_path, [("CASE-A", "iid shared", "passed", "tool")])
    win["scope_instances"]["CASE-B"] = ["iid shared"]
    assert WR.probe_gap_cases(win, tmp_path) == [("CASE-A", ["iid shared"]), ("CASE-B", ["iid shared"])]


def test_case_key_that_is_not_one_token_is_left_out(tmp_path):
    # the reader `contract.probe_gap_words` takes ONE token: a key with whitespace inside or a leading colon can never be recorded
    win = window(tmp_path, [("CASE A", "iid sp", "passed", "tool"), (":CASE-C", "iid colon", "passed", "tool"),
                            ("CASE-B", "iid b", "passed", "tool")])
    assert WR.probe_gap_cases(win, tmp_path) == [("CASE-B", ["iid b"])]          # the rest keeps its door
    assert "CASE-B" in WR.probe_gap_keys_line(win, tmp_path) and "CASE A" not in WR.probe_gap_keys_line(win, tmp_path)
    only = window(tmp_path, [("CASE A", "iid sp", "passed", "tool"), (":CASE-C", "iid colon", "passed", "tool")])
    assert WR.probe_gap_cases(only, tmp_path) == []                              # only such keys: no list, so not the probe-gap question
    assert WR.probe_gap_keys_line(only, tmp_path) == ""


def test_seam_go_on_skips_never_run_probe(tmp_path):
    win = window(tmp_path, [("CASE-A", "iid a1", "passed", "tool"), ("CASE-A", "iid a2", "passed", None),      # a probe nobody ran
                            ("CASE-B", "iid b1", "passed", "tool"), ("CASE-C", "iid c1", "passed", "down"),    # a stand that was down
                            ("CASE-D", "iid d1", "passed", "judged")])                                        # a probe that judged
    assert WR.probe_gap_cases(win, tmp_path) == [("CASE-B", ["iid b1"])]         # one never-run sibling keeps the whole case off the list


@pytest.mark.parametrize("bad", [None, "x", [], {}, {"scope_instances": []}, {"scope_instances": {"A": "no"}, "instances": "no"},
                                 {"scope_instances": {"A": ["i"]}, "instances": [{"instance_id": "i"}, 5]}])
def test_malformed_window_gives_nothing_and_never_raises(tmp_path, bad):
    assert WR.probe_gap_cases(bad, tmp_path) == []


def test_door_text_names_case_key_placeholder():
    for text in (WR.PROBE_GAP_RECORD, WR.PROBE_GAP_DOOR, WR.GAP_ORIGIN[WR.PROBE_GAP_UNRECORDED_KIND][1]):
        assert "<case key>" in text and "<IID>" not in text and "<instance id>" not in text
    sites = {"s5.md": (PKG / "skills/qa-story/phases/s5.md").read_text(encoding="utf-8"),
             "state-exits.md": (PKG / "design/state-exits.md").read_text(encoding="utf-8"),
             "conductor-actions.json": (PKG / "references/conductor-actions.json").read_text(encoding="utf-8"),
             "contract.probe_gap_words": C.probe_gap_words.__doc__}
    for name, text in sites.items():
        assert "probe gap: <instance id or case" not in text and "<instance id or case key>" not in text, name
    assert "probe gap: <case key>" in sites["s5.md"] and "probe gap: <case key>" in sites["state-exits.md"]
    assert "waiver.py refuses any other" not in sites["conductor-actions.json"]
    actions = json.loads(sites["conductor-actions.json"])["actions"]
    assert sum(1 for row in actions if "probe gap: <case key>" in row.get("run", "")) == 1


class StubController:
    def __init__(self, root):
        self.store = SimpleNamespace(root=root)
        self._noted = controller.Controller._noted

    @staticmethod
    def _ticket():
        return "QA-9"


def test_controller_door_keeps_concrete_ticket(tmp_path, monkeypatch):
    monkeypatch.setattr(acceptance, "validate_window", lambda w, r: [f"{acceptance.PROBE_GAP_UNRECORDED_KIND}:{PHRASE}"])
    win = window(tmp_path, [("LOCAL-1_TC_001", PHRASE, "passed", "tool")])
    problems = controller.Controller._s5_gap_problems(StubController(tmp_path), {"id": "S5-qa-code-critic-2"}, {}, win)
    text = problems[0][1]
    assert 'waiver.py --task QA-9 --stage S5 --block "probe gap: <case key>" --words-file <file>' in text
    assert "<T>" not in text and "<instance id>" not in text and "<IID>" not in text
    assert "window_record.py --task QA-9 --dispatch S5-qa-code-critic-2" in text


def test_controller_refusal_lists_concrete_cases(tmp_path):
    win = window(tmp_path, [("CASE-B", "iid b", "passed", "tool"), ("CASE-A", "iid a", "passed", "tool")])
    problems = controller.Controller._s5_completion_problems(StubController(tmp_path), {"id": "S5-qa-code-critic-2"}, {"window": win}, {}, [])
    text = problems[0][1]
    assert 'waiver.py --task QA-9 --stage S5 --block "probe gap: <case key>"' in text and "<T>" not in text
    assert "The case keys this window needs: CASE-A, CASE-B (one record each)." in text
    # no case the person can take: no list, the door text alone (an empty list is omitted)
    never = window(tmp_path, [("CASE-A", "iid z", "passed", None)])
    other = controller.Controller._s5_completion_problems(StubController(tmp_path), {"id": "d"}, {"window": never}, {}, [])[0][1]
    assert "probe gap: <case key>" in other and "The case keys this window needs" not in other


def test_door_block_is_accepted_by_block_name_row():
    assert waiver.block_name_row("probe gap: LOCAL-1_TC_001", "S5") is not None
    assert waiver.block_name_row(f"probe gap: {PHRASE}", "S5") is None            # the phrase form is the 16:44 refusal of arm B
    assert waiver.block_name_row("probe gap: <case key>", "S5") is None           # an unfilled placeholder names nothing


def test_recorded_case_word_is_read_by_probe_gap_words():
    pipe = {"stage_overrides": [{"stage": "S5", "match": "probe gap: LOCAL-1_TC_001", "decision": "go on", "at": "2026-11-05T10:00:00+00:00"},
                                {"stage": "S5", "match": f"probe gap: {PHRASE}", "decision": "go on", "at": "2026-11-05T10:00:00+00:00"}]}
    words = C.probe_gap_words(pipe)
    assert list(words) == ["LOCAL-1_TC_001"] and words["LOCAL-1_TC_001"]["words"] == "go on"


PAIRS = [("LOCAL-1_TC_001", [PHRASE]), ("LOCAL-1_TC_002", ["second test"])]


def test_lead_says_class_scope():
    lead = SR.Driver.probe_gap_lead(PAIRS)
    assert "2 test case(s) ran green" in lead
    assert f'LOCAL-1_TC_001 (the test "{PHRASE}"); LOCAL-1_TC_002 (the test "second test")' in lead
    assert "every test of this story whose check the tool could not read" in lead and "later windows" in lead
    assert "records your words once for each case named above" in lead
    for forbidden in ("waiver", ".py", "S5-qa", "probe_gap", "work/"):
        assert forbidden not in lead


def test_lead_cuts_at_ten_cases_and_counts_the_rest():
    lead = SR.Driver.probe_gap_lead([(f"CASE-{n:02d}", [f"t{n}"]) for n in range(13)])
    assert "CASE-09" in lead and "CASE-10" not in lead and ", and 3 more." in lead and "13 test case(s)" in lead


def test_person_carries_cases_through_asked_and_held_question():
    """`_person_of` -> `ask` -> `held_question`: the keys travel on the `rows` pattern, on a real driver over a temp project."""
    import harness
    from story_run_common import driver_for, seed
    root, task_root, env = seed("QA-9")
    try:
        driver = driver_for(root, env, "QA-9")
        state = {"kind": "refusal", "stage": "S5", "dispatch": "S5-qa-code-critic-2", "why": "threshold", "probe_gap_cases": ["CASE-A", "CASE-B"]}
        options = [{"norm": "go on", "move": "go_on_as_is"}, {"norm": "stop", "move": "stop_story"}]
        person = driver._person_of(state, "lead\n\nbody", options)
        assert person.probe_gap_cases == ("CASE-A", "CASE-B")
        driver.ask(person)
        assert driver.state["asked"]["probe_gap_cases"] == ["CASE-A", "CASE-B"]
        assert driver.held_question("held").probe_gap_cases == ("CASE-A", "CASE-B")
        plain = driver._person_of(dict(state, probe_gap_cases=[]), "lead\n\nbody", options)
        driver.ask(plain)
        assert "probe_gap_cases" not in driver.state["asked"]                    # no cases, no key (E1.7)
        assert driver.held_question("held").probe_gap_cases == ()
    finally:
        harness.cleanup(root)


class Rig:
    """`seam_chosen` on a stub `self`: the words file, `pass_block` and `no_move` are recorded stand-ins."""

    def __init__(self, refuse_at=None):
        self.passes, self.moves, self.refuse_at = [], [], refuse_at
        d = self.d = SimpleNamespace(state_dir=Path("."))
        d.original_words = lambda asked: ("state/words/a.txt", "go on")
        d.answer_file = lambda: "state/answer.txt"
        d.pass_block = self.pass_block
        d.mark_rows_word = lambda *a: None
        d.no_move = lambda state, moves=None: self.moves.append(state)
        d.held_question = lambda lead, details=None: RuntimeError(lead)
        d.seam_chosen = types.MethodType(SR.Driver.seam_chosen, d)

    def pass_block(self, stage, block, words_file, lead):
        if block == self.refuse_at:
            raise RuntimeError(lead)
        self.passes.append((stage, block, words_file))

    def choose(self, move, token, **asked):
        asked.setdefault("options", [{"token": token, "move": move}])
        self.d.seam_chosen(move, token, asked, "question text", "S5", "S5-qa-code-critic-2")


def test_seam_go_on_records_one_word_per_case(capsys):
    rig = Rig()
    rig.choose("go_on_as_is", "go on", probe_gap_cases=["LOCAL-1_TC_001", "LOCAL-1_TC_002"], block="")
    assert rig.passes == [("S5", "probe gap: LOCAL-1_TC_001", "state/words/a.txt"), ("S5", "probe gap: LOCAL-1_TC_002", "state/words/a.txt")]
    assert rig.moves == []                                                       # nothing went on to the conductor
    assert "S5: the probe gap of LOCAL-1_TC_001, LOCAL-1_TC_002 is recorded on your word" in capsys.readouterr().out
    assert all(block.startswith("probe gap: ") for _s, block, _f in rig.passes)  # recording these words never passes another line (E1.9)
    for _s, block, _f in rig.passes:
        assert waiver.block_name_row(block, "S5") is not None                    # every one is a block waiver.py takes


def test_seam_refused_word_is_held_and_never_printed_recorded(capsys):
    rig = Rig(refuse_at="probe gap: CASE-B")
    with pytest.raises(RuntimeError, match="probe gap of CASE-B"):
        rig.choose("go_on_as_is", "go on", probe_gap_cases=["CASE-A", "CASE-B", "CASE-C"], block="")
    assert [p[1] for p in rig.passes] == ["probe gap: CASE-A"]                    # earlier ones stay (append-only); the later one is not tried
    assert "is recorded on your word" not in capsys.readouterr().out             # E1.4


def test_seam_block_pass_runs_first_when_both_present():
    rig = Rig()
    rig.choose("go_on_as_is", "go on", probe_gap_cases=["CASE-A"], block="some block")
    assert [p[1] for p in rig.passes] == ["some block", "probe gap: CASE-A"]


def test_seam_go_on_without_cases_unchanged(capsys):
    rig = Rig()
    rig.choose("go_on_as_is", "go on", block="some block")
    assert [p[1] for p in rig.passes] == ["some block"]
    assert "going on on the person's word; recorded" in capsys.readouterr().out
    older = Rig()                                                                 # an `asked` written before N1: no key, no recording (E1.7)
    older.choose("go_on_as_is", "go on", block="")
    assert older.passes == [] and len(older.moves) == 1                           # today's path: the words go to the conductor


@pytest.mark.parametrize("move,token", [("retry_step", "retry"), ("stop_story", "stop"), ("rework_stage", "rework")])
def test_seam_retry_records_nothing(move, token):
    rig = Rig()
    try:
        rig.choose(move, token, probe_gap_cases=["CASE-A"], block="")
    except Exception:                                                              # a held question for a move with no words is fine
        pass
    assert rig.passes == []                                                        # only the token the person chose records anything (E1.6)


def refusal_rig(root: Path, win: dict):
    """`window_round_gate` on a stub `self` whose series already holds the same finding set, so the seam is reached at once."""
    (root / "work" / "windows").mkdir(parents=True, exist_ok=True)
    if win is not None:
        (root / "work" / "windows" / "S5-qa-code-critic-2.json").write_text(json.dumps(win), encoding="utf-8")
    line = "S5 window record is incomplete: something"
    d = SimpleNamespace(task_root=root, state={"window_rounds": {"S5|CASE": [
        {"at": "t", "dispatch": "S5-qa-code-critic-2", "set": SR.finding_lines([line]), "outcome": "to_conductor", "cause": "refusal"}]}},
        boundary="S5:S5-qa-code-critic-2")
    d.refusal_dispatch = lambda refusal: "S5-qa-code-critic-2"
    d.window_key = lambda stage, dispatch: "S5|CASE"
    d.save_state = lambda: None
    d.refusal_lines = lambda refusal, items=None: list(items or [])
    d.question_from_refusal = lambda refusal, stage: "THE FALLBACK LEAD"
    d.probe_gap_lead = SR.Driver.probe_gap_lead
    seen = []

    def no_move(state, moves=None):
        seen.append(state)
        raise RuntimeError("seam")

    d.no_move = no_move
    return d, SR.Refusal(line, findings=[line]), seen


def test_gate_seam_names_cases_when_the_record_has_them(tmp_path):
    win = window(tmp_path, [("CASE-A", "iid a", "passed", "tool")])
    d, refusal, seen = refusal_rig(tmp_path, win)
    with pytest.raises(RuntimeError, match="seam"):
        SR.Driver.window_round_gate(d, refusal, "S5")
    assert seen[0]["probe_gap_cases"] == ["CASE-A"] and seen[0]["lead"] == SR.Driver.probe_gap_lead([("CASE-A", ["iid a"])])
    assert seen[0]["call"] is False and seen[0]["kind"] == "refusal"


@pytest.mark.parametrize("rows,what", [([("CASE-A", "iid a", "failed", "tool")], "red only"),
                                       ([("CASE-A", "iid a", "passed", None)], "never run"),
                                       (None, "no record on disk")])
def test_gate_seam_is_todays_when_no_case_qualifies(tmp_path, rows, what):
    d, refusal, seen = refusal_rig(tmp_path, window(tmp_path, rows) if rows else None)
    with pytest.raises(RuntimeError, match="seam"):
        SR.Driver.window_round_gate(d, refusal, "S5")
    assert "probe_gap_cases" not in seen[0] and seen[0]["lead"].endswith("THE FALLBACK LEAD"), what   # E1.1: a red is never closed by a word


def test_gate_seam_of_another_stage_never_reads_the_window(tmp_path):
    d, refusal, seen = refusal_rig(tmp_path, window(tmp_path, [("CASE-A", "iid a", "passed", "tool")]))
    SR.WINDOW_ROUND_STAGES["S9"] = "x"
    try:
        d.state["window_rounds"] = {"S9|CASE": d.state["window_rounds"]["S5|CASE"]}
        d.window_key = lambda stage, dispatch: "S9|CASE"
        with pytest.raises(RuntimeError, match="seam"):
            SR.Driver.window_round_gate(d, refusal, "S9")
    finally:
        del SR.WINDOW_ROUND_STAGES["S9"]
    assert "probe_gap_cases" not in seen[0]


# --- N4 (t-2143): a record with NO failure text is the tool's gap and keeps its door ----------------------------------------------

def test_no_text_record_still_offered(tmp_path):
    """Item 2 / E-Q: a failed or error row with no message and no text is `incomplete` with `cause: tooling` (the caller's), so its test
    is still offered the `probe gap` question - at the window and at the seam - and a class word still covers it. The control is a
    row WITH text: it is the critic's and is not offered (`test_error_row_not_offered_as_gap`)."""
    import assertion_detectors as AD
    import probe_by_code as PBC
    entry = AD.ast_entry(".py")[1]
    detail = {"language": "python", "line": 3, "end_line": 5, "message_marker": "qa-probe-n4", "fires_as": None, "pair": None}
    for status, kind in (("failed", "failure"), ("error", "error")):
        win = window(tmp_path / status, [("CASE-A", "iid a", "passed", None)])
        row = {"test_id": "t", "status": status, "problems": [{"kind": kind, "message": "", "text": ""}]}
        got = PBC.judge_probe_row(row, {}, entry, detail, among=False, argv=["python", "-m", "pytest"])
        assert got["verdict"] == "incomplete" and "cause" not in got, got
        record = {"verdict": got["verdict"], "cause": "tooling", "language": "python", "test_file_sha256": "hash-0"}   # `_tooling_gap` writes the rest
        path = proof_level.probe_record_path(tmp_path / status, "iid a")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(record), encoding="utf-8")
        assert proof_level.probe_could_not_run(tmp_path / status, "iid a", "hash-0") is True
        assert WR.probe_gap_cases(win, tmp_path / status) == [("CASE-A", ["iid a"])]
        d, refusal, seen = refusal_rig(tmp_path / status, win)
        with pytest.raises(RuntimeError, match="seam"):
            SR.Driver.window_round_gate(d, refusal, "S5")
        assert seen[0]["probe_gap_cases"] == ["CASE-A"], (status, seen[0])


if __name__ == "__main__": raise SystemExit(pytest.main([__file__, "-q", "-p", "no:cacheprovider"]))
