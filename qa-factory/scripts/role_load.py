#!/usr/bin/env python3
"""What one role reads before its first useful action - ONE measure, printed layer by layer and as a sum (RC1-14).

A role's start load is not the injection alone. It reads its charter, the project's own `CLAUDE.md`, what
`inject-map.json` delivers (the common layer, its own layer, the project files), the task packet, the launch card,
its brief with the side files the brief points to, and the form it hands over in. The byte caps of audits A22 (42,000 B
of injection) and A25 (58,000 B of the dispatch) measured two overlapping slices of that and missed the rest, so the
number the factory kept under its cap was not the number a role paid (finding 20261030-potolki-inekcii-ne-tam-gde-rezhetsya).
This module is the one place that adds the layers up; audit A22, the retro's rules weight and the Part 3 table all
call `static_load`, never a private sum (AR-13).

  python role_load.py --role <role> [--kind first|repair|rework] [--json]   static: no story, per-story layers are
                                                                            allowances or ceilings, labelled so
  python role_load.py --all [--kind ...] [--json]                           every role of inject-map.json, one table
  python role_load.py --role <role> --story <task> [--dispatch <id>]        a story's real files (the kind of the chosen
                                                                            dispatch unless --kind says one), and the control
                                                                            against the first request in the cost file

Read-only: it writes nothing, not even a cache. Exit 0 on a measure; exit 2 on an unusable request (an unknown role, a
story folder that is not there, a settings file that cannot be read), with the reason on stderr.

`--json` shape (a contract, FR-14; every field has a reader, AR-22): one object per role (`--all`: a list) with
  role, kind, mode ("static"|"story"), story, dispatch   - the text printer, the A22 message
  layers [{name, bytes, measured, source, reason}]       - A22 (the heaviest layer), retro_numbers.rules_weight
  total_bytes, unmeasured, tokens, bytes_per_token       - A22, the printer, rules_weight's `assumption`
  craft_tokens, process_tokens, craft_notes              - A22 (the process ratchet, `process_ratchet_problems`), the printer;
                                                           craft_tokens + process_tokens == tokens; craft = sections of the
                                                           charter and the injected plugin files under `<!-- kind: craft -->`
                                                           above their heading, the rest is process (spec t-1765 2.3, node A4);
                                                           craft_notes: one line per file whose markers were ignored
  threshold_tokens, threshold_confirmed, verdict         - A22 (red only when the threshold is confirmed)
  control {verdict, first_request_tokens, predicted_tokens, gap_percent, reason}   - story mode only; the printer

A layer that cannot be read has `bytes: null` and `measured: false` (never 0, FR-41); an allowance or a ceiling has
its number and `measured: false` and says so in `reason`. `total_bytes` adds every layer whose `bytes` is not null;
`tokens` is ceil(total_bytes / bytes_per_token).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from content_size import content_bytes  # noqa: E402
from hooklib import PLUGIN_ROOT, is_one_component, project_root, read_json  # noqa: E402
from inject_context import DISPATCH_KINDS, delivered_text, dispatch_kind, entries_for  # noqa: E402  (the one reader of `kinds`, AR-13)

SETTINGS_REL = "references/role-load.json"
KINDS = DISPATCH_KINDS               # the dispatch kinds the CLI names; the map's `kinds` rows say what each drops (`first`: nothing)
# The closed list of layer names, in the order a role meets them.
LAYER_NAMES = ("charter", "project_claude_md", "injection_common", "injection_role", "injection_project",
               "packet", "launch", "brief", "brief_sides", "form")
# What the FIRST request of a role holds: the brief, its side files and the form are read later, by tool calls.
FIRST_REQUEST_LAYERS = ("charter", "project_claude_md", "injection_common", "injection_role", "injection_project",
                        "packet", "launch")
# The layers read from package files by `_files_layer`: `measured: false` there means some file could not be read.
FILE_LAYERS = ("charter", "injection_common", "injection_role")
STORY_FILE_LAYERS = ("packet", "launch")      # per-story: a missing one is a fact about the story, not an unreadable file
CLAUDE_MD_RELS = ("CLAUDE.md", ".claude/CLAUDE.md")
CRLF, LF = b"\r\n", b"\n"


class RoleLoadError(ValueError):
    """An unusable request or settings; the CLI answers it with exit 2 and the message."""


# ------------------------------------------------------------------------------------------ settings
def settings_present(plugin_root=PLUGIN_ROOT) -> bool:
    return (Path(plugin_root) / SETTINGS_REL).is_file()


def _settings_problems(doc: dict) -> list:
    def whole(value, low):
        return isinstance(value, int) and not isinstance(value, bool) and value >= low

    problems = []
    for key, low in (("threshold_tokens", 1), ("bytes_per_token", 1)):
        if not whole(doc.get(key), low):
            problems.append(f"`{key}` must be a whole number >= {low}")
    if doc.get("host_base_tokens") is not None and not whole(doc.get("host_base_tokens"), 0):
        problems.append("`host_base_tokens` must be null or a whole number >= 0")
    allowances = doc.get("allowances")
    if not isinstance(allowances, dict) or not all(whole(allowances.get(k), 0) for k in ("packet", "launch")):
        problems.append("`allowances` must hold whole numbers `packet` and `launch`")
    tolerance = doc.get("control_tolerance_percent")
    if isinstance(tolerance, bool) or not isinstance(tolerance, (int, float)) or tolerance < 0:
        problems.append("`control_tolerance_percent` must be a number >= 0")
    ratchet = doc.get("ratchet_tokens")
    if not isinstance(ratchet, dict) or not all(isinstance(k, str) and whole(v, 1) for k, v in ratchet.items()):
        problems.append("`ratchet_tokens` must map a role name to a whole number of tokens")
    if not whole(doc.get("ratchet_slack_tokens"), 0):
        problems.append("`ratchet_slack_tokens` must be a whole number >= 0")
    confirmed = doc.get("threshold_confirmed_by")
    if confirmed is not None and not isinstance(confirmed, str):
        problems.append("`threshold_confirmed_by` must be null or text")
    # The process ratchet and the target (spec t-1765 node A4): ABSENT is legal here (an old file), and the audit names the
    # missing key; PRESENT but malformed is refused.
    process = doc.get("process_ratchet_tokens")
    if process is not None and (not isinstance(process, dict)
                                or not all(isinstance(k, str) and whole(v, 0) for k, v in process.items())):
        problems.append("`process_ratchet_tokens` must map a role name to a whole number of tokens >= 0")
    if doc.get("target_tokens") is not None and not whole(doc.get("target_tokens"), 1):
        problems.append("`target_tokens` must be null or a whole number >= 1")
    target_by = doc.get("target_confirmed_by")
    if target_by is not None and not isinstance(target_by, str):
        problems.append("`target_confirmed_by` must be null or text")
    return problems


def settings(plugin_root=PLUGIN_ROOT) -> dict:
    """THE reader of references/role-load.json. `threshold_confirmed` is True when `threshold_confirmed_by` is a
    non-empty string. An absent, unreadable or malformed file is a RoleLoadError naming the file: an unreadable
    threshold is never read as "no threshold" (E6)."""
    path = Path(plugin_root) / SETTINGS_REL
    doc = read_json(path, None, kind=dict)
    if doc is None:
        raise RoleLoadError(f"{SETTINGS_REL} could not be read ({path}) - the role start load was not measured")
    problems = _settings_problems(doc)
    if problems:
        raise RoleLoadError(f"{SETTINGS_REL} is not usable: " + "; ".join(problems))
    out = dict(doc)
    out["threshold_confirmed"] = bool(str(doc.get("threshold_confirmed_by") or "").strip())
    out["target_confirmed"] = bool(str(doc.get("target_confirmed_by") or "").strip())    # informational until the owner confirms
    out["process_ratchet_tokens"] = doc.get("process_ratchet_tokens")                     # None: an old file without the key
    return out


def tokens_of(total_bytes: int, bytes_per_token: int) -> int:
    """ceil(bytes / bytes_per_token): the conservative side, a measure that errs over."""
    return -(-int(total_bytes) // int(bytes_per_token))


def ratchet_excess(measured: dict, ratchets: dict, slack: int) -> dict:
    """{role: how far its `ratchet_tokens` row sits above the measured tokens} for every role whose row is MORE than
    `slack` (`ratchet_slack_tokens` of role-load.json, the one place the slack lives) above the measure, or has no row.
    AT the slack is no entry, one token beyond is one: a shrink-only ratchet that sits higher than the load is a raise
    nobody named, and the fix is to lower the row (AR-20)."""
    return {role: (ratchets.get(role) - tokens) if role in ratchets else None
            for role, tokens in measured.items()
            if role not in ratchets or ratchets[role] - tokens > slack}


# ------------------------------------------------------------------------------------------ craft and process (spec t-1765 A4)
KIND_MARKER = re.compile(r"<!--\s*kind:\s*([A-Za-z0-9_-]+)\s*-->")
KNOWN_KINDS = ("craft", "process")        # a `kind:` value outside this tuple is ignored and counted, never read as craft
_COMMENT_LINE = re.compile(r"<!--.*-->")
_HEADING = re.compile(r"^(#{1,6})\s+\S")


def craft_split(text: str) -> tuple:
    """(craft_bytes, ignored) of one delivered text. A section is CRAFT when a `<!-- kind: craft -->` line sits above its heading
    (the way `<!-- roles: -->` is placed, contract_slices.parse; blank lines and other comment lines may stand between), and
    explicitly PROCESS under `<!-- kind: process -->`. A heading with no marker takes the kind of the nearest enclosing marked
    heading (a stack of levels: a marked `###` under a craft `##` ends at its sibling, the parent stays craft), and an unmarked
    heading of the same or a higher level than a marked one ends it. Everything else is PROCESS (E-A5). A marker inside a fenced
    code block (``` or ~~~) is not a marker; a marker not above a heading (text follows it, or the file ends) and a `kind:` value
    that is not craft or process are ignored and counted in `ignored`. The marker line belongs to the section it marks, so
    craft + the rest is exactly the bytes of `text`."""
    lines = text.split("\n")
    craft = ignored = 0
    stack = []                        # [(heading level, kind)] of the marked sections in force; the top one decides
    held = []                         # byte costs of a marker line and the blank / comment lines after it, awaiting a heading
    pending = [None]                  # the kind of the last marker line in `held`
    fence = None                      # the character of the open code fence, None outside one

    def in_craft() -> bool:
        return bool(stack) and stack[-1][1] == "craft"

    def flush():
        nonlocal craft
        if in_craft():
            craft += sum(held)
        held.clear()

    for i, line in enumerate(lines):
        cost = len(line.encode("utf-8")) + (1 if i < len(lines) - 1 else 0)
        stripped = line.strip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            if fence is None:
                fence = stripped[0]
            elif fence == stripped[0]:
                fence = None
            if held:
                ignored += 1
                flush()
            craft += cost if in_craft() else 0
            continue
        if fence is not None:
            craft += cost if in_craft() else 0
            continue
        heading = _HEADING.match(line)
        marker = KIND_MARKER.fullmatch(stripped)
        if marker and marker.group(1) in KNOWN_KINDS:
            held.append(cost)
            pending[0] = marker.group(1)
            continue
        if held and (not stripped or _COMMENT_LINE.fullmatch(stripped)) and not heading:
            held.append(cost)
            continue
        if heading:
            depth = len(heading.group(1))
            inline = KIND_MARKER.search(line)
            kind = pending[0] if held else (inline.group(1) if inline and inline.group(1) in KNOWN_KINDS else None)
            if inline and inline.group(1) not in KNOWN_KINDS:
                ignored += 1
            while stack and stack[-1][0] >= depth:
                stack.pop()
            if kind is not None:
                stack.append((depth, kind))
            craft += (sum(held) + cost) if in_craft() else 0
            held.clear()
            continue
        if KIND_MARKER.search(line):
            ignored += 1                                  # a marker inside a text line, or of an unknown kind: not read
        if held:
            ignored += 1
            flush()
        craft += cost if in_craft() else 0
    if held:
        ignored += 1
        flush()
    return craft, ignored


def _craft_measure(role, plugin_root, imap, kind) -> tuple:
    """(craft_bytes, notes) over the texts a role is handed from the package: its charter and the plugin entries
    `inject_context.entries_for` lists, each as `delivered_text` hands it. A file that cannot be read adds no craft (the
    process side then carries it, the side the ratchet holds). One note per file whose markers were ignored."""
    files = [("charter", f"agents/{role}.md", Path(plugin_root) / "agents" / f"{role}.md", None)]
    for entry in entries_for(role, imap, kind):
        if str(entry).startswith("plugin:"):
            rel = str(entry).split(":", 1)[1]
            files.append((str(entry), rel, Path(plugin_root) / rel, str(entry)))
    craft, notes = 0, []
    for _label, rel, path, entry in files:
        try:
            text = path.read_bytes().replace(CRLF, LF).decode("utf-8", errors="replace")
        except OSError:
            continue
        if entry is not None:
            text = delivered_text(entry, text, role, imap, kind)
        got, ignored = craft_split(text)
        craft += got
        if ignored:
            notes.append(f"{rel}: {ignored} `<!-- kind: craft -->` marker(s) not above a heading or of a kind other than craft/process, ignored")
    return craft, notes


def agent_roles(plugin_root=PLUGIN_ROOT) -> list:
    """The roles that have a charter: the stems of agents/*.md."""
    folder = Path(plugin_root) / "agents"
    return sorted(p.stem for p in folder.glob("*.md")) if folder.is_dir() else []


def process_ratchet_problems(measured: dict, rows, roles) -> list:
    """What is wrong with `process_ratchet_tokens` (`rows`) against `measured` {role: process_tokens}, one sentence each; [] when
    sound. Dense and tight with NO slack (spec t-1765 2.3): every role of `roles` (agents/*.md) has a row, no row names a role
    without a file, a process load above its row is a raise nobody named, and a row above the load is a row to lower (AR-20).
    `rows` None is an old file: the missing key is named, nothing is raised."""
    if rows is None:
        return ["references/role-load.json has no `process_ratchet_tokens` - no process ratchet: add one row per role at its "
                "measured process tokens (`role_load.py --all --json`)"]
    problems = []
    for role in sorted(roles):
        have = measured.get(role)
        if role not in rows:
            problems.append(f"`process_ratchet_tokens` has no row for {role} - add `{role}: {0 if have is None else have}`")
        elif have is not None and have > rows[role]:
            problems.append(f"{role} carries {have:,} process tokens, over its shrink-only process ratchet {rows[role]:,} "
                            "(`process_ratchet_tokens` in references/role-load.json): process text does not grow by a token - "
                            "move the fact to the layer that owns it, or mark a craft section `<!-- kind: craft -->`; "
                            "a raise of the ratchet is named in the verdict")
        elif have is not None and have < rows[role]:
            problems.append(f"{role} carries {have:,} process tokens, below its row {rows[role]:,}: lower to {have} "
                            "(`process_ratchet_tokens` in references/role-load.json; the slack is 0)")
    for role in sorted(r for r in rows if r not in set(roles)):
        problems.append(f"stale row `{role}` in `process_ratchet_tokens`: there is no agents/{role}.md - delete it")
    return problems


# ------------------------------------------------------------------------------------------ the map and its roles
def load_imap(plugin_root=PLUGIN_ROOT) -> dict:
    """inject-map.json of `plugin_root`: through `inject_context.load_map` for the running package (the one reader the hook
    uses), from the file for any other tree (a fixture); {} when it cannot be read."""
    root = Path(plugin_root)
    if root.resolve() == PLUGIN_ROOT.resolve():
        import inject_context
        imap = inject_context.load_map()
    else:
        imap = read_json(root / "references" / "inject-map.json", {}, errors=Exception)
    return imap if isinstance(imap, dict) else {}


def role_names(plugin_root=PLUGIN_ROOT) -> list:
    roles = load_imap(plugin_root).get("roles")
    return list(roles) if isinstance(roles, dict) else []


def _require_role(role, plugin_root) -> list:
    names = role_names(plugin_root)
    if not isinstance(role, str) or role not in names:
        raise RoleLoadError("name a role of inject-map.json: " + (", ".join(names) or "(the map names none)"))
    return names


def _split(entries) -> tuple:
    """(plugin entries, project entries) of a list of inject-map entries; no prefix = a project entry (resolve_entry)."""
    plugin = [str(e) for e in entries or [] if str(e).startswith("plugin:")]
    return plugin, [str(e) for e in entries or [] if not str(e).startswith("plugin:")]


# ------------------------------------------------------------------------------------------ layers
def _layer(name, nbytes, measured=True, source="", reason="") -> dict:
    return {"name": name, "bytes": nbytes, "measured": measured, "source": source, "reason": reason}


def _file_bytes(path) -> tuple:
    """(bytes, "") or (None, why): a missing or unreadable file is None, never 0."""
    try:
        if not Path(path).is_file():
            return None, "missing"
        return content_bytes(path), ""
    except OSError:
        return None, "unreadable"


def _delivered_bytes(path, rel, role, imap, kind) -> tuple:
    """`_file_bytes` of an entry as a dispatch of `kind` delivers it: the bytes of `inject_context.delivered_text` (the text the
    hook hands the role), in the rule of `content_size.content_bytes` (CRLF read as LF). An entry no row of the kind touches is
    `content_bytes` itself, so for `first` the number is the plain file size, as before the kinds."""
    size, why = _file_bytes(path)
    if size is None:
        return size, why
    try:
        text = Path(path).read_bytes().replace(CRLF, LF).decode("utf-8", errors="replace")
    except OSError:
        return None, "unreadable"
    cut = delivered_text(rel, text, role, imap, kind)
    return (size, "") if cut is text else (len(cut.encode("utf-8")), "")


def _files_layer(name, items, source, sizer=None) -> dict:
    """The layer of files `items` = [(label, path)]. Every file missing: bytes null. Some missing: the bytes of the
    readable ones, `measured: false`, the missing named (a missing layer never counts as 0 B quietly). `sizer(label, path)`
    answers (bytes, why) in place of `_file_bytes` (the kinds: a section dropped is not counted)."""
    if not items:
        return _layer(name, 0, True, source, "no entries")
    total, readable, bad = 0, 0, []
    for label, path in items:
        size, why = (sizer or (lambda _label, _path: _file_bytes(_path)))(label, path)
        if size is None:
            bad.append(why if len(items) == 1 else f"{label} {why}")
        else:
            total, readable = total + size, readable + 1
    if not bad:
        return _layer(name, total, True, source)
    reason = ", ".join(bad) if len(items) == 1 else "missing: " + ", ".join(bad)
    return _layer(name, total if readable else None, False, source, reason)


def _plugin_items(entries, plugin_root) -> list:
    return [(e, Path(plugin_root) / e.split(":", 1)[1]) for e in entries]


def _inside(path, root) -> bool:
    try:
        Path(path).resolve().relative_to(Path(root).resolve())
        return True
    except (OSError, ValueError):
        return False


def _project_path(entry, project) -> Path:
    """The file a `project:` entry names in `project`: `inject_context.resolve_entry` (it may answer with the strategy
    override, a LARGER path: the measure then over-counts, the safe side); an answer outside `project` is not this project's
    file, the conventional path stands."""
    import inject_context
    try:
        found = inject_context.resolve_entry(entry, {"cwd": str(project)})
    except Exception:
        found = None
    if found is not None and _inside(found, project):
        return Path(found)
    return Path(project) / (entry.split(":", 1)[1] if entry.startswith("project:") else entry)


def _project_layer(entries, project) -> dict:
    if not entries:
        return _layer("injection_project", 0, True, "inject-map.json project entries", "no project entries")
    if project is None:
        return _layer("injection_project", None, False, "inject-map.json project entries", "no project")
    total, absent = 0, []
    for entry in entries:
        size, why = _file_bytes(_project_path(entry, project))
        if size is None:
            absent.append(f"{entry} {why}")      # a project that has not written this file yet is legitimate: 0 B, said
        else:
            total += size
    return _layer("injection_project", total, True, "inject-map.json project entries",
                  ("not in the project: " + ", ".join(absent)) if absent else "")


def _claude_md_layer(project) -> dict:
    source = "CLAUDE.md and .claude/CLAUDE.md of the project"
    if project is None:
        return _layer("project_claude_md", None, False, source, "no project")
    total, found = 0, 0
    for rel in CLAUDE_MD_RELS:
        size, _why = _file_bytes(Path(project) / rel)
        if size is not None:
            total, found = total + size, found + 1
    return _layer("project_claude_md", total, True, source, "" if found else "the project has no CLAUDE.md")


def _form_candidates(role, plugin_root) -> list:
    """The contract ids of the role's handovers: `handoff.contract_of(stage, role)` for each stage of stages.json that names
    the role. [] for a tree that is not the running package (the index is the package's own)."""
    import handoff
    stages = read_json(Path(plugin_root) / "references" / "stages.json", {}, kind=dict).get("stages") or []
    ids = []
    for stage in stages:
        if isinstance(stage, dict) and role in (stage.get("roles") or []):
            contract = handoff.contract_of(str(stage.get("id") or ""), role)
            if contract and contract not in ids:
                ids.append(contract)
    return ids


def _static_form_layer(role, plugin_root) -> dict:
    source = "the heaviest handoffs/<contract>.yaml of the role"
    if Path(plugin_root).resolve() != PLUGIN_ROOT.resolve():
        return _layer("form", None, False, source, "the handoff index is read from the running package only")
    try:
        ids = _form_candidates(role, plugin_root)
    except Exception as exc:
        return _layer("form", None, False, source, f"the handoff index could not be read ({type(exc).__name__})")
    if not ids:
        return _layer("form", 0, True, source, "the role fills no handoff form")
    sizes = [(_file_bytes(Path(plugin_root) / "handoffs" / f"{c}.yaml"), c) for c in ids]
    known = [(s[0], c) for s, c in sizes if s[0] is not None]
    if not known:
        return _layer("form", None, False, source, "missing: " + ", ".join(ids))
    size, contract = max(known)
    gaps = [c for s, c in sizes if s[0] is None]
    return _layer("form", size, not gaps, f"handoffs/{contract}.yaml", ("missing: " + ", ".join(gaps)) if gaps else "")


def _brief_ceiling(role=None, plugin_root=PLUGIN_ROOT) -> int:
    """The brief's byte ceiling: its body cap and, for a role whose agent file is a charter, the hard cap of the SD head the
    brief carries outside the body (t-1765 X1 fix-4, F3): the head is a layer of the load, seen by A22 / F-1."""
    import brief_pack
    import charter
    # the ceiling is compared in budget bytes (the brief counted with the plugin root as a token), the unit "budget B" of brief_pack's labels
    ceiling = int(brief_pack.BRIEF_MAX_BYTES)
    try:
        text = (Path(plugin_root) / "agents" / f"{role}.md").read_text(encoding="utf-8-sig", errors="replace")
    except (OSError, TypeError):
        return ceiling
    return ceiling + int(brief_pack.SD_HEAD_MAX_BYTES) if charter.is_charter(text) else ceiling


def _head_layers(role, plugin_root, project, imap, kind="first") -> list:
    """charter, project_claude_md and the three injection layers: the same in static and story mode. The injection layers are
    what `inject_context.entries_for` lists (the common entries, then the role's own) with the bytes of `delivered_text` for
    `kind`: the text the hook hands a dispatch of that kind, never a private list (AR-13)."""
    entries = entries_for(role, imap, kind)
    n_common = len(imap.get("common") or []) if isinstance(imap.get("common"), list) else 0
    common_plugin, common_project = _split(entries[:n_common])
    own_plugin, own_project = _split(entries[n_common:])

    def sizer(label, path):
        return _delivered_bytes(path, label, role, imap, kind)
    return [
        _files_layer("charter", [("charter", Path(plugin_root) / "agents" / f"{role}.md")], f"agents/{role}.md"),
        _claude_md_layer(project),
        _files_layer("injection_common", _plugin_items(common_plugin, plugin_root), "inject-map.json common", sizer),
        _files_layer("injection_role", _plugin_items(own_plugin, plugin_root), f"inject-map.json roles.{role}", sizer),
        _project_layer(common_project + own_project, project),
    ]


def _assemble(role, kind, mode, story, dispatch, layers, cfg, craft=(0, ())) -> dict:
    total = sum(layer["bytes"] for layer in layers if layer["bytes"] is not None)
    tokens = tokens_of(total, cfg["bytes_per_token"])
    craft_tokens = min(tokens, tokens_of(craft[0], cfg["bytes_per_token"]))       # craft + process = tokens, always
    return {"role": role, "kind": kind, "mode": mode, "story": story, "dispatch": dispatch, "layers": layers,
            "total_bytes": total, "unmeasured": [layer["name"] for layer in layers if not layer["measured"]],
            "tokens": tokens, "craft_tokens": craft_tokens, "process_tokens": tokens - craft_tokens,
            "craft_notes": list(craft[1]),
            "bytes_per_token": cfg["bytes_per_token"], "threshold_tokens": cfg["threshold_tokens"],
            "threshold_confirmed": cfg["threshold_confirmed"],
            "verdict": "within" if tokens <= cfg["threshold_tokens"] else "over"}


def _check_kind(kind) -> None:
    if kind not in KINDS:
        raise RoleLoadError(f"name a dispatch kind: {', '.join(KINDS)}")


def static_load(role, kind=None, plugin_root=PLUGIN_ROOT, project=None) -> dict:
    """The start load of `role` with no story: the package's own files measured, the per-story layers counted as the
    allowances of role-load.json (packet, launch) or the brief's ceiling, each `measured: false` and said so; the brief's
    side files are not counted (`bytes: null`, per story). `project` None leaves the project's layers unmeasured. `kind` None
    is `first`, the full text; an unknown kind is a RoleLoadError. The packet is an allowance of a fixed size whatever the
    kind: the saving of the one-`known_paths` packet is a per-story fact a static measure cannot show (N1 report, K5)."""
    kind = "first" if kind is None else kind
    _check_kind(kind)
    _require_role(role, plugin_root)
    cfg = settings(plugin_root)
    imap = load_imap(plugin_root)
    layers = _head_layers(role, plugin_root, project, imap, kind)
    allowance = cfg["allowances"]
    layers += [
        _layer("packet", allowance["packet"], False, "allowances.packet in role-load.json", "allowance"),
        _layer("launch", allowance["launch"], False, "allowances.launch in role-load.json", "allowance"),
        _layer("brief", _brief_ceiling(role, plugin_root), False, "brief_pack.BRIEF_MAX_BYTES (+ SD_HEAD_MAX_BYTES for a charter)", "ceiling"),
        _layer("brief_sides", None, False, "work/briefs/<ID>-*.md", "per story"),
        _static_form_layer(role, plugin_root),
    ]
    return _assemble(role, kind, "static", None, None, layers, cfg, _craft_measure(role, plugin_root, imap, kind))


def common_list_bytes(plugin_root=PLUGIN_ROOT):
    """The bytes of the `common` list of inject-map.json alone (the layer every role pays), or None when a file of it
    cannot be read: the one number A22's list ratchet judges."""
    plugin, _project = _split(load_imap(plugin_root).get("common"))
    layer = _files_layer("injection_common", _plugin_items(plugin, plugin_root), "inject-map.json common")
    return layer["bytes"] if layer["measured"] else None


# ------------------------------------------------------------------------------------------ story mode
def _task_root(project, task) -> Path:
    root = Path(project) / "qa-factory" / "artifacts" / str(task)
    if not is_one_component(str(task)) or not root.is_dir():
        raise RoleLoadError(f"no story folder {task}")
    return root


def _dispatch_records(task_root) -> dict:
    state = read_json(Path(task_root) / "state" / "controller.json", {}, kind=dict)
    found = state.get("dispatches")
    return found if isinstance(found, dict) else {}


def _pick_dispatch(role, records, dispatch):
    if dispatch is not None:
        record = records.get(dispatch) if is_one_component(str(dispatch)) else None
        if not isinstance(record, dict):
            raise RoleLoadError(f"no dispatch {dispatch} in state/controller.json of this story")
        if record.get("role") != role:
            raise RoleLoadError(f"dispatch {dispatch} belongs to {record.get('role')}, not {role}")
        return dispatch
    mine = [i for i, r in records.items() if isinstance(r, dict) and r.get("role") == role]
    return mine[-1] if mine else None


def _story_layers(role, task_root, dispatch) -> list:
    if dispatch is None:
        why = f"no dispatch of {role} in this story"
        return [_layer(n, None, False, "", why) for n in ("launch", "brief", "brief_sides", "form")]
    import launch_card
    import story_step

    def one(name, rel, missing):
        size, _why = _file_bytes(Path(task_root) / rel)
        return _layer(name, size, size is not None, rel, "" if size is not None else missing)

    briefs = Path(task_root) / "work" / "briefs"
    sides = sorted(briefs.glob(f"{dispatch}-*.md")) if briefs.is_dir() else []
    side_layer = _files_layer("brief_sides", [(p.name, p) for p in sides], f"work/briefs/{dispatch}-*.md")
    if not sides:
        side_layer = _layer("brief_sides", 0, True, f"work/briefs/{dispatch}-*.md", "no side files")
    return [one("launch", launch_card.CARD_REL.format(dispatch_id=dispatch), "no launch card"),
            one("brief", story_step.BRIEF_REL.format(dispatch_id=dispatch), "no brief"),
            side_layer,
            one("form", story_step.FORM_REL.format(dispatch_id=dispatch), "no form yet")]


def story_load(role, task, dispatch=None, project=None, kind=None, plugin_root=PLUGIN_ROOT) -> dict:
    """The start load of `role` in a story: its real brief, side files (every `<ID>-*.md` of the dispatch: an upper bound,
    labelled - no code reads which the brief says to read first), launch card and form; the packet stays an allowance until
    one builder makes it (Part 2). Without `dispatch`, the last dispatch of the role in `state/controller.json`. `kind` None
    takes the kind of the chosen dispatch's record (`inject_context.dispatch_kind`, the hook's own reader; `first` when there is
    no dispatch); an explicit kind is measured as asked."""
    if kind is not None:
        _check_kind(kind)
    _require_role(role, plugin_root)
    cfg = settings(plugin_root)
    project = Path(project) if project is not None else project_root()
    task_root = _task_root(project, task)
    records = _dispatch_records(task_root)
    chosen = _pick_dispatch(role, records, dispatch)
    if kind is None:
        kind = dispatch_kind(records.get(chosen)) if chosen is not None else "first"
    imap = load_imap(plugin_root)
    layers = _head_layers(role, plugin_root, project, imap, kind)
    layers.insert(5, _layer("packet", cfg["allowances"]["packet"], False, "allowances.packet in role-load.json", "allowance"))
    layers += _story_layers(role, task_root, chosen)
    load = _assemble(role, kind, "story", str(task), chosen, layers, cfg, _craft_measure(role, plugin_root, imap, kind))
    load["control"] = first_request_control(load, project, plugin_root)
    return load


# ------------------------------------------------------------------------------------------ the control
def _control(verdict, first=None, predicted=None, gap=None, reason="") -> dict:
    return {"verdict": verdict, "first_request_tokens": first, "predicted_tokens": predicted,
            "gap_percent": gap, "reason": reason}


def first_request_control(load: dict, project, plugin_root=PLUGIN_ROOT) -> dict:
    """The sum against the first request the cost file recorded for the dispatch (the cost file is authoritative, FR-25).

    first = input + cache_read + cache_write_5m + cache_write_1h of the agent's earliest request; predicted =
    ceil(bytes of the first-request layers / bytes_per_token) + host_base_tokens. `ok` within control_tolerance_percent,
    else `defect`; no cost row, a collapsed ledger, a dispatch with no bound agent, a legacy row with no cache fields, or a
    first-request layer that could not be read (never counted as 0) is `not_measured` with its reason; `host_base_tokens` null is `not_calibrated` (the gap is printed with a base of 0,
    never as a pass)."""
    import cost_capture
    cfg = settings(plugin_root)
    records = _dispatch_records(_task_root(project, load["story"]))
    record = records.get(load.get("dispatch")) if load.get("dispatch") else None
    agent = record.get("agent_id") if isinstance(record, dict) else None
    if not load.get("dispatch"):
        return _control("not_measured", reason=f"no dispatch of {load['role']} in this story")
    hit, why = cost_capture.first_request_lookup(project, agent)
    if hit is None:
        return _control("not_measured", reason=why)
    usage = hit["usage"]
    parts = ("input", "cache_read", "cache_write_5m", "cache_write_1h")
    if any(not isinstance(usage.get(k), int) for k in parts):
        return _control("not_measured", reason="the first request row has no cache fields (a legacy row)")
    first = sum(usage[k] for k in parts)
    if first <= 0:
        return _control("not_measured", reason="the first request row holds no input tokens")
    by_name = {layer["name"]: layer for layer in load["layers"]}
    # A layer the measure could not read is not 0 B: the prediction would be short and could still read ok (FR-41).
    # The launch card and the packet are per-story files: no card is a fact about the story (driver mode has none), 0 B.
    gaps = [n for n in FIRST_REQUEST_LAYERS
            if (by_name[n]["bytes"] is None and n not in STORY_FILE_LAYERS)
            or (n in FILE_LAYERS and not by_name[n]["measured"])]
    if gaps:
        return _control("not_measured", reason="the prediction is not built from a layer that could not be read: " + ", ".join(gaps))
    predicted_bytes = sum(by_name[n]["bytes"] or 0 for n in FIRST_REQUEST_LAYERS)      # only a per-story layer can be None here
    base = cfg["host_base_tokens"]
    predicted = tokens_of(predicted_bytes, cfg["bytes_per_token"]) + (base or 0)
    gap = round(abs(first - predicted) / first * 100, 1)
    if base is None:
        return _control("not_calibrated", first, predicted, gap,
                        "host_base_tokens is null in role-load.json: the gap is printed with a host base of 0 and is not a verdict")
    verdict = "ok" if gap <= cfg["control_tolerance_percent"] else "defect"
    return _control(verdict, first, predicted, gap, f"cost file {hit['file']}, request at {hit['timestamp']}")


# ------------------------------------------------------------------------------------------ printing
def heaviest_layer(load: dict) -> dict:
    """The layer with the most bytes (the first of equals, by layer order)."""
    return max((layer for layer in load["layers"] if layer["bytes"] is not None), key=lambda layer: layer["bytes"])


def render_text(load: dict) -> str:
    status = "provisional, owner's word pending" if not load["threshold_confirmed"] else "confirmed"
    lines = [f"{load['role']} ({load['kind']}, {load['mode']}"
             + (f", story {load['story']}, dispatch {load['dispatch'] or '-'}" if load["mode"] == "story" else "")
             + f"): ~{load['tokens']:,} tokens, {load['total_bytes']:,} B - {load['verdict']} the threshold "
             f"{load['threshold_tokens']:,} tokens ({status})"]
    for layer in load["layers"]:
        size = "not counted" if layer["bytes"] is None else f"{layer['bytes']:,} B"
        note = layer["reason"] + (" - estimated" if layer["bytes"] is not None and not layer["measured"] else "")
        lines.append(f"  {layer['name']:<19} {size:>12}  {layer['source']}" + (f"  [{note.strip(' -')}]" if note.strip(" -") else ""))
    lines.append(f"  craft {load['craft_tokens']:,} + process {load['process_tokens']:,} tokens")
    lines += [f"  craft marker: {note}" for note in load["craft_notes"]]
    if load["unmeasured"]:
        lines.append("  not measured: " + ", ".join(load["unmeasured"]))
    control = load.get("control")
    if control:
        lines.append(f"  control: {control['verdict']}"
                     + (f" - first request {control['first_request_tokens']:,} tokens, predicted "
                        f"{control['predicted_tokens']:,}, gap {control['gap_percent']}%" if control["first_request_tokens"] else "")
                     + (f" ({control['reason']})" if control["reason"] else ""))
    return "\n".join(lines)


TABLE_COLUMNS = (("charter", "charter"), ("injection_common", "common"), ("injection_role", "slices"),
                 ("packet", "packet*"), ("launch", "launch*"), ("brief", "brief*"), ("form", "form"))


def render_table(loads: list, ratchets: dict | None = None) -> str:
    """One row per role: tokens, bytes, tokens free under the threshold, the ratchet row, every layer in bytes, the heaviest."""
    if not loads:
        return "no role in inject-map.json"
    first = loads[0]
    status = "provisional, owner's word pending" if not first["threshold_confirmed"] else "confirmed"
    head = (f"role start load, {first['mode']}, kind {first['kind']}: ceil(bytes / {first['bytes_per_token']}) tokens; threshold "
            f"{first['threshold_tokens']:,} tokens ({status})")
    cols = ["role", "tokens", "craft", "process", "bytes", "free", "ratchet"] + [c for _n, c in TABLE_COLUMNS] + ["heaviest"]
    rows = []
    for load in loads:
        by = {layer["name"]: layer for layer in load["layers"]}
        ratchet = (ratchets or {}).get(load["role"])
        rows.append([load["role"], f"{load['tokens']:,}", f"{load['craft_tokens']:,}", f"{load['process_tokens']:,}", f"{load['total_bytes']:,}",
                     f"{load['threshold_tokens'] - load['tokens']:,}", f"{ratchet:,}" if ratchet else "-"]
                    + ["n/a" if by[n]["bytes"] is None else f"{by[n]['bytes']:,}" for n, _c in TABLE_COLUMNS]
                    + [heaviest_layer(load)["name"]])
    widths = [max(len(str(r[i])) for r in [cols] + rows) for i in range(len(cols))]
    fmt = lambda r: "  ".join(str(v).ljust(widths[i]) if i in (0, len(cols) - 1) else str(v).rjust(widths[i]) for i, v in enumerate(r))
    notes = ("* = an allowance or a ceiling, not a measure (packet, launch card, brief at BRIEF_MAX_BYTES). "
             "Not counted in static mode: project_claude_md, injection_project (no project), brief_sides (per story).")
    return "\n".join([head, fmt(cols), fmt(["-" * w for w in widths])] + [fmt(r) for r in rows] + [notes])


# ------------------------------------------------------------------------------------------ the CLI
def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="The start load of a role: every layer it reads before its first useful action.")
    p.add_argument("--role", help="a role of inject-map.json")
    p.add_argument("--all", action="store_true", help="every role of inject-map.json, static mode")
    p.add_argument("--kind", choices=KINDS, default=None,
                   help="the dispatch kind (default: first; with --story, the kind of the measured dispatch)")
    p.add_argument("--story", help="a task id: measure the story's real files")
    p.add_argument("--dispatch", help="a dispatch id of the story (default: the role's last one)")
    p.add_argument("--json", action="store_true", help="the machine shape")
    return p


def main(argv=None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.all and (args.role is not None or args.story is not None or args.dispatch is not None):
            raise RoleLoadError("--all measures every role in static mode: drop --role, --story and --dispatch")
        if args.dispatch is not None and args.story is None:
            raise RoleLoadError("--dispatch names a dispatch of a story: add --story <task>")
        if args.all:
            loads = [static_load(r, args.kind) for r in role_names()]
            ratchets = settings().get("ratchet_tokens")
            print(json.dumps(loads, indent=2) if args.json else render_table(loads, ratchets))
            return 0
        if args.role is None:
            raise RoleLoadError("name a role of inject-map.json: " + ", ".join(role_names()))
        load = (story_load(args.role, args.story, args.dispatch, kind=args.kind) if args.story is not None
                else static_load(args.role, args.kind))
    except RoleLoadError as exc:
        print(f"role_load: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(load, indent=2) if args.json else render_text(load))
    return 0


if __name__ == "__main__":
    sys.exit(main())
