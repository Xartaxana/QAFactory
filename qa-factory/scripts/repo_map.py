"""The map of the test repository a window needs, built by code before the role starts.

On TP1-13797 the automator made 137 Read/Grep calls over the test repository per
window, most of them to learn the same four facts: which tests already exist for the area,
which conftest fixtures there are and what they take, which utils and page objects carry
the nouns the cases talk about, and how a test is written here. Every one of those reads
was re-billed on every later turn of the dispatch. This script answers the four questions
once, from the files, and writes them where the brief (`brief_pack.py`) links them:

    repo_map.py --task T --cases TC-001,TC-002 [--area X] [--json] [--output PATH]

    -> qa-factory/artifacts/<T>/work/briefs/repo-map-<hash>.md

  1. existing tests of the area: paths and test function names;
  2. conftest fixtures with their signatures (name, parameters, scope, first doc line);
  3. utils / page objects / test-data modules, ranked by the nouns of the cases' Given and
     When (code ranking: a noun in the file name outweighs one in a class name outweighs
     one in the body);
  4. one example test file head (<= 60 lines) - "how a test is written here".

The walk takes every code file (`test_files.is_code_file`) and recognises tests through `test_files.is_test_for`
(B-407 A-map). Only Python files are read for names, fixtures and members; another language is listed with a
note. An empty map says why (`empty_reason`).

The nouns come from the case files of the scope (`## Given` / `## When`): backticked names,
snake_case and CamelCase identifiers weigh more than plain words. `--area` overrides the
area read from the cases' frontmatter. `--json` prints the map and writes nothing;
`--output` writes the markdown to that path instead of `work/briefs/`.

The judge is a seam, never a requirement: when `judge.active()` and the registry carries
`disc_repo_map_relevance`, its answer may re-rank the utils; without it (the experiment
runs with `judge.provider: none`) the code ranking stands. This script never reads the
plugin's own scripts; the plugin is not a place a map points to.
"""
import argparse
import ast
import functools
import hashlib
import itertools
import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import hooklib  # noqa: E402
import test_files  # noqa: E402
import test_locations  # noqa: E402
from hooklib import sorted_paths  # noqa: E402

EXAMPLE_LINES = 60
MAX_AREA_FILES = 6
MAX_TESTS_PER_FILE = 25
MAX_FIXTURES = 30
MAX_UTILS = 10
MAX_DEFS_PER_UTIL = 8
SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", "qa-factory", ".tox",
             "dist", "build", ".mypy_cache", ".pytest_cache", "site-packages"}
LANGUAGE_NOTE = "not a Python file: its test names are not listed"
UTIL_LANGUAGE_NOTE = "not a Python file: its definitions are not listed"
UTIL_DIR_NAMES = {"utils", "util", "helpers", "helper", "pageobject", "pageobjects", "page_objects",
                  "pages", "support", "lib", "common", "test_data", "testdata", "fixtures",
                  "clients", "api", "steps"}
STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "into", "each", "against", "when",
    "given", "then", "returns", "return", "value", "values", "same", "both", "over", "only",
    "not", "never", "once", "per", "one", "two", "three", "four", "all", "any", "are", "was",
    "were", "has", "have", "does", "must", "read", "call", "calls", "called", "after", "before",
    "where", "which", "than", "there", "their", "them", "they", "its", "via", "under", "case",
    "cases", "test", "tests", "partition", "partitions", "expected", "exactly", "fresh",
    "configured", "request", "response", "none", "true", "false", "null", "list", "dict",
    "string", "str", "int", "bool", "object", "result", "results", "step", "steps",
}
SECTION_RE = re.compile(r"(?im)^##+\s*(Given|When)\b[^\n]*\n(.*?)(?=^##+\s|\Z)", re.S)
BACKTICK_RE = re.compile(r"`([^`\n]+)`")
IDENT_RE = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*\b")
WORD_RE = re.compile(r"[a-z]{4,}")
CAMEL_RE = re.compile(r"[A-Z][a-z0-9]+")
AREA_RE = re.compile(r"^\s*area:\s*(\S+)", re.M)
TEST_DEF_RE = re.compile(r"^\s*(?:async\s+)?def\s+(test_\w+)", re.M)
CLASS_RE = re.compile(r"^class\s+(\w+)", re.M)


