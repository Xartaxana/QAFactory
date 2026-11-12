"""The grounding table by code (G1-4, grounding/1): `work/grounding.yaml` is prepared, carried over and checked here.

  grounding_table.py --skeleton --task T          write the table: every hunk of the recorded diff in an empty row, every
                                                  requirement of the register in an empty line (the role fills the labels)
  grounding_table.py --refresh  --task T [--force] carry the role's marks to a new diff by the bytes they marked; what cannot
                                                  be carried is KEPT in `orphans[]`, never dropped (`--force` rewrites a table
                                                  the reader refuses: its old bytes stay beside the new table as
                                                  `grounding.unreadable-<sha8>.yaml` and ONE orphan points at them)
  grounding_table.py --check    --task T          the completeness check (R0..R5, R8) in detector form 1; writes NOTHING
  grounding_table.py --share    --task T          the refactoring share (G2-1): writes the ONE key `refactoring_share` of a readable
                                                  table in the world `diff`; a measure, not a detector (exit 0, no REJECT)

Exit codes: 0 done / no findings, 1 findings (form 1 on stdout), 2 a refused call (stderr, nothing written), 3 no such project or
story (`hooklib.story_root`, the shared contract of every script that takes `--task`).

The library (`check`, `check_report`, `source_state`, `write_yaml`, `write_key`, `dump_yaml`, `parse_list`, `expand_hunk_refs`) is
what the S3 gate and the window preparation call in-process: ONE function per fact, ONE YAML writer (`write_yaml`; `write_key`
goes through it), ONE reader (`planning_contract.read_grounding`). The role never runs this script: its refusals name the field
the role fills, or whoever acts (the driver, S1, the conductor).

Hunk ids: the first 12 hex of sha256(repo, file, the hunk's `body` lines from the diff index, markers included), then `-<n>`, the
occurrence among equal bodies; two different bodies that share 12 hex both grow to 16, 20, ... A hunk with no `body` in the index
is refused (never a hash of `lines`). A label moves to a new diff only with the same `(sha256, occurrence)` (I2).
"""
import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from collections import Counter, namedtuple
from pathlib import Path, PurePosixPath
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))
import contract as C  # noqa: E402
import detector_verdict as DV  # noqa: E402
import diff_pass as DP  # noqa: E402
import handoff as H  # noqa: E402
import handoff_check as HC  # noqa: E402
import hooklib  # noqa: E402
import planning_contract as PC  # noqa: E402
import test_files as TF  # noqa: E402

Finding = namedtuple("Finding", "rule text who")
TAIL = "A person's word passes this check (FR-4)."
REASON_LIMIT = 160
QUESTION_LIMIT = 300
MATTERS = ("yes", "no", "")
ROADS = ("none", "notify", "stop", "unknown")
PATH_KINDS = ("additive", "shared_path", "not_applicable", "", "unmeasured")
PLAIN_PATH_KINDS = ("additive", "not_applicable")
ORPHAN_WHY = ("hunk_gone", "requirement_gone", "area_changed", "source_changed", "requirement_changed", "table_unreadable")
ROLE_AREA_FIELDS = ("matters", "why", "regression", "add_tests", "text_says")
BLAST_FILE = "blast-radius.json"
WHERE_ROWS = 'rows with label "" in work/grounding.yaml'
COMMIT_RE = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")
ID_NUM = re.compile(r"^[A-Z]-(\d+)$")
LONE_SURROGATE = re.compile("[" + chr(0xD800) + "-" + chr(0xDFFF) + "]")      # not in the reader's set; a UTF-8 file cannot hold one
REPLACEMENT = chr(0xFFFD)                                                        # what the diff reader writes for a byte it cannot decode
R5_FIX = ("nothing for you to edit: the driver's S3 window preparation refreshes the table (labels of unchanged hunks are kept, "
          "changed and new hunks get empty rows, the rest is listed as orphaned).")
FORCE_FACTS = ("the old bytes are kept beside the new table as work/grounding.unreadable-<sha8>.yaml and ONE orphan "
               "(was: table, why_orphan: table_unreadable) points at them")


class Refusal(Exception):
    """A refused call (exit 2): `.text` says what is wrong, what is expected and what to do (FR-1)."""

    def __init__(self, text):
        super().__init__(text)
        self.text = text


def _text_sha(text: str) -> str:
    """sha256 of a text as UTF-8 (`surrogatepass`: a lone surrogate is hashed, not refused)."""
    return hashlib.sha256(text.encode("utf-8", "surrogatepass")).hexdigest()


def _digest(text: str) -> str:
    """THE hash of a hunk (id and `sha256` both): one name, so a test can force a short common prefix."""
    return _text_sha(text)


def _sentence(text) -> str:
    """`text` as one sentence with exactly one final period (a refusal ends with a period, FR-1)."""
    return str(text).strip().rstrip(".") + "."


def table_path(root) -> Path:
    return C.artifact_write_path(Path(root), "grounding.yaml")


# --- the ONE writer of work/grounding.yaml -----------------------------------------------------------------------------------

def _escape(match) -> str:
    return "\\u%04x" % ord(match.group())


def _quote(text: str) -> str:
    """A double-quoted scalar the table reader reads back as `text`: JSON, with every character the READER refuses raw
    (`PC._GROUNDING_CONTROL`: the C0/C1 controls, U+2028/9 - ONE set, imported, never copied) escaped, and the lone surrogates a
    UTF-8 file cannot hold (`json.dumps` leaves all of these raw)."""
    return LONE_SURROGATE.sub(_escape, PC._GROUNDING_CONTROL.sub(_escape, json.dumps(text, ensure_ascii=False)))


def _scalar_text(value) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    return _quote(value if isinstance(value, str) else str(value))      # a float is text in this table (the reader keeps it so)


def _key_text(key) -> str:
    key = str(key)
    return key if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_\-]*", key) else _quote(key)


def _inline(item) -> str:
    return "{}" if isinstance(item, dict) else "[]" if isinstance(item, list) else _scalar_text(item)


def _dump_into(out: list, value, indent: int, lead: str, path: str = "") -> None:
    """Block style, one key per line; a flow `[]` / `{}` only when empty. `lead` is what stands before the first line of a map in a
    list item (`- `). Never a flow map with content and never a value on the next line: `handoff.parse` drops both. `path` names
    the node for a refusal (a `TypeError` that says WHERE: `rows[3].hunks[0]`)."""
    pad = " " * indent
    if isinstance(value, dict):
        first = True
        for key, item in value.items():
            head = (lead if first and lead else pad) + f"{_key_text(key)}:"
            first = False
            if isinstance(item, (dict, list)) and item:
                out.append(head)
                _dump_into(out, item, indent + 2, "", f"{path}.{key}" if path else str(key))
            else:
                out.append(head + " " + _inline(item))
    elif isinstance(value, list):
        for n, item in enumerate(value):
            if isinstance(item, dict) and item:
                _dump_into(out, item, indent + 2, pad + "- ", f"{path}[{n}]")
            elif isinstance(item, list) and item:
                raise TypeError(f"`{path}[{n}]` is a list inside a list, which the table's subset cannot hold")
            else:
                out.append(f"{pad}- " + _inline(item))
    else:
        raise TypeError(f"`{path or '(top)'}` must be a mapping or a list, not {type(value).__name__}")


def dump_yaml(data: dict) -> str:
    """The text of `data` in the table's subset. A node it cannot write raises `TypeError` that names the node's path."""
    if not isinstance(data, dict):
        raise TypeError(f"the top of the table must be a mapping, not {type(data).__name__}")
    out: list = []
    _dump_into(out, data, 0, "")
    return "\n".join(out) + "\n"


def write_yaml(path, data: dict) -> None:
    """THE writer of the table: the whole text in a temp file beside the target, then `os.replace` (a crash leaves the old file or
    the new one, never half). An OSError removes the temp file and leaves the old file as it was; the caller reads it as a refusal."""
    path = Path(path)
    text = dump_yaml(data)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".grounding-", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(text.encode("utf-8"))
        os.replace(tmp, path)
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def write_key(target, key: str, value) -> None:
    """Write ONE top-level key of an existing table (`target`: the story root, or the table's own `work/grounding.yaml`): the table
    is read by the one reader, the key set, and the whole table goes out through `write_yaml` - there is no second emitter. A
    table the reader refuses, or a key the reader would refuse next time, is a `Refusal` and nothing is written."""
    root = Path(target)
    if not root.is_dir():
        root = root.parent.parent
    try:
        path = table_path(root)
    except (ValueError, OSError):
        path = None
    if path is None or (not Path(target).is_dir() and Path(target).resolve() != path.resolve()):
        raise Refusal(f"grounding_table: {target} is neither a story root nor the table of one. Expected: the story's artifact folder "
                      "or its work/grounding.yaml. Do: pass one of those; nothing was written.")
    if key not in PC.GROUNDING_KEYS:
        raise Refusal(f"grounding_table: `{key}` is not a key of the table (expected one of {', '.join(PC.GROUNDING_KEYS)}). "
                      "Expected: a key the table reader accepts. Do: write one of those keys; nothing was written.")
    doc, problem = PC.read_grounding(root)
    if doc is None:
        raise Refusal(f"grounding_table: cannot write `{key}`: {_sentence(problem)} Expected: the readable table the S3 window "
                      "preparation writes before any key is added. Do: the driver writes the table first "
                      "(grounding_table.py --refresh); nothing was written.")
    data = dict(doc.data)
    data[key] = value
    write_yaml(path, data)


def parse_list(text, name: str = "value") -> list:
    """The items of an `"a,b"` value (the `old` / `new` start,count of a hunk, a comma list a role or a reader writes) as stripped
    strings: spaces around commas are fine, `None` and `""` are `[]`. An empty item (`","`, `"a,,b"`, `"a,"`) is a `Refusal`
    that names `name` - never `['']`, because a list with a hidden empty item reads as one thing that is nothing."""
    if text is None:
        return []
    if not isinstance(text, str):
        raise Refusal(f"grounding_table: `{name}` is {type(text).__name__} {text!r}, not text. Expected: a comma list like "
                      "\"10,3\". Do: write the value as text; nothing was read.")
    if not text.strip():
        return []
    items = [part.strip() for part in text.split(",")]
    if not all(items):
        raise Refusal(f"grounding_table: `{name}` is {text!r}, a comma list with an empty item. Expected: items separated by "
                      "commas, like \"10,3\", or an empty value for none. Do: write every item; nothing was read.")
    return items


# --- facts read from the story -----------------------------------------------------------------------------------------------

def pipeline_word(root):
    pipe = hooklib.read_json(Path(root) / "pipeline.json", None, kind=dict)
    return pipe.get("implementation_source") if pipe else None


def diff_files(root) -> list:
    return [p for p in hooklib.sorted_paths((Path(root) / "work").glob("impl-diff*.txt")) if p.is_file()]


def source_state(root) -> tuple:
    """`(world, text)`: `diff`; `off_diff:<word>` (a recorded source other than `diff`, or `absent` when there is no record and no
    diff - the declared default); `mismatch` (a source that is not `diff` while a diff is on disk, or a word nobody lists; `text`
    says what and who acts). ONE function: the gate and the check both ask it."""
    word = pipeline_word(root)
    files = diff_files(root)
    if word == "diff":
        return "diff", ""
    listed = H.allowed("implementation_sources")
    if files:
        names = ", ".join(p.name for p in files)
        return "mismatch", (f"S1 recorded implementation_source {word if isinstance(word, str) and word else 'none'} while "
                            f"{names} {'is' if len(files) == 1 else 'are'} on disk")
    if isinstance(word, str) and word in listed:
        return f"off_diff:{word}", ""
    if word is None or word == "":
        return "off_diff:absent", "no implementation_source is recorded and no implementation diff is on disk (the declared default: nothing to label)"
    return "mismatch", f"S1 recorded implementation_source {word!r}, which is none of {', '.join(listed)}"


def manifest_entry_for(name: str, entries: list) -> tuple:
    """`(entry, "")` or `(None, reason)`: the manifest entry that names the diff `name` - by the basename of its `diff_path`, else
    (an `impl-diff-<x>.txt`) by `repo_id or repo` = x. Entries are read only through `HC.implementation_entries`. No third guess."""
    named = [e for e in entries if isinstance(e, dict) and isinstance(e.get("diff_path"), str)
             and PurePosixPath(e["diff_path"].replace("\\", "/")).name == name]
    if not named and name.startswith("impl-diff-") and name.endswith(".txt"):
        suffix = name[len("impl-diff-"):-len(".txt")]
        named = [e for e in entries if isinstance(e, dict) and str(e.get("repo_id") or e.get("repo") or "").strip() == suffix]
    if len(named) == 1:
        return named[0], ""
    return None, (f"no manifest entry for {name}" if not named else f"{len(named)} manifest entries name {name}")


