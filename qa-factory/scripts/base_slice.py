"""The base slice by code (G1-8, grounding/1): the text of the code the implementation diff CHANGED, as it was before - `work/base-slice/*.txt`
windows and the `base_slice[]` key of `work/grounding.yaml` (the "before" of a "was / is" question, P20; the proof that a requirement the
register calls `unchanged` really sits on an untouched line, G2-2).

  base_slice.py --task T          write the slice files and the key (through the table's one writer, `grounding_table.write_yaml`)
  base_slice.py --task T --json   print the records and write NOTHING

Exit codes: 0 the list is built (an `unknown` entry is content, not a failure), 2 a refused call (stderr, nothing written).

The library is what the S3 preparation and the grounding gates call in-process: `prepare` (writes), `collect` (the same computation, no
write: the ONE source of every judgement), `unchanged_evidence` (the one reader of the slice for G2-2), `base_place_problem` (the one
check of a `before_ref: base:` for G1-13).

How a base is chosen (FR-16: the tool that produced the diff names its base): the MR receipt's `diff_refs.base_sha` when its `head_sha`
is the recorded implementation commit, else the first parent of that commit. Either way the text is read ONLY from git objects (`cat-file`),
never from the working tree, and a file is `read` only when its hunks are REPRODUCED by that base - the old side of every hunk equals the
blob on the same line numbers, and (when the implementation commit is present) the blob plus the hunks IS the implementation's blob, so an
MR that touched the file in an earlier commit, or changed and reverted a region, is `unknown` and never a false "before". Every doubt
is `unknown` with the reason by name (FR-41, FR-59); a new file is `absent` (the third word, not `read` of nothing). Nothing is fetched.
`collect` is recomputed at every judgement (the strategist writes `grounding.yaml`, so its copy of the key is a display, never proof).
"""
import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))
import contract as C  # noqa: E402
import diff_pass as DP  # noqa: E402
import grounding_table as GT  # noqa: E402
import handoff_check as HC  # noqa: E402
import hooklib  # noqa: E402
import planning_contract as PC  # noqa: E402
import source_exclusions as SE  # noqa: E402
import test_files as TF  # noqa: E402
import test_novelty as TN  # noqa: E402

COMMIT_RE = GT.COMMIT_RE
WINDOW_LINES = 30
MERGE_GAP = 1                      # windows with at most this many lines between them are one window
MAX_SLICE_BYTES = 262144
SLICE_DIR = "base-slice"
KINDS = ("production", "config")   # the kinds of changed file that get a slice (F-1 (c)); a place of an `unchanged` row adds its file
LINE_RE = re.compile(r"[0-9]+")
NOT_UTF8 = "binary or not UTF-8 at base"
OUTSIDE = "path is outside the repository (not a canonical repository-relative path)"
BOM = chr(0xFEFF)                  # never a literal byte in this file (FR-29)


def _git(checkout, args, stdin=None):
    """`(code, stdout bytes)`; code None when git did not run or did not finish (the shared runner of the novelty check)."""
    return TN._git(checkout, args, stdin)


def _timeout_text(checkout) -> str:
    return f"git did not run or did not finish in {TN.GIT_TIMEOUT} s in {checkout}"


def _repo_path(text):
    """THE canonical form of a repository path, for the file set AND the predicate: `text` itself, or None. Refused: empty, absolute,
    a drive, a backslash, NUL or LF, an empty / `.` / `..` component. git itself resolves `<rev>:./p` to the blob of `p`, so a place
    spelled `./p` would otherwise become a record of its own with no hunks under its key (t-1036 B-1)."""
    if not isinstance(text, str) or not text or text.startswith("/") or "\\" in text or "\x00" in text or "\n" in text \
            or re.match(r"[A-Za-z]:", text):
        return None
    return None if any(part in ("", ".", "..") for part in text.split("/")) else text


def _lines(blob: bytes):
    """The lines of a blob the way the diff index counts them (LF, one `\\r` dropped); None when it is no text. The leading BOM stays in
    line 1 (the diff keeps it inside the `-` line), hence the borrowed one `DP.split_lines` takes off."""
    if b"\x00" in blob:
        return None
    try:
        return DP.split_lines(BOM + blob.decode("utf-8"))
    except UnicodeDecodeError:
        return None


