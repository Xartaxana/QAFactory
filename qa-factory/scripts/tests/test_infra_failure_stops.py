#!/usr/bin/env python3
"""stops: a part of test_infra_failure.py, split by tools/test_split.py (TD-11c). The shared helpers are in infra_failure_common."""
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import check, check_eq, check_in, check_not_in, finish  # noqa: E402
sys.path.insert(0, str(harness.SCRIPTS))
import story_run_common as T  # noqa: E402
from infra_failure_common import (  # noqa: E402
    AUTH, FILES, LIMIT, LIMIT_NO_RESET, MALFORMED, TASK, calls, control, done, entry, infra_of, install,
    project_of, prompt_for, raised, scenario, state_of,
)


# --- K2, K3, K7: a stop and a rerun ---------------------------------------------------------------
def k2_auth_stops_the_driver():
    root, task_root, env = T.seed(TASK)
    try:
        install(root, control([entry(AUTH)]))
        out = T.run_driver(root, env, "--task", TASK, "--max-boundaries", "1")
        T.eq("K2: exit 5", out.returncode, 5, out.stdout[-1200:] + out.stderr[-600:])
        check_in("K2: stdout says the login is missing", "logged in", out.stdout)
        check_in("K2: and gives the command to go on", "story_run.py", out.stdout)
        check_in("K2: with the task and the project", f"--task {TASK} --project", out.stdout)
        check_not_in("K2: no answer file in a command that has nothing to answer", "--answer", out.stdout)
        check("K2: no question file for the person", not (task_root / "state/driver-question.md").exists())
        check_eq("K2: the ordinary stub was never reached: no conductor call, no role call", T.stub_calls(root), [])
        check_eq("K2: exactly one claude call", len(calls(root)), 1)
        check("K2: no conductor row", not (task_root / "state/conductor.jsonl").exists())
        check("K2: no saved role result", not (task_root / "state/driver-runs/S1-qa-scout-1.json").exists())
        held = state_of(task_root)
        record = (held.get("interrupted") or {}).get("S1-qa-scout-1") or {}
        check_eq("K2: the dispatch is recorded as interrupted by auth", (record.get("kind"), record.get("rule")),
                 ("auth", "not_logged_in"))
        check_eq("K2: a one-turn call did no work", record.get("worked"), False)
        check_eq("K2: the record names the call, the stage, the role and the dispatch",
                 (record.get("call"), record.get("stage"), record.get("role"), record.get("dispatch")),
                 ("role", "S1", "qa-scout", "S1-qa-scout-1"))
        check("K2: and no session is stored for it", "S1-qa-scout-1" not in (held.get("sessions") or {}))
        runs = T.jsonl(task_root / "state/driver-runs.jsonl")
        check_eq("K2: one journal line for the one invocation", len(runs), 1)
        check_eq("K2: it carries subtype, infra, rule and retry",
                 (runs[0].get("subtype"), runs[0].get("infra"), runs[0].get("infra_rule"), runs[0].get("retry")),
                 ("success", "auth", "not_logged_in", 0))
        check_eq("K2: the dispatch is still the controller's (running), not dropped",
                 json.loads((task_root / "state/controller.json").read_text(encoding="utf-8"))["dispatches"]["S1-qa-scout-1"]["status"],
                 "running")

        # K7 (after K2): the rerun finds the interrupted record and starts the role fresh, with the note
        install(root, control([entry(AUTH)]))
        out = T.run_driver(root, env, "--task", TASK, "--max-boundaries", "1")
        T.eq("K7: the rerun after an auth stop finishes the stage", out.returncode, 0, out.stdout[-1500:] + out.stderr[-800:])
        log = calls(root)
        check_eq("K7: it made one more claude call", len(log), 2)
        second = log[1]
        check_not_in("K7: a session that did nothing is not resumed", "--resume", " ".join(second["argv"]))
        check_in("K7: the fresh prompt says this is not a rework", "Not a rework: continue this dispatch", second["prompt"])
        check_in("K7: and carries the note", "cut by an infrastructure failure", second["prompt"])
        check_in("K7: and the original dispatch prompt", "Dispatch: S1-qa-scout-1.", second["prompt"])
        check_eq("K7: S1 is done", json.loads((task_root / "pipeline.json").read_text(encoding="utf-8"))["stages"]["S1"]["status"], "done")
        check_eq("K7: the interrupted record is cleared by the successful call", state_of(task_root).get("interrupted"), {})
    finally:
        done(root)


