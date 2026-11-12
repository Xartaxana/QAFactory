"""Story runner tests, delivery, first part: the closed-story stage and the bug trigger, the resume and its readers,
the delivery of an experiment, the delivery mark, the launch record and three attempts.

Split out of the old test_story_run.py (B-155); the stub, the builders and the runner live in
story_run_common.py. Never launches a real `claude -p` (harness points STORY_RUN_CLAUDE at no_claude.py).
Continued in test_story_run_delivery_b.py (cut by measured seconds, each file at most 75 s, t-104).

t-342 adds keys: B-271 (the budget words are said the same way in both of their carriers, the retro is offered no cut in
either of its, and a no-trace run lists its bugs by number with their paths), B-273 (every resume prints its reason, and
a handoff form that is all there is assembled by code instead of resuming the role).
"""
import contextlib
import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import check, check_eq, check_in, check_not_in  # noqa: E402
from story_run_common import (  # noqa: E402
    run_scenarios,
    D3_JIRA, D3_PHRASE, GOOD_MANIFEST, SCOUT_DIGEST, d2_answer, d2_conductor_calls, d2_pipeline, d3_config,
    d3_delivery_ends, d3_loop, d3_s8_done, driver_for, eq, jsonl, rules_broken, run_driver, s0_pipeline, s0_question,
    s0_state, seed, set_control, stub_calls,
)


def delivery_closed_story_and_bug_trigger() -> None:
    task = "QA-9"
    import story_run
    # --- a closed story still has one stage, and a phrase list does not read the person -------
    root, task_root, env = seed(task)
    try:
        driver = driver_for(root, env, task)
        ran = []
        driver.stage_S9 = lambda: ran.append("S9")

        driver.dispatch_action({"action": "closed", "closed_at": "legacy", "revision": 9,
                                "reason": "gate B is decided and S8 is done", "stage": "S9",
                                "retro_pending": True})
        check_eq("a closed story with the retro pending runs the retro stage", ran, ["S9"])

        try:
            driver.dispatch_action({"action": "closed", "closed_at": "legacy", "revision": 9,
                                    "reason": "gate B is decided and S8 is done"})
            check("a closed story with nothing left stops", False)
        except story_run.Stop as stop:
            check_eq("a closed story with nothing left exits 0, not as a question", stop.code, 0)
            check_in("and says the story is finished and nothing is pending (A8: no promised reopen)",
                     "the story is finished; nothing is pending.", stop.reason)
            check_not_in("and promises no road back that this exit does not hold", "--operation rework", stop.reason)
        except story_run.Person:
            check("a closed story with nothing left is not a question for the person", False)

        # The bug trigger. The gate B packet asks "answer by number for the bugs to file", so the
        # order arrives as the person's own prose — in TP1-13797 run 5, in their own language,
        # which a two-phrase English regex could not read at all (and whose second phrase asked
        # for a literal 0x08 byte, so it never matched anything). The words seeded below order a
        # bug in plain English and still match neither phrase: that is the point.
        source = (harness.SCRIPTS / "story_run.py").read_text(encoding="utf-8")
        check("no phrase list decides whether the person ordered a bug", "asked_for_bug" not in source)
        check("and no control byte hides in the driver's source", chr(8) not in source)

        state = json.loads((task_root / "state/controller.json").read_text(encoding="utf-8"))
        # GB-1b: the reporter runs on a `bugs` order that is due - the driver records its gate B decision with `--bugs ordered`, so a
        # person's words with no draft chosen still order the reporter (13797); a decision with no order for it (0.10.4) does not
        state["decisions"] = {"gateB-1": {"gate": "B", "status": "approved", "selected_drafts": [],
                                          "orders": {"bugs": "due", "mr": "not_ordered"},
                                          "authorization_source": "File BUG-1 as a local proposal under "
                                                                  "qa-factory/bugs: AC7 is unmet as shipped."}}
        (task_root / "state/controller.json").write_text(json.dumps(state), encoding="utf-8")
        dispatched = []
        driver.run_role = lambda stage, role, **kw: dispatched.append((stage, role, kw))
        driver.state["delivery"] = {"at": "already done"}
        driver.after_gate_B()
        check_eq("gate-B words in any language reach the bug reporter",
                 [(s, r) for s, r, _ in dispatched], [("S8", "qa-bug-reporter")])
        extra = "\n".join(dispatched[0][2].get("extra") or [])
        check_in("with the decision verbatim", "BUG-1", extra)
        check_in("and 'nothing to file' named as a complete answer", "not a gap", extra)
        # B6 (the road a 0.10.4 decision loses, said in the changelog): words and no drafts and no `orders` order nothing
        state["decisions"]["gateB-1"].pop("orders")
        (task_root / "state/controller.json").write_text(json.dumps(state), encoding="utf-8")
        dispatched.clear()
        driver.gate_b_ran.clear()
        driver.after_gate_B()
        check_eq("a decision with no orders and no chosen drafts dispatches no reporter", dispatched, [])
    finally:
        harness.cleanup(root)


def d3_resume_and_readers() -> None:
    """(h)(i) and the readers of the flag: accepted on a resume, never reopened by its absence,
    settable by stage_done in both directions and refused by name for anything else."""
    import contextlib
    import io
    import external_writes
    task = "QA-9"
    root, task_root, env = seed(task)
    try:
        journal = root / "qa-factory" / "state" / "journal.jsonl"
        journal.parent.mkdir(parents=True, exist_ok=True)
        journal.write_text(json.dumps({"ts": "2026-09-29T10:00:00+00:00", "event": "external_write", "task": task,
                                       "ref": "bug-1", "notes": "filed"}) + "\n", encoding="utf-8")
        driver = driver_for(root, env, task, no_trace=True)
        driver.where = lambda: {"action": "stop", "reason": "end of test"}
        printed = io.StringIO()
        with contextlib.redirect_stdout(printed):
            code = driver.run()
        eq("D3(h) `--no-trace` on a resume: the loop runs on", code, 0, printed.getvalue()[-800:])
        pipeline = s0_pipeline(task_root)
        eq("D3(h) accepted: pipeline.no_trace is true", pipeline.get("no_trace"), True)
        check_in("D3(h) with the warning line, naming the stage it counts from",
                 "experiment from S1 on; earlier outward writes, if any, are not undone", pipeline["warnings"])
        check_in("D3(h) and said aloud", "--no-trace accepted from S1 on", printed.getvalue())
        check_in("D3(h) an external_write event already in the journal is printed too (FR-41)",
                 "already holds 1 external_write event(s)", printed.getvalue())
        eq("D3 the one reader agrees", bool(external_writes.closed_by_run(task_root)), True)
        driver = driver_for(root, env, task)          # no `no_trace` attribute at all, as driver_for builds it
        driver.where = lambda: {"action": "stop", "reason": "end of test"}
        driver.run()
        eq("D3(h) the flag's absence on a later command line does not reopen writes", s0_pipeline(task_root).get("no_trace"), True)
        eq("D3(h) and the driver still reads it closed", driver.no_trace(), True)
        driver = driver_for(root, env, task, no_trace=True)
        driver.where = lambda: {"action": "stop", "reason": "end of test"}
        printed = io.StringIO()
        with contextlib.redirect_stdout(printed):
            driver.run()
        eq("D3(h) the flag again: accepted once, its warning is not repeated",
           len([w for w in s0_pipeline(task_root)["warnings"] if w.startswith("experiment from")]), 1)
        check_not_in("D3(h) and nothing is announced twice", "accepted from", printed.getvalue())

        # (i) stage_done: the two words, and a refusal by name for the rest
        def stage_done(value: str):
            return harness.run_script("stage_done.py", "--task", task, "--set", f"no_trace={value}", cwd=root, env=env)
        out = stage_done("maybe")
        eq("D3(i) `no_trace=maybe` is refused: exit 2", out.returncode, 2, out.stdout + out.stderr)
        check_in("D3(i) by name, with the two words it takes", "`no_trace` is true or false", out.stderr)
        eq("D3(i) and nothing was written", s0_pipeline(task_root).get("no_trace"), True)
        out = stage_done("false")
        eq("D3(i) `no_trace=false` is accepted: exit 0", out.returncode, 0, out.stdout + out.stderr)
        eq("D3(i) it is the way out, written as a bool", s0_pipeline(task_root).get("no_trace"), False)
        eq("D3(i) and the one reader reads it open", external_writes.closed_by_run(task_root), "")
        eq("D3(i) and so does the driver", driver_for(root, env, task).no_trace(), False)
        out = stage_done("true")
        eq("D3(i) `no_trace=true` is accepted: exit 0", out.returncode, 0, out.stdout + out.stderr)
        eq("D3(i) and closes again", s0_pipeline(task_root).get("no_trace"), True)
    finally:
        harness.cleanup(root)
    # a story with no external_write event: nothing is said about one
    root, task_root, env = seed(task)
    try:
        driver = driver_for(root, env, task, no_trace=True)
        driver.where = lambda: {"action": "stop", "reason": "end of test"}
        printed = io.StringIO()
        with contextlib.redirect_stdout(printed):
            driver.run()
        check_in("D3(h) control: the flag is still accepted", "--no-trace accepted from S1 on", printed.getvalue())
        check_not_in("D3(h) control: and no journal line is announced", "external_write", printed.getvalue())
    finally:
        harness.cleanup(root)
    # before pipeline.json exists (S0 writes it) the only record is the command line
    root, task_root, env = seed(task)
    try:
        (task_root / "pipeline.json").unlink()
        eq("D3 no pipeline.json, no attribute: the driver reads it open", driver_for(root, env, task).no_trace(), False)
        eq("D3 no pipeline.json, the flag on the command line: closed", driver_for(root, env, task, no_trace=True).no_trace(), True)
    finally:
        harness.cleanup(root)


