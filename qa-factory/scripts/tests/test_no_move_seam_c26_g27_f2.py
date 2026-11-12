#!/usr/bin/env python3
"""c26 g27 f2: a part of test_no_move_seam.py, split by tools/test_split.py (TD-11c). The shared helpers are in no_move_seam_common."""
import contextlib
import io
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import check, check_eq, check_in, check_not_in  # noqa: E402
from story_run_common import jsonl, seam_option  # noqa: E402
import no_move as NM  # noqa: E402
import story_run  # noqa: E402
import copy  # noqa: E402
from no_move_seam_common import FACTS, answer, logged_rig, raised, rig, take, verdict  # noqa: E402


# --- t-856 (C2-6): the `rework` option carries "args", the token carries the person's words ------------------------------------------------------
C26_FACTS = dict(FACTS, rework_stages=["S4", "S5"], rework_roles={"S4": ["qa-case-designer"], "S5": ["qa-automator", "qa-code-critic"]},
                 scope=["TC-1", "TC-2"], causes=["test_defect", "mechanical"])


C26_ARGS = {"stage": "S5", "role": "qa-automator", "cases": ["TC-1"], "cause": "test_defect"}


def c26_option(**args) -> dict:
    return dict(seam_option("rework", "rework_stage"), args=args)


def c26_verdict(options, **extra) -> dict:
    return {"action": "ask_person", "did": "looked", "question": "Which one?", "why_person": "access", "checked": "the refusal",   # RN1-9 default class
            "options": options, **extra}


def c26_validate(options, facts=C26_FACTS, chosen=False, move=""):
    try:
        return NM.validate_options(c26_verdict(options), ["rework_stage", "person_does", "stop_here"], NM.data(), lambda s: s.strip().lower(),
                                   {}, facts=facts, chosen=chosen, chosen_move=move)[0] and "ok"
    except NM.ArgsRefused as refused:
        return "args: " + refused.rule


def c26_args_are_validated_and_carried() -> None:
    other = seam_option("retry", "person_does")
    check_eq("C26: good args pass and are kept on the option", NM.validate_options(
        c26_verdict([c26_option(**C26_ARGS), other]), ["rework_stage", "person_does"], NM.data(), lambda s: s.strip().lower(), {},
        facts=C26_FACTS)[0][0]["args"], C26_ARGS)
    bad = {"stage not listed": dict(C26_ARGS, stage="S7"), "role of another stage": dict(C26_ARGS, role="qa-case-designer"),
           "case outside scope": dict(C26_ARGS, cases=["TC-9"]), "cases and rows": dict(C26_ARGS, rows=["TS-1"]),
           "no case on S5": dict(C26_ARGS, cases=[]), "cause not listed": dict(C26_ARGS, cause="whim")}
    for label, args in bad.items():
        check(f"C26: {label} -> ArgsRefused", c26_validate([c26_option(**args), other]).startswith("args: "), c26_validate([c26_option(**args), other]))
    check("C26: no args at all -> ArgsRefused", c26_validate([seam_option("rework", "rework_stage"), other]).startswith("args: "))
    check("C26: a fact that was not read -> ArgsRefused (FR-59)", c26_validate([c26_option(**C26_ARGS), other], dict(C26_FACTS, scope=None)).startswith("args: "))
    # t-1936 F2 (Fork 3-B): `args` on a move whose column is null is DROPPED, the option kept (it was malformed, a refused answer, before)
    kept = NM.validate_options(
        c26_verdict([c26_option(**C26_ARGS), dict(other, args={"stage": "S5"})]), ["rework_stage", "person_does"], NM.data(), lambda s: s.strip().lower(), {},
        facts=C26_FACTS)[0]
    check("C26 (F2): args on another move is dropped, not ArgsRefused and not malformed: the option stays, without `args`",
          kept is not None and "args" not in kept[1] and kept[1].get("args_dropped") is True and kept[0]["args"] == C26_ARGS, str(kept))
    # the lone option (L-5, L-6 (b)): only at a chosen call for `rework`
    check_eq("C26: one rework option with good args is legal at a chosen call", c26_validate([c26_option(**C26_ARGS)], chosen=True, move="rework_stage"), "ok")
    check_eq("C26: ...not outside a chosen call", c26_validate([c26_option(**C26_ARGS)]), None)
    check_eq("C26: ...not at a chosen call of another move (L-6 b)", c26_validate([c26_option(**C26_ARGS)], chosen=True, move="go_on_as_is"), None)
    check_eq("C26: one option of another move is never legal", c26_validate([other], chosen=True, move="rework_stage"), None)
    check_eq("C26 F-4: a chosen call whose move is unknown opens no lone option (a bool and a move id, not a tri-state)", c26_validate([c26_option(**C26_ARGS)], chosen=True), None)
    listing = NM.rework_args_list(dict(C26_FACTS, scope=[f"TC-{n}" for n in range(61)]))
    for needle in ('"args" from these values only', "S5 → qa-automator | qa-code-critic", "(+1 more: state/controller.json \"scope\")", "cause: test_defect | mechanical"):
        check_in(f"C26: the closed list says {needle}", needle, listing)
    check_in("C26: the moves section carries the list, not the old stages line", "S4 → qa-case-designer", NM.moves_section(NM.data(), ["rework_stage"], C26_FACTS))


