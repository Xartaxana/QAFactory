"""test_source.py - the ONE reader of a test file written in a language that has an `assertion_probes` entry (EP1-37).

What a language's test file looks like - how a test is declared, how a group is, which part of a title is a tag, which
part a template substitution, what a loop head is - is DATA of its entry in `references/detectors.json` (AR-1). This
module holds no word of any language: it reads the file by the entry, with the lexer `probe_by_code.Source` already is,
and says what it found in one shape:

  read_file(path, rel)  -> {"language", "declarations", "unread": [{"line", "why"}], "why_not", "no_entry"}
  pattern_matches(pattern, title) / matches(decl, report_title)   which report title is this declaration's
  path_pattern(decl, title_join)                                  the pattern of a whole report name (group titles too)
  instance_shas_of(path, report_test_id, report_match, title_join)  the identity of ONE test of the file (B-3, B-4)

`read_file` never raises. A suffix with no entry is `language == ""` and a `why_not`: not a pass and not a refusal here
- the caller says "not read" by name (AR-28, FR-41). A file that has an entry and cannot be read to its end has
`why_not` too, and a test it could not read is in `unread` with its line: the role sees it, the code invents nothing.

`probe_by_code` is imported INSIDE `read_file`: it imports `red_sandbox`, which imports this module for `pattern_matches`
(M-10), so the two import in either order.
"""
import hashlib
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import assertion_detectors as AD  # noqa: E402

MIN_LITERAL = 3           # literal characters (no space, no tag) a templated title must keep to bind a report row
SCOPE = "file_skeleton"   # what the identity covers: the file less the other tests; imported helpers are not covered
WILD = ".+"               # what a template substitution stands for in a pattern


def pattern_matches(pattern, title) -> bool:
    """`re.fullmatch` of a pattern on a report title; a pattern that is empty or does not compile matches nothing."""
    if not isinstance(pattern, str) or not pattern:
        return False
    try:
        return re.fullmatch(pattern, str(title)) is not None
    except re.error:
        return False


def matches(decl: dict, report_title: str) -> bool:
    """Is `report_title` (the raw title of the leaf test, tags included) this declaration's? A declaration with a pattern
    by the pattern, any other by equality with its raw title."""
    if decl.get("pattern"):
        return pattern_matches(decl["pattern"], report_title)
    return report_title == decl.get("title")


def path_pattern(decl: dict, title_join: str) -> str:
    """The pattern of the whole report name of a templated declaration: its group titles as they are, then its own
    pattern, joined by the runner's `title_join`. "" when the declaration has no pattern."""
    if not decl.get("pattern"):
        return ""
    return re.escape(title_join or " ").join([re.escape(c) for c in decl.get("chain") or []] + [decl["pattern"]])


class _Call:
    """The part of a regex match `probe_by_code.body_span` reads (start, end, group(0)) for a call the entry's regex did not
    match whole: the second call of `x.each(rows)('title', body)`, or a call head."""

    def __init__(self, text: str, start: int, end: int):
        self._text, self._start, self._end = text, start, end

    def start(self):
        return self._start

    def end(self):
        return self._end

    def group(self, _n=0):
        return self._text[self._start:self._end]


# --- reading ------------------------------------------------------------------------------------------------------

