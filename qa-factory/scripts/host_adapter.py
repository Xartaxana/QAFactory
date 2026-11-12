"""Normalize host transport, not policy. Native arguments are retained for rewrites.

Codex aliases affect hook matching only. A patch can touch several paths; callers
must check every returned operation before allowing the original atomic call.
"""
from __future__ import annotations

import copy
import json
import re
import sys
from pathlib import Path

from hooklib import argv_text, command_segments, parse_frontmatter, reader_runs, role_name, shell_opaque_found

# The Codex host's native tool names, by what they carry. The ONE list: `tool_short_name` resolves a
# spelling to a name in it, `is_codex` reads it, and `hooks/codex.json`'s matchers are checked against it
# (the census in test_codex_hooks_matchers.py is generated from these constants, not typed again).
SHELL_TOOLS = frozenset({'shell', 'local_shell'})    # the CLI's shell tools: an argv list or a string
CELL_TOOLS = frozenset({'exec', 'js'})               # the Desktop's code cells: JavaScript text, not a command
HOST_ACTIONS = frozenset({'spawn_agent', 'send_input', 'send_message', 'followup_task',
                          'interrupt_agent', 'close_agent', 'exec_command', 'shell_command',
                          'write_stdin', 'apply_patch'}) | SHELL_TOOLS | CELL_TOOLS
NAMESPACE_PREFIXES = ('collaboration', 'functions')  # concatenated without a separator by some builds
# ONE list of the fields a shell-family call or a code cell carries its text in, in join order. For a cell the
# first two are a command (a second text beside its code), the rest are where its JavaScript can arrive.
COMMAND_FIELDS = ('command', 'cmd', 'input', 'code', 'source')
CELL_SOURCE_FIELDS = COMMAND_FIELDS[2:]
FIELD_WORDS = ", ".join(COMMAND_FIELDS[:-1]) + " or " + COMMAND_FIELDS[-1]
# Every key a message's recipient can arrive under, ONE list for the classification of `send_message` below.
# `stage_guard.check_resume` reads the same five and should adopt this tuple.
RECIPIENT_ALIASES = ('to', 'recipient', 'agent_id', 'id', 'target')
PARENT_RECIPIENT = '/root'


def tool_short_name(value):
    """Codex may concatenate a tool namespace without a separator in hook events."""
    name = str(value or '').rsplit('.', 1)[-1]
    for prefix in NAMESPACE_PREFIXES:
        if name.startswith(prefix) and name[len(prefix):] in HOST_ACTIONS:
            return name[len(prefix):]
    return name


def native_role(value):
    """Desktop task names use underscores; __suffix isolates concurrent stories."""
    raw = str(value or '')
    from native_context import is_probe_task
    if is_probe_task(raw):
        return 'qa-scout'
    candidate = raw.rpartition(':')[2].split('__',1)[0].replace('_','-')
    if (Path(__file__).resolve().parents[1] / 'agents' / (candidate+'.md')).is_file():
        return candidate
    return raw


def is_codex(event):
    """Whether the event came from the Codex host: its own markers, or the transport record `normalize`
    wrote (`_qa_host.codex`, computed from the RAW event - `normalize` drops one a caller sent, so on a
    normalized event it cannot be forged). The second reader matters because `normalize` renames
    `exec_command`, `shell`, ... to `Bash`: the tool-name test then sees no Codex name at all."""
    event = event or {}
    return bool(event.get("turn_id") or event.get("host") == "codex"
                or Path(str(event.get("transcript_path") or "")).name.startswith("rollout-")
                or (event.get("_qa_host") or {}).get("codex")
                or tool_short_name(event.get("tool_name")) in HOST_ACTIONS)


def _command_texts(tool_input):
    """The non-blank texts a shell-family call carries in COMMAND_FIELDS, de-duplicated, in that order.
    An argv list is `hooklib.argv_text` (its elements joined by a space). The checks read the joined text,
    so an element holding an unbalanced quote is grouped by their tokenizer, not by the argv. Any other
    non-text value is refused (ValueError), not rendered through str(): a dict or a number is not a command."""
    texts = []
    for key in COMMAND_FIELDS:
        value = tool_input.get(key)
        if isinstance(value, (list, tuple)):
            value = argv_text(value)
        elif value is not None and not isinstance(value, str):
            raise ValueError(f"tool_input.{key} must be text or an argv list")
        if value and value.strip() and value not in texts:
            texts.append(value)
    return texts


def _refused(what, expected, door):
    """A call-shape refusal in the FR-1 form: what is wrong, what was expected, the door. `normalize` records
    it on the transport (`_qa_host.refusal`) and `role_policy` blocks with it. It is NOT raised: an exception
    in `normalize` reaches the guard as an unreadable event ("broken stdin"), which names the wrong party and
    feeds the guard's escalation counter - and the fault here is the call's (FR-46)."""
    return {"what": what, "expected": expected, "door": door}


def _texts_or_refusal(tool_input):
    """(`_command_texts`, None), or ([], the refusal) when a field is neither text nor an argv list."""
    try:
        return _command_texts(tool_input), None
    except ValueError as exc:
        return [], _refused(str(exc), "text, or an argv list of text, in " + FIELD_WORDS,
                            "send the command as text or as an argv list in one of those fields")


def _cell_source(tool_input):
    """The one text a code cell's JavaScript arrives as, or None: no text, two different texts, a text beside a
    `command`/`cmd` field (nothing says which one runs), or an input that is neither text nor an object."""
    if isinstance(tool_input, str):
        return tool_input
    if not isinstance(tool_input, dict):
        return None
    if any(isinstance(tool_input.get(key), str) and tool_input[key].strip() for key in COMMAND_FIELDS[:2]):
        return None
    sources = {tool_input[key] for key in CELL_SOURCE_FIELDS
               if isinstance(tool_input.get(key), str) and tool_input[key].strip()}
    return next(iter(sources)) if len(sources) == 1 else None


