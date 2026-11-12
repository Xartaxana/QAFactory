"""SubagentStop journal hook: who tells the controller that a role came back.

TP2-2406 S5-7 and S5-8 (20.10.2026, Codex Desktop): the native child's per-turn stop fired
while the role was still working on the same thread, `subagent_journal` told the controller the
dispatch had RETURNED 97 s before the role called `run_suite`, and `run_suite` refused with "no
active S5-qa-automator-7 dispatch". The dispatch was bound by `story_step bind` (receipt
`bound_by: story_step`), and for such a dispatch only `story_step finish` moves the controller.
Every case below runs the hook's own `main()` against a real controller in a temp project, with the
live shapes of that run (the receipt, the dispatch, the rollout the host's `session_meta` names).
"""
import hashlib
import io
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import SCRIPTS, check, check_eq, cleanup, finish, s5_apply, temp_dir, use_project  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import hooklib  # noqa: E402
import host_dispatch  # noqa: E402
import subagent_journal as hook  # noqa: E402
from controller import Controller  # noqa: E402
import test_controller_state as BASE  # noqa: E402  (accept_stage / seed_plan / bind_gate_a fixtures)
import test_controller_rework_scope as SCOPED  # noqa: E402  (plan_row)

# The dashboard render after every commit is the slow part of a story fixture and is no part of what
# is tested here (the same switch test_execution_request.py sets).
os.environ["QA_FACTORY_SKIP_DASHBOARD_REFRESH"] = "1"

TASK = "TP2-2406"
DISPATCH = "S5-qa-automator-7"
AGENT_PATH = "/root/qa_automator__tp2_2406"
SESSION = "019daf66-9c2e-7a10-8c1d-2406a5b7c0de"
PARENT = "019daf10-0000-7000-8000-000000000001"
# The live receipt of S5-qa-automator-7, as `story_step bind` left it on 2406.
LIVE_RECEIPT = {"agent_id": AGENT_PATH, "task_path": AGENT_PATH, "task_id": TASK, "dispatch_id": DISPATCH,
                "status": "running", "bound_by": "story_step", "terminal_source": None,
                "bound_at": 1792455127.161339, "parent_session_id": None, "agent_type": "qa-automator"}


def story(root: Path):
    """A story whose S5-qa-automator-7 is `running` in the controller, and its task root."""
    (root / "qa-factory").mkdir(parents=True, exist_ok=True)
    (root / "qa-factory" / "config.json").write_text("{}", encoding="utf-8")
    task = root / "qa-factory" / "artifacts" / TASK
    task.mkdir(parents=True)
    controller = Controller(task)
    controller.apply("initialize", {"scope": ["TC-1"], "source_revision": "src-1",
                                    "known_paths": {"root": str(task)}, "idempotency_key": "init"})
    for number in range(5):  # S5 opens only on accepted S0..S4 and an approved Gate A
        BASE.accept_stage(controller, task, f"S{number}")
    BASE.seed_plan(task, [SCOPED.plan_row(1, "automate")])
    controller.apply("decision", BASE.bind_gate_a(task, {
        "id": "gate-a", "gate": "A", "action": "approve", "status": "approved",
        "authorization_source": "human", "source_revision": "src-1", "scope": ["TC-1"],
        "input_revision": "src-1", "idempotency_key": "gate-a"}))
    s5_apply(controller, {"id": DISPATCH, "stage": "S5", "role": "qa-automator", "scope": ["TC-1"],
                                  "input_hash": "ctx", "budget": {"requests": 5},
                                  "known_paths": {"root": str(task)}, "idempotency_key": "d-7"})
    return task


def put_receipt(root: Path, agent: str = AGENT_PATH, **over) -> Path:
    """The live receipt, with overrides, at the path `host_dispatch.binding_path` gives it."""
    path = host_dispatch.binding_path(root, agent)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({**LIVE_RECEIPT, **over}, indent=2), encoding="utf-8")
    return path


def rollout(root: Path) -> Path:
    """The child's own rollout, whose `session_meta` is where `host_dispatch.child_identity` reads the
    agent path from: the SubagentStop event carries a thread id, never the path."""
    path = root / ("rollout-2026-10-20T02-31-00-" + SESSION + ".jsonl")
    path.write_text(json.dumps({"type": "session_meta", "payload": {
        "id": SESSION, "agent_path": AGENT_PATH, "parent_thread_id": PARENT,
        "source": {"subagent": {"thread_spawn": {"agent_path": AGENT_PATH, "parent_thread_id": PARENT}}}}}) + "\n",
        encoding="utf-8")
    return path


