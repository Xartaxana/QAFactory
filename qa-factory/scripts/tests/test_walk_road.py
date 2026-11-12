#!/usr/bin/env python3
"""t-2016: the ROAD after the walker - verdict -> record -> form - walked end to end with no hand-written capture (fake browser, no network).

The critic of walker Slice 1 (t-2013) found that every part held and the road between them did not: a `pass` the server called ok was refused when its
record was built (F1), a verdict the build would refuse was accepted while the session lived (F2), the form values left 29 fields to a resume (F3), a
halt ended the lane's unwalked items for good (F4), a two-account lane left the walker (F5), the teardown check read a key nothing writes (F6).
Every test here goes through the REAL `Walk` (fake browser), the REAL `build_record` / `record_from_walk`, and - for the form - the REAL
`handoff_check.py --fix` on a form made by `handoff_init.fill_head`.
Run: `python -B test_walk_road.py` (exit code = failures) or `python -m pytest -p no:cacheprovider test_walk_road.py -q`.
"""
import contextlib
import json
import re
import subprocess
import sys
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE / "fixtures" / "manual-evidence"))
import pytest  # noqa: E402
import scaffold as S  # noqa: E402
import test_manual_capture as TMC  # noqa: E402
import test_manual_evidence as TME  # noqa: E402
import test_walk_lanes as L  # noqa: E402
import test_walk_record as R  # noqa: E402
import test_walk_session as W  # noqa: E402

import handoff  # noqa: E402
import handoff_init  # noqa: E402
import manual_evidence as ME  # noqa: E402
import story_step  # noqa: E402
import walk_session as WS  # noqa: E402

CASE, WALK, GO = W.CASE, W.WALK, W.GO
STEPS = GO + 'click "#a"\n'                 # a charter walk: no capture of its own; the server takes `pre_action`, `final` takes `completion`


@contextlib.contextmanager
def road(items=(CASE,)):
    """A walk on the fake browser over a PREPARED case (a real `request.json`), the controller faked as `scaffold` does."""
    rig = W.Rig(items=items).start()
    try:
        rig.t.state()
        TME.seed_provenance(rig.t.task, "e2e-ui", S.probe()["expected_source_revision"])
        with rig.t.patched():
            ME.prepare_to_file(rig.t.task, CASE, TMC.OBLIGATIONS[CASE])
        yield rig
    finally:
        rig.done()


def numbers(rig, item=CASE) -> list:
    return sorted(int(n) for n in json.loads(ME.request_path(rig.t.task, item).read_text(encoding="utf-8")).get("thens") or {}) or [1]


def thens(rig, result="pass", quote="button: Pay", **extra) -> list:
    return [{"n": n, "result": result, "quote": quote if result in ("pass", "fail") else "", **extra} for n in numbers(rig)]


def walked(rig, steps=STEPS, final=True, item=CASE):
    code, answer = rig.step(steps, item=item, final=final)
    assert code == 0, answer
    return answer


def build(rig, item=CASE) -> dict:
    """Close the session and build the case record from the item's result record, as the driver's `walk_after` does."""
    assert rig.call("close")[0] == 0
    found = json.loads((rig.t.task / "work" / "walks" / WALK / f"{item}.json").read_text(encoding="utf-8"))
    with rig.t.patched():
        return ME.record_from_walk(rig.t.task, item, found)


def record_of(rig, built, item=CASE) -> dict:
    assert built.get("written") is True, built
    return json.loads((rig.t.attempt_dir(item) / "record.json").read_text(encoding="utf-8"))


# --- F1: the charter road, no hand-written capture ------------------------------------------------------------------------------------

def test_pass_road_step_final_verdict_close_record():
    with road() as rig:
        walked(rig)
        code, answer = rig.call("verdict", item=CASE, verdict={"thens": thens(rig), "observations": [], "teardown": "none"})
        assert code == 0, answer
        built = build(rig)
        record = record_of(rig, built)
        assert record["result"] == "pass" and ME.validate_record(record, rig.t.task, record["evidence_policy"]) == [], record
        phases = {(r["phase"], tuple(r["proves"])) for r in record["evidence_refs"]}
        assert ("pre_action", ("start",)) in phases and ("post_action", ("completion",)) in phases, phases


def test_fail_road_same():
    with road() as rig:
        walked(rig, final=False)                                    # a fail needs no final, only a pre_action and a post_action picture
        rig.call("final", item=CASE)
        code, answer = rig.call("verdict", item=CASE, verdict={"thens": thens(rig, "fail"), "observations": []})
        assert code == 0, answer
        record = record_of(rig, build(rig))
        assert record["result"] == "fail" and ME.validate_record(record, rig.t.task, record["evidence_policy"]) == [], record


# --- F2: what the build refuses is refused while the session lives ----------------------------------------------------------------------

def test_inconclusive_then_limitation_reaches_record():
    with road() as rig:
        walked(rig)
        verdict = {"thens": [{"n": n, "result": "inconclusive", "limitation": "the cart page never showed the coupon field"} for n in numbers(rig)]}
        code, answer = rig.call("verdict", item=CASE, verdict=verdict)
        assert code == 0, answer                                    # a Then-level limitation is enough: the example D of the recipe
        record = record_of(rig, build(rig))
        assert record["result"] == "inconclusive" and any("the cart page never showed the coupon field" in x for x in record["limitations"]), record["limitations"]


def observed(rig, **extra) -> dict:
    capture = next(c["path"] for c in WS.attempt_rows(rig.t.task, CASE, rig.walk.item_rec[CASE]["attempt"].name)[1] if c["path"].endswith(".txt"))
    return {"step": 3, "expected": "the button reads Pay", "seen": "the button reads Pay", "capture": capture, **extra}


