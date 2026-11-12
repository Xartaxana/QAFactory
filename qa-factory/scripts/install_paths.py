"""What the factory installed under a project, and what a reinstall may do with each path.

Two pieces, one module, because a reinstall needs both answers about the same path:

  * the installed-paths MANIFEST `qa-factory/install-manifest.json` -- what the last install
    wrote, with the sha256 of each file, so a later install can tell "the factory wrote this and
    nobody touched it" from "a person changed it" (read_manifest / write_manifest /
    verify_manifest);
  * the CLASSIFICATION TABLE `references/install-paths.json` -- closed variety kept as data
    (FR-13): carried / regenerated / discarded / not_ours per path glob, with the script that
    reads the path (classify / validate_table / scan_tree).

This module only READS the project and only WRITES the manifest. It never deletes, moves or
rewrites any other file: scan_tree returns lists, the caller (onboard_apply) acts on the ones the
person approved. Why so strict: a reinstall that retires by manifest alone would delete a person's
edits (the sha says "changed" -> kept), and one that trusts a path in the manifest would follow
`../x` out of the project. Invariants held here:

  * a path outside the project root (absolute, `..`, a drive, UNC, a symlink or junction that
    resolves outside) is REFUSED and listed under `refused`, never read, hashed or returned for
    retirement;
  * a CARRIED path (by the table or by the manifest) is never in `retire`;
  * bytes that differ from the manifest's sha are `changed_since_install`, never `retire`;
  * an unreadable manifest (bad JSON, wrong shape) is unknown, never a basis for retiring (FR-41);
  * a manifest written by a NEWER package than this plugin retires nothing;
  * lock files and other `retire_safe: false` rows are never in `retire`;
  * a path the table flags `hook_written` (a running session's hooks rewrite it) is never in `retire`,
    by `retire_unbuilt`; the flag can only subtract, and `classify` may err only toward False (t-298);
  * the manifest is written atomically (temp file + replace): a crash leaves the old manifest or
    none, never half of one -- so it never describes a tree that was not written.

Machine-local entries (state that differs per machine) carry `class` and `machine_local: true`
and NO sha, so a clone of the project never reads them as "changed".

The two folders (owner, t-232 F7+F8): the table also says which class lives in which folder of the
factory's home (`folders`), derives the `.gitignore` block from that (`gitignore_block`) and names
the moves a reinstall makes for records an earlier factory kept in the ignored folder (`moves`).

Library module, no CLI and nothing on stdout (FR-14): callers import it.
"""
import hashlib
import json
import os
import re
import sys
from pathlib import Path

sys.dont_write_bytecode = True

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_REL = "qa-factory/install-manifest.json"
TABLE_REL = "references/install-paths.json"
MANIFEST_SCHEMA = 1

# What a manifest entry can be: the factory only writes these three. `not_ours` is a table-only
# class (an earlier generation's path we recognise by name and never touch).
ENTRY_CLASSES = ("carried", "regenerated", "discarded")
# One path, several matching rules: the first class in this tuple wins. It is code, not data: a
# data edit must not be able to turn a carried path into a retired one. Why carried first: the
# invariant "a carried path never appears in a retire listing" (t-232).
PRECEDENCE = ("carried", "regenerated", "discarded", "not_ours")
RESULT_CLASSES = PRECEDENCE + ("unrecognised", "refused")
# What a retirement does to one item (owner, t-232 F2: decided per class, kept in the table).
RETIRE_MODES = ("delete", "move")
# How a writer holds a lock (a table row's `lock_kind`; t-272 item 6): `os` = an OS byte-range lock on
# a file (event_store, execution_scheduler...: "free" when nobody holds it, so a leftover is provably
# stale); `exclusive_create` = the file's EXISTENCE is the lock (exit_gate: O_CREAT|O_EXCL), so a file
# that exists looks stale to a try-lock while it is held; `folder` = a directory made with mkdir is
# the lock (project_decisions). Only an `os` lock of a regenerated row can be proven stale.
LOCK_KINDS = ("os", "exclusive_create", "folder")

# Where `validate_table` looks for a reader / for text that contradicts `reader: none`.
CORPUS_DIRS = ("scripts", "hooks", "skills", "agents", "references", "handoffs")
CORPUS_SUFFIXES = {".py", ".md", ".json", ".yaml", ".yml", ".cmd", ".sh", ".txt"}
CORPUS_MAX_BYTES = 2_000_000
# Text that is NOT a reader of a project path: this table itself, this module, and the tests.
CORPUS_EXCLUDED = (TABLE_REL, "scripts/install_paths.py")

_BACKSLASH = chr(92)


# --- paths -----------------------------------------------------------------------------------

def _fold_default() -> bool:
    """Windows file names are case-insensitive: `QA-Factory/State/x` is `qa-factory/state/x`."""
    return sys.platform == "win32"


def normalize_rel(path) -> tuple:
    """-> (rel, None) or (None, reason). A project-relative path in forward slashes.

    Refused: empty, absolute (`/x`, `C:x`, `C:/x`, a leading backslash, UNC), any `..` component,
    a component made only of dots and spaces (Windows reads `.. ` as `..`), a colon anywhere
    (drive letters, NTFS streams), a control byte. `.` components and repeated slashes are dropped.
    Case is kept: matching folds case where the platform does (see `_fold_default`)."""
    if not isinstance(path, str):
        return None, f"a path must be text, got {type(path).__name__}"
    text = path.replace(_BACKSLASH, "/")
    if not text.strip():
        return None, "empty path"
    if any(ord(ch) < 32 for ch in text):
        return None, "path holds a control character"
    if text.startswith("/"):
        return None, "absolute path (starts with a slash) -- only paths inside the project root are allowed"
    if ":" in text:
        return None, "path holds a colon (drive letter or stream) -- only paths inside the project root are allowed"
    parts = []
    for part in text.split("/"):
        if part in ("", "."):
            continue
        if part.strip(" .") == "":
            return None, f"path component {part!r} is `..` or a spelling of it -- it would leave the project root"
        parts.append(part)
    if not parts:
        return None, "empty path"
    return "/".join(parts), None


def _key(rel: str, fold: bool) -> str:
    return rel.casefold() if fold else rel


def _realpath(path) -> str:
    return os.path.normcase(os.path.realpath(str(path)))


def _inside(real_root: str, real_path: str) -> bool:
    try:
        return os.path.commonpath([real_root, real_path]) == real_root
    except ValueError:      # another drive
        return False


def _resolve_inside(root, rel: str) -> tuple:
    """-> (absolute path, None) or (None, reason). `rel` is already normalised. A symlink or
    junction anywhere on the way whose target is outside the root is refused."""
    real_root = _realpath(root)
    path = Path(root, *rel.split("/"))
    if not _inside(real_root, _realpath(path)):
        return None, "resolves outside the project root (symlink or junction)"
    return path, None


def sha256_file(path) -> str:
    """Chunked sha256 of a file's bytes. (factory_manifest.py reads release_fingerprint's map and is a
    package-definition tool; this is a project-file helper, so it is not imported from there.)"""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


# --- versions --------------------------------------------------------------------------------

def _vtuple(text) -> tuple | None:
    match = re.match(r"^\s*(\d+(?:\.\d+)*)", text) if isinstance(text, str) else None
    return tuple(int(p) for p in match.group(1).split(".")) if match else None


def _vless(a: tuple, b: tuple) -> bool:
    width = max(len(a), len(b))
    return a + (0,) * (width - len(a)) < b + (0,) * (width - len(b))


def plugin_version(plugin_root=None) -> str:
    """`version` from `.claude-plugin/plugin.json` -- the one carrier of the package version."""
    path = Path(plugin_root or PLUGIN_ROOT) / ".claude-plugin" / "plugin.json"
    try:
        version = json.loads(path.read_text(encoding="utf-8-sig")).get("version")
    except (OSError, ValueError) as exc:
        raise ValueError(f"{path} is unreadable ({exc}); the manifest records the package version "
                         "from it -- restore plugin.json from the package") from exc
    if _vtuple(version) is None:
        raise ValueError(f"{path} has no readable `version` (got {version!r}); expected 'N.N.N'")
    return version


