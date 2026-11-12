#!/usr/bin/env python3
"""t-2181 PC-6 / t-2277 J-4, J-C8, J-C10: the story held for code, in the controller (FAST).

One state, two causes (`s5_absent_side` from S6, `first_look_stop` from S3). This file calls `Controller._next_action_for_state`
statically and `projection` / `Controller.validate` / `Controller.build_rework_request` on synthetic events and states - no
controller loop, no store on disk beyond an empty temp folder (N3). The names of the checks are the node's test list.
"""
import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import check, check_eq, check_in, check_not_in, cleanup, finish, temp_dir  # noqa: E402

sys.path.insert(0, str(harness.SCRIPTS))
import contract as CON  # noqa: E402
import controller as CT  # noqa: E402
from event_store import StateConflict  # noqa: E402

HEX = "a" * 64
HEADS = '{"backend": "abc123"}'
ABSENT = {"sides": {"backend": {"reality": "absent", "deliverable": True}}}
WORDS = "go on as it is, the feature works as I expected"


def ev(n, kind, payload):
    return {"sequence": n, "type": kind, "payload": payload, "created_at": 1000.0 + n}


def story(done=range(6), events=(), dispatches=None, approved=True):
    """A controller state: the stages `done` completed, gate A approved, the given events folded in, `dispatches` added."""
    state = CT.projection([ev(1, "initialize", {"scope": ["TC-1"], "source_revision": "r1", "known_paths": {"task_root": "x"}})]
                          + [ev(2 + i, kind, payload) for i, (kind, payload) in enumerate(events)])
    for i in done:
        state["stages"][f"S{i}"] = {"status": "completed"}
    if approved:
        state["decisions"]["gA"] = {"id": "gA", "gate": "A", "status": "approved", "source_revision": state.get("source_revision")}
    state["dispatches"].update(dispatches or {})
    return state


def never_started(stage, role="qa-runner", number=2, rework=True):
    ident = f"{stage}-{role}-{number}"
    return ident, {"id": ident, "stage": stage, "role": role, "input_hash": "h", "status": "never_started",
                   "rework_of": f"{stage}-{role}-1" if rework else None, "reason": "never reached an agent"}


def accepted(stage, role, number=1):
    ident = f"{stage}-{role}-{number}"
    return ident, {"id": ident, "stage": stage, "role": role, "input_hash": "h", "status": "accepted", "scope": ["TC-1"],
                   "budget": {}, "known_paths": {"task_root": "x"}}


def nxt(state, pipeline=None):
    return CT.Controller._next_action_for_state(state, {} if pipeline is None else pipeline)


def refused(call, *args, **kw):
    """(class name, message) of the refusal `call` raises, or ("", "") when it does not refuse."""
    try:
        call(*args, **kw)
    except (ValueError, StateConflict) as exc:
        return type(exc).__name__, str(exc)
    return "", ""


def controller_with(state, root):
    ctl = CT.Controller(root)
    ctl.state = lambda: copy.deepcopy(state)
    return ctl


def hold_events(cause=None, held_from=None, **more):
    payload = {"since": "2026-11-01T10:00:00+00:00", "packet": {"n": 1}, "s5_dispatch": "S5-qa-code-critic-1"}
    if cause:
        payload.update(cause=cause, held_from=held_from)
    return [("await", dict(payload, **more))]


def due_and_hold() -> None:
    sub = {"sides": {"backend": {"reality": "substituted", "deliverable": True}}}
    off = {"sides": {"backend": {"reality": "absent", "deliverable": False}}}
    action = nxt(story(), ABSENT)
    check_eq("enters await_implementation on an absent deliverable side after S5", action["action"], "await_implementation")
    check_eq("... with the default cause and stage", (action["cause"], action["held_from"]), ("s5_absent_side", "S6"))
    check_eq("a deliverable SUBSTITUTED side goes on to S6", (nxt(story(), sub)["action"], nxt(story(), sub).get("stage")), ("prepare_stage", "S6"))
    check_eq("an absent side that is not this story's deliverable goes on to S6", nxt(story(), off)["action"], "prepare_stage")
    check_eq("no pipeline (E-W2): not due, S6 is prepared", CT.Controller._next_action_for_state(story(), None)["action"], "prepare_stage")
    check_eq("S5 not done: the due check is not reached, S5 is prepared", nxt(story(done=range(5)), ABSENT)["stage"], "S5")
    held = story(events=hold_events())
    got = nxt(held, ABSENT)
    check_eq("an awaiting story answers awaiting_implementation with the record", (got["action"], got["since"], got["packet"]),
             ("awaiting_implementation", "2026-11-01T10:00:00+00:00", {"n": 1}))
    check_eq("the record holds with NO pipeline argument (E-W2)", CT.Controller._next_action_for_state(held, None)["action"], "awaiting_implementation")
    check_in("the answer names its doors", "stop_waiting", got["reason"])
    check_in("... and the arrival", "--side <side>=real", got["reason"])


