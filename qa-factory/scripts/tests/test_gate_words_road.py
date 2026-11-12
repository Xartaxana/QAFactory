#!/usr/bin/env python3
"""HF8-23 (r0107 S4c, node N1): a person's gate B words reach the delivery guard by one road.

Run 12586 (0.10.5): the person said at gate B "Bug 1 is a bug. deliver with known gaps. Open the MR as a draft"; the controller
recorded the decision and nothing wrote the journal line `stage_guard.rule_delivery` reads, so the MR command stayed blocked and
the refusal asked the person to say it at gate B again. Since this change `controller.py --operation gate-decision --gate B`
records the decision (`gates.B.deliver_with_risks`) and writes the journal line, from `--risks-file` or from a whole line of the
person's words; the guard's refusal over a recorded gate B names the door that opens (`log_append.py --reason-file`).

Keys of the spec (docs/tasks/specs/r0107-s4c-hf8-23-dc1-19.md section 8): h1 the flag, h2 the token line, h2b an old token in the
`Earlier answer` tail, h2c a token with no approval word, h3 the adversarial list, h4 a refused decision writes no line, h4b no
project marker, h5 the reason edges, h6 the refusal text, h6b the door with a two-line reason, h7 the crash shape, h8 damaged
records, (h9, the chosen-bug text, was dropped: a filed bug can move the verdict, see the report), h10 the later decision and the old story,
h11 a reader of the field, h12 the registry. The story is the recorded run of 12586 at gate B (`fixtures/run-12586-gate-b`),
decided again by the real `controller.main`.
"""
import contextlib
import copy
import io
import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import SCRIPTS, check, check_eq, check_in, check_not_in, cleanup, finish, temp_project  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import contract as C  # noqa: E402
import controller as CTL  # noqa: E402
import question_register as QR  # noqa: E402
import runtime_paths as RP  # noqa: E402
import stage_guard as SG  # noqa: E402

import test_gate_b_orders as GB  # noqa: E402

TICKET = "TP1-12586"
REASON = "release window, the bug is known and tracked"
NO = {"delivery_verdict": "no", "delivery_ready": False, "rows": [], "reasons": ["a requirement has no outcome"]}
SENTENCE = "The guard judges a whole command before any of it runs"


@contextlib.contextmanager
def in_cwd(path):
    """The process's cwd moved for the length of one block and put back (the shell's own cwd is never touched)."""
    old = os.getcwd()
    os.chdir(str(path))
    try:
        yield
    finally:
        os.chdir(old)


class Story:
    """A throwaway project holding the recorded gate B story, a ledger whose verdict is `no`, and the guard as the hook runs it."""

    def __init__(self) -> None:
        self.root, self.task, self.controller = GB.fixture_story("qa-gate-words-")
        (self.task / "work").mkdir(parents=True, exist_ok=True)
        (self.task / "work" / "ledger.json").write_text(json.dumps(NO), encoding="utf-8")
        self.seq = 0

    def words(self, text: str) -> Path:
        self.seq += 1
        return GB.words_file(self.task, f"gateB-{self.seq}.txt", text)

    def decide(self, words: str, *extra, project_env: bool = True) -> tuple:
        """`controller.py --operation gate-decision --gate B` in-process: (exit code, the answer's JSON or {"stderr": ...})."""
        argv = ["controller.py", "--task-root", str(self.task), "--operation", "gate-decision", "--gate", "B",
                "--words-file", str(self.words(words)), *extra]
        out, err, code = io.StringIO(), io.StringIO(), 0
        old_argv, old_env = sys.argv, os.environ.get("CLAUDE_PROJECT_DIR")
        sys.argv = argv
        if project_env:
            os.environ["CLAUDE_PROJECT_DIR"] = str(self.root)
        else:
            os.environ.pop("CLAUDE_PROJECT_DIR", None)
        import hooklib
        hooklib._PROJECT_ROOT_CACHE = None      # the root is cached per process (see `run_controller`)
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                try:
                    CTL.main()
                except SystemExit as exc:
                    code = exc.code if isinstance(exc.code, int) else 1
                except ValueError as exc:       # what `controller.py`'s own entry turns into exit 2 and the refusal's text
                    code = 2
                    print(str(exc), file=sys.stderr)
        finally:
            sys.argv = old_argv
            if old_env is None:
                os.environ.pop("CLAUDE_PROJECT_DIR", None)
            else:
                os.environ["CLAUDE_PROJECT_DIR"] = old_env
        text = out.getvalue().strip()
        return code, (json.loads(text) if text.startswith("{") else {"stdout": text, "stderr": err.getvalue()})

    def pipeline(self) -> dict:
        return json.loads((self.task / "pipeline.json").read_text(encoding="utf-8"))

    def journal_path(self) -> Path:
        return RP.record(self.root, "journal.jsonl")

    def journal(self) -> list:
        path = self.journal_path()
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.is_file() else []

    def risk_lines(self) -> list:
        return [row for row in self.journal() if row.get("event") == "deliver_with_risks"]

    def mr(self) -> tuple:
        """`glab mr create --fill` through the guard: (code, the refusal's text)."""
        SG.LAST_DENIAL["message"] = ""
        with contextlib.redirect_stderr(io.StringIO()):
            code = SG.check({"tool_name": "Bash", "cwd": str(self.root), "task_id": TICKET,
                             "tool_input": {"command": "glab mr create --fill"}})
        return code, SG.LAST_DENIAL.get("message") or ""

    def clear_journal(self) -> None:
        self.journal_path().unlink(missing_ok=True)


def h1_the_flag(story: Story) -> None:
    """h1: `--risks-file` -> a decision with the reason, the journal line with the verbatim reason, the MR command ALLOW at verdict `no`."""
    check_eq("h1 control: before the decision the MR command is refused at verdict no", story.mr()[0], SG.DENY)
    reason = story.words(REASON + "\nsecond line, with a \"quote\"\n")
    code, answer = story.decide("approve\n", "--drafts", "d-1", "--mr", "open", "--risks-file", str(reason))
    check_eq("h1 the decision records", (code, answer.get("recorded")), (0, True))
    wanted = REASON + "\nsecond line, with a \"quote\""
    check_eq("h1 the answer says what was recorded and that the journal line stands",
             answer.get("risks"), {"recorded": True, "journal": True})
    check_eq("h1 the receipt stays last in the answer", list(answer)[-1], "decision")
    check_eq("h1 gates.B.deliver_with_risks.reason is the reason verbatim (the field has a producer: AR-22)",
             story.pipeline()["gates"]["B"].get("deliver_with_risks"), {"reason": wanted})
    check_eq("h1 one journal line, for the story as the guard names it, with the reason verbatim",
             [(row["task"], row["reason"]) for row in story.risk_lines()], [(TICKET, wanted)])
    check_eq("h1 glab mr create at verdict no: ALLOW", story.mr()[0], SG.ALLOW)
    check_eq("h1 the verdict word did not move", json.loads((story.task / "work" / "ledger.json").read_text())["delivery_verdict"], "no")