def d3_experiment_delivery() -> None:
    """(d) an experiment's delivery is the null outcome - zero conductor calls, the mark recorded -
    and its reporter and scribe are told the channel is closed; and A2, the environment line."""
    task = "QA-9"
    root, task_root, env = seed(task)
    try:
        d3_config(root, D3_JIRA)
        driver = driver_for(root, env, task)
        eq("D3 control: an ordinary run's scribe reads the configured channels",
           driver.role_lines("S8", "qa-doc-scribe")[1], "Bugs channel: jira · Cases channel: markdown")
        harness.run_script("stage_done.py", "--task", task, "--set", "no_trace=true", cwd=root, env=env)
        set_control(root, {"conductor": {"action": "continue", "did": "it should never be called"}})
        eq("D3 the scribe is told both channels are closed for this run",
           driver.role_lines("S8", "qa-doc-scribe")[1],
           "Bugs channel: markdown (closed for this run: experiment) · Cases channel: markdown (closed for this run: experiment)")
        state = json.loads((task_root / "state/controller.json").read_text(encoding="utf-8"))
        # a decision recorded before 0.10.5 (no `orders`) with a chosen draft: `bugs` is derived (F-5), `mr` is not - its delivery runs as it did
        state["decisions"] = {"gateB-1": {"gate": "B", "status": "approved", "selected_drafts": ["BD-1"],
                                          "authorization_source": "File BUG-1 as a local proposal: AC7 is unmet."}}
        (task_root / "state/controller.json").write_text(json.dumps(state), encoding="utf-8")
        journal = root / "qa-factory" / "records" / "journal.jsonl"
        before = journal.read_bytes() if journal.exists() else b""
        dispatched: list = []
        driver.run_role = lambda stage, role, **kw: dispatched.append((stage, role, kw))
        driver.after_gate_B()
        extra = "\n".join(dispatched[0][2].get("extra") or [])
        eq("D3 the reporter still runs", [(s, r) for s, r, _ in dispatched], [("S8", "qa-bug-reporter")])
        check_in("D3 and is told the tracker is not a channel", "This run is an experiment: treat the bugs channel as markdown and write no proposal for a tracker.", extra)
        eq("D3(d) delivery under no_trace: zero conductor calls", stub_calls(root), [])
        mark = driver.state["delivery"]
        eq("D3(d) the mark is the null outcome, recorded", (mark.get("done"), mark.get("action")), (True, "nothing_outward"))
        eq("D3(d) and says what did not go out", mark.get("did"),
           "nothing outward (experiment): no branch, commit, push, merge request or tracker write")
        check("D3(d) the mark is on disk", s0_state(task_root).get("delivery", {}).get("action") == "nothing_outward")
        eq("D3(d) the driver's journal names the outcome",
           [(r.get("kind"), r.get("outcome")) for r in jsonl(task_root / "state/driver-runs.jsonl")][-1],
           ("delivery", "nothing_outward"))
        eq("D3(d) external_writes did not run: the project journal is as it was",
           journal.read_bytes() if journal.exists() else b"", before)
        driver.after_gate_B()
        eq("D3(d) once done, it is not entered again", stub_calls(root), [])
        # a delivery called on its own goes the same way, and the control text of the rule is closed
        driver2 = driver_for(root, env, task)
        driver2.delivery({})
        eq("D3(d) `delivery()` itself: zero conductor calls", stub_calls(root), [])
        check_in("D3 the outward rule of a closed run says so", "closed for outward writes", driver2.outward_rule())
        check_not_in("D3 and names no tracker to write", "config.external_writes names", driver2.outward_rule())
    finally:
        harness.cleanup(root)
    # A2: an environment no check has answered for is not printed as a plain name (FR-41)
    root, task_root, env = seed(task)
    try:
        driver = driver_for(root, env, task)
        d2_pipeline(task_root, environment="Local", environment_pending=True)
        eq("A2 unconfirmed: the runner is told it is not confirmed yet",
           driver.role_lines("S5", "qa-runner"), ["Environment: Local (not confirmed yet)"])
        eq("A2 unconfirmed: so is the failure analyst", driver.role_lines("S7", "qa-failure-analyst")[-1],
           "Environment: Local (not confirmed yet)")
        check_in("A2 unconfirmed: and the scout", "Environment: Local (not confirmed yet)", driver.role_lines("S1", "qa-scout"))
        d2_pipeline(task_root, environment="Local", environment_pending=False)
        eq("A2 confirmed: unchanged", driver.role_lines("S5", "qa-runner"), ["Environment: Local"])
        d2_pipeline(task_root, environment=None, environment_pending=True)
        eq("A2 no name, pending: unchanged", driver.role_lines("S5", "qa-runner"), ["Environment: pending"])
        d2_pipeline(task_root, environment=None, environment_pending=False)
        eq("A2 no name, not pending: unchanged", driver.role_lines("S5", "qa-runner"), ["Environment: none"])
    finally:
        harness.cleanup(root)


def d3_delivery_mark() -> None:
    """(e)(f)(g) and the rest of delta 8b: the mark exists only after `continue`; a question
    re-enters the delivery with the person's words and with what already went out; one conductor
    call per process; an old mark still means done."""
    import story_run
    task = "QA-9"
    first_did = "pushed branch qa/x; MR !12 created"
    for label, action, code, question in (("ask_person", "ask_person", 3, "Which reviewer should the merge request go to?"),
                                          ("stop", "stop", 4, "The push was refused: the branch is protected.")):
        root, task_root, env = seed(task)
        try:
            d3_config(root, D3_JIRA)
            set_control(root, {"conductor": {"action": action, "did": first_did, "question": question}})
            driver = driver_for(root, env, task)
            d3_loop(driver)
            eq(f"D3 {label}: the loop ends with the person's question: exit {code}", driver.run(), code)
            state = s0_state(task_root)
            check(f"D3 {label}: NO delivery mark is left", "delivery" not in state, str(state.get("delivery")))
            eq(f"D3 {label}: the attempt is remembered with what went out and what was asked",
               [(a["action"], a["did"], a["question"]) for a in state["delivery_attempts"]], [(action, first_did, question)])
            check_in(f"D3 {label}: the question is the conductor's", question, s0_question(task_root))
            first = d2_conductor_calls(root)[0]["prompt"]
            check_not_in(f"D3 {label}: the first call carries no earlier attempts", "Earlier attempts", first)
            check_not_in(f"D3 {label}: the fixed sentence naming one tracker is gone", "Jira is never written", first)
            check_in(f"D3 {label}: the channels are the project's own", "config.external_writes names (bugs=jira)", first)
            # the person's answer: the branch a stop passed before the answer takes it as a human_answer
            d3_s8_done(task_root)
            set_control(root, {"conductor": {"action": "continue", "did": "reviewer set on MR !12; nothing new created"}})
            driver = driver_for(root, env, task, answer=d2_answer(root, "Use Sam Rivera; the branch is fine"))
            d3_loop(driver)
            eq(f"D3 {label}: the answer re-enters the delivery, which ends: exit 0", driver.run(), 0)
            calls = d2_conductor_calls(root)
            eq(f"D3 {label}: two delivery calls in all, and none to record the answer", len(calls), 2)
            second = calls[1]["prompt"] if len(calls) > 1 else ""
            check_in(f"D3 {label}: the second prompt carries the first `did` verbatim", first_did, second)
            check_in(f"D3 {label}: and the first question", question, second)
            check_in(f"D3 {label}: and the person's words", "Use Sam Rivera; the branch is fine", second)
            check_in(f"D3 {label}: and the reuse instruction", D3_PHRASE, second)
            check_in(f"D3 {label}: saying they already went out", "already went out", second)
            state = s0_state(task_root)
            eq(f"D3 {label}: on `continue` the mark is done", (state["delivery"].get("done"), state["delivery"].get("action")), (True, "continue"))
            eq(f"D3 {label}: with the last `did`", state["delivery"].get("did"), "reviewer set on MR !12; nothing new created")
            eq(f"D3 {label}: both attempts are kept", [a["action"] for a in state["delivery_attempts"]], [action, "continue"])
            driver = driver_for(root, env, task)
            d3_loop(driver)
            eq(f"D3 {label}: a finished delivery is not entered again: exit 0", driver.run(), 0)
            eq(f"D3 {label}: no third call", len(d2_conductor_calls(root)), 2)
        finally:
            harness.cleanup(root)
    # (g) one conductor call per process; an old mark; a verdict of no known action
    root, task_root, env = seed(task)
    try:
        set_control(root, {"conductor": {"action": "continue", "did": "delivered"}})
        driver = driver_for(root, env, task)
        driver.delivery({})
        eq("D3(g) the first delivery call reaches the conductor", len(d2_conductor_calls(root)), 1)
        try:
            driver.delivery({})
            check("D3(g) a second call in the same process refuses", False)
        except story_run.Refusal as refusal:
            check_in("D3(g) a second call in the same process refuses, saying what it prevents",
                     "could create them twice", refusal.text)
            check_in("D3(g) and the door (C1-6c): answer `retry`, and no `run the driver again`", "answer `retry`: the delivery is asked again", refusal.text)
            check("D3(g) ... the old door is gone", "run the driver again" not in refusal.text, refusal.text)
        eq("D3(g) and the conductor was not called again", len(d2_conductor_calls(root)), 1)
        legacy = driver_for(root, env, task)
        legacy.state["delivery"] = {"at": "2026-09-01T00:00:00+00:00", "did": "old", "action": "ask_person"}
        legacy.after_gate_B()
        eq("D3 a legacy mark (truthy, no `done`) still means delivered: not re-run", len(d2_conductor_calls(root)), 1)
    finally:
        harness.cleanup(root)
    root, task_root, env = seed(task)
    try:
        # A verdict that is none of the three is `ask_person` (Lead's decision): a person's question
        # in words with the two choices, no mark, the attempt kept, one conductor call, no Refusal loop.
        for label, did, shown in (("with text", "half done: branch pushed", "The delivery step reported: half done: branch pushed"),
                                  ("with none", "", "The delivery step came back with an answer I do not recognise.")):
            set_control(root, {"conductor": {"action": "retry", "did": did}})
            before = len(d2_conductor_calls(root))
            driver = driver_for(root, env, task)
            d3_loop(driver)
            eq(f"D3 unknown verdict {label}: the person is asked: exit 3", driver.run(), 3)
            ask = s0_question(task_root)
            check_in(f"D3 unknown verdict {label}: the question says what the step reported", shown, ask)
            check_in(f"D3 unknown verdict {label}: and the two choices", "say to go on with the delivery", ask)
            check_in(f"D3 unknown verdict {label}: and to stop here", "or to stop here", ask)
            eq(f"D3 unknown verdict {label}: the question obeys human-questions.md", rules_broken(ask), [])
            eq(f"D3 unknown verdict {label}: the conductor was called once", len(d2_conductor_calls(root)) - before, 1)
            check(f"D3 unknown verdict {label}: no mark is written", "delivery" not in s0_state(task_root))
            eq(f"D3 unknown verdict {label}: the attempt is remembered",
               [(a["action"], a["did"]) for a in s0_state(task_root)["delivery_attempts"]][-1], ("retry", did))
            (task_root / "state" / "driver-question.md").unlink()
            st = s0_state(task_root)
            st["asked"] = {}
            (task_root / "state" / "driver-state.json").write_text(json.dumps(st), encoding="utf-8")
        # the outward rule of an open run follows the project's channels
        d3_config(root, D3_JIRA)
        check_in("D3 the outward rule of an open run names the configured channels", "(bugs=jira)", driver_for(root, env, task).outward_rule())
    finally:
        harness.cleanup(root)
    root, task_root, env = seed(task)
    try:
        check_in("D3 a project with markdown channels says so", "none: bugs and cases are markdown", driver_for(root, env, task).outward_rule())
    finally:
        harness.cleanup(root)