# --- the classification table ----------------------------------------------------------------

_SEG_RE: dict = {}


def _seg_regex(segment: str, fold: bool):
    cached = _SEG_RE.get((segment, fold))
    if cached is None:
        pattern = "".join("[^/]*" if ch == "*" else "[^/]" if ch == "?" else re.escape(ch) for ch in segment)
        cached = _SEG_RE[(segment, fold)] = re.compile(pattern + r"\Z", re.I if fold else 0)
    return cached


def _match(path_segs: list, glob_segs: list, fold: bool) -> bool:
    """`*`/`?` inside one segment; a `**` segment matches zero or more whole segments, so
    `a/**` matches `a` itself and everything below it."""
    if not glob_segs:
        return not path_segs
    head = glob_segs[0]
    if head == "**":
        return any(_match(path_segs[i:], glob_segs[1:], fold) for i in range(len(path_segs) + 1))
    if not path_segs:
        return False
    return bool(_seg_regex(head, fold).match(path_segs[0])) and _match(path_segs[1:], glob_segs[1:], fold)


def _could_contain(dir_segs: list, glob_segs: list, fold: bool) -> bool:
    """Could a path BELOW this directory match the glob? (Prunes the walk.)"""
    for i, seg in enumerate(dir_segs):
        if i >= len(glob_segs):
            return False
        if glob_segs[i] == "**":
            return True
        if not _seg_regex(glob_segs[i], fold).match(seg):
            return False
    return len(glob_segs) > len(dir_segs)


_TABLE_CACHE: dict = {}


def load_table(plugin_root=None) -> dict:
    """The classification table of the package. Raises ValueError (naming the file) when it is
    missing or not JSON: classification without its table must stop, not guess (FR-41)."""
    path = Path(plugin_root or PLUGIN_ROOT) / TABLE_REL
    try:
        stat = path.stat()
        stamp = (str(path), stat.st_mtime_ns, stat.st_size)
        if stamp not in _TABLE_CACHE:
            _TABLE_CACHE.clear()
            _TABLE_CACHE[stamp] = json.loads(path.read_text(encoding="utf-8-sig"))
        table = _TABLE_CACHE[stamp]
    except (OSError, ValueError) as exc:
        raise ValueError(f"{path} is unreadable ({exc}); it is part of the package -- reinstall the plugin") from exc
    if not isinstance(table, dict) or not isinstance(table.get("rules"), list):
        raise ValueError(f"{path} has no `rules` list; expected the shape described in its `description`")
    return table


def _rules(table: dict) -> list:
    out = []
    for raw in table.get("rules") or []:
        if not isinstance(raw, dict) or not isinstance(raw.get("glob"), str) or raw.get("class") not in PRECEDENCE:
            continue    # validate_table names these; classification must not guess a class for them
        out.append({"glob": raw["glob"], "class": raw["class"], "reader": raw.get("reader"),
                    "machine_local": bool(raw.get("machine_local", False)),
                    "retire_safe": raw.get("retire_safe", True) is not False,
                    "generation": raw.get("generation"), "requires": list(raw.get("requires") or []),
                    "retire_mode": raw.get("retire_mode") if raw.get("retire_mode") in RETIRE_MODES else None,
                    "reason": raw.get("reason") if isinstance(raw.get("reason"), str) else None,
                    "lock_kind": raw.get("lock_kind") if raw.get("lock_kind") in LOCK_KINDS else None,
                    "hook_written": raw.get("hook_written") is True,    # only a real `true`: any other value is a shape error and means no
                    "before_install": raw.get("before_install") is True,    # same: only a real `true` (B-411)
                    "discard_when": raw.get("discard_when"), "segs": raw["glob"].split("/")})
    return out


def retire_modes(table: dict | None = None) -> dict:
    """The per-class retirement rule from the table's `retire_modes` block (owner, t-232 F2):
    {discarded, regenerated_stale, undetermined, carried, undetermined_kinds[], move_target}. The
    caller (onboard_apply) reads WHAT to do with a retired item here, not from its own code. A
    table without the block gets the owner's answer as defaults, except `carried`, which is always
    'none': nothing carried is ever retired, whatever a data edit says."""
    block = (table or load_table()).get("retire_modes")
    block = block if isinstance(block, dict) else {}
    out = {"discarded": "delete", "regenerated_stale": "delete", "undetermined": "move", "carried": "none",
           "undetermined_kinds": ["unrecognised", "changed_since_install", "unknown"],
           "move_target": "qa-factory/state/retired/<date>/"}
    for key in ("discarded", "regenerated_stale", "undetermined"):
        if block.get(key) in RETIRE_MODES:
            out[key] = block[key]
    if isinstance(block.get("undetermined_kinds"), list) and all(isinstance(k, str) for k in block["undetermined_kinds"]):
        out["undetermined_kinds"] = list(block["undetermined_kinds"])
    if isinstance(block.get("move_target"), str) and block["move_target"]:
        out["move_target"] = block["move_target"]
    return out


def _mode_of(row_mode, cls: str, table: dict) -> str:
    """The retirement mode of one item: its own row's `retire_mode`, else the class rule."""
    if row_mode in RETIRE_MODES:
        return row_mode
    modes = retire_modes(table)
    return modes["discarded"] if cls == "discarded" else modes["undetermined"]


def home_of(table: dict) -> str:
    return str(table.get("home") or "qa-factory")


def gitignore_lines(table: dict | None = None) -> list:
    """[{line, generation}]: `.gitignore` lines an earlier generation wrote (onboard_apply owns
    the `.gitignore` edit; the line text lives here, in the table, not in that code)."""
    rows = (table or load_table()).get("gitignore_lines") or []
    return [{"line": r["line"], "generation": r.get("generation")} for r in rows
            if isinstance(r, dict) and isinstance(r.get("line"), str)]


def folders(table: dict | None = None) -> list:
    """[{path, tracked, holds}]: the class folders of the factory's home (owner, t-232 F7+F8): the
    tracked folder of carried records and the machine-local folder git ignores whole. A malformed
    entry is skipped here and named by `validate_table`."""
    rows = (table or load_table()).get("folders") or []
    return [{"path": r["path"], "tracked": r["tracked"], "holds": r.get("holds", "")} for r in rows
            if isinstance(r, dict) and isinstance(r.get("path"), str) and isinstance(r.get("tracked"), bool)]


def gitignore_block(table: dict | None = None) -> list:
    """The lines of the factory's `.gitignore` block, DERIVED from the table: the generated files
    inside a tracked folder (`gitignore_block.inside_tracked`), then ONE line per untracked class
    folder - never one per file, and never a line for a tracked folder (owner, t-232 F7: what is
    ignored and what is not must be visible at a glance)."""
    table = table if table is not None else load_table()
    inside = (table.get("gitignore_block") or {}).get("inside_tracked") or []
    return [line for line in inside if isinstance(line, str) and line] + [f"{f['path']}/" for f in folders(table) if not f["tracked"]]


