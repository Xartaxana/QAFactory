"""GW1-42: a line like `Q1: a (see the ticket)` is told as what it is, and the conductor sees its letter.

`question_register.near_answer` is a HINT over a line `_stray_lines` returned: one letter of the question's readings, never a
recorded choice (`parse_choices` stays strict, FR-12). The card note (`gate_brief.question_note`, branch `named`) says the line
was not read as an answer instead of "no answer"; a `named` history with no words keeps its old text. The driver's note for the
conductor names the letter so the closed question to the person is `confirm Q1 - a?`. Nothing here reaches a network or a model.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import check, check_eq, check_in, check_not_in, cleanup, finish, temp_dir  # noqa: E402

sys.path.insert(0, str(harness.SCRIPTS))
import gate_brief  # noqa: E402
import question_register as QR  # noqa: E402
import story_run  # noqa: E402


def story(root: Path, words: str, ids=("Q1", "Q2")):
    (root / "work").mkdir(parents=True, exist_ok=True)
    rows = [{"id": i, "question": f"question {i}?", "severity": "major",
             "readings": [{"reading": f"reading {n}", "from": "code", "if_chosen": "x"} for n in range(2)]} for i in ids]
    (root / "work" / "requirements-readiness.json").write_text(json.dumps({"verdict": "blocked", "open_questions": rows}), encoding="utf-8")
    (root / "pipeline.json").write_text(json.dumps({"ticket": "T-1", "gates": {"A": {"authorization_source": words}}}), encoding="utf-8")
    return root


def value_of(line: str) -> str:
    return QR._TOKEN.fullmatch(QR._content(line)).group("value")


def hint(line: str, letters="ab"):
    return QR.near_answer(value_of(line), letters)


def main():
    # the table of the spec (letters a, b)
    for label, line, want in (
            ("N1 a letter and a parenthesis", "Q1: a (see the ticket)", "a"),
            ("N2 a letter and a dash", "Q1: a - keep it", "a"),
            ("N3 a letter and a word: a near line, only for the conductor", "Q1: a question for later", "a"),
            ("N4 a letter beyond the readings", "Q1: z (later)", None),
            ("N5 two values", "Q1: a, b", None),
            ("N6 two values with a slash", "Q1: a / b", None),
            ("N7 two values with a semicolon", "Q1: a; b", None),
            ("N8 a word that starts with a letter", "Q1: apple", None),
            ("N9 prose", "Q1: not needed, sorry", None),
            ("N10 a capital is no letter of the readings", "Q1: A (note)", None),
            ("N11 empty value", "Q1:", None),
            ("N12 the second letter", "Q1: b (see)", "b"),
            ("N13 a letter then a digit is no letter", "Q1: a1", None)):
        check_eq(label, hint(line), want)
    check_eq("N14 no readings, no hint", hint("Q1: a (note)", ""), None)
    check_eq("N15 letters as None", hint("Q1: a (note)", None), None)
    check_eq("N16 a list of letters works too", hint("Q1: b (note)", ["a", "b"]), "b")
    check_eq("N17 a value that is not text", QR.near_answer(None, "ab"), None)

    # the hint is never a choice: `parse_choices` reads the strict form only; `Q1: a` and `Q1: b (..)` do not conflict
    root = story(temp_dir(), "Q1: a\nQ1: b (see the ticket)")
    try:
        questions = QR.load(root)["questions"]
        parsed = QR.parse_choices("Q1: a\nQ1: b (see the ticket)", questions, [])
        check_eq("P1 the strict line is the choice, the other records nothing", (parsed["choices"], parsed["conflicts"]), ({"Q1": "a"}, []))
        near = QR.parse_choices("Q1: a (see the ticket)", questions, [])
        check_eq("P2 `Q1: a (note)` is no choice", near["choices"], {})
        check_eq("P3 and the register reader still calls it unread", [x["id"] for x in QR.question_lines_unread("Q1: a (see the ticket)", questions)], ["Q1"])
    finally:
        cleanup(root)

    # the card note
    words = "approve\nQ1: a (see the ticket)\nQ2 is fine by me"
    root = story(temp_dir(), words)
    try:
        by_id = {q["id"]: q for q in QR.load(root)["questions"]}
        note1, note2 = gate_brief.question_note(by_id["Q1"]), gate_brief.question_note(by_id["Q2"])
        check_eq("C1 both are named", (by_id["Q1"]["status"], by_id["Q2"]["status"]), ("named", "named"))
        check_in("C2 the line of Q1 is told as a line not read as an answer", 'on a line the factory did not read as an answer: "Q1: a (see the ticket)"', note1)
        check_not_in("C3 and it does not say no answer", "recorded no answer", note1)
        check_eq("C4 a prose mention keeps the old text", note2, "named in your gate A words; the factory recorded no answer")
        check_eq("C5 a history `named` with no words keeps the old text",
                 gate_brief.question_note({"id": "Q1", "status": "named", "where": "waiver"}), "named in your waiver words; the factory recorded no answer")
        tail = dict(by_id["Q1"], words="approve\n\nEarlier answer at this gate:\nQ1: a (old)")
        check_eq("C6 the replaced earlier answer is not read", gate_brief.question_note(tail), "named in your gate A words; the factory recorded no answer")
        long = dict(by_id["Q1"], words="Q1: a " + "x " * 400)
        check("C7 a long line is cut in the note", len(gate_brief.question_note(long)) < 400, str(len(gate_brief.question_note(long))))
        check_in("C8 ... with the cut shown", '...', gate_brief.question_note(long))
        # F-6 (t-596): ONE reader of the stray line, `stray_line`; the note, the stop's card and the report ask it
        check_eq("S1 stray_line: the line of Q1, shown", QR.stray_line("Q1", words), "Q1: a (see the ticket)")
        check_eq("S2 ... a prose mention is no stray line", QR.stray_line("Q2", words), "")
        check_eq("S3 ... the replaced earlier answer is not read", QR.stray_line("Q1", tail["words"]), "")
        check_eq("S4 ... no id, no words, a value that is not text: empty", (QR.stray_line("", words), QR.stray_line("Q1", ""), QR.stray_line("Q1", None)),
                 ("", "", ""))
        import question_stop
        cards = "\n".join(question_stop.open_cards(root))
        check_in("S5 the stop's card tells the line of Q1 as not read, not as 'no answer'", 'on a line the factory did not read as an answer: "Q1: a (see the ticket)"', cards)
        check_in("S6 ... and the prose mention of Q2 keeps the old sentence (control)", "you named this question in your earlier words, but the factory recorded no answer for it.", cards)
    finally:
        cleanup(root)

    # the conductor's note
    root = story(temp_dir(), "")
    try:
        class Stub:
            task_root = root
            question_lines_shown = ""

        stub = Stub()

        def note(text):
            return story_run.Driver.gate_question_lines_note(stub, text)

        n = note("approve\nQ1: a (see the ticket)")
        check_in("D1 the note names the letter and the closed question", 'Q1 - a. Ask the person "confirm Q1 - a?"', n)
        check_in("D2 the old doors stay", "--defer", n)
        check_eq("D3 the person's text is the line", stub.question_lines_shown, 'Q1: "Q1: a (see the ticket)"')
        n = note("approve\nQ1: z (later)\nQ2: not confirmed")
        check_not_in("D4 a letter beyond the readings gets no hint", "Ask the person", n)
        check_in("D5 ... and the note names the lines", "Q2", n)
        n = note("Q1: a (x)\nQ2: b (y)")
        check_in("D6 two hints, two closed questions", 'Q1 - a; Q2 - b. Ask the person "confirm Q1 - a?" / "confirm Q2 - b?"', n)
        check_not_in("D7 a two-value line gets no hint", "Ask the person", note("Q1: a, b"))
        check_not_in("D8 a line cut for display gets no hint", "Ask the person", note("Q1: a " + "x " * 400))
        check_eq("D9 a clean token has no note", note("Q1: a"), "")
    finally:
        cleanup(root)
    finish("question_register near_answer")


if __name__ == "__main__":
    main()
