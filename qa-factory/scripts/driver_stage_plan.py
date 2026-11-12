"""driver_stage_plan.py - Driver members homed here by ai-packages/qa-factory/scripts/tests/fixtures/driver-layers.json (TD-11 cut by tools/source_split.py); no behaviour of its own."""

import json
import re
from pathlib import Path
import waiver
from driver_core import OpenWork, Person, Refusal, _read_answer, open_work_reason


class DriverStagePlan:
    def role_lines(self, stage: str, role: str, record=None) -> list:
        pipeline = self.pipeline()
        env = pipeline.get("environment") or ("pending" if pipeline.get("environment_pending") else "none")
        if pipeline.get("environment") and pipeline.get("environment_pending"):
            # A name that no check has answered for is not "the environment" (FR-41): a role that
            # reads `Environment: local` starts on it as if it were known to be up.
            env = f"{env} (not confirmed yet)"
        base = f"qa-factory/artifacts/{self.task}/"
        if role == "qa-scout":
            # An `--mr` the person gave up at S0 (the list of sources not to read named the same request and
            # they chose to skip it) is still on a later command line: the scout is not told it.
            # The launch is read from the KEPT launch too (F8): a process started with `--answer` carries no `--mr`, and the scout
            # must not be told "none" for a story that was launched with one. `launch_flags` is pure - no state is written here.
            launch = self.launch_flags()
            dropped = (self.state.get("launch") or {}).get("mr_dropped")
            mr = launch["mr"] if launch["mr"] and launch["mr"] != dropped else None
            flags = " ".join(f for f in [f"--mr {mr}" if mr else "", f"--branch {launch['branch']}" if launch["branch"] else "",
                                         f"--commit {launch['commit']}" if launch["commit"] else "",
                                         "--ungrounded" if launch["ungrounded"] else ""] if f) or "none"
            repos = ", ".join(f"{r.get('name')}={r.get('path')}" for r in self.config.get("code_repos") or [])
            repos = (repos + ", " if repos else "") + f"tests={self.config.get('tests_root') or '.'}"
            source = ("local text, key made by the factory; no tracker holds it: "
                      f"collect {self.task} --relation task records it, no network; do not peek it" if self.s0_is_local()
                      else '--ticket-file ' + launch['ticket_file'] if launch['ticket_file'] else 'the configured ticket adapter')
            # SS1-15: a tracker the factory holds no client for is read by the route onboarding recorded (`reads_by_role`)
            import ticket_adapter
            from source_inventory import tracker_route_lines
            by_role = ticket_adapter.reads_by_role(self.config)
            if by_role and source == 'the configured ticket adapter':
                source = "the project's tracker, by the route below; the task's text is the snapshot S0 made"
            # SS1-13: the person's `current code` answer reaches the scout BEFORE its work (FR-38): without the line step 4 of the role halts.
            grounding = ([f"implementation_source: {launch['implementation_source']}"] if launch.get("implementation_source") else [])
            # OH3-39: the places the project keeps requirements (config.json `requirements_sources`) reach the scout before its work (FR-38)
            from source_inventory import requirement_source_lines
            return ([f"Launch flags: {flags}"] + grounding + [f"Environment: {env}", f"Ticket source: {source}"]
                    + tracker_route_lines(self.config, by_role=by_role)
                    + [f"Repositories: {repos}", f"pipeline.json: {base}pipeline.json"]
                    + requirement_source_lines(self.config, local=self.s0_is_local(), by_role=by_role) + self.left_out_lines())
        if role == "qa-requirements-tester":
            return [f"implementation_source: {pipeline.get('implementation_source') or 'unknown'}",
                    f"context-bundle.json (read first): {base}work/context-bundle.json",
                    f"context-manifest.json (only referenced detail): {base}work/context-manifest.json",
                    f"impl-diff.txt: {base}work/impl-diff.txt (absent when ungrounded or current-code)"]
        if role == "qa-test-strategist":
            return self.s3_strategist_lines(record) if stage == "S3" else [self.S3_PLAN_LINE]
        if role == "qa-runner":
            return [f"Environment: {env}"]
        if role == "qa-failure-analyst":
            import controller as CT
            analyst = [f"run-report.json: {base}work/run-report.json · automation-manifest.json: {base}work/automation-manifest.json · evidence: {base}work/evidence/",
                       f"test-plan.md (each row's oracle): {base}test-plan.md", f"Environment: {env}"]
            # P2 M3: an investigation dispatch (a live gate call or a controller RECORD on a restart road) also gets its targets, caps and form note
            return analyst + self.investigation_lines() if CT.s7_part_of(record or {}) == "investigation" else analyst
        if role == "qa-doc-scribe":
            ext = self.config.get("external_writes") or {}
            channels = (f"Bugs channel: {ext.get('bugs', 'markdown')} · Cases channel: {ext.get('cases', 'markdown')}"
                        if not self.no_trace() else
                        "Bugs channel: markdown (closed for this run: experiment) · "
                        "Cases channel: markdown (closed for this run: experiment)")
            return [f"ledger.json, ledger.md, test-plan.md, automation-manifest.json, run-report.json, triage.json, bug-drafts/: under {base}work/ (test-plan.md at {base}test-plan.md)",
                    channels]
        if role == "qa-retro-analyst":
            feedback = self.state.get("retro_feedback") or "declined"
            return ["THE NUMBERS ARE ALREADY COMPUTED: work/retro-numbers.md (rendered) and work/retro-numbers.json (facts). Do not open journal.jsonl or state/cost/.",
                    f"pipeline.json, test-plan.md, context-manifest.json: {base}pipeline.json, {base}test-plan.md, {base}work/context-manifest.json",
                    f"Human feedback, verbatim: \"{feedback}\"",
                    "Do NOT move the artifact folder and do NOT set pipeline.json archived."]
        return []

    def stage_simple(self, stage: str) -> None:
        role = self.stages()[stage]["roles"][0]
        # S-c (t-2181 PC-9b): S1 of a story whose side carries a `reference` has ONE more dispatch after the scout, the runner's walk of the
        # old version (`optional_dispatches` of references/stages.json, read through `stage_guard.optional_rows`, the ONE reader; purpose
        # `reference_walk`). A story with no reference reads no stand name and takes the line below, byte for byte as before.
        if stage != "S1":
            return self.run_role(stage, role, extra=self.role_lines(stage, role))
        window = self.s1_window_owed(stage)
        if not window:
            return self.run_role(stage, role, extra=self.role_lines(stage, role))
        import controller as CT
        import exit_gate
        try:
            mine = {k: v for k, v in (self.controller_state().get("dispatches") or {}).items()
                    if isinstance(v, dict) and v.get("role") == role and v.get("status") not in CT.DISCOUNTED}
            scout = exit_gate.stage_dispatch(mine, stage)
        except Exception as exc:  # noqa: BLE001 - unreadable state: the scout runs again (the dearer direction), said once (N4)
            print(f"S1: reference window: the scout's dispatch could not be read ({type(exc).__name__}); the scout runs again")
            scout = None
        if not (scout and scout.get("status") == "accepted"):
            # the scout does NOT close S1 here: the runner's window is the stage's last dispatch (complete=True below)
            self.run_role(stage, role, extra=self.role_lines(stage, role), complete=False)
        self.s1_reference_window(stage, window)

    # --- S3 in two windows (G1-11, grounding/1) --------------------------------------------------------------------------------

    def stage_S3(self) -> None:
        """S3 as two strategist dispatches: window 1 (`purpose: s3_labelling`) labels work/grounding.yaml and writes no plan, window 2
        writes the plan. Window 2 is NOT chained here: after window 1's acceptance the loop asks `where` again, the controller answers
        `prepare_stage S3`, and this method finds `between` - one road for the live run and for a restart (I3). Off the diff world
        there is nothing to label: one window as before, after the preparation wrote the null outcome."""
        import controller as CT
        import grounding_table as GT
        self.first_look_step()       # t-2277 FL-5: before `s3_prepare` and window 1 of THIS pass; no strategist dispatch is registered ahead of it
        role = self.stages()["S3"]["roles"][0]
        critic = bool(self.stage_acceptor("S3"))
        if critic and self.s3_author_done():
            return self.stage_critic_route("S3", role)       # X2-7: the author's exit window is accepted; the stage critic is next
        if GT.source_state(self.task_root)[0] != "diff":
            self.s3_prepare()
            self.run_role("S3", role, extra=self.role_lines("S3", role), complete=self.s3_window_completion({"window": "exit"}))
            if critic:
                self.stage_critic_route("S3", role)
            return
        if self.s3_window() == "between":
            back = self.s3_fresh_for_window2()          # step 8: "" or why window 1 runs again (R5 was prepared there)
            if not back:
                self.s3_between_windows()
                self.run_role("S3", role, extra=self.role_lines("S3", role, {"window": "exit"}),
                              complete=self.s3_window_completion({"window": "exit"}))
                if critic:
                    self.stage_critic_route("S3", role)       # never after window 1 (labelling): a plan nobody wrote is not judged
                return
            print(f"S3: window 1 runs again - {back}")
        else:
            self.s3_prepare()                           # BEFORE `start`: the table exists before window 1 writes a byte
        self.run_role("S3", role, purpose=CT.S3_LABELLING, extra=self.role_lines("S3", role, {"window": "labelling"}),
                      complete=self.s3_window_completion({"window": "labelling"}))

    def first_look_step(self) -> None:
        """The first look at the new version on the stand, before the plan (t-2277 FL-5; `first_look.py` is the one reader and writer of the
        record, `walk_session.py` the walk, AR-14/AR-15). POSITION: the first call of `stage_S3`, before `s3_prepare` and window 1. INVARIANT:
        no strategist dispatch of this pass is registered before the first look is decided - walked, skipped with a named reason, or answered.
        1. `first_look.due` false WITH a reason -> `put --null <reason>` (a specific null already written for these heads is kept, never
           replaced by the generic `walk_not_opened`), one line, the plan as today; false with none -> one line "already on these heads".
           2. True -> `_first_look_walk`: the survey walk is opened for the register's requirements (`--env` of the story's stand; the
           actors are `first_look.walk_actors`: accounts first, `guest` in a slot left over, J-18), THEN the optional dispatch of
           stages.json S3 (`qa-runner`, purpose `first_look`) is registered and run (a failed open leaves no registered dispatch for the
           controller to close): an open that fails ends the attempt, removes the walk record and writes the null reason, and the plan is
           made as today (FR-57, no question). 3. Accepted = the dispatch closed by the controller AND `first_look.read` gives a fresh,
           non-empty record of THIS walk (`_first_look_accepted`); not accepted -> the attempt keeps what it is (`written` stays; one
           that is still `walking` ends `nothing_written`), a gap line, and S3 AT ONCE: no question over unaccepted work, the dispatch is
           not repeated on these heads (`due`). 4. `_first_look_question`: an ACCEPTED record whose `first_look.share` is below the floor,
           with something counted, no `continue` for these heads and register and no answer yet to this walk -> `first_look.dead`.
           Never raises for a doubt (P1): what code cannot establish is one printed line and the plan as today."""
        import first_look as FL
        T = self.task_root
        say = lambda text: print(f"S3: first look: {text}")      # noqa: E731
        try:
            pipeline = self.pipeline()
            due, reason, why = FL.due(T, pipeline, self.config)
        except Exception as exc:  # noqa: BLE001 - P1
            say(f"the question whether to walk could not be asked ({type(exc).__name__}); the plan is made as before")
            return
        if not due:
            if reason:
                self._first_look_null(FL, reason, why)
            else:
                say(f"on these heads there was already one: {FL.read_attempt(T).get('outcome') or 'recorded'}")
        elif not self._first_look_walk(FL, pipeline):
            return              # not walked or not accepted: S3 at once (B3), nothing is asked over work nobody accepted
        self._first_look_question(FL)

    def _first_look_null(self, FL, reason: str, why: str) -> None:
        """`put --null <reason>`, one line. A specific null of these heads (`no_reachable_surface`, `profile_not_chosen`) is not overwritten by
        the generic `walk_not_opened` a later entry reaches through `due` (t-2277 FL-5 m3, AR-27): the reason the person reads is the
        first one found."""
        T = self.task_root
        if reason == "walk_not_opened":
            held = FL.read(T)
            if held["null"] and held["null"] != reason and not held["stale"]:
                print(f"S3: first look: none ({held['null'].replace('_', ' ')}): kept; {why}")
                return
        # remains: the exit code is read on the next lines - a record that was not written is printed with the reason, and the plan is made as before (P1)
        code, out = self.py("first_look.py", "put", "--task-root", str(T), "--null", reason)
        print(f"S3: first look: none ({reason.replace('_', ' ')}): {why}"
              + (f"; the record of that was not written ({(str(out).strip().splitlines() or ['no output'])[-1][:200]})" if code else ""))

    def _first_look_accepted(self, FL) -> bool:
        """THE reader of "the first look of these heads was accepted" (AR-13): the attempt says `written`, the controller's dispatch of that
        attempt is `accepted`, and `first_look.read` gives a current, non-null, non-empty record of THAT walk. A record `put` wrote under a
        dispatch that was not accepted is not accepted work: it asks nothing and counts for nothing. Anything unreadable: False."""
        try:
            attempt = FL.read_attempt(self.task_root)
            got = FL.read(self.task_root)
            state = (self.controller_state().get("dispatches") or {}).get(attempt.get("dispatch")) or {}
            return bool(attempt.get("outcome") == "written" and state.get("status") == "accepted" and not got["problem"] and not got["null"]
                        and not got["stale"] and got["rows"] and got["walk"] == attempt.get("dispatch"))
        except Exception:  # noqa: BLE001 - an unreadable state is not an acceptance (AR-28)
            return False

    def _first_look_give_up(self, FL, dispatch: str, null: str, said: str, *, refused: bool) -> None:
        """The walk did not open (FR-57): the dead walk record goes and the null reason is written. The attempt ends `open_failed` (the next
        entry may try once more) - except for a REFUSED cause (`walk_session.REFUSED_CAUSES`: the project has no surface), which cannot get
        better by trying again and ends `nothing_written` (settled: `due` repeats nothing, m3)."""
        T = self.task_root
        # remains: the attempt's end is bookkeeping of a walk that is given up (P1): the plan is made as before whether or not it was written
        self.py("first_look.py", "end", "--task-root", str(T), "--outcome", "nothing_written" if refused else "open_failed")
        try:
            (T / "state" / "walks" / f"{dispatch}.json").unlink()
        except OSError:
            pass
        # remains: the null record only explains the missing look in the next line (P1): the plan is made as before whether or not it was written
        self.py("first_look.py", "put", "--task-root", str(T), "--null", null)
        print(f"S3: first look: none ({null.replace('_', ' ')}): the walk was not opened ({said}); the plan is made as before")

    def _first_look_walk(self, FL, pipeline: dict) -> bool:
        """Steps 2-3 of `first_look_step`: open the walk, register and run the optional dispatch, accept or not. True = ACCEPTED."""
        import controller as CT
        import grounding_table as GT
        import stage_guard as SG
        import walk_session as WS
        T = self.task_root
        say = lambda text: print(f"S3: first look: {text}")      # noqa: E731
        last = lambda out: (str(out).strip().splitlines() or ["no output"])[-1][:200]      # noqa: E731
        model = SG.stage_model()
        stage = next((st for st in model.get("stages") or [] if st.get("id") == "S3"), {})
        row = next((r for r in SG.optional_rows(stage) if r["purpose"] == CT.FIRST_LOOK), None)
        if row is None:     # the one source of the dispatch's role and purpose is stages.json; without its row there is nothing to register
            say("stages.json S3 names no optional dispatch of purpose first_look (gap); the plan is made as before")
            return False
        role, purpose = row["role"], row["purpose"]
        stand = str(pipeline.get("environment") or "")
        items = sorted(GT.register_info(T).ids, key=lambda r: (len(r), r))
        known = (self.controller_state().get("dispatches") or {})
        number = 1
        while f"S3-{role}-{number}" in known:
            number += 1
        dispatch = f"S3-{role}-{number}"
        who = FL.walk_actors(self.project, self.config, stand, WS.data()["max_actors"])
        actors = who["actors"]
        code, out = self.py("first_look.py", "begin", "--task-root", str(T), "--dispatch", dispatch, "--env", stand)
        if code:
            self._first_look_give_up(FL, dispatch, "walk_not_opened", f"first_look.py begin: {last(out)}", refused=False)
            return False
        code, out = self.py("walk_session.py", "open", "--task-root", str(T), "--walk", dispatch, "--place", "survey", "--env", stand,
                            "--items", ",".join(items), "--actor", actors[0], *(["--actor2", actors[1]] if len(actors) > 1 else []))
        if code:
            cause = str((_read_answer(out) or {}).get("cause") or "")
            self._first_look_give_up(FL, dispatch, cause if cause in (FL.data().get("null_reasons") or []) else "walk_not_opened", last(out),
                                     refused=cause in WS.REFUSED_CAUSES)
            return False

        def close_walk(done: str, _result=None) -> None:
            # remains: the exit code is read on the next line and printed as a note; the walk's server ends by itself
            code2, out2 = self.py("walk_session.py", "close", "--task-root", str(T), "--walk", done)
            if code2:
                print(f"note: walk_session.py close exit {code2}: {last(out2)}; the server ends by itself")
        try:
            from controller import Controller
            import event_store
            controller = Controller(T, wait_seconds=event_store.LIFECYCLE_WAIT_SECONDS)
            packet = controller.prepare({"stage": "S3", "role": role, "id": dispatch, "purpose": purpose})
            controller.apply("dispatch", dict(packet["dispatch_request"], purpose=purpose))
        except Exception as exc:  # noqa: BLE001 - nothing was registered or the registration failed: the walk is not left open
            close_walk(dispatch)
            self._first_look_give_up(FL, dispatch, "walk_not_opened",
                                     f"the dispatch was not registered: {type(exc).__name__}: {' '.join(str(exc).split())[:160]}", refused=False)
            return False
        self.boundary = f"S3:{dispatch}"
        if who["problem"]:
            say(f"the record of project knowledge could not be read fully ({who['problem'][:120]}); the accounts it has are used")
        print(f"S3: first look: {dispatch} walks {len(items)} requirement(s) on `{stand}` as {', '.join(actors)}"
              + (f"; accounts not opened (the walk holds {len(actors)}): {', '.join(who['left'])}" if who["left"] else ""))

        def launch() -> None:
            self.record_running("S3", role, dispatch, retry=launch)
            self.run_role("S3", role, scope=[], complete=False, after=close_walk,
                          extra=self.role_lines("S3", role),
                          rework={"id": dispatch, "scope": [], "reason": "first look",
                                  "line": f"First look: survey walk {dispatch} on {stand} is open; your brief has the commands and the form."})
        launch()
        if self._first_look_accepted(FL):
            return True
        if FL.read_attempt(T).get("outcome") == "walking":      # the role wrote nothing; a record `put` wrote keeps its `written` (B3)
            # remains: bookkeeping of an attempt that wrote nothing (P1): the line below says the plan is made without the look
            self.py("first_look.py", "end", "--task-root", str(T), "--outcome", "nothing_written")
        say(f"{dispatch} was not accepted with a record of this walk (gap); the plan is made without it and the look is not repeated on these heads")
        return False

    def _first_look_question(self, FL) -> None:
        """Step 4 of `first_look_step`: `first_look.dead` over an ACCEPTED record below the floor, not yet continued and not yet answered."""
        say = lambda text: print(f"S3: first look: {text}")      # noqa: E731
        T = self.task_root
        try:
            if not self._first_look_accepted(FL) or FL.asked(T):
                return
            share = FL.share(T, self.config)
            if not share["below"] or FL.continued(T, self.pipeline()):
                return
            record = FL.read(T)
            import contract
            sides = {n: s["reality"] for n, s in contract.story_sides(self.pipeline()).items() if s["reality"] != "real"}
        except Exception as exc:  # noqa: BLE001 - P1: an unreadable look asks nothing
            say(f"the share could not be read ({type(exc).__name__}); the plan is made as before")
            return
        import interim_packet
        lines = [f"Before planning I looked at the stand `{record.get('stand') or self.pipeline().get('environment')}` once. It showed "
                 f"{share['reachable']} of {share['counted']} requirements ({share['share']}%), under the {share['floor']}% from which I go on "
                 f"by myself. Every requirement, by what the stand answered: {interim_packet.status_counts(record['rows'])}."]
        stuck = [r for r in record["rows"] if r.get("status") not in (FL.data().get("reachable") or [])]
        if stuck:
            shown = [f"- {r.get('req')}: {' '.join(str(r.get('why') or 'no reason given').split())[:140]}" for r in stuck[:self.GROUNDING_NAMED_MAX]]
            if len(stuck) > self.GROUNDING_NAMED_MAX:
                shown.append(f"- and {len(stuck) - self.GROUNDING_NAMED_MAX} more")
            lines.append("The stand did not show:\n" + "\n".join(shown))
        if sides:
            lines.append("Parts of the product that are not the real thing yet: " + ", ".join(f"{n} ({w})" for n, w in sides.items()) + ".")
        if record.get("stand_build") == "not_established":
            lines.append("Nobody has confirmed which build is on the stand, so the feature may be missing only because the build there is old.")
        lines.append("What I need from you is one of these:")
        options = [{"answer": "continue", "token": "continue",
                    "says": "write the plan anyway; the plan reads what the stand showed as an observation, not as the truth"},
                   {"answer": "stop", "token": "stop",
                    "says": "stop the story here and wait until the build you want checked is on the stand; nothing runs. You can also tell me "
                            "in your own words what to do instead"}]
        # remains: a closed question over the story's own state, not a state without a move: every answer has an executor (`_first_look_answer`)
        raise Person("first_look_dead", self.closed_question("first_look.dead", "\n\n".join(lines), options),
                     "S3", answer_note="Write `continue`, `stop`, or your own words (the conductor reads them).")

    def s3_author_done(self) -> bool:
        """True when the newest S3 strategist dispatch that counts is ACCEPTED and is not window 1 (labelling): the plan is written and the
        stage critic's route is next (a restart of the process, or the author's repair round). Unreadable state: False."""
        import exit_gate
        try:
            mine = exit_gate.s3_strategist_records(self.controller_state().get("dispatches") or {})
        except Exception:
            return False
        newest = exit_gate.stage_dispatch(mine, "S3")
        return bool(newest) and newest.get("status") == "accepted" and not self.s3_labelling_of(newest)

    def s3_window(self) -> str:
        """`"between"` when the newest S3 strategist dispatch that counts is an ACCEPTED window 1, else `"w1"`. The word is read through
        `controller.s3_window_of` (never the top of the record) and the status only; the table is not consulted (I4). A set-aside dispatch
        (the controller's DISCOUNTED) does not count; an unreadable controller state is `w1`. `old` never appears at entry."""
        import controller as CT
        import exit_gate
        try:
            mine = exit_gate.s3_strategist_records(self.controller_state().get("dispatches") or {})
        except Exception:
            return "w1"
        newest = exit_gate.stage_dispatch(mine, "S3")
        if newest and CT.s3_window_of(newest) == "labelling" and newest.get("status") == "accepted":
            return "between"
        return "w1"

    def s3_fresh_for_window2(self) -> str:
        """Step 8: `""` when window 2 may run over the table, else the reason window 1 runs again. `GT.check` in-process; only R0, R1, R2
        and R5 send back (R3, R4, R8 are the exit's), minus the findings a person's recorded word passed (`waiver.split_overridden`).
        R5 (the register or diff moved) and R0 owned by the driver prepare the table first; a finding owned by the role goes back to
        window 1. A finding owned by the driver or the conductor that the preparation does not cure (R1/R2 of the diff or the register,
        R0 of a table the conductor's door must rewrite), or a check that raises, is a Refusal - never window 2, never window 1 again
        over it (FR-59, AR-25)."""
        import grounding_table as GT
        try:
            findings = GT.check(self.task_root)
        except Exception as exc:
            raise Refusal(f"S3 step 8: the grounding check could not run ({type(exc).__name__}: {exc}). Window 2 is not started over a "
                          "table that was not checked. Way on: the conductor (P22).", dispatch="")
        pipeline = self.pipeline()
        standing = [f for f in findings if f.rule in ("R0", "R1", "R2", "R5")
                    and not waiver.split_overridden([f.text], pipeline, "S3")[1]]
        if not standing:
            return ""
        # A finding window 1 cannot cure is a Refusal, raised BEFORE any window-1 dispatch is registered (nothing is paid): window 1's exit
        # keeps only the role's findings, so it would accept, this step would send it back, and the loop has no door (B2, AR-17 / AR-25).
        # What the prepare road cures (R5; R0 owned by the driver) and what the role fills (any `role` finding) is not in this class.
        stuck = [f for f in standing if f.who != "role" and not (f.rule == "R5" or (f.rule == "R0" and f.who == "driver"))]
        if stuck:
            raise Refusal(f"S3 step 8: {stuck[0].text} Window 1 cannot cure this ({stuck[0].rule}, owner: {stuck[0].who}), so window 2 is "
                          "not started over the table and window 1 is not run again. Way on: the conductor (P22).", dispatch="")
        if any(f.rule == "R5" or (f.rule == "R0" and f.who == "driver") for f in standing):
            self.s3_prepare()
        return f"{standing[0].rule}: {' '.join(standing[0].text.split())[:160]}"

    def s3_between_windows(self) -> None:
        """The slot between the windows (G2-2): the measures are written afresh over the table as it is now (`grounding_table.py --share`),
        the questions the strategist wrote on grounding rows join the question register (`claim_projector.project_row_questions`), then
        the two stops are judged (`grounding_stop`: coverage first). POSITION: after step 8 and before window 2 - the stop is never asked
        over a table step 8 would send back to window 1, and window 2 never starts over a stop nobody has answered. A measure or a
        projection the code cannot make is a refusal to the conductor, never a silent pass (FR-59)."""
        import claim_projector as CP
        code, out = self.py("grounding_table.py", "--share", "--task", self.task)
        if code:
            raise Refusal(f"S3: grounding_table.py --share exited {code} ({next((ln.strip() for ln in str(out).splitlines() if ln.strip()), 'no output')[:200]}), "
                          "so the coverage of the requirements cannot be judged and window 2 did not start. Way on: the conductor repairs "
                          "the table or the register (P22).", dispatch="")
        result = CP.project_row_questions(self.task_root)
        if result.problems:
            raise Refusal("S3 questions of the grounding table (claim_projector.py): " + "\n".join(f"- {p}" for p in result.problems),
                          dispatch=getattr(self, "last_dispatch", "") or "", retry=None)
        self.grounding_stop()

    GROUNDING_NAMED_MAX = 12                  # requirements a stop question names; the rest is a count

    def _stop_requirements(self, rows: list) -> list:
        """The lines that name requirements in a stop question: the register's own statement of each, in the person's words (no table
        field names), at most `GROUNDING_NAMED_MAX`."""
        import grounding_table as GT
        texts = GT.register_info(self.task_root).texts
        lines = [f"- {o['r']}: {' '.join(str(texts.get(o['r']) or 'no statement in the register').split())[:160]}" for o in rows[:self.GROUNDING_NAMED_MAX]]
        return lines + ([f"- and {len(rows) - self.GROUNDING_NAMED_MAX} more"] if len(rows) > self.GROUNDING_NAMED_MAX else [])

    def grounding_stop(self) -> None:
        """The two stops before window 2 (G2-2): requirement coverage FIRST, then the refactoring share. A stop with a person's word for
        its exact present digest (`grounding_table.stop_word`: the ONE reader) passes; one without is raised as a seam question
        (`_coverage_person`, `_refactoring_person`) and the refactoring one is asked only when coverage passed. A road the code cannot
        measure (`unknown`) is a refusal to the conductor, never a card for the person (FR-3) and never a pass (FR-59)."""
        import grounding_table as GT
        cov = GT.coverage_of(self.task_root)
        if cov["road"] == "unknown":
            raise Refusal(f"S3: the requirement coverage cannot be measured ({cov.get('reason') or 'no reason given'}), so window 2 did not start. "
                          "Way on: the conductor repairs the table, the register or the policy (P22).", dispatch="")
        if cov["road"] == "stop":
            digest = GT.coverage_digest(self.task_root, cov)
            if GT.stop_word(self.pipeline(), GT.COVERAGE_STOP_BLOCK, digest) is None:
                # remains: the coverage stop is a seam question (priced, `offered`): go on / stop have the seam's executors, other words go to the seam
                raise self._coverage_person(cov, digest)
        result = GT.share_of(self.task_root)
        if result["road"] == "unknown":
            raise Refusal(f"S3: the refactoring share cannot be measured ({result.get('reason') or 'no reason given'}), so window 2 did not start. "
                          "Way on: the conductor repairs the table or the policy (P22).", dispatch="")
        if result["road"] == "stop":
            digest = GT.refactoring_digest(self.task_root, result)
            if GT.stop_word(self.pipeline(), GT.REFACTORING_STOP_BLOCK, digest) is None:
                # remains: the refactoring stop is a seam question (priced, `offered`): go on / stop have the seam's executors, other words go to the seam
                raise self._refactoring_person(result, digest)

    GROUNDING_STOP_OPTION = {"answer": "stop", "token": "stop", "slots": {"what": "decide what the change is to do about these requirements"},
                             "says": "stop the story here; nothing runs. You can also tell me in your own words what to do instead, for "
                                     "example that this is the wrong merge request"}

    def _coverage_person(self, cov: dict, digest: str) -> "Person":
        """The coverage stop as a closed question: the requirements the change does not meet (`not implemented`, `outside the diff`
        with no place, absent from the table) and, as a paragraph of their own, those the factory could not establish (`unknown`)."""
        import grounding_table as GT
        import planning_contract as PC
        policy = (PC.grounding_policy()[0] or {}).get("coverage_stop_below_percent", "the configured")
        known = [o for o in cov.get("outside") or [] if o.get("state") != "unknown"]
        unknown = [o for o in cov.get("outside") or [] if o.get("state") == "unknown"]
        covered = cov["implemented"] + cov["partial"]
        if cov.get("reading") == "nothing_asked":
            lead = ("This merge request asks nothing of the story: every requirement is either left to the implementation itself or met "
                    "somewhere else, so there is nothing for the change to be checked against. Before the plan is written I need your word.")
        elif unknown and not known:   # F-5: nothing is known to be missing; the count of the numerator is not a statement about the change
            lead = (f"I could not establish whether the change implements these {len(unknown)} requirements of the story, so I cannot tell how much of "
                    f"it the change covers; {policy}% is the mark from which I go on by myself.\n\nI could not establish whether the change implements:\n"
                    + "\n".join(self._stop_requirements(unknown)) + "\nThe questions about them reach you at gate A.")
        else:
            lead = (f"The change implements {covered} of {cov['n']} requirements of the story ({cov['percent']}%), under the {policy}% "
                    "from which I go on by myself.")
            if known:
                lead += "\n\nThe change does not implement:\n" + "\n".join(self._stop_requirements(known))
            if unknown:
                lead += ("\n\nI could not establish whether the change implements:\n" + "\n".join(self._stop_requirements(unknown))
                         + ("\nThe questions about them reach you at gate A." if not known else ""))
        lead += "\n\nWhat I need from you is one of these:"
        go_on = {"answer": "go on", "token": "go on",
                 "says": "go on and write the plan anyway; the report carries these requirements as they stand, in your words"}
        options = [go_on, dict(self.GROUNDING_STOP_OPTION)]
        block = f"{GT.COVERAGE_STOP_BLOCK} {digest}"
        details = "The requirements outside the count: " + (", ".join(f"{o['r']} ({o['state']})" for o in cov.get("outside") or []) or "none")
        if cov.get("reading") == "nothing_asked":
            return self.site_seam_person("grounding_stop", self.closed_question("s3.grounding_coverage.nothing_asked", lead, options), "S3",
                                         block=block, details=details)
        if unknown and not known:
            return self.site_seam_person("grounding_stop", self.closed_question("s3.grounding_coverage.not_known", lead, options), "S3",
                                         block=block, details=details)
        return self.site_seam_person("grounding_stop", self.closed_question("s3.grounding_coverage", lead, options), "S3",
                                     block=block, details=details)

    def _refactoring_person(self, result: dict, digest: str) -> "Person":
        """The refactoring stop as a closed question: how much of the changed production code the table calls refactoring."""
        import grounding_table as GT
        import planning_contract as PC
        policy = (PC.grounding_policy()[0] or {}).get("stop_above_percent", "the configured")
        lead = (f"{result['percent']}% of the changed production lines ({result['refactoring']} of {result['total']}) are refactoring, "
                f"past the {policy}% from which I go on by myself. A change that mostly moves code gives the plan little to check "
                "against the story.\n\nWhat I need from you is one of these:")
        options = [{"answer": "go on", "token": "go on", "says": "go on and write the plan anyway; the report says the moved code is not checked beyond the plan"},
                   dict(self.GROUNDING_STOP_OPTION)]
        return self.site_seam_person("grounding_stop", self.closed_question("s3.grounding_refactoring", lead, options), "S3",
                                     block=f"{GT.REFACTORING_STOP_BLOCK} {digest}",
                                     details=f"Refactoring lines: {result['refactoring']}; changed production lines: {result['total']}")

    def s3_window_completion(self, record):
        """The completion of an S3 strategist dispatch, decided in ONE place for the live road, the recovery road and the ticket rework
        (I3). `record`: the controller record or `{"window": ...}`. Window 1 (labelling) is accepted OPEN with `plan_pending`; a window
        that closes S3 projects the claims first. An `old` dispatch - the diff world, no `work/grounding.yaml`, no word on the record
        (started one-window before this node, finished after it) - closes as it always did (None)."""
        import grounding_table as GT
        record = record if isinstance(record, dict) else {}
        if self.s3_labelling_of(record):
            def window_one(digest):
                self.s3_project()
                return OpenWork("plan_pending", open_work_reason(
                    "window 1 (labelling) is accepted; the plan is written by window 2 over work/grounding.yaml", "…"))
            return window_one
        try:
            old = GT.source_state(self.task_root)[0] == "diff" and not (self.task_root / "work" / "grounding.yaml").is_file()
        except Exception:
            old = False
        if old:
            # RN1-2 (B-5b): the plan is stamped on this road too - the role writes no mark any more, and an `old` dispatch closes
            # S3 with nothing else that would. No claims here (there is no grounding table); the closing outcome stays None.
            def closing_old(digest):
                self.s3_project(claims=False)
                return None
            return closing_old

        def closing(digest):
            self.s3_project()
            self.py("grounding_table.py", "--share", "--task", self.task, check=True)      # the saved measures follow the bytes the role left (R3)
            return None
        return closing

    def stage_S4(self) -> None:
        self.stages()
        state = self.controller_state()
        accepted = [d for d in (state.get("dispatches") or {}).values() if d.get("stage") == "S4" and d.get("status") == "accepted"]
        if not any(d.get("role") == "qa-case-designer" for d in accepted):
            self.run_role("S4", "qa-case-designer", extra=self.role_lines("S4", "qa-case-designer"))
        self.pin_cases()
        self.revise_plan()
        scope = self.critic_scope()
        # The rounds already spent are the controller's count from the journal, not a local number
        # (B-007); a budget nobody can read closes the stage's review without a round.
        budget = self.budget_or_none("S4", "qa-case-designer", scope)
        counted, cap = (budget or {}).get("counted"), (budget or {}).get("cap")
        last_round = not (isinstance(counted, int) and isinstance(cap, int) and counted < cap)

        # t-919 F-1: a critic accepted with `cases_in_repair` whose repair round nobody registered (its finish went through the
        # recovery road or a refused-then-continued finish, not through this method's tail) is owed its round NOW, from the
        # data - the shape of S7 reading `work/triage.json` - never a new paid critic over the same cases. Needs the findings
        # file and a round left (the very conditions the OpenWork was given under); otherwise the road below, a fresh critic.
        if not last_round and self.s4_findings() and self.s4_repair_owed(state.get("dispatches")):
            print("S4: the case critic was accepted with cases sent back and no repair round is registered; the round starts now, "
                  "no new critic")
            return self.s4_after_critic("concerns", scope, counted, cap, last_round)
        # the critic's finish closes S4 unless its verdict sends cases back and a round is left (`s4_critic_completion`: the one
        # rule of the live stage and of the recovery road, `completion_for`)
        digest, _next = self.run_role("S4", "qa-case-critic", scope=scope,
                                      complete=self.s4_critic_completion(scope, counted, cap),
                                      extra=["Review only the pinned versions; your roll-call names every case in scope."])
        self.s4_after_critic(self.case_verdict(digest), scope, counted, cap, last_round)

    @staticmethod
    def stage_repair_owed(dispatches, stage: str, author: str, critic: str, word: str) -> bool:
        """True when the NEWEST dispatch of the stage critic in `stage` is accepted with the open-work word `word` and no dispatch of
        `author` (a registered rework, whatever its state) follows it - a repair round the critic's finish promised and nobody
        registered. Read from the controller's dispatch records, in their creation order; a record whose `unresolved` is absent or
        of another word, or a state that is no mapping, is "not owed" (the road below is a fresh critic: costly, never a silent
        close of the stage). ONE rule for S2, S3 and S4 (X2-7)."""
        rows = [d for d in (dispatches.values() if isinstance(dispatches, dict) else []) if isinstance(d, dict) and d.get("stage") == stage]
        critics = [i for i, d in enumerate(rows) if d.get("role") == critic]
        if not critics:
            return False
        last = rows[critics[-1]]
        return (last.get("status") == "accepted" and word in json.dumps(last.get("unresolved"))
                and not any(d.get("role") == author for d in rows[critics[-1] + 1:]))

    @staticmethod
    def s4_repair_owed(dispatches) -> bool:
        """The S4 reading of `stage_repair_owed` (word `cases_in_repair`): a repair round the case critic's finish promised and nobody
        registered."""
        return DriverStagePlan.stage_repair_owed(dispatches, "S4", "qa-case-designer", "qa-case-critic", "cases_in_repair")

    # --- X2-7: the stage critic's route for S2 and S3 (queue: X2-7 -> X6-1, the map of the driver moves it) ----------------------

    def stage_acceptor(self, stage: str) -> str:
        """The role that accepts `stage` by meaning (`acceptance_by` in references/stages.json), or "" when the stage has none."""
        return str((self.stages().get(stage) or {}).get("acceptance_by") or "")

    def stage_S2(self) -> None:
        """S2: the tester, then the stage critic's route. A stage with no acceptor (the world before `acceptance_by`) stays `stage_simple`.
        An accepted author dispatch is not dispatched again (a restart, or the author of a repair round): the route goes straight on."""
        role = self.stages()["S2"]["roles"][0]
        if not self.stage_acceptor("S2"):
            return self.stage_simple("S2")
        accepted = [d for d in (self.controller_state().get("dispatches") or {}).values()
                    if isinstance(d, dict) and d.get("stage") == "S2" and d.get("role") == role and d.get("status") == "accepted"]
        if not accepted:
            self.run_role("S2", role, extra=self.role_lines("S2", role))
        self.stage_critic_route("S2", role)

    def stage_raise_questions(self, stage: str, author: str) -> list:
        """X2-6 on the route (t-1815 F2): the questions of the stage's critic were raised into the register by `stage_acceptance_write`
        (the critic's form is the one that declares `questions[]`; no author contract does), so here the conductor only settles what is
        still open (`settle_role_questions`). Returns the rows that carry a person class."""
        return self.settle_role_questions(stage)

    def stage_critic_route(self, stage: str, author: str) -> None:
        """The route of the stage critic after the author's stop (S2, S3): questions, the ONE repair counter (`budget_or_none`), a round owed
        by an earlier promise, then the critic's dispatch whose finish writes the acceptance record BEFORE the controller accepts it
        (`stage_critic_completion`). A rejected stage goes back to the author in a FRESH context (`rework`, `rework_mode: fresh`) with the
        artifact and the verdict; a budget nobody can read (None) gives no round and the critic still runs once."""
        critic = self.stage_acceptor(stage)
        self.stage_raise_questions(stage, author)
        scope: list = []
        budget = self.budget_or_none(stage, author, scope)
        counted, cap = (budget or {}).get("counted"), (budget or {}).get("cap")
        last_round = not (isinstance(counted, int) and isinstance(cap, int) and counted < cap)
        if not last_round and self.stage_repair_owed(self.controller_state().get("dispatches"), stage, author, critic, "stage_in_repair"):
            print(f"{stage}: the stage critic was accepted with the stage sent back and no repair round is registered; the round starts now, "
                  "no new critic")
            return self.stage_after_critic(stage, author, scope, counted, cap, last_round)
        self.run_role(stage, critic, scope=scope, complete=self.stage_critic_completion(stage, author, scope, counted, cap),
                      extra=[f"You accept or return {stage} by meaning: the author's artifact, its handoff form and "
                             f"work/advice-{stage}.json are in the brief; the verdict is `header.verdict` of your form."])
        self.stage_after_critic(stage, author, scope, counted, cap, last_round)

    def stage_after_critic(self, stage: str, author: str, scope, counted, cap, last_round: bool) -> None:
        """What follows the stage critic's accepted finish: a `reject` record with a round left starts the author's round (fresh context, the
        critic's form as the only extra). An `accept`, or no round left (the conductor already settled it inside `complete`), does nothing."""
        import acceptance
        self.stage_raise_questions(stage, author)        # the critic's questions were raised inside its finish; the conductor settles them now
        record = acceptance.stage_acceptance(self.pipeline(), stage) or {}
        if record.get("verdict") != "reject" or last_round:
            return
        form = self.stage_critic_form(stage)
        self.rework(stage, author, scope, "stage critic: " + str(record.get("quote") or ""), cause="test_defect",
                    extra=[f"Repair round {counted + 1} of {cap}: the stage critic's verdict is in {form}; change only what it names."])

    def stage_critic_form(self, stage: str) -> str:
        """The task-relative handoff form of the newest accepted dispatch of the stage critic of `stage`, or the form of the one running."""
        critic = self.stage_acceptor(stage)
        found = [str(d.get("id")) for d in (self.controller_state().get("dispatches") or {}).values()
                 if isinstance(d, dict) and d.get("stage") == stage and d.get("role") == critic]
        dispatch = found[-1] if found else getattr(self, "last_dispatch", "")
        return f"work/handoffs/{dispatch}.yaml"

    def stage_acceptance_write(self, stage: str, dispatch: str) -> None:
        """THE call of the writer (`stage_done.py --acceptance`, X2-5) for the stage critic's form of `dispatch`; a refusal of the writer is a
        `Refusal` on the standard road. Called inside `complete(digest)`, BEFORE `story_step finish` accepts the critic (E-X2-7d).
        First the critic's own `questions[]` are raised into the register (t-1815 F2; `check=True`: a refused form is a `Refusal` whose text
        names the entries, so no question is lost in silence; a form with no questions raises nothing; idempotent by `raised_from`)."""
        if (self.task_root / "work" / "handoffs" / f"{dispatch}.yaml").is_file():
            self.py("question_register.py", "--task", self.task, "--raise", "--stage", stage, "--asked-by", self.stage_acceptor(stage),
                    "--from-handoff", f"work/handoffs/{dispatch}.yaml", check=True,
                    expect=f"the questions[] of work/handoffs/{dispatch}.yaml raised into the register (none when the form has none)")
        self.py("stage_done.py", "--task", self.task, "--stage", stage, "--acceptance", f"work/handoffs/{dispatch}.yaml", check=True,
                expect=f"the stage acceptance of {stage} recorded in pipeline.json from work/handoffs/{dispatch}.yaml")

    def stage_critic_completion(self, stage: str, author: str, scope, counted, cap, dispatch_id=None):
        """The `complete` callable of the stage critic's finish (S2, S3): write the record, then (a) `accept` closes the stage (None), (b)
        `reject` with a round left keeps it open by `OpenWork("stage_in_repair")` (the controller accepts the pair), (c) `reject` on the last
        round, or a verdict word the table does not know, goes to the conductor (`stage_review_exhausted`) BEFORE the finish. Direction of
        error: never `None` without an `accept` record or a person's word. `dispatch_id` (t-1815 F1): the id of the critic dispatch
        this finish closes. The recovery road (`completion_for`) passes the saved RECORD's id ("" when it carries none: the seam gets the
        reason, never a guess); the live road passes None and `run_role` has set `last_dispatch` just before `finish`."""
        import acceptance
        last_round = not (isinstance(counted, int) and isinstance(cap, int) and counted < cap)

        def complete(digest: str):
            dispatch = str(getattr(self, "last_dispatch", "") or "") if dispatch_id is None else str(dispatch_id or "")
            form = f"work/handoffs/{dispatch}.yaml" if dispatch else ""
            if not dispatch:
                return self.stage_review_exhausted(stage, author, dispatch, None, form, unreadable=True,
                                                   text="the saved result of the stage critic carries no dispatch id, so its form cannot be found")
            if not self.stage_verdict_known(form):
                return self.stage_review_exhausted(stage, author, dispatch, None, form, unreadable=True)
            self.stage_acceptance_write(stage, dispatch)
            record = acceptance.stage_acceptance(self.pipeline(), stage) or {}
            if record.get("verdict") == "accept":
                return None
            quote = str(record.get("quote") or "")
            if not last_round:
                return OpenWork("stage_in_repair", open_work_reason(f"the stage critic sent {stage} back: {quote}", f"… [list: {form}]"))
            return self.stage_review_exhausted(stage, author, dispatch, record, form)
        return complete

    def stage_verdict_known(self, form: str) -> bool:
        """True when the form's `header.verdict` is a word of the acceptance table (`vocabulary.stage_acceptance_verdicts`). Reads only."""
        import acceptance
        import handoff
        try:
            data = handoff.parse((self.task_root / form).read_text(encoding="utf-8")).data
            return bool(acceptance.stage_acceptance_verdict(((data or {}).get("header") or {}).get("verdict")))
        except (OSError, ValueError, AttributeError):
            return False

    def stage_review_exhausted(self, stage: str, author: str, critic_dispatch: str, record, form: str, unreadable: bool = False,
                               text: str = ""):
        """F-X2-7: the stage critic rejected the stage on the last round (or its verdict word is unreadable): the conductor decides, through
        the ONE seam, BEFORE the critic's finish. The moves are the conductor's existing commands: accept with the gap
        (`stage_done.py --acceptance <form> --acceptor driver --verdict accept --quote "<gap>"`), one more round on the person's words
        (`rework --reason`, a cause that is not `test_defect`), or a question to the person with the price of each. Afterwards the facts are
        read: a `driver` accept for this author dispatch -> `None`; a new author dispatch -> `OpenWork`; neither -> the seam's `Person`."""
        import acceptance
        quote = "" if record is None else str(record.get("quote") or "")
        who = acceptance.consumer_of(stage) or "the stage critic"      # FR-37: the acceptor that judged, not always a stage critic (M1)
        text = text or (f"the verdict word of {who} is unreadable" if unreadable else
                        f"{who} rejected {stage} and no repair round is left: {quote}")
        files = ([self.task_root / form] if form else []) + [self.task_root / n for n in (self.stages()[stage].get("outputs") or [])
                                          if isinstance(n, str) and not n.startswith("project:") and (self.task_root / n).is_file()]
        line = f"{acceptance.STAGE_ACCEPTANCE_PHRASE}: {text}"      # F3: the line `waiver.py --block` is verified against
        state = {"why": "stage_review_exhausted", "kind": "conductor", "stage": stage, "dispatch": critic_dispatch, "text": text,
                 "lead": text + f". Decide: accept {stage} with the gap, one more round on words you ground, or ask the person.",
                 "files": [f for f in files if f.is_file()], "lines": [line]}
        # F3 (B-6): a person's `go on` recorded AFTER this critic dispatch started closes the stage with a finding. No journalled start of the
        # critic dispatch (`since == ""`) -> the pass is not consulted at all (the conductor / the person is asked).
        try:
            from controller import Controller, stamp_utc
            since = stamp_utc(Controller(self.task_root)._dispatch_starts().get(critic_dispatch))
        except Exception:  # noqa: BLE001 - a start that cannot be read is the safe side: no pass
            since = ""

        def person_closes(author_dispatch: str) -> bool:
            heard = self.person_pass(stage, author_dispatch, line, since=since) if since and author_dispatch else {}
            if not heard:
                return False
            self.owe_row("project_decisions.py", "--root", str(self.project), "add-finding",
                         "--essence", f"{stage} closed on the person's word over: {line}", "--scope", "local-calibration",
                         "--witness", f"{stage} person's word {str(heard.get('decision') or '')[:200]!r} at {heard.get('at')}",
                         "--idempotency-key", f"stage-review-pass:{self.task}:{stage}:{critic_dispatch}",
                         what="the finding about the stage review you passed", stage=stage)
            return True
        author_last = acceptance.stage_author_dispatch(self.controller_state(), acceptance.stage_def_of(stage))
        if person_closes(author_last):
            return None
        self.no_move(state)
        pipeline = self.pipeline()
        author_last = acceptance.stage_author_dispatch(self.controller_state(), acceptance.stage_def_of(stage))
        if acceptance.accepted_for(pipeline, stage, author_last, acceptor=acceptance.DRIVER_ACCEPTOR):
            return None
        if person_closes(author_last):
            return None
        # M1: «after» is anchored on the acceptor's OWN dispatch among ALL dispatches in creation order (a consumer's dispatch belongs to the
        # next stage, so the stage's own list never held it); with none readable, on the reviewed author dispatch the record names.
        every = [d for d in (self.controller_state().get("dispatches") or {}).values() if isinstance(d, dict)]
        ids = [str(d.get("id")) for d in every]
        anchor = critic_dispatch if critic_dispatch in ids else str((record or {}).get("reviewed_dispatch") or "")
        after = ids[ids.index(anchor) + 1:] if anchor in ids else []
        if any(d.get("stage") == stage and d.get("role") == author and str(d.get("id")) in after for d in every):
            word = "cases_in_repair" if stage == "S4" else "stage_in_repair"       # S4 keeps its own word (s4_repair_owed reads it)
            return OpenWork(word, open_work_reason(f"the conductor sent {stage} back for one more round", f"… [list: {form}]"))
        # The conductor made no move: the SEAM shows the priced fallback question (`call=False`: it was just asked, no second paid call).
        return self.no_move(dict(state, call=False, text=state["text"] + ". The conductor made no move on the exhausted stage review."))

    def s4_after_critic(self, verdict: str, scope, counted, cap, last_round: bool) -> None:
        """What follows the S4 case critic's accepted finish: the roll-call, the designer's repair round (verdict sends cases back,
        a round is left, a findings file exists) or the case appendix. ONE tail for the live road and the owed-round road."""
        if self.stage_acceptor("S4"):
            self.settle_role_questions("S4")         # t-1815 F2: the case critic's questions were raised inside its finish
        findings = self.s4_findings()
        fixes =bool(findings and re.search(r"approve_with_fixes", findings.read_text(encoding="utf-8", errors="replace")))
        # t-261 (O4, t-227): the same command also raises the questions the designer (no Bash) could only name - and it
        # does so with or without a findings file, so a pinned case that still says `raise` is reason enough to run it:
        # a critic who wrote `approve` otherwise left the Then with no question for gate A to show.
        if fixes or self.unraised_cases():
            # remains: R1 (C1-7b) - gate A's entry repair runs the same command when gate_preflight finds `unraised_questions` (GATE_REPAIRS -> `raise_move`, a failure -> `RepairFailed`), so no gate A packet is shown with a question this call could have raised
            self.py("critic_rollcall.py", *([str(findings)] if findings else []), "--apply-fixes",
                    "--task-root", str(self.task_root))
            self.pin_cases()
        if verdict in ("concerns", "review") and not last_round and findings:
            reason = findings.read_text(encoding="utf-8", errors="replace")[:1200]
            self.rework("S4", "qa-case-designer", scope, "critic round: " + reason, cause="test_defect",
                        extra=[f"Repair round {counted + 1} of {cap}: the critic's findings are in "
                               f"{findings.relative_to(self.task_root).as_posix()}; change only what they name."])
            self.pin_cases()
            return  # the loop comes back to S4 and dispatches the critic again
        # the stage is closed by the critic's finish; the appendix embeds the pinned cases
        self.render_appendix()

    @staticmethod
    def case_verdict(text: str) -> str:
        import role_digest
        return (role_digest.parse(text).get("header") or {}).get("verdict", "")

    def s4_findings(self) -> Path | None:
        """The case critic's findings file the S4 repair round reads (the newest `critic-findings*.md` under
        `work/test-cases/`), or None. Never the S5 files `work/test-code/critic-findings-*.md` (AR-13, AR-22)."""
        import findings_path
        return self.newest(findings_path.S4_PATTERN)      # through `self.newest`: the slow story tests stand in for it

    def s4_critic_completion(self, scope, counted, cap, dispatch_id=None):
        """The `complete` callable of the S4 case critic's finish - the live stage and `completion_for` (the recovery road) call
        THIS one rule (t-909 F-4; the shape of `s7_open_work`).

        `None` (the critic's finish closes S4) unless its verdict sends cases back AND a round is left. Then, by the rule of
        `stage_S4`'s rework branch: with a findings file the round WILL run, so the finish says it by `OpenWork` (`--not-complete
        --unresolved --reason`, a pair the controller accepts - no silent `False`, no resume of the critic for a record the driver
        owns, C2-4 K9-4). POSITION INVARIANT (t-909 F-3): `OpenWork` only when that branch runs; with no findings file the
        old `False` stays - one resume of the critic, who writes the findings (judgement).

        INVARIANT, on ANY road (t-919 F-1): an accepted `cases_in_repair` is never followed by a NEW paid critic over unchanged
        cases. The round is registered by `stage_S4`'s tail on the live road; on the recovery road (`_finish_saved_result`,
        `resume_role`) and after a refused finish that came back as `continue` no tail ran, so the next `stage_S4` entry derives
        the owed round from the dispatch records (`s4_repair_owed`) and starts it instead of a critic."""
        last_round = not (isinstance(counted, int) and isinstance(cap, int) and counted < cap)

        def complete(digest: str):
            # X2-7 (a): the acceptance record is written FIRST, from the critic's own form, before the controller accepts the critic (E-X2-7d)
            dispatch = str(getattr(self, "last_dispatch", "") or "") if dispatch_id is None else str(dispatch_id or "")      # F1, as the S2/S3 rule
            form = f"work/handoffs/{dispatch}.yaml" if dispatch else ""
            if self.stage_acceptor("S4"):
                if not dispatch:
                    return self.stage_review_exhausted("S4", "qa-case-designer", dispatch, None, form, unreadable=True,
                                                       text="the saved result of the S4 case critic carries no dispatch id, so its form cannot be found")
                if not self.stage_verdict_known(form):
                    return self.stage_review_exhausted("S4", "qa-case-designer", dispatch, None, form, unreadable=True)
                self.stage_acceptance_write("S4", dispatch)
            if self.case_verdict(digest) not in ("concerns", "review"):
                return None
            if last_round:
                # X2-7 point 7, the ONE changed line of S4: a critic that sends cases back on the last round no longer closes the stage in
                # silence - the conductor decides through the seam (accept with the gap / one more round / ask the person), F-X2-7
                if not self.stage_acceptor("S4"):
                    return None
                import acceptance
                return self.stage_review_exhausted("S4", "qa-case-designer", dispatch,
                                                   acceptance.stage_acceptance(self.pipeline(), "S4") or {}, form)
            findings = self.s4_findings()
            if not findings:
                return False
            import role_digest
            # the cases the critic REJECTED, by the closed state word of its own rows - not its whole scope (t-919 F-3); an
            # unreadable set prints no number (FR-41)
            cases = [str(r["id"]) for r in role_digest.parse(digest).get("rows") or []
                     if str(r.get("state") or "").split(":")[0] == "rejected"]
            lead = (f"the case critic sent {len(cases)} case(s) back for repair" if cases else "the case critic sent work back for repair")
            path = findings.relative_to(self.task_root).as_posix()
            text = (lead + "; S4 was kept open for the repair round" + (": " + ", ".join(cases) if cases else "")
                    + f"; its findings: {path}")
            return OpenWork("cases_in_repair", open_work_reason(text, f"… [list: {path}]"))
        return complete

    def render_appendix(self) -> None:
        """`render_case_appendix.py`: the case appendix, from the pinned cases. S4's last step, and (t-211,
        C10) the gate-entry step that runs it when the critic's refused finish skipped it.
        G2 (C1-7b): a non-zero exit is a `Refusal` (the factory's own, `known = False`): on the normal path nothing runs this again
        (`gate_entry_steps` only when `gate_entry_owed`), and gate A's packet embeds the appendix. The conductor can rerun it (`retry`)."""
        self.py("render_case_appendix.py", "--task-root", str(self.task_root), "--output",
                str(self.task_root / "work/case-appendix.md"), "--plan", str(self.task_root / "test-plan.md"), check=True,
                expect="work/case-appendix.md rendered from the pinned cases")

    def pin_cases(self) -> None:
        _code, out = self.py("case_versions.py", "--task-root", str(self.task_root), "--all", check=True)
        # HF8-6: `--all` records the approved scope itself; what it could not record it says in `scope_note`. Only printed here:
        # the sites that call `revise_plan()` next get the controller's own refusal, the others (a repair round) leave the
        # judging to the critic's start and gate A.
        # `py` joins stdout and stderr, so a stderr line may come last: take the last line that parses as an object.
        note = ""
        for line in reversed(out.strip().splitlines()):
            try:
                answer = json.loads(line)
            except ValueError:
                continue
            if isinstance(answer, dict):
                note = str(answer.get("scope_note") or "")
                break
        if note:
            print("S4: " + note)
        self.py("case_versions.py", "--task-root", str(self.task_root), "--verify", check=True)

    def pinned_cases(self) -> list:
        """The case ids that are pinned: the controller's own reading (`_pinned_links`: a link with a case id AND a version),
        so the driver never sends the critic or a dispatch a case the controller does not count as pinned (CX2-17, AR-13)."""
        from controller import Controller
        return sorted({str(link["case_id"]) for link in Controller(self.task_root)._pinned_links()})

    def unraised_cases(self) -> list:
        """The case files that still hold a Then `unknown` with the ref `raise` (the question was named, never raised).

        Read from the structured `then_oracles` field through `contract` - the reader `gate_preflight.
        check_unraised_questions` uses - never by a phrase (FR-12). [] when nothing says so or the cases cannot be read:
        a reader that cannot read says nothing (P1) and the rehearsal at gate A names what is left."""
        try:
            import contract
            found = []
            for path in contract.case_files(self.task_root):
                entries, _why = contract.then_oracles_from_text(Path(path).read_text(encoding="utf-8", errors="replace"))
                if any(isinstance(e, dict) and str(e.get("ref") or "").strip() == contract.RAISE_REF for e in entries or []):
                    found.append(Path(path).stem)
            return found
        except Exception:
            return []

    def critic_scope(self) -> list:
        """Cases of the plan rows that require independent design review; all pinned cases
        when the plan names none (a critic with no scope reviews whatever it reads)."""
        import case_versions
        return case_versions.review_scope(self.task_root, state=self.controller_state(), pinned=self.pinned_cases())

    def revise_plan(self) -> None:
        """Record the pinned cases as the approved scope, unless the controller already holds exactly them (CX1-11).

        HF8-6: the request is built by `case_versions.scope_request`, the one function `case_versions.py --all` calls too,
        so `--all` has usually recorded the scope already and this call is then a no-op; it stays the stage's own step so a
        failed record is the controller's `Refusal` here (the sites that only pin print the note instead).

        The controller writes the scope in the spelling the case index keys (`TC-001`, `<area>/TC-003` for a number two
        areas hold), so "already holds them" is a comparison of KEYS, by the controller's own rule (`_scope_membership`,
        which reads `_pinned_links`: ONE filter of "pinned", D-2). The idempotency key is the story's REVISION plus the
        scope's KEYS (`content_hash`, N-5; the payload carries the bare ids, the key hashes the keys they resolve to): a
        count replayed an area dropped at the same number, and a content hash alone replayed A -> B -> A (the store
        holds B, the third call returned the first event). An index that cannot be built counts as "not equal" (N-6):
        the bare ids go to the controller, which refuses with its own words (`Refusal`, never a crash of the driver)."""
        import case_versions
        notes: list = []
        request = case_versions.scope_request(self.task_root, notes=notes)    # the one builder; `--all` calls the same (HF8-6)
        for note in notes:
            print("S4: " + note)
        if request is None:
            return
        # CX2-17 C-2 (E43a): the driver takes the orchestrator lease itself at a rollover (`session = driver:<task>:<revision>`) and
        # `Driver.controller` adds no owner, so after a rollover the controller refused this request for a lease it had just
        # handed the driver. The owner is read from the record, as `handoff` does at the rollover (one line, no new method)
        owner = ((self.controller_state().get("leases") or {}).get("orchestrator") or {}).get("owner_session_id")
        self.controller("revise_plan", input_data=dict(request, owner_session_id=owner) if owner else request)

    def settle_role_questions(self, stage: str) -> list:
        """X2-6 (E-B6, E-B7): the questions the roles of `stage` raised into the register (`question_register.py --raise --from-handoff`,
        rows with `asked_by`) that nobody has answered. Each is given to the conductor through the seam (P22) with the paths the role read; a
        question whose answer lies on disk is CLOSED by the conductor with `question_register.py --answer ... --by driver --where "stage ran"`
        and the source (`<path>#<anchor>: <the answer>`) in the words - never sent to a person. WHETHER the answer is on disk is the
        conductor's judgment: this method closes nothing itself. Returns the rows still open that carry a `why_person` class: only those
        reach a person, batched at the next gate (gate A, gate B), and the role goes on by its `recommendation` meanwhile. A row left open
        with no class is printed as a gap and is NOT returned: a question with no class never reaches a person. Nothing open: `[]`, no call."""
        import question_register as QR

        def mine() -> list:
            return [q for q in QR.load(self.task_root)["questions"]
                    if q.get("asked_by") and q.get("stage") == stage and QR.is_open(q) and q.get("status") != "with_designer"]

        waiting = mine()
        if not waiting:
            return []
        shown, files = [], []
        for q in waiting:
            shown.append(f"- {q['id']} (asked by {q['asked_by']}, class: {q.get('why_person') or 'none'}; row_hash {q.get('row_hash')}): "
                         f"{q.get('question')}\n  read: {', '.join(q.get('read') or []) or 'nothing named'}\n"
                         f"  the role goes on with: {q.get('recommendation') or 'nothing stated'}\n  answers: "
                         + "; ".join(f"{QR.LETTERS[i]}) {r.get('reading')}" for i, r in enumerate(q.get("readings") or []) if isinstance(r, dict)))
            for ref in q.get("read") or []:
                for base in (self.task_root, self.project):
                    candidate = base / str(ref).split("#", 1)[0]
                    if candidate.is_file():
                        files.append(candidate)
                        break
        lead = (f"Questions the roles of {stage} raised while they worked. For each: read the paths it names; if the answer is THERE, close it "
                "now with `question_register.py --task " + self.task + " --answer <id> --reading <letter> --by driver --where \"stage ran\" "
                "--register-hash <its row_hash> --words \"<path>#<anchor>: <the answer you found>\"` (the words name the source). Close nothing "
                "you cannot ground in a file. A question that stays open goes to the person only when it has a class (`why_person`), at the "
                "next gate; ask the person now only for `access`. The role's work does not wait.\n\n" + "\n".join(shown))
        self.no_move({"why": "refusal", "kind": "conductor", "stage": stage, "dispatch": "", "text": lead, "lead": lead, "files": files})
        left = mine()
        for q in left:
            if not q.get("why_person"):
                print(f"role question {q['id']} ({stage}, {q['asked_by']}) has no person class and no answer on disk: left as a gap, not asked")
        return [q for q in left if q.get("why_person")]

    def ticket_rerun_critic(self, dispatch: str) -> None:
        """The restart route of a ticket re-run of S2/S3 (AR-25, AR-28): the stage has an acceptor, so the author's re-run no longer closes
        it (`completion_for` answers None) and the stage stays `completed` from its first run - nothing would ever enter its critic route
        again, and the re-run would go unreviewed. When the dispatch just finished is that author's accepted `ticket_changed` re-run, the
        stage critic's route runs now and its verdict closes (`stage_critic_completion`). A dispatch still running, another cause, the
        critic's own dispatch or a stage without an acceptor does nothing. Runs AFTER the finish, never before: the critic reads the accepted re-run."""
        record = (self.controller_state().get("dispatches") or {}).get(dispatch) or {}
        stage, role = str(record.get("stage") or ""), str(record.get("role") or "")
        if (record.get("status") != "accepted" or record.get("repair_cause") != "ticket_changed" or stage not in ("S2", "S3")
                or not self.stage_acceptor(stage) or role == self.stage_acceptor(stage)):
            return
        rows = [d for d in (self.controller_state().get("dispatches") or {}).values() if isinstance(d, dict) and d.get("stage") == stage]
        ids = [str(d.get("id")) for d in rows]
        if dispatch in ids and any(d.get("role") == self.stage_acceptor(stage) for d in rows[ids.index(dispatch) + 1:]):
            return          # the critic of this re-run is registered already (a retry that came back here): never a second one
        self.stage_critic_route(stage, role)

    def s3_record_lines(self, stage: str, role: str, record: dict) -> list:
        """The window lines of an S3 strategist dispatch finished through a recovery branch (the lines the live road gave it); other
        roles get none, as before - except an S7 INVESTIGATION dispatch (P2 M3), which gets the lines of its live road (its targets, caps and
        form note)."""
        import controller as CT
        if (stage, role) == ("S3", "qa-test-strategist") or ((stage, role) == ("S7", "qa-failure-analyst")
                                                             and CT.s7_part_of(record) == "investigation"):
            return self.role_lines(stage, role, record)
        return []

    def s3_check_packet(self, request: dict) -> None:
        """Before the controller's S3 strategist packet is dispatched again (G1-11): a labelling packet prepares the table; a window-2 packet
        (diff world, a table on disk) is held to step 8. A window-2 packet over a table step 8 would send back to window 1 is refused to the
        conductor with `release` as the door (the packet is fixed; window 1 is the driver's next move once it is released)."""
        import controller as CT
        import grounding_table as GT
        import launch_card
        if request.get("purpose") == CT.S3_LABELLING:
            self.s3_prepare()
            return
        if request.get("purpose") == "repair_verify":
            return
        if GT.source_state(self.task_root)[0] != "diff" or not (self.task_root / "work" / "grounding.yaml").is_file():
            return                          # off the diff, or a story that never had a table: nothing to hold the packet to
        back = self.s3_fresh_for_window2()
        if back:
            raise Refusal(f"S3: the window-2 packet {request.get('id')} was never launched, and the table it would plan over is no longer "
                          f"current ({back}). The packet is fixed, so it is not dispatched. Way on: the conductor releases the packet "
                          f"({launch_card.release_door(self.task_root, request.get('id'))}); the driver then runs window 1 again (P22).",
                          dispatch="")
        self.s3_between_windows()           # the same slot `stage_S3` runs: a packet over an unanswered stop does not go out (G2-2, AR-19)

    def completion_for(self, stage: str, role: str, record: dict):
        if stage == "S8" and role == "qa-doc-scribe":
            return True
        if stage == "S1" and role == "qa-runner" and (record.get("request_binding") or {}).get("purpose") == "reference_walk":
            # t-2181 PC-9b (critic t-2513 F2, axis 5): the S1 reference window closes the stage - the live road (`stage_simple`) finishes the
            # runner with `complete=True`; the recovery roads (`wait_existing_job`, `resume_role`) get the same answer here, or "the stage's
            # last role closes it" would make the scout the last role and leave S1 open for a SECOND window. POSITION: before every rule below
            return True
        if stage == "S1" and self.s1_window_owed(stage, role):
            # t-2277 batch 2b D (critic t-2548 F2): the S1 scout of a story with a reference does NOT close S1 on any road that finishes it -
            # a relaunch with no `rework_of`, the no-packet fallback, `wait_existing_job` over a saved result, `resume_role`: S1 stays open and
            # the next `where` -> `stage_simple` skips the accepted scout and runs the window (its `complete=True` closes S1). POSITION: after the
            # runner's own rule above (the window closes the stage), before every other rule. A story with no reference gets None here: unchanged
            return False
        if stage in ("S2", "S3") and record.get("repair_cause") == "ticket_changed":
            # B-364 (F12 / Change 10): the ticket re-run of S2 and S3 closes as COMPLETE, which re-captures the plan baseline.
            # Finished through `wait_existing_job` (the restart route) it must say so too: the `rework_of` rule at the end
            # answers False for every rework, and S3's baseline would stay the old plan's - the re-run's changes would later
            # count as the person's overrides. Placed before that rule; nothing else of the order changes.
            # S3 (G1-11) closes through the same callable as the live road (`s3_ticket_completion`: project, refresh, True).
            # X2-7: with an acceptor (`acceptance_by`) the author no longer closes the stage - the stage critic's accept does; the plan
            # baseline is then taken by that closing accept (B-364), and the side steps of S3 stay on the author's finish.
            if self.stage_acceptor(stage):
                return self.s3_ticket_completion(closes=False) if stage == "S3" else None
            return self.s3_ticket_completion() if stage == "S3" else True
        if stage in ("S2", "S3") and role == self.stage_acceptor(stage):
            # X2-7: the recovery road closes S2/S3 by the SAME rule the live route applies (`stage_critic_completion`), the budget read again.
            # POSITION INVARIANT: after the `ticket_changed` branch, BEFORE the `rework_of` rule below (whose silent False would leave the
            # critic's finish refused by the controller for a record the driver owns).
            budget = self.budget_or_none(stage, self.stages()[stage]["roles"][0], []) or {}
            # t-1815 F1: the dispatch is the RECORD's (a fresh process never ran `run_role`, `last_dispatch` is empty or another role's)
            return self.stage_critic_completion(stage, self.stages()[stage]["roles"][0], [], budget.get("counted"), budget.get("cap"),
                                                dispatch_id=str(record.get("id") or ""))
        if stage == "S6" and role == "qa-runner" and str(record.get("id") or getattr(self, "last_dispatch", "")) in {
                str(x) for ids in (self.state.get("s7_rejudge") or {}).values() if isinstance(ids, list) for x in ids}:
            # HF8-19 (t-909 F-4 class): an S7 RE-JUDGE dispatch finished through `wait_existing_job` closes like the live road
            # (`s7_rejudge_round`: `complete=False`). POSITION INVARIANT: BEFORE the S6 qa-runner rule below, which answers `True`
            # for a manual dispatch when no block is left to run - a re-judge writes no S6 completion and is not "the last block".
            return False
        if stage == "S6" and role == "qa-runner":
            # t-261 (C4, the same recovery class as S5 below): a saved result finished through `wait_existing_job` got no
            # answer here, so it took the controller's default and closed S6 over a half nobody had run. The rule is the
            # one `stage_S6` applies when it dispatches: the automation runner closes the stage only when no manual half
            # is left; a manual block closes it only when no other case could still be dispatched. A refused case stops
            # the close only WITHOUT a consumer (the controller refuses a completion over a case no accepted dispatch
            # carried); under a consumer the stage awaits it and manual_close closes the refused case later (X7-6).
            try:
                scope = self.stage_scope("S6", "manual").get("scope") or []
                if record.get("execution_kind") == "manual":
                    mine = [str(c) for c in record.get("manual_case_ids") or record.get("scope") or []]
                    if self.walk_pending(mine):
                        # t-2022 N5: the SAME guard the live road has (`run_manual_block`: `walk_pending(block)`): a case of this lane whose walk
                        # record the build refused is walked once more or closed `left_unchecked`, and the lane that carried it never closes the
                        # stage. POSITION INVARIANT: BEFORE `manual_plan(skip=mine)`, which skips the lane's own cases and so cannot see them
                        return False
                    plan = self.manual_plan(scope, skip=mine)
                    # X7-6: with a consumer the last block stops AWAITING the acceptance (as the live `run_manual_block` does)
                    # t-2239 B1 (X7-6): a refused case does not keep the last block from awaiting; `manual_close` closes it later
                    import acceptance
                    return self.consumer_awaits("S6", not plan["blocks"] and (True if acceptance.consumer_of("S6") else not plan["refused"]))
                return self.consumer_awaits("S6", not scope)
            except Exception:
                return False       # a doubt never closes a stage
        if stage == "S5":
            # The critic of the LAST window closes S5 - the same rule stage_S5 applies when it
            # dispatches. On the recovery path (a saved result finished through
            # `wait_existing_job`) this returned False for every dispatch, so every window was
            # accepted and the stage stayed open forever (TP1-13797, driver run 3).
            if role != "qa-code-critic":
                return False
            try:
                windows = self.stage_scope("S5").get("windows") or []
            except Exception:
                return False
            mine = set(record.get("scope") or [])
            if self.s5_parallel_cap() != 1:
                # TR3-6: other windows through `s5_open_windows` (a running dispatch, an owed round or a live chain keep a window open as
                # well as a missing acceptance); unreadable is open, never a close (FR-59). `mine == scope` is still skipped there.
                try:
                    if self.s5_open_windows(excluding=mine):
                        return False
                except Exception:       # noqa: BLE001
                    return False
            else:
                for window in windows:
                    if set(window.get("scope") or []) == mine:
                        continue
                    if "qa-code-critic" not in (window.get("accepted_by") or {}):
                        return False
            # t-698 A4/L6: the last critic closes S5 only by the SAME rule the loop applies - the route of ITS review (read after the
            # role wrote the form: `finish` evaluates the callable) and the person's answer for THIS critic dispatch.
            cases, dispatch = list(record.get("scope") or []), str(record.get("id") or getattr(self, "last_dispatch", ""))

            def closes(digest: str) -> bool:
                route, _form = self.route_of(digest, self.budget_or_none("S5", "qa-automator", cases, ref=dispatch), dispatch)
                return self.s5_window_closed(route, self.repair_answer(cases, dispatch))
            return closes
        if stage == "S4" and role == "qa-case-critic":
            # C2-4 (t-909 F-4): the recovery road closes S4 by the SAME rule the live stage applies (`s4_critic_completion`). POSITION
            # INVARIANT: BEFORE the `rework_of` rule below, as S7's: a saved critic result finished through `wait_existing_job`
            # must not close S4 over `concerns` with a round left, nor leave a silent `False` for the controller to refuse.
            cases = [str(c) for c in record.get("scope") or []]
            budget = self.budget_or_none("S4", "qa-case-designer", cases) or {}
            return self.s4_critic_completion(cases, budget.get("counted"), budget.get("cap"), dispatch_id=str(record.get("id") or ""))
        import controller as CT
        if stage == "S7" and role == "qa-failure-analyst" and CT.s7_part_of(record) == "investigation":
            # P2 M3. POSITION INVARIANT: BEFORE the S7 branch below (whose callable runs `s7_open_work` and could close S7 over a running
            # pass) and so before the `rework_of` rule: a saved / interrupted / never-launched / resumed / relaunched investigation never
            # closes S7. The purpose is read through `s7_part_of(record)` (the record's binding), never `record.get("purpose")`.
            return False
        if stage == "S7" and role == "qa-failure-analyst":
            # t-698 §18 (C1-5b2): S7 stays OPEN while repair rows remain. POSITION INVARIANT: BEFORE the `rework_of` rule below, whose
            # silent False would let a reworked analyst be refused by the controller (or close S7 over rows): no finish of the S7
            # closing role closes S7 while `s7_repair_rows()` is non-empty (or unreadable).
            # X7-6b: with a consumer (the doc scribe) the analyst's finish that WOULD close S7 stops AWAITING its acceptance instead.
            return lambda digest: self.consumer_awaits("S7", self.s7_open_work())
        if (stage == "S3" and role == "qa-test-strategist" and not record.get("rework_of")
                and record.get("purpose") != "repair_verify"):
            # G1-11 (t-909 F-4 class): the recovery road decides an S3 strategist dispatch by the SAME function as the live stage.
            # POSITION INVARIANT: after the `ticket_changed` branch (its own callable) and BEFORE the `rework_of` rule below, whose silent
            # False would make a saved window-1 result close nothing and a window 2 never close S3.
            return self.s3_window_completion(record)
        if record.get("repair_cause") == "question_answer":
            # HF2-7 (N1, H39): a rework the person's recorded answers opened closes by the stage's own rule on this road too - S3 by
            # its one close rule (the projection, outcome None: `s3_window_completion`), S4's designer by no flag (it is not the stage's
            # last role). POSITION INVARIANT: after the `ticket_changed` branch and the S4-critic / S5-S7 branches, BEFORE the `rework_of`
            # rule below, whose silent False would leave S3 with no closing role (the controller refuses that, `controller.py:3899`).
            return self.s3_window_completion(record) if stage == "S3" else None
        if record.get("rework_of") or record.get("purpose") == "repair_verify":
            # RN1-2 (B-1): an S3 strategist rework projects the plan too. POSITION INVARIANT: the answer stays `False` (the callable
            # returns it); only the projection is added, so nothing that closes a stage changes.
            return self.s3_rework_completion() if stage == "S3" and role == "qa-test-strategist" else False
        return None