def h2_the_token(story: Story) -> None:
    """h2: a whole line of the words in the packet's form does the same; h2b the tail; h2c no approval word."""
    story.clear_journal()
    code, answer = story.decide("approve\ndeliver with known gaps: " + REASON + "\n", "--drafts", "d-1", "--mr", "open")
    check_eq("h2 the token line records the decision and the journal line", (code, answer.get("risks")), (0, {"recorded": True, "journal": True}))
    check_eq("h2 the reason is the line's, verbatim", [row["reason"] for row in story.risk_lines()], [REASON])
    check_eq("h2 glab mr create: ALLOW", story.mr()[0], SG.ALLOW)
    story.clear_journal()
    tail = "approve\n\nEarlier answer at this gate:\ndeliver with known gaps: " + REASON + "\n"
    code, answer = story.decide(tail, "--drafts", "d-1", "--mr", "open")
    check_eq("h2b a token in the `Earlier answer` tail only: the decision records, no risk, no line",
             (code, answer.get("recorded"), "risks" in answer, story.risk_lines(),
              "deliver_with_risks" in story.pipeline()["gates"]["B"]), (0, True, False, [], False))
    check_eq("h2b the same words with the token above the tail record it", QR.risk_reason_of("deliver with known gaps: x\n\nEarlier answer at this gate:\nQ"),
             {"found": True, "reason": "x", "conflict": False})
    import story_run
    driver = story_run.Driver.__new__(story_run.Driver)
    check_eq("h2c the printed form alone (no approval word on the first line) is no approval: the driver road goes to the conductor",
             [driver.gate_approval("gate_B", words) for words in ("deliver with known gaps: x", "approve\ndeliver with known gaps: x")],
             [False, True])


def h3_the_adversarial_list() -> None:
    """h3: each stays `not found`, in the register's reader and (through the controller) in the recorded decision."""
    word = "deliver with known gaps"
    for text in ("do not " + word, word + "?", "> " + word + ": x", "```\n" + word + ": x\n```", "Bug 1: " + word,
                 word + " later: x", "I think we should " + word + ": x", word + ".", "", "   ", word + "s: x", "deliver  with known gaps: x"):
        check_eq(f"h3 `{text[:40]!r}` is not the word", QR.risk_reason_of(text)["found"], False)
    for text, reason in ((word + ": x", "x"), ("  " + word.upper() + " : x  ", "x"), ("- " + word, ""), ("1. " + word + ":", ""),
                         (word + ": x\n" + word + ": x", "x"), ("﻿" + word + ": x", "x"), (word + ": x", "x")):
        found = QR.risk_reason_of(text)
        check_eq(f"h3 control `{text[:30]!r}` is read", (found["found"], found["reason"], found["conflict"]), (True, reason, False))
    check_eq("h3 two reasons are a conflict, nothing is returned as the reason",
             QR.risk_reason_of(word + ": a\n" + word + ": b"), {"found": True, "reason": "", "conflict": True})
    check_eq("h3 a 200 KB line costs one pass and finds no word", QR.risk_reason_of("- " * 100000 + "x")["found"], False)
    saved = QR.VOCAB_PATH
    QR.VOCAB_PATH = Path(SCRIPTS) / "no-such-vocabulary.json"
    try:
        try:
            QR.risk_reason_of(word + ": x")
            raised = False
        except RuntimeError:
            raised = True
        check_eq("h3 a vocabulary that cannot be read is a package defect the caller sees, never a yes", raised, True)
    finally:
        QR.VOCAB_PATH = saved


def h3b_the_adversarial_words_record_no_risk(story: Story) -> None:
    story.clear_journal()
    code, answer = story.decide("approve\nBug 1: deliver with known gaps\ndo not deliver with known gaps: x\n", "--drafts", "d-1")
    check_eq("h3 words that only mention it: recorded, no risk, no line, and the MR command stays refused",
             (code, "risks" in answer, story.risk_lines(), story.mr()[0]), (0, False, [], SG.DENY))


def h4_no_line_over_an_unrecorded_decision(story: Story) -> None:
    """h4: a refused decision writes no line; h4b: no project marker is no exception and no lost decision."""
    story.clear_journal()
    code, refused = story.decide("approve\ndeliver with known gaps: x\n", "--drafts", "d-1", "--bugs", "not_ordered")
    check_eq("h4 a refused decision (--bugs not_ordered over chosen drafts) exits 2", code, 2)
    check_eq("h4 ... and writes no journal line", story.risk_lines(), [])
    code, preview = story.decide("approve\ndeliver with known gaps: x\n", "--drafts", "d-1", "--build-only")
    check_eq("h4 --build-only records nothing and writes no line", (code, preview.get("recorded"), story.risk_lines()), (0, False, []))
    check_eq("h4 ... and shows the field the decision WOULD carry", preview["request"].get("deliver_with_risks"), {"reason": "x"})
    # h4b: the story's task root with NO marker above it (F-1, E7): the real `log_append.write` finds no project and exits 3, nothing is
    # patched. The marker file is taken away by a byte copy and put back from it; cwd is a folder with no marker above either.
    config = story.root / "qa-factory" / "config.json"
    kept_config = config.read_bytes()
    config.unlink()
    try:
        with in_cwd(story.root.parent):
            code, answer = story.decide("approve\ndeliver with known gaps: " + REASON + "\n", "--drafts", "d-1")
    finally:
        config.write_bytes(kept_config)
    check_eq("h4b the marker is back byte for byte", config.read_bytes(), kept_config)
    risks = answer.get("risks") or {}
    check_eq("h4b no project marker: exit 0, the decision stands, the journal line did not", (code, answer.get("recorded"), risks.get("journal")),
             (0, True, False))
    check_in("h4b ... and the answer names the door", "log_append.py --event deliver_with_risks --task " + TICKET + " --reason-file", risks.get("line", ""))
    check_eq("h4b ... the field is recorded all the same", story.pipeline()["gates"]["B"].get("deliver_with_risks"), {"reason": REASON})


def f1_the_side_writes_follow_the_story(story: Story) -> None:
    """F-1 (r0107): the journal line the guard reads lands in the STORY's project, whatever the shell's cwd is. Two places the shell can
    be, env unset: inside ANOTHER onboarded project (the line used to land there and the answer said `journal: true`), and above the
    marker (the line used to be lost). Both end with the line in the story's journal and none in the other project."""
    story.clear_journal()
    other = temp_project("qa-other-")
    env_before = os.environ.get("CLAUDE_PROJECT_DIR")
    words = "approve\ndeliver with known gaps: " + REASON + "\n"
    try:
        with in_cwd(other):
            code, answer = story.decide(words, "--drafts", "d-1", project_env=False)
        check_eq("f1 cwd in another project, env unset: the decision records and the journal line is written",
                 (code, answer.get("recorded"), answer.get("risks")), (0, True, {"recorded": True, "journal": True}))
        check_eq("f1 ... the line is in the STORY's journal", [row["reason"] for row in story.risk_lines()], [REASON])
        check_eq("f1 ... and the other project's journal does not exist", RP.record(other, "journal.jsonl").is_file(), False)
        check_eq("f1 ... the guard opens the MR command of the story", story.mr()[0], SG.ALLOW)
        story.clear_journal()
        with in_cwd(story.root.parent):
            code, answer = story.decide(words, "--drafts", "d-1", project_env=False)
        check_eq("f1 cwd above the marker, env unset: the line is written all the same",
                 (code, answer.get("risks"), [row["reason"] for row in story.risk_lines()]),
                 (0, {"recorded": True, "journal": True}, [REASON]))
        check_eq("f1 ... the process env is as it was after the call (the pin lasts one call)", os.environ.get("CLAUDE_PROJECT_DIR"), env_before)
    finally:
        cleanup(other)
    # F-9: the file flag a refusal names is the one the caller took (log_append.py --reason-file, the same reader)
    empty = story.words(" \n")
    run = subprocess.run([sys.executable, "-B", str(SCRIPTS / "log_append.py"), "--event", "deliver_with_risks", "--task", TICKET,
                          "--reason-file", str(empty)], capture_output=True, text=True, timeout=60)
    check_eq("f9 log_append.py with an empty --reason-file: refused", run.returncode, 1)
    check("f9 ... and the refusal names --reason-file, not --words-file", "--reason-file" in run.stderr and "--words-file" not in run.stderr)