def d3_launch_record() -> None:
    """Q6/Q7: the launch's record (`state["launch"]["no_trace"]`, kept by S0) closes when pipeline.json
    cannot say, is honoured on a resume, and never overrides the person's explicit way out; a delivery
    already recorded as nothing outward is said to stay so once the run is no longer an experiment."""
    import contextlib
    import io
    task = "QA-9"

    def with_launch(root, task_root, on: bool = True, **extra):
        state = s0_state(task_root)
        state["launch"] = {"no_trace": True} if on else {}
        state.update(extra)
        (task_root / "state" / "driver-state.json").write_text(json.dumps(state), encoding="utf-8")

    def quiet_run(driver) -> str:
        driver.where = lambda: {"action": "stop", "reason": "end of test"}
        printed = io.StringIO()
        with contextlib.redirect_stdout(printed):
            driver.run()
        return printed.getvalue()
    root, task_root, env = seed(task)
    try:
        with_launch(root, task_root)
        (task_root / "pipeline.json").write_text("{not json", encoding="utf-8")
        eq("D3 Q6: an unreadable pipeline.json cannot reopen writes (the launch says experiment)", driver_for(root, env, task).no_trace(), True)
        (task_root / "pipeline.json").write_text(json.dumps({"ticket": task}), encoding="utf-8")
        eq("D3 Q6: a pipeline with no `no_trace` key is closed by the launch too", driver_for(root, env, task).no_trace(), True)
        (task_root / "pipeline.json").write_text(json.dumps({"ticket": task, "no_trace": False}), encoding="utf-8")
        eq("D3 Q6: an explicit false is the person's way out and wins", driver_for(root, env, task).no_trace(), False)
        with_launch(root, task_root, on=False)
        (task_root / "pipeline.json").write_text("{not json", encoding="utf-8")
        eq("D3 Q6 control: no launch record, unreadable pipeline: open", driver_for(root, env, task).no_trace(), False)
    finally:
        harness.cleanup(root)
    root, task_root, env = seed(task)
    try:
        with_launch(root, task_root)
        printed = quiet_run(driver_for(root, env, task))          # no flag on this command line
        eq("D3 Q7: a resume with no flag honours the launch's record", s0_pipeline(task_root).get("no_trace"), True)
        check_in("D3 Q7: and says so", "--no-trace accepted from S1 on", printed)
        out = harness.run_script("stage_done.py", "--task", task, "--set", "no_trace=false", cwd=root, env=env)
        eq("D3 Q7: the way out", out.returncode, 0, out.stdout + out.stderr)
        quiet_run(driver_for(root, env, task))
        eq("D3 Q7: the launch's record does not re-close an explicit false", s0_pipeline(task_root).get("no_trace"), False)
        # the delivery recorded as nothing outward stays so
        with_launch(root, task_root, delivery={"done": True, "at": "x", "action": "nothing_outward", "did": "nothing outward (experiment)"})
        printed = quiet_run(driver_for(root, env, task))
        check_in("D3 Q7: once the run is open again, the recorded delivery is said to stay nothing outward",
                 "already recorded as nothing outward", printed)
        eq("D3 Q7: said once", printed.count("already recorded as nothing outward"), 1)
        harness.run_script("stage_done.py", "--task", task, "--set", "no_trace=true", cwd=root, env=env)
        check_not_in("D3 Q7 control: while the run is an experiment nothing is said", "already recorded as nothing outward",
                     quiet_run(driver_for(root, env, task)))
    finally:
        harness.cleanup(root)


def d3_three_attempts() -> None:
    """F3: two attempts that did not end (`ask_person`, then a verdict of no known action), then `continue`:
    the third prompt carries BOTH earlier attempts, did and question, verbatim - not only the last."""
    task = "QA-9"
    root, task_root, env = seed(task)
    try:
        did1, q1 = "pushed branch qa/x; MR !12 created", "Which reviewer should the merge request go to?"
        did2, q2 = "set the reviewer; the title is not checked yet", "Is the merge request title right?"
        first, _, _ = d3_delivery_ends(root, env, task, {"action": "ask_person", "did": did1, "question": q1})
        eq("D3 three attempts: the first ends with a question: exit 3", first, 3)
        set_control(root, {"conductor": {"action": "retry", "did": did2, "question": q2}})
        d3_s8_done(task_root)
        driver = driver_for(root, env, task, answer=d2_answer(root, "Sam Rivera"))
        d3_loop(driver)
        eq("D3 three attempts: the second (no known action) asks the person: exit 3", driver.run(), 3)
        set_control(root, {"conductor": {"action": "continue", "did": "title confirmed; nothing new created"}})
        driver = driver_for(root, env, task, answer=d2_answer(root, "The title is right, go on"))
        d3_loop(driver)
        eq("D3 three attempts: the third ends the delivery: exit 0", driver.run(), 0)
        calls = d2_conductor_calls(root)
        eq("D3 three attempts: three delivery calls in all", len(calls), 3)
        third = calls[2]["prompt"] if len(calls) > 2 else ""
        for label, needle in (("first did", did1), ("first question", q1), ("second did", did2), ("second question", q2)):
            check_in(f"D3 three attempts: the third prompt carries the {label} verbatim", needle, third)
        check_in("D3 three attempts: numbered oldest first", "1. action: ask_person", third)
        check_in("D3 three attempts: and the second", "2. action: retry", third)
        check_in("D3 three attempts: with the reuse instruction", D3_PHRASE, third)
        eq("D3 three attempts: all three are kept",
           [a["action"] for a in s0_state(task_root)["delivery_attempts"]], ["ask_person", "retry", "continue"])
    finally:
        harness.cleanup(root)


S9_TASK = "QA-9"
S9_DISPATCH = "S9-qa-retro-analyst-1"
# What `stage_done.s9_exit` prints when the report does not hold what the factory recorded (R-S9.1).
S9_REFUSAL = ("stage_done: S9 closes the story, and test-report.md does not hold what the factory recorded (1 problem(s)):\n"
              "  - report check: test-report.md: block `gate-b` is missing - expected `<!-- facts:gate-b -->` ... "
              "`<!-- /facts:gate-b -->`; run `report_facts.py --task QA-9 --write` to render it\n"
              "Expected: a report whose code-owned blocks match the facts. Doors: `report_facts.py --task QA-9 --write`.")
S9_STORY_STEP_REFUSAL = S9_REFUSAL + "\nstory_step: stage_done refused S9 (exit 2); the refusal above is the halt"


class S9Stub:
    """An in-process driver at S9: every script is recorded (`log`, in order) and answers from `replies`
    (key -> [(exit, output), ...], the last one repeats); `claude -p`, the handoff and the S9 start are stubs.
    `py` keeps `check=True`'s meaning - a refusal that carries the call to repeat - so the refusal road of
    the real driver runs over it."""

    def __init__(self, root, env, task_root, mode: str, *, no_trace: bool = False, replies=None, answered: bool = True):
        self.log, self.replies, self.conductor_calls = [], dict(replies or {}), []
        d2_pipeline(task_root, retro_mode=mode)
        d = self.driver = driver_for(root, env, S9_TASK, no_trace=no_trace)
        if answered:
            d.state["retro_asked"] = True
        d.state["delivery"] = {"done": True, "at": "x", "action": "nothing_outward", "did": "nothing outward"}
        d.controller_state = lambda: {"decisions": {}, "dispatches": {}}
        d.step = lambda *a, **k: (f"dispatched {S9_DISPATCH} (revision 4)\n--- Agent prompt, verbatim ---\n"
                                  "You are the retro analyst.\n--- the moment the Agent call returns ---\n")
        d.system_file = lambda *a, **k: ""
        d.handoff = lambda role, stage, dispatch, result: "qa-retro-analyst S9 QA-9 · ok\nretro.md"
        d.question_threshold = lambda *a, **k: None

        def run_claude(kind, prompt, **kw):
            self.log.append(("run_claude", (kind,)))
            return {"result": "done", "session_id": "sess-1", "stderr": "", "total_cost_usd": 0.0, "is_error": False}
        d.run_claude = run_claude

        def py(script, *args, check=False, expect=""):      # C1-7b: G5 passes `expect`
            args = tuple(str(a) for a in args)
            self.log.append((script, args))
            key = {"report_facts.py": "report"}.get(script, script)
            if script == "story_step.py" and args and args[0] == "finish":
                key = "finish"
            if script == "stage_done.py" and "--stage" in args and args[args.index("--stage") + 1] == "S9":
                key = "stage_done:S9"
            # t-305 N8 attempt 2 (F4): the recompute decides on the word `check_delivery --json` PRINTS, so the stub prints one
            queue = self.replies.get(key) or [(0, '{"delivery_verdict": "yes", "delivery_ready": true}'
                                                if script == "check_delivery.py" else "")]
            code, out = queue.pop(0) if len(queue) > 1 else queue[0]
            if check and code:
                import story_run
                raise story_run.Refusal(f"{script} {' '.join(args[:6])} (exit {code}):\n{out}",
                                        retry=lambda: py(script, *args, check=True))
            return code, out
        d.py = py
        d.conductor = lambda *a, **k: self.conductor_calls.append(a) or {"action": "continue", "did": "stub"}

    def names(self) -> list:
        """The log as one label per call: `report_facts --write`, `stage_done S9 skipped`, `finish`, `run_claude`..."""
        out = []
        for script, args in self.log:
            if script == "report_facts.py":
                out.append("write" if "--write" in args else "report_facts")
            elif script == "stage_done.py":
                out.append("stage_done " + (args[args.index("--stage") + 1] + " " + args[args.index("--status") + 1]
                                             if "--stage" in args and "--status" in args else "other"))
            elif script == "story_step.py":
                out.append(args[0] if args else "story_step")
            elif script == "retro_numbers.py":
                out.append("retro_numbers --write-retro" if "--write-retro" in args else "retro_numbers")
            else:
                out.append(script.replace(".py", ""))
        return out

    def writes(self) -> int:
        return self.names().count("write")

    def run(self) -> str:
        """S9 as the loop enters it (`boundary_step`: the boundary is set, the refusal guard is around it)."""
        import contextlib
        import io
        printed = io.StringIO()
        with contextlib.redirect_stdout(printed):
            self.driver.boundary_step({"action": "prepare_stage", "stage": "S9"})
        return printed.getvalue()