def ignored_inside_tracked(rel_path, table: dict | None = None, casefold: bool | None = None) -> bool:
    """Whether the `.gitignore` block's `gitignore_block.inside_tracked` lines cover this project-relative
    path (OH3-33): a line ending in `/` names a folder and covers every FILE below it, any other line names
    the path itself or a folder of that name. Read from the SAME table the block is derived from, so the
    answer and the written block cannot drift (AR-14); the real `git check-ignore` is the control in the
    tests. Never raises: a path that does not normalise, or a table without the lines, is False (the
    caller then lists nothing, which is the safe direction - nothing is untracked by a wrong True)."""
    fold = _fold_default() if casefold is None else casefold
    rel, _why = normalize_rel(rel_path)
    if rel is None:
        return False
    try:
        table = table if table is not None else load_table()
    except ValueError:
        return False
    inside = (table.get("gitignore_block") or {}).get("inside_tracked") or []
    segs = rel.split("/")
    for line in inside:
        if not isinstance(line, str) or not line.strip("/"):
            continue
        folder_only = line.endswith("/")
        glob_segs = line.strip("/").split("/")
        last = len(segs) - 1 if folder_only else len(segs)    # a folder-only line never covers a FILE of that name
        if any(_match(segs[:i], glob_segs, fold) for i in range(1, last + 1)):
            return True
    return False


def moves(table: dict | None = None) -> list:
    """[{from, to, kind}]: where a reinstall moves the carried records an earlier factory kept in
    `state/` (the rows that carry `moved_to`). `kind` is 'file', or 'dir' for a `/**` row (the
    directory moves whole, file by file). Paths are project-relative, forward slashes, no glob."""
    out = []
    for raw in (table or load_table()).get("rules") or []:
        if not (isinstance(raw, dict) and raw.get("class") == "carried" and isinstance(raw.get("glob"), str)
                and isinstance(raw.get("moved_to"), str)):
            continue
        src, dst = raw["glob"], raw["moved_to"]
        if src.endswith("/**") and dst.endswith("/**"):
            out.append({"from": src[:-3], "to": dst[:-3], "kind": "dir"})
        elif not any(ch in src + dst for ch in "*?"):
            out.append({"from": src, "to": dst, "kind": "file"})
    return out


def regenerate_outputs(table: dict | None = None, scripts=None) -> list:
    """The project paths the install's regenerate step REBUILDS, from the table's `regenerate_step`
    block ({script, outputs[]} per script the apply runs): sorted, literal, project-relative. `scripts`
    (names) narrows it to the ones this run really runs; None means every script of the block. The
    caller (onboard_apply) says a regenerated file that is NOT in this set is not rebuilt by this run
    and is retired (t-272 item 1); the set lives in the table, not in code (FR-13)."""
    out = set()
    for entry in (table if table is not None else load_table()).get("regenerate_step") or []:
        if not (isinstance(entry, dict) and isinstance(entry.get("script"), str) and isinstance(entry.get("outputs"), list)):
            continue
        if scripts is not None and entry["script"] not in scripts:
            continue
        out.update(o for o in entry["outputs"] if isinstance(o, str) and o)
    return sorted(out)


def _condition(cond, root, rel: str, context) -> str:
    """Evaluate a row's `discard_when`: 'foreign' | 'current' | 'unknown'. Unknown is the answer
    to everything unreadable or unsupplied -- an unknown is kept, never discarded (FR-41). A report
    that READS FINE as a JSON object but names no fingerprint at all (the doctor smokes of the first
    versions: five of six on the live project) is `foreign`: reusable_report never reuses it, so it
    can never be of use again (t-272 item 1) - while an unreadable file or an unsupplied installed
    fingerprint stays unknown."""
    if not isinstance(cond, dict) or root is None or not isinstance(context, dict):
        return "unknown"
    wanted = context.get(cond.get("differs_from"))
    if not isinstance(wanted, str) or not wanted:
        return "unknown"
    path, why = _resolve_inside(root, rel)
    if path is None:
        return "unknown"
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return "unknown"
    if not isinstance(data, dict):
        return "unknown"
    value = data.get(cond.get("json_field"))
    if not isinstance(value, str) or not value:
        return "foreign"
    return "current" if value == wanted else "foreign"


def classify(rel_path, *, table: dict | None = None, casefold: bool | None = None,
             root=None, context: dict | None = None) -> dict:
    """The class of one project-relative path. Always the same keys (FR-14):

      rel_path, class (carried|regenerated|discarded|not_ours|unrecognised|refused),
      machine_local, retire_safe, reader, generation, requires[], rule (the winning glob),
      also_matched[] (other globs that matched), condition (None | 'foreign'|'current'|'unknown'),
      refused (None | reason), retire_mode (None | 'delete' | 'move': the winning row's own),
      reason (None | the winning row's text, e.g. why a not_ours path is not ours),
      lock_kind (None | 'os' | 'exclusive_create' | 'folder': the FIRST matching row that names one,
      in precedence then table order - a lock under a carried row stays a lock of its kind),
      hook_written (bool: a running session's hooks rewrite this path - t-298. True iff the WINNING class is
      still `regenerated` (a carried winner, or a file a `discard_when` proved foreign, is False) and ANY
      matching regenerated row carries the flag: the lock of the dashboard writer is won by the generic lock
      row and is hook-written through the writer's folder row).

    `before_install` (B-411) is true when the WINNING row carries `before_install: true` - the onboarding run's own
    notes, written before any install exists. `onboard_apply.table_hits` does not count such a path as a trace of an
    install. It is a GATE too and may err only toward False for the same reason: it only takes away install evidence
    (the p0 sentence "traces of an earlier installation") and changes nothing in retirement, the listing, the hashing
    or the manifest, so a missed flag brings the old sentence back and nothing is ever lost.

    `hook_written` is a GATE, not advice: it takes a file out of the retire listing, its sha recheck, the
    manifest and the count of stale locks. So it may err only toward False (a missed hook file is listed and
    hashed - the old spurious refusal - and never lost); a path no flagged row names exactly is False.

    Backslashes and (on Windows) letter case are normalised before matching. Several matching
    rules resolve by PRECEDENCE (carried > regenerated > discarded > not_ours); `retire_safe` is
    false when ANY matching rule says so (the safe direction). A row with `discard_when` is
    regenerated until `root` and `context` (e.g. {"package_fingerprint": ...}) prove the file's
    field differs -- then it is discarded; unreadable or unsupplied -> 'unknown', still kept."""
    fold = _fold_default() if casefold is None else casefold
    rel, why = normalize_rel(rel_path)
    base = {"rel_path": rel if rel is not None else str(rel_path), "class": "refused", "machine_local": False,
            "retire_safe": False, "reader": None, "generation": None, "requires": [], "rule": None,
            "also_matched": [], "condition": None, "refused": why, "retire_mode": None, "reason": None, "lock_kind": None,
            "hook_written": False, "before_install": False}
    if rel is None:
        return base
    table = table if table is not None else load_table()
    segs = rel.split("/")
    hits = [r for r in _rules(table) if _match(segs, [s for s in r["segs"]], fold)]
    base["refused"] = None
    if not hits:
        base.update({"class": "unrecognised", "retire_safe": False})
        return base
    hits.sort(key=lambda r: PRECEDENCE.index(r["class"]))       # stable: table order within a class
    win = hits[0]
    base.update({"class": win["class"], "machine_local": win["machine_local"],
                 "retire_safe": all(r["retire_safe"] for r in hits), "reader": win["reader"],
                 "generation": win["generation"], "requires": win["requires"], "rule": win["glob"],
                 "also_matched": [r["glob"] for r in hits[1:]], "retire_mode": win["retire_mode"],
                 "reason": win["reason"], "lock_kind": next((r["lock_kind"] for r in hits if r["lock_kind"]), None)})
    if win["discard_when"]:
        base["condition"] = _condition(win["discard_when"], root, rel, context)
        if base["condition"] == "foreign":
            base["class"] = "discarded"
    base["hook_written"] = base["class"] == "regenerated" and any(r["hook_written"] for r in hits if r["class"] == "regenerated")
    base["before_install"] = base["class"] == "carried" and win["before_install"]    # only the WINNING row's flag counts (B-411)
    return base


# --- validate_table: shape, overlaps, and the reader grep (G4) ---------------------------------

