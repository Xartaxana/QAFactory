#!/usr/bin/env python3
"""t-2181 PC-7 (§3.2, §5 E-A2, E-A4, E-A5, E-W1; joint plan t-2277 J-11): the driver's arrival road, in process (SLOW: CI only).

A seeded story (a real controller, S0 done) is held for code through the controller's own operations (`await`, `stop_waiting`); the
driver runs over it with `where` and the freshness look faked, and spies on every role run and every rework. What is proved:

  A1  `branch_word_survives_changed_ticket_question` (S11): a `--branch` given on a relaunch is kept before the freshness look; the
      process that asked the changed-ticket question ends with the word still pending; the ANSWER run (`run()` with `--answer`)
      records the arrival BEFORE the first rework of the ticket answer (B4, one ordered list of `arrive` and every rework)
  A2  no role is dispatched, and no arrival is recorded, before the person's answer about a changed ticket
  A3  E-A4: a relaunch with no flag on an awaiting story re-prints the packet, dispatches nothing, exits 3 (the absent-side question) - both relaunches, in a
      fake world
  A4  a STOPPED story relaunched without a flag prints the stopped line and exits 0 - no freshness look, no dispatch
  A5  a relaunch with a flag on a stopped story arrives: the hold is cleared, the side is real, `source: arrival`
  A6  `--side <s>=real` only for a RECORDED side that is not real yet (F2: an unrecorded name, a case variant and a side already real
      are said in one line and kept as nothing); `--until` does not swallow the three hold kinds (F1); `continue_command` repeats
      `--side` and `--reference`
  A7  `await_implementation` writes the await record (packet, S5 dispatch, cause, held_from) and the packet is printed, no role, and the
      question about the absent side follows the packet (exit 3);
      `--until gate_B` does not end the run before it (F1); the packet's restart line carries no `--side <s>=absent` (F7)
  A8  B1: the arrival's rework is S1, S2, then S5 `bind`, one per turn, by cause `source_arrived`; it comes after the ticket's rework
      in the loop; the record survives a crash (the next process goes on where the last stopped); a story with no accepted work is skipped
  A9  B2/E-A5 (b): the question `arrival.not_waiting` is asked on a finished all-real story and not on a held one; each token in a
      second process: `ignore` drops the word, `stop` ends with exit 0 and writes nothing, `re-ground` arrives and owes the rework
  A10 F3: a replay after a crash between `stage_done` and `arrive` records the same sides; F8: the await record's S5 dispatch is the
      newest ACCEPTED one
"""
import contextlib
import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import check, check_eq, check_in, check_not_in  # noqa: E402
from story_run_common import driver_for, run_scenarios, seed  # noqa: E402

KEY = "QA-5"
STOP = {"action": "stop", "reason": "x"}


def set_product(root, env, **attrs) -> None:
    args = []
    for attr, value in attrs.items():
        args += ["--set", f"sides.product.{attr}={value}"]
    harness.run_script("stage_done.py", "--task", KEY, *args, cwd=root, env=env)


def parked_story():
    """(root, task_root, env): a seeded story whose `product` side is absent and which the controller has NOT yet been told to hold."""
    root, task_root, env = seed(KEY)
    set_product(root, env, reality="absent", deliverable="true", source="person")
    return root, task_root, env


def held_story():
    """(root, task_root, env): a seeded story whose `product` side is absent and which the controller holds for code."""
    root, task_root, env = parked_story()
    driver = driver_for(root, env, KEY)
    driver.controller("await", input_data={"packet": "interim-report.md", "s5_dispatch": None, "idempotency_key": "await:t",
                                           "expected_revision": driver.controller_state().get("revision", 0)})
    return root, task_root, env


def pipeline(task_root: Path) -> dict:
    return json.loads((task_root / "pipeline.json").read_text(encoding="utf-8"))


def fake_world(driver, where, freshness=None):
    """Spies: every role run, every rework, every freshness look; `where` answers `where`. Returns the lists."""
    spied = {"roles": [], "reworks": [], "looks": []}
    driver.run_role = lambda *a, **k: spied["roles"].append((a, k))
    driver.rework = lambda *a, **k: spied["reworks"].append((a, k))

    def look():
        spied["looks"].append(1)
        if freshness is not None:
            raise freshness
        return "none"
    driver.ticket_freshness_entry = look
    driver.where = lambda: where
    return spied


def watch_controller(driver) -> list:
    """Wrap `controller` so that every operation is listed in order: `[("controller", "<op>")]` (the real call still happens)."""
    seen: list = []
    real = driver.controller

    def wrapped(op, *args, **kwargs):
        seen.append(("controller", op))
        return real(op, *args, **kwargs)
    driver.controller = wrapped
    return seen


