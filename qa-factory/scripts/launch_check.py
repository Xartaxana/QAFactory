#!/usr/bin/env python3
"""One launch check: does a profile's own test command START here, and if it did not, why.

TP1-13797, the automator's S5 marathon: `pytest` resolved to the system interpreter's
`Scripts\\pytest`, which has none of the project's plugins, and the run died with
`pytest: error: unrecognized arguments: --reruns --ui-headless`. The gate had collected with the
same bare command, said only the last line of its output (`rootdir: C:\\...`), and the role then
edited `config.json` on a person's word. Three places knew a piece of this and none knew the
cause. This module is the one place that names it (B-193, t-110 R-A1):

    classify(exit_code, lines, totals, *, argv=None)  what stopped a run that ran nothing
    probe(profile, project_root, *, ...)              collect with the profile's own command
    door(cause, audience="role")                      the sentence an audience reads for a cause
    runner_row(argv)                                  the runner row of a command: its exit facts
    runner_identity(argv)                             which runner a command starts: form id, collect row, selection
    CLI  launch_check.py [--profile ID] [--deactivated] [--json]

The cause list, its markers, its door sentences (one per audience: role, gate, onboarding), the
collect form of each runner, the wrapper launchers, the positional placeholder names and the
folders an environment keeps its executables in are DATA (`references/launch-causes.json`,
FR-13). The only runner-shaped code is the recogniser for a `collect_forms` row: `pytest` is
recognised by `execution_request.is_pytest_command`, the one reading S5 uses. It is a reporter
(FR-47, P1): it exits 0 whenever it ran and never writes a file (FR-45). Error direction
throughout: toward `unknown` / `not_checked`, never a confident wrong cause, never `failed` for a
launcher that works, never `ok` for a command the check did not really start.

What `classify` calls a cause (the standing rule): a cause HOLDS when one of the output lines has
one of its markers and the cause's own confirmation passes. The confirmation is against the argv
the caller gives: `launcher_rejected_arguments` needs an option the output names to be in that
argv; `executable_not_found` needs the line to name the program actually run (argv[0], or the
program a known wrapper such as `poetry run` starts) as the thing that was not found. A cause
confirmed that way beats one that is not, whatever the data order says: an earlier stray line
(`bash: aws: command not found`, a script's own missing tool) never gives a confident wrong
cause. With no argv given, a cause that needs confirming cannot be confirmed and is not
returned. Data order decides only among causes that hold. When none holds, the answer is
`unknown` (with the first unconfirmed line as evidence, and a note saying why it was not
believed).
"""
import argparse
import importlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

# The data file; a module attribute so a test can point it at a broken or reordered copy.
CAUSES_PATH = Path(__file__).resolve().parents[1] / "references" / "launch-causes.json"

EVIDENCE_MAX = 200
DEFAULT_TIMEOUT_S = 120
AUDIENCES = ("role", "gate", "onboarding")
# How a cause is confirmed against the argv, by the name the data file gives it. A `requires`
# this code does not know makes the file malformed: a confirmation nobody can run would let a
# cause hold unconfirmed.
KNOWN_REQUIRES = ("program_run",)
_EXE_SUFFIXES = (".exe", ".cmd", ".bat", ".com", ".ps1")
# The exit codes run_suite and stand_health read as "nothing was executed" for a command no
# `collect_forms` row has stated a fact for (pytest: 2 interrupted, 3 internal error, 4 usage
# error, 5 nothing collected). This is the declared default for "no fact", kept here so both
# readers import one copy; a row's `not_executed_exits` replaces it for that runner.
_LEGACY_NOT_EXECUTED = (2, 3, 4, 5)
# 124 is run_suite's timeout, 127 its launch failure: neither is ever a runner's own fact.
RUNNER_OWN_EXITS = (124, 127)

# ANSI escape sequences, built from chr() (FR-29: no control byte in a package file). CSI
# (`ESC [ ... final`), OSC (`ESC ] ... BEL|ESC \`) and the two-byte forms.
_ESC = chr(27)
_BEL = chr(7)
_ANSI_RE = re.compile(
    re.escape(_ESC) + "(?:"
    + r"\[[0-?]*[ -/]*[@-~]"
    + "|" + r"\][^" + _BEL + _ESC + r"]*(?:" + _BEL + "|" + re.escape(_ESC) + r"\\)?"
    + "|" + r"[@-Z\\-_]"
    + ")")

_PLACEHOLDER_RE = re.compile(r"<[^<>]+>")
_NEGATIVE_NUMBER_RE = re.compile(r"-\d+(?:\.\d+)?")


# --- the data file ----------------------------------------------------------------------------

