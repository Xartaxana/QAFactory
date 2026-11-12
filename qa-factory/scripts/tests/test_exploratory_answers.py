"""test_exploratory_answers.py - gate B asks the questions of the exploratory findings in words and reads three closed answers
(P2 fix round W2, critic t-1579 M1: N3 the packet, N4 the reader and the driver hook, N5 `intended`, N6 `open`, N8).

Run from the package root: python -B scripts/tests/test_exploratory_answers.py   (script style, like its neighbours)

Keys: K-M1-a..e (the packet), K-M1-f (the reader's battery), K-M1-g (every edge E3..E18), K-M1-i (`intended`), K-M1-j (`open`
and silence), K-M1-k (`bug`), K-WORDS (the word lists are apart), K-M1-l (the id overlap with a stand-gap card).
Mutation -> killing key (named, not run; D-0056): the fence rule dropped -> K-M1-f; the shown-map ("changed since") check dropped
-> K-M1-g; the stand-gap unread filter dropped -> K-M1-l; the selector on `kind` -> K-M1-d; the headline clause kept -> K-M1-c; the
question id shown -> K-M1-b; the `bug`+approval guard dropped -> K-M1-k.
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from harness import check, check_eq, check_in, cleanup, finish  # noqa: E402

import contract as C  # noqa: E402
import controller as CTL  # noqa: E402
import exploratory_findings as EF  # noqa: E402
import gate_brief as GB  # noqa: E402
import human_text as HT  # noqa: E402
import question_register as QR  # noqa: E402
import report_facts as RF  # noqa: E402
import test_report_facts as TRF  # noqa: E402

BY = "S7-qa-failure-analyst-1"
WORDS = GB.exploratory_question_words()
SHOWN = [{"case": "TC-006", "line": "EX-1", "qid": "Q7", "row_hash": "a" * 64, "addressable": True},
         {"case": "TC-007", "line": "EX-2", "qid": "", "row_hash": "", "addressable": True}]
LIVE = {"EX-1", "EX-2"}


def read(words, shown=SHOWN, current=LIVE):
    return GB.read_exploratory_answers(words, shown, current)


def lines_of(found, key):
    return [item["line"] if key == "unread" else item["line_text"] for item in found[key]]


# --- the packet (N3) --------------------------------------------------------------------------------------------------------

def readiness(task: Path) -> None:
    claim = C.claim_readings("400", "403")
    TRF.write(task / "work" / "requirements-readiness.json", {"open_questions": [
        {"id": "Q7", "question": "Which status should a viewer get from the export?", "source_says": "the ticket is silent",
         "readings": claim, "severity": "blocking", "owner_role": "the person", "before": {"value": "400", "where": "the old code"},
         "now": {"value": "403", "where": "the new code"}}]})


def question_story():
    task = TRF.story(with_bug=False)
    readiness(task)
    TRF.write(task / "work" / "evidence" / "e1.txt", "seen")
    EF.append(task, {"op": "add", "kind": "unresolved_question", "title": "the export for a viewer", "statement": "the export answered 403",
                     "refs": ["TC-006", "R-16", "Q7"], "why_not_a_bug": "no requirement says which status", "evidence_refs": [{"path": "work/evidence/e1.txt"}],
                     "question": "Which status should a viewer get from the export?", "owner_role": "the person",
                     "origin": {"dispatch": BY, "target": "t-1"}}, by=BY)
    return task


def block_of(packet: str) -> str:
    return packet[packet.index("Exploratory findings"):packet.index("Bugs found")]


def key_packet():
    task = question_story()
    try:
        parts = RF.exploratory_gate_parts(task)
        check_eq("K-M1-a one question, with its case and its row", [(q["case"], q["qid"], q["addressable"]) for q in parts["questions"]],
                 [("TC-006", "Q7", True)])
        packet = GB.render_gate_b("T-1", task)
        block = block_of(packet)
        for needle in ("TC-006", "Before the change: 400.", "Now: 403.", "Is this intended?", "`intended`", "`bug`", "`open`",
                       "Questions for you — is this intended? (1)", "`TC-006: intended`"):
            check_in(f"K-M1-a the packet holds {needle!r}", needle, block)
        check_eq("K-M1-a the question block passes the shape rules of a question", HT.shape_problems(block, kind="question"), [])
        check_eq("K-M1-a ... and every option carries its three price lines", HT.price_problems(block, ["intended", "bug", "open"]), [])
        check("K-M1-b no machine shape, no register id, no question id in the block",
              TRF.machine_shapes_in(block) == [] and not re.search(r"\bQ\d+\b", block), block[:300])
        check("K-M1-b ... and none in the whole packet's findings part either (the long-documents paths are another section)",
              "EX-" not in packet and not re.search(r"\bQ7\b", packet.split("## The long documents")[0].replace("Open before", "")), "")
        check("K-M1-c a question line exists: the no-bugs headline does not say 'nothing to answer here' (FR-10)",
              "Bugs found — none." in packet and "nothing to answer" not in packet, packet[:900])
        check("K-M1-c the question block stands ABOVE the headline (P1/P2)", packet.index("Questions for you") < packet.index("Bugs found"))
        check("K-M1-b the question is listed once: 'Open before the MR' does not repeat the readiness question (F4b)",
              packet.count("Which status should a viewer get") == 1 and "unanswered question" not in packet,
              str(packet.count("Which status should a viewer get")))
        check("F4b control: without the skip the readiness question is listed",
              any("Which status should a viewer get" in line for line in GB.open_before_mr(task)))
        check("F4b ... and with the qid shown it is not", not any("Which status should a viewer get" in line for line in GB.open_before_mr(task, "B", (), ("Q7",))))
        # K-M1-c control: only a gap line -> the old clause stays
        gap_only = TRF.story(with_bug=False)
        try:
            TRF.add_finding(gap_only, "coverage_gap", "no stand with the export", target="t-3")
            plain = GB.render_gate_b("T-1", gap_only)
            check("K-M1-c control: only gap lines -> 'nothing to answer here' still stands", "nothing to file and nothing to answer here." in plain, plain[:600])
        finally:
            cleanup(gap_only.parents[2])
        # K-M1-d: a closed-gap question (kind coverage_gap, oracle owner_question) is a question, once, and not a gap
        EF.append(task, {"op": "add", "kind": "coverage_gap", "title": "export for an admin", "statement": "the admin export was not tried",
                         "refs": ["TC-007"], "why_not_a_bug": "not investigated", "evidence_refs": [{"path": "work/evidence/e1.txt"}],
                         "missing_prerequisite": "not investigated - the budget ended", "oracle_status": "owner_question",
                         "question": "Should an admin export too?", "owner_role": "the person", "origin": {"dispatch": BY, "target": "t-2"}}, by=BY)
        parts = RF.exploratory_gate_parts(task)
        check_eq("K-M1-d the closed gap is a question line", sorted(q["case"] for q in parts["questions"]), ["TC-006", "TC-007"])
        check_eq("K-M1-d ... and not a gap line", parts["gaps"], [])
        text = "\n".join(RF.exploratory_gate_lines(task))
        check_eq("K-M1-d ... printed once", text.count("export for an admin"), 1)
        check_eq("K-M1-d ... its line without a before/now carrier says 'not recorded' (F3 a, FR-41)",
                 text.count("Before the change: not recorded. Now: not recorded."), 1)
    finally:
        cleanup(task.parents[2])


# --- the reader (N4) --------------------------------------------------------------------------------------------------------

def key_battery():
    ok = read("TC-006: intended\nTC-007: bug")
    check_eq("K-M1-f the plain form is read", [(e["case"], e["option"]) for e in ok["read"]], [("TC-006", "intended"), ("TC-007", "bug")])
    check_eq("K-M1-f ... with nothing unread", ok["unread"], [])
    fenced = read("```\nTC-006: intended\n```\n> TC-007: bug\n")
    check_eq("K-M1-f nesting: a fenced line and a quoted line are no answer (M-i)", (fenced["read"], fenced["unread"]), ([], []))
    check_eq("K-M1-f nesting: a bullet is forgiven, a closing . and backquotes too",
             [e["option"] for e in read("- TC-006: `intended`.")["read"]], ["intended"])
    check_eq("K-M1-f encoding: CRLF, upper case and a synonym", [e["option"] for e in read("TC-006: INTENDED\r\nTC-007: it is a bug\r\n")["read"]],
             ["intended", "bug"])
    check_eq("K-M1-f encoding: a BOM before the first id", [e["option"] for e in read(chr(0xFEFF) + "TC-006: open")["read"]], ["open"])
    check_eq("K-M1-f encoding: a no-break space inside a two-word synonym", [e["option"] for e in read("TC-006: leave" + chr(0xA0) + "open")["read"]], ["open"])
    look_alike = read("TC-006: " + chr(0x456) + "ntended")             # a Cyrillic i
    check_eq("K-M1-f encoding: a Cyrillic look-alike is not read, and is said", (look_alike["read"], len(look_alike["unread"])), ([], 1))
    check_eq("K-M1-f empty: empty words and blanks read nothing", (read(""), read("   \n\n \t")), ({"read": [], "unread": []},) * 2)
    for broken in ("TC-006:", ": intended", "TC-006 intended", "intended", "TC-006:   "):
        check_eq(f"K-M1-f broken {broken!r}: neither read nor unread", read(broken), {"read": [], "unread": []})
    many = [{"case": f"TC-{n:03d}", "line": f"EX-{n}", "qid": "", "row_hash": "", "addressable": True} for n in range(1, 51)]
    big = read("\n".join(f"TC-{n:03d}: {'intended' if n % 2 else 'open'}" for n in range(1, 51)), many, {f"EX-{n}" for n in range(1, 51)})
    check_eq("K-M1-f magnitude: 50 questions and 50 answers, all read", (len(big["read"]), big["unread"]), (50, []))


def key_edges():
    check_eq("E3/E1 nothing shown: nothing is read and nothing is unread", (read("TC-006: intended", []), read("TC-006: intended", None)),
             ({"read": [], "unread": []},) * 2)
    out = read("TC-006: intended\nTC-009: intended\nTC-006: perhaps")
    check_eq("E8 an id that is no question shown, a word outside the list: unread, with the words that apply",
             [(u["line"], "not one of the questions shown" in u["why"] or "the words that apply here are: `intended`, `bug`, `open`" in u["why"])
              for u in out["unread"]], [("TC-009: intended", True), ("TC-006: perhaps", True)])
    check_eq("E8 ... and the good line is still read", lines_of(out, "read"), ["TC-006: intended"])
    twin = read("TC-006: intended", [dict(SHOWN[0]), dict(SHOWN[0], line="EX-5")], LIVE | {"EX-5"})
    check_eq("E6 an id that names two questions is unread, never read", (twin["read"], [u["why"] for u in twin["unread"]]),
             ([], ["that id names more than one question; answer in words"]))
    same = read("TC-006: intended\nTC-006: expected")
    check_eq("E7 the same word twice is ONE answer, the earlier line kept", [(e["option"], e["replaced"]) for e in same["read"]],
             [("intended", ["TC-006: intended"])])
    clash = read("TC-006: intended\nTC-006: bug")
    check_eq("E7/F7 different words for one question: neither is applied, both unread", (clash["read"], len(clash["unread"])), ([], 2))
    two_words = read("TC-006: intended bug")
    check_eq("F7 two words on one line: unread (the whole text after the colon is the word)", (two_words["read"], len(two_words["unread"])), ([], 1))
    gone = read("TC-006: intended", SHOWN, {"EX-2", "EX-9"})
    check_eq("E10 the shown line is no longer the live one: unread 'changed since you saw it' (M-j)", (gone["read"], [u["why"] for u in gone["unread"]]),
             ([], ["the finding changed since you saw it"]))
    stand = read("TC-006: accept\nTC-006: change\nTC-006: not needed\nTC-007: manual\nTC-006: accept as blocked\nTC-006: command pytest -q")
    check_eq("E12 a word of another reader on a shown id is that reader's: neither read nor unread", stand, {"read": [], "unread": []})
    check_eq("E13 no word list: nothing is read and nothing unread, whatever the packet shows",
             GB.read_exploratory_answers("TC-006: intended", SHOWN, LIVE, rows=[]), {"read": [], "unread": []})
    check("E13 a damaged row (no price line) is dropped, never a wrong answer",
          GB.exploratory_word_index([r for r in WORDS if r["option"] != "bug"]).get("bug") is None)
    block = GB.exploratory_answer_block({"questions": [{"addressable": True, "case": "TC-006"}]})
    check("E13 the block names each word with its three price lines, in the order of the labels",
          all(any(line.startswith(f"({letter}) `{row['word']}`") for line in block) for letter, row in zip("abc", WORDS))
          and sum(line.startswith("the factory:") for line in block) == 3 and sum(line.startswith("you:") for line in block) == 3
          and sum(line.startswith("the story:") for line in block) == 3, "\n".join(block))
    check_eq("E5 a question with no case: no answer form is offered, one sentence says so",
             len(GB.exploratory_answer_block({"questions": [{"addressable": False, "case": ""}]})), 1)
    check_eq("E1 no questions: no block", GB.exploratory_answer_block({"questions": []}), [])


def key_words():
    """K-WORDS: a word belongs to one option of one reader only. Negative control: a temporary row `accept` makes it fail."""
    def clashes(rows):
        mine = {GB._word_key(t) for row in rows for t in [row["word"], *row["synonyms"]]}
        theirs = GB._foreign_word_keys()
        gates = json.loads((Path(GB.__file__).resolve().parents[1] / "references" / GB.APPROVAL_WORDS_FILE).read_text(encoding="utf-8"))
        approvals = {GB._word_key(w) for w in (gates.get("gate_approval_words") or {})}
        return sorted(mine & (theirs | approvals))
    check_eq("K-WORDS no word or synonym is a word of the stand-gap, environment, probe, case-decision, question or approval lists",
             clashes(WORDS), [])
    check_eq("K-WORDS the three options, once each", sorted(row["option"] for row in WORDS), ["bug", "intended", "open"])
    check("K-WORDS NEGATIVE CONTROL: a temporary row `accept` makes the check fail",
          clashes(WORDS + [{"option": "open", "word": "accept", "synonyms": []}]) == ["accept"])
    own = [GB._word_key(t) for row in WORDS for t in [row["word"], *row["synonyms"]]]
    check_eq("K-WORDS ... and no word belongs to two options of this list", len(own), len(set(own)))


# --- the driver hook (N4/N5/N6) ---------------------------------------------------------------------------------------------

def driver_of(task: Path, shown, state=None):
    import story_run as SR
    drv = object.__new__(SR.Driver)
    drv.task_root, drv.dry, drv.state = task, False, dict(state or {}, shown_exploratory=shown)
    drv.calls = []
    drv.gate_approval = lambda kind, words: words.strip().splitlines()[0].strip().lower() == "approve"
    drv.no_move_facts = lambda state: {"rework_stages": ["S7"], "rework_roles": {"S7": ["qa-failure-analyst"]}, "scope": ["TC-006", "TC-007"],
                                       "causes": list(CTL.REPAIR_CAUSES)}
    drv.record_seam_rework = lambda args, rel, preface=(): drv.calls.append((args, rel, list(preface)))
    drv.answer_file = lambda: "state/words/driver-answer-1.txt"
    return drv


def active_oracles(task):
    return {line["id"]: line["oracle_status"] for line in EF.read(task)["active"].values()}


def key_driver():
    task = question_story()
    try:
        shown = RF.exploratory_gate_parts(task)["questions"]
        mapping = [{k: q[k] for k in ("case", "line", "qid", "row_hash", "addressable")} for q in shown]
        check_eq("K-M1-i the shown map is the one the packet is rendered from", mapping, GB.exploratory_shown(task))
        drv = driver_of(task, mapping)
        out = drv.take_exploratory_answers("gate_B", "TC-006: intended", "")
        check_eq("K-M1-i `intended` is recorded by code", (out["recorded"], out["unread"]), (["TC-006: intended"], []))
        check_eq("K-M1-i the line is now person_confirmed (one active line for the target)", list(active_oracles(task).values()), ["person_confirmed"])
        line = next(iter(EF.read(task)["active"].values()))
        check("K-M1-i ... with the person's line in its words and the correction's reason",
              'you said at gate B: "TC-006: intended"' in line["why_not_a_bug"] and line["corrects"]["reason"].endswith("by the person at gate B"), str(line)[:300])
        row = next(q for q in QR.load(task)["questions"] if q["id"] == "Q7")
        check_eq("K-M1-i F1 B: the question is answered with the reading `now` (a), on the person's words", (row["status"], row["reading"], row["words"]),
                 ("answered", "a", "TC-006: intended"))
        check_eq("K-M1-i the gate lines no longer list TC-006", RF.exploratory_gate_parts(task)["questions"], [])
        before = (task / "work" / "exploratory-findings.jsonl").read_bytes()
        again = drv.take_exploratory_answers("gate_B", "TC-006: intended", "")
        check_eq("E11 the same word on the same line again: nothing is written", (again["unread"], (task / "work" / "exploratory-findings.jsonl").read_bytes() == before), ([], True))
        check_eq("E19 a dry run and another question read nothing", (setattr(drv, "dry", True) or drv.take_exploratory_answers("gate_B", "TC-006: bug", ""),
                                                                       setattr(drv, "dry", False) or drv.take_exploratory_answers("gate_A", "TC-006: bug", "")), ({}, {}))
    finally:
        cleanup(task.parents[2])

    task = question_story()
    try:
        mapping = GB.exploratory_shown(task)
        drv = driver_of(task, mapping)
        register = (task / "work" / "exploratory-findings.jsonl").read_bytes()
        silent = drv.take_exploratory_answers("gate_B", "thanks, looks fine", "")
        check_eq("K-M1-j silence reads nothing and writes nothing", (silent, (task / "work" / "exploratory-findings.jsonl").read_bytes() == register,
                                                                       (task / "work" / "question-answers.jsonl").exists()), ({}, True, False))
        out = drv.take_exploratory_answers("gate_B", "TC-006: open", "")
        check_eq("K-M1-j `open` leaves the register bytes unchanged", (out["unread"], (task / "work" / "exploratory-findings.jsonl").read_bytes() == register), ([], True))
        row = next(q for q in QR.load(task)["questions"] if q["id"] == "Q7")
        check_eq("K-M1-j F1 B: with a question, `open` writes ONE deferred_to_report", (row["status"], (task / "work" / "question-answers.jsonl").read_text(encoding="utf-8").count("\n")),
                 ("deferred_to_report", 1))
        drv.take_exploratory_answers("gate_B", "TC-006: open", "")
        check_eq("E11 the same `open` again writes nothing more", (task / "work" / "question-answers.jsonl").read_text(encoding="utf-8").count("\n"), 1)
        parts = RF.exploratory_gate_parts(task)
        check_eq("E9 a re-shown gate does not ask it again (FR-7), and says it was left open", (parts["questions"], parts["left_open"]), ([], ["TC-006"]))
        check_in("E9 ... in words", "Left open by you at gate B, not asked again: TC-006", "\n".join(RF.exploratory_gate_lines(task, parts=parts)))
        # a line with no question: remembered, asked again with a changed text
        EF.append(task, {"op": "add", "kind": "unresolved_question", "title": "export for an admin", "statement": "the admin export was not tried",
                         "refs": ["TC-007"], "why_not_a_bug": "not investigated", "evidence_refs": [{"path": "work/evidence/e1.txt"}],
                         "question": "Should an admin export too?", "owner_role": "the person", "origin": {"dispatch": BY, "target": "t-2"}}, by=BY)
        drv.state["shown_exploratory"] = GB.exploratory_shown(task)
        drv.take_exploratory_answers("gate_B", "TC-007: open", "")
        check_eq("K-M1-j F8: an `open` with no question is remembered, the register is not written", (drv.state.get("exploratory_open"),), ({"EX-2": "TC-007"},))
        said = drv.keep_shown_exploratory()
        check("E9/F8 the next gate B says 'Still open from your last answer'", said.startswith("Still open from your last answer: TC-007"), said)
        check_eq("E9 ... and once the line is gone from the packet it is forgotten", (setattr(drv, "state", dict(drv.state, exploratory_open={"EX-77": "TC-077"})) or drv.keep_shown_exploratory(),
                                                                                          drv.state["exploratory_open"]), ("", {}))
    finally:
        cleanup(task.parents[2])

    task = question_story()
    try:
        EF.append(task, {"op": "add", "kind": "unresolved_question", "title": "export for an admin", "statement": "the admin export was not tried",
                         "refs": ["TC-007"], "why_not_a_bug": "not investigated", "evidence_refs": [{"path": "work/evidence/e1.txt"}],
                         "question": "Should an admin export too?", "owner_role": "the person", "origin": {"dispatch": BY, "target": "t-2"}}, by=BY)
        mapping = GB.exploratory_shown(task)
        drv = driver_of(task, mapping)
        out = drv.take_exploratory_answers("gate_B", "TC-006: bug\nTC-007: wrong\nplease look at both", "")
        check_eq("K-M1-k E17 several `bug` lines: ONE rework of S7 with the whole words file (P5)",
                 (len(drv.calls), drv.calls[0][0]["stage"], drv.calls[0][0]["role"], drv.calls[0][0]["cases"], drv.calls[0][1]),
                 (1, "S7", "qa-failure-analyst", ["TC-006", "TC-007"], "state/words/driver-answer-1.txt"))
        check_eq("K-M1-k ... both recorded, nothing unread; the register is not written", (out["recorded"], out["unread"]), (["TC-006: bug", "TC-007: wrong"], []))
        check("K-M1-k ... and the note tells the conductor not to record them again", "recorded by code, do not record again: TC-006: bug" in out["note"], out["note"])
        drv = driver_of(task, mapping)
        out = drv.take_exploratory_answers("gate_B", "approve\nTC-006: bug", "")
        check_eq("E16/F7 a `bug` beside the approval word: no rework, the line is unread (the gate is not recorded by code)",
                 (drv.calls, out["unread"], out["recorded"]), ([], ["TC-006: bug"], []))
        drv = driver_of(task, mapping)
        drv.no_move_facts = lambda state: {"rework_stages": ["S7"], "rework_roles": {"S7": ["qa-failure-analyst"]}, "scope": ["TC-009"], "causes": list(CTL.REPAIR_CAUSES)}
        out = drv.take_exploratory_answers("gate_B", "TC-006: bug", "")
        check_eq("E18 a rework the controller would refuse (case outside the scope): the line is unread with the reason, nothing recorded",
                 (drv.calls, out["unread"], out["recorded"], "outside the approved scope" in out["note"]), ([], ["TC-006: bug"], [], True))
        drv = driver_of(task, mapping)
        out = drv.take_exploratory_answers("gate_B", "TC-006: intended\nTC-006: wrong\nTC-007: bug", "")
        check_eq("E7 contradicting words for one line never reach an executor", (active_oracles(task) == {"EX-1": "owner_question", "EX-2": "owner_question"},
                                                                                  len(out["unread"]) >= 2), (True, True))
    finally:
        cleanup(task.parents[2])


def key_overlap():
    """K-M1-l (P4, M-k): a question line and a stand-gap card on ONE case id. The exploratory words are not unread stand-gap lines;
    a stand-gap line that is really unread stays."""
    task = question_story()
    try:
        drv = driver_of(task, GB.exploratory_shown(task))
        drv._stand_gap_lines = lambda kind, gate, words, qtext: {
            "gaps": [], "found": {"read": [], "revokes": [], "unread": [
                {"line": "TC-006: intended", "why": "the word is not one of the answers the card offers"},
                {"line": "TC-006: bug", "why": "x"}, {"line": "TC-006: whatever", "why": "the word is not one of the answers the card offers"}]},
            "doors": {"read": [], "unread": []}, "forms": {}, "rehearsal": None}
        drv.revoke_environment_properties = lambda gate, revokes: []
        drv._record_gap_lines = lambda *a: ([], [], set())
        drv._record_door_lines = lambda *a: ([], [], set())
        drv._relay_note = lambda *a: ""
        out = drv.take_stand_gap_answers("gate_B", "TC-006: intended", "", "S9", "")
        check_eq("K-M1-l an exploratory word on a shown question id leaves the stand-gap unread list; a really unread line stays",
                 out["unread"], ["TC-006: whatever"])
        drv.state["shown_exploratory"] = []
        out = drv.take_stand_gap_answers("gate_B", "TC-006: intended", "", "S9", "")
        check_eq("K-M1-l control: with no question shown nothing is filtered", len(out["unread"]), 3)
    finally:
        cleanup(task.parents[2])


def promises_left_with_you(text: str) -> bool:
    """The B-1 judgment: does a price line promise the report's `Left with you` section? (Until HF8-17 no code writes that.)"""
    return "left with you" in str(text).lower()


