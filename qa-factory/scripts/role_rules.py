#!/usr/bin/env python3
"""role_rules.py - the one reader of design/role-rules.json, the register of the rules a role text must keep.

A rule a role must keep is ONE row: an id, the rule in plain words, its source (the word that made it), and the carriers - the
package files a role reads - each with an ANCHOR, 2-6 consecutive words of the rule's own sentence. The reader joins the
register against the package text: every anchor must stand exactly once in its carrier. Deleting the rule's sentence takes the
count to 0 and turns this red; a rule leaves a role text only together with its row, in the same diff, with the word that
retires it named in the commit message ("role-rules: retire <id> -- <whose word>").

  python -B scripts/role_rules.py --check     # findings, then `role-rules: <n> rows, <m> carriers checked, <k> finding(s)`

Exit 0 when there is no finding, 1 otherwise. That is the whole output contract (FR-14). The same check runs inside
`selftest.py --limits` and in scripts/tests/test_role_rules.py. It is NEVER wired into audit_factory.main(): that is the project
doctor, and role texts are package files a project never changes (the same reason as scripts/gate_registry.py).

WHAT IT JUDGES. Data, never a role's words: the presence of a developer-authored anchor in a developer-authored package file.
It never runs at story time and reads no role output (AR-29; class shape / xref, owner data). Whether a rule should stay is
the person's word and the critic's reading of the diff, not code.

SEARCH. Removed first are ONLY the package's own one-line marker comments (`<!-- kind: .. -->`, `<!-- roles: .. -->`,
`<!-- gen.. -->`, `<!-- /gen -->`); every other HTML comment, a fenced block and a `# ..` line of a handoff yaml is text, because
a role reads these files raw. Then the text and the anchor are folded (whitespace runs to one space, casefold) and the
non-overlapping occurrences are counted: 1 holds, 0 is lost, more is ambiguous. A `.json` carrier is searched by its string
values (recursively), never its keys.

OUT OF CODE, BY DESIGN (named, not hidden): E-19 a row deleted, or an anchor re-pointed to an unrelated phrase while the rule's
sentence disappeared - the critic reads that in the diff; E-21 a rule legitimately retired - the row is removed in the same diff
and the retiring word is named in the commit message; this reader never reads history. Duplicate KEYS inside one JSON object
are not detected (the parser keeps the last): one parser, `hooklib.read_json`, rather than a second one.

The reader returns strings and raises nothing. Findings print whole; nothing is truncated.
"""
import re
import sys
from pathlib import Path, PurePosixPath

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hooklib import read_json  # noqa: E402  (the one JSON reader of the package)

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
REGISTER = "design/role-rules.json"
HOMES = ("agents", "skills", "references", "handoffs")
SUFFIXES = (".md", ".yaml", ".yml", ".json")
ROW_KEYS = ("id", "rule", "source", "carriers")
ID_RE = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*")
DRIVE_RE = re.compile(r"^[A-Za-z]:")
# The package's own marker comments: one line each, nothing else is stripped (a multi-line comment is never a marker).
MARKER_RE = re.compile(r"<!--\s*(?:kind:|roles:|gen|/gen)[^\n]*?-->")
ANCHOR_MIN_WORDS, ANCHOR_MAX_WORDS, ANCHOR_MAX_CHARS, RULE_MAX_CHARS = 2, 6, 80, 300

EXPECT_ID = "a lowercase id like `case-focus-twin` ([a-z0-9]+(-[a-z0-9]+)*)"
EXPECT_RULE = f"a non-empty one-line string of at most {RULE_MAX_CHARS} characters"
EXPECT_SOURCE = "a non-empty string naming the owner's word, a finding, a spec id with key or a backlog id"
EXPECT_CARRIERS = 'a non-empty list of {"file": <package-relative posix path>, "anchor": <2-6 words>}'
EXPECT_ANCHOR = (f"{ANCHOR_MIN_WORDS}-{ANCHOR_MAX_WORDS} consecutive words of the rule's own sentence, "
                 f"at most {ANCHOR_MAX_CHARS} characters")


def fold(text: str) -> str:
    """Whitespace runs (CRLF, indentation, wraps, U+00A0) to one space, then casefold: layout and case are never a loss."""
    return " ".join(text.split()).casefold()


def strip_markers(text: str) -> str:
    return MARKER_RE.sub("", text)


def _strings(value) -> list:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for v in value.values() for s in _strings(v)]
    if isinstance(value, list):
        return [s for v in value for s in _strings(v)]
    return []


def _bad(index, ident, key, wrong, expected) -> str:
    return f'role-rules: row {index} ({ident or "no id"}): {key} {wrong}; expected {expected}.'


def _register_problems(data, why=None) -> list:
    """Register level: readable, an object, schema_version 1, a `rows` list. At most one finding."""
    form = ('a JSON object {"schema_version": 1, "note", "rows": [...]}; restore it from git or fix the JSON')
    if why is not None:
        return [f"role-rules: {REGISTER} cannot be read ({why}). Expected {form}."]
    if data.get("schema_version") != 1:
        return [f"role-rules: {REGISTER} cannot be read (schema_version is {data.get('schema_version')!r}, not 1). "
                f"Expected {form}."]
    if not isinstance(data.get("rows"), list):
        return [f"role-rules: {REGISTER} cannot be read (`rows` is missing or not a list). Expected {form}."]
    return []


