"""The blast-radius index by code (G1-2, grounding/1): `work/blast-radius.json` - per changed file of the implementation diff (an area
`B-n`) the touched symbols, the callers (file:line), the tests and the path kind; what code could not measure says `unmeasured: <reason>`.

  blast_radius.py --task T                 make the file current for the diffs and the manifest on disk (built, or reused as it is)
  blast_radius.py --task T --rebuild       build and write regardless of freshness (`--force`: also when the old file cannot be read -
                                           its bytes stay beside the new file as `blast-radius.unreadable-<sha8>.json`)
  blast_radius.py --task T --json          compute and print, write NOTHING

Exit codes: 0 built / reused / the story has no implementation diff (`unmeasured` inside the file is content, not a failure); 2 a refused
call (stderr says who acts; nothing was written); 3 no such project or story (`hooklib.story_root`). The driver's S3 preparation runs
this FIRST, before `grounding_table.py --refresh`; the brief of an S3 window builds the file only when it is missing or stale.

ONE writer: `ensure` (the CLI and `brief_pack.build` call it); the table (`grounding_table`) reads the file and copies it whole.
The join "diff -> manifest entry -> recorded commit" is the table's (`GT.manifest_entry_for`, `GT.commit_value`), the checkout is
`HC.implementation_checkout`, the code is read from git OBJECTS of the recorded commit (never the working tree, never HEAD), the
test roots are the project's. Error direction (I2): the index errs ONLY toward a bigger radius - an extra caller, `shared_path`,
`unmeasured` - never toward "not touched", `additive` without proof, or "covered" without a site. Python only is parsed
(`ast`); another language gets its module-level name searched.
"""
import argparse
import ast
import hashlib
import json
import os
import re
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path, PurePosixPath
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))
import base_slice as BS  # noqa: E402
import diff_pass as DP  # noqa: E402
import grounding_table as GT  # noqa: E402
import handoff_check as HC  # noqa: E402
import hooklib  # noqa: E402
import planning_contract as PC  # noqa: E402
import repo_map as RM  # noqa: E402
import test_files as TF  # noqa: E402
import test_novelty as TN  # noqa: E402

SCHEMA = 1
BLAST_FILE = GT.BLAST_FILE
MAX_SITES_PER_SYMBOL = 25
MAX_SITES_PER_AREA = 60
INDEX_BUDGET_SECONDS = 240
RETRY_STATES = ("no_checkout", "commit_absent", "git_failed", "budget")      # a state the next preparation may measure
NOT_APPLICABLE = ("test", "docs", "generated")                                # the kinds the radius does not apply to
UNMEASURED = "unmeasured: "
NO_CHECKOUT = "no checkout of "                                               # the one reason of `implementation_checkout` that is not an unknown repo
DEF_RE = re.compile(r"^\s*(?:async\s+)?(?:def|class)\s+([^\W\d]\w*)")
TOKEN_RE = re.compile(r"\w+")
ID_RE = re.compile(r"^B-(\d+)$")
NUL = bytes([0])
BOM = chr(0xFEFF)                                                             # never a literal byte in this file (FR-29)
LONE_CR = chr(13)
SKIP_GLOB = re.compile(r"[*?\[\]\\:]")                                        # a skip folder name that would be a pathspec magic is not passed
_clock = time.monotonic                                                       # a test replaces it (the budget is a clock fact)


def _unmeasured(reason) -> str:
    return UNMEASURED + str(reason)


def _sha12(sha) -> str:
    return str(sha or "")[:12]


def _text_sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _one_line(text) -> str:
    return " ".join(str(text).split())


# --- the bytes of the story: shared by the freshness check and the build ----------------------------------------------------------

def _stamp(root: Path) -> SimpleNamespace:
    """`SimpleNamespace(diffs {name: sha256 | None}, manifest sha256 | None)`: what a built file must have been built from."""
    diffs = {}
    for path in GT.diff_files(root):
        try:
            diffs[path.name] = _text_sha(path.read_bytes())
        except OSError:
            diffs[path.name] = None
    manifest = root / "work" / "context-manifest.json"
    try:
        sha = _text_sha(manifest.read_bytes()) if manifest.is_file() else None
    except OSError:
        sha = _text_sha(b"unreadable")                                         # an unreadable manifest is a state of its own: a repair rebuilds
    return SimpleNamespace(diffs=diffs, manifest=sha)


def _read_prior(path: Path) -> tuple:
    """`(doc | None, problem)`: the existing file as a mapping with an `areas` list of `{id: B-n, key}` and `retired_ids`; `(None, "")`
    when there is no file, `(None, why)` when there is one and it cannot be read (F-5: its ids cannot be kept)."""
    if not path.exists():
        return None, ""
    doc = hooklib.read_json(path, None, kind=dict)
    if doc is None:
        return None, "it is not a JSON object in UTF-8"
    if not isinstance(doc.get("areas"), list):
        return None, "it has no `areas` list"
    for area in doc["areas"]:
        if not isinstance(area, dict) or not ID_RE.match(str(area.get("id", ""))) or not isinstance(area.get("key"), str):
            return None, "an area has no `B-<n>` id or no `key`"
    retired = doc.get("retired_ids", [])
    if not isinstance(retired, list) or not all(isinstance(i, str) and ID_RE.match(i) for i in retired):
        return None, "`retired_ids` is not a list of `B-<n>` ids"
    return doc, ""