def s9_report_rebuilt_last() -> None:
    """R-212.1 (P9b): code rebuilds the report right after gate B, and again as the story's last step - after
    the retro role returns (full: inside the finish that closes S9), or right before `stage_done S9` (numbers, skip)."""
    root, task_root, env = seed(S9_TASK)
    try:
        # full: write (a) -> retro role -> write (b) -> the finish that records S9
        s = S9Stub(root, env, task_root, "full")
        s.run()
        names = s.names()
        writes = [i for i, n in enumerate(names) if n == "write"]
        eq("full: two writes, the second inside the closing finish", len(writes), 2, str(names))
        check("full: the first write comes before the retro role, the last one after it and before the finish",
              len(writes) == 2 and writes[0] < names.index("run_claude") < writes[-1] < names.index("finish"), str(names))
        eq("full: the write is `report_facts.py --task <T> --write`",
           [args for script, args in s.log if script == "report_facts.py"][0], ("--task", S9_TASK, "--write"))
        # numbers: write (a) -> the numbers -> write (b) -> stage_done S9 done
        s = S9Stub(root, env, task_root, "numbers")
        s.run()
        names = s.names()
        writes = [i for i, n in enumerate(names) if n == "write"]
        eq("numbers: two writes", len(writes), 2, str(names))
        check("numbers: the last write comes after the retro numbers and the estimate, right before stage_done S9",
              len(writes) == 2 and writes[0] < names.index("retro_numbers") and
              max(names.index("retro_numbers --write-retro"), names.index("estimate_record")) < writes[-1]
              < names.index("stage_done S9 done"), str(names))
        check("numbers: the first write is before any retro step",
              writes[0] < names.index("retro_numbers"), str(names))
        # skip: write (a) -> the escalation line -> write (b) -> stage_done S9 skipped
        s = S9Stub(root, env, task_root, "skip")
        s.run()
        names = s.names()
        writes = [i for i, n in enumerate(names) if n == "write"]
        eq("skip: two writes", len(writes), 2, str(names))
        check("skip: the last write comes after the escalation and right before stage_done S9",
              len(writes) == 2 and names.index("log_append") < writes[-1] < names.index("stage_done S9 skipped"), str(names))
        # an experiment rebuilds too: the rebuild is local, `--no-trace` changes nothing here
        s = S9Stub(root, env, task_root, "skip", no_trace=True)
        s.run()
        eq("--no-trace: the same two writes", s.names().count("write"), 2, str(s.names()))
        # the retro is not asked yet: the first write has run, nothing after the question
        s = S9Stub(root, env, task_root, "full", answered=False)
        import story_run
        try:
            s.run()
            check("full, retro not asked: the person is asked", False)
        except story_run.Person:
            # t-305 N8 (K-N8.7): the verdict is computed again FIRST (the three scripts, S8's order), then write (a); nothing
            # after the question
            eq("full, retro not asked: only the verdict recompute and write (a) ran before the question", s.names(),
               ["check_traceability", "ledger", "check_delivery", "write"])
    finally:
        harness.cleanup(root)


def s8_report_rebuilt_before_gate_b() -> None:
    """t-204 F6 (R-212.1): the report's code-owned blocks are rendered once the S8 scribe has returned and BEFORE
    gate B is asked, so the gate B packet reads a code-checked report. POSITION: after the scribe's finish, before
    the gate B question; a refused or crashed write is one printed line and never stops the story; `--no-trace`
    changes nothing; no write is made before the scribe has finished."""
    import contextlib
    import io
    import story_run
    root, task_root, env = seed(S9_TASK)
    damaged = ("test-report.md: a start marker `<!-- facts:verdict -->` has no end at line 4; report_facts.py does "
               "not guess where the scribe's prose ends - repair the markers")
    trace = "Traceback (most recent call last):\n  File \"report_facts.py\", line 1, in <module>\nValueError: boom in the render"

    def through_gate_b(s) -> str:
        """S8 as the loop enters it, then the await_gate boundary; the gate B question is a log entry."""
        s.driver.gate_text = lambda gate: s.log.append(("gate_text", (gate,))) or "the packet"
        printed = io.StringIO()
        with contextlib.redirect_stdout(printed):
            s.driver.boundary_step({"action": "prepare_stage", "stage": "S8"})
            try:
                s.driver.dispatch_action({"action": "await_gate", "gate": "B"})
                check("the gate B boundary asks the person", False)
            except story_run.Person as asked:
                check_eq("the gate B boundary asks the person", asked.kind, "gate_B")
        return printed.getvalue()
    try:
        s = S9Stub(root, env, task_root, "full")
        through_gate_b(s)
        names = s.names()
        check("the write comes after the scribe's finish and before the gate B question",
              names.count("write") == 1 and names.index("finish") < names.index("write") < names.index("gate_text"), str(names))
        check("and the three checks of S8 and the scribe's run come before the finish",
              names.index("run_claude") < names.index("finish") and names.index("check_delivery") < names.index("run_claude"),
              str(names))
        eq("the write is `report_facts.py --task <T> --write`",
           [args for script, args in s.log if script == "report_facts.py"], [("--task", S9_TASK, "--write")])
        # a refused write: one printed line, the story goes on to the gate B question
        s = S9Stub(root, env, task_root, "full", replies={"report": [(1, damaged)]})
        printed = through_gate_b(s)
        check_in("a refused write: one printed line with the refusal's own words",
                 "report rebuild refused, the report is as it was: test-report.md: a start marker", printed)
        check("a refused write: the gate B question was still asked, after the write",
              s.names().index("write") < s.names().index("gate_text"), str(s.names()))
        eq("a refused write: nobody was asked and no conductor was called", s.conductor_calls, [])
        # a write that crashes (a traceback, or `py` itself raising): printed, and the story goes on
        s = S9Stub(root, env, task_root, "full", replies={"report": [(2, trace)]})
        printed = through_gate_b(s)
        check_in("a crashed write: printed as could-not-run", "report rebuild could not run: ValueError: boom in the render", printed)
        check("a crashed write: the gate B question was still asked", "gate_text" in s.names(), str(s.names()))
        s = S9Stub(root, env, task_root, "full")
        real = s.driver.py

        def py_raises(script, *args, **kwargs):
            if script == "report_facts.py":
                raise OSError("the interpreter could not be started")
            return real(script, *args, **kwargs)
        s.driver.py = py_raises
        printed = through_gate_b(s)
        check_in("`py` raising: the same printed line", "report rebuild could not run: OSError: the interpreter could not", printed)
        check("`py` raising: the gate B question was still asked", "gate_text" in s.names(), str(s.names()))
        # an experiment rebuilds too: the rebuild is local, `--no-trace` changes nothing
        s = S9Stub(root, env, task_root, "full", no_trace=True)
        through_gate_b(s)
        check_eq("--no-trace: the same single write", s.names().count("write"), 1)
        # the scribe stops with a question: no write, and nothing after the question
        s = S9Stub(root, env, task_root, "full")
        s.driver.handoff = lambda role, stage, dispatch, result: "qa-doc-scribe S8 QA-9 · halt\nR-1 · unresolved · the report needs a decision"
        try:
            s.driver.boundary_step({"action": "prepare_stage", "stage": "S8"})
            check("a halting scribe: the person is asked", False)
        except story_run.Person:
            check_eq("a halting scribe: no write before the person has answered", s.names().count("write"), 0)
    finally:
        harness.cleanup(root)


def s9_rebuild_prints_and_goes_on() -> None:
    """P1: a write that refuses or raises is one printed line and the story goes on to `stage_done S9`, whose own
    check refuses with the doors; a second write over unchanged facts prints nothing new; no report, the real script."""
    import contextlib
    import io
    root, task_root, env = seed(S9_TASK)
    try:
        damaged = ("test-report.md: a start marker `<!-- facts:verdict -->` has no end at line 4; report_facts.py does "
                   "not guess where the scribe's prose ends - repair the markers\n"
                   "or have the scribe redo the report: `story_step.py start --task QA-9 --stage S8 --role qa-doc-scribe`")
        s = S9Stub(root, env, task_root, "skip", replies={"report": [(1, damaged)]})
        printed = s.run()
        check_in("write ok False: one printed line, with the refusal's own words", "report rebuild refused, the report is as it was: "
                 "test-report.md: a start marker", printed)
        check_in("write ok False: both lines of it, joined on that one line", " | or have the scribe redo the report", printed)
        eq("write ok False: and the story went on to stage_done S9", s.names()[-1], "stage_done S9 skipped")
        eq("write ok False: no question to the person (nothing asked of anyone)", s.conductor_calls, [])

        trace = "Traceback (most recent call last):\n  File \"report_facts.py\", line 1, in <module>\nValueError: boom in the render"
        s = S9Stub(root, env, task_root, "skip", replies={"report": [(1, trace)]})
        printed = s.run()
        check_in("write raising: printed as could-not-run with `<type>: <why>`",
                 "report rebuild could not run: ValueError: boom in the render", printed)
        check_not_in("write raising: the traceback itself is not printed", "Traceback", printed)
        eq("write raising: and the story went on", s.names()[-1], "stage_done S9 skipped")

        s = S9Stub(root, env, task_root, "skip")
        real = s.driver.py

        def py_raises(script, *args, **kwargs):
            if script == "report_facts.py":
                raise OSError("the interpreter could not be started")
            return real(script, *args, **kwargs)
        s.driver.py = py_raises
        printed = s.run()
        check_in("`py` itself raising: the same printed line", "report rebuild could not run: OSError: the interpreter could not be started", printed)
        eq("`py` itself raising: and the story went on", s.names()[-1], "stage_done S9 skipped")

        # a second write over unchanged facts: its output is the same and is not printed again
        s = S9Stub(root, env, task_root, "skip",
                   replies={"report": [(0, "test-report.md: every code-owned block already matches a fresh render")]})
        printed = s.run()
        eq("second write, unchanged facts: said once", printed.count("every code-owned block already matches"), 1, printed)
        s = S9Stub(root, env, task_root, "skip", replies={"report": [
            (0, "test-report.md: code-owned blocks refreshed (verdict)"),
            (0, "test-report.md: every code-owned block already matches a fresh render")]})
        printed = s.run()
        check_in("a write that changed something says so", "report: test-report.md: code-owned blocks refreshed (verdict)", printed)
        check_in("and the later no-op write says that", "already matches", printed)
    finally:
        harness.cleanup(root)
    # the real script on a story with no test-report.md at all (S8 skipped): refused, printed, the door named
    root, task_root, env = seed(S9_TASK)
    try:
        driver = driver_for(root, env, S9_TASK)
        printed = io.StringIO()
        with contextlib.redirect_stdout(printed):
            ok = driver.rebuild_report()
        eq("no report: the rebuild says it did not rebuild", ok, False)
        check_in("no report: one printed line naming S8's scribe", "S8's scribe writes it", printed.getvalue())
        eq("no report: one line", len(printed.getvalue().strip().splitlines()), 1, printed.getvalue())
    finally:
        harness.cleanup(root)


