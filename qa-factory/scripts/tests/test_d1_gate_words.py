#!/usr/bin/env python3
"""t-1697 D1-B (RN1-14): gate A does not ask what S1 decided, the norms marker, the claim link (F13) - the keys K-B1..K-B5, K-B9.

(K-B6 and K-B7, the stable gate item ids and the norms rule at gate A, are in test_gate_preflight.py.)

K-B1 the S1 decision is carried in a FORM (`planning_contract.register_fork_quotes`, `branch_accounting.quote_problem`), at
     `MIN_QUOTE_WORDS` (3 closes, 2 does not); K-B2 "Already decided by you" lists it, at `LEFT_OUT_CAP` and one more; K-B3 no card for a
     decided or a code-only contradiction (a contradiction between two REQUIREMENT sources keeps its card); K-B4 the S2 exit refuses a
     question on a decided requirement, the door is `asks_beyond_words`; K-B5 the role text; K-B9 a claim row that points to a question
     about other requirements while another question is about this one.

Mutations (named, not run): `decided_by_words` skips `quote_problem` -> K-B1 (the quote that is not in the file); the origin rule drops the
`code_says` condition -> K-B3 (R-10); the other-question rule removed -> K-B9.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import PLUGIN_ROOT, check, check_eq, check_in, cleanup, finish, temp_project  # noqa: E402

sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))
import branch_accounting as BA  # noqa: E402
import contract as C  # noqa: E402
import gate_brief as GB  # noqa: E402
import planning_contract as PC  # noqa: E402

TICKET = "QA-1"
WORDS = "0 is rejected, and so are negative, fractional and non-numeric quantities"
FILE = "s1-conflict-20261101-234118.txt"


def register(forks=(), matrix=(), code_says=None, rows=("R-8", "R-9", "R-10", "R-11")) -> str:
    """A register: `code_says` is `{R: cell}` (None: the register has no such column, as one written before it existed);
    `forks` is `[(R, Decision cell)]`; `matrix` is `[(R, code cell, other-ticket cell)]`."""
    column = code_says is not None
    head = "| R | Requirement | source | derived_from | verifiable | ac_ref | observable | impact | delta |" + (" code_says |" if column else "")
    body = "\n".join(f"| {r} | requirement {r} | story | — | yes | — | none | degraded | new |" + (f" {(code_says or {}).get(r, 'unknown')} |" if column else "")
                     for r in rows)
    text = f"---\ntask: {TICKET}\n---\n\n## Register\n\n{head}\n|{'---|' * (10 if column else 9)}\n{body}\n\n"
    if forks:
        text += "## Reading forks\n\n| R | Fork | Decision |\n|---|---|---|\n" + "\n".join(f"| {r} | a fork of {r} | {d} |" for r, d in forks) + "\n\n"
    text += "## Contradiction matrix\n\n| R | Code | Linked ticket |\n|---|---|---|\n"
    text += "\n".join(f"| {r} | {c} | {o} |" for r, c, o in matrix) + "\n"
    return text


def story(root, reg, words=None, questions=None):
    task = root / "qa-factory" / "artifacts" / TICKET
    (task / "work").mkdir(parents=True, exist_ok=True)
    (task / "state").mkdir(parents=True, exist_ok=True)
    (task / "pipeline.json").write_text(json.dumps({"ticket": TICKET, "stages": {"S0": {"status": "done"}, "S2": {"status": "running"}}}), encoding="utf-8")
    reg_path = task / "work" / "requirements-register.md"
    reg_path.unlink(missing_ok=True)
    if reg is not None:
        reg_path.write_text(reg, encoding="utf-8")
    ready = task / "work" / "requirements-readiness.json"
    ready.unlink(missing_ok=True)
    if questions is not None:
        ready.write_text(json.dumps({"open_questions": questions}), encoding="utf-8")
    (task / "work" / "question-answers.jsonl").unlink(missing_ok=True)       # one folder serves every variant: nothing of the last one stays
    for stale in (task / "state" / "words").glob("*") if (task / "state" / "words").is_dir() else []:
        stale.unlink()
    for name, text in (words or {}).items():
        (task / "state" / "words").mkdir(parents=True, exist_ok=True)
        (task / "state" / "words" / name).write_text(text, encoding="utf-8")
    return task


def quote(words=WORDS, name=FILE, why="") -> str:
    return f'"{words}" ({name})' + (f": {why}" if why else "")


def k_b1_the_decision_is_a_form(root) -> None:
    reg = register(forks=[("R-8", quote(why="the person's rule")), ("R-9", quote("0 is rejected")), ("R-10", "Q1 b adopted: letter"),
                          ("R-11", quote("0 is"))])
    got = PC.register_fork_quotes(reg)
    check_eq("K-B1 a Decision that STARTS with the quote form is in the map (the `: <why>` tail is optional), with quote and file",
             {r: got[r] for r in ("R-8", "R-9")}, {"R-8": {"quote": WORDS, "file": FILE}, "R-9": {"quote": "0 is rejected", "file": FILE}})
    check("K-B1 a cell starting with a question id is NOT in the map (that is `register_fork_questions`'s)", "R-10" not in got, str(got))
    check_eq("K-B1 the tail is optional", PC.register_fork_quotes(register(forks=[("R-8", quote())])), {"R-8": {"quote": WORDS, "file": FILE}})
    check_eq("K-B1 never raises: no register, junk", (PC.register_fork_quotes(""), PC.register_fork_quotes("| |\n## Reading forks\n|")), ({}, {}))
    task = story(root, reg, words={FILE: WORDS})
    check_eq("K-B1 quote_problem: the sentence is in the file -> ''", BA.quote_problem(task, WORDS, FILE), "")
    check_in("K-B1 a quote that is NOT in the file -> a problem", "not in", BA.quote_problem(task, "0 is accepted as a quantity", FILE))
    # E-B1: MIN_QUOTE_WORDS = 3, AT the limit (closes) and BEYOND (2 words: does not)
    check_eq("K-B1 E-B1 AT the limit: 3 words of theirs close the fork (`0 is rejected`)", BA.MIN_QUOTE_WORDS, 3)
    check_eq("K-B1 E-B1 ... three words -> ''", BA.quote_problem(task, "0 is rejected", FILE), "")
    check_in("K-B1 E-B1 BEYOND the limit: 2 words -> 'at least 3 words'", "at least 3 words", BA.quote_problem(task, "0 is", FILE))
    closed = BA.decided_by_words(task, reg)
    check_eq("K-B1 `decided_by_words`: the 3-word fork closes, the 2-word one and the question-id one do not, register order",
             list(closed), ["R-8", "R-9"])
    check_eq("K-B1 E-B1 a missing words file closes nothing", BA.decided_by_words(_without_words(root, reg), reg), {})
    check_eq("K-B1 a words file that does not hold the quote closes nothing",
             BA.decided_by_words(story(root, register(forks=[("R-8", quote("0 is accepted as a quantity"))]), words={FILE: WORDS})), {})
    check_eq("K-B1 E-B3 the register unreadable (absent) -> {}", BA.decided_by_words(story(root, None, words={FILE: WORDS})), {})


def _without_words(root, reg):
    task = story(root, reg)
    for f in (task / "state" / "words").glob("*"):
        f.unlink()
    return task


def k_b2_already_decided_lists_it(root) -> None:
    task = story(root, register(forks=[("R-8", quote(why="x")), ("R-9", quote("0 is rejected"))]), words={FILE: WORDS})
    check_eq("K-B2 the collect list: closed forks only, register order",
             GB._decided_by_words(task), [{"r": "R-8", "quote": WORDS, "file": FILE}, {"r": "R-9", "quote": "0 is rejected", "file": FILE}])
    lines = GB._decided_lines({"decided_by_words": GB._decided_by_words(task)})
    check("K-B2 the section renders when this list ALONE is non-empty", any("Already decided by you" in line for line in lines), str(lines))
    check_in("K-B2 the line: `R-8: decided by your words \"<quote>\" (<file>)`", f'- R-8: decided by your words "{WORDS}" ({FILE})', lines)
    check_eq("K-B2 nothing decided -> no section", GB._decided_lines({"decided_by_words": []}), [])
    rows = lambda n: [{"r": f"R-{i}", "quote": "0 is rejected", "file": FILE} for i in range(1, n + 1)]  # noqa: E731
    at = [line for line in GB._decided_lines({"decided_by_words": rows(GB.LEFT_OUT_CAP)}) if "decided by your words" in line]
    over = GB._decided_lines({"decided_by_words": rows(GB.LEFT_OUT_CAP + 1)})
    check_eq("K-B2 E-B2 AT the cap: all lines, no `(+K more`", (len(at), any("more" in line for line in GB._decided_lines({"decided_by_words": rows(GB.LEFT_OUT_CAP)}))),
             (GB.LEFT_OUT_CAP, False))
    check_eq("K-B2 E-B2 cap+1: `LEFT_OUT_CAP` lines and `(+1 more - the requirements register names them all)`",
             ([line for line in over if "decided by your words" in line].__len__(), over[-1]),
             (GB.LEFT_OUT_CAP, "- (+1 more - the requirements register names them all)"))
    long = "word " * 60
    clipped = [line for line in GB._decided_lines({"decided_by_words": [{"r": "R-1", "quote": long, "file": FILE}]}) if "R-1" in line][0]
    check("K-B2 a long quote is clipped to LEFT_OUT_CLIP with a mark", "… (cut)" in clipped and len(clipped) < GB.LEFT_OUT_CLIP + 80, clipped)
    try:
        data = GB.collect(TICKET, root=task)
        check_eq("K-B2 `collect` carries the key", [r["r"] for r in data.get("decided_by_words", [])], ["R-8", "R-9"])
    except Exception as exc:  # noqa: BLE001
        check("K-B2 `collect` runs on the fixture", False, f"{type(exc).__name__}: {exc}")
    check_eq("K-B2 E-B3 an unreadable register -> []", GB._decided_by_words(story(root, None, words={FILE: WORDS})), [])


def k_b3_no_card_for_a_decided_or_code_only_contradiction(root) -> None:
    matrix = [("R-8", "silent", "contradicts: the other ticket says negative is allowed"),
              ("R-9", "contradicts: the code accepts 0", "silent"),
              ("R-10", "contradicts: the code accepts -1", "silent"),
              ("R-11", "silent", "contradicts: the other ticket says 200")]
    rows = [{"id": f"TS-{n}", "source_conflict": True, "requirements": [r]} for n, r in ((8, "R-8"), (9, "R-9"), (10, "R-10"), (11, "R-11"))]
    reg = register(forks=[("R-8", quote())], matrix=matrix, code_says={"R-9": "contradicts: fact-1", "R-10": "unknown", "R-11": "unknown"})
    task = story(root, reg, words={FILE: WORDS})
    cards = [q["id"] for q in GB.contradiction_questions(task, rows)]
    check_eq("K-B3 R-8 (word-closed) no card; R-9 (code + `code_says: contradicts`) no card; R-10 (code, no `contradicts`) and R-11 (another ticket) keep theirs",
             cards, ["R-10", "R-11"])
    task = story(root, register(forks=[("R-8", quote())], matrix=matrix, code_says=None), words={FILE: WORDS})
    check_eq("K-B3 E-B4 a register with NO `code_says` column (before the port): the code cards stay; the word-closed one is still closed",
             [q["id"] for q in GB.contradiction_questions(task, rows)], ["R-9", "R-10", "R-11"])
    both = register(matrix=[("R-11", "silent", "contradicts: the other ticket says 200")], code_says={"R-11": "contradicts: fact-1"})
    check_eq("K-B3 invariant: a contradiction between two REQUIREMENT sources keeps its card although the row says `code_says: contradicts`",
             [q["id"] for q in GB.contradiction_questions(story(root, both), rows[3:])], ["R-11"])
    # F3 (t-1752): the code cell comes FIRST and the other ticket contradicts too -> the card stays; R-9 (code only) stays dropped
    two = register(matrix=[("R-12", "contradicts: the code accepts 0", "contradicts: the other ticket says 200"),
                           ("R-9", "contradicts: the code accepts 0", "silent")],
                   code_says={"R-12": "contradicts: fact-1", "R-9": "contradicts: fact-1"}, rows=("R-9", "R-12"))
    two_rows = [{"id": "TS-12", "source_conflict": True, "requirements": ["R-12"]}, {"id": "TS-9", "source_conflict": True, "requirements": ["R-9"]}]
    check_eq("K-B3 F3: code first + another ticket second keeps the card (R-12); code only (R-9) stays dropped",
             [q["id"] for q in GB.contradiction_questions(story(root, two), two_rows)], ["R-12"])
    check_eq("K-B3 F3: the readings carry every origin of the R", PC.register_contradiction_readings(two)["R-12"]["origins"], ["code", "description"])
    check_eq("K-B3 E-B3 the quote is not in the words file -> the card stays",
             [q["id"] for q in GB.contradiction_questions(story(root, reg, words={FILE: "something else entirely here"}), rows[:1])], ["R-8"])


def k_b4_a_question_on_a_decided_requirement(root) -> None:
    import test_branch_accounting as TB          # its story/register/snapshot helpers build a register the S2 exit reads
    ask = lambda qid, text, **extra: dict({"id": qid, "question": text, "severity": "major", "source_says": [],  # noqa: E731
                                           "readings": [{"reading": "a", "from": "person", "if_chosen": "x"}, {"reading": "b", "from": "person", "if_chosen": "y"}]}, **extra)
    reg = register(forks=[("R-8", quote()), ("R-9", quote("0 is rejected", why="again"))])

    def check_of(*questions, words=None):
        task = story(root, reg, words={FILE: WORDS} if words is None else words, questions=list(questions))
        return BA.decided_question_check(task, reg)

    got = check_of(ask("Q1", "Is 0 a valid quantity (R-8)?"))
    check("K-B4 every R the question names is word-closed -> 1 problem naming the question, the ids, the file and the door",
          len(got) == 1 and got[0].startswith("Q1:") and "R-8" in got[0] and FILE in got[0] and "asks_beyond_words" in got[0], str(got))
    check_eq("K-B4 with the door (`asks_beyond_words: <what the words leave open>`) -> 0",
             check_of(ask("Q1", "Is 0 a valid quantity (R-8)?", asks_beyond_words="the upper limit the words leave open")), [])
    check_eq("K-B4 an EMPTY door string is no door", len(check_of(ask("Q1", "Is 0 valid (R-8)?", asks_beyond_words="  "))), 1)
    check_eq("K-B4 one id not closed (R-10) -> 0", check_of(ask("Q1", "Is it valid for R-8 and R-10?")), [])
    check_eq("K-B4 all of several ids closed -> 1", len(check_of(ask("Q1", "Is it valid for R-8 and R-9?"))), 1)
    check_eq("K-B4 a question naming no R id -> 0 (FR-12: no meaning is read)", check_of(ask("Q1", "Is zero a valid quantity?")), [])
    check_eq("K-B4 the words file missing -> not closed -> 0", check_of(ask("Q1", "Is 0 valid (R-8)?"), words={"other.txt": "x"}), [])
    # an answered question is settled: nothing to refuse
    task = story(root, reg, words={FILE: WORDS}, questions=[ask("Q1", "Is 0 valid (R-8)?")])
    import question_register as QR
    (task / "work" / "question-answers.jsonl").write_text(json.dumps(
        {"id": "Q1", "status": "answered", "reading": "a", "words": "a", "where": "gate_a", "at": "2026-11-01T10:00:00", "row_hash": QR._hash(ask("Q1", "Is 0 valid (R-8)?"))}) + "\n",
        encoding="utf-8")
    check_eq("K-B4 an answered question -> 0", BA.decided_question_check(task, reg), [])
    # the S2 exit carries it (the caller named in the report: `branch_accounting.s2_check`, next to `norms_question_check`)
    snap = TB.snapshot("Plain sentence here.")
    s2 = TB.story(root, reg, snap)
    (s2 / "work" / "question-answers.jsonl").unlink(missing_ok=True)
    (s2 / "work" / "requirements-readiness.json").write_text(json.dumps({"open_questions": [ask("Q1", "Is 0 valid (R-8)?")]}), encoding="utf-8")
    (s2 / "state" / "words").mkdir(parents=True, exist_ok=True)
    (s2 / "state" / "words" / FILE).write_text(WORDS, encoding="utf-8")
    blocks = BA.s2_check(s2)["blocks"]
    check("K-B4 the S2 exit refuses it: a block with the question's line", any(any(line.startswith("Q1:") and "asks_beyond_words" in line for line in lines) for _h, lines in blocks), str(blocks))
    titles = [h for h, lines in blocks if any(line.startswith("Q1:") for line in lines)]
    check_eq("K-B4 F8: the block that carries the decided-question line is titled for it, not for `code_says`",
             titles, ["REJECT — 1 readiness question(s) on what is already decided:"])
    (s2 / "work" / "requirements-readiness.json").write_text(json.dumps({"open_questions": [ask("Q1", "Is 0 valid (R-8)?", asks_beyond_words="the maximum")]}), encoding="utf-8")
    check("K-B4 ... and passes with the door", not any(any("asks_beyond_words" in line for line in lines) for _h, lines in BA.s2_check(s2)["blocks"]))


def k_b5_the_role_text() -> None:
    text = (PLUGIN_ROOT / "agents" / "qa-requirements-tester.md").read_text(encoding="utf-8")
    # the role-text keys of the settled-fork form are rows of design/role-rules.json (test-diet TD-5.3.2)
    check("K-B5 the charter did not grow past the pin it had (10,672 B before this change)", len(text.encode("utf-8")) <= 10672, str(len(text.encode("utf-8"))))


def k_b9_the_claim_points_to_the_question_about_it() -> None:
    def question(qid, text):
        return {"id": qid, "question": text, "source_says": "", "before": {"value": "400", "where": "x"}, "now": {"value": "403", "where": "y"},
                "readings": [{"reading": "a", "from": "claim", "if_chosen": "x"}, {"reading": "b", "from": "claim", "if_chosen": "y"}]}
    row = {"r": "R-10", "before": "400", "before_ref": "absent", "now": "403", "now_ref": "diff:a.py:1", "differs": "yes", "question": "Q1"}
    questions = {"Q1": question("Q1", "What happens to R-11 on a missing id?"), "Q2": question("Q2", "What happens to R-10 on a missing id?")}
    got = C.claim_row_errors(row, questions)
    check("K-B9 the wrong link -> one error naming the claim, Q1, its ids and the question about R-10",
          len(got) == 1 and "claim of R-10 points to Q1" in got[0] and "R-11" in got[0] and "Q2 is the question about R-10" in got[0] and "point the claim to Q2" in got[0], str(got))
    check_eq("K-B9 Q1 naming no R id -> none (FR-12)", C.claim_row_errors(row, {"Q1": question("Q1", "What happens on a missing id?"), "Q2": questions["Q2"]}), [])
    check_eq("K-B9 Q1 naming R-10 itself -> none", C.claim_row_errors(row, {"Q1": question("Q1", "What happens to R-10 and R-11?"), "Q2": questions["Q2"]}), [])
    check_eq("K-B9 Q1 about other rows and NO other question about R-10 -> none", C.claim_row_errors(row, {"Q1": questions["Q1"]}), [])
    check_eq("K-B9 E-B8 the questions map None -> no link check", C.claim_row_errors(row, None), [])
    check_eq("K-B9 `R-1` is not `R-10` (whole ids): a question about R-1 is not about R-10", C.claim_row_errors(row, {"Q1": question("Q1", "What about R-11?"), "Q2": question("Q2", "What about R-1?")}), [])
    marked = {"id": "Q1", "question": "Which of R-1 and R-2 hold?", "norms_list": True}
    check_eq("K-B7 E-B7 the marker is inert with no norm rows", (C.is_norms_question(marked, set()), C.is_norms_question(marked, {"R-1", "R-2"})), (False, True))
    check_eq("K-B7 a marked question that names a non-norm row is refused",
             [e.split(" - ")[0] for e in C.norms_question_errors(dict(marked, id="Q1"), {"R-1"})], ["question Q1 is marked `norms_list` but names R-2, which is no norm row"])
    check_eq("K-B7 E-B7 a marked question with no R ids: only the `from: code` rule (none here)",
             C.norms_question_errors({"id": "Q1", "question": "Do the norms hold?", "norms_list": True, "readings": []}, {"R-1"}), [])
    check_eq("K-B7 `norms_list: \"true\"` (a string) is no mark", C.is_norms_question({"id": "Q1", "question": "Is R-1 ok?", "norms_list": "true"}, {"R-1"}), False)


if __name__ == "__main__":
    root = temp_project("qa-d1b-")
    try:
        k_b1_the_decision_is_a_form(root)
        k_b2_already_decided_lists_it(root)
        k_b3_no_card_for_a_decided_or_code_only_contradiction(root)
        k_b4_a_question_on_a_decided_requirement(root)
        k_b5_the_role_text()
        k_b9_the_claim_points_to_the_question_about_it()
    finally:
        cleanup(root)
    finish("test_d1_gate_words")
