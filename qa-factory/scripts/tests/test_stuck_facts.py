#!/usr/bin/env python3
"""B-20 (t-1988 N5): the stuck seam carries facts and asks once.

(1) `Driver.stuck_facts` (pure): the B-20 state (S6 pending, the analyst's accept record stands for the runner's dispatch) names it; a state with
    no earlier stage open gives no lines; an unreadable pipeline or controller state gives no lines (FR-41), at and beyond the edges.
(2) `Driver.stuck_text`: the facts replace "I cannot tell from here"; none keeps today's lead; an earlier answer is named (FR-7).
(3) The loop: the fifth identical `where` answer reaches the seam with the facts as the lead, and `stuck_pending` is written for the answer;
    `take_answer` records `stuck_asked[signature]` (producer); the same step coming back after the answer reaches the seam with the answer
    named in the lead and in `keep` (reader) - not the same text again.

Runs under pytest and as `python -B scripts/tests/test_stuck_facts.py` (exit non-zero on a failure).
"""
import contextlib
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import SCRIPTS, check_eq, check_in, cleanup, finish  # noqa: E402
from story_run_common import driver_for, human_broken, seed  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import story_run  # noqa: E402

RUNNER = "S6-qa-runner-5"
FACT = "S6 pending; acceptance by the failure analyst stands for S6-qa-runner-5"


def eq(name, got, want):
    assert check_eq(name, got, want), f"{name}: expected {want!r}, got {got!r}"


def has(name, needle, text):
    assert check_in(name, needle, text), f"{name}: {needle!r} not in {text!r}"


def controller(**stage_status):
    """A controller state: S0-S5 completed unless named, S6 pending with the runner's accepted, awaiting dispatch."""
    stages = {f"S{i}": {"status": "completed"} for i in range(6)}
    stages["S6"] = {"status": "pending"}
    stages.update({k: v for k, v in stage_status.items()})
    return {"stages": stages, "dispatches": {RUNNER: {"id": RUNNER, "stage": "S6", "role": "qa-runner", "status": "accepted",
                                                      "unresolved": "stage_awaits_acceptance"}}}


def record(reviewed=RUNNER):
    return {"acceptance": {"S6": [{"stage": "S6", "role": "qa-runner", "acceptor": "qa-failure-analyst", "reviewed_dispatch": reviewed,
                                   "verdict": "accept", "failure_class": None, "quote": "", "witness_paths": [], "at": "t"}]}}


FACTS = story_run.Driver.stuck_facts


def test_facts_name_the_b20_state():
    lines = FACTS(controller(), record(), "S7")
    eq("N5.1 the B-20 state: one line, S6 pending, the analyst's acceptance stands for the runner's dispatch", lines, [FACT])
    awaited = FACTS(controller(), {"acceptance": {}, "x": 1}, "S7")
    has("N5.1 no record: the acceptance is awaited for the dispatch", "awaited for S6-qa-runner-5; no accept record stands", awaited[0])
    stale = FACTS(controller(), record("S6-qa-runner-1"), "S7")
    has("N5.1 a record for another dispatch does not stand for this one", "awaited for S6-qa-runner-5", stale[0])
    reason = FACTS(controller(S6={"status": "pending", "reason": "the runner stopped"}), record(), "S7")
    has("N5.1 the controller's reason is carried", "reason: the runner stopped", reason[0])


PERSON_FACT = "the plan stage (S6) is pending; the failure analyst accepted the work of the runner"


def test_f3_the_person_lines_carry_no_dispatch_id_and_no_raw_reason():
    """B-20 F3 (FR-6): the lines a person reads name the stage by its place and the role in plain words; the ids and the controller's raw
    reason are the conductor's and the details file's (`ids=True`)."""
    place = lambda stage: f"the plan stage ({stage})"      # noqa: E731
    state = controller(S6={"status": "pending", "reason": "S6 awaits the acceptance of qa-failure-analyst"})
    eq("F3 person line: place and role words", FACTS(state, record(), "S7", place=place, ids=False),
       [PERSON_FACT])
    awaited = FACTS(state, {"acceptance": {}, "x": 1}, "S7", place=place, ids=False)
    eq("F3 awaited: no id, no reason", awaited, ["the plan stage (S6) is pending; the failure analyst has not accepted the work of the runner yet"])
    stale = FACTS(state, {"acceptance": {}, "x": 1}, "S7", ids=False)
    assert RUNNER not in stale[0] and "qa-" not in stale[0] and stale[0].startswith("stage S6 is pending"), f"F3 default place: {stale}"
    raw = FACTS(state, record(), "S7")
    assert RUNNER in raw[0] and "reason: S6 awaits the acceptance of qa-failure-analyst" in raw[0], f"F3 the factory's lines keep ids and reason: {raw}"
    eq("F3 a person line passes human_broken", human_broken("The step came back.\n\nWhat the factory can read:\n- " + PERSON_FACT), [])
    eq("F3 control: the raw line does not (a dispatch id)", human_broken("The step came back.\n\n- " + raw[0]), ["dispatch_id"])