def c26_rig(answers):
    root, task_root, driver = rig(answers=answers)
    driver.no_move_facts = lambda state: dict(C26_FACTS)
    return root, task_root, driver


def c26_a_chosen_call_runs_or_asks_literally() -> None:
    chosen = {"why": "chosen", "kind": "conductor", "stage": "S5", "dispatch": "", "text": "t", "token": "rework", "move": "rework_stage",
              "says": "the automator changes the test", "words": "change the export test", "words_file": ""}
    root, task_root, driver = c26_rig([c26_verdict([c26_option(**C26_ARGS)]), c26_verdict([c26_option(**C26_ARGS)])])
    try:
        rel = driver.words_file("change the export test", "answer").relative_to(driver.task_root).as_posix()
        result, person = raised(driver, dict(chosen, words_file=rel))
        check_eq("C26: one rework option with args at a chosen call -> `continue`, no Person, the record is written",
                 (result, person, (driver.state.get("seam_rework") or {}).get("words_file")), ("continue", None, rel))
        prompt = driver.calls[0]["text"]
        check_in("C26: the prompt carries what the option says and that the words are the instruction", 'The person chose `rework` (move `rework_stage`): "the automator changes the test".', prompt)
        check_in("C26: ...and the one-option answer the code can run", "answer ask_person with exactly one option", prompt)
        check_eq("C26: ...and the conductor got the ORIGINAL words and file", (driver.calls[0]["words"], driver.calls[0]["words_file"]), ("change the export test", rel))
        driver.state.pop("seam_rework")
        # no words on file: held, no record
        _, held = raised(driver, dict(chosen, words_file=""))
        check("C26: a lone rework option with no words on file -> held, no record", held is not None and "none are on file" in held.text and "seam_rework" not in driver.state)
    finally:
        harness.cleanup(root)
    root, task_root, driver = c26_rig([c26_verdict([seam_option("retry", "person_does"), seam_option("stop", "stop_here")])])
    try:
        _, person = raised(driver, dict(chosen, words_file="x"))
        check("C26 (1): two usable options -> the person is asked, no record", person is not None and list(person.offered) == ["retry", "stop"] and "seam_rework" not in driver.state)
    finally:
        harness.cleanup(root)
    root, task_root, driver = c26_rig([{"action": "stop", "did": "x", "question": "No.", "why_person": "access", "checked": "the refusal",
                                        "options": [seam_option("retry", "person_does"), seam_option("stop", "stop_here")]}])
    try:
        _, person = raised(driver, dict(chosen, words_file="x"))
        check_eq("C26 (2): `stop` -> the story stops (exit 4), no record", (person.code, "seam_rework" in driver.state), (story_run.EXIT_GAVE_UP, False))
    finally:
        harness.cleanup(root)
    root, task_root, driver = c26_rig([c26_verdict([seam_option("retry", "person_does")]), c26_verdict([seam_option("retry", "person_does")])])
    try:
        _, person = raised(driver, dict(chosen, words_file="x"))
        check_eq("C26 (3): a malformed answer -> a defect, the conductor again with the rule, then the fallback question, no record",
                 (len(driver.calls), len(driver.defects) >= 1, "Your options were refused" in driver.calls[-1]["text"], person is not None and "seam_rework" in driver.state),
                 (2, True, True, False))
    finally:
        harness.cleanup(root)
    root, task_root, driver = c26_rig([c26_verdict([c26_option(**dict(C26_ARGS, role="nobody")), seam_option("retry", "person_does")]),
                                       c26_verdict([c26_option(**C26_ARGS), seam_option("retry", "person_does")])])
    try:
        _, person = raised(driver, dict(chosen, why="refusal", words_file="x"))
        check_eq("C26 p.4: bad args -> ONE repeat to the conductor with the rule and the closed list; the good answer is shown to the person",
                 (len(driver.calls), "did no accepted work" in driver.calls[1]["text"], '"args" from these values only' in driver.calls[1]["text"],
                  person.options[0].get("args")), (2, True, True, C26_ARGS))
    finally:
        harness.cleanup(root)


