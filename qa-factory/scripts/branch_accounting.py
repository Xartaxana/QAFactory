#!/usr/bin/env python3
"""Branch accounting (G2-11): every sentence of the story's own text has a home in the S2 register, and every branch
of a requirement (a qualifier, a partition, a variant, a refusal) is a row with an id.

THE ONE READER of the register's `## Branches` and `## Source obligations` sections (AR-13, AR-15). It writes nothing
(FR-45). It reconciles; it never decides what is an obligation or a branch - that is the role's judgment (AR-2, AR-7),
and no phrase list is read anywhere (FR-12): units are cut by structure only (list markers, `.!?` + space).

Step 1 (this file) is the S2 exit detector and the two listing doors the role uses:
  python branch_accounting.py                          the S2 exit gate (no arguments; `--root` for tests)
  python branch_accounting.py --units --task <T>       the units of the story's text, `--page N` for the next 200
  python branch_accounting.py --unhomed --task <T>     the units with no home yet (the door of a long refusal)
  python branch_accounting.py --attachments --task <T> the files of the story and of its kept tickets, each with the
                                                       call that opens it (the role judges the file, never code)
`attachments_view(task_root)` (step 1c) is the ONE reader of what gate A and the report say about attachments; with
`inventory_sources` and `scope_class` it is also the one read of the inventory's list for the units and the files (AR-13).

Sources (the owner's word 30.10.2026, F-1a): the story's own snapshot `work/ticket-snapshot.json`, and the snapshot of
every linked ticket the person's review KEPT (`work/source-inventory.json`, `relevance: relevant`, `status: read`, a
`snapshot_ref`). Attachments are not units. Nothing else is read: no run archive, no stand, no other story.
A kept ticket stays in scope: the source review decided that, and S2 does not decide it again. A ticket none of whose sentences
obliges anything is a zero outcome, written as a home for each unit (`not_obligation: <why>`), and gate A says so by name.
A file is the one attachment the role looks at (`## Attachments`, the owner's word 30.10.2026, V2): code lists the files and
requires one FORM-checked row each; it never opens a byte of one (AR-2, AR-7), and whether a file contradicts a requirement is
the role's. The form of the call that opens a file is data (`attachment_read_forms`, AR-1).

The direction of error is one way: a false refusal with a door (the role writes a home in one move) or a debt for the
person; never a silent pass on an unknown (FR-41, FR-59). An unknown input is NAMED and the check goes on:
`source view absent`, `source view unreadable`, `linked tickets not known`, `<KEY>: not read`. Exit 3 is only for a
check that could not run at all (the register unreadable, no running story): `UNREADABLE: ...` (RH1-5).
"""
import argparse
import datetime
import hashlib
import json
import re
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import acceptance as AC  # noqa: E402
import detector_verdict as DV  # noqa: E402
import contract as C  # noqa: E402
import grammar as G  # noqa: E402
import hooklib  # noqa: E402
from person_words import WHOLE_PART, door  # noqa: E402

TABLE_NAME = "branch-accounting.json"
BRANCHES_HEADING = "## Branches"
OBLIGATIONS_HEADING = "## Source obligations"
ATTACHMENTS_HEADING = "## Attachments"
OLD_ATTACHMENTS_HEADING = "## Images"       # the name before 1d: a register that still has it gets a note, never a silent pass
ATTACHMENT_COLUMNS = ("attachment", "ticket", "reading", "r", "question", "why")
MATRIX_HEADING = "## Contradiction matrix"
ATTACHMENT_ORIGIN = "attachment"            # the `from:` origin (`planning_contract.matrix_origin`) of a file's matrix column
BRANCH_COLUMNS = ("bn", "r", "kind", "source_ref", "text")
OBLIGATION_COLUMNS = ("unit", "home")
NONE_LINE_RE = re.compile(r"^Branches:[ \t]*none[ \t]*(?:--(.*))?$")
BN_RE = re.compile(r"BN-\d+")
HEX12 = r"[0-9a-f]{12}"
KEY_RE = r"[A-Z][A-Z0-9_]*-\d+"
UNIT_TOKEN_RE = re.compile(rf"U-{HEX12}|G-{HEX12}|T-{KEY_RE}(?:@{HEX12})?|rest:{KEY_RE}|rest")     # `T-` stays to be REFUSED by name
WHOLE_BLOCK = "branch_accounting.py"      # the block name a person's word records against the whole refusal (waiver.py --block)
COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
LIST_MARK_RE = re.compile(r"^\s*(?:[-*•#]+|\d+[.)])\s+")
HEADING_MARK_RE = re.compile(r"^\s*h[1-6]\.\s+")
SENTENCE_END_RE = re.compile(r"(?<=[.!?…])\s+")
ISO_DAY_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")
STAGE_CHECKS = ("S2", "S3", "S4", "S5")  # the stages this one script is the exit gate of (`STAGE_RUNNERS` below: one check each)

# What a home may be, by its tag. Tags are this module's own spelling: nothing compares a verdict word (gate-registry).
H_REQ, H_BRANCH, H_NOT_OBLIGATION, H_EXCLUDED, H_UNRECONCILED = "req", "branch", "not_obligation", "excl", "unrec"
HOME_FORMS = ("`R-n`, `BN-n`, `not_obligation: <why>`, `excluded: Q<n>(<letter>): <why>` or `excluded: \"<their words>\" (<file>.txt): <why>` "
              "(a `rest` row takes `unreconciled: <why>`)")


class Unreadable(Exception):
    """The check could not run (RH1-5): the factory's own defect, never a pass."""


# --- the data file -----------------------------------------------------------------------------------------------

def table() -> dict:
    """`references/branch-accounting.json`; unreadable or malformed is `Unreadable`, never defaults that decide."""
    path = Path(__file__).resolve().parent.parent / "references" / TABLE_NAME
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise Unreadable(f"references/{TABLE_NAME} cannot be read ({type(exc).__name__}: {exc})")
    if not isinstance(data, dict):
        raise Unreadable(f"references/{TABLE_NAME} is not an object")
    return data


def limit(name: str) -> int:
    value = table().get(name)
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise Unreadable(f"references/{TABLE_NAME}: `{name}` must be a positive integer, got {value!r}")
    return value


def cutoff() -> str:
    value = str(table().get("cutoff") or "")
    if not ISO_DAY_RE.fullmatch(value):
        raise Unreadable(f"references/{TABLE_NAME}: `cutoff` must be an ISO date, got {value!r}")
    return value


def kinds() -> list:
    value = table().get("kinds")
    if not isinstance(value, list) or not value or not all(isinstance(k, str) for k in value):
        raise Unreadable(f"references/{TABLE_NAME}: `kinds` must be a non-empty list of words")
    return value


def _word_list(name: str) -> list:
    value = table().get(name)
    if not isinstance(value, list) or not value or not all(isinstance(k, str) for k in value):
        raise Unreadable(f"references/{TABLE_NAME}: `{name}` must be a non-empty list of words")
    return value


def _word_map(name: str) -> dict:
    """A `{word: sentence}` row of the data file; a damaged one is the same refusal as a damaged list."""
    value = table().get(name)
    if not isinstance(value, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in value.items()):
        raise Unreadable(f"references/{TABLE_NAME}: `{name}` must be an object of words to sentences")
    return value


def attachment_readings() -> list:
    return _word_list("attachment_readings")


def _read_forms() -> dict:
    """`attachment_read_forms` of the data file: how a file is opened, by media type and by suffix (AR-1, FR-13). A damaged block
    is `Unreadable`, never a default that decides."""
    value = table().get("attachment_read_forms")
    ok = (isinstance(value, dict) and isinstance(value.get("by_media"), list) and isinstance(value.get("by_suffix"), dict)
          and isinstance(value.get("unlabelled_media"), list) and isinstance(value.get("link_suffixes"), list)
          and all(isinstance(r, dict) and isinstance(r.get("prefix"), str) and isinstance(r.get("call"), str) for r in value["by_media"])
          and all(isinstance(k, str) and isinstance(v, str) for k, v in value["by_suffix"].items()))
    if not ok:
        raise Unreadable(f"references/{TABLE_NAME}: `attachment_read_forms` must hold `by_media`, `by_suffix`, `unlabelled_media` "
                         "and `link_suffixes`")
    return value


def picture_signatures() -> list:
    """The first bytes of the picture formats (`attachment_read_forms.picture_signatures`, AR-1): `[(name, [(offset, bytes)])]`, every
    part of a row must match. The ONE reader (AR-13); it opens no byte of any file (the read guard compares). A damaged block is
    `Unreadable`, never a default that decides; the older copy of the table without the key is read by `_read_forms` as before."""
    forms = table().get("attachment_read_forms")
    rows = forms.get("picture_signatures") if isinstance(forms, dict) else None
    bad = Unreadable(f"references/{TABLE_NAME}: `attachment_read_forms.picture_signatures` must be a non-empty list of "
                     "{name, parts: [[offset >= 0, even-length lowercase hex], ...]}")
    if not isinstance(rows, list) or not rows:
        raise bad
    out = []
    for row in rows:
        parts = row.get("parts") if isinstance(row, dict) else None
        if not isinstance(row, dict) or not isinstance(row.get("name"), str) or not isinstance(parts, list) or not parts:
            raise bad
        got = []
        for part in parts:
            ok = (isinstance(part, list) and len(part) == 2 and isinstance(part[0], int) and not isinstance(part[0], bool)
                  and part[0] >= 0 and isinstance(part[1], str) and part[1] and re.fullmatch(r"(?:[0-9a-f]{2})+", part[1]))
            if not ok:
                raise bad
            got.append((part[0], bytes.fromhex(part[1])))
        out.append((row["name"], got))
    return out


def _suffix(name) -> str:
    text = str(name or "").strip().lower()
    return "." + text.rsplit(".", 1)[1] if "." in text.rsplit("/", 1)[-1] else ""


def read_form(media_type, name) -> str:
    """The form of the call that opens a file (`limit_1`, `pages`, `whole`), or `""` when the data names none (`no_read_form`).
    The first `by_media` prefix that the media type starts with decides; an empty or `null` type, or one in `unlabelled_media`,
    is decided by the suffix of the name instead (a file Jira gave no type is still a file); a labelled type no row names has no
    form. The ONE reader of the data (AR-13); it opens no byte."""
    forms = _read_forms()
    media = str(media_type or "").strip().lower()
    if media and media not in forms["unlabelled_media"]:
        return next((row["call"] for row in forms["by_media"] if media.startswith(row["prefix"])), "")
    return forms["by_suffix"].get(_suffix(name), "")


def project_config(task_root) -> dict:
    """The config of the project the TASK lives in (the nearest `qa-factory/config.json` above it); `{}` when there is none or
    it cannot be read - every reader of it then takes its default (AR-3)."""
    try:
        import runtime_paths
        project = runtime_paths.nearest_project(task_root)
        if project is not None:
            cfg = json.loads((project / "qa-factory" / "config.json").read_text(encoding="utf-8-sig"))
            return cfg if isinstance(cfg, dict) else {}
    except Exception:  # noqa: BLE001 - no config is the defaults
        pass
    return {}


# --- units: structure only ---------------------------------------------------------------------------------------

def normalize(text) -> str:
    """NFC, whitespace and line breaks folded to single spaces: the text a unit id is computed from."""
    return " ".join(unicodedata.normalize("NFC", str(text or "")).split())


def _hex12(text: str) -> str:
    return hashlib.sha256(normalize(text).encode("utf-8")).hexdigest()[:12]


def unit_id(text) -> str:
    return "U-" + _hex12(text)


def group_id(text) -> str:
    """One comment as a whole: a home for the group covers every unit of it (the way a long thread costs one row)."""
    return "G-" + _hex12(text)


def split_units(text) -> list:
    """The units of a free text, by structure only: one per list item, one per sentence of a prose line. A line-initial
    Jira heading marker (`h3.`) is markup like a list marker and is cut off. A piece with no letter or digit is no unit."""
    units = []
    for line in str(text or "").splitlines():
        line = HEADING_MARK_RE.sub("", line, count=1).strip()
        if not line:
            continue
        marked = LIST_MARK_RE.match(line)
        pieces = [line[marked.end():]] if marked else SENTENCE_END_RE.split(line)
        for piece in pieces:
            piece = normalize(piece)
            if any(ch.isalnum() for ch in piece):
                units.append(piece)
    return units


def cut(text: str, shown: int) -> str:
    text = str(text)
    return text if len(text) <= shown else text[:max(shown - 1, 0)] + "…"


# --- one ticket snapshot -----------------------------------------------------------------------------------------

def _shape_reason(snap) -> str:
    """Why a snapshot is not of the shape that carries a ticket's text, or `""`. A missing key is NOT an empty ticket
    (FR-59): the canonical snapshot always carries the three (`ticket_light.SCHEMA_KEYS`)."""
    if not isinstance(snap, dict):
        return "the snapshot is not an object"
    if not isinstance(snap.get("description"), str):
        return "`description` is missing or not text"
    for name in ("acceptance_criteria", "comments"):
        if not isinstance(snap.get(name), list):
            return f"`{name}` is missing or not a list"
    for item in snap["acceptance_criteria"]:
        if not (isinstance(item, str) or (isinstance(item, dict) and isinstance(item.get("text"), str))):
            return "an element of `acceptance_criteria` is neither text nor an object with `text`"
    for item in snap["comments"]:
        if not (isinstance(item, dict) and isinstance(item.get("text"), str)):
            return "an element of `comments` is not an object with `text`"
    return ""


def snapshot_units(snap, *, title_counts: bool) -> dict:
    """`{"state": ok|unreadable|empty|no_unit, "reason": str, "units": [(field, text, group)]}` of one snapshot.
    `title_counts`: the story's own ticket (a title-only ticket is a normal case; a linked ticket's title is a label)."""
    why = _shape_reason(snap)
    if why:
        return {"state": "unreadable", "reason": why, "units": []}
    criteria = [i if isinstance(i, str) else i["text"] for i in snap["acceptance_criteria"]]
    comments = [c["text"] for c in snap["comments"]]
    if not (snap["description"].strip() or any(c.strip() for c in criteria) or any(c.strip() for c in comments)):
        title = snap.get("title")
        if title_counts and isinstance(title, str) and any(ch.isalnum() for ch in title):
            return {"state": "ok", "reason": "", "units": [("title", normalize(title), None)]}
        return {"state": "empty", "reason": "", "units": []}
    units = [("description", t, None) for t in split_units(snap["description"])]
    for item in criteria:
        text = normalize(item)
        if any(ch.isalnum() for ch in text):
            units.append(("criteria", text, None))
    for body in comments:
        gid = group_id(body)
        units += [("comments", t, gid) for t in split_units(body)]
    if not units:
        return {"state": "no_unit", "reason": "the ticket has text and no unit was read", "units": []}
    return {"state": "ok", "reason": "", "units": units}


# --- the scope: the story's snapshot and the kept linked tickets -------------------------------------------------

def _load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def inventory_sources(task_root) -> tuple:
    """`(sources, reason, absent)` of `work/source-inventory.json`: the ONE read of the inventory's list (AR-13) that the scope of
    the units (`in_scope_sources`), the files (`scope_attachments`) and the attachments of gate A (`attachments_view`) share.
    `sources` is None when the list cannot be read (the file is absent, not JSON, `sources` is no list, an element is no
    object); `reason` says why; `absent` is true only when the file is not on disk."""
    try:
        data = _load_json(Path(C.artifact(Path(task_root), "source-inventory.json")))
        sources = data["sources"]
        if not isinstance(sources, list):
            raise TypeError("`sources` is not a list")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return None, f"{type(exc).__name__}: {exc}", isinstance(exc, FileNotFoundError)
    if not all(isinstance(source, dict) for source in sources):
        return None, "an element of `sources` is not an object", False
    return sources, "", False


def scope_class(source: dict) -> str:
    """The ONE test of what a source of the inventory is to the person's review (AR-13): `own` (the story's entry), `own_out`
    (the story's entry, excluded), `left_out` (`not_relevant` or `excluded`: no unit, no debt), `kept` (`relevant` and `read`),
    `unread` (everything else: in scope, nobody read it)."""
    status = source.get("status")
    if source.get("relation") == "task":
        return "own_out" if status == "excluded" else "own"
    if source.get("relevance") == "not_relevant" or status == "excluded":
        return "left_out"
    return "kept" if source.get("relevance") == "relevant" and status == "read" else "unread"


def in_scope_sources(task_root) -> dict:
    """The linked tickets the person's review kept, read from `work/source-inventory.json` (never another story's).
    `{"known": bool, "reason": str, "read": [source], "not_read": [(KEY, why)], "left_out": [(KEY, why)]}`.
    Out of scope: `relevance: not_relevant` or `status: excluded` (no unit, no debt). In scope and READ: `relevant` +
    `status: read` + a safe `snapshot_ref` whose file exists. In scope and not read: everything else; it is named,
    never counted as reconciled and never as an empty ticket. The story's own entry (`relation: task`) gives no second
    set of units: its text is `work/ticket-snapshot.json`."""
    out = {"known": True, "reason": "", "read": [], "not_read": [], "left_out": []}
    sources, reason, _absent = inventory_sources(task_root)
    if sources is None:
        out.update(known=False, reason=reason)
        return out
    import source_inventory as SI
    for source in sources:
        kind = scope_class(source)
        if kind in ("own", "own_out"):
            continue
        key, relevance, status = SI._key(source) or "an unnamed source", source.get("relevance"), source.get("status")
        if kind == "left_out":
            out["left_out"].append((key, str(relevance if relevance == "not_relevant" else status)))
            continue
        ref = source.get("snapshot_ref")
        if kind == "unread":
            out["not_read"].append((key, f"relevance {relevance}, status {status}"))
        elif not SI._safe_rel(ref):
            out["not_read"].append((key, "the snapshot path is empty or not a work-relative path"))
        elif not (Path(task_root) / "work" / str(ref)).is_file():
            out["not_read"].append((key, "the snapshot file is not on disk"))
        else:
            out["read"].append({"key": key, "ref": str(ref), "revision": source.get("revision")})
    return out