def native_stop(root: Path) -> dict:
    """The Codex SubagentStop as the host sends it: a thread id and a rollout, no task, no dispatch."""
    return {"hook_event_name": "SubagentStop", "agent_type": "qa-automator", "subagent_type": "qa-automator",
            "session_id": SESSION, "agent_id": SESSION, "host": "codex", "transcript_path": str(rollout(root))}


def explicit_stop(**fields) -> dict:
    """A stop that names its story and dispatch itself and carries no identity enrich could resolve."""
    return {"hook_event_name": "SubagentStop", "agent_type": "qa-automator", "subagent_type": "qa-automator",
            "task_id": TASK, "dispatch_id": DISPATCH, **fields}


def stop(raw: dict, patched_read: bool = False) -> int:
    """Run `subagent_journal.main()` on the event; `patched_read` skips `enrich` (a receipt that no
    hook would have resolved). Returns the exit code, which must always be 0."""
    saved_stdin, saved_read = sys.stdin, hook.read_event
    try:
        if patched_read:
            hook.read_event = lambda: dict(raw)
        else:
            sys.stdin = io.StringIO(json.dumps(raw))
        try:
            hook.main()
        except SystemExit as exc:
            return int(exc.code or 0)
        return 0
    finally:
        sys.stdin, hook.read_event = saved_stdin, saved_read


def stops(root: Path) -> list:
    journal = root / "qa-factory" / "records" / "journal.jsonl"
    lines = [json.loads(x) for x in journal.read_text(encoding="utf-8").splitlines() if x] if journal.exists() else []
    return [r for r in lines if r.get("event") == "subagent_stop"]


def returned(task: Path) -> list:
    return [e for e in Controller(task).store.read() if e["type"] == "returned"]


def status(task: Path) -> str:
    return Controller(task).state()["dispatches"][DISPATCH]["status"]


def scenario(name: str, body) -> None:
    """A fresh temp project per case, the hook layer pointed at it."""
    root = temp_dir("qa-subagent-journal-")
    try:
        use_project(root)
        body(root, story(root))
    except Exception as exc:  # a crash in a case is one red line, not a lost run
        check(f"{name}: the case ran to its end", False, f"{type(exc).__name__}: {exc}")
    finally:
        cleanup(root)


def case_a(root, task):
    receipt = put_receipt(root)
    code = stop(native_stop(root))
    line = stops(root)[-1]
    check_eq("(a) the hook never blocks the stop", code, 0)
    check_eq("(a) enrich resolved the receipt, so the line names the story and dispatch",
             (line["task"], line["dispatch"]), (TASK, DISPATCH))
    check_eq("(a) a story_step-bound dispatch stays `running` after the native child's per-turn stop",
             status(task), "running")
    check_eq("(a) no `returned` event: `story_step finish` alone returns a bound dispatch", returned(task), [])
    check_eq("(a) the journal line names the owner of the return", line.get("return_owner"), "story_step")
    check_eq("(a) and the receipt, by file name, under `dispatch_receipt` (the event's `host_binding` is a path)",
             (line.get("dispatch_receipt"), "host_binding" in line), (receipt.name, False))
    check("(a) the old key `host_receipt` is gone: it named another artifact (`state/host-receipts/`)",
          "host_receipt" not in line)
    check_eq("(a) the receipt is read, never rewritten, by the stop",
             json.loads(receipt.read_text(encoding="utf-8")), LIVE_RECEIPT)


def case_b(root, task):
    put_receipt(root, status="terminal", terminal_source="story_step")
    check_eq("(b) the hook never blocks the stop", stop(native_stop(root)), 0)
    line = stops(root)[-1]
    check_eq("(b) a late stop after `story_step finish` adds no event, whatever the dispatch's state",
             (status(task), returned(task)), ("running", []))
    # CX2-24 (main differs from the base of 68b8cf83): `enrich._bound_candidate` names no story from a TERMINAL
    # receipt (a later launch under the same path is not that dispatch), so a late NATIVE stop carries no dispatch id
    # of the story: `_identity` falls back to the thread id, which no controller dispatch has, and `record_return`
    # finds nothing to return. No story_step receipt is named either way, and (FX1, critic t-1248) no `return_owner`
    # either: the thread id is no dispatch of the story, so nobody was told and no owner is claimed.
    check_eq("(b) a late native stop finds a terminal receipt that names no story: the dispatch is the thread id, no receipt, no owner named",
             (line["dispatch"], "dispatch_receipt" in line, "return_owner" in line), (SESSION, False, False))
    # The same late stop when the event names its story and dispatch itself: the terminal receipt owns it (E2).
    check_eq("(b) the hook never blocks the late stop", stop(explicit_stop()), 0)
    check_eq("(b) a terminal story_step receipt still owns the return of a named dispatch, and nothing is returned",
             (stops(root)[-1].get("return_owner"), returned(task)), ("story_step", []))
    check_eq("(b) every late stop leaves its journal line (FR-23: the null outcome is recorded)", len(stops(root)), 2)


