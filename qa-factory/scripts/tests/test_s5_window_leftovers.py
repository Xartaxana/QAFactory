#!/usr/bin/env python3
"""TR4-10 part A1 (spec t-2222 items 10.1, 10.2, 10.4 as amended by section 9; AR-13, AR-15, AR-25, AR-28): the S5 window leftovers of
the driver. Fast: every case builds a bare `Driver` (`Driver.__new__`, fake readers, no run, no subprocess).

10.1  the claims of a completed S5 are freed, whichever finish closed it (D4 status set, D5 position):
      recovery_finishes_free_sibling_claims, live_mechanical_round_close_frees_every_s5_claim,
      stage_completed_beside_running_rework_frees_nothing, completed_beside_incomplete_frees_nothing,
      completed_beside_returned_frees_nothing, unreadable_stage_frees_nothing, n1_reads_nothing,
      closed_by_debt_then_rework_automator_not_refused
10.2  a window whose last round came back unaccepted is open (D1 old body, D2 N == 1 residual):
      returned_mechanical_round_keeps_window_open, later_accepted_dispatch_closes_returned_window, returned_plan_dispatch_ignored,
      returned_without_scope_is_unreadable, returned_then_released_by_person_is_open, two_windows_old_body_does_not_close_over_returned_round,
      n1_old_body_reads_nothing, no_returned_round_keeps_the_old_refusal
10.4  the ownership line on both bodies: ownership_line_on_old_body_when_n_not_1, n1_extra_unchanged, line_iff_guard_enforces

D3 (Lead option b) and its fix round (B1, N1-N5; the controller's `next` hides the return, so `stage_S5` itself resumes the role with the filed
words): returned_last_round_raises_resolve_return_naming_the_dispatch, returned_last_round_no_words_raises_packet,
returned_last_round_with_words_resumes_role_and_consumes_them, second_entry_after_resume_does_not_raise_again,
words_of_another_dispatch_are_not_used, returned_record_gone_at_resume_gives_the_old_refusal,
resumed_mechanical_round_of_last_window_completes_s5, resumed_mechanical_round_of_not_last_window_does_not,
resolve_return_action_equals_the_controllers, kept_young_empty_claim_gives_no_note, owed_branch_does_not_close_over_open_window.
Round 3 (B2: the resumed author's round completes by its repair cause, as the live road): resumed_test_defect_round_does_not_complete_s5,
resumed_round_with_no_cause_does_not_complete_s5; nit (a), Lead option A: record_gone_refusal_keeps_the_stage_boundary.
"""
import contextlib
import io
import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import SCRIPTS, check, check_eq, check_in, check_not_in, cleanup, finish, temp_project, use_project  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import config_contract  # noqa: E402
import controller as CT  # noqa: E402
import dispatch_identity as DI  # noqa: E402
import guard_pre_tool as G  # noqa: E402
import planning_contract as PC  # noqa: E402
import story_run as SR  # noqa: E402
import window_files as WF  # noqa: E402

ROOTS: list = []
CRIT, AUTH = "qa-code-critic", "qa-automator"


def rec(ident, scope, status="accepted", role=CRIT, **extra):
    return {"id": ident, "stage": "S5", "role": role, "status": status, "scope": scope, **extra}


def table(*rows) -> dict:
    return {r["id"]: r for r in rows}


def rig(windows=(), dispatches=None, stage_status=None, config=None, scope=True):
    """A bare Driver. `windows`: `(cases, critic_accepted)` pairs. `d.ctl` is the controller record the readers see (mutable)."""
    d = SR.Driver.__new__(SR.Driver)
    d.task, d.host, d.dry, d.state = "T-1", "claude", True, {}
    d.config = {} if config is None else config
    d.task_root = Path(tempfile.mkdtemp(prefix="tr410a1-"))
    ROOTS.append(d.task_root)
    d.state_dir = d.task_root / "state"
    wins = [{"scope": list(c), "accepted_by": ({AUTH: "x", CRIT: "x"} if acc else {AUTH: "x"})} for c, acc in windows]
    d.stage_scope = lambda stage, kind="": {"scope": [c for w in wins for c in w["scope"]] if scope else [], "windows": wins}
    d.ctl = {"dispatches": dispatches if dispatches is not None else {}}
    if stage_status is not None:
        d.ctl["stages"] = {"S5": {"status": stage_status}}
    d.controller_state = lambda: d.ctl
    return d


def finish_rig(**kw):
    d = rig(**kw)
    d.timed = lambda *a, **k: contextlib.nullcontext(type("L", (), {"dispatch": ""})())
    d.py = lambda *a, **k: (0, "")
    d.close_window_series = d.revoke_passes_of_dispatch = d.revoke_passes_of_dead = d.forget_resumes = lambda *a, **k: None
    return d


def quiet_finish(d, dispatch, role, complete):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        d.finish(dispatch, "digest", complete=complete, role=role, stage="S5")
    return out.getvalue()


def claimed(d) -> dict:
    return {w: WF.files_of(d.task_root, w) for w in ("S5|A", "S5|B")}


# --- 10.1 -----------------------------------------------------------------------------------------------------------------------------

def recovery_finishes_free_sibling_claims():
    """A recovery process finishes window B's saved critic `--not-complete`, then the last window A's critic `--complete`: B's claims
    must go with S5 (the finish of A frees A only through `s5_release_of_dispatch`; S5 is never entered again)."""
    d = finish_rig(dispatches=table(rec("cb", ["B"]), rec("ca", ["A"])), stage_status="running")
    WF.claim(d.task_root, "tests/a.spec.ts", "S5|A", "ca")
    WF.claim(d.task_root, "tests/b.spec.ts", "S5|B", "cb")
    quiet_finish(d, "cb", CRIT, False)
    check_eq("B's critic finished --not-complete (S5 running): nothing is freed", claimed(d), {"S5|A": ["tests/a.spec.ts"], "S5|B": ["tests/b.spec.ts"]})
    d.ctl["stages"] = {"S5": {"status": "completed"}}
    quiet_finish(d, "ca", CRIT, True)
    check_eq("A's critic finished --complete (S5 completed): every S5 claim is free, B's too", claimed(d), {"S5|A": [], "S5|B": []})
    # negative control: the per-window release alone (what ran before) leaves B's claim
    c = finish_rig(dispatches=table(rec("cb", ["B"]), rec("ca", ["A"])), stage_status="completed")
    WF.claim(c.task_root, "tests/a.spec.ts", "S5|A", "ca")
    WF.claim(c.task_root, "tests/b.spec.ts", "S5|B", "cb")
    c.config = {}
    with contextlib.redirect_stdout(io.StringIO()):
        c.s5_release_of_dispatch("ca")
    check_eq("control: s5_release_of_dispatch frees A only", claimed(c), {"S5|A": [], "S5|B": ["tests/b.spec.ts"]})


