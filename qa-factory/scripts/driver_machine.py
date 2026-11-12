"""driver_machine.py - Driver members and names homed here by ai-packages/qa-factory/scripts/tests/fixtures/driver-layers.json (TD-11 cut by tools/source_split.py); no behaviour of its own."""

import hooklib  # noqa: F401 (console setup, K7)
import hashlib
import json
import re
import time
from pathlib import Path
from typing import NamedTuple
from driver_chains import once_on
from role_cli import PERSON_MARKER, REPAIR_MARKER
from question_register import EARLIER_ANSWER_MARK
import detector_verdict as DV
import human_text
import no_move as NM
import person_owned as PO
import person_words
import waiver
from driver_core import CODE_CLOSE_IDLE_CAP, CODE_CLOSE_SITES, DISPATCH_ID_RE, EXIT_DONE, EXIT_ERROR, EXIT_GAVE_UP, GATE_KINDS, HALT_RECORD_WHY, InfraStop, JOURNAL_ROWS_BLOCK, Person, REFUSALS_PER_BOUNDARY, Refusal, RepairFailed, ReworkRefused, STUCK_REPEATS, Stop, UNTIL_PAST, _answer_note, _now, _read_json, _read_jsonl, finding_key, finding_lines
from driver_dialog import ANSWER_BLOCK_RE, QUESTION_HEAD_RE, question_body_sha
from driver_conductor import MOVES_RULE, OWN_TOKEN_RULE, PRE_FILLED
from driver_dispatch import KNOWN_REFUSALS, STRUCTURED_RE, WINDOW_ROUND_STAGES, parse_next, resume_reason
from driver_sources import S1_DISPATCH_RE


# A recorded stand preparation whose process is still alive: looked at every half minute for
# twenty minutes before the person is asked. Waiting is the whole point - the one thing the
# driver must never do here is start a second preparation with a new key.
ENV_JOB_WAIT_SECONDS = 30

ENV_JOB_LOOKS = 40

# The two refusal HEADS the role's own resume answers (FR-46): a refusal of the role's handoff (`exit gate for <id>`) and
# a `story_step finish <id> (exit 3)` (the handover, the missing outputs). ANCHORED at the start of the text, never
# searched for: a refusal of the CALL class (`finish` exit 2: `--unresolved` without `--reason`, no such dispatch)
# carries the repair marker too, is the driver's own mistake and must stay on the conductor road, and a text that
# merely QUOTES one of these heads further down is not one of them (the controller's marked refusal arrives as exit 2).
RESUMABLE_HEADS = (re.compile(r"^exit gate for (S\d+-qa-[a-z-]+-\d+)"),
                   re.compile(r"^story_step finish (S\d+-qa-[a-z-]+-\d+) \(exit 3\)"))

# Rounds of one window the conductor may be given before the person is (F-cmp2-28c); AT it the round runs, BEYOND it the
# person is asked. Mirrors GATE_REPAIR_CAP. The table is stage -> the role whose accepted completion ends the window's
# series: built stage-generic, enabled for S5 only (S3, S4 and S7 have the same loop and are queued).
WINDOW_ROUND_CAP = 2


def match_known(text: str):
    """(name, action) of the row the refusal matches, or None.

    The marker comes first, and on purpose: the table was written from experience - one regex
    per message this driver had already met - so every refusal a new check adds went wherever
    the default led, which on TP1-13797 meant the conductor read factory sources at $0.88 a
    turn to decide something the refusal itself already knew. A script that knows the answer is
    the role's own work says so in `role_cli.REPAIR_MARKER`, and no row has to be added here
    for the driver to hand it back to the role (P6)."""
    body = text or ""
    if REPAIR_MARKER.lower() in body.lower():
        return "marked_repair", "resume_repair"
    if PERSON_MARKER.lower() in body.lower():
        return "marked_person", "ask_person"
    for name, pattern, action in KNOWN_REFUSALS:
        if re.search(pattern, text or "", re.IGNORECASE | re.DOTALL):
            return name, action
    return None


def route_known(refusal):
    """(name, action) of the ONE row every item of the refusal agrees on, or None (the conductor, with the whole text).

    A refusal that is a LIST (an exit gate's findings, the controller's combined refusal `N problems - the request is
    refused whole, every one is listed:`) is routed item by item: `match_known` over the whole text would let one item's
    phrase or marker lead the rest (K1, t-720 §3.4). INVARIANT: no item is routed by a neighbour's phrase or marker, and
    nothing that goes to the conductor alone today becomes `continue`, `retry` or a resume of the role through another
    item. Items: `refusal.findings` when there are two or more; else the items of the head `split_items` reads from the
    text with the transport taken off (`refusal_text`: the `story_step: refused - ` prefix and the JSON escaping of
    `--operation decision`). No head and fewer than two findings: `match_known` of the text, as before, byte for byte.
    A head that is there but whose items are fewer than two or do not match its count is NEVER matched over the whole
    text: the conductor reads it.

    A G refusal (`known` False, C1-7b F10) is NEVER routed by the table: its text holds a script's own words, and a phrase
    in them (`already completed`, `expected_revision`, `STORY BUDGET`, `event committed;`, `stands in front of gate`) must
    not turn a step that left no product into `continue`, `retry` or `ask_person`. INVARIANT: every such refusal reaches the
    conductor (FR-12: the table never reads a G step's output)."""
    if getattr(refusal, "known", True) is False:
        return None
    items = list(getattr(refusal, "findings", None) or [])
    if len(items) < 2:
        found = DV.split_items(DV.refusal_text(refusal.text))
        if found is None:
            return match_known(refusal.text)
        items = found
        if len(items) < 2:
            return None
    routes = {match_known(item) for item in items}
    return routes.pop() if len(routes) == 1 else None


class RelayCtx(NamedTuple):
    """t-667 D17: what `Driver._relay_note` reads about the answer being relayed - fixed by the time the note is built and never
    changed by it: the form ids of the gaps, the gaps, the rehearsal (None when none ran), the gate letter and the stage a gap with
    none of its own is recorded under. The things the note's builder fills or the caller goes on to use (`out`, `found`) stay
    explicit arguments (E11: a mutable is never put in a context object)."""
    forms: dict
    gaps: list
    rehearsal: dict | None
    gate: str
    default_stage: str


