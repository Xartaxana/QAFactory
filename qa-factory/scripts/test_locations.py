"""Where a project keeps its tests: the project's own word (D-0030, 06.10.2026) - the one reader.

A project names the places inside its application repository where its tests live, in the config key
`test_locations` (folders or file patterns relative to app_root, written like `protected_app_paths`). The
factory accepts them as project configuration and protects from change only the part that holds the
application code itself (P-00). The list of usual test names, `references/test-path-markers.json`, is a
suggestion at onboarding and a fallback for recognising tests when the project named none - never a
refusal and never a permission.

This module is the whole of that reading and nothing else writes it:

  is_test_path(path, cfg, base=, root=)   one verdict, six keys, never raises
  location_problems(cfg, root)            what in `test_locations` opens nothing, one sentence each
  whole_root_conflict(target, cfg, root)  the entry that covers a whole protected root and the root
  suggest(cfg, root, max_files)           candidate locations found by the usual test names
  check(cfg, root, max_files, candidates) what each entry (and each candidate) holds, counted
  markers() / pattern language            the usual test names and the pattern grammar (moved here from
                                          test_path_grants.py, which imports them)
  name_marker(name, table) / dir_marker   the one matcher of a file name (with the CamelCase endings, case-
                                          sensitive) and of a folder name; `test_files.py` builds on them

CLI (prints nothing but the answer; `--json` is the shape a role parses, FR-14):

  python test_locations.py --root <project> [--app-root R] [--protected P]... \
         (--suggest | --check [--candidate C]...) [--max-files N] [--json]

Permission is narrower than recognition. The verdict names its `source`; the guard opens a write only for
`source == "test_locations"` (the person's explicit word). `run.levels`, `profiles[].roots.test` and
`tests_root` are carriers of where tests live that were never permissions: they are recognised (so every
consumer reads ONE project word) and never open anything - an existing config must not silently widen what
is writable.

Pattern language, relative to app_root: `\\` is `/`; `*` inside a segment, `**` as a whole segment (zero or
more folders), `?`; a trailing `/` means `dir/**`; lower-cased like `hooklib.norm`, which is how a target is
compared (RESOLVED, so a symlink inside a test folder cannot lead into application code).
"""
import argparse
import fnmatch
import json
import os
import re
import sys
from functools import lru_cache
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import hooklib  # noqa: E402

CONFIG_KEY = "test_locations"
MARKERS_FILE = "test-path-markers.json"
MARKER_LISTS = ("dir_names", "dir_suffixes", "stem_prefixes", "stem_suffixes")
EXTRA_LISTS = ("stem_camel_suffixes", "code_extensions")   # B-407 A: optional; absent or malformed means []
BAD_CHARS = "[]{}!"
SOURCES = ("test_locations", "run.levels", "roots.test", "tests_root", "markers", "")
DEFAULT_MAX_FILES = 20000

WHOLE_ROOT = ("test_locations names all of {roots} ('{entry}'), which is also application code in "
              "protected_app_paths; the orchestrator asks the person which part of {first} holds the "
              "application code and records the answer with their words (project_decisions.py).")


# --- the markers (data, FR-13): a suggestion and a fallback, never a gate ----------------------------

def _extra_list(raw: dict, name: str) -> tuple:
    """([items], "") of an optional list of the markers file, ([], why) when it is absent or malformed. An
    item is stripped; `code_extensions` is lower-cased and carries its dot, `stem_camel_suffixes` keeps its case
    (the camel rule is case-sensitive)."""
    value = raw.get(name)
    if value is None:
        return [], f"'{name}' is absent"
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        return [], f"'{name}' is not a list of non-empty strings"
    items = [item.strip() for item in value]
    if name == "code_extensions":
        items = [("." + item.lstrip(".")).lower() for item in items]
    return items, ""


def markers() -> tuple:
    """({list name: [lower-case markers]}, "") or ({}, why it cannot be used).

    Missing, unreadable, or not the expected shape is one answer: the markers cannot be read, so no path
    can be recognised by its name. `problem` (the second item) concerns only the four lists: it is what
    every grant and B-415's guard depend on, and it is never set by an extra list. The table also carries
    `stem_camel_suffixes` and `code_extensions` (B-407 A) and `extras_problem`: an extra list that is absent
    or malformed is `[]` and named there, and nothing else changes (a world without the extras reads as
    before). Any other key is ignored (`skip_dirs` is read by `skip_dirs()`). `hooklib.load_ref_json` is how
    every reference table is loaded; it gives {} for a file it cannot read."""
    raw = hooklib.load_ref_json(MARKERS_FILE)
    if not isinstance(raw, dict) or not raw:
        return {}, "missing, unreadable or empty"
    table = {}
    for name in MARKER_LISTS:
        value = raw.get(name)
        if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
            return {}, f"not the expected shape ('{name}' must be a list of non-empty strings)"
        table[name] = [item.strip().lower() for item in value]
    extras = []
    for name in EXTRA_LISTS:
        table[name], why = _extra_list(raw, name)
        if why:
            extras.append(why)
    table["extras_problem"] = "; ".join(extras)
    return table, ""