def live_mechanical_round_close_frees_every_s5_claim():
    d = finish_rig(dispatches=table(rec("ca", ["A"]), rec("m1", ["A"], role=AUTH), rec("cb", ["B"])), stage_status="completed")
    WF.claim(d.task_root, "tests/a.spec.ts", "S5|A", "m1")
    WF.claim(d.task_root, "tests/b.spec.ts", "S5|B", "cb")
    quiet_finish(d, "m1", AUTH, True)
    check_eq("the author's mechanical round closed S5: every claim is free", claimed(d), {"S5|A": [], "S5|B": []})


def _stopped_beside_completed(name, status):
    d = finish_rig(dispatches=table(rec("ca", ["A"]), rec("w1", ["B"], status=status, role=AUTH)), stage_status="completed")
    WF.claim(d.task_root, "tests/b.spec.ts", "S5|B", "w1")
    out = quiet_finish(d, "ca", CRIT, True)
    check_eq(name, WF.files_of(d.task_root, "S5|B"), ["tests/b.spec.ts"])
    check_not_in(name + ": and no note", "could not be released", out)


def stage_completed_beside_running_rework_frees_nothing():
    _stopped_beside_completed("completed beside a RUNNING rework: the claim stays", "running")


def completed_beside_incomplete_frees_nothing():
    for status in sorted(CT.STOPPED):
        _stopped_beside_completed(f"completed beside a `{status}` S5 dispatch: the claim stays", status)


def completed_beside_returned_frees_nothing():
    _stopped_beside_completed("completed beside a `returned_unaccepted` S5 dispatch: the claim stays", CT.RETURNED)


def unreadable_stage_frees_nothing():
    def run(name, ctl):
        d = finish_rig()
        d.ctl = ctl
        WF.claim(d.task_root, "tests/a.spec.ts", "S5|A", "x")
        quiet_finish(d, "ca", AUTH, True)
        check_eq(f"{name}: nothing is freed", WF.files_of(d.task_root, "S5|A"), ["tests/a.spec.ts"])
    run("stage status absent", {"dispatches": {}, "stages": {"S5": {}}})
    run("no stages key", {"dispatches": {}})
    run("stage status running", {"dispatches": {}, "stages": {"S5": {"status": "running"}}})
    run("stage status pending", {"dispatches": {}, "stages": {"S5": {"status": "pending"}}})
    run("stage status not a string", {"dispatches": {}, "stages": {"S5": {"status": 5}}})
    run("stage record not a mapping", {"dispatches": {}, "stages": {"S5": "completed"}})
    run("controller record empty (file absent or unreadable)", {})
    run("dispatches not a collection", {"dispatches": "x", "stages": {"S5": {"status": "completed"}}})
    run("an S5 dispatch whose status is not text", {"dispatches": {"d": rec("d", ["A"], status=["running"])}, "stages": {"S5": {"status": "completed"}}})
    d = finish_rig()
    d.controller_state = lambda: (_ for _ in ()).throw(OSError("gone"))
    WF.claim(d.task_root, "tests/a.spec.ts", "S5|A", "x")
    out = quiet_finish(d, "ca", AUTH, True)
    check_eq("a reader that raises: nothing is freed", WF.files_of(d.task_root, "S5|A"), ["tests/a.spec.ts"])
    check_in("... and one note, never a stop", "note: the test files of S5 could not be released (OSError)", out)


def n1_reads_nothing():
    d = finish_rig(config={"dispatch": {"parallel_windows": 1}}, stage_status="completed")
    reads = []
    d.controller_state = lambda: reads.append("controller_state") or (_ for _ in ()).throw(AssertionError("N == 1 reads nothing"))
    d.s5_open_windows = lambda *a, **k: reads.append("s5_open_windows") or (_ for _ in ()).throw(AssertionError("N == 1 reads nothing"))
    WF.claim(d.task_root, "tests/a.spec.ts", "S5|A", "x")
    try:
        d.s5_release_completed()
        raised = ""
    except AssertionError as exc:
        raised = str(exc)
    check_eq("n1: the sweep returns before any read", raised, "")
    check_eq("n1: no read function was called at all", reads, [])
    check_eq("n1: and touches no claim", WF.files_of(d.task_root, "S5|A"), ["tests/a.spec.ts"])
    # no claim file at all (N != 1): returns without reading; the reader is made to count and to throw
    c = rig()
    calls = []
    c.controller_state = lambda: calls.append("controller_state") or (_ for _ in ()).throw(AssertionError("no claim file: nothing is read"))
    c.s5_open_windows = lambda *a, **k: calls.append("s5_open_windows") or (_ for _ in ()).throw(AssertionError("no claim file: nothing is read"))
    check_eq("no claim file at all (N != 1): returns None", SR.Driver.s5_release_completed(c), None)
    check_eq("... and no read function was called", calls, [])


def kept_young_empty_claim_gives_no_note():
    """N5: the 'claim(s) left' note counts only the claims the release meant to free (a readable S5 claim) - a young empty claim that
    `release` keeps on purpose, and another stage's claim, are not 'left'."""
    d = finish_rig(dispatches=table(rec("ca", ["A"])), stage_status="completed")
    folder = d.task_root / WF.SUBDIR
    folder.mkdir(parents=True, exist_ok=True)
    (folder / ("0" * 40 + ".json")).write_text("", encoding="utf-8")      # a young empty claim: kept on purpose
    WF.claim(d.task_root, "tests/s7.spec.ts", "S7|X", "x")                 # another stage's claim: not S5's
    WF.claim(d.task_root, "tests/a.spec.ts", "S5|A", "ca")
    out = quiet_finish(d, "ca", CRIT, True)
    check_eq("the S5 claim is freed, the other two stay", (WF.files_of(d.task_root, "S5|A"), WF.files_of(d.task_root, "S7|X")), ([], ["tests/s7.spec.ts"]))
    check_not_in("no 'could not be released' note for kept claims", "could not be released", out)
    # control: a readable S5 claim that cannot be removed IS counted
    c = finish_rig(dispatches=table(rec("cz", ["Z"])), stage_status="completed")      # "ca" is unknown: no per-window release runs
    WF.claim(c.task_root, "tests/a.spec.ts", "S5|A", "ca")
    import window_files
    real = window_files.release_stage
    window_files.release_stage = lambda *a, **k: 0       # a release that frees nothing
    try:
        out = quiet_finish(c, "ca", CRIT, True)
    finally:
        window_files.release_stage = real
    check_in("control: one S5 claim left is noted", "(1 claim(s) left)", out)