def arrive_clears() -> None:
    state = story(events=hold_events() + [("arrive", {})])
    check("arrive clears the record", "awaiting" not in state, str(state.get("awaiting")))
    check_eq("and the story goes on to S6 (the side is real now)", nxt(state)["action"], "prepare_stage")
    check_eq("contract.awaiting reads none", CON.awaiting({"awaiting": state.get("awaiting")})["state"], "none")


def stop_waiting_is_terminal() -> None:
    ident, never = never_started("S2", "qa-test-strategist")
    state = story(events=hold_events() + [("stop_waiting", {"words": "stop it", "at": "2026-11-02T09:00:00+00:00"})], dispatches={ident: never})
    got = nxt(state, ABSENT)
    check_eq("a stopped story answers awaiting_stopped with the words and the time", (got["action"], got["words"], got["at"]),
             ("awaiting_stopped", "stop it", "2026-11-02T09:00:00+00:00"))
    check_eq("terminal: a never-started dispatch below the hold is NOT relaunched either", got["action"], "awaiting_stopped")
    check_eq("contract.awaiting reads stopped", CON.awaiting({"awaiting": state["awaiting"]})["state"], "stopped")
    check_in("the answer names both doors", "arrive", got["reason"])
    check_in("... and the rework with words", "S0-S5", got["reason"])


def never_started_is_not_relaunched() -> None:
    ident, never = never_started("S6")
    state = story(events=hold_events(), dispatches={ident: never})
    state["stages"]["S6"] = {"status": "completed"}
    got = nxt(state, ABSENT)
    check_eq("never_started_s6_rework_is_not_relaunched_while_awaiting", got["action"], "awaiting_implementation")
    check_eq("... it is listed in `held`", [h["dispatch_id"] for h in got["held"]], [ident])
    low_id, low = never_started("S2", "qa-test-strategist")
    state = story(events=hold_events(), dispatches={ident: never, low_id: low})
    state["stages"]["S6"] = {"status": "completed"}
    got = nxt(state, ABSENT)
    check_eq("a never-started rework BELOW the hold runs (it is relaunched), the S6 one stays held",
             (got["action"], got.get("closed_dispatch_id")), ("relaunch", low_id))


def first_look_hold() -> None:
    fl = hold_events("first_look_stop", "S3")
    state = story(done=range(3), events=fl)
    got = nxt(state)
    check_eq("first_look_stop_holds_s3", (got["action"], got["cause"], got["held_from"]), ("awaiting_implementation", "first_look_stop", "S3"))
    check_in("a first-look hold names `first_look_continue`", "first_look_continue", got["reason"])
    check_eq("first_look_stop_record_has_null_s5_dispatch", state["awaiting"]["s5_dispatch"], None)
    check_eq("... a caller's s5_dispatch is never kept for this cause", state["awaiting"]["s5_dispatch"] is None, True)
    sides = {"backend": {"reality": "real"}}
    state = story(done=range(3), events=hold_events("first_look_stop", "S3", sides=sides))
    check_eq("the record's sides are the event's (the reader's, written by apply)", state["awaiting"]["sides"], sides)
    # a story with the hold from S3 does not dispatch S3 even where S3 has a never-started dispatch
    ident, never = never_started("S3", "qa-test-strategist")
    state = story(done=range(3), events=fl, dispatches={ident: never})
    got = nxt(state)
    check_eq("a never-started S3 dispatch is held, not relaunched", (got["action"], [h["dispatch_id"] for h in got["held"]]),
             ("awaiting_implementation", [ident]))
    # S2 rework runs inside the hold and the hold answers again at S3
    ident2, low = never_started("S2", "qa-test-strategist")
    state = story(done=range(3), events=fl, dispatches={ident2: low})
    check_eq("rework_s2_runs_inside_the_hold (a never-started S2 rework is relaunched)", nxt(state)["action"], "relaunch")
    running = story(done=range(3), events=fl, dispatches={"S2-qa-test-strategist-2": {"id": "S2-qa-test-strategist-2", "stage": "S2", "status": "running"}})
    check_eq("... and while it runs the controller waits for it", nxt(running)["action"], "wait_existing_job")
    ended = story(done=range(3), events=fl, dispatches={"S2-qa-test-strategist-2": {"id": "S2-qa-test-strategist-2", "stage": "S2", "status": "accepted"}})
    check_eq("rework_s2_end_holds_again", (nxt(ended)["action"], nxt(ended)["held_from"]), ("awaiting_implementation", "S3"))
    reopen = story(done=range(2), events=fl)      # S2 not done: the loop prepares it, then stops at S3
    check_eq("an open S2 is prepared by the loop (below the hold)", (nxt(reopen)["action"], nxt(reopen)["stage"]), ("prepare_stage", "S2"))


