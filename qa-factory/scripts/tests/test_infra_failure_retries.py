#!/usr/bin/env python3
"""retries: a part of test_infra_failure.py, split by tools/test_split.py (TD-11c). The shared helpers are in infra_failure_common."""
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import check, check_eq, check_in, check_not_in, finish  # noqa: E402
sys.path.insert(0, str(harness.SCRIPTS))
import story_run_common as T  # noqa: E402
from infra_failure_common import (  # noqa: E402
    AUTH, FILES, MALFORMED, S3_SAVED, TASK, calls, control, done, entry, infra_of, install, project_of,
    prompt_for, raised, scenario, state_of,
)


def taken(root):
    path = root / "infra-count.txt"
    return int(path.read_text()) if path.exists() else 0


# --- K4, K5 ---------------------------------------------------------------------------------------
def k4_transient_then_success():
    root, task_root, env, driver, delays = project_of(
        control([entry(MALFORMED, turns=3, session="sess-cut", files=FILES)]), max_boundaries=1)
    try:
        code = driver.run()
        check_eq("K4: the story goes on: exit 0", code, 0)
        check_eq("K4: one sleep of five seconds", delays, [5])
        log = calls(root)
        check_eq("K4: two calls", len(log), 2)
        argv = log[1]["argv"]
        check_eq("K4: the second resumes the session that failed", argv[argv.index("--resume") + 1], "sess-cut")
        check_in("K4: its prompt carries the note", "cut by an infrastructure failure", log[1]["prompt"])
        check_not_in("K4: and is not the dispatch prompt", "Dispatch:", log[1]["prompt"])
        check_eq("K4: S1 is done", json.loads((task_root / "pipeline.json").read_text(encoding="utf-8"))["stages"]["S1"]["status"], "done")
        check_eq("K4: the ordinary stub saw the retry only (a resume), no conductor", [c["kind"] for c in T.stub_calls(root)], ["resume"])
        check("K4: no conductor row", not (task_root / "state/conductor.jsonl").exists())
        runs = T.jsonl(task_root / "state/driver-runs.jsonl")
        check_eq("K4: two journal lines, the retry counted", [(r["infra"], r["retry"], r["resumed"]) for r in runs],
                 [("transient", 0, False), (None, 1, True)])
        check_eq("K4: and the malformed text is nowhere in a refusal or a question",
                 (task_root / "state/driver-question.md").exists(), False)
    finally:
        done(root)


def k5_transient_three_times():
    import story_run
    queue = [entry(MALFORMED, session="sess-a"), entry(MALFORMED, session="sess-b"), entry(MALFORMED, session="sess-c"),
             entry(MALFORMED, session="sess-never")]
    root, task_root, env, driver, delays = project_of(control(queue))
    try:
        stop, _ = raised(driver, "role", prompt_for(task_root), role="qa-scout", dispatch="S1-qa-scout-1", stage="S1")
        check_eq("K5: three broken answers in a row stop the driver as transient", infra_of(stop), "transient")
        check_eq("K5: the exit code is 5", stop.code if stop else None, story_run.EXIT_INFRA)
        check_eq("K5: the waits are 5 and 15 seconds", delays, [5, 15])
        check_eq("K5: exactly three calls - AT the limit", len(calls(root)), 3)
        check_eq("K5: and no fourth - BEYOND it", taken(root), 3)
        runs = T.jsonl(task_root / "state/driver-runs.jsonl")
        check_eq("K5: three journal lines, retry 0, 1, 2", [r["retry"] for r in runs], [0, 1, 2])
        check_in("K5: the message counts the answers", "3 times in a row", stop.reason if stop else "")
        check("K5: no session is stored for the dispatch", "S1-qa-scout-1" not in driver.state["sessions"])
        check_eq("K5: the dispatch is recorded as interrupted", driver.state["interrupted"]["S1-qa-scout-1"]["kind"], "transient")
        check_eq("K5: retries never became conductor calls", driver.conductor_calls, {})
    finally:
        done(root)