def closed_by_debt_then_rework_automator_not_refused():
    """The batch row's literal test: S5 closed by the person's `debt` (the critic's finish at the gate answer), then the automator of a
    rework is not refused by the guard over a file an earlier window of the same stage claimed."""
    root = temp_project("qa-s5-leftovers-")
    use_project(root)
    try:
        task = root / "qa-factory" / "artifacts" / "T-1"
        (task / "state").mkdir(parents=True)
        cfg = json.loads((root / "qa-factory" / "config.json").read_text(encoding="utf-8"))
        a1, a2 = "S5-qa-automator-1", "S5-qa-automator-2"
        closed = table(rec(a1, ["TC-1"], role=AUTH), rec("S5-qa-code-critic-1", ["TC-1"]), rec("S5-qa-code-critic-2", ["TC-2"]))
        rework = table(rec(a1, ["TC-1"], role=AUTH), rec("S5-qa-code-critic-1", ["TC-1"]), rec("S5-qa-code-critic-2", ["TC-2"]),
                       rec(a2, ["TC-2"], status="running", role=AUTH))

        def put(dispatches):
            (task / "state" / "controller.json").write_text(
                json.dumps({"dispatches": dispatches, "stages": {"S5": {"status": "completed"}}}), encoding="utf-8")

        def verdict(name, rel):
            import os
            saved = {k: os.environ.get(k) for k in (PC.DETECTOR_DISPATCH_ENV, DI.DRIVER_RUN_ENV)}
            os.environ.pop(PC.DETECTOR_DISPATCH_ENV, None)
            os.environ[DI.DRIVER_RUN_ENV] = name
            try:
                ev = {"tool_name": "Write", "tool_input": {"file_path": str(root / rel), "content": "x"}, "cwd": str(root)}
                return G._blocked(G.window_file_check, ev, cfg)
            finally:
                for key, value in saved.items():
                    if value is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = value
        test_file = "tests/test_orders.py"
        WF.claim(task, test_file, "S5|TC-1", a1)
        put(rework)
        check_in("control: before the close a rework automator is refused over window TC-1's file", "belongs to window TC-1",
                 verdict(a2, test_file) or "")
        put(closed)
        d = finish_rig()
        d.task_root, d.state_dir = task, task / "state"
        d.controller_state = lambda: json.loads((task / "state" / "controller.json").read_text(encoding="utf-8"))
        # the person's `debt` at the gate: the entry of the repair-limit answer for the last critic, finished by `s5_close_debt` through the
        # real `completion_for` -> `s5_window_closed` (only the controller-script route read and the save are faked)
        critic = "S5-qa-code-critic-2"
        entry = {"dispatch": critic, "token": "debt", "owed": True, "cases": ["TC-2"], "finished": False}
        d.state["repair_limit"] = {d.repair_key(["TC-2"]): entry}
        d.save_state = lambda *a, **k: None
        d.budget_or_none = lambda *a, **k: {}
        d.route_of = lambda digest, budget, dispatch: ({"action": "close"}, None)
        with contextlib.redirect_stdout(io.StringIO()):
            d.s5_close_debt(entry, {"scope": ["TC-2"]})
        check_eq("s5_close_debt finished the critic (the debt road)", entry.get("finished"), True)
        check_eq("the debt road released the claims of S5", WF.files_of(task, "S5|TC-1"), [])
        put(rework)
        check_eq("after the closing finish the rework's automator writes that file, no refusal", verdict(a2, test_file), None)
    finally:
        cleanup(root)


# --- 10.2 -----------------------------------------------------------------------------------------------------------------------------

def returned_mechanical_round_keeps_window_open():
    """The critic's scenario: window A's critic accepted with route `mechanical`, A's mechanical round came back `returned_unaccepted`;
    window B's finish must not close S5 (through `s5_last_fn` of B)."""
    wins = [(("A",), True), (("B",), True)]
    d = rig(wins, table(rec("ca", ["A"]), rec("m1", ["A"], status=CT.RETURNED, role=AUTH), rec("cb", ["B"])))
    check_eq("A is open: its last round came back", d.s5_open_windows(excluding=["B"]), [["A"]])
    check_eq("B's close predicate is False", d.s5_last_fn(["B"])(), False)
    d = rig(wins, table(rec("ca", ["A"]), rec("m1", ["A"], role=AUTH, **MECHANICAL), rec("cb", ["B"])))
    check_eq("control: the same round accepted -> nothing open", (d.s5_open_windows(excluding=["B"]), d.s5_last_fn(["B"])()), ([], True))
    d = rig(wins, table(rec("ca", ["A"]), rec("m1", ["A"], status=CT.RETURNED, role=AUTH), rec("cb", ["B"])))
    check_eq("the window's own series is skipped with its window (excluding A)", d.s5_open_windows(excluding=["A"]), [])
    d = rig([(("A", "B"), True)], table(rec("m1", ["A", "B"], status=CT.RETURNED, role=AUTH), rec("cc", ["C"])))
    d.stage_scope = lambda stage, kind="": {"windows": [{"scope": ["A"], "accepted_by": {CRIT: 1}}, {"scope": ["B"], "accepted_by": {CRIT: 1}},
                                                        {"scope": ["C"], "accepted_by": {CRIT: 1}}]}
    check_eq("one returned dispatch meeting two windows opens both", d.s5_open_windows(excluding=["C"]), [["A"], ["B"]])