def run_quiet(driver):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = driver.run()
    return code, out.getvalue()


def a1_branch_word_survives_changed_ticket_question() -> None:
    import story_run
    root, task_root, env = held_story()
    try:
        first = driver_for(root, env, KEY, branch="feature/cart")
        changed = story_run.Person("ticket_changed", "The ticket text changed while the story waited. Which text stands?", "S2")
        spied = fake_world(first, STOP, freshness=changed)
        code, _out = run_quiet(first)
        check_eq("A1: the process that asks the changed-ticket question ends with the person's exit code", code, 3)
        check_eq("A1: the launch word is kept before the question (`launch.branch`)", first.state["launch"].get("branch"), "feature/cart")
        check_eq("A1: and stays pending", (first.state["launch"].get("arrival") or {}).get("source"), {"branch": "feature/cart"})
        check_eq("A1: the arrival is not recorded yet - the hold stands", bool(pipeline(task_root).get("awaiting")), True)
        check_eq("A1: no role ran in the first process", spied["roles"] + spied["reworks"], [])
        # the ANSWER run (B4/B5): `run()` with `--answer` holding `new text` and no `--branch`. The adapter call of the real answer branch
        # is replaced by its effect (`ticket_rework` owed on S2/S3) and the ticket step by a spy that opens the rework the way the real one does.
        answer = root / "answer.txt"
        answer.write_text("new text\n", encoding="utf-8")
        second = driver_for(root, env, KEY, answer=str(answer))
        order = watch_controller(second)
        fake_world(second, STOP)

        def ticket_answer(words, qtext, stage, dispatch):
            second.state["ticket_rework"] = {"stages": ["S2"], "words": words, "at": "t", "before": []}
        second.take_ticket_answer = ticket_answer

        def ticket_step():
            order.append(("rework", "S2", "ticket_changed"))        # what `rework` does when the real step opens the S2 re-run
            second.state.pop("ticket_rework", None)
            return False
        second.ticket_rework_step = ticket_step
        code2, _out2 = run_quiet(second)
        record = pipeline(task_root)
        check_eq("A1: the answer run ends well (the fake `where` stops the loop)", code2, 0)
        check_eq("A1: the arrival is recorded from the kept word - the side is real, source arrival",
                 (((record.get("sides") or {}).get("product") or {}).get("reality"), ((record.get("sides") or {}).get("product") or {}).get("source")),
                 ("real", "arrival"))
        check_eq("A1: ... and the hold is cleared", "awaiting" in record, False)
        check_eq("A1: ... and the word is spent", "arrival" in second.state["launch"], False)
        names = [item for item in order if item[0] == "rework" or item == ("controller", "arrive")]
        check_eq("A1 (B4): `arrive` comes BEFORE the first rework of the ticket answer, in this one ordered list",
                 names[:2], [("controller", "arrive"), ("rework", "S2", "ticket_changed")])
    finally:
        harness.cleanup(root)


def a2_no_role_before_the_ticket_answer() -> None:
    import story_run
    root, task_root, env = held_story()
    try:
        driver = driver_for(root, env, KEY, mr="https://git.example/mr/9")
        spied = fake_world(driver, {"action": "prepare_stage", "stage": "S6"},
                           freshness=story_run.Person("ticket_changed", "The ticket text changed. Which text stands?", "S2"))
        code, _out = run_quiet(driver)
        check_eq("A2: the changed-ticket question is asked", code, 3)
        check_eq("A2: no role was dispatched and no rework opened before the answer", (spied["roles"], spied["reworks"]), ([], []))
        check_eq("A2: the arrival was not written ahead of the question", (pipeline(task_root).get("sides") or {}).get("product", {}).get("reality"),
                 "absent")
    finally:
        harness.cleanup(root)


def a3_reprint_with_no_dispatch() -> None:
    import story_run
    root, task_root, env = held_story()
    try:
        driver = driver_for(root, env, KEY)
        action = {"action": "awaiting_implementation", "cause": "s5_absent_side", "held_from": "S6", "packet": "interim-report.md"}
        spied = fake_world(driver, action)
        code, out = run_quiet(driver)
        check_eq("A3 (E-A4): exit 3: the absent-side question", code, story_run.EXIT_PERSON)
        check_eq("A3: the freshness look ran (a changed ticket would have been E-A2)", len(spied["looks"]), 1)
        check_eq("A3: no role, no rework", (spied["roles"], spied["reworks"]), ([], []))
        check_in("A3: the packet is printed", "# Interim report for " + KEY, out)
        check("A3: and sits at the story root", (task_root / "interim-report.md").is_file())
        again = driver_for(root, env, KEY)
        spied2 = fake_world(again, action)           # B5: the second relaunch has a fake world too - the real `where` would dispatch S1
        code2, out2 = run_quiet(again)
        check_eq("A3: a second relaunch with no flag is the same: exit 3: the absent-side question", code2, story_run.EXIT_PERSON)
        check_eq("A3: ... no role, no rework", (spied2["roles"], spied2["reworks"]), ([], []))
        check_in("A3: ... and the packet is printed again", "# Interim report for " + KEY, out2)
    finally:
        harness.cleanup(root)