def load_data(path=None):
    """`(data, note)`: the cause list read and checked, or `(None, why)`.

    Malformed is not a crash and not a guess: a file this code cannot fully trust answers
    nothing, and the callers say `unknown` with the note. An empty marker string would match
    every line, so it counts as malformed, not as a cause that always fires."""
    target = Path(path) if path else Path(CAUSES_PATH)
    name = target.name
    try:
        raw = json.loads(target.read_text(encoding="utf-8-sig"))
    except OSError as exc:
        return None, f"{name} is unreadable ({type(exc).__name__}): the cause list cannot be read"
    except ValueError as exc:
        return None, f"{name} is not valid JSON ({exc}): the cause list cannot be read"
    if not isinstance(raw, dict) or not isinstance(raw.get("causes"), list) or not raw["causes"]:
        return None, f"{name} has no non-empty `causes` list"
    causes, seen = [], set()
    for index, row in enumerate(raw["causes"]):
        where = f"{name} causes[{index}]"
        if not isinstance(row, dict):
            return None, f"{where} is not an object"
        cid = row.get("id")
        if not isinstance(cid, str) or not cid.strip() or cid in seen:
            return None, f"{where} has no unique string `id`"
        seen.add(cid)
        markers = row.get("markers")
        if not isinstance(markers, list) or any(not isinstance(m, str) or not m for m in markers):
            return None, f"{where} (`{cid}`) needs `markers`: a list of non-empty strings"
        doors = row.get("doors")
        if not isinstance(doors, dict) or any(
                not isinstance(k, str) or not isinstance(v, str) for k, v in doors.items()):
            return None, (f"{where} (`{cid}`) needs `doors`: an object of audience -> sentence "
                          f"(audiences: {', '.join(AUDIENCES)})")
        requires = row.get("requires")
        if requires is not None and requires not in KNOWN_REQUIRES:
            return None, f"{where} (`{cid}`) has a `requires` this code cannot check: {requires!r}"
        patterns = row.get("named_option_patterns", [])
        compiled = []
        if not isinstance(patterns, list):
            return None, f"{where} (`{cid}`) `named_option_patterns` is not a list"
        for pattern in patterns:
            try:
                rx = re.compile(pattern)
            except (re.error, TypeError) as exc:
                return None, f"{where} (`{cid}`) has a pattern that does not compile ({exc})"
            if rx.groups < 1:
                return None, f"{where} (`{cid}`) has a pattern with no group to read the option from"
            compiled.append(rx)
        causes.append({"id": cid, "markers": list(markers), "doors": dict(doors),
                       "requires": requires, "patterns": compiled})
    out = {"causes": causes}
    for key in ("deactivated_variables", "environment_folders", "positional_placeholders"):
        items = raw.get(key, [])
        if not isinstance(items, list) or any(not isinstance(v, str) or not v for v in items):
            return None, f"{name} `{key}` must be a list of non-empty strings"
        out[key] = list(items)
    if any(not _PLACEHOLDER_RE.fullmatch(v) for v in out["positional_placeholders"]):
        return None, f"{name} `positional_placeholders` holds a token that is not a `<...>` placeholder"
    wrappers = raw.get("wrappers", [])
    if not isinstance(wrappers, list):
        return None, f"{name} `wrappers` is not a list"
    out["wrappers"] = {}
    for index, row in enumerate(wrappers):
        subs = row.get("subcommands") if isinstance(row, dict) else None
        if (not isinstance(row, dict) or not isinstance(row.get("program"), str) or not row["program"]
                or not isinstance(subs, list) or any(not isinstance(s, str) or not s for s in subs)):
            return None, f"{name} wrappers[{index}] needs `program` and a list `subcommands`"
        out["wrappers"][row["program"]] = list(subs)
    forms = raw.get("collect_forms", [])
    if not isinstance(forms, list):
        return None, f"{name} `collect_forms` is not a list"
    out["collect_forms"] = []
    for index, row in enumerate(forms):
        where = f"{name} collect_forms[{index}]"
        if not isinstance(row, dict) or not isinstance(row.get("tool"), str) or not row["tool"]:
            return None, f"{where} needs a string `tool`"
        append, exits = row.get("append"), row.get("ok_exits")
        if not isinstance(append, list) or any(not isinstance(a, str) or not a for a in append):
            return None, f"{where} needs `append`: a list of non-empty strings"
        if (not isinstance(exits, list) or not exits
                or any(isinstance(e, bool) or not isinstance(e, int) for e in exits)):
            return None, f"{where} needs `ok_exits`: a non-empty list of integers"
        extras, problem = _runner_fields(where, row)
        if problem:
            return None, problem  # `problem` already starts with the file name and the row
        out["collect_forms"].append({"tool": row["tool"], "append": list(append),
                                     "ok_exits": list(exits), **extras})
    out["selection_by_form"], out["selection_problems"] = _selection_rows(name, raw)
    return out, ""


def _selection_rows(name: str, raw: dict) -> tuple:
    """`(selection_by_form, problems)`: the optional `selection` of each `run_forms` row, by the row's `id`. `hooklib`'s
    own reader keeps `id, argv, diagnostics, negators` of a row and drops any other key, so this file is read here for
    the one key it does not (EP1-1, M-12). A row without `selection` states none and is not a problem. A `selection`
    of a wrong shape (not an object, a `classname` other than `file` / `file_suffix`, no `args`, `report_id` or
    `title_join`) is left out of the map and named in `problems` as `{form id: words}`."""
    run_forms = raw.get("run_forms")
    rows = run_forms.get("forms") if isinstance(run_forms, dict) else None
    found, problems = {}, {}
    for index, row in enumerate(rows if isinstance(rows, list) else []):
        if not isinstance(row, dict) or "selection" not in row or not isinstance(row.get("id"), str):
            continue
        where, sel = f"{name} run_forms.forms[{index}] (`{row['id']}`) `selection`", row["selection"]
        if not isinstance(sel, dict):
            problems[row["id"]] = f"{where} is not an object"
        elif sel.get("classname") not in ("file", "file_suffix"):
            problems[row["id"]] = f"{where} needs `classname` `file` or `file_suffix`"
        elif not isinstance(sel.get("args"), list) or not sel["args"] \
                or any(not isinstance(a, str) or not a for a in sel["args"]):
            problems[row["id"]] = f"{where} needs `args`: a non-empty list of non-empty strings"
        elif not isinstance(sel.get("report_id"), str) or not sel["report_id"]:
            problems[row["id"]] = f"{where} needs `report_id`: a non-empty string"
        elif not isinstance(sel.get("title_join"), str) or not sel["title_join"]:
            problems[row["id"]] = f"{where} needs `title_join`: a non-empty string"
        elif "escape_file" in sel and not isinstance(sel["escape_file"], bool):
            problems[row["id"]] = f"{where} `escape_file` must be true or false"
        else:
            found[row["id"]] = dict(sel)
    return found, problems


def _runner_fields(where: str, row: dict) -> tuple:
    """`(extras, problem)`: the two optional runner facts of a `collect_forms` row, carried only
    when the raw row has them (a row without one states no such fact; an empty list is a fact).
    The runner's own codes, 124 (timeout) and 127 (launch failure), are never a runner fact."""
    extras = {}
    if "not_executed_exits" in row:
        exits = row["not_executed_exits"]
        if not isinstance(exits, list) or any(isinstance(e, bool) or not isinstance(e, int) for e in exits):
            return None, f"{where} `not_executed_exits` must be a list of integers"
        if any(e in RUNNER_OWN_EXITS for e in exits):
            return None, (f"{where} `not_executed_exits` lists {sorted(set(exits) & set(RUNNER_OWN_EXITS))}: "
                          "124 and 127 are the runner's own codes (timeout, launch failure), not a runner fact")
        extras["not_executed_exits"] = list(exits)
    if "node_ids" in row:
        if not isinstance(row["node_ids"], str) or not row["node_ids"].strip():
            return None, f"{where} `node_ids` must be a checker name (a non-empty string)"
        extras["node_ids"] = row["node_ids"]
    problem = (_partial_collect_fields(where, row, extras)
               or _regex_keys(where, row, extras, _TIMEOUT_REGEXES))
    return (None, problem) if problem else (extras, "")


# The words of a project-timeout outcome, ONE home for the writers (run_suite, judge_run) and the readers (s5_precheck): a
# `timeout` block of the run summary has `how` in PROJECT_TIMEOUT_HOWS when the PROJECT's limit ended the test (`run_killed`
# is run_suite's own), and an instance such a block names carries `reason_code` PROJECT_TIMEOUT_CODE (RH2-9, AR-22).
PROJECT_TIMEOUT_HOWS = ("hard_kill", "failed_in_report")
PROJECT_TIMEOUT_CODE = "project_timeout"

