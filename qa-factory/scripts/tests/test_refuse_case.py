#!/usr/bin/env python3
"""TR4-3: the record `{"refused": {...}}` of a case in its request.json has ONE writer, `Driver.refuse_case` (AR-14, AR-15), and the
three callers - `manual_close`, `stand_login_gate`, `walk_refuse_gaps` - write the same bytes they wrote before the helper existed.
The EXPECT_* literals were captured from the code BEFORE the helper (the old inline writes), not computed by the new code.
The id of a dispatch row in the controller has one reader, `_dispatch_ident` (the row's own `id`, else its key).

Mutations this file kills: a fourth inline `"refused": {` writer | a caller changing a field of its record | `plan["refused"]` appended
by the helper for `manual_close` (which has no plan) | a row id read with `or key` outside the helper.

Run: python -B scripts/tests/test_refuse_case.py    or    python -m pytest -p no:cacheprovider scripts/tests/test_refuse_case.py -q
"""
import contextlib
import io
import json
import re
import sys
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import pytest  # noqa: E402
import controller  # noqa: E402
import manual_evidence as ME  # noqa: E402
import story_run  # noqa: E402
import test_walk_lanes as L  # noqa: E402

EXPECT_WALK_GAPS = (
    '{\n  "refused": {\n    "reason": "not walked: for this case\'s account the factory does not know the password: named by one key USER_EMAIL",\n'
    '    "by": "left_unchecked",\n    "door": "record the account\'s two keys on the stand (credentials_by_role: `<role>: <login key> / <password key>`), '
    'or check the case yourself"\n  }\n}\n')
EXPECT_LOGIN = (
    '{\n  "refused": {\n    "reason": "not checked by an agent: the stand\'s sign-in account is not set up for the factory; the person said: '
    '\\"do it by hand\\"",\n    "door": "put the stand\'s test account in the project\'s settings; the next run checks it by hand",\n'
    '    "by": "person_checks"\n  }\n}\n')
EXPECT_REFUSAL = (
    '{\n  "refused": {\n    "reason": "not checked by hand: the record of its walk was refused twice - the build said no",\n'
    '    "by": "left_unchecked",\n    "door": "walk the case again after the build is fixed (retry at gate B), or check it yourself"\n  }\n}\n')
EXPECT_DEFERRED = (
    '{\n  "refused": {\n    "reason": "not checked by an agent: you answered question 3 about it; the person said: \\"do it by hand\\"",\n'
    '    "door": "fix what that question named; the next run checks it by hand",\n    "by": "person_checks"\n  }\n}\n')
EXPECT_CLOSE = (
    '{\n  "refused": {\n    "reason": "not checked yet: it waits for your answer to question 3, asked before gate B",\n'
    '    "door": "answer the question about this check that comes before gate B",\n    "by": "left_unchecked"\n  }\n}\n')


def _bytes(root: Path, case: str) -> str:
    return ME.request_path(root, case).read_text(encoding="utf-8")


def drive_walk_gaps(root: Path):
    """`walk_refuse_gaps` over one lane whose account is named by one key the stand has no pair for. (request bytes, plan refused, printed)"""
    import manual_capture as MC
    L.write_request(root, "TC-1", {"actors": [{"id": "u", "check": {"env": "USER_EMAIL"}}]})
    d = L.make_driver(root, lambda script, *a, **k: (0, ""))
    d.project, d.task = root, "QA-9"
    cfg = {"environments": [{"name": "local", "credentials_by_role": {"admin": ".env: AUTH_USERNAME / AUTH_PASSWORD"}}]}
    plan = {"blocks": [["TC-1"]], "refused": []}
    out = io.StringIO()
    with mock.patch.object(MC, "load_config", lambda r: (cfg, root)), contextlib.redirect_stdout(out):
        d.walk_refuse_gaps(plan)
    return _bytes(root, "TC-1"), plan["refused"], out.getvalue()


