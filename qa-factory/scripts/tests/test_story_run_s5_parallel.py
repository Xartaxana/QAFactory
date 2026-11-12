#!/usr/bin/env python3
"""t-1937 TR3-6 (the 17 CI keys) and TR3-18 (the equivalence suite and the seams at the default 3): the S5 window scheduler of the
driver, end to end through a REAL `Driver`, real threads and REAL `claude` stub processes (`story_run_common.STUB` with its marks and
barrier), over a stand-in for the controller's S5 record (`World`).

What is real: `stage_S5`, `run_chains`, `unbooked`, the launch gate, `run_role`, `run_claude`, `_launch` (one stub process per
session), `finish`, `s5_window`, `s5_review`, `s5_mechanical_round`, `s5_open_windows`, `s5_serial_reason`, `s5_seam`, `save_state`.
What is a stand-in (one place each, `World.install`): `py` (the `story_step.py` verbs start / bind / finish; every other script
answers 0), `controller_state`, `stage_scope`, `route_of` (the critic's verdict as a list per window), `budget_or_none`, `rework` (it
registers the round and runs `run_role`), `stand_check`, `build_check`, `question_threshold`, `repair_limit_gate`, `handoff`,
`system_file`. The controller's own side of the windows is `test_s5_parallel_admission.py` (fast); the lock, the seam order and the
gate with fake `step` / `launch` are `test_driver_chain.py` (fast). This file proves them together.

Determinism (M5): no sleep decides an assertion. A call waits for its peers at a BARRIER (stub marks), a hold ends on a file the
test writes when it has seen the event it waits for, and every wait has a cap that fails with a named message. Assertions are on
the ORDER of marks (their position in one file), never on wall clock.

This file is CI's (`story_run_*` is a slow-tier name): a builder never runs it locally (plans/builder-rules.md 7b).
"""
import contextlib
import io
import json
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import check, check_eq, check_in  # noqa: E402
from story_run_common import driver_for, seed, set_control, stub_calls  # noqa: E402

sys.path.insert(0, str(harness.SCRIPTS))
import story_run as SR  # noqa: E402

KEY = "QA-9"
AUTO, CRIT = "qa-automator", "qa-code-critic"
START = ("dispatched {id} (revision 1)\n--- Agent prompt, verbatim ---\nArtifacts dir: {root}\nDispatch: {id}.\n"
         "--- the moment the Agent call returns ---\n")


def flags(args) -> dict:
    out, items, i = {}, list(args), 0
    while i < len(items):
        if str(items[i]).startswith("--"):
            if i + 1 < len(items) and not str(items[i + 1]).startswith("--"):
                out[items[i]] = items[i + 1]
                i += 1
            else:
                out[items[i]] = True
        i += 1
    return out


