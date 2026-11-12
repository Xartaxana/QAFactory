#!/usr/bin/env python3
"""Where each section of a big artifact lies, as a map a role reads without a shell (SC1-3 part 2).

`work/grounding.yaml` (a live one: 4,883 lines) and `work/test-plan.json` (1,120 lines) are far past what a whole `Read` is
allowed to return, and a role that cannot see where a section ends reads windows by guess - the same area up to six times
(TP1-12586). This module is the ONE place that says which lines hold which section:

- `plan_row_spans(text)`: the bytes and the lines of every row of a plan, found STRUCTURALLY (`json.JSONDecoder.raw_decode` at
  each element of the rows array). The old way - find `"id": "TS-3"`, then the `{` before it - named the bytes of a nested
  object when the row carried one before its `id`, and of an earlier row's nested object when that one carried the same `id`;
  a `--set` then wrote over those bytes.
- `section_map_text(path, kind)`: the map `id first-last` of an artifact, for the guard's refusal and for the two CLIs
  (`plan_row.py --map`, `grounding_section.py --map`). Line numbers are 1-based, the number `Read offset` takes.

The error direction of every function here is one: NO map (an empty string, a raised ValueError for the span function), never a
wrong one. A map that points at other lines is worse than none, because the role reads them and then edits exactly those. So
the map is checked against the file before it is returned: the lines come from the grounding table's one reader and its
self-checked spans, the plan's rows are compared with an independent parse of the same bytes, and a file that changes while
the map is being built gives no map. This module reads and writes nothing else; it is a library, with no command line.
"""
from __future__ import annotations

import bisect
import json
import os
from pathlib import Path

import hooklib

MAP_CHARS = 4000        # the size of a map: what does not fit is counted at its end ("and N more"); the key ranges never shrink
IDS_SHOWN = 20          # how many ids a refusal lists before "and N more"
PLAN_ROWS_KEYS = ("rows", "items", "plan")    # where a plan keeps its rows, in the order the readers try (the one list of them)
_ALWAYS = ("rows", "requirements")            # a section the map names even when it is empty ("rows: none")


def rows_of(data) -> list:
    """The rows of a parsed plan: a bare array, or the first of `PLAN_ROWS_KEYS` that is a list, else `[]`."""
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in PLAN_ROWS_KEYS:
            if isinstance(data.get(key), list):
                return data[key]
    return []


def ids_there(ids, shown: int = IDS_SHOWN) -> str:
    """`a, b, c` for the first `shown` ids in order, then `and N more` - a refusal that lists ids is bounded and says how many it left out."""
    ids = [str(i) for i in dict.fromkeys(ids)]
    more = f" and {len(ids) - shown} more" if len(ids) > shown else ""
    return (", ".join(ids[:shown]) or "none") + more


# --- the rows of a plan: bytes and lines, found structurally ---------------------------------------------------------------

def _skip(text: str, i: int) -> int:
    while i < len(text) and text[i] in " \t\r\n":
        i += 1
    return i


def _plan_structure(text: str) -> tuple:
    """`(container, keys, elements)`: `container` is the key of the rows array (`rows`/`items`/`plan`, `rows` for a bare array);
    `keys` is `[(key, start, end)]` for each top-level key of an object; `elements` is `[(index, start, end, parsed)]` for EVERY
    element of the rows array, a non-object element included (it only moves the position on). ValueError when the text is not a
    JSON object or array."""
    dec = json.JSONDecoder()
    i = _skip(text, 1 if text.startswith("\ufeff") else 0)
    if i >= len(text) or text[i] not in "{[":
        raise ValueError("not a JSON object or array")
    keys, array_at, container = [], i, "rows"
    if text[i] == "{":
        last: dict = {}
        i += 1
        while True:
            i = _skip(text, i)
            if i >= len(text):
                raise ValueError("unterminated object")
            if text[i] == "}":
                break
            key, i = dec.raw_decode(text, i)
            i = _skip(text, i)
            if text[i] != ":" or not isinstance(key, str):
                raise ValueError("not a JSON object")
            i = _skip(text, i + 1)
            start = i
            _, i = dec.raw_decode(text, i)
            keys.append((key, start, i))
            last[key] = (start, i)                   # a repeated key: the last one wins, as in json.loads
            i = _skip(text, i)
            if text[i:i + 1] == ",":
                i += 1
        array_at = -1
        for name in PLAN_ROWS_KEYS:                  # the order of `rows_of`, not the order of the file
            if name in last and text[last[name][0]] == "[":
                array_at, container = last[name][0], name
                break
        if array_at < 0:
            return container, keys, []
    elements, i, index = [], array_at + 1, 0
    while True:
        i = _skip(text, i)
        if i >= len(text):
            raise ValueError("unterminated array")
        if text[i] == "]":
            break
        value, end = dec.raw_decode(text, i)
        elements.append((index, i, end, value))
        index += 1
        i = _skip(text, end)
        if text[i:i + 1] == ",":
            i += 1
    return container, keys, elements


