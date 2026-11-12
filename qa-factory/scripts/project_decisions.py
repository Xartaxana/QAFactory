"""Atomic writer for the canonical deferred-decision registry.

Rows are matched only by ``field_refs``: JSON pointers, or document refs ``doc:<path under qa-factory>[#<anchor>]`` for a hole
that is a paragraph in a file (``resolve`` writes no config key for those).  Prose is never used as identity.
The markdown registry remains human editable; a JSON projection is refreshed after every
write so interrupted writes can be reconciled without inventing a decision.

Exit codes of the CLI (FR-14: the shape of the output is a contract as much as the arguments):
  0  done; the row (or the existing row of a retried key) is printed as JSON.
  1  a crash: an error nothing in `main` catches (any error of `add-finding` other than ValueError / TimeoutError, and every
     ValueError of `add` and `resolve`, whose refusals are still raised). A traceback on stderr.
  2  refused, one stderr line, nothing written (a bad scope, missing words, a busy registry, argparse's own refusals).
     `stand-account` (HF8-9) and `stand-frontend` (HF8-10) refuse the same way: one stderr line with its door, exit 2, config.json and the registry untouched; the
     same record again exits 0 with `"unchanged": true`.
  3  `add-finding` only: the key is already recorded under DIFFERENT content. The finding exists (the line names its id), so a
     caller that only needs the finding on record has nothing left to write; the text is the same refusal line as before.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import sys
import tempfile
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit
import grammar as G
from hooklib import sorted_paths

# The addressee of a finding about the factory (`scope`), and what each word means - the meanings are
# `references/templates/factory-backlog.md`'s own words, shortened. ONE constant, imported by the dashboard
# (`factory_dashboard.tab_factory`), by the CLI's `--scope` choices and by the refusal below.
# FR-13 debt: closed variety living in code, not in a data file (design/factory-rules-debt.md).
# TP1-15045, 02.10: the conductor met `invalid finding scope` as a bare traceback with no word named,
# invented the scope `handoff.py REQUIRED_LISTS / handoff_check.py / driver S7 entry`, and the finding that
# the factory's own S7 form had no legal answer was never recorded.
FINDING_SCOPES = {
    "local-urgent": "breaks runs here and now (a broken schema, a dead hook): fix in this project's factory "
                    "before the next story",
    "local-calibration": "an inconvenience with no acute pain (numbering, report noise): no deadline, revisited "
                         "when several similar findings accumulate",
    "upstream-candidate": "a candidate for the shared plugin canon; passing it upstream is a human decision, "
                          "not automatic",
}
SCOPE_SHOWN = 60            # how much of a refused word the refusal repeats; the rest is cut with an ellipsis


def _shown(text) -> str:
    """The ONE cut of a refused or echoed word: at most `SCOPE_SHOWN` characters, the rest an ellipsis."""
    text = str(text)
    return text if len(text) <= SCOPE_SHOWN else text[:SCOPE_SHOWN] + "..."


def scope_refusal(scope) -> str:
    """FR-1: what was refused, what was expected (the three words, each with its meaning) and how to satisfy it."""
    return (f"invalid finding scope {_shown(scope)!r}: the scope is the finding's addressee, exactly one of "
            + "; ".join(f"`{word}` - {meaning}" for word, meaning in FINDING_SCOPES.items())
            + ". A place in the code or a topic is not a scope: it goes into --essence or --witness.")


HEADING = "## Deferred decisions (onboarding/gates)"
HEADER = ["id", "essence + where the marker is", "asked", "ripeness trigger", "created",
          "status", "decision with witness", "field_refs", "scope", "owner", "trigger_type",
          "trigger_value", "resolution_ref"]
FB_HEADING = "## Findings about the factory"
FB_HEADER = ["id", "essence", "scope", "witness/details", "created", "status", "decision"]


def _cells(line: str) -> list[str]:
    """The cells of one table row. A row is split only on an UNESCAPED pipe, and only then unescaped: the writer
    (`_escape`) turns a `|` of a person's words into `\\|`, so splitting on every pipe first would shift the columns.
    The one reader is `grammar.split_cells` (G2-10)."""
    return G.split_cells(line)


def _table_rows(text: str, heading: str, id_pattern: str) -> list[dict]:
    """The one markdown-table reader (B-309 t-422): the rows of the table under the `## ` section named `heading` (the first
    row of the table is its header, the separator row is skipped), as {column: cell}; a row is kept only when its `id` cell
    matches `id_pattern` in full, in any case."""
    active = False; columns: list[str] = []; rows: list[dict] = []
    for line in text.splitlines():
        if line.startswith("## "):
            active = line.strip() == heading
            columns = []
            continue
        if not active or not line.lstrip().startswith("|"): continue
        cells = _cells(line)
        if not columns:
            columns = cells; continue
        if cells and set(cells[0]) <= {"-", ":", " "}: continue
        row = {columns[i]: cells[i] if i < len(cells) else "" for i in range(len(columns))}
        if re.fullmatch(id_pattern, row.get("id", ""), re.I): rows.append(row)
    return rows


def parse_rows(text: str) -> list[dict]:
    return _table_rows(text, HEADING, r"DD-\d+")


DEFERRED_PREFIX = "## deferred decisions"
# The ONE pattern of a live deferral marker (OH3-23 Q3): any case of the word, an essence up to the closing bracket; `*` so a bare
# `[DEFERRED:]` is a marker with no essence (AR-28). `resolve` finds live markers by it, `audit_factory` (A13) imports it.
DEFERRED_MARKER = re.compile(r"\[DEFERRED:\s*([^\]]*)\]", re.I)


def deferred_table(text: str) -> dict:
    """The deferred-decisions table(s) as an AUDIT reads them (OH3-23 Q2, AR-13): `{headings, columns, rows}`. A section is any
    `## ` heading that STARTS with "deferred decisions" in any case (a project's variant heading is read, not lost: for an audit
    the unsafe direction is a silent miss); `columns` are the first table's header cells lower-cased; `rows` are the cell lists of
    every row, in every such section, whose first cell is `DD-<n>`. A text with no such section, an empty table or a header only
    gives empties. This is NOT the writer's reader: `parse_rows` keeps the exact `HEADING` and the exact column names."""
    headings: list[str] = []; columns: list[str] = []; rows: list[list[str]] = []
    active = False
    for line in str(text or "").splitlines():
        if line.startswith("## "):
            active = line.strip().lower().startswith(DEFERRED_PREFIX)
            if active: headings.append(line.strip())
            continue
        if not active or not line.lstrip().startswith("|"): continue
        cells = _cells(line)
        if set("".join(cells)) <= set("-: "): continue  # the |---|---| separator line
        if not columns:
            columns = [c.lower() for c in cells]  # the first pipe line of the first section is the header
        elif cells and re.fullmatch(r"DD-\d+", cells[0], re.I):
            rows.append(cells)
    return {"headings": headings, "columns": columns, "rows": rows}


