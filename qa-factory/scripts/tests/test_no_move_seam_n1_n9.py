#!/usr/bin/env python3
"""n1 n9: a part of test_no_move_seam.py, split by tools/test_split.py (TD-11c). The shared helpers are in no_move_seam_common."""
import json
import re
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import check, check_eq, check_in, check_not_in  # noqa: E402
from story_run_common import seam_option  # noqa: E402
import human_text  # noqa: E402
import no_move as NM  # noqa: E402
import story_run  # noqa: E402
from no_move_seam_common import raised, rig, verdict  # noqa: E402


def n1_one_why_at_a_time() -> None:
    root, task_root, driver = rig()
    try:
        driver.boundary = "S5:S5-qa-automator-1"
        for why in ("refusal", "stop", "unread_answer", "by_hand", "chosen"):
            driver.conductor_calls.clear()
            driver.calls.clear()
            state = {"why": why, "kind": "conductor", "stage": "S5", "dispatch": "", "text": "the factory's words", "words": "w",
                     "move": "person_does", "token": "retry"}
            result, person = raised(driver, state)
            check(f"N1 {why}: a Person of kind conductor", person is not None and person.kind == "conductor")
            check_eq(f"N1 {why}: offered = the tokens", list(person.offered), ["retry", "stop"])
            check_eq(f"N1 {why}: the conductor was called once", len(driver.calls), 1)
            for token in ("retry", "stop"):
                check_in(f"N1 {why}: `{token}` is followed by the three labels",
                         "\nthe factory: nothing runs now\nyou: work of yours outside the factory: the thing named above\nthe story: ", person.text)
            check_eq(f"N1 {why}: the factory's words are the details", person.details, "the factory's words")
            check_eq(f"N1 {why}: the price lines pass price_problems", human_text.price_problems(person.text, list(person.offered)), [])
        for why in ("cap", "threshold"):
            driver.calls.clear()
            driver.defects.clear()
            _, person = raised(driver, {"why": why, "kind": "refusal", "call": False, "text": "t"})
            check_eq(f"N1 {why} with call=False: the conductor was called 0 times", len(driver.calls), 0)
            if why == "cap":
                check("N1 cap: the defect names the refusal cap, not the conductor's",
                      len(driver.defects) == 1 and "the refusal cap was reached" in " ".join(driver.defects[0])
                      and "conductor cap" not in " ".join(driver.defects[0]), str(driver.defects))
            check_eq(f"N1 {why}: the fallback offers retry / go on / stop", list(person.offered), ["retry", "go on", "stop"])
            check_eq(f"N1 {why}: kind kept", person.kind, "refusal")
        driver.ask(person)
        asked = driver.state["asked"]
        check_eq("N1: ask() writes offered / options / why", (asked["offered"], asked["why"], asked["options"][0]),
                 (["retry", "go on", "stop"], "threshold", {"token": "retry", "move": "person_does",
                                                            "says": "you deal with what is in the way, and the factory looks again"}))     # C2-6: `says` travels (§4.3)
    finally:
        harness.cleanup(root)


def n2_the_filter() -> None:
    base = {"dispatch_status": "running", "session": True, "running": False, "closed": False, "attempts": 0,
            "rework_stages": ["S5"], "stand_authorized": True, "live_exclusions": True, "gate": "", "gate_decided": None}
    every = NM.move_ids()
    check_eq("N2: MOVE_FACTS keys == moves[].id of conductor-actions.json", sorted(NM.MOVE_FACTS), sorted(every))
    check_eq("N2: every move but `approve_gate` is open on a clean state outside a gate (that one needs a gate)",
             sorted(NM.open_moves(base, every)), sorted(set(every) - {"approve_gate"}))
    cases = [("rework_stage", {"rework_stages": []}), ("rework_stage", {"running": True}), ("rework_stage", {"closed": True}),
             ("rework_stage", {"attempts": 1}), ("rework_stage", {"attempts": None}), ("rework_stage", {"closed": None}),
             ("resume_with_words", {"dispatch_status": "accepted"}), ("resume_with_words", {"dispatch_status": "released_by_person"}),
             ("resume_with_words", {"dispatch_status": "never_started"}), ("resume_with_words", {"dispatch_status": "superseded"}),
             ("resume_with_words", {"dispatch_status": "stale"}), ("resume_with_words", {"dispatch_status": None}),
             ("resume_with_words", {"session": False}), ("release_and_restart", {"attempts": 1}),
             ("release_and_restart", {"dispatch_status": "superseded"}), ("stand_prepare", {"stand_authorized": False}),
             ("stand_prepare", {"stand_authorized": None}), ("revoke_exclusion", {"live_exclusions": False}),
             ("revoke_exclusion", {"live_exclusions": None})]
    for move, change in cases:
        check(f"N2 negative: {move} removed by {change}", move not in NM.open_moves(dict(base, **change), every))
    at_gate = dict(base, gate="B", gate_decided=False)
    check_eq("N2 (C1-4b): at a gate with no current decision `approve_gate` is open and `go_on_as_is` is not - at a gate the one pass is "
             "`approve`, two moves never pass one gate",
             sorted(NM.open_moves(at_gate, every)), sorted((set(every) - {"go_on_as_is"})))
    for label, change in (("gate decided", {"gate_decided": True}), ("gate decision unreadable", {"gate_decided": None}),
                          ("not at a gate", {"gate": ""}), ("a gate that is no gate", {"gate": "C"})):
        check(f"N2 negative (C1-4b): approve_gate removed by {label}", "approve_gate" not in NM.open_moves(dict(at_gate, **change), every))
    check("N2 negative (C1-4b): go_on_as_is removed at gate A as well, and by an unreadable gate fact",
          "go_on_as_is" not in NM.open_moves(dict(at_gate, gate="A"), every) and "go_on_as_is" not in NM.open_moves(dict(base, gate=None), every))
    check("N2: a raising predicate removes only its move",
          NM.open_moves(None, ["person_does"]) == ["person_does"] and "x" not in NM.open_moves(base, ["x"]))
    check("N2: no_trace is not a fact the filter reads (FR-36): the table has no such key", "no_trace" not in json.dumps(sorted(NM.MOVE_FACTS)))


