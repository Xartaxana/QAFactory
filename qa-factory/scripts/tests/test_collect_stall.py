"""The stall rule of the COLLECT skill (t-962 section 5 under the Lead's L-2 F-1/F-2, node CL1-3, FR-28: a measurer is code).

Expectations come from the spec and the review (docs/tasks/specs/t-962-collect-skill.md section 5, L-2; docs/tasks/specs/reviews/
t-972-t-962-collect-plan.md F-1 (a)-(e), F-2, m1) and from the census (t-948 section I) - never from what `collect_stall` prints
(FR-58). Keys:

  K1..K7   one signal each: the carrier field, its own window time, strictly AFTER the mark (AT the mark is not counted)
  F-1 a    "the role just returned": `returned_unaccepted` inside the quiet window is no stall; AT the window no, BEYOND yes
  F-1 b    `stale`, F-1 c `blocked`/`incomplete`/`paused`, F-1 d `running` + `unknown` are no signals
  F-1 d/e  "running now": a live dispatch is not `current`; a snapshot with no time is never a signal
  F-1 e    "waiting for a person": an open gate / question is a record and clears `current` ONLY; a K-signal or `unreadable`
           still makes the story stalled (t-1022 M-1: a conductor `stop` always opens the question)
  M-2      a launch with no end row younger than the quiet window is a call running now, not K3 (AT the window no, BEYOND yes)
  M-3      valid JSON in a shape the rule does not know (list for dict, huge integer, list status, string stage) is a named
           `unreadable` reason, never a raise; the other signals are still judged
  M-4      an unreadable carrier of the story's sessions is a named gap in H, never "no session is recorded"
  m-1/m-2  a BOM on a jsonl file is the encoding; one time parser (`dispatch_liveness._epoch`) behind the wrapper
  F-1      the status sets are read from `controller` at call time (a twin tied by a test, not a table of our own)
  m1       K4 fires only when the LAST outcome of the same dispatch is an error
  edges    `unreadable` (the safe side, FR-41): nothing readable, a mark in the future, a broken line, a bad parameter
  F-2      "another story's subagent": H keeps only the subagent folders of the story's own session transcripts
  reader   the file reader on a scratch project; `judge` never touches a disk and never changes its input

Run:  python -B scripts/tests/test_collect_stall.py
"""
import builtins
import copy
import io
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import check, check_eq, cleanup, finish, temp_dir  # noqa: E402

sys.path.insert(0, str(harness.SCRIPTS))
import archive_task  # noqa: E402
import collect_stall as CS  # noqa: E402
import controller  # noqa: E402

H = 3600
NOW = 1_800_000_000
QUIET = 24 * H
MARK = NOW - 10 * H            # the last collect: ten hours ago


def facts(**over):
    """A CLOSED, clean story: no signal can come out of it until a test adds one."""
    return dict({"closed": True, "unreadable": []}, **over)


def open_story(**over):
    """An open story with a fresh stamp (an hour old): not current until a test ages it."""
    return facts(closed=False, last_activity=NOW - H, **over)


def ids(verdict):
    return sorted(s["id"] for s in verdict["signals"])


def judge(f, mark=MARK, now=NOW, quiet=24):
    return CS.judge(f, mark, now, quiet)


def disp(ident, status, **kw):
    return dict({"id": ident, "status": status, "started_at": None, "returned_at": None, "liveness": None}, **kw)


def iso(epoch):
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat(timespec="seconds")


def edge(name, make, expect_at, expect_beyond):
    """A window edge: AT the mark (or at the quiet limit) is not a signal, one second BEYOND it is. `make(t)` builds facts."""
    check(f"{name}: AT the limit is not counted", ids(judge(make(expect_at))) == [], str(judge(make(expect_at))["signals"]))
    check(f"{name}: one second BEYOND is counted", ids(judge(make(expect_beyond))) != [],
          str(judge(make(expect_beyond))["signals"]))


def k_signals():
    # K1 driver-state.interrupted, window `at`
    f = lambda t: facts(interrupted=[{"key": "S5-qa-automator-2", "at": t}])  # noqa: E731
    check_eq("K1: a cut-off call after the mark", ids(judge(f(MARK + 1))), ["K1"])
    check_eq("K1: the signal carries its own time", judge(f(MARK + 1))["signals"][0]["at"], MARK + 1)
    edge("K1 window (`at`)", f, MARK, MARK + 1)
    check_eq("K1: an ISO time is read like an epoch", ids(judge(f(iso(MARK + 5)))), ["K1"])
    v = judge(facts(interrupted=[{"key": "S8:delivery"}]))
    check("K1: an entry with no `at` is never a signal, and is named", ids(v) == [] and v["ignored"][0]["where"].endswith("S8:delivery"),
          str(v))
    # K2 in_flight with a dead pid
    f = lambda t, **kw: facts(in_flight=[dict({"dispatch": "S5-x-1", "started_at": t, "alive": False, "reused": None}, **kw)])  # noqa: E731
    check_eq("K2: the driver's process is gone", ids(judge(f(MARK + 1))), ["K2"])
    check_eq("K2: the pid is live but taken over by another process", ids(judge(f(MARK + 1, alive=True, reused=True))), ["K2"])
    check_eq("K2: a live pid that is the dispatch's own is no stall", ids(judge(f(MARK + 1, alive=True, reused=False))), [])
    check_eq("K2: a pid that could not be asked (None) is not a verdict", ids(judge(f(MARK + 1, alive=None))), [])
    edge("K2 window (`started_at`)", f, MARK, MARK + 1)
    # K3 launched without an outcome row of the same dispatch after it - and older than the quiet window (t-1022 M-2). The
    # mark sits 90 h back so that the launches below are old enough; the age is pinned on its own further down.
    mark3 = NOW - 90 * H
    judge3 = lambda f: CS.judge(f, mark3, NOW, 24)  # noqa: E731
    launched = {"kind": "launched", "call": "role", "dispatch_id": "S5-x-1", "started_at": mark3 + 5}
    ended = {"kind": "role", "dispatch": "S5-x-1", "exit_code": 0, "is_error": False, "ts": mark3 + 9}
    check_eq("K3: a launch nobody ended", ids(judge3(facts(driver_runs=[launched]))), ["K3"])
    check_eq("K3: ended later by the same dispatch", ids(judge3(facts(driver_runs=[launched, ended]))), [])
    check_eq("K3: an outcome BEFORE the launch does not end it", ids(judge3(facts(driver_runs=[ended, launched]))), ["K3"])
    check_eq("K3: the outcome of ANOTHER dispatch does not end it",
             ids(judge3(facts(driver_runs=[launched, dict(ended, dispatch="S5-x-2")]))), ["K3"])
    check_eq("K3: a conductor call is matched by its kind",
             ids(judge3(facts(driver_runs=[{"kind": "launched", "call": "conductor", "dispatch_id": "", "started_at": mark3 + 5},
                                           {"kind": "conductor", "dispatch": "", "exit_code": 0, "ts": mark3 + 6}]))), [])
    check_eq("K3: live in_flight of the dispatch - the race launched->in_flight is not a stall",
             ids(judge3(facts(driver_runs=[launched],
                              in_flight=[{"dispatch": "S5-x-1", "started_at": mark3, "alive": True, "reused": False}]))), [])
    check_eq("K3: a running dispatch with liveness `alive` is live",
             ids(judge3(facts(driver_runs=[launched], dispatches=[disp("S5-x-1", "running", liveness="alive")]))), [])
    check_eq("K3: liveness `unknown` is not proof of life",
             ids(judge3(facts(driver_runs=[launched], dispatches=[disp("S5-x-1", "running", liveness="unknown")]))), ["K3"])
    g = lambda t: facts(driver_runs=[dict(launched, started_at=t)])  # noqa: E731
    check_eq("K3 window (`started_at`): AT the mark is not counted", ids(judge3(g(mark3))), [])
    check_eq("K3 window (`started_at`): one second BEYOND the mark is counted", ids(judge3(g(mark3 + 1))), ["K3"])
    check_eq("K3: `ts` serves when `started_at` is absent",
             ids(judge3(facts(driver_runs=[{"kind": "launched", "call": "role", "dispatch_id": "d", "ts": mark3 + 3}]))), ["K3"])
    # M-2: a call running RIGHT NOW is not a stall. A conductor call has a `launched` row and never an `in_flight` entry
    # (story_run.py: `launch(..., dispatch=dispatch if kind == "role" else "")`), a role's entry appears seconds later.
    old_mark = NOW - 200 * H
    age = lambda a, **kw: CS.judge(facts(driver_runs=[dict(launched, started_at=NOW - a, **kw)]), old_mark, NOW, 24)  # noqa: E731
    check_eq("K3 age: a launch one second old with no end row is a call running now, not a stall", ids(age(1)), [])
    check_eq("K3 age: ... and it is named in `ignored`, not dropped", len(age(1)["ignored"]), 1)
    check_eq("K3 age: a launch an hour old (a long conductor call) is still not a stall", ids(age(H)), [])
    check_eq("K3 age: a launch AT the quiet window (24 h exactly) is not a stall", ids(age(QUIET)), [])
    check_eq("K3 age: a launch one second BEYOND the quiet window is K3", ids(age(QUIET + 1)), ["K3"])
    check_eq("K3 age: a launch stamped in the future (clock skew) is not older than anything", ids(age(-H)), [])
    check_eq("K3 age: a conductor call running now (a first one ended, the second has no end row)",
             ids(CS.judge(facts(driver_runs=[
                 {"kind": "launched", "call": "conductor", "dispatch_id": "", "started_at": NOW - 600},
                 {"kind": "conductor", "dispatch": "", "exit_code": 0, "is_error": False, "ts": NOW - 590},
                 {"kind": "launched", "call": "conductor", "dispatch_id": "", "started_at": NOW - 5}]), old_mark, NOW, 24)), [])
    check_eq("K3 age: quiet_hours 0 (named, not refused): a launch one second old is K3", ids(CS.judge(
        facts(driver_runs=[dict(launched, started_at=NOW - 1)]), old_mark, NOW, 0)), ["K3"])
    check_eq("K3 age: an old launch with a LATER outcome row of the same dispatch is no stall",
             ids(CS.judge(facts(driver_runs=[dict(launched, started_at=NOW - 3 * QUIET), dict(ended, ts=NOW - 2 * QUIET)]),
                          old_mark, NOW, 24)), [])
    check_eq("K3 age: an old launch with a live in_flight entry is no stall",
             ids(CS.judge(facts(driver_runs=[dict(launched, started_at=NOW - 3 * QUIET)],
                                in_flight=[{"dispatch": "S5-x-1", "started_at": NOW - 3 * QUIET, "alive": True, "reused": False}]),
                          old_mark, NOW, 24)), [])
    # K4 the LAST outcome of a dispatch is an error (m1)
    def row(ident, ts, **kw):
        return dict({"kind": "role", "dispatch": ident, "ts": ts, "exit_code": 0, "is_error": False, "infra": None}, **kw)
    for label, bad in (("is_error", {"is_error": True}), ("exit_code 1", {"exit_code": 1}), ("infra", {"infra": "transient"})):
        check_eq(f"K4: the last outcome is an error ({label})", ids(judge(facts(driver_runs=[row("d1", MARK + 1, **bad)]))), ["K4"])
    check_eq("K4: an ok outcome is no stall", ids(judge(facts(driver_runs=[row("d1", MARK + 1)]))), [])
    check_eq("K4 (m1): an error and then an ok outcome of the SAME dispatch - a retry that held - does not fire",
             ids(judge(facts(driver_runs=[row("d1", MARK + 1, is_error=True, exit_code=1), row("d1", MARK + 2)]))), [])
    check_eq("K4: ok and then an error of the same dispatch fires",
             ids(judge(facts(driver_runs=[row("d1", MARK + 1), row("d1", MARK + 2, is_error=True)]))), ["K4"])
    check_eq("K4: an ok outcome of ANOTHER dispatch clears nothing",
             ids(judge(facts(driver_runs=[row("d1", MARK + 1, is_error=True), row("d2", MARK + 2)]))), ["K4"])
    check_eq("K4: a row with no outcome fields is not an outcome",
             ids(judge(facts(driver_runs=[{"kind": "role", "dispatch": "d1", "ts": MARK + 1}]))), [])
    edge("K4 window (`ts`)", lambda t: facts(driver_runs=[row("d1", t, is_error=True)]), MARK, MARK + 1)
    # K5 the conductor gave up
    f = lambda t, action="stop": facts(conductor=[{"ts": t, "action": action, "boundary": "S5"}])  # noqa: E731
    check_eq("K5: conductor.jsonl action stop", ids(judge(f(MARK + 1))), ["K5"])
    check_eq("K5: another action is no stall", ids(judge(f(MARK + 1, "ask_person"))), [])
    edge("K5 window (`ts`)", f, MARK, MARK + 1)
    # K7 a repair or a release in the event tail
    f = lambda t, kind="state_repair": facts(events=[{"type": kind, "created_at": t, "sequence": 7}])  # noqa: E731
    check_eq("K7: a state_repair event", ids(judge(f(MARK + 1))), ["K7"])
    check_eq("K7: a release event", ids(judge(f(MARK + 1, "release"))), ["K7"])
    check_eq("K7: another event type is no stall", ids(judge(f(MARK + 1, "dispatch"))), [])
    edge("K7 window (`created_at`)", f, MARK, MARK + 1)
    check_eq("mark None (never collected): every signal counts", ids(CS.judge(f(5), None, NOW)), ["K7"])


