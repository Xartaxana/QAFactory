"""probe_by_code.py: the joint judge of one run of several edited checks (t-2064 P4a item 2), on stub rows.

Pure functions only: a stub report row in, the judge's return value out. No walk, no runner, no record: what needs a run (the
alone rerun itself, the bytes each run saw, the retry flags) is part 3's (`_walk_plan`) and is named in the report.

A row is the shared reader's shape: `{test_id, status, problems: [{kind, message, text}]}`. A token is 12 hex characters.
Runnable alone (`python -B scripts/tests/test_probe_joint_judge.py`) and collected by pytest."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import assertion_detectors as AD  # noqa: E402
import probe_by_code as PBC  # noqa: E402

ENTRY = {"compiled": False, "builds_by_default": [], "marker_read": ["message", "text"], "frames": [], "skip_frames": [],
         "frame_path": "", "interruption_texts": ["Test timeout of \\d+ms exceeded"]}
PYTEST_ENTRY = dict(ENTRY, marker_read=["message"], interruption_texts=[])
CUT = "Test timeout of 6000ms exceeded."


def tok(n: int) -> str:
    return f"{n:012x}"


def failed(*bodies, message="", extra=()) -> dict:
    """A failed row: one `failure` problem per body (its text), after the optional `message`; `extra` problems follow."""
    problems = [{"kind": "failure", "message": message if i == 0 else "", "text": body} for i, body in enumerate(bodies)]
    return {"test_id": "t.spec.ts::x", "status": "failed", "problems": problems + list(extra)}


def block(token: str, tail: str = "expect(received).toBe(expected)") -> str:
    return f"Error: qa-probe-{token} msg\n\n{tail}\n"


# --- step 1: `_problem_texts`, the one marker reader, `_cut_by_runner` ------------------------------------------------------

def test_all_problems_read():
    """Two `failure` problems, the token only in the second: read; a row of one problem with the token elsewhere is not."""
    token = tok(1)
    row = {"status": "failed", "problems": [{"kind": "failure", "message": "first", "text": "nothing here"},
                                            {"kind": "failure", "message": "second", "text": block(token)}]}
    assert PBC._problem_texts(row) == ["first", "nothing here", "second", block(token)]
    answer = PBC._row_by_marker(row, token, {}, ENTRY, {"message_head": ""})
    assert answer["verdict"] == "intended_failure" and answer["proved_by"] == "marker"
    assert PBC._row_by_marker(row, tok(2), {}, ENTRY, {"message_head": ""}) is None


def test_error_problem_is_read_too():
    token = tok(3)
    row = {"status": "failed", "problems": [{"kind": "failure", "message": "", "text": "x"},
                                            {"kind": "error", "message": "", "text": block(token)}]}
    assert block(token) in PBC._problem_texts(row)
    assert PBC._row_by_marker(row, token, {}, ENTRY, {"message_head": ""})["verdict"] == "intended_failure"


def test_marker_in_system_out_not_read():
    """The token only in a system-out problem, in a skipped one or in a step title: never read, never proved."""
    token = tok(4)
    row = failed("plain failure", extra=[{"kind": "system-out", "message": "", "text": block(token)},
                                         {"kind": "skipped", "message": block(token), "text": ""}])
    row["title"] = block(token)
    assert PBC._problem_texts(row) == ["plain failure"]
    assert PBC._row_by_marker(row, token, {}, ENTRY, {"message_head": ""}) is None


def test_marker_read_fields_are_the_entrys():
    """`marker_read` is data: a runner that echoes values in its text (pytest) reads the message only."""
    token = tok(5)
    row = failed(block(token), message="short")
    assert PBC._problem_texts(row, ["message"]) == ["short"]
    assert PBC._row_by_marker(row, token, {}, PYTEST_ENTRY, {"message_head": ""}) is None
    assert PBC._row_by_marker(row, token, {}, ENTRY, {"message_head": ""})["verdict"] == "intended_failure"


def test_token_counts_only_as_its_exact_12_hex():
    """A longer hex run around the token makes it part of another word; the token beside text is read."""
    token = tok(6)
    for text, expected in ((f"qa-probe-{token} msg", True), (f"qa-probe-{token}0 msg", False), (f"qa-probe-a{token} msg", False),
                           (f"x{token}", True), (f"[{token}]", True), ("", False)):
        row = failed(text)
        assert (PBC._row_by_marker(row, token, {}, ENTRY, {"message_head": ""}) is not None) is expected, text
    assert PBC._row_by_marker(failed("anything"), "", {}, ENTRY, {"message_head": ""}) is None


def test_problem_texts_edge_inputs():
    assert PBC._problem_texts({}) == [] and PBC._problem_texts({"problems": None}) == []
    assert PBC._problem_texts({"problems": [None, {"kind": "failure", "message": None, "text": 3}]}) == []
    assert PBC._row_by_marker({"status": "failed", "problems": []}, tok(7), {}, ENTRY, {"message_head": ""}) is None


def test_one_marker_reader_in_a_row():
    """AR-13: every read of a token in a row goes through `_row_by_marker` (`_problem_texts` + `_token_in`)."""
    text = (Path(PBC.__file__)).read_text(encoding="utf-8")
    assert text.count("def _row_by_marker(") == 1 and text.count("def _problem_texts(") == 1
    assert "failure_problem(row)" not in text.split("def _row_by_marker(")[1].split("\ndef ")[0]


def test_cut_by_runner_reads_the_entrys_words():
    assert PBC._cut_by_runner(["x", CUT], ENTRY) is True
    assert PBC._cut_by_runner(["Test timeout of 6000ms exceeded"], ENTRY) is True      # no full stop: the word list decides
    assert PBC._cut_by_runner(["Error: element(s) not found"], ENTRY) is False
    assert PBC._cut_by_runner([CUT], PYTEST_ENTRY) is False        # no words: nothing to demote on that language
    assert PBC._cut_by_runner([CUT], {}) is False and PBC._cut_by_runner([], ENTRY) is False
    assert PBC._cut_by_runner([CUT], dict(ENTRY, interruption_texts=["(broken"])) is False     # a regex that does not compile: no cut


def test_cut_never_proves_in_the_reader():
    """`_cut_by_runner` only answers a question; `_row_by_marker` stays the same on a cut text (the judge demotes, step C)."""
    token = tok(8)
    row = failed(block(token) + "\n" + CUT)
    assert PBC._cut_by_runner(PBC._problem_texts(row), ENTRY) is True
    assert PBC._row_by_marker(row, token, {}, ENTRY, {"message_head": ""})["verdict"] == "intended_failure"
    assert AD.interruption_texts(ENTRY) == ["Test timeout of \\d+ms exceeded"]


# --- steps A-D and F: `_judge_joint_rows` on stub rows ---------------------------------------------------------------------

def keys_of(n: int) -> list:
    return [f"t.spec.ts:{10 + i}" for i in range(n)]


def judge(rows, keys, *, read=None, kinds="invert", greens=None, entry=ENTRY, location="", checks=None, runs=None, tokens=None):
    """The judge's return value for `keys` as ONE run. `read` = the keys whose token the row carries is the caller's business
    (it builds the row); `tokens` defaults to one distinct token per key; `kinds` is one `probe_kind` for all or a dict."""
    tokens = {key: tok(100 + i) for i, key in enumerate(keys)} if tokens is None else tokens
    kinds = kinds if isinstance(kinds, dict) else {key: kinds for key in keys}
    details = [{"key": key, "probe_kind": kinds[key], "line": int(key.rsplit(":", 1)[1]), "file": "t.spec.ts"} for key in keys]
    checks = checks if checks is not None else [{"key": key, "file": "t.spec.ts", "line": int(key.rsplit(":", 1)[1]),
                                                 "end_line": int(key.rsplit(":", 1)[1])} for key in keys]
    plan = {"checks": checks, "runs": runs if runs is not None else [{"run": 1, "keys": list(keys)}]}
    facts = {"entry": entry, "site": {"location": location} if location else {}, "author_green": greens or {}, "argv": ["npx", "x"]}
    return PBC._judge_joint_rows(rows, tokens, list(keys), plan, details, facts), tokens


def row_with(tokens: dict, keys: list, present, tail="", status="failed") -> dict:
    """A failed row with one block per key in `present` (their own tokens) and `tail` after them."""
    body = "".join(block(tokens[k]) for k in present) + tail
    return failed(body) if status == "failed" else {"test_id": "x", "status": status, "problems": []}


def run(keys, present, *, tail="", **kw):
    tokens = {key: tok(100 + i) for i, key in enumerate(keys)}
    (out, move), _ = judge([row_with(tokens, keys, present, tail)], keys, tokens=tokens, **kw)
    return out, move


def test_three_soft_one_run_three_proved():
    keys = keys_of(3)
    out, move = run(keys, keys)
    assert move == "go on" and list(out) == keys
    for key in keys:
        assert out[key]["verdict"] == "intended_failure" and out[key]["proved_by"] == "marker", key
        assert out[key]["check_key"] == key and out[key]["read_in_joint"] is True and out[key]["rerun_alone"] is False


def test_one_absent_named_and_rerun_alone():
    """The middle check printed nothing: it is named, `not_reached`, rerun alone; the last READ key is demoted with it (EP-V),
    the first is proved by its own token."""
    a, b, c = keys_of(3)
    out, move = run([a, b, c], [a, c])
    assert out[a]["verdict"] == "intended_failure"
    assert out[b]["verdict"] == "not_reached" and out[b]["rerun_alone"] is True and out[b]["read_in_joint"] is False
    assert out[b]["check_key"] == b and "marker" not in str(out[b].get("proved_by"))
    assert out[c]["verdict"] == "not_reached" and out[c]["rerun_alone"] is True and out[c]["demoted"] is True
    assert move == "go on"


def test_row_passed_no_rerun():
    keys = keys_of(3)
    (out, move), _ = judge([{"test_id": "x", "status": "passed", "problems": []}], keys, kinds="actual")
    assert move == "go on" and all(o["verdict"] == "no_failure" and o["rerun_alone"] is False for o in out.values())
    assert all(o["read_in_joint"] is False for o in out.values())


def test_passed_row_with_a_token_in_no_problem_settles_nothing_by_it():
    """Position invariant: only a passed row settles a not-fire; a token cannot sit in a passed row's problems, and a skipped
    child of a passed row is never read (its kind is not `failure` or `error`)."""
    keys = keys_of(1)
    token = tok(100)
    row = {"test_id": "x", "status": "passed", "problems": [{"kind": "skipped", "message": block(token), "text": ""}]}
    (out, _move), _ = judge([row], keys, kinds="actual")
    assert out[keys[0]]["verdict"] == "no_failure"


def test_run_of_one_absent_is_critic_no_rerun():
    """A throw in the check's own argument, a helper's throw: the failure is there, the token is not."""
    (key,) = keys_of(1)
    out, move = run([key], [], tail="Error: boom from thrower\n")
    answer = out[key]
    assert answer["verdict"] == "incomplete" and answer["cause"] == "judgment" and answer["rerun_alone"] is False
    assert answer["read_in_joint"] is False and move == "go on" and answer["observed"]["message_head"] != "x"


def test_cut_last_token_rerun_when_one_absent():
    """P0 s4's body: n1..n5 printed their marker, a timeout line, n6..n8 nothing. Pinned on the structure, never on an index."""
    keys = keys_of(8)
    out, move = run(keys, keys[:5], tail=CUT + "\n\nError: target closed\n")
    assert [out[k]["verdict"] for k in keys[:4]] == ["intended_failure"] * 4
    assert [out[k]["rerun_alone"] for k in keys] == [False] * 4 + [True] * 4
    assert out[keys[4]]["demoted"] is True and out[keys[4]]["read_in_joint"] is False
    assert all(out[k]["verdict"] == "not_reached" for k in keys[4:]) and move == "go on"
    # the cut moves with load: the same body with the cut after n6 reads the same way
    out, _ = run(keys, keys[:6], tail=CUT + "\n")
    assert [k for k in keys if out[k]["rerun_alone"]] == keys[5:]


