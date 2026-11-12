"""driver_dialog.py - Driver members and names homed here by ai-packages/qa-factory/scripts/tests/fixtures/driver-layers.json (TD-11 cut by tools/source_split.py); no behaviour of its own."""

import hooklib  # noqa: F401 (console setup, K7)
import hashlib
import re
from pathlib import Path
import human_text
import person_owned as PO
from driver_core import EXIT_GAVE_UP, EXIT_PERSON, GATE_KINDS, Person, Priced, REFUSALS_PER_BOUNDARY, Refusal, STUCK_REPEATS, Stop, _append_jsonl, _now, _read_json, _read_jsonl, _write_json


# The closed answers a question put to the person offers (C7): the code reads a token only when the WHOLE answer is
# the token (`s0_normalize`), never by a phrase inside it (FR-12); any other words go to the conductor with the words.
TOKEN_ANSWERS = (
    "What I need is a decision. Answer with exactly one of these words:\n"
    "`retry` — you deal with what is in the way, and I look again;\n"
    "`go on` — go on without it; I record your words as the reason the story carries;\n"
    "`stop` — stop the story here.")

# One source for the machine head above a question: `head_pattern` in references/human-text.json.
# The text hashed here and the text checked by `human_text.problems` lose the same lines. The
# pattern is line-based on purpose: with re.S a `.` in it eats the rest of the document, which is
# how the first version of this hashed every question to the same empty body.
QUESTION_HEAD_RE = human_text.HEAD_RE

ANSWER_BLOCK_RE = re.compile(r"\n---\nAnswer:.*", re.S)


def question_body_sha(text: str) -> str:
    """The identity of a question's BODY: its head (timestamp, ids) and its answer block are
    not part of what is being asked, so two asks of the same thing hash the same.

    FR-7 is the rule this serves: a boundary a person has answered is never re-asked with the
    same text. One `resolve_return` packet reached the person three times unchanged in run 5,
    because nothing compared what was being asked with what had already been answered."""
    body = QUESTION_HEAD_RE.sub("", str(text or ""), count=1)
    body = ANSWER_BLOCK_RE.sub("", body)
    return hashlib.sha256(" ".join(body.split()).encode("utf-8")).hexdigest()