def k5_two_retries_then_success_is_at_the_limit():
    queue = [entry(MALFORMED, session="sess-a"), entry(MALFORMED, session="sess-b")]
    root, task_root, env, driver, delays = project_of(control(queue))
    try:
        stop, result = raised(driver, "role", prompt_for(task_root), role="qa-scout", dispatch="S1-qa-scout-1", stage="S1")
        check_eq("K5: two retries and then an answer is not a stop", (stop, bool(result)), (None, True))
        check_eq("K5: with both waits", delays, [5, 15])
        check_eq("K5: on the third call", len(calls(root)), 3)
        check_eq("K5: and the result is the role's own", result["is_error"], False)
    finally:
        done(root)


# --- K6 -------------------------------------------------------------------------------------------
def k6_resume_choice():
    def retry_of(first, **kwargs):
        root, task_root, env, driver, delays = project_of(control([first]))
        try:
            p = prompt_for(task_root)
            stop, result = raised(driver, "role", p, role="qa-scout", dispatch="S1-qa-scout-1", stage="S1", **kwargs)
            log = calls(root)
            return stop, result, log, p, driver
        finally:
            done(root)

    def resumed(log):
        argv = log[1]["argv"]
        return argv[argv.index("--resume") + 1] if "--resume" in argv else None

    stop, result, log, p, _ = retry_of(entry(MALFORMED, turns=1, session="sess-t1"))
    check_eq("K6: one turn: the retry of a first call starts fresh", resumed(log), None)
    check_eq("K6: and with the prompt as it was", log[1]["prompt"], p)
    stop, result, log, p, _ = retry_of(entry(MALFORMED, turns=2, session="sess-t2"))
    check_eq("K6: two turns: the retry resumes that session", resumed(log), "sess-t2")
    check_in("K6: with the note", "cut by an infrastructure failure", log[1]["prompt"])
    first = entry(MALFORMED, session="sess-none")
    first["json"]["num_turns"] = None
    stop, result, log, p, _ = retry_of(first)
    check_eq("K6: an unknown number of turns counts as one: fresh", resumed(log), None)
    stop, result, log, p, _ = retry_of(entry(MALFORMED, turns=5, session=""))
    check_eq("K6: many turns and no session id: fresh", resumed(log), None)
    stop, result, log, p, _ = retry_of(entry(MALFORMED, turns=1, session="sess-lost"), resume="sess-orig")
    check_eq("K6: a handoff-repair call that failed at one turn is retried on the ORIGINAL session", resumed(log), "sess-orig")
    check_eq("K6: with the caller's own prompt", log[1]["prompt"], p)
    stop, result, log, p, _ = retry_of(entry(MALFORMED, turns=9, session="sess-more"), resume="sess-orig")
    check_eq("K6: the same call that did work is retried on the session that worked", resumed(log), "sess-more")

    # a resume the DRIVER chose, and the session is gone: one fresh attempt, then the result as it is
    lost = entry("No conversation found with session ID: sess-prior", turns=1, session="sess-x")
    root, task_root, env, driver, delays = project_of(control([lost]))
    try:
        driver.state["interrupted"]["S1-qa-scout-1"] = {"kind": "limit", "rule": "usage_limit", "session_id": "sess-prior",
                                                        "num_turns": 15, "worked": True, "call": "role"}
        p = prompt_for(task_root)
        stop, result = raised(driver, "role", p, role="qa-scout", dispatch="S1-qa-scout-1", stage="S1")
        log = calls(root)
        check_eq("K6: the first call resumed the recorded session", log[0]["argv"][log[0]["argv"].index("--resume") + 1], "sess-prior")
        check_eq("K6: the lost session is followed by ONE fresh attempt", (len(log), "--resume" in log[1]["argv"]), (2, False))
        check_in("K6: with the original prompt", "Dispatch: S1-qa-scout-1.", log[1]["prompt"])
        check_in("K6: and the note", "cut by an infrastructure failure", log[1]["prompt"])
        check_eq("K6: which succeeded, and the record is cleared", (stop, result["is_error"], driver.state["interrupted"]), (None, False, {}))
    finally:
        done(root)
    root, task_root, env, driver, delays = project_of(control([lost, dict(lost)]))
    try:
        driver.state["interrupted"]["S1-qa-scout-1"] = {"kind": "limit", "rule": "usage_limit", "session_id": "sess-prior",
                                                        "num_turns": 15, "worked": True, "call": "role"}
        stop, result = raised(driver, "role", prompt_for(task_root), role="qa-scout", dispatch="S1-qa-scout-1", stage="S1")
        check_eq("K6: when the fresh attempt fails as well the result comes back as any failure does",
                 (stop, result["is_error"], len(calls(root))), (None, True, 2))
        check_eq("K6: as unclassified", result["infra"]["kind"], "unclassified")
    finally:
        done(root)

    # the boundary of `worked` on the write side
    for turns, session, expected in ((1, "s", False), (2, "s", True), (None, "s", False), (5, "", False)):
        one = entry(AUTH, turns=1, session=session)
        one["json"]["num_turns"] = turns
        root, task_root, env, driver, delays = project_of(control([one]))
        try:
            raised(driver, "role", prompt_for(task_root), role="qa-scout", dispatch="S1-qa-scout-1", stage="S1")
            check_eq(f"K6: an interrupted call of {turns} turns and session {session!r} is worked={expected}",
                     driver.state["interrupted"]["S1-qa-scout-1"]["worked"], expected)
        finally:
            done(root)