def test_observation_as_the_charter_writes_it_is_kept():
    with road() as rig:
        walked(rig)
        code, answer = rig.call("verdict", item=CASE, verdict={"thens": thens(rig), "observations": [observed(rig, quote="button: Pay")]})
        assert code == 0, answer
        record = record_of(rig, build(rig))
        assert len(record["observations"]) == 1 and record["observations"][0]["quote"] == "button: Pay", record["observations"]
        assert ME.validate_record(record, rig.t.task, record["evidence_policy"]) == []


def test_observation_without_quote_is_refused_and_code_writes_no_citation():
    """t-2022 N3: the role's citation is the role's. No quote: refused at the verdict with the door; a hand-written record with none keeps none."""
    with road() as rig:
        walked(rig)
        code, answer = rig.call("verdict", item=CASE, verdict={"thens": thens(rig), "observations": [observed(rig)]})
        assert code == 2 and "quote" in answer["text"] and "Door:" in answer["text"], (code, answer)
        assert not (rig.t.task / "work" / "walks" / WALK / f"{CASE}.json").is_file()
        assert "quote" not in ME._walk_observations({"observations": [observed(rig)]})[0]          # nothing fills it in
        WS.write_verdict(rig.t.task, WALK, CASE, {"thens": thens(rig), "observations": [observed(rig)]}, attempt=rig.walk.item_rec[CASE]["attempt"].name)
        assert "refused" in build(rig)                                                         # the existing re-queue road, never a made-up quote


def test_verdict_refused_while_session_lives_on_what_build_refuses():
    shapes = {
        "inconclusive with no limitation": lambda rig: {"thens": [{"n": n, "result": "inconclusive"} for n in numbers(rig)]},
        "observation with nothing to quote": lambda rig: {"thens": thens(rig), "observations": [{"step": 1, "expected": "e", "seen": "s", "capture": "nowhere.png"}]},
        "pass of an item with no action (no pre_action)": lambda rig: {"thens": thens(rig)},
    }
    for name, make in shapes.items():
        with road() as rig:
            walked(rig, steps=GO + "look\n") if name.startswith("pass") else walked(rig)
            verdict = make(rig)
            code, answer = rig.call("verdict", item=CASE, verdict=verdict)
            assert code == 2 and "would be refused" in answer["text"] and "Door:" in answer["text"], (name, code, answer)
            assert not (rig.t.task / "work" / "walks" / WALK / f"{CASE}.json").is_file(), name       # nothing stored: the role can still act
            # the SAME verdict stored by force is refused by the build: the session check asked the build's own rule
            WS.write_verdict(rig.t.task, WALK, CASE, verdict, attempt=rig.walk.item_rec[CASE]["attempt"].name)
            assert "refused" in build(rig), name


def test_verdict_of_an_item_with_no_capture_takes_a_look_and_builds():
    """t-2022 N1: "Case file: not found ... say so in its verdict" and an item the walker declines to touch hold no capture; the build refuses
    such an attempt, so the verdict took the case with it. The server takes one `look` (P26: code writes the evidence); the case is recorded."""
    for steps in (None, GO):
        with road() as rig:
            if steps:
                walked(rig, steps=steps, final=False)
            verdict = {"thens": [{"n": n, "result": "inconclusive", "limitation": "the case file was not found, so no step was walked"} for n in numbers(rig)]}
            code, answer = rig.call("verdict", item=CASE, verdict=verdict)
            assert code == 0, (steps, answer)
            record = record_of(rig, build(rig))
            assert record["result"] == "inconclusive" and record["evidence_refs"], record
            assert ME.validate_record(record, rig.t.task, record["evidence_policy"]) == []
    with road() as rig:                                                    # the sign-in window open: no look can be taken: refused, with the door
        rig.walk.accounts["user"].window = True
        code, answer = rig.call("verdict", item=CASE, verdict={"thens": [{"n": n, "result": "inconclusive", "limitation": "x"} for n in numbers(rig)]})
        assert code == 2 and "holds no captures" in answer["text"] and "Door:" in answer["text"], (code, answer)


def test_surprise_citation_is_asked_at_the_verdict():
    """t-2022 N2: an observation that cites a surprise line that does not exist was accepted and refused by the build."""
    with road() as rig:
        walked(rig)
        attempt = rig.walk.item_rec[CASE]["attempt"]
        (attempt.dir / "surprises.jsonl").write_text(json.dumps({"line": "surprise", "id": "a1-ui-S3", "step": 2, "word": "click", "kind": "status",
                                                                 "fact": "status 404 on /x"}) + "\n", encoding="utf-8")
        code, answer = rig.call("verdict", item=CASE, verdict={"thens": thens(rig), "observations": [observed(rig, quote="button: Pay", surprise="status 404 on /x")]})
        assert code == 2 and "no surprise line" in answer["text"] and "a1-ui-S3" in answer["text"], (code, answer)
        code, answer = rig.call("verdict", item=CASE, verdict={"thens": thens(rig), "observations": [observed(rig, quote="button: Pay", surprise="a1-ui-S3")]})
        assert code == 0, answer
        record = record_of(rig, build(rig))
        assert record["observations"][0]["surprise"] == "a1-ui-S3"


