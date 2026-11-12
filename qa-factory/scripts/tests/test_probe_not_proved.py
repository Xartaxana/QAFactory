"""t-1968 node N5: when the code critic answers `cannot_judge` on a mutation probe, the PERSON gets their own question with the facts.

The owner's word 05.11.2026: such a test is asked separately; an earlier `go on` about tooling probes never covers it. The word is
`probe not proved: <case key>` (a block row with no class), read only when it is not older than the judgment; the `probe gap:` words
(instance, case, `tooling:`, class) are not read for the test; `window_record.probe_judgment_cases` lists the cases, `Driver.probe_judgment_lead`
asks, `seam_chosen` records one word per case on `go on`. Fast: the driver pieces run on a stub `self`; the records are real files in a temp dir.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import SCRIPTS  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import acceptance  # noqa: E402
import contract as C  # noqa: E402
import human_text  # noqa: E402
import proof_level  # noqa: E402
import story_run as SR  # noqa: E402
import waiver  # noqa: E402
import window_record as WR  # noqa: E402
from test_probe_gap_door import Rig, refusal_rig  # noqa: E402

PKG = SCRIPTS.parent
JUDGED_AT = "2026-11-05T10:00:00+00:00"
EARLIER, LATER = "2026-11-05T09:59:59+00:00", "2026-11-05T10:00:01+00:00"
STATEMENT = "expect(cart).toHaveText('1')"
WRITTEN = "expect(cart, ['qa-probe', 'abc123def456'].join('-') + ' ' + 'step 1: badge').toHaveText('1')"     # as WRITTEN: the factory's marker in it
FAILURE = "Error: expect(received).toHaveText(expected)\n\n   Expected: 1\n   Received: 2\n  at cart.spec.ts:12"


def probe(root: Path, iid: str, sha: str, how: str, *, at: str = JUDGED_AT, failure: str = FAILURE, why: str = "it threw before the check") -> None:
    """The probe record of `iid`: `cannot` = the critic could not judge, `unjudged` = owes the critic, `tool` / `down` / `judged` as the door test."""
    record = {"test_file_sha256": sha}
    if how in ("cannot", "unjudged"):
        record.update(verdict="incomplete", cause="judgment",
                      judgment_facts={"file": "tests/cart.spec.ts", "line": 12, "statement_after": WRITTEN, "statement_inverted": STATEMENT,
                                      "failure_text": failure})
        if how == "cannot":
            record["judgment"] = {"verdict": "cannot_judge", "quote": "", "why": why, "by": "S5-qa-code-critic-2", "at": at, "facts_sha": "x"}
    else:
        record["verdict"] = {"tool": "incomplete", "down": "not_executed", "judged": "no_failure"}[how]
    path = proof_level.probe_record_path(root, iid)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record), encoding="utf-8")


def window(root: Path, rows: list, **kw) -> dict:
    """rows: `(case, instance id, outcome, probe state or None)`; a state writes the record, None leaves the probe unrun."""
    scope, instances = {}, []
    for number, (case, iid, outcome, how) in enumerate(rows):
        scope.setdefault(case, []).append(iid)
        digest = f"hash-{number}"
        instances.append({"instance_id": iid, "input_hash": digest, "outcome": outcome, "change_disposition": "new_or_changed"})
        if how:
            probe(root, iid, digest, how, **kw)
    return {"scope_instances": scope, "instances": instances}


def words(root: Path, *matches, at: str = LATER, **extra) -> dict:
    """pipeline.json with one live S5 record per `match` (the way `waiver.py` writes it)."""
    pipeline = {"stage_overrides": [{"stage": "S5", "match": m, "decision": "go on", "at": at, **extra} for m in matches]}
    (root / "pipeline.json").write_text(json.dumps(pipeline), encoding="utf-8")
    return pipeline


def item_of(case="CASE-A", iid="the test", **over) -> dict:
    return {"iid": iid, "file": "tests/cart.spec.ts", "line": 12, "statement_inverted": STATEMENT, "statement_after": WRITTEN,
            "printed": "boom", "why": "it threw first", **over}


def test_not_proved_word_is_a_block_row():
    assert waiver.block_name_row("probe not proved: LOCAL-1_TC_001", "S5") is not None
    assert waiver.block_name_row("probe not proved: two words", "S5") is None          # one token, as every prefixed name
    assert waiver.block_name_row("probe not proved: <case key>", "S5") is None         # an unfilled placeholder names nothing
    assert waiver.block_name_row("probe not proved: CASE-A", "S6") is None             # S5 only
    row = next(r for r in json.loads((PKG / "references/block-names.json").read_text(encoding="utf-8"))["names"]
               if r["block"] == "probe not proved: <case key>")
    assert "class" not in row and row["reader"] == "contract:probe_not_proved_words" and row["stages"] == ["S5"]   # one word never widens
    pipe = {"stage_overrides": [{"stage": "S5", "match": "probe not proved: CASE-A", "decision": " go  on ", "at": JUDGED_AT},
                                {"stage": "S5", "match": "probe gap: CASE-B", "decision": "go on", "at": JUDGED_AT},
                                {"stage": "S5", "match": "probe not proved: *", "decision": "go on", "at": JUDGED_AT},
                                {"stage": "S5", "match": "probe not proved: CASE-C", "decision": "go on", "at": JUDGED_AT, "revoked_at": LATER}]}
    assert C.probe_not_proved_words(pipe) == {"CASE-A": {"words": "go on", "at": JUDGED_AT}, "*": {"words": "go on", "at": JUDGED_AT}}
    assert list(C.probe_gap_words(pipe)) == ["CASE-B"]                                  # each reader reads its own prefix only
    assert C.probe_not_proved_words(None) == {} and C.probe_not_proved_words({"stage_overrides": "x"}) == {}


@pytest.mark.parametrize("when", [EARLIER, LATER])
def test_go_on_for_tooling_never_covers_cannot_judge(tmp_path, when):
    """Every `probe gap:` word - the instance, the case, `tooling:`, the class - before or after the judgment: none names the test."""
    win = window(tmp_path, [("CASE-A", "the test", "passed", "cannot")])
    item = win["instances"][0]
    pipe = words(tmp_path, "probe gap: CASE-A", "probe gap: tooling:typescript", "probe gap: the-test", at=when)
    pipe["stage_overrides"].append({"stage": "S5", "match": "probe gap: CASE-Z", "decision": "go on", "at": when, "class": C.PROBE_GAP_CLASS})
    (tmp_path / "pipeline.json").write_text(json.dumps(pipe), encoding="utf-8")
    assert C.probe_gap_words(pipe) and C.probe_gap_class_word(pipe, ["CASE-A"])          # the words ARE live
    assert WR.probe_gap_block(tmp_path, item, ["CASE-A"], C.probe_gap_words(pipe), C.probe_gap_class_word(pipe, ["CASE-A"]),
                              C.probe_not_proved_words(pipe)) is None
    item["probe_gap"] = {"verdict": "incomplete", "record": None, "why": "w", "named_by": "x", "words": "w", "at": when}   # a block someone wrote
    assert acceptance.probe_gap_named(win, tmp_path) == {}
    assert WR.probe_judgment_cases(win, tmp_path)[0][0] == "CASE-A"                      # so the person is still asked


def test_word_older_than_judgment_not_read(tmp_path):
    win = window(tmp_path, [("CASE-A", "the test", "passed", "cannot")])
    item = win["instances"][0]
    for at, read in ((EARLIER, False), (JUDGED_AT, True), (LATER, True), ("", False), ("not a time", False)):
        pipe = words(tmp_path, "probe not proved: CASE-A", at=at)
        block = WR.probe_gap_block(tmp_path, item, ["CASE-A"], {}, None, C.probe_not_proved_words(pipe))
        assert (block is not None) is read, at
        if read:
            assert block["named_by"] == "probe not proved: CASE-A" and block["verdict"] == "incomplete" and block["words"] == "go on"
            assert block["at"] == at and "the code critic could not judge it: it threw before the check" in block["why"]
        item["probe_gap"] = block or {"verdict": "incomplete"}
        assert (item["instance_id"] in acceptance.probe_gap_named(win, tmp_path)) is read, at
    other = words(tmp_path, "probe not proved: CASE-B", at=LATER)                        # a word about another case names nothing
    assert WR.probe_gap_block(tmp_path, item, ["CASE-A"], {}, None, C.probe_not_proved_words(other)) is None


def test_cases_list_cannot_judge_only(tmp_path):
    win = window(tmp_path, [("CASE-B", "b1", "passed", "cannot"), ("CASE-A", "a1", "passed", "cannot"),
                            ("CASE-C", "c1", "passed", "unjudged"),                      # owes the critic: never listed (E5.6)
                            ("CASE-D", "d1", "passed", "cannot"), ("CASE-D", "d2", "passed", "unjudged"),   # one sibling keeps the case off
                            ("CASE-E", "e1", "failed", "cannot"),                        # red: a word never closes it
                            ("CASE-F", "f1", "passed", None),                            # never run
                            ("CASE-G", "g1", "passed", "tool"), ("CASE-H", "h1", "passed", "down"), ("CASE-I", "i1", "passed", "judged"),
                            ("CASE J", "j1", "passed", "cannot")])                       # not one token: no word can name it
    found = WR.probe_judgment_cases(win, tmp_path)
    assert [case for case, _items in found] == ["CASE-A", "CASE-B"]                      # sorted, cannot_judge only
    one = found[0][1][0]
    assert one == {"iid": "a1", "file": "tests/cart.spec.ts", "line": 12, "statement_inverted": STATEMENT, "statement_after": WRITTEN,
                   "printed": "Error: expect(received).toHaveText(expected) / Expected: 1 / Received: 2", "why": "it threw before the check"}
    assert [case for case, _ids in WR.probe_gap_cases(win, tmp_path)] == ["CASE-G"]      # the doors question keeps its own cases


def test_cases_empty_and_malformed_never_raise(tmp_path):
    for bad in (None, "x", [], {}, {"scope_instances": []}, {"scope_instances": {"A": "no"}, "instances": "no"},
                {"scope_instances": {"A": ["i"]}, "instances": [{"instance_id": "i"}, 5]}):
        assert WR.probe_judgment_cases(bad, tmp_path) == []
    none = window(tmp_path, [("CASE-A", "a1", "passed", "tool")])
    assert WR.probe_judgment_cases(none, tmp_path) == []                                 # E5.3: no cannot_judge item, no list


def test_cases_record_without_failure_text(tmp_path):
    win = window(tmp_path, [("CASE-A", "a1", "passed", "cannot")], failure="")
    (case, [item]), = WR.probe_judgment_cases(win, tmp_path)
    assert case == "CASE-A" and item["printed"] == ""
    path = proof_level.probe_record_path(tmp_path, "a1")
    record = json.loads(path.read_text(encoding="utf-8"))
    del record["judgment_facts"]                                                         # no facts at all: still listed, nothing invented
    path.write_text(json.dumps(record), encoding="utf-8")
    (case, [bare]), = WR.probe_judgment_cases(win, tmp_path)
    assert bare["printed"] == "" and bare["line"] is None and bare["statement_after"] is None and bare["statement_inverted"] is None
    lead = SR.Driver.probe_judgment_lead([(case, [bare])])                               # the lead says so without crashing
    assert "it printed nothing the factory kept" in lead and "the check it broke" in lead and "(``)" not in lead


def test_printed_lines_limits_at_and_beyond(tmp_path):
    text = "\n".join(["", "a" * 160, "  ", "b" * 161, "c  \t d", "fourth line is dropped"])
    win = window(tmp_path, [("CASE-A", "a1", "passed", "cannot")], failure=text)
    printed = WR.probe_judgment_cases(win, tmp_path)[0][1][0]["printed"].split(" / ")
    assert printed == ["a" * 160, "b" * 159 + "…", "c d"]                                # AT 160 whole, BEYOND cut with the mark; 3 lines; folded


def test_lead_shows_test_check_and_printed_text():
    pairs = [("LOCAL-1_TC_001", [item_of(iid="adds one item", printed="Error: Expected 1 / Received 2", why="it may have thrown earlier")]),
             ("LOCAL-1_TC_002", [item_of(iid="removes it", line=40, statement_inverted="expect(a).toBe(0)", printed="boom", why="no way to tell")])]
    lead = SR.Driver.probe_judgment_lead(pairs)
    assert lead.startswith("The review of this window of tests is finished, but for 2 test case(s) the factory could not prove that a test "
                           "would catch a broken product. It broke one check in each test and ran it; the test failed, and the code reviewer "
                           "could not tell whether it failed because of that check or for another reason: ")
    assert ("LOCAL-1_TC_001: the test \"adds one item\", the check broken at line 12 (`" + STATEMENT + "`), it printed "
            "\"Error: Expected 1 / Received 2\"; the reviewer said: it may have thrown earlier") in lead
    assert "LOCAL-1_TC_002: the test \"removes it\", the check broken at line 40 (`expect(a).toBe(0)`), it printed \"boom\"" in lead
    assert lead.endswith("Only you can decide what happens to these tests.\n\n"
                         "Answer `go on` to accept them as not proved: your words are recorded for these cases only, and the report lists them "
                         "as not proved. Answer `rework` to send them back to their author with your words. An earlier answer about tests the "
                         "factory's tool could not read does not cover these.")
    assert SR.Driver.probe_judgment_lead([("C", [item_of(statement_inverted="a `b` c")])]).count("`") == 2 + 2 * 2   # a backtick inside is not a fence


def test_lead_limits_at_and_beyond():
    def lead_of(**over):
        return SR.Driver.probe_judgment_lead([("CASE-A", [item_of(**over)])])
    assert f"(`{'s' * 120}`)" in lead_of(statement_inverted="s" * 120)                      # AT 120: whole
    assert f"(`{'s' * 119}…`)" in lead_of(statement_inverted="s" * 121) and "s" * 121 not in lead_of(statement_inverted="s" * 121)
    assert f"said: {'w' * 160}." in lead_of(why="w" * 160)                               # AT 160: whole
    assert f"said: {'w' * 159}…." in lead_of(why="w" * 161)
    assert "said: no reason was given." in lead_of(why="")


def test_lead_cuts_at_ten_tests_and_counts_the_rest():
    def many(count):
        return SR.Driver.probe_judgment_lead([(f"CASE-{n:02d}", [item_of(iid=f"t{n:02d}")]) for n in range(count)])
    ten, eleven = many(10), many(11)
    assert "CASE-09" in ten and "more" not in ten.split("Only you can decide")[0]       # 10 -> all listed, no tail
    assert "CASE-09" in eleven and "CASE-10" not in eleven and ", and 1 more. Only you can decide" in eleven
    many_in_one = SR.Driver.probe_judgment_lead([("CASE-A", [item_of(iid=f"t{n:02d}") for n in range(13)])])   # tests count, not cases
    assert "t09" in many_in_one and "t10" not in many_in_one and ", and 3 more." in many_in_one and "1 test case(s)" in many_in_one


def test_lead_obeys_human_text_rules():
    lead = SR.Driver.probe_judgment_lead([("LOCAL-1_TC_001", [item_of(iid="adds one item", printed="Error: Expected 1 / Received 2")])])
    assert human_text.shape_problems(lead) == []
    for forbidden in ("waiver", ".py", "S5-qa", "probe_judgment", "probe_gap", "work/", "judgment_facts", "cannot_judge", "dispatch"):
        assert forbidden not in lead
    assert human_text.shape_problems(lead + " Run waiver.py --task X --stage S5 to record it.")      # negative control: the check can fail


def test_person_carries_cases_through_asked_and_held_question():
    """`_person_of` -> `ask` -> `held_question`: the keys travel on the `rows` pattern, on a real driver over a temp project."""
    import harness
    from story_run_common import driver_for, seed
    root, task_root, env = seed("QA-9")
    try:
        driver = driver_for(root, env, "QA-9")
        state = {"kind": "refusal", "stage": "S5", "dispatch": "S5-qa-code-critic-2", "why": "threshold", "probe_judgment_cases": ["CASE-A", "CASE-B"]}
        options = [{"norm": "go on", "move": "go_on_as_is"}, {"norm": "stop", "move": "stop_story"}]
        person = driver._person_of(state, "lead\n\nbody", options)
        assert person.probe_judgment_cases == ("CASE-A", "CASE-B") and person.probe_gap_cases == ()
        driver.ask(person)
        assert driver.state["asked"]["probe_judgment_cases"] == ["CASE-A", "CASE-B"]
        assert driver.held_question("held").probe_judgment_cases == ("CASE-A", "CASE-B")
        plain = driver._person_of(dict(state, probe_judgment_cases=[]), "lead\n\nbody", options)
        driver.ask(plain)
        assert "probe_judgment_cases" not in driver.state["asked"]                        # no cases, no key (E5.3)
        assert driver.held_question("held").probe_judgment_cases == ()
    finally:
        harness.cleanup(root)


def test_seam_go_on_records_not_proved_per_case(capsys):
    rig = Rig()
    rig.choose("go_on_as_is", "go on", probe_judgment_cases=["LOCAL-1_TC_001", "LOCAL-1_TC_002"], block="")
    assert rig.passes == [("S5", "probe not proved: LOCAL-1_TC_001", "state/words/a.txt"), ("S5", "probe not proved: LOCAL-1_TC_002", "state/words/a.txt")]
    assert rig.moves == []                                                               # nothing went on to the conductor
    assert "S5: LOCAL-1_TC_001, LOCAL-1_TC_002 stay not proved on your word" in capsys.readouterr().out
    for _s, block, _f in rig.passes:
        assert not block.startswith("probe gap:") and waiver.block_name_row(block, "S5") is not None   # never a probe-gap word (E5.1)
    both = Rig()
    both.choose("go_on_as_is", "go on", probe_judgment_cases=["CASE-A"], block="some block")
    assert [p[1] for p in both.passes] == ["some block", "probe not proved: CASE-A"]    # the block pass runs first


def test_seam_refused_word_is_held_and_earlier_ones_stay(capsys):
    rig = Rig(refuse_at="probe not proved: CASE-B")
    with pytest.raises(RuntimeError, match="not proved for CASE-B"):
        rig.choose("go_on_as_is", "go on", probe_judgment_cases=["CASE-A", "CASE-B", "CASE-C"], block="")
    assert [p[1] for p in rig.passes] == ["probe not proved: CASE-A"]                    # E5.5: recorded stays, the later one is not tried
    assert "stay not proved on your word" not in capsys.readouterr().out


def test_seam_older_question_without_cases_is_todays_path():
    older = Rig()                                                                         # an `asked` written before N5: no key (E5.7)
    older.choose("go_on_as_is", "go on", block="")
    assert older.passes == [] and len(older.moves) == 1


def test_seam_rework_goes_to_conductor_with_words():
    rig = Rig()
    rig.choose("rework_stage", "rework", probe_judgment_cases=["CASE-A"], block="")
    assert rig.passes == [] and len(rig.moves) == 1                                       # no word recorded for a token not chosen
    assert rig.moves[0]["move"] == "rework_stage" and rig.moves[0]["words"] == "go on"    # the conductor gets the person's words (`original_words`)
    for move, token in (("retry_step", "retry"), ("stop_story", "stop")):
        other = Rig()
        try:
            other.choose(move, token, probe_judgment_cases=["CASE-A"], block="")
        except Exception:
            pass
        assert other.passes == []


def gate(tmp_path, win):
    d, refusal, seen = refusal_rig(tmp_path, win)
    d.probe_judgment_lead = SR.Driver.probe_judgment_lead
    with pytest.raises(RuntimeError, match="seam"):
        SR.Driver.window_round_gate(d, refusal, "S5")
    return seen[0]


def test_judgment_question_before_probe_gap_question(tmp_path):
    win = window(tmp_path, [("CASE-T", "iid t", "passed", "tool"), ("CASE-J", "iid j", "passed", "cannot")])
    state = gate(tmp_path, win)
    assert state["probe_judgment_cases"] == ["CASE-J"] and "probe_gap_cases" not in state     # ONE question per seam (E5.4)
    assert state["lead"] == SR.Driver.probe_judgment_lead(WR.probe_judgment_cases(win, tmp_path))
    pipe = words(tmp_path, "probe not proved: CASE-J")                                         # the person answered; the window is rebuilt
    win["instances"][1]["probe_gap"] = WR.probe_gap_block(tmp_path, win["instances"][1], ["CASE-J"], {}, None, C.probe_not_proved_words(pipe))
    after = gate(tmp_path, win)
    assert after["probe_gap_cases"] == ["CASE-T"] and "probe_judgment_cases" not in after      # the probe-gap question at the next refusal
    assert after["lead"] == SR.Driver.probe_gap_lead([("CASE-T", ["iid t"])])


@pytest.mark.parametrize("rows,what", [([("CASE-A", "iid a", "failed", "cannot")], "red only"),
                                       ([("CASE-A", "iid a", "passed", "unjudged")], "unjudged"),
                                       ([("CASE-A", "iid a", "passed", None)], "never run"),
                                       (None, "no record on disk")])
def test_gate_seam_is_todays_when_no_case_qualifies(tmp_path, rows, what):
    state = gate(tmp_path, window(tmp_path, rows) if rows else None)
    assert "probe_judgment_cases" not in state and state["lead"].endswith("THE FALLBACK LEAD"), what      # E5.3, E5.6


def test_twins_name_the_same_items(tmp_path):
    rows = [("CASE-A", "a1", "passed", "cannot"), ("CASE-B", "b1", "passed", "cannot"), ("CASE-C", "c1", "passed", "cannot"),
            ("CASE-D", "d1", "passed", "tool"), ("CASE-E", "e1", "passed", "unjudged")]
    win = window(tmp_path, rows)
    pipe = {"stage_overrides": [
        {"stage": "S5", "match": "probe not proved: CASE-A", "decision": "go on", "at": LATER},        # names a1
        {"stage": "S5", "match": "probe not proved: CASE-B", "decision": "go on", "at": EARLIER},       # older than the judgment: names nothing
        {"stage": "S5", "match": "probe gap: CASE-C", "decision": "go on", "at": LATER},                # the wrong word for a cannot_judge test
        {"stage": "S5", "match": "probe gap: CASE-D", "decision": "go on", "at": LATER},                # names d1 (tooling)
        {"stage": "S5", "match": "probe not proved: CASE-E", "decision": "go on", "at": LATER}]}        # e1 owes the critic (not cannot_judge): no
    (tmp_path / "pipeline.json").write_text(json.dumps(pipe), encoding="utf-8")
    blocked = {}
    for item in win["instances"]:
        iid = item["instance_id"]
        keys = [case for case, ids in win["scope_instances"].items() if iid in ids]
        block = WR.probe_gap_block(tmp_path, item, keys, C.probe_gap_words(pipe), C.probe_gap_class_word(pipe, [iid] + keys),
                                   C.probe_not_proved_words(pipe))
        if block:
            item["probe_gap"], blocked[iid] = block, block
    named = acceptance.probe_gap_named(win, tmp_path)
    assert set(blocked) == {"a1", "d1"} and set(named) == set(blocked)                    # the window and the acceptance name the same items
    assert blocked["a1"]["named_by"] == named["a1"]["key"] == "probe not proved: CASE-A"
    assert named["d1"]["key"] == "CASE-D"                                                  # the ordinary word is unchanged for the other items


@pytest.mark.parametrize("word", ["probe gap: the_test", "probe gap: CASE-A", "probe gap: tooling:typescript", "class"])
@pytest.mark.parametrize("when", [EARLIER, LATER])
def test_unjudged_record_is_named_by_no_probe_gap_word(tmp_path, word, when):
    """F1: a case was named for tooling, the stand was fixed, the re-probe ended `incomplete` / `cause: judgment` and nobody judged it.
    No word - the instance, its case, `tooling:`, the class - names it: it is the code critic's. Window and acceptance agree."""
    win = window(tmp_path, [("CASE-A", "the_test", "passed", "unjudged")])
    item = win["instances"][0]
    match = "probe gap: CASE-Z" if word == "class" else word
    pipe = words(tmp_path, match, at=when, **({"class": C.PROBE_GAP_CLASS} if word == "class" else {}))
    assert C.probe_gap_words(pipe) or C.probe_gap_class_word(pipe, ["CASE-A"])                  # the word IS live
    assert proof_level.probe_owes_judgment(tmp_path, "the_test", item["input_hash"]) == "unjudged"
    assert WR.probe_gap_block(tmp_path, item, ["CASE-A"], C.probe_gap_words(pipe), C.probe_gap_class_word(pipe, ["CASE-A"]),
                              C.probe_not_proved_words(pipe)) is None
    item["probe_gap"] = {"verdict": "incomplete", "record": None, "why": "w", "named_by": word, "words": "go on", "at": when}   # a block someone wrote
    assert acceptance.probe_gap_named(win, tmp_path) == {}
    assert WR.probe_judgment_cases(win, tmp_path) == []                                         # and nobody asks the person about it either