def _line_of(newlines: list, position: int) -> int:
    """The 1-based line of a character offset. Lines are counted by `\\n` ONLY: `splitlines` would also cut at U+2028 / U+0085,
    which JSON allows raw inside a string and which the `Read` tool does not treat as a line end."""
    return bisect.bisect_left(newlines, position) + 1


def plan_rows_indexed(text: str) -> tuple:
    """`(container, [(index, id, start, end, first_line, last_line)])` for each OBJECT element of the plan's rows array: its place in
    the array (the index in `rows_of`), `str(row.get("id"))`, the offsets of its bytes in `text` (end exclusive) and its 1-based
    first and last line."""
    container, _, elements = _plan_structure(text)
    newlines = [i for i, ch in enumerate(text) if ch == "\n"]
    out = [(index, str(value.get("id")), start, end, _line_of(newlines, start), _line_of(newlines, end - 1))
           for index, start, end, value in elements if isinstance(value, dict)]
    return container, out


def plan_row_spans(text: str) -> list:
    """`[(id, start, end, first_line, last_line)]` for every row (object) of a plan, in file order: `text[start:end]` is exactly that
    row's bytes. ValueError when the text is not a JSON object or array."""
    return [(rid, start, end, first, last) for _, rid, start, end, first, last in plan_rows_indexed(text)[1]]


# --- the map ---------------------------------------------------------------------------------------------------------------

def _assemble(head: list, sections: list, cap: int, label: str) -> str:
    """The head lines (never cut), then one line per section `name: entry, entry`; what does not fit in `cap` characters is dropped
    from the END, section by section, and counted: `... and N more (names); Grep -n ...`."""
    total = sum(len(entries) for _, entries in sections)

    def render(keep: list) -> str:
        lines = list(head)
        for (name, entries), count in zip(sections, keep):
            if count:
                lines.append(f"{name}: " + ", ".join(entries[:count]))
            elif not entries and name in _ALWAYS:
                lines.append(f"{name}: none")
        left = total - sum(keep)
        if left:
            names = ", ".join(name for (name, entries), count in zip(sections, keep) if count < len(entries))
            lines.append(f"... and {left} more ({names}); Grep -n \"<id>\" {label} gives one's first line")
        return "\n".join(lines)

    keep = [len(entries) for _, entries in sections]
    text = render(keep)
    if len(text) <= cap:
        return text
    keep = [0] * len(sections)
    for at, (_, entries) in enumerate(sections):
        for count in range(1, len(entries) + 1):
            trial = keep[:]
            trial[at] = count
            if len(render(trial)) > cap:
                return render(keep)
            keep = trial
    return render(keep)


def _head(label: str, key_spans: list) -> list:
    keys = ", ".join(f"{key} {a}-{b}" for key, a, b in key_spans)
    return [f"Map of {label} - id first-last (1-based lines, the number `Read offset` takes):",
            f"keys: {keys or 'none'}"]


def _label(item, *names: str) -> str:
    if isinstance(item, dict):
        for name in names:
            value = item.get(name)
            if isinstance(value, (str, int)) and not isinstance(value, bool) and str(value).strip():
                return str(value).strip()
    return ""