def name_marker(segment, table: dict) -> str:
    """`"<list>:<marker>"` when the last path segment (a file name, as the caller wrote it: original case) carries a
    usual test name, else "". The one matcher of a file name, used by step 4, `suggest`, `check` and
    `test_files.names_a_test`.

    In order: the stem (the name without its final extension, lower-cased) against `stem_prefixes` and
    `stem_suffixes`; then `stem_camel_suffixes` on the stem AS WRITTEN: it ends with the ending, at least one
    character stands before it, and an ending in capitals (`IT`) is not preceded by a capital (`AUDIT`,
    `SUBMIT`), so `FooTests`, `UITest`, `FooIT` are tests and `Test`, `AUDIT`, `Latest`, `MyTEST` are not."""
    last = str(segment or "")
    low = last.lower()
    stem = low.rpartition(".")[0] if "." in low else low
    for marker in table.get("stem_prefixes", ()):
        if stem.startswith(marker):
            return f"stem_prefixes:{marker}"
    for marker in table.get("stem_suffixes", ()):
        if stem.endswith(marker):
            return f"stem_suffixes:{marker}"
    written = last.rpartition(".")[0] if "." in last else last
    for suffix in table.get("stem_camel_suffixes", ()):
        if not written.endswith(suffix) or len(written) <= len(suffix):
            continue
        if suffix.isupper() and written[-len(suffix) - 1].isupper():
            continue
        return f"stem_camel_suffixes:{suffix}"
    return ""


def skip_dirs() -> list:
    """Folder names the walk of `--suggest` / `--check` never enters (dependencies, build output). Optional
    data in the markers file: absent or not a list of strings means no skips."""
    raw = hooklib.load_ref_json(MARKERS_FILE)
    value = raw.get("skip_dirs") if isinstance(raw, dict) else None
    if not isinstance(value, list):
        return []
    return [item.strip().lower() for item in value if isinstance(item, str) and item.strip()]


# --- the pattern language ------------------------------------------------------------------------

def _text(p) -> str:
    return str(p if p is not None else "").strip().replace("\\", "/")


def _segments(text: str) -> list:
    """The segments of a normalised pattern: empty and `.` dropped, a trailing `/` becomes `**`."""
    parts = [s for s in text.lower().split("/") if s not in ("", ".")]
    if parts and text.endswith("/"):
        parts.append("**")
    return parts


def _grammar_problem(text: str) -> str:
    """What is wrong with the pattern as written, in the words of the refusal; "" when nothing."""
    if not text.strip():
        return "empty"
    if text.startswith("/") or re.match(r"^[A-Za-z]:", text):
        return "an absolute path"
    if ".." in text.split("/"):
        return "outside it ('..')"
    for char in text:
        if char in BAD_CHARS:
            return f"using '{char}', which this pattern language does not have (only *, ** and ?)"
    if not _segments(text):
        return "empty"
    return ""


@lru_cache(maxsize=512)
def _segment_re(segment: str):
    return re.compile("".join("[^/]*" if c == "*" else "[^/]" if c == "?" else re.escape(c)
                              for c in segment) + r"\Z")


def _match(pattern: tuple, path: tuple) -> bool:
    """Does the pattern (segments) match the path (segments)? `**` is zero or more whole segments."""
    @lru_cache(maxsize=None)
    def go(i: int, j: int) -> bool:
        if i == len(pattern):
            return j == len(path)
        if pattern[i] == "**":
            return go(i + 1, j) or (j < len(path) and go(i, j + 1))
        return j < len(path) and bool(_segment_re(pattern[i]).match(path[j])) and go(i + 1, j + 1)
    return go(0, 0)


def _roots(cfg, app_root) -> list:
    """[(the entry as configured, its segments relative to app_root)] for every protected root that
    lies under app_root. A pattern is relative to app_root, so a root outside it cannot hold one."""
    base = hooklib.norm(str(app_root)).rstrip("/")
    out = []
    for entry in (cfg or {}).get("protected_app_paths") or []:
        if not isinstance(entry, str) or not entry.strip():
            continue
        full = hooklib.norm(str(Path(app_root) / entry))
        if full == base:
            rel = ""
        elif full.startswith(base + "/"):
            rel = full[len(base) + 1:]
        else:
            continue
        shown = entry.strip().replace("\\", "/").rstrip("/") or "."
        out.append((shown, tuple(s for s in rel.split("/") if s)))
    return out