def drive_login(root: Path):
    """`stand_login_gate` with a pass in the person's words and a recorded `by hand` choice. (request bytes, plan refused, printed, blocks)"""
    L.write_request(root, "TC-1", {"evidence_policy": "ui"})
    d = L.make_driver(root)
    d.state = {"login_choice": {"token": "by hand", "words": "do it by hand"}}
    d.manual_policy = lambda case: "ui"
    d.stand_login_problem = lambda screens: ("missing", {})
    d.pipeline = lambda: {}
    plan = {"blocks": [["TC-1"]], "refused": []}
    out = io.StringIO()
    with mock.patch.object(story_run.waiver, "split_overridden", lambda blocks, pipeline, stage: ([], [{"decision": "do it by hand"}])), \
            contextlib.redirect_stdout(out):
        d.stand_login_gate(plan)
    return _bytes(root, "TC-1"), plan["refused"], out.getvalue(), plan["blocks"]


def drive_close(root: Path):
    """`manual_close` with one case held by a deferred question 3. (request bytes, the closing calls)"""
    L.write_request(root, "TC-1", {"evidence_policy": "ui"})
    d = L.make_driver(root)
    closed = []
    d.consumer_need_record = lambda stage, site: None
    d.manual_done = lambda: set()
    d.deferred_waiting = lambda cases: [("TC-1", 3)]
    d.close_by_code = lambda *a, **k: closed.append((a, k))
    with contextlib.redirect_stdout(io.StringIO()):
        d.manual_close(["TC-1"], [])
    return _bytes(root, "TC-1"), closed


def drive_walk_refusal(root: Path):
    """`walk_refusal` on the SECOND refusal of a case (closed `left_unchecked`). (request bytes, its row, printed)"""
    L.write_request(root, "TC-1", {"evidence_policy": "ui"})
    d = L.make_driver(root)
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        row = d.walk_refusal("TC-1", "the build said no", {"TC-1": {"refused": 1, "open": True, "reason": "first"}})
    return _bytes(root, "TC-1"), row, out.getvalue()


def drive_deferred(root: Path):
    """`deferred_decision` over a case whose request.json is our waiting record. (request bytes, printed)"""
    L.write_request(root, "TC-1", {"refused": {"reason": "not checked yet: it waits for your answer to question 3, asked before gate B",
                                               "door": "x", "by": "left_unchecked"}})
    d = L.make_driver(root)
    d.pass_block = lambda *a, **k: None
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        d.deferred_decision({"n": 3, "holds": ["TC-1"]}, "by hand", "do it by hand", {}, "S6", "work/words.txt")
    return _bytes(root, "TC-1"), out.getvalue()


def json_of(root, case):
    return json.loads(_bytes(root, case))


def test_walk_refuse_gaps_writes_the_same_bytes(tmp_path):
    body, refused, printed = drive_walk_gaps(tmp_path)
    assert body == EXPECT_WALK_GAPS, body
    assert refused == [("TC-1", "not walked: for this case's account the factory does not know the password: named by one key USER_EMAIL")]
    assert printed.startswith("S6: TC-1: not walked: "), printed


def test_stand_login_gate_writes_the_same_bytes(tmp_path):
    body, refused, printed, blocks = drive_login(tmp_path)
    assert body == EXPECT_LOGIN, body
    assert len(refused) == 1 and refused[0][0] == "TC-1" and blocks == [], (refused, blocks)
    assert printed.startswith("S6: TC-1: not checked by hand — not checked by an agent: "), printed


def test_manual_close_writes_the_same_bytes_and_keeps_its_own_list(tmp_path):
    body, closed = drive_close(tmp_path)
    assert body == EXPECT_CLOSE, body
    (args, _kw), = closed
    assert args[0] == "S6" and "1 not checked: TC-1" in args[1], args