def _fresh(prior: dict, stamp: SimpleNamespace, mode: str) -> bool:
    """The file was built from these diff bytes and this manifest, at this schema (and, in `prepare` mode, no repository is in a state
    a later preparation may measure)."""
    index = prior.get("index") if isinstance(prior.get("index"), dict) else {}
    if index.get("schema") != SCHEMA or index.get("manifest_sha256") != stamp.manifest:
        return False
    built = [d for d in index.get("diffs") or [] if isinstance(d, dict)]
    if len(built) != len(stamp.diffs) or {(Path(str(d.get("path", ""))).name, d.get("sha256")) for d in built} != set(stamp.diffs.items()):
        return False
    return not (mode == "prepare" and any(isinstance(r, dict) and r.get("state") in RETRY_STATES for r in index.get("repos") or []))


# --- stage 1: the join of diff, manifest, commit and checkout ---------------------------------------------------------------------

def _context(root: Path, project, cfg) -> SimpleNamespace:
    """Everything the stages read, once: the diff records (the table's join), the diff index, the project, the config, the clock."""
    ctx = SimpleNamespace(root=root, project=Path(project) if project else hooklib.project_root(), t0=_clock(), diffs=[], files=[],
                          by_diff={}, sites={}, root_sites={}, added={}, kinds={}, test_files=[], tests_ran=False, tests_reason="",
                          test_roots=[], candidates=[], tests_head=None, repos_by_suffix={})
    ctx.cfg = cfg if cfg is not None else hooklib.load_config()
    work = root / "work"
    manifest = hooklib.read_json(work / "context-manifest.json", None, kind=dict)
    entries = HC.implementation_entries(manifest) if manifest is not None else []
    found = DP.index(work)
    unreadable = {r["diff"]: r["text"] for r in found["refusals"] if r["kind"] == "unreadable"}
    ctx.stamp = _stamp(root)
    for path in GT.diff_files(root):
        name = path.name
        entry, why = GT.manifest_entry_for(name, entries)
        stem = name[:-len(".txt")] if name.endswith(".txt") else name
        sha = ctx.stamp.diffs.get(name)
        rec = SimpleNamespace(name=name, path=f"work/{name}", repo=stem[len("impl-diff"):].lstrip("-"), sha=sha, entry=entry,
                              entry_why=why, state="", reason="", checkout=None, head=None, search="", search_reason="",
                              commit=GT.commit_value(entry, name) if entry else _unmeasured(why),
                              unreadable=_one_line(unreadable[name]) if name in unreadable else ("" if sha is not None else f"{name} cannot be read"))
        rec.rid = str((entry or {}).get("repo_id") or (entry or {}).get("repo") or "").strip()
        ctx.diffs.append(rec)
    ctx.by_diff = {rec.name: rec for rec in ctx.diffs}
    ctx.repos_by_suffix = {rec.repo: rec for rec in ctx.diffs}
    ctx.files = [f for f in found["files"] if f["diff"] in ctx.by_diff]
    bundle = hooklib.read_json(work / "context-bundle.json", None, kind=dict)
    listed = bundle.get("existing_test_candidates") if bundle else None
    ctx.candidates = [c for c in listed if isinstance(c, dict)] if isinstance(listed, list) else []
    return ctx


def _spent(ctx) -> bool:
    return _clock() - ctx.t0 > INDEX_BUDGET_SECONDS


def _out_of_budget(ctx, rec) -> None:
    rec.state, rec.reason = "budget", f"the index time budget of {INDEX_BUDGET_SECONDS} s ran out before {rec.rid or rec.name}"


def _git_head(checkout):
    code, out = TN._git(checkout, ["rev-parse", "HEAD"])
    text = out.decode("ascii", "replace").strip() if code == 0 else ""
    return text if GT.COMMIT_RE.fullmatch(text) else None


def _classify(ctx, rec) -> None:
    """Set `rec.state` / `rec.reason` / `rec.checkout` / `rec.head`: the FIRST failing row of the join table wins."""
    rec.state, rec.reason = "match", ""
    if rec.unreadable:
        rec.state, rec.reason = "diff_unreadable", rec.unreadable
        return
    if rec.entry is None:
        rec.state, rec.reason = "unknown_repo", rec.entry_why
        return
    found, why = HC.implementation_checkout(rec.entry, ctx.cfg, ctx.project, rec.name)
    if found is None and not why.startswith(NO_CHECKOUT):
        rec.state, rec.reason = "unknown_repo", why
        return
    if not GT.COMMIT_RE.fullmatch(rec.commit):
        rec.state, rec.reason = "no_record", rec.commit[len(UNMEASURED):] if rec.commit.startswith(UNMEASURED) else rec.commit
        return
    if found is None:
        rec.state, rec.reason = "no_checkout", why
        return
    rec.checkout = found
    if _spent(ctx):
        _out_of_budget(ctx, rec)
        return
    code, out = TN._git(found, ["cat-file", "-t", rec.commit])
    if code is None:
        rec.state, rec.reason = "git_failed", BS._timeout_text(found)
    elif code not in (0, 128):
        rec.state, rec.reason = "git_failed", f"git cat-file exited {code} in {found}"
    else:
        rec.head = _git_head(found)
        if code != 0 or out.strip() != b"commit":
            rec.state, rec.reason = "commit_absent", f"commit {_sha12(rec.commit)} is not in {found} (HEAD {_sha12(rec.head) or 'unknown'})"


def _join(ctx) -> None:
    for rec in ctx.diffs:
        _classify(ctx, rec)


# --- stage 2: the symbols of each changed file ------------------------------------------------------------------------------------