class DriverDialog:
    # --- what the driver itself says to a person, in words ---------------------------------

    def stage_place(self, stage: str) -> str:
        """`the plan stage (S3)`: where the story is, as a person names it (stages.json holds the
        name); `stage S3` when the name is unknown, `this story` when there is no stage."""
        name = ""
        try:
            name = str((self.stages().get(stage) or {}).get("name") or "").strip().lower()
        except Exception:
            pass
        if stage and name:
            return f"the {name} stage ({stage})"
        return f"stage {stage}" if stage else "this story"

    @staticmethod
    def role_words(role: str) -> str:
        """`qa-test-strategist` -> `test strategist`: a role as a person names it."""
        return re.sub(r"^qa-", "", str(role or "")).replace("-", " ").strip() or "role"

    def halt_text(self, stage: str, role: str, digest: str, *, again: bool = False) -> str:
        """What a person reads when a role hands the decision back, in plain words.

        TP1-13877: the halt led with a dispatch id and pasted the role's whole final message
        under it, and the check that reads the form found nothing (FR-6). The body says which
        stage stopped and which role, then one line per row the role reported - the row's id and
        its own reason, never its state word; the message itself goes to the details file
        (`Person.details`). A header that does not parse, or no rows, means the role gave no
        reason we can read, and the text says exactly that (FR-41) instead of guessing one."""
        import role_digest
        # The rows are read from the halting header `is_halting` finds - on ANY line, so prose
        # above it does not hide them; with no halting header there is no row to trust (FR-41).
        rows, digest_lines = [], role_digest._lines(digest)
        for index, line in enumerate(digest_lines):
            header, error = role_digest._parse_header(line)
            if not error and header.get("verdict") in role_digest.HALTING_VERDICTS:
                rows = role_digest.parse("\n".join(digest_lines[index:])).get("rows") or []
                break
        lines = []
        for row in rows:
            if row.get("state") == "ok":
                continue
            reason = " ".join(str(row.get("reason") or "").split())
            lines.append(f"- {row.get('id')} — {reason or 'the report gives no reason'}")
        place = self.stage_place(stage)
        words = self.role_words(role)
        stop = self.STOP_OPTION
        reported = ("What it reported:\n" + "\n".join(lines) if lines else
                    "It gave no reason in its report; its own words are in the file named below.")
        if stage == "S1" and self.s1_has_no_diff():
            # F7: the scout's manifest says no change was found (`implementation.source: none`). Its answers all go to the
            # scout as words (the halt road, kind `halt`; `not built yet` first records the side, see below); the question is phases/s1.md's, priced. Like every halt kind it keeps
            # what the role reported (FR-8/FR-35: the rows are the role's own verdict, the manifest only picks the question) and
            # says `again` when the role stopped a second time.
            return self.closed_question(
                "s1.no_diff",
                f"No implementation was found for {self.task}.{f' The {words} stopped on it again.' if again else ''}\n\n"
                f"{reported}\n\nTesting without grounding is a decision, so pick one:",
                [{"answer": "change", "says": "give me the change: a merge request, a branch or a commit, in your own words",
                  "slots": {"role": f"the {words}", "what": "the merge request, branch or commit"}},
                 {"answer": "lives", "says": "name where it already lives: the stand and the repository in which the change is in "
                                              "place; the tests are grounded on the current code, not on a change",
                  "slots": {"role": f"the {words}", "what": "the stand and the repository"}},
                 {"answer": "ungrounded", "says": self.UNGROUNDED_SAYS, "slots": {"role": f"the {words}"}},
                 # the twin of `s0.no_change` (AR-19): the same answer, the same words (one constant). Its executor is `take_answer`'s
                 # `s1.no_diff` branch (`_answer_s1_not_built`, PC-7 B3): it records `pipeline.sides.product` absent and deliverable.
                 {"answer": "not built yet", "says": self.NOT_BUILT_YET_SAYS, "slots": {"role": f"the {words}"}},
                 stop])
        held, block = self.halt_questions(stage, words)
        asked = self.closed_question(
            "halt",
            f"{place[:1].upper()}{place[1:]} stopped{' again' if again else ''}: the {words} cannot go on without a decision.\n\n"
            + reported + held,
            [{"answer": "words", "says": "answer in your own words ('go on without it' is an answer); the same role continues "
                                         "in its own session with your words", "slots": {"role": f"the {words}"}}, stop])
        # B2 (HF2-7): the "how to answer" block stands BELOW the priced section (a text a person reads obeys the order of
        # human-questions.md); the tokens the text prices are the section's own
        return Priced(str(asked) + ("\n\n" + block if block else ""), asked.priced)

    def halt_questions(self, stage: str, words: str) -> tuple:
        """`(the one-decision line and the cards, the answer block)` of a halt at S2-S4 over a register that has open questions, else
        `("", "")` (B2). The role stopped and the factory also holds questions open: the person is shown them HERE, with how to answer
        them by id, because the halt road records those lines by code (`_unread_halt_or_review`) before the conductor is called (FR-48).
        The cards and the block come from `question_stop` (`open_cards`, `answer_block`: the one builder of each, AR-13/AR-15); at a halt
        the only word read as a whole answer is `stop` (`whole=("stop",)`). A failed read shows the halt as it always was."""
        try:
            import question_register as QR
            import question_stop as QS
            if f"{stage} stop" not in QR.vocabulary()["where"]:
                return "", ""
            cards = QS.open_cards(self.task_root)
            block = QS.answer_block(self.task_root, ("stop",)) if cards else ""
        except Exception as exc:
            print(f"note: the open questions could not be added to the halt ({type(exc).__name__}: {exc}); it is shown without them")
            return "", ""
        if not cards:
            return "", ""
        return ("\n\nThis is one decision: what the " + words + " should do about the stop above. The factory also holds the "
                "questions below open; if your answer settles any of them, put it on its own line by its id (see \"How to answer\" "
                "below); the ones you leave out are asked again later.\n\n" + "\n".join(cards), block.rstrip("\n"))

    @staticmethod
    def stuck_facts(controller_state, pipeline, stage: str, *, place=None, ids: bool = True) -> list:
        """B-20 (t-1988 N5, AR-22/AR-17): what CODE can read about the stages before `stage` that are not completed - one line per stage:
        its status, what the acceptance of its consumer says (awaited for a dispatch, or standing for it) and the controller's `reason`.
        Pure data, no judgment (AR-29): the lines are facts for the conductor, not a verdict on why the step comes back. An unreadable
        controller state or pipeline gives `[]` (FR-41: an unknown is not reported as a fact), and so does a story with no earlier stage open.
        `ids=True` (default): the factory's own lines, dispatch ids and the raw `reason` included (the conductor's text and the details file).
        `ids=False`: the PERSON's lines (F3, FR-6): the stage named by `place(stage)` (default `stage Sn`) and the role in plain words, no
        dispatch id and no raw reason."""
        import acceptance
        if (not isinstance(controller_state, dict) or not isinstance(controller_state.get("stages"), dict)
                or not isinstance(pipeline, dict) or not pipeline or not re.fullmatch(r"S\d+", stage or "")):
            return []
        lines = []
        for number in range(int(stage[1:])):
            name = f"S{number}"
            entry = controller_state["stages"].get(name)
            status = entry.get("status") if isinstance(entry, dict) else None
            if not isinstance(status, str) or status in ("completed", "skipped"):
                continue        # a stage whose row cannot be read is not reported as a fact
            parts = [f"{name} {status}" if ids else f"{place(name) if place else f'stage {name}'} is {status}"]
            consumer = acceptance.consumer_of(name)
            if consumer:
                who = consumer.removeprefix("qa-").replace("-", " ")
                awaited = acceptance.awaits_acceptance(controller_state, name, pipeline)
                author = acceptance.stage_author_dispatch(controller_state, acceptance.stage_def_of(name))
                role = ((controller_state.get("dispatches") or {}).get(author) or {}).get("role") if author else None
                work = f"the work of the {DriverDialog.role_words(role)}" if role and not ids else "its author's work"
                if awaited:
                    parts.append(f"acceptance by the {who} is awaited for {awaited}; no accept record stands for it" if ids
                                 else f"the {who} has not accepted {work} yet")
                elif author and acceptance.accepted_for(pipeline, name, author):
                    parts.append(f"acceptance by the {who} stands for {author}" if ids else f"the {who} accepted {work}")
                else:
                    parts.append(f"no accept record stands for the {who}'s acceptance" + (f" of {author}" if author else "") if ids
                                 else f"no acceptance by the {who} is recorded")
            if ids and isinstance(entry.get("reason"), str) and entry["reason"].strip():
                parts.append(f"reason: {entry['reason'].strip()[:300]}")
            lines.append("; ".join(parts))
        return lines

    def stuck_facts_for(self, stage: str) -> tuple:
        """`(person lines, factory lines)` of `stuck_facts` for the live story: the first for the text a person reads, the second for the
        conductor's text and the details file. A state that cannot be read gives `([], [])` (facts are an aid, not a gate)."""
        try:
            state, pipeline = self.controller_state(), self.pipeline()
            return (self.stuck_facts(state, pipeline, stage, place=self.stage_place, ids=False),
                    self.stuck_facts(state, pipeline, stage))
        except Exception:  # noqa: BLE001
            return [], []

    def stuck_text(self, stage: str, *, waits_on_person: bool = False, facts=(), answered=None) -> str:
        """The driver asked `where` four times (`STUCK_REPEATS`) and got the same answer: it stops instead of
        asking a fifth. The answer itself (a JSON line) goes to the details file. `facts`: the lines of `stuck_facts`, put under the lead
        instead of "I cannot tell from here" (none: today's lead). `answered`: the record `{answer, at}` of the person's earlier answer to
        this very step (`state["stuck_asked"]`): said as new text, never the same question again (FR-7)."""
        at = f"at {self.stage_place(stage)}" if stage else "on this story"
        holding = ("I cannot tell from here what is holding it. The step's own answer is in the file named below, if you want it.")
        if facts:
            holding = "What the factory can read about the earlier stages:\n" + "\n".join(f"- {line}" for line in facts)
        if waits_on_person:      # t-698 sec. 21 (ii): S7 waits on the person's recorded `open_work`; the caller (the loop) reads it
            holding = ("What holds it: you decided to keep this stage open for more work, so the factory asks you before it closes it; "
                       "it does not close it over your word.")
        again = (f"You answered {answered['answer']} at {answered['at']}; the same step still comes back, so asking the same question again "
                 "would not move it.\n\n" if isinstance(answered, dict) and answered.get("answer") else "")
        return (f"The driver stopped {at}: the same step came back {({4: 'four'}).get(STUCK_REPEATS, STUCK_REPEATS)} times in a row with nothing "
                "changing in between, so I stopped instead of repeating it.\n\n" + again + holding)

    def refused_text(self, stage: str) -> str:
        """Six refusals in a row at one boundary. Each refusal is written for the role or the
        script that met it; the last one goes to the details file, whole."""
        at = f"at {self.stage_place(stage)}" if stage else "on this story"
        # C2-7 §5.5: the story's own words for what is missing. The `cap` is raised at ANY boundary (a gate, a waiting job, a closed story
        # after the retro), so with no stage the lead says nothing about a stage (FR-41): only that the reasons are the factory's own.
        missing = f"{self.stage_place(stage)} has not finished, and the reasons it was" if stage else "the reasons it was"
        facts = self.stuck_facts_for(stage)[0] if stage else []       # B-20 F3: the same person-safe facts as the stuck lead (no ids)
        known = ("\n\nWhat the factory can read about the earlier stages:\n" + "\n".join(f"- {line}" for line in facts)) if facts else ""
        return (f"The driver stopped {at}: {REFUSALS_PER_BOUNDARY + 1} times in a row a check of the factory's own turned "
                "the same move back, so I stopped instead of trying again.\n\n"
                "I cannot put those reasons into the story's own words - they are written for the "
                "script that met them, not for you. The last one is in the file named below, if you "
                "want it.\n\n"
                f"What the story is missing: {missing} turned back are written for the factory's own scripts, "
                f"so I cannot tell which answer {'of that step ' if stage else ''}would move it." + known)

    def refuse_case(self, plan, case: str, reason: str, door: str, by: str, by_first: bool = False) -> bool:
        """TR4-3 (AR-14, AR-15): the ONE writer of `{"refused": {reason, door, by}}` in a case's request.json - the refusal a later reader
        (the report, gate B, the delivery check) finds. With a `plan` the case also joins `plan["refused"]` as `(case, reason)`; `manual_close`
        has no plan (its list is local) and passes None. A write that fails is swallowed: the caller's printed line still names the case and
        the receipt still carries it. Nothing is checked here: an empty `door` or `by` and a case outside the plan are written as given, as
        every caller did before. Returns True when the record was written, False when the write failed (`deferred_decision` says so). `by_first` keeps the key order of the one caller that wrote `by` before `door` (byte-equal records)."""
        import manual_evidence as ME
        if plan is not None:
            plan["refused"].append((case, reason))
        record = {"reason": reason, "by": by, "door": door} if by_first else {"reason": reason, "door": door, "by": by}
        try:
            _write_json(ME.request_path(self.task_root, case), {"refused": record})
        except OSError:
            return False        # the caller's printed line still names the case; a caller that must say it reads the False
        return True

    # --- questions for the person ----------------------------------------------------------

    def question_path(self, answered: bool = False) -> Path:
        return self.state_dir / ("driver-question.answered.md" if answered
                                 else "driver-question.md")

    def reconcile_question(self) -> str:
        """The file a person reads and the `asked` flag the loop reads are two halves of one
        fact, and until they were written by one operation a story could hold half of it: a flag
        whose file had been deleted (the loop waits for an answer to a question nobody can read)
        or a file left behind after the answer landed (the person answers it twice). Both halves
        are repaired here, at startup, and the repair is PRINTED - a story silently put back on
        its feet is how the first half went unnoticed in the first place (P6)."""
        asked, path = self.state.get("asked") or {}, self.question_path()
        if not (asked.get("kind") and path.is_file()):
            self.drop_standing()               # E4: no question is open, so no refusal stands (a record a crash left behind)
        if asked.get("kind") and not path.is_file():
            self.state["asked"] = {}
            self.save_state()
            return (f"the open question ({asked.get('kind')} at {asked.get('stage') or '?'}) has "
                    f"no {path.name}: the flag is cleared and that step will run again")
        if path.is_file() and not asked.get("kind"):
            if not self.dry:
                path.replace(self.question_path(answered=True))
            return f"{path.name} was left behind with no question open: filed as answered"
        return ""

    def ask(self, person: Person) -> int:
        path = self.question_path()
        head = [f"# Driver question — {self.task}", f"kind: {person.kind}", f"stage: {person.stage}",
                f"dispatch: {person.dispatch}", f"asked_at: {_now()}", ""]
        tail = ["", "---", "Answer: write your words to a file and run",
                f"  python {self.scripts / 'story_run.py'} --task {self.task} --answer <file>"]
        if person.answer_note.strip():
            tail += ["", person.answer_note.strip()]
        waiting = len(self.deferred_items())            # RN1-24: one line, never the texts (FR-6: one question to a file); `defer_question` asks without it
        if waiting and not getattr(self, "_deferring", False):
            tail += ["", f"{waiting} more question(s) wait; they are asked before gate B."]
        # The factory's own words go beside the question, never instead of it: a refusal is
        # written for the role that called the script, and on TP1-13797 run 5 all twelve
        # questions that carried one reached the person with detector lines, form field paths
        # and an exit code in them (references/human-questions.md, "what the text may never
        # carry"). The file is named here, in the one block where a path is an instruction.
        if person.details.strip():
            details = self.state_dir / "driver-question-details.md"
            details.parent.mkdir(parents=True, exist_ok=True)
            details.write_text(f"# The factory's own words — {self.task}, {person.kind} at "
                               f"{person.stage or 'the story'}\n\nThis is what the check printed, "
                               "in its own vocabulary. It is here because you may want it, not "
                               "because it is the question.\n\n```\n" + person.details.strip() +
                               "\n```\n", encoding="utf-8")
            tail.append("")
            tail.append(f"{self.DETAILS_POINTER}, if you want them: "
                        f"qa-factory/artifacts/{self.task}/"
                        f"{details.relative_to(self.task_root).as_posix()}")
        body = list(head) + [person.text]
        # The question is compared the way `take_answer` hashed it: as the FILE reads, head first. A text that opens with a `# ` title
        # (the gate packet's `# Gate B - T`) lost that line to the head pattern here and kept it in the file, so a gate asked again
        # with the same text never met its own earlier answer (FR-7).
        earlier = self.already_answered("\n".join([*head, person.text]))
        if earlier:
            # FR-7: it either moves or comes back changed. The driver cannot know what the
            # earlier answer failed to settle - if it knew, it would not be asking - so it says
            # what it does know: this is the same question, here is what you said and when, and
            # here is the state it left. One `resolve_return` packet reached the person three
            # times word for word in run 5 because nothing compared the two.
            body += ["", "---", "**You have answered this exact question before** — "
                     f"{earlier.get('ts', 'earlier')}, and it did not settle it:", "",
                     "> " + str(earlier.get("words") or "")[:600].replace("\n", "\n> "), "",
                     "The factory is asking again because the boundary has not moved. If the "
                     "answer above still stands, say what should happen when it is followed and "
                     "the block is still there — including stopping the story."]
        text = "\n".join(body + tail)
        self.judge_own_question(person, text)
        # The flag first, the file second, and the file is what `reconcile_question` trusts: a
        # crash between the two leaves a flag with no file, which is the half it can repair.
        self.state["asked"] = {"kind": person.kind, "stage": person.stage,
                              "dispatch": person.dispatch, "at": _now()}
        if person.offered:
            # A question the seam (`no_move`) raised: `take_answer` reads a token against THESE, and a question of any other
            # origin carries none, so no other answer is captured (C1-1). The delivery flag (set by `delivery` alone for ITS
            # question) is not cleared here: `take_answer` ignores it for a question that carries `offered`, so "no delivery"
            # cannot be taken by the delivery branch as an answer to this one.
            self.state["asked"].update(offered=list(person.offered), options=list(person.options),
                                       words_file=person.words_file, why=person.why, block=person.block)
            if person.rows:
                self.state["asked"]["rows"] = list(person.rows)
            if person.probe_gap_cases:
                self.state["asked"]["probe_gap_cases"] = list(person.probe_gap_cases)
            if person.probe_judgment_cases:
                self.state["asked"]["probe_judgment_cases"] = list(person.probe_judgment_cases)
        if person.kind == "s1_gap":
            # POSITION INVARIANT: this kind ALONE gets the fields (a question of another kind never carries them, so the answer branch
            # of `s1_gap` cannot be reached by one), and a question the seam raised (`offered`) is never an `s1_gap`.
            self.state["asked"].update(sources=list(person.sources), classes=list(person.classes))
        if person.held_lead:
            self.state["asked"]["held_lead"] = person.held_lead
        if person.why_person:
            self.state["asked"]["why_person"] = person.why_person      # the class travels to the word the answer records (`waiver_road`)
        if person.kind in ("conductor", "refusal"):
            # The named blocks of the question (t-217 C8): written for conductor and refusal questions - an EMPTY
            # list until the parser that reads them from `details` lands (t-228). The KEY is what matters now: a
            # question asked by this driver carries it, so `take_answer` never reads a dispatch out of its text,
            # while a question an older driver asked (no key) keeps the legacy text reading.
            self.state["asked"]["blocks"] = []
        # The stand question's answer branch (`take_answer`) is keyed on this flag, so the flag is
        # written HERE and nowhere else: it names the stage for the Person `stand_check` raised, and
        # is gone for every other question. A flag that outlived its question captured the answer
        # to a later one at the same stage (t-037: `retry` to an `environment_job` question was
        # recorded as a stand answer and nothing else happened).
        stand_stage = getattr(person, "stand_stage", "")
        if stand_stage:
            self.state["stand_question"] = stand_stage
        else:
            self.state.pop("stand_question", None)
        # The same rule for the stand-login question (t-292): `take_answer`'s branch for it is keyed on this flag,
        # which is set HERE and nowhere else, from the Person `stand_login_gate` raised, and gone for every other
        # question - so the answer to another question can never be taken as the answer to this one.
        login_cases = getattr(person, "login_cases", None)
        if login_cases:
            self.state["login_question"] = {"stage": person.stage, "cases": list(login_cases)}
        else:
            self.state.pop("login_question", None)
        # And for the stand-BUILD question (t-300 N1b): `take_answer`'s branch for kind `stand_identity` is keyed on this
        # flag, set HERE and nowhere else, from the Person `build_check` raised, and gone for every other question. It
        # carries the whole packet the answer needs (the stand, the profile, the variant, the commits, what was offered).
        build_question = getattr(person, "build_question", None)
        if build_question:
            self.state["build_question"] = dict(build_question)
        else:
            self.state.pop("build_question", None)
        self.save_state()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        self.progress_line()            # the question is on record (`asked`): a gate is reached by being asked
        print(text)
        return person.code

    def already_answered(self, question: str) -> dict:
        """The answer this exact question got before, or {}.

        The comparison is the body's hash, written into `driver-answers.jsonl` when the answer
        was taken: the head carries a timestamp and the answer block carries a path, so two asks
        of the same thing differ in both and are the same question."""
        wanted = question_body_sha(question)
        found = {}
        for row in _read_jsonl(self.state_dir / "driver-answers.jsonl"):
            if row.get("question_sha") == wanted:
                found = row
        return found

    def judge_own_question(self, person: Person, text: str) -> list:
        """Does the text we are about to show obey `references/human-questions.md`?

        Never a reason not to ask: our defect is not the person's problem, and a question
        withheld is worse than a question worded badly. It is printed and journalled, so the
        share of questions that break our own rules is a number the next run can read instead
        of an impression (FR-41: the defect is stated, not hidden). Measured on run 5: of the
        twelve questions the conductor wrote, seven obeyed the rules on their own and all
        twelve broke them as the person saw them, because the refusal was glued underneath."""
        try:
            import human_text
            # `offered` UNION `priced`: a question is "own" when either set names the token (G20); `priced` is never in `asked`
            found = human_text.problems(text, offered=list(dict.fromkeys([*person.offered, *getattr(person, "priced", ())])) or None)
        except Exception as exc:  # a missing rules file must never cost a question
            print(f"question rules: not checked ({type(exc).__name__}: {exc})")
            return []
        _append_jsonl(self.state_dir / "driver-questions.jsonl",
                      {"ts": _now(), "kind": person.kind, "stage": person.stage,
                       "dispatch": person.dispatch, "bytes": len(text.encode("utf-8")),
                       "details_file": bool(person.details.strip()),
                       "problems": [p["rule"] for p in found],
                       # RN1-9: the class the question answers (None when it carries none), what was read, who raised it (calibration check 38)
                       "source": person.source, "why_person": person.why_person or None, "checked": person.checked or None,
                       "class_check": PO.status(),
                       # N16 (C2-9): the detector reads the causes a gap question carried, for `s1_gap` ALONE
                       **({"causes": list(person.classes)} if person.kind == "s1_gap" else {})})
        if found:
            print(f"question rules: this text breaks {len(found)} rule(s) of "
                  "references/human-questions.md — asked anyway, recorded as ours:")
            for item in found:
                print(f"  - {item['rule']}: `{item['found'][:80]}`")
        return found

    # --- a question about SOME manual cases waits; the independent work goes on (RN1-24, P22) -----------------------

    # LOCAL-1 (02.11.2026): one question about one manual case stopped the stages that did not depend on it. The question is rendered
    # by `ask()` exactly as a live one (the same text, the same `driver-questions.jsonl` row), kept in `state/deferred-questions/<n>.md`
    # and `state["deferred"]`, and asked one by one before gate B (`deferred_step`; the owner's FK-3 (a): no new reading of words, the
    # executors of the original question answer). The skill road has no code for it yet: s6.md carries the rule (AR-19, SC5-3).
    DEFER_FLAGS = ("login_question", "stand_question", "build_question", "gate_a_dry")      # the flags `ask()` / its Person set for a question

    def deferred_items(self) -> list:
        """The deferred questions in the order they were deferred; `[]` when there is none or the record is not a list (an unreadable
        record is no question: `deferred_step` never invents one)."""
        raw = self.state.get("deferred")
        return [item for item in raw if isinstance(item, dict) and item.get("n") is not None] if isinstance(raw, list) else []

    def deferred_waiting(self, cases) -> list:
        """`[(case, n)]` for the cases of `cases` a deferred question holds (the order of `cases`)."""
        held = {str(case): item["n"] for item in self.deferred_items() for case in item.get("holds") or []}
        return [(case, held[case]) for case in cases if case in held]

    def deferrable(self, person: "Person") -> bool:
        """May this question wait while the independent work goes on? True only when ALL hold: it names cases (`holds`); its kind is not
        a gate (a gate is the stop itself); it is not the conductor's `stop` (exit 4); its cases are not already held by another
        deferred question (E11: one open question per case); and the S6 scope has a case OUTSIDE `holds` (otherwise there is nothing to
        go on with: the question is asked at once, as before). ERROR DIRECTION: every doubt - no scope, an unreadable state - is False,
        a question asked at once, never one withheld.

        TR3-10 D (item 10, edge D.1) POSITION: the FIRST line, before the `holds` test. The two questions that hold NO case (`walk_supply`,
        `data_change`) set `no_hold`; only that kind WITH the flag passes - a `walk_supply` Person without it, and any other Person (a gate
        among them) with the flag set by mistake, fall through to the test below and are asked at once."""
        if getattr(person, "no_hold", False) and person.kind in ("walk_supply", "data_change"):
            return True
        holds = {str(case) for case in getattr(person, "holds", ()) or ()}
        if not holds or person.kind in GATE_KINDS or person.code == EXIT_GAVE_UP:
            return False
        return self.holds_can_wait(holds)

    def holds_can_wait(self, holds) -> bool:
        """The case half of `deferrable`, also read by the sign-in question's text (it says which road it is on): no case of `holds` is
        held by another deferred question (E11) and the S6 scope has a case OUTSIDE `holds`. An unreadable scope is False."""
        holds = {str(case) for case in holds}
        if not holds or any(case in holds for case, _n in self.deferred_waiting(sorted(holds))):
            return False
        try:
            scope = self.controller_state().get("scope")
        except Exception:
            return False
        return isinstance(scope, list) and any(str(case) not in holds for case in scope)

    def manual_holds(self, dispatch: str) -> tuple:
        """The third `holds` site (spec 2.2 p.2): the seam question over a REFUSED manual S6 dispatch waits for the cases that dispatch
        carried (`manual_case_ids` of its controller record, when `execution_kind` is `manual`). `()` (asks at once, as before) for no
        dispatch, another kind, an unreadable state or no ids - ERROR DIRECTION: a question asked, never withheld."""
        if not dispatch:
            return ()
        try:
            record = (self.controller_state().get("dispatches") or {}).get(dispatch)
        except Exception:
            return ()
        ids = record.get("manual_case_ids") if isinstance(record, dict) and record.get("execution_kind") == "manual" else None
        return tuple(dict.fromkeys(str(case) for case in ids)) if isinstance(ids, list) else ()

    def defer_question(self, person: "Person") -> None:
        """Set the question aside: `ask()` renders it (the same text, the same `driver-questions.jsonl` row and its `source`), the
        file moves to `state/deferred-questions/<n>.md`, and the flags `ask()` set are taken off the live state with the question
        (a flag that outlived its question captured the next answer at the same stage, t-037). The record keeps what `deferred_step`
        needs to ask it again as it was."""
        import contextlib
        import io
        n = int(self.state.get("deferred_seq") or 0) + 1
        before = {key for key in self.DEFER_FLAGS if key in self.state}
        self._deferring = True
        try:
            with contextlib.redirect_stdout(io.StringIO()):          # the text is shown at gate B, not now
                self.ask(person)
        finally:
            self._deferring = False
        live = self.question_path()
        text = live.read_text(encoding="utf-8", errors="replace") if live.is_file() else ""
        kept = self.state_dir / "deferred-questions" / f"{n}.md"
        kept.parent.mkdir(parents=True, exist_ok=True)
        kept.write_text(text, encoding="utf-8")
        live.unlink(missing_ok=True)
        flags = {key: self.state[key] for key in self.DEFER_FLAGS if key in self.state}
        for key in self.DEFER_FLAGS:
            if key not in before:
                self.state.pop(key, None)
        holds = sorted({str(case) for case in person.holds})
        self.state["deferred"] = self.deferred_items() + [{
            "n": n, "kind": person.kind, "stage": person.stage, "dispatch": person.dispatch, "holds": holds,
            "asked": dict(self.state.get("asked") or {}), "flags": flags, "at": _now()}]
        self.state["deferred_seq"] = n
        self.state["asked"] = {}
        self.save_state()
        print(f"[progress] {person.stage or 'S6'}: a question about {', '.join(holds)} waits for you; the other work goes on; "
              "it is asked before gate B", flush=True)

    def deferred_step(self) -> None:
        """Called at the top of gate B's entry: the first unanswered deferred question is asked again as it was (its `asked`, its flags,
        its text with one head line `question: k of N, waiting since <stage>` - inside the machine head, so `question_body_sha` is the
        live question's, FR-7) and the run stops with exit 3. The answer goes through `take_answer` unchanged, with the executors of the
        original question; the item is dropped at the END of `take_answer`. Gate B is shown only when nothing is deferred. A text file
        that is gone is a refusal that says so - never a silent drop of a question (AR-28)."""
        items = self.deferred_items()
        if not items:
            self.state.pop("deferred_round", None)
            return
        item = items[0]
        kept = self.state_dir / "deferred-questions" / f"{item['n']}.md"
        try:
            text = kept.read_text(encoding="utf-8")
        except OSError as exc:
            raise Refusal(f"deferred question {item['n']}: its text file {kept} cannot be read ({type(exc).__name__}). The question is "
                          "still owed to the person, and `state/driver-state.json` (`deferred`) holds no text to write it from; answer the "
                          "conductor's question that follows this refusal (it settles how the person is asked).")
        total = max(int(self.state.get("deferred_round") or 0), len(items))
        self.state["deferred_round"] = total
        mark = f"question: {total - len(items) + 1} of {total}, waiting since {item.get('stage') or 'S6'}"
        title, _sep, rest = text.partition("\n")
        text = (title + "\n" + mark + "\n" + rest) if title.startswith("#") else (mark + "\n" + text)
        for key in self.DEFER_FLAGS:
            self.state.pop(key, None)
        self.state.update(item.get("flags") or {})
        self.state["asked"] = dict(item.get("asked") or {}, deferred_n=item["n"])
        self.save_state()
        path = self.question_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        self.progress_line()
        print(text)
        # remains: the question is the person's, asked again exactly as `ask()` wrote it; exit 3 is `ask()`'s own code (RN1-24)
        raise Stop(EXIT_PERSON, f"{mark.split(': ', 1)[1]} - answer it; gate B follows the last one")

    def deferred_decision(self, item: dict, token: str, words: str, asked: dict, stage: str, rel: str) -> None:
        """`go on` / `by hand` on a deferred question whose stage is closed (P22: the words are executed, not only recorded): the pass of
        the question's block is recorded (`pass_block`, held on a refusal like the live road) and the request.json of each held case is
        rewritten, through the same writer `manual_close` and `stand_login_gate` use, from the waiting reason to the person's decision:
        `by: person_checks` for `by hand` (the typed carrier, as `stand_login_gate` writes it), `left_unchecked` for anything else.
        A case whose request.json is no longer OUR waiting record (it was prepared or run since) is left as it is (AR-28). `rel` is the
        words file of the answer (the caller reads it: `answer_file` sits in a higher layer)."""
        import manual_evidence as ME
        block = str(asked.get("block") or "")
        if block:
            self.pass_block(stage, block, rel, "Your word could not be recorded as the pass, so nothing was passed.")
        said = " ".join(words.replace(self.BOM, "").split())
        by = "person_checks" if token == "by hand" else "left_unchecked"
        reason = f"not checked by an agent: you answered question {item['n']} about it; the person said: \"{said}\""
        door = "fix what that question named; the next run checks it by hand"
        for case in item.get("holds") or []:
            path = ME.request_path(self.task_root, case)
            refused = _read_json(path).get("refused")
            if not (isinstance(refused, dict) and refused.get("by") == "left_unchecked"
                    and str(refused.get("reason") or "").startswith("not checked yet: it waits for your answer")):
                continue
            if not self.refuse_case(None, case, reason, door, by):
                print(f"{case}: the decision could not be written to its request.json; the answer is on record")
            else:
                print(f"S6: {case}: not checked by hand — {reason}")

    def deferred_note(self) -> None:
        """A run that ends with deferred questions still open says so (E9): the list is on the record, never silently left."""
        items = self.deferred_items()
        if items:
            print(f"[progress] {len(items)} question(s) wait for you and are asked before gate B: "
                  + "; ".join(f"{item.get('kind')} about {', '.join(item.get('holds') or [])}" for item in items), flush=True)

    @staticmethod
    def stop_held(then: str = "") -> str:
        """The first line of a question held after the person said to stop (FR-7: it comes back changed). ONE text for every
        site that holds a question on `stop`; `then` says how to go on after all."""
        return "You said to stop. Nothing runs and nothing is spent." + (" " + then if then else "")

    DETAILS_POINTER = "The factory's own words about this"       # the line `ask()` writes, and `held_question` looks for

    def held_question(self, lead: str, details: str | None = None) -> Person:
        """THE helper that brings the open question back (exit 3) with `lead` above its body: a `stop` (`stop_held`), or a sentence
        that says what could not be done (a pass that failed, an answer that was not read). Built from the question file, still on
        disk while `take_answer` runs, and from `asked` (its kind, stage, dispatch, and for a question the seam raised its tokens,
        options, words file, why and block - so the same tokens read the next answer). `details`: None keeps the details file the
        question points to, a text replaces it. A question that is ALREADY held loses ITS lead before the new one goes on: a second
        `stop`, or an unread answer after an unread answer, never stacks leads (t-684 F7, t-689 F-2). The lead is known by its
        extent, not by its words (FR-12): `ask()` keeps the lead this helper put on the question in `asked["held_lead"]`, and that
        exact text is what comes off the front of the body. Nothing of the lead lives in the question's own body."""
        asked = self.state.get("asked") or {}
        qtext = self.question_path().read_text(encoding="utf-8", errors="replace") if self.question_path().is_file() else ""
        body = QUESTION_HEAD_RE.sub("", ANSWER_BLOCK_RE.sub("", qtext), count=1).strip()
        held = str(asked.get("held_lead") or "").strip()
        if held and body.startswith(held):
            body = body[len(held):].strip()
        if details is None:
            file = self.state_dir / "driver-question-details.md"
            named = file.is_file() and self.DETAILS_POINTER in qtext     # a file the question itself points to
            said = re.search(r"```\n(.*)\n```", file.read_text(encoding="utf-8", errors="replace"), re.S) if named else None
            details = said.group(1) if said else ""
        again = Person(asked.get("kind", ""), lead + "\n\n" + body, asked.get("stage", ""), asked.get("dispatch", ""), details=details)
        again.offered, again.options = tuple(asked.get("offered") or ()), list(asked.get("options") or [])
        again.words_file, again.why, again.block = str(asked.get("words_file") or ""), str(asked.get("why") or ""), str(asked.get("block") or "")
        again.held_lead = lead.strip()
        again.why_person = PO.as_class(asked.get("why_person"))          # the same question keeps its class (`waiver_road`)
        again.rows = tuple(str(i) for i in asked.get("rows") or ())     # the same question: it keeps the rows it was about
        again.probe_gap_cases = tuple(str(c) for c in asked.get("probe_gap_cases") or ())   # the same question keeps the cases it named
        again.probe_judgment_cases = tuple(str(c) for c in asked.get("probe_judgment_cases") or ())   # (t-1968 N5) as the line above
        again.sources, again.classes = tuple(asked.get("sources") or ()), tuple(asked.get("classes") or ())    # an `s1_gap` keeps what it named
        return again

    def pass_block(self, stage: str, block: str, words_file: str, lead: str) -> None:
        """THE write-or-hold of a pass by the person's word (t-698 A13, t-781 m6): ONE `waiver.py` row for `block` at `stage`, the
        words by FILE (`words_file`: task-root relative). A row `waiver.py` refuses - or a `waiver.py` that cannot run at all - is
        printed and HELD (`lead` above the command's own output): nothing is passed in silence. Callers: the exit-limit `go on`
        (`_exit_go_on`), the seam's `go on` with a block (`take_seam_answer`) and the `go on` of a closed-by-code stage
        (`_answer_code_close`); the next one is b1's `_answer_repair_limit` (queued)."""
        code, out = self.py("waiver.py", "--task", self.task, "--stage", stage, "--block", block, "--words-file", str(self.task_root / words_file),
                             *self.waiver_road())
        if code:
            print(f"{stage}: the pass was not recorded ({out[-300:]}); the question comes back")
            raise self.held_question(lead, out)

    def after_close(self, stage: str, words: str) -> None:
        """THE short-circuit of an answer that arrives after its stage is done already: say so and put the person's words on the journal;
        the caller goes on. Callers: `_answer_exit_limit`, `_answer_code_close`, `take_seam_answer` and the conductor/refusal branch of
        `take_answer`. What each caller returns afterwards stays its own."""
        print(f"{stage} is done already; recording the words and going on")
        self.answer_row(f"{stage} (after close): ", words.strip(), what="your answer after the stage was closed")

    def question_from_refusal(self, refusal, stage: str, dispatch: str = "") -> str:
        """The LEAD of the question to ask when nobody wrote one: where the story is and that the reason cannot be put in its own
        words. The options come from the seam (`fallback_person`: the `fallback` block, each with its three price lines, C1-1).

        `ask_person` with an empty `question` came back sixteen times in seventy-six conductor
        sessions of run 5, and the driver turned each into "The conductor needs your word."
        plus the refusal's own text. That is not a question, so the answer was free prose, and
        reading it back cost another conductor session - the most expensive family of the run
        ($9.01 over 21 sessions). The driver cannot translate the refusal, but it does know
        where the story is and what the three standing answers are, and that is a question."""
        stages = {}
        try:
            stages = self.stages()
        except Exception:
            pass
        name = str((stages.get(stage) or {}).get("name") or "").strip().lower()
        where = f"the {name} stage ({stage})" if name and stage else (f"stage {stage}" if stage else "this story")
        done = [f"S{i}" for i in range(10)
                if str(((self.pipeline().get("stages") or {}).get(f"S{i}") or {}).get("status") or "") == "done"]
        return (
            f"The story has reached {where}" + (f", with {len(done)} stage(s) behind it" if done else "") +
            ", and a check of the factory's own refused to let it go on.\n\n"
            "I cannot put that check's reason into the story's own words — it is written for the "
            "role that ran it, not for you. That is a defect of ours and it is recorded as one; "
            "the words themselves are in the file named below, if you want them.")

    PROBE_GAP_LEAD_LIMIT = 10

    @classmethod
    def probe_gap_lead(cls, pairs) -> str:
        """B-16: the LEAD of the S5 seam question that offers the probe-gap word, in `human-questions.md` form (what the factory did, why
        it cannot decide, whose gap, one question; no field, script, path or dispatch id). `pairs` = `window_record.probe_gap_cases`:
        `[(case key, [instance ids])]`. The text is the owner's (05.11.2026 19:00): it says the word covers the whole CLASS of tests whose
        check the tool could not read, because that is what the record does (`contract.probe_gap_class_word`). At most
        `PROBE_GAP_LEAD_LIMIT` cases are listed, then `, and <k> more`; every case is still recorded by `seam_chosen`."""
        shown = [f"{case} (the test \"{(ids or [''])[0]}\")" for case, ids in list(pairs)[:cls.PROBE_GAP_LEAD_LIMIT]]
        more = len(pairs) - len(shown)
        listed = "; ".join(shown) + (f", and {more} more" if more > 0 else "")
        return (f"The review of this window of tests is finished. {len(pairs)} test case(s) ran green, but for each of them the factory "
                "could not run the check that proves the test would catch a broken product, because its own tool cannot read these "
                f"tests: {listed}. That is a gap in the factory's tool, not a flaw in the tests, and only you can accept it.\n\n"
                "If you answer `go on`, the factory records your words once for each case named above. From then on your words cover "
                "every test of this story whose check the tool could not read: the tests named here, other tests of the same cases, "
                "and tests in later windows of this story. The tests themselves are not changed; they are only not checked that way.")

    PROBE_JUDGMENT_LEAD_LIMIT = 10

    PROBE_JUDGMENT_STATEMENT_LIMIT, PROBE_JUDGMENT_WHY_LIMIT = 120, 160

    @classmethod
    def probe_judgment_lead(cls, pairs) -> str:
        """t-1968 N5: the LEAD of the S5 seam question for tests whose probe the code reviewer could not judge, in `human-questions.md`
        form (what the factory did, why it cannot decide, whose decision, the answers; no field, script, path or dispatch id). `pairs` =
        `window_record.probe_judgment_cases`: `[(case key, [{iid, line, statement_inverted, statement_after, printed, why, ...}])]`. The text is the spec's
        (the owner's word 05.11.2026): it covers THESE cases only and says an earlier answer about tooling does not cover them. One entry per
        TEST: the case, the test, the line of the broken check and the statement (at most 120 characters), what it printed (the lines
        `window_record` kept) and the reviewer's reason (at most 160); at most `PROBE_JUDGMENT_LEAD_LIMIT` tests are listed, then `, and <k> more`.
        An entry's missing datum is said plainly, never invented and never a crash. Pure."""

        def cut(text, limit):
            one = " ".join(str(text or "").split())
            return one if len(one) <= limit else one[:limit - 1] + "…"

        entries = [(str(case), item) for case, items in pairs for item in items or [] if isinstance(item, dict)]
        shown = []
        for case, item in entries[:cls.PROBE_JUDGMENT_LEAD_LIMIT]:
            # the person reads the check as the plain inversion (`statement_inverted`), never the written statement with the factory's own
            # marker expression in it (F5); a detail with no inversion text (a probe that wrote no marker) wrote the plain statement
            line = item.get("line")
            statement = cut(item.get("statement_inverted") or item.get("statement_after"),
                            cls.PROBE_JUDGMENT_STATEMENT_LIMIT).replace("`", "'")
            where = f"the check broken at line {line}" if line not in (None, "") else "the check it broke"
            printed = cut(item.get("printed"), 10 ** 6)
            said = cut(item.get("why"), cls.PROBE_JUDGMENT_WHY_LIMIT)
            shown.append(f"{case}: the test \"{item.get('iid') or ''}\", {where}" + (f" (`{statement}`)" if statement else "")
                         + (f", it printed \"{printed}\"" if printed else ", it printed nothing the factory kept")
                         + f"; the reviewer said: {said or 'no reason was given'}")
        more = len(entries) - len(shown)
        listed = "; ".join(shown) + (f", and {more} more" if more > 0 else "")
        return (f"The review of this window of tests is finished, but for {len(pairs)} test case(s) the factory could not prove that a "
                "test would catch a broken product. It broke one check in each test and ran it; the test failed, and the code reviewer "
                "could not tell whether it failed because of that check or for another reason: "
                f"{listed}. Only you can decide what happens to these tests.\n\n"
                "Answer `go on` to accept them as not proved: your words are recorded for these cases only, and the report lists them as "
                "not proved. Answer `rework` to send them back to their author with your words. An earlier answer about tests the "
                "factory's tool could not read does not cover these.")

    # The `says` of the `ungrounded` and `not built yet` answers: the twins `s0.no_change` and `s1.no_diff` (AR-19) use ONE text.
    UNGROUNDED_SAYS = ("go on with the requirements only, on the code the stand runs now; a test that goes red is judged like any red")

    NOT_BUILT_YET_SAYS = ("the code for this story is not written yet: the tests are written now from the requirements, using what the "
                          "project already has (page objects, locators of similar pages), and what cannot be known yet gets a "
                          "named placeholder; the story stops after the tests are written and reviewed and tells you what is missing, "
                          "and when the code exists you start the same story again with the merge request, branch or commit")

    # -- the doors of S0 ---------------------------------------------------------------------
    # Built from code points, so that the source stays plain ASCII (a literal BOM or curly quote
    # in a source file is invisible in review): the pairs a person's editor puts round a word.
    _PEEL = (("`", "`"), ('"', '"'), ("'", "'"), (chr(0x201C), chr(0x201D)), (chr(0x2018), chr(0x2019)))

    BOM = chr(0xFEFF)

    @classmethod
    def s0_normalize(cls, words: str) -> str:
        """The answer, reduced to what it would be if the person had typed exactly a token:
        BOM out, the quotes or backticks they wrapped it in off, ONE closing `.` or `!` off,
        lower case, runs of white space one space. It decides nothing about meaning (FR-12) -
        it only makes a BOM, a pair of quotes and a full stop around `Go on` the same characters
        as `go on`."""
        def peel(text: str) -> str:
            again = True
            while again and len(text) >= 2:
                again = False
                for opening, closing in cls._PEEL:
                    if text[0] == opening and text[-1] == closing:
                        text, again = text[1:-1].strip(), True
                        break
            return text
        text = peel(str(words or "").replace(cls.BOM, "").strip())
        if text[-1:] in (".", "!"):
            text = text[:-1].strip()
        # a curly apostrophe INSIDE a word (`another team’s`: the default of a phone or Word keyboard) is the ASCII one, after the
        # pairs are peeled (code points, as `_PEEL`)
        return " ".join(peel(text).replace(chr(0x2019), "'").replace(chr(0x2018), "'").split()).lower()

    def s0_quote(self, words: str) -> str:
        """The person's words as one line, at most QUOTE_LIMIT characters; a cut shows as an ellipsis."""
        one = " ".join(str(words or "").split())
        return one if len(one) <= self.QUOTE_LIMIT else one[:self.QUOTE_LIMIT] + self.CUT

    def unread_lead(self, words: str) -> str:
        """THE sentence that says an answer was not read (F-6): the lead of every closed question that comes back after words it
        does not take (S0, `package`, `ticket_changed`, `ticket_auth`). The words are quoted, cut like any quote (`s0_quote`)."""
        return f'Your answer "{self.s0_quote(words)}" is not one of the answers this question takes, so nothing has moved yet.'

    @classmethod
    def build_peel(cls, text: str) -> str:
        """The answer without a BOM and without the pairs of quotes or backquotes a person's editor put round it (case kept)."""
        text = str(text or "").replace(cls.BOM, "").strip()
        again = True
        while again and len(text) >= 2:
            again = False
            for opening, closing in cls._PEEL:
                if text[0] == opening and text[-1] == closing:
                    text, again = text[1:-1].strip(), True
                    break
        return text

    @classmethod
    def build_read_answer(cls, words: str, offered: list, forms: dict) -> dict:
        """The answer as ONE line that is exactly one form of the data (`answers.forms`): `{"form": name, "arg": text}`, or
        `{"form": "", "why": ...}` for anything else - empty, several lines, prose, another language, a form this question
        did not offer. The code reads the form word (case and the closing `.`/`!` do not matter) and what the form says may
        follow it; it never reads a meaning (FR-12). A commit after `deployed` or `test deployed` must LOOK like one (7 to 40
        hex characters): other words after the form are the person's own, and are not read. The same holds for every form that
        takes a value: its shape is `answers.forms.<form>.value` (a label is one word, a path is one word that starts with
        `/`, a command is the rest of the line); a value that misses it makes the answer NOT this form (t-366 F3)."""
        lines = [line.strip() for line in cls.build_peel(words).splitlines() if line.strip()]
        if not lines:
            return {"form": "", "why": "the answer is empty"}
        if len(lines) > 1:
            return {"form": "", "why": "the answer has more than one line"}
        line = cls.build_peel(lines[0])
        for name in sorted(forms, key=len, reverse=True):
            spec = forms[name]
            word = str(spec.get("word") or name)
            found = re.fullmatch(r"(?is)" + r"\s+".join(re.escape(w) for w in word.split()) + r"(?P<stop>[.!]?)(?:\s+(?P<arg>.*))?", line)
            if not found:
                continue
            kind, arg = str(spec.get("arg") or "none"), (found.group("arg") or "").strip()
            if (found.group("stop") and arg) or (kind == "none" and arg):
                continue
            if kind == "commit" and arg:
                arg = arg.rstrip(".!").lower()
            if kind in ("optional", "required") and spec.get("peel_arg"):
                arg = cls.build_peel(arg)
            # t-366 F3: the shape of the value is DATA (`value`, as a whole): prose where a label or a path belongs is not this
            # form - the whole answer goes to the conductor, never into a registry row (a label that is a sentence)
            if arg and spec.get("value") and not re.fullmatch(str(spec["value"]), arg):
                continue
            if name not in offered:
                return {"form": "", "why": f"`{name}` is not one of the answers this question offers", "named": name}
            return {"form": name, "arg": arg}
        return {"form": "", "why": "the words are not one of the answers"}

    def shown_packet(self, kind: str) -> str:
        """The text of the gate question the driver SHOWED the person ("" when there is none to read).

        t-291 (t-279 F5): `state/driver-question.md` while the question is open and is this gate's. The kept-answer
        retry in `gate_repair` runs after the file was filed as answered, and holds none: it gets "" and the answers
        are recorded against the row as it stands, as they always were."""
        try:
            if (self.state.get("asked") or {}).get("kind") != kind:
                return ""
            path = self.question_path()
            return path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""
        except OSError:
            return ""