def parse_findings(text: str) -> list[dict]:
    return _table_rows(text, FB_HEADING, r"FB-\d+")


# Every line break `str.splitlines` knows (the reader splits the file with it): CRLF counts once, like LF.
_LINE_BREAKS = G.LINE_BREAKS


def _escape(value: object) -> str:
    """A cell as the table writes it: a `|` escaped, and every line break (LF, CRLF, a lone CR, ...) one space - a row
    is ONE line, so a break would cut it in two and the next write would lose the marker. The body is
    `grammar.escape_cell` (G2-10)."""
    return G.escape_cell(value)


def _read_back(value: object) -> str:
    """A value as the table gives it back after `_escape` wrote it and `_cells` read it: what a retry must be compared with."""
    return _cells("| " + _escape(value) + " |")[0]


_CONTROL_BYTES = re.compile(r"[\x00-\x1f\x7f-\x9f]")


def one_line(words: str) -> str:
    """A person's words on ONE line for the registry cell: every run of whitespace, and every control character
    (FR-29), becomes a single space. The file the words came from stays verbatim; only the row is collapsed."""
    return " ".join(_CONTROL_BYTES.sub(" ", words).split())


def words_digest(words: str) -> str:
    """12 hex characters of sha256 over the words as the row holds them: the spec's formula `" ".join(text.split())`
    (t-974 section 3) applied to the text AFTER every control character became a space (`one_line`), so a key is
    recomputable from the row's own text. The same words (CRLF or LF, any spacing, a stray control byte) are the same
    request, other words are another one (a collision is 2^-48 per pair - accepted). Declared, not accidental:
    `stop<BEL>asking` and `stop asking` are one request."""
    return hashlib.sha256(one_line(words).encode("utf-8")).hexdigest()[:12]


def _replace_table(text: str, rows: list[dict], heading: str = HEADING, header: list[str] = HEADER) -> str:
    """Rewrite the table under the `## ` section `heading` (added at the end when the section is absent) with `rows`, columns
    `header`; the rest of the text is kept. The deferred decisions are the default; the findings pass `FB_HEADING`/`FB_HEADER`
    (B-309 e: the findings' copy of this function was equal statement for statement)."""
    lines = text.splitlines(); start = next((i for i, x in enumerate(lines) if x.strip() == heading), None)
    if start is None:
        if lines and lines[-1].strip(): lines.append("")
        lines.extend([heading, ""]); start = len(lines) - 2
    table_start = next((i for i in range(start + 1, len(lines)) if lines[i].lstrip().startswith("|")), None)
    next_heading = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    if table_start is None or table_start >= next_heading: table_start = next_heading
    table_end = table_start
    while table_end < len(lines) and lines[table_end].lstrip().startswith("|"): table_end += 1
    rendered = ["| " + " | ".join(header) + " |",
                "|" + "|".join("---" for _ in header) + "|"]
    rendered += ["| " + " | ".join(_escape(row.get(key, "")) for key in header) + " |" for row in rows]
    return "\n".join(lines[:table_start] + rendered + lines[table_end:]).rstrip() + "\n"


@contextmanager
def lock(root: Path, timeout: float = 10.0):
    # an OS byte lock on a FILE (TR4-2 part D); the older generation's `.project-decisions.lock` FOLDER is never touched
    import event_store as ES
    lock_file = root / "qa-factory" / "state" / "project-decisions.lock"
    try:
        held = ES.take_file_lock(lock_file, timeout, purpose="project decisions", record_holder=True)
    except ES.LockBusy as exc:
        raise TimeoutError(f"project decisions lock is busy; {exc.holder_clause}") from exc
    except ES.LockBroken as exc:
        raise TimeoutError(str(exc)) from exc
    try: yield
    finally: held.release()


def _registry_busy_line(action: str, exc: TimeoutError) -> str:
    """The one stderr line of a refused registry lock, for every CLI handler: a lock that cannot be made says its own sentence
    (no 'another writer', no retry advice); a busy one keeps the busy line and adds the holder clause the lock recorded (FR-1, FR-2)."""
    import event_store as ES
    if isinstance(exc.__cause__, ES.LockBroken):
        return f"project_decisions: {action} refused - {exc}"
    line = f"project_decisions: {action} refused - the registry is busy (another writer); run the same command again"
    cause = exc.__cause__
    holder = cause.holder_clause if getattr(cause, "holder", None) else ""
    return f"{line} ({holder})" if holder else line


def _atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as out:
            out.write(text); out.flush(); os.fsync(out.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp): os.unlink(temp)


# TP1-15045: `project_decisions.py add --field-ref "/gate_a/design_reviews"` came back
# from Git Bash (MSYS) as "C:/Program Files/Git/gate_a/design_reviews" — MSYS rewrites any
# argument that starts with a bare `/` into an absolute Windows path rooted at the Git
# install dir, because it looks like a POSIX path. The orchestrator tried twice and gave up;
# three factory findings never reached a registry. The tail after the install root
# holds the pointer's own text unchanged, so it is recovered rather than refused.
_MSYS_REWRITE_RE = re.compile(r"(?i)^[a-z]:[\\/](?:.*[\\/])?git(?:\s*\(x86\))?[\\/](.+)$")


DOC_PREFIX = "doc:"
_DRIVE = re.compile(r"^[A-Za-z]:")


def _doc_ref(item: str) -> str:
    """OH2-6 (b2): a ref naming a DOCUMENT, `doc:<path under qa-factory>[#<anchor>]`, for a row whose hole is a paragraph in a
    file and not a key of config.json (so `resolve` has no config pointer to write). Normalized: the prefix lower-case,
    backslashes to `/`, the path part stripped. The path part must be non-empty and relative: no `..`, no drive, no leading
    `/` - a document ref never leaves `qa-factory/`. Anything else is refused naming the form (FR-1, AR-9)."""
    path, hash_mark, anchor = item[len(DOC_PREFIX):].replace("\\", "/").partition("#")
    path = path.strip()
    if not path or path.startswith("/") or _DRIVE.match(path) or ".." in path.split("/"):
        raise ValueError("a document ref is doc:<path under qa-factory>[#<anchor>], e.g. "
                         f"doc:strategy/test-strategy.md#risk-and-impact-scale; got {_shown(item)!r}")
    return DOC_PREFIX + path + hash_mark + anchor