def _grounding_map(path: Path, cap: int) -> str:
    import contract
    import planning_contract as PC
    root = path.parent.parent                     # <story>/work/grounding.yaml
    if os.path.normcase(os.path.abspath(contract.artifact_write_path(root, "grounding.yaml"))) != \
            os.path.normcase(os.path.abspath(path)):
        return ""                                 # a file the registry does not name is not "the table"
    before = path.read_bytes()
    doc, _ = PC.read_grounding(root)              # THE reader of the table; None when it cannot be read
    if doc is None or path.read_bytes() != before or doc.lines != before.decode("utf-8").splitlines():
        return ""                                 # unreadable, or changed while it was being read: no map
    spans = PC.grounding_item_lines(doc)          # every span already checked against the element it names
    data = doc.data
    naming: dict = {}                             # requirement -> the ids of the rows that name it
    for row in data["rows"] if isinstance(data.get("rows"), list) else []:
        if isinstance(row, dict) and isinstance(row.get("requirements"), list):
            for req in row["requirements"]:
                naming.setdefault(str(req), []).append(_label(row, "id"))

    def entries(prefix: str, items, names: tuple, extra=None) -> tuple:
        out, unplaced = [], []
        for i, item in enumerate(items if isinstance(items, list) else []):
            at = f"{prefix}[{i}]"
            name = "/".join(dict.fromkeys(filter(None, (_label(item, n) for n in names)))) or at
            if at in spans:
                out.append(f"{name} {spans[at][0]}-{spans[at][1]}" + (extra(item) if extra else ""))
            else:
                unplaced.append(name)
        return out, unplaced

    def rows_naming(item) -> str:
        ids = [i for i in naming.get(_label(item, "r"), []) if i]
        return f" (rows {', '.join(ids)})" if ids else ""

    plan = [("rows", "rows", data.get("rows"), ("id",), None),
            ("requirements", "requirements", data.get("requirements"), ("r",), rows_naming),
            ("areas", "blast_radius.areas", (data.get("blast_radius") or {}).get("areas")
             if isinstance(data.get("blast_radius"), dict) else None, ("id",), None),
            ("claims", "claims", data.get("claims"), ("r",), None),
            ("hunks", "hunks", data.get("hunks"), ("id", "short"), None),
            ("orphans", "orphans", data.get("orphans"), (), None),
            ("diff", "diff", data.get("diff"), (), None)]
    sections, missing = [], []
    for name, prefix, items, names, extra in plan:
        found, unplaced = entries(prefix, items, names, extra)
        sections.append((name, found))
        missing += unplaced
    if missing:
        sections.append(("no lines of their own", [", ".join(missing[:10]) + (f" and {len(missing) - 10} more" if len(missing) > 10 else "")]))
    key_spans = [(key, *spans[key]) for key in data if key in spans]
    return _assemble(_head(PC.GROUNDING_FILE, key_spans), sections, cap, PC.GROUNDING_FILE)


def _crowded(spans: list) -> "int | None":
    """The line a row has no line of its own on, else None. Neighbours may share their BOUNDARY line (`}, {` on one line: the previous
    row's last line is the next row's first) and keep their ranges; a row whose every line is shared with a neighbour is the one a
    window cannot isolate - the whole map then gives ids without ranges. `spans` are `plan_rows_indexed` entries, in file order, so
    rows overlap by at most that one boundary line."""
    for at, (_, _, _, _, first, last) in enumerate(spans):
        before = at > 0 and spans[at - 1][5] == first
        after = at + 1 < len(spans) and spans[at + 1][4] == last
        if last - first + 1 - before - after < 1:
            return first if before else last
    return None


def _plan_map(path: Path, cap: int) -> str:
    before = path.read_bytes()
    value = hooklib.read_json(path)               # the package's one JSON reader: the independent parse the spans are checked against
    if value is None or path.read_bytes() != before:
        return ""
    text = before.decode("utf-8-sig")
    _, keys, elements = _plan_structure(text)
    rows = rows_of(value)
    if len(rows) != len(elements) or any(json.loads(text[s:e]) != rows[i] for i, s, e, _ in elements):
        return ""                                 # a span that does not give its row back: no map
    _, spans = plan_rows_indexed(text)
    newlines = [i for i, ch in enumerate(text) if ch == "\n"]
    key_spans = [(key, _line_of(newlines, s), _line_of(newlines, e - 1)) for key, s, e in keys]
    shared = _crowded(spans)
    if shared is not None:        # a row with no line of its own (a file written as one line): a line window cannot isolate it
        entries = [f"(rows share line {shared}: no line window isolates one row)"] + [rid for _, rid, *_ in spans]
    else:
        entries = [f"{rid} {first}-{last}" for _, rid, _, _, first, last in spans]
    return _assemble(_head("work/test-plan.json", key_spans), [("rows", entries)], cap, "work/test-plan.json")


KINDS = {"grounding": _grounding_map, "plan_rows": _plan_map}    # the names the data (`read_by_section`) uses


def section_map_text(path, kind: str, cap: int = MAP_CHARS) -> str:
    """The map of the sections of `path` (`kind`: `grounding` or `plan_rows`), at most `cap` characters apart from the key ranges
    that are never cut; `""` for ANY failure (an unknown kind, a file that is absent, broken or changes while it is read, a path
    the registry does not name, a span that does not give its element back). It never raises: the caller's refusal is then the text it
    had before, and a role reads by windows."""
    build = KINDS.get(kind)
    if build is None:
        return ""
    try:
        return build(Path(path), cap)
    except Exception:       # noqa: BLE001 - the error direction is "no map"; the reason is the caller's refusal text
        return ""