def test_before_picture_taken_after_the_action_is_refused_and_not_invited():
    """t-2022 N4: a `pre_action` after the page was acted on is no "before". The server inserts none once the attempt holds an action beyond
    the sign-in; the verdict refuses one that stands after the first action or after the `post_action`; the door never says "take your own"."""
    shapes = {
        "after two actions": (GO + 'click "#a"\nclick "#b"\n', 'capture pre_action mine\nclick "#c"\n'),
        "after the post_action": (GO + 'click "#a"\n', "look\ncapture post_action completion\ncapture pre_action late\n"),
    }
    for name, (first, second) in shapes.items():
        with road() as rig:
            rig.walk.accounts["user"].window = True                       # a call that starts inside the sign-in window gets no server picture
            assert rig.step(first)[0] == 0
            rig.walk.accounts["user"].window = False
            added = rig.step(second)[1].get("added_step")
            assert not added, (name, added)                                # nothing is inserted over an attempt that was acted on
            code, answer = rig.call("verdict", item=CASE, verdict={"thens": thens(rig, "fail"), "observations": []})
            assert code == 2 and "no picture of the page before" in answer["text"], (name, code, answer)
            assert "take your own" not in answer["text"] and "capture pre_action <label>" not in answer["text"], answer["text"]
    rows = lambda *words: [{"step": w, "outcome": "ok"} for w in words]          # noqa: E731
    signin = rows("goto /", "fill-account #u user user", "fill-account #p user secret")
    assert WS.before_order_problems(signin + rows('click "#go"', "capture pre_action start", 'click "#a"')) == []          # the submit is the sign-in's
    assert WS.before_order_problems(signin + rows('click "#a"', 'click "#b"', "capture pre_action start", 'click "#c"')) != []
    assert WS.before_order_problems(rows("goto /", "capture pre_action start", 'click "#a"', "capture post_action completion")) == []
    late = WS.before_order_problems(signin + rows('click "#go"', "look", "capture post_action completion", "capture pre_action late"))
    assert len(late) == 1 and "after the `post_action`" in late[0], late                       # critic's second shape, with the submit as the sign-in's
    assert WS.before_order_problems(rows("goto /", "look", "capture post_action completion", "capture pre_action late", 'click "#a"')) == []


# --- F4: a halt, a resume, a cut ------------------------------------------------------------------------------------------------------

def test_halt_after_item_1_resume_walks_items_2_3():
    items = (CASE, W.CASE2, "TP1-15045_TC_015")
    with road(items) as rig:
        walked(rig)
        assert rig.call("verdict", item=CASE, verdict={"thens": thens(rig), "observations": []})[0] == 0
        built = []
        d = L.make_driver(rig.t.task)
        d.py = lambda script, *args, **kw: (rig.call("close")[0], "") if args and args[0] == "close" else (0, "")
        calls = mock.patch.object(ME, "record_from_walk", lambda t, case, rec: built.append((case, bool(rec.get("missing_verdict")))) or {"written": True, "case": case, "result": "pass"})
        with calls:
            d.walk_after(list(items), WALK, {})                          # the halt: the walker is over after item 1
            assert built == [(CASE, False), (items[1], True), (items[2], True)], built
            marked = json.loads((rig.t.task / "work" / "walks" / WALK / f"{items[1]}.json").read_text(encoding="utf-8"))
            assert marked["missing_verdict"] is True
            # the walker is resumed: the server comes back; the marked records are no verdicts, so items 2 and 3 are walked
            again = WS.Walk(rig.t.task, WALK, list(items), ["user"], reopened=1)
            again.start()
            try:
                code, answer = again.dispatch({"op": "step", "token": again.token, "item": items[1], "steps": W.GO + "look\n"})
                assert code == 0, answer
                assert again.dispatch({"op": "step", "token": again.token, "item": CASE, "steps": W.GO})[0] == 2        # a REAL verdict still stands
                real = {"thens": [{"n": 1, "result": "inconclusive", "limitation": "walked on"}], "observations": []}
                assert again.dispatch({"op": "verdict", "token": again.token, "item": items[1], "verdict": real})[0] in (0, 2)
                WS.write_verdict(rig.t.task, WALK, items[1], real, attempt=again.item_rec[items[1]]["attempt"].name)
            finally:
                again._shutdown("dead", "test over", probe=False)
            built.clear()
            d.walk_after(list(items), WALK, {})                          # after the resume: item 2 is built again, item 3 (still missing) is not counted twice
            assert built == [(items[1], False)], built


def test_run_role_any_caller_reopens_and_runs_after(tmp_path):
    record = tmp_path / "state/walks" / f"{L.D1}.json"
    record.parent.mkdir(parents=True)
    record.write_text(json.dumps({"state": "dead", "items": ["TC-1"], "actors": ["admin"]}), encoding="utf-8")
    d = L.role_driver(tmp_path)
    d.walk_after = lambda lane, dispatch, result: d.events.append(("after", tuple(lane)))
    seen = []
    d.py = lambda script, *args, **kw: seen.append((script, args[0] if args else "")) or (0, json.dumps({"status": "ready", "signed_in": True, "landed_on": "/"}))
    with mock.patch.object(story_step, "_brief", lambda *a, **k: ("", "")), mock.patch.object(story_step, "_prompt", lambda *a, **k: "prompt"), \
            mock.patch.object(story_step, "_declared_halt", lambda *a, **k: False):
        d.run_role("S6", "qa-runner", scope=["TC-1"], rework={"id": L.D1, "scope": ["TC-1"], "line": "Not a rework: continue this dispatch"})   # no `after`
    assert ("walk_session.py", "open") in seen and ("after", ("TC-1",)) in d.events, (seen, d.events)
    assert d.events.index("role") < d.events.index(("after", ("TC-1",))) < d.events.index("handoff")
    plain = L.role_driver(tmp_path / "other")
    plain.walk_after = lambda *a: plain.events.append("after")
    with mock.patch.object(story_step, "_brief", lambda *a, **k: ("", "")), mock.patch.object(story_step, "_prompt", lambda *a, **k: "prompt"), \
            mock.patch.object(story_step, "_declared_halt", lambda *a, **k: False):
        plain.run_role("S6", "qa-runner", scope=["TC-1"], rework={"id": L.D1, "scope": ["TC-1"], "reason": "x"})
    assert "after" not in plain.events                                  # a dispatch with no walk record is no walk


