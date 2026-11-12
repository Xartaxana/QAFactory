"""Bind real child identities to a recorded factory dispatch after native spawn."""
import hashlib
import json
import time
from pathlib import Path
from event_store import atomic_json
from hooklib import read_json, sorted_paths


def binding_path(root, agent):
    return Path(root) / "qa-factory/state/host-dispatches" / (hashlib.sha256(str(agent).encode()).hexdigest() + ".json")


def controller_record(root, ticket, dispatch):
    """The story controller's record of `dispatch` (a dict), or None: the ONE strict reader of it for the two hooks that
    act on a running dispatch (`agent_autobind`, `conductor_stop`; F-10). Every doubt is None: no ticket or dispatch, a
    ticket that is not one path component, no folder, no record, a record that is no object. The reader the lifecycle
    uses (`worker_lifecycle.binding_is_active`) answers True on every doubt - the wrong direction for a hook that moves."""
    import hooklib
    ticket, dispatch = str(ticket or ""), str(dispatch or "")
    if not ticket or not dispatch or ticket in (".", "..") or any(char in ticket for char in "/\\:"):
        return None
    state = read_json(hooklib.artifact_root(root=root) / ticket / "state" / "controller.json", {}, kind=dict, errors=Exception)
    records = state.get("dispatches")
    record = records.get(dispatch) if isinstance(records, dict) else None
    return record if isinstance(record, dict) else None


def binding_names(binding) -> set:
    """Every name a receipt answers to: its `agent_id`, `task_path` and `task_name`, and the last
    `/`-component of the first two when they carry a `/`. The host addresses one agent as
    `/root/<name>` or as `<name>` (both succeed), and `story_step bind` records the path only, so a
    recipient is matched against this set and never against one spelling. A target holding a `/`
    can match a full form only: a basename has no `/`. A value that is not a non-empty string
    (a list, a number, None) names nothing and is skipped, and so is a receipt that is no object:
    a well-formed JSON receipt with an odd value must not fail the scan of every other receipt.

    THE one reader of receipt names (CX1-9, I-1): every comparison of a recipient or an identity
    with a receipt goes through it. What the CALLER does with a match is the caller's policy, and
    the two callers differ on purpose: a resume (`stage_guard.check_resume`) matches the target
    itself only, so a missed match is a refusal; a stop (`worker_lifecycle.guard`) matches the
    target OR its last component, so a missed match is not a stop allowed without a cancellation.
    The one deliberate exception is `record`'s SubagentStop skip below: a child's stop must never
    mark a `story_step` receipt terminal, so it compares `agent_id` and `task_path` only."""
    names = set()
    if not isinstance(binding, dict):
        return names
    for key in ('agent_id', 'task_path', 'task_name'):
        value = binding.get(key)
        if not isinstance(value, str) or not value:
            continue
        names.add(value)
        if key != 'task_name' and '/' in value:
            names.add(value.rsplit('/', 1)[1])
    names.discard('')
    return names


def _number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def bound_dispatches(receipt) -> list:
    """THE reader of a receipt's `bound_dispatches`: `[{"task_id", "dispatch_id", "bound_at"}]`, the dispatches
    `story_step bind` tied to this host agent, in the order of their first binding (DC1-11, run 14857: four
    `S6-qa-runner-1..4` dispatches ran as messages to ONE agent, and the receipt, one per agent, kept only the last
    `dispatch_id`; the scalar stays the LAST binding so every reader of it answers as before).

    It feeds a sentence (`turn_budget.message`), never a gate, so its error direction is DOWN: it may undercount, it
    never overcounts and never raises. A receipt with no list (written before this field, or by `host_dispatch.record`)
    answers with its scalar `dispatch_id` as one element; a list element that is no object or holds no non-empty string
    `dispatch_id` is dropped; a receipt that is no object answers `[]`. `bound_at` that is no number is 0."""
    if not isinstance(receipt, dict):
        return []
    field = receipt.get("bound_dispatches")
    if not isinstance(field, list):
        field = [{"task_id": receipt.get("task_id"), "dispatch_id": receipt.get("dispatch_id"),
                  "bound_at": receipt.get("bound_at")}]
    found = []
    for item in field:
        if not isinstance(item, dict):
            continue
        dispatch, task = item.get("dispatch_id"), item.get("task_id")
        if isinstance(dispatch, str) and dispatch:
            found.append({"task_id": task if isinstance(task, str) else "", "dispatch_id": dispatch,
                          "bound_at": item["bound_at"] if _number(item.get("bound_at")) else 0})
    return found


