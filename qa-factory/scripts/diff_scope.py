"""Did this change touch an executable line, or only what humans read?

The question a re-review turns on. On QA-EXAMPLE the code critic found that the tests
carried no marker tying them to the ticket, sent them back to the automator, and the fix — a
comment — went to a **fresh** critic dispatch that re-ran the rubric, the detectors, the
arch-check and the suite. The three proofs it had already taken were still valid: nothing
executable had changed. But "cosmetic" was a judgement nobody could check, so the expensive
answer won.

  diff_scope.py --file tests/test_x.py --since <sha>     comment-only | code
  diff_scope.py --file a.py --file b.py --since <sha> --json
  diff_scope.py --selftest

`--since` is any git revision the earlier review recorded (the critic writes the index hash
of the file it approved). Exit 0 and `comment-only` means every changed line is a comment, a
docstring line or blank — the earlier run still proves what it proved. Exit 0 and `code`
means a re-run is warranted. Anything this cannot classify counts as `code`: the safe
direction is the one that costs a run, not the one that ships an unproven test.
"""
import argparse
import ast
import difflib
import hashlib
import io
import json
import re
import subprocess
import sys
import tokenize
from pathlib import Path

LINE_COMMENT = ("#", "//", "--", ";", "%")
BLOCK_MARKS = ("/*", "*/", "*", '"""', "'''", "<!--", "-->")
STRING_ONLY = re.compile(r"""^(?:[rbuf]{0,2})(?:'''|\"\"\"|'|\")(.*)(?:'''|\"\"\"|'|\")\s*,?$""",
                         re.DOTALL)


# The factory's own case markers (`@pytest.mark.qa(...)`, `@pytest.mark.qa_unresolved(...)`) are
# cosmetic too (D-0019 item 3): they tie a test to its case, they change nothing it executes. Their
# shapes are the factory's closed variety and live in data, read by manifest_from_tests.py as well
# (one source, FR-13/FR-17). Any other decorator stays code.
MARKERS_FILE = Path(__file__).resolve().parents[1] / "references" / "case-markers.json"
_NOTHING = re.compile(r"(?!x)x")
_MARKER_HEAD = None


def marker_head():
    """The compiled head of a case-marker decorator line (`@pytest.mark.<name>` followed by `(`, a
    comment or the end of the line). An unreadable data file matches nothing: every decorator then
    counts as code - the safe direction."""
    global _MARKER_HEAD
    if _MARKER_HEAD is None:
        try:
            doc = json.loads(MARKERS_FILE.read_text(encoding="utf-8"))
            prefix = str(doc["decorator_prefix"])
            names = sorted({str(v) for v in doc["pytest"].values() if v}, key=len, reverse=True)
            _MARKER_HEAD = re.compile("^" + re.escape(prefix) + "(?:" + "|".join(re.escape(n) for n in names)
                                      + r")(?=\(|\s*$|\s*#)") if names else _NOTHING
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            _MARKER_HEAD = _NOTHING
    return _MARKER_HEAD


def _scan(text: str, depth: int, quote: str) -> tuple:
    """Walk `text` with the parenthesis depth and the open string quote carried in from the lines
    before: (depth, quote, index just past the `)` that brought the depth back to 0, or -1)."""
    i = 0
    while i < len(text):
        if quote:
            if text[i] == "\\":
                i += 2
                continue
            if text.startswith(quote, i):
                i += len(quote)
                quote = ""
                continue
            i += 1
            continue
        char = text[i]
        if char == "#":
            return depth, quote, -1
        if text.startswith(('"""', "'''"), i):
            quote, i = text[i:i + 3], i + 3
            continue
        if char in "\"'":
            quote, i = char, i + 1
            continue
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return depth, quote, i + 1
        i += 1
    return depth, quote, -1