def hold_without_cause() -> None:
    state = story(events=[("await", {"since": "2026-11-01T10:00:00+00:00"})])
    hold = CON.awaiting({"awaiting": state["awaiting"]})
    check_eq("await_without_cause_reads_s5_absent_side", (hold["cause"], hold["held_from"]), ("s5_absent_side", "S6"))
    check("... the record stores no invented cause", "cause" not in state["awaiting"], str(state["awaiting"]))
    check_eq("... and holds from S6", nxt(state, ABSENT)["held_from"], "S6")
    old = CT.projection([ev(1, "initialize", {"scope": [], "source_revision": "r"}), ev(2, "await", {"packet": None})])
    check_eq("a record with no `since` takes the event's own time", old["awaiting"]["since"], "1970-01-01T00:16:42+00:00")


def rework_refusals(root) -> None:
    fl = hold_events("first_look_stop", "S3")
    s2, s3 = accepted("S2", "qa-test-strategist"), accepted("S3", "qa-test-strategist")
    held = story(done=range(3), events=fl, dispatches=dict([s2, s3]))
    ctl = controller_with(held, root)
    kind, text = refused(ctl.build_rework_request, "S3", "qa-test-strategist", [], "fix", cause="source_arrived")
    check_eq("rework_s3_refused_while_first_look_held", kind, "StateConflict")
    for needle in ("held for code (first_look_stop) from S3", "stop_waiting", "--words-file", "arrive"):
        check_in(f"... the refusal names `{needle}`", needle, text)
    kind, text = refused(ctl.build_rework_request, "S2", "qa-test-strategist", [], "fix", cause="source_arrived")
    check_not_in("rework_s2_allowed_while_first_look_held (no refusal by the hold)", "held for code", text)
    check_eq("... and no refusal at all", kind, "")
    request = ctl.build_rework_request("S2", "qa-test-strategist", [], "fix", cause="source_arrived")
    check("... the request does not reopen anything", "await_reopened" not in request, str(sorted(request)))
    absent = story(events=hold_events(), dispatches=dict([accepted("S6", "qa-runner"), accepted("S2", "qa-test-strategist")]))
    ctl = controller_with(absent, root)
    kind, text = refused(ctl.build_rework_request, "S6", "qa-runner", ["TC-1"], "fix")
    check_eq("rework_s6_refused_while_awaiting", kind, "StateConflict")
    for needle in ("held for code (s5_absent_side) from S6", "stop_waiting", "arrive", "S0-S5"):
        check_in(f"... the refusal names `{needle}`", needle, text)
    check_eq("a rework of S2 with words while awaiting runs (no refusal)", refused(ctl.build_rework_request, "S2", "qa-test-strategist", [], WORDS,
                                                                                      words_given=True)[0], "")
    # stopped: only a person's words reopen it
    stopped = story(done=range(3), events=fl + [("stop_waiting", {"words": "stop"})], dispatches=dict([s2, s3]))
    ctl = controller_with(stopped, root)
    kind, text = refused(ctl.build_rework_request, "S2", "qa-test-strategist", [], "typed by code")
    check_eq("`--reason` (not the person's words) on a stopped story is refused", kind, "StateConflict")
    check_in("... naming the words door", "--words-file", text)
    kind, text = refused(ctl.build_rework_request, "S3", "qa-test-strategist", [], WORDS, words_given=True)
    check_eq("even with words a stopped story's S3 rework (>= held_from) is refused", kind, "StateConflict")
    request = ctl.build_rework_request("S2", "qa-test-strategist", [], WORDS, words_given=True)
    check_eq("the person's words carry `await_reopened`", request.get("await_reopened"), {"words": WORDS})
    reopened = story(done=range(3), events=fl + [("stop_waiting", {"words": "stop"})])
    after = CT.projection([ev(1, "initialize", {"scope": ["TC-1"], "source_revision": "r1", "known_paths": {"task_root": "x"}}),
                           ev(2, "await", {"cause": "first_look_stop", "held_from": "S3"}), ev(3, "stop_waiting", {"words": "stop"}),
                           ev(4, "dispatch", dict(request, known_paths={"task_root": "x"}))])
    check_eq("rework_with_words_reopens_stopped: the dispatch event removes `stopped`", (CON.awaiting({"awaiting": after["awaiting"]})["state"],
                                                                                          "stopped" in after["awaiting"]), ("awaiting", False))
    check_eq("... the hold itself stands (cause and stage)", (after["awaiting"]["cause"], after["awaiting"]["held_from"]), ("first_look_stop", "S3"))
    check("(the reopened story is still stopped before the rework's event)", "stopped" in reopened["awaiting"])