def s9_report_check_refusal_moves_once() -> None:
    """R-S9.1 / FR-42: a `report check:` refusal of the S9 record -> `report_facts.py --write` ONCE and the record
    again ONCE; the same refusal a second time is the conductor's, never the person's; any other refusal is today's."""
    import story_run
    check_eq("the refusal row matches the exit's own line and names the driver's move",
             story_run.match_known("  - report check: test-report.md: block `gate-b` is missing"), ("report_check", "rebuild_report"))
    check("the exit's crash line (`report check could not run`) is not that refusal",
          story_run.match_known("report check could not run: ValueError: boom") is None)
    root, task_root, env = seed(S9_TASK)
    state_file = task_root / "state" / "driver-state.json"
    try:
        # numbers/skip: the refused call is `stage_done S9` itself, and "again" is that call
        s = S9Stub(root, env, task_root, "skip", replies={"stage_done:S9": [(2, S9_REFUSAL), (0, "")]})
        printed = s.run()
        names = s.names()
        eq("skip: S9 recorded twice - refused, then again after the write", names.count("stage_done S9 skipped"), 2, str(names))
        eq("skip: and one write between them besides the two planned ones", names.count("write"), 3, str(names))
        check("skip: the extra write sits between the refusal and the second record",
              names[-3:] == ["stage_done S9 skipped", "write", "stage_done S9 skipped"], str(names))
        eq("skip: the conductor was not called", s.conductor_calls, [])
        check_in("skip: the driver says which row it took", "refusal: known `report_check` → rebuild_report", printed)
        eq("skip: the count is in the driver's state under the boundary", s.driver.state.get("report_rebuilds"), {"S9": 1})
        check("skip: and on disk", json.loads((task_root / "state" / "driver-state.json").read_text(encoding="utf-8"))
              .get("report_rebuilds") == {"S9": 1})

        # the SAME refusal again after the write: the conductor - and the move is not made twice. The loop
        # re-enters the stage after a refused retry (`guarded`), so the second entry meets the refusal once more.
        state_file.unlink(missing_ok=True)
        s = S9Stub(root, env, task_root, "skip", replies={"stage_done:S9": [(2, S9_REFUSAL)]})
        try:
            s.run()
        except story_run.Person as person:
            check("the second refusal goes to the conductor, never the person", False, person.text)
            return
        names = s.names()
        # two planned writes per entry of the stage (the loop enters it twice) and ONE by the move
        eq("twice refused: the move wrote once, not more", s.writes(), 5, str(names))
        eq("twice refused: the conductor was called once, with the refusal", len(s.conductor_calls), 1)
        check_in("twice refused: with the exit's own text", "report check:", s.conductor_calls[0][0])
        eq("twice refused: the record made by the retry is one, then the loop's own entry", names.count("stage_done S9 skipped"), 3, str(names))
        # a driver started again (the exit-3 relaunch) meets the same count: it cannot write -> refuse -> write
        again = S9Stub(root, env, task_root, "skip", replies={"stage_done:S9": [(2, S9_REFUSAL)]})
        again.run()
        names = again.names()
        eq("relaunched: the count survived - no write by the move (the two planned ones only)", again.writes(), 2, str(names))
        eq("relaunched: S9 was recorded once, then the conductor", (names.count("stage_done S9 skipped"), len(again.conductor_calls)), (1, 1))

        # full: the refusal comes out of `story_step finish`, the dispatch is accepted already, so "again" is the
        # S9 record alone - never a second acceptance
        state_file.unlink(missing_ok=True)
        s = S9Stub(root, env, task_root, "full", replies={"finish": [(2, S9_STORY_STEP_REFUSAL)]})
        s.run()
        names = s.names()
        eq("full: one finish, then the S9 record alone", (names.count("finish"), names.count("stage_done S9 done")), (1, 1), str(names))
        check("full: the extra write and the record follow the refused finish",
              names[-3:] == ["finish", "write", "stage_done S9 done"], str(names))
        eq("full: the count is under the boundary of the retro dispatch", s.driver.state.get("report_rebuilds"),
           {f"S9:{S9_DISPATCH}": 1})
        record = [args for script, args in s.log if script == "stage_done.py" and "--stage" in args][-1]
        check("full: the record repeats the arguments story_step used (role and digest)",
              "--role" in record and "qa-retro-analyst" in record and "--digest" in record, str(record))

        # a refusal that is not the report's: no write by the move; the record of a retro skipped by code is a stage the CODE closes (C2-8
        # site 7), so the person is asked through the seam (kind code_close) and the conductor is not called
        state_file.unlink(missing_ok=True)
        s = S9Stub(root, env, task_root, "skip", replies={"stage_done:S9": [(2, "stage_done: S9 cannot close: something else entirely"), (0, "")]})
        got = None
        try:
            s.run()
        except story_run.Person as person:
            got = person
        names = s.names()
        eq("another refusal: no write by the move (only the two planned)", names.count("write"), 2, str(names))
        eq("another refusal: the person is asked (code_close), the conductor is not called",
           (got is not None and got.kind, len(s.conductor_calls)), ("code_close", 0))
        eq("another refusal: no count is kept", s.driver.state.get("report_rebuilds"), None)
    finally:
        harness.cleanup(root)


# --- t-342 (B-271): the budget words, the retro and the bug list ----------------------------------------------------
def b271_budget_words_retro_and_bug_list() -> None:
    """The size line is worded the same in BOTH carriers (the gate B packet and the report), the retro is offered no cut in
    either of its carriers (the packet and phases/s8.md), and a no-trace run - which files nothing outward - still lists
    its bugs by number: with their paths in the gate B packet, with their ids in the report."""
    import gate_brief
    import report_facts
    task = "QA-9"
    root, task_root, env = seed(task)
    try:
        (task_root / "work" / "sizing.json").write_text(json.dumps(
            {"size": "XXL", "computed_budget": 84, "recommended_budget": 28, "cap": 28, "overage": 56}), encoding="utf-8")
        d2_pipeline(task_root, size_initial="XXL", size_final="XXL")
        drafts = task_root / "work" / "bug-drafts"
        drafts.mkdir(parents=True, exist_ok=True)
        for number in (1, 2):
            (drafts / f"BD-{number}.json").write_text(json.dumps(
                {"id": f"BD-{number}", "case": "TC-3", "title": f"the filter loses its state ({number})",
                 "impact": "degraded", "confirmation": "unconfirmed"}), encoding="utf-8")
        harness.run_script("stage_done.py", "--task", task, "--set", "no_trace=true", cwd=root, env=env)
        driver = driver_for(root, env, task)
        eq("B-271: the run is an experiment (it files nothing outward)", driver.no_trace(), True)
        # the budget words: one sentence, said the same way in the packet and in the report, and in the template
        words = "the requirements weigh 84 (each weighted by its priority and area); the XXL cap is 28"
        line = gate_brief.sizing_line(task_root)
        check_in("B-271: the packet's size line says what the requirements weigh and the cap of the size", words, line)
        check_in("B-271: and still says by how much the cap is passed", "**over the cap by 56**", line)
        for old in ("budget 84", "recommended 28", "cap 28,"):
            check_not_in(f"B-271: the packet's old budget words are gone ({old!r})", old, line)
        size_block = report_facts.render(report_facts.build(task_root))["size"]
        check_in("B-271: the report's size block says it in the same words", f"Forecast: **XXL** \u2014 {words}.", size_block)
        for old in ("computed budget", "a weighted count of expected cases"):
            check_not_in(f"B-271: the report's old words are gone ({old!r})", old, size_block)
        template = (harness.PLUGIN_ROOT / "references" / "templates" / "test-report.md").read_text(encoding="utf-8")
        check_in("B-271: the report template carries the same sentence",
                 "the requirements weigh <n> (each weighted by its priority and area); the <size> cap is <n>.", template)
        check_not_in("B-271: and not the old one", "a weighted count of expected cases", template)
        # the retro: no cut is offered, in the packet or in the phase file that tells the orchestrator what to say
        text = driver.gate_text("B")
        s8 = (harness.PLUGIN_ROOT / "skills" / "qa-story" / "phases" / "s8.md").read_text(encoding="utf-8")
        for label, carrier in (("the gate B packet", text), ("phases/s8.md", s8)):
            for phrase in ("skipped or cut", "numbers alone", "ilence is the full retro", "The story ends with the retro"):
                check_not_in(f"B-271: {label} does not offer the retro to be cut ({phrase!r})", phrase, carrier)
        check_in("B-271: phases/s8.md still says the retro is always the full one", "It is\n     always the full retro (`retro_mode: full`)", s8)
        check_in("B-271: the experiment's instruction asks for the bugs and nothing else", "Answer by number for the bugs to file.", text)
        # the bugs by number, with their paths, in a run that files nothing outward
        # HF8-20 (I5): the packet names a READABLE text of the draft, never the JSON file; with no text written yet the row has no path
        packet = gate_brief.render_gate_b(task, task_root)
        for number in (1, 2):
            check_not_in(f"B-271 pin: with no readable text written, bug {number} names no path (never the raw draft)",
                         f"work/bug-drafts/BD-{number}.json", packet)
        import bug_records as BR
        for _draft, text_path in BR.draft_text_paths(task_root):
            text_path.parent.mkdir(parents=True, exist_ok=True)
            text_path.write_text("The filter loses its state.\n", encoding="utf-8")
        packet = gate_brief.render_gate_b(task, task_root)
        for number, (_draft, text_path) in enumerate(BR.draft_text_paths(task_root), start=1):
            check_in(f"B-271 pin: gate B lists bug {number} by number", f"{number}. **the filter loses its state ({number})**", packet)
            check_in("B-271 pin: with the path of its readable text", gate_brief.portable(text_path, task_root), packet)
            check_not_in("B-271 pin: and still not the raw draft", f"work/bug-drafts/BD-{number}.json", packet)
            check_in("B-271 pin: the same list is in the text the driver shows", f"{number}. **the filter loses its state ({number})**", text)
        check_in("B-271 pin: the packet says the bugs stay as files in the repository", "bugs stay as files in this repository", packet)
        bugs = report_facts.render(report_facts.build(task_root))["bugs"]
        check_in("B-271 pin: the report's section counts them", "## Product bugs \u2014 0 confirmed \u00b7 2 unconfirmed", bugs)
        for number in (1, 2):
            check_in(f"B-271 pin: and lists bug {number} by number, with its file's id",
                     f"{number}. **minor \u00b7 TC-3** \u2014 the filter loses its state ({number}) (BD-{number})", bugs)
    finally:
        harness.cleanup(root)


