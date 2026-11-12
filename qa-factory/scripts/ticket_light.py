"""The ticket in a light form, and what a person's ticket text holds: pure functions, no I/O but
the two data tables.

D-06 (owner): ticket data comes by the tracker's API in a light form, and a tracker agent is not
a data source. This module is the pure half of that: it turns one raw Jira issue into the light
snapshot a role reads (`project`), finds the acceptance criteria of a ticket (`acceptance_criteria`),
writes and reads the one-line-per-comment view (`comment_lines`, `parse_comment_lines`), compares
the person's text with what the tracker says now (`compare_person_vs_rest`), lists every
reference a ticket's text carries (`references`) and measures how much of a snapshot is the
ticket's own words (`own_words_share`). Nothing here touches the network, the clock or the story
folder: the caller reads, this module shapes. Stdlib only.

Closed variety lives in two data files (FR-13): references/jira-fields.json and
references/reference-kinds.json. A missing, unreadable or empty table REFUSES with `TableError`
naming the file - never a silent empty whitelist, which would project every ticket to nothing and
look like a ticket with no content (TP1-15045 had 164 custom fields, 132 of them empty, and a
projection that silently dropped the rest would have been indistinguishable from it).

The raw response is stored whole by the caller; the projection only decides what a ROLE sees
(P4: nothing fetched is lost). The invariant the tests hold: every string of the issue's
whitelisted fields is in the light form, or is a value under a noise key.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urlsplit

import adapter_forms as AF

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
FIELDS_TABLE_PATH = PLUGIN_ROOT / "references" / "jira-fields.json"
KINDS_TABLE_PATH = PLUGIN_ROOT / "references" / "reference-kinds.json"

# FR-29: the characters that are easy to lose in a heredoc are built from code points.
BS = chr(92)
MID_DOT = chr(0xB7)
SEP = " " + MID_DOT + " "
LS, PS, NEL = chr(0x2028), chr(0x2029), chr(0x85)

# The single source of the key shape (C11) is `adapter_forms` (references/adapter-forms.json, B-405): this
# is its DEFAULT form, the Jira one, a compiled regex. Uppercase only, and no letter or digit glued to it on
# either side: the look-behind keeps `MY_PROJ-12` from yielding `PROJ-12` (the underscore is part of
# a Jira project key) and `fooTP1-9` from yielding `TP1-9`; the look-ahead keeps `ABC-12X` and
# `TP1-9a` out (t-280 F11: a lowercase letter glued to a key is not a key either - the old shape
# let both through). source_inventory.TICKET_KEY_RE is this very object. The key inside a browse
# URL is read through the same pattern (`ticket_url_regex`), so the two cannot disagree. A table that cannot
# be read gives the declared floor here (the same Jira shape) and the damage is kept in FORMS_DAMAGE: the
# readers that must refuse (`references`, via `key_form`) say it, naming the file.
_DEFAULT_FORM = AF.key_form(None, floor=True)
KEY_RE = _DEFAULT_FORM.link_key
_STRICT_KEY_RE = _DEFAULT_FORM.strict
FORMS_DAMAGE = " ".join(p.text for p in _DEFAULT_FORM.problems if p.code == AF.TABLE_UNREADABLE)

# Light snapshot keys the readers parse (ticket_adapter.SCHEMA_KEYS; brief_pack.snapshot_mask_lines
# and stage_compare.s0 read them). A test compares this tuple with the adapter's own.
SCHEMA_KEYS = ("key", "type", "status", "title", "description", "acceptance_criteria",
               "comments", "parent", "subtasks", "links")
# The standard fields the projection cannot do without: a table that lacks one is refused.
CORE_STANDARD = ("summary", "description", "status", "issuetype", "parent", "issuelinks",
                 "subtasks", "comment", "attachment", "updated")


class TableError(ValueError):
    """A data table or a call's whitelist is missing, malformed or empty. The message says what
    was refused, what was expected, and how to restore it (FR-1)."""


# ---------------------------------------------------------------------------------------------
# Data tables
# ---------------------------------------------------------------------------------------------

def _load_table(path: Path, label: str) -> dict:
    try:
        raw = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise TableError(f"{label} cannot be read ({exc.__class__.__name__}): expected the table at "
                         f"{path}; restore it from the plugin package (references/{label}) - "
                         "without it nothing is projected rather than everything silently dropped") from None
    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise TableError(f"{label} is not valid JSON ({exc}): expected a JSON object at {path}; "
                         f"restore references/{label} from the plugin package") from None
    if not isinstance(data, dict):
        raise TableError(f"{label} must be a JSON object, got {type(data).__name__}; "
                         f"restore references/{label} from the plugin package")
    return data


def _need_list(table: dict, key: str, label: str, *, nonempty: bool = True) -> list:
    value = table.get(key)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise TableError(f"{label}: key `{key}` must be a list of strings, got {type(value).__name__}; "
                         f"restore it in references/{label}")
    if nonempty and not [item for item in value if item.strip()]:
        raise TableError(f"{label}: key `{key}` is empty, which would silently drop everything it guards; "
                         f"expected at least one entry in references/{label}")
    return value


def check_fields_table(table, label: str = "jira-fields.json") -> dict:
    """The shape of jira-fields.json, refused with the file and the key named."""
    if not isinstance(table, dict):
        raise TableError(f"{label} must be a JSON object, got {type(table).__name__}; "
                         f"restore references/{label} from the plugin package")
    standard = _need_list(table, "standard", label)
    absent = [name for name in CORE_STANDARD if name not in standard]
    if absent:
        raise TableError(f"{label}: key `standard` lacks {', '.join(absent)}, which the light form "
                         f"cannot be built without; add them back in references/{label}")
    _need_list(table, "noise", label)
    _need_list(table, "acceptance_headings", label)
    _need_list(table, "section_names", label, nonempty=False)
    _need_list(table, "not_tracker_prefixes", label, nonempty=False)
    if not isinstance(table.get("noise_scope", {}), dict):
        raise TableError(f"{label}: key `noise_scope` must be an object; restore references/{label}")
    if not isinstance(table.get("attachment_policy"), dict):
        raise TableError(f"{label}: key `attachment_policy` must be an object; restore references/{label}")
    limit = table.get("description_limit_bytes")
    if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
        raise TableError(f"{label}: key `description_limit_bytes` must be a positive integer, got "
                         f"{limit!r}; restore references/{label}")
    return table


def load_fields_table(path: Path | None = None) -> dict:
    """references/jira-fields.json, validated. Refuses (TableError) when missing or malformed."""
    path = Path(path or FIELDS_TABLE_PATH)
    return check_fields_table(_load_table(path, path.name), path.name)


def check_reference_kinds(table, label: str = "reference-kinds.json") -> dict:
    if not isinstance(table, dict) or not isinstance(table.get("kinds"), list) or not table["kinds"]:
        raise TableError(f"{label}: key `kinds` must be a non-empty list of {{kind, hosts, path_regexes}}; "
                         f"restore references/{label} from the plugin package")
    for entry in table["kinds"]:
        if (not isinstance(entry, dict) or not isinstance(entry.get("kind"), str)
                or not isinstance(entry.get("hosts", []), list)
                or not isinstance(entry.get("path_regexes"), list) or not entry["path_regexes"]):
            raise TableError(f"{label}: every entry of `kinds` needs `kind` (string), `hosts` (list) and "
                             f"a non-empty `path_regexes` (list); got {str(entry)[:80]}; restore "
                             f"references/{label}")
        if "is_change" in entry and not isinstance(entry["is_change"], bool):
            # SS1-13: `is_change` says the kind is a change to the code (a merge or pull request); a word such as "yes" is not
            # a bool and a reader that took it as true would hide or invent a question, so the table is refused by name.
            raise TableError(f"{label}: kind `{entry['kind']}` has `is_change` {entry['is_change']!r}; it is true or false "
                             f"(a kind that is a change to the code); fix it in references/{label}")
        for rx in entry["path_regexes"]:
            try:
                compiled = re.compile(rx)
            except (re.error, TypeError):
                raise TableError(f"{label}: kind `{entry['kind']}` has a path regex that does not "
                                 f"compile: {rx!r}; fix it in references/{label}") from None
            # t-280 F7: a rule that only names a path marker is matched on the path SUFFIX. Anchored
            # at `^/`, a tracker behind a context path (`/jira/browse/ABC-5`) was kind `url` and its key
            # was swallowed. A rule that CAPTURES the project path (group 1 of a merge request) stays
            # anchored: the capture has to begin at the path start.
            if rx.startswith("^/") and compiled.groups == 0:
                raise TableError(f"{label}: key `path_regexes` of kind `{entry['kind']}` holds {rx!r}, which "
                                 "starts with `^/` and captures nothing: a path marker is matched on the path "
                                 "suffix, so write it as `(?:^|/)<marker>/` (for example `(?:^|/)browse/`) in "
                                 f"references/{label}")
            if entry["kind"] == "ticket" and compiled.groups:
                raise TableError(f"{label}: key `path_regexes` of kind `ticket` holds {rx!r}, which has a "
                                 "capture group: a ticket rule names only the path marker "
                                 "(`(?:^|/)browse/`) and the key shape is appended from ticket_light.KEY_RE, "
                                 f"so that the key is the one group; fix it in references/{label}")
    return table


def load_reference_kinds(path: Path | None = None) -> dict:
    """references/reference-kinds.json, validated. Refuses (TableError) when missing or malformed."""
    path = Path(path or KINDS_TABLE_PATH)
    return check_reference_kinds(_load_table(path, path.name), path.name)


def change_kinds(path: Path | None = None) -> set:
    """The kinds of reference that ARE a change to the code (`is_change: true` in reference-kinds.json): the ONE reader (AR-13), used
    by the driver's no-change question (SS1-13). A kind without the field is not a change. The table unreadable or damaged raises
    `TableError` (the caller decides what a table it cannot read means; the driver's answer is "no question")."""
    return {entry["kind"] for entry in load_reference_kinds(path)["kinds"] if entry.get("is_change") is True}


# ---------------------------------------------------------------------------------------------
# Text helpers: ADF flattening (with list markers) and a line splitter that keeps U+2028 whole
# ---------------------------------------------------------------------------------------------

def split_lines(text: str) -> list[str]:
    """Lines of a text on CRLF, CR and LF only. `str.splitlines()` also splits on U+2028, U+2029,
    U+0085, form feed and others, which would cut a comment or an item in the middle (C7)."""
    return re.split(r"\r\n|\r|\n", text or "")


def _adf_inline(node) -> str:
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return "".join(_adf_inline(item) for item in node)
    if not isinstance(node, dict):
        return str(node)
    kind = node.get("type")
    attrs = node.get("attrs") or {}
    if kind == "text":
        text = str(node.get("text") or "")
        for mark in node.get("marks") or []:
            if isinstance(mark, dict) and mark.get("type") == "link":
                href = str((mark.get("attrs") or {}).get("href") or "")
                # the link target is a reference: dropping it would lose it from the light form
                if href and href not in text:
                    text = f"{text} ({href})"
        return text
    if kind == "hardBreak":
        return "\n"
    if kind == "mention":
        return str(attrs.get("text") or "")
    if kind == "emoji":
        return str(attrs.get("text") or attrs.get("shortName") or "")
    if kind == "inlineCard":
        return str(attrs.get("url") or "")
    return str(node.get("text") or "") + _adf_inline(node.get("content"))


def _adf_item(item, depth: int, marker: str) -> list[str]:
    head, nested = [], []
    for child in (item.get("content") or []) if isinstance(item, dict) else []:
        kind = child.get("type") if isinstance(child, dict) else None
        if kind in ("bulletList", "orderedList"):
            nested.extend(_adf_lines(child, depth + 1))
        else:
            text = " ".join(line.strip() for line in _adf_lines(child, depth) if line.strip())
            if text:
                head.append(text)
    return [("  " * depth) + marker + " ".join(head)] + nested


def _adf_lines(node, depth: int = 0) -> list[str]:
    if node is None:
        return []
    if isinstance(node, str):
        return split_lines(node)
    if isinstance(node, list):
        out: list[str] = []
        for child in node:
            out.extend(_adf_lines(child, depth))
        return out
    if not isinstance(node, dict):
        return [str(node)]
    kind = node.get("type")
    content = node.get("content") or []
    attrs = node.get("attrs") or {}
    if kind in ("bulletList", "orderedList"):
        number = int(attrs.get("order") or 1) if kind == "orderedList" else 0
        lines: list[str] = []
        for item in content:
            marker = "* " if kind == "bulletList" else f"{number}. "
            number += 1
            lines.extend(_adf_item(item, depth, marker))
        return lines
    if kind == "heading":
        return [f"h{int(attrs.get('level') or 1)}. " + _adf_inline(content).strip()]
    if kind == "rule":
        return ["----"]
    if kind == "tableRow":
        return [" | ".join(" ".join(line.strip() for line in _adf_lines(cell, depth)) for cell in content)]
    if kind in ("paragraph", "codeBlock", "text", "mention", "emoji", "inlineCard", "hardBreak"):
        return split_lines(_adf_inline(node))
    # doc, blockquote, panel, table, anything unknown: its children are blocks, blank line between
    blocks = []
    for child in content:
        lines = _adf_lines(child, depth)
        if lines:
            blocks.append(lines)
    if not blocks and node.get("text"):
        return split_lines(str(node["text"]))
    out = []
    for index, lines in enumerate(blocks):
        if index and kind in ("doc", "blockquote", "panel"):
            out.append("")
        out.extend(lines)
    return out


def flatten_adf(node) -> str:
    """Jira v3 ADF as text, with list markers kept (`* ` bullets, `1. ` numbers, two-space nesting)
    and headings as `hN. `: source_inventory._text drops the markers, and with them every list
    item an acceptance-criteria section is made of (C2). Link targets stay, in brackets. A document
    nested past the interpreter's recursion limit does not crash and does not lose its words: they
    come back one per line, markers lost, in document order."""
    try:
        return "\n".join(_adf_lines(node))
    except RecursionError:
        words, stack = [], [node]
        while stack:
            current = stack.pop()
            if isinstance(current, dict):
                if isinstance(current.get("text"), str):
                    words.append(current["text"])
                if isinstance(current.get("content"), list):
                    stack.extend(reversed(current["content"]))
            elif isinstance(current, list):
                stack.extend(reversed(current))
            elif isinstance(current, str):
                words.append(current)
        return "\n".join(words)


def text_of(value) -> str:
    """A field value as plain text: a string as it is, ADF flattened, a list joined by lines."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(filter(None, (text_of(item) for item in value)))
    if isinstance(value, dict):
        if "content" in value or value.get("type") in ("doc", "paragraph"):
            return flatten_adf(value)
        return str(value.get("value") or value.get("name") or "")
    return str(value)


# ---------------------------------------------------------------------------------------------
# Acceptance criteria
# ---------------------------------------------------------------------------------------------

# `(\S.*)` and a later .strip(), not `(.+?)\s*$`: the lazy form is quadratic on a long line with inner
# runs of spaces, and a ticket description is text nobody vetted.
_ITEM_WIKI = re.compile(r"^\s*(?:[*\-#•]+|\d+[.)])\s+(\S.*)$")
_ITEM_MARKDOWN = re.compile(r"^\s*(?:[*\-+•]+|\d+[.)])\s+(\S.*)$")
_H_WIKI = re.compile(r"^h[1-6]\.\s*")
_H_MARKDOWN = re.compile(r"^#{1,6}\s+")
_BOLD_OPEN = re.compile(r"^(?:\*\*|__|\*|_)(?=\S)")
MARKUPS = ("wiki", "markdown", "adf")


def _heading_text(line: str, markup: str) -> str | None:
    """A line reduced to its heading words, or None for a blank line. `h3. *Acceptance Criteria:*`,
    `**What needs to be tested**`, `Acceptance Criteria:` and (markdown only) `## AC` all reduce to
    the same casefolded words. In wiki and ADF `# ` is a NUMBERED LIST ITEM, never a heading (C2),
    so `# Acceptance Criteria` stays an item there."""
    text = line.strip()
    if not text:
        return None
    match = _H_WIKI.match(text)
    if match:
        text = text[match.end():]
    elif markup == "markdown":
        match = _H_MARKDOWN.match(text)
        if match:
            text = text[match.end():]
    bold = _BOLD_OPEN.match(text)
    if bold:
        text = text[bold.end():]
    text = text.rstrip(" \t\r\n\f\v:*_")
    return " ".join(text.split()).casefold()


def _is_heading(line: str, markup: str) -> bool:
    text = line.strip()
    if re.match(r"^h[1-6]\.\s+\S", text):
        return True
    return markup == "markdown" and bool(re.match(r"^#{1,6}\s+\S", text))


def _norm_names(names, what: str, *, nonempty: bool) -> set:
    if not isinstance(names, (list, tuple, set)) or not all(isinstance(n, str) for n in names):
        raise TableError(f"{what} must be a list of strings, got {type(names).__name__}; pass the "
                         "list from references/jira-fields.json (plus the project's own, if any)")
    out = {" ".join(str(n).strip().rstrip(":").split()).casefold() for n in names if str(n).strip()}
    if nonempty and not out:
        raise TableError(f"{what} is empty: no heading could be recognised, so every ticket would "
                         "silently read as having no acceptance criteria; pass the list from "
                         "references/jira-fields.json")
    return out


def _field_items(value) -> list[str]:
    """The criteria of a configured acceptance field: one item per non-empty line, a list marker
    removed so the shape is the same as the heading route's."""
    items = []
    for line in split_lines(text_of(value)):
        if not line.strip():
            continue
        match = _ITEM_WIKI.match(line)
        items.append(match.group(1).strip() if match else line.strip())
    return items


def _heading_level(line: str, markup: str) -> int | None:
    """The level of a heading LINE (`h3.` and, in markdown, `###` are 3), or None for a line that is a
    heading only by its words (`Acceptance Criteria:`, `**AC**`): such a heading has no level, so the
    next heading of ANY level ends its section."""
    text = line.strip()
    match = re.match(r"^h([1-6])\.\s+\S", text)
    if match:
        return int(match.group(1))
    if markup == "markdown":
        match = re.match(r"^(#{1,6})\s+\S", text)
        if match:
            return len(match.group(1))
    return None


def _section_content(lines: list, index: int, markup: str, heads: set, sections: set) -> list[str]:
    """The non-blank lines from the heading at `index` to the END of its section, whatever they are
    (items, prose, a table): the end is the next heading of the SAME or a higher level (any heading
    when this one has no level), another criteria heading, a line equal to one of `sections`, or the end
    of the text. NOT the item loop's end - that stops at the first paragraph and would read a section
    of prose as empty (t-957 F-1)."""
    level = _heading_level(lines[index], markup)
    content: list[str] = []
    for position in range(index + 1, len(lines)):       # an index walk, not a slice: many headings must not make it quadratic
        line = lines[position]
        if not line.strip():
            continue
        words = _heading_text(line, markup)
        if words in sections:
            break
        if _is_heading(line, markup):
            deeper = _heading_level(line, markup)
            if level is None or deeper is None or deeper <= level:
                break
        elif words in heads:
            break
        content.append(line.strip())
    return content


def criteria_section(description, *, headings, section_names, markup: str = "wiki") -> dict:
    """The criteria SECTIONS of a description, and what the item reader made of the first: the one scanner
    of the criteria heading (`acceptance_criteria` delegates here, so S0 and the snapshots never disagree
    on where a section is).

    Every line equal to a heading of `headings` is a section; `sections` lists them all, in text order, as
    `{"heading": <the line as written>, "content_lines": <non-blank lines up to the section's end, see
    `_section_content`>, "first_line": <the first of them or "">}`. `heading` / `content_lines` /
    `first_line` are those of the first section that HAS content, else of the first section, else
    None / 0 / "". `items` are the criteria the item reader takes from the FIRST section (what
    `acceptance_criteria` has always returned). A section with content and no items is a criteria heading
    whose section the reader could not read; one with no content is an empty template (D-0050)."""
    if markup not in MARKUPS:
        raise ValueError(f"markup must be one of {', '.join(MARKUPS)}, got {markup!r}")
    heads = _norm_names(headings, "acceptance headings", nonempty=True)
    sections = _norm_names(section_names, "section names", nonempty=False)
    if isinstance(description, dict):
        markup = "adf"
    lines = split_lines(text_of(description))
    starts = [i for i, line in enumerate(lines) if _heading_text(line, markup) in heads]
    found = []
    for index in starts:
        content = _section_content(lines, index, markup, heads, sections)
        found.append({"heading": lines[index].strip(), "content_lines": len(content),
                      "first_line": content[0] if content else ""})
    chosen = next((s for s in found if s["content_lines"]), found[0] if found else None)
    out = {"heading": chosen["heading"] if chosen else None,
           "content_lines": chosen["content_lines"] if chosen else 0,
           "first_line": chosen["first_line"] if chosen else "",
           "items": [], "sections": found}
    if not starts:
        return out
    item_re = _ITEM_MARKDOWN if markup == "markdown" else _ITEM_WIKI
    items: list[str] = out["items"]
    seen_blank = False
    for line in lines[starts[0] + 1:]:
        if not line.strip():
            seen_blank = True
            continue
        if _heading_text(line, markup) in sections or _is_heading(line, markup):
            break
        match = item_re.match(line)
        if match:
            items.append(match.group(1).strip())
            seen_blank = False
        elif line[0] in " \t":
            continue
        elif seen_blank:
            break
        elif items:
            items[-1] = items[-1] + " " + line.strip()
    return out


def acceptance_criteria(description, *, acceptance_field_value=None, headings, section_names,
                        markup: str = "wiki") -> list[str]:
    """The acceptance criteria of a ticket, as a list; `[]` when it has none (the caller goes on without
    them, or - when `criteria_section` finds a section it read nothing from - stops, S0; a criterion is
    never invented).

    Precedence (F8): a non-empty configured field first. Otherwise the description section under a
    heading from `headings` (a whole line, markup and a trailing colon allowed). The section runs
    over list items; a non-item line directly after an item continues it; the section ENDS at
      * the first non-item, non-indented line after a blank line, or
      * a line equal to one of `section_names` (case-insensitive, trailing colon allowed), or
      * a heading line (`hN.`; in markdown also `#`).
    A non-item, non-indented line after a blank line ends the section even when no item was seen:
    a paragraph after the heading yields `[]` rather than the next section's list (a false
    criterion is worse than the loss `criteria_section` makes visible). `markup`: `wiki` (Jira api v2
    string, `# ` is an item), `markdown` (a pasted ticket, `# ` is a heading) or `adf` (a dict
    description, flattened first)."""
    if markup not in MARKUPS:
        raise ValueError(f"markup must be one of {', '.join(MARKUPS)}, got {markup!r}")
    _norm_names(headings, "acceptance headings", nonempty=True)
    _norm_names(section_names, "section names", nonempty=False)
    field = _field_items(acceptance_field_value)
    if field:
        return field
    return criteria_section(description, headings=headings, section_names=section_names, markup=markup)["items"]


# ---------------------------------------------------------------------------------------------
# Comments: one line each, id first, reversible
# ---------------------------------------------------------------------------------------------

def escape_text(value: str) -> str:
    """Backslash FIRST, then CR, LF, U+2028, U+2029, U+0085 - so the line view is one physical
    line per comment and the text comes back byte for byte (C7)."""
    value = str(value if value is not None else "")
    for raw, esc in ((BS, BS + BS), ("\r", BS + "r"), ("\n", BS + "n"), (LS, BS + "u2028"),
                     (PS, BS + "u2029"), (NEL, BS + "u0085")):
        value = value.replace(raw, esc)
    return value


def unescape_text(value: str) -> str:
    out, i, n = [], 0, len(value)
    while i < n:
        ch = value[i]
        if ch == BS and i + 1 < n:
            nxt = value[i + 1]
            if nxt == BS:
                out.append(BS)
                i += 2
                continue
            if nxt == "r":
                out.append("\r")
                i += 2
                continue
            if nxt == "n":
                out.append("\n")
                i += 2
                continue
            if nxt == "u" and value[i + 2:i + 6] in ("2028", "2029", "0085", "00b7"):
                out.append(chr(int(value[i + 2:i + 6], 16)))
                i += 6
                continue
        out.append(ch)
        i += 1
    return "".join(out)


def _head_field(value) -> str:
    # id, created and author sit before the text: a middle dot there would be read as a separator
    return escape_text(value).replace(MID_DOT, BS + "u00b7")


def _comment_tuple(comment: dict) -> tuple:
    created = comment.get("created") if comment.get("created") is not None else comment.get("date")
    text = comment.get("text") if comment.get("text") is not None else comment.get("body")
    return (str(comment.get("id") if comment.get("id") is not None else ""), str(created or ""),
            str(comment.get("author") or ""), str(text or ""))


def comment_lines(comments) -> str:
    """`<id> · <created> · <author> · <text>`, one physical line per comment, the id first so a
    role can name a comment by it. A null author is written empty. Lines are joined by LF only."""
    lines = []
    for comment in comments or []:
        cid, created, author, text = _comment_tuple(comment)
        lines.append(SEP.join((_head_field(cid), _head_field(created), _head_field(author),
                               escape_text(text))))
    return "\n".join(lines)


def parse_comment_lines(text: str) -> list[tuple]:
    """The tuples `(id, created, author, text)` a line view holds, in order. Splits on LF only
    (never `splitlines()`) and cuts at the first three separators, so a text with ` · ` is whole."""
    out = []
    for line in (text or "").split("\n"):
        line = line.rstrip("\r")
        if not line.strip():
            continue
        parts = line.split(SEP, 3)
        if len(parts) == 3 and parts[2].endswith(" " + MID_DOT):
            parts = [parts[0], parts[1], parts[2][:-2], ""]
        if len(parts) != 4:
            raise ValueError("a comment line is not `<id> | <created> | <author> | <text>` (with the "
                             f"middle-dot separator): {line[:80]!r}")
        out.append(tuple(unescape_text(part) for part in parts))
    return out


def verify_comment_lines(comments, text: str) -> list[str]:
    """Problems between the comments and their line view, each naming the comment id; `[]` when
    every id appears once, in order, with its created, author and text."""
    expected = [_comment_tuple(c) for c in comments or []]
    try:
        got = parse_comment_lines(text)
    except ValueError as exc:
        return [str(exc)]
    problems = []
    got_ids = [row[0] for row in got]
    for row in expected:
        if got_ids.count(row[0]) == 0:
            problems.append(f"comment {row[0]} is missing from the line view")
        elif got_ids.count(row[0]) > 1:
            problems.append(f"comment {row[0]} appears {got_ids.count(row[0])} times in the line view")
    if not problems and [row[0] for row in expected] != got_ids:
        problems.append("the line view holds the comments in a different order than the ticket")
    if not problems:
        for want, have in zip(expected, got):
            for name, a, b in zip(("id", "created", "author", "text"), want, have):
                if a != b:
                    problems.append(f"comment {want[0]}: {name} differs in the line view")
    return problems


# ---------------------------------------------------------------------------------------------
# The projection
# ---------------------------------------------------------------------------------------------

def _is_empty(value) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, tuple, dict, set)):
        return len(value) == 0
    return False