def walk_record_file(root, dispatch=L.D1, state="dead"):
    record = root / "state/walks" / f"{dispatch}.json"
    record.parent.mkdir(parents=True, exist_ok=True)
    record.write_text(json.dumps({"state": state, "items": ["TC-1"], "actors": ["admin"]}), encoding="utf-8")


def test_saved_result_reopens_no_session_but_runs_after(tmp_path):
    """t-2022 N7: a saved result means no role runs; opening a browser, a sign-in and the lease for no role is waste. `after` still runs."""
    walk_record_file(tmp_path)
    saved = tmp_path / "state/driver-runs" / f"{L.D1}.json"
    saved.parent.mkdir(parents=True)
    saved.write_text(json.dumps({"result": "earlier", "session_id": "s0", "is_error": False}), encoding="utf-8")
    d = L.role_driver(tmp_path)
    d.walk_after = lambda lane, dispatch, result: d.events.append(("after", tuple(lane)))
    with mock.patch.object(story_step, "_brief", lambda *a, **k: ("", "")), mock.patch.object(story_step, "_prompt", lambda *a, **k: "prompt"), \
            mock.patch.object(story_step, "_declared_halt", lambda *a, **k: False):
        d.run_role("S6", "qa-runner", scope=["TC-1"], rework={"id": L.D1, "scope": ["TC-1"], "line": "Not a rework: continue this dispatch"})
    assert ("py", "walk_session.py") not in d.events and "role" not in d.events and ("after", ("TC-1",)) in d.events, d.events


def test_finish_saved_result_runs_after_before_handoff(tmp_path):
    """t-2022 N6: a driver killed while `walk_after` ran comes back through `_finish_saved_result`, which had no hook (unbuilt items, no form values)."""
    walk_record_file(tmp_path)
    d = L.role_driver(tmp_path)
    d.walk_after = lambda lane, dispatch, result: d.events.append(("after", tuple(lane)))
    d.completion_for = lambda *a: None
    with mock.patch.object(story_step, "_declared_halt", lambda *a, **k: False):
        d._finish_saved_result({"result": "x", "session_id": "s"}, "qa-runner", "S6", L.D1, {"scope": ["TC-1"]})
        assert d.events.index(("after", ("TC-1",))) < d.events.index("handoff") < d.events.index("finish"), d.events
        plain = L.role_driver(tmp_path / "other")
        plain.walk_after = lambda *a: plain.events.append("after")
        plain.completion_for = lambda *a: None
        plain._finish_saved_result({"result": "x", "session_id": "s"}, "qa-runner", "S6", L.D1, {"scope": ["TC-1"]})
        assert "after" not in plain.events                              # a dispatch with no walk record is no walk


def test_completion_waits_for_a_requeued_case_of_its_own_lane(tmp_path):
    """t-2022 N5: `completion_for` (the road of a cut, a never-launched launch, a person's resume) asked `manual_plan(skip=<its own lane>)`, which
    cannot see a case of the lane that was refused once; the stage closed over it. The live road's guard `walk_pending` stands here too."""
    d = L.make_driver(tmp_path)
    d.stage_scope = lambda *a, **k: {"scope": ["TC-1", "TC-2"]}
    d.manual_plan = lambda cases, skip=(): {"blocks": [[c] for c in cases if c not in skip], "refused": []}
    d.consumer_awaits = lambda stage, closes: closes
    record = {"id": L.D1, "execution_kind": "manual", "scope": ["TC-1", "TC-2"]}
    assert d.completion_for("S6", "qa-runner", record) is True                                  # nothing re-queued: the lane is the last block
    d.state = {"walk_retry": {"TC-2": {"open": True, "refused": 1}}}
    assert d.walk_pending(["TC-1", "TC-2"]) is True
    assert d.completion_for("S6", "qa-runner", record) is False                                 # a case waits to be walked once more
    d.state = {"walk_retry": {"TC-2": {"open": False, "refused": 2}}}
    assert d.completion_for("S6", "qa-runner", record) is False                                 # closed `left_unchecked`: still never closes the stage


# --- F5: two accounts ---------------------------------------------------------------------------------------------------------------

def test_two_accounts_lane_opens_with_actor2(tmp_path):
    import manual_capture as MC
    cfg = {"environments": [{"name": "local", "roles": {"admin": "keys A_USER A_PW", "reader": "keys R_USER R_PW"}}]}
    for case in ("TC-1", "TC-2"):
        L.write_request(tmp_path, case, {"actors": [{"id": "admin", "check": {"stand_account": "admin"}}, {"id": "reader", "check": {"stand_account": "reader"}}]})
    opened = []
    d = L.make_driver(tmp_path, lambda script, *a, **k: opened.append((script, a)) or (0, "ready"))
    with mock.patch.object(MC, "load_config", lambda root: (cfg, tmp_path)), mock.patch.object(MC, "_roles_of", lambda stand: {"admin": {}, "reader": {}}), \
            mock.patch("gate_preflight.account_role", lambda roles, value: value if value in roles else None), \
            mock.patch("gate_preflight.account_keys", lambda role: ["u", "p"]):
        got = d.walk_before(["TC-1", "TC-2"], L.D1)
    args = next(a for script, a in opened if script == "walk_session.py")
    assert got["walking"] is True and args[args.index("--actor") + 1] == "admin" and args[args.index("--actor2") + 1] == "reader", opened
    assert not d.state.get("walk_old_road"), d.state
    # three accounts: today's road, the reason printed and the items marked out of the medians
    L.write_request(tmp_path, "TC-3", {"actors": [{"id": x, "check": {"stand_account": x}} for x in ("admin", "reader", "guest2")]})
    with mock.patch.object(MC, "load_config", lambda root: (cfg, tmp_path)):
        got = d.walk_before(["TC-3"], "S6-qa-runner-2")
    assert got["walking"] is False and "at most 2" in d.state["walk_old_road"]["TC-3"], d.state


