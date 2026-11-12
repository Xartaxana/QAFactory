#!/usr/bin/env python3
"""The planner's claim reaches the S2 register through code (G1-13, grounding/1).

  claim_projector.py --task T           project every claim of work/grounding.yaml `claims[]` into the register, in ONE move
  claim_projector.py --task T --check   judge the claims against the register and write NOTHING (the S3 gate's read; detector form 1)

The S3 planner meets a behaviour of the diff that S2 never registered. It has no Bash and is not the register's writer, so it writes a
CLAIM in its own `work/grounding.yaml` and this module copies it: the `## Register` row, the `ids:` entry, the `## Behaviour claims`
row (`origin: S3-grounding`) and the readiness `open_questions` record (the before/now question). S2 is never sent back (FR-7).

  * A projected R is always implementation-only (`contract.implementation_only`): `source: derived`, no `ac_ref`, `observable` = the
    claim's `now_ref` (`diff:`), no non-silent matrix cell. So the claim is judged and its question travels; a projected row never
    becomes a requirement a test takes its expected value from without the person's answer (FR-58, P20).
  * One move, all or nothing: a claim that cannot be projected is refused by name and NOTHING is written to either file.
  * Every byte of the register outside the projected lines is unchanged (lines are split and joined as `contract.md_table` splits them,
    CRLF and a BOM stay); the readiness file is JSON-equal outside the new `open_questions` entry and the recomputed counters.
  * The readiness file is written first, the register second, under the answers lock: a crash between them leaves a question whose row
    is missing, never a row naming a missing question, and a replay converges.
  * `s3_claim_errors` writes nothing and takes no lock (FR-45); `grounding.yaml` is never written here (its one writer is
    `grounding_table.py`).

Exit codes: 0 projected or nothing to do (`--check`: no finding), 1 findings the strategist fixes (form 1 on stdout), 2 a problem of the
conductor or the driver, or a refused call (stderr). The library (`project`, `s3_claim_errors`) is what the driver's S3 window and the
S3 gate call in-process.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import contract as C  # noqa: E402
import detector_verdict as DV  # noqa: E402
import grammar as G  # noqa: E402
import grounding_table as GT  # noqa: E402
import hooklib  # noqa: E402
import planning_contract as PC  # noqa: E402
import question_register as QR  # noqa: E402

ORIGIN = C.CLAIM_ORIGIN_S3
DASH = chr(0x2014)
REGISTER_FILE = "requirements-register.md"
R_RE = re.compile(r"R-[1-9][0-9]*")
NOW_REF_RE = re.compile(r"diff:[^\s|]+:[0-9]+")
# The characters `str.splitlines` breaks a line on: a value holding one would be two lines for the readers (axis 7).
BREAKS = frozenset(chr(c) for c in (0x0A, 0x0D, 0x0B, 0x0C, 0x1C, 0x1D, 0x1E, 0x85, 0x2028, 0x2029))
SOURCE_ORDER = ("story", "feature", "assumption", "discussion", "ac", "derived")   # the template's `by_source:` order
REGISTER_NAMES = ("r", "requirement", "source", "derived_from", "verifiable", "ac_ref", "observable")
DERIVED_FROM = "aspect:behaviour-change"
CLAIMS_HEADER = [C.CLAIM_COLUMNS[0].upper(), *C.CLAIM_COLUMNS[1:]]   # a claims table the projector creates: `R | before | ... | origin`
BEFORE_UNREADABLE = "the code before the change could not be read"
BEFORE_NEW_PATH = "a new path: no code before the change"
TEXT_KEYS = ("requirement", "impact", "before", "before_ref", "now", "now_ref", "differs")
NO_WRITE = "Nothing was written to requirements-register.md or requirements-readiness.json"
PERSON = "A person's word passes the S3 gate that reads this (FR-4)."


class ClaimProblem(str):
    """One refusal: a plain `str` (the FR-1 sentence, so a list of them still prints and joins) that carries `.rule` (R-a..R-e),
    `.who` (role | driver | conductor: who acts, the `PC.GroundingProblem` pattern) and `.label` (`R-28` or `claims[2]`)."""

    def __new__(cls, rule: str, who: str, label: str, text: str):
        self = super().__new__(cls, text)
        self.rule, self.who, self.label = rule, who, label
        return self


class _Carrier(Exception):
    """A carrier (register or readiness) that cannot take the claims; `.why` is the sentence."""


# --- the claim: what the strategist wrote, judged before any byte moves ---------------------------------------------------------------

def _scale() -> set:
    return set(G.impact_scale(G.load_overrides(hooklib.config_path())))


def _cell_flaw(value: str) -> str:
    bad = next((ch for ch in value if ch in BREAKS), "")
    if bad:
        return f"holds the line-break character U+{ord(bad):04X}"
    if "|" in value:
        return "holds `|`, which ends a table cell"
    if GT.LONE_SURROGATE.search(value):
        return "holds a lone surrogate, which cannot be written as UTF-8"
    return ""


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def _field(doc, i: int, claim: dict, key: str, found: list, required: bool = True):
    """The text at `claims[i].<key>`, or None with the reason appended to `found` as `(what, expected)`."""
    if key not in claim:
        if required:
            found.append((f"`{key}` is missing", f"`{key}: \"<text>\"`, the text in double quotes"))
        return None if required else ""
    value = claim[key]
    flaw = GT._traps(doc, f"claims[{i}].{key}", value)
    if flaw:
        found.append((f"`{key}` {flaw}", "a text value in double quotes, on one line"))
        return None
    if key in TEXT_KEYS or key == "r":
        flaw = _cell_flaw(value)
        if flaw:
            found.append((f"`{key}` {flaw}", "text on one line with no `|` (it becomes one cell of a register line)"))
            return None
    return value


def _before_where(before: str, before_ref: str) -> str:
    if before_ref:
        return before_ref
    return BEFORE_UNREADABLE if before.lower() == C.CLAIM_UNKNOWN else BEFORE_NEW_PATH if before.lower() == C.CLAIM_ABSENT else ""


def _judge(doc, i: int, claim, env) -> tuple:
    """`(found, prepared)` for ONE claim: `found` is [(what, expected)], `prepared` the claim as the projection needs it (None
    when anything is wrong). The contract's own judge (`claim_row_errors`) stays the judge of before/now/differs/question."""
    found: list = []
    if not isinstance(claim, dict):
        return [(f"claims[{i}] is not a map", "a map with `r`, `row`, `requirement`, `impact`, `before`, `before_ref`, `now`, "
                 "`now_ref`, `differs`, `question: raise`, `ask`")], None
    text = {key: _field(doc, i, claim, key, found, required=key != "before_ref") for key in ("r", "row", *TEXT_KEYS, "question")}
    origin = claim.get("origin")
    if "origin" in claim and origin != ORIGIN:
        found.append((f"`origin` is {origin!r}", f"`origin: {ORIGIN}` or no `origin` at all (the code writes it)"))
    if any(any(GT.LONE_SURROGATE.search(s) for s in _strings(v)) for v in claim.values()):
        found.append(("a text holds a lone surrogate, which cannot be written as UTF-8", "text that is valid UTF-8"))
    if text["r"] is not None and not R_RE.fullmatch(text["r"]):
        free = env.free_id()
        found.append((f"`r` is '{text['r']}'", "a free register id `R-<n>` with no leading zero"
                      + (f" (the next free id is {free})" if free else "")))
    if text["row"] is not None and text["row"] not in env.rows:
        found.append((f"`row` '{text['row']}' is no id of `rows[]`", "the id of the `behaviour_change` row this claim comes from"))
    if text["requirement"] is not None and not text["requirement"].strip():
        found.append(("`requirement` is empty", "one verifiable statement"))
    if text["impact"] is not None and text["impact"] not in env.scale:
        found.append((f"`impact` is '{text['impact']}'", "a word of the project's impact scale: " + ", ".join(sorted(env.scale))))
    if text["now_ref"] is not None and not NOW_REF_RE.fullmatch(text["now_ref"]):
        found.append((f"`now_ref` is '{text['now_ref']}'", "`diff:<path>:<line>`: it becomes the requirement's observable, "
                      "and a projected row is always read from the diff"))
    if text["question"] is not None and text["question"] != C.RAISE_REF:
        found.append((f"`question` is '{text['question']}'", f"`question: {C.RAISE_REF}`: the code gives the question its id"))
    ask = claim.get("ask")
    if not isinstance(ask, dict):
        found.append(("`ask` is not a map", "`ask:` with `question`, `source_says`, `severity`, `owner_role`"))
        ask = {}
    for key in ("question", "severity", "owner_role"):
        flaw = GT._traps(doc, f"claims[{i}].ask.{key}", ask.get(key)) if key in ask else ""
        if flaw:
            found.append((f"`ask.{key}` {flaw}", "a text value in double quotes, on one line"))
    leaves: list = []
    GT._leaf_traps(doc, f"claims[{i}].ask.source_says", ask.get("source_says"), "`ask.source_says`", set(), leaves)
    found.extend((leaf, "text in double quotes, on one line") for leaf in leaves)
    if found:
        return found, None
    before, before_ref = text["before"], text["before_ref"] or ""
    spec = {"question": ask.get("question"), "source_says": ask.get("source_says"), "severity": ask.get("severity"),
            "owner_role": ask.get("owner_role"), "before": {"value": before, "where": _before_where(before, before_ref)},
            "now": {"value": text["now"], "where": text["now_ref"]}}
    question, issues = C.claim_question(spec, f"claims[{i}].ask")
    found.extend((issue, "the `ask` map the form gives") for issue in issues)
    row = {"r": text["r"], "before": before, "before_ref": before_ref, "now": text["now"], "now_ref": text["now_ref"],
           "differs": text["differs"], "question": "Q?"}
    found.extend((frag, "the claim form") for frag in C.claim_row_errors(row, {"Q?": question} if question else None,
                                                                         snapshot_items=_snapshot_items(env.root)))
    if before_ref.startswith("base:") and before.lower() not in (C.CLAIM_UNKNOWN, C.CLAIM_ABSENT):
        why = env.base_problem(before_ref)
        if why:
            found.append((f"`before_ref` '{before_ref}' is not a place the base slice read: {why}", "a line of the base slice, or "
                          "`before: \"unknown\"` when the base cannot show it, or a `diff:-<path>:<line>` removed line"))
    if found:
        return found, None
    return [], SimpleNamespace(i=i, r=text["r"], question=question, before_where=_before_where(before, before_ref),
                               **{key: text[key] or "" for key in ("requirement", "impact", "before", "before_ref", "now", "now_ref", "differs")})


