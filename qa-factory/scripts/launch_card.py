"""The launch card of a dispatch: the one text an orchestrator needs to start the role, kept on disk.

On Codex Desktop the only carrier of the spawn call was the stdout of `story_step.py start`, printed at
the very END of a command that runs 34-112 s, while the orchestrator's exec cell yields after about 30 s
(TP2-2406, 12.10: S2 was dispatched three times and launched once). The card is lost with the cell,
the orchestrator asks `next`, and `next` had no "launch" action: a dispatch is `running` from the moment
the controller records it, a host receipt exists only after the spawn, and a host with no transcript
inventory answers `wait_existing_job` / `unknown` for work nobody has started.

This module is the ONE implementation `story_step.py start`, `story_step.py where` and
`Controller.next_action` share:

  render(...)          the block `start` prints and writes - one text, never two renderings
  write(...)           the card as a file next to the brief, replaced atomically
  launch_evidence(...) every reason a dispatch is NOT provably unlaunched (empty = never launched);
                       the denial rows come from the controller's own reader, as `extra_evidence`
  desktop_story(...)   a story the orchestrator runs by hand: the only kind that gets a `launch` action
  launch_action(...)   `launch` / `wait_start` for a running dispatch with no evidence of a launch, else None
  materialize_door(...) the command that writes brief, form and card for a packet committed outside `start`
  outside_start(...)   the ONE predicate "this packet was committed outside `start`" (the record lacks the field
                       `start` stamps), so only such a packet is sent to `materialize_door`

Nothing here decides for a person and nothing here writes except `write`: the readers are pure (P1, FR-48).
"""
import json
import os
import time
from pathlib import Path

import dispatch_liveness
import person_words
import worker_lifecycle

# The one definition of the variable the driver exports to every child it starts. `story_step` takes it
# from here (a second spelling would let the two readers of "who runs this story" disagree).
RUN_MODE_ENV = "QA_FACTORY_RUN_MODE"
DESKTOP = "desktop"
CARD_REL = "work/briefs/{dispatch_id}.launch.md"
# The field `story_step start` adds to the request it commits (the sha of config.json at start). It lives HERE
# because the predicate below reads it and `story_step` imports this module, not the other way round (FR-37).
CONFIG_START_FIELD = "config_sha256_at_start"


def card_path(task_root, dispatch_id) -> Path:
    return Path(task_root) / CARD_REL.format(dispatch_id=dispatch_id)


def card_rel(task, dispatch_id) -> str:
    """The project-relative path, the spelling every other path of a prompt has."""
    return f"qa-factory/artifacts/{task}/" + CARD_REL.format(dispatch_id=dispatch_id)


def materialize_door(task, dispatch_id) -> str:
    """The command that writes the brief, the handover form and this card for a dispatch the controller
    committed outside `start` (a `--operation rework` packet): bare words, like the `bind` line of `render`.
    One spelling for every text that names it (TP2-2406 S3-3, 15.10.2026: `wait_start` said "ask again"
    for a packet no `start` would ever write)."""
    return f"story_step.py materialize --task {task} --dispatch-id {dispatch_id}"


def outside_start(record) -> bool:
    """True when this dispatch record was committed outside `start`: it lacks the field `start` stamps into
    every request it commits. INVARIANT (the error direction): a record `start` is still writing the files of
    carries the field from the moment it is committed, so `start` at work is never sent to `materialize`
    (a conductor that launched the S5 critic before the settle would be the cost); a record that is not an
    object, or whose field holds anything but null, counts as `start`'s - the cost of that error is a door
    left unnamed, never a wrong one."""
    return isinstance(record, dict) and record.get(CONFIG_START_FIELD) is None


