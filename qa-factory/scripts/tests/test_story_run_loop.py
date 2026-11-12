"""The story runner's loop, first part: the dry run, the prose resume and the form a role must fill. Moved out of
test_story_run.py unchanged; the shared scaffolding is `story_run_common`. Continued in test_story_run_loop_b.py
(cut by measured seconds, each file at most 75 s, t-104).

Also here (legacy-2406 W2, M26): a `relaunch` is the controller's own packet, dispatched as it stands - and, on a stand
stage, only after the stand and build checks (upstream's rule for a role started on the stand).
"""
import contextlib
import io
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import check, check_eq, check_in  # noqa: E402
from story_run_common import (  # noqa: E402
    run_scenarios,
    GOOD_MANIFEST, SCOUT_DIGEST, driver_for, eq, jsonl, run_driver, seed, set_control, stub_calls,
)


def loop_dry_run_fresh() -> None:
    task = "QA-9"
    # --- dry-run: fresh project, then seeded --------------------------------------------------
    fresh = harness.temp_project("qa-story-run-fresh-")
    try:
        env = dict(os.environ, CLAUDE_PROJECT_DIR=str(fresh), STORY_RUN_CLAUDE=str(fresh / "none.py"))
        out = run_driver(fresh, env, "--task", task, "--dry-run")
        check_eq("dry-run on a fresh project exits 0", out.returncode, 0)
        check_in("and says S0 would run by code", "S0 by code", out.stdout)
        check("and dispatches nothing", not (fresh / "qa-factory/artifacts" / task).exists())
    finally:
        harness.cleanup(fresh)


def loop_prose_resume() -> None:
    task = "QA-9"
    # --- prose instead of the form: one resume ------------------------------------------------
    root, task_root, env = seed(task)
    try:
        set_control(root, {"roles": {"qa-scout": {
            "files": {"work/context-manifest.json": json.dumps(GOOD_MANIFEST).replace("{task}", task),
                      "work/context-bundle.json": "{}"},
            "result": "I have collected the sources and everything went well. The manifest is written."}},
            "resume": {"result": SCOUT_DIGEST.replace("{task}", task)}})
        out = run_driver(root, env, "--task", task, "--max-boundaries", "1")
        eq("the prose handoff still ends in a done stage", out.returncode, 0, out.stdout[-1200:] + out.stderr[-600:])
        calls = stub_calls(root)
        check_eq("one role call and one resume", [c["kind"] for c in calls], ["role", "resume"])
        check_in("the resume asks for the form", "print your handoff in the exact form", calls[1]["prompt"])
        check_eq("the resume goes to the same session", calls[1]["resume"], "sess-S1-qa-scout-1")
        pipeline = json.loads((task_root / "pipeline.json").read_text(encoding="utf-8"))
        check_eq("S1 is done on the resumed digest", pipeline["stages"]["S1"]["status"], "done")
        runs = jsonl(task_root / "state/driver-runs.jsonl")
        check_eq("driver-runs.jsonl marks the resume", [r["resumed"] for r in runs], [False, True])
    finally:
        harness.cleanup(root)


def loop_form_is_required() -> None:
    task = "QA-9"
    # --- the form is required, and answering it is the ROLE's job ------------------------------
    root, task_root, env = seed(task)
    try:
        # the default again: the form IS the handover (seed() turns it off for the loop tests)
        config = root / "qa-factory" / "config.json"
        cfg = json.loads(config.read_text(encoding="utf-8"))
        cfg.pop("handoffs", None)
        config.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        set_control(root, {"roles": {"qa-scout": {
            "files": {"work/context-manifest.json": json.dumps(GOOD_MANIFEST).replace("{task}", task),
                      "work/context-bundle.json": "{}"},
            "result": SCOUT_DIGEST.replace("{task}", task)}},
            "resume": {"result": SCOUT_DIGEST.replace("{task}", task)},
            "conductor": {"action": "stop"}})
        run_driver(root, env, "--task", task, "--max-boundaries", "1")
        calls = stub_calls(root)
        kinds = [c["kind"] for c in calls]
        check_eq("a digest with no form resumes the ROLE, and does it first",
                 kinds[:2], ["role", "resume"])
        check_in("the resume names the form the role must fill", "handover form", calls[1]["prompt"])
        check_in("and where it is", "work/handoffs/S1-qa-scout-1.yaml", calls[1]["prompt"])
        check_in("and that its lines are not about the work", "the only ones your role may write",
                 calls[1]["prompt"])
        check_in("and the way out that does not reach the person", "`blocked`", calls[1]["prompt"])
        form = task_root / "work" / "handoffs" / "S1-qa-scout-1.yaml"
        check("what code could derive is written into the form before the role is asked",
              "derived:" in form.read_text(encoding="utf-8"), form.read_text(encoding="utf-8")[-200:])
        check("a role that ignores it twice reaches the conductor, never the person",
              "conductor" in kinds, str(kinds))
        check_eq("and the stage does not close on a handover nobody wrote",
                 json.loads((task_root / "pipeline.json").read_text(encoding="utf-8"))
                 ["stages"]["S1"]["status"], "running")
    finally:
        harness.cleanup(root)


