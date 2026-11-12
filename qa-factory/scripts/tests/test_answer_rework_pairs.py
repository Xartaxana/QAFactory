"""HF3-10 (H41): a changed answer of the person reopens the rework - the two pure functions that decide it.

`Driver.answer_pairs_owed(item, findings)`: the part of a queued rework (`state["answer_rework"]` item) still owed. An item
carries `pairs` - (question, row or case) as the branch check saw them when the rework was named (`seen`). The check's
silence about a pair it never saw is not proof that the work is done (the code patched the branch off for the first answer):
only a SEEN pair the check no longer names is dropped. Keys A1-A8.

`Driver.answer_supersede(items, current)`: the part of the unstarted items that waits for an answer the person has since
replaced is taken out, never sent. Keys S1-S6.

Both are pure and need no driver, no task root and no network.
"""
import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import check, check_eq  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import story_run  # noqa: E402

owed, supersede = story_run.Driver.answer_pairs_owed, story_run.Driver.answer_supersede


def pair(question: str, where: str, seen=False) -> dict:
    return {"question": question, "where": where, "seen": seen}


def ask(qid: str, answer: str = "b", at: str = "t1", **more) -> dict:
    return dict({"id": qid, "answer": answer, "record_at": at}, **more)


def item(rows=(), cases=(), questions=(), pairs=None, stage: str = "S3") -> dict:
    out = {"stage": stage, "role": "qa-test-strategist" if stage == "S3" else "qa-case-designer", "rows": list(rows),
           "cases": list(cases), "questions": list(questions), "words_file": "", "before": []}
    if pairs is not None:
        out["pairs"] = list(pairs)
    return out


def finding(question: str, where: str) -> dict:
    return {"check": "question_branches", "question": question, "where": where, "kind": "settled_question"}


def shape(got):
    return None if got is None else (got["rows"], got["cases"], [a["id"] for a in got["questions"]])


def pairs_owed() -> None:
    one = item(rows=["TS-3"], questions=[ask("Q5")], pairs=[pair("Q5", "TS-3", False)])
    check_eq("A1: a pair the check did not see, and no finding: the row is still owed (the old rule dropped it)",
             shape(owed(one, [])), (["TS-3"], [], ["Q5"]))
    seen = item(rows=["TS-3"], questions=[ask("Q5")], pairs=[pair("Q5", "TS-3", True)])
    check_eq("A2: a pair the check saw and no longer names: nothing is owed (H41 kept)", owed(seen, []), None)
    check_eq("A3: a pair the check saw and still names: owed", shape(owed(seen, [finding("Q5", "TS-3")])), (["TS-3"], [], ["Q5"]))
    check_eq("A4: findings None (the check could not be read): the item as it is",
             owed(copy.deepcopy(one), None), one)
    check_eq("A4b: findings None keeps a SEEN pair the check no longer names (an unread check never drops work, FR-59; kills M3, None read as [])",
             owed(copy.deepcopy(seen), None), seen)
    bare = item(rows=["TS-3", "TS-10"], cases=["TC-011"], questions=[ask("Q5")])
    check_eq("A5: an item of an older state (no pairs), no findings: every row and case is owed",
             shape(owed(bare, [])), (["TS-3", "TS-10"], ["TC-011"], ["Q5"]))
    mixed = item(rows=["TS-3", "TS-4"], questions=[ask("Q5"), ask("Q1", "a")],
                 pairs=[pair("Q5", "TS-3", False), pair("Q1", "TS-4", True)])
    check_eq("A6: one row unseen, one seen and gone: the unseen row and its question stay",
             shape(owed(mixed, [])), (["TS-3"], [], ["Q5"]))
    check_eq("A7: `seen` that is not a bool is read as unseen",
             shape(owed(item(rows=["TS-3"], questions=[ask("Q5")], pairs=[pair("Q5", "TS-3", "yes")]), [])),
             (["TS-3"], [], ["Q5"]))
    check_eq("A7: nor is 1 a True",
             shape(owed(item(rows=["TS-3"], questions=[ask("Q5")], pairs=[pair("Q5", "TS-3", 1)]), [])), (["TS-3"], [], ["Q5"]))
    odd = item(rows=["TS-3"], questions=[ask("Q5")], pairs=[pair("Q1", "TS-9", True)])
    check_eq("A8: rows are owed and no question has a pair at them: the item's questions stay whole",
             shape(owed(odd, [])), (["TS-3"], [], ["Q5"]))
    cases = item(cases=["TC-011", "TC-012"], questions=[ask("Q5", "a")], stage="S4",
                 pairs=[pair("Q5", "TC-011", True), pair("Q5", "TC-012", True)])
    check_eq("A3b: the cases are judged the same way: one still named, one done",
             shape(owed(cases, [finding("Q5", "TC-012")])), ([], ["TC-012"], ["Q5"]))
    check_eq("A9: a finding for another question does not keep a seen pair", owed(seen, [finding("Q1", "TS-3")]), None)
    check_eq("A9: nor does a finding on another row", owed(seen, [finding("Q5", "TS-7")]), None)
    check_eq("A10: a finding that is no dict is ignored, the seen pair is dropped", owed(seen, ["oops", None]), None)
    check_eq("A10: pairs that are no dicts are ignored: the row has no pair, so it is owed",
             shape(owed(item(rows=["TS-3"], questions=[ask("Q5")], pairs=["x", None]), [])), (["TS-3"], [], ["Q5"]))
    before = copy.deepcopy(mixed)
    owed(mixed, [])
    check_eq("A11: the input item is not changed", mixed, before)
    two = item(rows=["TS-3"], questions=[ask("Q5"), ask("Q1", "a")],
               pairs=[pair("Q5", "TS-3", True), pair("Q1", "TS-3", False)])
    check_eq("A12: a row with two pairs, one seen and gone and one unseen: owed, and only the question with the owed pair is told (F5)",
             shape(owed(two, [])), (["TS-3"], [], ["Q1"]))
    check_eq("A12b: the question whose pair is done is told again once the check names it",
             shape(owed(two, [finding("Q5", "TS-3")])), (["TS-3"], [], ["Q5", "Q1"]))
    check_eq("A13: no rows, no cases: nothing to do", owed(item(questions=[ask("Q5")]), []), None)


