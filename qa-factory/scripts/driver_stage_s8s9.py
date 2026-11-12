"""driver_stage_s8s9.py - Driver members and names homed here by ai-packages/qa-factory/scripts/tests/fixtures/driver-layers.json (TD-11 cut by tools/source_split.py); no behaviour of its own."""

import hooklib  # noqa: F401 (console setup, K7)
import json
from pathlib import Path
import person_owned as PO
from driver_core import EXIT_GAVE_UP, EXIT_PERSON, Person, Refusal, _now, gate_refusal, json_record, mr_record
from driver_conductor import DELIVERY_RULE, last_json_line


S9_QUESTION = ("One question for the retro: what did you dislike in this session, what should "
               "change?\n(optional — reply 'skip')")


class DriverStageS8s9:
    def rebuild_report(self) -> bool:
        """`report_facts.py --write` for this story: the code-owned blocks of `test-report.md`, refreshed by
        code (R-212.1). Never a role's call and never a question to the person: a report problem is the
        factory's own, and the door is `--write`, the scribe's rework, or this printed line (FR-3, FR-42).

        A `write` that refuses (`ok: False`: damaged markers, no report, an older contract) is ONE printed line
        with its own lines and the story goes on - the S9 exit checks the report itself and refuses with the
        doors; a `write` that raises is "report rebuild could not run: <type>: <why>" and the story goes on
        (P1). A second write over unchanged facts changes nothing (P7) and its output is not printed again.
        True when the blocks are as they should be."""
        try:
            code, out = self.py("report_facts.py", "--task", self.task, "--write")
        except Exception as exc:
            print(f"report rebuild could not run: {type(exc).__name__}: {str(exc)[:160]}")
            return False
        lines = [line.strip() for line in (out or "").splitlines() if line.strip()]
        if code and any(line.startswith("Traceback (most recent call last)") for line in lines):
            print(f"report rebuild could not run: {lines[-1][:200]}")      # the script's own `<type>: <why>`
            return False
        shown = ("report rebuild refused, the report is as it was: " + " | ".join(lines)) if code else \
                "\n".join("report: " + line for line in lines)
        if code and not lines:
            shown = f"report rebuild refused, the report is as it was: report_facts.py exited {code} and said nothing"
        if shown and shown != getattr(self, "_report_shown", None):
            print(shown)
        self._report_shown = shown
        return not code

    def stage_S8(self) -> None:
        import acceptance
        # X7-6b: the analyst's last dispatch when S7 awaits its consumer (the one reader, AR-13). POSITION: the scribe is let in by the controller
        # while S7 awaits; a verdict (or a scribe that already worked) left by a restart is settled BEFORE the scribe is dispatched again.
        awaiting = acceptance.awaits_acceptance(self.controller_state(), "S7", self.pipeline())
        if awaiting and self.consumer_settled("S7", self.controller_state(), awaiting, True):
            return
        root = f"qa-factory/artifacts/{self.task}"
        # The three scripts, in this order (a later one reads an earlier one's product; a G refusal in the middle makes `retry` run the
        # WHOLE step again, E1). L1: check_traceability writes nothing (M1, t-1214: `walk` only reads; `main` only prints), and its exit 1
        # is a legitimate "gaps found" the decisions that need it (gate_preflight, check_delivery) read from the register themselves.
        # remains: L1 - a read-only check whose "no" (exit 1: gaps found) is an answer, never a conductor call (E2); nothing waits on its exit
        code, out = self.py("check_traceability.py", root)
        print(f"check_traceability.py: exit {code} — " + (out.splitlines()[-1] if out else ""))
        # G4: `work/ledger.json` and `work/ledger.md` are inputs of the scribe and of check_delivery; ledger.py exits 1 for "no such
        # directory" or a crash, never for a "no" (ledger.py:1078-1090)
        try:
            code, out = self.py("ledger.py", root, check=True, expect="work/ledger.json and work/ledger.md written")
        except Refusal as refusal:
            refusal.retry = self.stage_S8           # E1: the WHOLE step again - a later script reads this one's product
            raise
        print(f"ledger.py: exit {code} — " + (out.splitlines()[-1] if out else ""))
        # L2 / F4 (M2, t-1214: check_delivery.py REWRITES work/ledger.json, ledger.md, delivery-summary.* and evidence/index.json with the
        # verdict, and the scribe reads them): the record is read through `delivery_verdict.word_of`, never the exit code - 1 is a legitimate
        # `no` / `after_checks` (E2). A record with no readable word, a crash or a timeout (124) established nothing: a G refusal (the
        # factory's own) BEFORE the scribe reads a ledger the check did not write.
        code, out, word = self.delivery_record(root)
        print(f"check_delivery.py: exit {code} - the word it printed: {word or 'none'}")
        if word is None:
            raise gate_refusal("check_delivery.py", code, out, "work/ledger.json written with the delivery verdict (a readable word)",
                               retry=self.stage_S8)
        complete, extra = True, self.role_lines("S8", "qa-doc-scribe")
        if awaiting:
            # X7-6b. POSITION: the record is written from the scribe's FINISH, BEFORE the controller accepts it as S8 work, and never by the
            # analyst's own finish. `True` (today's close of S8) is the scribe's own completion on an accept.
            complete = self.consumer_completion("S7", True)      # the repair budget is read only if the verdict is a reject (B1)
            extra += [f"You also accept or return the analyst's handoff ({awaiting}): the verdict is `header.verdict` of your form (`ok` accepts it; "
                      "`concerns` sends it back and needs the section `stage_acceptance`), and `inputs_read` names the analyst's form "
                      "work/handoffs/" + awaiting + ".yaml. A concern about the report itself belongs in `unresolved`."]
            extra += self.s7_places_scribe_line()        # t-1991 U3a: settled / unsettled places, with the source of each expectation
        self.run_role("S8", "qa-doc-scribe", complete=complete, extra=extra)
        if awaiting and self.consumer_settled("S7", self.controller_state(), awaiting, True, ran=True):
            return          # the analyst repairs in a fresh context; the scribe's report is stale and is written again after the new accept
        # t-204 F6 (R-212.1): the code-owned blocks of the report are rendered right here, once the scribe has
        # returned and BEFORE gate B is asked (the next boundary reads the report to build its packet), so the
        # person reads a code-checked report and not the scribe's own arithmetic. POSITION INVARIANT: after the
        # scribe's finish and before `self.gate("B")` - what the rebuild never touches is the bug reporter,
        # which runs after gate B and has its own boundary. Its refusal or crash is ONE printed line and the
        # story goes on (P1, FR-3): S9's exit checks the report itself and names the doors. A story whose S8
        # ran before this change has no markers; its first `--write` converts the report (P7).
        self.rebuild_report()
        # RD1-20: the MR description quotes the report's "Left with you" section, and the scribe and the rebuild above have just
        # changed it - the summary is written again here, over the report as it stands now, whether or not the rebuild held (the
        # summary is its own record). POSITION INVARIANT: after the rebuild, so the quoted section is the one the person reads.
        # remains: a failure here is one line, S8 goes on and S9 writes the summary again
        code, out = self.py("delivery_summary.py", "--task-root", str(self.task_root))
        if code:
            print(f"delivery summary not rewritten after the report (exit {code}); S9 writes it again: "
                  + ((out or "").splitlines() or ["no output"])[-1][:160])

    def recompute_verdict(self) -> str:
        """The delivery verdict, computed again from what the person's gate B answers recorded (t-305 N8, F5, N-4), and the
        report brought up to it, BEFORE any act the verdict gates. The order is the position invariant - no verdict-gated act
        (the bug reporter, the MR, an outward write) reads a word, a head or a "Left with you" section older than the person's
        answers:
          (1) the answers were recorded at `take_answer` (`take_stand_gap_answers`: the typed waivers);
          (2) the three scripts of S8 run again over the story as it now stands (the ledger, the word W2, `left_items`);
          (3) `report_facts --write` renders the code-owned blocks from W2 and the typed items - the head, and the block
              "Added after gate B (from your answers)", one line per item an answer of theirs left with them;
          (4) `report_facts --check` must pass (it does by construction for the new items): a failure is a finding of the
              factory with the scribe's door, and the delivery does NOT run;
          (5) the head is the one `--write` just rendered (with the "Changed since gate B" notice when W1 differs);
          (6) the MR description is rebuilt from the report as it now stands (`delivery_summary`).
        Returns W2: `yes`, `after_checks`, `no`."""
        root = f"qa-factory/artifacts/{self.task}"
        # O5 (C1-7c), the two kinds of S8's loop as C1-7b built them (L1 and G4), and the same order (a later script reads an earlier
        # one's product). L: check_traceability writes nothing (M1, t-1214: `walk` only reads, `main` only prints), so no product is left
        # unwritten by it; its exit 1 is a legitimate "gaps found" that the decisions needing it (gate_preflight, check_delivery) read
        # from the register themselves; with no artifacts directory it prints one line and exits 1 and the ledger step below refuses.
        # remains: L - a read-only check whose "no" (exit 1: gaps found) is an answer, never a conductor call (E2); nothing waits on its exit
        code, out = self.py("check_traceability.py", root)
        print(f"gate B: check_traceability.py: exit {code} — " + (out.splitlines()[-1] if out else ""))
        # G: `work/ledger.json` / `ledger.md` are what `check_delivery` (the word W2) and the report read; ledger.py exits 1 for "no such
        # directory" or a crash, never for a "no" (ledger.py:1078-1090). A failed ledger is a `Refusal`; the delivery does NOT go on over
        # the ledger the answers did not rewrite. `retry` runs the WHOLE step again (E1): the caller of this function is `stage_S9`
        # (through `after_gate_B`), and a retry that reran only the ledger would end the step before the word, the report and the
        # delivery were reached
        try:
            code, out = self.py("ledger.py", root, check=True,
                                expect="work/ledger.json and work/ledger.md rewritten with the verdict row over the answers recorded at gate B")
        except Refusal as refusal:
            refusal.retry = self.stage_S9
            raise
        print(f"gate B: ledger.py: exit {code} — " + (out.splitlines()[-1] if out else ""))
        # F4 (FR-59): the verdict is the word the check PRINTS (`--json`), never its exit code: the check exits 1 for `no`,
        # for `after_checks` and on a crash alike. A check that crashes, times out or prints nothing parseable has
        # established nothing: the delivery does NOT go on over the word the ledger held before the answers (the ledger is
        # left as it was), and the driver stops with the factory's own reason in words.
        word = self.delivery_check_word(root)
        if not (self.task_root / "test-report.md").is_file():
            # nothing is stale where nothing is written: S8's own exit owns "there is a report" (FR-41: said, not silent)
            print("gate B: there is no test-report.md to bring up to the new verdict")
            return word
        self.rebuild_report()
        code, out = self.py("report_facts.py", "--task", self.task, "--check")
        lines = [line.strip() for line in (out or "").splitlines() if line.strip()]
        if code:
            if self.delivery_declined():        # the person said `no delivery` to this very question: nothing goes out, nothing asks again
                print("gate B: the report does not match your gate B answers; the delivery was declined, so the report stays as it is")
                return word
            # remains: the site's own closed question (`s8.report_match`: `no delivery` / `stop`, each with an executor in `_take_report_match_answer`)
            raise self.report_match_person(lines)
        # O6 (C1-7c, kind G): the MR description (`work/delivery-summary.json` / `.md`) is what the delivery sends out; the ledger step above
        # wrote it already (ledger.py:1065 `write_delivery_summary`) and this call writes it again over the report as it now stands. A
        # non-zero exit is a `Refusal`: the delivery does not go out over a description the answers did not rewrite. `retry`: the whole step
        try:
            self.py("delivery_summary.py", "--task-root", str(self.task_root), check=True,
                    expect="work/delivery-summary.json and work/delivery-summary.md rewritten from the report as it now stands (the MR description)")
        except Refusal as refusal:
            refusal.retry = self.stage_S9
            raise
        return word

    def delivery_declined(self) -> bool:
        """Did the person end the delivery (`no delivery`, `_decline_delivery`)? The two checks of S9 that would ask again do not."""
        return (self.state.get("delivery") or {}).get("action") == "declined_by_person"

    def report_match_person(self, lines: list) -> Person:
        """`s8.report_match` (C1-6c, S8 of the census): the report does not match the answers recorded at gate B. The factory's own gap
        reaches the person as `no delivery` / `stop` only, never as a choice to own the gap (A10, FR-3). `rebuild` is NOT offered: the
        controller refuses the scribe's rework it would run (see the handoff, Q1) and an option whose executor is refused is never
        offered (FR-9). The mismatch lines are the lead; the whole list is the details file. No command in the text (J3)."""
        shown = "; ".join(" ".join(line.split())[:200] for line in lines[:6])
        lead = ("The report does not match what your gate B answers recorded, so nothing was delivered: " + shown + ". This is the "
                "factory's own gap, not a choice of yours.\n\nWhat I need from you is one of these:")
        text = self.closed_question("s8.report_match", lead, [
            {"answer": "no delivery", "token": "no delivery", "says": "end the delivery here; nothing is sent out and the report stays as it is"},
            self.STOP_OPTION])
        return Person("report_match", text, "S8", details="\n".join(lines))

    def delivery_record(self, root: str) -> tuple:
        """THE read of the delivery verdict (C1-7b fix round, F-1, FR-14; AR-13, AR-28): run `check_delivery.py --json` and return
        `(exit code, output, word)`. The word is the one the check PRINTED (`yes`, `after_checks`, `no`), read by
        `delivery_verdict.word_of` from the record `json_record` parsed - never from the exit code: exit 1 with a readable `no` is the
        word `no` (E2, a legitimate answer). The word is None - the caller refuses, a word is never guessed and never a pass - when
        the exit is outside {0, 1} (a crash, a usage error, 124 the timeout), there is no record, the record is unreadable or it holds
        no word of the three. It raises nothing itself (`py` is called without `check`); each caller words its own refusal."""
        import delivery_verdict as DV
        code, out = self.py("check_delivery.py", root, "--json")
        doc, _after = json_record(out)
        word = DV.word_of(doc) if code in (0, 1) and isinstance(doc, dict) and "delivery_verdict" in doc else None
        return code, out, (word if word in ("yes", "after_checks", "no") else None)

    def delivery_check_word(self, root: str) -> str:
        """Run `check_delivery.py --json` and return the word it PRINTED (`yes`, `after_checks`, `no`) - read by
        `delivery_record` (the one reader; C1-7b F-1), never from the exit code. Raises `Person` (`s8.delivery_check`: the
        driver asks, nothing is delivered, the ledger keeps its word, ONE defect is filed; C1-6c) when the check crashes, times
        out, prints nothing parseable or prints a record with no readable word (FR-59: a gate does not decide on an unknown). The
        text is the factory's own gap in words: no script name, flag or exit code in it; the operator's log line carries those."""
        code, _out, word = self.delivery_record(root)
        print(f"gate B: check_delivery.py: exit {code} - the word it printed: {word or 'none'}")
        if word is None:
            if self.delivery_declined():        # `no delivery` was the answer: a check that cannot answer is no pass (FR-59), and the verdict is `no`
                print("gate B: the delivery check could not answer; the delivery was declined, so the verdict is `no`")
                return "no"
            # C1-6c (S9 of the census): the factory's own gap is ONE defect (owner: factory) and a closed question, never a promise that
            # nobody carries out. A crash is never a pass (AR-28): nothing is delivered until the check answers or the person ends it.
            self.file_defect(self.boundary, "owner: factory — the delivery check could not say whether the story is ready after the "
                                            f"person's gate B answers (exit {code}, the word it printed: {word or 'none'})")
            lead = ("The delivery check could not say whether the story is ready after your answers (it stopped, or printed nothing the "
                    "factory can read), so nothing was delivered and the verdict the story had before your answers stands unchanged. "
                    "This is the factory's own gap, recorded as one, not a choice of yours.\n\nWhat I need from you is one of these:")
            # remains: the site's own closed question (`s8.delivery_check`: `retry` / `no delivery` / `stop`, each with an executor in `_take_delivery_check_answer`)
            raise Person("delivery_check", self.closed_question("s8.delivery_check", lead, [
                {"answer": "retry", "token": "retry", "says": "the check runs again now"},
                {"answer": "no delivery", "token": "no delivery", "says": "end the delivery here; nothing is sent out"},
                self.STOP_OPTION]), "S8")
        return word

    def after_gate_B(self) -> None:
        """What the person decided at gate B is carried out here, order by order (t-1509, GB-1b): the bug reporter for a `bugs`
        order that is due, the delivery for an `mr` order that is due, each order settled by the controller's one producer
        (`gate_b_orders`; the reporter's accept or release settles `bugs`, `settle_order` settles `mr`). Idempotent: an order
        that is not due is not touched, and a delivery that left its mark is never run again (t-017 D3)."""
        import controller as C
        # FIRST (t-305 N8): the verdict W2, from the answers just recorded - above the reporter dispatch and `delivery`
        self.recomputed_word = self.recompute_verdict()
        state = self.controller_state()
        latest = C.latest_gate_b(state) or {}
        decision = latest if latest.get("status") == "approved" else {}
        statuses = C.gate_b_orders(state)
        if statuses.get("bugs") == C.ORDER_DUE and "bugs" not in self.gate_b_ran:
            # once per process: a reporter that ran and left its order due is not sent again by the next pass (the seam is)
            self.gate_b_ran.add("bugs")
            self.run_bug_reporter(decision)
        # HF8-22 F-2: the reporter filed after the summary above was written, so the report and the MR description still say "chosen
        # at gate B, not filed yet" about a bug that is filed. Outside the once-per-process `if`: a resume repeats it. The verdict is
        # NOT computed again (only the text over the files as they now lie), and nothing is redone once the MR is open.
        self.refresh_after_reporter()
        self.settle_mr(decision, statuses)

    def refresh_after_reporter(self) -> None:
        """The report's code-owned blocks and the MR description (`work/delivery-summary.*`) rebuilt over the bug files the reporter just
        wrote - the same two scripts `recompute_verdict` ends with, minus the verdict. A refusal of the description is a `Refusal` that
        retries the whole S9 step, as there. Nothing to do without a report, or when the delivery already left its mark."""
        if self.state.get("delivery") or not (self.task_root / "test-report.md").is_file():
            return
        self.rebuild_report()
        try:
            self.py("delivery_summary.py", "--task-root", str(self.task_root), check=True,
                    expect="work/delivery-summary.json and work/delivery-summary.md rewritten over the bug files the reporter wrote")
        except Refusal as refusal:
            refusal.retry = self.stage_S9
            raise

    def run_bug_reporter(self, decision: dict) -> None:
        """The executor of the `bugs` order. The person's word is the authority, not the draft list: at gate B of TP1-13797
        the owner ordered a bug draft for the missed UI scope while S7 had left no drafts behind. Whether anything is to be
        filed is the reporter's own judgement, and "nothing to file" is a complete answer that costs one dispatch to hear; a
        phrase list in code decides it for the person. It runs after `no delivery` too (F-7, the owner 28.10.2026: "only the
        MR"): it writes a local file and nothing is sent out (agents/qa-bug-reporter.md)."""
        drafts = [d for d in (decision.get("selected_drafts") or []) if d]
        words = str(decision.get("authorization_source") or "")
        # An experiment's reporter is told, in its own dispatch, that the tracker is not a
        # channel it may propose for (t-017 D3, FR-36): the packet the person read said so too.
        experiment = (["This run is an experiment: treat the bugs channel as markdown and write "
                       "no proposal for a tracker."] if self.no_trace() else [])
        self.run_role("S8", "qa-bug-reporter", complete=False,
                      extra=(["Chosen drafts: " + ", ".join(str(d) for d in drafts)] if drafts else
                             ["S7 left no bug drafts, so nothing is pre-chosen: read the gate-B decision "
                              "below and file exactly what the person's own words order there — a local "
                              "proposal under qa-factory/bugs, grounded in the register and the report, "
                              "submitted nowhere. If their words order no bug, file none and say so in "
                              "your digest: that is a complete answer, not a gap."]) +
                            [f"Gate B decision: {words[:2000]}",
                             "Drafts the person called not a bug are neither filed nor deleted."] + experiment)

    def settle_mr(self, decision: dict, statuses: dict) -> None:
        """The `mr` order: the ONE place it is worked out (AR-14). A decision recorded before 0.10.5 carries no orders (B6): its
        delivery runs as it always did when no mark exists, and no order is tracked. For a decision with orders the delivery runs
        only while `mr` is due and no mark exists; the mark - however it was left, also by a process that died right after it -
        is then settled (`settle_mr_from_mark`), so the delivery never runs twice."""
        import controller as C
        # Any truthy mark is "done": since t-017 D3 the driver writes it only on `continue` (or the
        # experiment's null outcome), but a mark an older driver wrote on `ask_person`/`stop` has no
        # `done` key and is still truthy - that story is not delivered a second time (conservative).
        if not isinstance(decision.get("orders"), dict):
            if not self.state.get("delivery"):
                self.delivery(decision)
            return
        if statuses.get("mr") != C.ORDER_DUE:
            return
        if not self.state.get("delivery"):
            self.delivery(decision)
        self.settle_mr_from_mark()

    def settle_mr_from_mark(self) -> None:
        """Settle the `mr` order from the delivery mark (t-1509 B5, F-11). The mark is the delivery step's own record: `mr` is the
        link or id its verdict named (a field, never searched for in the prose of `did`, FR-12). `done` only with that record;
        a delivery that opened no MR, or went nowhere (an experiment), is called off with the factory's coded reason and the
        step's one-line record; the person's `no delivery` is called off with THEIR words (FR-8). A repeat is the same answer."""
        import controller as C
        mark = self.state.get("delivery") or {}
        if not mark:
            return
        action, did = mark.get("action"), " ".join(str(mark.get("did") or "").split())
        ref = f"--ref={did[:C.SETTLE_REF_MAX] or 'the delivery mark holds no record of what went out'}"
        mr = str(mark.get("mr") or "").strip()
        if action == "declined_by_person":
            path = str(mark.get("words_file") or "")
            if not path or not Path(path).is_file():
                raise Refusal("The delivery was declined by the person, but the file with their words is gone, so the merge request "
                              "order cannot be called off with them. The conductor writes their earlier words (`no delivery` and what they "
                              f"added) to a file and calls the order off: `controller.py --task-root {self.task_root} --operation "
                              "settle_order --order mr --outcome cancelled --words-file <that file>`.",
                              title="declined_words_missing")
            args, outcome = ["--outcome", "cancelled", "--words-file", path], "cancelled"
        elif action == "nothing_outward":
            args, outcome = ["--outcome", "cancelled", "--reason-code", "no_trace", ref], "cancelled"
        elif mr:
            args, outcome = ["--outcome", "done", f"--ref={mr[:C.SETTLE_REF_MAX]}"], "done"
        else:
            args, outcome = ["--outcome", "cancelled", "--reason-code", "delivered_without_mr", ref], "cancelled"
        self.controller("settle_order", "--order", "mr", *args)
        print(f"gate B: the merge request order is {outcome} ({action or 'delivery'})")

    def person_answers(self) -> list:
        """The person's answers recorded for this story, oldest first (the project journal's
        `human_answer` events, the same source the briefs read)."""
        try:
            import brief_pack
            return brief_pack.answers_of(self.task, self.project)
        except Exception:
            return []

    def outward_rule(self) -> str:
        """The delivery prompt's line about writing outward. Since t-017 D3 it follows the run's
        record and the project's own channels, instead of the fixed sentence that named one
        tracker: the channels are `config.external_writes` unless the run is closed."""
        import external_writes
        closed = external_writes.closed_by_run(self.task_root)
        if closed:
            return (f"This run is closed for outward writes ({closed}): no tracker write and no "
                    "external_writes.py.")
        ext = self.config.get("external_writes") or {}
        named = [f"{kind}={ext[kind]}" for kind in ("bugs", "cases")
                 if str(ext.get(kind) or "markdown").strip() not in ("", "markdown", "none", "file")]
        return ("A tracker is written only through external_writes.py and only for the channels "
                "config.external_writes names (" + (", ".join(named) or "none: bugs and cases are markdown")
                + "); nothing else writes to a tracker.")

    def delivery(self, decision: dict) -> None:
        self.boundary = "S8:delivery"
        # INVARIANT (t-017 D3, delta 8b): a delivery with outward effects never runs twice. (1) The
        # mark `state["delivery"]` exists only after a `continue` verdict, or after the
        # experiment's null outcome below - `ask_person` and `stop` leave none, so the person's
        # answer re-enters this step; (2) at most ONE conductor call per driver process (the
        # refusal below); (3) every call carries every earlier attempt, verbatim - including a call
        # that was recorded as started and never reported back (`in_flight`, written before the call
        # and replaced by its verdict), so a process that died inside a call is not forgotten by the
        # next one. The residual risk - a conductor that repeats a step it was told already happened,
        # or one whose interrupted call left effects nobody recorded - is held by that prompt and by
        # nothing in code, and this comment says so (FR-41): it is not a guarantee.
        if self.no_trace():
            # The null outcome (FR-23): nothing goes out, the conductor is not called, external_writes
            # does not run, and that is recorded as the delivery's own state. FIRST in the step so
            # that no line below it - the conductor, the channels - is reachable in an experiment.
            did = "nothing outward (experiment): no branch, commit, push, merge request or tracker write"
            self.state["delivery"] = {"done": True, "at": _now(), "action": "nothing_outward", "did": did}
            self.save_state()
            self.journal_run({"kind": "delivery", "outcome": "nothing_outward"})
            print(f"delivery: {did}")
            return
        calls = getattr(self, "_delivery_calls", 0)
        if calls:
            raise Refusal(
                "The delivery - the branch, the commits, the push and the Draft merge request - was "
                "already handed to the conductor once in this run, and a second hand-over in the same run "
                "could create them twice, so nothing was repeated. To go on, answer `retry`: the delivery "
                "is asked again with the record of everything that already went out, and the conductor is "
                "asked to reuse it.", title="second_delivery")
        self._delivery_calls = calls + 1
        phase = self.plugin / "skills/qa-story/phases/s8.md"
        text = phase.read_text(encoding="utf-8", errors="replace") if phase.is_file() else ""
        start = text.find("## 4. Record, then execute verbatim")
        end = text.find("## Exit", start)
        section = text[start:end] if start >= 0 else text[:6000]
        conventions = json.dumps(self.config.get("git_conventions") or {})
        vcs = json.dumps((self.config.get("adapters") or {}).get("vcs") or {})
        suffix = self.flags.branch_suffix or ""
        prompt = "\n".join([
            f"Task: {self.task}. Project root: {self.project}. Plugin root: {self.plugin}. Task root: {self.task_root}.",
            "This is the DELIVERY after gate B: the bug reporter and the scribe are done; gate B is recorded.",
            # t-305 N8 (F5): the word is the one computed AFTER the person's gate B answers were recorded; on
            # `after_checks` the Draft MR is opened and its description carries the report's "Left with you" section
            f"Delivery verdict, recomputed after gate B: {getattr(self, 'recomputed_word', None) or self.delivery_word()}",
            f"Gate B decision, verbatim: {str(decision.get('authorization_source') or '')[:1500]}",
            # What the person said AFTER the gate belongs here too: a clarification recorded
            # as a human_answer was invisible to this step, and the delivery stopped on an
            # item the person had already settled (TP1-13797, driver run 3).
            "The person's answers recorded in this story, latest last: "
            + (" | ".join(self.person_answers()[-6:]) or "none recorded"),
            f"Delivery items recorded on the decision: {json.dumps({k: v for k, v in decision.items() if k in ('selected_drafts', 'action', 'deliver_with_risks', 'mr', 'items')}, ensure_ascii=False)[:800]}",
            f"git_conventions: {conventions}. VCS adapter: {vcs}. Branch name suffix to append: `{suffix}` (none when empty).",
            "Do exactly what the decision authorizes and nothing it does not: an MR is Draft. "
            + self.outward_rule() + " Commit by explicit path allowlists.",
            "Your job here is the delivery itself, in this order and nothing else: (1) the branch named by the "
            "conventions plus the suffix, (2) the commits by the decision's allowlist, (3) the push, (4) the Draft "
            "merge request. " + DELIVERY_RULE,
            "", "## The delivery section of phases/s8.md", section.strip(),
            "", "Answer with ONE JSON line last: {\"action\": \"continue|ask_person|stop\", \"did\": \"<what went out: commits, branch, MR url>\", "
                "\"question\": \"...\", \"why_person\": \"<a class of references/" + PO.FILE_NAME + ", with ask_person>\", "
                "\"mr\":\"<the Draft MR's url or id when one was opened or already exists; empty when none>\"}"])
        earlier = list(self.state.get("delivery_attempts") or [])
        if earlier:
            # What the earlier calls said went out, word for word: the only thing that keeps this
            # call from creating the branch or the merge request a second time. Every attempt is
            # listed (not the last), and an attempt that never reported back is listed as such.
            rows = [(f"{n}. a call started at {a.get('at')} and never reported back - what it did is unknown"
                     if a.get("in_flight") else
                     f"{n}. action: {a.get('action')} | did: {a.get('did') or 'nothing recorded'} | "
                     f"question: {a.get('question') or 'none'}") for n, a in enumerate(earlier, 1)]
            prompt += "\n\n## Earlier attempts at this delivery, oldest first, verbatim\n" + "\n".join(rows)
            if any(not a.get("in_flight") for a in earlier):
                prompt += ("\nThese already went out; verify the branch, commits and merge request that exist and "
                           "reuse them — create nothing twice.")
            if any(a.get("in_flight") for a in earlier):
                prompt += ("\nA previous call may have been interrupted and never reported what it did; verify the "
                           "branch, commits and merge request that exist and reuse them — create nothing twice.")
        else:
            prompt += "\n\nDelivery attempts so far: no attempt recorded."   # the line DELIVERY_RULE names (C1-2, C6)
        chosen = self.state.get("delivery_choice") or {}
        if chosen.get("choice") in ("go_on", "retry"):
            # A6: the typed record of the person's token (`_take_delivery_answer`), never a token read out of their prose
            prompt += ("\n\nThe person chose `" + chosen["token"] + "`: "
                       + ("deliver as it is." if chosen["choice"] == "go_on" else "they repaired what was undone themselves.")
                       + f" Their words are in {self.task_root / str(chosen.get('words_file') or '')}.")
        # The call is recorded BEFORE it is made and replaced by its verdict when it returns: a process
        # that dies inside the call (the conductor pushes, the driver is killed) leaves this line, and
        # the next process's first prompt says a call may have been interrupted (Lead's decision Q2).
        attempts = self.state.setdefault("delivery_attempts", [])
        attempts.append({"in_flight": True, "at": _now()})
        self.save_state()
        result = self.run_claude("conductor", prompt, stage="S8", tools="Bash,Read,Grep,Write",
                                 system_file=self.plugin / "references" / "conductor.md", max_turns=40,
                                 resume_key="S8:delivery")
        verdict = last_json_line(result["result"]) or {"action": "ask_person", "did": "", "question": result["result"][-1500:]}
        self.journal_conductor(stage="S8", refusal="delivery", action=verdict.get("action"), did=str(verdict.get("did") or "")[:1500],
                               question=str(verdict.get("question") or "")[:1000], session_id=result["session_id"],
                               total_cost_usd=result["total_cost_usd"], num_turns=result["num_turns"])
        action = verdict.get("action")
        # Every verdict is remembered as an attempt - what it said went out and what it asked - so the
        # next call can be told; the delivery MARK is written below, on `continue` only.
        attempts[-1] = {"at": _now(), "action": action, "did": str(verdict.get("did") or ""),
                        "question": str(verdict.get("question") or "")}
        self.state.pop("delivery_choice", None)      # the call that read the person's choice has answered: the choice is spent
        # The person's answer is read by code in `take_answer` (`_take_delivery_answer`: `go on` / `retry` / `no delivery` / `stop`
        # are tokens, any other words go to the seam). The flag is kept for its old readers (a state an older driver wrote).
        if action not in ("continue", "ask_person", "stop"):
            # An answer that is none of the three is treated as `ask_person` (Lead's decision, t-044):
            # no mark, the attempt is already kept with its did/question, and the person is asked in
            # words - no Refusal loop and no second conductor call. Their answer re-enters this step.
            self.state["delivery_question"] = True
            self.save_state()
            reported = str(verdict.get("question") or verdict.get("did") or "").strip()
            # remains: the site's own closed question (`s8.delivery.<word>`, four answers with executors in `_take_delivery_answer`)
            raise self.delivery_person("Delivery needs your word:\n\n" + (f"The delivery step reported: {reported}" if reported else
                                       "The delivery step came back with an answer I do not recognise."),
                                       why_person=verdict.get("why_person"))
        if action == "continue":
            # `mr` (t-1509, FR-14): the verdict's own field, the record the `mr` order is settled `done` with (`settle_mr_from_mark`);
            # kept only when it has the SHAPE of a record (`mr_record`): a link, an id token, a whole number; `none` / `N/A` /
            # `not opened` are no record, so the order is called off `delivered_without_mr` instead of closed as done
            mr = mr_record(verdict.get("mr"))
            self.state["delivery"] = {"done": True, "at": _now(), "did": verdict.get("did"), "action": action, "mr": mr}
        else:
            self.state["delivery_question"] = True
        self.save_state()
        if verdict.get("action") == "ask_person":
            # remains: the site's own closed question (see above)
            raise self.delivery_person(f"Delivery needs your word:\n\n{verdict.get('question')}", why_person=verdict.get("why_person"))
        if verdict.get("action") == "stop":
            # remains: the site's own closed question (see above)
            raise self.delivery_person(f"Delivery stopped:\n\n{verdict.get('question') or verdict.get('did')}", code=EXIT_GAVE_UP,
                                       why_person=verdict.get("why_person"))

    def delivery_person(self, said: str, *, code: int = EXIT_PERSON, why_person=None) -> Person:
        """`s8.delivery` (C1-6c, S11-S13 of the census): the delivery step's own words, then the priced answers. The key follows the
        verdict W2 the delivery is for (`yes` / `after_checks` / `no`, the word `recompute_verdict` returned): `go on` carries THAT
        word as its story line, never `yes` on `after_checks` (J4, P21), and on `after_checks` its person line is `your_checks`
        (the items in Left with you). `go on` and `retry` are two records (`delivery_choice`, FR-9): both re-enter the delivery step,
        which is first told what already went out. The delivery's own conductor session is NOT a seam call (F7); the question is."""
        options = [
            {"answer": "go on", "token": "go on", "slots": {"what": "the items in Left with you"},
             "says": "deliver as it is; the delivery step goes on with your words"},
            {"answer": "retry", "token": "retry", "slots": {"what": "the repair the delivery step named"},
             "says": "you repaired what was undone yourself; the delivery is asked again"},
            {"answer": "no delivery", "token": "no delivery", "says": "end the delivery here; nothing is sent out"},
            self.STOP_OPTION]
        # C-F2 (FR-10): the lead lists EVERY offered answer, read from `options` so it cannot drift from the priced section below it
        listed = ", ".join(f"`{o['token']}`" for o in options[:-1]) + f" or `{options[-1]['token']}`"
        lead = (said.rstrip() + "\n\nNothing is marked as delivered yet. When you say go on or retry, the delivery is first told what "
                                f"already went out and asked to reuse it. What I need from you: say to go on with the delivery, or to stop "
                                f"here. I take these answers: {listed}. To end the delivery here with nothing sent, answer `no delivery`; "
                                "any other words go to the delivery step as they are.\n\nThe answers are:")
        word = getattr(self, "recomputed_word", None) or self.delivery_word()
        # C-F2 (FR-59, AR-28): the unknown is never a `yes` - a word that is none of the two reads as the verdict `no` (not ready to ship).
        # The three ids stay LITERAL: the census of the conductor doors reads them (K15).
        if word == "after_checks":
            text = self.closed_question("s8.delivery.after_checks", lead, options)
        elif word == "yes":
            text = self.closed_question("s8.delivery.yes", lead, options)
        else:
            text = self.closed_question("s8.delivery.no", lead, options)
        person = Person("delivery", text, "S8", code=code)
        # RN1-9 (F5 a): RECORDED only - the delivery's own conductor session is no seam call, nothing is refused here
        person.source = "delivery"
        person.why_person = PO.as_class(why_person)
        return person

    def stage_S9(self) -> None:
        # GB-1b: the orders of gate B are carried out by `_act_execute_gate_b` BEFORE the story is closed; S9 runs on a closed
        # story only. This call stays (idempotent: an order that is not due is not touched) for a story decided before 0.10.5.
        self.after_gate_B()
        # R-212.1 (a): gate B is recorded, so the retro analyst and the S9 close see a report that carries its
        # gate B block, in every mode. `after_gate_B` is called here and by `_act_execute_gate_b`. (b), the
        # LAST write, is the mode's own: in `full` it is in `finish` (the retro role's return is what closes S9),
        # in `numbers` and `skip` it is right before `stage_done S9` below.
        self.rebuild_report()
        pipeline = self.pipeline()
        # `numbers` / `skip` are read only from a story an older version recorded (B-271, GW1-3); stage_done refuses them since 0.10.9.
        mode = pipeline.get("retro_mode") if pipeline.get("retro_mode") in ("full", "numbers", "skip") else "full"
        if mode == "skip":
            words = pipeline.get("retro_mode_words") or "skip"
            # W15 (C1-7b): the person's skip words are a journal row the retro and the report read; a refusal makes the row OWED
            self.owe_row("log_append.py", "--event", "escalated", "--agent", "qa-story", "--task", self.task,
                         "--reason", f"retro skipped by the person: {words}", what="your word to skip the retro")
            self.rebuild_report()
            self.record_close("s9.skip", "S9", "--status", "skipped", "--digest", f"retro skipped: {words}")
            return
        if not self.state.get("retro_asked"):
            raise Person("retro", S9_QUESTION, "S9")
        root = str(self.task_root)
        # G5 (C1-7b): its two files feed `--write-retro` and the retro analyst; a non-zero exit is a `Refusal` BEFORE `record_close` S9
        # (E3: the story is never recorded complete over an unwritten retro input)
        self.py("retro_numbers.py", "--task", self.task, "--output", f"{root}/work/retro-numbers.md",
                "--json-output", f"{root}/work/retro-numbers.json", check=True, expect="work/retro-numbers.md and work/retro-numbers.json written")
        if mode == "numbers":
            self.py("retro_numbers.py", "--task", self.task, "--write-retro", "--feedback",
                    self.state.get("retro_feedback") or "", check=True)
            # T6 (C1-7b): the estimate never raises, and the story's completion is never blocked by it (E3)
            self.py_trace("estimate_record.py", "--task", self.task, "--facts", f"{root}/work/estimate-facts.json",
                          why="the estimate feeds later stories' sizing; no decision of this story reads it")
            self.rebuild_report()
            self.record_close("s9.numbers", "S9", "--status", "done", "--digest", "retro: numbers only, on the person's word")
            return
        self.run_role("S9", "qa-retro-analyst", extra=self.role_lines("S9", "qa-retro-analyst"))