def load(root=PLUGIN_ROOT):
    """(rows, problems). An absent or unreadable register is a problem, never an empty list of rows."""
    path = Path(root) / REGISTER
    if not path.is_file():
        return [], _register_problems(None, "absent")
    try:
        if path.stat().st_size == 0:
            return [], _register_problems(None, "0 bytes")
    except OSError as exc:
        return [], _register_problems(None, f"cannot open ({type(exc).__name__})")
    data = read_json(path, default=None, kind=dict)
    if data is None:
        return [], _register_problems(None, "not a UTF-8 JSON object")
    problems = _register_problems(data)
    return ([] if problems else list(data["rows"])), problems


def _path_problem(file) -> str:
    """Why `file` is not a legal carrier path, or ''. Package-relative posix path under one of the four role homes."""
    if not isinstance(file, str) or not file:
        return "is not a non-empty string"
    if "\\" in file or file.startswith("/") or DRIVE_RE.match(file) or ".." in PurePosixPath(file).parts:
        return "is not a package-relative posix path (no backslash, no leading /, no drive, no ..)"
    parts = PurePosixPath(file).parts
    if parts[0] not in HOMES or len(parts) < 2 or (parts[0] == "skills" and "evals" in parts[:-1]):
        return "is outside the role homes"
    if PurePosixPath(file).suffix not in SUFFIXES:
        return f"has the suffix {PurePosixPath(file).suffix or '(none)'!r}, which no role reads as text"
    return ""


def _row_problems(index, row) -> list:
    """The schema of one row (shape). A row with a problem is never searched."""
    if not isinstance(row, dict):
        return [_bad(index, None, "the row", "is not an object", "an object with the keys id, rule, source, carriers")]
    ident = row.get("id") if isinstance(row.get("id"), str) else None
    out = []
    for key in ROW_KEYS:
        if key not in row:
            out.append(_bad(index, ident, key, "is missing", f"the key `{key}` (a row holds exactly {', '.join(ROW_KEYS)})"))
    for key in row:
        if key not in ROW_KEYS:
            out.append(_bad(index, ident, key, "is an unknown key", f"only {', '.join(ROW_KEYS)} (a typo such as `anchors` or `carrier`?)"))
    if "id" in row and not (isinstance(row["id"], str) and ID_RE.fullmatch(row["id"])):
        out.append(_bad(index, ident, "id", f"is {row['id']!r}", EXPECT_ID))
    rule = row.get("rule")
    if "rule" in row and not (isinstance(rule, str) and rule.strip() and "\n" not in rule and len(rule) <= RULE_MAX_CHARS):
        out.append(_bad(index, ident, "rule", "is empty, not a string, multi-line or too long", EXPECT_RULE))
    source = row.get("source")
    if "source" in row and not (isinstance(source, str) and source.strip()):
        out.append(_bad(index, ident, "source", "is empty or not a string", EXPECT_SOURCE))
    carriers = row.get("carriers")
    if "carriers" in row and not (isinstance(carriers, list) and carriers):
        out.append(_bad(index, ident, "carriers", "is empty or not a list", EXPECT_CARRIERS))
    elif isinstance(carriers, list):
        seen = set()
        for n, item in enumerate(carriers, 1):
            where = f"carriers[{n}]"
            if not isinstance(item, dict) or set(item) != {"file", "anchor"}:
                out.append(_bad(index, ident, where, "is not an object with exactly `file` and `anchor`", EXPECT_CARRIERS))
                continue
            if isinstance(item["file"], str) and item["file"] in seen:
                out.append(_bad(index, ident, f"{where}.file", f"names {item['file']} again",
                                "one carrier entry per file; put the second rule in its own row"))
            elif isinstance(item["file"], str):
                seen.add(item["file"])
            why = _path_problem(item["file"])
            if why.startswith("has the suffix"):
                out.append(_bad(index, ident, f"{where}.file", f"{item['file']} {why}",
                                f"a text carrier with one of the suffixes {', '.join(SUFFIXES)}"))
            elif why == "is outside the role homes":
                out.append(f"role-rules: {ident or 'no id'}: {item['file']} is not a role carrier (agents/, skills/, references/, "
                           "handoffs/). A rule lives where a role reads it (FR-44).")
            elif why:
                out.append(_bad(index, ident, f"{where}.file", why, "a package-relative posix path under agents/, skills/, "
                                                                  "references/ or handoffs/"))
            anchor = item["anchor"]
            words = len(anchor.split()) if isinstance(anchor, str) else 0
            if not (isinstance(anchor, str) and ANCHOR_MIN_WORDS <= words <= ANCHOR_MAX_WORDS
                    and len(" ".join(anchor.split())) <= ANCHOR_MAX_CHARS):
                out.append(_bad(index, ident, f"{where}.anchor", f"has {words} word(s) or is over {ANCHOR_MAX_CHARS} characters"
                                if isinstance(anchor, str) else "is not a string", EXPECT_ANCHOR))
    return out


