#!/usr/bin/env python3
"""The chain record of the driver: per-thread `boundary` and `last_dispatch`, `as_chain` / `adopt_chain`, `closes` with an explicit
dispatch, the `chain` of a `Refusal`, and `ChainStream` (t-1937 node TR3-17). No behaviour change on the serial road.

Every case builds a bare `Driver` (`Driver.__new__`, no run, no subprocess) and drives real threads that are joined at once (FR-31)."""
import io
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import SCRIPTS, check, check_eq, check_in, finish  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import story_run as SR  # noqa: E402
import driver_chains as DC  # noqa: E402  (the scheduler's names are read from their own module, not through story_run)


def driver() -> "SR.Driver":
    return SR.Driver.__new__(SR.Driver)


def on_thread(fn):
    """Run `fn()` on a fresh thread; return (result, exception)."""
    box = {}

    def target():
        try:
            box["result"] = fn()
        except BaseException as exc:      # the case reads what the thread raised
            box["error"] = exc
    t = threading.Thread(target=target)
    t.start()
    t.join()
    return box.get("result"), box.get("error")


def thread_local_values_isolated():
    d = driver()
    d.boundary, d.last_dispatch = "S5:main", "S5-main-1"
    seen = {}

    gate, done = threading.Barrier(2), threading.Barrier(2)

    def chain(name, n):
        with d.as_chain(DC.ChainRecord(n)):
            d.boundary, d.last_dispatch = f"S5:{name}", f"S5-{name}-1"
            gate.wait(timeout=10)                # both chains have written before either reads
            seen[name] = (d.boundary, d.last_dispatch)
            done.wait(timeout=10)                # and both are still inside while the other reads
    ts = [threading.Thread(target=chain, args=("a", 1)), threading.Thread(target=chain, args=("b", 2))]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    check_eq("chain a reads its own two values", seen["a"], ("S5:a", "S5-a-1"))
    check_eq("chain b reads its own two values", seen["b"], ("S5:b", "S5-b-1"))
    # two drivers on one thread do not share slots (the per-instance store of the serial road)
    other = driver()
    check_eq("another driver's last_dispatch is still the empty default", other.last_dispatch, "")
    err = None
    try:
        other.boundary
    except AttributeError as exc:
        err = exc
    check("another driver's boundary is unset: AttributeError, no default", err is not None)


def main_keeps_its_own_values():
    d = driver()
    d.boundary, d.last_dispatch = "S5:main", "S5-main-1"

    def chain():
        with d.as_chain(DC.ChainRecord(1, "S5:w1", "S5-w1-1")):
            d.boundary, d.last_dispatch = "S5:w1:x", "S5-w1-2"
    on_thread(chain)
    check_eq("main still reads its own values after a chain ran", (d.boundary, d.last_dispatch), ("S5:main", "S5-main-1"))
    _res, error = on_thread(lambda: d.boundary)
    check("a fresh thread reads boundary before any initialiser: AttributeError", isinstance(error, AttributeError))
    res, error = on_thread(lambda: d.last_dispatch)
    check_eq("a fresh thread reads last_dispatch: the empty default", (res, error), ("", None))
    res, _e = on_thread(lambda: getattr(d, "last_dispatch", "d"))
    check_eq("getattr(self, 'last_dispatch', '') answers '' on a fresh thread", res, "")
    bare = driver()
    check_eq("getattr on a driver that never set it answers ''", getattr(bare, "last_dispatch", ""), "")
    check_eq("a boundary that was never set is not defaulted by getattr's own default either", getattr(bare, "boundary", "unset"), "unset")


def as_chain_restores():
    d = driver()
    d.boundary, d.last_dispatch = "M", "D-main"
    record = DC.ChainRecord(3, "S5:w3", "S5-w3-1")
    with d.as_chain(record):
        check_eq("inside: the record's values", (d.boundary, d.last_dispatch), ("S5:w3", "S5-w3-1"))
        d.boundary, d.last_dispatch = "S5:w3:later", "S5-w3-2"
    check_eq("after: the thread's earlier values are back", (d.boundary, d.last_dispatch), ("M", "D-main"))
    check_eq("the record keeps where the chain stood", (record.boundary, record.last_dispatch), ("S5:w3:later", "S5-w3-2"))
    check("the chain of this thread is cleared", getattr(DC._CHAIN, "record", None) is None)
    # a raising block restores too
    try:
        with d.as_chain(DC.ChainRecord(4)):
            raise ValueError("boom")
    except ValueError:
        pass
    check_eq("a block that raised restores as well", (d.boundary, d.last_dispatch), ("M", "D-main"))
    # a thread that had NOTHING returns to nothing
    def fresh():
        with d.as_chain(DC.ChainRecord(5)):
            pass
        try:
            d.boundary
        except AttributeError:
            return "unset"
        return "set"
    check_eq("a fresh thread is unset again after the chain", on_thread(fresh)[0], "unset")


def adopt_chain_stays():
    d = driver()
    d.boundary, d.last_dispatch = "M", "D-main"
    record = DC.ChainRecord(2, "S5:w2:stand", "S5-w2-4")
    d.adopt_chain(record)
    check_eq("adopted: this thread reads the record's values", (d.boundary, d.last_dispatch), ("S5:w2:stand", "S5-w2-4"))
    check("adopting does not make this thread a chain", getattr(DC._CHAIN, "record", None) is None)
    d.adopt_chain(None)
    check_eq("no record (a serial refusal): nothing changes", (d.boundary, d.last_dispatch), ("S5:w2:stand", "S5-w2-4"))
    # TR3-6 extended the record with the scheduler's fields; still plain data: no thread or lock object, a process only while one runs
    check_eq("the record is plain data: no thread object in it", sorted(vars(record)),
             ["boundary", "cases", "done", "exception", "last_dispatch", "n", "proc", "running", "tag"])
    check("... and a fresh one holds no process and no exception", record.proc is None and record.exception is None and not record.running)


def closes_reads_given_dispatch():
    d = driver()
    d.last_dispatch = "S5-thread-OTHER"
    calls = {"route": [], "answer": []}

    def route_of(text, budget, dispatch=""):
        calls["route"].append(dispatch)
        return {"action": "close"}, None
    d.route_of = route_of
    d.repair_answer = lambda cases, dispatch: calls["answer"].append(dispatch) or {}
    box = {}

    def run_role(stage, role, **kw):
        box["closes"] = kw["complete"]
        box["verdicts"] = (kw["complete"]("digest", "S5-given-7"), kw["complete"]("digest"))
        return "digest", None
    d.run_role = run_role
    d.S5_CRITIC_BRIEF = ()
    d.s5_review(["TC-1"], True, None, None)
    check_eq("an explicit dispatch reaches route_of and repair_answer", (calls["route"][0], calls["answer"][0]), ("S5-given-7", "S5-given-7"))
    check_eq("the digest alone (finish's call) reads this thread's last_dispatch", (calls["route"][1], calls["answer"][1]), ("S5-thread-OTHER", "S5-thread-OTHER"))
    check_eq("the last window with a close route: both calls close", box["verdicts"], (True, True))
    d.route_of = lambda text, budget, dispatch="": ({"action": "close"}, None)
    d.s5_review(["TC-1"], False, None, None)
    check_eq("not the last window: never a close", box["verdicts"], (False, False))
    # the loop's own route_of after the review reads the critic the thread recorded
    check_eq("the review's own route_of gets the thread's critic", calls["route"][-1], "S5-thread-OTHER")