def test_cut_text_all_present_demotes_last():
    keys = keys_of(3)
    out, _ = run(keys, keys, tail=CUT)
    assert [out[k]["verdict"] for k in keys] == ["intended_failure", "intended_failure", "not_reached"]
    assert out[keys[2]]["rerun_alone"] is True and out[keys[2]]["interrupted"] is True


def test_cut_run_of_one_goes_to_critic():
    (key,) = keys_of(1)
    out, move = run([key], [key], tail=CUT)
    answer = out[key]
    assert answer["verdict"] == "incomplete" and answer["cause"] == "judgment" and answer["interrupted"] is True
    assert answer["rerun_alone"] is False and answer["read_in_joint"] is False and move == "go on"
    assert "proved_by" not in answer


def test_cut_never_proves():
    """Whatever the group's size or the position of the cut line: the demoted key is never `intended_failure`."""
    for n in (1, 2, 4):
        keys = keys_of(n)
        for tail in (CUT, "x\n" + CUT + "\ny"):
            out, _ = run(keys, keys, tail=tail)
            assert out[keys[-1]]["verdict"] != "intended_failure" and "proved_by" not in out[keys[-1]], (n, tail)
    out, _ = run(keys_of(2), keys_of(2), tail=CUT, entry=dict(ENTRY, interruption_texts=[]))           # no words, no cut: the entry decides
    assert all(o["verdict"] == "intended_failure" for o in out.values())