def _refs(value: str | list[str]) -> list[str]:
    raw = value if isinstance(value, list) else [x.strip() for x in str(value).split(",")]
    fixed = []
    for item in raw:
        item = str(item).strip()
        if not item:
            continue
        if item[:len(DOC_PREFIX)].lower() == DOC_PREFIX:
            fixed.append(_doc_ref(item))
            continue
        normalized = item.replace("\\", "/")
        rewritten = _MSYS_REWRITE_RE.match(normalized)
        if rewritten:
            normalized = "/" + rewritten.group(1)
        elif not normalized.startswith("/"):
            # A pointer without its leading `/` (typed by hand, or from a shell that ate it) —
            # the pointer text itself is not in question, only the missing marker.
            normalized = "/" + normalized
        fixed.append(normalized)
    result = sorted(set(fixed))
    if not result:
        raise ValueError("field_refs must contain JSON pointers or doc:<path> refs")
    return result


def _paths(root: Path) -> tuple[Path, Path]:
    import runtime_paths as RP      # a carried record: records/, or state/ in a project not yet re-onboarded
    return root / "qa-factory" / "factory-backlog.md", RP.record(root, "project-decisions.json")


def _persist(root: Path, text: str, rows: list[dict]) -> None:
    backlog, projection = _paths(root)
    updated = _replace_table(text, rows)
    _atomic(backlog, updated)
    payload = {"schema_version": 1, "generated_at": datetime.now(timezone.utc).isoformat(),
               "source": "qa-factory/factory-backlog.md", "findings": parse_findings(updated),
               "deferred_decisions": rows}
    _atomic(projection, json.dumps(payload, indent=2, ensure_ascii=False) + "\n")


RECORDED_EARLIER_EXIT = 3     # the CLI's exit for FindingRecordedEarlier (module docstring)


class FindingRecordedEarlier(ValueError):
    """The idempotency key is already recorded under different content. A ValueError, so every direct caller (the pre-tool
    guard) still sees a refusal; the CLI maps it to its own exit code, which is the structured signal (never the words)."""


_REQUIRED = "essence, witness and idempotency_key are required"
CHANGE_REQUEST = "change-request"        # the key class of a person's request to change the factory (CL1-5)


