#!/usr/bin/env python3
"""An accepted stage is never un-completed, and an S5/S6 scope is never typed.

Both rules come out of one run. TP1-15045 reached the doorstep of gate A and stopped:
`stage_done --stage S3 --status running` lowered a stage the controller had already accepted,
`--status done` then refused it, and nothing could close the story. The same file's
`issubset` check let an empty S5/S6 scope through from the start. The real journal of
that run is replayed here, so the fix is measured against the state the person actually saw.
"""
import contextlib
import hashlib
import io
import json
import shutil
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import (SCRIPTS, check, check_eq, check_in, check_not_in, cleanup, finish, mark_project, run_mode,  # noqa: E402
                     s5_window_form, temp_project)

sys.path.insert(0, str(SCRIPTS))
import event_store as ES  # noqa: E402
import guard_pre_tool as G  # noqa: E402
import hooklib  # noqa: E402
import stage_done  # noqa: E402
import waiver  # noqa: E402
from controller import Controller, projection, repair_rounds  # noqa: E402
from event_store import EventStore, StateConflict  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_controller_state as BASE  # noqa: E402  (accept_stage/seed_plan/bind_gate_a fixtures)

# The journal of the real run, copied into the repository as a fixture so the replay does not
# reach into somebody's live project. 34 events: S3 and S4 accepted, then a `stage_transition
# S3 running` for the plan repair, then `revise_plan`.
REAL_JOURNAL = Path(__file__).resolve().parent / "fixtures" / "events-TP1-15045.jsonl"