def case_c(root, task):
    # The receipt `host_dispatch.record` writes at spawn: keyed by the thread id, no `bound_by`.
    hook_bound = {"agent_id": SESSION, "task_path": AGENT_PATH, "task_id": TASK, "dispatch_id": DISPATCH,
                  "agent_type": "qa-automator", "status": "running", "parent_session_id": PARENT,
                  "host": "codex", "bound_at": 1792455100.0}
    path = host_dispatch.binding_path(root, SESSION)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(hook_bound), encoding="utf-8")
    check_eq("(c) the hook never blocks the stop", stop(native_stop(root)), 0)
    line = stops(root)[-1]
    check_eq("(c) enrich resolved the hook-bound receipt", line.get("dispatch"), DISPATCH)
    events = returned(task)
    check_eq("(c) a hook-bound receipt does not own the return: the hook records it as before",
             [(e["payload"]["dispatch_id"], e["payload"]["recorded_by"]) for e in events],
             [(DISPATCH, "subagent_stop")])
    check_eq("(c) the dispatch is no longer running", status(task) != "running", True)
    check_eq("(c) the line says the hook told the controller", line.get("return_owner"), "subagent_stop")
    check("(c) and carries no receipt name it did not use", "dispatch_receipt" not in line)


def case_c_other_owner(root, task):
    # enrich takes a non-story_step receipt only when its parent session is the child's own parent.
    put_receipt(root, bound_by="SubagentStart", parent_session_id=PARENT)
    check_eq("(c) the hook never blocks the stop", stop(native_stop(root)), 0)
    check_eq("(c) only `bound_by: story_step` owns a return: another writer's receipt does not",
             (len(returned(task)), stops(root)[-1].get("return_owner")), (1, "subagent_stop"))


def case_d(root, task):
    check_eq("(d) the hook never blocks the stop", stop(explicit_stop()), 0)
    line = stops(root)[-1]
    check_eq("(d) no receipt at all and an EXPLICIT `dispatch_id` on the event: the return is recorded",
             len(returned(task)), 1)
    check_eq("(d) the line says the hook told the controller", line.get("return_owner"), "subagent_stop")
    check("(d) and names no receipt", "dispatch_receipt" not in line)


def case_e(root, task):
    controller = Controller(task)
    check_eq("(e) the first return of a running dispatch is committed", controller.record_return(DISPATCH, "x", "qa"), True)
    check_eq("(e) a second return of the same dispatch commits nothing (idempotency key returned:<id>)",
             Controller(task).record_return(DISPATCH, "y", "qa"), False)
    check_eq("(e) so there is one `returned` event", len(returned(task)), 1)
    stop(explicit_stop())
    check_eq("(e) and a hook stop after that adds none", len(returned(task)), 1)
    check_eq("(e) the hook still journalled that stop", len(stops(root)), 1)


def case_e_accepted(root, task):
    """Item 2: the late stop after `story_step finish` accepted the dispatch."""
    (task / "e.txt").write_text("e", encoding="utf-8")
    evidence = {"path": "e.txt", "sha256": hashlib.sha256((task / "e.txt").read_bytes()).hexdigest()}
    Controller(task).apply("accept", {"id": DISPATCH, "status": "accepted", "stage_complete": False,
                                      "evidence_refs": [evidence], "idempotency_key": "a-7"})
    before = len(Controller(task).store.read())
    check_eq("(e) an accepted dispatch is not returned again", Controller(task).record_return(DISPATCH, "late", "qa"), False)
    stop(explicit_stop())
    check_eq("(e) neither by the record call nor by a stop: no event is added after the accept",
             len(Controller(task).store.read()), before)
    check_eq("(e) the dispatch stays accepted", status(task), "accepted")


def case_f(root, task):
    event = {"hook_event_name": "SubagentStop", "agent_type": "qa-automator", "task_id": TASK}
    check_eq("(f) the hook never blocks the stop", stop(event), 0)
    check_eq("(f) a stop whose dispatch cannot be told adds no event and the dispatch is untouched",
             (returned(task), status(task)), ([], "running"))
    check_eq("(f) but the journal line is written, as today", len(stops(root)), 1)
    check("(f) and names no return owner: with no dispatch id nobody was told, so no label overclaims",
          "return_owner" not in stops(root)[-1])


def case_f_no_guess(root, task):
    put_receipt(root)
    event = {"hook_event_name": "SubagentStop", "agent_type": "qa-automator", "task_id": TASK}
    check_eq("(f) the hook never blocks the stop", stop(event), 0)
    check_eq("(f) an unknown dispatch id is never guessed from the role's story_step receipt (FR-59)",
             (returned(task), status(task)), ([], "running"))
    check_eq("(f) the journal line is written", len(stops(root)), 1)
    line = stops(root)[-1]
    check("(f) with no dispatch id there is no `return_owner`, and no receipt is claimed",
          "return_owner" not in line and "dispatch_receipt" not in line)


