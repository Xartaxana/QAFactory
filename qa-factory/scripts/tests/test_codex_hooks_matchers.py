"""CX1-1: the Codex host surface - hooks/codex.json matchers, and what `host_adapter.normalize` makes of a shell call.

Measured on TP2-2406 under the Codex desktop host (her numbers, an estimate of her run): a `git status` took
12.9 to 14.1 s because the PreToolUse guard and four PostToolUse hooks ran on EVERY native tool call, and 930
`wait_agent` / `wait` / `sleep` calls paid the same for hooks that have nothing to say about them. The guard and the
probe receipt are therefore scoped to the tools they inspect, under BOTH readings of a matcher (a full match and a
search). The debounced cost sample is NOT narrowed here (its matcher stays empty, as on the Claude manifest): it adds
no latency (`async`), and a narrower one would lose the cost of a role session that never dispatches (P18).

What this file pins:
- the matchers are the regex image of `host_adapter.tool_short_name` (a CENSUS GENERATED from the adapter's own
  constants over every namespace spelling, not a typed list): a spelling the adapter resolves to a guarded name is
  matched, in a full match and in a search alike; nothing else is;
- `shell`/`local_shell` are shell calls (an argv list or text; every text field is joined, none is dropped); a Desktop
  code cell (`exec`/`js`) becomes a shell call ONLY when it holds exactly one literal `tools.exec_command`, with THAT
  command as the text the shell checks read. Any other cell is not a command: its nested `apply_patch` or connector
  call is invisible to the shell checks, so it must not be handed to them as if it were checked: `normalize` records
  a refusal on the transport (it does not raise, which the guard would report as a broken stdin and count towards
  its escalation), and `role_policy` blocks with the door "send one call per cell" (the real guard, two calls in a
  row, writes no finding);
- a call of that family with no command text is refused with its door named, whatever the call's host markers
  (`turn_id` or not: `normalize` renames the tool, so the markers are read from the transport record too);
- the doctor's probe reads the command of the event the guard saw (FR-17): the DENY echo inside `functions.exec` is
  recognized after `normalize` and the ALLOW echo is let through, in the real guard process.
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import PLUGIN_ROOT, SCRIPTS, check, check_eq, check_in, cleanup, temp_project  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import host_adapter as H  # noqa: E402
import host_probe  # noqa: E402

CODEX = PLUGIN_ROOT / "hooks" / "codex.json"

# Names Claude sends, which the Codex manifest keeps guarded; and the ones that are pure waiting.
CLAUDE_GUARDED = ["Agent", "Task", "SendMessage", "Bash", "PowerShell", "Write", "Edit", "MultiEdit", "NotebookEdit",
                  "Read", "Grep", "Glob"]
CLAUDE_PROBED = ["Bash", "PowerShell", "Write", "Edit", "MultiEdit", "NotebookEdit", "Agent"]
PROBE_ACTIONS = {"apply_patch", "exec_command", "shell_command", "write_stdin", "spawn_agent"} | H.SHELL_TOOLS | H.CELL_TOOLS
WAITING = ["wait_agent", "list_agents", "wait", "sleep", "view_image", "update_plan", "web_search"]
# Namespace spellings: a dot, none, the two prefixes Codex concatenates, a foreign namespace, both prefixes.
PREFIXES = ["", "functions.", "functions", "collaboration.", "collaboration", "x.", "container.", "functions.collaboration"]
DECOYS = ["xexec", "execute", "jsonrpc", "shells", "functionsfoo", "exec_commands", "local_shells", "spawn_agents", "", "exec ", "Bash2",
          "collaborationfunctionsexec", "mcp_x__y"]

CELL_OK = 'text(await tools.exec_command({cmd: "git status"}));'
CELL_CONST = 'const r = await tools.exec_command({ cmd: "git status" }); text(r.output);'
CELL_TWO = 'text(await tools.exec_command({cmd: "git status"})); text(await tools.exec_command({cmd: "rm -rf x"}));'
CELL_EMPTY = 'text(await tools.exec_command({cmd: ""}));'
SECRET_PATCH = ("*** Begin Patch\n*** Add File: notes/k.txt\n+-----BEGIN RSA PRIVATE KEY-----\n"
                "+MIIEowIBAAKCAQEA\n*** End Patch")
CELL_PATCH = "await tools.apply_patch({input: " + json.dumps(SECRET_PATCH) + "});"
SESSION = "codex-session-hooks"


def readings(matcher: str, tool: str) -> tuple:
    return bool(re.fullmatch(matcher, tool)), bool(re.search(matcher, tool))


def hook_with(wiring: dict, event: str, script: str) -> str:
    """The matcher of the one entry of `event` whose hook line ends in `script`; a missing entry fails."""
    found = [e.get("matcher", "") for e in wiring["hooks"].get(event, [])
             if any(h["command"].split(" telemetry_hook.py ", 1)[-1].strip() == script for h in e["hooks"])]
    check(f"{event} wires `{script}` exactly once", len(found) == 1, repr(found))
    return found[0] if found else ""


def census(matcher: str, guarded) -> tuple:
    """(spellings the matcher gets wrong, spellings tried). `guarded(spelling)` is the expectation; each spelling
    must be matched, or not, the SAME way by a full match and by a search."""
    spellings = sorted({p + n for p in PREFIXES for n in H.HOST_ACTIONS | set(WAITING)} | set(CLAUDE_GUARDED) | set(DECOYS)
                       | {"mcp__jira__create_issue", "mcp__x__y"})
    wrong = []
    for spelling in spellings:
        full, found = readings(matcher, spelling)
        if full != found or full != guarded(spelling):
            wrong.append((spelling, full, found, guarded(spelling)))
    return wrong, len(spellings)


def raises(call) -> bool:
    try:
        call()
    except ValueError:
        return True
    return False


def refusal(event: dict, cfg=None) -> str:
    """The text role_policy blocks with on this (normalized) event, or '' when it lets the call through."""
    seen = []

    def stop(message):
        seen.append(message)
        raise PermissionError

    with patch("hooklib.block", side_effect=stop):
        try:
            H.role_policy(event, cfg if cfg is not None else {"schema_version": 2})
        except PermissionError:
            pass
    return seen[0] if seen else ""


def refused(event: dict):
    """The refusal `normalize` recorded on the transport, or None."""
    return (event.get("_qa_host") or {}).get("refusal")


def run_guard_text(root: Path, stdin: str) -> tuple:
    """The real guard process on this stdin text: (exit code, stderr)."""
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(root), PYTHONDONTWRITEBYTECODE="1")
    done = subprocess.run([sys.executable, "-B", str(SCRIPTS / "guard_pre_tool.py")], input=stdin,
                          capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=str(root), env=env, timeout=120)
    return done.returncode, done.stderr


def run_guard(root: Path, event: dict) -> tuple:
    """The real guard process on this event: (exit code, stderr)."""
    return run_guard_text(root, json.dumps(dict(event, cwd=str(root), hook_event_name="PreToolUse", session_id=SESSION)))


def matchers_part() -> None:
    codex = json.loads(CODEX.read_text(encoding="utf-8"))
    guard = hook_with(codex, "PreToolUse", "guard_pre_tool.py")
    check("the guard no longer fires on every tool", guard != "")
    wrong, tried = census(guard, lambda s: H.tool_short_name(s) in H.HOST_ACTIONS or s in CLAUDE_GUARDED or s.startswith("mcp__"))
    check_eq(f"guard matcher: {tried} generated spellings, full match = search = what tool_short_name resolves to", wrong, [])
    for spelling in ("functions.local_shell", "functionsexec", "functionsjs", "functionsshell", "functions.exec", "container.exec",
                     "collaborationsend_message", "x.apply_patch", "exec", "js", "shell", "local_shell"):
        check_eq(f"guard matcher: {spelling} is guarded, in both readings", readings(guard, spelling), (True, True))
    for spelling in WAITING + ["collaborationwait_agent", "collaboration.wait_agent"]:
        check_eq(f"guard matcher: {spelling} (a wait) is not guarded, in both readings", readings(guard, spelling), (False, False))
    # the matcher the adapter's constants image; a name added to the adapter without the matcher fails the census above
    check("the census covers every adapter name", set(H.HOST_ACTIONS) >= {"exec", "js", "shell", "local_shell", "exec_command", "send_message"})
    probe = hook_with(codex, "PostToolUse", "host_probe.py --hook")
    check("the probe receipt no longer fires on every tool", probe != "")
    wrong, tried = census(probe, lambda s: H.tool_short_name(s) in PROBE_ACTIONS or s in CLAUDE_PROBED)
    check_eq(f"probe matcher: {tried} generated spellings, full match = search = the probed families", wrong, [])
    cost = hook_with(codex, "PostToolUse", "cost_capture.py --debounced")
    check_eq("the debounced cost sample is as it was (empty matcher: async, and a role that never dispatches keeps its cost)", cost, "")
    # HF2-9 K4, narrowed (TD-14.5 fix): an async guard's decision is ignored by the host, so the gate would open silently
    claude = json.loads((PLUGIN_ROOT / "hooks" / "hooks.json").read_text(encoding="utf-8"))
    guards = [(e.get("matcher", ""), h) for e in claude["hooks"].get("PreToolUse", []) for h in e["hooks"] if "guard_pre_tool.py" in h["command"]]
    check_eq("hooks/hooks.json: every guard_pre_tool.py hook is synchronous", [m for m, h in guards if h.get("async")], [])
    for tool in ("Write", "Edit", "Bash", "Read", "Grep", "Glob"):
        check(f"hooks/hooks.json: guard_pre_tool.py is wired on {tool}", any(re.fullmatch(m, tool) for m, _h in guards),
              f"matchers wired: {[m for m, _h in guards]}")


def shell_family_part() -> None:
    """`shell` / `local_shell`: a command as an argv list or as text; every text field is joined in the order
    command, cmd, input, code (E2, E5)."""
    def shell(name, tool_input):
        return H.normalize({"turn_id": "t", "tool_name": name, "tool_input": tool_input})

    event = shell("functions.shell", {"command": ["bash", "-lc", "npm test"]})
    check_eq("shell: an argv is one Bash command, joined by spaces", (event["tool_name"], event["tool_input"]["command"]),
             ("Bash", "bash -lc npm test"))
    check_eq("shell: the native name and input are kept for role_policy and the probe",
             (event["_qa_host"]["name"], event["_qa_host"]["input"]), ("functions.shell", {"command": ["bash", "-lc", "npm test"]}))
    check_eq("shell: an argv element that is not text goes through str()",
             shell("local_shell", {"command": ["sleep", 5]})["tool_input"]["command"], "sleep 5")
    check_eq("shell: a string input is the command", shell("functions.local_shell", "git status")["tool_input"]["command"], "git status")
    check_eq("shell: every spelling of the name resolves to a Bash call",
             [shell(n, {"command": "ls"})["tool_name"] for n in ("shell", "functions.shell", "functionsshell", "local_shell",
                                                                    "functions.local_shell", "functionslocal_shell", "container.shell")],
             ["Bash"] * 7)
    check_eq("shell: two different fields are BOTH in the text, in the order command, cmd, input, code",
             shell("shell", {"code": "d", "input": "c", "cmd": "b", "command": "a"})["tool_input"]["command"], "a\nb\nc\nd")
    check_eq("shell: the same text twice is one segment; a blank field adds none",
             shell("shell", {"command": "a", "cmd": "a", "input": "  "})["tool_input"]["command"], "a")
    check_eq("shell: a second field cannot hide behind the first",
             shell("shell", {"command": "ls", "cmd": "git config --global a b"})["tool_input"]["command"], "ls\ngit config --global a b")
    for name in ("shell", "exec_command"):
        for label, tool_input in (("a dict", {"command": {"a": 1}}), ("a number", {"cmd": 7}), ("true", {"code": True}),
                                  ("a list in a dict", {"input": {"x": ["y"]}})):
            event = shell(name, tool_input)
            check(f"{name}: {label} as the command is refused with a recorded refusal that names the field and the door "
                  "(no exception, never rendered through str())",
                  event["tool_name"] == name and "must be text or an argv list" in str(refused(event))
                  and "send the command as text or as an argv list" in str(refused(event)), repr(refused(event)))
            check_in(f"{name}: {label}: role_policy blocks with it, and with no config too",
                     "send the command as text or as an argv list", refusal(event, {}))
    check("shell: a number as the whole input is refused", raises(lambda: H.normalize({"tool_name": "shell", "tool_input": 5})))
    check("shell: a list as the whole input is refused", raises(lambda: H.normalize({"tool_name": "local_shell", "tool_input": ["ls"]})))
    check_eq("exec_command is read as before (cmd, then command)",
             (H.normalize({"tool_name": "exec_command", "tool_input": {"cmd": "ls"}})["tool_input"]["command"],
              H.normalize({"tool_name": "functions.exec_command", "tool_input": {}})["tool_input"]["command"]), ("ls", ""))
    # F-2: exec_command joins every command field like its neighbour; a second one cannot hide behind the first
    for label, tool_input, want in (("cmd only", {"cmd": "a"}, "a"), ("command only", {"command": "a"}, "a"),
                                    ("both equal", {"cmd": "a", "command": "a"}, "a"),
                                    ("both different", {"cmd": "a", "command": "b"}, "b\na")):
        for name in ("exec_command", "functions.shell_command"):
            check_eq(f"exec_command family: {label} ({name}) joined in the order command, cmd",
                     shell(name, tool_input)["tool_input"]["command"], want)


def cell_part() -> None:
    """A Desktop code cell is shell text only when it is one literal `tools.exec_command` call without a tty."""
    def cell(name, tool_input):
        return H.normalize({"turn_id": "t", "tool_name": name, "tool_input": tool_input})

    for name in ("exec", "functions.exec", "functionsexec", "container.exec", "js", "functions.js"):
        for label, source in (("text(await ...)", CELL_OK), ("const r = await ...; text(r.output)", CELL_CONST)):
            for kind, tool_input in (("string", source), ("dict", {"input": source})):
                event = cell(name, tool_input)
                check_eq(f"cell: {name} {kind} holding {label} is a Bash call with the INNER command",
                         (event["tool_name"], event["tool_input"]["command"]), ("Bash", "git status"))
    event = cell("functions.exec", CELL_OK)
    check_eq("cell: the native name and the input as text (the probe's transport) are kept",
             (event["_qa_host"]["name"], event["_qa_host"]["input"]), ("functions.exec", {"input": CELL_OK}))
    # every cell that is not exactly one literal exec_command keeps its own name and carries a refusal (never Bash)
    door = "send one call per cell"
    for label, source in (("two exec_command calls", CELL_TWO), ("a nested apply_patch", CELL_PATCH),
                          ("a connector call", 'await tools.mcp__x__write_doc({id: 1});'), ("plain JavaScript", "1 + 1"),
                          ("an exec_command with an expression for its command", 'text(await tools.exec_command({cmd: c}));')):
        for name, tool_input, kind in (("functions.exec", source, "STRING"), ("js", source, "STRING"),
                                       ("functions.exec", {"input": source}, "DICT")):
            event = cell(name, tool_input)
            check(f"cell: a {kind} {name} cell with {label} keeps its name, is not handed to the shell checks, and carries the door",
                  event["tool_name"] == name and door in str(refused(event)), repr((event["tool_name"], refused(event))))
            check_in(f"cell: {kind} {name} with {label}: role_policy blocks with the three parts of the FR-1 form, with no config too",
                     "holds more than one call, or a call the guard cannot read. Expected: exactly one literal tools.exec_command call. Door: "
                     + door, refusal(event, {}))
    # a cell that carries more than one text: nothing says which one runs
    check("cell: a cell that also carries a command field is refused", door in str(refused(cell("exec", {"input": CELL_OK, "command": "ls"}))))
    check("cell: two different source fields are refused", door in str(refused(cell("exec", {"input": CELL_OK, "code": CELL_TWO}))))
    check("cell: a source that is not text is refused with the field named",
          "tool_input.input must be text" in str(refused(cell("exec", {"input": 7}))))
    check("cell: a bare cmd field on a cell is refused (a cell is read only as code)", door in str(refused(cell("exec", {"cmd": "git status"}))))
    check_eq("cell: the refusal names what was wrong, what was expected and the door",
             refused(cell("exec", {"input": "1 + 1"})),
             {"what": "a code cell holds more than one call, or a call the guard cannot read",
              "expected": "exactly one literal tools.exec_command call", "door": door})
    check_eq("cell: the same source twice is one source", cell("exec", {"input": CELL_OK, "code": CELL_OK})["tool_name"], "Bash")
    # the code under `source` is a cell's text everywhere (one field list), not 'no command text'
    check_eq("cell: code under `source` is read as the cell's code", (cell("exec", {"source": CELL_OK})["tool_name"],
                                                                     cell("exec", {"source": CELL_OK})["tool_input"]["command"]), ("Bash", "git status"))
    check("cell: a second call under `source` is refused with the door, not as a cell with no text",
          door in str(refused(cell("exec", {"source": CELL_TWO}))))
    # a terminal session takes input the guard cannot check, so a cell asking for one is refused with its door
    for label, source in (("tty: true", 'text(await tools.exec_command({cmd: "bash", tty: true}));'),
                          ("tty: 1", 'text(await tools.exec_command({cmd: "bash", tty: 1}));'),
                          ('"tty": true', 'text(await tools.exec_command({"cmd": "bash", "tty": true}));'),
                          ("tty first, const form", 'const r = await tools.exec_command({tty: true, cmd: "bash"}); text(r.output);')):
        event = cell("functions.exec", source)
        check(f"cell: {label} keeps the cell's own name and carries the tty door", event["tool_name"] == "functions.exec"
              and "drop the tty option" in str(refused(event)), repr((event["tool_name"], refused(event))))
    for label, source in (("tty: false", 'text(await tools.exec_command({cmd: "git status", tty: false}));'),
                          ("tty: 0", 'text(await tools.exec_command({tty: 0, cmd: "git status"}));'),
                          ("no tty", CELL_OK)):
        check_eq(f"cell: {label} is still one command (control)", cell("functions.exec", source)["tool_name"], "Bash")
    # an exec_command cell whose command is empty is a shell call with no command: refused below (E3), never a pass
    event = cell("functions.exec", CELL_EMPTY)
    check_eq("cell: one exec_command with an empty cmd is a Bash call with an empty command", (event["tool_name"], event["tool_input"]["command"]),
             ("Bash", ""))
    check("cell: a number or a list as the whole input is still an unreadable event (ValueError: the host's fault, not the call's)",
          raises(lambda: cell("exec", 5)) and raises(lambda: cell("exec", ["x"])))
    check_eq("normalize: a waiting call is left as it is",
             H.normalize({"turn_id": "t", "tool_name": "wait_agent", "tool_input": {"timeout_ms": 60000}})["tool_name"], "wait_agent")
    check_eq("the shipped normalizer and the probe read one cell the same way",
             host_probe.probe_command(cell("functions.exec", CELL_OK)), "git status")


def refusal_part() -> None:
    """E3: a call of the shell/cell family with no command text is refused (FR-1: what is wrong, what was expected,
    where to put it), also WITHOUT any host marker on the event; `exec_command` without `cmd` is as it was."""
    for label, name, tool_input in (("an empty dict cell", "exec", {}), ("a blank input", "exec", {"input": "   "}),
                                    ("None as the input", "exec", None), ("an empty string cell", "functions.exec", ""),
                                    ("a js cell", "js", {}), ("an empty shell", "shell", {}), ("an empty argv", "local_shell", {"command": []}),
                                    ("blank text", "functions.shell", {"command": " ", "cmd": "\n"}),
                                    ("one exec_command with an empty cmd", "functions.exec", CELL_EMPTY)):
        event = H.normalize({"tool_name": name, "tool_input": tool_input})        # no turn_id, no host, no rollout path
        check_eq(f"E3: {label} carries no host marker of its own", (event.get("turn_id"), event.get("host")), (None, None))
        text = refusal(event)
        check_in(f"E3: {label} is refused, with what was expected", "carried no command text the guard can read", text)
        check_in(f"E3: {label}: the refusal names the fields", "command, cmd, input, code or source", text)
        check_in(f"E3: {label}: and the door", "tools.exec_command", text)
    check_eq("E3: exec_command without cmd is not this rule's (as on main)",
             refusal(H.normalize({"turn_id": "t", "tool_name": "exec_command", "tool_input": {}})), "")
    check_eq("E3: a command is not refused", refusal(H.normalize({"tool_name": "shell", "tool_input": {"command": "ls"}})), "")
    check_eq("E3: no config, no rule (the guard's rules all wait for a config)",
             refusal(H.normalize({"tool_name": "exec", "tool_input": {}}), {}), "")
    # position: it fires before the role-file branch, so a role without Bash sees THIS text, and after the doctor rule
    event = H.normalize({"tool_name": "shell", "tool_input": {}, "agent_type": "qa-case-critic"})
    check_in("E3 position: a role without Bash is told about the missing command, not that shell is forbidden",
             "carried no command text", refusal(event))
    event = dict(event, factory_diagnostic=True)
    check_in("E3 position: the doctor rule still comes first", "FACTORY DOCTOR", refusal(event))
    # the role-file branch itself is untouched: a role without Bash is refused a real command as before
    event = H.normalize({"tool_name": "shell", "tool_input": {"command": "pytest -q"}, "agent_type": "qa-case-critic"})
    check_in("E3 position: the no-Bash branch below is unchanged", "may read using rg", refusal(event))


def host_marker_part() -> None:
    """F-2: `normalize` renames the tool, so `is_codex` of a NORMALIZED event reads the transport record."""
    event = H.normalize({"tool_name": "exec_command", "tool_input": {"cmd": "ls"}})
    check_eq("is_codex: a normalized exec_command without any marker is still Codex (the transport says so)",
             (event["tool_name"], H.is_codex(event)), ("Bash", True))
    check_eq("is_codex: the same for send_input and a shell tool",
             [H.is_codex(H.normalize({"tool_name": n, "tool_input": {}})) for n in ("send_input", "shell", "local_shell", "exec", "js")],
             [True] * 5)
    claude = H.normalize({"tool_name": "Bash", "tool_input": {"command": "ls"}, "_qa_host": {"codex": True, "name": "exec_command"}})
    check_eq("is_codex: a transport record a caller SENT is dropped by normalize and cannot make a Claude call Codex",
             (claude["_qa_host"]["codex"], H.is_codex(claude)), (False, False))
    check_eq("is_codex: a Claude Bash call is not Codex", H.is_codex({"tool_name": "Bash", "tool_input": {"command": "ls"}}), False)
    check_eq("is_codex: the record on a normalized event is read", H.is_codex({"tool_name": "Bash", "_qa_host": {"codex": True}}), True)
    check_eq("is_codex: every native name of the host is Codex, raw (one list: HOST_ACTIONS)",
             sorted(n for n in H.HOST_ACTIONS if not H.is_codex({"tool_name": n})), [])
    check_eq("is_codex: a Claude tool name is not", [n for n in CLAUDE_GUARDED if H.is_codex({"tool_name": n})], [])
    # the refusal record: written by normalize alone, and only after any record the caller sent is dropped
    forged = {"refusal": None, "codex": False, "name": "Bash", "input": {}}
    kept = H.normalize({"tool_name": "functions.exec", "tool_input": CELL_TWO, "_qa_host": forged})["_qa_host"]
    check_eq("refusal record: a refused cell keeps its refusal and the Codex flag when the caller sent a record of its own",
             ("send one call per cell" in str(kept.get("refusal")), kept["codex"], kept["name"]), (True, True, "functions.exec"))
    sent = H.normalize({"tool_name": "Bash", "tool_input": {"command": "ls"},
                        "_qa_host": {"refusal": {"what": "x", "expected": "y", "door": "z"}}})
    check_eq("refusal record: a refusal a caller SENT is dropped (it cannot make a call refused)",
             ("refusal" in sent["_qa_host"], refusal(sent, {"schema_version": 2}), refusal(sent, {})), (False, "", ""))
    check_eq("refusal record: the same call passes (control)", refusal(H.normalize({"tool_name": "functions.exec", "tool_input": CELL_OK}), {}), "")


def probe_part() -> None:
    """F-1 (b), E16, I5: the probe reads the transport, so the cell's echo is recognized before and after normalize."""
    root = temp_project("qa-codex-matchers-")
    try:
        probe = host_probe.prepare(root, SESSION)
        allow, deny = probe["commands"]

        def cell_event(echo, kind, name="functions.exec"):
            source = "text(await tools.exec_command(" + json.dumps({"cmd": echo}) + "));"
            return {"hook_event_name": "PreToolUse", "session_id": SESSION, "tool_name": name, "tool_use_id": "exec-1",
                    "tool_input": source if kind == "string" else {"input": source}}

        for kind in ("string", "dict"):
            for name in ("functions.exec", "exec", "js"):
                check_eq(f"E16: observe(normalize(DENY echo in {name}, {kind})) says the guard must block",
                         host_probe.observe(root, H.normalize(cell_event(deny, kind, name))), True)
                check_eq(f"E16: observe(normalize(ALLOW echo in {name}, {kind})) lets it through",
                         host_probe.observe(root, H.normalize(cell_event(allow, kind, name))), False)
            check_eq(f"E16: the raw event reads the same way ({kind})", host_probe.observe(root, cell_event(deny, kind)), True)
        check_eq("I5: one event, one command, before and after normalize",
                 host_probe.probe_command(H.normalize(cell_event(deny, "string"))), host_probe.probe_command(cell_event(deny, "string")))
        # Invariant (t-949 L-2 F-2, which replaces t-931 L F-1 (b) for the probe): the probe reads the command the GUARD
        # reads - the normalized event's `command` - never the transport's own input. A normalizer that lost the echo
        # (put the cell's code into `command`, as the first version did) loses it for the guard AND for the probe: the
        # probe then records no receipt, the safe side, and the same event is not a DENY echo for either reader.
        shaped = dict(H.normalize(cell_event(deny, "string")), tool_input={"command": "text(await tools.exec_command(x))"})
        check_eq("F-2: probe_command of an event whose normalized command lost the echo is that command, not the transport's echo",
                 host_probe.probe_command(shaped), "text(await tools.exec_command(x))")
        check_eq("F-2: ...so observe records no receipt and does not ask the guard to block it", host_probe.observe(root, shaped), False)
        check_eq("F-1 (b): a raw event without a transport is read as it always was",
                 host_probe.probe_command({"tool_name": "Bash", "tool_input": {"command": allow}}), allow)
        two = 'text(await tools.exec_command({cmd: '+ json.dumps(deny) + '})); text(await tools.exec_command({cmd: "ls"}));'
        check_eq("E16: a cell with two calls is no probe even when one is the echo",
                 host_probe.observe(root, dict(cell_event(deny, "dict", "exec"), tool_input={"input": two})), False)
        check("E16: and the guard refuses such a cell before any probe (normalize records the refusal, role_policy blocks)",
              "send one call per cell" in refusal(H.normalize(dict(cell_event(deny, "dict", "exec"), tool_input={"input": two})), {}))
        # the real guard process, the project's own config, the probe store prepared above
        code, err = run_guard(root, cell_event(deny, "string"))
        check_eq("end to end: the DENY echo inside a string functions.exec cell is blocked by the doctor rule", code, 2)
        check_in("end to end: with the doctor's words", "QA FACTORY DOCTOR", err)
        code, err = run_guard(root, cell_event(deny, "dict", "exec"))
        check_eq("end to end: the same as a dict exec cell", (code, "QA FACTORY DOCTOR" in err), (2, True))
        for kind in ("string", "dict"):
            code, err = run_guard(root, cell_event(allow, kind))
            check_eq(f"end to end: the ALLOW echo inside a functions.exec cell ({kind}) exits 0 under the project's config", code, 0)
        code, err = run_guard(root, {"tool_name": "Bash", "tool_use_id": "b", "tool_input": {"command": deny}})
        check_eq("end to end, control: the DENY echo as a plain Bash call is blocked the same way", (code, "QA FACTORY DOCTOR" in err), (2, True))
        code, err = run_guard(root, {"tool_name": "exec", "tool_use_id": "b", "tool_input": CELL_OK})
        check_eq("end to end, control: another cell is not a probe", code, 0)
        (root / "qa-factory/state/host-probe.json").unlink()
        code, err = run_guard(root, cell_event(deny, "string"))
        check_eq("end to end, control: with no probe prepared the echo is only an echo", (code, "QA FACTORY DOCTOR" in err), (0, False))
    finally:
        cleanup(root)