def n3_options_authoritative() -> None:
    normalize = story_run.Driver.s0_normalize
    spec, words, open_ids = NM.data(), {"no": {"head": "Verdict: not ready to ship as is."}}, ["person_does", "stop_here", "release_and_restart"]
    ok, rule = NM.validate_options(verdict(), open_ids, spec, normalize, words)
    check("N3: the clean verdict is valid", ok is not None and rule == "", rule)
    bad = {"duplicate tokens": verdict((("retry", "person_does"), ("retry", "person_does")), question="What should happen? `retry`?"),
           "a token outside the move": verdict((("retry", "person_does"), ("go on", "stop_here"))),
           "a move not open": verdict((("retry", "person_does"), ("prepare the stand", "stand_prepare"))),
           "prose/options mismatch": verdict(question="What should happen? `retry` or `stop` or `go on`?"),
           "one option": verdict((("retry", "person_does"),)),
           "token dash": verdict((("retry", "person_does"), ("—", "rework_stage"))),
           "story as a plain string": dict(verdict(), options=[dict(seam_option("retry", "person_does"), story="x"), seam_option("stop", "stop_here")]),
           "a wrong action": verdict(action="wait")}
    for label, candidate in bad.items():
        options, rule = NM.validate_options(candidate, open_ids, spec, normalize, words)
        check(f"N3 {label}: not used ({rule})", options is None and rule)
    root, task_root, driver = rig(answers=[verdict((("retry", "person_does"), ("retry", "person_does")), question="What now? `retry`?")])
    try:
        driver.boundary = "S5:x"
        _, person = raised(driver, {"why": "refusal", "text": "t"})
        check_eq("N3: a duplicate-token verdict renders the fallback", list(person.offered), ["retry", "go on", "stop"])
        check_eq("N3: and exactly one defect_found is journalled", len(driver.defects), 1)
    finally:
        harness.cleanup(root)
    root, task_root, driver = rig(answers=[dict(verdict(), action="continue")])
    try:
        driver.boundary = "S5:x"
        _, person = raised(driver, {"why": "refusal", "text": "t"})
        check("N3: `continue` with options is not a move", person is not None and len(driver.defects) == 1)
    finally:
        harness.cleanup(root)


def n4_the_cap() -> None:
    root, task_root, driver = rig()
    try:
        driver.boundary = "S5:x"
        cap = story_run.CONDUCTOR_CALLS_PER_BOUNDARY
        driver.conductor_calls[driver.boundary] = cap - 1
        _, person = raised(driver, {"why": "refusal", "text": "t"})
        check_eq("N4 AT the cap - 1: the conductor is called", len(driver.calls), 1)
        driver.conductor_calls[driver.boundary] = cap
        driver.calls.clear()
        _, person = raised(driver, {"why": "refusal", "text": "t"})
        check_eq("N4 AT the cap: no call", len(driver.calls), 0)
        check("N4 AT the cap: the defect names the conductor cap",
              len(driver.defects) == 1 and "the conductor cap was reached" in " ".join(driver.defects[0]), str(driver.defects))
        check_not_in("N4: and never the old text", "What should happen?", person.text)
        check_in("N4: but the fallback with its prices", "## What each answer costs and does", person.text)
    finally:
        harness.cleanup(root)