def k3_limit_worked_then_continued():
    root, task_root, env = T.seed(TASK)
    try:
        install(root, control([entry(LIMIT, turns=15, session="sess-limit", cost=8.67, files=FILES)]))
        out = T.run_driver(root, env, "--task", TASK, "--max-boundaries", "1")
        T.eq("K3: exit 5", out.returncode, 5, out.stdout[-1200:])
        check_in("K3: the reset is quoted as the service wrote it", "2am (Europe/Madrid)", out.stdout)
        record = (state_of(task_root).get("interrupted") or {}).get("S1-qa-scout-1") or {}
        check_eq("K3: fifteen turns is work: worked, with its session", (record.get("worked"), record.get("session_id"), record.get("num_turns")),
                 (True, "sess-limit", 15))
        check_eq("K3: and the reset is in the record", record.get("reset"), "2am (Europe/Madrid)")

        # K7 (after K3): the rerun RESUMES that session with the note alone
        install(root, control())
        (root / "infra-count.txt").unlink()
        out = T.run_driver(root, env, "--task", TASK, "--max-boundaries", "1")
        T.eq("K7: the rerun after a limit stop finishes the stage", out.returncode, 0, out.stdout[-1500:] + out.stderr[-800:])
        second = calls(root)[-1]
        check_eq("K7: it resumes the session that worked", second["argv"][second["argv"].index("--resume") + 1], "sess-limit")
        check_in("K7: with the note", "cut by an infrastructure failure", second["prompt"])
        check_in("K7: which lists what the role had written", "work/context-manifest.json (", second["prompt"])
        check_not_in("K7: and is not the dispatch prompt again", "Dispatch:", second["prompt"])
        check_in("K7: it ends in the handoff form", "· ok|concerns|halt|impossible", second["prompt"])
        check_eq("K7: the record is cleared", state_of(task_root).get("interrupted"), {})
        check_eq("K7: the session is stored now", state_of(task_root)["sessions"].get("S1-qa-scout-1"), "sess-limit")
    finally:
        done(root)


def k3_a_second_stop_keeps_the_session_that_worked():
    """A rerun resumes the worked session and the login fails at one turn: the record keeps that
    session (worked, its turns) and refreshes only what failed; the next rerun resumes it."""
    queue = [entry(LIMIT, turns=15, session="sess-limit"), entry(AUTH, turns=1, session="sess-limit")]
    root, task_root, env, driver, delays = project_of(control(queue))
    try:
        args = ("role", prompt_for(task_root))
        kw = dict(role="qa-scout", dispatch="S1-qa-scout-1", stage="S1")
        stop, _ = raised(driver, *args, **kw)
        check_eq("K3b: the first stop is the limit, worked", (infra_of(stop), driver.state["interrupted"]["S1-qa-scout-1"]["worked"]), ("limit", True))
        stop, _ = raised(driver, *args, **kw)
        record = driver.state["interrupted"]["S1-qa-scout-1"]
        check_eq("K3b: the rerun resumed the recorded session and met auth", (infra_of(stop), calls(root)[1]["argv"][calls(root)[1]["argv"].index("--resume") + 1]), ("auth", "sess-limit"))
        check_eq("K3b: the record still has the session, worked, and its 15 turns",
                 (record["session_id"], record["worked"], record["num_turns"]), ("sess-limit", True, 15))
        check_eq("K3b: only what failed is refreshed", (record["kind"], record["rule"]), ("auth", "not_logged_in"))
        stop, result = raised(driver, *args, **kw)
        third = calls(root)[2]
        check_eq("K3b: the next rerun resumes that session", (stop, third["argv"][third["argv"].index("--resume") + 1]), (None, "sess-limit"))
        check_eq("K3b: and the record leaves", driver.state["interrupted"], {})
    finally:
        done(root)
    # a stop of a FRESH session (the record did no work) overwrites, as before
    root, task_root, env, driver, delays = project_of(control([entry(AUTH, turns=1, session="sess-a"), entry(AUTH, turns=1, session="sess-b")]))
    try:
        raised(driver, "role", prompt_for(task_root), role="qa-scout", dispatch="S1-qa-scout-1", stage="S1")
        raised(driver, "role", prompt_for(task_root), role="qa-scout", dispatch="S1-qa-scout-1", stage="S1")
        record = driver.state["interrupted"]["S1-qa-scout-1"]
        check_eq("K3b: a fresh-session stop overwrites the record", (record["session_id"], record["worked"]), ("sess-b", False))
    finally:
        done(root)


