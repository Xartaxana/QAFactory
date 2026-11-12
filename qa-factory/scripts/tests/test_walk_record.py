#!/usr/bin/env python3
"""t-1957 N2: the result record of a walked item, the reducer to the case record, and the timing report (fake backend, no browser, no network).

`verdict_problems` / `write_verdict` of walk_session.py read the item's ATTEMPT (steps.jsonl, captures.jsonl), never the call answer files;
`manual_evidence.record_from_walk` folds the walker's own per-Then words; `walk_timing.py` reads files and says why a figure is missing.
Mutations -> killing key: the attempt read replaced by the call answer files -> test_batch_and_single_steps_give_same_verdict_problems; the
`final` order check dropped -> test_final_before_last_action_refused; the item filter of the quote search dropped ->
test_quote_from_other_item_refused.
Run: `python -B test_walk_record.py` (exit code = failures).
"""
import contextlib
import io
import json
import sys
import tempfile
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "fixtures" / "manual-evidence"))
import scaffold as S  # noqa: E402
import test_walk_session as W  # noqa: E402

import manual_evidence as ME  # noqa: E402
import walk_timing as WT  # noqa: E402

MC, WS = S.MC, W.WS
CASE, CASE2, WALK, GO = W.CASE, W.CASE2, W.WALK, W.GO
LOOK = GO + "look\n"


@contextlib.contextmanager
def walking(**kw):
    rig = W.Rig(**kw).start()
    try:
        yield rig
    finally:
        rig.done()


def request(rig, item=CASE, thens=("1",), **extra):
    folder = MC.case_root(rig.t.task, item)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "request.json").write_text(json.dumps({"case": item, "thens": {n: f"Then {n}" for n in thens}, **extra}), encoding="utf-8")


def walk(rig, item=CASE, steps=LOOK, final=True):
    code, answer = rig.step(steps, item=item, final=final)
    assert code == 0, answer
    return answer


def attempt_of(rig, item=CASE):
    return rig.walk.item_rec[item]["attempt"].name


def problems(rig, thens, item=CASE, **extra):
    return WS.verdict_problems(rig.t.task, item, attempt_of(rig, item), {"thens": thens, **extra})


def passes(n=1, quote="button: Pay"):
    return {"n": n, "result": "pass", "quote": quote}


def has(found, words):
    return any(words in p for p in found)


# --------------------------------------------------------------------------------------------
# verdict_problems
# --------------------------------------------------------------------------------------------

def test_pass_without_quote_refused():
    with walking() as rig:
        walk(rig)
        found = problems(rig, [{"n": 1, "result": "pass"}])
        assert has(found, "quote the capture that shows it"), found
        assert problems(rig, [passes()]) == [], problems(rig, [passes()])
        assert has(problems(rig, [passes(quote="words nobody captured")]), "is not in the text this item's attempt")


def test_quote_from_other_item_refused():
    with walking() as rig:
        walk(rig)
        rig.made[0].look = lambda selector=None: ("heading: Other\nbutton: Secret", "aria", "", 0.05)
        walk(rig, CASE2)
        assert has(problems(rig, [passes(quote="button: Secret")]), "not in the text this item's attempt")
        assert problems(rig, [passes(quote="button: Secret")], item=CASE2) == []
        named = {**passes(), "capture": next(c["path"] for c in WS.attempt_rows(rig.t.task, CASE2, attempt_of(rig, CASE2))[1])}
        assert has(problems(rig, [named]), "is no capture of this item's attempt")


def test_pass_needs_final_after_last_action():
    with walking() as rig:
        walk(rig, final=False)
        found = problems(rig, [passes()])
        assert has(found, f"walk_session.py final --item {CASE}"), found
        assert problems(rig, [{"n": 1, "result": "fail", "quote": "button: Pay"}]) == []        # only a pass needs the final
        rig.call("final", item=CASE)
        assert problems(rig, [passes()]) == []


def test_final_before_last_action_refused():
    with walking() as rig:
        walk(rig)
        assert problems(rig, [passes()]) == []
        rig.step('click "#a"\n')
        assert has(problems(rig, [passes()]), "BEFORE the last action"), problems(rig, [passes()])
        rig.call("final", item=CASE)
        assert problems(rig, [passes()]) == []


