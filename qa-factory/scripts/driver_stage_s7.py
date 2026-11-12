"""driver_stage_s7.py - Driver members homed here by ai-packages/qa-factory/scripts/tests/fixtures/driver-layers.json (TD-11 cut by tools/source_split.py); no behaviour of its own."""

import hashlib
import json
import re
from driver_core import OpenWork, Person, Refusal, ReworkRefused, _now, _read_json, open_work_reason


class DriverStageS7:
    def failures_to_triage(self) -> str:
        report = _read_json(self.task_root / "work/run-report.json")
        status = report.get("execution_status")
        if status not in ("passed", "failed"):
            # t-305 N1 (Q19 a): `not_executed` is also what S6 leaves on purpose when it closes on a CODE-ONLY receipt
            # (nothing to execute, or everything handed to a person); S7 reads that report. Without the receipt it is
            # an S6 halt, and the refusal below stands word for word. The receipt is read only on this branch.
            import s7_pretriage
            if not (status == "not_executed" and s7_pretriage.s6_closed_by_code(self.task_root)):
                raise Refusal(f"S7 entry: run-report.json execution_status is `{status}` — nothing to triage yet; "
                              "the S6 halt that produced it stands")
        totals = report.get("current_totals") or report.get("totals") or {}
        reasons = []
        if int(totals.get("failed") or 0):
            reasons.append(f"failed={totals.get('failed')}")
        # t-309: the one definition of a failure that needs triage (contract.triage_targets), shared with the
        # reducer and the S7 handover check - a manual `inconclusive` or `error` is a failure here as there.
        import contract
        targets = contract.triage_targets(report)
        bad = sorted(targets["manual"]) + sorted(targets["unnamed_manual"])
        if bad:
            reasons.append("manual " + ",".join(bad))
        # P26 / RN1-10 (AR-28): a runner's observation, whatever its check's result, wants the analyst's verdict - a green check
        # with an observation dispatches the analyst; a report with none reads exactly as before
        if targets["observations"]:
            reasons.append("manual observations " + ",".join(sorted(targets["observations"])))
        # t-323 C2: a failed RESULT row with no id sits in `unnamed` beside the nameless manual checks, and was worded
        # "manual" with them - a failure of the automated run named as a manual check; it gets its own words
        nameless = sorted(targets["unnamed"] - targets["unnamed_manual"])
        if nameless:
            reasons.append(f"{len(nameless)} failed result row(s) with no id")
        if targets["results"] and not int(totals.get("failed") or 0):
            reasons.append("failed results " + ",".join(sorted(targets["results"])))
        manifest = _read_json(self.task_root / "work/automation-manifest.json")
        if "contradicts_requirement" in json.dumps(manifest.get("unresolved") or []):
            reasons.append("contradicts_requirement rows")
        return "; ".join(reasons)

    def stage_S7(self) -> None:
        state = self.controller_state()
        # P2 M3: an accepted INVESTIGATION is never a triage (case 1: with no triage file `analyst_done` would read True and a
        # re-triage of a story with no failure would start)
        import acceptance
        # X7-6: an analyst dispatch whose finish carried `stage_superseded` (S6's consumer REJECTED the runner's handoff) is stale work on
        # a handoff that was not accepted: it is not a triage, and a new analyst is owed after the runner's repair (E-24, AR-28). An accepted
        # INVESTIGATION is no triage either: `author_dispatches` is the one reading of both (M4 of t-1860).
        analyst_done = any(d.get("status") == "accepted" for d in acceptance.author_dispatches(state, acceptance.stage_def_of("S7")))
        awaiting = acceptance.awaits_acceptance(state, "S6", self.pipeline())      # the runner's last dispatch when S6 awaits its consumer
        if self.s7_closed_by_scribe(state):
            return
        if awaiting:
            if self.consumer_settled("S6", state, awaiting, analyst_done):
                return
        if analyst_done and not self.s7_fresh():
            # t-698 §20 N1 (FRESHNESS): an accepted analyst is only as fresh as the controller's staling, and a person-word rework of an
            # earlier stage does not stale an OPEN S7 (its stamp names completed stages only). A current failure with no row of the
            # triage is triaged again (a new analyst = a new life) and S7 is never closed over it. ONE re-triage per chain: a second
            # consecutive not-fresh triage asks the person through the seam (`s7_retriage_once`), never a third analyst (§22 FX-3).
            self.s7_retriage_once()
            print("S7: a failure of the current run report has no row in work/triage.json; the failure analyst triages again")
            analyst_done = False
        elif analyst_done and self.state.pop("s7_retriage", None):      # a fresh triage ends the chain
            self.save_state()
        if not analyst_done:
            reasons = self.failures_to_triage()
            if not reasons and not awaiting:
                # P2 M3 (the investigation before a close by code). POSITION INVARIANT: after `failures_to_triage` (a halted run raises
                # before any register write) and before the receipt (which hashes the register the pass wrote).
                self.s7_close_places(self.s7_gap_reason("no_failures"))      # t-1991 U3a: BEFORE the gate (a place is never both gaps)
                verdict, suffix = self.s7_investigation_gate()
                if verdict == "wait":
                    return
                register = ["work/exploratory-findings.jsonl"] if (self.task_root / "work" / "exploratory-findings.jsonl").is_file() else []
                self.close_by_code("S7", "no failures — nothing to triage" + suffix,
                                   ["work/run-report.json"] + register, site="s7.no_failures", finalize=False,
                                   tail=[["--event", "dispatch_skipped", "--task", self.task, "--reason", "S7: no failures to triage"]])
                return
            # t-305 N1 (Q23): code decides what the run already recorded BEFORE the analyst is asked (`s7_pretriage`:
            # a manual `inconclusive` whose own record says what stopped it; a red test is never pre-judged). POSITION
            # INVARIANT: after the entry refusal of `failures_to_triage` (a halted run is never triaged, so no row is
            # written over one) and before the analyst's dispatch (an analyst row is never written over, and the analyst
            # is never asked about a failure code answered). It runs on EVERY entry, so a row the analyst dropped is
            # restored; it does not run while an S7 dispatch is in flight (the analyst writes the same file). A pre-triage
            # that cannot run is one printed line and the analyst triages everything, as before (P1).
            import s7_pretriage
            pre = {}
            if not reasons:
                print("S7: no failure to triage; the failure analyst still judges the runner's handoff (S6 awaits its acceptance)")
            elif any(d.get("stage") == "S7" and d.get("status") == "running" for d in (state.get("dispatches") or {}).values()):
                print("S7: a triage dispatch is in flight; code writes no triage row while the analyst may be writing the file")
            else:
                try:
                    pre = s7_pretriage.pretriage(self.task_root)
                except Exception as exc:
                    print(f"S7: pre-triage could not run ({type(exc).__name__}: {exc}); the failure analyst triages every failure")
                for note in pre.get("notes") or []:
                    print("S7: " + note)
            if pre.get("closes") and not awaiting:
                said = f"every failure has a state the run already recorded: {len(pre['kept'])} written by code"
                # P2 M3. POSITION INVARIANT: after the pre-triage wrote its rows (the targets' triage context reads them), before the receipt.
                self.s7_close_places(self.s7_gap_reason("pretriaged"))       # t-1991 U3a: BEFORE the gate (a place is never both gaps)
                verdict, suffix = self.s7_investigation_gate()
                if verdict == "wait":
                    return
                register = ["work/exploratory-findings.jsonl"] if (self.task_root / "work" / "exploratory-findings.jsonl").is_file() else []
                self.close_by_code("S7", said + suffix, ["work/run-report.json", "work/triage.json"] + register, site="s7.pretriaged", finalize=False,
                                   tail=[["--event", "dispatch_skipped", "--task", self.task, "--reason",
                                          "S7: every failure has a state the run already recorded"]])
                return
            left = pre.get("left") or {}
            told = [f"Failures to triage: {reasons}"]
            if pre.get("kept") and (left.get("results") or left.get("manual") or left.get("unnamed")):
                # only the failures code left to the analyst are named, and the rows code wrote are named once, so the
                # analyst keeps them (they are listed under `not_for_repair` like any other row) or replaces one (Q10, Q11)
                told = ["Failures to triage: " + s7_pretriage.brief(
                            [("result", n) for n in left["results"]] + [("manual", n) for n in left["manual"]],
                            left["unnamed"], bool(pre.get("contradicted"))),
                        "Rows already written by code (keep them; you may replace one with your own): "
                        + ", ".join(pre["kept"])]
            complete = self.completion_for("S7", "qa-failure-analyst", {})
            if awaiting:
                # X7-6. POSITION: the record is written from the analyst's FINISH, BEFORE the controller accepts it as S7 work, and never by
                # the runner's own finish; the analyst is let in by the controller while S6 awaits (`awaits_acceptance`, one reader).
                complete = self.consumer_completion("S6", complete)      # the repair budget is read only if the verdict is a reject (B1)
            self.run_role("S7", "qa-failure-analyst", complete=complete,
                          extra=self.role_lines("S7", "qa-failure-analyst") + told
                          + ([f"You also accept or return the runner's handoff ({awaiting}): the verdict is `header.verdict` of your form, "
                              "and `inputs_read` names the runner's form work/handoffs/" + awaiting + ".yaml."] if awaiting else []))
            if awaiting:
                self.consumer_settled("S6", self.controller_state(), awaiting, True, ran=True)
                return          # S6 closes by the record (or the runner repairs) BEFORE S7's own repairs run
        self.s7_repairs()

    # --- X7-6b / X7-6c: S7 is accepted by its CONSUMER (the doc scribe of S8); the analyst's finish never closes it. The helpers shared with S6
    # are the `consumer_*` set above. ------------------------------------------------------------------------------------------------------
    def s7_closed_by_scribe(self, state: dict) -> bool:
        """X7-6b. POSITION: S7 closes HERE, by the consumer's (the doc scribe's) `accept` record of the analyst's LAST dispatch - never by the
        analyst's own finish (§3). INVARIANT: no record, a reject or a record for an earlier dispatch closes nothing; a failure of the current
        run report with no triage row (`s7_fresh`) closes nothing either and falls through to the re-triage. The close only CLOSES: the
        reduction ran when S7 went awaiting (`s7_await_scribe`, B3), so no second `finalize_task` (`finalize=False`)."""
        if not self.consumer_pending("S7"):
            return False
        reason, digest = self.consumer_close_words("S7")            # N4: who accepted, from the record (the scribe, or the person's word)
        return bool(self.close_by_code("S7", reason, ["work/triage.json", "work/run-report.json"],
                                       finalize=False, site="s7.accepted", digest=digest, fresh=self.s7_fresh))

    def s7_open_words(self, life: str) -> str:
        """The person's words of the recorded `close` answer to the open-work question of this life (`state["s7_open_work"][life]`, the file
        `_answer_open_work` kept); `""` when there is no such answer. A recorded answer whose file cannot be read still passes (its token is
        the word): the text then says so."""
        if not self.s7_open_answer(life):
            return ""
        rec = (self.state.get("s7_open_work") or {}).get(life) or {}
        try:
            text = (self.task_root / str(rec.get("words_file") or "")).read_text(encoding="utf-8", errors="replace") if rec.get("words_file") else ""
        except OSError:
            text = ""
        return text.strip() or "close (the answer to the open-work question; its words could not be read)"

    def s7_await_scribe(self, person_words: str = "") -> bool:
        """The end of S7's repairs under a consumer (X7-6b): with a consumer, an analyst dispatch that ran and NO accept record for its LAST one,
        S7 is left AWAITING the scribe. True = `s7_close` is done for this entry (nothing is closed, nothing is refused); False: no consumer, no
        analyst dispatch, S7 completed, or an accept record stands (a person's pass included: `person_words` - the recorded `close` answer - or a
        live waiver of `stage acceptance` is recorded as the accept by `consumer_person_pass`, M3, so the close goes on below).
        B3 (the Lead's decision): the reduction runs HERE, when S7 goes awaiting - BEFORE the marker and before S8 builds its ledger and report
        over it: `finalize_task`, then `s7_fresh`; a failure of the current run report with no triage row writes NO marker and S7 stays open for
        the re-triage (as at the close by code). The marker `pipeline["acceptance_awaits"]["S7"] = <the analyst's last dispatch>` (THE carrier
        `awaits_acceptance` reads; the controller, `next` and `rule_order` let the scribe in by it) is bound to a dispatch, so a scribe reject that
        reworks the analyst makes a NEW dispatch and this runs again at the next awaiting."""
        import acceptance
        if not acceptance.consumer_of("S7"):
            return False
        state = self.controller_state()
        if ((state.get("stages") or {}).get("S7") or {}).get("status") == "completed":
            return False
        author = acceptance.stage_author_dispatch(state, acceptance.stage_def_of("S7"))
        if not author or self.consumer_person_pass("S7", author, person_words):
            return False
        pipeline = self.pipeline()
        if acceptance.awaits_acceptance(state, "S7", pipeline) != author:
            code, out = self.py("finalize_task.py", str(self.task_root))
            if code:
                raise Refusal(f"S7 awaiting the scribe: finalize_task.py exit {code}: " + (out.splitlines()[-1] if out else ""))
            if not self.s7_fresh():
                print("S7: a failure of the current run report has no row in work/triage.json after the repairs; S7 stays open "
                      "and the failure analyst triages again on the next turn")
                return True
            from event_store import atomic_json
            pipeline = self.pipeline()
            marks = pipeline.get("acceptance_awaits") if isinstance(pipeline.get("acceptance_awaits"), dict) else {}
            pipeline["acceptance_awaits"] = dict(marks, S7=author)
            atomic_json(self.task_root / "pipeline.json", pipeline)
        print(f"S7: the repairs ended; S7 awaits the acceptance of {acceptance.consumer_of('S7')} for {author} (the scribe is let in; its record closes S7)")
        return True

    # --- S7 stays OPEN until its repairs end and is closed by code (C1-5b2, t-698 §18-§20) ----------------------------------------

    @staticmethod
    def s7_test_name(row: dict) -> str:
        case = str(row.get("case") or "").split("#")[0].split("::")[0]
        return str(row.get("test") or row.get("instance") or row.get("id") or case)

    def s7_listed_rows(self) -> list:
        """THE reader of the `triage` list of `work/triage.json` for the S7 loops (the repair rows and the re-judge rows both
        come through it, AR-13). A file that holds no list is a Refusal naming it - the analyst writes it again; nothing is guessed."""
        triage = _read_json(self.task_root / "work/triage.json")
        listed = triage.get("triage") if isinstance(triage, dict) else None
        if not isinstance(listed, list):
            raise Refusal("S7 repairs: work/triage.json holds no `triage` list, so the rows to repair are unknown; "
                          "the failure analyst writes it again")
        return listed

    def s7_rejudge_rows(self) -> list:
        """The triage rows S7 sends BACK TO THE RUNNER (HF8-19): the verdict `RUNNER_MISREAD_EVIDENCE`, no `fix_result` of `fixed` /
        `not_fixed`, not a `reorder` row, a non-empty `case`, and no problem of `contract.triage_contradiction_problems` (the one
        reader of the block, shared with the validator and the delivery check). A row that fails the selection starts nothing and
        is said in one line; the delivery check names it itself and the red stands. `s7_repair_rows` never sees this word (the S7
        contract's `repair_verdicts` is unchanged). ERROR DIRECTION: only toward NOT sending - a paid re-judge needs a row that
        passes every check. An unreadable list is the `Refusal` of `s7_listed_rows`."""
        import contract
        import s7_reorder
        out = []
        for row in self.s7_listed_rows():
            if not isinstance(row, dict) or row.get("verdict") != contract.TRIAGE_MISREAD_VERDICT:
                continue
            if str(row.get("fix_result", "")) in ("fixed", "not_fixed") or s7_reorder.wants_reorder(row) \
                    or not str(row.get("case") or "").strip():
                continue
            problems = contract.triage_contradiction_problems(row, self.task_root)
            if problems:
                print(f"S7: the row {self.s7_ident(row)} is {contract.TRIAGE_MISREAD_VERDICT} but is not sent back to the runner: "
                      f"{problems[0]}")
                continue
            out.append(row)
        return out

    def s7_repair_rows(self) -> list:
        """THE reader of the rows S7 repairs: the triage rows whose verdict is one of the S7 contract's own declaration
        (`null_outcome.scope.params.repair_verdicts`, data - FR-13; the word before the first colon, upper-cased) and that carry no
        `fix_result` of `fixed` / `not_fixed`. It filters by verdict and `fix_result` ONLY: the outcome skip of this life is applied
        in `s7_repairs` (at the analyst's finish there is no life yet). The analyst's finish (`s7_open_work`) and the loop both come
        through it. ERROR DIRECTION: a declaration or a triage list that cannot be read is a Refusal naming it - the finish then
        keeps S7 OPEN, and the entry refuses: a repair left undone is the one mistake this stage may not make."""
        import handoff
        declared = ((handoff.null_outcomes("s7-analyst-to-automator").get("scope") or {}).get("params") or {}).get("repair_verdicts")
        if not (isinstance(declared, list) and declared):
            raise Refusal("S7 repairs: handoffs/s7-analyst-to-automator.yaml carries no readable "
                          "`null_outcome.scope.params.repair_verdicts`, so the verdicts to repair are unknown; restore the "
                          "declaration (`null_outcomes.audit` names the contract) and enter S7 again",
                          close={"site": "s7.repair_verdicts", "stage": "S7", "step": "entry"})
        listed = self.s7_listed_rows()
        repair = {str(v).split(":")[0].strip().upper() for v in declared}
        import s7_reorder
        open_rows = [r for r in listed if isinstance(r, dict) and str(r.get("fix_result", "")) not in ("fixed", "not_fixed")]
        for r in open_rows:
            # a `reorder` request that cannot be executed is refused by name, never skipped (FR-1; the finish keeps S7 open)
            problems = s7_reorder.row_problems(r)
            if problems:
                raise Refusal("S7 repairs: " + problems[0] + " (work/triage.json; the failure analyst writes the row again)")
        # a row that asks for the reorder round is a repair whatever its verdict is (an APP_BUG whose later Thens stand behind
        # the red one): `reorder` is the analyst's request, `s7_reorder` the round (t-1508 R7)
        return [r for r in open_rows if s7_reorder.wants_reorder(r)
                or str(r.get("verdict", "")).split(":")[0].strip().upper() in repair]

    def s7_open_work(self):
        """What the analyst's finish does to S7 (`completion_for`): `OpenWork` while repair rows remain - or cannot be read - and
        `None` (today's road: the analyst closes S7) when there is nothing to repair. The reason is TIMELESS (it stays on the
        analyst's dispatch record after the close, where the dashboard lists it) and at most 300 characters: a longer list is cut
        with `…` and the path of the whole list."""
        try:
            rows = self.s7_repair_rows()
            rejudge = self.s7_rejudge_rows()        # HF8-19: one `try` - an unreadable list keeps S7 open for both
        except Refusal:
            return OpenWork("repairs_pending", "the failure analyst finished, but the factory could not read which verdicts are "
                            "repaired or the list of triage rows; S7 was kept open until it can")
        if not rows and not rejudge:
            # P2 M3, decision only. POSITION INVARIANT: after `s7_repair_rows` (repair rows outrank the investigation and `decision` is
            # not asked while one remains). This function never dispatches, projects or writes: it asks, the closers act.
            # What the role still decides: the investigation itself. An exception of the investigation code is one printed line and
            # today's road (P1, F-5).
            try:
                import investigation
                budget, _ = investigation.load_budget(self.plugin)
                word, why = investigation.decision(self.task_root, self.controller_state(), self.pipeline(), budget)
                if word == "none":
                    return None
                try:
                    open_ones = investigation.open_targets(self.task_root, budget)["unresolved"]
                except Exception:
                    open_ones = None
            except Exception as exc:
                print(f"S7: the observations the run left open could not be asked about ({type(exc).__name__}: {exc}); "
                      "S7 closes as it did without that")
                return None
            what = f"{len(open_ones)} observations" if open_ones is not None else "observations"
            head = f"the failure analyst finished; {what} the run left open are not investigated yet; "
            tail = {"dispatch": "S7 was kept open for one bounded read-only investigation",
                    "wait": "an investigation of them is running"}.get(
                word, f"before the close those only the factory has written are recorded as coverage gaps and those the analyst "
                      f"wrote are left as the analyst recorded them ({why})")
            return OpenWork("investigation_pending", open_work_reason(head + tail, "… [list: work/exploratory-findings.jsonl]"))
        # each sentence only for its own non-empty list (FR-10: the sentence about the TEST is never printed over a misread check)
        said = []
        if rows:
            said.append(f"the failure analyst found {len(rows)} failing test(s) whose fault is the test itself; "
                        f"S7 was kept open for their repairs: {', '.join(self.s7_test_name(r) for r in rows)}")
        if rejudge:
            said.append(f"the failure analyst found {len(rejudge)} manual check(s) whose record misreads its own captures; S7 was "
                        f"kept open until the runner judges them again: {', '.join(str(r.get('case')).strip() for r in rejudge)}")
        return OpenWork("repairs_pending", open_work_reason("; ".join(said), "… [list: work/triage.json]"))

    def s7_unbound(self):
        """The current failures of `work/run-report.json` that no row of `work/triage.json` answers, by THE binding
        (`contract.triage_failures` + `bind_triage`): their names, sorted, and one line for the failures with NO name at all (§21 iv:
        nothing can say they were triaged). `[]` is fresh; `None` - an unreadable report or list - is unknown, and unknown is not
        fresh (FR-41)."""
        import contract
        report = _read_json(self.task_root / "work/run-report.json")
        triage = _read_json(self.task_root / "work/triage.json")
        rows = triage.get("triage") if isinstance(triage, dict) else None
        if not (isinstance(report, dict) and report and isinstance(rows, list)):
            return None
        failures, unnamed = contract.triage_failures(report)
        bound = contract.bind_triage(failures, rows)["matched"]
        return sorted(key[1] for key in failures if not bound[key]) + ([f"{len(unnamed)} failure(s) with no name"] if unnamed else [])

    def s7_fresh(self) -> bool:
        """N1: every current failure of the run report is bound to a row of the triage (`s7_unbound` is empty). False - an unreadable
        report or list included - means the analyst's triage is not of this run: S7 is triaged again and never closed over it (allowed
        error: a needless triage; forbidden: a close over a failure nobody triaged)."""
        return self.s7_unbound() == []

    def s7_retriage_once(self) -> None:
        """The bound of N1's re-triage (t-698 §22 FX-3): ONE paid re-triage per chain of not-fresh triages. The record `s7_retriage`
        names the life the re-triage was started FROM; a not-fresh triage of a LATER life is the second consecutive one - the analyst
        has been asked again and the failure is still unbound, so the seam asks the person (`call=False`, no paid call; `retry` /
        `go on` / `stop`) and never a third analyst. A fresh triage ends the chain (`stage_S7` drops the record)."""
        life = self.s7_life()
        started = str((self.state.get("s7_retriage") or {}).get("from") or "")
        if started and started != life:
            unbound = self.s7_unbound()
            names = ("these failures still have no verdict from it: " + "; ".join(unbound)) if unbound else (
                "the factory could not read the run report or the analyst's list to say which failures have no verdict")
            self.no_move({"why": "threshold", "kind": "refusal", "call": False, "stage": "S7", "dispatch": life,
                          "lead": "The failure analyst has judged this story's failing tests twice, and " + names + ". The factory will "
                                  "not pay for a third go on its own, and it will not close this step over a failure nobody judged. "
                                  "Which of these should happen?",
                          "text": "Failures with no verdict from the analyst: " + ("; ".join(unbound) if unbound else "not known")})
        self.state["s7_retriage"] = {"from": life, "at": _now()}
        self.save_state()

    def s7_life(self) -> str:
        """The window life of the S7 repairs: the id of the latest ACCEPTED S7 `qa-failure-analyst` dispatch (new on every
        triage). `""` when none is readable: nothing is then written under it and no stored record is trusted (FR-59)."""
        import controller as CT
        found = [str(d.get("id") or key) for key, d in (self.controller_state().get("dispatches") or {}).items()
                 if isinstance(d, dict) and d.get("stage") == "S7" and d.get("role") == "qa-failure-analyst"
                 and d.get("status") == "accepted" and CT.s7_part_of(d) != "investigation"]       # P2 M3: an investigation is never the life
        return found[-1] if found else ""

    def s7_decided(self, life: str | None = None) -> dict:
        """The person's recorded decision on this life's analyst (`story_step._decision_of`, the one reader), `{}` when there is none -
        or none can be read: a stuck text asks it and must not fail (the error direction is today's wording)."""
        try:
            life = self.s7_life() if life is None else life
            import story_step
            return story_step._decision_of(self.task_root, life) if life else {}
        except Exception:
            return {}

    def s7_outcome(self, life: str, ident: str) -> str:
        """How this life ended the repairs of one test (`repaired` / `debt` / `no_progress`), `""` while it has not."""
        rec = ((self.state.get("s7_rows") or {}).get(life) or {}).get(ident) if life else None
        return str((rec or {}).get("outcome") or "")

    def s7_mark(self, life: str, ident: str, **fields) -> None:
        if not life:
            return
        rows = self.state.setdefault("s7_rows", {}).setdefault(life, {})
        rows[ident] = dict(rows.get(ident) or {}, at=_now(), **fields)
        self.save_state()

    def s7_ident(self, row: dict) -> str:
        """The identity of a triage row WITHIN a life (t-698 §22 FX-1): the row's OWN stable name (`contract.row_names`, the first).
        It is never rebuilt from `automation-manifest.json`: the repair round the loop dispatches is the automator, whose output IS
        that manifest, so a key read from it drifts under the loop's feet (a repaired row would be repaired again; the person's
        answer would not be found). A row with no name at all is `<its case>#<its index in the list of triage.json>` - stable within
        a life, since the list is fixed until the close's finalize."""
        import contract
        names = contract.row_names(row)
        if names:
            return names[0]
        listed = _read_json(self.task_root / "work/triage.json").get("triage") or []
        return f"{str(row.get('case') or '').strip()}#{listed.index(row) if row in listed else -1}"

    def s7_refs(self, row: dict) -> tuple:
        """`(tests, bound)`: the ledger refs of the manifest tests this triage row answers NOW (`ledger.triage_refs`, the reader the
        report's `Runs left failing` uses). A row no test is bound to is named `unbound:<its identity>`: that never equals a ledger ref,
        so it covers no other row, and `debt_key` keeps two apart. Read once per (life, row): `s7_tests` freezes it."""
        import ledger
        refs = ledger.triage_refs(self.task_root, row)
        return (refs, True) if refs else (["unbound:" + self.s7_ident(row)], False)

    def s7_tests(self, row: dict, ident: str, life: str) -> tuple:
        """`(tests, bound)` of a row, FROZEN per (life, row) at the first computation (t-698 §22 FX-1): the question, the debt entry and
        the answer read the frozen list, never a later reading of the manifest the repair round rewrites. Under life `""` nothing is
        written (`s7_mark`), so every call reads again."""
        kept = ((self.state.get("s7_rows") or {}).get(life) or {}).get(ident) if life else None
        if isinstance(kept, dict) and isinstance(kept.get("tests"), list) and kept["tests"]:
            return list(kept["tests"]), bool(kept.get("bound"))
        tests, bound = self.s7_refs(row)
        self.s7_mark(life, ident, tests=tests, bound=bound)
        return tests, bound

    def s7_plan(self, rows: list, life: str) -> list:
        """`[(row, ident, tests, bound)]` of the rows to repair, each keyed by its own name (`s7_ident`) with its frozen refs."""
        return [(row, ident, *self.s7_tests(row, ident, life)) for row, ident in ((row, self.s7_ident(row)) for row in rows)]

    def s7_repairs(self) -> None:
        """The repairs run INSIDE the open stage and end in exactly ONE of three ways: S7 closed by code (`s7_close`), the person asked
        (a `Person`) or a `Refusal` - a silent return with S7 open would repeat this entry on every `where`. The only returns are
        the person's recorded `close` (S7 is theirs to close), said in a printed line. Their recorded `open_work` ends in the closed
        question of `s7_open_work_ask` (t-698 §22 FX-2): the code does not close the stage over it, and `decide --close` is no door (it
        refuses an accepted dispatch), so the person's `close` is an answer to that question, read by `s7_open_answer`."""
        rows = self.s7_repair_rows()
        life = self.s7_life()
        decided = self.s7_decided(life)
        if "close" in decided:
            print("S7: the person's recorded decision closes S7; no repair round is dispatched")
            return
        plan = self.s7_plan(rows, life)
        for row, ident, tests, bound in plan:
            if not self.s7_outcome(life, ident):
                self.s7_repair_test(row, ident, tests, bound, life)
        # HF8-19: the checks a runner misread go back to the runner. POSITION INVARIANT: BELOW the person's recorded `close` (their
        # word is never answered by a paid round, P13), after the test repairs, and BEFORE `open_work` / `s7_close`: S7 is neither
        # closed nor is the person asked about its close while a selected row of this life has no `outcome`.
        plan_rejudge = [(row, self.s7_ident(row)) for row in self.s7_rejudge_rows()]
        for row, ident in plan_rejudge:
            self.s7_rejudge_round(row, ident, life)
        if "open_work" in decided and not self.s7_open_answer(life):
            self.s7_open_work_ask(plan, life, decided["open_work"])
        self.s7_close(plan, life, plan_rejudge)

    def s7_open_answer(self, life: str) -> bool:
        """The person answered `close` to the question of this life's `open_work` (`state["s7_open_work"][life]`). Under life `""` nothing is
        trusted (FR-59)."""
        return bool(life) and ((self.state.get("s7_open_work") or {}).get(life) or {}).get("token") == "close"

    def s7_open_work_ask(self, plan: list, life: str, decision: dict) -> None:
        """Every row of an `open_work` life has ended: ONE closed question names the person's open decision (their own words, quoted
        from the file `decide --open` kept) and asks whether to close S7 now (`close` -> `s7_close` on the next entry) or stop. No paid
        call, no round, no close here (P13: their word outranks the code's close); an entry with the question unanswered asks it again."""
        ended = [self.s7_outcome(life, ident) for _row, ident, _tests, _bound in plan]
        try:
            kept = (self.task_root / str(decision.get("words_ref") or "")).read_text(encoding="utf-8", errors="replace") if decision.get("words_ref") else ""
        except OSError:
            kept = ""
        quoted = f' (your words: "{self.s0_quote(kept)}")' if kept.strip() else ""
        lead = (f"You decided to keep {self.stage_place('S7')} open for more work{quoted}. The repairs of the failing tests it found are finished: "
                f"{ended.count('repaired')} repaired, {ended.count('debt')} left failing by your answer, {ended.count('no_progress')} stopped "
                "because a round changed nothing.\n\nShould the factory close this stage now, or hold it open?")
        self.state.setdefault("s7_open_work", {})[life] = {"token": "", "lead": lead, "at": _now()}
        self.save_state()
        print("S7: the repairs ended and the person's recorded decision keeps S7 open; the person is asked whether to close it")
        self.no_move({"why": "threshold", "kind": "open_work", "call": False, "stage": "S7", "dispatch": life, "lead": lead,
                      "site_doors": ("close",), "site_fallback": lambda said: self.s7_open_work_person(life, lead, said)})

    def s7_open_work_person(self, life: str, lead: str, said: str = "") -> Person:
        """The question from its words: `said` (an unread answer's lead) above the account, then the two priced answers of `s7.open_work`.
        ONE literal `closed_question` (the census of question ids reads it)."""
        lead = lead if not said.strip() or said.strip() == lead.strip() else said.strip() + "\n\n" + lead
        close = {"answer": "close", "token": "close", "slots": {},
                 "says": "the stage is closed now with one receipt written by the factory's own commands; nothing is run again and the "
                         "repairs stay as they ended"}
        return Person("open_work", self.closed_question("s7.open_work", lead, [close, dict(self.STOP_OPTION)]), "S7", life)

    def _answer_open_work(self, words: str, qtext: str, stage: str, dispatch: str) -> None:
        """The answer to the end-of-`open_work` question (FR-9: each token has an executor; FR-12: tokens only). `close` is kept for this
        life and the next entry closes S7 by code (`s7_repairs`); `stop` holds the question (it comes back on a rerun); any other word goes
        to the seam once, with this question as the one shown again."""
        rec = (self.state.get("s7_open_work") or {}).get(dispatch) or {}
        token = self.s0_normalize(words)
        if not rec or token not in ("close", "stop"):
            self.unread("open_work", stage, dispatch, qtext, words=words, doors=("close", "stop"), lead=self.unread_lead(words),
                        again=lambda said: self.s7_open_work_person(dispatch, rec["lead"], said) if rec else self.held_question(said))
            return
        self.answer_row(f"{stage} open work ({token}): ", words.strip(), what="your answer about the open work")
        if token == "stop":
            raise self.held_question(self.stop_held("If you want the factory to close the stage after all, answer `close`."))
        rec.update(token="close", words_file=self.answer_file(), answered=_now())
        self.save_state()
        print(f"{stage}: the person's answer `close` is recorded; the stage is closed on the next step")

    def s7_close(self, plan: list, life: str, rejudge: list = ()) -> None:
        """Every row ended in this life: finalize, then the receipt and the record, through `close_by_code` (the stage_done carries the
        analyst's digest and what happened to the repairs). A current failure with no triage row (checked after finalize, before the
        receipt) leaves S7 open for the next entry, which triages again (N1)."""
        # P2 M3: the investigation of what the run left open comes FIRST. POSITION INVARIANT: after every repair row of the life ended
        # (this is reached only from the end of `s7_repairs`), before the acceptance stop, finalize and the receipt. `wait`: no close, the next `where` resumes.
        # t-1991 U3a. POSITION INVARIANT: the places nobody settled are gapped BEFORE the investigation gate, so a place is never both a
        # settle gap and an investigation gap (`close_unsettled` never writes a plain open target; its `by` is outside `code:investigation.`).
        self.s7_close_places(self.s7_gap_reason())
        verdict, suffix = self.s7_investigation_gate()
        if verdict == "wait":
            return
        # X7-6b. POSITION INVARIANT: after the investigation (`author_dispatches` leaves it out: it is no triage), before the close by code: with a
        # consumer and no accept record the end of the repairs is «S7 awaits the scribe» (the reduction runs there, B3), never a close and never a
        # refusal; the record closes S7 at `s7.accepted` on the next entry. Both closing roads (the end of the repairs, the person's `close`
        # answer) come through here; a recorded `close` answer or a waiver is the person's pass (M3) and closes by the person's word below.
        if self.s7_await_scribe(self.s7_open_words(life)):
            return
        self.consumer_need_record("S7", "s7_close")        # the invariant: past this line a record stands (or there is no consumer); a bare close is refused
        ended = [self.s7_outcome(life, ident) for _row, ident, _tests, _bound in plan]
        debts = [self.s7_test_name(item[0]) for item, end in zip(plan, ended) if end == "debt"]
        fixed, stopped = ended.count("repaired"), ended.count("no_progress")
        reason = (f"repairs ended: {fixed} repaired; {len(debts)} left failing by your answer"
                  + (": " + ", ".join(debts) if debts else "") + f"; {stopped} stopped because a round changed nothing")
        sent = [self.s7_outcome(life, ident) for _row, ident in rejudge].count("rejudged")
        sent_back = f"{sent} manual check(s) were sent back to be judged again" if sent > 0 else ""
        if not plan:        # no repair row: the sentence above would say a repair happened (FR-10)
            reason = sent_back or "no failing test to repair; the failure analyst's triage stands"
        elif sent_back:
            reason += "; " + sent_back
        reason += suffix
        analyst = self.saved_done(life)
        digest = ((analyst or f"qa-failure-analyst S7 {self.task} done") + f"; repairs: fixed={fixed} not_fixed={len(debts)} stopped={stopped}"
                  + (f"; {sent_back}" if sent_back else "") + suffix)
        if not analyst:
            print("S7: the analyst's saved digest could not be read; the close carries a short digest")
        evidence = (["work/triage.json", "work/run-report.json"] + (["work/review-debts.json"] if debts else [])
                    + (["work/exploratory-findings.jsonl"] if (self.task_root / "work" / "exploratory-findings.jsonl").is_file() else []))
        if not self.close_by_code("S7", reason, evidence, site="s7.after_repairs", finalize=True, digest=digest, role="qa-failure-analyst", journal=True,
                                  fresh=self.s7_fresh):
            print("S7: a failure of the current run report has no row in work/triage.json after the repairs; S7 stays open "
                  "and the failure analyst triages again on the next turn")

    def s7_gap_reason(self, kind: str = "") -> str:
        """t-1991 U3a: the text the driver gives `place_answers.close_unsettled` (`references/place-answers.json` `gap_reason_names`, five texts picked by name).
        `kind` `no_failures` / `pretriaged` -> those names (no analyst ran). Otherwise `unanswered` - true whether or not the dispatch was told -
        unless the record U3b writes for the last S7 triage dispatch (`state["s7_walk"][<id>]["failed"]`) names `stand` or `session`. `""` when the texts cannot be read: `close_unsettled` then refuses and `s7_close_places` prints one line."""
        try:
            import place_answers
            texts = place_answers._data()["gap_reason_names"]           # chosen by NAME: a reorder of the list cannot give a false text
            if kind in ("no_failures", "pretriaged"):
                return texts[kind]
            import controller as CT
            ids = [str(d.get("id") or key) for key, d in (self.controller_state().get("dispatches") or {}).items()
                   if isinstance(d, dict) and d.get("stage") == "S7" and d.get("role") == "qa-failure-analyst" and CT.s7_part_of(d) != "investigation"]
            walk = (self.state.get("s7_walk") or {}).get(ids[-1]) if ids else None
            failed = str((walk or {}).get("failed") or "") if isinstance(walk, dict) else ""
            return texts["stand"] if failed == "stand" else texts["session"] if failed == "session" else texts["unanswered"]
        except Exception as exc:
            print(f"S7: the reason for the places nobody settled could not be chosen ({type(exc).__name__}: {exc})")
            return ""

    def s7_close_places(self, why: str) -> list:
        """t-1991 U3a: ONE call at each of the three S7 code closers, BEFORE `s7_investigation_gate` (INVARIANT: a place is never both a settle
        gap and an investigation gap; `close_unsettled` never writes a plain `open` place, and its `by` is outside the investigation's
        prefix). The ids of the register lines written. The list that could not be read whole is one printed line and the close still runs
        on what was read; an exception is one printed line and S7 goes on - it never reads as "no places" (P1, AR-28)."""
        try:
            import place_answers
            found = place_answers.places(self.task_root)
            if found["unreadable"]:
                print("S7: the places to settle could not be computed whole: " + "; ".join(f"{rec}: {w}" for rec, w in found["unreadable"]))
            printed: list = []
            written = place_answers.close_unsettled(self.task_root, why, printed, found=found)
        except Exception as exc:
            print(f"S7: the places nobody settled could not be recorded as gaps ({type(exc).__name__}: {exc}); S7 goes on")
            return []
        for line in printed:
            print(f"S7: {line}")
        if written:
            print(f"S7: {len(written)} place(s) nobody settled were recorded as coverage gaps: {why}")
        return written

    def s7_places_scribe_line(self) -> list:
        """t-1991 U3a: the ONE line the S8 scribe gets about the places of S7 - settled ones with the answer and the source of its
        expectation (where `expectation.source` reaches a reader beside `answer_problems`), unsettled ones with their state. At most
        `scribe_line_max` characters (the data row of `references/place-answers.json`); more is cut with "[and <n> more: place_answers.py list]". Returning the triage
        for them is the scribe's judgment; this line only shows the facts."""
        try:
            import place_answers
            cap = int(place_answers._data()["scribe_line_max"])
            found = place_answers.places(self.task_root)
            rows = [(p["id"],) + tuple(place_answers.settled_answer(self.task_root, p["id"])) for p in found["places"]]
        except Exception as exc:
            print(f"S7: the places for the scribe could not be listed ({type(exc).__name__}: {exc})")
            return [f"Places of S7: the list could not be computed whole ({type(exc).__name__}: {exc}); run place_answers.py list"]
        if found["unreadable"]:
            print("S7: the places for the scribe could not be computed whole: " + "; ".join(f"{rec}: {why}" for rec, why in found["unreadable"]))
        if not rows and not found["unreadable"]:
            return ["Places of S7: none in this run"]
        done, left = [], []
        for pid, record, state, _why in rows:
            if state == "settled":
                src = (record.get("expectation") or {}) if isinstance(record, dict) else {}
                done.append(f"{pid}: {record.get('answer')} (expectation: {src.get('source') or 'none'}"
                            + (f" {src.get('id')}" if src.get("id") else "") + ")")
            else:
                left.append(f"{pid} ({state})")
        entries = done + left
        whole = f" (not computed whole: {', '.join(rec for rec, _w in found['unreadable'])[:200]})" if found["unreadable"] else ""

        def render(keep: int) -> str:
            shown_done, shown_left = done[:keep], left[:max(0, keep - len(done))]
            parts = ([f"settled {len(done)}" + (" — " + "; ".join(shown_done) if shown_done else "")] if done else []) \
                + ([f"not settled {len(left)}" + (": " + ", ".join(shown_left) if shown_left else "")] if left else [])
            text = f"Places of S7 ({len(rows)}){whole}: " + "; ".join(parts)
            return text + (f" [and {len(entries) - keep} more: place_answers.py list]" if keep < len(entries) else "")
        for keep in range(len(entries), -1, -1):
            if len(render(keep)) <= cap or keep == 0:
                return [render(keep)]
        return [render(0)]

    def s7_investigation_gate(self) -> tuple:
        """What S7 does about the observations the run left open BEFORE it closes by code (P2 M3): `(verdict, suffix)`, verdict
        `proceed` | `dispatched` | `wait`, suffix the text added to the close reason and digest (`""` when nothing happened). Called
        ONLY at the three code closers (`s7.no_failures`, `s7.pretriaged`, `s7.after_repairs`), never at the stage entry. `wait`: the
        caller returns WITHOUT a close (a running pass; the next `where` resumes it). A stage the controller holds `completed` is
        never worked on. An exception of the investigation code is one printed line and today's close (P1, F-5). The decision itself
        is `investigation.decision` (pure); the register is written only through `investigation.project` / `close_gaps`. What the
        role still decides: the investigation itself (targets worth a probe, what the probe shows, how it is recorded)."""
        held = ((self.controller_state().get("stages") or {}).get("S7") or {}).get("status")
        if held == "completed":
            return "proceed", ""
        try:
            import investigation
            budget, _ = investigation.load_budget(self.plugin)
        except Exception as exc:
            print(f"S7: the investigation could not be loaded ({type(exc).__name__}: {exc}); S7 closes as it did without it")
            return "proceed", ""
        try:
            investigation.project(self.task_root, "S7")
        except Exception as exc:
            print(f"S7: the observations the run left open could not be projected ({type(exc).__name__}: {exc}); "
                  "S7 goes on with what the register holds")
        try:
            word, why = investigation.decision(self.task_root, self.controller_state(), self.pipeline(), budget)
            targets = (investigation.open_targets(self.task_root, budget)["unresolved"] if word == "dispatch" else [])
        except Exception as exc:
            print(f"S7: the investigation could not be decided ({type(exc).__name__}: {exc}); S7 closes as it did without it")
            return "proceed", ""
        if word == "wait":
            print(f"S7: the investigation {why} is running; S7 is not closed over it")
            return "wait", ""
        if word == "none":
            if why:
                print(f"S7: {why}")
            return "proceed", ""
        printed: list = []
        if word == "gaps":
            try:
                if why == investigation.WHY_TEXTS[0]:
                    print("S7: the investigation budget cannot be used (" + "; ".join(investigation.budget_problems(budget)) + ")")
                g = len(investigation.close_gaps(self.task_root, why, printed, budget=budget))
            except Exception as exc:
                print(f"S7: the observations the run left open could not be recorded as gaps ({type(exc).__name__}: {exc}); "
                      "S7 closes as it did without it")
                return "proceed", ""
            for line in printed:
                print(f"S7: {line}")
            return "proceed", (f"; {g} observation(s) the run left open were not investigated: {why}" if g else "")
        # dispatch: ONE bounded read-only pass, synchronous like the triage; a halt, a question threshold or a Refusal of
        # `run_role` interrupts the gate and leaves the dispatch `running` (the next entry goes through `wait_existing_job`)
        print(f"S7: {len(targets)} observation(s) the run left open are not investigated; one bounded read-only investigation is dispatched")
        self.run_role("S7", "qa-failure-analyst", purpose="investigation", complete=False,
                      extra=self.role_lines("S7", "qa-failure-analyst", {"stage": "S7", "purpose": "investigation"}))
        try:
            g = len(investigation.close_gaps(self.task_root, investigation.WHY_TEXTS[1], printed, budget=budget))
            for line in printed:
                print(f"S7: {line}")
            import exploratory_findings
            chains = exploratory_findings.chains_of(exploratory_findings.read(self.task_root)["lines"])
            by_role = {t for t, chain in chains.items() if any(not investigation.is_code_line(line) for line in chain)}
            k = len({str(t["id"]) for t in targets} & by_role)
        except Exception as exc:
            print(f"S7: what the investigation recorded could not be counted ({type(exc).__name__}: {exc}); S7 closes without the count")
            return "dispatched", ""
        return "dispatched", (f"; {len(targets)} observation(s) the run left open were investigated read-only: {k} recorded by the "
                              f"analyst, {g} left as coverage gaps")

    def investigation_lines(self) -> list:
        """The dispatch lines of the read-only investigation (P2 M3), recomputed from the CURRENT state at every call (a relaunch after
        a first attempt lists only the targets still without an active line): the two honesty lines first, the targets whole (observed
        verbatim, FR-49) with their triage context, the caps of `references/investigation-budget.json`, the commands, the six end
        states and the form note. A target list that cannot be computed is one printed line and a line telling the role to ask for it.
        What the role still decides: which target to probe, what to ask the stand, how to record what it saw."""
        base = f"qa-factory/artifacts/{self.task}/"
        py = '`python "${CLAUDE_PLUGIN_ROOT}/scripts/'
        lines = ["This dispatch is an INVESTIGATION (purpose `investigation`), not a triage and not a rework: a `Rework reason: investigation` "
                 "line above, if any, is the controller's purpose word.",
                 "The triage judge line and `work/judge-triage.json`, if present, are not your input: the triage is done."]
        try:
            import investigation
            budget, problems = investigation.load_budget(self.plugin)
            found = investigation.open_targets(self.task_root, budget)
        except Exception as exc:
            print(f"S7: the targets of the investigation could not be listed ({type(exc).__name__}: {exc})")
            return lines + [f"The factory could not list the targets ({type(exc).__name__}: {exc}): run {py}investigation.py\" unresolved "
                            f"--task-root {base}` and investigate what it lists, within the caps of references/investigation-budget.json."]
        if found["unresolved"]:
            lines.append("Findings to investigate:")
            for target in found["unresolved"]:
                lines.append(f"- {target['id']}: Then: {target['then']} | observed (verbatim): {target['observed']} | before the change: "
                             f"{target['before_change']} | evidence: {', '.join(target['evidence']) or 'none'} | why inconclusive: "
                             f"{target['why_inconclusive']}")
                lines += [f"  S7 triage said (context, not a verdict): {ctx}" for ctx in found["context"].get(target["id"], [])]
        else:
            lines.append("Findings to investigate: none left — each target already has an active line; hand back the form")
        if problems:
            lines.append("The investigation budget cannot be used (" + "; ".join(problems) + "): every probe is refused - record nothing new "
                         "and hand back the form.")
        else:
            p, r, t = budget["probes_per_dispatch"], budget["reproductions_per_target"], budget["timebox_minutes"]
            try:                    # the probes the pass has made so far (a retry/relaunch continues the counts); never a stop (P1)
                import investigation_probe
                used = str(len(investigation_probe.capture_lines(self.task_root)))
            except Exception:
                used = "unknown"
            lines.append(f"Caps of this investigation: {p} probes per pass (used so far: {used}), {r} per target, {t} minutes from the first probe; at most "
                         f"{p // r} targets (P divided by R, rounded down) can reach `reproduced` - choose which ones.")
        lines += [f"Commands: {py}investigation_probe.py\" http --task-root {base} --dispatch <your dispatch id> --target <target id> --method GET "
                  f"--url <address>` sends ONE read-only request; {py}investigation_probe.py\" record --task-root {base} --dispatch <your "
                  "dispatch id> --target <target id> --kind <observation|unresolved_question|coverage_gap> --statement <what you saw> "
                  f"--why-not-a-bug <why> --status <status>` writes what you saw; {py}exploratory_findings.py\" list --task-root {base}` "
                  "shows the register.",
                  "End states of a target, exactly one active line each: `reproduced` / `not_reproduced` / `environment_event` / "
                  "`unverified` (k of R) / `unresolved_question` / `coverage_gap`.",
                  "Record what the product does; never compare it with an expected value; never write a bug or a triage row; only "
                  "`investigation_probe.py` reaches the stand.",
                  "The places of `place_answers.py list` were the triage's to settle; you do not walk the page for them and do not answer them.",
                  "Your hand-back is the usual S7 form `s7-analyst-to-automator` with `scope: []` and no `not_for_repair` rows, and it is checked "
                  "whole. Fill: the `inputs_read` row [0] for `work/run-report.json` with its `version` and `failures` (what you read); the "
                  "`inputs_read` row [1] the template lists (the runtime provenance record, its `path` and `version`); the three `claims.*` "
                  "keys (true or false, none blank); `header.verdict`. Leave `unresolved` as the template has it - the register "
                  "(`exploratory_findings.py list`) is the carrier of what you left `unverified`, not the form; `triage.json` is not yours "
                  "to change. Your DIGEST (the result you return) carries one line per item of this dispatch's scope - every TC-n in scope: "
                  "`passed` for the ones that passed, `unresolved` for the targets above - and without such a line for an item the "
                  "hand-over is refused as incomplete."]
        return lines

    def saved_done(self, dispatch: str) -> str:
        """The digest of an ACCEPTED dispatch from its saved result (`driver-runs/<id>.done.json`), `""` when it is unreadable."""
        found = _read_json(self.state_dir / "driver-runs" / f"{dispatch}.done.json") if dispatch else {}
        return self.digest_of(str(found.get("result") or "")) if isinstance(found, dict) and found.get("result") else ""

    def close_by_code(self, stage: str, reason: str, evidence: list, *, finalize: bool, site: str = "", digest: str = "", role: str = "",
                      journal: bool = False, tail=(), fresh=None) -> bool:
        """THE helper of "a stage closed by code after its post-role loop" (t-698 §18.5; S7's two closes and the close after its
        repairs, and the three S6 closes, which pass `finalize=False` after their own `finalize_task` call and its own refusal text;
        C2-8 marks every one with its `site`): `finalize_task` when `finalize` (BEFORE the receipt, so the receipt hashes what finalize
        wrote), the `code_only` receipt (`close_receipt`), then the `stage_done` record (`record_close`). A stage the controller holds
        `completed` already is NOT closed again (state is read first, never a refusal's words): no finalize, no second receipt. A
        `stage_done` refused after a successful `code_only` is a Refusal whose retry repeats `record_close` - the write AND its tail.
        `fresh`: a precondition checked after finalize, before the receipt; False records nothing and returns False."""
        held = ((self.controller_state().get("stages") or {}).get(stage) or {}).get("status")
        if held == "completed":
            print(f"{stage}: the controller holds it completed already; no second receipt is written")
            return True
        if finalize:
            code, out = self.py("finalize_task.py", str(self.task_root))
            if code:
                raise Refusal(f"{stage} close: finalize_task.py exit {code}: " + (out.splitlines()[-1] if out else ""))
        if fresh is not None and not fresh():
            return False
        receipt = self.close_receipt(site, stage, reason, evidence)
        self.file_passed_over(stage, receipt)
        self.record_close(site, stage, "--status", "done", *(["--role", role] if role else []),
                          "--digest", digest or reason, *([] if journal else ["--no-journal"]), tail=tail, receipt=receipt)
        return True

    def s7_repair_test(self, row: dict, ident: str, tests: list, bound: bool, life: str) -> None:
        """The repair rounds of ONE failing test, until it is green, the count stops growing, or the repair limit is answered `debt`.
        At the limit (the cap is spent) or with no count the loop does not break in silence: the seam asks once per (test, count)
        and goes on by the person's answer (`s7_limit`, t-698 §4.4) - `round` runs exactly one more round, `debt` ends this test's
        loop with the failure recorded. The loop dispatches nothing at a count it cannot read (no round is guessed). The way it ends is
        recorded for this life (`s7_rows`), so a later entry never repairs the test again."""
        case = str(row.get("case") or "").split("#")[0].split("::")[0]
        test, spent = self.s7_test_name(row), None
        import s7_reorder
        reorder = s7_reorder.wants_reorder(row)
        # RD1-9b: whether the critic had REJECTED a test of this case is read BEFORE any round (the author's patch may rewrite the row)
        # and kept in the row's record, so a restart between the author and the critic still knows it (AR-25). Reorder has its own review.
        kept = (((self.state.get("s7_rows") or {}).get(life) or {}).get(ident) or {}) if life else {}
        was_rejected = False if reorder else (bool(kept["was_rejected"]) if "was_rejected" in kept else self.s7_was_rejected(case))
        if not reorder and "was_rejected" not in kept:
            self.s7_mark(life, ident, was_rejected=was_rejected)
            if was_rejected and not life:
                print(f"S7: {test} - no life: the repair review mark lives only in this run")
        if not reorder and self.s7_green_outside(life, ident, row, test, case, was_rejected):      # a reorder round's author digest is never read as repaired
            return
        while True:
            # the window's rounds are the controller's count, re-read every pass (B-007): the S7 repair
            # shares the cap with the S5 rounds of the same window, and a restart forgets nothing
            budget = self.budget_or_none("S5", "qa-automator", [case] if case else [])
            counted, cap = (budget or {}).get("counted"), (budget or {}).get("cap")
            owed = None
            if not self.repair_countable(budget) or counted >= cap:
                owed = self.s7_limit(test, ident, tests, bound, case, budget, life)      # the person's answer for this test at this count, or the question
                if owed.get("token") != "round" or owed.get("executed"):
                    print(f"S7: {test} - the person's answer `{owed.get('token')}` for this count is used; no further repair is dispatched")
                    self.s7_mark(life, ident, outcome="debt" if owed.get("token") == "debt" else "no_progress")
                    break
            elif spent is not None and counted <= spent:
                print(f"S7: {test} - the controller did not count the round just run ({counted} of {cap}); stopping the repairs of this test")
                self.s7_mark(life, ident, outcome="no_progress")
                break
            spent = counted
            if reorder:
                end = self.s7_reorder_turn(row, test, case, counted, cap, owed, life, ident)
                if end in ("repaired", "no_progress"):
                    self.s7_mark(life, ident, outcome=end)
                if end != "retry":
                    break               # "owed": the round never started, the person's round stays owed and nothing is marked
                continue                # one more round within the shared cap (the count decides; a round that was not counted stops above)
            digest = self.s7_round(row, test, case, counted, cap, owed, life, ident)
            import role_digest
            states = {r["state"] for r in role_digest.parse(digest).get("rows") or []}
            if states & {"green", "passed", "fixed"}:
                if not was_rejected:
                    self.s7_mark(life, ident, outcome="repaired")
                    break
                # position: the review comes AFTER the green author and BEFORE `repaired`; a test the critic rejected is never
                # `repaired` without the critic's word (RD1-9b)
                end = self.s7_review_repair(row, test, case, life, ident)
                if end in ("repaired", "no_progress"):
                    self.s7_mark(life, ident, outcome=end)
                    break
                continue                # "retry": one more round within the shared cap; the top meets `s7_limit` at the cap

    def s7_was_rejected(self, case: str) -> bool:
        """Did the critic REJECT any test of this case (`ledger.is_rejected`, the one reading) in the manifest as it stands now? An
        unreadable manifest or an empty case is False and says so: the review is then skipped, and RD1-9a's `blocked` still holds the
        rejected row out of `pass` (FR-59). `"REJECTED"` is not the critic's word: False."""
        try:
            import contract
            import ledger
            if not case:
                print("S7: a repair of a row with no case - the critic's earlier verdicts are not looked up")
                return False
            manifest = _read_json(self.task_root / "work/automation-manifest.json")
            return any(ledger.is_rejected(e) for e in contract.entries_for_case(contract.manifest_tests(manifest), case))
        except Exception as exc:
            print(f"S7: {case} - the manifest could not be read ({type(exc).__name__}: {exc}); no repair review for it")
            return False

    def s7_review_repair(self, row: dict, test: str, case: str, life: str, ident: str) -> str:
        """The critic's review of ONE repaired test the critic had rejected (RD1-9b; reason `S7 repair review: <test>`, cause
        `test_defect`, the cap is the window's). The round id goes into the record as `review_round` - NOT `round`, which is the
        author's (a critic's id there would read as a not-green digest and start another author round). The outcome is read through
        `s7_reorder_outcome` and so through `route_of` (AR-13). `ReworkRefused` at the spent cap returns `retry` (the loop's top meets
        `s7_limit`: a question to the person, no new stop, AR-17); any other refusal is raised, S7 stays open."""
        import s7_reorder
        try:
            digest, _next = self.rework("S5", "qa-code-critic", [case] if case else [], s7_reorder.REPAIR_REVIEW_REASON.format(test=test), cause="test_defect",
                                        on_request=lambda rid: self.s7_mark(life, ident, review_round=rid), extra=self.S5_CRITIC_BRIEF)
        except ReworkRefused:
            # t-593 F-5: the controller keeps a ledger and a cap PER ROLE (`budget_scope`), so the refusal of the critic's pass is
            # judged on the critic's own count as well as the author's: either one spent (or unreadable) is the cap, and `retry` goes
            # back to the loop (the author's rounds then reach the limit question); a refusal at neither is raised
            for role in ("qa-automator", "qa-code-critic"):
                budget = self.budget_or_none("S5", role, [case] if case else [])
                if not self.repair_countable(budget) or budget["counted"] >= budget["cap"]:
                    print(f"S7: {test} - the controller refused the repair review at the repair cap ({role}); the limit question decides")
                    return "retry"
            raise
        return self.s7_reorder_outcome(digest, test, case, what="repair review")

    def s7_reorder_turn(self, row: dict, test: str, case: str, counted: int, cap: int, owed: dict | None, life: str, ident: str) -> str:
        """One turn of a `reorder` test's loop and how it ended: `repaired` (the critic approved; the carried row is marked fixed -
        the one writer of that field, AR-14), `no_progress`, `retry` (one more round within the shared cap) or `owed` (the round never
        started and the person's `round` was taken back: the loop stops with nothing marked, so the person's round is still owed on
        the next entry). The author's digest is NEVER read as `repaired`: the round's outcome is `finish` (code) and the critic's review."""
        import s7_reorder
        try:
            digest = self.s7_round(row, test, case, counted, cap, owed, life, ident)
        except s7_reorder.ReorderRefused as exc:
            print(f"S7: {test} - the reorder round is not carried: {exc}")
            if exc.kind == "green":
                return "no_progress"
            return "owed" if owed and not owed.get("executed") else "retry"
        end = self.s7_reorder_outcome(digest, test, case)
        if end == "repaired":
            s7_reorder.mark_fixed(self.task_root, ident)
        elif end == "retry":
            s7_reorder.send_back(self.task_root, ident)      # the carried round was judged: it is never resumed as unjudged
        return end

    def s7_reorder_outcome(self, digest: str, test: str, case: str = "", what: str = "reorder") -> str:
        """How the critic's review of a reorder round ends it (and, with `what="repair review"`, the review of a repaired test the
        critic had rejected, `s7_review_repair`; only the printed words differ): `repaired`, `retry` (the review sends the window back to its author
        within the cap) or `no_progress` (a halting verdict, an `unverified` or `rejected` row on an approving verdict, a verdict this
        code does not know, a close over a seam reason). The review is read THROUGH `route_of` - the ONE reader of the critic's
        form for the S5 loop, the seam's gate and the close predicate (AR-13): `test_defect` / `mechanical` -> retry, a `close` over
        the spent cap (`cap`) -> retry too (the loop then meets the limit question, `s7.repair_limit`: another round or the limit
        answer, never a silent stop), any other `close` with a `code` (budget unknown, nobody's round) -> no_progress, a `close`
        without one and with no `rejected` row -> repaired. ERROR DIRECTION: only a
        clear approval repairs; a doubt stops the test, and the debt stays in the triage row (FR-59)."""
        import repair_route
        import role_digest
        thing, done = ("reorder", "reordered") if what == "reorder" else ("repair", "repaired")      # the default words stay byte for byte
        parsed = role_digest.parse(digest)
        if role_digest.is_halting(digest):
            print(f"S7: {test} - the critic of the {thing} round cannot go on; the round is stopped")
            return "no_progress"
        states = {r["state"] for r in parsed.get("rows") or []}
        if "unverified" in states:
            print(f"S7: {test} - the critic could not verify the {done} test; the round is stopped")
            return "no_progress"
        verdict = str((parsed.get("header") or {}).get("verdict") or "")
        if verdict not in ("ok", *repair_route.SEND_BACK):
            print(f"S7: {test} - the critic's review ({verdict or 'no verdict'}) does not approve the {thing}; the round is stopped")
            return "no_progress"
        route, _form = self.route_of(digest, self.budget_or_none("S5", "qa-automator", [case] if case else []))
        if route["action"] in ("test_defect", "mechanical"):
            print(f"S7: {test} - the critic sent the {thing} back ({route['reason']}); one more round")
            return "retry"
        if route["code"] == "untyped":      # F4 (e): no round on a cause nobody wrote; the debt stays in the triage row
            print(f"S7: {test} - the critic sent the {thing} back without a typed finding; the round is stopped")
            return "no_progress"
        if route["code"] == "cap":
            print(f"S7: {test} - the critic sent the {thing} back and the repair cap is spent; the limit question decides")
            return "retry"          # the loop's top meets counted >= cap: `s7_limit` asks the person (spec 5.7 p.4), never a silent stop
        if route["code"] or "rejected" in states:
            print(f"S7: {test} - the critic's review ({route['reason'] if route['code'] else 'a rejected row'}) does not approve the "
                  f"{thing} and no further round runs; the round is stopped")
            return "no_progress"
        return "repaired"

    def s7_green_outside(self, life: str, ident: str, row: dict | None = None, test: str = "", case: str = "", was_rejected: bool = False) -> bool:
        """E12: a round of this life that finished OUTSIDE the loop (a relaunch, `wait_existing_job`): its dispatch id was recorded
        before it started (`s7_round`); when the controller accepted it and its saved digest is green, the test is repaired. A
        relaunch gets a new id, so it is `not green` here - one more round below the cap, the question at it. RD1-9b: a test the
        critic had rejected (`was_rejected`) is repaired only by the critic's word. (a) A review of this life already ACCEPTED
        (`review_round`) is read once and decides; `retry` clears the mark and the loop goes on to the author (the read review is
        never read twice). (b) Else a green accepted author round leads to the review, not to `repaired`. A `review_round` that was
        not accepted is a new entry: a green `round` leads to a NEW review (a relaunch gets a new id)."""
        kept = (((self.state.get("s7_rows") or {}).get(life) or {}).get(ident) or {}) if life else {}
        review = str(kept.get("review_round") or "")
        if review and ((self.controller_state().get("dispatches") or {}).get(review) or {}).get("status") == "accepted":
            end = self.s7_reorder_outcome(self.saved_done(review), test, case, what="repair review")
            if end == "retry":
                self.s7_mark(life, ident, review_round="")
                return False
            self.s7_mark(life, ident, outcome=end)
            return True
        rid = str(kept.get("round") or "")
        if not rid or ((self.controller_state().get("dispatches") or {}).get(rid) or {}).get("status") != "accepted":
            return False
        import role_digest
        states = {r["state"] for r in role_digest.parse(self.saved_done(rid)).get("rows") or []}
        if not states & {"green", "passed", "fixed"}:
            return False
        if was_rejected:
            print(f"S7: the round {rid} finished green outside the loop; the critic reviews the repaired test")
            end = self.s7_review_repair(row or {}, test, case, life, ident)
            if end == "retry":
                return False
            self.s7_mark(life, ident, outcome=end)
            return True
        print(f"S7: the round {rid} finished green outside the loop; the test needs no further round")
        self.s7_mark(life, ident, outcome="repaired")
        return True

    def s7_round(self, row: dict, test: str, case: str, counted: int, cap: int, owed: dict | None, life: str = "", ident: str = "") -> str:
        """One S7 repair round of `test` (the author on its window); returns the author's digest. `owed`: the person's answer `round`
        at the repair limit - marked executed BEFORE the dispatch (a crash costs one round, never two), and taken back when the
        controller refused to START the round (no role ran, `last_dispatch` is unchanged): the person's round is then still owed
        (t-760 row 3, the same shape as `stage_S5`). The round's dispatch id is recorded for (life, test) the moment `rework`
        has it (N9), so a round that finishes outside the loop is found on re-entry (`s7_green_outside`)."""
        before = getattr(self, "last_dispatch", "")
        if owed:
            owed["executed"] = True
            self.save_state()
        import s7_reorder
        import s5_precheck
        if s7_reorder.wants_reorder(row):
            return self.s7_reorder_round(row, test, case, ident or self.s7_ident(row), owed, life, before)
        try:
            digest, _next = self.rework("S5", "qa-automator", [case] if case else [],
                                        f"{s5_precheck.S7_FIX_PREFIX}: {test} — verdict {row.get('verdict')}", cause="test_defect",
                                        on_request=lambda rid: self.s7_mark(life, ident, round=rid),
                                        extra=[f"Fix: {test} — verdict {row.get('verdict')}, mechanism "
                                               f"{row.get('mechanism') or 'n/a'} (FLAKY only)",
                                               f"triage.json: qa-factory/artifacts/{self.task}/work/triage.json · "
                                               f"automation-manifest.json: qa-factory/artifacts/{self.task}/work/automation-manifest.json",
                                               f"Round: {counted + 1} of {cap}. Retry annotations and sleeps are forbidden; the "
                                               "Then-lines before and after your fix must match. Re-run only the failed "
                                               f"test - `run_suite.py --mine {case or '<CASE>'} --node-id <test> --purpose "
                                               "repair_verify`; FLAKY confirmation per s7.md (at most 3 "
                                               "flaky_diagnostic runs, S7)."])
        except ReworkRefused:
            if owed and getattr(self, "last_dispatch", "") == before:
                owed["executed"] = False
                self.save_state()
            raise
        return digest

    def s7_rejudge_round(self, row: dict, ident: str, life: str) -> None:
        """One S7 re-judge round of a manual check the analyst found misread (HF8-19): the runner judges the SAME captures again
        (`manual_evidence.py rejudge`, nothing is captured again) through `rework` of S6 on the one case, inside the open S7 - the
        way back into S7 is this function returning (`rework` is synchronous; the stage `completed` S6 stays so, `set_stage` is
        monotonic). The result is not read from the digest: `s7_close` -> `finalize_task` -> `fresh` judge the new record.
        THE LIMIT (not the controller's: these rounds are `reviewer_error` rounds, which spend none of the controller's repair cap, though
        `qa-runner` is a `REPAIR_LOOP_ROLES` member since X7-6c; the cap that counts is the consumer's `test_defect` rounds):
        `repair_cycles` rounds per (case, ROOT of the attempt), counted in `state["s7_rejudge"]` ACROSS lives - a new analyst
        life is a new triage, not a new dispute over the same captures; a re-capture is a new attempt and counts from zero. At
        the limit no round and no question: `outcome="limit"`, the red stands (`failed:RUNNER_MISREAD_EVIDENCE`, `no`, owner the
        factory, FR-59). The count is written the moment `rework` has the dispatch id (a crash costs one round, never two)."""
        from runtime_policy import DEFAULT_LIMITS
        if self.s7_outcome(life, ident):
            return
        case = str(row.get("case") or "").strip()
        mine = ((self.state.get("s7_rows") or {}).get(life) or {}).get(ident) if life else None
        rid = str((mine or {}).get("round") or "")
        if rid and ((self.controller_state().get("dispatches") or {}).get(rid) or {}).get("status") == "accepted":
            print(f"S7: the re-judge round {rid} of {case} finished outside the loop; the check needs no further round")
            self.s7_mark(life, ident, outcome="rejudged")
            return
        attempt = re.sub(r"-r\d+$", "", str(row.get("attempt_id") or "").strip())
        key = f"{case}|{attempt}"
        spent = [str(x) for x in ((self.state.get("s7_rejudge") or {}).get(key) or [])]
        limit = DEFAULT_LIMITS["repair_cycles"]
        if len(spent) >= limit:
            print(f"S7: {case} - the runner has judged this check again {len(spent)} times; it stays failed and the factory's reason says so")
            self.s7_mark(life, ident, outcome="limit")
            return
        block = row.get("contradiction") if isinstance(row.get("contradiction"), dict) else {}
        command = (f"python \"${{CLAUDE_PLUGIN_ROOT}}/scripts/manual_evidence.py\" rejudge --task-root \"{self.task_root}\" --case {case}"
                   + (f" --of-attempt {attempt}" if attempt else "")
                   + " --result <pass|fail|inconclusive> --actual \"<what the captures show>\" --then-quote \"<n>=<words>\" "
                     "--reason \"<why the first verdict was wrong, or why it stands>\"")

        def registered(new_id: str) -> None:
            self.state.setdefault("s7_rejudge", {}).setdefault(key, []).append(new_id)
            self.s7_mark(life, ident, round=new_id)
            self.save_state()
        # `ReworkRefused` is raised before `on_request` (nothing is counted yet) and goes up to the seam as it is: no take-back needed
        self.rework("S6", "qa-runner", [case], f"S7 re-judge: {case}", cause="reviewer_error", complete=False,
                    on_request=registered,
                    extra=["Execution kind: manual — do not capture again unless the re-judge is refused",
                           f"S7 re-judge of {case}: the failure analyst found that your verdict on attempt {attempt or 'the latest'} "
                           "contradicts the text that attempt itself captured. Read those captures again and judge them; nothing "
                           "is captured again and the check is not run again.",
                           f"Then {block.get('then')}: you said — {block.get('runner_said')}",
                           f"The analyst's quote: {block.get('quote')} (file: {block.get('evidence')})",
                           "Record your judgment, then `finalize_task.py <task root>`: " + command,
                           "You decide: the analyst's reading is an input, not an order. When the captures still support your "
                           "verdict, record it again with the same command and say why."])
        self.s7_mark(life, ident, outcome="rejudged")

    def s7_reorder_round(self, row: dict, test: str, case: str, ident: str, owed: dict | None, life: str, before: str) -> str:
        """One S7 `reorder` round of `test` (t-1508 R7), the same steps the conductor runs by hand (`phases/s7.md`, Repair): the
        snapshot (`s7_reorder.start`), the author's rework (reason `S7 reorder: <test>`, cause `test_defect` - the cap is the
        window's, shared with the S5 rounds), `s7_reorder.finish` (shape of the edit, red run, carried row) and the critic of that
        one test (reason `S7 reorder review: <test>`). Returns the CRITIC's digest; `ReorderRefused` from `start` / `finish` goes
        to the loop, which stops on `green` and counts anything else. `ReworkRefused` is raised as in any round (the plan is not
        rolled back without a decision). A round already carried and not yet judged (the driver fell after `finish`) goes straight
        to its critic - no second author over the moved bytes (AR-25). A refusal BEFORE any role ran (`start`, or the author's
        registration) takes the person's owed round back, as in `s7_round` (F10)."""
        import s7_reorder
        cases = [case] if case else []

        def took_back() -> None:
            if owed and getattr(self, "last_dispatch", "") == before:
                owed["executed"] = False
                self.save_state()
        try:
            done = s7_reorder.carried_round(self.task_root, ident, self.project)
            started = {} if done else s7_reorder.start(self.task_root, ident, self.project)
        except s7_reorder.ReorderRefused:
            took_back()
            raise
        if done is None:
            red = s7_reorder.red_thens(self.task_root, row, ident)
            try:
                self.rework("S5", "qa-automator", cases, s7_reorder.AUTHOR_REASON.format(test=test), cause="test_defect",
                            on_request=lambda rid: self.s7_mark(life, ident, round=rid),
                            extra=s7_reorder.author_brief(test, s7_reorder.moved_thens(row), red))
            except ReworkRefused:
                took_back()
                raise
            done = s7_reorder.finish(self.task_root, ident, self.project)
        print(f"S7: {test} - the reorder is carried to attempt {done['attempt']}; the critic reviews that one test"
              + (f" (snapshot {started.get('snapshot')})" if started.get("snapshot") else ""))
        digest, _next = self.rework("S5", "qa-code-critic", [done["case"]] if done.get("case") else cases, done["critic"]["reason"],
                                    cause="test_defect", extra=done["critic"]["brief"])
        return digest

    # --- the S7 repair limit through the one seam (C1-5b2, t-698 §4.4) ----------------------------------------------------------
    # One question per (test, count, life): the answer is kept under a slot of that triple (`state["repair_limit_s7"]`, apart from the S5
    # windows' `repair_limit`, whose readers match a window by its cases). The question is the S5 one's machinery (`repair_limit_raise`,
    # `repair_limit_person`, `_answer_repair_limit`); the S7 answers are `round` / `debt` / `stop` - no `fixed` (re-running a test after
    # the person's own edit is S6's run, FR-9: it has no executor here) and no `review` (the person is not offered a review; a repair of a