def cell_command(name, tool_input):
    """The ONE literal shell command a Desktop code cell (`exec`, `js`) holds, or None.

    A cell is JavaScript text, not a command: only `host_probe.nested_command`'s shapes (one literal
    `tools.exec_command({...})`, never evaluated) have a command the shell checks can read. Anything
    else - a second call, a nested `apply_patch` or connector call, a cell that also carries a
    `command`/`cmd` field or two different source fields, a non-tool name - is None. `normalize` refuses
    such a cell that holds text (`_read_cell`): its nested calls are not seen by the shell checks, so it
    must neither become a shell call nor pass unchecked under its own name.
    A recognized cell whose command is "" returns "" (not None): `role_policy` refuses it (FR-1).
    Read by `normalize`; `host_probe.probe_command` reads the guard's normalized command instead of
    calling this directly, so the guard and the probe see one command (codex CX1-2)."""
    source = _cell_source(tool_input) if tool_short_name(name) in CELL_TOOLS else None
    if source is None:
        return None
    from host_probe import nested_command
    return nested_command({"type": "custom_tool_call", "name": "exec", "input": source})


# An option `tty` in the literal object of a cell's one exec_command, with any value but a literal false / 0 / null /
# "". Read off the cell's text (the recognizer returns only `cmd`), so a `, tty: 1` inside the command string
# refuses too: the direction is toward the refusal, as a tty session takes input the guard cannot check.
_CELL_TTY = re.compile(r'[{,]\s*"?tty"?\s*:(?!\s*(?:false|null|0|"")\s*[,}])')


def _read_cell(name, tool_input):
    """(command, refusal) of a code cell: the inner command when it is one literal exec_command without a tty;
    (None, None) for a cell with no text at all (`role_policy` names the fields); (None, refusal) for a cell
    with text that is not exactly that, as text or as an object (an unknown is never a pass, FR-59)."""
    texts, refusal = _texts_or_refusal(tool_input)
    if refusal:
        return None, refusal
    inner = cell_command(name, tool_input)
    if inner is None:
        return None, (_refused("a code cell holds more than one call, or a call the guard cannot read",
                               "exactly one literal tools.exec_command call", "send one call per cell")
                      if texts else None)
    if _CELL_TTY.search(_cell_source(tool_input)):
        return None, _refused("a code cell asks for a terminal session (a tty option), which takes input the guard "
                              "cannot check", "a non-interactive tools.exec_command call",
                              "drop the tty option so the command passes the guard")
    return inner, None


def _to_parent_only(tool_input):
    """Whether a message names no agent but the parent: every non-blank value under every recipient alias
    (RECIPIENT_ALIASES - rule 6 reads the same five) is exactly `/root`, or there is none. One other value
    anywhere (`id: /root` beside `to: agent-99`, `/root/x`, `root`) keeps the message under rule 6."""
    values = {str(tool_input.get(key) or "").strip() for key in RECIPIENT_ALIASES}
    return values <= {"", PARENT_RECIPIENT}


def normalize(event):
    if not isinstance(event, dict):
        raise ValueError("hook event must be an object")
    result = copy.deepcopy(event)
    result.pop("_qa_host", None)
    if result.get('agent_type'):
        result['agent_type'] = native_role(result['agent_type'])
    name = str(result.get("tool_name") or "")
    ti = result.get("tool_input") or {}
    short = tool_short_name(name)
    if name and not isinstance(ti, dict):
        if name.endswith("apply_patch") and isinstance(ti, str):
            ti = {"command": ti}
        elif short in SHELL_TOOLS | CELL_TOOLS and isinstance(ti, str):
            ti = {"input": ti}      # a custom tool's input is the call's text: a command, or a cell's code
        else:
            raise ValueError("tool_input must be an object")
    # `codex` is computed from the event WITHOUT a transport record a caller sent (dropped above): is_codex reads it.
    transport = {"name": name, "input": copy.deepcopy(ti), "codex": is_codex(dict(event, _qa_host=None))}
    refusal = None      # a call-shape refusal rides on the transport record; `role_policy` blocks with it
    if short in {"exec_command", "shell_command"} | SHELL_TOOLS:
        # Every command field is joined: the host may run any of them, and a second one must not hide behind the first.
        texts, refusal = _texts_or_refusal(ti)
        if refusal is None:
            result["tool_name"] = "Bash"
            ti = dict(ti, command="\n".join(texts))
    elif short in CELL_TOOLS:
        # Bash only around one literal exec_command; any other cell with text keeps its own name and a refusal:
        # its nested calls (a patch, a connector call) are invisible to the shell checks (FR-59). A cell with NO
        # text is kept for role_policy, whose refusal names the fields.
        inner, refusal = _read_cell(name, ti)
        if inner is not None:
            result["tool_name"] = "Bash"
            ti = dict(ti, command=inner)
    elif short == "apply_patch":
        result["tool_name"] = "apply_patch"
        ti = dict(ti, command=ti.get("command", ti.get("input", "")))
    elif short == "spawn_agent":
        result["tool_name"] = "Agent"
        ti = dict(ti, subagent_type=native_role(ti.get("agent_type") or ti.get("task_name") or ""),
                  prompt=ti.get("message", ti.get("prompt", "")))
        transport["prompt_field"] = "message" if "message" in ti else "prompt"
    elif short in {"send_input", "send_message", "followup_task"}:
        # The desktop's `send_message` only queues a message (a child's progress note to its parent) and
        # cannot start an idle worker, so a note to the PARENT is not a resume (FB-13, TP2-2406).
        # That premise is the host's property, not measured by us (PROJECT.md pt 6a), so the exemption is
        # as narrow as the observation: only a message that names no agent but `/root` under ANY recipient
        # alias. `send_input` and `followup_task` activate the recipient, and a `send_message` to any other
        # recipient is not known to be harmless: all of them stay `SendMessage`, under rule 6. Classified
        # by the native tool name and the recipient only, never by a message field a caller could set.
        result["tool_name"] = "AgentMessage" if short == "send_message" and _to_parent_only(ti) else "SendMessage"
        ti = dict(ti, recipient=ti.get("id") or ti.get("target") or "",
                  content=ti.get("message", ""), type="message")
    if refusal:
        transport["refusal"] = refusal
    result["tool_input"] = ti
    result["_qa_host"] = transport
    return result