def _next_free(taken, claims) -> str:
    numbers = [int(m.group(1)) for r in list(taken) + [c.get("r") for c in claims if isinstance(c, dict)]
               for m in [re.fullmatch(r"R-(\d+)", r.strip())] if isinstance(r, str) and m]
    return f"R-{max(numbers, default=0) + 1}"


def _a(i: int, r, what: str, expected: str, n: int, written: bool) -> ClaimProblem:
    door = (f"fix that field of work/grounding.yaml; {NO_WRITE.lower()} - one refused claim holds all {n}. {PERSON}" if written
            else f"fix that field of work/grounding.yaml. {PERSON}")
    return ClaimProblem("R-a", "role", str(r) if isinstance(r, str) and R_RE.fullmatch(r) else f"claims[{i}]",
                        f"grounding.yaml: claims[{i}] ({r}): {what}. Expected: {expected} - fix: {door}")


class _Env:
    """What the checks of a claim need from the world, built once per move: the row ids of the table, the impact scale, the base slice."""

    def __init__(self, root, doc, collected):
        rows = doc.data.get("rows")
        self.rows = {r.get("id") for r in rows if isinstance(r, dict)} if isinstance(rows, list) else set()
        self.scale, self.root, self.collected, self._failed = _scale(), root, collected, ""
        self.claims, self._free = doc.data.get("claims"), None

    def free_id(self) -> str:
        """The next free register id, for the text of a malformed `r` (a lock-free read, text only; "" when the register cannot be read)."""
        if self._free is None:
            try:
                self._free = _next_free(_state(_read_register(self.root)[1]).taken, self.claims)
            except _Carrier:
                self._free = ""
        return self._free

    def base_problem(self, ref: str) -> str:
        import base_slice as BS
        if self.collected is None and not self._failed:
            try:
                self.collected = BS.collect(self.root)
            except Exception as exc:   # the slice is an instrument: a failure to build it refuses the base ref, never the move (FR-59)
                self._failed = f"the base slice cannot be collected ({type(exc).__name__})"
        return self._failed or BS.base_place_problem(ref, self.root, collected=self.collected)