def test_unjudged_rule_keeps_the_other_words(tmp_path):
    """F1 controls: the same words still name a tooling test, and `cannot_judge` keeps its own word."""
    win = window(tmp_path, [("CASE-A", "the_test", "passed", "tool"), ("CASE-B", "other", "passed", "cannot")])
    pipe = words(tmp_path, "probe gap: CASE-A", "probe not proved: CASE-B")
    blocks = {}
    for item in win["instances"]:
        keys = [case for case, ids in win["scope_instances"].items() if item["instance_id"] in ids]
        blocks[item["instance_id"]] = WR.probe_gap_block(tmp_path, item, keys, C.probe_gap_words(pipe), None, C.probe_not_proved_words(pipe))
        item["probe_gap"] = blocks[item["instance_id"]] or {"verdict": "incomplete"}
    assert blocks["the_test"]["named_by"] == "CASE-A" and blocks["other"]["named_by"] == "probe not proved: CASE-B"
    assert set(acceptance.probe_gap_named(win, tmp_path)) == {"the_test", "other"}


def test_case_with_cannot_judge_and_tooling_test_gets_the_judgment_question(tmp_path):
    """S3: every owed item is `cannot_judge` or could-not-run: the case is listed, only the `cannot_judge` test is shown, the word names it only."""
    win = window(tmp_path, [("CASE-A", "judged one", "passed", "cannot"), ("CASE-A", "tooling one", "passed", "tool")])
    (case, shown), = WR.probe_judgment_cases(win, tmp_path)
    assert case == "CASE-A" and [item["iid"] for item in shown] == ["judged one"]
    assert WR.probe_gap_cases(win, tmp_path) == []                                              # the doors question waits (ONE question per seam)
    pipe = words(tmp_path, "probe not proved: CASE-A")
    for item in win["instances"]:
        block = WR.probe_gap_block(tmp_path, item, ["CASE-A"], {}, None, C.probe_not_proved_words(pipe))
        assert (block is not None) is (item["instance_id"] == "judged one")                     # the tooling test is not named by it
        item["probe_gap"] = block or {"verdict": "incomplete"}
    assert set(acceptance.probe_gap_named(win, tmp_path)) == {"judged one"}
    assert [c for c, _ids in WR.probe_gap_cases(win, tmp_path)] == ["CASE-A"]                    # next refusal: the tooling test is asked for itself
    assert WR.probe_judgment_cases(win, tmp_path) == []
    # a never-run sibling or an unjudged one still keeps the case off the list
    for how in (None, "unjudged"):
        other = window(tmp_path / str(how), [("CASE-A", "judged one", "passed", "cannot"), ("CASE-A", "third", "passed", how)])
        assert WR.probe_judgment_cases(other, tmp_path / str(how)) == []