class World:
    """The controller's S5 record as the driver reads it, kept by the fake `py`. `cases` are the windows (lists, stage-scope order)."""

    def __init__(self, task_root, cases):
        self.task_root, self.lock = task_root, threading.RLock()
        self.cases = [list(c) for c in cases]
        self.accepted = {self.key(c): {} for c in self.cases}
        self.dispatches, self.events, self.finishes, self.counter, self.rounds = {}, [], [], {}, {}
        self.routes = {}              # window key -> [critic verdicts in order]; absent: close
        self.refuse_finish = {}       # (window key, role) -> how many finishes are refused with exit 1
        self.crash_on_finish = {}     # (window key, role) -> the exception its finish raises
        self.stand_person = {}        # case -> the question the stand check raises
        self.person_after = {}        # case -> the question `question_threshold` raises for that window's author
        self.stand_calls, self.stand_main = [], []
        self.cause_of = {}            # (window key, role) -> the cause of the rework about to start that round
        self.shared = False
        self.shared_files = None      # dict window key -> files; None: `shared` decides

    @staticmethod
    def key(cases) -> tuple:
        return tuple(sorted(cases))

    def windows(self):
        with self.lock:
            return [{"scope": list(c), "accepted_by": dict(self.accepted[self.key(c)])} for c in self.cases]

    def closed(self) -> bool:
        with self.lock:
            return all(CRIT in a for a in self.accepted.values())

    def route_action(self, did) -> str:
        rec = self.dispatches.get(did) or {}
        key = self.key(rec.get("scope") or [])
        critics = [d for d, r in self.dispatches.items() if r["role"] == CRIT and self.key(r["scope"]) == key]
        order = self.routes.get(key) or []
        index = critics.index(did) if did in critics else 0
        return order[index] if index < len(order) else "close"

    def py(self, script, *args, check=False, expect=""):
        if script != "story_step.py" or not args:
            return 0, ""
        verb, opts = args[0], flags(args)
        with self.lock:
            if verb == "start":
                role = opts["--role"]
                scope = [c for c in str(opts.get("--scope", "")).split(",") if c]
                same = [d for d, r in self.dispatches.items() if r["role"] == role and r["status"] == "running"
                        and self.key(r["scope"]) == self.key(scope)]
                if same:                               # a start over a running dispatch of the window is its resume, as the controller answers
                    did = same[0]
                else:
                    self.counter[role] = self.counter.get(role, 0) + 1
                    did = f"S5-{role}-{self.counter[role]}"
                    self.dispatches[did] = {"id": did, "stage": "S5", "role": role, "status": "running", "scope": scope,
                                            "parallel_window": bool(opts.get("--parallel-window"))}
                    cause = self.cause_of.pop((self.key(scope), role), None)
                    if cause:                          # the controller copies the rework's cause onto the record (controller.py:3726-3727)
                        self.dispatches[did]["repair_cause"] = cause
                self.events.append(("start", did))
                return 0, START.format(id=did, root=self.task_root)
            if verb == "finish":
                did = opts["--dispatch-id"]
                rec = self.dispatches[did]
                key = self.key(rec["scope"])
                others_open = [k for k, a in self.accepted.items() if k != key and CRIT not in a]
                row = {"id": did, "role": rec["role"], "key": key, "args": [str(a) for a in args], "others_open": others_open}
                self.finishes.append(row)
                if self.crash_on_finish.get((key, rec["role"])):
                    self.events.append(("crash", did))
                    raise self.crash_on_finish.pop((key, rec["role"]))
                if self.refuse_finish.get((key, rec["role"]), 0) > 0:
                    self.refuse_finish[(key, rec["role"])] -= 1
                    row["refused"] = True
                    return 1, "story_step finish: refused (the stub's refusal)"
                rec["status"] = "accepted"
                if rec["role"] == AUTO:
                    self.accepted[key][AUTO] = did
                elif self.route_action(did) in ("close", "mechanical"):
                    self.accepted[key][CRIT] = did
                self.events.append(("finish", did))
                return 0, f"accepted {did}\nnext: {{}}"
        return 0, ""

    def controller_state(self):
        with self.lock:
            return {"dispatches": {k: dict(v) for k, v in self.dispatches.items()}}

    def stage_scope(self, stage, kind=""):
        return {"scope": [c for w in self.cases for c in w], "windows": self.windows()}

    def route_of(self, text, budget, dispatch=""):
        action = self.route_action(dispatch or "")
        return {"action": action, "reason": f"{action} (the stub's verdict)", "not_rounds": [], "note": "", "code": ""}, None

    def budget(self, stage, role, scope, ref="", **packet):
        return {"counted": self.rounds.get(self.key(scope or []), 0), "cap": 3, "mechanical": 0, "mechanical_cap": 1}

    def files_of(self, cases):
        key = self.key(cases)
        if self.shared_files is not None:
            return set(self.shared_files.get(key, ()))
        return {"tests/shared.py"} if self.shared else set()

    def question_threshold(self, stage, role, dispatch):
        scope = (self.dispatches.get(dispatch) or {}).get("scope") or []
        for case in scope:
            if role == AUTO and self.person_after.get(case):
                with self.lock:
                    self.events.append(("person", dispatch))
                raise SR.Person("threshold", self.person_after[case], stage, dispatch)

    def install(self, driver):
        self.driver = driver
        real_run_role = driver.run_role

        def stand_check(stage, kind=""):
            parts = str(driver.boundary).split(":", 1)       # a chain sets `S5:<cases>` before its checks; the serial road sets it after them
            case = parts[1] if len(parts) > 1 else ""
            with self.lock:
                self.stand_calls.append(case)
                self.stand_main.append(threading.current_thread() is threading.main_thread())
            if self.stand_person.get(case):
                with self.lock:
                    self.events.append(("person", "stand:" + case))
                raise SR.Person("stand", self.stand_person[case], stage)

        def rework(stage, role, cases, reason, *, cause, extra=(), complete=False, budget=SR.READ_BUDGET, **_kw):
            with self.lock:
                if cause == "test_defect":
                    self.rounds[self.key(cases)] = self.rounds.get(self.key(cases), 0) + 1
                if cause:
                    self.cause_of[(self.key(cases), role)] = cause
            try:
                return real_run_role(stage, role, scope=list(cases), extra=list(extra), complete=complete, budget=budget)
            finally:
                with self.lock:
                    self.cause_of.pop((self.key(cases), role), None)
        driver.py, driver.controller_state, driver.stage_scope = self.py, self.controller_state, self.stage_scope
        driver.route_of, driver.budget_or_none, driver.s5_window_files = self.route_of, self.budget, self.files_of
        driver.stand_check, driver.build_check, driver.rework = stand_check, lambda *a, **k: None, rework
        driver.question_threshold = self.question_threshold
        driver.repair_limit_gate = lambda *a, **k: None
        driver.handoff = lambda role, stage, dispatch, result: result["result"]
        driver.system_file = lambda role, dispatch, scope: None
        return self


def control(automator=None, critic=None, **top) -> dict:
    return dict({"marks": True, "roles": {AUTO: dict({"result": "qa-automator S5 window · ok"}, **(automator or {})),
                                          CRIT: dict({"result": "qa-code-critic S5 window · ok"}, **(critic or {}))}}, **top)


def barrier(need=3, name="n3") -> dict:
    return {"barrier": {"name": name, "need": need, "cap": 30}}


def rig(cases, *, parallel_windows=None, dispatch=None, ctl=None, strip_dispatch=False):
    root, task_root, env = seed(KEY, parallel_windows=parallel_windows, dispatch=dispatch)
    if strip_dispatch:
        path = root / "qa-factory" / "config.json"
        cfg = json.loads(path.read_text(encoding="utf-8"))
        cfg.pop("dispatch", None)
        path.write_text(json.dumps(cfg), encoding="utf-8")
    set_control(root, ctl if ctl is not None else control())
    driver = driver_for(root, env, KEY, max_boundaries=1000)
    world = World(task_root, cases)
    world.install(driver)
    return root, driver, world