def later_accepted_dispatch_closes_returned_window():
    d = rig([(("A",), True)], table(rec("m1", ["A"], status=CT.RETURNED, role=AUTH), rec("c2", ["A"])))
    check_eq("a returned round followed by an accepted dispatch of the window: closed", d.s5_open_windows(()), [])


def returned_plan_dispatch_ignored():
    d = rig([(("A",), True)], table(rec("p1", ["A"], status=CT.RETURNED, role=AUTH, request_binding={"purpose": CT.S5_PLAN})))
    check_eq("a returned S5 PLAN dispatch is no window's round", d.s5_open_windows(()), [])
    d = rig([(("A",), True)], table(rec("p1", [], status=CT.RETURNED, role=AUTH, request_binding={"purpose": CT.S5_PLAN})))
    check_eq("... even with no scope", d.s5_open_windows(()), [])


def returned_without_scope_is_unreadable():
    d = rig([(("A",), True), (("B",), True)], table(rec("m1", [], status=CT.RETURNED, role=AUTH)))
    try:
        d.s5_open_windows(excluding=["B"])
        raised = None
    except SR.WindowsUnreadable as exc:
        raised = exc
    check("a returned dispatch that names no cases raises WindowsUnreadable", raised is not None)
    check_eq("the close predicate reads that as NOT last", d.s5_last_fn(["B"])(), False)


def returned_then_released_by_person_is_open():
    """DISCOUNTED drops the later `released_by_person` (and `superseded`) record: the returned one is last, so the window is open."""
    for later in (CT.RELEASED, "superseded", "stale", CT.NEVER_STARTED):
        d = rig([(("A",), True)], table(rec("m1", ["A"], status=CT.RETURNED, role=AUTH), rec("m2", ["A"], status=later, role=AUTH)))
        check_eq(f"a returned round followed by a `{later}` record: open", d.s5_open_windows(()), [["A"]])
    d = rig([(("A",), True)], table(rec("m1", ["A"], status=CT.RETURNED, role=AUTH), rec("m2", ["A"], status="accepted", role=AUTH, **MECHANICAL),
                                    rec("m3", ["A"], status=CT.RELEASED, role=AUTH)))
    check_eq("returned, accepted, then released: the accepted one is last, closed", d.s5_open_windows(()), [])


def old_body(windows, dispatches, config=None, owed_open=None):
    """Run `stage_S5` on the old body (one window in todo) with every role call faked; return (last handed to s5_window, driver)."""
    d = rig(windows, dispatches, config=config)
    seen = {}
    d.stand_check = d.build_check = d.s5_release = d.s5_release_closed = d.save_state = lambda *a, **k: None
    d.timed = lambda *a, **k: contextlib.nullcontext(type("L", (), {"dispatch": ""})())
    d.run_role = lambda *a, **k: None
    d.s5_window = lambda window, last, auto_extra, owed=None: seen.update(last=last, scope=window["scope"])
    with contextlib.redirect_stdout(io.StringIO()):
        d.stage_S5()
    return seen.get("last"), d


def two_windows_old_body_does_not_close_over_returned_round():
    """B-1 (a): W1's critic accepted with route mechanical, W1's mechanical round returned, todo == [W2]: W2's critic finish is NOT last."""
    wins = [(("W1",), True), (("W2",), False)]
    last, _ = old_body(wins, table(rec("c1", ["W1"]), rec("m1", ["W1"], status=CT.RETURNED, role=AUTH)))
    check_eq("the old body at N != 1 reads the returned last round: last is False", last, False)
    last, _ = old_body(wins, table(rec("c1", ["W1"]), rec("m1", ["W1"], role=AUTH, **MECHANICAL)))
    check_eq("control: the round accepted -> W2's critic is last", last, True)
    last, _ = old_body(wins, table(rec("c1", ["W1"])), config={"dispatch": {"parallel_windows": 2}})
    check_eq("control: a story with nothing returned closes as before (cap 2)", last, True)


def n1_old_body_reads_nothing():
    wins = [(("W1",), True), (("W2",), False)]
    d = rig(wins, table(rec("c1", ["W1"]), rec("m1", ["W1"], status=CT.RETURNED, role=AUTH)), config={"dispatch": {"parallel_windows": 1}})
    seen = {}
    d.stand_check = d.build_check = d.s5_release = d.save_state = lambda *a, **k: None
    d.timed = lambda *a, **k: contextlib.nullcontext(type("L", (), {"dispatch": ""})())
    d.run_role = lambda *a, **k: None
    d.s5_window = lambda window, last, auto_extra, owed=None: seen.update(last=last)
    d.s5_open_windows = lambda *a, **k: (_ for _ in ()).throw(AssertionError("N == 1: the old body reads nothing"))
    with contextlib.redirect_stdout(io.StringIO()):
        d.stage_S5()
    check_eq("at N == 1 `last` is `len(todo) == 1`, whatever came back (the frozen road, D2)", seen.get("last"), True)


def returned_last_round_raises_resolve_return_naming_the_dispatch():
    """D3 (option b): todo empty, window A's last round came back: the EXISTING resolve_return packet for that dispatch, never the old refusal."""
    wins = [(("A",), True), (("B",), True)]
    d = rig(wins, table(rec("ca", ["A"]), rec("m1", ["A"], status=CT.RETURNED, role=AUTH, returned_digest="half done"), rec("cb", ["B"])))
    d.state["pending_words"] = {}
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            d.stage_S5()
        raised = None
    except SR.Refusal as exc:
        raised = exc
    text = str(raised)
    check("a Refusal is raised", raised is not None)
    check("it is the resolve_return packet", text.startswith("resolve_return: "), text[:80])
    packet = json.loads(text[len("resolve_return: "):]) if text.startswith("resolve_return: ") else {}
    check_eq("the packet names the dispatch, its role and status", (packet.get("dispatch_id"), packet.get("role"), packet.get("dispatch_status")),
             ("m1", AUTH, CT.RETURNED))
    check_eq("the Refusal carries the dispatch field", getattr(raised, "dispatch", None), "m1")
    check_not_in("the old refusal text is absent", "every window is accepted", text)
    # the first such dispatch in record order
    d = rig(wins, table(rec("m1", ["A"], status=CT.RETURNED, role=AUTH), rec("m2", ["B"], status=CT.RETURNED, role=AUTH)))
    d.state["pending_words"] = {}
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            d.stage_S5()
    except SR.Refusal as exc:
        check_eq("two windows returned: the first in record order", exc.dispatch, "m1")
    check_eq("the packet is the one builder's text", text, str(SR.Driver.resolve_return_refusal(packet)))
    # N == 1: nothing of this is read
    d = rig(wins, table(rec("m1", ["A"], status=CT.RETURNED, role=AUTH)), config={"dispatch": {"parallel_windows": 1}})
    d.state["pending_words"] = {}
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            d.stage_S5()
        got = ""
    except SR.Refusal as exc:
        got = str(exc)
    check_in("at N == 1 the old refusal stands (the frozen road)", "every window is accepted", got)


