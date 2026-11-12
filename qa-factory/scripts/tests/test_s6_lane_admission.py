#!/usr/bin/env python3
"""t-2147 TR3-9d: the controller side of parallel S6 manual-walk lanes (admission, resume, stage record, config key).

Keys (spec t-2147, Part D): a lane flagged `walk_lane: True` with a string `walk_actor` is admitted beside running S6 manual lanes
only when every scope is disjoint, the accounts are pairwise distinct and the count is within `manual.walkers`; everything else
keeps the old refusal text byte for byte; a record with no `walk_actor` is an UNKNOWN account and admits nothing; a stopped lane
resumes beside its siblings; the stage stays `running` while a sibling runs. Controller in-process on a temp project, no driver, no
thread; not named `test_controller_*` on purpose (those files are CI's).
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import SCRIPTS, check, check_eq, check_in, check_not_in, cleanup, finish, mark_project, temp_project  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import config_contract as C  # noqa: E402
import controller as CTRL  # noqa: E402

import test_controller_state as BASE  # noqa: E402  (evidence_ref)
import test_story_step_manual_block as MB  # noqa: E402  (real_story)

OLD_TEXT = "sequential task already has an active dispatch: {ids}. Finish it first (`story_step.py finish`)"


def story(walkers=None, cases=5):
    """A project through S0..S5 with five manual-agent cases (TC-1..TC-5) and `manual.walkers` = `walkers` (None: key left out)."""
    root = temp_project("qa-s6lane-")
    mark_project(root)
    c = MB.real_story(root, ["manual-agent"] * cases)
    path = root / "qa-factory" / "config.json"
    config = json.loads(path.read_text(encoding="utf-8") or "{}")
    if walkers is not None:
        config["manual"] = {"walkers": walkers}
    path.write_text(json.dumps(config), encoding="utf-8")
    return root, c


def lane(did, scope, actor="alice", flag=True, **extra):
    request = {"id": did, "stage": "S6", "role": "qa-runner", "execution_kind": "manual", "scope": list(scope),
               "manual_case_ids": list(scope), "input_hash": "s6", "budget": {}, "known_paths": {}, "idempotency_key": did}
    if flag:
        request["walk_lane"] = True
    if actor is not None:
        request["walk_actor"] = actor
    request.update(extra)
    return request


def refusal(call):
    try:
        call()
    except Exception as exc:  # noqa: BLE001
        return str(exc)
    return ""


def rec(c, did):
    return c.state()["dispatches"][did]


def stage(c):
    return c.state()["stages"]["S6"]


def running(c):
    return sorted(d for d, r in c.state()["dispatches"].items() if r["status"] == "running")


def accept(c, root, did, **extra):
    body = {"id": did, "status": "accepted", "stage_complete": False, "idempotency_key": did + "-ok",
            "evidence_refs": [BASE.evidence_ref(root, did + ".txt", did)]}
    body.update(extra)
    return c.apply("accept", body)


def with_one(walkers=None, actor="alice", scope=("TC-1",)):
    root, c = story(walkers)
    c.apply("dispatch", lane("L1", scope, actor))     # the first lane runs alone (the flag is inert); the driver marks every lane
    return root, c


def two_lanes_disjoint_distinct_accounts_admitted():
    root, c = with_one()
    try:
        c.apply("dispatch", lane("L2", ["TC-2"], "bob"))
        c.apply("dispatch", lane("L3", ["TC-3"], "carol"))
        check_eq("three disjoint lanes on three accounts run at once (default 3)", running(c), ["L1", "L2", "L3"])
        check_eq("the flag and the account are on the record", (rec(c, "L2").get("walk_lane"), rec(c, "L2").get("walk_actor")), (True, "bob"))
        text = refusal(lambda: c.apply("dispatch", lane("L4", ["TC-4"], "dave")))
        check_eq("a fourth lane is over the default cap: the old text", text, OLD_TEXT.format(ids="L1, L2, L3"))
    finally:
        cleanup(root)


def admitted_lane_never_runs_close_settled():
    """TR4-7 B1 for S6: a lane `validate` admits beside a running one must not make `apply` run the dead-holder repair over its
    siblings. The liveness reader is made to say "the session is over" for every row, so a repair that ran WOULD close L1."""
    import dispatch_liveness
    root, c = with_one()
    try:
        asked = []

        def over(project, dispatch, now=None):
            asked.append(dispatch.get("id"))
            return {"state": dispatch_liveness.RETURNED, "evidence": ["probe: the session is over"]}

        c._liveness = over
        before = dict(rec(c, "L1"))
        c.apply("dispatch", lane("L2", ["TC-2"], "bob"))
        check_eq("an admitted second lane: the first lane's row is untouched", rec(c, "L1"), before)
        check_eq("both lanes run", running(c), ["L1", "L2"])
        check_eq("liveness was never asked about a sibling of an admitted lane", asked, [])
        # control: a request that no clause admits still gets the repair (the clause only widens the admitted case)
        refused = refusal(lambda: c.apply("dispatch", lane("L3", ["TC-2", "TC-3"], "carol")))
        check("control: a lane that shares a case is NOT admitted, so the repair ran (liveness asked) and the rows closed",
              asked and rec(c, "L1")["status"] != "running", (asked, refused))
    finally:
        cleanup(root)


def shared_case_refused():
    root, c = with_one()
    try:
        old = OLD_TEXT.format(ids="L1")
        check_eq("a lane sharing a case is refused with the old text, byte for byte",
                 refusal(lambda: c.apply("dispatch", lane("Lx", ["TC-1", "TC-2"], "bob"))), old)
        check_eq("control: the same lane without the shared case runs", refusal(lambda: c.apply("dispatch", lane("Lx", ["TC-2"], "bob"))), "")
    finally:
        cleanup(root)


def same_account_refused():
    root, c = with_one()
    try:
        old = OLD_TEXT.format(ids="L1")
        text = refusal(lambda: c.apply("dispatch", lane("L2", ["TC-2"], "alice")))
        check_eq("two lanes on one account are refused with the old text", text, old)
        check_in("the text names the holder", "L1", text)
        check_in("the text names the door", "story_step.py finish", text)
    finally:
        cleanup(root)


def guest_beside_guest_refused():
    root, c = with_one(actor="")
    try:
        check_eq("a guest beside a guest is refused",
                 refusal(lambda: c.apply("dispatch", lane("L2", ["TC-2"], ""))), OLD_TEXT.format(ids="L1"))
        check_eq("a named account beside a guest is admitted", refusal(lambda: c.apply("dispatch", lane("L2", ["TC-2"], "bob"))), "")
    finally:
        cleanup(root)


def no_flag_old_refusal_byte_for_byte():
    root, c = with_one()
    try:
        old = OLD_TEXT.format(ids="L1")
        check_eq("no flag: the old refusal", refusal(lambda: c.apply("dispatch", lane("L2", ["TC-2"], "bob", flag=False))), old)
        for label, value in (("the string 'true'", "true"), ("the integer 1", 1), ("False", False), ("None", None)):
            check_eq(f"walk_lane is {label}, not literally True: the old refusal",
                     refusal(lambda: c.apply("dispatch", lane("L2", ["TC-2"], "bob", flag=False, walk_lane=value))), old)
    finally:
        cleanup(root)


def s6_beside_s5_window_refused():
    root, c = with_one()
    try:
        c.apply("dispatch", lane("L2", ["TC-2"], "bob"))
        state = c.state()
        window = {"id": "W1", "stage": "S5", "role": "qa-automator", "status": "running", "scope": ["TC-4"], "parallel_window": True}
        mine = lane("L3", ["TC-3"], "carol")
        check_eq("an S5 window among the running ones: no lane beside it", c._lane_beside_running(mine, state, [rec(c, "L1"), window]), False)
        check_eq("a lane among the running ones: no S5 window beside it",
                 c._window_beside_running(dict(window, id="W2", scope=["TC-5"]), state, [rec(c, "L1")]), False)
        automation = dict(rec(c, "L1"), execution_kind="automation")
        check_eq("an automation runner among the running ones: no lane beside it", c._lane_beside_running(mine, state, [automation]), False)
        other = dict(rec(c, "L1"), role="qa-automator")
        check_eq("another role among the running ones: no lane beside it", c._lane_beside_running(mine, state, [other]), False)
        check_eq("control: the two real lanes admit a third", c._lane_beside_running(mine, state, [rec(c, "L1"), rec(c, "L2")]), True)
    finally:
        cleanup(root)


def over_cap_refused():
    root, c = with_one(walkers=2)
    try:
        c.apply("dispatch", lane("L2", ["TC-2"], "bob"))
        check_eq("walkers 2: the third lane is refused with the old text",
                 refusal(lambda: c.apply("dispatch", lane("L3", ["TC-3"], "carol"))), OLD_TEXT.format(ids="L1, L2"))
        check_eq("the cap reads 2", c._walkers_cap(), 2)
        (root / "qa-factory" / "config.json").write_text("", encoding="utf-8")
        check_eq("an empty config: the default 3, no raise", c._walkers_cap(), 3)
        (root / "qa-factory" / "config.json").unlink()
        check_eq("no config file: the default 3, no raise", c._walkers_cap(), 3)
    finally:
        cleanup(root)


def walkers_one_never_admits():
    root, c = with_one(walkers=1)
    try:
        check_eq("walkers 1: a disjoint, distinct, flagged lane is still refused with the old text",
                 refusal(lambda: c.apply("dispatch", lane("L2", ["TC-2"], "bob"))), OLD_TEXT.format(ids="L1"))
        check_eq("one dispatch is running", running(c), ["L1"])
    finally:
        cleanup(root)


def returned_sibling_scope_counts():
    root, c = with_one()
    try:
        c.apply("dispatch", lane("L2", ["TC-2"], "bob"))
        c.record_return("L2", "digest", "agent-2")
        check_eq("L2 is returned_unaccepted", rec(c, "L2")["status"], "returned_unaccepted")
        check_eq("a returned sibling is not counted but its scope is checked",
                 refusal(lambda: c.apply("dispatch", lane("L3", ["TC-2", "TC-3"], "carol"))), OLD_TEXT.format(ids="L1"))
        check_eq("a disjoint lane runs", refusal(lambda: c.apply("dispatch", lane("L4", ["TC-4"], "dave"))), "")
    finally:
        cleanup(root)


def walk_actor_not_string_refused():
    root, c = with_one()
    try:
        state, base = c.state(), rec(c, "L1")
        for label, value in (("a list", ["bob"]), ("None", None), ("an int", 5), ("a dict", {})):
            check_eq(f"walk_actor of the new lane is {label}: refused",
                     c._lane_beside_running(dict(lane("L2", ["TC-2"], "bob"), walk_actor=value), state, [base]), False)
            check_eq(f"walk_actor of a running lane is {label}: refused",
                     c._lane_beside_running(lane("L2", ["TC-2"], "bob"), state, [dict(base, walk_actor=value)]), False)
        check_eq("control: strings pass", c._lane_beside_running(lane("L2", ["TC-2"], "bob"), state, [base]), True)
        for label, scope in (("empty", []), ("not a list", "TC-1"), ("a non-string case", [1])):
            check_eq(f"a running lane with a {label} scope is not disjoint",
                     c._lane_beside_running(lane("L2", ["TC-2"], "bob"), state, [dict(base, scope=scope)]), False)
        check_eq("an empty scope of the new lane is refused", c._lane_beside_running(dict(lane("L2", ["TC-2"], "bob"), scope=[]), state, [base]), False)
        check_eq("a malformed request never raises", c._lane_beside_running({"walk_lane": True}, state, [base]), False)
        check_eq("nothing running: not a 'beside'", c._lane_beside_running(lane("L2", ["TC-2"], "bob"), state, []), False)
    finally:
        cleanup(root)


def stop_lane(c, did):
    c.store.commit("stage_transition", {"stage": "S6", "status": "running", "digest": "", "dispatch_id": did, "agent_id": "ag-" + did}, "bind-" + did)
    c.apply("checkpoint", c.build_checkpoint_request(did, "paused", "the person is asked", None))


def resume_beside_running_lane():
    root, c = with_one()
    try:
        c.apply("dispatch", lane("L2", ["TC-2"], "bob"))
        stop_lane(c, "L2")
        check_eq("L2 is stopped, L1 runs", (rec(c, "L2")["status"], rec(c, "L1")["status"]), ("paused", "running"))
        c.apply("resume", c.build_resume_request("L2"))
        check_eq("a stopped lane resumes beside its running sibling (no flag on the road)", running(c), ["L1", "L2"])
        stop_lane(c, "L2")
        accept(c, root, "L1")
        c.apply("dispatch", lane("L3", ["TC-3"], "bob"))          # alone now; takes bob
        text = refusal(lambda: c.apply("resume", c.build_resume_request("L2")))
        check_in("the same account running: the resume keeps the old refusal", "sequential task already has an active dispatch: L3", text)
    finally:
        cleanup(root)
    root, c = with_one(walkers=1)
    try:
        c.apply("checkpoint", c.build_checkpoint_request("L1", "paused", "stop", None))
        c.apply("dispatch", lane("L2", ["TC-2"], "bob", flag=False))
        text = refusal(lambda: c.apply("resume", c.build_resume_request("L1")))
        check_in("walkers 1: the resume keeps the old refusal", "sequential task already has an active dispatch: L2", text)
    finally:
        cleanup(root)


def old_running_record_without_walk_actor_refuses():
    root, c = story()
    try:
        c.apply("dispatch", lane("L1", ["TC-1"], None, flag=False))            # a record from before this change: no walk_actor, no flag
        old = OLD_TEXT.format(ids="L1")
        check_eq("an old running record (no walk_actor) is an unknown account: no lane beside it",
                 refusal(lambda: c.apply("dispatch", lane("L2", ["TC-2"], "bob"))), old)
        check_eq("a flagged record with no walk_actor is the same",
                 c._lane_beside_running(lane("L2", ["TC-2"], "bob"), c.state(), [dict(rec(c, "L1"), walk_lane=True)]), False)
        check_eq("an actor with no flag is the same",
                 c._lane_beside_running(lane("L2", ["TC-2"], "bob"), c.state(), [dict(rec(c, "L1"), walk_actor="alice")]), False)
        check_eq("a guest request is not read as the unknown account either",
                 refusal(lambda: c.apply("dispatch", lane("L3", ["TC-3"], ""))), old)
    finally:
        cleanup(root)


def s6_lane_accept_beside_running_keeps_stage_running():
    root, c = with_one()
    try:
        c.apply("dispatch", lane("L2", ["TC-2"], "bob"))
        accept(c, root, "L1")
        check_eq("L1 accepted, L2 running: S6 stays running with L2's id", (stage(c)["status"], stage(c).get("dispatch_id")), ("running", "L2"))
        accept(c, root, "L2")
        check_eq("the last one to stop lowers the stage as it always did", stage(c)["status"], "pending")
        c.apply("dispatch", lane("L3", ["TC-3"], "alice"))
        c.apply("dispatch", lane("L4", ["TC-4"], "bob"))
        stop_lane(c, "L3")
        check_eq("a stop beside a running lane keeps S6 running", (stage(c)["status"], stage(c).get("dispatch_id")), ("running", "L4"))
        entry = {"status": "pending"}
        state = {"dispatches": {"a": {"id": "a", "stage": "S6", "role": "qa-runner", "execution_kind": "automation", "status": "running"}}}
        check("an automation runner beside is not a lane: the entry is returned as it was",
              CTRL.stage_entry_beside_running(state, lane("L9", ["TC-5"]), entry) is entry)
        done = {"status": "completed"}
        check("a completed entry is never touched", CTRL.stage_entry_beside_running(c.state(), rec(c, "L3"), done) is done)
    finally:
        cleanup(root)


def s6_serial_replay_byte_identical():
    root, c = story()
    try:
        for n, case in enumerate(("TC-1", "TC-2", "TC-3", "TC-4"), 1):
            c.apply("dispatch", lane(f"R{n}", [case], "alice", flag=False))
            if n == 3:
                stop_lane(c, "R3")
            else:
                accept(c, root, f"R{n}")
        events = c.store.read()
        now = json.dumps(CTRL.projection(events), sort_keys=True, default=str)
        real = CTRL.stage_entry_beside_running
        CTRL.stage_entry_beside_running = lambda state, d, entry: entry       # the reducer as it was before this node
        try:
            before = json.dumps(CTRL.projection(events), sort_keys=True, default=str)
        finally:
            CTRL.stage_entry_beside_running = real
        check_eq("a journal with no two running S6 dispatches replays byte-identical to the reducer without the node", now, before)
        check("and it really had several S6 records", len([r for r in c.state()["dispatches"].values() if r.get("stage") == "S6"]) >= 4)
    finally:
        cleanup(root)


def nonlast_lane_not_complete_beside_running_accepted():
    root, c = with_one()
    try:
        c.apply("dispatch", lane("L2", ["TC-2"], "bob"))
        text = refusal(lambda: accept(c, root, "L1", stage_complete=False))
        check_eq("a non-last lane accepted with stage_complete false beside a running one is accepted", text, "")
        check_eq("L1 is accepted, L2 still runs", (rec(c, "L1")["status"], rec(c, "L2")["status"]), ("accepted", "running"))
        check_eq("the stage is not completed", stage(c)["status"], "running")
    finally:
        cleanup(root)


def close_refused_beside_running_lane():
    root, c = story(cases=2)
    try:
        c.apply("dispatch", lane("L1", ["TC-1"], "alice"))
        c.apply("dispatch", lane("L2", ["TC-2"], "bob"))
        BASE.record_stage_acceptance(root, "S6", "L2")
        text = refusal(lambda: accept(c, root, "L2", stage_complete=True))
        check_in("closing S6 beside a running lane is refused, naming the lane", "L1", text)
        check_in("the refusal says it is still running", "still running", text)
        check_in("the refusal names the S5 twin's door: finish this lane without closing", "story_step.py finish", text)
        check_in("with --not-complete", "--not-complete", text)
        check_not_in("never the pause door (a paused lane is not a finished one, B-D1)", "story_step.py pause", text)
        check_in("and the person's word, lane not window (F-D4)", "close beside a running lane", text)
        check_not_in("the S6 text does not say window", "running window", text)
        check_eq("L2 is still running (nothing was written)", rec(c, "L2")["status"], "running")
        accept(c, root, "L1")
        check_eq("L1 finished: the close passes", refusal(lambda: accept(c, root, "L2", stage_complete=True)), "")
        check_eq("S6 is completed", stage(c)["status"], "completed")
    finally:
        cleanup(root)
    root, c = story(walkers=1, cases=2)
    try:
        c.apply("dispatch", lane("L1", ["TC-1", "TC-2"], "alice"))
        BASE.record_stage_acceptance(root, "S6", "L1")
        check_eq("walkers 1: the lone lane closes S6 as it always did", refusal(lambda: accept(c, root, "L1", stage_complete=True)), "")
    finally:
        cleanup(root)


def config_walkers_absent_bad_bool_zero():
    check_eq("the constant is 3", C.MANUAL_WALKERS_DEFAULT, 3)
    for label, cfg in (("no key", {"manual": {}}), ("no manual block", {}), ("config not an object", None), ("manual not an object", {"manual": 5})):
        check_eq("missing key reads 3, no note: " + label, C.walkers(cfg), (3, None))
    check_eq("2 reads 2", C.walkers({"manual": {"walkers": 2}}), (2, None))
    check_eq("1 reads 1 (one walker at a time)", C.walkers({"manual": {"walkers": 1}}), (1, None))
    for bad in (0, -1, "2", 1.5, True, None, [2]):
        value, note = C.walkers({"manual": {"walkers": bad}})
        check_eq(f"bad value {bad!r} reads the default", value, 3)
        check(f"bad value {bad!r} gives exactly one note line naming the key and the serial door",
              isinstance(note, str) and note.startswith("note:") and "\n" not in note and "manual.walkers" in note
              and "1 runs one walker at a time" in note, note)


def main():
    two_lanes_disjoint_distinct_accounts_admitted()
    admitted_lane_never_runs_close_settled()
    shared_case_refused()
    same_account_refused()
    guest_beside_guest_refused()
    no_flag_old_refusal_byte_for_byte()
    s6_beside_s5_window_refused()
    over_cap_refused()
    walkers_one_never_admits()
    returned_sibling_scope_counts()
    walk_actor_not_string_refused()
    resume_beside_running_lane()
    old_running_record_without_walk_actor_refuses()
    s6_lane_accept_beside_running_keeps_stage_running()
    s6_serial_replay_byte_identical()
    nonlast_lane_not_complete_beside_running_accepted()
    close_refused_beside_running_lane()
    config_walkers_absent_bad_bool_zero()
    finish("test_s6_lane_admission")


if __name__ == "__main__":
    main()
