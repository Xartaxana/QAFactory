"""assertion_detectors.py - the ONE reader of `references/detectors.json` `assertion_probes` (B-373).

A library module: no CLI, writes nothing, standard library only, and no import of any runtime of
`probe_by_code` / `red_sandbox` / `validate_artifacts` (they import THIS - FR-17: one reader of one table).

The table says how a test in a language other than Python is probed live: how its declaration, its body
and its assertion forms look, which one-for-one inversion each form has and the failure message that
inversion must fire, and how the runner's stack frames name the test file. It is closed variety, so it
is data (FR-13); the code here only validates it and hands it out.

The reader is STRICT. An unreadable file, an absent key and a malformed entry are three different
refusals (`DetectorsUnreadable`, `DetectorsKeyAbsent`, `DetectorEntryMalformed`), because an unknown is
never reported as "no entry" (FR-41): a probe that read a half-valid table as "this language has no
entry" would send a role to add a row that is already there. Every message names the field and what was
expected (FR-1). Anything that fails is a gap of the factory's data, never a verdict on a test.

  assertion_detectors(path=None) -> {language id: entry}   (validated; regexes are still strings)
  assertion_heads(table=None)    -> [head regex, ...]       (the accessor the other readers use, A11; `table` is
                                                               the validated table, never the raw document)
  assert_line_patterns(path=None) -> [regex, ...]           the `assert_lines` key: which lines of a self-fix
                                                               count as an assertion (B-407 C); a typed error when it
                                                               cannot be read, and ASSERT_LINE_FLOOR is the caller's
  shape_patterns(key, path=None) -> [regex, ...]            a key of plain regexes (`sleep`, `locator`,
                                                               `locator_words`, `negative_code`; B-407 C), same errors
  entry_for_suffix(doc, suffix)  -> (language id, entry) | (None, None)
  grammar_of(entry)              -> (frames, skip_frames, frame_path)   for `reporters.assertion_site`
  message_forms(form)            -> [variant, ...]          the ways the probe's marker enters the broken check's message
                                                               (t-1968 N1); [] = the form takes no message
  marker_expression(entry, token) -> str                    the entry's `marker_expr` with the probe's token in, or ""
                                                               (a table entry or the AST entry: same field)
  ast_entry(suffix, path=None)   -> (language id, entry) | (None, None)   the `assertion_probes_ast` entry of a language
                                                               read by an AST (Python); `entry_for_suffix` never reads it
  frames_deepest(entry)          -> "first" | "last" | None     which frame of a stack lies deepest; None = unknown
  declaration_regex(entry, name, helper=False) -> compiled declaration pattern for one name
  fires_matches(fires_as, subject) -> bool          `re.search(fires_as, subject)`, no added flags (L7)
  fires_in(fires_as, text, by_line=True) -> bool    THE one "does this failure text fire" reader: the whole text, and
                                                    (by default) each non-blank line with its leading blanks cut
  soft_stated(entry) -> (patterns, note)            the entry's soft forms: `[]` = "this framework's plain forms have no
                                                    soft form" (stated), a key that is absent reads as `[]` WITH a note
                                                    "the row does not say" (t-2064 P1, AR-23)
  actual_arg_of(form) -> int | "compare_left" | None  which argument of the form's call is the value the check reads (the
                                                    "actual"); None = the row does not say (a form in doubt has no key)
  no_retry_flags(entry, source_text, notes=None) -> [flag, ...]   the runner flags that switch retries off, by what the test
                                                    FILE imports (`probe_no_retry`); `[]` when no row's `source` matches
  interruption_texts(entry) -> [regex, ...]         the runner's own text for "the test was cut" (`interruption_texts`);
                                                    `[]` when the entry has none
  soft_scopes_of(entry, notes=None) -> [{opens, head}, ...]   the entry's soft SCOPES (`soft_scopes`, t-2064 P1b); absent and `[]`
                                                    read the same; a row whose regex fails is left out with a note
"""
import json
import os
import re
from pathlib import Path

REL = "references/detectors.json"
KEY = "assertion_probes"
# Tests point the reader at a broken copy through this variable (the way `PROBE_RUN_SUITE` replaces the
# runner); a path given as an argument wins over it.
ENV_FILE = "ASSERTION_DETECTORS_FILE"
DETECTORS_FILE = Path(__file__).resolve().parents[1] / "references" / "detectors.json"
ASSERT_LINES_KEY = "assert_lines"
# What counts as an assertion line when `assert_lines` cannot be read (an older copy of the references next to a
# newer script, a broken file): the same six patterns the shipped key holds. A check on a role's work may only
# over-refuse, never go quiet because a table was missing (B-407 C, E-C4), so the caller falls back to these.
ASSERT_LINE_FLOOR = (r"(?i)assert", r"\bexpect\s*\(", r"(?i)\bshould\b", r"\bverify\s*\(", r"\brequire\.\w+\(",
                     r"\bt\.(Error|Errorf|Fatal|Fatalf|Fail|FailNow)\(")

DECLARATION_STYLES = ("method", "call")
STATEMENT_ENDS = ("semicolon", "semicolon_or_newline")
MATCHER_AT = ("head", "after_args", "second_arg")
FRAME_PATHS = ("path", "basename")
ESCAPES = ("backslash", "double", "none")
NAME = "{name}"