def test_joint_judge_reads_the_second_of_two_failure_problems():
    """Two `failure` problems of ONE row, the token only in the second: read and proved."""
    (key,) = keys_of(1)
    token = tok(100)
    row = {"test_id": "x", "status": "failed", "problems": [{"kind": "failure", "message": "m", "text": "nothing"},
                                                            {"kind": "failure", "message": "", "text": block(token)}]}
    (out, _), _ = judge([row], [key], tokens={key: token})
    assert out[key]["verdict"] == "intended_failure"


def test_joint_judge_leaves_a_system_out_marker_incomplete_and_not_read_in_joint():
    (key,) = keys_of(1)
    token = tok(100)
    row = failed("plain", extra=[{"kind": "system-out", "message": "", "text": block(token)}])
    (out, _), _ = judge([row], [key], tokens={key: token})
    assert out[key]["verdict"] == "incomplete" and out[key]["read_in_joint"] is False


def test_only_marker_proves():
    """A failure whose wording and place fit the check, with no token: the role, never `intended_failure`."""
    (key,) = keys_of(1)
    row = failed("Error: expect(received).toBe(expected) // Object.is equality\nExpected: 2\nReceived: 1\n")
    (out, move), _ = judge([row], [key], location="t.spec.ts:10")
    assert out[key]["verdict"] == "incomplete" and out[key]["cause"] == "judgment" and "proved_by" not in out[key] and move == "go on"