# --- t-342 (B-273): every resume says why, and a form that is all there is built by code -----------------------------
S1_FORM = """schema_version: 1
contract: s1-scout-to-tester
stage: S1
from_role: qa-scout
to_role: qa-requirements-tester
header:
  role: qa-scout
  stage: S1
  window: {window}
  verdict: {verdict}
scope:
{rows}tried: []
tried_note: a grounding window; nothing was tried here
"""
S1_ROW = "  - id: {id}\n    state: {state}\n    reason: {reason}\n"
S1_PROSE = "I have collected the sources and everything went well. The manifest is written: work/context-manifest.json."


def s1_form(task: str = "QA-9", *, verdict: str = "ok", window=None, rows=None, extra: str = "") -> str:
    rows = [("SRC-1", "found", "the task itself")] if rows is None else rows
    return S1_FORM.format(window=window or task, verdict=verdict,
                          rows="".join(S1_ROW.format(id=i, state=s, reason=r) for i, s, r in rows)) + extra


def b273_resume_reason_classes() -> None:
    """`resume_reason`: the exit gate's findings in one line - the classes it knows by their words, the rest quoted whole."""
    import story_run
    digest = ("digest: your final message is not the handoff form. The orchestrator reads it whole on every later turn, so "
              "it is exactly: `<role> <stage> <window>`. What does not fit: the digest names no artifact path.")
    form = "handover form S1-qa-scout-1.yaml - header.verdict: not filled"
    rr = story_run.resume_reason
    eq("B-273: a final message that is not the form", rr([digest]), "the role's final message is not the handoff form")
    eq("B-273: a handover form that is not complete", rr([form]), "the handover form is not complete")
    eq("B-273: both, each once, in order", rr([digest, form, digest]),
       "the role's final message is not the handoff form; the handover form is not complete")
    eq("B-273: a missing required output is a class of its own", rr(["context-manifest.json: required key 'ticket' is missing"]),
       "a required output of the role is missing")
    eq("B-273: unclassified, with the exit gate's own words", rr(["something odd happened"]), "unclassified (something odd happened)")
    eq("B-273: a class and a stranger together", rr([digest, "something odd happened"]),
       "the role's final message is not the handoff form; unclassified (something odd happened)")
    eq("B-273: a text, not a list, is one finding", rr("something   odd\nhappened"), "unclassified (something odd happened)")
    eq("B-273: the quote is cut at 200 characters", rr(["x" * 300]), "unclassified (" + "x" * 200 + ")")
    eq("B-273: no finding at all still says something", rr([]), "unclassified (the exit gate named no finding)")
    eq("B-273: a blank finding is no finding", rr(["  ", ""]), "unclassified (the exit gate named no finding)")
    check_in("B-273: the controller's refusal of a structured artifact is a class of its own",
             "structured artifact", rr(["story_step: refused - S3 structured test plan invalid: OB-1: x"]))


def b273_run_claude_names_the_reason() -> None:
    """Every resume prints `resume <dispatch>: <reason>` and writes `resume_reason` into its journal row; a call that is
    not a resume does neither; a caller that names no reason gets `unclassified`, never silence."""
    task = "QA-9"
    root, task_root, env = seed(task)
    try:
        set_control(root, {"resume": {"result": "ok"}, "conductor": {"action": "continue", "did": "x"}})
        driver = driver_for(root, env, task)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            driver.run_claude("conductor", "decide", stage="S1")
            driver.run_claude("role", "go on", role="qa-scout", dispatch="S1-qa-scout-1", stage="S1", resume="sess-x",
                              resume_reason="the person answered what the role stopped for")
            driver.run_claude("role", "go on", role="qa-scout", dispatch="S1-qa-scout-1", stage="S1", resume="sess-x")
        rows = jsonl(task_root / "state/driver-runs.jsonl")
        eq("B-273: three calls, three rows", [r["resumed"] for r in rows], [False, True, True])
        eq("B-273: a call that is not a resume writes no reason", "resume_reason" in rows[0], False)
        eq("B-273: a resume writes the caller's reason", rows[1].get("resume_reason"), "the person answered what the role stopped for")
        eq("B-273: and a caller that names none gets `unclassified`", rows[2].get("resume_reason"), "unclassified (the call named no reason)")
        printed = out.getvalue().splitlines()
        eq("B-273: each role resume prints one line, in the log's own words",
           [l for l in printed if l.startswith("resume ")],
           ["resume S1-qa-scout-1: the person answered what the role stopped for",
            "resume S1-qa-scout-1: unclassified (the call named no reason)"])
    finally:
        harness.cleanup(root)


def b273_resume_prints_its_reason() -> None:
    """The prose handoff of the loop test, read for its REASON: the form is not all there (a template with placeholders),
    so the role is resumed as before - and the driver says why, once, in the log and in the journal row."""
    task = "QA-9"
    root, task_root, env = seed(task)
    try:
        set_control(root, {"roles": {"qa-scout": {
            "files": {"work/context-manifest.json": json.dumps(GOOD_MANIFEST).replace("{task}", task),
                      "work/context-bundle.json": "{}"},
            "result": "I have collected the sources and everything went well. The manifest is written."}},
            "resume": {"result": SCOUT_DIGEST.replace("{task}", task)}})
        out = run_driver(root, env, "--task", task, "--max-boundaries", "1")
        eq("B-273: the prose handoff still ends in a done stage", out.returncode, 0, out.stdout[-1200:] + out.stderr[-600:])
        eq("B-273: one role call and one resume (nothing was assembled)", [c["kind"] for c in stub_calls(root)], ["role", "resume"])
        said = [l for l in out.stdout.splitlines() if l.startswith("resume ")]
        eq("B-273: the log prints one reason line", len(said), 1, out.stdout[-1500:])
        check_in("B-273: it names the dispatch and the class", "resume S1-qa-scout-1: the role's final message is not the handoff form (not assembled by code: ", said[0])
        check_in("B-273: and why code did not assemble it (the form's header is still the template's)", "not filled", said[0])
        rows = jsonl(task_root / "state/driver-runs.jsonl")
        eq("B-273: the journal row of the resume carries the same words", rows[1].get("resume_reason"), said[0][len("resume S1-qa-scout-1: "):])
        eq("B-273: and the first call's row carries none", "resume_reason" in rows[0], False)
    finally:
        harness.cleanup(root)


def b273_form_assembled_by_code_closes_without_a_resume() -> None:
    """The class of man1 02.10: the role did the work and its last message is prose. Its handover form says everything the
    digest needs, so the driver builds the digest, marks it `assembled_by: code`, and the stage closes with NO resume."""
    task = "QA-9"
    root, task_root, env = seed(task)
    try:
        set_control(root, {"roles": {"qa-scout": {
            "files": {"work/context-manifest.json": json.dumps(GOOD_MANIFEST).replace("{task}", task),
                      "work/context-bundle.json": "{}",
                      "work/handoffs/S1-qa-scout-1.yaml": s1_form(task)},
            "result": S1_PROSE}},
            "resume": {"result": "THE ROLE MUST NOT BE ASKED"}})
        out = run_driver(root, env, "--task", task, "--max-boundaries", "1")
        eq("B-273: the story goes on", out.returncode, 0, out.stdout[-1200:] + out.stderr[-600:])
        eq("B-273: one role call and NO resume", [c["kind"] for c in stub_calls(root)], ["role"])
        check_in("B-273: the log says it was assembled, by code, and not resumed",
                 "the role's final message is not the handoff form; the form is assembled by code from its handover form and its artifact (assembled_by: code) - no resume", out.stdout)
        check("B-273: and no resume line is printed", not [l for l in out.stdout.splitlines() if l.startswith("resume ")], out.stdout[-800:])
        # a dispatch that is accepted has its saved result set aside as `<dispatch>.done.json` (`finish`)
        saved = json.loads((task_root / "state/driver-runs/S1-qa-scout-1.done.json").read_text(encoding="utf-8"))
        eq("B-273: the handoff record is marked `assembled_by: code` (FR-8, P13)", saved.get("assembled_by"), "code")
        eq("B-273: the digest is the role's own fields, copied",
           saved["result"], f"qa-scout S1 {task} \u00b7 ok\nSRC-1 \u00b7 found \u00b7 the task itself\nwork/context-manifest.json\nassembled_by: code")
        eq("B-273: the role's own last message is kept whole beside it", saved.get("role_final_message"), S1_PROSE)
        eq("B-273: S1 is done on the assembled digest", s0_pipeline(task_root)["stages"]["S1"]["status"], "done")
        rows = jsonl(task_root / "state/driver-runs.jsonl")
        eq("B-273: the journal holds the one call, not a resume", [r["resumed"] for r in rows], [False])
    finally:
        harness.cleanup(root)