ENTRY_FIELDS = {
    "required": ("suffixes", "lexer", "declaration_style", "test_declaration", "body_open",
                 "helper_declaration", "name_separators", "tail_join", "statement_end", "assertions",
                 "frames", "skip_frames", "frame_path", "compiled", "builds_by_default",
                 "no_rebuild_flags"),
    "optional": ("helper_body_open", "report_separators", "display_name", "conditional_directive",
                 "soft_assert_patterns", "soft_report", "title_tag", "title_template", "title_placeholders",
                 "group_declaration", "group_each_declaration", "each_declaration", "loop_heads", "marker_expr",
                 "frames_deepest", "marker_read", "import_forms", "passed_residual", "probe_no_retry",
                 "interruption_texts", "soft_scopes"),
}
# t-2064 P1b: `soft_scopes` rows {opens, head?}: a SCOPE whose checks do not stop one another (AssertJ assertSoftly, JUnit assertAll, NUnit
# Assert.Multiple). `opens` is a regex over the code that ends on the scope's OPENING bracket; the scope runs to the balanced closing.
# `head` (optional) is matched where a check starts: when present, only a check it matches is one of the scope's soft checks.
# Round 2 (t-2273): `closes` (optional) is a regex of the statement that ENDS a scope which is not a bracket (a variable that is opened by a
# declaration and closed by a call on it). A row with `closes` opens at the declaration `opens` matches (no trailing bracket needed) and ends
# at the first later `closes` match in the same body; `opens` may hold named groups, and `{name}` in `closes` and in `head` is replaced by the
# text the group matched (regex-escaped) - `fill_scope_regex`.
SCOPE_ROW_FIELDS = {"required": ("opens",), "optional": ("head", "closes")}
_BRACKET_END = re.compile(r"(?:\\[({\[]|\[[({\[]\])$")   # a pattern whose last token is an opening bracket
# t-2064 P1: `actual_arg` of a form - the 1-based number of the argument of the form's call that holds the value the check reads, or
# one of ACTUAL_ARG_WORDS for a form that has no call (Python `assert`: the left side of the comparison). A row is written ONLY
# where the order is verified in the library's documentation and on a sample; a form in doubt has no key.
ACTUAL_ARG_WORDS = ("compare_left",)
# `probe_no_retry`: rows {source, flags} - when the whole test file matches `source`, the runner is called with `flags` added so a
# probe's purpose-made red is not run twice (a project's own retries). The flags never become a verdict on the test.
RETRY_ROW_FIELDS = ("source", "flags")
# t-2045 N5: how a file of this language names the files it imports, so the probe can follow ONE hop out of a test body that holds no
# check (`import_forms`, read only through `import_forms()`). A row is {pattern, resolve, suffixes}: `pattern` a regex with a named
# group `path`, `resolve` one of IMPORT_RESOLVE, `suffixes` optional (the entry's own when absent). Absent or [] = no form: this file only.
IMPORT_RESOLVE = ("relative", "dotted")
IMPORT_ROW_FIELDS = ("pattern", "resolve", "suffixes")
IMPORT_GROUP = "path"
# t-2064 N3b (B1): the fields of a failure's report row the probe's own token may be read from, per runner (`marker_read`). A
# runner whose long traceback prints argument values (pytest) echoes the joined token inside a failure TEXT when a callee throws
# after the message was built, so it reads the `message` only; a runner whose text never echoes values reads both.
MARKER_READ_FIELDS = ("message", "text")
MARKER_READ_DEFAULT = ("message",)       # absent or unreadable: the narrow one (the error goes toward a judgment, never a proof)
# t-2045 N2: the shared contract of a language read by an AST, beside the table (`assertion_probes_ast`; Python today). The
# fields are the table entry's own that do not depend on a lexer or on assertion forms.
AST_KEY = "assertion_probes_ast"
AST_FIELDS = {
    "required": ("suffixes", "marker_expr", "frames", "skip_frames", "frame_path", "compiled", "builds_by_default",
                 "no_rebuild_flags", "forms"),
    "optional": ("frames_deepest", "marker_read", "passed_residual", "soft_assert_patterns"),
}
# t-2045 N2b: the check vocabulary of a language read by an AST - the rows of `forms`. The SHAPES are a closed set of AST shapes
# the reader knows (code); every name, rename, wrap text and message slot is a row's data (AR-1). A shape pairs with ONE kind of
# inversion and with the message slots that can sit on it.
AST_FORM_FIELDS = {
    "required": ("id", "shape", "invert"),
    "optional": ("names", "receivers", "min_args", "source", "message", "fires_as", "matcher_at", "actual_arg"),
}
AST_SHAPE_KIND = {"assert": "wrap_test", "call": "wrap_arg", "method": "rename", "chain": "method_pattern", "with": None}
AST_MESSAGE_SHAPE = {"assert_msg": "assert", "arg": "call", "kw": "method", "head_kw": "chain"}
ARG = "{arg}"
FRAMES_DEEPEST = ("first", "last")
# t-1968 N1: how the probe's own marker enters the message of the broken check. A variant is {id, at, args, insert} and
# optionally {string_arg, source, not_source, not_after}; `insert` holds MARKER once, an entry's `marker_expr` holds TOKEN once.
MESSAGE_AT = ("args_close", "after_args")     # and `arg_start:<n>`, checked by `_message_at`
MESSAGE_REQUIRED = ("id", "at", "args", "insert")
MESSAGE_OPTIONAL = ("string_arg", "source", "not_source", "not_after")
MARKER = "{marker}"
TOKEN = "{token}"
# EP1-37: the optional fields `test_source.read_file` reads a test file by. A regex field must compile; a field that
# is present and broken is a gap of the data, never "the language has none". Plain regexes (no {name}):
TEST_SOURCE_REGEX_FIELDS = ("title_tag", "group_declaration", "group_each_declaration", "each_declaration", "loop_heads")
# What a refusal shows when a language has no entry: the shape of the row to add (FR-1, FR-2: the door).
ENTRY_SHAPE = (
    '"' + KEY + '": {"<language id>": {"suffixes": [".ext"], "lexer": {"line_comments": ["//"], '
    '"block_comments": [["/*", "*/"]], "strings": [{"open": "\\"", "close": "\\"", "escape": "backslash"}]}, '
    '"declaration_style": "method|call", "test_declaration": "<regex with one {name}>", "body_open": "<regex>", '
    '"helper_declaration": "<regex with one {name}>", "name_separators": ["::"], "tail_join": ".", '
    '"statement_end": "semicolon|semicolon_or_newline", "assertions": [{"head": "<regex>", '
    '"matcher_at": "head|after_args|second_arg", "invert": [{"find": "<regex>", "replace": "<text>", '
    '"fires_as": "<regex of the failure the inverted form must show>"}]}], "frames": ["<regex with groups '
    'path and line>"], "skip_frames": ["<regex>"], "frame_path": "path|basename", "compiled": false, '
    '"builds_by_default": [], "no_rebuild_flags": []}} (optional, for a call-style language whose files are read '
    'to list their tests: "title_tag", "title_template": {"open", "close"}, "title_placeholders": [<regex>], '
    '"group_declaration", "group_each_declaration", "each_declaration", "loop_heads")')


class DetectorsError(ValueError):
    """The assertion-probe table cannot be used. `kind` says which of the three it is."""
    kind = ""


class DetectorsUnreadable(DetectorsError):
    kind = "unreadable"


class DetectorsKeyAbsent(DetectorsError):
    kind = "absent"


class DetectorEntryMalformed(DetectorsError):
    kind = "malformed"

    def __init__(self, field: str, message: str):
        super().__init__(message)
        self.field = field


# --- reading ----------------------------------------------------------------------------------------

def detectors_path(path=None) -> Path:
    return Path(path or os.environ.get(ENV_FILE) or DETECTORS_FILE)


_SHIPPED_TEXT: dict = {}     # {(path, mtime_ns, size): text} - the shipped file's text, read once per process (t-2064 par.12 N4 (c))


