"""The factory's single PreToolUse guard: app boundary + secrets in ONE process.

Why one entry point instead of two hooks. A measurement of a live story run
(17:06-20:10, 351 Bash/PowerShell calls): every python start on Windows costs ~1.07s,
and that was paid on every tool call. On Write|Edit two interpreters started back to
back - here they are merged into one. On Bash|PowerShell a shell prefilter used to sit
ahead of python in settings.json; the plugin ships no settings.json (a plugin's hooks.json
commands run directly), so the SAME fast exit now lives in Python, as the very first thing
main() does for these tool names (hooklib.needs_guard): the guard can only fire on a
write-capable command / a direct test launch / a protected-path mention, and such
commands are the minority of Bash/PowerShell calls - the rest pay no further cost.

The order of checks is preserved: app boundary (P-00) first, then secrets, then the
quiet-runs check. All three are fail-closed: an unparsed event blocks the call.
"""
import fnmatch
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from hooklib import (  # noqa: E402
    EXPANSION_RE, HEREDOC_RE, PLUGIN_ROOT, WALKER_DOOR, WalkerError, argv_text, block, body_of, cut_bodies, direct_test_form,
    has_write_marker, is_direct_test_run, launch_readings, load_config, needs_guard, project_root, read_event, role_name,
    run_forms_diagnostics_text, scan_bodies, state_dir, subagent_type,
)
import case_forms  # noqa: E402  (pure: no factory import, no config read - safe in a hook)
import guard_app_under_test as app_guard  # noqa: E402
import guard_secrets as secrets_guard  # noqa: E402


# --- a fail-closed refusal that fires twice in a row is a diagnosis, not a dead end --
#
# Two of this guard's refusals are closed to a person's word on purpose: the event did not
# parse, or the patch could not be read, so the app-boundary and secrets checks never ran and
# the guard cannot know what it would be letting through. A word that passed them would open
# exactly the hole they exist for. But if the defect is in the GUARD — it stops parsing
# ordinary events of this host — the factory stands still and the person's word cannot move
# it either, and the orchestrator's only remaining move is to offer them a line to edit
# inside the plugin. So the second one in a row, on a DIFFERENT call, stops being an answer
# about the call and becomes a diagnosis about the guard: owner factory, one line to the
# person, qa-doctor, and a finding written by code. The count lives in
# `<project>/qa-factory/state/guard-escalation/<session>.json` and is disposable, exactly
# like the turn counter beside it: delete the directory and every count starts again.
ESCALATES_AFTER = 2
REPEAT_WARNING = (" If the next call is refused the same way, the factory stops with a "
                  "diagnosis instead of repeating this refusal.")


def _escalation_path(event: dict | None, session: str) -> Path:
    safe = "".join(c for c in str(session or "") if c.isalnum() or c in "-_")[:64]
    return state_dir(event) / "state" / "guard-escalation" / f"{safe or 'unknown'}.json"


def _escalation_count(refusal_id: str, event: dict | None, call_key: str) -> int:
    """How many of these in a row in this session, counting this one. 0 = not counted.

    Never creates `qa-factory/`: a project with no config.json is not this factory's, and a
    hook that brought a state tree into existence by guessing is the TP1-14336 defect."""
    try:
        root = state_dir(event)
        if not (root / "config.json").is_file():
            return 0
        session = str((event or {}).get("session_id") or os.environ.get("CLAUDE_SESSION_ID")
                      or "unparsed")
        path = _escalation_path(event, session)
        try:
            prior = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            prior = {}
        prior = prior if isinstance(prior, dict) else {}
        same = prior.get("refusal") == refusal_id
        if same and prior.get("call") == call_key:
            return int(prior.get("count") or 1)  # the identical call retried is one call
        count = (int(prior.get("count") or 0) if same else 0) + 1
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"refusal": refusal_id, "count": count, "call": call_key,
                                    "at": datetime.now(timezone.utc).isoformat(timespec="seconds")},
                                   ensure_ascii=False), encoding="utf-8")
        return count
    except Exception:
        return 0  # a counter is never allowed to change a guard decision


def _record_escalation_finding(refusal_id: str, event: dict | None, witness: str) -> None:
    """The finding is about the factory, so the factory records it — not the person.

    The witness carries FACTS ABOUT the call (tool name, path, exception class), never the
    content of the patch: this refusal fires precisely because that content was not checked
    for secrets."""
    try:
        import project_decisions
        session = str((event or {}).get("session_id") or "unparsed")
        project_decisions.add_finding(
            state_dir(event).parent,
            essence=f"{refusal_id}: the pre-tool guard refused {ESCALATES_AFTER} calls in a "
                    "row for the same unparseable input — the guard, not the calls",
            scope="local-urgent", witness=str(witness or "no witness")[:400],
            idempotency_key=f"guard-escalation:{refusal_id}:{session}")
    except Exception:
        pass  # a backlog row is never worth raising out of a hook


def escalate(refusal_id: str, event: dict | None, witness: str = "", call_key: str = "") -> str:
    """"" on the first refusal; the diagnosis to append to the message on the second."""
    count = _escalation_count(refusal_id, event, call_key or f"pid-{os.getpid()}")
    if count < ESCALATES_AFTER:
        return ""
    _record_escalation_finding(refusal_id, event, witness)
    return (f"\n\nTHIS IS REFUSAL {count} IN A ROW of the same kind in this session, on a "
            f"different call: the defect is in the guard, not in what was asked. Owner: the "
            f"FACTORY. Nothing here is the person's to repair and no plugin file is to be "
            f"edited. Stop instead of repeating: tell them in one line that `{refusal_id}` "
            f"fired twice and the story is stopped, then run `/qa-factory:qa-doctor`. The "
            f"finding is in qa-factory/factory-backlog.md.")


# --- what a command DOES, as opposed to what it merely carries ---------------------------
#
# 2026-09-23, this factory's own session: a subagent wrote a scratch file through a Bash
# heredoc; the file held a Jira comment that QUOTED `waiver.py --stage S9 --block "still
# running"` as an example of the call a person makes. `human_word_check` matched that literal
# anywhere in the command string, heredoc body included, and refused the write. The agent then
# routed around the guard with a placeholder and a `perl` substitution — exactly the move this
# factory forbids roles to make — and the host raised a security warning. A guard that blocks
# TEXT teaches roles to evade it, and an evaded guard protects nothing.
#
# So every substring check in this file matches against the EXECUTABLE part of the command.
# Text is what a command carries:
#   * a heredoc body, unless the command receiving it is an interpreter: `cat > note.md
#     <<'EOF'` stores its body, `python - <<EOF` RUNS it;
#   * a PowerShell here-string (`@'` … `'@`, `@"` … `"@`) and a bash here-string (`<<< "…"`);
#   * the quoted arguments of a command whose whole job is to emit them (`echo`, `printf`,
#     `Write-Output`, `Set-Content`, `Add-Content`, `Out-File`).
# Executable on purpose, against the letter of the plan row: the string handed to `-c` /
# `-Command`. `bash -c "python waiver.py --stage S9 …"` is a call however it is quoted, and
# calling it text would turn this helper into the bypass it exists to close. Nesting is not
# unwrapped either — `bash -c "echo 'waiver.py --stage'"` is still refused. Over-blocking one
# step inside an interpreter costs a rephrase; under-blocking is the hole.
_INTERPRETERS = ("python", "python3", "python2", "py", "pwsh", "powershell", "bash", "sh",
                 "zsh", "ksh", "dash", "cmd", "node", "perl", "ruby", "php")
_TEXT_COMMANDS = ("echo", "printf", "write-output", "write-host", "set-content",
                  "add-content", "out-file")
_SEPARATORS = (";", "&", "|", "\n", "(", ")", "{", "}")
# Text that the shell will expand is not text: `echo "$(python waiver.py --stage S9)"` prints
# nothing and RUNS the call, and an unquoted heredoc delimiter expands its body the same way.
# Any of these markers inside a region this helper would discount keeps that region executable.
_EXPANSION_RE = EXPANSION_RE   # one spelling, in hooklib beside the scan that needs it too (OH3-22)


def _head_of_segment(src: str, pos: int) -> list:
    """The command words standing before `pos` in the same simple command, lowercased and
    reduced to their basenames. Used only to ask what kind of command is about to receive a
    heredoc, so a separator inside a quoted string is an acceptable miss."""
    start = max((src.rfind(sep, 0, pos) for sep in _SEPARATORS), default=-1)
    words = re.findall(r"[^\s'\"|;&<>()]+", src[start + 1:pos])
    return [w.rsplit("/", 1)[-1].rsplit("\\", 1)[-1].lower() for w in words]


def _receiver_runs_it(src: str, pos: int) -> bool:
    return any(word in _INTERPRETERS for word in _head_of_segment(src, pos))


def _split_off_bodies(src: str) -> tuple:
    """Pass one: heredocs and here-strings out of the executable run. This is the ADVICE reading of the records of
    `hooklib.scan_bodies` (the one scan of where a body starts and ends, OH3-22): an interpreter's heredoc body stays, a
    `<<<` word or a body that expands stays, whatever else is text comes out. The stage guard reads the same records with a
    stricter decision of its own (`stage_guard._executable_text`: a body comes out of a GATE only when the shell surely
    stores it), so the two never differ about where a body is. A heredoc body sits on its own lines, so the pieces around it
    join with a newline; a here-string is written INLINE and never ends a shell segment, so the pieces around it join with a
    space (`hooklib.cut_bodies`; B-404 E17)."""
    taken: list = []
    text: list = []
    where: list = []
    # a `<<<` the receiver test or an expansion refuses is no record: the scan re-reads it one character later, as always
    for record in scan_bodies(src, lambda at_src, at, word: not _receiver_runs_it(at_src, at) and not _EXPANSION_RE.search(word)):
        body = body_of(src, record)
        if record.kind == "ps_herestring":
            ok, label = not _EXPANSION_RE.search(body), "a PowerShell here-string"
        elif record.kind == "herestring":
            ok, label = True, "a here-string"
        else:
            # `<<EOF` (delimiter unquoted) expands its body; `<<'EOF'` hands it over as it stands. Only the second is text,
            # and only when nothing in it expands. An interpreter's body stays executable, quoting and all.
            ok = not _receiver_runs_it(src, record.op_at) and (record.quoted_delimiter or not _EXPANSION_RE.search(body))
            label = "a heredoc body"
        if ok:
            taken.append(record)
            text.append(body)
            where.append(label)
    return cut_bodies(src, taken)[0], text, where


def _segments(src: str) -> list:
    """`src` cut at the shell's command separators, quotes respected."""
    out: list = []
    i, n, start, quote = 0, len(src), 0, ""
    while i < n:
        ch = src[i]
        if quote:
            if ch == "\\" and quote == '"' and i + 1 < n:
                i += 2
                continue
            if ch == quote:
                quote = ""
            i += 1
            continue
        if ch in "'\"":
            quote = ch
        elif ch in ";&|\n()":
            out.append(src[start:i])
            start = i + 1
        i += 1
    out.append(src[start:])
    return out


def _split_off_emitted(src: str) -> tuple:
    """Pass two: the quoted arguments of a command that only prints or stores them."""
    keep: list = []
    text: list = []
    where: list = []
    for segment in _segments(src):
        words = re.findall(r"[^\s'\"|;&<>()]+", segment)
        head = words[0].rsplit("/", 1)[-1].rsplit("\\", 1)[-1].lower() if words else ""
        if head not in _TEXT_COMMANDS:
            keep.append(segment)
            continue
        i, n, kept = 0, len(segment), 0
        while i < n:
            if segment[i] in "'\"":
                closing = segment.find(segment[i], i + 1)
                if closing == -1:
                    break  # an unbalanced quote is not a string this guard may discount
                inner = segment[i + 1:closing]
                if _EXPANSION_RE.search(inner):
                    i = closing + 1
                    continue  # `echo "$(...)"` prints nothing and runs the call
                keep.append(segment[kept:i])
                text.append(inner)
                where.append(f"a quoted argument of `{head}`")
                kept = i = closing + 1
                continue
            i += 1
        keep.append(segment[kept:])
    return "\n".join(p for p in keep if p), text, where


def command_text_parts(command: str) -> dict:
    """Split a shell command into what will RUN and what it only carries.

    `{"exec": …, "text": …, "where": [names of the text regions found]}`. Every substring
    check below matches `exec` only and names `where` in its refusal, so a false positive is
    visible from the refusal's first line instead of costing a role a detour. An argv list is read as its
    joined line (`hooklib.argv_text`), never as `str(list)` (CX1-20 Q-9)."""
    src = argv_text(command)
    stage_one, text, where = _split_off_bodies(src)
    stage_two, more_text, more_where = _split_off_emitted(stage_one)
    return {"exec": stage_two, "text": "\n".join(text + more_text), "where": where + more_where}


def where_clause(parts: dict) -> str:
    """The sentence a refusal appends to say WHERE it matched."""
    seen = list(dict.fromkeys(parts.get("where") or []))
    if not seen:
        return " Found in the command's arguments."
    return (" Found in the command's arguments; " + ", ".join(seen)
            + " in the same command is text and was not checked.")


RUNS_MSG = ('PRE-TOOL GUARD: a direct {form} launch is blocked - suites and single tests run ONLY through `<plugin>/scripts/run_suite.py --task <id> --label <label> -- <your command>` (via the run-py.cmd launcher): the raw log goes to evidence/, you get a JSON summary; the details of one failed test - `run_suite.py --task <id> --label <label> --detail <test>`. Diagnostics without a run ({diagnostics}) pass as they are. If this command runs no tests (a build, an install), add the runner\'s no-run flag listed above; if it has none, name the command and the matched form as a finding in your digest.{door}')

# The same block, for a caller inside an open dispatch. The two guards used to send that
# caller in opposite directions: this message named `--task/--label`, and stage_guard refuses
# exactly that while a dispatch is open ("standalone user interfaces"), so a literal role
# obeyed the first and was refused by the second until the escalation stopped the story
# (0.7.7 review). One interface per situation, named in the message that blocks.
RUNS_MSG_REQUEST = ('PRE-TOOL GUARD: a direct {form} launch is blocked, and a factory dispatch is open - inside a dispatch tests run ONLY through a typed request. The ordinary run is `<plugin>/scripts/run_suite.py --mine <CASE>`: it builds the request of your open dispatch and runs it. A run that is not the ordinary one: `run_suite.py --request <request.json>` (or `--schedule <schedule.json>` at or above the configured parallel threshold, default 8 instances). Do not know the shape? `run_suite.py --template request` prints a complete skeleton with one comment per field and runs nothing. Legacy --task/--label is a standalone user interface and the stage guard refuses it here. The details of one failed test - `run_suite.py --task <id> --label <label> --detail <test>` (reads the captured log, runs nothing); a missing reporter row - `--reparse-block`, never a rerun. Diagnostics without a run ({diagnostics}) pass as they are. If this command runs no tests (a build, an install), add the runner\'s no-run flag listed above; if it has none, name the command and the matched form as a finding in your digest.{door}')

# The door RUNS_MSG adds when only the PowerShell reading finds the launch (CX1-20 M-3, FR-1/FR-2): the guard reads every
# command in BOTH shell dialects, so a bash command with `\"` inside double quotes, `\$(`, or `<#` at a word start is a
# launch to PowerShell and one quoted argument to bash. The role cannot tell which reading blocked it without this line.
READ_AS_POWERSHELL_DOOR = (" The guard also reads every command as PowerShell, and read as PowerShell this runs {form}: if you "
                           "meant it as bash, write the command without `\\\"` inside double quotes (use single quotes, or a "
                           "word with no quote in it), without `\\$(`, and without `<#` at the start of a word.")


def _dispatch_is_open(event: dict) -> bool:
    """Is this caller inside factory work that owes the typed interface? A role signature
    from the host, or any running dispatch in the project. Fail-open: an error here must
    never turn one guard message into no guard message."""
    try:
        return bool(subagent_type(event)) or _project_has_open_dispatch(event)
    except Exception:
        return False


MAX_COMMAND_CHARS = 64 * 1024   # the most of a shell command the guard reads: one walk of it costs milliseconds, not minutes
SIZE_MSG = ("PRE-TOOL GUARD: this command is {size:,} characters long, and the guard reads at most 64 KB ({cap:,} "
            "characters) of a command: it cannot judge more, so it does not let the rest through unread. Split the work "
            "into several commands, or write the long text to a file with the Write tool and name the file in the "
            "command.")


def size_check(event: dict, cfg: dict) -> None:
    """A shell command over 64 KB is refused BEFORE any guard reads it (CX1-20 F-8): every reader walks the whole text
    (R1-R5 and the host's read rule), so on the hook path one hostile command - 200 000 `$(` openers, 400 KB - cost the
    guards ~190 s together, past any hook timeout, and a hook that times out is a guard that did not answer. A legitimate
    command is far shorter; the door is the one the message names (several commands, or a file written with the Write
    tool). Runs first, so it costs one `len`."""
    if (event or {}).get("tool_name") not in ("Bash", "PowerShell"):
        return
    size = len(argv_text(((event or {}).get("tool_input") or {}).get("command")))   # a Codex argv list: its joined line
    if size > MAX_COMMAND_CHARS:
        block(SIZE_MSG.format(size=size, cap=MAX_COMMAND_CHARS))


def runs_check(event: dict, cfg: dict) -> None:
    """Quiet runs (2026-09-11): tests run only through run_suite.py - a direct launch of any form in
    launch-causes.json `run_forms` (B-404) in a role's shell is blocked. Economy, not security: the
    message names the form and tells the role exactly what to call."""
    tool_name = (event or {}).get("tool_name")
    if tool_name not in ("Bash", "PowerShell"):
        return
    raw = argv_text(((event or {}).get("tool_input") or {}).get("command"))  # a Codex argv list: the splitter reads text
    # Only the heredoc / here-string BODIES come out: the matcher reads quoted arguments as text
    # itself (a runner's name inside quotes is a mention, E4). The second pass of command_text_parts
    # joins the pieces around a quoted argument with a newline, which the matcher reads as a new
    # command position: `echo "a" pytest -q` would become a launch (B-404 F1).
    command = _split_off_bodies(str(raw or ""))[0]
    form = direct_test_form(command, "powershell" if tool_name == "PowerShell" else "bash")
    if form is not None:
        fields = {"form": " ".join(form["argv"]), "diagnostics": run_forms_diagnostics_text(form), "door": ""}
        if tool_name == "Bash" and "bash" not in launch_readings(command):   # only the PowerShell reading sees the launch
            fields["door"] = READ_AS_POWERSHELL_DOOR.format(form=fields["form"])
        block(RUNS_MSG.format(**fields) if not _dispatch_is_open(event)
              else RUNS_MSG_REQUEST.format(**fields))


GIT_CONFIG_MSG = (
    'PRE-TOOL GUARD: changing git configuration is blocked. A role investigating a repository '
    'ran `git config --global safe.directory` on a live story despite a written instruction not '
    'to touch git config (TP2-2520 feedback): the machine belongs to the person, not to '
    'the run, and `--global` outlives the story. Reading is allowed (`git config --get`, '
    '`--list`); if a repository genuinely cannot be read without a configuration change, report '
    'that as a blocker and let the person decide. This is a hook, not a sentence in a prompt, '
    'because the sentence was already there.')

# `git -C <path> config`, `git --no-pager config`, plain `git config`. Reads are let through:
# the harm this blocks is MUTATING the machine's configuration, not looking at it.
_GIT_CONFIG_RE = re.compile(
    r"\bgit\b(?:\s+(?:-C\s+\S+|--no-pager|--git-dir[= ]\S+|--work-tree[= ]\S+))*\s+config\b", re.I)
_GIT_CONFIG_READ_RE = re.compile(r"(?:^|\s)(--get|--get-all|--get-regexp|--get-urlmatch|--list|-l)(?:\s|$)", re.I)


def git_config_check(event: dict, cfg: dict) -> None:
    """Git configuration is the person's, not the run's."""
    if (event or {}).get("tool_name") not in ("Bash", "PowerShell"):
        return
    parts = command_text_parts(((event or {}).get("tool_input") or {}).get("command"))
    # "\n" too: the second pass of command_text_parts joins the segments of one command with a newline
    # and drops the `; && ||` between them, so `git config --get a; git config --global x y` is two lines
    for part in re.split(r"&&|\|\||;|\||\n", parts["exec"]):
        if _GIT_CONFIG_RE.search(part) and not _GIT_CONFIG_READ_RE.search(part):
            block(GIT_CONFIG_MSG + where_clause(parts))