def _read_claims(root, collected, written: bool) -> tuple:
    """`(claims, prepared, problems)`: `claims` is the list the table holds ([] for none), `prepared` one object per claim that
    passed, `problems` every R-a/R-e line. A table the reader refuses is one R-e (its own `who`); an absent table is no claim."""
    doc, problem = PC.read_grounding(root)
    if doc is None:
        if getattr(problem, "kind", "") == "missing":
            return [], [], []
        return [], [], [ClaimProblem("R-e", problem.who, "claims", str(problem))]
    claims = doc.data.get("claims")
    if claims is None or claims == []:
        return [], [], []
    if not isinstance(claims, list):
        return [], [], [_a(0, "claims", "`claims` is not a list", "`claims:` followed by `- r: R-<n>` entries", 1, written)]
    env = _Env(root, doc, collected)
    problems, prepared, seen = [], [], {}
    for i, claim in enumerate(claims):
        found, item = _judge(doc, i, claim, env)
        r = claim.get("r") if isinstance(claim, dict) else None
        problems.extend(_a(i, r, what, expected, len(claims), written) for what, expected in found)
        if item is not None:
            prepared.append(item)
        if isinstance(r, str):
            seen.setdefault(r, []).append(i)
    for r, where in seen.items():
        if len(where) > 1:
            problems.extend(_a(i, r, f"`r` {r} is also written by claims[{', '.join(str(j) for j in where if j != i)}]",
                               "one claim per register id", len(claims), written) for i in where)
    return claims, prepared, problems


# --- the carriers: the register and the readiness, read as their own writers read them ------------------------------------------------

def read_readiness(root) -> tuple:
    """`(path, data, rows)`: the readiness file as its writers read it; raises `_Carrier` (the sentence is `str(exc)`). The ONE reader for the
    claim projection and for the S3 plan's `new:` questions (`planning_contract._raise_new_questions`; RN1-2 m-5, AR-13)."""
    path = Path(root).joinpath(*QR.READINESS_REL)
    try:
        data = json.loads(path.read_bytes().decode("utf-8-sig"))
    except FileNotFoundError:
        raise _Carrier(f"{path.name} does not exist (S2 writes it)")
    except (OSError, ValueError, RecursionError):
        raise _Carrier(f"{path.name} is not valid JSON")
    rows = data.get("open_questions") if isinstance(data, dict) else None
    if not isinstance(data, dict) or not (rows is None or isinstance(rows, list)):
        raise _Carrier(f"{path.name} does not hold an object with an `open_questions` list")
    return path, data, rows or []


def _read_register(root) -> tuple:
    try:
        path = C.artifact(Path(root), REGISTER_FILE)
    except ValueError as exc:
        raise _Carrier(f"{exc}")
    if not path.is_file():
        raise _Carrier(f"work/{REGISTER_FILE} does not exist (S2 writes it)")
    try:
        text = path.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError):
        raise _Carrier(f"work/{REGISTER_FILE} cannot be read as UTF-8 text")
    if not C.md_table(text, "## Register"):
        raise _Carrier(f"work/{REGISTER_FILE} holds no `## Register` table")
    ids = C.front_line(text, "ids")
    if ids is None or not re.match(r"^\[.*\]", ids.strip()):
        raise _Carrier(f"work/{REGISTER_FILE} has no inline `ids: [R-1, ...]` list in its front matter")
    return path, text


def _d(why: str) -> ClaimProblem:
    return ClaimProblem("R-d", "conductor", "carrier",
                        f"requirements-register.md (or requirements-readiness.json) cannot take the S3 claims: {why}. Expected: the S2 "
                        "files as the requirements tester writes them - fix: both are S2's and the strategist cannot repair them: the "
                        f"conductor decides - repair the carrier, or pass the S3 gate by the person's word. {NO_WRITE}.")


def _state(text: str) -> SimpleNamespace:
    """The register as the claims meet it: who holds each R (`taken`, the first table or `ids:`), the Register rows, the claims rows,
    the matrix rows with a non-silent cell, by whole-token R (`R-2` is not `R-27`)."""
    taken: dict = {}
    for table in ("## Register", "## Contradiction matrix", "## Behaviour claims", "## Reading forks"):
        for cells in C.md_table(text, table):
            first = C.strip_cell(cells[0]) if cells else ""
            if C.REQ_ID_RE.fullmatch(first):
                taken.setdefault(first, table[3:])
    for r in G.parse_inline_list(C.front_line(text, "ids")):   # last: a table names the place better than `ids:` does
        taken.setdefault(r, "ids:")
    regs: dict = {}
    for cells in C.md_table(text, "## Register"):
        first = C.strip_cell(cells[0]) if cells else ""
        if C.REQ_ID_RE.fullmatch(first):
            regs.setdefault(first, []).append(cells)
    claims: dict = {}
    for row in C.behaviour_claims(text):
        claims.setdefault(row["r"], []).append(row)
    loud = set()
    for cells in C.md_table(text, "## Contradiction matrix"):
        first = C.strip_cell(cells[0]) if cells else ""
        if C.REQ_ID_RE.fullmatch(first) and not all(C._silent_cell(c) for c in cells[1:]):
            loud.add(first)
    return SimpleNamespace(taken=taken, regs=regs, claims=claims, loud=loud)


