#!/usr/bin/env python3
"""PostToolUse hook on `Agent|Task` (Claude): bind the agent the conductor has just launched to its dispatch (SC2-38 item 1).

The conductor of run 12586 made 62 `story_step` calls for 24 `Agent` calls: after every launch it ran `story_step.py
bind` by hand, because the agent's id exists only AFTER the host has spawned it. The host's own answer to the `Agent`
call carries that id (measured, N0 of r0107-s3b2: `tool_response.agentId`, foreground and background alike), and the
prompt `story_step.py start` composed names the dispatch (`You are <role>. Ticket: <T>. Dispatch: <id>.`). This hook joins
the two and runs the ONE writer of the receipt, `story_step.py bind`, exactly as the driver does (`story_run`): there is
no second writer of `state/host-dispatches/` and no second way to record a binding (AR-14).

THE RULE OF THE HOOK: it never guesses; a wrong binding is worse than none (FR-16). It binds only when every one of these
holds, and otherwise exits 0 having written nothing, leaving the conductor's own `bind` as the door (the card and the
guard's refusal still name it):
  - the host is not Codex (its receipts come from `host_dispatch.py`, AR-5), the project is onboarded, the tool is the
    launch of a role the factory knows (`inject-map.json`);
  - the response is an object that names the agent under a key of the row `launch_id_keys` with a plain id (a string response, no id, a path,
    an error: nothing);
  - the FIRST line of the prompt is exactly the `_prompt` form, its role is the launched role, and the prompt holds ONE
    dispatch id (two ids: nothing);
  - the controller's record of that dispatch exists, is `running` and is of that role (a closed, foreign or missing
    dispatch is never "washed" into a binding), and this agent's receipt does not yet hold the pair (idempotent: a bind
    the conductor made first leaves one entry and does not move `bound_at`).
A `bind` that is refused, crashes or times out is ONE `hook_signal` line and exit 0: the role is never stopped for it.

The reader of the id in the prompt is `hooklib._SUBAGENT_DISPATCH_RE` (the same regex `subagent_meta` and the liveness
use); the reader of the id in the response is `agent_id_of` below, which reads the key through `host_adapter.launch_id_of` (the row `launch_id_keys` of
`references/host-report-forms.json`: the one place the field's name is written, shared with `host_dispatch.record`).
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

TOOL_NAMES = ("Agent", "Task")     # the payload says `Agent`; the host's init list says `Task` (N0): both are the launch
BIND_TIMEOUT_S = 120               # `bind` runs `stage_done`, which refreshes the dashboard; the hook is synchronous
# The first line of `story_step._prompt`, whole. The dispatch id may hold dots (`_SAFE_ID`); the line's own last dot is not its.
FIRST_LINE_RE = re.compile(r"You are ([\w-]+)\. Ticket: ([\w-]+)\. Dispatch: ([\w\-]+(?:\.[\w\-]+)*)\.")
_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_\-]*")      # a bare host id; a path or a name with a slash is not one


def agent_id_of(response):
    """The agent id the host's answer to `Agent` names, or None. The key is read by `host_adapter.launch_id_of` (measured by
    N0, `tool_response.agentId`, both run modes; the row is data): a response that is a string (the host sent it as text), no
    object, with no such key, or an id that is not a plain token names nothing. A row that cannot be read raises."""
    from host_adapter import launch_id_of
    value = launch_id_of(response)
    return value if value is not None and _ID_RE.fullmatch(value) else None


def prompt_of(event):
    """`(role, ticket, dispatch)` from the first line of the launch prompt, or None. Exactly the `_prompt` form, and ONE
    dispatch id in the whole text: a prompt that names two is a prompt this hook cannot attribute."""
    import hooklib
    tool_input = event.get("tool_input")
    text = tool_input.get("prompt") if isinstance(tool_input, dict) else None
    if not isinstance(text, str) or not text.strip():
        return None
    first = FIRST_LINE_RE.fullmatch(text.strip().splitlines()[0].strip())
    if not first:
        return None
    role, ticket, dispatch = first.groups()
    if hooklib._SUBAGENT_DISPATCH_RE.findall(text) != [dispatch]:
        return None
    return role, ticket, dispatch


def _record_matches(root, ticket, dispatch, role) -> bool:
    """True ONLY when the story's controller holds this dispatch as `running` and of this role. Every doubt is False."""
    from host_dispatch import controller_record
    record = controller_record(root, ticket, dispatch)
    return record is not None and record.get("status") == "running" and record.get("role") == role