def collect(task_root) -> dict:
    """Everything the reconciliation reads: the units (by id, with every place each stands), the ids of the groups,
    and what was NOT known about the sources, each named.
    `{"units": {id: {"text", "occ": [{"key","field","group"}]}}, "collisions": {id}, "groups": {gid: key},
       "history": {"key","state","reason"}, "scope": in_scope_sources(...), "linked": {KEY: {"state","reason"}},
       "kept": [KEY]}` (`kept`: only a kept ticket whose text was read and gave units, in the inventory's order)."""
    root = Path(task_root)
    result = {"units": {}, "collisions": set(), "groups": {}, "linked": {}, "kept": []}
    by_id = result["units"]

    def add(key, found):
        for field, text, group in found["units"]:
            uid = unit_id(text)
            held = by_id.setdefault(uid, {"text": text, "occ": []})
            if normalize(held["text"]) != normalize(text):
                result["collisions"].add(uid)       # 48 bits met two different texts: neither is homed by id
                continue
            held["occ"].append({"key": key, "field": field, "group": group})
            if group:
                result["groups"][group] = key

    history = {"key": root.name, "state": "absent", "reason": ""}
    try:
        path = Path(C.artifact(root, "ticket-snapshot.json"))
        snap = _load_json(path) if path.is_file() else None
    except (OSError, ValueError) as exc:
        snap, history["state"], history["reason"] = None, "unreadable", f"{type(exc).__name__}: {exc}"
    if snap is not None:
        history["key"] = str(snap.get("key") or root.name) if isinstance(snap, dict) else root.name
        found = snapshot_units(snap, title_counts=True)
        history.update(state=found["state"], reason=found["reason"])
        add(history["key"], found)
    result["history"] = history

    scope = in_scope_sources(root)
    result["scope"] = scope
    for source in scope["read"]:
        try:
            snap = _load_json(root / "work" / source["ref"])
        except (OSError, ValueError) as exc:
            result["linked"][source["key"]] = {"state": "unreadable", "reason": f"{type(exc).__name__}: {exc}"}
            continue
        found = snapshot_units(snap, title_counts=False)
        result["linked"][source["key"]] = {"state": found["state"], "reason": found["reason"]}
        if found["units"]:
            result["kept"].append(source["key"])
        add(source["key"], found)
    return result


def units_by_ticket(task_root) -> dict:
    """`{KEY: number of occurrences}`: a count to MEASURE with (SL-11), never a threshold anything reads."""
    counts: dict = {}
    for held in collect(task_root)["units"].values():
        for occ in held["occ"]:
            counts[occ["key"]] = counts.get(occ["key"], 0) + 1
    return counts


# --- the register: `## Branches` and `## Source obligations` -----------------------------------------------------

def _read_register(task_root):
    """The register text with HTML comments cut out (a table in a template comment is not a row), or None when the
    file is absent. Not UTF-8, or unreadable: `Unreadable` (exit 3)."""
    path = Path(C.artifact(Path(task_root), "requirements-register.md"))
    if not path.is_file():
        return None
    try:
        return COMMENT_RE.sub("", path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError) as exc:
        raise Unreadable(f"{path.name} cannot be read ({type(exc).__name__}: {exc})")


def _section(text: str, heading: str):
    """The lines under EXACTLY `heading` (`## Branches (draft)` is another heading) up to the next `## `, or None."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.strip() == heading:
            body = []
            for rest in lines[i + 1:]:
                if rest.strip().startswith("## "):
                    break
                body.append(rest)
            return body
    return None


def _table_rows(body: list, columns: tuple):
    """`(rows, problem)`: the rows of the first table of a section, split into len(columns) cells; the LAST column keeps
    every `|` after it (a `|` inside the text cuts nothing). `problem` names a header that is not `columns`."""
    rows, header = [], None
    for line in body:
        st = line.strip()
        if not st.startswith("|"):
            continue
        cells = G.split_cells(st, len(columns))  # a `\|` is part of its cell (G2-10); the LAST column keeps bare bars
        if set("".join(cells)) <= set("-: "):
            continue
        if header is None:
            header = [c.lower() for c in G.split_cells(st)]
            if tuple(header[:len(columns)]) != columns:
                return [], f"the table header is `{' | '.join(header)}`, expected `{' | '.join(columns)}`"
            continue
        rows.append(cells + [""] * (len(columns) - len(cells)))
    return rows, ""


def _register_ids(text: str) -> list:
    """R ids of `## Register`, in order (the body of `contract.register_ids`, over a text with its comments cut)."""
    ids = []
    for cells in C.md_table(text, "## Register")[1:]:
        found = C.REQ_ID_RE.fullmatch(C.strip_cell(cells[0])) if cells else None
        if found and found.group(0) not in ids:
            ids.append(found.group(0))
    return ids


def _first_event_day(task_root):
    """The UTC day of the first event of `state/events.jsonl` (`created_at`, epoch seconds), or None."""
    try:
        with open(Path(task_root) / "state" / "events.jsonl", encoding="utf-8") as handle:
            stamp = json.loads(handle.readline())["created_at"]
        if isinstance(stamp, bool) or not isinstance(stamp, (int, float)):
            return None
        return datetime.datetime.fromtimestamp(stamp, datetime.timezone.utc).strftime("%Y-%m-%d")
    except (OSError, ValueError, KeyError, TypeError, OverflowError):
        return None


def _story_start(task_root):
    """The day the story began, FIRST that answers of: `pipeline.json` `stages.S0.started` (an ISO time the driver writes),
    the first event of `state/events.jsonl` (an imported S0 has no `started`, real run 14857), else None - and then
    `branch_state` trusts the register's own `created` (the last resort, pinned in S2-8)."""
    try:
        stages = _load_json(Path(task_root) / "pipeline.json")["stages"]
        found = ISO_DAY_RE.match(str(stages["S0"]["started"]))
        if found:
            return found.group(1)
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return _first_event_day(task_root)


def register_branches(text: str) -> dict:
    """`{"present": bool, "none": reason|None, "rows": [dict], "problems": [str]}` of `## Branches`. Direction of
    error: toward a refusal. `Branches: none --` with no reason, `none` beside a table, a table with no rows and no
    `none` line, a duplicate BN, an unknown kind, an R that is not in the register: each is a problem with its door."""
    body = _section(text, BRANCHES_HEADING)
    out = {"present": body is not None, "none": None, "rows": [], "problems": []}
    if body is None:
        return out
    problems = out["problems"]
    none_lines = [m for m in (NONE_LINE_RE.match(line.strip()) for line in body) if m]
    rows, bad_header = _table_rows(body, BRANCH_COLUMNS)
    if bad_header:
        problems.append(f"`{BRANCHES_HEADING}`: {bad_header} - fix: use the table of the register template")
    if none_lines:
        reason = (none_lines[0].group(1) or "").strip()
        out["none"] = reason
        if not reason:
            problems.append("`Branches: none --` gives no reason - fix: write the reason after `--`, e.g. "
                            "`Branches: none -- no qualifier, partition, variant or refusal in the story`")
        if rows:
            problems.append("`Branches: none` stands beside a table of branches - fix: keep the table, or remove the rows "
                            "and keep `none` with its reason")
    elif not rows and not bad_header:
        problems.append(f"`{BRANCHES_HEADING}` has no row and no `Branches: none -- <why>` line - fix: add the branches, "
                        "or `Branches: none -- <why>`")
    known_r, seen = _register_ids(text), set()
    allowed = kinds()
    for cells in rows:
        bn, r, kind, _source_ref, body_text = (C.strip_cell(c) for c in cells)
        if not BN_RE.fullmatch(bn):
            problems.append(f"`{bn or '(empty)'}` is not a branch id - fix: ids are `BN-1`, `BN-2`, ...")
            continue
        if bn in seen:
            problems.append(f"{bn} appears twice in `{BRANCHES_HEADING}` - fix: one row per branch, ids unique")
        seen.add(bn)
        if r not in known_r:
            problems.append(f"{bn}: `{r or '(empty)'}` is not a row of `## Register` - fix: name the requirement the "
                            "branch belongs to (R-n)")
        if kind not in allowed:
            problems.append(f"{bn}: kind `{kind or '(empty)'}` is not one of {', '.join(allowed)} - fix: pick one")
        if not body_text:
            problems.append(f"{bn}: `text` is empty - fix: write the branch in the story's own words (the person is shown it)")
        out["rows"].append({"bn": bn, "r": r, "kind": kind, "text": body_text})
    return out


def branch_state(task_root, text=None) -> dict:
    """`{"state": kept|none|missing|legacy|unreadable, "reason": str, "branches": register_branches(...)}`.
    `legacy` needs BOTH dates before the cutoff: the register's `created` (a free field the role writes) and the day the
    story began (`_story_start`: `pipeline.json` `S0.started`, else the first event of `state/events.jsonl`, else `created`
    is trusted); a story that began after the cutoff with an old `created` is `missing` (S2 refuses
    `created predates this story`). A `created` that is empty or not a date is `missing`, never legacy (t-269 F1).
    A register that carries the section is `kept` whatever its date: the role wrote it, so the checks are on."""
    try:
        text = _read_register(task_root) if text is None else text
    except Unreadable as exc:
        return {"state": "unreadable", "reason": str(exc), "branches": None}
    if text is None:
        return {"state": "unreadable", "reason": "requirements-register.md is not on disk", "branches": None}
    found = register_branches(text)
    if found["present"]:
        return {"state": "none" if found["none"] is not None and not found["rows"] else "kept", "reason": "",
                "branches": found}
    created = C.front_line(text, "created")
    if C.oracle_date_state(created) in ("missing", "unparseable"):
        held = "empty" if not str(created or "").strip() else f"'{str(created).strip()[:40]}'"
        return {"state": "missing", "branches": found,
                "reason": f"`created` is {held}: the branch checks switch on this date - write an ISO date, YYYY-MM-DD"}
    day, begun, line = str(created).strip()[:10], _story_start(task_root), cutoff()
    if day < line and (begun is None or begun < line):
        return {"state": "legacy", "reason": "register predates branch accounting: nothing reconciled", "branches": found}
    if day < line:
        return {"state": "missing", "branches": found,
                "reason": f"`created` ({day}) predates this story (it began {begun}): write the day the register was written"}
    return {"state": "missing", "reason": "", "branches": found}


# --- the reconciliation of the obligations -----------------------------------------------------------------------

def _home(cell: str):
    """`(tag, reason, problem)` of one home cell. Forms are case-sensitive words (`Excluded:` is no word: a refusal)."""
    value = str(cell or "").strip()
    if value.startswith("`") and value.endswith("`") and len(value) > 1:
        value = value[1:-1].strip()
    if C.REQ_ID_RE.fullmatch(value):
        return H_REQ, value, ""
    if BN_RE.fullmatch(value):
        return H_BRANCH, value, ""
    for prefix, tag in (("not_obligation:", H_NOT_OBLIGATION), ("excluded:", H_EXCLUDED), ("unreconciled:", H_UNRECONCILED)):
        if value.startswith(prefix):
            reason = value[len(prefix):].strip()
            return (tag, reason, "" if reason else f"`{prefix}` gives no reason")
    return "", "", f"`{value or '(empty)'}` is not a home"


class Cover:
    """What the rows of `## Source obligations` cover: the ONE place coverage is decided (`homed`, `by_other`)."""

    def __init__(self, collisions):
        self.collisions = collisions
        self.direct, self.group = set(), set()                         # unit ids, group ids
        self.nothing, self.nothing_group = {}, {}                      # unit id / group id -> the `not_obligation:` reason
        self.other, self.other_group = set(), set()                    # unit / group ids a requirement, branch or exclusion homes
        self.rest = set()                                              # `""` = every unit, a KEY = one ticket
        self.seen_rest = []

    def name(self, token, tag, reason) -> None:
        """A row names `token` (a unit id or a group id): it is covered, and the tag says by what. A requirement, branch or
        exclusion wins over `not_obligation` for the same unit (the error goes toward 'the ticket is not called empty')."""
        (self.group if token.startswith("G-") else self.direct).add(token)
        if tag == H_NOT_OBLIGATION:
            (self.nothing_group if token.startswith("G-") else self.nothing)[token] = reason
        else:
            (self.other_group if token.startswith("G-") else self.other).add(token)

    def by_other(self, uid, occ) -> bool:
        """Covered by a row that names it (not by a remainder row)."""
        return (uid in self.direct and uid not in self.collisions) or occ["group"] in self.group

    def homed(self, uid, occ) -> bool:
        return self.by_other(uid, occ) or "" in self.rest or occ["key"] in self.rest

    def why_nothing(self, uid, occ) -> str:
        """The `not_obligation:` reason that homes this occurrence and nothing else does, else `""`."""
        if uid in self.collisions or uid in self.other or occ["group"] in self.other_group:
            return ""
        return self.nothing.get(uid) or self.nothing_group.get(occ["group"]) or ""


def _source_notes(data) -> list:
    """What was NOT known about the sources, each named (never a silent zero)."""
    notes = []
    history = data["history"]
    if history["state"] == "absent":
        notes.append("source view absent: obligations not reconciled")
    elif history["state"] == "unreadable":
        notes.append(f"source view unreadable: obligations not reconciled ({history['reason']})")
    elif history["state"] == "no_unit":
        notes.append(f"the ticket has text and no unit was read ({history['key']})")
    elif history["state"] == "empty":
        notes.append("0 units in the ticket")
    scope = data["scope"]
    if not scope["known"]:
        notes.append(f"linked tickets not known: which tickets were kept is not known ({scope['reason']})")
    for key, why in scope["not_read"]:
        notes.append(f"{key}: not read ({why})")
    for key, state in sorted(data["linked"].items()):
        if state["state"] == "unreadable":
            notes.append(f"{key}: source view unreadable ({state['reason']})")
        elif state["state"] == "no_unit":
            notes.append(f"{key}: text and no unit")
    if scope["left_out"]:
        shown = ", ".join(f"{k} ({w})" for k, w in scope["left_out"][:limit("report_units_shown")])
        more = len(scope["left_out"]) - limit("report_units_shown")
        notes.append(f"{len(scope['left_out'])} linked tickets were left out and not reconciled: {shown}"
                     + (f" and {more} more" if more > 0 else ""))
    return notes


def _row_refusal(unit_cell, tokens, tag, reason, bad, known_r, known_bn) -> str:
    """Why one row of `## Source obligations` is refused whole (its unit cell or its home is no form), or `""`."""
    named = ", ".join(tokens)
    if not tokens or not all(UNIT_TOKEN_RE.fullmatch(t) for t in tokens):
        return (f"`{cut(unit_cell, 60) or '(empty)'}` is not a unit id - fix: `--units` lists them "
                "(`U-<12 hex>`, `G-<12 hex>`, `rest`, `rest:<KEY>`)")
    if bad:
        return f"{named}: {bad} - fix: a home is {HOME_FORMS}"
    if tag == H_REQ and reason not in known_r:
        return f"{named}: {reason} is not a row of `## Register` - fix: name an existing requirement"
    if tag == H_BRANCH and reason not in known_bn:
        return f"{named}: {reason} is not a row of `{BRANCHES_HEADING}` - fix: add the branch, or name an existing one"
    return ""


def _take_rest(token, tag, reason, story_keys, cover, problems, notes) -> None:
    key = token.partition(":")[2]
    if tag != H_UNRECONCILED:
        problems.append(f"{token}: the remainder takes `unreconciled: <why>` only - fix: say why it is left")
    elif token in cover.seen_rest:
        problems.append(f"{token} appears twice - fix: one `rest` row (or one per ticket)")
    elif key and key not in story_keys:
        problems.append(f"{token}: {key} is not a ticket of this story's scope - fix: name a kept ticket or the story itself")
    else:
        cover.seen_rest.append(token)
        cover.rest.add(key)
        notes.append(f"{token}: units left unreconciled: {reason}")


def _take_token(token, tag, reason, story_keys, data, cover, problems, notes) -> None:
    if token.startswith("rest"):
        _take_rest(token, tag, reason, story_keys, cover, problems, notes)
    elif tag == H_UNRECONCILED:
        problems.append(f"{token}: `unreconciled:` belongs to a `rest` row only - fix: give it a requirement, a branch, "
                        "`not_obligation:` or `excluded:`")
    elif token.startswith("T-"):
        # POSITION: after `rest` and `unreconciled:`, before the lookup of `data["units"]`. Unreachable: a unit covered by a ticket
        # token - the source review decided the ticket is in scope, and no row sets it aside whole (the owner's word 30.10.2026).
        problems.append(f"{token}: a kept ticket is not set aside here: the source review already decided it is in scope - fix: "
                        "give each of its units a home (`--units`), `not_obligation: <why>` where a sentence obliges nothing")
    elif token.startswith("G-"):
        if token in data["groups"]:
            cover.name(token, tag, reason)
        else:
            notes.append(f"{token}: no comment has this id now (the text changed?) - it covers nothing")
    elif token in data["units"]:
        cover.name(token, tag, reason)
    else:
        notes.append(f"{token}: no unit has this id now (the text changed?) - it covers nothing")


def _rest_covers(data, token, cover) -> bool:
    """Does a remainder row still hold at least one unit no other home covers? (A `rest` with nothing left is a note.)"""
    key = token.partition(":")[2]
    return any(not cover.by_other(uid, occ) for uid, held in data["units"].items() for occ in held["occ"]
               if not key or occ["key"] == key)


