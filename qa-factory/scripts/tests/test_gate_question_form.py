"""A gate-A question carries its readings, or the factory rewrites it before the gate is shown.

TP1-15045 asked the owner, once, `Where must a removed node appear when the YAML has no
layout meta (code falls back to {0,0})?` — no quote of the source, no readings, no consequence.
Nobody answered it. The factory then tested the letter of AC-4 ("shown at its former position")
with a 1 px coordinate check, while the implementing developer's comment on the parent ticket
said the diff re-lays the nodes out and the coordinates mean nothing; the contradiction matrix
had scored that requirement against the parent story as `silent`. The result was a bug that was
not a bug. Put as "the source says X; reading a, from the AC; reading b, from the developer's
comment; what changes with each", the same question was answered in one minute.

So: a question built from the register's matrix carries both readings with their origins, the
brief prints it as a card and not as a clipped line, and a question nobody can answer as it
stands is a repair the FACTORY owes itself before the gate — passed, like every block in this
factory, by the person's own recorded word.
"""
import collections
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import check, check_eq, check_in, check_not_in, cleanup, finish, temp_dir, SCRIPTS  # noqa: E402

sys.path.insert(0, str(SCRIPTS))

import contract  # noqa: E402
import gate_brief  # noqa: E402
import gate_preflight  # noqa: E402
import human_text  # noqa: E402
import planning_contract  # noqa: E402
import question_register as QR  # noqa: E402

EM_DASH = chr(0x2014)  # built, never typed: the package is ASCII-clean (FR-30)

# The 15045 register as S2 would write it once the matrix compares R-4 with the parent
# ticket's comments as well as with its AC.
REGISTER = """---
task: TP1-15045
---

## Register

| R | Requirement (one verifiable statement) | source | derived_from | verifiable | ac_ref | observable | impact |
|---|---|---|---|---|---|---|---|
| R-3 | A restored node keeps its identity | ac | - | yes | AC-3 | diff:Diff.tsx:80 | degraded |
| R-4 | A removed node is shown at its former position | ac | - | yes | AC-4 | diff:Diff.tsx:120 | cosmetic |

## Contradiction matrix

| R | parent story/feature | comments of the ticket and its parent | area open bugs |
|---|---|---|---|
| R-3 | ok:TP1-14482 | silent | silent |
| R-4 | silent | contradicts:"the position of elements displayed in the diff does not correspond to the position of the real restoration state" (TP1-14482 comment, 2026-09-09) | silent |
"""

PLAN = [{"id": "TS-4", "requirement_ids": ["R-4"], "level": "e2e-ui",
         "disposition": "automate", "oracle_unknown": True}]


def story(prefix: str, questions=None, pipeline_extra=None) -> Path:
    base = temp_dir(prefix) / "qa-factory"
    task_root = base / "artifacts" / "TP1-15045"
    (task_root / "work").mkdir(parents=True)
    (task_root / "state").mkdir(parents=True)
    (base / "config.json").write_text("{}", encoding="utf-8")
    (task_root / "work" / "requirements-register.md").write_text(REGISTER, encoding="utf-8")
    (task_root / "work" / "test-plan.json").write_text(json.dumps(PLAN), encoding="utf-8")
    (task_root / "work" / "requirements-readiness.json").write_text(
        json.dumps({"verdict": "ready", "open_questions": questions or []}), encoding="utf-8")
    (task_root / "pipeline.json").write_text(json.dumps(
        dict({"ticket": "TP1-15045"}, **(pipeline_extra or {}))), encoding="utf-8")
    return base


def test_readings_are_built_from_the_matrix() -> None:
    base = story("qa-question-readings-")
    task_root = base / "artifacts" / "TP1-15045"
    try:
        readings = planning_contract.register_contradiction_readings(REGISTER)
        check_in("the matrix row is read back", "R-4", readings)
        check_eq("and it names the column the requirement disagrees with",
                 readings["R-4"]["against"], "comments of the ticket and its parent")
        check_eq("which is where the second reading comes from",
                 readings["R-4"]["origin"], "comment")
        check_eq("the requirement's own text is the first reading",
                 readings["R-4"]["statement"],
                 "A removed node is shown at its former position")
        check_eq("and its AC is where that one comes from", readings["R-4"]["ac_ref"], "AC-4")
        check_not_in("a row the matrix does not contradict is not a question", "R-3", readings)

        questions = gate_brief.contradiction_questions(task_root, PLAN)
        check_eq("the contradicted plan row makes exactly one question", len(questions), 1)
        question = questions[0]
        check_eq("which a person can answer as it stands",
                 contract.question_errors(question), [])
        check_eq("it carries two readings, not one", len(question["readings"]), 2)
        check_eq("the first from the acceptance criterion",
                 question["readings"][0]["from"], "acceptance_criteria:AC-4")
        check_eq("the second from the developer's comment",
                 question["readings"][1]["from"], "comment")
        check("each reading says what follows from it",
              all("TS-4" in r["if_chosen"] for r in question["readings"]))
        check_in("and the coordinates reading is quoted, not paraphrased",
                 "does not correspond to the position",
                 json.dumps(question["source_says"]))

        text = gate_brief.render({"task": "TP1-15045", "open_questions": questions})
        check_in("the brief prints the quote", "the source says:", text)
        check_in("the readings are lettered for the answer", "- a) ", text)
        check_in("with the second beside it", "- b) ", text)
        check_in("and what each answer costs", "if chosen:", text)
        check_in("the person's own wording is offered without being a third reading",
                 "or your own wording", text)
        check_eq("and readings[] holds only what the sources say",
                 len(question["readings"]), 2)
        check("the question is no longer clipped to one line",
              len([line for line in text.splitlines() if line.startswith("  - ")]) >= 4)
    finally:
        cleanup(base.parent)