def test_walk_refusal_writes_the_same_bytes(tmp_path):
    body, row, printed = drive_walk_refusal(tmp_path)
    assert body == EXPECT_REFUSAL, body
    assert row["state"] == "refused" and row["n"] == 2 and printed.startswith("S6: TC-1: not checked by hand: the record of its walk was refused twice"), (row, printed)


def test_deferred_decision_writes_the_same_bytes(tmp_path):
    body, printed = drive_deferred(tmp_path)
    assert body == EXPECT_DEFERRED, body
    assert printed.startswith("S6: TC-1: not checked by hand — not checked by an agent: you answered question 3"), printed


def test_refuse_case_says_whether_it_wrote(tmp_path):
    d = L.make_driver(tmp_path)
    assert d.refuse_case(None, "TC-1", "why", "door", "by") is True
    with mock.patch.object(story_run, "_write_json", mock.Mock(side_effect=OSError("disk"))):
        assert d.refuse_case(None, "TC-2", "why", "door", "by") is False


def test_a_dead_directory_is_swallowed_as_before(tmp_path):
    """The three callers wrote inside `try ... except OSError: pass`: the helper keeps it (the printed line names the case)."""
    d = L.make_driver(tmp_path)
    plan = {"refused": []}
    with mock.patch.object(story_run, "_write_json", mock.Mock(side_effect=OSError("disk"))):
        d.refuse_case(plan, "TC-1", "why", "door", "left_unchecked")
    assert plan["refused"] == [("TC-1", "why")]
    d.refuse_case(None, "TC-2", "why", "door", "left_unchecked")          # no plan (manual_close): only the request is written
    assert json_of(tmp_path, "TC-2") == {"refused": {"reason": "why", "door": "door", "by": "left_unchecked"}}


def test_an_empty_door_or_by_is_written_as_given(tmp_path):
    """The old callers checked nothing: an empty `door` / `by` is written as it comes (the helper adds no rule)."""
    d = L.make_driver(tmp_path)
    d.refuse_case({"refused": []}, "TC-1", "why", "", "")
    assert json_of(tmp_path, "TC-1") == {"refused": {"reason": "why", "door": "", "by": ""}}


def test_a_case_outside_the_plan_is_still_written(tmp_path):
    """No caller checked membership: `refuse_case` appends to the plan list and writes whatever case it is given."""
    d = L.make_driver(tmp_path)
    plan = {"blocks": [["TC-9"]], "refused": []}
    d.refuse_case(plan, "TC-1", "why", "door", "left_unchecked")
    assert plan["refused"] == [("TC-1", "why")] and json_of(tmp_path, "TC-1")["refused"]["reason"] == "why"


def test_no_new_copy_of_the_refusal_record_in_story_run():
    """The literal `{"refused": {` opens a record writer. Exactly ONE is left: the one inside `refuse_case`; every other writer is outside it
    (count 0). A new copy turns this red."""
    src = (HERE.parent / "story_run.py").read_text(encoding="utf-8")
    start = src.index("    def refuse_case(")
    end = src.index("\n    def ", start + 10)
    outside = src[:start] + src[end:]
    assert len(re.findall(r'\{"refused": \{', outside)) == 0, "a writer of the refusal record outside Driver.refuse_case: use it"
    assert len(re.findall(r'\{"refused": \{', src[start:end])) == 1


def test_the_dispatch_row_id_has_one_reader():
    assert controller._dispatch_ident({"id": "S6-qa-runner-1"}, "k") == "S6-qa-runner-1"
    assert controller._dispatch_ident({}, "k") == "k" and controller._dispatch_ident({"id": ""}, "k") == "k"
    assert controller._dispatch_ident({"id": None}, "k") == "k" and controller._dispatch_ident("not a row", "k") == "k"
    src = (HERE.parent / "controller.py").read_text(encoding="utf-8")
    reads = re.findall(r'\.get\("id"\) or key', src)
    assert len(reads) == 1, f"{len(reads)} inline reads of a row id by `or key`: use _dispatch_ident (the helper holds the one)"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q", "-p", "no:cacheprovider"]))