def test_final_of_other_item_refused():
    with walking() as rig:
        walk(rig, CASE, final=False)
        walk(rig, CASE2, final=True)
        assert has(problems(rig, [passes()]), "no final snapshot"), problems(rig, [passes()])


def test_final_between_stopped_and_corrected_batch_refused():
    with walking() as rig:
        rig.made[0].missing = {"#x"}
        code, answer = rig.step(LOOK + 'click "#x"\nclick "#after"\n')
        assert code == 1 and answer["status"] == "stopped"
        rig.call("final", item=CASE)                              # a final taken after the stopped call ...
        assert problems(rig, [passes()]) == []
        rig.made[0].missing = set()
        rig.step('click "#x"\nclick "#after"\n')                   # ... but before the corrected call's actions
        assert has(problems(rig, [passes()]), "BEFORE the last action")


def test_final_deleted_after_is_refused():
    with walking() as rig:
        walk(rig)
        assert problems(rig, [passes()]) == []
        shot = WS.final_state(rig.t.task, CASE, attempt_of(rig))["final"]["screenshot"]
        (rig.t.task / shot).unlink()
        assert has(problems(rig, [passes()]), "no longer on disk")


def test_then_without_result_refused_when_request_lists_thens():
    with walking() as rig:
        request(rig, thens=("1", "2"))
        walk(rig)
        found = problems(rig, [passes(1)])
        assert has(found, "Then 2 has no result"), found
        assert has(problems(rig, [passes(1), {"n": 3, "result": "pass", "quote": "x"}]), "Then 3 is not a Then of this case")
        assert problems(rig, [passes(1), {"n": 2, "result": "inconclusive"}]) == []


@contextlib.contextmanager
def case_file(rig, item=CASE, teardown=""):
    """The case's own file with (or without) a `## Teardown` section, found by the reader the walk brief uses (`brief_pack.case_teardown`)."""
    import brief_pack
    rel = f"work/test-cases/x/{item}.md"
    path = rig.t.task / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\nid: {item}\n---\n\n## Given\n- g\n\n## Then\n1. t\n" + (f"\n## Teardown\n{teardown}\n" if teardown else ""), encoding="utf-8")
    with mock.patch.object(brief_pack, "case_paths", lambda root, scope: [rel]):
        yield


def test_teardown_named_by_the_case_is_asked_for():
    with walking() as rig, case_file(rig, teardown="remove the book"):
        walk(rig)
        assert has(problems(rig, [passes()]), "names a teardown")
        assert problems(rig, [passes()], teardown="done") == []
        assert has(problems(rig, [passes()], teardown="maybe"), "`teardown` is one of")


def test_batch_and_single_steps_give_same_verdict_problems():
    with walking() as rig:
        walk(rig, CASE, steps=LOOK + 'click "#a"\nlook\n')                                 # one call of four steps
        rig.step(GO, item=CASE2)
        for line in ('look\n', 'click "#a"\n', 'look\n'):                                  # the same steps, one per call
            rig.step(line, item=CASE2)
        rig.call("final", item=CASE2)
        verdicts = [[passes()], [{"n": 1, "result": "pass"}], [passes(quote="nothing like it")]]
        for thens in verdicts:
            assert problems(rig, thens, CASE) == problems(rig, thens, CASE2), thens
        assert problems(rig, [passes()], CASE) == []
        batches = lambda item: WS._batch_answers(rig.t.task, WALK, item)                    # noqa: E731
        assert len(batches(CASE)) == 1 and len(batches(CASE2)) == 4                         # the call answers differ, the verdict does not
        assert [r["step"] for r in WS.attempt_rows(rig.t.task, CASE, attempt_of(rig, CASE))[0]][:4] == \
               [r["step"] for r in WS.attempt_rows(rig.t.task, CASE2, attempt_of(rig, CASE2))[0]][:4]


def test_not_run_steps_are_not_actions():
    with walking() as rig:
        rig.made[0].missing = {"#x"}
        code, answer = rig.step(LOOK + 'click "#x"\nclick "#never"\n')
        assert code == 1 and answer["not_run"] == ['click "#never"']
        steps = WS.attempt_rows(rig.t.task, CASE, attempt_of(rig))[0]
        assert not any("#never" in r["step"] for r in steps)                                # no row for a step that never ran
        rig.call("final", item=CASE)
        assert problems(rig, [passes()]) == []                                              # "#never" is not the last action


