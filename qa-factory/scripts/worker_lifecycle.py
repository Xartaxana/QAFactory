"""Host-bound worker cancellation policy. Polling timeouts are never stop authority."""
import json
from pathlib import Path
from hooklib import sorted_paths

CAUSES = {"user_stop", "source_blocker", "terminal_failure", "authorized_budget"}


def cancellation(request):
    """The cancellation record of a request, or ONE refusal with every problem it has.

    The four checks read the request independently (each compares a field of it with a constant,
    none reads what another established), so they are collected, not raised one by one (K1,
    cmp3): a request with no evidence, an unreported source blocker and a tool still running
    cost three rounds when the first failure hid the rest. The refusal is the combined form
    `detector_verdict.compound` writes - one problem is its own sentence, unchanged - and the
    class is `ValueError`, as it always was."""
    cause = request.get("cause")
    problems = []
    if cause not in CAUSES or not request.get("evidence_ref"):
        problems.append("cancellation requires an explicit cause and evidence_ref; elapsed time is not a cause")
    if cause == "source_blocker" and not request.get("user_notified"):
        problems.append("required-source blocker must be reported to the user before stopping")
    if cause == "authorized_budget" and not request.get("authorization_ref"):
        problems.append("hard budget requires explicit authorization_ref")
    if request.get("tool_active") and cause != "user_stop":
        problems.append("allow the active tool operation to settle before cancellation")
    if problems:
        from detector_verdict import compound
        raise ValueError(compound(problems))
    return {"cause": cause, "evidence_ref": request["evidence_ref"],
            "retry_charge": cause == "terminal_failure", "status": "requested"}


def bindings(root):
    for path in sorted_paths((Path(root) / "qa-factory/state/host-dispatches").glob("*.json")):
        try:
            yield json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue


def _natively_returned(root, binding, now=None, held=None):
    """Whether the host's own record says this story_step-bound worker ended.

    TP2-2406 S4 (13.10.2026): the case designer's rollout ended with its completion event, but its
    `story_step` receipt stays `running` until `story_step finish`, which refused (handoff incomplete,
    case bytes unpinned) - and the receipt's `status` alone kept the authorized durable checkpoint
    refused ("host worker is still active"). The host's record for the receipt's EXACT path and THIS
    launch (`dispatch_liveness.native_stop`, all candidate rollouts of the path, older than its grace
    window) is a reason a non-terminal receipt stops counting as an active worker. The other is the Claude
    Code host's (OH3-16): the worker's transcript ends with the host's acknowledgement of its handback and the
    stop hooks have let it go (`dispatch_liveness.claude_stop`). Both are asked as `dispatch_liveness.state`
    asks them, through the one `host_verdict`, so the two readers agree. The receipt is neither written nor marked
    terminal. A rollout or transcript still being written or cut mid-row, one that ended otherwise (an abort), an
    earlier launch, no record, no report forms, or a helper that fails: not returned - a veto helper's failure is
    not evidence. `held` is a dict the caller shares between the receipts of one call: the records are read into
    it once, and only for a receipt they can speak about."""
    try:
        import time
        import dispatch_liveness
        verdict = dispatch_liveness.host_verdict(
            root, binding, time.time() if now is None else now, dispatch_liveness.thresholds(root),
            {} if held is None else held)
    except Exception:  # noqa: BLE001 - a failing reader must never free a worker
        return False
    return isinstance(verdict, dict) and verdict.get("state") == dispatch_liveness.RETURNED