# The runner's own per-test timeout lines (RH2-9, AR-1), optional keys of the same row and the group each must name.
# A row that states none of them states no timeout fact about its runner, and the reader (run_suite) applies nothing.
_TIMEOUT_REGEXES = {"timeout_kill_line": (), "timeout_failure_message": ("limit",), "timeout_header_line": ("limit",)}


def _regex_keys(where: str, row: dict, extras: dict, table: dict) -> str:
    """Validate the optional regex keys of `table` (`{key: groups it must name}`) of a `collect_forms` row and copy the
    ones the row states into `extras`; the problem text (it starts with `where`) or "". A key the row does not state
    stays out: no fact, never a default pattern."""
    for key, groups in table.items():
        if key not in row:
            continue
        pattern = row[key]
        if not isinstance(pattern, str) or not pattern:
            return f"{where} `{key}` must be a regular expression (a non-empty string)"
        try:
            names = re.compile(pattern, re.M).groupindex
        except re.error as exc:
            return f"{where} `{key}` is not a regular expression ({exc})"
        missing = [g for g in groups if g not in names]
        if missing:
            return f"{where} `{key}` must name the group `{missing[0]}`"
        extras[key] = pattern
    return ""


# The regex keys of the partial-collect facts and the group each must name; `cause`, `total` and `errors` are optional
# groups the reader may find absent (a module line has no ` - cause`; a count line may carry no total or no errors).
_PARTIAL_REGEXES = {"broken_line": ("path",), "count_line": ("selected",), "stopped_line": ()}


def _partial_collect_fields(where: str, row: dict, extras: dict) -> str:
    """Validate and copy the optional partial-collect keys of a `collect_forms` row into `extras`; the problem text
    (it starts with `where`) or "". A key a row does not state stays out of `extras`: a runner with no
    `continue_tokens` is a runner that cannot continue, and that is a fact, not a gap (RH1-3, AR-1)."""
    if "continue_tokens" in row:
        tokens = row["continue_tokens"]
        if not isinstance(tokens, list) or any(not isinstance(t, str) or not t for t in tokens):
            return f"{where} `continue_tokens` must be a list of non-empty strings"
        extras["continue_tokens"] = list(tokens)
    if "partial_exits" in row:
        exits = row["partial_exits"]
        if not isinstance(exits, list) or any(isinstance(e, bool) or not isinstance(e, int) for e in exits):
            return f"{where} `partial_exits` must be a list of integers"
        if any(e in RUNNER_OWN_EXITS for e in exits):
            return f"{where} `partial_exits` lists 124 or 127: the runner's own codes, not a runner fact"
        if set(exits) & set(row.get("ok_exits") or []):
            return f"{where} `partial_exits` repeats an exit that `ok_exits` already calls ok"
        extras["partial_exits"] = list(exits)
    problem = _regex_keys(where, row, extras, _PARTIAL_REGEXES)
    if problem:
        return problem
    if extras.get("partial_exits") and not ("broken_line" in extras and "count_line" in extras):
        return (f"{where} `partial_exits` needs `broken_line` and `count_line`: a partial collect is told by the "
                "broken files it names and the count it reports")
    return ""


def door(cause, audience="role") -> str:
    """The sentence `audience` (`role`, `gate` or `onboarding`) reads for `cause`, with `<argv0>` /
    `<resolved>` still in it for the caller to fill. `""` when the data file cannot say, does
    not know the cause, or has no sentence for that audience: an audience never reads another
    audience's text (a role's door names a digest line a person at a gate cannot use)."""
    data, _note = load_data()
    if data is None or not isinstance(audience, str):
        return ""
    for row in data["causes"]:
        if row["id"] == cause:
            return row["doors"].get(audience, "")
    return ""


# --- classify: what stopped a run that ran nothing -------------------------------------------

def _text(item) -> str:
    if item is None:
        return ""
    if isinstance(item, (bytes, bytearray)):
        return bytes(item).decode("utf-8", errors="replace")
    return item if isinstance(item, str) else str(item)


def _clean_lines(lines) -> list:
    """Non-empty output lines: bytes decoded (bad bytes replaced), CRLF and ANSI escapes gone."""
    if lines is None:
        return []
    if isinstance(lines, (str, bytes, bytearray)):
        lines = [lines]
    try:
        items = list(lines)
    except TypeError:
        return []
    cleaned = []
    for item in items:
        for part in _text(item).splitlines():
            part = _ANSI_RE.sub("", part).strip()
            if part:
                cleaned.append(part)
    return cleaned


def _named_options(line: str, patterns) -> list:
    """The option names the output line says were rejected (`--reruns`, not `--reruns=2`)."""
    names = []
    for rx in patterns:
        found = rx.search(line)
        if not found:
            continue
        for word in (found.group(1) or "").split():
            if word.startswith("-") and len(word) > 1:
                names.append(word.split("=", 1)[0])
    return names


def _option_in_argv(names, argv) -> bool:
    tokens = [str(a) for a in argv]
    return any(tok == name or tok.startswith(name + "=") for name in names for tok in tokens)


def _base_name(token) -> str:
    """The last path component of `token`, quotes and backticks removed: `'C:\\x\\poetry.exe'`
    -> `poetry.exe`. Both separators are split on, whatever the platform this runs on."""
    return re.split(r"[\\/]", str(token).strip().strip("'\"`"))[-1]


def _name_forms(name: str) -> set:
    """`name` as it can be spelled by a shell: with and without a Windows executable suffix,
    case-normalised the way the platform's file names are."""
    forms = {name}
    for suffix in _EXE_SUFFIXES:
        if name.lower().endswith(suffix) and len(name) > len(suffix):
            forms.add(name[:-len(suffix)])
    return {os.path.normcase(form) for form in forms if form}


def _programs_run(argv, wrappers) -> set:
    """The names of the programs `argv` starts: argv[0], and, when argv[0] is a known wrapper
    (`poetry run pytest`, `npx playwright`), the program after it (its subcommand and any
    leading options skipped). A wrapper option that takes a value (`uv run --with x pytest`)
    reads `x` as the program: the set then holds a wrong name and the line about `pytest` is
    not confirmed, which is the safe direction."""
    tokens = [str(a) for a in (argv or [])]
    if not tokens:
        return set()
    names = _name_forms(_base_name(tokens[0]))
    subs = wrappers.get(os.path.splitext(_base_name(tokens[0]))[0]) if wrappers else None
    if subs is not None:
        rest = tokens[1:]
        if subs:
            rest = rest[1:] if rest and rest[0] in subs else []
        while rest and rest[0].startswith("-"):
            rest = rest[1:]
        if rest:
            names |= _name_forms(_base_name(rest[0]))
    return names