# --- TR1-4: an account named by one key -------------------------------------------------------------------------------------------------

def env_driver(tmp_path, roles, opened):
    d = L.make_driver(tmp_path, lambda script, *a, **k: opened.append((script, a)) or (0, "ready"))
    d.project, d.task = tmp_path, "QA-9"
    cfg = {"environments": [{"name": "local", "credentials_by_role": roles}]} if roles is not None else {}
    return d, cfg


def test_env_one_key_with_a_pair_in_the_stand_opens_a_session(tmp_path):
    import manual_capture as MC
    for case in ("TC-1", "TC-2"):
        L.write_request(tmp_path, case, {"actors": [{"id": "u", "check": {"env": "USER_EMAIL"}}]})
    opened = []
    d, cfg = env_driver(tmp_path, {"user": ".env: USER_EMAIL / USER_PASSWORD - a user", "admin": ".env: AUTH_USERNAME / AUTH_PASSWORD"}, opened)
    with mock.patch.object(MC, "load_config", lambda root: (cfg, tmp_path)):
        assert d.walk_account_gap(["TC-1", "TC-2"]) == ""
        got = d.walk_before(["TC-1", "TC-2"], L.D1)
    args = next(a for script, a in opened if script == "walk_session.py")
    assert got["walking"] is True and args[args.index("--actor") + 1] == "user", opened
    assert not d.state.get("walk_old_road"), d.state


def test_env_one_key_without_a_pair_is_not_walked_and_the_next_lane_walks(tmp_path):
    import manual_capture as MC
    for case in ("TC-1", "TC-2"):
        L.write_request(tmp_path, case, {"actors": [{"id": "u", "check": {"env": "USER_EMAIL"}}]})
    L.write_request(tmp_path, "TC-3", L.account("admin"))
    opened = []
    d, cfg = env_driver(tmp_path, {"admin": ".env: AUTH_USERNAME / AUTH_PASSWORD"}, opened)
    plan = {"blocks": [["TC-1", "TC-2"], ["TC-3"]], "refused": []}
    with mock.patch.object(MC, "load_config", lambda root: (cfg, tmp_path)):
        d.walk_refuse_gaps(plan)
        assert plan["blocks"] == [["TC-3"]], plan                                   # no Person raised: the run goes on
        reasons = dict(plan["refused"])
        assert set(reasons) == {"TC-1", "TC-2"}, plan
        want = "not walked: for this case's account the factory does not know the password: named by one key USER_EMAIL"
        assert all(r == want for r in reasons.values()), reasons
        asked = json.loads(ME.request_path(tmp_path, "TC-1").read_text(encoding="utf-8"))["refused"]
        assert asked["reason"] == want and asked["by"] == "left_unchecked", asked   # 'not walked', never 'record refused'
        findings = [a for script, a in opened if script == "project_decisions.py"]
        assert len(findings) == 1 and "add-finding" in findings[0], opened          # one finding for the lane
        assert not d.state.get("walk_old_road"), d.state                            # not the old road
        got = d.walk_before(plan["blocks"][0], "S6-qa-runner-2")
    assert got["walking"] is True and any(s == "walk_session.py" for s, _a in opened), opened


class _Registry:
    """A controller double for the ENTRY: `prepare` / `apply("dispatch")` register a row in `dispatches`, as the real one does."""
    dispatches: dict = {}

    def __init__(self, *_a, **_k):
        pass

    def state(self):
        return {"dispatches": dict(_Registry.dispatches)}

    def prepare(self, options):
        return {"dispatch_request": dict(options)}

    def apply(self, operation, request):
        _Registry.dispatches[request["id"]] = dict(request)


class _Stop(Exception):
    """Raised by the double of `walk_before`: the entry got as far as the dispatch and the walk, which is all the control needs."""


def enter_manual_block(tmp_path, gap: bool):
    """`run_manual_block` itself over one prepared case - the entry, not its source. With `gap` the case's account is named by one key the
    stand has no pair for. Returns (printed, dispatch rows registered, the driver, what `manual_close` was given, whether the walk began)."""
    import contextlib
    import io
    import manual_capture as MC
    _Registry.dispatches = {}
    L.write_request(tmp_path, "TC-1", {"actors": [{"id": "u", "check": {"env": "USER_EMAIL" if gap else "ADMIN_EMAIL"}}]})
    roles = {"admin": ".env: ADMIN_EMAIL / ADMIN_PASSWORD"}
    d, cfg = env_driver(tmp_path, roles, [])
    d.config = cfg      # the real Driver sets it in __init__ (hooklib.load_config); run_manual_block reads `manual.walkers` from it (TR3-9 C1)
    d.deferred_waiting, d.deferred_items, d.manual_gate_note = (lambda cases: []), (lambda: []), (lambda: None)
    d.manual_plan = lambda cases, skip=(): {"blocks": [list(cases)], "refused": [], "unprepared": []}
    d.stand_login_gate = lambda plan: None
    d.MANUAL_BLOCK_MAX = 3
    closed, walked = [], []
    d.manual_close = lambda cases, refused: closed.append((list(cases), list(refused)))

    def walk_before(block, dispatch):
        walked.append((block, dispatch))
        raise _Stop()
    d.walk_before = walk_before
    out = io.StringIO()
    with mock.patch.object(MC, "load_config", lambda root: (cfg, tmp_path)), mock.patch("controller.Controller", _Registry),             contextlib.redirect_stdout(out):
        try:
            d.run_manual_block(["TC-1"])
        except _Stop:
            pass
    return out.getvalue(), dict(_Registry.dispatches), d, closed, walked