def h5_the_edges(story: Story) -> None:
    """h5: E1, E2, E3, E4, E5 at and beyond their boundaries."""
    story.clear_journal()
    for label, text, want in (("a token with no reason", "approve\ndeliver with known gaps\n", "carries no reason"),
                              ("a token with a blank reason", "approve\ndeliver with known gaps:   \n", "carries no reason")):
        code, refused = story.decide(text, "--drafts", "d-1")
        check_eq(f"h5 E1 {label}: refused, nothing recorded", (code, story.risk_lines()), (2, []))
        check_in(f"h5 E1 {label}: the refusal says ask once", want, refused["stderr"])
    blank = story.words(" \n")
    code, refused = story.decide("approve\n", "--drafts", "d-1", "--risks-file", str(blank))
    check_eq("h5 E1 a blank --risks-file is refused by the one words reader", code, 2)
    check("h5 E1/F-9 ... and the refusal names --risks-file, not --words-file",
          "--risks-file" in refused["stderr"] and "--words-file" not in refused["stderr"])
    check_eq("h5 E1 beyond: a one-character reason is recorded",
             story.decide("approve\ndeliver with known gaps: x\n", "--drafts", "d-1")[1].get("risks"), {"recorded": True, "journal": True})
    check_eq("h5 E1 ... whole", [row["reason"] for row in story.risk_lines()], ["x"])
    c = story.controller     # E2 and E3 are the builder's own refusals: gate A needs a gate A story, the builder is the seam
    for mr in ("do_not_open", "not_offered"):
        problem = None
        try:
            c.build_gate_decision("B", "w", [], None, mr, "x")
        except ValueError as exc:
            problem = str(exc)
        check_in(f"h5 E3 --mr {mr} with a reason: refused, both doors named", "Drop the risks", problem or "")
        check_in("h5 E3 ... and --mr open", "--mr open", problem or "")
    check("h5 E3 beyond: --mr open and the default (no --mr) with a reason build the field",
          all(c.build_gate_decision("B", "w", [], None, mr, "x").get("deliver_with_risks") == {"reason": "x"} for mr in ("open", None)))
    try:
        c.build_gate_decision("A", "w", [], None, None, "x")
        refused_at_a = ""
    except ValueError as exc:
        refused_at_a = str(exc)
    check_in("h5 E2 gate A with a reason: refused, the door is to leave the flag out", "leave --risks-file out", refused_at_a)
    flag = story.words("from the flag\n")
    code, answer = story.decide("approve\ndeliver with known gaps: from the words\n", "--drafts", "d-1", "--risks-file", str(flag))
    check_eq("h5 E4 flag and token that differ: the flag wins and the answer says so",
             (code, [row["reason"] for row in story.risk_lines()][-1], "was not used" in (answer.get("risks") or {}).get("line", "")),
             (0, "from the flag", True))
    story.clear_journal()
    code, answer = story.decide("approve\ndeliver with known gaps: a\ndeliver with known gaps: b\n", "--drafts", "d-1")
    check_eq("h5 E5 two tokens with different reasons: the decision records, no risk, no line, the answer says why",
             (code, answer.get("recorded"), story.risk_lines(), (answer.get("risks") or {}).get("recorded")), (0, True, [], False))
    check_in("h5 E5 ... in words", "different reasons", (answer.get("risks") or {}).get("line", ""))
    long_reason = "r" * 20000
    story.clear_journal()
    story.decide("approve\n", "--drafts", "d-1", "--risks-file", str(story.words(long_reason)))
    check_eq("h5 E6 a 20 000 character reason is recorded whole, in the journal and the field",
             ([len(row["reason"]) for row in story.risk_lines()], len(story.pipeline()["gates"]["B"]["deliver_with_risks"]["reason"])),
             ([20000], 20000))


def h6_the_refusal(story: Story) -> None:
    """h6: gate B recorded with no decision -> text 2; h6b the door opens with a two-line reason through a file; h7 the crash shape."""
    story.clear_journal()
    story.decide("approve\n", "--drafts", "d-1", "--mr", "open")
    code, said = story.mr()
    check_eq("h6 gate B recorded, no risk, no line: DENY", code, SG.DENY)
    for needle in ("Gate B is recorded, and it records no decision to deliver with known gaps", "log_append.py --event deliver_with_risks --task "
                   + TICKET + " --reason-file", "as its own call", SENTENCE, "A new gate B decision is not the way", "a requirement has no outcome"):
        check_in(f"h6 the text holds `{needle[:50]}`", needle, said)
    check_not_in("h6 ... and does not ask the person to say it at gate B again", "have the human say", said)
    reason = story.task / "state" / "words" / "reason-two-lines.txt"
    reason.write_bytes(("first line \"quoted\"\nsecond line\n").encode("utf-8"))
    ran = subprocess.run([sys.executable, "-B", str(SCRIPTS / "log_append.py"), "--event", "deliver_with_risks", "--task", TICKET,
                          "--reason-file", str(reason)], capture_output=True, text=True, cwd=str(story.root),
                         env=dict(os.environ, CLAUDE_PROJECT_DIR=str(story.root), PYTHONDONTWRITEBYTECODE="1"))
    check_eq("h6b the door the text names opens: log_append --reason-file exits 0 " + (ran.stdout + ran.stderr)[-200:], ran.returncode, 0)
    check_eq("h6b ... the reason stands whole, two lines and the quote", [row["reason"] for row in story.risk_lines()],
             ["first line \"quoted\"\nsecond line\n"])
    check_eq("h6b ... and the guard ALLOWs", story.mr()[0], SG.ALLOW)
    both = subprocess.run([sys.executable, "-B", str(SCRIPTS / "log_append.py"), "--event", "deliver_with_risks", "--task", TICKET,
                           "--reason", "x", "--reason-file", str(reason)], capture_output=True, text=True, cwd=str(story.root),
                          env=dict(os.environ, CLAUDE_PROJECT_DIR=str(story.root)))
    check_eq("h6b both options at once are refused, nothing written", (both.returncode, len(story.risk_lines())), (1, 1))
    # h7: the decision stands with the field and the line is missing (a crash between the two)
    story.clear_journal()
    story.decide("approve\n", "--drafts", "d-1", "--mr", "open", "--risks-file", str(story.words(REASON)))
    story.clear_journal()
    code, said = story.mr()
    check_eq("h7 the crash shape (field recorded, no line): DENY", code, SG.DENY)
    for needle in ("with the person's decision to deliver with known gaps (reason: " + REASON + ")", "has no deliver_with_risks line", "--reason-file",
                   "as its own call", SENTENCE):
        check_in(f"h7 the text holds `{needle[:50]}`", needle, said)
    check_eq("h7 beyond the cut: a reason over the shown limit is cut with the cut named",
             "cut here" in SG.rule_delivery(TICKET, "x", None, None, {"gates": {"B": {"status": "approved", "deliver_with_risks": {"reason": "z" * 5000}}}}),
             True)