# --- nouns --------------------------------------------------------------------------------

def _split_ident(token: str) -> list:
    """`webhook_utils` -> [webhook, utils]; `WebhookService` -> [webhook, service]."""
    parts = []
    for piece in token.split("_"):
        camel = CAMEL_RE.findall(piece)
        parts.extend(camel if camel and "".join(camel) == piece else [piece])
    return [p.lower() for p in parts if len(p) >= 3]


def nouns_from_cases(texts: list) -> dict:
    """{noun: weight} from the Given/When sections of the case texts (whole text when a
    case has no such headings - a legacy case is still a source of nouns)."""
    weights: dict = {}

    def add(word: str, weight: int) -> None:
        word = word.lower()
        if len(word) < 3 or word in STOPWORDS or word.isdigit():
            return
        weights[word] = weights.get(word, 0) + weight

    for text in texts:
        sections = [m.group(2) for m in SECTION_RE.finditer(text or "")]
        body = "\n".join(sections) if sections else str(text or "")
        for name in BACKTICK_RE.findall(body):
            for ident in IDENT_RE.findall(name):
                if len(ident) >= 3:
                    add(ident, 3)
                    for part in _split_ident(ident):
                        add(part, 2)
        plain = BACKTICK_RE.sub(" ", body)
        for ident in IDENT_RE.findall(plain):
            if "_" in ident or CAMEL_RE.search(ident[1:]):
                add(ident, 2)
                for part in _split_ident(ident):
                    add(part, 1)
        for word in WORD_RE.findall(plain.lower()):
            add(word, 1)
    return weights


NOUN_WEIGHT_CAP = 6  # in a BODY, a noun four cases repeat is not thirty times as telling as one they name once


def _score_text(text: str, nouns: dict, weight: int, cap: int = 1) -> int:
    """Presence, not frequency: a 3,000-line page object that mentions every noun once is
    not a better match than the 90-line util named after the one noun that matters."""
    low = str(text or "").lower()
    score = 0
    for noun, w in nouns.items():
        hits = low.count(noun)
        if hits:
            score += min(w, NOUN_WEIGHT_CAP) * weight * min(hits, cap)
    return score


def _token_score(names: list, nouns: dict) -> int:
    """A NAME matches a noun as a whole token (`webhook_utils` -> webhook, utils), with the
    noun's full weight: what the cases name most is what the module is named after."""
    tokens = set()
    for name in names:
        tokens.add(str(name).lower())
        tokens.update(_split_ident(str(name)))
    return sum(w for noun, w in nouns.items() if noun in tokens)


# --- the repository -------------------------------------------------------------------------

def _extra_skip_dirs() -> set:
    """The markers' `skip_dirs` (lower-case), added to `SKIP_DIRS`; absent, malformed or failing is no extra skip."""
    try:
        return {str(name).lower() for name in test_locations.skip_dirs() or []}
    except Exception:
        return set()


def _walk(root: Path, extra_skip=None, skipped=None):
    """Every code file under root (`test_files.is_code_file`), sorted; `SKIP_DIRS` plus the markers' `skip_dirs`
    (read once per walk) are pruned. `skipped`, when given, counts the files left out ({extension: count}). No cap."""
    extra = _extra_skip_dirs() if extra_skip is None else extra_skip
    is_code: dict = {}   # asked once per extension
    found = []
    for here, dirs, names in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and d.lower() not in extra]
        for name in names:
            ext = name.rpartition(".")[2].lower() if "." in name else ""
            if ext not in is_code:
                is_code[ext] = test_files.is_code_file(name) is True
            if is_code[ext]:
                found.append(Path(here) / name)
            elif skipped is not None:
                label = "." + ext if ext else "(no extension)"
                skipped[label] = skipped.get(label, 0) + 1
    yield from sorted_paths(found)