def c26_restart_refused_is_held_and_the_conductor_is_not_called() -> None:
    """t-722 §4.4 (owed pin): the controller REFUSED the release the person chose with `restart`: the question comes back held, with
    the controller's own words as its details, the same tokens; the conductor is not called and no other road releases the dispatch."""
    root, task_root, driver = logged_rig(answers=[verdict((("retry", "person_does"), ("restart", "release_and_restart")),
                                                          question="What now? `retry` or `restart`?")])
    try:
        driver.ask(story_run.Person("conductor", "What should happen at the plan stage?", "S5", "S5-qa-x-1"))
        person = take(driver, answer(task_root, "a1.md", b"start that step again, please\r\n"))
        driver.ask(person)
        driver.calls.clear()
        released = []
        real_release = story_run.waiver.run_release
        story_run.waiver.run_release = lambda task_root, dispatch, **kw: (released.append(dispatch), (1, "the controller refuses: S5-qa-x-1 is already accepted"))[1]
        try:
            held = take(driver, answer(task_root, "a2.md", b"restart\r\n"))
        finally:
            story_run.waiver.run_release = real_release
        check("C26 restart refused: the question is held, with the controller's words, the same tokens",
              held is not None and "could not be carried out, so nothing was released" in held.text
              and "is already accepted" in held.details and list(held.offered) == ["retry", "restart"], str(held))
        check_eq("C26 restart refused: the release was tried once, the conductor was not called, the question is still open",
                 (released, driver.calls, bool(driver.state["asked"])), (["S5-qa-x-1"], [], True))
    finally:
        harness.cleanup(root)


def c26_a_refused_rework_goes_to_the_conductor_through_the_seam() -> None:
    """t-722 §4.2 p.8 (owed pin): the controller refuses the rework the person chose (`ReworkRefused` in `seam_rework_step`): the record
    is dropped (nothing was registered), and the refusal reaches the CONDUCTOR through the one seam, with the refusal's words, the
    person's ORIGINAL words and file, and the closed list of what `args` may name; the conductor's options are the person's question."""
    root, task_root, driver = c26_rig([c26_verdict([c26_option(**C26_ARGS), seam_option("retry", "person_does")])])
    try:
        words = "change the export test and check the body too"
        rel = driver.words_file(words, "answer").relative_to(driver.task_root).as_posix()
        (driver.state_dir / "controller.json").write_text(json.dumps({"dispatches": {}}), encoding="utf-8")
        driver.controller_state = lambda: {"dispatches": {}}

        def refuse(*a, **k):
            raise story_run.ReworkRefused("the controller refuses the rework: S5 is not open for it")
        driver.rework = refuse
        driver.state["seam_rework"] = dict(C26_ARGS, words_file=rel, at="then", before=[])
        shown = io.StringIO()
        person = None
        try:
            with contextlib.redirect_stdout(shown):
                driver.seam_rework_step()
        except story_run.Person as raised_person:
            person = raised_person
        call = (driver.calls or [{}])[0]
        check_eq("C26 ReworkRefused: the record is dropped and the conductor was called ONCE", ("seam_rework" in driver.state, len(driver.calls)), (False, 1))
        check("C26 ReworkRefused: the call carries the refusal, the closed list and the person's original words and file",
              "S5 is not open for it" in call.get("text", "") and '"args" from these values only' in call.get("text", "")
              and (call.get("words"), call.get("words_file")) == (words, rel), str(call)[:400])
        check("C26 ReworkRefused: the conductor's options are the person's question (a Person, with `rework` offered)",
              person is not None and "rework" in person.offered, str(person))
    finally:
        harness.cleanup(root)


def c26_a_release_by_any_road_hands_its_words_to_the_relaunch() -> None:
    """t-698 §12.2.4 (owed pin; `relaunch_reason` is unchanged by C2-6): a dispatch released by the conductor's `restart` - NO exit-limit
    `fresh_line` anywhere - hands the person's words, whole, to the role that starts again; the packet's reason follows them; with no
    release and no line the old sentence stays."""
    root, task_root, driver = rig()
    try:
        closed = "S5-qa-x-1"
        driver.controller_state = lambda: {"dispatches": {closed: {"released_by_person": "start it again\r\nand read the body twice"}}}
        reason = driver.relaunch_reason({"relaunch_of": closed, "reason": "the packet's own reason"}, {})
        check("C26 relaunch: the released dispatch's words reach the role, whole, with the packet's reason after them",
              "set aside by the person" in reason and "The person's words, whole:\nstart it again\r\nand read the body twice" in reason
              and reason.index("read the body twice") < reason.index("the packet's own reason"), reason)
        driver.controller_state = lambda: {"dispatches": {closed: {}}}
        check_in("C26 relaunch negative: no release - today's line", "never reached an agent", driver.relaunch_reason({"relaunch_of": closed}, {}))
    finally:
        harness.cleanup(root)


