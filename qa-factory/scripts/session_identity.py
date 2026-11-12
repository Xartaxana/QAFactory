"""The ONE carrier of the identity of the session a command runs in (B-410).

A command a role runs from a shell (`activity_capture.py`, `host_probe.py`, `onboard_apply.py`) is not
given the session it belongs to. Three scripts used to guess, each its own way. Now they all ask
`resolve()`, and the answer comes from the host's own words only:

  * an id a person passed (`--session`), then the id in the hook event;
  * the receipt the PreToolUse hook wrote moments before this very call (`write_receipt`, called by
    telemetry_hook.py on every tool call, whether or not the project is onboarded yet): one file per
    session and script, naming the session, the script and every directory the call can run in;
  * the host's own variables (`references/session-identity.json` names them), which must AGREE with
    the receipt. Two answers that differ are never settled by choosing one: the result is a refusal.

Before `qa-factory/config.json` exists the receipts live in the spool under the user's home
(`~/.qa-factory/spool/`), never in the project: a hook never creates `qa-factory/`. The same spool
holds the activity file of a project that is not onboarded yet (activity_capture.py).

No side effects at import; `hooklib`, `host_probe` and `event_store` are imported when needed.
Every constant of the rules (names, windows, limits) is the data file's (FR-13).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

RULES_PATH = Path(__file__).resolve().parents[1] / "references" / "session-identity.json"
SAFE_ID = re.compile(r"[A-Za-z0-9._-]{1,128}")
RECEIPT_GLOB = "pretool-*-*.json"
PRUNE_BATCH = 50                      # E15: the most one write deletes
COMMAND_KEPT = 400                    # the receipt keeps this many characters of the command
_SEGMENTS = re.compile(r"&&|\|\||[;&\r\n]")
_WORDS = re.compile(r"\"[^\"]*\"|'[^']*'|\S+")
_NOT_LITERAL = "$%`"                  # a target with one of these is not spelled out: it is not followed


def spool_root() -> Path:
    """The one spool root: receipts before config, and the activity file of an un-onboarded project.
    Under the home (USERPROFILE / HOME), never under TMPDIR: the hook process and a tool process
    can disagree about the temp folder (MSYS converts `/tmp`, a PowerShell tool does not)."""
    return Path.home() / ".qa-factory" / "spool"


def _component(value) -> bool:
    return isinstance(value, str) and bool(SAFE_ID.fullmatch(value)) and value not in (".", "..")


def _valid(data) -> bool:
    if not isinstance(data, dict):
        return False
    for key in ("receipt_scripts", "env_vars", "cd_words"):
        items = data.get(key)
        if not (isinstance(items, list) and items and all(isinstance(i, str) and i.strip() for i in items)):
            return False
    for key in ("warm_seconds", "scan_limit", "spool_prune_days"):
        number = data.get(key)
        if isinstance(number, bool) or not isinstance(number, int) or number <= 0:
            return False
    # names that become file or folder names are one safe component; pruning must never reach a warm receipt
    return (all(_component(s) for s in data["receipt_scripts"]) and _component(data.get("spool_dir"))
            and data["spool_prune_days"] * 86400 > data["warm_seconds"])


def load_rules(path=None) -> dict | None:
    """The rules, or None when the file is absent, unreadable or invalid (the caller says so, owner: factory)."""
    try:
        data = json.loads(Path(path or RULES_PATH).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if _valid(data) else None


def _norm(path) -> str:
    return os.path.normcase(os.path.realpath(str(path)))


# --- the writer: what a PreToolUse hook leaves behind --------------------------------------------

def _absolute(path: str, base: str) -> str:
    """`path` made absolute against `base`, normalised; '' when that cannot be done."""
    joined = os.path.join(base, path) if base else path
    return os.path.normpath(joined) if joined and os.path.isabs(joined) else ""


def _cd_target(words: list) -> str:
    """The directory a `cd`-like command names, as spelled; '' when there is none or it is not literal
    (`-`, `$DIR`, `%X%`, a backtick): the safe direction is to stop, not to guess."""
    for raw in words:
        word = raw[1:-1] if len(raw) > 1 and raw[0] == raw[-1] and raw[0] in "\"'" else raw
        if word.lower() == "/d" or (word.startswith("-") and word != "-"):
            continue                                  # an option, or cmd's drive switch
        if word in ("", "-") or any(c in word for c in _NOT_LITERAL):
            return ""
        if word == "~" or word.startswith(("~/", "~\\")):
            word = str(Path.home()) + word[1:]
        drive = re.fullmatch(r"/([A-Za-z])(/.*)?", word)
        if drive and os.name == "nt":                 # MSYS spelling of a drive
            word = f"{drive[1].upper()}:{drive[2] or '/'}"
        return word
    return ""


def _cwds(event: dict, command: str, script: str, rules: dict) -> list:
    """Every directory `script` can run in, in order, without repeats: the event's cwd, the Codex
    `workdir`, then the target of each `cd`, `Set-Location` or `pushd` that comes before the script's
    name in the command (each resolved against the directory the walk has reached)."""
    found: list = []

    def add(path: str) -> None:
        if path and path not in found:
            found.append(path)

    start = _absolute(str(event.get("cwd") or ""), "")
    add(start)
    tool_input = event.get("tool_input")
    workdir = str(tool_input.get("workdir") or "") if isinstance(tool_input, dict) else ""
    running = _absolute(workdir, start) if workdir else start
    add(running)
    cd_words = {w.lower() for w in rules["cd_words"]}
    for segment in _SEGMENTS.split(command[:command.index(script)]):
        words = _WORDS.findall(segment.strip())
        if not words or words[0].lower() not in cd_words:
            continue
        literal = _cd_target(words[1:])
        target = _absolute(literal, running) if literal else ""
        if not target:
            break
        add(target)
        running = target
    return found


def _prune(folder: Path, rules: dict, now: float) -> None:
    """Delete receipts of the new shape older than `spool_prune_days` (mtime), at most PRUNE_BATCH a call.
    Only `pretool-*-*.json`: the other receipts of `host-receipts/` are not this writer's."""
    limit, removed = rules["spool_prune_days"] * 86400, 0
    for path in folder.glob(RECEIPT_GLOB):
        if removed >= PRUNE_BATCH:
            break
        try:
            if now - path.stat().st_mtime > limit:
                path.unlink()
                removed += 1
        except OSError:
            continue