def controller_text(tmp_path, win) -> str:
    from test_probe_gap_door import StubController, controller
    return controller.Controller._s5_completion_problems(StubController(tmp_path), {"id": "S5-qa-code-critic-2"}, {"window": win}, {}, [])[0][1]


def test_controller_door_follows_the_probe_record(tmp_path):
    """F4: the refusal names the door of what each owed test's record says, not the `probe gap:` word for every one of them."""
    import probe_by_code as PBC
    unjudged = controller_text(tmp_path / "u", window(tmp_path / "u", [("CASE-U", "iid u", "passed", "unjudged")]))
    assert PBC.JUDGE_DOOR in unjudged and "iid u" in unjudged
    assert "probe gap: <case key>" not in unjudged and "probe not proved: <case key>" not in unjudged     # the word is no road for it (F1)
    cannot = controller_text(tmp_path / "c", window(tmp_path / "c", [("CASE-C", "iid c", "passed", "cannot")]))
    assert 'waiver.py --task QA-9 --stage S5 --block "probe not proved: <case key>"' in cannot and "<T>" not in cannot
    assert "The case keys this window needs: CASE-C (one record each)." in cannot
    assert "probe gap: <case key>" not in cannot and PBC.JUDGE_DOOR not in cannot
    tooling = controller_text(tmp_path / "t", window(tmp_path / "t", [("CASE-T", "iid t", "passed", "tool")]))
    assert 'waiver.py --task QA-9 --stage S5 --block "probe gap: <case key>"' in tooling              # the old door, for what it serves
    assert "probe not proved: <case key>" not in tooling and PBC.JUDGE_DOOR not in tooling
    mixed = controller_text(tmp_path / "m", window(tmp_path / "m", [("CASE-U", "iid u", "passed", "unjudged"), ("CASE-C", "iid c", "passed", "cannot"),
                                                                    ("CASE-T", "iid t", "passed", "tool")]))
    assert PBC.JUDGE_DOOR in mixed and "probe not proved: <case key>" in mixed and "probe gap: <case key>" in mixed
    assert "The case keys this window needs: CASE-T (one record each)." in mixed                      # the old keys line lists tooling cases only


