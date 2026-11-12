"""driver_conductor.py - Driver members and names homed here by ai-packages/qa-factory/scripts/tests/fixtures/driver-layers.json (TD-11 cut by tools/source_split.py); no behaviour of its own."""

import json
import re
import sys
import time
from pathlib import Path
import hooklib
import human_text
import no_move as NM
import person_owned as PO
import waiver
from driver_core import EXIT_GAVE_UP, EXIT_PERSON, GATE_KINDS, JOURNAL_ROWS_BLOCK, OWED_ROW_TRIES, Person, Refusal, Stop, _append_jsonl, _now, recorded_earlier
from driver_dialog import TOKEN_ANSWERS


CONDUCTOR_TOOLS = "Bash,Read,Grep"

CONDUCTOR_MAX_TURNS = 20

CONDUCTOR_CALLS_PER_BOUNDARY = 3

CONDUCTOR_FILE_LIMIT = 8 * 1024

CONDUCTOR_FILES = 3          # files in a conductor prompt; the boundary's own files come as (help, form, values), see `conductor`

# The person's words in a conductor prompt are cut here with a pointer to the file that holds them whole (FR-8: the carrier of
# the words is the file, never the prompt); matches the refusal's own cut in `conductor`.
NO_MOVE_WORDS_IN_PROMPT = 6000

# The judge's reading of a person's words, handed to the conductor as a pre-filled option.
# It is not a decision and never records anything: the words the conductor writes are the
# person's own, verbatim (J6, and the boundary plan section 10.6 draws).
PRE_FILLED = ("\n\n## The option the judge reads in their words (confirm it against the words "
              "above; it decides nothing and records nothing)\n")

PATH_RE = re.compile(r"(?<![\w/])((?:[A-Za-z]:)?[\w./\\-]+\.(?:md|json|jsonl|py|txt|log|xml|toml|ini|cfg|env))\b")

# C1-2 (conductor/1, P22): what the conductor is told when a person's words are none of the answers a question offered.
# ONE text each, so a call site cannot drop or reword it (test_conductor_doors K12 builds every prompt and looks for them).
MOVES_RULE = ("If their words ask for something else the factory can do, take that move from `moves` (or the row of "
              "`actions` that says it) in "
              "references/conductor-actions.json when its precondition holds; otherwise run nothing and answer "
              "`ask_person` with the options, each with what it costs and what it does to the story "
              "(references/human-questions.md).")

OWN_TOKEN_RULE = ("A token from your own options is their choice: run that move (the row of `moves` whose token it is) "
                  "and say so in `did`.")

GATE_FALLBACK = ("retry", "stop")        # the standing words that have an executor at a gate: `retry` shows the gate again

# The floor at a gate (C2-7 §5.2): `approve` has an executor (`approve_by_option`) only when the original answer is on file, so the
# floor is TWO texts and the one with `approve` is used only then; `rework` is not on the floor (the floor is where nothing is read)
GATE_TOKEN_ANSWERS = (
    "What I need is a decision. Answer with exactly one of these words:\n"
    "`retry` — the gate is shown again, and you answer it;\n"
    "`stop` — stop the story here.\n"
    "To change something, write what to change in your own words.")

GATE_TOKEN_ANSWERS_APPROVE = (
    "What I need is a decision. Answer with exactly one of these words:\n"
    "`approve` — the gate is recorded as approved with the answer you gave before;\n"
    "`retry` — the gate is shown again, and you answer it;\n"
    "`stop` — stop the story here.\n"
    "To change something, write what to change in your own words.")

GATE_RULE = ("At gate A and gate B the person's words are the gate's answer. You never record a gate decision yourself. When "
             "their words approve what was shown and ask for no change, offer `approve`: the driver records it and applies "
             "their card answers first. When they ask for any change, offer the moves open here with what each costs. A "
             "rework of the stage that made it is followed by the stages after it running again and this gate being asked "
             "again. Run none of them before the person chooses.")

# The delivery's prompt: nothing has gone out only while no attempt is recorded (`delivery_attempts` empty, FR-59); a
# rework is not offered here (a delivery runs on a closed story, where a rework is a reopen: C1-6 adds it with its executor).
DELIVERY_RULE = ("You never start a role's session and never edit what a role wrote. Only when a repair the decision "
                 "orders is still undone: it is never delivered around — while no delivery attempt is recorded (the line "
                 "`no attempt recorded` below), answer `ask_person` with the options of references/human-questions.md — "
                 "`go on` (deliver as it is) or `retry` (the person repairs it, then the delivery is asked again) — and send "
                 "nothing out; once an attempt is listed below, ask the same way and register nothing. When the person's "
                 "choice is in this prompt (the line `The person chose`), do what they chose: `go on` → the four steps; "
                 "`retry` → the person says the repair is done: check that it is, then the four steps, and while it is "
                 "still undone ask again and send nothing out. With no repair undone, do the four steps.")


class ConductorSpent(Exception):
    """The conductor was called `CONDUCTOR_CALLS_PER_BOUNDARY` times at this boundary. Raised by `Driver.conductor` and caught
    by `Driver.no_move` ALONE: the cap is a reason to enter the seam, never a text of its own."""

    def __init__(self, count: int, refusal: str):
        super().__init__(f"the conductor was called {count} times at this boundary")
        self.count, self.refusal = count, refusal


def last_json_line(text: str) -> dict:
    """The conductor's verdict: the last line of its answer that is a JSON object."""
    for line in reversed((text or "").splitlines()):
        line = line.strip().strip("`")
        if line.startswith("{") and line.endswith("}"):
            try:
                data = json.loads(line)
                if isinstance(data, dict) and data.get("action"):
                    return data
            except ValueError:
                continue
    return {}


def named_files(text: str, roots: list, limit: int = CONDUCTOR_FILES) -> list:
    """Existing files a refusal names, resolved against the given roots, at most `limit`."""
    found, seen = [], set()
    for raw in PATH_RE.findall(text or ""):
        candidate = raw.strip("`'\"")
        for root in roots:
            path = (Path(candidate) if Path(candidate).is_absolute() else Path(root) / candidate)
            try:
                resolved = path.resolve()
            except OSError:
                continue
            if resolved.is_file() and str(resolved) not in seen:
                seen.add(str(resolved))
                found.append(resolved)
                break
        if len(found) >= limit:
            break
    return found