def replay() -> None:
    events = [("await", {"cause": "first_look_stop", "held_from": "S3", "sides": {"a": {"reality": "absent"}}}),
              ("stop_waiting", {"words": "w"}), ("first_look_continued", {"source_head": HEADS, "register_hash": HEX, "words": "x"})]
    import json
    import time
    one = story(done=range(3), events=events)
    # a replay reads no clock and keeps nothing between runs: the same log, round-tripped through JSON and projected later
    # (the clock moved a day on), is the same state - the identity of the hold included (the `await` event's own number)
    real = time.time
    time.time = lambda: real() + 86400
    try:
        two = story(done=range(3), events=[tuple(e) for e in json.loads(json.dumps(events))])
    finally:
        time.time = real
    check_eq("replay of the event log gives the same state", one, two)
    check_eq("... and the same answer", nxt(one), nxt(two))
    check_eq("the hold carries its own identity: the event number of its `await`", one["awaiting"]["opened"], 2)


def vocabulary() -> None:
    for word in ("bind", "reference_walk", "first_look"):
        check(f"purpose `{word}` is accepted", word in CT.PURPOSES, str(sorted(CT.PURPOSES)))
    check_eq("source_arrived stands BEFORE ticket_changed, which stays last", CT.REPAIR_CAUSES[-2:], ("source_arrived", "ticket_changed"))
    check("source_arrived is the driver's word, not a reviewer's", "source_arrived" not in CT.REVIEWER_CAUSES)
    check_eq("an S5 record of purpose `bind` is a window (s5_part_of)", CT.s5_part_of({"stage": "S5", "request_binding": {"purpose": "bind"}}), "window")
    check_eq("an unknown cause reads as test_defect (the safe side)", CT.repair_cause({"repair_cause": "zzz"}), "test_defect")
    check_eq("the four operations are APPLY operations", [op in CT.APPLY_OPERATIONS for op in CT.HOLD_OPERATIONS], [True] * 4)
    check_eq("the person's `first_look_continue` is recorded as `first_look_continued`", CT.EVENT_KIND, {"first_look_continue": "first_look_continued"})
    flag_built = [op for op in CT.APPLY_OPERATIONS if op not in CT.INPUT_FILE_OPERATIONS]
    check_in("`stop_waiting` builds its request from flags (no --input)", "stop_waiting", flag_built)
    check_in("`first_look_continue` builds its request from flags (no --input)", "first_look_continue", flag_built)
    check_not_in("`await` takes --input", "await", flag_built)