# --- places: `current-code:<path>:<line>` / `base:<rev>:<path>:<line>` ----------------------------------------------------------

def parse_place(observable) -> SimpleNamespace:
    """`SimpleNamespace(kind, rev, path, line, problem)`: the place an `observable` names; `problem` says why it is none. ONE parser."""
    text = C.strip_cell(observable)
    out = SimpleNamespace(kind="", rev="", path="", line=0, problem="")
    if text.startswith("current-code:"):
        out.kind, rest = "current-code", text[len("current-code:"):]
    elif text.startswith("base:"):
        out.kind = "base"
        out.rev, _, rest = text[len("base:"):].partition(":")
    else:
        out.problem = f"observable '{text[:60]}' is not a place (current-code:<path>:<line> or base:<rev>:<path>:<line>)"
        return out
    out.path, _, number = rest.rpartition(":")
    if not out.path or not LINE_RE.fullmatch(number) or int(number) < 1:
        out.problem = f"observable '{text[:60]}' has no line number >= 1 (a whole number after the last colon)"
    else:
        out.line = int(number)
    return out


def _span(start: int, count: int):
    """The lines of one side a hunk touches: its range, or - for an empty side (an insertion in old lines, a deletion in new) - the
    two lines around the cut."""
    return (start, start + count - 1) if count > 0 else (start, start + 1)


def _base_line(place, info):
    """`(line in the base file, "")` of a place, or `(None, why)`: the place must lie in no hunk of its file (context lines count as
    touched); a `current-code:` line is moved back by the lines the hunks above it added or removed."""
    if place.kind == "current-code" and info.deleted:
        return None, "the file is deleted by the diff"
    for old_start, old_count, new_start, new_count in info.hunks:
        lo, hi = _span(old_start, old_count) if place.kind == "base" else _span(new_start, new_count)
        if lo <= place.line <= hi:
            return None, f"place {place.path}:{place.line} lies inside a hunk of the diff"
    if place.kind == "base":
        return place.line, ""
    return place.line - sum(nc - oc for _, oc, ns, nc in info.hunks if ns <= place.line), ""


def unchanged_places(root) -> list:
    """The canonical places of the register rows that say `unchanged` (a row with a non-place or a non-canonical path gives none)."""
    try:
        text = C.artifact(Path(root), "requirements-register.md").read_text(encoding="utf-8", errors="replace")
    except (ValueError, OSError):
        return []
    places = []
    for row in C.register_rows(text):
        if C.delta_state(row) == "unchanged":
            place = parse_place(row.get("observable"))
            if not place.problem and _repo_path(place.path) == place.path:
                places.append(place)
    return places


# --- git: one repository ---------------------------------------------------------------------------------------------------------

def receipt_files(root: Path, iid) -> list:
    """The MR receipts of merge request `iid` the driver wrote: `work/sources/<SRC>/mr-<iid>.json`, at any depth. The locator is
    `source_exclusions._receipt_files` (the ONE reader of where receipts live, axis 19), narrowed to the receipts under `sources/` by
    name; `work/mr-<iid>.json` (a hand-placed copy) is not a route - nothing in the factory writes it."""
    work = Path(root) / "work"
    sources = work / "sources"
    return [p for p in SE._receipt_files(work) if sources in p.parents and p.name == f"mr-{iid}.json"]


def _receipt_base(root: Path, entry, commit: str) -> str:
    """`diff_refs.base_sha` of the MR receipt of the manifest `entry`, when the receipt's `head_sha` is `commit`; else ''. Two receipts that
    disagree give ''. The receipt is looked up by the number `vcs_evidence.mr_iid` reads from the entry's `mr` (the one reader of that field)."""
    import vcs_evidence
    iid = vcs_evidence.mr_iid(entry.get("mr") if isinstance(entry, dict) else None)
    if not iid:
        return ""
    paths = receipt_files(root, iid)
    found = set()
    for path in paths:
        meta = (hooklib.read_json(path, None, kind=dict) or {}).get("metadata")
        refs = meta.get("diff_refs") if isinstance(meta, dict) else None
        if isinstance(refs, dict) and refs.get("head_sha") == commit and isinstance(refs.get("base_sha"), str) \
                and COMMIT_RE.fullmatch(refs["base_sha"]):
            found.add(refs["base_sha"])
    return found.pop() if len(found) == 1 else ""