def test_a_bare_question_is_the_factorys_to_rewrite() -> None:
    """A story in flight, written by an older build: one finding, and a person's word passes it."""
    bare = [{"id": "Q-3", "severity": "major", "owner_role": "po_ba",
             "question": "Where must a removed node appear when the YAML has no layout meta?"}]
    base = story("qa-question-bare-", questions=bare)
    task_root = base / "artifacts" / "TP1-15045"
    try:
        rehearsal = gate_preflight.Rehearsal(task_root, "A")
        rehearsal.check_open_questions()
        check_eq("a bare question is exactly one finding", len(rehearsal.findings), 1)
        finding = rehearsal.findings[0]
        check_eq("owned by the factory, not by the person",
                 finding["class"], gate_preflight.FACTORY_FIXABLE)
        check_in("it names the question", "Q-3", finding["message"])
        check_in("and the role that rewrites it",
                 "qa-requirements-tester", finding["message"])
        check_in("the person's word passes it, as a line they write (t-357: no script named)",
                 f"write `{finding['id']}: accept` with your reason", finding["fix"])

        check_eq("the rehearsal writes nothing",
                 json.loads((task_root / "pipeline.json").read_text(encoding="utf-8")),
                 {"ticket": "TP1-15045"})
    finally:
        cleanup(base.parent)

    waived = {"stage_overrides": [{"stage": "S5", "match": "Q-3",
                                  "decision": "I know what I meant; go on",
                                  "at": "2026-09-24T09:00:00+00:00"}]}
    base = story("qa-question-waived-", questions=bare, pipeline_extra=waived)
    task_root = base / "artifacts" / "TP1-15045"
    try:
        rehearsal = gate_preflight.Rehearsal(task_root, "A")
        rehearsal.check_open_questions()
        check_eq("a waiver naming the question id silences it for good",
                 rehearsal.findings, [])
    finally:
        cleanup(base.parent)

    answered = [dict(bare[0], answer="the place in the structure")]
    base = story("qa-question-answered-", questions=answered)
    task_root = base / "artifacts" / "TP1-15045"
    try:
        rehearsal = gate_preflight.Rehearsal(task_root, "A")
        rehearsal.check_open_questions()
        check_eq("an answered question is not rewritten either", rehearsal.findings, [])
    finally:
        cleanup(base.parent)


def test_a_bare_question_still_reaches_the_person() -> None:
    """Backward compatibility: the brief shows a pre-0.7.16 question, it never drops it."""
    bare = {"question": "Where must a removed node appear?", "severity": "minor",
            "owner_role": "po_ba"}
    text = gate_brief.render({"task": "TP1-15045", "open_questions": [bare]})
    check_in("the old question is printed as it stands", "Where must a removed node appear?", text)
    check_not_in("with no invented reading beside it", "- a) ", text)


# --- t-155 (A2): what each answer changes, and the question's status from the register ----------
# B-216 / B-181. Stories here are shaped like TP1-13797 (cmp1): the project's FULL case id form
# `TP1-13797_TC_009`, manual rows a reading would take out of manual, and the person's
# answers kept in `authorization_source` of the gate record.

TICKET = "TP1-13797"
CASE_FORM = {"case_id_form": "{ticket}_TC_{nnn}"}
SHORT_TOKEN = re.compile(r"(?<![\w-])TC_[0-9]+: (?:manual|automate)")  # a short id in a token


def full_id(number: int) -> str:
    return f"{TICKET}_TC_{number:03d}"


def question(qid: str, count: int = 2, **extra) -> dict:
    row = {"id": qid, "question": f"What must happen for {qid}?", "severity": "major",
           "owner_role": "dev_arch",
           "readings": [{"reading": f"reading {i + 1} of {qid}", "from": "description",
                         "if_chosen": f"{qid} goes by reading {i + 1}"} for i in range(count)]}
    row.update(extra)
    return row


def plan_row(row_id: str, disposition: str = "manual-human", **extra) -> dict:
    row = {"id": row_id, "requirement_ids": ["R-21"], "level": "", "disposition": disposition}
    row.update(extra)
    return row


def case_text(number: int, plan_row_id: str, title: str, thens: list, question_thens=None,
              raw_question_thens=None) -> str:
    front = [f"id: {full_id(number)}", f"title: {title}", "area: webhook", "channel: manual-human",
             f"task: {TICKET}", f"plan_row: {plan_row_id}"]
    if raw_question_thens is not None:
        front.append("question_thens: " + raw_question_thens)
    elif question_thens is not None:
        front.append("question_thens: " + json.dumps(question_thens))
    body = [f"Requirements: R-{number}", f"Plan row: {plan_row_id}", "", "## Then"]
    body += [f"{n}. {text}" for n, text in enumerate(thens, start=1)]
    return "---\n" + "\n".join(front) + "\n---\n" + "\n".join(body) + "\n"


def gate_story(prefix: str, questions: list, rows=None, cases=None, pipeline=None,
               register: bool = True, with_register_md: bool = False) -> Path:
    base = temp_dir(prefix) / "qa-factory"
    task_root = base / "artifacts" / TICKET
    (task_root / "work" / "test-cases" / "webhook").mkdir(parents=True)
    (task_root / "state").mkdir(parents=True)
    (base / "config.json").write_text(json.dumps(CASE_FORM), encoding="utf-8")
    if register:
        (task_root / "work" / "requirements-readiness.json").write_text(
            json.dumps({"verdict": "ready", "open_questions": questions}), encoding="utf-8")
    if with_register_md:
        (task_root / "work" / "requirements-register.md").write_text(REGISTER, encoding="utf-8")
    (task_root / "work" / "test-plan.json").write_text(json.dumps(rows or []), encoding="utf-8")
    for number, text in (cases or {}).items():
        (task_root / "work" / "test-cases" / "webhook" / f"{full_id(number)}.md").write_text(
            text, encoding="utf-8")
    (task_root / "pipeline.json").write_text(
        json.dumps(dict({"ticket": TICKET}, **(pipeline or {}))), encoding="utf-8")
    return task_root


def drop(task_root: Path) -> None:
    cleanup(task_root.parents[2])


def packet(task_root: Path) -> str:
    return gate_brief.render(gate_brief.collect(TICKET, task_root))


def card_of(text: str, qid: str) -> str:
    """The lines of ONE question's card inside a rendered packet."""
    start = text.find(f"- **{qid}**")
    if start < 0:
        return ""  # a missing card is a FAIL line of the check that reads it, not a crash
    ends = [i for i in (text.find("\n- **", start + 1), text.find("\n## ", start + 1)) if i >= 0]
    return text[start:min(ends) if ends else len(text)]


def reading_of(card: str, letter: str) -> str:
    """The lines under ONE reading of a card (its sub-bullets included); "" when it has none."""
    parts = card.split(f"\n  - {letter}) ", 1)
    return parts[1].split("\n  - ", 1)[0] if len(parts) == 2 else ""


def question_part(text: str) -> str:
    """From the `Open questions` heading to the end of the `How to answer` block."""
    start = text.index("## Open questions")
    how = text.index("## How to answer", start)
    rest = text[how + 1:]
    stop = re.search(r"\n(?:## |_\(brief truncated)", rest)
    return text[start:how + 1 + stop.start()] if stop else text[start:]


