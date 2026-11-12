#!/usr/bin/env python3
"""driver_chains.py - the driver's generic chain scheduler (t-2147 part A, TR3-9a): moved out of `story_run.py`, no behaviour change.

One driver process runs several CHAINS (a window's automator -> critic -> rounds today) each in its own thread. `Driver.run_chains`
starts them under a cap, `_book` is held by a chain EXCEPT while its role's `claude` runs (`unbooked`), so every other code step runs
one at a time and only the role sessions overlap. The module knows no stage: what one chain is called, which resources its session
holds and how the failures of a run are ranked arrive through `ChainKind` and the `seam` argument of `run_chains` (the stage's own
module supplies them). It imports only the standard library (layer rank 0, beside driver_core: `Refusal` and the launcher read
`_CHAIN`, so the module can never sit above them) and never `story_run`; `DriverChains` is the base class of `story_run.Driver`.
"""
import contextlib
import sys
import threading
from dataclasses import dataclass


_CHAIN = threading.local()      # `record`: the ChainRecord the CURRENT thread runs (absent / None on the main thread and on the serial road)


def once_on(owner, name: str, make):
    """The value kept on `owner` under `name`, made by `make()` the first time (the dict's `setdefault` is atomic, so two threads that
    race get ONE value). The one place that touches the instance dict by a name chosen at the call: a driver built without
    `__init__` (a test's rig) still gets its lock, its flag or its slots. The name is a literal at every call: the layer map reads
    `once_on(self, "<name>", ...)` as a touch of the attribute `<name>` (test_driver_layers L3) and refuses any other form."""
    value = owner.__dict__.get(name)
    if value is None:
        value = owner.__dict__.setdefault(name, make())
    return value


class ThreadSlot:
    """A name the driver keeps once per thread and per driver (TR3-17 B4): `Driver.boundary` and `Driver.last_dispatch` read and
    write the slot of the current thread, so the many sites that use them as plain attributes stay unchanged. With `default` a
    thread that never set it reads the default; without one it raises AttributeError naming `hint` (a bug to show, no default)."""
    _NONE = object()

    def __init__(self, name: str, default=_NONE, hint: str = ""):
        self.name, self.default, self.hint = name, default, hint

    def __get__(self, owner, cls=None):
        if owner is None:
            return self
        slots = owner._slots()
        if self.default is not self._NONE:
            return getattr(slots, self.name, self.default)
        try:
            return getattr(slots, self.name)
        except AttributeError:
            raise AttributeError(self.hint or f"{self.name} was read on a thread that never set it") from None

    def __set__(self, owner, value) -> None:
        setattr(owner._slots(), self.name, value)


@dataclass
class ChainRecord:
    """One window's chain (t-1937 TR3-17): its number `n` (the `[W<n>] ` of its console lines) and the two values the driver keeps
    per chain, which are single slots on the serial road: `boundary` and `last_dispatch`. Plain data, no thread object, never saved
    into the driver's state. `Driver.as_chain` writes the thread's values back here when the chain's block ends, so a retry on
    another thread (`Driver.adopt_chain`) reads where the chain stood."""
    n: int
    boundary: str = "start"
    last_dispatch: str = ""
    # TR3-6 (the scheduler's part of the record; still plain data): `cases` the window's cases, `exception` what ended the chain (None
    # for a window that finished or was drained), `proc` the `claude` process of the running session (the interrupt kills it),
    # `running` a session of this chain is at work now (the launch gate reads it), `done` the chain's thread is over.
    cases: tuple = ()
    exception: object = None
    proc: object = None
    running: bool = False
    done: bool = False
    # t-2147 A: the console prefix letter of this chain's lines (`[<tag><n>] `), set by `run_chains` from `ChainKind.tag`
    tag: str = "W"


