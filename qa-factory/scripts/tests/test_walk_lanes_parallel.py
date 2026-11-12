#!/usr/bin/env python3
"""t-2147 TR3-9 C1: the manual half of S6 on the window scheduler (`run_chains`): walker lanes side by side (AR-14, AR-15, AR-17, AR-19, AR-22,
AR-25, AR-28).

Every case builds a bare `Driver` (`Driver.__new__`, no process) and drives the REAL `run_manual_block` / `run_manual_lane` / `run_s6_lanes` and the
real scheduler with real threads. Stand-ins (one place, `make`): the controller (`FakeController` over a `World`), `controller_state`,
`manual_prepare` / `manual_policy` / `manual_order`, `walk_before`, `record_running`, `role_lines`, and `run_role` - a fake that takes the launch
gate and gives `_book` up around its session exactly as `launch` does, then calls `complete(digest)` under `_book` as `finish` does. Overlap is
proved with barriers and events, never with sleeps (FR-31). The account key of a case comes from `KEYS` (a stand-in of `lane_keys`).

Keys: walkers_default_three_lanes_overlap, walkers_1_takes_old_road_no_thread, no_thread_started_at_walkers_1, one_lane_old_body,
same_account_lanes_in_turn, overlapping_part_sets_in_turn, lane_crash_others_finish_one_seam, drained_lane_registers_no_dispatch,
close_exactly_once_order_free, unreadable_lane_state_is_open, ids_never_shared, settling_lanes_first_then_parallel,
unreadable_account_lane_runs_first, serial_reason_each_row, lane_interrupt_kills_children, held_case_keeps_serial,
same_account_second_lane_never_registers, walk_open_carries_max_shared, close_waits_for_a_blocked_lane, consumer_branch_never_author_close,
lane_question_queued_next, crashed_lane_closes_its_walk, request_carries_walk_lane_and_actor, story_run_makes_no_new_thread_site; fix round t-2239: consumer_refused_case_still_awaits,
resume_road_consumer_ignores_refused, unreadable_key_lane_request_has_no_walk_actor, walk_reopen_passes_max_shared,
unreadable_settle_read_stays_serial.

Run: python -B scripts/tests/test_walk_lanes_parallel.py
"""
import contextlib
import io
import itertools
import json
import os
import re
import sys
import tempfile
import threading
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import SCRIPTS, check, check_eq, check_in, finish  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import story_run as SR  # noqa: E402
import driver_chains as DC  # noqa: E402
import manual_evidence as ME  # noqa: E402
import walk_pool as WP  # noqa: E402
import walk_session as WS  # noqa: E402

WAIT = 10
KEYS: dict = {}         # case -> account key (a case that is absent has a request that cannot be read)
SHOWN = {"lane_keys": SR.lane_keys}


def fake_lane_keys(_root, cases):
    return {str(c): KEYS[str(c)] for c in cases if str(c) in KEYS}


SR.lane_keys = fake_lane_keys


class World:
    """The controller's S6 record as the driver reads it."""

    def __init__(self):
        self.lock = threading.RLock()
        self.dispatches, self.events, self.complete_of, self.broken = {}, [], {}, False
        self.finished = {}

    def done_cases(self) -> set:
        with self.lock:
            return {c for d in self.dispatches.values() if d.get("status") == "accepted" for c in d.get("manual_case_ids") or []}

    def state_of(self) -> dict:
        with self.lock:
            if self.broken:
                raise OSError("controller.json cannot be read")
            return {"dispatches": {k: dict(v) for k, v in self.dispatches.items()}}

    def controller_class(self, driver):
        world = self

        class FakeController:
            def __init__(self, task_root, wait_seconds=0.0):
                pass

            def state(self):
                with world.lock:
                    return {"dispatches": {k: dict(v) for k, v in world.dispatches.items()}}

            def prepare(self, options):
                return {"dispatch_request": {"id": options["id"], "stage": options["stage"], "role": options["role"], "scope": list(options["scope"])}}

            def apply(self, operation, request):
                assert operation == "dispatch"
                with world.lock:
                    prior = driver._chains.get(1)
                    world.events.append(("register", request["id"], bool(prior and prior.done)))
                    world.dispatches[request["id"]] = dict(request, status="running")
        return FakeController

    def finish(self, did, complete, status="accepted"):
        with self.lock:
            self.complete_of[did] = complete
            self.dispatches[did]["status"] = status
            self.events.append(("finish", did, complete))
        self.finished.setdefault(did, threading.Event()).set()


def make(cases, keys=None, *, walkers=None, config=None, waiting=(), session=None, walking=False, world=None, running=()):
    """A bare Driver over the lanes `cases` (one case per lane: `MANUAL_BLOCK_MAX` 1), its world, and its fake `run_role`."""
    KEYS.clear()
    KEYS.update(keys if keys is not None else {c: f"stand_account:{c}" for c in cases})
    d = SR.Driver.__new__(SR.Driver)
    world = world or World()
    d.task, d.host, d.dry, d.state = "T-1", "claude", True, {}
    d.config = config if config is not None else ({} if walkers is None else {"manual": {"walkers": walkers}})
    d.task_root = Path(tempfile.mkdtemp(prefix="c1-lanes-"))
    d.state_dir = d.task_root / "state"
    d.MANUAL_BLOCK_MAX = 1
    d.save_state = lambda: None
    d.controller_state = world.state_of
    d.stage_scope = lambda stage, kind="": {"scope": list(cases)}
    d.manual_done = world.done_cases
    d.manual_order = lambda given: list(given)
    d.manual_prepare = lambda case: ([f"OB-{case}"], "", "")
    d.manual_policy = lambda case: "api"
    d.manual_gate_note = lambda: None
    d.manual_request_paths = lambda block: [f"work/evidence/manual/{c}/request.json" for c in block]
    d.deferred_waiting = lambda given: [(c, n) for c, n in waiting if c in given]
    d.deferred_items = lambda: []
    d.walk_refuse_gaps = lambda plan: None
    d.walk_before = lambda lane, did, assigned=None: {"walking": walking, "report_last": False, "assigned": assigned}
    d.walk_after = lambda lane, did, result: None
    d.record_running = lambda *a, **k: None
    d.role_lines = lambda stage, role: []
    for i, (case, status) in enumerate(running, 1):
        world.dispatches[f"S6-qa-runner-{i}"] = {"id": f"S6-qa-runner-{i}", "stage": "S6", "role": "qa-runner", "status": status,
                                                  "scope": [case], "manual_case_ids": [case], "execution_kind": "manual"}

    def run_role(stage, role, *, scope=None, extra=(), complete=None, rework=None, **kw):
        did = rework["id"]
        d.extras[did] = list(extra)         # TR3-10d: the prompt lines the lane's role would get
        with d.session_running(did):
            with d.unbooked(did):
                status = (d.session_fn(did, list(scope or [])) if d.session_fn else None) or "accepted"
        if status != "accepted":                 # the lane ended blocked or paused: no finish reaches the controller
            with world.lock:
                world.dispatches[did]["status"] = status
            return "", {}
        digest = "done"
        value = complete(digest) if callable(complete) else complete
        world.finish(did, value, status)
        return digest, {}
    d.run_role = run_role
    d.world, d.session_fn, d.consumer, d.extras = world, session, None, {}
    return d


def enter(d, cases, patches=()):
    """One `stage` entry of the manual half: (error, console)."""
    out, error = io.StringIO(), None
    with contextlib.ExitStack() as stack:
        stack.enter_context(mock.patch("controller.Controller", d.world.controller_class(d)))
        # the stand-in project has no consumer of S6 unless a case says so (the real table names the failure analyst)
        stack.enter_context(mock.patch("acceptance.consumer_of", lambda stage: d.consumer if stage == "S6" else None))
        for p in patches:
            stack.enter_context(p)
        stack.enter_context(contextlib.redirect_stdout(out))
        try:
            d.run_manual_block(list(cases))
        except BaseException as exc:      # noqa: BLE001 - the case reads what the road raised
            error = exc
    return error, out.getvalue()


def registered(d) -> list:
    return [e[1] for e in d.world.events if e[0] == "register"]


def request_of(d, did) -> dict:
    return d.world.dispatches[did]


class Overlap:
    """Counts the sessions that are at work at once; `meet(n)` is a barrier of n sessions."""

    def __init__(self):
        self.lock, self.now, self.most = threading.Lock(), 0, 0

    @contextlib.contextmanager
    def at_work(self):
        with self.lock:
            self.now += 1
            self.most = max(self.most, self.now)
        try:
            yield
        finally:
            with self.lock:
                self.now -= 1


def as_chain_thread(d, n, body, cases=()):
    record = DC.ChainRecord(n, cases=tuple(cases))
    box = {}

    def target():
        d._book.acquire()
        try:
            with d.as_chain(record):
                body(record)
        except BaseException as exc:      # noqa: BLE001
            box["error"] = exc
        finally:
            d._book.release()
    t = threading.Thread(target=target)
    t.start()
    return record, box, t


# --- the keys ------------------------------------------------------------------------------------------------------------------------------