def case_g(root, task):
    broken = root / "broken-receipt.json"
    broken.write_text("{not json", encoding="utf-8")
    event = explicit_stop(host_binding=str(broken))
    check_eq("(g) the hook never blocks the stop", stop(event, patched_read=True), 0)
    check_eq("(g) an unreadable receipt counts as absent: today's path records the return",
             len(returned(task)), 1)
    check_eq("(g) and the line says so", stops(root)[-1].get("return_owner"), "subagent_stop")


def case_g_directory(root, task):
    directory = host_dispatch.binding_path(root, AGENT_PATH).parent
    directory.mkdir(parents=True)
    (directory / "0-broken.json").write_text("{not json", encoding="utf-8")
    (directory / "1-list.json").write_text("[1, 2]", encoding="utf-8")
    check_eq("(g) the hook never blocks the stop", stop(explicit_stop()), 0)
    check_eq("(g) unreadable and non-object receipts in the directory name no owner",
             (len(returned(task)), stops(root)[-1].get("return_owner")), (1, "subagent_stop"))


def case_g_beside_owner(root, task):
    directory = host_dispatch.binding_path(root, AGENT_PATH).parent
    directory.mkdir(parents=True)
    (directory / "0-broken.json").write_text("{not json", encoding="utf-8")
    (directory / "1-list.json").write_text("[1, 2]", encoding="utf-8")
    put_receipt(root)
    check_eq("(g) the hook never blocks the stop", stop(explicit_stop()), 0)
    check_eq("(g) broken receipts beside the owner's do not hide it: still no event",
             (returned(task), status(task)), ([], "running"))
    broken = root / "broken-named.json"
    broken.write_text("{not json", encoding="utf-8")
    check_eq("(g) the hook never blocks the stop", stop(explicit_stop(host_binding=str(broken)), patched_read=True), 0)
    check_eq("(g) an unreadable NAMED receipt falls through to the directory, where the owner is found",
             (returned(task), stops(root)[-1].get("return_owner")), ([], "story_step"))


def case_h(root, task):
    receipt = put_receipt(root)
    event = explicit_stop(session_id="s-no-receipt")
    check("(h) the event carries no host_binding of its own", "host_binding" not in event)
    check_eq("(h) the hook never blocks the stop", stop(event), 0)
    line = stops(root)[-1]
    check_eq("(h) the receipt is found by task AND dispatch id and owns the return: no event",
             (returned(task), status(task)), ([], "running"))
    check_eq("(h) the line names the owner and the receipt",
             (line.get("return_owner"), line.get("dispatch_receipt")), ("story_step", receipt.name))


def case_h_not_shadowed(root, task):
    # A story_step receipt of another window of the same role, and of the same dispatch id in another story.
    put_receipt(root, agent="/root/qa_automator__old", dispatch_id="S5-qa-automator-6", status="terminal",
                terminal_source="story_step")
    put_receipt(root, agent="/root/qa_automator__other_story", task_id="OTHER-1")
    check_eq("(h) the hook never blocks the stop", stop(explicit_stop()), 0)
    check_eq("(h) a receipt of another dispatch, or of another story, never shadows this dispatch",
             (len(returned(task)), stops(root)[-1].get("return_owner")), (1, "subagent_stop"))


def case_host_binding_wins(root, task):
    receipt = put_receipt(root, dispatch_id=None)
    event = {"hook_event_name": "SubagentStop", "agent_type": "qa-automator", "task_id": TASK,
             "host_binding": str(receipt)}
    check_eq("(a) the hook never blocks the stop", stop(event, patched_read=True), 0)
    line = stops(root)[-1]
    check_eq("(a) a story_step receipt `host_binding` names decides, with no dispatch id to match and none guessed",
             (returned(task), status(task), line.get("dispatch_receipt")), ([], "running", receipt.name))
    check("(a) and with no dispatch resolved the line names no return owner", "return_owner" not in line)
    # The converse, flipped by the critic (t-047 F1): a readable NON-story_step receipt named by
    # host_binding does not decide; the directory scan finds the story_step receipt of this dispatch.
    plain = root / "hook-bound.json"
    plain.write_text(json.dumps({"agent_id": SESSION, "task_id": TASK, "dispatch_id": DISPATCH,
                                 "status": "running"}), encoding="utf-8")
    put_receipt(root)
    stop(explicit_stop(host_binding=str(plain)), patched_read=True)
    check_eq("(a) a named hook-bound receipt falls through to the scan: the story_step owner is found, no event",
             (returned(task), stops(root)[-1].get("return_owner")), ([], "story_step"))