def write_receipt(root, event, rules=None, now=None) -> None:
    """Called on every PreToolUse. Writes one receipt per named script that the command mentions:
    `pretool-<sha16 of the session>-<script stem>.json`, in `<root>/qa-factory/state/host-receipts/`
    once `config.json` exists and in the spool before that. Writes nothing when the session, the
    command, a named script or the rules are missing. Every failure is swallowed: a hook never
    changes the outcome of the tool call it rides on."""
    try:
        rules = rules or load_rules()
        session = str((event or {}).get("session_id") or "").strip()
        if not rules or not session:
            return
        from host_probe import probe_command           # the command is read the way the probe reads it (FR-17)
        command = probe_command(event).strip()
        names = [n for n in rules["receipt_scripts"] if n in command]
        if not names:
            return
        now = time.time() if now is None else now
        onboarded = (Path(root) / "qa-factory" / "config.json").is_file()
        folder = (Path(root) / "qa-factory" / "state" / "host-receipts" if onboarded
                  else spool_root() / rules["spool_dir"])
        _prune(folder, rules, now)
        from event_store import atomic_json
        key = hashlib.sha256(session.encode("utf-8")).hexdigest()[:16]
        for name in names:
            atomic_json(folder / f"pretool-{key}-{Path(name).stem}.json", {
                "session_id": session, "script": name, "cwds": _cwds(event, command, name, rules),
                "command": command[:COMMAND_KEPT], "observed_at": datetime.fromtimestamp(now, timezone.utc).isoformat()})
    except Exception:
        pass