def walkers_default_three_lanes_overlap():
    cases = ["TC-1", "TC-2", "TC-3"]
    meet, seen = threading.Barrier(3, timeout=WAIT), Overlap()

    def session(did, scope):
        with seen.at_work():
            meet.wait()
    d = make(cases, session=session)          # no `manual` block in the config: the default is 3
    err, said = enter(d, cases)
    check("no key: three lanes' sessions were at work at once (the barrier needs all three)", err is None and seen.most == 3, repr(err))
    check_eq("each lane registered its own dispatch", sorted(registered(d)), ["S6-qa-runner-1", "S6-qa-runner-2", "S6-qa-runner-3"])
    check_eq("all three were accepted", d.world.done_cases(), set(cases))
    check_in("a lane's console lines carry its tag", "[L1] S6: manual block of 1 case(s): TC-1", said)
    last = [d.world.complete_of[i] for i in ("S6-qa-runner-1", "S6-qa-runner-2", "S6-qa-runner-3")]
    check_eq("exactly one finish closed the stage", sum(1 for v in last if v is True), 1)


def walkers_1_takes_old_road_no_thread():
    cases = ["TC-1", "TC-2", "TC-3"]
    d = make(cases, walkers=1)
    boom = mock.Mock(side_effect=AssertionError("a walkers-1 entry must not touch this"))
    d.run_chains, d.s6_serial_reason, d.s6_settling_lanes, d.run_s6_lanes = boom, boom, boom, boom
    err, said = enter(d, cases)
    check("walkers 1: no scheduler, no serial reason, no settling read", err is None and not boom.called, repr(err))
    check_eq("one lane per entry: only the first registered", registered(d), ["S6-qa-runner-1"])
    check("the request carries no lane flag and no actor", "walk_lane" not in request_of(d, "S6-qa-runner-1") and "walk_actor" not in request_of(d, "S6-qa-runner-1"))
    check_eq("not complete: more lanes follow", d.world.complete_of["S6-qa-runner-1"], False)
    check_eq("no new state key", d.state, {})
    check("no `[L1]` tag on the old road", "[L" not in said, said)


def no_thread_started_at_walkers_1():
    cases = ["TC-1", "TC-2"]
    for walkers in (1,):
        d = make(cases, walkers=walkers)
        with mock.patch.object(threading, "Thread", side_effect=AssertionError("a thread was started")):
            err, _said = enter(d, cases)
        check_eq("walkers 1 starts no thread", err, None)
    d = make(cases, walkers=1)
    d.config = {"manual": {"walkers": "3"}}      # a bad value reads the default: the note is said, once
    err, said = enter(d, cases)
    check_in("a bad value reads three with its note", "note: manual.walkers is", said)
    d = make(cases, walkers=0)
    err, said = enter(d, cases)
    check_in("zero reads three with its note", "note: manual.walkers is 0", said)


def one_lane_old_body():
    d = make(["TC-1"])
    d.run_chains = mock.Mock(side_effect=AssertionError("one lane is no chain"))
    err, said = enter(d, ["TC-1"])
    check_eq("one lane: no scheduler", err, None)
    check("the request carries no lane flag", "walk_lane" not in request_of(d, "S6-qa-runner-1"))
    check_eq("the only lane closes the stage, as the old road does", d.world.complete_of["S6-qa-runner-1"], True)
    cases = ["TC-1", "TC-2"]
    d = make(cases)
    d.run_chains = mock.Mock(side_effect=AssertionError("a single settling lane is no chain"))
    d.world.dispatches["S6-qa-runner-9"] = {"id": "S6-qa-runner-9", "stage": "S6", "role": "qa-runner", "status": "running", "scope": ["TC-1"]}
    err, _said = enter(d, cases)
    check("a single settling lane takes the old body at one at a time", err is None and registered(d) == ["S6-qa-runner-2"], repr(err))


GRACE = 0.5     # how long the holder waits for the other lane to wrongly enter; a wait for an event that must NOT come, never a proof of one


def hold_first_lane(keys, cases):
    """Two lanes whose holds meet: the first lane to enter its session HOLDS on an event until a watcher thread releases it, and the
    watcher first gives the other lane `GRACE` seconds to (wrongly) enter. Returns `(driver, error, order, entered_while_held, stuck)`:
    `order` the cases in the order their sessions began, `entered_while_held` True when the second session began before the release,
    `stuck` True when the watcher did not finish within `WAIT`. The release sits in a `finally`, so a lane that raises never hangs this."""
    lock, order = threading.Lock(), []
    holding, release, second = threading.Event(), threading.Event(), threading.Event()
    box = {"early": False}

    def session(did, scope):
        with lock:
            order.append(scope[0])
            first = len(order) == 1
            if first:
                holding.set()
            else:
                box["early"] = not release.is_set()
                second.set()
        if first:
            release.wait(WAIT)

    def watcher():
        try:
            if holding.wait(WAIT):
                second.wait(GRACE)
        finally:
            release.set()
    d = make(cases, keys, session=session)
    thread = threading.Thread(target=watcher)
    thread.start()
    try:
        err, _said = enter(d, cases)
    finally:
        release.set()
        thread.join(WAIT)
    return d, err, order, box["early"], thread.is_alive()


def same_account_lanes_in_turn():
    cases = ["TC-1", "TC-2"]
    d, err, order, early, stuck = hold_first_lane({"TC-1": "stand_account:admin", "TC-2": "stand_account:admin"}, cases)
    check("the holding watcher finished (no hang)", not stuck and err is None, repr(err))
    check("two lanes on one account: the second does not enter while the first holds", early is False, repr(order))
    check_eq("both lanes ran, the second after the first left", (sorted(order), d.world.done_cases()), (sorted(cases), set(cases)))
    # Guests: since TR3-10 guest lanes run side by side when their data is disjoint (key `guest_lanes_side_by_side_when_data_disjoint`);
    # the old "guest beside guest in turn" half asserted nothing about order and is gone.


def overlapping_part_sets_in_turn():
    d = make(["TC-1", "TC-2"], {"TC-1": "stand_account:admin+stand_account:user", "TC-2": "stand_account:user"})
    check_eq("one hold per part of a `+`-joined key, never the whole string", d.s6_lane_holds(["TC-1"]),
             {"case:TC-1", "account:stand_account:admin", "account:stand_account:user"})
    check_eq("a lane of one part holds that part", d.s6_lane_holds(["TC-2"]), {"case:TC-2", "account:stand_account:user"})
    check_eq("a guest holds `account:guest`", make(["G"], {"G": ""}).s6_lane_holds(["G"]), {"case:G", "account:guest"})
    check_eq("a key that cannot be read holds `account:?<case>`", make(["U"], {}).s6_lane_holds(["U"]), {"case:U", "account:?U"})
    d, err, order, early, stuck = hold_first_lane({"TC-1": "stand_account:admin+stand_account:user", "TC-2": "stand_account:user"}, ["TC-1", "TC-2"])
    check("the holding watcher finished (no hang)", not stuck and err is None, repr(err))
    check("lanes whose part sets meet: the second does not enter while the first holds", early is False, repr(order))
    check_eq("both lanes ran", (sorted(order), d.world.done_cases()), (["TC-1", "TC-2"], {"TC-1", "TC-2"}))


def lane_crash_others_finish_one_seam():
    cases = ["TC-1", "TC-2", "TC-3"]
    meet = threading.Barrier(2, timeout=WAIT)
    boom = SR.Refusal("lane one broke")

    def session(did, scope):
        meet.wait()                                # both sessions are at work before the first one fails
        if scope == ["TC-1"]:
            raise boom
        d._drain.wait(WAIT)                        # the second one ends only after the drain began
    d = make(cases, walkers=2, session=session)
    err, said = enter(d, cases)
    check("the crashed lane's Refusal is raised once, on this thread", err is boom, repr(err))
    check_eq("the other running lane finished and booked", d.world.done_cases(), {"TC-2"})
    check_eq("the third lane was never registered after the drain", sorted(registered(d)), ["S6-qa-runner-1", "S6-qa-runner-2"])
    check_eq("the crashed lane's dispatch stays running for the re-entry", d.world.dispatches["S6-qa-runner-1"]["status"], "running")


def drained_lane_registers_no_dispatch():
    d = make(["TC-1", "TC-2"])
    d._s6_view = {"plan": {"blocks": [["TC-1"], ["TC-2"]], "refused": []}, "waiting": [], "cases": ["TC-1", "TC-2"]}
    d._drain.set()
    out = io.StringIO()
    with mock.patch("controller.Controller", d.world.controller_class(d)), contextlib.redirect_stdout(out):
        _r, box, t = as_chain_thread(d, 1, lambda record: d.run_manual_lane(record, ["TC-1"]), cases=("TC-1",))
        t.join(WAIT)
    check("a drained lane stops by `Drained`", isinstance(box.get("error"), DC.Drained), repr(box))
    check_eq("it registered nothing", d.world.dispatches, {})