def stopped_story():
    root, task_root, env = held_story()
    words = root / "stop-words.txt"
    words.write_text("we do not need this feature after all", encoding="utf-8")
    driver_for(root, env, KEY).controller("stop_waiting", "--words-file", str(words))
    return root, task_root, env


def a4_stopped_relaunch_without_flag_prints_and_exits_zero() -> None:
    root, task_root, env = stopped_story()
    try:
        driver = driver_for(root, env, KEY)
        spied = fake_world(driver, {"action": "awaiting_stopped", "cause": "s5_absent_side", "held_from": "S6"})
        code, out = run_quiet(driver)
        check_eq("A4: exit 0", code, 0)
        check_in("A4: the stopped line is printed with the person's words", "we do not need this feature after all", out)
        check_not_in("A4: the flags are in the how-to block, not in the sentence the person reads first", "(--mr", out)
        check_eq("A4: no freshness look, no role, no rework", (spied["looks"], spied["roles"], spied["reworks"]), ([], [], []))
        check_eq("A4: the record stays stopped", bool((pipeline(task_root).get("awaiting") or {}).get("stopped")), True)
    finally:
        harness.cleanup(root)


def a5_a_flag_on_a_stopped_story_arrives() -> None:
    root, task_root, env = stopped_story()
    try:
        driver = driver_for(root, env, KEY, branch="feature/cart")
        fake_world(driver, {"action": "stop", "reason": "done for the test"})
        code, out = run_quiet(driver)
        check_eq("A5: exit 0 (the fake `where` ends the loop)", code, 0)
        record = pipeline(task_root)
        check_eq("A5: the hold - stopped too - is cleared by `arrive`", "awaiting" in record, False)
        check_eq("A5: the side is real", ((record.get("sides") or {}).get("product") or {}).get("reality"), "real")
        check_eq("A5: `implementation_source` is the diff", record.get("implementation_source"), "diff")
        check_not_in("A5: the stopped line is not the answer to a word", "the wait for the code was ended", out)
    finally:
        harness.cleanup(root)


def a6_edges_until_and_continue() -> None:
    root, task_root, env = held_story()
    try:
        driver = driver_for(root, env, KEY, side=[("product", "real")])
        driver.until = "gate_B"
        for kind in ("await_implementation", "awaiting_implementation", "awaiting_stopped"):
            check_eq(f"A6 (F1): `--until` does not swallow {kind} (its handler ends the run itself)", driver.until_reached({"action": kind}), False)
        check_eq("A6: a stop is still a stop under `--until`", driver.until_reached({"action": "stop"}), True)
        check_eq("A6: a plain action is not a stop under `--until`", driver.until_reached({"action": "prepare_stage", "stage": "S3"}), False)
        cmd = driver_for(root, env, KEY, side=[("backend", "substituted"), ("product", "real")], reference=[("ui", "Old")]).continue_command()
        check_in("A6: `continue_command` repeats --side", "--side backend=substituted --side product=real", cmd)
        check_in("A6: ... and --reference", "--reference ui=Old", cmd)
        # F2: only a RECORDED side that is not real yet is an arrival word
        out = io.StringIO()
        for label, name in (("an unrecorded name", "ghost"), ("a case variant of a recorded side", "Product")):
            driver = driver_for(root, env, KEY, side=[(name, "real")])
            with contextlib.redirect_stdout(out):
                driver.arrival_keep()
            check_eq(f"A6 (F2): `--side {name}=real` ({label}) leaves no pending word", "arrival" in driver.state.get("launch", {}), False)
        check_in("A6 (F2): ... and says so in one line", "is not a part of this story's product that was waiting", out.getvalue())
        named = driver_for(root, env, KEY, side=[("product", "real")])
        named.arrival_keep()
        check_eq("A6: the recorded absent side named real IS a pending arrival", (named.state["launch"].get("arrival") or {}).get("side"),
                 {"product": "real"})
        named.state["launch"].pop("arrival")             # that word was kept on disk by the line above; the next check starts clean
        named.save_state()
        set_product(root, env, reality="real")
        again = driver_for(root, env, KEY, side=[("product", "real")])
        with contextlib.redirect_stdout(io.StringIO()):
            again.arrival_keep()
        check_eq("A6: `--side product=real` on a real side leaves no pending word", "arrival" in again.state.get("launch", {}), False)
    finally:
        harness.cleanup(root)


