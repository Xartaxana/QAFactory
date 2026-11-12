#!/usr/bin/env python3
"""TR3-13 (spec t-1937 B1; AR-13, AR-15, AR-28): "which dispatch am I" has ONE reader, `dispatch_identity`.

ERROR DIRECTION under test: the reader may answer None, it must never answer another window's dispatch. Every case runs the
REAL `s5_precheck` / `exit_gate` / `branch_accounting` functions over a seeded `state/controller.json`; the environment
words (`QA_FACTORY_DETECTOR_DISPATCH`, `QA_FACTORY_DRIVER_RUN`) are set by `envs()` and always restored.

Keys (the spec's list): named_wins_over_count, detector_dispatch_beats_driver_run, env_other_role_is_none_not_count,
closed_dispatch_named_is_none, unknown_id_falls_to_count, no_env_one_running_same_as_today, no_env_two_running_none,
blank_env_is_unset, returned_named_found_only_when_asked, finish_with_two_automators_judges_own_scope,
detector_two_running_no_name_unreadable_never_every_case, digest_scope_read_with_two_automators; plus the awkward inputs of
the pure reader (lists, None, non-dicts) and the old count rule pinned against a copy of it.
"""
import contextlib
import io
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import PLUGIN_ROOT, check, check_eq, check_in, cleanup, finish, temp_project, use_project  # noqa: E402

sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))
import branch_accounting as BA  # noqa: E402
import detector_verdict as DV  # noqa: E402
import dispatch_identity as DI  # noqa: E402
import exit_gate as gate  # noqa: E402
import planning_contract as PC  # noqa: E402
import s5_precheck as S5  # noqa: E402
import story_step  # noqa: E402

TICKET = "QA-DI1"
A1, A2, C1, A3 = "S5-qa-automator-1", "S5-qa-automator-2", "S5-qa-critic-1", "S5-qa-automator-3"
DETECTOR_ENV, DRIVER_ENV = PC.DETECTOR_DISPATCH_ENV, DI.DRIVER_RUN_ENV


def rec(ident, status="running", role="qa-automator", stage="S5", scope=None, **extra):
    return {"id": ident, "stage": stage, "role": role, "status": status, "scope": scope or [], **extra}


@contextlib.contextmanager
def envs(detector=None, driver=None):
    """Set the two words (None = unset), restore both on exit."""
    saved = {k: os.environ.get(k) for k in (DETECTOR_ENV, DRIVER_ENV)}
    for key, value in ((DETECTOR_ENV, detector), (DRIVER_ENV, driver)):
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    try:
        yield
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


class Story:
    """A throwaway story: controller.json with `dispatches` and a manifest; the gate reads artifacts from it."""

    def __init__(self, dispatches):
        self.root = temp_project("qa-dispatch-identity-")
        use_project(self.root)
        self.task = self.root / "qa-factory" / "artifacts" / TICKET
        (self.task / "state").mkdir(parents=True)
        (self.task / "work").mkdir(parents=True)
        (self.task / "state" / "controller.json").write_text(json.dumps({"dispatches": dispatches}), encoding="utf-8")
        (self.task / "work" / "automation-manifest.json").write_text("{}", encoding="utf-8")
        self.saved = gate.artifact_root
        gate.artifact_root = lambda: self.root / "qa-factory" / "artifacts"

    def close(self):
        gate.artifact_root = self.saved
        cleanup(self.root)


def old_count_rule(dispatches, role="qa-automator", stage="S5", status="running"):
    """The rule every site copied before TR3-13, verbatim (`live[0] if len(live) == 1 else None`), as an id."""
    live = [str(d.get("id") or d.get("dispatch_id") or "") for d in dispatches.values()
            if d.get("status") == status and str(d.get("role") or "") == role and str(d.get("stage") or "") == stage]
    live = [d for d in live if d]
    return live[0] if len(live) == 1 else None


TWO = {A1: rec(A1, scope=["TC-001"]), A2: rec(A2, scope=["TC-002"])}


