#!/usr/bin/env python3
"""RH1-6 A3: the driver tells the truth over a gate A approval the controller refused for open items, and hands `approve as is` on.

The controller records a gate A approval only over `person_decides` items the person has worded (the owner's F-2, 27.10.2026). Before
this, the driver told the conductor "words that are not the approval word" and the person "the factory's to repair" over such a
refusal - a lie about whose it was. These tests drive the driver's own functions on a bare `Driver` (no run, no paid call)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import SCRIPTS, check, check_eq, check_in, check_not_in, finish  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import story_run as SR  # noqa: E402

ITEMS = [
    {"id": "fx-1", "check": "fx", "message": "a line item", "door": {"kind": "line", "says": "write the line", "block": "stand gap: TC-1",
                                                                     "stage": "S5", "waives": []}},
    {"id": "fx-2", "check": "fx", "message": "a words item", "door": {"kind": "words", "says": "say it", "block": "a words item block",
                                                                      "stage": "S5", "waives": []}},
    {"id": "fx-3", "check": "fx", "message": "a doorless item", "door": {"kind": "none", "says": "say it", "block": "", "stage": "", "waives": []}},
]
WORDS = "approve\nbut go on without the toolchain, TC-1 as blocked"


def refusal(items=ITEMS, **extra):
    return json.dumps(dict({"recorded": False, "problems": ["[fx-1] a line item - needs your word: write the line"],
                            "open_items": items, "request": {}}, **extra))


def driver(text=""):
    d = SR.Driver.__new__(SR.Driver)
    d.gate_refusal = text
    d.scripts = Path("/pkg/scripts")
    d.task = "QA-1"
    d.dry = True
    d.state = {}
    d.question_lines_note, d.question_lines_shown = "", ""      # GW1-34: what `__init__` sets and `kept_answer_text` reads
    return d


def k15_the_conductor_prompt_says_heard_and_kept_and_gives_a_command_per_item():
    d = driver(refusal())
    prompts = []
    d.save_state = lambda: None
    d.controller_state = lambda: {}
    d.judged_reply = lambda *a, **k: ""
    d.unread = lambda kind, stage, dispatch, prompt, **kw: prompts.append(prompt)
    d._unread_kept_gate("gate_A", "S4", "", "the gate question", WORDS, "")
    prompt = prompts[0]
    check_in("A-K15 the approval was heard and kept", "approval word was heard and kept", prompt)
    check_not_in("A-K15 and the old lie about the answer is gone", "words that are not the approval", prompt)
    check_in("A-K15 a `line` item gets its recording command", '--block "stand gap: TC-1"', prompt)
    check_in("A-K15 a `words` item gets its recording command", '--block "a words item block"', prompt)
    check_in("A-K15 both by file, the one renderer (`person_words.door`)", "--words-file <file>", prompt)
    check_in("A-K15 the `none` item names the closed word", "only the person's `approve as is` passes it", prompt)
    check_in("A-K19 the whole words are in the prompt", WORDS, prompt)
    check_not_in("A-K15 no `*` block is offered for these items", '--block "*"', prompt.replace('never record `--block "*"`', ""))
    # A-K18: a non-approval answer keeps today's prompt byte for byte
    check_eq("A-K18 a non-approval answer: today's generic prompt", driver(refusal()).generic_prompt("gate_A", "S4", "q"),
             SR.Driver.generic_prompt("gate_A", "S4", "q"))
    check_in("A-K18 ... which still says it is not the approval word", "words that are not the approval word", SR.Driver.generic_prompt("gate_A", "S4", "q"))
    plain = []
    d2 = driver(refusal())
    d2.save_state, d2.controller_state, d2.judged_reply = (lambda: None), (lambda: {}), (lambda *a, **k: "")
    d2.unread = lambda kind, stage, dispatch, prompt, **kw: plain.append(prompt)
    d2._unread_kept_gate("gate_A", "S4", "", "q", "change the plan first", "")
    check_in("A-K18 the driver's own call with a non-approval answer", "words that are not the approval word", plain[0])


def k16_k17_the_kept_text_names_its_owner_only_when_it_can_read_it():
    kept = {"gate": "A", "words": WORDS, "at": "2026-10-28T10:00:00"}
    text = driver(refusal()).kept_answer_text(kept)
    check_not_in("A-K16 over items: no \"factory's to repair\"", "factory's to repair", text)
    check_in("A-K16 it names the item", "fx-1", text)
    check_in("A-K16 and the closed word", "`approve as is`", text)
    plain = driver(json.dumps({"recorded": False, "problems": ["a factory problem"], "request": {}})).kept_answer_text(kept)
    check_in("A-E12 a readable refusal with no items is the factory's, as before", "factory's to repair", plain)
    for label, bad in (("no JSON at all", "the controller said something odd"), ("nothing", ""), ("a JSON list", "[1, 2]")):
        text = driver(bad).kept_answer_text(kept)
        check_not_in(f"A-K17 {label}: no owner is named", "factory's to repair", text)
        check_in(f"A-K17 {label}: neutral text", "not known whose to repair", text)
    check_eq("A-K17 JSON preceded by a stdout line is READ", len(SR.Driver.gate_open_items("gate A: noted\n" + refusal())), 3)
    check_eq("A-K17 no `open_items` key: unreadable", SR.Driver.gate_open_items(json.dumps({"recorded": False, "problems": []})), None)
    check_eq("A-K17 an item that is not an object: unreadable", SR.Driver.gate_open_items(json.dumps({"open_items": ["x"]})), None)


def k22_k27_k28_the_as_is_word_is_a_closed_word_and_reaches_the_controller_as_a_flag():
    d = driver()
    check_eq("A-K27 `approve as is` is gate A's approval", d.gate_approval("gate_A", "approve as is"), True)
    check_eq("A-K27 and the as-is word", d.as_is_word("gate_A", "approve as is"), True)
    check_eq("A-K27 `approve` is an approval, not the as-is word", (d.gate_approval("gate_A", "approve"), d.as_is_word("gate_A", "approve")), (True, False))
    check_eq("A-K22 `approve as is, but fix X` is not the word", (d.gate_approval("gate_A", "approve as is, but fix X"),
                                                                 d.as_is_word("gate_A", "approve as is, but fix X")), (False, False))
    check_eq("A-E15 at gate B it is not a word", (d.gate_approval("gate_B", "approve as is"), d.as_is_word("gate_B", "approve as is")), (False, False))
    check_eq("A-E15 the first line decides, case and a stop are the normalizer's", d.as_is_word("gate_A", "Approve As Is.\nplease"), True)
    argv = []

    def run(kind, words):
        del argv[:]
        e = driver()
        e.py = lambda *a: argv.append(list(a)) or (0, "")
        e.words_args = lambda words, name: ["--words", words]
        e.report_attribution = lambda gate, words: None
        e.task_root = Path("/story")
        check(f"A-K28 {words!r} records", e.record_by_code(kind, "S4", words))
        return argv[0]
    check_in("A-K28 `approve as is` passes --as-is", "--as-is", run("gate_A", "approve as is"))
    check_not_in("A-K28 `approve` does not", "--as-is", run("gate_A", "approve"))


def m2_factory_sentences_and_item_sentences_are_told_apart():
    """M2 / A-K9 (driver side): the controller marks where the items' sentences start; the driver prints the factory's own under their
    own heading, offers `approve as is` only when there are none, and never slices the list by a count of items."""
    kept = {"gate": "A", "words": WORDS, "at": "2026-10-28T10:00:00"}
    factory = [f"factory sentence {n}" for n in range(1, 6)]            # more than the old `len(items) + 3` slice kept
    items = ITEMS[:1]
    sentences = factory + ["[fx-1] a line item - needs your word: write the line",
                           "Your approval is kept; it records once each item above has your word."]
    mixed = refusal(items, problems=sentences, item_problems_from=len(factory))
    text = driver(mixed).kept_answer_text(kept)
    check_in("A-K9 the factory's heading", "the factory's own to repair", text)
    check_eq("A-K9 all five factory sentences are printed (no slice by item count)", sum(f"- factory sentence {n}" in text for n in range(1, 6)), 5)
    check_in("A-K9 and the item sentence", "- [fx-1] a line item", text)
    check("A-K9 the factory sentences come before the items", text.index("factory sentence 1") < text.index("[fx-1]"))
    check_not_in("A-K9 no `approve as is` is offered while factory problems stand", "approve as is", text)
    clean = driver(refusal(items, problems=sentences[len(factory):], item_problems_from=0)).kept_answer_text(kept)
    check_in("A-K9 control: with no factory sentence it is offered", "`approve as is`", clean)
    check_not_in("A-K9 control: and no factory heading", "the factory's own to repair", clean)
    check_eq("A-K9 an older record (no mark): every sentence is the items'",
             SR.Driver.gate_refusal_parts(json.dumps({"problems": ["a", "b"], "open_items": ITEMS})), ([], ["a", "b"]))
    check_eq("A-K9 a mark beyond the list or not a number: every sentence is the items'",
             [SR.Driver.gate_refusal_parts(json.dumps({"problems": ["a"], "item_problems_from": bad}))[0] for bad in (5, -1, "1", True, None)],
             [[]] * 5)
    prompts = []
    d = driver(mixed)
    d.save_state, d.controller_state, d.judged_reply = (lambda: None), (lambda: {}), (lambda *a, **k: "")
    d.unread = lambda kind, stage, dispatch, prompt, **kw: prompts.append(prompt)
    d._unread_kept_gate("gate_A", "S4", "", "the gate question", "approve", "")
    check_in("A-K9 the conductor sees the factory's sentences under their own owner", "The factory's own problems", prompts[0])
    check_not_in("A-K9 and is not told `approve as is` passes the item", "only the person's `approve as is` passes it", prompts[0])


def m4_one_first_line_reader():
    d = driver()
    check_eq("M4 the first non-empty line, normalised, after a BOM and blank lines", d.first_line("﻿\n\n  Approve As Is.  \nmore"), "approve as is")
    check_eq("M4 empty answers read as empty", (d.first_line(""), d.first_line(None)), ("", ""))


def main():
    m2_factory_sentences_and_item_sentences_are_told_apart()
    m4_one_first_line_reader()
    k15_the_conductor_prompt_says_heard_and_kept_and_gives_a_command_per_item()
    k16_k17_the_kept_text_names_its_owner_only_when_it_can_read_it()
    k22_k27_k28_the_as_is_word_is_a_closed_word_and_reaches_the_controller_as_a_flag()
    finish("test_gate_open_items")


if __name__ == "__main__":
    main()