def c26_fix_round_t873() -> None:
    """t-873 fix round: F-2 (one chosen note), F-5 (the exit code of an unusable `continue`/`retry` with options), F-7 (the own dispatch
    of a rework has an ORIGIN: the person's words by file, or the driver's `ticket_changed` reason), and the one words reader."""
    root, task_root, driver = rig()
    try:
        state = {"token": "rework", "move": "rework_stage", "says": "", "words": "change it"}
        shut, live = driver.chosen_note(state, ["person_does", "stop_here"]), driver.chosen_note(state, ["rework_stage", "person_does"])
        check("C26 F-2: a `rework` that is no longer open says so and does not order the one rework option",
              "no longer open" in shut and "exactly one option" not in shut, shut)
        check("C26 F-2: ...an open `rework` orders the one option and does not call itself closed",
              "exactly one option" in live and "no longer open" not in live, live)
        # the one words reader: `person_words.read` (CRLF kept, a BOM dropped, UTF-16 / not UTF-8 / empty / missing = lost, no file = none)
        words = task_root / "state" / "words"
        words.mkdir(parents=True, exist_ok=True)
        arrow = "→"
        files = {"crlf-bom.txt": b"\xef\xbb\xbfone\r\ntwo " + arrow.encode("utf-8"), "blank.txt": b"  \r\n\r\n", "utf16.txt": "one two".encode("utf-16"),
                 "latin1.txt": b"caf\xe9 \xff"}
        for name, raw in files.items():
            (words / name).write_bytes(raw)
        got = {name: driver.original_words({"words_file": f"state/words/{name}"}) for name in (*files, "missing.txt")}
        check_eq("C26 words reader: a BOM is dropped, CRLF and a non-ASCII sign are kept", got["crlf-bom.txt"], ("state/words/crlf-bom.txt", "one\r\ntwo " + arrow))
        check_eq("C26 words reader: blank, UTF-16, not UTF-8 and missing are the words LOST (None), never replacement characters",
                 [got[n] for n in ("blank.txt", "utf16.txt", "latin1.txt", "missing.txt")], [None] * 4)
        check_eq("C26 words reader: no file named is no words, not a loss", driver.original_words({"words_file": ""}), ("", ""))
    finally:
        harness.cleanup(root)
    for why, code in (("stop", story_run.EXIT_GAVE_UP), ("refusal", story_run.EXIT_PERSON)):
        for action in ("continue", "retry"):
            root, task_root, driver = rig(answers=[dict(verdict(), action=action)])
            try:
                driver.boundary = "S5:x"
                _, person = raised(driver, {"why": why, "text": "t"})
                check_eq(f"C26 F-5: `{action}` with options at why={why} -> the state's own exit code (what it was before C2-6)", person.code, code)
            finally:
                harness.cleanup(root)
    root, task_root, driver = c26_rig([])
    try:
        rel = driver.words_file("change the export test", "answer").relative_to(driver.task_root).as_posix()
        record = dict(C26_ARGS, cause="ticket_changed", words_file=rel, at="then", before=[])
        calls = []
        driver.rework = lambda *a, **k: calls.append((a, k)) or ("", "")
        # a `ticket_changed` rework in the controller is the driver's own (`--reason`, no `person_words`): it is NOT the record's own dispatch
        origins = {"ticket": {"stage": "S5", "repair_cause": "ticket_changed", "status": "accepted"},
                   "person": {"stage": "S5", "repair_cause": "ticket_changed", "status": "accepted", "person_words": True}}
        for origin, held, expected in (("ticket", origins["ticket"], 1), ("person", origins["person"], 0)):
            driver.state["seam_rework"] = dict(record)
            calls.clear()
            driver.controller_state = lambda held=held: {"dispatches": {"S5-qa-automator-3": held}}
            with contextlib.redirect_stdout(io.StringIO()):
                driver.seam_rework_step()
            check_eq(f"C26 F-7: the dispatch of the {origin}'s origin: the person's rework is {'still owed (run once)' if expected else 'already registered (not run)'}",
                     (len(calls), "seam_rework" in driver.state), (expected, False))
        # ... and the other way: the person's rework of S2 is not the ticket re-run's own, so the owed re-run still starts
        driver.state["ticket_rework"] = {"stages": ["S2"], "words": "new text", "at": "then", "before": []}
        driver.controller_state = lambda: {"dispatches": {
            "S2-qa-analyst-1": {"stage": "S2", "role": "qa-analyst", "status": "accepted"},
            "S2-qa-analyst-2": {"stage": "S2", "role": "qa-analyst", "repair_cause": "ticket_changed", "status": "accepted", "person_words": True}}}
        calls.clear()
        with contextlib.redirect_stdout(io.StringIO()):
            moved = driver.ticket_rework_step()
        check_eq("C26 F-7: a `ticket_changed` rework by the person's words is not taken for the ticket re-run's own", (moved, len(calls)), (True, 1))
    finally:
        harness.cleanup(root)


# --- t-834 (C1-8): the seam set A27 exempts is the seam the Driver has -------------------------------------------------------------------------

def n24_the_seam_set_is_the_seam() -> None:
    """A27 (audit_factory.NO_MOVE_SEAM) exempts the members of the seam from its census. The AST cannot see what a runtime
    `getattr` can: that each name is a function of the LIVE `Driver`. A name of the set the Driver does not have would
    exempt nothing, and a member renamed in `story_run.py` would leave a stale exemption that reads as covered."""
    import audit_factory as A
    members = sorted(A.NO_MOVE_SEAM)
    missing = [m for m in members if not callable(getattr(story_run.Driver, m.split(".", 1)[1], None))]
    check("N24: every member of A27's NO_MOVE_SEAM is a function of the live Driver (" + str(len(members)) + " members)", not missing, str(missing))
    check_eq("N24: the entries of the seam are exactly no_move, unread and funnel", sorted(A.NO_MOVE_ENTRIES), ["funnel", "no_move", "unread"])
    check("N24: every entry is a member", all("Driver." + e in A.NO_MOVE_SEAM for e in A.NO_MOVE_ENTRIES))
    integrity = [f for f in A.a27_findings(harness.PLUGIN_ROOT) if f.startswith("A27 seam") or f.startswith("A27 I-one")]
    check("N24: A27 finds no seam-integrity and no I-one finding on the live driver", not integrity, "\n".join(integrity))