def named_wins_over_count():
    s = Story(TWO)
    try:
        with envs(driver=A2):
            check_eq("named_wins_over_count: the driver word picks its own among two", S5.running_dispatch(s.task), A2)
            check_eq("named_wins_over_count: window_dispatch agrees", S5.window_dispatch(s.task), A2)
        with envs(driver=A1):
            check_eq("named_wins_over_count: and the other window gets the other id", S5.running_dispatch(s.task), A1)
        with envs():
            check_eq("named_wins_over_count: control, no word, two running: none", S5.running_dispatch(s.task), None)
        # two automators WITH a name: still its own, never the sibling; the pure reader too
        check_eq("two automators with a name: own record", DI.own(TWO, "qa-automator", "S5", name=A1)["id"], A1)
    finally:
        s.close()


def detector_dispatch_beats_driver_run():
    s = Story(TWO)
    try:
        with envs(detector=A1, driver=A2):
            check_eq("detector_dispatch_beats_driver_run: the gate's word first", (DI.named(), S5.running_dispatch(s.task)), (A1, A1))
        with envs(detector=None, driver=A2):
            check_eq("detector_dispatch_beats_driver_run: control, the driver word alone", DI.named(), A2)
        with envs(detector="  " + A1 + " \n", driver=A2):
            check_eq("detector_dispatch_beats_driver_run: stripped", DI.named(), A1)
    finally:
        s.close()


def env_other_role_is_none_not_count():
    d = {A1: rec(A1, scope=["TC-001"]), C1: rec(C1, role="qa-code-critic", scope=["TC-001"])}
    s = Story(d)
    try:
        with envs(driver=C1):
            check_eq("env_other_role_is_none_not_count: the critic's session asks for the automator: none, NOT the one automator",
                     S5.running_dispatch(s.task), None)
            check_eq("env_other_role_is_none_not_count: window_dispatch too", S5.window_dispatch(s.task), None)
            check_eq("env_other_role_is_none_not_count: exit_gate._live_dispatch too", gate._live_dispatch("qa-automator", TICKET), None)
        with envs():
            check_eq("env_other_role_is_none_not_count: control, no word: the one automator", S5.running_dispatch(s.task), A1)
        with envs(driver=C1):
            check_eq("the pure reader: a name of another STAGE is none", DI.own(d, "qa-code-critic", "S7"), None)
    finally:
        s.close()


def closed_dispatch_named_is_none():
    d = {A1: rec(A1, "accepted", scope=["TC-001"]), A2: rec(A2, scope=["TC-002"])}
    s = Story(d)
    try:
        with envs(driver=A1):
            check_eq("closed_dispatch_named_is_none: running_dispatch", S5.running_dispatch(s.task), None)
            check_eq("closed_dispatch_named_is_none: window_dispatch", S5.window_dispatch(s.task), None)
            check_eq("closed_dispatch_named_is_none: digest scope", gate.dispatch_scope("qa-automator", TICKET), [])
        with envs():
            check_eq("closed_dispatch_named_is_none: control, no word: the running one", S5.running_dispatch(s.task), A2)
    finally:
        s.close()


def unknown_id_falls_to_count():
    one = Story({A2: rec(A2, scope=["TC-002"])})
    two = Story(TWO)
    try:
        with envs(driver="S5-qa-automator-9"):
            check_eq("unknown_id_falls_to_count: another story's id, one running here: it", S5.running_dispatch(one.task), A2)
            check_eq("unknown_id_falls_to_count: at two or more: none", S5.running_dispatch(two.task), None)
    finally:
        one.close()
        two.close()


def no_env_one_running_same_as_today():
    """The Temporal edge: before TR3-4 two running cannot exist, so every road gives the count rule's old answer."""
    shapes = {
        "one running": {A1: rec(A1, scope=["TC-001"])},
        "one running, one done": {A1: rec(A1, "accepted"), A2: rec(A2, scope=["TC-002"])},
        "none running": {A1: rec(A1, "accepted")},
        "one returned": {A1: rec(A1, "returned_unaccepted", scope=["TC-001"])},
        "returned and done": {A1: rec(A1, "returned_unaccepted"), A2: rec(A2, "accepted")},
        "no dispatches": {},
    }
    with envs():
        for label, d in shapes.items():
            s = Story(d)
            try:
                old_run = old_count_rule(d)
                old_window = old_run or old_count_rule(d, status="returned_unaccepted")
                check_eq(f"no_env_one_running_same_as_today: running_dispatch [{label}]", S5.running_dispatch(s.task), old_run)
                check_eq(f"no_env_one_running_same_as_today: window_dispatch [{label}]", S5.window_dispatch(s.task), old_window)
                live = gate._live_dispatch("qa-automator", TICKET)
                check_eq(f"no_env_one_running_same_as_today: exit_gate._live_dispatch [{label}]", live and live["id"], old_run)
            finally:
                s.close()
        s = Story(shapes["one running"])
        try:
            check_eq("no_env_one_running_same_as_today: branch_accounting.s5_scope", BA.s5_scope(s.task), ["TC-001"])
        finally:
            s.close()