def _is_python(path: Path) -> bool:
    return path.suffix.lower() == ".py"


@functools.lru_cache(maxsize=None)
def _resolved(path: Path) -> Path:
    return path.resolve()


@functools.lru_cache(maxsize=None)
def _rel(path: Path, project: Path) -> str:
    """The path relative to the project root, kept per process: resolving costs milliseconds, and a walked path
    already lies under the resolved root, so it is read lexically first."""
    try:
        lexical = path.relative_to(_resolved(project))
        if ".." not in lexical.parts:
            return lexical.as_posix()
    except ValueError:
        pass
    try:
        return _resolved(path).relative_to(_resolved(project)).as_posix()
    except ValueError:
        return path.as_posix()


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _root_plan(cfg: dict, project: Path) -> list:
    """`{path (as written), abs, exists, used}` per root the config names: the profile test roots, and `tests_root`
    when none of them exists. A missing root is listed (the empty map names it) and not read, but `tests_root`."""
    plan = []
    for profile in cfg.get("profiles") or []:
        raw = ((profile or {}).get("roots") or {}).get("test") if isinstance(profile, dict) else None
        if raw:
            exists = (project / raw).is_dir()
            plan.append({"path": str(raw), "abs": (project / raw).resolve(), "exists": exists, "used": exists})
    if not any(entry["used"] for entry in plan):
        raw = str(cfg.get("tests_root") or ".").strip() or "."
        plan.append({"path": raw, "abs": (project / raw).resolve(), "exists": (project / raw).is_dir(),
                     "used": True})
    return plan


def test_roots(cfg: dict, project: Path) -> list:
    """The narrowest roots the config names: profile test roots, else `tests_root`."""
    roots = [entry["abs"] for entry in _root_plan(cfg, project) if entry["used"]]
    # a root inside another root is the other root's business
    out = []
    for root in sorted(set(roots), key=lambda p: len(p.parts)):
        if not any(root != kept and root.is_relative_to(kept) for kept in out):
            out.append(root)
    return out


def _is_test_file(path: Path, cfg: dict, project: Path) -> bool:
    """A test body by the one leaf (`test_files`, "test_body"); unreadable names mean "not a test" (advice only)."""
    return test_files.is_test_for("test_body", _rel(path, project), cfg, root=project) is True


def _is_util_file(path: Path, root: Path, cfg: dict, project: Path, is_test) -> bool:
    """`is_test` is the caller's memo of `_is_test_file` (a verdict costs milliseconds)."""
    if is_test(path) or path.name in ("conftest.py", "__init__.py"):
        return False
    if test_files.is_test_for("test_place", _rel(path, project), cfg, root=project) is True:
        return True      # a helper that lives in a test place
    try:
        parts = path.relative_to(root).parts[:-1]
    except ValueError:
        return False
    return any(part.lower() in UTIL_DIR_NAMES for part in parts)