def test_a_card_shows_what_each_answer_changes() -> None:
    """R8 items 1-3: the consequence under each reading, the token that keeps a case manual, and
    the answer grammar once, in the `how to answer` block."""
    questions = [question("Q1"), question("Q4")]
    rows = [plan_row("TS-9", what_we_verify="array filter on an object field",
                     if_answered={"Q4": {"*": {"disposition": "automate", "level": "api"}}}),
            plan_row("TS-6")]
    cases = {
        9: case_text(9, "TS-9", "Array-filter syntax on an object field",
                     ["The root-anchored filter saves and its delivery creates one execution.",
                      "The array filter on an object field: per the owner's decision."],
                     question_thens=[{"question": "Q4", "then": 2, "readings": {
                         "a": "The array filter on an object field saves and never matches: no execution.",
                         "b": "The array filter on an object field is rejected at save time: 422, nothing stored."}}]),
        6: case_text(6, "TS-6", "A disallowed event type is acknowledged", ["The delivery is acknowledged."],
                     question_thens=[{"question": "Q1", "then": 1, "readings": {
                         "a": "HTTP 200 and no execution.", "b": ""}}])}
    task_root = gate_story("qa-a2-card-", questions, rows, cases)
    try:
        data = gate_brief.collect(TICKET, task_root)
        text = gate_brief.render(data)
        q4 = card_of(text, "Q4")
        token = f"`{full_id(9)}: manual`"
        for letter, then_text in (("a", "saves and never matches: no execution."),
                                  ("b", "rejected at save time: 422, nothing stored.")):
            block = reading_of(q4, letter)
            check_in(f"R8-1 Q4 reading {letter}: the changed Then is printed with its case and number",
                     f"Then 2 of {full_id(9)} (Array-filter syntax on an object field) would read:", block)
            check_in(f"R8-1 Q4 reading {letter}: with THIS reading's text", then_text, block)
            check_in(f"R8-2 Q4 reading {letter}: the `*` patch reaches every reading - the case "
                     "leaves manual and the card says the factory does not switch it yet, how it is "
                     "checked is decided again from an automated test, and the report says what",
                     "The factory does not switch it by itself yet: after your answer, how it is checked "
                     "is decided again, starting from an automated test, and the report says what was "
                     "decided. To keep it checked by hand, write", block)
            check_in(f"R8-2 Q4 reading {letter}: the token that keeps it manual carries the FULL case id",
                     token, block)
        check_not_in("R8-1 the Then's own punctuation is not doubled", '.".', q4)
        check_in("R8-2 the token closes the block: what the case says comes first",
                 "would read:", q4.split("TP1-13797_TC_009 (Array-filter syntax on an object field) would no longer")[0])
        check_not_in("R8-2 conflict: the spec's 'would move to automate' is not what the card says",
                     "move to automate", text)
        check_not_in("R8-2 and it does not promise `automated by default` either (P19)", "by default", text)
        # the switch of a plan row after the answer is not built yet (owner, 01.10): no promise of it.
        # The positive control is the check above: the new words ARE in the card, so the absence is not a miscall.
        check_not_in("t-199 the old promise `decide anew` is absent from the rendered card", "decide anew", text)
        check_not_in("t-199 and so is its other form, `will decide`", "will decide", text)
        check("R8-2 no token of the packet carries a short case id",
              SHORT_TOKEN.search(text) is None, SHORT_TOKEN.search(text) and SHORT_TOKEN.search(text).group(0))
        q1 = card_of(text, "Q1")
        check_in("R8-1 an empty reading text is printed as nothing asserted, the Then keeps its number",
                 f"Then 1 of {full_id(6)} (A disallowed event type is acknowledged): "
                 "nothing is asserted here for this answer.", reading_of(q1, "b"))
        check_in("R8-1 Q1 reading a prints its own text", "HTTP 200 and no execution.", reading_of(q1, "a"))
        check_not_in("R8-2 a case no reading takes out of manual is offered no token",
                     f"{full_id(6)}: manual", text)
        check_in("R8-1 the structured effect carries the same fact (the applier's twin reads fields)",
                 "leaves_manual", json.dumps(data["question_effects"]["Q4"]["a"]))
        # item 3: the grammar, once, in its own block, and it is the strict one.
        check_eq("R8-3 the `how to answer` block appears once", text.count("## How to answer"), 1)
        check_eq("R8-3 and the letter form is stated once in the whole packet",
                 text.count("`<question id>: <letter>`"), 1)
        how = text[text.index("## How to answer"):]
        for form in ("`<question id>: <letter>`", "`<question id>: not needed`",
                     "`<full case id>: manual`", "`<full case id>: automate`",
                     "Write each answer on its own line",
                     gate_brief.ANYTHING_ELSE_SENTENCE):
            check_in(f"R8-3 the block says: {form}", form, how)
        check_not_in("R8-3 no other form is advertised: not the lenient `(a)`", "(a)", how)
        check("R8-3 the block comes after every card", text.index("## How to answer") > text.index("- **Q4**"))
        # the printed grammar is the one the register's parser reads (FR-10): feed it the tokens.
        words = f"Q4: a\nQ1: b\n{full_id(9)}: manual\n"
        parsed = QR.parse_choices(words, questions, [full_id(9), full_id(6)])
        check_eq("R8-3 what the card prints is what the parser reads: choices",
                 parsed["choices"], {"Q4": "a", "Q1": "b"})
        check_eq("R8-3 and the case token parses to the full id",
                 [(t["case"], t["decision"]) for t in parsed["case_tokens"]], [(full_id(9), "manual")])
        # FR-6: the text a person reads breaks no rule of human-questions.md.
        check_eq("R8 the question cards and the block obey human-questions.md",
                 [p["rule"] for p in human_text.problems(question_part(text))], [])
    finally:
        drop(task_root)