def n5_gate_kinds_carry_their_moves() -> None:
    """N5 (flipped by C1-4b): the gates left EXCLUDED_KINDS. A gate kind is called with the moves open at the gate and its priced
    options, offers what the conductor offers within them, and its fallback (cap, unreadable answer) is `retry` / `stop`."""
    root, task_root, driver = rig(answers=[verdict(question="What now? `retry` once you changed it, or `stop`?")])
    try:
        driver.boundary = "S8:answer"
        _, person = raised(driver, {"why": "unread_answer", "kind": "gate_B", "stage": "S8", "text": "t", "words": "w"})
        check_eq("N5: a gate kind now carries offered - the conductor's two options", list(person.offered), ["retry", "stop"])
        check_eq("N5: and keeps the gate's own kind", person.kind, "gate_B")
        check_in("N5: the call carried the moves section", "## Moves open here", driver.calls[0]["text"])
        check_in("N5: and the options of this gate with their price lines (data rows `gate_B`)", "## The options at this gate",
                 driver.calls[0]["text"])
        driver.conductor_calls[driver.boundary] = story_run.CONDUCTOR_CALLS_PER_BOUNDARY
        driver.calls.clear()
        _, person = raised(driver, {"why": "unread_answer", "kind": "gate_A", "stage": "S4", "text": "t", "words": "w"})
        check_eq("N5d: the cap at a gate: no call, the gate's own kind, and the gate fallback `retry` / `stop`",
                 (len(driver.calls), person.kind, list(person.offered)), (0, "gate_A", ["retry", "stop"]))
        check_not_in("N5d: never today's free 'What should happen?'", "What should happen?", person.text)
        check_in("N5d: and the fallback's priced lines", "## What each answer costs and does", person.text)
    finally:
        harness.cleanup(root)
    root, task_root, driver = rig(answers=[verdict((("retry", "person_does"), ("go on", "go_on_as_is")), question="Which? `retry` or `go on`?")])
    try:
        driver.boundary = "S4:answer"
        _, person = raised(driver, {"why": "unread_answer", "kind": "gate_A", "stage": "S4", "text": "t", "words": "w"})
        check_eq("N5c: a `go on` the conductor offers at a gate is not valid (the move is closed there): the gate fallback, one defect",
                 (list(person.offered), len(driver.defects)), (["retry", "stop"], 1))
    finally:
        harness.cleanup(root)


def n5c_approve_is_open_only_at_a_gate_with_no_decision() -> None:
    """N5c: the facts of `Driver.no_move_facts` over a stubbed controller state - `gate` from the SITE's kind alone, `gate_decided` from
    an approved decision of that gate on the story's current source revision, `go on` never open at a gate."""
    root, task_root, driver = rig()
    try:
        ctl = {"dispatches": {}, "decisions": {}, "source_revision": "r1"}
        driver.controller_state = lambda: ctl
        moves = NM.move_ids()

        def opened(kind):
            return driver.open_moves({"kind": kind, "dispatch": ""}, moves)
        for kind in ("gate_A", "gate_B"):
            check(f"N5c: {kind} with no decision: `approve_gate` open, `go_on_as_is` closed",
                  "approve_gate" in opened(kind) and "go_on_as_is" not in opened(kind), str(opened(kind)))
        check("N5c: a question that is no gate: `go_on_as_is` open, `approve_gate` closed",
              "go_on_as_is" in opened("conductor") and "approve_gate" not in opened("conductor"))
        driver.state["asked"] = {"kind": "gate_B"}
        check_eq("N5c: the gate is never read from `asked` (C1-1 F1): a conductor site is no gate whatever was asked",
                 driver.no_move_facts({"kind": "conductor", "dispatch": ""})["gate"], "")
        ctl["decisions"] = {"g": {"gate": "A", "status": "approved", "source_revision": "r1"}}
        check("N5c: gate A decided: `approve_gate` closed at gate A, still open at gate B",
              "approve_gate" not in opened("gate_A") and "approve_gate" in opened("gate_B"))
        ctl["decisions"]["g"]["status"] = "stale"
        check("N5c: a stale decision is no decision: open again", "approve_gate" in opened("gate_A"))
        ctl["decisions"]["g"].update(status="approved", source_revision="r0")
        check("N5c: a decision on another source revision is no current decision: open again", "approve_gate" in opened("gate_A"))
        driver.controller_state = lambda: {}
        check("N5c: an unreadable controller state removes `approve_gate` (the safe side, FR-59) and still not `go_on_as_is`'s closure",
              "approve_gate" not in opened("gate_B") and "go_on_as_is" not in opened("gate_B"))
    finally:
        harness.cleanup(root)