def commit_value(entry: dict, name: str) -> str:
    who = str(entry.get("repo_id") or entry.get("repo") or name).strip() or name
    sha = entry.get("source_sha")
    if sha is None or not str(sha).strip():
        return f"unmeasured: no source_sha for repo {who}"
    return sha if isinstance(sha, str) and COMMIT_RE.fullmatch(sha) else f"unmeasured: source_sha '{sha}' is not a commit id"


def diff_records(root) -> list:
    """`diff[]`: one record per `work/impl-diff*.txt`, joined to the context manifest through `HC.implementation_entries`."""
    manifest = hooklib.read_json(Path(root) / "work" / "context-manifest.json", None, kind=dict)
    entries = HC.implementation_entries(manifest) if manifest is not None else []
    out = []
    for path in diff_files(root):
        stem = path.name[:-len(".txt")] if path.name.endswith(".txt") else path.name
        repo = stem[len("impl-diff"):].lstrip("-")
        entry, why = manifest_entry_for(path.name, entries)
        out.append({"path": f"work/{path.name}", "repo": repo,
                    "repo_id": str(entry.get("repo_id") or entry.get("repo") or "") if entry else "",
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "implementation_commit": commit_value(entry, path.name) if entry else f"unmeasured: {why}"})
    return out


def register_info(root) -> SimpleNamespace:
    """The register as the table needs it: ids, the implementation-only ids, a digest of each statement cell, the first cells of
    rows the id reader would silently drop. `ok` False + `why` when there is nothing to read."""
    info = SimpleNamespace(ok=False, why="", ids=[], exempt=[], statements={}, texts={}, unread=[], sha256="", path=None)
    try:
        path = C.artifact(Path(root), "requirements-register.md")
    except ValueError as exc:
        info.why = str(exc)
        return info
    if not path.is_file():
        info.why = "work/requirements-register.md does not exist"
        return info
    info.path, raw = path, path.read_bytes()
    info.sha256, text = hashlib.sha256(raw).hexdigest(), raw.decode("utf-8", "replace")
    table = C.md_table(text, "## Register")
    if not table:
        info.why = "work/requirements-register.md holds no `## Register` table"
        return info
    header = [C.strip_cell(c).lower() for c in table[0]]
    col = next((i for i, h in enumerate(header) if h.startswith("requirement")), 1)
    for cells in table[1:]:
        first = C.strip_cell(cells[0]) if cells else ""
        if not C.REQ_ID_RE.fullmatch(first):
            if any(C.strip_cell(c) for c in cells):
                info.unread.append(first or "(empty first cell)")
            continue
        statement = " ".join(str(cells[col]).split()) if col < len(cells) else ""
        info.statements.setdefault(first, _text_sha(statement))
        info.texts.setdefault(first, statement)
    info.ids, info.exempt, info.ok = C.register_ids(path), C.implementation_only(text), True
    return info


# --- the hunks ---------------------------------------------------------------------------------------------------------------

def hunk_text(repo: str, file: str, hunk: dict):
    """The text a hunk is hashed by: repo, file, `pseudo:<kind>` for a pseudo-hunk, and the `body` lines as the index gave them
    (context and `\\ No newline` markers included). None when the index carries no `body` (the caller refuses: no hash by `lines`)."""
    body = hunk.get("body")
    if not isinstance(body, list) or not all(isinstance(x, str) for x in body):
        return None
    head = f"pseudo:{hunk['pseudo']}\n" if hunk.get("pseudo") else ""
    return repo + "\n" + file + "\n" + head + "\n".join(body)


def assign_ids(shas: list) -> list:
    """The ids of hunks with these full digests, in order: `<prefix>-<occurrence>`; the prefix is the shortest of 12, 16, 20 ... hex
    that no OTHER distinct digest shares."""
    uniq = list(dict.fromkeys(shas))
    width = {}
    for n in range(12, 65, 4):
        counts = Counter(s[:n] for s in uniq)
        for s in uniq:
            if s not in width and (counts[s[:n]] == 1 or n == 64):
                width[s] = n
    seen: Counter = Counter()
    out = []
    for s in shas:
        seen[s] += 1
        out.append(f"{s[:width[s]]}-{seen[s]}")
    return out


def index_hunks(root) -> tuple:
    """`(hunks, refusals, no_body)`: the hunks of every recorded diff with their table records, recomputed from disk. A hunk
    record is a SimpleNamespace(rec, diff, old_start, new_start)."""
    found = DP.index(Path(root) / "work")
    raw, no_body = [], False
    for f in found["files"]:
        for h in f["hunks"]:
            text = hunk_text(f["repo"], f["path"], h)
            if text is None:
                no_body = True
                continue
            raw.append((f, h, _digest(text)))
    if no_body:
        return [], found["refusals"], True
    hunks, kinds = [], {}
    for pos, (f, h, sha), ident in zip(range(1, len(raw) + 1), raw, assign_ids([r[2] for r in raw])):
        lines = h.get("lines") or []
        if f["path"] not in kinds:                           # file_kind costs ~10 ms a call: once per file, not per hunk
            kinds[f["path"]] = TF.file_kind(f["path"])
        rec = {"id": ident, "short": f"H-{pos}", "repo": f["repo"], "file": f["path"], "kind": kinds[f["path"]],
               "old": f"{h.get('old_start', 0)},{h.get('old_count', 0)}", "new": f"{h['new_start']},{h.get('new_count', 0)}",
               "function": h.get("header", ""), "added": sum(1 for x in lines if x[1] == "+"),
               "removed": sum(1 for x in lines if x[1] == "-"), "sha256": sha, "pseudo": h.get("pseudo", "")}
        hunks.append(SimpleNamespace(rec=rec, diff=f["diff"], old_start=h.get("old_start", 0), new_start=h["new_start"],
                                     replaced=any(REPLACEMENT in line for line in h["body"])))
    return hunks, found["refusals"], False


def parse_all_ref(ref: str):
    """`(repo, file)` of `all:<repo>:<file>` (the repo may be empty: `all::<file>`), else None."""
    if not isinstance(ref, str) or not ref.startswith("all:"):
        return None
    repo, _, file = ref[4:].partition(":")
    return repo, file


def hunk_index(hunks: list) -> SimpleNamespace:
    """The lookup `expand_hunk_refs` needs, built ONCE for a list of hunk records (a caller that expands many rows builds it once:
    10 000 rows against 10 000 hunks must not rebuild it 10 000 times)."""
    by_id, by_file = set(), {}
    for h in hunks:
        if isinstance(h, dict) and isinstance(h.get("id"), str):
            by_id.add(h["id"])
            by_file.setdefault((h.get("repo", ""), h.get("file", "")), []).append(h["id"])
    return SimpleNamespace(by_id=by_id, by_file=by_file)


def expand_hunk_refs(refs, hunks) -> tuple:
    """`(ids, dangling)` of a `hunks` value (an id, an `all:<repo>:<file>`, or a list of them) against `hunks` (a list of table
    records, or the `hunk_index` of one). An id in no record, an `all:` of a file no record has, and an item that is not text, are
    dangling (verbatim). THE expander of a `hunks` value: the completeness check, the references check and the refresh all read a
    `hunks` value through it."""
    items = [refs] if isinstance(refs, str) else (refs if isinstance(refs, list) else [])
    index = hunks if isinstance(hunks, SimpleNamespace) else hunk_index(hunks)
    ids, seen, dangling = [], set(), []
    for item in items:
        whole = parse_all_ref(item)
        found = index.by_file.get(whole, []) if whole else ([item] if isinstance(item, str) and item in index.by_id else [])
        if not found:
            dangling.append(str(item))
        ids += [i for i in found if i not in seen and not seen.add(i)]
    return ids, dangling


# --- the skeleton ------------------------------------------------------------------------------------------------------------

def gather(root) -> SimpleNamespace:
    root = Path(root)
    world, why = source_state(root)
    word = pipeline_word(root)
    inp = SimpleNamespace(root=root, world=world, why=why, word=word if isinstance(word, str) else "", diffs=[], hunks=[],
                          refusals=[], no_body=False, register=register_info(root))
    if world == "diff":
        inp.diffs = diff_records(root)
        inp.hunks, inp.refusals, inp.no_body = index_hunks(root)
    return inp


def project_blast(inp) -> dict:
    """`blast_radius` from `work/blast-radius.json` - THE source of the index state and of the code part of every area, for the
    skeleton and for `--check` alike (the table's own copy is never believed): the index state, the areas with their hunk positions
    turned into hunk ids by `(diff, area file, old_start, new_start)` - the FILE is part of the key: two new files both start at
    `(0, 1)`, and on 13877 ten of them shared one position. No file: `{index: {state: absent}}`; a file that is not a mapping or
    holds no `areas` list: `{index: {state: unreadable}}` - neither carries `areas` (a missing index is not an empty one). An area
    position or a diff digest that no longer matches marks the index `stale` (R8: the driver rebuilds) - a position is never
    dropped silently."""
    path = inp.root / "work" / BLAST_FILE
    if not path.is_file():
        return {"index": {"state": "absent"}}
    src = hooklib.read_json(path, None, kind=dict)
    if src is None or not isinstance(src.get("areas"), list):
        return {"index": {"state": "unreadable"}}
    index = dict(src.get("index") if isinstance(src.get("index"), dict) else {})
    index.setdefault("state", "built")
    at = {(h.diff, h.rec["file"], h.old_start, h.new_start): h.rec["id"] for h in inp.hunks}
    stale = False
    disk = {Path(d["path"]).name: d["sha256"] for d in inp.diffs}
    for d in index.get("diffs") or []:
        if isinstance(d, dict) and disk.get(Path(str(d.get("path", ""))).name) != d.get("sha256"):
            stale = True
    areas = []
    for area in src["areas"]:
        if not isinstance(area, dict):
            continue
        area = json.loads(json.dumps(area))
        touched = area.get("touched") if isinstance(area.get("touched"), dict) else {}
        ids = []
        for pos in touched.get("hunks") or []:
            ident = (at.get((pos.get("diff"), touched.get("file"), pos.get("old_start"), pos.get("new_start")))
                     if isinstance(pos, dict) else None)
            if ident is None:
                stale = True
            else:
                ids.append(ident)
        area["touched"] = dict(touched, hunks=ids)
        for field in ROLE_AREA_FIELDS:
            area.setdefault(field, "")
        areas.append(area)
    if stale:
        index["state"] = "stale"
    return {"index": index, "areas": areas}


def empty_row(number: int, hunk_ids: list) -> dict:
    return {"id": f"G-{number}", "hunks": list(hunk_ids), "label": "", "requirements": [], "risks": [], "question": "", "reason": ""}


def empty_line(r: str, text_sha: str) -> dict:
    return {"r": r, "state": "", "hunks": [], "where": "", "question": "", "text_sha256": text_sha}


def skeleton(inp) -> dict:
    """The table of a story whose source is `diff`: one empty row per hunk, one empty line per requirement of the register that
    is not implementation-only. Refuses (Refusal) a diff index that carries no hunk body."""
    if inp.no_body:
        raise Refusal("grounding_table: the diff index carries no hunk bodies (a hunk has no `body`), so no hunk can be identified. "
                      "Expected: diff_pass.index giving every hunk its body. Do: this is the factory's own defect - the conductor "
                      "reports it; nothing was written.")
    reg = inp.register
    table = {"schema_version": PC.GROUNDING_SCHEMA_VERSION, "implementation_source": "diff",
             "register_sha256": reg.sha256 or f"unmeasured: {reg.why}",
             "diff": inp.diffs, "hunks": [h.rec for h in inp.hunks],
             "rows": [empty_row(i, [h.rec["id"]]) for i, h in enumerate(inp.hunks, 1)],
             "requirements": [empty_line(r, reg.statements.get(r, "")) for r in reg.ids if r not in reg.exempt]}
    blast = project_blast(inp)
    if blast["index"]["state"] != "absent":                      # no index file: no `blast_radius` key (t-1046 seam 3); R8 says so
        table["blast_radius"] = blast
    return table


def null_table(inp) -> dict:
    """The table of a story with no diff: `{schema_version, implementation_source, null_outcome: {source, words}}`."""
    source = inp.world.split(":", 1)[1]
    policy, why = PC.grounding_policy()
    words = policy.get("null_outcome_words") if policy else None
    text = words.get(source) if isinstance(words, dict) else None
    if not isinstance(text, str) or not text.strip():
        raise Refusal("grounding_table: the words of the null outcome cannot be read" + (f" ({why})" if why else "")
                      + f". Expected: references/grounding-policy.json with `null_outcome_words` holding a sentence for `{source}`. "
                      "Do: restore that data file; nothing was written.")
    return {"schema_version": PC.GROUNDING_SCHEMA_VERSION, "implementation_source": "" if source == "absent" else source,
            "null_outcome": {"source": source, "words": text}}