def a7_await_record_and_until() -> None:
    import story_run
    root, task_root, env = parked_story()
    try:
        driver = driver_for(root, env, KEY, side=[("product", "absent")])
        spied = fake_world(driver, {"action": "await_implementation", "cause": "s5_absent_side", "held_from": "S6", "sides": {}})
        code, out = run_quiet(driver)
        hold = (pipeline(task_root).get("awaiting") or {})
        check_eq("A7: the run ends with the person's question (exit 3) over the absent side (t-2559 W2 B3)",
                 (code, (driver.state.get("asked") or {}).get("kind"), driver.state.get("absent_side")), (story_run.EXIT_PERSON, "absent_side", "product"))
        check_eq("A7: the await record names the packet", hold.get("packet"), "interim-report.md")
        check_eq("A7: ... the cause and the place it holds from travelled from the action", (hold.get("cause"), hold.get("held_from")),
                 ("s5_absent_side", "S6"))
        check_in("A7: the packet is printed", "# Interim report for " + KEY, out)
        check_eq("A7: no role, no rework", (spied["roles"], spied["reworks"]), ([], []))
        check_not_in("A7 (F7): the restart line carries no `--side product=absent` beside the branch", "--side product=absent", out)
    finally:
        harness.cleanup(root)
    root, task_root, env = parked_story()
    try:
        driver = driver_for(root, env, KEY)
        driver.until = "gate_B"
        fake_world(driver, {"action": "await_implementation", "cause": "s5_absent_side", "held_from": "S6", "sides": {}})
        code, out = run_quiet(driver)
        check_eq("A7 (F1): `--until gate_B` still writes the await record", bool((pipeline(task_root).get("awaiting") or {}).get("packet")), True)
        check_in("A7 (F1): ... and the packet is printed", "# Interim report for " + KEY, out)
        check_eq("A7 (F1): ... and the run ends with the question about the absent side (exit 3; the question follows the packet)", code,
                 story_run.EXIT_PERSON)
    finally:
        harness.cleanup(root)


def accepted_world(driver, dispatches: dict) -> list:
    """A fake controller state of accepted work and a `rework` that registers the dispatch the way the controller does. Returns the calls."""
    state = {"revision": 1, "dispatches": dispatches}
    calls: list = []
    driver.controller_state = lambda: state

    def rework(stage, role, cases, reason, **kw):
        did = f"{stage}-r{len(calls)}"
        state["dispatches"][did] = {"stage": stage, "role": role, "status": "accepted", "repair_cause": kw.get("cause"), "person_words": False}
        calls.append((stage, role, kw.get("cause"), kw.get("purpose"), kw.get("complete")))
    driver.rework = rework
    return calls


ACCEPTED = {"S1-qa-scout-1": {"stage": "S1", "role": "qa-scout", "status": "accepted"},
            "S2-qa-requirements-tester-1": {"stage": "S2", "role": "qa-requirements-tester", "status": "accepted"},
            "S5-qa-automator-1": {"stage": "S5", "role": "qa-automator", "status": "accepted"}}
OWED = {"stages": ["S1", "S2", "S5"], "reason": "the code has arrived", "at": "t", "before": []}