def reconcile(task_root, text: str, branches: dict, qmap=None) -> dict:
    """`{"problems": [str], "notes": [str], "unhomed": [(id, unit, why)], "data": collect(...)}` of the units against
    `## Source obligations`. Counts every unit, however many: no limit here shortens what is checked (spec 5.3). `qmap` is
    `{id: question}` of the register when the caller has read it (`_questions`), else it is read on the first `excluded:` row."""
    data = collect(task_root)
    problems, notes = [], _source_notes(data)
    rows, bad_header = _table_rows(_section(text, OBLIGATIONS_HEADING) or [], OBLIGATION_COLUMNS)
    if bad_header:
        problems.append(f"`{OBLIGATIONS_HEADING}`: {bad_header} - fix: use the table of the register template")
    known_r = set(_register_ids(text))
    known_bn = {r["bn"] for r in (branches or {}).get("rows", [])}
    story_keys = {data["history"]["key"]} | set(data["linked"])
    cover = Cover(data["collisions"])
    excluded_rows, free_rows = [], []      # the rows that say a unit is left out (`excluded:`) or obliges nothing (`not_obligation:`)
    for unit_cell, home_cell in rows:
        tag, reason, bad = _home(home_cell)
        tokens = [t for t in re.split(r"[,;\s]+", unit_cell.replace("`", "")) if t]
        refusal = _row_refusal(unit_cell, tokens, tag, reason, bad, known_r, known_bn)
        if refusal:
            problems.append(refusal)
            continue
        for token in tokens:
            _take_token(token, tag, reason, story_keys, data, cover, problems, notes)
        if tag == H_EXCLUDED:
            qmap = _questions(task_root) if qmap is None else qmap
            excluded_rows.append({"tokens": tokens, "reason": reason, **_exclusion(task_root, reason, qmap)})
        elif tag == H_NOT_OBLIGATION:
            free_rows.append({"tokens": tokens, "reason": reason})
    # POSITION: after `_row_refusal` (a row refused whole never reaches `excluded_rows`) and independent of `cover`: an undecided
    # exclusion still covers its units, so they are named ONCE, as an exclusion nobody decided, and not again as "no home".
    # Unreachable by this move: an `excluded:` that quotes nothing the person said and asks no question (WG1-1, E-1..E-9).
    problems += [f"{', '.join(row['tokens'])}: {row['problem']}" for row in excluded_rows if row["problem"]]
    if "rest" in cover.seen_rest and any(t.startswith("rest:") for t in cover.seen_rest):
        notes.append("a `rest` row and a `rest:<KEY>` row both stand: the first covers everything")
    unhomed = [(uid, held, "shares its id with a different text (id collision)" if uid in data["collisions"] else "has no home")
               for uid, held in data["units"].items() if any(not cover.homed(uid, occ) for occ in held["occ"])]
    notes += [f"{token}: nothing is left for it to cover" for token in cover.seen_rest if not _rest_covers(data, token, cover)]
    return {"problems": problems, "notes": notes, "unhomed": unhomed, "data": data, "cover": cover, "excluded_rows": excluded_rows, "free_rows": free_rows,
            "no_requirement": _no_requirement(data, cover)}


def _no_requirement(data, cover) -> dict:
    """`{KEY: [why, ...]}` of the kept tickets whose text gave units and EVERY unit of which has `not_obligation: <why>` for its only
    home: the zero outcome, written as homes (AR-23), with the distinct reasons in the order they stand. A single unit with a
    requirement, a branch, an exclusion, a remainder row, no home or a colliding id keeps the ticket out (the error goes toward
    'the ticket is not called empty'). The tickets are the kept ones with units, so a ticket nobody read is never in it (FR-41)."""
    out = {}
    for key in data["kept"]:
        reasons = []
        for uid, held in data["units"].items():
            for occ in held["occ"]:
                if occ["key"] != key:
                    continue
                why = cover.why_nothing(uid, occ)
                if not why:
                    reasons = None
                    break
                if why not in reasons:
                    reasons.append(why)
            if reasons is None:
                break
        if reasons:
            out[key] = reasons
    return out


# --- files: listed by code, judged by the role --------------------------------------------------------------------

def text_lines_limit() -> int:
    """`attachment_text_lines` of the data file: how many lines of a text file over the size limit the role is given to read (the
    start, `Read <path> limit <n>`, and says so in `why`). 0, absent or damaged = none: such a file is named, not read (the designer's
    recommendation of 30.10.2026 is a start in part, until the owner's word, D-0025; the value is set when the size of the mockup of
    15045 is measured, M5, which was not: the Jira query gave 401)."""
    value = table().get("attachment_text_lines")
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else 0


def partial_start(lines: int) -> str:
    """How the `why` of a row about a file read in part must begin (the one spelling the form check and the listing share)."""
    return f"read lines 1-{lines}:"


def scope_attachments(task_root) -> dict:
    """The files of the story and of the linked tickets the review kept, from `work/source-inventory.json`.
    `{"known": bool, "reason": str, "items": [entry]}`, `entry` = `{"key","name","status","path","call","scout","why","needs_row","partial"}`
    (`_attachment_entry`). A saved link whose file suffix is in `link_suffixes` is listed as a file too (a mockup the ticket links to
    and the factory saved); Figma and unsaved links are named at gate A and not listed. A row is owed for a file the role can open
    with a call; one the policy left out, that could not be fetched, has no form, is too large or is not on disk has no call and is
    named, never required of the role (FR-5). No byte of a file is opened here (AR-2, AR-7): the inventory and `stat` only."""
    out = {"known": True, "reason": "", "items": []}
    sources, reason, _absent = inventory_sources(task_root)
    if sources is None:
        out.update(known=False, reason=reason)
        return out
    import source_inventory as SI
    root, cfg = Path(task_root).resolve(), project_config(task_root)
    for source in sources:
        if scope_class(source) not in ("own", "kept"):
            continue
        key = SI._key(source) or "an unnamed source"
        materials = source.get("materials") if isinstance(source.get("materials"), dict) else {}
        items, why = _block_items(materials.get("attachments"), "attachments")
        if items is None:
            # not a story with no file (FR-41, AR-28): the list is not known, said once, with the ticket named
            out.update(known=False, reason=out["reason"] or f"{attachment_name(key)}: {why}")
            continue
        out["items"] += [_attachment_entry(item, key, root, cfg, False) for item in items]
        links, _why = _block_items(materials.get("external_media"), "linked material")
        out["items"] += [e for e in (_attachment_entry(item, key, root, cfg, True) for item in links or []) if e]
    return out


def _cause(key: str) -> str:
    """The plain words for a reason of the listing (`attachment_words.causes`, AR-1); a key with no row reads `unknown`'s words."""
    try:
        words = attachment_words()
        return words["causes"].get(key, words["unknown"])
    except Unreadable:
        return "not known"


def _attachment_entry(item: dict, key: str, root: Path, cfg: dict, media: bool):
    """One file of `scope_attachments`, or None for a link that is not a file to open. `media`: the item is a linked material
    (`external_media`), listed only when it was saved (`status: read`) under a suffix of `link_suffixes`.
    ORDER of the checks, and the invariant that no reason of 'no call' becomes a pass: status, path, file on disk, form, size.
    `call` is what follows `Read <path>`: ` limit 1` (a picture), ` pages 1-<N>` (a PDF), `` (a text file whole) or ` limit <n>` (the start
    of a text file over the limit, when the data asks for it); `""` with `needs_row` False when there is none, and `why` says why."""
    import guard_pre_tool
    import source_inventory as SI
    status, ref = item.get("status"), item.get("local_ref")
    if media:
        if status != "read" or _suffix(ref) not in _read_forms()["link_suffixes"]:
            return None
        name = normalize(SI._short_url(str(item.get("url") or ""), 80) if item.get("url") else ref)
    else:
        name = normalize(item.get("filename") or item.get("attachment_id") or "an unnamed attachment")
    entry = {"key": key, "name": name, "status": status, "path": None, "call": None, "needs_row": False, "partial": 0,
             "scout": normalize(item.get("analysis_reason") or ""), "why": ""}
    if status != "read":
        entry["why"] = normalize(item.get("reason") or item.get("error") or f"status {status}")
        return entry
    if not SI._safe_rel(ref):
        entry["why"] = _cause("no_path")
        return entry
    path = root / "work" / str(ref)
    if not path.is_file():
        entry["why"] = _cause("file_missing")
        return entry
    form = read_form(None if media else item.get("media_type"), ref if media else item.get("filename") or ref)
    if not form:
        entry["why"] = _cause("no_read_form")
        return entry
    if form == "pages" and _suffix(ref) != ".pdf":
        entry["why"] = _cause("pdf_without_suffix")          # the tool returns raw bytes for it (M1): no call, never a pass
        return entry
    entry["path"] = path.as_posix()
    if form == "limit_1":
        entry["call"] = " limit 1"
    elif form == "pages":
        entry["call"] = f" pages 1-{guard_pre_tool.big_read_pages(cfg)}"
    else:
        cap = guard_pre_tool.big_read_cap(cfg)
        try:
            size = path.stat().st_size                       # `stat` decides, never the `size` the inventory says
        except OSError:
            entry.update(path=None, why=_cause("file_missing"))
            return entry
        if cap > 0 and size > cap:
            lines = text_lines_limit()
            if not lines:
                entry.update(path=None, why=_cause("too_large"))
                return entry
            entry.update(call=f" limit {lines}", partial=lines)
        else:
            entry["call"] = ""
    entry["needs_row"] = True
    return entry


def attachment_words() -> dict:
    """`{"opened": [status], "causes": {status key: plain words}, "unknown": words}` from `references/branch-accounting.json`
    (FR-13, AR-1): the words gate A and the report give for an attachment's state. A status with no row is `unknown`'s words,
    never read as opened; a damaged block is `Unreadable`, never defaults that decide."""
    value = table().get("attachment_words")
    ok = (isinstance(value, dict) and isinstance(value.get("opened"), list) and isinstance(value.get("causes"), dict)
          and isinstance(value.get("unknown"), str) and value["unknown"].strip()
          and all(isinstance(k, str) for k in value["opened"])
          and all(isinstance(k, str) and isinstance(v, str) and v.strip() for k, v in value["causes"].items()))
    if not ok:
        raise Unreadable(f"references/{TABLE_NAME}: `attachment_words` must hold `opened` (a list), `causes` (words by status) "
                         "and `unknown` (words)")
    return value


def attachment_name(text, room: int = 80) -> str:
    """A name that came from a ticket (a file name, a link, a key, a reason), as ONE plain line: whitespace and line breaks
    folded, back quotes removed, cut to `room` with `…`. It is data, never markup (`phases/s1.md`: a file name is not an
    instruction); the gate and the report print names through this and nothing else."""
    return cut(" ".join(str(text or "").replace("`", "").split()), room)


def _attachment_state(item: dict, words: dict, media: bool) -> tuple:
    """`(opened, plain cause)` of one attachment or linked-material receipt. The key into `attachment_words`: a link's own
    `status`; a file whose bytes were fetched: its `analysis_status` (what the scout did); a policy skip: `skipped_by_policy:<verdict>`;
    any other file status as it is. A key with no row is NOT opened and reads `unknown`'s words (m32)."""
    status = item.get("status")
    if not media and status == "read":
        key = str(item.get("analysis_status") or "unknown")
    elif not media and status == "skipped_by_policy":
        key = f"skipped_by_policy:{item.get('skipped_by_policy')}"
    else:
        key = str(status)
    if key in words["opened"]:
        return True, ""
    return False, words["causes"].get(key, words["unknown"])


def _block_items(block, kind: str):
    """`(items, why)` of one materials block: `items` None when the list is not known (`why`, plain words). `kind` is
    `attachments` or `linked material` (a mass noun: `was`, `is`)."""
    one = kind == "linked material"
    was, is_ = ("was", "is") if one else ("were", "are")
    if not isinstance(block, dict):
        return None, f"no record of the {kind} was kept"
    items, count = block.get("items"), block.get("count")
    if block.get("status") == "unknown":
        return None, f"the {kind} {was} not read"
    if not isinstance(items, list) or not all(isinstance(i, dict) for i in items):
        return None, f"the list of the {kind} cannot be read"
    if isinstance(count, int) and not isinstance(count, bool) and count > len(items):
        return None, f"the {kind} {is_} counted ({count}) but not listed"
    return items, ""


def _ticket_attachments(source: dict, key: str, words: dict, root: Path, cfg: dict) -> dict:
    """`{"key", "known", "reason", "items": [{"name", "opened", "cause", "listed", "part"}]}` of one source of the scope. `listed`: a
    file the role is asked to open (it has a call); `part`: the lines of its start when only that is read. A reason of the listing
    (no form, too large, not on disk, a PDF with no suffix) is what gate A says of a file the scout called read: the gate never says
    `opened` for what no call opens (FR-18)."""
    import source_inventory as SI
    ticket = {"key": key, "known": True, "reason": "", "items": []}
    materials = source.get("materials") if isinstance(source.get("materials"), dict) else {}
    for field, kind, media in (("attachments", "attachments", False), ("external_media", "linked material", True)):
        items, why = _block_items(materials.get(field), kind)
        if items is None:
            ticket.update(known=False, reason=ticket["reason"] or why)
            continue
        for item in items:
            name = (SI._short_url(str(item.get("url") or ""), 80) if media and item.get("url")
                    else item.get("filename") or item.get("attachment_id") or "an unnamed attachment")
            opened, cause = _attachment_state(item, words, media)
            entry = _attachment_entry(item, key, root, cfg, media)
            if entry and item.get("status") == "read" and entry["why"]:
                opened, cause = False, entry["why"]
            ticket["items"].append({"name": attachment_name(name) or "an unnamed attachment", "opened": opened, "cause": cause,
                                    "listed": bool(entry and entry["needs_row"]), "part": entry["partial"] if entry else 0})
    return ticket


def _overlay_read_rows(text: str, tickets: list) -> None:
    """What the tester wrote under `## Attachments` over the files the inventory calls opened (F-1): a file on a `not_opened` row, or
    one a `rest` row leaves, reads `not opened: <why>` - the inventory says only that the scout's bytes were read, not that anyone
    compared it. `agrees`, `contradicts` and `not_an_expectation` stay as the inventory has them. It reaches EVERY listed file, a
    kept ticket's included (the zero outcome of a ticket does not take its files away). No section (or one with a bad header):
    nothing is overlaid, no state is claimed here."""
    body = _section(text, ATTACHMENTS_HEADING)
    rows, bad_header = _table_rows(body, ATTACHMENT_COLUMNS) if body is not None else ([], "")
    if bad_header or not rows:
        return
    shown, rest_why, named, not_opened = limit("unit_text_shown"), None, set(), {}
    for cells in rows:
        name, ticket, reading, why = (C.strip_cell(cells[i]) for i in (0, 1, 2, 5))
        if name == "rest" and reading == "not_opened":
            rest_why = attachment_name(why, shown) or "no reason was given"
            continue
        pair = (attachment_name(name), attachment_name(ticket))
        named.add(pair)
        if reading == "not_opened":
            not_opened[pair] = attachment_name(why, shown) or "no reason was given"
    for entry in tickets:
        for item in entry["items"]:
            pair = (item["name"], entry["key"])
            if not (item.get("listed") and item["opened"]):
                continue
            if pair in not_opened:
                item.update(opened=False, cause=not_opened[pair])
            elif rest_why and pair not in named:
                item.update(opened=False, cause=rest_why)


def _from_register(task_root, out: dict) -> None:
    """What the register of the story adds to the view: the files the tester did not open (`_overlay_read_rows`), and the kept
    tickets none of whose sentences obliges anything (`reconcile`'s `no_requirement`): `out["no_requirement"]` = [(KEY, [why])]. A
    register that cannot be read is `no_requirement_known` False and says so, never an empty list. No `not_obligation:` in the
    register, no read of the snapshots: such a register cannot hold the zero outcome. An exception of `reconcile` is
    `no_requirement_known` False too, never an empty list."""
    try:
        text = _read_register(task_root)
        if text is None:
            return
        if "not_obligation:" in text:
            found = reconcile(task_root, text, branch_state(task_root, text)["branches"])
            out["no_requirement"] = [(attachment_name(key), [attachment_name(w, limit("unit_text_shown")) for w in whys])
                                     for key, whys in found["no_requirement"].items()]
        _overlay_read_rows(text, out["tickets"])
    except Exception:  # noqa: BLE001 - the view never raises; an unknown is named, not an empty list
        out.update(no_requirement_known=False, no_requirement_reason="the register could not be read")


def attachments_view(task_root) -> dict:
    """THE one reader of what gate A and the report say about attachments (AR-13): over `inventory_sources`, the tickets of the
    scope (the story, every ticket the review kept, and one nobody has read, which is then `not known`).
    `{"state": known|absent|unreadable, "known": bool, "reason": plain words, "detail": raw cause, "total": N,
      "tickets": [{"key", "known", "reason", "scope": own|kept|unread, "items": [{"name", "opened", "cause"}]}],
      "no_requirement": [(KEY, [why])], "no_requirement_known": bool, "no_requirement_reason": str}`; an `unreadable` view caused
    by a data table of this module (not by the inventory) also carries `"cause": "tables"`.
    Attachments are never units and never read here beyond the inventory's own record and `stat`; a ticket whose list is not known
    is named, never counted as having none (FR-41). A story with no inventory file is `absent`: there is nothing to list (an older
    build, a test folder); a file that does not parse is `unreadable`. Never raises."""
    out = {"state": "known", "known": True, "reason": "", "detail": "", "total": 0, "tickets": [], "no_requirement": [],
           "no_requirement_known": True, "no_requirement_reason": ""}
    try:
        words = attachment_words()
    except Unreadable as exc:
        out.update(state="unreadable", known=False, reason="the list of words for an attachment's state cannot be read",
                   detail=str(exc), cause="tables")
        return out
    sources, detail, absent = inventory_sources(task_root)
    if sources is None:
        out.update(state="absent" if absent else "unreadable", known=False, detail=detail,
                   reason="the list of the story's sources is missing" if absent else "the list of the story's sources cannot be read")
        return out
    import source_inventory as SI
    root, cfg = Path(task_root).resolve(), project_config(task_root)
    try:
        for source in sources:
            if scope_class(source) in ("own", "kept", "unread"):
                ticket = _ticket_attachments(source, attachment_name(SI._key(source) or "an unnamed source"), words, root, cfg)
                ticket["scope"] = scope_class(source)
                out["tickets"].append(ticket)
                out["total"] += len(ticket["items"])
    except Unreadable as exc:
        out.update(state="unreadable", known=False, reason="the list of how a file is opened cannot be read", detail=str(exc), cause="tables")
        return out
    _from_register(task_root, out)
    return out