def _document(where: Path, expected: str = KEY):
    """The parsed detectors file, or DetectorsUnreadable (the one place the file is opened).

    The SHIPPED file's text is read once per process (`parse_node` asks for it on every call): the cache is keyed by the path, the
    file's mtime and size, so a rewrite of the file is read again, and it holds the TEXT, so every caller parses its own fresh
    document and nothing a caller does to it outlives the call. A file at any other path (a test's scratch copy, the env override,
    a path given as an argument) is never cached: it is read on every call, as before."""
    try:
        if where == DETECTORS_FILE:
            stat = where.stat()
            key = (str(where), stat.st_mtime_ns, stat.st_size)
            if key not in _SHIPPED_TEXT:
                _SHIPPED_TEXT.clear()
                _SHIPPED_TEXT[key] = where.read_text(encoding="utf-8-sig")
            return json.loads(_SHIPPED_TEXT[key])
        return json.loads(where.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise DetectorsUnreadable(
            f"{REL} cannot be read ({type(exc).__name__}: {str(exc)[:120]}): this is a gap of the factory's data "
            f"({where}), not of the test. Expected: a JSON object with the key `{expected}`") from exc


def _keyed_table(doc, key: str, shape_text: str) -> dict:
    """The non-empty `{language id: raw entry}` object under `key` of the parsed document, or DetectorsKeyAbsent /
    DetectorEntryMalformed (the one preamble of the two readers of a language table: `assertion_detectors` and `ast_entry`)."""
    if not isinstance(doc, dict) or key not in doc:
        raise DetectorsKeyAbsent(
            f"{REL} has no `{key}` key (found: {', '.join(sorted(doc)[:8]) if isinstance(doc, dict) else 'not an object'}):"
            f" a gap of the factory's data, not of the test. {shape_text}")
    table = doc[key]
    if not isinstance(table, dict) or not table:
        raise DetectorEntryMalformed(key, f"{REL} `{key}` must be a non-empty object with one entry per language id, "
                                          f"got {type(table).__name__}")
    return table


def _claims_once(doc: dict) -> None:
    """A suffix belongs to one entry of ONE key: a suffix claimed by both `assertion_probes` and `assertion_probes_ast` is
    refused, because which reader judges a file must never be a guess. Reads the raw suffixes of both keys; a key that is
    absent or not shaped as a table is the other reader's refusal, not this check's."""
    claimed = {}
    for key in (KEY, AST_KEY):
        table = doc.get(key)
        if not isinstance(table, dict):
            continue
        for language, entry in table.items():
            suffixes = entry.get("suffixes") if isinstance(entry, dict) else None
            for suffix in (suffixes if isinstance(suffixes, list) else []):
                if not isinstance(suffix, str):
                    continue
                low = suffix.lower()
                if low in claimed and claimed[low][0] != key:
                    other_key, other = claimed[low]
                    raise DetectorEntryMalformed(
                        f"{key}.{language}.suffixes",
                        f"{key}.{language}.suffixes: {suffix!r} is also claimed by {other_key}.{other}; a suffix belongs to "
                        f"exactly one entry of one key (which reader judges a file must never be a guess). Fix the rows in "
                        f"{REL}; this is a gap of the factory's data, not of the test")
                claimed.setdefault(low, (key, language))


def assertion_detectors(path=None) -> dict:
    """{language id: entry}, every entry validated. Raises one of the three typed errors."""
    doc = _document(detectors_path(path))
    table = _keyed_table(doc, KEY, f"The key holds one entry per language: {ENTRY_SHAPE}")
    entries, seen = {}, {}
    for language, entry in table.items():
        entries[language] = _entry(language, entry)
        for suffix in entries[language]["suffixes"]:
            if suffix in seen:
                raise DetectorEntryMalformed(
                    f"{KEY}.{language}.suffixes",
                    f"{KEY}.{language}.suffixes: {suffix!r} is also claimed by {seen[suffix]!r}; a suffix belongs to "
                    "exactly one entry (which grammar reads a file must never be a guess). Fix the rows in "
                    f"{REL}; this is a gap of the factory's data, not of the test")
            seen[suffix] = language
    _claims_once(doc)                       # after the entries: a table entry's own refusal (`.py`, twice) comes first
    return entries


def assertion_heads(table=None) -> list:
    """The head regex of every assertion form of every entry, in table order, without repeats: what
    another reader counts as "this line is an assertion" (B-407's `assert_lines` is unioned with it).

    `table` is the VALIDATED table `assertion_detectors()` returns - `{language id: entry}` - or nothing (the
    shipped table is read). It is NOT the raw `detectors.json` document (the one that holds the key
    `assertion_probes` beside `retry_markers` and the rest): that is refused with a ValueError that says so."""
    table = assertion_detectors() if table is None else table
    if not isinstance(table, dict) or KEY in table or not all(
            isinstance(entry, dict) and isinstance(entry.get("assertions"), list) for entry in table.values()):
        raise ValueError(
            "assertion_heads takes the validated table `{language id: entry}` that `assertion_detectors()` "
            f"returns (every entry holding `assertions`), not the raw {REL} document (the one with the key "
            f"`{KEY}`): call `assertion_heads(assertion_detectors())`, or `assertion_heads()`")
    out = []
    for entry in table.values():
        for form in entry["assertions"]:
            if form["head"] not in out:
                out.append(form["head"])
    return out


def shape_patterns(key: str, path=None) -> list:
    """The regexes of one plain-list key of `detectors.json` (`sleep`, `locator`, `locator_words`, `negative_code`,
    `assert_lines`), validated: a non-empty list of non-empty strings that each compile. The same three refusals
    as `assertion_detectors` (unreadable file, absent key, malformed key), and a partly valid list is malformed as
    a whole - an unknown is never a shorter list (FR-41). Each reader decides what its failure means (the
    direction in which it may err): arch_check keeps today's regex, judge_code asks the question of every test,
    check_self_fixes keeps ASSERT_LINE_FLOOR."""
    doc = _document(detectors_path(path), key)
    if not isinstance(doc, dict) or key not in doc:
        raise DetectorsKeyAbsent(
            f"{REL} has no `{key}` key (found: {', '.join(sorted(doc)[:8]) if isinstance(doc, dict) else 'not an object'}):"
            f" a gap of the factory's data (an older copy of the references?). Expected: a non-empty list of regex strings")
    value = doc[key]
    if not isinstance(value, list) or not value or not all(isinstance(p, str) and p for p in value):
        raise DetectorEntryMalformed(key, f"{REL} `{key}` must be a non-empty list of non-empty regex strings, "
                                          f"got {type(value).__name__}: a gap of the factory's data")
    for pattern in value:
        try:
            re.compile(pattern)
        except re.error as exc:
            raise DetectorEntryMalformed(key, f"{REL} `{key}`: {pattern!r} does not compile ({exc}): a gap of the "
                                              "factory's data") from exc
    return list(value)


def assert_line_patterns(path=None) -> list:
    """The `assert_lines` key: the patterns that make a line of a self-fix's `before`/`after` an assertion line
    (B-407 C). Loads the document itself, the way `assertion_detectors(path)` does; raises the typed error when the
    key cannot be read, and the caller falls back to ASSERT_LINE_FLOOR with a note. Not unioned with
    `assertion_heads()` here: the union is the caller's, because `assertion_heads` has its own failure."""
    return shape_patterns(ASSERT_LINES_KEY, path)


def entry_for_suffix(table, suffix: str) -> tuple:
    suffix = str(suffix or "").lower()
    for language, entry in table.items():
        if suffix and suffix in entry["suffixes"]:
            return language, entry
    return None, None


def ast_entry(suffix: str, path=None) -> tuple:
    """(language id, entry) of the `assertion_probes_ast` key for `suffix`, or (None, None) when no entry claims it (THE one
    reader of that key, AR-13). Strict as the table is: an unreadable file, an absent key and a malformed entry are the three
    typed errors, never "no entry" (FR-41). `entry_for_suffix` does not read this key: `.py` is never an entry of the table."""
    doc = _document(detectors_path(path), AST_KEY)
    table = _keyed_table(doc, AST_KEY, "The key holds one entry per language read by an AST, with the fields "
                                       + ", ".join(AST_FIELDS["required"]))
    entries = {language: _ast_entry(language, entry) for language, entry in table.items()}
    _claims_once(doc)
    suffix = str(suffix or "").lower()
    for language, entry in entries.items():
        if suffix and suffix in entry["suffixes"]:
            return language, entry
    return None, None


def frames_deepest(entry) -> str | None:
    """Which frame of a failure's stack lies deepest in the code under test: "first" or "last". Absent or any other word is
    None: the frame fact is unknown (AR-23), and the caller then reads no frame by position."""
    value = entry.get("frames_deepest") if isinstance(entry, dict) else None
    return value if isinstance(value, str) and value in FRAMES_DEEPEST else None


# --- one entry's use ----------------------------------------------------------------------------------

def _list_of(value) -> list:
    return [value] if isinstance(value, str) else list(value or [])


def grammar_of(entry: dict) -> tuple:
    """(frames, skip_frames, frame_path) as `reporters.assertion_site` takes them. A fresh list each call:
    the caller owns what it gets."""
    return _list_of(entry["frames"]), _list_of(entry["skip_frames"]), entry["frame_path"]


def soft_patterns(entry: dict) -> list:
    """The entry's `soft_assert_patterns` (the assertion forms that record a failure and let the test go on); `[]` when the
    language declares none. A fresh list each call."""
    return _list_of((entry or {}).get("soft_assert_patterns"))


SOFT_UNSAID = "the row does not say whether this framework has a soft form (`soft_assert_patterns` is absent): read as none"


def soft_stated(entry) -> tuple:
    """`(patterns, note)` - the entry's soft forms and what the data did or did not say (t-2064 P1, AR-23, AR-1).

    `soft_assert_patterns: []` STATES that this framework's plain forms have no soft form: `([], "")`. An entry that leaves the key
    out says nothing: it reads as the same `[]` (the same plan) and the note says the row does not say. A pattern that does not
    compile reads as `[]` with a note, never an exception (the loader refuses such a row; this reader meets entries that were not
    validated). The note is "" when nothing needs saying. A fresh list each call. "No soft form" is data here, never a language."""
    if not isinstance(entry, dict) or "soft_assert_patterns" not in entry:
        return [], SOFT_UNSAID
    patterns = _list_of(entry.get("soft_assert_patterns"))
    for pattern in patterns:
        try:
            re.compile(pattern)
        except (re.error, TypeError):
            return [], f"a `soft_assert_patterns` row does not compile ({str(pattern)[:60]!r}): read as none"
    return patterns, ""


def actual_arg_of(form):
    """The `actual_arg` of one assertion form (a table `assertions` row or an AST `forms` row): the 1-based number of the call's
    argument that holds the value the check reads, or `"compare_left"` (Python `assert`: the left side of the comparison); None
    when the row does not say - a form in doubt has no key, and the caller then falls back to the other roads (t-2064 P1, AR-23)."""
    value = form.get("actual_arg") if isinstance(form, dict) else None
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value >= 1:
        return value
    return value if isinstance(value, str) and value in ACTUAL_ARG_WORDS else None


def no_retry_flags(entry, source_text, notes=None) -> list:
    """The runner flags of the first `probe_no_retry` row whose `source` regex matches the test FILE's text; `[]` otherwise
    (t-2064 P1, F-P7, F-P10). The row is chosen by what the file imports, never by the language or the runner's form id, so a
    project's own script that forwards the flag fires it too. No entry key, no source text or no match: `[]`. A `source` that does
    not compile: `[]` and, when `notes` is a list, one line appended to it - never an exception. A fresh list each call."""
    rows = entry.get("probe_no_retry") if isinstance(entry, dict) else None
    if not isinstance(rows, list) or not isinstance(source_text, str):
        return []
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("source"), str) or not isinstance(row.get("flags"), list):
            continue
        try:
            hit = re.search(row["source"], source_text) is not None
        except re.error as exc:
            if isinstance(notes, list):
                notes.append(f"a `probe_no_retry` source does not compile ({exc}): no retry flags added")
            return []
        if hit:
            return [flag for flag in row["flags"] if isinstance(flag, str) and flag]
    return []


def interruption_texts(entry) -> list:
    """The regexes of the runner's own text that says "this test was cut" (`interruption_texts`, t-2064 P1, F-P11): a row of the
    entry that only DEMOTES a marker read in a failure - it never proves anything. `[]` when the entry has none (nothing to demote
    on that language). Strings only, a fresh list each call."""
    value = entry.get("interruption_texts") if isinstance(entry, dict) else None
    return [text for text in value if isinstance(text, str) and text] if isinstance(value, list) else []