def b273_assembly_edges() -> None:
    """`assemble_digest` builds only from a complete form, and `handoff` uses the result only when the same exit gate that
    would have judged the role's own message lets it through; every other case resumes the role, with the reason."""
    import role_digest
    import story_run
    task = "QA-9"
    root, task_root, env = seed(task)
    try:
        driver = driver_for(root, env, task)
        form = task_root / "work" / "handoffs" / "S1-qa-scout-1.yaml"
        form.parent.mkdir(parents=True, exist_ok=True)
        (task_root / "work" / "context-manifest.json").write_text("{}", encoding="utf-8")

        def assemble(text, message=S1_PROSE):
            if text is None:
                form.unlink(missing_ok=True)
            else:
                form.write_text(text, encoding="utf-8")
            return driver.assemble_digest("qa-scout", "S1", "S1-qa-scout-1", {"result": message})

        good = f"qa-scout S1 {task} \u00b7 ok\nSRC-1 \u00b7 found \u00b7 the task itself\nwork/context-manifest.json\nassembled_by: code"
        eq("B-273: a complete form is assembled", assemble(s1_form(task)), (good, ""))
        eq("B-273: `concerns` is a verdict the code copies too", assemble(s1_form(task, verdict="concerns"))[0].splitlines()[0],
           f"qa-scout S1 {task} \u00b7 concerns")
        eq("B-273: the assembled digest passes the real digest check", role_digest.check(good), [])
        eq("B-273: a row with no reason is a row without one", assemble(s1_form(task, rows=[("SRC-1", "found", "<= 80 characters>")]))[0].splitlines()[1],
           "SRC-1 \u00b7 found")
        eq("B-273: a row per item, in the form's order", assemble(s1_form(task, rows=[("SRC-1", "found", "a"), ("SRC-2", "not_found", "b")]))[0].splitlines()[1:3],
           ["SRC-1 \u00b7 found \u00b7 a", "SRC-2 \u00b7 not_found \u00b7 b"])
        # --- what is NOT assembled, and why (the reason is what the log prints) ---
        for label, text, message, why in [
            ("no handover form", None, S1_PROSE, "the role wrote no handover form"),
            ("a halt is the role's own word", s1_form(task, verdict="halt"), S1_PROSE, "a halt is the role's own word"),
            ("an impossible verdict is a halt too", s1_form(task, verdict="impossible"), S1_PROSE, "a halt is the role's own word"),
            ("a verdict outside the closed list", s1_form(task, verdict="great"), S1_PROSE, "outside the closed list is its own to correct"),
            ("a verdict still the template's", s1_form(task, verdict="<one of vocabulary.header_verdicts>"), S1_PROSE, "header is not filled"),
            ("a window still the template's", s1_form(task, window="<TICKET>"), S1_PROSE, "header is not filled"),
            ("a row whose state is the template's", s1_form(task, rows=[("SRC-1", "<one of vocabulary.row_states>", "x")]), S1_PROSE, "row 1 of the form is not filled"),
            ("a reason over the limit (code never shortens a role's words)", s1_form(task, rows=[("SRC-1", "found", "r" * 81)]), S1_PROSE, "the reason of SRC-1 is 81 characters, the form allows 80"),
            ("no rows at all", s1_form(task, rows=[]), S1_PROSE, "the handover form lists no rows"),
            ("an empty final message", s1_form(task), "  ", "the role's final message is empty"),
            ("a path that is not a file", s1_form(task), "done: work/nowhere.json", "no artifact path of the role is a file on disk"),
            ("an absolute path is never used", s1_form(task), "done: C:\\somewhere\\work\\context-manifest.json", "no artifact path of the role is a file on disk"),
            ("a form whose digest would not fit", s1_form(task, rows=[(f"SRC-{n}", "found", "x" * 70) for n in range(1, 30)]), S1_PROSE, "the digest limit is 1800"),
            ("a form one line over what a digest keeps when read back (41)", s1_form(task, rows=[(f"S{n}", "found", "") for n in range(1, 39)]), S1_PROSE, "keeps the last 40"),
        ]:
            digest, reason = assemble(text, message)
            eq(f"B-273: {label}: nothing is assembled", digest, "")
            check_in(f"B-273: {label}: and the reason names it", why, reason)
        head_rows = [(f"R{k:02d}", "found", "y" * 70) for k in range(1, 21)]
        short = assemble(s1_form(task, rows=head_rows + [("Z1", "found", "z")]))[0]
        fill = 1 + story_run.DIGEST_MAX - len(short)
        exact, over = (assemble(s1_form(task, rows=head_rows + [("Z1", "found", "z" * n)])) for n in (fill, fill + 1))
        eq("B-273: a digest of exactly DIGEST_MAX characters is assembled (AT the limit)", (len(exact[0]), exact[1]), (story_run.DIGEST_MAX, ""))
        eq("B-273: one character more is not (BEYOND it), and the reason says so", (over[0], f"{story_run.DIGEST_MAX + 1} characters" in over[1]), ("", True))
        at_the_line = assemble(s1_form(task, rows=[(f"S{n}", "found", "") for n in range(1, 38)]))
        eq("B-273: a form of exactly 40 lines is assembled (AT the limit; 41 above is not)", (len(at_the_line[0].splitlines()), at_the_line[1]), (40, ""))
        # a path the role did not print but the form names: the form's own artifact is the fallback
        digest, reason = assemble(s1_form(task, extra="artifacts:\n  context_manifest: work/context-manifest.json\n"), "I did everything.")
        eq("B-273: the form's artifact path stands in for a message that names none", digest.splitlines()[2], "work/context-manifest.json")
        # a path in the message is used when the form names none, and a project-relative one is accepted as the older digests wrote it
        art = f"qa-factory/artifacts/{task}/work/context-manifest.json"
        eq("B-273: a project-relative path of the message is used as written", assemble(s1_form(task), f"Wrote {art}.")[0].splitlines()[2], art)
        # t-363 B5 (B-287, critic t-346 F5): the FORM's own `artifacts.*` field comes first, the prose only when the field is
        # empty; the old order let the last existing file of the prose win over the structure.
        import contextlib
        import io
        (task_root / "work" / "other-artifact.json").write_text("{}", encoding="utf-8")
        field = "artifacts:\n  context_manifest: work/context-manifest.json\n"
        prose_other = "I wrote work/context-manifest.json and then work/other-artifact.json."
        said = io.StringIO()
        with contextlib.redirect_stdout(said):
            digest, reason = assemble(s1_form(task, extra=field), prose_other)
        eq("B5: the field names one file and the prose ends with another that exists: the FIELD wins", (digest.splitlines()[2], reason),
           ("work/context-manifest.json", ""))
        check_in("B5: ...and a [driver] note names the prose path that was ignored", "[driver] S1-qa-scout-1: the form's artifact path "
                 "work/context-manifest.json is used; the path the role's message names (work/other-artifact.json) is ignored", said.getvalue())
        said = io.StringIO()
        with contextlib.redirect_stdout(said):
            digest, reason = assemble(s1_form(task, extra=field), f"Wrote {art}.")
        eq("B5: the prose spells the SAME file another way (project-relative): no disagreement, no note", (digest.splitlines()[2], said.getvalue()),
           ("work/context-manifest.json", ""))
        said = io.StringIO()
        with contextlib.redirect_stdout(said):
            digest, reason = assemble(s1_form(task, extra="artifacts:\n  context_manifest: <path>\n"), prose_other)
        eq("B5: a field that is still the template's is EMPTY: the prose is used, as before (the last existing file)",
           (digest.splitlines()[2], said.getvalue()), ("work/other-artifact.json", ""))
        eq("B5: a form with no field at all and a prose path is today's behaviour", assemble(s1_form(task), prose_other)[0].splitlines()[2],
           "work/other-artifact.json")
        digest, reason = assemble(s1_form(task, extra="artifacts:\n  context_manifest: work/nowhere.json\n"), prose_other)
        eq("B5: the field names a file that is NOT there while the prose names one that is: nothing is assembled", digest, "")
        check_in("B5: ...and the reason reports the FIELD's path as missing (FR-37), not the prose's", "`work/nowhere.json` is not a relative path of a file on disk", reason)
        check_in("B5: ...and says the prose is not used in its place", "not used in its place", reason)
        digest, reason = assemble(s1_form(task, extra="artifacts:\n  a: work/nowhere.json\n  b: work/other-artifact.json\n"), "done")
        eq("B5: two fields, the first missing and the second there: the existing one is the artifact (as before)", digest.splitlines()[2], "work/other-artifact.json")
        digest, reason = assemble(s1_form(task, extra="artifacts:\n  a: C:\\somewhere\\x.json\n"), prose_other)
        eq("B5: an absolute path in the field is not written into a digest", digest, "")
        check_in("B5: ...and the reason names it", "C:\\somewhere\\x.json", reason)
        digest, reason = assemble(s1_form(task), "nothing to name")
        eq("B5: the field empty AND no prose path: the missing-artifact refusal, unchanged", (digest, reason),
           ("", "no artifact path of the role is a file on disk"))
        # critic t-346: TWO headers in one message (`ok` first, `halt` later) over an `ok` form. `said` takes the FIRST header, so
        # it agrees with the form; the `is_halting` guard (any line) is the only barrier that keeps the halt reaching the person.
        ok_header = f"qa-scout S1 {task} · ok"
        two_headers = f"{ok_header}\nSRC-1 · found · the task itself\nwork/context-manifest.json\nqa-scout S1 {task} · halt\nI need a person to decide."
        digest, reason = assemble(s1_form(task), two_headers)
        eq("B-273: a message with an `ok` header and a later `halt` header is not assembled over an `ok` form - the halt reaches the person",
           digest, "")
        check_in("B-273: two headers: and the reason names the halt", "the role's own message halts", reason)
        digest, reason = assemble(s1_form(task), f"{ok_header}\nSRC-1 · found · the task itself\nwork/context-manifest.json")
        eq("B-273: negative control: the same message with the single `ok` header is still assembled", (digest.splitlines()[0], reason),
           (f"qa-scout S1 {task} · ok", ""))

        # --- handoff(): the assembled digest is judged by the SAME exit gate; anything else wrong is the role's ---
        gate_error = role_digest.refusal("qa-scout", ["the first line is not a digest header"])
        result = {"result": S1_PROSE, "session_id": "sess-1", "is_error": False, "exit_code": 0, "stderr": ""}
        valid = f"qa-scout S1 {task} \u00b7 ok\nSRC-1 \u00b7 found \u00b7 the task itself\nwork/context-manifest.json"
        form.write_text(s1_form(task), encoding="utf-8")

        def wire(errors_for):
            """Replace the exit gate and the form check, and the paid call: (calls of `run_claude`, calls of `assemble_digest`)."""
            resumed, assembled = [], []
            driver.form_errors = lambda dispatch: []
            driver.exit_errors = errors_for
            real_assemble = story_run.Driver.assemble_digest.__get__(driver)
            driver.assemble_digest = lambda *a, **k: assembled.append(a) or real_assemble(*a, **k)
            driver.run_claude = lambda kind, prompt, **kw: resumed.append(kw) or {
                "result": valid, "session_id": "sess-2", "is_error": False, "exit_code": 0, "stderr": ""}
            driver.state["refusal_resumes"] = {}
            return resumed, assembled

        def real_gate(role, digest, dispatch=None):
            errs = role_digest.check(digest, [])
            return [role_digest.refusal(role, errs)] if errs else []
        resumed, assembled = wire(real_gate)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            got = driver.handoff("qa-scout", "S1", "S1-qa-scout-1", result)
        eq("B-273: handoff returns the assembled digest and calls no paid resume", (got == good, resumed), (True, []))
        eq("B-273: the saved result carries the mark", json.loads((driver.state_dir / "driver-runs" / "S1-qa-scout-1.json").read_text(encoding="utf-8")).get("assembled_by"), "code")
        # an error beside the digest's: the role is resumed (assembling would not save the resume), nothing is tried
        calls = {"n": 0}

        def two_findings(role, digest, dispatch=None):
            calls["n"] += 1
            return [gate_error, "some other finding"] if calls["n"] == 1 else []
        resumed, assembled = wire(two_findings)
        with contextlib.redirect_stdout(io.StringIO()):
            driver.handoff("qa-scout", "S1", "S1-qa-scout-1", dict(result, session_id="sess-3"))
        eq("B-273: another finding beside the digest's: no assembly is tried", assembled, [])
        eq("B-273: the role is resumed once, with the reasons of BOTH findings", [kw.get("resume_reason") for kw in resumed],
           ["the role's final message is not the handoff form; unclassified (some other finding)"])
        # the assembled form that the gate refuses is never used: the role is resumed, and the log says why
        # The gate refuses until the role has been resumed (read from the paid-call spy), not for the first N calls: since C2-4
        # `handoff` asks the exit gate once more before any assembly (`shorten_form`'s guard, t-908 §3.2), so a counter shifts
        # by one and lets the assembled form through - the behaviour under test (t-342 / B-273: a refused assembly is never used,
        # the role is resumed once with the reason; t-908 §4 K9-1 "stays", its non-goals name B-273) did not change.
        def refuses_the_assembled(role, digest, dispatch=None):
            return [] if resumed else [gate_error]
        resumed, assembled = wire(refuses_the_assembled)
        with contextlib.redirect_stdout(io.StringIO()):
            driver.handoff("qa-scout", "S1", "S1-qa-scout-1", dict(result, session_id="sess-4"))
        eq("B-273: assembly was tried once", len(assembled), 1)
        check("B-273: and the role was resumed with the reason", len(resumed) == 1 and resumed[0].get("resume_reason", "").startswith(
            "the role's final message is not the handoff form (not assembled by code: the assembled form still fails the exit gate: digest: your final message"),
            str(resumed))
        # a form that is not there at all: the role is resumed as it always was
        form.unlink()
        resumed, assembled = wire(lambda role, digest, dispatch=None: [gate_error] if digest == S1_PROSE else [])
        with contextlib.redirect_stdout(io.StringIO()):
            driver.handoff("qa-scout", "S1", "S1-qa-scout-1", dict(result, session_id="sess-5"))
        eq("B-273: with no handover form the role is resumed, and the log names that", [kw.get("resume_reason") for kw in resumed],
           ["the role's final message is not the handoff form (not assembled by code: the role wrote no handover form)"])
        # --- critic t-346 F1 (FR-47): a halt of the role's own is never written over by the form's `ok` ---
        halting = f"qa-scout S1 {task} · halt\nI could not reach the source and stopped.\nwork/context-manifest.json"
        digest, reason = assemble(s1_form(task), halting)
        eq("F1: a halting message over an `ok` form is NOT assembled", digest, "")
        check_in("F1: and the reason says the halt is the role's word", "the role's own message halts", reason)
        digest, reason = assemble(s1_form(task), f"qa-scout S1 {task} · concerns\nSome doubts remain.\nwork/context-manifest.json")
        eq("F1: a message whose own verdict differs from the form's is NOT assembled", digest, "")
        check_in("F1: and both verdicts are named", "says `concerns` and its form says `ok`", reason)
        digest, reason = assemble(s1_form(task), f"qa-scout S1 {task} · ok\nAll went well.\nwork/context-manifest.json")
        eq("F1 plain case: a message that agrees with the form is assembled", (digest.splitlines()[0], reason), (f"qa-scout S1 {task} · ok", ""))
        eq("F1 plain case: the prose message still is", assemble(s1_form(task))[0], good)
        resumed, assembled = wire(lambda role, digest, dispatch=None: [gate_error] if "halt" in digest else [])
        with contextlib.redirect_stdout(io.StringIO()):
            driver.handoff("qa-scout", "S1", "S1-qa-scout-1", dict(result, result=halting, session_id="sess-6"))
        check("F1: through handoff the halt is not assembled over: the role is resumed with the reason",
              len(resumed) == 1 and "the role's own message halts" in resumed[0].get("resume_reason", ""), str(resumed))
    finally:
        harness.cleanup(root)


