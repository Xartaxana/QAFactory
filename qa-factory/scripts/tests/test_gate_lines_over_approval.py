#!/usr/bin/env python3
"""GW1-33 (release 0.10.8): a gate answer that opens with the approval word and then answers the packet's items in their own
forms is put to the controller, not sent whole to the conductor because some of those lines could not be read.

Run 14857 (RL-4:8): `approve`, `vcs-1: go on on this branch`, `case_environment-1: accept the gap` - "9 lines of the answer look like a
stand-gap answer and could not be read; the answer goes to the conductor". Before this change one unread line in `stand["unread"]`
kept `take_answer` from calling `record_by_code`. Now `Driver.gate_lines_over_approval` lets the call be made when the answer IS the
approval word on GATE A (t-550 F1: gate B's controller call has no open-items net) and none of the unread lines is the exploratory
reader's or held (`stand["hold"]`, t-550 F2: a refused record, an `ask again`, a line with `?`); the gate A controller still refuses an
approval over an open item (then the old road: the whole answer kept for the conductor), and the unread lines are told as "not
understood", twenty at most.

Keys: s1 step 1, the reproduction (the real reader leaves the RL-4:8 lines unread); g1 the truth table of the function; t1 the lines
ride the approval and are told (20 and 21 lines); t2 an exploratory `bug` beside `approve` goes to the conductor; t3 the controller
refuses (stub and the real one): the old road, nothing told as understood; t4 `approve` not on the first line; t5 a gate with no
unread line is untouched; t6 `approve as is` reaches the controller with its flag (the road of the driver); t7 gate B
`delivery-1: deliver with known gaps` is a line the reader leaves unread and it is KEPT for the conductor (t-550 F1); t8 the reader's
`hold` list (a refused record, `ask again`, a line with `?`) and a held line keeps the approval on gate A.
"""
import contextlib
import io
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import check, check_eq, check_in, check_not_in  # noqa: E402
from story_run_common import driver_for, seed  # noqa: E402

TASK = "QA-9"
RL4 = "approve\nvcs-1: go on on this branch\ncase_environment-1: accept the gap"
FINDINGS = [{"id": "vcs-1", "message": "the branch has no remote", "waives": [{"block": "vcs", "stage": "S9", "option": "accept"}]},
            {"id": "case_environment-1", "message": "TS-14 declares a gap", "waives": []}]


class Rig:
    """A seeded project and a Driver over it; the readers and the executors are replaced by recorders, `log` is what happened."""

    def __init__(self, kind="gate_A", stand=None, asked_lines=None, record=True):
        self.root, self.task_root, self.env = seed(TASK)
        self.d = driver_for(self.root, self.env, TASK)
        self.log, self.rows = [], []
        self.kind, self.stage = kind, ("S4" if kind == "gate_A" else "S8")
        d = self.d
        d.take_stand_gap_answers = lambda *a, **k: stand if stand is not None else {}
        d.take_exploratory_answers = lambda *a, **k: asked_lines if asked_lines is not None else {}
        d.record_by_code = lambda kind, stage, words, **k: self.log.append(("record", words)) or record
        d._unread_kept_gate = lambda *a, **k: self.log.append(("kept", a[4]))
        d.answer_row = lambda prefix, words, **k: self.rows.append((prefix, words))

    def take(self, words: str) -> str:
        d = self.d
        d.state["asked"] = {"kind": self.kind, "stage": self.stage, "dispatch": ""}
        d.save_state()
        (self.task_root / "state" / "driver-question.md").write_text(
            f"# Driver question\nkind: {self.kind}\nstage: {self.stage}\n\nthe gate\n", encoding="utf-8")
        answer = self.root / "answer.md"
        answer.write_bytes(words.encode("utf-8"))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            d.take_answer(answer)
        return out.getvalue()

    def close(self) -> None:
        os.chdir(harness.PLUGIN_ROOT)       # the Driver chdirs into the project
        harness.cleanup(self.root)