def _is_commit(checkout, rev):
    """True / False, or None when git did not answer."""
    code, out = _git(checkout, ["cat-file", "-t", rev])
    return None if code is None else code == 0 and out.strip() == b"commit"


def _parent_of(checkout, commit):
    """`(parent sha, "")` or `("", why)`."""
    code, out = _git(checkout, ["rev-parse", "--verify", "--quiet", f"{commit}^1^{{commit}}"])
    if code is None:
        return "", _timeout_text(checkout)
    if code == 0 and COMMIT_RE.fullmatch(out.decode("ascii", "replace").strip()):
        return out.decode("ascii").strip(), ""
    if code != 1:
        return "", f"git rev-parse exited {code} in {checkout}"
    shallow_code, shallow = _git(checkout, ["rev-parse", "--is-shallow-repository"])
    if shallow_code is None:
        return "", _timeout_text(checkout)
    if shallow.strip() == b"true":
        return "", f"parent of {commit} is not in {checkout} (shallow clone)"
    return "", f"{commit} has no parent"


def _repo_state(ctx, name: str, record: dict, entry) -> SimpleNamespace:
    """The base of one diff: `problem` (the whole repository is `unknown` with it) or `checkout`, `impl` (a commit the checkout holds, or
    ''), `base`, `how`. The chain diff -> recorded repo id and commit (the table's matcher) -> checkout (the config's) -> commit."""
    state = SimpleNamespace(problem="", checkout=None, impl="", base="", how="")
    commit = record["implementation_commit"]
    if not COMMIT_RE.fullmatch(commit):
        # the table's reason as is (G1-2: one cause, ONE text in `blast_radius` and here); the `unmeasured: ` prefix is the table's, not ours
        state.problem = commit[len("unmeasured: "):] if commit.startswith("unmeasured: ") else commit
        return state
    found, why = HC.implementation_checkout(entry, ctx.cfg, ctx.project, name)
    if found is None:
        state.problem = why
        return state
    state.checkout = found
    present = _is_commit(found, commit)
    if present is None:
        state.problem = _timeout_text(found)
        return state
    state.impl = commit if present else ""
    receipt = _receipt_base(ctx.root, entry, commit) if entry else ""
    if receipt:
        state.how, state.base = "mr-receipt", receipt
        has = _is_commit(found, receipt)
        if has is None:
            state.problem = _timeout_text(found)
        elif not has:
            state.problem = (f"base commit {receipt} (diff_refs.base_sha of the MR receipt) is not in {found}; nothing is fetched - "
                             f"the owner of the checkout brings it in")
    elif not present:
        state.problem = f"commit {commit} is not in {found}"
    else:
        state.how = "parent"
        state.base, state.problem = _parent_of(found, commit)
    if state.problem:
        state.base = ""                                                    # an unresolved base is '' in the records (never a guess)
    return state


def _blobs(checkout, specs: list) -> tuple:
    """`({spec: bytes | None (missing) | False (not a blob)}, problem)`: ONE `cat-file --batch` for every `<rev>:<path>` in `specs`."""
    specs = list(dict.fromkeys(specs))
    if not specs:
        return {}, ""
    code, out = _git(checkout, ["cat-file", "--batch"], ("\n".join(specs) + "\n").encode("utf-8"))
    if code is None:
        return {}, _timeout_text(checkout)
    if code != 0:
        return {}, f"git cat-file exited {code} in {checkout}"
    got, pos = {}, 0
    for spec in specs:
        end = out.find(b"\n", pos)
        if end < 0:
            return {}, f"git cat-file answered fewer objects than asked in {checkout}"
        header, pos = out[pos:end], end + 1
        if header.endswith(b" missing") or header.endswith(b" ambiguous"):
            got[spec] = None if header.endswith(b" missing") else False
            continue
        parts = header.split(b" ")
        if len(parts) != 3 or not parts[2].isdigit():
            return {}, f"git cat-file answered an unreadable header in {checkout}"
        size = int(parts[2])
        got[spec] = out[pos:pos + size] if parts[1] == b"blob" else False
        pos += size + 1
    return got, ""