def test_stop_snapshot_quotable_not_final():
    with walking() as rig:
        rig.made[0].missing = {"#x"}
        code, answer = rig.step(GO + 'click "#x"\n')
        snapshot = answer["page"]["snapshot_file"]
        assert snapshot, answer
        rig.made[0].look = lambda selector=None: ("heading: Cart\nbutton: Pay", "aria", "", 0.05)
        words = " ".join((rig.t.task / snapshot).read_text(encoding="utf-8").split())[:20]
        fail = {"n": 1, "result": "fail", "quote": words}
        assert problems(rig, [fail]) == [], problems(rig, [fail])                           # quotable like a look
        assert has(problems(rig, [{**passes(quote=words)}]), "no final snapshot")           # never a final


def test_stop_snapshot_of_other_item_refused():
    with walking() as rig:
        walk(rig)
        rig.made[0].missing = {"#x"}
        rig.made[0].look = lambda selector=None: ("heading: Elsewhere\nbutton: Hidden", "aria", "", 0.05)
        code, answer = rig.step(GO + 'click "#x"\n', item=CASE2)
        assert answer["page"]["snapshot_file"]
        assert has(problems(rig, [{"n": 1, "result": "fail", "quote": "button: Hidden"}]), "not in the text this item's attempt")


def test_final_flag_capture_satisfies_pass():
    with walking() as rig:
        walk(rig, steps=LOOK + 'click "#a"\n', final=True)
        state = WS.final_state(rig.t.task, CASE, attempt_of(rig))
        assert state["after_action"] and state["final"]["screenshot"] and state["final"]["snapshot"], state
        assert problems(rig, [passes()]) == []


# --------------------------------------------------------------------------------------------
# write_verdict, the missing verdict, timing.jsonl
# --------------------------------------------------------------------------------------------

def test_missing_verdict_is_inconclusive():
    with walking() as rig:
        request(rig, thens=("1", "2"))
        walk(rig)
        record = WS.write_verdict(rig.t.task, WALK, CASE, None)
        assert [t["result"] for t in record["thens"]] == ["inconclusive", "inconclusive"], record
        assert WS.ENDED_WITHOUT_VERDICT in record["limitation"]
        assert json.loads((rig.t.task / "work" / "walks" / WALK / f"{CASE}.json").read_text(encoding="utf-8")) == record


def test_stopped_without_verdict_names_stop():
    with walking() as rig:
        request(rig, thens=("1",))
        rig.made[0].missing = {"#x"}
        rig.step(GO + 'click "#x"\n')
        record = WS.write_verdict(rig.t.task, WALK, CASE, None)
        assert "stopped at step 3" in record["limitation"] and "failed" in record["limitation"], record["limitation"]     # goto, the server's pre_action, click
        assert record["missing_verdict"] is True
        assert record["stops"] == 1 and record["batches"] == 1


def test_result_record_and_timing_line_shape():
    with walking() as rig:
        request(rig, thens=("1",))
        walk(rig, steps=LOOK + 'click "#a"\n')
        code, answer = rig.call("verdict", item=CASE, verdict={"thens": [passes()], "observations": [], "teardown": "none"})
        assert code == 0, answer
        record = json.loads((rig.t.task / answer["file"]).read_text(encoding="utf-8"))
        assert {"walk", "place", "item", "index", "actor", "attempt", "started_at", "ended_at", "steps", "batches", "stops", "thens", "final",
                "observations", "teardown"} <= set(record), record
        assert record["thens"][0]["capture"] and record["final"]["screenshot"] and record["steps"] == 6 and record["batches"] == 1     # + the server's pre_action
        assert "missing_verdict" not in record
        line = [json.loads(x) for x in (rig.t.task / "work" / "walks" / WALK / "timing.jsonl").read_text(encoding="utf-8").splitlines()]
        assert [set(r) for r in line] == [{"item", "index", "place", "started_at", "ended_at", "steps", "batches", "stops", "attempt"}], line
        code, answer = rig.call("verdict", item=CASE, verdict={"thens": [{"n": 1, "result": "pass"}]})
        assert code == 2 and "quote the capture" in answer["text"], answer