def fill_scope_regex(pattern: str, values: dict) -> str:
    """`pattern` with every `{name}` of `values` replaced by that text, regex-escaped (t-2273: the variable a scope's `opens` captured,
    carried into its `closes` and `head`). A `{name}` that has no value stays as written; nothing is compiled here."""
    for name, value in (values or {}).items():
        pattern = pattern.replace("{" + name + "}", re.escape(value if isinstance(value, str) else ""))
    return pattern


def _compiled_scope_row(row: dict) -> None:
    """Compile the three regexes of a scope row; `{name}` stands for a group of `opens` and is tried with a dummy text. Raises
    `re.error` or `TypeError` - the caller turns it into a note (reader) or a refusal (loader)."""
    for field in ("opens", "head", "closes"):
        if row.get(field) is not None and not isinstance(row[field], str):
            raise TypeError(f"`{field}` must be a regex string")
    opens = re.compile(row["opens"])
    dummies = {name: "x" for name in opens.groupindex}
    for field in ("head", "closes"):
        if row.get(field) is not None:
            re.compile(fill_scope_regex(row[field], dummies))


def soft_scopes_of(entry, notes=None) -> list:
    """The soft SCOPES of an entry (`soft_scopes`, t-2064 P1b): `[{"opens": regex, "head": regex | None, "closes": regex | None}]`, in the
    row order, each a fresh dict. A scope is a region in which the checks do not stop one another. Without `closes` it is a bracketed
    region: `opens` ends on its opening bracket and the scope runs to the balanced closing. With `closes` it opens at the declaration
    `opens` matches and ends at the first later `closes` match in the same body (a variable closed by a call, t-2273). `head`, when
    given, is matched where a check starts (only a check it matches is one of the scope's soft ones).

    An entry with no key and an entry with `[]` read the SAME `[]` (AR-23: no scope is a legal row, never an error). A row that is not
    {opens, head?, closes?}, or whose regex does not compile, is left OUT and, when `notes` is a list, one line says which - never an
    exception (the loader refuses such a row; this reader meets entries that were not validated). No language is read: a scope is a row."""
    rows = entry.get("soft_scopes") if isinstance(entry, dict) else None
    out = []
    for position, row in enumerate(rows if isinstance(rows, list) else []):
        try:
            if not isinstance(row, dict) or "opens" not in row or set(row) - set(SCOPE_ROW_FIELDS["required"] + SCOPE_ROW_FIELDS["optional"]):
                raise TypeError("a row must be {opens, head?, closes?}")
            _compiled_scope_row(row)
        except (re.error, TypeError) as exc:
            if isinstance(notes, list):
                notes.append(f"`soft_scopes[{position}]` is not read ({str(exc)[:80]}): no scope from that row")
            continue
        out.append({"opens": row["opens"], "head": row.get("head"), "closes": row.get("closes")})
    return out


def soft_report_of(entry: dict) -> tuple:
    """(error_head, after_frame_ok) of the entry's `soft_report`, or (None, []) when the language declares none."""
    report = (entry or {}).get("soft_report")
    if not isinstance(report, dict) or not isinstance(report.get("error_head"), str):
        return None, []
    return report["error_head"], _list_of(report.get("after_frame_ok"))


def message_forms(form: dict) -> list:
    """THE one reader of a form's `message` field (t-1968 N1, AR-13): the variants, in table order, as fresh dicts. `[]` when
    the form takes no message or declares none (AR-23: the empty outcome is a legal row, the probe then adds no marker and
    says nothing is wrong). The table was validated by `assertion_detectors()`; a form that is not a dict reads as `[]`."""
    variants = (form or {}).get("message") if isinstance(form, dict) else None
    return [dict(variant) for variant in variants] if isinstance(variants, list) else []


def marker_read(entry) -> list:
    """THE one reader of an entry's `marker_read` (t-2064 N3b B1, AR-13): the fields of a report row (`message`, `text`) the
    probe's token may be read from, as a fresh list. Absent, empty or not a list of those words reads as `MARKER_READ_DEFAULT`
    (the message only: the error direction is toward a judgment). The entry was validated by its loader."""
    value = entry.get("marker_read") if isinstance(entry, dict) else None
    if isinstance(value, list) and value and all(word in MARKER_READ_FIELDS for word in value):
        return list(value)
    return list(MARKER_READ_DEFAULT)


def import_forms(entry) -> list:
    """THE one reader of an entry's `import_forms` (t-2045 N5, AR-13): [{pattern (compiled, multiline), resolve, suffixes}] in table
    order, the suffixes defaulting to the entry's own and lower-cased; [] when the entry has none (that language follows no import:
    this file only). The entry was validated by its loader."""
    rows = entry.get("import_forms") if isinstance(entry, dict) else None
    return [{"pattern": re.compile(row["pattern"], re.MULTILINE), "resolve": row["resolve"],
             "suffixes": [s.lower() for s in row.get("suffixes") or entry["suffixes"]]} for row in rows or []]


def marker_expression(entry: dict, token: str) -> str:
    """The entry's `marker_expr` with the probe's `token` put in: the expression of the language that builds
    `qa-probe-<token>` at run time. "" when the entry declares none (then no form gets a marker)."""
    expr = (entry or {}).get("marker_expr")
    return expr.replace(TOKEN, token) if isinstance(expr, str) and expr else ""


def declaration_regex(entry: dict, name: str, helper: bool = False):
    """The compiled declaration pattern with `name` escaped in: the data names the shape, `re.escape` keeps
    the title of a test from being read as regex syntax."""
    pattern = entry["helper_declaration" if helper else "test_declaration"]
    return re.compile(pattern.replace(NAME, re.escape(name)))


def fires_matches(fires_as: str, subject: str) -> bool:
    """`re.search(fires_as, subject)` and nothing added: no flags, so an anchor means the start of the
    subject (L7). A row that cannot be compiled is a gap, so it never matches."""
    try:
        return re.search(fires_as, subject or "") is not None
    except re.error:
        return False


def fires_in(fires_as: str, text: str, by_line: bool = True) -> bool:
    """THE one definition of "the failure text fires `fires_as`" (AR-13): `fires_matches` on the whole text, and with
    `by_line` also on each non-blank line, leading whitespace cut, so a `^` binds to the start of a LINE (a Playwright
    report opens with a header and its own `Error: <msg>` line; the library's `expect(received)...` line is indented after
    them). A code frame echo stays out by its `> 12 |` prefix, not by the anchor. `by_line=False` is the whole text only: the
    caller passes it for the AUTHOR's own message, whose lines must not be able to fire a detector (AR-28)."""
    text = str(text or "")
    if fires_matches(fires_as, text):
        return True
    return by_line and any(fires_matches(fires_as, line.lstrip()) for line in text.splitlines() if line.strip())


def top_level_alternatives(pattern: str) -> list:
    """The alternatives of `pattern` split at the `|` that sit outside any group, class or escape."""
    parts, depth, in_class, start, index = [], 0, False, 0, 0
    while index < len(pattern):
        char = pattern[index]
        if char == "\\":
            index += 2
            continue
        if in_class:
            in_class = char != "]"
        elif char == "[":
            in_class = True
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        elif char == "|" and depth == 0:
            parts.append(pattern[start:index])
            start = index + 1
        index += 1
    parts.append(pattern[start:])
    return parts


def anchored(pattern: str) -> bool:
    """Every top-level alternative starts with `^` (after the global flags group, if there is one), and `^`
    means the start of the SUBJECT: a global `m` flag makes it match at every line, which is exactly the
    code-frame echo an anchor exists to keep out (L7), so such a pattern is not anchored."""
    flags = re.match(r"^\(\?([aiLmsux]+)\)", pattern)
    if flags and "m" in flags.group(1):
        return False
    body = pattern[flags.end():] if flags else pattern
    return all(alt.startswith("^") for alt in top_level_alternatives(body))


# --- validation ---------------------------------------------------------------------------------------

def _bad(language: str, path: str, message: str, row_id: str = "", key: str = KEY):
    field = f"{key}.{language}.{path}"
    where = f"{field} ({row_id})" if row_id else field
    return DetectorEntryMalformed(field, f"{where}: {message}. Fix the row in {REL}; this is a gap of the "
                                         "factory's data, not of the test")