def _one_line_marker(stripped: str) -> bool:
    """A case marker complete on this line, with nothing but a comment after it."""
    if not marker_head().match(stripped):
        return False
    depth, quote, end = _scan(stripped, 0, "")
    if end >= 0:
        return _blank_or_comment(stripped[end:])
    return depth == 0 and not quote          # a bare `@pytest.mark.qa`


def _blank_or_comment(rest: str) -> bool:
    rest = rest.strip()
    return not rest or rest.startswith("#")


def is_prose(line: str) -> bool:
    """True when this changed line cannot execute: blank, a comment, a bare string
    literal on a line of its own (a docstring's body, an annotation, a marker comment), or a
    factory case marker complete on the line (`case-markers.json`). A continuation line of a
    multi-line marker cannot be told from code on its own. This per-line reading is only the REPORT
    of deciding lines: nothing that gates a receipt or a reuse reads it (`executable_sha` does)."""
    s = line.strip()
    if not s:
        return True
    if s.startswith(LINE_COMMENT):
        return True
    if s.startswith(BLOCK_MARKS) or s.endswith(('"""', "'''")):
        return True
    if STRING_ONLY.match(s):
        return True
    if _one_line_marker(s):
        return True
    return False


def marker_names() -> set:
    """The dotted names of the factory's case markers (`pytest.mark.qa`, ...), from
    `case-markers.json`. An unreadable file gives none: every decorator then counts as code."""
    try:
        doc = json.loads(MARKERS_FILE.read_text(encoding="utf-8"))
        prefix = str(doc["decorator_prefix"]).lstrip("@")
        return {prefix + str(v) for v in doc["pytest"].values() if v}
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return set()


def _dotted(node) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        owner = _dotted(node.value)
        return owner + "." + node.attr if owner else ""
    return ""


def _is_marker(body: list, lines: list, names: set) -> bool:
    """Is this whole logical line (its tokens, INDENT/DEDENT/NEWLINE left out) exactly a factory
    case marker `@pytest.mark.<name>` or `@pytest.mark.<name>(<literals only>)`, nothing after it?
    Arguments that call or name code (`case=setup_db()`, `case=CASE`) make it code - the safe
    direction. What a string token holds never reaches here: marker-shaped text inside a docstring
    is one STRING token."""
    if not names or len(body) < 2 or body[0].type != tokenize.OP or body[0].string != "@":
        return False
    (srow, scol), (erow, ecol) = body[1].start, body[-1].end
    piece = lines[srow - 1:erow]
    if not piece:
        return False
    piece[-1] = piece[-1][:ecol]      # cut the end first: the columns are the original line's
    piece[0] = piece[0][scol:]
    try:
        node = ast.parse("(" + "\n".join(piece) + "\n)", mode="eval").body
    except (SyntaxError, ValueError):
        return False
    target = node.func if isinstance(node, ast.Call) else node
    if _dotted(target) not in names:
        return False
    if isinstance(node, ast.Call):
        for arg in list(node.args) + [kw.value for kw in node.keywords]:
            try:
                ast.literal_eval(arg)
            except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
                return False
        if any(kw.arg is None for kw in node.keywords):   # **kwargs
            return False
    return True


# token types that carry no text worth hashing: their presence is the structure
_BARE = {tokenize.NEWLINE, tokenize.DEDENT, tokenize.ENDMARKER}