def _opens_boundary(segs: list, roots: list):
    """(root as configured, "root" | "holder") when the pattern opens a protected root or the folder
    that holds one, else None.

    Three readings, the first that hits wins: a wildcard-only last segment (empty after removing
    `*`, `?`, `.`) whose literal folder prefix is a root or its parent (`src/**`, `src/*.*`, `src/`);
    a pattern that matches the root itself; a pattern that matches an ancestor of it."""
    wildcard_only = not re.sub(r"[*?.]", "", segs[-1])
    folder = segs[:-1]
    literal = []
    for part in folder:
        if "*" in part or "?" in part:
            break
        literal.append(part)
    # a folder segment of nothing but wildcards that holds a `*` (`*`, `**`, `?*`) matches any folder, so it
    # reaches the root's whole content exactly as `**` does: `testproject1/*/`, `testproject1/?*/`, `testproject1/*/**` open
    # everything under `testproject1` (the critic's probe, t-529 F1). A lone `?` is one character: not "any".
    only_stars_after = all("*" in part and not re.sub(r"[*?.]", "", part) for part in folder[len(literal):])
    for shown, root in roots:
        if wildcard_only and only_stars_after:
            if tuple(literal) == root:
                return shown, "root"
            if root and tuple(literal) == root[:-1]:
                return shown, "holder"
        if _match(tuple(segs), root):
            return shown, "root"
        if any(_match(tuple(segs), root[:k]) for k in range(1, len(root))):
            return shown, "holder"
    return None


def _effective(text: str) -> list:
    """The segments an entry of `test_locations` matches with: an entry that ends in `/`, or whose last
    segment holds no `*` or `?`, means that folder and everything below it (a slashless folder name is
    the common way to write one: 'src/legacy/checks'); any other entry is the waiver language as it is."""
    segs = _segments(text)
    if segs and not text.endswith("/") and not any(c in segs[-1] for c in "*?"):
        segs.append("**")
    return segs


# --- one project's view ----------------------------------------------------------------------------

def _norm(path) -> str:
    return hooklib.norm(str(path))


def _rel(t: str, base: str):
    """The segments of `t` below `base` (both normalised), () when they are the same, None when `t` is not
    inside `base`."""
    b, x = base.rstrip("/"), t.rstrip("/")
    if x == b:
        return ()
    if x.startswith(b + "/"):
        return tuple(s for s in x[len(b) + 1:].split("/") if s)
    return None


def _inside(t: str, base: str) -> bool:
    return _rel(t, base) is not None


class _Ctx:
    """The project root, app_root, the protected roots and the live entries of one config, resolved once."""

    def __init__(self, cfg, root):
        self.cfg = cfg if isinstance(cfg, dict) else {}
        top = Path(root) if root is not None else hooklib.project_root()
        self.root_p = top.resolve()
        self.root_n = _norm(self.root_p)
        raw = str(self.cfg.get("app_root") or ".").strip() or "."
        given = Path(raw)
        self.app_p = (given if given.is_absolute() else self.root_p / given).resolve()
        self.app_n = _norm(self.app_p)
        listed = self.cfg.get("protected_app_paths")
        listed = listed if isinstance(listed, list) else []
        self.roots = _roots({"protected_app_paths": listed}, self.app_p)
        self.protected = []  # (shown, absolute normalised, the entry as written)
        for entry in listed:
            if isinstance(entry, str) and entry.strip():
                shown = entry.strip().replace("\\", "/").rstrip("/") or "."
                self.protected.append((shown, _norm(self.app_p / entry.strip()), entry.strip()))
        self._entries = None

    def entries(self) -> list:
        """[(entry as written, effective segments, the protected roots it covers whole)] of every LIVE entry
        of `test_locations`: a non-empty string with no grammar problem. A value that is not a list has none."""
        if self._entries is None:
            found = []
            value = self.cfg.get(CONFIG_KEY)
            for item in value if isinstance(value, list) else []:
                if not isinstance(item, str) or not item.strip() or _grammar_problem(_text(item)):
                    continue
                segs = tuple(_effective(_text(item)))
                covered = [(shown, rsegs) for shown, rsegs in self.roots
                           if _opens_boundary(list(segs), [(shown, rsegs)])]
                found.append((item.strip(), segs, covered))
            self._entries = found
        return self._entries

    def at_or_above(self, prefix: str) -> bool:
        """Is `prefix` the project root, app_root or a folder above either?"""
        return _inside(self.root_n, prefix) or _inside(self.app_n, prefix)


def _verdict(test: bool, by: str, source: str, kind: str, where: str, reason: str) -> dict:
    return {"test": bool(test), "by": by, "source": source, "kind": kind, "where": where, "reason": reason}


