#!/usr/bin/env python3
"""texts: a part of test_infra_failure.py, split by tools/test_split.py (TD-11c). The shared helpers are in infra_failure_common."""
import contextlib
import io
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import check, check_eq, check_in, check_not_in, finish  # noqa: E402
sys.path.insert(0, str(harness.SCRIPTS))
import story_run_common as T  # noqa: E402
from infra_failure_common import (  # noqa: E402
    AUTH, DIGEST, FILES, LIMIT, LIMIT_NO_RESET, MALFORMED, S3_SAVED, TASK, calls, control, done, entry,
    infra_of, install, project_of, prompt_for, raised, scenario,
)


# --- K14 ------------------------------------------------------------------------------------------
def k14_the_texts_obey_the_human_rules():
    import human_text
    for label, text, turns, queue_size in (("auth", AUTH, 1, 1), ("limit", LIMIT, 15, 1), ("limit without a reset", LIMIT_NO_RESET, 3, 1),
                                           ("transient", MALFORMED, 1, 3)):
        root, task_root, env, driver, delays = project_of(control([entry(text, turns=turns, session=f"s{i}") for i in range(queue_size)]))
        try:
            stop, _ = raised(driver, "role", prompt_for(task_root), role="qa-scout", dispatch="S1-qa-scout-1", stage="S1")
            message = stop.reason if stop else ""
            check_eq(f"K14: the {label} message breaks no rule of human-questions", human_text.problems(message), [])
            check_in(f"K14: the {label} message ends in a how-to-answer block that gives the command", "## How to answer\nNothing to answer:", message)
            body = message.split("\n## How to answer")[0]
            for shape in ("story_run", ".py", "exit 5", "S1-qa-scout-1", "--"):
                check_not_in(f"K14: the {label} body carries no `{shape}`", shape, body)
            check_in(f"K14: the {label} body says nothing about the story is wrong or lost", "nothing", body.lower())
            if label == "auth":
                check_in("K14: auth lists what was taken from the child and the door to keep it", "driver.child_env.keep", message)
        finally:
            done(root)


# --- the command, the note, the flags, the conflicts ------------------------------------------------
def command_and_flags():
    root, task_root, env, driver, delays = project_of(control())
    try:
        base = f'python "{driver.scripts / "story_run.py"}" --task {TASK} --project "{driver.project}"'
        driver.flags.max_boundaries = 80      # driver_for's own default is 10, which IS a non-default
        check_eq("cmd: the default command is the task and the project only", driver.continue_command(), base)
        f = driver.flags
        f.plugin_dir, f.model, f.until, f.mr, f.branch, f.commit = "C:/a b/plugin", "opus", "gate_A", "12", "br x", "abc"
        f.ungrounded, f.ticket_file, f.env, f.branch_suffix, f.max_boundaries, f.no_trace = True, "t k.md", "local", "s 1", "3", True
        got = driver.continue_command()
        for part in ('--plugin-dir "C:/a b/plugin"', "--model opus", "--until gate_A", "--mr 12", '--branch "br x"', "--commit abc",
                     "--ungrounded", '--ticket-file "t k.md"', "--env local", '--branch-suffix "s 1"', "--max-boundaries 3", "--no-trace"):
            check_in(f"cmd: every non-default flag is repeated: {part}", part, got)
        f.model, f.until, f.max_boundaries = "sonnet", "end", 80
        check_not_in("cmd: the defaults are not", "--model", driver.continue_command())
        check_not_in("cmd: max-boundaries 80 is not", "--max-boundaries", driver.continue_command())
        f.answer = str(root / "answer.md")
        driver.state["asked"] = {}
        check_not_in("cmd: an answer already taken is not offered again", "--answer", driver.continue_command())
        driver.state["asked"] = {"kind": "halt", "stage": "S1", "dispatch": "S1-qa-scout-1"}
        check_in("cmd: during take_answer (the question still open) the answer file is repeated", "--answer", driver.continue_command())
        f.answer = None
        check_not_in("cmd: an open question with no answer file given is not", "--answer", driver.continue_command())
    finally:
        done(root)


def k9b_a_stop_during_take_answer_repeats_the_answer():
    root, task_root, env = T.seed(TASK)
    try:
        install(root, control([entry(AUTH)]))
        (task_root / "state").mkdir(parents=True, exist_ok=True)
        (task_root / "state/driver-question.md").write_text("# Driver question\nkind: halt\nstage: S1\ndispatch: S1-qa-scout-1\n\nQuestion?\n", encoding="utf-8")
        (task_root / "state/driver-state.json").write_text(json.dumps({"asked": {"kind": "halt", "stage": "S1", "dispatch": "S1-qa-scout-1"}}), encoding="utf-8")
        answer = root / "answer.md"
        answer.write_text("go on please", encoding="utf-8")
        out = T.run_driver(root, env, "--task", TASK, "--answer", str(answer), "--max-boundaries", "1")
        T.eq("take_answer: a conductor call that meets auth while the answer is taken stops with 5", out.returncode, 5, out.stdout[-1200:] + out.stderr[-500:])
        check_in("take_answer: and the command carries the answer file", f"--answer {answer}", out.stdout)
    finally:
        done(root)