# --- the hunks of the index -------------------------------------------------------------------------------------------------------

def _views(file_record: dict, path: str):
    """`(views, problem)`: for each real hunk of the index its numbers and its old and new SIDE lines (context both, `-` old, `+` new; the
    `\\ No newline` marker is no line). A hunk with no `body`, a cut one, or one whose counts the body does not honour is a problem."""
    views = []
    for hunk in file_record["hunks"]:
        if hunk.get("pseudo"):
            continue
        where = f"hunk at {path}:{hunk.get('old_start', 0)}"
        body = hunk.get("body")
        if not isinstance(body, list):
            return [], f"the diff index carries no body for the {where}"
        old, new = [], []
        for raw in body:
            sign, text = raw[:1], raw[1:]
            if sign == "\\":
                continue
            if sign in ("", " "):
                old.append(text)
                new.append(text)
            elif sign == "-":
                old.append(text)
            elif sign == "+":
                new.append(text)
        if hunk.get("truncated") or hunk.get("overflow") or len(old) != hunk["old_count"] or len(new) != hunk["new_count"]:
            return [], f"the {where} is cut off or malformed in the diff"
        views.append({"old_start": hunk["old_start"], "old_count": hunk["old_count"], "new_start": hunk["new_start"],
                      "new_count": hunk["new_count"], "old": old, "new": new})
    return views, ""


def _apply(base: list, views: list, label: str):
    """`(the lines the hunks make of `base`, "")` or `(None, why)`: every hunk's old side must equal the base on the same line numbers."""
    out, pos = [], 0
    for view in sorted(views, key=lambda v: v["old_start"]):
        start = view["old_start"] - 1 if view["old_count"] > 0 else view["old_start"]
        if start < pos or start > len(base):
            return None, f"{label}: the hunk at line {view['old_start']} is out of order or beyond the file"
        if base[start:start + len(view["old"])] != view["old"]:
            return None, f"{label} does not reproduce the hunk at line {view['old_start']}"
        out += base[pos:start] + view["new"]
        pos = start + len(view["old"])
    return out + base[pos:], ""


def _old_path(f: dict) -> str:
    """The base path of a renamed file (the index keeps the raw `--- ` text or the `rename from` value), else ''."""
    raw = f.get("old_path") or ""
    if raw in ("", DP.DEV_NULL):
        return ""
    text, ok = DP.header_path(raw)
    pure = any(h.get("pseudo") == "rename" for h in f["hunks"])
    text = text if pure else DP.without_prefix(text, "a/")
    return text if ok and text != f["path"] else ""