def _module_name(path: str) -> str:
    """The module-level name of a file: its stem, a package's `__init__.py` by the folder's name (m-2)."""
    p = PurePosixPath(path)
    return (p.parent.name or p.stem) if p.stem == "__init__" else p.stem


def _change(f: dict) -> str:
    """added | modified | deleted | renamed | mode | binary | refused | uncertain: what the diff says happened to the file."""
    if f["path_uncertain"]:
        return "uncertain"
    if f["refused"]:
        return "refused"
    if f["new"]:
        return "added"
    if f["deleted"]:
        return "deleted"
    pseudo = next((h.get("pseudo") for h in f["hunks"] if h.get("pseudo")), "")
    if pseudo in ("binary", "mode"):
        return pseudo
    if pseudo in ("rename", "copy") or BS._old_path(f):
        return "renamed"
    return "uncertain" if pseudo == "unknown" else "modified"


def _kind(ctx, path: str) -> str:
    """`TF.file_kind(path)`, once per path (a verdict costs milliseconds and a search can name thousands of sites)."""
    if path not in ctx.kinds:
        ctx.kinds[path] = TF.file_kind(path)
    return ctx.kinds[path]


def _new_area(ctx, f: dict) -> SimpleNamespace:
    """One area per DP file record (I5): the public part `out`, and what the stages need besides."""
    kind = _kind(ctx, f["path"])
    a = SimpleNamespace(f=f, rec=ctx.by_diff[f["diff"]], kind=kind, change=_change(f), names=[], own=set(), gap="")
    real = [h for h in f["hunks"] if not h.get("pseudo")]
    a.added = {n for h in real for n, sign, _text in h["lines"] if sign == "+"}
    a.pure_rename = a.change == "renamed" and not real
    a.unread = a.change in ("refused", "uncertain")                           # the diff cannot say what was changed in this file
    a.na = kind in NOT_APPLICABLE and not a.unread                           # the radius does not apply (tests, docs, generated)
    ext = PurePosixPath(f["path"]).suffix.lstrip(".").lower()
    a.python = ext == "py"
    a.out = {"id": "", "key": f"{f['repo']}:{f['path']}",
             "touched": {"repo": f["repo"], "file": f["path"], "kind": kind, "change": a.change, "lines": f["added"] + f["removed"],
                         "hunks": [{"diff": f["diff"], "old_start": h.get("old_start", 0), "new_start": h["new_start"]} for h in f["hunks"]],
                         "symbols": []},
             "language": "" if a.python else ext, "callers": [], "callers_more": 0, "truncated": "no", "same_name_defs": [], "tests": [],
             "tests_gap": "", "suggested_tests": [], "path_kind": "", "path_kind_why": ""}
    return a


def _areas(ctx) -> list:
    """Every DP file record, in DP order. A second record of one key (one file twice in a diff) keeps its own area: key `...#2`."""
    areas, seen = [], {}
    for f in ctx.files:
        a = _new_area(ctx, f)
        key = a.out["key"]
        seen[key] = seen.get(key, 0) + 1
        if seen[key] > 1:
            a.out["key"] = f"{key}#{seen[key]}"
        ctx.added.setdefault((f["repo"], f["path"]), set()).update(a.added)
        areas.append(a)
    return areas


def _module_symbol(a) -> dict:
    status = {"added": "new", "deleted": "deleted"}.get(a.change, "moved" if a.pure_rename else "modified")
    name = _module_name(a.f["path"])
    return {"name": name, "qual": name, "status": status, "level": "module"}


def _old_module(a, symbols) -> list:
    """A renamed file keeps its OLD module name as a second module-level symbol: the importers of the old name are the callers that break."""
    if a.change != "renamed" or a.na or a.unread:
        return []
    old = BS._old_path(a.f)
    name = _module_name(old)
    if not old or not name or any(s["name"] == name and s["level"] == "module" for s in symbols):
        return []
    return [{"name": name, "qual": name, "status": "moved", "level": "module"}]


def _def_nodes(tree) -> list:
    """Every def / class of a module: span from the FIRST DECORATOR to the last line (m-1), the dotted name, the class around it."""
    out = []

    def visit(node, prefix, cls):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                start = min([child.lineno] + [d.lineno for d in child.decorator_list])
                qual = prefix + child.name
                out.append(SimpleNamespace(start=start, end=child.end_lineno or child.lineno, qual=qual, name=child.name,
                                           line=child.lineno, cls=cls, depth=prefix.count(".")))
                visit(child, qual + ".", qual if isinstance(child, ast.ClassDef) else cls)
            else:
                visit(child, prefix, cls)
    visit(tree, "", "")
    return out


def _parse(lines) -> tuple:
    """`(tree, "")` or `(None, why)`. A lone CR would be a line break for `ast` and none for git (m-10): refused, not guessed."""
    if lines is None:
        return None, "is not UTF-8 text"
    if any(LONE_CR in line for line in lines):
        return None, "holds a lone CR line break"
    try:
        return ast.parse("\n".join(lines).lstrip(BOM)), ""
    except (SyntaxError, ValueError, RecursionError, MemoryError) as exc:
        return None, f"cannot be parsed as Python ({type(exc).__name__})"