def _is_user(value: dict) -> bool:
    return any(k in value for k in ("displayName", "accountId", "emailAddress"))


def strip_noise(value, table: dict):
    """The noise blacklist applied recursively to a nested value. A name with a scope entry in
    `noise_scope` is dropped only there: `id` from nested objects, `key` from user objects."""
    noise = set(table.get("noise") or [])
    scope = table.get("noise_scope") or {}

    def walk(node):
        if isinstance(node, dict):
            user = _is_user(node)
            out = {}
            for name, child in node.items():
                if name in noise:
                    how = scope.get(name, "any")
                    if how in ("any", "nested") or (how == "user" and user):
                        continue
                out[name] = walk(child)
            return out
        if isinstance(node, list):
            return [walk(child) for child in node]
        return node

    return walk(value)


def _light_value(value, table: dict):
    """A custom field's value in light form; `None` when it is empty. An option object becomes
    its `value`, else its `name`; a user object its `displayName`; ADF becomes text; anything else
    keeps its shape minus the noise. A value that turns empty after this is empty (never kept)."""
    if _is_empty(value):
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return value
    if isinstance(value, list):
        items = [light for light in (_light_value(item, table) for item in value) if light is not None]
        return items or None
    if isinstance(value, dict):
        if "content" in value and value.get("type") == "doc":
            return text_of(value) or None
        if not _is_empty(value.get("value")) and not isinstance(value.get("value"), (dict, list)):
            head = value["value"]
            child = _light_value(value.get("child"), table) if "child" in value else None
            return {"value": head, "child": child} if child is not None else head
        if not _is_empty(value.get("displayName")):
            return value["displayName"]
        if not _is_empty(value.get("name")):
            return value["name"]
        cleaned = strip_noise(value, table)
        kept = {k: light for k, light in ((k, _light_value(v, table)) for k, v in cleaned.items())
                if light is not None}
        return kept or None
    return str(value)