def n2c_the_stages_a_rework_may_name() -> None:
    """N2c (C1-4b): `stages_open` - S5-S8 once gate A is decided, S1-S4 before it; a later accepted stage no longer closes an earlier one
    (the person-word rework stamps the later stages to run again, C1-4a)."""
    root, task_root, driver = rig()
    try:
        ctl = {"dispatches": {f"d{n}": {"status": "accepted", "stage": f"S{n}"} for n in range(1, 8)}, "decisions": {}, "source_revision": "r1"}
        driver.controller_state = lambda: ctl
        read = lambda: driver.no_move_facts({"kind": "gate_B", "dispatch": ""})["rework_stages"]
        check_eq("N2c: gate A undecided: S1-S4 only, S5-S7 absent", read(), ["S1", "S2", "S3", "S4"])
        ctl["decisions"] = {"a": {"gate": "A", "status": "approved", "source_revision": "r1"}}
        check_eq("N2c: gate A decided: S5-S7, S4 absent, and S5 is open although S6 and S7 are accepted (the old rule closed it)",
                 read(), ["S5", "S6", "S7"])
        ctl["dispatches"]["d9"] = {"status": "accepted", "stage": "S9"}
        ctl["dispatches"]["d8"] = {"status": "accepted", "stage": "S8"}
        check_eq("N2c: S8 is the last stage a rework may name; S9 never", read(), ["S5", "S6", "S7", "S8"])
        ctl["dispatches"]["d6"]["status"] = "stale"
        check_eq("N2c: a stale dispatch names no stage", read(), ["S5", "S7", "S8"])
        ctl["decisions"]["a"]["status"] = "stale"
        check_eq("N2c: gate A made stale: back to S1-S4", read(), ["S1", "S2", "S3", "S4"])
    finally:
        harness.cleanup(root)


def n9_edges_and_ties() -> None:
    labels = human_text.price_labels()
    item6 = re.search(r"6\. \*\*Price and consequences, per option\.\*\*(.*)", (Path(story_run.__file__).resolve().parent.parent
                                                                             / "references" / "human-questions.md").read_text(encoding="utf-8"))
    check("N9: the three labels of price_lines are the ones item 6 names", item6 and all(f"`{label}`" in item6.group(1) for label in labels), str(labels))
    check_eq("N9: TOKEN_MOVES == the tokens of the data", {m["token"]: m["id"] for m in NM.data()["moves"] if m["token"] in NM.TOKEN_MOVES},
             NM.TOKEN_MOVES)
    root, task_root, driver = rig()
    try:
        driver.boundary = "S5:x"
        orig = NM.fallback_options
        NM.fallback_options = lambda *a, **k: (_ for _ in ()).throw(story_run.Refusal("rendering broke"))
        try:
            _, person = raised(driver, {"why": "refusal", "call": False, "text": "t"})
        finally:
            NM.fallback_options = orig
        check_eq("N9: a rendering failure still ends in a question (the last resort, no price lines)", list(person.offered), ["retry", "go on", "stop"])
        check_eq("N9: the seam is free again after it (reset in a finally)", driver._in_no_move, False)
        check_eq("N9: one defect_found", len(driver.defects), 1)
        driver._in_no_move = True
        _, person = raised(driver, {"why": "refusal", "text": "t"})
        driver._in_no_move = False
        check("N9: re-entry renders the last resort and never recurses", person is not None and not driver.calls)
        long6000, long6001 = "x" * 6000, "x" * 6001
        driver.conductor = story_run.Driver.conductor.__get__(driver)
        driver.run_claude = lambda *a, **k: {"result": json.dumps({"action": "continue", "did": "d"}), "session_id": "s", "stderr": "",
                                              "total_cost_usd": 0, "num_turns": 1}
        driver.step = lambda *a, **k: "next: nothing"
        driver._answer = {"text": long6001, "rel": None}
        seen = []
        driver.run_claude = lambda kind, prompt, **k: (seen.append(prompt), {"result": '{"action": "continue", "did": "d"}', "session_id": "s",
                                                                             "stderr": "", "total_cost_usd": 0, "num_turns": 1})[1]
        driver.conductor("r", words=long6000)
        driver.conductor("r", words=long6001, words_file=driver.answer_file())
        check_not_in("N9: 6000 characters are not cut", "(cut;", seen[0])
        check_in("N9: 6001 characters are cut, with the pointer to the whole file", "(cut; the whole answer is in", seen[1])
        check_eq("N9: the words file keeps the answer whole (CRLF kept)", (task_root / driver.answer_file()).read_bytes(), long6001.encode())
    finally:
        harness.cleanup(root)


def main() -> None:
    for scenario in (
        n1_one_why_at_a_time,
        n2_the_filter,
        n2c_the_stages_a_rework_may_name,
        n3_options_authoritative,
        n4_the_cap,
        n5_gate_kinds_carry_their_moves,
        n5c_approve_is_open_only_at_a_gate_with_no_decision,
        n9_edges_and_ties,
    ):
        scenario()
    harness.finish("no_move seam_n1_n9")


# split: runner piece 1
if __name__ == "__main__":
    main()
