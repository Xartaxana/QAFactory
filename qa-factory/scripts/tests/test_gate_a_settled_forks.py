"""HF4-8 (hotfix-12586/4): gate A does not ask again a contradiction whose reading fork a register question closed, and its
"Already decided by you" section lists the questions the person answered.

The live run TP1-12586 (0.10.3) put three cards at gate A - R-3 (TS-1), R-5 (TS-2) and R-1 (TS-8) - for forks the person had
closed at the S2 stop (`Q1 b`, `Q2 a`, `Q4 a`; the register's `## Reading forks` says so in the `Decision` cell), and listed none of
the seven answers under "Already decided by you". The fixture `fixtures/run-12586-gate-a/` is that story as the stand held it.

Keys: K1 the seam (the stand's register, answers and plan rows through `contradiction_questions`), K2 the negative control, K3 the
seam through the whole brief, K4 one key per edge and per unwelcome input of the spec, K5 the limits AT and BEYOND, K6 the callers of
`contradiction_questions`, K7 the contract text (a doc-witness with a negative control).
"""
import json
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import FIXTURES, SCRIPTS, check, check_eq, check_in, check_not_in, cleanup, finish, temp_dir  # noqa: E402

sys.path.insert(0, str(SCRIPTS))

import gate_brief  # noqa: E402
import planning_contract as PC  # noqa: E402
import question_register as QR  # noqa: E402

FIX = FIXTURES / "run-12586-gate-a"
TASK = "TP1-12586"
PLUGIN = SCRIPTS.parent


def story(prefix: str = "qa-hf48-") -> tuple:
    """(base, task_root): the stand's story at gate A in a throwaway project."""
    base = temp_dir(prefix) / "qa-factory"
    root = base / "artifacts" / TASK
    shutil.copytree(FIX / "work", root / "work")
    shutil.copyfile(FIX / "pipeline.json", root / "pipeline.json")
    (root / "state").mkdir(parents=True)
    (base / "state" / "cost").mkdir(parents=True)
    (base / "config.json").write_text("{}", encoding="utf-8")
    return base, root


def rows_of(root: Path) -> list:
    return json.loads((root / "work" / "test-plan.json").read_text(encoding="utf-8"))["rows"]


def ids(root: Path, rows=None) -> list:
    return [q["id"] for q in gate_brief.contradiction_questions(root, rows if rows is not None else rows_of(root))]


def answers_path(root: Path) -> Path:
    return root / "work" / "question-answers.jsonl"


def records(root: Path) -> list:
    return [json.loads(line) for line in answers_path(root).read_text(encoding="utf-8").splitlines() if line.strip()]


def write_records(root: Path, recs: list) -> None:
    answers_path(root).write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in recs) + "\n", encoding="utf-8", newline="\n")


def without(root: Path, qid: str) -> None:
    write_records(root, [r for r in records(root) if r["id"] != qid])


def edit_record(root: Path, qid: str, **changes) -> None:
    write_records(root, [dict(r, **changes) if r["id"] == qid else r for r in records(root)])


def edit_register(root: Path, old: str, new: str) -> None:
    path = root / "work" / "requirements-register.md"
    text = path.read_text(encoding="utf-8")
    check(f"(setup) the register holds `{old[:40]}`", old in text)
    path.write_text(text.replace(old, new, 1), encoding="utf-8", newline="\n")


def section(text: str, heading: str) -> str:
    start = text.find(heading)
    if start < 0:
        return ""
    rest = text[start + len(heading):]
    stop = re.search(r"(?m)^## ", rest)
    return rest[:stop.start()] if stop else rest


def brief(root: Path, **changes) -> str:
    return gate_brief.render(dict(gate_brief.collect(TASK, root), **changes))


FORK_R3 = "Q1 b adopted: outcome check"