def _questions_by_id(task_root):
    """`{id: [the `from` of each reading]}` of `open_questions`, or None when the file is absent or cannot be read (AR-13:
    `question_register.load` is the one reader; a row of it that is no question is skipped there, and its own problems stay its)."""
    import question_register
    view = question_register.load(task_root)
    if not view["register_present"] or (view["problems"] and not view["questions"]):
        return None
    out = {}
    for q in view["questions"]:
        readings = q.get("readings") if isinstance(q.get("readings"), list) else []
        out[q["id"]] = [str(r.get("from") or "") for r in readings if isinstance(r, dict)]
    return out


def _same_file(a, b) -> bool:
    return attachment_name(a, 400) == attachment_name(b, 400)


def _contradiction_problem(name, r, question, text, questions) -> str:
    """Why a `contradicts` row of a file does not walk the whole road of a contradiction with code (spec 1.3), or `""`: the matrix cell
    in a column that is a file's, the question with a reading whose `from` is this file, the fork that names the question. FORM only."""
    import planning_contract as PC
    tail = f"({attachment_name(name, 400)})"         # the cell names the file it quotes; the register reader cuts a cell at 200
    cell = any(rid == r and PC.matrix_origin(column) == ATTACHMENT_ORIGIN and tail in attachment_name(quote, 400)
               for rid, column, quote in PC.register_contradiction_cells(text))
    if not cell:
        return (f"{name}: `contradicts` needs a cell in `{MATRIX_HEADING}`, row {r}, in a column named `attachments`, that starts "
                f"`contradicts:` and quotes the file (`contradicts:\"<quote>\" ({name})`, the whole cell within 200 characters) - fix: "
                "add the column when a file differs from a requirement")
    if not any(_same_file(origin.partition(":")[2], name) for origin in questions[question] if origin.startswith("attachment:")):
        return (f"{name}: question {question} has no reading whose `from` is `attachment:{name}` - fix: the file's side of the "
                "question is a reading with that `from`")
    if question not in PC.register_fork_questions(text).get(r, []):
        return (f"{name}: `## Reading forks` has no row for {r} whose `Decision` starts with {question} - fix: add `| {r} | ... | "
                f"{question} ... |`, so the answer to {question} closes {r} and the person is not asked twice")
    return ""


def _attachment_row_problems(cells, known_r, questions, allowed, text="", partial=None) -> tuple:
    """`(problem | "", (name, ticket) | None)` of one row of `## Attachments`: the FORM only, never the judgment. `questions`:
    `{id: [from]}` or None; `partial`: `{(name, ticket): lines}` of the files read only at the start."""
    name, ticket, reading, r, question, why = (C.strip_cell(c) for c in cells)
    empty = lambda value: value in C.EMPTY_CELLS     # noqa: E731
    if empty(name):
        return f"a row of `{ATTACHMENTS_HEADING}` names no file - fix: write the file name, or `rest`", None
    if name == "rest":
        if reading != "not_opened" or empty(why):
            return (f"the `rest` row of `{ATTACHMENTS_HEADING}` reads `not_opened` and gives a reason - fix: `| rest | - | not_opened | - | - "
                    "| <why the remaining files were not opened> |`"), None
        return "", ("rest", "")
    if empty(ticket):
        return f"{name}: the row names no ticket - fix: write the key of the ticket the file is attached to", None
    found = (name, ticket)
    if reading not in allowed:
        return f"{name}: reading `{reading or '(empty)'}` is not one of {', '.join(allowed)} - fix: pick one", found
    if reading == "contradicts":
        if r not in known_r:
            return f"{name}: `contradicts` names `{r or '(empty)'}`, which is not a row of `## Register` - fix: name the requirement", found
        if questions is None:
            return (f"{name}: `contradicts` needs the question that carries both readings, and `requirements-readiness.json` cannot "
                    "be read to find it - fix: write the question into `open_questions` first"), found
        if empty(question) or question not in questions:
            return (f"{name}: `contradicts` names question `{question if not empty(question) else '(none)'}`, which is not in "
                    "`open_questions` - fix: add one `open_questions` record with the file and the requirement as two readings, "
                    "and write its id"), found
        problem = _contradiction_problem(name, r, question, text, questions)
        if problem:
            return problem, found
    elif reading in ("not_opened", "not_an_expectation") and empty(why):
        return f"{name}: `{reading}` gives no reason in `why` - fix: say what the tool answered, or what the scout's line says", found
    lines = (partial or {}).get((name, ticket))
    if lines and reading != "not_opened" and not why.startswith(partial_start(lines)):
        return (f"{name}: only the first {lines} lines of it were given to read - fix: `why` begins `{partial_start(lines)}` and "
                "says what you saw in that part, or the reading is `not_opened`"), found
    return "", found


def attachment_check(task_root, text: str) -> dict:
    """`{"blocks": [(header, [line])], "notes": [str], "known", "reason"}` of the register's `## Attachments` against the files the
    inventory lists. Owed: one row per file with a call, or one `rest` row (with its reason). No section is owed when no file is owed
    (a ticket with no file is a result, NE32). A `rest` row is never silent: it is a note. The old name `## Images` is a note
    with a door when files are owed and only that section stands, never a silent pass."""
    listing = scope_attachments(task_root)
    blocks, notes = [], []
    required = [i for i in listing["items"] if i["needs_row"]]
    body = _section(text, ATTACHMENTS_HEADING)
    if body is None and not required:
        return {"blocks": blocks, "notes": notes, "known": listing["known"], "reason": listing["reason"]}
    rows, bad_header = _table_rows(body or [], ATTACHMENT_COLUMNS)
    problems = [f"`{ATTACHMENTS_HEADING}`: {bad_header} - fix: use the table of the register template"] if bad_header else []
    if body is None and _section(text, OLD_ATTACHMENTS_HEADING) is not None:
        problems.append(f"`{OLD_ATTACHMENTS_HEADING}` is the old name of `{ATTACHMENTS_HEADING}` - fix: name the section "
                        f"`{ATTACHMENTS_HEADING}` and its first column `attachment`")
    known_r, questions, allowed = set(_register_ids(text)), _questions_by_id(task_root), attachment_readings()
    partial = {(i["name"], i["key"]): i["partial"] for i in required if i["partial"]}
    named, rest_rows = set(), 0
    for cells in rows:
        problem, found = _attachment_row_problems(cells, known_r, questions, allowed, text, partial)
        if problem:
            problems.append(problem)
        if found == ("rest", ""):
            rest_rows += 1
            notes.append(f"files not opened: {C.strip_cell(cells[5])}")
        elif found:
            named.add(found)
    if rest_rows > 1:
        problems.append(f"`rest` appears twice in `{ATTACHMENTS_HEADING}` - fix: one `rest` row")
    listed = {(i["name"], i["key"]) for i in listing["items"]}
    notes += [f"{name} ({ticket}): no such file is attached now - the row is kept as a note"
              for name, ticket in sorted(named - listed)]
    missing = [] if rest_rows else [i for i in required if (i["name"], i["key"]) not in named]
    if problems:
        blocks.append((f"REJECT — {len(problems)} problem(s) in `{ATTACHMENTS_HEADING}`:", [DV.one_line(p) for p in problems]))
    if missing:
        shown = limit("refusal_units_shown")
        lines = [DV.one_line(f"{i['key']}: {cut(i['name'], limit('unit_text_shown'))} has no row in `{ATTACHMENTS_HEADING}` - fix: open it as "
                             f"`--attachments` prints and add `| {i['name']} | {i['key']} | <reading> | <R-n or -> | <Qn or -> | <why> |`")
                 for i in missing[:shown]]
        if len(missing) > shown:
            lines.append(f"{len(missing) - shown} more files have no row ({len(missing)} in all); see `--attachments`, "
                         "or one `rest` row with `not_opened` and the reason")
        blocks.append((f"REJECT — {len(lines)} file(s) of the story have no row in `{ATTACHMENTS_HEADING}`:", lines))
    return {"blocks": blocks, "notes": notes, "known": listing["known"], "reason": listing["reason"]}


def attachment_lines(task_root) -> list:
    """The `--attachments` listing, one line per file: ticket, name, the scout's line, and the call that opens it (`Read <path>
    limit 1` for a picture, `pages 1-<N>` for a PDF, the path alone for a text file: the calls the big-file guard lets through -
    AR-8, nothing to search for). A file the factory could not read has its cause and no path."""
    listing = scope_attachments(task_root)
    if not listing["known"]:
        return [f"attachments not known: the attachments cannot be listed ({listing['reason']})"]
    shown, rows = limit("unit_text_shown"), []
    for i in listing["items"]:
        if i["path"]:
            scout = f'scout: "{cut(i["scout"], shown)}"' if i["scout"] else "scout: no line"
            rows.append(f"{i['key']} | {i['name']} | {scout} | open: Read {i['path']}{i['call']}")
        else:
            rows.append(f"{i['key']} | {i['name']} | not opened by the factory: {cut(i['why'] or 'no usable path', shown)} | no path")
    return rows


# --- the exit gate and the doors ---------------------------------------------------------------------------------

def unit_line(uid: str, held: dict, why: str = "") -> str:
    keys = ",".join(dict.fromkeys(o["key"] for o in held["occ"]))
    fields = "/".join(dict.fromkeys(o["field"] for o in held["occ"]))
    groups = ",".join(dict.fromkeys(o["group"] for o in held["occ"] if o["group"]))
    text = cut(held["text"], limit("unit_text_shown"))
    return DV.one_line(f'{uid}{" " + groups if groups else ""} ({keys} {fields}): "{text}"' + (f" {why}" if why else ""))


def _says(cell) -> tuple:
    """`(word, fact id)` of one `code_says` cell: `("unknown", "")`, `("meets"|"contradicts", <id>)`, or `(None, "")` for any other
    cell (an empty one, `Contradicts`, `n/a`). The id is the REST of the cell after `meets: ` / `contradicts: `, stripped and compared
    exactly (a fact id holds spaces and `/`); an id with a `|` cannot stand in a table cell and so cannot be cited (t-1677 C-9)."""
    value = str(cell or "").strip()
    if value == "unknown":
        return "unknown", ""
    if value.startswith("unknown:") and value[len("unknown:"):].strip():      # `unknown: <why>` (N1-6): a reason is said
        return "unknown", ""
    for word in C.CODE_SAYS_WORDS[:2]:
        prefix = f"{word}: "
        if value.startswith(prefix) and value[len(prefix):].strip():
            return word, value[len(prefix):].strip()
    return None, ""


def code_says_contradicts(row) -> bool:
    """Does the register row's `code_says` cell say `contradicts: <fact id>` (the reading `_says` gives; a register with no such column,
    an empty cell or a malformed one is False: the card stays, FR-59)? The public reader gate A's contradiction cards use (AR-13)."""
    return isinstance(row, dict) and _says(row.get("code_says"))[0] == "contradicts"


def _row_place(observable) -> tuple:
    """`(path, line)` of a register row's `observable` when it is `current-code:<path>:<line>` or `diff:<path>:<line>` (a removed
    line, `diff:-<path>:<line>`, is read at its number in the new file, as the tester's card says); `("", 0)` for `none`,
    `expected-contract`, a path with no line, or anything else - no place, so no fact can stand on it (N1-6)."""
    value = str(observable or "").strip()
    for prefix in ("current-code:", "diff:"):
        if value.startswith(prefix):
            rest = value[len(prefix):]
            path, _sep, line = (rest[1:] if prefix == "diff:" and rest.startswith("-") else rest).strip().rpartition(":")
            if path.strip() and line.strip().isdigit():
                return path.strip().replace("\\", "/").removeprefix("./"), int(line.strip())
    return "", 0


def code_says_check(task_root, text, branches) -> list:
    """`[str]` problems of the register's `code_says` column (RN1-17 item 0): the column joins an UNAMBIGUOUS requirement with an S1
    fact. (a) a cell that is not `unknown` / `unknown: <why>` / `meets: <id>` / `contradicts: <id>` (an empty cell: write `unknown`);
    (a2, t-1685 N1-6) a BARE `unknown` on a row whose `observable` is `current-code:`/`diff:` `<path>:<line>` while a fact of the bundle
    stands on that same path and line is refused with the fact's id: silence is what is stopped, any reason opens it (FR-4); (b) an id that is no
    fact of `bug_records.bundle_facts` (the bundle cannot be read: ONE problem, never a pass); (c) a `contradicts` R that no
    `variant`/`qualifier` branch opens, while an unsettled `open_questions` row names it: a predicted bug is not put to the person as a
    choice (FR-3), it is planned as one expected-red check. A register with no such column (written before it existed) has no
    problem: it could not have it (TEMPORAL, G-1). The ambiguity proxy is structural (FR-12): a branch row, never the requirement's words."""
    try:
        rows = C.register_rows(text)
    except ValueError as exc:       # `register_rows` refuses a table with no `Requirement` column: an unreadable register is ONE problem, never a pass
        return [f"the register cannot be read, so code_says cannot be checked ({str(exc)[:160]})"]
    if not rows or all(row.get("code_says") is None for row in rows):
        return []
    problems, cited, bare = [], {}, {}
    for row in rows:
        word, fid = _says(row["code_says"])
        if word is None:
            problems.append(f"{row['r']}: code_says `{row['code_says'] or '(empty)'}` is not `unknown`, `unknown: <why>`, `meets: <fact id>` or "
                            "`contradicts: <fact id>` - fix: write `unknown` (or `unknown: <why no fact settles it>`) when no fact speaks to the requirement")
        elif word != "unknown":
            cited[row["r"]] = (word, fid)
        elif str(row["code_says"]).strip() == "unknown" and _row_place(row.get("observable"))[1]:
            bare[row["r"]] = _row_place(row.get("observable"))       # a BARE `unknown` on a row that has a place to compare (N1-6)
    if cited or bare:
        import bug_records as BR
        by_id, why = BR.bundle_facts(task_root)
        if by_id is None:
            problems.append(f"the S1 facts cannot be read ({why}), so code_says cannot be checked - fix: the scout's bundle is the factory's to "
                            "restore; until then write `unknown: <why>`")
        else:
            standing = {}
            for fid, held in by_id.items():
                for fact in held:
                    fpath = str(fact.get("path") or "").strip().replace("\\", "/").removeprefix("./")
                    if fpath and isinstance(fact.get("line"), int) and not isinstance(fact.get("line"), bool):
                        standing.setdefault((fpath, fact["line"]), []).append(fid)
            for rid, place in bare.items():
                ids = list(dict.fromkeys(standing.get(place, [])))
                if ids:
                    problems.append(f"{rid}: code_says unknown, but the S1 fact {ids[0]}{' (or ' + ', '.join(ids[1:]) + ')' if len(ids) > 1 else ''} stands "
                                    f"on this row's own line ({place[0]}:{place[1]}) - compare them: meets: {ids[0]}, contradicts: {ids[0]}, or "
                                    "unknown: <why the fact does not settle it>")
            problems += [f"{rid}: `{fid}` is not the id of a fact in context-bundle.json - fix: copy the id of the fact exactly, or write `unknown`"
                         for rid, (_word, fid) in cited.items() if fid not in by_id]
    contradicted = [(rid, fid) for rid, (word, fid) in cited.items() if word == "contradicts"]
    if contradicted:
        import question_register as QR
        open_asks = [q for q in _questions(task_root).values() if not QR.settled(q)]
        opened = {r["r"] for r in (branches or {}).get("rows", []) if r["kind"] in C.AMBIGUOUS_BRANCH_KINDS}
        norms = C.norm_row_ids(text)
        for rid, fid in contradicted:
            # the norms-list question (F5 b) is not a fork: the norm is its default reading, so a norm the code departs from stands as an
            # expected red even when that question lists it; a fork question naming the same R still refuses (t-1692 B1)
            asking = [q["id"] for q in open_asks if rid not in opened and _names_branch(q, rid) and not C.is_norms_question(q, norms)]
            if asking:
                problems.append(f"{rid}: the requirement says what to expect and the code contradicts it ({fid}) - that is a predicted bug, not a "
                                f"question: drop {', '.join(asking)} and plan one expected-red check, or add the variant/qualifier branch that "
                                "makes the expectation open")
    return problems


def norms_question_check(task_root, text) -> list:
    """`[str]` problems of the norms-list question (F5 b, t-1692 B2): an unsettled question that lists the register's norm rows carries
    no reading `from: code` - `contract.question_errors` is the ONE validator, called here with the register's norm rows. [] when the
    register has no norm rows or no such question (the rule is inert)."""
    try:
        norms = C.norm_row_ids(text)
    except ValueError:              # the same unreadable register is already ONE problem of `code_says_check`
        return []
    if not norms:
        return []
    import question_register as QR
    out = []
    for q in _questions(task_root).values():
        if not QR.settled(q) and C.is_norms_question(q, norms):
            out += [f"{q.get('id')}: {e}" for e in C.norms_question_errors(q, norms)]
    return out