def _is_own(st, r: str) -> bool:
    rows = st.claims.get(r, [])
    return len(rows) == 1 and rows[0].get("origin") == ORIGIN and len(st.regs.get(r, [])) == 1 and r not in st.loud


def _empty(value: str) -> str:
    return "" if value in C.EMPTY_CELLS else value


def _differences(st, header, c) -> list:
    """`[(field, in the register, in the claim)]` of an own R whose claim no longer says what was projected."""
    cells, row = st.regs[c.r][0], st.claims[c.r][0]

    def cell(place: int) -> str:
        return C.strip_cell(cells[place]) if len(cells) > place else ""
    seen = [("requirement", cell(1), c.requirement), ("observable", cell(6), c.now_ref)]
    if header.has_impact:
        seen.append(("impact", cell(7), c.impact))
    seen += [(key, row.get(key, ""), getattr(c, key)) for key in ("before", "before_ref", "now", "now_ref", "differs")]
    return [(field, a, C.strip_cell(b)) for field, a, b in seen if _empty(a) != _empty(C.strip_cell(b))]


# --- the headers (E17) --------------------------------------------------------------------------------------------------------------

def _register_header(text: str) -> SimpleNamespace:
    """The `## Register` header as the contract and the validator both read it: each contract name at its own place (default
    `_header_index` mode), `impact` at 7 when there are 8 cells or more, `delta` by exact name beyond them."""
    header = C.md_table(text, "## Register")[0]
    info = SimpleNamespace(cells=header, has_impact=len(header) >= 8, delta_at=C._header_index(header, "delta", -1, exact=True), why="")
    for i, name in enumerate(REGISTER_NAMES):
        if C._header_index(header, name, -1) != i:
            info.why = f"the `## Register` header has no `{name}` cell at place {i + 1}"
    if info.has_impact and C._header_index(header, "impact", -1) != 7:
        info.why = "the `## Register` header has 8 cells or more but no `impact` cell at place 8"
    if 0 <= info.delta_at < 7:
        info.why = "the `## Register` header has its `delta` cell inside the first seven places"
    return info


def _register_line(info, c) -> str:
    cells = [DASH] * len(info.cells)
    values = {0: c.r, 1: c.requirement, 2: "derived", 3: DERIVED_FROM, 4: "yes", 5: DASH, 6: c.now_ref}
    if info.has_impact:
        values[7] = c.impact
    if info.delta_at >= 0:
        values[info.delta_at] = "new"
    for place, value in values.items():
        cells[place] = value
    return "| " + " | ".join(cells) + " |"


def _claims_line(header: list, c, question_id: str) -> str:
    cells = [DASH] * len(header)
    wanted = {"r": c.r, "before": c.before, "before_ref": c.before_ref or DASH, "now": c.now, "now_ref": c.now_ref,
              "differs": c.differs, "question": question_id, "origin": ORIGIN}
    for i, name in enumerate(C.CLAIM_COLUMNS):
        place = C._header_index(header, name, -1, exact=True) if name == "origin" else C._header_index(header, name, i)
        if 0 <= place < len(cells):
            cells[place] = wanted[name]
    return "| " + " | ".join(cells) + " |"


# --- the register text: lines inserted, nothing else moved (I4) -----------------------------------------------------------------------

def _ending(line: str) -> str:
    return "\r\n" if line.endswith("\r\n") else "\n" if line.endswith("\n") else "\r" if line.endswith("\r") else ""


def _section(lines: list, heading: str):
    """`(start, end)`: the heading line and the next `## ` line (or the end), exactly as `contract.md_table` walks it; None if absent."""
    start = next((i for i, line in enumerate(lines) if line.strip().startswith(heading)), None)
    if start is None:
        return None
    end = next((i for i in range(start + 1, len(lines)) if lines[i].strip().startswith("## ")), len(lines))
    return start, end


def _last_row(lines: list, start: int, end: int):
    rows = [i for i in range(start + 1, end) if lines[i].strip().startswith("|")]
    return rows[-1] if rows else None


def _table_head(header: list) -> list:
    return ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]


def _claims_header(lines: list, claims: tuple, notes: list) -> list:
    """The header cells of an existing claims table; a table with no `origin` cell gets one (header and separator widened in place)."""
    rows = [i for i in range(claims[0] + 1, claims[1]) if lines[i].strip().startswith("|")]
    head_at = rows[0]
    header = G.split_cells(lines[head_at])
    if C._header_index(header, "origin", -1, exact=True) >= 0:
        return header
    sep_at = next((i for i in rows[1:2] if set("".join(G.split_cells(lines[i]))) <= set("-: ")), None)
    if not lines[head_at].rstrip().endswith("|") or sep_at is None or not lines[sep_at].rstrip().endswith("|"):
        raise _Carrier("the `## Behaviour claims` header has no `origin` cell and its lines cannot take one")
    for place, suffix in ((head_at, " origin |"), (sep_at, "---|")):
        body = lines[place].rstrip("\r\n")
        lines[place] = body.rstrip() + suffix + lines[place][len(body):]
    notes.append("the `## Behaviour claims` header got an `origin` cell (older registers have none)")
    return header + ["origin"]


def _claims_inserts(lines: list, reg: tuple, items: list, notes: list) -> tuple:
    """`(position, [line])` where the claims rows go: in a new section after the matrix, under a heading with no table, or below the
    last row of the existing table."""
    claims = _section(lines, "## Behaviour claims")
    if claims is None:
        after = (_section(lines, "## Contradiction matrix") or reg)[1]
        return after, ["", "## Behaviour claims", ""] + _table_head(CLAIMS_HEADER) + [_claims_line(CLAIMS_HEADER, c, q) for c, q in items]
    row = _last_row(lines, *claims)
    if row is not None:
        header = _claims_header(lines, claims, notes)
        return row + 1, [_claims_line(header, c, q) for c, q in items]
    blank = claims[0] + 1 < len(lines) and not lines[claims[0] + 1].strip()
    return (claims[0] + (2 if blank else 1),
            ([] if blank else [""]) + _table_head(CLAIMS_HEADER) + [_claims_line(CLAIMS_HEADER, c, q) for c, q in items])