def _id_list(value, what: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, (list, tuple)) or not all(isinstance(v, str) for v in value):
        raise TableError(f"{what} must be a list of custom-field ids (strings), got "
                         f"{type(value).__name__}; fix it in qa-factory/config.json")
    return [v.strip() for v in value if v.strip()]


def _name_of(value) -> str:
    return str((value or {}).get("name") or "") if isinstance(value, dict) else ""


def _person(value) -> str | None:
    if isinstance(value, dict):
        return value.get("displayName") or None
    return None


def project(raw_issue: dict, *, fields_table: dict, config_custom_fields, acceptance_fields,
            acceptance_headings, section_names, epic_fields=(), remote_links=None) -> dict:
    """One raw Jira issue (`fields=*all`) as the light snapshot a role reads.

    Keeps SCHEMA_KEYS and the `links` dict shape (`merge_request`, `branch`, `issue_links`,
    `remote_links`) that `brief_pack.snapshot_mask_lines` and `stage_compare.s0` parse (FR-14).
    Dropped: every custom field the project did not name, every named one that is empty (None, "",
    [], {}, whitespace), and the noise keys of `jira-fields.json` at every depth of what is kept.
    `description` is whole, comments keep their `id`, attachments shrink to
    `{id, filename, size, mimeType}`, `updated` stays, once, as `revision`. Keys beyond SCHEMA_KEYS
    (labels, components, fix_versions, priority, reporter, assignee, custom_fields, fields_missing)
    are printed only when non-empty. A named custom field
    the issue does not carry at all is listed in `fields_missing`, never silently ignored.
    The caller puts EVERY comment page into `fields.comment.comments`; `remote_links` is the raw
    `/remotelink` answer (optional), `epic_fields` the ids of the Epic Link fields from `/field`
    (optional, only used to find a parent the classic way)."""
    table = check_fields_table(fields_table)
    if not isinstance(raw_issue, dict) or not isinstance(raw_issue.get("fields") or {}, dict):
        raise TableError("the raw issue is not a Jira issue object with a `fields` object; expected "
                         "the answer of GET /rest/api/<v>/issue/<KEY>?fields=*all")
    config_ids = _id_list(config_custom_fields, "direct_api.custom_fields")
    acceptance_ids = _id_list(acceptance_fields, "direct_api.acceptance_criteria_fields")
    epic_ids = _id_list(list(epic_fields or ()), "epic_fields")
    _norm_names(acceptance_headings, "acceptance headings", nonempty=True)
    standard = set(table["standard"])
    fields = raw_issue.get("fields") or {}

    raw_description = fields.get("description")
    description = text_of(raw_description)
    markup = "adf" if isinstance(raw_description, dict) else "wiki"
    field_values = [text_of(fields.get(fid)) for fid in acceptance_ids if not _is_empty(fields.get(fid))]
    criteria = acceptance_criteria(raw_description, acceptance_field_value=field_values or None,
                                   headings=acceptance_headings, section_names=section_names,
                                   markup=markup)

    parent = (fields.get("parent") or {}).get("key") if isinstance(fields.get("parent"), dict) else None
    if not parent:
        for fid in epic_ids:
            value = fields.get(fid)
            if isinstance(value, dict):
                value = value.get("key")
            if isinstance(value, str) and _STRICT_KEY_RE.fullmatch(value.strip()):
                parent = value.strip()
                break

    comments = []
    for comment in ((fields.get("comment") or {}).get("comments") or []) if isinstance(
            fields.get("comment"), dict) else []:
        if isinstance(comment, dict):
            comments.append({"id": comment.get("id"), "author": _person(comment.get("author")) or "",
                             "date": comment.get("created"), "text": text_of(comment.get("body"))})

    issue_links = []
    for link in fields.get("issuelinks") or []:
        if not isinstance(link, dict):
            continue
        other = link.get("outwardIssue") or link.get("inwardIssue") or {}
        kind = link.get("type") or {}
        relation = kind.get("outward") if link.get("outwardIssue") else kind.get("inward")
        if other.get("key"):
            other_fields = other.get("fields") or {}
            issue_links.append({"relation": relation or kind.get("name") or "", "type": kind.get("name") or "",
                                "key": other.get("key"), "summary": other_fields.get("summary") or "",
                                "status": _name_of(other_fields.get("status"))})

    remote = []
    for row in remote_links or []:
        obj = (row or {}).get("object") or {}
        if obj.get("url"):
            remote.append({"title": obj.get("title") or "", "url": obj.get("url")})
    merge_request = next((r["url"] for r in remote if "/merge_requests/" in r["url"] or "/pull/" in r["url"]), None)
    if not merge_request:
        found = re.search(r"https?://\S+/(?:merge_requests|pull)/\d+", description)
        merge_request = found.group(0) if found else None

    subtasks = [{"key": st.get("key"), "status": _name_of((st.get("fields") or {}).get("status")) or "unknown"}
                for st in fields.get("subtasks") or [] if isinstance(st, dict) and st.get("key")]
    attachments = [{"id": a.get("id"), "filename": a.get("filename"), "size": a.get("size"),
                    "mimeType": a.get("mimeType")}
                   for a in fields.get("attachment") or [] if isinstance(a, dict)]

    out = {
        "key": raw_issue.get("key"),
        "type": _name_of(fields.get("issuetype")),
        "status": _name_of(fields.get("status")),
        "title": fields.get("summary") or "",
        "description": description,
        "acceptance_criteria": criteria,
        "comments": comments,
        "parent": parent,
        "subtasks": subtasks,
        "links": {"merge_request": merge_request, "branch": None, "issue_links": issue_links,
                  "remote_links": remote},
        "id": raw_issue.get("id"),
        "attachments": attachments,
        # `updated` is carried here, once: a second copy of the same string is bytes a role pays for
        "revision": str(fields.get("updated") or raw_issue.get("version") or "unknown"),
    }
    # Beyond SCHEMA_KEYS an empty value is not printed (the owner's rule for custom fields, applied
    # to every extra): the light form is what a role pays for, and the raw keeps everything.
    extras = {}
    if "labels" in standard:
        extras["labels"] = [str(x) for x in fields.get("labels") or []]
    if "components" in standard:
        extras["components"] = [n for n in (_name_of(c) for c in fields.get("components") or []) if n]
    if "fixVersions" in standard:
        extras["fix_versions"] = [n for n in (_name_of(v) for v in fields.get("fixVersions") or []) if n]
    if "priority" in standard:
        extras["priority"] = _name_of(fields.get("priority"))
    if "reporter" in standard:
        extras["reporter"] = _person(fields.get("reporter"))
    if "assignee" in standard:
        extras["assignee"] = _person(fields.get("assignee"))

    custom, missing = {}, []
    for fid in dict.fromkeys(config_ids + acceptance_ids):
        if fid not in fields:
            missing.append(fid)
            continue
        light = _light_value(fields[fid], table)
        if light is not None:
            custom[fid] = light
    extras["custom_fields"] = custom
    extras["fields_missing"] = missing
    out.update({name: value for name, value in extras.items() if not _is_empty(value)})
    return out


