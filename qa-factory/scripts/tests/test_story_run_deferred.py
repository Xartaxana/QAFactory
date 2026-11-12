"""RN1-24 (P22): a question about SOME manual cases does not hold the work that does not depend on them (K-D1..K-D7 of t-1700).

Nothing here reaches the network or a real model. The rig is `test_story_run_s6`'s manual rig (a fake controller class, the role and
the code-only receipt recorded); `where` and `dispatch_action` are replaced so that `Driver.run` is the loop under test.
"""
import contextlib
import io
import json
import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
import story_run_common  # noqa: E402
from story_run_common import (  # noqa: E402
    check, check_in, check_not_in, d2_answer, d2_pipeline, d2_seed, driver_for, eq, run_scenarios, s0_state,
)
from test_story_run_s6 import AWAITS, manual_rig, t292_config  # noqa: E402

TASK = "QA-9"
UI = "QA-9_TC_001"            # a screen case: the stand's sign-in account is missing for it
API = "QA-9_TC_003"           # a case that opens no screen
UI_2 = "QA-9_TC_002"
POLICY = {UI: "ui", UI_2: "ui", API: "api"}


def rig(root, env, cases, scope):
    """(driver, world, launched, moves) at S6 with the stand's account missing (no `environment.env_file`) and `scope` the story's scope."""
    t292_config(root)
    driver, world, launched, moves = manual_rig(root, env, TASK, cases, policy=POLICY)
    driver.controller_state = lambda: {"dispatches": world.dispatches, "scope": list(scope)}
    return driver, world, launched, moves


def loop(driver, world, actions, seen):
    """`where` yields `actions` in order; a stage-S6 action is one `run_manual_block` over the scope the driver was given, S7 and
    gate B are recorded. The new dispatches are accepted at once (the runner finished)."""
    queue = list(actions)
    driver.where = lambda: queue.pop(0)

    def act(action):
        if action.get("action") == "await_gate":
            seen.append(("gate", action["gate"]))
            return driver._act_await_gate(action)
        seen.append((action["stage"],))
        if action["stage"] == "S6":
            before = set(world.dispatches)
            driver.run_manual_block(list(action["cases"]))
            for dispatch_id in sorted(set(world.dispatches) - before):
                world.accept(dispatch_id)
                # X7-6c: S6 closes only over the consumer's (failure analyst's) record for the author's last dispatch; the analyst has judged it
                story_run_common.accept_record(driver.task_root, "S6", dispatch_id)
    driver.dispatch_action = act


def run_quiet(driver, world=None):
    out = io.StringIO()
    fake = world.controller_class() if world else mock.MagicMock()
    with mock.patch("controller.Controller", fake), contextlib.redirect_stdout(out):
        code = driver.run()
    return code, out.getvalue()


def stand_person(driver, cases):
    """The stand-sign-in question as `stand_login_gate` raises it (the real builder, the real fields)."""
    person = driver.site_seam_person("stand_login", driver.stand_login_question_text(list(cases), "no_file"), "S6",
                                     block=driver.STAND_LOGIN_BLOCK, details="where the account is looked for")
    person.login_cases, person.holds = list(cases), tuple(cases)
    return person


def gate_stubs(driver, gates):
    driver.ticket_freshness_entry = lambda: None
    driver.gate_repair = lambda gate: {"ran": False, "top": ""}
    driver.gate = lambda gate, top="": gates.append(gate)