def _key_of(rule: dict) -> str:
    """The text a reader must contain: the rule's own `key`, else the longest literal run of the
    last glob segment that has one (`metrics*.json` -> `metrics`, `*.lock` -> `.lock`)."""
    if isinstance(rule.get("key"), str) and rule["key"]:
        return rule["key"]
    for seg in reversed(str(rule.get("glob", "")).split("/")):
        runs = [run for run in re.split(r"[*?]+", seg) if run]
        if runs:
            return max(runs, key=len)
    return ""


def _reader_path(package_root: Path, reader: str) -> Path:
    return package_root / reader if "/" in reader else package_root / "scripts" / reader


def _read_lower(path: Path) -> str | None:
    try:
        if path.stat().st_size > CORPUS_MAX_BYTES:
            return None
        return path.read_text(encoding="utf-8", errors="replace").casefold()
    except OSError:
        return None


def _corpus(package_root: Path) -> dict:
    """{package-relative path: lower-cased text} of everything that could READ a project path."""
    out = {}
    for folder in CORPUS_DIRS:
        base = package_root / folder
        if not base.is_dir():
            continue
        for current, dirs, files in os.walk(base):
            here = Path(current).relative_to(package_root).as_posix()
            dirs[:] = [d for d in dirs if d != "__pycache__" and f"{here}/{d}" != "scripts/tests"]
            for name in files:
                path = Path(current, name)
                rel = path.relative_to(package_root).as_posix()
                if path.suffix not in CORPUS_SUFFIXES or rel in CORPUS_EXCLUDED:
                    continue
                text = _read_lower(path)
                if text is not None:
                    out[rel] = text
    return out


def _grep(corpus: dict, key: str) -> list:
    needle = key.casefold()
    return sorted(rel for rel, text in corpus.items() if needle and needle in text)


def _step_outputs(table) -> list:
    """The literal outputs every `regenerate_step` declares, whatever else is malformed in the block."""
    out = []
    for step in table.get("regenerate_step") if isinstance(table.get("regenerate_step"), list) else []:
        if isinstance(step, dict) and isinstance(step.get("outputs"), list):
            out.extend(o for o in step["outputs"] if isinstance(o, str) and o)
    return out


def _shape_errors(table) -> list:
    if not isinstance(table, dict) or not isinstance(table.get("rules"), list):
        return [{"code": "shape", "glob": "", "message": "the table has no `rules` list; expected the shape "
                 "described in the table's `description`"}]
    errors = []
    for i, rule in enumerate(table["rules"]):
        label = rule.get("glob") if isinstance(rule, dict) and isinstance(rule.get("glob"), str) else f"rules[{i}]"

        def bad(message, label=label):
            errors.append({"code": "shape", "glob": label, "message": message})
        if not isinstance(rule, dict):
            bad("a rule must be an object with `glob`, `class` and `reader`")
            continue
        glob = rule.get("glob")
        if not isinstance(glob, str) or not glob:
            bad("`glob` must be a non-empty string")
        else:
            segs = glob.split("/")
            if _BACKSLASH in glob or glob.startswith("/") or ":" in glob or ".." in segs or "" in segs:
                bad("`glob` must be a project-relative path with forward slashes, no `..`, no empty segment")
        if rule.get("class") not in PRECEDENCE:
            bad(f"`class` must be one of {list(PRECEDENCE)}")
        if not isinstance(rule.get("reader"), str) or not rule.get("reader"):
            bad("`reader` must be a script name, a package-relative path, or `none`")
        for flag in ("machine_local", "retire_safe"):
            if flag in rule and not isinstance(rule[flag], bool):
                bad(f"`{flag}` must be true or false")
        if "generation" in rule and (not isinstance(rule["generation"], int) or isinstance(rule["generation"], bool)):
            bad("`generation` must be an integer")
        if "requires" in rule and not (isinstance(rule["requires"], list) and all(isinstance(r, str) for r in rule["requires"])):
            bad("`requires` must be a list of names")
        if "retire_mode" in rule:
            if rule["retire_mode"] not in RETIRE_MODES:
                bad(f"`retire_mode` must be one of {list(RETIRE_MODES)}")
            elif rule.get("class") == "carried":
                bad("a carried row never carries a `retire_mode`: nothing carried is ever retired")
        if "reason" in rule and not isinstance(rule["reason"], str):
            bad("`reason` must be text")
        if "lock_kind" in rule:
            if rule["lock_kind"] not in LOCK_KINDS:
                bad(f"`lock_kind` must be one of {list(LOCK_KINDS)}")
            elif rule.get("retire_safe") is not False:
                bad("a lock row must carry `retire_safe: false`: a lock file or folder is never put in a retire list")
        if "hook_written" in rule:
            # t-298: the flag only SUBTRACTS from retirement, so every shape that could make it add something,
            # or hide a file the install itself rebuilds, is refused here (one error per row).
            if not isinstance(rule["hook_written"], bool):
                bad("`hook_written` must be true or false")
            elif rule["hook_written"]:
                if rule.get("class") != "regenerated":
                    bad("`hook_written` belongs on a regenerated row only: a carried path is never retired anyway, and nothing else "
                        "is rewritten by a running session's hooks")
                elif "retire_mode" in rule or "discard_when" in rule:
                    bad("a `hook_written` row carries no `retire_mode` and no `discard_when`: a file a running session rewrites is "
                        "never retired, by any rule")
                elif isinstance(glob, str) and glob and any(_match(o.split("/"), glob.split("/"), False) for o in _step_outputs(table)):
                    bad("a `hook_written` glob must not cover an output of a `regenerate_step`: flagging it would drop a file the "
                        "install rebuilds from the manifest and from the reinstall-equals-fresh comparison")
        if "before_install" in rule:
            # B-411: the flag only SUBTRACTS (a flagged path is not counted as a trace of an install), so every
            # shape that could make it hide a real trace is refused here: a value that is not a real bool, a row
            # that is not carried (a regenerated or discarded file IS the old factory's), and a glob that overlaps
            # another row's (flagging the notes folder must not flag a path some other row names too).
            if not isinstance(rule["before_install"], bool):
                bad("`before_install` must be true or false")
            elif rule["before_install"]:
                if rule.get("class") != "carried":
                    bad("`before_install` belongs on a carried row only: a regenerated or discarded path is what an "
                        "earlier install left, and must keep counting as a trace of one")
                elif isinstance(glob, str) and glob:
                    mine = glob.split("/")
                    for other in table["rules"]:
                        if other is rule or not isinstance(other, dict) or not isinstance(other.get("glob"), str):
                            continue
                        theirs = other["glob"].split("/")
                        if _match(theirs, mine, False) or _match(mine, theirs, False):
                            bad(f"a `before_install` glob must not overlap another row's: {glob!r} and {other['glob']!r} "
                                "can name the same path, and flagging it would hide an install trace the other row names")
                            break
        if "moved_to" in rule:
            target = rule["moved_to"]
            if rule.get("class") != "carried":
                bad("`moved_to` belongs on a carried row only: nothing else is moved by a reinstall")
            elif not isinstance(target, str) or not isinstance(glob, str) or glob.endswith("/**") != target.endswith("/**") \
                    or any(ch in (glob[:-3] if glob.endswith("/**") else glob) + (target[:-3] if target.endswith("/**") else target)
                           for ch in "*?"):
                bad("`moved_to` must be the new path of the same record: a file for a file, `dir/**` for `dir/**`, no other pattern")
        cond = rule.get("discard_when")
        if cond is not None and not (isinstance(cond, dict) and isinstance(cond.get("json_field"), str)
                                     and isinstance(cond.get("differs_from"), str)):
            bad("`discard_when` must be {json_field, differs_from}")
    for i, folder in enumerate(table.get("folders") or []):
        if not (isinstance(folder, dict) and isinstance(folder.get("path"), str) and folder["path"]
                and isinstance(folder.get("tracked"), bool)):
            errors.append({"code": "shape", "glob": f"folders[{i}]", "message":
                           "a folder entry needs a `path` and `tracked` (true: git keeps what is in it; false: git ignores it)"})
    steps = table.get("regenerate_step")
    if steps is not None and not isinstance(steps, list):
        errors.append({"code": "shape", "glob": "regenerate_step", "message": "`regenerate_step` must be a list of {script, outputs[]}"})
    for i, step in enumerate(steps if isinstance(steps, list) else []):
        label = f"regenerate_step[{i}]"
        if not (isinstance(step, dict) and isinstance(step.get("script"), str) and step["script"]
                and isinstance(step.get("outputs"), list)):
            errors.append({"code": "shape", "glob": label, "message": "a regenerate step needs a `script` (a name under scripts/) and an `outputs` list"})
            continue
        for out in step["outputs"]:
            rel, why = normalize_rel(out)
            if why is not None or rel != out or any(ch in out for ch in "*?"):
                errors.append({"code": "shape", "glob": label, "message":
                               f"output {out!r} must be ONE literal project-relative path with forward slashes (no glob): "
                               "it names a file the script writes"})
    block = table.get("gitignore_block")
    inside = block.get("inside_tracked", []) if isinstance(block, dict) else None
    if block is not None and not (isinstance(inside, list) and all(isinstance(x, str) and x for x in inside)):
        errors.append({"code": "shape", "glob": "gitignore_block", "message":
                       "`gitignore_block.inside_tracked` must be a list of `.gitignore` lines"})
    return errors