# --- the verdict -----------------------------------------------------------------------------------

def _config_match(ctx: _Ctx, t_rel):
    """((entry, kind) of the first entry that counts for this target or None, the first (entry, root shown)
    that matched but covers a protected root whole that holds the target or None)."""
    conflict = None
    if t_rel is None:
        return None, None
    for entry, segs, covered in ctx.entries():
        if not _match(segs, t_rel):
            continue
        held = [shown for shown, rsegs in covered if t_rel[:len(rsegs)] == rsegs]
        if held:
            conflict = conflict or (entry, held[0])  # protection wins per target (F3)
            continue
        return (entry, "folder" if segs[-1] == "**" else "file"), conflict
    return None, conflict


def _glob_literal(text: str) -> str:
    """`fnmatch` reads `[`, `*`, `?` in a resolved path as wildcards; the literal prefix must not."""
    return "".join(f"[{c}]" if c in "[*?" else c for c in text)


def _split_pattern(ctx: _Ctx, value: str):
    """(absolute normalised literal prefix, the wildcard remainder lower-cased, remainder is wildcard-only)
    of a project-root-relative pattern: its literal leading segments are joined to the project root and
    resolved, the rest is kept as written. Joined to the project root, a pattern with `..` that leaves
    app_root still names the same place the project's own readers match."""
    parts = value.strip().replace("\\", "/").split("/")
    literal, rest = [], []
    for i, seg in enumerate(parts):
        if any(c in seg for c in "*?["):
            rest = parts[i:]
            break
        literal.append(seg)
    base = Path("/".join(literal)) if "/".join(literal) else Path(".")
    prefix = _norm(base if base.is_absolute() else ctx.root_p / base)
    kept = [s for s in rest if s not in ("", ".")]
    return prefix, "/".join(kept).lower(), all(not re.sub(r"[*?.]", "", s) for s in kept)


def _recognition(ctx: _Ctx, t: str):
    """(source, where, kind) of the first recognition-only carrier that names `t`, else None. These
    carriers (`run.levels`, `profiles[].roots.test`, `tests_root`) never grant anything: they say where
    the project's tests are, and every consumer reads them through this one function.

    A value that names the whole project or the application (`""`, `"."`, a prefix at or above the project
    root or app_root with nothing but wildcards after it) is ignored, and so is one that covers a protected
    root whole when `t` lies in that root: a carrier never makes everything a test (S12, S13)."""
    def held_whole(prefix: str, wild_only: bool) -> bool:
        return wild_only and any(_inside(t, absolute) and _inside(absolute, prefix)
                                 for _shown, absolute, _entry in ctx.protected)

    run = ctx.cfg.get("run")
    levels = run.get("levels") if isinstance(run, dict) else None
    for level, patterns in (levels.items() if isinstance(levels, dict) else []):
        for value in patterns if isinstance(patterns, list) else [patterns]:
            if not isinstance(value, str) or not value.strip():
                continue
            prefix, rest, wild_only = _split_pattern(ctx, value)
            if (wild_only and ctx.at_or_above(prefix)) or held_whole(prefix, wild_only):
                continue
            pattern = _glob_literal(prefix) + ("/" + rest if rest else "")
            # `factory_dashboard.level_for`'s two forms; `*` crosses `/`, both sides are lower-case
            if fnmatch.fnmatchcase(t, pattern) or fnmatch.fnmatchcase(t, pattern.rstrip("/") + "/*"):
                kind = "folder" if (not rest or rest.endswith("**")) else "file"
                return "run.levels", f"run.levels:{level} {value}", kind
    profiles = ctx.cfg.get("profiles")
    carriers = []
    for profile in profiles if isinstance(profiles, list) else []:
        roots = profile.get("roots") if isinstance(profile, dict) else None
        if isinstance(roots, dict) and isinstance(roots.get("test"), str):
            carriers.append(("roots.test", f"profiles[{profile.get('profile_id') or ''}].roots.test",
                             roots["test"]))
    if isinstance(ctx.cfg.get("tests_root"), str):
        carriers.append(("tests_root", "tests_root", ctx.cfg["tests_root"]))
    for source, where, value in carriers:
        text = value.strip().replace("\\", "/")
        if not text:
            continue
        given = Path(text)
        prefix = _norm(given if given.is_absolute() else ctx.root_p / given)
        if ctx.at_or_above(prefix) or held_whole(prefix, True):
            continue
        if _inside(t, prefix):
            return source, where, "folder"
    return None