def the_continuation_note():
    root, task_root, env, driver, delays = project_of(control())
    try:
        check_eq("note: no outputs and no record: no note for a fresh role call",
                 driver.continuation_note("role", "qa-scout", "S1", "S1-qa-scout-1", alone=False, known=False), "")
        generic = driver.continuation_note("conductor", "", "S1", "", alone=True, known=True)
        check_in("note: a call that is not a role's gets the generic note", "cut by an infrastructure failure, not by anything you did", generic)
        check_not_in("note: without a list of outputs", "Continue them", generic)
        for rel, content in FILES.items():
            (task_root / rel).parent.mkdir(parents=True, exist_ok=True)
            (task_root / rel).write_text(content, encoding="utf-8")
        form = task_root / "work/handoffs/S1-qa-scout-1.yaml"
        form.parent.mkdir(parents=True, exist_ok=True)
        form.write_text("header: {}\n", encoding="utf-8")
        note = driver.continuation_note("role", "qa-scout", "S1", "S1-qa-scout-1", alone=True, known=True)
        check_in("note: it says it is the same dispatch with the same inputs", "same dispatch with the same inputs", note)
        check_in("note: it lists the role's own outputs with their size", f"work/context-manifest.json ({len(FILES['work/context-manifest.json'].encode())} bytes)", note)
        check_not_in("note: and not what code writes (the bundle)", "context-bundle.json (", note)
        check_in("note: and the handover form", "work/handoffs/S1-qa-scout-1.yaml", note)
        check_in("note: it names the doors of a role that has Bash", "artifact_supersede.py", note)
        check_in("note: and the plan check", "planning_contract.py --kind plan", note)
        check_in("note: and ends in the handoff form", "· ok|concerns|halt|impossible", note)
        (task_root / "work/test-plan.json").write_text(json.dumps({"rows": [{"id": "TS-1"}]}), encoding="utf-8")
        strategist = driver.continuation_note("role", "qa-test-strategist", "S3", "S3-qa-test-strategist-1", alone=True, known=True)
        check_in("note: the strategist's plan is listed", "work/test-plan.json (", strategist)
        check_not_in("note: a role with no Bash is not sent to a script it cannot run (FR-2)", "artifact_supersede.py", strategist)
        check_in("note: it is sent to the point editor instead", "Edit", strategist)
        (task_root / "work/test-cases").mkdir(parents=True, exist_ok=True)
        (task_root / "work/test-cases/TC-1.md").write_text("x", encoding="utf-8")
        (task_root / "work/test-cases/TC-2.md").write_text("y", encoding="utf-8")
        designer = driver.continuation_note("role", "qa-case-designer", "S4", "S4-qa-case-designer-1", alone=True, known=True)
        check_in("note: a directory is its file count", "work/test-cases/ (2 files)", designer)
        (driver.project / "bugs").mkdir(exist_ok=True)
        (driver.project / "bugs/b1.md").write_text("z", encoding="utf-8")
        reporter = driver.continuation_note("role", "qa-bug-reporter", "S8", "S8-qa-bug-reporter-1", alone=True, known=True)
        check_in("note: `project:` resolves against the project root", "project:bugs/ (1 file)", reporter)
    finally:
        done(root)