def k_d1_the_question_waits_and_the_other_case_goes_on() -> None:
    """K-D1: TC_001 (screen, no account) is held, TC_003 is dispatched, the question is in `deferred`, there is no exit 3, S7 starts."""
    root, task_root, env = d2_seed(TASK, environment="Local", pending=False)
    try:
        cases = [UI, API]
        driver, world, launched, moves = rig(root, env, cases, scope=cases)
        seen = []
        entry = {"action": "prepare_stage", "stage": "S6", "cases": cases}
        loop(driver, world, [entry, entry, entry, {"action": "prepare_stage", "stage": "S7"}, {"action": "stop", "reason": "end of test"}], seen)
        code, printed = run_quiet(driver, world)
        eq("K-D1 the run ends without a stop for the person (exit 0)", code, 0)
        eq("K-D1 the case that does not depend on the question is dispatched, the held one is not", [e["scope"] for e in launched], [[API]])
        state = s0_state(task_root)
        eq("K-D1 the question is deferred: kind, stage, the cases it holds", [(i["kind"], i["stage"], i["holds"]) for i in state["deferred"]],
           [("stand_login", "S6", [UI])])
        eq("K-D1 and no question is open now", state.get("asked"), {})
        check("K-D1 the live question file is not there; the deferred one is", not (task_root / "state" / "driver-question.md").is_file()
              and (task_root / "state" / "deferred-questions" / "1.md").is_file())
        check_in("K-D1 the login flag went with the question", "login_question", json.dumps(state["deferred"][0]["flags"]))
        check_not_in("K-D1 and is not left on the live state", "login_question", json.dumps({k: v for k, v in state.items() if k != "deferred"}))
        check_in("K-D1 a progress line says it waits and is asked before gate B", "waits for you; the other work goes on; it is asked before gate B", printed)
        check("K-D1 S6 closes over the rest with the code-only receipt, and S7 starts afterwards",
              [m[0] for m in moves if m[0] in ("code_only", "stage_done")] == ["code_only", "stage_done"] and seen[-1] == ("S7",), repr((moves, seen)))
        request = json.loads((task_root / "work" / "evidence" / "manual" / UI / "request.json").read_text(encoding="utf-8"))
        eq("K-D1 the held case stands as left unchecked, in the safe default, and says whose answer it waits for",
           (request["refused"]["by"], "waits for your answer to question 1" in request["refused"]["reason"]), ("left_unchecked", True))
        row = [json.loads(l) for l in (task_root / "state" / "driver-questions.jsonl").read_text(encoding="utf-8").splitlines()][-1]
        eq("K-D1 the question has its driver-questions.jsonl row, as a live one", (row["kind"], row["source"]), ("stand_login", "code"))
        eq("K-D1 the last block did not close S6 on the runner's word: it awaits the consumer (X7-6c; a held case is outside the cover)", [e["complete"] for e in launched], [AWAITS])
    finally:
        harness.cleanup(root)


def k_d2_d3_gate_b_waits_for_every_deferred_question_one_by_one() -> None:
    """K-D2: two deferred questions -> two stops before gate B ("1 of 2", "2 of 2"), gate B after the second answer.
    K-D3: gate B is not shown while one is unanswered; a run with no answer asks the same item again, and FR-7 does not fire."""
    root, task_root, env = d2_seed(TASK, environment="Local", pending=False)
    try:
        d2_pipeline(task_root, stages={"S0": {"status": "done"}, "S6": {"status": "done"}})
        scope = [UI, UI_2, API]
        driver = driver_for(root, env, TASK)
        driver.controller_state = lambda: {"dispatches": {}, "scope": scope}
        with contextlib.redirect_stdout(io.StringIO()):
            driver.defer_question(stand_person(driver, [UI]))
            driver.defer_question(stand_person(driver, [UI_2]))
        eq("K-D2 two items are deferred, numbered 1 and 2", [i["n"] for i in s0_state(task_root)["deferred"]], [1, 2])
        check_not_in("K-D2 the first item's text carries no 'more question(s) wait' line (asked while deferring)", "more question(s) wait",
                     (task_root / "state" / "deferred-questions" / "1.md").read_text(encoding="utf-8"))

        def entry(answer=None):
            fresh = driver_for(root, env, TASK, answer=answer)
            gates, seen = [], []
            gate_stubs(fresh, gates)
            loop(fresh, mock.MagicMock(), [{"action": "await_gate", "gate": "B"}, {"action": "stop", "reason": "end of test"}], seen)
            code, printed = run_quiet(fresh)
            return code, printed, gates, fresh

        code, printed, gates, fresh = entry()
        eq("K-D2 first entry to gate B: exit 3 and gate B is NOT shown", (code, gates), (3, []))
        check_in("K-D2 the first stop is 'question 1 of 2'", "question: 1 of 2, waiting since S6", printed)
        asked = s0_state(task_root)["asked"]
        eq("K-D2 the restored question is the open one, with its seam tokens and its item number", (asked["kind"], asked["deferred_n"], asked["offered"]),
           ("stand_login", 1, ["retry", "by hand", "go on"]))
        eq("K-D2 and its flag is back for the original answer branch", s0_state(task_root).get("login_question"), {"stage": "S6", "cases": [UI]})
        first_sha = __import__("story_run").question_body_sha((task_root / "state" / "driver-question.md").read_text(encoding="utf-8"))

        code, printed, gates, fresh = entry()
        eq("K-D3 a run with no answer asks the same item again (exit 3), gate B still not shown", (code, gates), (3, []))
        check_in("K-D3 it is still 'question 1 of 2'", "question: 1 of 2, waiting since S6", printed)
        check_not_in("K-D3 FR-7 does not fire: the text is the same and there was no answer", "You have answered this exact question before", printed)
        eq("K-D3 the body hash is the same (the head line sits inside the machine head)", __import__("story_run").question_body_sha(
            (task_root / "state" / "driver-question.md").read_text(encoding="utf-8")), first_sha)
        eq("K-D3 nothing was dropped", len(s0_state(task_root)["deferred"]), 2)

        code, printed, gates, fresh = entry(d2_answer(root, "go on"))
        eq("K-D2 the first answer is taken and the second question is asked: exit 3, no gate B", (code, gates), (3, []))
        check_in("K-D2 the second stop is 'question 2 of 2'", "question: 2 of 2, waiting since S6", printed)
        eq("K-D2 the answered item is dropped, the other stays", [i["n"] for i in s0_state(task_root)["deferred"]], [2])
        check_in("K-D2 the answer reached the original question's branch (its typed record of the choice)", "go on", json.dumps(s0_state(task_root).get("login_choice")))

        code, printed, gates, fresh = entry(d2_answer(root, "go on"))
        eq("K-D2 after the last answer gate B is shown and the run goes on", (code, gates), (0, ["B"]))
        state = s0_state(task_root)
        eq("K-D2 nothing is deferred and no round is left open", (state["deferred"], state.get("deferred_round"), state["asked"]), ([], None, {}))
    finally:
        harness.cleanup(root)