# --- a relaunch is the controller's own packet, dispatched as it stands ---------------------------
# `relaunch` used to run `story_step start`, a NEW dispatch built from the stage and the scope:
# `relaunch_of`, `retry_reason`, the pinned case versions, the repair cause, `rework_of`
# and the mandatory `reason` of the dispatch that never reached an agent were all lost.

def never_started_action(root, task_root, task, **fields) -> tuple:
    """An S1 dispatch that never reached an agent, closed by the liveness repair, and the action
    `next` answers with: (controller, action). `fields` ride on the original request."""
    import hooklib
    import time
    import test_dispatch_liveness as LIFE
    from controller import Controller
    config = root / "qa-factory" / "config.json"
    cfg = json.loads(config.read_text(encoding="utf-8"))
    cfg["dispatch"] = {"never_started_after_s": 0.01}
    config.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    controller = Controller(task_root)
    controller.apply("dispatch", {"id": "S1-qa-scout-1", "stage": "S1", "role": "qa-scout",
                                  "scope": [], "input_hash": "sources-1", "budget": {},
                                  "known_paths": {"root": str(task_root), "project_root": str(root)},
                                  "idempotency_key": "dispatch:S1-qa-scout-1", **fields})
    saved = (hooklib.story_subagent_transcripts, hooklib.subagent_meta)
    LIFE.fake_hooklib([LIFE.transcript(root, "other", "S5-qa-automator-9", role="qa-automator",
                                       ticket=task, age=30)])
    time.sleep(0.05)
    try:
        return controller, Controller(task_root).next_action()
    finally:
        hooklib.story_subagent_transcripts, hooklib.subagent_meta = saved


def spied(driver) -> list:
    """Every factory script the driver runs, as (script, argv strings); the real script still runs."""
    calls = []
    real = driver.py

    def spy(script, *args, **kwargs):
        calls.append((script, tuple(str(a) for a in args)))
        return real(script, *args, **kwargs)
    driver.py = spy
    return calls


def starts(calls) -> list:
    return [c for c in calls if c[0] == "story_step.py" and c[1][:1] == ("start",)]