def case_named_hook_receipt_alone(root, task):
    plain = root / "hook-bound.json"
    plain.write_text(json.dumps({"agent_id": SESSION, "task_id": TASK, "dispatch_id": DISPATCH,
                                 "status": "running"}), encoding="utf-8")
    check_eq("(a) the hook never blocks the stop", stop(explicit_stop(host_binding=str(plain)), patched_read=True), 0)
    check_eq("(a) a named hook-bound receipt with no story_step receipt anywhere: today's path records the return",
             (len(returned(task)), stops(root)[-1].get("return_owner")), (1, "subagent_stop"))


def case_two_receipts(root, task):
    # The live host (t-047 F1): `host_dispatch.record` wrote a receipt keyed by the child's thread id
    # (no `bound_by`), `story_step bind` one keyed by the path; `enrich` finds the thread-id one first.
    hook_bound = {"agent_id": SESSION, "task_path": AGENT_PATH, "task_id": TASK, "dispatch_id": DISPATCH,
                  "agent_type": "qa-automator", "status": "running", "parent_session_id": PARENT,
                  "host": "codex", "bound_at": 1792455100.0}
    thread_receipt = host_dispatch.binding_path(root, SESSION)
    thread_receipt.parent.mkdir(parents=True, exist_ok=True)
    thread_receipt.write_text(json.dumps(hook_bound), encoding="utf-8")
    owner = put_receipt(root)
    enriched = host_dispatch.enrich(native_stop(root))
    check_eq("(two) the real enrich resolves the THREAD-ID receipt first, as on the live host",
             Path(enriched["host_binding"]).name, thread_receipt.name)
    check_eq("(two) the hook never blocks the stop", stop(native_stop(root)), 0)
    line = stops(root)[-1]
    check_eq("(two) the story_step receipt owns the return although the thread-id one was named: no `returned`",
             (returned(task), status(task)), ([], "running"))
    check_eq("(two) the line names the owner and the story_step receipt's file",
             (line.get("return_owner"), line.get("dispatch_receipt")), ("story_step", owner.name))


def case_claude_host(root, task):
    agent = "a1b2c3d4e5f60718"  # Claude Code identifies a subagent by `agent_id`; no rollout, no thread path
    raw = {"hook_event_name": "SubagentStop", "agent_type": "qa-automator", "subagent_type": "qa-automator",
           "session_id": "claude-session-1", "agent_id": agent, "host": "claude"}
    owner = put_receipt(root, agent=agent, agent_id=agent, task_path=None)
    check_eq("(F3) the hook never blocks the stop", stop(raw), 0)
    line = stops(root)[-1]
    check_eq("(F3) Claude host: a story_step receipt keyed by the agent id resolves the dispatch",
             (line["task"], line["dispatch"]), (TASK, DISPATCH))
    check_eq("(F3) and owns the return: the skip holds on every host, the contract is the binding",
             (returned(task), status(task), line.get("return_owner"), line.get("dispatch_receipt")),
             ([], "running", "story_step", owner.name))
    owner.unlink()
    check_eq("(F3) the hook never blocks the stop", stop({**raw, "task_id": TASK, "dispatch_id": DISPATCH}), 0)
    check_eq("(F3) Claude host, no receipt, an EXPLICIT `dispatch_id` on the event: today's `returned` stays "
             "(the live shape without a `dispatch_id` is case `FX1` below)",
             (len(returned(task)), stops(root)[-1].get("return_owner")), (1, "subagent_stop"))


def claude_stop(**fields) -> dict:
    """A live Claude Code SubagentStop as the hook receives it: a hex `agent_id`, the story's task, NO `dispatch_id`."""
    return {"hook_event_name": "SubagentStop", "agent_type": "qa-automator", "subagent_type": "qa-automator",
            "session_id": "claude-session-1", "agent_id": "a1b2c3d4e5f60718", "host": "claude", "task_id": TASK,
            **fields}