# --- t-884 (C2-7): the fallback site carries the site's words (t-722 §5.1, §5.2) --------------------------------------------------------------
G27 = dict(C26_FACTS, gate="A", gate_decided=False)


def g27_state(**extra) -> dict:
    return dict({"why": "unread_answer", "kind": "gate_A", "stage": "S4", "dispatch": "", "lead": "Your answer was not read.",
                 "words_file": "state/words/driver-answer-x.txt"}, **extra)


def g27_the_fallback_question_at_a_gate() -> None:
    """§5.1: the fallback at a gate offers what has an executor and is open - `approve` (code, the original answer on file),
    `rework` (no `args`; the conductor names the stage), `retry`, `stop` - from the ONE table `GATE_OPTIONS`, the stages in the story's
    words; what is not offered is said in one line of the lead; a fact that cannot be read removes its move and is not told as a reason."""
    root, task_root, driver = rig()
    try:
        def person_for(facts, **extra):
            driver.no_move_facts = lambda state: dict(facts)
            return driver.fallback_person(g27_state(**extra))
        full = person_for(G27)
        check_eq("C27: with the answer on file and the gate open: approve / rework / retry / stop, each with its move",
                 ([(o["token"], o["move"]) for o in full.options]),
                 [("rework", "rework_stage"), ("approve", "approve_gate"), ("retry", "person_does"), ("stop", "stop_here")])
        check_eq("C27: ...and no option carries `args` (the code never picks the stage, P1)", [o for o in full.options if "args" in o], [])
        named = " or ".join(driver.stage_place(s) for s in G27["rework_stages"])
        check_in("C27: the stages slot names the stages in words, once", f"the stage the conductor names — {named} — and the stages after it up to this gate", full.text)
        check_not_in("C27: ...and no bare stage id stands alone", " S4 ", full.text.replace(driver.stage_place("S4"), ""))
        check_in("C27: the site's lead is the body", "Your answer was not read.", full.text)
        check_in("C27: the three price lines follow each option (rule 6)", "the factory:", full.text)
        for label, facts, extra, line in (
                ("no words on file", G27, {"words_file": ""}, driver.NO_APPROVE_WORDS),
                ("a step running", dict(G27, running=True), {}, "Sending a stage back is not open now: a step of the story is still running."),
                ("a delivery attempt", dict(G27, attempts=1), {}, "a delivery attempt is already recorded"),
                ("the story closed", dict(G27, closed=True), {}, "the story is closed"),
                ("no stage with accepted work", dict(G27, rework_stages=[]), {}, "no stage before this gate has accepted work to send back"),
                ("a fact that could not be read", dict(G27, running=None), {}, NM.REWORK_UNREAD),
                ("the controller state unreadable", {"gate": "A"}, {}, NM.REWORK_UNREAD)):
            person = person_for(facts, **extra)
            gone = "approve" if label == "no words on file" else "rework"
            check(f"C27 {label}: `{gone}` is not offered and the lead says why, in one line", gone not in person.offered and line in person.text
                  and "retry" in person.offered and "stop" in person.offered, str(person.offered) + person.text[:200])
        undecided = person_for(dict(G27, gate_decided=None))
        check("C27: a gate decision that cannot be read: no `approve` (FR-59)", "approve" not in undecided.offered, str(undecided.offered))
        check_not_in("C27: no stand card shown, no line about cards", "are read in this answer too", full.text)
        driver.state.setdefault("shown_gaps", {})["A"] = {"gaps": [{"id": "g"}]}
        check_in("C27: the lead names the open stand cards when the packet shown had them (one line, §6 p.21)",
                 "Your answers to the stand cards of this gate, one per line as `<case>: <word>`, are read in this answer too.", person_for(G27).text)
    finally:
        harness.cleanup(root)


def g27_the_floor_at_a_gate() -> None:
    """§5.2: the floor of a gate has `approve` only with the original answer on file and the gate open; `rework` never; the text is
    the one with or without the `approve` line."""
    root, task_root, driver = rig()
    try:
        def floor(facts, **extra):
            driver.no_move_facts = lambda state: dict(facts)
            state = g27_state(**extra)
            return driver.last_resort(state, "the floor", lead=state["lead"])
        with_words = floor(G27)
        check_eq("C27 floor: approve / retry / stop with the answer on file", [o["token"] for o in with_words.options], ["approve", "retry", "stop"])
        check_in("C27 floor: the text says what `approve` does", "`approve` — the gate is recorded as approved with the answer you gave before;", with_words.text)
        check_in("C27 floor: ...and the door to a change", "To change something, write what to change in your own words.", with_words.text)
        for label, person in (("no words file", floor(G27, words_file="")), ("gate decided", floor(dict(G27, gate_decided=True))),
                              ("decision unreadable", floor(dict(G27, gate_decided=None))), ("facts unreadable", floor({}))):
            check(f"C27 floor {label}: no `approve` in the options or the text, `rework` never",
                  list(person.offered) == ["retry", "stop"] and "`approve`" not in person.text and "rework" not in person.text, str(person.offered))
    finally:
        harness.cleanup(root)