def test_the_gap_check_refuses_before_any_dispatch_is_registered(tmp_path):
    """TR4-8, POSITION INVARIANT of `walk_refuse_gaps`: a lane that cannot walk costs no role - the refusal (with its door) is on record and
    NO dispatch row exists after it. Driven through the entry `run_manual_block`; the CONTROL (no gap) shows the same rig does register a
    dispatch, so an empty registry above is the order, not a rig that never registers."""
    printed, rows, d, closed, walked = enter_manual_block(tmp_path, gap=True)
    asked = json.loads(ME.request_path(tmp_path, "TC-1").read_text(encoding="utf-8"))["refused"]
    assert asked["by"] == "left_unchecked" and asked["door"] and asked["reason"].startswith("not walked: "), asked   # the refusal, with its door
    assert rows == {} and walked == [], (rows, walked)                                                              # no dispatch, no walk
    assert closed == [(["TC-1"], [("TC-1", asked["reason"])])], closed                                              # the manual half closes over it
    assert "S6: TC-1: not walked: " in printed, printed


def test_the_control_without_a_gap_registers_the_dispatch(tmp_path):
    printed, rows, d, closed, walked = enter_manual_block(tmp_path, gap=False)
    assert list(rows) == ["S6-qa-runner-1"] and walked == [(["TC-1"], "S6-qa-runner-1")] and closed == [], (rows, walked, closed)


def test_env_one_key_two_roles_with_the_key_is_no_pair_and_names_both(tmp_path):
    import manual_capture as MC
    L.write_request(tmp_path, "TC-1", {"actors": [{"id": "u", "check": {"env": "USER_EMAIL"}}]})
    opened = []
    d, cfg = env_driver(tmp_path, {"first": "USER_EMAIL / A_PASSWORD", "second": "USER_EMAIL / B_PASSWORD"}, opened)
    with mock.patch.object(MC, "load_config", lambda root: (cfg, tmp_path)):
        why = d.walk_account_gap(["TC-1"])
    assert "`first`" in why and "`second`" in why and "does not guess" in why, why
    with mock.patch.object(MC, "load_config", lambda root: (cfg, tmp_path)):
        actors, why2 = d.walk_actors("TC-1", "env:USER_EMAIL")
    assert actors == [] and "does not guess" in why2, (actors, why2)


def test_env_one_key_with_no_stand_records_is_no_pair(tmp_path):
    import manual_capture as MC
    L.write_request(tmp_path, "TC-1", {"actors": [{"id": "u", "check": {"env": "USER_EMAIL"}}]})
    d, _cfg = env_driver(tmp_path, None, [])
    with mock.patch.object(MC, "load_config", mock.Mock(side_effect=ValueError("no qa-factory/config.json"))):
        assert "named by one key USER_EMAIL" in d.walk_account_gap(["TC-1"])
    # B5: one road for every shape: with no stand records a role is not listed, which is a reason too (never the old road)
    L.write_request(tmp_path, "TC-2", L.account("admin"))
    with mock.patch.object(MC, "load_config", mock.Mock(side_effect=ValueError("no qa-factory/config.json"))):
        assert "not one a machine can sign in as" in d.walk_account_gap(["TC-2"])


ROLES = {"user": ".env: USER_EMAIL / USER_PASSWORD - a user", "admin": ".env: AUTH_USERNAME / AUTH_PASSWORD", "plain": "a note with no keys"}


def shaped(tmp_path, case, actors, raw=None):
    """A request naming `actors` (id -> check dict); `raw` writes the file as text instead (a request that cannot be read)."""
    if raw is not None:
        path = ME.request_path(tmp_path, case)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(raw, encoding="utf-8")
    else:
        L.write_request(tmp_path, case, {"actors": [{"id": a, "check": c} for a, c in actors]})


def test_every_account_shape_that_cannot_open_is_refused_with_its_reason_never_the_old_road(tmp_path):
    """B5: `walk_account_gap` asks `walk_actors`, the reader the session opens by; each shape is not walked, names its reason,
    leaves no `walk_old_road` mark and the next lane opens."""
    import manual_capture as MC
    shapes = {
        "TC-1": ([("a", {"env": "GHOST_USER"}), ("b", {"stand_account": "admin"})], "named by one key GHOST_USER"),
        "TC-2": ([("a", {"stand_account": "ghost"})], "not one a machine can sign in as"),
        "TC-3": ([("a", {"stand_account": "plain"})], "not one a machine can sign in as"),
        "TC-5": ([(x, {"stand_account": x}) for x in ("admin", "user", "plain")], "at most 2"),
        "TC-6": ([("a", {"stand_account": "admin"}), ("b", {"stand_account": "ghost"})], "not one a machine can sign in as"),
    }
    for case, (actors, _why) in shapes.items():
        shaped(tmp_path, case, actors)
    shaped(tmp_path, "TC-7", None, raw="{this is not json")
    L.write_request(tmp_path, "TC-8", L.account("admin"))
    opened = []
    d, cfg = env_driver(tmp_path, ROLES, opened)
    plan = {"blocks": [[c] for c in (*shapes, "TC-7", "TC-8")], "refused": []}
    with mock.patch.object(MC, "load_config", lambda root: (cfg, tmp_path)):
        d.walk_refuse_gaps(plan)
        reasons = dict(plan["refused"])
        for case, (_actors, why) in shapes.items():
            assert why in reasons.get(case, ""), (case, reasons)
        assert "could not be read from its request" in reasons["TC-7"], reasons
        shaped(tmp_path, "TC-4", [("a", {"none": "no machine can check it"})])        # `lane_key` drops a `none` check: the key is "", a guest
        assert d.walk_account_gap(["TC-4"]) == ""
        assert plan["blocks"] == [["TC-8"]] and "TC-8" not in reasons, plan
        assert not d.state.get("walk_old_road"), d.state
        got = d.walk_before(plan["blocks"][0], "S6-qa-runner-2")
    assert got["walking"] is True and not d.state.get("walk_old_road"), (got, d.state)
    assert not any("--as" in str(v) for v in reasons.values()), reasons         # P9: no flag in the person's text