def refusal_retry_reads_its_own_chain():
    d = driver()
    d.boundary, d.last_dispatch = "M", "D-main"
    check("a refusal on the main thread carries no chain", SR.Refusal("x").chain is None)
    record = DC.ChainRecord(6, "S5:w6", "S5-w6-1")
    holder = {}

    def chain():
        try:
            with d.as_chain(record):
                d.boundary, d.last_dispatch = "S5:w6:handoff", "S5-w6-2"
                raise SR.Refusal("handoff refused", dispatch="S5-w6-2")
        except SR.Refusal as refusal:
            holder["refusal"] = refusal
    on_thread(chain)
    refusal = holder["refusal"]
    check("a refusal raised in a chain carries its record", refusal.chain is record)
    check("a subclass does too", SR.ReworkRefused("what", "t").chain is None)
    d.adopt_chain(refusal.chain)
    check_eq("the retry on main reads the chain's values", (d.boundary, d.last_dispatch), ("S5:w6:handoff", "S5-w6-2"))


def chain_stream_prefixes_only_chain_lines():
    sink = io.StringIO()
    stream = DC.ChainStream(sink)
    d = driver()
    d.boundary = "M"
    stream.write("main line\n")

    def chain(n, text):
        with d.as_chain(DC.ChainRecord(n)):
            stream.write(text)
            stream.flush()
    on_thread(lambda: chain(2, "one\ntwo\n"))
    stream.write("main again\n")

    def partial():
        with d.as_chain(DC.ChainRecord(3)):
            stream.write("part")
            stream.flush()
            stream.write("ial\nB\n")
    on_thread(partial)
    lines = sink.getvalue().split("\n")
    check_eq("main lines carry nothing, chain lines carry [W<n>]", lines[:4], ["main line", "[W2] one", "[W2] two", "main again"])
    check_eq("a flushed partial line is not held back and gets no second prefix", lines[4:6], ["[W3] partial", "[W3] B"])
    # concurrent chains never split each other's line
    sink2 = io.StringIO()
    s2 = DC.ChainStream(sink2)
    gate = threading.Barrier(4)

    def talk(n):
        with d.as_chain(DC.ChainRecord(n)):
            gate.wait(timeout=10)
            for i in range(50):
                s2.write("a")
                s2.write(f"b{i}\n")
    ts = [threading.Thread(target=talk, args=(n,)) for n in range(1, 5)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    rows = [r for r in sink2.getvalue().split("\n") if r]
    check_eq("200 whole lines", len(rows), 200)
    check("every line is one chain's whole line", all(len(r) > 5 and r.startswith("[W") and r[3:5] == "] " and "ab" in r for r in rows))
    check_eq("attribute passthrough", DC.ChainStream(io.StringIO()).getvalue(), "")


def serial_values_unchanged():
    d = driver()
    d.boundary = "start"
    d.boundary = "S5:TC-1"
    d.last_dispatch = "S5-qa-code-critic-2"
    check_eq("serial: what was set is what is read", (d.boundary, d.last_dispatch), ("S5:TC-1", "S5-qa-code-critic-2"))
    check("no attribute lands in the instance under the old names", "boundary" not in d.__dict__ and "last_dispatch" not in d.__dict__)
    check_eq("a Refusal's text, fields and chain on the serial road", (SR.Refusal(" say no ", dispatch="D").text, SR.Refusal("x").dispatch, SR.Refusal("x").chain), ("say no", "", None))
    sink = io.StringIO()
    stream = DC.ChainStream(sink)
    stream.write("plain ")
    stream.write("bytes\n")
    stream.flush()
    check_eq("main thread through ChainStream: every byte as written", sink.getvalue(), "plain bytes\n")
    seen = []
    d.route_of = lambda text, budget, dispatch="": seen.append(dispatch) or ({"action": "close"}, None)
    d.repair_answer = lambda cases, dispatch: {}
    d.run_role = lambda stage, role, **kw: (kw["complete"]("digest"), None)
    d.S5_CRITIC_BRIEF = ()
    d.s5_review(["TC-1"], True, None, None)
    check_eq("serial s5_review: route_of reads the one critic dispatch both times", seen, ["S5-qa-code-critic-2", "S5-qa-code-critic-2"])


# --- TR3-6: the scheduler, the lock, the close predicate, the serial reason, the seam, the gate (fake step / launch, real threads) ------
import contextlib  # noqa: E402
import tempfile  # noqa: E402


def sched_driver(windows=None, dispatches=None, **state) -> "SR.Driver":
    """A bare Driver with the readers the scheduler uses replaced by fakes: `windows` are `(cases, accepted)` pairs."""
    d = driver()
    d.task, d.host, d.dry, d.config, d.state = "T-1", "claude", True, {}, dict(state)
    d.task_root = Path(tempfile.mkdtemp(prefix="tr36-"))
    d.state_dir = d.task_root / "state"
    wins = [{"scope": list(c), "accepted_by": ({"qa-code-critic": "x"} if acc else {})} for c, acc in (windows or [])]
    d.stage_scope = lambda stage, kind="": {"windows": wins}
    d.controller_state = lambda: {"dispatches": dispatches if dispatches is not None else {}}
    return d


def as_chain_thread(d, n, body, cases=()):
    """Run `body()` on a thread that is chain `n` and holds `_book` as a scheduler's chain does; returns (record, error)."""
    record = DC.ChainRecord(n, cases=tuple(cases))
    box = {}

    def target():
        d._book.acquire()
        try:
            with d.as_chain(record):
                body()
        except BaseException as exc:      # noqa: BLE001 - the case reads it
            box["error"] = exc
        finally:
            d._book.release()
    t = threading.Thread(target=target)
    t.start()
    return record, box, t


def unbooked_releases_once_and_retakes_on_exception():
    d = sched_driver()
    seen = {}

    def body():
        try:
            with d.unbooked("D1"):
                seen["inside"] = d._book.locked()
                raise RuntimeError("boom")
        except RuntimeError:
            seen["after"] = d._book.locked()
    _r, box, t = as_chain_thread(d, 1, body)
    t.join()
    check_eq("on a chain with a dispatch the lock is free inside the block", seen.get("inside"), False)
    check_eq("... and taken back exactly once when the block raised (the chain then released it itself)", (seen.get("after"), d._book.locked()), (True, False))
    check("... no error escaped", "error" not in box)


def conductor_launch_holds_book():
    d = sched_driver()
    seen = {}

    def body():
        with d.unbooked(""):
            seen["chain_no_dispatch"] = d._book.locked()
    _r, _b, t = as_chain_thread(d, 1, body)
    t.join()
    d._book.acquire()
    with d.unbooked("D9"):
        seen["main"] = d._book.locked()
    d._book.release()
    check_eq("a call with no dispatch (conductor, delivery) keeps the lock", seen.get("chain_no_dispatch"), True)
    check_eq("the main thread never releases it, dispatch or not", seen.get("main"), True)


def settling_one_at_a_time():
    d = sched_driver()
    state = {"now": 0, "most": 0, "book_free_inside": 0}
    gate = threading.Barrier(2, timeout=10)

    def settle():
        with d.unbooked(settling=True):
            state["now"] += 1
            state["most"] = max(state["most"], state["now"])
            if d._book.acquire(False):          # a critic's start does not hold the lock for the others' bookkeeping
                state["book_free_inside"] += 1
                d._book.release()
            threading.Event().wait(0.05)
            state["now"] -= 1
    def meet_then_settle():
        with d.unbooked("D"):       # both chains are at work (outside the lock) before they ask to settle together
            gate.wait()
        settle()
    threads = [as_chain_thread(d, n, meet_then_settle)[2] for n in (1, 2)]
    for t in threads:
        t.join()
    check_eq("two critics' starts never settle together", state["most"], 1)
    check("the lock was free while a start settled", state["book_free_inside"] >= 1)


def open_windows_each_reason():
    wins = [(("A",), True), (("B",), True), (("C",), False)]
    d = sched_driver(wins)
    check_eq("an open critic is open; the asking window is not counted", d.s5_open_windows(excluding=["A"]), [["C"]])
    d = sched_driver(wins[:2], {"d1": {"id": "d1", "stage": "S5", "status": "running", "scope": ["B"], "role": "qa-code-critic"}})
    check_eq("a running dispatch that meets a scope keeps it open", d.s5_open_windows(excluding=["A"]), [["B"]])
    d = sched_driver(wins[:2], repair_limit={"S5|B": {"token": "round", "cases": ["B"], "executed": False, "dispatch": "c1"}})
    check_eq("an owed round keeps it open", d.s5_open_windows(excluding=["A"]), [["B"]])
    d = sched_driver(wins[:2])
    d._chains[2] = DC.ChainRecord(2, cases=("B",))
    check_eq("a live chain keeps it open", d.s5_open_windows(excluding=["A"]), [["B"]])
    d._chains[2].done = True
    check_eq("... and a chain that ended does not", d.s5_open_windows(excluding=["A"]), [])


def open_windows_unreadable_is_open():
    d = sched_driver([(("A",), True), (("B",), True)])
    d.stage_scope = lambda stage, kind="": (_ for _ in ()).throw(SR.Refusal("no controller"))
    for why, make in (("the windows cannot be read", lambda: d.s5_open_windows(excluding=["A"])),):
        try:
            make()
            raised = False
        except Exception:
            raised = True
        check(f"{why}: it raises (the caller treats that as open)", raised)
    check_eq("the close predicate reads that as NOT last", d.s5_last_fn(["A"])(), False)
    d = sched_driver([(("A",), True)])
    d.controller_state = lambda: {}
    try:
        d.s5_open_windows(excluding=[])
        raised = False
    except ValueError:
        raised = True
    check("no dispatch list in the controller record: it raises", raised)
    d = sched_driver([(("A",), True), (("B",), True)], {"p": {"id": "p", "stage": "S5", "status": "running", "scope": []}})
    try:
        d.s5_open_windows(excluding=["A"])
        raised = False
    except ValueError:
        raised = True
    check("a running dispatch with no cases: it raises, never 'no window'", raised)


def serial_reason_each_row():
    ok = [(("A",), False), (("B",), False)]
    check_eq("nothing in the way reads parallel", sched_driver(ok).s5_serial_reason(ok and sched_driver(ok).stage_scope("S5")["windows"]), "")
    cases = []
    d = sched_driver(ok)
    d.host = "codex"
    cases.append(("host", d, "not Claude"))
    d = sched_driver(ok)
    d.config = {"run": {"parallel": True}}
    cases.append(("run.parallel true", d, "run.parallel: false"))
    d = sched_driver(ok)
    d.__dict__["_s5_cap_one"] = True
    cases.append(("a limit earlier in this run", d, "limited"))
    d = sched_driver(ok, {"d1": {"id": "d1", "stage": "S5", "status": "blocked", "scope": ["A"]}})
    cases.append(("a stopped dispatch at entry", d, "running or stopped"))
    d = sched_driver(ok, repair_limit={"S5|A": {"token": "round", "cases": ["A"], "executed": False}})
    cases.append(("an owed round", d, "owed"))
    d = sched_driver([(("A",), True), (("B",), False)])
    (d.task_root / "work" / "test-code").mkdir(parents=True)
    (d.task_root / "work" / "test-code" / "critic-findings.md").write_text("old", encoding="utf-8")
    cases.append(("a story from before the per-dispatch files", d, "began before"))
    d = sched_driver(ok)
    d.stage_scope = lambda stage, kind="": (_ for _ in ()).throw(SR.Refusal("x"))
    cases.append(("unreadable windows", d, "cannot be read"))
    for label, driver_, word in cases:
        try:
            windows = driver_.stage_scope("S5")["windows"]
        except SR.Refusal:
            windows = []
        check_in(f"serial row: {label}", word, driver_.s5_serial_reason(windows))


def serial_reason_printed_once():
    d = sched_driver()
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        d.say_once("s5-windows", "note: S5 windows run one at a time: x")
        d.say_once("s5-windows", "note: S5 windows run one at a time: x")
    check_eq("one line through state['noted'], never twice", out.getvalue().count("run one at a time"), 1)


def seam_order_infra_refusal_person():
    def rec(n, exc):
        r = DC.ChainRecord(n, boundary=f"S5:w{n}", last_dispatch=f"D{n}")
        r.exception = exc
        return r

    def raised(records, cap=3):
        d = sched_driver()
        try:
            d.s5_seam(records, cap)
            return None, d
        except BaseException as exc:      # noqa: BLE001
            return exc, d
    person, refusal, infra = SR.Person("halt", "q"), SR.Refusal("r"), SR.InfraStop("auth", "login")
    got, d = raised([rec(1, person), rec(2, refusal), rec(3, infra)])
    check("an InfraStop wins over a Refusal and a Person", got is infra)
    got, d = raised([rec(1, person), rec(2, refusal)])
    check("a Refusal wins over a Person", got is refusal)
    check_eq("the main thread adopts that chain's record", (d.boundary, d.last_dispatch), ("S5:w2", "D2"))
    other = SR.Person("halt", "q2")
    got, _ = raised([rec(2, other), rec(1, person)])
    check("the lowest number among equals", got is person)
    got, _ = raised([rec(1, None), rec(2, None)])
    check("no chain failed: no seam", got is None)
    limit = SR.InfraStop("limit", "slow down")
    got, d = raised([rec(1, limit)])
    check("a model-service limit with more than one window allowed is not a stop; the run goes on at one", got is None and d.__dict__.get("_s5_cap_one"))
    got, _ = raised([rec(1, limit)], cap=1)
    check("... but at one window already it stops as today", got is limit)
    got, _ = raised([rec(1, SR.InfraStop("auth", "login"))])
    check("any other kind stops as today", isinstance(got, SR.InfraStop) and got.kind == "auth")


def chains_run(d, items, chain_fn, cap, launchable=lambda r: True):
    out = io.StringIO()
    error = None
    with contextlib.redirect_stdout(out):
        try:
            d.run_chains(items, launchable, chain_fn, cap)
        except BaseException as exc:      # noqa: BLE001
            error = exc
    return error, out.getvalue()


def n3_windows_overlap_and_cap():
    d = sched_driver()
    live = {"now": 0, "most": 0}
    both = threading.Barrier(2, timeout=10)

    def body(record, payload):
        live["now"] += 1
        live["most"] = max(live["most"], live["now"])
        with d.unbooked("D"):
            if payload == "wait":
                both.wait()
        live["now"] -= 1
    err, _ = chains_run(d, [(1, ["A"], "wait"), (2, ["B"], "wait")], body, 2)
    check("two windows' sessions were at work at once (the barrier needs both)", err is None and live["most"] == 2)
    live.update(now=0, most=0)
    err, _ = chains_run(sched_driver(), [(1, ["A"], ""), (2, ["B"], "")], body, 1)
    check_eq("cap 1 is the serial road: never two at once", live["most"], 1)


def launch_gate_waits_then_progresses():
    d = sched_driver()
    files = {("A",): {"f.py"}, ("B",): {"f.py", "g.py"}, ("C",): {"h.py"}}
    d.s5_window_files = lambda cases: set(files.get(tuple(cases), ()))
    order = []

    def body(record, payload):
        order.append(("start", record.n))
        with d.unbooked("D"):
            threading.Event().wait(0.15)
        order.append(("end", record.n))
    err, _ = chains_run(d, [(1, ["A"], ""), (2, ["B"], ""), (3, ["C"], "")], body, 3, launchable=d.s5_launchable)
    check("two windows sharing a file never run at once: B starts after A ended, never refused", err is None and order.index(("end", 1)) < order.index(("start", 2)))
    check("a window sharing nothing runs beside the first", order.index(("start", 3)) < order.index(("end", 1)))
    d = sched_driver()
    d.s5_window_files = lambda cases: {"same.py"}
    err, _ = chains_run(d, [(1, ["A"], ""), (2, ["B"], "")], lambda r, p: None, 2, launchable=lambda r: False)
    check("when the gate holds every window and nothing runs, the first still starts and then the next", err is None and all(r.done for r in d._chains.values()) and len(d._chains) == 2)
    # the session gate: a session waits while another window's RUNNING session holds a file of its window
    d = sched_driver()
    d.s5_window_files = lambda cases: {"f.py"}
    d._chain_kind = d.s5_chain_kind()
    first, second = DC.ChainRecord(1, cases=("A",)), DC.ChainRecord(2, cases=("B",))
    d._chains.update({1: first, 2: second})
    first.running = True
    started = threading.Event()

    def waiter():
        with d.session_running("D2"):
            started.set()
    _r, _b, t = as_chain_thread(d, 2, waiter, cases=("B",))
    d._chains[2] = _r
    started.wait(0.3)
    check("a session beside a running session that holds its file waits", not started.is_set())
    d._book.acquire()
    first.running = False
    d._cond.notify_all()
    d._book.release()
    t.join(5)
    check("... and goes on once that session ended", started.is_set())


def _wait_until(test, seconds=10.0, what="the awaited condition") -> bool:
    """Poll `test()` on the calling (chain) thread without holding `_book`; True when it held within `seconds`. A cap that expires
    says so loudly (stderr, naming the thread and what did not happen) and returns False."""
    end = threading.Event()
    for _ in range(int(seconds / 0.02)):
        if test():
            return True
        end.wait(0.02)
    print(f"TIMEOUT: thread {threading.current_thread().name} gave up after {seconds}s waiting for {what}", file=sys.__stderr__, flush=True)
    return False


def _gate_run(d, counting_chain=0):
    """Two chains whose windows share a file: chain 1's session is at work until chain 2 said it waits (`_gate_said`); then, unless
    `counting_chain` names chain 2 (which counts its own launch first), chain 1 starts the drain and ends. Returns (error, started)."""
    d.s5_window_files = lambda cases: {"f.py"}
    started = []

    def body(record, payload):
        if record.n == counting_chain:
            d.count_launch()
        with d.session_running(f"D{record.n}"):
            started.append(record.n)
            if record.n == 1:
                with d.unbooked("D1"):
                    _wait_until(lambda: bool(d.__dict__.get("_gate_said")), what="chain 2 to say it waits at the session gate")
                    if not counting_chain:
                        d._drain.set()
    kind = DC.ChainKind(holds=lambda cases: {"f.py"})
    out = io.StringIO()
    error = None
    with contextlib.redirect_stdout(out):
        try:
            # chain 2 is launched only once chain 1's session is RUNNING: thread start order is not guaranteed, and a chain 2 that
            # reaches the gate first finds nothing blocking and legitimately starts its session (no wait, no drain to test)
            d.run_chains([(1, ["A"], ""), (2, ["B"], "")], lambda r: r.n == 1 or (1 in d._chains and d._chains[1].running), body, 2, kind=kind)
        except BaseException as exc:      # noqa: BLE001
            error = exc
    return error, started


def gated_session_does_not_start_after_drain():
    """TR4-10 Q3: a chain that waited in `session_gate` does not start its session once the drain is on, and ends `Drained` with no exception."""
    d = sched_driver()
    error, started = _gate_run(d)
    check("the waiting chain's session never started after the drain; no error reached the seam", error is None and started == [1])
    check("... the chain ended without an exception and its window stays open for the next entry",
          d._chains[2].exception is None and d._chains[2].done)
    # EVERY launch attempt is gated, not only a dispatch's first: a chain re-tried after the drain is refused the same way
    d = sched_driver()
    d.s5_window_files = lambda cases: {"f.py"}
    d._chain_kind = d.s5_chain_kind()
    first = DC.ChainRecord(1, cases=("A",))
    d._chains[1] = first
    first.running = True
    d._drain.set()
    seen = []

    def two_attempts():
        for attempt in (1, 2):
            try:
                with d.session_running("D2"):
                    seen.append(("started", attempt))
            except DC.Drained:
                seen.append(("drained", attempt))
    record, box, t = as_chain_thread(d, 2, two_attempts, cases=("B",))
    d._chains[2] = record
    t.join(5)
    check_eq("each attempt of the same chain after the drain is refused by the gate", seen, [("drained", 1), ("drained", 2)])
    check("... and a Drained is no failure of the thread", "error" not in box)


def counting_chain_still_launches_after_its_own_drain():
    """TR4-10 Q3, fork F4 (a): the chain whose `count_launch` hit `--max-boundaries` still launches (the one that counted still runs)."""
    d = sched_driver()
    d.max_boundaries = 1
    error, started = _gate_run(d, counting_chain=2)
    check("the counting chain waited behind chain 1 and then launched; both sessions ran", error is None and sorted(started) == [1, 2])
    check_eq("the drain was started by chain 2", (d._drain.is_set(), d._drain_by), (True, 2))
    chains_run(d, [], lambda r, p: None, 1)
    check("a new run clears the mark with the flag", d._drain_by is None and not d._drain.is_set())


def ungated_chain_unchanged_by_drain_flag():
    """TR4-10 Q3: a chain that reaches the gate with nothing blocking passes as today, drain or not; N == 1 never enters the gate."""
    d = sched_driver()
    d._chain_kind = DC.ChainKind(holds=lambda cases: {"f.py"})
    d._chains[1] = DC.ChainRecord(1, cases=("A",))
    d._drain.set()
    ran = []

    def body():
        with d.session_running("D1"):
            ran.append(1)
    record, box, t = as_chain_thread(d, 1, body, cases=("A",))
    d._chains[1] = record
    t.join(5)
    check("an ungated chain launches although the drain is on", ran == [1] and "error" not in box)
    d = sched_driver()
    d._drain.set()
    got = []
    with d.session_running("D1"):
        got.append("serial")
    check("off a chain (N == 1, the serial road) the drain flag changes nothing", got == ["serial"])


def seam_one_exception_after_the_drain():
    d = sched_driver()
    book = []

    def body(record, payload):
        if payload == "person":
            raise SR.Person("halt", "the question")
        with d.unbooked("D"):
            threading.Event().wait(0.2)     # a session that is working while the other chain raises
        book.append(record.n)
        d.stop_if_drained()                  # its next dispatch: refused by the drain, no new dispatch
        book.append("registered")
    err, _ = chains_run(d, [(1, ["A"], "person"), (2, ["B"], "work")], body, 2)
    check("the person's question is raised once, on the main thread, after the running window finished", isinstance(err, SR.Person) and book[:1] == [2])
    check("a drained chain registers no new dispatch", "registered" not in book)
    check("the drained chain ended without an exception (no seam of its own)", d._chains[2].exception is None and d._chains[2].done)
    err, _ = chains_run(sched_driver(), [(1, ["A"], ""), (2, ["B"], "")], lambda r, p: None, 2)
    check("no chain failed: run_chains returns", err is None)


def no_thread_started_at_n1():
    def run(config, windows, **state):
        d = sched_driver(windows, **state)
        d.config = config
        calls = {"chains": 0, "roles": []}
        d.timed = lambda *a, **k: contextlib.nullcontext(type("L", (), {"dispatch": ""})())
        d.stand_check = d.build_check = lambda *a, **k: None
        d.run_role = lambda stage, role, **k: calls["roles"].append(role)
        d.s5_window = lambda *a, **k: None
        d.run_s5_windows = lambda *a, **k: calls.__setitem__("chains", calls["chains"] + 1)
        d.s5_serial_reason = lambda w: ""
        d.stage_scope = lambda stage, kind="": {"scope": ["A", "B"], "windows": [{"scope": list(c), "accepted_by": {}} for c, _a in windows]}
        d.stage_S5()
        return calls
    two = [(("A",), False), (("B",), False)]
    pinned = run({"dispatch": {"parallel_windows": 1}}, two)
    check("parallel_windows 1: today's body, no scheduler", pinned["chains"] == 0 and pinned["roles"] == ["qa-automator"])
    check_eq("the default (absent key) with two open windows enters the scheduler", run({}, two)["chains"], 1)
    check_eq("one open window: today's body", run({}, two[:1])["chains"], 0)
    owed = run({}, two, repair_limit={"S5|A": {"token": "round", "cases": ["A"], "executed": False, "dispatch": "c1"}})
    check("an owed round runs first through today's body (no scheduler)", owed["chains"] == 0)


def window_release_at_close():
    import window_files
    d = sched_driver()
    window_files.claim(d.task_root, "tests/a.spec.ts", "S5|A", "D1")
    window_files.claim(d.task_root, "tests/b.spec.ts", "S5|B", "D2")
    d.config = {"dispatch": {"parallel_windows": 1}}
    d.s5_release(["A"])
    check_eq("parallel_windows 1 releases nothing (nothing was claimed by design)", window_files.files_of(d.task_root, "S5|A"), ["tests/a.spec.ts"])
    d.config = {}
    d.s5_release(["A"])
    check_eq("a closed window frees its files", window_files.files_of(d.task_root, "S5|A"), [])
    check_eq("... and only its own", window_files.files_of(d.task_root, "S5|B"), ["tests/b.spec.ts"])
    d = sched_driver([(("A",), True), (("B",), False)])
    window_files.claim(d.task_root, "tests/a.spec.ts", "S5|A", "D1")
    window_files.claim(d.task_root, "tests/b.spec.ts", "S5|B", "D2")
    d.s5_release_closed()
    check("the entry sweep frees a closed window's claim and keeps an open one's",
          window_files.files_of(d.task_root, "S5|A") == [] and window_files.files_of(d.task_root, "S5|B") == ["tests/b.spec.ts"])


def finish_flag_names_open_windows():
    d = sched_driver([(("A",), True), (("B",), False), (("C",), False)])
    check_eq("others open: the flag names their cases", d.s5_open_flag(["A"]), ["--open-windows", "B,C"])
    d = sched_driver([(("A",), True)])
    check_eq("none open: no flag", d.s5_open_flag(["A"]), [])
    d.stage_scope = lambda stage, kind="": (_ for _ in ()).throw(SR.Refusal("x"))
    check_eq("unreadable: nothing is guessed", d.s5_open_flag(["A"]), [])


def notes_line_names_the_per_dispatch_notes():
    d = sched_driver()
    check_eq("no notes: no line", d.s5_notes_line(), "")
    (d.task_root / "work").mkdir(parents=True)
    (d.task_root / "work" / "s5-notes.md").write_text("x", encoding="utf-8")
    check_eq("the old file alone: as before", d.s5_notes_line(), "Read qa-factory/artifacts/T-1/work/s5-notes.md first.")
    (d.task_root / "work" / "s5-notes").mkdir()
    (d.task_root / "work" / "s5-notes" / "S5-qa-automator-1.md").write_text("x", encoding="utf-8")
    check_in("the per-dispatch folder is named too", "every file of qa-factory/artifacts/T-1/work/s5-notes/", d.s5_notes_line())


# --- TR3-6 fix round (t-2124): B1 interrupt, F1-F8, Q1 ----------------------------------------------------------------------------------
import json  # noqa: E402
import os  # noqa: E402
import subprocess  # noqa: E402


def interrupt_starts_no_new_process():
    """B1: Ctrl-C on the main thread kills the running session; the chain that gets the killed result back launches NOTHING more."""
    d = sched_driver()
    d.WAIT_POLL_S = 0.05
    d.project, d.claude_env = d.task_root, dict(os.environ)
    d.mark_in_flight = d.clear_in_flight = lambda *a, **k: None
    mark = d.task_root / "launches.txt"
    cmd = [sys.executable, "-c", f"import time,pathlib; pathlib.Path(r'{mark}').open('a').write('x'); time.sleep(8)"]

    def body(record, payload):
        d.launch(cmd, "", dispatch="D1")       # killed by the interrupt, and returned as a plain result
        d.launch(cmd, "", dispatch="D1")       # the fresh attempt / handoff resume / conductor road: must start nothing

    def launchable(record):
        first = d._chains.get(1)
        # the child is up and at work: its 'x' is WRITTEN (the file exists the moment the child opens it, before the letter lands; an
        # interrupt in that gap kills a child that never writes, which is a slow interpreter start, not the behaviour under test)
        try:
            written = mark.read_text(encoding="utf-8") == "x"
        except OSError:
            written = False
        if record.n == 2 and first is not None and first.proc is not None and written:
            raise KeyboardInterrupt()          # the person's Ctrl-C reaches the main thread while the session works
        return record.n == 1
    err, _ = chains_run(d, [(1, ["A"], ""), (2, ["B"], "")], body, 2, launchable=launchable)
    check("the interrupt leaves run_chains as a KeyboardInterrupt", isinstance(err, KeyboardInterrupt))
    check_eq("ONE process was ever started: no chain launched a new `claude` after the interrupt", mark.read_text(encoding="utf-8"), "x")
    check("the killed session is not the role's result: the chain ended by the interrupt, not by a return",
          isinstance(d._chains[1].exception, KeyboardInterrupt) and d._chains[1].done)
    # the one launcher refuses to start anything once the flag is set
    d2 = sched_driver()
    d2.project, d2.claude_env = d2.task_root, dict(os.environ)
    d2._interrupted.set()
    try:
        d2._launch([sys.executable, "-c", f"import pathlib; pathlib.Path(r'{mark}').open('a').write('y')"], "", dispatch="D2")
        raised = False
    except KeyboardInterrupt:
        raised = True
    check("`_launch` after the interrupt raises and starts no process", raised and mark.read_text(encoding="utf-8") == "x")


def interrupted_call_is_never_booked():
    """B1: `run_claude` never classifies, journals or stores a call the interrupt cut off, and never starts an attempt after it."""
    d = sched_driver()
    d.claude, d.model, d.infra_rules = "x", "m", []
    d.claude_cmd, d.host_prompt = (lambda *a, **k: ["x"]), (lambda *a, **k: "")
    rows, calls = [], []
    d.journal_run = rows.append

    def launch(cmd, prompt, dispatch="", resume=""):
        calls.append(1)
        d._interrupted.set()          # the interrupt came while the session worked; the killed process returns a plain failure
        return subprocess.CompletedProcess(cmd, 1, "", "killed")
    d.launch = launch
    try:
        d.run_claude("role", "p", role="qa-automator", dispatch="D1", stage="S5")
        raised = False
    except KeyboardInterrupt:
        raised = True
    check("a call the interrupt cut off raises, it does not return a result", raised and len(calls) == 1)
    check_eq("... and no end row was journalled for it (only the `launched` row)", [r.get("kind") for r in rows], ["launched"])
    check("... and no session was stored", d.state.get("sessions", {}) == {} and "D1" not in (d.state.get("interrupted") or {}))
    try:
        d.run_claude("role", "p", role="qa-automator", dispatch="D1", stage="S5")
    except KeyboardInterrupt:
        pass
    check_eq("an attempt after the flag starts no launch and writes no row", (len(calls), len(rows)), (1, 1))


def save_state_rides_out_a_reader():
    """F1: a reader holding driver-state.json never makes save_state raise, and the file is whole afterwards."""
    d = sched_driver()
    d.dry, d.state = False, {"a": 1}
    d.state_dir.mkdir(parents=True)
    path = d.state_dir / "driver-state.json"
    path.write_text("{}", encoding="utf-8")
    out = io.StringIO()
    with open(path, "r", encoding="utf-8"), contextlib.redirect_stdout(out):
        d.save_state()
    check_eq("the state is published although a reader holds the file", json.loads(path.read_text(encoding="utf-8")), {"a": 1})
    check_eq("no temp file is left behind", list(d.state_dir.glob("*.tmp")), [])


def critic_settle_counts_as_running():
    """F2: a critic's settling `start` marks the chain running for its length, so a sibling's launch gate waits for it."""
    d = sched_driver()
    seen = {}
    d.stages = lambda: {"S5": {}}
    d.timed = lambda *a, **k: contextlib.nullcontext(type("L", (), {"dispatch": ""})())

    def step(*args):
        seen["running"] = d._chains[1].running
        raise RuntimeError("stop here")
    d.step = step

    def body():
        record = DC._CHAIN.record
        d._chains[1] = record
        try:
            d.run_role("S5", "qa-code-critic", scope=["A"])
        except RuntimeError:
            seen["after"] = record.running
    _r, box, t = as_chain_thread(d, 1, body, cases=("A",))
    t.join(10)
    check_eq("the settle runs with the record marked running", seen.get("running"), True)
    check_eq("... and it is unmarked when the settle ended, on the exception road too", seen.get("after"), False)


def seam_names_what_it_does_not_choose():
    """F3: every unchosen exception is one line; a crash outranks a person's question."""
    def rec(n, exc):
        r = DC.ChainRecord(n, boundary=f"S5:w{n}", last_dispatch=f"D{n}")
        r.exception = exc
        return r
    d = sched_driver()
    crash, person = OSError("file race " + "x" * 400), SR.Person("halt", "q")
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        try:
            d.s5_seam([rec(1, person), rec(2, crash)], 3)
            got = None
        except BaseException as exc:      # noqa: BLE001
            got = exc
    check("a crash (OSError) outranks the person's question", got is crash)
    lines = [line for line in out.getvalue().splitlines() if line.startswith("S5: window 1 also ended")]
    check("the unchosen question is one line, with its number and type", len(lines) == 1 and "Person" in lines[0])
    d = sched_driver()
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        try:
            d.s5_seam([rec(1, crash), rec(2, person)], 3)
        except BaseException:      # noqa: BLE001
            pass
    shown = [line for line in out.getvalue().splitlines() if line.startswith("S5: window 2 also ended")]
    check("the line is cut at 200 characters of the message", len(shown) == 1 and len(shown[0]) < 300)


def open_windows_use_the_repair_predicates():
    """F4: the close predicate asks `repair_owed` / `repair_debt_pending`, not a copy."""
    d = sched_driver([(("A",), True)])
    check_eq("nothing owed: closed", d.s5_open_windows(()), [])
    d.repair_owed = lambda windows: ({"x": 1}, windows[0])
    check_eq("`repair_owed` says owed: open", d.s5_open_windows(()), [["A"]])
    d = sched_driver([(("A",), True)])
    d.repair_debt_pending = lambda windows: ({"x": 1}, windows[0])
    check_eq("`repair_debt_pending` says pending: open", d.s5_open_windows(()), [["A"]])


def main_thread_exception_joins_the_chains():
    """F5: any exception on the main thread drains and joins the chains before it goes on."""
    d = sched_driver()
    d.WAIT_POLL_S = 0.05
    done = []

    def body(record, payload):
        with d.unbooked("D"):
            threading.Event().wait(0.4)
        done.append(record.n)

    def launchable(record):
        first = d._chains.get(1)
        if record.n == 2 and first is not None:
            raise RuntimeError("the scheduler's own read failed")
        return record.n == 1
    err, _ = chains_run(d, [(1, ["A"], ""), (2, ["B"], "")], body, 2, launchable=launchable)
    check("the exception is raised", isinstance(err, RuntimeError))
    check_eq("the running chain was joined before it left (its session ended and booked)", done, [1])


def interrupt_between_popen_and_registration():
    """R1: a Ctrl-C that lands while the child is being marked (after the pre-Popen check, before the proc was registered for main's kill)
    is seen by the chain itself right after it registers: the child is killed and nothing is booked."""
    d = sched_driver()
    d.project, d.claude_env = d.task_root, dict(os.environ)
    mark = d.task_root / "r1.txt"
    d.mark_in_flight = lambda *a, **k: d._interrupted.set()      # main set the flag and found no proc to kill
    d.clear_in_flight = lambda *a, **k: None
    cmd = [sys.executable, "-c", f"import time,pathlib; pathlib.Path(r'{mark}').open('a').write('x'); time.sleep(1.5); pathlib.Path(r'{mark}').open('a').write('y')"]
    box = {}

    def body():
        try:
            d.launch(cmd, "", dispatch="D1")
            box["returned"] = True
        except KeyboardInterrupt:
            box["ki"] = True
    _r, _b, t = as_chain_thread(d, 1, body, cases=("A",))
    t.join(20)
    threading.Event().wait(2.5)          # long enough for a child that was NOT killed to write its second letter
    check("the chain raised KeyboardInterrupt, no result came back", box.get("ki") and not box.get("returned"))
    check("the child was killed: it never got to its second write", "y" not in (mark.read_text(encoding="utf-8") if mark.exists() else ""))


def interrupt_during_the_wait_for_chains():
    """R2: on a non-Ctrl-C exit main says it waits; a Ctrl-C during that wait sets the flag and kills the running session."""
    d = sched_driver()
    d.WAIT_POLL_S = 0.05
    armed = threading.Event()

    real_join = threading.Thread.join

    def ctrl_c_join(thread, timeout=None):
        """The person's Ctrl-C, raised once inside the main thread's own wait for a chain (`_thread.interrupt_main` does nothing under
        a CI shell that ignores SIGINT)."""
        if armed.is_set() and threading.current_thread() is threading.main_thread():
            armed.clear()
            raise KeyboardInterrupt()
        return real_join(thread, timeout)
    d.project, d.claude_env = d.task_root, dict(os.environ)
    d.mark_in_flight = d.clear_in_flight = lambda *a, **k: None
    mark = d.task_root / "r2.txt"
    cmd = [sys.executable, "-c", f"import time,pathlib; pathlib.Path(r'{mark}').open('a').write('x'); time.sleep(1.5); pathlib.Path(r'{mark}').open('a').write('y')"]

    def body(record, payload):
        d.launch(cmd, "", dispatch="D1")

    def launchable(record):
        first = d._chains.get(1)
        if record.n == 2 and first is not None and first.proc is not None and mark.exists():
            armed.set()       # the person's Ctrl-C, at main's next wait for the chain
            raise RuntimeError("the scheduler's own read failed")
        return record.n == 1
    threading.Thread.join = ctrl_c_join
    try:
        err, said = chains_run(d, [(1, ["A"], ""), (2, ["B"], "")], body, 2, launchable=launchable)
    finally:
        threading.Thread.join = real_join
    threading.Event().wait(2.5)
    check("a Ctrl-C during the wait leaves as a KeyboardInterrupt", isinstance(err, KeyboardInterrupt))
    check_in("the wait was said once, with the exception's type", "waiting for window 1", said)
    check("the flag was set and the running session killed", d._interrupted.is_set() and "y" not in mark.read_text(encoding="utf-8"))


def cases_of_a_dispatch_have_one_reader():
    """R3: `finish` and the release read the cases of an S5 dispatch through `s5_cases_of`."""
    d = sched_driver(dispatches={"D1": {"id": "D1", "stage": "S5", "status": "running", "scope": ["A", "B"]}})
    check_eq("off a chain: the controller's record of the dispatch", d.s5_cases_of("D1"), ["A", "B"])
    check_eq("an unknown dispatch: none", d.s5_cases_of("D9"), [])
    seen = {}
    _r, _b, t = as_chain_thread(d, 1, lambda: seen.setdefault("cases", d.s5_cases_of("D1")), cases=("C",))
    t.join(5)
    check_eq("on a chain: the chain's own cases", seen.get("cases"), ["C"])
    called = []
    real = d.s5_cases_of
    d.s5_cases_of = lambda dispatch: (called.append(dispatch), real(dispatch))[1]
    import window_files
    window_files.claim(d.task_root, "tests/a.spec.ts", "S5|A,B", "D1")
    d.config = {}
    d.s5_release_of_dispatch("D1")
    check_eq("the release reads through the helper", called, ["D1"])


def walk_timing_end_line_is_published_whole():
    """Q-new-2: `walk_after` rewrites `timing.jsonl` through the atomic publisher: one `after_end`, a reader holding the file changes nothing."""
    d = sched_driver()
    d.py = lambda *a, **k: (0, "")
    d.walk_case_records = d.walk_values = lambda *a, **k: None
    timing = d.task_root / "work" / "walks" / "W1" / "timing.jsonl"
    timing.parent.mkdir(parents=True)
    timing.write_text('{"item": 1}\n{"after_end": "old"}\n', encoding="utf-8")
    out = io.StringIO()
    with open(timing, "r", encoding="utf-8"), contextlib.redirect_stdout(out):
        d.walk_after([], "W1", {})
    lines = timing.read_text(encoding="utf-8").splitlines()
    check("the old end line is replaced by one new end line, the other lines kept",
          len(lines) == 2 and json.loads(lines[0]) == {"item": 1} and "after_end" in json.loads(lines[1]) and json.loads(lines[1])["after_end"] != "old")
    check_eq("no temp file is left", [p.name for p in timing.parent.glob("*.tmp")], [])
    check("no failure note: " + out.getvalue()[:300], "closing steps did not all run" not in out.getvalue())


def serial_reason_falls_away_after_the_settling_windows():
    """F6 (spec 3.6): a reason that is a state at entry holds for the windows it names only; the rest goes side by side in the same stage."""
    def run(host="claude", settle=True):
        dispatches = {"d1": {"id": "d1", "stage": "S5", "status": "running", "scope": ["A"]}}
        d = sched_driver([(("A",), False), (("B",), False), (("C",), False)], dispatches)
        d.host = host
        d.timed = lambda *a, **k: contextlib.nullcontext(type("L", (), {"dispatch": ""})())
        calls, accepted = [], set()

        def run_s5_windows(windows, todo, cap):
            calls.append(([w["scope"][0] for w in todo], cap))
            if len(calls) == 1:
                accepted.add("A")           # the first window ran to its close
                if settle:
                    dispatches.clear()      # and the asked dispatch settled
        d.run_s5_windows = run_s5_windows
        d.stage_scope = lambda stage, kind="": {"scope": ["A", "B", "C"], "windows": [
            {"scope": [c], "accepted_by": ({"qa-code-critic": "x"} if c in accepted else {})} for c in "ABC"]}
        with contextlib.redirect_stdout(io.StringIO()):
            d.stage_S5()
        return calls
    check_eq("the window with the running dispatch goes first, alone; then the rest goes side by side (cap 3 over 2 windows -> 2)",
             run(), [(["A"], 1), (["B", "C"], 2)])
    check_eq("a dispatch that never settles cannot loop the stage: the rest then runs one at a time, once",
             run(settle=False), [(["A"], 1), (["B", "C"], 1)])
    check_eq("a reason that is not about the entry state keeps the whole run serial",
             run(host="codex"), [(["A", "B", "C"], 1)])


def release_failure_note_can_print():
    """F7: `window_files.release` never raises; a claim left on disk is still named in a note."""
    import window_files
    d = sched_driver()
    d.config = {}
    window_files.claim(d.task_root, "tests/a.spec.ts", "S5|A", "D1")
    real = window_files.release
    window_files.release = lambda *a, **k: 0       # a hook is reading the claim: nothing could be removed, nothing raised
    out = io.StringIO()
    try:
        with contextlib.redirect_stdout(out):
            d.s5_release(["A"])
    finally:
        window_files.release = real
    check_in("a claim left behind is said", "could not be released", out.getvalue())
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        d.s5_release(["A"])
    check_eq("a release that worked is silent", out.getvalue(), "")


def closing_finish_releases_the_window():
    """Q1: the finish that closes S5 (the gate-answer road, `s5_close_debt`) frees the window's files, though `s5_window` never returns."""
    import window_files
    d = sched_driver(dispatches={"D1": {"id": "D1", "stage": "S5", "status": "running", "scope": ["A"]}})
    d.config = {}
    window_files.claim(d.task_root, "tests/a.spec.ts", "S5|A", "D1")
    window_files.claim(d.task_root, "tests/b.spec.ts", "S5|B", "D2")
    d.timed = lambda *a, **k: contextlib.nullcontext(type("L", (), {"dispatch": ""})())
    d.py = lambda *a, **k: (0, "")
    d.close_window_series = d.revoke_passes_of_dead = d.forget_resumes = lambda *a, **k: None
    with contextlib.redirect_stdout(io.StringIO()):
        d.finish("D1", "digest", complete=True, role="qa-code-critic", stage="S5")
    check_eq("the closing window's files are free", window_files.files_of(d.task_root, "S5|A"), [])
    check_eq("... and another window's are not touched", window_files.files_of(d.task_root, "S5|B"), ["tests/b.spec.ts"])


def scheduler_module_knows_no_stage():
    """t-2147 A.2 / A.3: `driver_chains.py` imports only the standard library, holds no string that IS a stage word and no `s5_`/`s6_` name
    (its moved docstrings may say S5: a docstring is not code), and the names `story_run` imports are the SAME objects, not copies; one
    `run_chains`."""
    import ast

    def stage_problems(source: str) -> list:
        tree = ast.parse(source)
        docstrings = {id(n.body[0].value) for n in ast.walk(tree)
                      if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.body
                      and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant) and isinstance(n.body[0].value.value, str)}
        found = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                found += [f"imports {a.name}" for a in node.names if a.name.split(".")[0] not in sys.stdlib_module_names]
            elif isinstance(node, ast.ImportFrom):
                if node.level or (node.module or "").split(".")[0] not in sys.stdlib_module_names:
                    found.append(f"imports from {node.module}")
            elif isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings and node.value in ("S5", "S6"):
                found.append(f"holds the stage word {node.value!r}")
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name.startswith(("s5_", "s6_")):
                found.append(f"defines {node.name}")
            elif isinstance(node, ast.Name) and node.id.startswith(("s5_", "s6_")):
                found.append(f"names {node.id}")
            elif isinstance(node, ast.Attribute) and node.attr.startswith(("s5_", "s6_")):
                found.append(f"reads .{node.attr}")
        return found
    check_eq("the real module knows no stage and imports only the standard library",
             stage_problems(Path(DC.__file__).read_text(encoding="utf-8")), [])
    bad = stage_problems('"""S5 is fine here."""\nimport story_run\nfrom controller import X\nLABEL = "S5"\n\n\ndef s6_x():\n    return self.s5_window_files\n')
    for needle in ("imports story_run", "imports from controller", "holds the stage word 'S5'", "defines s6_x", "reads .s5_window_files"):
        check_in(f"a bad fixture is reported by name: {needle}", needle, "\n".join(bad))
    check_eq("a docstring that says S5 is not reported", stage_problems('"""S5."""\n\n\ndef f():\n    """S6."""\n'), [])
    for name in ("_CHAIN", "ChainKind", "DriverChains", "ThreadSlot"):   # the names story_run reads itself (t-2164 CI fix)
        check(f"story_run.{name} is the object of driver_chains, not a copy", getattr(SR, name) is getattr(DC, name))
    # after the cut every mixin member is outside `Driver.__dict__`, so the old `not in Driver.__dict__` is vacuous: ask the MRO instead.
    # (1) the attribute `Driver.run_chains` resolves to the very function of DriverChains; (2) its defining module is driver_chains;
    # (3) of every class on Driver's MRO, exactly DriverChains holds a `run_chains` in its own namespace (a definition in Driver or in
    # any other part of the driver set fails (1)-(3))
    check("Driver inherits run_chains from DriverChains and does not redefine it", SR.Driver.run_chains is DC.DriverChains.run_chains
          and SR.Driver.run_chains.__module__ == DC.__name__
          and [klass.__name__ for klass in SR.Driver.__mro__ if "run_chains" in vars(klass)] == ["DriverChains"],
          str([(klass.__name__, klass.__module__) for klass in SR.Driver.__mro__ if "run_chains" in vars(klass)]))
    check_eq("the S5 kind keeps its words and the [W<n>] tag", (SR.Driver.__new__(SR.Driver).s5_chain_kind().label, DC.ChainKind().tag,
                                                              SR.Driver.__new__(SR.Driver).s5_chain_kind().noun), ("S5", "W", "window"))