def test_model_red_author_goes_to_critic():
    (key,) = keys_of(1)
    out, _ = run([key], [key], kinds="actual", greens={key: False})
    answer = out[key]
    assert answer["verdict"] == "incomplete" and answer["cause"] == "judgment" and answer["author_green"] is False
    assert answer["read_in_joint"] is True and "proved_by" not in answer


def test_author_unknown_critic():
    (key,) = keys_of(1)
    for greens in ({}, {key: None}):
        out, _ = run([key], [key], kinds="find", greens=greens)
        assert out[key]["verdict"] == "incomplete" and out[key]["author_green"] is None and out[key]["cause"] == "judgment"


def test_model_green_author_proves():
    keys = keys_of(2)
    out, _ = run(keys, keys, kinds={keys[0]: "actual", keys[1]: "find"}, greens={keys[0]: True, keys[1]: False})
    assert out[keys[0]]["verdict"] == "intended_failure" and out[keys[0]]["author_green"] is True
    assert out[keys[1]]["verdict"] == "incomplete" and out[keys[1]]["author_green"] is False


def test_invert_needs_no_green():
    (key,) = keys_of(1)
    out, _ = run([key], [key], kinds="invert", greens={key: False})
    assert out[key]["verdict"] == "intended_failure" and "author_green" not in out[key]


def test_find_model_pass_is_judgment():
    keys = keys_of(2)
    (out, move), _ = judge([{"test_id": "x", "status": "passed", "problems": []}], keys, kinds="find")
    assert all(o["verdict"] == "incomplete" and o["cause"] == "judgment" and o["rerun_alone"] is False for o in out.values())
    assert move == "go on"