def test_k1_the_stand_story_asks_only_what_nobody_closed() -> None:
    """K1 (seam): the recorded register, answers and plan rows -> exactly {R-2 (TS-8), TS-14}; before the fix the cards were
    {R-3, R-5, R-1, TS-14} (`gate-a-brief.txt:41-65` of the stand)."""
    base, root = story()
    try:
        questions = gate_brief.contradiction_questions(root, rows_of(root))
        check_eq("K1: R-2 (TS-8) and TS-14 are asked, nothing else", [q["id"] for q in questions], ["R-2", "TS-14"])
        check_in("K1: the R-2 card is TS-8's - the contradiction nobody was asked about", "TS-8 (R-2)", questions[0]["question"])
        check_in("K1: ...and it quotes R-2, not the closed R-1 or R-4", "R-2", " ".join(s["where"] for s in questions[0]["source_says"]))
        check_not_in("K1: ...no reading of the closed R-1 is put to the person", "R-1", json.dumps(questions[0]["readings"]))
        check_eq("K1: the fork reader gives the stand's four forks, each with its question",
                 PC.register_fork_questions((root / "work" / "requirements-register.md").read_text(encoding="utf-8")),
                 {"R-1": ["Q4"], "R-3": ["Q1"], "R-4": ["Q3"], "R-5": ["Q2"]})
        # the old behaviour is the same story without the forks' ids: it is what the stand showed
        edit_register(root, "| Q4 a adopted: feature wanted |", "| question at gate A |")
        edit_register(root, "| Q1 b adopted: outcome check |", "| question at gate A |")
        edit_register(root, "| Q3 b adopted: Move only |", "| question at gate A |")
        edit_register(root, "| Q2 a adopted: Move must succeed, 400 is APP_BUG |", "| question at gate A |")
        check_eq("K1 control: forks that name no question leave the stand's four cards (R-1 first for TS-8, as it was)",
                 ids(root), ["R-3", "R-5", "R-1", "TS-14"])
    finally:
        cleanup(base.parent)