def add_finding(root: Path, *, essence: str, scope: str, witness: str,
                idempotency_key: str) -> dict:
    """Append one canonical FB row; retrying the same key returns the existing row."""
    if scope not in FINDING_SCOPES:
        raise ValueError(scope_refusal(scope))
    if not all(str(value).strip() for value in (essence, witness, idempotency_key)):
        raise ValueError(_REQUIRED)
    backlog, projection = _paths(root)
    with lock(root):
        text = backlog.read_text(encoding="utf-8") if backlog.exists() else "# Findings about the factory itself\n"
        findings = parse_findings(text)
        marker = f"idempotency:{idempotency_key}"
        # END-anchored: the writer's own marker is always the last thing in the cell, so a key that is a prefix of
        # another (`launch-a` / `launch-ab`), or a marker typed inside a person's words, never answers for it.
        existing = next((row for row in findings if row.get("witness/details", "").endswith("; " + marker)), None)
        if existing:
            # Compared with the row AS THE TABLE READS IT BACK (a newline is a space, a `|` is escaped and restored),
            # not with the raw argument: a retry of a multi-line witness is the same finding, not a clash.
            if (existing.get("essence") != _read_back(essence) or existing.get("scope") != scope or
                    existing.get("witness/details") != _read_back(f"{witness}; {marker}")):
                raise FindingRecordedEarlier(
                    f"idempotency key reused with different finding content: {' '.join(str(idempotency_key).split())} "
                    f"is {existing.get('id')} (essence '{_shown(existing.get('essence', ''))}'); "
                    "that finding is recorded - nothing to do; "
                    "a different finding needs a different key")
            return existing
        next_id = max([int(row["id"].split("-")[1]) for row in findings] or [0]) + 1
        row = {"id": f"FB-{next_id}", "essence": essence, "scope": scope,
               "witness/details": f"{witness}; {marker}", "created": date.today().isoformat(),
               "status": "open", "decision": "—"}
        findings.append(row)
        updated = _replace_table(text, findings, FB_HEADING, FB_HEADER)
        _atomic(backlog, updated)
        payload = {"schema_version": 1, "generated_at": datetime.now(timezone.utc).isoformat(),
                   "source": "qa-factory/factory-backlog.md",
                   "findings": findings, "deferred_decisions": parse_rows(updated)}
        _atomic(projection, json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    _refresh(root)
    return row


def _refresh(root: Path) -> None:
    """Refresh visible projections after our registry lock has been released."""
    try:
        import dashboard_refresh
        dashboard_refresh.refresh_project(root)
    except Exception as exc:
        stale = root / "qa-factory" / "state" / "project-decisions-refresh-stale.json"
        _atomic(stale, json.dumps({"schema_version": 1, "status": "stale",
                                  "error": str(exc),
                                  "recorded_at": datetime.now(timezone.utc).isoformat()}, indent=2) + "\n")


_LIST_INDEX = re.compile(r"0|[1-9][0-9]{0,8}")


def _set_pointer(document: dict, pointer: str, value) -> None:
    """Put `value` at a JSON pointer, creating the objects on the way. A step through a LIST (`/environments/1/credentials_by_role/x`)
    reads the part as a decimal index inside the list's length (HF8-9): an index beyond it, `-1`, a name, or a leading zero is the
    same `ValueError` as any step that is not an object - nothing is created in a list, so a wrong index never writes a stray entry."""
    if not pointer.startswith("/"):
        raise ValueError("field reference must be a JSON pointer")
    parts = [part.replace("~1", "/").replace("~0", "~") for part in pointer[1:].split("/")]
    node = document

    def step(container, part):
        """The key (or index) of `part` in `container`, or a ValueError: the one place the two container kinds differ."""
        if isinstance(container, dict):
            return part
        if isinstance(container, list) and _LIST_INDEX.fullmatch(part) and int(part) < len(container):
            return int(part)
        raise ValueError(f"cannot set {pointer}")
    for part in parts[:-1]:
        key = step(node, part)
        if isinstance(node, dict):
            node = node.setdefault(key, {})
        else:
            node = node[key]
    node[step(node, parts[-1])] = value


def upsert(root: Path, *, field_refs: list[str], essence: str, asked: str, scope: str,
           owner: str, trigger_type: str = "manual", trigger_value: str = "") -> dict:
    refs = _refs(field_refs)
    if not asked.strip(): raise ValueError("asked evidence is required")
    if trigger_type not in {"manual", "capability_verified", "story_count", "date"}:
        raise ValueError("invalid trigger_type")
    if trigger_type == "story_count" and (not str(trigger_value).isdigit() or int(trigger_value) < 1):
        raise ValueError("story_count trigger_value must be a positive integer")
    if trigger_type == "date": date.fromisoformat(str(trigger_value).removesuffix("Z"))
    backlog, _ = _paths(root)
    with lock(root):
        text = backlog.read_text(encoding="utf-8") if backlog.exists() else "# Findings about the factory itself\n"
        rows = parse_rows(text)
        needle = ",".join(refs)

        def stored(r: dict) -> set:    # a hand-edited cell: refused naming the row and the file, never skipped (FR-1, FR-59)
            try:
                return set(_refs(r.get("field_refs", "")))
            except ValueError as exc:
                raise ValueError(f"row {r.get('id')} of qa-factory/factory-backlog.md has a field_refs cell that cannot be read "
                                 f"({exc}); correct that cell to a JSON pointer or doc:<path>[#<anchor>], then run this again") from exc
        existing = next((r for r in rows if r.get("status") == "open" and
                         r.get("field_refs", "") and stored(r) == set(refs)), None)
        if existing: return existing
        next_id = max([int(r["id"].split("-")[1]) for r in rows] or [0]) + 1
        row = {"id": f"DD-{next_id}", "essence + where the marker is": essence,
               "asked": asked, "ripeness trigger": f"{trigger_type}:{trigger_value}" if trigger_value else trigger_type,
               "created": date.today().isoformat(), "status": "open", "decision with witness": "—",
               "field_refs": needle, "scope": scope, "owner": owner,
               "trigger_type": trigger_type, "trigger_value": trigger_value, "resolution_ref": ""}
        rows.append(row); _persist(root, text, rows)
    _refresh(root)
    return row


def _marker_forms(content: str, token: str) -> list[str]:
    """Every spelling of the marker `token` stands for that stands in `content` (OH3-23 Q3): the token exactly, and - when the
    token is itself a marker - every marker of the same essence (blanks folded, any case) in another spelling, so `[deferred: x]`
    and `[DEFERRED: x]` are one marker and none is left behind a resolved row. A token that is no marker (a `--marker-text` of
    free form) is matched exactly only."""
    forms = [token] if token and token in content else []
    own = DEFERRED_MARKER.fullmatch(token.strip()) if token else None
    if own:
        key = " ".join(own.group(1).split()).lower()
        for found in DEFERRED_MARKER.finditer(content):
            if found.group(0) not in forms and " ".join(found.group(1).split()).lower() == key:
                forms.append(found.group(0))
    return forms


def resolve(root: Path, decision_id: str, decision: str, resolution_ref: str,
            field_values: dict | None = None, marker_files: list[str] | None = None,
            marker_text: str = "") -> dict:
    if not resolution_ref.strip(): raise ValueError("resolution_ref is required")
    backlog, _ = _paths(root)
    with lock(root):
        text = backlog.read_text(encoding="utf-8"); rows = parse_rows(text)
        matches = [r for r in rows if r["id"].upper() == decision_id.upper()]
        if len(matches) != 1: raise ValueError(f"unknown decision {decision_id}")
        row = matches[0]
        refs = _refs(row.get("field_refs", ""))
        # A document ref (OH2-6 b2) names no config key: it needs no value, and a value given for it stays in the receipt.
        pointers = [ref for ref in refs if not ref.startswith(DOC_PREFIX)]
        field_values = field_values or {}
        missing = sorted(set(pointers) - set(field_values))
        if missing:
            raise ValueError("resolution must provide exact values for field_refs: " + ", ".join(missing))
        config_path = root / "qa-factory" / "config.json"
        # `utf-8-sig`, as `_project_config` reads it: a file that passed the check before `upsert` must not fail here, after it
        config = json.loads(config_path.read_text(encoding="utf-8-sig")) if pointers and config_path.exists() else {}
        before = copy.deepcopy(config) if pointers and config_path.exists() and isinstance(config, dict) else None
        for pointer in pointers:
            _set_pointer(config, pointer, field_values[pointer])
        marker_inputs = [Path(raw) for raw in (marker_files or [])]
        if any(path.is_absolute() or ".." in path.parts for path in marker_inputs):
            raise ValueError("marker file must be a relative path inside project root")
        marker_paths = [(root / raw).resolve(strict=False) for raw in marker_inputs]
        token = marker_text or f"[DEFERRED: {row.get('essence + where the marker is', '')}]"
        # Any live marker matching the supplied token, in any case of the word (OH3-23 Q3), must be named for removal.
        candidates = [config_path] + list((root / "qa-factory" / "strategy").glob("*.md"))
        live = [path.resolve(strict=False) for path in candidates if path.exists() and _marker_forms(path.read_text(encoding="utf-8"), token)]
        if set(live) - set(marker_paths):
            raise ValueError("paired deferred marker remains; name every marker file in this resolution")
        tx_dir = root / "qa-factory" / "state" / "decision-transactions"
        tx_dir.mkdir(parents=True, exist_ok=True)
        receipt_path = tx_dir / f"{decision_id}.json"
        earlier = json.loads(receipt_path.read_text(encoding="utf-8")) if receipt_path.exists() else {}
        recovering = earlier.get("status") == "pending"
        receipt = {"schema_version": 1, "decision_id": decision_id, "status": "pending",
                   "field_values": field_values,
                   "marker_files": [str(p).replace("\\", "/") for p in marker_inputs],
                   "marker_text": token, "decision": decision, "resolution_ref": resolution_ref}
        # HF8-9: the receipt is also the record of WHEN the config was written and what it held before, so a story's revert
        # (`config_contract.recorded_writes`) keeps the project's own answer. A recovery keeps the first attempt's pair: the config
        # it reads now may already hold the write.
        if before is not None:
            receipt["recorded_at"] = str(earlier.get("recorded_at") or "") if recovering and earlier.get("before") is not None \
                else datetime.now(timezone.utc).isoformat(timespec="seconds")
            receipt["before"] = earlier["before"] if recovering and earlier.get("before") is not None else before
        _atomic(receipt_path, json.dumps(receipt, indent=2, ensure_ascii=False) + "\n")
        if pointers and config_path.exists():
            _atomic(config_path, json.dumps(config, indent=2, ensure_ascii=False) + "\n")
        for path in marker_paths:
            if not path.is_file(): raise ValueError(f"marker file is absent: {path}")
            content = path.read_text(encoding="utf-8")
            forms = _marker_forms(content, token)
            if not forms:
                if not recovering: raise ValueError(f"exact marker not found in {path}")
            else:
                for form in forms: content = content.replace(form, "")
                _atomic(path, content)
        row["status"] = "closed"; row["decision with witness"] = decision
        row["resolution_ref"] = resolution_ref
        _persist(root, text, rows)
        receipt["status"] = "complete"
        _atomic(receipt_path, json.dumps(receipt, indent=2, ensure_ascii=False) + "\n")
    _refresh(root)
    return row


def recover_pending(root: Path) -> list[str]:
    """Finish transactions whose config/marker write was interrupted before DD closure."""
    recovered = []
    tx_dir = root / "qa-factory" / "state" / "decision-transactions"
    for path in sorted_paths(tx_dir.glob("DD-*.json")) if tx_dir.exists() else []:
        receipt = json.loads(path.read_text(encoding="utf-8"))
        if receipt.get("status") != "pending": continue
        resolve(root, receipt["decision_id"], receipt["decision"], receipt["resolution_ref"],
                receipt["field_values"], receipt.get("marker_files", []), receipt.get("marker_text", ""))
        recovered.append(receipt["decision_id"])
    return recovered


def due(row: dict, *, verified_capabilities: set[str] | None = None, stories_since: int = 0,
        today: date | None = None) -> bool:
    kind, value = row.get("trigger_type", "manual"), row.get("trigger_value", "")
    if kind == "capability_verified": return value in (verified_capabilities or set())
    if kind == "story_count": return str(value).isdigit() and stories_since >= int(value)
    if kind == "date":
        try: return (today or date.today()) >= date.fromisoformat(str(value).removesuffix("Z"))
        except ValueError: return False
    return False


# --- HF8-9: a fact of the stand, heard at a gate, goes into the project's config ---------------------------------------------
# On TP1-12586 the gate asked for an account the person had already named; the answer lived only in the story. The fact is
# written through the two writers this module already has (`upsert` + `resolve`: one transaction, a receipt, a registry row that
# keeps the person's words, no second writer of config.json, AR-14); what is new is the checking BEFORE the first of them, so a
# refusal leaves no open row behind.
def _ptr(part: str) -> str:
    """One JSON-pointer segment: `~` and `/` of a role's name escaped (RFC 6901), so a role `admin/ro` is one key."""
    return str(part).replace("~", "~0").replace("/", "~1")


def _stand_of(config: dict, name: str = "") -> tuple:
    """(index, entry) of the `environments[]` row a fact of the stand is written to: the stand `name` when one is given, else the
    only row. ONE selection for every stand fact (the account here, the address of the UI in HF8-10). A refusal names the stands
    and the flag that picks one (FR-1): no row at all, an unknown or ambiguous name, several rows and no name - nothing is guessed,
    so a fact never lands on a stand the person did not mean."""
    raw = config.get("environments") if isinstance(config.get("environments"), list) else []
    rows = [(i, entry) for i, entry in enumerate(raw) if isinstance(entry, dict)]
    if not rows:
        raise ValueError("config.json has no `environments[]` row to hold this: the stand is not recorded yet. Record it first "
                         "(/qa-factory:qa-onboarding, topic 2); nothing was written")
    names = ", ".join(f"`{entry.get('name')}`" for _, entry in rows)
    want = str(name or "").strip()
    if want:
        hit = [(i, entry) for i, entry in rows if str(entry.get("name") or "") == want]
        if len(hit) != 1:
            raise ValueError(f"no single stand is named {_shown(want)!r} (the stands: {names}); repeat with --stand <one of them>")
        return hit[0]
    if len(rows) == 1:
        return rows[0]
    raise ValueError(f"the project records {len(rows)} stands ({names}); name the one with --stand <name>")


def _project_config(root: Path, what: str) -> dict:
    """The project's `qa-factory/config.json` as an object, for a stand fact (`what`: "the account", "the address of the UI") to be
    recorded in. A missing, unreadable or non-object file is a refusal with its door, never a created or guessed file (FR-1)."""
    config_path = Path(root) / "qa-factory" / "config.json"
    if not config_path.exists():
        raise ValueError(f"{config_path} does not exist: there is no project config to record {what} in. Run "
                         "/qa-factory:qa-onboarding first; nothing was written")
    try:
        config = json.loads(config_path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        raise ValueError(f"{config_path} is not readable JSON; repair it (or restore it) and repeat; nothing was written") from None
    if not isinstance(config, dict):
        raise ValueError(f"{config_path} does not hold a JSON object; repair it and repeat; nothing was written")
    return config


def _refuse_unsafe_role(role: str) -> None:
    """A role the decision registry cannot carry in a pointer (`_refs` cuts at a comma and a bar, turns `\\` into `/`, a line
    break splits the row) is a refusal before `upsert`: the registry row would be written and `resolve` would then fail, leaving
    an open decision. The same refusal serves a role the person names and one the config already holds under another spelling."""
    if any(mark in role for mark in (",", "|", "\\")) or _CONTROL_BYTES.search(role) or _LINE_BREAKS.search(role):
        raise ValueError(f"the role {_shown(role)!r} holds a comma, a bar, a backslash or a line break, which the decision registry "
                         "cannot carry in a pointer; name the role in plain words without them; nothing was written")


def record_stand_account(root: Path, *, stand: str, role: str, user_key: str, secret_key: str, words: str,
                         replace: bool = False) -> dict:
    """Record `environments[<stand>].credentials_by_role[<role>] = "<user key> / <secret key>"` on a person's word. Names only: the
    two keys live in the env file, never here. Every refusal is a ValueError with its door and writes nothing (all checks come
    before `upsert`); the same record again is `unchanged` and writes nothing. Returns what the CLI prints."""
    import config_contract as CC
    from gate_preflight import account_keys, role_candidates
    root = Path(root)
    config = _project_config(root, "the account")
    index, entry = _stand_of(config, stand)
    role = str(role).strip()
    if not role:
        raise ValueError("--role is empty: name the account's role on the stand (administrator, a plain user, ...); nothing was written")
    _refuse_unsafe_role(role)
    if CC.reserved_role(role):
        raise ValueError(f"the role {_shown(role)!r} is a reserved form (`default`, `env:...`, `created:...`): a capture reads those "
                         "before any role, so this one could never be reached; choose another role name; nothing was written")
    for label, name in (("--user-key", user_key), ("--secret-key", secret_key)):
        if not CC.KEY_NAME_RE.fullmatch(str(name)):
            raise ValueError(f"{label} {_shown(name)!r} is not a variable NAME (letters, digits and `_`, no `=`): give the name of the "
                             "variable in the env file, never its value; nothing was written")
    if user_key == secret_key:
        raise ValueError(f"--user-key and --secret-key are the same name ({user_key}): the login and the password are two variables, "
                         "so one name cannot hold both and the account would look recorded while no sign-in could read it; give "
                         "two different names; nothing was written")
    note = f"{user_key} / {secret_key}"
    if account_keys(note) != [user_key, secret_key]:
        raise ValueError(f"the gate cannot read the names {user_key} / {secret_key} back from a role's note (a name needs capitals "
                         "and an underscore): either use `--as env:USER_KEY/SECRET_KEY` for this account in the case, or rename the "
                         "variables in the env file; nothing was written")
    environment = config.get("environment") if isinstance(config.get("environment"), dict) else {}
    named = bool(str(environment.get("env_file") or "").strip()) or any(str(x).strip() for x in (environment.get("env_files") or []))
    if named:
        held = set(CC.env_key_names(root, environment))
        absent = [name for name in (user_key, secret_key) if name not in held]
        if absent:
            where = str(environment.get("env_file") or (environment.get("env_files") or ["the env file"])[0])
            raise ValueError(f"{', '.join(absent)} is in neither {where} nor the process environment: add the name(s) to that file "
                             "(the password goes there, never into the chat or config.json) and repeat; nothing was written")
    roles = entry.get("credentials_by_role") if "credentials_by_role" in entry else {}
    if not isinstance(roles, dict):
        raise ValueError("the stand's credentials_by_role is not an object; repair it by hand (a role name -> `U / S`) and repeat; "
                         "nothing was written")
    result = {"stand": str(entry.get("name") or ""), "role": role, "keys": [user_key, secret_key], "names_checked": named,
              "unchanged": False}
    if not named:
        result["note"] = "names not checked: the config names no env file"
    # The role the gate reads (`role_candidates`, the one reader of a role's spelling): `default user` and `default_user` are ONE
    # role there, so a second spelling must not become a twin row that turns the first one's lookups into a refusal (AR-13).
    held = role_candidates(roles, role)
    if len(held) > 1:
        raise ValueError(f"the stand already records several roles that {_shown(role)!r} could mean ({', '.join(_shown(k) for k in held)}); "
                         "name one of them exactly, or remove the extra ones by hand; nothing was written")
    if held:
        role = held[0]                      # the real key: recorded again (`unchanged`) or replaced in place, never a twin
        result["role"] = role
        _refuse_unsafe_role(role)
        if roles[role] == note:
            result["unchanged"] = True
            return result
        if not replace:
            raise ValueError(f"the stand already records the role {_shown(role)!r} with another entry; to replace it say so with "
                             "--replace (the old entry is overwritten); nothing was written")
    ref = _refs([f"/environments/{index}/credentials_by_role/{_ptr(role)}"])[0]
    row = upsert(root, field_refs=[ref], essence=f"account of the role {role} on the stand {result['stand']}",
                 asked=f"gate A: which variables of the env file hold the account of the role {role}?", scope="project", owner="user")
    closed = resolve(root, row["id"], words, f"stand-account {result['stand']}", {ref: note})
    result["decision"] = closed["id"]
    return result


def _record_stand_fact(action: str, args, record) -> dict:
    """The CLI of a stand fact (`stand-account`, `stand-frontend`): the person's words resolved first, then `record(root, words=...)`;
    a refusal is one stderr line and exit 2 (as `add-finding`). ONE wrapper for every stand fact."""
    try:
        import person_words
        words = person_words.read(None, args.words_file, "--decision")
        return record(args.root.resolve(), words)
    except ValueError as exc:
        print(f"project_decisions: {action} refused - {exc}", file=sys.stderr)
        raise SystemExit(2)
    except TimeoutError as exc:
        print(_registry_busy_line(action, exc), file=sys.stderr)
        raise SystemExit(2)


def _record_stand_account(args) -> dict:
    """The `stand-account` action."""
    return _record_stand_fact("stand-account", args, lambda root, words: record_stand_account(
        root, stand=args.stand, role=args.role, user_key=args.user_key, secret_key=args.secret_key, words=words, replace=args.replace))


def _same_value(held, wanted) -> bool:
    """Is what the config holds at a pointer already the wanted text (an absent or empty value is not)?"""
    return isinstance(held, str) and held.strip() == wanted


def _frontend_block_form(config: dict, root: Path, rows: list, key: str, stand: str, api_path: str, result: dict) -> dict:
    """The block form of `record_stand_frontend` (zero or one stand): `{pointer: (new, held)}` for `environment.frontend.url_key`
    (and `api_path`), after every check; `result` is filled with what the CLI prints. The variable is looked up in the files the
    GATE reads (`gate_preflight.configured_env_files` and `env_values`, one reading: AR-13, FR-37) and the process environment; a
    config that names no file leaves the variable unchecked and says so (`names not checked`), as `stand-account` does."""
    import config_contract as CC
    import env_probe
    from gate_preflight import configured_env_files, env_values
    if stand:
        _stand_of(config, stand)                    # a named stand must be the project's own (the refusal names the stands)
    environment = config.get("environment") if "environment" in config else {}
    block = environment.get("frontend") if isinstance(environment, dict) and "frontend" in environment else {}
    if not isinstance(environment, dict) or not isinstance(block, dict):
        raise ValueError("`environment` or its `frontend` in config.json is not an object; repair it by hand and repeat; "
                         "nothing was written")
    if rows and (rows[0].get("frontend") or str(rows[0].get(env_probe.FRONTEND_ALIAS_KEY) or "").strip()):
        raise ValueError("the stand's own entry in environments[] already names its UI address, and the reader never lets the block "
                         "override it: change the address in that entry by hand (frontend.url), or remove it and repeat; "
                         "nothing was written")
    problems = CC.frontend_errors("environment.frontend", {"url_key": key, "api_path": api_path}, "url_key")
    if problems:
        raise ValueError("; ".join(problems) + "; nothing was written")
    files, _how = configured_env_files(environment, root)
    result["names_checked"] = bool(files)
    if files:
        held = env_values(files).get(key)
        if held is None:
            shown = ", ".join(os.path.relpath(p, root).replace("\\", "/") if Path(p).drive == Path(root).drive else Path(p).name
                              for p in files)
            gone = any(not Path(p).is_file() for p in files)
            raise ValueError(f"{key} is in neither {shown} nor the process environment: add the variable to that file (the address "
                             "goes there, not into config.json) and repeat"
                             + ("; a named file is not there at all: fix environment.env_file / env_files (or restore the file)"
                                if gone else "") + "; nothing was written")
        if not str(held).strip().lower().startswith(("http://", "https://")):
            raise ValueError(f"{key} does not hold an http(s) address: pick the variable that holds the UI's address, or correct the "
                             "file and repeat; nothing was written")
    else:
        result["note"] = "names not checked: the config names no env file"
    wanted = {"/environment/frontend/url_key": (key, block.get("url_key"))}
    if api_path:
        wanted["/environment/frontend/api_path"] = (api_path, block.get("api_path"))
    result.update(form="block", stand=str((rows[0].get("name") if rows else "") or ""), key=key)
    return wanted


def _frontend_entry_form(config: dict, url: str, stand: str, api_path: str, result: dict) -> dict:
    """The entry form of `record_stand_frontend` (two stands or more): `{pointer: (new, held)}` for the named stand's
    `frontend.url` (and `api_path`), after every check (an address with a login or no host is refused)."""
    import config_contract as CC
    index, entry = _stand_of(config, stand)
    problems = CC.frontend_errors(f"environments[{index}].frontend", {"url": url, "api_path": api_path}, "url")
    parts = urlsplit(url)
    if not problems and (not parts.hostname or re.search(r"\s", url) or "@" in parts.netloc):
        problems = ["--url must be an http(s) address with a host and without a login (`user:pass@` is refused: a login is "
                    "never recorded in a URL)"]
    if problems:
        raise ValueError("; ".join(problems) + "; nothing was written")
    block = entry.get("frontend") if "frontend" in entry else {}
    if not isinstance(block, dict):
        raise ValueError("the stand's `frontend` in config.json is not an object; repair it by hand and repeat; nothing was written")
    wanted = {f"/environments/{index}/frontend/url": (url, block.get("url"))}
    if api_path:
        wanted[f"/environments/{index}/frontend/api_path"] = (api_path, block.get("api_path"))
    result.update(form="entry", stand=str(entry.get("name") or ""),
                  note="the stand's address is part of its identity: an earlier confirmation of this stand is asked again")
    return wanted


def record_stand_frontend(root: Path, *, key: str = "", url: str = "", stand: str = "", api_path: str = "", words: str,
                          replace: bool = False) -> dict:
    """Record the stand's UI address on a person's word (HF8-10). The FORM depends on the number of stands, as `env_probe.frontend_of`
    reads it: zero or one `environments[]` row -> `environment.frontend.url_key = <KEY>` (the NAME of the env-file variable, `--key`);
    two or more -> `environments[<stand>].frontend.url = <address>` of the named stand (`--url`, `--stand`), because the reader does
    not see the block there. A form that does not fit the count is refused with the reader's own door text (`frontend_door`). Every
    refusal is a ValueError with its door and writes nothing (all checks come before `upsert`, so no open registry row is left); the
    same record again is `unchanged`; another value is replaced only with `replace`. `api_path` (optional) goes beside the address.
    No value of the env file or the address is ever put into a message or into the output."""
    import env_probe
    root = Path(root)
    config = _project_config(root, "the address of the UI")
    rows = [row for row in config.get("environments") or [] if isinstance(row, dict)] if isinstance(config.get("environments"), list) else []
    door = env_probe.frontend_door(config)
    key, url, api_path = str(key or "").strip(), str(url or "").strip(), str(api_path or "").strip()
    if bool(key) == bool(url):
        raise ValueError("give exactly one of --key (the NAME of the env-file variable that holds the UI's address) or --url (the "
                         f"address itself); the config reads it at {door['set']}; nothing was written")
    result = {"form": "", "unchanged": False}
    if len(rows) <= 1:
        if url:
            raise ValueError(f"this project records {len(rows)} stand(s): the address of the UI is a variable NAME of the env file, "
                             f"recorded at {door['set']}: repeat with --key <NAME> instead of --url; nothing was written")
        wanted = _frontend_block_form(config, root, rows, key, stand, api_path, result)
    else:
        if key:
            raise ValueError(f"this project records {len(rows)} stands: the block key serves only one; set the address in the entry of "
                             f"the stand - {door['set']}: repeat with --stand <name> --url <address>; nothing was written")
        wanted = _frontend_entry_form(config, url, stand, api_path, result)
    changed = {ref: new for ref, (new, old) in wanted.items() if not _same_value(old, new)}
    if not changed:
        result["unchanged"] = True
        return result
    clash = [ref for ref in changed if wanted[ref][1] not in (None, "") and not replace]
    if clash:
        raise ValueError("the project already records another value at " + ", ".join(clash) + "; to replace it say so with --replace "
                         "(the old value is overwritten); nothing was written")
    refs = _refs(list(changed))
    row = upsert(root, field_refs=refs, essence=f"address of the UI of the stand {result['stand'] or '(the only one)'}",
                 asked="gate A: which variable of the env file (or which address) is the stand's UI?", scope="project", owner="user")
    closed = resolve(root, row["id"], words, f"stand-frontend {result['stand'] or 'block'}", {ref: changed[ref] for ref in refs})
    result["decision"] = closed["id"]
    return result


def _record_stand_frontend(args) -> dict:
    """The `stand-frontend` action."""
    return _record_stand_fact("stand-frontend", args, lambda root, words: record_stand_frontend(
        root, key=args.key, url=args.url, stand=args.stand, api_path=args.api_path, words=words, replace=args.replace))


def _scope_arg(value: str) -> str:
    """`--scope` of `add-finding`: the word, or a refusal that names the three words with their meanings (the
    `choices` below lists them in `--help`, but argparse's own message for a bad choice carries no meaning)."""
    if value not in FINDING_SCOPES:
        raise argparse.ArgumentTypeError(scope_refusal(value))
    return value


def _finding_words(args) -> tuple:
    """(witness, key) for `add-finding`, resolved ONCE before the registry is locked: a refusal writes nothing.
    A person's words travel in a file (cmd.exe cuts a multi-line value at its first break, M30), read through
    `person_words`; the row holds them on one line and the key is completed with their digest, so the same words are
    the same finding and other words never share a row. The code reads bytes; whether the words are a request is the
    caller's judgment. The ONE place the code reads a key's class (the prefix before its first `:`): an inline
    `--witness` under a `change-request` key is refused, because inline there is neither a digest (the same words by
    the two routes would be two rows) nor a safe retry (two different requests would answer "nothing to do")."""
    key = args.idempotency_key
    if args.words_file is not None:
        import person_words
        words = person_words.read(args.witness, args.words_file, "--witness")
        if not str(key).strip():
            raise ValueError(_REQUIRED)
        return one_line(words), f"{key}:{words_digest(words)}"
    if args.witness is None:
        raise ValueError("add-finding needs --witness <one line> or --words-file <path> (a person's "
                         "words as they were given); neither was given")
    if str(key).strip().partition(":")[0].strip().casefold() == CHANGE_REQUEST:
        raise ValueError(f"the key {_shown(' '.join(str(key).split()))!r} is a person's change request, and its words came "
                         "inline (--witness); a request's words are kept as they were given, in a file: run the same call "
                         "with --words-file <file> (UTF-8, the person's words) instead of --witness; nothing was recorded")
    return args.witness, key


def _record_finding(args) -> dict:
    """The `add-finding` action: its words resolved, the row written; a refusal is one stderr line and exit 2, except a key
    recorded earlier under other content: the same kind of line, exit `RECORDED_EARLIER_EXIT` (3)."""
    try:
        witness, key = _finding_words(args)
        return add_finding(args.root.resolve(), essence=args.essence, scope=args.scope,
                           witness=witness, idempotency_key=key)
    except FindingRecordedEarlier as exc:
        print(f"project_decisions: add-finding refused - {exc}", file=sys.stderr)
        raise SystemExit(RECORDED_EARLIER_EXIT)
    except ValueError as exc:
        # A refusal is one line the caller can read, never a traceback (FR-1, FR-47). `add_finding` itself
        # still raises: the pre-tool guard calls it that way (guard_pre_tool.py).
        print(f"project_decisions: add-finding refused - {exc}", file=sys.stderr)
        raise SystemExit(2)
    except TimeoutError as exc:
        print(_registry_busy_line("add-finding", exc), file=sys.stderr)
        raise SystemExit(2)


def _build_parser() -> argparse.ArgumentParser:
    """The command line: one subparser per action (kept out of `main`, which stays short - P21)."""
    parser = argparse.ArgumentParser(); parser.add_argument("--root", type=Path, default=Path.cwd())
    sub = parser.add_subparsers(dest="action", required=True)
    add = sub.add_parser("add"); add.add_argument("--field-ref", action="append", required=True)
    add.add_argument("--essence", required=True); add.add_argument("--asked", required=True)
    add.add_argument("--scope", default="project"); add.add_argument("--owner", default="user")
    add.add_argument("--trigger-type", default="manual"); add.add_argument("--trigger-value", default="")
    finding = sub.add_parser("add-finding"); finding.add_argument("--essence", required=True)
    finding.add_argument("--scope", required=True, type=_scope_arg, choices=list(FINDING_SCOPES),
                         help="the finding's addressee: " + "; ".join(f"{w} = {m}" for w, m in FINDING_SCOPES.items()))
    finding.add_argument("--witness", help="the evidence, one line typed by code; exactly one of --witness / --words-file")
    finding.add_argument("--words-file", help="a file holding a person's own words as they were given (UTF-8), "
                                              "instead of --witness: the row holds them on one line and the key "
                                              "gets a 12-hex digest of them as its tail")
    finding.add_argument("--idempotency-key", required=True)
    close = sub.add_parser("resolve"); close.add_argument("--id", required=True)
    close.add_argument("--decision", help="the person's own words (one line typed by code); "
                                          "exactly one of --decision / --words-file")
    close.add_argument("--words-file", help="a file holding the person's own words as they were "
                                            "given (UTF-8), instead of --decision")
    close.add_argument("--resolution-ref", required=True)
    close.add_argument("--field-values", default=None,
                       help="JSON object mapping every JSON-pointer field_ref to its exact approved value; "
                            "optional when every field_ref is a document ref (`doc:<path>[#<anchor>]`, which names no config key)")
    close.add_argument("--marker-file", action="append", default=[])
    close.add_argument("--marker-text", default="")
    account = sub.add_parser("stand-account", help="record a stand's account (a role and the two env-file variable NAMES that hold "
                                                    "its login and password) in qa-factory/config.json, on a person's word")
    account.add_argument("--stand", default="", help="the stand's name; may be left out when the project records exactly one")
    account.add_argument("--role", required=True, help="the account's role on the stand, in the person's words")
    account.add_argument("--user-key", required=True, help="NAME of the env variable that holds the login")
    account.add_argument("--secret-key", required=True, help="NAME of the env variable that holds the password")
    account.add_argument("--words-file", required=True, help="a file holding the person's own words as they were given (UTF-8)")
    account.add_argument("--replace", action="store_true", help="overwrite the role when the stand records it with another entry")
    front = sub.add_parser("stand-frontend", help="record the address of the stand's UI in qa-factory/config.json, on a person's word: "
                                                   "--key <NAME of the env variable> for a project with one stand, --stand <name> --url "
                                                   "<address> for a project with several")
    front.add_argument("--key", default="", help="NAME of the env-file variable that holds the UI's address (one stand or none)")
    front.add_argument("--url", default="", help="the UI's address itself, for the entry of the named stand (two stands or more)")
    front.add_argument("--stand", default="", help="the stand's name (required with --url)")
    front.add_argument("--api-path", default="", help="a path through the frontend whose answer is the API's own JSON, e.g. /api/v1/config")
    front.add_argument("--words-file", required=True, help="a file holding the person's own words as they were given (UTF-8)")
    front.add_argument("--replace", action="store_true", help="overwrite another address the project already records")
    sub.add_parser("recover")
    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    decision = None
    if args.action == "resolve":
        # Resolved ONCE, before the registry is locked or read: a refusal closes nothing and
        # writes no receipt (M30: one reader for a person's words, `person_words.py`).
        import person_words
        try:
            decision = person_words.read(args.decision, args.words_file, "--decision")
        except person_words.WordsRefused as exc:
            parser.error(str(exc))
        if decision is None:
            parser.error("resolve needs --decision (one line) or --words-file <path> (the person's "
                         "words as they were given)")
    if args.action == "add": result = upsert(args.root.resolve(), field_refs=args.field_ref,
        essence=args.essence, asked=args.asked, scope=args.scope, owner=args.owner,
        trigger_type=args.trigger_type, trigger_value=args.trigger_value)
    elif args.action == "add-finding": result = _record_finding(args)
    elif args.action == "stand-account": result = _record_stand_account(args)
    elif args.action == "stand-frontend": result = _record_stand_frontend(args)
    elif args.action == "resolve":
        result = resolve(args.root.resolve(), args.id, decision, args.resolution_ref,
                         json.loads(args.field_values) if args.field_values is not None else {},
                         args.marker_file, args.marker_text)
    else:
        result = {"recovered": recover_pending(args.root.resolve())}
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__": main()