LOGS_MSG = ('PRE-TOOL GUARD: reading a raw run log is blocked - this read is {size:,} bytes of log; up to '
            '{cap:,} bytes read freely, more does not: a full-file pytest log weighs 50-64 KB '
            '(~15K tokens) and, once read, is re-billed on EVERY later turn of the dispatch until it ends '
            '(measured on TP1-13958: 107K tokens of context per turn, 85-90K of it accumulated tool '
            'output). Two routes already hold what you are after, and both work under an open dispatch: '
            '(1) the `<label>-<ts>.json` summary next to the log - totals, exit code, failed names with '
            'their first reason line, and `error_head`: the first error lines of the log when nothing ran '
            '(pytest exit 2-5, or nothing collected); (2) for one failure '
            '`<plugin>/scripts/run_suite.py --request <request file> --detail <test>` (or `--task <id> '
            '--label <label> --detail <test>`) - message and traceback from the junitxml, no re-run, no '
            'raw log. The log stays on disk for the audit.')

# `.log` and `.junit.xml` only: the `.json` summary IS the intended channel, and evidence
# screenshots (`.png`) are a runner artifact a role may legitimately look at.
_LOG_SUFFIXES = (".log", ".junit.xml")

# The rule is about weight, and until 0.7.8 it was applied by file extension. On TP1-15045
# that refused 12 reads, most of them of logs that weighed nothing: a 1.2 KB log whose one
# line was `ERROR: not found: ...::test_x[buffer-R3-vs-selected-R1]` (pytest exit 4), red-probe
# junit files of 238 bytes. No role could see why nothing had run, two critic dispatches
# went on "a tooling blocker", and TC-008, TC-003 and TC-006 ended "cause not established".
# 87 of that story's 109 evidence logs are under 8 KB — about 2K tokens, less than the
# refusal and the detour around it cost. config: guards.raw_log_free_bytes (0 = no log
# reads freely, the behaviour before 0.7.8).
DEFAULT_RAW_LOG_FREE_BYTES = 8192
_CD_RE = re.compile(r"(?:^|[;&|(\n])\s*(?:cd|pushd|chdir|Set-Location|sl)\s+(?:/d\s+|-\w+\s+)?"
                    r"(\"[^\"\n]+\"|'[^'\n]+'|[^\s;&|)]+)", re.IGNORECASE)


def _is_evidence_log(path: str) -> bool:
    p = str(path or "").replace("\\", "/").lower()
    return "/evidence/" in p and p.endswith(_LOG_SUFFIXES)


def _raw_log_free_bytes(cfg: dict) -> int:
    block_cfg = (cfg or {}).get("guards")
    raw = block_cfg.get("raw_log_free_bytes") if isinstance(block_cfg, dict) else None
    try:
        cap = DEFAULT_RAW_LOG_FREE_BYTES if raw is None else int(raw)
    except Exception:
        cap = DEFAULT_RAW_LOG_FREE_BYTES
    return cap if cap >= 0 else DEFAULT_RAW_LOG_FREE_BYTES


def _native_path(raw: str) -> str:
    """Git Bash spells a drive `/c/...`; Python on the same machine does not know that path.

    A path may also arrive Windows-spelled (backslash separators) on a host that resolves
    paths with forward slashes: until 0.7.19 the separator was left alone off Windows, so on
    a macOS host a backslash spelling of a real evidence log resolved to nothing, its size
    read as 0 and the heavy-log guard let the raw log through (a colleague's install smoke,
    24.09.2026). The separator is normalized first, on every OS."""
    text = os.path.expanduser(str(raw or "").strip()).replace("\\", "/")
    if os.name == "nt":
        m = re.match(r"^/([a-zA-Z])/(.*)$", text)
        if m:
            return f"{m.group(1).upper()}:/{m.group(2)}"
    return text


def _evidence_logs(raw: str, event: dict, command: str = "") -> dict:
    """{file: bytes} of the evidence log(s) `raw` names; empty when no such file is found.

    A shell names a log relative to wherever the command stands — the tool call's cwd, the
    project, or a `cd` in the command itself (the refused shell reads of TP1-15045
    began `cd <project> && python - <<EOF`) — and may name several with a wildcard.
    A path found nowhere is not blocked: the tool reports a missing file better than a
    guard does, and a refusal about a file that is not there sends a role looking for it."""
    import glob as _glob
    target = _native_path(raw)
    if os.path.isabs(target):
        candidates = [target]
    else:
        cwd = _native_path((event or {}).get("cwd") or "") or os.getcwd()
        bases = [cwd]
        for found in _CD_RE.findall(command or ""):
            moved = _native_path(found.strip("\"'"))
            bases.append(moved if os.path.isabs(moved) else os.path.join(cwd, moved))
        try:
            bases.append(str(project_root(event)))
        except Exception:
            pass
        candidates = [os.path.join(base, target) for base in bases]
    seen: dict = {}
    for candidate in candidates:
        # literal first: a parametrized test's log may carry `[chromium]` in its own name
        names = ([candidate] if os.path.isfile(candidate)
                 else _glob.glob(candidate) if any(c in candidate for c in "*?[") else [])
        for name in names:
            try:
                path = Path(name)
                if path.is_file():
                    seen[str(path.resolve()).lower()] = path.stat().st_size
            except Exception:
                continue  # a path the guard cannot stat is not the guard's business
    return seen


def logs_check(event: dict, cfg: dict) -> None:
    """Raw run logs are written for the audit, not for an agent's context (2026-09-15, the
    TP1-13958 measurement). Blocks the Read tool on an evidence `.log`/`.junit.xml`, and
    the same file reached through a shell (`cat`, `head`, `tail`, `sed -n`, `type`, a python
    one-liner) — when the log weighs more than `guards.raw_log_free_bytes`; a small one reads
    freely either way. A shell command is weighed whole: every log it names, wildcards
    expanded. A command that mentions `run_suite.py` is exempt: that is the writer of those
    logs, and its own `--detail` reads the junitxml on purpose."""
    ti = (event or {}).get("tool_input") or {}
    tool_name = (event or {}).get("tool_name", "")
    cap = _raw_log_free_bytes(cfg)
    if tool_name == "Read":
        if _is_evidence_log(ti.get("file_path")):
            size = sum(_evidence_logs(ti.get("file_path"), event).values())
            if size > cap:
                block(LOGS_MSG.format(size=size, cap=cap))
            return  # a log that reads freely is not then refused for being a file
        if _in_factory_scope(event):
            big_read_check(ti, cfg, event)
        return
    if tool_name not in ("Bash", "PowerShell"):
        return
    command = command_text_parts(ti.get("command"))["exec"]
    if "run_suite" in command:
        return
    named = {token for token in re.findall(r"[^\s'\"|;&<>()]+", command) if _is_evidence_log(token)}
    if not named:
        return
    weighed: dict = {}
    for token in named:
        weighed.update(_evidence_logs(token, event, command))
    size = sum(weighed.values())
    if size > cap:
        block(LOGS_MSG.format(size=size, cap=cap))


PLUGIN_READ_MSG = (
    "PRE-TOOL GUARD: {tool} inside the plugin is refused for a role ({path}). The brief carries the "
    "commands: `work/briefs/<dispatch id>.md` (named in your prompt) lists the files to read and every "
    "command with its argument shape and what it answers; `python <plugin>/scripts/<script>.py --help` "
    "is allowed and answers what the card does not. The plugin's references/ (rules, templates, "
    "contracts) stay readable. On TP1-13797 one automator window spent 106 Grep/Read calls inside "
    "the plugin looking for what the brief now says in one page.")
# What a role may still read inside the plugin: the documents written FOR roles. Everything
# else there - scripts, phase files, agent charters, hooks - is the factory's own code, and a
# role reading it is a role re-deriving the brief at its own expense.
PLUGIN_READ_ALLOWED = ("references/",)


def _plugin_target(event: dict) -> str:
    """The path a Read/Grep/Glob call is about, or '' when it names none."""
    ti = (event or {}).get("tool_input") or {}
    for key in ("file_path", "path"):
        value = str(ti.get(key) or "").strip()
        if value:
            return value
    pattern = str(ti.get("pattern") or "").strip()
    if (event or {}).get("tool_name") == "Glob" and pattern and (os.path.isabs(_native_path(pattern))
                                                                  or re.match(r"^/[a-zA-Z]/", pattern)):
        return pattern  # an absolute glob names its own directory
    return str((event or {}).get("cwd") or "")  # Grep/Glob with no path search the cwd


def _called_by_role(event: dict) -> bool:
    """The same two signals human_word_check reads: the host's agent fields on a call fired
    inside a subagent, or a subagent transcript wherever a host still sends one."""
    return bool(subagent_type(event)) or "/subagents/" in str(
        (event or {}).get("transcript_path") or "").replace("\\", "/")


def plugin_read_check(event: dict, cfg: dict) -> None:
    """A role reads the brief, not the plugin (PLAN-driver.md, E).

    Applies to Read, Grep and Glob whose target is inside the installed plugin, for calls the
    host marks as a role's. The orchestrator, the driver and the hooks themselves are never a
    role and are untouched; `--help` runs through Bash and is not this check's business.
    references/ is exempt: contracts and templates are written for roles to read."""
    if (event or {}).get("tool_name") not in ("Read", "Grep", "Glob"):
        return
    if not _called_by_role(event):
        return
    raw = _plugin_target(event)
    if not raw:
        return
    import runtime_paths as RP
    try:
        target = Path(_native_path(raw.split("*", 1)[0]) if "*" in raw else _native_path(raw)).resolve()
    except Exception:  # noqa: BLE001 - a target that cannot be resolved is not known to be the plugin's
        return
    # The package's one containment predicate (by components of the real places, never a string prefix: `<plugin>-old/` is
    # not inside `<plugin>`). It also holds the DIRECTORY itself (`<plugin>/references` without a trailing slash): a role that
    # greps that directory was refused the one place the guard documents as readable. Measured on TP1-13797: six of the
    # scout's and the strategist's guard refusals were exactly this - a role reaching for the contract it is judged by and
    # being sent back to a brief that does not carry it.
    if not RP.contained(target, PLUGIN_ROOT):
        return
    if any(RP.contained(target, PLUGIN_ROOT / allowed.rstrip("/")) for allowed in PLUGIN_READ_ALLOWED):
        return
    block(PLUGIN_READ_MSG.format(tool=event.get("tool_name"), path=raw))


def _in_factory_scope(event: dict) -> bool:
    """the read-size limit and the turn counter act only where factory work is
    actually happening — never in a session that only ever `cd`ed into the project once.

    An analysis session (cwd `D:/ws5`, not a story) followed one `cd` into a project
    and inherited both mechanisms as if it were a role: a 30 KB `Read` limit "of this
    dispatch" it never opened, and a turn counter that left a stray `state/turns/*.json`
    behind — the same session's cost capture separately left a 1.8 MB per-request file for
    a session that did no factory work (both share one cause: no activity was ever
    recorded for it). Three signals decide, any one is enough: the session's recorded activity
    record for this session; the host's own agent fields (`agent_id`/`agent_type`), sent by
    Claude Code on a PreToolUse fired inside a subagent call (verified against the Claude
    Code hooks reference, 2026-09-21 — not assumed); or an open dispatch anywhere in the
    project, which covers a role's very first tool call before activity capture has written
    anything for it yet."""
    event = event or {}
    try:
        from hooklib import session_has_factory_activity
    except ImportError:
        return True  # hooklib without the function: no scope narrowing, today's behavior
    session_id = str(event.get("session_id") or "")
    try:
        if session_id and session_has_factory_activity(session_id, event):
            return True
    except Exception:
        pass  # an activity check that fails never WIDENS what the guard already does today
    if subagent_type(event):
        return True
    return _project_has_open_dispatch(event)


def _project_has_open_dispatch(event: dict) -> bool:
    """Any story of this project with a `running` dispatch right now — cheap: a glob and a
    handful of small JSON reads, only reached once the two cheaper signals above came back
    empty."""
    try:
        import json
        from hooklib import artifact_root
        root = artifact_root(event)
        for controller_path in root.glob("*/state/controller.json"):
            try:
                data = json.loads(controller_path.read_text(encoding="utf-8"))
            except Exception:
                continue
            dispatches = data.get("dispatches")
            if isinstance(dispatches, dict) and any(
                    isinstance(d, dict) and d.get("status") == "running"
                    for d in dispatches.values()):
                return True
    except Exception:
        return False
    return False


DEFAULT_BIG_READ_BYTES = 30000
DEFAULT_IMAGE_READ_BYTES = 5242880   # = the ticket adapter's image download limit (jira-fields.json attachment_policy): downloaded means readable
DEFAULT_PDF_PAGES = 20      # the tool's own limit of pages in one `Read` of a PDF
# Files a role legitimately reads whole: a template it is about to fill, a contract it must
# follow to the letter, and its own small state. Everything else — application source, a
# diff, a manifest that grew with the story — has a first line and a last line, and a role
# needs the part between two of them.
#
# Each entry is an EXACT place (SC1-3 part 3, t-1253 B-2), not a mark in the path. The marks were substrings, and a substring
# exempts whatever else contains it: `config.json` let through the plugin's own template (30,135 B), a project's tsconfig.json
# and the project config itself (50,098 B read whole by the conductor and three roles); `templates/` let through a product's
# `src/.../templates/agents/core_prompts.py` (32,413 B); `readiness.json` the story's requirements-readiness.json. Now:
# (where, path below it) - `plugin` is the running plugin, `project` the project root, `story` one story's folder under the
# artifact root (`<ticket>/<path>`); a trailing `/` is the whole directory. The plugin's `references/` holds the templates.
# The project's own readiness.json lives in two worlds (`runtime_paths`), so `_big_read_exempt` asks the layout for it.
# The project config is NOT here: it is the one file that is refused when it is big, with its own door (`_config_door`).
# `skills/` of the plugin is here because the old `.claude/` mark exempted the whole INSTALLED plugin (it lives under
# `~/.claude/plugins/cache/`): the phase and onboarding files SKILL.md tells a reader to read whole (`phases/s0.md` 31,146 B,
# `p2-interview.md`, `p4-generate.md`) are contracts followed to the letter, and stay readable whole (t-1333 B-1). A `skills/`
# folder of a PRODUCT is not the plugin's and is refused when big.
BIG_READ_EXEMPT = (
    ("plugin", "references/"),
    ("plugin", "skills/"),
    ("project", ".claude/"),
    ("project", "CLAUDE.md"),
    ("project", "AGENTS.md"),
    ("story", "pipeline.json"),
    ("story", "work/requirements-readiness.json"),
)


def big_read_cap(cfg) -> int:
    """The size above which a role may not read a file whole (`config.read.max_bytes`, default 30000); 0 or less = the guard is
    off. The ONE reader of the limit: `big_read_check` blocks by it, and `source_inventory` (C2-9) calls a material of that size a
    gap by default - a role physically cannot open it. A PICTURE is judged by `big_read_image_cap` instead (the text limit is
    unchanged)."""
    raw_cap = ((cfg or {}).get("read") or {}).get("max_bytes")
    try:
        return DEFAULT_BIG_READ_BYTES if raw_cap is None else int(raw_cap)
    except Exception:
        return DEFAULT_BIG_READ_BYTES


def big_read_image_cap(cfg) -> int:
    """The most bytes of a PICTURE a role may read whole (`config.read.max_image_bytes`, default 5,242,880: the ticket adapter's
    image download limit). The ONE reader of the key (AR-13): `big_read_check` lets a picture through by it, and
    `source_inventory.image_size_limit_of` prints it. Anything but a positive whole number is the default (AR-3), never "off"."""
    section = (cfg or {}).get("read") if isinstance(cfg, dict) else None
    raw = section.get("max_image_bytes") if isinstance(section, dict) else None
    if isinstance(raw, bool) or not isinstance(raw, int) or raw < 1:
        return DEFAULT_IMAGE_READ_BYTES
    return raw


def _is_picture(path_raw) -> bool:
    """Does the file START with a listed picture signature (`branch_accounting.picture_signatures`, a data row)? By CONTENT only:
    live blobs have no suffix, and a text file named `x.png` is not a picture. Reads at most 16 bytes. The error direction is
    "not a picture" (the old refusal with its door): an open error, an unreadable table, an import error all give False."""
    try:
        import branch_accounting
        rows = branch_accounting.picture_signatures()
        with open(path_raw, "rb") as handle:
            head = handle.read(16)
        return any(all(head[off:off + len(sig)] == sig for off, sig in parts) for _name, parts in rows)
    except Exception:  # noqa: BLE001 - see the docstring
        return False


def big_read_pages(cfg) -> int:
    """The most pages one `Read` of a `.pdf` may take (`config.read.max_pdf_pages`, default 20: the tool's own limit). The ONE reader of
    it (AR-13): `big_read_check` lets a `pages` range through by it, and `branch_accounting` prints `pages 1-<N>` by it. Anything but
    a positive whole number is the default (AR-3)."""
    section = (cfg or {}).get("read") if isinstance(cfg, dict) else None
    raw = section.get("max_pdf_pages") if isinstance(section, dict) else None
    if isinstance(raw, bool) or not isinstance(raw, int) or raw < 1:
        return DEFAULT_PDF_PAGES
    return raw


def _pdf_range_ok(pages, cfg) -> bool:
    """Is `pages` a range of a `.pdf` the tool honours and the limit allows (`"3"`, `"1-20"`)? The error direction is "no": an empty,
    non-text, reversed, zero-based or too wide value is a refusal with a door (`pages 1-<N>`), never a pass."""
    if not isinstance(pages, str):
        return False
    found = re.fullmatch(r"([0-9]+)(?:-([0-9]+))?", pages)
    if not found:
        return False
    first = int(found.group(1))
    last = int(found.group(2)) if found.group(2) is not None else first
    return first >= 1 and last >= first and last - first + 1 <= big_read_pages(cfg)


def _big_read_exempt(path_raw: str, event) -> bool:
    """Is this path one of the EXACT places `BIG_READ_EXEMPT` names (a file, or anything below a directory entry)? A file is
    compared resolved and case-folded (`hooklib.norm`), so `./qa-factory/../qa-factory/x` and a different case are the same place;
    a directory (and the artifact root) is asked of `runtime_paths.contained`, the package's one containment predicate (by
    components of the real places, never a string prefix). The error direction is "not exempt": a layout that cannot be resolved
    (an `artifact_root` that raises included) leaves the size rule in force, and its refusal names a door (a range read) - the
    guard never crashes on it."""
    try:
        from hooklib import artifact_root, norm
        import runtime_paths as RP
        target = norm(path_raw)
        located = Path(path_raw).resolve()
        project = project_root(event)
        for where, rel in BIG_READ_EXEMPT:
            if where == "story":
                continue
            place = (PLUGIN_ROOT if where == "plugin" else project) / rel.rstrip("/")
            if target == norm(str(place)) or (rel.endswith("/") and RP.contained(located, place)):
                return True
        if target in (norm(str(RP.readiness_write(project))), norm(str(RP.home_dir(project) / RP.READINESS))):
            return True                                   # the project's readiness report: state/ now, beside the config before
        root = artifact_root(event)
        if RP.contained(located, root):
            below = located.relative_to(root).parts       # (<ticket>, <path in the story>...)
            story_path = "/".join(below[1:]).lower()
            return len(below) >= 2 and any(where == "story" and story_path == rel for where, rel in BIG_READ_EXEMPT)
        return False
    except Exception:  # noqa: BLE001 - see the docstring
        return False


def _has_bash(event) -> bool:
    """Does the caller have a shell (`role_ways`, the one reader of the role's `tools:`)? A doubt names no script: a door the role
    cannot open is a trap (FR-2), and the range read is open to everyone."""
    try:
        return "Bash" in role_ways(event or {})
    except Exception:  # noqa: BLE001
        return False


def _config_door(path_raw: str, event) -> str:
    """The door of a whole read of THIS project's config (`hooklib.config_path`, compared as a resolved path), else "".
    The config is 50 KB on a real project and its readers (the conductor, onboarding, the runner, the bug reporter) read it
    whole; they get one refusal and then the key. TEMPORAL: `config_view.py` is SC1-8's - while it is not in the plugin the door
    is `Grep -n` and a range read; once it is, a caller with a shell is also named it. Each world names only what exists."""
    try:
        from hooklib import config_path, norm
        if norm(path_raw) != norm(str(config_path(event))):
            return ""
    except Exception:  # noqa: BLE001 - no config path, no config door
        return ""
    text = ("This is the project config: it is read by key, not whole. `Grep -n \"<the key>\" "
            f"{path_raw.replace(chr(92), '/')}` gives the line, and `Read` with `offset`/`limit` takes that part.")
    if _has_bash(event) and (PLUGIN_ROOT / "scripts" / "config_view.py").is_file():
        text += (" `python \"${CLAUDE_PLUGIN_ROOT}/scripts/config_view.py\" --keys` lists its keys and "
                 "`config_view.py --get <key>` prints one.")
    return text


def _registry_artifacts() -> dict:
    """`artifacts` of `references/artifact-writers.json`, read through `hooklib.load_ref_json` (the package's one reader of a
    reference table - the guard kept two inline `json.loads` copies of it). {} for anything but a dict: a registry that is
    missing, broken, not an object or without `artifacts` (an older copy of the plugin) - every caller reads {} as "no registry"
    and keeps its own fallback; the function never raises."""
    try:
        from hooklib import load_ref_json
        artifacts = load_ref_json("artifact-writers.json").get("artifacts")
    except Exception:  # noqa: BLE001 - see the docstring
        return {}
    return artifacts if isinstance(artifacts, dict) else {}