def _load(path, rel: str) -> dict:
    """Everything one read of the file gives: `{language, entry, bom, text, src, declarations, unread, why_not}`. The bytes
    are read ONCE; `read_file` and the identity both use this."""
    out = {"language": "", "entry": None, "bom": False, "text": "", "src": None, "declarations": [], "unread": [],
           "why_not": "", "no_entry": False}
    suffix = Path(str(rel or path)).suffix.lower()
    try:
        table = AD.assertion_detectors()
    except AD.DetectorsError as exc:
        out["why_not"] = f"references/detectors.json assertion_probes cannot be used ({exc.kind}): {str(exc)[:160]}"
        return out
    language, entry = AD.entry_for_suffix(table, suffix)
    if entry is None:
        out["no_entry"] = True
        out["why_not"] = f"no entry for {suffix or 'a file with no suffix'} in references/detectors.json assertion_probes"
        return out
    out.update(language=language, entry=entry)
    try:
        raw = Path(path).read_bytes()
    except OSError as exc:
        out["why_not"] = f"the file cannot be read ({type(exc).__name__})"
        return out
    out["bom"] = raw.startswith(b"\xef\xbb\xbf")
    try:
        out["text"] = raw[3 if out["bom"] else 0:].decode("utf-8")
    except UnicodeDecodeError:
        out["why_not"] = "the file is not UTF-8, so it is not read and nothing is guessed"
        return out
    from probe_by_code import Refusal, Source   # inside: see the module docstring
    try:
        out["src"] = Source(out["text"], entry["lexer"], str(rel or Path(path).name))
    except Refusal as exc:
        out["why_not"] = str(exc)
        return out
    _declarations(out, str(rel or Path(path).name))
    return out


def read_file(path, rel: str = "") -> dict:
    """`{"language", "declarations", "unread", "why_not", "no_entry"}` of a test file; never raises. `no_entry` is true ONLY
    when the table was read and has no row for the suffix: the one case that is a note. Any other `why_not` on a file is a
    problem to refuse by name (a broken table, a reader defect). See the module docstring."""
    state = {"language": "", "entry": None, "declarations": [], "unread": [], "why_not": "", "no_entry": False}
    try:
        state = _load(path, rel)
    except Exception as exc:   # a reader's own defect is "not read", never a crash of the caller
        state["why_not"] = f"the reader failed ({type(exc).__name__}: {str(exc)[:120]})"
    return {"language": state["language"], "declarations": state["declarations"], "unread": state["unread"],
            "why_not": state["why_not"], "no_entry": state["no_entry"]}


def _strings(entry: dict) -> dict:
    return {spec["open"]: spec for spec in entry["lexer"]["strings"]}


def _literal_at(state: dict, quote_at: int):
    """(raw title, index after the closing delimiter) of the string literal that opens at `quote_at`, or None. The lexer's own
    scanner finds the end; a backslash-escaped delimiter or backslash is unescaped, nothing else."""
    from probe_by_code import _string_end
    text, specs = state["text"], _strings(state["entry"])
    spec = specs.get(text[quote_at:quote_at + 1])
    if spec is None:
        return None
    start = quote_at + len(spec["open"])
    end = _string_end(text, start, spec)
    if end < 0:
        return None
    raw = text[start:end - len(spec["close"])]
    if spec["escape"] == "backslash":
        raw = re.sub(r"\\([\\" + re.escape(spec["close"]) + "])", r"\1", raw)
    return raw, end


def _plain_end(state: dict, end: int) -> bool:
    """Does the string literal that ended at `end` stand alone as the argument (`'a' + b` does not)?"""
    code = state["src"].code
    while end < len(code) and code[end].isspace():
        end += 1
    return end < len(code) and code[end] in ",)"


def _template_parts(raw: str, template) -> list:
    """`raw` split into ("lit", text) and ("sub", `${...}`) parts by the entry's `title_template` (nesting counted); with no
    template the whole title is one literal."""
    if not template:
        return [("lit", raw)]
    parts, i, buf = [], 0, []
    open_, close = template["open"], template["close"]
    while i < len(raw):
        if not raw.startswith(open_, i):
            buf.append(raw[i])
            i += 1
            continue
        depth, j = 1, i + len(open_)
        while j < len(raw) and depth:
            if raw.startswith(open_, j):
                depth, j = depth + 1, j + len(open_)
            elif raw.startswith(close, j):
                depth, j = depth - 1, j + len(close)
            else:
                j += 1
        parts += [("lit", "".join(buf)), ("sub", raw[i:j])]
        buf, i = [], j
    parts.append(("lit", "".join(buf)))
    return parts


