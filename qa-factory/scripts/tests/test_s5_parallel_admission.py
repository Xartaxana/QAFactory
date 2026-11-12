#!/usr/bin/env python3
"""t-1937 TR3-4: the controller side of parallel S5 windows (admission, resume, stage record, close fields).

Keys (spec t-1937, node TR3-4): the scheduler's flag, disjoint scopes and the cap admit a second S5 window dispatch; everything
else keeps the old refusal text byte for byte; a stopped window resumes beside its siblings; the stage stays `running` while a
window runs; `open_windows` lifts the "no role to close it" refusal only for real other windows; `stage_complete: true` is refused
beside a running window. Controller in-process on a temp project, no driver, no thread; not named `test_controller_*` on purpose
(those files are CI's). The fixture is the one of `test_controller_rework_scope.gate_a_task`, with four automate rows.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import SCRIPTS, check, check_eq, check_in, check_not_in, cleanup, finish, mark_project, s5_window_form, temp_project  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import controller as CTRL  # noqa: E402
from controller import Controller  # noqa: E402

import test_controller_rework_scope as R  # noqa: E402  (plan_row, evidence)
import test_controller_state as BASE  # noqa: E402  (accept_stage, seed_plan, bind_gate_a, add_override)

CASES = ("TC-1", "TC-2", "TC-3", "TC-4")
OLD_TEXT = "sequential task already has an active dispatch: {ids}. Finish it first (`story_step.py finish`)"


def story(cap=None, drop_config=False):
    """A project accepted through S0..S4 with an approved plan of four automate cases; one case per S5 window; the config's
    `dispatch.parallel_windows` is `cap` (None: the template's own)."""
    root = temp_project("qa-s5par-")
    mark_project(root)
    c = Controller(root)
    c.apply("initialize", {"scope": list(CASES), "source_revision": "src-1", "known_paths": {"root": str(root)}, "idempotency_key": "init"})
    for number in range(5):
        BASE.accept_stage(c, root, f"S{number}")
    BASE.seed_plan(root, [R.plan_row(i, "automate") for i in range(1, 5)])
    (root / "state" / "story-case-links.json").write_text(json.dumps({"links": [
        {"case_id": case, "version": "cv_1"} for case in CASES]}), encoding="utf-8")       # seed_plan pins TC-1 only
    decision = {"id": "gate-a", "gate": "A", "action": "approve", "status": "approved", "authorization_source": "human",
                "source_revision": "src-1", "scope": list(CASES), "input_revision": "src-1", "idempotency_key": "gate-a"}
    c.apply("decision", BASE.bind_gate_a(root, decision))
    path = root / "qa-factory" / "config.json"
    config = json.loads(path.read_text(encoding="utf-8"))
    config.setdefault("execution", {})["s5_window_cases"] = 1
    if cap is not None:
        config.setdefault("dispatch", {})["parallel_windows"] = cap
    path.write_text(json.dumps(config), encoding="utf-8")
    if drop_config:
        path.unlink()
    return root, c


def request(did, role, scope, **extra):
    return dict({"id": did, "stage": "S5", "role": role, "scope": list(scope), "input_hash": "h", "budget": {}, "known_paths": {},
                 "idempotency_key": did}, **extra)


def send(c, root, did, role, scope, **extra):
    with s5_window_form(c, root):
        return c.apply("dispatch", request(did, role, scope, **extra))


def refusal(call):
    try:
        call()
    except Exception as exc:  # noqa: BLE001
        return str(exc)
    return ""


def rec(c, did):
    return c.state()["dispatches"][did]


def stage(c):
    return c.state()["stages"]["S5"]


def accept(c, root, did, **extra):
    body = {"id": did, "status": "accepted", "stage_complete": False, "idempotency_key": did + "-ok",
            "evidence_refs": [R.evidence(root, did + ".txt")]}
    body.update(extra)
    return c.apply("accept", body)


def with_two(cap=None):
    """root, controller with W1 (TC-1) running; W2 (TC-2) admitted beside it."""
    root, c = story(cap)
    send(c, root, "W1", "qa-automator", ["TC-1"], parallel_window=True)
    return root, c


# --- admission ------------------------------------------------------------------------------------------------------------

def parallel_s5_windows_admitted_disjoint():
    root, c = with_two()
    try:
        send(c, root, "W2", "qa-automator", ["TC-2"], parallel_window=True)
        # the checks below the clause still run on an admitted dispatch: a scope outside the approved one is refused as ever
        text = refusal(lambda: send(c, root, "W4", "qa-automator", ["TC-9"], parallel_window=True))
        check("an admitted dispatch meets the approved-scope check (not the active-dispatch one)",
              bool(text) and "active dispatch" not in text, text)
        send(c, root, "W3", "qa-code-critic", ["TC-3"], parallel_window=True)       # the critic of another window is a window dispatch too
        state = c.state()
        check_eq("three disjoint flagged S5 windows run at once (cap 3, the template default)",
                 sorted(d for d, r in state["dispatches"].items() if r["status"] == "running" and d.startswith("W")), ["W1", "W2", "W3"])
        check_eq("the flag is on the record", rec(c, "W2").get("parallel_window"), True)
        check_eq("the stage is running", stage(c)["status"], "running")
    finally:
        cleanup(root)


def overlapping_scope_refused():
    root, c = with_two()
    try:
        old = OLD_TEXT.format(ids="W1")
        check_eq("a window sharing a case is refused with the old text, byte for byte",
                 refusal(lambda: send(c, root, "Wx", "qa-automator", ["TC-1", "TC-2"], parallel_window=True)), old)
        send(c, root, "W2", "qa-automator", ["TC-2"], parallel_window=True)
        c.record_return("W2", "digest", "agent-2")
        check_eq("W2 is returned_unaccepted", rec(c, "W2")["status"], "returned_unaccepted")
        text = refusal(lambda: send(c, root, "Wy", "qa-automator", ["TC-2", "TC-3"], parallel_window=True))
        check_eq("a returned sibling is not counted but its scope is checked: the overlap is refused", text, old)
        send(c, root, "Wz", "qa-automator", ["TC-3"], parallel_window=True)
        check_eq("a returned sibling does not count toward the cap: the disjoint one runs", rec(c, "Wz")["status"], "running")
        # direct, on the shapes `apply` cannot make: empty or missing scope on a running dispatch is not disjoint
        mine = request("Wq", "qa-automator", ["TC-4"], parallel_window=True)
        for label, scope in (("empty", []), ("missing", None), ("not a list", "TC-1"), ("a non-string case", [1])):
            running = {"id": "Wr", "stage": "S5", "role": "qa-automator", "status": "running"}
            if scope is not None:
                running["scope"] = scope
            check_eq(f"a running dispatch with a {label} scope is not disjoint", c._window_beside_running(mine, c.state(), [running]), False)
        check_eq("an empty scope of the new dispatch is refused", c._window_beside_running(dict(mine, scope=[]), c.state(), []), False)
    finally:
        cleanup(root)


def plan_dispatch_runs_alone():
    root, c = with_two()
    try:
        plan = request("P1", "qa-automator", list(CASES), purpose="s5_plan", parallel_window=True)
        check_eq("a flagged PLAN dispatch beside a running window is refused with the old text",
                 refusal(lambda: c.apply("dispatch", plan)), OLD_TEXT.format(ids="W1"))
        running_plan = {"id": "P0", "stage": "S5", "role": "qa-automator", "scope": ["TC-1"], "status": "running",
                        "request_binding": {"purpose": "s5_plan"}}
        check_eq("a flagged window beside a running PLAN is not admitted",
                 c._window_beside_running(request("Wn", "qa-automator", ["TC-2"], parallel_window=True), c.state(), [running_plan]), False)
        check_eq("the same request beside a running window is admitted (control)",
                 c._window_beside_running(request("Wn", "qa-automator", ["TC-2"], parallel_window=True), c.state(), [rec(c, "W1")]), True)
    finally:
        cleanup(root)


def non_s5_refused_while_window_runs():
    root, c = with_two()
    try:
        old = OLD_TEXT.format(ids="W1")
        other_stage = dict(request("S4x", "qa-case-critic", ["TC-2"], parallel_window=True), stage="S4")
        check_eq("a flagged S4 dispatch is refused with the old text", refusal(lambda: c.apply("dispatch", other_stage)), old)
        check_eq("a flagged S5 dispatch of another role is refused with the old text",
                 refusal(lambda: send(c, root, "Wk", "qa-scout", ["TC-2"], parallel_window=True)), old)
        s6 = {"id": "R1", "stage": "S6", "role": "qa-runner", "scope": ["TC-3"], "status": "running"}
        check_eq("a flagged window beside a running S6 dispatch is not admitted",
                 c._window_beside_running(request("Wn", "qa-automator", ["TC-2"], parallel_window=True), c.state(), [s6]), False)
    finally:
        cleanup(root)


def count_over_cap_refused():
    root, c = with_two(cap=2)
    try:
        send(c, root, "W2", "qa-automator", ["TC-2"], parallel_window=True)
        check_eq("the third window over a cap of 2 is refused with the old text",
                 refusal(lambda: send(c, root, "W3", "qa-automator", ["TC-3"], parallel_window=True)), OLD_TEXT.format(ids="W1, W2"))
    finally:
        cleanup(root)
    root, c = with_two(cap=1)
    try:
        check_eq("cap 1: even the first sibling is refused", refusal(lambda: send(c, root, "W2", "qa-automator", ["TC-2"], parallel_window=True)),
                 OLD_TEXT.format(ids="W1"))
    finally:
        cleanup(root)
    root, c = story(drop_config=True)
    try:
        check_eq("no config file: the reader's default 3", c._parallel_cap(), 3)
        (root / "qa-factory").mkdir(exist_ok=True)
        (root / "qa-factory" / "config.json").write_text("{not json", encoding="utf-8")
        check_eq("an unreadable config: the reader's default 3, no raise", c._parallel_cap(), 3)
        (root / "qa-factory" / "config.json").write_text(json.dumps({"dispatch": {"parallel_windows": 0}}), encoding="utf-8")
        check_eq("a bad value reads the default too", c._parallel_cap(), 3)
        # F8: the file is read by `config_contract.read_config_file` (the one reader): a byte-order mark is tolerated, an empty file is the default
        (root / "qa-factory" / "config.json").write_bytes(b"\xef\xbb\xbf" + json.dumps({"dispatch": {"parallel_windows": 2}}).encode("utf-8"))
        check_eq("a config with a BOM is read like the driver reads it (cap 2)", c._parallel_cap(), 2)
        (root / "qa-factory" / "config.json").write_text("", encoding="utf-8")
        check_eq("an empty config: the default 3, no raise", c._parallel_cap(), 3)
    finally:
        cleanup(root)


def no_flag_keeps_old_refusal_text():
    root, c = with_two()
    try:
        old = OLD_TEXT.format(ids="W1")
        check_eq("no flag: the old refusal, byte for byte", refusal(lambda: send(c, root, "W2", "qa-automator", ["TC-2"])), old)
        for label, value in (("the string 'true'", "true"), ("the integer 1", 1), ("False", False), ("None", None)):
            check_eq(f"parallel_window is {label}, not literally True: the old refusal",
                     refusal(lambda: send(c, root, "W2", "qa-automator", ["TC-2"], parallel_window=value)), old)
        send(c, root, "C1", "qa-code-critic", ["TC-2"], parallel_window=True)
        text = refusal(lambda: send(c, root, "W9", "qa-automator", ["TC-3"]))
        check_in("a running critic keeps the --needs-author door in the old text", "--needs-author", text)
    finally:
        cleanup(root)


def skill_road_second_start_keeps_old_refusal():
    """The skill and conductor roads never pass `--parallel-window`: `story_step start` without it builds a request with no key,
    and with it a request with the key (read from the real parser)."""
    import story_step
    seen = {}
    real = story_step.start
    story_step.start = lambda args: seen.update(flag=getattr(args, "parallel_window", "absent")) or 0
    try:
        base = ["story_step.py", "start", "--task", "T", "--stage", "S5", "--role", "qa-automator"]
        old_argv, sys.argv = sys.argv, base
        story_step.main()
        check_eq("start without the flag: parallel_window is False", seen["flag"], False)
        sys.argv = base + ["--parallel-window"]
        story_step.main()
        check_eq("start with the flag: parallel_window is True", seen["flag"], True)
    finally:
        story_step.start, sys.argv = real, old_argv
    root, c = with_two()
    try:
        check_eq("the skill road's second start (a request with no key) meets the old refusal",
                 refusal(lambda: send(c, root, "W2", "qa-automator", ["TC-2"])), OLD_TEXT.format(ids="W1"))
    finally:
        cleanup(root)


def find_active_narrows_by_disjoint_case():
    import execution_request as ER
    root, c = with_two()
    try:
        send(c, root, "W2", "qa-automator", ["TC-2"], parallel_window=True)
        found = ER.find_active_dispatch(root.parent, task=root.name, cases=["TC-2"])
        check_eq("two running windows: a run for TC-2 belongs to W2", found[2]["id"], "W2")
        found = ER.find_active_dispatch(root.parent, task=root.name, cases=["TC-1"])
        check_eq("and a run for TC-1 to W1", found[2]["id"], "W1")
        both = refusal(lambda: ER.find_active_dispatch(root.parent, task=root.name, cases=["TC-1", "TC-2"]))
        check_in("a run spanning both windows is still refused, naming --dispatch", "--dispatch", both)
    finally:
        cleanup(root)


# --- resume ---------------------------------------------------------------------------------------------------------------

def resume_beside_running_window():
    root, c = with_two()
    try:
        send(c, root, "W2", "qa-automator", ["TC-2"], parallel_window=True)
        c.store.commit("stage_transition", {"stage": "S5", "status": "running", "digest": "", "dispatch_id": "W2", "agent_id": "ag-2"}, "bind-W2")
        c.apply("checkpoint", c.build_checkpoint_request("W2", "paused", "the person is asked", None))
        check_eq("W2 is stopped, W1 runs", (rec(c, "W2")["status"], rec(c, "W1")["status"]), ("paused", "running"))
        c.apply("resume", c.build_resume_request("W2"))
        check_eq("a stopped window resumes beside its running sibling (no flag on the road)",
                 (rec(c, "W2")["status"], rec(c, "W1")["status"]), ("running", "running"))
        # a window whose cases are held by a running sibling is not resumed beside it (two dispatches never share a case)
        mine = dict(rec(c, "W2"))
        check_eq("overlap on resume is not admitted", c._window_beside_running(dict(mine, scope=["TC-1"]), c.state(), [rec(c, "W1")], flagged=False), False)
    finally:
        cleanup(root)
    root, c = with_two(cap=1)
    try:
        c.store.commit("stage_transition", {"stage": "S5", "status": "running", "digest": "", "dispatch_id": "W1", "agent_id": "ag-1"}, "bind-W1")
        c.apply("checkpoint", c.build_checkpoint_request("W1", "paused", "stop", None))
        send(c, root, "W2", "qa-automator", ["TC-2"])        # alone now: no sibling, no flag needed
        text = refusal(lambda: c.apply("resume", c.build_resume_request("W1")))
        check_in("over the cap the resume keeps the old refusal", "sequential task already has an active dispatch: W2", text)
    finally:
        cleanup(root)


def resume_non_s5_refused():
    root = temp_project("qa-s5par-resume-")
    try:
        art = root / "qa-factory" / "artifacts" / "QA-R1"
        art.mkdir(parents=True)
        (art / "pipeline.json").write_text(json.dumps({"task": "QA-R1", "stages": {"S0": {"status": "running"}}}), encoding="utf-8")
        c = Controller(art)
        c.apply("initialize", {"scope": ["TC-1"], "source_revision": "src-1", "known_paths": {"root": str(art)}, "idempotency_key": "init"})
        c.apply("dispatch", {"id": "A", "stage": "S0", "role": "qa-scout", "scope": ["TC-1"], "input_hash": "x", "budget": {},
                             "known_paths": {}, "idempotency_key": "dA"})
        c.store.commit("stage_transition", {"stage": "S0", "status": "running", "digest": "", "dispatch_id": "A", "agent_id": "ag"}, "bind-A")
        c.apply("checkpoint", c.build_checkpoint_request("A", "blocked", "waits for the person", None))
        c.apply("dispatch", {"id": "B", "stage": "S0", "role": "qa-scout", "scope": ["TC-1"], "input_hash": "x", "budget": {},
                             "known_paths": {}, "idempotency_key": "dB", "parallel_window": True})
        text = refusal(lambda: c.apply("resume", c.build_resume_request("A")))
        check_in("a non-S5 resume beside a running dispatch keeps the refusal", "sequential task already has an active dispatch: B", text)
    finally:
        cleanup(root)


# --- the stage record -----------------------------------------------------------------------------------------------------

def accept_w1_leaves_s5_running_while_w2_runs():
    root, c = with_two()
    try:
        send(c, root, "W2", "qa-automator", ["TC-2"], parallel_window=True)
        accept(c, root, "W1")
        check_eq("W1 accepted, W2 running: S5 stays running with W2's id", (stage(c)["status"], stage(c).get("dispatch_id")), ("running", "W2"))
        accept(c, root, "W2")
        check_eq("the last one to stop lowers the stage as it always did", stage(c)["status"], "pending")
        # a checkpoint of a window beside a running one keeps the stage running as well
        send(c, root, "W3", "qa-automator", ["TC-3"], parallel_window=True)
        send(c, root, "W4", "qa-automator", ["TC-4"], parallel_window=True)
        c.apply("checkpoint", c.build_checkpoint_request("W3", "paused", "asked", None))
        check_eq("a stop beside a running window keeps S5 running", (stage(c)["status"], stage(c).get("dispatch_id")), ("running", "W4"))
    finally:
        cleanup(root)


def stage_pending_beside_blocked_sibling():
    """t-2121 Q5 (TR4-10 item 10.5, a pin, no behaviour change): the last RUNNING window accepts beside a `blocked` sibling -> the stage
    reads `pending` while the sibling stays `blocked`; `next` answers `prepare_stage` when a later accepted dispatch of the stage hides the
    stopped sibling as history (the first scenario, the usual case), and the sibling's `resume_checkpoint` when the stopped window is
    the NEWEST dispatch of the stage (state-exits.md, the row after `stages.S5.status = running`)."""
    root, c = with_two()
    try:
        send(c, root, "W2", "qa-automator", ["TC-2"], parallel_window=True)
        c.apply("checkpoint", c.build_checkpoint_request("W1", "blocked", "waits for the person", None))
        check_eq("W1 checkpointed beside running W2: the stage reads running (W2's id)",
                 (rec(c, "W1")["status"], stage(c)["status"], stage(c).get("dispatch_id")), ("blocked", "running", "W2"))
        accept(c, root, "W2")
        check_eq("W2 accepted, W1 still blocked: the stage reads pending, the sibling stays blocked",
                 (stage(c)["status"], rec(c, "W1")["status"], rec(c, "W2")["status"]), ("pending", "blocked", "accepted"))
        # the stopped window W1 is OLDER than the accepted W2: `next` reads it as history (a later accepted dispatch of the stage), so
        # the stage is prepared again and `stage_S5` settles the stopped dispatch at entry (S5_SETTLE_RUNNING)
        check_eq("the stopped window is older than the accepted one: next offers the stage, not the resume",
                 c.next_action().get("action"), "prepare_stage")
    finally:
        cleanup(root)
    root, c = with_two()
    try:
        send(c, root, "W2", "qa-automator", ["TC-2"], parallel_window=True)
        c.apply("checkpoint", c.build_checkpoint_request("W2", "blocked", "waits for the person", None))
        accept(c, root, "W1")
        check_eq("the stopped window is the NEWER one: the stage reads pending, W2 blocked",
                 (stage(c)["status"], rec(c, "W2")["status"], rec(c, "W1")["status"]), ("pending", "blocked", "accepted"))
        action = c.next_action()
        check_eq("... and next offers its resume_checkpoint",
                 (action.get("action"), action.get("dispatch_id")), ("resume_checkpoint", "W2"))
    finally:
        cleanup(root)


def replay_serial_journal_identical():
    root, c = story()
    try:
        for n, case in enumerate(CASES, 1):
            send(c, root, f"S{n}", "qa-automator", [case])
            if n == 3:
                c.apply("checkpoint", c.build_checkpoint_request("S3", "paused", "asked", None))
            else:
                accept(c, root, f"S{n}")
        events = c.store.read()
        now = json.dumps(CTRL.projection(events), sort_keys=True, default=str)
        real = CTRL.stage_entry_beside_running
        CTRL.stage_entry_beside_running = lambda state, d, entry: entry       # the reducer as it was before this node
        try:
            before = json.dumps(CTRL.projection(events), sort_keys=True, default=str)
        finally:
            CTRL.stage_entry_beside_running = real
        check_eq("a journal with no two running dispatches replays byte-identical to the reducer without the node", now, before)
        check("and it really had several S5 records", len([r for r in c.state()["dispatches"].values() if r.get("stage") == "S5"]) >= 4)
    finally:
        cleanup(root)


# --- close fields ---------------------------------------------------------------------------------------------------------

def open_windows_lifts_refusal():
    root, c = story()
    try:
        send(c, root, "C2", "qa-code-critic", ["TC-2"])
        accept(c, root, "C2")
        send(c, root, "C1", "qa-code-critic", ["TC-1"])
        send(c, root, "C3", "qa-code-critic", ["TC-3"], parallel_window=True)
        accept(c, root, "C3")                                   # the other windows' critics are in; only C1's bare false would strand S5
        send(c, root, "C4", "qa-code-critic", ["TC-4"], parallel_window=True)
        accept(c, root, "C4")
        text = refusal(lambda: accept(c, root, "C1"))
        check_in("without the field the refusal stands", "leaves S5 with no role to close it", text)
        accept(c, root, "C1", open_windows=["TC-2"])
        check_eq("with open_windows naming another real window the same accept is recorded", rec(c, "C1")["status"], "accepted")
        check_eq("and the field is on the record", rec(c, "C1").get("open_windows"), ["TC-2"])
    finally:
        cleanup(root)


def open_windows_bad_name_refused():
    root, c = story()
    try:
        send(c, root, "C2", "qa-code-critic", ["TC-2"])
        send(c, root, "C1", "qa-code-critic", ["TC-1"], parallel_window=True)
        for label, value, needle in (("an unknown case", ["TC-9"], "TC-9"), ("this dispatch's own case", ["TC-1"], "own cases"),
                                     ("one good and one bad", ["TC-2", "TC-9"], "TC-9"), ("an empty list", [], "non-empty"),
                                     ("not a list", "TC-2", "non-empty"), ("a blank case", [" "], "non-empty")):
            text = refusal(lambda: accept(c, root, "C1", open_windows=value))
            check_in(f"{label}: refused, naming the windows", "the other windows of S5 are: TC-2", text)
            check_in(f"{label}: and what is wrong", needle, text)
            check_eq(f"{label}: nothing recorded", rec(c, "C1")["status"], "running")
        text = refusal(lambda: accept(c, root, "C1", open_windows=["TC-2"], unresolved="could_not_judge", reason="words"))
        check_in("not together with unresolved", "not unresolved", text)
    finally:
        cleanup(root)


def bare_not_complete_on_true_last_refused():
    root, c = story()
    try:
        for case, did in (("TC-2", "C2"), ("TC-3", "C3"), ("TC-4", "C4")):
            send(c, root, did, "qa-code-critic", [case])
            accept(c, root, did)
        send(c, root, "C1", "qa-code-critic", ["TC-1"])
        text = refusal(lambda: accept(c, root, "C1"))
        check_in("the silent false on the truly last window is refused", "leaves S5 with no role to close it", text)
        text = refusal(lambda: accept(c, root, "C1", open_windows=["TC-1"]))
        check_in("naming its own window does not lift it", "own cases", text)
        check_eq("still running", rec(c, "C1")["status"], "running")
    finally:
        cleanup(root)


def own_round_last_window_same_as_today():
    """A recorded pre-change expectation: the last window's own round, `--not-complete` with no other open window and no
    field, meets exactly the refusal text the controller wrote before this node."""
    root, c = story()
    try:
        for case, did in (("TC-2", "C2"), ("TC-3", "C3"), ("TC-4", "C4")):
            send(c, root, did, "qa-code-critic", [case])
            accept(c, root, did)
        send(c, root, "C1", "qa-code-critic", ["TC-1"])
        expected = (f"accepting C1 with stage_complete: false leaves S5 with no role to close it — pass stage_complete: "
                    f"true, name the unresolved work with its reason, or checkpoint the dispatch if the work is not done "
                    f"(`controller.py --task-root {c.store.root} --operation checkpoint --dispatch C1 --status incomplete "
                    f"--reason \"<what is left>\" --brief`)")
        check_eq("the refusal text is the one of before the node", refusal(lambda: accept(c, root, "C1")), expected)
    finally:
        cleanup(root)


def stage_complete_refused_while_other_s5_running():
    root, c = with_two()
    try:
        send(c, root, "W2", "qa-automator", ["TC-2"], parallel_window=True)
        text = refusal(lambda: accept(c, root, "W1", stage_complete=True))
        check_in("the backstop names the running dispatch", "W2", text)
        check_in("the backstop names the word", "close beside a running window", text)
        check_in("the door is --not-complete --open-windows with its cases", "--not-complete --open-windows TC-2", text)
        check_in("the person's word route is named", "waiver.py", text)
        check_eq("nothing recorded", rec(c, "W1")["status"], "running")
        BASE.add_override(root, "S5", "close beside a running window", "accept - the person's word (fixture)")
        text = refusal(lambda: accept(c, root, "W1", stage_complete=True))
        check_not_in("a recorded word passes the backstop (other refusals may remain)", "close beside a running window", text)
    finally:
        cleanup(root)


def flags_reach_the_controller():
    """The two CLI flags: `finish --open-windows a,b` becomes the accept field; `controller rework --parallel-window` the request key."""
    import story_step
    seen = {}
    real = story_step.finish
    story_step.finish = lambda args: seen.update(open=getattr(args, "open_windows", "absent")) or 0
    old_argv = sys.argv
    try:
        sys.argv = ["story_step.py", "finish", "--task", "T", "--dispatch-id", "D", "--digest", "x", "--not-complete", "--open-windows", "TC-1,TC-2"]
        story_step.main()
        check_eq("finish --open-windows is parsed", seen["open"], "TC-1,TC-2")
        sys.argv = ["story_step.py", "finish", "--task", "T", "--dispatch-id", "D", "--digest", "x"]
        story_step.main()
        check_eq("and absent by default", seen["open"], None)
    finally:
        story_step.finish, sys.argv = real, old_argv
    root, c = story()
    try:
        send(c, root, "W1", "qa-automator", ["TC-1"])
        accept(c, root, "W1")
        flagged = c.build_rework_request("S5", "qa-automator", ["TC-1"], "mend it", parallel_window=True)
        plain = c.build_rework_request("S5", "qa-automator", ["TC-1"], "mend it")
        check_eq("rework with the flag carries parallel_window True", flagged.get("parallel_window"), True)
        check_not_in("rework without it carries no key", "parallel_window", json.dumps(plain))
        packet = c.prepare({"dispatch_id": "W1", "outputs": ["W1.txt"], "stage_complete": False, "open_windows": ["TC-2"]})
        check_eq("prepare carries open_windows into the accept request", packet["accept_request"].get("open_windows"), ["TC-2"])
    finally:
        cleanup(root)


def main():
    parallel_s5_windows_admitted_disjoint()
    overlapping_scope_refused()
    plan_dispatch_runs_alone()
    non_s5_refused_while_window_runs()
    count_over_cap_refused()
    no_flag_keeps_old_refusal_text()
    skill_road_second_start_keeps_old_refusal()
    find_active_narrows_by_disjoint_case()
    resume_beside_running_window()
    resume_non_s5_refused()
    accept_w1_leaves_s5_running_while_w2_runs()
    stage_pending_beside_blocked_sibling()
    replay_serial_journal_identical()
    open_windows_lifts_refusal()
    open_windows_bad_name_refused()
    bare_not_complete_on_true_last_refused()
    stage_complete_refused_while_other_s5_running()
    own_round_last_window_same_as_today()
    flags_reach_the_controller()
    finish("test_s5_parallel_admission")


if __name__ == "__main__":
    main()