def a8_arrival_rework_in_order_after_the_ticket_and_across_a_crash() -> None:
    root, task_root, env = seed(KEY)
    try:
        driver = driver_for(root, env, KEY)
        calls = accepted_world(driver, {did: dict(d) for did, d in ACCEPTED.items()})
        driver.state["arrival_rework"] = dict(OWED)
        turns = []
        with contextlib.redirect_stdout(io.StringIO()):
            turns = [driver.arrival_rework_step() for _ in range(6)]
        check_eq("A8 (B1): S1, S2, then the S5 bind round - one per turn, by cause `source_arrived`", calls,
                 [("S1", "qa-scout", "source_arrived", None, True), ("S2", "qa-requirements-tester", "source_arrived", None, True),
                  ("S5", "qa-automator", "source_arrived", "bind", None)])
        check_eq("A8: a turn that moved something says True; the turn after the list is done says False", turns, [True, True, True, True, False, False])
        check_eq("A8: after the last stage the record is dropped", "arrival_rework" in driver.state, False)
    finally:
        harness.cleanup(root)
    root, task_root, env = seed(KEY)
    try:
        # the ticket's rework first, in the loop's own order (E-A2): the ticket step answers True until it is done, then the arrival's
        driver = driver_for(root, env, KEY)
        order = []
        ticket = iter([True, False, False, False])
        arrival = iter([True, False, False])
        driver.ticket_rework_step = lambda: (order.append("ticket"), next(ticket))[1]
        driver.arrival_rework_step = lambda: (order.append("arrival"), next(arrival))[1]
        driver.seam_rework_step = lambda: (order.append("seam"), False)[1]
        driver.where = lambda: (order.append("where"), STOP)[1]
        driver.ticket_freshness_entry = lambda: "none"
        run_quiet(driver)
        check_eq("A8: while the ticket's step moves, the arrival's is not asked (E-A2): ticket, ticket, then arrival", order[:3],
                 ["ticket", "ticket", "arrival"])
        check_eq("A8: and the arrival's step comes before the seam's and `where`", order.index("arrival") < order.index("seam") < order.index("where"), True)
    finally:
        harness.cleanup(root)
    root, task_root, env = seed(KEY)
    try:
        shared = {did: dict(d) for did, d in ACCEPTED.items()}
        first = driver_for(root, env, KEY)
        calls = accepted_world(first, shared)
        first.state["arrival_rework"] = dict(OWED)
        first.save_state()
        with contextlib.redirect_stdout(io.StringIO()):
            first.arrival_rework_step()              # S1 is dispatched, then the process dies
        second = driver_for(root, env, KEY)          # a new process: the record is on disk
        check_eq("A8 (crash): the record survived the process", (second.state.get("arrival_rework") or {}).get("stages"), ["S1", "S2", "S5"])
        calls2 = accepted_world(second, shared)
        with contextlib.redirect_stdout(io.StringIO()):
            second.arrival_rework_step()
        check_eq("A8 (crash): the next process goes on where the last stopped (S2, not S1 again)", (calls, calls2),
                 ([("S1", "qa-scout", "source_arrived", None, True)], [("S2", "qa-requirements-tester", "source_arrived", None, True)]))
    finally:
        harness.cleanup(root)
    root, task_root, env = seed(KEY)
    try:
        driver = driver_for(root, env, KEY)
        calls = accepted_world(driver, {})
        driver.state["arrival_rework"] = dict(OWED)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            driver.arrival_rework_step()
        check_eq("A8: a story with no accepted work of the stage's role gets a line and is skipped, no dispatch", calls, [])
        check_in("A8: ... the line names the stage", "S1 has no accepted work to make again", out.getvalue())
    finally:
        harness.cleanup(root)


def not_waiting_first_process(branch="feat"):
    """A finished all-real story relaunched with `--branch`: the first process asks `arrival.not_waiting`. (root, task_root, env, first, seen)."""
    root, task_root, env = seed(KEY)
    first = driver_for(root, env, KEY, branch=branch)
    seen = watch_controller(first)
    fake_world(first, STOP)
    code, _out = run_quiet(first)
    check_eq("A9: the first process asks the question (the person's exit code)", code, 3)
    check_eq("A9: ... it is the `arrival_not_waiting` question", (first.state.get("asked") or {}).get("kind"), "arrival_not_waiting")
    check_eq("A9: ... nothing was recorded for the word yet", (("controller", "arrive") in seen, "implementation_source" in pipeline(task_root)),
             (False, False))
    return root, task_root, env


def a9_not_waiting_tokens() -> None:
    for token in ("ignore", "stop", "re-ground"):
        root, task_root, env = not_waiting_first_process()
        try:
            answer = root / "answer.txt"
            answer.write_text(token + "\n", encoding="utf-8")
            second = driver_for(root, env, KEY, answer=str(answer))
            seen = watch_controller(second)
            fake_world(second, STOP)
            code, out = run_quiet(second)
            arrived = ("controller", "arrive") in seen
            if token == "ignore":
                check_eq("A9 ignore: the run goes on (exit 0), the word is dropped, no `arrive`", (code, arrived, "arrival" in second.state["launch"]),
                         (0, False, False))
                check_eq("A9 ignore: the question is not asked again", (second.state.get("asked") or {}), {})
            elif token == "stop":
                check_eq("A9 stop: exit 0, nothing written, no `arrive`", (code, arrived, "implementation_source" in pipeline(task_root)),
                         (0, False, False))
                check_in("A9 stop: the line says nothing was run", "nothing was run and nothing was changed", out)
            else:
                check_eq("A9 re-ground: `arrive` is recorded and the diff is the implementation source", (code, arrived,
                         pipeline(task_root).get("implementation_source")), (0, True, "diff"))
                check_in("A9 re-ground: the rework it owes is walked (no accepted work here: each stage is skipped by name)",
                         "S1 has no accepted work to make again", out)
        finally:
            harness.cleanup(root)
    root, task_root, env = held_story()
    try:
        driver = driver_for(root, env, KEY, branch="feat")
        fake_world(driver, STOP)
        code, out = run_quiet(driver)
        check_eq("A9 (E-A5 b): on a HELD story the same flag is an arrival, not a question", (code, "awaiting" in pipeline(task_root)), (0, False))
    finally:
        harness.cleanup(root)