def _placeholder_parts(parts: list, placeholders: list) -> list:
    """The literal parts of `parts` split again at the entry's `title_placeholders` (`%s`, `$name`): each is a substitution."""
    holder = re.compile("|".join(f"(?:{p})" for p in placeholders))
    split = []
    for kind, value in parts:
        if kind != "lit":
            split.append((kind, value))
            continue
        at = 0
        for hit in holder.finditer(value):
            split += [("lit", value[at:hit.start()]), ("sub", hit.group(0))]
            at = hit.end()
        split.append(("lit", value[at:]))
    return split


def _shape(raw: str, entry: dict, each: bool):
    """(bare title, pattern, tags, why-unread) of a raw title. Tags go out of the bare title; a template substitution (or, for
    an `each` declaration, a placeholder) makes the title a pattern; a pattern with fewer than MIN_LITERAL literal characters
    is no pattern a report row can be tied to (`${a}${b}` would bind every row)."""
    tag = re.compile(entry["title_tag"]) if entry.get("title_tag") else None
    tags = tag.findall(raw) if tag else []
    bare = " ".join((tag.sub("", raw) if tag else raw).split())
    parts = _template_parts(raw, entry.get("title_template"))
    if each and entry.get("title_placeholders"):
        parts = _placeholder_parts(parts, entry["title_placeholders"])
    if not any(kind == "sub" for kind, _v in parts):
        return bare, "", tags, ""
    literal = "".join(value for kind, value in parts if kind == "lit")
    if tag:
        literal = tag.sub("", literal)
    kept = len("".join(literal.split()))
    if kept < MIN_LITERAL:
        return bare, "", tags, (f"its title is a template with {kept} literal character(s) (fewer than {MIN_LITERAL}): "
                                "a pattern that loose would bind any report row to it")
    return bare, "".join(re.escape(v) if k == "lit" else WILD for k, v in parts if v), tags, ""


def _enclosing(src, position: int) -> list:
    return sorted(o for o, c in src.pairs.items() if o < position < c)


def _opens_loop(src, opener: int, loops, closers: dict) -> bool:
    at = opener
    if src.skeleton[opener] == "{":
        k = opener - 1
        while k >= 0 and src.skeleton[k].isspace():
            k -= 1
        if k >= 0 and src.skeleton[k] == ")" and k in closers:
            at = closers[k]
    return any(m.end() == at + 1 for m in loops.finditer(src.skeleton, max(0, at - 60), at + 1))


def _in_code(src, index: int) -> bool:
    return src.skeleton[index] == src.code[index] and not src.code[index].isspace()


def _groups(state: dict) -> list:
    """(opener, closer, title) of every group of the file; a title that is not ONE plain literal, or is a template (a pattern
    no report group name can be tied to), is None - the tests inside are `unread`, not bound to a name that is never there.
    `group_each_declaration` (`describe.each(rows)('g %s', fn)`): the group of the SECOND call, its title None."""
    entry, src = state["entry"], state["src"]
    groups = []
    if entry.get("group_declaration"):
        for hit in re.finditer(entry["group_declaration"], src.code):
            if not _in_code(src, hit.start()):
                continue
            opener = hit.start() + hit.group(0).index("(")
            read = _literal_at(state, hit.end() - 1)
            title = read[0] if read and _plain_end(state, read[1]) else None
            if title is not None:
                _bare, pattern, _tags, loose = _shape(title, entry, False)
                if pattern or loose:
                    title = None
            if opener in src.pairs:
                groups.append((opener, src.pairs[opener], title))
    if entry.get("group_each_declaration"):
        for hit in re.finditer(entry["group_each_declaration"], src.code):
            first = hit.end() - 1
            if not _in_code(src, hit.start()) or first not in src.pairs:
                continue
            second = src.pairs[first] + 1
            while second < len(src.code) and src.code[second].isspace():
                second += 1
            if second < len(src.code) and src.code[second] == "(" and second in src.pairs:
                groups.append((second, src.pairs[second], None))
    return groups