def test_k2_k4_what_must_still_be_asked() -> None:
    """K2 (negative control) and K4 (one key per edge and per unwelcome input): the direction of every error is "ask"."""
    base, root = story()
    try:
        without(root, "Q1")
        check_eq("K2: Q1 is not answered -> R-3 is asked again (the closing is the answer, not the mention)", ids(root), ["R-3", "R-2", "TS-14"])
    finally:
        cleanup(base.parent)

    cases = [
        ("K4 deferred_to_report is not settled", lambda r: edit_record(r, "Q1", status="deferred_to_report", reading=""), ["R-3", "R-2", "TS-14"]),
        ("K4 with_designer is not settled", lambda r: edit_record(r, "Q1", status="with_designer", reading=""), ["R-3", "R-2", "TS-14"]),
        ("K4 an answer given on another text of the question (changed since) does not close the new text",
         lambda r: edit_record(r, "Q1", row_hash="0" * 64), ["R-3", "R-2", "TS-14"]),
        ("K4 an answered question with an unreadable row_hash (a number) closes nothing",
         lambda r: edit_record(r, "Q1", row_hash=12345), ["R-3", "R-2", "TS-14"]),
        ("K4 an answered question with no row_hash closes nothing", lambda r: edit_record(r, "Q1", row_hash=""), ["R-3", "R-2", "TS-14"]),
        ("K4 `status: answered` with no `at` closes nothing", lambda r: edit_record(r, "Q1", at=""), ["R-3", "R-2", "TS-14"]),
        ("K4 an answers line with broken JSON: nothing closes (the answers may be missing), even Q1 that read fine",
         lambda r: answers_path(r).write_text(answers_path(r).read_text(encoding="utf-8") + "{broken\n", encoding="utf-8"),
         ["R-3", "R-5", "R-1", "TS-14"]),
    ]
    for label, setup, expected in cases:
        base, root = story()
        try:
            setup(root)
            check_eq(label, ids(root), expected)
        finally:
            cleanup(base.parent)

    # the Decision cell: what counts as naming a question
    unwelcome = [
        ("K4 `Q1` in the cell while the register holds only `Q10`: not the same id", FORK_R3, "Q1 b adopted", "q10"),
        ("K4 `Q-1` names nothing", FORK_R3, "Q-1 b adopted: outcome check", ""),
        ("K4 `q1` (lower case) names nothing", FORK_R3, "q1 b adopted: outcome check", ""),
        ("K4 an id inside a path is not the question", FORK_R3, "work/Q1.md b adopted", ""),
        ("K4 an id that does not start the cell does not close (`question at gate A (see Q1)`)", FORK_R3, "question at gate A (see Q1)", ""),
        ("K4 an id the register does not hold closes nothing", FORK_R3, "Q9 b adopted: outcome check", ""),
        ("K4 an empty Decision cell leaves the fork open", FORK_R3, "", ""),
    ]
    for label, old, new, mode in unwelcome:
        base, root = story()
        try:
            if mode == "q10":
                # Q10 is answered, Q1 is gone: the cell says `Q1`
                data = json.loads((root / "work" / "requirements-readiness.json").read_text(encoding="utf-8"))
                one = next(q for q in data["open_questions"] if q["id"] == "Q1")
                data["open_questions"] = [q for q in data["open_questions"] if q["id"] != "Q1"] + [dict(one, id="Q10")]
                (root / "work" / "requirements-readiness.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
                tenth = QR._hash(next(q for q in data["open_questions"] if q["id"] == "Q10"))
                write_records(root, [r for r in records(root) if r["id"] != "Q1"]
                              + [dict(next(r for r in records(root) if r["id"] == "Q2"), id="Q10", reading="b", row_hash=tenth)])
            edit_register(root, f"| {old} |", f"| {new} |")
            check_eq(label, ids(root), ["R-3", "R-2", "TS-14"])
        finally:
            cleanup(base.parent)

    # no `## Reading forks`, no Decision column, a stray pipe: nothing is read, today's cards stay
    register = (FIX / "work" / "requirements-register.md").read_text(encoding="utf-8")
    check_eq("K4 a register with no `## Reading forks` section names nothing",
             PC.register_fork_questions(register.replace("## Reading forks", "## Something else")), {})
    check_eq("K4 a fork table with no Decision column names nothing",
             PC.register_fork_questions(register.replace("| Behavior difference | Decision |", "| Behavior difference | Verdict |")), {})
    check_eq("K4 a row with a stray unescaped pipe has another cell count than its header: that row names nothing, its neighbours still do",
             PC.register_fork_questions(register.replace("| Q1 b adopted: outcome check |", "| Q1 b adopted | outcome check |")),
             {"R-1": ["Q4"], "R-4": ["Q3"], "R-5": ["Q2"]})
    check_eq("K4 an escaped pipe in the cell does not shift the columns (axis 21)",
             PC.register_fork_questions(register.replace("| Q1 b adopted: outcome check |", r"| Q1 b adopted: A \| B |")).get("R-3"), ["Q1"])
    check_eq("K4 the text is empty", PC.register_fork_questions(""), {})
    base, root = story()
    try:
        edit_register(root, "## Reading forks", "## Notes")
        check_eq("K4 a register with no fork table gives today's cards", ids(root), ["R-3", "R-5", "R-1", "TS-14"])
    finally:
        cleanup(base.parent)

    # a cell naming two questions is closed when BOTH are
    for label, setup, expected in (
            ("K4 a cell with two ids (`Q1 b, Q6`) is closed when both are answered", lambda r: None, ["R-2", "TS-14"]),
            ("K4 ...and asked while one of them is not", lambda r: without(r, "Q6"), ["R-3", "R-2", "TS-14"])):
        base, root = story()
        try:
            edit_register(root, "| Q1 b adopted: outcome check |", "| Q1 b, Q6 adopted: outcome check |")
            check_eq("(setup) the reader gives both ids", PC.register_fork_questions(
                (root / "work" / "requirements-register.md").read_text(encoding="utf-8"))["R-3"], ["Q1", "Q6"])
            setup(root)
            check_eq(label, ids(root), expected)
        finally:
            cleanup(base.parent)

    # the text of the decisions still names an R (today's rule), per contradicted R
    base, root = story()
    try:
        pipeline = json.loads((root / "pipeline.json").read_text(encoding="utf-8"))
        pipeline["stage_overrides"] = [{"stage": "S3", "match": "x", "decision": "R-2: a"}]
        check_eq("K4 a recorded word that names R-2 closes TS-8's last open contradiction (today's rule, kept)",
                 [q["id"] for q in gate_brief.contradiction_questions(root, rows_of(root), pipeline)], ["TS-14"])
    finally:
        cleanup(base.parent)

    # a row whose contradictions are all closed except one keeps that one (TS-8: R-1 -> Q4, R-4 -> Q3, R-2 has no fork)
    base, root = story()
    try:
        row = next(r for r in rows_of(root) if r["id"] == "TS-8")
        card = gate_brief.contradiction_questions(root, [row])[0]
        check_eq("K4 TS-8: R-1 and R-4 are closed, R-2 has no fork -> the card is R-2's", card["id"], "R-2")
    finally:
        cleanup(base.parent)


def test_k3_the_brief_prints_what_is_decided() -> None:
    """K3 (seam): the whole brief of the stand's story."""
    base, root = story()
    try:
        text = brief(root)
        opened = section(text, "## Open questions")
        decided = section(text, "## Already decided by you")
        for card in ("R-1", "R-3", "R-5"):
            check_not_in(f"K3: no `{card}` card in Open questions", f"**{card}**", opened)
        check_in("K3: the contradiction nobody settled is asked", "**R-2**", opened)
        check_in("K3: ...and TS-14", "**TS-14**", opened)
        check_in("K3: ...and Open questions counts two", "## Open questions (2)", text)
        lines = [ln for ln in decided.splitlines() if re.match(r"- Q\d: ", ln)]
        check_eq("K3: Q1..Q7 are listed under Already decided, in order", [ln.split(":")[0] for ln in lines],
                 [f"- Q{n}" for n in range(1, 8)])
        by_id = {ln.split(":")[0][2:]: ln for ln in lines}
        check_eq("K3: Q3 (a letter) shows the reading's text and where it was given",
                 by_id["Q3"], "- Q3: Move only is delivered scope (your answer when the requirements were checked)")
        check_in("K3: Q6 (no letter) shows the person's words (the copy of its own id is dropped, as the S5 line does: one renderer)", "- Q6: \"we check everything that can be configured", by_id["Q6"])
        check_in("K3: Q7 (words, given at gate A) is listed as words", "(your words at gate A)", by_id["Q7"])
        check_in("K3: Q7's words are cut at the limit with an ellipsis", "…", by_id["Q7"])
        check_in("K3: the accepted source gap of the stand's pipeline is not invented by this fixture (section is not empty)", "Q1:", decided)
        # the order: a brief longer than the cap loses a tail, never an open question for a decided line
        long = brief(root, documents={f"d{n}": f"p{n}" for n in range(150)})
        check_in("K3: the brief is cut at its cap", "brief truncated at", long)
        check("K3: ...and the open cards stand BEFORE the decided section, whole",
              long.index("**R-2**") < long.index("## Already decided by you") and "**TS-14**" in long.split("## Already decided by you")[0])
        check_in("K3: ...and the decided lines are still there", "- Q1: ", long)
    finally:
        cleanup(base.parent)

    # a story with no decision of the old kinds still prints the section when a question is answered
    base, root = story()
    try:
        text = brief(root)
        check_in("K3: only answers, no pass, no gap: the section is printed", "## Already decided by you — repeated, not re-asked", text)
    finally:
        cleanup(base.parent)

    # unreadable answers: one line, NO item listed as decided, and the questions they may settle are asked again (FR-10)
    base, root = story()
    try:
        answers_path(root).write_text(answers_path(root).read_text(encoding="utf-8") + "{broken\n", encoding="utf-8")
        text = brief(root)
        decided = section(text, "## Already decided by you")
        check_in("K4: broken answers line -> one line says some answers could not be read",
                 "some of your earlier answers could not be read; questions they settle are shown again above", decided)
        check_in("K4: ...and the cards of R-3, R-5 and R-1 are shown again", "**R-3**", section(text, "## Open questions"))
        check_not_in("K4: ...and nothing is listed as decided while its card is asked (FR-10: one packet, no contradiction)", "- Q2: ", decided)
        check_eq("K4: ...the section holds that one line only", [ln for ln in decided.splitlines() if ln.startswith("- ")],
                 ["- some of your earlier answers could not be read; questions they settle are shown again above"])
        check("K4: ...and 'above' is true: the open cards come before the section", text.index("## Open questions") < text.index("## Already decided by you"))
        shutil.copyfile(FIX / "work" / "question-answers.jsonl", answers_path(root))
        check_not_in("K4: with the file whole again the line is gone", "could not be read", section(brief(root), "## Already decided by you"))
    finally:
        cleanup(base.parent)


def test_k5_the_limits() -> None:
    """K5: ten lines, then `(+K more)`; 160 characters of words, then `…`. AT and BEYOND."""
    def item(n, words="x"):
        return {"id": f"Q{n}", "status": "answered", "reading": "", "reading_text": "", "words": words, "where": "gate A"}

    def lines_for(count, words="x"):
        return gate_brief._answered_lines({"answered": {"items": [item(n, words) for n in range(1, count + 1)], "unreadable": False}})

    ten, eleven = lines_for(10), lines_for(11)
    check_eq("K5: ten answers are ten lines and no tail (AT the limit)", (len(ten), any("more" in ln for ln in ten)), (10, False))
    check_eq("K5: eleven answers are ten lines and `(+1 more ...)` (BEYOND)", (len(eleven), eleven[-1]),
             (11, "- (+1 more — work/question-answers.jsonl)"))
    check_eq("K5: the tail counts the rest (25 -> +15)", lines_for(25)[-1], "- (+15 more — work/question-answers.jsonl)")
    check_eq("K5: no answers, nothing", gate_brief._answered_lines({"answered": {"items": [], "unreadable": False}}), [])
    check_eq("K5: no `answered` key at all (a caller that does not carry it), nothing", gate_brief._answered_lines({}), [])
    one = lambda words: lines_for(1, words)[0]          # noqa: E731
    check_eq("K5: 160 characters are shown whole", one("w" * 160), f"- Q1: \"{'w' * 160}\" (your words at gate A)")
    check_eq("K5: 161 characters are 160 and an ellipsis", one("w" * 161), f"- Q1: \"{'w' * 160}…\" (your words at gate A)")
    check_eq("K5: whitespace is squeezed before it is counted", one("a \n\n  b\t c"), "- Q1: \"a b c\" (your words at gate A)")
    check_eq("K5: a not-needed answer says so", gate_brief._answered_lines({"answered": {"items": [dict(item(2), status="not_needed")], "unreadable": False}}),
             ["- Q2: not needed (your answer at gate A)"])
    check_eq("K5: unreadable answers alone still print one line",
             gate_brief._answered_lines({"answered": {"items": [], "unreadable": True}}),
             ["- some of your earlier answers could not be read; questions they settle are shown again above"])


def test_k6_the_callers() -> None:
    """K6: who calls `contradiction_questions` (the control: the function itself is found by the same pattern)."""
    hits = []
    for path in sorted(SCRIPTS.glob("*.py")):
        for number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
            if "contradiction_questions(" in line:
                hits.append((path.name, "def" if line.lstrip().startswith("def ") else "call"))
    check_eq("K6: the pattern finds the function itself (positive control)", ("gate_brief.py", "def") in hits, True)
    check_eq("K6: the only caller outside the tests is `gate_brief.collect` (gate B builds no R-n card)", hits,
             [("gate_brief.py", "def"), ("gate_brief.py", "call")])


def test_k7_the_contract_says_it() -> None:
    """K7: the settled-fork form of the register template reads back through the one reader (the role-text keys of the form are
    rows of design/role-rules.json)."""
    template = (PLUGIN / "references" / "templates" / "requirements-register.md").read_text(encoding="utf-8")
    # the template's own sample row reads through the one reader (FR-12: the sample is data, not prose)
    check_eq("K7: the template's sample forks read back through the reader", PC.register_fork_questions(template), {"R-2": ["Q1"]})
    quotes = PC.register_fork_quotes(template)
    check("K7 (F2): the template's quote-form sample row reads back through `register_fork_quotes`", list(quotes) == ["R-3"], str(quotes))


if __name__ == "__main__":
    test_k1_the_stand_story_asks_only_what_nobody_closed()
    test_k2_k4_what_must_still_be_asked()
    test_k3_the_brief_prints_what_is_decided()
    test_k5_the_limits()
    test_k6_the_callers()
    test_k7_the_contract_says_it()
    finish("test_gate_a_settled_forks")