def chain_launchable_gate():
    """`chain_launchable` (t-2147 A): False only while a LIVE chain (not done) of the same run holds a resource of this one."""
    d = sched_driver()
    d._chain_kind = DC.ChainKind(holds=lambda cases: set(cases))
    mine, other = DC.ChainRecord(1, cases=("f.py",)), DC.ChainRecord(2, cases=("f.py", "g.py"))
    d._chains.update({1: mine, 2: other})
    check("a chain whose resource a live chain holds is not launchable", d.chain_launchable(mine) is False)
    other.done = True
    check("... and is launchable once that chain is done", d.chain_launchable(mine) is True)
    other.done = False
    other.cases = ("g.py",)
    check("a chain that shares nothing with a live chain is launchable", d.chain_launchable(mine) is True)
    d._chain_kind = DC.ChainKind()
    other.cases = ("f.py",)
    check("a kind with no `holds` never gates", d.chain_launchable(mine) is True)


def window_files_take_the_oracle_file():
    """t-2180 B: a window's gate files include the oracle file of a recorded probe of its rows (two windows sharing only that file meet)."""
    import json
    import proof_level as PL

    def rig(rows, records):
        d = sched_driver()
        (d.task_root / "work").mkdir(parents=True)
        (d.task_root / "work" / "automation-manifest.json").write_text(json.dumps({"tests": rows}), encoding="utf-8")
        for iid, rec in records.items():
            p = PL.probe_record_path(d.task_root, iid)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(rec if isinstance(rec, str) else json.dumps(rec), encoding="utf-8")
        return d

    def mrow(iid, case, file):
        return {"instance_id": iid, "case": case, "covers": [case], "file": file, "case_version_links": [{"case_id": case, "version": "v"}]}

    def rec(node, function="add", file="src\\calc.py"):
        return {"test_node": node, "mutation": "invert", "mutation_detail": {"oracle_function": function, "file": file}}
    rows = [mrow("a", "TC-1", "tests/a.py"), mrow("b", "TC-2", "tests/b.py")]
    d = rig(rows, {"a": rec("tests/a.py::t"), "b": rec("tests/b.py::t")})
    fa, fb = d.s5_window_files(["TC-1"]), d.s5_window_files(["TC-2"])
    check_eq("window A holds its test file and the oracle file", fa, {"tests/a.py", "src/calc.py"})
    check("two windows sharing only the oracle file meet (not launched together)", fa & fb == {"src/calc.py"})
    d = rig(rows, {"a": "{broken", "b": rec("tests/b.py::t", function="")})
    check_eq("an unreadable record keeps the manifest file (today's set)", d.s5_window_files(["TC-1"]), {"tests/a.py"})
    check_eq("an empty oracle_function: the test file, no oracle file", d.s5_window_files(["TC-2"]), {"tests/b.py"})
    d = rig(rows, {})
    check_eq("an absent record: today's set", d.s5_window_files(["TC-1"]), {"tests/a.py"})
    d = rig(rows, {"a": rec("tests/a.py::C::t")})
    check_eq("several :: -> the first part", d.s5_window_files(["TC-1"]), {"tests/a.py", "src/calc.py"})
    d = rig([{"instance_id": "n", "case": "TC-3", "covers": ["TC-3"], "case_version_links": [{"case_id": "TC-3", "version": "v"}]}],
            {"n": rec("tests/n.py::t")})
    check_eq("a row with no test file but an oracle record", d.s5_window_files(["TC-3"]), {"tests/n.py", "src/calc.py"})