class DriverConductor:
    def owed_rows_step(self) -> None:
        """Write the owed rows again, BEFORE any brief is built (S2, E8): `run()` calls it after the answer is taken and first in every
        loop turn. Nothing owed: nothing happens (no line, no question). Each row runs once; one that writes leaves the list. A row that
        fails `OWED_ROW_TRIES` times in all is the seam's question (`no_move` called here, with the block `JOURNAL_ROWS_BLOCK`, the
        priced fallback and no paid call; its text is row ids and counts, never the person's words - FR-12). The person's `go on`
        (`rows_word`: the rows its own question named, marked by `mark_rows_word` - paired by row id, never by clock) gives those rows
        up (`state["rows_given_up"]`, FR-40) with ONE `rows_given_up` line in driver-runs.jsonl, and from then on a row of the same
        script that fails is given up with no question (D-0043; the word is the story's, kept in `pipeline.json`). POSITION: no step that can dispatch or resume a role runs while a row is owed (S2)."""
        rows = self.owed_list()
        if not rows:
            return
        given = self.state.get("rows_given_up")
        given = self.state["rows_given_up"] = given if isinstance(given, list) else []
        classes = {str(r.get("script")) for r in given if isinstance(r, dict)}
        classes |= {str(r.get("script")) for r in rows if isinstance(r, dict) and self.rows_word(r)}
        kept, failed, dropped = [], [], []
        for row in rows:
            if not (isinstance(row, dict) and row.get("script") and isinstance(row.get("args"), list)):
                self.journal_run({"kind": "trace_failed", "script": "owed_rows", "exit": 0, "why": "an owed row that cannot be read was set aside"})
                continue
            code, out = self.py(str(row["script"]), *row["args"])
            if not code or recorded_earlier(str(row["script"]), code):
                continue
            tries = row["tries"] if isinstance(row.get("tries"), int) else 1
            row = dict(row, tries=tries + 1, exit=code, tail=out[-300:])
            if row["script"] in classes:
                dropped.append(dict(row, given_up=_now()))
            else:
                (failed if row["tries"] >= OWED_ROW_TRIES else kept).append(row)
        if dropped:
            given += dropped
            self.journal_run({"kind": "rows_given_up", "rows": [r["id"] for r in dropped], "scripts": sorted({r["script"] for r in dropped}),
                              "count": len(dropped)})
            print(f"journal: {len(dropped)} row(s) given up on the person's word; they are not in the story's journal")
        self.state["owed_rows"] = kept + failed
        self.save_state()
        if not failed:
            return
        have_pipeline = (self.task_root / "pipeline.json").is_file()
        ids = ", ".join(str(r.get("id")) for r in failed)
        self.boundary = "owed_rows"
        self.no_move({"why": "refusal", "kind": "refusal", "call": False, "stage": str(failed[0].get("stage") or "S0"), "dispatch": "",
                      "block": JOURNAL_ROWS_BLOCK if have_pipeline else "", "fallback": ["retry", "go on", "stop"] if have_pipeline else ["retry", "stop"],
                      "rows": [str(r.get("id")) for r in failed],       # B-1: the ids this question is about; its `go on` marks exactly these
                      "lead": (f"{len(failed)} record(s) of this story could not be written to its journal, even on a second try. The roles that "
                               "run next read that journal, so they would work without " + ("it" if len(failed) == 1 else "them") + ": "
                               + "; ".join(str(r.get("what")) for r in failed) + ". The fault is the factory's own, not yours. Nothing about it "
                               "is filed yet: the records wait and are written again at the next step; if you go on without them, one line in "
                               "the story's run log says so."),
                      "lines": [str(r.get("what")) for r in failed],
                      "text": f"The journal refused {len(failed)} row(s) twice: {ids}. The rows stay owed in the story's state and are written "
                              "again at the next step."})

    def stand_remedy(self) -> str:
        """The standing authorization the conductor needs before it touches a stand: the
        selected environment's `bring_up` text says AUTHORIZED, or config.driver says so."""
        driver = self.config.get("driver") or {}
        if driver.get("stand_remedy_authorized") is True:
            return "authorized (config.driver.stand_remedy_authorized)"
        name = self.pipeline().get("environment")
        for env in self.config.get("environments") or []:
            if env.get("name") == name and "AUTHORIZED" in str(env.get("bring_up") or ""):
                return f"authorized for stand `{name}` (config.environments.bring_up carries AUTHORIZED)"
        return "NOT authorized: no standing authorization in config.json — a stand remedy is a question for the person"

    def pass_to_person(self, verdict: dict, kind: str, stage: str, dispatch: str) -> None:
        """`ask_person` carries the question; without one it is the conductor failing its own
        contract, not a question. TP1-13797, 26.09: one such answer cost $1.27 and 21 turns,
        recorded nothing (`did` empty) and reached the person as the driver's filler sentence
        "The conductor needs more." — no file, no refusal, no decision in it. The driver does not
        invent the words: the failure is printed and journalled as the factory's own, and the loop
        goes back to `where`. A block that really stands comes back with its own text."""
        question = str(verdict.get("question") or "").strip()
        # RN1-9 (E-8): a question with no class or no `checked` is the same exit as an empty one; `ConductorSpent` bounds the loop.
        rule = PO.question_rule(verdict.get("why_person"), verdict.get("checked")) if question else ""
        if question and not rule:
            person = Person(kind, question, stage, dispatch)
            person.why_person, person.checked, person.source = (PO.normalize(verdict.get("why_person")),
                                                                PO.checked_text(verdict.get("checked")), "conductor")
            raise person
        did = str(verdict.get("did") or "").strip()
        if rule:
            print(f"conductor: ask_person without a class at {stage}:{dispatch} - {rule[:160]}; back to `where`")
            self.file_defect(dispatch, f"owner: factory — the conductor answered `ask_person` without a class of "
                                       f"references/{PO.FILE_NAME} or without what it read at {stage}:{dispatch} "
                                       f"({rule[:300]}); the driver went on instead of asking the person")
            return
        print(f"conductor: ask_person with no question at {stage}:{dispatch} — its own contract "
              f"failure, not a question for the person (did: {did[:120] or 'nothing'}); back to `where`")
        self.file_defect(dispatch, f"owner: factory — the conductor answered `ask_person` with an empty question "
                                   f"at {stage}:{dispatch} (did: {did[:300] or 'nothing'}); the driver went on "
                                   "instead of handing the person a filler sentence")

    # --- the conductor ---------------------------------------------------------------------

    def answer_file(self) -> str:
        """The file of the answer being taken, task-root relative (`state/words/driver-answer-<ms>.txt`), written ONCE per answer
        from the raw bytes of `--answer` (CRLF kept) the first time something needs it; '' with no answer or an empty one."""
        held = self._answer
        if not held:
            return ""
        if held.get("rel") is None:
            path = self.words_file(held["text"], "answer")
            held["rel"] = path.relative_to(self.task_root).as_posix() if path else ""
        return held["rel"]

    def record_answer_row(self, token: str, dispatch: str | None = None) -> None:
        """The audit row of the answer being taken in `state/driver-answers.jsonl`, written ONCE per answer: `take_answer` writes
        it at its end, and the run()-level funnel writes it for an answer whose reading raised a Refusal before that point, so a
        person's word is never lost to the refusal. Nothing to write for an answer `take_answer` has not read far enough."""
        held = self._answer
        if not held or held.get("row") or "kind" not in held:
            return
        held["row"] = True
        _append_jsonl(self.state_dir / "driver-answers.jsonl",
                      {"ts": _now(), "kind": held["kind"], "stage": held["stage"], "dispatch": held["dispatch"] if dispatch is None else dispatch,
                       # The body this answer settled, so the same body cannot come back unchanged
                       # (FR-7). The text itself is not kept here: it is in the question file and
                       # in the journal of questions; what travels is its identity.
                       "question_sha": held["question_sha"], "words": held["words"],
                       # C1-1: the token this answer was ("" when it was not one) and the file that holds it whole
                       "token": token, "words_file": held.get("rel") or ""})

    def settle_unread_answer(self) -> str:
        """For the run()-level funnel: the answer `take_answer` was reading when a Refusal came out of it (read, not yet on the
        record) gets its words file and its row now; its words file (task-root relative), else '' - no answer, or one already on
        the record, which this refusal is not about."""
        held = self._answer
        if not held or held.get("row") or "kind" not in held:
            return ""
        path = self.answer_file()
        self.record_answer_row("")
        return path

    def conductor(self, refusal: str, *, words: str = "", files=None, words_file: str | None = None) -> dict:
        """One conductor session. Called ONLY from `no_move` (I-one). The cap raises `ConductorSpent`, which only `no_move`
        catches; an answer with no JSON line is `{"action": "_unreadable"}`, never the model's raw end shown as a question.
        `words_file`: the task-root-relative file that holds `words` whole (the caller names it; nothing is inferred from the
        text); with none, the driver writes one."""
        key = self.boundary
        count = self.conductor_calls.get(key, 0)
        if count >= CONDUCTOR_CALLS_PER_BOUNDARY:
            raise ConductorSpent(count, refusal)
        self.conductor_calls[key] = count + 1
        try:
            where = self.step("where", "--task", self.task)
        except Refusal as exc:
            where = exc.text
        roots = [self.task_root, self.project, self.plugin]
        # The handover form of the dispatch this boundary is about, always - not only when the
        # refusal happens to name it. It is the state of the boundary: what the role claimed,
        # what code derived, what is `blocked` and in whose words. A conductor deciding without
        # it reads factory sources instead, which is what the fifty-four sessions of
        # TP1-13797 spent their turns on (P6).
        boundary_form = []
        # `<stage>:<dispatch>` and `<stage>:<dispatch>:resume` both name it in the same
        # place; `S0:ticket` and `S5:TC-1,TC-2` name no dispatch and the file check drops them.
        parts = self.boundary.split(":")
        dispatch = parts[1] if len(parts) > 1 else ""
        if dispatch:
            import handoff_check                                   # the one rule for the name of the words waiting beside a form
            form = self.task_root / "work" / "handoffs" / f"{dispatch}.yaml"
            # The order is the priority inside a window of CONDUCTOR_FILES: the boundary's files come BEFORE the refusal's own, so
            # the form (the state of the boundary) is in view in every case; the waiting words come after it, the first to give way.
            for candidate in (handoff_check.sibling_help(form), form, handoff_check.sibling_values(form)):
                if candidate.is_file():
                    boundary_form.append(candidate)
        named = boundary_form + list(files or []) + named_files(refusal, roots)
        shown, seen = [], set()
        for path in named:
            path = Path(path)
            if not path.is_file() or str(path) in seen:
                continue
            seen.add(str(path))
            body = path.read_text(encoding="utf-8", errors="replace")[:CONDUCTOR_FILE_LIMIT]
            shown.append(f"--- {path} ---\n{body}")
            if len(shown) >= CONDUCTOR_FILES:
                break
        # The conductor has Bash, Read and Grep and no way to make a file of the answer below, and a
        # command line cannot carry it whole: the driver writes it and names the path, as one
        # sentence the conductor can act on. No answer, no sentence, and the prompt is as it was.
        words_path = (self.task_root / words_file) if words_file else self.words_file(words, "conductor" + self.boundary.split(":")[0])
        # A rework's `--words-file` is the file of the answer being read in THIS call, never a file that holds a token (C1-2, C2).
        words_note = ([f"The person's words are in {words_path}; pass them as --words-file {words_path}. That is the file of "
                       "the answer you are reading now. For a `rework`, never pass a file that holds only a token."]
                      if words and words_path else [])    # a call with no words (why=chosen) names its file in its own note
        prompt = "\n".join([
            f"Task: {self.task}. Project root: {self.project}. Plugin root: {self.plugin}.",
            f"Task root: {self.task_root}. Boundary: {self.boundary}. Model: {self.model}.",
            f"Stand remedy: {self.stand_remedy()}.",
            f"Driver flags: branch suffix `{self.flags.branch_suffix or ''}`.",
            "", "## The refusal", refusal.strip()[:6000], "", "## `story_step.py where`", where.strip()[:2000],
            "", "## The person's words" if words else "",
            (words.strip()[:NO_MOVE_WORDS_IN_PROMPT]
             + (f"\n(cut; the whole answer is in {words_path})" if len(words.strip()) > NO_MOVE_WORDS_IN_PROMPT else "")) if words else "",
            *words_note,
            "", "## Files the refusal names" if shown else "", "\n\n".join(shown),
            "", "Make your moves with the factory's own commands, then answer with ONE JSON line last: "
                '{"action": "continue|retry|ask_person|stop", "did": "<what you ran>", "question": "<for the person, when ask_person>", '
                f'"why_person": "<a class of references/{PO.FILE_NAME}, with ask_person or stop>", "checked": "<what you read before asking>", '
                '"options": [{"token": "<word>", "move": "<id in moves>", "says": "<what it does>", "factory": "<its cost to the factory>", '
                '"person": "<its cost to the person>", "story": {"unverified": "<what stays unverified>", '
                '"report": "<the open item, or none>", "delivery": "<the move\'s delivery value>"}, '
                '"args": {"stage": "S<n>", "role": "<role>", "cases": ["<id>", ...] | "rows": ["<id>", ...], "cause": "<cause>"}}]} '
                "(`options` go with `ask_person` and `stop`: references/conductor.md, Your answer; `args` goes with the `rework` option only, "
                "from the closed list in \"Moves open here\")"])
        started = time.time()
        result = self.run_claude("conductor", prompt, stage=self.boundary.split(":")[0], tools=CONDUCTOR_TOOLS,
                                 system_file=self.plugin / "references" / "conductor.md",
                                 max_turns=CONDUCTOR_MAX_TURNS)
        verdict = last_json_line(result["result"])
        if not verdict:
            verdict = {"action": "_unreadable", "did": "", "question": ""}
        self.journal_conductor(stage=self.boundary.split(":")[0], refusal=refusal[:2000], action=verdict.get("action"),
                               did=str(verdict.get("did") or "")[:1000], question=str(verdict.get("question") or "")[:1000],
                               why_person=str(verdict.get("why_person") or "")[:60],
                               session_id=result["session_id"], total_cost_usd=result["total_cost_usd"],
                               num_turns=result["num_turns"], duration_ms=int((time.time() - started) * 1000),
                               words=bool(words))
        return verdict

    # --- the one seam "no move" (conductor/1, C1-1; PROJECT.md P22, D-0039) ----------------------------------------------

    def no_move_facts(self, state: dict) -> dict:
        """The facts the moves filter reads, each in its OWN try: a reader that raises leaves its fact `None` and removes only
        the moves that need it. The controller's own statuses and `hooklib.story_closure(C.closure_view(...))` (the one reading of closure), never a second reading."""
        import controller as C
        import hooklib
        facts, dispatch = {}, str(state.get("dispatch") or "")

        def read(name, fn):
            try:
                facts[name] = fn()
            except Exception:
                facts[name] = None

        def held() -> dict:
            found = self.controller_state()
            if not isinstance(found, dict) or not isinstance(found.get("dispatches"), dict):
                raise ValueError("controller.json is not readable")
            return found

        def decided(gate: str) -> bool:
            ctl = held()
            return any(isinstance(d, dict) and d.get("gate") == gate and d.get("status") == "approved"
                       and d.get("source_revision") == ctl.get("source_revision") for d in (ctl.get("decisions") or {}).values())

        def stages_open() -> list:
            # S5-S8 once gate A is decided, S1-S4 before it. "No later stage done" is no rule any more: a rework with the person's
            # words stamps the later stages to run again (`rerun_after`, C1-4a), so a later completed stage does not close this one.
            low, high = (5, 8) if decided("A") else (1, 4)
            accepted = {str(d.get("stage")) for d in held()["dispatches"].values()
                        if isinstance(d, dict) and d.get("status") == "accepted" and re.fullmatch(r"S\d+", str(d.get("stage") or ""))}
            return sorted((s for s in accepted if low <= int(s[1:]) <= high), key=lambda s: int(s[1:]))

        gate = {"gate_A": "A", "gate_B": "B"}.get(str(state.get("kind") or ""), "")     # never read from `asked` (C1-1 F1)
        facts["gate"] = gate

        read("dispatch_status", lambda: held()["dispatches"][dispatch]["status"] if dispatch else None)
        read("session", lambda: bool(held()["dispatches"][dispatch]) and bool(self.state["sessions"].get(dispatch)))
        read("running", lambda: any(isinstance(d, dict) and d.get("status") == "running" for d in held()["dispatches"].values()))
        read("closed", lambda: hooklib.story_closure(C.closure_view(held(), self.pipeline()))["state"] == "closed")
        read("attempts", lambda: len(self.state.get("delivery_attempts") or []))
        read("rework_stages", stages_open)
        # What an option's `args` may name (C2-6 §4.2 p.2): the roles of each stage's accepted work (the `ticket_rework_step` rule),
        # the approved scope, the controller's own causes
        read("rework_roles", lambda: {s: sorted({str(d.get("role")) for d in held()["dispatches"].values()
                                                 if isinstance(d, dict) and d.get("stage") == s and d.get("status") == "accepted" and d.get("role")})
                                      for s in facts["rework_stages"]})
        read("scope", lambda: [str(c) for c in held().get("scope") or []])
        read("causes", lambda: list(C.REPAIR_CAUSES))
        read("gate_decided", lambda: decided(gate) if gate else None)
        read("stand_authorized", lambda: self.stand_remedy().startswith("authorized"))

        def exclusions() -> bool:
            import source_exclusions as SE
            return bool(SE.live(self.task_root))
        read("live_exclusions", exclusions)
        return facts

    def open_moves(self, state: dict, moves, facts: dict | None = None) -> list:
        """The ids of `moves` whose state precondition holds now (`NM.MOVE_FACTS`), over `facts` (read here when not given)."""
        facts = self.no_move_facts(state) if facts is None else facts
        return NM.open_moves(facts, NM.move_ids() if moves is None else moves)

    def no_move_defect(self, rule: str, did: str = "", ref: str = "") -> None:
        """ONE `defect_found` per failure of the seam (owner: factory), and the `unusable` mark in conductor.jsonl."""
        self.file_defect(ref, f"owner: factory — {rule} at {self.boundary} (did: {str(did or '')[:200] or 'nothing'})")
        self.journal_conductor(stage=self.boundary.split(":")[0], action="unusable", unusable=rule)

    def _person_of(self, state: dict, text: str, options: list, *, code: int = EXIT_PERSON) -> Person:
        stage = str(state.get("stage") or self.boundary.split(":")[0])
        dispatch = str(state.get("dispatch") or "")
        person = Person(str(state.get("kind") or "conductor"), text, stage, dispatch, code=code, details=str(state.get("text") or ""))
        person.offered = tuple(o["norm"] for o in options)
        # `says` (what the option does, C2-6 §4.3) and a `rework` option's `args` (§4.2 p.5) travel with the token and move: the
        # next process reads them back from `asked` (`held_question` restores them whole)
        person.options = [{"token": o["norm"], "move": o["move"], **({"says": o["says"]} if o.get("says") else {}),
                           **({"args": o["args"]} if o.get("args") else {})} for o in options]
        person.words_file, person.why, person.block = str(state.get("words_file") or ""), str(state.get("why") or ""), str(state.get("block") or "")
        person.answer_note = str(state.get("answer_note") or "")
        person.rows = tuple(str(i) for i in state.get("rows") or ())
        person.probe_gap_cases = tuple(str(c) for c in state.get("probe_gap_cases") or ())
        person.probe_judgment_cases = tuple(str(c) for c in state.get("probe_judgment_cases") or ())
        # RN1-9: the class and the reading travel with the question; a priced fallback has none (counted `fallback`, never refused)
        person.why_person, person.checked = PO.normalize(state.get("why_person")), PO.checked_text(state.get("checked") or "")
        person.source = state.get("source") or "fallback"
        if state.get("why") == "refusal":
            person.holds = self.manual_holds(dispatch)       # RN1-24, third `holds` site: a refused MANUAL S6 dispatch holds its own cases
        return person

    def site_person(self, state: dict, lead: str, code: int, rule: str = ""):
        """The SITE's own question (`state["site_fallback"](lead)`, C1-3 G2) as the Person to raise, or None: no site, or the site's
        builder itself failed. A site that asked a CLOSED question (S0, `package`, `ticket_changed`) reads only its own words, so
        every exit of the seam that has no usable conductor answer shows that question again with the unread answer's `lead`, with
        its prices when they rendered and without them when they did not - never the generic `retry` / `go on` its reader cannot
        take. ONE defect_found per failure (G8), filed HERE for every caller (F-7): `rule` (why the seam is at its fallback) and the
        price reasons found while the site renders (`_price_notes`) are ONE note, so a site that renders prices never files a
        second defect for the same cause. `code`: 4 only after a conductor `stop`, else 3 (the fallback's own rule)."""
        again = state.get("site_fallback")
        if not callable(again):
            return None
        self._price_notes = []
        try:
            try:
                person = again(lead)
            except Person as made:
                person = made
            except Exception:                   # a site that cannot rebuild its question falls to the floor (`last_resort`)
                person = None
        finally:
            notes, self._price_notes = self._price_notes, None
        if rule or notes:
            self.no_move_defect("; ".join(part for part in (rule, *notes) if part), ref=str(state.get("dispatch") or ""))
        if not isinstance(person, Person):
            return None
        person.code = code
        return person

    def fallback_person(self, state: dict, rule: str = "", code: int | None = None, conductor_text: str = "") -> Person:
        """The priced fallback question (`fallback` of conductor-actions.json) for a state in which no conductor answer
        exists or is usable - or, when the site asked a closed question (`site_fallback`), THAT question again (`site_person`).
        `rule` (when the answer was unusable) is journalled as the factory's own defect; ONE per failure, with the reasons the
        prices of the site's question could not be read added to it. `conductor_text` (t-1936 F2.2 (a), FR-9, AR-17): the `question` of a
        conductor answer whose options were refused - it reaches the person after the lead (`What the conductor found:`, cut at 1200
        characters, a line for each word it quotes that is not offered), on every road below, the floor included; empty = as before."""
        stage = str(state.get("stage") or self.boundary.split(":")[0])
        lead = str(state.get("lead") or "") or self.question_from_refusal(None, stage)
        if code is None:
            code = EXIT_GAVE_UP if state.get("why") == "stop" else EXIT_PERSON
        spec, site = NM.data(), state.get("site_doors") or ()
        # the answers shown are not known yet on these roads (a site's own question, the floor): the text is shown, no token line is claimed
        unknown = lambda: NM.conductor_lead(lead, conductor_text, None, spec, self.s0_normalize, site=site)
        if callable(state.get("site_fallback")):
            person = self.site_person(state, unknown(), code, rule)       # files the ONE defect (the rule and the price reasons)
            if person is not None:
                return person
            return self.last_resort(dict(state, site_fallback=None), "the question of the site could not be shown again", lead=unknown(), code=code)
        if rule:
            self.no_move_defect(rule, ref=str(state.get("dispatch") or ""))
        verdicts = (hooklib.load_ref_json(NM.VERDICTS_FILE) or {}).get("words") or {}
        try:
            if str(state.get("kind") or "") in GATE_KINDS:
                text, options = self.gate_fallback_question(state, lead, verdicts, conductor_text=conductor_text)
            else:
                options = NM.fallback_options(spec, verdicts, self.s0_normalize, keep=state.get("fallback"))
                facts = self.fallback_facts(state) if str(conductor_text).strip() else {}
                text = NM.render_question(NM.conductor_lead(lead, conductor_text, [o["norm"] for o in options], spec, self.s0_normalize,
                                                            facts=facts, site=site), options, human_text.price_labels())
            return self._person_of(state, text, options, code=code)
        except (NM.DataUnreadable, human_text.LabelsUnreadable, Refusal) as exc:
            return self.last_resort(state, f"the fallback could not be rendered ({exc})", lead=unknown(), code=code)

    NO_APPROVE_WORDS = "To approve, answer this gate in your own words; the choice alone has nothing to record."

    def gate_fallback_question(self, state: dict, lead: str, verdicts: dict, conductor_text: str = "") -> tuple:
        """`(text, options)` of the fallback question AT A GATE (t-722 C2-7 §5.1): the options of the ONE table `GATE_OPTIONS` that are open now (the
        conductor's own prices at this gate read the same rows, `gate_option_rows`, FR-10), each with its executor - `approve` (code,
        the original answer on file), `rework` (no `args`: the answer goes to the conductor with the person's words, which names the
        stage, P1), `retry`, `stop`. An option that is not offered is said in ONE line of the lead (FR-42). A fact that could not be
        read removes its move and is never told as a reason (FR-59). Raises what the caller turns into the floor (`last_resort`).
        `conductor_text` (t-1936 F2.2 (a), E2.5): the conductor's refused `question`, shown after the lead with a line for each word it
        quotes that these options do not carry; it offers nothing, so `go on` stays unoffered at a gate."""
        facts = self.fallback_facts(state)
        open_ids = NM.open_moves(facts, [move for _answer, move, _says, _slots in self.GATE_OPTIONS])
        notes = []
        if "approve_gate" in open_ids and not state.get("words_file"):
            open_ids.remove("approve_gate")
            notes.append(self.NO_APPROVE_WORDS)
        if "rework_stage" not in open_ids:
            notes.append("Sending a stage back is not open now: " + NM.rework_closed_reason(facts) + ".")
        if ((self.state.get("shown_gaps") or {}).get(str(state["kind"])[-1]) or {}).get("gaps"):
            notes.append("Your answers to the stand cards of this gate, one per line as `<case>: <word>`, are read in this answer too.")
        rows = self.gate_option_rows(open_ids, facts)
        priced = NM.priced_options("gate_A" if state["kind"] == "gate_A" else "gate_B", rows, NM.data(), verdicts)
        options = [dict(row_priced, norm=self.s0_normalize(row["token"]), move=row["move"]) for row_priced, row in zip(priced, rows)]
        lead = NM.conductor_lead(lead, conductor_text, [o["norm"] for o in options], NM.data(), self.s0_normalize, facts=facts,
                                 site=state.get("site_doors") or ())
        return NM.render_question("\n\n".join([lead, *notes]), options, human_text.price_labels()), options

    def fallback_facts(self, state: dict) -> dict:
        """`no_move_facts` for the fallback of a gate, `{}` when even that fails: every move that needs a fact is then closed."""
        try:
            return self.no_move_facts(state)
        except Exception:
            return {}

    def last_resort(self, state: dict, rule: str, *, lead: str = "", code: int = EXIT_PERSON) -> Person:
        """The floor of the seam. With a site's question (`site_fallback`) that is the question, shown without prices if they cannot
        be read; otherwise the question with no price lines: the three standing words (TOKEN_MOVES). A site question that is itself
        unreadable ends here, ONCE: the generic words, and nothing below them (G2)."""
        lead = lead or self.question_from_refusal(None, str(state.get("stage") or self.boundary.split(":")[0]))
        if callable(state.get("site_fallback")):
            shown = self.site_person(state, lead, code, rule)         # the rule joins the price reasons: ONE defect (F-7)
            if shown is not None:
                return shown
        elif rule:
            self.no_move_defect(rule, ref=str(state.get("dispatch") or ""))
        at_gate = str(state.get("kind") or "") in GATE_KINDS      # at a gate `go on` passes nothing: only `retry` and `stop` have an executor
        options = [{"token": t, "norm": t, "move": m} for t, m in NM.TOKEN_MOVES.items() if not at_gate or t in GATE_FALLBACK]
        # C2-7 §5.2: `approve` is on the floor of a gate only with the original answer on file and the gate not decided (a fact that
        # cannot be read is no gate that is open: the move is not offered, FR-59)
        approve = at_gate and bool(state.get("words_file")) and bool(NM.open_moves(self.fallback_facts(state), ["approve_gate"]))
        if approve:
            options.insert(0, {"token": "approve", "norm": self.s0_normalize("approve"), "move": "approve_gate"})
        floor = (GATE_TOKEN_ANSWERS_APPROVE if approve else GATE_TOKEN_ANSWERS) if at_gate else TOKEN_ANSWERS
        return self._person_of(state, lead + "\n\n" + floor, options, code=code)

    def _ask_conductor(self, text: str, state: dict) -> dict:
        """THE call (I-one): the only `self.conductor(` of the driver.

        The ONE named exception (C1-6c, F7): the delivery's own session, `Driver.delivery`'s `run_claude("conductor")`, is the second
        conductor call site and there is no third. It is a role-like session (tools, 40 turns, a resume key), not a state the driver has
        no move for; only its QUESTIONS go through the seam helpers (`delivery_person`). `audit_factory.CONDUCTOR_SITES` names both."""
        named = {"words_file": state["words_file"]} if state.get("words_file") else {}      # no file named: the call is as it was
        return self.conductor(text, words=str(state.get("words") or ""), files=state.get("files"), **named)

    def standing_refusal(self, state: dict) -> None:
        """THE writer of `state/standing-refusal.json` (t-722 §3.1, §L-7, class K4): `{stage, lines, doors}` of the refusal the seam is
        called for, which `waiver.py --block` reads (`waiver.read_standing`, the one reader) to refuse a block that is in none of it.
        Only a call that carries `lines` (a non-empty list, built by `refusal_lines`) writes; `unread_answer`, `chosen`, `stop` and
        `by_hand` carry none and leave the file as it is. The last refusal REPLACES the record, never merged. `doors`: the block
        names the refusal printed in its own door, read from the raw `text` (`waiver.door_blocks`) - the lines have lost them.
        The stage is `state["stage"]`; with none (`funnel`) the ONE stage `pipeline.json` holds `running`; no stage or several, no
        record (an unknown is not a fact, FR-59) and the old one goes. A dry run writes and erases nothing; a record that cannot
        be written erases the old one (a refusal that no longer stands is never judged against); the seam goes on either way (P1)."""
        lines = state.get("lines")
        if self.dry or not isinstance(lines, list) or not lines:
            return
        stage = str(state.get("stage") or "").strip().upper()
        if not stage:
            running = [s for s, held in (self.pipeline().get("stages") or {}).items()
                       if isinstance(held, dict) and held.get("status") == "running"]
            stage = running[0] if len(running) == 1 else ""
        if not re.fullmatch(r"S\d+", stage):
            return self.drop_standing()
        try:
            waiver.write_standing(self.task, stage, lines, waiver.door_blocks(state.get("text")))
        except OSError as exc:
            print(f"note: the record of the standing refusal was not written ({exc}); a block is recorded as not verified", file=sys.stderr)
            self.drop_standing()

    def standing_note(self, stage: str) -> str:
        """What the conductor is told about `go on` with no block of code's own (t-722 §3.4): the lines of the refusal the record
        holds for `stage`, whole and numbered, under the writer's ceiling (`waiver.listed`: the same listing as its refusal), or the
        sentence that none is recorded. `waiver.py` refuses a block that is in none of the lines."""
        lines = waiver.read_standing(self.task, stage.strip().upper())["lines"]
        if not lines:
            return "No refusal is recorded as standing here; if their words pass nothing, keep them with --remark."
        return ("The refusal standing here has these lines; record their words only for the lines their words cover, one waiver.py "
                "--block per line, the line whole:\n" + waiver.listed(lines, waiver.standing_path(self.task))
                + "\nwaiver.py refuses a block that is in none of them.")

    def no_move(self, state: dict, moves=None) -> str:
        """The ONE seam for a state in which the driver has no move of its own. Returns `continue` / `retry` after a conductor
        move; otherwise raises `Person` with a closed question of at least two options, each followed by its three price lines.
        Never returns silently (I-nosilent).

        `state`: why (refusal, stop, unread_answer, cap, threshold, by_hand, chosen), kind (the Person's kind at this site),
        stage, dispatch, text (the factory's words: the details file only), words, words_file (task-root relative), files, and
        `call` (False: never a paid call here), `block` (the waivable block code knows), `lead` (the site's own words: the
        conductor reads them first, and the fallback shows them as the body), `keep` (strings of the lead the conductor's
        question must carry, else the lead is shown above it), `fallback` (tokens to show),
        `move` (why=chosen: the move id), `token`, `lines` (a refusal's lines from `refusal_lines`: `standing_refusal` records them).
        `moves`: ids of conductor-actions.json (default all), filtered by state."""
        if str(state.get("kind") or "") in GATE_KINDS and "fallback" not in state:
            state = dict(state, fallback=list(GATE_FALLBACK))     # `site_fallback` still wins (it is never set at a gate)
        if self._in_no_move:
            raise self.last_resort(state, "")            # the seam never recurses (and journals nothing: the first failure did)
        self.standing_refusal(state)                     # AFTER the guard: a nested call never rewrites the outer one's record
        self._in_no_move = True
        try:
            action = self._no_move(state, moves)
            self.drop_standing()                         # E1: the conductor moved (`continue` / `retry`); the driver is out of the refusal
            return action
        except Refusal as exc:                           # edge 6: a refusal raised while rendering is caught, nothing else
            raise self.last_resort(state, f"the question could not be rendered ({exc.text[:100]})") from None
        finally:
            self._in_no_move = False

    def _no_move(self, state: dict, moves) -> str:
        kind = str(state.get("kind") or "conductor")
        if state.get("call") is False:                   # F1: before the exclusions - no paid call, no gate branch
            raise self.fallback_person(state, "the refusal cap was reached" if state.get("why") == "cap" else "")
        if kind in NM.EXCLUDED_KINDS:
            return self.no_move_legacy(state, kind)
        facts = self.no_move_facts(state)
        open_ids = self.open_moves(state, moves, facts)
        try:
            site = NM.site_check(state.get("site_doors"), NM.data(), self.s0_normalize)       # a door that is a move's word: unreadable (G7)
        except NM.DataUnreadable as exc:
            raise self.fallback_person(state, str(exc)) from None
        chosen = state.get("why") == "chosen"                     # a call for the token the person chose (t-722 §4.3)
        chosen_move = str(state.get("move") or "") if chosen else ""
        text = self._conductor_text(state, facts, open_ids, site, chosen)
        try:
            verdict = self._ask_conductor(text, state)
        except ConductorSpent:
            raise self.fallback_person(state, "the conductor cap was reached") from None
        while True:
            action = str(verdict.get("action") or "")
            print(f"conductor: {action} — {str(verdict.get('did') or '')[:300]}")
            if action in ("continue", "retry") and not verdict.get("options"):
                return action
            try:
                options, rule, again = self._verdict_rule(verdict, facts, open_ids, site, chosen, chosen_move)
            except NM.DataUnreadable as unreadable:      # F2 (E2.2): a bad column of the move table is the factory's defect; the answer is not used
                options, rule, again = None, f"the table of moves cannot be read ({unreadable})", False
            if not rule:
                break
            # t-1936 F2.2 (a): the question of a conductor that asked or stopped is the person's to read even when its options are refused
            refused_text = str(verdict.get("question") or "") if action in ("ask_person", "stop") and verdict.get("options") else ""   # E2.4: no options, as before
            if not again or state.get("args_refused"):
                # `continue`/`retry` with options keeps the code the state itself gives (`why=stop` -> EXIT_GAVE_UP), as before C2-6
                raise self.fallback_person(state, rule, code=None if action in ("continue", "retry")
                                           else EXIT_GAVE_UP if action == "stop" else EXIT_PERSON, conductor_text=refused_text)
            if chosen:                                  # a malformed answer to the person's CHOICE is the factory's defect, once (§4.3)
                self.no_move_defect(rule, ref=str(state.get("dispatch") or ""))
            state = dict(state, args_refused=1)
            try:
                verdict = self._ask_conductor(text + "\n\n## Your options were refused\n" + rule + "\n" + NM.rework_args_list(facts), state)
            except ConductorSpent:
                raise self.fallback_person(state, rule, conductor_text=refused_text) from None
        dropped = [str(o["token"]) for o in options if o.get("args_dropped")]
        if dropped:                                     # F2 (Fork 3-B): `args` on a move that takes none was dropped, the option kept - said once
            self.journal_conductor(stage=self.boundary.split(":")[0], action="args_dropped", args_dropped=dropped)
        if chosen and len(options) == 1:                # the `rework` decision of the person's choice: recorded, run next turn, no question
            return self.chosen_rework(state, options[0])
        raise self.options_person(state, verdict, options, action == "stop", EXIT_GAVE_UP if action == "stop" else EXIT_PERSON)

    def _conductor_text(self, state: dict, facts: dict, open_ids: list, site, chosen) -> str:
        """The prompt body of the conductor's call: the site's own account (`lead`) first - the conductor decides on what the factory
        found, not on the details file alone - then the moves open here, the factory's words, the gate's priced options, and for a
        token the person chose the paragraph of their choice."""
        lead = str(state.get("lead") or "").strip()
        text = (lead + "\n\n" if lead else "") + NM.moves_section(NM.data(), open_ids, facts, site) + "\n\n" + str(state.get("text") or "")
        if facts.get("gate"):
            text += "\n\n" + self.gate_prices(str(facts["gate"]), open_ids, facts, has_words=bool(state.get("words_file")))
        return text + ("\n\n## The person's choice\n" + self.chosen_note(state, open_ids) if chosen else "")

    def _verdict_rule(self, verdict: dict, facts: dict, open_ids: list, site, chosen: bool, chosen_move: str) -> tuple:
        """`(options, rule, again)` of one conductor answer: `rule` is why it is unusable ("" when it is usable); `again` - the conductor
        may be told the rule once (a bad "args" always, any other malformed answer only to the person's CHOICE: `chosen`, whose move
        is `chosen_move`)."""
        action = str(verdict.get("action") or "")
        verdicts = (hooklib.load_ref_json(NM.VERDICTS_FILE) or {}).get("words") or {}
        try:
            if action in ("ask_person", "stop"):
                options, rule = NM.validate_options(verdict, open_ids, NM.data(), self.s0_normalize, verdicts, site,
                                                    facts=facts, chosen=chosen, chosen_move=chosen_move)
            else:
                options, rule = None, (f"the conductor answered `{action}` with options" if action in ("continue", "retry")
                                       else f"the conductor answered `{action or 'nothing'}`")
            return options, rule, bool(rule) and bool(chosen)
        except NM.ArgsRefused as refused:
            return None, refused.rule, True            # bad "args": the conductor is told the rule and the list ONCE (§4.2 p.4)

    def chosen_note(self, state: dict, open_ids: list) -> str:
        """The paragraph "## The person's choice" of a call for a token the person chose (`why=chosen`, t-722 §4.3): the token, its
        move and what the option says; where the ORIGINAL words are (the prompt carries them whole - the token answer is not the
        instruction); the closed list of lines for `go on` with no block of code's own (§3.4); for `rework` the answer the code can run."""
        token, move, says = (str(state.get(key) or "") for key in ("token", "move", "says"))
        note = f"The person chose `{token}` (move `{move}`)" + (f': "{says}".' if says else ".")
        note += (' Their original words are under "The person\'s words" below; the token answer itself is not the instruction.'
                 if str(state.get("words") or "").strip() else " Their original words were none beyond the token.")
        if move not in open_ids:
            note += f" `{token}` is no longer open: the state it needs has changed; say so in your question."
        if move == "go_on_as_is":          # `go on` with no block of code's own (t-722 §3.4): the closed list of lines
            note += "\n" + self.standing_note(str(state.get("stage") or ""))
        if move == "rework_stage" and move in open_ids:          # a `rework` that is no longer open is not asked for (the order would be refused)
            note += ("\nWhich stage, role and cases is your judgement: answer ask_person with exactly one option, the `rework` option "
                     "carrying \"args\" from the closed list in \"Moves open here\"; the driver records it and runs it with their words "
                     "on its next step, and the person is not asked again. Do not run the rework yourself.")
        return note

    NO_REWORK_WORDS = ("You chose `rework`, and a rework is done with your words as its instruction; none are on file. "
                       "Write what should change, in your own words.")

    def chosen_rework(self, state: dict, option: dict) -> str:
        """The conductor's ONE `rework` option with "args" at a call for the person's choice: the choice is made, so this is a decision
        and not a question (t-722 §4.3, §L-5). Recorded for `seam_rework_step` with the ORIGINAL words; returns `continue`."""
        self.record_seam_rework(option["args"], str(state.get("words_file") or ""))
        return "continue"

    def record_seam_rework(self, args: dict, rel: str, preface=()) -> None:
        """The record `state["seam_rework"]` (t-722 §4.2 p.6): `args` (stage, role, cases|rows, cause), the words file of the person's
        ORIGINAL words, when, and `before` - the controller's dispatches of that stage and cause that are not this rework's, so
        `seam_rework_step` finds its own. No words on file: held, a rework is done with the person's words as its instruction. A
        controller state that cannot be read: held, never a record with an unknown `before` that would take another dispatch for its
        own (FR-59). `preface`: lines the CODE puts in front of the person's words in the rework's reason (the finding the words are
        about, critic t-1592 M-a); kept in the record, absent when there are none."""
        if not rel:
            raise self.held_question(self.NO_REWORK_WORDS)  # remains: the person's own question comes back with the reason (t-722 §4.2 p.6), not a state with no move
        found = self.controller_state()
        dispatches = found.get("dispatches") if isinstance(found, dict) else None
        if not isinstance(dispatches, dict) or not (self.state_dir / "controller.json").is_file():
            # remains: the person's own question comes back with the reason (t-722 §4.2 p.6, FR-59), not a state the driver has no move for
            raise self.held_question("Your choice could not be carried out: the factory could not read where the story stands, so "
                                     "nothing was sent back. Answer again, in your own words or with one of the words offered.")
        before = sorted(self.rework_dispatches(dispatches, args["cause"], by_person=True, stage=args["stage"]))
        self.state["seam_rework"] = {**args, "words_file": rel, "at": _now(), "before": before,
                                     **({"preface": [str(line) for line in preface]} if preface else {})}
        self.save_state()
        print(f"{args['stage']}: the rework you chose is started next, with your words")

    # The options a gate offers, by the move that executes each (C1-4b): the words stay here, the three price lines are DATA
    # (`question-prices.json` `gate_A` / `gate_B`, rendered by the ONE price helper). The prompt carries them so the conductor's own
    # options at a gate are priced the way the data says.
    GATE_OPTIONS = (("rework", "rework_stage", "the role that made this stage's work changes it with your words as its instruction; "
                                               "what follows it runs again and you see this gate again", {}),     # `stages`: built from facts, `gate_option_rows`
                    ("approve", "approve_gate", "the gate is recorded as approved with your answer as you gave it; nothing is changed first", {}),
                    ("retry", "person_does", "you change it yourself, outside the factory, then answer this gate again",
                     {"what": "the change itself, outside the factory"}),
                    ("stop", "stop_here", "stop the story here", {}))

    def gate_option_rows(self, open_ids: list, facts: dict, *, has_words: bool = True) -> list:
        """The rows of `GATE_OPTIONS` whose move is in `open_ids`, as `[{answer, token, says, slots, move}]`: the ONE source of the
        options of a gate - the conductor's prices (`gate_prices`) and the fallback question (`gate_fallback_question`) read it (FR-10).
        The `stages` slot of `rework` is built from the facts (`rework_stages`), in the story's words: the conductor names the stage,
        the person does not (t-722 §5.1). `has_words` False (the question carries no `asked.words_file`): `approve_gate` is not a row -
        its road records the ORIGINAL answer from that file, so there is no such road to show or to price (C4-14, the same rule
        `gate_fallback_question` applies before it asks)."""
        import handoff_check
        open_ids = [move for move in open_ids if has_words or move != "approve_gate"]
        named = [self.stage_place(stage) for stage in (facts.get("rework_stages") or [])]
        listed = handoff_check._or_list(named) if named else ""        # the package's one "A, B or C" joiner
        slots = {"stages": "the stage the conductor names" + (f" — {listed} —" if listed else "") + " and the stages after it up to this gate"}
        return [{"answer": answer, "token": answer, "says": says, "slots": slots if move == "rework_stage" else others, "move": move}
                for answer, move, says, others in self.GATE_OPTIONS if move in open_ids]

    def gate_prices(self, gate: str, open_ids: list, facts: dict, *, has_words: bool = True) -> str:
        """"The price lines of the options open at gate `gate`", from the data rows `gate_A` / `gate_B` (one site per key: the census
        of question ids reads the literal). A row the data lacks shows the option with no price lines and ONE defect (`priced_section`)."""
        options = self.gate_option_rows(open_ids, facts, has_words=has_words)
        section = self.priced_section("gate_A", options) if gate == "A" else self.priced_section("gate_B", options)
        return "## The options at this gate\nWhen you offer one of these, use its lines:\n\n" + str(section)

    def options_person(self, state: dict, verdict: dict, options: list, stopped: bool, code: int) -> Person:
        """The Person for a conductor's usable options. The site's own `lead` goes ABOVE the conductor's prose when the prose
        drops a fact the site marked in `keep` (its record path): what the factory did is never replaced by the conductor's
        wording. Price labels that cannot be read end in the last-resort question and one defect_found, never in unpriced options."""
        prose = ("The conductor stopped the story:\n\n" if stopped else "") + str(verdict["question"]).strip()
        lead = str(state.get("lead") or "").strip()
        if lead and any(str(fact) not in prose for fact in state.get("keep") or ()):
            prose = lead + "\n\n" + prose
        try:
            labels = human_text.price_labels()
        except human_text.LabelsUnreadable as exc:
            return self.last_resort(state, f"the price labels could not be read ({exc})", lead=lead, code=code)
        return self._person_of(dict(state, why_person=verdict.get("why_person"), checked=verdict.get("checked"), source="conductor"),
                               NM.render_question(prose, options, labels), options, code=code)

    def no_move_legacy(self, state: dict, kind: str) -> str:
        """The S1 review until C1-3 gives it an executor (the gates left in C1-4b): today's behaviour. The conductor is called with
        the site's prompt and no options; `ask_person` with a question re-raises it as `kind`, with none it is printed and
        journalled and the loop goes back to `where`; `stop` ends the run (exit 4); the cap raises today's Person."""
        stage = str(state.get("stage") or self.boundary.split(":")[0])
        dispatch = str(state.get("dispatch") or "")
        try:
            verdict = self._ask_conductor(str(state.get("text") or ""), state)
        except ConductorSpent as spent:
            raise Person("conductor", f"The conductor was called {spent.count} times at {self.boundary} and the block "
                         f"stands. Last refusal:\n\n{spent.refusal}\n\nWhat should happen? (your word passes any "
                         "block: it is recorded with waiver.py / release by the conductor)",
                         stage, dispatch) from None
        action = verdict.get("action")
        if action in ("ask_person", "_unreadable"):
            self.pass_to_person(dict(verdict, action="ask_person", question="" if action == "_unreadable" else verdict.get("question")),
                                kind, stage, dispatch)
        elif action == "stop":
            raise Stop(EXIT_GAVE_UP, str(verdict.get("question") or verdict.get("did")))
        return action if action in ("continue", "retry") else "continue"

    def conductor_round(self, refusal: Refusal, stage: str, *, words: str = "", recover_failed: str = "",
                        committed: bool = False) -> str:
        """The conductor call an unmatched refusal gets, and what its verdict means: 'continue' or 'retry',
        or a Person / Stop. Split out of `handle_refusal` (t-211) so the gate-entry repair can hand its list
        over through the SAME call without passing the text through `match_known`: the table matches
        anywhere in a text, and a finding that happens to hold `already completed` or `expected_revision`
        would turn into `continue` or `retry` and loop (the list is the factory's own words, not a refusal).

        `recover_failed` is what the controller's `recover` said when a known row ran it and it refused
        too (the conductor is shown both texts); `committed` says the refused event is already in the
        journal, so a `retry` verdict is read as `continue`. The gate-entry caller (`hand_to_conductor`)
        passes neither: its behaviour is the table-less call it always was."""
        shown = refusal.text
        if recover_failed:
            shown = (refusal.text + "\n\n## `controller.py --operation recover` was run for it and "
                     "refused too\n" + recover_failed)
        action = self.no_move({"why": "refusal", "kind": "conductor", "stage": stage, "dispatch": self.refusal_dispatch(refusal),
                               "text": shown, "words": words, "files": refusal.files, "lines": self.refusal_lines(refusal)})
        if committed and action == "retry":
            # The event of this refusal is IN the journal: running the action again would write
            # it twice (`story_step start` would dispatch a second time). `retry` has no meaning
            # here, so it is read as the nearest thing that does: back to `where`. Any other
            # row keeps what `retry` means - its action was refused, nothing was committed.
            print("conductor: `retry` of a committed event is read as `continue` - the action is not repeated")
            return "continue"
        # `continue` / `retry` after a conductor move; anything else was a Person raised by the seam (never a silent return).
        # An `ask_person` with no question, or no usable options, is not an answer and the refusal is not pasted in place of
        # one: the seam renders the priced fallback question and journals the factory's own defect (once).
        return action

    def unread(self, kind: str, stage: str, dispatch: str, text: str, words: str = "", block: str = "", *,
               doors=None, lead: str = "", again=None) -> str:
        """An answer none of the branches of `take_answer` read (or one a question offered no token for): the seam, with the
        words verbatim and the file that holds them whole (C1-1: `why=unread_answer`). Returns `continue` / `retry` after a
        conductor move, else raises the Person with the priced options. EVERY `--answer` is new words (D-0041): this always calls
        the conductor (under the cap); the question without a call is the site's own, raised by a rerun with no `--answer`.

        A CLOSED question that reads only its own words (S0, `package`, `ticket_changed`; C1-3) passes `doors` - a TUPLE of its
        tokens (a dict gives its keys) - so the conductor may offer them back (`retry` / `go on` as the moves they are, any other
        as `site_door`), `lead` - the one sentence that says the answer was not read - and `again(lead)` - the Person that
        shows the SAME question again, which the seam raises when the conductor cannot answer. `stop` is always a door."""
        state = {"why": "unread_answer", "kind": kind, "stage": stage, "dispatch": dispatch, "text": text,
                 "words": words, "words_file": self.answer_file(), "block": block}
        if doors is None:
            return self.no_move(state, None)
        tokens = [self.s0_normalize(token) for token in doors]
        moves = [NM.TOKEN_MOVES[token] for token in NM.TOKEN_MOVES if token in tokens or token == "stop"]
        state.update(lead=lead, site_doors=tuple(token for token in tokens if token not in NM.TOKEN_MOVES), site_fallback=again)
        return self.no_move(state, moves)

    @staticmethod
    def generic_prompt(kind: str, stage: str, qtext: str, items_text: str = "") -> str:
        """The conductor's prompt for an answer of kind `kind` that no branch of `take_answer` read.

        `items_text` (RH1-6): a gate's APPROVAL that the controller refused over open items - the prompt then says the approval was heard
        and kept (`open_items_text`), not "words that are not the approval word" (which would be a lie about whose refusal it is)."""
        if kind in GATE_KINDS and items_text:
            return items_text + " " + MOVES_RULE + " " + OWN_TOKEN_RULE + " " + GATE_RULE + "\n\n## The question\n" + qtext[:8000]
        if kind in GATE_KINDS:
            # C1-4b: a gate answer that is not the approval word. The conductor PROPOSES and never records the gate decision (I6);
            # the options it may offer carry the moves of the gate (`approve` / `rework` / `retry`), each executed by the driver.
            return (f"The person answered the driver's question of kind `{kind}` at {stage} with words that are not the approval "
                    "word of the gate, so nothing is recorded as approved. " + MOVES_RULE + " " + OWN_TOKEN_RULE + " " + GATE_RULE
                    + "\n\n## The question\n" + qtext[:8000])
        return (f"The person answered the driver's question of kind `{kind}` at {stage}. Record "
                "their words with the factory's own commands (waiver.py --block/--remark for items, "
                "stage_done --set for "
                "story facts, release for a dead dispatch, log_append for anything else) so the "
                "block stands lifted and the loop continues. "
                # Every kind that lands here may be answered with a token of the conductor's own options (C1).
                + MOVES_RULE + " " + OWN_TOKEN_RULE
                + "\n\n## The question\n" + qtext[:8000])

    def funnel(self, state: dict) -> int:
        """The run()-level handler of the seam: `call=False` (no paid call, `no_move` always raises) unless the state carries the
        words file of an answer being taken - those words are new (D-0041, t-671 Q12), so the conductor reads them like any other
        unread answer. The Person the seam raises is handed to `ask()` (the exit code). A conductor `continue` / `retry` leaves the
        answer on the record and the refusal standing in the story's state: the free question comes back, nothing is lost. The
        handlers raise only `Person`, so nothing escapes an `except` clause."""
        free = dict(state, call=False)
        try:
            self.no_move(state if state.get("words_file") else free, None)
            self.no_move(free, None)
        except Person as person:
            return self.ask(person)
        raise AssertionError("no_move(call=False) returned: the seam always raises a Person here")   # not a code path

    # --- the person's answer -----------------------------------------------------------------

    def judged_reply(self, qtext: str, words: str, kind: str) -> str:
        """What the judge reads in the person's own words, as a pre-filled option (J6).

        `gate_reply_intent` and `gate_stand_gap_option` were in the registry, calibrated at 0.9,
        and called only by an orchestrator a phase file instructs - in a driver run nothing asked
        them, so every answer in a person's own words went to a conductor session that spent its
        first turns deciding which option that was. This asks for them at the boundary, in code.

        It records NOTHING. A gate decision is the person's authority and their verbatim words are
        what gets written, by the conductor, with the factory's own command; the judge only saves
        the turns spent asking "did you mean approve or approve with edits". That line is the
        plan's own (section 10.6): the judge does not pass a gate, does not lift a block and does
        not authorise a write. What it buys is that the reading is printed back to the person here,
        in the log, where a misread is visible at once instead of after the write.
        """
        try:
            import judge_reply
        except Exception:                                # pragma: no cover - broken install
            return ""
        try:
            if "stand" in kind or "stand gap" in qtext.lower()[:2000]:
                got = judge_reply.stand_gap_option(words, ticket=self.task, stage=self.boundary)
            else:
                got = judge_reply.intent(qtext, words, ticket=self.task, stage=self.boundary)
        except Exception as exc:
            return f"the judge could not be asked ({type(exc).__name__}); decide from the words"
        if got.get("status") != "ok":
            return ""
        value, leaning = got.get("value"), got.get("leaning")
        read = value or leaning
        if not read:
            return ""
        line = (f"{read} (confidence {got.get('confidence')}, {got.get('judgment')}, "
                + ("decided" if got.get("decided") and value else "a leaning only") + ")")
        print(f"the judge reads their answer as: {line}")
        return line
