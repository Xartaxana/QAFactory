#!/usr/bin/env python3
"""The stand (t-017 D2), middle third, by the driver in this process with `claude` replaced by the stub: the
lifecycle of the stand question's flag, the relaunch and its kinds, and the positions and answers.

Every scenario builds a Driver in this process, so they run one after another (`run_scenarios([], [...])`). The
helpers, the stub and the runner live in `story_run_common.py`. Continues test_story_run_stand.py; followed by
test_story_run_stand_c.py (t-104).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import check, check_in, check_not_in  # noqa: E402
from story_run_common import (  # noqa: E402
    run_scenarios,
    D2_ASKED_ONCE, D2_DEAD, d2_alive_server, d2_answer, d2_conductor_calls, d2_driver, d2_enter, d2_pipeline,
    d2_seed, d2_stand_at, eq, human_broken, rules_broken, s0_journal, s0_pipeline, s0_question, s0_state,
    seam_control, set_control,
)


def d2_flag_lifecycle() -> None:
    """R1 (critic t-037): the stand question's flag belongs to THAT question. Its answer branch must never
    take the answer to another question of the same stage. In-process."""
    import environment_preparation as EP
    task = "QA-9"
    server, alive = d2_alive_server()
    root, task_root, env = d2_seed(task, environment="Local", pending=True, url=D2_DEAD)
    try:
        set_control(root, {"conductor": {"action": "continue", "did": "read it", "text": "Read."}})
        # step 1: the stand question is asked; the flag names its stage
        driver, started, steps, probes = d2_driver(root, env, task)
        eq("D2(R1) step 1: the stand question is asked", d2_enter(driver, "S5"), 3)
        eq("D2(R1) step 1: the flag names S5", s0_state(task_root).get("stand_question"), "S5")
        # step 2 (the critic's probe): the flag is still set when a DIFFERENT question of the same stage
        # is raised - an environment_job question, kind `environment`, stage S5
        store = EP.EnvironmentJobs(task_root / "state" / "environment-jobs")
        key = "env:QA-9:local"
        store.write({"idempotency_key": key, "job_id": "job-1", "status": "running", "phase": "steps",
                     "coordinator_pid": 4_000_000_000, "coordinator_started_at": "1999-01-01T00:00:00+00:00",
                     "steps": [{"name": "compose-up", "status": "running"}]})
        job = {"action": "observe_environment_job", "stage": "S5", "job_id": "job-1", "status": "running",
               "receipt_ref": "state/environment-jobs/" + store.path(key).name}
        # C1-1: the orphaned job is a by-hand state of the seam; a conductor that gives a usable answer asks it with options
        set_control(root, {"conductor": seam_control("The stand preparation stopped without a result. Say `retry` once it is settled, or `stop`.")})
        driver, started, steps, probes = d2_driver(root, env, task)
        driver.where = lambda: job
        eq("D2(R1) step 2: the environment_job question is asked", driver.run(), 3)
        state = s0_state(task_root)
        eq("D2(R1) step 2: it is kind environment", (state.get("asked") or {}).get("kind"), "environment")
        check("D2(R1) step 2: and the stale flag is GONE (a question that is not stand_check's carries none)",
              "stand_question" not in state, str(state.get("stand_question")))
        # step 3: `retry` answers the JOB question: it is a token of the options that question offered, read by the seam's own
        # branch (back to `where`, no conductor call), and nothing is recorded as a stand answer
        before = len(d2_conductor_calls(root))
        driver, started, steps, probes = d2_driver(root, env, task, answer=d2_answer(root, "retry"))
        driver.where = lambda: {"action": "stop", "reason": "test stop"}
        eq("D2(R1) step 3: the answer is taken: exit 0", driver.run(), 0)
        eq("D2(R1) step 3: the job question's own branch read the token itself: no conductor call", len(d2_conductor_calls(root)) - before, 0)
        check("D2(R1) step 3: and the journal does NOT say `stand at S5`",
              not any("stand at S5" in str(e.get("notes")) for e in s0_journal(root)), str(s0_journal(root))[-300:])

        # M8: a flag that outlives its question is cleared when stand_check runs again and the stand is
        # confirmed - no question is open then, so nothing else would clear it
        driver, started, steps, probes = d2_driver(root, env, task)
        eq("D2(R1) M8: setup - the stand question is asked again", d2_enter(driver, "S5"), 3)
        eq("D2(R1) M8: and the flag is set", s0_state(task_root).get("stand_question"), "S5")
        d2_stand_at(root, alive)                       # the person brought the stand up and simply ran the story again
        driver, started, steps, probes = d2_driver(root, env, task)
        eq("D2(R1) M8: the stage goes on, its stand confirmed by the probe", d2_enter(driver, "S5"), 0)
        check("D2(R1) M8: and the flag is not left behind", "stand_question" not in s0_state(task_root),
              str(s0_state(task_root).get("stand_question")))
    finally:
        harness.cleanup(root)
        server.shutdown()


def d2_relaunch_and_kinds() -> None:
    """R4: a role that is STARTED on S5/S6 - a relaunch, a registered dispatch the driver never launched - passes
    the stand check first; a dispatch resumed with the person's words does not (checked in
    d2_positions_and_answers). R6: the question says what S6 will run. In-process."""
    import story_run
    task = "QA-9"
    root, task_root, env = d2_seed(task, environment="Local", pending=True)
    try:
        for stage, role in (("S5", "qa-automator"), ("S6", "qa-runner")):
            driver, started, steps, probes = d2_driver(root, env, task)
            relaunch = {"action": "relaunch", "stage": stage, "role": role, "dispatch_request": {"scope": ["TC-1"]}}
            try:
                driver.dispatch_action(relaunch)
                check(f"D2(R4) a relaunch on {stage} with an unconfirmed stand asks first", False)
            except story_run.Person as person:
                eq(f"D2(R4) a relaunch on {stage} with an unconfirmed stand asks first (kind environment)", (person.kind, person.stage), ("environment", stage))
            eq(f"D2(R4) and no {stage} role started", started, [])
        for stage, role in (("S5", "qa-automator"), ("S6", "qa-runner")):
            driver, started, steps, probes = d2_driver(root, env, task)
            driver.controller_state = lambda stage=stage, role=role: {"dispatches": {f"{stage}-{role}-3": {"stage": stage, "role": role, "scope": ["TC-1"]}}}
            try:
                driver.dispatch_action({"action": "wait_existing_job", "dispatch_id": f"{stage}-{role}-3"})
                check(f"D2(R4) a never-launched {stage} dispatch asks first", False)
            except story_run.Person as person:
                eq(f"D2(R4) a never-launched {stage} dispatch asks first", (person.kind, person.stage), ("environment", stage))
            eq(f"D2(R4) and no {stage} role started (never-launched)", started, [])
        # confirmed by a person's word: both go through and start the role
        d2_pipeline(task_root, stage_overrides=[{"stage": "S5", "match": D2_ASKED_ONCE, "decision": "go on",
                                                 "at": "2026-09-29T10:00:00+00:00", "by": "human"}])
        driver, started, steps, probes = d2_driver(root, env, task)
        driver.dispatch_action({"action": "relaunch", "stage": "S6", "role": "qa-runner", "dispatch_request": {"scope": ["TC-1"]}})
        eq("D2(R4) with the person's word on record a relaunch starts its role", started, [("S6", "qa-runner")])

        # R6: what the stage is about to run, in the question's words
        driver = d2_driver(root, env, task)[0]
        auto = driver.stand_question_text("S6", "Local", ["Local"], "automation")
        manual = driver.stand_question_text("S6", "Local", ["Local"], "manual")
        both = driver.stand_question_text("S6", "Local", ["Local"], "both")
        check_in("D2(R6) an automated S6 says it runs the automated tests", "running the automated tests, and", auto)
        check_not_in("D2(R6) a manual-only S6 does not say automated tests", "automated tests", manual)
        check_in("D2(R6) and says the manual checks", "carrying out the manual checks", manual)
        check_in("D2(R6) a mixed S6 says both", "running the automated tests and carrying out the manual checks", both)
        for text in (auto, manual, both):
            eq("D2(R6) the text obeys human-questions.md", human_broken(text), [])
    finally:
        harness.cleanup(root)
    # through the stage itself: only manual cases in scope
    root, task_root, env = d2_seed(task, environment="Local", pending=True)
    try:
        driver, started, steps, probes = d2_driver(root, env, task, auto=(), manual=("TC-2",))
        eq("D2(R6) S6 with manual cases only asks: exit 3", d2_enter(driver, "S6"), 3)
        ask = s0_question(task_root)
        check_in("D2(R6) and says the manual checks", "carrying out the manual checks", ask)
        check_not_in("D2(R6) and not the automated tests", "automated tests", ask)
        eq("D2(R6) no role started", started, [])
    finally:
        harness.cleanup(root)


def d2_positions_and_answers() -> None:
    """The positional invariant (a stage that runs nothing never asks; nothing already begun is gated), the
    legacy pair (h), the S6 with nothing to run (f), and the take_answer invariant. In-process."""
    import story_run
    task = "QA-9"
    # (h) legacy pipeline.json: `environment: null, environment_pending: false` - what the old S0 wrote
    root, task_root, env = d2_seed(task, environment=None, pending=False, stands=())
    try:
        driver, started, steps, probes = d2_driver(root, env, task)
        eq("D2(h) a legacy null/false pair asks at S5: exit 3", d2_enter(driver, "S5"), 3)
        ask = s0_question(task_root)
        check_in("D2(h) it says this project records no stand", "this project records no stand, so there is nothing to run them on yet", ask)
        # t-363 B3 (the Lead's second site): the plugin's command is something to type, so it stands in the answer block and
        # the body says "the onboarding step named below"
        # C1-6b: the answer is a priced option now - `retry` is its own token, not a sentence in the option's words
        check_in("D2(h) and the door: the onboarding step named below, then `retry`", "record a stand with the onboarding step named below; I ask again", ask)
        check_in("D2(h) ...and `retry` is the priced answer that carries it", "`retry` — ", ask)
        import human_text
        body, block = human_text.split(ask)
        check_not_in("D2(h) the body carries no plugin command", "/qa-factory:", body)
        check_in("D2(h) the answer block names it", "`/qa-factory:qa-onboarding`", block)
        eq("D2(h) (t-373 F7) ONE answer block: no heading of the text's own, the command is `ask()`'s answer note",
           (ask.count("Answer: write your words"), "## How to answer" in ask), (1, False))
        eq("D2(h) the question obeys human-questions.md", rules_broken(ask), [])
        eq("D2(h) no role started", started, [])
        # the four other shapes of the question, one rules check each (S6 wording included)
        person_texts = {
            "named, other stands": driver.stand_question_text("S5", "Local", ["Local", "Staging"]),
            "named, no other stand": driver.stand_question_text("S6", "Local", ["Local"]),
            "no name, stands": driver.stand_question_text("S6", "", ["Local", "Staging"]),
            "no name, none recorded": driver.stand_question_text("S5", "", []),
            "named, none recorded": driver.stand_question_text("S5", "Local", []),
        }
        for label, text in person_texts.items():
            eq(f"D2 text `{label}` obeys human-questions.md", human_broken(text), [])
        check_in("D2 text: S6 says it is the running that needs the stand", "step is running the automated tests, and", person_texts["no name, stands"])
        check_not_in("D2 text: with one stand only there is no `another stand` door", "another configured stand", person_texts["named, no other stand"])
    finally:
        harness.cleanup(root)

    # the positional invariant: a stage that has nothing to run never asks, whatever the stand says
    root, task_root, env = d2_seed(task, environment=None, pending=True)
    try:
        driver, started, steps, probes = d2_driver(root, env, task, s5=())
        try:
            driver.stage_S5()
            check("D2 position: S5 with no automate case refuses", False)
        except story_run.Refusal as refusal:
            check_in("D2 position: S5 with no automate case refuses before the stand is asked", "no automate cases", refusal.text)
        except story_run.Person:
            check("D2 position: S5 with no automate case refuses before the stand is asked", False)
        driver, started, steps, probes = d2_driver(root, env, task)
        driver.stage_scope = lambda stage, kind="": {"scope": ["TC-1"], "windows": [{"scope": ["TC-1"], "accepted_by": {"qa-code-critic": 1}}]}
        try:
            driver.stage_S5()
            check("D2 position: S5 with every window accepted refuses", False)
        except story_run.Refusal as refusal:
            check_in("D2 position: ... and the second refusal comes before the stand is asked too", "every window is accepted", refusal.text)
        except story_run.Person:
            check("D2 position: ... and the second refusal comes before the stand is asked too", False)
        # (f) S6 with nothing to execute closes with pending still true and asks nothing. The controller
        # refuses a code-only close of S6 in a seeded story whose S1-S5 it never accepted, so the two
        # closing moves are RECORDED here - the assertion is that they are the moves made, in a story
        # whose stand is unconfirmed, and that no question and no probe came before them.
        driver, started, steps, probes = d2_driver(root, env, task, auto=(), manual=())
        moves = []
        driver.code_only = lambda stage, reason, evidence: moves.append(("code_only", stage, reason))
        real_py = driver.py

        def closing_py(script, *args, **kwargs):
            if script == "stage_done.py":
                moves.append(("stage_done", " ".join(str(a) for a in args)))
                return 0, ""
            return real_py(script, *args, **kwargs)
        driver.py = closing_py
        try:
            driver.stage_S6()
            check("D2(f) S6 with nothing to execute closes without a question", True)
        except story_run.Person:
            check("D2(f) S6 with nothing to execute closes without a question", False)
        eq("D2(f) the close is the code-only receipt and the stage_done move", [m[:2] if m[0] == "code_only" else m[0] for m in moves],
           [("code_only", "S6"), "stage_done"])
        check_in("D2(f) with the digest `nothing to execute`", "--stage S6 --status done --digest nothing to execute", moves[1][1])
        eq("D2(f) it started nothing and probed nothing", (started, probes), ([], []))
        eq("D2(f) the stand is still unconfirmed (closing S6 is not confirming a stand)", s0_pipeline(task_root)["environment_pending"], True)
        check("D2(f) no question was raised", "stand_question" not in s0_state(task_root))
    finally:
        harness.cleanup(root)

    # dispatches already begun are not gated: a person's words resume the role with the stand unconfirmed
    root, task_root, env = d2_seed(task, environment="Local", pending=True)
    try:
        driver, started, steps, probes = d2_driver(root, env, task)
        driver.controller_state = lambda: {"dispatches": {"S5-qa-automator-1": {"stage": "S5", "role": "qa-automator"}}}
        resumed = []
        driver.resume_role = lambda stage, role, dispatch, words, **kw: resumed.append((stage, role, dispatch, words))
        driver.state["pending_words"]["S5-qa-automator-1"] = "the person's words"
        driver.dispatch_action({"action": "resume_checkpoint", "dispatch_id": "S5-qa-automator-1"})
        driver.dispatch_action({"action": "wait_existing_job", "dispatch_id": "S5-qa-automator-1"})
        eq("D2 position: resume_checkpoint and wait_existing_job resume the begun dispatch, no stand question",
           (len(resumed), probes), (2, []))
        eq("D2 position: and nothing was asked", s0_state(task_root).get("stand_question"), None)
    finally:
        harness.cleanup(root)

    # the take_answer invariant: only the question stand_check raised takes the stand branch
    root, task_root, env = d2_seed(task, environment="Local", pending=True)
    try:
        set_control(root, {"conductor": {"action": "continue", "did": "read it", "text": "Read."}})
        for label, stand_flag in (("no stand_question (an environment_job question)", None),
                                  ("a stand_question of ANOTHER stage", "S6")):
            before = len(d2_conductor_calls(root))
            driver = d2_driver(root, env, task)[0]
            driver.state["asked"] = {"kind": "environment", "stage": "S5", "dispatch": ""}
            if stand_flag:
                driver.state["stand_question"] = stand_flag
            else:
                driver.state.pop("stand_question", None)
            driver.save_state()
            (task_root / "state" / "driver-question.md").write_text("# q\nkind: environment\n", encoding="utf-8")
            driver.take_answer(Path(d2_answer(root, "retry")))
            eq(f"D2 answer: {label} keeps the final else - `retry` reaches the conductor, as before",
               len(d2_conductor_calls(root)) - before, 1)
            check(f"D2 answer: {label} - the stand was not touched",
                  (s0_pipeline(task_root)["environment"], s0_pipeline(task_root)["environment_pending"]) == ("Local", True))
        # and a question raised by environment_job itself carries no stand_question
        import environment_preparation as EP
        driver = d2_driver(root, env, task)[0]
        driver.state.pop("stand_question", None)
        store = EP.EnvironmentJobs(task_root / "state" / "environment-jobs")
        key = "env:QA-9:local"
        store.write({"idempotency_key": key, "job_id": "job-1", "status": "running", "phase": "steps",
                     "coordinator_pid": 4_000_000_000, "coordinator_started_at": "1999-01-01T00:00:00+00:00",
                     "steps": [{"name": "compose-up", "status": "running"}]})
        set_control(root, {"conductor": seam_control("The stand preparation stopped without a result. Say `retry` once it is settled, or `stop`.")})
        try:
            driver.dispatch_action({"action": "observe_environment_job", "stage": "S5", "job_id": "job-1",
                                    "status": "running", "receipt_ref": "state/environment-jobs/" + store.path(key).name})
            check("D2 answer: an orphaned stand job reaches the person", False)
        except story_run.Person as person:
            eq("D2 answer: environment_job's question is kind environment", person.kind, "environment")
            check("D2 answer: and carries no stand_question", "stand_question" not in driver.state)
    finally:
        harness.cleanup(root)


def main() -> None:
    run_scenarios([], [
        d2_flag_lifecycle,
        d2_relaunch_and_kinds,
        d2_positions_and_answers,
    ])
    harness.finish("test_story_run_stand_b")


if __name__ == "__main__":
    main()