def test_a_many_account_key_with_a_login_key_opens_with_both_actors(tmp_path):
    import manual_capture as MC
    shaped(tmp_path, "TC-1", [("a", {"env": "USER_EMAIL"}), ("b", {"stand_account": "admin"})])
    shaped(tmp_path, "TC-2", [("a", {"env": "USER_EMAIL"}), ("b", {"stand_account": "user"})])
    opened = []
    d, cfg = env_driver(tmp_path, ROLES, opened)
    with mock.patch.object(MC, "load_config", lambda root: (cfg, tmp_path)):
        assert d.walk_account_gap(["TC-1"]) == ""
        got = d.walk_before(["TC-1"], L.D1)
        same = d.walk_actors("TC-2", MC.lane_key(tmp_path, "TC-2"))        # two parts that resolve to one role are one account
    args = next(a for script, a in opened if script == "walk_session.py")
    assert got["walking"] is True and args[args.index("--actor") + 1] == "user" and args[args.index("--actor2") + 1] == "admin", opened
    assert same == (["user"], ""), same


def test_only_a_failed_open_takes_the_old_road_and_marks_the_items(tmp_path):
    import manual_capture as MC
    L.write_request(tmp_path, "TC-1", L.account("admin"))
    opened = []
    d, cfg = env_driver(tmp_path, ROLES, [])
    d.py = lambda script, *a, **k: opened.append(script) or ((1, "the browser would not start") if script == "walk_session.py" else (0, ""))
    with mock.patch.object(MC, "load_config", lambda root: (cfg, tmp_path)):
        assert d.walk_account_gap(["TC-1"]) == ""
        got = d.walk_before(["TC-1"], L.D1)
    assert got["walking"] is False and "the browser would not start" in d.state["walk_old_road"]["TC-1"], (got, d.state)


def test_walk_timing_leaves_the_old_road_out_of_the_figures(tmp_path):
    import walk_timing
    task = tmp_path / "qa-factory" / "artifacts" / "QA-9"
    (task / "state").mkdir(parents=True)
    (task / "state" / "driver-state.json").write_text(json.dumps({"walk_old_road": {"TC-2": "no walk session"}}), encoding="utf-8")
    timing = task / "work" / "walks" / L.D1 / "timing.jsonl"
    timing.parent.mkdir(parents=True)
    timing.write_text("".join(json.dumps(r) + "\n" for r in (
        {"item": "TC-1", "index": 0, "place": "case", "started_at": "2026-11-06T10:00:00", "ended_at": "2026-11-06T10:01:00"},
        {"item": "TC-2", "index": 1, "place": "case", "started_at": "2026-11-06T10:01:00", "ended_at": "2026-11-06T10:02:00"})), encoding="utf-8")
    walks = walk_timing.timed_walks(task, [])
    assert [r["item"] for r in walks[L.D1]["items"]] == ["TC-1"] and walks[L.D1]["old_road"] == ["TC-2"], walks
    data = walk_timing.report(task)
    assert data["places"]["case"]["items"] == 1 and data["old_road"] == ["TC-2"], data
    assert "TC-2" in walk_timing.render(data)
    (task / "state" / "driver-state.json").unlink()
    assert len(walk_timing.timed_walks(task, [])[L.D1]["items"]) == 2          # no mark: both counted


def test_walk_timing_names_a_marked_item_that_has_no_timing_row(tmp_path):
    """F7: a lane on the old road never opened a session, so no timing row names it: the marks themselves are the list, in both shapes."""
    import walk_timing
    task = tmp_path / "qa-factory" / "artifacts" / "QA-9"
    (task / "state").mkdir(parents=True)
    (task / "state" / "driver-state.json").write_text(json.dumps({"walk_old_road": {"TC-18": "no pair", "TC-19": "no pair"}}), encoding="utf-8")
    none = walk_timing.report(task)                                             # no walk timed at all
    assert none["timed"] is False and none["old_road"] == ["TC-18", "TC-19"], none
    assert "TC-18" in walk_timing.render(none) and "TC-19" in walk_timing.render(none) and "no walk timed" in walk_timing.render(none)
    timing = task / "work" / "walks" / L.D1 / "timing.jsonl"                    # a walked lane beside them
    timing.parent.mkdir(parents=True)
    timing.write_text(json.dumps({"item": "TC-1", "index": 0, "place": "case", "started_at": "2026-11-06T10:00:00",
                                  "ended_at": "2026-11-06T10:01:00"}) + "\n", encoding="utf-8")
    data = walk_timing.report(task)
    assert data["timed"] is True and data["old_road"] == ["TC-18", "TC-19"] and data["places"]["case"]["items"] == 1, data
    assert "TC-18" in walk_timing.render(data)
    (task / "state" / "driver-state.json").unlink()
    assert walk_timing.report(task)["old_road"] == []                          # no mark: nothing named


# --- F6: the teardown carrier ---------------------------------------------------------------------------------------------------------