def test_controller_unrecorded_gap_door_follows_the_probe_record(tmp_path, monkeypatch):
    """F4, the second refusal (`_s5_gap_problems`): the same helper."""
    import probe_by_code as PBC
    from test_probe_gap_door import StubController, controller
    monkeypatch.setattr(acceptance, "validate_window", lambda w, r: [f"{acceptance.PROBE_GAP_UNRECORDED_KIND}:iid c"])
    win = window(tmp_path, [("CASE-C", "iid c", "passed", "cannot")])
    text = controller.Controller._s5_gap_problems(StubController(tmp_path), {"id": "S5-qa-code-critic-2"}, {}, win)[0][1]
    assert "probe not proved: <case key>" in text and "probe gap: <case key>" not in text and PBC.JUDGE_DOOR not in text
    win = window(tmp_path / "t", [("CASE-T", "iid t", "passed", "tool")])
    text = controller.Controller._s5_gap_problems(StubController(tmp_path), {"id": "S5-qa-code-critic-2"}, {}, win)[0][1]
    assert "probe gap: <case key>" in text and "probe not proved: <case key>" not in text


def test_lead_shows_the_check_not_the_marker_expression():
    """F5: the person reads the plain inversion; the written statement carries the factory's own marker expression."""
    lead = SR.Driver.probe_judgment_lead([("CASE-A", [item_of()])])
    assert f"(`{STATEMENT}`)" in lead and "qa-probe" not in lead and "abc123def456" not in lead
    assert human_text.shape_problems(lead) == []
    plain = SR.Driver.probe_judgment_lead([("CASE-A", [item_of(statement_inverted=None, statement_after=STATEMENT)])])
    assert f"(`{STATEMENT}`)" in plain                                                          # a probe that wrote no marker: the one statement there is


