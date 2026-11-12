#!/usr/bin/env python3
"""k6 k7: a part of test_story_run_freshness.py, split by tools/test_split.py (TD-11c). The shared helpers are in story_run_freshness_common."""
import contextlib
import hashlib
import io
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import check, check_eq, check_in, check_not_in  # noqa: E402
from story_run_common import driver_for, run_scenarios, stub_calls
from story_run_freshness_common import KEY, asked_driver, events, freshness_project  # noqa: E402


# --- K6-K7 new text -------------------------------------------------------------------------------------------------
def gate_a_story(decided: bool = True, late: bool = False):
    """(root, task_root, env, ticket file, controller): S0..S4 accepted and gate A approved on scope TC-1 - and S5 accepted
    when `late` - over the same file adapter as `freshness_project`."""
    root, task_root, env, ticket = freshness_project()
    import test_controller_rework_scope as SCOPED
    import test_controller_state as BASE
    from controller import Controller
    c = Controller(task_root)
    c.apply("revise_plan", {"scope": ["TC-1"], "plan_revision": "src-1", "reason": "test setup: the story's scope",
                            "idempotency_key": "scope"})
    for number in range(5 if decided else 4):
        BASE.accept_stage(c, task_root, f"S{number}")
    if decided:
        BASE.seed_plan(task_root, [SCOPED.plan_row(1, "automate")])
        c.apply("decision", BASE.bind_gate_a(task_root, {"id": "gate-a", "gate": "A", "action": "approve", "status": "approved",
                                                          "authorization_source": "human", "source_revision": "src-1", "scope": ["TC-1"],
                                                          "input_revision": "src-1", "idempotency_key": "gate-a"}))
    if late:
        BASE.accept_stage(c, task_root, "S5")
    return root, task_root, env, ticket, c


def strategist_closed_s3(controller, task_root: Path) -> None:
    """`BASE.accept_stage` closes S3 with a `qa-worker` dispatch, but the rework of S3 goes back over the work of the strategist
    (`ticket_rework_step`: "a first look accepted after the strategist is not the author"): give S3 the strategist's accepted work."""
    controller.apply("dispatch", {"id": "dS3-strategist", "stage": "S3", "role": "qa-test-strategist", "scope": ["TC-1"], "input_hash": "S3",
                                  "budget": {}, "known_paths": {}, "idempotency_key": "dispatch-S3-strategist"})
    evidence = task_root / "S3-strategist.txt"
    evidence.write_text("S3-strategist", encoding="utf-8")
    controller.apply("accept", {"id": "dS3-strategist", "status": "accepted", "stage_complete": False, "idempotency_key": "accept-S3-strategist",
                                "evidence_refs": [{"path": evidence.name, "sha256": hashlib.sha256(evidence.read_bytes()).hexdigest()}]})


def staged_driver(root: Path, env: dict, task_root: Path, accept: dict):
    """A driver whose roles are recorded, not run: `accept["on"]` says whether the stub closes the dispatch it was sent to."""
    driver = driver_for(root, env, KEY, max_boundaries=12)
    started = []

    def fake_role(stage, role, scope=None, extra=None, complete=None, rework=None, **kwargs):
        started.append((stage, role, (rework or {}).get("id"), complete))
        if accept["on"]:
            accept_dispatch(task_root, (rework or {}).get("id"), bool(complete))
        return "", None
    driver.run_role = fake_role
    driver.started = started
    return driver


def accept_dispatch(task_root: Path, dispatch_id: str, complete: bool = True) -> None:
    import hashlib
    from controller import Controller
    evidence = task_root / f"{dispatch_id}.txt"
    evidence.write_text(dispatch_id, encoding="utf-8")
    if complete:
        # X2-7: a stage with an acceptor closes over the critic's record of THIS dispatch (a refusal raises StateConflict out of `apply`: loud)
        # the record names the dispatch the controller reads as the stage's author (`""` for a fixture role that is not the stage's first)
        import acceptance
        from test_controller_state import record_stage_acceptance
        state = Controller(task_root).state()
        held = state["dispatches"][dispatch_id]
        record_stage_acceptance(task_root, held["stage"], reviewed_dispatch=acceptance.stage_author_dispatch(state, acceptance.stage_def_of(held["stage"]), held))
    Controller(task_root).apply("accept", {"id": dispatch_id, "status": "accepted", "stage_complete": complete,
                                           "evidence_refs": [{"path": evidence.name, "sha256": hashlib.sha256(evidence.read_bytes()).hexdigest()}],
                                           "idempotency_key": "accept-" + dispatch_id})