def a10_replay_and_s5_dispatch() -> None:
    import story_run
    root, task_root, env = held_story()
    try:
        first = driver_for(root, env, KEY)
        first.state.setdefault("launch", {})["arrival"] = {"source": {"branch": "b"}, "side": {}}
        first.save_state()
        real = first.controller

        def crash(op, *args, **kwargs):
            if op == "arrive":
                raise RuntimeError("the process died between stage_done and arrive")
            return real(op, *args, **kwargs)
        first.controller = crash
        try:
            first.arrival_record()
            check("A10: the crash was injected", False)
        except RuntimeError:
            pass
        check_eq("A10 (F3): `becomes` is stored before the first write", first.state["launch"]["arrival"].get("becomes"), ["product"])
        check_eq("A10: `stage_done` had already made the side real", ((pipeline(task_root).get("sides") or {}).get("product") or {}).get("reality"), "real")
        second = driver_for(root, env, KEY)
        seen = []
        real2 = second.controller

        def spy(op, *args, **kwargs):
            seen.append((op, (kwargs.get("input_data") or {}).get("sides")))
            return real2(op, *args, **kwargs)
        second.controller = spy
        with contextlib.redirect_stdout(io.StringIO()):
            second.arrival_record()
        check_eq("A10 (F3): the replay records the SAME sides (not `[]` read from the now-real side)", [s for op, s in seen if op == "arrive"],
                 [["product"]])
        check_eq("A10: the pending word is spent and the rework is owed in the same save", ("arrival" in second.state["launch"],
                 (second.state.get("arrival_rework") or {}).get("stages")), (False, ["S1", "S2", "S5"]))
    finally:
        harness.cleanup(root)
    root, task_root, env = parked_story()
    try:
        driver = driver_for(root, env, KEY)
        sent = []
        driver.controller = lambda op, **kw: sent.append((op, kw.get("input_data")))
        driver.controller_state = lambda: {"revision": 3, "dispatches": {
            "S5-a": {"stage": "S5", "status": "accepted"}, "S5-b": {"stage": "S5", "status": "rejected"},
            "S5-c": {"stage": "S5", "status": "accepted"}, "S5-d": {"stage": "S5", "status": "superseded"}}}
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                driver._act_await_implementation({"action": "await_implementation", "cause": "s5_absent_side", "held_from": "S6"})
        except (story_run.Stop, story_run.Person):      # the parked story has an absent side of its own: the hold asks about it (t-2559)
            pass
        check_eq("A10 (F8): the await record's S5 dispatch is the newest ACCEPTED one", sent[0][1]["s5_dispatch"], "S5-c")
    finally:
        harness.cleanup(root)


FL_ACTION = {"action": "awaiting_implementation", "cause": "first_look_stop", "held_from": "S3"}


def first_look_held_story():
    """(root, task_root, env): a seeded story with EVERY side real that the person stopped after the first look - the controller holds it
    with cause `first_look_stop`, held from S3 (t-2277 FL-6)."""
    root, task_root, env = seed(KEY)
    driver = driver_for(root, env, KEY)
    driver.controller("await", input_data={"packet": "interim-report.md", "s5_dispatch": None, "cause": "first_look_stop", "held_from": "S3",
                                           "idempotency_key": "await:fl", "expected_revision": driver.controller_state().get("revision", 0)})
    return root, task_root, env