def h8_damaged_records() -> None:
    """h8 (E8, E9): `gate_risk_reason` reads "" for every shape that is no approved decision with a text reason; the guard then claims no decision."""
    approved = {"status": "approved", "decision": "approved"}
    for label, pipeline in (("None", None), ("a list", []), ("no gates", {}), ("gates a string", {"gates": "B"}), ("no B", {"gates": {}}),
                            ("B a string", {"gates": {"B": "approved"}}), ("declined", {"gates": {"B": {"status": "declined", "deliver_with_risks": {"reason": "x"}}}}),
                            ("deferred", {"gates": {"B": {"status": "deferred", "deliver_with_risks": {"reason": "x"}}}}),
                            ("field a string", {"gates": {"B": dict(approved, deliver_with_risks="x")}}),
                            ("field null", {"gates": {"B": dict(approved, deliver_with_risks=None)}}),
                            ("reason blank", {"gates": {"B": dict(approved, deliver_with_risks={"reason": "  "})}}),
                            ("reason a number", {"gates": {"B": dict(approved, deliver_with_risks={"reason": 7})}})):
        check_eq(f"h8 {label}: no decision", C.gate_risk_reason(pipeline), "")
    check_eq("h8 control: an approved record with a reason reads it", C.gate_risk_reason({"gates": {"B": dict(approved, deliver_with_risks={"reason": "x"})}}), "x")
    # E8: with no pipeline handed over the sentence is today's, and says nothing about a decision
    said = SG.rule_delivery("QA-3", "this delivery command", None, ("glab mr create", "x")) or ""
    check_in("h8 E8 no pipeline: today's sentence", "have the human say 'deliver with known gaps'", said)
    for label, pipeline in (("no gate B", {"stages": {"S8": {"status": "done"}}}), ("declined", {"stages": {"S8": {"status": "done"}}, "gates": {"B": {"status": "declined"}}})):
        said = SG.rule_delivery("QA-3", "x", None, ("glab mr create", "x"), pipeline) or ""
        check_in(f"h8 {label}: today's sentence, no claim of a decision", "have the human say 'deliver with known gaps'", said)
        check_not_in(f"h8 {label}: ... and none of the new ones", "log_append.py", said)


def h10_a_later_decision_and_the_old_story(story: Story) -> None:
    """h10 (E11, E23): the later decision without risks drops the field and the line stays (R1); a record of an older version reads as no risk."""
    story.clear_journal()
    story.decide("approve\n", "--drafts", "d-1", "--mr", "open", "--risks-file", str(story.words(REASON)))
    story.decide("approve\n", "--drafts", "d-1", "--mr", "open")
    check_eq("h10 E11 the later decision without risks: the field is gone (latest wins)",
             "deliver_with_risks" in story.pipeline()["gates"]["B"], False)
    check_eq("h10 E11 ... the journal line stays and still opens the MR command (named residual R1)",
             (len(story.risk_lines()), story.mr()[0]), (1, SG.ALLOW))
    story.clear_journal()
    old = copy.deepcopy(story.pipeline())
    old["gates"]["B"].pop("deliver_with_risks", None)
    check_eq("h10 E23 an old record (no field): no risk, and a hand-written line still passes",
             (C.gate_risk_reason(old), story.mr()[0]), ("", SG.DENY))
    story.journal_path().parent.mkdir(parents=True, exist_ok=True)
    story.journal_path().write_text(json.dumps({"event": "deliver_with_risks", "task": TICKET, "reason": "by hand"}) + "\n", encoding="utf-8")
    check_eq("h10 E23 ... the hand-written line passes", story.mr()[0], SG.ALLOW)


def h11_a_reader_prints_the_reason() -> None:
    """h11 (AR-22): the declared readers of the field find it where the controller writes it."""
    check_eq("h11 the controller's decision projection carries the request's key whole",
             CTL.gate_b_record({"decisions": {}}, {"status": "approved", "gate": "B", "deliver_with_risks": {"reason": "x"}})["deliver_with_risks"],
             {"reason": "x"})
    # the reader side: the retro's gate lines print the reason of the record the controller wrote
    record = CTL.gate_b_record({"decisions": {}}, {"status": "approved", "gate": "B", "deliver_with_risks": {"reason": REASON}})
    import retro_numbers as RN  # noqa: E402
    check_in("h11 the retro reads deliver_with_risks where the controller writes it", f"Gate B: delivered with known gaps — {REASON}",
             RN.gate_answers({"gates": {"B": record}}))


def h12_registry_and_text() -> None:
    """h12 plus the sentences (key presence with a negative control, quoted before the run)."""
    keys = {
        "skills/qa-story/phases/s8.md": ("--risks-file", "log_append.py", "--reason-file", "--mr open"),
        "references/conductor.md": ("deliver_with_risks", "--reason-file"),    # never `gate-decision`: the conductor records no gate (test_conductor_doors I6)
        "handoffs/gate-b-to-delivery.yaml": ("gate-decision", "--risks-file"),
    }
    package = SCRIPTS.parent
    for name, needles in keys.items():
        text = (package / name).read_text(encoding="utf-8")
        for needle in needles:
            check_in(f"h12 {name} holds `{needle}`", needle, text)
    check_not_in("h12 s8.md no longer says the guard reads the controller receipt", "stage_guard` reads the controller receipt",
                 (package / "skills/qa-story/phases/s8.md").read_text(encoding="utf-8"))
    import gate_brief
    check_in("h12 the packet's one sentence: approval word first, then the line of its own", "`approve` on the first line of your answer, then, on a line of its own, "
             "`deliver with known gaps: <your reason>`", gate_brief.risk_form())
    check("h12 conductor.md stays under its cap", len((package / "references/conductor.md").read_bytes()) <= 12000)


# --- N2 (DC1-19): one executor of a person's words at a gate, for the conductor and the driver alike (keys d1..d15) --------------------
# The story is the recorded run of 12586 cut before its gate A decision (`fixtures/run-12586-manual`), with a register of three questions
# (Q10-Q12) and plan rows that branch on them added by the test; every call is the real `controller.main`.

import test_gate_decision_manual_pass as MP  # noqa: E402
import planning_contract as PC  # noqa: E402
from event_store import content_hash  # noqa: E402


def register_row(qid: str) -> dict:
    return {"id": qid, "question": f"Which reading of {qid}?", "readings": [{"reading": "the first"}, {"reading": "the second"}],
            "severity": "minor", "owner_role": "qa-test-strategist", "source_says": "the ticket is silent"}


def run_controller(root: Path, argv_tail: list, project_env: bool = True) -> tuple:
    """`controller.py <argv_tail>` in-process: (exit code, stdout JSON or {}, stderr's last JSON line or {"stderr": text})."""
    out, err, code = io.StringIO(), io.StringIO(), 0
    old_argv, old_env = sys.argv, os.environ.get("CLAUDE_PROJECT_DIR")
    sys.argv = ["controller.py", *argv_tail]
    if project_env:
        os.environ["CLAUDE_PROJECT_DIR"] = str(root)
    else:
        os.environ.pop("CLAUDE_PROJECT_DIR", None)
    import hooklib
    hooklib._PROJECT_ROOT_CACHE = None      # hooklib caches the project root per process: an earlier case's root must not answer for this one (d5b)
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                CTL.main()
            except SystemExit as exc:
                code = exc.code if isinstance(exc.code, int) else 1
            except ValueError as exc:
                code = 2
                print(str(exc), file=sys.stderr)
    finally:
        sys.argv = old_argv
        if old_env is None:
            os.environ.pop("CLAUDE_PROJECT_DIR", None)
        else:
            os.environ["CLAUDE_PROJECT_DIR"] = old_env
        hooklib._PROJECT_ROOT_CACHE = None
    text, lines =out.getvalue().strip(), [x for x in err.getvalue().splitlines() if x.strip()]
    last = lines[-1] if lines else ""
    return code, brief_aware(text, argv_tail), (json.loads(last) if last.startswith("{") else {"stderr": err.getvalue()})


def brief_aware(text: str, argv_tail: list) -> dict:
    """The answer of a call as a dict. Whole JSON as printed; with `--brief` and an answer over the limit, stdout is SUMMARY LINES
    (`key: <json>`) ending in `full result: <path> (<n> bytes)` - the whole result is then read from `state/output/controller-<operation>.json`
    (the file the summary names), and the summary's own `key: value` lines must agree with it (a door's reader sees what the file holds)."""
    if text.startswith("{"):
        return json.loads(text)
    lines = text.splitlines()
    if not lines or not lines[-1].startswith("full result: "):
        return {}
    task_root = argv_tail[argv_tail.index("--task-root") + 1]
    whole = json.loads((Path(task_root) / "state" / "output" / f"controller-{argv_tail[argv_tail.index('--operation') + 1]}.json").read_text(encoding="utf-8"))
    for line in lines[:-1]:
        key, _, value = line.partition(": ")
        if key in whole and value.startswith(("true", "false", '"')):
            assert json.loads(value) == whole[key], f"summary line `{key}` differs from the full result"
    return whole