def state_of(task_root: Path) -> dict:
    from controller import Controller
    return Controller(task_root).state()


def k6_k7_new_text_reworks_s2_then_s3_then_reopens_gate_a() -> None:
    root, task_root, env, ticket, controller = gate_a_story(decided=True, late=True)
    try:
        strategist_closed_s3(controller, task_root)
        driver, _person = asked_driver(root, env, task_root, ticket)
        accept = {"on": False}
        stub = staged_driver(root, env, task_root, accept)
        stub.state = driver.state                                   # the same driver's state, a fresh process's roles
        stub.state["asked"] = {"kind": "ticket_changed", "stage": "S0", "dispatch": "", "at": "x"}
        printed = io.StringIO()
        with contextlib.redirect_stdout(printed):
            stub.take_ticket_answer("new text", "# q\n", "S0", "")
        check("K6: `new text` adopted the waiting text: `.next` is gone", not (task_root / "work" / "ticket-snapshot.next.json").is_file())
        check_in("K6: and it says so in words", "the new ticket text is adopted; the requirements and the plan are made again from it", printed.getvalue())
        owed = stub.state.get("ticket_rework") or {}
        check_eq("K6: S2 and S3, the stages the controller holds completed, in order", (owed.get("stages"), owed.get("words")), (["S2", "S3"], "new text"))
        check("K6: the person's words are on the journal's record (FR-8)", any("new text" in str(r.get("notes")) for r in events(root, "human_answer")))
        # S2 first; it is left running, so S3 must NOT be registered (the controller refuses a second running dispatch anyway)
        with contextlib.redirect_stdout(io.StringIO()):
            check_eq("K6: the first turn moves", stub.ticket_rework_step(), True)
            check_eq("K6: S2 is sent back with cause `ticket_changed` and complete=True", [(s, c) for s, _r, _i, c in stub.started], [("S2", True)])
            check_eq("K6: S2 left running: the next turn leaves it to the loop (False), and S3 is NOT registered", (stub.ticket_rework_step(), len(stub.started)), (False, 1))
        s2 = state_of(task_root)["dispatches"][stub.started[0][2]]
        check_eq("K6: the dispatch carries the cause and the words as its reason", (s2["repair_cause"], s2["reason"], s2["status"]), ("ticket_changed", "new text", "running"))
        accept_dispatch(task_root, stub.started[0][2], True)
        accept["on"] = False
        with contextlib.redirect_stdout(io.StringIO()):
            check_eq("K6: S2 accepted: S3 is registered now", (stub.ticket_rework_step(), [s for s, *_ in stub.started]), (True, ["S2", "S3"]))
        if not check_eq("K6: the S3 dispatch is there to be accepted", len(stub.started), 2):
            return
        s3_id = stub.started[1][2]
        accept_dispatch(task_root, s3_id, True)
        state = state_of(task_root)
        check_eq("K6: S2 and S3 stay completed (a re-run lowers nothing)", (state["stages"]["S2"]["status"], state["stages"]["S3"]["status"]), ("completed", "completed"))
        # K7: S2 and S3 are done again: gate A, decided on the old requirements, is asked again - and the automation built on them goes
        stub.save_state()
        with contextlib.redirect_stdout(printed := io.StringIO()):
            check_eq("K7: the next turn reopens gate A", stub.ticket_rework_step(), True)
        state = state_of(task_root)
        check_eq("K7: the approved gate A decision is stale", [d["status"] for d in state["decisions"].values() if d.get("gate") == "A"], ["stale"])
        check_eq("K7: S4 is pending, reopened", (state["stages"]["S4"]["status"], state["stages"]["S4"].get("gate_a_reopened")), ("pending", True))
        reopens = state.get("reopens") or []
        check_eq("K7: one reopen, the person's words as the reason, on the story's scope",
                 (len(reopens), reopens[0]["reason"].startswith("the person chose the changed ticket text: new text"), reopens[0]["affected_scope"]), (1, True, ["TC-1"]))
        check_eq("K7: S5 stood completed: its accepted work of the scope is invalidated, the stage is pending again",
                 (state["stages"]["S5"]["status"], [d["status"] for d in state["dispatches"].values() if d["stage"] == "S5"]), ("pending", ["stale", "stale"]))
        check_eq("K7: the rework is done: nothing owed, the note for gate A is set",
                 (stub.state.get("ticket_rework"), "Gate A is asked again" in (stub.state.get("gate_note") or {}).get("A", "")), (None, True))
        with contextlib.redirect_stdout(io.StringIO()):
            check_eq("K7: and a later turn has nothing to do", stub.ticket_rework_step(), False)
        # what the loop answers: the full S4 run first, THEN gate A
        first = stub.where()
        check_eq("K7: `where` answers prepare_stage S4 (a full re-run), before any await_gate A", (first.get("action"), first.get("stage")), ("prepare_stage", "S4"))
        import test_controller_state as BASE
        BASE.accept_case_review_stage(controller, task_root, "s4-redo")
        second = stub.where()
        check_eq("K7: once S4 is accepted again, gate A is asked", (second.get("action"), second.get("gate")), ("await_gate", "A"))
        # the gate's text carries the line, once
        stub.gate_text = lambda gate: "the packet"
        person = None
        try:
            stub.gate("A", top="the rest")
        except Exception as exc:
            person = exc
        check("K7: the gate A question starts with the line that says why it comes again, then the rest",
              person is not None and person.text.startswith(f"# Gate A — {KEY}\n\nGate A is asked again: you chose the new ticket text, and the requirements and the plan were made again from it.\n\nthe rest"),
              getattr(person, "text", "")[:300])
        check_eq("K7: the line is popped: the next ask of the gate does not repeat it", stub.state.get("gate_note", {}).get("A"), None)
        # t-694 F4: ONE carrier. The writer wrote `gate_note` (above); the old key is neither written nor read any more.
        check_eq("F4: the reopen wrote no `ticket_gate_note`", "ticket_gate_note" in stub.state, False)
        stub.state["ticket_gate_note"] = {"A": "a line an older driver left in its state file"}
        left_over = None
        try:
            stub.gate("A", top="")
        except Exception as exc:
            left_over = exc
        check_not_in("F4: and a leftover `ticket_gate_note` is not read at the gate (named in the report as dropped)",
                     "an older driver", getattr(left_over, "text", ""))
        check_eq("K7: no conductor was called anywhere on the way (the answer is a token, read by code, never a meaning)",
                 [c for c in stub_calls(root) if c["kind"] == "conductor"], [])
    finally:
        harness.cleanup(root)