def k3_stop_record():
    """TR4-11: K3 and the person's stop record. Clearing a K3 is the unsafe side (a missing transcript), so every key that must STAY a
    stall is pinned beside the one that clears: expectations are the spec's (t-2222 item 11.1) and the plan critic's F-1, not what the code prints."""
    mark3 = NOW - 90 * H
    judge3 = lambda f: CS.judge(f, mark3, NOW, 24)  # noqa: E731
    began = mark3 + 5
    launched = {"kind": "launched", "call": "role", "dispatch_id": "S5-x-1", "started_at": began}
    call_id = f"S5-x-1@{began}"
    stop = {"kind": "stopped_by_person", "who": "person", "at": mark3 + 20, "since": mark3 + 1, "cut": [call_id]}
    runs = lambda *rows: facts(driver_runs=list(rows))  # noqa: E731
    v = judge3(runs(launched, stop))
    check("k3_cleared_by_stop_record_of_same_process: no signal, named in `ignored` with the stop time",
          ids(v) == [] and v["unreadable_reasons"] == []
          and any(i["why"] == f"stopped by the person at {mark3 + 20}" for i in v["ignored"]), str(v))
    check_eq("k3_kept_without_stop_record", ids(judge3(runs(launched))), ["K3"])
    check_eq("k3_kept_for_row_before_since: the row began before the stopping process (a dead earlier driver), even if `cut` names it",
             ids(judge3(runs(launched, dict(stop, since=began + 1)))), ["K3"])
    check_eq("k3 (since AT the row's start) clears", ids(judge3(runs(launched, dict(stop, since=began)))), [])
    check_eq("k3_kept_for_row_after_stop: the stop row stands BEFORE the launched row in the file",
             ids(judge3(runs(stop, launched))), ["K3"])
    for label, bad in (("since is a word", {"since": "yesterday"}), ("at is a word", {"at": "yesterday"}),
                       ("since is a list", {"since": [1]})):
        v = judge3(runs(launched, dict(stop, **bad)))
        check(f"k3_unreadable_stop_record_is_unreadable ({label}): the row stays K3 AND the story is unreadable",
              ids(v) == ["K3", "unreadable"] and any("not a time" in r for r in v["unreadable_reasons"]), str(v))
    check_eq("k3_stop_record_of_other_who_ignored: `who` other than person", ids(judge3(runs(launched, dict(stop, who="conductor")))), ["K3"])
    no_who = {k: v for k, v in stop.items() if k != "who"}
    check_eq("k3 a record with no `who` is not honoured", ids(judge3(runs(launched, no_who))), ["K3"])
    for key in ("since", "at"):
        v = judge3(runs(launched, {k: x for k, x in stop.items() if k != key}))
        check(f"k3 a record with no `{key}` is not honoured, silently", ids(v) == ["K3"] and v["unreadable_reasons"] == [], str(v))
    check_eq("k3 a record with no `cut` (an older writer) clears nothing",
             ids(judge3(runs(launched, {k: v for k, v in stop.items() if k != "cut"}))), ["K3"])
    check_eq("k3 a `cut` that is not a list clears nothing", ids(judge3(runs(launched, dict(stop, cut=call_id)))), ["K3"])
    check_eq("k3 an empty `cut` clears nothing", ids(judge3(runs(launched, dict(stop, cut=[])))), ["K3"])
    # two processes on one story: A (a dead one) launched the SAME dispatch at another second; B's record cuts only B's own row
    other = dict(launched, started_at=began + 3)
    v = judge3(runs(launched, other, dict(stop, cut=[f"S5-x-1@{began + 3}"], since=began)))
    check("k3_cut_names_exactly_its_rows: the row the record does not name stays K3 beside the one it does",
          ids(v) == ["K3"] and v["signals"][0]["at"] == began and len(v["ignored"]) == 1, str(v))
    check_eq("k3 a row launched AFTER the stop row stays K3 though its id is in `cut`", ids(judge3(runs(stop, launched))), ["K3"])
    check_eq("k3 a stop record with an ISO time is read like an epoch",
             ids(judge3(runs(launched, dict(stop, at=iso(mark3 + 20), since=iso(mark3 + 1))))), [])
    # a younger row (inside the quiet window) is named for the stop, not "may be running now"
    fresh = dict(launched, started_at=NOW - 5)
    v = CS.judge(runs(fresh, dict(stop, cut=[f"S5-x-1@{NOW - 5}"], since=NOW - 9, at=NOW - 2)), NOW - 100 * H, NOW, 24)
    check("k3 a cut row inside the quiet window is named for the stop", ids(v) == [] and "stopped by the person" in v["ignored"][0]["why"], str(v))
    # a conductor call: the id is `<call>@<started_at>` when there is no dispatch id
    cond = {"kind": "launched", "call": "conductor", "dispatch_id": "", "started_at": began}
    check_eq("k3 a conductor call is cut by `conductor@<started_at>`",
             ids(judge3(runs(cond, dict(stop, cut=[f"conductor@{began}"])))), [])