WINS_AB = [(("A",), True), (("B",), True)]


def returned_rig(words, extra_rows=(), wins=WINS_AB, m1=None):
    """`stage_S5` with every window critic-accepted and window A's last round `m1` returned; `resume_role` is a recorder that spends the
    words as the real one does and accepts the round. `m1`: extra fields of the returned record (its `repair_cause`). Returns (driver, calls)."""
    d = rig(wins, table(rec("ca", ["A"]), {**rec("m1", ["A"], status=CT.RETURNED, role=AUTH, returned_digest="half done"), **(m1 or {})},
                        rec("cb", ["B"]), *extra_rows))
    d.state["pending_words"] = dict(words)
    calls = []

    def resume_role(stage, role, dispatch, text, *, complete=None):
        calls.append({"stage": stage, "role": role, "dispatch": dispatch, "words": text, "complete": complete})
        d.state["pending_words"].pop(dispatch, None)
        d.ctl["dispatches"][dispatch]["status"] = "accepted"
    d.resume_role = resume_role
    return d, calls


def enter(d):
    """One entry of `stage_S5`: the Refusal it raised (text) or ''."""
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            d.stage_S5()
        return ""
    except SR.Refusal as exc:
        return str(exc)


def returned_last_round_no_words_raises_packet():
    for name, words in (("no words filed", {}), ("empty words for the dispatch", {"m1": ""}), ("words key absent", None)):
        d, calls = returned_rig({})
        if words is None:
            del d.state["pending_words"]
        else:
            d.state["pending_words"] = dict(words)
        got = enter(d)
        check_in(f"{name}: the packet is raised", "resolve_return: ", got)
        check_eq(f"{name}: no role is resumed", calls, [])


def returned_last_round_with_words_resumes_role_and_consumes_them():
    """B1: the controller's `next` hides the return behind later S5 work, so the words filed for it are consumed HERE."""
    d, calls = returned_rig({"m1": "accept it"})
    got = enter(d)
    check_eq("no refusal: the stage resumed the role and returned", got, "")
    check_eq("resume_role is called once, with the dispatch, its stage and role and the words whole",
             [(c["stage"], c["role"], c["dispatch"], c["words"]) for c in calls], [("S5", AUTH, "m1", "accept it")])
    check_eq("the words are consumed: pending_words no longer holds m1", d.state["pending_words"], {})
    check_eq("the boundary names the dispatch", d.boundary, "S5:m1")
    # words that are only blank are words for `_act_resolve_return` (truthy), so they are used the same way: one move, one rule
    d, calls = returned_rig({"m1": "  "})
    check_eq("blank (not empty) words follow `_act_resolve_return`: used", (enter(d), len(calls)), ("", 1))


def second_entry_after_resume_does_not_raise_again():
    d, calls = returned_rig({"m1": "accept it"})
    enter(d)
    seen, second = _stage_run(d)
    check_not_in("the second entry raises no resolve_return packet", "resolve_return", second)
    # TR4-13: the resumed test_defect round is now an accepted author round no critic saw, so the second entry is the critic's review
    # (it used to be the old refusal, the known gap of TR4-10 A1); the old refusal's own state is `no_returned_round_keeps_the_old_refusal`
    check_eq("it is the critic's review of that window, not the old refusal", (second, seen.get("scope")), ("", ["A"]))
    check_eq("the role was resumed once, not twice", len(calls), 1)


def words_of_another_dispatch_are_not_used():
    d, calls = returned_rig({"zz": "go on"})
    got = enter(d)
    check_in("words filed for another dispatch: the packet for m1 is raised", '"dispatch_id": "m1"', got)
    check_eq("nothing is resumed", calls, [])
    check_eq("and the other words are left alone", d.state["pending_words"], {"zz": "go on"})


def returned_record_gone_at_resume_gives_the_old_refusal():
    d, calls = returned_rig({"m1": "accept it"})
    reads = []
    real = d.controller_state

    def state():
        reads.append(1)
        return real() if len(reads) == 1 else {"dispatches": {}}      # the record is gone by the time of the resume
    d.controller_state = state
    got = enter(d)
    check_in("the old refusal", "every window is accepted", got)
    check_eq("no role was resumed", calls, [])


def record_gone_refusal_keeps_the_stage_boundary():
    """Nit (a), Lead option A: on the record-gone road the old refusal carries the STAGE's boundary, not the helper's `:m1`."""
    d, calls = returned_rig({"m1": "accept it"})
    reads = []
    real = d.controller_state

    def state():
        reads.append(1)
        return real() if len(reads) == 1 else {"dispatches": {}}      # the record is gone by the time of the resume
    d.controller_state = state
    d.boundary = "S5"           # what `_act_prepare_stage` set before `stage_S5`
    got = enter(d)
    check_in("record gone: the old refusal", "every window is accepted", got)
    check_eq("... raised under the stage's boundary", d.boundary, "S5")
    # control: the visible no-words road (`_act_resolve_return`) still raises its packet under `S5:<dispatch>`, which the conductor reads
    d, calls = returned_rig({})
    d.boundary = "S5"
    try:
        d._act_resolve_return({"action": "resolve_return", "dispatch_id": "m1", "stage": "S5", "role": AUTH})
        raised = ""
    except SR.Refusal as exc:
        raised = str(exc)
    check_in("control: the no-words packet is raised", "resolve_return: ", raised)
    check_eq("control: ... under `S5:m1`", d.boundary, "S5:m1")