class DriverMachine:
    def where(self) -> dict:
        out = self.step("where", "--task", self.task)
        self.last_where = out
        return parse_next(out)

    def check_run_mode(self) -> None:
        """B-014, F14-3: a story is run by one mode. `story_step start` stamps `pipeline.run_mode`
        and refuses a switch; the driver asks the same question at the start of a run, as a person's
        question, instead of meeting that refusal at the first stage it dispatches. The stage judged
        is the first one not done (what a run would start next); a story with none left has nothing
        to start and nothing to refuse. A story with no stamp adopts this mode silently."""
        pipeline = self.pipeline()
        stages = pipeline.get("stages") or {}
        stage = next((s for s in (f"S{i}" for i in range(10))
                      if (stages.get(s) if isinstance(stages.get(s), dict) else {}).get("status") != "done"), "")
        if not pipeline or not stage:
            return
        import story_step
        switch = story_step.run_mode_switch(pipeline, stage, "driver")
        if not switch:
            return
        stamped = switch["stamped"]
        text = self.closed_question(
            "package.mode",
            f"This story was started in {stamped.get('mode')} mode, and this run is in driver mode. "
            "Stages of one story are run one way, because each way leaves the story's records under "
            "its own assumptions, and mixing them can leave a stage judged by rules it was not built under.\n\n"
            "What I need is a decision. Answer with exactly one of these words:",
            [{"answer": "desktop", "token": "desktop", "says": "you finish the story in the desktop app; the driver runs "
                                                              "nothing meanwhile", "slots": {"what": "finish the story in the desktop app"}},
             {"answer": "go on", "token": "go on", "says": "go on in driver mode; I record your words as the reason the story "
                                                           "carries"},
             self.STOP_OPTION])
        details = (f"run_mode stamped in pipeline.json: {json.dumps(stamped, ensure_ascii=False)}\n"
                   f"this run: driver, package {self.plugin} (version {self._copy_version(self.plugin) or 'unknown'})\n"
                   "Your answer is recorded by code with: "
                   f"python \"{self.scripts / 'waiver.py'}\" --task {self.task} --stage {stage} "
                   "--block \"mode switch\" --decision \"<your words>\"")      # prose: test_words_doors' inline-door census keys on the literal
        self.state["package_question"] = {"what": "mode", "stage": stage, "text": text, "details": details}
        raise Person("package", text, stage, details=details)

    # --- t-217: whose refusal it is, one resume per finding set, a cap on a window's rounds ---------------

    def boundary_dispatch(self) -> str:
        """The dispatch the boundary names by its SHAPE, else "": `S5:S5-qa-code-critic-2` and the `:resume` / `:answer`
        forms name one; `S0:ticket`, `gate_A`, `S5:TC-1,TC-2` and `S5:environment:<job>` do not."""
        parts = self.boundary.split(":")
        return parts[1] if len(parts) > 1 and DISPATCH_ID_RE.fullmatch(parts[1]) else ""

    def refusal_dispatch(self, refusal) -> str:
        """The dispatch a refusal is about, for a Person raised from it (F-cmp2-22, FR-16): the refusal's own
        field first, else the boundary's. NEVER an id read out of its text - the same text can quote another
        dispatch (a probe's hint, a critic id placeholder), and a person's words filed into a wrong dispatch
        resume a role that never asked."""
        return str(getattr(refusal, "dispatch", "") or "") or self.boundary_dispatch()

    @staticmethod
    def resumable_head(text: str) -> str:
        """The dispatch id of a refusal whose HEAD is one the role's own resume answers (`RESUMABLE_HEADS`), else "".
        Anchored at the start of the text on purpose (`match`, never `search`)."""
        for pattern in RESUMABLE_HEADS:
            found = pattern.match(str(text or ""))
            if found:
                return found.group(1)
        return ""

    def stand_probe(self, dispatch: str):
        """(c)(d): None when the stand clause does not apply; else (answers, the probe's output whole).

        It applies only when the saved result's digest holds a row whose STATE is `blocked_by_env` (a closed
        vocabulary value, never prose - FR-12) and the story names a stand. The probe is `env_probe.py` - the tool
        `stand_check` already uses (FR-17). It answers only when it exits 0 AND prints something: a probe that fails,
        crashes or prints nothing does not answer (FR-41). Nothing is written here."""
        saved = _read_json(self.state_dir / "driver-runs" / f"{dispatch}.json")
        text = saved.get("result") if isinstance(saved, dict) else ""
        environment = str(self.pipeline().get("environment") or "")
        if not isinstance(text, str) or not text.strip() or not environment:
            return None
        try:
            import role_digest
            rows = role_digest.parse(self.digest_of(text)).get("rows") or []
        except Exception:
            return None
        if not any(row.get("state") == "blocked_by_env" for row in rows):
            return None
        try:
            code, out = self.py("env_probe.py", "--env", environment, "--task", self.task)
        except Exception as exc:
            return False, f"the probe could not run: {type(exc).__name__}: {str(exc)[:200]}"
        out = str(out or "").strip()
        return (code == 0 and bool(out)), (out or "the probe printed nothing")

    def close_by_doors(self, refusal: Refusal, stage: str, dispatch: str) -> str | None:
        """C2-4 (K9, I2): the step BEFORE every resume of `resume_on_refusal` - what code can write, code writes, and the refused
        call is made again. `"continue"` when the retry went through; `None` when nothing was closed by code (today's road, over
        the refusal as it was).

        POSITION INVARIANT: the caller puts this before the branches ('no dispatch', 'no session', the first resume, the stand,
        'already resumed'), so none of them sees a refusal the code closed - and NOT inside `key not in record`, where the
        'already resumed' branch would never meet it. It is not a resume: no `note_resume`, the 'once per finding set' of the role
        is untouched (I3). BOUNDS: once per (dispatch, finding key) in this process (a door that rewrites its file on every pass
        cannot loop it), and never from inside its own retry (`in_code_step`, t-909 F-2): a NEW refusal the retry raises takes
        the whole road of `handle_refusal` (t-721 F-17), but that road's `resume_on_refusal` skips this step, so a chain of
        refusals with changing keys cannot recurse here - `guarded`'s cap counts the turns it sees."""
        if not dispatch or not refusal.retry or self.in_code_step:
            return None
        key = finding_key(self.refusal_lines(refusal))
        if (dispatch, key) in self.doors_tried:
            return None
        self.doors_tried.add((dispatch, key))
        wrote = self.code_doors(stage, self.dispatch_role(dispatch), dispatch)
        if not wrote:
            return None
        self.in_code_step = True
        try:
            try:
                refusal.retry()
            except Refusal as again:
                if finding_key(self.refusal_lines(again)) == key:
                    return None
                print(f"refusal: {dispatch}: code wrote ({', '.join(wrote)}) and the refusal changed; it takes the whole road")
                return self.handle_refusal(again)
        finally:
            self.in_code_step = False
        self.drop_standing()            # E2: the refused step went through
        print(f"refusal: {dispatch} closed by code ({', '.join(wrote)}) - no resume")
        return "continue"

    def resume_on_refusal(self, refusal: Refusal, stage: str, head: str) -> str:
        """(c) A refusal of the role's handoff or of its `finish` (exit 3) answered after the role's session ended.
        Returns "continue" (the role was resumed once; the loop goes on from its new result) or raises Person.

        INVARIANTS: a role is never resumed twice for the same finding set on one dispatch+session, across entries and
        relaunches (`refusal_resumes`, written BEFORE the call); a role that has not seen these findings is resumed
        once before anyone else is asked; the stand is looked at once per dispatch+session, never per set; the
        CONDUCTOR is never asked about an IDENTICAL finding set (fork 3: a second identical refusal is a fact the factory
        already knows and a $0.3 call can add nothing - F-cmp2-11, -16, -27): the person gets the priced fallback question
        (C1-1). No dispatch or no session, and a stand that does not answer: the seam calls the conductor once."""
        dispatch = self.refusal_dispatch(refusal) or head
        sid = self.refusal_sid(dispatch) if dispatch else ""
        closed = self.close_by_doors(refusal, stage, dispatch)      # C2-4: before EVERY branch below (I2)
        if closed:
            return closed

        def person(lead: str, details: str = "", call: bool = False) -> str:
            # The seam (C1-1). No session and a stand that does not answer CALL the conductor (it has moves for them: the
            # stand, a restart); the repeat of an identical finding set does not (t-217 fork 3: no paid repeat on the same set
            # - the person gets the priced fallback question; D-0039 weighs this and the owner's answer is open).
            return self.no_move({"why": "refusal", "kind": "refusal", "call": call, "stage": stage, "dispatch": dispatch,
                                 "lead": lead + self.question_from_refusal(refusal, stage), "text": details or refusal.text,
                                 "lines": self.refusal_lines(refusal)})

        if not dispatch:
            print("refusal: no session of the role is known; the person is asked")
            return person("", call=True)
        if not sid:
            # t-764 E9 (FR-42): the dispatch is known and no session of it is - the one seam says so, with no `round`
            print("refusal: no session of the role is known; the person is asked")
            self.exit_limit(stage, self.dispatch_role(dispatch), dispatch, self.refusal_lines(refusal), sid="", why="refusal", text=refusal.text)
        key = finding_key(self.refusal_lines(refusal))
        record = self.resume_record(dispatch, sid)
        if key not in record:
            self.note_resume(dispatch, sid, key, "refusal")
            print(f"refusal: {dispatch} is resumed in its own session with the refusal, once")
            self.resume_with(refusal, stage, dispatch, sid, "The factory refused to close your dispatch "
                             + dispatch + ":\n\n")
            return "continue"
        if "stand" not in record.values():
            probe = self.stand_probe(dispatch)
            if probe is not None:
                answers, out = probe
                if not answers:
                    print("refusal: the role reported its work blocked by the stand and the stand does not answer; "
                          "the person is asked")
                    return person("The stand did not answer when I looked at it just now, so what the role was "
                                  "stopped by has not changed.\n\n",
                                  refusal.text + "\n\nWhat the probe of the stand printed:\n" + out, call=True)
                self.note_resume(dispatch, sid, key, "stand")
                print(f"refusal: the stand answers now; {dispatch} is resumed with the probe's words, once")
                self.resume_with(refusal, stage, dispatch, sid,
                                 "The stand answers now:\n" + out + "\n\nThe factory refused to close your dispatch "
                                 + dispatch + ":\n\n",
                                 reason="the role reported its work blocked by the stand and the stand answers now; "
                                 + resume_reason(refusal.findings or refusal.text))
                return "continue"
        print(f"refusal: {dispatch} was already resumed on these findings; the person is asked")
        # t-764 E8: the ONE seam (the finish refusals `story_step finish (exit 3)` reach only this site); a round the person
        # bought is spent there and the loop judges the role's new result
        self.exit_limit(stage, self.dispatch_role(dispatch), dispatch, self.refusal_lines(refusal), sid=sid, why="refusal", text=refusal.text)
        return "continue"

    def window_key(self, stage: str, dispatch: str) -> str:
        """`<stage>|<the dispatch's scope, sorted and joined by commas>` from the controller's dispatch record
        (the S5 window's cases); the dispatch's own id when the record or its scope cannot be read (then the series
        cannot accumulate across dispatches and the conductor's per-boundary cap is the only bound, as before);
        "" with neither."""
        try:
            record = (self.controller_state().get("dispatches") or {}).get(dispatch) or {}
            scope = sorted({str(item) for item in (record.get("scope") or []) if item})
        except Exception:
            scope = []
        if scope:
            return self.window_id(stage, scope)
        return f"{stage}|{dispatch}" if dispatch else ""

    def window_round_gate(self, refusal: Refusal, stage: str) -> None:
        """F-cmp2-28c: a cap on the rework rounds the CONDUCTOR may start over one window. Returns to let the
        conductor have it, or raises Person.

        The loop was unmatched refusal -> conductor -> rework -> new dispatch -> new boundary -> three fresh conductor
        calls (the per-boundary cap lives in memory, keyed by the boundary): cmp2 spent 11 automators and 4 critics on
        one window over the same five gap lines ($7.28). A round is written to `window_rounds` BEFORE the paid call,
        and the series bounds itself: a finding set equal to an earlier round's, or a third round, is the person's.

        POSITION INVARIANT: after every known row of `handle_refusal` (they act first and are never counted);
        `gate_repair`'s `hand_to_conductor` calls `conductor_round` directly and never meets this. A set that
        differs from every earlier round and is within the cap always reaches the conductor. EDGES: no findings
        (an empty set) is never recorded and never "equal" (FR-41); a stage not in WINDOW_ROUND_STAGES passes; the
        person's answer clears nothing - the same set afterwards asks again, with `ask()`'s FR-7 block.
        DC1-21: the round's kind (`cause`) is `window` when the set is the window record's gap lines
        (`window_findings`), else `refusal` (the factory's own refusal of the call); each kind has its own cap of
        `WINDOW_ROUND_CAP`; `same_set` is judged across both; a record with no or an unknown `cause` counts as
        `window` (an unknown is never free: FR-59)."""
        if stage not in WINDOW_ROUND_STAGES:
            return
        dispatch = self.refusal_dispatch(refusal)
        key = self.window_key(stage, dispatch)
        source = (refusal.window_findings or refusal.findings
                  or [line for line in refusal.text.splitlines()[1:] if line.strip()])
        found = finding_lines(source)               # the COMPARISON form (`<dispatch>` for ids): never what the record is built from
        if not key or not found:
            return
        cause = "window" if refusal.window_findings else "refusal"
        held = self.state.get("window_rounds")
        if not isinstance(held, dict):
            held = self.state["window_rounds"] = {}
        series = held.get(key)
        if not isinstance(series, list):
            series = held[key] = []
        rounds = [r for r in series if isinstance(r, dict) and r.get("outcome") == "to_conductor"]

        def kind(r):
            return "refusal" if r.get("cause") == "refusal" else "window"

        mine = [r for r in rounds if kind(r) == cause]
        scope = key.split("|", 1)[1]
        same = next((i for i, r in enumerate(rounds, 1) if r.get("set") == found), None)
        reason = "same_set" if same is not None else ("cap" if len(mine) >= WINDOW_ROUND_CAP else "")
        if reason:
            if not any(isinstance(r, dict) and r.get("set") == found and r.get("outcome") == reason for r in series):
                series.append({"at": _now(), "dispatch": dispatch, "set": found, "outcome": reason, "cause": cause})
                self.save_state()
            if reason == "same_set":
                print(f"{stage} window {scope}: round {len(rounds) + 1} came back with the same {len(found)} "
                      f"finding(s) as round {same} — no further rework; the person is asked")
                if cause == "refusal":
                    lead = (f"The factory's own checks refused this window again with the same reasons as round {same}. "
                            "Nothing was reworked: the reasons are not about its tests. Tell me how to go on.\n\n")
                else:
                    lead = (f"This window came back with the same findings as round {same}; the driver does not "
                            "rework it again.\n\n")
            elif cause == "refusal":
                print(f"{stage} window {scope}: {WINDOW_ROUND_CAP} rounds over refusals that are not about the "
                      "window's tests are spent - the person is asked")
                lead = (f"The factory's own checks refused this window {len(mine)} times for reasons that are not "
                        "about its tests, and the driver does not hand it on again.\n\n")
            else:
                print(f"{stage} window {scope}: the cap of {WINDOW_ROUND_CAP} rounds is spent — the person is asked")
                lead = (f"The driver has sent this window back for rework {len(mine)} times already and does "
                        "not do it again.\n\n")
            state = {"why": "threshold", "kind": "refusal", "call": False, "stage": stage, "dispatch": dispatch,
                     "lead": lead + self.question_from_refusal(refusal, stage), "lines": self.refusal_lines(refusal, items=source),
                     "text": refusal.text + "\n\nThe findings of this round:\n- " + "\n- ".join(found)}
            if stage == "S5" and dispatch:
                # B-16: the window's green tests whose probe the tool could not read: the question names their case keys and carries
                # them in `asked` (the `rows` pattern); `seam_chosen` records `probe gap: <case key>` for each on `go on`. The record
                # on disk is the one the driver rebuilt at the finish. No such case (red only, never run, no record): today's question.
                import window_record
                record = _read_json(self.task_root / "work" / "windows" / f"{dispatch}.json")
                # t-1968 N5: the tests whose probe the code reviewer could not judge are read FIRST (the person's own question, the owner's
                # word 05.11.2026); the probe-gap question below runs only when there are none. ONE question per seam (AR-16): the other
                # kind comes at the next refusal, and no word is recorded for a token the person did not choose.
                judged = window_record.probe_judgment_cases(record, self.task_root)
                pairs = [] if judged else window_record.probe_gap_cases(record, self.task_root)
                if judged:
                    state["probe_judgment_cases"] = [case for case, _items in judged]
                    state["lead"] = self.probe_judgment_lead(judged)
                elif pairs:
                    state["probe_gap_cases"] = [case for case, _ids in pairs]
                    state["lead"] = self.probe_gap_lead(pairs)
            self.no_move(state)
        series.append({"at": _now(), "dispatch": dispatch, "set": found, "outcome": "to_conductor", "cause": cause})
        self.save_state()
        number = len(mine) + 1
        if cause == "refusal":
            print(f"{stage} window {scope}: refusal round {number} of {WINDOW_ROUND_CAP} goes to the conductor - the "
                  "refusal is not about the window's tests; the window's own rounds stay "
                  f"{sum(1 for r in rounds if kind(r) == 'window')} of {WINDOW_ROUND_CAP}")
            return
        print(f"{stage} window {scope}: round {number} of {WINDOW_ROUND_CAP} goes to the conductor"
              + (" (the findings changed)" if number > 1 else ""))

    def handle_refusal(self, refusal: Refusal, *, words: str = "") -> str:
        """Returns 'continue' or 'retry'; raises Person / Stop when the loop must end."""
        stage = self.boundary.split(":")[0]
        if refusal.title == "second_delivery":
            # P49: a second hand-over of the delivery in one process cannot add anything a paid call would (it could create the
            # branch and the merge request twice): no call, the priced question with the two answers that mean something.
            # Keyed on the TITLE the raiser gave, never on a regex over the sentence; BEFORE `match_known` on purpose.
            return self.no_move({"why": "refusal", "kind": "refusal", "call": False, "stage": stage, "dispatch": "",
                                 "fallback": ["retry", "stop"], "lead": self.question_from_refusal(refusal, stage),
                                 "text": refusal.text, "lines": self.refusal_lines(refusal)})
        known = route_known(refusal)
        committed, recover_failed = False, ""
        if known and known[0] == "gate_stage":
            # t-211 / C9: the row lets the driver go on ONLY over a stage the controller has already closed
            # (story_step accepts, and only then calls stage_done). An open stage is not this refusal's
            # case: it falls to the conductor, as it did before the row existed. What the refused finish
            # skipped (S4's case appendix, S8's report rebuild) is owed at gate entry (C10).
            if not self.stage_completed(stage):
                known = None
            else:
                owed = self.state.setdefault("gate_entry_owed", {})
                owed[stage] = _now()
                self.save_state()
        if known and known[0] == "s0_receipt" and stage != "S0":
            # C2-8 B2 (measured t-763): the row answers with the move of S0 (`code_only("S0")`) and so only a refusal raised ON THE
            # BOUNDARY OF S0. The same door at S1-S9 (the retro's record at S9) is not S0's: the receipt would be refused inside this
            # method and the run would end in `funnel`. ERROR DIRECTION: too few moves of code is allowed (the S0 boundary under another
            # name goes to the conductor), the move of S0 on another stage is forbidden. Exact stage equality, never a prefix.
            known = None
        if known:
            name, action = known
            if action in ("resume_handoff", "resume_repair") and re.search(STRUCTURED_RE, refusal.text, re.IGNORECASE | re.DOTALL):
                # INVARIANT: one text with a form problem AND a structured-artifact problem resumes the role
                # ONCE, with the whole text. The rows above (and the marker) only say "the role site resumed
                # already" - true for `handoff`, never for a `finish` refusal - so the first match must not win.
                name, action = "structured_artifact", "resume_structured"
            self.journal_conductor(stage=stage, refusal=refusal.text[:2000], action="known:" + name, did=action)
            print(f"refusal: known `{name}` → {action}")
            if action == "ask_person":
                return self.no_move({"why": "refusal", "kind": "refusal", "call": False, "stage": stage,
                                     "dispatch": self.refusal_dispatch(refusal), "lines": self.refusal_lines(refusal),
                                     "lead": self.question_from_refusal(refusal, stage), "text": refusal.text,
                                     # RN1-9 (E-20): a code-raised question's class is its `code_routes` row; None when it has none
                                     "why_person": PO.code_route(name), "source": "code"})
            if action in ("s1_review", "s1_gap"):
                parts = self.boundary.split(":")
                dispatch = parts[1] if len(parts) > 1 and parts[1].startswith("S1-") else ""
                # The field first, the sentence only for a refusal some other script raised.
                m = re.search(S1_DISPATCH_RE, refusal.text)
                dispatch = dispatch or refusal.dispatch or (m.group(1) if m else "")
                if action == "s1_gap" and self.close_vcs_gaps([refusal.text]):
                    # Collected through the factory's own authenticated route: the gate reads the
                    # inventory again instead of the person answering about material we now have.
                    return "retry"
                text = (self.s1_review_text(refusal.text) if action == "s1_review"
                        else self.s1_gap_text(refusal.text))
                raise Person(action, text, stage, dispatch,
                             answer_note=(human_text.onboarding_note(self.pipeline().get("environment"), self.config.get("environments"))
                                          if action == "s1_review" else ""))
            if action == "retry":
                return "retry"
            if action == "recover":
                try:
                    self.controller("recover")
                    if name == "committed_event" and self.stage_completed(stage):
                        # A finish refused over a stage the controller has CLOSED (the event is in the journal)
                        # skipped the stage's tail exactly as `gate_stage` does: S4's case appendix, S8's report
                        # rebuild. The same mark, so the gate entry runs what a normally closed stage ran - once
                        # (one key per stage). A stage that is not completed is not marked.
                        self.state.setdefault("gate_entry_owed", {})[stage] = _now()
                        self.save_state()
                    return "continue"
                except Refusal as again:
                    # `recover` itself said no. That is a refusal no row here answers, so it
                    # goes where an unknown one goes - the conductor - and `recover` is not run
                    # a second time. The conductor is shown BOTH texts: what was refused first
                    # and what recover said about it, because it has to judge the pair.
                    recover_failed = again.text
                    if name == "committed_event":
                        committed = True
            if action == "code_only_s0":
                self.code_only("S0", "preflight green: S0 closed on a task initialized before it",
                               ["pipeline.json"])
                return "continue"
            if action == "initialize":
                self.initialize()
                return "continue"
            if action == "error":
                raise Stop(EXIT_ERROR, refusal.text)
            if action == "rebuild_report":
                # R-S9.1 / FR-42: the driver's own move on the S9 exit's report check, ONCE per boundary:
                # `--write`, then the very call that was refused, again. The count lives in the state file
                # under the boundary (`S9`, or `S9:<dispatch>`), so a driver started again after an exit 3
                # meets it too and cannot go write -> refuse -> write for ever. A refusal with no call to
                # repeat, or the same refusal a second time, is the conductor's - never the person's.
                done = self.state.setdefault("report_rebuilds", {})
                if refusal.retry and not done.get(self.boundary):
                    done[self.boundary] = 1
                    self.save_state()
                    self.rebuild_report()
                    return "retry"
                print("refusal: the report check refused again after the rebuild; the conductor is called")
            elif action == "resume_structured":
                # FR-42 / FR-48: the role's own session gets the refusal, ONCE per dispatch; the count lives
                # in the state file (survives an exit-3 relaunch). Never the conductor, never a fresh session.
                # The same refusal again, or no session to resume, is the person's (the refusal beside, whole).
                parts = self.boundary.split(":")
                dispatch = refusal.dispatch or (parts[1] if len(parts) > 1 and re.fullmatch(r"S\d+-[\w-]+-\d+", parts[1]) else "")
                if not dispatch:
                    m = re.search(r"story_step finish (S\d+-[\w-]+-\d+) \(exit", refusal.text)
                    dispatch = m.group(1) if m else ""
                sid = self.state["sessions"].get(dispatch) if dispatch else ""
                done = self.state.setdefault("structured_resumes", {})
                if not sid or done.get(dispatch):
                    print("refusal: the structured artifact is refused again (or no session is known); the person is asked")
                    if dispatch:
                        # t-764 F-d6 (E11): the same class as the handoff's - one resume spent, the dispatch not accepted. The key of
                        # the set is `finding_key` of the refusal's lines (`structured_resumes` is per dispatch), so a round the person
                        # buys is counted for THIS set; a round is spent there and the loop judges the role's new result
                        self.exit_limit(stage, self.dispatch_role(dispatch), dispatch, self.refusal_lines(refusal), sid=sid or "",
                                        why="structured", text=refusal.text)
                        return "continue"
                    return self.no_move({"why": "refusal", "kind": "refusal", "call": False, "stage": stage,
                                         "dispatch": self.refusal_dispatch(refusal), "lines": self.refusal_lines(refusal),
                                         "lead": self.question_from_refusal(refusal, stage), "text": refusal.text})
                done[dispatch] = 1
                self.save_state()
                try:
                    role = str(((self.controller_state().get("dispatches") or {}).get(dispatch) or {}).get("role") or "")
                except Exception:
                    role = ""
                role = role or (re.fullmatch(r"S\d+-(qa-[a-z-]+)-\d+", dispatch) or [None, ""])[1]
                print(f"refusal: {dispatch} is resumed in its own session with the refusal, once")
                self.run_claude("role", "The factory refused to close your dispatch " + dispatch + ":\n\n" + refusal.text.strip()
                                + "\n\nRepair the named fields in the artifact, change nothing else, then your final "
                                  "message is the handoff form only.", role=role, dispatch=dispatch, stage=stage, resume=sid,
                                resume_reason=resume_reason(refusal.findings or refusal.text))
                return "retry"
            elif action in ("resume_handoff", "resume_repair"):
                # t-217 / F-cmp2-23: a refusal of the role's handoff or of its `finish` (exit 3) is answered by the
                # role's OWN session, once per finding set, then the stand, then the PERSON - never the conductor
                # (a declared change of the old "the role site already resumed once; below it is the conductor's").
                # Any other refusal with such a marker (a refusal of the CALL class, a text that only quotes a head)
                # stays on the conductor road below.
                head = self.resumable_head(refusal.text)
                if head:
                    return self.resume_on_refusal(refusal, stage, head)
            elif action == "continue":
                return "continue"
        if refusal.close and not recover_failed and not (known and known[0] == "report_check"):
            # C2-8 (K3): a stage the CODE closes with no role - there is no role to resume and no point in a paid call about the text.
            # POSITION INVARIANT: after the known rows that have a move of code (I1: `story_budget`, `already_done`, the first
            # `report check:`), so none of them is taken from code; the SECOND `report check:` (R-S9.1: never the person's) and a
            # refusal whose own `recover` refused (both texts to the conductor) are the conductor's, as before; before
            # `window_round_gate` (no S5 window refusal carries `close`).
            return self.code_close(refusal)
        self.window_round_gate(refusal, stage)
        return self.conductor_round(refusal, stage, words=words, recover_failed=recover_failed,
                                    committed=committed)

    def seam_rework_step(self) -> bool:
        """One move of the rework the person CHOSE at the seam (`state["seam_rework"]`, written by `record_seam_rework`; t-722 §4.2
        p.7), or False when none is owed. Run at the start of each turn of the loop after `ticket_rework_step`, before `where`: nothing
        `where` could say goes ahead of what the person chose. INVARIANT (P22): the record lives until the controller has REGISTERED
        the rework and is dropped only after; a crash anywhere neither loses the choice nor registers it twice. Order: no record or
        no controller state -> False; a dispatch running -> False (`where` leads it); the record's OWN dispatch (stage and cause
        match, id not in `before`) already registered -> the record goes, False; a dry run says so ONCE, touches nothing, False; the
        person's words (`original_words`) gone -> the record goes and the seam hears it; else `rework` with the words by file,
        `complete=False` (the stage opens again: on S5 the window's reviewer is dispatched again) and `purpose` by default
        (`repair_verify`, as `ticket_rework_step`); a refusal to register drops the record and goes to the conductor."""
        owed = self.owed_rework("seam_rework")
        if owed is None:
            return False
        pending, dispatches = owed
        stage, role, cause = (str(pending.get(key) or "") for key in ("stage", "role", "cause"))
        if any(did not in (pending.get("before") or [])           # the record's OWN dispatch: the person's origin, never a `ticket_changed` one
               for did in self.rework_dispatches(dispatches, cause, by_person=True, stage=stage)):
            self.drop_record("seam_rework")
            return False
        if self.dry:
            print("dry run: the rework the person chose is not started")
            return False             # nothing moved: a True here would spin the loop `max_boundaries` times over the same line
        rel = str(pending.get("words_file") or "")
        given = self.original_words({"words_file": rel})
        if not given or not given[1].strip():
            self.drop_record("seam_rework")
            self.seam_rework_refused(stage, f"the words file of the person's rework is gone: {self.task_root / rel}", "", "", [])
            return True
        preface = [str(line) for line in pending.get("preface") or [] if str(line).strip()]
        reason = "\n".join(preface + [given[1]]) if preface else given[1]       # the code's preface, then the person's words VERBATIM
        try:
            self.rework(stage, role, list(pending.get("cases") or []), reason, cause=cause, rows=list(pending.get("rows") or []),
                        words_file=rel, complete=self.s3_rework_completion() if (stage, role) == ("S3", "qa-test-strategist") else False)
        except ReworkRefused as exc:
            self.drop_record("seam_rework")                     # nothing was registered and nothing will be (§4.2 p.7 step 7)
            self.seam_rework_refused(stage, exc.text, given[1], rel, self.refusal_lines(exc))
            return True
        self.drop_record("seam_rework")
        return True

    def answer_rework_step(self) -> bool:
        """One move of the rework the person's recorded answers owe (`state["answer_rework"]`, written by `apply_question_answers`), or False
        when none is owed. Run each turn of the loop after `seam_rework_step`, before `code_close_step` and `where`. The rework is opened by CODE:
        `Driver.rework(cause="question_answer")` - the conductor is not called (FR-48). INVARIANT (P22, as the seam's): an item lives until the
        controller has REGISTERED its rework and goes only after, so a crash neither loses it nor registers it twice. Order of the checks:
        no record / no controller state / a dispatch running -> False (`where` leads it); the item's OWN dispatch (this stage, cause
        `question_answer`, id not in its `before`) already registered -> the item goes, False (H42 b, d); a dry run says so ONCE and moves
        nothing; the work is already done (H41: the plan and the cases of the item follow its answers - the same reader as the gate A
        rehearsal) -> the item goes with one line, no paid repeat (FR-55); else `rework` with `complete=None` (N1: the stage's own rule
        closes it; S3 closes by its projection, `s3_window_completion`), the person's words by file, or the driver's own reason when
        there are none or the file is gone (C16, H42 g); a refusal of the controller drops the item and goes to the conductor WITH the
        words (H42 c). The strategist's item (S3) is first: the plan before the cases (H40)."""
        owed = self.owed_rework("answer_rework")
        if owed is None:
            return False
        pending, dispatches = owed
        items = [i for i in pending.get("items") or [] if isinstance(i, dict) and i.get("stage") and i.get("role")]
        if not items:
            self.drop_record("answer_rework")
            return False
        item = items[0]
        stage, role = str(item["stage"]), str(item["role"])
        if self.answer_rework_registered(item, dispatches):
            self.finish_answer_item(item)
            return False
        if self.dry:
            print("dry run: the rework your recorded answers owe is not started")
            return False             # nothing moved: a True here would spin the loop `max_boundaries` times over the same line
        owed_item = self.answer_item_still_owed(item)
        if owed_item is None:
            ids = ", ".join(str(a.get("id")) for a in item.get("questions") or [])
            print(f"{stage}: the {self.role_words(role)} already made the {'plan' if stage == 'S3' else 'cases'} follow your answer to "
                  f"{ids}; no further rework is started")
            self.finish_answer_item(item)
            return False
        rel = str(owed_item.get("words_file") or "")
        given = self.original_words({"words_file": rel})
        words = given[1] if given is not None and given[1].strip() else ""
        rel = rel if words else ""
        reason = words or ("The person answered " + ", ".join(str(a.get("id")) for a in owed_item["questions"])
                           + " after your work was written; make the " + ("rows" if stage == "S3" else "cases")
                           + " named in this rework follow the answers.")
        extra = self.answer_rework_lines(owed_item) + (self.s3_strategist_lines({"repair_cause": "question_answer"}) if stage == "S3" else [])
        complete = self.s3_window_completion({"repair_cause": "question_answer"}) if stage == "S3" else None
        try:
            self.rework(stage, role, list(owed_item.get("cases") or []), reason, cause="question_answer",
                        rows=list(owed_item.get("rows") or []), words_file=rel, extra=extra, complete=complete)
        except ReworkRefused as exc:
            self.finish_answer_item(item)                       # nothing was registered and nothing will be
            self.seam_rework_refused(stage, exc.text, words, rel, self.refusal_lines(exc))
            return True
        self.finish_answer_item(item)
        return True

    def finish_answer_item(self, item: dict) -> None:
        """The item `answer_rework_step` is done with goes out of `state["answer_rework"]`; the record goes with the last item."""
        record = self.state.get("answer_rework")
        left = [i for i in (record.get("items") if isinstance(record, dict) else None) or [] if i is not item]
        if left:
            self.state["answer_rework"] = {"items": left}
            self.save_state()
        else:
            self.drop_record("answer_rework")

    def answer_item_still_owed(self, item: dict):
        """H41: the part of `item` the plan and the cases still do NOT follow, or None when nothing is left (the role already did it, e.g.
        it was resumed with the answers) - `answer_pairs_owed` over the branch check as it reads NOW. When the check cannot be read the item
        is returned as it is: an unknown never drops owed work (FR-59)."""
        return self.answer_pairs_owed(item, self.question_branch_findings())

    @staticmethod
    def answer_pairs_owed(item: dict, findings):
        """HF3-10 (H41, M1): the part of `item` still owed, given `findings` (`question_branch_findings`: [finding] or None). The item's
        `pairs` are (question, row or case) as the check saw them when the rework was named (`seen`). A pair is owed unless it was SEEN
        (`seen is True` - anything else, a missing field included, is unseen) and the check no longer names it: the check's silence about
        a row it never saw branching on the question is not proof that the row follows the answer (the code patched the branch off for the
        first answer). A row or case is kept while ANY of its pairs is owed, or when it has no pair at all (an item of an older state);
        a question is kept while it has an OWED pair at a row or case that stays (a pair of it that is done is not told to the role), or no
        pair at all; if rows or cases stay and no question does, all the questions stay. Nothing left -> None; `findings` None -> the item as it is. ERROR DIRECTION: an extra rework, never
        a dropped one - the only input that drops work is a seen pair the check no longer names. Pure."""
        if findings is None:
            return item
        named = {(f.get("question"), f.get("where")) for f in findings if isinstance(f, dict)}
        pairs = [p for p in item.get("pairs") or [] if isinstance(p, dict)]

        def owed(pair: dict) -> bool:
            return pair.get("seen") is not True or (pair.get("question"), pair.get("where")) in named

        def stays(where) -> bool:
            theirs = [p for p in pairs if p.get("where") == where]
            return not theirs or any(owed(p) for p in theirs)
        rows = [r for r in item.get("rows") or [] if stays(r)]
        cases = [c for c in item.get("cases") or [] if stays(c)]
        if not rows and not cases:
            return None
        asked = [a for a in item.get("questions") or [] if isinstance(a, dict)]
        questions = [a for a in asked
                     if not any(p.get("question") == a.get("id") for p in pairs)
                     or any(p.get("question") == a.get("id") and p.get("where") in rows + cases and owed(p) for p in pairs)]
        return dict(item, rows=rows, cases=cases, questions=questions or asked)

    def answer_rework_lines(self, item: dict) -> list:
        """What the owner is told, one line per answer (the role reads them before the work): which question, what the person answered
        and when, and that the rows or cases named in the rework do not follow it yet. An answer in the person's own words is said so
        (no letter); an id the register no longer holds is told without the time. An answer that CHANGED (`was`, HF3-10) also says what
        it was before: the rows or cases still follow that one (FR-38: the role knows what to move away from)."""
        import planning_contract as PC
        import question_register as QR
        try:
            where_of = {q["id"]: q.get("where") for q in QR.load(self.task_root)["questions"]}
        except Exception:
            where_of = {}
        out = []
        for asked in item.get("questions") or []:
            answer = str(asked.get("answer") or "")
            said = ("answered in the person's own words" if not answer else "marked as not needed" if answer == "not_needed"
                    else f"answered `{answer}`")
            when = f" {QR.where_words(where_of.get(asked.get('id')))}" if asked.get("id") in where_of else ""
            parts = "rows" if item.get("stage") == "S3" else "cases"
            if isinstance(asked.get("was"), str):               # `was` "" is the person's own words: a changed answer all the same
                was_words = PC._answer_words(asked["was"])
                out.append(f"{asked.get('id')} is {said}{when}; it was {was_words} before, and the {parts} named in this rework "
                           "still follow that - make them follow the new answer")
                continue
            out.append(f"{asked.get('id')} is {said}{when}; the {parts} named in this rework do not follow it yet - make them follow it")
        return out

    def seam_rework_refused(self, stage: str, text: str, words: str, rel: str, lines: list) -> None:
        """The controller refused the rework the person chose (or its words are gone): the refusal goes to the conductor WITH the
        person's words and the closed list of what `args` may name, so it can offer another `rework` or ask (t-722 §4.2 p.8)."""
        facts = self.no_move_facts({"stage": stage})
        self.no_move({"why": "refusal", "kind": "conductor", "stage": stage, "dispatch": "",
                      "text": text + "\n\n" + NM.rework_args_list(facts), "words": words, "words_file": rel, "lines": lines})

    def accept_no_trace(self) -> None:
        """`--no-trace` on a story that was started without it (t-017 D3, owner decision F5):
        accepted from this stage on - closing outward writes is always the safe direction - and
        said so, because what an earlier stage already sent is not undone (FR-41).

        The flag is the command line's or the launch's (kept by S0) - the launch only while
        pipeline.json has no `no_trace` key, so an explicit false (the person's way out) is not
        re-closed on every run. And a delivery already recorded as nothing outward is said to stay
        so when the run is no longer an experiment: the flag does not reopen it (Lead's decision Q7)."""
        mark = self.state.get("delivery") or {}
        if mark.get("action") == "nothing_outward" and not self.no_trace():
            print(f"{self.task}: the delivery was already recorded as nothing outward while this run was an "
                  "experiment; it is not reopened by the flag being off now")
        pipeline = self.pipeline()
        launched = bool((self.state.get("launch") or {}).get("no_trace")) and "no_trace" not in pipeline
        if not (getattr(self.flags, "no_trace", False) or launched):
            return
        if not pipeline or pipeline.get("no_trace"):
            return
        stages = pipeline.get("stages") or {}
        stage = next((f"S{i}" for i in range(10)
                      if (stages.get(f"S{i}") or {}).get("status") not in ("done", "skipped")), "S9")
        self.py("stage_done.py", "--task", self.task, "--set", "no_trace=true", "--warn",
                f"experiment from {stage} on; earlier outward writes, if any, are not undone", check=True)
        print(f"{self.task}: --no-trace accepted from {stage} on; nothing more leaves the project, "
              "and anything sent before it is not undone")
        # t-261 (FR-37): through the layout, not by hand - a project onboarded after the two-folder layout keeps its
        # journal in `records/`, an older one in `state/`, and a path the person's own config names is honoured as written.
        import runtime_paths
        journal = runtime_paths.configured(self.project, self.config.get("journal_path"), "journal.jsonl")
        sent = 0
        if journal.is_file():
            for line in journal.read_text(encoding="utf-8", errors="replace").splitlines():
                try:
                    record = json.loads(line)
                except ValueError:
                    continue
                if record.get("event") == "external_write" and record.get("task") == self.task:
                    sent += 1
        if sent:
            print(f"{self.task}: the journal already holds {sent} external_write event(s) for this story "
                  "- they went out before the flag and stay where they are")

    # --- the loop --------------------------------------------------------------------------

    # t-2181 PC-7, the arrival road (§3.2): one road for "a side became real". Position 1 `arrival_keep` (before the freshness look, resumed
    # stories only), position 2 `arrival_record` (after `accept_no_trace`, before the loop; on the answer run of the changed-ticket question,
    # BEFORE `ticket_rework_step`), then `arrival_rework_step` in the loop turns (step 2, 3 and 5 of §3.2; step 4 is PC-8's).
    ARRIVAL_TOKENS = ("re-ground", "ignore", "stop")       # the three answers of `arrival.not_waiting`; `_answer_arrival_not_waiting` reads them

    ARRIVAL_STAGES = ["S1", "S2", "S5"]                    # data on the record: FL-6 changes the list by cause, not the step

    ARRIVAL_STAGES_FIRST_LOOK = ["S1", "S2"]               # t-2277 FL-6: the list of an arrival after `first_look_stop` (S3 on, no bind round)

    def arrival_keep(self) -> None:
        """Position 1: keeps this command line's launch word - `--mr/--branch/--commit` and `--side <s>=real` - through
        `s0_keep_late_launch`, and records what is NEW as a pending arrival in `launch["arrival"]` (`{source, side}`; it lives until
        `arrive` is written, so it outlives a question asked in this process). A source flag is new when the story is held (awaiting or
        stopped) or the value differs from the one kept. `--side <s>=real` is an arrival word only for a side the story RECORDED and that
        is not real yet (F2): any other name - an unrecorded one, a case variant, a side already real - is said in one line and kept as
        nothing. A STOPPED story given no word prints its line and ends the run (`_act_awaiting_stopped` raises `Stop`, exit 0)."""
        if not (self.task_root / "pipeline.json").is_file():
            return
        import contract
        ns, launch, pipeline = self.flags, self.state.setdefault("launch", {}), self.pipeline()
        hold, sides = contract.awaiting(pipeline), contract.story_sides(pipeline)
        held = hold["state"] != "none"
        source = {key: getattr(ns, key) for key in ("mr", "branch", "commit")
                  if getattr(ns, key, None) and (held or getattr(ns, key) != launch.get(key))}
        side = {}
        for name, word in dict(getattr(ns, "side", None) or ()).items():
            if word != "real":
                continue
            if name in sides and sides[name]["reality"] != "real":
                side[name] = word
            else:
                print(f"{self.task}: `{name}` is not a part of this story's product that was waiting; nothing changed for it")
        self.s0_keep_late_launch()
        if source or side:
            pending = launch.setdefault("arrival", {})
            pending["source"] = {**(pending.get("source") or {}), **source}
            pending["side"] = {**(pending.get("side") or {}), **side}
            self.save_state()
        if hold["state"] == "stopped" and not launch.get("arrival"):
            self._act_awaiting_stopped({"action": "awaiting_stopped", "cause": hold["cause"], "held_from": hold["held_from"],
                                        "at": (hold.get("stopped") or {}).get("at"), "words": (hold.get("stopped") or {}).get("words")})

    def sides_reread(self) -> None:
        """t-2181 PC-1b (E-U1, AR-25): a relaunch re-reads the project's record of sides when S0 could not (`pipeline.sides_unknown`).
        Nothing happens for a story that is not marked (no `pipeline.json`, or no mark). The registry is read for the story's own stand
        (`pipeline.environment`); a read that still fails or holds a malformed row keeps the mark and says why in one line. A clean
        read clears the mark and, when the story has no `pipeline.sides` yet, records the registry's non-real or referenced sides
        (`source: registry`), and the implicit `product` (`source: default`) when `contract.product_implied`, in the SAME
        `stage_done` call, so the clear and the record land together. The Thens proven while the mark
        stood keep their stamp (PC-5 owns that). INVARIANT: an unreadable registry is never read as real, and the mark never clears
        without a clean read."""
        if not (self.task_root / "pipeline.json").is_file():
            return
        pipeline = self.pipeline()
        if not pipeline.get("sides_unknown"):
            return
        import contract
        read = contract.registry_sides(self.project, pipeline.get("environment"))
        if read["problem"]:
            print(f"{self.task}: the project's sides are still unknown ({read['problem']})")
            return
        sets, now = ["sides_unknown="], _now()
        if not pipeline.get("sides"):
            entries = {}
            for name, row in sorted(read["sides"].items()):
                if row["reality"] and (row["reality"] != self.SIDE_REAL or row["reference"]):
                    entries[name] = row
            if entries:
                if contract.product_implied(read["sides"]):     # over the registry's sides, never the filtered `entries`
                    entries.setdefault("product", {"reality": self.SIDE_REAL, "deliverable": True, "settles_by": "", "reference": None,
                                                   "source": "default"})
                for name, row in entries.items():
                    attrs = {"reality": row["reality"], "source": row["source"], "at": now}
                    if row["deliverable"] is not None:
                        attrs.update(deliverable="true" if row["deliverable"] else "false")
                        if row.get("settles_by"):
                            attrs.update(settles_by=row["settles_by"])
                    if row["reference"]:
                        attrs.update(reference=row["reference"])
                    sets += self.side_set_args(name, **attrs)
        self.py("stage_done.py", "--task", self.task, *[part for item in sets for part in ("--set", item)], check=True)
        print(f"{self.task}: the project's sides were read again; the mark `sides_unknown` is cleared")

    def arrival_record(self) -> None:
        """Position 2: a pending arrival is recorded - `implementation_source` and the sides through `stage_done.py --set`
        (`source: arrival`), then the controller event `arrive`, which clears the hold - and the rework it owes is put on the record
        (`state["arrival_rework"]`, §3.2 steps 2, 3, 5) in the SAME save that spends the pending word, so a crash anywhere replays from
        one of the two records. A bare source flag makes real the sides that are `absent` and this story's own; `--side` names the
        others. A story with every side real and nothing held asks `arrival.not_waiting` first (E-A5 b): the flag is never silently
        dropped and never silently re-grounds a finished story; the answer is read from `launch["arrival"]["answer"]`, which
        `_answer_arrival_not_waiting` writes (FR-7: the question is not asked again with the same text). `becomes` and the hold's
        `since` are stored on the pending word BEFORE the first write (F3), so a replay after a partial crash records the same sides
        under the same key."""
        if not (self.task_root / "pipeline.json").is_file():
            return
        import contract
        launch, pipeline = self.state.setdefault("launch", {}), self.pipeline()
        hold, sides = contract.awaiting(pipeline), contract.story_sides(pipeline)
        pending = launch.get("arrival")
        if not pending:
            return
        source, named = dict(pending.get("source") or {}), dict(pending.get("side") or {})
        if "becomes" not in pending and hold["state"] == "none" and all(s["reality"] == "real" for s in sides.values()) and not named:
            # E-A5 (b): nothing is held, every side is real. A word recorded here (`becomes`) is past this question: a replay never asks it.
            answer = str(pending.get("answer") or "")
            if answer == "ignore":
                launch.pop("arrival", None)
                self.save_state()
                return
            if answer == "stop":
                launch.pop("arrival", None)
                self.save_state()
                raise Stop(EXIT_DONE, f"{self.task}: stopped at your word; nothing was run and nothing was changed")
            if answer != "re-ground":
                raise Person("arrival_not_waiting", self.closed_question(
                    "arrival.not_waiting",
                    f"You started {self.task} again with the code that is to be tested ({', '.join(sorted(source))} given), but the story "
                    "was not waiting for code: every part of the product it tests is already real, and it has been tested against "
                    "what existed. Nothing has been run for this word yet.\n\nWhat should the code you named do?",
                    [{"answer": "re-ground", "token": "re-ground", "slots": {"stages": "the reading of the code, the requirements and the tests"},
                      "says": "treat it as new code for this story: the story is read again against it"},
                     {"answer": "ignore", "token": "ignore",
                      "says": "drop the word and go on with the story as it stands"},
                     {"answer": "stop", "token": "stop", "says": "stop here: nothing runs now and the story stays as it is"}]), "S0")
        if "becomes" not in pending:
            # the sides that become real: the ones named (`--side <s>=real`), else - a bare source flag - the absent sides this story delivers
            pending["becomes"] = sorted(named) or sorted(name for name, s in sides.items()
                                                         if s["reality"] == contract.PARKING_REALITY and s["deliverable"] is True)
            pending["since"] = str(hold.get("since") or "")
            pending["cause"] = str(hold.get("cause") or "")        # t-2277 FL-6: stored with `becomes`, so a replay owes the same stages
            self.save_state()
        becomes, since = list(pending["becomes"]), str(pending.get("since") or "")
        sets, now = [], _now()
        for name in becomes:
            sets += self.side_set_args(name, reality="real", source="arrival", at=now)
        if source:
            sets.append("implementation_source=diff")
        if sets:
            self.py("stage_done.py", "--task", self.task, *[part for item in sets for part in ("--set", item)], check=True)
        self._arrive(becomes, source, [becomes, source, since])
        # §3.2 steps 2, 3, 5: the stages that were made without the code are made again - S1 and S2 over it, then the bind round of S5.
        # Written with the spend of the pending word in ONE save; `before` holds the earlier `source_arrived` reworks, so a second
        # arrival is owed its own. The stage list is data on the record (FL-6 selects it by cause).
        reason = ("the code this story waits for has arrived (" + ", ".join(f"{key} {value}" for key, value in sorted(source.items()))
                  + (", " if source and becomes else "") + (", ".join(becomes) + " now real" if becomes else "")
                  + "): read the story again against it")
        # t-2277 FL-6 (B2): the code that arrives after the first look stopped the story re-reads the story (S1, S2) and goes on from S3 -
        # no bind round (S5 never ran) and no affected rows (steps 4-5 of §3.2 do not apply); the stage list is data chosen by the hold's cause
        import controller as CT
        stages = list(self.ARRIVAL_STAGES_FIRST_LOOK if pending.get("cause") == CT.FIRST_LOOK_STOP else self.ARRIVAL_STAGES)
        self.state["arrival_rework"] = {
            "stages": stages, "reason": reason, "at": _now(),
            "before": sorted(self.rework_dispatches(self.controller_state().get("dispatches") or {}, "source_arrived", by_person=False))}
        launch.pop("arrival", None)             # the record is written: the pending word is spent
        self.save_state()
        print(f"{self.task}: the code arrived ({', '.join(becomes) or 'no side named'} real); "
              + ("the hold is lifted" if hold["state"] != "none" else "recorded") + "; the stages that ran without it are made again from it")

    def arrival_rework_step(self) -> bool:
        """One move of the rework the arrival owes (`state["arrival_rework"]`, §3.2 steps 2, 3, 5), or False when none is owed. Run each
        turn of the loop right AFTER `ticket_rework_step` (a changed ticket stays first, E-A2) and before `seam_rework_step`. The shape
        of `ticket_rework_step`, one stage per turn, by cause `source_arrived`: the stage's primary role (`stages.json`) goes back over
        its accepted work (S1, S2 with `complete=True`; S5 with `purpose="bind"`: the round that settles the provisional rows and runs the
        pending instances). A stage with no accepted work of its role gets one line and is skipped; one set aside before it was accepted
        ends the list with one line. After the last stage the record is dropped and `where` reads on (E-A3: a side still absent parks the
        story again). True: this turn moved something, ask `where` on the next one. Step 4 (the affected rows) is PC-8's: an absent
        `affected` list of the tester reads as none affected, said once in the line that ends the list."""
        owed = self.owed_rework("arrival_rework")
        if owed is None:
            return False
        pending, dispatches = owed
        import controller as C
        set_aside = C.DISCOUNTED - {C.NEVER_STARTED}
        stages = list(pending.get("stages") or [])
        while stages:
            stage = stages[0]
            role = str((self.stages().get(stage) or {}).get("role") or "")
            mine = [d for did, d in self.rework_dispatches(dispatches, "source_arrived", by_person=False, stage=stage).items()
                    if did not in (pending.get("before") or [])]
            status = mine[-1].get("status") if mine else None
            if status == "accepted":
                stages.pop(0)
                pending["stages"] = stages
                self.save_state()
                continue
            if mine and status in set_aside:
                print(f"{self.task}: the re-run of {stage} for the arrived code was set aside before it was accepted; nothing more is "
                      "made again for it")
                stages = []
                pending["stages"] = stages
                self.save_state()
                break
            if mine:
                return False
            if not any(d.get("stage") == stage and d.get("role") == role and d.get("status") == "accepted" for d in dispatches.values()):
                print(f"{self.task}: {stage} has no accepted work to make again for the arrived code; skipped")
                stages.pop(0)
                pending["stages"] = stages
                self.save_state()
                continue
            if self.dry:
                print("dry run: the rework the arrival owes is not started")
                return False
            reason = str(pending.get("reason") or "the code this story waits for has arrived: read the story again against it")
            if stage == "S5":
                self.rework(stage, role, [], reason, cause="source_arrived", purpose="bind")
            else:
                self.rework(stage, role, [], reason, cause="source_arrived", complete=True)
            return True
        print(f"{self.task}: the stages are made again for the arrived code; the tester's list of the rows it affects is not read here "
              "(a later step), so no row is reopened and gate A stands")
        self.drop_record("arrival_rework")
        return True

    def _arrive(self, sides: list, source: dict, key_parts: list) -> None:
        """t-2562 F-2 (AR-13, AR-15): THE `arrive` request of the driver - the sides that become real or substituted, the source flags, the
        revision of now and an idempotency key over `key_parts` (each caller owns its parts, so a replay finds the same key). The hold's
        `since` is read by the callers through `contract.awaiting`, never from the raw controller state."""
        state = self.controller_state()
        self.controller("arrive", input_data={"sides": sides, "source": source, "expected_revision": state.get("revision", 0),
                                              "idempotency_key": "arrive:" + hashlib.sha256(
                                                  json.dumps(key_parts, sort_keys=True).encode()).hexdigest()[:16]})

    def _act_await_implementation(self, action: dict) -> None:
        """`await_implementation` (S5 is done and a side this story delivers is absent: record the wait) and `awaiting_implementation`
        (the wait is recorded; E-A4: a relaunch with no flag re-prints and dispatches nothing). The packet `interim-report.md` is
        assembled by code from data (`interim_packet.py`, rebuilt each time: a ticket rework while waiting may have rewritten tests)
        and printed; the run then ends with exit 0. No gate B, no verdict, no bug (D2). The packet is chosen by the cause (t-2277 FL-6):
        `first_look_stop` prints `first_look_packet` (what the stand showed), any other cause the S5 packet. A bare relaunch of a
        `first_look_stop` hold first asks `first_look_code_look` whether the code moved: True = the arrival is recorded and the loop goes on
        (INVARIANT: no role of a stage from S3 on starts before an arrival or a `continue`)."""
        import contract
        import controller as CT
        import interim_packet
        first_look = action.get("cause") == CT.FIRST_LOOK_STOP
        if first_look and action.get("action") == "awaiting_implementation" and self.first_look_code_look(action):
            return
        waiting = {name for name, side in contract.story_sides(self.pipeline()).items()
                   if side["reality"] == contract.PARKING_REALITY and side["deliverable"] is True}
        write = interim_packet.write_first_look if first_look else interim_packet.write
        path = write(self.task_root, self.continue_command(drop_absent=waiting))         # F7: no `--side <s>=absent` beside `--branch`
        if action.get("action") == "await_implementation":
            state = self.controller_state()
            # F8: the S5 dispatch the wait is about is the newest ACCEPTED one (a superseded, stale or rejected round is no basis)
            s5 = [did for did, d in (state.get("dispatches") or {}).items()
                  if isinstance(d, dict) and d.get("stage") == "S5" and d.get("status") == "accepted"]
            # (e): the cause and the place the hold starts at travel from the action when it names them (the controller emits them)
            self.controller("await", input_data={"packet": path.name, "s5_dispatch": s5[-1] if s5 else None,
                                                 **{key: action[key] for key in ("cause", "held_from") if action.get(key)},
                                                 "expected_revision": state.get("revision", 0),
                                                 "idempotency_key": f"await:{state.get('revision', 0)}"})
        print(path.read_text(encoding="utf-8"))
        if not first_look and waiting:
            # t-2559 (W2 B3, t-2562 B-1/B-2): on BOTH actions (the hold was just recorded, or it is met again) the factory says what it waits
            # for and asks whose a missing side is, ONE question per side not yet answered for THIS hold (`_absent_side_next`, keyed by the
            # hold's `opened`), so the `not ours` door the packet and `next` name exists on every road (a crash, a lost question file,
            # a bare relaunch). FR-7 is kept by a changed lead, never by silence.
            # remains: a closed question over the story's own state (the `first_look.same_code` shape); every answer has an executor (`_answer_absent_side`)
            person = self._absent_side_next(waiting, str(action.get("held_from") or "S6"))
            if person is not None:
                raise person
        raise Stop(EXIT_DONE, f"{self.task} is waiting for the code; nothing runs until it arrives "
                              f"(the report is qa-factory/artifacts/{self.task}/{path.name})")

    def _act_awaiting_stopped(self, action: dict) -> None:
        """`awaiting_stopped`: the person ended the wait; nothing is relaunched. Prints the stopped line with the doors and ends the run
        with exit 0 (E-W1). A relaunch with the code (`arrive`) or a rework of the stages before `held_from` with words is the way out."""
        held = str(action.get("held_from") or "S6")
        said = " ".join(str(action.get("words") or "").split())[:200]
        import controller as CT
        if action.get("cause") == CT.FIRST_LOOK_STOP:
            # t-2277 FL-6 (J-9 does not apply: the person ended this wait): the line names the first look, not a missing side
            print(f"{self.task}: this story was stopped on {str(action.get('at') or '')[:10] or 'an earlier day'} after the first look, "
                  "when the feature did not work" + (f": \"{said}\"" if said else "") + ". Nothing runs. To check new code, start the story "
                  "again with --mr <link>, --branch <name> or --commit <sha>.")
            # remains: the person ended this wait (J-9 does not apply); the line is the answer and the run ends with exit 0, as the stop below
            raise Stop(EXIT_DONE, f"{self.task} is stopped; no stage runs")
        print(f"{self.task}: the wait for the code was ended on {str(action.get('at') or '')[:10] or 'an earlier day'}"
              + (f" at your word: \"{said}\"" if said else "") + f". Nothing from {self.stage_place(held)} on runs. "
              "To take it up again, start the story again and name where the code is, or ask for the earlier stages to be made again, "
              "with your words.\n\nHow to start it again: --mr <link>, --branch <name> or --commit <sha>; for one part of the product "
              "only, --side <name>=real.")
        raise Stop(EXIT_DONE, f"{self.task} is stopped; no stage runs")

    # --- the code look of a story held after the first look (t-2277 FL-6, J-9 (b), N3) ----------------------------------------------

    def first_look_code_look(self, action: dict) -> bool:
        """A relaunch with NO flag of a story held for `first_look_stop`: did the code move since the first look? True = it did (or the
        manifest names an implementation the record does not): the arrival is recorded with the earlier source (`arrival_record`, the road of
        a flag) and the caller returns, so the loop owes S1, S2 and then S3. False = nothing more is owed here: the caller prints the packet
        and ends the run (exit 0). Otherwise the closed question `first_look.same_code` is raised (`Person`).
        RULE (N3, FR-59, AR-28): ANY repository moved (recorded and live are both commits and differ) or a NEW entry -> arrive; else a
        repository whose recorded or live head is not a commit (`unmeasured`, network, checkout, timeout) or that the story no longer names ->
        the question with ONE line per such repository, never "moved"; else (all equal) the question with no such line. The person
        decided in THIS process (`answer_kind`): the `stop` of `first_look.dead` ends at once (False); `wait` ends with the packet (False),
        `source` prints the restart command and ends (Stop) - the question is not asked again over the answer just taken (FR-7)."""
        import first_look as FL
        kind = self.answer_kind
        if kind == "first_look_dead":
            return False
        if kind == "first_look_same_code":
            said = [row for row in _read_jsonl(self.state_dir / "driver-answers.jsonl") if row.get("kind") == "first_look_same_code"]
            if said and said[-1].get("token") == "source":      # the FIRST line of the answer: `_same_code_answer` records it so
                import contract
                import interim_packet
                waiting = {n for n, s in contract.story_sides(self.pipeline()).items() if s["reality"] == contract.PARKING_REALITY and s["deliverable"] is True}
                print("\n".join(interim_packet.restart_lines(self.continue_command(drop_absent=waiting))))
                # remains: the person chose `source` - the restart command is the whole answer and the run ends with exit 0 (the hold stands)
                raise Stop(EXIT_DONE, f"{self.task} waits for the code; nothing runs until it arrives")
            return False
        found = self._first_look_heads(FL)
        if found["moved"] or found["new"]:
            launch = self.state.setdefault("launch", {})
            pending = launch.setdefault("arrival", {})
            pending["source"] = {**(pending.get("source") or {}), **{key: launch[key] for key in ("mr", "branch", "commit") if launch.get(key)}}
            pending.setdefault("side", {})
            self.save_state()
            print(f"{self.task}: the code changed since the first look ({', '.join(found['moved'] + found['new'])}); it arrives")
            self.arrival_record()
            return True
        # remains: a closed question over the story's own state (the `first_look.dead` shape): every answer has an executor (`_same_code_answer`)
        raise self._first_look_same_code_person(FL, found)

    def _first_look_heads(self, FL) -> dict:
        """The comparison the rule of `first_look_code_look` stands on, for EVERY repository of the first look's record: `{moved, new,
        same, unknown: [(repo, why)], recorded, record, details}`. The record is read through `first_look.read` (one reader, AR-13), the
        implementation entries through `first_look.source_entries` (the one naming of them). Every `why` is plain words (human-questions.md);
        the factory's own words behind it (git's refusal, a stored value) are in `details`, which the question carries as its details file.
        A merge request's live head is asked by `git ls-remote origin refs/merge-requests/<number>/head` in the checkout of that repository
        (`repo_of_project`, `ls_remote_head`), a branch's the same way with `refs/heads/<branch>`; a commit does not move. Nothing raises:
        a doubt is a line."""
        record = FL.read(self.task_root)
        out = {"moved": [], "new": [], "same": [], "unknown": [], "recorded": dict(record["source_head"]), "record": record, "details": []}
        entries = FL.source_entries(self.task_root)
        if record["problem"] and not record["source_head"]:
            out["unknown"].append(("the repositories", "the record of the first look cannot be read"))
            out["details"].append(f"the record of the first look: {record['problem'][:160]}")
            return out
        for key, was in sorted(out["recorded"].items()):
            entry = entries.get(key)
            if entry is None:
                out["unknown"].append((key, "the story's record of the code no longer names this repository" if entries
                                       else "the story's record of the code is empty or cannot be read"))
                continue
            live, why, raw = self._first_look_live_head(entry, key)
            if not live:
                out["unknown"].append((key, why))
                out["details"] += [f"{key}: {raw}"] if raw else []
            elif not FL.COMMIT.fullmatch(was):
                out["unknown"].append((key, "the first look did not record which commit it saw"))
                out["details"].append(f"{key}: the recorded head is `{was[:120]}`")
            elif live != was:
                out["moved"].append(key)
            else:
                out["same"].append(key)
        out["new"] = [key for key in entries if key not in out["recorded"]]
        return out

    def _first_look_live_head(self, entry: dict, key: str) -> tuple:
        """`(commit, "", "")` or `("", why, raw)`: the head the source of ONE implementation entry has NOW. `why` is plain words for the
        person, `raw` the factory's own words behind it (for the details file). A merge request (`mr`: a number or a link) is asked of the
        remote in the repository's one checkout (`ls_remote_head`, `refs/merge-requests/<n>/head`); when that gives nothing, the entry's own
        `branch` is asked the same way (a link no number can be read from goes straight to the branch); a `commit` alone is itself. An entry
        that names a merge request or a branch NEVER falls back to its `commit`: the commit is what was seen, it cannot say the code is
        unchanged (AR-28). Any failure is the reason, never a move."""
        import first_look as FL
        import vcs_evidence
        mr, branch, commit = (str(entry.get(name) or "").strip() for name in ("mr", "branch", "commit"))
        iid = vcs_evidence.mr_iid(mr)       # AR-13: the one reader of the manifest's `mr` (the base slice reads its receipt by the same number)
        if iid or branch:
            unusable: list = []
            found = self.repo_of_project(str(entry.get("repo_id") or entry.get("repo") or key), why=unusable)
            if not found:
                return "", "no checkout of it is set up on this machine", "; ".join(unusable) or f"no local checkout of `{key}` is configured"
            asks = ([(f"merge request {iid}", f"refs/merge-requests/{iid}/head", "the merge request is not listed there")] if iid else []) \
                + ([(f"branch {branch}", f"refs/heads/{branch}", "the branch is not listed there")] if branch else [])
            raws = []
            for label, ref, missing in asks:
                head, raw = self.ls_remote_head(found[1], ref, missing)
                if head:
                    return head, "", ""
                raws.append(f"{label}: {raw}")
            return "", f"the remote did not give the current commit of its {'merge request' if iid else 'branch'}", "; ".join(raws)
        if mr:
            return "", "the link to its merge request is not one this machine can read", f"no merge request number in `{mr[:120]}`"
        if FL.COMMIT.fullmatch(commit):
            return commit, "", ""
        return "", "the story's record names no merge request, branch or commit to ask about", ""

    def _first_look_same_code_person(self, FL, found: dict) -> "Person":
        """The closed question `first_look.same_code` as a `Person` (kind `first_look_same_code`, held from S3): the day the story stopped, the
        counts of the record, the heads by repository and, for each repository whose head could not be established, one line saying so
        (FR-59). After an earlier `wait` the text carries its day - read from the rows of answered questions the driver keeps
        (`driver-answers.jsonl`, the carrier `already_answered` reads); a row that does not read gives a question without the line."""
        import contract
        import interim_packet
        pipeline = self.pipeline()
        hold = contract.awaiting(pipeline)
        since = str(hold.get("since") or "")[:10] or "an earlier day"
        record = found["record"]
        lines = []
        if record["problem"] and not record["rows"]:
            lines.append(f"You stopped this story on {since} after the first look at the stand. The record of that look cannot be read now.")
        else:
            share = FL.share(self.task_root, self.config)
            lines.append(f"You stopped this story on {since} after the first look at the stand `{record.get('stand') or pipeline.get('environment')}`: "
                         f"it showed {share['reachable']} of {share['counted']} requirements"
                         + (f" ({share['share']}%)" if share["share"] is not None else "")
                         + f". Every requirement, by what the stand answered: {interim_packet.status_counts(record['rows'])}.")
        waits = [row for row in _read_jsonl(self.state_dir / "driver-answers.jsonl")
                 if row.get("kind") == "first_look_same_code" and row.get("token") == "wait"]
        day = str(waits[-1].get("ts") or "")[:10] if waits else ""
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
            lines.append(f"On {day} you chose to wait" + ("." if found["unknown"] else "; the code has not changed since."))
        heads = [f"{repo} {interim_packet.short_head(was)}" for repo, was in sorted(found["recorded"].items())]
        lines.append("The code the first look was about, by repository: " + ("; ".join(heads) if heads else "none is recorded") + ".")
        lines += [f"I could not find out whether the code in {repo} has changed: {why}." for repo, why in found["unknown"]]
        lines.append("What I need from you is one of these:")
        options = [{"answer": "wait", "token": "wait",
                    "says": "keep the story stopped and show you the same summary again; nothing runs"},
                   {"answer": "source", "token": "source",
                    "says": "tell me where the new code is: I print the command that starts the story again with it"},
                   {"answer": "continue", "token": "continue",
                    "says": "go on with the plan as it is; the plan reads what the stand showed as an observation, not as the truth"}]
        return Person("first_look_same_code", self.closed_question("first_look.same_code", "\n\n".join(lines), options), "S3",
                      details="\n".join(found["details"]), answer_note="Write `wait`, `source`, `continue`, or your own words (the conductor reads them).")

    ABSENT_SIDE_TOKENS = ("not ours", "relaunch")        # the two answers of `awaiting.absent_side`; `_answer_absent_side` reads them

    SIDE_SUBSTITUTED = "substituted"                      # a word of side-realities.json (the writer refuses any other)

    def _absent_side_next(self, waiting: set, held_from: str) -> "Person | None":
        """t-2562 (B-1, B-2): the question of the hold's next absent side, or None. The answers are kept per hold in
        `state["absent_side_answers"]` = {opened, sides: {name: {token, at}}}; `opened` is the hold's identity (`contract.awaiting`, the
        `await` event's number; a record without it reads as the empty key, so the hold still asks). A side with no answer for this hold is
        asked, the first by name (a crash before the question file was written leaves no answer, so it is asked again). Every side answered
        `relaunch`: in the process of that answer nothing is asked (the exit 0 of old); in a LATER process the first is offered again with
        a lead that names the earlier answer (FR-7: never the same text twice). INVARIANT: a side the person called not ours is never
        waiting, so it is never asked; no waiting side, no question."""
        import contract
        hold = contract.awaiting(self.pipeline())
        opened = "" if hold.get("opened") is None else str(hold["opened"])
        record = self.state.get("absent_side_answers")
        if not (isinstance(record, dict) and record.get("opened") == opened and isinstance(record.get("sides"), dict)):
            record = {"opened": opened, "sides": {}}
            self.state["absent_side_answers"] = record
            self.save_state()
        answers = record["sides"]
        fresh = [name for name in sorted(waiting) if name not in answers]
        if fresh:
            return self._absent_side_person(fresh[0], held_from)
        if getattr(self, "_absent_answered_here", False):
            return None
        again = [name for name in sorted(waiting) if isinstance(answers.get(name), dict) and answers[name].get("token") == "relaunch"]
        if not again:
            return None
        return self._absent_side_person(again[0], held_from, earlier=str(answers[again[0]].get("at") or ""))

    def _absent_side_person(self, name: str, held_from: str, earlier: str = "") -> "Person":
        """t-2559 (W2 B3): the closed question `awaiting.absent_side` as a `Person` (kind `absent_side`) over the side `name`: what the
        factory waits for, and whose the side is. The name is kept in `state["absent_side"]` for the executor (never read back out of the
        question's text, FR-12). `earlier` (the date of an earlier `relaunch` for this hold) changes the lead (FR-7). Plain words only
        (human-questions.md): no stage code, field or path."""
        self.state["absent_side"] = name
        self.save_state()
        if earlier:
            lead = (f"On {earlier} you said you would start {self.task} again when the code exists; the code for the part of the product "
                    f"called `{name}` is still not named, and the story still waits for it. Nothing has been delivered. Whether `{name}` is "
                    f"this team's to make or another team's decides whether the story keeps waiting.\n\nWhat should happen with `{name}`?")
        else:
            lead = (f"The tests for {self.task} are written and reviewed, but the part of the product called `{name}` does not exist yet, and "
                    f"this story is the one that delivers it, so the story waits for its code. Nothing has been delivered. Whether `{name}` is "
                    f"this team's to make or another team's decides whether the story keeps waiting.\n\nWhat should happen with `{name}`?")
        options = [{"answer": "not ours", "token": "not ours",
                    "says": f"`{name}` is another team's: the story does not wait for it, the tests go on against a stand-in for it "
                            "(mocks), and the report lists what was not checked against the real one"},
                   {"answer": "relaunch", "token": "relaunch",
                    "says": "you start the story again when the code exists and say where it is; until then nothing runs"}]
        return Person("absent_side", self.closed_question("awaiting.absent_side", lead, options), held_from,
                      answer_note="Write `not ours`, `relaunch`, or your own words (the conductor reads them).")

    def until_reached(self, action: dict) -> bool:
        if not self.until:
            return False
        stage = str(action.get("stage") or "")
        # F1 (PC-7 critic): `await_implementation`, `awaiting_implementation` and `awaiting_stopped` are NOT here. Their handlers
        # already end the run with exit 0 (`Stop(EXIT_DONE)`), and checked here BEFORE the dispatch they would end `--until gate_B`
        # without the packet and without the `await` record (the story would read "not awaiting" to every reader).
        return (stage in UNTIL_PAST[self.until] or action.get("action") in ("stop", "complete"))

    def dispatch_action(self, action: dict) -> None:
        """One handler per action kind (t-667 D15). The `kind == "..."` forms stay literal: the census of
        `refusal_every_action_has_a_move` reads them. A handler returns what its branch returned (None); `Driver.gate` ends in
        `raise Person`, so `_act_await_gate` never returns normally past the gate. An action with no move reaches the last line."""
        kind = action.get("action")
        if kind == "prepare_stage":
            return self._act_prepare_stage(action)
        if kind == "await_gate":
            return self._act_await_gate(action)
        if kind == "closed":
            return self._act_closed(action)
        if kind == "execute_gate_b":
            return self._act_execute_gate_b(action)
        if kind == "wait_existing_job":
            return self._wait_then_critic(action)
        if kind == "resume_checkpoint":
            return self._act_resume_checkpoint(action)
        if kind == "relaunch":
            return self._act_relaunch(action)
        if kind == "resolve_return":
            return self._act_resolve_return(action)
        if kind == "await_implementation":
            return self._act_await_implementation(action)
        if kind == "awaiting_implementation":
            return self._act_await_implementation(action)
        if kind == "awaiting_stopped":
            return self._act_awaiting_stopped(action)
        if kind == "observe_environment_job":
            self.environment_job(action)
            return
        if kind in ("handoff_ready", "rollover_pending"):
            self.orchestrator_rollover(action)
            return
        raise Refusal(f"the driver has no move for `{kind}`: {json.dumps(action)[:800]}")

    def _act_prepare_stage(self, action: dict) -> None:
        stage = action["stage"]
        self.boundary = stage
        if stage == "S0":
            if (self.task_root / "pipeline.json").is_file():
                self.code_only("S0", "preflight green: S0 closed on a task initialized before it", ["pipeline.json"])
            else:
                self.s0()
        elif stage == "S1":
            self.stage_simple(stage)
        elif stage == "S2":
            self.stage_S2()
        elif stage == "S3":
            self.stage_S3()
        else:
            getattr(self, f"stage_{stage}")()

    def _act_await_gate(self, action: dict) -> None:
        # t-211: the rehearsal comes BEFORE the person. Everything it lists that code can repair is
        # repaired first (a round is dispatched and the loop comes back through `where`); the gate is
        # shown only when nothing is left to repair, or with the remainder stated at its top.
        if action["gate"] == "B":
            # B-364 R18 (F10 c): the person decides gate B knowing whether the requirements moved since a look
            # older than the freshness window - the position phases/s8.md section 2b gives. BEFORE the rehearsal,
            # because a `ticket_changed` question (the new text re-runs S2-S3 and gate A) makes the rehearsal's
            # findings moot; gate A gets no pre-check (s8.md names gate B). Every gate of the entry applies (no
            # controller, ticket not needed, a closed story, another question open) and a failed look is a line.
            self.ticket_freshness_entry()
            # RN1-24 POSITION INVARIANT: after the freshness look (a changed ticket is asked first) and BEFORE the rehearsal and the
            # gate: gate B is never shown while a question about a manual case is unanswered
            self.deferred_step()
        shown = self.gate_repair(action["gate"])
        if shown["ran"]:
            return
        self.gate(action["gate"], top=shown["top"])

    def _act_closed(self, action: dict) -> None:
        # A closed story is not a story with nothing left: the controller says so in its own
        # words — "the retro is the one stage that still runs on a closed story, so its id
        # travels with the answer" — and sends `stage` and `retro_pending` inside the action.
        # The driver had no branch for `closed` at all, so live TP1-13797 run 5 reached
        # the person as "this story is closed, do you want to reopen it?" with gate B just
        # decided and S9 never started. The person's reason then had nowhere to go either,
        # and the same question was asked twice: four conductor calls, $0.45, no move.
        held = [item for item in action.get("held") or [] if isinstance(item, dict) and item.get("dispatch_id")]
        if held:
            # B-331 (C1-6a): work that never started is not started on a closed story without a person's word. The question
            # comes BEFORE the retro (edge 3: the retro reads the story's final state, so it runs after the answer). A story a
            # person reopened for PART of that work asks about the rest the same way (`reopened_at` on the action, B1).
            # remains: the site's own closed question (`run again` / `leave` / `stop`, each with an executor in `_take_closed_held_answer`)
            raise self.closed_held_person(held, reopened=bool(action.get("reopened_at")))
        if action.get("retro_pending") and action.get("stage"):
            self.boundary = str(action["stage"])
            getattr(self, f"stage_{action['stage']}")()
            return
        # A8: a finished story with nothing held says so and nothing more - no promised reopen: the road back to a closed story
        # exists only as the `closed_held` question above, and as a person's own rework through the conductor.
        import story_step
        # Every terminal exit of this method that ends the story keeps `give_back_config` before its Stop (a new terminal branch gets the same call).
        if story_step.give_back_config(self.project, self.task_root, self.task):      # HF5-6: S9 is recorded, the story ends here (a second call reverts nothing: the copy is marked)
            self.rebuild_report()       # F4: the report's "where to look" block carries the revert line (read from the copy); once, a second call has no line
        raise Stop(EXIT_DONE, f"{self.task}: the story is finished; nothing is pending.")

    def _act_execute_gate_b(self, action: dict) -> None:
        """`execute_gate_b` (t-1509, GB-1b): gate B is decided and what the person ordered there is not carried out yet. The
        orders are carried out by `after_gate_B`; the controller then says `closed` (every order done or called off) or says
        this again. A pass that moved no order is NOT repeated blindly (AR-17, FR-48): the first one is looked at again by the
        loop, the second goes to the one seam `no_move` - the conductor, with the person behind it - never a third pass."""
        import controller as C
        self.boundary = "S8:gate_b_orders"
        before = [str(o.get("order")) for o in action.get("orders") or [] if isinstance(o, dict)]
        self.after_gate_B()
        after = C.orders_due(self.controller_state())
        if set(before) - set(after):                    # an order that was due is not any more: something moved
            self.gate_b_idle = 0
            return
        self.gate_b_idle += 1
        if self.gate_b_idle < 2:
            return
        self.gate_b_idle = 0
        words = {"bugs": "the bug reports", "mr": "the merge request"}
        named = " and ".join(words.get(o, o) for o in after or before) or "what gate B decided"
        self.no_move({"why": "threshold", "kind": "refusal", "stage": "S8", "dispatch": "",
                      "lead": f"What you decided at gate B is not carried out yet ({named}), and the factory tried twice without moving it. "
                              "Which of these should happen?",
                      "text": json.dumps({"orders": action.get("orders"), "still_due": after}, ensure_ascii=False)[:2000]})

    def closed_held_person(self, held: list, reopened: bool = False) -> "Person":
        """The `closed.held` question (B-331, C1-6a): a CLOSED story whose work never started. `run again` / `leave` / `stop`, each
        with its executor (`_take_closed_held_answer`, FR-9). The ids the question NAMES are kept in `state["closed_held"]`: one answer
        covers exactly that set (edge 4), whatever `next` lists when the answer arrives. `reopened`: the story was already reopened
        for other work (a partial `run again`), and this is the question about the rest."""
        def piece(item: dict) -> str:
            why = " ".join(str(item.get("reason") or "").split())[:200]
            return f"{self.stage_place(str(item.get('stage') or ''))}, {item.get('role') or ''}" + (f" - {why}" if why else "")
        n = len(held)
        opening = (f"{self.task} was reopened for other work." if reopened
                   else f"{self.task} is finished (gate B is decided, S8 is done).")
        lead = (f"{opening} {n} piece(s) of work never started: "
                + "; ".join(piece(item) for item in held) + ". Starting it "
                + ("needs your words." if reopened else "reopens the story with your words.") + "\n\n"
                "What I need from you is one of these:")
        roles = " and ".join(dict.fromkeys(str(item.get("role") or "") for item in held if item.get("role")))
        text = self.closed_question("closed.held", lead, [
            {"answer": "run again", "token": "run again", "slots": {"role": roles or "the role"},
             "says": "start the work that never started; the story is reopened with your words, and each piece runs, one at a time"},
            {"answer": "leave", "token": "leave",
             "says": "leave it as it is (also when you finish it yourself); the work that never started is recorded as left "
                     "with your words, and nothing asks for it again"},
            self.STOP_OPTION])
        self.state["closed_held"] = {"dispatch_ids": [str(item["dispatch_id"]) for item in held]}
        return Person("closed_held", text, str(held[0].get("stage") or ""),
                      details="The work that never started, as the factory recorded it:\n"
                              + "\n".join(f"{item['dispatch_id']}: {item.get('stage')} {item.get('role')} - {item.get('reason') or ''}"
                                          for item in held))

    def _wait_then_critic(self, action: dict) -> None:
        """`_act_wait_existing_job`, then the stage critic's route over a finished ticket re-run (`ticket_rerun_critic`). The one entry of
        the `wait_existing_job` action and of its `retry`."""
        self._act_wait_existing_job(action)
        self.ticket_rerun_critic(str(action.get("dispatch_id") or ""))

    def _act_wait_existing_job(self, action: dict) -> None:
        dispatch = action.get("dispatch_id", "")
        state = self.controller_state()
        record = (state.get("dispatches") or {}).get(dispatch) or {}
        stage, role = str(record.get("stage") or ""), str(record.get("role") or "")
        self.boundary = f"{stage}:{dispatch}"
        words = self.state["pending_words"].get(dispatch)
        if words:
            self.resume_role(stage, role, dispatch, words, complete=self.completion_for(stage, role, record))
            return
        asked = self.state.get("asked") or {}
        if asked.get("dispatch") == dispatch and asked.get("kind") == "questions" \
                and self.question_path().is_file():
            # INVARIANT (t-113 B2, edge x): a threshold stop that nobody has answered is asked again,
            # and is never finished from the role's saved result below - that result is the very
            # handoff the stop held back, so finishing it would close the stage over the questions.
            text = self.question_path().read_text(encoding="utf-8", errors="replace")
            raise Person("questions", QUESTION_HEAD_RE.sub("", ANSWER_BLOCK_RE.sub("", text), count=1).strip(),
                         stage, dispatch)
        saved_path = self.state_dir / "driver-runs" / f"{dispatch}.json"
        saved = _read_json(saved_path)
        if saved.get("result") and self.retire_infra_result(saved_path, saved, role=role, stage=stage,
                                                             dispatch=dispatch):
            saved = {}   # not a result: the interruption is recorded and the branch below continues it
        if saved.get("result"):
            return self._finish_saved_result(saved, role, stage, dispatch, record)
        if (self.state.get("interrupted") or {}).get(dispatch):
            # A call an infrastructure failure cut off: the SAME role goes on, in the session that did
            # work or fresh with a note (`run_claude` decides which). It comes after the person's words
            # and after a valid saved result - both are newer facts than the interruption - and before
            # the `asked` check, which is about a question, and there is none here.
            print(f"{dispatch}: was cut off by an infrastructure failure - continuing it")
            self.run_role(stage, role, scope=list(record.get("scope") or []),
                          extra=self.s3_record_lines(stage, role, record),
                          complete=self.completion_for(stage, role, record),
                          rework={"id": dispatch, "scope": list(record.get("scope") or []),
                                  "line": "Not a rework: continue this dispatch after an infrastructure "
                                          "interruption"})
            return
        asked = self.state.get("asked") or {}
        if asked.get("dispatch") == dispatch and asked.get("kind") in ("halt", "s1_review"):
            text = (self.state_dir / "driver-question.md").read_text(encoding="utf-8", errors="replace")
            raise Person(asked["kind"], text.split("\n", 6)[-1], stage, dispatch)
        if dispatch and dispatch not in self.state["sessions"]:
            # A dispatch this driver never launched (the conductor registered it while
            # lifting a block, TP1-13797 run 3: the manual half of S6). The driver is
            # the only executor here, so the answer to "nobody is running it" is to run it.
            print(f"{dispatch}: registered but never launched by this driver — running it now")
            if stage in self.STAND_STAGES:      # this STARTS a role on the stand: the same check as the stage's entry
                self.stand_check(stage, str(record.get("execution_kind") or ""))
                self.build_check(stage, str(record.get("execution_kind") or ""), cases=list(record.get("scope") or []))
            # F-2 (t-1252, AR-24): this is the road of a conductor's `continue` over a dispatch that a G site registered and did not
            # record (G3 `run_manual_block`, O4 `_act_relaunch`). It starts the role the way the site would have: the `running` record
            # first (`record_running`; a refusal's `retry` is this whole branch), the standing role lines, and - for a relaunched
            # packet - the relaunch reason (the fresh_line and the person's release words, whole). INVARIANT: the packet is registered
            # ONCE (nothing here dispatches); the record comes after the stand and build checks above, so a refused check leaves
            # nothing recorded as running.
            import controller as CT
            labelling = CT.s3_window_of(record) == "labelling"
            scope = list(record.get("scope") or [])
            relaunched = bool(record.get("relaunch_of"))
            self.record_running(stage, role, dispatch, retry=lambda: self._wait_then_critic(action), relaunched=relaunched,
                                rework_of=str(record.get("rework_of") or ""))
            # The registered record's own `reason` is what the role is told (FR-8): the person's words of a conductor rework, whole.
            # `purpose` ("repair_verify") is a word of the controller's, not a reason (C1-2, F3). Window 1 of S3 is not a rework
            # (G1-11): the word `s3_labelling` is never shown as a reason. The role lines are the record-aware ones (G1-11: the S3
            # strategist's window lines ride on its record; merge of C1-7c over G1-11, 21.10).
            reason = (self.relaunch_reason(record, action) if relaunched
                      else str(record.get("reason") or (record.get("purpose") if not labelling else "")
                               or "registered dispatch"))
            self.run_role(stage, role, scope=scope, extra=self.role_lines(stage, role, record),
                          complete=self.completion_for(stage, role, record),
                          rework={"id": dispatch, "scope": scope, "reason": reason,
                                  **({"line": "Not a rework: window 1 of S3 registered and never launched"} if labelling else {})})
            return
        self._liveness_refusal(action, dispatch, record)

    def _finish_saved_result(self, saved: dict, role: str, stage: str, dispatch: str, record: dict) -> None:
        """t-667 D15: the role's saved result finishes the dispatch (the tail `run_role` twins). Returns None (the branch's `return`)."""
        # t-2022 N6: a walk dispatch gets its `after` on THIS road too (a driver killed after the saved result was written and before `walk_after`
        # ended comes back here): idempotent (`after.json`), BEFORE `handoff` and `finish` like `run_role`'s, so the form has its values
        lane, _ = self.walk_reopen(dispatch, reopen=False)          # the items of the walk record only; nothing is opened
        if lane:
            self.walk_after(lane, dispatch, saved)
        digest = self.handoff(role, stage, dispatch, saved)
        # The saved result may be one a refusal resumed (t-217 `resume_on_refusal`) and the role halted in
        # its answer: `run_role` hears a halt before `finish`, and so must the entry that finishes a saved
        # result - a halted role is the person's, and `finish` would close its dispatch over the halt.
        import story_step
        if story_step._declared_halt(self.task_root, story_step.FORM_REL.format(dispatch_id=dispatch), digest):   # CX1-14 (B-2): the one reader
            # O3 (C1-7c, kind T as T1 and O1): the same record, the same invariant (`HALT_RECORD_WHY`); the role is not run again
            self.py_trace("stage_done.py", "--task", self.task, "--stage", stage, "--status", "halted", "--role", role, "--digest", digest,
                          why=HALT_RECORD_WHY)
            raise Person("halt", self.halt_text(stage, role, digest), stage, dispatch,
                         details=str(digest or "").strip() or "the role's final message was empty")
        self.repair_limit_gate(stage, role, dispatch, digest, record.get("scope"), recovering=True)      # t-698 A4: no answer asks
        self.finish(dispatch, digest, complete=self.completion_for(stage, role, record), role=role, stage=stage)

    def _liveness_refusal(self, action: dict, dispatch: str, record: dict) -> None:
        """t-667 D15: the last word of `wait_existing_job` - nothing to resume, finish or ask - always raises a Refusal."""
        # Say what is known about the agent, in the word the evidence supports. The action
        # itself carries no verdict (`next` does not pay for one on every boundary), and
        # the driver prints `liveness=None`, which reads as "nothing is wrong" - while the
        # honest answer is often "nobody can tell". FR-41: the no-evidence state has its own
        # word and it is printed. Five of run 5's first nine questions to a person were this
        # boundary.
        verdict = {"state": "unknown", "evidence": ["liveness could not be read"]}
        try:
            import dispatch_liveness
            verdict = dispatch_liveness.state(self.project, self.task, dict(record, id=dispatch))
        except Exception as exc:
            verdict["evidence"] = [f"{type(exc).__name__}: {exc}"]
        told = {"unknown": "nobody can tell whether its agent is running: this host keeps no "
                            "evidence either way",
                "alive": "its agent is working",
                "abandoned": "its agent is gone",
                "never_started": "its agent never started",
                "returned": "its agent returned"}.get(str(verdict.get("state")), str(verdict.get("state")))
        raise Refusal(f"wait_existing_job {dispatch}: {told} — " +
                      "; ".join(str(item) for item in (verdict.get("evidence") or [])[:3]) +
                      f". The driver holds no result and no question for it: {json.dumps(action)[:500]}",
                      dispatch=dispatch)

    def _act_resume_checkpoint(self, action: dict) -> None:
        dispatch = action.get("dispatch_id", "")
        record = (self.controller_state().get("dispatches") or {}).get(dispatch) or {}
        words = self.state["pending_words"].get(dispatch)
        stage, role = str(record.get("stage") or ""), str(record.get("role") or "")
        self.boundary = f"{stage}:{dispatch}"
        if words:
            # FB-4 (the driver's side of the ONE `resume`, AR-19/AR-15): a dispatch stopped for a person (`blocked` / `paused`) and
            # continued by its own session is made `running` in the controller BEFORE the session goes on, by the command the
            # skill road runs - `story_step.py resume` - so `finish` accepts it and no `S<n>-<role>-2` retry supersedes the role.
            # POSITION INVARIANT: before `resume_role` (it records the stage `running` and runs the session): a role is never
            # resumed over a record the controller did not move; a refusal is a `Refusal` carrying the dispatch and `retry`
            # (this whole step, the G3 pattern of `record_running`), and the words stay in `pending_words`. No known session, or
            # another status (`incomplete`: its agent is gone, the road is the retry packet): nothing is run and the road is as
            # it was - the driver never invents an agent.
            sid = self.session_of(stage, dispatch)      # TR3-6: on a chain the dispatch's own session only
            if record.get("status") in ("blocked", "paused") and sid:
                try:
                    self.py("story_step.py", "resume", "--task", self.task, "--dispatch-id", dispatch, "--agent-id", sid,
                            check=True, expect=f"{dispatch} resumed")
                except Refusal as refusal:
                    refusal.dispatch = dispatch
                    refusal.retry = lambda: self._act_resume_checkpoint(action)
                    raise
            self.resume_role(stage, role, dispatch, words, complete=self.completion_for(stage, role, record))
            return
        raise Refusal(f"resume_checkpoint {dispatch}: {json.dumps(action)[:800]}", dispatch=dispatch)

    def _act_relaunch(self, action: dict) -> None:
        request = action.get("dispatch_request") or {}
        stage, role = str(action.get("stage") or request.get("stage") or ""), str(action.get("role") or request.get("role") or "")
        scope = list(request.get("scope") or [])
        # POSITION INVARIANT: the stand and build checks come BEFORE the packet is dispatched and before
        # the no-packet fallback starts a role - a relaunch on a stand stage registers no dispatch and
        # starts no role until both pass; a refused check leaves the controller's record as it was.
        if stage in self.STAND_STAGES:          # a relaunch STARTS a role on the stand: the same check as the stage's entry
            self.stand_check(stage, str(request.get("execution_kind") or action.get("execution_kind") or ""))
            self.build_check(stage, str(request.get("execution_kind") or action.get("execution_kind") or ""),
                             cases=scope)
        if not request.get("id"):
            # An older controller state names no packet. A fresh `story_step start` is all
            # that is left, and it starts a NEW dispatch: say so, because what the closed one
            # was opened for (its binding, cause, lineage, reason) does not travel with it.
            print(f"relaunch {action.get('closed_dispatch_id') or '?'}: the controller's action "
                  "carries no dispatch_request, so a fresh dispatch is started and the lineage "
                  "(relaunch_of, case versions, repair cause, rework_of, reason) is not carried")
            if (stage, role) == ("S3", "qa-test-strategist"):
                self.stage_S3()             # G1-11: S3 decides its own window (a one-window start here would skip the labelling)
                return
            self.run_role(stage, role, scope=scope, extra=self.role_lines(stage, role),
                          complete=self.completion_for(stage, role, {}))
            return
        if (stage, role) == ("S3", "qa-test-strategist") and not request.get("rework_of"):
            self.s3_check_packet(request)
        # The controller's own packet is the dispatch: it names the closed one (`relaunch_of`)
        # and carries its original binding, cause, lineage and reason. `story_step start`
        # built a new request from the stage and the scope and lost all of it. A refusal of
        # the packet is the controller's word and travels as every other controller refusal
        # of this driver: no fallback to a fresh start, which would be the same work with
        # the contract thrown away.
        self.controller("dispatch", input_data=dict(request))
        # O4 (C1-7c, kind G as G3): the running record is written BEFORE the dispatch's role starts; a non-zero exit is a `Refusal` (the
        # factory's own) and the role is not started over a stage the record does not show as running. The packet above is already
        # registered, so `retry` is record-then-role (the G1/G3 pattern, F-2 of C1-7b): the retry itself registers nothing (the replay
        # of a failed retry reaches `controller("dispatch")` again, and the store returns the existing event for the same key), and
        # the registered dispatch is not left to `where` -> `wait_existing_job` without the relaunch lines on a retry. A conductor's
        # `continue` takes that road, and its never-launched branch (`_act_wait_existing_job`) starts the role WITH the same lines (F-2
        # of t-1252). The refusal carries the dispatch id (E-c8). A rework of accepted work writes no record (`rework_of`: what `start`
        # does after it registers a dispatch, a rework of an accepted stage does not - its stage is already settled), which
        # `record_running` knows with the controller's `completed`.
        def record_then_role() -> None:
            self.record_running(stage, role, request["id"], retry=record_then_role, relaunched=True,
                                rework_of=str(request.get("rework_of") or ""))
            record = (self.controller_state().get("dispatches") or {}).get(request["id"]) or {}
            # t-2277 batch 2b D (critic t-2513 F1, axis 5): the person's `rework S1` reaches the driver as this relaunch; the scout's rework
            # leaves S1 open and the reference window follows it, the same road as `rework()` (None for any other dispatch or no reference)
            window = self.s1_window_owed(stage, role) if request.get("rework_of") else None
            self.run_role(stage, role, scope=scope, extra=self.role_lines(stage, role, record),
                          complete=False if window else self.completion_for(stage, role, record),
                          rework={"id": request["id"], "scope": scope, "reason": self.relaunch_reason(request, action)})
            if window:
                self.s1_reference_window(stage, window)
        record_then_role()

    def _act_resolve_return(self, action: dict) -> None:
        # A role that stopped without acceptance. `relaunch` has a move and
        # `resume_checkpoint` has a move; this one had none, so the driver raised the
        # packet at the conductor, the conductor has no command for it either (its `did`
        # came back empty), the person was asked, and their words landed on this same
        # line again. Live TP1-13797, run 5: the S5 critic looped person -> conductor
        # -> person with the identical JSON until the loop was read from the code.
        # The person's word decides accept/checkpoint/rework, but only the ROLE can write
        # its own digest, so the move is the one `resume_checkpoint` already makes: hand
        # the words back to the role and let it close itself.
        if self.resume_with_filed_words(action.get("dispatch_id", ""), self.completion_for):
            return
        raise self.resolve_return_refusal(action)

    # --- the three actions that are about somebody else's machinery -------------------------

    def environment_job(self, action: dict) -> None:
        """A recorded stand preparation: observe it, never start a second one.

        `observe_environment_job` is the controller's FIRST branch, so an unsettled job
        outranks every other action — and the driver had no move for it at all, which on any
        project that records a stand preparation means the whole loop falls into "the driver
        has no move for X" -> conductor -> a question to a person, while the action's own
        `reason` already says what to do (run 5 never met it only because its stand was
        prepared by hand). `EnvironmentJobs.observe` is the door: it reuses a finished job,
        confirms a live one, and settles an orphan as `blocked` without relaunching it."""
        job_id = str(action.get("job_id") or "")
        self.boundary = f"{action.get('stage') or 'S5'}:environment:{job_id or 'unknown'}"
        receipt = str(action.get("receipt_ref") or "")
        jobs_dir = self.task_root / "state" / "environment-jobs"
        key = str(_read_json(self.task_root / receipt).get("idempotency_key") or "") if receipt else ""
        if not key:
            raise Refusal(
                f"observe_environment_job {job_id or '(no job_id)'}: the job record "
                f"`{receipt or 'state/environment-jobs/<job>.json'}` carries no `idempotency_key`, "
                "and without it the job cannot be observed and must not be started again. "
                "Either repair that file's identity or settle the job by hand: "
                f"`environment_preparation.py status --jobs {jobs_dir} --key <key>`.")
        for attempt in range(1, ENV_JOB_LOOKS + 1):
            code, out = self.py("environment_preparation.py", "observe", "--jobs", jobs_dir, "--key", key)
            try:
                seen = json.loads(out[out.index("{"):out.rindex("}") + 1])
            except (ValueError, TypeError):
                raise Refusal(f"environment_preparation.py observe --key {key} (exit {code}) printed "
                              f"no readable JSON:\n{out[-600:]}")
            status, job = str(seen.get("status") or "unknown"), (seen.get("job") or {})
            if seen.get("settled"):
                print(f"environment job {job_id or key}: settled as `{status}` — the story goes on")
                return
            if seen.get("uncertain_process"):
                # The one state code may not settle: the outcome is unknown and relaunching is
                # forbidden. Saying "still running" here would be the exact thing FR-41 names.
                last = (job.get("steps") or [{}])[-1] if job.get("steps") else {}
                # By hand (C1-1, P31): the person's work is an OPTION with a token; the command that settles the job leaves the
                # body for the answer block (human-questions.md rule 5) and stays there as the way out (FR-57).
                self.no_move({
                    "why": "by_hand", "kind": "environment", "stage": str(action.get("stage") or "S5"), "dispatch": "",
                    "lead": f"The stand preparation `{job_id or key}` stopped without a result and the "
                            f"process that owned it is gone, so nobody can say whether it finished.\n\n"
                            f"- last step: {str(last.get('name') or 'unknown')} "
                            f"({str(last.get('status') or 'unknown')}), phase `{job.get('phase') or 'unknown'}`\n"
                            f"- the record: qa-factory/artifacts/{self.task}/{receipt}\n"
                            f"- I did NOT start it again: a second run of the same preparation is what the "
                            f"job's identity exists to prevent.\n\n"
                            "A read-only probe of the stand settles it; only you know which probe says whether the stand is up. "
                            "Or say in your own words that the stand is not available, and S5 carries it as `env_blocked` "
                            "instead of waiting.",
                    "keep": [f"qa-factory/artifacts/{self.task}/{receipt}"],
                    "answer_note": "To settle the job with a probe: python " + str(self.scripts / "environment_preparation.py")
                                   + f" reconcile --jobs {jobs_dir} --key {key} --probe <probe.json>",
                    "text": f"{job_id or key}: uncertain_process, phase {job.get('phase') or 'unknown'}, record {receipt}"}, None)
                return                  # the conductor took a move: back to `where`, which observes the job again
            print(f"environment job {job_id or key}: `{status}`, its process is alive "
                  f"(look {attempt} of {ENV_JOB_LOOKS}) — waiting, not starting a second one", flush=True)
            time.sleep(ENV_JOB_WAIT_SECONDS)
        self.no_move({
            "why": "threshold", "kind": "environment", "stage": str(action.get("stage") or "S5"), "dispatch": "",
            "lead": f"The stand preparation `{job_id or key}` has been running for "
                    f"{ENV_JOB_LOOKS * ENV_JOB_WAIT_SECONDS // 60} minutes and its process is still alive, so "
                    "I have neither a result to use nor a dead job to settle.\n\n"
                    f"- the record: qa-factory/artifacts/{self.task}/{receipt}\n"
                    "- I did not stop it and did not start a second one.\n\n"
                    "The choice is to keep waiting, or to carry the stand as `env_blocked` and go on.",
            "keep": [f"qa-factory/artifacts/{self.task}/{receipt}"],
            "text": f"{job_id or key}: alive after {ENV_JOB_LOOKS} looks, record {receipt}"}, None)

    def orchestrator_rollover(self, action: dict) -> None:
        """The window counters belong to a model session; this driver has none.

        `handoff_ready` and `rollover_pending` exist for an LLM orchestrator whose context
        window is filling up. A code driver has no window to roll over, so the honest move is
        to take the lease and clear the counters — the takeover the record is asking for is
        the one that already happened. When the takeover is not safe yet, the action names
        what is unsettled and so does the refusal."""
        wait_for = action.get("wait_for") or {}
        blocking = [f"{kind}: {json.dumps(rows)[:200]}"
                    for kind, rows in (("running jobs", wait_for.get("running_jobs")),
                                       ("external writes with no recorded result",
                                        wait_for.get("unknown_external_writes")),
                                       ("running dispatches", wait_for.get("running_dispatches")))
                    if rows]
        if action.get("action") == "rollover_pending" or blocking:
            raise Refusal(
                "the orchestrator window is full and the takeover is blocked by work nobody has "
                "settled:\n- " + "\n- ".join(blocking or ["(the record names nothing)"]) +
                "\nThis driver has no context window, so the rollover itself costs it nothing — what "
                "has to move is the list above. A durable run job is settled with `run_suite.py "
                "--recover <KEY> --task " + self.task + "`, a proposal with `external_writes.py "
                "--record <proposal.json> --external-id <ID>`, and a dispatch through `where`.")
        state = self.controller_state()
        lease = (state.get("leases") or {}).get("orchestrator") or {}
        session = f"driver:{self.task}:{state.get('revision', 0)}"
        print(f"orchestrator rollover: {', '.join(action.get('reasons') or ['window'])} — the driver "
              f"has no context window; taking the lease from `{lease.get('owner_session_id') or 'nobody'}`")
        self.controller("handoff", input_data={
            "owner_session_id": lease.get("owner_session_id") or session,
            "host_capability": "manual_continuation",
            "reason": "the code driver continues this story; it has no context window to roll over",
            "lease": {"owner_session_id": session,
                      "generation": int(lease.get("generation") or 0) + 1},
            "expected_revision": state.get("revision", 0),
            "idempotency_key": f"handoff:driver:{state.get('revision', 0)}"})

    def run(self) -> int:
        self.run_started = _now()       # TR4-11: when THIS process began; the stop record names it (`since`)
        self.progress_line()            # the log header: where the story stands as this process starts
        if not self.state.get("asked"):
            self.state.pop("stuck_pending", None)       # B-20 F6: a mark left by a process that died in the conductor belongs to no open question
        # TR4-11 (F-3): the OUTER try. Ctrl-C reaches here from the loop AND from the run-level handlers of the inner try (a `Refusal` handed
        # to `funnel` can be a paid conductor call): a sibling `except` of the inner try would not see the second kind.
        try:
            return self._run_guarded()
        except KeyboardInterrupt:
            self.person_stop_record()
            raise

    def person_stop_record(self) -> None:
        """TR4-11: the person stopped the run (Ctrl-C, either road): ONE row of `driver-runs.jsonl`, through `journal_run`, so that the
        collector tells the calls THIS process cut off from a driver that died on its own (`collect_stall` K3).

        `{"kind": "stopped_by_person", "who": "person", "at", "since": <run_started>, "cut": [<call id>...]}`; a call id is
        `<dispatch_id or call>@<started_at>` of a `launched` row this process wrote and has seen no end row for (`journal_run` keeps
        the set), so K3 clears exactly those rows and no row of any other process. No `dispatch`, `session_id`, cost, `exit_code`,
        `is_error` or `infra`: every reader that binds sessions, prices or outcomes passes the row by, as it passes a `launched` row.

        Edges: no story folder yet -> nothing is written (Ctrl-C never creates it, and no call was launched); a failed write -> one
        `note:` line; a second Ctrl-C while writing -> the row may be absent (K3 then reads a dead driver: the safe side), the first
        interrupt still goes on. Nothing is printed otherwise; the caller re-raises."""
        try:
            if not self.state_dir.is_dir():
                return
            cut = sorted(f"{key}@{at}" for key, at in list(once_on(self, "_open_calls", set)))
            self.journal_run({"kind": "stopped_by_person", "who": "person", "at": _now(), "since": self.run_started, "cut": cut})
        except OSError as exc:
            print(f"note: the stop by the person could not be journalled ({type(exc).__name__}); it goes on", flush=True)
        except KeyboardInterrupt:
            pass

    def _run_guarded(self) -> int:
        try:
            repaired = self.reconcile_question()
            if repaired:
                print(f"{self.task}: {repaired}")
            if self.flags.answer:
                self.take_answer(Path(self.flags.answer))
            # C1-7a (B-1): the rows the journal refused are written again BEFORE the first step that could build a brief (the changed-ticket
            # rework below dispatches a role). POSITION INVARIANT: after the answer is taken (its own rows are owed by then), before every
            # pre-loop step; the loop's first step is the same call (S2: no brief is built while a row of the person's words is owed).
            self.owed_rows_step()
            self.adopt_legacy_snapshot()
            # B-014: after the answer is taken (a person's word for the switch is recorded there) and
            # before anything is dispatched; a story with no pipeline yet has no mode to switch.
            self.check_run_mode()
            self.report_gap_class_problem()
            self.skip_sources_late()
            # t-2181 PC-7 POSITION (S11): the launch word of a RESUMED story is kept here - after `skip_sources_late`, BEFORE the freshness
            # branch below. INVARIANT: a source word given on this command line survives a question asked in this same process (the
            # changed-ticket question: the answer run carries `--answer`, not `--branch`, and still arrives); a stopped story given no
            # word ends here with its line (`Stop`, exit 0), so no freshness look and no dispatch happen for it.
            resumed = (self.task_root / "pipeline.json").is_file()
            if resumed:
                self.arrival_keep()
            if not resumed:
                print(f"{self.task}: fresh story — S0 by code")
                import story_step
                story_step.keep_config_copy(self.project, self.task_root, self.task)
                self.guarded(self.s0, {"action": "prepare_stage", "stage": "S0"})
            elif self.answer_kind == "ticket_changed":
                # B-364 R4/R12: the run that carries the answer to the changed-ticket question does not look at the
                # ticket again (the person has just chosen); what they chose starts here, as it does at the top of
                # every loop turn below.
                # B4 POSITION INVARIANT (S11): the arrival is recorded BEFORE this rework opens. The answer just taken wrote
                # `ticket_rework` (S2/S3 owed), and `ticket_rework_step` runs the S2 tester on the new text; run first, it would put a
                # role on the story while `pipeline.sides` still says absent and `implementation_source` is not the diff. The person's
                # ticket answer is already taken, so "no role before the ticket answer" still holds; the call after `accept_no_trace`
                # below is then a no-op (the pending word is spent).
                self.guarded(self.arrival_record, {"action": "arrival"})
                self.guarded(self.ticket_rework_step, {"action": "ticket_rework"})
            else:
                # B-364 R4 (D-0027): a resumed story is the one most likely to have been overtaken by an edit in the
                # tracker, so the ticket is looked at ONCE here - after the person's answer was recorded (FR-8: their
                # words come before any new question) and before the next step - and never in a process that just ran
                # S0 (the S0 branch above; K11: an S0 resume does not ask the tracker and leaves the snapshot's hash
                # alone). Whether the baseline is old enough is the adapter's rule, not a decision made here.
                self.guarded(self.ticket_freshness_entry, {"action": "ticket_freshness"})
            # `--no-trace` on a story that has no such record yet (t-017 D3): accepted from here on. A
            # story S0 has just written with the flag already carries it, and this is a no-op.
            self.boundary = "no_trace"
            self.guarded(self.accept_no_trace, {"action": "accept_no_trace"})
            # t-2181 PC-7 POSITION (S11): the arrival is recorded AFTER the freshness branch and `accept_no_trace`, BEFORE the loop.
            # INVARIANT: a changed ticket is asked first (one road: `ticket_changed` and `ticket_rework_step`); no role is dispatched on the
            # new code before the person's answer about a changed ticket is taken; the arrival is on the record before any rework opens,
            # so a crash in between replays from the record (the kept word stays pending until `arrive` is written).
            self.guarded(self.arrival_record, {"action": "arrival"})
            self.guarded(self.sides_reread, {"action": "sides_reread"})   # PC-1b E-U1: a relaunch re-reads the sides S0 could not read
            repeats, previous = 0, None
            for _ in range(self.max_boundaries):
                # B-364 R12: a ticket rework the person chose is owed BEFORE anything `where` could say - the loop
                # would otherwise go on to gate B on stages built from the old text. The step says so when it moved
                # (a stage ran, or the gate was reopened): the turn is spent and `where` is asked on the next one.
                # A refusal the guard handled leaves `moved` empty: the same, the step reads the state again.
                self.owed_rows_step()           # C1-7a (B-1): the first step of every turn - before anything that can dispatch or resume a role
                moved: list = []
                self.guarded(lambda: moved.append(self.ticket_rework_step()), {"action": "ticket_rework"})
                if not moved or moved[0]:
                    continue
                # t-2181 PC-7 (§3.2 steps 2, 3, 5): the rework the ARRIVAL owes comes right after the ticket's (a changed ticket stays
                # first, E-A2) and before the seam's, by the same rule
                arrived: list = []
                self.guarded(lambda: arrived.append(self.arrival_rework_step()), {"action": "arrival_rework"})
                if not arrived or arrived[0]:
                    continue
                # t-722 C2-6: the rework the person chose at the seam is owed right after the ticket's and before `where`, by the same rule
                seamed: list = []
                self.guarded(lambda: seamed.append(self.seam_rework_step()), {"action": "seam_rework"})
                if not seamed or seamed[0]:
                    continue
                # HF2-7: the rework the person's recorded answers owe (the plan rows or cases that still follow the other reading) is
                # opened by code right after the person's chosen rework, by the same rule (P22), before `where` and before a stage is closed
                answered: list = []
                self.guarded(lambda: answered.append(self.answer_rework_step()), {"action": "answer_rework"})
                if not answered or answered[0]:
                    continue
                # C2-8: the record of a stage the code closed (receipt written, `stage_done` refused) is owed after any rework the person
                # chose (it may open the stage again: then the record is dropped, I4) and before `where` reads on from the receipt
                written: list = []
                self.guarded(lambda: written.append(self.code_close_step()), {"action": "code_close"})
                if not written or written[0]:
                    continue
                # B-20: the person's `stage acceptance` word for a stage that awaits its consumer is recorded from any position, after the
                # reworks above (a rework may change the author the word binds to) and before `where` (the router sees the record this turn)
                worded: list = []
                self.guarded(lambda: worded.append(self.consumer_word_step()), {"action": "consumer_word"})
                if not worded or worded[0]:
                    continue
                try:
                    action = self.where()
                except Refusal as refusal:
                    self.boundary = "where"
                    self.handle_refusal(refusal)
                    continue
                signature = json.dumps(action, sort_keys=True)
                repeats = repeats + 1 if signature == previous else 0
                previous = signature
                if repeats >= STUCK_REPEATS:
                    # `where` said the same `STUCK_REPEATS` times: the seam (one call under the cap), then the loop looks again
                    # `keep` (Q2): the place the stuck text names goes above the conductor's prose when that prose drops it. The cap
                    # site below (`call: False`) has none: `keep` is read only on the conductor's road (G15).
                    # B-20 N5 (AR-22, AR-17, FR-7): the lead carries the facts code can read about the earlier open stages (`stuck_facts`)
                    # and, when the person already answered THIS step, says so instead of putting the same question again. The record
                    # `stuck_asked[signature]` is written by `take_answer` from `stuck_pending`, which lives only while the question is open.
                    stuck_stage = str(action.get("stage") or "")
                    told = (self.state.get("stuck_asked") or {}).get(signature)
                    told = told if isinstance(told, dict) and told.get("answer") else None
                    facts, raw_facts = self.stuck_facts_for(stuck_stage)    # the person's lines / the factory's lines (F3: ids stay out of the lead)
                    keep = [self.stage_place(stuck_stage)] + ([str(told["answer"])] if told else [])
                    self.state["stuck_pending"] = {"signature": signature, "stage": stuck_stage, "kind": "refusal"}
                    try:
                        self.no_move({"why": "threshold", "kind": "refusal", "stage": stuck_stage, "dispatch": "",
                                      "lead": self.stuck_text(stuck_stage, waits_on_person=(
                                          action.get("stage") == "S7" and "open_work" in self.s7_decided()), facts=facts, answered=told),
                                      "text": signature + ("\n\nWhat the factory can read, with its own ids and words:\n"
                                                           + "\n".join(f"- {line}" for line in raw_facts) if raw_facts else ""),
                                      "keep": keep})
                    except Person:
                        raise               # the question is open: `stuck_pending` waits for its answer (`take_answer`)
                    except BaseException:
                        self.state.pop("stuck_pending", None)
                        raise
                    self.state.pop("stuck_pending", None)       # the conductor moved: no question is open
                    repeats, previous = 0, None
                    continue
                if action.get("action") in ("stop", "complete"):
                    import story_step
                    story_step.give_back_config(self.project, self.task_root, self.task)      # HF5-6: the story ends here, with or without `--until`
                if self.until_reached(action):
                    print(f"{self.task}: --until {self.until} reached at {json.dumps(action)}")
                    self.deferred_note()        # RN1-24 E9: a deferred question is never left unsaid
                    self.progress_line()        # the end of this run
                    return EXIT_DONE
                if action.get("action") == "stop":
                    print(f"{self.task}: {action.get('reason')}")
                    self.progress_line()
                    return EXIT_DONE
                if action.get("action") == "complete":
                    self.py_trace("factory_dashboard.py", why="the story is complete; no step of it reads the dashboard, and a failure here is "
                                                              "journalled in driver-runs.jsonl")
                    print(f"{self.task} — the story is complete. Documents: qa-factory/artifacts/{self.task}/test-report.md · retro.md")
                    self.progress_line()
                    return EXIT_DONE
                try:
                    self.boundary_step(action)
                except Person as person:
                    # RN1-24: a question about SOME manual cases does not hold the work that does not depend on them; anything else is asked now
                    if not self.deferrable(person):
                        raise
                    self.defer_question(person)
                    repeats, previous = 0, None         # the step comes again with fewer cases: not "the same action four times"
            print(f"{self.task}: paused after {self.max_boundaries} boundaries (--max-boundaries); run again to go on")
            self.deferred_note()                # RN1-24 E9
            self.progress_line()
            return EXIT_DONE
        except Person as person:
            return self.ask(person)
        except Refusal as refusal:
            # Raised OUTSIDE `guarded` (a `py(check=True)` inside `take_answer`): a traceback is a stalled run (P22), so the
            # seam asks. `call=False` makes `no_move` ALWAYS raise `Person`, and a `Person` raised inside an `except` is not
            # caught by the sibling clause above: it is handed to `ask()` here (D1/E1). No `asked` is passed (F1).
            # The answer being taken (if the refusal came out of `take_answer`) is on the record before the question comes back:
            # its words file named in `asked`, its row in driver-answers.jsonl - the person's word is not lost to the refusal.
            # An answer whose words file is set is NEW words (D-0041): the funnel lets them reach the conductor (`funnel`).
            file = self.settle_unread_answer()
            return self.funnel({"why": "refusal", "kind": "conductor", "text": refusal.text, "words_file": file,
                                "lines": self.refusal_lines(refusal),
                                "words": str((self._answer or {}).get("text") or "") if file else "",
                                "lead": self.question_from_refusal(refusal, self.boundary.split(":")[0])})
        except Stop as stop:
            print(f"story_run: stopped — {stop.reason}")
            if stop.code == EXIT_GAVE_UP and not isinstance(stop, InfraStop):
                # The conductor's `stop` of a gate / the S1 review (exit 4): the priced question with no paid call and no gate
                # branch (F1/F2). `ask` prints the progress line itself (t-323 B1).
                return self.funnel({"why": "stop", "kind": "conductor", "text": stop.reason, "lead": stop.reason,
                                    "dispatch": self.boundary_dispatch()})   # the free answer is filed for this dispatch
            self.progress_line()
            return stop.code

    # --- a stage closed by code with no role (conductor/2 C2-8, t-745; class K3) --------------------------------------------------

    def running_tail(self) -> "list | None":
        """The stages of `pipeline.json` other than S9 whose status is exactly `running` (the predicate `stage_done` uses for its `still
        running` door); `None` when `pipeline.json` holds no readable stage table (an unknown is not an empty tail, FR-59). The one
        caller (`code_close`) hands the value to `code_close_block`, which reads `None` as "no block established"."""
        stages = self.pipeline().get("stages")
        if not isinstance(stages, dict):
            return None
        return [s for s, held in stages.items() if s != "S9" and isinstance(held, dict) and held.get("status") == "running"]

    def code_close_block(self, site: str, tail, passed=()) -> str:
        """The waivable block of an S9 record, read from the STATE (never from the refusal's words): `still running` when a stage is
        left marked so; `no accepted controller stage` at the numbers-only retro of a controller-managed story whose S9 the controller
        has not completed; else `""`. An unreadable state is `""` too: no `go on` is offered over what was not established. A block the
        person's word already PASSED (`passed`) is not the block of the next refusal: `stage_done` reads the pass and goes on to its next
        door, so the second block of one record is shown as its own question (spec 3.6(3); the pass stays in the offer rule)."""
        if site not in ("s9.skip", "s9.numbers") or tail is None:
            return ""
        if tail and NM.BLOCK_RUNNING not in passed:
            return NM.BLOCK_RUNNING
        if site == "s9.numbers":
            held = self.controller_state()
            stages = held.get("stages") if isinstance(held, dict) else None
            if isinstance(held.get("dispatches"), dict) and isinstance(stages, dict) \
                    and (stages.get("S9") or {}).get("status") != "completed":
                return NM.BLOCK_NO_STAGE
        return ""

    def code_close(self, refusal: Refusal) -> str:
        """The seam for a refusal at a place where the CODE closes a stage (`refusal.close`): the question with what lets the story go on,
        no paid call (I2). On S9 the stage left `running` is settled by code first, once (`controller recover`, I8). Returns `retry`
        after that move; otherwise raises the `Person` through `no_move(call=False)`."""
        mark = refusal.close
        stage, site, step = mark["stage"], mark["site"], mark["step"]
        rec = self.state.setdefault("code_close", {}).setdefault(stage, {})
        for name, empty in (("passed", []), ("refused", []), ("filed", []), ("recovered", False), ("recover_failed", ""), ("pending", None)):
            rec.setdefault(name, empty)
        rec.update(site=site, step=step, key=("code_close.factory_file" if step in ("evidence", "entry") else
                                              "code_close.closed_story" if stage == "S9" else "code_close.stage"))
        tail = self.running_tail() if stage == "S9" else []
        if stage == "S9" and tail and not rec["recovered"]:
            rec["recovered"] = True
            self.save_state()
            try:
                self.controller("recover")
                print("S9: a step still marked as in progress was settled by the factory; the retro is recorded again")
                return "retry"
            except Refusal as again:
                rec["recover_failed"] = again.text[:2000]
        rec["block"] = self.code_close_block(site, tail, rec["passed"])
        if step == "record" and stage in ("S6", "S7"):
            rec["pending"] = rec["pending"] if (rec["pending"] or {}).get("receipt") == mark.get("receipt") else {
                "site": site, "args": list(mark.get("args") or []), "tail": list(mark.get("tail") or []),
                "receipt": str(mark.get("receipt") or ""), "idle": 0}
        # B-20 (t-1988 N3, AR-25/AR-9/AR-17): the close is refused because an EARLIER stage is not closed - not the factory's defect and no
        # word of the person's to refuse. POSITION: after the S9 `recover` above (unchanged) and BEFORE `file_defect`; INVARIANT: the
        # driver never closes a stage over an open earlier stage, and never says "no word of yours passes" when the earlier stage accepts
        # a word. The refusal is the controller's own fixed message; WHICH stage is behind comes ONLY from `code_close_facts` (the one
        # reading), never from the words. Another conflict (running work, already completed) and an unreadable state keep today's road.
        ctl = self.controller_state()
        if (rec["key"] != "code_close.factory_file" and "required prior logical stage incomplete" in refusal.text
                and isinstance(ctl, dict) and isinstance(ctl.get("stages"), dict) and isinstance(ctl.get("dispatches"), dict)):
            import acceptance
            from controller import code_close_facts
            facts = code_close_facts(ctl, stage)
            # B2: "is something still running" is the CONTROLLER's verdict (it reads the liveness of each row), carried by its sentence; the
            # default facts here read every `running` row as holding, so a dead row would put the close on the defect road again
            if facts["behind"] and "checkpoint active work" not in refusal.text and not facts["completed"]:
                behind = facts["behind"][0]
                waits = acceptance.awaits_acceptance(ctl, behind, self.pipeline())
                at = f"{behind}@{ctl.get('revision')}"
                held = rec.get("behind_seen") if isinstance(rec.get("behind_seen"), dict) else {}
                nth = (int(held.get("n") or 0) if held.get("at") == at else 0) + 1       # this refusal, counted per (behind, revision)
                rec.update(key="code_close.behind", behind=behind, awaits=bool(waits), block="", behind_seen={"at": at, "n": nth})
                if not waits and nth < CODE_CLOSE_IDLE_CAP:
                    # (a) the earlier stage waits for nobody: the driver's own move - go back to it (`where` routes there). The bound is
                    # the seam's `CODE_CLOSE_IDLE_CAP` (F3): refusal 1 of a revision is a silent retry, refusal 2 at the SAME revision
                    # (nothing moved) is asked below.
                    self.save_state()
                    print(f"{stage}: closed after {behind}, which is not closed yet; the factory goes back to it")
                    return "retry"
                return self.code_close_ask(stage, rec, refusal.text, lines=self.refusal_lines(refusal))
        found = f"{site}:{finding_key(refusal.text.splitlines())}"
        if found not in rec["filed"]:
            rec["filed"].append(found)
            self.file_defect(stage, f"owner: factory — {site}: the factory's own close of {stage} was refused at its {step}")
        details = refusal.text + (("\n\n## `controller.py --operation recover` was run for it and refused too\n" + rec["recover_failed"])
                                  if rec["recover_failed"] else "")
        return self.code_close_ask(stage, rec, details, lines=self.refusal_lines(refusal))

    def code_close_ask(self, stage: str, rec: dict, details: str, *, lines=None, cap: bool = False) -> str:
        """Fix the options of the question from the facts (`NM.code_close_offer`), keep them and the lead in the state (the answer reads them),
        and raise the question through the seam."""
        tokens, absent = NM.code_close_offer(rec["key"], {"block": rec["block"], "passed": rec["passed"], "refused": rec["refused"],
                                                           "idle_cap": cap, "awaits": bool(rec.get("awaits"))})
        rec.update(offer=tokens, lead=self.code_close_lead(stage, rec, absent, cap), details=details, at=_now())
        self.save_state()
        return self.no_move({"why": "refusal", "kind": "code_close", "call": False, "stage": stage, "dispatch": "", "lead": rec["lead"],
                             "text": details, "block": rec["block"], **({"lines": lines} if lines else {}),
                             "site_fallback": lambda said: self.code_close_person(stage, said)})

    def code_close_lead(self, stage: str, rec: dict, absent: list, cap: bool) -> str:
        """The words above the options (human-questions.md items 1-6): what is decided, why the factory cannot, what the person can do."""
        what = (self.consumer_close_words(stage)[0] if rec["site"] in ("s6.accepted", "s7.accepted")       # N4: who accepted, from the record
                else CODE_CLOSE_SITES[rec["site"]][1])
        place = self.stage_place(stage)
        said = "".join(line + "\n" for line in absent)
        if rec["key"] == "code_close.behind":
            behind = str(rec.get("behind") or "")
            route = self.CONSUMER_ROUTES.get(behind) or {}
            bplace = self.stage_place(behind)
            head = (f"The story is at {place}. No role works at this step: the factory closes it by itself ({what}), but {bplace} is not "
                    "closed yet, and the factory closes the stages in order. ")
            if rec.get("awaits"):
                return (head + f"{bplace[:1].upper() + bplace[1:]} is finished on the factory's side and waits for one thing: the "
                        f"{route.get('who', 'next role')} has not "
                        f"yet accepted {route.get('what', 'its handoff')}. A word of yours can give that acceptance in the "
                        f"{route.get('who', 'next role')}'s place. Which of these should happen?")
            return (head + f"The factory went back to {bplace} and nothing moved.\n{said}The factory cannot finish this step by itself. "
                    "Which of these should happen?")
        if rec["key"] == "code_close.factory_file":
            cause = ("its own description of which failed tests to repair cannot be read, and going past it would leave failed tests "
                     "unrepaired" if rec["step"] == "entry" else f"the file that shows that {what} is not on disk")
            return (f"The story is at {place}. No role works at this step, and the factory cannot do it: {cause}. This is the factory's "
                    f"own defect and it is filed.\n{said}The factory cannot go past it by itself. Which of these should happen?")
        owner = ("The factory tried to record it twice and something of its own kept the record from finishing; it is filed as a defect "
                 "of ours." if cap else
                 "Another step of this story is still marked as in progress" + (", and the factory could not settle that by itself"
                                                                                 if rec["recover_failed"] else "")
                 + "; a finished story must not leave a step marked so." if rec["block"] == NM.BLOCK_RUNNING else
                 "The factory can record the retro as finished only after the retro analyst's own work, or on your word."
                 if rec["block"] == NM.BLOCK_NO_STAGE else
                 "The reason is the factory's own; it is filed as a defect of ours, and the factory's own words are in the file named below.")
        return (f"The story is at {place}. No role works at this step: the factory closes it by itself ({what}), and its own record of "
                f"that close was refused. {owner}\n{said}The factory cannot finish this step by itself. Which of these should happen?")

    def code_close_person(self, stage: str, said: str = "") -> Person:
        """The question from its facts (the state keeps them across processes): `said` (an unread answer's lead) above the lead, then the
        priced answers of the key. One literal `closed_question` per key (the census of question ids reads them)."""
        rec = (self.state.get("code_close") or {}).get(stage) or {}
        lead = rec["lead"] if not said.strip() or said.strip() == rec["lead"].strip() else said.strip() + "\n\n" + rec["lead"]
        factory_file = rec["key"] == "code_close.factory_file"
        says = {"retry": (("once the factory's own file is repaired by whoever maintains the factory (not within this story), the factory "
                           "tries this step again", {"what": "the factory's own file repaired by whoever maintains the factory"})
                          if factory_file else
                          ("you settle what is in the way, then the factory records the retro again", {}) if stage == "S9" else
                          ("you deal with what is in the way, then the factory records the close again", {})),
                "go on": ("the retro is recorded as closed as it is, on your word; your words are kept as the reason", {}),
                "full retro": ("the retro analyst does the retro of this story after all, and its finish closes this step",
                               {"role": "the retro analyst"})}
        if rec["key"] == "code_close.behind":
            route = self.CONSUMER_ROUTES.get(str(rec.get("behind") or "")) or {}
            who = route.get("who", "next role")
            says = {"retry": ((f"you deal with what is in the way, or the {who} accepts {route.get('what', 'its handoff')}, then the factory "
                               "records the close again" if rec.get("awaits") else
                               "you deal with what is in the way, then the factory records the close again"), {}),
                    "go on": (f"your word accepts {route.get('what', 'its handoff')} in the {who}'s place, your words are kept as the reason, "
                              "and the factory records the close again", {})}
        options = [dict(self.STOP_OPTION) if t == "stop" else {"answer": t, "token": t, "says": says[t][0], "slots": says[t][1]}
                   for t in rec["offer"]]
        if rec["key"] == "code_close.behind":
            text = self.closed_question("code_close.behind", lead, options)
        elif rec["key"] == "code_close.closed_story":
            text = self.closed_question("code_close.closed_story", lead, options)
        elif factory_file:
            text = self.closed_question("code_close.factory_file", lead, options)
        else:
            text = self.closed_question("code_close.stage", lead, options)
        return Person("code_close", text, stage, "", details=rec.get("details", ""))

    def _answer_code_close(self, words: str, qtext: str, stage: str, dispatch: str, *, words_file: str = "") -> bool:
        """The answer to a `code_close` question - the one executor of its tokens, whoever asked it (FR-9; FR-12: only a whole token).
        `retry` lets the step run again; `go on` records the pass through the writer of passes and files the finding (FR-4); `full retro`
        sets the retro to its role; `stop` holds the question. Any other word goes back to the question (`doors`, `again`). True = a token."""
        held = self.state.get("code_close") or {}
        rec = held.get(stage) or {}
        token = self.s0_normalize(words)
        if not rec:                    # the facts are lost (a state from before this record): the conductor reads the words (FR-59)
            self.unread("code_close", stage, "", self.generic_prompt("code_close", stage, qtext), words=words)
            return False
        if ((self.pipeline().get("stages") or {}).get(stage) or {}).get("status") in ("done", "skipped"):
            self.after_close(stage, words)      # no executor runs on a stage already closed
            held.pop(stage, None)
            self.save_state()
            return token in rec.get("offer", ())
        if token not in rec.get("offer", ()):
            self.unread("code_close", stage, "", qtext, words=words, block=rec.get("block", ""), doors=tuple(rec.get("offer") or ("stop",)),
                        lead=self.unread_lead(words), again=lambda said: self.code_close_person(stage, said))
            return False
        file = words_file or self.answer_file()
        self.answer_row(f"{stage} code close ({token}): ", words.strip(), what="your answer about the closed stage")
        if token == "stop":
            # remains: `stop` holds the question that was asked (the person's own word); it is no state without a move
            raise self.held_question(self.stop_held("If you want the factory to go on after all, answer one of the other answers."))
        if token == "retry":
            rec["recovered"] = False
            if rec.get("pending"):
                rec["pending"]["idle"] = 0
            print(f"{stage}: nothing is passed; the step runs again")
        elif token == "go on" and rec.get("key") == "code_close.behind":
            # B-20 (N3): the person's word accepts the EARLIER stage in its consumer's place - recorded by the one path every such pass takes
            # (`consumer_person_pass`: the driver accept `by: person` and its finding) - and then the close runs again, as after `retry`.
            import acceptance
            behind = str(rec.get("behind") or "")
            author = acceptance.awaits_acceptance(self.controller_state(), behind, self.pipeline())
            lead = "Your word could not be recorded as the acceptance, so nothing was passed."
            try:
                passed = self.consumer_person_pass(behind, author, answer=words) if author else True      # nothing waits any more: just try again
            except Refusal as refusal:       # a state with no move of its own: the seam asks the same question again, with the facts (AR-17)
                self.no_move({"why": "refusal", "kind": "code_close", "call": False, "stage": stage, "dispatch": "", "lead": lead,
                              "text": refusal.text, "block": rec.get("block", ""),
                              "site_fallback": lambda said: self.code_close_person(stage, said)})
            if not passed:
                self.no_move({"why": "refusal", "kind": "code_close", "call": False, "stage": stage, "dispatch": "", "lead": lead,
                              "text": lead, "block": rec.get("block", ""),
                              "site_fallback": lambda said: self.code_close_person(stage, said)})
            rec["recovered"] = False
            rec.pop("behind_seen", None)       # the record stands now (the pass is a record, the controller revision may not move): the next refusal is a fresh count
            if rec.get("pending"):
                rec["pending"]["idle"] = 0
            print(f"{stage}: going on on the person's word for {behind}; the step runs again")
        elif token == "go on":
            block = rec["block"]
            try:
                self.pass_block(stage, block, file, "Your word could not be recorded as the pass, so nothing was passed.")
            except Person:
                rec["refused"].append(block)
                self.save_state()
                raise
            rec["passed"].append(block)
            quoted = self.s0_quote((self.task_root / file).read_text(encoding="utf-8", errors="replace") if (self.task_root / file).is_file() else words)
            self.owe_row("project_decisions.py", "--root", str(self.project), "add-finding",
                         "--essence", f"{stage} {block} passed by the person's word: {quoted}", "--scope", "local-calibration",
                         "--witness", f"{stage} code close", "--idempotency-key", f"code-close-pass:{self.task}:{stage}:{block}",
                         what="the finding about the closed stage you passed", stage=stage)
            print(f"{stage}: going on on the person's word; recorded")
        else:                                           # `full retro`
            code, out = self.py("stage_done.py", "--task", self.task, "--set", "retro_mode=full")
            if code:
                # remains: the person's choice could not be written; the question comes back with the writer's own words (FR-1)
                raise self.held_question("Your choice could not be recorded, so nothing was changed.", out)
            held.pop(stage, None)
            print(f"{stage}: the retro analyst does the retro of this story")
        self.save_state()
        return True

    def code_close_step(self) -> bool:
        """The deferred record of a stage the code closed (S6/S7), one step of the loop (C2-8 M2/M4): the receipt stands in the controller and
        the record was refused. True when it wrote (the turn is spent). INVARIANT (I4): written only while the receipt this record was
        deferred for still stands in the controller - a stage opened again is never closed behind the person's back; an unreadable state
        writes nothing (FR-59). At most `CODE_CLOSE_IDLE_CAP` idle turns, then the person is asked (`retry` / `stop`)."""
        held = self.state.get("code_close") or {}
        stage = next((s for s, r in held.items() if isinstance(r, dict) and r.get("pending")), "")
        if not stage:
            return False
        rec = held[stage]
        pending = rec["pending"]
        self.boundary = stage                      # a known refusal that asks (`story_budget`) asks at THIS stage, not at `no_trace`
        stages = self.pipeline().get("stages")
        if isinstance(stages, dict) and (stages.get(stage) or {}).get("status") == "done":
            rec["pending"] = None
            self.save_state()
            print(f"{stage}: the record is on file already; the deferred record is dropped")
            return False
        ctl = self.controller_state()
        mine = (ctl.get("stages") or {}).get(stage) if isinstance(ctl, dict) else None
        if not isinstance(stages, dict) or not isinstance(mine, dict):
            pending["idle"] += 1
            self.save_state()
            return False
        if mine.get("status") != "completed" or not pending["receipt"] or mine.get("receipt_id") != pending["receipt"]:
            rec["pending"] = None
            self.save_state()
            print(f"{stage}: the receipt this record waited for no longer stands; the deferred record is dropped")
            return False
        if pending["idle"] >= CODE_CLOSE_IDLE_CAP:
            self.code_close_ask(stage, rec, rec.get("details", ""), cap=True)
        if self.dry:
            print(f"dry run: the deferred record of {stage} is not written")
            return True
        pending["idle"] += 1
        self.save_state()
        self.record_close(pending["site"], stage, *pending["args"], tail=pending["tail"], receipt=pending["receipt"])
        held.pop(stage, None)
        self.save_state()
        return True

    @staticmethod
    def seam_tokens(asked: dict) -> dict:
        """`{token: move}` of the options a seam question offered (`asked.options`): THE reading of what a token of that question is,
        for `take_seam_answer` and for the test `take_answer` makes of an answer at a gate (C2-7 §5.3)."""
        return {str(o.get("token")): str(o.get("move")) for o in asked.get("options") or [] if isinstance(o, dict)}

    def take_seam_answer(self, words: str, asked: dict, qtext: str, stage: str, dispatch: str) -> bool:
        """The answer to a question the seam raised (`asked.offered`): True when it was one of the offered tokens (the words are
        then NOT filed for a role), False when it was anything else (the seam again, `unread_answer`, the words whole).

        A token is read against THIS question's `options` only, and it dispatches on its move (`options[token].move`), never
        on the token text: `retry` -> look again, `stop` -> held (the question comes back changed, exit 3), `go on` with a
        block code knows -> `waiver.py` by code, any other offered token -> the seam (`why=chosen`) with the original words'
        file. A stage that is already done is never reopened by a token (edge 8): the words are recorded and the loop goes on.

        At a GATE (C1-4b, H2) the stage in front of the gate (S4 / S8) is always done when the gate is asked, so the done-stage
        short-circuit does not apply to the gate kinds: `done and kind not in GATE_KINDS` short-circuits as before; a non-gate kind
        whose stage is done is never reopened by a token. At a gate `approve` (move `approve_gate`) is recorded by code from the
        words file of the original answer, `retry` shows the gate again, `rework` goes to the conductor with that file."""
        kind, token = asked.get("kind", ""), self.s0_normalize(words)
        by_token = self.seam_tokens(asked)
        if kind == "code_close":
            # C2-8: every answer to a question of this kind - the site's or the conductor's options - has the ONE executor, BEFORE the
            # general "stage done" short-circuit (it sees `done` only; the executor knows `skipped` too) and before the general unread road
            # (no doors) and the `else` below (a conductor call for `full retro`, which no conductor executes).
            return self._answer_code_close(words, qtext, stage, dispatch, words_file=str(asked.get("words_file") or ""))
        # C1-7a: the question about the journal's rows is about the story's journal, not about a stage: its `go on` is executed whether or
        # not the stage it names is done (POSITION INVARIANT: before the "stage done" short-circuit, which would write a row and pass
        # nothing - the question would be asked for ever).
        done = bool(stage) and (self.pipeline().get("stages") or {}).get(stage, {}).get("status") == "done" \
            and str(asked.get("block") or "") != JOURNAL_ROWS_BLOCK
        if done and kind not in GATE_KINDS:
            self.after_close(stage, words)
            return token in by_token
        if kind == "exit_limit":
            # t-764 A7 (F5): every word of this kind - a token of the conductor's options (`go on`, `stop` too) or not - has the ONE
            # reader, BEFORE the `by_token` test (t-781 M1): its tokens are the SITE's (`round` / `fresh` / `go on` / `stop`), `round` /
            # `fresh` carry the person's ORIGINAL words (`asked.words_file`), never the file that holds only the token, and words that
            # are none of them go back to the SITE's question (`doors`, `again`) - never to the generic call with every move open, whose
            # `restart` / `retry` this kind cannot execute (FR-9), nor to a floor that offers a `go on` the site withdrew (A1).
            return self._answer_exit_limit(words, qtext, stage, dispatch, words_file=str(asked.get("words_file") or ""))
        if token not in by_token:
            self.unread(kind, stage, dispatch, self.generic_prompt(kind, stage, qtext), words=words, block=str(asked.get("block") or ""))
            return False
        move = by_token[token]
        self.answer_file()          # the token's own words file: the audit trail row of driver-answers.jsonl names it (E6)
        self.answer_row(f"{stage} ({token}): ", words.strip(), what="your answer to the question")
        if move == "approve_gate" and kind in GATE_KINDS:
            self.approve_by_option(kind, stage, asked)
        elif move == "person_does":
            print(f"{stage}: nothing is passed; the step runs again" if kind not in GATE_KINDS
                  else f"gate {kind[-1]}: nothing is recorded; the gate is shown again")
        elif move == "stop_here":
            others = " or ".join(f"`{offered}`" for offered in asked.get("offered") or () if offered != token)
            raise self.held_question(self.stop_held(f"If you want the factory to go on after all, answer {others}." if others else ""))
        else:
            self.seam_chosen(move, token, asked, qtext, stage, dispatch)
        return True

    def seam_chosen(self, move: str, token: str, asked: dict, qtext: str, stage: str, dispatch: str) -> None:
        """Every chosen token whose move is not `approve` / `retry` / `stop` (t-722 §4.2-4.6): the ORIGINAL words (`original_words`) go
        to the executor, never the file that holds only the token (FR-8). By code: `go on` with a block (`waiver.py`), `restart`
        (`waiver.run_release`), `rework` whose option carries "args" (the record `seam_rework`, run by `seam_rework_step`). Every other
        move goes to the conductor WITH the words and what the option says. Words named but not on file: held for every one of them."""
        given = self.original_words(asked)
        if given is None:
            # remains: the person's own question comes back with the reason (t-722 §4.6, the C1-4b `approve_by_option` pattern), not a state with no move
            raise self.held_question("Your choice could not be carried out: the words it is about are not on file, so nothing was done. "
                                     "Answer again, in your own words or with one of the words offered.")
        rel, said = given
        option = next((o for o in asked.get("options") or [] if isinstance(o, dict) and str(o.get("token")) == token), {})
        block = str(asked.get("block") or "")
        gap_cases = [str(c) for c in asked.get("probe_gap_cases") or () if str(c).strip()]
        judged_cases = [str(c) for c in asked.get("probe_judgment_cases") or () if str(c).strip()]    # t-1968 N5; absent in an `asked` of any other question (E5.7)
        if move == "go_on_as_is" and (block or gap_cases or judged_cases):
            # POSITION INVARIANT (B-16, E1.6): only the token the person chose records anything; the existing `block` pass runs FIRST
            if block:
                self.pass_block(stage, block, rel or self.answer_file(), "Your word could not be recorded as the pass, so nothing was passed.")
                if block == JOURNAL_ROWS_BLOCK:
                    self.mark_rows_word(asked, stage)       # B-1: AFTER the pass is recorded, and only the rows of THIS question
                print(f"{stage}: going on on the person's word; recorded")
            import contract as C   # late, as every other site of this module
            for case in gap_cases:
                # the keys come from the question (`probe_gap_cases` of the window record), never typed here; a refusal is HELD (E1.4)
                self.pass_block(stage, f"{C.PROBE_GAP_MATCH_PREFIX} {case}", rel or self.answer_file(),
                                f"Your word could not be recorded as the probe gap of {case}, so nothing more was passed.")
            if gap_cases:
                print(f"{stage}: the probe gap of {', '.join(gap_cases)} is recorded on your word")
            for case in judged_cases:
                # one `probe not proved: <case key>` word per case the question named, never a `probe gap:` word (E5.1); a refusal is
                # HELD (E5.5): the words recorded before it stay (append-only), the later ones are not tried, nothing is printed as recorded
                self.pass_block(stage, f"{C.PROBE_NOT_PROVED_PREFIX} {case}", rel or self.answer_file(),
                                f"Your word could not be recorded as not proved for {case}, so nothing more was passed.")
            if judged_cases:
                print(f"{stage}: {', '.join(judged_cases)} stay not proved on your word")
        elif move == "release_and_restart":
            self.restart_by_option(stage, dispatch, rel or self.answer_file())
        elif move == "rework_stage" and isinstance(option.get("args"), dict):
            self.record_seam_rework(option["args"], rel)
        else:
            details = self.state_dir / "driver-question-details.md"
            if move == "rework_stage" and not rel:          # a rework without words has nothing to instruct with (§4.2 p.6)
                raise self.held_question(self.NO_REWORK_WORDS)  # remains: the person's own question comes back with the reason (t-722 §4.2 p.6)
            self.no_move({"why": "chosen", "kind": asked.get("kind", ""), "stage": stage, "dispatch": dispatch, "token": token, "move": move,
                          "says": str(option.get("says") or ""), "words": said,
                          "text": (details.read_text(encoding="utf-8", errors="replace") if details.is_file() else qtext[:6000]),
                          "words_file": rel, "block": block}, None)

    def restart_by_option(self, stage: str, dispatch: str, file: str) -> None:
        """`restart` (move `release_and_restart`): the dispatch the question is about is released BY CODE through `waiver.run_release`
        - the one caller of the controller's `release` (N4) - with the person's words by file; `where` then gives `relaunch` and the
        new session is told the words (`relaunch_reason`). A refusal of the controller is held with its words, nothing is released."""
        if not dispatch:
            # remains: the person's own question comes back with the reason (t-722 §4.4), not a state the driver has no move for
            raise self.held_question("Your choice to start that step again could not be carried out, so nothing was released.",
                                     "the question named no step")
        code, answer = waiver.run_release(self.task_root, dispatch, words_file=str(self.task_root / file), env=self.env)
        if code:
            # remains: the controller refused the release the person chose; the question comes back with its words (t-722 §4.4, FR-1)
            raise self.held_question("Your choice to start that step again could not be carried out, so nothing was released.", answer)
        print(f"{stage}: {dispatch} is released on the person's word; the driver starts it again")

    def original_words(self, asked: dict) -> "tuple[str, str] | None":
        """THE reader of the words a seam question is about (t-722 §4.1): `(rel, text)` of `asked.words_file`, read by the package's one
        words-file reader (`person_words.read`: bytes, CRLF kept, FR-8). Three outcomes: no file named (the question was raised without
        an answer: the token is everything said) -> `("", "")`; a file with text -> `(rel, text)`; a file named but missing, unreadable,
        not UTF-8 or empty -> None (the words are lost: the reader's refusal is the reason, and nobody acts on words nobody can read)."""
        rel = str(asked.get("words_file") or "")
        if not rel:
            return "", ""
        try:
            return rel, person_words.read(None, str(self.task_root / rel), "--words")
        except person_words.WordsRefused:
            return None

    EARLIER_ANSWER = EARLIER_ANSWER_MARK

    def combine_gate_words(self, asked: dict, raw: str, words: str) -> str:
        """The COMBINED words of a second answer at a gate (t-891 F-1..F-3): this answer, then `Earlier answer at this gate:` and the
        original answer of the question the seam raised. They are what the gate's decision keeps (FR-8, FR-9), and the same text is
        the answer's ONE words file (`self._answer`), so a token on the NEXT question - `approve`, `rework`, `go on` - reads both
        answers from `asked.words_file`. The tail is never read for the cards: the plan takes this answer's lines alone (`record_by_code`
        `apply_words`). No words file named on the question -> this answer alone, no tail. A file that is NAMED and lost is the held road
        of `approve_by_option` (t-722 4.6): the new answer is put on the record first, nothing is recorded, the person is told (FR-8)."""
        earlier = self.original_words(asked)
        if earlier is None:
            self.answer_file()
            self.record_answer_row("")
            # remains: the question comes back with the reason (t-722 4.6, the same held road as `approve_by_option`), not a move the driver lacks
            raise self.held_question("Your answer could not be taken: the words of your earlier answer at this gate are not on file, so "
                                     "nothing was recorded. Answer this gate again.")
        tail = earlier[1].strip()
        if not tail:
            return words
        if self._answer is not None and self._answer.get("rel") is None:        # the file of this answer is not written yet: it holds both
            self._answer["text"] = raw.rstrip() + self.EARLIER_ANSWER + tail
        return words + self.EARLIER_ANSWER + tail

    def approve_by_option(self, kind: str, stage: str, asked: dict) -> None:
        """The person chose `approve` from the options the seam raised at a gate (move `approve_gate`): the gate decision is recorded
        by code with the words of the ORIGINAL answer (`asked.words_file`, whole - FR-8), the card answers applied first (FR-9), and
        `approved_by="option"` says the choice, not the words, is the approval. The conductor never records a gate (I6). A controller
        refusal keeps the answer with that mark, so the kept road re-records it as an approval (H4) and the gate comes back with the
        refusal at its top (FR-7)."""
        words = (self.original_words(asked) or ("", ""))[1]
        if not words.strip():
            raise self.held_question("Your choice to approve could not be recorded: the words it is about are not on file, so "
                                     "nothing was approved. Answer this gate again.")
        # t-891 F-2 on the token road: a file that holds a second answer is `<new answer><EARLIER_ANSWER><earlier>` (`combine_gate_words`); the
        # card lines are read from the HEAD (the new answer) alone, the record keeps the whole. No tail -> nothing passed, as before.
        head, tail_mark, _earlier = words.partition(self.EARLIER_ANSWER)
        apply = {"apply_words": head} if tail_mark else {}
        if self.record_by_code(kind, stage, words, approved_by="option", **apply):
            return
        self.state["gate_answer_kept"] = {"gate": kind[-1], "words": words, "at": _now(), "approved_by": "option",
                                          "source_revision": self.controller_state().get("source_revision"),
                                          **({"apply": head} if tail_mark else {})}
        self.save_state()

    def boundary_step(self, action: dict) -> None:
        """One action, with the refusal loop around it."""
        self.guarded(lambda: self.dispatch_action(action), action)

    def guarded(self, move, action: dict) -> None:
        attempts = 0
        while True:
            try:
                move()
                self.drop_standing()            # E2: the step went through, so the refusal does not stand (and does not outlive its stage)
                return
            except Refusal as refusal:
                attempts += 1
                if attempts > REFUSALS_PER_BOUNDARY:
                    self.no_move({"why": "cap", "kind": "refusal", "call": False, "stage": str(action.get("stage") or ""),
                                  "dispatch": self.refusal_dispatch(refusal), "lead": self.refused_text(str(action.get("stage") or "")),
                                  "lines": self.refusal_lines(refusal),       # the last refusal's lines, not the "N refusals in a row" head
                                  "text": f"{attempts} refusals in a row at {self.boundary}; the last:\n\n{refusal.text}"})
                outcome = self.handle_refusal(refusal)
                if outcome == "retry" and refusal.retry:
                    try:
                        refusal.retry()
                        self.drop_standing()    # E2, the retried step went through
                        return
                    except Refusal as again:
                        refusal = again
                        continue
                return  # `continue`: back to `where`

    def take_stand_gap_answers(self, kind: str, words: str, qtext: str, stage: str, dispatch: str, keep_earlier: bool = False) -> dict:
        """Gate B (t-342, B-272): run the recording of a person's stand-gap answers FOR them.

        The card shows four answers in words and one form, `<case id>: <word>` (`gate_brief.gate_b_card_lines`,
        the words in `references/question-vocabulary.json`). A line that form reads is recorded here with the
        command the card used to print for the person to type - `waiver.py --stage S9 --block "stand gap: <id>"` -
        with the person's own line as the words (P13), so `contract.stand_gap_decisions` reads the same record as
        before (its option is the decision's first word). The command is the DRIVER's (FR-9: the decision has an
        executor; FR-48: a routine command runs from code) and is never shown to the person.

        Returns {} for any other question, or {"recorded": [...], "unread": [...], "note": str}. `unread` are lines
        that look like the form and cannot be read (an id that is no stand gap of this gate, a word outside the
        closed list, an id two gaps share); the caller sends the answer to the conductor with `note`, which names
        them - never silently dropped. A line that is not the form at all stays in the person's words, which the
        gate decision keeps whole.

        EDGES: two lines for one gap - the last counts, and the line printed says so; a story with no stand gaps -
        nothing is read and nothing is printed; a recording that fails raises a Person in words (the record's own
        text goes to the details file), the lines that did record stay recorded, and an answer sent again records
        them again harmlessly (`waiver.py` replaces the entry of the same block).

        `keep_earlier` (C2-7 §5.3, t-722 finding 6): this answer is a SECOND answer at the gate (a non-token to a question the seam
        raised); `stand_accept_cases` / `stand_accept_remedies` an EARLIER answer set are not dropped, so they reach `record_by_code`
        with the cases and remedies this answer adds (merged where they are set)."""
        # t-364: the SAME reader serves gate A (stage S5, the cards of `gate_brief.stand_gap_cards(.., "A")`) and the
        # `<check id>: accept` door of a rehearsal finding (`read_finding_doors`, both gates). Gate B's own lines are
        # read exactly as before.
        if kind not in ("gate_A", "gate_B") or self.dry:
            return {}
        gate = kind[-1]
        default_stage = "S5" if gate == "A" else "S9"
        if not keep_earlier:
            self.state.pop("stand_accept_cases", None)   # gate A: the cases whose every gap was accepted (read by `record_by_code`)
            self.state.pop("stand_accept_remedies", None)   # ... and the remedy each of them is blocked by when a LEVEL accepted it
        try:
            # B-426 D7: `C` is bound HERE, in the try, as it always was - an import that fails ends the reading
            # with the line below; the helpers import what they read themselves (`gate_brief` for the form line of the
            # refusal and the note)
            import contract as C
            read =self._stand_gap_lines(kind, gate, words, qtext)
        except Exception as exc:
            print(f"gate {gate}: the stand-gap lines of the answer could not be read ({type(exc).__name__}: "
                  f"{' '.join(str(exc).split())[:160]}); the answer is recorded whole, as it always was")
            return {}
        if read is None:
            return {}
        gaps, found, doors = read["gaps"], read["found"], read["doors"]
        forms, rehearsal = read["forms"], read["rehearsal"]
        if gate == "A":
            # `<case id>: accept as blocked` is the token of ANOTHER reader (`planning_contract.apply_gate_answers`, run by
            # `record_by_code`: the none card and every case with no gap card): not an unreadable stand-gap line. GW1-33 F7: the same
            # for `manual` / `automate` - the controller applies those case tokens too (`question_register.is_case_decision`)
            import question_register as QR
            found["unread"] = [item for item in found["unread"]
                               if not ((m := re.search(r":\s*([^:]+)$", item["line"])) and QR.is_case_decision(m.group(1).lower()))]
        if gate == "B":
            # P4 (id overlap): `<case id>: intended|bug|open` on a case that ALSO has a stand-gap card is the exploratory reader's
            # (`take_exploratory_answers`), not an unreadable stand-gap line. INVARIANT: only a line whose word is one of the
            # exploratory words AND whose id is a question line shown leaves this list; a stand-gap line that is really unread stays.
            import gate_brief
            cases = {gate_brief._id_key(s.get("case")) for s in self.state.get("shown_exploratory") or [] if isinstance(s, dict) and s.get("case")}
            index = gate_brief.exploratory_word_index()
            found["unread"] = [item for item in found["unread"]
                               if not ((m := gate_brief._FORM_LINE_RE.match(item["line"])) and gate_brief._id_key(m.group("id")) in cases
                                       and gate_brief._word_key(m.group("word")) in index)]
        revoked = self.revoke_environment_properties(gate, found.get("revokes") or [])
        found["unread"] = found["unread"] + doors["unread"] + revoked
        out = {"recorded": [], "unread": [item["line"] for item in found["unread"]], "note": "", "probed": []}
        failed = []
        failed_cases = set()      # B-361: the case of every gap whose own record failed (no carry is written for it)
        decided = {}
        try:
            decided = C.stand_gap_decisions(json.loads((self.task_root / "pipeline.json").read_text(encoding="utf-8")))
        except Exception:
            pass
        # every gap record, then every door record - the order the comment below depends on; each helper returns what it
        # recorded and what failed, and the lists grow here, in that order (S2)
        for recorded, bad, bad_cases in (self._record_gap_lines(gate, found["read"], forms, default_stage),
                                         self._record_door_lines(gate, doors["read"], gaps, default_stage)):
            out["recorded"] += recorded
            failed += bad
            failed_cases |= bad_cases
        # the container a person named on a which-container card (`read_finding_doors` `probes`): the read-only check runs FIRST
        # (`gate_preflight.Rehearsal._probe_verdict`, the verdict as the probe wrote it, never a sentence read here, FR-12) and the
        # write command runs ONCE, through `probe_move`, ONLY on `matched` (a write's exit 0 says nothing of the check: AR-28, FR-59).
        # Any other verdict, a timeout, an unreadable answer or a refused write joins `failed` with the verdict in words and writes
        # nothing, so another name stays answerable (AR-25). No waiver is recorded (nothing is passed: the next rehearsal proves the
        # stand with the registered probe's own check), the gate stays open, the person is not asked again (FR-3), nothing is retried.
        for entry in doors.get("probes") or []:
            if entry["replaced"]:
                print(f"gate {gate}: {entry['id']} was answered more than once; the last line counts: {entry['line']}")
            try:
                import gate_preflight
                said = gate_preflight.Rehearsal.named_container_said(Path(self.project), entry["name"], entry["probe"])
                if said:
                    failed.append((entry["id"], entry["line"], said))
                    continue
                self.probe_move(gate, [], {"argvs": [(entry["profile"], entry["argv"])]}, {"moves": []})
            except RepairFailed as exc:
                failed.append((entry["id"], entry["line"], f"the check matched, but registering it was refused ({exc.what}): {exc.text}"))
                continue
            except Exception as exc:
                failed.append((entry["id"], entry["line"], f"{type(exc).__name__}: {exc}"))
                continue
            out["probed"].append(entry)
            print(f"gate {gate}: {entry['id']}: the check of the stand's container `{entry['name']}` matched, and the probe is registered "
                  f"for `{entry['profile']}` on the person's word ({entry['line']})")
        if gate == "A":
            # F1 (FR-10): an `accept` on a card pointer's door (`case_preconditions-1: accept`) passes the block of THAT gap -
            # it is the same word as `<case id>: accept`, so it feeds the `accept as blocked` row the same way
            prefix = C.STAND_GAP_MATCH_PREFIX + " "
            by_gap = {str(g.get("id")): g for g in gaps}
            via_door = [{"gap": by_gap[str(e["door"]["block"])[len(prefix):]], "option": "accept", "line": e["line"]}
                        for e in doors["read"] if e["word"] == "accept" and e["door"].get("option") == "any"
                        and str(e["door"]["block"]).startswith(prefix) and str(e["door"]["block"])[len(prefix):] in by_gap]
            # B-361 (D-0026, FR-7): the gate A word travels under the CASE key, so the gate B card and the delivery check
            # find it (`stand_gaps.gate_b_answers`, `check_delivery.gather`). Both steps (R1b, then `carry_environment_
            # properties`, which also carries what the environment record covers) run AFTER every gap record of this
            # answer was written, and BEFORE the `failed` raise below: a case whose own gap record failed gets no carry (the
            # answer is asked again whole), and a revoke never follows the re-carry of the same answer. Neither step raises
            # (FR-3): what cannot be written is told, and gate B asks.
            self._revoke_changed_carries(found, gaps, default_stage)
            # R1 (`stand_gaps.write_carries`) and R8(c): the accepted cases, their remedies, the carries - the person's own lines
            # and what the environment record covers, in one call
            self.carry_environment_properties("A", gaps, found["read"] + via_door, decided, failed_cases)
        failure = ""
        if failed:
            # C1-4b (G22, FR-3): a record the story refused is the FACTORY's to repair, not a reason to make the person send their whole
            # answer again. The failed lines join `unread` (so the gate is not recorded by code over them), and the refusal text goes
            # whole into the note: the answer reaches the conductor ONCE with the failed line and what the record said.
            failure = ("\n\n## Lines of the answer the story's record REFUSED (the factory's to repair; the person is not asked to "
                       "send them again; what the driver could record is recorded)\n"
                       + "\n".join(f"- {shown} (\"{line}\"): {' '.join(str(text).split())[:600]}" for shown, line, text in failed))
        out["note"] = failure + self._relay_note(out, found, RelayCtx(forms, gaps, rehearsal, gate, default_stage))
        out["unread"] += [line for _shown, line, _text in failed]      # after the note: the relay note lists only lines nobody could read
        # GW1-33 F2: lines the code UNDERSTOOD but did not carry out, or that ask: they hold the approval for the conductor
        # (`gate_lines_over_approval`); a plain unread line may ride it. The refused record's text lives only in `note`.
        out["hold"] = ([line for _shown, line, _text in failed] + [item["line"] for item in revoked]
                       + [line for line in out["unread"] if "?" in line])
        return out

    EXPLORATORY_REWORK = {"stage": "S7", "role": "qa-failure-analyst", "cause": "question_answer"}

    def take_exploratory_answers(self, kind: str, words: str, qtext: str) -> dict:
        """Gate B (P2 fix round, critic t-1579 M1): carry out the person's answers to the QUESTION LINES of the findings
        (`<case id>: intended|bug|open`, `gate_brief.read_exploratory_answers`, read against `shown_exploratory`). Executors, in
        this order (the re-run S7 must see the confirmations): every `intended` (the line is corrected to `person_confirmed` by the
        person's word and, for a line with a question, the question is answered with the reading `now`), every `open` (a line with
        a question is `deferred_to_report`, one without is remembered so the next gate B says it is asked again), then ONE rework of
        S7 for all `bug` lines together with the person's whole words (the seam's record, run by `seam_rework_step`). A `bug`
        beside the gate's approval word is applied NOT (FR-12: the factory does not choose between contradicting words); both go to the
        conductor. Returns {} for another question, a dry run or nothing to read, else {"recorded", "unread", "note"}: a line that
        cannot be read or whose executor failed is `unread`, so the gate is not recorded by code over it and the answer reaches the
        conductor with the lines named (FR-3: the factory's failure never asks the person to send it again)."""
        if kind != "gate_B" or self.dry:
            return {}
        try:
            import gate_brief
            import exploratory_findings as EF
            shown = self.state.get("shown_exploratory") or []
            if not shown or not any(gate_brief._FORM_LINE_RE.match(raw) for raw in str(words or "").splitlines()):
                return {}
            register = EF.read(self.task_root)
            by_id = {line["id"]: line for line in register["lines"]}
            # live = the live line of each chain, and a line the person's own `intended` already replaced (the same word again is a
            # no-op, E11, not "the finding changed")
            live = {line["id"] for line in register["active"].values()} | {
                line["id"] for line in register["lines"] if line.get("_status") == "superseded"
                and (by_id.get(line.get("_next")) or {}).get("oracle_status") == EF.PERSON_CONFIRMED}
            try:
                gaps, covered = gate_brief.gate_b_split(self.task_root)
                card_ids = set(gate_brief._ids_of(list(gaps) + list(covered)))      # the ids a stand-gap card answers (m-6)
            except Exception:
                card_ids = set()                 # unknown: a word of another reader is read by nobody here, so it goes to the conductor
            found = gate_brief.read_exploratory_answers(words, shown, live, card_ids=card_ids)
        except Exception as exc:
            print(f"gate B: the question lines of the answer could not be read ({type(exc).__name__}: "
                  f"{' '.join(str(exc).split())[:160]}); the answer is recorded whole, as it always was")
            return {}
        unread = list(found["unread"])
        recorded, failed, bugs = [], [], []
        approval = self.gate_approval(kind, words)
        for entry in sorted(found["read"], key=lambda e: gate_brief.EXPLORATORY_OPTIONS.index(e["option"])):
            if entry["option"] == "bug":
                if approval:
                    unread.append({"line": entry["line_text"], "why": "a bug answer and the approval word in one answer; neither is applied"})
                else:
                    bugs.append(entry)
                continue
            try:
                done = (self._confirm_exploratory(entry, by_id.get(entry["line"]), words) if entry["option"] == "intended"
                        else self._leave_exploratory_open(entry, words))
            except Exception as exc:
                failed.append({"line": entry["line_text"], "why": ' '.join(str(getattr(exc, "text", "") or exc).split())[:300]})
                continue
            if done:
                recorded.append(entry["line_text"])
                print(f"gate B: {entry['case']}: {entry['option']} is carried out on the person's word ({entry['line_text']})")
        if bugs:
            args = dict(self.EXPLORATORY_REWORK, cases=sorted({e["case"] for e in bugs}))
            try:
                facts = self.no_move_facts({"kind": kind})
                clean, rule = NM.check_args(args, facts)
                if clean is None:
                    raise ValueError(rule)
                self.record_seam_rework(clean, self.answer_file(), self._bug_preface(bugs, by_id))
                recorded += [e["line_text"] for e in bugs]
                print(f"gate B: {', '.join(args['cases'])}: bug - the failure analysis is sent back, with your words, on its next step")
            except Exception as exc:
                failed += [{"line": e["line_text"], "why": ' '.join(str(getattr(exc, "text", "") or exc).split())[:300]} for e in bugs]
        out = {"recorded": recorded, "unread": [item["line"] for item in unread + failed], "note": ""}
        if recorded or unread or failed:
            out["note"] = ("\n\n## Question lines of the findings in this answer (the driver read them by code)\n"
                           + "".join(f"- recorded by code, do not record again: {line}\n" for line in recorded)
                           + "".join(f"- not read: {item['line']} ({item['why']})\n" for item in unread)
                           + "".join(f"- the factory could not carry it out: {item['line']} ({item['why']}); this is the factory's to repair, "
                                     "the person is not asked to send it again\n" for item in failed))
        return out

    def _question_row(self, qid: str):
        """The question register's row `qid`, or None: the ONE lookup of the exploratory executors (`question_register.load`, which
        raises on an unreadable register - the caller's line then fails to the conductor, never a silent pass)."""
        import question_register as QR
        return next((q for q in QR.load(self.task_root)["questions"] if q["id"] == qid), None) if qid else None

    def _bug_preface(self, bugs: list, by_id: dict) -> list:
        """One line per `bug` answer for the front of the rework's reason (critic t-1592 M-a, F10 (b)): the case, the finding's
        statement - what was seen - and before/now when the question row knows them (`report_facts.exploratory_bug_preface`). A
        line whose statement cannot be read says `not recorded`; the person's words travel whole either way."""
        import report_facts
        return [report_facts.exploratory_bug_preface(e["case"], by_id.get(e["line"]) or {}, self._question_row(e.get("qid")))
                for e in bugs]

    def _confirm_exploratory(self, entry: dict, line, words: str) -> bool:
        """`intended`: the question is answered with the reading `now` when the question says which reading that is (one writer,
        `question_register.record`), then the line is corrected to `person_confirmed` with the person's line (one writer,
        `exploratory_findings.append`). A line already confirmed is skipped (repeating words writes nothing); a line that is not the
        live line of its chain raises (the finding changed). False when nothing was written."""
        import contract as C
        import exploratory_findings as EF
        import question_register as QR
        if isinstance(line, dict) and line.get("_status") == "superseded":
            newer = next((l for l in EF.read(self.task_root)["lines"] if l.get("id") == line.get("_next")), {})
            if newer.get("oracle_status") == EF.PERSON_CONFIRMED and newer.get("_status") == "active":
                return False                  # the person's own word was carried out already: repeating it writes nothing
        if not isinstance(line, dict) or line.get("_status") != "active":
            raise ValueError("the finding changed since you saw it")
        if line.get("oracle_status") == EF.PERSON_CONFIRMED:
            return False
        if entry.get("qid"):
            row = self._question_row(entry["qid"])
            index = C.claim_reading_index(row, "now") if row else None
            if index is not None:
                QR.record(self.task_root, entry["qid"], "answered", words, "gate B", self.QUESTION_ANSWER_BY,
                          entry.get("row_hash") or row["row_hash"], reading=QR.LETTERS[index])
        fresh = {key: line[key] for key in ("kind", "title", "statement", "refs", "probe", "verification_status", "question",
                                            "owner_role", "missing_prerequisite") if key in line}
        fresh.update(op="correct", oracle_status=EF.PERSON_CONFIRMED,
                     why_not_a_bug=f'you said at gate B: "{entry["line_text"]}"',
                     evidence_refs=[{"path": ref["path"]} for ref in line.get("evidence_refs") or [] if isinstance(ref, dict) and ref.get("path")],
                     corrects={"id": line["id"], "reason": "confirmed as intended by the person at gate B"})
        if isinstance(line.get("origin"), dict):
            fresh["origin"] = line["origin"]
        EF.append(self.task_root, fresh, by=self.QUESTION_ANSWER_BY)
        return True

    def _leave_exploratory_open(self, entry: dict, words: str) -> bool:
        """`open`: a line with a question is `deferred_to_report` (not asked again, listed by the report - the question register's own
        state and its own way out, `--reopen`); a line without one is remembered, and the next gate B says it is asked again. The
        findings register is not written. False when nothing was written."""
        import question_register as QR
        if entry.get("qid"):
            row = self._question_row(entry["qid"])
            if row is not None and row.get("status") == QR.DEFERRED and not QR.is_open(row):
                return False
            QR.record(self.task_root, entry["qid"], QR.DEFERRED, words, "gate B", self.QUESTION_ANSWER_BY,
                      entry.get("row_hash") or (row or {}).get("row_hash", ""))
            return True
        self.state.setdefault("exploratory_open", {})[entry["line"]] = entry["case"]
        return True

    def _stand_gap_lines(self, kind: str, gate: str, words: str, qtext: str) -> dict | None:
        """B-426 D7: the READING half of `take_stand_gap_answers`, run inside its `try` (an exception here prints the
        "could not be read" line and returns {} there). None means "return {}": no line of the form in the words. Otherwise
        the gaps, what `read_stand_gap_answers` found, the rehearsal's doors, the form ids and the rehearsal itself."""
        import gate_brief
        if not any(gate_brief._FORM_LINE_RE.match(raw) for raw in str(words or "").splitlines()):
            if gate == "A":
                self.carry_environment_properties("A")   # no line to read - what the environment record decided still carries
            return None                     # no line of the form `<id>: <something>`: nothing to read, nothing to ask for
        rehearsal = None
        if gate == "A" or any(self._FINDING_LINE_RE.match(raw) for raw in str(words or "").splitlines()):
            rehearsal = self.rehearse(gate)          # ONE rehearsal serves the gaps (gate A) and the doors
        covered = []
        if gate == "A":
            import stand_gaps
            gaps = stand_gaps.collect(self.task_root, "A", rehearsal=rehearsal)
            covered = [g for g in (self.state.get("shown_gaps") or {}).get("A", {}).get("covered") or [] if isinstance(g, dict)]
        else:
            gaps, covered = gate_brief.gate_b_split(self.task_root)
        findings = [f for f in (rehearsal or {}).get("findings") or [] if isinstance(f, dict) and f.get("id")]
        # t-364 attempt 2, F3: a door line is read only against the packet the person was SHOWN (`qtext`, the question
        # file the answer belongs to - the text `shown_packet(kind)` reads): finding ids are ordinal per check, so a
        # rehearsal that changed since the packet could otherwise pass a block the person never saw under that id
        doors = (self.read_finding_doors(words, findings, qtext or self.shown_packet(kind),
                                         (self.state.get("shown_doors") or {}).get(gate))
                 if rehearsal is not None else {"read": [], "unread": []})
        found = gate_brief.read_stand_gap_answers(words, gaps, covered=covered)
        forms = gate_brief.stand_gap_form_ids(list(gaps) + covered)
        # F1: a line whose id is a finding of THIS rehearsal is the door reader's, never an unreadable stand-gap line
        finding_ids = {str(f["id"]) for f in findings}
        found["unread"] = [item for item in found["unread"]
                           if not ((m := self._FINDING_LINE_RE.match(item["line"])) and m.group("id") in finding_ids)]
        return {"gaps": gaps, "found": found, "doors": doors, "forms": forms, "rehearsal": rehearsal}

    def _record_gap_lines(self, gate: str, entries: list, forms: dict, default_stage: str) -> tuple:
        """B-426 D7: write the record (`waiver.py`) of every stand-gap line the reader read, in order. Returns
        (recorded ids, failed [(shown, line, text)], the cases of the gaps whose own record failed)."""
        import contract as C
        recorded, failed, failed_cases = [], [], set()
        # twin of _record_door_lines kept on purpose (t-666 F-4): four of eight steps differ; one loop would need a kind switch
        for entry in entries:
            gap, option = entry["gap"], entry["option"]
            shown = forms.get(str(gap.get("id")), str(gap.get("id")))
            if entry["replaced"]:
                print(f"gate {gate}: {shown} was answered more than once; the last line counts: {entry['line']}")
            # t-364 attempt 2, F4 (FR-7): a word the person gave at the OTHER gate for the same case is not a reason to
            # skip this one - each gate's card reads its own gap id, so ONE word is written as TWO records, and the card
            # the person just answered (and the dashboard) shows it answered
            # the decision's FIRST word is the option (`contract.stand_gap_decisions` reads it from there); the rest is
            # the person's own line, and - when they wrote the gap twice - the earlier lines this one replaces
            said = C.person_decision(option, entry["line"], entry["replaced"])
            code, text = self.py("waiver.py", "--task", self.task, "--stage", str(gap.get("stage") or default_stage),
                                 "--block", f"{C.STAND_GAP_MATCH_PREFIX} {gap.get('id')}", "--decision", said, *self.waiver_road())
            if code:
                failed.append((shown, entry["line"], text))
                import stand_gaps
                failed_cases.update(stand_gaps.gap_cases(gap))
                continue
            recorded.append(shown)
            print(f"gate {gate}: stand gap {shown}: recorded on the person's word, as {option} ({entry['line']})")
            if entry.get("lasting"):
                # B-414 R8(b): `accept always` - the story's answer above, and ONE row in the project's environment record, with
                # the person's line whole. A failure is printed, never added to `failed` (FR-3: it is the factory's, not a reason to
                # ask the person to send the whole answer again)
                import stand_gaps
                stand_gaps.record_lasting(self.project, entry, self.task, print)
        return recorded, failed, failed_cases

    def _record_door_lines(self, gate: str, entries: list, gaps: list, default_stage: str) -> tuple:
        """B-426 D7: write the record of every rehearsal-finding door the reader read, in order; the same return as
        `_record_gap_lines`."""
        import contract as C
        recorded, failed, failed_cases = [], [], set()
        # twin of _record_gap_lines kept on purpose (t-666 F-4): four of eight steps differ; one loop would need a kind switch
        for entry in entries:
            # a rehearsal finding's door (`<check id>: accept` and the person's reason): the block and the stage are the
            # finding's own `waives` (gate_preflight), the person's line is quoted whole as the decision
            door, line = entry["door"], entry["line"]
            if door.get("option") == "product_gap":
                # D1-C2 (Q1-d): a product gap is the person's word about a requirement, recorded by its ONE writer and never a
                # waiver - so it can never become a `stage_overrides[]` row that `_plan_decision` files as "your words at gate A"
                import product_gaps
                path = self.words_file(line, "productgap")
                try:
                    ref = path.relative_to(self.task_root).as_posix() if path is not None else ""
                except ValueError:
                    ref = str(path)
                reqs, problem = product_gaps.record(self.task_root, str(door.get("row") or ""), line, ref, gate)
                if problem:
                    failed.append((entry["id"], line, problem))
                    continue
                recorded.append(entry["id"])
                print(f"gate {gate}: {entry['id']}: recorded as a product gap of {', '.join(reqs)} - the product has no such function, "
                      f"on the person's word ({line})")
                continue
            said = C.person_decision(entry["word"], line, entry["replaced"])
            code, text = self.py("waiver.py", "--task", self.task, "--stage", str(door.get("stage") or default_stage),
                                 "--block", str(door["block"]), "--decision", said, *self.waiver_road())
            shown = entry["id"]
            if code:
                failed.append((shown, line, text))
                if gate == "A" and str(door["block"]).startswith(C.STAND_GAP_MATCH_PREFIX + " "):
                    import stand_gaps
                    failed_cases.update(c for g in gaps if str(g.get("id")) == str(door["block"])[len(C.STAND_GAP_MATCH_PREFIX) + 1:]
                                        for c in stand_gaps.gap_cases(g))
                continue
            recorded.append(shown)
            print(f"gate {gate}: {shown}: the block `{door['block']}` is passed on the person's word ({line})")
        return recorded, failed, failed_cases

    def _revoke_changed_carries(self, found: dict, gaps: list, default_stage: str) -> None:
        """B-426 D7 (gate A only): R1b - take back, with `waiver.py --revoke`, the case-level `accept` an earlier answer
        carried for a gap whose word CHANGED in this answer. Prints one line per case; never raises on a failed revoke."""
        import contract as C
        import stand_gaps
        gap_cases = stand_gaps.gap_cases          # N6: ONE expansion of a gap to its cases (a level gap names several)
        # R1b: a gap's word CHANGED in this answer takes back the case-level `accept` an earlier answer carried (else gate
        # B settles on a word the person has since replaced). The cases: every case of the gap plus every case of every
        # gap with that id
        try:
            overrides = json.loads((self.task_root / "pipeline.json").read_text(encoding="utf-8")).get("stage_overrides")
        except Exception:
            overrides = []
        live = {C.stand_gap_id(o.get("match")): str(o.get("match")) for o in overrides if isinstance(o, dict)
                and str(o.get("stage") or "") == default_stage and not o.get("revoked_at")} if isinstance(overrides, list) else {}
        for entry in found["read"]:
            if entry["option"] == "accept":
                continue
            for case in dict.fromkeys(gap_cases(entry["gap"]) + [c for g in gaps if str(g.get("id")) == str(entry["gap"].get("id"))
                                                                 for c in gap_cases(g)]):
                if case not in live:
                    continue
                code, text = self.py("waiver.py", "--revoke", "--task", self.task, "--stage", default_stage, "--block", live[case],
                                     *stand_gaps.words_args(self.words_file, f"the person changed their answer at gate A: {entry['line']}", "revoke"), *self.waiver_road(False))
                print(f"gate A: {case}: the earlier acceptance of the whole case is taken back, you changed a word of it ({entry['line']})"
                      if not code else
                      f"gate A: {case}: the earlier acceptance could not be taken back ({' '.join(text.split())[-160:]}); gate B will ask again")
                live.pop(case, None)

    def _relay_note(self, out: dict, found: dict, ctx: RelayCtx) -> str:
        """B-426 D7: the note the conductor reads - what the driver already recorded, and the lines it could not read
        with everything the conductor needs to record them (critic t-346 F4/F3). Prints the one line about the unread
        lines. The note is "" when nothing was recorded and nothing was unread."""
        import gate_brief
        note = ""
        # critic t-346 F4: whenever ANY line was recorded the conductor is told so - the gate decision can still fail to
        # record by code and the words then reach it, with these lines already on the record.
        if out["recorded"]:
            note += ("\n\n## Stand-gap lines of this answer the driver has already recorded: "
                     + ", ".join(out["recorded"]) + " - do not record those again")
        if out.get("probed"):
            # not stand-gap lines: a container the person named, checked read-only (`matched`) and then registered; no waiver, no gate passed
            note += ("\n\n## Containers the person named on a runtime-probe card, already checked and registered by the driver (these are not "
                     "stand-gap lines and pass no gate; do not check or register them again): "
                     + "; ".join(f"{p['id']} = `{p['name']}` for profile `{p['profile']}` (the check said `matched`)" for p in out["probed"]))
        if out["unread"]:
            # critic t-346 F3 (FR-7: a guessed word reads back as "" and the gap is asked again): the note carries what
            # the conductor needs to record a gap in the form the reader reads - the block key, the stage and the
            # word -> option map, the last from the data file (`stand_gap_words`), never from prose.
            options = "; ".join(f"`{row['option']}` for " + ", ".join(f"`{w}`" for w in [row["word"], *row["synonyms"]])
                                for row in gate_brief.stand_gap_words())
            # t-409 H3 (FR-10, axis 5): the options are PER CARD. A card that carries `remedy.offers` (the reporter card) takes
            # ONLY those; a card with none takes all four, as every card did before. The line says which, in the same words
            # `skills/qa-story/phases/s4.md` says them, and never lets the map above speak for a card that does not take a word.
            keys = "\n".join(gate_brief.relay_card_line(g, ctx.forms.get(str(g.get("id")), g.get("id")), ctx.default_stage)
                             for g in ctx.gaps)
            # t-364: the doors of the rehearsal's findings, for a line `<check id>: accept` the driver could not read
            # (a finding with no door is a gap of the factory's own: the conductor says so, never passes it silently)
            door_keys = "\n".join(
                f"- {f['id']}: block `{d['block']}`, stage {d.get('stage') or ctx.default_stage}, word option `{d.get('option')}`"
                for f in (ctx.rehearsal or {}).get("findings") or [] if isinstance(f, dict) and f.get("id")
                for d in f.get("waives") or [] if isinstance(d, dict) and d.get("block"))
            # F3: a door line whose id no longer names the message the person read goes whole to the conductor, with the
            # CURRENT list, so it can ask what they meant (the same class as `shown_hashes` on a card)
            changed = ""
            if any(str(item.get("why") or "").startswith("the checks changed") for item in found["unread"]):
                changed = ("\n\nThe checks changed since the person read them; here is the current list (id and message) - "
                           "pass nothing by an id the person did not see with this message:\n"
                           + "\n".join(f"- [{f['id']}] {' '.join(str(f.get('message') or '').split())}"
                                       for f in (ctx.rehearsal or {}).get("findings") or [] if isinstance(f, dict) and f.get("id")))
            note += ("\n\n## Lines of the answer the driver could not read as a stand-gap answer (read each one "
                     "and record what the person means with the factory's own commands; the lines the driver "
                     "did read are already recorded"
                     + (f": {', '.join(out['recorded'])}" if out["recorded"] else "")
                     + " - do not record those again)\n"
                     + "\n".join(f"- {item['line']}  [{item['why']}]" for item in found["unread"])
                     + "\n\nTo record a stand gap run waiver.py --task <T> --stage <stage> --block "
                       "\"<block>\" --decision \"<option> - the person wrote: <their line>\": the decision's "
                       "FIRST word must be the option, or the reader reads it back as no answer and the gap is "
                       "asked again. Options and the words that mean them (a gap below that says it takes ONLY some "
                       "options takes only those: record nothing for another word, and tell the person the words "
                       "that apply to that card): " + options
                     + ". A lasting word (`accept always`) and `ask again` have their commands in "
                       "references/conductor-actions.json. The gaps of this gate:\n" + keys
                     + ("\n\nThe findings of this gate's rehearsal a person's word can pass (a line `<check id>: "
                        "accept` and their reason; a finding that is not listed has no door - say so, pass "
                        "nothing for it):\n" + door_keys if door_keys else "")
                     + changed)
            print(f"gate {ctx.gate}: " + str(len(out["unread"])) + " line(s) of the answer look like a stand-gap answer and "
                  "could not be read: " + "; ".join(out["unread"])[:300])
        return note

    def carry_environment_properties(self, gate: str, gaps=None, read=(), decided=None, failed_cases=()) -> None:
        """B-414 R8(c) (D-0029): what a person accepted ONCE for this environment reaches THIS story as if they had said it here.

        Reads what the packet the person saw kept (`shown_gaps`: its open gaps and the gaps the environment record covered) and
        runs no rehearsal. For each covered gap with no live record in this story: the gap's own override, `--by environment-
        record`, the record's words quoted (`stand_gaps.write_environment_overrides`; none when its id is shared with, or the start
        of, another gap's); then, over the open gaps AND the covered ones together, the cases whose EVERY stand gap is accepted -
        by the person's lines of this answer (`gaps`/`read`, given by the tail of `take_stand_gap_answers`) or by the record -
        become `stand_accept_cases` (merged into what is there) with each LEVEL gap's own remedy as `stand_accept_remedies`
        (F19), and get their carry (`stand_gaps.write_carries`). A case with another OPEN gap gets neither (E12), and one
        printed line names the gap. With no covered gap and no lines this changes nothing. Never raises (FR-3)."""
        import contract as C
        import stand_gaps
        shown = (self.state.get("shown_gaps") or {}).get(gate) or {}
        covered = [g for g in shown.get("covered") or [] if isinstance(g, dict) and isinstance(g.get("property"), dict)]
        reopened = [g for g in shown.get("reopened") or [] if isinstance(g, dict)]     # taken back by `ask again` in this answer
        if gaps is None and not covered:
            return
        open_gaps = [g for g in (shown.get("gaps") if gaps is None else gaps) or [] if isinstance(g, dict)] + reopened
        try:
            if decided is None:
                decided = C.stand_gap_decisions(json.loads((self.task_root / "pipeline.json").read_text(encoding="utf-8")))
            failed = set(failed_cases)
            for gid in stand_gaps.write_environment_overrides(self.task_root, self.task, covered,
                                                              [str(g.get("id")) for g in open_gaps + covered], self.py,
                                                              self.words_file, print):
                failed |= {c for g in covered if str(g.get("id")) == gid for c in stand_gaps.gap_cases(g)}
            everything, entries = open_gaps + covered, list(read) + stand_gaps.covered_entries(covered)
            cases = self.accepted_cases(everything, entries, decided)
            accepted_ids = {str(e["gap"].get("id")) for e in entries if e.get("option") == "accept"}
            for case in dict.fromkeys(c for g in covered for c in stand_gaps.gap_cases(g)):
                still = [str(g.get("id")) for g in open_gaps if case in stand_gaps.gap_cases(g)
                         and str(g.get("id")) not in accepted_ids and (decided.get(str(g.get("id"))) or {}).get("option") != "accept"]
                if case not in cases and still:
                    print(f"gate {gate}: {case}: not blocked and not carried - its stand gap {', '.join(still)} is still open")
            if cases:
                self.state["stand_accept_cases"] = list(dict.fromkeys(list(self.state.get("stand_accept_cases") or []) + cases))
                remedies = self._level_remedies(everything, cases)
                if remedies:
                    self.state["stand_accept_remedies"] = dict(self.state.get("stand_accept_remedies") or {}, **remedies)
            stand_gaps.write_carries(self.task_root, self.task, everything, entries, cases, decided, failed, self.py,
                                     self.words_file, print)
        except Exception as exc:
            print(f"gate {gate}: what the answer accepts could not all be carried ({type(exc).__name__}: "
                  f"{' '.join(str(exc).split())[:160]}); gate B will ask what is left")

    @staticmethod
    def _level_remedies(everything: list, cases: list) -> dict:
        """t-667 D16: the remedy each LEVEL gap carries, by case, for the cases that are accepted (F19): the first gap that names a
        case wins (`setdefault`); a gap that is not a level gap, or whose remedy is not valid, gives none. Pure - the caller keeps
        the `try` (FR-3: `carry_environment_properties` never raises) and the write to `stand_accept_remedies`."""
        import contract as C
        import stand_gaps
        remedies = {}
        for gap in everything:
            if not (gap.get("scope") == "level" and isinstance(gap.get("remedy"), dict) and not C.remedy_errors(gap["remedy"])):
                continue
            for case in stand_gaps.gap_cases(gap):
                if case in cases:
                    remedies.setdefault(case, dict(gap["remedy"]))
        return remedies

    def revoke_environment_properties(self, gate: str, revokes: list) -> list:
        """B-414 R8(d) (E8, FR-48, FR-57): `<name>: ask again` for a gap the environment record covers. The driver takes the row
        back (`environment_record.py revoke`), then this story's own records that rest on it (`stand_gaps.revoke_environment_
        overrides`), and drops the gap's cases from the cases about to be blocked. Returns the `unread` lines for the conductor
        ("show them its card"): the gate decision is not recorded by code over them, so the card is asked again through the
        channel that already exists. A failed revoke is printed and changes nothing."""
        import stand_gaps
        out, gone_ids = [], set()
        for entry in revokes:
            gap = entry["gap"]
            row = gap.get("property") if isinstance(gap.get("property"), dict) else {}
            name = stand_gaps._label(gap)
            registry = bool(stand_gaps.pk_property_of(gap))      # PK0-9: a row of the project-knowledge registry, taken back by its own tool
            code, text = self.py("project_knowledge.py" if registry else "environment_record.py", "revoke", "--id", str(row.get("id")),
                                 *stand_gaps.words_args(self.words_file, entry["line"], "ask-again"))
            if code:
                why = " ".join(text.split())[-160:]
                held = "its entry in the record of earlier answers" if registry else "its record for the environment"
                print(f"gate {gate}: {name}: " + ("the entry in the record of earlier answers" if registry
                                                  else "the record for this environment") + f" could not be taken back ({why})")
                out.append({"line": entry["line"], "why": f"the person asked for this again, and {held} "
                                                          f"could not be taken back ({why}): nothing was changed"})
                continue
            stand_gaps.revoke_environment_overrides(self.task_root, self.task, gap, self.py, self.words_file, print)
            cases = set(stand_gaps.gap_cases(gap))
            if self.state.get("stand_accept_cases"):
                self.state["stand_accept_cases"] = [c for c in self.state["stand_accept_cases"] if c not in cases]
            if isinstance(self.state.get("stand_accept_remedies"), dict):
                self.state["stand_accept_remedies"] = {c: r for c, r in self.state["stand_accept_remedies"].items() if c not in cases}
            gone_ids.add(str(gap.get("id")))
            print(f"gate {gate}: {name}: taken back from the {'record of earlier answers' if registry else 'environment record'} "
                  f"({row.get('id')}); it is asked again")
            out.append({"line": entry["line"], "why": "the person asked for this again; its " + (
                "entry in the record of earlier answers" if registry else "record for the environment") + " is taken back: show them its card"})
        shown = (self.state.get("shown_gaps") or {}).get(gate)
        if gone_ids and isinstance(shown, dict):
            # a gap taken back is an OPEN gap of this story again (no word, so none of its cases is blocked or carried)
            shown["reopened"] = list(shown.get("reopened") or []) + [g for g in shown.get("covered") or [] if str(g.get("id")) in gone_ids]
            shown["covered"] = [g for g in shown.get("covered") or [] if str(g.get("id")) not in gone_ids]
        return out

    # t-364 -- the readers `take_stand_gap_answers` leans on. A rehearsal finding's id is `<check>-<n>` or `<check>-<subject>` (`case_environment-TS-23`), starting lower case; membership decides.
    from gate_preflight import FINDING_ID_PATTERN as _FINDING_ID_PATTERN  # the id form the rehearsal WRITES (`_id_token`) is the one read here (AR-18, F5)
    _FINDING_LINE_RE = re.compile(r"^\s*(?:[-*•]\s+)?`?(?P<id>" + _FINDING_ID_PATTERN + r")`?\s*:\s*(?P<rest>\S.*?)\s*$")

    def read_finding_doors(self, words: str, findings: list, shown: str = "", shown_doors: dict | None = None) -> dict:
        """The line `<check id>: accept <the person's reason>` for a finding of the gate's rehearsal: {"read", "unread", "probes"}.

        `probes`: a line `<check id>: <container name>` that names exactly one container of a which-container card (the finding's
        `container_answers`) - it passes the same packet, door and `?` checks as a door line, and is NEVER in `read` (it records no
        waiver); `take_stand_gap_answers` runs its write command once.

        The door a finding names in words (`gate_preflight.Rehearsal.waiver_command`) is READ here, by form: the id of a
        finding of THIS rehearsal AS THE PERSON SAW IT (`shown`: the packet carries `[<id>] <the current message>`, else
        the line is unread - ids are ordinal per check and renumber when the rehearsal changes), then either the WHOLE text
        after the colon is a word or synonym of the closed list (the t-342 rule), or its FIRST word is the canonical `word`
        of an option and the rest is the person's reason, kept whole inside the decision (P13). A synonym as a first word
        is never read (`blocked, why? what does this mean` is a question, not consent). The finding's own `waives`
        ([{block, stage, option}]) says what the word passes: `accept` (or `any`, the card pointers) takes `accept`;
        `handed` takes `run`. A door that asks for a reason (`accept` on a check) is unread without one.
        Never read: a finding with NO `waives` (a gap of the factory's own), a word the door does not take, an unknown
        word. Unread lines are named, never dropped. The person's LAST line for an id decides it: a readable line
        followed by an unreadable one is set aside with it. An id that is no finding of this rehearsal is not this
        reader's line at all (a case, a question, a bug number).

        t-369 N-1: a `?` ANYWHERE in the line sends it to the conductor whole - a question is never consent.
        N-2: `shown_doors` is {id: waives} as the packet SHOWED them (`gate()` stores it when the gate is asked); a line is
        read only when the current rehearsal's `waives` for that id EQUAL the stored ones - the message alone does not bind
        the block (same id, same words, another block is another door); no stored entry reads as changed."""
        import gate_brief

        def container_choice(finding: dict, text: str):
            """The closed answer of a which-container card (`gate_preflight._probe_which_container`): the WHOLE text after the colon,
            trimmed, is exactly one of the finding's own `container_answers` (case-sensitive) and that name has a write command in
            `answer_probes` (the read-only check) and `answer_argvs` (the write): {"profile", "name", "probe", "argv"}, else None.
            Nothing is run here and no pass is recorded by it."""
            names = finding.get("container_answers")
            name = str(text or "").strip()
            pair = []
            for key in ("answer_probes", "answer_argvs"):
                argvs = finding.get(key)
                argv = argvs.get(name) if isinstance(argvs, dict) else None
                if not (isinstance(argv, list) and argv and all(isinstance(a, str) and a for a in argv)):
                    return None
                pair.append(list(argv))
            if not (isinstance(names, list) and name in names):
                return None
            return {"profile": str(finding.get("profile") or ""), "name": name, "probe": pair[0], "argv": pair[1]}

        index = gate_brief.stand_gap_word_index()
        stored_doors = shown_doors if isinstance(shown_doors, dict) else {}
        canonical = {gate_brief._word_key(row["word"]): row["option"] for row in gate_brief.stand_gap_words()}
        door_words = gate_brief.finding_door_words()
        # the packet's lines, whitespace-normalised: a finding is SHOWN when a line ENDS with `[<id>] <the message>` (a message
        # that only starts like the one shown is another message)
        packet = [" ".join(row.split()) for row in str(shown or "").splitlines()]
        by_id = {str(f.get("id")): f for f in findings if isinstance(f, dict) and f.get("id")}
        seen: dict = {}
        for raw in str(words or "").splitlines():
            hit = self._FINDING_LINE_RE.match(raw)
            if not hit or hit.group("id") not in by_id:
                continue
            fid, rest, line = hit.group("id"), hit.group("rest"), " ".join(raw.split())
            option, reason = index.get(gate_brief._word_key(rest), ""), ""
            first = re.match(r"([^\s,;:.\-—–]+)[\s,;:.\-—–]*(.*)", rest, re.DOTALL)
            if not option and first:
                option, reason = canonical.get(gate_brief._word_key(first.group(1)), ""), first.group(2).strip()
            if not option:
                # D1-C2 (Q1-b): the words a finding's OWN door takes (`finding_door_words`), tried only AFTER the stand-gap words, so no
                # existing word changes meaning. The word alone (or a synonym alone) is read; the word followed by a separator and the
                # person's reason is read with the reason kept; the word followed by a letter (`product gaps`) is not the word
                option, reason = gate_brief.finding_door_option(rest, door_words)
            doors = [d for d in by_id[fid].get("waives") or [] if isinstance(d, dict) and d.get("block")]
            message = " ".join(str(by_id[fid].get("message") or "").split())
            if not any(row == f"[{fid}] {message}" or row.endswith(f" [{fid}] {message}") for row in packet):
                status = ("unread", "the checks changed since the person read them: this id does not name that message in the "
                                    "packet they were shown")
            elif fid not in stored_doors or json.dumps(stored_doors[fid], sort_keys=True) != json.dumps(
                    [d for d in by_id[fid].get("waives") or [] if isinstance(d, dict)], sort_keys=True):
                status = ("unread", "the checks changed since the person read them: the door this id showed is not the one "
                                    "it has now")
            elif "?" in line:
                status = ("unread", "the line asks a question, and a question is never consent")
            elif (choice := container_choice(by_id[fid], rest)):
                status = ("probe", choice)
            elif not option:
                status = ("unread", "the word is not one of the answers a finding's door takes")
            elif not doors:
                status = ("unread", "this finding records no door (a gap of the factory's own): nothing is passed for it")
            else:
                fit = [d for d in doors if d.get("option") == option or (d.get("option") == "any" and option == "accept")]
                if len(fit) != 1:
                    status = ("unread", "the door of this finding does not take that word" if not fit
                              else "this finding has more than one door for that word")
                elif option == "accept" and fit[0].get("option") == "accept" and not reason:
                    status = ("unread", "the door of this check asks for the person's reason with `accept`, and there is none")
                else:
                    status = ("read", {"door": fit[0], "option": option, "reason": reason})
            seen.setdefault(fid, []).append((line, status))
        out: dict = {"read": [], "unread": [], "probes": []}
        for fid, lines in seen.items():
            line, (state, payload) = lines[-1]
            earlier = [l for l, _s in lines[:-1]]
            if state == "probe":
                out["probes"].append(dict(payload, id=fid, line=line, replaced=earlier))
            elif state == "read":
                out["read"].append({"id": fid, "line": line, "word": payload["option"], "door": payload["door"],
                                    "reason": payload["reason"], "replaced": earlier})
            else:
                out["unread"].append({"line": line, "why": payload})
                out["unread"].extend({"line": l, "why": "an earlier line for this finding, set aside: its last line could "
                                                        "not be read, so the person's last word is unread"} for l in earlier)
        return out

    @staticmethod
    def accepted_cases(gaps: list, read: list, decided: dict) -> list:
        """The cases whose EVERY gap at this gate is accepted - by this answer (at least one of them) or an earlier one.

        `accept` on a card says "it stays blocked and is reported as not run": the waiver is the person's decision, and
        the `blocked_by_env` row that makes S5 report it is `planning_contract.apply_gate_answers`'s effect of it. Both
        come from the ONE line read here (`record_by_code` hands that line to the executor in its own token), so the
        two records cannot disagree. A case with a gap that is NOT accepted is never blocked as a whole (the error
        direction of the executor: toward not applying).

        B-414 (R8(a), R16): a gap's cases are `stand_gaps.gap_cases` (a LEVEL gap names several, and each of them is counted),
        and a case that got a word OTHER than `accept` for any of its gaps in THIS answer is never returned, whatever an older
        `decided` says (rev1 guard iii: the stale-`decided` fallback no longer lets a changed word through). `read` may hold the
        entries of covered gaps (`stand_gaps.covered_entries`): an `accept` that the environment record gave."""
        import stand_gaps
        now = {str(e["gap"].get("id")) for e in read if e.get("option") == "accept"}
        reworded = {c for e in read if e.get("option") != "accept" for c in stand_gaps.gap_cases(e["gap"])}
        by_case: dict = {}
        for gap in gaps:
            for case in stand_gaps.gap_cases(gap):
                by_case.setdefault(case, []).append(str(gap.get("id")))
        return [case for case, ids in by_case.items()
                if case not in reworded and any(i in now for i in ids)
                and all(i in now or (decided.get(i) or {}).get("option") == "accept" for i in ids)]

    def take_package_answer(self, words: str, qtext: str, stage: str, dispatch: str) -> None:
        """The answer to a `package` question (B-014 / FR-4 / FR-9: a check stops a silent pass, never an informed one, and what a
        person decides has an executor). The answer is one of a CLOSED set of tokens (the S0 stop's pattern; the code reads a token,
        never a meaning - FR-12): `go on` passes the ONE thing asked about (the root pair, or the mode switch at that stage) and is
        recorded; `retry` (hooks) or `desktop` (mode) and `stop` are recorded and END the run without running or spending anything
        - the question stays open, the same door. Anything else is NEW words the code cannot read: the seam (D-0041), with the
        question's own words as its doors; a conductor `continue` / `retry` RETURNS from here - nothing is recorded or passed,
        `package_question` is kept and the check runs again (G1). `package_question` is popped only by an answer that lets the run
        go on."""
        pending = self.state.get("package_question") or {}
        is_mode = pending.get("what") == "mode"
        token = self.s0_normalize(words)
        said = "run mode switch" if is_mode else "package copies differ between the driver and the hooks"
        own = "desktop" if is_mode else "retry"
        base = str(pending.get("text") or QUESTION_HEAD_RE.sub("", ANSWER_BLOCK_RE.sub("", qtext), count=1)).strip()
        details = str(pending.get("details") or "")
        if token not in ("go on", "stop", own):
            self.answer_row(f"package ({said}): not one of the answers, asked again: ", words.strip(), what="your answer about the package copies")
            lead = self.unread_lead(words)
            self.unread("package", stage, dispatch, base + "\n\n" + details, words=words, doors=(own, "go on"), lead=lead,
                        again=lambda said_lead: Person("package", f"{said_lead}\n\n{base}", stage, dispatch, details=details))
            return
        if token in ("stop", "desktop"):
            self.answer_row(f"package ({said}): ", words.strip(), what="your answer about the package copies")
            held = (self.stop_held() if token == "stop" else
                    "You said you will finish this story in the desktop app. The story waits for it; "
                    "nothing runs here meanwhile.")
            raise Person("package", f"{held} If you want the driver to go on after all, answer `go on`.\n\n{base}",
                         stage, dispatch, details=details)
        self.state.pop("package_question", None)
        ref = dispatch or str(pending.get("session") or "") or self.task
        self.answer_row(f"package ({said}): ", words.strip(), what="your answer about the package copies")
        if token == "retry":
            print(f"{stage}: nothing is passed; the step runs again and the copies are compared again")
        elif is_mode:
            # Q3 (C1-7a): a switch that was not recorded is the person's own question back, not a print (B-3). POSITION INVARIANT: the
            # `package_question` is popped above, so a held question raised from here would make the NEXT `go on` read as the
            # package-copies pass (`pending` empty, FR-9): the question is put back before it is raised, and only a recorded switch
            # leaves it popped.
            try:
                self.pass_block(str(pending.get("stage") or stage), waiver.MODE_SWITCH_BLOCK, self.answer_file(),
                                "Your word could not be recorded as the mode switch, so nothing was switched.")
            except Person:
                self.state["package_question"] = pending
                raise
            print(f"{stage}: the mode switch is recorded on the person's word")
        else:
            self.state["package_pass"] = {"driver_root": pending.get("driver_root") or "",
                                          "hook_roots": list(pending.get("hook_roots") or []),
                                          "words": words, "ts": _now()}
            print(f"{stage}: the person's word passes this pair of package copies; the step runs again")
        if token == "go on" and not is_mode:
            # A mismatch of the factory's own copies is a defect of ours, filed in the person's
            # words. A run-mode switch is the person's choice, not a defect: waiver + human_answer only.
            self.py_trace("log_append.py", "--event", "defect_found", "--task", self.task, "--ref", ref,
                          "--by", "driver", "--notes", _answer_note(
                              f"owner: factory — {said}; passed on the person's words: ", words.strip()),
                          why="the pass itself is on the record (package_pass and the human_answer row above); this defect line is the "
                              "finding about it, and a defect filer cannot file its own failure")

    def take_answer(self, path: Path) -> None:
        raw = path.read_bytes().decode("utf-8", "replace")      # the bytes as given (CRLF kept): the words file is written from them
        words = raw.replace("\r\n", "\n").replace("\r", "\n").strip()
        question = self.state_dir / "driver-question.md"
        asked = self.state.get("asked") or {}
        if not words:
            raise Stop(EXIT_ERROR, f"{path} is empty")
        if not asked.get("kind"):
            raise Stop(EXIT_ERROR, "no question is open (state/driver-state.json has none asked)")
        self._answer = {"text": raw, "rel": None}               # ONE words file per answer, written on first use (`answer_file`)
        seam_token = False                                      # the answer was a token of a question the seam raised
        kind, stage, dispatch = asked.get("kind", ""), asked.get("stage", ""), asked.get("dispatch", "")
        self.boundary = f"{stage}:{dispatch or kind}:answer"
        self.answer_kind = kind
        print(f"answer for {kind} ({stage}{' ' + dispatch if dispatch else ''}): {words[:200]}")
        qtext = question.read_text(encoding="utf-8", errors="replace") if question.is_file() else ""
        self._answer.update(kind=kind, stage=stage, dispatch=dispatch, question_sha=question_body_sha(qtext), words=words)
        # t-342 (B-272): a gate B answer's stand-gap lines are recorded here, BEFORE the branches below; {} for any
        # other question. `stand["unread"]` (a line that looks like the form and cannot be read) keeps the gate
        # decision from being recorded by code: those lines go to the conductor, with the lines named (FR-8).
        # C1-4b (H3, FR-9): NOT for an answer to a question the seam raised (`offered`): that answer is a token of an option (`approve`),
        # and the stand-gap keys of the ORIGINAL answer (`stand_accept_cases`, `stand_accept_remedies`) must survive to `record_by_code`.
        # C2-7 (F-7c, K6): a word that is NOT a token of the options of a question the seam raised AT A GATE is a new answer of the gate
        # (cmp3 17:17: `approve` to a `retry` / `stop` question went round the seam). POSITION INVARIANT: the whole answer is compared
        # (a card line beside `approve` is no token); a token reads as before (`take_seam_answer`, the stand keys of the original
        # answer live on to `record_by_code`); every non-gate kind is untouched. Such an answer reads its card lines like a first answer
        # (`keep_earlier`: the keys of the earlier one are kept), is an approval only as `gate_approval` reads it, and is never
        # silent: what is neither goes whole to the conductor (`_unread_kept_gate`). The decision keeps everything said at the gate.
        seam_gate_words = (kind in GATE_KINDS and bool(asked.get("offered"))
                           and self.s0_normalize(words) not in self.seam_tokens(asked))
        gate_words, apply = words, {}
        if seam_gate_words:
            gate_words = self.combine_gate_words(asked, raw, words)
            if gate_words != words:
                apply = {"apply_words": words}          # the cards are read from this answer alone, never from the tail (t-891 F-2)
        asked_unread: list = []
        stand = ({} if asked.get("offered") and not seam_gate_words
                 else self.take_stand_gap_answers(kind, words, qtext, stage, dispatch, keep_earlier=seam_gate_words))
        if not (asked.get("offered") and not seam_gate_words):
            # P2 fix round (M1) POSITION INVARIANT: right AFTER the stand-gap reader, BEFORE every kind branch below. Its unread lines
            # join `stand["unread"]`, so no branch records gate B by code over a line nobody could read; the note names them.
            asked_lines = self.take_exploratory_answers(kind, words, qtext)
            if asked_lines:
                # GW1-33: the exploratory reader's unread lines are kept apart BEFORE the merge: they stay the conductor's
                # (`bug` beside `approve` is a contradiction), while the stand-gap reader's unread lines may ride an approval
                asked_unread = list(asked_lines["unread"])
                stand = {"recorded": stand.get("recorded", []) + asked_lines["recorded"],
                         "unread": stand.get("unread", []) + asked_lines["unread"],
                         "note": stand.get("note", "") + asked_lines["note"],
                         "hold": stand.get("hold", [])}
        # Set by `delivery()` alone, when it raises one of its three questions; consumed by whatever
        # answer comes next, so it cannot outlive its question (t-037's lesson about `stand_question`).
        # (a question the seam raised at S8 carries `offered`: the flag of an earlier delivery question cannot capture its answer)
        delivery_asked = bool(self.state.pop("delivery_question", None)) and kind == "conductor" and stage == "S8" \
            and not asked.get("offered")
        if delivery_asked and self.s0_normalize(words) == "no delivery":
            # The one answer to a delivery question that code reads (Lead's decision Q1, FR-9: a
            # person's "no delivery" has an executor): the delivery is closed as declined - a mark like
            # the one `continue` writes, so the story goes on to the retro - with no conductor call.
            # Every other word re-enters the delivery through the "S8 is done" branch below.
            self._decline_delivery(words)
        elif kind == "retro":
            self.state["retro_asked"] = True
            self.state["retro_feedback"] = "declined" if words.lower() in ("skip", "-", "no") else words
            self.owe_row("log_append.py", "--event", "escalated", "--agent", "qa-story", "--task", self.task,
                         "--reason", f"retro feedback: {self.state['retro_feedback']}", what="your feedback on the retro")
        elif kind == "package":
            self.take_package_answer(words, qtext, stage, dispatch)
        elif kind == "repair_limit":
            # t-698 (C1-5b1): the site's own question at an S5 repair limit - its tokens have executors (`_answer_repair_limit`), any
            # other word goes to the seam once. Raised by the gate in front of a critic's finish, so it carries no `offered`.
            self._answer_repair_limit(words, qtext, stage, dispatch)
        elif kind == "walk_supply":
            # TR3-10 D (item 14): the way question - its three tokens have executors (`_answer_walk_supply`), any other word goes to the
            # conductor once. POSITION INVARIANT: before the generic `offered` branch below (these questions carry no `offered`: L5);
            # the site's executors run, never the generic offered road.
            self._answer_walk_supply(words, qtext, stage, dispatch)
        elif kind == "data_change":
            # TR3-10 D (item 14): the data-change question - same position and invariant as `walk_supply` above (no `offered`: L5).
            self._answer_data_change(words, qtext, stage, dispatch)
        elif kind == "walk_account":
            # TR3-10 D (item 14): the account question - `by hand` / `go on` have executors (`_answer_walk_account`), `added` and any other
            # word go to the conductor once. POSITION INVARIANT: right after `walk_supply`, before the generic `offered` branch below
            # (this question carries no `offered`: L5); the site's executors run, never the generic offered road.
            self._answer_walk_account(words, qtext, stage, dispatch)
        elif kind == "open_work":
            # t-698 §22 FX-2 (C1-5b2): the site's own question at the end of an S7 `open_work` life - `close` / `stop` have executors
            # (`_answer_open_work`), any other word goes to the seam once (the `repair_limit` shape: this kind carries no `offered`).
            self._answer_open_work(words, qtext, stage, dispatch)
        elif kind == "exit_limit" and not asked.get("offered"):
            # t-764 (C1-5d2): the site's own question over an exit-gate refusal that survived the resume limit - its tokens have
            # executors (`_answer_exit_limit`), any other word goes to the conductor once. POSITION INVARIANT: after the closed
            # questions with their own executors, BEFORE the `offered` branch below (an exit-limit question carries no `offered`;
            # the conductor's options of this kind are read by `take_seam_answer`, which hands every token to the same executor).
            # A token sets `seam_token`: it is not words for a role (`_file_words`).
            seam_token = self._answer_exit_limit(words, qtext, stage, dispatch)
        elif kind == "code_close" and not asked.get("offered"):
            # C2-8 (t-745): the site's own question when the CODE closes a stage with no role and its record was refused - the tokens have
            # ONE executor (`_answer_code_close`); the conductor's options of this kind reach the same executor by `take_seam_answer`.
            # POSITION INVARIANT: after the closed questions with their own executors, before the `offered` branch (this question
            # carries no `offered`). A token sets `seam_token`: it is not words for a role (`_file_words`).
            seam_token = self._answer_code_close(words, qtext, stage, dispatch)
        elif kind == "ticket_changed":
            # B-364 R3 / FR-9: the changed-ticket question has three tokens, each with an executor (the S0 stop's
            # and the `package` question's pattern): code reads a token, never a meaning (FR-12) and calls no conductor.
            self.take_ticket_answer(words, qtext, stage, dispatch)
        elif kind == "ticket_auth":
            # The freshness check lost the tracker login (G3): `retry` / `go on` / `stop` have their executors in this method and
            # the rest goes to the seam. POSITION INVARIANT: only kind `ticket_auth` (raised by `ticket_look_failed` alone), before
            # the generic seam branch below, so an answer to it is never recorded as another question's token.
            self.take_ticket_auth_answer(words, qtext, stage, dispatch)
        elif kind == "arrival_not_waiting":
            # t-2181 PC-7 B2 (FR-9, FR-7, AR-22): the code was named for a story that was not waiting for it - `re-ground` / `ignore` /
            # `stop` have ONE executor (`_answer_arrival_not_waiting`: the token goes to `launch.arrival.answer`, read by `arrival_record`
            # in this same process), any other word goes to the conductor once. POSITION INVARIANT: only kind `arrival_not_waiting`
            # (raised by `arrival_record` alone, no `offered`), before the generic `offered` branch. A token sets `seam_token`.
            seam_token = self._answer_arrival_not_waiting(words, qtext, stage)
        elif kind == "first_look_dead":
            # t-2277 FL-5 (FR-9, FR-12, AR-24): the first look's `continue` / `stop` have ONE executor (`_first_look_answer`: the keys of now to
            # `first_look_continue`, the controller `await` for `stop`), any other word goes to the conductor once. POSITION INVARIANT: only kind
            # `first_look_dead` (raised by `first_look_step` alone, no `offered`), before the generic `offered` branch, so its tokens are never
            # read as another question's. A token sets `seam_token`.
            seam_token = self._first_look_answer(words, qtext, stage)
        elif kind == "first_look_same_code":
            # t-2277 FL-6 (FR-9, FR-12, AR-24): `wait` / `source` / `continue` have ONE executor (`_same_code_answer`; `continue` is the
            # operation of `first_look.dead`), any other word goes to the conductor once. POSITION INVARIANT: only kind
            # `first_look_same_code` (raised by `first_look_code_look` alone, no `offered`), before the generic `offered` branch. A token
            # sets `seam_token`: the answers row keeps it, and the code look of this process reads it (`wait` / `source`).
            seam_token = self._same_code_answer(words, qtext, stage)
        elif kind == "absent_side":
            # t-2559 (W2 B3, FR-9, FR-12, AR-24, AR-25): `not ours` / `relaunch` have ONE executor (`_answer_absent_side`), any other word goes
            # to the conductor once. POSITION INVARIANT: only kind `absent_side` (raised by `_act_await_implementation` alone, no `offered`),
            # before the generic `offered` branch, so its tokens are never read as another question's. A token sets `seam_token`.
            seam_token = self._answer_absent_side(words, qtext, stage)
        elif kind == "closed_held":
            # B-331 (C1-6a): the closed story's never-started work - `run again` / `leave` / `stop` have executors
            # (`_take_closed_held_answer`), any other word goes to the seam once. POSITION INVARIANT: only kind `closed_held`
            # (raised by `closed_held_person` alone), before the generic `offered` branch: the seam's own Person of this kind
            # carries `offered`, and its answers must reach the same executor. A token sets `seam_token`: it is not words
            # for a role (`_file_words`).
            seam_token = self._take_closed_held_answer(words, qtext, stage)
        elif kind == "environment" and stage in self.STAND_STAGES and self.state.get("stand_question") == stage:
            # The answer to `stand_check`'s question - and only to it: `stand_question` is set by `stand_check` alone, so the
            # questions of `environment_job` (kind `environment` too) never carry it and go on to the final `else` as before.
            # C1-6b (A7): the question is a seam question (it carries `offered`), so this branch stands BEFORE the generic `offered`
            # branch: the stand's NAME is the site's own door, `retry` / `go on` are carried out by `take_seam_answer`
            # (`_take_stand_answer`). A token sets `seam_token`: it is not words for a role (`_file_words`).
            seam_token = self._take_stand_answer(kind, stage, dispatch, qtext, words)
        elif kind == "stand_login" and self.state.get("login_question"):
            # The answer to `stand_login_gate`'s question - and only to it: `login_question` is set by `ask()` alone, from that
            # Person (t-037's lesson, as for the branch above). POSITION INVARIANT (as above): before the generic `offered` branch,
            # because the question carries `offered`; the typed record of `by hand` is written here, the pass by the seam's executor.
            seam_token = self._take_stand_login_answer(kind, stage, dispatch, qtext, words)
        elif kind == "gate_a_dry":
            # The answer to the `s6.gate_a_dry` question (`manual_gate_note`, raised by that site alone): `reapprove` has the site's
            # executor (`semantic_reopen`), `go on` / `stop` the seam's. POSITION INVARIANT: before the generic `offered` branch (the
            # question carries `offered`: `reapprove` is a word only this branch reads). A token sets `seam_token`.
            seam_token = self._take_gate_a_dry_answer(kind, stage, dispatch, qtext, words)
        elif kind in ("report_match", "delivery_check", "delivery"):
            # C1-6c (S8-S13 of the census): the delivery's own closed questions - tokens have executors, any other word goes to the
            # seam once. POSITION INVARIANT: only these kinds (each raised by its own builder alone), before the generic `offered` branch
            # and after the old `delivery_asked` branch above, which keys on kind `conductor` (a state an older driver wrote).
            seam_token = {"report_match": self._take_report_match_answer, "delivery_check": self._take_delivery_check_answer,
                          "delivery": self._take_delivery_answer}[kind](words, qtext, stage)
        elif kind == "s1_review" and self.record_review(words):
            self.state["pending_words"][dispatch] = words
        elif kind == "s1_gap" and self._answer_s1_gap(words, asked, qtext, stage, dispatch):
            self.state["pending_words"][dispatch] = words      # C2-9: the tokens and the fence have their executor; free words fall through
        elif (stage == "S0" and kind in ("halt", "refusal") and self.state.get("s0_block")
              and (not (self.task_root / "pipeline.json").is_file()
                   or self.state.get("s0_block") == "source_list")):
            # A stop of S0's own, answered before the story has a pipeline.json (`_keep_s0_words`: the words wait for the
            # next S0 step, no conductor and no judge). INVARIANT: this position keeps every
            # answer on today's paths the moment pipeline.json exists, and gate, retro and s1
            # kinds never reach it - it is `halt`/`refusal` at S0 with an open S0 block, only.
            # The ONE exception after pipeline.json exists is the `source_list` block: the person's list
            # of sources not to read, given on a command line of a story whose sources were already
            # collected (t-172 C1), is asked at S0 and read by `skip_sources_late`, not by a conductor.
            self._keep_s0_words(words)
        elif asked.get("offered") and not seam_gate_words:
            # A question the seam (`no_move`) raised, and only such a question: `ask()` writes `offered` from its Person alone, so
            # no other question's answer is captured here (`s1_review` never carries it). POSITION INVARIANT:
            # after the branches of the closed questions with their own executors above, before the plain "stage is done" branch.
            # At a gate only a TOKEN of the options comes here; any other word falls to the gate branches below (C2-7, `seam_gate_words`).
            seam_token = self.take_seam_answer(words, asked, qtext, stage, dispatch)
        elif kind in ("conductor", "refusal") and stage and \
                (self.pipeline().get("stages") or {}).get(stage, {}).get("status") == "done":
            # The stop was passed before the person answered (the conductor closed the stage
            # itself and still asked): the words go on the record, the loop goes on.
            self.after_close(stage, words)
        elif kind in ("conductor", "refusal") and self.s1_exit_gate(qtext) and self.record_s1(qtext, words):
            dispatch = self.s1_exit_gate(qtext)
            self.state["pending_words"][dispatch] = words
        elif kind == "questions":
            # A threshold stop (t-113 B2, R17): tokens are recorded by code and the words go to the
            # role's own session - no conductor, no judge. Only this kind reaches it.
            self.take_question_answer(stage, dispatch, words)
        elif kind == "halt" and stage == "S1" and self.s0_normalize(words) == "not built yet" and self.s1_has_no_diff():
            # t-2181 PC-7 B3 (FR-9, AR-19): the `not built yet` answer of `s1.no_diff` - the twin of the `s0.no_change` answer - records the
            # side before the words go to the scout. POSITION INVARIANT: only kind `halt` at S1 with the manifest's `none` source, the WHOLE
            # answer (`not built yet please` is other words and takes the unread road below); before `judged_reply` / `unread`, so the
            # story parks after S5 instead of reading the default `product: real`.
            self._answer_s1_not_built(words, dispatch)
        elif kind == "halt" and self.s0_normalize(words) == "stop":
            # The halt question's one token (`halt` / `s1.no_diff` of question-prices.json). POSITION INVARIANT: only kind `halt`,
            # the WHOLE answer, and BEFORE `judged_reply` / `unread` - the conductor is not called and the words are not filed
            # for the role (no `pending_words`): `stop please` is other words and takes the unread road below, as today.
            self.answer_row(f"{stage} halt (stop): ", words.strip(), what="your answer at the halt")
            raise self.held_question(self.stop_held("If you want the role to go on after all, answer in your own words."))
        elif kind in ("halt", "s1_review"):
            self._unread_halt_or_review(kind, stage, dispatch, qtext, words)
        elif (kind in ("gate_A", "gate_B")
              and (not stand.get("unread") or self.gate_lines_over_approval(kind, gate_words, stand, asked_unread))
              and self.record_by_code(kind, stage, gate_words, **apply)):
            # A gate decision is one command with the person's words in it — not a problem, so not
            # a conductor session. What the gate packet's items still need is decided by the loop:
            # a block that outlives the decision comes back as its own refusal, with its own owner.
            # GW1-33 POSITION INVARIANT: lines nobody could read ride an APPROVAL only through `gate_lines_over_approval` (gate A
            # only), and the gate A controller still refuses an approval over an open item (then this branch is not taken: the old
            # road, the whole answer kept for the conductor). Gate B and held lines never ride. The unread lines are told as "not understood", whole in the answer's row, never as accepted.
            self.state["pending_words"].pop(dispatch, None)
            if stand.get("unread"):
                lines = [str(line) for line in stand["unread"]]
                print(f"gate {kind[-1]}: recorded by code; {len(lines)} line(s) of the answer were not understood and are not applied:")
                print("\n".join(f"  - {line}" for line in lines[:20]) + (f"\n  ... and {len(lines) - 20} more" if len(lines) > 20 else ""))
                self.answer_row(f"{stage} {kind} lines not understood: ", "\n".join(lines), what="the lines of your answer that were not understood")
        elif kind == "stand_identity" and self.state.get("build_question"):
            # The answer to `build_check`'s question - and only to it (t-300 N1b): `build_question` is set by `ask()` alone,
            # from that Person, so no other question's answer comes here (t-037's lesson, as for the two branches above).
            # The closed forms are read and executed by code, the rest goes to the conductor: `take_build_answer`.
            self.take_build_answer(words, qtext, stage, dispatch)
        else:  # gate_A, gate_B, conductor, refusal — a block that outlived the recording
            self._unread_kept_gate(kind, stage, dispatch, qtext, gate_words, stand.get("note", ""), **apply)
        # POSITION INVARIANT (t-217 / F-cmp2-22, FR-16, FR-7, FR-8): after every branch above. A person's words are resumed (the
        # `pending_words` consumers) only into the dispatch the question was about - the FIELD `asked.dispatch`, never an id read
        # out of the question's text - and when unsure they are filed to NO dispatch: the boundary then asks again, with ask()'s
        # FR-7 block, never to a wrong one. `dispatch` is the one the s1_exit_gate branch may have reassigned (E4); the seam token
        # reaches `_file_words` (a token of a seam question is not words for a role).
        self._file_words(kind, dispatch, asked, words, qtext, seam_token)
        self.record_answer_row(self.s0_normalize(words) if seam_token else "", dispatch)
        if asked.get("deferred_n") is not None:
            # RN1-24 (E10, E12): the answer to a DEFERRED question was read above by the original question's own executors. Its stage (S6)
            # is closed already, so a `retry` (the move `person_does`, read from `asked.options`, never from the word) found no step to
            # run again there: it is carried out here as the seam's rework of exactly the held cases (`record_seam_rework`; S7 and
            # gate B follow it again). POSITION INVARIANT: after every branch and the filing of the words, BEFORE `asked` is cleared, so
            # a rework that cannot be recorded brings the question back (`held_question`) with the item still owed, never a lost answer.
            item = next((i for i in self.deferred_items() if i["n"] == asked["deferred_n"]), None)
            closed = (self.pipeline().get("stages") or {}).get(stage, {}).get("status") == "done"
            move, token = self.seam_tokens(asked).get(self.s0_normalize(words)), self.s0_normalize(words)
            if item and closed and move == "go_on_as_is":
                # `go on` / `by hand` after the stage is closed: `after_close` only recorded the words; the decision is carried out here
                # (the held cases' request.json, the pass). A `retry` whose cause is not fixed is the branch below, unchanged.
                self.deferred_decision(item, token, words, asked, stage, self.answer_file())
            if item and closed and move == "person_does":
                clean, rule = NM.check_args({"stage": "S6", "role": "qa-runner", "cases": list(item.get("holds") or []),
                                             "cause": "question_answer"}, self.no_move_facts({"kind": kind}))
                if clean is None:
                    # remains: the person's own question comes back with the reason and the item stays owed (the `record_seam_rework` pattern)
                    raise self.held_question("Your choice to check these again could not be carried out, so nothing was sent back.", rule)
                self.record_seam_rework(clean, self.answer_file())
            self.state["deferred"] = [i for i in self.deferred_items() if i["n"] != asked["deferred_n"]]
            if not self.state["deferred"]:
                self.state.pop("deferred_round", None)
        # Cleared the way it was opened: the flag, then the file. Between the two the question
        # reads as answered-but-not-filed, which is the half `reconcile_question` files; the
        # other order would re-ask a question already recorded.
        # B-20 N5 (AR-22): the producer of `stuck_asked`; its reader is the stuck seam of the loop. Only the answer to the stuck question itself
        # (same stage, same kind) is recorded under its step's signature; any other answer drops a stale pending mark.
        pending = self.state.pop("stuck_pending", None)
        if isinstance(pending, dict) and pending.get("stage") == stage and pending.get("kind") == kind:
            self.state.setdefault("stuck_asked", {})[str(pending.get("signature") or "")] = {
                "answer": " ".join(words.split())[:100], "at": _now()}
        self.state["asked"] = {}
        self.save_state()
        self.drop_standing()                   # E3: the question about the refusal is closed (the answer was read above)
        if question.is_file():
            question.replace(self.question_path(answered=True))

    # t-667 D14: the BODIES of `take_answer`'s branches. The ladder, its side-effecting conditions and its order stay in
    # `take_answer`; a body runs only when its condition holds there, and returns nothing.
    def _decline_delivery(self, words: str) -> None:
        """t-667 D14: a person's "no delivery" (Lead's decision Q1, FR-9: it has an executor): the delivery is closed as declined -
        a mark like the one `continue` writes, so the story goes on to the retro - with no conductor call."""
        said = self.s0_quote(words)
        did = f"nothing outward: the person declined the delivery ({said})"
        # the person's words, whole, in a file of their own: the `mr` order is called off WITH them (`settle_mr_from_mark`, FR-8, F-7)
        path = self.words_file(words, "delivery")
        self.state["delivery"] = {"done": True, "at": _now(), "action": "declined_by_person", "did": did,
                                  "words_file": str(path) if path else ""}
        self.answer_row("S8 delivery: ", words.strip(), what="your answer about the delivery")
        self.journal_run({"kind": "delivery", "outcome": "declined_by_person"})
        print(f"delivery: {did}")

    def _keep_s0_words(self, words: str) -> None:
        """t-667 D14: a stop of S0's own, answered before the story has a pipeline.json: there is no `waiver.py` to write into,
        so a conductor could only read the words and hand back the same block (S0 "promised `go on` and never read the answer").
        The words wait for the next S0 step, which reads them against the tokens the stop offered (`s0_read_word`); no
        conductor and no judge."""
        block = self.state["s0_block"]
        self.state["pending_words"]["S0"] = words
        self.answer_row(f"S0 {block}: ", words, what="your answer at the start of the story")
        print(f"S0 {block}: the answer is kept and read in the next S0 step")

    def _answer_arrival_not_waiting(self, words: str, qtext: str, stage: str) -> bool:
        """t-2181 PC-7 B2: the answer to `arrival.not_waiting` (FR-9: each token has an executor; FR-12: code reads a token, never a
        meaning). The FIRST non-empty line is the token (`s0_normalize`); the whole answer is the person's words, by FILE. A token is
        written to `launch["arrival"]["answer"]` and `arrival_record` carries it out in the same process (`re-ground`: the arrival and the
        rework it owes; `ignore`: the word is dropped; `stop`: nothing runs, exit 0) - the question is never asked again with the same
        text (FR-7). A token with no pending word (nothing waits for it any more) is said and taken. Any other answer is new words:
        the seam, with `re-ground` / `ignore` as its doors. True = a token was taken."""
        first = next((line for line in str(words).splitlines() if line.strip()), "")
        token = self.s0_normalize(first)
        if token not in self.ARRIVAL_TOKENS:
            self.unread("arrival_not_waiting", stage, "", qtext, words=words, doors=("re-ground", "ignore"),
                        lead=self.unread_lead(words), again=lambda said: self.held_question(said))
            return False
        pending = (self.state.get("launch") or {}).get("arrival")
        if not isinstance(pending, dict):
            print(f"{self.task}: no word about the code is waiting any more; your answer ({token}) changes nothing")
            return True
        pending["answer"] = token
        self.save_state()
        return True

    def _first_look_answer(self, words: str, qtext: str, stage: str) -> bool:
        """t-2277 FL-5: the answer to `first_look.dead` (FR-9: each token has an executor; FR-12: code reads a token, never a meaning). The
        FIRST non-empty line is the token (`s0_normalize`), the whole answer is the person's words, by FILE. `continue`: `controller.py
        --operation first_look_continue --words-file <the words> --source-head H --register-hash R` with `(H, R) =
        first_look.current_keys` - the keys of NOW, so a later head or register asks again (FR-7). `stop`: the controller `await` with cause
        `first_look_stop` held from S3, through the one body of the hold (`_act_await_implementation`, which prints the first look's own
        packet for that cause, FL-6); its `Stop` is taken here (take_answer files the answer and clears the question first) and the loop's next `where` answers
        `awaiting_implementation` and ends the run, exit 0. Any other answer is new words for the conductor, once (`unread`). A command the
        controller refuses brings the question back with its words (`held_question`). True = a token was taken. ANY answer marks the walk as
        asked (`first_look.mark_asked`): the question is not put again for this walk, whatever the words were (B3, FR-7) - it is marked HERE and
        not when it is raised, so a question nobody has answered yet still comes back after a restart (AR-25)."""
        import first_look as FL
        FL.mark_asked(self.task_root)
        token = self.s0_normalize(next((line for line in str(words).splitlines() if line.strip()), ""))
        if token not in ("continue", "stop"):
            self.unread("first_look_dead", stage, "", qtext, words=words, doors=("continue", "stop"),
                        lead=self.unread_lead(words), again=lambda said: self.held_question(said))
            return False
        self.answer_row(f"{stage} first look ({token}): ", words.strip(), what="your answer about the first look")
        try:
            if token == "continue":
                self._first_look_continue(stage)
            else:
                try:
                    self._act_await_implementation({"action": "await_implementation", "cause": "first_look_stop", "held_from": "S3"})
                except Stop:
                    pass
        except Refusal as refusal:
            # remains: the person's own question comes back with the reason (a refused carrying-out); nothing was changed
            raise self.held_question("Your answer could not be carried out, so nothing changed.", refusal.text)
        return True

    def _same_code_answer(self, words: str, qtext: str, stage: str) -> bool:
        """t-2277 FL-6: the answer to `first_look.same_code` (FR-9: each token has an executor; FR-12: code reads a token, never a meaning).
        The FIRST non-empty line is the token (`s0_normalize`), the whole answer is the person's words, by FILE. `continue` is the SAME
        operation as the `continue` of `first_look.dead` (`first_look_continue` with the keys of now, PC-6); `wait` and `source` change
        nothing here: `first_look_code_look` of this same process reads the row this answer leaves in `driver-answers.jsonl` and prints
        the packet / the restart command (exit 0). Any other answer is new words for the conductor, once (`unread`). A command the
        controller refuses brings the question back with its words (`held_question`). True = a token was taken. The row of the answer
        carries that first-line token (F1, critic t-2528), so a second line of the person's words changes nothing about the executor."""
        token = self.s0_normalize(next((line for line in str(words).splitlines() if line.strip()), ""))
        if token not in ("wait", "source", "continue"):
            self.unread("first_look_same_code", stage, "", qtext, words=words, doors=("wait", "source", "continue"),
                        lead=self.unread_lead(words), again=lambda said: self.held_question(said))
            return False
        self.answer_row(f"{stage} first look, the code ({token}): ", words.strip(), what="your answer about the code")
        # F1: the row carries the token THIS executor read (the first line), never the whole normalized answer: `first_look_code_look`
        # and the date line of the next question read the row by that token, so `source` + a second line still prints the command
        self.record_answer_row(token)
        if token == "continue":
            try:
                self._first_look_continue(stage)
            except Refusal as refusal:
                # remains: the person's own question comes back with the reason (the `_first_look_answer` pattern); nothing was changed
                raise self.held_question("Your answer could not be carried out, so nothing changed.", refusal.text)
        return True

    def _answer_absent_side(self, words: str, qtext: str, stage: str) -> bool:
        """t-2559 (W2 B3): the answer to `awaiting.absent_side` (FR-9: each token has an executor; FR-12: code reads a token, never a
        meaning). The FIRST non-empty line is the token (`s0_normalize`), the whole answer is the person's words, by FILE. `relaunch`: nothing
        changes - the hold stands and the loop's next `where` prints the packet and ends with exit 0, as before. `not ours`: `_side_not_ours`.
        Any other answer is new words for the conductor, once (`unread`). A refused carrying-out brings the question back with its words
        (`held_question`), nothing half-done is lost (every step is repeatable). True = a token was taken."""
        token = self.s0_normalize(next((line for line in str(words).splitlines() if line.strip()), ""))
        if token not in self.ABSENT_SIDE_TOKENS:
            self.unread("absent_side", stage, "", qtext, words=words, doors=self.ABSENT_SIDE_TOKENS,
                        lead=self.unread_lead(words), again=lambda said: self.held_question(said))
            return False
        self.answer_row(f"{stage} absent side ({token}): ", words.strip(), what="your answer about the missing part")
        self.record_answer_row(token)
        name = str(self.state.get("absent_side") or "")
        if token == "not ours":
            try:
                self._side_not_ours(name, words.strip())
            except Refusal as refusal:
                # remains: the person's own question comes back with the reason (the `_same_code_answer` pattern); nothing was lost
                raise self.held_question("Your answer could not be carried out, so nothing changed.", refusal.text)
        else:
            # `relaunch` (t-2562 B-1/B-2): recorded for THIS hold only, so the loop's next `where` asks the next side with no answer and a
            # later process re-offers with a changed lead; nothing else changes. This process asks nothing more once every side answered.
            record = self.state.get("absent_side_answers")
            if isinstance(record, dict) and isinstance(record.get("sides"), dict) and name:
                record["sides"][name] = {"token": token, "at": _now()[:10]}
            self._absent_answered_here = True
        self.state.pop("absent_side", None)
        return True

    def _side_not_ours(self, name: str, words: str) -> None:
        """t-2559 (W2 B3): the side `name` is another team's. In THIS order, each step repeatable on a replay: (1) the project's record
        through `_keep_sides_answer` (the one writer of the registry row, by the person's words; `--no-trace` keeps it in the story only, an
        unreadable registry is said in words and the answer stays in the story, AR-28); (2) the story's record - `deliverable false`, reality
        `substituted`, `source person` through ONE `stage_done.py` call (the writer of `pipeline.sides`, AR-14), which also carries the
        lines of (1) as `--warn`, so the report and gate A read them (t-2562 F-1, AR-22); the story no longer parks;
        (3) the hold is lifted by the controller's own `arrive` naming this side (no source: no code arrived). Other sides are untouched (they
        park the story again on the next `where`, one question each). A write that is refused is a `Refusal`."""
        if not name:
            raise Refusal("the part of the product this answer is about is not recorded, so nothing was changed; start the story again")
        import contract
        since = str(contract.awaiting(self.pipeline()).get("since") or "")
        lines = self._keep_sides_answer(name, "another team's", words=words, where="the answer to the question about the missing side after S5")
        sets = self.side_set_args(name, reality=self.SIDE_SUBSTITUTED, deliverable="false", source="person", at=_now())
        self.py("stage_done.py", "--task", self.task, *[part for item in sets for part in ("--set", item)],
                *[part for line in lines for part in ("--warn", line)], check=True)
        self._arrive([name], {}, ["not ours", name, since])
        print(f"{self.task}: `{name}` is another team's at your word; the wait is over and the tests go on against a stand-in for it")

    def _first_look_continue(self, stage: str) -> None:
        """THE `continue` of the first look (FR-9, AR-15), for both of its questions (`first_look.dead`, `first_look.same_code`): the
        controller operation `first_look_continue` with the person's words (by FILE) and the keys of NOW (`first_look.current_keys`), so a
        later head or register asks again (FR-7). A missing words file or a refusal of the controller is a `Refusal` the caller turns into the
        held question."""
        import first_look as FL
        file = self.answer_file()
        if not file:
            raise Refusal("first look: the answer has no words file, so `continue` was not recorded; the question stays")
        heads, register = FL.current_keys(self.task_root)
        self.controller("first_look_continue", "--words-file", str(self.task_root / file), "--source-head", heads, "--register-hash", register)
        print(f"{stage}: first look: your `continue` is recorded for these heads and this register")

    def _answer_s1_not_built(self, words: str, dispatch: str) -> None:
        """t-2181 PC-7 B3: the `not built yet` answer of `s1.no_diff`, the twin of the `s0.no_change` one (AR-19). The side `product` is
        recorded absent, deliverable, `source: person` through `stage_done.py --set` (the writer of `pipeline.sides`, AR-14; the keys of
        `s0_sides_sets`), so the story parks after S5; then the words go to the scout as on every halt (`pending_words`): it goes on with
        the requirements only. A refused write is a `Refusal` (the seam asks), and nothing was filed for the scout."""
        import contract
        sets = self.side_set_args("product", reality=contract.PARKING_REALITY, deliverable="true", source="person", at=_now())
        self.py("stage_done.py", "--task", self.task, *[part for item in sets for part in ("--set", item)], check=True)
        self.state["pending_words"][dispatch] = words

    def _unread_halt_or_review(self, kind: str, stage: str, dispatch: str, qtext: str, words: str) -> None:
        """t-667 D14: the answer to a halt or an S1 source review that no executor of code reads: the conductor records it, the
        words are filed for the role.

        HF2-7 (B2): a halt at S2-S4 over a register that holds questions is answered BY LINES (the halt text shows the open questions
        and how to answer them by id), so the lines are recorded by CODE first (`question_register.record_answers`, the ONE writer
        of answers, AR-14) and the words are journalled as the person's (`human_answer`) in the same move. When every line was a
        token and none was left unread (H31) the conductor is not called and the judge is not asked - the words wait for the
        role (`pending_words`) and nothing else is owed (FR-48, FR-55). Otherwise the conductor reads what code could not, and is
        told what was already recorded (it must not record it again) and which command records an answer to a question."""
        recorded = self.record_halt_words(stage, words) if kind == "halt" else None
        if recorded is not None and recorded["all_tokens"] and not recorded["unread"]:
            self.state["pending_words"][dispatch] = words
            return
        read = self.judged_reply(qtext, words, kind)
        commands = ("assess / accept-gap / review --record / log_append human_answer|escalated / stage_done --set / waiver.py"
                    if recorded is None else "assess / accept-gap / review --record / question_register.py / stage_done --set / waiver.py")
        self.unread(kind, stage, dispatch, "The person answered a " + ("source review" if kind == "s1_review" else "halt") +
                                 f" of dispatch {dispatch} at {stage}. Record what they decided with the "
                                 f"factory's own commands ({commands}), nothing else; the role "
                                 "itself is resumed by the driver afterwards."
                                 + ("" if recorded is None else
                                    " The factory read their lines against the register's questions by code - recorded by code: "
                                    + (", ".join(recorded["recorded"] + [f"{q} (until the report)" for q in recorded["deferred"]]) or "nothing")
                                    + "; do not record these again, and do not journal their words again (the driver did). "
                                    + ("Not read, still open: " + "; ".join(recorded["unread"] + recorded["unknown_ids"]) + ". "
                                       if recorded["unread"] or recorded["unknown_ids"] else "")
                                    + f"An answer they gave to a question in other words is recorded with question_register.py "
                                    f"(--answer QID --reading <letter> | --not-needed QID | --defer QID, with --words-file, --where \"{stage} stop\", "
                                    "--by conductor and the --register-hash that --show prints).")
                                 # `s1_review` gets no options: `record_review` records ANY words as the S1 review before
                                 # the conductor sees them (C1-3 owns that text); a `halt` re-raises as a `halt` (C1-2, C1).
                                 + ("" if kind == "s1_review" else " " + MOVES_RULE + " " + OWN_TOKEN_RULE)
                                 + "\n\n## The question\n" + qtext[:6000]
                                 + (PRE_FILLED + read if read else ""),
                                 words=words)
        self.state["pending_words"][dispatch] = words

    def _delivery_token(self, kind: str, stage: str, qtext: str, words: str, doors: tuple, reenter: bool = False) -> str:
        """The token of an answer to one of the delivery's closed questions, or '' (C1-6c). The FIRST non-empty line is the token
        (`s0_normalize`, A6: a typed carrier, never a token read out of prose); the whole answer is the person's words, by FILE. `stop`
        holds the question; `no delivery` is today's declined mark (`_decline_delivery`); any other word is new words: they go on the
        journal (the delivery step reads them) and then, by default, to the seam, which offers `doors` back (D-0041, edge 7).
        `reenter` (the delivery question alone, F7): the delivery step IS a conductor session that reads their words, so the words
        re-enter it as they always did and no second session reads them first."""
        first = next((line for line in str(words).splitlines() if line.strip()), "")
        token = self.s0_normalize(first)
        if token not in (*doors, "stop"):
            # C-F3 (t-1228): the journal row is the ONLY road of these words to the delivery session (`person_answers`, `reenter`), so a
            # failed write is OWED (`answer_row`): `owed_rows_step` writes it again before the delivery step is built, a second failure
            # is the seam's question - the words never reach a session that cannot read them
            self.answer_row(f"S8 {kind}: ", words.strip(), what="your words about the delivery")
            if not reenter:
                self.unread(kind, stage, "", qtext, words=words, doors=doors, lead=self.unread_lead(words),
                            again=lambda said: self.held_question(said))
            return ""
        self.answer_file()
        self.record_answer_row(token)
        if token == "stop":
            # remains: `stop` holds the question as every closed question does (`stop_held`, FR-7); nothing runs
            raise self.held_question(self.stop_held(self.delivery_stop_door(doors)))
        if token == "no delivery":
            self._decline_delivery(words)
        else:
            self.answer_row(f"S8 {kind} ({token}): ", words.strip(), what="your answer about the delivery")    # owed on a failed write (C-F3)
        return token

    @staticmethod
    def delivery_stop_door(doors: tuple) -> str:
        """C-F1 (FR-2, FR-10): the sentence after `stop` on a delivery question names each door for what it does - the doors that carry
        the delivery on, then `no delivery`, which ENDS it (never listed as a way to get the delivery). A question with no carrying door
        (the report that does not match) names only the one that ends it."""
        carry = [d for d in doors if d != "no delivery"]
        end = "to end the delivery here with nothing sent, answer `no delivery`."
        return ("To carry on, answer " + " or ".join(f"`{d}`" for d in carry) + "; " + end) if carry else end[0].upper() + end[1:]

    def _take_delivery_answer(self, words: str, qtext: str, stage: str) -> bool:
        """`s8.delivery`: `go on` and `retry` are TWO records (`delivery_choice`: go_on | retry, FR-9) and both re-enter the delivery
        step (it is first told what already went out); `no delivery` / `stop` as every delivery question."""
        token = self._delivery_token("delivery", stage, qtext, words, ("go on", "retry", "no delivery"), reenter=True)
        if token in ("go on", "retry"):
            self.state["delivery_choice"] = {"choice": token.replace(" ", "_"), "token": token, "words_file": self.answer_file(), "at": _now()}
            print(f"delivery: {token} - the delivery step goes on with your words")
        return bool(token)

    def _take_delivery_check_answer(self, words: str, qtext: str, stage: str) -> bool:
        """`s8.delivery_check`: `retry` records nothing - the next step of the loop runs the check again; `no delivery` / `stop` as above."""
        token = self._delivery_token("delivery_check", stage, qtext, words, ("retry", "no delivery"))
        if token == "retry":
            print("delivery: the check runs again")
        return bool(token)

    def _take_report_match_answer(self, words: str, qtext: str, stage: str) -> bool:
        """`s8.report_match`: `no delivery` is the declined mark (the report stays as it is); `stop` holds the question. `rebuild` is
        not offered (handoff Q1): any word that is not a door goes to the seam."""
        return bool(self._delivery_token("report_match", stage, qtext, words, ("no delivery",)))

    CLOSED_HELD_TOKENS = ("run again", "leave", "stop")

    def _take_closed_held_answer(self, words: str, qtext: str, stage: str) -> bool:
        """The answer to the `closed.held` question (C1-6a, FR-9: each token has an executor, FR-12: code reads a token, never a
        meaning). The FIRST non-empty line of the answer is the token (`s0_normalize`); the whole answer is the person's words, by
        FILE. `run again` - the controller's `reopen_story` for exactly the dispatches the question named (the existing `next` ->
        `relaunch` loop then starts them, one at a time, behind the stand and build checks); `leave` - `leave_unlaunched` for the
        same set; `stop` - nothing runs, the question is held. Anything else is new words: the seam, with `run again` / `leave` as
        its doors. A refusal of the controller (the work started meanwhile, the story was reopened) is said and the loop asks again
        from `next`: the question comes back CHANGED (edge 9), never a move on a false precondition. True = a token was taken."""
        record = self.state.pop("closed_held", None) or {}
        ids = [str(item) for item in record.get("dispatch_ids") or []]
        first = next((line for line in str(words).splitlines() if line.strip()), "")
        token = self.s0_normalize(first)
        if token not in self.CLOSED_HELD_TOKENS:
            self.state["closed_held"] = record
            self.unread("closed_held", stage, "", qtext, words=words, doors=("run again", "leave"),
                        lead=self.unread_lead(words), again=lambda said: self.held_question(said))
            return False
        # A6: the typed carrier - the audit row holds the TOKEN (`run again` / `leave` / `stop`), never the whole answer read back;
        # the words file is made first, so the row names the file that holds the whole answer (the row is written once)
        self.answer_file()
        self.record_answer_row(token)
        # remains: the journal row of the person's words (FR-8); the answer is carried out whatever the row does
        self.py("log_append.py", "--event", "human_answer", "--task", self.task,
                "--notes", _answer_note(f"closed story, work that never started ({token}): ", words.strip()))
        if token == "stop":
            self.state["closed_held"] = record
            # remains: `stop` holds the question as every closed question does (`stop_held`, FR-7); nothing runs
            raise self.held_question(self.stop_held("If you want the work to run or be left after all, answer `run again` or `leave`."))
        if not ids:
            # an older state names no set: nothing is guessed (FR-41) - the next entry builds the question from `next`
            print("closed story: the question named no dispatches; it is asked again from the controller's own list")
            return True
        operation = "reopen_story" if token == "run again" else "leave_unlaunched"
        try:
            got = self.controller(operation, "--dispatch", ",".join(ids), "--words-file", str(self.task_root / self.answer_file()))
        except Refusal as refusal:
            print(f"closed story: your choice ({token}) could not be carried out and nothing was changed; the question comes back "
                  f"as the story stands now ({refusal.text[-300:]})")
            return True
        print(f"closed story: {'the story is reopened and the work starts' if token == 'run again' else 'the work is left'} "
              f"({', '.join(got.get('dispatch_ids') or ids)})")
        return True

    def _words_door(self, stage: str, block: str) -> str:
        """The command the conductor is told to record a person's free words with, for `block` at `stage`: the words by FILE (the file of
        the answer being read, `answer_file`), never typed inline (axis 5; the S5 class of the inline `--decision`). The command is the
        site's own; the file part is `person_words.door`, the one renderer of the words door (no second text of the option here)."""
        return person_words.door(f"python {self.scripts / 'waiver.py'} --task {self.task} --stage {stage} --block \"{block}\"",
                                 path=str(self.task_root / self.answer_file()))

    def _take_stand_answer(self, kind: str, stage: str, dispatch: str, qtext: str, words: str) -> bool:
        """The answer to `stand_check`'s question (t-667 D14; C1-6b A7). The code reads only what it can name (FR-12): a configured
        stand's NAME (the site's own door: the next entry probes it), `retry` and `go on` - the tokens the question offers, carried
        out by the seam's own executors (`take_seam_answer`: `person_does`; `go_on_as_is` + the block `stand not confirmed`, which S5 and
        S6 both read, as `waiver.py --words-file`) - and anything else, which is the person's own words and goes to the conductor with
        the command to record them if they mean it (FR-4). True = the answer was a name or a token."""
        self.state.pop("stand_question", None)
        asked = self.state.get("asked") or {}
        if not asked.get("offered"):      # a question an older driver asked (temporal, edge 13): the same tokens with the same moves
            asked = dict(asked, options=[{"token": t, "move": self.SITE_MOVES[t]} for t in ("retry", "go on")], block=waiver.STAND_NOT_CONFIRMED_BLOCK)
        token = self.s0_normalize(words)
        named = next((name for name in self.stand_names() if self.s0_normalize(name) == token), "")
        if named:
            self.py("stage_done.py", "--task", self.task, "--set", f"environment={named}",
                    "--set", "environment_pending=true", check=True)
            self.answer_row(f"stand at {stage}: ", words, what=f"the person's words naming the stand at {stage}")
            print(f"{stage}: the stand is `{named}`; it is checked when the stage starts")
            return True
        if token in self.seam_tokens(asked):
            return self.take_seam_answer(words, asked, qtext, stage, dispatch)
        self.unread(
            kind, stage, dispatch,
            f"The person answered the driver's question about the stand at {stage}: no stand "
            "is confirmed for the story, and their words are below. If they say to go on "
            "without a stand, record them with exactly this one command and nothing else:\n"
            f"{self._words_door(stage, waiver.STAND_NOT_CONFIRMED_BLOCK)}\n"
            + MOVES_RULE + " " + OWN_TOKEN_RULE + "\n\n## The question\n" + qtext[:6000],
            words=words, block=waiver.STAND_NOT_CONFIRMED_BLOCK)
        return False

    def _take_stand_login_answer(self, kind: str, stage: str, dispatch: str, qtext: str, words: str) -> bool:
        """The answer to `stand_login_gate`'s question (t-667 D14; C1-6b A6/A7). `retry` and `go on` are carried out by the seam's own
        executors; `by hand` is the same pass (`go_on_as_is` + the block `stand login missing`) plus the site's TYPED record of the
        choice (`state["login_choice"]`: the token and the words it was made with), which `stand_login_gate` reads to write
        `refused.by: person_checks` - `go on` and every pass the conductor recorded from free words leave `left_unchecked`. Anything else
        is the person's own words and goes to the conductor with the command to record them (FR-4). True = a token was taken."""
        self.state.pop("login_question", None)
        asked = self.state.get("asked") or {}
        if not asked.get("offered"):      # a question an older driver asked (temporal, edge 13): the same tokens with the same moves
            asked = dict(asked, options=[{"token": t, "move": self.SITE_MOVES[t]} for t in ("retry", "by hand", "go on")], block=self.STAND_LOGIN_BLOCK)
        token = self.s0_normalize(words)
        if token in ("by hand", "go on") and token in self.seam_tokens(asked):
            self.state["login_choice"] = {"token": token, "words": " ".join(words.replace(self.BOM, "").split()), "at": _now()}
        elif token in self.seam_tokens(asked):
            return self.take_seam_answer(words, asked, qtext, stage, dispatch)
        else:
            self.state.pop("login_choice", None)
            self.unread(
                kind, stage, dispatch,
                f"The person answered the driver's question about the stand's sign-in account at {stage}: the "
                "checks an agent makes by hand on the product's screens cannot start without it, and their words "
                "are below. If they say they will check those screens themselves, or to go on without them, record "
                "their words with exactly this one command and nothing else:\n"
                f"{self._words_door('S6', self.STAND_LOGIN_BLOCK)}\n"
                + MOVES_RULE + " " + OWN_TOKEN_RULE + "\n\n## The question\n" + qtext[:6000],
                words=words, block=self.STAND_LOGIN_BLOCK)
            return False
        return self.take_seam_answer(words, asked, qtext, stage, dispatch)

    def _take_gate_a_dry_answer(self, kind: str, stage: str, dispatch: str, qtext: str, words: str) -> bool:
        """The answer to the `s6.gate_a_dry` question (C1-6b, §3.3; FR-9: each token has an executor, FR-12: a token, never a meaning).
        `reapprove` (offered only when it can run) - the controller's `semantic_reopen` with the person's words as its reason and the
        cases the question named as its scope: S4 goes back to pending and the gate A decision on those cases is stale, so gate A is asked
        again and its `approve` applies the card answers. A refusal of the controller (a role runs, no current gate A) is said, nothing
        was changed, the question comes back. `go on` / `stop`: the seam's executors (`waiver.py --words-file` for the block
        `gate A recorded dry`; `stop_held`). Any other word is new words: the seam, with `reapprove` offered back as its door."""
        asked = self.state.get("asked") or {}
        offered = [str(item) for item in asked.get("offered") or ()]
        token = self.s0_normalize(words)
        if token == "reapprove" and "reapprove" in offered:
            scope = [str(case) for case in (self.state.get("gate_a_dry") or {}).get("cases") or []]
            self.answer_file()
            self.record_answer_row(token)
            self.answer_row("gate A recorded dry (reapprove): ", words.strip(), what="the person's choice to approve gate A again")
            if not scope:
                # remains: the person's own question comes back with the reason; nothing was changed (an older state names no cases)
                raise self.held_question("Your choice to approve gate A again could not be carried out: the question named no cases, so "
                                         "nothing was changed.")
            try:
                self.controller("semantic_reopen", input_data={
                    "reason": words.replace(self.BOM, "").strip(), "affected_scope": scope,
                    "idempotency_key": f"semantic_reopen:gate_a_dry:{self.answer_file()}",
                    "expected_revision": self.controller_state().get("revision", 0)})
            except Refusal as refusal:
                # remains: the controller refused the reopening the person chose (a role runs, no current gate A); the question comes back with its words (FR-1)
                raise self.held_question("Your choice to approve gate A again could not be carried out, so nothing was changed.",
                                         refusal.text)
            print("S6: gate A is asked again; the test design is reviewed first, and the cases are checked by hand after your approval")
            return True
        if token in offered or "reapprove" not in offered:
            return self.take_seam_answer(words, asked, qtext, stage, dispatch)
        self.unread(kind, stage, dispatch, self.generic_prompt(kind, stage, qtext), words=words, block=self.GATE_A_DRY_BLOCK,
                    doors=tuple(offered), lead=self.unread_lead(words), again=lambda said: self.held_question(said))
        return False

    def _unread_kept_gate(self, kind: str, stage: str, dispatch: str, qtext: str, words: str, stand_note: str, apply_words: str = "") -> None:
        """t-667 D14: gate_A, gate_B, conductor, refusal - a block that outlived the recording: an approval that was heard and
        not recorded is kept, then the words go to the conductor. `stand_note` is the note of the stand-gap lines that could not
        be read (`take_stand_gap_answers`), "" for any other answer. `apply_words`: the part of `words` the card lines are read from
        (a second answer's tail is not, t-891 F-2); kept beside the words as `apply` for the recording that comes back."""
        if kind in ("gate_A", "gate_B") and self.gate_approval(kind, words):
            # t-211 / C3 (FR-7): an APPROVAL that was heard and not recorded (the controller refused it, or a stand-gap line did
            # not record). It is kept BEFORE the conductor sees it (a conductor that asks a question ends this process), so the
            # loop coming back to await_gate finds it and records the decision again instead of repairing or asking again.
            # C1-4b (I2): words that are NOT the approval word are never kept as one - they reach the seam, whole, and nothing else.
            self.state["gate_answer_kept"] = {"gate": kind[-1], "words": words, "at": _now(), "approved_by": "token",
                                              "source_revision": self.controller_state().get("source_revision"),
                                              **({"apply": apply_words} if apply_words and apply_words != words else {})}
            self.save_state()
        read = self.judged_reply(qtext, words, kind)
        lines_note, self.question_lines_note = getattr(self, "question_lines_note", ""), ""      # GW1-34: told once, to this call
        # RH1-6 (A-AC5): the controller refused this APPROVAL over open items: the conductor is told whose refusal it is, and given the
        # recording command for each item - not "words that are not the approval word". Items unreadable: today's prompt (FR-41).
        items = self.gate_open_items(self.gate_refusal) if kind == "gate_A" and self.gate_approval(kind, words) else None
        items_text = self.open_items_text(items, words, self.gate_refusal_parts(self.gate_refusal)[0]) if items else ""
        if lines_note and not items_text:
            items_text = "The person said the gate's approval word; it is kept, and nothing is recorded yet."
        self.unread(kind, stage, dispatch,
                    self.generic_prompt(kind, stage, qtext, items_text) + stand_note + lines_note + (PRE_FILLED + read if read else ""),
                    words=words)

    def _file_words(self, kind: str, dispatch: str, asked: dict, words: str, qtext: str, seam_token: bool) -> None:
        """t-667 D14: the words belong to the dispatch the refusal itself names, even when the question header carried none. Live
        TP1-13797 run 5: a `resolve_return` packet names its `dispatch_id`, the question header does not, so nothing filed
        the answer, the controller asked again and the identical packet reached the person three times. A boundary the person
        has answered must never be re-asked with the same text. t-217 / F-cmp2-22 (FR-16, FR-7, FR-8): WHOSE answer it is is a
        FIELD (`asked.dispatch`, set when the question was raised), never an id read out of the question's text. Two runs filed a
        person's words for the wrong dispatch that way: a gate-A packet that quotes "the S2 handoff of S2-qa-requirements-tester-1"
        (cmp2-18) and a probe's hint "--dispatch <critic id>" (cmp2-26). The field outranks the text; `seam_token` (the answer was
        a token of a question the seam raised) is never filed as words for a role."""
        if kind in ("gate_A", "gate_B"):
            # The gate's keeper is `gate_answer_kept` (`record_by_code` / the kept answer), never `pending_words`.
            print(f"gate {kind[-1]}: the answer is "
                  + ("kept for the gate" if self.state.get("gate_answer_kept")
                     else "recorded by code" if self.gate_approval(kind, words)
                     else "taken through the options of the question" if seam_token else "with the conductor")
                  + " and filed for no dispatch")
        elif dispatch:
            if kind in ("conductor", "refusal"):
                # The kinds a refusal raises: their words were once filed by the id the text happened to name
                # (a `resolve_return` packet, run 5), and the field now says it. Every other kind with a dispatch
                # (a halt, a review, a threshold stop) filed its own words in its own branch above, and a package or
                # retro answer is not words for a role at all. A TOKEN of a seam question is not words for a role either:
                # `retry` / `restart` resuming the role with the token as its instruction was the hole (F6).
                if seam_token:
                    print("the answer is a token of the question's own options: it is not filed for a role")
                else:
                    self.state["pending_words"][dispatch] = words
                    print(f"the answer is filed for {dispatch}, the dispatch the question is about")
        elif "blocks" in asked or kind not in ("conductor", "refusal"):
            # t-217 O2 (critic t-244): the text reading below is for the two kinds an OLDER driver raised from a refusal.
            # This driver's questions of every other kind (an `environment` stop quoting `--dispatch S6-qa-test-runner-1`
            # in its own words) carry no dispatch on purpose, and their words are not words for a role.
            print("the answer is filed for no dispatch: the question names none")
        else:
            # A question an OLDER driver asked (no `blocks` key): its text is all there is. The two spellings a
            # refusal wrote a dispatch in survive, and a capture counts only when it IS a dispatch id by shape and
            # is the only one the text names (`<critic id>`, a placeholder, is not one).
            named = sorted({m for m in (re.findall(r'"dispatch_id":\s*"([^"]+)"', qtext or "")
                                        + re.findall(r'--dispatch\s+(\S+)', qtext or ""))
                            if DISPATCH_ID_RE.fullmatch(m)})
            if len(named) == 1:
                self.state["pending_words"][named[0]] = words
                print(f"the answer is filed for {named[0]}, named by the refusal itself")
            else:
                print("the answer is filed for no dispatch: the question names none"
                      if not named else "the answer is filed for no dispatch: the question names more than one")

    # --- dry run -------------------------------------------------------------------------------

    def describe(self) -> int:
        print(f"story_run --dry-run: task {self.task}, project {self.project}, plugin {self.plugin}, "
              f"model {self.model}"
              + (f" ({'named' if self.model_explicit else 'default_model.codex of references/driver-infra.json'})"
                 if self.host == "codex" else "")
              + f", {self.host} {' '.join(self.claude) or '<not found>'}")
        print(f"until: {self.until or 'end'}; stand remedy: {self.stand_remedy()}")
        if self.flags.answer:
            asked = self.state.get("asked") or {}
            if asked.get("kind") == "questions":
                print(f"would record the answers in {self.flags.answer} by code, per open question, and resume the "
                      "role's own session with the words (no conductor)")
            else:
                print(f"would route the answer in {self.flags.answer} to the conductor as kind `{asked.get('kind')}`"
                      if asked else "no question is open: the answer would be refused")
        if not (self.task_root / "pipeline.json").is_file():
            print("pipeline.json is absent: would run S0 by code — ticket_adapter get --raw-dir (the tracker by REST; a read "
                  "that fails is asked of the person, a lost login stops the run, no model is called; a dry run asks "
                  "nothing and reads nothing), environment_selection, "
                  "readiness --write --probe-vcs / --require, env_probe, pipeline.json, stage_done S0, controller initialize")
            return EXIT_DONE
        try:
            action = self.where()
        except Refusal as exc:
            print("where refused:\n" + exc.text)
            known = route_known(exc)
            print(f"would: {'known refusal ' + known[0] + ' -> ' + known[1] if known else 'call the conductor'}")
            return EXIT_DONE
        print("where: " + json.dumps(action, ensure_ascii=False))
        if self.until_reached(action):
            print(f"would stop: --until {self.until} reached")
            return EXIT_DONE
        kind, stage = action.get("action"), str(action.get("stage") or "")
        stages = self.stages()
        example = self.claude_cmd("<prompt>", agent="<role>", system_file=Path("<state/driver-tmp/<dispatch>.system.md>"))
        if kind == "prepare_stage":
            if stage == "S5":
                scope = self.stage_scope("S5")
                todo = [w for w in scope.get("windows") or [] if "qa-code-critic" not in (w.get("accepted_by") or {})]
                print(f"S5 windows left: {json.dumps(todo, ensure_ascii=False)[:1500]}")
                print("would: story_step start qa-automator --scope <window> -> claude -p -> bind -> finish --not-complete; "
                      "then qa-code-critic the same; concerns -> rework --cause test_defect (cap from repair_budget). At the cap, "
                      "when the count cannot be read, or when the critic's findings are nobody's round: ONE closed question to "
                      "the person (round / debt / fixed / stop, or review for the critic's own doubt) BEFORE the critic's finish; "
                      "nothing is dispatched or closed over it")
            elif stage == "S6":
                print("would: stage-scope automation / manual -> qa-runner per block -> finalize_task.py")
            elif stage == "S7" and self.s7_life():
                try:
                    waiting = len(self.s7_repair_rows()) + len(self.s7_rejudge_rows())
                except Refusal:
                    waiting = 0
                print(f"the failure analyst's triage is accepted; S7 stays open for the repairs of {waiting} test(s): would run their "
                      "rounds (S5 qa-automator rework per test, cap from repair_budget; at the cap ONE closed question per test), then "
                      "close S7 by code (finalize_task, code_only S7, stage_done)")
            elif stage == "S7":
                try:
                    print("failures to triage: " + (self.failures_to_triage() or "none -> code_only S7 + stage_done"))
                except Refusal as exc:
                    print("S7 entry: " + exc.text)
            elif stage == "S9":
                print("would: bug reporter (chosen drafts) + delivery conductor call once, then the retro "
                      f"(retro_mode {self.pipeline().get('retro_mode') or 'full'}; question asked: {bool(self.state.get('retro_asked'))})")
            else:
                roles = stages.get(stage, {}).get("roles") or []
                print(f"would: story_step start {stage} {' then '.join(roles)} -> claude -p -> bind -> handoff check -> finish")
        elif kind == "await_gate":
            print(self.gate_repair_would(str(action.get("gate") or "A")))
            print(f"would: write state/driver-question.md from gate_brief --gate {action.get('gate')} + gate_preflight, exit 3")
        else:
            print(f"would: {kind} -> " + ("resume the saved session" if self.state["pending_words"] else "known table / conductor"))
        print(f"{self.host} command shape: " + " ".join(example))
        return EXIT_DONE