def _under(glob: str, folder: str) -> bool:
    return glob == folder or glob.startswith(folder + "/")


def _layout_errors(table: dict) -> list:
    """The two-folder rule (owner, t-232 F7+F8), checked against the table's own rows so the
    `.gitignore` block derived from it cannot hide a record or commit a machine-local file:
      * a carried row that is not machine-local must not sit in an UNTRACKED folder (git would never
        see it) - unless it carries `moved_to`, which declares the old place of a record being moved;
      * a machine-local row must not sit in a TRACKED folder (it would be committed);
      * `moved_to` must be a carried, non-machine-local row of its own, in a tracked folder, and the
        old place must be in an untracked one."""
    errors = []
    rows = [r for r in table.get("rules") or [] if isinstance(r, dict) and isinstance(r.get("glob"), str)
            and r.get("class") in PRECEDENCE]
    by_glob = {r["glob"].casefold(): r for r in rows}
    cleaned = folders(table)
    tracked = [f["path"] for f in cleaned if f["tracked"]]
    untracked = [f["path"] for f in cleaned if not f["tracked"]]
    for r in rows:
        glob, local = r["glob"], bool(r.get("machine_local", False))
        if r["class"] == "carried" and not local and "moved_to" not in r:
            hit = next((f for f in untracked if _under(glob, f)), None)
            if hit:
                errors.append({"code": "folder_mismatch", "glob": glob, "message":
                               f"{glob!r} is a carried record inside {hit!r}, which git ignores whole: a record there is never "
                               "committed. Put it in the tracked folder, or mark it `machine_local` if it differs per machine"})
        if local:
            hit = next((f for f in tracked if _under(glob, f)), None)
            if hit:
                errors.append({"code": "folder_mismatch", "glob": glob, "message":
                               f"{glob!r} is machine-local but sits inside {hit!r}, which git keeps: it would be committed. "
                               "Put it in the ignored folder"})
        if "moved_to" in r and isinstance(r["moved_to"], str):
            target = by_glob.get(r["moved_to"].casefold())
            if target is None or target["class"] != "carried" or target.get("machine_local"):
                errors.append({"code": "folder_mismatch", "glob": glob, "message":
                               f"{glob!r} is moved to {r['moved_to']!r}, which is not a carried, non-machine-local row of this table: "
                               "add that row, or fix `moved_to`"})
            if not any(_under(r["moved_to"], f) for f in tracked):
                errors.append({"code": "folder_mismatch", "glob": glob, "message":
                               f"{glob!r} is moved to {r['moved_to']!r}, which is not inside a tracked folder: a moved record must land "
                               "where git keeps it"})
            if not any(_under(glob, f) for f in untracked):
                errors.append({"code": "folder_mismatch", "glob": glob, "message":
                               f"{glob!r} carries `moved_to` but is not inside an untracked folder: only the old place of a record "
                               "an earlier factory kept in the machine-local folder is moved"})
    return errors


def validate_table(package_root=None, table: dict | None = None) -> dict:
    """Refuse a table that contradicts itself or the package. -> {ok, rules, errors[], grep{}}.

    errors[] items: {code, glob, message}; codes: shape, class_overlap (one glob text in two
    classes -- names both), duplicate_glob, reader_missing (the reader file is not in the
    package), reader_key_absent (the declared reader does not contain the glob's key),
    reader_contradicted (`reader: none` but the key appears in package text), grep_control_failed,
    folder_mismatch (a record in the ignored folder, a machine-local file in the tracked one, or a
    `moved_to` that does not land in a tracked folder), regenerate_script_missing / regenerate_output_unrowed
    (a `regenerate_step` script that is not in the package, or an output the table does not know as
    regenerated or carried).

    G4: `reader: none` is VERIFIED, not declared. The grep that finds no reader must first find a
    known one -- the control is the first declared reader's key through the SAME function and the
    same case profile; if the control is not found, the grep is a miscall and every `none` is
    refused as unverifiable instead of trusted. The contradiction check runs on DISCARDED `none`
    rows only (a carried / not_ours path is never retired; the control still runs for any `none`)."""
    package_root = Path(package_root or PLUGIN_ROOT)
    if table is None:
        try:
            table = json.loads((package_root / TABLE_REL).read_text(encoding="utf-8-sig"))
        except (OSError, ValueError) as exc:
            return {"ok": False, "rules": 0, "grep": {"control_key": None, "control_found": False, "files_scanned": 0},
                    "errors": [{"code": "shape", "glob": "", "message": f"{package_root / TABLE_REL} is unreadable ({exc})"}]}
    errors = _shape_errors(table)
    grep_info = {"control_key": None, "control_found": False, "files_scanned": 0}
    if any(e["glob"] == "" for e in errors):
        return {"ok": False, "rules": 0, "errors": errors, "grep": grep_info}
    rules = [r for r in table["rules"] if isinstance(r, dict) and isinstance(r.get("glob"), str)
             and r.get("class") in PRECEDENCE]
    seen: dict = {}
    for r in rules:
        text = r["glob"].casefold()
        if text in seen:
            first = seen[text]
            if first["class"] != r["class"]:
                errors.append({"code": "class_overlap", "glob": r["glob"], "message":
                               f"glob {r['glob']!r} is in two classes ({first['class']} and {r['class']}); a carried "
                               "path never appears in a retire listing -- keep the glob in ONE class"})
            else:
                errors.append({"code": "duplicate_glob", "glob": r["glob"], "message":
                               f"glob {r['glob']!r} is listed twice in class {r['class']}; keep one row"})
        else:
            seen[text] = r
    errors.extend(_layout_errors(table))
    # t-272 item 1: what a regenerate script is declared to rebuild must be a path the table knows as
    # regenerated or carried (never something a reinstall would retire or move), and the script must exist.
    for step in [s for s in table.get("regenerate_step") or [] if isinstance(s, dict) and isinstance(s.get("script"), str)
                 and isinstance(s.get("outputs"), list)]:
        if not (package_root / "scripts" / step["script"]).is_file():
            errors.append({"code": "regenerate_script_missing", "glob": step["script"], "message":
                           f"regenerate step script {step['script']!r} is not in the package (scripts/); name the script that rebuilds the outputs"})
        for out in step["outputs"]:
            got = classify(out, table=table, casefold=False)
            if got["class"] not in ("regenerated", "carried"):
                errors.append({"code": "regenerate_output_unrowed", "glob": str(out), "message":
                               f"{out!r} is declared an output of {step['script']} but the table classifies it {got['class']!r}: "
                               "add a regenerated row for it, so a reinstall rebuilds it and never retires or moves it"})
    corpus = _corpus(package_root)
    grep_info["files_scanned"] = len(corpus)
    readers = [r for r in rules if isinstance(r.get("reader"), str) and r["reader"] != "none" and _key_of(r)]
    for r in readers:
        path = _reader_path(package_root, r["reader"])
        text = _read_lower(path)
        if text is None:
            errors.append({"code": "reader_missing", "glob": r["glob"], "message":
                           f"reader {r['reader']!r} of {r['glob']!r} is not in the package ({path}); name a script that "
                           "reads the path, or `none`"})
        elif _key_of(r).casefold() not in text:
            errors.append({"code": "reader_key_absent", "glob": r["glob"], "message":
                           f"reader {r['reader']!r} does not contain {_key_of(r)!r}, the key of {r['glob']!r}; name the "
                           "script that does (grep the package), or set the row's `key`"})
    nones = [r for r in rules if r.get("reader") == "none"]
    if nones:
        control = next((r for r in readers if _key_of(r).casefold() in (_read_lower(_reader_path(package_root, r["reader"])) or "")), None)
        if control is not None:
            grep_info["control_key"] = _key_of(control)
            grep_info["control_found"] = bool(_grep(corpus, _key_of(control)))
        if control is None or not grep_info["control_found"]:
            errors.append({"code": "grep_control_failed", "glob": "", "message":
                           "the grep of the package could not find a key that a declared reader contains, so its silence "
                           "about the `none` rows proves nothing; check the package root, then run again"})
        else:
            # Only a DISCARDED row can be wrongly retired because "nothing reads it": a carried or
            # not_ours row is never retired, so a mention of its key proves nothing (t-239 O1-2:
            # `pre-0.7.0-recovery` is carried with reader none, and the package names it in text).
            # `.md` stays in the corpus: roles are readers.
            for r in (r for r in nones if r["class"] == "discarded"):
                key = _key_of(r)
                hits = _grep(corpus, key)
                if hits:
                    errors.append({"code": "reader_contradicted", "glob": r["glob"], "message":
                                   f"{r['glob']!r} declares reader `none`, but {key!r} appears in {', '.join(hits[:3])}"
                                   f"{' ...' if len(hits) > 3 else ''}; name that file as the reader, or remove the mention"})
    return {"ok": not errors, "rules": len(rules), "errors": errors, "grep": grep_info}