def evidence(root, name, content="receipt"):
    path = root / name
    path.write_text(content, encoding="utf-8")
    return {"path": name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def managed_task(root, ticket="QA-1"):
    """A controller task under a project root, the way stage_done.py expects to find one."""
    task = root / "qa-factory" / "artifacts" / ticket
    task.mkdir(parents=True)
    mark_project(root)
    (task / "pipeline.json").write_text(json.dumps({"ticket": ticket, "stages": {}, "gates": {}}),
                                        encoding="utf-8")
    return task


def plan_row(index, disposition):
    """One starter-policy plan row that names its disposition, the way 0.7.5 plans do."""
    return {"id": f"TS-{index}", "impact": "low", "likelihood": "low", "confidence": "high",
            "risk_rationale": "bounded", "risk_source_refs": ["R-1"],
            "risk_policy_revision": "factory-starter-v1", "coverage_refs": ["R-1"],
            "unknowns": [], "verification_depth": "low", "required_scenarios": [f"TC-{index}"],
            "test_level_rationale": "unit", "design_review_required": False,
            "bounded_reversible": True, "disposition": disposition}


def gate_a_task(root, scope=("TC-1",)):
    """A task accepted through S0..S4 with an approved plan, ready for S5."""
    mark_project(root)
    c = Controller(root)
    c.apply("initialize", {"scope": list(scope), "source_revision": "src-1",
                           "known_paths": {"root": str(root)}, "idempotency_key": "init"})
    for number in range(5):
        BASE.accept_stage(c, root, f"S{number}")
    BASE.seed_plan(root, [plan_row(1, "automate")])
    decision = {"id": "gate-a", "gate": "A", "action": "approve", "status": "approved",
                "authorization_source": "human", "source_revision": "src-1", "scope": list(scope),
                "input_revision": "src-1", "idempotency_key": "gate-a"}
    c.apply("decision", BASE.bind_gate_a(root, decision))
    return c


# --- an accepted stage is reworked, never lowered ----------------------------------------

def reducer_keeps_an_accepted_stage():
    root = temp_project("qa-rework-reducer-")
    try:
        c = Controller(root)
        c.apply("initialize", {"scope": ["TC-1"], "source_revision": "r",
                               "known_paths": {"root": str(root)}, "idempotency_key": "init"})
        for number in range(4):
            BASE.accept_stage(c, root, f"S{number}")
        c.store.commit("stage_transition",
                       {"task": "QA-1", "stage": "S3", "status": "running",
                        "digest": "S3 plan repair: sync test-plan.md with plan JSON"},
                       "stage:s3-running", project=c.project)
        stage = c.state()["stages"]["S3"]
        check_eq("a running transition on an accepted stage does not lower it",
                 stage["status"], "completed")
        check_eq("it is recorded as rework instead", (stage.get("rework"), stage.get("rework_status")),
                 (True, "running"))
        check_in("with the reason the caller gave", "plan repair", stage.get("rework_reason", ""))
        pipeline = json.loads((root / "pipeline.json").read_text(encoding="utf-8"))
        check_eq("and the projection still shows the stage done",
                 pipeline["stages"]["S3"]["status"], "done")
        check_eq("with the rework visible to a reader", pipeline["stages"]["S3"].get("rework"), True)
        # Closing the stage again clears the mark rather than accumulating it: `update` on the
        # pipeline entry never removes a key by itself.
        c.store.commit("stage_transition",
                       {"task": "QA-1", "stage": "S3", "status": "done", "digest": "plan repaired"},
                       "stage:s3-done", project=c.project)
        pipeline = json.loads((root / "pipeline.json").read_text(encoding="utf-8"))
        check_not_in("a stage closed again no longer claims rework",
                     "rework", json.dumps(pipeline["stages"]["S3"]))
    finally:
        cleanup(root)


def stage_done_refuses_to_un_complete():
    root = temp_project("qa-rework-stage-done-")
    old = hooklib._PROJECT_ROOT_CACHE
    try:
        task = managed_task(root)
        hooklib._PROJECT_ROOT_CACHE = root
        c = Controller(task)
        c.apply("initialize", {"scope": ["TC-1"], "source_revision": "r",
                               "known_paths": {"root": str(root)}, "idempotency_key": "init"})
        for number in range(4):
            BASE.accept_stage(c, task, f"S{number}")
        import io
        import contextlib
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            code = stage_done.run("QA-1", "S3", "running", "qa-test-strategist", "plan repair", True)
        check_eq("stage_done refuses to reopen an accepted stage", code, stage_done.EXIT_BAD_ARGS)
        check_in("and names SendMessage as the way to rework it", "SendMessage", err.getvalue())
        check_in("and revise_plan as the way to record a changed plan",
                 "revise_plan", err.getvalue())
        check_not_in("without ever advising --status running again",
                     "--status running`", err.getvalue().replace("--status running would", ""))
        check_eq("the stage is untouched by the refusal",
                 c.state()["stages"]["S3"]["status"], "completed")
        # A person's word passes it, like every other block in this factory.
        pipeline = json.loads((task / "pipeline.json").read_text(encoding="utf-8"))
        waiver.apply_stage_override(pipeline, "S3", "already accepted",
                                    "reopen it, I want the plan redone", waiver.now_iso())
        (task / "pipeline.json").write_text(json.dumps(pipeline), encoding="utf-8")
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            code = stage_done.run("QA-1", "S3", "running", "qa-test-strategist", "plan repair", True)
        check_eq("a person's recorded word passes the refusal", code, 0)
        check_in("and says whose word it was", "person's word", err.getvalue())
        check_eq("and even then the accepted stage is not lowered",
                 c.state()["stages"]["S3"]["status"], "completed")
    finally:
        hooklib._PROJECT_ROOT_CACHE = old
        cleanup(root)


def real_journal_replays_clean():
    root = temp_project("qa-rework-replay-")
    try:
        task = root / "TP1-15045"
        (task / "state").mkdir(parents=True)
        shutil.copyfile(REAL_JOURNAL, task / "state" / "events.jsonl")
        events = EventStore(task).read()
        check_eq("the real journal is the one the person's run left", len(events), 34)
        state = projection(events)
        check_eq("replaying it leaves S3 accepted", state["stages"]["S3"]["status"], "completed")
        check_eq("with the plan repair recorded as rework", state["stages"]["S3"].get("rework"), True)
        check_eq("and S4 still accepted", state["stages"]["S4"]["status"], "completed")
        action = Controller._next_action_for_state(state)
        check("the story is no longer sent back to prepare S3",
              not (action.get("action") == "prepare_stage" and action.get("stage") == "S3"), action)
        check_eq("it is waiting for the person at gate A", action.get("action"), "await_gate")
    finally:
        cleanup(root)


def recover_repairs_internal_state():
    root = temp_project("qa-rework-recover-")
    try:
        c = Controller(root)
        c.apply("initialize", {"scope": ["TC-1"], "source_revision": "r",
                               "known_paths": {"root": str(root)}, "idempotency_key": "init"})
        for number in range(4):
            BASE.accept_stage(c, root, f"S{number}")
        # What 0.7.4 left on disk: the journal is intact, the projections are not.
        pipeline = json.loads((root / "pipeline.json").read_text(encoding="utf-8"))
        pipeline["stages"]["S3"]["status"] = "running"
        (root / "pipeline.json").write_text(json.dumps(pipeline), encoding="utf-8")
        result = c.recover()
        pipeline = json.loads((root / "pipeline.json").read_text(encoding="utf-8"))
        check_eq("recover puts the accepted stage back without asking anyone",
                 pipeline["stages"]["S3"]["status"], "done")
        check_in("and reports exactly what it repaired", "S3", json.dumps(result["reprojected_stages"]))
        check_eq("its old contract still holds", isinstance(result.get("revision"), int), True)
        check_eq("a second recover has nothing left to repair", Controller(root).recover()["reprojected_stages"], [])

        # The detector, for a state written by an older or foreign writer: running with no
        # active dispatch and its own last dispatch accepted as stage_complete.
        stranded = {"stages": {"S3": {"status": "running"}},
                    "dispatches": {"d": {"id": "d", "stage": "S3", "status": "accepted",
                                         "stage_complete": True}}}
        fixes = Controller.stage_repairs(stranded)
        check_eq("a stage stranded running with an accepted receipt is repairable", len(fixes), 1)
        check_eq("and the repair names its evidence", fixes[0]["dispatch_id"], "d")
        never = {"stages": {"S3": {"status": "running"}},
                 "dispatches": {"d": {"id": "d", "stage": "S3", "status": "accepted",
                                      "stage_complete": False}}}
        check_eq("a stage that was never completed is not invented as completed",
                 Controller.stage_repairs(never), [])
        busy = {"stages": {"S3": {"status": "running"}},
                "dispatches": {"d": {"id": "d", "stage": "S3", "status": "running"}}}
        check_eq("a story with work in flight is left alone", Controller.stage_repairs(busy), [])

        # The repair is a journalled fact, not a quiet rewrite of a cache.
        c.store.commit("state_repair", {"fixes": [{"kind": "stage_completed", "stage": "S2",
                                                   "dispatch_id": "dS2", "reason": "recover"}],
                                        "reason": "recover repaired internal state"},
                       "state_repair:test", project=c.project)
        check_eq("a journalled state_repair completes the stage it names",
                 c.state()["stages"]["S2"]["status"], "completed")
        check_eq("and says it was the factory that repaired it",
                 c.state()["stages"]["S2"].get("repaired_by_recover"), True)
    finally:
        cleanup(root)


def owner_check_no_longer_teaches_the_deadlock():
    message = G.owner_check.__doc__ or ""
    root = temp_project("qa-rework-guard-")
    try:
        task = root / "qa-factory" / "artifacts" / "QA-1"
        (task / "work").mkdir(parents=True)
        mark_project(root)
        (task / "pipeline.json").write_text(json.dumps({"stages": {"S5": {"status": "done"}}}),
                                            encoding="utf-8")
        target = task / "work" / "automation-manifest.json"
        event = {"tool_name": "Edit", "cwd": str(root),
                 "tool_input": {"file_path": str(target)}, "transcript_path": "/main.jsonl"}
        old = hooklib._PROJECT_ROOT_CACHE
        hooklib._PROJECT_ROOT_CACHE = root
        try:
            blocked = ""
            err = io.StringIO()
            try:
                with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
                    G.owner_check(event, {})
            except SystemExit:
                blocked = "raised"
            except Exception as exc:  # block() may raise its own carrier
                blocked = str(exc)
        finally:
            hooklib._PROJECT_ROOT_CACHE = old
        text = err.getvalue() or blocked
        check("the guard still refuses a repair from outside the owning role", bool(blocked), message[:80])
        check_in("the refusal names SendMessage as the way on (TP1-15045)", "SendMessage", text)
        check_not_in("the refusal does not teach `--status running.` (the TP1-15045 deadlock)", "--status running.", text)
    finally:
        cleanup(root)


# --- the S5/S6 scope comes from the plan --------------------------------------------------

def scope_is_computed_and_an_empty_one_is_refused():
    root = temp_project("qa-scope-")
    try:
        c = gate_a_task(root)
        computed = c.stage_scope("S5")
        check_eq("the controller computes the S5 scope from the approved plan",
                 computed["scope"], ["TC-1"])
        check_eq("naming the disposition it came from", computed["by_disposition"]["automate"], ["TC-1"])
        packet = c.prepare({"stage": "S5", "role": "qa-automator"})
        check_eq("prepare offers the same scope so nobody types it",
                 packet["stage_scope"]["scope"], ["TC-1"])
        check_eq("and builds the dispatch request with it",
                 packet["dispatch_request"]["scope"], ["TC-1"])
        refused = ""
        try:
            with s5_window_form(c, root):       # SC1-14 B1b: the plan order is not what this key is about
                c.apply("dispatch", {"id": "empty-s5", "stage": "S5", "role": "qa-automator",
                                     "scope": [], "input_hash": "h", "budget": {}, "known_paths": {},
                                     "idempotency_key": "empty-s5"})
        except StateConflict as exc:
            refused = str(exc)
        check_in("an empty S5 scope is refused", "empty scope", refused)
        check_in("and the refusal names the cases it expected", "TC-1", refused)
        check_in("and points at the operation that computes it", "stage-scope", refused)
        check_in("and at the way a person's word passes it", "waiver.py", refused)
        # A person's word passes it, recorded the same way every other stage block is.
        pipeline_path = root / "pipeline.json"
        pipeline = json.loads(pipeline_path.read_text(encoding="utf-8"))
        waiver.apply_stage_override(pipeline, "S5", "empty scope",
                                    "run S5 empty, the automation is out of this story",
                                    waiver.now_iso())
        pipeline_path.write_text(json.dumps(pipeline), encoding="utf-8")
        with s5_window_form(c, root):
            c.apply("dispatch", {"id": "empty-s5-passed", "stage": "S5", "role": "qa-automator",
                                 "scope": [], "input_hash": "h", "budget": {}, "known_paths": {},
                                 "idempotency_key": "empty-s5-passed"})
        check_eq("a person's recorded word passes the empty-scope block",
                 c.state()["dispatches"]["empty-s5-passed"]["status"], "running")
    finally:
        cleanup(root)


def s6_scope_follows_the_execution_kind():
    root = temp_project("qa-scope-s6-")
    try:
        c = Controller(root)
        c.apply("initialize", {"scope": ["TC-1", "TC-2", "TC-3"], "source_revision": "r",
                               "known_paths": {"root": str(root)}, "idempotency_key": "init"})
        BASE.seed_plan(root, [plan_row(index, disposition) for index, disposition in
                              enumerate(("automate", "manual-agent", "manual-human"), start=1)])
        state = c.state()
        check_eq("S5 takes only the automate rows",
                 c.stage_scope("S5", state)["scope"], ["TC-1"])
        check_eq("a manual S6 block takes only the manual-agent rows",
                 c.stage_scope("S6", state, "manual")["scope"], ["TC-2"])
        check_eq("an automation S6 block takes the automated instances",
                 c.stage_scope("S6", state, "automation")["scope"], ["TC-1"])
        check_eq("S6 without a declared kind covers both",
                 c.stage_scope("S6", state)["scope"], ["TC-1", "TC-2"])
        check_eq("manual-human is nobody's dispatch",
                 "TC-3" in c.stage_scope("S6", state)["scope"], False)
        check_eq("a stage whose scope is not derived says so",
                 c.stage_scope("S4", state)["derived"], False)
    finally:
        cleanup(root)


def gate_a_cannot_approve_nothing():
    root = temp_project("qa-scope-gate-")
    try:
        c = Controller(root)
        c.apply("initialize", {"scope": ["TC-1"], "source_revision": "src-1",
                               "known_paths": {"root": str(root)}, "idempotency_key": "init"})
        for number in range(5):
            BASE.accept_stage(c, root, f"S{number}")
        BASE.seed_plan(root, [plan_row(1, "automate")])
        # The real shape of the mistake: the reviewed plan is recorded with an empty scope.
        c.apply("revise_plan", {"scope": [], "plan_revision": "plan-2",
                                "reason": "scope recorded empty by mistake",
                                "idempotency_key": "revise"})
        decision = {"id": "gate-a", "gate": "A", "action": "approve", "status": "approved",
                    "authorization_source": "human", "source_revision": "src-1", "scope": [],
                    "input_revision": "plan-2", "idempotency_key": "gate-a"}
        decision.update(c.gate_inputs())
        refused = ""
        try:
            c.apply("decision", decision)
        except StateConflict as exc:
            refused = str(exc)
        check_in("gate A refuses an empty scope under a plan with rows", "empty scope", refused)
        check_in("naming the rows it read", "TS-1", refused)
        check_in("and the operation that records the reviewed scope", "revise_plan", refused)
    finally:
        cleanup(root)


# --- the repair cap does not depend on a counter ------------------------------------------

def repair_cap_counts_dispatches():
    def critic(scope=("TC-1",), **extra):
        return dict({"stage": "S4", "role": "qa-case-critic", "scope": list(scope),
                     "status": "accepted"}, **extra)

    window = critic()
    check_eq("one dispatch is not a repair round", repair_rounds({"a": critic()}, window), 0)
    three = {f"d{i}": critic() for i in range(3)}
    check_eq("three dispatches of one window are two repair rounds",
             repair_rounds(three, window), 2)
    three["retry"] = critic(parent_retry="d0")
    check_eq("a resumed checkpoint is not another round", repair_rounds(three, window), 2)
    three["old"] = critic(status="superseded")
    check_eq("superseded work is not counted twice", repair_rounds(three, window), 2)
    # S5 deliberately runs several windows of the same stage and role; window three is not
    # repair round three, which is why the key is the budget scope and not stage/role.
    windows = {f"w{i}": critic(scope=(f"TC-{i}",)) for i in range(4)}
    check_eq("another window of the same role spends nobody's cap",
             repair_rounds(windows, critic(scope=("TC-9",))), 0)

    root = temp_project("qa-repair-cap-")
    try:
        c = gate_a_task(root)
        # The pilot's blind spot: the host recorded no counters at all, so cumulative_budget
        # returned None for every metric and the cap simply did not exist.
        for index in range(3):
            with s5_window_form(c, root):
                c.apply("dispatch", {"id": f"a{index}", "stage": "S5", "role": "qa-automator",
                                     "scope": ["TC-1"], "input_hash": "h", "budget": {},
                                     "known_paths": {}, "idempotency_key": f"a{index}"})
            c.apply("accept", {"id": f"a{index}", "status": "accepted", "stage_complete": False,
                               "evidence_refs": [evidence(root, f"a{index}.txt")],
                               "idempotency_key": f"a{index}-ok"})
        check_eq("no counter was ever recorded for that scope",
                 c.state()["cumulative_counters"], {})
        refused = ""
        try:
            c.apply("dispatch", {"id": "a3", "stage": "S5", "role": "qa-automator",
                                 "scope": ["TC-1"], "input_hash": "h", "budget": {},
                                 "known_paths": {}, "idempotency_key": "a3"})
        except StateConflict as exc:
            refused = str(exc)
        check_in("the cap still holds without one", "repair round", refused)
        check_in("and names the person's way past it", "waiver.py", refused)
        pipeline_path = root / "pipeline.json"
        pipeline = json.loads(pipeline_path.read_text(encoding="utf-8"))
        waiver.apply_stage_override(pipeline, "S5", "repair round",
                                    "one more round, the fix is one line", waiver.now_iso())
        pipeline_path.write_text(json.dumps(pipeline), encoding="utf-8")
        c.apply("dispatch", {"id": "a3", "stage": "S5", "role": "qa-automator",
                             "scope": ["TC-1"], "input_hash": "h", "budget": {},
                             "known_paths": {}, "idempotency_key": "a3"})
        check_eq("a person's word buys the round", c.state()["dispatches"]["a3"]["status"], "running")
    finally:
        cleanup(root)


# --- a telemetry file never costs a committed event ---------------------------------------

def telemetry_race_never_loses_an_event():
    check_eq("a hook telemetry aggregate is a shared file",
             ES.shared_file("/p/qa-factory/state/telemetry/hook-1234.aggregate.json"), True)
    check_eq("a windows path is read the same way",
             ES.shared_file(r"C:\p\qa-factory\state\telemetry\hook-1.jsonl"), True)
    check_eq("the task's own state is not shared", ES.shared_file("/p/state/controller.json"), False)

    attempts = []

    def flaky():
        attempts.append(1)
        if len(attempts) < 3:
            raise PermissionError(13, "in use", "/p/qa-factory/state/telemetry/hook-1.aggregate.json")
        return "done"

    check_eq("a bounded retry rides out the hook that held it", ES.retry_shared(flaky), "done")
    owned = PermissionError(13, "in use", "/p/state/controller.json")

    def fails():
        raise owned

    raised = ""
    try:
        ES.retry_shared(fails)
    except PermissionError as exc:
        raised = str(exc.filename)
    check_eq("a file we do own still fails loudly", raised, "/p/state/controller.json")

    root = temp_project("qa-telemetry-")
    import dashboard_refresh
    original = dashboard_refresh.refresh_for_task
    try:
        # Lock boundary: the refresh takes the very lock the lifecycle commit holds, so it can
        # only succeed once that lock is released. (Legacy TP2-2406: a render inside the
        # lock stalled dispatch and recover behind "an active state writer".)
        boundary = []

        def unlocked(task_root):
            with ES.EventStore(Path(task_root)).lock(wait_seconds=0):
                boundary.append("free")
            return {"status": "current"}
        dashboard_refresh.refresh_for_task = unlocked
        c = Controller(root)
        c.apply("initialize", {"scope": ["TC-1"], "source_revision": "r",
                               "known_paths": {"root": str(root)}, "idempotency_key": "init"})
        check_eq("dashboard refresh runs after the lifecycle writer lock is released",
                 boundary, ["free"])
        check_eq("and the event it followed is committed", c.state().get("source_revision"), "r")

        def held(task_root):
            raise PermissionError(13, "in use",
                                  str(Path(task_root) / "state/telemetry/hook-9.aggregate.json"))
        dashboard_refresh.refresh_for_task = held
        # The same request again: an idempotent replay re-runs the refresh, now over a held file.
        c.apply("initialize", {"scope": ["TC-1"], "source_revision": "r",
                               "known_paths": {"root": str(root)}, "idempotency_key": "init"})
        check_eq("the lifecycle event survives a held telemetry file",
                 c.state().get("source_revision"), "r")
        deferred = json.loads((root / "state" / "dashboard-deferred.json").read_text(encoding="utf-8"))
        check_eq("and the deferred dashboard is owned by the factory, not the person",
                 deferred.get("owner"), "factory")

        def other(task_root):
            raise PermissionError(13, "locked", str(Path(task_root) / "state/controller.json"))
        dashboard_refresh.refresh_for_task = other
        propagated = False
        try:
            c.apply("dispatch", {"id": "d", "stage": "S0", "role": "qa-scout", "scope": ["TC-1"],
                                 "input_hash": "h", "budget": {}, "known_paths": {},
                                 "idempotency_key": "d"})
        except StateConflict:
            propagated = True
        check("a permission failure on our own state is still reported", propagated)
    finally:
        dashboard_refresh.refresh_for_task = original
        cleanup(root)


# --- the window-budget seam ---------------------------------------------------------

def boundary_notice_is_optional():
    saved = sys.modules.pop("window_budget", None)
    try:
        stub = types.ModuleType("window_budget")
        stub.boundary_notice = lambda task, stage: f"window almost spent; {stage} is closed"
        sys.modules["window_budget"] = stub
        check_in("a stage closed as done prints the window notice", "window almost spent",
                 stage_done.print_boundary_notice("QA-1", "S4", "done"))
        check_eq("a stage that did not close prints nothing",
                 stage_done.print_boundary_notice("QA-1", "S4", "running"), "")
        stub.boundary_notice = lambda task, stage: ""
        check_eq("and an empty notice stays silent",
                 stage_done.print_boundary_notice("QA-1", "S4", "done"), "")

        def broken(task, stage):
            raise RuntimeError("no budget file yet")
        stub.boundary_notice = broken
        check_eq("a broken window budget never fails a closed stage",
                 stage_done.print_boundary_notice("QA-1", "S4", "done"), "")
        sys.modules["window_budget"] = types.ModuleType("empty")
        check_eq("nor does one that ships without the function",
                 stage_done.print_boundary_notice("QA-1", "S4", "done"), "")
    finally:
        sys.modules.pop("window_budget", None)
        if saved is not None:
            sys.modules["window_budget"] = saved


# --- CX1-11: the approved scope is PINNED CASES, compared by KEYS (t-996, t-1069) ------------------------
# Expectations come from the invariants of the node (I1 no refusal by spelling, I2 never-pinned is never dispatched,
# I3 the approved side is never widened at a read, I5 a store written before the node reads as it did), not from the
# output of the code (FR-58). The fixture is the live run's shape: TC-003 is held by two areas, so the index keys it
# `<area>/TC-003` and a bare TC-003 names both.
def refusal(call):
    try:
        call()
    except (ValueError, StateConflict) as exc:
        return str(exc)
    return ""


KEYED = "TP2-2406"
AREAS = {1: ["session-feedback"], 2: ["session-feedback"], 3: ["feedback-api", "session-feedback"], 4: ["session-feedback"]}
APPROVED_KEYS = ["TC-001", "TC-002", "TC-004", "feedback-api/TC-003", "session-feedback/TC-003"]
ALL_BARE = ["TC-001", "TC-002", "TC-003", "TC-004"]


def pin_case_files(root, areas):
    """Pinned CaseVersions as the live run has them: `state/case-versions/TC-n/cv_<hash>.md` and the links to them."""
    links = []
    for number in sorted(areas):
        for area in areas[number]:
            body = (f"---\nid: TC-{number:03d}\ntitle: case {number}\narea: {area}\nstatus: Draft\n"
                    f"plan_row: TS-{number}\n---\nPlan row: TS-{number}\n").encode("utf-8")
            digest = hashlib.sha256(body).hexdigest()
            rel = f"state/case-versions/TC-{number:03d}/{area}-cv_{digest[:20]}.md"
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            (root / rel).write_bytes(body)
            links.append({"case_id": f"TC-{number:03d}", "version": f"cv_{digest[:20]}", "content_hash": digest,
                          "path": rel, "area": area})
    (root / "state").mkdir(parents=True, exist_ok=True)
    (root / "state" / "story-case-links.json").write_text(json.dumps({"links": links}), encoding="utf-8")


def keyed_story(areas=AREAS, gate=True):
    """S0..S4 accepted (a case critic over TC-001 at S4), the scope recorded by `revise_plan`, gate A approved."""
    from harness import temp_dir
    parent = temp_dir("qa-scope-keys-")
    root = parent / KEYED
    root.mkdir()
    c = Controller(root)
    c.apply("initialize", {"scope": [], "source_revision": "src-1", "known_paths": {"root": str(root)},
                           "idempotency_key": "init"})
    BASE.seed_plan(root, [plan_row(n, "automate") for n in sorted(areas)])
    pin_case_files(root, areas)
    c.apply("revise_plan", {"scope": ALL_BARE, "plan_revision": "sha256:plan-1", "reason": "the pinned cases",
                            "idempotency_key": "revise"})
    for stage in ("S0", "S1", "S2", "S3", "S4"):
        for role in (("qa-case-designer", "qa-case-critic") if stage == "S4" else ("qa-worker",)):
            c.apply("dispatch", {"id": f"d{stage}-{role}", "stage": stage, "role": role,
                                 "scope": ["TC-001"] if role == "qa-case-critic" else [], "input_hash": stage,
                                 "budget": {}, "known_paths": {}, "idempotency_key": f"dispatch-{stage}-{role}"})
            if role != "qa-case-designer":  # E-B11: the closing accept of S2-S4 needs the acceptor's record (no-op for S0/S1)
                BASE.record_stage_acceptance(root, stage, f"d{stage}-qa-case-designer" if stage == "S4" else "")
            c.apply("accept", {"id": f"d{stage}-{role}", "status": "accepted", "stage_complete": role != "qa-case-designer",
                               "evidence_refs": [BASE.evidence_ref(root, f"{stage}-{role}.txt", stage)],
                               "idempotency_key": f"accept-{stage}-{role}"})
    if gate:
        decision = {"id": "gate-a", "gate": "A", "action": "approve", "status": "approved",
                    "authorization_source": "human", "source_revision": "src-1", "scope": list(c.state()["scope"]),
                    "input_revision": "sha256:plan-1", "idempotency_key": "gate-a"}
        c.apply("decision", BASE.bind_gate_a(root, decision))
    return root, parent, c


def window(scope, name="w"):
    return {"id": name, "stage": "S5", "role": "qa-automator", "scope": scope, "input_hash": "h",
            "budget": {}, "known_paths": {}}


def verdict(c, scope, state=None):
    """'' when the dispatch scope check passes, the refusal text otherwise."""
    with run_mode("driver"):        # SC1-14 B1b: the scope keys are judged here, not the plan order (a desktop process asks for a plan first)
        return refusal(lambda: c.validate("dispatch", window(scope), state or c.state()))


def scope_is_written_and_compared_by_keys():
    root, parent, c = keyed_story()
    try:
        state = c.state()
        check_eq("revise_plan writes the index keys: a bare number two areas hold is every one of its keys (F-1)",
                 state["scope"], APPROVED_KEYS)
        for member in (["TC-001"], ["session-feedback/TC-001"], ["TC-001", "TC-003"], ["feedback-api/TC-003"],
                       [" TC-001"], ["session-feedback\\TC-001"], ["TC-003"], APPROVED_KEYS):
            check_eq(f"I1: {member} is never refused by its spelling", verdict(c, member), "")
        for member in (["billing/TC-001"], ["TC-010"], [KEYED], ["feedback-api/TC-001"]):
            message = verdict(c, member)
            check_in(f"I2: {member!r} is refused (no TypeError)", "scope expansion requires plan/gate revision: ", message)
            check_in(f"and the refusal names the door {member!r}", "--operation revise_plan", message)
        canonical, refused = c._outside_approved([None, 4, ["TC-001"], "", "TC-001"], state["scope"])
        check_eq("E4: a member that is no string is refused on its own line, never a TypeError (the schema comes first)",
                 (canonical, [str(m) for m, _ in refused]), (["TC-001"], ["None", "4", "['TC-001']", ""]))
        check_in("a refused member is named, the passing one is not", "billing/TC-001;",
                 verdict(c, ["TC-001", "billing/TC-001"]))
        # I2/C3-12: a bare number two areas hold, only one area approved, is refused (never the intersection)
        narrow = dict(state, scope=["feedback-api/TC-003"])
        check_in("one key of two approved is not approval of the bare id", "scope expansion", verdict(c, ["TC-003"], narrow))
        check_eq("the approved key itself passes", verdict(c, ["feedback-api/TC-003"], narrow), "")
        check_in("and the other area's key does not", "session-feedback/TC-003", verdict(c, ["session-feedback/TC-003"], narrow))
        # I5: a store written before the node answers to its own spelling first (literal-equal passes), and the door
        # for a qualified request names the spelling the index keys
        bare = dict(state, scope=ALL_BARE)
        check_eq("a legacy bare store: bare TC-003 passes literally", verdict(c, ["TC-003"], bare), "")
        message = verdict(c, ["feedback-api/TC-003"], bare)
        check_in("a legacy bare store: a qualified key is refused", "scope expansion requires", message)
        check_in("and the refusal says how the index keys the stored id", "the approved scope holds TC-003, which the case "
                 "index keys as feedback-api/TC-003, session-feedback/TC-003 - record it in that spelling", message)
        ticket = dict(state, scope=[KEYED])
        check_eq("the 2406 store (the ticket key) answers to itself", verdict(c, [KEYED], ticket), "")
        check_in("and still refuses a case it does not hold", "scope expansion", verdict(c, ["TC-001"], ticket))
        # E13: the gate checks report first
        check_in("the Gate A checks still report before the scope", "Gate A decision required",
                 verdict(c, ["TC-042"], dict(state, source_revision="somebody-else")))
        check_not_in("an empty request scope is no scope expansion (the empty-window guard is behind it)",
                     "scope expansion", verdict(c, []))
        # E9: AT and BEYOND the list limit
        many = [f"x/TC-{n:03d}" for n in range(100, 121)]
        at, beyond = verdict(c, many[:20]), verdict(c, many)
        check("E9: 20 members are all named, no tail", all(m in at for m in many[:20]) and "in all" not in at, at[:200])
        check_in("E9: 21 members: the first 20 and the number", "(21 in all)", beyond)
        check_not_in("E9: the 21st is not listed", many[20] + ";", beyond)
    finally:
        cleanup(parent)


def dispatch_records_one_spelling_and_a_replay_meets_a_moved_index():
    root, parent, c = keyed_story()
    try:
        original = ["session-feedback/TC-001", "TC-003"]
        request = dict(window(original, "S5-qa-automator-1"), idempotency_key="w1")
        with s5_window_form(c, root):
            c.apply("dispatch", request)
        check_eq("M-3: the recorded scope is the approved keys, not the words of the request",
                 c.state()["dispatches"]["S5-qa-automator-1"]["scope"],
                 ["TC-001", "feedback-api/TC-003", "session-feedback/TC-003"])
        check_eq("the caller's own list is untouched (FR-45)", original, ["session-feedback/TC-001", "TC-003"])
        c.apply("dispatch", dict(window(original, "S5-qa-automator-1"), idempotency_key="w1"))
        check_eq("an identical replay is a replay: one event for it", len(c.state()["dispatches"]), 6 + 1)
        # F-2 (t-1084 P1): ANOTHER scope under the same id, nothing moved on disk: not a moved index
        other = refusal(lambda: c.apply("dispatch", dict(window(["TC-002"], "S5-qa-automator-1"), idempotency_key="w1")))
        check_in("F-2: another scope under a committed id keeps the head", "idempotency key reused with different inputs: dispatch "
                 "S5-qa-automator-1 was committed with scope [TC-001, feedback-api/TC-003, session-feedback/TC-003]", other)
        check_in("F-2: and says it is not a replay, with what the request names", "a different scope under the same id is not a "
                 "replay (this request names [TC-002])", other)
        check_in("F-2: and the door (revise_plan, a new gate A decision)", "--operation revise_plan", other)
        check_not_in("F-2: the index moved nothing, so it does not say it did", "case index moved", other)
        # E12: a second area now holds TC-001 (the index re-keys it); the story's approved scope still names TC-001
        pin_case_files(root, {**AREAS, 1: ["session-feedback", "billing"]})
        message = refusal(lambda: c.apply("dispatch", dict(window(original, "S5-qa-automator-1"), idempotency_key="w1")))
        check_in("N-2: a replay after the index moved keeps its refusal's head", "idempotency key reused", message)
        check_in("N-2: and names the door (revise_plan, a new gate A decision)", "--operation revise_plan", message)
        check_in("N-2: and the scope it was committed with", "TC-001, feedback-api/TC-003", message)
        check_in("F-2: and says the index moved, when the request was rewritten", "the case index moved since the dispatch "
                 "was committed (this request reads as [", message)
        check_not_in("F-2: and not that it is a different scope", "is not a replay", message)
        idle = dict(c.state(), dispatches={})        # the window above is still running: judge the scope, not the lock
        legacy = verdict(c, ["session-feedback/TC-001", "billing/TC-001"], idle)
        check_in("E12: both re-keyed members are refused", "session-feedback/TC-001, billing/TC-001", legacy)
        check_in("E12: with the spelling to record", "which the case index keys as billing/TC-001, session-feedback/TC-001", legacy)
        check_eq("E12: the bare request after the re-key still passes literally (the (d) hole, named and queued)",
                 verdict(c, ["TC-001"], idle), "")
    finally:
        cleanup(parent)


def a_respelled_dispatch_keeps_its_environment_stamp():
    """F-3 (t-1084): `_stamp_dispatch` keys the window by the request's scope, so it must read the CANONICAL scope - a
    window recorded under `TC-001` is the window of a request that spells the case `session-feedback/TC-001`. A lost
    stamp would not fail anything loudly (a courtesy stamp), hence this pin."""
    from controller import window_key
    root, parent, c = keyed_story()
    try:
        canonical = window_key({"stage": "S5", "scope": ["TC-001", "TC-002"]})
        respelled = ["session-feedback/TC-001", "TC-002"]
        check("the control: the window key of the words as sent is another window", window_key(window(respelled)) != canonical)
        # the stand's signal belongs to the window recorded under the approved keys, whoever asks
        c._window_stand_signal = lambda state, request: (
            {"summary": "evidence/runs/w1/run-1.json"} if window_key(request) == canonical else None)
        with s5_window_form(c, root):
            c.apply("dispatch", dict(window(respelled, "S5-qa-automator-1"), idempotency_key="w1"))
        recorded = c.state()["dispatches"]["S5-qa-automator-1"]
        check_eq("F-3: the respelled request is stamped environment, from the window's run summary",
                 (recorded.get("repair_cause"), recorded.get("repair_cause_source"), recorded["scope"]),
                 ("environment", "stand_signal:evidence/runs/w1/run-1.json", ["TC-001", "TC-002"]))
    finally:
        cleanup(parent)


def rework_reads_the_scope_by_keys_and_stamps_the_canonical_case():
    root, parent, c = keyed_story()
    try:
        def build(cases, **extra):
            return c.build_rework_request("S4", "qa-case-designer", cases, "the person's words", cause="test_defect", **extra)
        request = build(["session-feedback/TC-001"])
        check_eq("I1: a rework of a qualified spelling is built, scoped to the approved key", request["scope"], ["TC-001"])
        check_eq("with the case's own pin", [l["case_id"] for l in request["case_version_links"]], ["TC-001"])
        check_eq("M-3/N-3: the person's padded spelling is read after its strip", build([" TC-004 "])["scope"], ["TC-004"])
        both = build(["TC-003"])
        check_eq("a bare TC-003 is approved (both keys) and brings both pins", (both["scope"], len(both["case_version_links"])),
                 (["feedback-api/TC-003", "session-feedback/TC-003"], 2))
        for case in ("billing/TC-001", "TC-010", KEYED):
            check_in(f"I2: {case} is outside the approved scope", f"outside the approved scope: {case}", refusal(lambda: build([case])))
        stamped = build(["session-feedback/TC-001"], words_given=True).get("rerun_after") or {}
        check_eq("N-3: a person's rework of sf/TC-001 sets aside the review of TC-001", stamped.get("reviews"),
                 ["dS4-qa-case-critic"])
        # the door of the 2406 story: the stored scope is the ticket key, every asked case is pinned
        door = c._scope_door([KEYED], ["TC-004"])
        check_in("R3: the door names revise_plan and the pinned ids", "`--operation revise_plan` (scope = TC-001, TC-002, TC-003, TC-004;", door)
        check_eq("no door for a case nobody pinned", c._scope_door([KEYED], ["TC-004", "TC-010"]), "")
        check_eq("no door when the stored scope already holds a pinned case", c._scope_door(["TC-001", KEYED], ["TC-004"]), "")
        check_eq("no door for a story with no pin", Controller(parent)._scope_door([KEYED], ["TC-004"]), "")
        many = pin_many(root, 21)
        check_in("E9: 21 pinned ids: 20 and the number", "(21 in all)", c._scope_door([KEYED], many[:1]))
    finally:
        cleanup(parent)


def pin_many(root, count):
    pin_case_files(root, {n: ["session-feedback"] for n in range(1, count + 1)})
    return [f"TC-{n:03d}" for n in range(1, count + 1)]


def revise_plan_writes_keys_and_refuses_what_nobody_pinned():
    root, parent, c = keyed_story(gate=False)
    try:
        before = (c.state()["scope"], c.state()["revision"])

        def record(scope, key, **extra):
            return c.apply("revise_plan", dict({"scope": scope, "plan_revision": "sha256:plan-2", "reason": "the cases",
                                                "idempotency_key": key}, **extra))
        for member in ("TC-010", "TP2-9999", "TS-4", "billing/TC-001", "tc-004", None, 4, ["TC-004"], ""):
            message = refusal(lambda: record([member], f"bad-{member!r}"))
            check_in(f"R1: {member!r} is refused", "not pinned case ids", message)
        message = refusal(lambda: record(["billing/TC-001"], "bad-area"))
        check_in("R1 names the area the case is pinned in", "pinned in: session-feedback", message)
        check_in("R1 names the door with its command", "case_versions.py --task-root", message)
        check_in("R1 names the pinned ids", "TC-001, TC-002, TC-003, TC-004", message)
        message = refusal(lambda: record(["TC-004", "TC-010", "TC-011"], "bad-two"))
        check("m-2: ONE problem lists every unpinned member", message.count("not pinned case ids") == 1
              and "TC-010, TC-011" in message, message[:300])
        message = refusal(lambda: record(["TC-010"], "bad-both", extra=1))
        check_in("K1: a stray field and an invented member are ONE refusal", "2 problems", message)
        message = refusal(lambda: record([KEYED], "bad-own"))
        check_in("F-9/R2: the story's own key is refused with the S0 shape", "at S0 the scope is []", message)
        check_eq("nothing was written by the refusals", (c.state()["scope"], c.state()["revision"]), before)
        receipt = record(["TC-003", "session-feedback/TC-001", "TC-004"], "ok")
        check_eq("a bare two-area number is every key, a qualified one is its key, sorted",
                 c.state()["scope"], ["TC-001", "TC-004", "feedback-api/TC-003", "session-feedback/TC-003"])
        check_eq("m-13: the receipt (not the payload) lists what was written otherwise than spelt",
                 receipt.get("scope_expansions"), {"TC-003": ["feedback-api/TC-003", "session-feedback/TC-003"],
                                                   "session-feedback/TC-001": ["TC-001"]})
        check_not_in("and the payload carries none of it", "scope_expansions", json.dumps(c.store.read()[-1]["payload"]))
        record([], "empty")
        check_eq("an empty scope stays legal", c.state()["scope"], [])
        # M-1: an index that cannot be built is the story's files' fault, with the door
        broken = next((root / "state" / "case-versions" / "TC-001").glob("*.md"))
        broken.write_text(broken.read_text(encoding="utf-8").replace("id: TC-001", "id: TC-051"), encoding="utf-8")
        message = refusal(lambda: record(["TC-001"], "broken"))
        check_in("M-1: the index failure is named", "the case index cannot be built: ", message)
        check_in("M-1: with the files to fix and the command", "case_versions.py --task-root", message)
        try:
            c.validate("revise_plan", {"scope": ["TC-001"], "plan_revision": "x", "reason": "r"}, c.state())
        except StateConflict:
            klass = "StateConflict"
        except ValueError:
            klass = "ValueError"
        check_eq("M-1: the class says the story's files refused, not the call", klass, "StateConflict")
    finally:
        cleanup(parent)


def initialize_and_no_pin_stories_keep_their_old_world():
    from harness import temp_dir
    parent = temp_dir("qa-scope-init-")
    try:
        root = parent / KEYED
        root.mkdir()
        for variant in (KEYED, KEYED.lower(), f"  {KEYED} "):
            message = refusal(lambda: Controller(root).apply("initialize", {
                "scope": [variant], "source_revision": "s", "known_paths": {"root": str(root)}, "idempotency_key": "i"}))
            check_in(f"R2: initialize with {variant!r} is refused", "scope holds case ids", message)
        check_eq("nothing was written", Controller(root).state().get("source_revision"), None)
        Controller(root).apply("initialize", {"scope": [], "source_revision": "s", "known_paths": {"root": str(root)},
                                              "idempotency_key": "i"})
        Controller(root).apply("revise_plan", {"scope": ["TC-010", "TC-011"], "plan_revision": "p", "reason": "r",
                                               "idempotency_key": "r1"})
        check_eq("I5: with no pin revise_plan records what it is given (S0-S3)", Controller(root).state()["scope"],
                 ["TC-010", "TC-011"])
        check_in("F-9: the story's key is refused even before any pin",
                 "scope holds case ids", refusal(lambda: Controller(root).apply("revise_plan", {
                     "scope": [KEYED], "plan_revision": "p", "reason": "r", "idempotency_key": "r2"})))
        canonical, refused = Controller(root)._outside_approved(["TC-010", "TC-012"], Controller(root).state()["scope"])
        check_eq("an index with no entries: a member equal to a stored one passes, the rest is refused (literal, as main)",
                 (canonical, [m for m, _ in refused]), (["TC-010"], ["TC-012"]))
    finally:
        cleanup(parent)


def one_operation_count_for_ten_thousand_keys():
    """E8, as a count (FR-31): the index is walked ONCE and `matching` (a scan per member) never."""
    from contract import CaseIndex, scope_member_resolution

    class Counting(CaseIndex):
        passes = 0
        scans = 0

        def items(self):
            Counting.passes += 1
            return super().items()

        def matching(self, case_id, area=""):
            Counting.scans += 1
            return super().matching(case_id, area)
    index = Counting()
    members = []
    for area in range(10):
        for number in range(1, 1000):
            key = f"area-{area}/TC-{number:03d}"
            index[key] = {"case_id": f"TC-{number:03d}", "area": f"area-{area}", "version": "cv"}
            members.append(key)
    members += [f"area-0/TC-{n:03d}" for n in range(1, 11)]    # duplicates: each key once in the answer
    answers = scope_member_resolution(members, index)
    keys, refused = {key for _, found, _ in answers for key in found}, [(m, why) for m, _, why in answers if why]
    check_eq("E8: the index is read once and never scanned per member", (Counting.passes, Counting.scans), (1, 0))
    check_eq("E8: every key once, nothing refused", (len(keys), refused), (len(index), []))


def plan_rows_are_not_marked_dropped_for_a_respelling():
    root, parent, c = keyed_story(gate=False)
    try:
        c._capture_plan_baseline(c.state())
        pin_case_files(root, {**AREAS, 1: ["session-feedback", "billing"]})     # E12: the index re-keys TC-001
        c.apply("revise_plan", {"scope": ALL_BARE, "plan_revision": "sha256:plan-3", "reason": "re-key",
                                "idempotency_key": "rekey"})
        check_eq("M-4: a re-keyed member is not a dropped one", c._mark_plan_overrides("w"), [])
        c.apply("revise_plan", {"scope": ["TC-001", "TC-002", "TC-004", "feedback-api/TC-003"], "plan_revision": "sha256:plan-4",
                                "reason": "area dropped", "idempotency_key": "drop"})
        check_eq("M-4: an area dropped from a number is still a drop", c._mark_plan_overrides("w"), ["TS-3"])
    finally:
        cleanup(parent)


def main():
    scope_is_written_and_compared_by_keys()
    dispatch_records_one_spelling_and_a_replay_meets_a_moved_index()
    a_respelled_dispatch_keeps_its_environment_stamp()
    rework_reads_the_scope_by_keys_and_stamps_the_canonical_case()
    revise_plan_writes_keys_and_refuses_what_nobody_pinned()
    initialize_and_no_pin_stories_keep_their_old_world()
    one_operation_count_for_ten_thousand_keys()
    plan_rows_are_not_marked_dropped_for_a_respelling()
    reducer_keeps_an_accepted_stage()
    stage_done_refuses_to_un_complete()
    real_journal_replays_clean()
    recover_repairs_internal_state()
    owner_check_no_longer_teaches_the_deadlock()
    scope_is_computed_and_an_empty_one_is_refused()
    s6_scope_follows_the_execution_kind()
    gate_a_cannot_approve_nothing()
    repair_cap_counts_dispatches()
    telemetry_race_never_loses_an_event()
    boundary_notice_is_optional()
    finish("test_controller_rework_scope")


if __name__ == "__main__":
    main()