def _marker_hit(segs, is_folder: bool, table: dict, name: str = ""):
    """(list name, marker, kind) for a path given as lower-case segments, else None. Folder segments (every
    one but the last, or all of them for a folder) are checked against `dir_names` and `dir_suffixes` (a suffix
    needs at least one character before it); the last segment against `name_marker`, the one matcher of a file
    name. `name` is the last segment in its ORIGINAL case (the segments are lower-case, and the camel rule is
    case-sensitive); "" means the lower-case one."""
    folders = list(segs) if is_folder else list(segs[:-1])
    for part in folders:
        found = dir_marker(part, table)
        if found:
            return (*found.split(":", 1), "folder")
    if is_folder or not segs:
        return None
    found = name_marker(name or segs[-1], table)
    return (*found.split(":", 1), "file") if found else None


def _is_test_path(path, cfg, base, root) -> dict:
    ctx = _Ctx(cfg, root)
    text = str(path if path is not None else "")
    if not text.strip():
        return _verdict(False, "none", "", "", "", "no path was given")
    is_folder = text.endswith(("/", "\\"))
    given = Path(text)
    if not given.is_absolute():
        given = (Path(base) if base is not None else ctx.root_p) / given
    t = _norm(given)
    # 1. A colon after the drive is an alternate data stream (`app.ts:x.spec.ts`): a write to a stream of
    # an application file is never a test-location write, so no config carrier may match.
    stream = ":" in t[2:]
    if not stream:
        # 2. `test_locations` first: its match is never hidden by another carrier.
        hit, _conflict = _config_match(ctx, _rel(t, ctx.app_n))
        if hit:
            entry, kind = hit
            return _verdict(True, "config", "test_locations", kind, entry,
                            f"'{entry}' is one of the project's test locations (test_locations in "
                            "qa-factory/config.json)")
        # 2b. the other carriers of where tests live: recognition only
        found = _recognition(ctx, t)
        if found:
            source, where, kind = found
            return _verdict(True, "config", source, kind, where,
                            f"the project's own {where} names this place as tests; that recognises it and "
                            "grants nothing")
    # 3. inside application code, with the project's word given: only that word answers
    held = next((shown for shown, absolute, _entry in ctx.protected if _inside(t, absolute)), None)
    if held is not None and ctx.entries():
        return _verdict(False, "none", "", "", "",
                        f"inside application code '{held}' and in none of the project's test locations")
    # 4. the usual test names, relative to the DEEPEST of app_root and the project root that holds it
    bases = [b for b in (ctx.app_n, ctx.root_n) if _inside(t, b)]
    if not bases:
        return _verdict(False, "none", "", "", "", "outside the project and the application")
    deepest = max(bases, key=len)
    table, why = markers()
    if why:
        return _verdict(False, "none", "", "", "",
                        f"the list of usual test names (references/{MARKERS_FILE}) is {why}, so the name of "
                        "this path was not read")
    rel = _rel(t, deepest)
    # the camel rule is case-sensitive, and `t` is lower-case: the name comes from the path as it was written. A
    # path that resolved to another name (a symlink) keeps the resolved, lower-case one, as before.
    name = Path(text.rstrip("/\\")).name
    hit = _marker_hit(rel, is_folder, table, name if rel and name.lower() == rel[-1] else "")
    if hit:
        name, marker, kind = hit
        return _verdict(True, "markers", "markers", kind, f"{name}:{marker}",
                        f"its name carries the usual test marker '{marker}' ({name})")
    return _verdict(False, "none", "", "", "", "neither a test location of the project nor a usual test name")


def is_test_path(path, cfg, *, base=None, root=None) -> dict:
    """Is this path a test, by the project's word or by the usual test names?

    Always the six keys `test` (bool), `by` ("config" | "markers" | "none"), `source` ("test_locations" |
    "run.levels" | "roots.test" | "tests_root" | "markers" | ""), `kind` ("folder" | "file" | ""), `where` (the
    entry or carrier as written, or `<list>:<marker>`) and `reason` (one English sentence); never raises:
    any exception is `test=False, by="none"` with the exception's type in the reason.

    `root` is the project root (default `hooklib.project_root()`), `base` the folder a relative `path` is
    taken from (default `root`); a trailing `/` or `\\` on `path` means a folder. Consumers choose by
    `source`: the guard opens a write only for "test_locations"; a gate that must not miss a test takes any
    `test is True`."""
    try:
        return _is_test_path(path, cfg, base, root)
    except Exception as exc:
        return _verdict(False, "none", "", "", "", f"the check failed ({type(exc).__name__})")


# --- what in the config opens nothing ------------------------------------------------------------------

def _and(items: list) -> str:
    return " and ".join(f"'{item}'" for item in items)