class GateA:
    """A throwaway project at gate A: the recorded run, a register (Q10-Q12), TS-1 branching on Q10, TS-2 on Q11 (no branch for `b`), a plan table."""

    def __init__(self) -> None:
        self.root = temp_project("qa-gate-a-words-")
        self.task = MP.story(self.root)
        (self.task / "work" / "requirements-readiness.json").write_text(
            json.dumps({"verdict": "ok", "open_questions": [register_row(q) for q in ("Q10", "Q11", "Q12")]}), encoding="utf-8")
        plan = MP.plan_of(self.task)
        rows = {r["id"]: r for r in plan["rows"]}
        rows["TS-1"]["question_refs"] = ["Q10"]
        rows["TS-1"]["if_answered"] = {"Q10": {"a": {"reason": "Q10 a: the first reading holds."}, "b": {"reason": "Q10 b: the second reading holds."},
                                              "not_needed": {}}}
        rows["TS-2"]["question_refs"] = ["Q11"]
        rows["TS-2"]["if_answered"] = {"Q11": {"a": {"reason": "Q11 a: the first reading holds."}}}
        self.plan_path = self.task / "work" / "test-plan.json"
        self.plan_path.write_text(json.dumps(plan, indent=1), encoding="utf-8")
        self.md_path = C.artifact(self.task, "test-plan.md")
        self.md_path.write_text(f"{C.PLAN_HEADING}\n\n| ts | disposition + reason | level | fit |\n|---|---|---|---|\n"
                                f"| TS-1 | `automate` - Input 1: x | `api` | new |\n", encoding="utf-8")
        self.seq = 0
        self.base_events = 0
        self.base_events = self.manifest_events()

    def words(self, text: str) -> Path:
        self.seq += 1
        return GB.words_file(self.task, f"gateA-{self.seq}.txt", text)

    def call(self, words: str, *extra, gate: str = "A", as_is: bool = True, project_env: bool = True) -> tuple:
        return run_controller(self.root, ["--task-root", str(self.task), "--operation", "gate-decision", "--gate", gate,
                                          *(["--as-is"] if as_is and gate == "A" else []), "--words-file", str(self.words(words)), *extra], project_env)

    def row(self, rid: str = "TS-1") -> dict:
        return {r["id"]: r for r in MP.plan_of(self.task)["rows"]}[rid]

    def lines(self, kind: str = "") -> list:
        path = self.task / "work" / "question-answers.jsonl"
        rows = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()] if path.is_file() else []
        return [r for r in rows if r.get("id") in ("Q10", "Q11", "Q12") or r.get("kind") == PC.ANSWERS_APPLIED and r.get("id") in ("Q10", "Q11", "Q12")
                ] if not kind else [r for r in rows if r.get("kind", "question") == kind and r.get("id") in ("Q10", "Q11", "Q12")]

    def three(self) -> dict:
        return {p.name: (p.read_bytes() if p.is_file() else None) for p in CTL._story_file_paths(self.task)}

    def manifest_events(self) -> int:
        """The `manifest` events added to the journal since the story was copied (the recorded run holds its own)."""
        path = self.task / "state" / "events.jsonl"
        return (sum("manifest" in x for x in path.read_text(encoding="utf-8").splitlines()) if path.is_file() else 0) - self.base_events

    def unresolved(self) -> list:
        path = self.task / "work" / "automation-manifest.json"
        return [u.get("case") for u in json.loads(path.read_text(encoding="utf-8")).get("unresolved") or []] if path.is_file() else []


def refuse_once(g: GateA, words: str, *extra) -> tuple:
    """The call refused by a synthetic factory problem (as the manual-pass test does), the real check put back after."""
    real = CTL.Controller.check_decision
    CTL.Controller.check_decision = lambda self, payload: ["synthetic factory problem"]
    try:
        return g.call(words, *extra)
    finally:
        CTL.Controller.check_decision = real


def d1_d2_d3_d6_a_line_is_recorded_and_applied() -> None:
    g = GateA()
    try:
        code, out, _ = g.call("approve as is\nQ10: a\n")
        check_eq("d1/d2 a `Q10: a` line at gate A with `approve as is` records the decision", (code, out.get("recorded")), (0, True))
        check_eq("d1 the answer says what it recorded", out["questions"]["recorded"], ["Q10: a"])
        check_eq("d1 one register record: Q10 answered `a` at gate A, by the conductor",
                 [(r["id"], r["status"], r.get("reading"), r["where"], r["by"]) for r in g.lines("question")], [("Q10", "answered", "a", "gate A", "conductor")])
        check_eq("d1 the row followed the answer and Q10 left it", (g.row()["reason"], "if_answered" in g.row(), "question_refs" in g.row()),
                 ("Q10 a: the first reading holds.", False, False))
        check_in("d1 the plan.md cell moved with the json", "Q10 a: the first reading holds.", g.md_path.read_text(encoding="utf-8"))
        check_eq("d6 the decision binds the PATCHED plan (the hash is of the file as it stands)",
                 out["decision"]["payload"]["plan_content_hash"], content_hash(MP.plan_of(g.task)))
        check_eq("d6 and the approval is current", MP.gate_a_is_current(g.root, g.task)[0], True)
        for _n in range(2):
            code, again, _ = g.call("approve as is\nQ10: a\n")
        check_eq("d3 three calls with the same words: one question record, one answers_applied", (len(g.lines("question")), len(g.lines(PC.ANSWERS_APPLIED))), (1, 1))
        check_eq("d3 and the repeat names it `already`, not `recorded`", (again["questions"]["recorded"], again["questions"]["already"]), ([], ["Q10: a"]))
    finally:
        cleanup(g.root)


def d4_d5_d5c_a_refused_call_records_the_words_and_leaves_the_files() -> None:
    g = GateA()
    try:
        before = g.three()
        code, _, refusal = refuse_once(g, "approve as is\nQ10: b\n")
        check_eq("d4 a refused call exits 2", code, 2)
        after = g.three()
        check_eq("d5 the plan json and the plan md are byte for byte", {k: after[k] for k in ("test-plan.json", "test-plan.md")},
                 {k: before[k] for k in ("test-plan.json", "test-plan.md")})
        check_eq("d5 the printed refusal lists what it recorded (B4)", refusal["questions"]["recorded"], ["Q10: b"])
        check_eq("d5 the register holds the answer and NO answers_applied record (the plan is not hashed behind it)",
                 (len(g.lines("question")), len(g.lines(PC.ANSWERS_APPLIED))), (1, 0))
        code, out, _ = g.call("approve as is\n")
        check_eq("d4 the retry with NO tokens records", (code, out.get("recorded")), (0, True))
        check_eq("d4 and the plan follows the answer given at the refused call (the 14857 sequence)", g.row()["reason"], "Q10 b: the second reading holds.")
        check_eq("d4/d6 the recorded hash is the hash of that plan", out["decision"]["payload"]["plan_content_hash"], content_hash(MP.plan_of(g.task)))
        check_eq("d4 one applied record, written at the recording call", len(g.lines(PC.ANSWERS_APPLIED)), 1)
        told = " | ".join(refusal["questions"]["lines"])
        check_not_in("d5/F-2 a refused call does not tell plan moves it rolled back", "updated", told)
        check_in("d5/F-2 ... they stand as `lines_if_recorded`", "updated", " | ".join(refusal["questions"]["lines_if_recorded"]))
        # d5c: over a standing approval, a refused call records Q12 only; the next recording call says it did not change the plan
        gate_before = g.three()
        code, _, _ = refuse_once(g, "approve as is\nQ12: a\n")
        check_eq("d5 over a standing approval the refused call leaves the plan as approved", g.three()["test-plan.json"], gate_before["test-plan.json"])
        check_eq("d5 and the approval is still current", MP.gate_a_is_current(g.root, g.task)[0], True)
        code, out, _ = g.call("approve as is\n")
        said = " | ".join(out["questions"]["lines"])
        check_in("d5c the retry over a standing approval names the answer it did not apply (R5)", "already approved the test plan at gate A", said)
    finally:
        cleanup(g.root)