def _refuse_call(inp) -> None:
    if inp.world == "mismatch":
        raise Refusal(f"grounding_table: {inp.why}. Expected: implementation_source `diff` when a diff is on disk, and a diff "
                      "only when the source is `diff`. Do: S1 records the source again (the orchestrator sets it with stage_done "
                      "--set implementation_source=...); nothing was written.")


# --- --refresh: carry the marks, keep the rest -------------------------------------------------------------------------------

def _max_number(prefix: str, *groups) -> int:
    top = 0
    for group in groups:
        for item in group or []:
            m = ID_NUM.match(str(item.get("id", ""))) if isinstance(item, dict) else None
            if m and m.group(0).startswith(prefix):
                top = max(top, int(m.group(1)))
    return top


def _is_empty(rec: dict, fields) -> bool:
    return all(rec.get(f) in ("", None, [], {}) for f in fields)


def _diff_sha(old: dict, old_ids: list) -> str:
    by_repo = {d.get("repo", ""): d.get("sha256", "") for d in old.get("diff") or [] if isinstance(d, dict)}
    by_id = {h.get("id"): h for h in old.get("hunks") or [] if isinstance(h, dict)}
    return ",".join(sorted({by_repo.get(by_id[i].get("repo", ""), "") for i in old_ids if i in by_id} - {""}))


def make_orphan(was: str, rec: dict, why: str, hunks: list, diff_sha: str) -> dict:
    """An `orphans[]` record: the line or area verbatim in flat fields, the reason in `why_orphan` (never `why`, the area's own).
    The reason is one of the closed list `ORPHAN_WHY`; any other word is the writer's defect, so it stops here."""
    if why not in ORPHAN_WHY:
        raise ValueError(f"the orphan reason {why!r} is none of {', '.join(ORPHAN_WHY)}")
    return {"was": was, "id": str(rec.get("id", rec.get("r", ""))), "why_orphan": why,
            "label": rec.get("label", ""), "requirements": list(rec.get("requirements") or []), "risks": rec.get("risks") or [],
            "question": rec.get("question", ""), "reason": rec.get("reason", ""), "hunks": list(hunks), "diff_sha": diff_sha,
            "state": rec.get("state", ""), "where": rec.get("where", ""),
            **{f: rec.get(f, "") for f in ROLE_AREA_FIELDS}}


def _carry_ids(refs, old_hunks: list, mapping: dict) -> tuple:
    """`(new ids, gone refs, ids before)` of a `hunks` value: old ids mapped by `(sha256, occurrence)`; what has no image is gone."""
    ids, dangling = expand_hunk_refs(refs, old_hunks)
    return [mapping[i] for i in ids if i in mapping], [i for i in ids if i not in mapping] + dangling, ids


def refresh_table(old: dict, inp) -> tuple:
    """`(new table, report lines)` for an `old` table (the data of a readable one) over the recomputed `inp`."""
    new = skeleton(inp)
    old_hunks = [h for h in old.get("hunks") or [] if isinstance(h, dict)]
    new_by = {}
    seen: Counter = Counter()
    replaced = {h.rec["id"] for h in inp.hunks if h.replaced}        # a U+FFFD body: two byte strings read alike, so no label moves
    for h in new["hunks"]:
        seen[h["sha256"]] += 1
        if h["id"] not in replaced:
            new_by[(h["sha256"], seen[h["sha256"]])] = h["id"]
    mapping, seen = {}, Counter()
    for h in old_hunks:
        seen[h.get("sha256")] += 1
        if (h.get("sha256"), seen[h.get("sha256")]) in new_by and h.get("id") is not None:
            mapping[h["id"]] = new_by[(h.get("sha256"), seen[h.get("sha256")])]
    orphans = list(old.get("orphans") or [])
    fresh: list = []
    report: list = []
    sha_of = lambda ids: _diff_sha(old, ids)                                              # noqa: E731
    rows, used = [], set()
    for row in old.get("rows") or []:
        if not isinstance(row, dict):
            rows.append(row)
            continue
        mapped, gone, before = _carry_ids(row.get("hunks"), old_hunks, mapping)
        if not before and not gone:
            rows.append(row)
            continue
        if not mapped:
            if _is_empty(row, ("label", "requirements", "risks", "question", "reason")):
                report.append(f"row {row.get('id')}: empty, its hunks left the diff - dropped")
            else:
                fresh.append(make_orphan("row", row, "hunk_gone", gone, sha_of(before)))
                report.append(f"row {row.get('id')}: all its hunks left the diff - kept in orphans (hunk_gone)")
            continue
        if gone:
            fresh.append(make_orphan("row", row, "hunk_gone", gone, sha_of(before)))
            report.append(f"row {row.get('id')}: {len(gone)} of its hunks left the diff - kept in orphans (hunk_gone)")
        whole = parse_all_ref(row.get("hunks"))
        file_new = [h["id"] for h in new["hunks"] if whole and (h["repo"], h["file"]) == whole]
        keep_whole = whole and not gone and sorted(file_new) == sorted(mapped)
        rows.append(dict(row, hunks=row["hunks"] if keep_whole else mapped))
        used.update(mapped)
    top = _max_number("G-", old.get("rows"), rows, orphans, fresh)        # every id ever issued here, a dropped empty row's included
    added = 0
    for h in new["hunks"]:
        if h["id"] not in used:
            top += 1
            added += 1
            rows.append(empty_row(top, [h["id"]]))
    new["rows"] = rows
    new["requirements"] = _carry_requirements(old, inp, old_hunks, mapping, fresh, report)
    blast = _carry_areas(old, new, old_hunks, fresh, report)
    if blast is None:
        new.pop("blast_radius", None)
    else:
        new["blast_radius"] = blast
    if orphans or fresh:
        new["orphans"] = orphans + fresh
    for key in ("claims", "base_slice", "refactoring_share", "requirement_coverage"):
        if key in old:
            new[key] = old[key]
    kept = {r.get("id") for r in rows if isinstance(r, dict)}
    lost = [c.get("row") for c in old.get("claims") or [] if isinstance(c, dict) and c.get("row") not in kept]
    if lost:
        report.append(f"claims name rows that are no longer rows ({', '.join(map(str, lost))}): kept as they are; they now point at orphans")
    report.insert(0, f"carried {len(rows) - added} rows, {added} new empty rows, {len(fresh)} new orphans, {len(orphans)} earlier orphans kept")
    return new, report


def _carry_requirements(old: dict, inp, old_hunks: list, mapping: dict, fresh: list, report: list) -> list:
    reg = inp.register
    if old.get("requirements") and not reg.ok:
        raise Refusal(f"grounding_table: the register cannot be read ({reg.why}), so the requirement lines cannot be carried. Expected: "
                      "the register S2 wrote. Do: the driver restores S2's register; nothing was written.")
    lines = {}
    extras = []
    for line in old.get("requirements") or []:
        if isinstance(line, dict) and line.get("r") not in lines:
            lines[line.get("r")] = line
        else:
            extras.append(line)
    out = []
    for r in reg.ids:
        old_line = lines.pop(r, None)
        if old_line is None:
            if r not in reg.exempt:
                out.append(empty_line(r, reg.statements.get(r, "")))
            continue
        if old_line.get("text_sha256") != reg.statements.get(r):
            fresh.append(make_orphan("requirement", old_line, "requirement_changed", _ids(old_line, old_hunks), _diff_sha(old, _ids(old_line, old_hunks))))
            report.append(f"{r}: the requirement text changed - the old line is kept in orphans (requirement_changed)")
            if r not in reg.exempt:
                out.append(empty_line(r, reg.statements.get(r, "")))
            continue
        mapped, gone, before = _carry_ids(old_line.get("hunks"), old_hunks, mapping)
        if gone:
            fresh.append(make_orphan("requirement", old_line, "hunk_gone", gone, _diff_sha(old, before)))
            report.append(f"{r}: {len(gone)} of its hunks left the diff - kept in orphans (hunk_gone)")
        out.append(dict(old_line, hunks=mapped))
    for r, old_line in lines.items():
        before = _ids(old_line, old_hunks)
        fresh.append(make_orphan("requirement", old_line, "requirement_gone", before, _diff_sha(old, before)))
        report.append(f"{r}: no longer in the register - the line is kept in orphans (requirement_gone)")
    return out + extras


def _ids(rec: dict, old_hunks: list) -> list:
    return expand_hunk_refs(rec.get("hunks"), old_hunks)[0]


def _carry_areas(old: dict, new: dict, old_hunks: list, fresh: list, report: list):
    """The new `blast_radius` (None when the index file is absent: no key): role fields move by `key` ONLY when the (non-empty) set
    of hunk digests of the area is unchanged; a judged area the new index no longer holds goes to orphans."""
    blast = new.get("blast_radius")
    old_areas = [a for a in (old.get("blast_radius") or {}).get("areas") or [] if isinstance(a, dict)] \
        if isinstance(old.get("blast_radius"), dict) else []
    by_key = {a.get("key"): a for a in old_areas if a.get("key")}
    sha_old = {h.get("id"): h.get("sha256") for h in old_hunks}
    sha_new = {h["id"]: h["sha256"] for h in new["hunks"]}
    seen_keys = set()
    for area in (blast or {}).get("areas") or []:
        prior = by_key.get(area.get("key"))
        seen_keys.add(area.get("key"))
        if prior is None:
            continue
        before = {sha_old.get(i) for i in (prior.get("touched") or {}).get("hunks") or []}
        after = {sha_new.get(i) for i in (area.get("touched") or {}).get("hunks") or []}
        if before and None not in before and before == after:
            area.update({f: prior.get(f, "") for f in ROLE_AREA_FIELDS})
        elif not _is_empty(prior, ROLE_AREA_FIELDS):
            fresh.append(make_orphan("area", prior, "area_changed", (prior.get("touched") or {}).get("hunks") or [], _diff_sha(old, (prior.get("touched") or {}).get("hunks") or [])))
            report.append(f"area {prior.get('id')}: its hunks changed - the judgement is kept in orphans (area_changed)")
    for key, prior in by_key.items():
        if key not in seen_keys and not _is_empty(prior, ROLE_AREA_FIELDS):
            fresh.append(make_orphan("area", prior, "area_changed", (prior.get("touched") or {}).get("hunks") or [], ""))
            report.append(f"area {prior.get('id')}: it left the blast radius - the judgement is kept in orphans (area_changed)")
    return blast


def switch_to_null(old: dict, inp) -> tuple:
    """A table whose source changed (M-9): every row, line and judged area goes to `orphans` (`source_changed`), then the null form."""
    new = null_table(inp)
    fresh, old_hunks = [], [h for h in old.get("hunks") or [] if isinstance(h, dict)]
    for row in old.get("rows") or []:
        if isinstance(row, dict) and not _is_empty(row, ("label", "requirements", "risks", "question", "reason")):
            ids = _ids(row, old_hunks)
            fresh.append(make_orphan("row", row, "source_changed", ids, _diff_sha(old, ids)))
    for line in old.get("requirements") or []:
        if isinstance(line, dict) and not _is_empty(line, ("state", "hunks", "where", "question")):
            ids = _ids(line, old_hunks)
            fresh.append(make_orphan("requirement", line, "source_changed", ids, _diff_sha(old, ids)))
    for area in (old.get("blast_radius") or {}).get("areas") or [] if isinstance(old.get("blast_radius"), dict) else []:
        if isinstance(area, dict) and not _is_empty(area, ROLE_AREA_FIELDS):
            fresh.append(make_orphan("area", area, "source_changed", (area.get("touched") or {}).get("hunks") or [], ""))
    if old.get("orphans") or fresh:
        new["orphans"] = list(old.get("orphans") or []) + fresh
    if old.get("claims"):
        new["claims"] = old["claims"]
    return new, [f"the source changed from {old.get('implementation_source')!r}: {len(fresh)} records kept in orphans (source_changed)"]


def keep_unreadable(path: Path) -> list:
    """`--refresh --force` on a table the one reader refuses (empty, `{}`, a list at the top, another schema, a syntax flaw ...): the
    file is kept BYTE FOR BYTE beside the table (`grounding.unreadable-<sha8>.yaml`) and ONE orphan (`was: table`, `why_orphan:
    table_unreadable`) points at it - the two facts every `--force` text states (`FORCE_FACTS`). This module parses the table
    nowhere else (the one reader refuses it, so there is nothing structured to carry); the bytes are what is kept."""
    raw = path.read_bytes()
    name = f"grounding.unreadable-{hashlib.sha256(raw).hexdigest()[:8]}.yaml"
    path.with_name(name).write_bytes(raw)
    return [make_orphan("table", {"id": "", "reason": f"the table that could not be read is kept as work/{name}"}, "table_unreadable", [], "")]