def enter(driver, out=None):
    out = out if out is not None else io.StringIO()
    error = None
    with contextlib.redirect_stdout(out):
        try:
            driver.stage_S5()
        except BaseException as exc:      # noqa: BLE001 - the case reads what the stage raised
            error = exc
    return error, out.getvalue()


def until_closed(driver, world, limit=6):
    """Enter the stage as the main loop does, until every window is closed; returns the list of (error, console) of the entries."""
    got = []
    for _ in range(limit):
        if world.closed():
            break
        got.append(enter(driver))
        if any(isinstance(e, KeyboardInterrupt) for e, _o in got):
            break
    return got


def marks(root) -> list:
    path = root / "stub-log.jsonl.marks"
    rows = []
    for line in (path.read_text(encoding="utf-8").splitlines() if path.exists() else []):
        try:
            rows.append(json.loads(line))
        except ValueError:
            pass
    return rows


def pos(rows, event, role=None, dispatch=None) -> list:
    return [i for i, r in enumerate(rows) if r["event"] == event and (role is None or r["role"] == role)
            and (dispatch is None or r["dispatch"] == dispatch)]


def timeouts(rows) -> list:
    return [r for r in rows if str(r["event"]).endswith("_timeout")]


def release_when(path, cond, cap=25):
    box = {"met": False}

    def target():
        stop = time.monotonic() + cap
        while time.monotonic() < stop:
            if cond():
                box["met"] = True
                break
            time.sleep(0.05)
        Path(path).write_text("go", encoding="utf-8")
    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    return box, thread


def completes(world) -> list:
    return [f for f in world.finishes if "--complete" in f["args"]]


def roles_by_window(world) -> dict:
    out = {}
    for did, rec in world.dispatches.items():
        out.setdefault(",".join(sorted(rec["scope"])), []).append(rec["role"])
    return out


THREE = [["TC-1"], ["TC-2"], ["TC-3"]]


# --- the 17 keys of TR3-6 ---------------------------------------------------------------------------------------------------------
def n3_three_automators_overlap():
    root, driver, world = rig(THREE, ctl=control(automator=barrier(3)))
    try:
        error, out = enter(driver)
        rows = marks(root)
        check("n3: the stage returned without an exception", error is None, repr(error))
        check("n3: no barrier timed out", not timeouts(rows), str(timeouts(rows)))
        starts, ends = pos(rows, "start", AUTO), pos(rows, "end", AUTO)
        check("n3: three automator sessions were at work at once (all started before any ended)", len(starts) == 3 and ends and max(starts) < min(ends), f"{starts} {ends}")
        check("n3: every window closed", world.closed())
        check_in("n3: console lines of a chain carry [W1]", "[W1] ", out)
    finally:
        harness.cleanup(root)


def no_thread_started_at_n1():
    root, driver, world = rig(THREE, parallel_windows=1)
    try:
        called = []
        driver.run_chains = lambda *a, **k: called.append(1)
        got = until_closed(driver, world)
        check("n1: parallel_windows 1 never enters the scheduler", not called)
        check("n1: every stand check ran on the main thread", world.stand_main and all(world.stand_main), str(world.stand_main))
        check("n1: no chain was registered, no [W prefix on the console", not driver._chains and not any("[W" in o for _e, o in got))
        check("n1: every window closed through the old body, one finish closed the stage", world.closed() and len(completes(world)) == 1)
    finally:
        harness.cleanup(root)


def crash_in_one_window_others_finish():
    root, driver, world = rig(THREE, ctl=control(automator=barrier(3)))
    try:
        world.crash_on_finish[(("TC-2",), AUTO)] = OSError("disk full (the stub's crash)")
        error, out = enter(driver)
        crash = [i for i, e in enumerate(world.events) if e[0] == "crash"]
        check("crash: the crash is the one exception the stage raises", isinstance(error, OSError), repr(error))
        check("crash: a crash was recorded and no dispatch started after it", len(crash) == 1 and not [e for e in world.events[crash[0] + 1:] if e[0] == "start"], str(world.events))
        check("crash: the other windows' running sessions finished and booked", all(AUTO in world.accepted[(c,)] for c in ("TC-1", "TC-3")), str(world.accepted))
        crashed = next(d for d, r in world.dispatches.items() if r["scope"] == ["TC-2"])
        check_eq("crash: the main thread adopted the crashed chain's last dispatch", driver.last_dispatch, crashed)
    finally:
        harness.cleanup(root)


def person_in_one_window_drains_then_asks_once():
    root, driver, world = rig(THREE, ctl=control(automator=barrier(3)))
    try:
        world.person_after["TC-2"] = "Which stand should the tests run on?"
        error, out = enter(driver)
        asked = [i for i, e in enumerate(world.events) if e[0] == "person"]
        check("person: the question is raised once, on the main thread", isinstance(error, SR.Person) and error.text == world.person_after["TC-2"], repr(error))
        check("person: asked once and nothing started after it", len(asked) == 1 and not [e for e in world.events[asked[0] + 1:] if e[0] == "start"], str(world.events))
        check("person: the other windows' running sessions finished and booked", all(AUTO in world.accepted[(c,)] for c in ("TC-1", "TC-3")))
        world.person_after.clear()
        later = until_closed(driver, world)
        check("person: after the answer the story goes on and closes, no second question", world.closed() and not any(isinstance(e, SR.Person) for e, _o in later), str([e for e, _o in later]))
        check_eq("person: one question in all", len([e for e in world.events if e[0] == "person"]), 1)
    finally:
        harness.cleanup(root)