def _judge(f, path: str, base_rev: str, impl: str, blob):
    """`(state, why, base_path, base_lines, views)` of one file of a diff (`f` None: a file the diff does not list). `blob(spec)` reads the
    batch. Never raises; every doubt is `unknown`; the state `skip` is a file the diff does not list and this base does not hold (it
    belongs to another repository - no record here)."""
    b_spec = lambda p: f"{base_rev}:{p}"                                                          # noqa: E731
    i_spec = lambda p: f"{impl}:{p}"                                                              # noqa: E731
    bad = lambda why: ("unknown", why, path, [], [])                                              # noqa: E731
    views, problem = _views(f, path) if f else ([], "")
    if problem:
        return bad(problem)
    old = _old_path(f) if f else ""
    if f and (f.get("refused") or f.get("path_uncertain")):
        return bad("the diff reader could not settle the path of this section")
    if f and any(h.get("pseudo") == "binary" for h in f["hunks"]):
        return bad(NOT_UTF8)
    if old and _repo_path(old) != old:
        return bad(OUTSIDE)
    base_path = old or path
    in_base, in_impl = blob(b_spec(base_path)), (blob(i_spec(path)) if impl else None)
    if in_base is False or in_impl is False:
        return bad("git object is not a plain file at base or at the implementation commit")
    if f and (f["new"] or any(h.get("pseudo") == "copy" for h in f["hunks"])) and not old:
        if in_base is not None:
            return bad(f"base {base_rev[:12]} has {path} while the diff creates it")
        return ("absent", "", path, [], [])
    base = _lines(in_base) if in_base is not None else []
    if in_base is not None and base is None:
        return bad(NOT_UTF8)
    if in_base is None:
        if not f:
            return ("skip", "", path, [], [])                                                     # not a file of this repository
        return bad(f"base {base_rev[:12]} lacks {base_path} while the diff {'renames' if old else 'modifies'} it")
    tail = []
    if old:                                                                                       # a rename or a copy
        if not impl:
            return bad("a rename cannot be told from a copy: the implementation commit is not in the checkout")
        if blob(b_spec(path)) is not None:
            return bad(f"base {base_rev[:12]} has {path}, the target of a rename")
        if blob(i_spec(old)) is not None:
            return ("absent", "", path, [], [])                                                   # a copy: the target is new
        tail = [f"renamed from {old}"]
    deleted = bool(f and f["deleted"])
    if impl:
        want = _lines(in_impl) if in_impl is not None else []
        if want is None:
            return bad(NOT_UTF8)
        if (in_impl is None) != deleted:
            return bad(f"the implementation commit {'still has' if deleted else 'lacks'} {path} the diff {'deletes' if deleted else 'writes'}")
        got, problem = _apply(base, views, f"base {base_rev[:12]}")
        if got is None:
            return bad(problem)
        if got != want:
            return bad(f"base {base_rev[:12]} plus the diff is not the implementation's {path} (an earlier commit of the MR changed it)")
    else:
        if not f:
            return bad("the implementation commit is not in the checkout, so a file the diff does not list cannot be verified")
        got, problem = _apply(base, views, f"base {base_rev[:12]}")
        if got is None:
            return bad(problem)
    return ("read", "; ".join(tail), base_path, base, views)


# --- windows and files ------------------------------------------------------------------------------------------------------------

def _windows(total: int, spans: list) -> list:
    """The merged windows (first, last line) of `total` lines: each span +-WINDOW_LINES, clipped to the file, merged at a gap <= MERGE_GAP."""
    merged: list = []
    for lo, hi in sorted(spans):
        lo, hi = max(1, lo - WINDOW_LINES), min(total, hi + WINDOW_LINES)
        if lo > hi:
            continue
        if merged and lo <= merged[-1][1] + 1 + MERGE_GAP:
            merged[-1] = (merged[-1][0], max(merged[-1][1], hi))
        else:
            merged.append((lo, hi))
    return merged


def _slice_text(head: str, lines: list, windows: list) -> str:
    body = []
    for n, (lo, hi) in enumerate(windows):
        body += (["..."] if n else []) + [f"{i}| {lines[i - 1]}" for i in range(lo, hi + 1)]
    return head, "\n".join(body) + "\n" if body else ""


def _slice_name(repo: str, file: str) -> str:
    digest = hashlib.sha256((repo + "\n" + file).encode("utf-8", "surrogatepass")).hexdigest()[:12]
    return f"{digest}-{re.sub(r'[^A-Za-z0-9._-]', '_', file.rpartition('/')[2])[:40]}.txt"


def _slice_dir(root) -> tuple:
    """`(the folder of the slice files, its path relative to the task)`: the resolver of machine artifacts decides where it is (axis 8);
    the relative form is what the key `path` carries."""
    folder = C.artifact_write_path(Path(root), SLICE_DIR)
    return folder, folder.relative_to(Path(root)).as_posix()


def _entry(repo, file, base_rev, state, why, path="") -> dict:
    return {"repo": repo, "file": file, "base_rev": base_rev, "path": path, "state": state, "why": why}