def _regex(language: str, path: str, pattern, row_id: str = "", with_name: bool = False, key: str = KEY):
    if not isinstance(pattern, str) or not pattern:
        raise _bad(language, path, f"must be a non-empty regex string, got {pattern!r}", row_id, key)
    probe = pattern
    if with_name:
        if pattern.count(NAME) != 1:
            raise _bad(language, path, f"must hold exactly one {NAME} (got {pattern.count(NAME)})", row_id, key)
        probe = pattern.replace(NAME, re.escape("x"))
    try:
        return re.compile(probe)
    except re.error as exc:
        raise _bad(language, path, f"does not compile ({exc})", row_id, key) from exc


def _strings(language: str, path: str, value, *, allow_empty: bool = True, key: str = KEY) -> list:
    if not isinstance(value, list) or not all(isinstance(v, str) and v for v in value) or \
            (not allow_empty and not value):
        raise _bad(language, path, "must be a list of non-empty strings" + ("" if allow_empty else " (not empty)"), key=key)
    return value


def _lexer(language: str, value) -> dict:
    if not isinstance(value, dict):
        raise _bad(language, "lexer", "must be an object {line_comments, block_comments, strings}")
    extra = sorted(set(value) - {"line_comments", "block_comments", "strings", "regex_literal"})
    if extra:
        raise _bad(language, "lexer", f"unknown field(s) {', '.join(extra)}")
    _strings(language, "lexer.line_comments", value.get("line_comments", []))
    blocks = value.get("block_comments", [])
    if not isinstance(blocks, list) or not all(isinstance(b, list) and len(b) == 2 and all(
            isinstance(x, str) and x for x in b) for b in blocks):
        raise _bad(language, "lexer.block_comments", "must be a list of [open, close] pairs of non-empty strings")
    strings = value.get("strings")
    if not isinstance(strings, list) or not strings:
        raise _bad(language, "lexer.strings", "must be a non-empty list of {open, close, escape}")
    for index, item in enumerate(strings):
        if not isinstance(item, dict) or not {"open", "close", "escape"} <= set(item) \
                or set(item) - {"open", "close", "escape", "multiline"} or not (
                isinstance(item["open"], str) and item["open"] and isinstance(item["close"], str) and item["close"]):
            raise _bad(language, f"lexer.strings[{index}]",
                       "must be {open, close, escape[, multiline]} with non-empty delimiters")
        if item["escape"] not in ESCAPES:
            raise _bad(language, f"lexer.strings[{index}].escape", f"must be one of {', '.join(ESCAPES)}")
        if "multiline" in item and not isinstance(item["multiline"], bool):
            raise _bad(language, f"lexer.strings[{index}].multiline", "must be true or false")
    if "regex_literal" in value:
        _regex_literal(language, value["regex_literal"])
    return value


def _regex_literal(language: str, spec) -> None:
    """The optional `lexer.regex_literal`: a `/`-style literal that is told from a division by what comes before it."""
    path = "lexer.regex_literal"
    keys = {"open", "close", "escape", "class_open", "class_close", "multiline", "after"}
    if not isinstance(spec, dict) or not keys - {"multiline"} <= set(spec) or set(spec) - keys:
        raise _bad(language, path, "must be {open, close, escape, class_open, class_close, after[, multiline]}")
    for key in ("open", "close", "escape", "class_open", "class_close"):
        if not (isinstance(spec[key], str) and len(spec[key]) == 1):
            raise _bad(language, f"{path}.{key}", "must be exactly one character")
    if "multiline" in spec and not isinstance(spec["multiline"], bool):
        raise _bad(language, f"{path}.multiline", "must be true or false")
    after = spec["after"]
    if not isinstance(after, dict) or set(after) != {"chars", "words"} or not isinstance(after["chars"], str) \
            or not isinstance(after["words"], list) or not all(isinstance(w, str) and w for w in after["words"]) \
            or not (after["chars"] or after["words"]):
        raise _bad(language, f"{path}.after", "must be {chars: a string, words: a list of words}, not both empty "
                   "(what makes a `/` open the literal instead of divide)")


def _pair(language: str, base: str, index: int, pair, call_style: bool) -> None:
    path = f"{base}.invert[{index}]"
    row_id = str(pair.get("id") or "") if isinstance(pair, dict) else ""
    if not isinstance(pair, dict) or not {"find", "replace", "fires_as"} <= set(pair) \
            or set(pair) - {"id", "find", "replace", "fires_as"}:
        raise _bad(language, path, "must be {find, replace, fires_as} (and optionally an id), nothing else", row_id)
    if "id" in pair and not (isinstance(pair["id"], str) and pair["id"]):
        raise _bad(language, path + ".id", "must be a non-empty string", row_id)
    find = _regex(language, path + ".find", pair["find"], row_id)
    if not isinstance(pair["replace"], str):
        raise _bad(language, path + ".replace", "must be a string (group references as \\1)", row_id)
    for ref in re.findall(r"\\(\d+)", pair["replace"]):
        if int(ref) > find.groups:
            raise _bad(language, path + ".replace", f"names group {ref}, and `find` has {find.groups}", row_id)
    fires = pair["fires_as"]
    _regex(language, path + ".fires_as", fires, row_id)
    if call_style and not anchored(fires):
        # A jest-style failure text carries a code frame that echoes the mutated statement; only an
        # alternative that is anchored to the start of the subject keeps that echo out (L7).
        raise _bad(language, path + ".fires_as", "every alternative of a call-style row must start with `^`, "
                   "so a code frame echoing the mutated statement can never fire it", row_id)


def _message_at(language: str, path: str, value, row_id: str) -> None:
    if value in MESSAGE_AT:
        return
    number = value[len("arg_start:"):] if isinstance(value, str) and value.startswith("arg_start:") else ""
    if not (number.isdigit() and int(number) >= 1):
        raise _bad(language, path, f"must be one of {', '.join(MESSAGE_AT)}, or arg_start:<n> with n >= 1 (got {value!r})", row_id)


def _message(language: str, base: str, variants) -> None:
    """The optional `message` of a form: a list of variants, `[]` meaning "this form takes no message" (AR-23)."""
    path = base + ".message"
    if not isinstance(variants, list):
        raise _bad(language, path, "must be a list of variants ([] = the form takes no message)")
    for position, variant in enumerate(variants):
        here = f"{path}[{position}]"
        row_id = str(variant.get("id") or "") if isinstance(variant, dict) else ""
        if not isinstance(variant, dict) or not set(MESSAGE_REQUIRED) <= set(variant) \
                or set(variant) - set(MESSAGE_REQUIRED) - set(MESSAGE_OPTIONAL):
            raise _bad(language, here, f"must be {{{', '.join(MESSAGE_REQUIRED)}}} and optionally "
                                       f"{{{', '.join(MESSAGE_OPTIONAL)}}}, nothing else", row_id)
        if not (isinstance(variant["id"], str) and variant["id"]):
            raise _bad(language, here + ".id", "must be a non-empty string", row_id)
        _message_at(language, here + ".at", variant["at"], row_id)
        for key in ("args", "string_arg"):
            if key in variant and not (isinstance(variant[key], int) and not isinstance(variant[key], bool)
                                       and variant[key] >= (0 if key == "args" else 1)):
                raise _bad(language, f"{here}.{key}", "must be a whole number (args >= 0, string_arg >= 1)", row_id)
        for key in ("source", "not_source", "not_after"):
            if key in variant:
                _regex(language, f"{here}.{key}", variant[key], row_id)
        if not (isinstance(variant["insert"], str) and variant["insert"].count(MARKER) == 1):
            raise _bad(language, here + ".insert", f"must be a string holding {MARKER} exactly once", row_id)


def _actual_arg(language: str, path: str, value, row_id: str = "", key: str = KEY) -> None:
    """The optional `actual_arg` of a form: a whole number from 1 (the call's argument that holds the value the check reads) or
    one of ACTUAL_ARG_WORDS. Anything else is a gap of the data (a row in doubt is left out, never written as a guess)."""
    if isinstance(value, bool) or not ((isinstance(value, int) and value >= 1) or (isinstance(value, str) and value in ACTUAL_ARG_WORDS)):
        raise _bad(language, path, f"must be a whole number from 1 or one of {', '.join(ACTUAL_ARG_WORDS)}, got {value!r} "
                   "(leave the key out where the argument order is not verified)", row_id, key)


def _soft_assert_patterns(language: str, value, key: str = KEY) -> None:
    """`soft_assert_patterns`: the assertion forms that do not stop a test when they fail (Playwright `expect.soft`). A list of
    regexes; `[]` is a legal and meaningful row - "this framework's plain forms have no soft form" (t-2064 P1, AR-23). A list that
    does not compile is a gap of the data, never "no soft form"."""
    for position, pattern in enumerate(_strings(language, "soft_assert_patterns", value, key=key)):
        _regex(language, f"soft_assert_patterns[{position}]", pattern, key=key)


