#!/usr/bin/env python3
"""The form of a role charter (spec t-1765 part B, section 3.3): the ONE reader of what a charter file is.

A charter is an `agents/<role>.md` file of six `## ` sections in a fixed order. Each heading has a
`<!-- kind: craft -->` or `<!-- kind: process -->` line DIRECTLY above it:

    Outcome (process) / Good outcome (process) / Where bugs hide at this stage (craft) / Techniques (craft)
    / Tools (process) / When to ask (process)

Marker order, for a file that also carries a `<!-- roles: ... -->` marker (references/*.md, read by contract_slices.parse):
either order is read the same - `contract_slices.parse` skips a `kind` line (`KIND_LINE`) and keeps the pending `roles`
marker, and `role_load.craft_split` skips a comment line between its marker and the heading. `kind` first is the
convention of the shipped files. A charter has no `roles` marker; there `kind` stands directly above the heading.

What counts as craft is measured by `role_load.craft_split` and by nothing else (AR-13): this module imports its marker
regexp and never counts craft itself. It only judges the SHAPE of the file (headings, order, markers, size, DoD item
count). The human description of the form is references/charter-form.md.

Functions and their side of the judgment census (AR-29): `is_charter`, `sections`, `outcome_text`, `dod_leads`,
`stray_markers` read and return data (not check-shaped names); `charter_errors` is a data check of shape (its name matches
`UNIT_NAME_RE`), it judges no role's work.

Usage: python charter.py <agents/role.md>   -> prints the errors, exit 1 when there are any
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from role_load import KIND_MARKER  # noqa: E402  (the one craft regexp)

PROCESS_MARKER = re.compile(r"<!--\s*kind:\s*process\s*-->")
CHARTER_SECTIONS = (("Outcome", "process"), ("Good outcome", "process"), ("Where bugs hide at this stage", "craft"),
                    ("Techniques", "craft"), ("Tools", "process"), ("When to ask", "process"))
CHARTER_MAX_LINES = 150
DOD_ITEMS = (3, 6)
_H2 = re.compile(r"^##\s+(.*\S)\s*$")
_ITEM = re.compile(r"^\d+\.\s+(.*)$")
_BOLD = re.compile(r"\*\*(.+?)\*\*")


def _lines(text: str) -> list:
    return text.replace("\r\n", "\n").replace("\r", "\n").split("\n")


def _marker_kind(line: str):
    stripped = line.strip()
    match = KIND_MARKER.fullmatch(stripped)
    if match and match.group(1) in ("craft", "process"):
        return match.group(1)
    return None


def is_charter(text: str) -> bool:
    """True when the file carries at least one kind marker line outside a fenced block."""
    fence = False
    for line in _lines(text):
        if line.strip().startswith("```"):
            fence = not fence
        elif not fence and _marker_kind(line):
            return True
    return False


def sections(text: str) -> list:
    """[{heading, kind, body}] for every `## ` section, in file order. `kind` is read from the line DIRECTLY above the heading
    ('craft', 'process' or None); `body` is the text up to the next `## ` heading (marker line of the next one excluded).
    A shape reader; the craft COUNT belongs to role_load."""
    lines = _lines(text)
    found, fence = [], False
    for i, line in enumerate(lines):
        if line.strip().startswith("```"):
            fence = not fence
            continue
        match = None if fence else _H2.match(line)
        if match:
            found.append({"heading": match.group(1), "kind": _marker_kind(lines[i - 1]) if i else None, "at": i})
    out = []
    for n, sec in enumerate(found):
        end = found[n + 1]["at"] if n + 1 < len(found) else len(lines)
        if n + 1 < len(found) and sec["at"] < end - 1 and _marker_kind(lines[end - 1]):
            end -= 1
        out.append({"heading": sec["heading"], "kind": sec["kind"], "body": "\n".join(lines[sec["at"] + 1:end]).strip("\n")})
    return out


def _section(text: str, heading: str) -> str:
    for sec in sections(text):
        if sec["heading"] == heading:
            return sec["body"]
    return ""


def outcome_text(text: str) -> str:
    """The body of `## Outcome`, whitespace collapsed; '' when the charter has none."""
    return re.sub(r"\s+", " ", _section(text, "Outcome")).strip()


def _dod_items(body: str) -> list:
    return [m.group(1) for m in (_ITEM.match(line) for line in body.split("\n")) if m]


def dod_leads(text: str) -> list:
    """The lead of every numbered item under `## Good outcome`: the first bold span, else the first 60 characters."""
    leads = []
    for item in _dod_items(_section(text, "Good outcome")):
        bold = _BOLD.search(item)
        leads.append(bold.group(1).strip().rstrip(".") if bold else item.strip()[:60])
    return leads


def stray_markers(text: str) -> list:
    """Kind-marker lines whose next line is not a heading: reported, never an error (a marker not above a heading marks
    nothing; role_load.craft_split counts it in `ignored`). One line per marker: '<n>: <text>'."""
    lines, fence, out = _lines(text), False, []
    for i, line in enumerate(lines):
        if line.strip().startswith("```"):
            fence = not fence
        elif not fence and _marker_kind(line):
            nxt = lines[i + 1] if i + 1 < len(lines) else ""
            if not re.match(r"^#{1,6}\s+\S", nxt):
                out.append(f"line {i + 1}: {line.strip()}")
    return out


def charter_errors(text: str) -> list:
    """What is wrong with the SHAPE of a charter, one sentence each (what is wrong, what was expected); [] when it is well formed."""
    errors = []
    total = len(_lines(text.rstrip("\n")))
    if total > CHARTER_MAX_LINES:
        errors.append(f"the charter is {total} lines, at most {CHARTER_MAX_LINES}")
    found = sections(text)
    names = [s["heading"] for s in found]
    expected = [name for name, _ in CHARTER_SECTIONS]
    for name in expected:
        if name not in names:
            errors.append(f"no `## {name}` section; the six sections are: " + ", ".join(expected))
    for name in names:
        if name not in expected:
            errors.append(f"`## {name}` is not one of the six sections: " + ", ".join(expected))
    present = [n for n in names if n in expected]
    if present != [n for n in expected if n in present]:
        errors.append("the sections are out of order; expected: " + ", ".join(expected))
    kinds = dict(CHARTER_SECTIONS)
    for sec in found:
        want = kinds.get(sec["heading"])
        if want is None:
            continue
        if sec["kind"] is None:
            errors.append(f"`## {sec['heading']}` has no `<!-- kind: {want} -->` line directly above its heading")
        elif sec["kind"] != want:
            errors.append(f"`## {sec['heading']}` is {want}, its marker says {sec['kind']}")
    count = len(_dod_items(_section(text, "Good outcome")))
    if "Good outcome" in names and not DOD_ITEMS[0] <= count <= DOD_ITEMS[1]:
        errors.append(f"`## Good outcome` has {count} numbered items, expected {DOD_ITEMS[0]} to {DOD_ITEMS[1]}")
    intro = next((ln for ln in _section(text, "Good outcome").split("\n") if ln.strip()), "")
    if "Good outcome" in names and "`tried`" not in intro:
        errors.append("the first line of `## Good outcome` must name the `tried` table of the handoff form as the witness")
    if not re.search(r"<!--\s*gen:digest\b", text) or not re.search(r"<!--\s*/gen\s*-->", text):
        errors.append("no `<!-- gen:digest ... -->` block closed by `<!-- /gen -->` (it belongs at the end of `## Tools`)")
    return errors


def main(argv: list) -> int:
    if len(argv) != 2:
        print("usage: charter.py <agents/role.md>")
        return 2
    text = Path(argv[1]).read_text(encoding="utf-8-sig")
    problems = charter_errors(text)
    for p in problems:
        print(p)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