def _not_found_subject(line: str, marker: str) -> str:
    """The program a `not found` line says is missing. `bash: aws: command not found` and
    `'aws' is not recognized as ...` name it BEFORE the marker; `zsh: command not found: aws` and
    `Command not found: pytest` name it AFTER a colon. Only the word next to the marker counts:
    `run.sh: line 3: aws: command not found` is about `aws`, not about `run.sh`, and a line
    that merely mentions the program elsewhere is not a line about it."""
    index = line.find(marker)
    if index < 0:
        return ""
    after = line[index + len(marker):].lstrip()
    if after.startswith(":"):
        words = after[1:].split()
        return _base_name(words[0]) if words else ""
    words = line[:index].rstrip(" \t:'\"`").split()
    return _base_name(words[-1]) if words else ""


def _confirm(cause: dict, line: str, marker: str, argv, data: dict) -> tuple:
    """`(holds, note)`: does `line` really say this cause, against the profile's `argv`?"""
    if cause["patterns"]:
        named = _named_options(line, cause["patterns"])
        if not named or argv is None or not _option_in_argv(named, argv):
            return False, (f"the output matches `{cause['id']}` but names no option that is in "
                           "the profile's own argv")
    if cause.get("requires") == "program_run":
        programs = _programs_run(argv, data["wrappers"])
        if not programs:
            return False, (f"the output matches `{cause['id']}`, but no argv was given, so it "
                           "cannot be confirmed that the line is about the program that was run")
        if not (_name_forms(_not_found_subject(line, marker)) & programs):
            return False, (f"the output matches `{cause['id']}`, but the line does not name the "
                           "program the profile runs ("
                           + ", ".join(sorted(programs))[:80] + ") as the one not found")
    return True, ""


def classify(exit_code, lines, totals, *, argv=None) -> dict:
    """What stopped a run that ran nothing: `{"cause", "evidence"}` (+ `"note"` when the data
    file could not be used, or a matching line was not believed).

    - `totals` is the run's totals record. Any record at all (even `tests=1, errors=1`: a
      collection error is a run with totals) means something ran, and the answer is exactly
      `{"cause": None}` — no `evidence` key. "Nothing ran" is `totals is None`.
    - The causes come from the data file in its order; the first cause that HOLDS wins (module
      docstring: a marker in a line plus the cause's own confirmation against `argv`; data
      order decides only among causes that hold). Matching is case-sensitive, after ANSI
      escapes are removed. `evidence` is the first line that made that cause hold, clipped to
      200 characters.
    - `argv` is the PROFILE's own argv, given by the caller (`run_suite` has it). A cause that
      needs confirming and cannot be (no argv, or no option / program of the argv in the line)
      is not returned: the answer is the next cause that holds, else `unknown`, with the first
      unbelieved line as evidence and a `note`. A confident wrong cause is worse than none.
    - An unreadable or malformed data file gives `unknown` plus a `note`, never an exception."""
    if totals is not None:
        return {"cause": None}
    data, note = load_data()
    if data is None:
        return {"cause": "unknown", "evidence": "", "note": note}
    cleaned = _clean_lines(lines)
    # An argv that is not a list of tokens (a string, a number) confirms nothing.
    if argv is not None:
        try:
            argv = None if isinstance(argv, (str, bytes, bytearray)) else [str(a) for a in argv]
        except TypeError:
            argv = None
    unbelieved = None
    for cause in data["causes"]:
        if not cause["markers"]:
            continue
        for line in cleaned:
            marker = next((m for m in cause["markers"] if m in line), None)
            if marker is None:
                continue
            holds, why = _confirm(cause, line, marker, argv, data)
            if holds:
                return {"cause": cause["id"], "evidence": line[:EVIDENCE_MAX]}
            if unbelieved is None:
                unbelieved = (line[:EVIDENCE_MAX], why)
    if unbelieved is not None:
        return {"cause": "unknown", "evidence": unbelieved[0], "note": unbelieved[1]}
    return {"cause": "unknown", "evidence": ""}


# --- the environment: an activated virtual environment, and taking it away ---------------------

def _env_key(env: dict, name: str):
    """The key `name` has in `env`; on Windows the variable names are case-insensitive."""
    if name in env:
        return name
    if os.name == "nt":
        for key in env:
            if isinstance(key, str) and key.upper() == name.upper():
                return key
    return None


def _norm(path: str) -> str:
    """`path` as it is compared: real (symlinks, junctions and Windows 8.3 short names such as
    `DEV1~1` resolved, as far as the path exists), normalised and case-normalised. Both sides
    of every comparison go through here, so `C:\\Users\\DEV1~1\\p` and
    `C:\\Users\\dev1\\p` are one directory."""
    text = path.strip().strip('"')
    try:
        text = os.path.realpath(text)
    except (OSError, ValueError):
        pass
    return os.path.normcase(os.path.normpath(text))


def _is_root(path: str) -> bool:
    return os.path.dirname(path) == path


def _under(entry: str, prefix: str) -> bool:
    return entry == prefix or entry.startswith(prefix.rstrip(os.sep) + os.sep)


def _folder_key(text: str) -> str:
    """A folder relative to an environment's prefix, spelled one way: `Library\\bin` and
    `library/bin` are the same key; the prefix itself is `.`."""
    key = os.path.normcase(text.replace("\\", "/").strip("/")).replace("\\", "/")
    return key or "."


def _own_folder(entry: str, prefix: str, folders: set) -> bool:
    """Is `entry` (already `_norm`ed) the prefix itself or one of the environment's own
    executable folders under it? `<prefix>\\node_modules\\.bin` is under the prefix and is not
    one: `VIRTUAL_ENV=C:\\proj` names a project, not an environment to strip."""
    if entry == prefix:
        return "." in folders
    tail = entry[len(prefix.rstrip(os.sep)) + 1:]
    return _folder_key(tail) in folders