def a11_arrival_after_first_look_stop() -> None:
    """FL-6 item 2 (B2): a flag on a `first_look_stop` hold records the arrival, owes S1 and S2 (no S5 bind round, no affected rows) and
    the loop goes on to `where` - the S3 of the flow; the position invariant of PC-7 holds."""
    root, task_root, env = first_look_held_story()
    try:
        driver = driver_for(root, env, KEY, branch="feature/cart")
        order = watch_controller(driver)
        spied = fake_world(driver, STOP)
        seen_where = []
        driver.where = lambda: (seen_where.append(len(order)), STOP)[1]
        code, out = run_quiet(driver)
        record = pipeline(task_root)
        check_eq("A11 arrival_after_first_look_stop_goes_s1_s2_then_s3: the hold is lifted by `arrive` and the source is the diff",
                 ("awaiting" in record, record.get("implementation_source")), (False, "diff"))
        check_eq("A11 arrival_after_first_look_stop_goes_s1_s2_then_s3: the run ends well", code, 0)
        check_in("A11 arrival_after_first_look_stop_goes_s1_s2_then_s3: S1 is made again from the arrived code", "S1 has no accepted work to make again", out)
        check_in("A11 arrival_after_first_look_stop_goes_s1_s2_then_s3: ... then S2", "S2 has no accepted work to make again", out)
        check_not_in("A11 no_bind_after_first_look_stop: S5 (the bind round) is not owed - S5 never ran", "S5 has no accepted work", out)
        check_eq("A11 arrival_after_first_look_stop_goes_s1_s2_then_s3: `arrive` is the first controller call, `where` (S3's flow) comes after it",
                 (order[0], len(seen_where) >= 1 and seen_where[0] >= 1), (("controller", "arrive"), True))
        check_eq("A11: no role ran, and the reworks of S1 and S2 were walked, not dispatched here (no accepted work in a seeded story)",
                 (spied["roles"], spied["reworks"]), ([], []))
    finally:
        harness.cleanup(root)


def a12_no_bind_and_no_affected_rows_after_first_look_stop() -> None:
    root, task_root, env = first_look_held_story()
    try:
        driver = driver_for(root, env, KEY, branch="feature/cart")
        fake_world(driver, STOP)
        with contextlib.redirect_stdout(io.StringIO()):
            driver.arrival_keep()
            driver.arrival_record()
        owed = driver.state.get("arrival_rework") or {}
        check_eq("A12 no_bind_after_first_look_stop: the record owes S1 and S2 only, never the S5 bind round", owed.get("stages"), ["S1", "S2"])
        calls = accepted_world(driver, {did: dict(d) for did, d in ACCEPTED.items()})
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            turns = [driver.arrival_rework_step() for _ in range(4)]
        check_eq("A12 no_bind_after_first_look_stop: S1, S2 by cause `source_arrived`, no `bind` purpose, no S5 even with accepted S5 work", calls,
                 [("S1", "qa-scout", "source_arrived", None, True), ("S2", "qa-requirements-tester", "source_arrived", None, True)])
        check_eq("A12: the turns say True twice for the stages, once for the end of the list, then False", turns, [True, True, True, False])
        check_in("A12 no_affected_rows_rework_after_first_look_stop: the list ends without reading the affected rows - no row is reopened",
                 "no row is reopened and gate A stands", out.getvalue())
        check_eq("A12 no_affected_rows_rework_after_first_look_stop: no other rework is on the record (ticket, seam, answer)",
                 [key for key in ("ticket_rework", "seam_rework", "answer_rework", "arrival_rework") if key in driver.state], [])
    finally:
        harness.cleanup(root)


def a13_ticket_question_still_first_on_first_look_arrival() -> None:
    """PC-7's position invariant on the new branch: the changed-ticket question first, the source word survives the question, the arrival
    is written before any rework of the ticket answer."""
    import story_run
    root, task_root, env = first_look_held_story()
    try:
        first = driver_for(root, env, KEY, branch="feature/cart")
        changed = story_run.Person("ticket_changed", "The ticket text changed while the story waited. Which text stands?", "S2")
        spied = fake_world(first, STOP, freshness=changed)
        code, _out = run_quiet(first)
        check_eq("A13 ticket_question_still_first_on_first_look_arrival: the changed-ticket question is asked first", code, 3)
        check_eq("A13: ... the source word survives it", (first.state["launch"].get("arrival") or {}).get("source"), {"branch": "feature/cart"})
        check_eq("A13: ... the hold stands, no role ran", (bool(pipeline(task_root).get("awaiting")), spied["roles"] + spied["reworks"]), (True, []))
        answer = root / "answer.txt"
        answer.write_text("new text\n", encoding="utf-8")
        second = driver_for(root, env, KEY, answer=str(answer))
        order = watch_controller(second)
        fake_world(second, STOP)
        second.take_ticket_answer = lambda words, qtext, stage, dispatch: second.state.__setitem__(
            "ticket_rework", {"stages": ["S2"], "words": words, "at": "t", "before": []})

        def ticket_step():
            order.append(("rework", "S2", "ticket_changed"))
            second.state.pop("ticket_rework", None)
            return False
        second.ticket_rework_step = ticket_step
        code2, _out2 = run_quiet(second)
        names = [item for item in order if item[0] == "rework" or item == ("controller", "arrive")]
        check_eq("A13: the answer run records the arrival BEFORE the ticket answer's rework", (code2, names[:2]),
                 (0, [("controller", "arrive"), ("rework", "S2", "ticket_changed")]))
        check_eq("A13: ... and the hold is lifted", "awaiting" in pipeline(task_root), False)
    finally:
        harness.cleanup(root)