def area_tests(files: list, area: str, nouns: dict, project: Path, is_test) -> list:
    """Test files of the area (path match), else the best noun matches; with their tests. `files` are the code files;
    `is_test` is asked only about the candidates, in rank order: a verdict is costly, a big tree has thousands."""
    area_low = (area or "").lower()

    def path_rank(path: Path) -> tuple:
        rel = _rel(path, project).lower()
        parts = rel.split("/")
        # a directory named after the area, then a file named after it, then a mention
        exact_dir = any(part == area_low for part in parts[:-1])
        in_name = area_low in parts[-1]
        return (0 if exact_dir else 1 if in_name else 2, -_score_text(rel + "\n" + _read(path)[:20000], nouns, 1, cap=3), rel)

    by_path = sorted((f for f in files if area_low and area_low in _rel(f, project).lower() and is_test(f)),
                     key=path_rank)
    chosen = by_path
    if not chosen:
        scored = [(f, _score_text(_rel(f, project) + "\n" + _read(f)[:20000], nouns, 1, cap=3)) for f in files]
        chosen = (f for f, s in sorted(scored, key=lambda fs: (-fs[1], _rel(fs[0], project))) if s > 0 and is_test(f))
    out = []
    for path in itertools.islice(chosen, MAX_AREA_FILES):
        text = _read(path)
        if not _is_python(path):
            # the readers below know Python only: another language's file is listed, its names are not guessed
            out.append({"path": _rel(path, project), "bytes": len(text.encode("utf-8")), "classes": [],
                        "tests": [], "test_count": 0, "matched_by": "area" if by_path else "nouns",
                        "language_note": LANGUAGE_NOTE})
            continue
        names = TEST_DEF_RE.findall(text)
        out.append({"path": _rel(path, project), "bytes": len(text.encode("utf-8")),
                    "classes": CLASS_RE.findall(text)[:6], "tests": names[:MAX_TESTS_PER_FILE],
                    "test_count": len(names), "matched_by": "area" if by_path else "nouns"})
    return out


def _fixture_scope(decorator) -> str:
    if isinstance(decorator, ast.Call):
        for kw in decorator.keywords:
            if kw.arg == "scope" and isinstance(kw.value, ast.Constant):
                return str(kw.value.value)
    return "function"


def _is_fixture(decorator) -> bool:
    target = decorator.func if isinstance(decorator, ast.Call) else decorator
    name = target.attr if isinstance(target, ast.Attribute) else getattr(target, "id", "")
    return name == "fixture"


def fixtures_of(path: Path, project: Path) -> list:
    """`[{name, signature, scope, doc, file}]` for every pytest fixture in one file."""
    text = _read(path)
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    out = []
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        marks = [d for d in node.decorator_list if _is_fixture(d)]
        if not marks:
            continue
        args = [a.arg for a in node.args.args if a.arg not in ("self", "request")]
        doc = (ast.get_docstring(node) or "").strip().splitlines()
        out.append({"name": node.name, "signature": f"{node.name}({', '.join(args)})",
                    "scope": _fixture_scope(marks[0]), "doc": doc[0][:100] if doc else "",
                    "file": _rel(path, project)})
    return out


def conftest_fixtures(files: list, nouns: dict, project: Path) -> tuple:
    """(ranked fixtures, total) over every conftest.py found. Ranked by the nouns; the ones
    every test takes (a client, a project) rank by name only when the cases name them."""
    found = []
    for path in files:
        if path.name == "conftest.py":
            found.extend(fixtures_of(path, project))
    for fx in found:
        fx["score"] = 10 * _token_score([fx["name"]], nouns) + _score_text(fx["doc"], nouns, 1)
    ranked = sorted(found, key=lambda fx: (-fx["score"], fx["file"], fx["name"]))
    return ranked[:MAX_FIXTURES], len(found)


def _defs(text: str) -> list:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return [], []
    classes = [n.name for n in tree.body if isinstance(n, ast.ClassDef)]
    functions = [n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    methods = []
    for n in tree.body:
        if isinstance(n, ast.ClassDef):
            methods += [m.name for m in n.body if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))
                        and not m.name.startswith("_")]
    return classes, (functions + methods)


