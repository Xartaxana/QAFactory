#!/usr/bin/env python3
"""TR3-14 (spec t-1937 B1, hook readers; AR-13, AR-28): the hooks that guess "the one running dispatch" read the identity.

ERROR DIRECTION under test: a hook may answer "no one" (refuse, or leave the owner guard shut); it must never answer another
window's dispatch. Every case runs the REAL `stage_guard.rule_typed_runner`, `guard_pre_tool.dispatched_role` / `owner_check`
and `subagent_journal.record_return` over a seeded `state/controller.json`; the environment words are set by `envs()` and
always restored.

Keys (the spec's list): run_request_of_second_window_passes, run_request_of_sibling_id_refused,
run_request_no_name_two_active_matched_by_id, dispatched_role_names_own_role,
critic_of_w2_cannot_write_automator_artifact_while_w1_runs, owner_of_named_session_writes, journal_waits_for_busy_lock.
"""
import contextlib
import json
import os
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import SCRIPTS, check, check_eq, check_in, cleanup, finish, mark_project, temp_project  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import dispatch_identity as DI  # noqa: E402
import event_store as ES  # noqa: E402
import guard_pre_tool as G  # noqa: E402
import hooklib  # noqa: E402
import planning_contract as PC  # noqa: E402
import stage_guard as SG  # noqa: E402
import subagent_journal as SJ  # noqa: E402
from event_store import EventStore  # noqa: E402

import test_controller_release as REL  # noqa: E402  (at_s3_rework: a running dispatch to act on)

TICKET = "QA-WI1"
W1, W2, C2 = "S5-qa-automator-1", "S5-qa-automator-2", "S5-qa-code-critic-2"
DETECTOR_ENV, DRIVER_ENV = PC.DETECTOR_DISPATCH_ENV, DI.DRIVER_RUN_ENV


def rec(ident, role="qa-automator", status="running", scope=None):
    return {"id": ident, "stage": "S5", "role": role, "status": status, "scope": scope or []}


@contextlib.contextmanager
def envs(driver=None, detector=None):
    saved = {k: os.environ.get(k) for k in (DETECTOR_ENV, DRIVER_ENV)}
    for key, value in ((DETECTOR_ENV, detector), (DRIVER_ENV, driver)):
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    try:
        yield
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def controller_of(*records):
    return {"dispatches": {r["id"]: r for r in records}}


def run_command(root, dispatch_id, selected):
    request = root / "request.json"
    request.write_text(json.dumps({"dispatch_id": dispatch_id, "selected_instance_ids": selected}), encoding="utf-8")
    return f'python run_suite.py --request "{request}"', {"cwd": str(root)}


def verdict(root, state, dispatch_id, selected):
    command, event = run_command(root, dispatch_id, selected)
    return SG.rule_typed_runner(command, event, "X", state)


def part_typed_runner(root):
    two = controller_of(rec(W1, scope=["TC-1"]), rec(W2, scope=["TC-2"]))
    with envs():
        check_eq("run_request_no_name_two_active_matched_by_id: the second window's own id and scope pass",
                 verdict(root, two, W2, ["TC-2"]), "")
        check_eq("run_request_no_name_two_active_matched_by_id: the first window's own id and scope pass",
                 verdict(root, two, W1, ["TC-1"]), "")
        check_in("run_request_no_name_two_active_matched_by_id: the matched window's scope is the one judged",
                 "exceed the active dispatch scope", verdict(root, two, W2, ["TC-1"]))
        check_in("run_request_no_name_two_active_matched_by_id: an id no running dispatch holds is the old refusal",
                 "dispatch_id does not match the active controller dispatch", verdict(root, two, "S5-qa-automator-9", ["TC-2"]))
        one = controller_of(rec(W1, scope=["TC-1"]))
        check_eq("no name, one active: today's road (it passes)", verdict(root, one, W1, ["TC-1"]), "")
        check_in("no name, one active: a foreign id is today's refusal",
                 "dispatch_id does not match the active controller dispatch", verdict(root, one, W2, ["TC-1"]))
        check_eq("no running dispatch: nothing is read (today's road)", verdict(root, controller_of(rec(W1, status="accepted")), "x", []), "")
    with envs(driver=W2):
        check_eq("run_request_of_second_window_passes: a session named W2 with W1 running beside it passes its own request",
                 verdict(root, two, W2, ["TC-2"]), "")
    with envs(detector=W2, driver=W1):
        check_eq("run_request_of_second_window_passes: the gate's word beats the driver's",
                 verdict(root, two, W2, ["TC-2"]), "")
    with envs(driver=W2):
        check_in("run_request_of_sibling_id_refused: a session named W2 carrying W1's id is refused, today's text",
                 "RunRequest dispatch_id does not match the active controller dispatch", verdict(root, two, W1, ["TC-1"]))
        closed = controller_of(rec(W1, scope=["TC-1"]), rec(W2, status="accepted", scope=["TC-2"]), rec("S5-qa-automator-3", scope=["TC-3"]))
        check_in("run_request_of_sibling_id_refused: a name that is closed owns no running dispatch (even its own id)",
                 "dispatch_id does not match", verdict(root, closed, W2, ["TC-2"]))
    with envs(driver="S5-qa-automator-77"):
        check_eq("a name this story does not hold: the count rule, one active (today's road)",
                 verdict(root, one, W1, ["TC-1"]), "")
        check_eq("a name this story does not hold, two active: told apart by the request id",
                 verdict(root, two, W1, ["TC-1"]), "")
    with envs(driver="   "):
        check_eq("a blank name is no name", verdict(root, two, W2, ["TC-2"]), "")