def executable_tokens(text: str) -> list | None:
    """What can execute in Python source, as `(token type, text)` pairs, or None when it cannot be
    told (a tokenize error). Built from `tokenize`, never from lines (Amendment 5 of t-016, critic
    t-048: a per-line reading called `"alice",` in an assert's list, a URL argument on its own
    line, a `// 2` continuation and a `*base,` unpack "prose"):
      - COMMENT and NL tokens are dropped;
      - a LOGICAL line made only of STRING tokens is dropped - a real docstring or bare string
        statement; inside brackets there is no logical line of its own, so an argument string is
        code;
      - a logical line that is exactly a factory case marker (`case-markers.json`, literal
        arguments only, nothing after) is dropped;
      - every other token counts, INDENT/DEDENT included (indentation is code in Python).
    CRLF and LF are the same text; a trailing newline or not is the same code."""
    source = str(text).replace("\r\n", "\n").replace("\r", "\n")
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return None
    lines, names = source.split("\n"), marker_names()
    kept, logical = [], []

    def close():
        structure = [t for t in logical if t.type in (tokenize.INDENT, tokenize.DEDENT)]
        body = [t for t in logical if t.type not in (tokenize.INDENT, tokenize.DEDENT, tokenize.NEWLINE,
                                                     tokenize.ENDMARKER)]
        if body and (all(t.type == tokenize.STRING for t in body) or _is_marker(body, lines, names)):
            chosen = structure + [t for t in logical if t.type == tokenize.ENDMARKER]
        else:
            chosen = logical
        kept.extend((t.type, "" if t.type in _BARE else t.string) for t in chosen)

    for tok in tokens:
        if tok.type in (tokenize.COMMENT, tokenize.NL):
            continue
        logical.append(tok)
        if tok.type in (tokenize.NEWLINE, tokenize.ENDMARKER):
            close()
            logical = []
    if logical:
        close()
    return kept


def executable_sha(text: str, name: str = "") -> str:
    """sha256 of what can execute in Python source (`executable_tokens`); `""` - NO code sha, the
    raw rule only - when it cannot be told: a tokenize error, or a file `name` that is not `.py`.
    Two versions that differ only in comments, blank lines, docstrings and the factory's case
    markers hash the same; any other token changed, added, removed or re-indented makes them differ.

    ONE predicate for "cosmetic" (D-0017, "cosmetic is measured, not judged"): a receipt keeps its
    proof over a comment-only change of its test, and `classify_texts` / the CLI decide a file's
    scope by it. The per-line `is_prose` / `classify` only report the deciding lines."""
    if name and not str(name).lower().endswith(".py"):
        return ""
    tokens = executable_tokens(text)
    if tokens is None:
        return ""
    return hashlib.sha256(json.dumps(tokens, ensure_ascii=False).encode("utf-8")).hexdigest()


def changed_lines(diff_text: str) -> list:
    out = []
    for raw in diff_text.splitlines():
        if raw.startswith(("+++", "---", "diff --git", "index ", "@@", "new file", "deleted file",
                           "similarity", "rename ", "old mode", "new mode", "Binary files")):
            continue
        if raw.startswith(("+", "-")):
            out.append(raw[1:])
    return out


def classify(diff_text: str) -> tuple:
    """('comment-only' | 'code' | 'no-change', the lines that decided it)"""
    lines = changed_lines(diff_text)
    if not lines:
        return "no-change", []
    executable = [ln for ln in lines if not is_prose(ln)]
    if executable:
        return "code", executable[:5]
    return "comment-only", lines[:5]


def classify_texts(old: str, new: str, name: str = "") -> tuple:
    """('comment-only' | 'code' | 'no-change', the lines that decided it) for one file's two
    versions. The decision is `executable_sha(old) == executable_sha(new)`, both known - the one
    predicate; what cannot be classified (not `.py`, a tokenize error) is `code`. The lines are
    only the report (a line on its own cannot be judged: `"alice",` may be a list element)."""
    if old.splitlines() == new.splitlines():  # CRLF against LF is not a change
        return "no-change", []
    changed = changed_lines("\n".join(difflib.unified_diff(old.splitlines(), new.splitlines(),
                                                           lineterm="", n=0)))
    before, after = executable_sha(old, name), executable_sha(new, name)
    if before and after and before == after:
        return "comment-only", changed[:5]
    if not (before and after):
        return "code", [f"{name or 'the file'} cannot be classified (not Python source that tokenizes)"]
    return "code", ([ln for ln in changed if not is_prose(ln)] or changed)[:5]