def _each_calls(state: dict, add, unread: list) -> None:
    """`x.each(rows)('title', fn)`: the second call is the declaration (`add` it, `each=True`); a second call that is not
    (title, function) with a string title is `unread`."""
    entry, src, text = state["entry"], state["src"], state["text"]
    for hit in re.finditer(entry["each_declaration"], src.code):
        if not _in_code(src, hit.start()):
            continue
        first = hit.end() - 1
        if first not in src.pairs:
            continue
        second = src.pairs[first] + 1
        while second < len(src.code) and src.code[second].isspace():
            second += 1
        quote = second + 1
        while quote < len(src.code) and src.code[quote].isspace():
            quote += 1
        read = _literal_at(state, quote) if second < len(src.code) and src.code[second] == "(" else None
        if read is None or second not in src.pairs:
            unread.append({"line": src.line(hit.start()),
                           "why": "the call after the table is not (title, function) with a string title"})
            continue
        add(hit.start(), src.pairs[second] + 1, read[0], True, hit.start(), _Call(text, second, read[1]), read[1])


def _unread_heads(state: dict, found_at: set, unread: list, file: str) -> None:
    """A call head of the test declaration whose title is not a string literal, and that no declaration took: `unread`."""
    from probe_by_code import Refusal, body_span
    entry, src = state["entry"], state["src"]
    cut = entry["test_declaration"].find("\\(")
    if cut < 0 or AD.NAME in entry["test_declaration"][:cut]:
        return
    for hit in re.compile(entry["test_declaration"][:cut + 2]).finditer(src.code):
        if hit.start() in found_at or not _in_code(src, hit.start()) or hit.end() - 1 not in src.pairs:
            continue
        if any(u["line"] == src.line(hit.start()) for u in unread):
            continue
        try:
            body_span(src, entry, hit, False, file)
        except Refusal:
            continue    # a call with no function body is not a test declaration (a skip inside a test, a regex .test())
        unread.append({"line": src.line(hit.start()), "why": "its title is not a string literal"})


def _declarations(state: dict, file: str) -> None:
    """Fill `declarations` and `unread` of a loaded state from the entry's data."""
    from probe_by_code import Refusal, body_span
    entry, src = state["entry"], state["src"]
    call = entry["declaration_style"] == "call"
    declarations, unread, found_at = [], [], set()
    loops = re.compile(entry["loop_heads"]) if entry.get("loop_heads") else None
    closers = {c: o for o, c in src.pairs.items()}
    groups = _groups(state)

    def add(start, close, title, each, line_at, match, quote_end):
        why = ""
        if call and (title is None or not _plain_end(state, quote_end)):
            why = "its title is not a single string literal"
        enclosing = [g for g in groups if g[0] < start < g[1]]
        enclosing.sort(key=lambda g: g[0])
        if not why and any(g[2] is None for g in enclosing):
            why = "it sits in a group whose title is not a single string literal"
        try:
            body = body_span(src, entry, match, False, file)
        except Refusal as exc:
            unread.append({"line": src.line(line_at), "why": str(exc), "at": start})
            return
        if why:
            unread.append({"line": src.line(line_at), "why": why})
            return
        bare, pattern, tags, loose = _shape(title, entry, each)
        if loose:
            unread.append({"line": src.line(line_at), "why": loose})
            return
        looped = bool(loops) and any(_opens_loop(src, o, loops, closers) for o in _enclosing(src, start))
        chain = [g[2] for g in enclosing]
        declarations.append({
            "title": title, "chain": chain, "title_path": chain + [title], "bare_title": bare, "pattern": pattern,
            "generated": bool(each or looped or pattern), "line": src.line(line_at), "end_line": src.line(close - 1),
            "body": body, "span": (line_at, close), "tags": tags})
        found_at.add(line_at)

    title_rx = None
    if entry.get("test_declaration"):
        inner = r"(?P<_title>(?:\\.|[^\\\r\n])*?)" if call else r"(?P<_title>[A-Za-z_$][\w$]*)"
        title_rx = re.compile(entry["test_declaration"].replace(AD.NAME, inner))
    for hit in (title_rx.finditer(src.code) if title_rx else []):
        if not _in_code(src, hit.start()) or "(" not in hit.group(0):
            continue
        if hit.start() and src.code[hit.start() - 1] == ".":
            continue    # E-4: a member call (`/x/.test('abc')`, `obj.test(...)`) is not a declaration
        opener = hit.start() + hit.group(0).index("(")
        if opener not in src.pairs:
            continue
        title = hit.group("_title")
        if call:    # the title as the lexer reads the literal (a backslash-escaped delimiter unescaped)
            read = _literal_at(state, hit.start("_title") - 1)
            title = read[0] if read else title
        add(hit.start(), src.pairs[opener] + 1, title, False, hit.start(), hit, hit.end())
    if call and entry.get("each_declaration"):
        _each_calls(state, add, unread)
    if call and entry.get("test_declaration"):
        _unread_heads(state, found_at, unread, file)
    declarations.sort(key=lambda d: d["span"][0])
    # E-4: a call that has no function body and stands INSIDE a found test's body (`test.skip(cond, 'why')`) is part of that
    # test, not a test of its own: its record goes (the offset `at` was kept for exactly this, and is not part of the shape)
    bodies = [d["body"] for d in declarations]
    unread = [{k: v for k, v in u.items() if k != "at"} for u in unread
              if not any(low < u.get("at", -1) < high for low, high in bodies)]
    unread.sort(key=lambda u: u["line"])
    state["declarations"], state["unread"] = declarations, unread