def stand_of(lines, note="n"):
    return {"recorded": [], "unread": list(lines), "note": note}


def s1_reproduction() -> None:
    """Step 1: the real stand-gap reader, with the findings of RL-4:8 in the rehearsal, leaves BOTH lines in `stand["unread"]` and holds
    none. At gate A the function lets the controller be asked (the controller then refuses over the open items: the old road); at gate B
    it does not (t-550 F1: `open_gate_items` has no net there)."""
    root, _task_root, env = seed(TASK)
    try:
        d = driver_for(root, env, TASK)
        d.rehearse = lambda gate: {"findings": FINDINGS, "stand_gaps": []}
        for kind in ("gate_A", "gate_B"):
            with contextlib.redirect_stdout(io.StringIO()):
                stand = d.take_stand_gap_answers(kind, RL4, "", "S4", "")
            check_eq(f"s1 {kind}: both RL-4:8 lines are unread by the real reader",
                     stand.get("unread"), ["vcs-1: go on on this branch", "case_environment-1: accept the gap"])
            check(f"s1 {kind}: and the answer is the approval word", d.gate_approval(kind, RL4))
            check_eq(f"s1 {kind}: nothing is held", stand.get("hold"), [])
            check_eq(f"s1 {kind}: the function lets the controller be asked at gate A only",
                     d.gate_lines_over_approval(kind, RL4, stand, []), kind == "gate_A")
    finally:
        os.chdir(harness.PLUGIN_ROOT)
        harness.cleanup(root)


def g1_truth_table() -> None:
    root, _task_root, env = seed(TASK)
    try:
        d = driver_for(root, env, TASK)
        one = stand_of(["TC-1: maybe"])
        held = {**stand_of(["TC-1: accept", "TC-2: maybe"]), "hold": ["TC-1: accept"]}
        cases = [("approval + stand-gap unread line", ("gate_A", "approve\nTC-1: maybe", one, []), True),
                 ("gate B: no net there, kept", ("gate_B", "approve\nTC-1: maybe", one, []), False),
                 ("a refused record is held", ("gate_A", "approve\nTC-1: accept", held, []), False),
                 ("a held line beside a plain one", ("gate_A", "approve\nTC-1: accept\nTC-2: maybe", held, []), False),
                 ("no unread line", ("gate_A", "approve", stand_of([]), []), False),
                 ("an empty stand", ("gate_A", "approve", {}, []), False),
                 ("stand None", ("gate_A", "approve", None, []), False),
                 ("the exploratory reader's unread line", ("gate_B", "approve\nTC-1: bug", stand_of(["TC-1: bug"]), ["TC-1: bug"]), False),
                 ("stand-gap line + exploratory line", ("gate_B", "approve", stand_of(["TC-1: maybe", "TC-2: bug"]), ["TC-2: bug"]), False),
                 ("not the approval word", ("gate_A", "approve, but fix X\nTC-1: maybe", one, []), False),
                 ("approval word on a later line", ("gate_A", "thanks\napprove\nTC-1: maybe", one, []), False),
                 ("a kind that is no gate", ("conductor", "approve\nTC-1: maybe", one, []), False),
                 ("the word is not an approval", ("gate_A", "do not approve\nTC-1: maybe", one, []), False)]
        for label, args, want in cases:
            check_eq(f"g1 {label}", d.gate_lines_over_approval(*args), want)
    finally:
        os.chdir(harness.PLUGIN_ROOT)
        harness.cleanup(root)