def k6_dispatch_status():
    # abandoned / never_started: the dispatch's start (the `dispatch` event's created_at) is the window
    for status in ("abandoned", "never_started"):
        f = lambda t, s=status: facts(dispatches=[disp("d1", s, started_at=t)])  # noqa: E731
        check_eq(f"K6: {status}", ids(judge(f(MARK + 1))), ["K6"])
        edge(f"K6 {status} window (`started_at`)", f, MARK, MARK + 1)
    v = judge(facts(dispatches=[disp("d1", "abandoned")]))
    check("K6: a snapshot with NO time (controller.json status only) is never a signal, and is named",
          ids(v) == [] and len(v["ignored"]) == 1, str(v))
    # returned_unaccepted: the role just returned (F-1 a)
    returned = lambda age: facts(dispatches=[disp("d1", "returned_unaccepted", returned_at=NOW - age)])  # noqa: E731
    mark_long_ago = NOW - 90 * H
    judged = lambda age, q=24: CS.judge(returned(age), mark_long_ago, NOW, q)  # noqa: E731
    check_eq("the role just returned (an hour ago): no stall", ids(judged(H)), [])
    check_eq("the role returned AT the quiet window (24 h exactly): no stall - strictly older is a stall", ids(judged(QUIET)), [])
    check_eq("the role returned one second BEYOND the quiet window: K6", ids(judged(QUIET + 1)), ["K6"])
    check_eq("quiet_hours 0 (named, not refused): a returned role one second old is a stall", ids(judged(1, 0)), ["K6"])
    check_eq("quiet_hours 0: a role that returned this very second is still not older than now", ids(judged(0, 0)), [])
    check_eq("a returned_at in the future (clock skew) is not older than anything", ids(judged(-H)), [])
    check_eq("K6 returned_unaccepted older than quiet but AT the mark: not counted",
             ids(CS.judge(returned(2 * QUIET), NOW - 2 * QUIET, NOW)), [])
    check_eq("K6 returned_unaccepted one second after the mark and old: counted",
             ids(CS.judge(returned(2 * QUIET), NOW - 2 * QUIET - 1, NOW)), ["K6"])
    v = judge(facts(dispatches=[disp("d1", "returned_unaccepted")]))
    check("a returned_unaccepted with no returned_at is never a signal, and is named", ids(v) == [] and len(v["ignored"]) == 1, str(v))
    # not signals: the controller's own planned / discounted statuses and `running`
    for status in ("stale", "blocked", "incomplete", "paused", "released_by_person", "superseded", "accepted"):
        check_eq(f"F-1: status {status} is no signal even with a fresh start", ids(judge(
            facts(dispatches=[disp("d1", status, started_at=MARK + 1, returned_at=MARK - QUIET)]))), [])
    for liveness in ("unknown", "abandoned", "never_started", "returned", None):
        check_eq(f"F-1 d: `running` + liveness {liveness} is no K6 signal (the business of `current`)", ids(judge(
            facts(dispatches=[disp("d1", "running", started_at=MARK + 1, liveness=liveness)]))), [])


def statuses_come_from_controller():
    stands = CS.episode_statuses()
    check_eq("the statuses that are an episode as they stand (Lead L-2 F-1)", stands, {"abandoned", "never_started"})
    check("none of the controller's STOPPED / stale / released / superseded statuses is one",
          not (stands & {"blocked", "paused", "incomplete", "stale", "released_by_person", "superseded", "returned_unaccepted"}))
    # the twin tied by a test: the module follows `controller` at call time, it holds no table of its own
    saved = (controller.SETTLED, controller.DISCOUNTED)
    try:
        controller.SETTLED = saved[0] | {"settled_by_a_future_controller"}
        check("a status added to controller.SETTLED is an episode with no edit here",
              "settled_by_a_future_controller" in CS.episode_statuses())
        v = judge(facts(dispatches=[disp("d1", "settled_by_a_future_controller", started_at=MARK + 1)]))
        check_eq("... and it fires K6", ids(v), ["K6"])
        controller.SETTLED = saved[0] | {"stale"}
        check("a status the controller also DISCOUNTS is never an episode, whatever else lists it", "stale" not in CS.episode_statuses())
        controller.SETTLED = saved[0]
        controller.DISCOUNTED = saved[1] | {"abandoned"}
        check("... and the same for a status the controller starts to discount", "abandoned" not in CS.episode_statuses())
    finally:
        controller.SETTLED, controller.DISCOUNTED = saved
    check_eq("the sets are back as the controller defines them", CS.episode_statuses(), {"abandoned", "never_started"})
    check_eq("the returned status is the controller's own constant", controller.RETURNED, "returned_unaccepted")


def running_now_and_current():
    old = NOW - 2 * QUIET
    f = lambda **kw: facts(closed=False, last_activity=old, **kw)  # noqa: E731
    v = judge(f(dispatches=[disp("d1", "running", liveness="alive")]))
    check("running now: a live dispatch with an old stamp is not stalled", not v["stalled"] and not v["current"] and v["running_now"], str(v))
    v = judge(f(dispatches=[disp("d1", "running", liveness="unknown")]))
    check("running + liveness unknown + a stamp older than the quiet window IS current (the one door `unknown` has)",
          v["current"] and v["stalled"] and not v["running_now"] and ids(v) == [], str(v))
    v = judge(f(in_flight=[{"dispatch": "d1", "started_at": MARK, "alive": True, "reused": False}]))
    check("running now: a driver process alive and not taken over is a live dispatch", not v["current"] and v["running_now"], str(v))
    v = judge(f(in_flight=[{"dispatch": "d1", "started_at": MARK + 1, "alive": True, "reused": True}]))
    check("a pid taken over by another process is not life: current, and K2", v["current"] and ids(v) == ["K2"], str(v))
    v = judge(f())
    check("an open story, nothing live, an old stamp: current and stalled", v["current"] and v["stalled"], str(v))
    v = judge(facts(closed=True, last_activity=old))
    check("a CLOSED story with an old stamp is not current", not v["current"] and not v["stalled"], str(v))
    check_eq("fresh activity (an hour old) is not current", judge(open_story())["current"], False)
    check_eq("last activity AT the quiet window (24 h): not current", judge(facts(closed=False, last_activity=NOW - QUIET))["current"], False)
    check_eq("last activity one second BEYOND the quiet window: current",
             judge(facts(closed=False, last_activity=NOW - QUIET - 1))["current"], True)
    # last_activity None -> the newest event -> the dispatch start -> unreadable (F-1 e)
    ev = [{"type": "dispatch", "created_at": NOW - 3 * H}, {"type": "accept", "created_at": NOW - 2 * H}]
    check_eq("last_activity None: the newest events.jsonl created_at serves (recent: not current)",
             judge(facts(closed=False, last_activity=None, events=ev))["current"], False)
    check_eq("... and an old one makes it current",
             judge(facts(closed=False, last_activity=None, events=[{"type": "dispatch", "created_at": old}]))["current"], True)
    check_eq("no events: the dispatch's started_at serves",
             judge(facts(closed=False, last_activity=None, dispatches=[disp("d1", "accepted", started_at=NOW - H)]))["current"], False)
    check_eq("... old, it is current",
             judge(facts(closed=False, last_activity=None, dispatches=[disp("d1", "accepted", started_at=old)]))["current"], True)


def waiting_for_a_person():
    old = NOW - 3 * QUIET
    gate = "gate A was opened after S3 and never answered"
    v = judge(facts(closed=False, last_activity=old, open_items=[gate, "the story never reached S9 done - it was parked, not finished"]))
    check("waiting for a person: an unanswered gate item is a record, not a stall - no transcripts",
          v["record"] == "waiting for a person" and not v["stalled"] and not v["current"] and v["waiting_for_person"], str(v))
    v = judge(facts(closed=False, last_activity=old, open_items=[gate], interrupted=[{"key": "d1", "at": MARK + 1}],
                    conductor=[{"ts": MARK + 1, "action": "stop"}], events=[{"type": "release", "created_at": MARK + 2}]))
    check("waiting for a person overrides ONLY `current`: K1, K5 and K7 still make it stalled (t-1022 M-1), the record stays",
          v["stalled"] and not v["current"] and ids(v) == ["K1", "K5", "K7"] and v["record"] == "waiting for a person", str(v))
    # the conductor `stop` always opens driver-question.md (story_run.py): the person walked away - transcripts must come
    v = judge(facts(closed=False, last_activity=old, driver_question_open=True, conductor=[{"ts": MARK + 5, "action": "stop"}]))
    check("K5 + an open driver-question.md: stalled, with a record - the case D-0052 exists for",
          v["stalled"] and ids(v) == ["K5"] and v["record"] == "waiting for a person" and v["waiting_for_person"], str(v))
    got = CS.select_transcripts(v, [{"sid": "s", "transcript": "/c/s.jsonl", "exists": True}], ["/c/s/subagents/a.jsonl"])
    check_eq("... and the packer's choice yields the transcripts for it", (got["main"], got["subagents"]),
             (["/c/s.jsonl"], ["/c/s/subagents/a.jsonl"]))
    v = judge(facts(closed=False, last_activity=old, driver_question_open=True))
    check("waiting for a person: an open driver-question.md ALONE is not a stall (no signal, not current)",
          not v["stalled"] and not v["current"] and v["record"] == "waiting for a person", str(v))
    v = judge(facts(closed=False, last_activity=old, driver_question_open=True,
                    unreadable=["driver-state.json is there and cannot be read as a JSON object"]))
    check("waiting + an unreadable carrier: `unreadable` is listed and the story is NOT fine",
          v["stalled"] and ids(v) == ["unreadable"] and v["unreadable_reasons"], str(v))
    v = judge(facts(closed=False, last_activity=old, open_items=["S5 left running", "unresolved halt: stand is down"]))
    check("other open items are not a person's turn: the story is current and stalled", v["current"] and v["stalled"] and v["record"] is None, str(v))
    # the sentence is archive_task's own: tied to the real function, so a rewording there fails here
    pipeline = {"stages": {"S1": {"status": "done"}, "S2": {"status": "done"}, "S3": {"status": "done"}}}
    items = archive_task.open_items(pipeline)
    check("archive_task.open_items on a story parked at gate A holds the sentence this rule reads",
          any("gate A" in i for i in items) and CS.judge(facts(closed=False, last_activity=old, open_items=items), None, NOW)["waiting_for_person"],
          str(items))
    answered = dict(pipeline, gates={"A": {"decision": "approved"}})
    check("... and with gate A answered the same story is not waiting",
          not CS.judge(facts(closed=False, last_activity=old, open_items=archive_task.open_items(answered)), None, NOW)["waiting_for_person"])