def utils_ranked(files: list, roots: list, nouns: dict, project: Path, cfg: dict, is_test) -> list:
    out = []
    for path in files:
        text = _read(path)
        classes, defs = _defs(text) if _is_python(path) else ([], [])
        # The file name first, its class and function names second, the body last and only
        # as a tiebreaker: what a module is named after is what it is for.
        score = (100 * _token_score([path.stem], nouns) + 10 * _token_score(classes + defs, nouns)
                 + _score_text(text[:40000], nouns, 1))
        # scored first: the util verdict is costly, asked only of a file that could be listed
        if score <= 0 or not any(_is_util_file(path, root, cfg, project, is_test) for root in roots):
            continue
        entry = {"path": _rel(path, project), "score": score, "classes": classes[:4],
                 "defs": [d for d in defs if not d.startswith("_")][:MAX_DEFS_PER_UTIL],
                 "bytes": len(text.encode("utf-8"))}
        if not _is_python(path):
            entry["language_note"] = UTIL_LANGUAGE_NOTE
        out.append(entry)
    out.sort(key=lambda u: (-u["score"], u["path"]))
    return out[:MAX_UTILS]


def _judge_rerank(utils: list, nouns: dict, cfg_root) -> list:
    """The optional seam: a registered `disc_repo_map_relevance` judgment may re-rank the
    utils. Without a judge, or without that judgment in the registry, the code ranking stands."""
    try:
        import judge
        if not utils or not judge.active() or "disc_repo_map_relevance" not in judge.load_registry():
            return utils
        answer = judge.ask_one({"nouns": sorted(nouns, key=nouns.get, reverse=True)[:20],
                                "candidates": [u["path"] for u in utils]},
                               "disc_repo_map_relevance", project_root=cfg_root)
        order = (answer or {}).get("value") if isinstance(answer, dict) else None
        if isinstance(order, list) and order:
            rank = {path: i for i, path in enumerate(order)}
            return sorted(utils, key=lambda u: rank.get(u["path"], len(rank)))
    except Exception:
        pass
    return utils


# --- the story's cases ----------------------------------------------------------------------

def case_texts(task_root: Path, cases: list) -> tuple:
    """(texts, area, paths) of the scoped cases: the pinned versions when the story has
    them, else the case files of the story or the project's store (`contract.case_files`)."""
    import contract
    wanted = {c.strip() for c in cases if c and c.strip()}
    texts, paths, areas = [], [], []
    links = {str(link.get("case_id")): link for link in contract.story_case_links(task_root)}
    for cid in sorted(wanted):
        link = links.get(cid) or links.get(cid.rsplit("/", 1)[-1])
        path = None
        if link and link.get("path"):
            candidate = task_root / str(link["path"])
            if candidate.is_file():
                path = candidate
            if link.get("area"):
                areas.append(str(link["area"]))
        if path is None:
            for candidate in contract.case_files(task_root):
                if contract.case_id(candidate) == cid.rsplit("/", 1)[-1]:
                    path = candidate
                    break
        if path is None:
            continue
        text = _read(path)
        texts.append(text)
        paths.append(path)
        m = AREA_RE.search(text.split("---", 2)[1] if text.lstrip().startswith("---") and text.count("---") >= 2 else "")
        if m:
            areas.append(m.group(1).strip().strip("\"'"))
    area = ""
    if areas:
        area = max(set(areas), key=areas.count)
    return texts, area, paths


# --- build and render -----------------------------------------------------------------------

def _markers_problem() -> str:
    """Why the test names or code extensions cannot be used, in words; "none" when they can."""
    try:
        table, why = test_files.markers()
    except Exception as exc:
        return f"the markers could not be loaded ({type(exc).__name__})"
    if why:
        return f"references/{test_files.MARKERS_FILE} is {why}"
    found = []
    if not table.get("code_extensions"):    # is_code_file is then unknown: no file is code, and the map says why
        found.append(f"code_extensions is empty in references/{test_files.MARKERS_FILE}: no file counts as code")
    if table.get("extras_problem"):
        found.append(str(table["extras_problem"]))
    return "; ".join(found) or "none"