def supersession() -> None:
    queued = item(rows=["TS-3", "TS-10"], questions=[ask("Q5", "b")],
                  pairs=[pair("Q5", "TS-3"), pair("Q5", "TS-10")])
    check_eq("S1: the person now says `a`: an item waiting for `b` is gone", supersede([queued], {"Q5": "a"}), [])
    check_eq("S2: the person still says `b`: nothing changes", supersede([queued], {"Q5": "b"}), [queued])
    both = item(rows=["TS-3", "TS-4"], questions=[ask("Q5", "b"), ask("Q1", "b")],
                pairs=[pair("Q5", "TS-3"), pair("Q1", "TS-4")])
    got = supersede([both], {"Q5": "a"})
    check_eq("S3: another question's work stays, with its row and pair; the replaced one's row goes",
             (len(got), got[0]["rows"], [a["id"] for a in got[0]["questions"]], got[0]["pairs"]),
             (1, ["TS-4"], ["Q1"], [pair("Q1", "TS-4")]))
    check_eq("S4: no current answers: the input", supersede([queued], {}), [queued])
    check_eq("S4: an id the item does not hold: the item is the same by value", supersede([queued], {"Q9": "a"}), [queued])
    check_eq("S4: `current` that is no dict: the input", supersede([queued], None), [queued])
    older = item(rows=["TS-3"], questions=[ask("Q5", "b"), ask("Q1", "b")])
    got = supersede([older], {"Q5": "a"})
    check_eq("S5: an item with no pairs: the replaced question goes, the rows stay", (got[0]["rows"], [a["id"] for a in got[0]["questions"]]),
             (["TS-3"], ["Q1"]))
    check_eq("S5: and with no question left the item goes", supersede([item(rows=["TS-3"], questions=[ask("Q5", "b")])], {"Q5": "a"}), [])
    s4 = item(cases=["TC-011"], questions=[ask("Q5", "b")], stage="S4", pairs=[pair("Q5", "TC-011")])
    items = [queued, s4]
    frozen = copy.deepcopy(items)
    check_eq("S6: both owners' items are replaced", supersede(items, {"Q5": "a"}), [])
    check_eq("S6: and the input list and its items are not changed", items, frozen)
    keep = item(rows=["TS-3"], questions=[ask("Q5", "b"), ask("Q5", "a", "t2")], pairs=[pair("Q5", "TS-3")])
    got = supersede([keep], {"Q5": "a"})
    check_eq("S7: an item that holds the current answer too keeps that question and its pair",
             (got[0]["rows"], got[0]["questions"], got[0]["pairs"]), (["TS-3"], [ask("Q5", "a", "t2")], [pair("Q5", "TS-3")]))
    own_words = item(rows=["TS-3"], questions=[ask("Q5", "")], pairs=[pair("Q5", "TS-3")])
    check_eq("S8: an answer in words is an answer: `a` replaces it, and words replace `a`",
             (supersede([own_words], {"Q5": "a"}), supersede([item(rows=["TS-3"], questions=[ask("Q5", "a")], pairs=[pair("Q5", "TS-3")])],
                                                              {"Q5": ""})), ([], []))
    words = item(rows=["TS-3"], questions=[ask("Q5", "", "t1")], pairs=[pair("Q5", "TS-3")])
    check_eq("S9: own words given again (another record): the earlier words go, one line is left for the question (F6)",
             supersede([words], {"Q5": ""}, {"Q5": "t2"}), [])
    check_eq("S9: the same record of the words: kept", supersede([words], {"Q5": ""}, {"Q5": "t1"}), [words])
    check_eq("S9: no record named for the words (an older caller, an unknown record): equal answers are the same answer",
             (supersede([words], {"Q5": ""}), supersede([words], {"Q5": ""}, {"Q5": ""}), supersede([words], {"Q5": ""}, {})),
             ([words], [words], [words]))
    letter = item(rows=["TS-3"], questions=[ask("Q5", "a", "t1")], pairs=[pair("Q5", "TS-3")])
    check_eq("S9: the record decides only for words: a lettered answer with another record is the same answer",
             supersede([letter], {"Q5": "a"}, {"Q5": "t2"}), [letter])
    both = item(rows=["TS-3"], questions=[ask("Q5", "", "t1"), ask("Q5", "", "t2")], pairs=[pair("Q5", "TS-3")])
    check_eq("S9: of two words records only the current one stays", [a["record_at"] for a in supersede([both], {"Q5": ""}, {"Q5": "t2"})[0]["questions"]],
             ["t2"])


if __name__ == "__main__":
    pairs_owed()
    supersession()
    check("the two functions are static (callable with no driver)", isinstance(story_run.Driver.__dict__["answer_pairs_owed"], staticmethod)
          and isinstance(story_run.Driver.__dict__["answer_supersede"], staticmethod))
    harness.finish("test_answer_rework_pairs")