def test_off_target_door_says_the_true_road():
    """S2: no new word for off target; the door names `finish --unresolved --reason` by the role and what delivery then says."""
    door = WR.OFF_TARGET_DOOR
    for needle in ("--at <n>", "a Python test has no `--at`", "story_step.py finish", "--unresolved <why>", '--reason "',
                   "requires a current sensitivity proof", "No word of the person closes it"):
        assert needle in door, needle
    assert "the person decides" not in door and "probe gap" not in door and "probe not proved" not in door
    assert "--unresolved <why> --reason" in (SCRIPTS / "story_step.py").read_text(encoding="utf-8")      # the door names a command that takes them


# --- N4 (t-2143): a record owed to the critic for any read failure is never offered to the person first -------------------------------

def owed_rows(kind: str) -> list:
    """The rows a run of each NEW kind of record ended with: every one of them answered `cause: judgment` by the real row judge (asserted)."""
    def one(i, status="failed", message="", text="the run printed this"):
        return {"test_id": f"tests.t::test_x[{i}]", "status": status,
                "problems": [{"kind": "error" if status == "error" else "failure", "message": message, "text": text}]}
    return {"error": [one(0, "error", "setup exploded", "Traceback: setup exploded in a fixture")],
            "site_unread": [one(0, text="Error: a text whose place the reader could not find")],
            "pytest_no_site": [one(0, message="ValueError: invalid literal", text="def helper():\n>   int('abc')\nE   ValueError: invalid literal")],
            "param_rows": [one(0), one(1, "error", "setup of b", "Traceback: b")],
            "rows_cut": [one(i) for i in range(PBC_FACTS_ROWS_MAX + 1)]}[kind]


