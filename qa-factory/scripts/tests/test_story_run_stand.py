#!/usr/bin/env python3
"""The stand (t-017 D2: B-005, owner decision D-0014), first third, by the driver in this process with `claude`
replaced by the stub: the ONE question about a stand, `stand_check`, at the entry of S5 and S6 that have something
to run (nothing starts before it, nothing that runs nothing asks it), its three answers, that it is asked once, and
the person's free words.

Every scenario builds a Driver in this process, which changes the working directory, so they run one after
another (`run_scenarios([], [...])`). The helpers, the stub and the runner live in `story_run_common.py`. The rest
of the stand scenarios are in test_story_run_stand_b.py and test_story_run_stand_c.py (cut by measured seconds,
each file at most 75 s, t-104).
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import check, check_in, check_not_in  # noqa: E402
from story_run_common import (  # noqa: E402
    run_scenarios,
    BOM, D2_ASKED_ONCE, D2_DEAD, d2_alive_server, d2_answer, d2_conductor_calls, d2_driver, d2_enter,
    d2_pipeline, d2_seed, d2_stand_at, d2_waiver, eq, rules_broken, s0_journal, s0_pipeline, s0_question,
    s0_state, set_control, stub_calls,
)


def d2_stand_question() -> None:
    """(c)(e)(h) and D-0014: the question before S5, its three answers, and asked ONCE. In-process."""
    import story_run
    task = "QA-9"
    server, alive = d2_alive_server()
    root, task_root, env = d2_seed(task, environment="Local", pending=True, url=D2_DEAD)
    try:
        # --- (c) entry into S5 with a named stand that does not answer: a question, and no role starts ---
        driver, started, steps, probes = d2_driver(root, env, task)
        eq("D2(c) entry into S5 with an unconfirmed stand asks: exit 3", d2_enter(driver, "S5"), 3)
        first = s0_question(task_root)
        check_in("D2(c) the question is of kind environment", "kind: environment", first)
        check_in("D2(c) at S5", "stage: S5", first)
        check_in("D2(c) it names the stand that did not answer", "the stand `Local` did not answer when I checked it just now", first)
        check_in("D2(c) and offers the other configured stand by name", "`Staging`", first)
        check_in("D2(c) and `retry` after the stand is up", "(a) `retry` — bring `Local` up", first)
        check_in("D2(c) and going on without one, by the token `go on`", "`go on` — go on without a stand", first)
        eq("D2(c) the question obeys human-questions.md", rules_broken(first), [])
        check_in("D2(c) the probe's own words are beside it, not in it", "NO ANSWER",
                 (task_root / "state" / "driver-question-details.md").read_text(encoding="utf-8"))
        check_not_in("D2(c) not in the body", "NO ANSWER", first)
        eq("D2(c) NO S5 role started", started, [])
        check("D2(c) and no `story_step start` was made", not [s for s in steps if s and s[0] == "start"], str(steps))
        eq("D2(c) nor any claude call", stub_calls(root), [])
        check("D2(c) and no S5 dispatch is registered", not [d for d in (json.loads((task_root / "state" / "controller.json").read_text(encoding="utf-8")).get("dispatches") or {}) if d.startswith("S5")])
        eq("D2(c) the driver remembers which stage the question is about", s0_state(task_root).get("stand_question"), "S5")
        eq("D2(c) and the probe ran once", len(probes), 1)

        # --- (e) the answer names a configured stand: environment is set, and the NEXT entry probes it -----
        answer = d2_answer(root, "STAGING.")
        driver, started, steps, probes = d2_driver(root, env, task, answer=answer)
        eq("D2(e) a name (any case, a full stop) puts the stand on the story and the next entry probes it: still dead, asks again", d2_enter(driver, "S5"), 3)
        pipeline = s0_pipeline(task_root)
        eq("D2(e) environment is the configured spelling, pending still true", (pipeline["environment"], pipeline["environment_pending"]), ("Staging", True))
        again = s0_question(task_root)
        check_in("D2(e) the question comes back CHANGED, naming that stand", "the stand `Staging` did not answer", again)
        check("D2(e) FR-7: its body is not the one already answered", story_run.question_body_sha(first) != story_run.question_body_sha(again))
        eq("D2(e) that entry probed the named stand", probes[0][:2], ("--env", "Staging"))
        eq("D2(e) no conductor for a name", d2_conductor_calls(root), [])
        check("D2(e) the answer is a human_answer in the journal", any(e.get("event") == "human_answer" and "stand at S5: STAGING." in str(e.get("notes")) for e in s0_journal(root)), str(s0_journal(root))[-300:])
        eq("D2(e) and no role started", started, [])

        # --- `retry` after the stand came up: journal only, the next entry confirms it -----------------------
        d2_stand_at(root, alive)
        answer = d2_answer(root, "retry")
        driver, started, steps, probes = d2_driver(root, env, task, answer=answer)
        eq("D2(e) `retry` with the stand up: S5 goes on: exit 0", d2_enter(driver, "S5"), 0)
        pipeline = s0_pipeline(task_root)
        eq("D2(e) the stand is confirmed by its probe: pending false", (pipeline["environment"], pipeline["environment_pending"]), ("Staging", False))
        eq("D2(e) both S5 roles started, in order", started, [("S5", "qa-automator"), ("S5", "qa-code-critic")])
        eq("D2(e) `retry` called no conductor", d2_conductor_calls(root), [])
        check("D2(e) and is a journal line only", any(e.get("event") == "human_answer" and "S5 (retry): retry" in str(e.get("notes")) for e in s0_journal(root)))
        check("D2(e) the question flag is gone", "stand_question" not in s0_state(task_root))

        # --- F4: a confirmed stand is NOT probed again at S5 (next window) or at S6 -------------------------
        driver, started, steps, probes = d2_driver(root, env, task)
        d2_enter(driver, "S5")
        eq("D2 F4: the next S5 window goes through without a probe", (len(probes), started), (0, [("S5", "qa-automator"), ("S5", "qa-code-critic")]))
        driver, started, steps, probes = d2_driver(root, env, task)
        eq("D2 F4: S6 goes through without a probe", (d2_enter(driver, "S6"), len(probes), started), (0, 0, [("S6", "qa-runner")]))
    finally:
        harness.cleanup(root)
        server.shutdown()


def d2_asked_once() -> None:
    """D-0014: one word passes S5 AND S6. `go on` is read by CODE (R5: the driver records the pass with
    waiver.py itself, no conductor); S6 then asks nothing. Free words are the conductor's
    (`d2_free_words`). A pass recorded on either stage covers the other. In-process."""
    task = "QA-9"
    root, task_root, env = d2_seed(task, environment=None, pending=True)
    try:
        driver, started, steps, probes = d2_driver(root, env, task)
        eq("D2 asked-once: a story with no stand name asks at S5: exit 3", d2_enter(driver, "S5"), 3)
        ask = s0_question(task_root)
        check_in("D2 asked-once: it says no stand has been chosen", "no stand has been chosen for this story yet", ask)
        check_in("D2 asked-once: and offers the configured stands by name", "`Local`, `Staging`", ask)
        check_in("D2 asked-once: and `go on`", "`go on` — go on without a stand", ask)
        check_not_in("D2 asked-once: `retry` is not offered when there is no stand to bring up", "`retry`", ask)
        eq("D2 asked-once: the question obeys human-questions.md", rules_broken(ask), [])
        eq("D2 asked-once: no probe for a story with no name", probes, [])
        driver, started, steps, probes = d2_driver(root, env, task, answer=d2_answer(root, "go on"))
        eq("D2(R5) `go on` is recorded by code and S5 goes on: exit 0", d2_enter(driver, "S5"), 0)
        eq("D2(R5) NO conductor was called for it", d2_conductor_calls(root), [])
        overrides = s0_pipeline(task_root).get("stage_overrides") or []
        check("D2(R5) the pass is an override of S5 on the block, with their words",
              any(o.get("stage") == "S5" and o.get("match") == D2_ASKED_ONCE and o.get("decision") == "go on" for o in overrides), str(overrides))
        check("D2(R5) and a human_answer in the journal", any(e.get("event") == "human_answer" and "S5 (go on): go on" in str(e.get("notes")) for e in s0_journal(root)))
        eq("D2 asked-once: S5 started its roles without a confirmed stand", started, [("S5", "qa-automator"), ("S5", "qa-code-critic")])
        eq("D2 asked-once: the question flag is gone", "stand_question" in s0_state(task_root), False)
        # S6: the same word covers it - NO second question
        driver, started, steps, probes = d2_driver(root, env, task)
        eq("D2 asked-once: S6 does not ask again for the same story: exit 0", d2_enter(driver, "S6"), 0)
        eq("D2 asked-once: and its runner started", started, [("S6", "qa-runner")])
        eq("D2 asked-once: no question is open", s0_state(task_root).get("asked"), {})
    finally:
        harness.cleanup(root)

    # `go on` however it is typed: case, spaces, a full stop, backticks, a BOM - and when NO stand is
    # recorded (the door is offered there too)
    for label, words, stands in (("case, spaces, a full stop", "  Go On.  ", ("Local", "Staging")),
                                 ("BOM and backticks", BOM + "`go on`", ("Local", "Staging")),
                                 ("no stand recorded", "go on", ())):
        root, task_root, env = d2_seed(task, environment=None, pending=True, stands=stands)
        try:
            driver, started, steps, probes = d2_driver(root, env, task)
            d2_enter(driver, "S5")
            check_in(f"D2(R5) `go on` is offered ({label})", "`go on` — go on without a stand", s0_question(task_root))
            driver, started, steps, probes = d2_driver(root, env, task, answer=d2_answer(root, words))
            eq(f"D2(R5) `go on` ({label}) passes: exit 0", d2_enter(driver, "S5"), 0)
            eq(f"D2(R5) ({label}) with no conductor", d2_conductor_calls(root), [])
            overrides = s0_pipeline(task_root).get("stage_overrides") or []
            check(f"D2(R5) ({label}) the decision keeps their words, BOM out",
                  any(o.get("decision") == words.replace(BOM, "").strip() for o in overrides), str(overrides))
        finally:
            harness.cleanup(root)

    # (d) an override of the block, on either stage, passes both - and needs no probe
    for owner, other in (("S5", "S6"), ("S6", "S5")):
        root, task_root, env = d2_seed(task, environment="Local", pending=True)
        try:
            d2_pipeline(task_root, stage_overrides=[{"stage": owner, "match": D2_ASKED_ONCE, "decision": "go on without it",
                                                     "at": "2026-09-29T10:00:00+00:00", "by": "human"}])
            for stage in ("S5", "S6"):
                driver, started, steps, probes = d2_driver(root, env, task)
                eq(f"D2(d) an override recorded at {owner} passes {stage} without a question: exit 0", d2_enter(driver, stage), 0)
                check(f"D2(d) and {stage} started its role", bool(started), str(started))
                eq("D2(d) and did not probe the stand", probes, [])
        finally:
            harness.cleanup(root)
    # a revoked pass is history: the stand is asked about again (FR-40's way out)
    root, task_root, env = d2_seed(task, environment="Local", pending=True)
    try:
        d2_pipeline(task_root, stage_overrides=[{"stage": "S5", "match": D2_ASKED_ONCE, "decision": "go on",
                                                 "at": "2026-09-29T10:00:00+00:00", "by": "human",
                                                 "revoked_at": "2026-09-29T11:00:00+00:00"}])
        driver, started, steps, probes = d2_driver(root, env, task)
        eq("D2(d) a revoked pass no longer passes: S5 asks again", (d2_enter(driver, "S5"), started), (3, []))
    finally:
        harness.cleanup(root)


def d2_free_words() -> None:
    """Words that are no stand name, not `retry`, not `go on` are the person's own: they go to the
    conductor, whose prompt names ONE command to record them if they mean it. In-process."""
    task = "QA-9"
    root, task_root, env = d2_seed(task, environment=None, pending=True)
    try:
        driver, started, steps, probes = d2_driver(root, env, task)
        eq("D2 words: setup - S5 asks", d2_enter(driver, "S5"), 3)
        words = "no stand for now, write the tests and we run them later"
        set_control(root, {"conductor": {"action": "continue", "did": "recorded the person's word", "text": "Recorded.",
                                         "run": [d2_waiver(task, "S5", words)]}})
        driver, started, steps, probes = d2_driver(root, env, task, answer=d2_answer(root, words))
        eq("D2 words: their words are recorded and S5 goes on: exit 0", d2_enter(driver, "S5"), 0)
        calls = d2_conductor_calls(root)
        eq("D2 words: the conductor was called once, for the words", len(calls), 1)
        prompt = calls[0]["prompt"]
        check_in("D2 words: its prompt names the one command", "waiver.py", prompt)
        check_in("D2 words: with the block", '--block "stand not confirmed"', prompt)
        check_in("D2 words: and the stage", "S5", prompt)
        check_in("D2 words: and carries the words whole", words, prompt)
        check_in("D2 words: and tells it to run nothing when the words do not say so", "run nothing", prompt)
        overrides = s0_pipeline(task_root).get("stage_overrides") or []
        check("D2 words: the pass is recorded as an override of S5, with their words",
              any(o.get("stage") == "S5" and o.get("match") == D2_ASKED_ONCE and o.get("decision") == words for o in overrides), str(overrides))
        eq("D2 words: S5 started its roles without a confirmed stand", started, [("S5", "qa-automator"), ("S5", "qa-code-critic")])
        driver, started, steps, probes = d2_driver(root, env, task)
        eq("D2 words: S6 does not ask again: exit 0", (d2_enter(driver, "S6"), started), (0, [("S6", "qa-runner")]))
        eq("D2 words: still one conductor call in all", len(d2_conductor_calls(root)), 1)
    finally:
        harness.cleanup(root)


def main() -> None:
    run_scenarios([], [
        d2_stand_question,
        d2_asked_once,
        d2_free_words,
    ])
    harness.finish("test_story_run_stand")


if __name__ == "__main__":
    main()
