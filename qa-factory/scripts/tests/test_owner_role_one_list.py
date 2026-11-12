#!/usr/bin/env python3
"""t-2277 small-1 D (test-diet 2): the owner words of an open question are ONE closed list in data (`question_owners` of
`handoffs/vocabulary.yaml`, FR-13), read through one reader (`planning_contract.question_owners`, over `handoff.allowed`) by both
callers: `check_witness._readiness_form` (an `open_questions[]` row of requirements-readiness.json) and
`planning_contract._new_question_flaws` (a `new_questions` entry of an S3 plan row).

  D1  the reader gives the vocabulary's words (po_ba, dev_arch, qa) - no copy in either caller.
  D2  both callers accept every listed word and refuse an unlisted one, with the SAME door sentence (`owner_role_flaw`).
  D3  an EMPTY owner_role: `_new_question_flaws` keeps its own `owner_role is empty` (and no second sentence); the readiness form
      keeps refusing the row with its form line (no door sentence added for an empty value). Today's behaviour in each caller.
  D4  an unreadable vocabulary is a named package defect in both callers, never a pass (AR-28).
KILLS: a hand list back in either caller; an unlisted word accepted by `_new_question_flaws`; a different sentence in one caller.
"""
import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import check, check_eq, finish  # noqa: E402

sys.path.insert(0, str(harness.SCRIPTS))
import check_witness as CW  # noqa: E402
import planning_contract as PC  # noqa: E402

OWNERS = ("po_ba", "dev_arch", "qa")


def entry(owner):
    return {"question": "Which total is shown?", "source_says": [{"quote": "q", "where": "w"}],
            "readings": [{"reading": "a", "from": "x", "if_chosen": "y"}, {"reading": "b", "from": "x", "if_chosen": "z"}],
            "severity": "major", "owner_role": owner}


def readiness_lines(owner):
    return CW._readiness_form({"verdict": "ready", "goal_summary": "g" * 40, "aspects": {"a": {"status": "ready"}},
                               "open_questions": [{"question": "q?", "severity": "major", "owner_role": owner}]})


def owner_lines(lines):
    return [line for line in lines if "open_questions[0]" in line]


def test_one_list_in_data():
    check_eq("D1: the reader returns the vocabulary's words", PC.question_owners(), OWNERS)


def test_both_callers_accept_listed_and_refuse_unlisted_with_one_sentence():
    for word in OWNERS:
        check_eq(f"D2: readiness form accepts {word}", owner_lines(readiness_lines(word)), [])
        check_eq(f"D2: new_questions entry accepts {word}", [f for f in PC._new_question_flaws(entry(word)) if "owner_role" in f], [])
    door = PC.owner_role_flaw("manager")
    check("D2: the door sentence names the word and the list", "'manager'" in door and "po_ba|dev_arch|qa" in door, door)
    check("D2: readiness form refuses an unlisted word with the door sentence", any(door in line for line in readiness_lines("manager")),
          str(readiness_lines("manager")))
    check("D2: new_questions entry refuses an unlisted word with the SAME sentence", door in PC._new_question_flaws(entry("manager")),
          str(PC._new_question_flaws(entry("manager"))))


def test_empty_owner_keeps_each_callers_behaviour():
    flaws = [f for f in PC._new_question_flaws(entry("")) if "owner_role" in f]
    check_eq("D3: an empty owner_role in a new_questions entry is `owner_role is empty` only", flaws, ["owner_role is empty"])
    lines = owner_lines(readiness_lines(""))
    check("D3: an empty owner_role in the readiness form is still refused, by the form line alone",
          len(lines) == 1 and "needs question, severity" in lines[0] and "is not one of" not in lines[0], str(lines))


def test_unreadable_vocabulary_is_named_not_passed():
    with mock.patch("handoff.allowed", side_effect=OSError("gone")):
        check_eq("D4: unreadable -> no words", PC.question_owners(), ())
        check("D4: a new_questions entry is refused naming the defect",
              any("cannot be checked" in f for f in PC._new_question_flaws(entry("qa"))), str(PC._new_question_flaws(entry("qa"))))
        check("D4: the readiness row is refused", len(owner_lines(readiness_lines("qa"))) == 1, str(readiness_lines("qa")))


def main():
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    finish("test_owner_role_one_list")


if __name__ == "__main__":
    main()