def strip_activation(env: dict, variables, *, folders=None, interpreter=None, notes=None) -> tuple:
    """`(new_env, removed_variables, removed_path_entries)`: the activated-virtual-environment
    variables taken out of a COPY of `env`, and the PATH entries that are the environment's own
    executable folders (an activated venv's `bin`/`Scripts` is first on PATH, and removing the
    variable alone would leave the interpreter's own launcher in front of the project's).

    A PATH entry goes only when it lies under the directory a removed variable names AND is
    that environment's own folder (`folders`: the data file's `environment_folders`, `.` being
    the directory itself). Both sides are compared after `os.path.realpath` and case
    normalisation. A prefix that names no directory (`POETRY_ACTIVE=1`) is not used; a
    filesystem root, or a directory that holds the interpreter running this check
    (`interpreter`: its directory, default `sys.executable`'s), strips nothing. `notes`, when
    given a list, receives one sentence per prefix that was not used and why, so a caller can
    say it. Which variables were removed is always the second item: an always-active conda
    `base` is removed like any other, and the caller says so, so that a `failed` it produces
    can be understood."""
    if folders is None:
        data, _note = load_data()
        folders = data["environment_folders"] if data else []
    folder_keys = {_folder_key(f) for f in folders}
    if interpreter is None:
        interpreter = os.path.dirname(sys.executable or "")
    interp = _norm(interpreter) if interpreter else ""
    out = dict(env)
    removed, prefixes = [], []
    for name in variables:
        key = _env_key(out, name)
        if key is None:
            continue
        value = _text(out.pop(key))
        removed.append(name)
        raw = value.strip().strip('"')
        if not raw or not os.path.isabs(raw):
            continue
        prefix = _norm(raw)
        if _is_root(prefix):
            reason = "a filesystem root"
        elif interp and _under(interp, prefix):
            reason = "it holds the interpreter that is running this check"
        else:
            prefixes.append(prefix)
            continue
        if notes is not None:
            notes.append(f"{name}={value.strip()} left its PATH entries alone: {reason}")
    dropped = []
    path_key = _env_key(out, "PATH")
    if path_key is not None and prefixes:
        kept = []
        for entry in _text(out[path_key]).split(os.pathsep):
            gone = False
            if entry.strip():
                real = _norm(entry)
                gone = any(_under(real, prefix) and _own_folder(real, prefix, folder_keys)
                           for prefix in prefixes)
            if gone:
                dropped.append(entry)
            else:
                kept.append(entry)
        out[path_key] = os.pathsep.join(kept)
    return out, removed, dropped


def _active_variables(env: dict, variables) -> dict:
    found = {}
    for name in variables:
        key = _env_key(env, name)
        if key is not None:
            found[name] = _text(env[key])
    return found


# --- probe: collect with the profile's own command ---------------------------------------------

def _is_flag(token: str) -> bool:
    return (token.startswith("-") and token not in ("-", "--") and "=" not in token
            and not _NEGATIVE_NUMBER_RE.fullmatch(token))


def strip_placeholders(argv, positional=None) -> tuple:
    """`(tokens, None)` with every `<...>` placeholder gone, or `(None, why)` when the shape
    cannot be reduced without guessing.

    How the flag a placeholder belongs to is decided:
    - A POSITIONAL placeholder (`positional`: the data file's `positional_placeholders`, default
      read from it; `<test-file>`, `<test-path>`) stands for a bare argument and only it goes:
      `pytest --no-cov <test-file>` -> `pytest --no-cov`, which is what S5 builds
      (`execution_request._profile_argv`), so the probe proves the command S5 runs.
    - `-m <test-id>`: any other standalone placeholder right after a token that starts with `-`
      and has no `=` is that flag's value; both go. (A boolean flag before such a placeholder is
      dropped too: the probe then runs without one option, which can hide a problem with that
      option but can never invent one.) A placeholder name the data file does not list keeps
      this rule.
    - `--flag=<x>`: the placeholder sits in the flag's own token; that token goes.
    - `<x>` after a plain token (`--reruns 2 <x>`, `pytest <x>`): a bare positional; only it
      goes, and `2` stays.
    - Undecidable, so not reduced: the program itself is a placeholder; a token that is a
      command string holding a placeholder (`sh -c "pytest <x>"`)."""
    if positional is None:
        data, _note = load_data()
        positional = data["positional_placeholders"] if data else []
    tokens = [str(t) for t in argv]
    if tokens and all(_PLACEHOLDER_RE.search(t) for t in tokens):
        return None, "the argv is only placeholders: there is no command to probe"
    kept = []
    for index, token in enumerate(tokens):
        if not _PLACEHOLDER_RE.search(token):
            kept.append(token)
            continue
        if index == 0:
            return None, "the program (the first token of the argv) is a placeholder"
        if re.search(r"\s", _PLACEHOLDER_RE.sub("", token).strip()):
            return None, (f"`{token[:60]}` is a command string holding a placeholder: which part "
                          "belongs to the placeholder cannot be told")
        if (_PLACEHOLDER_RE.fullmatch(token) and token not in positional
                and len(kept) > 1 and _is_flag(kept[-1])):
            kept.pop()
    return kept, None


class _ShapeUnavailable(Exception):
    """A sibling module this one reads through could not be loaded (the code that recognises a runner, or the profile
    reader): "cannot tell", never a finding."""


def _sibling(name: str):
    """A sibling module of this directory, imported when first needed; one that cannot load is `_ShapeUnavailable`."""
    here = str(Path(__file__).resolve().parent)
    if here not in sys.path:
        sys.path.append(here)  # last: never shadows anything the caller already resolved
    try:
        return importlib.import_module(name)
    except Exception as exc:  # a broken sibling module is not a broken launcher
        raise _ShapeUnavailable(f"{type(exc).__name__}: {exc}"[:EVIDENCE_MAX]) from exc


def _is_pytest(tokens) -> bool:
    """The reading S5 itself uses for "this command is pytest" (it sees through poetry, uv and
    `python -m`), imported when first needed. It is imported, not copied: two readings of one
    question drift apart."""
    return bool(_sibling("execution_request").is_pytest_command(tokens))


# The runners this code can recognise, by the `tool` name of a `collect_forms` row. A row whose
# tool is not here never applies: a runner nobody taught it to recognise is not probed.
_SHAPES = {"pytest": _is_pytest}


def _collect_form(tokens, forms):
    """The `collect_forms` row that applies to the command `tokens`, or None."""
    for row in forms:
        recogniser = _SHAPES.get(row["tool"])
        if recogniser is not None and recogniser(tokens):
            return row
    return None


def runner_row(argv) -> tuple:
    """`(row, problem)`: the `collect_forms` row of the runner `argv` starts, as `load_data` read
    it (`tool`, `append`, `ok_exits`, and `not_executed_exits` / `node_ids` when the row states
    them; also `timeout_kill_line`, `timeout_failure_message`, `timeout_header_line`, the runner's own per-test
    timeout lines, when it states them, RH2-9). `(None, "")` is an answer: no row recognises this command. `(None, why)` is "cannot
    tell": the data file is unreadable or the recogniser could not be loaded; the caller reads
    the runner's exit codes by the legacy rule and says why, it never treats a problem as a
    fact about the runner. Reports and never raises."""
    data, note = load_data()
    if data is None:
        return None, note
    try:
        return _collect_form([str(a) for a in argv or []], data["collect_forms"]), ""
    except _ShapeUnavailable as exc:
        return None, f"the recogniser for this runner could not be loaded ({exc})"
    except Exception as exc:  # a recogniser's own defect is "cannot tell", not a crash
        return None, f"the recogniser for this runner failed ({type(exc).__name__}: {exc})"[:EVIDENCE_MAX]