def k7b_gate_a_not_decided_is_not_reopened() -> None:
    root, task_root, env, ticket, controller = gate_a_story(decided=False)
    try:
        strategist_closed_s3(controller, task_root)
        driver, _ = asked_driver(root, env, task_root, ticket)
        accept = {"on": True}
        stub = staged_driver(root, env, task_root, accept)
        stub.state = driver.state
        with contextlib.redirect_stdout(io.StringIO()):
            stub.take_ticket_answer("new text", "# q\n", "S0", "")
        check_eq("K7b: S2 and S3 are owed", (stub.state.get("ticket_rework") or {}).get("stages"), ["S2", "S3"])
        printed = io.StringIO()
        with contextlib.redirect_stdout(printed):
            turns = []
            for _ in range(5):
                turns.append(stub.ticket_rework_step())
        check_eq("K7b: S2, then S3 are re-run and accepted; the last turns reach the reopen's turn and then nothing", turns, [True, True, True, False, False])
        check_eq("K7b: no gate A was decided: no reopen is recorded", state_of(task_root).get("reopens") or [], [])
        check_in("K7b: one line says so", "no approved gate A to ask again", printed.getvalue())
        check_eq("K7b: the rework is done and no note is left", (stub.state.get("ticket_rework"), "gate_note" in stub.state), (None, False))
    finally:
        harness.cleanup(root)