def t1_lines_ride_the_approval() -> None:
    for count, kind in ((2, "gate_A"), (20, "gate_A"), (21, "gate_A"), (25, "gate_A")):
        lines = [f"item-{i}: go on" for i in range(1, count + 1)]
        rig = Rig(kind, stand=stand_of(lines))
        try:
            words = "approve\n" + "\n".join(lines)
            out = rig.take(words)
            label = f"t1 {kind}, {count} unread lines"
            check_eq(f"{label}: the controller is asked with the whole answer, the conductor is not", rig.log, [("record", words)])
            check_in(f"{label}: told as not understood", "were not understood and are not applied", out)
            check_not_in(f"{label}: and never as accepted or applied", "accepted", out)
            printed = [row for row in out.splitlines() if row.startswith("  - ")]
            check_eq(f"{label}: at most 20 lines are printed", len(printed), min(count, 20))
            if count > 20:
                check_in(f"{label}: the rest is counted", f"... and {count - 20} more", out)
                check_not_in(f"{label}: the 21st line is not printed", lines[20], out)
            else:
                check_not_in(f"{label}: nothing is cut", "more", out)
            check_eq(f"{label}: the answer's row holds every unread line, whole", rig.rows,
                     [(f"{rig.stage} {kind} lines not understood: ", "\n".join(lines))])
        finally:
            rig.close()


def t2_exploratory_bug_with_approval() -> None:
    bug = "TC-3: bug"
    asked = {"recorded": [], "unread": [bug], "note": "\n\n## Question lines of the findings\n- not read: TC-3: bug (a bug answer and the approval word)\n"}
    rig = Rig("gate_B", stand=stand_of(["vcs-1: go on", bug]), asked_lines=asked)    # gate B: kept for the conductor either way
    try:
        # take_answer merges the exploratory reader's lines into the stand: the stub of the stand reader returns the stand-gap
        # line alone, the merge adds `bug`
        rig.d.take_stand_gap_answers = lambda *a, **k: stand_of(["vcs-1: go on"])
        rig.take(f"approve\nvcs-1: go on\n{bug}")
        check_eq("t2: the exploratory `bug` beside `approve` goes to the conductor: no record by code, the whole answer kept",
                 [entry[0] for entry in rig.log], ["kept"])
        check_eq("t2: and nothing is told as not understood", rig.rows, [])
    finally:
        rig.close()


def t3_controller_refuses() -> None:
    lines = ["vcs-1: go on on this branch", "case_environment-1: accept the gap"]
    words = "approve\n" + "\n".join(lines)
    rig = Rig("gate_A", stand=stand_of(lines), record=False)
    try:
        out = rig.take(words)
        check_eq("t3 (stub): the controller is asked, refuses, and the whole answer is kept for the conductor - the old road",
                 [entry[0] for entry in rig.log], ["record", "kept"])
        check_eq("t3 (stub): the kept words are the person's whole answer", rig.log[-1][1], words)
        check_not_in("t3 (stub): nothing is told as not understood-and-recorded", "not understood", out)
        check_eq("t3 (stub): no row of unread lines", rig.rows, [])
    finally:
        rig.close()
    # the real record_by_code and the real controller of a bare story: the gate is not reachable there, the controller refuses, and the
    # answer takes the same old road (the line `gate A: the decision did not record by code`)
    rig = Rig("gate_A", stand=stand_of(lines))
    try:
        del rig.d.record_by_code            # back to the class's method
        rig.d.report_attribution = lambda gate, w: {}
        out = rig.take(words)
        check_in("t3 (real controller): the controller refused", "the decision did not record by code", out)
        check_eq("t3 (real controller): and the answer went the old road", [entry[0] for entry in rig.log], ["kept"])
        check_eq("t3 (real controller): no row of unread lines", rig.rows, [])
    finally:
        rig.close()


def t4_approve_not_on_the_first_line() -> None:
    lines = ["vcs-1: go on on this branch"]
    rig = Rig("gate_A", stand=stand_of(lines))
    try:
        rig.take("vcs-1: go on on this branch\napprove")
        check_eq("t4: `approve` on a later line is no approval: the unread line sends the answer to the conductor, as before",
                 [entry[0] for entry in rig.log], ["kept"])
    finally:
        rig.close()


