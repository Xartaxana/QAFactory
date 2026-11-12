#!/usr/bin/env python3
"""t-1957 N1a, the recorder half of the step-call rule (fake backend, no browser, no network).

This file holds the tests of the `manual_capture.py` pieces the walk server stands on: the `status` number on a `status` line, the
`stop=` call-back of `_run_steps` (the `ui` road passes none and stays as it was), `read ... expect=`, `_store_requests_seen(since=)`.
The tests of the server itself (`walk_session.py`: the batch limits, the stop rules, the answer) are NOT here yet - node N1a is handed
over unfinished, see the report t-1983-walker-n1a-report.md.

Mutations -> killing key: `status` number not stored -> test_status_number_recorded_on_status_line; `stop` ignored by `_run_steps` ->
test_stop_callback_ends_the_loop_row_outcome_unchanged; `since` ignored -> test_requests_seen_since_keeps_only_the_items_requests.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures" / "manual-evidence"))
import scaffold as S  # noqa: E402
import test_manual_capture as T  # noqa: E402
import test_manual_surprise as TS  # noqa: E402
from harness import check, check_eq, check_in, finish  # noqa: E402

MC = S.MC
OTHER = "http://localhost:5173/other"
CASE = T.UI_CASE
READ = "read #price expect=\"$5\""


def _attempt(t):
    return MC.Attempt(t.task, CASE, "a1", t.cfg)


def _steps(text):
    return MC.parse_steps(f"goto {TS.PAGE}\n" + text, MC.spec())


def _run(t, browser, text, stop=None):
    attempt = _attempt(t)
    rows, failed = MC._run_steps(browser, attempt, _steps(text), 100, t.cfg, MC.spec(), 30, MC.SessionAccount(), stop=stop)
    return attempt, rows, failed


def test_status_number_recorded_on_status_line():
    t = S.make_task()
    try:
        b = TS.EventBrowser(born={("click", "#a"): [TS.ev("response", "GET", "/books/3", 503, rid=2),
                                                    TS.ev("pageerror", text="TypeError: x")]})
        _run(t, b, 'click "#a"\n')
        rows = [r for r in TS.lines(t) if r["line"] == "surprise"]
        status = [r for r in rows if r["kind"] == "status"]
        check_eq("the status line carries the answer's number", [r.get("status") for r in status], [503])
        check("a line of another kind carries no status field", all("status" not in r for r in rows if r["kind"] != "status"), str(rows))
    finally:
        S.cleanup(t)


def test_stop_callback_ends_the_loop_row_outcome_unchanged():
    t = S.make_task()
    try:
        seen = []

        def stop(step, row, found, late=False):
            seen.append((step["word"], row["outcome"], late))
            return step["word"] == "click"
        b = TS.EventBrowser()
        attempt, rows, failed = _run(t, b, 'click "#a"\nclick "#b"\nclick "#c"\n', stop=stop)
        check_eq("the loop ended after the step the call-back stopped on", [r["step"] for r in rows],
                 [f"goto {TS.PAGE}", 'click "#a"'][:len(rows)])
        check_eq("two steps ran (the goto, then the click that was stopped on)", len(rows), 2)
        check_eq("the row's own outcome is unchanged and `failed` stays what the outcome says", (rows[-1]["outcome"], failed), ("ok", None))
        check("the call-back was asked after every step that ran", [s[0] for s in seen][:2] == ["goto", "click"], str(seen))
    finally:
        S.cleanup(t)


def test_ui_call_unchanged_without_stop():
    t = S.make_task()
    try:
        _, with_none, _ = _run(t, TS.EventBrowser(), 'click "#a"\nclick "#b"\n')
        t2 = S.make_task()
        try:
            _, with_quiet, _ = _run(t2, TS.EventBrowser(), 'click "#a"\nclick "#b"\n', stop=lambda *a, **k: None)
        finally:
            S.cleanup(t2)
        strip = lambda rows: [{k: v for k, v in r.items() if k not in ("at", "screenshot")} for r in rows]    # noqa: E731
        check_eq("stop=None and a call-back that never stops give the same rows", strip(with_none), strip(with_quiet))
    finally:
        S.cleanup(t)


def test_read_expect_differs_stops_and_records():
    t = S.make_task()
    try:
        stop = lambda step, row, found, late=False: row.get("expect") == "differs"        # noqa: E731
        b = TS.EventBrowser(reads={"#price": "$6"})
        attempt, rows, failed = _run(t, b, f"{READ}\nclick \"#b\"\n", stop=stop)
        check_eq("the read that read otherwise ended the call", len(rows), 2)
        check_eq("the step row records the comparison", rows[-1].get("expect"), "differs")
        check("and its detail says so", "expect: differs" in rows[-1]["detail"], rows[-1]["detail"])
        steps = T.jsonl(attempt.dir / "steps.jsonl")
        check_eq("steps.jsonl holds it", steps[-1].get("expect"), "differs")
    finally:
        S.cleanup(t)
    t = S.make_task()
    try:
        b = TS.EventBrowser(reads={"#price": " $5  "})
        _, rows, _ = _run(t, b, f"{READ}\n")
        check_eq("whitespace is collapsed: equal text matches", rows[-1].get("expect"), "matched")
    finally:
        S.cleanup(t)


def test_read_expect_in_ui_call_only_recorded():
    t = S.make_task()
    try:
        b = TS.EventBrowser(reads={"#price": "$6"})
        code, out, err, _ = T.ui_run(t, f"goto {TS.PAGE}\n{READ}\nclick \"#b\"\n", b)
        check_eq("a `ui` call goes on after a difference (exit 0)", code, 0)
        steps = [s for s in T.jsonl(t.attempt_dir(CASE) / "steps.jsonl") if not s["step"].startswith("login by code")]
        check_eq("every step ran", len(steps), 3)
        check_eq("the difference is recorded", [s.get("expect") for s in steps], [None, "differs", None])
    finally:
        S.cleanup(t)


def test_read_arity_three_is_for_the_expectation_only():
    spec = MC.spec()
    check_eq("`read <sel> expect=x` parses", len(MC.parse_steps(f"goto {TS.PAGE}\nread #p expect=x\n", spec)), 2)
    check_eq("`read <sel> attr=title expect=x` parses", len(MC.parse_steps(f"goto {TS.PAGE}\nread #p attr=title expect=x\n", spec)), 2)
    for bad in ("read #p text attr=title", "read #p a b c", "read #p state=nope expect=x"):
        try:
            MC.parse_steps(f"goto {TS.PAGE}\n{bad}\n", spec)
            refused = False
        except ValueError:
            refused = True
        check(f"`{bad}` is refused", refused)


def test_requests_seen_since_keeps_only_the_items_requests():
    t = S.make_task()
    try:
        b = TS.EventBrowser()
        b.allowed = {MC.host_key(TS.API)}
        b.log = [TS.ev("request", "GET", "/first"), TS.ev("request", "GET", "/second"), TS.ev("response", "GET", "/second", 200, rid=1)]
        b.drain_requests = lambda: {"rows": [{"method": "GET", "url": f"{TS.API}/first"}, {"method": "GET", "url": f"{TS.API}/second"}]}
        attempt = _attempt(t)
        MC._store_requests_seen(b, attempt, t.cfg, since=1)
        files = list(attempt.dir.glob("*requests-seen*"))
        check_eq("only the request after the mark is in the item's file", files[0].read_text(encoding="utf-8").splitlines(),
                 [f"GET {TS.API}/second"])
        other = MC.Attempt(t.task, CASE, "a2", t.cfg)
        MC._store_requests_seen(b, other, t.cfg)
        check_eq("with no mark the whole log is kept, as before",
                 list(other.dir.glob("*requests-seen*"))[0].read_text(encoding="utf-8").splitlines(),
                 [f"GET {TS.API}/first", f"GET {TS.API}/second"])
    finally:
        S.cleanup(t)


# --------------------------------------------------------------------------------------------
# the step-call rule of the server (walk_session.py): limits, stops, answers
# --------------------------------------------------------------------------------------------
import threading  # noqa: E402
import test_walk_session as W  # noqa: E402

WS = W.WS
GO = W.GO


def rig_test(fn):
    """The batch rules are judged on the steps the role sent: the server's own `pre_action` (t-2016 F1, covered by test_walk_road.py) is
    narrowed away here through the data override, so the counts below are the role's steps alone."""
    def narrowed(rig):
        surprise = MC.spec().get("surprise") or {}
        WS.OVERRIDE["pre_not_before"] = [*surprise.get("action_steps", []), *surprise.get("input_steps", [])]
        return fn(rig)
    narrowed.__name__ = fn.__name__
    return W.with_rig(narrowed)