def test_the_star_patch_a_letter_override_and_not_needed() -> None:
    """R8 / Q12: `*` applies to every reading and a letter's own patch wins; `not needed` prints
    its consequence only when a patch exists for it; an answer that changes nothing says so."""
    rows = [plan_row("TS-7", if_answered={"Q2": {"*": {"disposition": "automate", "level": "api"},
                                                 "b": {"disposition": "manual-human"},
                                                 "not_needed": {"disposition": "automate"}}}),
            plan_row("TS-5", "automate", level="api", what_we_verify="the size limit on a payload",
                     if_answered={"Q2": {"*": {"disposition": "manual-agent"},
                                         "b": {"disposition": "automate"}}})]
    cases = {7: case_text(7, "TS-7", "Dispatched only for the listed event", ["One execution."]),
             5: case_text(5, "TS-5", "Payload size limit", ["The payload is refused."])}
    task_root = gate_story("qa-a2-star-", [question("Q2")], rows, cases)
    try:
        text = packet(task_root)
        card = card_of(text, "Q2")
        a, b = reading_of(card, "a"), reading_of(card, "b")
        check_in("R8 reading a: the case TS-7 leaves manual and the full token is offered",
                 f"`{full_id(7)}: manual`", a)
        check_in("R8 reading a: a row that stays checked but changes how is one plain line",
                 "the size limit on a payload: an automated test becomes a check by an agent, by hand "
                 f"(cases: {full_id(5)}).", a)
        check_in("R8 reading b: both letter patches restore what the row already was - it says nothing changes",
                 "nothing in the plan or the cases changes.", b)
        check_not_in("R8 reading b: and offers no token", f"{full_id(7)}: manual", b)
        check_eq("R8 `not needed` has its own block because a patch exists for it",
                 card.count("if you write `Q2: not needed`, what changes:"), 1)
        check_in("R8 and it offers the token for the case that would leave manual",
                 f"`{full_id(7)}: manual`", card.split("what changes:")[-1])
    finally:
        drop(task_root)
    # No patch for `not needed` anywhere: no such block.
    plain = gate_story("qa-a2-star2-", [question("Q2")],
                       [plan_row("TS-7", if_answered={"Q2": {"a": {"disposition": "automate"}}})],
                       {7: case_text(7, "TS-7", "Dispatched", ["One."])})
    try:
        check_not_in("R8 no `not needed` patch, no `not needed` block",
                     "what changes:", card_of(packet(plain), "Q2").split("- or your own wording")[-1])
    finally:
        drop(plain)


def test_a_story_from_before_the_fields_reads_as_it_did() -> None:
    """E-9: no `question_refs`, `if_answered` or `question_thens` anywhere: the card is today's card."""
    task_root = gate_story("qa-a2-legacy-", [question("Q1")], [plan_row("TS-9")],
                           {9: case_text(9, "TS-9", "Array filter", ["One."])})
    try:
        data = gate_brief.collect(TICKET, task_root)
        check_eq("E-9 nothing is computed for a story without the fields", data["question_effects"], {})
        check_eq("E-9 and nothing is unreadable", data["question_effect_problems"], [])
        expected = ["- **Q1** [major, owner dev_arch] What must happen for Q1?",
                    "  - a) reading 1 of Q1 (from description)", "    if chosen: Q1 goes by reading 1",
                    "  - b) reading 2 of Q1 (from description)", "    if chosen: Q1 goes by reading 2",
                    f"  - or your own wording {EM_DASH} the readings are what the sources say, "
                    "not a closed list of answers.",
                    "  - Answer: `Q1: a`, `Q1: b` or `Q1: not needed`"]        # GW1-32: the one line added to the card of before
        check_eq("E-9 the card is exactly the card of before, line for line, plus its Answer line",
                 gate_brief.question_card(data["open_questions"][0], 1, data["question_effects"]), expected)
        text = gate_brief.render(data)
        check_not_in("E-9 no consequence lines", "what changes", text)
        check_not_in("E-9 and no offer to keep anything manual", "kept checked by hand", text)
    finally:
        drop(task_root)


def test_what_cannot_be_read_is_named_not_raised() -> None:
    """Edges: a patch with no case to show; a Then number beyond the case's list; a case whose
    `question_thens` is not JSON. Each says what is known and what could not be read."""
    rows = [plan_row("TS-3", what_we_verify="the retry limit",
                     if_answered={"Q3": {"*": {"disposition": "automate"}}}),
            plan_row("TS-4", "automate", what_we_verify="the size limit")]
    cases = {4: case_text(4, "TS-4", "Size limit", ["One.", "Two."],
                          question_thens=[{"question": "Q3", "then": 5, "readings": {"a": "Five is refused."}}]),
             8: case_text(8, "TS-8", "Broken fields", ["One."], raw_question_thens="[not json")}
    task_root = gate_story("qa-a2-unread-", [question("Q3")], rows, cases)
    try:
        text = packet(task_root)
        a = reading_of(card_of(text, "Q3"), "a")
        check_in("edge: a patch whose row has no case file says it could not read one",
                 "the retry limit would no longer be kept checked by hand. The factory does not switch "
                 "it by itself yet: after your answer, how it is checked is decided again, starting "
                 "from an automated test, and the report says what was decided. No case of it could "
                 "be read here", a)
        check_not_in("t-199 edge: the label branch does not promise `decide anew` either", "decide anew", text)
        check_in("edge: a Then number beyond the case's list says what the case has",
                 "the case has no Then 5 (its Thens are 1, 2)", a)
        check_in("edge: and the reading's own text is still shown", "Five is refused.", a)
        check_in("edge: a case whose per-answer texts are not JSON is named, once",
                 f"Not read, so not shown above: {full_id(8)}: its per-answer Then texts could not be read",
                 text)
        check_eq("edge: and named once, not once per reading", text.count(full_id(8)), 1)
        check_in("edge: the packet still ends in the answer block", "## How to answer", text)
    finally:
        drop(task_root)


def test_a_register_row_without_ac_ref_is_signed_by_its_source() -> None:
    """G1-0 (t-928, P23): a requirement of a task with no AC has no `ac_ref`; the first reading of its contradiction was signed
    `description` whatever it came from. Now the register's `source` word decides (`REGISTER_SOURCE_ORIGINS`), the AC id still wins when
    there is one, `derived` and an unknown word stay `description`, and every value is an origin `question_errors` accepts."""
    import grammar
    head = ("## Register\n\n| R | Requirement | source | derived_from | verifiable | ac_ref | observable |\n|---|---|---|---|---|---|---|\n")
    rows = {"R-1": ("discussion", "-"), "R-2": ("feature", "-"), "R-3": ("story", "-"), "R-4": ("ac", "AC-4"),
            "R-5": ("ac", "-"), "R-6": ("derived", "-"), "R-7": ("somethingnew", "-")}
    register = head + "".join(f"| {r} | text of {r} | {src} | - | yes | {ac} | - |\n" for r, (src, ac) in rows.items())
    register += ("\n## Contradiction matrix\n\n| R | comment |\n|---|---|\n"
                 + "".join(f"| {r} | contradicts: other {r} |\n" for r in rows))
    got = {r: v["first_from"] for r, v in planning_contract.register_contradiction_readings(register).items()}
    check_eq("the first reading is signed by the source word when there is no ac_ref; the AC id wins; derived and unknown stay description",
             got, {"R-1": "comment", "R-2": "parent_ticket", "R-3": "description", "R-4": "acceptance_criteria:AC-4",
                   "R-5": "acceptance_criteria", "R-6": "description", "R-7": "description"})
    check("every origin is a word `question_errors` accepts", all(v.split(":")[0] in contract.READING_ORIGINS for v in got.values()))
    check_eq("REGISTER_SOURCE_ORIGINS plus `derived` is exactly grammar.REQ_SOURCES: a new source word fails here, loudly (G1-3)",
             set(planning_contract.REGISTER_SOURCE_ORIGINS) | {"derived"}, set(grammar.REQ_SOURCES))