def k7c_the_reworks_own_edges() -> None:
    """The step's state machine over a fake controller state: running, a stopped dispatch, a person's word, a second change,
    no accepted work - each its own move (FR-42)."""
    root, task_root, env, _ticket = freshness_project()
    try:
        driver = driver_for(root, env, KEY)
        (task_root / "state").mkdir(exist_ok=True)
        (task_root / "state" / "controller.json").write_text("{}", encoding="utf-8")       # the controller exists (B5)
        rework_calls = []
        driver.rework = lambda stage, role, cases, reason, **kw: rework_calls.append((stage, role, cases, reason, kw))
        holder = {"dispatches": {}, "stages": {}}
        driver.controller_state = lambda: holder
        driver.ticket_reopen_gate_a = lambda pending: rework_calls.append(("reopen", dict(pending)))

        def owed(stages, before=()):
            driver.state["ticket_rework"] = {"stages": list(stages), "words": "new text", "at": "t", "before": list(before)}

        def step():
            with contextlib.redirect_stdout(io.StringIO()):
                return driver.ticket_rework_step()
        accepted_s2 = {"id": "S2-qa-requirements-tester-1", "stage": "S2", "role": "qa-requirements-tester", "status": "accepted"}
        # nothing owed
        driver.state.pop("ticket_rework", None)
        check_eq("K7c: nothing owed: False, nothing called", (step(), rework_calls), (False, []))
        # a running dispatch anywhere: the loop's, not ours
        owed(["S2"])
        holder["dispatches"] = {"x": {"stage": "S5", "status": "running"}, accepted_s2["id"]: accepted_s2}
        check_eq("K7c: a dispatch is running: False, nothing registered", (step(), rework_calls), (False, []))
        # S2 has accepted work: it is registered, with the role of its last accepted dispatch, complete=True
        holder["dispatches"] = {accepted_s2["id"]: accepted_s2}
        check_eq("K7c: S2 with accepted work: registered", step(), True)
        check_eq("K7c: with the role of that dispatch, no cases, the person's words, cause `ticket_changed`, complete=True",
                 rework_calls, [("S2", "qa-requirements-tester", [], "new text", {"cause": "ticket_changed", "complete": True})])
        rework_calls.clear()
        # S2's re-run exists and is stopped (not accepted): the loop resolves it
        mine = {"id": "S2-qa-requirements-tester-2", "stage": "S2", "role": "qa-requirements-tester", "status": "incomplete", "repair_cause": "ticket_changed"}
        holder["dispatches"][mine["id"]] = mine
        check_eq("K7c: its re-run stopped: False (the loop's `where` resolves it), nothing registered twice", (step(), rework_calls), (False, []))
        # set aside before it was accepted - the controller's own words (a person's release, a retry that took its place,
        # an invalidation), never literals of ours: the rework ends with one line, the rest is not re-run, and the person's
        # choice of the new text still stands, so gate A is still asked again (the reopen move), never left on the old text
        import controller as C
        for status in (C.RELEASED, "superseded", "stale"):
            mine["status"] = status
            owed(["S2", "S3"])
            rework_calls.clear()
            printed = io.StringIO()
            with contextlib.redirect_stdout(printed):
                moved = driver.ticket_rework_step()
            check_eq(f"K7c: the re-run `{status}`: no more re-runs, the gate A move follows, the list is gone",
                     (moved, [c[0] for c in rework_calls], driver.state.get("ticket_rework")), (True, ["reopen"], None))
            check_in(f"K7c: the re-run `{status}`: one line says it was set aside and gate A is still asked again", "was set aside before it was accepted", printed.getvalue())
        mine["status"] = C.NEVER_STARTED
        owed(["S2"])
        rework_calls.clear()
        check_eq("K7c: a re-run that never started is the loop's to relaunch (`where`): False, nothing else moves", (step(), rework_calls), (False, []))
        rework_calls.clear()
        # a second change of the ticket: the earlier re-run is NOT this one's (the `before` list), so S2 is owed again
        mine["status"] = "accepted"
        owed(["S2"], before=[mine["id"]])
        check_eq("K7c: a second ticket change is owed its own re-run, not satisfied by the first", (step(), [c[0] for c in rework_calls]), (True, ["S2"]))
        rework_calls.clear()
        # this change's own re-run accepted: popped; the list is empty: the gate A move is asked for
        owed(["S2"])
        check_eq("K7c: this change's re-run accepted: the stage is done, then the gate A move", (step(), [c[0] for c in rework_calls]), (True, ["reopen"]))
        check_eq("K7c: and the list is gone", driver.state.get("ticket_rework"), None)
        rework_calls.clear()
        # a stage with no accepted work gets no rework and one line (K25)
        owed(["S6"])
        printed = io.StringIO()
        with contextlib.redirect_stdout(printed):
            moved = driver.ticket_rework_step()
        check_eq("K25: a stage with no accepted dispatch: no rework, skipped, then the gate A move", (moved, [c[0] for c in rework_calls]), (True, ["reopen"]))
        check_in("K25: one line says so", "S6 has no accepted work to make again; skipped", printed.getvalue())
        # no controller.json (B5): never
        (task_root / "state" / "controller.json").unlink()
        owed(["S2"])
        rework_calls.clear()
        check_eq("K18b: no controller.json: no rework, whatever is owed", (step(), rework_calls), (False, []))
    finally:
        harness.cleanup(root)