# --------------------------------------------------------------------------------------------
# record_from_walk
# --------------------------------------------------------------------------------------------

def folded(thens, **walk_extra):
    seen = {}

    def fake_build(task, case, result, actual, masked, **kw):
        seen.update(result=result, actual=actual, masked=masked, **kw)
        return {"written": True}
    with mock.patch.object(ME, "build_record", fake_build), mock.patch.object(ME, "unprepared_request", lambda t, c: None):
        out = ME.record_from_walk(Path("."), "C", {"attempt": "a1", "thens": thens, **walk_extra})
    return seen, out


def test_fold_fail_wins():
    pas, fail, inc, unr = (dict(n=1, result="pass", quote="q"), dict(n=2, result="fail", quote="w"), dict(n=3, result="inconclusive"),
                           dict(n=4, result="unreached"))
    assert folded([pas, fail, inc, unr])[0]["result"] == "fail"
    assert folded([pas, inc])[0]["result"] == "inconclusive"
    assert folded([pas, unr])[0]["result"] == "inconclusive"
    assert folded([pas])[0]["result"] == "pass"
    assert folded([])[0]["result"] == "inconclusive"                                         # no recorded words, no pass
    seen = folded([pas, fail, unr])[0]
    assert seen["quotes"] == [("text", "1=q"), ("text", "2=w"), ("unreached", "4")] and seen["masked"] is True and seen["attempt"] == "a1"
    assert seen["observations"] == []                                                        # empty observations are legal (AR-23)


def test_unprepared_goes_to_write_unprepared():
    calls = []
    with mock.patch.object(ME, "unprepared_request", lambda t, c: {"reason": "r"}), \
            mock.patch.object(ME, "write_unprepared", lambda t, c, o, not_walked="": calls.append((o, not_walked)) or Path(t) / "b.json"), \
            mock.patch.object(ME, "build_record", side_effect=AssertionError("an unprepared case is never built")), \
            mock.patch.object(ME, "_recorded_walks", lambda t, c: [("a1", [{}], [])]):
        out = ME.record_from_walk(Path("."), "C", {"thens": [{"n": 1, "result": "pass", "quote": "q"}],
                                                   "observations": [{"step": 1, "expected": "e", "seen": "s", "capture": "p", "quote": "q", "about": "case"},
                                                                    {"step": 1, "expected": "e", "seen": "s", "capture": "p", "quote": "q", "about": "card"}]})
    assert out["unprepared"] is True and out["written"] is True
    assert calls == [([{"step": 1, "expected": "e", "seen": "s", "evidence": "p", "quote": "q"}], "")], calls


def test_build_refusal_returned_not_raised():
    def refuse(*a, **k):
        raise ValueError("attempt a1 of C holds no captures: capture first")
    with mock.patch.object(ME, "build_record", refuse), mock.patch.object(ME, "unprepared_request", lambda t, c: None):
        out = ME.record_from_walk(Path("."), "C", {"thens": [{"n": 1, "result": "pass", "quote": "q"}]})
    assert out == {"refused": "attempt a1 of C holds no captures: capture first"}, out


def test_record_from_walk_builds_valid_record():
    t = S.make_task()
    try:
        case = S.CASES["ui"]
        import test_manual_capture as TMC
        import test_manual_evidence as TME
        TME.seed_provenance(t.task, "e2e-ui", S.probe()["expected_source_revision"])
        TMC.ui_run(t, steps=f"goto {TMC.UI}\ncapture pre_action initial\nread {TMC.VIEWPORT} style=transform\ncapture post_action final\n")
        folder = t.attempt_dir(case)
        text = next(c for c in TMC.jsonl(folder / "captures.jsonl") if Path(c["path"]).suffix in ME.QUOTE_SUFFIXES)
        words = " ".join((t.task / text["path"]).read_text(encoding="utf-8").split())[:12]
        with t.patched():
            ME.prepare_to_file(t.task, case, TMC.OBLIGATIONS[case])
            record = {"attempt": "a1", "thens": [{"n": 1, "result": "fail", "quote": words}],
                      "observations": [{"step": 1, "expected": "e", "seen": "s", "capture": text["path"], "quote": words}]}
            thens = json.loads(ME.request_path(t.task, case).read_text(encoding="utf-8")).get("thens") or {}
            record["thens"] = [{"n": int(n), "result": "fail" if i == 0 else "unreached", "quote": words if i == 0 else ""}
                               for i, n in enumerate(sorted(thens, key=int))] or record["thens"]
            done = ME.record_from_walk(t.task, case, record)
            assert done.get("written") is True, done
            written = json.loads((folder / "record.json").read_text(encoding="utf-8"))
            assert written["result"] == "fail" and ME.validate_record(written, t.task, written["evidence_policy"]) == [], written["result"]
    finally:
        S.cleanup(t)