def render(task, role, dispatch_id, prompt, door="") -> str:
    """The block, from the prompt line through the `finish` line, ending in a newline. `door` is the S5
    critic's extra `finish` words (a window it could not close). `start` prints exactly this text and
    writes exactly this text."""
    return (f"--- Agent prompt, verbatim; subagent_type: {role} ---\n{prompt}\n"
            # the PREFIX is read by story_run.parse_prompt (it ends the prompt block): never reword it (SC2-38, F-3)
            f"--- the moment the Agent call returns an id: on Claude the plugin's hook binds it; by hand only on Codex "
            f"or when the guard or `where` says unbound: story_step.py bind --task {task} "
            f"--dispatch-id {dispatch_id} --agent-id <id> ---\n"
            f"--- after the digest: story_step.py finish --task {task} --dispatch-id {dispatch_id} "
            f'--digest "<digest>"{door} ---\n')


def write(task_root, dispatch_id, text) -> Path:
    """The card as a file: a temporary file in the same folder, then `os.replace`, so a reader sees the
    whole card or no card. UTF-8 with plain newlines, the bytes `start` prints."""
    path = card_path(task_root, dispatch_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
    try:
        tmp.write_bytes(text.encode("utf-8"))
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)
    return path


def _unbound_evidence(row, role, task, began):
    """A receipt of this story and role that names NO dispatch (`host_dispatch.record` leaves the id empty
    unless exactly one dispatch of the role is running): it may be the launch of this one. A non-terminal
    one always counts; a terminal one counts unless it is PROVEN older than this dispatch - the time rule
    is `dispatch_liveness._may_be_this_dispatch`'s (the status is judged here, so it is handed neutral).
    Returns the evidence line, naming the receipt, or None."""
    terminal = str(row.get("status") or "") == "terminal"
    if terminal and not dispatch_liveness._may_be_this_dispatch(dict(row, status=""), role, task, began):
        return None
    name = row.get("agent_id") or row.get("task_path") or "-"
    return (f"a {'terminal' if terminal else 'running'} host receipt of this story and role (agent {name}) "
            "names no dispatch, so it may be this one's")


def _receipt_evidence(project_root, task, dispatch) -> list:
    """Receipts of `state/host-dispatches/` of this story, of ANY status: one naming this dispatch means
    the role ran; one naming none (`_unbound_evidence`) may be this one's. The reader is
    `worker_lifecycle.bindings`, which skips a file it cannot parse without saying so - so the files on
    disk are counted against the records it yielded, and a difference is evidence of its own (an unknown
    never becomes a launch: FR-41, FR-59). A receipt with no `task_id` is of no story: it is neither
    evidence here nor input of `worker_lifecycle.guard`, which filters by task."""
    identifier, role = str(dispatch.get("id") or ""), str(dispatch.get("role") or "")
    began = dispatch_liveness._started_at(dispatch)
    found = []
    directory = Path(project_root) / "qa-factory" / "state" / "host-dispatches"
    try:
        on_disk = len(list(directory.glob("*.json")))
        rows = list(worker_lifecycle.bindings(project_root))
    except OSError as exc:
        return [f"could not read {directory}: {type(exc).__name__}"]
    for row in rows:
        if not isinstance(row, dict):
            found.append("a host receipt is not a JSON object, so it cannot be ruled out")
            continue
        if str(row.get("task_id") or "") != task:
            continue
        named = str(row.get("dispatch_id") or "")
        if named == identifier and named:
            found.append(f"a host receipt names this dispatch (agent {row.get('agent_id') or '-'}, "
                         f"status {row.get('status') or '-'})")
        elif not named and str(row.get("agent_type") or "") == role:
            line = _unbound_evidence(row, role, task, began)
            if line:
                found.append(line)
    if on_disk > len(rows):
        found.append(f"{on_disk - len(rows)} file(s) in {directory} could not be read as a receipt, so "
                     "none of them can be ruled out")
    return found


def launch_evidence(project_root, task, dispatch, extra_evidence=()) -> list:
    """Every reason this dispatch is NOT provably unlaunched, in the reader's words. Empty = this host's
    own records show no launch. Each of these alone forbids a `launch` action: an agent id on the
    record, a host receipt of any status (naming the dispatch, or naming none: `_receipt_evidence`), a
    return mark, a record that cannot be read - and whatever the CALLER already knows: the denial rows
    belong to the controller's one reader (`Controller._denial_times`), which attributes a row that names
    no dispatch by role, stage and time; this module keeps no second reader of that file."""
    dispatch = dispatch if isinstance(dispatch, dict) else {}
    found = []
    if dispatch.get("agent_id"):
        found.append(f"the dispatch record carries agent_id {dispatch['agent_id']}")
    for key in ("returned_at", "returned_digest"):
        if dispatch.get(key):
            found.append(f"the dispatch record carries {key}")
    return found + _receipt_evidence(project_root, str(task), dispatch) + [str(x) for x in extra_evidence]