def g27_a_rework_from_the_fallback_goes_to_the_conductor_with_the_original_words() -> None:
    """§5.1 / §6 p.29: the person answers `rework` to the fallback question: the conductor gets the ORIGINAL words and file and the line
    'Which stage, role and cases is your judgement', answers with the one `rework` option carrying args, and the record is written with
    NO second question (the person is not asked again)."""
    root, task_root, driver = c26_rig([c26_verdict([c26_option(**C26_ARGS)])])
    try:
        words = "the export test checks only the status code, check the body"
        rel = driver.words_file(words, "answer").relative_to(driver.task_root).as_posix()
        driver.no_move_facts = lambda state: dict(G27)
        with contextlib.redirect_stdout(io.StringIO()):
            driver.ask(driver.fallback_person(g27_state(words_file=rel)))
            person = take(driver, answer(task_root, "token.md", b"rework"))
        call = (driver.calls or [{}])[0]
        check_eq("C27: the token is read, no Person is raised, the conductor was called once with the original words and file",
                 (person, len(driver.calls), call.get("words"), call.get("words_file")), (None, 1, words, rel))
        check_in("C27: ...and told that the stage is its judgement", "Which stage, role and cases is your judgement", call.get("text", ""))
        check_eq("C27: the record of the rework is written with the original file", (driver.state.get("seam_rework") or {}).get("words_file"), rel)
    finally:
        harness.cleanup(root)


def rd1_19_gate_b_assert_stricter_road_is_open() -> None:
    """RD1-19: the words `_assert_stricter_how` hands a person ("tell the delivery gate in your own words") lead to the
    conductor, who may offer a `rework` of the accepted automator for a case in scope at gate B. This key proves ONLY that the
    road is open - `check_args` refuses nothing for those facts - not that the rework restores a removed Then (it cannot after
    gate A; that is the conductor's cost-and-consequence line, FR-9)."""
    facts = dict(C26_FACTS, gate="B", gate_decided=False)
    clean, rule = NM.check_args(dict(C26_ARGS), facts)
    check_eq("RD1-19 gate B, an accepted automator, a case in scope: the args are clean", (clean, rule), (C26_ARGS, ""))
    refused, why = NM.check_args(dict(C26_ARGS, cases=["TC-9"]), facts)
    check("RD1-19 negative control: a case outside the scope is refused by the same call", refused is None and "outside the approved scope" in why, why)


F2_OPEN = ["person_does", "stop_here", "release_and_restart", "go_on_as_is", "rework_stage", "resume_with_words", "story_fact", "revoke_exclusion"]


F2_DASH = {"resume_with_words": "run on the person's own words, never an option: a token answer carries no words",
           "revoke_exclusion": "run on the person's own words, never an option: a token answer carries no words",
           "story_fact": "the conductor's own move: it runs it with a value a script or the person named; never a person's choice"}


def f2_spec(**rows) -> dict:
    """A copy of the real `conductor-actions.json` with the named rows' keys changed (`{move id: {key: value}}`; a value `...` drops the key)."""
    spec = copy.deepcopy(NM.data())
    for row in spec["moves"]:
        for key, value in rows.get(row["id"], {}).items():
            if value is ...:
                row.pop(key, None)
            else:
                row[key] = value
    return spec


def f2_check(options, spec=None, open_ids=None, **extra):
    verdict_ = dict(verdict(()), options=options, question="What should happen next?", **extra)
    return NM.validate_options(verdict_, F2_OPEN if open_ids is None else open_ids, NM.data() if spec is None else spec,
                               story_run.Driver.s0_normalize, {}, facts=C26_FACTS)


def test_args_column_reads_data() -> None:
    rework = dict(seam_option("rework", "rework_stage"), args=dict(C26_ARGS))
    goon = dict(seam_option("go on", "go_on_as_is"), args=dict(C26_ARGS))
    # today's data: the column of rework_stage is "rework" (checked), the column of go_on_as_is is null (dropped)
    options, rule = f2_check([rework, goon])
    assert rule == "" and options is not None, rule
    assert options[0]["args"] == C26_ARGS and "args" not in options[1] and options[1].get("args_dropped") is True, options
    # the COLUMN decides, not the literal move id: swap them and the answers swap
    swapped = f2_spec(rework_stage={"args": None}, go_on_as_is={"args": "rework"})
    options, rule = f2_check([rework, goon], spec=swapped)
    assert rule == "" and "args" not in options[0] and options[0].get("args_dropped") is True, options
    assert options[1]["args"] == C26_ARGS and "args_dropped" not in options[1], options
    # an "args" column still checks the closed list (the invariant of E2.1): a bad stage is the same ArgsRefused
    bad = dict(goon, args=dict(C26_ARGS, stage="S9"))
    try:
        f2_check([rework, bad], spec=swapped)
    except NM.ArgsRefused as refused:
        assert "stage" in refused.rule, refused.rule
    else:
        raise AssertionError("a bad `args` on a move whose column is `rework` was not refused")