def main():
    window_files_take_the_oracle_file()
    scheduler_module_knows_no_stage()
    interrupt_starts_no_new_process()
    interrupted_call_is_never_booked()
    save_state_rides_out_a_reader()
    critic_settle_counts_as_running()
    seam_names_what_it_does_not_choose()
    open_windows_use_the_repair_predicates()
    main_thread_exception_joins_the_chains()
    interrupt_between_popen_and_registration()
    interrupt_during_the_wait_for_chains()
    cases_of_a_dispatch_have_one_reader()
    walk_timing_end_line_is_published_whole()
    serial_reason_falls_away_after_the_settling_windows()
    release_failure_note_can_print()
    closing_finish_releases_the_window()
    unbooked_releases_once_and_retakes_on_exception()
    conductor_launch_holds_book()
    settling_one_at_a_time()
    open_windows_each_reason()
    open_windows_unreadable_is_open()
    serial_reason_each_row()
    chain_launchable_gate()
    serial_reason_printed_once()
    seam_order_infra_refusal_person()
    n3_windows_overlap_and_cap()
    launch_gate_waits_then_progresses()
    gated_session_does_not_start_after_drain()
    counting_chain_still_launches_after_its_own_drain()
    ungated_chain_unchanged_by_drain_flag()
    seam_one_exception_after_the_drain()
    no_thread_started_at_n1()
    window_release_at_close()
    finish_flag_names_open_windows()
    notes_line_names_the_per_dispatch_notes()
    thread_local_values_isolated()
    main_keeps_its_own_values()
    as_chain_restores()
    adopt_chain_stays()
    closes_reads_given_dispatch()
    refusal_retry_reads_its_own_chain()
    chain_stream_prefixes_only_chain_lines()
    serial_values_unchanged()
    finish("test_driver_chain")


if __name__ == "__main__":
    main()