def _symbols_from_tree(a, nodes) -> list:
    """The symbols a modified Python file's diff touches. A changed new-side line -> the innermost def / class; a removed line with no
    added one -> the symbols at the deletion point; a removed `def` / `class` whose name is gone from the new tree -> `deleted`.
    The hunk header is never read (it names the PREVIOUS function when the change sits before the next one)."""
    names = {n.name for n in nodes}
    by_qual = {n.qual: n for n in nodes}
    removed = [(n, t) for h in a.f["hunks"] if not h.get("pseudo") for n, sign, t in h["lines"] if sign == "-"]
    gone = {m.group(1) for _n, t in removed for m in [DEF_RE.match(t)] if m and m.group(1) not in names}
    cache, found, module = {}, {}, [False]

    def at(line):
        if line not in cache:
            held = [n for n in nodes if n.start <= line <= n.end]
            cache[line] = max(held, key=lambda n: n.start) if held else None
        return cache[line]

    def add(node):
        if node is None:
            module[0] = True
            return
        if node.name.startswith("__") and node.name.endswith("__") and node.cls:
            node = by_qual.get(node.cls, node)                              # a dunder method is searched as its class
        status = "new" if node.line in a.added and node.name not in gone else "modified"
        found.setdefault(node.qual, {"name": node.name, "qual": node.qual, "status": status, "level": "symbol", "_at": node.start})
    for line in sorted(a.added):
        add(at(line))
    runs = {}
    for n, text in removed:
        runs.setdefault(n, []).append(text)
    for n in sorted(runs):
        if n in a.added or any((m := DEF_RE.match(t)) and m.group(1) in gone for t in runs[n]):
            continue                                                         # an added line at the same place covers it; a deleted def adds no neighbour
        around = {id(at(k)): at(k) for k in (n - 1, n) if k >= 1 and at(k) is not None}
        for node in around.values():
            add(node)
        module[0] = module[0] or not around
    out = [{k: v for k, v in s.items() if k != "_at"} for s in sorted(found.values(), key=lambda s: s["_at"])]
    out += [{"name": g, "qual": g, "status": "deleted", "level": "symbol"} for g in sorted(gone)]
    if module[0] or not out:
        out.append(_module_symbol(a))
    a.own = {(n.name, n.line) for n in nodes}
    return out


def _side_lines(a, side: str):
    """The whole text of a NEW or DELETED file from the diff alone (the `new` / `old` side of its hunks), or None."""
    views, problem = BS._views(a.f, a.f["path"])
    return None if problem else [line for v in views for line in v[side]]


def _top_level(a, lines, status) -> tuple:
    """`(symbols, gap)` of a whole new / deleted Python file: its top-level defs and classes, then the module's name."""
    tree, why = _parse(lines)
    if tree is None:
        return [_module_symbol(a)], f"{a.f['path']} {why} in the diff"
    nodes = [n for n in _def_nodes(tree) if n.depth == 0]
    a.own = {(n.name, n.line) for n in nodes}
    return [{"name": n.name, "qual": n.qual, "status": status, "level": "symbol"} for n in nodes] + [_module_symbol(a)], ""


def _verify(a, lines) -> str:
    """"" when the blob's lines are the diff's new side on every hunk, else why not (I2: a blob that is not the diff's file is not read)."""
    views, problem = BS._views(a.f, a.f["path"])
    if problem:
        return problem
    for v in views:
        start = v["new_start"] - 1 if v["new_count"] > 0 else v["new_start"]
        if v["new_count"] > 0 and lines[start:start + v["new_count"]] != v["new"]:
            return f"does not match the diff at line {v['new_start']}"
    return ""


def _symbols_of(a, blobs) -> tuple:
    """`(symbols, gap)`: the symbols of one area, or - with `gap` set - ONE module-level symbol (to search) and the reason the rest is
    unmeasured. A new or deleted file is read from the diff, no checkout; a modified Python file from its blob at the commit."""
    path = a.f["path"]
    if a.unread:
        return [], f"{path} is {a.change} in the diff and cannot be read from it"
    if a.na:
        return [], ""
    mod = [_module_symbol(a)]
    if a.pure_rename or a.change in ("mode", "binary") or not a.python:
        return mod, ""
    if a.change in ("added", "deleted"):
        lines = _side_lines(a, "new" if a.change == "added" else "old")
        if lines is None:
            return mod, f"{path} has no readable body in the diff"
        return _top_level(a, lines, "new" if a.change == "added" else "deleted")
    if a.rec.state != "match":
        return mod, a.rec.reason
    if BS._repo_path(path) != path:
        return mod, f"{path} is not a repository-relative path"
    got, problem = blobs.get(a.rec.name, ({}, "no blob was asked for"))
    if problem:
        return mod, problem
    spec = f"{a.rec.commit}:{path}"
    if spec not in got:                                                      # never say "not a file of the commit" about a file nobody asked for
        return mod, "no blob was asked for"
    data = got[spec]
    if data is None or data is False:
        return mod, f"{path} is not a file of commit {_sha12(a.rec.commit)}"
    lines = BS._lines(data)
    tree, why = _parse(lines)
    why = why or _verify(a, lines)
    if why:
        return mod, f"{path} {why} at {_sha12(a.rec.commit)}"
    return _symbols_from_tree(a, _def_nodes(tree)), ""


def _symbols(ctx, areas) -> None:
    """Fill `touched.symbols` and the search names of every area. ONE `cat-file --batch` per repository (the modified Python files)."""
    want = {}
    for a in areas:
        body = a.change == "modified" or (a.change == "renamed" and not a.pure_rename)     # a renamed file WITH hunks is read at its new path
        if not (a.unread or a.na) and a.python and body and a.rec.state == "match" and BS._repo_path(a.f["path"]) == a.f["path"]:
            want.setdefault(a.rec.name, []).append(a.f["path"])
    blobs = {}
    for name, paths in want.items():
        rec = ctx.by_diff[name]
        if _spent(ctx):
            _out_of_budget(ctx, rec)
            continue
        blobs[name] = BS._blobs(rec.checkout, [f"{rec.commit}:{p}" for p in paths])
    for a in areas:
        symbols, a.gap = _symbols_of(a, blobs)
        symbols = symbols + _old_module(a, symbols)
        a.out["touched"]["symbols"] = _unmeasured(a.gap) if a.gap else symbols
        a.names = list(dict.fromkeys([s["name"] for s in symbols if s["level"] == "symbol"] + [s["name"] for s in symbols if s["level"] == "module"]))
        a.symbols = symbols