def unreadable_cases():
    v = judge(facts(closed=False))
    check("a story with NO dispatch record, no events and no stamp: unreadable (the safe side)",
          v["stalled"] and ids(v) == ["unreadable"] and v["unreadable_reasons"], str(v))
    v = judge(facts(closed=True))
    check("... but a CLOSED story with nothing to read needs no activity time: not unreadable, not stalled", not v["stalled"] and ids(v) == [], str(v))
    v = CS.judge(open_story(events=[{"type": "state_repair", "created_at": NOW - H}]), NOW + 1, NOW)
    check("a mark in the future: unreadable with the reason, no signal drawn",
          v["stalled"] and ids(v) == ["unreadable"] and "future" in v["unreadable_reasons"][0], str(v))
    check_eq("a mark exactly AT now is a legal window", ids(CS.judge(open_story(), NOW, NOW)), [])
    for bad in ("not a time", True, "", [1]):
        v = CS.judge(open_story(), bad, NOW)
        check(f"a mark that is not a time {bad!r}: unreadable", v["stalled"] and ids(v) == ["unreadable"], str(v))
    for bad in (-1, True, "24", float("nan"), None):
        v = CS.judge(open_story(), MARK, NOW, bad)
        check(f"stall_quiet_hours {bad!r}: unreadable, never a silent default", v["stalled"] and ids(v) == ["unreadable"], str(v))
    # CL1-4 F3 (t-1067): the packer takes its default for a bad stall_quiet_hours by THIS predicate (one validator, not a second one);
    # the rule above stays strict, so the line between "usable" and "not" is pinned here, on both sides.
    check_eq("F3 the predicate the packer relies on: not a number / bool / negative / NaN / infinity / None -> None",
             [CS._quiet_seconds(x) for x in ("24", True, -1, [1], {"h": 1}, float("nan"), float("inf"), None)], [None] * 8)
    check_eq("F3 ... and a finite number >= 0 (0 and a fraction included) -> seconds", [CS._quiet_seconds(x) for x in (0, 24, 5.5)], [0.0, 24 * 3600.0, 5.5 * 3600.0])
    v = CS.judge(open_story(), MARK, None)
    check("now that is not a time: unreadable", v["stalled"] and ids(v) == ["unreadable"], str(v))
    v = judge(open_story(unreadable=["driver-state.json is there and cannot be read as a JSON object"],
                         events=[{"type": "state_repair", "created_at": MARK + 1}]))
    check("a carrier named unreadable: the readable part counts (K7) AND the unreadable signal stands, stalled",
          ids(v) == ["K7", "unreadable"] and v["stalled"], str(v))
    check_eq("None for facts is an empty story, not a crash", ids(CS.judge(None, MARK, NOW)), ["unreadable"])


def foreign_shapes():
    """M-3 (pure half) and m-2: another project's carriers hold valid JSON in shapes the rule does not know. FR-41/FR-59: such a
    field is NAMED (one reason, `unreadable`), the rest of the story is still judged, and nothing raises."""
    k7 = [{"type": "state_repair", "created_at": MARK + 1, "sequence": 3}]
    # magnitude: a time that is a huge integer (legal JSON) used to raise OverflowError inside `_epoch`
    v = judge(open_story(events=k7, interrupted=[{"key": "S5-x-1", "at": 10 ** 400}]))
    check("M-3 magnitude: a huge integer as a time is one named reason, K7 is still judged",
          ids(v) == ["K7", "unreadable"] and len(v["unreadable_reasons"]) == 1 and "interrupted S5-x-1" in v["unreadable_reasons"][0]
          and len(v["unreadable_reasons"][0]) < 200, str(v)[:400])
    for label, kw in (("now", dict(now=10 ** 400)), ("the mark", dict(mark=10 ** 400))):
        v = judge(open_story(), **kw)
        check(f"M-3 magnitude: {label} a huge integer is unreadable with a short reason, never a raise",
              v["stalled"] and ids(v) == ["unreadable"] and len(v["unreadable_reasons"][0]) < 200, str(v)[:300])
    for bad in (float("nan"), float("inf"), "99999-01-01", [1], {"a": 1}):
        v = judge(open_story(events=k7, interrupted=[{"key": "k", "at": bad}]))
        check(f"a time that is there and is not a time ({bad!r}): named, never a signal", ids(v) == ["K7", "unreadable"], str(v)[:300])
    # a status that is a list (unhashable in a set lookup) used to raise TypeError inside `judge`
    v = judge(open_story(events=k7, dispatches=[disp("d1", ["abandoned"], started_at=MARK + 1)]))
    check("M-3 nesting: a list as a dispatch status is one named reason, K7 is still judged",
          ids(v) == ["K7", "unreadable"] and len(v["unreadable_reasons"]) == 1 and "d1" in v["unreadable_reasons"][0]
          and "status" in v["unreadable_reasons"][0], str(v)[:300])
    check_eq("a record with NO status at all is not a field in a wrong shape", ids(judge(open_story(dispatches=[disp("d1", None)]))), [])
    # a fact in a shape the reader would never hand over: no raise
    v = judge(open_story(open_items=5, unreadable=7, events={"a": 1}, driver_runs="x", interrupted=3))
    check("facts with a list expected and another type given: an empty story, no crash", ids(v) == [] and not v["stalled"], str(v)[:300])
    # m-2: ONE time parser. The wrapper differs from `dispatch_liveness._epoch` only where that one returns a non-finite
    # number or raises.
    import dispatch_liveness as DL
    for value in ("2026-10-19T10:00:00Z", "2026-10-19T10:00:00", 1_800_000_000, "2026-10-19T10:00:00+03:00", 12.5):
        check_eq(f"_epoch ({value!r}) is dispatch_liveness._epoch", CS._epoch(value), DL._epoch(value))
    for value in (True, "", "  ", None, "not a time"):
        check_eq(f"_epoch ({value!r}) is None in both", (CS._epoch(value), DL._epoch(value)), (None, None))
    check_eq("where DL returns a non-finite number, the wrapper says `not a time`",
             (CS._epoch(float("nan")), CS._epoch(float("inf"))), (None, None))
    try:
        DL._epoch(10 ** 400)
        raised = False
    except OverflowError:
        raised = True
    check("where DL raises (a huge integer), the wrapper says `not a time`", raised and CS._epoch(10 ** 400) is None)


def purity():
    f = open_story(events=[{"type": "release", "created_at": MARK + 1}], driver_runs=[{"kind": "launched", "call": "r", "ts": MARK + 1}],
                   dispatches=[disp("d1", "running", liveness="alive")], open_items=["x"])
    before = copy.deepcopy(f)
    # every door a read goes through: the builtin, `io.open` (pathlib's), `Path.open` (read_text / read_bytes / write_*
    # call it), and `os.open` (m-6: patching `builtins.open` alone let a `Path.read_text` inside `judge` pass)
    doors = [(builtins, "open"), (io, "open"), (os, "open"), (Path, "open")]
    real = [getattr(owner, name) for owner, name in doors]

    def no_open(*a, **k):
        raise AssertionError("the rule opened a file")
    for owner, name in doors:
        setattr(owner, name, no_open)
    probes = {"builtins.open": lambda: builtins.open("x"), "io.open": lambda: io.open("x"),
              "os.open": lambda: os.open("x", 0), "Path.read_text": lambda: Path("x").read_text()}
    trapped = []
    try:
        v = judge(f)
        for label, probe in probes.items():
            try:
                probe()
            except AssertionError:
                trapped.append(label)
            except Exception:
                pass
    finally:
        for (owner, name), original in zip(doors, real):
            setattr(owner, name, original)
    check("PURE: the rule runs with open(), io.open(), os.open() and Path.open() forbidden", v is not None)
    check_eq("PURE: the trap is live - a read through each of the four doors reaches it", trapped, list(probes))
    check_eq("PURE: the facts are unchanged after the verdict", f, before)
    check_eq("PURE: the same facts give the same verdict", judge(f), judge(copy.deepcopy(f)))