def _probe_no_retry(language: str, value, key: str = KEY) -> None:
    """The optional `probe_no_retry` of an entry: a list (empty = none) of {source, flags}; the source must compile, the flags are a
    non-empty list of non-empty strings."""
    if not isinstance(value, list):
        raise _bad(language, "probe_no_retry", "must be a list of {source: regex, flags: [text]} (an empty list: none)", key=key)
    for position, row in enumerate(value):
        path = f"probe_no_retry[{position}]"
        if not isinstance(row, dict) or set(row) != set(RETRY_ROW_FIELDS):
            raise _bad(language, path, f"must be exactly {{{', '.join(RETRY_ROW_FIELDS)}}}", key=key)
        _regex(language, f"{path}.source", row["source"], key=key)
        _strings(language, f"{path}.flags", row["flags"], allow_empty=False, key=key)


def _interruption_texts(language: str, value, key: str = KEY) -> None:
    """The optional `interruption_texts` of an entry: a list of regexes (the runner's text for "the test was cut")."""
    for position, pattern in enumerate(_strings(language, "interruption_texts", value, key=key)):
        _regex(language, f"interruption_texts[{position}]", pattern, key=key)


def _soft_scopes(language: str, value, key: str = KEY) -> None:
    """The optional `soft_scopes` of an entry: a list (empty = none) of {opens, head?, closes?}; all are regexes that compile (`{name}` in
    `head` and `closes` stands for a named group of `opens`). A row that does not is a gap of the data, never "no scope" (t-2064 P1b,
    AR-23). A row without `closes` is a bracketed scope, so its `opens` must end on an opening bracket; only a row WITH `closes` may not
    (t-2273)."""
    if not isinstance(value, list):
        raise _bad(language, "soft_scopes", "must be a list of {opens: regex, head: regex (optional), closes: regex (optional)} (an empty list: none)", key=key)
    for position, row in enumerate(value):
        path = f"soft_scopes[{position}]"
        if not isinstance(row, dict) or "opens" not in row or set(row) - set(SCOPE_ROW_FIELDS["required"] + SCOPE_ROW_FIELDS["optional"]):
            raise _bad(language, path, "must be {opens, head, closes} with `head` and `closes` optional", key=key)
        _regex(language, f"{path}.opens", row["opens"], key=key)
        dummies = {name: "x" for name in re.compile(row["opens"]).groupindex}
        for field in ("head", "closes"):
            if field in row:
                _regex(language, f"{path}.{field}", fill_scope_regex(row[field], dummies) if isinstance(row[field], str) else row[field], key=key)
        if "closes" not in row and not _BRACKET_END.search(row["opens"]):
            raise _bad(language, f"{path}.opens", "must end on an opening bracket - the scope runs to its closing - unless the row has `closes`", key=key)


def _form(language: str, index: int, form, call_style: bool) -> None:
    base = f"assertions[{index}]"
    if not isinstance(form, dict) or not {"head", "matcher_at", "invert"} <= set(form) \
            or set(form) - {"head", "matcher_at", "invert", "message", "actual_arg"}:
        raise _bad(language, base, "must be {head, matcher_at, invert} and optionally {message, actual_arg}")
    _regex(language, base + ".head", form["head"])
    if form["matcher_at"] not in MATCHER_AT:
        raise _bad(language, base + ".matcher_at", f"must be one of {', '.join(MATCHER_AT)}")
    if "actual_arg" in form:
        _actual_arg(language, base + ".actual_arg", form["actual_arg"])
    if "message" in form:
        _message(language, base, form["message"])
    pairs = form["invert"]
    if pairs is None:
        return
    if not isinstance(pairs, list) or not pairs:
        raise _bad(language, base + ".invert", "must be null (no inversion) or a non-empty list of pairs")
    for position, pair in enumerate(pairs):
        _pair(language, base, position, pair, call_style)


def _frames(language: str, entry: dict, key: str = KEY) -> None:
    frames = _list_of(entry["frames"]) if isinstance(entry["frames"], (str, list)) else None
    if not frames or not all(isinstance(f, str) for f in frames):
        raise _bad(language, "frames", "must be a regex or a non-empty list of regexes", key=key)
    for position, pattern in enumerate(frames):
        rx = _regex(language, f"frames[{position}]", pattern, key=key)
        if not {"path", "line"} <= set(rx.groupindex):
            raise _bad(language, f"frames[{position}]", "must name the groups `path` and `line`", key=key)
        if entry["frame_path"] == "basename" and "qual" not in rx.groupindex:
            raise _bad(language, f"frames[{position}]", "a frame_path `basename` grammar must name the group `qual` "
                       "(the qualified method name: its package decides which same-named file it is)", key=key)
    skip = entry["skip_frames"]
    if not isinstance(skip, (str, list)) or not all(isinstance(s, str) for s in _list_of(skip)):
        raise _bad(language, "skip_frames", "must be a regex or a list of regexes", key=key)
    for position, pattern in enumerate(_list_of(skip)):
        _regex(language, f"skip_frames[{position}]", pattern, key=key)


def _suffixes(language: str, value, key: str = KEY, allow_py: bool = False) -> list:
    """The lower-cased suffixes of an entry. `.py` is refused unless `allow_py` (the AST key's entry holds it); a suffix listed
    twice is refused in both keys."""
    _strings(language, "suffixes", value, allow_empty=False, key=key)
    out = []
    for suffix in value:
        low = suffix.lower()
        if not low.startswith(".") or len(low) < 2 or "/" in low or "\\" in low:
            raise _bad(language, "suffixes", f"{suffix!r} must be a file suffix like `{'.py' if allow_py else '.cs'}`", key=key)
        if low == ".py" and not allow_py:
            raise _bad(language, "suffixes", "`.py` is never an entry: a Python test is probed by the AST path", key=key)
        if low in out:
            raise _bad(language, "suffixes", f"{suffix!r} is listed twice", key=key)
        out.append(low)
    return out


MARKER_PREFIX = "qa-probe-"
SAMPLE_TOKEN = "0a1b2c3d4e5f"
_LITERAL = re.compile(r"""'((?:[^'\\]|\\.)*)'|"((?:[^"\\]|\\.)*)\"""")


def marker_value(expr: str, token: str):
    """What a `marker_expr` holding `token` evaluates to, read from its string literals in any of the shipped languages' joins
    (`'-'.join([a, b])`, `string.Join("-", a, b)`, `[a, b].join('-')`) or a single literal: the literals joined by one of them
    taken as the separator, or all of them joined by nothing. A shape this does not read gives None. Data only: no code of the
    entry is run."""
    literals = [single or double for single, double in _LITERAL.findall(expr.replace(TOKEN, token))]
    options = ["".join(literals)]
    for i, separator in enumerate(literals):
        options.append(separator.join(literals[:i] + literals[i + 1:]))
    return next((o for o in options if o == MARKER_PREFIX + token), None)


def _marker_expr(language: str, expr, key: str = KEY) -> None:
    if not isinstance(expr, str) or expr.count(TOKEN) != 1 or "\n" in expr or "\r" in expr:
        raise _bad(language, "marker_expr", f"must be one line of the language's code holding {TOKEN} exactly once "
                                            "(the probe builds qa-probe-<token> from separate pieces at run time)", key=key)
    if marker_value(expr, SAMPLE_TOKEN) is None:
        raise _bad(language, "marker_expr", f"with the token {SAMPLE_TOKEN!r} put in must evaluate to exactly "
                                            f"{MARKER_PREFIX + SAMPLE_TOKEN!r} (the probe reads the message back as "
                                            f"{MARKER_PREFIX}<token>); got the literals of {expr!r}", key=key)


def _marker_read(language: str, value, key: str = KEY) -> None:
    if (not isinstance(value, list) or not value or not all(isinstance(word, str) and word in MARKER_READ_FIELDS for word in value)
            or len(set(value)) != len(value)):
        raise _bad(language, "marker_read", f"must be a non-empty list of distinct words from {', '.join(MARKER_READ_FIELDS)} "
                                            "(the report-row fields the probe's token may be read from)", key=key)


def _passed_residual(language: str, value, key: str = KEY) -> None:
    """The optional `passed_residual` of an entry (t-2064 par.12 d): the one sentence a `no_failure` row of an entry that is not
    compiled prints as its residual (what a pass here does not rule out). DATA of the entry, never a language branch of the
    reader; absent = no residual is printed. Present, it is a non-empty string."""
    if not isinstance(value, str) or not value.strip():
        raise _bad(language, "passed_residual", "must be a non-empty string (the residual a passed row of this entry prints); "
                                                "leave the key out for none", key=key)