# --- stage 3: ONE search per repository -------------------------------------------------------------------------------------------

def _attribute(text: str, names, strict: bool) -> list:
    """The names (of `names`) a line of text mentions: its identifier tokens against the set. `strict` stops there (a test needs the
    NAME); otherwise a name with a character outside the identifier set is looked for as a substring (errs to a caller, never to none)."""
    hit = sorted(set(TOKEN_RE.findall(text)) & names)
    if hit or strict:
        return hit
    return sorted(n for n in names if n in text)


def _grep(rec, names) -> tuple:
    """`(sites, "")` or `(None, reason)`: ONE `git grep` of every name over the OBJECT of the recorded commit. `-z` makes a `:` in a path
    safe; a timeout drops the partial output; an exit other than 0 / 1 is a reason by name."""
    skip = [d for d in sorted(set(RM.SKIP_DIRS) | RM._extra_skip_dirs()) if d and not SKIP_GLOB.search(d)]
    pathspec = ["--", ".", *[f":(exclude,glob)**/{d}/**" for d in skip]]
    fd, name = tempfile.mkstemp(prefix="blast-radius-", suffix=".txt")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(("\n".join(names) + "\n").encode("utf-8"))
        code, out = TN._git(rec.checkout, ["-c", "core.quotepath=off", "grep", "-z", "-n", "-I", "-w", "-F", "-f", name, rec.commit, *pathspec])
    finally:
        try:
            os.unlink(name)
        except OSError:
            pass
    if code is None:
        return None, BS._timeout_text(rec.checkout)
    if code == 1:
        return [], ""
    if code != 0:
        return None, f"git grep exited {code} in {rec.checkout}"
    sites, prefix = [], (rec.commit + ":").encode("ascii")
    for raw in out.split(b"\n"):
        if not raw:
            continue
        parts = raw.split(NUL, 2)
        if len(parts) != 3 or not parts[0].startswith(prefix) or not parts[1].isdigit():
            return None, f"git grep answered a line this reader does not know in {rec.checkout}"
        sites.append((parts[0][len(prefix):].decode("utf-8", "replace"), int(parts[1]), parts[2].decode("utf-8", "replace")))
    return sites, ""


def _file_sites(ctx, rec, raw, nameset) -> None:
    """Sort the sites of one repository's search into callers / tests / same-name definitions, per name."""
    for path, line, text in raw:
        kind = _kind(ctx, path)
        made = DEF_RE.match(text) if path.endswith(".py") else None
        defined = made.group(1) if made else ""
        for name in _attribute(text, nameset, strict=kind == "test"):
            bucket = ctx.sites.setdefault(name, SimpleNamespace(callers=set(), tests=set(), defs=set()))
            site = (rec.repo, path, line)
            (bucket.defs if name == defined else bucket.tests if kind == "test" else bucket.callers).add(site)


def _search(ctx, names) -> None:
    nameset = set(names)
    for rec in ctx.diffs:
        rec.search = ""
        if rec.state != "match":
            rec.search_reason = rec.reason
        elif not names:
            rec.search_reason = "no symbol name to search"
        elif _spent(ctx):
            _out_of_budget(ctx, rec)
            rec.search_reason = rec.reason
        else:
            raw, why = _grep(rec, names)
            if raw is None:
                rec.state, rec.reason, rec.search_reason = "git_failed", why, why
            else:
                rec.search = "ok"
                _file_sites(ctx, rec, raw, nameset)


# --- stage 4: the tests of the project's test roots -------------------------------------------------------------------------------

def _inside(path: Path, folder: Path) -> bool:
    try:
        return path.is_relative_to(folder.resolve())
    except (OSError, ValueError):
        return False


def _scan_tests(ctx, names) -> None:
    """Sites of the names in the project's TEST ROOTS (the working tree; the files `RM._is_test_file` accepts, strict name match). A file
    under a checkout whose commit was searched is the commit's (m-3). `tests_ran` False says why in `tests_reason`; sites found stay."""
    roots = RM.test_roots(ctx.cfg, ctx.project)
    ctx.test_roots = [RM._rel(r, ctx.project) for r in roots]
    missing = [r for r in roots if not r.is_dir()]
    if missing:
        ctx.tests_reason = f"the test root {RM._rel(missing[0], ctx.project)} is not a folder"
        return
    ctx.tests_ran = True
    ctx.tests_head = _git_head(ctx.project)
    if not names:
        return
    files = [p for root in roots for p in RM._walk(root)]
    ctx.test_files = files
    searched = [rec.checkout for rec in ctx.diffs if rec.search == "ok"]
    nameset = set(names)
    rx = re.compile("|".join(re.escape(n) for n in sorted(nameset, key=len, reverse=True)))
    for path in files:
        if _spent(ctx):
            ctx.tests_ran, ctx.tests_reason = False, f"the index time budget of {INDEX_BUDGET_SECONDS} s ran out in the test roots"
            return
        if any(_inside(path, c) for c in searched):
            continue
        try:
            text = path.read_bytes().decode("utf-8", "replace")
        except OSError:
            ctx.tests_ran, ctx.tests_reason = False, f"the test file {RM._rel(path, ctx.project)} cannot be read"
            return
        if not rx.search(text) or not RM._is_test_file(path, ctx.cfg, ctx.project):
            continue
        ref = RM._rel(path, ctx.project)
        for number, line in enumerate(text.split("\n"), 1):
            if rx.search(line):
                for name in _attribute(line, nameset, strict=True):
                    ctx.root_sites.setdefault(name, set()).add((ref, number))