def with_bound_dispatch(existing, task, dispatch, bound_at) -> list:
    """The list a receipt carries after `bind` of `dispatch` of `task`: what `existing` (the receipt as it is now, or
    any junk) already holds plus the new pair. A pair (`task_id`, `dispatch_id`) already there is not added twice and
    keeps its first `bound_at`: the same `bind` run again must not grow the dispatch count a role is told. Dispatch ids
    repeat across stories (`S5-qa-automator-12` in two), so the pair is the identity, never the id. Pure."""
    held = bound_dispatches(existing)
    if not isinstance(dispatch, str) or not dispatch:
        return held
    task = task if isinstance(task, str) else ""
    if any(item["task_id"] == task and item["dispatch_id"] == dispatch for item in held):
        return held
    return held + [{"task_id": task, "dispatch_id": dispatch, "bound_at": bound_at if _number(bound_at) else 0}]


def receipt_files(root) -> list:
    """THE scanner of the receipt directory: `[(path, receipt)]` in `hooklib.sorted_paths` order. A file that is
    not JSON, not an object or empty names nothing and is left out, never raised: no receipt of the directory
    can fail the reading of another (the read is `hooklib.read_json`, ax. 16). Other readers of the directory
    (`worker_lifecycle.bindings`, `dispatch_liveness.host_bindings`, `story_step._release_binding`, the
    `tool_use_id` scan of `record`) are queued to converge here (CX2-10), not folded by CX1-9."""
    found = []
    for path in sorted_paths((Path(root) / 'qa-factory/state/host-dispatches').glob('*.json')):
        data = read_json(path, {}, kind=dict, errors=Exception)
        if data:
            found.append((path, data))
    return found


def matching_binding_paths(root, identity) -> list:
    """Every receipt that answers to `identity`. The receipt hashed by the identity itself - the one a
    literally recorded identity (a bare `--agent-id qa_x` included) wrote - is the exact one and answers
    alone; otherwise every receipt of the directory whose `binding_names` hold the identity, in sorted file
    order. A name nobody holds, an empty or a non-string identity: no receipt."""
    if not isinstance(identity, str) or not identity:
        return []
    direct = binding_path(root, identity)
    if direct.is_file():
        return [direct]
    return [path for path, data in receipt_files(root) if identity in binding_names(data)]


def resolve_binding_path(root, identity):
    """The ONE receipt that answers to `identity`: the exact file, else the only match, else the (absent)
    direct path. Two or more matches answer none: a name two stories both hold must not be read as
    whichever file sorts first (FR-59), and `enrich` names no story on it."""
    found = matching_binding_paths(root, identity)
    return found[0] if len(found) == 1 else binding_path(root, identity)


def child_identity(event):
    """Resolve path-only native spawn responses from the child's own host metadata."""
    from host_adapter import is_codex
    if not is_codex(event):
        return {}  # Never scan an unrelated Claude transcript for Codex metadata.
    wanted = event.get('agent_id') or event.get('session_id')
    transcript = event.get('agent_transcript_path') or event.get('transcript_path')
    if not wanted or not transcript:
        return {}
    try:
        with Path(transcript).open(encoding='utf-8') as handle:
            for line in handle:
                row = json.loads(line)
                meta = row.get('payload') or {}
                if row.get('type') == 'session_meta' and meta.get('id') == wanted:
                    source = meta.get('source') if isinstance(meta.get('source'), dict) else {}
                    spawn = (source.get('subagent') or {}).get('thread_spawn') or {}
                    return {'agent_id': wanted, 'task_path': meta.get('agent_path') or spawn.get('agent_path'),
                            'parent_session_id': meta.get('parent_thread_id') or spawn.get('parent_thread_id')}
    except (OSError, ValueError):
        pass
    return {}