def _registry_hits(raw: str, field: str):
    """(key, entry) of every registry entry that carries a truthy `field` and whose key is a path suffix of `raw` (a path with
    forward slashes): the ONE suffix match of the registry's artifacts."""
    for key, entry in _registry_artifacts().items():
        if isinstance(entry, dict) and entry.get(field) and raw.endswith("/" + str(key).lstrip("/")):
            yield key, entry


def _section_door(path_raw: str, event) -> str:
    """The map of a big artifact's sections for the refusal of its whole read, else "" (the refusal then keeps its old text).

    WHICH artifacts are read by section is data: `read_by_section` in `references/artifact-writers.json` (`grounding`,
    `plan_rows`), read through `hooklib.load_ref_json`; an entry without it, or a registry without the key (an older copy of the
    plugin), gives no map. The map is `artifact_sections.section_map_text` - checked against the file when it is built, "" for
    any doubt - and it is built HERE only, on the way to a block, so a read that passes never pays the parse. The error
    direction is one: NO map (a role reads by windows as before), never a wrong one; the function never raises."""
    try:
        raw = path_raw.replace("\\", "/")
        for _key, entry in _registry_hits(raw, "read_by_section"):
            kind = entry["read_by_section"]
            if not isinstance(kind, str):
                continue
            import artifact_sections
            sections = artifact_sections.section_map_text(path_raw, kind)
            if not sections:
                return ""
            door = ("This file is read by section. Its map (id: lines):\n" + sections + "\nRead one section with `Read` "
                    "`offset=<first line>` `limit=<last line - first line + 1>`; after your own Edit the lines below it move - "
                    "a whole Read of the file gives the map again.")
            if _has_bash(event):
                story = _STORY_RE.search(raw)
                task = story.group(1) if story else "<TICKET>"
                script = "plan_row.py" if kind == "plan_rows" else "grounding_section.py"
                shape = "--show --row <TS-n> [--row ...]" if kind == "plan_rows" else "--show <id> [--show ...] | --requirement <R-n>"
                door += f"\nWith a shell: python \"${{CLAUDE_PLUGIN_ROOT}}/scripts/{script}\" --task {task} {shape}"
            return door
    except Exception:  # noqa: BLE001 - see the docstring
        return ""
    return ""


def big_read_check(ti: dict, cfg: dict, event: dict | None = None) -> None:
    """A large file is read by the range, not whole (common-rules.md, turn economy).

    The measurement behind it: a 102,214-character diff read at turn 10 of 140 was re-billed
    on all 130 remaining turns of that dispatch (TP1-14336), and across one story 3.12M
    characters of file content were pulled into contexts — `automation-manifest.json` alone
    32 times, 806K characters. `offset`/`limit` is the whole fix, and `Grep -n` finds the
    line to start at. A limit of 0 (config.read.max_bytes) turns this off.

    ORDER (SC1-3 part 3, t-1253 E-7/E-11): range read, limit off, stat, size - as before; THEN the exact exemptions; THEN the
    refusal, whose door is built only now: the project config's, or the map of a big artifact (`_section_door`). A small file,
    a range read and an exempt place pass without a resolve or a parse, and no door can turn a refusal into a pass."""
    path_raw = str(ti.get("file_path") or "")
    if not path_raw:
        return
    is_pdf = path_raw.lower().endswith(".pdf")
    if is_pdf:
        # A `.pdf` is bounded only by a `pages` range within the limit: the tool ignores `offset`/`limit` there (it returned all 14
        # pages of 14 for `limit 1`), and `pages` is ignored on any other file. The error direction is a refusal with a door.
        if _pdf_range_ok(ti.get("pages"), cfg):
            return
    elif ti.get("offset") or ti.get("limit"):
        return
    cap = big_read_cap(cfg)
    if cap <= 0:
        return
    normalized = path_raw.replace("\\", "/")
    try:
        size = Path(path_raw).stat().st_size
    except Exception:
        return  # a path the guard cannot stat is not the guard's business
    if size <= cap:
        return
    if _big_read_exempt(path_raw, event):
        return
    applied_cap = cap
    if not is_pdf and _is_picture(path_raw):
        # POSITION INVARIANT: reached only after the text rule has refused (size > cap, cap > 0, no range, not exempt); it can only
        # turn that refusal into a pass, for a file that starts with a listed picture signature. The sniff is paid on the way to a block.
        applied_cap = max(cap, big_read_image_cap(cfg))
        if size <= applied_cap:
            return
        door = ("This is a picture: it cannot be read in parts. If it is a ticket attachment, record it as unread with cause "
                "`too_large` so the person sees it with its size; do not try `offset`/`limit`.")
        if _has_bash(event):
            door += ("\nWith a shell: python \"${CLAUDE_PLUGIN_ROOT}/scripts/ticket_adapter.py\" inspect --output <work/source-inventory.json> "
                     "--source-id <source id> --attachment-id <attachment id> --evidence-ref <path of the evidence you wrote> "
                     "--inspection-status unavailable --reason \"too_large: <what you saw: the size and the limit>\"")
        else:
            door += " Name it in your findings as a picture over the read limit."
    elif is_pdf:
        door = (f"A PDF is read by pages: `Read` with `pages` `1-{big_read_pages(cfg)}` (at most {big_read_pages(cfg)} pages a call), "
                "then the next range; `offset`/`limit` do not bound a PDF.")
    else:
        door = _config_door(path_raw, event) or _section_door(path_raw, event) or (
            "Read the part you need: `Read` with `offset`/`limit`, after `Grep -n <what you are looking for> "
            f"{normalized}` gives you the line. For a diff, `scripts/diff_pass.py --diff <path>` prints the "
            "changed files and their changed lines in one call. If you genuinely need the whole file, read it in "
            "ranges and say in your findings why.")
    block(f"PRE-TOOL GUARD: reading {normalized} whole is blocked — it is {size:,} bytes "
          f"(the limit is {applied_cap:,}), and everything you read is billed again on every "
          f"remaining turn of this dispatch. " + door)


def _is_case_file(raw: str, cfg: dict | None = None) -> bool:
    """Is this path a case document, in the id form THIS project records (`config.case_id_form`,
    then `TC-NNN`)? Read through `case_forms`, never a pattern of its own: the guard used to know
    only `TC-<n>*.md`, so a project whose cases are `TP1-13877_TC_001.md` could write them
    anywhere and no owner was named for them (B-013, FR-17/FR-39). `cfg` is the config the caller
    holds; empty or absent means the project's own. A config that cannot be read is the default
    form - recognition never falls to "nothing is a case"."""
    base = str(raw or "").replace("\\", "/").rsplit("/", 1)[-1]
    return case_forms.is_case_file_name(base, cfg or load_config())


def case_store_check(event: dict, cfg: dict) -> None:
    """A case is written where this project keeps its cases, and nowhere else.

    Onboarding finds the project's case store and records it in `cases_root`; before that
    key existed the finding was dropped and every case went into the factory's own per-story
    tree beside the project's real library. With a store declared there is exactly one right
    place, so a second one is a defect and not a preference. An empty key keeps the old
    behaviour (cases per story) and this check stays silent."""
    if (event or {}).get("tool_name") not in ("Write", "Edit", "NotebookEdit"):
        return
    raw = str(((event or {}).get("tool_input") or {}).get("file_path") or "").replace("\\", "/")
    # Recognition stays the FIRST filter, before cases_root is read: a path that is not a case is
    # never this check's business, and a project with no store stays silent for every path.
    if not raw or not _is_case_file(raw, cfg):
        return
    store = str((cfg or {}).get("cases_root") or "").strip()
    if not store:
        return
    try:
        root = project_root(event)
        target = Path(raw)
        target = (target if target.is_absolute() else root / target).resolve()
        allowed = (Path(root) / store).resolve()
    except Exception:
        return  # a path the guard cannot resolve is not the guard's business
    if target == allowed or allowed in target.parents:
        return
    ticket = _STORY_RE.search(raw)
    sample = case_forms.example(ticket.group(1) if ticket else "", cfg or load_config())
    block(f"PRE-TOOL GUARD: this project keeps its test cases in `{store}` "
          f"(config.json, cases_root), and this write goes to {raw}. Write it as "
          f"`{store}/<area>/{sample}.md` instead — the coverage map, the traceability check "
          "and the next story's dedupe all read that one store, and a case outside it is "
          "invisible to every one of them. If the project's cases have moved, re-run "
          "qa-onboarding rather than writing a second library.")


# Artifact -> owner role, when the registry cannot be read. Only files a ROLE writes: the state
# files scripts own (pipeline.json, ledger.*) are written by Bash and never reach this check.
# `owned_artifacts()` below is what the guard uses; this is the floor under a broken checkout,
# and the two are held together by a test.
OWNED_ARTIFACTS = {
    "context-manifest.json": "qa-scout",
    "requirements-register.md": "qa-requirements-tester",
    "understanding.md": "qa-requirements-tester",
    "test-plan.md": "qa-test-strategist",
    "automation-manifest.json": "qa-automator",
    "run-report.json": "qa-runner",
    "triage.json": "qa-failure-analyst",
    "test-report.md": "qa-doc-scribe",
}
# Artifacts a role writes and a script does, where the ROLE is the one whose dispatch must be
# open for a Write to pass. The registry names the script, because the script is what writes the
# file; the role is who is dispatched to produce it, which is what this guard asks about.
REGISTRY_ROLE_BY_SCRIPT = {"manifest_put.py": "qa-automator", "finalize_task.py": "qa-runner"}
_STORY_RE = re.compile(r"/artifacts/([^/]+)/")


def owned_artifacts() -> dict:
    """{artifact key: owning role} from `references/artifact-writers.json`.

    One owner per fact (audit A21): the registry exists to say "one artifact, one writer", and
    this guard used to keep a second, shorter copy of the same list in code — eight of the
    sixteen artifacts a role owns, so the other eight (the readiness, the machine plan, the diff,
    the bug drafts, the retro and the two project ledgers) could be repaired from outside the
    role that owns them, which is the whole defect `owner_check` exists for (FR-17, FR-39).

    Keys are as the registry spells them: a file name, a directory ending in `/`, or
    `project:<path>` for something outside the story's own root.
    """
    registry = _registry_artifacts()
    if not registry:                                     # a broken checkout, or no registry: the floor under it (a test holds the two together)
        return dict(OWNED_ARTIFACTS)
    out = {}
    for key, entry in registry.items():
        writer = str((entry or {}).get("writer") or "")
        found = re.findall(r"qa-[a-z-]+", writer)
        role = found[0] if found else REGISTRY_ROLE_BY_SCRIPT.get(writer.split()[0] if writer else "")
        if not role:
            continue
        name = str(key)
        if name.endswith("/") or name.startswith("project:"):
            out[name] = role
        elif "/" in name:
            # A PATH key (`work/test-cases/critic-findings.md`) is kept whole: reduced to its
            # basename, two files of one name in two directories would collapse into one and the
            # last would win. Its basename alias stays only where no other key shares it, so
            # every path that resolved by basename before still resolves to the same role.
            out[name] = role
            base = name.rsplit("/", 1)[-1]
            shared = sum(1 for other in registry if str(other).rsplit("/", 1)[-1] == base
                         and not str(other).endswith("/") and not str(other).startswith("project:"))
            if shared == 1:
                out[base] = role
        else:
            out[name] = role
    return out or dict(OWNED_ARTIFACTS)


def _is_path_key(key: str) -> bool:
    return "/" in key and not key.endswith("/") and not key.startswith("project:")


def _owner_of_path(raw: str, cfg: dict | None = None) -> tuple:
    """(owning role, is it outside the story root) for this path, or (None, False).

    The case branch stays LAST: a file the registry names is that role's, whatever its name looks
    like, and only a path nothing else claims is read as a case document (`cfg` = the project's
    config when the caller holds it)."""
    path = str(raw or "").replace("\\", "/")
    name = path.rsplit("/", 1)[-1]
    owned = owned_artifacts()
    # PATH keys first: `work/test-cases/critic-findings.md` is the critic's although the directory
    # key `work/test-cases/` is the designer's. Same basename AND the key's directory part in the
    # path (an area directory may sit between them). Nothing else moves: the rest is one pass in
    # the registry's own order, as before, so every other path resolves to the same role.
    for key, role in owned.items():
        if _is_path_key(key):
            directory, base = key.rsplit("/", 1)
            # A base with `*` (`critic-findings-*.md`, one file per dispatch) is matched by fnmatch; a base without it keeps the
            # exact match, so the old `critic-findings.md` row still claims exactly that name (first match wins, as before).
            same = fnmatch.fnmatchcase(name, base) if "*" in base else name == base
            if same and "/" + directory + "/" in "/" + path:
                return role, False
    for key, role in owned.items():
        if _is_path_key(key):
            continue
        if key.startswith("project:"):
            tail = key[len("project:"):]
            if path.endswith("/" + tail) or ("/" + tail) in path:
                return role, True
        elif key.endswith("/"):
            if "/" + key.lstrip("/") in path + "/":
                return role, False
        elif name == key:
            return role, False
    if _is_case_file(path, cfg):
        return "qa-case-designer", False
    return None, False


# The names a handover folder holds (SC1-2 B2): the form `<stem>.yaml`, the role's waiting words `<stem>.values.yaml`
# (the EXACT suffix - `.values.yml` and `.values.yaml.bak` are not it), the traces code leaves (`.values.applied`,
# `.values.stale`) and the conductor's `.help`.
_HANDOFF_FILE = re.compile(r"^(?P<stem>.+?)(?P<kind>\.values\.applied|\.values\.stale|\.values|\.help)?\.(?P<ext>yaml|yml)$")


def handoff_write_check(event: dict, cfg: dict) -> None:
    """The handover form is filled through its values file, never rewritten whole, and never edited under a waiting one.

    TP1-13797, 26.09: the roles of one run wrote a handover form with `Write` **18 times**
    against 14 `handoff_check --set` calls. A form runs to dozens of fields (the code critic's is
    90), so every full rewrite is thousands of output tokens, it lands in the role's own context
    and is re-read on every later turn — and it silently reverts whatever `--fix` had just derived
    and whatever another hand had set. SC1-2 (12586: 138 form-filling calls): the role says every
    field it owns in ONE `<dispatch>.values.yaml` (or `--values -`), and `handoff_check --fix` writes
    them into the form. This function owns the doors around that file:
      - `Write` of `<stem>.values.yaml` is the role's door: `handoff_values_check` proves it before it lands;
      - `Write` of `.values.applied.yaml` / `.values.stale.yaml` is code's (a trace nothing reads): refused;
      - `Write` over an existing form is refused, the values file named first;
      - `Edit` of a form while its values file waits is refused (M-5): the file is applied over the form at the
        next check, so the edit would be lost; the field goes into the values file.
    The first write of the form is `handoff_init.py`'s skeleton, and an `Edit` with no waiting file stays allowed."""
    tool = (event or {}).get("tool_name")
    if tool not in ("Write", "Edit"):
        return
    raw = str(((event or {}).get("tool_input") or {}).get("file_path") or "").replace("\\", "/")
    if "/work/handoffs/" not in raw or not raw.endswith((".yaml", ".yml")):
        return
    folder, name = raw.rsplit("/", 1)
    found = _HANDOFF_FILE.match(name)
    stem, kind, ext = (found.group("stem"), found.group("kind") or "", found.group("ext")) if found else (name, "", "")
    waiting = f"{stem}.values.yaml"                       # the same name `handoff_check.sibling_values` gives (a test pins it)
    values = f"{folder}/{waiting}"
    if tool == "Edit":
        if kind or not Path(values).is_file():
            return                                        # the file of values itself (E20) and a form nothing waits on
        # The line a role with Bash may use is a command only it can run (FR-2): a role without it sees the file door.
        block(f"PRE-TOOL GUARD: {waiting} is waiting to be applied to this form, and it is applied over it at the "
              f"next check - an Edit here would be lost. Put the field into {waiting} (rewrite it whole, with the "
              f"field added): {values}"
              + (f"\nor apply it first: python \"${{CLAUDE_PLUGIN_ROOT}}/scripts/handoff_check.py\" --file {raw} --fix,"
                 " then Edit" if "Bash" in role_ways(event) else ""))
        return
    if kind == ".values" and ext == "yaml":
        handoff_values_check(event)
        return                                            # the exemption lifts THIS rule only; the chain goes on (P5)
    if ext == "yaml" and kind in (".values.applied", ".values.stale"):
        block(f"PRE-TOOL GUARD: {name} is written by code - it is the trace of a values file that was applied (or "
              f"set aside because its form was written again), and nothing reads it. Write your fields to {values} "
              "instead: `path: value` lines in one Write; a row of a list by its index, \"<list>[0].<field>\": value; "
              "the next check applies them.")
    if not Path(raw).is_file():
        return  # the first write is `handoff_init.py`'s skeleton, not a rewrite
    ways = role_ways(event)
    block("PRE-TOOL GUARD: the handover form is filled through its values file, not rewritten. A Write "
          f"replaces {name} whole — it drops what `--fix` derived, drops what anyone else set, "
          "and costs a full file of output tokens that then sits in your context for the rest of "
          "the dispatch. What your role can use here:\n"
          f"  Write {values}\n"
          "      (every field you own as `path: value` lines, in one Write; a row of a list by its index, "
          "\"<list>[0].<field>\": value; the next check applies them)\n"
          + ((f"  or, in one call:\npython \"${{CLAUDE_PLUGIN_ROOT}}/scripts/handoff_check.py\" --file {raw} --fix --values - <<'EOF'\n"
              "<path>: <value>\nEOF\n"
              "      (the same lines; --fix also derives everything code can, then names what is left)\n")
             if "Bash" in ways else "")
          + (f"  Edit   (one field's own lines; refused while {waiting} waits for this form)" if "Edit" in ways else ""))


def handoff_values_check(event: dict) -> None:
    """A role's values file is proved before it lands: the form with those values merged in memory must be ready.

    The seam that keeps a role without Bash out of a dead end (SC1-2 B2): it cannot run `handoff_check`, so the one
    Write of `<dispatch>.values.yaml` is answered, in the same turn, with every problem at once - one block, built by
    the same `refusal_text` the command prints, carrying the role's good lines (M-4) and the lines to fix. A form
    that is ready, or one whose `blocked.problem` is filled (FR-57: a role that cannot fill a field says so and the
    stage reads it), lets the file land; `story_step finish` or the driver applies it with `--fix`.
    Where it is SOFTER than `--fix`: a blank field code fills itself is not asked for (M-9: the role cannot produce
    it), there is no form beside the file (nothing could apply it), and any exception passes (P1: the guard is a help,
    `--fix` checks again). Where it is STRICTER: the judge is never asked, so a word beside the list is refused even
    though `--fix` would let the judge map it. It writes nothing (FR-45)."""
    tool_input = (event or {}).get("tool_input") or {}
    content = tool_input.get("content")
    raw = str(tool_input.get("file_path") or "").replace("\\", "/")
    if not isinstance(content, str) or not raw.endswith(".values.yaml"):
        return
    form = Path(raw[:-len(".values.yaml")] + ".yaml")
    if not form.is_file():
        return                                            # E-noform: nothing could apply it; the transition checks the form
    try:
        import handoff_check
        report = handoff_check.values_report(form, content)    # the one parse, the one read of the form (SC2-13)
        if not report.problems:
            return
        if report.blocked_said:
            return                                        # the door: what the role cannot fill, it says in `blocked`
        refusal = handoff_check.refusal_text(form, report.contract, report.problems, report.role, kept=report.kept)
    except Exception:
        return                                            # cannot tell: pass; `--fix` checks the file again
    block("PRE-TOOL GUARD: these handover values leave the form not ready; nothing was written.\n" + refusal)


def dispatched_role(event: dict) -> str:
    """The role of the dispatch that is running, from `state/controller.json`.

    A PreToolUse event does not name the agent that caused it — `agent_type` arrives on
    SubagentStop and nowhere else — so a guard that needs to know WHO is writing reads the open
    dispatch instead. With no name in the environment the first running dispatch answers (one at a time before parallel
    windows); a session that carries its dispatch's name (`dispatch_identity.named`) gets that dispatch's role. None open, or no
    controller, means the caller decides what to assume."""
    raw = str(((event or {}).get("tool_input") or {}).get("file_path") or "").replace("\\", "/")
    story = _STORY_RE.search(raw)
    if not story:
        return ""
    import json
    from hooklib import artifacts_dir
    try:
        controller = json.loads((artifacts_dir(story.group(1), event) / "state" / "controller.json")
                                .read_text(encoding="utf-8"))
    except Exception:
        return ""
    dispatches = controller.get("dispatches") if isinstance(controller.get("dispatches"), dict) else {}
    import dispatch_identity
    if dispatch_identity.named():
        # A session that carries its dispatch's name is that dispatch (TR3-14, AR-13); two windows running do not make
        # it the first one. The name read, no running dispatch fits it: no role (the caller decides what to assume).
        mine = dispatch_identity.own(dispatches)
        return role_name(str(mine.get("role") or "")) if mine else ""
    for dispatch in dispatches.values():
        if isinstance(dispatch, dict) and dispatch.get("status") == "running":
            return role_name(str(dispatch.get("role") or ""))
    return ""