def desktop_story(task_root) -> bool:
    """The orchestrator runs this story by hand: `pipeline.json` stamps `run_mode.mode` as `desktop` and
    this process is not the driver's (which exports the variable). A story with no stamp, a stamp that is
    not an object, a pipeline that cannot be read: not a desktop story - the old answers stand."""
    if os.environ.get(RUN_MODE_ENV, "").strip():
        return False
    try:
        pipeline = json.loads((Path(task_root) / "pipeline.json").read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return False
    stamp = pipeline.get("run_mode") if isinstance(pipeline, dict) else None
    return isinstance(stamp, dict) and str(stamp.get("mode") or "").strip() == DESKTOP


def release_door(task_root, dispatch_id) -> str:
    """The person's door out of a dispatch nobody is doing: the one string `wait_existing_job` and
    `wait_start` both carry."""
    return person_words.door(f"controller.py --task-root {task_root} --operation release "
                             f"--dispatch {dispatch_id}")


def _age(dispatch, now):
    """Seconds since the dispatch was recorded, or None: no usable start, or one ahead of the clock."""
    began = dispatch_liveness._started_at(dispatch)
    if began is None or began > now:
        return None
    return round(now - began, 1)


def launch_action(project_root, task, task_root, dispatch, now=None, extra_evidence=()):
    """`launch` / `wait_start` for a running dispatch of a desktop story that nothing shows launched;
    None otherwise (the caller's own answer stands). Pure: reads, writes nothing, never raises on a
    record that lacks its parts. `extra_evidence` is what the caller already knows forbids a launch (the
    controller's denial rows); it is added to the evidence, never read from a file here. No project
    (`project_root` None) means the host's records cannot be located, so nothing is proved: None. The
    card file's existence is what separates the two answers: `start` writes it LAST, after the brief and
    the handover form, so a card on disk means those steps are over."""
    if project_root is None or not isinstance(dispatch, dict) or dispatch.get("status") != "running":
        return None
    identifier, stage, role = (str(dispatch.get(key) or "") for key in ("id", "stage", "role"))
    if not (identifier and stage and role) or not desktop_story(task_root):
        return None
    if launch_evidence(project_root, task, dispatch, extra_evidence):
        return None
    card = card_rel(task, identifier)
    if card_path(task_root, identifier).is_file():
        return {"action": "launch", "dispatch_id": identifier, "stage": stage, "role": role,
                "subagent_type": role, "card": card,
                "bind": f"story_step.py bind --task {task} --dispatch-id {identifier} --agent-id <id>",
                "reason": "no agent id, receipt, return or denial names this dispatch; the host never "
                          "launched it; spawn the Agent call in the card, then bind"}
    if outside_start(dispatch):
        # No `start` runs for this packet, so it is not told to ask again about one (FR-10): the files come from
        # the door, and the person's word frees a packet nothing will write.
        reason = ("no `start` ran for this dispatch (a packet committed outside `start`): its brief, handover "
                  f"form and card come from: {materialize_door(task, identifier)}; if nothing will write them, "
                  "the person's word frees it: release")
    else:
        reason = ("the card is not written yet: `start` writes it last, after the brief and the handover "
                  "form, so ask again while `start` runs; if `start` is no longer running, or none ever "
                  "ran for this dispatch (a rework packet), the person's word frees it: release")
    return {"action": "wait_start", "dispatch_id": identifier, "stage": stage, "role": role, "card": card,
            "age_s": _age(dispatch, time.time() if now is None else float(now)),
            "reason": reason,
            "rebuild": f"story_step.py where --task {task}",
            "release": release_door(task_root, identifier)}