def validate(root) -> None:
    ctl = CT.Controller(root)
    fl_hold = story(done=range(3), events=hold_events("first_look_stop", "S3"))
    absent_hold = story(events=hold_events())
    stopped = story(done=range(3), events=hold_events("first_look_stop", "S3") + [("stop_waiting", {"words": "x"})])
    none = story()
    good = {"words": WORDS, "source_head": HEADS, "register_hash": HEX}

    def go(op, payload, state):
        return refused(ctl.validate, op, payload, state)

    check_eq("first_look_continue_clears_first_look_stop_hold: the call is accepted on a first_look_stop hold", go("first_look_continue", good, fl_hold), ("", ""))
    cleared = story(done=range(3), events=hold_events("first_look_stop", "S3") + [("first_look_continued", dict(good, at="2026-11-03T10:00:00+00:00"))])
    check("... and the event clears `awaiting`", "awaiting" not in cleared, str(cleared.get("awaiting")))
    check_eq("... the story then goes on to S3", nxt(cleared)["stage"], "S3")
    kind, text = go("first_look_continue", good, absent_hold)
    check_eq("first_look_continue_refused_on_s5_absent_side", kind, "StateConflict")
    check_in("... the refusal names the arrival door", "arrive", text)
    check_in("... and the stop door", "stop_waiting", text)
    kept = story(events=hold_events() + [("first_look_continued", good)])
    check("... (if such an event ever stood it would not clear an s5_absent_side hold)", "awaiting" in kept)
    kind, text = go("first_look_continue", good, stopped)
    check_eq("first_look_continue is refused on a stopped story", kind, "StateConflict")
    check_in("... naming the rework with words", "S0-S2", text)
    check_eq("first_look_continue_without_hold_records_only: accepted", go("first_look_continue", good, none), ("", ""))
    recorded = story(events=[("first_look_continued", dict(good, at="2026-11-03T10:00:00+00:00"))])
    check_eq("... it records and holds nothing", ("awaiting" in recorded, recorded["first_look_continue"]["register_hash"]), (False, HEX))
    kind, text = go("first_look_continue", dict(good, words="  "), fl_hold)
    check_eq("first_look_continue_empty_words_refused", kind, "ValueError")
    check_in("... naming --words-file", "--words-file", text)
    check_eq("first_look_continue_stores_given_keys (as given, nothing parsed)", (recorded["first_look_continue"]["source_head"],
             recorded["first_look_continue"]["register_hash"], recorded["first_look_continue"]["words"], recorded["first_look_continue"]["at"]),
             (HEADS, HEX, WORDS, "2026-11-03T10:00:00+00:00"))
    odd = '  not json at all {  '
    odd_state = story(events=[("first_look_continued", dict(good, source_head=odd))])
    check_eq("... a heads text that is no JSON is still stored whole", odd_state["first_look_continue"]["source_head"], odd)
    check_eq("... and accepted by the validation", go("first_look_continue", dict(good, source_head=odd), none), ("", ""))
    for label, payload in (("missing", {k: v for k, v in good.items() if k != "source_head"}), ("empty", dict(good, source_head=""))):
        kind, text = go("first_look_continue", payload, fl_hold)
        check_eq(f"first_look_continue_without_keys_refused ({label} --source-head)", kind, "ValueError")
        check_in("... the door names the keys", "first_look.py show --json", text)
    kind, text = go("first_look_continue", {k: v for k, v in good.items() if k != "register_hash"}, fl_hold)
    check_eq("first_look_continue_without_keys_refused (missing --register-hash)", kind, "ValueError")
    for label, bad in (("short", "abc"), ("63 hex", "a" * 63), ("65 hex", "a" * 65), ("non-hex", "g" * 64), ("empty", "")):
        kind, text = go("first_look_continue", dict(good, register_hash=bad), fl_hold)
        check_eq(f"first_look_continue_bad_register_hash_refused ({label})", kind, "ValueError")
        check_in("... naming 64 hex", "64 hex", text)
    check_eq("an upper-case 64 hex is a hash too", go("first_look_continue", dict(good, register_hash="A" * 64), fl_hold), ("", ""))
    kind, text = go("first_look_continue", dict(good, words="", source_head="", register_hash="x"), absent_hold)
    check_in("every shape problem is told at once (K1)", "3 problems", text)

    # the three other operations
    check_eq("stop_waiting needs words", go("stop_waiting", {"words": ""}, absent_hold)[0], "ValueError")
    check_eq("stop_waiting is accepted on an awaiting story", go("stop_waiting", {"words": "stop"}, absent_hold), ("", ""))
    check_eq("stop_waiting on a story that waits for nothing is refused", go("stop_waiting", {"words": "stop"}, none)[0], "StateConflict")
    check_eq("stop_waiting twice is refused", go("stop_waiting", {"words": "stop"}, stopped)[0], "StateConflict")
    check_eq("arrive clears an awaiting story", go("arrive", {}, absent_hold), ("", ""))
    check_eq("arrive also lifts a stopped story (relaunching with the code)", go("arrive", {}, stopped), ("", ""))
    check_eq("arrive with nothing held is accepted: it only RECORDS the arrival road (F4)", go("arrive", {}, none), ("", ""))
    check_eq("... and the event holds nothing", "awaiting" in story(events=[("arrive", {})]), False)
    check_eq("await: the default record (no cause, no stage) is accepted", go("await", {"packet": None}, none), ("", ""))
    check_eq("await: both cause and stage are accepted", go("await", {"cause": "first_look_stop", "held_from": "S3"}, none), ("", ""))
    kind, text = go("await", {"cause": "first_look_stop"}, none)
    check_eq("await: a cause with no `held_from` is refused (it would read S6)", kind, "ValueError")
    check_eq("await: `held_from` that is no stage is refused", go("await", {"cause": "first_look_stop", "held_from": "stage 3"}, none)[0], "ValueError")
    check_eq("await: an empty cause is refused", go("await", {"cause": " ", "held_from": "S3"}, none)[0], "ValueError")
    kind, text = go("await", {"packet": None}, stopped)
    check_eq("await over a stopped story is refused (E-W1: two ways out only)", kind, "StateConflict")
    check_in("... naming the doors", "arrive", text)
    again = story(events=hold_events() + [("await", {"s5_dispatch": "S5-new", "since": "2026-11-05T00:00:00+00:00"})])
    check_eq("a new `await` replaces the record (the S5 dispatch it names)", (again["awaiting"]["s5_dispatch"], again["awaiting"]["since"]),
             ("S5-new", "2026-11-05T00:00:00+00:00"))