def owed_probe(root: Path, iid: str, sha: str, kind: str, *, judged: bool = False) -> None:
    """The probe record of `iid` as the road writes it for `kind` (facts built by `judgment_facts` over the rows the judge answered)."""
    import assertion_detectors as AD
    import probe_by_code as PBC
    rows = owed_rows(kind)
    entry = AD.ast_entry(".py")[1]
    detail = {"language": "python", "line": 12, "end_line": 12, "message_marker": "qa-probe-n4", "fires_as": None, "pair": None, "file": "tests/cart.spec.ts"}
    for row in rows:
        got = PBC.judge_probe_row(row, {}, entry, detail, among=False, argv=["python", "-m", "pytest"])
        assert (got["verdict"], got["cause"]) == ("incomplete", "judgment"), (kind, got)
    facts = PBC.judgment_facts({}, rows[0], {}, dict(detail, statement_after=WRITTEN, statement_inverted=STATEMENT), entry, rows=rows)
    record = {"test_file_sha256": sha, "verdict": "incomplete", "cause": "judgment", "language": "python", "judgment_facts": facts}
    if judged:
        record["judgment"] = {"verdict": "cannot_judge", "quote": "", "why": "twelve rows shown", "by": "S5-qa-code-critic-2", "at": JUDGED_AT, "facts_sha": "x"}
    path = proof_level.probe_record_path(root, iid)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record), encoding="utf-8")