def no_env_two_running_none():
    s = Story(TWO)
    try:
        with envs():
            check_eq("no_env_two_running_none: running_dispatch", S5.running_dispatch(s.task), None)
            check_eq("no_env_two_running_none: window_dispatch", S5.window_dispatch(s.task), None)
            check_eq("no_env_two_running_none: _live_dispatch", gate._live_dispatch("qa-automator", TICKET), None)
            check_eq("no_env_two_running_none: branch_accounting.s5_scope is unknown, never every case",
                     BA.s5_scope(s.task), BA.UNKNOWN_SCOPE)
            saved = (BA._read_register, BA.branch_state)
            BA._read_register = lambda root: "register"
            BA.branch_state = lambda root, text: {"state": "ok", "branches": []}
            try:
                BA.s5_check(s.task)
                cause = ""
            except BA.Unreadable as exc:
                cause = str(exc)
            finally:
                BA._read_register, BA.branch_state = saved
            check_in("no_env_two_running_none: the cause says what it knows", "2 automators are running and none was named", cause)
            check("no_env_two_running_none: and no longer the false 'no running'", "no running qa-automator" not in cause, cause)
    finally:
        s.close()


def blank_env_is_unset():
    s = Story(TWO)
    try:
        for label, det, drv in (("both blank", "", "   "), ("tabs and newlines", "\t\n", " \n "), ("detector blank, driver absent", " ", None)):
            with envs(detector=det, driver=drv):
                check_eq(f"blank_env_is_unset: named() [{label}]", DI.named(), "")
                check_eq(f"blank_env_is_unset: two running, none [{label}]", S5.running_dispatch(s.task), None)
        with envs(detector="  ", driver=A2):
            check_eq("blank_env_is_unset: a blank gate word falls to the driver word", DI.named(), A2)
    finally:
        s.close()


def returned_named_found_only_when_asked():
    d = {A1: rec(A1, "returned_unaccepted", scope=["TC-001"]), A2: rec(A2, "returned_unaccepted", scope=["TC-002"])}
    s = Story(d)
    try:
        with envs(detector=A2):
            check_eq("returned_named_found_only_when_asked: default statuses: none", DI.own(d, "qa-automator", "S5"), None)
            check_eq("returned_named_found_only_when_asked: running_dispatch: none", S5.running_dispatch(s.task), None)
            check_eq("returned_named_found_only_when_asked: asked for it: found",
                     DI.own(d, "qa-automator", "S5", statuses=("running", S5.RETURNED_STATUS))["id"], A2)
            check_eq("returned_named_found_only_when_asked: window_dispatch asks: its own", S5.window_dispatch(s.task), A2)
        with envs():
            check_eq("returned_named_found_only_when_asked: control, two returned and no word: none", S5.window_dispatch(s.task), None)
        with envs(detector=C1):
            check_eq("returned_named_found_only_when_asked: a name that is no record, two returned: none (count)",
                     S5.window_dispatch(s.task), None)
        # a running automator beside a returned one named by the critic's session: never the automator's window
        d2 = {A1: rec(A1, scope=["TC-001"]), C1: rec(C1, "returned_unaccepted", role="qa-code-critic")}
        s2 = Story(d2)
        try:
            with envs(detector=C1):
                check_eq("a named critic never gets the automator's window", S5.window_dispatch(s2.task), None)
        finally:
            s2.close()
    finally:
        s.close()