def binding_is_active(root, binding, event=None):
    """Whether a non-terminal host receipt still owns a running controller dispatch.

    A receipt is a fact about a launch, and the host rewrites it only when the child's stop hook
    fires. A dispatch the person released, one that never started, one the controller accepted
    leaves its receipt `running` for good - and that receipt then blocked every replacement
    spawn of its role, so the person's `release` was a dead end on the Codex host.

    False ONLY on a recorded controller fact that the dispatch is not running (or on the
    receipt's own terminal mark, read without touching anything else). Every doubt keeps the
    receipt active: no story or dispatch named, the story's controller.json missing, unreadable,
    not an object, or without that dispatch, a dispatch with no status - a spawn beside a live
    worker is the expensive mistake, a refused spawn names its door.

    `root` is where the receipts were read, so the story is resolved under it, exactly as
    `hooklib.artifacts_dir` would (including its refusal of a ticket that is not one path
    component: a receipt cannot steer this read outside the story folders). `artifacts_dir`
    itself resolves under the event's project, which is not `root` when no event is given."""
    if binding.get("status") == "terminal":
        return False
    task, dispatch = binding.get("task_id"), binding.get("dispatch_id")
    if not task or not dispatch:
        return True
    task = str(task)
    if task in (".", "..") or any(c in task for c in "/\\:"):
        return True
    try:
        from hooklib import artifact_root
        state = json.loads((artifact_root(event, root=root) / task / "state/controller.json")
                           .read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return True
    dispatches = state.get("dispatches") if isinstance(state, dict) else None
    record = dispatches.get(str(dispatch)) if isinstance(dispatches, dict) else None
    status = record.get("status") if isinstance(record, dict) else None
    if not isinstance(status, str) or not status:
        return True
    return status == "running"


def _blocking_text(blocking, root, task, event):
    """What blocks a duplicate spawn and the door that frees it, per receipt: the dispatch the
    receipt names and the person's `release`; a receipt that names none cannot be released."""
    named = list(dict.fromkeys(str(b["dispatch_id"]) for b in blocking if b.get("dispatch_id")))
    unbound = [b for b in blocking if not b.get("dispatch_id")]
    parts = []
    if named:
        try:
            from hooklib import artifacts_dir
            where = str(artifacts_dir(task, event))
        except (ValueError, OSError):
            where = "<the story's folder>"
        from person_words import door
        for dispatch in named:
            parts.append(f"Blocking: dispatch {dispatch} has a running host receipt and the controller has not "
                         f"recorded it as settled. If the person says it is gone, record their words: `"
                         + door(f"controller.py --task-root {where} --operation release --dispatch {dispatch}")
                         + "`; a released dispatch stops blocking.")
    if unbound:
        who = ", ".join(str(b.get("agent_id") or b.get("task_path") or "unknown") for b in unbound)
        parts.append(f"Blocking: a receipt ({who}) names no dispatch, so `release` cannot address it; it "
                     "clears when that worker stops and the host marks it terminal.")
    return " ".join(parts)


def note_unlaunched_denial(root, event, task, role, reason):
    """Write the pre-launch refusal of a spawn to the story's `dispatch-denials.jsonl`, for the one
    `running` dispatch of that role no worker ever took (FB-24, TP2-2406).

    `guard` refused S5-qa-automator-1's native spawn (host unverified) before `inject_context` could
    note the denial, so the controller's record said `running` with no agent and no receipt, and
    recovery could only answer "liveness unknown" - a story nobody could move without a person's
    release. The refusal itself is unchanged; it is written down the way `inject_context.note_denial`
    writes every other one, so `recover` can close the dispatch as `never_started`.

    Never closes a live worker (FB-24, I7): nothing is written while a receipt of this task and role is
    still active (`binding_is_active`: a terminal receipt or a dispatch the controller settled does not
    count; every doubt does), and a dispatch is charged only when it is `running`, of this role, with no
    `agent_id` and no `returned_at`. The dispatch the event NAMES (`dispatch_id_of`) is charged when it
    passes that test, and when it fails the line is not written at all - the orchestrator meant that
    dispatch, never another. An event naming none (the desktop's prompt is opaque) charges nobody by
    name: exactly ONE such dispatch of the role gives a row with its stage and role and NO dispatch id,
    which `Controller._denial_times` owns (one rule for who the row belongs to). The denial is enforced
    either way; this only records it."""
    try:
        if any(binding_is_active(root, b, event) for b in bindings(root)
               if b.get('task_id') == task and b.get('agent_type') == role):
            return
        from hooklib import artifacts_dir, read_json
        from inject_context import dispatch_id_of, note_denial
        state = read_json(artifacts_dir(task, event) / 'state/controller.json', {}, kind=dict)
        unlaunched = [d for d in (state.get('dispatches') or {}).values()
                      if isinstance(d, dict) and d.get('status') == 'running' and d.get('role') == role
                      and not d.get('agent_id') and not d.get('returned_at')]
        named = dispatch_id_of(event)
        if named:
            unlaunched = [d for d in unlaunched if d.get('id') == named]
        if len(unlaunched) != 1:
            return
        note_denial(dict(event, tool_input={'dispatch_id': named} if named else {}),
                    task, unlaunched[0].get('stage'), role, reason)
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return  # the refusal must still be enforced when its receipt cannot be written


def guard(event):
    from hooklib import project_root, block
    root = project_root(event)
    transport = event.get("_qa_host") or {}
    from host_adapter import tool_short_name
    name = tool_short_name(transport.get("name") or event.get("tool_name"))
    ti = transport.get("input") or event.get("tool_input") or {}
    if name == 'spawn_agent':
        from host_adapter import native_role
        from stage_guard import requested_ticket
        role = native_role(ti.get('agent_type') or ti.get('task_name'))
        task = requested_ticket(event)
        if task and role.startswith('qa-'):
            from host_capabilities import inspect
            if not inspect(root).get('story_ready'):
                reason = ('FACTORY HOST: essential native guard/context behavior is unverified. '
                          'Run the doctor host probes before starting a story worker.')
                try:
                    note_unlaunched_denial(root, event, task, role, reason)
                finally:
                    block(reason)  # the refusal holds whatever the note does (RecursionError, a half-installed plugin)
        blocking = [b for b in bindings(root) if task and b.get('task_id') == task
                    and b.get('agent_type') == role and binding_is_active(root, b, event)]
        if blocking:
            block('WORKER LIFECYCLE: an active factory worker already owns this task/role; wait or resume it, '
                  'do not spawn a duplicate. ' + _blocking_text(blocking, root, task, event))
    stopping = name in {"interrupt_agent", "close_agent"} or (name == "send_input" and ti.get("interrupt"))
    if not stopping:
        return
    target = ti.get("target") or ti.get("id")
    from host_dispatch import receipt_files
    from hooklib import artifacts_dir
    # EVERY receipt that answers to the target is judged, not the first one: a `terminal` receipt of a
    # finished worker with the same name no longer lets a LIVE one be stopped (CX1-9, E17).
    for _, binding in receipt_files(root):
        if not _answers_to_stop(target, binding) or binding.get("status") == "terminal":
            continue
        task, dispatch = binding.get("task_id"), binding.get("dispatch_id")
        try:
            state = json.loads((artifacts_dir(task, event) / "state/controller.json").read_text(encoding="utf-8")) if task else {}
            allowed = state.get("dispatches", {}).get(dispatch, {}).get("cancellation")
        except (OSError, ValueError, AttributeError, TypeError):   # a state we cannot read allows nothing
            allowed = None
        if not allowed:
            block("WORKER LIFECYCLE: stop denied. Continue waiting for the active factory worker; "
                  "5/15/30+ minutes and a missing digest are not failure. Record request_cancel with "
                  "a verified cause and evidence before cancelling. Do not launch a duplicate.")


def _answers_to_stop(target, binding) -> bool:
    """Whether a stop of `target` is about this receipt - the reading of names is `host_dispatch.binding_names`.

    The error direction of a STOP is the opposite of a resume's (CX1-9, B-2): a resume that misses a
    receipt is refused, a stop that misses one is ALLOWED with no recorded cancellation. So the stop reads
    wide: the target itself OR its last component (`/root/qa_x` and `qa_x` address one agent, and a
    SubagentStart receipt holds only the bare name), exactly what the comparison always read; and a target
    that names nobody (empty, not a string) could stop anyone, so every receipt answers to it."""
    if not isinstance(target, str) or not target.strip():
        return True
    from host_dispatch import binding_names
    names = binding_names(binding)
    return target in names or target.rsplit('/', 1)[-1] in names


def active_binding(root, dispatch_id, task=None, now=None):
    """The non-terminal receipt of a dispatch. Dispatch ids repeat across stories (two stories
    both reach `S5-qa-automator-12`), so with `task` given a receipt counts only for the story
    it names; one that names no story is not this story's. Without `task`, any story's.

    A story_step receipt whose worker the host itself recorded as ended (a Codex rollout's completion for its
    exact path and this launch, a Claude Code transcript ending with the host's acknowledged handback once the
    stop hooks let it go - `_natively_returned`) is not an active worker: TP2-2406 S4, 13.10.2026 - the
    completed-but-unaccepted worker's receipt stayed `running` and refused the controller's checkpoint; OH3-16 -
    the same for a critic that handed back, so its reject could not be paused without a person's word. The
    receipt is not written; a rollout or transcript still being written, an abort or interrupt, no record or a
    failing reader keep it active as before. `now` defaults to the clock, read inside the helper for each receipt
    (the controller calls without it); the host's records are read once per call.

    A receipt whose dispatch the controller itself no longer holds `running` (accepted, superseded, released) is not
    an active worker either, by the one reader the spawn guard already uses (`binding_is_active`): its receipt stays
    `running` on a host whose stop hook never marks it terminal, and the checkpoint veto kept
    treating a dispatch the controller had settled as a worker still at work. Every doubt that reader has (no
    story, no controller, no status) keeps the receipt active, as before."""
    held = {}
    return next((b for b in bindings(root) if b.get("dispatch_id") == dispatch_id
                 and b.get("status") != "terminal"
                 and (task is None or b.get("task_id") == task)
                 and binding_is_active(root, b)
                 and not _natively_returned(root, b, now, held)), None)