def test_args_on_null_column_dropped_and_journaled() -> None:
    options, rule = f2_check([dict(seam_option("retry", "person_does"), args={"dispatch": "S2-x-1"}), seam_option("stop", "stop_here")])
    assert rule == "" and "args" not in options[0] and options[0]["args_dropped"] is True and "args_dropped" not in options[1], (rule, options)
    # E2.3: dropping `args` never relaxes another rule: the same option with a token that is not its move's own is still refused
    options, rule = f2_check([dict(seam_option("go on", "person_does"), args={"x": 1}), seam_option("stop", "stop_here")])
    assert options is None and "is not the token of the move" in rule, rule
    # the driver: the option reaches the person without `args`, and conductor.jsonl says which tokens lost it
    root, task_root, driver = rig(answers=[dict(verdict(), options=[dict(seam_option("retry", "person_does"), args={"dispatch": "S2-x-1"}),
                                                                    seam_option("stop", "stop_here")])])
    try:
        driver.boundary = "S2:S2-qa-case-critic-1"
        _, person = raised(driver, {"why": "refusal", "text": "t", "stage": "S2"})
        assert list(person.offered) == ["retry", "stop"] and person.source == "conductor", (person.offered, person.source)
        assert all("args" not in option for option in person.options), person.options
        lines = jsonl(driver.state_dir / "conductor.jsonl")
        assert [row.get("args_dropped") for row in lines if row.get("action") == "args_dropped"] == [["retry"]], lines
        assert not [row for row in lines if row.get("action") == "unusable"] and not driver.defects, (lines, driver.defects)
    finally:
        harness.cleanup(root)


def test_missing_column_compat_rework_only() -> None:
    bare = f2_spec(**{move["id"]: {"args": ..., "offerable": ..., "not_offered": ...} for move in NM.data()["moves"]})
    for row in bare["moves"]:
        assert "args" not in row and "offerable" not in row, row
    # before the columns exist (E2.1): only rework_stage takes args; a token-`—` move is not offerable, every other one is
    got = {row["id"]: NM.move_columns(row)[:2] for row in bare["moves"]}
    assert got["rework_stage"] == ("rework", True), got
    assert {move: cols for move, cols in got.items() if cols[0] is not None} == {"rework_stage": ("rework", True)}, got
    assert sorted(move for move, cols in got.items() if not cols[1]) == sorted(F2_DASH), got
    rework = dict(seam_option("rework", "rework_stage"), args=dict(C26_ARGS))
    goon = dict(seam_option("go on", "go_on_as_is"), args={"stage": "S2"})
    options, rule = f2_check([rework, goon], spec=bare)
    assert rule == "" and options[0]["args"] == C26_ARGS and options[1].get("args_dropped") is True, (rule, options)
    try:
        f2_check([dict(rework, args=dict(C26_ARGS, cause="invented")), goon], spec=bare)
    except NM.ArgsRefused as refused:
        assert "cause" in refused.rule, refused.rule
    else:
        raise AssertionError("the closed list was not checked in the world without the columns")
    options, rule = f2_check([seam_option("resume", "resume_with_words"), seam_option("stop", "stop_here")], spec=bare)
    assert options is None and "never an option" in rule, rule


def test_bad_column_value_unreadable() -> None:
    for move, change in (("stop_here", {"args": "everything"}), ("person_does", {"offerable": "yes"}), ("stop_here", {"args": ["rework"]})):
        spec = f2_spec(**{move: change})
        token = "stop" if move == "stop_here" else "retry"
        try:
            f2_check([seam_option(token, move), seam_option("go on", "go_on_as_is")], spec=spec)
        except NM.DataUnreadable as unreadable:
            assert move in str(unreadable) and next(iter(change)) in str(unreadable), str(unreadable)
        else:
            raise AssertionError(f"a bad column value {change} on {move} passed silently")
    # the prompt's moves section must never fail on the same data: it reads the safe side
    assert "## Moves open here" in NM.moves_section(f2_spec(stop_here={"offerable": "yes"}), ["stop_here"], {})
    # the driver turns it into an unusable answer with the conductor's question shown - never an exception out of the seam
    root, task_root, driver = rig(answers=[verdict((("retry", "person_does"), ("stop", "stop_here")), question="Do you want to stop here?")])
    real, bad_spec = NM.data, f2_spec(person_does={"offerable": "yes"})
    NM.data = lambda: bad_spec
    try:
        driver.boundary = "S2:x"
        _, person = raised(driver, {"why": "refusal", "text": "t"})
        assert person is not None and "What the conductor found:\nDo you want to stop here?" in person.text, person.text
        assert len(driver.defects) == 1 and "person_does" in " ".join(driver.defects[0]), driver.defects
    finally:
        NM.data = real
        harness.cleanup(root)