def finish_with_two_automators_judges_own_scope():
    s = Story(TWO)
    seen = {}
    saved = (gate.detector_gates, gate.all_errors)
    try:
        gate.detector_gates = lambda: {"qa-automator": ["s5_precheck.py"]}

        def fake_all_errors(role, task, digest):
            seen["held"] = (gate.held_dispatch(), gate.held_stage())
            seen["env"] = gate._detector_env(task)
            seen["scope"] = gate.dispatch_scope(role, task)
            return [], []
        gate.all_errors = fake_all_errors
        args = SimpleNamespace(task=TICKET)
        with envs():
            story_step._finish_gate(args, s.task, TWO[A2], {})
        check_eq("finish_with_two_automators_judges_own_scope: the gate holds the finisher's dispatch and stage",
                 seen.get("held"), (A2, "S5"))
        check_eq("finish_with_two_automators_judges_own_scope: the detector is told the dispatch",
                 seen["env"].get(DETECTOR_ENV), A2)
        check_eq("finish_with_two_automators_judges_own_scope: and the in-process scope is the finisher's own", seen.get("scope"), ["TC-002"])
        check_eq("finish_with_two_automators_judges_own_scope: restored after the gate", gate.held_dispatch(), "")
        check_eq("finish_with_two_automators_judges_own_scope: no dispatch held, no word in the detector env",
                 DETECTOR_ENV in gate._detector_env(TICKET), False)
        with envs(detector="S5-stale"):
            check_eq("finish_with_two_automators_judges_own_scope: a stale word of the parent is removed from a bare call",
                     DETECTOR_ENV in gate._detector_env(""), False)
        with gate.holding_dispatch(A1):
            check_eq("holding_dispatch: nested restore (outer)", gate.held_dispatch(), A1)
            with gate.holding_dispatch(A2):
                check_eq("holding_dispatch: nested restore (inner)", gate.held_dispatch(), A2)
            check_eq("holding_dispatch: back to the outer", gate.held_dispatch(), A1)
            check_eq("holding_dispatch: not named beside no story (unknown-task)", DETECTOR_ENV in gate._detector_env("unknown-task"), False)
        try:
            with gate.holding_dispatch(A1):
                raise RuntimeError("x")
        except RuntimeError:
            pass
        check_eq("holding_dispatch: restored on an exception", gate.held_dispatch(), "")
        with gate.holding_dispatch(None):
            check_eq("holding_dispatch: a non-string holds nothing", gate.held_dispatch(), "")
        # the driver's road: no word in its environment, the held dispatch alone names the gated one
        with envs(), gate.holding_dispatch(A1):
            check_eq("the driver's road: held dispatch picks its own among two", gate._live_dispatch("qa-automator", TICKET)["id"], A1)
    finally:
        gate.detector_gates, gate.all_errors = saved
        s.close()


def detector_two_running_no_name_unreadable_never_every_case():
    s = Story(TWO)
    calls = []
    saved = (S5.run, S5.is_plan_dispatch, S5.report)
    try:
        S5.run = lambda root, dispatch=None: calls.append(dispatch) or {"ok": True}
        S5.is_plan_dispatch = lambda root, dispatch: False
        S5.report = lambda result: 0
        story_env = os.environ.get(PC.DETECTOR_STORY_ENV)
        os.environ[PC.DETECTOR_STORY_ENV] = str(s.task)
        try:
            out = io.StringIO()
            with envs(), contextlib.redirect_stdout(out):
                code = S5.detector_main()
            check_eq("detector_two_running_no_name: exit UNREADABLE", code, DV.EXIT_UNREADABLE)
            check_in("detector_two_running_no_name: the UNREADABLE line", "UNREADABLE", out.getvalue())
            check_in("detector_two_running_no_name: says what it was not told",
                     "two or more windows are running and this check was not told whose handoff it judges", out.getvalue())
            check_eq("detector_two_running_no_name: run() was never called (never every case)", calls, [])
            with envs(driver=A2), contextlib.redirect_stdout(io.StringIO()):
                code = S5.detector_main()
            check_eq("control: the same story with a name judges that window", (code, calls), (0, [A2]))
            calls.clear()
            with envs(driver=C1), contextlib.redirect_stdout(io.StringIO()):
                code = S5.detector_main()
            check_eq("a name that fits no window while two run: unreadable, run() not called", (code, calls), (DV.EXIT_UNREADABLE, []))
        finally:
            if story_env is None:
                os.environ.pop(PC.DETECTOR_STORY_ENV, None)
            else:
                os.environ[PC.DETECTOR_STORY_ENV] = story_env
    finally:
        S5.run, S5.is_plan_dispatch, S5.report = saved
        s.close()
    # zero running with no name keeps today's road (run(root, None)): the control on the other side of the line
    s = Story({A1: rec(A1, "accepted")})
    saved = (S5.run, S5.is_plan_dispatch, S5.report)
    try:
        calls = []
        S5.run = lambda root, dispatch=None: calls.append(dispatch) or {"ok": True}
        S5.is_plan_dispatch = lambda root, dispatch: False
        S5.report = lambda result: 0
        os.environ[PC.DETECTOR_STORY_ENV] = str(s.task)
        try:
            with envs(), contextlib.redirect_stdout(io.StringIO()):
                code = S5.detector_main()
            check_eq("zero running, no name: today's road, run(root, None)", (code, calls), (0, [None]))
        finally:
            os.environ.pop(PC.DETECTOR_STORY_ENV, None)
    finally:
        S5.run, S5.is_plan_dispatch, S5.report = saved
        s.close()