def rewritten_input(event, updated):
    """Return only arguments supported by the original tool's schema."""
    transport = event.get("_qa_host") or {}
    if tool_short_name(transport.get("name")) != "spawn_agent":
        return updated
    result = dict(transport["input"])
    result[transport["prompt_field"]] = updated["prompt"]
    if 'task_name' in result:  # desktop schema; CLI uses its native TOML profile
        for key in ('model','reasoning_effort'):
            if updated.get(key): result[key] = updated[key]
        if any(updated.get(key) for key in ('model','reasoning_effort')) and result.get('fork_turns') in (None,'all'):
            raise ValueError('Explicit desktop model/effort overrides require fork_turns=none or a bounded history')
    return result


def patch_operations(command):
    """Read Codex's explicit patch grammar; malformed/unknown sections fail closed."""
    if not isinstance(command, str):
        raise ValueError("apply_patch.command must be text")
    lines = command.strip().splitlines()
    if not lines or lines[0] != "*** Begin Patch" or lines[-1] != "*** End Patch":
        raise ValueError("unsupported patch envelope")
    operations, current = [], None
    for line in lines[1:-1]:
        found = False
        for marker, kind in (("*** Add File: ", "add"), ("*** Update File: ", "update"),
                             ("*** Delete File: ", "delete")):
            if line.startswith(marker):
                path = line[len(marker):].strip()
                if not path or "\x00" in path:
                    raise ValueError("patch path missing or invalid")
                current = {"path": path, "kind": kind, "added": []}
                operations.append(current)
                found = True
                break
        if found:
            continue
        if current is None:
            raise ValueError("patch content before path")
        if line.startswith("*** Move to: "):
            if current["kind"] != "update" or current.get("destination"):
                raise ValueError("invalid patch move")
            current["destination"] = line[len("*** Move to: "):].strip()
            if not current["destination"]:
                raise ValueError("empty move destination")
        elif line.startswith("+"):
            current["added"].append(line[1:])
        elif not (line.startswith((" ", "-", "@@")) or line == "*** End of File" or not line):
            raise ValueError("unsupported patch operation")
    if not operations:
        raise ValueError("patch contains no operations")
    return operations


def mutation_events(event):
    """Include BOTH source and destination of moves, plus every deletion.

    BOTH events of a move carry `patch_move: True`: a test-path permission (guard_app_under_test)
    opens writing test files and nothing else, and a move is a delete plus a write that no single
    event shows on its own."""
    if event.get("tool_name") != "apply_patch":
        return [event]
    result = []
    cwd = Path(event.get("cwd") or Path.cwd())
    for op in patch_operations((event.get("tool_input") or {}).get("command")):
        for raw in [op["path"], *([op["destination"]] if op.get("destination") else [])]:
            path = Path(raw)
            path = path if path.is_absolute() else cwd / path
            tool_input = {"file_path": str(path.resolve()),
                          "content": "\n".join(op["added"]),
                          "patch_operation": op["kind"]}
            if op.get("destination"):
                tool_input["patch_move"] = True
            result.append(dict(event, tool_name="Write" if op["kind"] == "add" else "Edit",
                               tool_input=tool_input))
    return result


def _print_additional_context(name, text):
    """The one place that writes the `hookSpecificOutput.additionalContext` object, with no verdict in it."""
    print(json.dumps({"hookSpecificOutput": {"hookEventName": name, "additionalContext": text}},
                     ensure_ascii=False))


def context_output(event, text):
    if not text:
        return
    if not is_codex(event):
        print(text)
        return
    name = event.get("hook_event_name") or "PostToolUse"
    if name in {"PreToolUse", "PostToolUse", "SessionStart", "UserPromptSubmit", "SubagentStart"}:
        _print_additional_context(name, text)
    else:
        print(json.dumps({"systemMessage": text}, ensure_ascii=False))


def notice_output(event, text):
    """Hand the model a NOTICE that rides beside a tool call's result and never stops the call (SC1-6).

    On Claude Code the channel is `hookSpecificOutput.additionalContext` of a PreToolUse or PostToolUse
    hook, measured in a throwaway project against `claude` 2.1.310: both reach the model as a system
    reminder, while a PreToolUse stderr at exit 0 and a bare PostToolUse stdout do not. The JSON carries NO
    `permissionDecision`: a notice never approves a call the host's permissions would ask about. Codex, and
    any other event name, go through `context_output`, the one channel the package already has there."""
    if not text:
        return
    name = (event or {}).get("hook_event_name")
    if is_codex(event) or name not in ("PreToolUse", "PostToolUse"):
        context_output(event, text)
        return
    _print_additional_context(name, text)


def rewrite_output(event, updated_input, context=""):
    """The ONE writer of the PreToolUse object that allows a call with a REWRITTEN input (AR-5): exactly one JSON
    object on stdout, `permissionDecision: allow` plus `updatedInput`.

    `context` is an advice for the orchestrator about this dispatch (RH1-5 B9). Empty: the output is byte for byte what
    the hook always printed. Non-empty: it is NOT put in `additionalContext` beside `updatedInput` - measured (B0 a,
    claude 2.1.311, a PreToolUse hook on Agent): the rewritten prompt reached the subagent, the `additionalContext` of the
    same object reached nobody. The advice goes to the journal as a `hook_signal` of kind `inject`, which the run report
    reads (`hooklib.person_signal`), so it is never silent."""
    if context:
        from hooklib import person_signal
        person_signal(event, "inject", context)
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "allow",
                                             "updatedInput": updated_input}}, ensure_ascii=False))