# --- --check -----------------------------------------------------------------------------------------------------------------

def _named(items, where=None) -> str:
    return DV.named([DV.one_line(i)[:140] for i in items], where=where, sep="; ")


def _find(out: list, rule: str, who: str, what: str, items, expected: str, fix: str, where=None) -> None:
    out.append(Finding(rule, f"{len(list(items))} {what}: {_named(items, where)}. Expected: {expected} — fix: {fix}", who))


R0_FIX = {"driver": "the driver's S3 window preparation writes the table again; you fill only labels, requirement lines and area judgements in it.",
          "role": "repair the file you edited: the message above names the place; keep to the keys of the table.",
          "conductor": "the conductor decides, and the driver's S3 window preparation then runs `--refresh --force` for this story: it "
                       f"writes a new table; {FORCE_FACTS}."}
# The reader files an empty table and a list at the top under the driver, but the driver's `--refresh` refuses them (exit 2): the
# door that works is `--refresh --force`, which the conductor opens (t-1046 seam 9.2). R0 names the door that works (FR-2).
R0_WHO = {"empty": "conductor", "not_a_mapping": "conductor"}


def _r0(problem, who=None) -> Finding:
    who = who or R0_WHO.get(getattr(problem, "kind", ""), "") or problem.who
    return Finding("R0", f"{_sentence(DV.one_line(str(problem)))} Expected: the table the S3 window preparation writes (schema_version "
                         f"{PC.GROUNDING_SCHEMA_VERSION}). — fix: {R0_FIX[who]}", who)


def _hunk_items(hunks: list) -> list:
    return [f"{h.rec['short']} (..{h.rec['file'][-44:]}:{h.rec['new'].split(',')[0]}, id {h.rec['id']})" for h in hunks]


def _dicts(value) -> list:
    return [x for x in value if isinstance(x, dict)] if isinstance(value, list) else []


def r5_findings(data: dict, inp) -> list:
    """R5: the table was labelled against other inputs (diff bytes, source, commit, register) or its hunk list was edited."""
    out = []
    on_disk = {Path(d["path"]).name: d for d in inp.diffs}
    table = {Path(str(d.get("path", ""))).name: d for d in _dicts(data.get("diff"))}
    moved = [f"{n} was {str(table[n].get('sha256'))[:8]}…, is {on_disk[n]['sha256'][:8]}…"
             for n in on_disk if n in table and table[n].get("sha256") != on_disk[n]["sha256"]]
    moved += [f"{n} was added" for n in on_disk if n not in table] + [f"{n} was removed" for n in table if n not in on_disk]
    if moved:
        _find(out, "R5", "driver", "implementation diff(s) moved since the table was labelled", moved,
              "rows measured on other bytes do not count (the MR moved).", R5_FIX)
    if data.get("implementation_source") != "diff":
        out.append(_r5(f"the table records implementation_source {data.get('implementation_source')!r} but the story records `diff`. "
                       "Expected: a table of the same source"))
    commits = [f"{n}: was {table[n].get('implementation_commit')}, is {on_disk[n]['implementation_commit']}" for n in on_disk if n in table
               and table[n].get("implementation_commit") != on_disk[n]["implementation_commit"]
               and COMMIT_RE.fullmatch(str(table[n].get("implementation_commit")))]
    if commits:
        _find(out, "R5", "driver", "implementation commit(s) changed since the table was labelled", commits,
              "the commit recorded with the diff.", R5_FIX)
    mine, was = inp.register.sha256, data.get("register_sha256")
    if inp.register.ok and isinstance(was, str) and was and was != mine:
        out.append(_r5("the requirements register changed since the table was labelled. Expected: a table labelled against this register"))
    elif inp.register.ok and not (isinstance(was, str) and was):
        out.append(_r5("the table records no digest of the requirements register. Expected: `register_sha256` as the driver wrote it"))
    keys = ("id", "short", "repo", "file", "kind", "old", "new", "function", "added", "removed", "sha256", "pseudo")
    mine_h = [tuple(str(h.rec[k]) for k in keys) for h in inp.hunks]
    theirs = [tuple(str(h.get(k)) for k in keys) for h in _dicts(data.get("hunks"))]
    if mine_h != theirs and not moved:
        out.append(_r5(f"the hunk list of the table ({len(theirs)} records) does not match the diff on disk ({len(mine_h)} hunks); it was "
                       "edited. Expected: the list the driver wrote"))
    return out


def _r5(what: str) -> Finding:
    return Finding("R5", f"{what} — fix: {R5_FIX}", "driver")


def _key(value):
    """`value` as a dict/set key: text stays text, anything else (a list or a map the role wrote where an id belongs) becomes its repr."""
    return value if isinstance(value, str) else repr(value)


def _traps(doc, path: str, value, typed: bool = True) -> str:
    """Why a scalar the role wrote reads differently from how it was written, or ''. `typed` False judges only what would cut the
    text (a comment, a line break), not the type the field should have."""
    node = doc.nodes.get(path)
    if node is not None and node.comment:
        return "holds ` #`, which the table reader takes for a comment (the text after it is lost); put the value in double quotes"
    if node is not None and node.end_line > node.line:
        return "is broken over several lines; write it on one line in double quotes"
    if not typed:
        return ""
    if isinstance(value, dict):
        return "reads as a map (`{...}` or an empty value); put the text in double quotes"
    if isinstance(value, list):
        return "reads as a list; put the text in double quotes"
    if isinstance(value, bool) or isinstance(value, int) or value is None:
        return "reads as a number, a boolean or null, not as text; put the text in double quotes"
    return ""


def _leaf_traps(doc, path: str, value, name: str, skip: set, out: list) -> None:
    """Every scalar under `value` (what the role wrote in a row, a requirement line, a claim - risks, hunk lists, requirement lists
    included) is read as written: a ` #` comment or a line break would cut a person's words silently, so each is a finding that
    names where (the risk by its id). `skip` holds the paths already judged field by field."""
    if isinstance(value, dict):
        for key, item in value.items():
            _leaf_traps(doc, f"{path}.{key}", item, f"{name} `{key}`", skip, out)
    elif isinstance(value, list):
        for n, item in enumerate(value):
            tag = item.get("id") if isinstance(item, dict) and item.get("id") else n
            _leaf_traps(doc, f"{path}[{n}]", item, f"{name}[{tag}]", skip, out)
    elif path not in skip:
        flaw = _traps(doc, path, value, typed=False)
        if flaw:
            out.append(f"{name} {flaw}")


def _scan_r3(doc, data: dict, out: list) -> None:
    labels, states = list(H.vocabulary()["grounding_labels"]), list(H.vocabulary()["requirement_grounding_states"])
    shape, words, traps, long_, coded = [], [], [], [], []
    for section, fields in (("rows", ("label", "reason", "question")), ("requirements", ("state", "where", "question"))):
        value = data.get(section)
        if value is not None and not isinstance(value, list):
            shape.append(f"`{section}` is not a list")
            continue
        for i, rec in enumerate(value or []):
            if not isinstance(rec, dict):
                shape.append(f"{section}[{i}] is not a mapping")
                continue
            name = f"row {rec.get('id')}" if section == "rows" else f"requirement {rec.get('r')}"
            judged = {f"{section}[{i}].{field}" for field in fields}
            for field in fields:
                if field not in rec:
                    continue
                flaw = _traps(doc, f"{section}[{i}].{field}", rec[field])
                if flaw:
                    traps.append(f"{name} `{field}` {flaw}")
                    continue
                limit = REASON_LIMIT if field == "reason" else QUESTION_LIMIT if field == "question" else 0
                if limit and len(rec[field]) > limit:
                    long_.append(f"{name} `{field}` is {len(rec[field])} characters (limit {limit})")
            _leaf_traps(doc, f"{section}[{i}]", rec, name, judged, traps)
            word, vocab = (rec.get("label"), labels) if section == "rows" else (rec.get("state"), states)
            if isinstance(word, str) and word and word not in vocab:
                words.append(f"{name} `{'label' if section == 'rows' else 'state'}` is \"{word[:40]}\"")
    for i, claim in enumerate(_dicts(data.get("claims"))):
        _leaf_traps(doc, f"claims[{i}]", claim, f"claim {claim.get('row')}", set(), traps)
    blast = data.get("blast_radius")
    if blast is not None and not isinstance(blast, dict):
        shape.append("`blast_radius` is not a mapping")
        blast = {}
    for i, area in enumerate(_dicts((blast or {}).get("areas"))):
        for field in ROLE_AREA_FIELDS:
            if field in area:
                flaw = _traps(doc, f"blast_radius.areas[{i}].{field}", area[field])
                if flaw:
                    traps.append(f"area {area.get('id')} `{field}` {flaw}")
        if isinstance(area.get("matters"), str) and area["matters"] not in MATTERS:
            words.append(f"area {area.get('id')} `matters` is \"{area['matters'][:40]}\"")
        if area.get("path_kind", "") not in PATH_KINDS:
            coded.append(f"area {area.get('id')} `path_kind` is \"{str(area.get('path_kind'))[:40]}\"")
    for key in ("refactoring_share", "requirement_coverage"):
        road = (data.get(key) or {}).get("road") if isinstance(data.get(key), dict) else None
        if road is not None and road not in ROADS:
            coded.append(f"`{key}.road` is \"{str(road)[:40]}\"")
    kept_words = f"a label of: {', '.join(labels)}; a state of: {', '.join(states)}; `matters` yes, no or empty."
    for found, who, what, expected, fix in (
            (shape, "role", "table parts that are not lists of mappings", "rows, requirements and areas as lists of mappings.",
             "write each as a mapping under its key."),
            (words, "role", "words outside the closed lists", kept_words, "write one of the list."),
            (traps, "role", "values the table reader takes differently from how they were written",
             "plain text values that read as written.", "put the value in double quotes."),
            (long_, "role", "values over their limit",
             f"a `reason` of at most {REASON_LIMIT} characters and a `question` of at most {QUESTION_LIMIT}.", "shorten it."),
            (coded, "driver", "fields of the code with an unknown word", "the words the blast radius index and the measures write.",
             "the driver's S3 window preparation rebuilds the blast radius index; you do not edit these fields.")):
        if found:
            _find(out, "R3", who, what, found, expected, fix)


def _scan_rows(data: dict, inp, out: list, ctx: list) -> None:
    """R1 (completeness by the RECOMPUTED index) and R4 (references and obligations of a label)."""
    rows = _dicts(data.get("rows"))
    _scan_r1(inp, rows, out, ctx)
    _scan_r4(data, inp, rows, out)


def _covered_ids(inp, rows: list) -> set:
    """The ids of the RECOMPUTED hunks a row with a label names (an id, or `all:<repo>:<file>`): ONE reading for R1 and for the counts."""
    index = hunk_index([h.rec for h in inp.hunks])
    covered: set = set()
    for row in rows:
        if str(row.get("label") or "").strip():
            covered.update(expand_hunk_refs(row.get("hunks"), index)[0])
    return covered


def _scan_r1(inp, rows: list, out: list, ctx: list) -> None:
    """R1: a hunk of the diff on disk is covered when some row with a label names it (an id, or `all:<repo>:<file>`). The hunk list
    is the RECOMPUTED one, never the table's `hunks[]` - a role that deletes a hunk record or a row hides nothing (I1)."""
    covered = _covered_ids(inp, rows)
    missing = [h for h in inp.hunks if h.rec["id"] not in covered]
    labels = "/".join(H.vocabulary()["grounding_labels"])
    if missing:
        _find(out, "R1", "role", f"of {len(inp.hunks)} hunks of the implementation diff have no labelled row", _hunk_items(missing),
              f"every hunk in a row labelled one of {labels}; a whole file may be one row (hunks: all:<repo>:<file>).",
              "fill `label` and `reason` of the empty rows; a hunk you cannot judge is `unclassified` with a reason and a question.",
              WHERE_ROWS)
    if not inp.hunks and not inp.refusals:
        out.append(Finding("R1", "the implementation diff on disk has no hunk, so nothing can be labelled. Expected: a diff that holds "
                                 "the change — fix: S1 exports the diff again (the driver acts), or the person says there is no "
                                 "change to read.", "driver"))
    whole = sorted({w[1] for r in rows if r.get("label") == "infrastructure" for w in [parse_all_ref(r.get("hunks"))] if w})
    if whole:
        ctx.append("grounding: labelled whole: " + ", ".join(whole))