def d4b_d4c_an_answer_the_plan_has_no_branch_for_is_owed_not_dropped() -> None:
    g = GateA()
    try:
        code, _, refusal = refuse_once(g, "approve as is\nQ11: b\n")
        code, out, _ = g.call("approve as is\n")
        rework = out["questions"]["rework"]
        check_eq("d4b the row with no branch for `b` is named for the strategist, not merely not refused",
                 [(r["owner"], r["where"], r["question"], r["answer"]) for r in rework], [("strategist", "TS-2", "Q11", "b")])
        check_eq("d4b `approve as is` passes over it (F-8 a): recorded, and the rework stays in the answer", (code, out["recorded"]), (0, True))
        check_in("d4b/F-4 the recorded answer carries the rework's door", "--operation rework --stage S3 --role qa-test-strategist --rows TS-2",
                 out["questions"].get("rework_left", ""))
        import report_facts as RF
        check_in("d4b/F-4 the report's Left with you holds the owed rework", "TS-2", RF._owed_rework_gap(g.task))
        check_eq("d4b/F-4 control: a story with no owed rework gets no such line", RF._owed_rework_gap(Path(g.root)), "")
        # AR-9: the door the sentence names is OPENED, not only read (the placeholder `<file>` filled with the person's words)
        door = next((x for x in re.findall(r"`([^`]+)`", out["questions"]["rework_left"]) if "--operation rework" in x), "")
        check("d4b/AR-9 the sentence holds a door command", door.startswith("controller.py --task-root ") and "<file>" in door)
        # AR-25: the door is a rework answering a question - `question_answer` spends none of the repair cap (a person's answer is not a defect of the
        # test); and a repair-loop role outside every REPAIR_PAIR (the S3 strategist) is its own pair, so the cap refusal never meets a KeyError
        check_in("d4b/AR-25 the door classes the round as the answer to a question", "--cause question_answer", door)
        import controller as CTL
        check_eq("d4b/AR-25 edge: a loop role outside every pair has a pass of its own (was an empty answer, a KeyError at the cap)",
                 list(CTL.repair_passes({}, {"stage": "S3", "role": "qa-test-strategist"})), ["qa-test-strategist"])
        opened = door.replace("<file>", str(g.words("the strategist reworks TS-2 for Q11: b\n"))).split()[1:]
        code, answer, refusal = run_controller(g.root, opened)
        check_eq("d4b/AR-9 the door opens: the rework is dispatched for the strategist at S3 (no refusal, no unknown flag)",
                 (code, answer.get("dispatched"), (answer.get("request") or {}).get("stage"), (answer.get("request") or {}).get("role"), refusal.get("stderr", "")),
                 (0, True, "S3", "qa-test-strategist", ""))
    finally:
        cleanup(g.root)
    g = GateA()
    try:
        refuse_once(g, "Q11: b\n")
        first = g.call("approve\n", as_is=False)
        second = g.call("approve\n", as_is=False)
        for label, (code, _out, err) in (("first", first), ("second", second)):
            check_eq(f"d4c own words, {label} call: not recorded", code, 2)
            check_eq(f"d4c {label} call names the rework again (E27)", [r["where"] for r in err["questions"]["rework"]], ["TS-2"])
            check_in(f"d4c {label} call: the sentence holds the rework door", "--operation rework --stage S3 --role qa-test-strategist --rows TS-2",
                     " ".join(err["problems"]))
    finally:
        cleanup(g.root)


def d5_d5b_nothing_moves_without_a_record() -> None:
    g = GateA()
    try:
        before = g.three()
        code, built, _ = g.call("approve as is\nQ10: a\nTC-001: accept as blocked\n", "--build-only")
        check_eq("d5/E14 --build-only exits 0 and records nothing", (code, built.get("recorded")), (0, False))
        check_eq("d5/E14 the three files are byte for byte", g.three(), before)
        check_eq("d5b/E14 no manifest event, no manifest", (g.manifest_events(), g.unresolved()), (0, []))
        code, _, _ = refuse_once(g, "approve as is\nQ10: a\nTC-001: accept as blocked\n")
        check_eq("d5b a refused call over an `accept as blocked` token: no manifest event, no blocked case", (code, g.manifest_events(), g.unresolved()), (2, 0, []))
        check_eq("d5b ... and it names the token it did not apply (R4)", run_controller_refusal_not_applied(g), ["TC-001: accept as blocked"])
        remedy ={"kind": "reporter", "where": "qa-factory/config.json:profiles[web].commands.one_test", "change": "name the flag"}
        code, out, _ = g.call("approve as is\nQ10: a\nTC-001: accept as blocked\n",
                              "--remedies-file", str(GB.words_file(g.task, "remedies.json", json.dumps({"TC-001": remedy}))))
        check_eq("d5b the recording call puts the blocked case in the manifest (E22 world: it works), and the plan hash is the file's "
                 + " | ".join(out["questions"]["lines"])[-600:],
                 (code, g.unresolved(), out["decision"]["payload"]["plan_content_hash"] == content_hash(MP.plan_of(g.task))),
                 (0, ["TC-001"], True))
        check_eq("d5/E14 the preview's plan hash is the hash recording binds", built["request"]["plan_content_hash"], out["decision"]["payload"]["plan_content_hash"])
    finally:
        cleanup(g.root)


def d5_e15_an_exception_leaves_the_files_and_the_journal() -> None:
    g = GateA()
    real = CTL.Controller.check_decision
    CTL.Controller.check_decision = lambda self, payload: (_ for _ in ()).throw(RuntimeError("boom"))
    try:
        snap = g.three()
        try:
            g.call("approve as is\nQ10: a\nTC-001: accept as blocked\n")
        except RuntimeError:
            pass
        check_eq("d5/E15 an exception: the three files restored, nothing recorded, no manifest event", (g.three(), g.manifest_events()), (snap, 0))
    finally:
        CTL.Controller.check_decision = real
        cleanup(g.root)


def run_controller_refusal_not_applied(g: GateA) -> list:
    code, _, err = refuse_once(g, "approve as is\nTC-001: accept as blocked\n")
    return err["questions"]["not_applied_yet"]