def location_problems(cfg, root=None) -> list:
    """One English sentence per `test_locations` entry that opens nothing, [] when none: the value is not a
    list; an item is not a text or is empty; a grammar problem (empty, absolute including drive and UNC, `..`,
    `[]{}!`); or the entry covers a whole `protected_app_paths` entry (or the folder that holds one), so
    protection wins for every target inside it. Pure: it prints nothing, never raises."""
    try:
        value = cfg.get(CONFIG_KEY) if isinstance(cfg, dict) else None
        if value is None or value == []:
            return []  # the common case, answered before any path is resolved: the guard asks on every call
        ctx = _Ctx(cfg, root)
        if not isinstance(value, list):
            return [f"test_locations is a {type(value).__name__}, not a list, so none of it is used; write it "
                    'as a list of folders or file patterns relative to app_root, for example ["src/tests/"]']
        out = []
        for i, item in enumerate(value):
            if not isinstance(item, str) or not item.strip():
                out.append(f"test_locations[{i}] is not a non-empty text, so it opens nothing")
                continue
            why = _grammar_problem(_text(item))
            if why:
                out.append(f"test_locations[{i}] '{item.strip()}' is {why}, so it opens nothing; write it the "
                           'way protected_app_paths are written, relative to app_root, for example "src/tests/"')
                continue
            covered = [shown for shown, rsegs in ctx.roots
                       if _opens_boundary(_effective(_text(item)), [(shown, rsegs)])]
            if covered:
                out.append(WHOLE_ROOT.format(roots=_and(covered), entry=item.strip(), first=f"'{covered[0]}'"))
        return out
    except Exception as exc:
        return [f"test_locations could not be read ({type(exc).__name__})"]


def whole_root_conflict(target, cfg, root=None):
    """(entry, root as configured) when a live `test_locations` entry matches `target` but covers whole a
    protected root that holds it - the guard keeps the root protected and says why - else None."""
    try:
        ctx = _Ctx(cfg, root)
        t = _norm(target)
        if ":" in t[2:]:
            return None
        return _config_match(ctx, _rel(t, ctx.app_n))[1]
    except Exception:
        return None


# --- the walk: suggest and check ---------------------------------------------------------------------

def _scan(ctx: _Ctx, max_files: int) -> dict:
    """Walk every protected root once with `os.walk(followlinks=False)`, skipping `skip_dirs`, and stop
    after `max_files` files. `truncated` is true only when one more file exists beyond the cap, so a walk of
    exactly N files at the cap N is complete (FR-41)."""
    skip = set(skip_dirs())
    files, dirs, unreadable, seen = [], [], [], set()
    truncated, walked_roots = False, 0
    for shown, _absolute, entry in ctx.protected:
        try:
            top = (ctx.app_p / entry).resolve()
            top.relative_to(ctx.app_p)
        except (ValueError, OSError):
            continue  # a root outside app_root: no pattern can address it (as `_roots`)
        if not top.is_dir():
            unreadable.append(f"protected path '{shown}' is not a folder on disk, so nothing was walked there")
            continue
        walked_roots += 1
        for dirpath, dirnames, filenames in os.walk(top, followlinks=False):
            dirnames[:] = sorted(d for d in dirnames if d.lower() not in skip)
            here = Path(dirpath).relative_to(ctx.app_p).parts
            if here != top.relative_to(ctx.app_p).parts:
                dirs.append((shown, here))
            for name in sorted(filenames):
                segs = here + (name,)
                key = tuple(s.lower() for s in segs)
                if key in seen:
                    continue
                if len(seen) >= max_files:
                    truncated = True
                    break
                seen.add(key)
                files.append((shown, segs))
            if truncated:
                break
        if truncated:
            break
    if not walked_roots:
        # "0 files" from a walk that never started is an unknown, not a count (FR-41). Before p4 writes the config
        # there is nothing to read the roots from: onboarding passes them (p1's candidates).
        unreadable.append("no protected root was walked (no config yet: pass --app-root and --protected), so every "
                          "count is unknown, not zero")
    return {"files": files, "dirs": dirs, "truncated": truncated, "unreadable": unreadable}


def dir_marker(name: str, table: dict):
    """`"<list>:<marker>"` when this lower-case folder name carries a usual test name (`dir_names`, or a
    `dir_suffixes` ending with at least one character before it), else None. The one matcher of a folder name."""
    if name in table["dir_names"]:
        return f"dir_names:{name}"
    for suffix in table["dir_suffixes"]:
        if name.endswith(suffix) and len(name) > len(suffix):
            return f"dir_suffixes:{suffix}"
    return None


def _join(root_shown: str, rest: str) -> str:
    return rest if root_shown == "." else f"{root_shown}/{rest}"