def test_actual_model_pass_is_no_failure():
    keys = keys_of(2)
    (out, _), _ = judge([{"test_id": "x", "status": "passed", "problems": []}], keys, kinds="actual")
    assert all(o["verdict"] == "no_failure" and "cause" not in o for o in out.values())


def test_unknown_kind_is_never_an_inversion():
    """A key with no detail at all reads as a value kind: it needs the author's green (the error goes toward the role)."""
    (key,) = keys_of(1)
    tokens = {key: tok(100)}
    row = failed(block(tokens[key]))
    out, _move = PBC._judge_joint_rows([row], tokens, [key], {"checks": [], "runs": []}, [], {"entry": ENTRY})
    assert out[key]["verdict"] == "incomplete" and out[key]["author_green"] is None


def test_error_row_and_no_row_use_the_existing_rule_for_the_whole_group():
    keys = keys_of(2)
    error = {"test_id": "x", "status": "error", "problems": [{"kind": "error", "message": "setup blew up", "text": ""}]}
    (out, move), _ = judge([error], keys)
    assert all(o["verdict"] == "incomplete" and o["cause"] == "judgment" and o["rerun_alone"] is False for o in out.values())
    assert move == "go on"
    (out, move), _ = judge([], keys)                           # empty rows: no row
    assert all(o["verdict"] == "not_executed" and o["rerun_alone"] is False for o in out.values()) and move == "go on"
    (out, _), _ = judge([{"test_id": "x", "status": "skipped", "problems": []}], keys)
    assert all(o["verdict"] == "not_executed" for o in out.values())


def test_failed_row_with_token_outranks_an_error_row_beside_it():
    (key,) = keys_of(1)
    token = tok(100)
    rows = [{"test_id": "x", "status": "error", "problems": [{"kind": "error", "message": "e", "text": ""}]}, failed(block(token))]
    (out, _), _ = judge(rows, [key], tokens={key: token})
    assert out[key]["verdict"] == "intended_failure"


def test_token_read_outranks_the_location():
    """Position invariant: the failing site names an unrelated line, the key's own token still stands (steps C and E only demote)."""
    keys = keys_of(2)
    out, _ = run(keys, keys, location="t.spec.ts:999")
    assert all(o["verdict"] == "intended_failure" for o in out.values())


def test_empty_edges():
    assert PBC._judge_joint_rows([failed("x")], {}, [], {}, [], {"entry": ENTRY}) == ({}, "go on")
    keys = keys_of(2)
    row = failed("x")
    (out, move), _ = judge([row], keys, tokens={})              # empty tokens: nothing is read, each is rerun alone
    assert all(o["verdict"] == "not_reached" and o["rerun_alone"] is True for o in out.values()) and move == "go on"
    (out, _), _ = judge([row], keys[:1], tokens={})
    assert out[keys[0]]["verdict"] == "incomplete" and out[keys[0]]["rerun_alone"] is False


def test_key_with_no_token_is_never_read():
    """The check has no message slot: its entry in `tokens` is absent or empty; the other key still reads."""
    a, b = keys_of(2)
    token = tok(7)
    row = failed(block(token))
    (out, _), _ = judge([row], [a, b], tokens={a: token, b: ""})
    assert out[a]["verdict"] == "not_reached" and out[a]["demoted"] is True        # last READ key, one key absent
    assert out[b]["verdict"] == "not_reached" and out[b]["read_in_joint"] is False
    (out, _), _ = judge([row], [b, a], tokens={a: token})
    assert out[b]["rerun_alone"] is True


def test_doubled_text_of_a_retried_run_reads_each_token_once():
    keys = keys_of(2)
    tokens = {key: tok(100 + i) for i, key in enumerate(keys)}
    body = "".join(block(tokens[k]) for k in keys)
    (out, _), _ = judge([failed(body + body)], keys, tokens=tokens)
    assert [out[k]["verdict"] for k in keys] == ["intended_failure"] * 2 and len(out) == 2


def test_two_tokens_in_one_problem_both_read():
    a, b = keys_of(2)
    ta, tb = tok(1), tok(2)
    (out, _), _ = judge([failed(f"Error: qa-probe-{ta} msg then qa-probe-{tb} msg")], [a, b], tokens={a: ta, b: tb})
    assert out[a]["verdict"] == out[b]["verdict"] == "intended_failure"