def _duplicate_problems(rows) -> list:
    """Two rows with one id, or two rows guarding the same folded anchor in the same carrier (xref). Valid rows only."""
    out, ids, guards = [], {}, {}
    for index, row in rows:
        if row["id"] in ids:
            out.append(f"role-rules: id {row['id']} is used by rows {ids[row['id']]} and {index}; expected unique ids - rename one.")
        else:
            ids[row["id"]] = index
        for item in row["carriers"]:
            key = (item["file"], fold(item["anchor"]))
            if key in guards and guards[key] != row["id"]:
                out.append(f'role-rules: rows {guards[key]} and {row["id"]} guard the same anchor "{item["anchor"]}" in '
                           f"{item['file']}; one rule, one row - merge them.")
            guards.setdefault(key, row["id"])
    return out


def _carrier_text(root, file):
    """(raw text, folded searchable text, reason). `reason` is '' when the carrier was read; a .json carrier gives its string values."""
    path = Path(root) / file
    if not path.is_file():
        return None, None, "missing"
    try:
        raw = path.read_bytes()
    except OSError as exc:
        return None, None, f"cannot open ({type(exc).__name__})"
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return None, None, "not UTF-8"
    if file.endswith(".json"):
        data = read_json(path, default=None)
        if data is None:
            return None, None, "not JSON"
        text = "\n".join(_strings(data))
        return text, fold(text), ""
    return text, fold(strip_markers(text)), ""


def _carrier_problems(root, row, cache) -> list:
    """Every carrier of one valid row holds its anchor exactly once (xref)."""
    ident, out, counts = row["id"], [], {}
    for item in row["carriers"]:
        file, anchor = item["file"], item["anchor"]
        if file not in cache:
            cache[file] = _carrier_text(root, file)
        raw, text, reason = cache[file]
        if reason == "missing":
            out.append(f"role-rules: {ident}: carrier {file} does not exist. If the text moved, point the row at the new file in "
                       "the same diff; if the rule is retired, remove the row as above.")
            continue
        if reason:
            out.append(f"role-rules: {ident}: carrier {file} cannot be read ({reason}). Expected a UTF-8 text file.")
            continue
        n = text.count(fold(anchor))
        counts[file] = (n, raw is not None and not file.endswith(".json") and fold(raw).count(fold(anchor)))
    for item in row["carriers"]:
        file, anchor = item["file"], item["anchor"]
        if file not in counts:
            continue
        n, before = counts[file]
        held = [o["file"] for o in row["carriers"] if o["file"] != file and counts.get(o["file"], (0,))[0] == 1]
        lost = (f'role-rules: {ident}: {file} lost the rule "{row["rule"]}" (source: {row["source"]}) - ')
        retire = (f'if the rule is retired, remove the row in the same diff and name whose word retires it '
                  f'(owner\'s word, finding or spec id) in the commit message as "role-rules: retire {ident} -- <whose word>".')
        tail = f" - still held by: {', '.join(held)}" if held and len(row["carriers"]) > 1 else ""
        if n == 0 and before:
            out.append(lost + f'the anchor "{anchor}" stands only inside a package marker comment (<!-- kind/roles/gen -->), '
                       "which is not text a rule lives in. Put the rule in the text, or retire the row as above." + tail)
        elif n == 0:
            out.append(lost + f'the anchor "{anchor}" is not in the text. Expected: the anchor exactly once. Restore the rule in '
                       f"{file}; if you reworded it, put 2-6 words of the new wording that occur once into the row's anchor in "
                       f"the same diff; {retire}" + tail)
        elif n > 1:
            out.append(f'role-rules: {ident}: {file} carries the anchor "{anchor}" {n} times. Expected exactly once, so that '
                       "deleting the rule turns this red. Choose 2-6 words of the rule's own sentence that occur once "
                       "(role_rules.py --check counts them).")
    return out


def _scan(root):
    """(findings, rows, carriers searched): register, then row schema, then duplicates, then per row per carrier."""
    rows, problems = load(root)
    findings = list(problems)
    valid = []
    for index, row in enumerate(rows, 1):
        bad = _row_problems(index, row)
        findings += bad
        if not bad:
            valid.append((index, row))
    findings += _duplicate_problems(valid)
    cache = {}
    for _index, row in valid:
        findings += _carrier_problems(root, row, cache)
    return findings, len(rows), sum(len(row["carriers"]) for _i, row in valid)


def findings(root=PLUGIN_ROOT) -> list:
    """Every problem, one FR-1 line each. An empty list means every rule of the register holds."""
    return _scan(root)[0]


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args != ["--check"]:
        print("usage: role_rules.py --check")
        return 2
    found, rows, carriers = _scan(PLUGIN_ROOT)
    for line in found:
        print(line)
    if not found and rows == 0:
        print("role-rules: 0 rows - no rule of a role is guarded")
    print(f"role-rules: {rows} rows, {carriers} carriers checked, {len(found)} finding(s)")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