def t5_no_unread_line_is_untouched() -> None:
    rig = Rig("gate_A", stand=stand_of([]))
    try:
        out = rig.take("approve\nthe export test is fine")
        check_eq("t5: no unread line: recorded by code as always, nothing told", (rig.log, rig.rows), ([("record", "approve\nthe export test is fine")], []))
        check_not_in("t5: no 'not understood' text", "not understood", out)
    finally:
        rig.close()


def t6_approve_as_is_reaches_the_controller_with_its_flag() -> None:
    """The half of the finding that is already true (spec A11): `approve as is` is one closed word of gate A, read by `as_is_word`, and
    the driver's road declares it to the controller by `--as-is`. A stub of `py` records the call."""
    root, _task_root, env = seed(TASK)
    try:
        d = driver_for(root, env, TASK)
        calls = []
        d.py = lambda script, *args, **k: calls.append((script, list(args))) or (0, "{}")
        d.gate_answer_told = lambda gate, out: None
        d.report_attribution = lambda gate, words: {}
        d.shown_packet = lambda kind: ""
        for words, flag in (("approve as is", True), ("approve", False), ("approve as is, but fix X", False)):
            calls.clear()
            with contextlib.redirect_stdout(io.StringIO()):
                ok = d.record_by_code("gate_A", "S4", words)
            check_eq(f"t6 {words!r}: recorded", ok, True if flag or words == "approve" else False)
            if ok:
                check_eq(f"t6 {words!r}: --as-is {'is' if flag else 'is not'} sent to the controller",
                         "--as-is" in calls[0][1], flag)
    finally:
        os.chdir(harness.PLUGIN_ROOT)
        harness.cleanup(root)


def t7_gate_b_delivery_line() -> None:
    """Gate B `delivery-1: deliver with known gaps` (RL-12): the real stand-gap reader leaves it unread (it names no stand gap), and the
    approval does NOT ride it (t-550 F1): the controller has no open-items net at gate B, so the decision to deliver with known gaps
    would be lost under a recorded approval. The answer is kept whole for the conductor."""
    root, _task_root, env = seed(TASK)
    try:
        d = driver_for(root, env, TASK)
        words = "approve\ndelivery-1: deliver with known gaps"
        with contextlib.redirect_stdout(io.StringIO()):
            stand = d.take_stand_gap_answers("gate_B", words, "", "S8", "")
        check_eq("t7: the line is in `unread`", stand.get("unread"), ["delivery-1: deliver with known gaps"])
        check_eq("t7: and the function does not let the approval ride it", d.gate_lines_over_approval("gate_B", words, stand, []), False)
    finally:
        os.chdir(harness.PLUGIN_ROOT)
        harness.cleanup(root)
    rig = Rig("gate_B", stand=stand_of(["delivery-1: deliver with known gaps"]))
    try:
        rig.take("approve\ndelivery-1: deliver with known gaps")
        check_eq("t7 (take_answer): no record by code, the whole answer kept", [entry[0] for entry in rig.log], ["kept"])
    finally:
        rig.close()