def loop_relaunch_is_the_controllers_packet() -> None:
    import story_run
    from controller import Controller
    task = "QA-9"
    original = {"purpose": "repair_verify", "rework_of": "S1-qa-scout-0",
                "reason": "the tracker did not answer", "repair_cause": "environment",
                "case_version_links": [{"case_id": "TC-1", "version": "cv_original"}],
                "limits": {"requests": 40}}
    scout_roles = {"roles": {"qa-scout": {
        "files": {"work/context-manifest.json": json.dumps(GOOD_MANIFEST).replace("{task}", task),
                  "work/context-bundle.json": "{}"},
        "result": SCOUT_DIGEST.replace("{task}", task)}}}

    root, task_root, env = seed(task)
    try:
        controller, action = never_started_action(root, task_root, task, **original)
        packet = action.get("dispatch_request") or {}
        check_eq("the controller offers a relaunch with its packet", action.get("action"), "relaunch")
        closed = (Controller(task_root).state().get("dispatches") or {}).get("S1-qa-scout-1") or {}
        check_eq("the packet's known_paths are the record's, portable and stamped by THIS package",
                 packet.get("known_paths"), Controller._stamped_paths(closed.get("known_paths")))
        driver = driver_for(root, env, task)
        calls = spied(driver)
        # The role itself is not run here: a repair round of an S1 scout is a fixture of the
        # CONTRACT (the stage's own closing rule would refuse its finish), and what is proved is
        # which dispatch the driver hands to `run_role` and how. The plain relaunch below runs
        # the whole way through the stub.
        ran = []
        driver.run_role = lambda stage, role, **kw: ran.append((stage, role, kw))
        driver.dispatch_action(action)
        record = (json.loads((task_root / "state/controller.json").read_text(encoding="utf-8"))
                  .get("dispatches") or {}).get(packet.get("id")) or {}
        check_eq("the driver dispatched the packet: the new record names the closed one",
                 record.get("relaunch_of"), "S1-qa-scout-1")
        for key in ("case_version_links", "repair_cause", "rework_of", "reason", "purpose", "limits"):
            check_eq(f"and its {key} is the packet's", record.get(key), packet.get(key))
        check_eq("with the binding of the original request",
                 {key: record.get("request_binding", {}).get(key) for key in original},
                 original)
        check_eq("no fresh `story_step start` was made for it", starts(calls), [])
        check_eq("the packet went through the controller's dispatch operation, once",
                 len([c for c in calls if c[0] == "controller.py" and c[1][2:4] == ("--operation", "dispatch")]),
                 1)
        check_eq("the role is run for THAT dispatch, as a registered one (never a fresh start)",
                 [(s, r, (kw.get("rework") or {}).get("id"), (kw.get("rework") or {}).get("reason"),
                   kw.get("complete", "unset")) for s, r, kw in ran],
                 [("S1", "qa-scout", packet.get("id"), "the tracker did not answer", False)])
    finally:
        harness.cleanup(root)

    # An older controller state: the action carries no packet. That is today's behaviour - a
    # fresh dispatch - and the driver says out loud that the lineage could not be carried.
    root, task_root, env = seed(task)
    try:
        controller, action = never_started_action(root, task_root, task, **original)
        action.pop("dispatch_request")
        driver = driver_for(root, env, task)
        calls = spied(driver)
        set_control(root, scout_roles)
        said = io.StringIO()
        with contextlib.redirect_stdout(said):
            driver.dispatch_action(action)
        check_in("the driver says the lineage could not be carried", "lineage", said.getvalue())
        check_in("and why", "carries no dispatch_request", said.getvalue())
        check_eq("a fresh start is what ran", len(starts(calls)), 1)
        fresh = (json.loads((task_root / "state/controller.json").read_text(encoding="utf-8"))
                 ["dispatches"]).get("S1-qa-scout-2") or {}
        check("and its record carries no relaunch lineage",
              fresh and not fresh.get("relaunch_of") and not fresh.get("reason"), str(fresh)[:300])
    finally:
        harness.cleanup(root)

    # The controller refuses the packet: that refusal is the driver's own, with no fresh start
    # behind it - the same work with the contract thrown away.
    root, task_root, env = seed(task)
    try:
        controller, action = never_started_action(root, task_root, task, **original)
        refused_action = dict(action, dispatch_request=dict(action["dispatch_request"],
                                                            relaunch_of="S1-qa-scout-99"))
        driver = driver_for(root, env, task)
        calls = spied(driver)
        set_control(root, scout_roles)
        before = sorted((json.loads((task_root / "state/controller.json").read_text(encoding="utf-8"))
                         ["dispatches"]))
        try:
            driver.dispatch_action(refused_action)
            check("a refused packet reaches the driver's refusal path", False)
        except story_run.Refusal as refusal:
            check_in("as a controller refusal that names what was refused", "S1-qa-scout-99", refusal.text)
            check_in("with the controller's own words", "controller dispatch", refusal.text)
        check_eq("no fresh start was made behind it", starts(calls), [])
        check_eq("no dispatch was recorded", sorted(json.loads(
            (task_root / "state/controller.json").read_text(encoding="utf-8"))["dispatches"]), before)
        check_eq("and no role ran", [c for c in stub_calls(root) if c["kind"] == "role"], [])
    finally:
        harness.cleanup(root)

    # A plain relaunch (an initial dispatch, no repair) is still a start-shaped dispatch: the
    # stage is marked running as `start` did, and the lineage is the packet's.
    root, task_root, env = seed(task)
    try:
        controller, action = never_started_action(root, task_root, task)
        packet = action["dispatch_request"]
        driver = driver_for(root, env, task)
        calls = spied(driver)
        set_control(root, scout_roles)
        driver.dispatch_action(action)
        check_eq("the stage is marked running, as `start` did", [c[1] for c in calls
                 if c[0] == "stage_done.py" and "running" in c[1]][:1],
                 [("--task", task, "--stage", "S1", "--status", "running", "--role", "qa-scout")])
        check_eq("no `story_step start`", starts(calls), [])
        record = (json.loads((task_root / "state/controller.json").read_text(encoding="utf-8"))
                  ["dispatches"][packet["id"]])
        check_eq("the new record names the closed one and why it was repeated",
                 (record.get("relaunch_of"), record.get("retry_reason")),
                 ("S1-qa-scout-1", packet.get("retry_reason")))
        check_eq("and it finished, closing the stage as a first dispatch does", record.get("status"), "accepted")
        roles = [c for c in stub_calls(root) if c["kind"] == "role"]
        check_eq("the role ran once, for THAT dispatch", len(roles), 1)
        check_in("under the packet's id", f"Dispatch: {packet['id']}.", roles[0]["prompt"])
        check_in("with the dispatch it repeats named to it", "S1-qa-scout-1 never reached an agent",
                 roles[0]["prompt"])
    finally:
        harness.cleanup(root)