def k_d4_k_d5_what_is_not_deferred_is_asked_at_once() -> None:
    """K-D4: `holds` covers the whole scope and there is no other half -> asked at once (exit 3, nothing deferred).
    K-D5: a Person with no `holds`, a gate question and the conductor's stop (EXIT_GAVE_UP) are never set aside."""
    import story_run
    root, task_root, env = d2_seed(TASK, environment="Local", pending=False)
    try:
        cases = [UI, UI_2]
        driver, world, launched, moves = rig(root, env, cases, scope=cases)
        entry = {"action": "prepare_stage", "stage": "S6", "cases": cases}
        loop(driver, world, [entry, {"action": "stop", "reason": "end of test"}], [])
        code, _printed = run_quiet(driver, world)
        state = s0_state(task_root)
        eq("K-D4 every case of the scope is held: the question is asked at once (exit 3)", code, 3)
        eq("K-D4 it is the open question and nothing is deferred", (state["asked"]["kind"], state.get("deferred")), ("stand_login", None))
        check("K-D4 nothing was dispatched", launched == [])

        driver = driver_for(root, env, TASK)
        driver.controller_state = lambda: {"dispatches": {}, "scope": [UI, API]}
        person = stand_person(driver, [UI])
        check("K-D5 control: a question with `holds` and a case outside them is deferrable", driver.deferrable(person))
        person.holds = ()
        check("K-D5 a Person with no `holds` (the default) is not deferrable", not driver.deferrable(person))
        check("K-D5 and a fresh Person has none", story_run.Person("conductor", "t").holds == ())
        gate = stand_person(driver, [UI])
        gate.kind = "gate_B"
        check("K-D5 a gate question is not deferrable even with `holds`", not driver.deferrable(gate))
        stop = stand_person(driver, [UI])
        stop.code = story_run.EXIT_GAVE_UP
        check("K-D5 the conductor's stop (exit 4) is not deferrable", not driver.deferrable(stop))
        driver.controller_state = lambda: {"dispatches": {}}
        check("K-D5 a scope that cannot be read: not deferrable (a question asked, never withheld)", not driver.deferrable(stand_person(driver, [UI])))
        driver.controller_state = lambda: {"dispatches": {}, "scope": [UI, API]}
        with contextlib.redirect_stdout(io.StringIO()):
            driver.defer_question(stand_person(driver, [UI]))
        check("K-D5 E11: a second question about a case a deferred one holds is not deferrable", not driver.deferrable(stand_person(driver, [UI])))
    finally:
        harness.cleanup(root)