def test_facts_none_when_no_earlier_stage_is_open():
    done = controller(S6={"status": "completed"})
    eq("N5.2 every earlier stage completed: no lines (today's lead)", FACTS(done, record(), "S7"), [])
    eq("N5.2 the stage itself is not its own earlier stage", FACTS(controller(), record(), "S6"), [])
    skipped = controller(S3={"status": "skipped"}, S6={"status": "completed"})
    eq("N5.2 a skipped stage is not open", FACTS(skipped, record(), "S7"), [])


def test_facts_unreadable_pipeline_or_state_gives_no_lines():
    eq("N5.3 an unreadable pipeline ({}): no lines", FACTS(controller(), {}, "S7"), [])
    eq("N5.3 a pipeline that is not a dict: no lines", FACTS(controller(), None, "S7"), [])
    eq("N5.3 an unreadable controller state: no lines", FACTS({}, record(), "S7"), [])
    eq("N5.3 a controller state that is not a dict: no lines", FACTS(None, record(), "S7"), [])
    eq("N5.3 no stage given: no lines", FACTS(controller(), record(), ""), [])
    eq("N5.3 a row that cannot be read is not a fact", FACTS(controller(S6="broken"), record(), "S7"), [])


class Stub:
    stage_place = staticmethod(lambda stage: f"place of {stage}")
    stuck_text = story_run.Driver.stuck_text


def test_text_facts_replace_the_blind_lead():
    blind = "I cannot tell from here what is holding it."
    has("N5.4 no facts: today's lead", blind, Stub().stuck_text("S7"))
    text = Stub().stuck_text("S7", facts=[FACT])
    has("N5.4 facts: the line is in the lead", "- " + FACT, text)
    assert blind not in text, "N5.4 the facts replace 'I cannot tell from here'"
    has("N5.4 the number of repeats is said as before", "came back four times in a row", text)
    again = Stub().stuck_text("S7", facts=[FACT], answered={"answer": "retry", "at": "2026-11-05T10:00:00"})
    has("N5.4 an earlier answer is named with its time", "You answered retry at 2026-11-05T10:00:00; the same step still comes back", again)
    assert "You answered" not in Stub().stuck_text("S7", facts=[FACT], answered={"answer": "", "at": "t"}), "N5.4 an empty answer is not named"


def run_loop(driver, seen):
    def seam(state, moves=None):
        seen.append(dict(state, pending=dict(driver.state.get("stuck_pending") or {})))     # the mark as the question is raised
        raise story_run.Stop(story_run.EXIT_DONE, "end of test")
    driver.no_move = seam
    driver.where = lambda: {"action": "prepare_stage", "stage": "S7", "revision": 1}
    driver.boundary_step = lambda action: None
    driver.controller_state = lambda: controller()
    driver.pipeline = lambda: record()
    with contextlib.redirect_stdout(io.StringIO()):
        driver.run()