def clicks(n):
    return "".join(f'click "#c{i}"\n' for i in range(n))


@rig_test
def test_batch_runs_all_steps_in_one_call_done(rig):
    code, a = rig.step(GO + clicks(3))
    check_eq("four steps, one call: done, exit 0", (code, a["status"], len(a["steps"]), [s["outcome"] for s in a["steps"]]), (0, "done", 4, ["ok"] * 4))
    check("the answer names its stored file and holds no stop", "stopped_at" not in a and (rig.t.task / a["answer_file"]).is_file())


@rig_test
def test_single_step_call_is_a_batch_of_one(rig):
    rig.step(GO)
    code1, one = rig.step('click "#a"\n')
    code2, many = rig.step('click "#a"\nclick "#b"\n')
    check_eq("a call of one step has the same answer shape as a call of many", (code1, set(one) == set(many)), (0, True))
    rig.made[0].missing = {"#m"}
    code3, stopped = rig.step('click "#m"\n')
    check_eq("and the same stop path: stopped at k = 1, nothing left", (code3, stopped["stopped_at"]["k"], stopped["not_run"]), (1, 1, []))
    rows = T.jsonl(rig.attempt() / "steps.jsonl")
    check("the evidence rows are the same kind", all(set(r) >= {"at", "command", "step", "outcome", "detail"} for r in rows))


