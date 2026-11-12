#!/usr/bin/env python3
"""t-1957 N5s: the driver runs serial walk lanes; code before and after inside `run_role`; the door and the progress line are twins
(AR-14, AR-15, AR-19, AR-25, AR-28, AR-29).

Keys: `controller.walk_lanes` groups cases by the key of their account set and cuts at three; guests are one lane; a case whose request
cannot be read walks alone. `run_role(after=)` runs `after` once the result exists (fresh, reused or `{}` after a crash) and BEFORE `bind`,
`handoff` and `finish`; `walk_after` is idempotent, closes a lane's cases, re-queues a refused build ONCE and then closes it
`left_unchecked`; `walk_before` makes the run report, falls back to today's road when `open` fails; `resume_role` reopens the session
before the role is resumed; the door and the progress line cut lanes with the driver's function and size.

Mutations this file kills: `after` moved after `finish` (test_after_runs_before_bind) | `after` outside the `finally` | the retry counter
never closing | `open` before the report | the reopen after the resume | a literal size in the door or the progress line.

Run: python -B scripts/tests/test_walk_lanes.py    or    python -m pytest -p no:cacheprovider scripts/tests/test_walk_lanes.py -q
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import pytest  # noqa: E402
import controller  # noqa: E402
import manual_evidence as ME  # noqa: E402
import story_run  # noqa: E402
import story_step  # noqa: E402
import walk_session as WS  # noqa: E402

D1 = "S6-qa-runner-1"


def write_request(root: Path, case: str, body: dict) -> None:
    path = ME.request_path(root, case)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(body), encoding="utf-8")


def account(handle: str) -> dict:
    return {"actors": [{"id": handle, "check": {"stand_account": handle}}]}


def make_driver(root: Path, py=None) -> "story_run.Driver":
    d = story_run.Driver.__new__(story_run.Driver)
    d.task_root, d.task, d.state, d.events = root, "QA-9", {}, []
    d.state_dir = root / "state"
    d.save_state = lambda: None
    d.py = py or (lambda script, *args, **kw: d.events.append(("py", script, args[0] if args else "")) or (0, ""))
    return d


# --- the cut -----------------------------------------------------------------------------------------------------------------------

def test_groups_by_account_set_and_cuts_at_three():
    keys = {"a": "stand_account:admin", "b": "", "c": "stand_account:admin", "d": "stand_account:admin", "e": "", "f": "stand_account:admin"}
    lanes = controller.walk_lanes(list("abcdef"), keys, controller.MANUAL_WINDOW_CASES)
    assert controller.MANUAL_WINDOW_CASES == 3
    assert lanes == [["a", "c", "d"], ["f"], ["b", "e"]], lanes          # plan-row order inside a key, a cut at three
    assert controller.walk_lanes(["a", "b"], {"a": "", "b": ""}, 0) == [["a"], ["b"]]          # a size below 1 is the smallest lane
    assert controller.walk_lanes([], {}, 3) == []


def test_guest_cases_one_lane(tmp_path):
    cases = [f"TC-{n}" for n in range(1, 5)]
    for case in cases[:2]:
        write_request(tmp_path, case, {"evidence_policy": "ui"})                  # a request that names no account
    keys = controller.lane_keys(tmp_path, cases)                                   # TC-3, TC-4: no request file at all
    assert set(keys.values()) == {""}, keys
    assert controller.walk_lanes(cases, keys, 3) == [cases[:3], cases[3:]]


def test_unreadable_request_lane_of_one(tmp_path):
    write_request(tmp_path, "TC-1", account("admin"))
    write_request(tmp_path, "TC-2", {"actors_unreadable": "the Given names an account nobody can read"})
    write_request(tmp_path, "TC-3", account("admin"))
    keys = controller.lane_keys(tmp_path, ["TC-1", "TC-2", "TC-3"])
    assert "TC-2" not in keys and keys["TC-1"] == keys["TC-3"] != "", keys
    assert controller.walk_lanes(["TC-1", "TC-2", "TC-3"], keys, 3) == [["TC-1", "TC-3"], ["TC-2"]]
    # a key that is a case id never collides with a lane of its own
    assert controller.walk_lanes(["x", "y"], {"x": "y"}, 3) == [["x"], ["y"]]


# --- run_role: after ---------------------------------------------------------------------------------------------------------------

def role_driver(root: Path, crash=False):
    d = make_driver(root)
    d.plugin = d.scripts = "P"
    d.stages = lambda: {"S6": {}}
    d.system_file = lambda *a: None
    d.progress_line = lambda: None
    d.retire_infra_result = lambda *a, **k: False
    d.digest_of = lambda text: text
    d.records_exist = False

    def run_claude(*a, **k):
        d.events.append("role")
        if crash:
            raise story_run.Refusal("the role crashed", dispatch=D1)
        return {"result": "done", "session_id": "s1", "is_error": False}

    def py(script, *args, **kw):
        d.events.append(("bind", d.records_exist) if args and args[0] == "bind" else ("py", script))
        return 0, ""
    d.run_claude, d.py = run_claude, py
    d.handoff = lambda *a, **k: d.events.append("handoff") or "digest"
    d.question_threshold = lambda *a, **k: d.events.append("threshold")
    d.repair_limit_gate = lambda *a, **k: d.events.append("gate")
    d.finish = lambda *a, **k: d.events.append("finish") or ("digest", {})
    for rel in (story_step.FORM_REL.format(dispatch_id=D1), ):
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text("x", encoding="utf-8")
    card = story_step.launch_card.card_path(root, D1)
    card.parent.mkdir(parents=True, exist_ok=True)
    card.write_text("x", encoding="utf-8")
    return d


def run_it(d, after):
    return d.run_role("S6", "qa-runner", scope=["TC-1"], rework={"id": D1, "scope": ["TC-1"], "reason": "manual block"}, after=after)


@pytest.fixture
def seams(monkeypatch):
    monkeypatch.setattr(story_step, "_brief", lambda *a, **k: ("", ""))
    monkeypatch.setattr(story_step, "_prompt", lambda *a, **k: "prompt")
    monkeypatch.setattr(story_step, "_declared_halt", lambda *a, **k: False)


def test_after_runs_before_bind(tmp_path, seams):
    d = role_driver(tmp_path)

    def after(dispatch, result):
        d.records_exist = True
        d.events.append("after")
    run_it(d, after)
    order = [e if isinstance(e, str) else e[0] for e in d.events if e != ("py", "x")]
    assert order == ["role", "after", "bind", "handoff", "threshold", "gate", "finish"], d.events
    assert ("bind", True) in d.events           # the records existed when bind (and so the running dispatch) was reached


def test_after_runs_on_reused_saved_result(tmp_path, seams):
    d = role_driver(tmp_path)
    saved = d.state_dir / "driver-runs" / f"{D1}.json"
    saved.parent.mkdir(parents=True)
    saved.write_text(json.dumps({"result": "earlier", "session_id": "s0", "is_error": False}), encoding="utf-8")
    seen = []
    run_it(d, lambda dispatch, result: seen.append((dispatch, result["result"])))
    assert "role" not in d.events and seen == [(D1, "earlier")], (d.events, seen)


def test_after_runs_when_role_crashes(tmp_path, seams):
    d = role_driver(tmp_path, crash=True)
    seen = []
    with pytest.raises(story_run.Refusal):
        run_it(d, lambda dispatch, result: seen.append((dispatch, result)))
    assert seen == [(D1, {})] and "handoff" not in d.events and "finish" not in d.events, (seen, d.events)


# --- walk_after --------------------------------------------------------------------------------------------------------------------

def stub_records(monkeypatch, built):
    calls = {"build": [], "verdict": []}
    monkeypatch.setattr(ME, "record_from_walk", lambda t, case, rec: calls["build"].append(case) or dict(built(case)))
    monkeypatch.setattr(WS, "write_verdict", lambda t, w, case, verdict, **k: calls["verdict"].append((case, verdict)) or {"thens": []})
    return calls


def test_after_is_idempotent(tmp_path, monkeypatch):
    calls = stub_records(monkeypatch, lambda case: {"written": True, "case": case, "result": "pass", "block": f"work/{case}.json"})
    d = make_driver(tmp_path)
    d.walk_after(["TC-1", "TC-2"], D1, {})
    first = list(calls["build"])
    d.walk_after(["TC-1", "TC-2"], D1, {"result": "reused"})
    assert first == ["TC-1", "TC-2"] and calls["build"] == first, calls
    # a walker that ended with no verdict: the result record is made from nothing (every Then inconclusive), then built
    assert [c for c, v in calls["verdict"]] == ["TC-1", "TC-2"] and all(v is None for _c, v in calls["verdict"])
    timing = (tmp_path / "work/walks" / D1 / "timing.jsonl").read_text(encoding="utf-8").splitlines()
    assert sum('"after_end"' in line for line in timing) == 1, timing
    values = json.loads((tmp_path / "work/handoffs" / f"{D1}.values.yaml").read_text(encoding="utf-8")) if (tmp_path / "work/handoffs" / f"{D1}.values.yaml").is_file() else None
    assert values is None        # no form there: no values file is written beside nothing


def test_build_refusal_requeued_once_then_closed(tmp_path, monkeypatch):
    stub_records(monkeypatch, lambda case: {"refused": "no proof of the landing"})
    d = make_driver(tmp_path)
    d.manual_done = lambda: {"TC-1"}                  # the lane was accepted with TC-1 in it
    d.manual_order = lambda given: list(given)
    d.manual_prepare = lambda case: ([f"OB-{case}"], "", "")
    d.walk_after(["TC-1"], D1, {})
    assert d.state["walk_retry"]["TC-1"]["open"] is True and d.walk_pending(["TC-1"])
    assert d.manual_plan(["TC-1"])["blocks"] == [["TC-1"]]          # once more, in the next lane
    d.walk_after(["TC-1"], "S6-qa-runner-2", {})
    entry = d.state["walk_retry"]["TC-1"]
    assert entry["refused"] == 2 and entry["open"] is False and d.walk_pending(["TC-1"])
    refused = json.loads(ME.request_path(tmp_path, "TC-1").read_text(encoding="utf-8"))["refused"]
    assert refused["by"] == "left_unchecked" and "no proof of the landing" in refused["reason"], refused
    assert d.manual_plan(["TC-1"])["blocks"] == []                  # the manual_close road, not a third walk


def test_done_cases_not_redispatched():
    d = story_run.Driver.__new__(story_run.Driver)
    prepared = []
    d.task_root, d.state = None, {}
    d.manual_done = lambda: {"TC-1", "TC-2"}
    d.manual_order = lambda given: list(given)
    d.manual_prepare = lambda case: prepared.append(case) or ([f"OB-{case}"], "", "")
    plan = d.manual_plan(["TC-1", "TC-2", "TC-3"])
    assert plan["blocks"] == [["TC-3"]] and prepared == ["TC-3"], (plan, prepared)


# --- walk_before -------------------------------------------------------------------------------------------------------------------

def test_open_failure_falls_back_to_capture_road(tmp_path):
    record = tmp_path / "state/walks" / f"{D1}.json"
    record.parent.mkdir(parents=True)
    calls = []

    def py(script, *args, **kw):
        calls.append((script, args))
        if script == "walk_session.py":
            record.write_text("{}", encoding="utf-8")            # open leaves a dead record behind
            return 3, "the walk session did not start: the stand is held"
        return 0, "app-card: unchanged"
    d = make_driver(tmp_path, py)
    got = d.walk_before(["TC-1"], D1)
    assert got["walking"] is False and not record.exists(), (got, calls)        # no walk record: today's brief
    ok = make_driver(tmp_path, lambda script, *a, **k: (0, "ready"))
    assert ok.walk_before(["TC-1"], D1)["walking"] is True


def test_run_report_made_before_walk(tmp_path):
    report = tmp_path / "work/run-report.json"
    calls = []

    def py(script, *args, **kw):
        calls.append(script)
        if script == "finalize_task.py":
            report.parent.mkdir(parents=True, exist_ok=True)
            report.write_text("{}", encoding="utf-8")
        return 0, "ok"
    got = make_driver(tmp_path, py).walk_before(["TC-1"], D1)
    assert calls.index("finalize_task.py") < calls.index("walk_session.py") and got["report_last"] is False, calls
    report.unlink()
    # TEMPORAL (E5s.3): finalize_task cannot make a report from zero blocks -> the brief names it as the walker's last command
    got = make_driver(tmp_path, lambda script, *a, **k: (1, "no blocks") if script == "finalize_task.py" else (0, "ok")).walk_before(["TC-1"], D1)
    assert got["report_last"] is True and got["walking"] is True


# --- resume ------------------------------------------------------------------------------------------------------------------------

def test_resume_reopens_session_first(tmp_path, seams, monkeypatch):
    record = tmp_path / "state/walks" / f"{D1}.json"
    record.parent.mkdir(parents=True)
    record.write_text(json.dumps({"state": "dead", "items": ["TC-1", "TC-2"], "actors": ["admin"]}), encoding="utf-8")
    d = make_driver(tmp_path)
    d.state.update({"sessions": {D1: "s1"}, "pending_words": {}})
    d.pipeline = lambda: {}
    d.record_running = lambda *a, **k: None
    d.progress_line = lambda: None
    prompts = []

    def py(script, *args, **kw):
        d.events.append(("py", script, args[0]))
        return 0, json.dumps({"status": "ready", "signed_in": True, "landed_on": "/home"})
    d.py = py

    def run_claude(kind, prompt, **k):
        prompts.append(prompt)
        d.events.append("role")
        return {"result": "done", "session_id": "s1", "is_error": False}
    d.run_claude = run_claude
    d.walk_after = lambda lane, dispatch, result: d.events.append(("after", tuple(lane)))
    d.handoff = lambda *a, **k: d.events.append("handoff") or "digest"
    d.question_threshold = lambda *a, **k: None
    d.repair_limit_gate = lambda *a, **k: None
    d.finish = lambda *a, **k: d.events.append("finish") or ("digest", {})
    d.resume_role("S6", "qa-runner", D1, "go on")
    names = [e if isinstance(e, str) else e[0] + ":" + e[1] if e[0] == "py" else e[0] for e in d.events]
    assert names == ["py:walk_session.py", "role", "after", "handoff", "finish"], d.events
    assert d.events[0][2] == "open" and "reopened" in prompts[0] and "signed in" in prompts[0], prompts


# --- the twins ---------------------------------------------------------------------------------------------------------------------

def test_door_and_progress_use_walk_lanes(tmp_path, monkeypatch):
    import story_progress as SP
    seen = []
    real = controller.walk_lanes

    def spy(cases, keys, size):
        seen.append((list(cases), size))
        return real(cases, keys, size)
    monkeypatch.setattr(controller, "walk_lanes", spy)
    monkeypatch.setattr(story_step, "walk_lanes", spy)
    monkeypatch.setattr(story_step, "_task_root", lambda task: tmp_path)
    cases = [f"TC-{n}" for n in range(1, 8)]
    ctl = type("Ctl", (), {"stage_scope": lambda self, stage, state, half: {"derived": True, "scope": cases}})()
    lines = story_step._manual_block_door("QA-9", [], {}, ctl)
    assert "--scope TC-1,TC-2,TC-3" in lines[0] and "then 2 more block(s) of at most 3 case(s)" in lines[1], lines
    monkeypatch.setattr(SP, "_scope_of", lambda *a, **k: {"derived": True, "scope": cases})
    position = SP._block_position(tmp_path, {}, [], None, "QA-9")
    assert position["blocks_total"] == 3 == len(real(cases, {c: "" for c in cases}, 3))          # one function, one size: the door's 3 lanes
    assert [size for _c, size in seen] == [3, 3] and seen[0][0] == seen[1][0] == cases, seen


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q", "-p", "no:cacheprovider"]))