def transcripts_h(tmp):
    """F-2: the host-wide subagent list is cut to the story's own session folders."""
    own = tmp / "proj" / "cc" / "aaaa-own"
    sub = lambda stem, name: tmp / "proj" / "cc" / stem / "subagents" / name  # noqa: E731
    paths = [sub("aaaa-own", "agent-1.jsonl"), sub("aaaa-own", "agent-2.jsonl"), sub("bbbb-other", "agent-9.jsonl")]
    sessions = [{"sid": "aaaa-own", "transcript": str(own) + ".jsonl", "exists": True}]
    stalled = {"stalled": True, "record": None}
    got = CS.select_transcripts(stalled, sessions, paths)
    check_eq("another story's subagent is excluded by stem", got["subagents"], [str(paths[0]), str(paths[1])])
    check_eq("the main transcript of the story's session is kept", got["main"], [str(own) + ".jsonl"])
    got = CS.select_transcripts(stalled, [{"sid": "s", "transcript": str(own) + ".jsonl", "exists": False}], paths)
    check("a missing main file is a gap named by its sid, and its subagents (found by stem) still come",
          got["main"] == [] and got["gaps"] == [{"sid": "s", "why": "the transcript file is not on disk"}] and len(got["subagents"]) == 2, str(got))
    got = CS.select_transcripts(stalled, [{"sid": "s", "transcript": None, "exists": False, "why": "no cost file for this session"}], paths)
    check("a session with no transcript recorded keeps no subagent at all", got["subagents"] == [] and got["gaps"][0]["sid"] == "s", str(got))
    for empty in ([], None):
        got = CS.select_transcripts(stalled, empty, paths)
        check(f"an empty transcripts list ({empty!r}) is `no transcripts`, never a crash", got["main"] == [] and got["subagents"] == []
              and got["why"].startswith("no transcripts"), str(got))
    check("no host-wide list at all (None) is no crash", CS.select_transcripts(stalled, sessions, None)["subagents"] == [])
    got = CS.select_transcripts({"stalled": False, "record": "waiting for a person"}, sessions, paths)
    check("a story waiting for a person gets no transcripts, and the reason says so",
          got["main"] == [] and got["subagents"] == [] and got["why"] == "waiting for a person", str(got))
    got = CS.select_transcripts({"stalled": False, "record": None}, sessions, paths)
    check("a story that is not stalled and has no `looped` key (not looped) gets none",
          got["subagents"] == [] and got["why"] == "the story neither stalled nor looped", str(got))     # CL3-9 B-5: the why text changed
    twice = [dict(sessions[0]), dict(sessions[0], sid="again")]
    check_eq("two sessions pointing at one transcript give it once", CS.select_transcripts(stalled, twice, paths)["main"], [str(own) + ".jsonl"])
    check_eq("a verdict that is not a dict gives nothing", CS.select_transcripts(None, sessions, paths)["subagents"], [])


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def write_lines(path, rows, tail=""):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(("\n".join(rows) + "\n" + tail).encode("utf-8"))


def reader_on_a_scratch_project(tmp):
    project = tmp / "proj2"
    task = project / "qa-factory" / "artifacts" / "QA-7"
    state = task / "state"
    claude = tmp / "cc"
    # sess-own: named by the driver's journal; sess-inter: an interactive session whose cost file names the ticket (by_task);
    # sess-foreign: another story's session - it is neither
    for sid, task_key in (("sess-own", "(no task)"), ("sess-inter", "QA-7"), ("sess-foreign", "QA-OTHER")):
        transcript = claude / f"{sid}.jsonl"
        transcript.parent.mkdir(parents=True, exist_ok=True)
        transcript.write_text("{}\n", encoding="utf-8")
        write_json(project / "qa-factory" / "state" / "cost" / f"{sid}.json",
                   {"transcript": str(transcript), "by_task": {task_key: {}}})
        (claude / sid / "subagents").mkdir(parents=True, exist_ok=True)
        (claude / sid / "subagents" / f"agent-{sid}.jsonl").write_text("{}\n", encoding="utf-8")
    write_json(project / "qa-factory" / "config.json", {})
    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait()
    write_json(task / "pipeline.json", {"stages": {"S1": {"status": "done", "finished": iso(NOW - 80 * H)}}})
    write_json(state / "driver-state.json", {"sessions": {"S5-x-1": "sess-own"},
                                             "in_flight": {"S5-x-1": {"dispatch_id": "S5-x-1", "pid": dead.pid, "started_at": iso(NOW - 2 * H)}},
                                             "interrupted": {}})
    write_json(state / "controller.json", {"dispatches": {"S5-x-1": {"id": "S5-x-1", "status": "running"},
                                                          "S5-x-0": {"id": "S5-x-0", "status": "abandoned"}}})
    write_lines(state / "events.jsonl",
                [json.dumps({"sequence": 1, "type": "dispatch", "created_at": NOW - 5 * H, "payload": {"id": "S5-x-0"}}),
                 json.dumps({"sequence": 2, "type": "dispatch", "created_at": NOW - 2 * H, "payload": {"id": "S5-x-1"}}),
                 "{ this line is broken",
                 json.dumps({"sequence": 3, "type": "state_repair", "created_at": NOW - H, "payload": {}})],
                tail='{"sequence": 4, "type": "rele')            # a write in progress: no newline, does not parse
    write_lines(state / "driver-runs.jsonl", [json.dumps({"kind": "role", "dispatch": "S5-x-1", "session_id": "sess-own",
                                                         "exit_code": 0, "is_error": False, "ts": iso(NOW - 3 * H)}),
                                              json.dumps({"kind": "role", "dispatch": "S5-x-2", "session_id": "sess-gone",
                                                         "exit_code": 0, "is_error": False, "ts": iso(NOW - 3 * H)})])
    facts_ = CS.read_facts(project, task, NOW)
    check("reader: closed is read from the pipeline (S8/gate B not done: open)", facts_["closed"] is False)
    check_eq("reader: the sentence of a broken line is named with its number, once - the unfinished last line is left alone",
             [r for r in facts_["unreadable"] if "events.jsonl" in r], ["events.jsonl line 3 is not a JSON object"])
    check_eq("reader: the readable events count", [e["type"] for e in facts_["events"]], ["dispatch", "dispatch", "state_repair"])
    check_eq("reader: the dead driver pid is read as not alive", [e["alive"] for e in facts_["in_flight"]], [False])
    running = [d for d in facts_["dispatches"] if d["id"] == "S5-x-1"][0]
    check_eq("reader: a dispatch's start is the `dispatch` event's created_at", running["started_at"], NOW - 2 * H)
    check_eq("reader: a running dispatch whose process is gone has no proof of life (liveness is not `alive`)", running["liveness"] != "alive", True)
    v = CS.stall(project, task, NOW - 3 * H, NOW)
    check("stall(): K2 (dead pid, 2 h ago), K6 abandoned (5 h ago is BEFORE the mark: not counted), K7 (1 h ago), unreadable (broken line)",
          ids(v) == ["K2", "K7", "unreadable"], str(v["signals"]))
    v = CS.stall(project, task, NOW - H, NOW)
    check_eq("stall(): a later mark drops what happened before it; the broken line still stands", ids(v), ["unreadable"])
    # the broken line is the only fault: delete it and the verdict loses `unreadable`
    write_lines(state / "events.jsonl", [json.dumps({"sequence": 1, "type": "dispatch", "created_at": NOW - 2 * H, "payload": {"id": "S5-x-1"}})])
    v = CS.stall(project, task, NOW - 3 * H, NOW)
    check_eq("stall(): with the broken line gone, `unreadable` is gone", ids(v), ["K2"])
    # H on the same tree: hooklib's host-wide list, cut to the story's own session
    got = CS.transcripts_for(project, task, v)
    check_eq("transcripts_for: the subagents of the story's own sessions (the driver's and the ticket's by_task), not sess-foreign's",
             sorted(Path(p).name for p in got["subagents"]), ["agent-sess-inter.jsonl", "agent-sess-own.jsonl"])
    check_eq("transcripts_for: the main transcripts of those sessions", sorted(Path(p).name for p in got["main"]),
             ["sess-inter.jsonl", "sess-own.jsonl"])
    check_eq("transcripts_for: a session the journal names that has no cost file is a gap named by its sid",
             [g["sid"] for g in got["gaps"]], ["sess-gone"])
    # an unreadable controller.json is named, not a crash
    (state / "controller.json").write_text("[1, 2]", encoding="utf-8")
    check("a controller.json that is not an object is named as unreadable",
          any("controller.json" in r for r in CS.read_facts(project, task, NOW)["unreadable"]))
    empty = tmp / "proj3" / "qa-factory" / "artifacts" / "QA-8"
    empty.mkdir(parents=True)
    v = CS.stall(tmp / "proj3", empty, None, NOW)
    check("a story folder with nothing in it: unreadable, no crash", v["stalled"] and ids(v) == ["unreadable"], str(v))


