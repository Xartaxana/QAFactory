"""GW1-34: a free answer to a register question is read BEFORE the gate A decision seals the plan.

The decision seals the plan, so a line like `Q3: not confirmed, keep open` that no reader understood must not slip under the
approval. `question_register.question_lines_unread` is the pure reader (over `_stray_lines`); `Driver.record_by_code` returns
before the controller call when it finds such a line, or when the register cannot be read, so the answer goes to the conductor
(`_unread_kept_gate`). The code never guesses the letter. Nothing here reaches a network or a model.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import check, check_eq, cleanup, finish, temp_dir  # noqa: E402

sys.path.insert(0, str(harness.SCRIPTS))
import question_register as QR  # noqa: E402
import story_run  # noqa: E402

FENCE = "`" * 3


def story(root: Path, ids=("Q1", "Q2", "Q3"), answers=None, raw_answers=None):
    (root / "work").mkdir(parents=True, exist_ok=True)
    rows = [{"id": i, "question": f"question {i}?", "severity": "major",
             "readings": [{"reading": f"reading {n}", "from": "code", "if_chosen": "x"} for n in range(2)]} for i in ids]
    (root / "work" / "requirements-readiness.json").write_text(json.dumps({"verdict": "blocked", "open_questions": rows}), encoding="utf-8")
    if raw_answers is not None:
        (root / "work" / "question-answers.jsonl").write_bytes(raw_answers)
    return root


def lines_of(root: Path, words: str):
    return QR.question_lines_unread(words, QR.load(root)["questions"])


class Stub:
    """Just enough driver for `record_by_code`: the controller call is a counter."""
    dry = False

    def __init__(self, root, as_is=False):
        self.task_root, self.as_is, self.state, self.calls = root, as_is, {}, []
        self.gate_refusal = ""

    def gate_approval(self, kind, words):
        return True

    def as_is_word(self, kind, words):
        return self.as_is

    def py(self, *argv):
        self.calls.append(argv)
        return 0, "{}"

    def shown_packet(self, kind):
        return ""

    def words_file(self, *a):
        return ""

    def json_file(self, *a):
        return ""

    def words_args(self, *a):
        return []

    def gate_answer_told(self, *a):
        pass

    def report_attribution(self, *a):
        pass

    def gate_question_lines_note(self, words):
        return story_run.Driver.gate_question_lines_note(self, words)


def record(root, words, kind="gate_A", as_is=False, apply_words=""):
    stub = Stub(root, as_is)
    got = story_run.Driver.record_by_code(stub, kind, "S3", words, apply_words=apply_words)
    return got, stub


def main():
    root = story(temp_dir())
    try:
        # the pure reader
        check_eq("R1 a free line about an open question is unread", [x["id"] for x in lines_of(root, "approve\nQ3: not confirmed, keep open")], ["Q3"])
        check_eq("R2 a clean token is read, not stray", lines_of(root, "Q1: a\nQ2: not needed"), [])
        check_eq("R3 empty `Q1:` counts unread", [x["id"] for x in lines_of(root, "Q1:")], ["Q1"])
        check_eq("R4 a tail after a letter is no choice", [x["id"] for x in lines_of(root, "Q1: a (see the ticket)")], ["Q1"])
        check_eq("R5 a line in a fence goes the fenced road, not here", lines_of(root, f"{FENCE}\nQ1: maybe\n{FENCE}"), [])
        check_eq("R6 a quoted line is not read", lines_of(root, "> Q1: maybe"), [])
        check_eq("R7 an id the register does not hold is not here", lines_of(root, "Q9: maybe"), [])
        tail = "Q1: a\n\nEarlier answer at this gate:\nQ2: maybe"
        check_eq("R8 the replaced earlier answer is not read", lines_of(root, tail), [])
        long = lines_of(root, "Q1: " + "x " * 400)
        check("R9 a long line is cut for the view", len(long) == 1 and len(long[0]["line"]) <= QR.MAX_NOTICE_LINE, str(long))
        check_eq("R10 no words, no lines", lines_of(root, ""), [])
        check_eq("R11 None words", QR.question_lines_unread(None, QR.load(root)["questions"]), [])
        QR.record_answers(root, "Q2: a", "gate A", "person", None, [])
        check_eq("R12 a question already settled does not count", [x["id"] for x in lines_of(root, "Q2: maybe\nQ3: maybe")], ["Q3"])
        QR.record_answers(root, "Q3: until the report", "gate A", "person", None, [])
        check_eq("R13 a question kept open until the report does not count (no loop)", lines_of(root, "Q3: maybe"), [])

        # the driver
        fresh = story(temp_dir())
        got, stub = record(fresh, "approve\nQ3: not confirmed, keep open")
        check("D1 free line: record_by_code returns False, the controller is not called", got is False and stub.calls == [], str(stub.calls))
        check("D1b the note names the line and the door", "Q3" in stub.question_lines_note and "--defer" in stub.question_lines_note, stub.question_lines_note)
        got, stub = record(fresh, "approve\nQ1: a")
        check("D2 clean token: records as today", got is True and len(stub.calls) == 1 and stub.question_lines_note == "")
        got, stub = record(fresh, "approve\nQ3: not confirmed", as_is=True)
        check("D3 `approve as is` does not return", got is True and len(stub.calls) == 1)
        got, stub = record(fresh, "approve\nQ3: not confirmed", kind="gate_B")
        check("D4 gate B is not touched", got is True and len(stub.calls) == 1)
        got, stub = record(fresh, "approve\nQ3: maybe\nEarlier answer at this gate:\n", apply_words="approve")
        check("D5 apply_words: the new answer's lines alone are read", got is True and len(stub.calls) == 1)
        got, stub = record(fresh, "approve\nQ1:")
        check("D6 empty `Q1:` goes to the conductor", got is False and stub.calls == [])

        broken = story(temp_dir())
        (broken / "work" / "question-answers.jsonl").mkdir()       # a path that cannot be read as a file
        view = QR.load(broken)
        got, stub = record(broken, "approve\nQ3: not confirmed")
        check("D7 unreadable register: unknown, the conductor takes it (FR-59)",
              got is False and stub.calls == [] and "could not be read" in stub.question_lines_note,
              f"{view['skipped']} {view['problems']} {stub.question_lines_note!r}")
        # t-550 F6: a register whose `load` raises is not a crash of the driver: unknown goes to the conductor (FR-59)
        real_load = QR.load
        QR.load = lambda root: (_ for _ in ()).throw(RuntimeError("register exploded"))
        try:
            got, stub = record(fresh, "approve\nQ3: not confirmed")
        finally:
            QR.load = real_load
        check("D8 `load` raises: no crash, the conductor takes it, the note says so",
              got is False and stub.calls == [] and "RuntimeError" in stub.question_lines_note and "could not be read" in stub.question_lines_note,
              repr(stub.question_lines_note))

        # t-550 F7: a dry run records no answer; the controller is called (with --no-answers) and the note is not made
        dry_stub = Stub(fresh)
        dry_stub.dry = True
        got = story_run.Driver.record_by_code(dry_stub, "gate_A", "S3", "approve\nQ3: not confirmed, keep open")
        check("D9 dry: the controller is called, no note", got is True and len(dry_stub.calls) == 1 and dry_stub.question_lines_note == "",
              repr(dry_stub.question_lines_note))

        # t-550 F4/F5: the kept approval held on such a line is told in the person's words and names the line; the note is told once
        got, stub = record(fresh, "approve\nQ3: not confirmed, keep open")
        d = story_run.Driver.__new__(story_run.Driver)
        d.question_lines_note, d.question_lines_shown, d.gate_refusal = stub.question_lines_note, stub.question_lines_shown, ""
        text = d.kept_answer_text({"gate": "A", "words": "approve\nQ3: not confirmed, keep open", "at": "10:00"})
        check("D10 kept text names the line and the way to answer, not 'the controller printed nothing'",
              "Q3" in text and "not confirmed" in text and "Q3: not needed" in text and "printed nothing" not in text and "answer `approve` again" not in text, text)
        check("D10b and the note is consumed (it reaches no other call)", d.question_lines_note == "")
        text = d.kept_answer_text({"gate": "A", "words": "approve", "at": "10:00"})
        check("D10c a second kept text is the plain one", "printed nothing" in text, text)
        d.question_lines_note, d.question_lines_shown, d.gate_refusal = "", "", "old refusal"
        d.gate_approval = lambda kind, words: True
        d.state, d.save_state, d.controller_state = {}, (lambda: None), (lambda: {})
        d.judged_reply, d.gate_open_items = (lambda *a, **k: ""), (lambda *a, **k: None)
        sent = []
        d.unread = lambda kind, stage, dispatch, text, words="", **k: sent.append(text)
        d.question_lines_note = "\n\nLines about questions the code could not read: Q3."
        d._unread_kept_gate("gate_A", "S3", "", "qtext", "approve\nQ3: x", "")
        check("D11 the conductor is told the approval word was said, not the opposite",
              len(sent) == 1 and "approval word" in sent[0] and "not the approval word" not in sent[0] and "Q3" in sent[0], repr(sent))
        cleanup(fresh)
        cleanup(broken)
    finally:
        cleanup(root)
    finish("question_lines_unread")


if __name__ == "__main__":
    main()