def role_ways(event: dict) -> set:
    """The point-edit tools the role doing this write actually has, from its own agent file.

    TP1-13797, 27.09: a rewrite guard told `qa-test-strategist` to run `plan_row.py` and, if
    that did not suit, to use `Edit`. That role carries `tools: Read, Grep, Glob, Write` — no Bash
    and no Edit — so the host answered its one attempt with `No such tool available: Edit`, and the
    role, left with no legal way to change its own artifact, tried the same Write four times. A
    refusal that names a way out the role does not have is not a refusal, it is a trap.

    The doubt is decided by the test `host_adapter.role_policy` itself applies (a role is a role when its agent
    file exists), and the line is read by `host_adapter.tools_line` (the frontmatter only, one parser):
      - no role, or no agent file (the orchestrator, a caller that is no factory role): both doors, because a
        guard must not go quiet on a doubt and `role_policy` binds no tools on such a caller;
      - an agent file with no `tools:` line (or an empty one, or one that cannot be read): `role_policy` refuses
        such a role every shell command but one plain read, so on Codex the only door is Edit; on Claude Code
        both are named - an ESTIMATE, not measured here: a Claude agent that lists no `tools:` inherits the
        host's tools;
      - an agent file with a `tools:` line: exactly the tools it lists."""
    role = role_name(subagent_type(event)) or dispatched_role(event)
    if not role:
        return {"Edit", "Bash"}
    if not (PLUGIN_ROOT / "agents" / f"{role}.md").is_file():
        return {"Edit", "Bash"}
    from host_adapter import is_codex, role_tools
    tools = role_tools(role, PLUGIN_ROOT)
    if tools:
        return set(tools)
    return {"Edit"} if is_codex(event) else {"Edit", "Bash"}


def artifact_rewrite_check(event: dict, cfg: dict) -> None:
    """An artifact that already exists is changed where it changed, not written again.

    Which artifacts, and what to use instead, is not in this code: it is in
    `references/artifact-writers.json`, whose entry carries `rewrite` (what to use) and
    `rewrite_cost` (what the rewrites measured on this story cost). Artifacts differ too much for a
    list in code, and a new one must not need a guard change. The plan has its own check below,
    because its refusal names the rows it is holding."""
    if (event or {}).get("tool_name") != "Write":
        return
    raw = str(((event or {}).get("tool_input") or {}).get("file_path") or "").replace("\\", "/")
    if not raw or raw.endswith(("/work/test-plan.json", "/work/test-plan.md")):
        return
    if not Path(raw).is_file() or not Path(raw).stat().st_size:
        return  # the first write of an artifact is one Write; that is how it comes into being
    for key, entry in _registry_hits(raw, "rewrite"):    # no registry, no hits: no opinion
        name = raw.rsplit("/", 1)[-1]
        cost = str(entry.get("rewrite_cost") or "").strip()
        # The door of a ban (FR-57): a run that was cut off may leave a file nothing can be continued
        # from, and the guard must not be a dead end then. Named only to a role that can run it.
        story = _STORY_RE.search(raw)
        door = ("\nIf a run of yours was cut off and left this file with nothing in it to continue from, set it "
                "aside and write it again:\n  python \"${CLAUDE_PLUGIN_ROOT}/scripts/artifact_supersede.py\" "
                f"--task {story.group(1) if story else '<TICKET>'} --path {str(key).lstrip('/')} "
                "--role <your role> --reason \"<one line>\"\n(it moves the file to `.superseded`; your next "
                "Write of it is its first.)") if "Bash" in role_ways(event) else ""
        block(f"PRE-TOOL GUARD: {name} already exists, and a Write replaces it whole"
              + (" — " + cost if cost else "")
              + f".\nChange what changed instead: {entry['rewrite']}.\n"
              "Everything you have already written stays; a rewrite would spend the whole file in "
              "output tokens again and carry it in your context for the rest of the dispatch." + door)
        return


def plan_write_check(event: dict, cfg: dict) -> None:
    """The test plan is written whole once; after that a row at a time.

    TP1-13797, measured over three runs: `qa-test-strategist` wrote `test-plan.json` whole
    **59 times** — 525,812 tokens of call arguments, the single largest line item in the factory.
    Each rewrite is a full file of output tokens, it then sits in the role's own context and is
    re-read on every later turn, and it silently reverts whatever another hand had set. One run's
    two booleans cost $16.53 this way. `plan_row.py --set` changes a field in place, `--add-row`
    appends one row the role wrote, and `Edit` changes one line of prose; none of the three can
    lose a neighbouring row."""
    if (event or {}).get("tool_name") != "Write":
        return
    raw = str(((event or {}).get("tool_input") or {}).get("file_path") or "").replace("\\", "/")
    if not raw.endswith(("/work/test-plan.json", "/work/test-plan.md")):
        return
    path = Path(raw)
    if not path.is_file():
        return  # the plan does not exist yet: writing it the first time is one Write
    if raw.endswith(".json"):
        try:
            import json
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except Exception:
            return  # unreadable: a rewrite is the repair, not the defect
        rows = data if isinstance(data, list) else next(
            (data.get(k) for k in ("rows", "items", "plan") if isinstance(data.get(k), list)), [])
        ids = [str(r.get("id")) for r in rows if isinstance(r, dict) and r.get("id")]
        if not ids:
            return  # no rows yet: this Write is still the plan's first shape
        ways = role_ways(event)
        shell = ("  python \"${CLAUDE_PLUGIN_ROOT}/scripts/plan_row.py\" --task <TICKET> "
                 "--row <TS-n> --set <field>=<value>   (one field; repeatable)\n"
                 "  python \"${CLAUDE_PLUGIN_ROOT}/scripts/plan_row.py\" --task <TICKET> "
                 "--add-row <json|file>                (one new row you wrote)\n") if "Bash" in ways else ""
        editor = ("  Edit                                                                  "
                  "        (one row's own lines; several Edit calls in one turn)") if "Edit" in ways else ""
        # The door of the ban (FR-57). A plan left half written by an interrupted run (TP1-13877: 3
        # rows) is CONTINUED by default; only when nothing in it is usable is it set aside. Named only
        # to a role that can run the command - the same test as the commands above.
        story = _STORY_RE.search(raw)
        door = ("\nA run of yours that was cut off may have left this plan half written: continue it - keep the "
                "rows that parse and pass their check, repair a stale row with `plan_row.py --set`, add the "
                "rest with `--add-row`. Only when nothing in it is usable, set it aside and write the plan "
                "again:\n  python \"${CLAUDE_PLUGIN_ROOT}/scripts/artifact_supersede.py\" --task "
                f"{story.group(1) if story else '<TICKET>'} --path {raw.split(story.group(0), 1)[1] if story else 'work/test-plan.json'} "
                "--role <your role> --reason \"<one line>\"\n(it moves the file to `.superseded`; your next "
                "Write of it is its first.)") if "Bash" in ways else ""
        block(f"PRE-TOOL GUARD: this plan already holds {len(ids)} rows ({', '.join(ids[:6])}"
              f"{', …' if len(ids) > 6 else ''}), and a Write replaces the file whole. Measured on "
              "this very story: 59 whole rewrites of this file, 525,812 tokens of arguments that "
              "then sat in the strategist's context and were re-read on every later turn; two "
              "booleans once cost $16.53. What your role can use here:\n" + shell + editor + door)
    else:
        story = _STORY_RE.search(raw)
        ways = role_ways(event)
        door = ("\nIf a run of yours was cut off and left this file with nothing in it to continue from, set it "
                "aside and write it again:\n  python \"${CLAUDE_PLUGIN_ROOT}/scripts/artifact_supersede.py\" "
                f"--task {story.group(1) if story else '<TICKET>'} --path "
                f"{raw.split(story.group(0), 1)[1] if story else 'work/test-plan.md'} "
                "--role <your role> --reason \"<one line>\"\n(it moves the file to `.superseded`; your next "
                "Write of it is its first.)") if "Bash" in ways else ""
        # TP2-2406 S3-3 (15.10): this text sent every role, the strategist included, to plan_row.py - a
        # command a role without Bash cannot run (the JSON branch above already names Edit through role_ways). The
        # machine copy's door is named by what THIS role has, and only a role with a shell is sent to the script.
        machine = ("it is changed with plan_row.py, never by hand." if "Bash" in ways else
                   "it is changed with Edit, one row's own lines at a time, never by a whole Write; "
                   "code checks the plan when it is saved." if "Edit" in ways else "")
        block("PRE-TOOL GUARD: test-plan.md already exists and a Write replaces it whole — on this "
              "story that cost 27,648 tokens of arguments over 8 rewrites, all of it re-read on "
              "every later turn of the dispatch. This file is the human's copy of the plan, in your "
              "own words: change the lines that changed with Edit (one call per line, several calls "
              "in one turn), and add a new row's line the same way."
              + (" The machine copy is test-plan.json, and " + machine if machine else "") + door)


def manifest_write_check(event: dict, cfg: dict) -> None:
    """automation-manifest.json is merged into, never replaced.

    S5's windows run one after another *because they write the same file* — a rule that
    lived in the orchestrator's phase file and nowhere else. On TP2-2104 window 2
    wrote the manifest whole and window 1 vanished from it: accepted work, with its evidence
    still on disk, that had to be reconstructed by hand. A `Write` replaces a file by
    definition, so a `Write` over a manifest that already holds entries is the defect
    itself; `manifest_put.py` merges by case, and `Edit` changes a line without touching the
    rest."""
    if (event or {}).get("tool_name") != "Write":
        return
    raw = str(((event or {}).get("tool_input") or {}).get("file_path") or "").replace("\\", "/")
    if not raw.endswith("automation-manifest.json"):
        return
    try:
        import json
        current = json.loads(Path(raw).read_text(encoding="utf-8"))
    except Exception:
        return  # absent or unreadable: the first window writes it, and that is the only Write
    held = [e for key in ("tests", "unresolved")
            for e in (current.get(key) or []) if isinstance(e, dict)]
    if not held:
        return
    cases = ", ".join(sorted({str(e.get("case") or "?") for e in held})) or "some"
    block(f"PRE-TOOL GUARD: this manifest already holds {len(held)} entr"
          f"{'y' if len(held) == 1 else 'ies'} ({cases}), and a Write replaces the file — "
          "which is how window 1's work was lost on TP2-2104 and had to be rebuilt "
          "from the journal and the evidence logs. Merge instead: write your window as a "
          "fragment and run `scripts/manifest_put.py --task <TICKET> --fragment <file.json>` "
          "(it replaces the entries for your cases by id, keeps everyone else's, and appends "
          "to runs[]/self_fixes[]). To change one field of one entry, use Edit.")


def _dispatch_open_for_owner(controller: dict, owner: str, named: str = "") -> bool:
    """True when `state/controller.json` shows the owning role doing the writing itself.

    Two independent readings, either is enough: (1) some dispatch record carries that role
    and `status == "running"` — this is set the instant `--operation dispatch` records the
    request (`controller.py` `dispatch` event), REWORK OF AN ACCEPTED STAGE INCLUDED, because
    the per-dispatch record's own status is never touched by `set_stage`'s monotonic merge
    — only the STAGE's rolled-up status stays `completed`. (2) a stage carries the
    legacy `rework` sub-state (the `stage_transition` path) and its active dispatch is the
    owning role — kept for the one other way a rework gets recorded."""
    dispatches = controller.get("dispatches") if isinstance(controller.get("dispatches"), dict) else {}
    held = None
    if named:
        # A session that carries its dispatch's name (`named`) opens the owner's guard only as that dispatch: a sibling of
        # the owner running beside it must not (TR3-14 invariant). A name this story does not hold: today's "any".
        import dispatch_identity
        held = dispatch_identity.held(dispatches, named)
    if held:
        if len(held) == 1 and held[0].get("status") == "running" and role_name(str(held[0].get("role") or "")) == owner:
            return True
    elif any(isinstance(d, dict) and role_name(str(d.get("role") or "")) == owner
             and d.get("status") == "running" for d in dispatches.values()):
        return True
    stages = controller.get("stages") if isinstance(controller.get("stages"), dict) else {}
    for stage in stages.values():
        if not isinstance(stage, dict) or not stage.get("rework"):
            continue
        active_id = stage.get("active_dispatch_id") or stage.get("dispatch_id")
        active = dispatches.get(active_id) if active_id else None
        if isinstance(active, dict) and role_name(str(active.get("role") or "")) == owner:
            return True
    return False