def pipeline_projection(root) -> None:
    """`_project_pipeline` writes the hold into pipeline.json and an `arrive` takes it out again."""
    import json
    from types import SimpleNamespace
    fake = SimpleNamespace(store=SimpleNamespace(root=root), _ticket=lambda: "T-1")
    fake._pipeline = lambda: CT.Controller._pipeline(fake)
    held = story(done=range(3), events=hold_events("first_look_stop", "S3") + [("first_look_continued", {"source_head": HEADS, "register_hash": HEX, "words": "w"})])
    held2 = story(done=range(3), events=hold_events("first_look_stop", "S3", sides={"b": {"reality": "absent"}}))
    CT.Controller._project_pipeline(fake, held2)
    written = json.loads((root / "pipeline.json").read_text(encoding="utf-8"))
    check_eq("pipeline.awaiting carries the record", (written["awaiting"]["cause"], written["awaiting"]["held_from"], written["awaiting"]["s5_dispatch"]),
             ("first_look_stop", "S3", None))
    check_eq("contract.awaiting reads it from the file", CON.awaiting(written)["state"], "awaiting")
    CT.Controller._project_pipeline(fake, held)
    written = json.loads((root / "pipeline.json").read_text(encoding="utf-8"))
    check_eq("a first_look_continued clears pipeline.awaiting and leaves pipeline.first_look_continue",
             ("awaiting" in written, written["first_look_continue"]["register_hash"]), (False, HEX))


def held_range_after_acceptance_move() -> None:
    """F6 (POSITIONAL): the stop inside the stage loop is repeated after `awaits_acceptance` moves `i`. INVARIANT: no stage of the held
    range is prepared. Here S6 awaits its consumer's acceptance and the hold starts at S7 - the move lands on S7."""
    import acceptance
    state = story(done=range(6), events=hold_events("first_look_stop", "S7"))
    real = acceptance.awaits_acceptance
    acceptance.awaits_acceptance = lambda s, stage, pipeline=None, table=None: "d6" if stage == "S6" else ""
    try:
        got = nxt(state)
    finally:
        acceptance.awaits_acceptance = real
    check_eq("a hold from S7 with S6 awaiting its acceptor does not prepare S7", (got["action"], got.get("held_from")),
             ("awaiting_implementation", "S7"))