def description_note(description: str, *, limit_bytes: int) -> str | None:
    """K14: one printed line when the description is longer than `limit_bytes` (UTF-8), else None.
    At the limit: no line; one byte over: one line. The description is never cut - the line only
    tells the person how big it is (P4)."""
    size = len((description or "").encode("utf-8", "surrogatepass"))
    if size <= limit_bytes:
        return None
    return (f"The ticket description is {size:,} bytes, over the {limit_bytes:,}-byte size at which it "
            "is called out. It is kept whole, nothing was cut.")


# ---------------------------------------------------------------------------------------------
# Own words and the person-vs-tracker comparison
# ---------------------------------------------------------------------------------------------

def own_words_share(snapshot) -> tuple[int, int, float]:
    """`(words_bytes, file_bytes, share)`: the UTF-8 bytes of the ticket's own words (title,
    description, the acceptance criteria joined by LF, every comment text) against the bytes of the
    snapshot file. A dict is measured as the adapter prints it (indent 2, no ASCII escaping, one
    trailing newline); bytes or a str are the file itself."""
    file_bytes_override = None
    if isinstance(snapshot, (bytes, bytearray)):
        file_bytes_override = len(snapshot)
        snapshot = json.loads(bytes(snapshot).decode("utf-8"))
    elif isinstance(snapshot, str):
        file_bytes_override = len(snapshot.encode("utf-8"))
        snapshot = json.loads(snapshot)
    ac = snapshot.get("acceptance_criteria")
    ac_text = "\n".join(str(x) for x in ac) if isinstance(ac, list) else str(ac or "")
    parts = [str(snapshot.get("title") or ""), str(snapshot.get("description") or ""), ac_text]
    parts += [str((c or {}).get("text") or "") for c in snapshot.get("comments") or [] if isinstance(c, dict)]
    words = sum(len(part.encode("utf-8", "surrogatepass")) for part in parts)
    size = file_bytes_override if file_bytes_override is not None else len(
        json.dumps(snapshot, indent=2, ensure_ascii=False).encode("utf-8", "surrogatepass")) + 1
    return words, size, (words / size if size else 0.0)