def case_host_id_is_no_dispatch(root, task):
    """FX1 (critic t-1248 F1): `exit_gate._identity` falls back to the host's own id when the event sends no
    `dispatch_id`; that id is no dispatch of the story, so no stop that carries only it claims an owner. The
    controller state is as before: nothing returned (the controller has no dispatch keyed by a host id)."""
    # (1) a native stop with no receipt anywhere (a rollout, a thread id, no task, no dispatch)
    check_eq("(FX1) the hook never blocks a native stop with no receipt", stop(native_stop(root)), 0)
    line = stops(root)[-1]
    check_eq("(FX1) native, no receipt: the line's dispatch is the thread id and nobody was told: no owner, no receipt",
             (line["dispatch"], "return_owner" in line, "dispatch_receipt" in line), (SESSION, False, False))
    # (2) a Claude-shaped stop with no receipt and no transcript to read a dispatch from
    check_eq("(FX1) the hook never blocks a Claude stop with no receipt", stop(claude_stop()), 0)
    line = stops(root)[-1]
    check_eq("(FX1) Claude, no receipt, no dispatch to read: the dispatch is the agent id, no owner claimed",
             (line["dispatch"], "return_owner" in line, "dispatch_receipt" in line), ("a1b2c3d4e5f60718", False, False))
    check_eq("(FX1) and the controller state is as before: nothing returned, the dispatch untouched",
             (returned(task), status(task)), ([], "running"))
    # (3) the converse, adversarial: the session id alone, equal to nothing the controller knows
    stop(claude_stop(agent_id=""))
    line = stops(root)[-1]
    check_eq("(FX1) the session id is a host id too (no agent id sent)",
             (line["dispatch"], "return_owner" in line), ("claude-session-1", False))
    # (4) an event that DOES send its dispatch_id is unchanged, whatever host ids ride along - even when a host id
    # equals the dispatch id itself (the id is then the event's own, not the fallback's)
    for label, fields in (("with host ids", {"agent_id": "a1b2c3d4e5f60718", "session_id": "claude-session-1"}),
                          ("with the agent id equal to the dispatch id", {"agent_id": DISPATCH})):
        stop(explicit_stop(**fields))
        line = stops(root)[-1]
        check_eq(f"(FX1) a real `dispatch_id` is unchanged {label}: the owner is named",
                 (line["dispatch"], line.get("return_owner")), (DISPATCH, "subagent_stop"))
    check_eq("(FX1) and the controller was told once, about that dispatch",
             [e["payload"]["dispatch_id"] for e in returned(task)], [DISPATCH])


def case_claude_remedy(root, task):
    """F5 (critic t-1248): the live Claude stop has no `dispatch_id`; the host id `_identity` fell back to must not hide
    the two fallbacks behind it (the subagent transcript's first prompt, the event's own prompt) - the TP1-15045 remedy."""
    transcript = root / "agent-a1b2c3d4e5f60718.jsonl"
    transcript.write_text(json.dumps({"type": "user", "message": {"role": "user", "content": [
        {"type": "text", "text": f"You are qa-automator. Ticket: {TASK}. Dispatch id: {DISPATCH} Work on it."}]}}) + "\n",
        encoding="utf-8")
    check_eq("(F5) the hook never blocks a Claude stop whose transcript names the dispatch",
             stop(claude_stop(transcript_path=str(transcript))), 0)
    line = stops(root)[-1]
    check_eq("(F5) a host-id-only stop is owned by the hook, the journal line keeping the scope's own `dispatch` key",
             (line["dispatch"], line.get("return_owner")), ("a1b2c3d4e5f60718", "subagent_stop"))
    check_eq("(F5) and the controller is told about the dispatch the transcript names, not about the agent id",
             ([e["payload"]["dispatch_id"] for e in returned(task)], status(task) != "running"), ([DISPATCH], True))


def case_claude_remedy_prompt(root, task):
    """F5, the second fallback: no transcript, the dispatch id rides in the event's own prompt."""
    check_eq("(F5) the hook never blocks the stop", stop(claude_stop(prompt=f"Ticket: {TASK}. Dispatch id: {DISPATCH} go")), 0)
    check_eq("(F5) a host-id-only stop whose prompt names the dispatch is returned by the hook",
             (len(returned(task)), stops(root)[-1].get("return_owner")), (1, "subagent_stop"))


def case_once_per_stop(root, task):
    """F7 (critic t-1248): the dispatch of a stop (and the transcript read behind it) is resolved ONCE in `main` and handed down."""
    calls = []
    original = hook._dispatch_id
    hook._dispatch_id = lambda event, scope: (calls.append(1), original(event, scope))[1]
    try:
        stop(explicit_stop())                       # no owner: record_return runs
        unowned = len(calls)
        calls.clear()
        put_receipt(root)
        stop(explicit_stop())                       # an owner by the directory scan: record_return is skipped
        owned = len(calls)
    finally:
        hook._dispatch_id = original
    check_eq("(F7) one resolution of the dispatch per stop, with and without an owner", (unowned, owned), (1, 1))


def case_never_raises(root, task):
    put_receipt(root)
    saved = host_dispatch.receipt_files

    def boom(_root):
        raise RuntimeError("the receipt directory is unreadable")

    host_dispatch.receipt_files = boom
    try:
        code = stop(explicit_stop())
    finally:
        host_dispatch.receipt_files = saved
    check_eq("(k) a failing receipt scan never blocks the stop", code, 0)
    check_eq("(k) it is no owner: today's path records the return and the line is written",
             (len(returned(task)), len(stops(root))), (1, 1))