def _apply_inserts(lines: list, inserts: dict, first_nl: str) -> None:
    for position in sorted(inserts, reverse=True):
        nl = _ending(lines[position - 1] if position else "") or first_nl
        if position == len(lines) and lines and not _ending(lines[-1]):
            lines[-1] += nl
        lines[position:position] = [line + nl for line in inserts[position]]


def _edit_register(text: str, st_header, items: list, notes: list) -> str:
    """The register text with each item's Register line and claims line inserted, `ids:` extended and `by_source:` recounted."""
    lines = text.splitlines(keepends=True)
    reg = _section(lines, "## Register")
    inserts = {_last_row(lines, *reg) + 1: [_register_line(st_header, c) for c, _ in items]}
    position, block = _claims_inserts(lines, reg, items, notes)
    inserts.setdefault(position, []).extend(block)
    _apply_inserts(lines, inserts, _ending(lines[0]) or "\n")
    return _front_matter("".join(lines), [c.r for c, _ in items], notes)


def _front_matter(text: str, added: list, notes: list) -> str:
    """`ids:` gets the new R before its closing bracket; `by_source:` has only its `derived` count rewritten (from the rows of this text).
    Both go through `contract.set_front_line` (it normalises `key: value` spacing); a value of another shape is left as S2 wrote it, and
    `_post_build` then refuses an `ids:` that lacks the R."""
    ids = (C.front_line(text, "ids") or "").rstrip()   # `front_line` keeps the `\r` of a CRLF line in its value
    found = re.match(r"^(\[)(.*?)(\][ \t]*(?:#.*)?)$", ids)
    if found:
        inner = found.group(2) + "".join((", " if (found.group(2).strip() or k) else "") + r for k, r in enumerate(added))
        text = C.set_front_line(text, "ids", found.group(1) + inner + found.group(3))
    by_source = C.front_line(text, "by_source")
    if by_source is None:
        return text
    found = re.match(r"^(\{)(.*?)(\}[ \t]*(?:#.*)?)$", by_source.rstrip())
    if not found:
        notes.append("front matter `by_source:` is not an inline map: its `derived` count was left as S2 wrote it")
        return text
    derived = sum(1 for row in C.register_rows(text) if row["source"] == "derived")
    if re.search(r"\bderived:[ \t]*\d+", found.group(2)):
        inner = re.sub(r"(\bderived:[ \t]*)\d+", lambda m: f"{m.group(1)}{derived}", found.group(2), count=1)
    else:
        inner = found.group(2) + ((", " if found.group(2).strip() else "") + f"derived: {derived}")
    return C.set_front_line(text, "by_source", found.group(1) + inner + found.group(3))


def _counters(data: dict, text: str) -> None:
    """The readiness counters from the rows of the NEW register text: `register.total` and `register.by_source.derived`; a readiness
    with no `register` key gets the whole block the template names (never incremented: a replay recomputes the same numbers)."""
    rows = C.register_rows(text)
    count = {word: sum(1 for row in rows if row["source"] == word) for word in SOURCE_ORDER}
    block = data.get("register")
    if block is None:
        data["register"] = {"total": len(rows), "by_source": count}
        return
    if not isinstance(block, dict):
        raise _Carrier("`register` in the readiness file is not an object")
    block["total"] = len(rows)
    if not isinstance(block.get("by_source"), dict):
        block["by_source"] = {}
    block["by_source"]["derived"] = count["derived"]


# --- the one move ---------------------------------------------------------------------------------------------------------------------

def _empty_result() -> SimpleNamespace:
    return SimpleNamespace(projected=[], unchanged=[], problems=[], notes=[], wrote=False)


def _plan(prepared: list, readiness: tuple, register: tuple, claims: list, snapshot_items=None) -> SimpleNamespace:
    """PURE: what the move would write. `problems` non-empty means nothing is to be written. `snapshot_items`: the story's reference
    snapshot item ids for the read-back of a `reference:<item>` claim (None: none)."""
    plan = SimpleNamespace(problems=[], projected=[], unchanged=[], notes=[], text=None, data=None)
    _, data, rows = readiness
    _, text = register
    st = _state(text)
    header = _register_header(text)
    if header.why:
        plan.problems.append(_d(header.why))
        return plan
    asked = {str(c.get("r")) for c in claims if isinstance(c, dict)}
    for r, row in st.claims.items():
        if r not in asked and any(x.get("origin") == ORIGIN for x in row):
            plan.notes.append(f"{r} projected, no longer claimed (the register keeps the row)")
    top, new_rows, items = 0, [], []
    for c in prepared:
        key = {"claim": c.r, "origin": ORIGIN}
        if _is_own(st, c.r):
            diff = _differences(st, header, c)
            earlier = next((x for x in rows if isinstance(x, dict) and x.get("raised_for") == key), None)
            if diff:
                plan.problems.append(_changed(c, st.claims[c.r][0]["question"], diff))
            elif earlier is not None and earlier.get("id") != st.claims[c.r][0]["question"]:
                plan.problems.append(_d(f"the claims row of {c.r} names {st.claims[c.r][0]['question']} while readiness holds its question as "
                                        f"{earlier.get('id')}"))
            else:
                plan.unchanged.append(c.r)
            continue
        if c.r in st.taken:
            plan.problems.append(_taken(c, st, claims))
            continue
        row, earlier = QR._question_row(rows, c.question, key, taken=top)
        if earlier is not None:
            old, new = QR._shown(earlier), QR._shown(c.question)
            if old != new:
                plan.problems.append(_changed(c, earlier.get("id"), [("before/now", old, new)]))
                continue
            qid = earlier.get("id")
        else:
            qid = row["id"]
            top = int(qid[1:])
            new_rows.append(row)
        items.append((c, qid))
        plan.projected.append(c.r)
    if plan.problems or not items:
        return plan
    data = json.loads(json.dumps(data))
    data["open_questions"] = list(rows) + new_rows
    try:
        plan.text = _edit_register(text, header, items, plan.notes)
        _counters(data, plan.text)
    except _Carrier as exc:
        plan.problems.append(_d(str(exc)))
        return plan
    if not header.has_impact:
        plan.notes.append("impact not written: the register has no impact column")
    plan.data = data
    plan.problems.extend(_post_build(plan.text, data["open_questions"], items, snapshot_items))
    return plan