def test_dash_moves_not_offerable() -> None:
    rows = {row["id"]: row for row in NM.data()["moves"]}
    for move, why in F2_DASH.items():
        assert NM.move_columns(rows[move]) == (None, False, why), (move, NM.move_columns(rows[move]))
        assert rows[move]["token"] == "—", move                  # no new token (fork 4 reversed)
    for move in set(rows) - set(F2_DASH):
        assert NM.move_columns(rows[move])[1] is True, move
        assert str(rows[move]["token"]) != "—", move
    for move in F2_DASH:
        options, rule = f2_check([seam_option("resume", move), seam_option("stop", "stop_here")])
        assert options is None and f"which is never an option: {F2_DASH[move]}" in rule, rule
    # the invariant that stays: an option whose move is not in the table is still refused
    options, rule = f2_check([seam_option("fly", "teleport"), seam_option("stop", "stop_here")], open_ids=F2_OPEN + ["teleport"])
    assert options is None and "not open here" in rule, rule


def test_not_offered_refusal_quotes_row_reason() -> None:
    spec = f2_spec(story_fact={"not_offered": "THE ROW'S OWN REASON"})
    options, rule = f2_check([seam_option("fact", "story_fact"), seam_option("stop", "stop_here")], spec=spec)
    assert options is None and rule == "the option `fact` names the move `story_fact`, which is never an option: THE ROW'S OWN REASON", rule
    gone = f2_spec(story_fact={"not_offered": ...})
    options, rule = f2_check([seam_option("fact", "story_fact"), seam_option("stop", "stop_here")], spec=gone)
    assert options is None and NM.NOT_OFFERED_DEFAULT in rule, rule


def test_moves_section_says_args_and_never_an_option() -> None:
    section = NM.moves_section(NM.data(), list(F2_OPEN) + ["approve_gate", "stand_prepare"], C26_FACTS)
    assert '- `rework_stage` — token `rework`; its option carries "args" from these values only:' in section, section
    assert '- `go_on_as_is` — token `go on`; option carries no "args"' in section, section
    assert '- `release_and_restart` — token `restart`; option carries no "args"' in section, section
    assert '- `stand_prepare` — token `prepare the stand`; option carries no "args"' in section, section
    assert "- `resume_with_words` — run on the person's own words, never an option" in section, section
    assert "- `revoke_exclusion` — run on the person's own words, never an option" in section, section
    assert "- `story_fact` — yours to run, never an option" in section, section
    assert "resume_with_words` — token" not in section and "story_fact` — token" not in section, section
    # a table where go_on_as_is takes args prints the rework list for it: the section reads the column
    swapped = NM.moves_section(f2_spec(go_on_as_is={"args": "rework"}, rework_stage={"args": None}), ["go_on_as_is", "rework_stage"], C26_FACTS)
    assert 'option carries "args" from these values only' in swapped and "`rework_stage` — token `rework`; option carries no" in swapped, swapped


F2_TESTS = (
    test_args_column_reads_data,
    test_args_on_null_column_dropped_and_journaled,
    test_missing_column_compat_rework_only,
    test_bad_column_value_unreadable,
    test_dash_moves_not_offerable,
    test_not_offered_refusal_quotes_row_reason,
    test_moves_section_says_args_and_never_an_option,
)


def f2_run() -> None:
    for scenario in F2_TESTS:
        try:
            scenario()
            check(f"F2 {scenario.__name__}", True)
        except AssertionError as exc:
            check(f"F2 {scenario.__name__}", False, str(exc)[:600])


# split: runner piece 1
if __name__ == "__main__":
    f2_run()                                                         # t-1936 F2: one block at the end, so the merge with another node is clean
    rd1_19_gate_b_assert_stricter_road_is_open()                     # RD1-19: one block at the end, so the merge with another node is clean
    g27_the_fallback_question_at_a_gate()                          # t-884 (C2-7): one block at the end, so the merge with another node is clean
    g27_the_floor_at_a_gate()
    g27_a_rework_from_the_fallback_goes_to_the_conductor_with_the_original_words()
    c26_args_are_validated_and_carried()                             # t-856 (C2-6): one block at the end, so the merge with another node is clean
    c26_a_chosen_call_runs_or_asks_literally()
    c26_restart_refused_is_held_and_the_conductor_is_not_called()
    c26_a_refused_rework_goes_to_the_conductor_through_the_seam()
    c26_a_release_by_any_road_hands_its_words_to_the_relaunch()
    c26_fix_round_t873()
    n24_the_seam_set_is_the_seam()                                  # t-834: after el12_..., before main() finishes the run
    harness.finish("no_move seam_c26_g27_f2")