def queued_question_asked_next():
    root, driver, world = rig(THREE, ctl=control(automator=barrier(3)))
    try:
        world.person_after.update({"TC-1": "first question?", "TC-2": "second question?"})
        error, out = enter(driver)
        check_eq("queued: the lowest window's question is asked first", getattr(error, "text", repr(error)), "first question?")
        check_in("queued: the other question is named on the console, not dropped", "also ended with Person", out)
        del world.person_after["TC-1"]
        error, out = enter(driver)
        check_eq("queued: the other question is asked on the next entry, whatever the first answer was", getattr(error, "text", repr(error)), "second question?")
        del world.person_after["TC-2"]
        later = until_closed(driver, world)
        check("queued: then the story closes", world.closed() and not any(isinstance(e, SR.Person) for e, _o in later))
    finally:
        harness.cleanup(root)


def round_in_w1_blocks_close_by_w2():
    root, driver, world = rig([["TC-1"], ["TC-2"]])
    try:
        release = root / "release-round"
        ctl = control(automator=dict(barrier(2), by_prompt={"Repair round": {"barrier": None, "hold_until": {"file": str(release), "cap": 30}}}))
        set_control(root, ctl)
        world.routes[("TC-1",)] = ["test_defect", "close"]
        box, thread = release_when(release, lambda: any(f["role"] == CRIT and f["key"] == ("TC-2",) for f in world.finishes))
        error, out = enter(driver)
        thread.join(5)
        check("round: the stage returned without an exception", error is None, repr(error))
        w2 = [f for f in world.finishes if f["role"] == CRIT and f["key"] == ("TC-2",)]
        check("round: W2's critic did not close S5 while W1 was in its round (--not-complete)", w2 and "--not-complete" in w2[0]["args"] and "--complete" not in w2[0]["args"], str(w2))
        done = completes(world)
        check("round: exactly one finish closed S5 and it was W1's second review", len(done) == 1 and done[0]["key"] == ("TC-1",) and done[0]["role"] == CRIT, str(done))
        check("round: W1 was reviewed twice", len([f for f in world.finishes if f["role"] == CRIT and f["key"] == ("TC-1",)]) == 2)
        check("round: the release came from W2's finish (the event was met, not capped)", box["met"])
    finally:
        harness.cleanup(root)


def mechanical_last_with_other_chain_open():
    root, driver, world = rig([["TC-1"], ["TC-2"]])
    try:
        release = root / "release-w2"
        set_control(root, control(automator={"by_scope": {"TC-2": {"hold_until": {"file": str(release), "cap": 30}}}}))
        world.routes[("TC-1",)] = ["mechanical"]
        box, thread = release_when(release, lambda: len([f for f in world.finishes if f["role"] == AUTO and f["key"] == ("TC-1",)]) >= 2)
        error, out = enter(driver)
        thread.join(5)
        check("mechanical: the stage returned without an exception", error is None, repr(error))
        mech = [f for f in world.finishes if f["role"] == AUTO and f["key"] == ("TC-1",)]
        check("mechanical: the mechanical round finished --not-complete while W2 was still open", len(mech) == 2 and "--not-complete" in mech[1]["args"], str(mech))
        check("mechanical: no critic was dispatched again for W1", len([f for f in world.finishes if f["role"] == CRIT and f["key"] == ("TC-1",)]) == 1)
        done = completes(world)
        check("mechanical: S5 closed once, by W2's critic", len(done) == 1 and done[0]["key"] == ("TC-2",), str(done))
        check("mechanical: the release came from the round's finish", box["met"])
    finally:
        harness.cleanup(root)


def exactly_one_close_order_free():
    for order in (["TC-1", "TC-2", "TC-3"], ["TC-3", "TC-2", "TC-1"]):
        root, driver, world = rig(THREE)
        try:
            files = {c: root / f"release-{c}" for c in order}
            set_control(root, control(critic={"by_scope": {c: {"hold_until": {"file": str(files[c]), "cap": 40}} for c in order}}))
            threads = []
            for i, case in enumerate(order):
                before = order[i - 1] if i else None
                cond = ((lambda b=before: any(f["role"] == CRIT and f["key"] == (b,) for f in world.finishes)) if before else
                        (lambda: len(pos(marks(root), "start", CRIT)) >= 3))
                threads.append(release_when(files[case], cond, cap=35)[1])
            error, out = enter(driver)
            for t in threads:
                t.join(5)
            done = completes(world)
            check(f"close {order}: no exception", error is None, repr(error))
            check(f"close {order}: exactly one finish closed S5, the last window to finish", len(done) == 1 and done[0]["key"] == (order[-1],), str(done))
            check(f"close {order}: every window closed", world.closed())
        finally:
            harness.cleanup(root)


def stage_closes_only_after_last_window():
    root, driver, world = rig(THREE, ctl=control(automator=barrier(3)))
    try:
        error, out = enter(driver)
        done = completes(world)
        critics = [f for f in world.finishes if f["role"] == CRIT]
        check("last: no exception", error is None, repr(error))
        check("last: the one closing finish saw every other window closed", len(done) == 1 and done[0]["others_open"] == [], str(done))
        check("last: every other critic finish left S5 open while a window was open", all("--complete" in f["args"] or f["others_open"] for f in critics), str(critics))
    finally:
        harness.cleanup(root)