_WIKI_ESCAPE = re.compile(r"\\([\\{}\[\]()*_?|!#+.<>~^-])")


def _norm_text(value) -> str:
    """For comparing only (stored text stays verbatim): wiki escapes undone, CRLF as LF, runs of
    whitespace as one space."""
    text = _WIKI_ESCAPE.sub(r"\1", str(value or ""))
    return " ".join(text.replace("\r\n", "\n").split())


def _items(value) -> list[str]:
    if isinstance(value, list):
        return [str(v) for v in value if str(v).strip()]
    return [line for line in split_lines(str(value or "")) if line.strip()]


def compare_person_vs_rest(person_snapshot: dict, rest_snapshot: dict) -> dict:
    """The person's ticket text against what the tracker says now (FR-25). The PERSON's text is the
    requirement (P13/P20): the tracker is shown beside it as "the tracker now says", every
    difference lands in `disagreements[]`, and one line says so in plain words - printed whether or
    not anything differs. Wiki escapes are normalised before comparing (`\\{` equals `{`)."""
    person_snapshot, rest_snapshot = person_snapshot or {}, rest_snapshot or {}
    disagreements = []
    if _norm_text(person_snapshot.get("title")) != _norm_text(rest_snapshot.get("title")):
        disagreements.append({"field": "title", "person": person_snapshot.get("title") or "",
                              "rest": rest_snapshot.get("title") or ""})
    p_ac, r_ac = _items(person_snapshot.get("acceptance_criteria")), _items(rest_snapshot.get("acceptance_criteria"))
    p_norm, r_norm = [_norm_text(x) for x in p_ac], [_norm_text(x) for x in r_ac]
    if p_norm != r_norm:
        disagreements.append({"field": "acceptance_criteria", "person": len(p_ac), "rest": len(r_ac),
                              "only_in_person": [x for x, n in zip(p_ac, p_norm) if n not in r_norm],
                              "only_in_rest": [x for x, n in zip(r_ac, r_norm) if n not in p_norm]})
    p_count, r_count = len(person_snapshot.get("comments") or []), len(rest_snapshot.get("comments") or [])
    if p_count != r_count:
        disagreements.append({"field": "comments", "person": p_count, "rest": r_count})
    if _norm_text(person_snapshot.get("parent")) != _norm_text(rest_snapshot.get("parent")):
        disagreements.append({"field": "parent", "person": person_snapshot.get("parent") or "",
                              "rest": rest_snapshot.get("parent") or ""})
    words = {"title": "the title", "acceptance_criteria": "the acceptance criteria",
             "comments": "the number of comments", "parent": "the parent"}
    def detail(d):
        if d["field"] == "acceptance_criteria":
            return (f" ({len(d['only_in_person'])} only in the person's text, "
                    f"{len(d['only_in_rest'])} only on the tracker)")
        if d["field"] == "comments":
            return f" (the person's text has {d['person']}, the tracker {d['rest']})"
        return ""

    if disagreements:
        what = "; ".join(words[d["field"]] + detail(d) for d in disagreements)
        line = ("The person's text is the requirement for this story. The tracker now says something "
                f"different about: {what}. Nothing was changed; only a new word from the person "
                "switches the requirement.")
    else:
        line = ("The person's text is the requirement for this story. The tracker now says the same "
                "about the title, the acceptance criteria, the number of comments and the parent.")
    return {"authority": "person", "line": line, "disagreements": disagreements}