def _warn(message):
    print("FACTORY HOST POLICY (warning): " + message, file=sys.stderr)


def _host_tools(cfg):
    """The ONE reader of the `host_tools` block of the project config, validated: `{"read_only": [str],
    "read_only_calls": {tool: [str]}}`. The block is written by a person, so any shape can arrive; a hook
    that raises exits 1, which the host reads as a pass, so NO shape raises here and a shape that is not
    the documented one grants nothing: a string where a list belongs used to permit by SUBSTRING
    (`raw in "<string>"`), a list or a number raised. A wrong container shape or a dropped element
    prints one warning line that names the key, so the person finds the entry that grants nothing."""
    empty = {"read_only": [], "read_only_calls": {}}
    block = cfg.get("host_tools") if isinstance(cfg, dict) else None
    if block is None:
        return empty
    if not isinstance(block, dict):
        _warn(f"host_tools must be an object with read_only and read_only_calls, got {type(block).__name__}; it permits nothing")
        return empty
    read_only, calls = block.get("read_only"), block.get("read_only_calls")
    if read_only is not None and not isinstance(read_only, list):
        _warn(f"host_tools.read_only must be a list of tool names, got {type(read_only).__name__}; it permits nothing")
    if calls is not None and not isinstance(calls, dict):
        _warn(f"host_tools.read_only_calls must map a tool name to a list of regexes, got {type(calls).__name__}; it permits nothing")
    names = [item for item in read_only if isinstance(item, str)] if isinstance(read_only, list) else []
    if isinstance(read_only, list) and len(names) != len(read_only):
        _warn("host_tools.read_only holds entries that are not strings; they permit nothing")
    forms = {}
    for tool, patterns in (calls.items() if isinstance(calls, dict) else ()):
        if isinstance(tool, str) and isinstance(patterns, list):
            forms[tool] = [item for item in patterns if isinstance(item, str)]
            if len(forms[tool]) != len(patterns):
                _warn(f"host_tools.read_only_calls[{tool!r}] holds entries that are not strings; they permit nothing")
        else:
            _warn(f"host_tools.read_only_calls[{tool!r}] must be a list of regexes, got {type(patterns).__name__}; it permits nothing")
    return {"read_only": names, "read_only_calls": forms}


def _read_only_call(tool, tool_input, host_tools):
    """Whether this exact connector CALL is a registered read, when its tool as a whole is not.

    A connector that multiplexes reads and writes through one code-taking tool cannot be
    registered in `host_tools.read_only` without whitelisting its writes too. FB-38
    (TP2-2406): the browser connector's inventory read, `await cua.getState();` on
    `mcp__cua_repl__js`, was refused as arbitrary mutating JavaScript, and the runner had no
    read-only way to find its tab. The project config names the exact call forms instead:

        "host_tools": {"read_only_calls": {
            "mcp__cua_repl__js": ["\\\\s*await\\\\s+cua\\\\.getState\\\\(\\\\s*\\\\)\\\\s*;?\\\\s*"]}}

    `host_tools` is the validated block (`_host_tools`). `read_only_calls` maps a tool name to the regexes
    its `code` (or `input`) must FULLY match (`re.fullmatch`; a partial match never passes); nothing else
    on that tool is a read - not an extra expression after the call, not a comment before it, not a
    different connector with the same code. Fails closed: a field that is not text makes the text "" (a
    pattern that matches "" is then the person's own choice), TWO non-empty code fields are not a
    read (the host may run either), a pattern that does not compile classifies nothing. Risk taken, as
    for every pattern a person writes in the config: a pattern with catastrophic backtracking is not
    time-limited."""
    import re
    patterns = host_tools["read_only_calls"].get(tool) or []
    ti = tool_input if isinstance(tool_input, dict) else {}
    fields = [ti.get("code"), ti.get("input")]
    if any(value is not None and not isinstance(value, str) for value in fields):
        text = ""
    else:
        texts = [value for value in fields if value]
        if len(texts) > 1:
            return False
        text = texts[0] if texts else ""
    for pattern in patterns:
        try:
            if re.fullmatch(pattern, text) is not None:
                return True
        except (re.error, RecursionError, OverflowError):
            continue
    return False


def _carries_no_command(event):
    """Whether a call of the shell/cell family (`shell`, `local_shell`, `exec`, `js`) reached the guard with
    no command text it can read: the normalized command is blank, or the call kept its own name. `normalize`
    renames every call of the family it can read, and records a refusal (which `role_policy` raises first)
    for one that holds text it cannot, so a call that kept its name here holds no text at all. Such a call
    is refused, never passed unchecked. Other tools, and `exec_command` without `cmd` (as before), are not
    this rule's."""
    native = event.get("_qa_host") or {}
    if tool_short_name(native.get("name")) not in SHELL_TOOLS | CELL_TOOLS:
        return False
    if event.get("tool_name") != "Bash":
        return True
    tool_input = event.get("tool_input")
    return not str((tool_input if isinstance(tool_input, dict) else {}).get("command") or "").strip()


_READ_HEAD = re.compile(r"(?:rg|cat|ls|pwd|Get-Content|Get-ChildItem|Select-String)(?:\s|$)")
# What a read command may not hold even inside quotes (the shell's own forms the tokenizer does not model are
# `hooklib.SHELL_OPAQUE_BAN`, read first): a substitution, a redirect, a backtick, a line end.
_READ_BAN = re.compile(r"[`$<>\r\n]")
# What makes a read command run another program (`rg --pre`, `find -exec`) is ONE table for the runner guard, this read
# guard and the launch matcher: launch-causes.json `reader_runs`, read through `hooklib.reader_runs` (CX1-20 M-5, FR-13).
# This guard asks it for its own read heads only, after the quote and escape characters are out of the word.
_READ_DOOR = ("One plain read command passes: `rg -n '<pattern>' <path>` or `Get-Content <path>`. A quoted pattern "
              "may hold | ; & ( ) inside ASCII quotes; $ < > a backtick, a newline and a typographic quote are refused "
              "even quoted; there is no pipe, no chaining and no redirect outside quotes, and never rg --pre.")