def story_event(root, name="automation-manifest.json"):
    target = root / "qa-factory" / "artifacts" / TICKET / "work" / name
    return {"tool_name": "Write", "cwd": str(root), "tool_input": {"file_path": str(target)}, "transcript_path": "/main.jsonl"}


def seed_story(root, *records):
    task = root / "qa-factory" / "artifacts" / TICKET
    (task / "state").mkdir(parents=True, exist_ok=True)
    (task / "work").mkdir(parents=True, exist_ok=True)
    (task / "state" / "controller.json").write_text(json.dumps(controller_of(*records)), encoding="utf-8")


@contextlib.contextmanager
def project_at(root):
    old = hooklib._PROJECT_ROOT_CACHE
    hooklib._PROJECT_ROOT_CACHE = root
    try:
        yield
    finally:
        hooklib._PROJECT_ROOT_CACHE = old


def blocked(event):
    import io
    old_err, sys.stderr = sys.stderr, io.StringIO()      # the refusal text is not this test's output
    try:
        G.owner_check(event, {})
    except BaseException:
        return True
    finally:
        sys.stderr = old_err
    return False


def part_roles(root):
    seed_story(root, rec(W1), rec(C2, role="qa-code-critic"))
    with project_at(root), envs():
        check_eq("dispatched_role_names_own_role: no name, today's first running", G.dispatched_role(story_event(root)), "qa-automator")
    with project_at(root), envs(driver=C2):
        check_eq("dispatched_role_names_own_role: the critic's session names the critic, not the first running",
                 G.dispatched_role(story_event(root)), "qa-code-critic")
    with project_at(root), envs(detector=W1, driver=C2):
        check_eq("dispatched_role_names_own_role: the gate's word is the automator", G.dispatched_role(story_event(root)), "qa-automator")
    with project_at(root), envs(driver="S5-qa-automator-77"):
        check_eq("dispatched_role_names_own_role: an unknown name with two running names no one", G.dispatched_role(story_event(root)), "")
    seed_story(root, rec(W1), rec(C2, role="qa-code-critic", status="accepted"))
    with project_at(root), envs(driver=C2):
        check_eq("dispatched_role_names_own_role: a closed name names no one", G.dispatched_role(story_event(root)), "")
    seed_story(root, rec(W1, status="accepted"))
    with project_at(root), envs():
        check_eq("no running dispatch, no name: today's empty answer", G.dispatched_role(story_event(root)), "")

    # the owner guard
    seed_story(root, rec(W1), rec(C2, role="qa-code-critic"))
    with project_at(root), envs(driver=C2):
        check("critic_of_w2_cannot_write_automator_artifact_while_w1_runs: refused",
              blocked(story_event(root)))
    with project_at(root), envs(driver=W1):
        check("owner_of_named_session_writes: the automator's own named session writes", not blocked(story_event(root)))
    with project_at(root), envs():
        check("no name: today's road, an owner running opens the guard", not blocked(story_event(root)))
    with project_at(root), envs(driver="S5-qa-automator-77"):
        check("a name this story does not hold: today's road (any owner running)", not blocked(story_event(root)))
    seed_story(root, rec(W1, role="qa-code-critic"))
    with project_at(root), envs():
        check("no name, no owner running: refused as today", blocked(story_event(root)))
    # the project-level path: any story
    ledger = {"tool_name": "Write", "cwd": str(root), "tool_input": {"file_path": str(root / "qa-factory" / "obligations.md")}}
    owner, outside = G._owner_of_path(ledger["tool_input"]["file_path"].replace("\\", "/"), {})
    if owner:
        seed_story(root, rec(W1, role=owner), rec(C2, role="qa-code-critic"))
        with project_at(root), envs(driver=C2):
            check("a project-level artifact: the sibling's open dispatch does not open the guard for a named non-owner",
                  (owner == "qa-code-critic") or not G._any_story_open_for_owner(ledger, owner))
    # reading (2), the legacy rework sub-state, is unchanged
    state = {"dispatches": {W1: rec(W1, status="accepted")}, "stages": {"S5": {"rework": True, "active_dispatch_id": W1}}}
    check_eq("reading (2) (rework sub-state) is unchanged", G._dispatch_open_for_owner(state, "qa-automator", C2), True)