def close_exactly_once_order_free():
    cases = ["TC-1", "TC-2", "TC-3"]
    for order in itertools.permutations(range(3)):
        gates = [threading.Event() for _ in cases]
        inside = [threading.Event() for _ in cases]

        def session(did, scope):
            i = cases.index(scope[0])
            inside[i].set()
            gates[i].wait(WAIT)
        d = make(cases, session=session)

        def conductor():
            for i in order:
                inside[i].wait(WAIT)
                gates[i].set()
                d.world.finished.setdefault(f"S6-qa-runner-{registered_index(d, cases[i])}", threading.Event()).wait(WAIT)

        def registered_index(drv, case):
            return next(int(k.rsplit("-", 1)[1]) for k, v in drv.world.dispatches.items() if v["scope"] == [case])
        t = threading.Thread(target=conductor)
        t.start()
        err, _said = enter(d, cases)
        t.join(WAIT)
        by_case = {v["scope"][0]: d.world.complete_of[k] for k, v in d.world.dispatches.items()}
        last = cases[order[-1]]
        check(f"finish order {[cases[i] for i in order]}: only the last finisher closes S6, once",
              err is None and by_case[last] is True and sum(1 for v in by_case.values() if v is True) == 1, f"{by_case} {err!r}")


def unreadable_lane_state_is_open():
    d = make(["TC-1", "TC-2"])
    d._s6_view = {"plan": {"blocks": [], "refused": []}, "waiting": [], "cases": ["TC-1", "TC-2"]}
    d.controller_state = lambda: {}
    err = None
    try:
        d.s6_open_lanes(())
    except Exception as exc:      # noqa: BLE001
        err = exc
    check("a controller record with no dispatches RAISES (an unknown is open)", isinstance(err, ValueError), repr(err))
    d.controller_state = lambda: (_ for _ in ()).throw(OSError("gone"))
    try:
        d.s6_open_lanes(())
        err = None
    except Exception as exc:      # noqa: BLE001
        err = exc
    check("an unreadable controller RAISES", isinstance(err, OSError), repr(err))
    d._s6_view = None
    try:
        d.s6_open_lanes(())
        err = None
    except Exception as exc:      # noqa: BLE001
        err = exc
    check("no plan in view RAISES", isinstance(err, ValueError), repr(err))
    meet = threading.Barrier(2, timeout=WAIT)

    def session(did, scope):
        meet.wait()
        if scope == ["TC-2"]:
            d.world.broken = True                  # the state cannot be read from here on: the finish asks it
    d = make(["TC-1", "TC-2"], session=session)
    d.controller_state = lambda: d.world.state_of()
    err, _said = enter(d, ["TC-1", "TC-2"])
    check("with the state unreadable at the finish no lane closes S6", err is None and not any(v is True for v in d.world.complete_of.values()),
          f"{d.world.complete_of} {err!r}")


def ids_never_shared():
    cases = [f"TC-{i}" for i in range(1, 7)]
    meet = threading.Barrier(3, timeout=WAIT)

    def session(did, scope):
        with contextlib.suppress(threading.BrokenBarrierError):
            meet.wait(1)
    d = make(cases, session=session)
    err, _said = enter(d, cases)
    ids = registered(d)
    check("six lanes took six distinct ids", err is None and len(ids) == len(set(ids)) == 6, f"{ids} {err!r}")
    check_eq("the ids are the count 1..6", sorted(ids), [f"S6-qa-runner-{i}" for i in range(1, 7)])


def settling_lanes_first_then_parallel():
    cases = ["TC-1", "TC-2", "TC-3"]
    d = make(cases, running=[("TC-1", "running")])
    d.run_chains = mock.Mock(side_effect=AssertionError("the settling round of one lane is no chain"))
    err, said = enter(d, cases)
    check_eq("round one: only the lane that meets the running dispatch ran, at one at a time", (err, registered(d)[-1]), (None, "S6-qa-runner-2"))
    check_eq("it is the lane of TC-1", d.world.dispatches["S6-qa-runner-2"]["scope"], ["TC-1"])
    check_in("the reason is said once", "S6 lanes run one at a time: dispatches of S6 are running or stopped at entry", said)
    del d.run_chains
    d.world.dispatches["S6-qa-runner-1"]["status"] = "accepted"          # it settled
    meet, seen = threading.Barrier(2, timeout=WAIT), Overlap()

    def session(did, scope):
        with seen.at_work():
            meet.wait()
    d.session_fn = session
    err, said = enter(d, cases)
    check("the next entry runs the rest side by side", err is None and seen.most == 2, repr(err))
    check_eq("and both carry the lane flag", [request_of(d, i).get("walk_lane") for i in ("S6-qa-runner-3", "S6-qa-runner-4")], [True, True])


def unreadable_account_lane_runs_first():
    cases = ["TC-1", "TC-2", "TC-3"]
    d = make(cases, {"TC-2": "stand_account:a", "TC-3": "stand_account:b"})        # TC-1's request cannot be read
    d.run_chains = mock.Mock(side_effect=AssertionError("round one is one lane"))
    err, _said = enter(d, cases)
    check_eq("round one is the unreadable lane alone", (err, d.world.dispatches["S6-qa-runner-1"]["scope"]), (None, ["TC-1"]))
    check("without the lane flag (the old body)", "walk_lane" not in request_of(d, "S6-qa-runner-1"))


def serial_reason_each_row():
    base = ["TC-1", "TC-2"]

    def reason(mutate=None, view=True, **kw):
        d = make(base, **kw)
        if view:
            d._s6_view = {"plan": {"blocks": [["TC-1"], ["TC-2"]], "refused": []}, "waiting": kw.pop("w", []), "cases": list(base)}
        if mutate:
            mutate(d)
        return d.s6_serial_reason()
    check_eq("nothing in the way: no reason", reason(), "")
    check_in("host not Claude", "host is not Claude", reason(lambda d: setattr(d, "host", "codex")))
    check_in("execution.parallel.mode serial", "execution.parallel.mode: serial",
             reason(config={"execution": {"parallel": {"mode": "serial"}}}))
    check_in("a model-service limit earlier", "limited one lane", reason(lambda d: setattr(d, "_s6_cap_one", True)))
    check_in("unreadable dispatches", "cannot be read", reason(lambda d: setattr(d, "controller_state", lambda: (_ for _ in ()).throw(OSError("x")))))
    check_eq("a running dispatch at entry", reason(running=[("TC-1", "running")]), SR.Driver.S6_SETTLE_RUNNING)
    check_eq("a blocked one too", reason(running=[("TC-1", "blocked")]), SR.Driver.S6_SETTLE_RUNNING)
    check_eq("and a paused one", reason(running=[("TC-1", "paused")]), SR.Driver.S6_SETTLE_RUNNING)
    check_in("a deferred question holding a case", "holds a case of the plan",
             reason(lambda d: d._s6_view.update(waiting=[("TC-3", 4)])))
    check_in("the plan of the entry not known", "cannot be read", reason(view=False))
    check_eq("the project's own `walkers: 1` is not a reason (it is the old road)", reason(walkers=1), "")


def lane_interrupt_kills_children():
    cases = ["TC-1", "TC-2"]
    d = make(cases)
    d.WAIT_POLL_S = 0.05
    armed = threading.Event()
    real_join = threading.Thread.join

    def ctrl_c_join(thread, timeout=None):
        if armed.is_set() and threading.current_thread() is threading.main_thread():
            armed.clear()
            raise KeyboardInterrupt()
        return real_join(thread, timeout)
    d.project, d.claude_env = d.task_root, dict(os.environ)
    d.mark_in_flight = d.clear_in_flight = lambda *a, **k: None
    mark = d.task_root / "c8.txt"
    cmd = [sys.executable, "-c", f"import time,pathlib; pathlib.Path(r'{mark}').open('a').write('x'); time.sleep(20); pathlib.Path(r'{mark}').open('a').write('y')"]

    def run_role(stage, role, *, scope=None, rework=None, **kw):
        d.launch(cmd, "", dispatch=rework["id"])
        return "", {}
    d.run_role = run_role

    def launchable(record):
        first = d._chains.get(1)
        if record.n == 2 and first is not None and first.proc is not None and mark.exists():
            armed.set()
            raise RuntimeError("the scheduler's own read failed")
        return record.n == 1
    d.chain_launchable = launchable
    import subprocess
    real_popen, procs = subprocess.Popen, []

    def spy(*a, **k):
        procs.append(real_popen(*a, **k))
        return procs[-1]
    threading.Thread.join = ctrl_c_join
    try:
        err, said = enter(d, cases, patches=[mock.patch.object(subprocess, "Popen", spy)])
    finally:
        threading.Thread.join = real_join
    code = procs[0].wait(timeout=WAIT) if procs else None
    check("a Ctrl-C during the lanes' wait leaves as a KeyboardInterrupt", isinstance(err, KeyboardInterrupt), repr(err))
    check("the flag is set, the lane's child is dead and wrote nothing after it", d._interrupted.is_set() and code not in (None, 0) and "y" not in mark.read_text(encoding="utf-8"), f"{code}")
    check_eq("the second lane never registered", registered(d), ["S6-qa-runner-1"])


def held_case_keeps_serial():
    cases = ["TC-1", "TC-2", "TC-3"]
    d = make(cases, waiting=[("TC-3", 7)])
    d.run_chains = mock.Mock(side_effect=AssertionError("a held case keeps the entry serial"))
    err, said = enter(d, cases)
    check_eq("one lane, the old road", (err, registered(d)), (None, ["S6-qa-runner-1"]))
    check_in("the reason is said", "S6 lanes run one at a time: a question about a check", said)
    check_eq("not complete: a held case is outside the cover", d.world.complete_of["S6-qa-runner-1"], False)