def k_d6_retry_on_a_deferred_question_sends_the_held_cases_back() -> None:
    """K-D6: `retry` on a deferred sign-in question -> the seam's rework of S6 with scope [TC_001] is recorded and the item is dropped;
    the rework step then opens exactly that."""
    k_d6(("retry",))


def k_d6_control_go_on_registers_no_rework() -> None:
    """K-D6 control: `go on` on the same deferred question registers no rework and drops the item (one project per scenario)."""
    k_d6(("go on",))


def k_d6(words) -> None:
    import controller as C
    scope = [UI, API]
    for word in words:
        root, task_root, env = d2_seed(TASK, environment="Local", pending=False)
        try:
            d2_pipeline(task_root, stages={"S0": {"status": "done"}, "S6": {"status": "done"}})

            calls = []          # the reworks the loop's `seam_rework_step` registers (the controller call is replaced)

            def deferred_driver(answer=None):
                driver = driver_for(root, env, TASK, answer=answer)
                driver.controller_state = lambda: {"dispatches": {}, "scope": scope}
                driver.no_move_facts = lambda state: {"rework_stages": ["S6"], "rework_roles": {"S6": ["qa-runner"]}, "scope": scope,
                                                      "causes": list(C.REPAIR_CAUSES), "gate": ""}
                driver.rework = lambda stage, role, cases, reason, **kw: calls.append((stage, role, cases, kw.get("cause"), reason))
                return driver
            first = deferred_driver()
            with contextlib.redirect_stdout(io.StringIO()):
                first.defer_question(stand_person(first, [UI]))
            for answer in (None, d2_answer(root, word)):        # the first entry to gate B asks the item; the second takes the answer
                entering = deferred_driver(answer)
                gate_stubs(entering, [])
                loop(entering, mock.MagicMock(), [{"action": "await_gate", "gate": "B"}, {"action": "stop", "reason": "end of test"}], [])
                run_quiet(entering)
            state = s0_state(task_root)
            if word == "go on":
                eq("K-D6 control: `go on` registers no rework and the item is dropped", (calls, state["deferred"]), ([], []))
                continue
            eq("K-D6 `retry`: the loop registers ONE rework, S6 / qa-runner, for exactly the held case, as a person's answer",
               [c[:4] for c in calls], [("S6", "qa-runner", [UI], "question_answer")])
            eq("K-D6 ...with the person's word as its reason, the item dropped, no question open and the record consumed",
               (calls[0][4], state["deferred"], state["asked"], state.get("seam_rework")), ("retry", [], {}, None))
        finally:
            harness.cleanup(root)