def digest_scope_read_with_two_automators():
    s = Story(TWO)
    try:
        with envs(driver=A2):
            check_eq("digest_scope_read_with_two_automators: named, its own scope", gate.dispatch_scope("qa-automator", TICKET), ["TC-002"])
            check_eq("digest_scope_read_with_two_automators: and its own record", gate._live_dispatch("qa-automator", TICKET)["id"], A2)
        with envs(detector=A1, driver=A2):
            check_eq("digest_scope_read_with_two_automators: the gate's word first", gate.dispatch_scope("qa-automator", TICKET), ["TC-001"])
        with envs():
            check_eq("digest_scope_read_with_two_automators: control, nobody named: no scope, as before",
                     gate.dispatch_scope("qa-automator", TICKET), [])
        with envs(driver=A2), gate.holding_dispatch(A1):
            check_eq("a held dispatch (the caller's own) wins over the inherited word", gate.dispatch_scope("qa-automator", TICKET), ["TC-001"])
    finally:
        s.close()


def the_pure_reader_on_awkward_input():
    with envs():
        for label, value in (("None", None), ("a string", "x"), ("an int", 3), ("empty list", []), ("empty dict", {}),
                             ("list of non-dicts", [1, "a", None, [2]]), ("dict of non-dicts", {"a": 1, "b": None})):
            check_eq(f"no raise, none: {label}", DI.own(value, "qa-automator", "S5"), None)
        check_eq("a list of records is read", DI.own([rec(A1)], "qa-automator", "S5")["id"], A1)
        check_eq("non-dicts beside one record are ignored", DI.own([None, 4, rec(A1)], "qa-automator", "S5")["id"], A1)
        check_eq("the id is filled from the mapping key", DI.own({"k": {"status": "running", "role": "r", "stage": "s"}}, "r", "s")["id"], "k")
        check_eq("the id is filled from dispatch_id", DI.own([{"dispatch_id": "d", "status": "running"}])["id"], "d")
        check_eq("role and stage are not asked when blank", DI.own([rec(A1)])["id"], A1)
        check_eq("a record with a non-string id does not raise", DI.own([{"id": 5, "status": "running"}]) is not None, True)
    with envs(driver=A1):
        check_eq("a name over non-dict dispatches: none, no raise", DI.own([None, 1]), None)
        check_eq("a duplicated name: none (never a pick between two)", DI.own([rec(A1), rec(A1)], "qa-automator", "S5"), None)
        check_eq("named() reads the word", DI.named(), A1)
        check_eq("a blank name= argument is no name: falls to the environment word", DI.own([rec(A1), rec(A2)], name="  ")["id"], A1)