def _taken(c, st, claims) -> ClaimProblem:
    where = st.taken[c.r]
    cells = st.regs.get(c.r, [[]])[0]
    said = f": «{C.strip_cell(cells[1])[:60]}»" if where == "Register" and len(cells) > 1 else ""
    return ClaimProblem("R-b", "role", c.r, f"grounding.yaml: claims[{c.i}] names {c.r}, which is already taken in requirements-register.md "
                        f"({where}{said}). Expected: a claim takes a free id - fix: write r: {_next_free(st.taken, claims)}. {NO_WRITE}. {PERSON}")


def _changed(c, qid, diff) -> ClaimProblem:
    old = "; ".join(f"{f} {a}" for f, a, _ in diff)
    new = "; ".join(f"{f} {b}" for f, _, b in diff)
    return ClaimProblem("R-c", "role", c.r, f"grounding.yaml: claim {c.r} was raised as {qid} showing {old}; it now shows {new}. Expected: a raised "
                        "claim is not rewritten (its question may be in front of the person) - fix: restore the claim, or write the new "
                        f"behaviour as a new claim with a new free `r`. {NO_WRITE}. {PERSON}")


def _snapshot_items(root):
    """The ids of the story's reference snapshot (`reference_snapshot.item_ids`, the reader of record); None when there is none, it cannot
    be read or the build is half-installed: a `reference:<item>` claim is then refused, never passed."""
    try:
        import reference_snapshot
        return reference_snapshot.item_ids(root)
    except Exception:   # noqa: BLE001
        return None


def _post_build(text: str, questions: list, items: list, snapshot_items=None) -> list:
    """I3 asserted, not hoped: every projected R reads back as an implementation-only claim with its own question, whole, and in `ids:`."""
    by_id = {q["id"]: q for q in questions if isinstance(q, dict) and isinstance(q.get("id"), str)}
    only, asked, claim_rows = set(C.implementation_only(text)), C.claim_questions(text), {r["r"]: r for r in C.behaviour_claims(text)}
    ids = G.parse_inline_list(C.front_line(text, "ids"))
    link_index = C.claim_link_index(by_id)      # once for all the rows: a scan per row is quadratic (t-1781)
    out = []
    for c, qid in items:
        row = claim_rows.get(c.r)
        errors = [] if row is not None else ["it has no claims row"]
        if c.r not in ids:
            errors.append("it is not in the front matter `ids:`")
        if row is not None:
            errors += C.claim_row_errors(row, by_id, link_index, snapshot_items=snapshot_items)
            errors += [f"its {key} reads back as '{row.get(key)}'" for key in ("before", "before_ref", "now", "now_ref", "differs")
                       if _empty(row.get(key, "")) != _empty(C.strip_cell(getattr(c, key)))]
            errors += [] if row.get("origin") == ORIGIN else [f"its origin reads back as '{row.get('origin')}'"]
        if c.r not in only:
            errors.append("it is not implementation-only")
        if asked.get(c.r) != qid:
            errors.append(f"its question reads back as {asked.get(c.r)}, not {qid}")
        if errors:
            out.append(_d(f"the projection of {c.r} would not read back as a behaviour claim ({'; '.join(errors)})"))
    return out


def _write(path: Path, payload: bytes) -> None:
    staged = path.with_name(path.name + ".tmp")
    staged.write_bytes(payload)
    os.replace(staged, path)


def project(task_root, *, collected=None, lock_wait=None) -> SimpleNamespace:
    """Project every claim of the story's `work/grounding.yaml` into the register and the readiness file, in ONE move.

    `SimpleNamespace(projected=[R], unchanged=[R], problems=[ClaimProblem], notes=[str], wrote=bool)`. Never raises on story data.
    Problems non-empty means nothing was written - except a failed write of the register after the readiness file was written
    (`wrote` is True then, and the problem says so: the replay converges). `collected` is the base slice result (tests give a stub);
    `lock_wait` the seconds to wait for the answers lock (default `question_register.LOCK_WAIT_SECONDS`)."""
    root = Path(task_root)
    result = _empty_result()
    claims, prepared, problems = _read_claims(root, collected, True)
    if problems:
        result.problems = problems
        return result
    if not prepared:
        return result
    wait = QR.LOCK_WAIT_SECONDS if lock_wait is None else lock_wait
    try:
        with QR.answers_lock(root, wait):
            _project_locked(root, claims, prepared, result)
    except QR.Refused:
        result.problems.append(ClaimProblem("R-e", "driver", "lock", "another writer holds the answers lock; nothing was written; the driver "
                                            "repeats the step"))
        result.projected, result.unchanged = [], []
    return result