@rig_test
def test_batch_empty_refused_nothing_run(rig):
    code, a = rig.step("# only a comment\n\n   \n")
    check_eq("an empty call is refused (2)", code, 2)
    check_in("naming the rule", "at least one step", a["text"])
    check_eq("nothing ran and no attempt opened", ([c for c in rig.made[0].calls if c[0] != "login"], MC.attempts_of(MC.case_root(rig.t.task, W.CASE))), ([], []))


@rig_test
def test_batch_at_limit_runs_over_limit_refused(rig):
    WS.OVERRIDE["max_batch_steps"] = 4
    code, a = rig.step(GO + clicks(3))
    check_eq("exactly the limit runs", (code, a["status"]), (0, "done"))
    before = len(rig.made[0].calls)
    code, a = rig.step(GO + clicks(4))
    check_eq("one more is refused before any step", (code, len(rig.made[0].calls)), (2, before))
    check_in("with the split door", "send steps 1-4 now and the rest as the next call", a["text"])


@rig_test
def test_first_step_deviation_stops_rest_not_run(rig):
    rig.made[0].missing = {"#x"}
    code, a = rig.step(GO + 'click "#x"\nclick "#after"\n')
    check_eq("stopped at the failed step, the rest listed", (code, a["status"], a["stopped_at"]["k"], a["stopped_at"]["reason"]), (1, "stopped", 2, "failed"))
    check_eq("and not run", (a["not_run"], a["not_run_count"]), (['click "#after"'], 1))
    check("no step after the deviation ran", ("click", "#after") not in rig.made[0].calls)
    check_eq("the row of the step that failed is on disk", [r["outcome"] for r in T.jsonl(rig.attempt() / "steps.jsonl") if r["step"] == 'click "#x"'], ["failed"])
    code, a = rig.step('click "#x"\nclick "#after"\n')
    check_eq("a first step that deviates: k = 1, steps 2..n not run", (a["stopped_at"]["k"], a["not_run"]), (1, ['click "#after"']))


@rig_test
def test_last_step_deviation_says_stopped(rig):
    rig.made[0].born[("click", "#b")] = [TS.ev("pageerror", text="TypeError: y")]
    code, a = rig.step(GO + 'click "#a"\nclick "#b"\n')
    check_eq("a console error on the last step: stopped at k = n, nothing to skip", (code, a["stopped_at"]["k"], a["stopped_at"]["reason"], a["not_run"]), (1, 3, "surprise", []))
    code, a = rig.step('click "#a"\n', final=True)
    check_eq("the call after it is done", (code, a["status"]), (0, "done"))


@rig_test
def test_late_5xx_after_last_step_says_stopped(rig):
    b = rig.made[0]
    calls = []
    real = b.settle

    def settle(*args):
        calls.append(1)
        if len(calls) == 2:                  # the step's own pump, then the final pump after the last step
            b.pending.append(TS.ev("response", "GET", "/books/3", 503, rid=9))
        return real(*args)
    b.settle = settle
    code, a = rig.step('click "#a"\n')
    check_eq("a 5xx that arrives after the last step is a stop, not done", (code, a["status"], a["stopped_at"]["k"], a["stopped_at"]["reason"]), (1, "stopped", 1, "surprise"))
    check_eq("the fact carries the number", [f.get("status") for f in a["stopped_at"]["facts"]], [503])