# ---------------------------------------------------------------------------------------------
# References
# ---------------------------------------------------------------------------------------------

_URL_RE = re.compile(r"https?://[^\s<>()\[\]\"'|]+")
_LOCAL_PATH_RE = re.compile(r"(?<![\w/.\\-])(?:~/[^\s,;\"'<>()\[\]|]+|[A-Za-z]:\\[^\s,;\"'<>()\[\]|]+)")
_ATTACHED_MR_RE = re.compile(r"(?<![\w.-])([A-Za-z0-9][\w.-]*)!(\d+)(?!\w)")
_PLAIN_MR_RE = re.compile(r"(?<![\w!])!(\d+)(?!\w)")
_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+(?:[-.][A-Za-z0-9_]+)*")
_TRAILING = ".,;:!?*"
MR_KINDS = ("merge_request", "pull_request")


def split_remote_identity(identity) -> tuple:
    """`(host, path)` of a repository's `remote_identity`: the scp form `git@host:group/name.git`
    or a URL. Not a URL parser - the scp form has no scheme and `urlsplit` reads its host as a
    scheme. `(None, None)` for an empty or unreadable value."""
    text = str(identity or "").strip()
    if not text:
        return None, None
    if "://" in text:
        parts = urlsplit(text)
        path = parts.path.strip("/")
        return (parts.hostname or None), (path[:-4] if path.endswith(".git") else path) or None
    match = re.match(r"^(?:[^@/\s]+@)?([^:/\s]{2,}):(?![\\/])(.+)$", text)
    if match:
        path = match.group(2).strip("/")
        return match.group(1).lower(), (path[:-4] if path.endswith(".git") else path) or None
    return None, None


def host_of(entry) -> str | None:
    """The host of a known-host entry: a bare host, a URL, or an scp-form remote."""
    text = str(entry or "").strip()
    if not text:
        return None
    if "://" in text:
        return (urlsplit(text).hostname or "").lower() or None
    host, _path = split_remote_identity(text)
    if host:
        return host
    return text.split("/")[0].split(":")[0].lower() or None