def _project_locked(root, claims: list, prepared: list, result) -> None:
    """The move itself, under the answers lock: read both carriers, plan, write."""
    try:
        readiness, register = read_readiness(root), _read_register(root)
    except _Carrier as exc:
        result.problems.append(_d(str(exc)))
        return
    plan = _plan(prepared, readiness, register, claims, _snapshot_items(root))
    result.notes, result.unchanged = plan.notes, plan.unchanged
    if plan.problems:
        result.problems = plan.problems
        return
    if plan.text is None:
        return
    result.projected = plan.projected
    # Readiness first, register second (one lock): a crash between them leaves a question whose row is missing, never a row
    # naming a missing question, and the replay finds the question by `raised_for` and converges.
    for path, write in ((readiness[0], lambda p: QR._write_readiness(p, plan.data)),
                        (register[0], lambda p: _write(p, plan.text.encode("utf-8")))):
        if path == readiness[0] and plan.data == readiness[1]:
            continue
        try:
            write(path)
        except OSError as exc:
            result.problems.append(ClaimProblem("R-e", "driver", "carrier", f"{path.name} could not be written ({type(exc).__name__}); "
                                                + ("the question is recorded and the register row is not: the driver repeats the "
                                                   "step and it converges" if result.wrote else "nothing was written")))
            return
        result.wrote = True


def _row_question_items(root, data: dict) -> list:
    """`[(label, key, prose, quote, where)]`: every non-empty `question` of `requirements[]` then `rows[]` of the table, in table order. The key
    is the `raised_for` of its readiness row (`{requirement | row, origin}`); the quote is the register's statement of the requirement, or what
    the row's hunks and `reason` say (a blank quote is never written: the question needs one to be answerable)."""
    items = []
    texts = GT.register_info(root).texts
    for line in GT._dicts(data.get("requirements")):
        prose, r = str(line.get("question") or "").strip(), line.get("r")
        if prose and isinstance(r, str) and r.strip():
            items.append((r, {"requirement": r, "origin": ORIGIN}, prose,
                          texts.get(r) or f"requirement {r} of the register", f"work/{REGISTER_FILE} ({r})"))
    for row in GT._dicts(data.get("rows")):
        prose, g = str(row.get("question") or "").strip(), row.get("id")
        if prose and isinstance(g, str) and g.strip():
            hunks = row.get("hunks")
            hunks = ", ".join(str(h) for h in hunks) if isinstance(hunks, list) else str(hunks or "")
            items.append((g, {"row": g, "origin": ORIGIN}, prose,
                          str(row.get("reason") or "").strip() or f"the change in hunks {hunks or 'of the diff'}", f"work/grounding.yaml ({g})"))
    return items


def _rows_problem(rule: str, who: str, label: str, text: str) -> ClaimProblem:
    return ClaimProblem(rule, who, label, f"{text}. Nothing was written to requirements-readiness.json")


def _project_rows_locked(root, items: list, result) -> None:
    try:
        path, data, rows = read_readiness(root)
    except _Carrier as exc:
        result.problems.append(_rows_problem("R-d", "conductor", "carrier", f"requirements-readiness.json cannot take the questions of the "
                                             f"grounding table: {exc}. Expected: the S2 file as the requirements tester writes it - the "
                                             "conductor decides (repair the file)"))
        return
    new_rows, top = [], 0
    for label, key, prose, quote, where in items:
        question = C.grounding_row_question(prose, quote, where)
        errors = C.question_errors(dict(question, id="Q0"))
        if errors:
            result.problems.append(_rows_problem("R-d", "conductor", label, f"{label}: its question cannot be written as a register question "
                                                 f"({'; '.join(errors)}). Expected: a question with a quote and its place - the factory's own "
                                                 "defect, the conductor reports it"))
            continue
        row, earlier = QR._question_row(rows, question, key, taken=top)
        if earlier is not None:
            if " ".join(str(earlier.get("question") or "").split()) != " ".join(prose.split()):
                result.notes.append(f"{label}: its question text changed after {earlier.get('id')} was raised; {earlier.get('id')} stays as it was")
            continue
        top = int(row["id"][1:])
        new_rows.append(row)
        result.projected.append(label)
    if result.problems or not new_rows:
        result.projected = [] if result.problems else result.projected
        return
    data = json.loads(json.dumps(data))
    data["open_questions"] = list(rows) + new_rows
    try:
        _counters(data, _read_register(root)[1])
        QR._write_readiness(path, data)
    except _Carrier as exc:
        result.projected = []
        result.problems.append(_rows_problem("R-d", "conductor", "carrier", f"the readiness counters cannot be computed: {exc}"))
        return
    except OSError as exc:
        result.projected = []
        result.problems.append(_rows_problem("R-e", "driver", "carrier", f"requirements-readiness.json could not be written ({type(exc).__name__}); "
                                             "the driver repeats the step"))
        return
    result.wrote = True


def project_row_questions(task_root) -> SimpleNamespace:
    """The questions the strategist wrote on grounding rows and requirement lines (`question` of `work/grounding.yaml`) into the question
    register of `requirements-readiness.json` (G2-2): `SimpleNamespace(projected=[label], notes=[str], problems=[ClaimProblem], wrote=bool)`.
    One question per key (`{requirement | row, origin: S3-grounding}`), ONE `Q-n` for ever: a repeat adds nothing, a prose that changed
    since the question was raised keeps the first `Q-n` and leaves a note. The register is not touched. A readiness file that is absent or
    unreadable is a problem, never a silent "nothing to do" (FR-59), but only when a question is owed. Never raises on story data; the same
    answers lock and writer as `project`."""
    root = Path(task_root)
    result = SimpleNamespace(projected=[], notes=[], problems=[], wrote=False)
    doc, problem = PC.read_grounding(root)
    if doc is None:
        if getattr(problem, "kind", "") != "missing":
            result.problems.append(ClaimProblem("R-e", getattr(problem, "who", "conductor"), "questions", str(problem)))
        return result
    items = _row_question_items(root, doc.data)
    if not items:
        return result
    try:
        with QR.answers_lock(root, QR.LOCK_WAIT_SECONDS):
            _project_rows_locked(root, items, result)
    except QR.Refused:
        result.projected, result.wrote = [], False
        result.problems.append(ClaimProblem("R-e", "driver", "lock", "another writer holds the answers lock; nothing was written; the driver "
                                            "repeats the step"))
    return result