def s2_check(task_root) -> dict:
    """The S2 exit check. `{"state", "blocks": [(header, [line])], "notes": [str], "unhomed": [...]}`: `blocks` empty means
    the register passes. `legacy` is one note and nothing reconciled; `unreadable` raises `Unreadable`."""
    text = _read_register(task_root)
    if text is None:
        return {"state": "no_register", "blocks": [], "notes": [], "unhomed": []}
    state = branch_state(task_root, text)
    if state["state"] == "unreadable":
        raise Unreadable(state["reason"])
    if state["state"] == "legacy":
        return {"state": "legacy", "blocks": [], "notes": [state["reason"]], "unhomed": []}
    blocks, branch_problems = [], []
    if state["state"] == "missing":
        branch_problems.append(state["reason"] or f"the register has no `{BRANCHES_HEADING}` section - fix: add it "
                               "(a table of the branches, or `Branches: none -- <why>`; see the register template)")
    branch_problems += (state["branches"] or {}).get("problems", [])
    if branch_problems:
        blocks.append((f"REJECT — {len(branch_problems)} problem(s) in the register's branch accounting (`{BRANCHES_HEADING}`):",
                       [DV.one_line(p) for p in branch_problems]))
    found = reconcile(task_root, text, state["branches"])
    if found["problems"]:
        blocks.append((f"REJECT — {len(found['problems'])} problem(s) in `{OBLIGATIONS_HEADING}`:",
                       [DV.one_line(p) for p in found["problems"]]))
    says = code_says_check(task_root, text, state["branches"])
    if says:
        blocks.append((f"REJECT — {len(says)} problem(s) in the register's code_says column:", [DV.one_line(p) for p in says]))
    norms = norms_question_check(task_root, text)   # t-1772: its own block, it is about a question's readings, not the `code_says` column (F8 t-1752)
    if norms:
        blocks.append((f"REJECT — {len(norms)} problem(s) in the norms-list question:", [DV.one_line(p) for p in norms]))
    decided = decided_question_check(task_root, text)   # D1-B B4: a question on a requirement S1 decided in the person's words (door: asks_beyond_words); its own block, it is not about `code_says` (F8 t-1752)
    if decided:
        blocks.append((f"REJECT — {len(decided)} readiness question(s) on what is already decided:", [DV.one_line(p) for p in decided]))
    unhomed = found["unhomed"]
    if unhomed:
        shown = limit("refusal_units_shown")
        lines = [unit_line(u, h, w) + f" - fix: add `| {u} | R-n |` to `{OBLIGATIONS_HEADING}` (or BN-n, not_obligation: <why>, "
                 "excluded: Q<n>(<letter>): <why> or excluded: \"<their words>\" (<file>.txt): <why>)" for u, h, w in unhomed[:shown]]
        if len(unhomed) > shown:
            lines.append(f"{len(unhomed) - shown} more units have no home ({len(unhomed)} in all); see --unhomed")
        blocks.append((f"REJECT — {len(lines)} part(s) of the story's text have no home in `{OBLIGATIONS_HEADING}`:", lines))
    files = attachment_check(task_root, text)
    blocks += files["blocks"]
    notes = found["notes"] + files["notes"]
    if not files["known"] and found["data"]["scope"]["known"]:
        # the inventory reads, but its attachment lists do not: named. (An unreadable inventory is already `linked tickets not known`.)
        notes.append(f"attachments not known: the attachments cannot be listed ({files['reason']})")
    return {"state": state["state"], "blocks": blocks, "notes": notes, "unhomed": unhomed}


# --- S3 and S4: where each branch goes (step 2, TQ1-17) ---------------------------------------------------------------
# The strategist homes every branch in the plan; the case critic's exit sees it carried by a case. Both read the register
# through `branch_state` (a legacy or unrecorded register is a note: nothing reconciled), never a second reader (AR-13).

MANUAL_DISPOSITIONS = tuple(d for d in C.DISPOSITIONS if d.startswith("manual"))    # the rows that owe a `rung_basis`
PLAN_EXCLUDING = ("skip", "unverifiable")      # a plan row with one of these checks nothing: a branch on it is left out, by the row's reason
BNT_RE = re.compile(r"BN-T\d+")                # a branch the strategist found in an existing test (`candidate_branches`)
DECIDERS = ("role", "person")
BRANCH_HOMES_HEADING = "## Branch homes"
HOME_COLUMNS = ("bn", "home", "reason")
BRANCH_HOME_FORM = ('`{"branch": "BN-2", "home": "excluded", "reason": "<why>", "decided_by": "role|person", '
                    '"answer": "<the question id, when a person decided>"}`')
CASE_HOME_FORM = "| BN-n | TC-n or excluded | <why> |"


def _plan(task_root):
    """`(document, rows)` of `work/test-plan.json`; `(None, [])` when there is no plan (nothing to reconcile). A plan that is
    there and cannot be read is `Unreadable`: not knowing the plan is not a pass (FR-59)."""
    path = Path(C.artifact(Path(task_root), "test-plan.json"))
    if not path.is_file():
        return None, []
    try:
        doc = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, UnicodeDecodeError) as exc:
        raise Unreadable(f"{path.name} cannot be read ({type(exc).__name__}: {exc})")
    rows = doc.get("rows") if isinstance(doc, dict) else doc
    if not isinstance(rows, list):
        raise Unreadable(f"{path.name} holds no list of rows")
    return doc, [r for r in rows if isinstance(r, dict)]


def plan_case_budget(task_root):
    """The number of cases the S3 plan allows the story: the top-level `plan_case_budget` of `work/test-plan.json`, read through
    `_plan` (its one reader). Written by the strategist's plan under SC5-6 (words-gates/1); absent until then. `None` when the plan
    is absent or unreadable, the key is absent, or the value is not an int >= 1 (a `bool` is no int here): never raises - a bad
    datum of the factory's own is a note for the reader, never a refusal of the role (TQ1-27)."""
    try:
        doc = _plan(task_root)[0]
    except Unreadable:
        return None
    value = doc.get("plan_case_budget") if isinstance(doc, dict) else None
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 1 else None


def _row_branches(row, rid, problems) -> list:
    raw = row.get("branches")
    if raw is None:
        return []
    if not isinstance(raw, list) or any(not isinstance(b, str) for b in raw):
        problems.append(f"{rid}: `branches` must be a list of branch ids, such as [\"BN-1\"] - fix: write the ids of the "
                        "branches this row checks")
        return []
    return [b.strip() for b in raw if b.strip()]


def _candidate_branches(doc, known_r, problems) -> dict:
    """`{BN-T<n>: {"r", "text", "from"}}`: the branches the strategist read in existing tests (the role judges, AR-2)."""
    raw = doc.get("candidate_branches") if isinstance(doc, dict) else None
    if raw is None:
        return {}
    if not isinstance(raw, list):
        problems.append("`candidate_branches` must be a list of {\"id\": \"BN-T1\", \"r\": \"R-n\", \"from\": \"<candidate id>\", "
                        "\"text\": \"...\"} - fix: write the list, or remove the key")
        return {}
    out = {}
    for index, item in enumerate(raw):
        where = f"`candidate_branches[{index}]`"
        if not isinstance(item, dict):
            problems.append(f"{where} is not an object - fix: {{\"id\": \"BN-T1\", \"r\": \"R-n\", \"from\": \"<candidate id>\", \"text\": \"...\"}}")
            continue
        cid, r, source, text = (str(item.get(k) or "").strip() for k in ("id", "r", "from", "text"))
        if not BNT_RE.fullmatch(cid):
            problems.append(f"{where}: `{cid or '(empty)'}` is not the id of a branch found in an existing test - fix: ids are `BN-T1`, `BN-T2`, ...")
            continue
        if cid in out:
            problems.append(f"{cid} appears twice in `candidate_branches` - fix: one entry per branch")
            continue
        for bad, what in ((r not in known_r, "`r` is not a row of `## Register`"), (not source, "`from` names no existing test candidate"),
                          (not text, "`text` is empty (the person is shown it)")):
            if bad:
                problems.append(f"{cid}: {what} - fix: name the requirement, the candidate id and the branch in words")
        out[cid] = {"r": r, "text": text, "from": source}
    return out


def _branch_homes(doc, owed, problems) -> dict:
    """`{branch: "excluded (role|person): <reason>"}` of the plan's `branch_homes`. Whether a person's answer is the one the
    branch rests on is the verdict's reading (`question_register.load`), not this gate's."""
    raw = doc.get("branch_homes") if isinstance(doc, dict) else None
    if raw is None:
        return {}
    if not isinstance(raw, list):
        problems.append(f"`branch_homes` must be a list of {BRANCH_HOME_FORM} - fix: write the list, or remove the key")
        return {}
    out = {}
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            problems.append(f"`branch_homes[{index}]` is not an object - fix: {BRANCH_HOME_FORM}")
            continue
        branch, home, reason, by, answer = (str(item.get(k) or "").strip() for k in ("branch", "home", "reason", "decided_by", "answer"))
        bad = ("names no branch of the register or of `candidate_branches`" if branch not in owed else
               "`home` is not `excluded` (a branch a row checks is named in that row's `branches`)" if home != "excluded" else
               "gives no `reason` (the person is shown it)" if not reason else
               "`decided_by` is not `role` or `person`" if by not in DECIDERS else
               "is decided by the person and names no `answer` (the id of the question they answered)" if by == "person" and not answer else "")
        if bad:
            problems.append(f"`branch_homes[{index}]` ({branch or 'no branch'}): {bad} - fix: {BRANCH_HOME_FORM}")
        else:
            out.setdefault(branch, f"excluded ({by}): {reason}")
    return out


def _rung_problem(rid, disposition, value, priority="") -> str:
    """The form of a `manual-*` row's `rung_basis`: what its P19 rung rests on (a probe, a question, or the environment's
    reason it cannot run). A kind known but not accepted (`not_measured`: the lower rung was not tried) is refused (RN1-13);
    a row of a priority in `rung_reason_priorities` owes `reason`. The role judges the rung; this requires that it was said."""
    accepted = _word_list("rung_kinds_accepted")      # AR-1: the kinds the door names are the data row, never a list in code
    fix = "fix: `\"rung_basis\": {\"kind\": \"%s\", \"ref\": \"<probe or question id, or the environment's reason>\"}`" % " | ".join(accepted)
    if not isinstance(value, dict):
        return f"{rid}: a `{disposition}` row has no `rung_basis` (what its P19 rung rests on) - {fix}"
    kind, ref = (str(value.get(k) or "").strip() for k in ("kind", "ref"))
    if not kind:
        return f"{rid}: its `rung_basis` has no `kind` - {fix}"
    allowed = _word_list("rung_kinds")
    if kind not in allowed:
        return f"{rid}: its `rung_basis` kind `{kind}` is not one of {', '.join(allowed)} - {fix}"
    if not ref:
        return f"{rid}: its `rung_basis` gives no `ref` (the probe or question id, or the environment's reason) - {fix}"
    if kind not in accepted:
        ways = [way for word, way in _word_map("rung_kind_fixes").items() if word in accepted] or [fix[len("fix: "):]]
        return f"{rid}: a `{disposition}` row rests on `{kind}` - not trying the lower rung is no reason to climb (P19) - fix: " + ", or ".join(ways)
    if priority and priority in _word_list("rung_reason_priorities") and not str(value.get("reason") or "").strip():
        return f"{rid}: a {priority} row is handed off automation - fix: add `\"reason\": \"<why a person or an agent checks it by hand>\"` to its `rung_basis`"
    return ""


def _patch_rung_problems(rid, row, found) -> list:
    """The rung refusals of a row's `if_answered` patches: the row as the answer would make it (RN1-13). A patch that is not
    an object, or that leaves a non-manual disposition, owes nothing; a problem the row itself already has (`found`) is said once."""
    out = []
    answered = row.get("if_answered")
    for question, letters in (answered.items() if isinstance(answered, dict) else ()):
        for letter, patch in (letters.items() if isinstance(letters, dict) else ()):
            merged = {**row, **patch} if isinstance(patch, dict) else None
            if merged is None or str(merged.get("disposition") or "") not in MANUAL_DISPOSITIONS:
                continue
            again = _rung_problem(rid, str(merged["disposition"]), merged.get("rung_basis"), str(merged.get("priority") or ""))
            if again and again != found:
                out.append(f"{rid} (if {question} = {letter}): {again[len(rid) + 2:]}")
    return out


def _read_plan(task_root, text, branches, problems, notes):
    """The plan's side of the accounting, read once for S3 and S4: `None` when there is no plan, else `{"rows": [(id, row,
    [branch ids])], "owed": {id: {"r", "text"}}, "checked": {branch: [row ids]}, "excluded": {branch: why}, "candidates",
    "doc"}`. What is wrong with the plan's own form goes to `problems`, what is only to be said to `notes`."""
    doc, rows = _plan(task_root)
    if doc is None:
        return None
    candidates = _candidate_branches(doc, set(_register_ids(text)), problems)
    owed = {r["bn"]: {"r": r["r"], "text": r["text"]} for r in branches["rows"] if BN_RE.fullmatch(r["bn"])}
    owed.update({cid: {"r": c["r"], "text": c["text"]} for cid, c in candidates.items()})
    checked, excluded, entries = {}, _branch_homes(doc, owed, problems), []
    for index, row in enumerate(rows):
        rid = str(row.get("id") or f"row[{index}]")
        disposition = str(row.get("disposition") or "")
        names = _row_branches(row, rid, problems)
        entries.append((rid, row, names))
        for name in names:
            reason = str(row.get("reason") or "").strip()
            if name not in owed:
                problems.append(f"{rid}: `{name}` is no branch of the register or of `candidate_branches` - fix: name an existing branch")
            elif disposition not in PLAN_EXCLUDING:
                checked.setdefault(name, []).append(rid)
            elif not reason:
                problems.append(f"{rid}: is `{disposition}` with no reason, so it leaves {name} out of the plan without a word - fix: write the "
                                "reason (the person is shown it), or move the branch to a row that checks it")
            else:
                excluded.setdefault(name, f"plan row {rid} is `{disposition}`: {cut(reason, 120)}")
        found = ""
        if disposition in MANUAL_DISPOSITIONS:
            found = _rung_problem(rid, disposition, row.get("rung_basis"), str(row.get("priority") or ""))
            if found:
                problems.append(found)
        problems.extend(_patch_rung_problems(rid, row, found))
    for name, why in excluded.items():
        notes.append(f"{name} is left out of the plan: {why}")
    return {"rows": entries, "owed": owed, "checked": checked, "excluded": excluded, "candidates": candidates, "doc": doc}


def bundle_candidate_records(task_root):
    """`(records | None, why)`: the `existing_test_candidates` entries of `work/context-bundle.json` that are objects with a non-empty
    `candidate_id`, in file order (TQ1-21: the ONE parser of the bundle's candidates, AR-13). No bundle, or none listed (an older
    bundle): `[]`. A bundle that cannot be read is `None` with the reason: the caller does not know."""
    path = Path(C.artifact(Path(task_root), "context-bundle.json"))
    if not path.is_file():
        return [], ""
    try:
        bundle = _load_json(path)
    except (OSError, ValueError) as exc:
        return None, f"context-bundle.json cannot be read ({type(exc).__name__})"
    listed = bundle.get("existing_test_candidates") if isinstance(bundle, dict) else None
    if isinstance(bundle, dict) and listed is None:
        return [], ""
    if not isinstance(listed, list):
        return None, "context-bundle.json is not an object with a list `existing_test_candidates`"
    return [c for c in listed if isinstance(c, dict) and str(c.get("candidate_id") or "").strip()], ""


def _bundle_candidates(task_root):
    """`(ids | None, why)`: the `candidate_id`s of `bundle_candidate_records` (a view of it); `None` with the reason when the bundle cannot be read."""
    records, why = bundle_candidate_records(task_root)
    if records is None:
        return None, why
    return [str(c["candidate_id"]).strip() for c in records], ""


def _walk_problems(task_root, plan, problems, notes) -> None:
    """Every existing test candidate of the bundle is named in a `candidates_walked` entry: its branches taken (`took`), or `none`
    with the reason. The strategist reads the tests; this only requires that each candidate was walked."""
    ids, why = _bundle_candidates(task_root)
    if ids is None:
        notes.append(f"existing test candidates not known: {why}; none was reconciled against the walk")
        ids = []
    raw, named = plan["doc"].get("candidates_walked") if isinstance(plan["doc"], dict) else None, set()
    form = '{"candidates": ["<id>"], "took": ["BN-T1"]} or {"candidates": ["<id>"], "none": "<why no branch>"}'
    if raw is not None and not isinstance(raw, list):
        problems.append(f"`candidates_walked` must be a list of {form} - fix: write the list")
        raw = []
    for index, item in enumerate(raw or []):
        where = f"`candidates_walked[{index}]`"
        listed, took = (item.get("candidates"), item.get("took")) if isinstance(item, dict) else (None, None)
        if not isinstance(listed, list) or not listed or any(not isinstance(c, str) for c in listed):
            problems.append(f"{where} names no candidates - fix: {form}")
            continue
        named.update(c.strip() for c in listed)
        took = [] if took is None else took
        none = str(item.get("none") or "").strip()
        if not isinstance(took, list) or any(not isinstance(t, str) for t in took) or bool(took) == bool(none):
            problems.append(f"{where}: takes branches (`took`) or says `none` with its reason, one of the two - fix: {form}")
        elif [t for t in took if t not in plan["candidates"]]:
            problems.append(f"{where}: `took` names {', '.join(t for t in took if t not in plan['candidates'])}, which `candidate_branches` does not hold - fix: add them there")
    missing = [c for c in ids if c not in named]
    if missing:
        problems.append(f"{len(missing)} existing test candidate(s) of `context-bundle.json` are named in no `candidates_walked` entry "
                        f"({DV.named(missing, limit('refusal_units_shown'), tail=' ({n} in all)')}) - fix: walk each, {form}")


def s3_problems(task_root, text, branches):
    """`(problems, notes)` of the S3 exit: every register branch (`BN-n`) and every branch found in an existing test (`BN-T<n>`)
    is named in a row's `branches` or excluded in `branch_homes` (a `skip`/`unverifiable` row excludes it by its own reason); every
    existing test candidate is walked; every `manual-*` row says what its rung rests on. Direction of error: a refusal with a door."""
    problems, notes = [], []
    plan = _read_plan(task_root, text, branches, problems, notes)
    if plan is None:
        return [], ["no test-plan.json yet: nothing to reconcile"]
    for name, info in plan["owed"].items():
        if name not in plan["checked"] and name not in plan["excluded"]:
            problems.append(f"{name} ({info['r']}: \"{cut(info['text'], limit('unit_text_shown'))}\") has no home in the plan - fix: name it in the "
                            f"`branches` of the row that checks it, or exclude it in `branch_homes` {BRANCH_HOME_FORM}")
    _walk_problems(task_root, plan, problems, notes)
    return problems, notes