R4_SETS = (
    ("rows", "row labels that point at the register wrongly", "implements rows that name R ids of the register.",
     "name R ids from the register, or relabel the row."),
    ("refs", "references to hunks that are not in the diff", "hunk ids of the diff or all:<repo>:<file> of a file in it.",
     "use the ids and files listed in `hunks` of the table."),
    ("claim", "behaviour_change rows without a claim", "a claims[] entry whose `row` is the row id.",
     "write the claim for the row, or relabel it."),
    ("need", "rows without what their label needs", "a `question` and a `reason` on every unrelated or unclassified row.",
     "fill the missing fields."),
    ("dup", "ids used twice", "every G, K and B id once in the table.", "give each its own id."),
    ("link", "implemented or partial hunks not tied by an implements row",
     "implemented and partial only on hunks an implements row ties to the same R.",
     "add the R to the implements row of those hunks, or lower the state."))


def _row_problems(row: dict, n: int, hunks: list, ctx, bad: dict) -> None:
    """R4 for ONE row: duplicate ids, references to hunks the diff does not hold, and what its label obliges. `ctx` carries the
    register and the claims' rows, plus the ids seen so far (`seen_g`, `seen_k`)."""
    name = f"row {row.get('id')}"
    gid = str(row.get("id"))
    if gid in ctx.seen_g:
        bad["dup"].append(f"G id {row.get('id')} is used by rows[{ctx.seen_g[gid]}] and rows[{n}]")
    ctx.seen_g.setdefault(gid, n)
    for risk in _dicts(row.get("risks")):
        if str(risk.get("id")) in ctx.seen_k:
            bad["dup"].append(f"K id {risk.get('id')} is used by {ctx.seen_k[str(risk.get('id'))]} and {name}")
        ctx.seen_k.setdefault(str(risk.get("id")), name)
    bad["refs"] += [f"{name} names {d[:50]}, which is not in the diff" for d in expand_hunk_refs(row.get("hunks"), hunks)[1]]
    if row.get("label") == "implements":
        named = row.get("requirements") if isinstance(row.get("requirements"), list) else []
        if not named:
            bad["rows"].append(f"{name} is implements and names no requirement")
        bad["rows"] += [f"{name} is implements and names {r}, which the register does not hold" for r in named
                        if ctx.reg.ok and r not in ctx.reg.ids]
    if row.get("label") == "behaviour_change" and _key(row.get("id")) not in ctx.claims:
        bad["claim"].append(f"{name} is behaviour_change and no claims[] entry names it")
    if row.get("label") in ("unrelated", "unclassified"):
        bad["need"] += [f"{name} is {row['label']} and has no `{field}`" for field in ("question", "reason")
                        if not (isinstance(row.get(field), str) and row[field].strip())]


def _scan_r4(data: dict, inp, rows: list, out: list) -> None:
    """R4: references and obligations - every row, then every requirement line against the rows that tie it to hunks."""
    hunks = hunk_index([h.rec for h in inp.hunks])
    bad: dict = {key: [] for key, *_ in R4_SETS}
    ctx = SimpleNamespace(reg=inp.register, claims={_key(c.get("row")) for c in _dicts(data.get("claims"))}, seen_g={}, seen_k={})
    for n, row in enumerate(rows):
        _row_problems(row, n, hunks, ctx, bad)
    impl_rows: dict = {}
    for row in rows:
        if row.get("label") == "implements":
            for r in row.get("requirements") if isinstance(row.get("requirements"), list) else []:
                impl_rows.setdefault(_key(r), set()).update(expand_hunk_refs(row.get("hunks"), hunks)[0])
    for line in _dicts(data.get("requirements")):
        got, dangling = expand_hunk_refs(line.get("hunks"), hunks)
        bad["refs"] += [f"requirement {line.get('r')} names {d[:50]}, which is not in the diff" for d in dangling]
        if line.get("state") in ("implemented", "partial"):
            tied = impl_rows.get(_key(line.get("r")), set())
            bad["link"] += [f"requirement {line.get('r')} is {line['state']} on {h}, which no implements row ties to it"
                            for h in got if h not in tied]
    for key, what, expected, fix in R4_SETS:
        if bad[key]:
            _find(out, "R4", "role", what, bad[key], expected, fix)


def _scan_requirements(data: dict, inp, out: list) -> None:
    reg = inp.register
    if not reg.ok:
        out.append(Finding("R2", f"the requirements register cannot be read ({reg.why}). Expected: the register S2 wrote — fix: the "
                                 "driver restores S2's register; a role does not edit it.", "driver"))
        return
    if reg.unread:
        _find(out, "R2", "driver", "rows of the register that no requirement id can be read from", reg.unread, "a first cell R-<n>.", "S2 writes the id again (the driver acts).")
    lines = _dicts(data.get("requirements"))
    by_r: dict = {}
    for line in lines:
        by_r.setdefault(line.get("r"), []).append(line)
    need = [r for r in reg.ids if r not in reg.exempt]
    gap = [r for r in need if r not in by_r or not str(by_r[r][0].get("state") or "").strip()]
    if gap:
        _find(out, "R2", "role", "requirements of the register have no grounding line", gap,
              "state implemented or partial with its hunks, not_implemented with a blocking question, outside_diff with where (none needs a question), unknown with a question.",
              "fill `state` and its field in the lines under `requirements`.")
    stray = [f"{r} is not in the register" for r in by_r if r not in reg.ids] + [f"{r} is written {len(v)} times" for r, v in by_r.items() if len(v) > 1]
    if stray:
        _find(out, "R2", "role", "requirement lines that do not match the register", stray, "one line per requirement of the register.", "remove or merge the line.")
    owed = []
    for line in lines:
        state, r = line.get("state"), line.get("r")
        if state in ("implemented", "partial") and not (line.get("hunks") or []):
            owed.append(f"{r} is {state} with no hunks")
        if state == "outside_diff" and not str(line.get("where") or "").strip():
            owed.append(f"{r} is outside_diff with no `where`")
        if state in ("not_implemented", "unknown") and not str(line.get("question") or "").strip():
            owed.append(f"{r} is {state} with no `question`")
    if owed:
        _find(out, "R2", "role", "requirement lines without what their state needs", owed,
              "hunks for implemented and partial, a question for not_implemented and unknown, `where` for outside_diff.",
              "fill the missing field.")


BR_FIX = "the driver's S3 window preparation builds (or rebuilds) the blast radius index and refreshes the table."


def _area_code(area: dict) -> tuple:
    """The part of an area the CODE wrote (id, key, path kind, the hunks it touches): what the role must leave alone."""
    touched = area.get("touched") if isinstance(area.get("touched"), dict) else {}
    hunks = touched.get("hunks") if isinstance(touched.get("hunks"), list) else []
    return str(area.get("id")), str(area.get("key")), str(area.get("path_kind", "")), tuple(sorted(str(h) for h in hunks))


def _judged_areas(data: dict, truth: dict, out: list) -> list:
    """The areas of the index FILE (`truth`), each with the role's judgement from the table by its B id. The code part is never
    taken from the table: an area the table lacks is unjudged, an area the table adds or changes is a finding for the driver."""
    blast = data.get("blast_radius")
    mine: dict = {}
    for area in _dicts(blast.get("areas") if isinstance(blast, dict) else None):
        mine.setdefault(str(area.get("id")), area)
    dup = [f"B id {i} is used {n} times" for i, n in Counter(
        str(a.get("id")) for a in _dicts(blast.get("areas") if isinstance(blast, dict) else None)).items() if n > 1]
    if dup:
        _find(out, "R4", "driver", "area ids used twice", dup, "every B id once.", BR_FIX)
    edited, judged = [], []
    for area in truth.get("areas") or []:
        theirs = mine.pop(str(area.get("id")), None)
        if theirs is None:
            edited.append(f"{area.get('id')} ({str(area.get('key'))[:60]}) is missing from the table")
        elif _area_code(theirs) != _area_code(area):
            edited.append(f"{area.get('id')} ({str(area.get('key'))[:60]}) differs from the index in its key, path kind or hunks")
        judged.append(dict(area, **{f: (theirs or {}).get(f, "") for f in ROLE_AREA_FIELDS}))
    edited += [f"{i} is in the table but not in the index" for i in mine]
    if edited:
        _find(out, "R8", "driver", "areas of the table that do not match the blast radius index", edited,
              "the area list the driver projected from work/blast-radius.json.", f"nothing for you to edit: {BR_FIX}")
    return judged


def _scan_areas(data: dict, out: list, inp) -> list:
    """R8: the blast radius index exists and matches the diff, and every area it marks is judged and has its regression. The index
    state and the code part of every area come from `work/blast-radius.json` (`project_blast`), NEVER from the table's own copy of
    them: a `built` the role wrote, or an area the role deleted, hides nothing (I1, I3). A file that cannot be read is an R8 finding
    like an absent one (FR-59: an unknown is not a pass)."""
    truth = project_blast(inp)
    state = truth["index"].get("state")
    ctx: list = []
    if state == "absent":
        out.append(Finding("R8", "the table has no blast radius index: work/blast-radius.json does not exist. Expected: the index the "
                                 f"driver builds before the table is labelled — fix: {BR_FIX}", "driver"))
        return ctx
    if state == "unreadable":
        out.append(Finding("R8", "the blast radius index work/blast-radius.json cannot be read (it is not a mapping with an `areas` "
                                 "list), so no area can be judged; it is not counted as an empty index. Expected: an index the "
                                 f"driver builds — fix: {BR_FIX}", "driver"))
        return ctx
    if state not in ("built", "stale"):
        out.append(Finding("R8", f"the blast radius index records the state {str(state)[:40]!r}, which this build does not know. "
                                 f"Expected: built — fix: {BR_FIX}", "driver"))
        return ctx
    if state == "stale":
        out.append(Finding("R8", "the blast radius index does not match the diff on disk (built on other bytes). Expected: an index of "
                                 f"this diff — fix: {BR_FIX}", "driver"))
    areas = _judged_areas(data, truth, out)
    unjudged, no_reg, no_tests, shared = [], [], [], []
    for area in areas:
        name = f"{area.get('id')} ({str(area.get('key'))[:60]})"
        regression = str(area.get("regression") or "").strip()
        matters = area.get("matters")
        if matters in ("", None):
            unjudged.append(name)
        if matters == "yes" and not regression:
            no_reg.append(name)
        if matters == "yes":
            tests = area.get("tests")
            gap = str(area.get("tests_gap") or "").strip().lower() not in ("", "no", "none", "false")
            if (tests in (None, "", [], "none", "unmeasured") or gap) and not str(area.get("add_tests") or "").strip():
                no_tests.append(name)
        if area.get("path_kind", "") not in PLAIN_PATH_KINDS and not regression:
            shared.append(name)
    for names, what, expected, fix in (
            (unjudged, "areas are not judged (`matters` is empty)", "`matters` yes or no on every area.",
             "fill `matters` and `why` of each area."),
            (no_reg, R8_NO_REGRESSION,
             "the tests or set, or gap:<reason>.", "fill `regression` of each area."),
            (no_tests, "areas are matters: yes with no tests and no add_tests",
             "tests that cover the area, or `add_tests` (TS-n or not_needed:<reason>).", "fill `add_tests` of each area."),
            (shared, R8_SHARED_NO_REGRESSION,
             "the tests or set that defend it, or gap:<reason>, on every area that is not additive.", "fill `regression` of each area.")):
        if names:
            _find(out, "R8", "role", what, names, expected, fix)
    return ctx