def a14_stopped_first_look_story_prints_cause_line() -> None:
    root, task_root, env = first_look_held_story()
    try:
        words = root / "stop-words.txt"
        words.write_text("the feature does not work on the stand", encoding="utf-8")
        driver_for(root, env, KEY).controller("stop_waiting", "--words-file", str(words))
        driver = driver_for(root, env, KEY)
        spied = fake_world(driver, {"action": "awaiting_stopped", "cause": "first_look_stop", "held_from": "S3"})
        code, out = run_quiet(driver)
        check_eq("A14 stopped_first_look_story_prints_cause_line: exit 0", code, 0)
        check_in("A14: the line names the first look and the person's words", "after the first look, when the feature did not work: \"the feature does not work on the stand\"", out)
        check_in("A14: ... says nothing runs and names the three flags", "Nothing runs. To check new code, start the story again with --mr <link>, --branch <name> or --commit <sha>", out)
        check_not_in("A14: it is not the missing-side line", "the wait for the code was ended", out)
        check_eq("A14: no freshness look, no role, no rework", (spied["looks"], spied["roles"], spied["reworks"]), ([], [], []))
        flagged = driver_for(root, env, KEY, branch="feature/cart")
        fake_world(flagged, STOP)
        run_quiet(flagged)
        check_eq("A14: a flag on the stopped first-look story arrives (J-9 does not apply: the person ended the wait)", "awaiting" in pipeline(task_root), False)
    finally:
        harness.cleanup(root)


def a15_side_words_on_a_first_look_hold() -> None:
    root, task_root, env = first_look_held_story()
    try:
        driver = driver_for(root, env, KEY, side=[("product", "absent")])
        spied = fake_world(driver, FL_ACTION)
        driver.first_look_code_look = lambda action: False          # the code look is not the subject here: the hold is
        code, _out = run_quiet(driver)
        check_eq("A15 side_absent_relaunch_keeps_hold: `--side product=absent` is recorded as the restart's word, the hold stands, no arrival",
                 (code, bool(pipeline(task_root).get("awaiting")), (driver.state["launch"].get("side") or {}).get("product"),
                  "arrival" in driver.state["launch"]), (0, True, "absent", False))
        check_eq("A15: ... and no role ran", (spied["roles"], spied["reworks"]), ([], []))
    finally:
        harness.cleanup(root)
    root, task_root, env = first_look_held_story()
    try:
        driver = driver_for(root, env, KEY, side=[("product", "real")])
        fake_world(driver, FL_ACTION)
        driver.first_look_code_look = lambda action: False
        code, out = run_quiet(driver)
        check_eq("A15 side_real_already_real_is_no_trigger: `--side product=real` on a side already real is no arrival word (m-new-6)",
                 (code, "arrival" in driver.state["launch"], bool(pipeline(task_root).get("awaiting"))), (0, False, True))
        check_in("A15: ... one line says so, and the flow is the bare relaunch's (the code look)", "is not a part of this story's product that was waiting", out)
    finally:
        harness.cleanup(root)


def main() -> None:
    run_scenarios([], [
        a11_arrival_after_first_look_stop,
        a12_no_bind_and_no_affected_rows_after_first_look_stop,
        a13_ticket_question_still_first_on_first_look_arrival,
        a14_stopped_first_look_story_prints_cause_line,
        a15_side_words_on_a_first_look_hold,
        a1_branch_word_survives_changed_ticket_question,
        a2_no_role_before_the_ticket_answer,
        a3_reprint_with_no_dispatch,
        a4_stopped_relaunch_without_flag_prints_and_exits_zero,
        a5_a_flag_on_a_stopped_story_arrives,
        a6_edges_until_and_continue,
        a7_await_record_and_until,
        a8_arrival_rework_in_order_after_the_ticket_and_across_a_crash,
        a9_not_waiting_tokens,
        a10_replay_and_s5_dispatch,
    ])
    harness.finish("test_story_run_arrival")


if __name__ == "__main__":
    main()