def k_d8_the_third_holds_site_and_the_question_text() -> None:
    """The seam question over a REFUSED manual S6 dispatch holds that dispatch's manual cases (`_person_of`, why `refusal` only);
    the sign-in question's text says which road it is on."""
    root, task_root, env = d2_seed(TASK, environment="Local", pending=False)
    try:
        driver = driver_for(root, env, TASK)
        dispatches = {"S6-qa-runner-1": {"execution_kind": "manual", "manual_case_ids": [UI, API, UI]},
                      "S6-qa-runner-2": {"execution_kind": "automation", "manual_case_ids": [UI]}, "S6-qa-runner-3": {"execution_kind": "manual"}}
        driver.controller_state = lambda: {"dispatches": dispatches, "scope": [UI, API, UI_2]}
        eq("K-D8 a manual dispatch holds its own case ids, once each", driver.manual_holds("S6-qa-runner-1"), (UI, API))
        eq("K-D8 another execution kind, no ids, an unknown dispatch, no dispatch: nothing held (asked at once)",
           [driver.manual_holds(d) for d in ("S6-qa-runner-2", "S6-qa-runner-3", "S6-qa-runner-9", "")], [(), (), (), ()])
        driver.controller_state = lambda: (_ for _ in ()).throw(OSError("unreadable"))
        eq("K-D8 an unreadable controller state: nothing held", driver.manual_holds("S6-qa-runner-1"), ())
        driver.controller_state = lambda: {"dispatches": dispatches, "scope": [UI, API, UI_2]}
        options = [{"norm": "retry", "move": "person_does"}, {"norm": "go on", "move": "go_on_as_is"}]
        person = driver._person_of({"why": "refusal", "kind": "refusal", "stage": "S6", "dispatch": "S6-qa-runner-1"}, "q", options)
        eq("K-D8 the seam Person of a refusal over that dispatch carries `holds`", person.holds, (UI, API))
        check("K-D8 ...and is deferrable (the scope has a case outside them)", driver.deferrable(person))
        other = driver._person_of({"why": "stop", "kind": "conductor", "stage": "S6", "dispatch": "S6-qa-runner-1"}, "q", options)
        eq("K-D8 a Person of another cause (stop) carries none", other.holds, ())

        waiting = driver.stand_login_question_text([UI], "no_file")
        check_in("K-D8 a question that will wait says the other checks go on and names the cases", f"the other checks go on; these cases wait for your answer: {UI}", waiting)
        check_not_in("K-D8 ...and not the live sentence", "wait for this answer too", waiting)
        driver.controller_state = lambda: {"dispatches": {}, "scope": [UI]}
        live = driver.stand_login_question_text([UI], "no_file")
        check_in("K-D8 a question that is asked at once keeps the live sentence", "the other checks by hand wait for this answer too", live)
        check_not_in("K-D8 ...without the deferred one", "the other checks go on", live)
    finally:
        harness.cleanup(root)


def k_d9_go_on_and_by_hand_after_the_stage_is_closed_are_carried_out() -> None:
    """`go on` / `by hand` on a deferred question: the held case's request.json goes from the waiting reason to the person's decision
    (`by hand` -> person_checks, `go on` -> left_unchecked) and the pass is recorded; a case whose request is not our waiting record is
    left alone; `retry` keeps its road (K-D6)."""
    for word in ("go on", "by hand"):
        root, task_root, env = d2_seed(TASK, environment="Local", pending=False)
        try:
            d2_pipeline(task_root, stages={"S0": {"status": "done"}, "S6": {"status": "done"}})
            scope = [UI, UI_2, API]
            passes = []

            def deferred_driver(answer=None):
                driver = driver_for(root, env, TASK, answer=answer)
                driver.controller_state = lambda: {"dispatches": {}, "scope": scope}
                driver.pass_block = lambda stage, block, rel, lead: passes.append((stage, block, bool(rel)))
                return driver
            first = deferred_driver()
            with contextlib.redirect_stdout(io.StringIO()):
                first.defer_question(stand_person(first, [UI, UI_2]))
            waiting = {"refused": {"reason": "not checked yet: it waits for your answer to question 1, asked before gate B", "door": "d", "by": "left_unchecked"}}
            ran = {"refused": {"reason": "something else", "door": "d", "by": "person_checks"}}
            paths = {}
            for case, body in ((UI, waiting), (UI_2, ran)):
                paths[case] = task_root / "work" / "evidence" / "manual" / case / "request.json"
                paths[case].parent.mkdir(parents=True, exist_ok=True)
                paths[case].write_text(json.dumps(body), encoding="utf-8")
            for answer in (None, d2_answer(root, word)):
                entering = deferred_driver(answer)
                gate_stubs(entering, [])
                loop(entering, mock.MagicMock(), [{"action": "await_gate", "gate": "B"}, {"action": "stop", "reason": "end of test"}], [])
                run_quiet(entering)
            got = json.loads(paths[UI].read_text(encoding="utf-8"))["refused"]
            eq(f"K-D9 `{word}`: the held case carries the person's decision in the typed carrier",
               (got["by"], got["reason"].startswith("not checked by an agent:"), f'the person said: "{word}"' in got["reason"]),
               ("person_checks" if word == "by hand" else "left_unchecked", True, True))
            check(f"K-D9 `{word}`: it no longer says it waits", "waits for your answer" not in got["reason"])
            eq(f"K-D9 `{word}`: a request that is not our waiting record is untouched", json.loads(paths[UI_2].read_text(encoding="utf-8")), ran)
            eq(f"K-D9 `{word}`: the pass of the question's block is recorded at S6, with the answer's file", passes,
               [("S6", "stand login missing", True)])
            eq(f"K-D9 `{word}`: the item is dropped", s0_state(task_root)["deferred"], [])
        finally:
            harness.cleanup(root)