def _blocking_rig(rig):
    gate, started = threading.Event(), threading.Event()
    real = rig.made[0].click

    def click(selector):
        started.set()
        gate.wait(10)
        return real(selector)
    rig.made[0].click = click
    out = {}
    thread = threading.Thread(target=lambda: out.update(result=rig.step(GO + 'click "#a"\nclick "#b"\n')), daemon=True)
    thread.start()
    started.wait(10)
    return gate, thread, out


@rig_test
def test_second_batch_while_running_refused_with_door(rig):
    gate, thread, out = _blocking_rig(rig)
    code, a = rig.step('click "#z"\n')
    check_eq("a second call is refused at once (2)", code, 2)
    check("with the door: wait for call 1, its file, status", all(w in a["text"] for w in ("call 1 of item", "step 2 of 3", "status --walk", "stored at")), a["text"])
    for op in ("look", "final", "item"):
        check_eq(f"{op} is refused too", rig.call(op, item=W.CASE)[0], 2)
    gate.set()
    thread.join(10)
    check_eq("the running call was not interrupted: done with all its steps", (out["result"][0], len(out["result"][1]["steps"])), (0, 3))


@rig_test
def test_status_answered_while_batch_runs(rig):
    gate, thread, out = _blocking_rig(rig)
    code, a = rig.call("status")
    check_eq("status is answered while a call runs, and names it", (code, a["running"]["batch"], a["running"]["item"]), (0, 1, W.CASE))
    gate.set()
    thread.join(10)
    code, a = rig.call("status")
    check_eq("afterwards nothing runs and the last call is named", (a["running"], a["last_call"]["status"]), (None, "done"))


@rig_test
def test_batch_answer_stored_when_caller_gone(rig):
    gate, thread, out = _blocking_rig(rig)
    gate.set()
    thread.join(10)                                    # nobody reads out["result"]: the server stored the answer all the same
    path = rig.walk.batch_path(W.CASE, 1)
    check("the answer file is on disk", path.is_file())
    check_eq("it holds the whole answer and the lock is free", (json.loads(path.read_text(encoding="utf-8"))["status"], rig.walk.busy.locked()), ("done", False))
    check_eq("status names the last call's file", rig.call("status")[1]["last_call"]["file"], rig.walk.rel(path))


@rig_test
def test_stopped_item_keeps_attempt_end_probe_at_close(rig):
    rig.made[0].missing = {"#x"}
    code, a = rig.step(GO + 'click "#x"\n' + "capture pre_action initial\n")
    check_eq("the call stopped", code, 1)
    check_eq("the attempt stays open", rig.walk.item_rec[W.CASE]["attempt"].name, "a1")
    rig.step(GO + "capture pre_action initial\n", item=W.CASE2)           # leaving the stopped item flushes it, never closes it
    rig.call("close")
    check_eq("it still gets its end probe at close", sorted(r["when"] for r in T.jsonl(rig.attempt() / "probes.jsonl")), ["end", "start"])


@rig_test
def test_next_batch_runs_from_the_same_page(rig):
    rig.made[0].missing = {"#x"}
    rig.step(GO + 'click "#x"\n')
    rig.made[0].missing = set()
    code, a = rig.step('click "#ok"\ncapture pre_action initial\n')
    check_eq("the next call needs no goto and writes into the same attempt", (code, a["batch"], rig.walk.item_rec[W.CASE]["attempt"].name), (0, 2, "a1"))
    check_eq("the page was visited once", len([c for c in rig.made[0].calls if c[0] == "goto"]), 1)


@rig_test
def test_stop_on_unknown_kind_refused_names_kinds(rig):
    for bad, word in (("nonsense", "nonsense"), ("status:200-299", "400 <= lo"), ("status:5xx", "status:5xx"), ("status:550-500", "400 <= lo")):
        code, a = rig.step(GO, stop_on=[bad])
        check_eq(f"`{bad}` is refused before any step", (code, [c for c in rig.made[0].calls if c[0] == "goto"]), (2, []))
        check_in(f"`{bad}`: the refusal names it", word, a["text"])
    check_in("and lists the kinds from the data", "blocked_host", rig.step(GO, stop_on=["nonsense"])[1]["text"])