def _case_records(task_root) -> list:
    """The story's cases: `{"id", "text", "plan_row", "entries", "problem", "carried"}`. A case file the contract reads wherever
    the project keeps them (`contract.case_files`); `branches` is ONE line of JSON, parsed by the contract's own reader."""
    out = []
    for path in C.case_files(Path(task_root)):
        text = C.read_text(path)
        cid = (C.front_line(text, "id") or "").strip().strip("\"'") or Path(path).stem
        entries, problem = C.parse_json_list(C.front_line(text, "branches"))
        found = C.CASE_PLAN_ROW_RE.search(text)
        row = found.group(1) if found else (C.front_line(text, "plan_row") or "").strip()
        decision = (C.front_line(text, "reuse_decision") or "").strip().strip("\"'").partition(":")[0].strip()
        out.append({"covers": set(C.REQ_ID_RE.findall(C.front_line(text, "covers") or "")), "status": C.case_status(path),
                    "id": cid, "text": text, "plan_row": row, "reused": decision in _word_list("reused_decisions"), "entries": entries or [], "problem": problem,
                    "carried": {str(e.get("id") or "").strip() for e in entries or []}})
    return out


def _case_entry_problems(task_root, case, owed) -> list:
    """The form of one case's `branches` line: the branch exists, its Then is one of the case's, its partition one the case names
    (`contract.then_number`, `case_then_numbers`, `partition_key`: the one reading of each, AR-13)."""
    cid = case["id"]
    if case["problem"]:
        return [f"{cid}: `branches` {case['problem']} - fix: ONE line, `branches: [{{\"id\": \"BN-1\", \"then\": 2, \"partition\": \"P-name\"}}]`"]
    import s5_precheck as S5
    numbers = C.case_then_numbers(task_root, cid, case["text"])
    named = {C.partition_key(p) for p in S5.case_partitions(re.sub(r"(?m)^branches:[^\n]*", "", case["text"], count=1))}
    out = []
    for entry in case["entries"]:
        name = str(entry.get("id") or "").strip()
        if name not in owed:
            out.append(f"{cid}: `branches` names `{name or '(no id)'}`, no branch of the register or of `candidate_branches` - fix: name an existing branch")
            continue
        then, partition = C.then_number(entry.get("then")), entry.get("partition")
        if then < 1 or then not in numbers:
            out.append(f"{cid}: {name} names Then {entry.get('then')!r}, and the case's Thens are {', '.join(map(str, numbers)) or 'none'} - fix: name the Then that proves the branch")
        if partition not in (None, "") and (not isinstance(partition, str) or not C.partition_key(partition) or C.partition_key(partition) not in named):
            out.append(f"{cid}: {name} names partition {partition!r}, which the case does not name (`P-<name>` in its body) - fix: name one of them, or leave the partition out")
    return out


def _round_homes(task_root, owed, problems) -> dict:
    """`{BN: [{"round", "home", "reason"}]}`, newest round first: the `## Branch homes` tables of the findings files. Rounds are
    PREPENDED, a newer round beats an older one, and an older round's bytes are never edited, so only the NEWEST round of a file
    is held to its form (an old malformed row could never be mended)."""
    import critic_rollcall as CR
    homes = {}
    for path in CR.findings_files(task_root):
        for index, first in CR.rounds(path.read_text(encoding="utf-8", errors="replace")):
            body = _section(first, BRANCH_HOMES_HEADING)
            rows, bad_header = _table_rows(body, HOME_COLUMNS) if body is not None else ([], "")
            if bad_header and index == 0:
                problems.append(f"`{BRANCH_HOMES_HEADING}`: {bad_header} - fix: `{CASE_HOME_FORM}`")
            for cells in rows:
                name, home, reason = (C.strip_cell(c) for c in cells)
                if index == 0 and (name not in owed or not home or (home == "excluded" and not reason)):
                    problems.append(f"`{BRANCH_HOMES_HEADING}` row `{name or '(empty)'}`: " + (
                        "no branch of the register or of `candidate_branches`" if name not in owed else
                        "no home" if not home else "`excluded` gives no reason (the person is shown it)") + f" - fix: `{CASE_HOME_FORM}`")
                    continue
                homes.setdefault(name, []).append({"round": index, "home": home, "reason": reason})
    return homes


def _scoped(scope):
    """The predicate 'this case is in the critic's scope': `scope` None (unknown) is every case, the refusing direction."""
    return (lambda case: True) if scope is None else (lambda case: case["id"] in scope or any(s.rsplit("/", 1)[-1] == case["id"] for s in scope))


def _label(name, info) -> str:
    return f"{name} ({info['r']}: \"{cut(info['text'], limit('unit_text_shown'))}\")"


def s4_problems(task_root, text, branches, scope):
    """`(problems, notes)` of the S4 exit (the case critic's): every branch a plan row checks is carried by a case (`branches` on
    the case) or has a home in the NEWEST round's `## Branch homes` (`home: TC-n` or `excluded` with a reason). A case outside the
    critic's `scope` is a note, not a refusal (it did not read it; the verdict names the branch); `scope` None is the whole plan."""
    problems, notes = [], []
    plan = _read_plan(task_root, text, branches, [], [])
    if plan is None:
        return [], ["no test-plan.json: nothing to reconcile"]
    cases, in_scope = _case_records(task_root), _scoped(scope)
    by_id = {c["id"]: c for c in cases}
    for case in cases:
        (problems if in_scope(case) else notes).extend(_case_entry_problems(task_root, case, plan["owed"]))
    homes = _round_homes(task_root, plan["owed"], problems)
    for rid, row, names in plan["rows"]:
        if str(row.get("disposition") or "") in PLAN_EXCLUDING:
            continue
        row_cases = [c for c in cases if c["plan_row"] == rid]
        for name in dict.fromkeys(n for n in names if n in plan["owed"]):
            if any(name in c["carried"] for c in cases):
                continue
            label, entries = _label(name, plan["owed"][name]), homes.get(name, [])
            if not entries:
                scoped = [c["id"] for c in row_cases if in_scope(c)]
                if not row_cases:
                    notes.append(f"{label} is on plan row {rid}, which has no case yet: nothing can carry it (the case review's dimension 7 names that row)")
                elif not scoped:
                    notes.append(f"{label}: the cases of plan row {rid} ({', '.join(c['id'] for c in row_cases)}) are outside this review's scope; the verdict names it if it stays unhomed")
                else:
                    problems.append(f"{label} is on plan row {rid}; its case {', '.join(scoped)} does not carry it and the round names no home - fix: add it to the "
                                    f"case's `branches` line, or write `{CASE_HOME_FORM}` under `{BRANCH_HOMES_HEADING}` of this round")
                continue
            latest = entries[0]
            if latest["home"] == "excluded":
                continue
            target = by_id.get(latest["home"])
            if target is not None and (name in target["carried"] or target["reused"]):
                continue        # a reused case (`reuse_decision` extend/dedupe/updated) is not edited to carry the line
            said = f"{label}: the round says `home: {latest['home']}`, " + ("no such case exists" if target is None else "and that case does not carry it")
            if latest["round"] >= 1 or sum(1 for e in entries if e["home"] == latest["home"]) >= 2:
                problems.append(f"{said}, though an earlier round already named it - fix: carry it in that case, or write `{name} | excluded | <why>` in this round")
            else:
                notes.append(f"{said}: the repair is ahead, nothing is refused yet")
    return problems, notes


def critic_scope(task_root):
    """The case ids the case critic reviews (`case_versions.review_scope`, THE one computation, as `Driver.critic_scope`), or
    None when it cannot be read or is empty: an unknown scope is the whole plan, never nothing (FR-59)."""
    try:
        import case_versions
        scope = case_versions.review_scope(Path(task_root))
    except Exception:
        return None
    return [str(c) for c in scope] or None


def _stage_check(task_root, where, hint, run) -> dict:
    """The shape of `s2_check` for S3 and S4: `blocks` empty means the stage passes. A register that is absent, `legacy` or not
    recorded is one note and nothing reconciled (the S2 gate and the verdict own those); an unreadable one raises `Unreadable`."""
    text = _read_register(task_root)
    if text is None:
        return {"state": "no_register", "blocks": [], "notes": [], "unhomed": []}
    state = branch_state(task_root, text)
    if state["state"] == "unreadable":
        raise Unreadable(state["reason"])
    if state["state"] in ("legacy", "missing"):
        note = state["reason"] or f"the register has no `{BRANCHES_HEADING}` section: nothing reconciled here (the S2 gate and the verdict name it)"
        return {"state": state["state"], "blocks": [], "notes": [note], "unhomed": []}
    problems, notes = run(text, state["branches"])
    shown = limit("refusal_units_shown")
    lines = [DV.one_line(p) for p in problems[:shown]]
    if len(problems) > shown:
        lines.append(f"{len(problems) - shown} more problems ({len(problems)} in all); fix these first, the check runs again")
    blocks = [(f"REJECT — {len(lines)} problem(s) in {where}:", lines)] if lines else []
    return {"state": state["state"], "blocks": blocks, "notes": notes, "unhomed": [], "hint": hint}


def s3_check(task_root) -> dict:
    return _stage_check(task_root, "the branches of the plan (`branches`, `branch_homes`, `candidates_walked`, `rung_basis`)",
                        "branch accounting: every branch of the register needs a row of the plan that checks it or an exclusion with a reason; "
                        "every existing test candidate is walked; a manual row says what its rung rests on.",
                        lambda text, branches: s3_problems(task_root, text, branches))


def s4_check(task_root) -> dict:
    return _stage_check(task_root, "the branches of the cases (`branches` on a case, `## Branch homes` in the findings)",
                        "branch accounting: every branch a plan row checks is carried by a case (`branches` on the case) or homed in this round's "
                        f"`{BRANCH_HOMES_HEADING}` (`{CASE_HOME_FORM}`).",
                        lambda text, branches: s4_problems(task_root, text, branches, critic_scope(task_root)))


# --- S5 and the verdict: where each (branch, Then, partition) is proved (step 3, TQ1-20) ---------------------------------
# ONE reader of the manifest's side of a branch (`_pair`): the S5 exit asks "does the pair have a home" (covered, or held in a
# remainder or an `unresolved[]` row), the verdict asks "is it covered". Nothing here runs a test or opens a test file.

def _same_case(a, b, cfg) -> bool:
    a, b = str(a or "").strip(), str(b or "").strip()
    return bool(a and b) and (C.case_matches(a, b, cfg=cfg) or C.case_matches(b, a, cfg=cfg))


def _labels(row, keys) -> set:
    """The comparable partition labels a row (an `unresolved[]` row or a `tests[]` entry) holds under `keys`."""
    out = set()
    for key in keys:
        value = row.get(key) if isinstance(row, dict) else None
        out |= {C.partition_key(v) for v in (value if isinstance(value, list) else [value]) if v is not None}
    return out - {""}


def _bound_tests(manifest, cfg, case, binding) -> tuple:
    """`(named, tests)`: the `tests[]` entries a `then_bindings` row stands on. A row that names its instance (`instance_id`) stands
    on the entries of that instance that prove `case` - none when the manifest holds no such instance (F-1). A row that names none
    (`instance_id` None) stands on every entry that proves `case`, as the S5-1 rows are written."""
    instance = str(binding.get("instance_id") or "").strip()
    tests = [t for t in C.manifest_tests(manifest) if any(_same_case(link, case, cfg) for link in C.manifest_test_links(t, cfg))]
    if instance:
        tests = [t for t in tests if instance in C.instance_id_aliases(t, cfg)]
    return bool(instance), tests


def _partition_declared(tests, key) -> bool:
    """Does one of `tests` (the entries a binding stands on) stand for the partition `key`: it declares it, or declares no partition
    at all (a test with none stands for all of them, as `s5_precheck` reads it). No test: no."""
    for test in tests:
        declared = _labels(test, C.UNRESOLVED_PARTITION_KEYS)
        if not declared or key in declared:
            return True
    return False


def _speaking(unresolved, tests, partition, cfg) -> list:
    """The `unresolved[]` rows that speak about the pair for `tests`: `acceptance.row_slice` (AR-13, the one reader of a row's slice)
    read against each entry carrying the PAIR's own partition (the entry's own declaration is `_partition_declared`'s). With no entry
    the probe names no instance: a whole-case row and a row slicing the pair's partition speak, a row naming an instance does not."""
    probes = []
    for test in tests or [{}]:
        probe = {k: v for k, v in test.items() if k not in C.UNRESOLVED_PARTITION_KEYS}
        if partition not in (None, ""):
            probe["partition"] = partition
        probes.append(probe)
    return [u for u in unresolved if any(not AC.row_slice(u, probe, u.get("case"), cfg=cfg) for probe in probes)]


def _pair(manifest, cfg, case, then, partition) -> str:
    """`covered` | `held` | `none` for the pair (case, Then number, partition) of the manifest. `covered`: a `then_bindings` row of the
    Then is `covered`, stands on a test of the manifest that proves the case (the instance it names, F-1; any test of the case when
    it names none), no `unresolved[]` row speaks about the pair for that test (a whole-case row, a row naming that instance, a row
    slicing this partition), and (for a partition) a test it stands on declares it or declares none - the declaring test is the
    bound one, never another Then's. `held`: not covered, but the manifest keeps it somewhere (a remainder row, a speaking
    `unresolved[]` row). `none`: the manifest says nothing - the branch has no home there (a binding to an instance the manifest does
    not hold included). Error direction: toward `held`/`none`, never toward `covered`, with ONE named edge: a `covered` row that
    names no instance (the contract requires `instance_id` on a row, so this is a damaged manifest) while no test of the manifest
    proves the case at all reads `covered` for a pair with no partition - today's any-test rule, pinned; a refusal of it is queued."""
    key = C.partition_key(partition) if partition not in (None, "") else ""
    unresolved = [u for u in C.manifest_unresolved(manifest) if _same_case(u.get("case"), case, cfg)]
    bindings = [b for b in manifest.get("then_bindings") or [] if isinstance(b, dict) and _same_case(b.get("case"), case, cfg)
                and then >= 1 and C.then_number(b.get("then")) == then]
    held = [b for b in bindings if str(b.get("status") or "") != "covered"]
    for binding in bindings or [{}]:
        named, tests = _bound_tests(manifest, cfg, case, binding)
        rows = _speaking(unresolved, tests, partition, cfg)
        held = held or rows
        if (str(binding.get("status") or "") == "covered" and (tests or not named) and not rows
                and (not key or _partition_declared(tests, key))):
            return "covered"
    return "held" if held else "none"


def _manifest(task_root):
    """`(manifest, cfg)`; `({}, cfg)` when there is no manifest file (the pair is then `none`)."""
    return C.load_json(C.artifact(Path(task_root), "automation-manifest.json")), C.case_config(Path(task_root))


def s5_problems(task_root, text, branches, scope):
    """`(problems, notes)` of the S5 exit (the automator's): every (branch, Then, partition) a case of the dispatch carries is covered
    in the manifest, or held in a remainder or an `unresolved[]` row (with its slice) - a partition is never dropped by the shape of
    a manifest row (L-6). `scope` None (the dispatch cannot be read) is every case: the refusing direction (m18). A case outside the
    window is a note; a manual case is not judged here (its record is read at the verdict); no manifest yet is nothing to check."""
    problems, notes = [], []
    plan = _read_plan(task_root, text, branches, [], [])
    if plan is None:
        return [], ["no test-plan.json: nothing to reconcile"]
    if not C.artifact(Path(task_root), "automation-manifest.json").is_file():
        return [], ["no automation-manifest.json yet: nothing to reconcile (the verdict names a branch nobody proved)"]
    manifest, cfg = _manifest(task_root)
    in_scope = _scoped(scope)
    rows = {rid: row for rid, row, _names in plan["rows"]}
    for case in _case_records(task_root):
        if str((rows.get(case["plan_row"]) or {}).get("disposition") or "") in MANUAL_DISPOSITIONS + PLAN_EXCLUDING:
            continue
        for entry in case["entries"]:
            name, then, partition = str(entry.get("id") or "").strip(), C.then_number(entry.get("then")), entry.get("partition")
            if name not in plan["owed"] or _pair(manifest, cfg, case["id"], then, partition) != "none":
                continue
            where = f"Then {then}" + (f", partition {partition}" if partition not in (None, "") else "")
            (problems if in_scope(case) else notes).append(
                f"{case['id']}: {_label(name, plan['owed'][name])} - {where} is bound to no instance that covers it and no remainder or "
                "`unresolved` row holds it - fix: bind it in `then_bindings` to a test that proves it, or record it in `unresolved` "
                "(with `partition` for a part of the case) and its reason: `manifest_put.py --task <T> --fragment <file>`")
    return problems, notes


UNKNOWN_SCOPE = "unknown_scope"      # `s5_scope` found no window it can read: never "every case" (RN1-26, FR-59, AR-28)


def _s5_window(task_root):
    """`(found, returned, error)` of the S5 window, read ONCE per exit (AR-13: `s5_precheck.window_dispatch` and `dispatch_ids` are the
    one reader of the live dispatches; `s5_scope` and `s5_check` both read this and never look the state up twice): `found` is the
    dispatch the exit judges (the running one, else the ONE `returned_unaccepted`), `returned` the ids of the returned ones, `error`
    the exception when the state could not be read (never swallowed into "none returned")."""
    try:
        import s5_precheck as S5
        root = Path(task_root)
        return S5.window_dispatch(root), S5.dispatch_ids(root, S5.RETURNED_STATUS), None
    except Exception as exc:
        return None, [], exc


def _s5_running_count(task_root) -> int:
    """How many S5 automators are running (by `s5_precheck.dispatch_ids`, the one reader); 0 when the state cannot be read: the
    cause text then falls to its old wording, and the unreadable state itself is `_s5_window`'s `error`, said first."""
    try:
        import s5_precheck as S5
        return len(S5.dispatch_ids(Path(task_root), "running"))
    except Exception:
        return 0


def s5_scope(task_root):
    """The cases of the S5 window the exit judges: the dispatch `_s5_window` found, then `dispatch_scope` of it (the two readers,
    AR-13). Two returned, none, an unreadable or an empty scope: `UNKNOWN_SCOPE` - never None and never "every case" (RN1-26).
    INVARIANT: the returned window is read after the running one found nothing (`s5_precheck.window_dispatch`), so a running
    window is never judged by a returned one."""
    found, _returned, error = _s5_window(task_root)
    if error is not None:
        return UNKNOWN_SCOPE
    try:
        import s5_precheck as S5
        scope = S5.dispatch_scope(Path(task_root), found)
    except Exception:
        return UNKNOWN_SCOPE
    return scope if scope else UNKNOWN_SCOPE