# --- the manifest ----------------------------------------------------------------------------

def _manifest_path(root) -> Path:
    return Path(root, *MANIFEST_REL.split("/"))


def _unreadable(reason: str) -> dict:
    return {"status": "unreadable", "reason": reason, "schema_version": None, "package_version": None,
            "plugin_version": None, "newer": None, "entries": [], "refused": []}


def read_manifest(root, *, plugin_root=None, casefold: bool | None = None):
    """None when there is no manifest (every project before the first new-generation install --
    nothing may be retired on its word). Otherwise always the same keys (FR-14):

      status ('ok' | 'unreadable'), reason (None | why), schema_version, package_version,
      plugin_version, newer (True | False | None), entries[], refused[].

    'unreadable' (bad JSON, wrong shape, unknown schema) is UNKNOWN, not "no manifest": callers
    fall back to the table and retire nothing on the manifest's word (FR-41). `newer` is True
    when the manifest (or any entry) names a package version above the plugin's -- callers
    retire nothing then; None when the plugin's own version could not be read (also: no retiring).
    entries[] items: {rel_path, class, machine_local, package_version, input_hash} plus `sha256`
    on every non-machine-local entry. An entry that is adversarial (`../x`, `C:x`, a symlink out
    of the root) or malformed is moved to refused[] ({rel_path, reason}) and never returned."""
    fold = _fold_default() if casefold is None else casefold
    path = _manifest_path(root)
    if not os.path.lexists(path):
        return None
    if not path.is_file():
        return _unreadable(f"{MANIFEST_REL} is not a file; expected the JSON that write_manifest writes")
    try:
        data = json.loads(path.read_bytes().decode("utf-8-sig"))
    except (OSError, ValueError) as exc:
        return _unreadable(f"{MANIFEST_REL} is not valid JSON ({exc}); expected the JSON that write_manifest writes -- "
                           "move the file aside, the factory will not guess its content")
    if not isinstance(data, dict) or data.get("schema_version") != MANIFEST_SCHEMA or not isinstance(data.get("entries"), list):
        return _unreadable(f"{MANIFEST_REL} has the wrong shape (expected an object with schema_version {MANIFEST_SCHEMA} "
                           "and an `entries` list) -- it may come from a newer factory; update the plugin or move the file aside")
    top_version = data.get("package_version")
    if _vtuple(top_version) is None:
        return _unreadable(f"{MANIFEST_REL} has no readable `package_version` (got {top_version!r}); expected 'N.N.N'")
    try:
        mine = plugin_version(plugin_root)
    except ValueError:
        mine = None
    entries, refused, seen, versions = [], [], set(), [top_version]
    for raw in data["entries"]:
        raw_rel = raw.get("rel_path") if isinstance(raw, dict) else None
        rel, why = normalize_rel(raw_rel)
        if why is None:
            _, why = _resolve_inside(root, rel) if os.path.lexists(Path(root, *rel.split("/"))) else (None, None)
        if why is None and not isinstance(raw, dict):
            why = "an entry must be an object"
        if why is None and raw.get("class") not in ENTRY_CLASSES:
            why = f"`class` must be one of {list(ENTRY_CLASSES)}"
        local = bool(raw.get("machine_local")) if why is None else False
        if why is None and raw.get("machine_local") not in (None, True, False):
            why = "`machine_local` must be true or false"
        if why is None and local and "sha256" in raw:
            why = "a machine-local entry must carry no sha256 (a clone would read it as changed)"
        if why is None and not local and not re.fullmatch(r"[0-9a-f]{64}", str(raw.get("sha256", ""))):
            why = "a non-machine-local entry needs a 64-hex `sha256`"
        version = raw.get("package_version", top_version) if why is None else None
        if why is None and _vtuple(version) is None:
            why = f"`package_version` {version!r} is not 'N.N.N'"
        if why is None and not isinstance(raw.get("input_hash", ""), str):
            why = "`input_hash` must be text"
        if why is None and _key(rel, fold) in seen:
            why = "listed twice"
        if why is not None:
            refused.append({"rel_path": rel if rel is not None else str(raw_rel), "reason": why})
            continue
        seen.add(_key(rel, fold))
        versions.append(version)
        entry = {"rel_path": rel, "class": raw["class"], "machine_local": local, "package_version": version,
                 "input_hash": raw.get("input_hash", "")}
        if not local:
            entry["sha256"] = raw["sha256"]
        entries.append(entry)
    newer = None
    if mine is not None:
        newer = any(_vless(_vtuple(mine), _vtuple(v)) for v in versions)
    return {"status": "ok", "reason": None, "schema_version": MANIFEST_SCHEMA, "package_version": top_version,
            "plugin_version": mine, "newer": newer, "entries": entries, "refused": refused}