def resumed_mechanical_round_of_last_window_completes_s5():
    """N1: the resumed MECHANICAL round finishes under the window's rule (`s5_last_fn`), like the live mechanical round."""
    d, calls = returned_rig({"m1": "accept it"}, m1=MECHANICAL)
    enter(d)
    complete = calls[0]["complete"]
    check("the completion rule is a callable of the digest", callable(complete))
    check_eq("A is the last window open (B is accepted, nothing else returned): the round completes S5", complete("digest"), True)
    check_eq("the completion rule is the one `s5_last_fn` answers", complete("digest"), d.s5_last_fn(["A"])())


def resumed_mechanical_round_of_not_last_window_does_not():
    d, calls = returned_rig({"m1": "accept it"}, extra_rows=(rec("m2", ["B"], status=CT.RETURNED, role=AUTH),), m1=MECHANICAL)
    enter(d)
    check_eq("window B still holds a returned last round: the resumed round of A does not complete S5", calls[0]["complete"]("digest"), False)
    d, calls = returned_rig({"m1": "accept it"}, m1=MECHANICAL)
    d.s5_open_windows = lambda *a, **k: (_ for _ in ()).throw(OSError("unreadable"))
    enter(d)
    check_eq("an unreadable state is open, never a close", calls[0]["complete"]("digest"), False)


MECHANICAL = {"repair_cause": "mechanical"}


def _completes(complete) -> bool:
    """The resume's completion as the finish reads it: a flag, or a callable of the digest."""
    return bool(complete("digest")) if callable(complete) else bool(complete)


def resumed_test_defect_round_does_not_complete_s5():
    """B2 (re-review): N = 3. W1's critic rejected with test_defect (the critic is accepted `--not-complete`, so W1 leaves todo); W1's
    repair round m1 (`repair_cause: test_defect`) came back; W2 and W3 closed (a later dispatch hides m1 from `next`); the person's words
    are filed under m1. The resume finishes NOT complete: the critic reviews the repair first (AR-28)."""
    wins = [(("A",), True), (("B",), True), (("C",), True)]
    d, calls = returned_rig({"m1": "accept it"}, extra_rows=(rec("cc", ["C"]),), wins=wins, m1={"repair_cause": "test_defect"})
    check_eq("control: with the round set aside, no other window is open (s5_last_fn of A says last)", d.s5_last_fn(["A"])(), True)
    got = enter(d)
    check_eq("the role is resumed (no refusal)", (got, len(calls)), ("", 1))
    check_eq("the resumed test_defect round does not complete S5", _completes(calls[0]["complete"]), False)
    # the same rig with the cause mechanical: the only difference flips the answer (the key is the cause, nothing else)
    d, calls = returned_rig({"m1": "accept it"}, extra_rows=(rec("cc", ["C"]),), wins=wins, m1=MECHANICAL)
    enter(d)
    check_eq("control: the same state with a mechanical round completes S5", _completes(calls[0]["complete"]), True)


def resumed_round_with_no_cause_does_not_complete_s5():
    """An absent, empty or unknown cause is read as the controller reads it (`repair_cause` -> test_defect): never a close (FR-59)."""
    for name, extra in (("no repair_cause field", {}), ("an empty cause", {"repair_cause": ""}),
                        ("an unknown cause", {"repair_cause": "whatever"}), ("a cause that is not a string", {"repair_cause": 7}),
                        ("environment", {"repair_cause": "environment"})):
        d, calls = returned_rig({"m1": "accept it"}, m1=extra)
        enter(d)
        check_eq(f"{name}: the resumed round does not complete S5", _completes(calls[0]["complete"]), False)
    # a resumed CRITIC keeps `completion_for`, whatever a cause field says
    d, calls = returned_rig({"m1": "accept it"}, m1={"role": CRIT, "repair_cause": "mechanical"})
    seen = []
    d.completion_for = lambda stage, role, record: seen.append((stage, role, record.get("id"))) or "the critic's rule"
    enter(d)
    check_eq("a resumed critic gets `completion_for`, unchanged", (calls[0]["complete"], seen), ("the critic's rule", [("S5", CRIT, "m1")]))


def resolve_return_action_equals_the_controllers():
    """N3: the action `stage_S5` builds is the controller's own for the same returned dispatch (a state where the return is NOT hidden).
    Queued: ONE shared builder of this action in the controller (not done here)."""
    row = rec("m1", ["A"], status=CT.RETURNED, role=AUTH, returned_digest="half done", reason="ran out of turns")
    state = {"environment_jobs": [], "dispatches": {"m1": dict(row)}, "window_counters": {}, "window_context_percent": None,
             "stages": {"S5": {"status": "pending"}}, "decisions": {}, "revision": 1, "scope": [], "gates": {}}
    theirs = CT.Controller._next_action_for_state(state)
    check_eq("control: the controller offers resolve_return for the unhidden return", theirs.get("action"), "resolve_return")
    d = rig([(("A",), True)], {"m1": dict(row)})
    d.state["pending_words"] = {}
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            d.stage_S5()
        raised = ""
    except SR.Refusal as exc:
        raised = str(exc)
    ours = json.loads(raised[len("resolve_return: "):])
    check_eq("the same keys", sorted(ours), sorted(theirs))
    check_eq("the same values (nothing in the action depends on the run)", ours, theirs)


def owed_branch_does_not_close_over_open_window():
    """The owed branch of the old body's `last` reads the same close rule at N != 1 (D1 invariant), and nothing at N == 1."""
    def run(config, dispatches):
        d = rig([(("A",), False), (("B",), True)], dispatches, config=config)
        d.repair_owed = lambda windows: (({"token": "round", "dispatch": "c", "executed": False}, windows[0])
                                         if windows[0]["scope"] == ["A"] else ({}, None))      # only window A is owed its round
        seen = {}
        d.stand_check = d.build_check = d.s5_release = d.s5_release_closed = d.save_state = lambda *a, **k: None
        d.timed = lambda *a, **k: contextlib.nullcontext(type("L", (), {"dispatch": ""})())
        d.run_role = lambda *a, **k: None
        d.s5_window = lambda window, last, auto_extra, owed=None: seen.update(last=last)
        with contextlib.redirect_stdout(io.StringIO()):
            d.stage_S5()
        return seen.get("last")
    returned = table(rec("cb", ["B"]), rec("m1", ["B"], status=CT.RETURNED, role=AUTH))
    check_eq("owed round at N != 1 beside another window's returned last round: not last", run({}, returned), False)
    check_eq("control: nothing returned -> last", run({}, table(rec("cb", ["B"]))), True)
    check_eq("N == 1: the owed branch is as before, whatever came back", run({"dispatch": {"parallel_windows": 1}}, returned), True)