def _unreadable(files: list) -> dict:
    """{reason: count} of the files that cannot be opened (never raised)."""
    counts: dict = {}
    for path in files:
        try:
            open(path, "rb").close()
        except OSError as exc:
            reason = f"unreadable ({type(exc).__name__})"
            counts[reason] = counts.get(reason, 0) + 1
    return counts


def _empty_reason(cfg: dict, project: Path, files: list, skipped: dict) -> dict:
    """Why a map is empty: roots (a missing one marked), files read, top 3 extensions left out, unreadable files,
    the markers problem."""
    top = sorted(skipped.items(), key=lambda kv: (-kv[1], kv[0]))[:3]
    return {"roots": [{"path": entry["path"], "exists": entry["exists"]} for entry in _root_plan(cfg, project)],
            "files_read": len(files),
            "skipped_by_extension": [{"extension": ext, "count": n} for ext, n in top],
            "files_skipped": _unreadable(files), "markers_problem": _markers_problem()}


def build(task_root: Path, project: Path, cfg: dict, cases: list, area: str = "") -> dict:
    texts, found_area, paths = case_texts(task_root, cases)
    area = area or found_area
    nouns = nouns_from_cases(texts)
    roots = test_roots(cfg, project)
    files, skipped, extra_skip = [], {}, _extra_skip_dirs()
    for root in roots:
        files.extend(_walk(root, extra_skip, skipped))
    is_test = functools.lru_cache(maxsize=None)(lambda path: _is_test_file(path, cfg, project))
    area_files = area_tests(files, area, nouns, project, is_test)
    fixtures, total_fixtures = conftest_fixtures(files, nouns, project)
    utils = _judge_rerank(utils_ranked(files, roots, nouns, project, cfg, is_test), nouns, project)
    example = None
    if area_files:
        example_path = project / area_files[0]["path"]
        lines = _read(example_path).splitlines()[:EXAMPLE_LINES]
        example = {"path": area_files[0]["path"], "lines": len(lines), "text": "\n".join(lines)}
    key = hashlib.sha256(("|".join(sorted(c.strip() for c in cases)) + "#" + area).encode("utf-8")).hexdigest()[:10]
    doc = {"task": task_root.name, "cases": sorted(c.strip() for c in cases if c.strip()), "area": area,
           "hash": key, "case_files": [_rel(p, project) for p in paths],
           "test_roots": [_rel(r, project) for r in roots],
           "nouns": [n for n, _ in sorted(nouns.items(), key=lambda kv: (-kv[1], kv[0]))[:24]],
           "existing_tests": area_files, "fixtures": fixtures, "fixtures_total": total_fixtures,
           "utils": utils, "example": example,
           "empty": not (area_files or fixtures or utils)}
    if doc["empty"]:
        doc["empty_reason"] = _empty_reason(cfg, project, files, skipped)
    return doc


def _reason_line(why: dict) -> str:
    """The `empty_reason` in one paragraph: what was read, what was left out, what could not be read."""
    roots = ", ".join(f"`{r['path']}` ({'exists' if r['exists'] else 'missing'})" for r in why.get("roots") or []) or "none"
    by_ext = ", ".join(f"`{e['extension']}` x{e['count']}" for e in why.get("skipped_by_extension") or []) or "none"
    unread = ", ".join(f"{reason} x{n}" for reason, n in (why.get("files_skipped") or {}).items()) or "none"
    return (f"Why: roots read - {roots}; files read: {why.get('files_read', 0)}; left out by extension (top 3): "
            f"{by_ext}; files that could not be read: {unread}; markers problem: {why.get('markers_problem') or 'none'}.")