def suggest(cfg, root, max_files: int = DEFAULT_MAX_FILES) -> dict:
    """Candidate test locations found by the usual test names, inside the protected roots:
    `{"candidates": [{"pattern", "kind", "files", "marker"}], "walked", "truncated", "unreadable"}`.

    A marker folder name seen once is proposed as its literal path (`src/app/__tests__/`); seen two or more
    times it becomes `<root>/**/<name>/`. Files outside those folders whose name carries a marker are grouped
    as `<root>/**/*<suffix>.<ext>` or `<root>/**/<prefix>*.<ext>`. Sorted by files, then by pattern. This is
    advice for the person to confirm, never a decision: a folder that merely looks like a test folder is
    named and counted, nothing is recorded. `unreadable` lists what could not be walked or read."""
    ctx = _Ctx(cfg, root)
    table, why = markers()
    scan = _scan(ctx, max_files)
    unreadable = list(scan["unreadable"])
    candidates = []
    if why:
        unreadable.append(f"the list of usual test names (references/{MARKERS_FILE}) is {why}, so no candidate "
                          "could be proposed")
    else:
        root_len = {shown: len(rsegs) for shown, rsegs in ctx.roots}
        marker_dirs = {}  # lower-case segments of the OUTERMOST marker folder -> (root shown, name, marker)
        for shown, segs in scan["dirs"]:
            low = tuple(s.lower() for s in segs)
            if any(low[:k] in marker_dirs for k in range(root_len.get(shown, 0) + 1, len(low))):
                continue  # inside a marker folder already counted
            hit = dir_marker(low[-1], table)
            if hit:
                marker_dirs[low] = (shown, segs, hit)
        folders = {}  # (root shown, lower name) -> {"dirs": [segs], "files": n, "marker": m}
        for low, (shown, segs, hit) in marker_dirs.items():
            slot = folders.setdefault((shown, low[-1]), {"dirs": [], "files": 0, "marker": hit})
            slot["dirs"].append(segs)
        groups = {}
        for shown, segs in scan["files"]:
            low = tuple(s.lower() for s in segs)
            owner = next((low[:k] for k in range(1, len(low)) if low[:k] in marker_dirs), None)
            if owner is not None:
                folders[(marker_dirs[owner][0], owner[-1])]["files"] += 1
                continue
            found = _marker_hit(low, False, table, segs[-1])
            if found:
                name, marker, _kind = found
                _head, dot, ext = low[-1].rpartition(".")
                ext = f".{ext}" if dot else ""
                shape = (f"*{marker}{ext}" if name in ("stem_suffixes", "stem_camel_suffixes") else f"{marker}*{ext}")
                slot = groups.setdefault((shown, shape), {"files": 0, "marker": f"{name}:{marker}"})
                slot["files"] += 1
        for (shown, name), slot in folders.items():
            if len(slot["dirs"]) == 1:
                pattern = "/".join(slot["dirs"][0]) + "/"
            else:
                pattern = _join(shown, f"**/{name}/")
            candidates.append({"pattern": pattern, "kind": "folder", "files": slot["files"],
                               "marker": slot["marker"]})
        for (shown, shape), slot in groups.items():
            candidates.append({"pattern": _join(shown, f"**/{shape}"), "kind": "file", "files": slot["files"],
                               "marker": slot["marker"]})
        candidates.sort(key=lambda c: (-c["files"], c["pattern"]))
    return {"candidates": candidates, "walked": len(scan["files"]), "truncated": scan["truncated"],
            "unreadable": unreadable}