def test_teardown_check_reads_case_section():
    with road() as rig:
        walked(rig)
        plain = {"thens": thens(rig), "observations": []}
        with R.case_file(rig):                                              # the case names none: nothing is asked
            assert not any("teardown" in p for p in WS.verdict_problems(rig.t.task, CASE, rig.walk.item_rec[CASE]["attempt"].name, plain))
        with R.case_file(rig, teardown="delete the coupon you created"):
            found = WS.verdict_problems(rig.t.task, CASE, rig.walk.item_rec[CASE]["attempt"].name, plain)
            assert any("names a teardown" in p for p in found), found
            assert WS.verdict_problems(rig.t.task, CASE, rig.walk.item_rec[CASE]["attempt"].name, {**plain, "teardown": "done"}) == []
            assert WS._missing_verdict(rig.t.task, WALK, CASE)["teardown"] == "not_done"


# --- F3: the form -------------------------------------------------------------------------------------------------------------------------

def form_exit(rig, rows, dispatch=WALK) -> tuple:
    """Materialize the S6 form, let the driver write `walk_values`, then the REAL `handoff_check.py --fix` over both. `(exit, output)`."""
    task = rig.t.task
    text = handoff_init.fill_head((handoff.CONTRACTS / "s6-runner-to-analyst.yaml").read_text(encoding="utf-8"), task=S.TICKET, dispatch=dispatch,
                                  role="qa-runner", stage="S6", scope=",".join(rows))
    form = task / "work" / "handoffs" / f"{dispatch}.yaml"
    form.parent.mkdir(parents=True, exist_ok=True)
    form.write_text(text, encoding="utf-8")
    subprocess.run([sys.executable, "-B", str(HERE.parent / "finalize_task.py"), str(task)], capture_output=True, text=True)
    d = L.make_driver(task)
    d.walk_values(dispatch, rows)
    done = subprocess.run([sys.executable, "-B", str(HERE.parent / "handoff_check.py"), "--file", str(form), "--task-root", str(task), "--fix", "--no-judge"],
                          capture_output=True, text=True)
    return done.returncode, done.stdout + done.stderr


def rows_of(rig, built, state) -> dict:
    return {CASE: {"state": state, "block": built.get("block"), "evidence": list(built.get("evidence") or []), "missing": False}}


def test_walk_values_passes_handoff_check_exit_0():
    with road() as rig:
        walked(rig)
        assert rig.call("verdict", item=CASE, verdict={"thens": thens(rig), "observations": []})[0] == 0
        built = build(rig)
        code, out = form_exit(rig, rows_of(rig, built, "passed"))
        assert code == 0, out
    with road() as rig:                                                     # failed, and a second case whose record was refused twice
        walked(rig)
        assert rig.call("verdict", item=CASE, verdict={"thens": thens(rig, "fail"), "observations": []})[0] == 0
        built = build(rig)
        rows = {**rows_of(rig, built, "failed"), "TP1-15045_TC_012": {"state": "refused", "reason": "no proof", "n": 2, "missing": False}}
        code, out = form_exit(rig, rows)
        assert code == 0, out


def values_of(rig, name="values.applied.yaml", dispatch=WALK) -> dict:
    return json.loads((rig.t.task / "work" / "handoffs" / f"{dispatch}.{name}").read_text(encoding="utf-8"))


def test_walk_values_say_only_what_was_walked():
    """t-2022 N8: two rows, one never walked and refused: the witness counts the walked ones and the reason is the row's own words. (`executed`
    of such a row: a question to the coordinator, the form's enum has no word for it.)"""
    with road() as rig:
        walked(rig)
        assert rig.call("verdict", item=CASE, verdict={"thens": thens(rig), "observations": []})[0] == 0
        built = build(rig)
        rows = {**rows_of(rig, built, "passed"), "TP1-15045_TC_012": {"state": "refused", "reason": "no step was ever walked: the case file is missing", "n": 2, "missing": True}}
        code, out = form_exit(rig, rows)
        assert code == 0, out
        values = values_of(rig)
        assert "1 of 2 manual case(s) walked" in values["run.witness"] and "over 1 walked case(s)" in values["tried[0].technique"], values
        assert (values["scope[0].executed"], values["scope[1].executed"]) == ("fresh", "none"), values          # `none`: nothing ran; the form takes it
        assert values["scope[1].reason"] == "no step was ever walked: the case file is missing", values["scope[1].reason"]


def test_walk_values_are_applied_again_when_a_late_verdict_changes_the_rows():
    """t-2022 N9: handoff applied, then the walker's late verdict rebuilt a record: the second `walk_values` must write the new words, and the
    same rows again must write nothing (the form is not rewritten over the role's edits)."""
    with road() as rig:
        walked(rig)
        assert rig.call("verdict", item=CASE, verdict={"thens": thens(rig), "observations": []})[0] == 0
        built = build(rig)
        code, out = form_exit(rig, rows_of(rig, built, "inconclusive"))
        assert code == 0, out
        task, form = rig.t.task, rig.t.task / "work" / "handoffs" / f"{WALK}.yaml"
        waiting = form.with_name(f"{WALK}.values.yaml")
        d = L.make_driver(task)
        d.walk_values(WALK, rows_of(rig, built, "inconclusive"))
        assert not waiting.is_file()                                           # the same rows: nothing to say again
        d.walk_values(WALK, rows_of(rig, built, "passed"))
        assert waiting.is_file() and json.loads(waiting.read_text(encoding="utf-8"))["manual_observations[0].result"] == "passed"
        done = subprocess.run([sys.executable, "-B", str(HERE.parent / "handoff_check.py"), "--file", str(form), "--task-root", str(task), "--fix", "--no-judge"],
                              capture_output=True, text=True)
        assert done.returncode == 0, done.stdout + done.stderr
        section = form.read_text(encoding="utf-8").split("manual_observations:")[1]
        assert re.search(r"\bresult:\s*\"?passed", section) and not re.search(r"\bresult:\s*\"?inconclusive", section), section[:400]


def main():
    return pytest.main([str(Path(__file__)), "-q", "-p", "no:cacheprovider"])


if __name__ == "__main__":
    sys.exit(main())