def _bound_candidate(root, meta):
    """The record of the child's EXACT agent path that names its story, or None.

    TP2-2406 S3 (12.10) / S4 (13.10): the SubagentStop of a story_step-bound Codex Desktop child ran the
    exit gate as unknown-task, and another story's bugs blocked it, because this record was refused for a session
    id a CLI cannot know: `story_step bind` writes it under the child's exact agent path with `bound_by:
    story_step` and no `parent_session_id`. That record is the factory's own dispatch of this very path, so it
    names the story; it is READ, never rewritten. Why: `record`'s SubagentStop skip (`identity not in {agent_id,
    task_path}`) needs the path to stay in `agent_id`, so a child's stop never marks it terminal - only
    `story_step finish` does. A `terminal` record is a dispatch that has finished: a later launch under the same
    path is not it, and the record names nothing. A session id, when the record carries one, must be the child's
    parent's; a different one, a spawn-time record with no session id, a file that is not a JSON object (the
    read is `read_json`, which never raises: a broken record is no record) and a path with no record name no
    story. A spawn-time record keeps the rule it had: the same session, and the thread id is stamped into it
    (a stamp that cannot be written leaves the record as it was; it still names the story)."""
    from hooklib import read_json
    task_path = meta.get('task_path')
    candidate = binding_path(root, task_path) if task_path else None
    bound = read_json(candidate, default={}, kind=dict) if candidate else {}
    if not bound:
        return None
    session = bound.get('parent_session_id')
    if bound.get('bound_by') == 'story_step':
        if bound.get('status') != 'terminal' and session in (None, '', meta.get('parent_session_id')):
            return candidate
        return None
    if session == meta.get('parent_session_id'):
        bound['agent_id'] = meta['agent_id']
        try:
            atomic_json(candidate, bound)
        except OSError:
            pass   # the stamp is a convenience: the record stays as it was (unstamped) and still names the story
        return candidate
    return None


def enrich(event):
    from hooklib import project_root, read_json
    root = project_root(event)
    for identity in (event.get("agent_id"), event.get("session_id")):
        if not identity:
            continue
        try:
            path = resolve_binding_path(root, identity)
        except Exception:   # a read-only scan: whatever fails in it names no story (defence in depth)
            # The scan used to open every receipt of the directory with `json.loads`: ONE broken receipt
            # anywhere raised out of `enrich`, `hooklib.read_event` answered None and the exit gate left with
            # exit 0 for every stop (a silent pass). CX1-9 made the scan itself safe (`receipt_files` reads
            # through `read_json`, which never raises on a file's content), so this `except` is only the
            # second line: whatever else fails still names no story. A name two receipts hold names none
            # either (`resolve_binding_path`: exact file, else exactly one match).
            path = binding_path(root, identity)
        if not path.is_file():
            try:
                meta = child_identity(event)
            except Exception:   # a rollout line that is JSON but no object (a list, a string): `child_identity`
                meta = {}       # catches only OSError and ValueError, and this read must never raise (see above)
            path = _bound_candidate(root, meta) or path
        data = read_json(path, default={}, kind=dict) if path.is_file() else {}
        if data:
            for key in ("task_id", "dispatch_id", "agent_type", "activity_id", "factory_diagnostic"):
                if data.get(key) and isinstance(data[key], str):
                    event[key] = data[key]
            event["host_binding"] = str(path)
            break
    return event