def _import_forms(language: str, value, key: str = KEY) -> None:
    """The optional `import_forms` of an entry: a list (empty = none) of {pattern, resolve[, suffixes]}. A row that does not
    compile, has no group `path`, names a `resolve` the reader does not know or holds another key is a gap of the data."""
    if not isinstance(value, list):
        raise _bad(language, "import_forms", "must be a list of {pattern, resolve[, suffixes]} (an empty list: this file only)", key=key)
    for position, row in enumerate(value):
        path = f"import_forms[{position}]"
        if not isinstance(row, dict):
            raise _bad(language, path, f"must be an object {{pattern, resolve[, suffixes]}}, got {type(row).__name__}", key=key)
        extra = sorted(set(row) - set(IMPORT_ROW_FIELDS))
        if extra or "pattern" not in row or "resolve" not in row:
            raise _bad(language, path, f"holds the fields {', '.join(IMPORT_ROW_FIELDS)} (suffixes optional); "
                       + (f"unknown: {', '.join(extra)}" if extra else "pattern and resolve are required"), key=key)
        pattern = row["pattern"]
        if not isinstance(pattern, str) or not pattern:
            raise _bad(language, f"{path}.pattern", f"must be a non-empty regex string, got {pattern!r}", key=key)
        try:
            compiled = re.compile(pattern, re.MULTILINE)
        except re.error as exc:
            raise _bad(language, f"{path}.pattern", f"does not compile ({exc})", key=key) from exc
        if IMPORT_GROUP not in compiled.groupindex:
            raise _bad(language, f"{path}.pattern", f"must hold a named group (?P<{IMPORT_GROUP}>...): the text the import names", key=key)
        if row["resolve"] not in IMPORT_RESOLVE:
            raise _bad(language, f"{path}.resolve", f"must be one of {', '.join(IMPORT_RESOLVE)}, got {row['resolve']!r}", key=key)
        if "suffixes" in row:
            suffixes = row["suffixes"]
            if (not isinstance(suffixes, list) or not suffixes
                    or not all(isinstance(s, str) and s.startswith(".") and len(s) > 1 and "/" not in s and "\\" not in s for s in suffixes)):
                raise _bad(language, f"{path}.suffixes", "must be a non-empty list of file suffixes like `.ts`", key=key)


def _ast_entry(language: str, entry) -> dict:
    """One entry of `assertion_probes_ast`, validated: the table entry's shared fields (suffixes, marker_expr, frames,
    skip_frames, frame_path, compiled, the build fields) and the optional `frames_deepest` (not judged here: an unknown word
    reads as None in `frames_deepest`). Unlike a table entry it has no lexer and no assertion forms, and it MAY hold `.py`."""
    key = AST_KEY
    if not isinstance(entry, dict):
        raise _bad(language, "", f"must be an object, got {type(entry).__name__}", key=key)
    missing = [k for k in AST_FIELDS["required"] if k not in entry]
    if missing:
        raise _bad(language, missing[0], f"is missing (the entry also lacks: {', '.join(missing[1:]) or 'nothing else'})", key=key)
    extra = sorted(set(entry) - set(AST_FIELDS["required"]) - set(AST_FIELDS["optional"]))
    if extra:
        raise _bad(language, extra[0], f"is not a field of an entry (unknown: {', '.join(extra)})", key=key)
    out = dict(entry)
    out["suffixes"] = _suffixes(language, entry["suffixes"], key, allow_py=True)
    _marker_expr(language, entry["marker_expr"], key)
    if "marker_read" in entry:
        _marker_read(language, entry["marker_read"], key)
    if "passed_residual" in entry:
        _passed_residual(language, entry["passed_residual"], key)
    if "soft_assert_patterns" in entry:
        _soft_assert_patterns(language, entry["soft_assert_patterns"], key)
    for field in ("builds_by_default", "no_rebuild_flags"):
        _strings(language, field, entry[field], key=key)
    if not isinstance(entry["compiled"], bool):
        raise _bad(language, "compiled", "must be true or false", key=key)
    if entry["frame_path"] not in FRAME_PATHS:
        raise _bad(language, "frame_path", f"must be one of {', '.join(FRAME_PATHS)}", key=key)
    _frames(language, entry, key)
    out["forms"] = _ast_forms(language, entry["forms"])
    return out


def _count(language: str, path: str, value, row_id: str, minimum: int = 0) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        raise _bad(language, path, f"must be a whole number, {minimum} or more, got {value!r}", row_id, AST_KEY)
    return value


def _ast_forms(language: str, forms) -> list:
    """The `forms` of an `assertion_probes_ast` entry, validated (t-2045 N2b): a non-empty list of rows, each {id, shape,
    invert[, names, receivers, min_args, source, message, fires_as, matcher_at]}. A row that cannot work - an unknown shape, an
    inversion of another shape, a regex that does not compile, a message slot the shape has no place for, a call whose
    inverted argument its `min_args` does not guarantee - is a gap of the data, named by field and row id, never a guess at run time."""
    key = AST_KEY
    if not isinstance(forms, list) or not forms:
        raise _bad(language, "forms", "must be a non-empty list of rows {id, shape, invert}", key=key)
    seen = set()
    for index, form in enumerate(forms):
        base = f"forms[{index}]"
        if not isinstance(form, dict):
            raise _bad(language, base, f"must be an object, got {type(form).__name__}", key=key)
        row = form.get("id") if isinstance(form.get("id"), str) else ""
        missing = [k for k in AST_FORM_FIELDS["required"] if k not in form]
        if missing:
            raise _bad(language, f"{base}.{missing[0]}", "is missing", row, key)
        extra = sorted(set(form) - set(AST_FORM_FIELDS["required"]) - set(AST_FORM_FIELDS["optional"]))
        if extra:
            raise _bad(language, f"{base}.{extra[0]}", f"is not a field of a row (unknown: {', '.join(extra)})", row, key)
        if not row or row in seen:
            raise _bad(language, f"{base}.id", "must be a non-empty string, one per row" + (f" ({row!r} is listed twice)" if row else ""),
                       row, key)
        seen.add(row)
        shape = form["shape"]
        if shape not in AST_SHAPE_KIND:
            raise _bad(language, f"{base}.shape", f"must be one of {', '.join(AST_SHAPE_KIND)}", row, key)
        for field in ("names", "receivers"):
            if field in form:
                _strings(language, f"{base}.{field}", form[field], allow_empty=False, key=key)
        invert = form["invert"]
        if "min_args" in form:
            if shape not in ("call", "method"):
                raise _bad(language, f"{base}.min_args", f"does not apply to the {shape} shape", row, key)
            _count(language, f"{base}.min_args", form["min_args"], row)
        if "source" in form:
            _regex(language, f"{base}.source", form["source"], row, key=key)
        if "fires_as" in form and form["fires_as"] is not None:
            _regex(language, f"{base}.fires_as", form["fires_as"], row, key=key)
        if "matcher_at" in form and form["matcher_at"] not in MATCHER_AT:
            raise _bad(language, f"{base}.matcher_at", f"must be one of {', '.join(MATCHER_AT)}", row, key)
        if "actual_arg" in form:
            _actual_arg(language, f"{base}.actual_arg", form["actual_arg"], row, key)
        if shape in ("call", "chain", "with") and "names" not in form:
            raise _bad(language, f"{base}.names", f"is required by the {shape} shape (the names it matches)", row, key)
        if shape == "with":
            if "receivers" not in form:
                raise _bad(language, f"{base}.receivers", "is required by the with shape (the receivers it matches)", row, key)
            if invert is not None:
                raise _bad(language, f"{base}.invert", "must be null on the with shape: no inversion of a context manager exists "
                                                       "in data (the plan names it as not invertible by code)", row, key)
        elif shape == "method":
            if "receivers" not in form:
                raise _bad(language, f"{base}.receivers", "is required by the method shape (the receivers it matches)", row, key)
            if "names" not in form and not (isinstance(invert, dict) and isinstance(invert.get("names"), dict)):
                raise _bad(language, f"{base}.names", "is required by the method shape unless the inversion names its methods", row, key)
        elif "receivers" in form:
            raise _bad(language, f"{base}.receivers", f"does not apply to the {shape} shape", row, key)
        if invert is None:
            if "message" in form:
                raise _bad(language, f"{base}.message", "has nothing to attach to: the row's invert is null", row, key)
            continue
        _ast_invert(language, f"{base}.invert", form, invert, row)
        if "message" in form:
            _ast_message(language, f"{base}.message", form, row)
    return forms