def case_unbound(root, task):
    """E1 and E4: a subagent that names no story, no dispatch and has no receipt; the journal file is absent."""
    journal = root / "qa-factory" / "records" / "journal.jsonl"
    check("(E1) the journal file is absent before the stop", not journal.exists())
    check_eq("(E1) the hook never blocks the stop of an unbound subagent",
             stop({"hook_event_name": "SubagentStop", "agent_type": "general-purpose"}), 0)
    check_eq("(E1/E4) the absent journal is created and the stop journalled, as before", len(stops(root)), 1)
    line = stops(root)[-1]
    check_eq("(E1) nothing returned, the dispatch untouched, nobody refused",
             (returned(task), status(task)), ([], "running"))
    check("(E1) no owner and no receipt claimed: nobody was told",
          "return_owner" not in line and "dispatch_receipt" not in line)


def case_spellings(root, task):
    """E3 / axis 20: the one reader of a child's name is `host_dispatch.binding_names`, inside `enrich`. The receipt
    is `story_step bind`'s (path + task_name); the stop names the child as the path or as the bare task name, and the
    agent type is spelled the Claude way (`qa-factory:<role>`) or the Codex way (the bare role)."""
    name = AGENT_PATH.rsplit("/", 1)[-1]
    owner = put_receipt(root, task_name=name)
    for label, agent_id, agent_type in (("path", AGENT_PATH, "qa-automator"), ("task_name", name, "qa-automator"),
                                        ("claude type", AGENT_PATH, "qa-factory:qa-automator")):
        raw = {"hook_event_name": "SubagentStop", "agent_type": agent_type, "subagent_type": agent_type,
               "session_id": "s-" + label, "agent_id": agent_id}
        check_eq(f"(E3 {label}) the hook never blocks the stop", stop(raw), 0)
        line = stops(root)[-1]
        check_eq(f"(E3 {label}) enrich resolved the receipt under this spelling: the story_step receipt owns the return",
                 (line.get("dispatch"), line.get("return_owner"), line.get("dispatch_receipt")),
                 (DISPATCH, "story_step", owner.name))
    check_eq("(E3) three stops under three spellings returned nothing", (returned(task), status(task)), ([], "running"))
    # (iii) the other binding kind under a bare task_name: the SubagentStart receipt (no `bound_by`) is told as before
    owner.unlink()
    put_receipt(root, agent="019e-start-uuid", agent_id="019e-start-uuid", task_path=None, bound_by=None,
                task_name="qa_start_child", parent_session_id="p-1")
    raw = {"hook_event_name": "SubagentStop", "agent_type": "qa-automator", "session_id": "p-1",
           "agent_id": "qa_start_child"}
    check_eq("(iii) the hook never blocks the stop", stop(raw), 0)
    check_eq("(iii) a SubagentStart (non-story_step) receipt, found by its task_name, keeps today's `returned`",
             (len(returned(task)), stops(root)[-1].get("return_owner")), (1, "subagent_stop"))


def case_one_terminal(root, task):
    """(ii) and (iv): `story_step finish` accepts the dispatch; a stop before, after and twice adds no `returned`."""
    receipt = put_receipt(root)
    check_eq("(ii) a stop before the finish: no event", (stop(native_stop(root)), returned(task)), (0, []))
    (task / "e.txt").write_text("e", encoding="utf-8")
    evidence = {"path": "e.txt", "sha256": hashlib.sha256((task / "e.txt").read_bytes()).hexdigest()}
    Controller(task).apply("accept", {"id": DISPATCH, "status": "accepted", "stage_complete": False,
                                      "evidence_refs": [evidence], "idempotency_key": "a-7"})
    receipt.write_text(json.dumps({**LIVE_RECEIPT, "status": "terminal", "terminal_source": "story_step"}),
                       encoding="utf-8")
    before = len(Controller(task).store.read())
    for label in ("late", "duplicate"):
        check_eq(f"(iv) a {label} stop is journalled and adds no controller event",
                 (stop(explicit_stop()), len(Controller(task).store.read())), (0, before))
    check_eq("(ii) `story_step finish` was the only terminal: accepted, never `returned`",
             (status(task), returned(task), len(stops(root))), ("accepted", [], 3))