def file_scope(since: str, file: str, cwd: Path) -> tuple:
    """(scope, deciding lines) of one file between `since` (git show <rev>:./<file>) and the file on
    disk now. What git cannot show, a file gone from disk, bytes that are not UTF-8: `code` - the
    safe direction."""
    shown = subprocess.run(["git", "show", f"{since}:./{Path(file).as_posix()}"], capture_output=True,
                           cwd=str(cwd), timeout=120)
    if shown.returncode != 0:
        why = (shown.stderr or b"").decode("utf-8", "replace").strip().splitlines()
        return "code", [f"git cannot show {since}:{file}" + (f" ({why[0]})" if why else "")]
    path = Path(cwd) / file
    if not path.is_file():
        return "code", [f"{file} is not on disk"]
    try:
        old, new = shown.stdout.decode("utf-8"), path.read_bytes().decode("utf-8")
    except UnicodeDecodeError:
        return "code", [f"{file}: not UTF-8, cannot be classified"]
    return classify_texts(old, new, Path(file).name)


def git_diff(since: str, files: list, cwd: Path) -> tuple:
    cmd = ["git", "diff", "--unified=0", since, "--", *files]
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", cwd=str(cwd), timeout=120)
    return p.returncode, p.stdout, (p.stderr or "").strip()


def selftest() -> int:
    failures: list = []

    def case(name, got, expected):
        if got != expected:
            failures.append(f"{name}: expected {expected!r}, got {got!r}")

    case("a blank line is prose", is_prose("   "), True)
    case("a python comment is prose", is_prose("    # TC-001"), True)
    case("a js comment is prose", is_prose("  // @case QA-1_TC_001"), True)
    case("a docstring fence is prose", is_prose('    """'), True)
    case("a docstring body is prose", is_prose('    "@case QA-1_TC_001"'), True)
    case("an assert is not prose", is_prose("    assert x == 1"), False)
    case("a decorator is not prose", is_prose("@pytest.mark.api"), False)
    case("a call is not prose", is_prose("    purge(name)"), False)
    case("a string ASSIGNMENT is not prose", is_prose('    name = "x"'), False)

    marker_only = (
        "diff --git a/tests/test_x.py b/tests/test_x.py\n"
        "index aaa..bbb 100644\n"
        "--- a/tests/test_x.py\n"
        "+++ b/tests/test_x.py\n"
        "@@ -4,0 +5,2 @@\n"
        '+    """@case QA-1_TC_001"""\n'
        "+\n"
    )
    case("a marker-only change is comment-only", classify(marker_only)[0], "comment-only")

    real = marker_only + "@@ -9,1 +11,1 @@\n-    assert x == 1\n+    assert x == 2\n"
    case("one changed assertion makes it code", classify(real)[0], "code")
    case("and the reason names the line", "assert x == 2" in " ".join(classify(real)[1]), True)
    case("an empty diff is no-change", classify("")[0], "no-change")

    mixed = (
        "diff --git a/a.ts b/a.ts\n@@ -1,0 +2,2 @@\n"
        "+// renamed for clarity\n+  const timeout = 5000\n"
    )
    case("a comment plus a constant is code", classify(mixed)[0], "code")

    # executable_sha: the same predicate over a whole file (a receipt's comment-only rule)
    base = 'import pytest\n\n\n@pytest.mark.api\ndef test_x():\n    """Check x."""\n    assert x == 1\n'
    same = executable_sha(base)
    case("a comment added is the same code",
         executable_sha(base.replace("def test_x", "# TC-001\ndef test_x")), same)
    case("a comment edited is the same code",
         executable_sha(base.replace("def", "# a\ndef")),
         executable_sha(base.replace("def", "# b\ndef")))
    commented = base.replace("    assert", "    # why this value\n    assert")
    case("a comment removed is the same code", executable_sha(base), executable_sha(commented))
    case("blank lines are the same code", executable_sha(base.replace("\n\n\n", "\n\n\n\n\n")), same)
    case("a docstring line is the same code",
         executable_sha(base.replace('"""Check x."""', '"""Check x, and why."""')), same)
    case("a string-only line is the same code",
         executable_sha(base.replace("    assert", '    "note"\n    assert')), same)
    case("an assert changed is other code", executable_sha(base.replace("== 1", "== 2")) != same, True)
    case("a decorator changed is other code",
         executable_sha(base.replace("mark.api", "mark.smoke")) != same, True)
    case("a code line re-indented is other code",
         executable_sha(base.replace("    assert", "        assert")) != same, True)
    case("CRLF against LF is the same code", executable_sha(base.replace("\n", "\r\n")), same)
    case("an empty file has a defined code sha, the one of a prose-only file",
         executable_sha(""), executable_sha("# only a comment\n\n"))

    # the factory's case markers (references/case-markers.json) are cosmetic; other decorators are code
    marked = base.replace("def test_x", '@pytest.mark.qa(case="TC-001", then=[1])\ndef test_x')
    case("a case marker added is the same code", executable_sha(marked), same)
    case("a case marker edited is the same code",
         executable_sha(marked.replace("then=[1]", "then=[1, 2]")), same)
    case("a skip added is other code",
         executable_sha(base.replace("def test_x", "@pytest.mark.skip\ndef test_x")) != same, True)
    multi = base.replace("def test_x", '@pytest.mark.qa_unresolved(\n    case="TC-002",\n'
                                       '    reason="impossible")\ndef test_x')
    case("a multi-line marker is the same code", executable_sha(multi), same)
    case("a continuation line edited is comment-only",
         classify_texts(multi, multi.replace('"impossible"', '"blocked-flow"'))[0], "comment-only")
    listed = 'def test_a(names):\n    assert names == [\n        "alice",\n    ]\n'
    case("a list element inside an assert is code (tokenize, not lines)",
         executable_sha(listed.replace("alice", "alicia")) != executable_sha(listed), True)
    case("what does not tokenize has no code sha", executable_sha("x = (\n"), "")
    case("code after the closing ')' is code",
         executable_sha(multi.replace('reason="impossible")', 'reason="impossible"); x = 1')) != same, True)

    if failures:
        print("DIFF_SCOPE SELFTEST: VIOLATIONS")
        for f in failures:
            print("  - " + f)
        return 1
    print("DIFF_SCOPE SELFTEST: no violations (prose detection, classification, mixed diffs, "
          "executable_sha, case markers)")
    return 0