def _any_story_open_for_owner(event: dict, owner: str) -> bool:
    """Any story of this project with an open dispatch of THIS role. `_project_has_open_dispatch`
    asks the same question without the role, which is not enough for an artifact that belongs to
    one: the retro analyst's ledgers must not be repaired while only the scout is running."""
    try:
        import json
        import dispatch_identity
        from hooklib import artifact_root
        name = dispatch_identity.named()
        for controller_path in artifact_root(event).glob("*/state/controller.json"):
            try:
                data = json.loads(controller_path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if _dispatch_open_for_owner(data, owner, name):
                return True
    except Exception:
        return False
    return False


def owner_check(event: dict, cfg: dict) -> None:
    """An artifact is repaired by the role that owns it, not by whoever noticed.

    Roles hand back artifacts that are incomplete or inconsistent, and the validator's
    rejection lands on the orchestrator after the dispatch has closed — so the cheap move
    was to fix it by hand. It happened on all three green-lantern stories: manifest entries
    reconstructed after a window overwrote them, report and manifest structures corrected
    once the roles had finished, a runner's omission patched instead of returned. The
    artifact then has no reviewer, and the correction is spent out of the orchestrator's
    context, which is already 40% of a story's bill.

    A 0.7.5 regression: this used to read ONE stage-level flag in `pipeline.json` —
    "is any stage `running`" — plus a `/subagents/` mark in `transcript_path`. Neither
    survived 0.7.5. `set_stage`'s monotonic merge keeps an accepted stage `completed`
    during rework, so no stage ever shows `running` again; and on Claude Code the hook
    receives the PARENT session's transcript path even for a call made inside a subagent, so
    `/subagents/` never appears either. `S4-qa-case-designer-3`, dispatched to rework two
    already-reviewed cases, could not make a single one of its four edits — the designer had
    no way back into its own artifact.

    Three independent readings now decide it, any one lets the write through: (1) the host's
    own agent fields say this call IS the owning role — Claude Code sends `agent_id` /
    `agent_type` on a PreToolUse fired inside a subagent call (checked against the Claude
    Code hooks reference, not assumed); (2) `state/controller.json` has an open (`running`)
    dispatch of the owning role for this story, rework included (`_dispatch_open_for_owner`);
    (3) no controller.json exists yet (a story predating it) — the 0.7.4 `pipeline.json`
    signal is honoured so an already-onboarded project keeps working, plus the historical
    `/subagents/` mark for whichever host still sends it. Still deliberately fail-open: no
    story on disk at all is not this guard's business."""
    if (event or {}).get("tool_name") not in ("Write", "Edit", "NotebookEdit"):
        return
    raw = str(((event or {}).get("tool_input") or {}).get("file_path") or "").replace("\\", "/")
    if not raw:
        return
    owner, outside_story = _owner_of_path(raw, cfg)
    if owner is None:
        return
    story = _STORY_RE.search(raw)
    if not story and not outside_story:
        return
    ticket = story.group(1) if story else ""
    if role_name(subagent_type(event)) == owner:
        return  # the host's own event says this IS the owning role writing
    if not ticket:
        # A project-level ledger (`project:obligations.md`, `project:factory-backlog.md`,
        # `bugs/`) carries no ticket in its path, so there is no one story's controller to ask:
        # any story of this project with an open dispatch of the owning role answers instead.
        if _any_story_open_for_owner(event, owner):
            return
        block(f"PRE-TOOL GUARD: {raw.rsplit('/', 1)[-1]} belongs to {owner}, and no story of "
              f"this project has an open dispatch of that role — this is a repair from outside "
              f"the role that owns the artifact. Send it back instead: `controller.py "
              f"--operation rework --stage <STAGE> --role {owner} --reason \"...\" --brief` builds a "
              "fresh dispatch request from that role's last accepted work, ready to hand to "
              "`Agent`. An artifact the orchestrator fixed by hand has no reviewer.")
        return
    import json
    from hooklib import artifacts_dir
    try:
        controller = json.loads((artifacts_dir(ticket, event) / "state" / "controller.json")
                                .read_text(encoding="utf-8"))
    except Exception:
        controller = None
    if controller is not None:
        import dispatch_identity
        if _dispatch_open_for_owner(controller, owner, dispatch_identity.named()):
            return  # a dispatch of the owning role is open (the named session's own, if it has a name), rework included
    else:
        try:
            pipeline = json.loads((artifacts_dir(ticket, event) / "pipeline.json")
                                  .read_text(encoding="utf-8"))
        except Exception:
            return  # no controller, no pipeline, no story — not the guard's business
        stages = pipeline.get("stages") if isinstance(pipeline.get("stages"), dict) else {}
        if any((v or {}).get("status") == "running" for v in stages.values() if isinstance(v, dict)):
            return  # pre-controller story: the 0.7.4 signal still applies
    if "/subagents/" in str((event or {}).get("transcript_path") or "").replace("\\", "/"):
        return  # a subagent transcript is honoured wherever a host still sends one
    block(f"PRE-TOOL GUARD: {raw.rsplit('/', 1)[-1]} belongs to {owner}, and no dispatch of "
          f"{ticket} is open for that role — this is a repair from outside the role that owns "
          "the artifact. Send it back instead: `controller.py --operation rework --stage "
          f"<STAGE> --role {owner} --cases <ids> --reason \"...\" --brief` builds a fresh dispatch "
          "request from that role's last accepted work (input_hash, known_paths, budget), "
          "ready to hand to `Agent`. Do NOT `SendMessage` an id from an earlier session — "
          "Claude Code refuses it with \"No transcript found\" once the window has changed, "
          "which is exactly the dead end TP1-15045 hit here. An artifact the orchestrator "
          "fixed by hand has no reviewer, and the fix is paid for out of the one context that "
          "lives the whole story. Do NOT reopen the stage to make room for the fix: on "
          "TP1-15045 this advice sent the orchestrator to `stage_done --status running` "
          "on a stage the controller had already accepted, the stage was lowered, `--status "
          "done` then refused it, and the story stalled one step before gate A. An accepted "
          "stage is reworked without being lowered — a fresh dispatch of the same stage "
          "records it as rework, and a changed plan is recorded with `controller.py "
          "--operation revise_plan`.")


def _window_dispatch_of_session(controller: dict, name: str) -> dict | None:
    """The record of the S5 window dispatch of `qa-automator` that THIS session works for, or None.

    The name must be a record of THIS story (a name the story does not hold falls to `dispatch_identity.own`'s count rule,
    which here would attribute the session to a stranger: refused as None). A plan dispatch has no window: which dispatch is a
    plan is `controller.s5_part_of`'s word, the one reader (AR-13)."""
    import dispatch_identity as DI
    dispatches = controller.get("dispatches") if isinstance(controller, dict) else None
    record = DI.own(dispatches, role="qa-automator", stage="S5", name=name)
    if not record or record.get("id") != name:
        return None
    from controller import s5_part_of        # below every cheap return: only an S5 automator window pays the import (AR-12)
    return None if s5_part_of(record) == "plan" else record


def _window_note(event: dict, text: str) -> None:
    """A state the window-file check could not read, said through `hooklib.notice` (the one carrier with a reader, AR-15) to the
    person as a journal signal: a fence on a write is outside FR-59's scope, and its declared direction is a pass, said not silent."""
    import hooklib
    hooklib.notice(event, f"window_file_check: {text}; this write was not checked against the claims of other windows",
                   reader="person")


def _sessions_of(event: dict, name: str) -> list:
    """`(task root, controller, record)` for every story of this project whose controller holds the S5 window dispatch `name`
    with a scope. A controller that cannot be read is retried three times at 20 ms (a rename in flight; a transient sharing error
    on Windows), then passed with one notice naming the story: an unknown is said, and refusing outright would dead-end the door
    (FR-57). A fence on a write is outside FR-59's scope (no gate judging a run, test, stand or proof); its pass is declared."""
    import time
    from hooklib import artifact_root
    out = []
    try:
        paths = sorted(artifact_root(event).glob("*/state/controller.json"))
    except Exception as exc:
        _window_note(event, f"the story folders could not be listed ({type(exc).__name__})")
        return out
    for path in paths:
        controller = None
        for attempt in range(3):
            try:
                controller = json.loads(path.read_text(encoding="utf-8"))
                break
            except Exception:
                if attempt < 2:
                    time.sleep(0.02)
        if controller is None:
            _window_note(event, f"the controller of story {path.parent.parent.name} could not be read")
            continue
        record = _window_dispatch_of_session(controller, name)
        if record and any(str(c) for c in (record.get("scope") or [])):
            out.append((path.parent.parent, controller, record))
    return out


def window_file_check(event: dict, cfg: dict) -> None:
    """First-write ownership of a test file by an S5 window (spec t-1937 F3 b, TR3-16; AR-9, AR-14, AR-25).

    Two windows of one story that run side by side must not write one test file. The first window to Write or Edit a test file
    claims it (`window_files.claim`); a later write by another window is refused with the door a role can always use: a
    new file in the same directory. P17 stays the role's (where a test lives); the refusal does not judge the test.

    In order, each a return: no dispatch name in the environment (`dispatch_identity.named()`); `dispatch.parallel_windows` is 1
    (one window at a time: nothing is claimed, the old road literally); not an S5 window dispatch of `qa-automator` (any story of
    this project that holds the name); the path is not inside the project; the path is not a test body
    (`test_files.is_test_for("test_body", ...)` not literally True: a support file, a fixture or an unknown passes, F10).
    Then claim: a claim holds until `window_files.release` (no liveness reading, no takeover); the holder is this window's own
    when it shares a case with it (a repair round, a grown round), else the write is refused. An empty claim file (a crash between
    create and write) is an unknown owner and refuses with the same door and a note. A controller that cannot be read is retried,
    then passed with a notice to the person (`_sessions_of`). A second refusal in a row names the story's state, not the guard.
    A Bash write is not seen here (the named known gap; the launch gate is the net).

    ERROR DIRECTION: it may refuse needlessly (a new file is always possible); it never lets two windows write one file
    through Write, Edit or NotebookEdit when it can read the story. Class `safety` (a guard on a write); the owner it serves is
    the intent that two windows do not tear one file, not a judgment of the test."""
    if (event or {}).get("tool_name") not in ("Write", "Edit", "NotebookEdit"):
        return
    import dispatch_identity as DI
    name = DI.named()
    if not name:
        return
    tool_input = (event or {}).get("tool_input") or {}
    raw = str(tool_input.get("file_path") or tool_input.get("notebook_path") or "")    # NotebookEdit names it `notebook_path`
    if not raw:
        return
    import config_contract
    if config_contract.parallel_windows(cfg)[0] == 1:
        return                                       # one window at a time: no second window to meet, the old road literally
    sessions = _sessions_of(event, name)
    if not sessions:
        return
    import window_files as WF
    project = project_root(event)
    rel = WF.project_rel(project, raw)
    if rel is None:
        return
    import test_files
    if test_files.is_test_for("test_body", rel, cfg, root=project) is not True:
        return
    for task_root, _controller, record in sessions:
        mine = WF.window_id("S5", record.get("scope"))
        owner = WF.claim(task_root, rel, mine, name)
        if owner != mine:
            count = _escalation_count("PT-window-file", event, rel)     # the count only: this refusal is the story's state, not a guard fault
            block(_window_refusal(WF, task_root, rel, owner, count))


def _window_refusal(WF, task_root, rel: str, owner: str, count: int) -> str:
    """The text of a refused write: whose file it is, the door, the conductor's way out; from the second refusal in a row the
    state of the story (windows meeting on files) and the move, never a claim that the guard is at fault (FR-1, FR-46, FR-57)."""
    directory = rel.rsplit("/", 1)[0] if "/" in rel else "."
    text = (f"PRE-TOOL GUARD: this test file belongs to window {WF.cases_of(owner) if owner else 'another window'} until that "
            f"window closes. Put your test in a new file in the same directory: {directory}. Where a test lives stays your "
            "choice (P17); a test in a new file is judged the same.")
    free = (f'python "${{CLAUDE_PLUGIN_ROOT}}/scripts/window_files.py" --task "{Path(task_root).as_posix()}" '
            "--release ")
    if owner:
        text += f" If the file must change hands, the conductor frees the claim with: {free}\"{owner}\""
    else:
        text += (" (The claim on this file cannot be read, so its owner is unknown; once it is 30 seconds old the conductor "
                 f"clears it with: {free}\"S5|\")")
    if count >= ESCALATES_AFTER:
        text += (f"\n\nThis is refusal {count} in a row on files another window holds: the windows of this story meet on the "
                 "same test files, which retrying does not change and which is not a fault of the guard. Nothing is stopped. Put "
                 "every test of yours that needs a claimed file into a new file in its directory, and say in your hand-back which "
                 "files you could not write and which window holds them, so the conductor can regroup the plan.")
    return text


WRITES_MSG = ('PRE-TOOL GUARD: writing to a tracker or a test-management system from a shell is blocked. '
              'No role creates, edits, closes, transitions or comments on an external item directly - not '
              'even a "harmless" comment. Write a PROPOSAL FILE under '
              '`qa-factory/artifacts/<TICKET>/work/proposals/` in the shape external-writes.md defines; '
              'after gate B the orchestrator runs `<plugin>/scripts/external_writes.py`, which performs the '
              'write for the channels config.json permits and never overwrites text a human wrote. Reading '
              'is not blocked: `list`, `view`, `search` and a ticket read through `ticket_adapter.py` all '
              'pass. Creating the MR is a separate, stage-gated path and is unaffected.')

# Tracker/TMS CLIs and the write verbs. Reads (`list`, `view`, `get`, `search`) are how the
# scout grounds a story and must stay free; only the verbs that change something on the other
# side are blocked. `mr`/`pr` objects are deliberately absent: creating the merge request is
# the delivery path, governed by the stage guard's rule 4, not by this check.
_TRACKER_CLIS = ("glab", "gh", "jira", "az", "trello", "linear", "youtrack", "tr", "testrail", "xray")
_WRITE_VERBS = ("create", "update", "edit", "close", "reopen", "delete", "comment", "note",
                "transition", "move", "assign", "label", "add", "set", "post", "upload")
_WRITE_OBJECTS = ("issue", "issues", "ticket", "work-item", "workitem", "boards", "case",
                  "testcase", "test-case", "run", "execution", "epic", "story")
_METHOD_WRITE = ("-x post", "-x put", "-x patch", "-x delete", "--method post", "--method put",
                 "--method patch", "--method delete")
# The sanctioned paths: the executor that IS allowed to write, and the one reader of tickets.


def _declared_write_commands(cfg: dict) -> list:
    """The write commands this project declared. A role must not call one; only the executor.

    The factory ships no tracker CLI and names none: whatever the project put in
    `external_writes` is by definition a command that writes to somebody else's system."""
    out = []
    ew = (cfg or {}).get("external_writes") or {}
    for cmd in (ew.get("commands") or {}).values():
        head = str(cmd or "").strip().split()
        if head:
            out.append(head[0].strip('"').strip("'").lower())
    for delivery in (ew.get("channels") or {}).values():
        if isinstance(delivery, dict):
            head = str(delivery.get("command") or "").strip().split()
            if head:
                out.append(head[0].strip('"').strip("'").lower())
    return [c for c in out if c]


def writes_check(event: dict, cfg: dict) -> None:
    """No role writes to an external system; it writes a proposal file (common-rules.md).

    The rule was absolute in prose and enforced by nothing: a role holding `Bash` could run
    `glab issue create` and the factory would never know. Blocking it here makes the rule the
    same kind of fact as "tests run through run_suite" - the guard refuses and its message
    names the sanctioned path, so the role learns it in one turn instead of after a review."""
    if (event or {}).get("tool_name") not in ("Bash", "PowerShell"):
        return
    parts = command_text_parts(((event or {}).get("tool_input") or {}).get("command"))
    low = parts["exec"].lower()
    if not low.strip():
        return
    tokens = [tk.strip('"').strip("'") for tk in re.findall(r"[^\s'\"|;&<>()]+", low)]
    if not tokens:
        return
    declared = _declared_write_commands(cfg)
    for i, tk in enumerate(tokens):
        exe = tk.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
        if exe in declared:
            block(WRITES_MSG + where_clause(parts))
        if exe not in _TRACKER_CLIS:
            continue
        rest = tokens[i + 1:i + 5]
        if any(obj in rest for obj in _WRITE_OBJECTS) and any(v in rest for v in _WRITE_VERBS):
            block(WRITES_MSG + where_clause(parts))
        if "api" in rest and any(m in low for m in _METHOD_WRITE):
            block(WRITES_MSG + where_clause(parts))


HUMAN_WORD_MSG = ("PRE-TOOL GUARD: a person's word is recorded by the orchestrator, never by a role. "
                  "`waiver.py --stage`, `ticket_adapter.py accept-gap` and `ticket_adapter.py review "
                  "--record` store what the PERSON said so that a gate stops blocking on it; a role "
                  "running them would be the factory excusing itself. "
                  "`waiver.py --carry-from` copies what a person said under another key; a role running it would be excusing itself "
                  "with someone else's words. "
                  "`source_exclusions.py --load` and `--revoke` store which sources the person left out "
                  "before the run, or took back; a role running them would be choosing its own sources "
                  "(`--show` is open to you). "
                  "`stand_identity.py record`, `confirm`, `forget` and `unconfirm` store what the person said about "
                  "which build a stand runs; a role running them would be confirming its own build "
                  "(`show` and `validate` are open to you). "
                  "`environment_record.py record` and `revoke` store what the person accepted as a property of the environment, "
                  "or took back; a role running them would be excusing its own gap (`show` is open to you). "
                  "`project_knowledge.py account`, `role` and `revoke` store what the person said about the product's roles and "
                  "the stand's accounts, or take it back; a role running them would turn its own inference into a project fact "
                  "(`show` is open to you). "
                  "`project_knowledge.py side` stores what the person said about the product's sides (which are real on a stand, "
                  "whose they are, which stand runs the old version); a role running it would declare its own substitute real or "
                  "its own gap someone else's (`show` is open to you). "
                  "`report_adapt.py kind` changes how a test command's report is read in the project's configuration; that is the "
                  "driver's or the conductor's move, and a role that cannot read a report hands the kept report over in its digest "
                  "(`understood` and `show` are open to you). "
                  "`story_step.py decide` records the person's decision about a dispatch (the cases they run themselves, work "
                  "left open, a stage closed as it is); a role running it would hand its own cases to the person or close its "
                  "own stage (`finish` is open to you). "
                  "Return the open point in your "
                  "digest — the orchestrator shows it to the person and records the answer.")


def human_word_check(event: dict, cfg: dict) -> None:
    """The commands that turn a person's words into a passed gate, or into a source left out
    before the run (`source_exclusions.py --load` / `--revoke`), are closed to every
    role. They are what makes every block passable, so they must not be self-service.

    Matched against the executable part only (command_text_parts): on 2026-09-23 a role
    quoting one of these calls inside a heredoc it was writing to a file was refused, and
    went around the guard rather than past it."""
    if (event or {}).get("tool_name") not in ("Bash", "PowerShell"):
        return
    parts = command_text_parts(((event or {}).get("tool_input") or {}).get("command"))
    low = parts["exec"].lower()
    records = (("waiver.py" in low and "--stage" in low)
               # GW1-40: `--carry-from` copies a person's words from another key; the flag is named as a whole option, so another
               # script's flag of the same name (`handoff_init.py --carry-from`) is not closed
               or ("waiver.py" in low and re.search(r"--carry-from(?![\w-])", low))
               or ("ticket_adapter.py" in low and "accept-gap" in low)
               or ("ticket_adapter.py" in low and " review" in low and "--record" in low)
               # The person's list of sources to leave out, and taking one back. `--show` stays open
               # (FR-39: a role may read what it is told not to read); the script's argparse takes no
               # abbreviation, so these two spellings are the whole door.
               or ("source_exclusions.py" in low and re.search(r"--(?:load|revoke)(?![\w-])", low))
               # The person's word about which build a stand runs (t-300 Q12): with these a role could confirm
               # its own build and unblock its own run. `show` and `validate` only read, and stay open (FR-39).
               # The subcommand is the word right after the script (the CLI has no option before it): after a space,
               # or after the comma of an argument list (`['stand_identity.py', 'confirm', ...]`).
               or re.search(r"stand_identity\.py[\"']?(?:\s*,\s*|\s+)[\"']?(?:record|confirm|forget|unconfirm)(?![\w-])", low)
               # What the person accepted ONCE as a property of the environment, and taking it back (B-414): the same door shape
               or re.search(r"environment_record\.py[\"']?(?:\s*,\s*|\s+)[\"']?(?:record|revoke)(?![\w-])", low)
               # What the person said about the product's roles and the stand's accounts, and taking it back (PK0-8): the same door shape;
               # `show` stays open
               or re.search(r"project_knowledge\.py[\"']?(?:\s*,\s*|\s+)[\"']?(?:account|role|revoke|side)(?![\w-])", low)
               # B-416 M10: `report_adapt.py kind` writes the config's report kind and `forget` takes the helper's row back (it would
               # reset the one-turn bound); `config_write_check` reacts only to a `config.json` path word, and this script names none,
               # so the role door is closed here for both. `understood` and `show` stay open.
               or re.search(r"report_adapt\.py[\"']?(?:\s*,\s*|\s+)[\"']?(?:kind|forget)(?![\w-])", low)
               # t-721 D4: `story_step.py decide` records the person's decision about a dispatch (the S5 cases they run
               # themselves, work left open, a stage closed as it is). With it a role could hand its own cases to the
               # person, or close its own stage: closed to every role, like the other doors that record their word.
               or re.search(r"story_step\.py[\"']?(?:\s*,\s*|\s+)[\"']?decide(?![\w-])", low))
    if not records:
        return
    from_role = (str((event or {}).get("agent_type") or (event or {}).get("agent_name") or "").strip()
                 or "/subagents/" in str((event or {}).get("transcript_path") or "").replace("\\", "/"))
    if from_role:
        block(HUMAN_WORD_MSG + where_clause(parts))


# The text `budget_notice` leaves for `_flush_notice` to deliver on the way out of `main` (SC1-6). The notice used
# to be a `block()`: the call was thrown away and the role repeated it, 14 times in run 12586, each repeat a
# request over a 200-480K-token context. It now rides beside the call, which runs.
_NOTICE = ""


def budget_notice(event: dict, cfg: dict) -> None:
    """One notice when the caller's OWN tool calls cross the budget, and every interval
    after: a role's dispatch is counted by the host's `agent_id`, the orchestrator's window
    by session (turn_budget.py; one session-wide counter gave TP1-15045 43 notices about
    somebody else's calls). Nothing else in the factory counts turns, and the rule that
    depends on it — turn economy in common-rules.md — was the one nothing enforced.

    It only counts and records the text in `_NOTICE`; it never exits, so no rule after it is skipped and the
    call is never stopped by it. `_flush_notice` says it, once, whatever way `main` ends.

    Scoped by `_in_factory_scope`: a session with no factory activity and no role
    signature never sees this notice at all."""
    global _NOTICE
    if not _in_factory_scope(event):
        return
    try:
        import turn_budget
    except Exception:
        return
    try:
        notice = turn_budget.check(event, cfg)
    except Exception:
        return  # a counter never stands between a role and its work
    if notice:
        if str(event.get('agent_type') or '').split(':')[-1] == 'qa-scout':
            notice += " Discovery milestone only; continue required collection."
        _NOTICE = notice


def _flush_notice(event: dict, code: int) -> None:
    """Say the pending TURN BUDGET notice on the way out of `main`, then forget it.

    Exit 0: the model's channel (`host_adapter.notice_output`, the one place that knows the host's shape).
    Exit 2: another rule refused this call - the notice goes to stderr AFTER that refusal, marked as not part
    of it, so the refusal and its door keep their own words and are not buried. Any other exit (the guard
    itself failed): stderr. Nothing here raises: a notice never changes the way the guard ended."""
    global _NOTICE
    text, _NOTICE = _NOTICE, ""
    try:
        import hooklib
        # RH1-5 (AR-15): the budget notice joins the ONE queue of `hooklib.notice`, and `take_notices` says all of it
        # at once - this script is hooked on PreToolUse only, so an event without the name gets that one.
        hooklib.notice(event, text, reader="role")
        hooklib.take_notices(event, code, default_event="PreToolUse")
    except Exception:
        pass


def stage_check(event: dict, cfg: dict) -> None:
    """Stage guard rules 3 and 4 on the Bash side: a `git commit` touching test files while
    the automation manifest still has undecided holes, and a delivery command (the commands of
    references/adapter-forms.json and the project's `adapters.vcs.delivery_commands`; a TMS publish is
    not gated, it happens at S4) while the delivery verdict is not `yes` or `after_checks`. The fast gate
    (`needs_stage_guard`, given this call's `cfg`) is a cheap word test first, so an ordinary command
    never pays for loading the stage model or reading pipeline.json.

    The gate reads the RAW command, one line as the role wrote it (CX1-20 F-1): `command_text_parts` cuts a `$(` into
    `$` + LF and a `(` into LF, so on its `exec` text `git com$(true)mit` is `git com$` LF `true` LF `mit` and the words
    of a form are gone - while `stage_guard.check` reads the raw command anyway and is the judge of what is text."""
    if (event or {}).get("tool_name") not in ("Bash", "PowerShell"):
        return
    command = argv_text(((event or {}).get("tool_input") or {}).get("command"))   # a Codex argv list: its joined line
    try:
        import stage_guard  # type: ignore
    except ImportError:
        return
    if not stage_guard.needs_stage_guard(command, cfg):
        return
    if stage_guard.check(event) != 0:
        sys.exit(2)  # the reason is already on stderr, in the guard's own voice


CONFIG_WRITE_MSG = (
    "PRE-TOOL GUARD: a role does not write qa-factory/config.json (refused: {what}). The profile in that "
    "file holds the command every window of this story runs (commands.one_test, commands.collect, "
    "test_command_templates), so a change made from inside a dispatch changes the command under work that "
    "is already running, and nobody has reviewed it. If a launch or test command is what stops you, do not "
    "repair it in the profile: name `launch: <cause>` and the evidence line (the one line of the run's own "
    "error text) in your digest, and stop repairing that run. If you cannot tell the cause, write `launch: "
    "unknown` with the same evidence line. If a person's word is to change the profile, "
    "the orchestrator carries it out: it edits the profile itself and then runs `launch_check.py --profile "
    "<id>` to prove the command; put the point in your digest and it reaches the orchestrator. Reading the "
    "file is not blocked.")

# A ROLE never writes the profile (t-110, R-A5 as amended by K1 and K2). The main session - the
# orchestrator, the conductor, onboarding - is never refused: it edits the profile on a person's word
# while a dispatch runs. Error direction: toward PASS on anything unclear (a variable-held path, a
# helper script the role wrote); a detector at the dispatch boundary (story_step.py) catches what passes.
# The write shape and the profile's path must sit in ONE shell segment, the path in the destination
# position, so `sed -i x t.py && cat qa-factory/config.json` is a read and passes.
_SANCTIONED_CONFIG_SCRIPTS = {"config_contract.py": (), "project_decisions.py": (),
                              "runtime_probe.py": ("--write",), "ticket_adapter.py": ("--migrate-method",)}
_PY_WORDS = ("python", "python3", "python2", "py")
_COPY_HEADS = ("cp", "mv", "copy", "move", "copy-item", "move-item")
_PS_WRITERS = ("set-content", "add-content", "out-file")
# parameters of the PowerShell writers / copiers that take a value, so the value is not read as the path
_PS_VALUE_PARAMS = ("encoding", "value", "stream", "width", "inputobject", "delimiter", "filter",
                    "include", "exclude", "credential", "attributes")
_PY_OPEN_RE = re.compile(r"""\bopen\(\s*\\?(['"])(?P<p>[^'"]{1,400})\1\s*,\s*(?:mode\s*=\s*)?\\?(['"])"""
                         r"""(?P<m>[A-Za-z+]{1,4})\\?\3""")
_PY_WRITE_TEXT_RE = re.compile(r"""\(\s*\\?(['"])(?P<p>[^'"]{1,400})\1\s*\)\s*\.\s*write_(?:text|bytes)\(""")
# `Path('<literal>').open('w')`: the mode is the FIRST argument of the method, the path sits in the call before it
_PY_PATH_OPEN_RE = re.compile(r"""\(\s*\\?(['"])(?P<p>[^'"]{1,400})\1\s*\)\s*\.\s*open\(\s*(?:mode\s*=\s*)?"""
                              r"""\\?(['"])(?P<m>[A-Za-z+]{1,4})\\?\3""")
# `shutil.copy|copy2|copyfile|move(<anything>, '<literal>')` and `os.replace|rename(<anything>, '<literal>')`
# with the literal as the DESTINATION. `os.` is required for replace/rename: `text.replace(a, 'x')` is no write.
_PY_ONTO_RE = re.compile(
    r"""(?:\b(?:shutil\s*\.\s*)?(?:copy2?|copyfile|move)|\bos\s*\.\s*(?:replace|rename))\(\s*"""
    r"""(?:[^,()]|\([^()]{0,200}\)){1,400}?\s*,\s*\\?(['"])(?P<p>[^'"]{1,400})\1\s*[,)]""")
_PY_INTERPRETER_RE = re.compile(r"(?:python[0-9.]*|py)w?")


def _is_factory_role(event: dict) -> bool:
    """`subagent_type(event)` names a factory role: the host's own agent field on a call fired inside
    a subagent. No name (the main session), or a name that is no role of this factory (a built-in
    such as `general-purpose`), is not refused - the shape is reported, it never widens the ban.

    A subagent event that carries NO role name at all (a resumed session whose agent could not be
    found sends no `agent_type`) cannot be told from the main session, and the main session must
    never be refused, so it passes exactly as the main session does. The direction is deliberate:
    what passes here is caught by the detector at the dispatch boundary (`story_step.py`), which
    reports a profile changed under a running dispatch; a refusal aimed at the wrong caller has no
    detector and would lock the orchestrator out of the file it must edit."""
    role = role_name(subagent_type(event))
    if not role:
        return False
    return role.startswith("qa-") or (PLUGIN_ROOT / "agents" / f"{role}.md").is_file()


def _profile_matcher(event: dict):
    """A function `word -> bool`: does this path word name THIS project's qa-factory/config.json?
    Resolved, so either slash style and a relative or absolute spelling meet; a word holding a
    variable, a glob or a home shortcut it cannot expand is not decided (False = pass)."""
    root = project_root(event)
    target = os.path.normcase(str((Path(root) / "qa-factory" / "config.json").resolve()))
    cwd = str((event or {}).get("cwd") or "").strip()
    base = Path(_native_path(cwd)) if cwd and Path(_native_path(cwd)).is_dir() else Path(root)

    def names(word: str) -> bool:
        text = str(word or "").strip().strip("'\"").strip()
        if not text or len(text) > 1000 or any(c in text for c in "$%*?`\x00"):
            return False
        if not text.replace("\\", "/").lower().endswith("config.json"):
            return False
        path = Path(_native_path(text))
        path = path if path.is_absolute() else base / path
        return os.path.normcase(str(path.resolve())) == target

    return names


def _base_word(word: str) -> str:
    name = str(word or "").replace("\\", "/").rsplit("/", 1)[-1].lower()
    return name[:-4] if name.endswith(".exe") else name


def _run_target(words: list) -> tuple:
    """(name, arguments after it) of the command a segment actually RUNS: the program itself, or, for a
    python / `py` invocation, its script argument (`-c` / `-m` run no script file, so they name none).
    Leading `NAME=value`, `sudo`, `command`, `env`, `nohup` are not the command. A name that only
    appears among the arguments is not run - `echo x > f # config_contract.py` runs `echo`."""
    i = 0
    while i < len(words) and (re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", words[i])
                              or _base_word(words[i]) in ("sudo", "command", "env", "nohup")):
        i += 1
    if i >= len(words):
        return "", []
    head, args = _base_word(words[i]), words[i + 1:]
    if not _PY_INTERPRETER_RE.fullmatch(head):
        return head, args
    j = 0
    while j < len(args):
        word = args[j]
        if word in ("-W", "-X", "-Q"):
            j += 2  # these take the next word as their value
        elif word.startswith("-") and len(word) > 1:
            if word[1] in "cm":
                return "", []
            j += 1
        else:
            return _base_word(word), args[j + 1:]
    return "", []


def _shell_words(segment: str) -> tuple:
    """(words, redirect targets) of one shell segment, quotes removed. A `>` or `>>` outside quotes
    makes the next word a target (its file descriptor, `2>`, is dropped). A backslash stays a
    backslash: a Windows path is not an escape."""
    words: list = []
    targets: list = []
    cur: list = []
    state = {"has": False, "quoted": False, "expect": False}
    quote = ""
    i, n = 0, len(segment)

    def flush() -> None:
        nonlocal cur
        if state["has"]:
            (targets if state["expect"] else words).append("".join(cur))
            state["expect"] = False
        cur = []
        state["has"] = state["quoted"] = False

    while i < n:
        ch = segment[i]
        if quote:
            if ch == "\\" and quote == '"' and i + 1 < n and segment[i + 1] == '"':
                cur.append('"')
                i += 2
                continue
            if ch == quote:
                quote = ""
            else:
                cur.append(ch)
            i += 1
            continue
        if ch in "'\"":
            quote = ch
            state["has"] = state["quoted"] = True
        elif ch.isspace():
            flush()
        elif ch == ">":
            if state["has"] and not state["quoted"] and "".join(cur).isdigit():
                cur = []
                state["has"] = False
            else:
                flush()
            if i + 1 < n and segment[i + 1] == ">":
                i += 1
            state["expect"] = True
        else:
            cur.append(ch)
            state["has"] = True
        i += 1
    flush()
    return words, targets


def _split_args(args: list) -> tuple:
    """(flags, positionals): a word starting with `-` is a flag until a bare `--`; a lone `-` is not."""
    flags: list = []
    pos: list = []
    ended = False
    for word in args:
        if not ended and word == "--":
            ended = True
        elif not ended and word.startswith("-") and len(word) > 1:
            flags.append(word)
        else:
            pos.append(word)
    return flags, pos


def _edits_in_place(head: str, flags: list) -> bool:
    """`sed -i`, `sed -ni`, `sed --in-place=.bak`, `perl -i`, `perl -pi.bak`. A cluster is read letter by
    letter and stops at a letter that takes the rest as its argument, so `perl -Mstrict` is not `-i`."""
    takes_rest = "efl" if head != "perl" else "eEIMmxXCdDFlV0"
    for flag in flags:
        if flag.startswith("--"):
            if flag.startswith("--in-place"):
                return True
            continue
        for ch in flag[1:]:
            if ch == "i":
                return True
            if ch in takes_rest:
                break
    return False


def _named_or_positional(args: list, wanted: tuple, index: int = 0, other_named: tuple = ()):
    """The PowerShell argument for a parameter: the value of the named parameter (`wanted`, a prefix
    of at least two letters is enough, as PowerShell reads it), else the `index`-th positional once
    the value-taking parameters (`other_named` and _PS_VALUE_PARAMS) have taken their values.
    None when the command names none."""
    pos: list = []
    i = 0
    while i < len(args):
        word = args[i]
        if word.startswith("-") and len(word) > 1:
            name = word.lstrip("-").lower().split(":", 1)[0]
            if len(name) >= 2 and any(p.startswith(name) for p in wanted):
                if ":" in word:
                    return word.split(":", 1)[1]
                return args[i + 1] if i + 1 < len(args) else None
            if name in _PS_VALUE_PARAMS or (len(name) >= 2 and any(p.startswith(name) for p in other_named)):
                i += 1  # this parameter's value is not a positional
        else:
            pos.append(word)
        i += 1
    return pos[index] if len(pos) > index else None


def _segment_write_shape(words: list, targets: list, names) -> str:
    """The write shape this ONE segment carries on the profile, or ''."""
    if any(names(t) for t in targets):
        return "a redirection into it"
    i = 0
    while i < len(words) and (re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", words[i])
                              or _base_word(words[i]) in ("sudo", "command", "env", "nohup")):
        i += 1
    if i >= len(words):
        return ""
    head, args = _base_word(words[i]), words[i + 1:]
    flags, pos = _split_args(args)
    if head in ("sed", "gsed", "perl"):
        if _edits_in_place(head, flags) and any(names(p) for p in pos):
            return f"`{head} -i` on it"
    elif head == "tee":
        if any(names(p) for p in pos):
            return "`tee` into it"
    elif head in _PS_WRITERS:
        if names(_named_or_positional(args, ("path", "literalpath", "filepath"), 0) or ""):
            return f"`{head}` into it"
    elif head in ("rm", "del", "remove-item"):
        # the profile taken away is a write: the file the running command reads is gone
        if any(names(p) for p in pos) or names(_named_or_positional(args, ("path", "literalpath"), 0) or ""):
            return f"`{head}` of it"
    elif head in _COPY_HEADS:
        moves = head in ("mv", "move", "move-item")  # a move also TAKES AWAY its source
        sources: list = []
        if head in ("copy-item", "move-item"):
            # a named -Path / -LiteralPath is the source and takes no positional slot: the first
            # positional is then the destination (PowerShell binds Path 0, Destination 1)
            named_source = any(len(n) >= 2 and ("path".startswith(n) or "literalpath".startswith(n))
                               for n in (f.lstrip("-").lower().split(":", 1)[0] for f in flags))
            dest = _named_or_positional(args, ("destination",), 0 if named_source else 1,
                                        other_named=("path", "literalpath"))
            source = _named_or_positional(args, ("path", "literalpath"), 0, other_named=("destination",))
            sources = [source] if source is not None else []
        elif any(f in ("-t",) or f.startswith("--target-directory") for f in flags):
            dest, sources = None, pos  # the destination is a directory; every positional is a source
        else:
            if head in ("copy", "move"):
                pos = [p for p in pos if not re.match(r"^/[A-Za-z]$", p)]
            dest = pos[-1] if len(pos) >= 2 else None
            sources = pos[:-1] if len(pos) >= 2 else []
        if dest is not None and names(dest):
            return f"`{head}` with it as the destination"
        if moves and any(names(s) for s in sources):
            return f"`{head}` with it as the source (it is taken away)"
    elif head == "git":
        j = 0
        while j < len(args) and args[j].startswith("-"):
            j += 2 if args[j] in ("-C", "-c", "--git-dir", "--work-tree", "--namespace") else 1
        sub = args[j].lower() if j < len(args) else ""
        if sub in ("checkout", "restore"):
            rest_flags, rest_pos = _split_args(args[j + 1:])
            index_only = sub == "restore" and any(f in ("--staged", "-S") for f in rest_flags) \
                and not any(f in ("--worktree", "-W") for f in rest_flags)
            if not index_only and any(names(p) for p in rest_pos):
                return f"`git {sub}` of it"
    return ""


def _python_write_shape(text: str, names) -> str:
    """`open('<literal path>', 'w'|'a'|'x'|'r+')` or `Path('<literal path>').write_text(` in python code.
    A path held in a variable is not a literal and is not decided."""
    for m in _PY_OPEN_RE.finditer(text):
        if any(c in m.group("m") for c in "wax+") and names(m.group("p").rstrip("\\")):
            return "python `open(..., write mode)` on it"
    for m in _PY_PATH_OPEN_RE.finditer(text):
        if any(c in m.group("m") for c in "wax+") and names(m.group("p").rstrip("\\")):
            return "python `Path(...).open(write mode)` on it"
    for m in _PY_WRITE_TEXT_RE.finditer(text):
        if names(m.group("p").rstrip("\\")):
            return "python `write_text` on it"
    for m in _PY_ONTO_RE.finditer(text):
        if names(m.group("p").rstrip("\\")):
            return "python `shutil` / `os` copy or move onto it"
    return ""


def _shell_write_shape(event: dict, names, sanctioned=None) -> str:
    """The write shape this shell command carries on the files `names` recognises, or ''. `sanctioned` is the table
    of scripts that write those files by design and pass whatever their arguments (the profile's own writers by
    default; the stand records have none: a role runs no writer of them)."""
    sanctioned = _SANCTIONED_CONFIG_SCRIPTS if sanctioned is None else sanctioned
    command = str(((event or {}).get("tool_input") or {}).get("command") or "")
    stage_one = _split_off_bodies(command)[0]
    for segment in _segments(stage_one):
        words, targets = _shell_words(segment)
        # The sanction belongs to the command that is RUN in this segment - the program, or the script a
        # python invocation runs - never to a name that merely appears in it (`echo {} > qa-factory/config.json
        # # see config_contract.py`, `grep -l x config_contract.py > qa-factory/config.json`).
        target, after = _run_target(words)
        need = sanctioned.get(target)
        if need is not None and all(any(w == flag or w.startswith(flag + "=") for w in after) for flag in need):
            continue  # the scripts that write the profile by design pass whatever their arguments
        shape = _segment_write_shape(words, targets, names)
        if shape:
            return shape
        if any(_base_word(w) in _PY_WORDS for w in words):
            shape = _python_write_shape(segment, names)
            if shape:
                return shape
    for m in HEREDOC_RE.finditer(command):
        if not any(_base_word(w) in _PY_WORDS for w in _head_of_segment(command, m.start())):
            continue  # only an interpreter RUNS its heredoc body; the others store it as text
        newline = command.find("\n", m.end())
        if newline == -1:
            continue
        closer = re.compile(r"^[ \t]*" + re.escape(m.group(2)) + r"[ \t]*$", re.M).search(command, newline + 1)
        shape = _python_write_shape(command[newline + 1:closer.start() if closer else len(command)], names)
        if shape:
            return shape
    return ""


def config_write_check(event: dict, cfg: dict) -> None:
    """A role never writes `qa-factory/config.json` (t-110 / B-193, R-A5, K1, K2).

    The measured case: on a story run the automator edited the profile's test command on a person's
    gate answer, and the edit could never have worked (the request copies the story's last typed
    run), while the command every window runs changed under running work. Only a caller the host
    marks as a factory role is refused; the main session is not (it edits the profile itself on a
    person's word, then runs `launch_check.py`). Registered LAST in every chain of `main()`: every
    older refusal is reached exactly as before, and this one refuses only a call they all passed."""
    tool = (event or {}).get("tool_name")
    if tool not in ("Write", "Edit", "NotebookEdit", "Bash", "PowerShell"):
        return
    what = ""
    try:
        ti = (event or {}).get("tool_input") or {}
        if tool in ("Write", "Edit", "NotebookEdit"):
            mention = " ".join(str(ti.get(key) or "") for key in ("file_path", "notebook_path"))
        else:
            mention = str(ti.get("command") or "")
        # The cheap gate, BEFORE the role test and any path resolution: every spelling of the profile's
        # path ends in `config.json`, so a call that does not contain it costs a role what it costs the
        # main session (a substring test). Measured before this gate: a role paid ~13 ms per plain `ls`.
        if "config.json" not in mention.lower():
            return
        if not _is_factory_role(event):
            return
        names = _profile_matcher(event)
        if tool in ("Write", "Edit", "NotebookEdit"):
            if any(names(str(ti.get(key) or "")) for key in ("file_path", "notebook_path")):
                what = f"{tool} on it"
        else:
            what = _shell_write_shape(event, names)
    except Exception:
        return  # an error here is "cannot tell", and cannot-tell passes
    if what:
        block(CONFIG_WRITE_MSG.format(what=what))


STAND_RECORD_MSG = (
    "PRE-TOOL GUARD: a role does not write the stand registry, a story's stand confirmations, the environment record, the "
    "report adaptations or the project's answer registry (refused: {what}). "
    "`qa-factory/records/project-knowledge.json` is that registry: what a person said about the product's roles and the stand's "
    "accounts, written by the driver or the conductor with `project_knowledge.py` (`project_knowledge.py show` is open to you); "
    "if it lacks something you found, say so in your digest and the conductor records it - the stand halt below does not apply "
    "to this file. "
    "`qa-factory/records/stand-identity.json`, `qa-factory/artifacts/<story>/state/stand-confirmations.jsonl`, "
    "`qa-factory/records/environment-properties.json` and `qa-factory/records/report-adaptations.json` hold "
    "what a PERSON said about which build a stand runs and about what is a property of this environment (the last is "
    "written by the driver or the conductor with `environment_record.py`); a role writing them would be the factory taking "
    "its own word for its own build, and a run would pass on it. If the build of the stand is what stops you, hand off as a halt, in "
    "the digest's own form: the header ends `· halt`, one row `stand · blocked · <what is wrong, at most 80 characters>`, "
    "then the artifact path; put the one line of evidence in the handoff form's `blocked` section and run "
    "`handoff_help.py --file work/handoffs/<dispatch>.yaml`, then stop. The conductor reads it, asks the person if only "
    "the person can say, and records the answer with `stand_identity.py`. Reading the files, and `stand_identity.py show` "
    "/ `validate`, are not blocked.")


# The files under `qa-factory/records/` that hold a person's word about the environment: only the driver and the conductor write
# them (`stand_identity.py`, `environment_record.py`), never a role.
STAND_RECORD_FILES = ("stand-identity.json", "environment-properties.json", "report-adaptations.json", "project-knowledge.json")


def _stand_record_matcher(event: dict):
    """A function `word -> bool`: does this path word name THIS project's stand registry
    (`qa-factory/records/stand-identity.json`), its environment record (`qa-factory/records/environment-properties.json`,
    B-414), its project-knowledge registry (`qa-factory/records/project-knowledge.json`, PK0-8) or the stand confirmations of one of its stories
    (`<artifact root>/<story>/state/stand-confirmations.jsonl`)? Resolved, so either slash style and a relative or
    absolute spelling meet; a word holding a variable, a glob or a home shortcut it cannot expand is not decided
    (False = pass)."""
    root = project_root(event)
    records = {name: os.path.normcase(str((Path(root) / "qa-factory" / "records" / name).resolve()))
               for name in STAND_RECORD_FILES}
    from hooklib import artifact_root
    artifacts = os.path.normcase(str(Path(artifact_root(event)).resolve()))
    cwd = str((event or {}).get("cwd") or "").strip()
    base = Path(_native_path(cwd)) if cwd and Path(_native_path(cwd)).is_dir() else Path(root)

    def names(word: str) -> bool:
        text = str(word or "").strip().strip("'\"").strip()
        if not text or len(text) > 1000 or any(c in text for c in "$%*?`\x00"):
            return False
        low = text.replace("\\", "/").lower()
        if not low.endswith(STAND_RECORD_FILES + ("stand-confirmations.jsonl",)):
            return False
        path = Path(_native_path(text))
        resolved = (path if path.is_absolute() else base / path).resolve()
        if resolved.name.lower() in records:
            return os.path.normcase(str(resolved)) == records[resolved.name.lower()]
        return (resolved.name.lower() == "stand-confirmations.jsonl" and resolved.parent.name == "state"
                and os.path.normcase(str(resolved.parent.parent.parent)) == artifacts)

    return names


def stand_record_write_check(event: dict, cfg: dict) -> None:
    """A role never writes the stand registry, the environment record or a story's stand confirmations (t-300 Q12, §0b; the shape of
    `config_write_check`). The person-word commands are closed by `human_word_check`; this closes the other road to
    the same files - a Write, an Edit, a redirection, a copy - because the file IS the person's word.

    Only a call the host marks as a role's is refused (`_called_by_role`: the agent fields, which a driver-launched
    role gets from the dispatch binding `host_dispatch.enrich` adds to the event, or a subagent transcript); the main
    session, the driver and the conductor are never refused: they record the word. Error direction: toward PASS on
    anything unclear (a variable-held path, a helper script the role wrote, `python -c "import stand_identity ..."`
    or `-m stand_identity`: the token this guard and `human_word_check` look for is the script's file name). What
    passes is on discipline alone - detector: the next fresh run's bound role transcripts grepped for
    `import stand_identity` / `-m stand_identity`. `recorded_by` and `stand_identity.py validate` do NOT detect it
    (a line written through the library carries the same `recorded_by` and validates)."""
    tool = (event or {}).get("tool_name")
    if tool not in ("Write", "Edit", "NotebookEdit", "Bash", "PowerShell"):
        return
    what = ""
    try:
        ti = (event or {}).get("tool_input") or {}
        if tool in ("Write", "Edit", "NotebookEdit"):
            mention = " ".join(str(ti.get(key) or "") for key in ("file_path", "notebook_path"))
        else:
            mention = str(ti.get("command") or "")
        low = mention.lower()
        # The cheap gate, before the role test and any path resolution: every spelling of any of the files ends in its name.
        if not any(name in low for name in STAND_RECORD_FILES + ("stand-confirmations.jsonl",)):
            return
        if not _called_by_role(event):
            return
        names = _stand_record_matcher(event)
        if tool in ("Write", "Edit", "NotebookEdit"):
            if any(names(str(ti.get(key) or "")) for key in ("file_path", "notebook_path")):
                what = f"{tool} on it"
        else:
            what = _shell_write_shape(event, names, sanctioned={})
    except Exception:
        return  # an error here is "cannot tell", and cannot-tell passes
    if what:
        block(STAND_RECORD_MSG.format(what=what))


def _blocked(fn, event: dict, cfg: dict) -> str | None:
    """Runs a check and returns the blocking text (or None). For --selftest only."""
    import io
    import contextlib

    err = io.StringIO()
    try:
        with contextlib.redirect_stderr(err):
            fn(event, cfg)
    except SystemExit as e:
        if e.code == 2:
            return err.getvalue().strip()
        raise
    return None


def _noticed(fn, event: dict, cfg: dict) -> str | None:
    """Runs a rule that only records a notice (`budget_notice`) in this process and returns the text it left for
    `_flush_notice` (or None), clearing it. The notice twin of `_blocked`; used by --selftest and by
    test_guard_dispatch_budget_and_logs.py."""
    global _NOTICE
    _NOTICE = ""
    fn(event, cfg)
    text, _NOTICE = _NOTICE, ""
    return text or None


def selftest() -> int:
    # Line one names the root this selftest took. A hijacked root then reads as one line
    # instead of a dozen assertion mismatches (macOS 0.7.11, plugin clone inside a project).
    print(f"SELFTEST ROOT: {project_root()}")
    failures: list[str] = []

    def case(name: str, got, expected):
        if got != expected:
            failures.append(f"{name}: expected {expected!r}, got {got!r}")

    # 1. Write-marker semantics: stderr redirections do not count as writes.
    for cmd, expected in [
        ("ls -la", False),
        ("cat a.txt", False),
        ("grep -rn foo testproject1/src 2>&1", False),
        ("docker ps 2>/dev/null", False),
        ("Get-Content a.txt 2>$null", False),
        ("dir 2>NUL", False),
        ("poetry run pytest -q 2>&1 | tail -5", False),
        ("echo x > f.txt", True),
        ("echo x >> f.txt", True),
        ("rm -rf a", True),
        ("sed -i s/a/b/ f", True),
        ("Set-Content f.txt 'x'", True),
    ]:
        case(f"has_write_marker({cmd!r})", has_write_marker(cmd), expected)

    # 1b. Direct test launches (quiet runs): pytest at a command position, outside run_suite.
    for cmd, expected in [
        ("poetry run pytest tests/x.py -q", True),
        ("pytest", True),
        ("cd repo && python -m pytest tests", True),
        ("uv run pytest -x | tail -20", True),
        ("python run_suite.py --task T --label l -- poetry run pytest tests", False),
        ("poetry run pytest --collect-only -q", False),
        ("pytest --version", False),
        ("cat pytest.ini", False),
        ("grep -rn pytest tests/", False),
        ("poetry add pytest-rerunfailures", False),
    ]:
        case(f"is_direct_test_run({cmd!r})", is_direct_test_run(cmd), expected)

    # 2. The Python-only prefilter (needs_guard): the substring gate that replaces the
    # old shell prefilter — must let obviously-safe reads through and catch writes/tests.
    for cmd, expected in [
        ("ls -la", False),
        ("git status", False),
        ("cat a.txt", False),
        ("echo x > f.txt", True),
        ("pytest tests/", True),
        ("Set-Content f.txt 'x'", True),
        ("rm -rf a", True),
    ]:
        case(f"needs_guard({cmd!r})", needs_guard(cmd, {}), expected)

    # 1c. The blocked pytest is sent to the interface that is open to THIS caller: the
    # standalone one outside a dispatch, the typed one inside it (stage_guard refuses
    # --task/--label there, and the two messages used to contradict each other).
    _pytest = {"tool_name": "Bash", "tool_input": {"command": "poetry run pytest tests/x.py"}}
    case("a direct pytest outside a dispatch keeps the standalone interface",
         "--task <id> --label <label> -- <your command>" in (_blocked(runs_check, _pytest, {}) or ""),
         True)
    _role_event = dict(_pytest, agent_type="qa-factory:qa-automator")
    _role_msg = _blocked(runs_check, _role_event, {}) or ""
    case("a direct pytest inside a dispatch is sent to the typed request",
         "--request <request.json>" in _role_msg, True)
    case("and is told where the shape comes from", "--template request" in _role_msg, True)
    case("and is never sent to the interface the stage guard refuses there",
         "--label <label> -- <your command>" in _role_msg, False)

    # 3. A functional minimum of both checks against a synthetic config.
    cfg = {
        "app_root": ".",
        "protected_app_paths": ["app/src"],
        "secret_file_patterns": [r"\.env$"],
        "secret_content_patterns": [r"(?i)api[_-]?key\s*[=:]\s*['\"][A-Za-z0-9]{16,}['\"]"],
    }
    root = project_root()
    app_write = {"tool_name": "Write", "tool_input": {"file_path": str(root / "app" / "src" / "x.py")}}
    case("boundary: a write into app/src is blocked", bool(_blocked(app_guard.check, app_write, cfg)), True)
    own_write = {"tool_name": "Write", "tool_input": {"file_path": str(root / "qa-factory" / "x.md")}}
    case("boundary: a write into the factory's own state is allowed", _blocked(app_guard.check, own_write, cfg), None)
    read_cmd = {"tool_name": "Bash", "tool_input": {"command": "grep -rn foo app/src 2>&1"}}
    case("boundary: reading app/src with 2>&1 is not blocked", _blocked(app_guard.check, read_cmd, cfg), None)
    write_cmd = {"tool_name": "Bash", "tool_input": {"command": "echo x > app/src/y.py"}}
    case("boundary: a Bash write into app/src is blocked", bool(_blocked(app_guard.check, write_cmd, cfg)), True)
    quoted_path = {"tool_name": "Bash", "tool_input": {"command": "echo 'app/src/y.py' > notes.txt"}}
    case("boundary: a protected path quoted as data is allowed when target is outside",
         _blocked(app_guard.check, quoted_path, cfg), None)
    moved_path = {"tool_name": "PowerShell", "tool_input": {"command": "Move-Item app/src/y.py archive/y.py"}}
    case("boundary: moving a protected source is blocked",
         bool(_blocked(app_guard.check, moved_path, cfg)), True)

    # P-00 is absolute, so an empty protected_app_paths must be ANNOUNCED rather than passed
    # over: unenforced and unmentioned reads exactly like enforced. Silent only where the
    # plugin has no business speaking - a repository that was never onboarded.
    import io as _io
    from contextlib import redirect_stderr as _redirect_stderr
    unset_cfg = {"app_root": ".", "protected_app_paths": []}
    any_write = {"tool_name": "Write", "tool_input": {"file_path": str(root / "anything.py")}}
    def _warning_of(event_in, cfg_in):
        """_blocked() swallows stderr into its own buffer, so a WARNING would be invisible
        through it; call the check directly to see what it actually said."""
        err = _io.StringIO()
        blocked = None
        try:
            with _redirect_stderr(err):
                app_guard.check(event_in, cfg_in)
        except SystemExit:
            blocked = err.getvalue().strip()
        return blocked, err.getvalue()

    unset_blocked, unset_err = _warning_of(any_write, unset_cfg)
    case("boundary: an empty protected_app_paths does not block", unset_blocked, None)
    case("boundary: an empty protected_app_paths warns that P-00 is unenforced",
         "protected_app_paths is empty" in unset_err, True)
    _, silent_err = _warning_of(any_write, {})
    case("boundary: a repository with no config at all stays silent", silent_err.strip(), "")
    env_write = {"tool_name": "Write", "tool_input": {"file_path": str(root / ".env"), "content": "x"}}
    case("secrets: a write into .env is blocked", bool(_blocked(secrets_guard.check, env_write, cfg)), True)
    helper_write = {"tool_name": "Write", "tool_input": {
        "file_path": str(root / "tests" / "credentials_manager.py"), "content": "def load(): pass"}}
    case("secrets: benign credentials helper filename is allowed",
         _blocked(secrets_guard.check, helper_write, cfg), None)
    key_write = {
        "tool_name": "Write",
        "tool_input": {"file_path": str(root / "qa-factory" / "x.md"), "content": "api_key: 'ABCDEFGHIJKLMNOP'"},
    }
    case("secrets: a key signature in content is blocked", bool(_blocked(secrets_guard.check, key_write, cfg)), True)
    key_write_no_cfg = {
        "tool_name": "Write",
        "tool_input": {"file_path": str(root / "qa-factory" / "y.md"), "content": "api_key: 'ABCDEFGHIJKLMNOP'"},
    }
    case("secrets: guarded even with an empty config (no onboarding yet)",
         bool(_blocked(secrets_guard.check, key_write_no_cfg, {})), True)

    # The guard must not block the config that configures it: the shipped template carries
    # `(?i)aws_secret_access_key` as a DETECTOR. Blocking it is how a project ended up with
    # secret_content_patterns deleted "to get past the guard" and no content detectors left.
    template = (PLUGIN_ROOT / "references" / "templates" / "config.json").read_text(encoding="utf-8")
    template_write = {
        "tool_name": "Write",
        "tool_input": {"file_path": str(root / "qa-factory" / "config.json"), "content": template},
    }
    case("secrets: the factory's own config template is not a secret",
         _blocked(secrets_guard.check, template_write, cfg), None)
    # ...and a real credential inside that same config is still blocked.
    import json as _json
    poisoned = _json.loads(template)
    poisoned["environment"]["stolen"] = "api_key: 'ABCDEFGHIJKLMNOP'"
    poisoned_write = {
        "tool_name": "Write",
        "tool_input": {"file_path": str(root / "qa-factory" / "config.json"),
                       "content": _json.dumps(poisoned)},
    }
    case("secrets: a real credential inside the config is still blocked",
         bool(_blocked(secrets_guard.check, poisoned_write, cfg)), True)

    direct_run = {"tool_name": "Bash", "tool_input": {"command": "poetry run pytest tests/ -q 2>&1 | tail -30"}}
    case("runs: a direct pytest in Bash is blocked", bool(_blocked(runs_check, direct_run, cfg)), True)
    via_suite = {"tool_name": "Bash", "tool_input": {"command": "python run_suite.py --task T --label l -- poetry run pytest tests/"}}
    case("runs: pytest through run_suite is allowed", _blocked(runs_check, via_suite, cfg), None)

    # Raw run logs: readable by the audit on disk, not by an agent's context — by WEIGHT.
    # Sizes are the real ones of TP1-15045: a 1,212-byte red-probe log and a 238-byte
    # junit file were refused by extension; the 16,106-byte junit is what the rule is for.
    import tempfile as _tf_logs
    with _tf_logs.TemporaryDirectory(prefix="qa-rawlog-") as _ld:
        ev_dir = Path(_ld) / "qa-factory" / "artifacts" / "T-1" / "evidence" / "runs" / "2bbc13c5"
        ev_dir.mkdir(parents=True)
        big_log = ev_dir / "repair_verify-1.junit.xml"
        big_log.write_text("x" * 16106, encoding="utf-8")
        small_log = ev_dir / "red_probe-1.log"
        small_log.write_text("ERROR: not found: tests/test_a.py::test_x[buffer-R3-vs-selected-R1]\n" * 12,
                             encoding="utf-8")
        small_junit = ev_dir / "red_probe-1.junit.xml"
        small_junit.write_text("j" * 238, encoding="utf-8")
        edge_log = ev_dir / "edge.log"
        edge_log.write_text("e" * DEFAULT_RAW_LOG_FREE_BYTES, encoding="utf-8")
        rel = "qa-factory/artifacts/T-1/evidence/runs/2bbc13c5"

        def log_read(path):
            return {"tool_name": "Read", "cwd": _ld, "tool_input": {"file_path": str(path)}}

        def log_shell(command, tool="Bash", cwd=_ld):
            return {"tool_name": tool, "cwd": cwd, "tool_input": {"command": command}}

        refusal = _blocked(logs_check, log_read(big_log), cfg) or ""
        case("logs: Read of a heavy evidence .junit.xml is blocked", bool(refusal), True)
        case("logs: the refusal says how heavy and where the line is",
             ("16,106 bytes" in refusal) and ("8,192 bytes" in refusal), True)
        case("logs: and names the two routes that work under a dispatch",
             ("error_head" in refusal) and ("--request <request file> --detail <test>" in refusal), True)
        case("logs: Read of a small evidence .log passes", _blocked(logs_check, log_read(small_log), cfg), None)
        case("logs: Read of a small evidence .junit.xml passes",
             _blocked(logs_check, log_read(small_junit), cfg), None)
        case("logs: a log of exactly the free size passes", _blocked(logs_check, log_read(edge_log), cfg), None)
        case("logs: a Windows spelling of the heavy log is blocked the same",
             bool(_blocked(logs_check, log_read(str(big_log).replace("/", "\\")), cfg)), True)
        case("logs: a log that is not there is the tool's to report, not the guard's",
             _blocked(logs_check, log_read(ev_dir / "gone-1.log"), cfg), None)
        case("logs: the free size comes from config",
             bool(_blocked(logs_check, log_read(small_log), {"guards": {"raw_log_free_bytes": 100}})), True)
        case("logs: 0 frees nothing, as before 0.7.8",
             bool(_blocked(logs_check, log_read(small_junit), {"guards": {"raw_log_free_bytes": 0}})), True)
        case("logs: a raised free size lets the heavy one through",
             _blocked(logs_check, log_read(big_log), {"guards": {"raw_log_free_bytes": 20000}}), None)
        case("logs: an unusable value is the default, not a crash",
             (bool(_blocked(logs_check, log_read(big_log), {"guards": {"raw_log_free_bytes": "lots"}})),
              _blocked(logs_check, log_read(small_log), {"guards": "nonsense"})), (True, None))
        case("logs: a shell read of the heavy log is blocked",
             bool(_blocked(logs_check, log_shell(f"cat {rel}/repair_verify-1.junit.xml | tail -50"), cfg)), True)
        case("logs: a shell read of a small log passes",
             _blocked(logs_check, log_shell(f"cat {rel}/red_probe-1.log"), cfg), None)
        case("logs: the path is found through the command's own cd",
             bool(_blocked(logs_check, log_shell(
                 f"cd {Path(_ld).as_posix()} && python - <<'E'\nimport xml.etree.ElementTree as ET\n"
                 f"ET.parse(\"{rel}/repair_verify-1.junit.xml\")\nE", cwd=str(Path(_ld).parent)), cfg)), True)
        case("logs: PowerShell is weighed the same",
             (bool(_blocked(logs_check, log_shell(f"Get-Content {rel}/repair_verify-1.junit.xml", "PowerShell"), cfg)),
              _blocked(logs_check, log_shell(f"Get-Content {rel}/red_probe-1.log", "PowerShell"), cfg)),
             (True, None))
        case("logs: a wildcard is weighed whole",
             bool(_blocked(logs_check, log_shell(f"cat {rel}/*.junit.xml"), cfg)), True)
        case("logs: many small logs in one command add up",
             bool(_blocked(logs_check, log_shell(f"cat {rel}/red_probe-1.log {rel}/edge.log"), cfg)), True)
        case("logs: a shell read of a missing log is not blocked",
             _blocked(logs_check, log_shell(f"cat {rel}/gone-1.log"), cfg), None)
        case("logs: run_suite reading its own junitxml is exempt",
             _blocked(logs_check, log_shell(
                 f"python run_suite.py --task T-1 --label w --detail test_x {rel}/repair_verify-1.junit.xml"),
                 cfg), None)
    read_summary = {"tool_name": "Read",
                    "tool_input": {"file_path": "qa-factory/artifacts/T-1/evidence/witness-20260915-105617.json"}}
    case("logs: the .json summary is the intended channel", _blocked(logs_check, read_summary, cfg), None)
    read_shot = {"tool_name": "Read", "tool_input": {"file_path": "qa-factory/artifacts/T-1/evidence/step-3.png"}}
    case("logs: an evidence screenshot is not a log", _blocked(logs_check, read_shot, cfg), None)
    read_other = {"tool_name": "Read", "tool_input": {"file_path": "testproject1_test_harness/tests/test_a.py"}}
    case("logs: an ordinary file is untouched", _blocked(logs_check, read_other, cfg), None)

    # A large file is read by the range. The measurement: a 102,214-character diff read at
    # turn 10 of 140 was re-billed on the 130 turns after it (TP1-14336).
    import tempfile as _tf
    with _tf.TemporaryDirectory(prefix="qa-bigread-") as _td:
        big = Path(_td) / "impl-diff.txt"
        big.write_text("x" * 40000, encoding="utf-8")
        small = Path(_td) / "notes.md"
        small.write_text("y" * 100, encoding="utf-8")
        # A template is the plugin's own references/templates/ file, by its exact place (SC1-3 part 3): a folder that is merely
        # CALLED templates/ in a temp dir is no longer exempt. config.json there is 30,135 B, over the limit - the trap key.
        tpl = PLUGIN_ROOT / "references" / "templates" / "config.json"

        def read_ev(path, **extra):
            # these calls represent a ROLE reading its own diff/manifest mid-dispatch —
            # the exact scenario the cap exists for (TP1-14336) — so they carry a session
            # this block marks as having factory activity, putting them in scope like a real
            # role's Read. `_in_factory_scope`'s own on/off behaviour is proven separately
            # below ("scope: ..."), with events that deliberately carry none of the signals.
            return {"tool_name": "Read", "session_id": "selftest-bigread",
                    "tool_input": dict({"file_path": str(path)}, **extra)}

        import hooklib as _hooklib_bigread
        _hooklib_bigread.session_has_factory_activity = lambda session_id, event=None: True
        try:
            case("big read: a 40KB file read whole is blocked",
                 bool(_blocked(logs_check, read_ev(big), cfg)), True)
            case("big read: the message offers offset/limit",
                 "offset" in (_blocked(logs_check, read_ev(big), cfg) or ""), True)
            case("big read: the same file by range passes",
                 _blocked(logs_check, read_ev(big, offset=1, limit=50), cfg), None)
            case("big read: a small file passes",
                 _blocked(logs_check, read_ev(small), cfg), None)
            case("big read: a template is read whole on purpose",
                 _blocked(logs_check, read_ev(tpl), cfg), None)
            case("big read: a path that does not exist is not the guard's business",
                 _blocked(logs_check, read_ev(Path(_td) / "nope.txt"), cfg), None)
            case("big read: the limit can be turned off",
                 _blocked(logs_check, read_ev(big), {"read": {"max_bytes": 0}}), None)
        finally:
            del _hooklib_bigread.session_has_factory_activity

        # The case store: with one declared there is exactly one right place for a case.
        import os as _os
        store_root = Path(_td)
        (store_root / "qa-factory").mkdir(exist_ok=True)
        (store_root / "qa-factory" / "config.json").write_text("{}", encoding="utf-8")
        (store_root / "docs" / "test-cases" / "checkout").mkdir(parents=True, exist_ok=True)
        store_cfg = {"cases_root": "docs/test-cases"}
        saved_env = _os.environ.get("CLAUDE_PROJECT_DIR")
        import hooklib as _hooklib
        saved_cache = _hooklib._PROJECT_ROOT_CACHE
        # Pin it, cache and env var both: clearing the cache alone asked cwd again, and from a
        # cwd inside a real project the case store, the manifest and the owner cases all ran
        # against that project's stories (14 mismatches, macOS 0.7.11).
        _hooklib.pin_project_root(store_root)

        def write_ev(path):
            return {"tool_name": "Write", "tool_input": {"file_path": str(path)}}

        try:
            case("case store: a case written into the declared store passes",
                 _blocked(case_store_check,
                          write_ev(store_root / "docs" / "test-cases" / "checkout" / "TC-001.md"),
                          store_cfg), None)
            case("case store: the same case in the factory's own tree is blocked",
                 bool(_blocked(case_store_check,
                               write_ev(store_root / "qa-factory" / "artifacts" / "QA-1" / "work"
                                        / "test-cases" / "checkout" / "TC-001.md"), store_cfg)), True)
            case("case store: the message names the store",
                 "docs/test-cases" in (_blocked(case_store_check,
                                                write_ev(store_root / "elsewhere" / "TC-001.md"),
                                                store_cfg) or ""), True)
            case("case store: a file that is not a case is not its business",
                 _blocked(case_store_check, write_ev(store_root / "elsewhere" / "notes.md"),
                          store_cfg), None)
            case("case store: with no store declared nothing is blocked",
                 _blocked(case_store_check, write_ev(store_root / "elsewhere" / "TC-001.md"),
                          {"cases_root": ""}), None)

            # The owner check: a repair from outside an open dispatch goes back to the role.
            art = store_root / "qa-factory" / "artifacts" / "QA-1"
            (art / "work").mkdir(parents=True, exist_ok=True)
            manifest = art / "work" / "automation-manifest.json"
            report = art / "work" / "run-report.json"
            pipeline = art / "pipeline.json"

            import json as _json

            def set_stages(**status):
                pipeline.write_text(_json.dumps({"task": "QA-1", "stages":
                                   {k: {"status": v} for k, v in status.items()}}), encoding="utf-8")

            set_stages(S5="done", S6="done")
            case("owner: a role-owned artifact with no dispatch open is blocked",
                 bool(_blocked(owner_check, write_ev(manifest), {})), True)
            case("owner: the message names the owner role",
                 "qa-automator" in (_blocked(owner_check, write_ev(manifest), {}) or ""), True)
            case("owner: the way back names the rework operation, not SendMessage",
                 "controller.py --operation rework" in (_blocked(owner_check, write_ev(report), {}) or ""),
                 True)
            case("owner: it does not tell the orchestrator to SendMessage first",
                 "Send it back instead: `SendMessage`" in (_blocked(owner_check, write_ev(report), {}) or ""),
                 False)
            set_stages(S5="running", S6="pending")
            case("owner: a running stage means a dispatch is writing its own artifact",
                 _blocked(owner_check, write_ev(manifest), {}), None)
            set_stages(S5="done", S6="done")
            case("owner: a subagent transcript is honoured with no controller.json",
                 _blocked(owner_check, dict(write_ev(manifest),
                                            transcript_path="/x/session/subagents/agent-1.jsonl"), {}), None)
            case("owner: an artifact no role owns is not its business",
                 _blocked(owner_check, write_ev(art / "work" / "notes.md"), {}), None)
            case("owner: a path outside a story folder is not its business",
                 _blocked(owner_check, write_ev(store_root / "run-report.json"), {}), None)

            # the 0.7.5 regression. An accepted S5 (`pipeline.json` stage status stays
            # "done") with `state/controller.json` recording a fresh REWORK dispatch of
            # its owning role as `running` — the exact shape of `S4-qa-case-designer-3`, only
            # here on S5/qa-automator so it reuses the fixture above.
            controller_path = art / "state" / "controller.json"
            controller_path.parent.mkdir(parents=True, exist_ok=True)

            def set_controller(dispatches=None, stages=None):
                controller_path.write_text(_json.dumps(
                    {"dispatches": dispatches or {}, "stages": stages or {}}), encoding="utf-8")

            set_controller(dispatches={"S5-qa-automator-2": {"role": "qa-automator", "status": "running"}})
            case("owner: a running rework dispatch in controller.json passes, "
                 "even though the stage itself still reads done",
                 _blocked(owner_check, write_ev(manifest), {}), None)
            set_controller(dispatches={"S5-qa-automator-2": {"role": "qa-automator", "status": "accepted"}})
            case("owner: an accepted (not running) dispatch is still a repair from outside",
                 bool(_blocked(owner_check, write_ev(manifest), {})), True)
            set_controller(
                dispatches={"S5-qa-automator-2": {"role": "qa-automator", "status": "running"}})
            case("owner: controller.json is trusted over pipeline.json when both exist",
                 _blocked(owner_check, write_ev(manifest), {}), None)
            set_controller(
                stages={"S5": {"status": "done", "rework": True, "active_dispatch_id": "d1"}},
                dispatches={"d1": {"role": "qa-automator", "status": "accepted"}})
            case("owner: the legacy rework sub-state also passes for its active role",
                 _blocked(owner_check, write_ev(manifest), {}), None)
            set_controller(dispatches={})
            case("owner: the host's own agent_type passes even with no open dispatch",
                 _blocked(owner_check, dict(write_ev(manifest), agent_type="qa-automator"), {}), None)
            case("owner: a mismatched agent_type is not enough on its own",
                 bool(_blocked(owner_check, dict(write_ev(manifest), agent_type="qa-scout"), {})), True)
            controller_path.unlink()

            # the read-size limit and the turn counter act only inside real factory
            # work. `big` (40 KB) is the same fixture the plain big-read tests above use.
            scope_art = store_root / "qa-factory" / "artifacts" / "QA-SCOPE"
            (scope_art / "state").mkdir(parents=True, exist_ok=True)

            def set_scope_dispatch(status):
                (scope_art / "state" / "controller.json").write_text(
                    _json.dumps({"dispatches": {"d1": {"role": "qa-scout", "status": status}}}),
                    encoding="utf-8")

            _hooklib.session_has_factory_activity = lambda session_id, event: False
            try:
                case("scope: no activity, no agent fields, no open dispatch - "
                     "a big read is not blocked",
                     _blocked(logs_check, read_ev(big), cfg), None)
                case("scope: out of scope, the turn counter is never charged either",
                     bool(_noticed(budget_notice, dict(read_ev(big), session_id="s-scope"),
                                   {"turns": {"soft": 1, "repeat": 1}})), False)
                case("scope: the host's own agent_type puts a read back in scope",
                     bool(_blocked(logs_check, dict(read_ev(big), agent_type="qa-scout"), cfg)), True)
                set_scope_dispatch("running")
                case("scope: an open dispatch anywhere in the project puts a read back in scope",
                     bool(_blocked(logs_check, read_ev(big), cfg)), True)
                set_scope_dispatch("accepted")
                case("scope: a closed dispatch does not put it back in scope",
                     _blocked(logs_check, read_ev(big), cfg), None)
            finally:
                del _hooklib.session_has_factory_activity

            _hooklib.session_has_factory_activity = lambda session_id, event: True
            try:
                case("scope: recorded session activity puts the read limit back in scope",
                     bool(_blocked(logs_check, dict(read_ev(big), session_id="s-scope"), cfg)), True)
            finally:
                del _hooklib.session_has_factory_activity

            case("scope: with session_has_factory_activity missing (hooklib without it "
                 "yet), narrowing is off and today's behavior is unchanged",
                 bool(_blocked(logs_check, read_ev(big), cfg)), True)

            # The turn notice counts ONE reader. On TP1-15045 a session-wide counter
            # told a role on its first minute "930 tool calls, hand back" (43 interruptions
            # in 16 dispatches). Same session below: the orchestrator, then two roles.
            tight = {"turns": {"soft": 5, "repeat": 5}}
            orch_call = {"tool_name": "Bash", "session_id": "s-budget",
                         "tool_input": {"command": "ls"}}
            role_call = dict(orch_call, agent_id="a301712c46df18269",
                             agent_type="qa-factory:qa-automator")
            _hooklib.session_has_factory_activity = lambda session_id, event: True
            try:
                for _ in range(4):
                    _noticed(budget_notice, orch_call, tight)
                case("budget: a role's first calls are its own, whatever the session has spent",
                     [_noticed(budget_notice, role_call, tight) for _ in range(4)], [None] * 4)
                role_notice = _noticed(budget_notice, role_call, tight) or ""
                case("budget: a role is told about its agent's calls, in the role's words only",
                     ("this agent has made 5" in role_notice, "hand back" in role_notice,
                      "stage_done" in role_notice), (True, True, False))
                orch_notice = _noticed(budget_notice, orch_call, tight) or ""
                case("budget: the orchestrator is told about its window, role calls not counted in",
                     ("this window has made 5" in orch_notice, "hand back" in orch_notice),
                     (True, False))
                case("budget: the next dispatch of the same session starts from nothing",
                     _noticed(budget_notice, dict(role_call, agent_id="a3bb0091b2c125ccd"), tight), None)
            finally:
                del _hooklib.session_has_factory_activity

            # The manifest is merged into, never replaced: a Write over held entries is the
            # exact shape of the loss on TP2-2104.
            case("manifest: a Write over an absent manifest passes (the first window)",
                 _blocked(manifest_write_check, write_ev(manifest), {}), None)
            manifest.write_text(_json.dumps({"tests": [], "unresolved": []}), encoding="utf-8")
            case("manifest: a Write over an empty manifest passes",
                 _blocked(manifest_write_check, write_ev(manifest), {}), None)
            manifest.write_text(_json.dumps({"tests": [{"case": "TC-001"}, {"case": "TC-002"}]}),
                                encoding="utf-8")
            case("manifest: a Write over held entries is blocked",
                 bool(_blocked(manifest_write_check, write_ev(manifest), {})), True)
            case("manifest: the message names the cases at risk",
                 "TC-001, TC-002" in (_blocked(manifest_write_check, write_ev(manifest), {}) or ""),
                 True)
            case("manifest: and names the merge script",
                 "manifest_put.py" in (_blocked(manifest_write_check, write_ev(manifest), {}) or ""),
                 True)
            case("manifest: an Edit of the same file is not a replacement",
                 _blocked(manifest_write_check,
                          {"tool_name": "Edit", "tool_input": {"file_path": str(manifest)}}, {}), None)

            pipeline.unlink()
            case("owner: no pipeline.json means no story to protect",
                 _blocked(owner_check, write_ev(manifest), {}), None)
        finally:
            if saved_env is None:
                _os.environ.pop("CLAUDE_PROJECT_DIR", None)
            else:
                _os.environ["CLAUDE_PROJECT_DIR"] = saved_env
            _hooklib._PROJECT_ROOT_CACHE = saved_cache

    # External writes: the rule was absolute in prose and enforced by nothing until 0.3.0.
    # What must stay free is READING - the scout grounds a story on `list`/`view`/`search`.
    def bash(command):
        return {"tool_name": "Bash", "tool_input": {"command": command}}

    for command, why in [
        ("glab issue create --title x", "creating an issue"),
        ("gh issue comment 12 --body hi", "commenting on an issue"),
        ("jira issue move QA-1 Done", "transitioning a ticket"),
        ("az boards work-item update --id 5 --state Closed", "updating a work item"),
        ("glab api projects/1/issues -X POST -f title=x", "a POST through the api verb"),
    ]:
        case(f"writes: {why} is blocked", bool(_blocked(writes_check, bash(command), cfg)), True)

    for command, why in [
        ("glab mr list --search TP1-1", "the scout searching for an MR"),
        ("gh pr list --search QA-1", "the scout searching for a PR"),
        ("glab issue list --label bug", "listing issues"),
        ("glab issue view 12", "reading one issue"),
        ("glab mr create --fill", "the delivery path, owned by the stage guard"),
        ("python scripts/external_writes.py --task QA-1", "the executor that IS allowed to write"),
        ("python scripts/ticket_adapter.py get QA-1", "the one sanctioned ticket read"),
        ("git commit -m x", "an ordinary git command"),
    ]:
        case(f"writes: {why} passes", _blocked(writes_check, bash(command), cfg), None)

    for command, why in [
        ("git config --global safe.directory C:/repo", "the exact call a role made on 2520"),
        ("git config user.email qa@example.com", "a local write is still the person's setting"),
        ("git config --system core.autocrlf true", "--system is machine-wide"),
        ("cd /repo && git config --global core.longpaths true", "chained after another command"),
        ("git -C ../app config --global user.name x", "reached through -C"),
    ]:
        case(f"git config: {why} is blocked", bool(_blocked(git_config_check, bash(command), cfg)), True)

    for command, why in [
        ("git config --get remote.origin.url", "reading one value"),
        ("git config --list", "reading the whole configuration"),
        ("git config --get-regexp ^remote", "reading by pattern"),
        ("git status", "an ordinary git command"),
        ("git log --format=%H", "an ordinary git command with flags"),
    ]:
        case(f"git config: {why} passes", _blocked(git_config_check, bash(command), cfg), None)

    # Until 0.7.18 this was a deliberate over-block: the guard did not parse quoting, so a
    # quoted mention was refused too. The heredoc incident of 2026-09-23 showed what that
    # costs — a role refused for TEXT goes around the guard instead of past it — so a command
    # that only prints the words is now let through, while every spelling that RUNS them
    # (including `bash -c "..."`) is still refused; see command_text_parts.
    case("git config: printing the words is not changing the configuration",
         _blocked(git_config_check, bash("echo 'do not run git config --global x y'"), cfg), None)
    case("git config: the same words inside `bash -c` are a call",
         bool(_blocked(git_config_check, bash('bash -c "git config --global x y"'), cfg)), True)

    # A command the PROJECT declared as a write channel is blocked by that fact alone: the
    # factory names no tracker CLI, so whatever config.json put there writes to someone else.
    declared_cfg = {"external_writes": {"commands": {"bugs": "dmtools jira create {file}"}}}
    case("writes: a project-declared write command is blocked",
         bool(_blocked(writes_check, bash("dmtools jira create bug.json"), declared_cfg)), True)
    case("writes: mentioning sanctioned executor cannot exempt a chained tracker write",
         bool(_blocked(writes_check, bash("echo external_writes.py; jira issue create"), declared_cfg)), True)

    # The stage-guard bridge (rules 3/4 on the Bash side). The rules themselves are proven by
    # stage_guard.py --selftest; what is proven here is the wiring: an ordinary command never
    # reaches the stage model, and a delivery-shaped one is not silently ignored.
    ordinary = {"tool_name": "Bash", "tool_input": {"command": "git status --porcelain"}}
    case("stage: an ordinary command is not stage-checked", _blocked(stage_check, ordinary, cfg), None)
    import stage_guard
    case("stage: a test-code commit is stage-shaped",
         stage_guard.needs_stage_guard("git commit -m x tests/test_a.py"), True)
    case("stage: an MR command is stage-shaped", stage_guard.needs_stage_guard("glab mr create --fill"), True)
    case("stage: git status is not", stage_guard.needs_stage_guard("git status --porcelain"), False)

    # the second fail-closed refusal in a row is a diagnosis. Run against a synthetic
    # project so the counter has somewhere to live; the counter must never invent one.
    import tempfile
    import hooklib as _hl
    with tempfile.TemporaryDirectory(prefix="qa-factory-escalation-") as td, \
            tempfile.TemporaryDirectory(prefix="qa-factory-bare-") as bare_td, \
            _hl.selftest_root_restored():
        proj = Path(td)
        (proj / "qa-factory" / "state").mkdir(parents=True)
        (proj / "qa-factory" / "config.json").write_text('{"schema_version": 1}', encoding="utf-8")
        # The counter and the backlog note below are written to the root, so pin it: run from
        # a cwd inside a real project, these cases used to file the factory's own findings in
        # that project's factory-backlog.md.
        _hl.pin_project_root(proj)
        bare = Path(bare_td)  # a repository with no factory in it, and none of ours above it
        ev = {"session_id": "s-esc", "cwd": str(proj)}
        case("escalation: the first refusal is an ordinary refusal",
             escalate("PT-patch-unchecked", ev, witness="w", call_key="Edit:a.py"), "")
        case("escalation: the same call again is still one call",
             escalate("PT-patch-unchecked", ev, witness="w", call_key="Edit:a.py"), "")
        second = escalate("PT-patch-unchecked", ev, witness="w", call_key="Edit:b.py")
        case("escalation: the second, on a different call, escalates", bool(second), True)
        case("escalation: and says who owns the defect", "Owner: the FACTORY" in second, True)
        case("escalation: and names the doctor", "/qa-factory:qa-doctor" in second, True)
        case("escalation: and the finding is written by code",
             "guard-escalation" in (proj / "qa-factory" / "factory-backlog.md").read_text(
                 encoding="utf-8"), True)
        case("escalation: a different refusal starts its own count",
             escalate("PT-unparsed-event", ev, witness="w", call_key="pid-1"), "")
        # This case is about what the counter does with a root that has no marker, not about
        # how that root was found, so the bare directory is pinned outright. Clearing the
        # cache instead would hand the case back to the walk from cwd — and from a cwd inside
        # a real project that walk answers with the project, which does have a config.json.
        with _hl.selftest_root_restored():
            _hl.pin_project_root(bare)
            case("escalation: a project with no config.json is never given a state tree",
                 (_escalation_count("PT-unparsed-event", {"cwd": str(bare)}, "pid-1"),
                  (bare / "qa-factory").exists()), (0, False))
            case("escalation: and a counter that cannot be written never raises",
                 escalate("PT-unparsed-event", {"cwd": str(bare)}, witness="w"), "")
        case("escalation: both fail-closed messages warn before they escalate",
             "stops with a diagnosis" in REPEAT_WARNING, True)

    if failures:
        print(f"PRE-TOOL GUARD: VIOLATIONS ({len(failures)})")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("PRE-TOOL GUARD: no violations (write marker, prefilter, app boundary, secrets, quiet runs, raw logs, external writes, case store, manifest merge, artifact owner)")
    return 0


def main() -> None:
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    event = read_event()
    if event is None:
        block("PRE-TOOL GUARD: hook event could not be parsed (broken stdin) - fail-closed, call blocked."
              + REPEAT_WARNING + escalate("PT-unparsed-event", None,
                                          witness="read_event() returned None: stdin was not a "
                                                  "JSON hook event this host's adapter recognizes"))
    try:
        try:
            _guard(event)
        except WalkerError as exc:
            walker_refusal(event, exc)
    except SystemExit as exc:
        _flush_notice(event, exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1))
        raise
    except BaseException:
        _flush_notice(event, 1)
        raise
    _flush_notice(event, 0)