def _repo_index(repos) -> list[dict]:
    out = []
    for repo in repos or []:
        if not isinstance(repo, dict) or not repo.get("repo_id"):
            continue
        host, path = split_remote_identity(repo.get("remote_identity"))
        names = set()
        if path:
            names.add(path.rsplit("/", 1)[-1].casefold())
        local = str(repo.get("local_path") or "").replace(BS, "/").rstrip("/")
        if local:
            names.add(local.rsplit("/", 1)[-1].casefold())
        out.append({"repo_id": str(repo["repo_id"]), "names": names, "path": (path or "").casefold()})
    return out


def _compile_kinds(reference_kinds: dict, key_re=None) -> list[tuple]:
    """The kinds as `(kind, hosts, compiled path regexes)`. A ticket rule names only the path marker in
    the data file; the key shape is APPENDED here from `KEY_RE` (or the caller's `key_re`), so the key has
    one source and is group 1 (t-280 F7)."""
    check_reference_kinds(reference_kinds)
    key = (key_re or KEY_RE).pattern
    return [(e["kind"], [h.lower() for h in e.get("hosts") or []],
             [re.compile(rx + key if e["kind"] == "ticket" else rx) for rx in e["path_regexes"]])
            for e in reference_kinds["kinds"]]


def ticket_url_regex(reference_kinds: dict | None = None, key_re=None):
    """The regex that finds `<ticket path marker><KEY>` in a text - the table's ticket rules joined, then
    the key shape - group 1 is the key. `source_inventory` builds its `/browse/KEY` finder from this, so the
    kind rule and that finder cannot disagree (t-280 F7: one source, FR-13 and FR-17)."""
    table = check_reference_kinds(reference_kinds if reference_kinds is not None else load_reference_kinds())
    markers = [rx for e in table["kinds"] if e["kind"] == "ticket" for rx in e["path_regexes"]]
    if not markers:
        raise TableError("reference-kinds.json: no entry of `kinds` has kind `ticket`, so no tracker link can "
                         "be read as a ticket; restore it in references/reference-kinds.json")
    return re.compile("(?:" + "|".join(markers) + ")" + (key_re or KEY_RE).pattern)


def _classify_url(url: str, kinds: list[tuple]) -> tuple:
    parts = urlsplit(url)
    host, path = (parts.hostname or "").lower(), parts.path
    for kind, hosts, regexes in kinds:
        if hosts and not any(host == h or host.endswith("." + h) for h in hosts):
            continue
        for rx in regexes:
            match = rx.search(path)
            if match:
                return kind, host, match
    return "url", host, None


def classify_url(url: str, kinds: list | None = None) -> tuple:
    """`(kind, host, match)` of one link against the reference kinds (reference-kinds.json, or the compiled
    `kinds` a caller already holds): the kind's own path rule is matched against the URL's PATH only, so a
    merge-request path inside a query string is no merge request. `match` is the rule's match object (group 1
    the project path and group 2 the number of a merge or pull request) or None for kind `url`. A link that
    cannot be parsed is kind `url`: the error direction of every caller is toward "not a request"."""
    compiled = kinds if kinds is not None else _compile_kinds(load_reference_kinds())
    try:
        return _classify_url(str(url or ""), compiled)
    except ValueError:
        return "url", "", None


def prefix_of(key: str) -> str:
    return key.rsplit("-", 1)[0]