def main() -> int:
    try:
        import console_io
        console_io.utf8_stdio()
    except ImportError:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", action="append", default=[], help="repeatable")
    ap.add_argument("--since", default="", help="a git revision the earlier review recorded")
    ap.add_argument("--cwd", default=".", help="repository to diff in (default: here)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        return selftest()
    if not args.file or not args.since:
        print("diff_scope.py: --file <path> (repeatable) and --since <rev> are required",
              file=sys.stderr)
        return 2
    # Each file is decided by ONE predicate - executable_sha of its bytes at --since against its
    # bytes now (a multi-line case marker edited only in a continuation line is comment-only, which
    # a per-line reading of the diff cannot see). What git cannot show counts as code.
    scopes, why = [], []
    for file in args.file:
        scope_one, lines = file_scope(args.since, file, Path(args.cwd))
        scopes.append(scope_one)
        why.extend(lines)
    scope = ("code" if "code" in scopes else "comment-only" if "comment-only" in scopes else "no-change")
    why = why[:5]
    if args.json:
        print(json.dumps({"scope": scope, "files": args.file, "since": args.since,
                          "deciding_lines": why}, indent=2))
        return 0
    print(scope)
    if scope == "code":
        print("executable lines changed:")
        for line in why:
            print("  " + line.rstrip())
        print("A re-run of these tests is warranted — the code changed.")
    elif scope == "comment-only":
        print("Only comments, docstrings and blank lines changed. An earlier green run and "
              "red probe still prove what they proved: confirm the fix was applied, do not "
              "re-prove the test.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