def walker_refusal(event: dict, exc: Exception) -> None:
    """The command walker failed (CX1-20 N-1): BLOCK with the door, never exit 1 - a PreToolUse hook that exits 1 is a
    non-blocking error, the call goes ahead and every check after the crash is skipped. The fault is the guard's, so
    the refusal is counted like the unparsed event: the second in a row on a different call records a finding."""
    import hashlib
    tool_name = str((event or {}).get("tool_name") or "")
    line = argv_text(((event or {}).get("tool_input") or {}).get("command"))
    block("PRE-TOOL GUARD: " + WALKER_DOOR.format(reason=exc) + REPEAT_WARNING
          + escalate("PT-walker-error", event, witness=f"{tool_name}: the command walker raised {exc}",
                     call_key=f"{tool_name}:{hashlib.sha1(line.encode('utf-8', 'replace')).hexdigest()[:16]}"))


def _guard(event: dict) -> None:
    """main()'s checks on a parsed event, in their order; every way out is a sys.exit (0 or a block)."""
    cfg = load_config(event)
    from host_probe import observe as probe_observe
    if probe_observe(project_root(event), event):
        block("QA FACTORY DOCTOR: expected harmless deny probe; host guard is invoked.")
    from worker_lifecycle import guard as worker_guard
    worker_guard(event)
    size_check(event, cfg)   # before every reader of a command text, role_policy's read rule included
    from host_adapter import role_policy
    role_policy(event, cfg)

    # Python-only prefilter (replaces the old shell layer): a Bash/PowerShell call that
    # cannot possibly write, run a test directly or touch a protected path is let through
    # BEFORE any config-derived regex work. Write|Edit|NotebookEdit always go through the
    # full guard (secrets apply to every write, config or not).
    tool_name = event.get("tool_name", "")

    # The turn budget counts first and speaks before any other rule: it is a notice about
    # what this dispatch has already spent, not a judgement about the call in hand. Every
    # tool the guard sees is counted, so the number means what it says.
    budget_notice(event, cfg)

    # Read is hooked ONLY for this one check, so it exits here without touching the app
    # boundary, the secret patterns or the stage model. Measured cost of the hook on a
    # Read: 0.37 s, against a story that spends hours — worth it for the single largest
    # token driver the pilot found.
    if tool_name == "Read":
        plugin_read_check(event, cfg)
        logs_check(event, cfg)
        sys.exit(0)

    # Grep and Glob are hooked for one rule alone: a role searching the plugin instead of
    # reading its brief. Nothing else in this guard applies to a search.
    if tool_name in ("Grep", "Glob"):
        plugin_read_check(event, cfg)
        sys.exit(0)

    if tool_name in ("Bash", "PowerShell"):
        logs_check(event, cfg)
        writes_check(event, cfg)
        human_word_check(event, cfg)
        # Before the prefilter: `git config --global x y` carries no write marker and names no
        # protected path, so needs_guard() would wave it through.
        git_config_check(event, cfg)
        command = str((event.get("tool_input") or {}).get("command") or "")
        if not needs_guard(command, cfg, event):
            # `git commit`/`glab mr create` carry no write marker and no protected path, so
            # the prefilter would let them past — the stage rules still apply to them.
            stage_check(event, cfg)
            config_write_check(event, cfg)  # LAST, as in the loop below: `python -c "open(...)"` has no marker
            stand_record_write_check(event, cfg)
            sys.exit(0)

    from host_adapter import mutation_events
    try:
        operations = mutation_events(event)
    except ValueError as exc:
        target = str((event.get("tool_input") or {}).get("file_path") or "")
        block(f"PRE-TOOL GUARD: {exc}; patch was not checked and is blocked."
              + REPEAT_WARNING + escalate("PT-patch-unchecked", event,
                                          witness=f"{tool_name} on {target or '<no path>'}: "
                                                  f"{type(exc).__name__}: {exc}",
                                          call_key=f"{tool_name}:{target}"))
    for operation in operations:
        app_guard.check(operation, cfg)
        secrets_guard.check(operation, cfg)
        runs_check(operation, cfg)
        case_store_check(operation, cfg)
        manifest_write_check(operation, cfg)
        artifact_rewrite_check(operation, cfg)
        plan_write_check(operation, cfg)
        handoff_write_check(operation, cfg)
        owner_check(operation, cfg)
        window_file_check(operation, cfg)
        stage_check(operation, cfg)
        # After every older check, so none of their refusals moves: this one refuses only a call
        # they all passed, and never turns one of theirs into a pass.
        config_write_check(operation, cfg)
        stand_record_write_check(operation, cfg)
    sys.exit(0)


if __name__ == "__main__":
    # Telemetry is observational only; never change a guard decision or add a model retry.
    from contextlib import nullcontext
    telemetry = nullcontext()
    try:
        from telemetry_capture import Span
        root = project_root()
        # `--selftest` is not a hook call. Run by hand from a cwd inside a real project it
        # would otherwise drop a hook-<pid>.jsonl into that project's state tree — the same
        # class of leak I-89 is about, visible only to whoever ran it there.
        if (root / "qa-factory/config.json").is_file() and "--selftest" not in sys.argv:
            telemetry = Span(root / "qa-factory/state/telemetry" / f"hook-{os.getpid()}.jsonl",
                             span_kind="hook", source="plugin")
    except Exception:
        pass
    with telemetry:
        main()