def same_account_second_lane_never_registers():
    cases = ["TC-1", "TC-2"]
    d = make(cases, {"TC-1": "stand_account:admin", "TC-2": "stand_account:admin"})
    err, _said = enter(d, cases)
    events = [e for e in d.world.events if e[0] == "register"]
    check("the second same-key lane's apply came only after the first chain was done", err is None and len(events) == 2 and events[1][2] is True, f"{d.world.events} {err!r}")


def walk_open_carries_max_shared():
    d = make(["TC-1"])
    (d.task_root / "work").mkdir(parents=True)
    (d.task_root / "work" / "run-report.json").write_text("{}", encoding="utf-8")
    calls = []
    d.py = lambda script, *args, **kw: (calls.append([script, *args]), (0, "x"))[1]
    d.state["walk_old_road"] = {}
    del d.walk_before                                  # the real one
    KEYS.update({"TC-1": ""})
    d.config = {"manual": {"walkers": 2}}
    with contextlib.redirect_stdout(io.StringIO()):
        out = d.walk_before(["TC-1"], "S6-qa-runner-1")
    opens = [c for c in calls if c[0] == "walk_session.py"]
    check("off a chain (the old road) the open carries no flag", out["walking"] and "--max-shared" not in opens[0], str(opens))
    calls.clear()
    seen = {}

    def body(record):
        with contextlib.redirect_stdout(io.StringIO()):
            seen["out"] = d.walk_before(["TC-1"], "S6-qa-runner-2")
    _r, box, t = as_chain_thread(d, 1, body, cases=("TC-1",))
    t.join(WAIT)
    opens = [c for c in calls if c[0] == "walk_session.py"]
    check("on a chain the open carries `--max-shared <walkers>`", "error" not in box and opens and opens[0][-2:] == ["--max-shared", "2"], f"{opens} {box}")


def close_waits_for_a_blocked_lane():
    meet = threading.Barrier(2, timeout=WAIT)

    def session(did, scope):
        meet.wait()
        return "blocked" if scope == ["TC-1"] else None
    d = make(["TC-1", "TC-2"], session=session)
    err, _said = enter(d, ["TC-1", "TC-2"])
    check("a lane that ended blocked is open: the other lane's finish does not close S6", err is None and not any(v is True for v in d.world.complete_of.values()),
          f"{d.world.complete_of} {err!r}")
    check_eq("its case is not accepted", d.world.done_cases(), {"TC-2"})


def consumer_branch_never_author_close():
    meet = threading.Barrier(2, timeout=WAIT)
    gates = [threading.Event(), threading.Event()]

    def session(did, scope):
        meet.wait()
        i = 0 if scope == ["TC-1"] else 1
        if i == 1:
            gates[0].wait(WAIT)                          # TC-2 finishes after TC-1
    d = make(["TC-1", "TC-2"], session=session)
    real_finish = d.world.finish

    def finish(did, complete, status="accepted"):
        real_finish(did, complete, status)
        gates[0].set()
    d.world.finish = finish
    d.consumer = "qa-failure-analyst"
    err, _said = enter(d, ["TC-1", "TC-2"])
    values = d.world.complete_of
    check("with a consumer no finish is ever `True`", err is None and not any(v is True for v in values.values()), f"{values} {err!r}")
    check("the lane that would close is the open-work word, never an author close", any(isinstance(v, SR.OpenWork) for v in values.values()), f"{values}")


def lane_question_queued_next():
    meet = threading.Barrier(2, timeout=WAIT)

    def session(did, scope):
        meet.wait()
        raise SR.Person("halt", f"question of {scope[0]}", "S6", did)
    d = make(["TC-1", "TC-2"], session=session)
    err, said = enter(d, ["TC-1", "TC-2"])
    check("one Person is raised, on this thread (the lowest lane)", isinstance(err, SR.Person) and "TC-1" in str(err.text if hasattr(err, "text") else err), repr(err))
    check_in("the other is named, to be asked on the next entry", "S6: lane 2 also ended with Person", said)


def crashed_lane_closes_its_walk():
    calls = []

    def after(lane, did, result):
        calls.append((list(lane), did, result))
    d = make(["TC-1", "TC-2"], walking=True)
    d.walk_after = after

    def broken(*a, **k):
        raise SR.Refusal("the running record could not be written")
    d.record_running = broken
    err, _said = enter(d, ["TC-1", "TC-2"])
    check("the crash is raised once", isinstance(err, SR.Refusal), repr(err))
    # lanes run in threads: which lane crashes first, which takes which dispatch id, and whether the second opens a walk at all are not guaranteed
    runner_ids = {"S6-qa-runner-1", "S6-qa-runner-2"}
    check("the lane that opened a walk and ended before `run_role` closes it, with no result",
          bool(calls) and all(lane in (["TC-1"], ["TC-2"]) and did in runner_ids and result == {} for lane, did, result in calls), str(calls))
    d = make(["TC-1", "TC-2"], walking=False)
    d.walk_after = after
    d.record_running = broken
    calls.clear()
    enter(d, ["TC-1", "TC-2"])
    check_eq("a lane that opened no walk closes none", calls, [])


def request_carries_walk_lane_and_actor():
    cases = ["TC-1", "TC-2", "TC-3"]
    meet = threading.Barrier(3, timeout=WAIT)

    def session(did, scope):
        meet.wait()
    d = make(cases, {"TC-1": "stand_account:admin+stand_account:user", "TC-2": "", "TC-3": "stand_account:user2"}, session=session)
    err, _said = enter(d, cases)
    got = {request_of(d, i)["scope"][0]: (request_of(d, i).get("walk_lane"), request_of(d, i).get("walk_actor")) for i in registered(d)}
    check_eq("each lane's request carries the flag and its account key as a string (`\"\"` is a guest)", got,
             {"TC-1": (True, "stand_account:admin+stand_account:user"), "TC-2": (True, "guest#2"), "TC-3": (True, "stand_account:user2")})   # TR3-10d item 6: a guest lane's actor is its own `guest#<n>`
    d = make(["TC-1", "TC-2"], {"TC-2": "stand_account:x"})
    enter(d, ["TC-1", "TC-2"])
    check_eq("a key that cannot be read is `?<case>`, a string that equals no other", request_of(d, "S6-qa-runner-1").get("walk_lane"), None)
    d = make(["TC-1", "TC-2"], {"TC-1": "stand_account:a", "TC-2": "stand_account:b"})
    d.run_chains = lambda items, launchable, chain_fn, cap, **k: [chain_fn(DC.ChainRecord(n, cases=tuple(c)), p) for n, c, p in items]
    enter(d, ["TC-1", "TC-2"])
    check_eq("(unreadable lane first: old body, no flag; the rest flagged)", [request_of(d, i).get("walk_actor") for i in registered(d)],
             ["stand_account:a", "stand_account:b"])


def story_run_makes_no_new_thread_site():
    sites = [(path.name, text.count("\n", 0, at.start()) + 1) for path, text in harness.driver_sources()
             for at in re.finditer(r"threading\.Thread\(", text)]
    check("AR-15: the driver set has TWO `threading.Thread(` sites (the chain scheduler and the timing watcher) and none for lanes: "
          + ", ".join(f"{name}:{line}" for name, line in sites), len(sites) == 2, f"{sites}")


def consumer_refused_case_still_awaits():
    """t-2239 B1 (AR-25, X7-6): with a consumer a refused case does not keep the last lane from awaiting; `manual_close` closes it later."""
    def prep(c):
        return ([], "the request could not be prepared", "door") if c == "TC-3" else ([f"OB-{c}"], "", "")
    cases = ["TC-1", "TC-2", "TC-3"]
    d = make(cases, walkers=3)
    d.manual_prepare = prep
    d.consumer = "qa-failure-analyst"
    d.manual_close = lambda cs, refused: d.world.events.append(("manual_close", tuple(cs), tuple(c for c, _ in refused)))
    err, _said = enter(d, cases)
    values = d.world.complete_of
    check("walkers 3, a refused case: no error and some lane gives the open-work word", err is None and any(isinstance(v, SR.OpenWork) for v in values.values()), f"{values} {err!r}")
    d = make(cases, walkers=3)
    d.manual_prepare = prep
    d.manual_close = lambda cs, refused: None
    enter(d, cases)
    check("control: with no consumer the refused case still keeps every lane from closing", not any(v is True for v in d.world.complete_of.values()), f"{d.world.complete_of}")


def resume_road_consumer_ignores_refused():
    """t-2239 B1 sibling: `completion_for` S6 manual, the resume road, follows the live road (X7-6): a refused case does not stop the await."""
    cases = ["TC-1", "TC-2", "TC-3"]
    record = {"execution_kind": "manual", "manual_case_ids": ["TC-1", "TC-2"], "scope": ["TC-1", "TC-2"]}

    def completion(consumer):
        d = make(cases)
        d.manual_prepare = lambda c: ([], "the request could not be prepared", "door") if c == "TC-3" else ([f"OB-{c}"], "", "")
        d.consumer = consumer
        with mock.patch("acceptance.consumer_of", lambda stage: consumer if stage == "S6" else None):
            return d.completion_for("S6", "qa-runner", record)
    check("under a consumer the last block awaits though TC-3 is refused", isinstance(completion("qa-failure-analyst"), SR.OpenWork), repr(completion("qa-failure-analyst")))
    check_eq("control: with no consumer the refused case still keeps the stage open", completion(None), False)