def conflicts():
    root, task_root, env, driver, delays = project_of(control())
    try:
        driver.state["interrupted"]["S1-qa-scout-1"] = {"kind": "limit", "rule": "usage_limit", "session_id": "sess-prior",
                                                        "num_turns": 15, "worked": True, "call": "role"}
        stop, result = raised(driver, "role", prompt_for(task_root), role="qa-scout", dispatch="S1-qa-scout-1", stage="S1",
                              resume="sess-explicit")
        first = calls(root)[0]
        check_eq("conflict: an explicit resume wins over the interrupted record",
                 first["argv"][first["argv"].index("--resume") + 1], "sess-explicit")
        check_in("conflict: and the note is appended to the caller's prompt", "cut by an infrastructure failure", first["prompt"])
        check_in("conflict: after the caller's own words", "Do the work.", first["prompt"])
    finally:
        done(root)

    root, task_root, env, driver, delays = project_of(control())
    try:
        started = harness.run_script("story_step.py", "start", "--task", TASK, "--stage", "S1", "--role", "qa-scout", cwd=root,
                                     env=dict(env, QA_FACTORY_RUN_MODE="driver"))
        check_eq("conflict: a dispatch to hold both", started.returncode, 0)
        seen = []
        driver.resume_role = lambda *a, **k: seen.append("resume_role")
        driver.run_role = lambda *a, **k: seen.append("run_role")
        driver.handoff = lambda *a, **k: seen.append("handoff") or "digest"
        driver.finish = lambda *a, **k: seen.append("finish")
        driver.state["interrupted"]["S1-qa-scout-1"] = {"kind": "limit", "worked": True, "session_id": "s", "call": "role"}
        driver.state["pending_words"]["S1-qa-scout-1"] = "the person's words"
        driver.dispatch_action({"action": "wait_existing_job", "dispatch_id": "S1-qa-scout-1"})
        check_eq("conflict: the person's words win over an interrupted record", seen, ["resume_role"])
        driver.state["pending_words"].pop("S1-qa-scout-1")
        saved = task_root / "state/driver-runs/S1-qa-scout-1.json"
        saved.parent.mkdir(parents=True, exist_ok=True)
        saved.write_text(json.dumps({"session_id": "s1", "result": DIGEST, "num_turns": 3, "is_error": False, "exit_code": 0, "stderr": ""}), encoding="utf-8")
        seen.clear()
        driver.dispatch_action({"action": "wait_existing_job", "dispatch_id": "S1-qa-scout-1"})
        check_eq("conflict: a valid saved result wins over an interrupted record", seen, ["handoff", "finish"])
        check("conflict: and the saved result is not set aside", saved.is_file() and not saved.with_name("S1-qa-scout-1.infra.json").exists())
        seen.clear()
        saved.write_text(json.dumps(dict(S3_SAVED)), encoding="utf-8")
        driver.dispatch_action({"action": "wait_existing_job", "dispatch_id": "S1-qa-scout-1"})
        check_eq("conflict: an infrastructure result saved beside a record is set aside and the dispatch continues", seen, ["run_role"])
        check("conflict: as .infra.json", saved.with_name("S1-qa-scout-1.infra.json").is_file() and not saved.exists())
    finally:
        done(root)


def the_data_file_absent_is_one_note():
    import hooklib
    real = hooklib.load_ref_json
    hooklib.load_ref_json = lambda name: {} if name == "driver-infra.json" else real(name)
    root, task_root, env = T.seed(TASK)
    try:
        install(root, control([entry(AUTH)]))
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            driver = T.driver_for(root, env, TASK)
        check_eq("temporal: one printed note that the failures are not recognised", buffer.getvalue().count("infrastructure failures not recognised"), 1)
        driver.sleep = lambda s: None
        check_eq("temporal: the environment is the host's plus UTF-8, nothing removed", (driver.env_removed, driver.claude_env == driver.env), ([], True))
        check_eq("temporal: an old state file gets the key", driver.state.get("interrupted"), {})
        stop, result = raised(driver, "role", prompt_for(task_root), role="qa-scout", dispatch="S1-qa-scout-1", stage="S1")
        check_eq("temporal: a login failure is then today's failure, unclassified", (stop, result["infra"]["kind"]), (None, "unclassified"))
        check_eq("temporal: and journalled as such", T.jsonl(task_root / "state/driver-runs.jsonl")[0]["infra"], "unclassified")
    finally:
        hooklib.load_ref_json = real
        done(root)


def delivery_carries_its_key():
    root, task_root, env, driver, delays = project_of(control([entry(LIMIT, turns=6, session="sess-deliv")]))
    try:
        stop, _ = raised(driver, "conductor", "deliver it", stage="S8", resume_key="S8:delivery")
        check_eq("delivery: a conductor call with a key is remembered", infra_of(stop), "limit")
        record = driver.state["interrupted"].get("S8:delivery") or {}
        check_eq("delivery: under that key, with its session", (record.get("call"), record.get("session_id"), record.get("worked")),
                 ("conductor", "sess-deliv", True))
        install(root, control())
        stop, result = raised(driver, "conductor", "deliver it", stage="S8", resume_key="S8:delivery")
        second = calls(root)[-1]
        check_eq("delivery: the rerun resumes that session", second["argv"][second["argv"].index("--resume") + 1], "sess-deliv")
        check_not_in("delivery: with the note alone, not the delivery prompt again", "deliver it", second["prompt"])
        check_eq("delivery: and the record is cleared", driver.state["interrupted"], {})
    finally:
        done(root)


SCENARIOS = (
    k9b_a_stop_during_take_answer_repeats_the_answer,
    k14_the_texts_obey_the_human_rules,
    command_and_flags,
    the_continuation_note,
    conflicts,
    the_data_file_absent_is_one_note,
    delivery_carries_its_key,
)


# split: runner piece 1
# `test_infra_failure.py k2_auth_stops_the_driver k5_transient_three_times` runs only those (a mutation
# control names the one scenario it targets); with no names, all of them run - the witness is that run.
for _fn in SCENARIOS:
    if not sys.argv[1:] or _fn.__name__ in sys.argv[1:]:
        scenario(_fn)


finish("test_infra_failure_texts")