def scratch_story(tmp, name, files, costs=()):
    """A project with one story `QA-9`. `files`: {relative path under the story: object (JSON) | list of lines | bytes}.
    `costs`: session ids that get a cost file naming the ticket in `by_task` and an existing transcript."""
    project = tmp / name
    task = project / "qa-factory" / "artifacts" / "QA-9"
    write_json(project / "qa-factory" / "config.json", {})
    for rel, content in files.items():
        path = task / rel
        if isinstance(content, bytes):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        elif isinstance(content, list):
            write_lines(path, content)
        else:
            write_json(path, content)
    for sid in costs:
        transcript = tmp / f"{name}-cc" / f"{sid}.jsonl"
        transcript.parent.mkdir(parents=True, exist_ok=True)
        transcript.write_text("{}\n", encoding="utf-8")
        write_json(project / "qa-factory" / "state" / "cost" / f"{sid}.json", {"transcript": str(transcript), "by_task": {"QA-9": {}}})
    return project, task


def reader_shapes(tmp):
    """M-3 (reader half), m-1, M-4: valid JSON in an unexpected shape through the real reader, on a scratch project."""
    mark = NOW - 3 * H
    repair = json.dumps({"sequence": 3, "type": "state_repair", "created_at": NOW - H, "payload": {}})
    done = {"stages": {"S1": {"status": "done", "finished": iso(NOW - 80 * H)}}}
    base = {"pipeline.json": done, "state/events.jsonl": [repair]}

    count = []

    def case(label, needle, **override):
        files = dict(base, **override)
        count.append(label)
        project, task = scratch_story(tmp, f"shape-{len(count)}", files)
        v = CS.stall(project, task, mark, NOW)
        check(f"M-3 {label}: one reason naming the field, K7 still judged, no raise",
              ids(v) == ["K7", "unreadable"] and len(v["unreadable_reasons"]) == 1 and needle in v["unreadable_reasons"][0],
              str(v["unreadable_reasons"]) + str(ids(v)))
    case("list-for-dict: controller.json dispatches is a list", "controller.json dispatches", **{"state/controller.json": {"dispatches": ["d"]}})
    case("list-for-dict: a dispatch event payload is a list", "payload",
         **{"state/events.jsonl": [json.dumps({"sequence": 1, "type": "dispatch", "created_at": NOW - 2 * H, "payload": ["x"]}), repair]})
    case("list-for-dict: driver-state in_flight is a list", "in_flight", **{"state/driver-state.json": {"in_flight": ["x"]}})
    case("string-for-dict: pipeline stage S1 is a string", "open items", **{"pipeline.json": {"stages": {"S1": "done"}}})
    case("magnitude: a huge integer as a time", "interrupted k",
         **{"state/driver-state.json": {"interrupted": {"k": {"at": 10 ** 400}}}})
    case("nesting: a list as a dispatch status", "status", **{"state/controller.json": {"dispatches": {"d1": {"status": ["x"]}}}})
    deep = "[" * 100_000 + "]" * 100_000
    case("nesting: a driver-state nested beyond the parser", "driver-state.json", **{"state/driver-state.json": deep.encode()})
    case("nesting: an events line nested beyond the parser", "events.jsonl line 1", **{"state/events.jsonl": [deep, repair]})
    # m-1: a BOM is the encoding, not a broken first line
    bom = b"\xef\xbb\xbf" + (repair + "\n").encode("utf-8")
    project, task = scratch_story(tmp, "bom", dict(base, **{"state/events.jsonl": bom}))
    v = CS.stall(project, task, mark, NOW)
    check("m-1: a BOM on events.jsonl is no fault - K7 from its first line, no `unreadable`", ids(v) == ["K7"] and not v["unreadable_reasons"], str(v)[:300])
    # M-4: an unreadable carrier of the sessions is a named gap in H, never "none recorded"
    stalled = {"stalled": True, "record": None}
    project, task = scratch_story(tmp, "m4a", dict(base, **{"state/driver-state.json": b"{broken"}))
    got = CS.transcripts_for(project, task, stalled)
    check("M-4: an unreadable driver-state.json and no cost file: H says unreadable, not `no session is recorded`",
          "unreadable" in got["why"] and "no session" not in got["why"] and got["main"] == []
          and len(got["gaps"]) == 1 and got["gaps"][0]["sid"] is None and "driver-state.json" in got["gaps"][0]["why"], str(got))
    project, task = scratch_story(tmp, "m4b", dict(base, **{"state/driver-state.json": b"{broken"}), costs=("sess-cost",))
    got = CS.transcripts_for(project, task, stalled)
    check_eq("M-4: an unreadable driver-state.json with a readable cost file: the session comes from the cost file",
             [Path(p).name for p in got["main"]], ["sess-cost.jsonl"])
    check("... and the reason is listed as a gap with no sid", [g["sid"] for g in got["gaps"]] == [None]
          and "driver-state.json" in got["gaps"][0]["why"] and got["why"] == "the story is stalled", str(got))
    project, task = scratch_story(tmp, "m4c", dict(base, **{"state/driver-state.json": {"sessions": {"S5-x-1": "sess-cost"}}}), costs=("sess-cost",))
    got = CS.transcripts_for(project, task, stalled)
    check("M-4: a readable story is unchanged - the session, no gap", [Path(p).name for p in got["main"]] == ["sess-cost.jsonl"] and got["gaps"] == [], str(got))
    project, task = scratch_story(tmp, "m4d", base)
    got = CS.transcripts_for(project, task, stalled)
    check("M-4: nothing unreadable and no session: `no session of this story is recorded` is still the answer",
          got["why"] == "no transcripts: no session of this story is recorded" and got["gaps"] == [], str(got))


# --- CL3-9: the loop rule. Expectations come from spec t-625 section 2 / 3 and the plan critic's amendments, never from output ---
TABLE = CS.load_loops()


def lj(f, mark=MARK, table=TABLE):
    return CS.judge(f, mark, NOW, 24, table)


def lids(v):
    return sorted(s["id"] for s in v["loop_signals"])


def ledge(name, make, expect_id):
    """AT the mark not counted, one second BEYOND counted (AR-15), for one loop id."""
    check(f"{name}: AT the mark is not counted", lids(lj(make(MARK))) == [], str(lj(make(MARK))["loop_signals"]))
    check_eq(f"{name}: one second BEYOND is counted", lids(lj(make(MARK + 1))), [expect_id])


def dsf(**state):
    return facts(driver_state=state, driver_state_present=True)


def loop_table():
    check("L-T0a the shipped table loads", isinstance(TABLE, dict) and TABLE["schema"] == 1)
    good = json.loads(CS.LOOPS_FILE.read_text(encoding="utf-8"))

    def broken(label, needle, edit):
        bad = copy.deepcopy(good)
        edit(bad)
        path = Path(tmp_loops) / f"{len(label)}-{abs(hash(label))}.json"
        path.write_text(json.dumps(bad), encoding="utf-8")
        try:
            CS.load_loops(path)
            check(f"L-T0b {label}: refused", False, "no error")
        except ValueError as exc:
            check(f"L-T0b {label}: refused, naming {needle}", needle in str(exc), str(exc))
    broken("schema 2", "schema", lambda d: d.update(schema=2))
    broken("max_normal 0", "max_normal", lambda d: d["repeat_dispatch"].update(max_normal=0))
    broken("max_normal true", "max_normal", lambda d: d["repeat_dispatch"].update(max_normal=True))
    broken("unknown shape", "shape", lambda d: d["records"][0].update(shape="blob"))
    broken("values and min", "no min", lambda d: d["records"][0].update(min=1))
    by_shape = lambda d, shape: next(r for r in d["records"] if r["shape"] == shape)   # noqa: E731

    def swap(row, give, take_):
        row[give] = row.pop(take_) if take_ in row else 1
    broken("a records row with min instead of values", "needs values and no min",
           lambda d: swap(by_shape(d, "records"), "min", "values"))
    broken("a nested_records row with values instead of min", "needs min and no values",
           lambda d: swap(by_shape(d, "nested_records"), "values", "min"))
    broken("a rows row on a state carrier", "carrier", lambda d: d["records"][1].update(carrier="driver-state.json"))
    broken("a records row without key", "key", lambda d: d["records"][2].pop("key"))
    try:
        CS.load_loops(Path(tmp_loops) / "absent.json")
        check("L-T0b an absent table is refused", False)
    except ValueError:
        check("L-T0b an absent table is refused", True)
    # L-T1: the table-to-driver join (AR-22): every key / kind / inner / field / value word of the shipped table is a literal the driver
    # writes (ONE text read of story_run.py: no importable object carries these words); the L4 values are the driver's OWED_TOKENS
    # (imported) or `debt`, and `route` (code's own owe_route, no person) is not one
    import story_run as SR  # noqa: E402
    src = (harness.SCRIPTS / "story_run.py").read_text(encoding="utf-8")
    owed = set(SR.Driver.OWED_TOKENS)
    missing = []
    for row in good["records"]:
        for word in [row.get("key"), row.get("kind"), row.get("inner"), row["field"], *row.get("values", [])]:
            if word and f'"{word}"' not in src:
                missing.append(f"{row['id']}:{word}")
        if row["id"] == "L4":
            missing += [f"L4 {row['key']}:{v} (not an owed token)" for v in row["values"] if v not in owed and v != "debt"]
            if "route" in row["values"]:
                missing.append(f"L4 {row['key']}:route")
    check("L-T1 every word of collect-loops.json is a literal the driver writes, L4 values within OWED_TOKENS", not missing,
          "missing: " + ", ".join(missing))
    # L-T1b: the pass-key form is tied to the real builder
    for kind in ("round", "mechanical"):
        check(f"L-T1b PASS_KEY matches repair_pass_key({kind})",
              CS.PASS_KEY.match(controller.repair_pass_key("S5", "qa-automator", 3, "S5:qa-automator:abc", kind=kind)))
    check("L-T1b a key with no hash does not match", not CS.PASS_KEY.match("round pass 1 for qa-automator on S5"))