def s5_check(task_root) -> dict:
    def run(text, branches):
        if not C.artifact(Path(task_root), "automation-manifest.json").is_file():
            return s5_problems(task_root, text, branches, None)      # no manifest yet: `s5_problems` says so and reads no scope
        scope = s5_scope(task_root)
        if scope == UNKNOWN_SCOPE:
            found, returned, error = _s5_window(task_root)
            if error is not None:
                cause = f"the dispatch state could not be read ({type(error).__name__}: {error})"
            elif found:
                cause = f"dispatch {found} has an empty scope"
            else:
                running = _s5_running_count(task_root)
                if running >= 2:
                    cause = f"{running} automators are running and none was named (QA_FACTORY_DETECTOR_DISPATCH / QA_FACTORY_DRIVER_RUN)"
                else:
                    cause = f"no running qa-automator dispatch and {len(returned) or 'none'} returned unaccepted"
            raise Unreadable(f"the S5 window's scope could not be read: {cause}; state/controller.json dispatches")
        return s5_problems(task_root, text, branches, scope)
    return _stage_check(task_root, "the branches of the manifest (`then_bindings`, `unresolved`)",
                        "branch accounting: every (branch, Then, partition) of the cases you carry is bound to a test that covers it, or "
                        "recorded in `unresolved` (with a `partition` slice) or as a remainder, with its reason.", run)


STAGE_RUNNERS = {"S2": s2_check, "S3": s3_check, "S4": s4_check, "S5": s5_check}


LIVE_DISPATCH = ("running", "returned_unaccepted")      # `controller.RETURNED` is the second: a stop without a bind receipt


def _running_stage(task_root):
    """Which of `STAGE_CHECKS` the gate is judging in this story, or None (the gate then says it cannot tell, never a guess): the
    stage the gate NAMED (`planning_contract.detector_stage_named`, the finisher's own: it wins over any inference; a named stage
    this gate does not judge is None - never another stage's check, FR-59, AR-28); with none named, the first stage its
    `pipeline.json` says is `running`, else the ONE stage with a live dispatch in `state/controller.json`
    (`_running_dispatch_stage`). The story is `_running`'s: no second listing of pipelines."""
    from planning_contract import detector_stage_named
    named = detector_stage_named()
    if named:
        return named if named in STAGE_CHECKS else None
    try:
        stages = _load_json(Path(task_root) / "pipeline.json")["stages"]
        found = next((s for s in STAGE_CHECKS if (stages.get(s) or {}).get("status") == "running"), None)
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        found = None
    return found or _running_dispatch_stage(task_root)


def _running_dispatch_stage(task_root):
    """The ONE stage of `STAGE_CHECKS` that has a live dispatch (`LIVE_DISPATCH`: `running`, or `returned_unaccepted` - a stop with no
    `story_step bind` receipt leaves the finisher there, and `finish` is its accept target) in the controller's state, else None.
    A REWORK or repair round of a stage that is already accepted hands off while `pipeline.json` still says `done` (t-430,
    test_story_run_s7_live: every repair round's `finish` was refused `unreadable` - a gate that judged nothing on a round that did
    the work). INVARIANT (FR-59, AR-28): this is read only when the gate NAMED no stage (the finisher's own wins, t-440) and the pipeline names no running stage; two
    stages with a live dispatch each, no state, an unreadable one, or a stage this gate does not judge all read as None - the gate
    then says it cannot tell the stage, and one stage's finish is never judged by another stage's check. Reader of the dispatches:
    `controller.json` `dispatches` (AR-13: `s5_precheck.running_dispatch` answers by role and stage, not "any stage")."""
    try:
        state = _load_json(Path(task_root) / "state" / "controller.json")
        live = {str(d.get("stage") or "") for d in (state.get("dispatches") or {}).values()
                if isinstance(d, dict) and d.get("status") in LIVE_DISPATCH} & set(STAGE_CHECKS)
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None
    return next(iter(live)) if len(live) == 1 else None


def _waiver_tail(stage: str = "S2") -> str:
    """The doors of a person's word, in the sibling form (`planning_contract`, `critic_rollcall`): the whole refusal by the
    gate's own name, one line by `<part of the line>` (a unit id is a part). Both parse as printed (no quote of the
    finding's own text is ever put inside the command)."""
    whole = door(f'waiver.py --task <TICKET> --stage {stage} --block "{WHOLE_BLOCK}"')
    part = door(f'waiver.py --task <TICKET> --stage {stage} --block "<part of the line>"')
    return f"A person's word passes all of these: `{whole}`; one line of them: `{part}` {WHOLE_PART} (a unit id such as `U-...` is a part)."


def _running(root):
    """The folder of the story to judge, or None. Another story is never judged: `planning_contract.detector_story` (GW1-10 F-1, the
    one rule) gives the story the gate NAMES. A NAMED story is judged as it stands (its stage is `_running_stage`'s answer, which
    may be None: exit 3). An UNNAMED call (a hand run, no `QA_FACTORY_DETECTOR_STORY`) takes the newest story and judges it only if
    its pipeline says `running` for some stage of `STAGE_CHECKS`; no such story is None, never a story picked for want of another.
    Step 2 takes the role of the stopped worker as well (queued: the verdict's F11)."""
    from planning_contract import detector_story, detector_story_named
    if detector_story_named():       # the gate NAMED the story: it is the one to judge (the stage argument is not read for a named story)
        found = detector_story(root, stage_id=STAGE_CHECKS[0])
        return Path(found) if found is not None else None
    for stage in STAGE_CHECKS:
        task_root = detector_story(root, stage_id=stage)
        if task_root is None:
            continue
        try:
            stages = _load_json(Path(task_root) / "pipeline.json")["stages"]
            if stages[stage]["status"] == "running":
                return Path(task_root)
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return None


def detector_main(root=None) -> int:
    """Zero-argument entry of the exit gate of S2-S5. Exit 0: nothing refused (notes name what was not known); exit 1: the
    contract's blocks (`detector_verdict`); exit 3: the check could not run (`UNREADABLE: ...`, FR-59, P22) - also when no story
    to judge is found, or the stage of the story cannot be told (`_running_stage` None), because a gate that cannot tell which
    story or stage it judges has judged nothing."""
    try:
        task_root = _running(root)
        if task_root is None:
            print(DV.unreadable_line("branch_accounting could not find a story to judge (none named, none with a running stage)"))
            return DV.EXIT_UNREADABLE
        stage = _running_stage(task_root)
        if stage is None:
            print(DV.unreadable_line("branch_accounting could not tell which stage of the story is running"))
            return DV.EXIT_UNREADABLE
        result = STAGE_RUNNERS[stage](task_root)
    except Unreadable as exc:
        print(DV.unreadable_line(f"branch_accounting could not read what it checks ({exc})"))
        return DV.EXIT_UNREADABLE
    except Exception as exc:
        print(DV.unreadable_line(f"branch_accounting could not complete ({type(exc).__name__}: {exc})"))
        return DV.EXIT_UNREADABLE
    if result["state"] == "no_register":
        print(f"branch_accounting: {task_root.name} has no requirements-register.md yet - nothing to check")
        return 0
    for note in result["notes"]:
        print("note: " + DV.one_line(note))
    if not result["blocks"]:
        print(f"branch_accounting: OK ({result['state']})")
        return 0
    for header, lines in result["blocks"]:
        print(header)
        for line in lines:
            print("- " + line)
    print(result.get("hint") or "branch accounting: every unit of the story's text needs a home, every branch a row. "
          "`--unhomed --task <TICKET>` lists the units still without one; `--units` lists them all.")
    if any(ATTACHMENTS_HEADING in header for header, _lines in result["blocks"]):
        print("files: `--attachments --task <TICKET>` lists each with the call that opens it; a row says what you saw "
              "(`agrees`, `contradicts` with its question, `not_an_expectation`, `not_opened`), never your pick of a side.")
    print(_waiver_tail(stage))
    return 1


# --- the verdict: one record per debt (step 3, TQ1-20) -------------------------------------------------------------------
# `account(art)` recomputes everything from the story's own material (no stand, no other story, no run archive): what passed the
# detectors by a person's word, a `--apply-fixes` after the critic's finish, an edited case or a changed ticket is not lost here.
# Direction of error: toward a debt (`after_checks`) or `no`; nothing unknown becomes a pass (FR-41, FR-59).

SOURCE_KIND = "branches"                        # the `source` of every record of this section (report_facts and check_delivery read it)


def _debt(kind, key, requirements, to_check, how, **extra) -> dict:
    return {"text": "", "kind": kind, "case": "", "ref": key, "item_key": key, "requirements": [r for r in requirements if r],
            "to_check": to_check, "how": how, "source": SOURCE_KIND, **extra}


def _questions(root) -> dict:
    """`{id: question}` of `question_register.load` (AR-13); `{}` when it cannot be read (an answer nobody can read confirms nothing)."""
    try:
        import question_register as QR
        return {q["id"]: q for q in QR.load(root)["questions"]}
    except Exception:
        return {}


def _confirmed(qmap, qid) -> bool:
    """Did the person answer question `qid`, on the row they saw (`answered`, `question_register.settled`, not changed since)?"""
    import question_register as QR
    question = qmap.get(qid)
    return bool(question and question.get("status") == "answered" and question.get("changed_since_answer") is not True
                and QR.settled(question))


def _names_branch(question, token) -> bool:
    """An id (a branch `BN-n`, a requirement `R-n`) stands in the question's own text (`question`, `source_says`, a list of
    `{quote, where}` read as its text): the only binding a `branch_homes` answer has, and how `code_says_check` finds the question
    that names a requirement. ONE search of the text, not a second (t-1677 C-8)."""
    held = " ".join(str(question.get(k) or "") for k in ("question", "source_says"))
    return bool(re.search(rf"(?<![\w-]){re.escape(token)}(?!\w)", held))


# --- an exclusion of the register: whose decision is it (t-1676, WG1-1) ---------------------------------------------
# LOCAL-1: S2 wrote `excluded: ... (person's scope decision, s1-conflict-...)` while the person's words file said only "only the
# add-to-cart function": the role's inference was filed under the person's name and the territory of B-1/B-3 vanished before the
# cases. Decided by FORM, never by a phrase ("person's" is searched nowhere, FR-12): an `excluded:` reason is either a question
# the person answers (`Q<n>(<letter>): <why>`, <letter> the reading that leaves the part out) or the person's own recorded words
# QUOTED from `state/words/<file>.txt`. Anything else is the role's inference and the S2 exit refuses it; the door is the question.
MIN_QUOTE_WORDS = 3                 # a one-word fragment cannot carry a scope decision
QFORM_RE = re.compile(r"\s*(Q-?\d+)(?:\(([A-Za-z])\))?\s*:\s*(.*)$", re.DOTALL)
_QUOTE_HEAD = r'^"(?P<quote>.+?)"\s*\((?P<file>[^()]+?)\)\s*'      # the ONE prefix of the quote form: `"<words>" (<file>.txt)`
QUOTE_FORM_RE = re.compile(_QUOTE_HEAD + r':\s*(?P<why>\S.*)$', re.DOTALL)
WORDS_FILE_RE = re.compile(r"[A-Za-z0-9._-]+\.txt")
QUESTION_FORM = "`excluded: Q<n>(<letter>): <why>` (an open_questions row Q<n> with severity blocker; <letter> is the reading that leaves the part out)"
QUOTE_FORM = "`excluded: \"<their words>\" (<file>.txt): <why>` (at least 3 words of theirs, quoted from state/words)"


def _quote_problem(task_root, quote, name) -> str:
    """Why `quote` is not in the person's words file `name`, or `""`. The file is one of `state/words/` (no path, no `..`) and is
    read by `person_words.read`, the one reader of a words file; an unreadable record confirms nothing (FR-59)."""
    path = Path(task_root) / "state" / "words" / name
    if not WORDS_FILE_RE.fullmatch(name) or ".." in name or not path.is_file():
        return f'"{name}" is not a file of the person\'s words (state/words)'
    import person_words as PW
    try:
        words = PW.read(None, str(path), "--words")
    except (PW.WordsRefused, OSError) as exc:
        return f"{name} cannot be read as the person's words ({str(exc).split('.')[0][:90]})"
    if len(quote.split()) < MIN_QUOTE_WORDS:
        return f"quote at least {MIN_QUOTE_WORDS} words of theirs"
    if " ".join(quote.split()) not in " ".join(str(words).split()):
        return f"the quote is not in {name}: quote their words as written"
    return ""


quote_problem = _quote_problem      # the public name: gate A's "decided by your words" and the S2 exit read the quote through THIS one reader (AR-13)
# A fork Decision that STARTS with the quote form (D1-B B1): the same prefix as QUOTE_FORM_RE (`_QUOTE_HEAD`), the `: <why>` tail optional.
QUOTE_HEAD_RE = re.compile(_QUOTE_HEAD + r'(?::.*)?$', re.DOTALL)


def decided_by_words(task_root, text=None) -> dict:
    """`{R-n: {"quote", "file"}}` of the reading forks the person closed in their OWN words: the Decision cell holds the quote form
    (`planning_contract.register_fork_quotes`) AND `quote_problem` is empty (at least `MIN_QUOTE_WORDS` words, found in the file under
    `state/words`). Register order. Never raises: an unreadable register or an unreadable words file closes nothing (an unknown never
    closes a card, FR-59)."""
    try:
        text = _read_register(task_root) if text is None else text
        if text is None:
            return {}
        import planning_contract as PC
        found = PC.register_fork_quotes(text)
        return {r: dict(v) for r, v in found.items() if quote_problem(task_root, v["quote"], v["file"]) == ""}
    except Exception:  # noqa: BLE001
        return {}


def decided_question_check(task_root, text) -> list:
    """`[str]` problems (D1-B B4, F-2 a): an unsettled readiness question whose text names R ids that the person ALL decided in their
    words (`decided_by_words`) asks what S1 already settled. The door is `asks_beyond_words: <what the words leave open>` on the
    question (a non-empty string passes it); a question that names no R id, or one id that is not word-closed, is not judged (no
    reading of meaning, FR-12). [] when nothing is decided by words."""
    closed = decided_by_words(task_root, text)
    if not closed:
        return []
    import question_register as QR
    out = []
    for q in _questions(task_root).values():
        if QR.settled(q) or str(q.get("asks_beyond_words") or "").strip():
            continue
        ids = sorted(C.named_r_ids(q), key=lambda r: int(r[2:]))
        if ids and all(i in closed for i in ids):
            files = ", ".join(dict.fromkeys(closed[i]["file"] for i in ids))
            out.append(f"{q.get('id')}: it asks about {', '.join(ids)}, which the person already decided in their words ({files}) - fix: "
                       "remove the question, or set `asks_beyond_words: <what the words leave open>` on it")
    return out


def _exclusion(task_root, reason, qmap) -> dict:
    """The one reader of the reason after `excluded:`: `{"form": question|quote|none, "qid", "letter", "quote", "file", "why",
    "decided": bool, "problem": str}`. `problem` is what the S2 exit refuses (`""`: it stands); `decided` is what delivery may read as
    the person's word. An OPEN blocking question has no problem and is not decided: the S2 halt asks it before any plan. The form
    `Q<n>:` with no letter is read as delivery always read it (decided when the person answered) and refused at the S2 exit: a
    `keep it` answer must never be filed as an exclusion by the person's word (t-1677 C-5)."""
    out = {"form": "none", "qid": "", "letter": "", "quote": "", "file": "", "why": "", "decided": False, "problem": ""}
    reason = str(reason or "").strip()
    found = QFORM_RE.match(reason)
    if found:
        import question_register as QR
        qid, letter = found.group(1), (found.group(2) or "").lower()
        question = (qmap or {}).get(qid)
        out.update(form="question", qid=qid, letter=letter, why=found.group(3).strip())
        if question is None:
            out["problem"] = f"{qid} is not a question of this story - fix: raise it in open_questions with severity blocker, or name an existing one"
        elif letter and letter not in str(question.get("letters") or ""):
            out["problem"] = f"{qid} has no reading {letter} - fix: name the reading that leaves the part out"
        elif QR.settled(question):
            key = QR.answer_key(question)
            out["decided"] = _confirmed(qmap, qid) and (not letter or key == letter)
            if not out["decided"]:
                out["problem"] = f"{qid} was answered {key or 'in words'}: the part stays in scope - give it a home"
        elif not QR.open_blocker(question):
            out["problem"] = f"{qid} must be a blocking question (severity blocker): the scope is decided before the plan - fix: make it a blocker"
        if not out["problem"] and not letter:
            out["problem"] = f"{qid}: name the reading that leaves the part out - fix: excluded: {qid}(<letter>): <why>"
        return out
    found = QUOTE_FORM_RE.match(reason)
    if found:
        out.update(form="quote", quote=" ".join(found.group("quote").split()), file=found.group("file").strip(), why=found.group("why").strip())
        out["problem"] = _quote_problem(task_root, out["quote"], out["file"])
        out["decided"] = not out["problem"]
        return out
    out["problem"] = f"an exclusion nobody decided - fix: ask the person ({QUESTION_FORM}) or quote their words ({QUOTE_FORM})"
    return out


def exclusions(task_root, text=None) -> list:
    """`[{"tokens", "texts", "reason", **_exclusion(...)}]`: every `excluded:` row of the register with its reading (gate A shows the
    quote-form ones, delivery reads them). Never raises: an unreadable register is `[]` (the S2 exit refuses that by its own path)."""
    try:
        text = _read_register(task_root) if text is None else text
        if text is None:
            return []
        found = reconcile(task_root, text, branch_state(task_root, text)["branches"])
        units = found["data"]["units"]
        return [dict(row, texts=[units[t]["text"] if t in units else _group_text(found["data"], t) for t in row["tokens"]
                                 if t in units or t in found["data"]["groups"]]) for row in found["excluded_rows"]]
    except Exception:  # noqa: BLE001
        return []