def runner_identity(argv) -> dict:
    """The ONE reader of "which runner is this command" for new callers (EP1-1, AR-13): `{form_id, collect_row,
    selection, problem, no_direct_form}`. `collect_row` is `runner_row`'s; `form_id` the `id` of the `run_forms` row
    `hooklib.direct_test_form` finds, or ""; `selection` that row's optional `selection` (None when the row states none:
    no selector is built for it). `problem` is a table or reader that could not be read, and then `selection` is None and
    `no_direct_form` is "": a problem of the table is not a fact about the runner (AR-28). `no_direct_form` is the words
    for a command that is no pytest and no known form (the project's own script: it is not read inside, so no selector
    is built, B-6); "" otherwise. Reports and never raises."""
    tokens = [str(a) for a in argv or []]
    identity = {"form_id": "", "collect_row": None, "selection": None, "problem": "", "no_direct_form": ""}
    try:
        data, note = load_data()
        if data is None:
            identity["problem"] = note
            return identity
        identity["collect_row"] = _collect_form(tokens, data["collect_forms"])
        form = _sibling("hooklib").direct_test_form(tokens) if tokens else None
        form_id = str(form.get("id") or "") if isinstance(form, dict) else ""
        identity["form_id"] = form_id
        if form_id in data["selection_problems"]:
            identity["problem"] = data["selection_problems"][form_id]
        else:
            identity["selection"] = data["selection_by_form"].get(form_id) if form_id else None
        if tokens and not identity["problem"] and not form_id and not _is_pytest(tokens):
            identity["no_direct_form"] = (f"this command starts {tokens[0]}, the project's own script; the factory "
                                          "does not read inside it, so it builds no selector for it")
    except _ShapeUnavailable as exc:
        identity.update(selection=None, no_direct_form="", problem=f"the runner reader could not be loaded ({exc})")
    except Exception as exc:  # a reader's own defect is "cannot tell", not a crash
        identity.update(selection=None, no_direct_form="",
                        problem=f"the runner reader failed ({type(exc).__name__}: {exc})"[:EVIDENCE_MAX])
    return identity


def table_note(problem: str) -> str:
    """The note of a runner table that could not be read (E3-12): the collect stays all-or-nothing and never gains a
    flag from the code. The ONE wording, for the gate and for S5 (AR-15)."""
    return f"the runner table could not be read ({problem}): the collect stays all-or-nothing"


def _reader():
    """`profile_contract`, the ONE reader of `profiles[].commands` (OH3-27, AR-13), imported when first needed like
    `_is_pytest`'s sibling: imported, not copied. A sibling that cannot load is "cannot tell", never a crash."""
    return _sibling("profile_contract")


def _argv_of(spec) -> tuple:
    """`(argv list or None, why-not)` for a command spec, through `profile_contract.command_argv` and no parser of its
    own. The reader's words stand: an absent, empty or all-blank argv is `([], "")` (an empty word makes no command, so
    it counts as no argv), and a shape it names a problem for is `(None, problem)`."""
    try:
        words, problem = _reader().command_argv(spec)
    except _ShapeUnavailable as exc:
        return None, f"the profile reader could not be loaded ({exc})"
    return (None, problem) if problem else (words, "")


def _rehearsal_block(project_root, config):
    """`(gate_rehearsal block, problem)`. A config the caller did not hand over is read from the
    project; absent is normal, present-but-unreadable means `skip_collect` cannot be read."""
    if config is None:
        path = Path(project_root) / "qa-factory" / "config.json"
        if not path.is_file():
            return {}, ""
        try:
            config = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError) as exc:
            return {}, (f"qa-factory/config.json is unreadable ({type(exc).__name__}), so "
                        "`gate_rehearsal` cannot be read and nothing was run")
    block = config.get("gate_rehearsal") if isinstance(config, dict) else None
    return (block if isinstance(block, dict) else {}), ""


def _timeout_of(block: dict):
    raw = block.get("collect_timeout_s")
    if raw is None or raw == "" or isinstance(raw, bool):
        return DEFAULT_TIMEOUT_S
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return DEFAULT_TIMEOUT_S
    if not value > 0 or value == float("inf"):
        return DEFAULT_TIMEOUT_S
    return int(value) if value == int(value) else value


def _result(status, profile_id, argv=(), resolved=None, cause=None, evidence="", env=None,
            reason="", exit_code=None, broken_files=None) -> dict:
    out = {"status": status, "profile": profile_id, "argv": [str(a) for a in argv],
           "resolved": resolved, "cause": cause, "evidence": evidence, "env": dict(env or {}),
           "reason": reason, "exit_code": exit_code}
    if broken_files:
        # additive (FR-14): present only when the collect went on past files that failed to import; `[{path, head}]`
        out["broken_files"] = [dict(b) for b in broken_files]
    return out