def record(event):
    from hooklib import project_root, artifacts_dir, role_name, is_one_component
    from stage_guard import resolve_ticket
    if event.get("hook_event_name") == "SubagentStop":
        from host_probe import check_child, check_role_context
        check_child(project_root(event), event)
        check_role_context(project_root(event), event)   # evidence of a real dispatch's context (HF8-12, W-5); never raises
        if not event.get('_exit_gate_released'):
            return  # an exit hook may still reject completion; do not race it
        for identity in (event.get("agent_id"), event.get("session_id")):
            path = Path(event['host_binding']) if event.get('host_binding') else binding_path(project_root(event), identity)
            if identity and path.is_file():
                receipt = json.loads(path.read_text(encoding="utf-8"))
                if identity not in {receipt.get('agent_id'), receipt.get('task_path')}:
                    continue
                receipt.update(status="terminal", terminal_source="SubagentStop")
                atomic_json(path, receipt)
        return
    if event.get("tool_name") != "Agent":
        return
    role = role_name((event.get("tool_input") or {}).get("subagent_type"))
    from inject_context import load_map
    if role not in load_map().get("roles", {}):
        return
    response = event.get("tool_response") or {}
    if isinstance(response, str):
        try: response = json.loads(response)
        except ValueError: return
    if isinstance(response, dict) and isinstance(response.get('structuredContent'), dict):
        response = response['structuredContent']
    if not isinstance(response, dict):
        return
    from host_adapter import launch_id_of      # the ONE reader of the launch-id keys (a data row, RN1-1)
    launch_id = launch_id_of(response)
    agent = launch_id or response.get('task_path') or response.get('task_name')
    if not agent:
        from host_probe import note_no_launch_id
        note_no_launch_id(project_root(event), event)   # the probe of THIS call stays unverified, and says why
        return
    for existing in sorted_paths((project_root(event)/'qa-factory/state/host-dispatches').glob('*.json')):
        bound = json.loads(existing.read_text(encoding='utf-8'))
        if event.get('tool_use_id') and bound.get('tool_use_id') == event['tool_use_id'] and bound.get('parent_session_id') == event.get('session_id'):
            # SubagentStart can bind the UUID before spawn returns its path-only result.
            returned_path = response.get('task_path') or response.get('task_name')
            if returned_path and str(returned_path).startswith('/'):
                bound['task_path'] = returned_path
            if launch_id:
                bound['agent_id'] = agent
                from host_probe import bind_injection
                if bind_injection(project_root(event),event,agent):
                    bound['factory_diagnostic'] = 'context_probe'
            atomic_json(existing,bound)
            return
    from host_probe import bind_injection
    diagnostic = bind_injection(project_root(event), event, agent)
    task, facts = resolve_ticket(event)
    if not task and facts.get("exploration"):
        # An exploration has no story: its receipt carries the exploration identity (`explore:<slug>`), which `enrich`
        # copies into the child's events, so its stop is attributed to it and to no story (XT1-2).
        import exploration
        task = exploration.task_id(facts["exploration"])
    raw_input = (event.get('_qa_host') or {}).get('input') or {}
    receipt = {"agent_id": agent, "agent_type": role, "task_id": task, "status": "running",
               "factory_diagnostic": "context_probe" if diagnostic else None,
               "task_name": raw_input.get('task_name'),
               "task_path": response.get('task_path') or response.get('task_name') or
                            ('/root/' + raw_input['task_name'] if raw_input.get('task_name') else None),
               "parent_session_id": event.get("session_id"), "dispatch_id": None,
               "tool_use_id": event.get("tool_use_id"), "host": "codex",
               # The launch, set here once and by nobody after: the file's mtime is the LAST
               # write (a rebind, the terminal mark), so only this says how old a launch is.
               "bound_at": time.time()}
    from activity_capture import activity_path, load
    session = event.get('session_id')
    if session:
        doc = load(activity_path(event, session), session)
        active = next((a for a in doc.get('activities',[]) if doc.get('active_stack') and a['activity_id']==doc['active_stack'][-1]), {})
        receipt['activity'] = active
        receipt['activity_id'] = active.get('activity_id')
    if task and is_one_component(task):     # an `explore:<slug>` id is no story folder: the receipt is still written below
        path = artifacts_dir(task, event) / "state/controller.json"
        if path.is_file():
            state = json.loads(path.read_text(encoding="utf-8"))
            matches = [d for d in state.get("dispatches", {}).values()
                       if d.get("role") == role and d.get("status") == "running"]
            if len(matches) == 1:
                receipt["dispatch_id"] = matches[0]["id"]
    atomic_json(binding_path(project_root(event), agent), receipt)


def main():
    from hooklib import read_event, project_root
    event = read_event() or {}
    if (project_root(event) / "qa-factory/config.json").is_file():
        record(event)


if __name__ == "__main__":
    main()