def unreadable_key_lane_request_has_no_walk_actor():
    """t-2239 F3: a lane whose account cannot be read puts neither `walk_lane` nor `walk_actor` on its request (FR-59)."""
    cases = ["TC-1", "TC-2"]
    d = make(cases, {"TC-2": "stand_account:b"})
    d.s6_settling_lanes = lambda lanes: []
    d.run_chains = lambda items, launchable, chain_fn, cap, **k: [chain_fn(DC.ChainRecord(n, cases=tuple(c)), p) for n, c, p in items]
    enter(d, cases)
    got = {request_of(d, i)["scope"][0]: (request_of(d, i).get("walk_lane"), request_of(d, i).get("walk_actor")) for i in registered(d)}
    check_eq("TC-1 (unreadable) carries neither; TC-2 carries both", got, {"TC-1": (None, None), "TC-2": (True, "stand_account:b")})


def walk_reopen_passes_max_shared():
    """t-2239 F4, the driver side: `walk_reopen` adds `--max-shared N` when the walk record holds N > 1; none for 1 or an old record."""
    def argv_for(extra):
        d = make(["TC-1"])
        path = d.task_root / "state" / "walks"
        path.mkdir(parents=True)
        import json
        (path / "S6-qa-runner-1.json").write_text(json.dumps(dict({"walk": "S6-qa-runner-1", "state": "dead", "items": ["TC-1"], "actors": ["guest"]}, **extra)), encoding="utf-8")
        calls = []
        d.py = lambda script, *args, **kw: (calls.append([script, *args]), (0, "x"))[1]
        with contextlib.redirect_stdout(io.StringIO()):
            d.walk_reopen("S6-qa-runner-1")
        return calls[0]
    check_eq("a record with max_shared 3 reopens with `--max-shared 3`", argv_for({"max_shared": 3})[-2:], ["--max-shared", "3"])
    check("a record with 1 adds no flag", "--max-shared" not in argv_for({"max_shared": 1}))
    check("an old record (no field) adds no flag", "--max-shared" not in argv_for({}))


def unreadable_settle_read_stays_serial():
    """t-2239 F5: `s6_settling_lanes` raising keeps the whole entry on the old road, one lane, as the S5 twin does (FR-59)."""
    cases = ["TC-1", "TC-2", "TC-3"]
    d = make(cases)

    def broken(lanes):
        raise OSError("controller.json cannot be read")
    d.s6_settling_lanes = broken
    d.run_chains = mock.Mock(side_effect=AssertionError("an unreadable settle read must not take the parallel road"))
    err, _said = enter(d, cases)
    check_eq("one lane ran, serially", (err, registered(d)), (None, ["S6-qa-runner-1"]))


# --- TR3-10 D2 (t-2282): lanes take their account and record; guest and alone lanes ----------------------------------------------------------

ROLES = {"user": ".env: QA_USER / QA_PASS - a user", "admin": ".env: AUTH_USERNAME / AUTH_PASSWORD - the admin"}
USER, ADMIN, GUEST = "stand_account:user", "stand_account:admin", ""
X2 = "env:QA2_U/QA2_P"


def project(d, safe=True):
    """A real `qa-factory/config.json` above the story folder (the pool readers read real files); `d.task_root` is that folder."""
    root = Path(tempfile.mkdtemp(prefix="d2-proj-"))
    task = root / "qa-factory" / "artifacts" / "T-1"
    task.mkdir(parents=True)
    stand = {"name": "local", "credentials_by_role": ROLES, "safe_to_break": safe}
    (root / "qa-factory" / "config.json").write_text(json.dumps({"environment": {"env_file": ".env"}, "environments": [stand]}), encoding="utf-8")
    d.task_root, d.state_dir = task, task / "state"
    return task


def supply_config(accounts=None, data=None, walkers=None) -> dict:
    manual = {key: value for key, value in (("walkers", walkers), ("accounts_way", accounts), ("data_way", data)) if value is not None}
    return {"manual": manual} if manual else {}


def put_request(d, case, **fields):
    SR._write_json(ME.request_path(d.task_root, case), fields)


def pools_patch(mapping):
    """`walk_pool.pool_of` with the pools of `mapping` {part: (handles, role)}; any other part is read for real."""
    real = WP.pool_of

    def fake(task_root, cfg, case, part, supply, doubts):
        if part in mapping:
            handles, role = mapping[part]
            return WP.Pool(handles, role, 0), []
        return real(task_root, cfg, case, part, supply, doubts)
    return mock.patch("walk_pool.pool_of", fake)


def opened_by(d, assigned, key="stand_account:user"):
    """The argv `walk_session.py open` gets from the REAL `walk_before` for `assigned` (the driver's `py` stood in)."""
    calls: list = []
    d.py = lambda script, *args, **kw: (calls.append([script, *args]), (0, "ok"))[1]
    d.walk_settle_unopened = lambda *a, **k: None
    with contextlib.redirect_stdout(io.StringIO()):
        SR.Driver.walk_before(d, ["TC-1"], "S6-qa-runner-1", assigned)
    return next(c for c in calls if c[0] == "walk_session.py" and c[1] == "open")


def plan_of(*lanes):
    return {"blocks": [list(lane) for lane in lanes], "refused": []}


def walkers_1_reads_no_supply():
    """D.5: walkers 1, or one lane, runs none of the assignment: no supply read, no pool read, no new state key."""
    boom = mock.Mock(side_effect=AssertionError("the old road must not read the supply or a pool"))
    patches = [mock.patch("config_contract.walk_supply", boom), mock.patch("walk_pool.pool_of", boom), mock.patch("walk_pool.assign_lanes", boom)]
    for cases, walkers in ((["TC-1", "TC-2", "TC-3"], 1), (["TC-1"], None)):
        d = make(cases, walkers=walkers)
        d.run_chains = mock.Mock(side_effect=AssertionError("old road"))
        err, _said = enter(d, cases, patches)
        check_eq(f"{len(cases)} lane(s), walkers {walkers}: the road ran and read nothing", (err, boom.called), (None, False))
        check_eq("and left no state key", d.state, {})
    d = make(["TC-1", "TC-2"])
    d.walk_assign_step = boom
    d.state = {"walk_ids": {"1": "S6-qa-runner-7"}, "walk_assign_cases": {"TC-9": 1}}
    d.run_chains = mock.Mock(side_effect=AssertionError("old road"))
    d.s6_walkers_cap = lambda: 1
    enter(d, ["TC-1", "TC-2"])
    check("a key left by an earlier parallel entry is cleared on the old road (no assignment is applied to a lane of another entry)",
          "walk_ids" not in d.state and "walk_assign_cases" not in d.state, repr(d.state))


def stale_reservation_settled_free():
    """L4: a reserved id no dispatch took is settled `free` before the next assignment (no walker touched the record)."""
    d = make(["TC-1", "TC-2"], {"TC-1": USER, "TC-2": ADMIN})
    task = project(d)
    row = {"kind": "book", "instance": "b1", "walk": "S6-qa-runner-7", "item": "TC-9", "state": "in_use", "at": "2026-11-10T10:00:00"}
    WS.update_claims(task, lambda rows: ([*rows, row], None))
    d.state = {"walk_ids": {"1": "S6-qa-runner-7"}}
    with contextlib.redirect_stdout(io.StringIO()):
        d.walk_assign_step(plan_of(["TC-1"], ["TC-2"]))
    check_eq("the stale reservation went free", [r["state"] for r in WS.claims_of(task)[0] if r["walk"] == "S6-qa-runner-7"], ["free"])
    d.world.dispatches["S6-qa-runner-8"] = {"id": "S6-qa-runner-8", "stage": "S6", "role": "qa-runner", "status": "running", "scope": ["TC-1"]}
    WS.update_claims(task, lambda rows: ([*rows, {**row, "walk": "S6-qa-runner-8"}], None))
    d.state = {"walk_ids": {"1": "S6-qa-runner-8"}}
    with contextlib.redirect_stdout(io.StringIO()):
        d.walk_assign_step(plan_of(["TC-1"], ["TC-2"]))
    check_eq("an id a dispatch took is left to its walk (not settled here)", [r["state"] for r in WS.claims_of(task)[0] if r["walk"] == "S6-qa-runner-8"], ["in_use"])
    d.controller_state = lambda: (_ for _ in ()).throw(OSError("controller.json cannot be read"))
    d.state = {"walk_ids": {"1": "S6-qa-runner-8"}, "walk_assign_cases": {"TC-1": 1}}
    d.walk_assign_clear()
    check("with the controller unreadable nothing is dropped (an unknown is never a free)", d.state.get("walk_ids") == {"1": "S6-qa-runner-8"}, repr(d.state))