def _atomic_write(path: Path, data: bytes) -> None:
    """Temp file in the same directory, flushed, then `os.replace`: the reader sees the old
    manifest or the whole new one. On any failure the temp file is removed and the old manifest
    (or its absence) stands."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f"{path.name}.tmp-{os.getpid()}")
    try:
        with open(temp, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    except BaseException:
        try:
            os.unlink(temp)
        except OSError:
            pass
        raise


def write_manifest(root, entries, *, input_hash: str = "", plugin_root=None, table: dict | None = None,
                   casefold: bool | None = None) -> dict:
    """Write `qa-factory/install-manifest.json` for the paths this run wrote -- the caller does
    it LAST, after every file it lists exists. -> {path, written[], refused[], package_version}.

    `entries`: project-relative paths (str) or {rel_path, class?, machine_local?, input_hash?}.
    Class comes from the table unless given; a path the table does not recognise and no class
    given is refused (a gap in the table is a defect to see, not to paper over). A non-machine-
    local entry must be an existing regular file inside the root: its sha256 is taken NOW, from
    disk. A machine-local entry carries class and `machine_local: true` and no sha. Adversarial
    entries are refused, listed, never read. Deterministic: sorted, no timestamp, LF newlines --
    the same tree gives the same bytes (the equality check compares trees). Atomic."""
    fold = _fold_default() if casefold is None else casefold
    table = table if table is not None else load_table(plugin_root)
    version = plugin_version(plugin_root)
    out, refused, seen = [], [], set()
    for item in entries:
        spec = item if isinstance(item, dict) else {"rel_path": item}
        rel, why = normalize_rel(spec.get("rel_path"))
        found = None
        if why is None:
            found = classify(rel, table=table, casefold=fold)
            cls = spec.get("class") or found["class"]
            local = bool(spec.get("machine_local", found["machine_local"]))
            if cls not in ENTRY_CLASSES:
                why = (f"class {cls!r} is not one the manifest can hold; the table does not recognise this path -- add a "
                       "row to references/install-paths.json or pass `class`") if cls in ("unrecognised", "not_ours") \
                    else f"class {cls!r} is not one of {list(ENTRY_CLASSES)}"
        if why is None and _key(rel, fold) in seen:
            why = "listed twice"
        sha = None
        if why is None and not local:
            path, why = _resolve_inside(root, rel)
            if why is None and not path.is_file():
                why = "not a file on disk -- the manifest never lists a path that was not written"
            if why is None:
                try:
                    sha = sha256_file(path)
                except OSError as exc:
                    why = f"cannot be read ({exc})"
        if why is None and local:
            _, why = _resolve_inside(root, rel)
        if why is not None:
            refused.append({"rel_path": rel if rel is not None else str(spec.get("rel_path")), "reason": why})
            continue
        seen.add(_key(rel, fold))
        record = {"rel_path": rel, "class": cls, "package_version": version,
                  "input_hash": str(spec.get("input_hash", input_hash))}
        if local:
            record["machine_local"] = True
        else:
            record["sha256"] = sha
        out.append(record)
    out.sort(key=lambda r: _key(r["rel_path"], fold))
    body = {"schema_version": MANIFEST_SCHEMA, "package_version": version, "entries": out}
    _atomic_write(_manifest_path(root), (json.dumps(body, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))
    return {"path": MANIFEST_REL, "written": [r["rel_path"] for r in out], "refused": refused, "package_version": version}


def verify_manifest(root, *, plugin_root=None) -> dict:
    """Does the disk still match the manifest? -> {ok, status, mismatches[], missing[], refused[],
    package_version, plugin_version, package_version_ok}. A missing manifest is status 'absent',
    ok False (there is nothing to verify). Machine-local entries have no sha and are not compared."""
    manifest = read_manifest(root, plugin_root=plugin_root)
    shape = {"ok": False, "status": "absent", "mismatches": [], "missing": [], "refused": [],
             "package_version": None, "plugin_version": None, "package_version_ok": False}
    if manifest is None:
        return shape
    shape.update({"status": manifest["status"], "refused": manifest["refused"],
                  "package_version": manifest["package_version"], "plugin_version": manifest["plugin_version"]})
    if manifest["status"] != "ok":
        return shape
    for entry in manifest["entries"]:
        if entry["machine_local"]:
            continue
        path, why = _resolve_inside(root, entry["rel_path"])
        if path is None or not path.is_file():
            shape["missing"].append(entry["rel_path"])
        elif sha256_file(path) != entry["sha256"]:
            shape["mismatches"].append({"rel_path": entry["rel_path"], "expected": entry["sha256"],
                                        "actual": sha256_file(path)})
    shape["package_version_ok"] = manifest["package_version"] == manifest["plugin_version"] and all(
        e["package_version"] == manifest["plugin_version"] for e in manifest["entries"])
    shape["ok"] = not (shape["mismatches"] or shape["missing"] or shape["refused"]) and shape["package_version_ok"]
    return shape


# --- scan_tree: what a reinstall would write, retire and keep -----------------------------------

def scan_tree(root, written=(), *, manifest="auto", context: dict | None = None, table: dict | None = None,
              plugin_root=None, casefold: bool | None = None, retire_unbuilt: bool = False) -> dict:
    """Walk what the factory left under `root` and sort it. Writes nothing, deletes nothing.

    `written`: the project-relative paths THIS run writes or rebuilds (never retired, whatever the
    table says): the caller adds the regenerate step's outputs (`regenerate_outputs`) here.
    `manifest`: 'auto' (read it), or the dict read_manifest returned, or None.
    `context`: {"package_fingerprint": <installed fingerprint>} for rows with `discard_when`.
    `retire_unbuilt`: True when `written` names EVERYTHING this run rebuilds, so a regenerated file that
    is not in it is retired (t-272 item 1: "regenerated" means a script rebuilds it, and one that this
    run does not rebuild is a leftover). False (the default: a caller that does not know what it
    rebuilds) keeps the older rule - only a regenerated row with `discard_when` that proved stale.

    -> always these keys (FR-14):
      manifest: {status 'absent'|'ok'|'unreadable', reason, newer, package_version}
      retire[]: {rel_path, class, source ('table'|'manifest'|'table+manifest'), generation,
                 requires[], condition, retire_mode ('delete'|'move')}  -- candidates only; the
                 caller lists them and acts on the approved ones. `requires: ['fold_receipt']`
                 means do not retire without that proof. `retire_mode` comes from the row, else
                 from the table's per-class `retire_modes` (see `retire_modes()`).
      retire_blocked: None | 'newer_manifest' | 'plugin_version_unknown'  (then retire is [])
      changed_since_install[]: {rel_path, expected_sha256, actual_sha256, written}  -- kept
      not_ours_kept[]: {rel_path, generation, reason}  -- reason: the row's own text (e.g. "the
                 project's dev factory (superpowers)"), 'earlier_generation' (a row with a
                 generation), 'not_ours', or 'unrecognised' (no row names it: an unrecognised FOLDER
                 inside the home is opened and each file below is its own item - the caller decides
                 what to do with them, onboard_apply sets them aside)
      locks[]: rel paths of `retire_safe: false` files (and `lock_kind: folder` folders, and any file or
                 folder under the home named `*.lock` that no row names) found (the live-lock check
                 and what becomes of each is the caller's)
      unknown[]: {rel_path, reason}  -- evidence missing (e.g. a smoke report with no readable
                 fingerprint); kept
      missing[]: manifest entries no longer on disk (nothing to retire)
      refused[]: {rel_path, reason}  -- adversarial manifest/`written` entries and symlinks out of
                 the root; never read or hashed

    Missing or empty root: every list empty, no error. Where the manifest and the table disagree
    the safe side wins: carried by either is kept; a path the table says is regenerated (a current
    reader rebuilds it) is not retired on the manifest's word."""
    fold = _fold_default() if casefold is None else casefold
    table = table if table is not None else load_table(plugin_root)
    rules = _rules(table)
    home = home_of(table)
    result = {"manifest": {"status": "absent", "reason": None, "newer": False, "package_version": None},
              "retire": [], "retire_blocked": None, "changed_since_install": [], "not_ours_kept": [],
              "locks": [], "unknown": [], "missing": [], "refused": []}
    root = str(root)
    if not os.path.isdir(root):
        return result
    real_root = _realpath(root)
    skip = set()
    for item in written:
        rel, why = normalize_rel(item)
        if why is not None:
            result["refused"].append({"rel_path": str(item), "reason": why})
        else:
            skip.add(_key(rel, fold))

    m = read_manifest(root, plugin_root=plugin_root, casefold=fold) if manifest == "auto" else manifest
    known, known_dirs, usable = set(), set(), []
    if m is not None:
        result["manifest"].update({"status": m["status"], "reason": m["reason"], "newer": m["newer"],
                                   "package_version": m["package_version"]})
        result["refused"].extend(m["refused"])
        if m["status"] == "ok":
            usable = m["entries"]
            for e in usable:
                k = _key(e["rel_path"], fold)
                known.add(k)
                parts = k.split("/")
                known_dirs.update("/".join(parts[:i]) for i in range(1, len(parts)))

    retire: dict = {}
    not_ours: dict = {}

    def add_retire(rel, cls, source, generation, requires, condition, row_mode=None):
        k = _key(rel, fold)
        if k in retire:
            retire[k]["source"] = "table+manifest" if retire[k]["source"] != source else source
            return
        retire[k] = {"rel_path": rel, "class": cls, "source": source, "generation": generation,
                     "requires": requires, "condition": condition, "retire_mode": _mode_of(row_mode, cls, table)}

    def visit(rel: str, is_dir: bool, is_link: bool) -> None:
        k = _key(rel, fold)
        if k in skip:
            return
        segs = rel.split("/")
        hits = [r for r in rules if _match(segs, r["segs"], fold)]
        if hits:
            hits.sort(key=lambda r: PRECEDENCE.index(r["class"]))
            win = hits[0]
            safe = all(r["retire_safe"] for r in hits)
            if is_dir and not is_link and win["class"] in ("discarded", "not_ours") and any(
                    PRECEDENCE.index(r["class"]) < PRECEDENCE.index(win["class"]) and _could_contain(segs, r["segs"], fold)
                    for r in rules):
                # A whole-directory unit must not swallow a path a stronger row claims below it:
                # open it and judge each child (carried below a discarded directory stays carried).
                descend(rel)
                return
            if win["class"] == "not_ours":
                # `reason`: the row's own text when it has one (the team's dev factory is not "an
                # earlier generation"); else the generation word; else plain "not_ours".
                not_ours[k] = {"rel_path": rel, "generation": win["generation"],
                               "reason": win["reason"] or ("earlier_generation" if win["generation"] is not None else "not_ours")}
            elif win["class"] == "discarded":
                if safe:
                    add_retire(rel, "discarded", "table", win["generation"], win["requires"], None, win["retire_mode"])
            elif win["class"] == "regenerated":
                if is_dir:
                    if any(r["lock_kind"] == "folder" for r in hits):
                        result["locks"].append(rel)           # a folder made with mkdir IS the lock: listed, never opened
                    elif retire_unbuilt and not is_link:
                        descend(rel)                          # judge each file below on its own row (a lock below stays a lock)
                elif not safe:
                    result["locks"].append(rel)
                elif any(r["hook_written"] for r in hits if r["class"] == "regenerated"):
                    pass        # a running session's hooks rewrite it (t-298): never a retire candidate, by any rule below
                elif win["discard_when"]:
                    state = _condition(win["discard_when"], root, rel, context)
                    if state == "foreign":
                        add_retire(rel, "discarded", "table", win["generation"], win["requires"], state,
                                   win["retire_mode"] or retire_modes(table)["regenerated_stale"])
                    elif state == "unknown":
                        result["unknown"].append({"rel_path": rel, "reason":
                                                  "its fingerprint could not be compared (an unreadable file, or no "
                                                  "installed fingerprint was given)"})
                elif retire_unbuilt:
                    # A file a current script rebuilds, which THIS run's regenerate step does not
                    # rebuild (it is not in `written`): technical data nothing will use again -
                    # retired under the one "yes", by name, with the class's mode (t-272 item 1).
                    # NOT a file a running session's hooks rewrite (`hook_written`, t-298): it is back by the
                    # time the person says "yes", so listing it only makes the apply refuse on a sha that moved.
                    add_retire(rel, "regenerated", "table", win["generation"], win["requires"], None,
                               win["retire_mode"] or retire_modes(table)["regenerated_stale"])
            return
        in_home = k == _key(home, fold) or k.startswith(_key(home, fold) + "/")
        if is_dir and not is_link:
            if rel.endswith(".lock") and in_home:
                result["locks"].append(rel)                   # an unrecognised folder named like a lock is left alone, whole
            elif in_home or any(_could_contain(segs, r["segs"], fold) for r in rules) or k in known_dirs:
                # Inside the factory's home an unrecognised folder is judged file by file (t-272 item 2):
                # a folder is never retired as a whole, so each file below is its own undetermined item.
                descend(rel)
            return
        if in_home and k not in known:
            if rel.endswith(".lock"):
                result["locks"].append(rel)                   # a lock nobody named is never moved aside
            else:
                not_ours[k] = {"rel_path": rel, "generation": None, "reason": "unrecognised"}

    def descend(rel: str) -> None:
        directory = os.path.join(root, *rel.split("/")) if rel else root
        try:
            with os.scandir(directory) as it:
                children = sorted(it, key=lambda e: e.name)
        except OSError:
            return
        for child in children:
            child_rel = f"{rel}/{child.name}" if rel else child.name
            try:
                is_link = child.is_symlink()
                is_dir = child.is_dir()
            except OSError:
                continue
            if (is_link or is_dir) and not _inside(real_root, _realpath(child.path)):
                result["refused"].append({"rel_path": child_rel, "reason": "resolves outside the project root (symlink or junction)"})
                continue
            visit(child_rel, is_dir, is_link)

    descend("")

    # The manifest's word: a path it lists that this run does not write.
    blocked = None
    if m is not None and m["status"] == "ok" and m["newer"] is not False:
        blocked = "newer_manifest" if m["newer"] else "plugin_version_unknown"
    for e in usable:
        if e["machine_local"]:
            continue
        rel, k = e["rel_path"], _key(e["rel_path"], fold)
        path, why = _resolve_inside(root, rel)
        if path is None:
            result["refused"].append({"rel_path": rel, "reason": why})
            continue
        if not path.is_file():
            result["missing"].append(rel)
            continue
        actual = sha256_file(path)
        if actual != e["sha256"]:
            result["changed_since_install"].append({"rel_path": rel, "expected_sha256": e["sha256"],
                                                    "actual_sha256": actual, "written": k in skip})
            continue
        if k in skip or e["class"] == "carried":
            continue
        c = classify(rel, table=table, casefold=fold, root=root, context=context)
        # `unrecognised` has retire_safe false by itself (classification never retires an unknown
        # path); here the manifest's sha is the evidence that the factory wrote it, untouched.
        if c["class"] in ("carried", "regenerated", "not_ours") or (c["class"] == "discarded" and not c["retire_safe"]):
            continue
        add_retire(rel, c["class"] if c["class"] == "discarded" else e["class"], "manifest", c["generation"],
                   c["requires"], c["condition"], c["retire_mode"])

    # Bytes the factory did not write are never retired, whichever source named them: the table
    # has no sha, so a changed manifest entry overrides a table row.
    changed = {_key(c["rel_path"], fold) for c in result["changed_since_install"]}
    for k in [k for k in retire if k in changed]:
        del retire[k]
    if blocked:
        result["retire_blocked"] = blocked
        for item in retire.values():
            result["unknown"].append({"rel_path": item["rel_path"], "reason":
                                      f"retirement is blocked ({blocked}): a newer factory wrote this project, update the "
                                      "plugin" if blocked == "newer_manifest" else
                                      f"retirement is blocked ({blocked}): the plugin's own version could not be read"})
        retire = {}
    result["retire"] = sorted(retire.values(), key=lambda r: r["rel_path"])
    result["not_ours_kept"] = sorted((v for k, v in not_ours.items() if k not in retire and k not in changed),
                                     key=lambda r: r["rel_path"])
    result["changed_since_install"].sort(key=lambda r: r["rel_path"])
    result["locks"].sort()
    result["unknown"].sort(key=lambda r: r["rel_path"])
    result["missing"].sort()
    return result