# test the critic had rejected ends in a critic review of that one test, run by the loop itself: `s7_review_repair`).

    @staticmethod
    def s7_slot(ident: str, life: str, counted) -> str:
        """The slot of one test of one life at one count (`unknown` for no count): free of colons, so it can ride as the question's dispatch."""
        return ("S7-" + hashlib.sha256(f"{ident}|{life}".encode("utf-8")).hexdigest()[:12] + "-"
                + (str(counted) if isinstance(counted, int) else "unknown"))

    def s7_limit(self, test: str, ident: str, tests: list, bound: bool, case: str, budget, life: str) -> dict:
        """The person's answer for this test in this life (the kept record), or the question: ONCE per (test, life, count) - an answer
        recorded for the slot is returned on every later loop turn and every later entry, and nothing is asked again. A `debt` is FINAL
        for its test within a life: it is found before the count is read, so a sibling that moves the shared count never re-asks it.
        `ident`: the triage row's own name (`s7_ident`), the key of the record and of the slot. Under life `""` no record is trusted."""
        slot =self.s7_slot(ident, life, budget["counted"] if self.repair_countable(budget) else None)
        kept = list((self.state.get("repair_limit_s7") or {}).values()) if life else []
        found = next((r for r in kept if isinstance(r, dict) and r.get("life") == life and r.get("ident") == ident
                      and r.get("token") == "debt"), None) \
            or next((r for r in kept if isinstance(r, dict) and r.get("dispatch") == slot and r.get("life") == life), None)
        if found:
            return found
        ask = self.s7_limit_facts(slot, test, ident, tests, bound, case, budget, life)
        if ask["code"] == "cap" and not ask["passes"]:
            self.repair_older_controller("S7", slot, budget, "still fail after their repairs")
        self.repair_limit_raise(ask)

    def s7_limit_facts(self, slot: str, test: str, ident: str, tests: list, bound: bool, case: str, budget, life: str) -> dict:
        """The facts of the S7 question (the shape `repair_limit_person` and `_answer_repair_limit` read): the cap is spent (`cap`,
        with `round`) or the count cannot be read (`unknown`, no `round`: no round is started blind). The lead names the test and the
        count in words (A6: no id, no cause token). `tests` are the ledger refs of the debt entry; `bound` says whether a test of the
        plan answers this row (the `debt` words promise nothing about the report when none does, N5)."""
        countable = self.repair_countable(budget)
        counted, cap = (budget["counted"], budget["cap"]) if countable else (None, None)
        head, where = (f"For {case}: ", "the tests of this case") if case else ("", "this test")      # `For TC-1:` explains the id (human-questions.md)
        if countable:
            opening = (f"{head}{test} still fails in the test run, and the failure is in the test itself. The test writer has already "
                       f"repaired {where} {counted} times, the rounds after the critic's review included; the factory's limit for "
                       f"that is {cap} rounds, and it is used up.")
        else:
            opening = (f"{head}{test} still fails in the test run, and the failure is in the test itself. The factory could not count "
                       f"how many repair rounds the test writer has already had on {where}, so it will not start another on its own; "
                       "starting a round is left out of the answers below.")
        passes = self.repair_passes(budget) if countable else None
        return {"stage": "S7", "dispatch": slot, "cases": [case] if case else [], "tests": list(tests), "name": str(test), "life": life,
                "ident": ident, "bound": bound,
                "key": "s7.repair_limit", "offer": ["round", "debt", "stop"] if countable else ["debt", "stop"],
                "code": "cap" if countable else "unknown", "lead": opening + "\n\nWhich of these should happen?", "cause": "",
                "passes": passes or {}, "counted": counted, "cap": cap, "round_counted": counted, "round_cap": cap, "reason": "",
                "by_cause": (budget.get("by_cause") if isinstance(budget, dict) else None) or {}}