# --- the reader: one function for every script that needs its own session ---------------------------

def _result(session_id, source, problem, checked, conflict=None) -> dict:
    return {"session_id": session_id, "source": source, "problem": problem, "checked": checked, "conflict": conflict}


def _chosen(value: str, source: str, checked: list) -> dict:
    """An id that decided, or `unsafe` when it could become a path outside its folder."""
    if _component(value):
        return _result(value, source, "none", checked)
    return _result("", source, "unsafe", checked)


def _receipt_folders(event: dict, cwd: str, rules: dict) -> list:
    """The folders the receipts of this project can be in: its state folder once it is onboarded, and the spool."""
    from hooklib import project_root
    folders = []
    try:
        root = project_root(dict(event, cwd=event.get("cwd") or cwd))
        if (root / "qa-factory" / "config.json").is_file():
            folders.append(root / "qa-factory" / "state" / "host-receipts")
    except Exception:
        pass
    try:
        folders.append(spool_root() / rules["spool_dir"])
    except RuntimeError:                     # no home directory (a host stripped USERPROFILE / HOME): the role is not stopped
        return folders, False
    return folders, True


def _counts(doc, script: str, here: str) -> bool:
    """A receipt counts only when it can prove its script and a directory equal to the reader's."""
    return (isinstance(doc, dict) and doc.get("script") == script
            and isinstance(doc.get("session_id"), str) and bool(doc["session_id"].strip())
            and isinstance(doc.get("cwds"), list)
            and any(isinstance(c, str) and c and _norm(c) == here for c in doc["cwds"]))


def _receipt_answer(folders: list, script: str, cwd: str, rules: dict, now: float) -> tuple:
    """('unique', id) | ('ambiguous', '') | ('none', ''): newest first by mtime, at most `scan_limit`
    files read; a file counts when it is warm, names this script and has this directory. Uniqueness is
    never claimed over files that were not read: a warm file left past the limit makes it ambiguous."""
    files = []
    for folder in folders:
        try:
            for path in folder.glob(RECEIPT_GLOB):
                try:
                    files.append((path.stat().st_mtime, path))
                except OSError:
                    continue
        except OSError:
            continue
    here, ids, read = _norm(cwd), set(), 0
    for mtime, path in sorted(files, key=lambda item: item[0], reverse=True):
        if now - mtime > rules["warm_seconds"]:
            break                                       # newest first: nothing older is warm either
        if read >= rules["scan_limit"]:
            return "ambiguous", ""
        read += 1
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if _counts(doc, script, here):
            ids.add(doc["session_id"])
    return ("ambiguous", "") if len(ids) > 1 else (("unique", next(iter(ids))) if ids else ("none", ""))