# What a role without Bash does on Codex Desktop (TP2-2406 S3-4, 16.10): the child's `exec` cell holds
# `tools.exec_command`, `tools.apply_patch` and `tools.mcp__codex_app__*`; no tool named Read, Grep, Glob, Write or Edit
# exists there, and every other text of the factory names only those. This is the ONE place that says how such a role
# reads and edits on that host: the role's injected instructions (inject_context.py), the no-shell card of its brief
# (brief_pack.NO_SHELL_HEAD) and the refusals of `role_policy` carry it verbatim. What a read may hold is `_READ_DOOR`,
# the one wording of that limit (FR-10): a change to `_is_one_plain_read` is a change to that line, and so to this text.
# Plain ASCII, at most 900 characters (the refusal and the injection carry it whole).
CODEX_DESKTOP_TOOLS = (
    "On Codex Desktop there is no Read, Grep, Glob, Write or Edit tool. Read or search a file with tools.exec_command "
    "running ONE plain command. " + _READ_DOOR + " Any other shell command is refused. "
    "Edit a file you may write with tools.apply_patch: an Update File hunk with real context lines (the host "
    "refuses an empty hunk). Create a NEW file with tools.apply_patch and an *** Add File: <path> hunk (the guard "
    "reads it as Write and applies the same write rules). Connector and app tools (tools.mcp__codex_app__*, "
    "open_in_codex) are not file access.")


def tools_line(text):
    """The tools a role file's frontmatter `tools:` line grants, as a set of names: split on commas, each stripped,
    empty names dropped. The ONE way the factory splits that line; the parse is `hooklib.parse_frontmatter`, so the
    line is read in the frontmatter only (a `tools:` in the body grants nothing), the LAST `tools:` of the frontmatter
    wins, an empty `tools:` line grants nothing (never the line after it), and a BOM before the frontmatter is
    skipped. No frontmatter, no `tools:` key or an empty value -> `frozenset()`. `Bash(git:*)`, `bash` and
    `[Read, Bash]` are not `Bash`: the host's tool names are case-sensitive and a list in brackets is not parsed, so
    the doubt falls toward no Bash."""
    meta = parse_frontmatter(str(text or "").lstrip(chr(0xFEFF))) or {}
    return frozenset(name.strip() for name in str(meta.get("tools") or "").split(",") if name.strip())


def role_tools(role, plugin_root=None):
    """The tools a role's file grants (`tools_line` of `<plugin_root or hooklib.PLUGIN_ROOT>/agents/<role>.md`, read
    as UTF-8 with a BOM skipped), or None when the role has no readable file (no role, no file, a directory, no
    permission). The ONE reader of a role's tools; `role_has_bash` and `role_policy` (what the guard refuses), the
    texts written to a role (launch prompt, brief, injection, the driver's note) and the audits all ask it.

    The default of every consumer when the role has no `tools:` line, or its file is absent:

    | consumer                                   | no file (None)             | file, no / empty / unparsed line | error goes toward   |
    | `role_policy` (what the guard refuses)     | not a factory role         | no Bash: one plain read          | refusal             |
    | `guard_pre_tool.role_ways` (edit doors)    | both doors (Edit, Bash)    | Codex {Edit}; Claude both (an    | naming a door       |
    |                                            |                            | estimate, not measured here)     |                     |
    | launch prompt, brief, injection, driver    | no Bash                    | no Bash                          | a usable text       |
    | A23, A2, A19 (audits)                      | skipped (not a role)       | reported                         | reported            |
    | A2b (excess write right)                   | skipped                    | skipped (no right to report)     | -                   |

    A text for a role never names a command the guard would refuse it (Edit is in every role's tools), so a text
    treats a role of no known tools as having no Bash. `plugin_root` is for a caller that checks another copy."""
    from hooklib import PLUGIN_ROOT
    path = (plugin_root or PLUGIN_ROOT) / "agents" / (role_name(role) + ".md")
    try:
        text = path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return None
    return tools_line(text)


def role_has_bash(role, plugin_root=None):
    """Whether the role's file lists Bash; False for a role with no readable file, no `tools:` line or an empty one.
    A caller that must tell a role without Bash from no role at all asks `role_tools(...) is None` first."""
    return "Bash" in (role_tools(role, plugin_root) or ())