# --- the identity of one test (B-3, B-4) ----------------------------------------------------------------------------

def _find(declarations: list, report_test_id: str, report_match, title_join: str):
    """The ONE declaration a report id names, or None. By the pattern the contract recorded when it has one, else by the
    title path after the first `::`. Never by a line number: a line moves with every edit above the test (B-2)."""
    join = title_join or " "
    pattern = str((report_match or {}).get("pattern") or "") if isinstance(report_match, dict) else ""
    if pattern:
        hits = [d for d in declarations if path_pattern(d, join) == pattern]
    else:
        tail = str(report_test_id or "").partition("::")[2]
        hits = [d for d in declarations if tail and join.join(d["title_path"]) == tail]
    return hits[0] if len(hits) == 1 else None


def _kept(text: str, cuts: list) -> str:
    out, at = [], 0
    for start, end in cuts:
        out.append(text[at:start])
        at = end
    out.append(text[at:])
    return "".join(out)


def instance_shas_of(path, report_test_id, report_match, title_join) -> dict:
    """`{"instance_content_sha", "instance_code_sha", "scope"}` of ONE test of a file, or `{}` when it cannot be told. The
    file is the identity less the span of EVERY OTHER test (with the gap before it and a `;` after it, as FB-10 does for
    Python), so an edit of a neighbour changes nothing; the rest - a constant above the test, a `beforeEach`, a loop head -
    is part of it, and an edit there is "different" (the one error that is allowed). `instance_code_sha` is the same with the
    comments blanked and the whitespace folded; `scope` says `file_skeleton`: the helpers the file imports are not covered.
    A span that overlaps the test's own is never cut."""
    try:
        state = _load(path, Path(str(path)).name)
        if state["why_not"] or not state["language"]:
            return {}
        target = _find(state["declarations"], report_test_id, report_match, title_join)
        if target is None:
            return {}
        code = state["src"].code
        low, high = target["span"]
        cuts = []
        for other in state["declarations"]:
            start, end = other["span"]
            if other is target or (start < high and end > low):
                continue
            while start > 0 and code[start - 1].isspace():
                start -= 1
            if end < len(code) and code[end] == ";":
                end += 1
            cuts.append((start, end))
        merged = []
        for start, end in sorted(cuts):
            if merged and start <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], end))
            else:
                merged.append((start, end))
        raw = (b"\xef\xbb\xbf" if state["bom"] else b"") + _kept(state["text"], merged).encode("utf-8")
        folded = " ".join(_kept(code, merged).split())
        return {"instance_content_sha": hashlib.sha256(raw).hexdigest(),
                "instance_code_sha": hashlib.sha256(folded.encode("utf-8")).hexdigest(), "scope": SCOPE}
    except Exception:
        return {}