def t8_hold_list() -> None:
    """t-550 F2: the stand-gap reader's `hold` names the lines that were understood and not carried out (a record the story REFUSED, an
    `ask again`) or ask (`?`); `take_answer` keeps such an approval for the conductor on gate A."""
    root, _task_root, env = seed(TASK)
    try:
        d = driver_for(root, env, TASK)
        d.rehearse = lambda gate: {"findings": FINDINGS, "stand_gaps": []}
        d.revoke_environment_properties = lambda gate, revokes: [{"line": "gap-1: ask again", "why": "taken back"}]
        d._record_door_lines = lambda *a, **k: ([], [("vcs-1", "vcs-1: accept", "the story refused the record")], set())
        words = "approve\nvcs-1: accept\ncase_environment-1: is this fine?\nsome-3: go on"
        with contextlib.redirect_stdout(io.StringIO()):
            stand = d.take_stand_gap_answers("gate_A", words, "", "S4", "")
        check_in("t8: a refused record is held", "vcs-1: accept", stand.get("hold", []))
        check_in("t8: an `ask again` is held", "gap-1: ask again", stand.get("hold", []))
        check("t8: a line with `?` is held", any("?" in line for line in stand.get("hold", [])), str(stand.get("hold")))
        check_not_in("t8: a plain unread line is not held", "some-3: go on", " | ".join(stand.get("hold", [])))
        check_eq("t8: so the approval does not ride", d.gate_lines_over_approval("gate_A", words, stand, []), False)
    finally:
        os.chdir(harness.PLUGIN_ROOT)
        harness.cleanup(root)
    for label, line in (("failed", "vcs-1: accept"), ("ask again", "gap-1: ask again"), ("question mark", "TC-1: accept?")):
        rig = Rig("gate_A", stand={**stand_of([line]), "hold": [line]})
        try:
            rig.take("approve\n" + line)
            check_eq(f"t8 {label} (take_answer): kept for the conductor, not recorded", [entry[0] for entry in rig.log], ["kept"])
        finally:
            rig.close()


def t9_open_items_refusal_keeps_the_answer() -> None:
    """t-550 F7 (spec A11 step 1, outcome 2): the RL-4:8 answer at gate A, the controller's refusal carrying `open_items` (the shape
    `controller.py` prints; the items are `person_decides`, so an unread line words nothing). The real `record_by_code` and the real
    `_unread_kept_gate` run over a recorder of the controller call: the approval is NOT recorded, it is kept whole, and the conductor
    is given the open items. The node does not itself record this example; the conductor can only offer `approve` again (finding)."""
    import json
    items = [{"id": "vcs-1", "check": "vcs", "message": "the branch has no remote",
              "door": {"kind": "line", "says": "write the line", "block": "vcs", "stage": "S9", "waives": []}},
             {"id": "case_environment-1", "check": "case_environment", "message": "TS-14 declares a gap",
              "door": {"kind": "none", "says": "say it", "block": "", "stage": "", "waives": []}}]
    refused = json.dumps({"recorded": False, "problems": ["[vcs-1] the branch has no remote - needs your word: write the line"],
                          "open_items": items, "request": {}})
    rig = Rig("gate_A", stand=stand_of(["vcs-1: go on on this branch", "case_environment-1: accept the gap"]))
    try:
        d, sent = rig.d, []
        del d.record_by_code, d._unread_kept_gate          # the class's methods
        d.py = lambda script, *args, **k: sent.append(script) or (1, refused)
        d.shown_packet = lambda kind: ""
        d.judged_reply = lambda *a, **k: ""
        d.controller_state = lambda: {}
        d.unread = lambda kind, stage, dispatch, text, words="", **k: rig.log.append(("conductor", text, words))
        rig.take(RL4)
        check_eq("t9: the controller was asked once and refused", sent, ["controller.py"])
        check_eq("t9: the approval is kept whole", (d.state.get("gate_answer_kept") or {}).get("words"), RL4)
        conductor = [entry for entry in rig.log if entry[0] == "conductor"]
        check_eq("t9: the conductor gets the whole answer, once", [entry[2] for entry in conductor], [RL4])
        check_in("t9: and the open items by id", "vcs-1", conductor[0][1] if conductor else "")
        check_eq("t9: nothing told as understood", rig.rows, [])
    finally:
        rig.close()


def main() -> None:
    for scenario in (s1_reproduction, g1_truth_table, t1_lines_ride_the_approval, t2_exploratory_bug_with_approval,
                     t3_controller_refuses, t4_approve_not_on_the_first_line, t5_no_unread_line_is_untouched,
                     t6_approve_as_is_reaches_the_controller_with_its_flag, t7_gate_b_delivery_line, t8_hold_list,
                     t9_open_items_refusal_keeps_the_answer):
        scenario()
    harness.finish("test_gate_lines_over_approval")


if __name__ == "__main__":
    main()
