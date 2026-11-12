"""Shared scaffolding for the tests that replay a text's commands through the real role guard (not a test itself).

On Codex Desktop a role without Bash in its `tools:` line may run ONE plain read command, and the refusal
comes from `host_adapter.role_policy`, reached through `guard_pre_tool.py` as a PreToolUse hook. A test that
wants the real verdict sends the hook an event as a subprocess. TP2-2406 S4-6/S4-7, 14.10: a text of the
factory sent a role without Bash to a script and the guard refused the call, so the role stopped with its form
untouched; the tests of the launch prompt, the brief and the tool guidance prove each text by replaying every command
it names. What they need lives here once:

  * the roles of `agents/*.md` and which of them have Bash (`ROLES`, `NO_BASH`, `WITH_BASH`; the tools of a role are
    `host_adapter.role_tools`, the one reader of that line)
  * `named_commands(text)`: every shell command a text instructs, in the shape a role would type it
  * `codex_event` / `file_event` / `guard_verdict` / `replay_all`: a Codex PreToolUse event for that role, sent to the
    real `guard_pre_tool.py` as a subprocess; exit 0 = allowed, 2 = refused
"""
import json
import os
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402

sys.path.insert(0, str(harness.SCRIPTS))
import host_adapter as HA  # noqa: E402

# The heads of a plain read command are the guard's own list (`HA._READ_HEAD`, SIBLING_MAP axis 11): built from it, so
# a read command the guard learns is a command this replay extracts. `named_commands` is an INDEPENDENT oracle of what
# a text instructs (prose -> command); it does not share an extractor with role_permissions' INLINE_RUN_RE / FENCE_RE.
_READ_ALTS = HA._READ_HEAD.pattern.removeprefix("(?:").removesuffix(r")(?:\s|$)")
assert "|" in _READ_ALTS and "(" not in _READ_ALTS, HA._READ_HEAD.pattern    # the shape this derivation relies on
SHELL_WORDS = re.compile(r"^(?:python|" + _READ_ALTS + r")\b")
READ_LINE = re.compile(r"^\s*(?:[-*]\s+)?((?:" + _READ_ALTS + r")\s.*)$")
PY_TOKEN = re.compile(r"\b[\w-]+\.py\b")


def agent_tools(role: str) -> list:
    """The tools of a role's file, sorted; the role always has a file (it comes from `agents/*.md`)."""
    tools = HA.role_tools(role)
    assert tools is not None, f"agents/{role}.md is not readable"
    return sorted(tools)


ROLES = sorted(p.stem for p in (harness.PLUGIN_ROOT / "agents").glob("*.md"))
NO_BASH = sorted(r for r in ROLES if "Bash" not in agent_tools(r))
WITH_BASH = sorted(r for r in ROLES if "Bash" in agent_tools(r))


def _as_python(span: str, root: str) -> str:
    """A span that starts with a bare `name.py` is run through the interpreter, from this copy's scripts."""
    m = re.match(r"([\w-]+\.py)\b(.*)$", span)
    return f'python "{root}/scripts/{m.group(1)}"{m.group(2)}' if m else span


def named_commands(text: str) -> list:
    """Every shell command the text's own lines instruct, in the shape a role would type it.

    Five spellings occur: a backticked command (`python <plugin>/scripts/x.py ...`), a line that
    carries `python "<path>" ...` to its end, `run <script>.py <args>` (the handoff_help line), any other
    `name.py args` - in a backticked span or bare - which a role would run as
    `python <plugin>/scripts/name.py args`, and a line that is itself a read command
    (`rg ...`, `Get-Content ...`, also behind a list dash). ANY backticked span holding a `.py` token
    is a command. `<plugin>` is this copy's plugin root; any other `<placeholder>` is replaced by a word."""
    root = harness.PLUGIN_ROOT.as_posix()
    found = []
    for line in text.splitlines():
        ticked = [_as_python(m.group(1), root) for m in re.finditer(r"`([^`]+)`", line)
                  if SHELL_WORDS.match(m.group(1)) or PY_TOKEN.search(m.group(1))]
        if ticked:
            found += ticked
            continue
        m = re.search(r"\b(python\s.*)$", line)
        if m:
            found.append(m.group(1))
            continue
        m = re.search(r"\brun\s+(\w+\.py)\s+(--file\s+\S+)", line)
        if m:
            found.append(f'python "{root}/scripts/{m.group(1)}" {m.group(2)}')
            continue
        m = READ_LINE.match(line)
        if m:
            found.append(m.group(1))
            continue
        token = PY_TOKEN.search(line)
        if token:
            found.append(_as_python(line[token.start():], root))
    return [re.sub(r"<[^>]+>", "x", c.replace("<plugin>", root)) for c in found]


def codex_event(role: str, command: str, root: Path, n: int) -> dict:
    """A Codex Desktop PreToolUse event: the child's own `exec_command`, named like a native task."""
    return {"hook_event_name": "PreToolUse", "session_id": f"replay-{n}", "turn_id": f"turn-{n}",
            "cwd": str(root), "agent_type": role.replace("-", "_") + "__tp2_2406_7",
            "tool_name": "exec_command", "tool_input": {"cmd": command}}


def file_event(role: str, tool: str, tool_input: dict, root: Path, n: int) -> dict:
    """A Codex PreToolUse event for a file tool of the role's own child."""
    return dict(codex_event(role, "", root, n), tool_name=tool, tool_input=tool_input)


def guard_verdict(role: str, command: str, root: Path, n: int, event: dict | None = None) -> tuple:
    """(exit code, stderr) of the real guard for this call. 0 = allowed; 2 = refused.

    `event` replaces the default `exec_command` event (a replay may send an `apply_patch` or a Write)."""
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(root), PYTHONDONTWRITEBYTECODE="1")
    done = subprocess.run([sys.executable, "-B", str(harness.SCRIPTS / "guard_pre_tool.py")],
                          input=json.dumps(event or codex_event(role, command, root, n)), capture_output=True,
                          text=True, encoding="utf-8", errors="replace", cwd=str(root), env=env, timeout=120)
    return done.returncode, (done.stderr or "")[-3000:]


def replay_all(jobs: list, root: Path, first_n: int = 0) -> list:
    """The verdict (exit code, stderr) of the real guard for every (role, command) of `jobs`, in order."""
    with ThreadPoolExecutor(max_workers=4) as pool:
        return list(pool.map(lambda item: guard_verdict(item[0][0], item[0][1], root, item[1]),
                             [(job, first_n + n) for n, job in enumerate(jobs)]))