def test_a_row_that_names_its_register_question_is_not_asked_twice() -> None:
    """R8 item 4 and its position invariant."""
    row = {"id": "TS-4", "requirement_ids": ["R-4"], "level": "e2e-ui", "disposition": "automate",
           "oracle_unknown": True}
    task_root = gate_story("qa-a2-dupes-", [question("Q1")], [row], with_register_md=True)
    try:
        def asked(question_refs, plan=None):
            rows = [dict(row, **({"question_refs": question_refs} if question_refs is not None else {}))]
            return [q["id"] for q in gate_brief.contradiction_questions(task_root, plan or rows)]

        check_eq("item 4 control: a row with no `question_refs` still produces its question", asked(None), ["R-4"])
        check_eq("item 4: every ref resolves to a register id - no duplicate R-n question", asked(["Q1"]), [])
        check_eq("item 4 invariant: one ref resolves and one does not - the question stays", asked(["Q1", "Q99"]), ["R-4"])
        check_eq("item 4 invariant: a ref that resolves nowhere - the question stays", asked(["Q99"]), ["R-4"])
        check_eq("item 4: ids are case-sensitive - `q1` is not Q1", asked(["q1"]), ["R-4"])
        check_eq("item 4: an empty list resolves nothing", asked([]), ["R-4"])
        check_eq("item 4: a ref that is not a list resolves nothing", asked("Q1"), ["R-4"])
        rows_with = [dict(row, question_refs=["Q1"])]
        (task_root / "work" / "test-plan.json").write_text(json.dumps(rows_with), encoding="utf-8")
        text = packet(task_root)
        check_in("item 4: the register question is on the card", "- **Q1**", text)
        check_not_in("item 4: and its twin `R-4` is not", "- **R-4**", text)
        (task_root / "work" / "test-plan.json").write_text(json.dumps([row]), encoding="utf-8")
        check_in("item 4: without the ref the twin is asked, as before", "- **R-4**", packet(task_root))
    finally:
        drop(task_root)
    bare = gate_story("qa-a2-dupes2-", [], [dict(row, question_refs=["Q1"])], register=False,
                      with_register_md=True)
    try:
        check_eq("item 4 invariant: no register at all - nothing resolves, the question stays",
                 [q["id"] for q in gate_brief.contradiction_questions(
                     bare, [dict(row, question_refs=["Q1"])])], ["R-4"])
    finally:
        drop(bare)


def test_no_question_and_no_reading_is_cut() -> None:
    """R8 item 5 and E-13: every open question gets a card; readings up to z; over 26 is a finding."""
    many = [question(f"Q{n}", 2) for n in range(1, 13)]
    task_root = gate_story("qa-a2-many-", many)
    try:
        text = packet(task_root)
        check_in("item 5: the count is the count", "## Open questions (12)", text)
        for n in (1, 6, 7, 12):
            check_in(f"item 5: question {n} of 12 has its card, with its last reading",
                     f"reading 2 of Q{n}", card_of(text, f"Q{n}"))
        check_eq("item 5: twelve cards, not six", len(re.findall(r"(?m)^- \*\*Q[0-9]+\*\*", text)), 12)
        check_not_in("item 5: nothing is cut by the brief's line cap", "brief truncated", text)
        check_eq("item 5: and the answer block is still there, once", text.count("## How to answer"), 1)
    finally:
        drop(task_root)
    for count in (8, 9, 26):
        lines = gate_brief.question_card(question("Q1", count), 1)
        lettered = [line for line in lines if re.match(r"  - [a-z]\) ", line)]
        last = "abcdefghijklmnopqrstuvwxyz"[count - 1]
        check_eq(f"E-13 {count} readings: {count} lettered lines", len(lettered), count)
        check_in(f"E-13 {count} readings: the last one is lettered {last} and keeps its text",
                 f"  - {last}) reading {count} of Q1 (from description)", lines)
    nine = gate_story("qa-a2-nine-", [question("Q1", 9)])
    try:
        check_in("E-13 nine readings in the packet: the ninth has letter i",
                 "  - i) reading 9 of Q1", packet(nine))
    finally:
        drop(nine)
    over = gate_brief.question_card(question("Q1", 27), 1)
    check_eq("E-13 27 readings: no letters at all", [l for l in over if re.match(r"  - [a-z]\) ", l)], [])
    check_in("E-13 27 readings: the card says it is the factory's own defect, not the person's",
             "The factory wrote 27 readings for this question, more than it can letter (26). "
             "That is the factory's own defect, not yours", over)
    check_in("E-13 27 readings: and offers the person's own words", "answer in your own words", over)
    check_in("E-13 27 readings: no reading is cut", "reading 27: reading 27 of Q1 (from description)", over)


def test_the_decision_text_holds_the_words_where_they_are_stored() -> None:
    """R12 / item 6 (B-181): the gate record keeps the answer in `authorization_source`."""
    gate = {"gates": {"A": {"decision": "approved", "authorization_source": "R-4: a\ngo on"}}}
    check_in("item 6: `authorization_source` is read", "R-4: a", gate_brief._decision_text(gate))
    check_not_in("item 6: a caller that asks for the non-gate decisions does not get the gate's words",
                 "R-4: a", gate_brief._decision_text(gate, with_gates=False))
    row = {"id": "TS-4", "requirement_ids": ["R-4"], "level": "e2e-ui", "disposition": "automate",
           "oracle_unknown": True}
    task_root = gate_story("qa-a2-words-", [], [row], pipeline=gate, with_register_md=True)
    try:
        check_eq("item 6: the gate's words name R-4, so the fork is not asked again",
                 gate_brief.contradiction_questions(task_root, [row]), [])
    finally:
        drop(task_root)
    other = gate_story("qa-a2-words2-", [], [row], with_register_md=True,
                       pipeline={"gates": {"A": {"decision": "approved", "authorization_source": "R-44: b"}}})
    try:
        check_eq("item 6 class: `R-44` is not `R-4` - an id is never matched as a substring",
                 [q["id"] for q in gate_brief.contradiction_questions(other, [row])], ["R-4"])
    finally:
        drop(other)


class Tolerant(dict):
    """A row that answers "" for a key it lacks: a question missing from a listing is a FAIL line
    of the check that reads it, never a crash that hides the other checks."""

    def __missing__(self, key):
        return ""