def k5_transient_retries_keep_the_recorded_session():
    """The driver resumed the session that worked (step a); three broken answers at one turn must not
    send the retries to a fresh session or overwrite the record."""
    queue = [entry(MALFORMED, turns=1, session="sess-x") for _ in range(3)]
    root, task_root, env, driver, delays = project_of(control(queue))
    try:
        driver.state["interrupted"]["S1-qa-scout-1"] = {"kind": "limit", "rule": "usage_limit", "session_id": "sess-prior",
                                                        "num_turns": 15, "worked": True, "call": "role"}
        stop, _ = raised(driver, "role", prompt_for(task_root), role="qa-scout", dispatch="S1-qa-scout-1", stage="S1")
        log = calls(root)
        check_eq("K5b: three calls, then the stop", (infra_of(stop), len(log)), ("transient", 3))
        check_eq("K5b: every call resumes the recorded session",
                 [c["argv"][c["argv"].index("--resume") + 1] if "--resume" in c["argv"] else None for c in log], ["sess-prior"] * 3)
        check_not_in("K5b: with the note, never the dispatch prompt", "Dispatch:", log[2]["prompt"])
        record = driver.state["interrupted"]["S1-qa-scout-1"]
        check_eq("K5b: the record keeps the session and that it worked",
                 (record["session_id"], record["worked"], record["num_turns"], record["kind"]), ("sess-prior", True, 15, "transient"))
    finally:
        done(root)


def k3_a_limit_without_a_reset_says_so():
    root, task_root, env, driver, delays = project_of(control([entry(LIMIT_NO_RESET, turns=2, session="sess-l2")]))
    try:
        stop, _ = raised(driver, "role", prompt_for(task_root), role="qa-scout", dispatch="S1-qa-scout-1", stage="S1")
        check_eq("K3: a limit without a reset stops as limit", infra_of(stop), "limit")
        check_in("K3: and says the service named no reset time", "no reset time", stop.reason if stop else "")
        check_eq("K3: two turns count as work", driver.state["interrupted"]["S1-qa-scout-1"]["worked"], True)
        check_eq("K3: a limit is not retried", (delays, len(calls(root))), ([], 1))
    finally:
        done(root)


SCENARIOS = (
    k2_auth_stops_the_driver,
    k3_limit_worked_then_continued,
    k3_a_second_stop_keeps_the_session_that_worked,
    k5_transient_retries_keep_the_recorded_session,
    k3_a_limit_without_a_reset_says_so,
)


# split: runner piece 1
# `test_infra_failure.py k2_auth_stops_the_driver k5_transient_three_times` runs only those (a mutation
# control names the one scenario it targets); with no names, all of them run - the witness is that run.
for _fn in SCENARIOS:
    if not sys.argv[1:] or _fn.__name__ in sys.argv[1:]:
        scenario(_fn)


finish("test_infra_failure_stops")
