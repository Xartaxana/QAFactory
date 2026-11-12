"""driver_stage_s5.py - Driver members homed here by ai-packages/qa-factory/scripts/tests/fixtures/driver-layers.json (TD-11 cut by tools/source_split.py); no behaviour of its own."""

import hooklib  # noqa: F401 (console setup, K7)
import json
from driver_chains import ChainKind
from driver_core import InfraStop, Refusal, ReworkRefused, seam_rank


class DriverStageS5:
    def host_window_reason(self) -> str:
        """The one reader of the host for the S5 scheduler: "" on Claude, else why S5 windows do not run side by side on this host
        (the hook environment and the receipts of a window are measured on Claude only)."""
        if self.host != "claude":
            return "the host is not Claude, and the hook environment and the receipts of a window are not measured there"
        return ""

    def s5_parallel_cap(self) -> int:
        """`dispatch.parallel_windows` through `config_contract.parallel_windows` (the one reader, AR-13); a bad value reads the default
        with its note, printed once per story (`state["noted"]`)."""
        import config_contract
        value, note = config_contract.parallel_windows(self.config)
        if note:
            self.say_once("parallel_windows", note)
        return value

    # The two reasons that are a state AT ENTRY and fall away once the windows they name have settled (spec 3.6, last row); every other
    # reason (the host, `run.parallel`, a limit, an old story, an unreadable state) holds for the whole run.
    S5_SETTLE_RUNNING = "dispatches of S5 are running or stopped at entry; they settle first and the rest goes side by side after"

    S5_SETTLE_OWED = "a repair round or a debt is owed; it runs first"

    def s5_settling_windows(self, windows: list) -> list:
        """The windows among `windows` that the entry-state reasons name: those whose scope meets a running, blocked or paused S5
        dispatch, and the window of an owed round or a debt. Empty when a dispatch names no case or meets no window (nothing is then
        known to settle, and the caller keeps the whole run serial). Raises with the readers (the caller treats that as serial)."""
        import dispatch_identity
        from controller import s5_part_of
        ctl = self.controller_state()
        rows = dispatch_identity.records(ctl.get("dispatches") if isinstance(ctl, dict) else None)
        scopes = [{str(c) for c in r.get("scope") or [] if c} for r in rows
                  if r.get("stage") == "S5" and r.get("status") in ("running", "blocked", "paused") and s5_part_of(r) != "plan"]
        if any(not s for s in scopes):
            return []
        named = [w for w in windows if any({str(c) for c in w.get("scope") or []} & s for s in scopes)]
        for window in (self.repair_owed(windows)[1], self.repair_debt_pending(windows)[1]):
            if window is not None and window not in named:
                named.append(window)
        return named

    def s5_serial_reason(self, windows: list) -> str:
        """"" when S5 windows may run side by side, else the one reason they run one at a time (spec 3.6). Direction of error: it may say
        serial needlessly on doubt; it must never let two windows run where a row below holds. The project's own word
        (`parallel_windows: 1`) is not this function's: that is the old road itself."""
        import dispatch_identity
        host_reason = self.host_window_reason()
        if host_reason:
            return host_reason
        run = self.config.get("run")
        if isinstance(run, dict) and run.get("parallel") is True:
            return ("the project runs its tests in parallel (`run.parallel: true`) and `test-results/` is shared; with "
                    "`run.parallel: false` the runs queue on the stand and the windows go side by side")
        if getattr(self, "_s5_cap_one", False):
            return "the model service limited one window earlier in this run"
        try:
            ctl = self.controller_state()
            rows = dispatch_identity.records(ctl.get("dispatches") if isinstance(ctl, dict) else None)
        except Exception:       # noqa: BLE001
            return "the state of the S5 dispatches cannot be read"
        if any(r.get("stage") == "S5" and r.get("status") in ("running", "blocked", "paused") for r in rows):
            return self.S5_SETTLE_RUNNING
        if self.repair_owed(windows)[0] or self.repair_debt_pending(windows)[0]:
            return self.S5_SETTLE_OWED
        root = self.task_root / "work"
        legacy = (root / "test-code" / "critic-findings.md").is_file() or (root / "probe-debt.json").is_file()
        per_dispatch = any((root / "test-code").glob("critic-findings-*.md")) or any((root / "probe-debt").glob("*.json"))
        if legacy and not per_dispatch and any("qa-code-critic" in (w.get("accepted_by") or {}) for w in windows):
            return "this story began before the windows kept their findings and probe debt per dispatch; its remainder reads the old files"
        try:
            self.s5_open_windows(())
        except Exception:       # noqa: BLE001
            return "the state or the scope of a window cannot be read"
        return ""

    def s5_todo(self, windows: list) -> list:
        """The windows `stage_S5` works next: those with no accepted critic, and those whose last round is an accepted author round no
        critic has seen (`_s5_author_awaits_critic`, the clause `s5_open_windows` reads too). At `parallel_windows` == 1 nothing is read
        (the frozen N == 1 road, a named residual of TR4-10), and a record that cannot be read leaves today's list."""
        import dispatch_identity
        todo = [w for w in windows if "qa-code-critic" not in (w.get("accepted_by") or {})]
        if self.s5_parallel_cap() == 1:
            return todo
        try:
            ctl = self.controller_state()
            rows = dispatch_identity.records(ctl.get("dispatches") if isinstance(ctl, dict) else None)
            return [w for w in windows if w in todo or self._s5_author_awaits_critic(self._s5_last_round(rows, w.get("scope") or []))]
        except Exception:       # noqa: BLE001 - unreadable: today's list, the refusal below stays reachable
            return todo

    def s5_last_fn(self, cases):
        """The close predicate of a chain's window, as a callable: True only when no other window is open. Unreadable is open."""
        def last() -> bool:
            try:
                return not self.s5_open_windows(excluding=cases)
            except Exception:       # noqa: BLE001 - FR-59
                return False
        return last

    def s5_release_closed(self) -> None:
        """The restart sweep: claims of windows that are closed (not in `s5_open_windows`) are released; it costs nothing when the story has
        claimed nothing. An unreadable state releases nothing."""
        import window_files
        folder = self.task_root / window_files.SUBDIR
        if not folder.is_dir() or not any(folder.glob("*.json")):
            return
        try:
            opened = {tuple(w) for w in self.s5_open_windows(())}
            windows = self.stage_scope("S5").get("windows") or []
        except Exception as exc:       # noqa: BLE001
            print(f"note: the claims of closed windows were left in place: the windows could not be read ({type(exc).__name__})")
            return
        for window in windows:
            cases = sorted({str(c) for c in window.get("scope") or [] if c})
            if cases and tuple(cases) not in opened:
                self.s5_release(cases)

    def s5_notes_line(self) -> str:
        """The line that tells a window which notes of the earlier windows to read first: the old `work/s5-notes.md` (a story from before)
        and the per-dispatch folder `work/s5-notes/`, each named only when it holds something."""
        base = f"qa-factory/artifacts/{self.task}/work"
        parts = []
        if (self.task_root / "work" / "s5-notes.md").is_file():
            parts.append(f"{base}/s5-notes.md")
        if any((self.task_root / "work" / "s5-notes").glob("*.md")):
            parts.append(f"every file of {base}/s5-notes/")
        return f"Read {' and '.join(parts)} first." if parts else ""

    # The door the guard's refusal of a claimed test file names (`guard_pre_tool.window_file_check`), written ONCE for both ownership lines.
    S5_OWN_FILE_DOOR = ("put your test in a new file in the same directory; where a test lives stays your choice, "
                        "and a test in a new file is judged the same.")

    def s5_auto_extra(self, window: dict, cases: list, chain: bool = False) -> list:
        """The lines every dispatch of an S5 window carries. On the parallel road (`chain`) two more tell the role what the scheduler
        makes true: another window may own a test file, and a busy stand is not its failure. TR4-10 Q4 (D6): wherever the guard enforces
        the claims (`config_contract.parallel_windows` != 1, the guard's own reader) the role is told of the ownership rule on the serial
        body too, in a variant without the sentence that is false there (no other window is written at the same time); the stand line
        stays `chain`-only. At N == 1 with `chain` False the list is as it was."""
        import config_contract
        cfg = getattr(self, "config", None)
        enforced = config_contract.parallel_windows(cfg if isinstance(cfg, dict) else {})[0] != 1
        extra = [f"Window: {', '.join(cases)} — {window.get('surface', 'other')} surface.",
                 "Runs go through run_suite.py --mine <CASE>; the manifest is written with manifest_put.py. "
                 "A test written to an approved case that fails against the implementation is handed over "
                 "RED with unresolved reason contradicts_requirement, never adjusted to the code."]
        notes = self.s5_notes_line()
        if notes:
            extra.append(notes)
        if chain:
            extra.append("Other windows of this story are written at the same time. A test file one of them wrote first refuses your "
                         "Write or Edit: " + self.S5_OWN_FILE_DOOR)
        elif enforced:
            extra.append("A test file another window of this story wrote first refuses your Write or Edit: " + self.S5_OWN_FILE_DOOR)
        if chain:
            extra.append("A run that answers `stand busy` after some minutes waited for the stand queue: it is not a failure of your "
                         "tests. Say so in your digest and run again.")
        return extra

    def s5_chain_kind(self) -> "ChainKind":
        """What the scheduler's console and gate call an S5 chain (t-2147 A): a window, holding files; the gate reads `s5_window_files`
        at call time, so a rig's override is seen."""
        return ChainKind("S5", "window", "a file", lambda cases: self.s5_window_files(cases))

    def s5_seam(self, records: list, cap: int) -> None:
        """The seam after the drain (B4): see `run_chains`. A model-service `limit` in one chain, with more than one chain allowed, is not
        a stop: the rest finished and booked, this run goes on at one window at a time (F13), said once. Any other kind stops as today."""
        pick = self.chain_pick(records, self.s5_chain_kind(), seam_rank)
        if pick is None:
            return
        exc = pick.exception
        if isinstance(exc, InfraStop) and exc.kind == "limit" and cap > 1 and not getattr(self, "_s5_cap_one", False):
            self._s5_cap_one = True
            print("note: the model service limited a window; the others finished and are booked, and S5 goes on one window at a time "
                  "for the rest of this run", flush=True)
            return
        self.adopt_chain(pick)
        raise exc

    def s5_launchable(self, record) -> bool:
        """The gate at a chain's start: no running chain's window holds a file of this one."""
        mine = self.s5_window_files(record.cases)
        if not mine:
            return True
        return not any(mine & self.s5_window_files(r.cases) for r in self._chains.values() if r is not record and not r.done)

    def s5_window_chain(self, record, window: dict) -> None:
        """One window's chain, on its own thread: the stand and build checks (a Person there re-arises, state unchanged), the author when
        it has not been accepted, then the loop `s5_window` runs; the window's files are freed when it closed."""
        self.stop_if_drained()
        cases = list(window["scope"])
        self.boundary = "S5:" + ",".join(cases)
        with self.timed("stand_check", stage="S5"):
            self.stand_check("S5")
        with self.timed("build_check", stage="S5"):
            self.build_check("S5", cases=cases)
        auto_extra = self.s5_auto_extra(window, cases, chain=True)
        if "qa-automator" not in (window.get("accepted_by") or {}):
            self.run_role("S5", "qa-automator", scope=cases, complete=False, extra=auto_extra)
        self.s5_window(window, self.s5_last_fn(cases), auto_extra, None)
        self.s5_release(cases)
        view = getattr(self, "_s5_view", None)
        if view is not None:
            view["closed"].add(record.n)

    def run_s5_windows(self, windows: list, todo: list, cap: int) -> None:
        """The parallel road of `stage_S5`: one chain per open window, `cap` at a time."""
        number = {tuple(sorted(w["scope"])): i + 1 for i, w in enumerate(windows)}
        items = [(number[tuple(sorted(w["scope"]))], list(w["scope"]), w) for w in todo]
        held = {tuple(sorted(w["scope"])) for w in todo}       # a window `s5_todo` holds (an accepted author round owed its critic) is not closed
        self._s5_view = {"total": len(windows), "closed": {number[tuple(sorted(w["scope"]))] for w in windows
                                                        if "qa-code-critic" in (w.get("accepted_by") or {})
                                                        and tuple(sorted(w["scope"])) not in held}}      # `todo` may be a part of the open windows (F6)
        try:
            self.run_chains(items, self.s5_launchable, self.s5_window_chain, cap, kind=self.s5_chain_kind(), seam=self.s5_seam)
        finally:
            self._s5_view = None

    def stage_S5(self) -> None:
        with self.timed("stage_scope", stage="S5"):
            scope = self.stage_scope("S5")
        windows = scope.get("windows") or []
        if not scope.get("scope"):
            raise Refusal("S5: stage-scope returned no automate cases: " + json.dumps(scope)[:800])
        todo = self.s5_todo(windows)
        owed, owed_window = self.repair_owed(windows)       # a round the person chose at the repair limit and not run yet (t-698 A4)
        # t-733: a `debt` that consumed an owed round leaves its critic's finish (`--not-complete`) to be completed; no role runs, so no stand or
        # build check is owed. POSITION INVARIANT: before the L5 refusal (which has no door for it) and before any review (a fresh critic would
        # be asked the same question again), never while a round is owed (that round runs first). The critic is finished only while it can
        # be: still running (the controller refuses a bare `--not-complete` accept of the stage's closing critic, so it stays so and its
        # window is in `todo`) or, with nothing else waiting, accepted.
        pending, pending_window = ({}, None) if owed else self.repair_debt_pending(windows)
        if pending and (not todo or "qa-code-critic" not in (pending_window.get("accepted_by") or {})):
            self.s5_close_debt(pending, pending_window)
            return
        if not todo and not owed and self.s5_parallel_cap() != 1:
            # TR4-10 D3 (Lead, option b): a window held open by a returned LAST round (`s5_open_windows` reads it open) is not "every window is
            # accepted": the refusal below names the wrong door for it. The controller's `next` HIDES such a return behind later S5 work, so
            # `_act_resolve_return` never runs for it: this block is the whole road. No words filed: the EXISTING `resolve_return` packet
            # (`resolve_return_refusal`, the one builder `_act_resolve_return` raises too) names the dispatch and goes through the one seam to
            # the conductor, who settles it or asks the person. Words filed for THAT dispatch: the stage resumes the role itself
            # (`resume_with_filed_words`, the one move `_act_resolve_return` makes too; `resume_role` consumes the words) and the stage
            # re-enters - the same packet is never raised twice for words already filed (AR-24). The resumed author's round completes by its
            # repair cause, as the live road does (AR-28): a MECHANICAL round (the critic itself routed it, no critic follows) by the
            # window's own rule, `s5_last_fn` (`s5_mechanical_round`); any other author round (`test_defect`, an absent or unknown cause,
            # read through the controller's one reader `repair_cause`) never completes S5 - its critic reviews it first (`s5_author_round`
            # passes `rework`'s default False). Error direction: False costs one more critic entry, True would close S5 over an
            # unreviewed round. Any other role by `completion_for`.
            # POSITION INVARIANT: before the refusal below, which stays reachable when no window has a returned last round, when the state is
            # unreadable, or when the returned record is gone at the resume. Words filed for ANOTHER dispatch are not used.
            returned, window_scope = None, []
            try:
                import controller as CT
                import dispatch_identity
                ctl = self.controller_state()
                rows = dispatch_identity.records(ctl.get("dispatches") if isinstance(ctl, dict) else None)
                for w in windows:
                    last_row = self._s5_last_round(rows, w.get("scope") or [])
                    if last_row is not None and last_row.get("status") == CT.RETURNED:
                        returned, window_scope = last_row, list(w.get("scope") or [])
                        break
            except Exception:       # noqa: BLE001
                returned = None
            if returned is not None and (self.state.get("pending_words") or {}).get(returned.get("id")):
                def complete_for(stage, role, record):
                    if role == "qa-automator":
                        if CT.repair_cause(record) != "mechanical":
                            return False
                        window_last = self.s5_last_fn(window_scope)
                        return lambda _digest: bool(window_last())
                    return self.completion_for(stage, role, record)
                stage_boundary = getattr(self, "boundary", "S5")
                if self.resume_with_filed_words(str(returned.get("id")), complete_for):
                    return
                # the record is gone: the old refusal below, raised under the STAGE's boundary (the helper set `<stage>:<id>` for
                # `_act_resolve_return`'s packet, which the conductor reads; nothing resumed here, so it is put back - Lead, option A)
                self.boundary = stage_boundary
                returned = None
            if returned is not None:
                from contract import retry_reason_for
                raise self.resolve_return_refusal({
                    "action": "resolve_return", "dispatch_id": returned.get("id"), "stage": returned.get("stage"),
                    "role": returned.get("role"), "dispatch_status": returned.get("status"),
                    "digest": returned.get("returned_digest") or "", "options": ["accept", "checkpoint", "rework"],
                    "retry_reason": retry_reason_for(returned),
                    "reason": returned.get("reason") or "the role stopped without acceptance; accept its evidence, record the block, or send "
                                                        "the work back"})
        if not todo and not owed:
            raise Refusal("S5: every window is accepted by its author and its critic and S5 is still open. That is the "
                          "factory's own state, not a gap in the tests: run `controller.py --operation recover` first and "
                          "read what the controller holds.")
        # TR3-6: the default is 3 windows at a time. `parallel_windows: 1`, ONE open window and an owed round take the body below, verbatim
        # (no thread, no scheduler, no new state key): the owed round runs first through today's one-window code and the stage re-enters,
        # so the remainder then goes side by side. The claims of closed windows are freed first (the restart sweep, F3 b).
        parallel = self.s5_parallel_cap()
        if parallel != 1:
            self.s5_release_closed()
            if len(todo) >= 2 and not owed:
                reason = self.s5_serial_reason(windows)
                if reason:
                    self.say_once("s5-windows", f"note: S5 windows run one at a time: {reason}")
                if reason in (self.S5_SETTLE_RUNNING, self.S5_SETTLE_OWED):
                    # F6 (spec 3.6, last row): a reason that is a state AT ENTRY lasts only while it holds. The windows it names run one
                    # at a time FIRST; when they have settled the reason is read again and the rest goes side by side in this same stage.
                    # A reason that is not about the entry state (the host, `run.parallel`, a limit, an old story) keeps the whole run
                    # serial, as does one that names no window. One round only: a dispatch that never settles cannot loop the stage.
                    try:
                        first = self.s5_settling_windows(todo)
                    except Exception:       # noqa: BLE001 - unreadable: the whole run stays serial
                        first = []
                    if first and len(first) < len(todo):
                        self.run_s5_windows(windows, first, 1)
                        windows = self.stage_scope("S5").get("windows") or []
                        todo = self.s5_todo(windows)
                        if len(todo) < 2:
                            return      # the stage re-enters: no window left, or one, which takes today's body
                        reason = self.s5_serial_reason(windows)
                        if reason:
                            self.say_once("s5-windows", f"note: S5 windows run one at a time: {reason}")
                return self.run_s5_windows(windows, todo, 1 if reason else min(parallel, len(todo)))
        window = owed_window if owed else todo[0]       # a pure choice: above the checks, so each stand check is followed at once by its build check
        with self.timed("stand_check", stage="S5"):
            self.stand_check("S5")      # every window comes through here; a confirmed or passed stand costs no probe
        with self.timed("build_check", stage="S5"):
            self.build_check("S5", cases=list(window.get("scope") or []))     # t-300: the build of THIS window's profiles
        if owed:
            # POSITION INVARIANT (t-729 F3): AFTER the two checks (either can raise a Person and the owed round must still be owed on the
            # next entry) and BEFORE the first dispatch of the round (a crash costs one round, never two).
            owed["executed"] = True
            self.save_state()
        last = (not [w for w in todo if w.get("scope") != window.get("scope")]) if owed else len(todo) == 1
        if last and parallel != 1:
            # TR4-10 D1: at N != 1 the old body reads the same close rule as the chain road: no other window open (a running dispatch, an
            # owed round, a live chain, a LAST round that came back unaccepted). Unreadable is open (FR-59). At N == 1 nothing is read.
            last = self.s5_last_fn(window.get("scope") or [])()
        cases = list(window["scope"])
        self.boundary = "S5:" + ",".join(cases)
        auto_extra = self.s5_auto_extra(window, cases)      # TR3-6: the notes line names the per-dispatch notes too, not only the old file
        if "qa-automator" not in (window.get("accepted_by") or {}):
            self.run_role("S5", "qa-automator", scope=cases, complete=False, extra=auto_extra)
        before = getattr(self, "last_dispatch", "")
        try:
            self.s5_window(window, last, auto_extra, owed)
            self.s5_release(cases)          # the window closed: its test files are free for a later one (a no-op at `parallel_windows: 1`)
        except ReworkRefused:
            if owed and getattr(self, "last_dispatch", "") == before:
                # t-760 (t-758 finding 3): the controller refused to START the owed round (no role ran, `last_dispatch` is unchanged), so the
                # mark above is taken back - on a non-last window the critic is accepted and the person's round would be lost in silence
                owed["executed"] = False
                self.save_state()
            raise

    S5_CRITIC_BRIEF = ["Static review first, then probe_by_code.py once per instance, every check of the test: "
                       "red_sandbox.py --probe (only when you doubt the check looks at the product, with the reason "
                       "in your findings) proves only the one check it names, the others stay owed; a probe of unchanged "
                       "bytes and the same entries is answered `already_probed`; write your findings file and the review_receipt_ref "
                       "on the manifest bindings; `cause:` on each finding."]

    def s5_window(self, window: dict, last: bool, auto_extra: list, owed: dict | None = None) -> None:
        """One S5 window from its review to its close: the critic reviews, the route says what follows (an author round, a mechanical
        round, the close), and a round the person chose at the repair limit (`owed`) runs first. The gate of the seam sits in
        `run_role`, before the critic's finish: a limit, an unreadable count or a rejection nobody can repair is asked there."""
        import repair_route
        cases = list(window["scope"])
        after_round, step = None, owed      # `after_round`: `counted` when the last test_defect round was dispatched
        while True:
            # the rounds spent are the controller's count, read fresh before every review
            budget = self.budget_or_none("S5", "qa-automator", cases)
            if after_round is not None and isinstance(budget, dict) and isinstance(budget.get("counted"), int) \
                    and isinstance(budget.get("cap"), int) and budget["counted"] <= after_round:
                # the loop's only bound is the ledger growing with every round; a ledger that did not count
                # the round just run would send the same review back for ever
                print(f"S5: the controller did not count the round just run ({budget['counted']} of {budget['cap']}); "
                      "no further repair round is dispatched for this window")
                # the count is UNKNOWN now (L3, t-698 §2): the gate of this very review reads this budget (it is passed, not re-read),
                # so the window closes over the seam reason `unknown` - asked, never in silence - and a debt is recorded if chosen
                budget = dict(budget, counted=None)
            if step and step["token"] in ("round", "route"):
                # the person's round (`owed`, token `round`), or the ordinary round a recovery finish left owed (token `route`): the
                # critic's rejection stands, the author repairs it (on the passes the answer wrote, for `round`)
                critic, digest = step["dispatch"], ""
                form = repair_route.read_form(self.task_root / "work" / "handoffs" / f"{critic}.yaml") if step["token"] == "route" else None
                route = {"action": step.get("action") or "test_defect", "reason": "the person's round" if step["token"] == "round"
                         else step.get("reason") or "an owed round", "not_rounds": [], "note": "", "code": ""}
                if route["action"] == "test_defect" and not self.repair_countable(budget):
                    # t-732: the round is announced as "n of cap" and the loop is bounded by that count - with no count it is not run
                    # blind. It stays owed (the mark `stage_S5` wrote is taken back) and the seam asks `unknown`, never a TypeError.
                    step["executed"] = False
                    self.save_state()
                    self.repair_limit_raise(self.repair_limit_facts(critic, cases, dict(route, action="close", code="unknown"), form, budget))
            else:
                digest, critic, route, form = self.s5_review(cases, last, budget, step)
            step = None
            self.s5_note_findings(route, form, critic)
            forms = f"work/handoffs/{critic}.yaml"
            if route["action"] == "test_defect":
                after_round = self.s5_author_round(cases, budget, digest, forms, auto_extra, critic)
                continue        # the loop dispatches the critic again on the new bytes
            if route["action"] == "mechanical":
                self.s5_mechanical_round(cases, last, critic, form, auto_extra)
                break           # the reviewer is not dispatched again after a mechanical round
            print(f"S5: {critic} closes the window with no further round: {route['reason']}")
            break

    @staticmethod
    def s5_window_closed(route: dict, answer: dict) -> bool:
        """THE close predicate of an S5 window (t-698 A3), shared by the loop and `completion_for`: the route closes it, and when
        the route closes over a seam reason (`code`) the person's answer for THAT critic dispatch is `debt`. A close over a seam
        reason with no answer is not a close: the gate asks first, so this is False only on a road that skipped the gate.
        A `debt` that consumed an owed round (`owed`, t-733) is a close whatever the route now reads: the round it replaced is never run."""
        if answer.get("token") == "debt" and answer.get("owed"):
            return True
        return route.get("action") == "close" and (not route.get("code") or answer.get("token") == "debt")

    def s5_review(self, cases: list, last: bool, budget, step: dict | None) -> tuple:
        """(digest, critic, route, form): ONE review of the window. `step` (the person's answer `fixed` / `review`) is a critic
        dispatch with the cause the answer names, which spends none of the cap; otherwise the plain critic dispatch. The route is
        known BEFORE the critic's finish: the last window's critic closes S5 only when `s5_window_closed` says so - never while its
        author is owed a (mechanical) round, never over a seam reason the person has not answered."""
        def closes(text: str, dispatch: str = "") -> bool:
            # TR3-17: the critic dispatch is read ONCE and handed to both readers; `finish` calls with the digest alone, so the default is
            # this thread's `last_dispatch` (the serial road's value, byte for byte as before).
            dispatch = dispatch or getattr(self, "last_dispatch", "")
            route, _form = self.route_of(text, budget, dispatch)
            # TR3-6: on the parallel road `last` is a callable (no other window open), read HERE, at the finish, under `_book`
            return bool((last() if callable(last) else last) and self.s5_window_closed(route, self.repair_answer(cases, dispatch)))
        if step and step.get("cause"):
            digest, _next = self.rework("S5", "qa-code-critic", cases, step.get("reason") or "the person asked for a new review",
                                        cause=step["cause"], complete=closes, extra=self.S5_CRITIC_BRIEF, budget=budget)
        else:
            digest, _next = self.run_role("S5", "qa-code-critic", scope=cases, complete=closes, extra=self.S5_CRITIC_BRIEF, budget=budget)
        critic = getattr(self, "last_dispatch", "")
        route, form = self.route_of(digest, budget, critic)
        return digest, critic, route, form

    def s5_author_round(self, cases: list, budget, digest: str, forms: str, auto_extra: list, critic: str = ""):
        """The author's test_defect round over the critic's findings (`critic`: the dispatch whose review sent the window back);
        returns the `counted` it was dispatched at. The findings are that critic's file `work/test-code/critic-findings-<critic>.md`,
        else the one file of a story from before findings went one per dispatch (`critic-findings.md`), else the digest: never "the
        newest on disk" and never `work/**` (with two windows that was the other window's file, or the S4 critic's; t-1937 TR3-5)."""
        import findings_path
        found = findings_path.resolve(self.task_root, critic)
        findings = (self.task_root / found) if found else None
        reason = (findings.read_text(encoding="utf-8", errors="replace")[:1200] if findings else digest)
        self.rework("S5", "qa-automator", cases, "critic round: " + reason, cause="test_defect",
                    extra=[f"Repair round {budget['counted'] + 1} of {budget['cap']}: the critic's form is {forms} and "
                           f"its findings are in "
                           f"{findings.relative_to(self.task_root).as_posix() if findings else 'the critic digest'}; "
                           "re-run only the instances whose code changed; a comment/docstring/marker-only "
                           "fix keeps its run (the factory answers `reused`)."] + auto_extra)
        return budget["counted"]

    def s5_mechanical_round(self, cases: list, last: bool, critic: str, form, auto_extra: list) -> None:
        """The author's mechanical round over the critic's mechanical findings; no critic is dispatched after it."""
        import repair_route
        ids = ", ".join(f["id"] for f in repair_route.findings(form) if f["blocking"] and f["cause"] == "mechanical")
        forms = f"work/handoffs/{critic}.yaml"
        self.rework("S5", "qa-automator", cases, f"mechanical fixes of review {critic}: {ids}",
                    cause="mechanical", complete=((lambda _digest: bool(last())) if callable(last) else last),
                    extra=[f"Mechanical round of the review {critic} (its form is {forms}): fix only the findings "
                           f"{ids}; no critic is dispatched after it - your green run on the new bytes closes the "
                           f"round. Write `mechanical_round` on the window record with window_record.py "
                           f"(reviewer dispatch {critic}); re-run only the instances whose code changed; a "
                           "comment/docstring/marker-only fix keeps its run (the factory answers "
                           "`reused`)."] + auto_extra)

    def s5_close_debt(self, entry: dict, window: dict) -> None:
        """The critic of `entry` was left open by an owed round and the person then chose `debt` instead of the round:
        finish it by the SAME close predicate as the gate's debt (`completion_for` -> `s5_window_closed`), so the window closes
        over the debt (the review-debts entry was written with the answer). Marked `finished` once the finish went through, so a
        refused finish is made again by the next entry and a finished one never twice (t-733)."""
        cases, critic = list(window.get("scope") or []), entry["dispatch"]
        print(f"S5: the person left the tests of {', '.join(cases)} rejected instead of another round; {critic} closes the window")
        digest = f"qa-code-critic S5 {', '.join(cases)} · concerns\nthe window is closed by the person's choice; the tests stay rejected (review debt)"
        self.finish(critic, digest, complete=self.completion_for("S5", "qa-code-critic", {"id": critic, "scope": cases}),
                    role="qa-code-critic", stage="S5")
        entry["finished"] = True
        self.save_state()

    def resume_with_filed_words(self, dispatch: str, complete_for) -> bool:
        """The ONE move on a returned dispatch whose person's words are filed (TR4-10 B1): hand the words back to the role so it closes its own
        window. Called by `_act_resolve_return` (the controller offered the return) and by `stage_S5` (the controller hides it behind later S5
        work). `complete_for(stage, role, record)` answers the completion rule of the resume. True when the role was resumed (`resume_role`
        spends the words); False when no words are filed for `dispatch` (empty text counts as none, a blank one as words - as before), or
        its record is gone, or names no stage or role: nothing ran and the caller takes its refusal."""
        record = (self.controller_state().get("dispatches") or {}).get(dispatch) or {}
        words = self.state["pending_words"].get(dispatch)
        stage, role = str(record.get("stage") or ""), str(record.get("role") or "")
        self.boundary = f"{stage}:{dispatch}"
        if words and stage and role:
            print(f"{dispatch}: returned without acceptance — resuming the role with the "
                  f"person's words so it closes its own window")
            self.resume_role(stage, role, dispatch, words, complete=complete_for(stage, role, record))
            return True
        return False

    @staticmethod
    def resolve_return_refusal(action: dict) -> "Refusal":
        """The `resolve_return` packet as a Refusal naming the dispatch: ONE builder for `_act_resolve_return` (no words filed) and for
        `stage_S5` (a window held open by a returned last round, TR4-10 D3)."""
        return Refusal(f"resolve_return: {json.dumps(action)[:1200]}", dispatch=action.get("dispatch_id", ""))