PBC_FACTS_ROWS_MAX = 12     # the cap of `judgment_facts.rows` (`probe_by_code.FACTS_ROWS_MAX`; asserted equal below)


def owed_window(root: Path, kind: str, *, judged: bool = False) -> dict:
    import probe_by_code as PBC
    assert PBC.FACTS_ROWS_MAX == PBC_FACTS_ROWS_MAX
    owed_probe(root, "iid a", "hash-0", kind, judged=judged)
    return {"scope_instances": {"CASE-A": ["iid a"]},
            "instances": [{"instance_id": "iid a", "input_hash": "hash-0", "outcome": "passed", "change_disposition": "new_or_changed"}]}


KINDS = ["error", "site_unread", "pytest_no_site", "param_rows", "rows_cut"]


@pytest.mark.parametrize("kind", KINDS)
def test_error_row_not_offered_as_gap(tmp_path, kind):
    """E4.3: `probe_could_not_run` is false for `judgment`, so no new kind of record (an error row, a row with no place, several rows, a
    cut list) reaches the `probe gap` question: its lists are empty, and the owed record stands as `unjudged` (the critic's)."""
    win = owed_window(tmp_path, kind)
    assert proof_level.probe_could_not_run(tmp_path, "iid a", "hash-0") is False
    assert proof_level.probe_owes_judgment(tmp_path, "iid a", "hash-0") == "unjudged"
    assert WR.probe_gap_cases(win, tmp_path) == [] and WR.probe_judgment_cases(win, tmp_path) == []
    pipe = words(tmp_path, "probe gap: CASE-A", "probe gap: tooling:python", "probe gap: iid-a", "probe not proved: CASE-A")
    item = win["instances"][0]
    assert WR.probe_gap_block(tmp_path, item, ["CASE-A"], C.probe_gap_words(pipe), C.probe_gap_class_word(pipe, ["CASE-A"]),
                              C.probe_not_proved_words(pipe)) is None       # no word of the person names it


@pytest.mark.parametrize("kind", KINDS)
def test_person_is_last(tmp_path, kind):
    """The person is last: for a record of each new kind that the critic has NOT judged, the seam (`window_round_gate`, walked as it is,
    not the predicate) offers neither `probe not proved` nor `probe gap` - the fallback question stands; after the critic's
    `cannot_judge` the SAME record is offered the `probe not proved` word (the control: the walk can see the door when it is open)."""
    state = gate(tmp_path / "unjudged", owed_window(tmp_path / "unjudged", kind))
    assert "probe_judgment_cases" not in state and "probe_gap_cases" not in state and state["lead"].endswith("THE FALLBACK LEAD"), (kind, state)
    open_ = gate(tmp_path / "judged", owed_window(tmp_path / "judged", kind, judged=True))
    assert open_["probe_judgment_cases"] == ["CASE-A"] and "probe_gap_cases" not in open_, (kind, open_)


def main() -> int:
    return pytest.main([__file__, "-q", "-p", "no:cacheprovider"])


if __name__ == "__main__":
    sys.exit(main())