def check_report(root) -> tuple:
    """`(findings, context lines)`: the whole check, read-only. Order: R0 (form) stops everything; R5 (stale) stops R1-R4 and R8; then
    R1, R2, R3, R4 and R8 together."""
    root = Path(root)
    world, why = source_state(root)
    ctx = []
    if world == "mismatch":
        return [Finding("R0", f"work/grounding.yaml cannot be judged: {why}. Expected: implementation_source `diff` when a diff is on "
                              "disk. — fix: the conductor asks S1 to record the source again (stage_done --set "
                              "implementation_source=...) or the diff to be removed.", "conductor")], ctx
    doc, problem = PC.read_grounding(root)
    if world != "diff":
        if problem and problem.kind == "missing":
            return [], [f"grounding: no table ({world.split(':', 1)[1]}); nothing to label"]
        if problem:
            return [_r0(problem)], ctx
        source = world.split(":", 1)[1]
        want = "" if source == "absent" else source
        null = doc.data.get("null_outcome")
        if doc.data.get("implementation_source") != want or not isinstance(null, dict) or null.get("source") != source:
            return [_r5(f"the table records implementation_source {doc.data.get('implementation_source')!r} while the story "
                        f"records {source!r}. Expected: the null form of this source")], ctx
        return [], [f"grounding: null outcome recorded ({source})"]
    if problem:
        return [_r0(problem)], ctx
    data = doc.data
    if not isinstance(data.get("implementation_source"), str) or not data["implementation_source"]:
        return [_r0(PC.GroundingProblem("missing", "work/grounding.yaml has no `implementation_source`"))], ctx
    inp = gather(root)
    if inp.no_body:
        return [Finding("R1", "the diff index carries no hunk bodies, so no hunk can be identified. Expected: diff_pass.index giving "
                              "every hunk its body — fix: this is the factory's own defect; the conductor reports it.", "conductor")], ctx
    stale = r5_findings(data, inp)
    if stale:
        return stale, ctx
    out: list = []
    for refusal in inp.refusals:
        out.append(Finding("R1", f"{DV.one_line(refusal['text'])[:300]} Expected: a diff the reader can take in full — fix: S1 exports "
                                 "the diff again (the driver acts).", "driver"))
    for d in inp.diffs:
        if d["implementation_commit"].startswith("unmeasured"):
            ctx.append(f"grounding: {Path(d['path']).name}: implementation_commit {d['implementation_commit']}")
    _scan_rows(data, inp, out, ctx)
    _scan_requirements(data, inp, out)
    _scan_r3(doc, data, out)
    ctx += _scan_areas(data, out, inp)
    if _dicts(data.get("orphans")):
        ctx.append(f"grounding: {len(_dicts(data.get('orphans')))} orphaned records are kept in the table (not counted)")
    return out, ctx


def check(root) -> list:
    return check_report(root)[0]


# --- the refactoring share (G2-1) ----------------------------------------------------------------------------------------------

SHARE_REPORT_LABEL = "unclassified"           # REPORT only (the `unclassified` field); no road ever reads it, the policy decides W
SHARE_UNKNOWN_RULES = ("R0", "R1", "R5")      # a table that cannot be read, is not complete, or sits on other bytes: no measure


def _share_unknown(out: dict, reason: str) -> dict:
    out.update(road="unknown", percent="n/a", reason=reason)
    return out