def k7d_the_reopen_sets_aside_the_late_work_and_names_what_it_cannot() -> None:
    """F3 over a fake controller: (a) a half-done S5 (pending, accepted windows) is invalidated like a completed one; (b) a
    completed stage no dispatch of the scope names (closed by code, or scopeless) is NAMED in the line and at gate A's top;
    (c) a restart after the invalidate names the same stage and records nothing twice."""
    root, task_root, env, _ticket = freshness_project()
    try:
        driver = driver_for(root, env, KEY)
        calls = []
        driver.controller = lambda op, *a, input_data=None: calls.append((op, input_data)) or {}
        holder = {"source_revision": "r", "revision": 3, "scope": ["TC-1"],
                  "decisions": {"g": {"gate": "A", "status": "approved", "source_revision": "r"}}, "stages": {}, "dispatches": {}}
        driver.controller_state = lambda: holder

        def reopen(pending):
            printed = io.StringIO()
            with contextlib.redirect_stdout(printed):
                driver.ticket_reopen_gate_a(pending)
            return printed.getvalue()
        holder["stages"] = {"S5": {"status": "pending"}}
        holder["dispatches"] = {"dS5": {"stage": "S5", "status": "accepted", "scope": ["TC-1"]}}
        reopen({"words": "new text", "at": "t"})
        check_eq("F3a: S5 only PENDING with an accepted window: the reopen and the invalidate of that window",
                 ([c[0] for c in calls], (calls[1][1] or {}).get("dispatch_ids")), (["semantic_reopen", "invalidate"], ["dS5"]))
        check_eq("F3a: nothing is left unnamed: the note for gate A is the plain line", driver.state["gate_note"]["A"].count("Note that"), 0)
        # (b) S5 completed with its window; S6 closed by code (no dispatch); S7 has a dispatch that carries no scope
        calls.clear()
        holder["stages"] = {"S5": {"status": "completed"}, "S6": {"status": "completed"}, "S7": {"status": "completed"}}
        holder["dispatches"] = {"dS5": {"stage": "S5", "status": "accepted", "scope": ["TC-1"]}, "dS7": {"stage": "S7", "status": "accepted", "scope": []}}
        said = reopen({"words": "new text", "at": "t"})
        check_eq("F3b: the window of S5 is still invalidated", [(c[0], (c[1] or {}).get("dispatch_ids")) for c in calls][1:], [("invalidate", ["dS5"])])
        note = driver.state["gate_note"]["A"]
        check("F3b: the line and the top of gate A name EVERY completed stage nothing could set aside, in words",
              all(w in said and w in note for w in ("run (S6)", "triage (S7)", "made from the old text")) and "automation" not in note, said + " || " + note)
        # (c) a restart after the invalidate: the window is `stale` now, S5 is pending, S6 and S7 still stand
        calls.clear()
        holder["stages"] = {"S5": {"status": "pending"}, "S6": {"status": "completed"}, "S7": {"status": "completed"}}
        holder["dispatches"]["dS5"]["status"] = "stale"
        holder["decisions"]["g"]["status"] = "stale"
        driver.state.pop("gate_note", None)
        reopen({"words": "new text", "at": "t", "reopened": True, "invalidated": True})
        check_eq("F3c: a restart records nothing twice", calls, [])
        check("F3c: and still names S6 and S7, and not the stage that was set aside", "run (S6)" in driver.state["gate_note"]["A"]
              and "triage (S7)" in driver.state["gate_note"]["A"] and "automation" not in driver.state["gate_note"]["A"])
    finally:
        harness.cleanup(root)