def test_token_that_is_a_prefix_of_a_longer_hex_run_is_not_read():
    (key,) = keys_of(1)
    token = tok(5)
    (out, _), _ = judge([failed(f"Error: qa-probe-{token}ff msg")], [key], tokens={key: token})
    assert out[key]["verdict"] == "incomplete" and out[key]["read_in_joint"] is False


# --- step E: the stop (EP-G) and `_earlier_check_at` ------------------------------------------------------------------------
# The walk-level half of each chain test (the bytes each run saw, the third run that does not happen) needs runs: part 3's
# (`_walk_plan`). Here: the judge's return value for the run of `b` in a chain a, b, c of three stopping checks.

A, B, C = keys_of(3)
CHAIN_RUNS = [{"run": 1, "keys": [A]}, {"run": 2, "keys": [B]}, {"run": 3, "keys": [C]}]


def chain_run_of_b(location, kinds="actual", tail="Error: something else\n"):
    """The run of `b`: `a` untouched (not in the edits), `b` edited, `c` not yet run; b's failure carries no token."""
    (out, move), _ = judge([failed(tail)], [B], kinds=kinds, location=location, runs=CHAIN_RUNS,
                           checks=[{"key": k, "file": "t.spec.ts", "line": int(k.rsplit(":", 1)[1]), "end_line": int(k.rsplit(":", 1)[1])}
                                   for k in (A, B, C)])
    return out, move


def test_chain_red_link_stops_walk():
    out, move = chain_run_of_b("t.spec.ts:10")                      # the failure lies on a's span
    assert move == "stop" and list(out) == [B, C]
    for key in (B, C):
        assert out[key]["verdict"] == "not_reached" and out[key]["rerun_alone"] is False and out[key]["plan_remaining"] == [B, C]
        assert out[key]["earlier_check"] == A and "proved_by" not in out[key]


def test_chain_helper_throw_walk_goes_on():
    out, move = chain_run_of_b("helpers.ts:3")                      # a helper's throw: a file the plan does not hold
    assert move == "go on" and list(out) == [B] and out[B]["verdict"] == "incomplete" and out[B]["rerun_alone"] is False


def test_chain_own_argument_throw_walk_goes_on():
    out, move = chain_run_of_b("t.spec.ts:20")                      # b's own span: a throw in b's argument
    assert move == "go on" and out[B]["verdict"] == "incomplete" and out[B]["cause"] == "judgment"


def test_chain_no_location_walk_goes_on():
    out, move = chain_run_of_b("")
    assert move == "go on" and out[B]["verdict"] == "incomplete"


def test_find_breaks_earlier_check_goes_on():
    """A `find` of this run may stand before `a`: the failure on a's span is not shown to be a's own."""
    out, move = chain_run_of_b("t.spec.ts:10", kinds="find")
    assert move == "go on" and list(out) == [B] and out[B]["verdict"] == "incomplete"


def test_earlier_check_at_unit():
    plan = {"checks": [{"key": k, "file": "t.spec.ts", "line": int(k.rsplit(":", 1)[1]), "end_line": int(k.rsplit(":", 1)[1]) + 1}
                       for k in (A, B, C)], "runs": CHAIN_RUNS}
    edit = {"key": B, "probe_kind": "actual", "file": "t.spec.ts", "line": 20}
    assert PBC._earlier_check_at("t.spec.ts:10", plan, {"keys": [B]}, [edit]) == A
    assert PBC._earlier_check_at("t.spec.ts:11", plan, {"keys": [B]}, [edit]) == A            # inside a's span, not only its first line
    assert PBC._earlier_check_at("t.spec.ts:30", plan, {"keys": [B]}, [edit]) is None         # c is LATER than b: never "earlier"
    assert PBC._earlier_check_at("t.spec.ts:20", plan, {"keys": [B]}, [edit]) is None         # b's own span
    assert PBC._earlier_check_at("t.spec.ts:10", plan, {"keys": [A]}, [dict(edit, key=A)]) is None   # nothing before the first check
    assert PBC._earlier_check_at("t.spec.ts:10", plan, {"keys": [B]}, [dict(edit, key=A)]) is None   # a was edited by this run
    assert PBC._earlier_check_at("t.spec.ts:10", plan, {"keys": [B]}, [dict(edit, probe_kind="find")]) is None
    assert PBC._earlier_check_at("t.spec.ts:10", plan, {"keys": [B]}, [dict(edit, line=5)]) is None   # an edit stands above a
    assert PBC._earlier_check_at("", plan, {"keys": [B]}, [edit]) is None
    assert PBC._earlier_check_at("t.spec.ts:10", plan, {"keys": []}, [edit]) is None
    assert PBC._earlier_check_at("t.spec.ts:10", plan, {"keys": ["unknown"]}, [edit]) is None
    assert PBC._earlier_check_at("t.spec.ts:10", {}, {"keys": [B]}, [edit]) is None and PBC._earlier_check_at("t.spec.ts:10", plan, {"keys": [B]}, []) == A
    assert PBC._earlier_check_at("C:\\w\\t.spec.ts:10", plan, {"keys": [B]}, [edit]) == A      # a Windows path: same file by its tail