def key_w3():
    """P2 fix round W3 (critic t-1592): B-1 the `open` text, M-a the `bug` rework carries the finding, M-b the answer form tells the
    truth, m-1..m-6. Each check names the finding it pins."""
    import story_run as SR
    # --- B-1: option (c) says only what the code does ---------------------------------------------------------------------------
    story = next(row["story"] for row in WORDS if row["option"] == "open")
    block = "\n".join(GB.exploratory_answer_block({"questions": [{"addressable": True, "case": "TC-006"}]}))
    check("K-B1 the `open` price line does not promise the section 'Left with you' (no code writes it, HF8-17), and says what stays",
          not promises_left_with_you(story) and "left open with you" in story and not promises_left_with_you(block), story)
    check("K-B1 NEGATIVE CONTROL: the line W2 shipped fails the same judgment",
          promises_left_with_you('it is listed in "Left with you" as not verified; delivery unchanged.'))

    # --- M-b: the closing sentence is true after an approval word ---------------------------------------------------------------
    tail = GB.exploratory_answer_block({"questions": [{"addressable": True, "case": "TC-006"}]})[-1]
    check("K-MB the closing sentence says where the helper does NOT read (an answer that starts with the approval word)",
          "unless your answer starts with the word that approves this gate" in tail and "only the lines in the form above are read" in tail, tail)
    check_eq("K-MB the closing line IS the shared constant (one definition for every answer block: the stand-gap block ends with it too, D6 golden)",
             tail, GB.APPROVAL_FIRST_LINE_TAIL)
    check("K-MB ... and the constant starts with the one sentence for 'anything else' (GW1-32)", GB.APPROVAL_FIRST_LINE_TAIL.startswith(GB.ANYTHING_ELSE_SENTENCE),
          GB.APPROVAL_FIRST_LINE_TAIL)
    task = question_story()
    try:
        drv = driver_of(task, GB.exploratory_shown(task))
        drv.gate_approval = lambda kind, words: SR.Driver.gate_approval(drv, kind, words)          # the REAL first-line reader
        free = "approve\nthe export 403 is fine as it is"
        check_eq("K-MB E1 approval word first, then free words: gate_approval is True and no question line is read - the sentence says so",
                 (drv.gate_approval("gate_B", free), drv.take_exploratory_answers("gate_B", free, "")), (True, {}))
        before_word = "TC-006: intended\napprove"
        check_eq("K-MB E2 a question line BEFORE the approval word: not an approval (the words go to the helper), the line is carried out",
                 (drv.gate_approval("gate_B", before_word), drv.take_exploratory_answers("gate_B", before_word, "")["recorded"]),
                 (False, ["TC-006: intended"]))
    finally:
        cleanup(task.parents[2])
    task = question_story()
    try:
        drv = driver_of(task, GB.exploratory_shown(task))
        drv.gate_approval = lambda kind, words: SR.Driver.gate_approval(drv, kind, words)
        after = "approve\nTC-006: intended\nthanks"
        out = drv.take_exploratory_answers("gate_B", after, "")
        check_eq("K-MB E3 approval word, then a question line: the line is carried out, nothing unread", (out["recorded"], out["unread"]),
                 (["TC-006: intended"], []))
    finally:
        cleanup(task.parents[2])

    # --- M-a: the `bug` rework carries the finding the person called wrong -------------------------------------------------------
    task = question_story()
    try:
        drv = driver_of(task, GB.exploratory_shown(task))
        out = drv.take_exploratory_answers("gate_B", "TC-006: bug", "")
        preface = drv.calls[0][2]
        text = " ".join(preface)
        check("K-MA the record's preface names the case, what was seen and before/now",
              len(preface) == 1 and all(needle in text for needle in ("TC-006", "the export for a viewer", "Seen: the export answered 403.",
                                                                       "Before the change: 400.", "Now: 403.")), text)
        check("K-MA ... in words: no register id, no question id", "EX-" not in text and not re.search(r"\bQ\d+\b", text), text)
    finally:
        cleanup(task.parents[2])
    unreadable = RF.exploratory_bug_preface("TC-007", {"title": "export for an admin", "statement": "  "}, None)
    check_eq("K-MA E4 a line whose statement cannot be read: 'not recorded', no invented before/now", unreadable,
            "The person called this finding a bug - TC-007: export for an admin. Seen: not recorded.")
    check("K-MA NEGATIVE CONTROL: a statement that exists is printed, so the check above can fail",
          "Seen: not recorded" not in RF.exploratory_bug_preface("TC-007", {"title": "t", "statement": "it broke"}, None))
    drv = object.__new__(SR.Driver)
    pending = {"stage": "S7", "role": "qa-failure-analyst", "cause": "question_answer", "cases": ["TC-006"], "words_file": "state/words/a.txt",
               "before": [], "preface": ["The person called this finding a bug - TC-006. Seen: the export answered 403."]}
    seen: list = []
    drv.dry, drv.owed_rework = False, lambda name: (pending, {})
    drv.rework_dispatches = lambda *a, **k: []
    drv.original_words = lambda rec: ("state/words/a.txt", "TC-006: bug\nthe 403 is wrong")
    drv.rework = lambda stage, role, cases, reason, **kw: seen.append((stage, role, cases, reason, kw)) or ("", "")
    drv.drop_record = lambda name: None
    check("K-MA the seam's rework reason = the code's preface, then the person's words VERBATIM (the words file still travels whole)",
          drv.seam_rework_step() and seen[0][3] == pending["preface"][0] + "\nTC-006: bug\nthe 403 is wrong"
          and seen[0][4]["words_file"] == "state/words/a.txt", str(seen))
    pending.pop("preface")
    seen.clear()
    drv.seam_rework_step()
    check_eq("K-MA control: a record with no preface (the conductor's own rework) sends the words alone", seen[0][3], "TC-006: bug\nthe 403 is wrong")

    # --- m-1 / m-3: the report's words ---------------------------------------------------------------------------------------------
    line = {"_status": "active", "kind": "observation", "statement": "s", "why_not_a_bug": "w", "verification_status": "unverified"}
    check_in("m-1 a confirmed line says it is confirmed for this finding only (the readiness question may stay open)",
             "for this finding only", RF._exploratory_item(dict(line, oracle_status="person_confirmed")))
    asked = dict(line, oracle_status="owner_question", question="Which status?")
    check("m-3 before gate B is decided the report asks the question; after it, it says 'left open with you'",
          "waits for your answer: Which status?" in RF._exploratory_item(asked, False)
          and "left open with you: Which status?" in RF._exploratory_item(asked, True)
          and "left open" not in RF._exploratory_item(asked, False))

    # --- m-2: a question left open at gate B is named once ----------------------------------------------------------------------------
    task = question_story()
    try:
        drv = driver_of(task, GB.exploratory_shown(task))
        drv.take_exploratory_answers("gate_B", "TC-006: open", "")
        parts = RF.exploratory_gate_parts(task)
        check_eq("m-2 the left-open question's id travels with the parts", parts["left_open_qids"], ["Q7"])
        check("m-2 control: 'Open before the MR' without the skip lists it as unanswered",
              any("Which status should a viewer get" in item for item in GB.open_before_mr(task)))
        packet = GB.render_gate_b("T-1", task)
        check("m-2 the re-shown gate B names it as left open and does not list it again as an unanswered question",
              "Left open by you at gate B, not asked again: TC-006" in packet and "Which status should a viewer get" not in packet, packet[:700])
    finally:
        cleanup(task.parents[2])

    # --- m-5: a quoted line is no answer in either reader ---------------------------------------------------------------------------
    gaps = [{"id": "TC-001", "case_id": "TC-001", "stage": "S9", "remedy": {}}]
    check_eq("m-5 stand-gap reader: a quoted line is neither read nor unread", GB.read_stand_gap_answers(">TC-001: accept", gaps)["read"], [])
    check_eq("m-5 control: the same line unquoted is read", [r["option"] for r in GB.read_stand_gap_answers("TC-001: accept", gaps)["read"]],
             ["accept"])
    check_eq("m-5 exploratory reader: a quoted line is no answer (the twin)", read(">TC-006: intended"), {"read": [], "unread": []})

    # --- m-6: a word of another reader on a question id that no stand-gap card answers is read by nobody -------------------------------
    check_eq("m-6 the id is no stand-gap card: unread, so it reaches the conductor",
             [u["line"] for u in GB.read_exploratory_answers("TC-006: manual", SHOWN, LIVE, card_ids=set())["unread"]], ["TC-006: manual"])
    check_eq("m-6 ... the id IS a card: the card's reader owns the word (neither here)",
             GB.read_exploratory_answers("TC-006: accept", SHOWN, LIVE, card_ids={"tc-006"}), {"read": [], "unread": []})
    task = question_story()
    try:
        drv = driver_of(task, GB.exploratory_shown(task))
        out = drv.take_exploratory_answers("gate_B", "TC-006: accept", "")
        check_eq("m-6 the driver: a story with no stand-gap card at gate B, `TC-006: accept`: the line is unread (not lost with the approval)",
                 out.get("unread"), ["TC-006: accept"])
    finally:
        cleanup(task.parents[2])


def main():
    for key in (key_packet, key_battery, key_edges, key_words, key_driver, key_overlap, key_w3):
        key()
    finish("test_exploratory_answers")


if __name__ == "__main__":
    main()