def lanes_take_distinct_handles_side_by_side():
    cases = ["TC-1", "TC-2"]
    meet, seen = threading.Barrier(2, timeout=WAIT), Overlap()

    def session(did, scope):
        with seen.at_work():
            meet.wait()
    d = make(cases, {c: USER for c in cases}, session=session)
    project(d)
    got: dict = {}
    d.walk_before = lambda lane, did, assigned=None: (got.update({lane[0]: assigned}), {"walking": False, "report_last": False})[1]
    err, said = enter(d, cases, [pools_patch({USER: (["user", X2], "user")})])
    check("two lanes of one account part with two handles in the pool ran at once", err is None and seen.most == 2, repr(err))
    check_eq("each lane got its own handle (and `walk_before` got it)", got, {"TC-1": {USER: "user"}, "TC-2": {USER: X2}})
    check_eq("the state holds the assignment by lane number", d.state["walk_assign"], {"1": {USER: "user"}, "2": {USER: X2}})
    check_eq("holds: one account hold per assigned handle", (d.s6_lane_holds(["TC-1"]), d.s6_lane_holds(["TC-2"])),
             ({"case:TC-1", "account:user"}, {"case:TC-2", "account:" + X2}))
    check("no line about lanes waiting", "wait for each other" not in said, said)


def shared_handle_in_turn():
    cases = ["TC-1", "TC-2"]
    seen = Overlap()

    def session(did, scope):
        with seen.at_work():
            pass
    d = make(cases, {c: USER for c in cases}, session=session)
    project(d)
    err, said = enter(d, cases, [pools_patch({USER: (["user"], "user")})])
    check("one handle for two lanes: in turn, both ran", err is None and seen.most == 1 and d.world.done_cases() == set(cases), repr(err))
    check_in("the console says why (one line per shared handle)", "S6: 2 lanes wait for each other: the project's list holds 1 account(s) for user", said)
    check_eq("said once", said.count("lanes wait for each other"), 1)


def walk_actor_equals_assigned_handle():
    cases = ["TC-1", "TC-2", "TC-3"]
    d = make(cases, {"TC-1": USER, "TC-2": USER, "TC-3": ADMIN + "+" + USER})
    project(d)
    err, _said = enter(d, cases, [pools_patch({USER: (["user", X2], "user")})])
    got = {request_of(d, i)["scope"][0]: request_of(d, i).get("walk_actor") for i in registered(d)}
    check_eq("a lane's `walk_actor` is its handle; two handles are the sorted, `+`-joined string", (err, got),
             (None, {"TC-1": "user", "TC-2": X2, "TC-3": "admin+user"}))


def overlapping_handle_sets_in_turn():
    """Pool `user` = 1 handle; lanes `admin+user` and `user` share a handle, so they hold a common string and run in turn."""
    cases = ["TC-1", "TC-2"]
    keys = {"TC-1": ADMIN + "+" + USER, "TC-2": USER}
    seen = Overlap()

    def session(did, scope):
        with seen.at_work():
            pass
    d = make(cases, keys, session=session)
    project(d)
    err, _said = enter(d, cases)
    check("lanes whose handle sets meet ran in turn, both done", err is None and seen.most == 1 and d.world.done_cases() == set(cases), repr(err))
    check_eq("holds: one per handle", (d.s6_lane_holds(["TC-1"]), d.s6_lane_holds(["TC-2"])),
             ({"case:TC-1", "account:admin", "account:user"}, {"case:TC-2", "account:user"}))
    check("they meet on `account:user`", d.s6_lane_holds(["TC-1"]) & d.s6_lane_holds(["TC-2"]) == {"account:user"})


def old_running_dispatch_runs_alone_first():
    """D.6: a running S6 dispatch of the old road (its `walk_actor` is a key, not a handle) meets lanes with handles: the lane that meets it
    runs ALONE first, so no new lane starts beside it and two sessions never share one real account."""
    cases = ["TC-1", "TC-2", "TC-3"]
    d = make(cases, {"TC-1": ADMIN, "TC-2": USER, "TC-3": ADMIN}, running=[("TC-1", "running")])
    project(d)
    d.world.dispatches["S6-qa-runner-1"].update(walk_lane=True, walk_actor=ADMIN)
    d.run_chains = mock.Mock(side_effect=AssertionError("round one is one lane at a time"))
    err, said = enter(d, cases)
    check_eq("round one: the lane of the running dispatch alone; nothing beside it", (err, registered(d)[-1], len(registered(d))),
             (None, "S6-qa-runner-2", 1))
    check_eq("it is TC-1's lane", d.world.dispatches["S6-qa-runner-2"]["scope"], ["TC-1"])
    check_in("said why", "S6 lanes run one at a time: dispatches of S6 are running or stopped at entry", said)


def guest_lanes_side_by_side_when_data_disjoint():
    cases = ["TC-1", "TC-2", "TC-3"]
    meet, seen = threading.Barrier(3, timeout=WAIT), Overlap()

    def session(did, scope):
        with seen.at_work():
            meet.wait()
    d = make(cases, {c: GUEST for c in cases}, session=session)
    project(d)
    err, _said = enter(d, cases)
    check("three guest lanes with no record in common ran at once", err is None and seen.most == 3, repr(err))
    got = {request_of(d, i)["scope"][0]: request_of(d, i).get("walk_actor") for i in registered(d)}
    check_eq("each guest lane is its own `guest#<lane n>`", got, {"TC-1": "guest#1", "TC-2": "guest#2", "TC-3": "guest#3"})
    check_eq("and holds its own account string", d.s6_lane_holds(["TC-2"]), {"case:TC-2", "account:guest#2"})
    check_eq("a guest lane OPENS as the one `guest` actor", opened_by(make(["TC-1"]), {"": "guest#2"})[-2:], ["--actor", "guest"])
    check_eq("(a guest lane with no assignment keeps `account:guest`)", make(["G"], {"G": ""}).s6_lane_holds(["G"]), {"case:G", "account:guest"})


def guest_lane_walk_global_runs_alone():
    cases = ["TC-1", "TC-2", "TC-3"]
    d = make(cases, {c: GUEST for c in cases})
    project(d)
    put_request(d, "TC-2", walk_global="the Then counts every book")
    d.run_chains = mock.Mock(side_effect=AssertionError("round one is the one alone lane"))
    err, _said = enter(d, cases)
    check_eq("a guest lane whose request names `walk_global` ran first and alone", (err, [request_of(d, i)["scope"] for i in registered(d)]), (None, [["TC-2"]]))
    check_eq("marked alone in the state", d.state["walk_alone"], ["TC-2"])
    del d.run_chains
    meet, seen = threading.Barrier(2, timeout=WAIT), Overlap()

    def session(did, scope):
        with seen.at_work():
            meet.wait()
    d.session_fn = session
    err, _said = enter(d, cases)
    check("the next entry runs the others side by side", err is None and seen.most == 2 and d.world.done_cases() == set(cases), repr(err))


def walk_global_lane_runs_alone():
    cases = ["TC-1", "TC-2", "TC-3"]
    d = make(cases, {"TC-1": USER, "TC-2": ADMIN, "TC-3": USER})
    project(d)
    put_request(d, "TC-2", walk_global="the Then counts every user")
    d.run_chains = mock.Mock(side_effect=AssertionError("round one is the one alone lane"))
    err, said = enter(d, cases, [pools_patch({USER: (["user", X2], "user")})])
    check_eq("the lane with `walk_global` ran first and alone", (err, [request_of(d, i)["scope"] for i in registered(d)]), (None, [["TC-2"]]))
    check_eq("a request with no field is not alone", d.state["walk_alone"], ["TC-2"])


def book_data(**more):
    return {"pools": {"book": {"existing": ["b1", "b2"][:more.pop("n", 2)]}}, **more}


def exclusive_kind_no_pool_alone():
    cases = ["TC-1", "TC-2"]
    plan = plan_of(["TC-1"], ["TC-2"])
    for words, alone in ((None, ["TC-1"]), ("share what you like", [])):
        d = make(cases, {"TC-1": USER, "TC-2": ADMIN}, config=supply_config(data=None if words is None else {"words": words}))
        project(d)
        put_request(d, "TC-1", walk_data=[{"kind": "Invoice", "exclusive": True, "changes": "sends one"}])
        with contextlib.redirect_stdout(io.StringIO()):
            facts = d.walk_assign_step(plan)
        check_eq(f"data words {words!r}: a lane that needs an exclusive kind with no pool", d.state["walk_alone"], alone)
        check_eq("the facts the question will need name the kind", facts["alone_kinds"], ["Invoice"] if alone else [])
        check_eq("and carry the supply", facts["supply"]["data"]["known"], words is not None)
    d = make(cases, {"TC-1": USER, "TC-2": ADMIN}, config=supply_config(data={"pools": {"book": {"existing": ["b1"]}}}))
    project(d)
    put_request(d, "TC-1", walk_data=[{"kind": "Book", "exclusive": True, "changes": "x"}])
    put_request(d, "TC-2", walk_data=[{"kind": "book", "exclusive": True, "changes": "y"}])
    with contextlib.redirect_stdout(io.StringIO()):
        facts = d.walk_assign_step(plan)
    check_eq("one instance for two lanes and no words: the lane that got none is alone", d.state["walk_alone"], ["TC-2"])
    check_eq("(the kind that had a pool but no free instance is named too)", facts["alone_kinds"], ["book"])


