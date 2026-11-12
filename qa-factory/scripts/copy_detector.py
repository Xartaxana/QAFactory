#!/usr/bin/env python3
"""copy_detector.py -- the name-blind copy of a function or a fragment (TQ1-19).

A function (or a window of consecutive statements) is reduced to its normal form: local names are
numbered by first appearance, literals keep only their type, the docstring and the function's own name
are dropped, names that are NOT local (calls into the project, attributes) stay -- so two bodies that do
the same thing under different names have one normal form and two bodies that call different things
do not.

A pure library plus a CLI. `normal_form` and the pool walk over a file's imports; `limits` (the
`copy_detector` row of `references/detectors.json`, defaults and a note when it cannot be read);
`find_copies` (the units of the files a story's history touched, against those files plus the project
files they import, kept only when the unit is new or changed in the story: the novelty is handed in, this
module knows no story); `main` (`--root --min --window`, the N0 measurement: every test file in turn as
NEW units against its own importable pool). The gate that turns copies into findings and hints is
`s5_precheck.check_copies`; the detector reports and the role judges (AR-2).
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import sys
from pathlib import Path

DEFAULT_MIN_FUNCTION_STATEMENTS = 2
DEFAULT_FRAGMENT_WINDOW = 3
DEFAULT_MAX_FILES = 40
RECURSION_LIMIT = 6000
LIMITS_KEY = "copy_detector"
LIMIT_KEYS = ("min_function_statements", "fragment_window", "max_files")
LIMIT_DEFAULTS = {"min_function_statements": DEFAULT_MIN_FUNCTION_STATEMENTS,
                  "fragment_window": DEFAULT_FRAGMENT_WINDOW, "max_files": DEFAULT_MAX_FILES}
NOVELTY_KEPT = ("new", "changed")          # `unchanged` is somebody else's code; anything else is `unknown`

_DEFS = (ast.FunctionDef, ast.AsyncFunctionDef)
_BREAKERS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
_SKIP_FIELDS = frozenset({"ctx", "type_comment", "kind", "type_params", "annotation", "returns"})
_BINDING_STRINGS = frozenset({("FunctionDef", "name"), ("AsyncFunctionDef", "name"), ("ClassDef", "name"),
                              ("ExceptHandler", "name"), ("alias", "asname")})
_MARK = re.compile("\x00([^\x00]*)\x00")
_SKIP_DIRS = frozenset({"__pycache__", ".git", ".venv", "venv", "node_modules", ".tox", "build", "dist"})


# ---------------------------------------------------------------- normal form

def _strip_doc(body):
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
            and isinstance(body[0].value.value, str):
        return body[1:]
    return body


def count_statements(stmts) -> int:
    """Statements in a list, nested ones included (a docstring is not a statement)."""
    n = 0
    for s in stmts:
        n += 1
        for blk in _child_blocks(s):
            n += count_statements(blk)
    return n


def _child_blocks(stmt):
    if isinstance(stmt, _BREAKERS):
        return [_strip_doc(stmt.body)]
    blocks = []
    for _, value in ast.iter_fields(stmt):
        if isinstance(value, list) and value:
            if all(isinstance(v, ast.stmt) for v in value):
                blocks.append(value)
            else:
                for v in value:
                    if isinstance(v, (ast.ExceptHandler, ast.match_case)):
                        blocks.append(v.body)
    return blocks


def _locals(fn) -> frozenset:
    names, declared = set(), set()
    for n in ast.walk(fn):
        t = type(n)
        if t is ast.Name:
            if isinstance(n.ctx, (ast.Store, ast.Del)):
                names.add(n.id)
        elif t is ast.arg:
            names.add(n.arg)
        elif t in _BREAKERS:
            if n is not fn:
                names.add(n.name)
        elif t is ast.ExceptHandler:
            if n.name:
                names.add(n.name)
        elif t in (ast.Global, ast.Nonlocal):
            declared.update(n.names)
    return frozenset(names - declared)


def _nm(identifier, locs) -> str:
    return "\x00" + identifier + "\x00" if identifier in locs else "N:" + identifier


def _ser(node, locs) -> str:
    if isinstance(node, list):
        return "[" + ",".join(_ser(v, locs) for v in node) + "]"
    if not isinstance(node, ast.AST):
        return repr(node)
    cls = type(node)
    if cls is ast.Name:
        return _nm(node.id, locs)
    if cls is ast.Constant:
        v = node.value
        if v is None or v is True or v is False or v is Ellipsis:
            return repr(v)
        return "K:" + type(v).__name__
    if cls is ast.arg:
        return "arg " + _nm(node.arg, locs)
    brk = isinstance(node, _BREAKERS)
    parts = [cls.__name__]
    for fname, value in ast.iter_fields(node):
        if fname in _SKIP_FIELDS:
            continue
        if brk and fname == "body":
            value = _strip_doc(value)
        if (cls.__name__, fname) in _BINDING_STRINGS:
            parts.append(fname + "=" + (_nm(value, locs) if isinstance(value, str) else "None"))
        else:
            parts.append(fname + "=" + _ser(value, locs))
    return "(" + " ".join(parts) + ")"


def _renumber(text: str) -> str:
    seen: dict = {}
    return _MARK.sub(lambda mo: "\x01%d" % seen.setdefault(mo.group(1), len(seen)), text)


def _digest(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8", "backslashreplace")).hexdigest()


def normal_form(fn, stmts=None, locs=None) -> str:
    """The name-blind fingerprint of a function (`stmts is None`: parameters + body) or of a window of its
    statements (`stmts` given: only those statements, local names numbered from where the window starts).
    The function's own name and its decorators are not part of it. `locs`: the function's local names, when
    the caller already has them."""
    if locs is None:
        locs = _locals(fn)
    if stmts is None:
        kind = "async" if isinstance(fn, ast.AsyncFunctionDef) else "def"
        text = kind + _ser(fn.args, locs) + _ser(_strip_doc(fn.body), locs)
    else:
        text = "win" + _ser(list(stmts), locs)
    return _digest(_renumber(text))


# ---------------------------------------------------------------- units of one file

class Unit:
    """One function or method. `chain` is its class chain, `top` the `(class chain, name)` of the OUTERMOST function it
    sits in (itself for a top-level or class-level one): the novelty of a nested function is its outer one's."""
    __slots__ = ("path", "name", "line", "size", "kind", "fhash", "windows", "chain", "top")

    def __init__(self, path, name, line, size, kind, fhash, windows, chain=(), top=None):
        self.path, self.name, self.line, self.size = path, name, line, size
        self.kind, self.fhash, self.windows = kind, fhash, windows
        self.chain, self.top = tuple(chain), top if top is not None else (tuple(chain), name)

    @property
    def qname(self) -> str:
        return ".".join(self.chain + (self.name,))

    @property
    def key(self) -> tuple:
        return (str(self.path), self.line, self.name)