def l_signals():
    S9 = lambda i, t: {"id": f"S9-d-{i}", "status": "returned", "started_at": t, "role": "qa-delivery", "key": "S9:qa-delivery:h"}  # noqa: E731
    # L1 and its limits (E2, E3); S9 is not a repair-loop role: limit 2
    two = facts(dispatches=[S9(1, MARK + 1), S9(2, MARK + 2)])
    check_eq("L-T3a L1: two dispatches of a role are AT the limit - not a loop (E2)", lids(lj(two)), [])
    three = facts(dispatches=[S9(1, MARK + 1), S9(2, MARK + 2), S9(3, MARK + 3)])
    v = lj(three)
    check_eq("L-T3a L1: a third dispatch is beyond the limit (E3)", lids(v), ["L1"])
    check_eq("L-T3a L1: the signal is at the newest start beyond the limit", v["loop_signals"][0]["at"], MARK + 3)
    seven = facts(dispatches=[S9(i, MARK + i) for i in range(1, 8)])
    check_eq("L-T3a L1: seven S9 dispatches are ONE signal", lids(lj(seven)), ["L1"])
    ledge("L1 window (newest start beyond the limit)", lambda t: facts(dispatches=[S9(1, MARK - 9), S9(2, MARK - 8), S9(3, t)]), "L1")
    rep = lambda n: facts(dispatches=[{"id": f"s5-{i}", "status": "returned", "started_at": MARK + i, "role": "qa-automator",   # noqa: E731
                                       "key": "S5:qa-automator:h"} for i in range(1, n + 1)])
    check_eq("L-T3a L1: a repair-loop role has five normal dispatches", lids(lj(rep(5))), [])
    check_eq("L-T3a L1: a sixth is a loop", lids(lj(rep(6))), ["L1"])
    check_eq("L-T3g one dispatch per stage S0..S9 is no loop signal",
             lids(lj(facts(dispatches=[{"id": f"d{i}", "status": "returned", "started_at": MARK + i, "role": f"r{i}", "key": f"S{i}:r{i}:h"}
                                       for i in range(10)]))), [])
    # L2
    row = lambda outcome, t: dsf(window_rounds={"S5|c1": [{"at": t, "dispatch": "d", "set": ["x"], "outcome": outcome}]})  # noqa: E731
    check_eq("L-T3b L2 `cap`", lids(lj(row("cap", MARK + 1))), ["L2"])
    check_eq("L-T3b L2 `same_set`", lids(lj(row("same_set", MARK + 1))), ["L2"])
    ledge("L2 window (`at`)", lambda t: row("cap", t), "L2")
    check_eq("L-T3b L2: two `to_conductor` rounds (cap reached, not exceeded) are no loop (E4)",
             lids(lj(dsf(window_rounds={"S5|c1": [{"at": MARK + 1, "outcome": "to_conductor"}, {"at": MARK + 2, "outcome": "to_conductor"}]}))), [])
    v = lj(dsf(window_rounds={"S5|c1": [{"outcome": "cap"}]}))
    check("L-T3b L2: a row with no time is never a signal and is named (E10)", lids(v) == [] and len(v["loop_ignored"]) == 1, str(v))
    # L3: the driver journal
    gate = lambda stop, t: facts(driver_runs=[{"kind": "gate_repair", "gate": "B", "stop": stop, "ts": t}], driver_state_present=True)  # noqa: E731
    check_eq("L-T3c L3 `stop: cap`", lids(lj(gate("cap", MARK + 1))), ["L3"])
    check_eq("L-T3c L3 `stop: same_set`", lids(lj(gate("same_set", MARK + 1))), ["L3"])
    ledge("L3 window (`ts`)", lambda t: gate("cap", t), "L3")
    for stop in ("", "failed", "no_move"):
        check_eq(f"L-T3c L3 `stop: {stop!r}` is no loop", lids(lj(gate(stop, MARK + 1))), [])
    # L4
    tok = lambda key, token, t: dsf(**{key: {"S5|c1": {"token": token, "at": t}}})  # noqa: E731
    check_eq("L-T3d L4 token `round`", lids(lj(tok("repair_limit", "round", MARK + 1))), ["L4"])
    check_eq("L-T3d L4 `repair_limit_s7` token `debt`", lids(lj(tok("repair_limit_s7", "debt", MARK + 1))), ["L4"])
    ledge("L4 window (`at`)", lambda t: tok("repair_limit", "round", t), "L4")
    check_eq("L-T3d L4 token `route` is no loop (E7)", lids(lj(tok("repair_limit", "route", MARK + 1))), [])
    # L5
    key = controller.repair_pass_key("S5", "qa-automator", 2, "S5:qa-automator:h")
    ov = lambda match, t, **kw: facts(stage_overrides=[dict({"stage": "S5", "match": match, "decision": "d", "at": t}, **kw)], driver_state_present=True)  # noqa: E731
    check_eq("L-T3e L5 a repair pass key", lids(lj(ov(key, MARK + 1))), ["L5"])
    ledge("L5 window (`at`)", lambda t: ov(key, t), "L5")
    check_eq("L-T3e L5 a REVOKED pass still counts (E8)", lids(lj(ov(key, MARK + 1, revoked_at=MARK + 2))), ["L5"])
    check_eq("L-T3e L5 an S1 source override is no loop", lids(lj(ov("source material unavailable", MARK + 1, stage="S1"))), [])
    check_eq("L-T3e L5 the old stage-wide word `repair round` is no loop", lids(lj(ov("repair round", MARK + 1))), [])
    joined = facts(stage_overrides=[{"stage": "S9", "match": "block one", "at": MARK + 1}], driver_state_present=True,
                   driver_state={"exit_limit": {"S9-d": {"passes": [{"stage": "S9", "block": "block one"}]}}})
    check_eq("L-T3e L5 an exit-pass block named in exit_limit joins its override", lids(lj(joined)), ["L5"])
    check_eq("L-T3e L5 the same override with no exit pass is no loop", lids(lj(dict(joined, driver_state={}))), [])
    # L6
    ex = lambda granted, t: dsf(exit_limit={"S9-d": {"rounds": {"k": {"granted": granted, "at": t}}}})  # noqa: E731
    check_eq("L-T3f L6 granted 1", lids(lj(ex(1, MARK + 1))), ["L6"])
    ledge("L6 window (inner `at`)", lambda t: ex(1, t), "L6")
    check_eq("L-T3f L6 granted 0 is no loop", lids(lj(ex(0, MARK + 1))), [])
    check_eq("L-T3f L6 granted true is no loop (a bool is not an int)", lids(lj(ex(True, MARK + 1))), [])
    # L7 (B-6): the durable carrier - the window's record was overwritten, the question journal still shows it
    q = lambda kind, t: facts(driver_state={"repair_limit": {"S5|c1": {"token": "route", "at": MARK + 5}}}, driver_state_present=True,   # noqa: E731
                              driver_questions=[{"ts": t, "kind": kind, "stage": "S5", "dispatch": "d"}])
    check_eq("B-6 carrier: a closed window whose record was overwritten (`route`) is still seen via driver-questions.jsonl",
             lids(lj(q("repair_limit", MARK + 1))), ["L7"])
    check_eq("B-6 carrier: an exit_limit question", lids(lj(q("exit_limit", MARK + 1))), ["L7"])
    ledge("L7 window (`ts`)", lambda t: q("repair_limit", t), "L7")
    check_eq("B-6 carrier: any other question kind is no loop", lids(lj(q("s1_gap", MARK + 1))), [])
    # E11 / E13 / E14 / E15 / E16
    v = lj(dsf(window_rounds={"S5|c1": [{"at": "yesterday", "outcome": "cap"}]}))
    check("E11 a loop time that is not a time: no signal, a reason, looped None", lids(v) == [] and v["looped"] is None and v["loop_unreadable_reasons"], str(v))
    check_eq("E13 no mark: every loop counts", lids(lj(row("cap", 5), mark=None)), ["L2"])
    check_eq("L-T9 a bad mark: looped None", lj(row("cap", 5), mark="soon")["looped"], None)
    check_eq("L-T7 driver-state absent and the driver journal has rows: looped None (E16)",
             lj(facts(driver_state_present=False, driver_runs=[{"kind": "role", "ts": MARK - 1}]))["looped"], None)
    v = lj(facts(driver_state_present=False, driver_runs=[]))
    check("L-T7 driver-state absent and no driver rows (skill road): looped False, no reason (E15)", v["looped"] is False and not v["loop_unreadable_reasons"], str(v))
    # B-3/B-5/M5: unknowns, shapes
    v = lj(dsf(window_rounds=[]))
    check("L-T6 `window_rounds: []` on a clean closed story: stalled False, unreadable_reasons [], looped None, reason named",
          v["stalled"] is False and v["unreadable_reasons"] == [] and v["looped"] is None and "window_rounds" in v["loop_unreadable_reasons"][0], str(v))
    check_eq("L-T6 a clean story with the table: looped False", lj(dsf())["looped"], False)
    check_eq("no table given: looped None", CS.judge(dsf(), MARK, NOW, 24)["looped"], None)
    check_eq("L-T6 a stall-side unreadable (file-level) makes the loop state unknown", lj(facts(unreadable=["x"]))["looped"], None)
    v = lj(dsf(exit_limit={"d": {"rounds": []}}))
    check("E18 `exit_limit.d.rounds: []`: a loop reason, the other kinds still read", v["looped"] is None and "rounds" in v["loop_unreadable_reasons"][0], str(v))
    # B-3: a record that is not in its shape is a reason (looped None), never "no loop"
    for label, state, needle in (("records", {"repair_limit": {"S5|a": "x"}}, "S5|a is not a JSON dict (str)"),
                                 ("nested_records, outer", {"exit_limit": {"S9-d": 7}}, "S9-d is not a JSON dict (int)"),
                                 ("nested_records, inner", {"exit_limit": {"S9-d": {"rounds": {"k": "y"}}}}, "k is not a JSON dict (str)"),
                                 ("series", {"window_rounds": {"S5|c1": "z"}}, "S5|c1 is not a JSON list (str)")):
        v = lj(dsf(**state))
        check(f"B-3 {label}: looped None and the reason names the record", v["looped"] is None and any(needle in r for r in v["loop_unreadable_reasons"]), str(v))
        check_eq(f"B-3 {label}: the stall half is untouched", v["unreadable_reasons"], [])