def part_journal(root):
    c = REL.at_s3_rework(root)
    request = c.build_rework_request("S3", "qa-test-strategist", [], "one more pass")
    c.apply("dispatch", dict(request))
    release = threading.Event()
    acquired = threading.Event()

    def hold():
        with EventStore(root).lock():
            acquired.set()
            release.wait(10)
    holder = threading.Thread(target=hold)
    holder.start()
    check("the other writer holds the lock", acquired.wait(5))
    threading.Timer(3.0, release.set).start()     # longer than the controller's own 3 short retries (1.2 s in all)
    real = SJ.artifacts_dir
    SJ.artifacts_dir = lambda task, event: root
    try:
        started = time.monotonic()
        SJ.record_return({"digest": "done"}, {"agent": "a"}, {"task": "X"}, request["id"])
        elapsed = time.monotonic() - started
    finally:
        SJ.artifacts_dir = real
        release.set()
        holder.join(10)
    returned = [e["type"] for e in EventStore(root).read()].count("returned")
    check_eq("journal_waits_for_busy_lock: the return was recorded after the wait", returned, 1)
    check("journal_waits_for_busy_lock: it waited for the holder, not at once", elapsed >= 2.5, f"{elapsed:.2f}s")
    check("journal_waits_for_busy_lock: and less than the lifecycle wait", elapsed < ES.LIFECYCLE_WAIT_SECONDS, f"{elapsed:.2f}s")


def part_busy_lock_line(root):
    """t-2087 F2: the REAL controller with the lock held through all its tries returns False (it never raises): one line on stderr."""
    import io
    c = REL.at_s3_rework(root)
    request = c.build_rework_request("S3", "qa-test-strategist", [], "one more pass")
    c.apply("dispatch", dict(request))
    release, acquired = threading.Event(), threading.Event()

    def hold():
        with EventStore(root).lock():
            acquired.set()
            release.wait(30)
    holder = threading.Thread(target=hold)
    holder.start()
    check("busy-lock line: the other writer holds the lock", acquired.wait(5))
    real_dir, real_wait = SJ.artifacts_dir, ES.LIFECYCLE_WAIT_SECONDS
    SJ.artifacts_dir = lambda task, event: root
    ES.LIFECYCLE_WAIT_SECONDS = 0.2          # three tries of 0.2 s: the test does not wait 31 s
    captured, old_err = io.StringIO(), sys.stderr
    sys.stderr = captured
    try:
        SJ.record_return({"digest": "x"}, {"agent": "a"}, {"task": "X"}, request["id"])
    finally:
        sys.stderr = old_err
        SJ.artifacts_dir, ES.LIFECYCLE_WAIT_SECONDS = real_dir, real_wait
        release.set()
        holder.join(10)
    lines = [ln for ln in captured.getvalue().splitlines() if ln.strip()]
    check_eq("busy-lock line: a busy lock that returns False leaves exactly one line in the hook's log", len(lines), 1)
    check_in("busy-lock line: it names the dispatch", request["id"], lines[0] if lines else "")
    check_eq("busy-lock line: and no return was written (the control: the lock really was busy)",
             [e["type"] for e in EventStore(root).read()].count("returned"), 0)


def part_swallow_line(root):
    """A controller that raises: swallowed, one line on stderr."""
    import io
    import controller as CTRL
    real_cls, real_dir = CTRL.Controller, SJ.artifacts_dir

    class Broken:
        def __init__(self, *a, **k):
            raise OSError("lock busy")
    CTRL.Controller = Broken
    SJ.artifacts_dir = lambda task, event: root
    captured, old_err = io.StringIO(), sys.stderr
    sys.stderr = captured
    try:
        SJ.record_return({"digest": "x"}, {"agent": "a"}, {"task": "X"}, "S5-qa-automator-1")
    finally:
        sys.stderr = old_err
        CTRL.Controller, SJ.artifacts_dir = real_cls, real_dir
    lines = [ln for ln in captured.getvalue().splitlines() if ln.strip()]
    check_eq("journal_waits_for_busy_lock: the swallowed exception leaves exactly one line in the hook's log", len(lines), 1)
    check_in("the line names the dispatch and the error", "S5-qa-automator-1", lines[0] if lines else "")


def main():
    root = temp_project("qa-window-identity-")
    try:
        mark_project(root)
        part_typed_runner(root)
        part_roles(root)
        part_swallow_line(root)
    finally:
        cleanup(root)
    root2 = temp_project("qa-window-identity-journal-")
    try:
        part_journal(root2)
    finally:
        cleanup(root2)
    root3 = temp_project("qa-window-identity-busy-")
    try:
        part_busy_lock_line(root3)
    finally:
        cleanup(root3)
    finish("guard_window_identity")


if __name__ == "__main__":
    main()