def guard_part() -> None:
    """The real guard on the shell family and on the cell that carries a secret."""
    door = "send one call per cell"
    root = temp_project("qa-codex-guard-")
    try:
        code, err = run_guard(root, {"tool_name": "apply_patch", "tool_input": {"input": SECRET_PATCH}})
        check_eq("control: the same patch as apply_patch is refused by the secrets rule", (code, "SECRETS" in err or "secret" in err.lower()), (2, True))
        for name in ("functions.exec", "exec", "js", "functionsexec"):
            code, err = run_guard(root, {"tool_name": name, "tool_input": CELL_PATCH})
            check_eq(f"F-1: a string {name} cell whose nested apply_patch writes a private key exits 2 (not handed to the shell checks)", code, 2)
            check_in(f"F-1: {name}: refused with the door the role can use", door, err)
            check(f"F-1: {name}: and NOT as a broken stdin (the fault is the call's)", "broken stdin" not in err and "could not be parsed" not in err)
        for name in ("functions.exec", "exec", "js"):
            code, err = run_guard(root, {"tool_name": name, "tool_input": {"input": CELL_PATCH}})
            check_eq(f"Q1: a DICT {name} cell whose nested apply_patch writes a private key exits 2 (not a pass under its own name)", code, 2)
            check_in(f"Q1: {name}: refused with the door the role can use", door, err)
            check(f"Q1: {name}: and NOT as a broken stdin (the fault is the call's)", "broken stdin" not in err and "could not be parsed" not in err)
        code, err = run_guard(root, {"tool_name": "functions.exec", "tool_input": {"input": CELL_TWO}})
        check_eq("Q1: a DICT cell with two exec_command calls exits 2", code, 2)
        code, err = run_guard(root, {"tool_name": "functions.exec", "tool_input": CELL_TWO})
        check_eq("F-1: a cell with two exec_command calls exits 2 (not read as its first)", code, 2)
        code, err = run_guard(root, {"tool_name": "functions.exec", "tool_input": CELL_OK})
        check_eq("a cell with ONE literal exec_command is judged as that command (git status passes)", code, 0)
        code, err = run_guard(root, {"tool_name": "functions.exec", "tool_input": 'text(await tools.exec_command({cmd: "git config --global a b"}));'})
        check_eq("and the INNER command is what the shell checks refuse", (code, "changing git configuration" in err), (2, True))
        for label, argv in (("git config in an argv", ["bash", "-lc", "git config --global a b"]),
                            ("a direct pytest launch in an argv", ["bash", "-lc", "pytest 'tests/x.py'"])):
            code, err = run_guard(root, {"tool_name": "shell", "tool_input": {"command": argv}})
            check_eq(f"E2: {label} is refused by the shell checks (the joined text shows it)", code, 2)
        code, err = run_guard(root, {"tool_name": "local_shell", "tool_input": {"command": ["ls", "-la"]}})
        check_eq("E2: an ordinary argv passes", code, 0)
        code, err = run_guard(root, {"tool_name": "shell", "tool_input": {"command": "ls", "cmd": "git config --global a b"}})
        check_eq("E5: a second command field is checked too", code, 2)
        bad = "git config --global a b"
        for label, tool_input, want in (("cmd only", {"cmd": bad}, 2), ("command only", {"command": bad}, 2),
                                        ("both equal", {"cmd": bad, "command": bad}, 2), ("both benign and different", {"cmd": "ls", "command": "pwd"}, 0),
                                        ("cmd benign, command refused", {"cmd": "ls", "command": bad}, 2)):
            code, err = run_guard(root, {"tool_name": "exec_command", "turn_id": "t", "tool_input": tool_input})
            check_eq(f"exec_command {label}: exit {want}", code, want)
        code, err = run_guard(root, {"tool_name": "exec_command", "turn_id": "t", "tool_input": {"cmd": bad, "command": "ls"}})
        check_eq("F-2: exec_command with cmd = git config --global and a decoy command = ls exits 2 (the same pair on shell does)", code, 2)
        check_in("F-2: with the shell checks' words, not a parse failure", "changing git configuration", err)
        code, err = run_guard(root, {"tool_name": "functions.exec", "tool_input": 'text(await tools.exec_command({cmd: "bash", tty: true}));'})
        check_eq("F-3: a cell asking for a tty session exits 2", code, 2)
        check_in("F-3: with its door", "drop the tty option", err)
        for name, tool_input in (("exec", {}), ("shell", {}), ("functions.exec", CELL_EMPTY)):
            code, err = run_guard(root, {"tool_name": name, "tool_input": tool_input})
            check_eq(f"E3: an empty {name} call with no host marker exits 2", code, 2)
            check_in(f"E3: {name}: with the missing-command words", "carried no command text", err)
        code, err = run_guard(root, {"tool_name": "wait_agent", "tool_input": {"timeout_ms": 1}})
        check_eq("a wait call that did reach the guard is not refused", code, 0)
    finally:
        cleanup(root)