def no_returned_round_keeps_the_old_refusal():
    """The refusal 'every window is accepted ... recover' stays reachable when no window has a returned last round."""
    d = rig([(("A",), True), (("B",), True)], table(rec("ca", ["A"]), rec("cb", ["B"])))
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            d.stage_S5()
        raised = ""
    except SR.Refusal as exc:
        raised = str(exc)
    check_in("todo empty and nothing returned: the factory's own-state refusal", "every window is accepted", raised)


# --- 10.4 -----------------------------------------------------------------------------------------------------------------------------

CHAIN_LINE = ("Other windows of this story are written at the same time. A test file one of them wrote first refuses your "
              "Write or Edit: put your test in a new file in the same directory; where a test lives stays your choice, "
              "and a test in a new file is judged the same.")
OLD_BODY_LINE = ("A test file another window of this story wrote first refuses your Write or Edit: put your test in a new file in the "
                 "same directory; where a test lives stays your choice, and a test in a new file is judged the same.")
STAND_LINE = ("A run that answers `stand busy` after some minutes waited for the stand queue: it is not a failure of your "
              "tests. Say so in your digest and run again.")


def extra_of(config, chain, absent=False):
    d = rig(config=config)
    if absent:
        del d.__dict__["config"]
    d.s5_notes_line = lambda: ""
    return d.s5_auto_extra({"surface": "api"}, ["TC-1"], chain=chain)


def ownership_line_on_old_body_when_n_not_1():
    lines = extra_of({}, False)
    check_in("old body, default N: the ownership line is given", OLD_BODY_LINE, lines)
    check_not_in("... in the variant: the false 'written at the same time' sentence is not", "written at the same time", lines)
    check_not_in("... and the stand line stays chain-only", "stand busy", lines)
    check_eq("the variant shares the door sentence with the chain text", (SR.Driver.S5_OWN_FILE_DOOR in CHAIN_LINE, CHAIN_LINE.endswith(SR.Driver.S5_OWN_FILE_DOOR),
                                                                          OLD_BODY_LINE.endswith(SR.Driver.S5_OWN_FILE_DOOR)), (True, True, True))
    chain = extra_of({}, True)
    check_eq("chain=True: both lines, byte for byte as before", chain[-2:], [CHAIN_LINE, STAND_LINE])
    check_not_in("chain=True does not carry the variant", OLD_BODY_LINE, chain)
    check_in("config absent on the rig: no raise, the default (not 1) gives the line", OLD_BODY_LINE, extra_of(None, False, absent=True))


def n1_extra_unchanged():
    one = {"dispatch": {"parallel_windows": 1}}
    lines = extra_of(one, False)
    check_eq("N == 1, chain False: only the window line and the run line", [x.startswith(p) for x, p in zip(lines, ("Window: TC-1 — api surface.", "Runs go through run_suite.py"))] + [len(lines)],
             [True, True, 2])
    check_not_in("... no ownership line", "refuses your Write or Edit", lines)
    check_eq("N == 1 with chain=True (never reached today) keeps today's two lines", extra_of(one, True)[-2:], [CHAIN_LINE, STAND_LINE])


def line_iff_guard_enforces():
    for value in (1, 2, 3, "x", 0, True, None):
        cfg = {"dispatch": {"parallel_windows": value}}
        enforced = config_contract.parallel_windows(cfg)[0] != 1
        check_eq(f"parallel_windows {value!r}: the line is present iff the guard's reader says N != 1 ({enforced})",
                 OLD_BODY_LINE in extra_of(cfg, False), enforced)
    check_eq("absent `dispatch`: the line is present", OLD_BODY_LINE in extra_of({"x": 1}, False), True)
    check_eq("a config that is not an object: the default, the line is present", OLD_BODY_LINE in extra_of([], False), True)


# --- TR4-13: a window whose last round is an ACCEPTED author round is open and goes to the critic -----------------------------------------

def _author_last(**extra):
    """Window A critic-accepted earlier; its LAST round is an accepted author round `m1` (the cause in `extra`)."""
    return table(rec("ca", ["A"]), rec("m1", ["A"], role=AUTH, **extra))


def _stage_run(d):
    """`stage_S5` with every role call faked: (scope handed to the critic loop or None, the Refusal text or '')."""
    seen = {}
    d.stand_check = d.build_check = d.s5_release = d.s5_release_closed = d.save_state = lambda *a, **k: None
    d.timed = lambda *a, **k: contextlib.nullcontext(type("L", (), {"dispatch": ""})())
    d.run_role = lambda *a, **k: seen.setdefault("author_run", True)
    d.s5_window = lambda window, last, auto_extra, owed=None: seen.update(scope=window["scope"], last=last)
    d.state.setdefault("pending_words", {})
    return seen, enter(d)


def accepted_author_round_opens_the_window_and_goes_to_the_critic():
    """(a) the red test: before the node the window read closed and the stage ended at the 'recover' refusal."""
    d = rig([(("A",), True)], _author_last(repair_cause="test_defect"))
    check_eq("(a) the window is open", d.s5_open_windows(()), [["A"]])
    d = rig([(("A",), True)], _author_last(repair_cause="test_defect"))
    seen, refusal = _stage_run(d)
    check_eq("(a) the next move is the critic's review of that window (no refusal, no author run)", (refusal, seen.get("scope"), "author_run" in seen),
             ("", ["A"], False))
    check_eq("(a) it is the last window: the review may close S5", seen.get("last"), True)


def accepted_author_round_is_read_from_disk_after_a_restart():
    """(b) nothing in memory: a NEW driver over the same record reads the same open window."""
    rows = _author_last(repair_cause="test_defect")
    first = rig([(("A",), True)], rows)
    again = rig([(("A",), True)], json.loads(json.dumps(rows)))
    check_eq("(b) both drivers read the window open", (first.s5_open_windows(()), again.s5_open_windows(())), ([["A"]], [["A"]]))
    seen, refusal = _stage_run(again)
    check_eq("(b) the restarted driver sends it to the critic", (refusal, seen.get("scope")), ("", ["A"]))