def _collect_diff(ctx, name: str, files: list, record: dict, entry, wanted: set, res) -> None:
    """The entries of one diff (one repository): the files of `files` of a kind that matters, plus the `wanted` paths (places of `unchanged`
    rows) not listed in it."""
    repo = record["repo"]
    listed = {f["path"]: f for f in files}
    chosen = {p: f for p, f in listed.items() if TF.file_kind(p) in KINDS or p in wanted}
    own = sorted(chosen)                                                                          # the files THIS diff lists
    chosen.update({p: None for p in sorted(wanted - set(listed))})
    if not chosen:
        return
    state = _repo_state(ctx, name, record, entry)
    paths = sorted(chosen)
    if state.problem:                                                                             # a repository-wide failure marks only
        res.entries += [_entry(repo, p, "", "unknown", state.problem) for p in own]               # the files of this repository's diff
        res.failed.append(f"{record['repo_id'] or repo or name}: {state.problem}")
        return
    specs = []
    for p in paths:
        specs += [f"{state.base}:{p}"] + ([f"{state.impl}:{p}"] if state.impl else [])
        old = _old_path(chosen[p]) if chosen[p] else ""
        specs += [f"{state.base}:{old}", f"{state.base}:{p}"] + ([f"{state.impl}:{old}"] if state.impl else []) if old else []
    blobs, problem = _blobs(state.checkout, [s for s in specs if "\n" not in s])
    if problem:
        res.entries += [_entry(repo, p, state.base, "unknown", problem) for p in own]
        res.failed.append(f"{record['repo_id'] or repo or name}: {problem}")
        return
    read = lambda spec: blobs.get(spec, False if "\n" in spec else None)                          # noqa: E731
    for p in paths:
        if _repo_path(p) != p:
            res.entries.append(_entry(repo, p, state.base, "unknown", OUTSIDE))
            continue
        verdict, why, base_path, lines, views = _judge(chosen[p], p, state.base, state.impl, read)
        if verdict == "skip":
            continue
        info = SimpleNamespace(base_path=base_path, lines=len(lines), windows=[], deleted=bool(chosen[p] and chosen[p]["deleted"]),
                               hunks=[(v["old_start"], v["old_count"], v["new_start"], v["new_count"]) for v in views], entry=None)
        out = _entry(repo, p, state.base, verdict, why)
        if verdict == "read":
            spans = [_span(os_, oc) for os_, oc, _, _ in info.hunks]
            spans += [(b, b) for b in (_base_line(pl, info)[0] for pl in res.places if pl.path == p) if b is not None]
            info.windows = _windows(len(lines), spans)
            verified = "hunks+implementation" if state.impl else "hunks"
            head = (f"# base slice (code, read-only): repo={repo} file={p} base_path={base_path} base_rev={state.base} from={state.impl} "
                    f"how={state.how} verified={verified} diff_sha256={record['sha256']} lines={len(lines)}")
            head, body = _slice_text(head, lines, info.windows)
            if len(body.encode("utf-8")) > MAX_SLICE_BYTES:
                out = _entry(repo, p, state.base, "unknown", f"base slice is {len(body.encode('utf-8'))} bytes, over {MAX_SLICE_BYTES}")
            else:
                out["path"] = f"{_slice_dir(ctx.root)[1]}/{_slice_name(repo, p)}"
                res.files[_slice_name(repo, p)] = head + "\n" + body
        info.entry = out
        res.infos.append(info)
        res.entries.append(out)