def config_absent_reads_three():
    root, driver, world = rig(THREE, ctl=control(automator=barrier(3)), strip_dispatch=True)
    try:
        check_eq("config absent: the cap reads 3", driver.s5_parallel_cap(), 3)
        error, out = enter(driver)
        check("config absent: three windows ran at once (the barrier of 3 passed)", error is None and not timeouts(marks(root)) and world.closed(), repr(error))
        check("config absent: no note about the key", "parallel_windows" not in out)
    finally:
        harness.cleanup(root)


def config_invalid_reads_three_with_note():
    root, driver, world = rig(THREE, ctl=control(automator=barrier(3)), dispatch={"parallel_windows": "many"})
    try:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            first, second = driver.s5_parallel_cap(), driver.s5_parallel_cap()
        check_eq("config invalid: the cap reads 3", (first, second), (3, 3))
        check_eq("config invalid: one note, not two", out.getvalue().count("not a whole number"), 1)
        error, _o = enter(driver)
        check("config invalid: three windows ran at once", error is None and not timeouts(marks(root)) and world.closed(), repr(error))
    finally:
        harness.cleanup(root)


def refusal_retry_on_main_reads_chain():
    root, driver, world = rig([["TC-1"], ["TC-2"]])
    try:
        world.refuse_finish[(("TC-1",), CRIT)] = 1
        error, out = enter(driver)
        check("retry: the refusal of W1's critic finish is the stage's exception", isinstance(error, SR.Refusal) and error.chain is not None, repr(error))
        check_eq("retry: the main thread reads the chain's last dispatch, not its own empty one", driver.last_dispatch, error.dispatch)
        # the boundary a chain leaves is the one `run_role` sets for its last dispatch (`<stage>:<dispatch>`, story_run :3158), so the
        # refused dispatch's own boundary is exact: another window's dispatch would name another id
        check_eq("retry: the boundary is the refused dispatch's own (S5:<its dispatch id>), not another window's",
                 str(driver.boundary), "S5:" + (error.dispatch or "<no dispatch>"))
        check_eq("retry: and that dispatch is window W1's critic", (world.dispatches.get(error.dispatch) or {}).get("scope"), ["TC-1"])
        digest, _next = error.retry()
        rows = [f for f in world.finishes if f["id"] == error.dispatch]
        check("retry: the finish ran again on the main thread and the dispatch is accepted", len(rows) == 2 and world.dispatches[error.dispatch]["status"] == "accepted", str(rows))
    finally:
        harness.cleanup(root)


def stand_person_in_chain_re_arises():
    root, driver, world = rig(THREE)
    try:
        world.stand_person["TC-2"] = "Is the stand up?"
        first, _o = enter(driver)
        second, _o = enter(driver)
        check("stand: the question is raised", isinstance(first, SR.Person) and first.text == "Is the stand up?", repr(first))
        check("stand: it re-arises on the next entry (the state did not change)", isinstance(second, SR.Person) and second.text == first.text, repr(second))
        check("stand: no role was started for the window whose stand is not confirmed", not [d for d in world.dispatches.values() if d["scope"] == ["TC-2"]])
        del world.stand_person["TC-2"]
        later = until_closed(driver, world)
        check("stand: once confirmed the story closes", world.closed() and not any(e for e, _o in later), str([e for e, _o in later]))
    finally:
        harness.cleanup(root)


def driver_interrupt_kills_children():
    root, driver, world = rig([["TC-1"], ["TC-2"]], ctl=control(automator={"hold_until": {"file": "never-written", "cap": 20}}))
    spawned, real = [], subprocess.Popen

    class Spy(real):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            spawned.append(self)
    class CtrlC(threading.Condition):
        """The Ctrl-C, delivered where it is delivered: the MAIN thread's own wait raises KeyboardInterrupt once both sessions are at work.
        (`_thread.interrupt_main` does nothing under CI, where SIGINT is ignored by the job's shell.)"""

        def wait(self, timeout=None):
            if threading.current_thread() is threading.main_thread() and len(pos(marks(root), "start", AUTO)) >= 2:
                raise KeyboardInterrupt()
            return super().wait(timeout)
    try:
        subprocess.Popen = Spy
        driver.__dict__["_book_cond"] = CtrlC(driver._book)
        error, out = enter(driver)
    finally:
        subprocess.Popen = real
    try:
        stubs = [p for p in spawned if any("fake_claude" in str(a) for a in p.args)]
        rows = marks(root)
        check("interrupt: the stage raised KeyboardInterrupt", isinstance(error, KeyboardInterrupt), repr(error))
        check("interrupt: two sessions were running and both were killed (exited non-zero)", len(stubs) == 2 and all(p.returncode not in (None, 0) for p in stubs), str([p.returncode for p in stubs]))
        check("interrupt: neither session reached its end mark, nothing started after", not pos(rows, "end", AUTO) and len(pos(rows, "start", AUTO)) == 2 and not timeouts(rows), str(rows))
        check("interrupt: the flag stands", driver._interrupted.is_set())
    finally:
        harness.cleanup(root)