def _read_refusal(command):
    """Why `command` is not ONE plain read command (rg, cat, Get-Content ...) - no chaining, no substitution, no
    program launch, the only shell call a role without Bash may make - or "" when it is one.

    TP2-2406 S3-3 (15.10): `rg -n -A 8 -B 2 '"id":"TS-(1|2|3|4|8)"' <plan>` was refused because a plain
    character search for `; & | ( )` ignored the quotes, the strategist halted on the refusal and its plan was never
    changed. Those five are now judged by `hooklib.command_segments`, the one shell tokenizer (SIBLING_MAP axis 11),
    in BOTH dialects: exactly one segment, or it is refused - a `|` or `;` INSIDE quotes is
    text, an unquoted one is an operator. The error direction is refusal: a doubt in either dialect refuses, and so
    does every form the shell reads differently from the tokenizer (`SHELL_OPAQUE_BAN`: a read guard that lets a
    cut piece through frees whatever the shell runs). A `#` comment is skipped (bash and PowerShell both skip it)."""
    text = str(command or "")
    if not text.strip():
        return "the command is empty"
    if not _READ_HEAD.match(text.strip()):
        return "it does not start with a read command (rg, cat, ls, pwd, Get-Content, Get-ChildItem, Select-String)"
    what, door = shell_opaque_found(text)
    if what:
        return f"it holds {what}, which the shell reads differently from the guard; {door}"
    banned = _READ_BAN.search(text)
    if banned:
        shown = "a line end" if banned.group() in "\r\n" else f"`{banned.group()}`"
        return (f"it holds {shown}, which starts a substitution, a redirect or a second command even inside quotes; "
                "write the command without it")
    for dialect in ("bash", "powershell"):
        # a `$( )` or backtick region cannot reach this line: `_READ_BAN` holds `$` and the backtick, the only forms
        # that open one, so only the segment count is read (CX1-19 revisits it when the tokenizer's regions change)
        segments = command_segments(text, dialect)[0]
        if len(segments) != 1:
            return ("it holds more than one command (read as " + dialect + "): `| ; & ( )` outside ASCII quotes "
                    "separate commands; put the pattern in quotes or send one command per call")
        found = reader_runs([word for word, _quoted in segments[0]])   # `rg --p\re python x f` is `--pre` to bash
        if found is not None:
            return f"it passes `{found[0]}`, which makes the read command run another program; search without it"
    return ""


def _is_one_plain_read(command):
    """Whether `command` is ONE plain read command - see `_read_refusal` for the grounds."""
    return not _read_refusal(command)


def role_policy(event, cfg):
    """Enforce Claude role tool intent on Codex's broader native tool surface.

    A connector tool (`mcp__<server>__<tool>`) passes as a read by its NAME (`host_tools.read_only`,
    or a get/list/read/... operation) or by its exact CALL (`host_tools.read_only_calls`, see
    `_read_only_call`); anything else is a write and goes through a proposal."""
    from hooklib import PLUGIN_ROOT, block
    transport = event.get("_qa_host")
    refused = transport.get("refusal") if isinstance(transport, dict) else None
    if isinstance(refused, dict):
        # First, before the no-config return: a call the guard cannot read fails closed in a project with no config
        # too, as the guard's own parse block does. Its text names what is wrong, what was expected and the door.
        block("FACTORY HOST POLICY: {what}. Expected: {expected}. Door: {door}.".format_map(
            {key: str(refused.get(key) or "") for key in ("what", "expected", "door")}))
    if not is_codex(event) or not cfg:
        return
    if event.get('factory_diagnostic'):
        block('FACTORY DOCTOR: the context diagnostic must return its challenge without tools')
    if _carries_no_command(event):
        block("FACTORY HOST POLICY: " + str((event.get("_qa_host") or {}).get("name")) + " carried no command text the "
              "guard can read (expected " + FIELD_WORDS + "); the call is refused unchecked. Send the "
              "command in one of those fields; inside a code cell, as one literal tools.exec_command({cmd: ...}) call.")
    role = role_name(event.get("agent_type") or "")
    path = PLUGIN_ROOT / "agents" / (role + ".md")
    name = event.get("tool_name") or ""
    # A factory role is a role with an agent file (a caller with none, the orchestrator, is not bound by a role's tools).
    # `role_has_bash` is asked once per event, for both branches below: a role without Bash (no `tools:` line, an empty
    # one and an unreadable file included) is the one the read rule and the connector text speak to.
    no_shell = path.is_file() and not role_has_bash(role)
    if path.is_file():
        if name in {"Agent", "Task"}:
            block("FACTORY ROLE: nested delegation is not permitted for " + role)
        if name in {"Bash", "PowerShell"} and no_shell:
            command = str((event.get("tool_input") or {}).get("command") or "")
            why = _read_refusal(command)
            if why:
                block("FACTORY ROLE: " + role + " may read using rg/Get-Content without shell chaining; arbitrary shell "
                      "execution is not permitted: " + why + ". " + CODEX_DESKTOP_TOOLS)
    native = event.get('_qa_host') or {}
    raw_name = tool_short_name(native.get('name') or name)
    if raw_name == 'write_stdin' and (event.get('tool_input') or {}).get('chars'):
        block('FACTORY HOST POLICY: interactive shell input cannot be checked as a standalone command; use a guarded exec_command call')
    if raw_name == 'exec_command' and (event.get('tool_input') or {}).get('tty'):
        block('FACTORY HOST POLICY: use non-interactive shell calls so every command passes the guard')
    raw = str((event.get("_qa_host") or {}).get("name") or name)
    if raw.startswith("mcp__"):
        operation = raw.rsplit("__", 1)[-1]
        host_tools = _host_tools(cfg)
        if (raw not in host_tools["read_only"] and not _read_only_call(raw, event.get("tool_input"), host_tools)
                and not re.match(r"^(?:get|list|read|search|find|fetch|view|describe)(?:_|$)", operation)):
            lead = ("FACTORY HOST POLICY: unclassified or mutating connector tool " + raw +
                    "; external writes require a proposal and the gated executor.")
            if no_shell:
                # `host_tools.read_only` is the orchestrator's door: a role without Bash registers nothing, so its
                # refusal names what that role has instead (FR-2). A role WITH Bash and a caller with no agent file keep
                # the text they always had - the constant says "any other shell command is refused", false for them.
                block(lead + " " + CODEX_DESKTOP_TOOLS)
            block(lead + " The orchestrator registers verified read-only tools in host_tools.read_only, or the exact "
                  "call forms of a code-taking tool in host_tools.read_only_calls.")


# How a host hands a subagent's final report back, as data (AR-1, AR-5): the file holds the tool name, the
# acknowledgement form, the sidecar's finished marker and the completion event's name; `report_forms` below is the
# ONE reader. The path is a module name so a test can point it at a copy; nothing else rebinds it.
REPORT_FORMS_FILE = Path(__file__).resolve().parents[1] / "references" / "host-report-forms.json"


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _ack_form(value):
    """`{"field": <text>, "value": <bool | text | number>}`: the host's acknowledgement of a handback call."""
    return (isinstance(value, dict) and _text(value.get("field"))
            and isinstance(value.get("value"), (bool, str, int, float)))