# --- stage 5: callers, tests and the kind of every area ---------------------------------------------------------------------------

def _callers(ctx, a) -> None:
    """The callers of a measured area, capped (25 per symbol, 60 per area, round-robin, symbol-level names first)."""
    out, lists, total, defs = a.out, [], set(), set()
    for name in a.names:
        bucket = ctx.sites.get(name)
        full = sorted(bucket.callers) if bucket else []
        defs |= {s for s in (bucket.defs if bucket else set()) if not (s[0] == a.f["repo"] and s[1] == a.f["path"] and (name, s[2]) in a.own)}
        total |= set(full)
        lists.append((name, full[:MAX_SITES_PER_SYMBOL], len(full) - MAX_SITES_PER_SYMBOL))
    picked, seen, depth = [], set(), 0
    while len(picked) < MAX_SITES_PER_AREA and any(depth < len(shown) for _n, shown, _m in lists):
        for name, shown, _more in lists:
            if depth < len(shown) and len(picked) < MAX_SITES_PER_AREA and shown[depth] not in seen:
                seen.add(shown[depth])
                picked.append((name, shown[depth]))
        depth += 1
    out["callers"] = [{"file": s[1], "line": s[2], "symbol": name, "repo": s[0],
                       "in_diff": "added" if s[2] in ctx.added.get((s[0], s[1]), ()) else "no"} for name, s in sorted(picked, key=lambda p: p[1][1:])]
    out["callers_more"] = len(total) - len(picked)
    more = {name: m for name, _shown, m in lists if m > 0}
    for symbol in a.symbols:
        if more.get(symbol["name"]):
            symbol["more"] = more[symbol["name"]]
    out["truncated"] = "yes" if out["callers_more"] > 0 or more else "no"
    out["same_name_defs"] = [{"file": s[1], "line": s[2]} for s in sorted(defs, key=lambda s: s[1:])]


def _candidate(ctx, ref, repo_id, rel):
    """The bundle candidate (`work/context-bundle.json` `existing_test_candidates`) a test site belongs to: `(repo, path)` equal, or the
    project-relative path equal / `<repo>/<path>`; `None` when no candidate names it."""
    for cand in ctx.candidates:
        path, repo = str(cand.get("path") or ""), str(cand.get("repo") or "")
        if path and ((path == ref and repo == repo_id) or (rel and (path == rel or f"{repo}/{path}" == rel))):
            return cand
    return None


def _tests(ctx, a, gap: str) -> None:
    """`tests` (sites only: a test needs a found site) and `tests_gap` (every part that did not run, by name)."""
    out, found = a.out, {}
    for name in a.names:
        if not gap:
            for repo, path, line in sorted(ctx.sites.get(name, SimpleNamespace(tests=())).tests):
                holder = ctx.repos_by_suffix.get(repo)
                rel = None
                if holder is not None and holder.checkout is not None:
                    try:
                        rel = (Path(os.path.relpath(holder.checkout, ctx.project)) / path).as_posix()
                    except ValueError:
                        rel = None
                found.setdefault((path, line), (name, "repo_scan", holder.rid if holder else "", rel))
        for ref, line in sorted(ctx.root_sites.get(name, ())):
            found.setdefault((ref, line), (name, "test_root", "", ref))
    reasons = [gap] if gap else []
    if not ctx.tests_ran:
        reasons.append(ctx.tests_reason)
    rows = []
    for (ref, line), (name, source, repo_id, rel) in sorted(found.items()):
        cand = _candidate(ctx, ref, repo_id, rel)
        rows.append({"ref": ref, "line": line, "symbol": name, "source": "bundle" if cand else source,
                     "candidate_id": str(cand.get("candidate_id") or "") if cand else ""})
    out["tests_gap"] = "; ".join(reasons)
    out["tests"] = rows if rows else (_unmeasured(out["tests_gap"]) if reasons else [])


def _suggest(ctx, a) -> list:
    """`suggested_tests`: the test files of the roots whose PATH names the module (advice, cap 6; nouns are not used)."""
    stem = _module_name(a.f["path"]).lower()
    if a.na or a.unread or not stem or not ctx.test_files:
        return []
    near = [p for p in ctx.test_files if stem in RM._rel(p, ctx.project).lower()]
    if not near:
        return []
    found = RM.area_tests(near, _module_name(a.f["path"]), {}, ctx.project, lambda p: RM._is_test_file(p, ctx.cfg, ctx.project))
    return [{"path": row["path"], "matched_by": row["matched_by"]} for row in found]