def case_unfinished_worker(root, task):
    """(v) a worker that never calls `finish` is not recovered by the journal line: the dispatch stays `running`,
    and `dispatch_liveness` answers UNKNOWN with the person's release as the door (fail-closed), never RETURNED."""
    import dispatch_liveness as DL
    receipt = put_receipt(root)
    stop(native_stop(root))
    bound_at = LIVE_RECEIPT["bound_at"]
    row = {"id": DISPATCH, "role": "qa-automator"}
    verdict = DL.state(root, TASK, row, now=bound_at + 100000)
    check_eq("(v) the journalled stop of a bound dispatch is no return: past the window it is UNKNOWN",
             verdict["state"], DL.UNKNOWN)
    check_eq("(v) and the verdict names the door: only a person's release closes it",
             any("only a person's release closes it" in line for line in verdict["evidence"]), True)
    check_eq("(v) a young receipt keeps it alive", DL.state(root, TASK, row, now=bound_at + 5)["state"], DL.ALIVE)
    check_eq("(v) the receipt was not written by the stop", json.loads(receipt.read_text(encoding="utf-8")),
             LIVE_RECEIPT)


def case_no_second_reader(root, task):
    """(vi) / AR-5 / AR-13: the hook compares no child name and scans no receipt directory itself. Positive control:
    the same pattern finds the reader in `host_dispatch.py`."""
    import re
    pattern = re.compile(r"""["'](?:agent_id|task_path|task_name)["']|host-dispatches|\.glob\(""")
    hd_source = Path(host_dispatch.__file__).read_text(encoding="utf-8")
    check("(vi) control: the pattern finds the receipt-name keys in host_dispatch.py", bool(pattern.search(hd_source)))
    code = [line.strip() for line in Path(hook.__file__).read_text(encoding="utf-8").splitlines()
            if not line.strip().startswith("#")]
    # The ONE named exemption: the EVENT's own host-id fields that `exit_gate._identity` falls back to (FX1/F5). They are
    # event fields, not a receipt's name keys; `HOST_ID_FIELDS` is the only line allowed to spell them.
    exempt = [line for line in code if line.startswith("HOST_ID_FIELDS = ")]
    check_eq("(vi) the exemption is exactly one constant naming the event's host-id fields",
             exempt, ['HOST_ID_FIELDS = ("agent_id", "session_id")'])
    check_eq("(vi) subagent_journal.py reads no receipt name key and scans no receipt directory itself",
             [line for line in code if pattern.search(line) and line not in exempt], [])


def case_probe_child(root, task):
    """RN1-1 m-2: the doctor's probe child on Claude has no receipt and no `host_binding`; the ONE predicate
    `host_probe.is_probe_child` (its mark, tied to the same launch) keeps it out of the journal, as `exit_gate` does.
    Kills: the inline binding-only check back in `subagent_journal.main` (K6 line written), a predicate that ignores the session."""
    challenge = "0123456789abcdef0123456789abcdef"
    store = root / "qa-factory" / "state" / "host-probe.json"
    store.parent.mkdir(parents=True, exist_ok=True)
    store.write_text(json.dumps({"session_id": "claude-session-1", "injection": {
        "challenge": challenge, "status": "emitted", "tool_use_id": "spawn"}}), encoding="utf-8")
    before = len(stops(root))
    probe = claude_stop(last_assistant_message="QA_CONTEXT_RECEIVED_" + challenge + "_END")
    check_eq("(K6) the hook never blocks the probe child's stop", stop(probe), 0)
    check_eq("(K6) the probe child is not journaled as a `subagent_stop`", len(stops(root)), before)
    check_eq("(K7) control: a stage role's stop (no mark) IS journaled", (stop(claude_stop()), len(stops(root))), (0, before + 1))
    stop({**probe, "session_id": "another-session"})
    check_eq("(K3) the mark under another session is journaled (not exempt)", len(stops(root)), before + 2)


def main() -> None:
    cached =hooklib._PROJECT_ROOT_CACHE
    try:
        for name, body in (("a", case_a), ("b", case_b), ("c", case_c), ("c2", case_c_other_owner),
                           ("d", case_d), ("e", case_e), ("e2", case_e_accepted), ("f", case_f),
                           ("f2", case_f_no_guess), ("g", case_g), ("g2", case_g_directory), ("g3", case_g_beside_owner), ("h", case_h),
                           ("h2", case_h_not_shadowed), ("a2", case_host_binding_wins),
                           ("a3", case_named_hook_receipt_alone), ("two", case_two_receipts),
                           ("F3", case_claude_host), ("FX1", case_host_id_is_no_dispatch),
                           ("F5", case_claude_remedy), ("F5b", case_claude_remedy_prompt),
                           ("F7", case_once_per_stop), ("k", case_never_raises),
                           ("E1", case_unbound), ("E3", case_spellings), ("ii", case_one_terminal),
                           ("v", case_unfinished_worker), ("vi", case_no_second_reader),
                           ("probe", case_probe_child)):
            scenario(name, body)
    finally:
        hooklib._PROJECT_ROOT_CACHE = cached
    finish("test_subagent_journal")


if __name__ == "__main__":
    main()