def through_the_door() -> None:
    """The hold driven through the REAL `Controller.apply` on a store (the junction F1 and the event-kind map hide in): stop, a
    reopening rework with the person's words, the same words stopped again -> a NEW event and a stopped story (F1); then the
    dispatch refusals of F5 on the real state."""
    from test_controller_rework_scope import gate_a_task
    from harness import temp_project
    root = temp_project("qa-awaiting-door-")
    try:
        c = gate_a_task(root)
        c.apply("await", {"cause": "first_look_stop", "held_from": "S3", "idempotency_key": "await-1"})
        c.stop_waiting("stop")
        stopped = c.state()
        check_eq("stop_waiting through apply: the story is stopped", CON.awaiting({"awaiting": stopped["awaiting"]})["state"], "stopped")
        check_eq("... and `next` answers awaiting_stopped", c.next_action()["action"], "awaiting_stopped")
        check_eq("a first_look_continue on it is recorded under its own event kind only where allowed (refused here)",
                 refused(c.first_look_continue, "go on", HEADS, HEX)[0], "StateConflict")
        # F5 on the real state: a dispatch on a stopped story that is not the person's rework is refused, and so is a hand-written
        # `await_reopened` whose words are typed by code
        request = c.build_rework_request("S2", "qa-worker", [], WORDS, words_given=True)
        check_eq("the rework with words carries `await_reopened`", request.get("await_reopened"), {"words": WORDS})
        bare = {k: v for k, v in request.items() if k != "await_reopened"}
        kind, text = refused(c.validate, "dispatch", bare, stopped)
        check_eq("F5: a dispatch on a stopped story without the person's reopening is refused", kind, "StateConflict")
        check_in("... naming the doors", "arrive", text)
        kind, text = refused(c.validate, "dispatch", dict(request, person_words=False), stopped)
        check_eq("F5: a hand-written `await_reopened` with words typed by code is refused", kind, "ValueError")
        check_in("... naming the words file", "--words-file", text)
        kind, text = refused(c.validate, "dispatch", dict(request, await_reopened={"words": " "}), stopped)
        check_eq("F5: `await_reopened` with empty words is refused", kind, "ValueError")
        high = {k: v for k, v in request.items() if k != "rerun_after"}
        kind, text = refused(c.validate, "dispatch", dict(high, stage="S3", rework_of="dS3", role="qa-worker"), stopped)
        check_eq("F5: `await_reopened` on a stage from `held_from` is refused", kind, "StateConflict")
        check_eq("F5: the person's own rework passes the validation", refused(c.validate, "dispatch", request, stopped), ("", ""))
        before = c.state()["revision"]
        c.apply("dispatch", request)
        reopened = c.state()
        check_eq("the rework reopens the story: awaiting again, with the identity of the reopening",
                 (CON.awaiting({"awaiting": reopened["awaiting"]})["state"], reopened["awaiting"].get("reopened") is not None),
                 ("awaiting", True))
        check_eq("... one event more", reopened["revision"], before + 1)
        kind, text = refused(c.validate, "dispatch", dict(request, id="S2-qa-worker-9"), reopened)
        check_eq("F5: `await_reopened` on a story that is not stopped is refused", kind, "StateConflict")
        # F1: the SAME words stopped again are a new decision, not a replay of the first one
        again = c.stop_waiting("stop")
        after = c.state()
        check_eq("F1: the same words after a reopening commit a new event", after["revision"], reopened["revision"] + 1)
        check_eq("... and the story is stopped again", CON.awaiting({"awaiting": after["awaiting"]})["state"], "stopped")
        check_eq("... the receipt is not the first one's", again["receipt"].get("revision", after["revision"]) != stopped["revision"], True)
        repeat = c.stop_waiting("stop")
        check_eq("a REPEAT of that call (nothing between) is the same answer: no new event", c.state()["revision"], after["revision"])
        check_eq("... still stopped", repeat["stopped"], True)
        # F4: `arrive` with nothing held only records
        c.apply("arrive", {"idempotency_key": "arrive-1"})
        cleared = c.state()
        c.apply("arrive", {"idempotency_key": "arrive-2"})
        check_eq("F4: arrive with nothing held records (a new event) and refuses nothing", c.state()["revision"], cleared["revision"] + 1)
    finally:
        cleanup(root)


def main() -> None:
    root = temp_dir("qa-factory-awaiting-")
    try:
        due_and_hold()
        arrive_clears()
        stop_waiting_is_terminal()
        never_started_is_not_relaunched()
        first_look_hold()
        hold_without_cause()
        rework_refusals(root)
        replay()
        vocabulary()
        validate(root)
        pipeline_projection(root)
        held_range_after_acceptance_move()
        through_the_door()
    finally:
        cleanup(root)
    finish("test_awaiting_state")


if __name__ == "__main__":
    main()