def test_earlier_check_is_walk_order_not_line_order():
    """A check outside the body runs last: a failure on its span is not an EARLIER link for a body check."""
    plan = {"checks": [{"key": "t.spec.ts:10", "file": "t.spec.ts", "line": 10, "end_line": 10},
                       {"key": "h.ts:5", "file": "h.ts", "line": 5, "end_line": 5}],
            "runs": [{"run": 1, "keys": ["t.spec.ts:10"]}, {"run": 2, "keys": ["h.ts:5"]}]}
    assert PBC._earlier_check_at("h.ts:5", plan, {"keys": ["t.spec.ts:10"]}, []) is None
    assert PBC._earlier_check_at("t.spec.ts:10", plan, {"keys": ["h.ts:5"]}, []) == "t.spec.ts:10"


def test_stop_needs_an_absent_key_and_never_unproves_a_read_one():
    """A joint run b, c, d with the failure on a's span: d's token stands and proves; b (absent) and the demoted last read key stop."""
    keys = keys_of(5)
    a, b, c, d, e = keys
    runs = [{"run": 1, "keys": [a]}, {"run": 2, "keys": [b, c, d]}, {"run": 3, "keys": [e]}]
    tokens = {k: tok(200 + i) for i, k in enumerate(keys)}
    row = failed(block(tokens[c]) + block(tokens[d]))
    checks = [{"key": k, "file": "t.spec.ts", "line": int(k.rsplit(":", 1)[1]), "end_line": int(k.rsplit(":", 1)[1])} for k in keys]
    (out, move), _ = judge([row], [b, c, d], tokens=tokens, location="t.spec.ts:10", runs=runs, checks=checks)
    assert move == "stop" and out[c]["verdict"] == "intended_failure"
    assert out[b]["verdict"] == out[d]["verdict"] == out[e]["verdict"] == "not_reached"
    assert out[b]["plan_remaining"] == [b, d, e] and out[d]["earlier_check"] == a
    # no absent key: the location is never consulted, the proof stands
    row = failed(block(tokens[b]) + block(tokens[c]) + block(tokens[d]))
    (out, move), _ = judge([row], [b, c, d], tokens=tokens, location="t.spec.ts:10", runs=runs, checks=checks)
    assert move == "go on" and all(out[k]["verdict"] == "intended_failure" for k in (b, c, d))


def test_stop_never_on_a_passed_or_error_row():
    keys = keys_of(2)
    runs = [{"run": 1, "keys": [keys[0]]}, {"run": 2, "keys": [keys[1]]}]
    for row in ({"test_id": "x", "status": "passed", "problems": []},
                {"test_id": "x", "status": "error", "problems": [{"kind": "error", "message": "m", "text": ""}]}):
        (out, move), _ = judge([row], [keys[1]], location="t.spec.ts:10", runs=runs, kinds="actual")
        assert move == "go on" and list(out) == [keys[1]]


def test_location_in_the_plan_is_a_fact_not_a_proof():
    """A stop never writes `proved_by` or `intended_failure` for anything."""
    out, move = chain_run_of_b("t.spec.ts:10")
    assert move == "stop" and all("proved_by" not in o and o["verdict"] != "intended_failure" for o in out.values())


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-q", "-p", "no:cacheprovider"]))