def _marker_form(value):
    """`{"file_suffix": <text>, "field": <text>}`: the sidecar file beside a transcript, and the field it keeps."""
    return isinstance(value, dict) and _text(value.get("file_suffix")) and _text(value.get("field"))


def _person_turn_form(value):
    """`{"flags": [<text>, ...], "notification_prefixes": [<text>, ...]}`: which `user` rows are not the person's turn.
    Both lists must hold at least one text: an empty list would read every such row as the person's, the wrong
    direction for a row that exists to exclude (AR-28)."""
    return (isinstance(value, dict)
            and all(isinstance(value.get(key), list) and value[key] and all(_text(item) for item in value[key])
                    for key in ("flags", "notification_prefixes")))


# The rows each host's readers (`dispatch_liveness`, `cost_capture`) need, with the shape of each. A host whose rows are not
# all there in this shape has NO forms, and its caller then gives the answer it gave before the rows existed.
_HOST_ROWS = {"claude": {"handback_tool": _text, "handback_ack": _ack_form, "finished_marker": _marker_form,
                         "not_a_person_turn": _person_turn_form},
              "codex": {"completion_event": _text}}


def report_forms(path=None, host=None):
    """(forms, reason): the parsed `references/host-report-forms.json`, or (None, why) when it cannot be trusted.

    The ONE reader of that file (AR-13): the context probe (`host_probe._assistant_texts`) and the dispatch
    liveness read the host's return forms through it. It never raises, because its callers sit on hook and gate
    paths where an exception is not a block. A file that is absent, unreadable, not JSON, not an object, or whose
    `claude.handback_tool` is not a non-empty string gives (None, reason) and the caller takes NO tool call for a
    handback: a missing form must never make a probe pass (AR-28), so the safe direction is "unverified". There
    is no default in code - a default would be the tool name this file exists to keep out of code (AR-1).

    `host` asks for ONE host's whole set of rows (`claude`: the tool, the acknowledgement, the finished marker and
    the rule of which `user` rows are not the person's turn; `codex`: the completion event). A row of that host missing or of the wrong type, and a host nobody reads, is
    (None, reason) for that host only - another host's malformed row does not take it away. Without `host` only
    `claude.handback_tool` is judged, as the context probe has always read it."""
    target = Path(path) if path is not None else REPORT_FORMS_FILE
    try:
        forms = json.loads(target.read_text(encoding="utf-8"))
    except Exception as error:  # noqa: BLE001 - OSError, a decode error, bad JSON, a RecursionError: none may escape
        return None, f"host report forms unreadable ({target.name}): {error.__class__.__name__}"
    if host is not None:
        rows = _HOST_ROWS.get(host)
        if rows is None:
            return None, f"host report forms have no reader for the host {host!r} ({target.name})"
        section = forms.get(host) if isinstance(forms, dict) else None
        bad = [name for name, ok in rows.items() if not isinstance(section, dict) or not ok(section.get(name))]
        if bad:
            return None, f"host report forms hold no usable {', '.join(f'{host}.{name}' for name in bad)} ({target.name})"
        return forms, ""
    claude = forms.get("claude") if isinstance(forms, dict) else None
    tool = claude.get("handback_tool") if isinstance(claude, dict) else None
    if not isinstance(tool, str) or not tool.strip():
        return None, f"host report forms hold no usable claude.handback_tool ({target.name})"
    return forms, ""


LAUNCH_ID_ROW = "launch_id_keys"


class LaunchIdRowRefused(ValueError):
    """The data row naming the launch-id keys of the host's `Agent` answer cannot be read. Raised, never defaulted: with
    no row the factory does not know which key is the id, and a guessed key would bind or refuse by luck (FR-59)."""


def launch_id_keys(path=None) -> list:
    """The keys of the host's `Agent` answer that carry the launch id, in priority order: the row `launch_id_keys` of
    `references/host-report-forms.json` (AR-1, AR-5). Raises `LaunchIdRowRefused`, naming the file and the key, when the
    file is unreadable or the row is absent, not a non-empty list of non-empty texts. No default in code."""
    target = Path(path) if path is not None else REPORT_FORMS_FILE
    try:
        row = json.loads(target.read_text(encoding="utf-8")).get(LAUNCH_ID_ROW)
    except Exception as error:  # noqa: BLE001 - OSError, a decode error, bad JSON, a file that is no object: all one refusal
        raise LaunchIdRowRefused(f"{target.name} cannot be read for the row `{LAUNCH_ID_ROW}` "
                                 f"({error.__class__.__name__}); restore the file from the package") from error
    if not isinstance(row, list) or not row or not all(_text(item) for item in row):
        raise LaunchIdRowRefused(f"{target.name} holds no usable row `{LAUNCH_ID_ROW}` (expected a non-empty list of key names, "
                                 "in priority order); restore the file from the package")
    return list(row)


def launch_id_of(response, path=None):
    """The launch id the host's answer to `Agent` carries, or None: the value of the FIRST key of the row
    `launch_id_keys` that holds a non-empty string (an empty or blank value counts as absent; a number is no id). The ONE
    reader of that field (AR-13): `host_dispatch.record` (the Codex hook) and `agent_autobind` (the Claude hook) read the id
    through it, and the doctor's probe is bound from the id they read (`host_probe.note_probe_launch`). An answer that is
    not an object carries none. A row that cannot be read raises `LaunchIdRowRefused`."""
    keys = launch_id_keys(path)
    if not isinstance(response, dict):
        return None
    for key in keys:
        value = response.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return None