def critic_probe_waits_for_file_holder():
    root, driver, world = rig([["TC-1"], ["TC-2"]])
    try:
        release = root / "release-critic"
        set_control(root, control(automator=barrier(2), critic={"hold_until": {"file": str(release), "cap": 30}}))
        out = io.StringIO()
        orig_py = driver.py

        def py(script, *args, **kw):
            result = orig_py(script, *args, **kw)
            if script == "story_step.py" and args and args[0] == "finish" and flags(args).get("--dispatch-id", "").startswith("S5-qa-automator"):
                world.shared = True               # the first author's files are known once it booked: both windows now hold shared.py
            return result
        driver.py = py
        box, thread = release_when(release, lambda: "waits for window" in out.getvalue())
        error, _o = enter(driver, out)
        thread.join(5)
        rows = marks(root)
        starts, ends = pos(rows, "start", CRIT), pos(rows, "end", CRIT)
        check("probe: the stage returned without an exception", error is None, repr(error))
        check("probe: the second critic session waited (the console says so) until the holder was released", box["met"])
        check("probe: the two critic sessions never overlapped", len(starts) == 2 and sorted(starts)[1] > min(ends), f"{starts} {ends}")
        check("probe: every window closed", world.closed())
    finally:
        harness.cleanup(root)


def stand_busy_is_not_a_window_failure():
    text = "qa-automator S5 window · ok\nstand busy: waited 30 minutes for the stand queue; the tests are not at fault"
    root, driver, world = rig([["TC-1"], ["TC-2"]], ctl=control(automator={"result": text}))
    try:
        error, out = enter(driver)
        brief = [c["prompt"] for c in stub_calls(root) if c["kind"] == "role" and c["role"] == AUTO]
        check("stand busy: no window failed, no drain", error is None and world.closed(), repr(error))
        check("stand busy: both windows went on to their critics", len([d for d in world.dispatches.values() if d["role"] == CRIT]) == 2)
        check("stand busy: the brief tells the role a busy stand is not its failure", brief and all("stand busy" in p and "not a failure" in p for p in brief))
    finally:
        harness.cleanup(root)


def ticket_rework_owed_after_drain():
    root, driver, world = rig([["TC-1"], ["TC-2"]])
    try:
        owed = {"stages": ["S2", "S3"], "words": "use the new ticket text", "at": "2026-11-10T00:00:00", "before": []}
        driver.state["ticket_rework"] = dict(owed)
        driver.save_state()
        seen = []
        driver.ticket_rework_step = lambda: seen.append(1) or False
        world.person_after["TC-2"] = "Which stand?"
        error, out = enter(driver)
        stored = json.loads((driver.state_dir / "driver-state.json").read_text(encoding="utf-8"))
        check("ticket rework: the drain ended in the person's question", isinstance(error, SR.Person), repr(error))
        check("ticket rework: no per-turn step ran inside the stage", not seen)
        check_eq("ticket rework: the owed record is untouched in memory and on disk", (driver.state.get("ticket_rework"), stored.get("ticket_rework")), (owed, owed))
    finally:
        harness.cleanup(root)


# --- TR3-18: equivalence and the seams at the default ---------------------------------------------------------------------------------
# The two lines a chain's brief carries on top of the serial one (`story_run.s5_auto_extra`, the `if chain` block): the one prompt difference
# between N=1 and N=3 that the design makes. Quoted whole; the compare strips them, so any OTHER difference stays visible.
CHAIN_ONLY_LINES = (
    "Other windows of this story are written at the same time. A test file one of them wrote first refuses your "
    "Write or Edit: put your test in a new file in the same directory; where a test lives stays your choice, "
    "and a test in a new file is judged the same.",
    "A run that answers `stand busy` after some minutes waited for the stand queue: it is not a failure of your "
    "tests. Say so in your digest and run again.",
    # TR4-10 Q4 (D6): the serial body at N != 1 (a single window left, `single_window_default_equals_n1`) carries the ownership line in its
    # own variant; N=1 carries none, so the compare strips it as well.
    "A test file another window of this story wrote first refuses your Write or Edit: put your test in a new file in the same directory; "
    "where a test lives stays your choice, and a test in a new file is judged the same.")
# State keys that may differ between N=1 and N=3, each with its reason. Empty: none is expected (a key the scheduler adds is a finding).
JUSTIFIED_STATE_KEYS: dict = {}


def flag_of(row) -> str:
    args = row["args"]
    return "--complete" if "--complete" in args else ("--not-complete" if "--not-complete" in args else "none")


def window_ids(world) -> dict:
    """Dispatch id -> `<role>@<window>#<n>`: the n-th dispatch of that role in that window. The ids themselves count in start order, which
    differs between the roads; the window and the nth do not."""
    seen, out = {}, {}
    for did, rec in sorted(world.dispatches.items(), key=lambda kv: int(kv[0].rsplit("-", 1)[1])):
        group = (rec["role"], ",".join(sorted(rec["scope"])))
        seen[group] = seen.get(group, 0) + 1
        out[did] = f"{group[0]}@{group[1]}#{seen[group]}"
    return out


def story_outcome(cases, parallel_windows, routes=None, ctl=None):
    root, driver, world = rig(cases, parallel_windows=parallel_windows, ctl=ctl)
    try:
        world.routes.update(routes or {})
        got = until_closed(driver, world)
        ids = window_ids(world)

        def clean(prompt):
            prompt = prompt.replace(str(root), "<root>").replace(str(world.task_root), "<task>").replace("\r\n", "\n")
            for line in CHAIN_ONLY_LINES:
                prompt = prompt.replace(line + "\n", "").replace("\n" + line, "")
            return re.sub(r"S5-[a-z-]+-\d+", lambda m: ids.get(m.group(0), m.group(0)), prompt)
        calls = [(c["kind"], c["role"], clean(c["prompt"])) for c in stub_calls(root)]
        critic_rows = [f for f in world.finishes if f["role"] == CRIT]
        record = {"errors": [type(e).__name__ for e, _o in got if e], "closed": world.closed(), "roles": roles_by_window(world),
                  "accepted": {",".join(k): sorted(v) for k, v in sorted(world.accepted.items())},
                  "closers": [(f["key"], f["role"]) for f in completes(world)], "completes": len(completes(world)), "calls": sorted(calls),
                  # sorted by window (order-free): WHICH window's critic closes S5 is the one difference the order allows and is checked apart
                  "rows": sorted((f["role"], f["key"]) for f in world.finishes),
                  "flag_counts": sorted((f["role"], flag_of(f)) for f in world.finishes),
                  "last_critic": critic_rows[-1]["key"] if critic_rows else None,
                  "state_keys": sorted(k for k in driver.state if k not in ("noted",))}
        return record, world, marks(root)
    finally:
        harness.cleanup(root)