def _exclusions(root, plan, qmap, rounds) -> tuple:
    """`(role, person)`: `{branch: reason}` of the exclusions a role made, and `{branch: question id}` of the ones the person's
    CONFIRMED answer stands behind. A person's `decided_by` with no confirmed answer on the branch reads as the role's (spec 4.3)."""
    role, person = {}, {}
    homes = plan["doc"].get("branch_homes") if isinstance(plan["doc"], dict) else None
    for item in homes if isinstance(homes, list) else []:
        if not isinstance(item, dict) or item.get("home") != "excluded":
            continue
        bn, why = str(item.get("branch") or "").strip(), str(item.get("reason") or "").strip()
        qid = str(item.get("answer") or "").strip()
        if item.get("decided_by") == "person" and qid in qmap and _confirmed(qmap, qid) and _names_branch(qmap[qid], bn):
            person.setdefault(bn, qid)
        role.setdefault(bn, why)
    applied = []
    try:
        import planning_contract as PC
        applied = [r for r in PC._applied_records(root) if PC.plan_intent(r)]
    except Exception:
        pass
    for rid, row, names in plan["rows"]:
        if str(row.get("disposition") or "") not in PLAN_EXCLUDING:
            continue
        for bn in names:
            role.setdefault(bn, f"plan row {rid} is `{row.get('disposition')}`: {str(row.get('reason') or '').strip()}")
            for rec in applied:
                if rid in {str(x) for x in rec.get("rows") or []} and _confirmed(qmap, str(rec.get("id") or "")):
                    person.setdefault(bn, str(rec["id"]))
    for bn, entries in rounds.items():
        if entries and entries[0]["home"] == "excluded":
            role.setdefault(bn, entries[0]["reason"])
    return role, person


def _branch_records(root, text, branches, qmap) -> list:
    """The records of the register's branches and the branches read in existing tests (`BN-T<n>`), by the table of spec 3.3."""
    plan = _read_plan(root, text, branches, [], [])
    owed = plan["owed"] if plan else {r["bn"]: {"r": r["r"], "text": r["text"]} for r in branches["rows"] if BN_RE.fullmatch(r["bn"])}
    if not owed:
        return []
    manifest, cfg = _manifest(root)
    cases = _case_records(root) if plan else []
    by_id = {c["id"]: c for c in cases}
    carried: dict = {}
    for case in cases:
        for entry in case["entries"]:
            carried.setdefault(str(entry.get("id") or "").strip(), []).append((case["id"], C.then_number(entry.get("then")),
                                                                                  entry.get("partition")))
    rounds = _round_homes(root, owed, []) if plan else {}
    for bn, entries in rounds.items():         # a round's `home: TC-n` is a home when that case carries it or is reused (V-12)
        target = by_id.get(entries[0]["home"]) if entries else None
        if target and bn not in target["carried"] and target["reused"]:
            carried.setdefault(bn, []).append((target["id"], 0, None))
    role, person = _exclusions(root, plan, qmap, rounds) if plan else ({}, {})
    manual_cache: list = []

    def manual_passed(case) -> bool:
        if not manual_cache:
            try:
                import traceability as T
                manual_cache.append(T.Story(Path(root).parents[1], root))
            except Exception:
                manual_cache.append(None)
        story = manual_cache[0]
        try:
            return bool(story) and story.manual_outcome(case).get("result") == "pass"
        except Exception:
            return False

    out = []
    for bn, info in owed.items():
        reqs, said = [info["r"]], info["text"]
        if bn in person:
            out.append(_debt("branch_excluded_by_word", bn, reqs, said, f"excluded by your answer to {person[bn]}", question=person[bn]))
            continue
        homes = carried.get(bn, [])
        if any(_pair(manifest, cfg, case, then, part) == "covered" or (not part and manual_passed(case)) for case, then, part in homes):
            continue
        if bn in role:
            out.append(_debt("branch_excluded", bn, reqs, said, f"the role left it out, you have not said so: {role[bn] or 'no reason was given'}"))
        elif homes:
            carrying = list(dict.fromkeys(case for case, then, _part in homes if then >= 1))
            reused = [c for c in dict.fromkeys(case for case, then, _part in homes if then < 1) if c not in carrying]
            words = ([f"{', '.join(carrying)} carries it, but no test or recorded check proves it"] if carrying else []) + (
                [f"{', '.join(reused)} is a reused case: which Then proves it is not recorded"] if reused else [])
            out.append(_debt("branch_unproven", bn, reqs, said, "; ".join(words)))
        else:
            out.append(_debt("branch_lost", bn, reqs, said, "no case carries it and nobody left it out: nobody checked it"))
    return out


def _group_text(data, token) -> str:
    texts = [held["text"] for held in data["units"].values() if any(o["group"] == token for o in held["occ"])]
    return (texts[0] + (f" (and {len(texts) - 1} more sentences of the comment)" if len(texts) > 1 else "")) if texts else token


def _field_words(counts) -> str:
    words = ", ".join(f"{name} {counts.get(name, 0)}" for name in ("description", "criteria", "comments"))
    return words + (f", title {counts['title']}" if counts.get("title") else "")


def _unit_records(root, text, branches, qmap, out) -> list:
    """Spec 3.3 on the story's text and the kept tickets' text: a part with no home (or left in a `rest` row) is `source_unreconciled`
    (`ticket-text`, `ticket-text:<KEY>`, `linked-tickets`); a part with an `excluded:` home is `branch_excluded[_by_word]` by a
    confirmed answer named in the row; `not_obligation` is no debt but is COUNTED (`out["not_obligation"]`, the size line)."""
    found = reconcile(root, text, branches, qmap)
    data, cover = found["data"], found["cover"]
    history, scope, records = data["history"], data["scope"], {}
    out["left_out"] = list(scope["left_out"])
    out["not_obligation"] = [(len(units), row["reason"]) for row in found["free_rows"] for units in [_row_units(row["tokens"], data)] if units]
    named_key = lambda key: "ticket-text" if key == history["key"] else f"ticket-text:{key}"   # noqa: E731
    if history["state"] in ("absent", "unreadable", "no_unit"):
        why = {"absent": "the story's own text was not kept", "unreadable": "the story's own text cannot be read",
               "no_unit": "the story's own text has no readable part"}[history["state"]]
        records["ticket-text"] = _debt("source_unreconciled", "ticket-text", [], why, "read the ticket yourself: the factory could not account for its text")
    if not scope["known"]:
        records["linked-tickets"] = _debt("source_unreconciled", "linked-tickets", [], "which linked tickets were kept is not known",
                                          "check the linked tickets of the story for what they ask")
    for key, why in scope["not_read"]:
        records[named_key(key)] = _debt("source_unreconciled", named_key(key), [], f"the text of {key} was not read ({why})",
                                        f"read {key} yourself: it is in the scope of the story and nobody read it")
    for key, state in sorted(data["linked"].items()):
        if state["state"] in ("unreadable", "no_unit"):
            records[named_key(key)] = _debt("source_unreconciled", named_key(key), [], f"the text of {key} could not be read into parts",
                                            f"read {key} yourself")
    open_units: dict = {}
    for uid, held in data["units"].items():
        for occ in held["occ"]:
            if not cover.by_other(uid, occ):
                bucket = open_units.setdefault(occ["key"], {"fields": {}, "lines": []})
                bucket["fields"][occ["field"]] = bucket["fields"].get(occ["field"], 0) + 1
                bucket["lines"].append(held["text"])
    for key, bucket in open_units.items():
        number, label = len(bucket["lines"]), ("the ticket" if key == history["key"] else f"ticket {key}")
        records[named_key(key)] = _debt("source_unreconciled", named_key(key), [], f"{number} parts of {label} have no home ({_field_words(bucket['fields'])})",
                                        "read these parts and say whether each asks for something to check", lines=list(bucket["lines"]))
    result = list(records.values())
    for row in found["excluded_rows"]:
        by_word = row["decided"] and row["form"] in ("question", "quote")      # the person's confirmed answer, or their words QUOTED (E-11)
        qid = row["qid"]
        for token in row["tokens"]:
            if token not in data["units"] and token not in data["groups"]:
                continue
            said = data["units"][token]["text"] if token in data["units"] else _group_text(data, token)
            if by_word and row["form"] == "quote":
                result.append(_debt("branch_excluded_by_word", token, [], said, f'excluded by your words: "{row["quote"]}"',
                                    question="", quote=row["quote"], words_file=row["file"]))
            elif by_word:
                result.append(_debt("branch_excluded_by_word", token, [], said, f"excluded by your answer to {qid}", question=qid))
            else:
                result.append(_debt("branch_excluded", token, [], said, f"the role left it out, you have not said so: {row['reason']}"))
    return result


def _row_units(tokens, data) -> list:
    """The unit ids a `not_obligation:` row stands for (a unit or a comment; a `T-` token is refused, DD-4)."""
    ids = []
    for token in tokens:
        if token.startswith("G-"):
            ids += [uid for uid, held in data["units"].items() if any(o["group"] == token for o in held["occ"])]
        elif token in data["units"]:
            ids.append(token)
    return list(dict.fromkeys(ids))


def _walk_records(root) -> list:
    """An `existing_test_candidates` entry of the bundle that no `candidates_walked` entry names (spec 3.3): `source_unreconciled`,
    `test-candidates`; a bundle that cannot be read is ONE record; no bundle or none listed is none."""
    ids, why = _bundle_candidates(root)
    if ids is None:
        return [_debt("source_unreconciled", "test-candidates", [], f"the existing tests were not read ({why})", "check what the existing tests already prove")]
    if not ids:
        return []
    doc, _rows = _plan(root)
    walked = doc.get("candidates_walked") if isinstance(doc, dict) else None
    named = {str(c).strip() for item in (walked if isinstance(walked, list) else []) if isinstance(item, dict)
             for c in (item.get("candidates") if isinstance(item.get("candidates"), list) else [])}
    missing = [c for c in ids if c not in named]
    return [_debt("source_unreconciled", "test-candidates", [], f"{len(missing)} existing tests were not walked for branches",
                  "check what these tests already prove", lines=missing)] if missing else []


def _unseen_attachments(root) -> tuple:
    """`(unseen, unknown)` of the files nobody looked at (amendment 3.3, F-D6 (c)). `unseen`: `<KEY>: <name>` of a file the tester did
    not open (`attachments_view`: not `opened`, a row `not_opened`, a `rest` row, a reason of the listing) AND the person was not shown
    by name: plan gate A must have been reached (a current approved decision, `gate_brief.gate_a_decided`, THE reader) AND the
    packet must have named it (`state["shown_attachments"]["A_named"]`, read by `gate_brief.attachments_data`). No decision, or a
    record that is absent, unreadable, None or has no named list, shows nothing: every file not opened is unseen (what nobody saw
    does not pass; the error goes only toward a debt). A file shown and not opened is no debt: the person saw it and answered (FR-4).
    `unknown`: a line per ticket of the scope whose list of attachments is not known, while gate A was not reached (a ticket nobody
    read has its own debt, `ticket-text:<KEY>`, and is not repeated); with a decision it is silent, gate A said `not known` and the
    person answered. A data table that cannot be read raises `Unreadable` before a decision (after it, silent, for the same reason).
    A story with no inventory, or one that cannot be read, lists nothing here (`linked-tickets` and `ticket-text` speak)."""
    import gate_brief as GB
    data = GB.attachments_data(root)
    decided = GB.gate_a_decided(root) is True
    if data.get("state") == "unreadable" and data.get("cause") == "tables":
        if decided:
            return [], []
        raise Unreadable(data["reason"])
    if not data["known"]:
        return [], []
    shown = data["named"] if decided and isinstance(data["named"], list) else []
    unseen = [ident for ticket in data["tickets"] for item in ticket["items"] if not item["opened"]
              for ident in GB.attachment_ids({"tickets": [{"key": ticket["key"], "items": [item]}]}) if ident not in shown]
    unknown = [] if decided else [f"{t['key']}: the list of attachments is not known ({t['reason']})" for t in data["tickets"]
                                  if not t["known"] and t.get("scope") != "unread"]
    return unseen, unknown


def _attachment_records(root, text, qmap) -> list:
    """A `## Attachments` row `contradicts` whose question the person has not settled (or that names none): `attachment_question_open`
    (F-A5); and ONE `source_unreconciled` row `attachments-unseen` for the files nobody looked at (`_unseen_attachments`, F-2)."""
    body = _section(text, ATTACHMENTS_HEADING)
    rows, bad_header = _table_rows(body, ATTACHMENT_COLUMNS) if body is not None else ([], "")
    out = []
    import question_register as QR
    for cells in [] if bad_header else rows:
        name, _ticket, reading, r, qid, _why = (C.strip_cell(c) for c in cells)
        if reading != "contradicts" or (qid in qmap and QR.settled(qmap[qid])):
            continue
        out.append(_debt("attachment_question_open", f"attachment:{attachment_name(name)}", [r], f"{r} against {attachment_name(name)}",
                         "the file and the requirement disagree; nobody has said which is right"))
    unseen, unknown = _unseen_attachments(root)
    if unseen or unknown:
        said = ([f"{len(unseen)} attachments were not opened and were not shown to you"] if unseen else []) + (
            [f"the attachments of {len(unknown)} tickets could not be listed and the plan gate was not reached"] if unknown else [])
        out.append(_debt("source_unreconciled", "attachments-unseen", [], " and ".join(said),
                         "open them and say whether any of them holds a requirement", lines=unseen + unknown))
    return out


def account(art) -> dict:
    """`{"state", "records", "not_obligation": [(parts, reason)], "left_out": [(KEY, why)]}` of one story. `legacy` and a story with
    no register read `[]`; an unreadable register, plan or snapshot raises `Unreadable` (the caller makes one `branches_unreadable`)."""
    root, out = Path(art), {"state": "", "records": [], "not_obligation": [], "left_out": []}
    text = _read_register(root)
    if text is None:
        out["state"] = "no_register"
        return out
    state = branch_state(root, text)
    out["state"] = state["state"]
    if state["state"] == "unreadable":
        raise Unreadable(state["reason"])
    if state["state"] == "legacy":
        return out
    if state["state"] == "missing":
        out["records"].append(_debt("branches_not_recorded", "branches", [], "the register has no record of the story's branches",
                                    state["reason"] or "the register written for this story carries no `## Branches` section: check what the story's qualifiers, partitions and refusals ask"))
        return out
    qmap = _questions(root)
    out["records"] += _branch_records(root, text, state["branches"], qmap)
    out["records"] += _unit_records(root, text, state["branches"], qmap, out)
    out["records"] += _walk_records(root)
    out["records"] += _attachment_records(root, text, qmap)
    return out


def delivery_records(art) -> list:
    """The records `check_delivery.assess` adds (spec 3.2): `{text:"", kind, case:"", ref, item_key, requirements, to_check, how,
    source:"branches"}` (+ `lines`, `question`). Raises `Unreadable` when it cannot read what it must."""
    return account(art)["records"]


def branch_debts(items) -> dict:
    """`{R-n: [words]}` of the `left_items` that are a debt of a branch or of a file (`source: branches`): the requirement is not
    proven while one stands (`report_facts._requirements`, F-4b). The words name the branch."""
    out: dict = {}
    for item in items or []:
        if not isinstance(item, dict) or item.get("source") != SOURCE_KIND:
            continue
        for r in item.get("requirements") or []:
            out.setdefault(r, []).append(f"{item.get('ref')}")
    return out


def _page(lines: list, page: int) -> list:
    size = limit("units_page")
    pages = max(1, -(-len(lines) // size))
    page = min(max(page, 1), pages)
    out = lines[(page - 1) * size: page * size]
    out.append(f"page {page} of {pages}" + (f"; next: --page {page + 1}" if page < pages else ""))
    return out


def list_units(task_root, *, unhomed: bool, page: int) -> list:
    text = _read_register(task_root)
    if unhomed:
        state = branch_state(task_root, text)
        found = reconcile(task_root, text or "", state.get("branches"))
        rows = [unit_line(u, h, w) for u, h, w in found["unhomed"]]
    else:
        rows = [unit_line(u, h) for u, h in collect(task_root)["units"].items()]
    return _page(rows, page)


def list_attachments(task_root, *, page: int) -> list:
    """`--attachments`: a header line above page 1, then the files 200 to a page (`units_page`), as `--units` pages."""
    rows = attachment_lines(task_root)
    if rows and rows[0].startswith("attachments not known"):
        return rows
    head = [f"files (ticket | name | the scout's line | the call that opens it); a row of `{ATTACHMENTS_HEADING}` owes each one that has a call:"]
    return (head if page <= 1 else []) + _page(rows, page)


def main() -> int:
    try:
        import console_io
        console_io.utf8_stdio()
    except ImportError:
        pass
    ap = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    ap.add_argument("--units", action="store_true", help="every unit of the story's text, 200 to a page")
    ap.add_argument("--unhomed", action="store_true", help="the units with no home yet")
    ap.add_argument("--attachments", action="store_true", help="the files of the story and its kept tickets, with the call that opens each")
    ap.add_argument("--page", type=int, default=1)
    ap.add_argument("--task", default=None)
    ap.add_argument("--task-root", dest="task_root", default=None)
    ap.add_argument("--project-root", dest="project_root", default=None)
    ap.add_argument("--root", default=None, help="project root; detector mode only, for tests")
    args = hooklib.exact_options(ap).parse_args()
    if not (args.units or args.unhomed or args.attachments):
        return detector_main(args.root)        # no flag: the exit-gate hook's mode
    project = Path(args.project_root) if args.project_root else None
    task_root = hooklib.story_cli("branch_accounting.py", key=args.task, root=args.task_root, project=project)
    try:
        if args.units or args.unhomed:
            for line in list_units(task_root, unhomed=args.unhomed, page=args.page):
                print(line)
        if args.attachments:
            for line in list_attachments(task_root, page=args.page):
                print(line)
    except Unreadable as exc:
        print(DV.unreadable_line(str(exc)))
        return DV.EXIT_UNREADABLE
    return 0


if __name__ == "__main__":
    sys.exit(main())