def handback_input_texts(value) -> list:
    """Every string inside a handback call's `input`, however the host nests it (`message`, a `report`, a list of
    parts). Nothing else is interpreted (FR-12); a number, a null or an empty container gives nothing."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [t for v in value.values() for t in handback_input_texts(v)]
    if isinstance(value, list):
        return [t for v in value for t in handback_input_texts(v)]
    return []


def assistant_row_blocks(row) -> list:
    """The content blocks of ONE transcript row, both host shapes: Claude `type: assistant` + `message.content`,
    Codex `response_item` + `payload.role == 'assistant'`. A string content is one text block; a row that is not an
    assistant's, or not an object, gives []; a block that is not an object is dropped. The ONE place the row shapes
    are told apart (AR-13): `assistant_row_texts` and the probe's tool-call census are built on it."""
    if not isinstance(row, dict):
        return []
    payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
    message = row.get("message") if isinstance(row.get("message"), dict) else {}
    kind = row.get("type")
    if kind == "assistant" and message:
        content = message.get("content")
    elif kind == "response_item" and payload.get("role") == "assistant":
        content = payload.get("content")
    else:
        return []
    blocks = [{"text": content}] if isinstance(content, str) else content if isinstance(content, list) else []
    return [block for block in blocks if isinstance(block, dict)]


def handback_name(forms):
    """The handback tool's name from the forms (`claude.handback_tool`), or None when the forms give no usable one."""
    claude = forms.get("claude") if isinstance(forms, dict) else None
    name = claude.get("handback_tool") if isinstance(claude, dict) else None
    return name if isinstance(name, str) and name.strip() else None


def assistant_row_texts(row, forms=None) -> list:
    """The texts of ONE transcript row (`assistant_row_blocks`: both host shapes). A row that is not an assistant's,
    or not an object, gives [].

    A text block gives its text (a block with no text gives ''), a string content gives itself, and a tool call
    whose name is EXACTLY `forms["claude"]["handback_tool"]` gives every string of its `input` - the host's
    way of returning a child's report. No other call is read, and a name that merely resembles it is not the
    handback. With `forms` None or without a usable handback name NO call is a handback: only text blocks are read
    (the safe side - a word not found, never a word invented, AR-28). The ONE row reader of the two callers that
    need a role's own words: `host_probe._assistant_texts` (strict about unreadable rows) and
    `exit_gate.handoff_digest` (skips them) - the strictness stays with the caller (AR-13, axis 22)."""
    handback = handback_name(forms)
    texts = []
    for block in assistant_row_blocks(row):
        if handback and block.get("type") == "tool_use" and block.get("name") == handback:
            texts.extend(handback_input_texts(block.get("input")))
            continue
        texts.append(str(block.get("text") or ""))
    return texts


def _is_handback_call(block, handback) -> bool:
    return block.get("type") == "tool_use" and block.get("name") == handback


def ended_in_text_after_handback(path, forms, tail_rows) -> bool:
    """Did a role that already handed its report back end its LAST turn in plain text (HF8-15 (1))?

    A role resumed after its handback is told to hand its new report back with the host's handback call again; one
    that answers in text instead leaves the conductor with nothing it can take (the host's return form is the call).
    True when, in the last `tail_rows` lines of the transcript at `path`: an assistant row holds a call of the
    handback tool (`forms["claude"]["handback_tool"]`, EXACTLY), a LATER assistant row holds text, and the LAST
    non-empty assistant row (a text or a tool call; a row of thinking only is empty) holds text and no handback
    call. One row that holds both the call and the text is a handback, not a text end (it is also the last row).

    Errors go to False, the side of "no refusal": a path that is not readable, a line that is not JSON, forms with no
    usable handback name, a transcript with no earlier handback - the role has nothing to repair, and the caller
    reads the unknown as "not returned" (AR-28). A handback older than `tail_rows` lines is not seen: the limit is
    the caller's, the same one `exit_gate.handoff_digest` reads the role's word with, and a miss beyond it is the
    allowed direction of error. The reader of one row's blocks is `assistant_row_blocks` (AR-13); the name of the
    call is data (AR-1). Codex rows have no handback call in the forms: always False there."""
    handback = handback_name(forms)
    if not handback or not isinstance(path, str) or not path.strip():
        return False
    try:
        lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return False
    seen_call = text_after = False        # a handback call seen; text seen after it
    last_has_call = last_has_text = None  # the last non-empty assistant row
    for line in lines[-tail_rows:]:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        blocks = assistant_row_blocks(row)
        calls = any(_is_handback_call(block, handback) for block in blocks)
        text = any(block.get("type", "text") == "text" and str(block.get("text") or "").strip() for block in blocks)
        if not calls and not text and not any(block.get("type") == "tool_use" for block in blocks):
            continue
        if text and seen_call:
            text_after = True
        seen_call = seen_call or calls
        last_has_call, last_has_text = calls, text
    return bool(seen_call and text_after and last_has_text and not last_has_call)


def subagent_transcript_of(session_transcript, names):
    """The subagent transcript of the session whose own transcript is `session_transcript`, for the first of `names`
    that has one, or None. The host keeps a session's children beside its transcript, as
    `<its folder>/<its name without the extension>/subagents/agent-<name>.jsonl` (the layout
    `hooklib.story_subagent_transcripts` reads from the cost files). This is the question "is this receipt this
    session's?": a receipt whose agent has no transcript there is another session's, and a conductor never takes
    another's work. A name that is not one path component names nothing; unreadable input gives None (AR-28)."""
    try:
        parent = Path(str(session_transcript))
        if not str(session_transcript).strip() or not parent.name:
            return None
        folder = parent.parent / parent.stem / "subagents"
        for name in names:
            if isinstance(name, str) and name and not re.search(r"[\\/:]|^\.+$", name):
                found = folder / f"agent-{name}.jsonl"
                if found.is_file():
                    return found
    except (OSError, ValueError):
        return None
    return None