def _path_kind(ctx, a, gap: str) -> None:
    """`additive` ONLY with proof (every symbol new, no caller outside the added lines, nothing unmeasured or truncated); a doubt is
    `shared_path` with its reason (spec 2.1.6). A doc, a test and a generated file are `not_applicable` by KIND in every repository state
    (a kind is known from the path, no git needed; `unmeasured` is reserved for code - an unmeasured code file never reads as measured)."""
    out, symbols = a.out, a.out["touched"]["symbols"]
    if a.na:
        out["path_kind"], out["path_kind_why"] = "not_applicable", ""
        return
    outside = isinstance(out["callers"], list) and any(c["in_diff"] != "added" for c in out["callers"])
    listed = symbols if isinstance(symbols, list) else []
    if gap or a.rec.state != "match" or a.unread or isinstance(out["callers"], str) or isinstance(symbols, str) or out["tests_gap"]:
        why = "unmeasured"
    elif a.change == "deleted" or any(s["status"] == "deleted" for s in listed):
        why = "deleted"
    elif a.pure_rename or (listed and all(s["status"] == "moved" for s in listed)):
        why = "moved"
    elif out["truncated"] == "yes":
        why = "truncated"
    elif outside:
        why = "callers_found"
    elif a.change == "added" or (listed and all(s["status"] == "new" for s in listed)):
        out["path_kind"], out["path_kind_why"] = "additive", "new_no_outside_caller"
        return
    else:
        why = "modified_existing"
    out["path_kind"], out["path_kind_why"] = "shared_path", why


def _finish(ctx, a) -> None:
    out, rec = a.out, a.rec
    gap = a.gap if a.unread else "" if a.na else rec.reason if rec.state != "match" else rec.search_reason if rec.search != "ok" else ""
    if gap:
        out["callers"] = _unmeasured(gap)
    elif not a.na:
        _callers(ctx, a)
    if a.na:                                                                 # by FILE KIND, in every repository state (t-1190 L-2 F-A)
        out["tests"], out["tests_gap"] = [], ""
    else:
        _tests(ctx, a, gap)
    out["suggested_tests"] = _suggest(ctx, a)
    _path_kind(ctx, a, gap)


# --- stage 6: the ids, the document ------------------------------------------------------------------------------------------------

def _number(areas, prior, floor: int) -> list:
    """`B-n` by key (I6): an old key keeps its id, a new key gets `max + 1` over the prior ids AND `retired_ids` (and `floor`), a key that
    left is retired for good. Returns the new `retired_ids`."""
    old = {a["key"]: a["id"] for a in (prior or {}).get("areas", [])}
    retired = list((prior or {}).get("retired_ids", []))
    top = max([floor] + [int(ID_RE.match(i).group(1)) for i in list(old.values()) + retired])
    for a in areas:
        ident = old.get(a.out["key"])
        if ident is None:
            top += 1
            ident = f"B-{top}"
        a.out["id"] = ident
    keys = {a.out["key"] for a in areas}
    retired += [ident for key, ident in old.items() if key not in keys and ident not in retired]
    return retired


def _checkout_text(ctx, rec):
    if rec.checkout is None:
        return None
    try:
        return Path(os.path.relpath(rec.checkout, ctx.project)).as_posix()
    except ValueError:
        return rec.checkout.name


def _document(ctx, areas, retired, manifest_sha) -> dict:
    return {"index": {"schema": SCHEMA, "state": "built", "built_at": datetime.now().isoformat(timespec="seconds"),
                      "budget_seconds": INDEX_BUDGET_SECONDS,
                      "diffs": [{"path": r.path, "sha256": r.sha, "state": "unreadable" if r.unreadable else "read", "reason": r.unreadable}
                                for r in ctx.diffs],
                      "manifest_sha256": manifest_sha, "test_roots": ctx.test_roots, "tests_repo_head": ctx.tests_head,
                      "repos": [{"repo": r.repo, "diff": r.name, "id": r.rid, "checkout": _checkout_text(ctx, r), "head": r.head,
                                 "state": r.state, "reason": r.reason} for r in ctx.diffs]},
            "areas": [a.out for a in areas], "retired_ids": retired}


def build(task_root, prior=None, *, project=None, cfg=None, floor: int = 0) -> dict:
    """The document for the diffs and the manifest on disk. `prior` (the existing file, read) keeps the ids; `floor` is the highest
    `B-n` a forced rebuild must number above. Writes nothing."""
    ctx = _context(Path(task_root), project, cfg)
    _join(ctx)
    areas = _areas(ctx)
    _symbols(ctx, areas)
    names = list(dict.fromkeys(n for a in areas for n in a.names))
    _search(ctx, names)
    _scan_tests(ctx, names)
    for a in areas:
        _finish(ctx, a)
    retired = _number(areas, prior, floor)
    return _document(ctx, areas, retired, ctx.stamp.manifest)


# --- the one writer ---------------------------------------------------------------------------------------------------------------

def _table_floor(root: Path) -> int:
    """The highest `B-n` the grounding table knows (its areas and the orphaned ones), for a forced rebuild (F-5)."""
    doc, _problem = PC.read_grounding(root)
    if doc is None:
        return 0
    blast = doc.data.get("blast_radius")
    areas = blast.get("areas") if isinstance(blast, dict) else []
    orphans = [o for o in doc.data.get("orphans") or [] if isinstance(o, dict) and o.get("was") == "area"]
    return GT._max_number("B-", areas, orphans)


def _unreadable_refusal(problem: str) -> GT.Refusal:
    return GT.Refusal(f"blast_radius: work/{BLAST_FILE} cannot be read ({problem}), so its area ids cannot be kept. Expected: a readable "
                      f"index, or a rebuild that numbers above the table's highest B-n. Do: the conductor runs `blast_radius.py --task "
                      f"<key> --rebuild --force` (the old bytes stay beside the new file as blast-radius.unreadable-<sha8>.json); "
                      "nothing was written.")