@rig_test
def test_stop_on_none_still_stops_on_failed_step(rig):
    rig.made[0].elapsed = {"goto": 1000.0}
    code, a = rig.step(GO + 'click "#a"\n', stop_on=["none"])
    check_eq("`none` with a step that timed out still stops", (code, a["stopped_at"]["reason"], a["not_run"]), (1, "timeout", ['click "#a"']))
    rig.made[0].elapsed = {}
    rig.made[0].missing = {"#m"}
    code, a = rig.step('click "#m"\nclick "#a"\n', stop_on=["none"])
    check_eq("and with a failed one; the role's switch cannot turn rule (1) off", (a["stopped_at"]["reason"], a["not_run"]), ("failed", ['click "#a"']))
    rig.made[0].missing = set()
    rig.made[0].born[("click", "#a")] = [TS.ev("response", "GET", "/x", 503, rid=3)]
    check_eq("while a 5xx no longer stops under `none`", rig.step('click "#a"\n', stop_on=["none"])[1]["status"], "done")


@rig_test
def test_final_flag_only_on_done(rig):
    code, a = rig.step(GO + "capture pre_action initial\n", final=True)
    check_eq("on a done call the final is part of it", (code, [o["outcome"] for o in a["final"]]), (0, ["ok", "ok"]))
    rig.made[0].missing = {"#x"}
    code, a = rig.step('click "#x"\n', final=True)
    late = [c["path"] for c in T.jsonl(rig.attempt() / "captures.jsonl") if "completion" in c["path"]]
    check_eq("a stopped call takes no final (the one completion capture is from the call before)", (code, a["final"], len(late)), (1, "no final: the call stopped", 1))


@rig_test
def test_default_stops_on_5xx_console_url(rig):
    b = rig.made[0]
    rig.step(GO)
    b.born[("click", "#e5")] = [TS.ev("response", "GET", "/books/3", 503, rid=2)]
    b.born[("click", "#ec")] = [TS.ev("pageerror", text="TypeError: x")]
    b.nav[("goto", OTHER)] = "http://localhost:5173/auth/sign-in"
    for sel, kind in (("#e5", "status"), ("#ec", "console"), (OTHER, "url")):
        code, a = rig.step((f'click "{sel}"\n' if kind != "url" else f"goto {sel}\n") + 'click "#after"\n')
        check_eq(f"{kind}: stopped under the default, the next step did not run", (code, a["stopped_at"]["reason"], a["stopped_at"]["facts"][0]["kind"], a["not_run"]),
                 (1, "surprise", kind, ['click "#after"']))
    check_eq("a redirect to the sign-in page stopped as `url` (the last loop pass)", a["stopped_at"]["facts"][0]["fact"].endswith("/auth/sign-in"), True)


@rig_test
def test_default_records_4xx_and_field_without_stop(rig):
    b = rig.made[0]
    rig.step(GO)
    b.born[("click", "#a")] = [TS.ev("response", "GET", "/books/3", 404, rid=2)]
    b.typed = {"#qty": [{"n": 1, "value": "1", "focus": True}, {"n": 2, "value": "1", "focus": True}, {"n": "settled", "value": "1", "focus": True}]}
    code, a = rig.step('click "#a"\ntype "#qty" 12\n')
    check_eq("a 4xx and an application-changed value are recorded, not stopped on", (code, a["status"]), (0, "done"))
    kinds = {r["kind"] for r in T.jsonl(rig.attempt() / "surprises.jsonl") if r["line"] == "surprise"}
    check("the lines are on disk", {"status", "field"} <= kinds, str(kinds))


@rig_test
def test_stop_on_widened_and_narrowed_per_call(rig):
    b = rig.made[0]
    rig.step(GO)
    b.born[("click", "#a")] = [TS.ev("response", "GET", "/books/3", 404, rid=2)]
    b.born[("click", "#ec")] = [TS.ev("pageerror", text="TypeError: x")]
    check_eq("`+status:400-499` adds to the default", rig.step('click "#a"\nclick "#n"\n', stop_on=["+status:400-499"])[1]["stopped_at"]["reason"], "surprise")
    check_eq("`-console` removes from it", rig.step('click "#ec"\nclick "#n"\n', stop_on=["-console"])[1]["status"], "done")
    check_eq("rules without a sign replace it (a 5xx no longer stops, a 4xx does)", rig.step('click "#a"\n', stop_on=["status:400-499"])[1]["status"], "stopped")