# --------------------------------------------------------------------------------------------
# walk_timing
# --------------------------------------------------------------------------------------------

TS = "2026-11-05T10:{:02d}:{:02d}+00:00"


def timed_story(with_transcript=True, with_launch=True):
    root = Path(tempfile.mkdtemp(prefix="qa-walk-timing-")).resolve()
    qa = root / "qa-factory"
    task = qa / "artifacts" / "T-1"
    (task / "work" / "walks" / "W1").mkdir(parents=True)
    (task / "state").mkdir()
    (qa / "state" / "cost").mkdir(parents=True)
    (qa / "config.json").write_text(json.dumps({"rate_overrides": [{"model_id": "test-model", "revision": "t", "rates": {
        "input": 1.0, "output": 2.0, "cache_read": 0.5, "cache_write_5m": 1.0, "cache_write_1h": 1.0}}]}), encoding="utf-8")
    items = [{"item": "C1", "index": 0, "place": "case", "started_at": TS.format(1, 0), "ended_at": TS.format(2, 0), "steps": 5, "batches": 1, "stops": 0, "attempt": "a1"},
             {"item": "C2", "index": 1, "place": "case", "started_at": TS.format(2, 0), "ended_at": TS.format(4, 0), "steps": 7, "batches": 3, "stops": 2, "attempt": "a1"}]
    lines = [json.dumps(r) for r in items] + [json.dumps({"after_end": TS.format(6, 0)})]
    (task / "work" / "walks" / "W1" / "timing.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    runs = ([{"kind": "launched", "dispatch_id": "W1", "started_at": TS.format(0, 0)}] if with_launch else []) + [
        {"kind": "role", "dispatch": "W1", "session_id": "s1", "total_cost_usd": 0.5, "exit_code": 0, "ts": TS.format(5, 0)},
        {"kind": "role", "dispatch": "W1", "session_id": "s1", "total_cost_usd": 0.75, "exit_code": 0, "ts": TS.format(5, 30)}]
    (task / "state" / "driver-runs.jsonl").write_text("\n".join(json.dumps(r) for r in runs) + "\n", encoding="utf-8")
    if with_transcript:
        def turn(minute, second, rid, calls, usage):
            return json.dumps({"type": "assistant", "timestamp": TS.format(minute, second).replace("+00:00", "Z"), "requestId": rid,
                               "message": {"id": rid, "model": "test-model", "usage": usage,
                                           "content": [{"type": "tool_use", "name": "Bash", "id": f"{rid}{k}"} for k in range(calls)]}})
        use = lambda i, c, r, o: {"input_tokens": i, "cache_creation_input_tokens": c, "cache_read_input_tokens": r, "output_tokens": o}  # noqa: E731
        transcript = qa / "s1.jsonl"
        transcript.write_text("\n".join([turn(0, 30, "r0", 2, use(100, 0, 0, 10)),          # before every window: 2 calls outside
                                         turn(1, 10, "r1", 3, use(1000, 0, 2000, 500)),     # C1
                                         turn(2, 30, "r2", 1, use(2000, 100, 4000, 100)),   # C2
                                         turn(3, 30, "r3", 2, use(500, 0, 1000, 50))]) + "\n", encoding="utf-8")   # C2
        (qa / "state" / "cost" / "s1.json").write_text(json.dumps({"session_id": "s1", "transcript": str(transcript), "by_task": {"T-1": {}}}), encoding="utf-8")
    return task