def collect(root, *, project=None, cfg=None) -> SimpleNamespace:
    """The whole computation, no write: `SimpleNamespace(source, entries, infos, files, places, failed)`. `source` is `diff` or the null
    outcome's word; `entries` the records of `base_slice[]` (sorted by repo and file); `infos` what the predicate needs per record;
    `files` the slice texts by name; `failed` the repositories that could not be checked at all, each with its reason. Raises `GT.Refusal` for a story whose source and diffs disagree."""
    root = Path(root)
    world, why = GT.source_state(root)
    res = SimpleNamespace(source="diff", entries=[], infos=[], files={}, places=[], failed=[])
    if world == "mismatch":
        raise GT.Refusal(f"base_slice: {why}. Expected: implementation_source `diff` when a diff is on disk, and a diff only when the "
                         "source is `diff`. Do: S1 records the source again (stage_done --set implementation_source=...); nothing was written.")
    if world != "diff":
        res.source = world.split(":", 1)[1]
        return res
    ctx = SimpleNamespace(root=root, project=project or hooklib.project_root(), cfg=cfg if cfg is not None else hooklib.load_config())
    res.places = unchanged_places(root)
    wanted = {pl.path for pl in res.places}
    records = {Path(d["path"]).name: d for d in GT.diff_records(root)}
    manifest = hooklib.read_json(root / "work" / "context-manifest.json", None, kind=dict)
    manifest_entries = HC.implementation_entries(manifest) if manifest is not None else []
    by_diff: dict = {}
    for f in DP.index(root / "work")["files"]:
        by_diff.setdefault(f["diff"], []).append(f)
    for name in sorted(records):
        entry, _ = GT.manifest_entry_for(name, manifest_entries)
        _collect_diff(ctx, name, by_diff.get(name, []), records[name], entry, wanted, res)
    unchecked = f" (not checked: {'; '.join(res.failed)})" if res.failed else ""
    for path in sorted(wanted - {e["file"] for e in res.entries}):                                # a place no repository base holds is
        res.entries.append(_entry("", path, "", "unknown",                                        # pinned to NO repository
                                  f"repo unresolved: no recorded repository base holds this file{unchecked}"))
    order = lambda e: (e["repo"], e["file"])                                                      # noqa: E731
    res.entries.sort(key=order)
    res.infos.sort(key=lambda i: order(i.entry))
    return res


def prepare(root, *, project=None, cfg=None) -> SimpleNamespace:
    """Write the slice files and the `base_slice[]` key of the table (the key LAST, through `GT.write_yaml`); the result of `collect`."""
    root = Path(root)
    res = collect(root, project=project, cfg=cfg)
    doc, problem = PC.read_grounding(root)
    if doc is None:
        raise GT.Refusal(f"base_slice: {problem}. Expected: the table the S3 window preparation writes before the slice "
                         "(grounding_table.py --refresh). Do: the driver writes the table first; nothing was written.")
    word = doc.data.get("implementation_source")
    if (word == "diff") != (res.source == "diff"):
        raise GT.Refusal(f"base_slice: the table records implementation_source {word!r} while the story records {res.source!r}. Expected: a "
                         "table of the same source. Do: the driver refreshes the table (grounding_table.py --refresh); nothing was written.")
    folder = _slice_dir(root)[0]
    if res.files:
        folder.mkdir(parents=True, exist_ok=True)
        for name, text in res.files.items():
            (folder / name).write_bytes(text.encode("utf-8"))
    if folder.is_dir():
        for stale in folder.glob("*.txt"):
            if stale.name not in res.files:
                try:
                    stale.unlink()
                except OSError:
                    pass
    doc.data["base_slice"] = res.entries
    GT.write_yaml(GT.table_path(root), doc.data)
    return res


# --- the readers of the slice (judged on `collect`, never on the table's copy of the key) -------------------------------------------

def _record(col, path: str):
    found = [i for i in col.infos if i.entry["file"] == path]
    others = [e for e in col.entries if e["file"] == path and not any(i.entry is e for i in found)]
    return found, others


def _one(col, place):
    """`(info, "")` of the ONE record of the place's file that is `read`, or `(None, why)`."""
    found, others = _record(col, place.path)
    every = [i.entry for i in found] + others
    if not every:
        return None, f"no base slice record for {place.path}"
    if len(every) > 1:
        return None, f"{len(every)} base slice records name {place.path} (repos: {', '.join(repr(e['repo']) for e in every)})"
    if every[0]["state"] != "read" or not found:
        return None, f"the base slice of {place.path} is {every[0]['state']}" + (f": {every[0]['why']}" if every[0]["why"] else "")
    return found[0], ""