def equivalence_outcomes_n1_vs_default():
    routes = {("TC-2",): ["test_defect", "close"]}
    one, _w, _m = story_outcome(THREE, 1, routes)
    three, _w, _m = story_outcome(THREE, None, routes)
    for field in ("errors", "closed", "roles", "accepted", "completes", "rows", "flag_counts"):
        check_eq(f"equivalence: {field} is the same at N=1 and at the default 3", three[field], one[field])
    # the one justified difference: serial closes with the LAST window in order, parallel with the last window to finish (any)
    check_eq("equivalence: at N=1 the closer is the last window in order", one["closers"], [(("TC-3",), CRIT)])
    check_eq("equivalence: at the default the closer is exactly the last critic to finish", three["closers"], [(three["last_critic"], CRIT)])
    # the prompts differ only by the two chain-only lines (stripped in `story_outcome`; dispatch ids named by role, window and nth)
    check_eq("equivalence: the calls (role, prompt) are the same at N=1 and at the default 3 but for the two chain-only lines", three["calls"], one["calls"])
    # the state: equal, or each differing key is named in JUSTIFIED_STATE_KEYS with its reason
    differing = sorted(set(three["state_keys"]) ^ set(one["state_keys"]))
    check_eq("equivalence: the driver state's keys are the same, or each difference is justified (JUSTIFIED_STATE_KEYS)",
             [k for k in differing if k not in JUSTIFIED_STATE_KEYS], [])


def single_window_default_equals_n1():
    one, _w, _m = story_outcome([["TC-1"]], 1)
    three, _w, _m = story_outcome([["TC-1"]], None)
    for field in ("errors", "closed", "roles", "accepted", "completes", "rows", "calls", "state_keys"):
        check_eq(f"single window: {field} is the same at the default 3 as at parallel_windows 1", three[field], one[field])


def shared_files_default_equals_serial():
    root, driver, world = rig(THREE)
    try:
        world.shared_files = {(c,): {"tests/x.py"} for c in ("TC-1", "TC-2", "TC-3")}
        got = until_closed(driver, world)
        rows = marks(root)
        spans = sorted((pos(rows, "start", dispatch=d)[0], pos(rows, "end", dispatch=d)[0]) for d in world.dispatches)
        check("shared files: every window closed without an exception", world.closed() and not any(e for e, _o in got), str([e for e, _o in got]))
        check("shared files: no two sessions overlapped (the default runs them as serial)", all(spans[i][1] < spans[i + 1][0] for i in range(len(spans) - 1)), str(spans))
    finally:
        harness.cleanup(root)
    serial, _w, _m = story_outcome(THREE, 1)
    check_eq("shared files: the windows' roles are those of N=1", roles_by_window(world), serial["roles"])


FIVE = [[f"TC-{i}"] for i in range(1, 6)]


def overlap_shape_all_windows_close():
    root, driver, world = rig(FIVE)
    try:
        world.shared_files = {("TC-1",): {"t/a.py"}, ("TC-2",): {"t/a.py"}, ("TC-3",): {"t/b.py"}, ("TC-4",): {"t/b.py"}, ("TC-5",): {"t/c.py"}}
        got = until_closed(driver, world)
        rows = marks(root)
        by = {}
        for d, r in world.dispatches.items():
            by.setdefault(tuple(r["scope"]), []).append((pos(rows, "start", dispatch=d)[0], pos(rows, "end", dispatch=d)[0]))
        clash = []
        for first, second in ((("TC-1",), ("TC-2",)), (("TC-3",), ("TC-4",))):
            clash += [(s, t) for s in by[first] for t in by[second] if s[0] < t[1] and t[0] < s[1]]
        check("overlap shape: every window closed, one close", world.closed() and len(completes(world)) == 1 and not any(e for e, _o in got), str([e for e, _o in got]))
        check("overlap shape: windows sharing a file never ran at once", not clash, str(clash))
    finally:
        harness.cleanup(root)


def no_overlap_shape_all_windows_close():
    root, driver, world = rig(FIVE, ctl=control(automator=barrier(3)))
    try:
        world.shared_files = {(f"TC-{i}",): {f"t/f{i}.py"} for i in range(1, 6)}
        got = until_closed(driver, world)
        rows = marks(root)
        check("no-overlap shape: every window closed, one close", world.closed() and len(completes(world)) == 1 and not any(e for e, _o in got), str([e for e, _o in got]))
        check("no-overlap shape: three sessions were at work at once, no barrier timed out", not timeouts(rows) and max(pos(rows, "start", AUTO)[:3]) < min(pos(rows, "end", AUTO)))
    finally:
        harness.cleanup(root)