def test_question_status_comes_from_the_register() -> None:
    """R12 / item 7: `answered` and `not_needed` are not listed; `named` is, with its note; ids exact."""
    ids = ["Q1", "Q2", "Q3", "Q4", "Q5", "Q6", "Q7", "Q10"]
    questions = [question(qid) for qid in ids] + [{"question": "a bare question with no id",
                                                   "severity": "minor", "owner_role": "po_ba"}]
    words = "go on\nQ5 - let us see\nQ10: a\nq6: a"
    task_root = gate_story("qa-a2-status-", questions,
                           pipeline={"gates": {"A": {"decision": "approved", "authorization_source": words}}})
    try:
        shown = {q["id"]: q["row_hash"] for q in QR.load(task_root)["questions"]}
        stale = "0" * 64
        QR.record(task_root, "Q2", "answered", "Q2: a", "gate A", "person", shown["Q2"], reading="a")
        QR.record(task_root, "Q3", "not_needed", "Q3: not needed", "gate A", "person", shown["Q3"])
        QR.record(task_root, "Q4", "answered", "Q4: a", "gate A", "person", stale, reading="a")
        QR.record(task_root, "Q7", "not_needed", "Q7: not needed", "gate A", "person", stale)
        got = gate_brief.unanswered_questions(task_root)
        by_id = collections.defaultdict(Tolerant, {q.get("id"): Tolerant(q) for q in got})
        check_eq("item 7: listed are open, changed, named and the row the register cannot place; "
                 "`answered` Q2 and `not_needed` Q3 are not",
                 [q.get("id") for q in got], ["Q1", "Q4", "Q5", "Q6", "Q7", "Q10", None])
        check_eq("item 7: an `open` question carries no note", by_id["Q1"]["status_note"], "")
        named = "named in your gate A words; the factory recorded no answer"
        check_eq("item 7: `named` Q5 says exactly that", by_id["Q5"]["status_note"], named)
        check_eq("item 7: `named` Q10 says exactly that", by_id["Q10"]["status_note"], named)
        check_eq("item 7: and is `named`, never `answered`", by_id["Q5"]["status"], "named")
        check_not_in("item 7: the suffix `answered at` is not attached to a named question",
                     "answered at", by_id["Q5"]["status_note"])
        check_eq("item 7: ids are exact - Q10 named does not make Q1 named", by_id["Q1"]["status"], "open")
        check_eq("item 7: ids are case-sensitive - `q6: a` does not name Q6", by_id["Q6"]["status"], "open")
        check_in("item 7: a changed `answered` question says its text changed and is asked again",
                 "its text changed after your answer, so it is asked again", by_id["Q4"]["status_note"])
        check_in("item 7: and only an `answered` one carries the suffix `answered at gate A`",
                 "(answered at gate A)", by_id["Q4"]["status_note"])
        check_in("item 7: a changed `not_needed` question says its text changed",
                 "its text changed after your answer", by_id["Q7"]["status_note"])
        check_not_in("item 7: but it does not carry the `answered` suffix", "answered at",
                     by_id["Q7"]["status_note"])
        check_in("item 7: a question with no id is listed as it stands, not dropped",
                 "a bare question with no id", json.dumps(by_id[None]))
        shown_packet = packet(task_root)
        check_in("item 7: the gate A card of a named question carries the note too", named + ".",
                 card_of(shown_packet, "Q5"))
        check_in("item 7: the card of a changed question says so", "its text changed after your answer",
                 card_of(shown_packet, "Q4"))
        check_not_in("item 7 (FR-7): an answered question has no card to be asked again", "- **Q2**", shown_packet)
        check_not_in("item 7 (FR-7): nor a `not_needed` one", "- **Q3**", shown_packet)
        lines = gate_brief.open_before_mr(task_root)
        blob = "\n".join(lines)
        check_in("item 7: the MR list carries the named note", named, blob)
        check_not_in("item 7: and does not list the answered question", "What must happen for Q2?", blob)
        check_eq("item 7 (FR-10): the gate A packet lists the same questions as the MR list",
                 [q.get("id") for q in gate_brief.collect(TICKET, task_root)["open_questions"]],
                 [q.get("id") for q in got])
    finally:
        drop(task_root)


def test_a_register_that_cannot_be_read_is_said_and_never_read_as_answered() -> None:
    """Edge: `question_register.load` raising, or the register file absent: today's behaviour
    plus one line saying question status could not be read."""
    words = {"gates": {"A": {"decision": "approved", "authorization_source": "Q1: a"}}}
    task_root = gate_story("qa-a2-broken-", [question("Q1"), question("Q2")], pipeline=words)
    real = QR.load

    def broken(_root):
        raise RuntimeError("the register is unreadable on purpose")

    QR.load = broken
    try:
        data = gate_brief.collect(TICKET, task_root)
        text = gate_brief.render(data)
        check_eq("edge: both questions are still carded", [q["id"] for q in data["open_questions"]], ["Q1", "Q2"])
        check_eq("edge: one line says question status could not be read",
                 text.count("Question status could not be read"), 1)
        check_in("edge: and says the questions are shown as they stand",
                 "so every question below is shown as it stands.", text)
        check_eq("edge: the listing does not call any of them answered",
                 [q.get("status") for q in gate_brief.unanswered_questions(task_root)], [None, None])
        check_in("edge: the MR list carries its own one line",
                 "question status could not be read", "\n".join(gate_brief.open_before_mr(task_root)))
    finally:
        QR.load = real
        drop(task_root)
    absent = gate_story("qa-a2-absent-", [], [{"id": "TS-4", "requirement_ids": ["R-4"], "level": "e2e-ui",
                                                "disposition": "automate", "oracle_unknown": True}],
                        register=False, with_register_md=True)
    try:
        text = packet(absent)
        check_in("edge: no register file, a question from the plan row: the one line",
                 "Question status could not be read (the story has no questions register file)", text)
        check_in("edge: and the question is still carded", "- **R-4**", text)
    finally:
        drop(absent)


def test_an_empty_register_and_a_question_with_no_readings() -> None:
    """Edge: nothing to ask prints nothing; a question no reading can be named for asks for words."""
    empty = gate_story("qa-a2-empty-", [])
    try:
        text = packet(empty)
        check_not_in("edge: an empty register prints no question section", "## Open questions", text)
        check_not_in("edge: and no answer block", "## How to answer", text)
    finally:
        drop(empty)
    lonely = question("Q5", 0, readings_unnameable=True)
    card = gate_brief.question_card(lonely, 1)
    check_eq("edge: a zero-reading question has no letters", [l for l in card if re.match(r"  - [a-z]\) ", l)], [])
    check_in("edge: and asks for the person's own words", "No reading can be named for this one. "
             "Answer in your own words, or write `Q5: not needed`.", card)
    task_root = gate_story("qa-a2-lonely-", [lonely])
    try:
        text = packet(task_root)
        check_in("edge: it is carded in the packet", "- **Q5**", text)
        how = text[text.index("## How to answer"):]
        check_not_in("edge: with no letter form offered, there being no letter to choose", "<letter>", how)
        check_in("edge: `not needed` is still offered", "`<question id>: not needed`", how)
    finally:
        drop(task_root)