def handoff_gates_its_own_dispatch_not_the_last():
    """t-2087 F1: `Driver.exit_errors` holds the dispatch `handoff` passes, never `last_dispatch`. The critic's three probe inputs,
    over the REAL `s5_precheck.window_dispatch` and `exit_gate.dispatch_scope` (only `all_errors` itself is replaced to read them)."""
    import story_run
    rows = (
        ("serial, stale accepted critic held as last_dispatch",
         {C1: rec(C1, "accepted", role="qa-code-critic", scope=["TC-9"]), A2: rec(A2, scope=["TC-2"])}, C1),
        ("two windows, the first held as last_dispatch", TWO, A1),
        ("two windows, a fresh process (no last_dispatch at all)", TWO, None),
    )
    for label, dispatches, last in rows:
        s = Story(dispatches)
        seen = {}
        saved = gate.all_errors
        try:
            def fake_all_errors(role, task, digest):
                # the detector is a child process that gets the held dispatch as its environment word (`_detector_env`)
                with envs(detector=gate._detector_env(task).get(DETECTOR_ENV)):
                    seen["window"] = S5.window_dispatch(s.task)
                seen["scope"] = gate.dispatch_scope(role, task)
                seen["held"] = gate.held_dispatch()
                return [], []
            gate.all_errors = fake_all_errors
            driver = object.__new__(story_run.Driver)
            driver.task = TICKET
            if last is not None:
                driver.last_dispatch = last
            with envs():
                driver.exit_errors("qa-automator", "digest", A2)
            check_eq(f"handoff_gates_its_own_dispatch [{label}]: the gate judges the dispatch it was given",
                     (seen.get("held"), seen.get("window"), seen.get("scope")), (A2, A2, dispatches[A2]["scope"]))
            check_eq(f"handoff_gates_its_own_dispatch [{label}]: restored after", gate.held_dispatch(), "")
        finally:
            gate.all_errors = saved
            s.close()
    # `handoff` passes ITS dispatch to every gate call, and the hold is not around the rest of `handoff` (a process global)
    calls, held_in_ladder = [], []
    driver = object.__new__(story_run.Driver)
    driver.task, driver.last_dispatch = TICKET, A1
    driver.exit_errors = lambda role, digest, dispatch=None: calls.append(dispatch) or []
    driver.form_errors = lambda dispatch: []
    driver.revoke_passes_of_dead = lambda: None
    driver.handoff_ladder = lambda *a: held_in_ladder.append(gate.held_dispatch()) or "ladder"
    out = driver.handoff("qa-automator", "S5", A2, {"is_error": False, "result": "digest text", "exit_code": 0, "stderr": ""})
    check_eq("handoff passes its own dispatch to the exit gate, not last_dispatch", (out, calls), ("ladder", [A2]))
    check_eq("handoff: nothing is held when it goes on to the ladder (which resumes the role)", held_in_ladder, [""])


def one_spelling_of_the_name_lookup_and_no_heavy_import():
    check_eq("held(): the records of a name, [] for no name", ([r["id"] for r in DI.held(TWO, A1)], DI.held(TWO, None)), ([A1], []))
    check_eq("held(): a duplicated name is both records (the caller decides)", len(DI.held([rec(A1), rec(A1)], A1)), 2)
    check_eq("held(): awkward input is [] and does not raise", (DI.held(None, A1), DI.held("x", A1), DI.held([1, None], A1)), ([], [], []))
    with envs(driver=A2):
        check_eq("held(): the environment name by default", [r["id"] for r in DI.held(TWO)], [A2])
    check_eq("the gate's word has ONE literal, here, and planning_contract agrees", DI.DETECTOR_DISPATCH_ENV, PC.DETECTOR_DISPATCH_ENV)
    import subprocess
    code = ("import sys; sys.path.insert(0, sys.argv[1]); import dispatch_identity as D; D.named(); "
            "print(sorted(m for m in ('planning_contract', 'contract', 'grammar') if m in sys.modules))")
    run = subprocess.run([sys.executable, "-B", "-c", code, str(PLUGIN_ROOT / "scripts")], capture_output=True, text=True, timeout=60)
    check_eq("named() imports nothing beyond os (AR-12: it runs at every hook)", run.stdout.strip(), "[]")


def main() -> None:
    handoff_gates_its_own_dispatch_not_the_last()
    one_spelling_of_the_name_lookup_and_no_heavy_import()
    named_wins_over_count()
    detector_dispatch_beats_driver_run()
    env_other_role_is_none_not_count()
    closed_dispatch_named_is_none()
    unknown_id_falls_to_count()
    no_env_one_running_same_as_today()
    no_env_two_running_none()
    blank_env_is_unset()
    returned_named_found_only_when_asked()
    finish_with_two_automators_judges_own_scope()
    detector_two_running_no_name_unreadable_never_every_case()
    digest_scope_read_with_two_automators()
    the_pure_reader_on_awkward_input()
    finish("test_dispatch_identity")


if __name__ == "__main__":
    main()