def k_d7_an_unfinished_run_says_what_waits() -> None:
    """K-D7: `--until` reached or `max_boundaries` spent with a deferred question -> the list is printed and the record is kept."""
    root, task_root, env = d2_seed(TASK, environment="Local", pending=False)
    try:
        for label, overrides, actions in (("--until", {"until": "gate_A"}, [{"action": "prepare_stage", "stage": "S5"}]),
                                          ("max_boundaries", {"max_boundaries": 1}, [{"action": "prepare_stage", "stage": "S7"}])):
            driver = driver_for(root, env, TASK, **overrides)
            driver.controller_state = lambda: {"dispatches": {}, "scope": [UI, API]}
            if not s0_state(task_root).get("deferred"):
                with contextlib.redirect_stdout(io.StringIO()):
                    driver.defer_question(stand_person(driver, [UI]))
            driver.state = s0_state(task_root)
            loop(driver, mock.MagicMock(), actions, [])
            driver.dispatch_action = lambda action: None
            code, printed = run_quiet(driver)
            eq(f"K-D7 {label}: the run ends, exit 0", code, 0)
            check_in(f"K-D7 {label}: the list of waiting questions is printed", "1 question(s) wait for you and are asked before gate B: stand_login about " + UI, printed)
            eq(f"K-D7 {label}: the record is kept", [i["holds"] for i in s0_state(task_root)["deferred"]], [[UI]])
    finally:
        harness.cleanup(root)


def e_the_text_is_gone_and_the_ask_tail_line() -> None:
    """A deferred item whose text file is gone is a refusal that says so (never a silent drop); a live question asked while one waits
    ends with ONE line naming the count, and not the texts."""
    import story_run
    root, task_root, env = d2_seed(TASK, environment="Local", pending=False)
    try:
        driver = driver_for(root, env, TASK)
        driver.controller_state = lambda: {"dispatches": {}, "scope": [UI, API]}
        with contextlib.redirect_stdout(io.StringIO()):
            driver.defer_question(stand_person(driver, [UI]))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            driver.ask(story_run.Person("conductor", "A live question about something else."))
        text = (task_root / "state" / "driver-question.md").read_text(encoding="utf-8")
        check_in("tail line: one line with the count, in the answer block", "1 more question(s) wait; they are asked before gate B.", text)
        check_not_in("tail line: not the deferred text", "cannot find that account", text)
        check("tail line: it sits after the answer block marker, so it is not part of the question's hash",
              text.index("1 more question(s) wait") > text.index("\n---\nAnswer:"))
        (task_root / "state" / "deferred-questions" / "1.md").unlink()
        try:
            driver.deferred_step()
            raised = None
        except story_run.Refusal as refusal:
            raised = refusal
        check("a deferred text that is gone: a Refusal naming the file, the item stays", raised is not None and "1.md" in raised.text
              and len(driver.deferred_items()) == 1)
        check("F11: the door names no way the item cannot serve (the item holds no text to write the file from)",
              raised is not None and "write the file again" not in raised.text and "holds no text" in raised.text, str(raised and raised.text))
    finally:
        harness.cleanup(root)


def main() -> None:
    run_scenarios([], [k_d1_the_question_waits_and_the_other_case_goes_on, k_d2_d3_gate_b_waits_for_every_deferred_question_one_by_one,
                       k_d4_k_d5_what_is_not_deferred_is_asked_at_once, k_d6_retry_on_a_deferred_question_sends_the_held_cases_back,
                       k_d6_control_go_on_registers_no_rework, k_d8_the_third_holds_site_and_the_question_text,
                       k_d9_go_on_and_by_hand_after_the_stage_is_closed_are_carried_out,
                       k_d7_an_unfinished_run_says_what_waits, e_the_text_is_gone_and_the_ask_tail_line])
    harness.finish("test_story_run_deferred")


if __name__ == "__main__":
    main()