def exclusive_kinds_distinct_instances_side_by_side():
    cases = ["TC-1", "TC-2"]
    meet, seen = threading.Barrier(2, timeout=WAIT), Overlap()

    def session(did, scope):
        with seen.at_work():
            meet.wait()
    d = make(cases, {"TC-1": USER, "TC-2": ADMIN}, session=session, config=supply_config(data=book_data()))
    task = project(d)
    for case in cases:
        put_request(d, case, walk_data=[{"kind": "book", "exclusive": True, "changes": "deletes one book"}])
    err, _said = enter(d, cases)
    check("two lanes that change the same kind but are given two instances ran at once", err is None and seen.most == 2, repr(err))
    check_eq("instances by lane", {n: [(e["instance"], e["how"]) for found in v.values() for e in found] for n, v in d.state["walk_entities"].items()},
             {"1": [("b1", "existing")], "2": [("b2", "existing")]})
    check_eq("holds name the instance", (d.s6_lane_holds(["TC-1"]), d.s6_lane_holds(["TC-2"])),
             ({"case:TC-1", "account:user", "data:book:b1"}, {"case:TC-2", "account:admin", "data:book:b2"}))
    check_eq("no lane is alone", d.state["walk_alone"], [])
    check_eq("L1: the id of each walk is the id its records were written under", sorted(registered(d)), sorted(d.state["walk_ids"].values()))
    check_eq("the claims store holds those ids `in_use` for those instances",
             sorted((r["walk"], r["instance"], r["state"]) for r in WS.claims_of(task)[0]),
             [("S6-qa-runner-1", "b1", "in_use"), ("S6-qa-runner-2", "b2", "in_use")])


def guest_lanes_same_exclusive_kind_one_instance_in_turn():
    cases = ["TC-1", "TC-2"]
    seen = Overlap()

    def session(did, scope):
        with seen.at_work():
            pass
    d = make(cases, {c: GUEST for c in cases}, session=session, config=supply_config(data=book_data(n=1)))
    task = project(d)
    for case in cases:
        put_request(d, case, walk_data=[{"kind": "book", "exclusive": True, "changes": "deletes one book"}])
    d.run_chains = mock.Mock(side_effect=AssertionError("round one is one lane at a time"))
    err, _said = enter(d, cases)
    check_eq("one instance, two guest lanes: the one with none runs ALONE first", (err, [request_of(d, i)["scope"] for i in registered(d)]), (None, [["TC-2"]]))
    err, _said = enter(d, cases)
    check("the other follows in turn: never at once, both done", err is None and seen.most == 1 and d.world.done_cases() == set(cases), repr(err))
    check_eq("the reservation of the lane that waited went `free` at its entry (no walker touched the record)",
             [r["state"] for r in WS.claims_of(task)[0] if r["walk"] == "S6-qa-runner-1"], ["free"])


def no_walk_data_row_not_alone():
    cases = ["TC-1", "TC-2"]
    d = make(cases, {"TC-1": USER, "TC-2": ADMIN}, config=supply_config(data=book_data()))
    task = project(d)
    plan = plan_of(["TC-1"], ["TC-2"])
    with contextlib.redirect_stdout(io.StringIO()):
        d.walk_assign_step(plan)
    check_eq("no `walk_data` anywhere: nobody is alone, nothing reserved, no claim written", (d.state["walk_alone"], d.state["walk_ids"], WS.claims_of(task)),
             ([], {}, ([], "")))
    put_request(d, "TC-1", walk_data=[{"kind": "book", "exclusive": False, "changes": "reads"}])
    with contextlib.redirect_stdout(io.StringIO()):
        d.walk_assign_step(plan)
    check_eq("a non-exclusive entry is no constraint either", d.state["walk_alone"], [])
    d = make(["TC-1"])
    err, _said = enter(d, ["TC-1"])
    check_eq("an old plan (one lane) has no assignment at all", (err, d.state), (None, {}))


def empty_plan_no_crash():
    d = make(["TC-1"], {})
    project(d)
    with contextlib.redirect_stdout(io.StringIO()):
        facts = d.walk_assign_step({"blocks": [[], ["TC-1"]], "refused": []})
        d.walk_assign_step({"blocks": [], "refused": []})
    check_eq("a lane with no cases and an empty plan: no crash, no assignment", (d.state.get("walk_assign"), facts["alone_kinds"]), ({}, []))


# --- TR3-10 D2 step 3 (t-2292): the prompt lines of an assigned lane; the failed sign-up of an obtain lane ------------------------------------------

CLAIM = ("Before you change a record other walkers could also use, claim it: `walk_session.py claim --kind <what it is> --instance <its id>` "
         "(`--all` when your check reads the whole list); a claim held by another walker waits a little, then tells you what to do.")
DATA_LINE = 'How this project handles shared records, in the person\'s words: "{}"'
OBTAIN_WAY = {"words": "the app makes them", "self_sign_up": {"roles": ["user"]}}


def obtain_pair(data=None, accounts=None, walkers=None):
    """Two lanes of ONE account (a pool of one) and a role that may sign up: lane 1 takes `user`, lane 2 takes `obtain:user#2`."""
    cases = ["TC-1", "TC-2"]
    d = make(cases, {c: USER for c in cases}, walking=True, config=supply_config(accounts=accounts or OBTAIN_WAY, data=data, walkers=walkers))
    project(d)
    err, _said = enter(d, cases, [pools_patch({USER: (["user"], "user")})])
    check_eq("the pair ran", (err, d.world.done_cases()), (None, set(cases)))
    return d, {request_of(d, i)["scope"][0]: d.extras[i] for i in registered(d)}


def obtain_lane_opens_guest_with_lines():
    d, lines = obtain_pair()
    check_eq("lane 2 took the obtain handle", d.state["walk_assign"]["2"], {USER: "obtain:user#2"})
    check_in("the obtain lane's prompt carries the obtain sentence", "make your own user on the app's sign-up page with `fill-new-account` steps",
             " ".join(lines["TC-2"]))
    check("the lane with a pool handle gets no obtain sentence", not any("fill-new-account" in line for line in lines["TC-1"]), repr(lines["TC-1"]))
    check("EVERY assigned lane gets the claim sentence", CLAIM in lines["TC-1"] and CLAIM in lines["TC-2"], repr(lines))
    check_eq("no data words known: no line about them", [line for line in lines["TC-2"] if "shared records" in line], [])
    check_eq("an obtain handle OPENS as the guest (the real `walk_before`)", opened_by(make(["TC-1"]), {USER: "obtain:user#2"})[-2:], ["--actor", "guest"])
    # the lane keeps the entity line of its record
    cases = ["TC-1", "TC-2"]
    d = make(cases, {"TC-1": USER, "TC-2": ADMIN}, walking=True, config=supply_config(data=book_data()))
    project(d)
    for case in cases:
        put_request(d, case, walk_data=[{"kind": "book", "exclusive": True, "changes": "deletes one book"}])
    enter(d, cases)
    got = {request_of(d, i)["scope"][0]: d.extras[i] for i in registered(d)}
    check("each lane's prompt names its own record", any("`b1`" in line for line in got["TC-1"]) and any("`b2`" in line for line in got["TC-2"]), repr(got))
    check("(and not the other lane's)", not any("`b2`" in line for line in got["TC-1"]), repr(got["TC-1"]))
    # a lane that is not assigned: walkers 1, one lane - the prompt as before
    for cases, walkers in ((["TC-1", "TC-2"], 1), (["TC-1"], None)):
        d = make(cases, {c: USER for c in cases}, walking=True, config=supply_config(data={"words": "share nothing"}, walkers=walkers))
        enter(d, cases)
        for did in registered(d):
            check_eq(f"walkers {walkers}, {len(cases)} lane(s): the prompt is today's one line", len(d.extras[did]), 1)


def obtain_same_address_confirm_then_sign_in():
    """The confirm word: a same-address sign-up stays `unconfirmed` and `fill-account created:` is refused, so the prompt tells the walker the
    way out; the sentences are the charter's, word for word."""
    _d, lines = obtain_pair()
    text = " ".join(" ".join(lines["TC-2"]).split())
    for part in ("then sign in with `fill-account <selector> created:<name> user|secret`", "'was not seen to land' but you saw the app accept it",
                 "say `account created:<name> confirmed \"<what you saw>\"` and sign in again",
                 "say `account created:<name> unconfirmed \"<what you saw>\"` and end without walking the items"):
        check_in("the obtain lane's prompt says", part, text)
    charter = " ".join((SCRIPTS.parent / "references" / "walk-charter.md").read_text(encoding="utf-8").split())
    check_in("the claim sentence is the charter's", " ".join(CLAIM.split()), charter)
    check_in("the confirm word is the charter's", "account created:<name> confirmed \"<what you saw>\"", charter)