def b273_resume_reason_sites() -> None:
    """R6 (critic t-346): the reason strings of every resume site - `resume_with`, `resume_role`, a resume the driver chooses
    for a call the service cut off, and a retry after a broken response."""
    import infra_failure
    import story_run
    task = "QA-9"
    root, task_root, env = seed(task)
    try:
        driver = driver_for(root, env, task)
        dispatch = "S1-qa-scout-1"
        seen = []
        driver.run_claude = lambda kind, prompt, **kw: seen.append(kw) or {
            "result": "ok", "session_id": "sess-1", "is_error": False, "exit_code": 0, "stderr": "", "num_turns": 3}
        digest_error = "digest: your final message is not the handoff form. What does not fit: x"
        with contextlib.redirect_stdout(io.StringIO()):
            driver.resume_with(story_run.Refusal("exit gate for " + dispatch, findings=[digest_error]), "S1", dispatch, "sess-1", "lead: ")
            driver.resume_with(story_run.Refusal("x", findings=[digest_error]), "S1", dispatch, "sess-1", "lead: ", reason="the stand answers now")
        eq("R6: resume_with classifies the refusal's findings when it is given no reason",
           seen[0]["resume_reason"], "the factory refused to close the dispatch: the role's final message is not the handoff form")
        eq("R6: and uses the caller's reason when it has one", seen[1]["resume_reason"], "the stand answers now")
        # resume_role: a halt answered, and a threshold stop answered
        driver.state["sessions"][dispatch] = "sess-9"
        driver.handoff = lambda *a, **k: "qa-scout S1 QA-9 · ok\nwork/x.json"
        driver.question_threshold = lambda *a, **k: None
        driver.finish = lambda *a, **k: ("", None)
        driver.question_resume_prompt = lambda d, w: "the words"
        seen.clear()
        with contextlib.redirect_stdout(io.StringIO()):
            driver.resume_role("S1", "qa-scout", dispatch, "go on")
            driver.state["question_stop"] = {"resume": True, "dispatch": dispatch}
            driver.resume_role("S1", "qa-scout", dispatch, "go on")
        eq("R6: resume_role names what the person answered",
           [kw["resume_reason"] for kw in seen],
           ["the person answered what the role stopped for", "the person answered the question the role was stopped on"])
    finally:
        harness.cleanup(root)
    # the two resumes the driver chooses itself, through the stub claude (a real `run_claude`)
    root, task_root, env = seed(task)
    real_classify = infra_failure.classify
    try:
        set_control(root, {"resume": {"result": "ok"}})
        driver = driver_for(root, env, task)
        driver.sleep = lambda seconds: None
        driver.state["interrupted"][dispatch] = {"kind": "transient", "session_id": "sess-old", "worked": True, "num_turns": 5}
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            driver.run_claude("role", "go on", role="qa-scout", dispatch=dispatch, stage="S1")
        rows = jsonl(task_root / "state/driver-runs.jsonl")
        eq("R6: a resume the driver chooses for a cut-off call says so",
           rows[-1].get("resume_reason"), "an earlier call of this dispatch was cut off by the model service; its own session goes on")
        check_in("R6: and prints it", f"resume {dispatch}: an earlier call of this dispatch was cut off", out.getvalue())
        # a broken response retried in the session that did the work
        calls = {"n": 0}

        def classify(result, rules, host=None):
            calls["n"] += 1
            return {"kind": "transient", "rule": "t", "retry_code": "service_unavailable"} if calls["n"] == 1 else None
        infra_failure.classify = classify
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            driver.run_claude("role", "go on", role="qa-scout", dispatch="S1-qa-scout-2", stage="S1", resume="sess-x",
                              resume_reason="the person answered what the role stopped for")
        rows = jsonl(task_root / "state/driver-runs.jsonl")[-2:]
        eq("R6: the first call keeps the caller's reason, the retry names the broken response",
           [r.get("resume_reason") for r in rows],
           ["the person answered what the role stopped for",
            "the model service broke the response (retry 1 of 2); the session that did the work goes on"])
        eq("R6: both are printed", len([l for l in out.getvalue().splitlines() if l.startswith("resume ")]), 2)
    finally:
        infra_failure.classify = real_classify
        harness.cleanup(root)


def main() -> None:
    run_scenarios([], [
        delivery_closed_story_and_bug_trigger,
        d3_resume_and_readers,
        d3_experiment_delivery,
        d3_delivery_mark,
        d3_launch_record,
        d3_three_attempts,
        s9_report_rebuilt_last,
        s8_report_rebuilt_before_gate_b,
        s9_rebuild_prints_and_goes_on,
        s9_report_check_refusal_moves_once,
        b271_budget_words_retro_and_bug_list,
        b273_resume_reason_classes,
        b273_run_claude_names_the_reason,
        b273_resume_prints_its_reason,
        b273_form_assembled_by_code_closes_without_a_resume,
        b273_assembly_edges,
        b273_resume_reason_sites,
    ])
    harness.finish("test_story_run_delivery")


if __name__ == "__main__":
    main()