def _ast_invert(language: str, path: str, form: dict, invert, row: str) -> None:
    key, shape = AST_KEY, form["shape"]
    if not isinstance(invert, dict) or invert.get("kind") != AST_SHAPE_KIND[shape]:
        raise _bad(language, f"{path}.kind", f"the {shape} shape is inverted by kind {AST_SHAPE_KIND[shape]!r}; invert must be "
                                             "null or an object of that kind", row, key)
    kind = invert["kind"]
    allowed = {"wrap_test": {"kind"}, "wrap_arg": {"kind", "arg", "wrap"}, "rename": {"kind", "names"},
               "method_pattern": {"kind", "pairs"}}[kind]
    if set(invert) != allowed:
        raise _bad(language, path, f"must hold exactly {', '.join(sorted(allowed))}", row, key)
    if kind == "wrap_arg":
        arg = _count(language, f"{path}.arg", invert["arg"], row)
        if not isinstance(invert["wrap"], str) or invert["wrap"].count(ARG) != 1:
            raise _bad(language, f"{path}.wrap", f"must be a text holding {ARG} exactly once", row, key)
        if not isinstance(form.get("min_args"), int) or form["min_args"] <= arg:
            raise _bad(language, f"{_base(path)}.min_args", f"must be more than the inverted argument ({arg}): a call with "
                                                              "fewer has no such argument", row, key)
    elif kind == "rename":
        names = invert["names"]
        if not isinstance(names, dict) or not names:
            raise _bad(language, f"{path}.names", "must be a non-empty object {method: {to, args}}", row, key)
        for old, spec in names.items():
            if not old or not isinstance(spec, dict) or set(spec) != {"to", "args"} or not isinstance(spec["to"], str) or not spec["to"]:
                raise _bad(language, f"{path}.names.{old}", "must be {to: <method name>, args: <count>}", row, key)
            _count(language, f"{path}.names.{old}.args", spec["args"], row)
    elif kind == "method_pattern":
        pairs = invert["pairs"]
        if not isinstance(pairs, list) or not pairs:
            raise _bad(language, f"{path}.pairs", "must be a non-empty list of {find, replace}", row, key)
        for position, pair in enumerate(pairs):
            at = f"{path}.pairs[{position}]"
            if not isinstance(pair, dict) or set(pair) != {"find", "replace"} or not isinstance(pair["replace"], str):
                raise _bad(language, at, "must be {find: <regex>, replace: <text>}", row, key)
            rx = _regex(language, f"{at}.find", pair["find"], row, key=key)
            try:
                rx.sub(pair["replace"], "")
            except (re.error, IndexError) as exc:
                raise _bad(language, f"{at}.replace", f"is not a replacement of its find ({exc})", row, key) from exc


def _base(path: str) -> str:
    """`forms[2].invert` -> `forms[2]`."""
    return path.rsplit(".", 1)[0]


def _ast_message(language: str, path: str, form: dict, row: str) -> None:
    key, slot = AST_KEY, form["message"]
    if not isinstance(slot, dict) or slot.get("at") not in AST_MESSAGE_SHAPE:
        raise _bad(language, f"{path}.at", f"must be one of {', '.join(AST_MESSAGE_SHAPE)}", row, key)
    at = slot["at"]
    if AST_MESSAGE_SHAPE[at] != form["shape"]:
        raise _bad(language, f"{path}.at", f"{at!r} sits on the {AST_MESSAGE_SHAPE[at]} shape, this row is {form['shape']}", row, key)
    wanted = {"assert_msg": {"at"}, "arg": {"at", "arg"}, "kw": {"at", "kw"}, "head_kw": {"at", "kw", "args"}}[at]
    if set(slot) != wanted:
        raise _bad(language, path, f"must hold exactly {', '.join(sorted(wanted))}", row, key)
    if "kw" in slot and (not isinstance(slot["kw"], str) or not slot["kw"].isidentifier()):
        raise _bad(language, f"{path}.kw", "must be a keyword name", row, key)
    if at == "head_kw":
        _count(language, f"{path}.args", slot["args"], row)
    if at == "arg":
        arg = _count(language, f"{path}.arg", slot["arg"], row)
        if arg <= form["invert"]["arg"] or not isinstance(form.get("min_args"), int) or form["min_args"] < arg:
            raise _bad(language, f"{path}.arg", "must come after the inverted argument and not beyond the row's min_args", row, key)


def _entry(language: str, entry) -> dict:
    if not isinstance(entry, dict):
        raise _bad(language, "", f"must be an object, got {type(entry).__name__}")
    missing = [k for k in ENTRY_FIELDS["required"] if k not in entry]
    if missing:
        raise _bad(language, missing[0], f"is missing (the entry also lacks: {', '.join(missing[1:]) or 'nothing else'})")
    extra = sorted(set(entry) - set(ENTRY_FIELDS["required"]) - set(ENTRY_FIELDS["optional"]))
    if extra:
        raise _bad(language, extra[0], f"is not a field of an entry (unknown: {', '.join(extra)})")
    out = dict(entry)
    out["suffixes"] = _suffixes(language, entry["suffixes"])
    _lexer(language, entry["lexer"])
    if entry["declaration_style"] not in DECLARATION_STYLES:
        raise _bad(language, "declaration_style", f"must be one of {', '.join(DECLARATION_STYLES)}")
    for key in ("test_declaration", "helper_declaration"):
        _regex(language, key, entry[key], with_name=True)
    for key in ("body_open", "helper_body_open", "display_name", "conditional_directive"):
        if key in entry:
            _regex(language, key, entry[key])
    for key in ("name_separators", "report_separators", "builds_by_default", "no_rebuild_flags"):
        if key in entry:
            _strings(language, key, entry[key])
    if "soft_assert_patterns" in entry:
        # EP1-38: the assertion forms that do not stop a test when they fail (Playwright `expect.soft`). `[]` says the
        # framework has none (t-2064 P1); a list that does not compile is a gap of the data, never "no soft form".
        _soft_assert_patterns(language, entry["soft_assert_patterns"])
    if "probe_no_retry" in entry:
        _probe_no_retry(language, entry["probe_no_retry"])
    if "interruption_texts" in entry:
        _interruption_texts(language, entry["interruption_texts"])
    if "soft_scopes" in entry:
        _soft_scopes(language, entry["soft_scopes"])
    if "soft_report" in entry:
        # EP1-38 F-2: how a soft test's failure text is built (the integrity check of `reporters.failure_frames`)
        report = entry["soft_report"]
        if not isinstance(report, dict) or set(report) - {"error_head", "after_frame_ok"} or not isinstance(report.get("error_head"), str):
            raise _bad(language, "soft_report", "must be an object {error_head: regex, after_frame_ok: [regex]}")
        _regex(language, "soft_report.error_head", report["error_head"])
        for position, pattern in enumerate(_strings(language, "soft_report.after_frame_ok", report.get("after_frame_ok", []))):
            _regex(language, f"soft_report.after_frame_ok[{position}]", pattern)
    for key in TEST_SOURCE_REGEX_FIELDS:
        if key in entry:
            _regex(language, key, entry[key])
    if "marker_expr" in entry:
        _marker_expr(language, entry["marker_expr"])
    if "marker_read" in entry:
        _marker_read(language, entry["marker_read"])
    if "passed_residual" in entry:
        _passed_residual(language, entry["passed_residual"])
    if "import_forms" in entry:
        _import_forms(language, entry["import_forms"])
    if "title_template" in entry:
        template = entry["title_template"]
        if not isinstance(template, dict) or set(template) != {"open", "close"} or not all(
                isinstance(template[k], str) and template[k] for k in template):
            raise _bad(language, "title_template", "must be an object {open, close} of two non-empty strings")
    if "title_placeholders" in entry:
        for position, pattern in enumerate(_strings(language, "title_placeholders", entry["title_placeholders"])):
            _regex(language, f"title_placeholders[{position}]", pattern)
    if not isinstance(entry["tail_join"], str) or not entry["tail_join"]:
        raise _bad(language, "tail_join", "must be a non-empty string (one space is legal)")
    if entry["statement_end"] not in STATEMENT_ENDS:
        raise _bad(language, "statement_end", f"must be one of {', '.join(STATEMENT_ENDS)}")
    if not isinstance(entry["compiled"], bool):
        raise _bad(language, "compiled", "must be true or false")
    if entry["frame_path"] not in FRAME_PATHS:
        raise _bad(language, "frame_path", f"must be one of {', '.join(FRAME_PATHS)}")
    forms = entry["assertions"]
    if not isinstance(forms, list) or not forms:
        raise _bad(language, "assertions", "must be a non-empty list of {head, matcher_at, invert}")
    for index, form in enumerate(forms):
        _form(language, index, form, entry["declaration_style"] == "call")
    _frames(language, entry)
    return out