def critic_round_after_the_author_round_keeps_the_window_closed():
    """(c) no regress: author round then a critic round -> closed, and the old refusal stays for that state."""
    rows = table(rec("m1", ["A"], role=AUTH, repair_cause="test_defect"), rec("c2", ["A"]))
    d = rig([(("A",), True)], rows)
    check_eq("(c) closed", d.s5_open_windows(()), [])
    seen, refusal = _stage_run(rig([(("A",), True)], rows))
    check_in("(c) every window accepted: the old refusal", "every window is accepted", refusal)
    check_eq("(c) no critic dispatch", seen.get("scope"), None)


def mechanical_author_round_completes_the_window_as_before():
    """(d) cause read through `controller.repair_cause`, as A1 round 3 does."""
    d = rig([(("A",), True)], _author_last(repair_cause="mechanical"))
    check_eq("(d) a mechanical author round: closed", d.s5_open_windows(()), [])
    for name, extra in (("absent cause", {}), ("unknown cause", {"repair_cause": "whatever"}), ("cause not a string", {"repair_cause": 7})):
        d = rig([(("A",), True)], _author_last(**extra))
        check_eq(f"{name} reads as test_defect (the controller's reader): open", d.s5_open_windows(()), [["A"]])


def unreadable_record_in_stage_keeps_the_old_refusal():
    """The one edge new to this node: the stage with the controller record unreadable keeps today's refusal path (`s5_todo` falls
    back to the critic-less windows). The other edges (gone record, no rounds, critic last) are pinned by the TR4-10 tests above."""
    d = rig([(("A",), True)], _author_last(repair_cause="test_defect"))
    d.controller_state = lambda: (_ for _ in ()).throw(OSError("unreadable"))
    seen, refusal = _stage_run(d)
    check_in("the stage with an unreadable record: the old refusal, no crash", "every window is accepted", refusal)


def progress_line_does_not_count_a_held_window_as_closed():
    """N2: a window `s5_todo` holds (critic in `accepted_by`, author round owed its critic) is running, not closed."""
    d = rig([(("A",), True), (("B",), True)])
    wins = d.stage_scope("S5")["windows"]
    seen = {}
    d.run_chains = lambda *a, **k: seen.update(view=dict(d._s5_view))
    d.run_s5_windows(wins, [wins[0]], 3)
    check_eq("A is held (todo), B is closed", (seen["view"]["total"], seen["view"]["closed"]), (2, {2}))
    seen.clear()
    d.run_s5_windows([], [], 3)
    check_eq("an empty window list: nothing closed", (seen["view"]["total"], seen["view"]["closed"]), (0, set()))


def todo_and_open_windows_agree_on_the_author_round():
    """AR-13: one predicate. Every state of one window: `stage_S5` sends it to the critic iff `s5_open_windows` lists it for that reason."""
    for name, rows, want in (("author test_defect", _author_last(repair_cause="test_defect"), True),
                             ("author mechanical", _author_last(repair_cause="mechanical"), False),
                             ("critic last", table(rec("m1", ["A"], role=AUTH), rec("c2", ["A"])), False)):
        d = rig([(("A",), True)], rows)
        opened = d.s5_open_windows(()) == [["A"]]
        seen, _ = _stage_run(rig([(("A",), True)], rows))
        check_eq(f"{name}: open == dispatched to the critic", (opened, seen.get("scope") == ["A"]), (want, want))


def n1_keeps_the_old_refusal_for_an_accepted_author_round():
    """Non-goal, a named residual of TR4-10: at N == 1 nothing is read and the road is as before."""
    d = rig([(("A",), True)], _author_last(repair_cause="test_defect"), config={"dispatch": {"parallel_windows": 1}})
    d.s5_open_windows = lambda *a, **k: (_ for _ in ()).throw(AssertionError("N == 1: nothing is read"))
    seen, refusal = _stage_run(d)
    check_in("N == 1: the old refusal stands", "every window is accepted", refusal)
    check_eq("N == 1: no critic dispatch", seen.get("scope"), None)


def main():
    cases = [accepted_author_round_opens_the_window_and_goes_to_the_critic, accepted_author_round_is_read_from_disk_after_a_restart,
             critic_round_after_the_author_round_keeps_the_window_closed, mechanical_author_round_completes_the_window_as_before,
             unreadable_record_in_stage_keeps_the_old_refusal, progress_line_does_not_count_a_held_window_as_closed,
             todo_and_open_windows_agree_on_the_author_round,
             n1_keeps_the_old_refusal_for_an_accepted_author_round,
             recovery_finishes_free_sibling_claims, live_mechanical_round_close_frees_every_s5_claim,
             stage_completed_beside_running_rework_frees_nothing, completed_beside_incomplete_frees_nothing,
             completed_beside_returned_frees_nothing, unreadable_stage_frees_nothing, n1_reads_nothing,
             closed_by_debt_then_rework_automator_not_refused, kept_young_empty_claim_gives_no_note,
             returned_mechanical_round_keeps_window_open, later_accepted_dispatch_closes_returned_window, returned_plan_dispatch_ignored,
             returned_without_scope_is_unreadable, returned_then_released_by_person_is_open,
             two_windows_old_body_does_not_close_over_returned_round, n1_old_body_reads_nothing, no_returned_round_keeps_the_old_refusal,
             returned_last_round_raises_resolve_return_naming_the_dispatch, returned_last_round_no_words_raises_packet,
             returned_last_round_with_words_resumes_role_and_consumes_them, second_entry_after_resume_does_not_raise_again,
             words_of_another_dispatch_are_not_used, returned_record_gone_at_resume_gives_the_old_refusal,
             resumed_mechanical_round_of_last_window_completes_s5, resumed_mechanical_round_of_not_last_window_does_not,
             resumed_test_defect_round_does_not_complete_s5, resumed_round_with_no_cause_does_not_complete_s5,
             record_gone_refusal_keeps_the_stage_boundary, resolve_return_action_equals_the_controllers, owed_branch_does_not_close_over_open_window,
             ownership_line_on_old_body_when_n_not_1, n1_extra_unchanged, line_iff_guard_enforces]
    try:
        for case in cases:
            print(f"-- {case.__name__}")
            case()
    finally:
        for root in ROOTS:
            shutil.rmtree(root, ignore_errors=True)
    finish("test_s5_window_leftovers")


if __name__ == "__main__":
    main()