# --- K8 -------------------------------------------------------------------------------------------
def k8_a_result_saved_before_this_change():
    root, task_root, env = T.seed(TASK)
    try:
        install(root, control())
        started = harness.run_script("story_step.py", "start", "--task", TASK, "--stage", "S1", "--role", "qa-scout",
                                     cwd=root, env=dict(env, QA_FACTORY_RUN_MODE="driver"))
        check_eq("K8: the dispatch is registered", started.returncode, 0)
        for rel, content in FILES.items():
            path = task_root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        saved = task_root / "state/driver-runs/S1-qa-scout-1.json"
        saved.parent.mkdir(parents=True, exist_ok=True)
        saved.write_text(json.dumps(S3_SAVED), encoding="utf-8")
        check("K8: no `interrupted` key in the state, as an older driver left it",
              "interrupted" not in state_of(task_root))
        out = T.run_driver(root, env, "--task", TASK, "--max-boundaries", "1")
        T.eq("K8: the driver goes on and finishes the stage", out.returncode, 0, out.stdout[-1500:] + out.stderr[-800:])
        aside = task_root / "state/driver-runs/S1-qa-scout-1.infra.json"
        check("K8: the infrastructure result is set aside as .infra.json", aside.is_file())
        check_eq("K8: unchanged", json.loads(aside.read_text(encoding="utf-8")), S3_SAVED)
        log = calls(root)
        argv = log[0]["argv"]
        check_eq("K8: its session is resumed", argv[argv.index("--resume") + 1], S3_SAVED["session_id"])
        check_in("K8: with the note", "cut by an infrastructure failure", log[0]["prompt"])
        conductor = (task_root / "state/conductor.jsonl")
        check("K8: no conductor row mentions the API error",
              not conductor.exists() or "API Error" not in conductor.read_text(encoding="utf-8"))
        check_eq("K8: no question", (task_root / "state/driver-question.md").exists(), False)
        check_eq("K8: S1 is done", json.loads((task_root / "pipeline.json").read_text(encoding="utf-8"))["stages"]["S1"]["status"], "done")
    finally:
        done(root)


SCENARIOS = (
    k4_transient_then_success,
    k5_transient_three_times,
    k5_two_retries_then_success_is_at_the_limit,
    k6_resume_choice,
    k8_a_result_saved_before_this_change,
)


# split: runner piece 1
# `test_infra_failure.py k2_auth_stops_the_driver k5_transient_three_times` runs only those (a mutation
# control names the one scenario it targets); with no names, all of them run - the witness is that run.
for _fn in SCENARIOS:
    if not sys.argv[1:] or _fn.__name__ in sys.argv[1:]:
        scenario(_fn)


finish("test_infra_failure_retries")