def escalation_part() -> None:
    """FR-46: a refusal of this class is the CALL's fault. It is never reported as a parse failure and never feeds
    the guard's escalation counter, so two in a row stop no story and write no finding about the factory."""
    door = "send one call per cell"
    findings = lambda root: sorted(p.name for p in root.rglob("factory-backlog.md")) + sorted(  # noqa: E731
        p.name for p in root.rglob("guard-escalation"))
    root = temp_project("qa-codex-escalation-")
    try:
        for n in (1, 2, 3):
            code, err = run_guard(root, {"tool_name": "functions.exec", "tool_use_id": f"c{n}", "tool_input": {"input": CELL_PATCH + f"/*{n}*/"}})
            check_eq(f"escalation: refused cell call {n} exits 2 with the door", (code, door in err), (2, True))
            check(f"escalation: call {n} is not told that the guard is at fault", "IN A ROW" not in err and "broken stdin" not in err)
        check_eq("escalation: three refused cells leave no factory-backlog.md and no escalation counter", findings(root), [])
        for n in (1, 2):
            code, err = run_guard(root, {"tool_name": "shell", "tool_use_id": f"s{n}", "tool_input": {"command": {"x": n}}})
            check_eq(f"escalation: refused shell call {n} (a field that is not text) exits 2 with its door",
                     (code, "send the command as text or as an argv list" in err, "IN A ROW" in err), (2, True, False))
        check_eq("escalation: and two refused shell calls leave nothing either", findings(root), [])
    finally:
        cleanup(root)
    # positive control of the assertion: the SAME detector sees the files when the guard really cannot read stdin twice
    root = temp_project("qa-codex-escalation-control-")
    try:
        for n in (1, 2):
            code, err = run_guard_text(root, "{ not json " + str(n))
        check_eq("escalation, control: broken stdin twice does escalate (the detector can fail)",
                 (code, "IN A ROW" in err, findings(root)), (2, True, ["factory-backlog.md", "guard-escalation"]))
    finally:
        cleanup(root)


def main() -> None:
    for part in (matchers_part, shell_family_part, cell_part, refusal_part, host_marker_part, probe_part, guard_part, escalation_part):
        try:
            part()
        except Exception as exc:  # noqa: BLE001 - one part crashing must not hide the verdict of the others
            check(part.__name__ + " ran to the end", False, type(exc).__name__ + ": " + str(exc))
    harness.finish("test_codex_hooks_matchers")


if __name__ == "__main__":
    main()