def seam_halt():
    root, driver, world = rig(THREE, ctl=control(automator=dict(barrier(3), by_scope={"TC-2": {"result": "qa-automator S5 TC-2 · halt"}})))
    try:
        error, out = enter(driver)
        check("seam halt: the role's halt reaches the person as one question from the main thread", isinstance(error, SR.Person) and error.kind == "halt", repr(error))
        check("seam halt: the other windows' running sessions finished and booked", all(AUTO in world.accepted[(c,)] for c in ("TC-1", "TC-3")))
    finally:
        harness.cleanup(root)


def seam_question_threshold():
    root, driver, world = rig(THREE, ctl=control(automator=barrier(3)))
    try:
        world.person_after["TC-3"] = "How many answers may the role ask for?"
        error, out = enter(driver)
        check("seam threshold: the threshold's question is raised once after the drain", isinstance(error, SR.Person) and error.kind == "threshold", repr(error))
        check_eq("seam threshold: the chain's dispatch is adopted by the main thread", driver.last_dispatch, next(d for d, r in world.dispatches.items() if r["scope"] == ["TC-3"]))
    finally:
        harness.cleanup(root)


def seam_infra_cut_resume():
    limit = "You've hit your weekly limit · resets 2am (Europe/Madrid)"
    root, driver, world = rig(THREE, ctl=control(automator=dict(barrier(3), by_scope={"TC-2": {"result": limit, "is_error": True}})))
    try:
        error, out = enter(driver)
        check("seam limit: a limit in one of three windows is not a stop: the stage returns", error is None, repr(error))
        check_in("seam limit: the run goes on one window at a time, said once", "one window at a time", out)
        check("seam limit: the others booked their authors", all(AUTO in world.accepted[(c,)] for c in ("TC-1", "TC-3")))
        check("seam limit: the cap-one switch is set after the cut", driver.__dict__.get("_s5_cap_one") is True, str(driver.__dict__.get("_s5_cap_one")))
        set_control(root, control())
        later = until_closed(driver, world)
        rows = marks(root)
        # the cut came with the last author's session (the three authors met at one barrier); the switch to cap 1 falls inside the FIRST
        # entry, so the sessions that count are every one that started after the last author ended, in this entry and the later ones
        cut = max(pos(rows, "end", AUTO))
        after = {r["dispatch"] for i, r in enumerate(rows) if i > cut and r["event"] == "start"}
        spans = sorted((pos(rows, "start", dispatch=d)[0], pos(rows, "end", dispatch=d)[0]) for d in after)
        check("seam limit: the cut window resumes and the story closes", world.closed() and not any(e for e, _o in later), str([e for e, _o in later]))
        check("seam limit: after the cut the sessions ran one at a time (cap 1): at least two, none overlapping another",
              len(spans) >= 2 and all(spans[i][1] < spans[i + 1][0] for i in range(len(spans) - 1)), str(spans))
    finally:
        harness.cleanup(root)


def seam_mechanical_round():
    root, driver, world = rig([["TC-1"], ["TC-2"]])
    try:
        world.routes[("TC-1",)] = ["mechanical"]
        error, out = enter(driver)
        mech = [f for f in world.finishes if f["role"] == AUTO and f["key"] == ("TC-1",)]
        check("seam mechanical: no exception, every window closed", error is None and world.closed(), repr(error))
        check("seam mechanical: the author ran a second time and no second critic was dispatched for W1",
              len(mech) == 2 and len([f for f in world.finishes if f["role"] == CRIT and f["key"] == ("TC-1",)]) == 1, str(mech))
        check("seam mechanical: one close in all", len(completes(world)) == 1)
    finally:
        harness.cleanup(root)


SCENARIOS = [n3_three_automators_overlap, no_thread_started_at_n1, crash_in_one_window_others_finish,
             person_in_one_window_drains_then_asks_once, queued_question_asked_next, round_in_w1_blocks_close_by_w2,
             mechanical_last_with_other_chain_open, exactly_one_close_order_free, stage_closes_only_after_last_window,
             config_absent_reads_three, config_invalid_reads_three_with_note, refusal_retry_on_main_reads_chain,
             stand_person_in_chain_re_arises, driver_interrupt_kills_children, critic_probe_waits_for_file_holder,
             stand_busy_is_not_a_window_failure, ticket_rework_owed_after_drain,
             equivalence_outcomes_n1_vs_default, single_window_default_equals_n1, shared_files_default_equals_serial,
             overlap_shape_all_windows_close, no_overlap_shape_all_windows_close, seam_halt, seam_question_threshold,
             seam_infra_cut_resume, seam_mechanical_round]


def main() -> None:
    wanted = sys.argv[1:]
    chosen = [s for s in SCENARIOS if not wanted or any(s.__name__.startswith(prefix) for prefix in wanted)]
    if not chosen:
        sys.exit("test_story_run_s5_parallel: no scenario starts with " + str(wanted) + "; they are: " + ", ".join(s.__name__ for s in SCENARIOS))
    from story_run_common import run_scenarios
    shown, held = sys.stdout, io.StringIO()
    sys.stdout = held
    try:
        run_scenarios([], chosen)
    finally:
        sys.stdout = shown
    failed = [name for ok, name in harness.RESULTS if not ok]
    if failed:      # CI shows the first lines that start with FAIL only: the whole list of this file goes first, in ONE line
        print("FAIL (the whole list of this file): " + " | ".join(failed))
    print(held.getvalue(), end="")
    harness.finish("test_story_run_s5_parallel")


if __name__ == "__main__":
    main()