def _kind(fn) -> str:
    import repo_map             # the one reader of what a fixture decorator looks like (AR-13)
    if any(repo_map._is_fixture(d) for d in fn.decorator_list):
        return "fixture"
    if fn.name.startswith("test"):
        return "test"
    return "helper"


def _windows(fn, m: int) -> set:
    found: set = set()
    if m < 1:
        return found

    def lists(stmts):
        yield stmts
        for s in stmts:
            if isinstance(s, _BREAKERS):
                continue
            for blk in _child_blocks(s):
                yield from lists(blk)

    locs = _locals(fn)
    for stmts in lists(_strip_doc(fn.body)):
        for i in range(len(stmts) - m + 1):
            win = stmts[i:i + m]
            if any(isinstance(s, _BREAKERS) for s in win):
                continue
            found.add(normal_form(fn, win, locs))
    return found


def read_units(path: Path, window: int):
    """(units, note): every function and method of a Python file; a file that does not parse gives no units
    and a note (never a crash, never a silent skip)."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(text)
    except (OSError, SyntaxError, ValueError, RecursionError) as exc:
        return [], f"{path.name}: not parsed ({type(exc).__name__}); unchecked"
    units = []
    found: list = []
    try:
        _collect(tree.body, (), None, found)
        for node, chain, top in found:
            body = _strip_doc(node.body)
            units.append(Unit(path, node.name, node.lineno, count_statements(body), _kind(node),
                              normal_form(node), _windows(node, window), chain, top))
    except RecursionError:
        return [], f"{path.name}: too deep to read; unchecked"
    return units, ""


def _collect(stmts, chain: tuple, outer, out: list) -> None:
    """`[(function node, class chain, top)]` of every function and method, nested ones included (`top` is the outermost
    function's `(class chain, name)`, the one a novelty is measured for)."""
    for node in stmts:
        if isinstance(node, _DEFS):
            top = outer or (chain, node.name)
            out.append((node, chain, top))
            _collect(_strip_doc(node.body), chain, top, out)
        elif isinstance(node, ast.ClassDef):
            _collect(node.body, chain if outer else chain + (node.name,), outer, out)
        else:
            for blk in _child_blocks(node):
                _collect(blk, chain, outer, out)


# ---------------------------------------------------------------- the importable pool

def _py_files(root: Path):
    for p in sorted(root.rglob("*.py")):
        if not (set(p.relative_to(root).parts) & _SKIP_DIRS):
            yield p


def _module_candidates(root: Path, here: Path, module: str, level: int, names):
    bases = []
    if level:
        base = here.parent
        for _ in range(level - 1):
            base = base.parent
        bases = [base]
    else:
        bases = [root, root.parent, here.parent]
    out = []
    parts = module.split(".") if module else []
    for base in bases:
        stem = base.joinpath(*parts) if parts else base
        for cand in (stem.with_suffix(".py"), stem / "__init__.py"):
            out.append(cand)
        for nm in names:  # `from pkg import mod` -- a submodule
            out.append(stem / (nm + ".py"))
    return out


def imported_files(root: Path, pyfile: Path) -> list:
    """The project files this file imports (one hop) plus the `conftest.py` files above it. An import that
    resolves outside `root` is not read."""
    try:
        tree = ast.parse(pyfile.read_text(encoding="utf-8", errors="replace"))
    except (OSError, SyntaxError, ValueError, RecursionError):
        return []
    root = root.resolve()
    found: dict = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            wanted = [(a.name, 0, []) for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            wanted = [(node.module or "", node.level, [a.name for a in node.names])]
        else:
            continue
        for module, level, names in wanted:
            for cand in _module_candidates(root, pyfile.resolve(), module, level, names):
                try:
                    r = cand.resolve()
                    r.relative_to(root)
                except (OSError, ValueError):
                    continue
                if r.is_file() and r != pyfile.resolve():
                    found[r] = True
    here = pyfile.resolve().parent
    while True:
        conf = here / "conftest.py"
        if conf.is_file() and conf != pyfile.resolve():
            found[conf] = True
        if here == root or root not in here.parents and here != root:
            break
        here = here.parent
    return sorted(found)


# ---------------------------------------------------------------- the comparison

def compare(new_units, pool_units, min_statements: int):
    """Copies of NEW units in the pool: one finding per (new unit, pool unit) pair. `function`: equal normal
    form of the whole function (at least `min_statements` statements); `fragment`: an equal window and no
    equal function. A function is never compared with itself (`Unit.key`); a pool unit that is the same function as
    `u` is skipped, so the pool may hold the files of the new units as well."""
    by_func: dict = {}
    by_win: dict = {}
    for u in pool_units:
        by_func.setdefault(u.fhash, []).append(u)
        for w in u.windows:
            by_win.setdefault(w, []).append(u)
    findings = []
    for u in new_units:
        seen: set = {u.key}
        if u.size >= min_statements:
            for p in by_func.get(u.fhash, ()):
                if p.key in seen:
                    continue
                seen.add(p.key)
                findings.append((u, p, "function"))
        hit: dict = {}
        for w in u.windows:
            for p in by_win.get(w, ()):
                if p.key not in seen:
                    hit[p.key] = p
        for p in hit.values():
            findings.append((u, p, "fragment"))
    return findings


def limits(path=None) -> tuple:
    """`(limits, notes)`: the `copy_detector` row of `references/detectors.json` (`min_function_statements`,
    `fragment_window`, `max_files`; positive integers). A file that cannot be read, a row that is absent or not an object,
    a key that is not a positive integer: the DEFAULT of that key and a note that names it -- a broken table never
    switches the check off and never goes unsaid (FR-41). The one path is `assertion_detectors.detectors_path` (AR-13)."""
    out, notes = dict(LIMIT_DEFAULTS), []
    shown = ", ".join(f"{k}={LIMIT_DEFAULTS[k]}" for k in LIMIT_KEYS)
    try:
        import assertion_detectors as AD
        doc = json.loads(AD.detectors_path(path).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        return out, [f"copy check: references/detectors.json cannot be read ({type(exc).__name__}); defaults used ({shown})"]
    row = doc.get(LIMITS_KEY) if isinstance(doc, dict) else None
    if not isinstance(row, dict):
        return out, [f"copy check: references/detectors.json has no `{LIMITS_KEY}` row; defaults used ({shown})"]
    for key in LIMIT_KEYS:
        value = row.get(key)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 1:
            out[key] = value
        else:
            notes.append(f"copy check: `{LIMITS_KEY}.{key}` of references/detectors.json is not a positive integer "
                         f"({str(value)[:20]}); default {LIMIT_DEFAULTS[key]} used")
    return out, notes


def _as_novelty(value) -> str:
    return value if value in ("new", "changed", "unchanged") else "unknown"


def find_copies(unit_files, root, lim: dict, novelty=None) -> dict:
    """The copies of the units of `unit_files` (the files a story's history touched) in a pool of those files plus the
    project files they import (one hop, outside `root` not read). `novelty(tops)` takes `[(path, class chain, function
    name)]` of the outermost functions with a copy and returns one of `new` / `changed` / `unchanged` / anything else
    (= `unknown`) for each, in order; with none given every unit is `unknown`. A unit that is `unchanged` is somebody
    else's code and is dropped; the answer is never guessed (FR-59).

    Returns `{"copies": [...], "notes": [...], "dropped": [paths]}`; a copy is `{"unit", "old", "how",
    "novelty", "more"}` (`more`: other pool units the same unit repeats). One copy per unit, a `function` copy
    before a `fragment` one. A pair of two units of the files is reported once, on the non-`test*` side first, so a
    helper twin is never reported twice. At most `lim["max_files"]` files are read as units; the rest are returned in
    `dropped` (the caller says so, never silence, D2-1). Unparsable files are notes, not units."""
    notes: list = []
    files: list = []
    for f in unit_files:
        f = Path(f)
        if f not in files:
            files.append(f)
    dropped = files[lim["max_files"]:]
    files = files[:lim["max_files"]]
    cache: dict = {}

    def units_of(path):
        if path not in cache:
            got, note = read_units(path, lim["fragment_window"])
            cache[path] = got
            if note:
                notes.append(note)
        return cache[path]

    own = [u for f in files for u in units_of(f)]
    pool_files = list(files)
    if root is not None:
        for f in files:
            for imported in imported_files(root, f):
                if imported not in pool_files:
                    pool_files.append(imported)
    pool = [u for f in pool_files for u in units_of(f)]
    raw = compare(own, pool, lim["min_function_statements"])
    by_unit: dict = {}
    for u, p, how in raw:
        by_unit.setdefault(u.key, (u, []))[1].append((p, how))
    cands = [pair[0] for pair in by_unit.values()]
    tops = list(dict.fromkeys((u.path, u.top[0], u.top[1]) for u in cands))
    values: dict = {}
    if tops:
        try:
            answers = list(novelty(tops)) if novelty is not None else []
        except Exception as exc:       # the measurer never decides: a failure is `unknown`, said by the caller's note
            answers = []
            notes.append(f"copy check: novelty could not be measured ({type(exc).__name__}); every copy is read as `unknown`")
        for index, top in enumerate(tops):
            values[top] = _as_novelty(answers[index] if index < len(answers) else None)
    copies: list = []
    for u in sorted(cands, key=lambda c: (c.kind == "test", str(c.path), c.line)):
        value = values[(u.path, u.top[0], u.top[1])]
        if value == "unchanged":
            continue
        pairs = sorted(by_unit[u.key][1], key=lambda pw: (pw[1] != "function", str(pw[0].path), pw[0].line))
        copies.append({"unit": u, "old": pairs[0][0], "how": pairs[0][1], "novelty": value,
                       "more": [p for p, _how in pairs[1:]]})
    seen_pairs: set = set()
    out: list = []
    for c in copies:
        pair = frozenset((c["unit"].key, c["old"].key))
        if pair in seen_pairs:
            continue
        seen_pairs.add(pair)
        out.append(c)
    out.sort(key=lambda c: (str(c["unit"].path), c["unit"].line))
    return {"copies": out, "notes": notes, "dropped": dropped}


def measure(root: Path, min_statements: int, window: int, only=None):
    """Every test file in turn as NEW units against its own importable pool. Returns (rows, notes)."""
    notes: list = []
    cache: dict = {}

    def units_of(path):
        if path not in cache:
            units, note = read_units(path, window)
            cache[path] = units
            if note:
                notes.append(note)
        return cache[path]

    rows = []
    for pyfile in _py_files(root):
        name = pyfile.name
        if not (name.startswith("test_") or name.endswith("_test.py")):
            continue
        if only and only not in str(pyfile):
            continue
        new_units = units_of(pyfile.resolve())
        pool = []
        imports = imported_files(root, pyfile)
        for p in imports:
            pool.extend(units_of(p))
        fnds = compare(new_units, pool, min_statements)
        row = {"file": str(pyfile.relative_to(root)).replace("\\", "/"), "units": len(new_units),
               "pool_files": len(imports), "function": 0, "fragment": 0,
               "by_kind": {"helper": 0, "fixture": 0, "test": 0}, "samples": []}
        for u, p, how in fnds:
            row[how] += 1
            row["by_kind"][u.kind] += 1
            if len(row["samples"]) < 3:
                row["samples"].append(f"{how}: {u.name}:{u.line} ~ {p.path.name}::{p.name}:{p.line}")
        rows.append(row)
    return rows, notes


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="name-blind copies: each test file as new units against its imports")
    ap.add_argument("--root", required=True, help="project root to read")
    ap.add_argument("--min", type=int, default=DEFAULT_MIN_FUNCTION_STATEMENTS, dest="min_statements")
    ap.add_argument("--window", type=int, default=DEFAULT_FRAGMENT_WINDOW)
    ap.add_argument("--only", default="", help="substring of a test file path")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args(argv)
    root = Path(args.root)
    if not root.is_dir():
        print(f"copy_detector: --root {args.root} is not a directory", file=sys.stderr)
        return 2
    if args.min_statements < 1 or args.window < 1:
        print("copy_detector: --min and --window must be at least 1", file=sys.stderr)
        return 2
    sys.setrecursionlimit(max(sys.getrecursionlimit(), RECURSION_LIMIT))
    rows, notes = measure(root, args.min_statements, args.window, args.only or None)
    with_f = [r for r in rows if r["function"] + r["fragment"]]
    summary = {"min": args.min_statements, "window": args.window, "test_files": len(rows),
               "files_with_findings": len(with_f),
               "findings": sum(r["function"] + r["fragment"] for r in rows),
               "function": sum(r["function"] for r in rows), "fragment": sum(r["fragment"] for r in rows),
               "max_per_file": max((r["function"] + r["fragment"] for r in rows), default=0),
               "helper": sum(r["by_kind"]["helper"] for r in rows),
               "fixture": sum(r["by_kind"]["fixture"] for r in rows),
               "test": sum(r["by_kind"]["test"] for r in rows), "notes": len(notes)}
    if args.json:
        print(json.dumps({"summary": summary, "rows": with_f, "notes": notes}, indent=1))
        return 0
    for r in sorted(with_f, key=lambda r: -(r["function"] + r["fragment"])):
        print(f"{r['function'] + r['fragment']:4d}  fn={r['function']} fr={r['fragment']}  {r['file']}")
        for s in r["samples"]:
            print(f"        {s}")
    for n in notes:
        print("note:", n)
    print("summary:", json.dumps(summary))
    return 0


if __name__ == "__main__":
    sys.exit(main())