def data_words_line_secret_masked():
    words = "claim a record before you change it; deleting a book is fine"
    secret = 'login with password: "abcdefghijklmnop1234" and then share'
    for label, data, want in (("known words, whole", {"words": words}, DATA_LINE.format(words)),
                              ("words that look like a secret", {"words": secret}, DATA_LINE.format("(not shown: they look like a secret)")),
                              ("absent words", {"pools": {}}, None), ("empty words", {"words": "   "}, None), ("words not known", {"words": "not known"}, None)):
        _d, lines = obtain_pair(data=data)
        got = [line for line in lines["TC-1"] if "shared records" in line]
        check_eq(f"{label}: the line", got, [want] if want else [])
        if want and "not shown" in want:
            check("the secret is nowhere in the lane's prompt", not any("abcdefghijklmnop1234" in line for line in lines["TC-1"] + lines["TC-2"]), repr(lines))
    with mock.patch("manual_capture.secret_pattern_hit", mock.Mock(side_effect=ValueError("bad pattern"))):
        _d, lines = obtain_pair(data={"words": words})
    check_in("a pattern list that cannot be read masks the words too (an unknown is never shown)", DATA_LINE.format("(not shown: they look like a secret)"),
             lines["TC-1"])


def obtain_walk(d, handle="obtain:user#2", lane=("TC-1", "TC-2"), rows=None, names=None, result=None):
    """The REAL `walk_after` over `lane` assigned `handle`; `rows` is what `walk_case_records` built, `names` the names file's rows."""
    task = d.task_root
    d.state.update({"walk_assign_cases": {lane[0]: 2} if lane else {}, "walk_assign": {"2": {USER: handle}}})
    if names is not None:
        import manual_capture as MC
        SR._write_json(MC.created_names_path(task), {"accounts": names})
    d.py = lambda script, *args, **kw: (0, "")
    d.walk_values = lambda dispatch, built: None
    d.walk_case_records = lambda lane_, did, built: built.update(rows or {})
    with contextlib.redirect_stdout(io.StringIO()) as said:
        SR.Driver.walk_after(d, list(lane), "S6-qa-runner-2", result)
    return said.getvalue()


def failed_obtain_requeues_once_and_stops_obtain():
    reason = "its walker could not get an account: the sign-up was not seen to land"
    d = make(["TC-1", "TC-2"], {"TC-1": USER, "TC-2": USER})
    task = project(d)
    gone = {"state": "inconclusive", "missing": True}
    done = {"state": "passed", "missing": False}
    said = obtain_walk(d, rows={"TC-1": dict(gone), "TC-2": dict(done)}, names=[{"name": "u1", "case": "TC-1", "status": "unconfirmed"}])
    retry = d.state["walk_retry"]
    check_eq("the case without a verdict is re-queued as ONE refusal with the reason", (retry["TC-1"]["refused"], retry["TC-1"]["open"], retry["TC-1"]["reason"]), (1, True, reason))
    check("a case that HAS a verdict is not re-queued", "TC-2" not in retry, repr(retry))
    check_eq("the role gets no obtain lane for the rest of the story", d.state["obtain_failed"], {"user": True})
    check_eq("after.json carries the refused row (the re-run skips it)", json.loads((task / "work/walks/S6-qa-runner-2/after.json").read_text())["rows"]["TC-1"]["state"], "refused")
    check_in("said", "walked once more in the next lane", said)
    # idempotent: the same run again is no second refusal
    obtain_walk(d, rows={"TC-1": {"state": "refused", "missing": True}, "TC-2": dict(done)}, names=[{"name": "u1", "case": "TC-1", "status": "unconfirmed"}])
    check_eq("a second run of the same walk counts nothing more", d.state["walk_retry"]["TC-1"]["refused"], 1)
    # D.9: the next entry gives that role no obtain lane (the lanes take the pool in turn)
    d2 = make(["TC-1", "TC-2"], {c: USER for c in ("TC-1", "TC-2")}, config=supply_config(accounts=OBTAIN_WAY))
    project(d2)
    d2.state["obtain_failed"] = {"user": True}
    with pools_patch({USER: (["user"], "user")}), contextlib.redirect_stdout(io.StringIO()):
        d2.walk_assign_step(plan_of(["TC-1"], ["TC-2"]))
    check_eq("`assign_lanes` is not given the failed role: both lanes share the one handle", d2.state["walk_assign"], {"1": {USER: "user"}, "2": {USER: "user"}})
    d3 = make(["TC-1", "TC-2"], {c: USER for c in ("TC-1", "TC-2")}, config=supply_config(accounts=OBTAIN_WAY))
    project(d3)
    with pools_patch({USER: (["user"], "user")}), contextlib.redirect_stdout(io.StringIO()):
        d3.walk_assign_step(plan_of(["TC-1"], ["TC-2"]))
    check_eq("(control: with no failure the second lane takes the obtain handle)", d3.state["walk_assign"]["2"], {USER: "obtain:user#2"})
    # the second failure closes the case by the EXISTING rule
    with contextlib.redirect_stdout(io.StringIO()):
        d.walk_refusal("TC-1", reason, d.state["walk_retry"])
    check_eq("a second refusal closes the case `left_unchecked`", json.loads(ME.request_path(task, "TC-1").read_text())["refused"]["by"], "left_unchecked")


def obtain_confirmed_or_odd_lane_changes_nothing():
    names_ok = [{"name": "u1", "case": "TC-1"}]       # no `status`: confirmed
    for label, kwargs in (("a confirmed user", dict(names=names_ok, rows={"TC-1": {"state": "inconclusive", "missing": True}})),
                          ("a user confirmed by the walker's word", dict(names=[{"name": "u1", "case": "TC-1", "confirmed_by": "walker"}],
                                                                         rows={"TC-1": {"state": "inconclusive", "missing": True}})),
                          ("a handle that is not an obtain handle", dict(handle="user", names=[], rows={"TC-1": {"state": "inconclusive", "missing": True}}))):
        d = make(["TC-1", "TC-2"], {"TC-1": USER, "TC-2": USER})
        project(d)
        obtain_walk(d, lane=("TC-1",), **kwargs)
        check_eq(f"{label}: nothing re-queued, nothing recorded", (d.state.get("walk_retry", {}), d.state.get("obtain_failed")), ({}, None))
    # result None, a crashed walker, an empty lane, no names file at all: no crash
    for label, kwargs in (("result None, no names file", dict(lane=("TC-1",), rows={"TC-1": {"state": "inconclusive", "missing": True}})),
                          ("an empty lane", dict(lane=())), ("a crashed walker's result", dict(lane=("TC-1",), result={"crashed": True}, names=[],
                                                                                                    rows={"TC-1": {"state": "inconclusive", "missing": True}}))):
        d = make(["TC-1"], {"TC-1": USER})
        project(d)
        try:
            obtain_walk(d, **kwargs)
            err = None
        except Exception as exc:    # noqa: BLE001
            err = exc
        check_eq(f"{label}: no crash", err, None)
        if not kwargs["lane"]:
            check_eq("(an empty lane re-queues and records nothing)", (d.state.get("walk_retry", {}), d.state.get("obtain_failed")), ({}, None))


SCENARIOS = [consumer_refused_case_still_awaits, resume_road_consumer_ignores_refused, unreadable_key_lane_request_has_no_walk_actor,
             walk_reopen_passes_max_shared, unreadable_settle_read_stays_serial, walkers_default_three_lanes_overlap, walkers_1_takes_old_road_no_thread, no_thread_started_at_walkers_1, one_lane_old_body,
             same_account_lanes_in_turn, overlapping_part_sets_in_turn, lane_crash_others_finish_one_seam, drained_lane_registers_no_dispatch,
             close_exactly_once_order_free, unreadable_lane_state_is_open, ids_never_shared, settling_lanes_first_then_parallel,
             unreadable_account_lane_runs_first, serial_reason_each_row, lane_interrupt_kills_children, held_case_keeps_serial,
             same_account_second_lane_never_registers, walk_open_carries_max_shared, close_waits_for_a_blocked_lane,
             consumer_branch_never_author_close, lane_question_queued_next, crashed_lane_closes_its_walk,
             request_carries_walk_lane_and_actor, story_run_makes_no_new_thread_site,
             walkers_1_reads_no_supply, stale_reservation_settled_free, lanes_take_distinct_handles_side_by_side, shared_handle_in_turn,
             walk_actor_equals_assigned_handle, overlapping_handle_sets_in_turn, old_running_dispatch_runs_alone_first,
             guest_lanes_side_by_side_when_data_disjoint, guest_lane_walk_global_runs_alone, walk_global_lane_runs_alone,
             exclusive_kind_no_pool_alone, exclusive_kinds_distinct_instances_side_by_side, guest_lanes_same_exclusive_kind_one_instance_in_turn,
             no_walk_data_row_not_alone, empty_plan_no_crash, obtain_lane_opens_guest_with_lines, obtain_same_address_confirm_then_sign_in,
             data_words_line_secret_masked, failed_obtain_requeues_once_and_stops_obtain, obtain_confirmed_or_odd_lane_changes_nothing]


def main() -> None:
    try:
        for fn in SCENARIOS:
            fn()
    finally:
        SR.lane_keys = SHOWN["lane_keys"]
    finish("test_walk_lanes_parallel")


if __name__ == "__main__":
    main()