@dataclass(frozen=True)
class ChainKind:
    """What one run of `run_chains` calls its chains (t-2147 A item 2): `label` the prefix of the scheduler's own console lines, `noun`
    what one chain is called, `held` what a running session holds (in the gate's line), `holds` a callable `cases -> set` of the
    resources a chain's session holds, given the chain's case tuple (None = nothing knowable = no gate), `tag` the console prefix
    letter of a chain's lines. The defaults are the scheduler's own words; the rank of a failure is the seam's business, not the kind's."""
    label: str = "chains"
    noun: str = "window"
    held: str = "a file"
    holds: object = None
    tag: str = "W"


class Drained(Exception):
    """A chain reached `run_role` or `rework` after another chain raised: the scheduler is draining, so no new dispatch is registered
    (TR3-6, spec t-1937 3.2). Not an error: a chain that ends by it has `exception = None` and an open window, and no seam runs."""


class ChainStream:
    """A stdout wrapper (TR3-17; installed by TR3-6, not here): a line written by a chain thread starts with `[W<n>] `, a line written
    by any other thread is passed through as it is. Thread-safe: a chain thread's partial line waits in its own buffer and goes out
    whole under one lock at its newline, so two chains never split each other's line; `flush` sends the partial line too (FR-43:
    a progress line without a newline is not held back), and the rest of that line carries no second prefix."""

    def __init__(self, stream):
        self._stream = stream
        self._lock = threading.Lock()
        self._parts = threading.local()          # per thread: `buf` (the partial line), `mid` (a partial line already went out)

    def __getattr__(self, name):
        return getattr(self._stream, name)

    @staticmethod
    def _prefix() -> str:
        record = getattr(_CHAIN, "record", None)
        return f"[{record.tag}{record.n}] " if record is not None else ""

    def write(self, text) -> int:
        text = str(text)
        prefix = self._prefix()
        if not prefix:
            with self._lock:
                self._stream.write(text)
            return len(text)
        parts = self._parts
        buf = getattr(parts, "buf", "") + text
        out = ""
        while "\n" in buf:
            line, buf = buf.split("\n", 1)
            out += ("" if getattr(parts, "mid", False) else prefix) + line + "\n"
            parts.mid = False
        parts.buf = buf
        if out:
            with self._lock:
                self._stream.write(out)
        return len(text)

    def flush(self) -> None:
        prefix = self._prefix()
        buf = getattr(self._parts, "buf", "") if prefix else ""
        with self._lock:
            if buf:
                self._stream.write(("" if getattr(self._parts, "mid", False) else prefix) + buf)
                self._parts.buf, self._parts.mid = "", True
            self._stream.flush()