def d7_d8_d9_d11_gate_b_and_the_flags() -> None:
    story = Story()
    try:
        (story.task / "work" / "requirements-readiness.json").write_text(
            json.dumps({"verdict": "ok", "open_questions": [register_row(q) for q in ("Q10", "Q11", "Q12")]}), encoding="utf-8")
        plan_path = story.task / "work" / "test-plan.json"
        row = {"id": "TS-1", "disposition": "automate", "question_refs": ["Q10"], "if_answered": {"Q10": {"a": {"reason": "x"}}}}
        plan_path.parent.mkdir(parents=True, exist_ok=True)
        plan_path.write_text(json.dumps({"rows": [row]}), encoding="utf-8")
        was = plan_path.read_bytes()
        code, out = story.decide("approve\nQ10: a\n", "--drafts", "d-1", "--mr", "open")
        check_eq("d7 gate B `Q10: a` on a line: recorded", (code, out["questions"]["recorded"]), (0, ["Q10: a"]))
        records = [json.loads(x) for x in (story.task / "work" / "question-answers.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
        check_eq("d7 the register says gate B", [(r["id"], r["where"]) for r in records if r.get("id") == "Q10" and r.get("kind", "question") == "question"], [("Q10", "gate B")])
        check_eq("d7 and the plan is byte for byte (no plan is read or written at gate B)", plan_path.read_bytes(), was)
        check_eq("d7b the rows that still branch on the answer are listed (a recorded letter is not a carried-out one)",
                 out["questions"]["plan_not_changed"], [{"id": "Q10", "rows": ["TS-1"]}])
        code, again = story.decide("approve\nQ10: a\n", "--drafts", "d-1", "--mr", "open")
        check_eq("d7b/F-5 the retry of the same words (`already`, nothing new recorded) still lists the rows that branch on it",
                 (again["questions"]["recorded"], again["questions"]["already"], again["questions"]["plan_not_changed"]),
                 ([], ["Q10: a"], [{"id": "Q10", "rows": ["TS-1"]}]))
        code, out = story.decide("approve\nQ10: a Q11: a\n", "--drafts", "d-1", "--mr", "open")
        unread = out["questions"]["unread"]
        check_eq("d8/E18 `Q10: a Q11: a` is unread, with the form to use; the decision is recorded all the same", (code, out["recorded"], len(unread), unread[0]["id"]),
                 (0, True, 1, "Q10"))
        check_in("d8 and the line says each answer goes on a line of its own", "each answer goes on a line of its own", unread[0]["why"])
        code, out = story.decide("approve\nQ10: b\n", "--drafts", "d-1", "--mr", "open")
        check_eq("d9/E17 a different answer on a settled id: unread with the `--reopen` door, the decision recorded",
                 (code, out["recorded"], out["questions"]["recorded"]), (0, True, []))
        check_in("d9 the door is named", "--reopen Q10", out["questions"]["unread"][0]["why"])
        # d11/E21: a missing flag file is a refusal naming the flag, before any write
        before = (story.task / "work" / "question-answers.jsonl").read_bytes()
        code, _ = story.decide("approve\nQ11: a\n", "--shown-file", str(story.task / "state" / "no-such.json"))
        check_eq("d11/E21 a missing --shown-file is refused, naming the flag; nothing was recorded",
                 (code, (story.task / "work" / "question-answers.jsonl").read_bytes() == before), (2, True))
        code, _ = story.decide("approve\nQ11: a\n", "--no-answers", "--answers-file", str(story.words("Q11: a")))
        check_eq("d11/E21 --no-answers with --answers-file is refused", code, 2)
        code, out = story.decide("approve\nQ11: a\n", "--no-answers", "--drafts", "d-1", "--mr", "open")
        check_eq("d11/M14 --no-answers records no answer, and the answer says the token was not recorded",
                 (code, out["questions"]["recorded"], [u["line"] for u in out["questions"]["unread"]],
                  (story.task / "work" / "question-answers.jsonl").read_bytes() == before), (0, [], ["Q11: a"], True))
    finally:
        cleanup(story.root)


def d12_d13_the_view_reads_the_answer_without_its_tail_and_never_hides_an_unknown() -> None:
    g = GateA()
    try:
        QR.record(g.task, "Q10", "answered", "Q10: b", "gate A", "driver", QR.load(g.task)["questions"][0]["row_hash"], reading="b")
        before = QR.load(g.task)
        view = QR.gate_words_view(g.task, "Q10: b\n", before)
        check_eq("d12/F1 the answer's own lines: `Q10: b` again is `already`, nothing unread", (view["already"], view["unread"]), (["Q10: b"], []))
        whole = "Q10: a\n\nEarlier answer at this gate:\nQ10: b\n"
        check_eq("d12/F1 control: the whole words WITH the tail read as two answers (why the driver hands the new lines alone)",
                 [u["why"] for u in QR.gate_words_view(g.task, whole, before)["unread"]], ["two different answers for it; none was recorded"])
        (g.task / "work" / "requirements-readiness.json").write_text("{not json", encoding="utf-8")
        check_eq("d13 an unreadable register is `unknown`, never three empty lists", list(QR.gate_words_view(g.task, "Q10: a", None)), ["unknown"])
        (g.task / "work" / "requirements-readiness.json").unlink()
        check_eq("d13 no register, no token: the four empty lists", QR.gate_words_view(g.task, "approve\n", None),
                 {"recorded": [], "already": [], "unread": [], "named_not_recorded": []})
    finally:
        cleanup(g.root)


def d10_the_gate_b_list_no_longer_holds_a_question_answered_at_gate_a() -> None:
    """d10: the list gate B and the MR section read (`gate_brief.unanswered_questions`) is the register's: what a gate A line settled is gone
    from it, what no line settled stays, and nobody is told "the factory recorded no answer" for a question that has one."""
    import gate_brief
    g = GateA()
    try:
        ids = lambda: [q["id"] for q in gate_brief.unanswered_questions(g.task)]
        check_eq("d10 control: before the words all three questions are listed", ids(), ["Q10", "Q11", "Q12"])
        g.call("approve as is\nQ10: a\n")
        check_eq("d10 after `Q10: a` at gate A the list holds the two questions no line settled", ids(), ["Q11", "Q12"])
        notes = " | ".join(str(q.get("status_note") or "") for q in gate_brief.unanswered_questions(g.task))
        check_not_in("d10 and nothing says the factory recorded no answer", "recorded no answer", notes)
        code, _, _ = g.call("approve as is\nQ11: a Q12: a\n")
        check_eq("d10 control: a line the register cannot read settles nothing, the question stays listed (toward asking)", ids(), ["Q11", "Q12"])
    finally:
        cleanup(g.root)


def d14_both_roads_leave_the_same_plan() -> None:
    a, b = GateA(), GateA()
    try:
        a.call("approve as is\nQ10: a\n")
        b.call("approve as is\nQ10: a\n", "--answers-by", "driver", "--answers-file", str(b.words("approve as is\nQ10: a\n")))
        check_eq("d14 the conductor's road and the driver's flags end with one plan", MP.plan_of(a.task), MP.plan_of(b.task))
        check_eq("d14 ... and the driver's records say `driver`", [r["by"] for r in b.lines("question")], ["driver"])
    finally:
        cleanup(a.root)
        cleanup(b.root)


def real_driver(g: GateA, dry: bool = False):
    """The REAL `story_run.Driver` over the gate A project (its `py` runs the real `controller.py` in a child). The Driver chdirs into the
    project and sets `CLAUDE_PROJECT_DIR`; the caller puts both back (`driver_run`)."""
    import types
    import harness
    import story_run
    harness.remember_cwd()
    ns = types.SimpleNamespace(task="TP1-12586", answer=None, until="end", dry_run=dry, model="sonnet", plugin_dir=None, project=str(g.root),
                               mr=None, branch=None, commit=None, ungrounded=False, ticket_file=None, env=None, branch_suffix="", max_boundaries=10)
    return story_run.Driver(ns)


@contextlib.contextmanager
def driver_run():
    """The cwd and `CLAUDE_PROJECT_DIR` a Driver moves, given back; stdout captured (the driver prints its news): yields the buffer."""
    old_cwd, old_env, printed = os.getcwd(), os.environ.get("CLAUDE_PROJECT_DIR"), io.StringIO()
    try:
        with contextlib.redirect_stdout(printed):
            yield printed
    finally:
        os.chdir(old_cwd)
        if old_env is None:
            os.environ.pop("CLAUDE_PROJECT_DIR", None)
        else:
            os.environ["CLAUDE_PROJECT_DIR"] = old_env


def d16_the_real_driver_through_the_real_controller() -> None:
    """d16 (r0107 Q4, F-7, F-4): ONE key per seam with nothing faked between the driver and the controller. (a) `record_by_code` with the
    real `py` over gate A: `approve as is\\nQ10: a` and a stand token (`accept as blocked`, the remedy by file) end with the plan patched, a
    register record by `driver`, and the case in the manifest. (b) `--no-answers` under a dry run: the decision records, the register,
    the plan and the manifest are as they were. (c) F-4: a refused `Q11: b` queues the rework; a recorded `approve as is` over it does
    NOT leave the queued item (S3 does not open), prints the sentence with its door, and the report's Left with you holds the line."""
    remedy = {"kind": "reporter", "where": "qa-factory/config.json:profiles[web].commands.one_test", "change": "name the flag"}
    g = GateA()
    try:
        with driver_run() as printed:
            driver = real_driver(g)
            driver.state["stand_accept_cases"], driver.state["stand_accept_remedies"] = ["TC-001"], {"TC-001": remedy}
            recorded = driver.record_by_code("gate_A", "S4", "approve as is\nQ10: a\n", approved_by="option")
        check_eq("d16 (a) the real driver, the real controller: the decision records", recorded, True)
        check_eq("d16 (a) the plan follows the answer", g.row()["reason"], "Q10 a: the first reading holds.")
        check_eq("d16 (a) the register says `driver`", [(r["id"], r["by"]) for r in g.lines("question")], [("Q10", "driver")])
        check_eq("d16 (a) the accepted case is in the manifest (one event) and the driver's keys are consumed",
                 (g.unresolved(), g.manifest_events(), driver.state.get("stand_accept_cases"), driver.state.get("stand_accept_remedies")),
                 (["TC-001"], 1, None, None))
        check_eq("d16 (a) the approval is current on the patched plan", MP.gate_a_is_current(g.root, g.task)[0], True)
        check_in("d16 (a) the driver told the person what the plan did", "its plan entry is updated", printed.getvalue())
    finally:
        cleanup(g.root)
    g = GateA()
    try:
        before = g.row()
        with driver_run() as printed:
            driver = real_driver(g, dry=True)
            recorded = driver.record_by_code("gate_A", "S4", "approve as is\nQ10: a\n", approved_by="option")
        check_eq("d16 (b) F-7 a dry run records the decision", recorded, True)
        check_eq("d16 (b) ... and no answer: no register line, the row still branches on Q10 and keeps its reason",
                 (len(g.lines("question")), g.row()), (0, before))
    finally:
        cleanup(g.root)
    g = GateA()
    try:
        with driver_run() as printed:
            driver = real_driver(g)
            first = driver.record_by_code("gate_A", "S4", "approve\nQ11: b\n", approved_by="option")
            owed_first = driver.state.get("answer_rework")
            again = driver.record_by_code("gate_A", "S4", "approve\n", approved_by="option")
            queued = driver.state.get("answer_rework")
            second = driver.record_by_code("gate_A", "S4", "approve as is\n", approved_by="option")
            opened = driver.answer_rework_step()
        check_eq("d16 (c) F-4 the first `approve` (the answer `Q11: b` recorded alone: open items refuse it) is refused", (first, owed_first), (False, None))
        check_eq("d16 (c) ... the second `approve` is refused over the rework the plan now owes and the driver QUEUES it for the strategist",
                 (again, [(i.get("stage"), i.get("rows")) for i in (queued or {}).get("items") or []]), (False, [("S3", ["TS-2"])]))
        check_eq("d16 (c) then `approve as is` records", second, True)
        check_eq("d16 (c) ... the queued item is gone and S3 does not open (the person's word wins)", ("answer_rework" in driver.state, opened), (False, False))
        check_in("d16 (c) ... the driver printed the sentence with its door", "--operation rework --stage S3 --role qa-test-strategist --rows TS-2", printed.getvalue())
        import report_facts as RF
        check_in("d16 (c) ... and the report's Left with you holds the line", "TS-2", RF._owed_rework_gap(g.task))
    finally:
        cleanup(g.root)


def d11b_a_valid_shown_file_reaches_the_stored_hash() -> None:
    """d11b (t-435 F4, was K-SHOWN of test_story_run_gate_repair): a VALID `--shown-file` through a real `gate-decision` to the hash the
    register stores. The hash the card carried is the requirement (what the person saw), so a row that changed after it reads
    `changed_since_answer`; the hash of the row today reads unchanged. Killed by: reading `shown=a.shown` out of the call (controller.py:8373/8393)."""
    for label, stale, expected in (("a hash of a row as it was NOT today", True, True), ("the hash of the row today", False, False)):
        g = GateA()
        try:
            today = next(q for q in QR.load(g.task)["questions"] if q["id"] == "Q10")["row_hash"]
            shown = "ab" * 32 if stale else today
            shown_file = g.task / "state" / "shown.json"
            shown_file.parent.mkdir(parents=True, exist_ok=True)
            shown_file.write_text(json.dumps({"Q10": shown}), encoding="utf-8")
            code, out, _ = g.call("approve as is\nQ10: a\n", "--shown-file", str(shown_file))
            row = next(q for q in QR.load(g.task)["questions"] if q["id"] == "Q10")
            check_eq(f"d11b {label}: recorded, the stored hash is the one the card carried", (code, out.get("recorded"), row["record_row_hash"]), (0, True, shown))
            check_eq(f"d11b {label}: changed_since_answer follows it", row["changed_since_answer"], expected)
        finally:
            cleanup(g.root)


def d15_the_text_says_it() -> None:
    package = SCRIPTS.parent
    for name, keys in (("skills/qa-story/phases/s4.md", ("each on its own line", "question_register.py --answer", "questions.recorded", "questions.rework", "questions.rework_left")),
                       ("skills/qa-story/phases/s8.md", ("each on its own line", "question_register.py --answer", "questions.recorded", "questions.plan_not_changed"))):
        text = (package / name).read_text(encoding="utf-8")
        for key in keys:
            check_in(f"d15 {name} holds `{key}`", key, text)


def main() -> None:
    h3_the_adversarial_list()
    h8_damaged_records()
    h11_a_reader_prints_the_reason()
    h12_registry_and_text()
    d1_d2_d3_d6_a_line_is_recorded_and_applied()
    d4_d5_d5c_a_refused_call_records_the_words_and_leaves_the_files()
    d4b_d4c_an_answer_the_plan_has_no_branch_for_is_owed_not_dropped()
    d5_d5b_nothing_moves_without_a_record()
    d5_e15_an_exception_leaves_the_files_and_the_journal()
    d7_d8_d9_d11_gate_b_and_the_flags()
    d12_d13_the_view_reads_the_answer_without_its_tail_and_never_hides_an_unknown()
    d10_the_gate_b_list_no_longer_holds_a_question_answered_at_gate_a()
    d11b_a_valid_shown_file_reaches_the_stored_hash()
    d14_both_roads_leave_the_same_plan()
    d16_the_real_driver_through_the_real_controller()
    d15_the_text_says_it()
    story = Story()
    try:
        h1_the_flag(story)
        h2_the_token(story)
        h3b_the_adversarial_words_record_no_risk(story)
        h4_no_line_over_an_unrecorded_decision(story)
        f1_the_side_writes_follow_the_story(story)
        h5_the_edges(story)
        h6_the_refusal(story)
        h10_a_later_decision_and_the_old_story(story)
    finally:
        cleanup(story.root)
    finish("test_gate_words_road")


if __name__ == "__main__":
    main()