def references(texts: dict, *, known_prefixes, not_tracker_prefixes, key_form=None, reference_kinds: dict,
               known_hosts, repos, seeded=None, own_key: str | None = None) -> list[dict]:
    """Every reference the texts carry, as rows `{ref, kind, origins[], status}` (+ `repo_id`,
    `repo`, `matched_token`, `prefix_known`, and `key` on a ticket LINK of a host the project does not
    know, where they apply). Nothing present in a text vanishes:
    a reference is either fetchable (`not_fetched:not read yet`, for the S1 machinery to read and
    settle) or listed for the person (FR-41).

    `texts` maps an ORIGIN (`mention:summary`, `mention:description`, `mention:comment:<id>`,
    `mention:attachment:<name>`) to its text; `seeded` are rows the caller already knows from typed
    fields (`{"ref": "TP1-14482", "origins": ["field:parent"]}`). Order of work per text: URLs
    are classified and CONSUMED, then local paths, then `!NNN` merge requests, and only then keys -
    so a key inside a URL path or a path is never a candidate. `key_form` is the project's key shape
    (`adapter_forms.key_form`; none = the default Jira form, uppercase only): under a prefix-less form
    (bare numbers) only the form's mentions - `#123`, `Ticket: 123`, ... - are candidates, a ticket has
    no project prefix to probe (`prefix_known` is True), no row is tagged `other_project` and the
    not-tracker prefixes are not consulted.
    Statuses: a link on a host the project does not know, and a merge request named only in
    comments, are `person`; a local path is `not_fetched:local path mention`; the rest
    `not_fetched:not read yet`. `other_project` is an ORIGIN tag on a ticket whose prefix is not the
    prefix of `own_key`; `prefix_known` says whether the prefix needs a per-prefix probe."""
    if key_form is None and FORMS_DAMAGE:
        raise TableError(FORMS_DAMAGE)  # the floor still reads keys elsewhere; this reader says what is damaged
    form = key_form or _DEFAULT_FORM
    prefixed = form.prefixed
    kinds = _compile_kinds(reference_kinds, form.link_key)
    known_pref = {str(p).upper() for p in known_prefixes or []}
    not_tracker = {str(p).upper() for p in not_tracker_prefixes or []}
    hosts = {h for h in (host_of(e) for e in known_hosts or []) if h}
    repo_rows = _repo_index(repos)
    own_prefix = prefix_of(own_key) if own_key and prefixed else None
    rows: dict = {}

    def row_for(identity, ref, kind, host_known=True, **extra):
        row = rows.get(identity)
        if row is None:
            row = rows[identity] = {"ref": ref, "kind": kind, "origins": [], "_host_known": host_known}
        for name, value in extra.items():
            row.setdefault(name, value)
        return row

    def add_origin(row, origin):
        if origin not in row["origins"]:
            row["origins"].append(origin)

    def add_ticket(key, origin):
        if key == own_key:
            return
        row = row_for(("ticket", key), key, "ticket",
                      prefix_known=not prefixed or prefix_of(key).upper() in known_pref)
        add_origin(row, origin)
        if own_prefix and prefix_of(key) != own_prefix:
            add_origin(row, "other_project")

    def repo_by_path(path):
        """The repository a merge-request URL's project path belongs to: the repo whose `remote_identity` path is
        that path, whole. When none is (t-287 item 4: a repo recorded by its `local_path` only has no remote path,
        and a group that was renamed or moved is another path for the same repo), the LAST segment of the URL's path
        is matched against the repos' names - the same names a `testproject1-ui!1924` mention is tied by - and a repo is
        taken only when exactly ONE has that name: two of them, or none, leave the link a row of its own (a merge
        request is never tied to a repository the text does not name)."""
        wanted = str(path or "").strip("/").casefold()
        exact = next((r for r in repo_rows if r["path"] and r["path"] == wanted), None)
        if exact or not wanted:
            return exact
        named = [r for r in repo_rows if wanted.rsplit("/", 1)[-1] in r["names"]]
        return named[0] if len(named) == 1 else None

    for seed in seeded or []:
        ref = str((seed or {}).get("ref") or "").strip()
        if not ref:
            continue
        if form.strict.fullmatch(ref):
            for origin in seed.get("origins") or []:
                add_ticket(ref, origin)
        else:
            row = row_for(("seed", ref), ref, seed.get("kind") or "url")
            for origin in seed.get("origins") or []:
                add_origin(row, origin)

    for origin, raw_text in (texts or {}).items():
        text = str(raw_text or "")

        def take_url(match):
            url = match.group(0).rstrip(_TRAILING)
            kind, host, found = _classify_url(url, kinds)
            host_known = host in hosts
            if kind == "ticket" and found:
                if host_known:
                    add_ticket(found.group(1), origin)
                    return " " * len(match.group(0))
                # a ticket link on a host the project does not know: listed for the person, and it
                # CARRIES its key, so the one extractor (`source_inventory.extract_ticket_keys`) still
                # reports the key the link names (t-280 class: URLs are consumed before keys)
                row = row_for(("url", url), url, "ticket", False, key=found.group(1))
            elif kind in MR_KINDS and found:
                repo = repo_by_path(found.group(1))
                identity = ("mr", repo["repo_id"] if repo else f"{host}/{found.group(1)}".casefold(), found.group(2))
                row = row_for(identity, url, kind, host_known, _iid=found.group(2))
                if repo:
                    row.setdefault("repo_id", repo["repo_id"])
                if row["ref"] != url and not row["ref"].startswith("http"):
                    row["ref"] = url
            else:
                row = row_for((kind, host, urlsplit(url).path.rstrip("/").casefold(), urlsplit(url).query), url, kind, host_known)
            add_origin(row, origin)
            return " " * len(match.group(0))

        text = _URL_RE.sub(take_url, text)

        def take_path(match):
            path = match.group(0).rstrip(_TRAILING)
            add_origin(row_for(("path", path), path, "local_path"), origin)
            return " " * len(match.group(0))

        text = _LOCAL_PATH_RE.sub(take_path, text)

        def take_attached(match):
            token, iid = match.group(1), match.group(2)
            # t-363 B4 (B-256 c): ONE rule with the URL form (`repo_by_path`): a name is a repository only when
            # EXACTLY ONE attached repository has it. Two or more with one basename (compared case-insensitively:
            # `Testproject1-UI` and `testproject1-ui` are one name on Windows) used to resolve to the first, silently, and a
            # merge request was tied to a repository the text never named; now the row is `ambiguous`, names every
            # candidate by its path and says the door. A repository listed twice under one `repo_id` is one.
            matches = list({r["repo_id"]: r for r in repo_rows if token.casefold() in r["names"]}.values())
            repo = matches[0] if len(matches) == 1 else None
            if len(matches) > 1:
                recorded = {str(r.get("repo_id")): r for r in repos or [] if isinstance(r, dict)}
                paths = [str((recorded.get(m["repo_id"]) or {}).get("local_path")
                             or (recorded.get(m["repo_id"]) or {}).get("remote_identity") or m["repo_id"])
                         for m in matches]
                # t-373 F5: the NAME is part of the identity - two ambiguous names with one merge request number are two
                # rows, each with its own candidates. `refusal` is the line `brief_pack.reference_gap_lines` prints (F6);
                # `_candidate_ids` keeps the post-pass from merging the row into a repository outside them (F4).
                count = {2: "two", 3: "three"}.get(len(paths), str(len(paths)))
                row = row_for(("mr", "ambiguous", iid, token.casefold()), "!" + iid, "merge_request", repo="ambiguous",
                              matched_token=token, _iid=iid, candidates=paths,
                              _candidate_ids={m["repo_id"] for m in matches},
                              refusal=(f"{count} repositories carry this name: {'; '.join(paths)}; "
                                       "name the repository by its path or URL"))
            elif repo:
                row = row_for(("mr", repo["repo_id"], iid), "!" + iid, "merge_request", repo_id=repo["repo_id"],
                              matched_token=token, _iid=iid)
            else:
                row = row_for(("mr", "?", iid), "!" + iid, "merge_request", repo="unknown", matched_token=token,
                              _iid=iid)
            add_origin(row, origin)
            return " " * len(match.group(0))

        text = _ATTACHED_MR_RE.sub(take_attached, text)

        lines = split_lines(text)

        def tokens_of(chunk):
            hits = {}
            for token in _TOKEN_RE.findall(chunk):
                for repo in repo_rows:
                    if token.casefold() in repo["names"]:
                        hits.setdefault(repo["repo_id"], token)
            return hits

        for index, line in enumerate(lines):
            for match in _PLAIN_MR_RE.finditer(line):
                iid = match.group(1)
                hits = tokens_of(line)
                if not hits:
                    low, high = index, index
                    while low > 0 and lines[low - 1].strip():
                        low -= 1
                    while high + 1 < len(lines) and lines[high + 1].strip():
                        high += 1
                    hits = tokens_of("\n".join(lines[low:high + 1]))
                if len(hits) == 1:
                    (rid, token), = hits.items()
                    row = row_for(("mr", rid, iid), "!" + iid, "merge_request", repo_id=rid, matched_token=token,
                                  _iid=iid)
                elif hits:
                    row = row_for(("mr", "ambiguous", iid), "!" + iid, "merge_request", repo="ambiguous", _iid=iid)
                else:
                    row = row_for(("mr", "?", iid), "!" + iid, "merge_request", repo="unknown", _iid=iid)
                add_origin(row, origin)

        for key in AF.form_keys(text, form):
            if (prefixed and prefix_of(key).upper() in not_tracker) or key == own_key:
                continue
            add_ticket(key, origin)

    # A bare `!NNN` that no repo token ties (the same MR named again further down, in a paragraph
    # of its own) is the MR some other mention DID tie, when exactly one tied row has that number:
    # one merge request is one row. With two tied rows of that number it stays a row of its own.
    tied = {}
    for row in rows.values():
        if row["kind"] in MR_KINDS and row.get("repo_id"):
            tied.setdefault(row.get("_iid"), []).append(row)
    for identity, row in list(rows.items()):
        if row["kind"] == "merge_request" and "repo_id" not in row and row.get("repo") in ("unknown", "ambiguous"):
            candidates = tied.get(row.get("_iid"), [])
            # t-373 F4: a row that names its candidate repositories is never merged into a tied row OUTSIDE them - the
            # merge would drop the refusal and credit the mention to a repository the text never named
            named = row.get("_candidate_ids")
            if len(candidates) == 1 and (not named or candidates[0].get("repo_id") in named):
                for origin in row["origins"]:
                    add_origin(candidates[0], origin)
                del rows[identity]

    out = []
    for row in rows.values():
        row.pop("_iid", None)
        row.pop("_candidate_ids", None)
        host_known = row.pop("_host_known")
        comment_only = bool(row["origins"]) and all(o.startswith("mention:comment:") for o in row["origins"])
        if row["kind"] == "local_path":
            status = "not_fetched:local path mention"
        elif not host_known or (row["kind"] in MR_KINDS and comment_only):
            status = "person"
        else:
            status = "not_fetched:not read yet"
        row["status"] = status
        out.append(row)
    return out


def prefixes_to_probe(rows: list[dict]) -> list[str]:
    """Prefixes of ticket rows whose prefix the run does not know yet: one per-prefix probe each
    (never one per key). The decoy `TC-001` of TP1-15045 costs one."""
    return sorted({prefix_of(r["ref"]).upper() for r in rows if r.get("kind") == "ticket"
                   and _STRICT_KEY_RE.fullmatch(r["ref"]) and not r.get("prefix_known", True)})