def test_a_before_now_question_shows_both_and_asks_the_fixed_pair() -> None:
    """t-227 (P20): TC_015 asked for the code P-multi returns and no question existed; the 403 came
    from the diff. A behaviour claim's question carries `before` and `now`, each `{value, where}`,
    and its two readings are the fixed pair, both `from: claim` (never `from: code`)."""
    fixtures = Path(__file__).resolve().parent / "fixtures" / "oracle-provenance"
    asked = {q["id"]: q for q in json.loads(
        (fixtures / "requirements-readiness.json").read_text(encoding="utf-8"))["open_questions"]}
    q1, q7 = asked["Q1"], asked["Q7"]
    check_eq("a question written before t-227 (the verbatim cmp2 Q1) is still answerable as it stands",
             contract.question_errors(q1), [])
    check_eq("a before/now question is answerable as it stands", contract.question_errors(q7), [])
    check("`claim` is a reading origin", "claim" in contract.READING_ORIGINS)
    # the fixture predates the `claim` field (HF4-7): the texts are the code's pair, and the question is READ as it
    check_eq("the fixture's Q7 readings are the fixed pair the code builds (less the `claim` mark it predates)",
             q7["readings"], [{k: v for k, v in r.items() if k != "claim"} for r in contract.claim_readings("unknown", "400")])
    check_eq("...and a pair of the code's is recognised by its texts: now = a, before = b",
             (contract.claim_reading_index(q7, "now"), contract.claim_reading_index(q7, "before")), (0, 1))
    check_eq("both readings come from `claim`", [r["from"] for r in q7["readings"]], ["claim", "claim"])
    check_in("with the base revision unreadable, reading (b) says so and asks what it was",
             "the behaviour before the change is the expected one - unknown; say what it was",
             q7["readings"][1]["reading"])
    known = contract.claim_readings("400", "403")
    check_in("with a known before, reading (b) names it", "(400)", known[1]["reading"])
    check_in("and reading (a) names the behaviour now as data", "(403)", known[0]["reading"])
    check_eq("two readings, no third: the person's own wording is always open to them, never written",
             len(known), 2)

    only_before = {k: v for k, v in q7.items() if k != "now"}
    check_in("`before` without `now` asks nothing", "carries `before` but no `now`",
             contract.question_errors(only_before))
    no_where = dict(q7, now={"value": "400", "where": " "})
    check_in("a `now` with no `where` is refused", "question.now needs value and where",
             contract.question_errors(no_where))
    check_in("a `before` that is not an object is refused", "question.before needs value and where",
             contract.question_errors(dict(q7, before="400")))
    from_code = json.loads(json.dumps(q7))
    from_code["readings"][0]["from"] = "code"
    check_in("a reading `from: code` on a before/now question is refused (NOW is data, not a source)",
             "readings[0].from must be `claim`", contract.question_errors(from_code))
    ordinary = json.loads(json.dumps(q1))
    ordinary["readings"][0]["from"] = "code"
    check_eq("while an ordinary question may still cite the code", contract.question_errors(ordinary), [])


# --- GW1-32: ONE list of the forms of an answer ---------------------------------------------------------------------------------

LINE_ITEM = {"id": "fx-1", "check": "fx", "class": "person_decides", "message": "the stand lacks a second user", "fix": "write the line",
             "waives": [{"block": "stand gap: TC-1", "stage": "S5", "option": "accept"}]}
WORDS_ITEM = {"id": "fx-2", "check": "fx", "class": "person_decides", "message": "a words item", "fix": "say it"}
RENUMBERED = dict(LINE_ITEM, id="fx-9")


def forms_data(questions=None, findings=None, cards=None, example="") -> dict:
    return {"task": TICKET, "open_questions": questions or [], "case_id_example": example, "stand_gap_cards": cards or [],
            "rehearsal": ({"gate": "A", "next_stage": "S5", "can_proceed": False, "by_class": {}, "findings": findings}
                          if findings is not None else {})}


def read_by(row: dict, data: dict, questions: list):
    """Feed the row's `example` to the function its `reader` names; the answer is the reader's own count of what it took."""
    import story_run
    example, reader = row["example"], row["reader"]
    if reader == "parse_choices":
        parsed = QR.parse_choices(example, questions, [full_id(9)])
        return len(parsed["choices"]) + len(parsed["not_needed"]) + len(parsed["case_tokens"])
    if reader == "read_stand_gap_answers":
        return len(gate_brief.read_stand_gap_answers(example, [{"id": "g-1", "case_id": full_id(9)}])["read"])
    driver = story_run.Driver.__new__(story_run.Driver)
    if reader == "Driver.as_is_word":
        return int(driver.as_is_word("gate_A", example))
    if reader == "Driver.read_finding_doors":
        findings = [f for f in data["rehearsal"]["findings"] if f.get("waives")]
        shown = "\n".join(f"- [{f['id']}] {f['message']}" for f in findings)
        doors = {f["id"]: f["waives"] for f in findings}
        return len(driver.read_finding_doors(example, findings, shown, doors)["read"])
    return -1       # a reader this test does not know is a red line, not a pass


def test_answer_forms_are_one_list_and_each_has_its_reader() -> None:
    """GW1-32: every form with an example is taken by the reader it names (FR-11, AR-24); a line outside the list is taken by none."""
    questions = [question("Q1"), question("Q4")]
    findings = [LINE_ITEM, WORDS_ITEM, dict(WORDS_ITEM, id="cp-1", check="case_preconditions", message=full_id(9) + ": needs a user")]
    gap = {"id": "g-1", "case_id": full_id(9)}
    cards = ["## Stand gaps (1)"] + gate_brief._answer_words([gap], ["g-1"], gate_brief.stand_gap_words(), {"g-1": full_id(9)},
                                                             gate_brief.stand_gap_word_of())
    data = forms_data(questions, findings, cards, full_id(9))
    forms = gate_brief.answer_forms(data, questions)
    names = [row["form"] for row in forms]
    check_eq("GW1-32 each form is on the list once (one line per form)", len(names), len(set(names)))
    for expected in ("<question id>: <letter>", "<question id>: not needed", "<full case id>: manual", "<full case id>: automate",
                     "<full case id>: accept as blocked", gate_brief.STAND_GAP_FORM, "<item id>: accept <your reason>", "approve as is"):
        check_in(f"GW1-32 the list holds {expected}", expected, names)
    for row in forms:
        check_eq(f"GW1-32 a row carries exactly the five keys: {row['form']}", sorted(row), ["example", "form", "reader", "says", "where"])
        check(f"GW1-32 the example of `{row['form']}` is taken by {row['reader']}", read_by(row, data, questions) == 1,
              f"{row['example']!r} -> {read_by(row, data, questions)}")
    # the negative control: a line that is on no form is read by none of the readers (the controls share the readers' own shape)
    check_eq("GW1-32 control: `Q1: maybe` is no choice and no `not needed`", read_by(
        {"example": "Q1: maybe", "reader": "parse_choices"}, data, questions), 0)
    check_eq("GW1-32 control: a stand-gap line with an unlisted word is not read", read_by(
        {"example": f"{full_id(9)}: maybe", "reader": "read_stand_gap_answers"}, data, questions), 0)
    check_eq("GW1-32 control: an item line with an unlisted word is not read", read_by(
        {"example": "fx-1: maybe", "reader": "Driver.read_finding_doors"}, data, questions), 0)
    check_eq("GW1-32 control: `approve as is, but fix X` is not the as-is word", read_by(
        {"example": "approve as is, but fix X", "reader": "Driver.as_is_word"}, data, questions), 0)