def test_timing_wall_from_driver_runs():
    task = timed_story()
    data = WT.report(task)
    rep = data["dispatches"][0]
    assert rep["wall_s"] == 360.0 and rep["per_item_wall_s"] == 180.0, rep           # launched 10:00 -> after_end 10:06, over 2 items
    assert rep["role_wall_s"] == 330.0, rep                                           # launched -> the role's LAST result row
    bare = WT.report(timed_story(with_launch=False))["dispatches"][0]
    assert str(bare["wall_s"]).startswith("not measured: no `launched` row"), bare    # a missing figure says why, never 0


def test_cost_last_value_per_session():
    rep = WT.report(timed_story())["dispatches"][0]
    assert rep["cost_usd"] == 0.75, rep                                               # 0.5 then 0.75 of ONE session: the last, not the sum


def test_cost_by_item_index():
    rows = WT.report(timed_story())["dispatches"][0]["rows"]
    assert rows[0]["cost_usd"] == 0.003, rows[0]                                       # r1: 1000*1 + 2000*0.5 + 500*2 per million
    assert rows[1]["cost_usd"] == 0.0054, rows[1]                                      # r2 4300 + r3 1100 per million: both inside C2's window


def test_tool_calls_and_tokens_per_item_from_transcript():
    rows = WT.report(timed_story())["dispatches"][0]["rows"]
    assert rows[0]["tool_calls"] == 4.0 and rows[1]["tool_calls"] == 4.0, rows          # 3 / 1+2 inside the window + 2 outside / 2 items
    assert rows[0]["tokens"] == {"uncached_input": 1000, "cache_creation": 0, "cache_read": 2000, "output": 500}, rows[0]["tokens"]
    assert rows[1]["tokens"] == {"uncached_input": 2500, "cache_creation": 100, "cache_read": 5000, "output": 150}, rows[1]["tokens"]
    assert WT.report(timed_story())["dispatches"][0]["final_context"] == round(1500 / 2)                  # last request: 500 + 0 + 1000


def test_batches_and_stops_per_item():
    rows = WT.report(timed_story())["dispatches"][0]["rows"]
    assert [(r["recorder_calls"], r["stops"]) for r in rows] == [(1, 0), (3, 2)], rows


def test_figures_grouped_by_place():
    task = timed_story()
    path = task / "work" / "walks" / "W1" / "timing.jsonl"
    rows = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()]
    rows[1]["place"] = "explore"
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    places = WT.report(task)["places"]
    assert sorted(places) == ["case", "explore"] and places["case"]["items"] == 1 and places["explore"]["items"] == 1, places
    assert places["case"]["recorder_calls_per_item"] == 1.0 and places["explore"]["recorder_calls_per_item"] == 3.0   # never averaged across places


def test_tool_calls_not_measured_says_why():
    rep = WT.report(timed_story(with_transcript=False))["dispatches"][0]
    row = rep["rows"][0]
    for key in ("cost_usd", "tool_calls", "tokens"):
        assert str(row[key]).startswith("not measured: no transcript found for session s1"), (key, row[key])
    assert str(rep["final_context"]).startswith("not measured"), rep["final_context"]


def test_timing_absent_says_so():
    root = Path(tempfile.mkdtemp(prefix="qa-walk-timing-")).resolve()
    task = root / "qa-factory" / "artifacts" / "T-9"
    task.mkdir(parents=True)
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = WT.main(["--task-root", str(task)])
    assert code == 0 and out.getvalue().strip() == "no walk timed for T-9", out.getvalue()


def test_broken_timing_line_is_counted_and_named():
    task = timed_story()
    path = task / "work" / "walks" / "W1" / "timing.jsonl"
    path.write_text(path.read_text(encoding="utf-8") + "{not json\n", encoding="utf-8")
    data = WT.report(task)
    assert any("timing.jsonl line 4" in p for p in data["problems"]), data["problems"]
    assert "note: " in WT.render(data)


def main():
    import pytest
    return pytest.main([str(Path(__file__)), "-q", "-p", "no:cacheprovider"])


if __name__ == "__main__":
    sys.exit(main())