def plan(event, root):
    """`(ticket, dispatch, agent id)` to bind, or None. See the module text for every condition; None writes nothing."""
    import hooklib
    import host_adapter
    from host_dispatch import binding_path, bound_dispatches
    from inject_context import load_map
    if not isinstance(event, dict) or event.get("tool_name") not in TOOL_NAMES or host_adapter.is_codex(event):
        return None
    if not (root / "qa-factory" / "config.json").is_file():
        return None
    tool_input = event.get("tool_input")
    role = hooklib.role_name(tool_input.get("subagent_type") if isinstance(tool_input, dict) else "")
    if not role or role not in (load_map().get("roles") or {}):
        return None
    agent = agent_id_of(event.get("tool_response"))
    found = prompt_of(event)
    if agent is None or found is None or found[0] != role:
        return None
    _, ticket, dispatch = found
    if not _record_matches(root, ticket, dispatch, role):
        return None
    receipt = hooklib.read_json(binding_path(root, agent), {}, kind=dict, errors=Exception)
    if any(item["task_id"] == ticket and item["dispatch_id"] == dispatch for item in bound_dispatches(receipt)):
        return None                    # the conductor (or an earlier launch of this hook) already bound it: one entry, no move
    return ticket, dispatch, agent


def bind(root, ticket, dispatch, agent):
    """Run `story_step.py bind` as the driver does. `(exit code, last line of its answer)`; a crash or a timeout is code -1."""
    try:
        done = subprocess.run([sys.executable, "-B", str(HERE / "story_step.py"), "bind", "--task", ticket,
                               "--dispatch-id", dispatch, "--agent-id", agent], capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=BIND_TIMEOUT_S, cwd=str(root),
                              env=dict(os.environ, CLAUDE_PROJECT_DIR=str(root)))
    except Exception as exc:  # noqa: BLE001 - a launch that did not run or timed out is a failed bind, never a stopped role
        return -1, f"{type(exc).__name__}"
    lines = [line for line in (done.stdout or done.stderr or "").strip().splitlines() if line.strip()]
    return done.returncode, (lines[-1] if lines else "no output")


def note_probe(event, root) -> None:
    """The doctor's probe child is launched through this same hook (FR-17): bind its proof to the id the host's answer
    names, or record that it names none (`host_probe.note_probe_launch`, the Claude path; Codex does it in `host_dispatch`).
    Runs BEFORE the story filters of `plan` (the probe prompt is no story prompt) and writes only into the proof of THIS
    call's `tool_use_id`: every other launch writes nothing. Never stops the hook: the bind below is independent of it."""
    import host_adapter
    if not isinstance(event, dict) or event.get("tool_name") not in TOOL_NAMES or host_adapter.is_codex(event):
        return
    try:
        from host_probe import note_probe_launch
        note_probe_launch(root, event, event.get("tool_response"))
    except Exception:  # noqa: BLE001 - the probe's bookkeeping must not cost the story its binding
        pass


def decide(event):
    """Bind when `plan` says so; the failure of the bind is ONE signal. Returns the plan (or None) for the caller's tests."""
    import hooklib
    root = hooklib.project_root(event if isinstance(event, dict) else None)
    note_probe(event, root)
    found = plan(event, root)
    if found is None:
        return None
    ticket, dispatch, agent = found
    code, last = bind(root, ticket, dispatch, agent)
    if code:
        hooklib.person_signal(event, "auto_bind_failed",
                              f"agent_autobind: `story_step.py bind` for {dispatch} (agent {agent}) did not succeed "
                              f"(exit {code}: {last[:160]}); the conductor binds it by hand (the launch card names the command)",
                              task=ticket)
    return found


def main() -> None:
    event = None
    try:
        raw = sys.stdin.read()
        try:
            event = json.loads(raw) if raw.strip() else None
        except ValueError:
            event = None        # an input that is no JSON is no launch: nothing to bind, and nothing of ours broke
        decide(event)
    except Exception as exc:  # noqa: BLE001 - a hook never blocks on its own defect, and says so
        try:
            import hooklib
            hooklib.person_signal(event if isinstance(event, dict) else {}, "gate_unreadable",
                                  f"agent_autobind: unreadable - the binding check crashed ({type(exc).__name__}) - the "
                                  "factory's own defect; bind by hand: `story_step.py bind`",
                                  once_key=f"agent_autobind|{type(exc).__name__}")
        except Exception:  # noqa: BLE001
            pass
    sys.exit(0)


if __name__ == "__main__":
    main()