def unchanged_evidence(row, task_root, *, collected=None, project=None, cfg=None) -> tuple:
    """`("evidenced" | "unevidenced", where, why)` for a register row that says `unchanged`: the place its `observable` names lies on an
    untouched line of a file the slice READ, inside a window. `collected` (a `collect` result) is what G2-2 computes once for all rows; None
    computes it here - always from the git objects and the diff on disk, never from `grounding.yaml`. The error runs one way: a doubt is
    `unevidenced` (the row stays in the count), never `evidenced`."""
    no = lambda why: ("unevidenced", "", why)                                                     # noqa: E731
    if C.delta_state(row) != "unchanged":
        return no("not unchanged")
    place = parse_place(row.get("observable") if isinstance(row, dict) else "")
    if place.problem:
        return no(place.problem)
    if _repo_path(place.path) != place.path:
        return no("place is not a repository-relative path")
    if place.kind == "base" and not COMMIT_RE.fullmatch(place.rev):
        return no("the base revision of the place is not a full commit id")
    try:
        col = collected if collected is not None else collect(task_root, project=project, cfg=cfg)
    except GT.Refusal as refusal:
        return no(f"the base slice cannot be collected ({refusal.text.split('. Expected')[0]})")
    info, why = _one(col, place)
    if info is None:
        return no(why)
    if place.kind == "base" and (place.rev != info.entry["base_rev"] or place.path != info.base_path):
        return no(f"the place names base {place.rev[:12]}:{place.path}, the slice is of {info.entry['base_rev'][:12]}:{info.base_path}")
    line, why = _base_line(place, info)
    if line is None:
        return no(why)
    if not 1 <= line <= info.lines or not any(lo <= line <= hi for lo, hi in info.windows):
        return no(f"line {line} of {info.base_path} is outside the slice windows")
    return "evidenced", f"base:{info.entry['base_rev']}:{info.base_path}:{line}", ""


def base_place_problem(ref, task_root, *, collected=None, project=None, cfg=None) -> str:
    """'' when a `before_ref: base:<rev>:<path>:<line>` names a line of a file the slice READ at exactly that revision; else why not."""
    place = parse_place(ref)
    if place.problem or place.kind != "base":
        return place.problem or f"'{ref}' is not a base:<rev>:<path>:<line> place"
    if _repo_path(place.path) != place.path or not COMMIT_RE.fullmatch(place.rev):
        return "the place is not a repository-relative path at a full revision"
    try:
        col = collected if collected is not None else collect(task_root, project=project, cfg=cfg)
    except GT.Refusal as refusal:
        return f"the base slice cannot be collected ({refusal.text.split('. Expected')[0]})"
    info, why = _one(col, place)
    if info is None:
        return why
    if place.rev != info.entry["base_rev"] or place.path != info.base_path:
        return f"the slice of {place.path} is at {info.entry['base_rev'][:12]}, not at {place.rev[:12]}"
    if not 1 <= place.line <= info.lines:
        return f"{info.base_path} has {info.lines} lines at that revision"
    if not any(lo <= place.line <= hi for lo, hi in info.windows):                                # a line the role could never have read
        return f"line {place.line} of {info.base_path} is outside the slice windows"
    return ""


# --- the command line ---------------------------------------------------------------------------------------------------------------

def _summary(res) -> list:
    count = {s: sum(1 for e in res.entries if e["state"] == s) for s in ("read", "absent", "unknown")}
    lines = [f"base_slice: source {res.source}: {len(res.entries)} entries ({count['read']} read, {count['absent']} absent, {count['unknown']} unknown)"]
    reasons: dict = {}
    for e in res.entries:
        if e["state"] == "unknown":
            reasons.setdefault(e["why"], []).append(e["file"])
    lines += [f"base_slice: unknown x{len(files)} ({files[0]}{', ...' if len(files) > 1 else ''}): {why}" for why, files in reasons.items()]
    return lines


def main(argv=None) -> int:
    try:
        import console_io
        console_io.utf8_stdio()
    except ImportError:
        pass
    ap = argparse.ArgumentParser(description="The base slice: the code the implementation diff changed, as it was before.")
    ap.add_argument("--task", required=True, help="the story's ticket key")
    ap.add_argument("--json", action="store_true", help="print the records and write nothing")
    args = ap.parse_args(argv)
    try:
        root = hooklib.story_root(args.task, "base_slice")
        if args.json:
            res = collect(root)
            print(json.dumps({"source": res.source, "base_slice": res.entries}, indent=2, ensure_ascii=False))
            return 0
        for line in _summary(prepare(root)):
            print(line)
        return 0
    except GT.Refusal as refusal:
        print(refusal.text, file=sys.stderr)
    except (ValueError, OSError) as exc:
        print(f"base_slice: {exc}. Nothing was written (an existing table is as it was).", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