def k7e_a_ticket_rework_finished_through_the_restart_route_is_complete() -> None:
    """F4: the R12 restart route is `wait_existing_job` on a registered dispatch this driver never launched; the ticket
    re-run of S2/S3 must close COMPLETE there too (the plan baseline is re-captured), while every other rework still does not."""
    root, task_root, env, ticket, _controller = gate_a_story(decided=True)
    try:
        driver, _ = asked_driver(root, env, task_root, ticket)
        accept = {"on": False}
        stub = staged_driver(root, env, task_root, accept)
        stub.state = driver.state
        with contextlib.redirect_stdout(io.StringIO()):
            stub.take_ticket_answer("new text", "# q\n", "S0", "")
            stub.ticket_rework_step()
        dispatch_id = stub.started[0][2]
        check_eq("setup: the re-run is registered and left running (the driver 'died' here)", state_of(task_root)["dispatches"][dispatch_id]["status"], "running")
        fresh = driver_for(root, env, KEY)
        seen = []
        fresh.run_role = lambda stage, role, **kw: seen.append((stage, kw.get("complete"), (kw.get("rework") or {}).get("id"))) or ("", None)
        with contextlib.redirect_stdout(io.StringIO()):
            fresh.dispatch_action({"action": "wait_existing_job", "dispatch_id": dispatch_id})
        # X2-7: S2 has an acceptor (`acceptance_by`), so the author's re-run does not close the stage (None, never True: the controller refuses an
        # author's closing accept without the critic's record); the closing is the critic route's, which the loop enters next (checked below)
        check_eq("F4: finished through the restart route, the ticket re-run of S2 leaves the closing to the stage critic", seen, [("S2", None, dispatch_id)])
        # the stage stays `completed` from its first run, so no turn of the loop enters S2 again: the restart route itself runs the critic
        # route over the accepted re-run (`ticket_rerun_critic`, AR-25/AR-28) - and only over an accepted one, once
        seen.clear()
        with contextlib.redirect_stdout(io.StringIO()):
            fresh.ticket_rerun_critic(dispatch_id)
            check_eq("F4: a re-run still running gets no critic yet", seen, [])
            accept_dispatch(task_root, dispatch_id, False)
            fresh.ticket_rerun_critic(dispatch_id)
            fresh.ticket_rerun_critic("no-such-dispatch")
        check_eq("F4: the accepted re-run of S2 is followed by the stage critic's route (one critic call, whose finish closes)",
                 [(stage, callable(done), rework) for stage, done, rework in seen], [("S2", True, None)])
        record = state_of(task_root)["dispatches"][dispatch_id]
        check_eq("F4 control: any other rework record still answers False (the `rework_of` rule is unchanged)",
                 (fresh.completion_for("S2", record["role"], dict(record, repair_cause=None)), fresh.completion_for("S4", "qa-case-designer", {"rework_of": "x", "repair_cause": "ticket_changed"})), (False, False))
    finally:
        harness.cleanup(root)


SCENARIOS = [
    k6_k7_new_text_reworks_s2_then_s3_then_reopens_gate_a,
    k7b_gate_a_not_decided_is_not_reopened,
    k7c_the_reworks_own_edges,
    k7d_the_reopen_sets_aside_the_late_work_and_names_what_it_cannot,
    k7e_a_ticket_rework_finished_through_the_restart_route_is_complete,
]


def main() -> None:
    """No argument: every scenario. Names (prefixes, `k7c k10`): only those - the one a mutation of the driver is checked
    by (builder-rules 7a), with the same checks; an argument that names nothing is an error, never a silent green."""
    wanted = sys.argv[1:]
    chosen = [s for s in SCENARIOS if not wanted or any(s.__name__.startswith(prefix) for prefix in wanted)]
    if not chosen:
        sys.exit(f"test_story_run_freshness: no scenario starts with {wanted}; they are: " + ", ".join(s.__name__ for s in SCENARIOS))
    run_scenarios([], chosen)
    harness.finish("test_story_run_freshness_k6_k7")


# split: runner piece 1
if __name__ == "__main__":
    main()