def _questions_view(root):
    """`{id: question}` of requirements-readiness.json as the question register reads it; None when the file is absent or the reader raised."""
    try:
        view = QR.load(root)
    except Exception:   # a half-installed build judges what it can (as validate_artifacts._question_rows)
        return None
    return {q["id"]: q for q in view.get("questions", [])} if view.get("register_present") else None


def s3_claim_errors(task_root) -> list:
    """The S3 re-run of the claim judgement, read-only (FR-45: no lock, no file is created, `grounding.yaml` is never written).

    (a) a readable table's claims through the checks of `project`; (b) each claim against the register: in `ids:`, one Register row, one
    claims row `origin: S3-grounding` equal to what the projection writes - or the question raised and the row pending; (c) EVERY
    `origin: S3-grounding` row of the live register, claimed or not: the contract's judge of the row, once, implementation-only,
    its question the one the claims table names and found in requirements-readiness.json (a file that is absent or unreadable
    confirms nothing: a finding per row, never a pass - FR-59). S2's own rows are never judged here (FR-7). No date gate (E15)."""
    root = Path(task_root)
    out: list = []
    claims, prepared, problems = _read_claims(root, None, False)
    out.extend(problems)
    try:
        _, text = _read_register(root)
    except _Carrier as exc:
        return out + ([_d(str(exc))] if claims else [])
    st, header = _state(text), _register_header(text)
    ids = set(G.parse_inline_list(C.front_line(text, "ids")))
    try:
        _, _, rows = read_readiness(root)
    except _Carrier:
        rows = []
    for c in prepared:
        if _is_own(st, c.r):
            diff = [] if header.why else _differences(st, header, c)
            out.extend(ClaimProblem("R-c", "role", c.r, f"claim {c.r} differs from its projected row ({f}: {a} vs {b}) - fix: restore the claim "
                                    f"in work/grounding.yaml or write the new behaviour as a new claim with a free `r`. {PERSON}")
                       for f, a, b in diff)
            if c.r not in ids:
                out.append(ClaimProblem("R-d", "conductor", c.r, f"{c.r}: projected, but not in the front matter `ids:` of requirements-register.md - "
                                        "fix: the register was rewritten after the projection (conductor)"))
        elif c.r in st.taken:
            out.append(_taken(c, st, claims))
        elif any(isinstance(x, dict) and x.get("raised_for") == {"claim": c.r, "origin": ORIGIN} for x in rows):
            q = next(x for x in rows if isinstance(x, dict) and x.get("raised_for") == {"claim": c.r, "origin": ORIGIN})
            out.append(ClaimProblem("R-d", "conductor", c.r, f"question {q.get('id')} raised, row pending for {c.r} - fix: rerun the projector: "
                                    f"claim_projector.py --task {root.name} (conductor)"))
        else:
            out.append(ClaimProblem("R-d", "conductor", c.r, f"claim {c.r} is not in the register - fix: the driver projects claims after each S3 "
                                    f"window; run claim_projector.py --task {root.name} (conductor)"))
    questions = _questions_view(root)
    only, asked, seen = set(C.implementation_only(text)), C.claim_questions(text), {}
    link_index = C.claim_link_index(questions)
    snapshot_items = _snapshot_items(root)
    for row in C.behaviour_claims(text):
        if row.get("origin") != ORIGIN:
            continue
        r, seen[row["r"]] = row["r"], seen.get(row["r"], 0) + 1
        tail = "the register was rewritten after the projection (conductor)"
        if seen[r] == 2:
            out.append(ClaimProblem("R-d", "conductor", r, f"{r}: appears twice under \"{C.CLAIM_HEADING}\" - fix: one claim per requirement; {tail}"))
        out.extend(ClaimProblem("R-d", "conductor", r, f"{r}: behaviour claim - {frag} - fix: {tail}") for frag in C.claim_row_errors(row, questions, link_index, snapshot_items=snapshot_items))
        if questions is None:   # nothing to confirm the question against is not a pass (FR-59)
            out.append(ClaimProblem("R-d", "conductor", r, f"{r}: question {row['question']} cannot be confirmed: requirements-readiness.json is "
                                    "absent/unreadable - fix: S2 writes that file; restore it (conductor)"))
        if r not in only:
            out.append(ClaimProblem("R-d", "conductor", r, f"{r}: projected row no longer implementation-only - fix: {tail}"))
        elif asked.get(r) != row["question"]:
            out.append(ClaimProblem("R-d", "conductor", r, f"{r}: its question is {asked.get(r)}, not {row['question']} - fix: {tail}"))
    return out


# --- the command line -----------------------------------------------------------------------------------------------------------------

def _print_findings(findings: list) -> None:
    print(f"REJECT — {len(findings)} finding(s) in the grounding claims:")
    for f in findings:
        print("- " + DV.one_line(f"[claims {f.label}] {f}"))


def main(argv=None) -> int:
    try:
        import console_io
        console_io.utf8_stdio()
    except ImportError:
        pass
    ap = argparse.ArgumentParser(description="Project the planner's claims into the requirements register (or --check them).")
    ap.add_argument("--task", required=True, help="the story's ticket key")
    ap.add_argument("--check", action="store_true", help="judge the claims against the register and write nothing")
    args = ap.parse_args(argv)
    try:
        root = hooklib.story_root(args.task, "claim_projector")
        if args.check:
            found = s3_claim_errors(root)
            if not found:
                print("OK: the claims of work/grounding.yaml are in the register")
                return 0
            _print_findings(found)
            return 1
        res = project(root)
        for r in res.projected:
            print(f"projected {r}")
        for r in res.unchanged:
            print(f"unchanged {r}")
        for note in res.notes:
            print(f"note: {note}")
        if res.problems:
            _print_findings(res.problems)
            return 1 if all(p.who == "role" for p in res.problems) else 2
        return 0
    except (ValueError, OSError) as exc:
        print(f"claim_projector: {exc}. Nothing was written.", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