def _tenths(part: int, whole: int) -> str:
    """`part` of `whole` as a percent with one decimal, in integers (display only: the road never compares it)."""
    tenths = (1000 * part + whole // 2) // whole
    return f"{tenths // 10}.{tenths % 10}"


def share(data, policy, findings, policy_why: str = "") -> dict:
    """The refactoring share of a readable table, pure (writes nothing; the caller hands the findings of `check`, so the table is
    not judged twice). T = changed lines of the hunks whose file `TF.file_kind` calls production (the table's own `kind` is not
    believed); W = T lines of the hunks every row of which carries a label of `policy["numerator_labels"]`; a pseudo-hunk (a pure
    rename, a mode change) weighs 0 lines and its file is named. The road compares integers only, `100*W > percent*T`, strictly:
    a share of exactly the threshold is not past it. What cannot be measured is `unknown` with the reason, never `none` and
    never `stop` (FR-41, FR-59): no policy, a finding that says the table is not whole or not the diff's, a production hunk
    with no label. The thresholds and label words come from the policy only."""
    out = {"measure": "", "refactoring": None, "unclassified": None, "total": None, "percent": "n/a", "road": "unknown",
           "policy": {}, "mixed_hunks": [], "outside_files": [], "pseudo_files": [], "reason": ""}
    if not isinstance(policy, dict):
        return _share_unknown(out, f"the thresholds cannot be read: {policy_why or 'no policy was given'}")
    out["measure"] = policy["measure"]
    out["policy"] = {k: policy[k] for k in ("notify_above_percent", "stop_above_percent", "numerator_labels")}
    bad = sorted({f.rule for f in findings or [] if f.rule in SHARE_UNKNOWN_RULES})
    if bad:
        return _share_unknown(out, f"the grounding check found {', '.join(bad)}, so the table cannot be measured now")
    if not isinstance(data, dict):
        return _share_unknown(out, "the table is not a mapping")
    hunks = _dicts(data.get("hunks"))
    index = hunk_index(hunks)
    labels_of: dict = {}                                    # hunk id -> labels of the rows that stand on it
    for row in _dicts(data.get("rows")):
        mark = row.get("label")
        for ident in expand_hunk_refs(row.get("hunks"), index)[0]:
            labels_of.setdefault(ident, []).append(mark if isinstance(mark, str) else "")
    numerator, kinds = policy["numerator_labels"], {}
    total = whole = tally_unclassified = 0
    for h in hunks:
        name = str(h.get("file", ""))
        added, removed = h.get("added"), h.get("removed")
        if any(type(n) is not int or n < 0 for n in (added, removed)):
            return _share_unknown(out, f"hunk {h.get('id')} has a changed-line count that is not a whole number")
        if name not in kinds:
            kinds[name] = TF.file_kind(name)
        if kinds[name] != "production":
            if added + removed and name not in out["outside_files"]:
                out["outside_files"].append(name)
            continue
        if h.get("pseudo") or not added + removed:
            if name not in out["pseudo_files"]:
                out["pseudo_files"].append(name)
            continue
        lines, marks = added + removed, labels_of.get(h.get("id"), [])
        if not marks or not all(marks):
            return _share_unknown(out, f"hunk {h.get('id')} ({name}) has an empty mark: no row labels it")
        total += lines
        if all(m in numerator for m in marks):
            whole += lines
            if set(marks) == {SHARE_REPORT_LABEL}:
                tally_unclassified += lines
        elif any(m in numerator for m in marks):
            out["mixed_hunks"].append(h.get("id"))
    out.update(refactoring=whole, unclassified=tally_unclassified, total=total)
    if not total:                                           # nothing to divide: not 0 %, and no card either (FR-41)
        out.update(road="none", reason="no changed production line in the diff, so a share is not defined")
        return out
    out["percent"] = _tenths(whole, total)
    notify, stop = policy["notify_above_percent"], policy["stop_above_percent"]
    out["road"] = "stop" if 100 * whole > stop * total else "notify" if 100 * whole > notify * total else "none"
    return out


# --- the requirement coverage and the two stops (G2-2) -------------------------------------------------------------------------

COVERAGE_STOP_BLOCK = "grounding coverage stop"           # the names `references/block-names.json` holds, each followed by the digest
REFACTORING_STOP_BLOCK = "grounding refactoring stop"
COVERAGE_NUMERATOR = ("implemented", "partial")             # the states that count as covered
STOP_STAGE = "S3"


def _blank_coverage() -> dict:
    return {"implemented": 0, "partial": 0, "n": 0, "unknown": 0, "percent": "n/a", "road": "unknown", "reading": "", "outside": [], "reason": ""}


def _coverage_unknown(out: dict, reason: str) -> dict:
    out.update(road="unknown", percent="n/a", reason=reason)
    return out


def coverage(data, reg, policy, evidenced=frozenset(), policy_why: str = "") -> dict:
    """The requirement coverage of a readable table, pure (writes nothing). `reg` is `register_info` (`ok`, `ids`, `exempt`). N = the
    register's ids minus the implementation-only ones, minus the ids of `evidenced` (an `unchanged` row whose place the base slice shows
    untouched - the ONLY way a row leaves the count by its delta), minus the lines `outside_diff` with a `where` that is not `none`.
    The numerator is the lines `implemented` and `partial`; `unknown`, `not_implemented`, `outside_diff` with `where: none`, a line with
    no state and an id with no line at all stay in N and out of the numerator (the error runs toward the stop, FR-59). `road`:
    `100*num < percent*N` stop, `num < N` highlight, else none; N == 0 is a stop with `reading: nothing_asked` (a merge request that
    asks nothing of the story is not a pass); what cannot be measured is `unknown`, never `none` and never `stop` (FR-41)."""
    out = _blank_coverage()
    if not isinstance(policy, dict) or type(policy.get("coverage_stop_below_percent")) is not int:
        return _coverage_unknown(out, f"the thresholds cannot be read: {policy_why or 'no policy was given'}")
    if not isinstance(data, dict):
        return _coverage_unknown(out, "the table is not a mapping")
    if not getattr(reg, "ok", False):
        return _coverage_unknown(out, f"the requirements register cannot be read: {getattr(reg, 'why', '') or 'no register was given'}")
    by_r: dict = {}
    for line in _dicts(data.get("requirements")):
        by_r.setdefault(line.get("r"), line)
    exempt, seen = set(reg.exempt), set()
    for r in reg.ids:
        if r in exempt or r in seen or r in evidenced:
            continue
        seen.add(r)
        line = by_r.get(r) or {}
        state = str(line.get("state") or "").strip()
        where = str(line.get("where") or "").strip()
        if state == "outside_diff" and where and where.lower() != "none":
            continue                                        # an honest merge request: the requirement is met elsewhere, and says where
        out["n"] += 1
        if state in COVERAGE_NUMERATOR:
            out[state] += 1
            continue
        out["unknown"] += state == "unknown"
        out["outside"].append({"r": r, "state": state or "absent"})
    num, n = out["implemented"] + out["partial"], out["n"]
    if not n:
        out.update(road="stop", reading="nothing_asked", reason="no requirement of the register is left to be covered by this change")
        return out
    out["percent"] = _tenths(num, n)
    out["road"] = "stop" if 100 * num < policy["coverage_stop_below_percent"] * n else "highlight" if num < n else "none"
    return out


def _evidenced(root, reg) -> frozenset:
    """The ids of the register rows the base slice shows untouched (`base_slice.unchanged_evidence` says `evidenced`). Asked only for a row
    whose delta says `unchanged`; the slice is collected once. Anything that cannot be established - the slice raised, the register cannot
    be read - evidences nobody: the row stays in the count (the error runs toward the stop)."""
    try:
        text = Path(reg.path).read_bytes().decode("utf-8", "replace")
        exempt = set(reg.exempt)
        rows = [row for row in C.register_rows(text) if row["r"] not in exempt and C.delta_state(row) == "unchanged"]
        if not rows:
            return frozenset()
        import base_slice as BS                              # lazy: base_slice imports this module
        collected = BS.collect(root)
        return frozenset(row["r"] for row in rows if BS.unchanged_evidence(row, root, collected=collected)[0] == "evidenced")
    except Exception:
        return frozenset()


def coverage_of(root) -> dict:
    """`coverage` over the story's own table and register, read now: THE caller of `coverage` for the driver, the `--share` write and R6."""
    root = Path(root)
    out = _blank_coverage()
    policy, why = PC.grounding_policy()
    doc, problem = PC.read_grounding(root)
    if doc is None:
        return _coverage_unknown(out, f"the table cannot be read: {_sentence(problem)}")
    reg = register_info(root)
    return coverage(doc.data, reg, policy, _evidenced(root, reg) if reg.ok else frozenset(), policy_why=why)


def share_of(root) -> dict:
    """`share` over the story's own table and policy, read now (the driver's question asks it; `unknown` with the reason when the table or
    the policy cannot be read)."""
    root = Path(root)
    policy, why = PC.grounding_policy()
    doc, problem = PC.read_grounding(root)
    if doc is None:
        return share(None, policy, [Finding("R0", str(problem), "conductor")], why)       # R0: the table cannot be read, so no measure
    return share(doc.data, policy, check(root), why)


def _hex12(parts: list) -> str:
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()[:12]


def coverage_digest(root, cov: dict) -> str:
    """12 hex of the state a coverage stop is about: the diff bytes (the sorted sha256 of every `impl-diff*.txt`) and, per requirement
    outside the numerator, `R:state:statement_sha`. The register's whole sha256 is NOT in it: the claims' projection moves it on a normal
    history, and a word would then never survive the window. A word given for another digest is another question's word."""
    reg = register_info(root)
    outside = sorted(f"{o['r']}:{o['state']}:{reg.statements.get(o['r'], '')}" for o in cov.get("outside") or [] if isinstance(o, dict))
    return _hex12(sorted(d["sha256"] for d in diff_records(root)) + ["--"] + outside)


def refactoring_digest(root, result: dict) -> str:
    """12 hex of the state a refactoring stop is about: the diff bytes and the two numbers the share is made of (W, T)."""
    return _hex12(sorted(d["sha256"] for d in diff_records(root)) + ["--", f"W={result.get('refactoring')}", f"T={result.get('total')}"])


def stop_word(pipeline, prefix: str, digest: str):
    """The live `stage_overrides[]` record of S3 that is a person's word for THIS stop, or None - the ONE reader of that word, for the
    question and for R6 (AR-13). The word is `<prefix> <digest>` read by `contract.stage_override_values` (the digest compared for
    EQUALITY, never as a substring), or the `*` of a person (passes every block, FR-4: it is reported as the person's word). A revoked
    record, an empty decision, another stage, another digest, another prefix, a pipeline that cannot be read: no word."""
    digest = str(digest or "").strip()
    if digest:
        for value, entry in C.stage_override_values(pipeline, prefix, STOP_STAGE):
            if value == digest:
                return entry
    for entry in C.live_stage_overrides(pipeline, STOP_STAGE):
        if str(entry.get("match") or "").strip() == "*":
            return entry
    return None


def _saved_coverage(saved) -> str:
    if not isinstance(saved, dict):
        return ""
    return f" (the key saved by the last measure says {saved.get('implemented')} implemented and {saved.get('partial')} partial of {saved.get('n')})"


def r6_findings(root, data: dict, found: list) -> list:
    """R6 (G2-2): the two stops and the saved roads, judged over the CURRENT bytes - the saved keys `requirement_coverage` and
    `refactoring_share` are shown, never believed. `found` = the findings of `check` (the share reads them). A road `stop` with no word of
    a person for its present digest is R6 (driver: the driver asks); a road `unknown` is R6 (conductor); a saved road other than the fresh
    one is R3 (driver: the keys are measures the driver rewrites). No saved key is no verdict: the fresh measure decides."""
    root = Path(root)
    pipeline = hooklib.read_json(root / "pipeline.json", None, kind=dict)
    policy, why = PC.grounding_policy()
    cov, result = coverage_of(root), share(data, policy, found, why)
    out: list = []
    for name, fresh in (("requirement coverage", cov), ("refactoring share", result)):
        if fresh["road"] == "unknown":
            out.append(Finding("R6", f"the {name} cannot be measured now ({fresh.get('reason') or 'no reason given'}), so a stop cannot be judged. "
                                     "Expected: a table, a register and a policy that can be read. Way on: the conductor repairs them (P22).", "conductor"))
    if cov["road"] == "stop":
        digest = coverage_digest(root, cov)
        if stop_word(pipeline, COVERAGE_STOP_BLOCK, digest) is None:
            out.append(Finding("R6", f"requirement coverage is {cov['implemented'] + cov['partial']} of {cov['n']} ({cov['percent']}%), below the "
                                     f"{policy['coverage_stop_below_percent'] if policy else 'configured'}% the policy sets, and no person's word stands "
                                     f"for the table as it is now{_saved_coverage(data.get('requirement_coverage'))}. Expected: the person's word "
                                     f"for exactly this state, the block `{COVERAGE_STOP_BLOCK} {digest}`. Way on: the conductor puts the question to "
                                     "the person and records the word for this block (window 2 is over; a word given for another state does not count).", "driver"))
    if result["road"] == "stop":
        digest = refactoring_digest(root, result)
        if stop_word(pipeline, REFACTORING_STOP_BLOCK, digest) is None:
            out.append(Finding("R6", f"the refactoring share is {result['percent']}% of the changed production lines, past the "
                                     f"{policy['stop_above_percent'] if policy else 'configured'}% the policy sets, and no person's word stands for "
                                     f"the diff as it is now. Expected: the person's word for exactly this state, the block "
                                     f"`{REFACTORING_STOP_BLOCK} {digest}`. Way on: the conductor puts the question to the person and records "
                                     "the word for this block (window 2 is over).", "driver"))
    for key, fresh in (("requirement_coverage", cov), ("refactoring_share", result)):
        saved = data.get(key)
        if saved is not None and (not isinstance(saved, dict) or saved.get("road") != fresh["road"]):
            was = saved.get("road") if isinstance(saved, dict) else "not a mapping"
            out.append(Finding("R3", f"`{key}` in work/grounding.yaml says road {was!r}, and the table as it is now gives {fresh['road']!r}. "
                                     "Expected: the key the last measure wrote for these bytes. Way on: the conductor measures again "
                                     "(grounding_table.py --share --task <ticket>); the table was changed after the measure.", "driver"))
    return out


# --- the S3 exit (G1-5): what `check` does not see and the plan, the claims and the regression section add -------------------------

MISSING_TABLE = ("work/grounding.yaml is missing while implementation_source is diff: this S3 was planned without a grounding table "
                 "(begun before this check, or the table is gone). Expected: the table the S3 preparation writes before window 1. "
                 "Way on: a person's word (waiver.py --task {task} --stage S3 --block \"<this line>\") or release of the dispatch; "
                 "the driver then prepares the table and runs window 1.")
OFF_DIFF_TABLE = ("work/grounding.yaml holds a grounding table while implementation_source is '{word}': the table is legal only on a "
                  "diff. Expected: no table (or the null-outcome form). Way on: the conductor settles which record is wrong (P22).")
TABLE_KEYS = ("hunks", "rows", "requirements", "blast_radius")
R7_REGRESSION = "R7-regression"
RECOMMENDED_REGRESSION = "## Recommended regression"
BLAST_TOKEN = re.compile(r"(?<![A-Za-z0-9])blast:B-(\d+)(?![A-Za-z0-9_])")
TS_ID = re.compile(r"^TS-\d+$")
# The two `what` words of R8 that are about the regression command: ONE spelling for the finding and the reader that picks it
# (the claim `every_area_that_matters_has_regression_or_a_gap`).
R8_NO_REGRESSION = "areas are matters: yes with neither the regression tests that defend them nor gap:<reason>"
R8_SHARED_NO_REGRESSION = "areas are on a shared path (or an unmeasured one) with no regression"


def _id_number(ident) -> int:
    found = ID_NUM.match(str(ident))
    return int(found.group(1)) if found else 0


def not_planned_of(root, dispatch_id: str = "", plan=None) -> list:
    """The `not_planned` entries (dicts) the S3 exit reads: the plan document's own list, plus the list of the strategist's handover form.
    ONE reader (AR-13). The form is `work/handoffs/<dispatch_id>.yaml` when the dispatch is named (the controller's accept), else the
    newest `work/handoffs/S3-*.yaml` (the exit detector knows the story, not the dispatch). A form that cannot be read adds nothing."""
    out = [e for e in (plan.get("not_planned") if isinstance(plan, dict) and isinstance(plan.get("not_planned"), list) else []) if isinstance(e, dict)]
    folder = Path(root) / "work" / "handoffs"
    if dispatch_id:
        form = folder / f"{dispatch_id}.yaml"
    else:
        found = [p for p in folder.glob("S3-*.yaml") if p.is_file()] if folder.is_dir() else []
        form = max(found, key=lambda p: (p.stat().st_mtime, p.name), default=None)
    if form is not None and form.is_file():
        try:
            listed = H.parse(form.read_bytes().decode("utf-8-sig")).data.get("not_planned")
        except (OSError, ValueError, UnicodeDecodeError):
            listed = None
        out += [e for e in (listed if isinstance(listed, list) else []) if isinstance(e, dict)]
    return out


def _plan_refs(plan_rows: list, not_planned: list) -> tuple:
    """`(named, ids)`: `named` = the K/B ids a plan row (`PC.grounding_refs`) or a `not_planned[].ref` names; `ids` = the row ids of the plan."""
    named, ids = set(), set()
    for row in plan_rows:
        if isinstance(row, dict) and isinstance(row.get("id"), str):
            ids.add(row["id"])
        refs = PC.grounding_refs(row)
        named.update(refs["K"] + refs["B"])
    for entry in not_planned:
        ref = entry.get("ref")
        if isinstance(ref, str) and re.fullmatch(r"[KB]-[1-9][0-9]*", ref.strip().strip("`").strip()):
            named.add(ref.strip().strip("`").strip())
    return named, ids


def _table_ids(data: dict) -> tuple:
    """`(risks, areas)`: `{K-n: hypothesis}` of `rows[].risks[]` and the areas (dicts) of `blast_radius.areas`, as the table holds them."""
    risks: dict = {}
    for row in _dicts(data.get("rows")):
        for risk in _dicts(row.get("risks")):
            if isinstance(risk.get("id"), str):
                risks.setdefault(risk["id"], str(risk.get("hypothesis") or ""))
    blast = data.get("blast_radius")
    return risks, [a for a in _dicts(blast.get("areas") if isinstance(blast, dict) else None) if isinstance(a.get("id"), str)]


def _area_label(area: dict) -> str:
    return f"{area['id']} ({str(area.get('key') or '')[:60]})"


def r7_findings(data: dict, plan_rows: list, not_planned: list) -> list:
    """R7 (plan exists): every `K-n` of `rows[].risks` and every area with `matters: yes` is named by a plan row (`PC.grounding_refs`) or by a
    `not_planned[].ref`; a plan reference the table does not hold, and an `add_tests: TS-n` no plan row carries, are R7 too. The entry of the
    role is enough (a person decides at gate A). Never reads a prefix `PC.grounding_refs` refuses."""
    named, ids = _plan_refs(plan_rows, not_planned)
    risks, areas = _table_ids(data)
    out: list = []
    owed = [f"{k} ({DV.one_line(h)[:50]})" for k, h in sorted(risks.items(), key=lambda kv: _id_number(kv[0])) if k not in named]
    owed += [_area_label(a) for a in sorted(areas, key=lambda a: _id_number(a["id"])) if a.get("matters") == "yes" and a["id"] not in named]
    if owed:
        _find(out, "R7", "role", "risks and areas that matter reach no plan row", owed,
              "a plan row's `risk_source_refs` entry (`grounding:K-n` / `blast:B-n`) in work/test-plan.json, or a `not_planned` entry with `ref` K-n / B-n.",
              "edit work/test-plan.json or the S3 form.")
    known = set(risks) | {a["id"] for a in areas}
    dangling = sorted((n for n in named if n not in known and n[0] in "KB"), key=_id_number)
    dangling = [f"{n} is named, and work/grounding.yaml does not hold it" for n in dangling]
    missing = [f"{_area_label(a)} names add_tests {a['add_tests'].strip()}, which no plan row carries as its id" for a in areas
               if isinstance(a.get("add_tests"), str) and TS_ID.match(a["add_tests"].strip()) and a["add_tests"].strip() not in ids]
    if dangling or missing:
        _find(out, "R7", "role", "plan references that point at nothing", dangling + missing,
              "references to ids the table holds and tests the plan carries.", "correct the reference in work/test-plan.json or the table.")
    return out


def _regression_text(root) -> list | None:
    """The lines of `## Recommended regression` in test-plan.md (`delivery_verdict.regression_lines`), None when the file or the heading is absent."""
    import delivery_verdict as DVD
    try:
        return DVD.regression_lines(C.read_text(C.artifact(Path(root), "test-plan.md")))
    except (OSError, ValueError):
        return None


def r7_regression_findings(root, data: dict) -> list:
    """R7-regression (F-16): an area with `matters: yes` whose `regression` names tests (not `gap:`) is named, as its own `blast:B-n` token, in the plan's
    `## Recommended regression` section - in any line of it (until the section has a form of its own, RG1-1). No section, or a section that
    only says `No regression:`, names nothing."""
    _, areas = _table_ids(data)
    matters = {"blast_radius": {"areas": [a for a in areas if a.get("matters") == "yes"]}}
    owed = [(ident, e["command"]) for e in PC.regression_from_blast(matters) if "command" in e for ident in e["area"].split(", ")]
    if not owed:
        return []
    lines = _regression_text(root)
    named = {f"B-{n}" for n in BLAST_TOKEN.findall("\n".join(lines or []))}
    by_id = {a["id"]: a for a in areas}
    items = [f"{_area_label(by_id[ident])}: expected `{DV.one_line(command)[:80]}`" for ident, command in owed if ident not in named]
    out: list = []
    if items:
        _find(out, R7_REGRESSION, "role", f"areas that matter are not named in the plan's {RECOMMENDED_REGRESSION} section", items,
              "each area with regression tests named there by its own token `blast:B-n`, on the item that names those tests.",
              f"write the {RECOMMENDED_REGRESSION} section of test-plan.md: one item per test path, signed `(blast:B-n)` with one token per area it defends.")
    return out


def exit_findings(root, plan_rows, not_planned) -> list:
    """The findings the S3 exit adds to the plan's own checks: ONE function for the controller's gate, the exit detector and the claims (FR-10).
    Reads only (FR-45). `plan_rows` None = no plan yet (R7 does not run). In order:
      a diff and no table -> R0 (conductor), nothing else is counted; off a diff: no file -> []; a table there -> G-0b;
      `check(root)` (R0..R5, R8); a table the reader refuses stops here with that one R0;
      the claims of `claim_projector.s3_claim_errors` (CL); R7 and R7-regression (diff, a plan); then R6 and the saved-road R3 (G2-2: the two
      stops and the saved measures, judged over the bytes as they are now)."""
    root = Path(root)
    world, _ = source_state(root)
    if world != "mismatch":
        doc, problem = PC.read_grounding(root)
        missing = bool(problem) and getattr(problem, "kind", "") == "missing"
        if world == "diff" and missing:
            return [Finding("R0", MISSING_TABLE.format(task=root.name), "conductor")]
        if world != "diff" and missing:
            return []
        if world != "diff" and doc is not None and any(k in doc.data for k in TABLE_KEYS):
            return [Finding("G-0b", OFF_DIFF_TABLE.format(word=world.split(":", 1)[1]), "conductor")]
    out = list(check(root))
    if world != "diff" or any(f.rule == "R0" for f in out):
        return out
    import claim_projector as CP
    seen = {f.text for f in out}
    for problem in CP.s3_claim_errors(root):
        if str(problem) not in seen:
            seen.add(str(problem))
            out.append(Finding("CL", str(problem), getattr(problem, "who", "conductor")))
    if isinstance(plan_rows, list):
        doc, _ = PC.read_grounding(root)
        out += r7_findings(doc.data, plan_rows, list(not_planned or []))
        out += r7_regression_findings(root, doc.data)
        out += r6_findings(root, doc.data, out)
    return out


def exit_line(finding) -> str:
    """One finding as the line a refusal carries: `[grounding <rule>] <text>` and the tail that names the person's word (FR-4)."""
    tail = "" if "waiver.py" in finding.text else f" {TAIL}"
    return DV.one_line(f"[grounding {finding.rule}] {finding.text}{tail}")


def role_exit_lines(root, plan_rows) -> list:
    """The lines the exit DETECTOR hands the ROLE: the findings whose `who` is the role, nothing the driver or the conductor owns (a finding
    that is not the role's neither closes the stage nor comes back to it as its work). Raises what `exit_findings` raises."""
    plan = None
    if isinstance(plan_rows, list):
        plan = {"rows": plan_rows}
    return [exit_line(f) for f in exit_findings(root, plan_rows, not_planned_of(root, "", plan)) if f.who == "role"]


def regression_findings(findings) -> list:
    """From `check`'s findings the R8 ones that are about the regression command (the claim reads them through here, never by their words)."""
    return [f for f in findings if f.rule == "R8" and any(w in f.text for w in (R8_NO_REGRESSION, R8_SHARED_NO_REGRESSION))]


def grounding_counts(root) -> dict | None:
    """The numbers of the S3 form's `grounding` section, as words: `hunks` ("3 of 8": hunks of the diff on disk that a labelled row names),
    `rows_cover` (rows with a label), `requirements_cover` (register lines with a state), and, when the table holds a `refactoring_share`,
    its `refactoring_percent` and `road`. `None` off a diff, or when the table cannot be read. Read-only; the form's fields are these, never typed."""
    root = Path(root)
    if source_state(root)[0] != "diff":
        return None
    doc, problem = PC.read_grounding(root)
    if doc is None:
        return None
    inp = gather(root)
    rows, lines = _dicts(doc.data.get("rows")), _dicts(doc.data.get("requirements"))
    need = [r for r in inp.register.ids if r not in inp.register.exempt] if inp.register.ok else []
    stated = {line.get("r") for line in lines if str(line.get("state") or "").strip()}
    out = {"hunks": f"{len(_covered_ids(inp, rows))} of {len(inp.hunks)}",
           "rows_cover": f"{sum(1 for r in rows if str(r.get('label') or '').strip())} of {len(rows)}",
           "requirements_cover": f"{sum(1 for r in need if r in stated)} of {len(need)}"}
    share = doc.data.get("refactoring_share")
    if isinstance(share, dict):
        out.update({name: str(share[key]) for name, key in (("refactoring_percent", "percent"), ("road", "road")) if share.get(key) not in (None, "")})
    return out


def blast_lines(root) -> list:
    """The `blast_radius` list of the S3 form: one line per area of the table (`B-n: path_kind ..., matters ..., regression ..., add_tests ...`)."""
    doc, _ = PC.read_grounding(Path(root))
    _, areas = _table_ids(doc.data) if doc is not None else ({}, [])
    return [f"{a['id']}: path_kind {a.get('path_kind') or '-'}, matters {a.get('matters') or '-'}, "
            f"regression {DV.one_line(str(a.get('regression') or '-'))[:80]}, add_tests {DV.one_line(str(a.get('add_tests') or '-'))[:40]}"
            for a in sorted(areas, key=lambda a: _id_number(a["id"]))]


def claim_view(root, rules=(), *, plan_rows=None, not_planned=None, regression=False) -> tuple:
    """`(True | False | None, text)` for a claim of the S3 form (FR-41: `None` = no verdict). `rules` = the finding rules the claim is about;
    `regression` = the R8 findings about the regression command instead. Decided by the gate's own function, no rule of its own."""
    root = Path(root)
    world, why = source_state(root)
    if world != "diff":
        return None, f"implementation_source is not diff here ({why or world}): no grounding table is judged"
    found = exit_findings(root, plan_rows, not_planned) if plan_rows is not None else check(root)
    broken = [f for f in found if f.rule in ("R0", "G-0b")]
    if broken:
        return None, f"the table cannot be judged: {DV.one_line(broken[0].text)[:200]}"
    mine = regression_findings(found) if regression else [f for f in found if f.rule in rules]
    if mine:
        return False, "; ".join(DV.one_line(f.text)[:200] for f in mine[:2])
    return True, "the grounding check finds nothing against it"


# --- the command line --------------------------------------------------------------------------------------------------------

def _cmd_skeleton_or_refresh(root: Path, refresh: bool, force: bool) -> list:
    path = table_path(root)
    inp = gather(root)
    _refuse_call(inp)
    doc, problem = PC.read_grounding(root)
    exists = path.is_file()
    if path.exists() and not exists:
        raise Refusal("grounding_table: work/grounding.yaml exists but is not a file. Expected: a file or nothing. Do: the conductor "
                      "removes it; nothing was written.")
    if not refresh and exists:
        raise Refusal("grounding_table: work/grounding.yaml already exists, and --skeleton never replaces it. Expected: a story with no "
                      "table yet. Do: --refresh --task <key> carries the existing marks to the current diff, and --refresh --force "
                      f"--task <key> rewrites a table that cannot be read ({FORCE_FACTS}); nothing was written.")
    if force and not refresh:
        raise Refusal("grounding_table: --force belongs to --refresh, which rewrites a table that cannot be read: "
                      f"{FORCE_FACTS}. Do: run --refresh --force --task <key>; nothing was written.")
    lines: list = []
    old = None
    if refresh and exists:
        if problem and not force:
            raise Refusal(f"grounding_table: {_sentence(problem)} Expected: a readable table to carry over. Do: the conductor repairs "
                          f"the file, or runs --refresh --force --task <key>, which writes a new table; {FORCE_FACTS}; "
                          "nothing was written.")
        old = doc.data if doc is not None else None
    if inp.world != "diff":
        new = null_table(inp)
        lines.append(f"grounding: null outcome written ({inp.world.split(':', 1)[1]})")
        if old is not None and old.get("implementation_source") != new["implementation_source"] and (old.get("rows") or old.get("requirements")):
            new, lines = switch_to_null(old, inp)
        elif old is not None and old.get("orphans"):
            new["orphans"] = old["orphans"]
    elif old is not None and isinstance(old.get("implementation_source"), str) and old["implementation_source"] != "diff":
        new = skeleton(inp)
        new["orphans"] = old.get("orphans") or []
        top = _max_number("G-", new["orphans"], old.get("rows"))              # a table of orphans only still advances the counter
        for n, row in enumerate(new["rows"], 1):
            row["id"] = f"G-{top + n}"
        lines.append("grounding: the source is diff again; the table is built new")
    elif old is not None:
        new, lines = refresh_table(old, inp)
    else:
        new = skeleton(inp)
    if refresh and exists and problem:
        new["orphans"] = keep_unreadable(path)
        lines.append(f"grounding: the table could not be read; a new one is written and {FORCE_FACTS} ({new['orphans'][0]['reason']})")
    for refusal in inp.refusals:
        lines.append(f"grounding: the diff reader refused part of {refusal['diff']} ({refusal['kind']}); --check names it")
    for d in inp.diffs:
        if d["implementation_commit"].startswith("unmeasured"):
            lines.append(f"grounding: {Path(d['path']).name}: implementation_commit {d['implementation_commit']}")
    write_yaml(path, new)
    if inp.world == "diff":
        blast = new.get("blast_radius") or {"index": {"state": "absent"}}
        lines.insert(0, f"grounding: wrote {path.name}: {len(new['hunks'])} hunks, {len(new['rows'])} rows, {len(new['requirements'])} "
                        f"requirement lines, {len(blast.get('areas') or [])} areas (blast radius index {blast['index'].get('state')})")
    return lines


def _run_check(root: Path) -> int:
    findings, ctx = check_report(root)
    for line in ctx:
        print(line)
    if not findings:
        print("OK: work/grounding.yaml satisfies the grounding check (R0-R5, R8)")
        return 0
    print(f"REJECT — {len(findings)} finding(s) in the grounding table:")
    for f in findings:
        print("- " + DV.one_line(f"[grounding {f.rule}] {f.text} {TAIL}"))
    return 1


def _share_line(result: dict) -> str:
    text = f"share: {result['percent']}% road {result['road']}" if result["percent"] != "n/a" else f"share: n/a road {result['road']}"
    if result["total"]:
        text += f" ({result['refactoring']} of {result['total']} changed production lines)"
    return text + (f" - {result['reason']}" if result["reason"] else "")


def _coverage_line(cov: dict) -> str:
    text = f"coverage: {cov['implemented'] + cov['partial']} of {cov['n']} requirements road {cov['road']}"
    return text + (f" ({cov['reading']})" if cov["reading"] else "") + (f" - {cov['reason']}" if cov["reason"] else "")


def _cmd_share(root: Path) -> list:
    """`--share`: measure and write TWO keys (`refactoring_share`, `requirement_coverage`) through `write_key`. Written only in the world
    `diff`, on a table the one reader reads; every other case is a printed line and an untouched file. It is a measure, not a detector:
    no REJECT, exit 0."""
    world, why = source_state(root)
    if world != "diff":
        return [f"share: not measured - {why or 'the story has no implementation diff (' + world + ')'}; nothing was written"]
    doc, problem = PC.read_grounding(root)
    if doc is None:
        return [f"share: road unknown - R0, {_sentence(problem)} Nothing was written (a measure is not written on a table that cannot be "
                "read)."]
    policy, policy_why = PC.grounding_policy()
    result = share(doc.data, policy, check(root), policy_why)
    write_key(root, "refactoring_share", result)
    cov = coverage_of(root)
    write_key(root, "requirement_coverage", cov)
    return [_share_line(result), _coverage_line(cov),
            f"share: wrote refactoring_share and requirement_coverage in {table_path(root).name}"]


def main(argv=None) -> int:
    try:
        import console_io
        console_io.utf8_stdio()
    except ImportError:
        pass
    ap = argparse.ArgumentParser(description="The grounding table by code (skeleton, refresh, check).")
    mode = ap.add_mutually_exclusive_group(required=True)
    for flag in ("--skeleton", "--refresh", "--check", "--share"):
        mode.add_argument(flag, action="store_true")
    ap.add_argument("--task", required=True, help="the story's ticket key")
    ap.add_argument("--force", action="store_true", help="with --refresh: rewrite a table that cannot be read (its old bytes are kept "
                    "beside the new table as grounding.unreadable-<sha8>.yaml and ONE orphan points at them)")
    args = ap.parse_args(argv)
    try:
        root = hooklib.story_root(args.task, "grounding_table")
        if args.check:
            return _run_check(root)
        if args.share:
            for line in _cmd_share(root):
                print(line)
            return 0
        for line in _cmd_skeleton_or_refresh(root, args.refresh, args.force):
            print(line)
        return 0
    except Refusal as refusal:
        print(refusal.text, file=sys.stderr)
    except TypeError as exc:
        print(f"grounding_table: a node of the table has a type this tool cannot handle: {_sentence(exc)} Expected: text, numbers, "
              "lists and mappings in the places the table form gives them. Do: the conductor repairs that node (--refresh --force "
              f"--task <key> rewrites the table; {FORCE_FACTS}); nothing was written.", file=sys.stderr)
    except (ValueError, OSError) as exc:
        print(f"grounding_table: {_sentence(exc)} Nothing was written (an existing table is as it was).", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