def loop_relaunch_on_a_stand_stage_checks_the_stand_first() -> None:
    """POSITION INVARIANT (t-428 S8): on S5 and S6 the stand check and the build check come BEFORE the packet is
    dispatched and before the no-packet fallback starts a role. A refusal of either check registers no dispatch,
    runs no `stage_done` and starts no role; a stage that is not a stand stage runs neither check."""
    import story_run
    task = "QA-9"
    root, task_root, env = seed(task)
    packet = {"id": "S5-qa-automator-2", "stage": "S5", "role": "qa-automator", "scope": ["TC-1"],
              "relaunch_of": "S5-qa-automator-1", "reason": "S5-qa-automator-1 never reached an agent"}

    def rig(refuse: str = ""):
        """A driver whose checks, controller, scripts and role are recorded, in one list, in the order they run."""
        driver = driver_for(root, env, task)
        order = []

        def stand_check(stage, kind=""):
            order.append(("stand_check", stage))
            if refuse == "stand":
                raise story_run.Person("environment", "the stand is not confirmed", stage)

        def build_check(stage, kind="", cases=None):
            order.append(("build_check", stage, list(cases or [])))
            if refuse == "build":
                raise story_run.Person("environment", "the build is not there", stage)

        def controller(operation, *args, input_data=None):
            order.append(("controller", operation, (input_data or {}).get("id")))
            return {}

        def py(script, *args, **kwargs):
            order.append((script,))
            return 0, ""
        driver.stand_check, driver.build_check, driver.controller, driver.py = stand_check, build_check, controller, py
        driver.controller_state = lambda: {"dispatches": {}}
        driver.completion_for = lambda *a, **k: None
        driver.run_role = lambda stage, role, **kw: order.append(("run_role", stage, role))
        return driver, order

    try:
        for stage, role in (("S5", "qa-automator"), ("S6", "qa-runner")):
            request = dict(packet, id=f"{stage}-{role}-2", stage=stage, role=role,
                           relaunch_of=f"{stage}-{role}-1")
            action = {"action": "relaunch", "stage": stage, "role": role, "dispatch_request": request,
                      "closed_dispatch_id": f"{stage}-{role}-1"}
            driver, order = rig()
            with contextlib.redirect_stdout(io.StringIO()):
                driver.dispatch_action(action)
            check_eq(f"{stage}: the stand check and the build check come first, then the dispatch, then the role",
                     [step[:2] if step[0] != "build_check" else step[:2] + (step[2],) for step in order],
                     [("stand_check", stage), ("build_check", stage, ["TC-1"]),
                      ("controller", "dispatch"), ("stage_done.py",), ("run_role", stage)])
            check_eq(f"{stage}: the dispatch is the packet's", order[2], ("controller", "dispatch", request["id"]))
            for refused, label in (("stand", "stand check"), ("build", "build check")):
                driver, order = rig(refused)
                try:
                    with contextlib.redirect_stdout(io.StringIO()):
                        driver.dispatch_action(action)
                    stopped = False
                except story_run.Person:
                    stopped = True
                check(f"{stage}: a refused {label} reaches the driver as the person's question", stopped, str(order))
                check_eq(f"{stage}: and nothing was dispatched, recorded or started behind it",
                         [step[0] for step in order if step[0] in ("controller", "stage_done.py", "run_role")], [])

            # no packet: the fallback is a fresh start, and it is a role started on the stand too
            driver, order = rig()
            with contextlib.redirect_stdout(io.StringIO()):
                driver.dispatch_action(dict(action, dispatch_request={}))
            check_eq(f"{stage}: with no packet the checks still come before the fresh start",
                     [step[0] for step in order], ["stand_check", "build_check", "run_role"])
            driver, order = rig("stand")
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    driver.dispatch_action(dict(action, dispatch_request={}))
            except story_run.Person:
                pass
            check_eq(f"{stage}: a refused stand check with no packet starts no role",
                     [step[0] for step in order], ["stand_check"])

        # a stage that is not a stand stage: the packet is dispatched with neither check
        request = dict(packet, id="S1-qa-scout-2", stage="S1", role="qa-scout", relaunch_of="S1-qa-scout-1")
        driver, order = rig()
        with contextlib.redirect_stdout(io.StringIO()):
            driver.dispatch_action({"action": "relaunch", "stage": "S1", "role": "qa-scout",
                                    "dispatch_request": request, "closed_dispatch_id": "S1-qa-scout-1"})
        check_eq("S1: no stand check, no build check", [step[0] for step in order],
                 ["controller", "stage_done.py", "run_role"])
    finally:
        harness.cleanup(root)


def main() -> None:
    run_scenarios([], [
        loop_dry_run_fresh,
        loop_prose_resume,
        loop_form_is_required,
        loop_relaunch_is_the_controllers_packet,
        loop_relaunch_on_a_stand_stage_checks_the_stand_first,
    ])
    harness.finish("test_story_run_loop")


if __name__ == "__main__":
    main()