def probe(profile, project_root, *, env=None, run=None, which=None, config=None) -> dict:
    """Collect with the profile's own command; `{status, profile, argv, resolved, cause,
    evidence, env, reason, exit_code[, broken_files]}` (`reason` and `exit_code` are additions to the spec's
    shape: why nothing was checked, and the launcher's exit; `broken_files` `[{path, head}]` is present only on an
    `ok` whose collect went on past test files that failed to import).

    `status`: `ok` (an exit the collect form lists: for pytest 0 or 5, for any other runner
    only 0), `failed` (the launch or the collect failed; `cause` and `evidence` say why),
    `not_checked` (this code cannot tell — never a finding, `reason` says why).

    The command, in order: the profile's `commands.one_test.argv` with every `<...>` placeholder
    removed (a positional placeholder alone, any other with the flag it is the value of — see
    `strip_placeholders`) plus the collect form's `append` (data: `--collect-only -q`), but ONLY
    when the command is one a `collect_forms` row recognises (pytest-shaped, by
    `execution_request.is_pytest_command`); else the profile's `commands.collect.argv`, placeholders
    removed the same way, no suffix (also what runs when there is no one_test); else
    `not_checked` ("no collect form known for this runner"). A runner with no collect form is
    never launched with another runner's suffix and never `failed`: the check is not stricter
    than the gate A rehearsal, which skips such a runner.

    `env` is the environment the command would run in (default: this process's); `run` and
    `which` are injectable (`subprocess.run` / `shutil.which` shapes) so a test starts nothing.
    `config` is the parsed `qa-factory/config.json` for `gate_rehearsal.skip_collect` and
    `collect_timeout_s`; when not given it is read from the project.
    `env` in the result: the activated-virtual-environment variables present in the environment
    the command ran in (empty when none) — what a caller needs to say "started inside an
    active venv"."""
    run = run or subprocess.run
    which = which or shutil.which
    pid = str(profile.get("profile_id") or "") if isinstance(profile, dict) else ""
    base = dict(os.environ) if env is None else dict(env)
    data, _note = load_data()
    seen = _active_variables(base, data["deactivated_variables"]) if data else {}

    def nothing(reason, argv=()):
        return _result("not_checked", pid, argv, env=seen, reason=reason)

    if not isinstance(profile, dict):
        return nothing("the profile is not an object")
    block, problem = _rehearsal_block(project_root, config)
    if problem:
        return nothing(problem)
    if block.get("skip_collect"):
        return nothing("gate_rehearsal.skip_collect is true: the project asked for no collect")

    try:
        commands, problem = _reader().profile_commands(profile)
    except _ShapeUnavailable as exc:
        return nothing(f"the profile reader could not be loaded, so no command was read ({exc})")
    if problem:
        return nothing(problem)   # a foreign shape of `commands` is named, never read as "no commands"
    if not commands:
        return nothing("the profile declares no commands")
    if data is None:
        # Without the data file there is no collect form and no placeholder name to read: the
        # honest answer is "cannot tell", not a probe with a guessed command.
        return nothing(f"the launch-check data file cannot be read, so no command was built: {_note}")
    positional, forms = data["positional_placeholders"], data["collect_forms"]
    one_argv, why = _argv_of(commands.get("one_test"))
    if one_argv is None:
        return nothing("commands.one_test: " + why)
    try:
        form = None
        if one_argv:
            spec, original = commands["one_test"], one_argv
            tokens, why = strip_placeholders(original, positional)
            if tokens is None:
                return nothing(f"commands.one_test.argv: {why}", original)
            form = _collect_form(tokens, forms)
            if form is not None:
                tokens = tokens + [s for s in form["append"] if s not in tokens]
        if form is None:
            # No collect form for this runner (or no one_test at all): the profile's own
            # `commands.collect` is the only command this code may run. Its exit 0 is the only
            # exit it treats as ok unless a form recognises it (pytest's 5 is pytest's fact).
            collect_argv, why = _argv_of(commands.get("collect"))
            if collect_argv is None:
                return nothing("commands.collect: " + why)
            if not collect_argv:
                if one_argv:
                    return nothing("no collect form known for this runner", tokens)
                return nothing("the profile declares neither commands.one_test.argv nor "
                               "commands.collect.argv")
            spec, original = commands["collect"], collect_argv
            tokens, why = strip_placeholders(original, positional)
            if tokens is None:
                return nothing(f"commands.collect.argv: {why}", original)
            form = _collect_form(tokens, forms)
    except _ShapeUnavailable as exc:
        return nothing("the recogniser of the runner could not be loaded, so no collect form "
                       f"was chosen ({exc})")
    ok_exits = tuple(form["ok_exits"]) if form is not None else (0,)
    if form is not None:
        # the runner's flag for "go on past a file that fails to import" (data, RH1-3): one broken module must not make
        # the probe say the launcher is broken. After the form's own `append`, never twice.
        tokens = tokens + [t for t in form.get("continue_tokens", []) if t not in tokens]

    cwd = Path(project_root) / str(spec.get("cwd") or ".")
    if not cwd.is_dir():
        return nothing(f"the command's cwd is not a directory: {cwd}", tokens)

    timeout = _timeout_of(block)
    head = tokens[0]
    if "/" in head or "\\" in head:
        candidate = Path(head) if Path(head).is_absolute() else cwd / head
        resolved = str(candidate) if candidate.is_file() else None
        missing = f"`{head}` is not a file (looked from {cwd})"
    else:
        path_key = _env_key(base, "PATH")
        found = which(head, path=_text(base[path_key]) if path_key is not None else "")
        resolved = str(found) if found else None
        missing = f"`{head}` was not found on PATH"
    if resolved is None:
        return _result("failed", pid, tokens, None, "executable_not_found",
                       missing[:EVIDENCE_MAX], seen)

    command = [resolved] + tokens[1:]
    run_env = dict(base, PYTHONDONTWRITEBYTECODE="1")
    try:
        done = run(command, cwd=str(cwd), env=run_env, capture_output=True, timeout=timeout,
                   stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return _result("failed", pid, tokens, resolved, "unknown",
                       f"the collect did not finish within {timeout}s", seen)
    except FileNotFoundError as exc:
        return _result("failed", pid, tokens, resolved, "executable_not_found",
                       _text(exc).strip()[:EVIDENCE_MAX], seen)
    except OSError as exc:
        return _result("failed", pid, tokens, resolved, "unknown",
                       f"{type(exc).__name__}: {_text(exc).strip()}"[:EVIDENCE_MAX], seen)
    except Exception as exc:  # a reporter never crashes its caller; "cannot tell" is not a finding
        return _result("not_checked", pid, tokens, resolved, env=seen,
                       reason=f"the probe itself failed ({type(exc).__name__}: {exc})"[:EVIDENCE_MAX])

    code = getattr(done, "returncode", None)
    if isinstance(code, bool) or not isinstance(code, int):
        return _result("not_checked", pid, tokens, resolved, env=seen,
                       reason="the launcher returned no exit code")
    if code in ok_exits:
        return _result("ok", pid, tokens, resolved, env=seen, exit_code=code)
    outputs = [getattr(done, "stdout", None), getattr(done, "stderr", None)]
    outcome = _collect_outcome(code, outputs, form)
    if outcome["kind"] in ("partial", "none_selected"):
        # the launcher works: it collected, and some test files of the PROJECT did not import. Onboarding records a
        # finding for them; the profile is not rewritten for it (the `onboarding` door of `collection_error`).
        import node_ids          # the verdict above came from it, so it imports (AR-15: the ONE names-text builder)
        shown = node_ids.broken_names(outcome["broken"], BROKEN_SHOWN)
        reason = f"{len(outcome['broken'])} test files could not be collected ({shown}); the launcher works"
        if outcome["kind"] == "none_selected":
            reason += ", and the filter selected none of the others"
        return _result("ok", pid, tokens, resolved, env=seen, reason=reason, exit_code=code,
                       broken_files=outcome["broken"])
    verdict = classify(code, outputs, None, argv=original)
    reason = verdict.get("note", "")
    if verdict["cause"] == "unknown" and not verdict.get("evidence"):
        reason = reason or f"exit code {code}; no line of the output names a known cause"
    if outcome["kind"] == "stopped":
        reason = (reason + "; " if reason else "") + "the project's addopts stop the collect at the first error"
    return _result("failed", pid, tokens, resolved, verdict["cause"], verdict.get("evidence", ""),
                   seen, reason, code)


BROKEN_SHOWN = 5   # broken files named in a probe's reason (one line the onboarding role reads); `broken_files` holds all


def _collect_outcome(code, outputs, form) -> dict:
    """`node_ids.collect_verdict` over the probe's output (the ONE reading of a collect's outcome, AR-13/AR-15).
    A module that cannot be imported, or a row with no partial-collect facts, is `failed`, as before."""
    try:
        import node_ids
        return node_ids.collect_verdict(code, "\n".join(_text(o) for o in outputs if o is not None), form)
    except Exception:  # the reading is the factory's own; its defect is the old behaviour, never a pass
        return {"kind": "failed", "broken": []}


# --- the CLI ----------------------------------------------------------------------------------

def _find_project_root(start: Path):
    for base in (start, *start.parents):
        if (base / "qa-factory" / "config.json").is_file():
            return base
    return None


def _overall(results) -> str:
    statuses = [r["status"] for r in results]
    if "failed" in statuses:
        return "failed"
    return "ok" if "ok" in statuses else "not_checked"


def _clip_text(text: str, limit: int = 300) -> str:
    return text if len(text) <= limit else text[:limit] + "..."


def main(argv=None, *, run=None, which=None, env=None, out=None, err=None, cwd=None) -> int:
    """The CLI. Exit 0 whenever it ran (it reports, it does not gate); 2 for an unreadable
    config, no project, or a `--profile` the config does not have (the message names the ids).
    Under `--json` stdout is one JSON document and nothing else. It writes no file."""
    parser = argparse.ArgumentParser(
        prog="launch_check.py",
        description="Collect with each profile's own command and say why a launch failed.")
    parser.add_argument("--profile", help="check only this profile_id")
    parser.add_argument("--deactivated", action="store_true",
                        help="probe with the activated-virtual-environment variables and their "
                             "PATH entries removed (what onboarding proves)")
    parser.add_argument("--json", action="store_true", help="JSON on stdout, nothing else")
    args = parser.parse_args(argv)
    out = out or sys.stdout
    err = err or sys.stderr
    as_json = args.json

    def emit(document: dict, text_lines: list) -> None:
        if as_json:
            out.write(json.dumps(document, ensure_ascii=False, indent=2) + "\n")
        else:
            out.write("\n".join(text_lines) + "\n")

    def refuse(message: str, **extra) -> int:
        err.write(message + "\n")
        if as_json:
            out.write(json.dumps({"status": "error", "error": message, **extra},
                                 ensure_ascii=False, indent=2) + "\n")
        return 2

    start = Path(cwd) if cwd else Path.cwd()
    root = _find_project_root(start.resolve())
    if root is None:
        return refuse("no qa-factory/config.json found from the current directory upward; run "
                      "launch_check.py from the project root")
    try:
        config = json.loads((root / "qa-factory" / "config.json").read_text(encoding="utf-8-sig"))
        if not isinstance(config, dict):
            raise ValueError("the top level is not an object")
    except (OSError, ValueError) as exc:
        return refuse(f"qa-factory/config.json is unreadable ({type(exc).__name__}: {exc}); "
                      "fix it or restore it, then run launch_check.py again")

    raw_profiles = config.get("profiles")
    profiles = []
    for index, item in enumerate(raw_profiles if isinstance(raw_profiles, list) else []):
        if isinstance(item, dict):
            pid = str(item.get("profile_id") or "").strip() or f"#{index}"
            profiles.append((pid, item))
    known = [pid for pid, _ in profiles]
    if args.profile is not None and args.profile not in known:
        return refuse(f"unknown profile `{args.profile}`; the config's profiles are: "
                      + (", ".join(known) if known else "none"), known=known)
    if not profiles:
        message = ("no profile: qa-factory/config.json has no `profiles[]`, so there is no "
                   "command to check")
        emit({"status": "no_profile", "message": message, "profiles": []}, [message])
        return 0
    selected = [(pid, p) for pid, p in profiles if args.profile in (None, pid)]

    base = dict(os.environ) if env is None else dict(env)
    document = {"status": "", "deactivated": bool(args.deactivated), "removed": {}, "profiles": []}
    if args.deactivated:
        data, note = load_data()
        if data is None:
            # Stripping needs the variable list; without it the check would claim a clean
            # shell it did not make.
            document["notes"] = [note]
            document["profiles"] = [
                _result("not_checked", pid, env={}, reason=f"--deactivated cannot be honoured: {note}")
                for pid, _ in selected]
            document["status"] = "not_checked"
            emit(document, ["launch check: not_checked"]
                 + [f"- {r['profile']}: not_checked - {r['reason']}" for r in document["profiles"]])
            return 0
        skipped = []
        base, removed, dropped = strip_activation(
            base, data["deactivated_variables"], folders=data["environment_folders"], notes=skipped)
        document["removed"] = {"variables": removed, "path_entries": dropped, "skipped": skipped}

    results = []
    for pid, profile in selected:
        one = probe(profile, root, env=base, run=run, which=which, config=config)
        one["profile"] = pid
        results.append(one)
    document["profiles"] = results
    document["status"] = _overall(results)

    lines = [f"launch check: {document['status']}"
             + (" (activated-environment variables removed)" if args.deactivated else "")]
    if args.deactivated:
        # Said out loud so that a `failed` that only exists because a variable was removed (a
        # conda `base` that is always active) can be understood by whoever reads it.
        removed_doc = document["removed"]
        lines.append("removed variables: " + (", ".join(removed_doc["variables"]) or "none"))
        lines.append("removed PATH entries: " + (", ".join(removed_doc["path_entries"]) or "none"))
        lines.extend("not stripped: " + note for note in removed_doc["skipped"])
    for one in results:
        head = f"- {one['profile']}: {one['status']}"
        if one["cause"]:
            head += f" ({one['cause']})"
        lines.append(head)
        if one["argv"]:
            lines.append("    command: " + _clip_text(" ".join(one["argv"])))
        if one["resolved"]:
            lines.append(f"    resolved: {one['resolved']}")
        if one["evidence"]:
            lines.append(f"    evidence: {one['evidence']}")
        if one["reason"]:
            lines.append(f"    reason: {one['reason']}")
        if one["env"]:
            lines.append("    activated environment present: " + ", ".join(sorted(one["env"])))
    emit(document, lines)
    return 0


if __name__ == "__main__":
    try:
        import console_io
        console_io.utf8_stdio()
    except ImportError:
        pass
    sys.exit(main())