@rig_test
def test_own_fail_request_never_stops(rig):
    b = rig.made[0]
    b.born[("click", "#pay")] = [TS.ev("response", "POST", "/pay", 500, rid=4, ours=True)]
    code, a = rig.step(GO + 'fail_request "**/api/x**" 500\nclick "#pay"\n')
    check_eq("a 500 the role's own fail_request caused is never a status line, never a stop", (code, a["status"]), (0, "done"))


def test_unreadable_status_number_stops():
    d = WS.data()
    line = {"id": "a1-ui-S1", "kind": "status", "fact": "not kept: matches secret_content_patterns[1]"}
    now, rules = WS._clock(), WS.stop_rules([], d)
    hit = WS.stop_at({"outcome": "ok"}, [line], rules, now, d)
    check_eq("a status line with no readable number stops (never read as below 500)", hit and hit["reason"], "surprise")
    check("a number outside every rule does not", WS.stop_at({"outcome": "ok"}, [{**line, "status": 404}], rules, now, d) is None)
    check("a number inside it does", WS.stop_at({"outcome": "ok"}, [{**line, "status": 503}], rules, now, d) is not None)
    check("a bool is no number", WS.stop_at({"outcome": "ok"}, [{**line, "status": True}], rules, now, d) is not None)


@rig_test
def test_stop_snapshot_state_file_and_excerpt(rig):
    rig.made[0].missing = {"#x"}
    code, a = rig.step(GO + 'click "#x"\n')
    page = a["page"]
    caps = T.jsonl(rig.attempt() / "captures.jsonl")
    check("the snapshot is a state file of the item's attempt, in the answer", page["snapshot_file"] and any(c["path"] == page["snapshot_file"] and c["kind"] == "state" and c["phase"] == "supporting" for c in caps), str(page))
    check_in("with an excerpt of the page", "heading: Cart", page["excerpt"])
    check("named stop-<batch>-<k>", "stop-1-2" in page["snapshot_file"], page["snapshot_file"])


@rig_test
def test_no_stop_snapshot_in_signin_window(rig):
    rig.walk.accounts["user"].window = True
    code, a = rig.step("capture pre_action initial\n")
    check_eq("a step refused inside the window stops", (code, a["stopped_at"]["reason"]), (1, "refused"))
    check_eq("and the answer says there is no snapshot", (a["page"]["snapshot_file"], "sign-in window" in a["page"]["excerpt"], getattr(rig.made[0], "looked", 0)), (None, True, 0))


@rig_test
def test_batch_time_budget_stops_between_steps(rig):
    WS.OVERRIDE["batch_max_s"] = 1
    tick = [0.0]
    WS.SEAMS["clock"] = lambda: tick.__setitem__(0, tick[0] + 2) or tick[0]
    try:
        code, a = rig.step(GO + clicks(2))
        check_eq("a spent budget stops between steps", (code, a["stopped_at"]["reason"], a["stopped_at"]["k"], a["not_run_count"]), (1, "batch_time", 1, 2))
        code, a = rig.step('click "#last"\n')
        check_eq("but never after the last step", (code, a["status"]), (0, "done"))
    finally:
        WS.SEAMS["clock"] = None


def test_stop_rules_from_data():
    d = WS.data()
    check_eq("no token: the data default", WS.stop_rules([], d), d["stop_on_default"])
    check_eq("`none` is the empty list", WS.stop_rules(["none"], d), [])
    check_eq("`default,+field` adds to the data default", WS.stop_rules(["default", "+field"], d), [*d["stop_on_default"], "field"])
    check_eq("`-console` removes", WS.stop_rules(["-console"], d), ["status:500-599", "url"])
    check_eq("an unsigned token replaces the default", WS.stop_rules(["status:400-599", "url"], d), ["status:400-599", "url"])
    check_eq("`none,+failed` replaces, then adds", WS.stop_rules(["none", "+failed"], d), ["failed"])
    WS.OVERRIDE["stop_on_default"] = ["field"]
    try:
        check_eq("the default is the data's, not a literal of the code", WS.stop_rules([], WS.data()), ["field"])
    finally:
        WS.OVERRIDE.clear()


def main():
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    finish("test_walk_batch")


if __name__ == "__main__":
    main()