def _old_bytes(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except OSError:
        return b""


def _write(path: Path, doc: dict, keep: bytes = b"") -> None:
    """tmp file beside the target, then `os.replace`: a reader sees the old file or the new one whole. `keep`: the old bytes of a file
    that could not be read, set aside first."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if keep:
        path.with_name(f"blast-radius.unreadable-{_text_sha(keep)[:8]}.json").write_bytes(keep)
    tmp = path.with_name(path.name + f".tmp-{os.getpid()}")
    try:
        tmp.write_bytes((json.dumps(doc, ensure_ascii=False, indent=1) + "\n").encode("utf-8", "replace"))
        os.replace(tmp, path)
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass


def _off_diff(root: Path) -> bool:
    """True for a story with no implementation diff; raises the ONE refusal when the recorded source and the diffs on disk disagree.
    `ensure` and `--json` (`_compute_only`) both ask this, so a dry run refuses with the words the real call refuses with."""
    world, why = GT.source_state(root)
    if world == "mismatch":
        raise GT.Refusal(f"blast_radius: {why}. Expected: implementation_source `diff` when a diff is on disk, and a diff only when the "
                         "source is `diff`. Do: S1 records the source again (stage_done --set implementation_source=...); nothing was written.")
    return world.startswith("off_diff")


def ensure(task_root, *, mode: str = "prepare", write: bool = True, rebuild: bool = False, force: bool = False, project=None, cfg=None) -> tuple:
    """`(doc | None, how)`: make `work/blast-radius.json` current - THE writer. `how`: `built`, `reused` (fresh: same diff and manifest
    bytes, same schema, and in `prepare` mode no repository left unmeasured by a fixable cause: the driver's preparation retries
    those, the brief's `link` mode never does), `off_diff` (the story has no implementation diff: nothing built, a file on disk is
    untouched), and with `write=False` also `absent` / `stale` (nothing is built then). `rebuild` builds regardless; `force` lets a
    rebuild replace a file that cannot be read. Raises `GT.Refusal` for a source and diffs that disagree, and for an unreadable old
    file without `force`."""
    root = Path(task_root)
    if _off_diff(root):
        return None, "off_diff"
    path = root / "work" / BLAST_FILE
    prior, problem = _read_prior(path)
    stamp = _stamp(root)
    if prior is not None and not rebuild and _fresh(prior, stamp, mode):
        return prior, "reused"
    if not write:
        return None, "absent" if not path.exists() else "stale"
    if problem and not force:
        raise _unreadable_refusal(problem)
    doc = build(root, prior, project=project, cfg=cfg, floor=_table_floor(root) if problem else 0)
    _write(path, doc, _old_bytes(path) if problem else b"")
    return doc, "built"


def summary(doc: dict) -> SimpleNamespace:
    """`SimpleNamespace(areas, repos, unmeasured, first)`: the counts of a document and the first reason anything is unmeasured."""
    areas = doc.get("areas") or []
    repos = (doc.get("index") or {}).get("repos") or []
    open_areas = [a for a in areas if a.get("path_kind_why") == "unmeasured"]
    first = next((r["reason"] for r in repos if r.get("state") != "match" and r.get("reason")), "")
    for a in open_areas:
        for field in (a.get("callers"), (a.get("touched") or {}).get("symbols"), a.get("tests_gap")):
            if not first and isinstance(field, str) and field:
                first = field[len(UNMEASURED):] if field.startswith(UNMEASURED) else field
    return SimpleNamespace(areas=len(areas), repos=len(repos), unmeasured=len(open_areas), first=_one_line(first))


def main(argv=None) -> int:
    try:
        import console_io
        console_io.utf8_stdio()
    except ImportError:
        pass
    ap = argparse.ArgumentParser(description="The blast-radius index of the implementation diff (work/blast-radius.json).")
    ap.add_argument("--task", required=True, help="the story's ticket key")
    ap.add_argument("--rebuild", action="store_true", help="build and write regardless of freshness (ids are kept by key)")
    ap.add_argument("--force", action="store_true", help="with --rebuild: replace a file that cannot be read (its bytes are kept beside it)")
    ap.add_argument("--json", action="store_true", help="compute and print the document, write nothing")
    args = ap.parse_args(argv)
    try:
        root = hooklib.story_root(args.task, "blast_radius")
    except hooklib.StoryRootError as exc:
        print(str(exc), file=sys.stderr)
        return 3
    try:
        if args.json:
            doc = _compute_only(root)
            print(json.dumps(doc, ensure_ascii=False, indent=1) if doc is not None else "blast radius: off_diff - nothing to index")
            return 0
        doc, how = ensure(root, rebuild=args.rebuild, force=args.force)
        if doc is None:
            print("blast radius: off_diff - the story has no implementation diff; nothing was built")
            return 0
        s = summary(doc)
        print(f"blast radius: {how} work/{BLAST_FILE}: {s.areas} areas, {s.repos} repositories, {s.unmeasured} unmeasured"
              + (f" ({s.first[:120]})" if s.unmeasured and s.first else ""))
        return 0
    except GT.Refusal as refusal:
        print(refusal.text, file=sys.stderr)
    except (ValueError, OSError) as exc:
        print(f"blast_radius: {_one_line(exc)}. Nothing was written (an existing file is as it was).", file=sys.stderr)
    return 2


def _compute_only(root: Path):
    """`--json`: the document `ensure` would write, or None for a story with no implementation diff. Writes nothing."""
    if _off_diff(root):
        return None
    prior, problem = _read_prior(root / "work" / BLAST_FILE)
    if problem:
        raise _unreadable_refusal(problem)
    return build(root, prior)


if __name__ == "__main__":
    sys.exit(main())