def test_answer_forms_edges() -> None:
    """GW1-32 edges: nothing to answer, no letters, a door that is none, a renumbered id, the block outliving the cap."""
    check_eq("GW1-32 edge: no question, no item, no gap - no form", gate_brief.answer_forms(forms_data(), []), [])
    check_eq("GW1-32 edge: and no section", "## How to answer" in gate_brief.render(forms_data()), False)
    check_eq("GW1-32 edge: no form, no block lines", gate_brief.how_to_answer_lines([]), [])
    lonely = question("Q5", 0, readings_unnameable=True)
    names = [row["form"] for row in gate_brief.answer_forms(forms_data([lonely]), [lonely])]
    check_not_in("GW1-32 edge: questions with no letter offer no letter form", "<question id>: <letter>", names)
    check_in("GW1-32 edge: ...only `not needed` (and the case words)", "<question id>: not needed", names)
    three = [question("Q1"), question("Q2"), question("Q3")]
    text = gate_brief.render(forms_data(three, example=full_id(9)))
    check_eq("GW1-32 edge: three questions with the same example - one line per form", text.count("`<question id>: not needed`"), 1)
    # a door of kind none gets no line form, only the as-is word
    none_item = dict(WORDS_ITEM, id="fx-3", message="x" * 80)          # one word longer than 60: no door that passes its own check
    rows = gate_brief.answer_forms(forms_data(findings=[none_item]), [])
    check_eq("GW1-32 edge: an item with no line door - only `approve as is`", [row["form"] for row in rows], ["approve as is"])
    check_eq("GW1-32 edge: ...and no item at all - none", gate_brief.answer_forms(forms_data(findings=[]), []), [])
    # the renumbered id: the example carries the id of THIS rehearsal, and the old id is read by nobody
    rows = gate_brief.answer_forms(forms_data(findings=[RENUMBERED]), [])
    line = next(row for row in rows if row["reader"] == "Driver.read_finding_doors")
    check_in("GW1-32 edge: the example carries the real id of the item", "fx-9: ", line["example"])
    import story_run
    d = story_run.Driver.__new__(story_run.Driver)
    shown = f"- [fx-9] {RENUMBERED['message']}"
    stale = d.read_finding_doors("fx-1: accept known", [RENUMBERED], shown, {"fx-9": RENUMBERED["waives"]})
    check_eq("GW1-32 edge: a renumbered (old) id is read by nobody", (stale["read"], stale["unread"]), ([], []))
    # (the block outliving the cap, with and without a question, is pinned on the golden packet in test_gate_brief_and_retro.py)


def test_answer_line_and_the_helper_sentence() -> None:
    """GW1-32: the last line of a card is its own `Answer:`; one sentence names the assistant; the text a person reads obeys the rules."""
    q1, q5 = question("Q1"), question("Q5", 0, readings_unnameable=True)
    check_eq("GW1-32 the card ends with the forms of THIS question, with its own id",
             gate_brief.question_card(q1, 1)[-1], "  - Answer: `Q1: a`, `Q1: b` or `Q1: not needed`")
    check_eq("GW1-32 a question with no reading is offered `not needed` alone",
             gate_brief.question_card(q5, 1)[-1], "  - Answer: `Q5: not needed`")
    many = question("Q6", len(gate_brief.QUESTION_LETTERS) + 1)
    check_eq("GW1-32 more readings than letters: `not needed` alone", gate_brief.question_card(many, 1)[-1], "  - Answer: `Q6: not needed`")
    data = forms_data([q1, q5], [LINE_ITEM, WORDS_ITEM], example=full_id(9))
    text = gate_brief.render(data)
    for needle in ("a person's helper", "read by a helper", "a helper turns"):
        check_not_in(f"GW1-32 the old helper wording is gone: {needle}", needle, text)
        check_not_in(f"GW1-32 ...and from the constants: {needle}", needle, gate_brief.APPROVAL_FIRST_LINE_TAIL + gate_brief.ANYTHING_ELSE_SENTENCE)
    check_in("GW1-32 the one sentence names the assistant", "the assistant running this story", gate_brief.ANYTHING_ELSE_SENTENCE)
    check_in("GW1-32 the approval-word boundary is kept", "unless your answer starts with the word that approves this gate",
             gate_brief.APPROVAL_FIRST_LINE_TAIL)
    check_eq("GW1-32 the answer block obeys human-questions.md",
             [p["rule"] for p in human_text.problems(text[text.index("## Open questions"):])], [])


if __name__ == "__main__":
    test_answer_forms_are_one_list_and_each_has_its_reader()
    test_answer_forms_edges()
    test_answer_line_and_the_helper_sentence()
    test_a_before_now_question_shows_both_and_asks_the_fixed_pair()
    test_readings_are_built_from_the_matrix()
    test_a_bare_question_is_the_factorys_to_rewrite()
    test_a_bare_question_still_reaches_the_person()
    test_a_card_shows_what_each_answer_changes()
    test_the_star_patch_a_letter_override_and_not_needed()
    test_a_story_from_before_the_fields_reads_as_it_did()
    test_what_cannot_be_read_is_named_not_raised()
    test_a_register_row_without_ac_ref_is_signed_by_its_source()
    test_a_row_that_names_its_register_question_is_not_asked_twice()
    test_no_question_and_no_reading_is_cut()
    test_the_decision_text_holds_the_words_where_they_are_stored()
    test_question_status_comes_from_the_register()
    test_a_register_that_cannot_be_read_is_said_and_never_read_as_answered()
    test_an_empty_register_and_a_question_with_no_readings()
    finish("gate question form")