def resolve(event=None, explicit="", script=None, cwd=None, now=None, rules=None, env=None) -> dict:
    """{"session_id", "source", "problem", "checked", "conflict"} for the session this call runs in.

    source: explicit | event | receipt | env:<NAME> | none. problem: none | missing | ambiguous | unsafe |
    rules_unreadable. `session_id` is '' unless the problem is none. The order: an explicit id; the
    event's `session_id`; then the receipt R and the host's variables E, which must AGREE:
    R unique and (E empty or R in E) -> R; R unique and R not in E -> ambiguous (`conflict` names the
    variables); R none and one id in E -> that id; R none and two or more -> ambiguous; R ambiguous ->
    ambiguous; R none and E empty -> missing. A refusal is never settled by choosing a side."""
    event = event if isinstance(event, dict) else {}
    explicit = str(explicit or "")
    if explicit:
        return _chosen(explicit, "explicit", ["--session given"])
    given = str(event.get("session_id") or "")
    if given:
        return _chosen(given, "event", ["the hook event's session_id"])
    checked = ["--session not given", "the hook event carries no session_id"]
    rules = rules if rules is not None else load_rules()
    if rules is None:
        return _result("", "none", "rules_unreadable", checked)
    now, cwd = (time.time() if now is None else now), str(cwd or os.getcwd())
    env = os.environ if env is None else env
    folders, has_home = _receipt_folders(event, cwd, rules)
    state, receipt = _receipt_answer(folders, script, cwd, rules, now) if script else ("none", "")
    checked.append(f"hook receipts of {script} for {cwd}, in " + (" and ".join(str(f) for f in folders) or "no folder"))
    if not has_home:
        checked.append("no home directory: the spool was not looked at")
    held = {name: str(env.get(name) or "").strip() for name in rules["env_vars"]}
    held = {name: value for name, value in held.items() if value}
    checked.append("the variables " + ", ".join(rules["env_vars"]) + (f" (set: {', '.join(held)})" if held else " (none set)"))
    ids = {}
    for name, value in held.items():
        ids.setdefault(value, name)
    conflict = [f"{name}={value}" for name, value in held.items()]
    if state == "ambiguous":
        return _result("", "none", "ambiguous", checked)
    if state == "unique":
        if not ids or receipt in ids:
            return _chosen(receipt, "receipt", checked)
        return _result("", "none", "ambiguous", checked, conflict)
    if len(ids) == 1:
        value, name = next(iter(ids.items()))
        return _chosen(value, f"env:{name}", checked)
    if ids:
        return _result("", "none", "ambiguous", checked, conflict)
    return _result("", "none", "missing", checked)


def refusal(result: dict, script: str) -> str:
    """One paragraph: what was looked for and where, why there is no answer, and the move (FR-1, FR-2).
    No placeholder is offered; `--session` only with an id a person gives you."""
    problem, looked = result.get("problem"), "; ".join(result.get("checked") or [])
    head = f"Could not tell which session {script} runs in. Looked at: {looked}."
    if problem == "missing":
        from hooklib import _nearest_project
        here = Path(os.getcwd())
        # forward slashes and quotes: a backslash path is eaten by Git Bash, a path with a space breaks PowerShell
        return (f"{head} There is no hook receipt for this call and no session id in the environment. Run "
                f"`cd \"{(_nearest_project(here) or here).as_posix()}\"` as its own shell call, then run the command with no `cd` in front of it. "
                "If it still fails, the factory's hooks are not active in this session: run /qa-factory:qa-doctor (owner: factory).")
    if problem == "ambiguous" and result.get("conflict") is not None:
        names = ", ".join(c.split("=", 1)[0] for c in result["conflict"])
        return (f"{head} This call's hook receipt and {names} name different sessions, or two variables disagree. "
                "The environment carries another session's id, which happens to a session started from inside another "
                "session's shell. Run it again as its own shell call; if it repeats, start the work from a fresh terminal.")
    if problem == "ambiguous":
        rules = load_rules() or {}
        return (f"{head} Two or more sessions ran {script} in {os.getcwd()} within {rules.get('warm_seconds', 30)} s. "
                "Run it again in a few seconds as its own shell call.")
    if problem == "unsafe":
        source = str(result.get("source"))
        where = ("the `--session` argument" if source == "explicit" else "the hook event" if source == "event"
                 else f"the variable {source[4:]}" if source.startswith("env:") else source)
        return (f"{head} The id from {where} cannot be used: an id is 1 to 128 characters of letters, digits, "
                "'.', '_' or '-' (not '.' or '..'), because it becomes a file name. Pass `--session` only with an id a "
                "person gives you, in that form, or leave it out so the command finds its own session.")
    return (f"{head} The rules file {RULES_PATH} is missing or invalid, so only an id from the hook event or one a person "
            "gives you can be used. The install of the factory is damaged (owner: factory): run /qa-factory:qa-doctor.")