def test_loop_producer_and_reader():
    root, task_root, env = seed("QA-9")
    driver = driver_for(root, env, "QA-9", max_boundaries=50)
    try:
        seen = []
        run_loop(driver, seen)
        eq("N5.5 the fifth identical `where` reaches the seam once", [s.get("why") for s in seen], ["threshold"])
        person_fact = f"{driver.stage_place('S6')} is pending; the failure analyst accepted the work of the runner"
        has("N5.5 the lead carries the facts in the person's words", "- " + person_fact, seen[0]["lead"])
        assert RUNNER not in seen[0]["lead"], "F3 no dispatch id in the lead"
        eq("F3 the lead passes human_broken", human_broken(seen[0]["lead"]), [])
        has("F3 the ids go to the text (conductor and details file)", FACT, seen[0]["text"])
        eq("N5.5 keep is the place only (no earlier answer)", seen[0]["keep"], [driver.stage_place("S7")])
        signature = seen[0]["text"].split("\n")[0]
        pending = seen[0]["pending"]
        eq("N5.5 the open question is marked pending for its answer", (pending.get("signature"), pending.get("stage"), pending.get("kind")),
           (signature, "S7", "refusal"))
        eq("N5.5 a seam that does not leave a question open (here: a stop) leaves no mark", "stuck_pending" in driver.state, False)
        driver.state["stuck_pending"] = pending          # what a raised `Person` leaves behind
        # the producer: the answer to the stuck question is recorded under the step's signature
        answer = task_root / "answer.md"
        answer.write_text("retry please\n", encoding="utf-8")
        driver.state["asked"] = {"kind": "refusal", "stage": "S7", "dispatch": ""}
        for name in ("_unread_kept_gate", "_file_words", "record_answer_row"):
            setattr(driver, name, lambda *a, **k: None)
        driver.save_state = lambda: None
        with contextlib.redirect_stdout(io.StringIO()):
            driver.take_answer(answer)
        got = (driver.state.get("stuck_asked") or {}).get(signature) or {}
        eq("N5.6 take_answer records the answer under the signature", got.get("answer"), "retry please")
        assert got.get("at"), "N5.6 ... with the time"
        eq("N5.6 the pending mark is spent", "stuck_pending" in driver.state, False)
        # the reader: the same step coming back names the answer, not the same text
        seen2 = []
        run_loop(driver, seen2)
        has("N5.7 the lead names the earlier answer", "You answered retry please at", seen2[0]["lead"])
        has("N5.7 ... and still carries the facts", person_fact, seen2[0]["lead"])
        eq("N5.7 keep carries the answer so the conductor's question keeps it", seen2[0]["keep"], [driver.stage_place("S7"), "retry please"])
        assert seen2[0]["lead"] != seen[0]["lead"], "N5.7 never the same text again (FR-7)"
        # another step (another signature) is not touched by that answer
        eq("N5.7 the record is per signature", list(driver.state["stuck_asked"]), [signature])
    finally:
        cleanup(root)


def test_other_answer_does_not_record_and_drops_pending():
    root, task_root, env = seed("QA-9")
    driver = driver_for(root, env, "QA-9", max_boundaries=50)
    try:
        answer = task_root / "answer.md"
        answer.write_text("stop\n", encoding="utf-8")
        driver.state["stuck_pending"] = {"signature": "sig", "stage": "S7", "kind": "refusal"}
        driver.state["asked"] = {"kind": "gate_A", "stage": "S3", "dispatch": ""}
        for name in ("_unread_kept_gate", "_file_words", "record_answer_row", "record_by_code"):
            setattr(driver, name, lambda *a, **k: None)
        driver.save_state = lambda: None
        with contextlib.redirect_stdout(io.StringIO()):
            driver.take_answer(answer)
        eq("N5.8 an answer to another question records nothing and drops the stale mark",
           (driver.state.get("stuck_asked"), "stuck_pending" in driver.state), (None, False))
    finally:
        cleanup(root)


def test_f6_a_pending_mark_with_no_open_question_is_dropped_at_the_start_of_a_run():
    root, task_root, env = seed("QA-9")
    driver = driver_for(root, env, "QA-9", max_boundaries=50)
    try:
        seen = []
        driver.reconcile_question = lambda: seen.append("stuck_pending" in driver.state) or ""
        driver.owed_rows_step = lambda: (_ for _ in ()).throw(story_run.Stop(story_run.EXIT_DONE, "end of test"))
        mark = {"signature": "sig", "stage": "S7", "kind": "refusal"}
        for asked, want in (({}, False), ({"kind": "refusal", "stage": "S7", "dispatch": ""}, True)):
            driver.state["stuck_pending"], driver.state["asked"] = dict(mark), dict(asked)
            with contextlib.redirect_stdout(io.StringIO()):
                driver.run()
            eq(f"F6 asked={bool(asked)}: the mark is {'kept' if want else 'dropped'} when the run starts", seen[-1], want)
    finally:
        cleanup(root)


def test_f3_the_cap_lead_names_the_earlier_stages_without_ids():
    root, task_root, env = seed("QA-9")
    driver = driver_for(root, env, "QA-9", max_boundaries=50)
    try:
        driver.controller_state = lambda: controller()
        driver.pipeline = lambda: record()
        text = driver.refused_text("S7")
        has("F3 refused_text carries the facts", "What the factory can read about the earlier stages:", text)
        assert RUNNER not in text, "F3 no dispatch id in the refused lead"
        eq("F3 the refused lead passes human_broken", human_broken(text), [])
        assert "What the factory can read" not in driver.refused_text(""), "F3 no stage: no facts (FR-41)"
    finally:
        cleanup(root)


def test_constant():
    eq("N5.9 the named constant", story_run.STUCK_REPEATS, 4)


def main():
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    for _name, fn in tests:
        fn()
    finish("test_stuck_facts")


if __name__ == "__main__":
    main()