class DriverChains:
    """The scheduler's members, the base class of `story_run.Driver` (t-2147 A). Bodies are the ones `story_run.Driver` held before the
    move; the console words of a run come from `ChainKind` (`run_chains(..., kind=)`), and the failure that wins the seam from the
    `seam` argument (`chain_seam` is the generic one)."""

    # TR3-17 (B4 parts 1-2): `boundary` and `last_dispatch` were single slots; they are now per thread AND per driver, under the same
    # names, so the 26 + 57 sites read and write them unchanged. The main thread's value is the one `__init__` and the serial road set.
    # A thread that never set one: `boundary` raises AttributeError (a bug to show, no default); `last_dispatch` reads "" (its only
    # silent default - and `getattr(self, "last_dispatch", "")` keeps answering "").
    def _slots(self):
        return once_on(self, "_thread_slots", threading.local)

    @contextlib.contextmanager
    def as_chain(self, record: "ChainRecord"):
        """Run the block as the chain `record`: this thread's two values start from the record's, its console lines belong to the chain
        (`ChainStream`), a `Refusal` raised inside carries the record. At the end the values go back into the record and this thread's
        earlier values and chain are restored (a chain that ended leaves nothing behind on a reused thread)."""
        slots = self._slots()
        missing = object()
        before = (getattr(slots, "boundary", missing), getattr(slots, "last_dispatch", missing), getattr(_CHAIN, "record", None))
        slots.boundary, slots.last_dispatch, _CHAIN.record = record.boundary, record.last_dispatch, record
        try:
            yield record
        finally:
            record.boundary = getattr(slots, "boundary", record.boundary)
            record.last_dispatch = getattr(slots, "last_dispatch", record.last_dispatch)
            for name, old in (("boundary", before[0]), ("last_dispatch", before[1])):
                if old is missing:
                    slots.__dict__.pop(name, None)
                else:
                    setattr(slots, name, old)
            _CHAIN.record = before[2]

    def adopt_chain(self, record) -> None:
        """Make THIS thread read the chain `record`'s two values and keep them (the seam's retry on the main thread, after a chain's
        `Refusal`). No record (a refusal of the serial road): nothing changes. The thread's own chain is not touched."""
        if record is None:
            return
        slots = self._slots()
        slots.boundary, slots.last_dispatch = record.boundary, record.last_dispatch

    # --- the window scheduler (TR3-6, spec t-1937 3.2 and 3.6): parallel sessions, serial bookkeeping ----------------------------
    # One driver process. Each window is a CHAIN (automator -> critic -> rounds) in its own thread. `_book` is held by a chain EXCEPT while
    # its role's `claude` runs (`unbooked`), so every other code step runs one at a time and only the role sessions overlap. Nothing
    # below is entered with `dispatch.parallel_windows: 1`, or with one S5 window, or with a round owed: that is today's body, verbatim.
    GATE_POLL_S = 5.0           # a chain waiting for a file holder looks again at least this often
    WAIT_POLL_S = 1.0           # the scheduler's own wait for a chain to end

    @property
    def _book(self):
        """The driver lock: a plain `threading.Lock` (one acquire per chain, no nesting, so an accidental nested acquire shows at once)."""
        return once_on(self, "_book_lock", threading.Lock)

    @property
    def _settling(self):
        """The second lock: one critic `start` (its probe-debt settle, up to 90 s) at a time, never held while waiting for `_book`."""
        return once_on(self, "_settle_lock", threading.Lock)

    @property
    def _cond(self):
        return once_on(self, "_book_cond", lambda: threading.Condition(self._book))

    @property
    def _drain(self):
        return once_on(self, "_drain_flag", threading.Event)

    @property
    def _interrupted(self):
        """Set by the main thread on Ctrl-C BEFORE it kills the sessions: no `claude` process starts after it, and a session killed
        by it is never read as the role's result (`_launch` checks it before the start and after the wait)."""
        return once_on(self, "_interrupt_flag", threading.Event)

    def stop_if_interrupted(self) -> None:
        """The person stopped the run: raise what Ctrl-C raises. Called at the one launcher and at the top of each attempt of `run_claude`."""
        if self._interrupted.is_set():
            raise KeyboardInterrupt()

    @property
    def _chains(self) -> dict:
        return once_on(self, "_chain_registry", dict)

    @staticmethod
    def on_chain() -> bool:
        """True on a chain thread (the parallel road); False on the main thread and on the serial road."""
        return getattr(_CHAIN, "record", None) is not None

    @contextlib.contextmanager
    def unbooked(self, dispatch: str = "", *, settling: bool = False):
        """Give up `_book` for the block and take it back at the end, exactly once, on every road (`BaseException` included).
        Releases ONLY on a chain thread AND with a non-empty `dispatch` (a role's own call) or `settling` (a critic's `start`): the
        conductor and the delivery call keep the lock. `settling` also takes `_settling` for the block. ORDER: release `_book`, take
        `_settling`, run, release `_settling`, take `_book`; `_settling` is never held while waiting for `_book`, so no deadlock."""
        if not self.on_chain() or not (dispatch or settling) or not self._book.locked():
            yield
            return
        self._book.release()
        held = False
        try:
            if settling:
                self._settling.acquire()
                held = True
            yield
        finally:
            try:
                if held:
                    self._settling.release()
            finally:
                self._book.acquire()

    def stop_if_drained(self) -> None:
        """A chain that reaches the place where a dispatch would be registered while the scheduler drains stops there (`Drained`)."""
        if self.on_chain() and self._drain.is_set():
            raise Drained()

    def count_launch(self) -> None:
        """One more dispatch registered by a chain; on reaching `--max-boundaries` the drain starts (the one that counted still runs)."""
        if not self.on_chain():
            return
        self._launched = getattr(self, "_launched", 0) + 1
        if self._launched >= getattr(self, "max_boundaries", 10 ** 9):
            if not self._drain.is_set():
                self._drain_by = _CHAIN.record.n       # TR4-10: the chain that started the drain still launches (its gate does not drain it)
            self._drain.set()

    def chain_overlap_running(self, record) -> list:
        """The numbers of the OTHER chains whose session is running now and whose chain holds a resource of `record`'s chain (what
        `ChainKind.holds` names for the run's kind). Empty when the chain names none or the run has no `holds` (no overlap is
        knowable, and the guard judges each write)."""
        holds = getattr(getattr(self, "_chain_kind", None), "holds", None)
        if holds is None:
            return []
        running = [r for r in self._chains.values() if r is not record and r.running and not r.done]
        if not running:
            return []
        mine = holds(record.cases)
        if not mine:
            return []
        return sorted(r.n for r in running if mine & holds(r.cases))

    def chain_launchable(self, record) -> bool:
        """The gate at a chain's start (the generic twin of a stage's own): no LIVE chain (running or waiting, not done) holds a
        resource of this one. No `holds` in the run's kind, or none named: True."""
        holds = getattr(getattr(self, "_chain_kind", None), "holds", None)
        if holds is None:
            return True
        mine = holds(record.cases)
        if not mine:
            return True
        return not any(mine & holds(r.cases) for r in self._chains.values() if r is not record and not r.done)

    def session_gate(self, record) -> None:
        """LAUNCH GATE: a session of this chain's window does not start while a RUNNING session of another window holds a file of it
        (a critic's probe never mutates a file a sibling's session is writing, and the guard does not see probes). Overlap blocks
        concurrency, never progress: only RUNNING sessions are waited for, and a waiting chain has none, so no two chains wait for each
        other; when nothing else runs the session starts.

        TR4-10 (Q3): a chain that had to WAIT here does not start its session once the drain is on (`Drained`, no exception on the
        record), checked before each wait and once more when it wakes: the person's question is not held behind a whole extra session.
        The chain whose own `count_launch` started the drain (`_drain_by`, `--max-boundaries`) is exempt - the one that counted still
        runs. A chain that reaches the gate with nothing blocking passes as today. The test is made at EVERY launch attempt (a retry,
        a resume), never only a dispatch's first: a chain re-tried after the drain is refused the same way.

        NEW STATE, two sub-states (state-exits.md, the two rows after row 23). A chain stopped here leaves a dispatch REGISTERED
        (`running`) that has no live process (a `launched` row at most).
        (a) FIRST attempt (the session is not in `state["sessions"]`): the next entry's `next` answers `wait_existing_job`, which
        `dispatch_action` hands to `_act_wait_existing_job`; its branch "registered but never launched by this driver" (`story_run.py`,
        the `dispatch not in self.state["sessions"]` branch) relaunches the role BY CODE, no person and no paid call. This holds for
        liveness `unknown` too (under 180 s, or no transcripts); `release` stays the person's door, not the driver's road.
        (b) a RETRY or a RESUME (the gate runs at every attempt) of a dispatch whose session IS stored: the never-launched branch does
        not apply. `_act_wait_existing_job` goes: a saved result -> `_finish_saved_result`; an `interrupted` mark -> the dispatch
        continues; otherwise `_liveness_refusal` raises a Refusal. A `dead_dispatch` verdict (abandoned / never_started / returned) is
        the `KNOWN_REFUSALS` row -> `recover` (code); liveness `unknown` goes to the funnel and the conductor, which is a PAID call."""
        kind = getattr(self, "_chain_kind", None) or ChainKind()

        def drained() -> bool:
            return self._drain.is_set() and getattr(self, "_drain_by", None) != record.n

        waited = False
        while True:
            blocking = self.chain_overlap_running(record)
            if waited and drained():
                raise Drained()
            if not blocking:
                return
            waited = True
            if drained():
                raise Drained()
            once = once_on(self, "_gate_said", set)
            if (record.n, tuple(blocking)) not in once:
                once.add((record.n, tuple(blocking)))
                print(f"{kind.label}: the session of {kind.noun} {record.n} waits for {kind.noun} {', '.join(str(n) for n in blocking)}, which is working on {kind.held} of it",
                      flush=True)
            self._cond.wait(timeout=self.GATE_POLL_S)

    @contextlib.contextmanager
    def session_running(self, dispatch: str):
        """Around one role's launch on a chain thread: the gate, then `running` while the session works (the gate of the other chains
        reads it), and a wake-up of the waiting chains at the end. No-op off a chain or for a call with no dispatch."""
        record = getattr(_CHAIN, "record", None)
        if record is None or not dispatch or not self._book.locked():
            yield
            return
        self.session_gate(record)
        record.running = True
        try:
            yield
        finally:
            record.running = False
            self._cond.notify_all()

    def run_chains(self, items: list, launchable, chain_fn, cap: int, *, kind=None, seam=None) -> None:
        """The scheduler, which TR3-9 reuses (spec 3.7; not S5-specific by signature). `items`: `(n, cases, payload)` in launch order;
        `launchable(record)`: may this chain start now (the launch gate, read under `_book`); `chain_fn(record, payload)`: the chain's
        body, run on its own thread inside `as_chain` holding `_book`; `cap`: how many chains at once. `kind` (a `ChainKind`, default the
        scheduler's own words) names what a chain is called and what its session holds; `seam(records, cap)` replaces the generic
        `chain_seam` at the end of the run.

        A skipped item waits and later ones pass it; with no chain running the first item starts whatever the gate says (overlap blocks
        concurrency, never progress). Any exception in a chain starts the DRAIN: nothing new launches, running sessions finish and book,
        and a chain that reaches `run_role` or `rework` stops by `Drained`. After all chains joined, on THIS thread, ONE exception is
        chosen - an `InfraStop`, else another `Stop`, else a `Refusal`, else a `Person`, then the lowest number - the main thread adopts
        that chain's record and re-raises it to `guarded`. The others are not handled in this turn: they re-arise on re-entry, because
        their dispatch is still running with a saved result. Ctrl-C reaches this thread only: it drains, kills every running session and
        joins with a cap."""
        cap = max(1, int(cap))
        kind = kind or ChainKind()
        self._chain_kind = kind
        try:
            self._drain.clear()
            self._drain_by = None
            self._interrupted.clear()
            self._launched = 0
            registry = self._chains
            registry.clear()
            pending = [(ChainRecord(n=n, cases=tuple(cases), tag=kind.tag), payload) for n, cases, payload in items]
            live: list = []
            shown = sys.stdout
            sys.stdout = ChainStream(shown)
            try:
                with self._cond:
                    while True:
                        for entry in [e for e in live if e[0].done]:
                            entry[1].join()
                            live.remove(entry)
                        while pending and len(live) < cap and not self._drain.is_set():
                            pick = next((e for e in pending if launchable(e[0])), None)
                            if pick is None and not live:
                                pick = pending[0]
                            if pick is None:
                                break
                            pending.remove(pick)
                            thread = threading.Thread(target=self._chain_thread, args=(pick[0], pick[1], chain_fn), daemon=True)
                            registry[pick[0].n] = pick[0]
                            live.append((pick[0], thread))
                            thread.start()
                        if not live:
                            break
                        self._cond.wait(timeout=self.WAIT_POLL_S)
            except BaseException as exc:       # noqa: BLE001 - F5: ANY exit of the main thread leaves no chain running beside it
                self._drain.set()
                interrupt = isinstance(exc, KeyboardInterrupt)
                if interrupt:
                    self._interrupt_chains(live)
                # the lock is free here (the `with` ended): the chains finish their running sessions and book (a Ctrl-C waits at most 10 s,
                # its sessions are dead), then the exception goes on. R2: any other exit waits in short joins, says so once, and a Ctrl-C
                # during that wait is the same interrupt (flag, kill, capped join).
                try:
                    if interrupt:
                        for _record, thread in live:
                            thread.join(timeout=10)
                    else:
                        working = [r.n for r, t in live if t.is_alive()]
                        if working:
                            print(f"{kind.label}: waiting for {kind.noun} {', '.join(str(n) for n in working)} to finish its running session before "
                                  f"{type(exc).__name__} goes on", flush=True)
                        for _record, thread in live:
                            while thread.is_alive():
                                thread.join(timeout=1)
                except KeyboardInterrupt:
                    self._interrupt_chains(live)
                    for _record, thread in live:
                        thread.join(timeout=10)
                    raise
                raise
            finally:
                sys.stdout = shown
            (seam or self.chain_seam)(sorted(registry.values(), key=lambda r: r.n), cap)
        finally:
            self._chain_kind = None

    def _interrupt_chains(self, live: list) -> None:
        """The person stopped the run: the flag FIRST (no launcher starts a process after it, a killed session is never booked), then
        every registered session is killed."""
        self._interrupted.set()
        for record, _thread in live:
            try:
                if record.proc is not None:
                    record.proc.kill()
            except Exception:       # noqa: BLE001
                pass

    def _chain_thread(self, record, payload, chain_fn) -> None:
        self._book.acquire()
        try:
            with self.as_chain(record):
                try:
                    chain_fn(record, payload)
                except Drained:
                    pass
                except BaseException as exc:       # noqa: BLE001 - the chain catches everything; the seam re-raises ONE
                    record.exception = exc
                    self._drain.set()
        finally:
            record.done = True
            self._cond.notify_all()
            self._book.release()

    def chain_pick(self, records: list, kind, rank):
        """The chain whose exception the seam raises (the first half of the seam after the drain, B4): of the chains that failed, the one
        with the lowest `(rank(exception), n)`; what it does not choose is said, one line each, never dropped in silence (F3). Returns
        the picked record, or None when no chain failed. `rank` is the stage's (an `InfraStop` before a `Stop` before a `Refusal`
        before a `Person`); the console words come from `kind`."""
        failed = [r for r in records if r.exception is not None]
        if not failed:
            return None
        pick = min(failed, key=lambda r: (rank(r.exception), r.n))
        for other in sorted(failed, key=lambda r: r.n):
            if other is not pick:       # F3: what the seam does not choose is said, one line each - never dropped in silence
                print(f"{kind.label}: {kind.noun} {other.n} also ended with {type(other.exception).__name__}: "
                      f"{' '.join(str(other.exception).split())[:200]}", flush=True)
        return pick

    def chain_seam(self, records: list, cap: int) -> None:
        """The generic seam after the drain: the lowest-numbered failed chain is adopted and its exception re-raised on this thread
        (every failure ranks alike). A stage with its own ranking and its own limit branch passes `seam=` to `run_chains`."""
        kind = getattr(self, "_chain_kind", None) or ChainKind()
        pick = self.chain_pick(records, kind, lambda e: 0)
        if pick is None:
            return
        self.adopt_chain(pick)
        raise pick.exception