def check(cfg, root, max_files: int = DEFAULT_MAX_FILES, candidates=()) -> dict:
    """What each entry of `test_locations` (and each candidate) holds, counted over the protected roots:
    `{"entries": [{"entry", "live", "problem", "files", "without_marker"}], "walked", "truncated",
    "proposed_value", "unreadable"}`.

    `live` is a readable entry (a text with no grammar problem; an entry that covers a whole protected root
    is live and carries its sentence in `problem`); `files` is how many walked files it names and
    `without_marker` how many of those carry no usual test name (null when the list of usual names cannot be
    read: an unknown is not a number). When `truncated` is true both are lower bounds. `proposed_value` is
    the current `test_locations` list with the candidates appended, duplicates removed, order kept - the
    exact value to record, so nothing already recorded is dropped; null (and the problem named) when the
    current value is not a list or a candidate has a grammar problem. A candidate that covers a whole
    protected root (a `problem` row) is left OUT of it: such a row is said to the person, never recorded."""
    ctx = _Ctx(cfg, root)
    table, why = markers()
    scan = _scan(ctx, max_files)
    current = ctx.cfg.get(CONFIG_KEY)
    listed = current if isinstance(current, list) else ([] if current is None else None)
    texts = [item.strip() for item in listed if isinstance(item, str)] if listed else []
    extra = [str(c).strip() for c in candidates if str(c).strip() and str(c).strip() not in texts]
    extra = list(dict.fromkeys(extra))
    names = ([(i, item) for i, item in enumerate(listed or [])]
             + [(None, c) for c in extra])
    entries, blocked, left_out = [], listed is None, set()
    lowered = [(shown, tuple(s.lower() for s in segs), segs[-1]) for shown, segs in scan["files"]]
    for _index, item in names:
        row = {"entry": item if isinstance(item, str) else str(item), "live": False, "problem": "",
               "files": 0, "without_marker": None if why else 0}
        if not isinstance(item, str) or not item.strip():
            row["problem"] = "not a non-empty text, so it opens nothing"
        else:
            problem = _grammar_problem(_text(item))
            if problem:
                row["problem"] = f"is {problem}, so it opens nothing"
                if _index is None:
                    blocked = True
            else:
                row["live"] = True
                segs = tuple(_effective(_text(item)))
                covered = [shown for shown, rsegs in ctx.roots if _opens_boundary(list(segs), [(shown, rsegs)])]
                if covered:
                    row["problem"] = WHOLE_ROOT.format(roots=_and(covered), entry=item.strip(),
                                                       first=f"'{covered[0]}'")
                    if _index is None:
                        left_out.add(item.strip())  # a candidate with a problem is never in the value to record
                held = [(low, written) for _shown, low, written in lowered if _match(segs, low)]
                row["files"] = len(held)
                if not why:
                    row["without_marker"] = sum(1 for low, written in held
                                                if _marker_hit(low, False, table, written) is None)
                else:
                    row["without_marker"] = None
        entries.append(row)
    proposed = None if blocked else list(listed) + [c for c in extra if c not in left_out]
    unreadable = list(scan["unreadable"])
    if why:
        unreadable.append(f"the list of usual test names (references/{MARKERS_FILE}) is {why}, so the entries "
                          "without a usual test name were not counted")
    if listed is None:
        unreadable.append("test_locations is not a list, so no value can be proposed until the person's full "
                          "list is known")
    return {"entries": entries, "walked": len(scan["files"]), "truncated": scan["truncated"],
            "proposed_value": proposed, "unreadable": unreadable}


# --- the CLI -----------------------------------------------------------------------------------------------

def _config_of(root: Path) -> dict:
    try:
        data = json.loads((root / "qa-factory" / "config.json").read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _count_words(files: int, without, truncated: bool) -> str:
    more = "at least " if truncated else ""
    tail = "" if without is None else f", {more}{without} without a usual test name"
    return f"{more}{files} files{tail}"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Candidate test locations and what a project's entries hold.")
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="the project root (default: cwd)")
    parser.add_argument("--app-root", help="overrides config app_root (onboarding runs before any config)")
    parser.add_argument("--protected", action="append", default=None,
                        help="overrides config protected_app_paths; repeat for several")
    what = parser.add_mutually_exclusive_group(required=True)
    what.add_argument("--suggest", action="store_true", help="propose candidates by the usual test names")
    what.add_argument("--check", action="store_true", help="count what each test_locations entry holds")
    parser.add_argument("--candidate", action="append", default=[],
                        help="with --check: one more entry to count and add to proposed_value")
    parser.add_argument("--max-files", type=int, default=DEFAULT_MAX_FILES)
    parser.add_argument("--json", action="store_true", help="print the JSON the caller parses and nothing else")
    args = parser.parse_args(argv)
    if args.candidate and not args.check:
        parser.error("--candidate goes with --check")
    root = args.root.resolve()
    cfg = _config_of(root)
    if args.app_root is not None:
        cfg["app_root"] = args.app_root
    if args.protected is not None:
        cfg["protected_app_paths"] = args.protected
    if args.suggest:
        result = suggest(cfg, root, args.max_files)
    else:
        result = check(cfg, root, args.max_files, args.candidate)
    if args.json:
        print(json.dumps(result, ensure_ascii=False))
        return 0
    if args.suggest:
        for c in result["candidates"]:
            print(f"{c['pattern']}  ({c['kind']}, {_count_words(c['files'], None, result['truncated'])}, "
                  f"marker {c['marker']})")
        if not result["candidates"]:
            print("no candidate found inside the application folders")
    else:
        for row in result["entries"]:
            line = f"{row['entry']}: {_count_words(row['files'], row['without_marker'], result['truncated'])}"
            print(line + (f" - {row['problem']}" if row["problem"] else ""))
        if not result["entries"]:
            print("test_locations holds no entry")
        print(f"proposed value: {json.dumps(result['proposed_value'], ensure_ascii=False)}")
    for note in result["unreadable"]:
        print(f"note: {note}")
    if result["truncated"]:
        print(f"note: the walk stopped after {args.max_files} files; every count above is a lower bound")
    return 0


if __name__ == "__main__":
    sys.exit(main())