def i0_and_gate():
    # L-T5 (I-0): the stall half is byte-identical with and without the loop table, whatever the facts
    fixtures = [facts(), open_story(), facts(interrupted=[{"key": "k", "at": MARK + 1}]), facts(unreadable=["x"]),
                open_story(driver_runs=[{"kind": "launched", "call": "r", "ts": MARK + 1}]), dsf(window_rounds=[]),
                facts(driver_state_present=False, driver_runs=[{"kind": "role"}]), facts(events=[{"type": "release", "created_at": MARK + 1}])]
    keys = ("stalled", "current", "running_now", "waiting_for_person", "record", "signals", "unreadable_reasons", "ignored")
    for i, f in enumerate(fixtures):
        a, b = judge(f), lj(f)
        check(f"L-T5 fixture {i}: the stall keys are equal with and without the loop table", all(a[k] == b[k] for k in keys), str((a, b)))
    # L-T8: the gate
    sessions = [{"sid": "s", "transcript": "/x/s.jsonl", "exists": True}]
    got = CS.select_transcripts({"stalled": True, "looped": False, "record": None}, sessions, [])
    check("L-T8 stalled and not looped: packed", got["main"] and got["why"] == "the story is stalled", str(got))
    got = CS.select_transcripts({"stalled": False, "looped": True}, sessions, [])
    check("L-T8 looped only: packed, why `the story looped`", got["main"] and got["why"] == "the story looped", str(got))
    got = CS.select_transcripts({"stalled": True, "looped": True}, sessions, [])
    check_eq("L-T8 both", got["why"], "the story is stalled and looped")
    got = CS.select_transcripts({"stalled": False, "looped": None}, sessions, [])
    check("L-T8 looped unknown: packed", got["main"] and got["why"] == "whether the story looped is not known", str(got))
    got = CS.select_transcripts({"stalled": False, "looped": False}, sessions, [])
    check("L-T8 neither: nothing", got["main"] == [] and got["why"] == "the story neither stalled nor looped", str(got))
    check("B-5 a verdict WITHOUT the key `looped` is not looped", not CS.wants_transcripts({"stalled": False}))
    # purity of the loop half
    f = dsf(window_rounds={"S5|c": [{"at": MARK + 1, "outcome": "cap"}]}, dispatches=[], stage_overrides=[])
    before = copy.deepcopy(f)
    real = builtins.open
    builtins.open = lambda *a, **k: (_ for _ in ()).throw(AssertionError("the rule opened a file"))
    try:
        v = lj(f)
    finally:
        builtins.open = real
    check("PURE: the loop half opens no file and leaves the facts unchanged", f == before and lids(v) == ["L2"])


def l_reader_and_dispatch_keys(tmp):
    # L-T2: the grouping key, adversarial inputs, through the real reader
    ds = lambda i, stage, role, scope: {"id": f"d{i}", "stage": stage, "role": role, "scope": scope, "status": "returned"}  # noqa: E731
    disps = {f"d{i}": ds(i, "S4", "qa-case-designer", sc) for i, sc in enumerate([["A"], ["A", "B"], ["C"]])}
    disps.update({"e1": ds(10, "S5", "qa-automator", ["B", "A"]), "e2": ds(11, "S5", "qa-automator", ["A", "B"]),
                  "f1": {"id": "f1", "status": "returned"}, "g1": ds(20, "S5", "qa-automator", None), "g2": ds(21, "S5", "qa-automator", []),
                  "g3": {"id": "g3", "stage": "S5", "role": "qa-automator", "status": "returned"},
                  "h1": ds(30, "S9", "qa-delivery", ["A", "B"]), "h2": ds(31, "S9", "qa-delivery", ["A", "B"]),
                  "h3": ds(32, "S9", "qa-delivery", ["B", "A", "A"])})
    project, task = scratch_story(tmp, "keys", {"pipeline.json": {"stages": {"S1": {"status": "done", "finished": iso(NOW - 80 * H)}}},
                                               "state/controller.json": {"dispatches": disps}})
    f = CS.read_facts(project, task, NOW)
    key = {d["id"]: d["key"] for d in f["dispatches"]}
    check_eq("L-T2 the S4 designer with three different case lists is ONE key", {key["d0"], key["d1"], key["d2"]}, {"S4:qa-case-designer"})
    check_eq("L-T2 the same scope in another order is one key", key["e1"], key["e2"])
    check_eq("L-T2 (B-2) a scope with a DUPLICATE entry is the key of the sorted-unique scope, for every order",
             key["h3"] == key["h1"] == key["h2"], True)
    check_eq("L-T2 (B-2) the de-duped key equals ledger_key of the sorted-unique scope",
             key["h3"], controller.ledger_key(dict(disps["h3"], scope=["A", "B"])))
    three = [{"id": i, "status": "returned", "started_at": MARK + n, "role": "qa-delivery", "key": key[i]} for n, i in enumerate(("h1", "h2", "h3"), 1)]
    v = lj(facts(dispatches=three))
    check("L-T2 (B-2) three dispatches of one window, one with scope [B,A,A], are ONE series beyond the limit: looped, L1",
          v["looped"] is True and lids(v) == ["L1"], str(v))
    check_eq("L-T2 a scope that is null, [] or absent is one key", {key["g1"], key["g2"], key["g3"]}, {key["g1"]})
    check("L-T2 a record with no stage and role does not raise and has a key", key["f1"] is not None and f["loop_unreadable"] == [], str(f["loop_unreadable"]))
    check_eq("L-T2 the stall list is untouched by the loop reading", f["unreadable"], [])
    # L-T4: reader: a wrong-shape key is read by the rule, never as a stall reason; the question journal is read
    project, task = scratch_story(tmp, "l4", {"pipeline.json": {"stages": {"S1": {"status": "done", "finished": iso(NOW - 80 * H)}}},
                                             "state/driver-state.json": {"window_rounds": []},
                                             "state/driver-questions.jsonl": [json.dumps({"ts": iso(NOW - H), "kind": "repair_limit", "stage": "S5", "dispatch": "d"}),
                                                                              "{broken"]})
    f = CS.read_facts(project, task, NOW)
    check("L-T4 a broken line of driver-questions.jsonl is a LOOP reason only", f["unreadable"] == [] and any("driver-questions.jsonl" in r for r in f["loop_unreadable"]), str(f))
    check_eq("L-T4 the raw driver-state object and its presence are carried", (f["driver_state"], f["driver_state_present"]), ({"window_rounds": []}, True))
    v = CS.stall(project, task, NOW - 3 * H, NOW)
    check("L-T4 stall(): the question row is L7, the wrong shape is a reason, the stall half is clean",
          lids(v) == ["L7"] and v["unreadable_reasons"] == [] and v["looped"] is True, str(v))


def main():
    tmp = temp_dir("collect-stall-")
    global tmp_loops
    tmp_loops = tmp
    try:
        loop_table()
        l_signals()
        i0_and_gate()
        l_reader_and_dispatch_keys(tmp)
        k_signals()
        k3_stop_record()
        k6_dispatch_status()
        statuses_come_from_controller()
        running_now_and_current()
        waiting_for_a_person()
        unreadable_cases()
        foreign_shapes()
        purity()
        transcripts_h(tmp)
        reader_on_a_scratch_project(tmp)
        reader_shapes(tmp)
    finally:
        cleanup(tmp)
    finish("test_collect_stall")


if __name__ == "__main__":
    os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
    main()