def render(doc: dict) -> str:
    lines = [f"# Repo map - {doc['area'] or 'no area'} ({', '.join(doc['cases']) or 'no cases'})", ""]
    lines.append(f"Test roots: {', '.join('`' + r + '`' for r in doc['test_roots'])}. "
                 f"Nouns from the cases' Given/When: {', '.join(doc['nouns'][:16]) or 'none found'}.")
    if doc.get("empty"):
        lines += ["", "**The map is empty**: no test of this area, no conftest fixture and no util matched. "
                  "This is the one case where searching the repository yourself is the right move."]
        if doc.get("empty_reason"):
            lines += ["", _reason_line(doc["empty_reason"])]
    lines += ["", "## Existing tests of the area", ""]
    if not doc["existing_tests"]:
        lines.append("- none found for this area (by path or by the cases' nouns)")
    for entry in doc["existing_tests"]:
        if entry.get("language_note"):
            lines.append(f"- `{entry['path']}` ({entry['bytes']:,} B, matched by {entry['matched_by']}): "
                         f"{entry['language_note']}")
            continue
        names = ", ".join(entry["tests"]) + (" ..." if entry["test_count"] > len(entry["tests"]) else "")
        lines.append(f"- `{entry['path']}` ({entry['test_count']} tests, {entry['bytes']:,} B, matched by "
                     f"{entry['matched_by']}): {names or 'no test functions'}")
    lines += ["", f"## Fixtures (conftest) - {len(doc['fixtures'])} of {doc['fixtures_total']}, ranked by the nouns", ""]
    if not doc["fixtures"]:
        lines.append("- no conftest.py fixture found under the test roots")
    for fx in doc["fixtures"]:
        scope = "" if fx["scope"] == "function" else f" [{fx['scope']}]"
        doc_line = f" - {fx['doc']}" if fx["doc"] else ""
        lines.append(f"- `{fx['signature']}`{scope} in `{fx['file']}`{doc_line}")
    lines += ["", "## Utils, page objects and test data, ranked", ""]
    if not doc["utils"]:
        lines.append("- no helper module matched the nouns")
    for util in doc["utils"]:
        members = ", ".join(util["classes"] + [d for d in util["defs"] if d not in util["classes"]])
        lines.append(f"- `{util['path']}` ({util['bytes']:,} B): "
                     f"{util.get('language_note') or members or 'module-level code'}")
    if doc.get("example"):
        ex = doc["example"]
        lines += ["", f"## How a test is written here - `{ex['path']}`, first {ex['lines']} lines", "",
                  "```" + test_files.fence_language(ex["path"]), ex["text"], "```"]
    lines += ["", "Read what is named here with `offset`/`limit`; search the repository only when this map is empty.", ""]
    return "\n".join(lines)


def write_map(task_root: Path, doc: dict, output: Path | None = None) -> Path:
    path = output or (task_root / "work" / "briefs" / f"repo-map-{doc['hash']}.md")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render(doc), encoding="utf-8")
    return path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0], formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--task", required=True)
    ap.add_argument("--cases", required=True, help="comma-separated case ids of the window")
    ap.add_argument("--area", default="", help="override the area read from the cases")
    ap.add_argument("--json", action="store_true", help="print the map as JSON and write nothing")
    ap.add_argument("--output", help="write the markdown here instead of work/briefs/repo-map-<hash>.md")
    ns = ap.parse_args()
    task_root = hooklib.story_cli("repo_map.py", key=ns.task)     # the story EXISTS (CX1-18); a refusal is story_cli's: one line, exit 2
    project = hooklib.project_root()
    cfg = hooklib.load_config() or {}
    cases = [c for c in re.split(r"[,\s]+", ns.cases) if c]
    doc = build(task_root, project, cfg, cases, ns.area)
    if ns.json:
        print(json.dumps(dict(doc, markdown=render(doc)), ensure_ascii=False, indent=1))
        return 0
    path = write_map(task_root, doc, Path(ns.output) if ns.output else None)
    size = path.stat().st_size
    print(f"repo map: {_rel(path, project)} ({size:,} B) - {len(doc['existing_tests'])} test file(s), "
          f"{len(doc['fixtures'])}/{doc['fixtures_total']} fixtures, {len(doc['utils'])} utils"
          + (" - EMPTY" if doc["empty"] else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
