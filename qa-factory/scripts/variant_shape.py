"""The shape of a variant of a test file: which lines of ONE function were removed, added or moved.

`variant_shape(original_text, variant_text, function_name)` is the ONE helper that judges a variant
(AR-15). Two callers ask it for opposite shapes: the diagnostic run of `red_sandbox.py --diagnostic` wants a
variant that only REMOVES lines of the function (`removed` non-empty, `added` empty, nothing `moved`, nothing
`outside`), and the `reorder` round of S7 wants the same lines in another order (`moved` true, `added` and
`removed` empty, nothing `outside`). It only describes; each caller decides what it accepts, and a doubt is
always read as `outside` or as a change, so a caller that refuses on those words refuses on a doubt (FR-59,
FR-58: the verdict is about the shape of the edit, never about what the test asserts).

Result: `{"removed": [{"line": n, "text": t}], "added": [{"line": n, "text": t}], "moved": bool,
"outside": bool, "function_found": bool}`. `removed` are lines of the original that the variant lacks
(`line` is 1-based in the ORIGINAL), `added` are lines of the variant the original lacks (`line` is 1-based in
the VARIANT); lines are compared as text without their line ending, as a multiset, so a line that exists twice
and loses one copy is one removed line. `moved` is true when the lines both texts share are in another order.
`outside` is true when any change lies outside the function: before its declaration line, on it, or after its
last line; a function that cannot be found in the original is `outside` too (`function_found` false).

The function is located by its name alone, for any language: its declaration is the first line that carries the
name as a whole identifier (`def name(` in Python, `function name(`, `void name()`, `it("name"` ...). Its extent
is the indented block when the declaration (the signature may run over several lines) ends with a colon, the
braces `{ ... }` when it opens a brace, else the declaration line alone. Braces inside strings and comments are
counted like any other, so a function whose strings hold unbalanced braces reads wider or narrower than it is;
a narrower reading makes a real removal `outside` (a refusal, the safe side). No other file is read.
"""
import re
from collections import Counter
from difflib import SequenceMatcher


def _lines(text: str) -> list:
    return str(text or "").splitlines()


def _depth_change(line: str, opening: str, closing: str) -> int:
    return line.count(opening) - line.count(closing)


def function_span(lines: list, function_name: str):
    """(first, end, head) - the 0-based half-open range of the function's lines and the last line of its header, or None
    when it is not found.

    `first` is the declaration line, `head` the line where its signature ends (a body starts after it; a signature
    that runs over several lines is part of the declaration, not of the body). An empty name finds nothing."""
    name = str(function_name or "").strip()
    if not name:
        return None
    wanted = re.compile(r"(?<![\w$])" + re.escape(name) + r"(?![\w$])")
    declares = re.compile(r"\b(?:def|function|func|fn|void|public|private|protected|static|async|sub)\b|\b(?:it|test)\s*\(")
    first = next((i for i, line in enumerate(lines) if wanted.search(line) and declares.search(line)), None)
    if first is None:
        first = next((i for i, line in enumerate(lines) if wanted.search(line)), None)
    if first is None:
        return None
    indent = len(lines[first]) - len(lines[first].lstrip())
    # the signature: up to the line where its parentheses are balanced
    head, depth = first, 0
    while head < len(lines):
        depth += _depth_change(lines[head], "(", ")") + _depth_change(lines[head], "[", "]")
        if depth <= 0 or "{" in lines[head] or lines[head].rstrip().endswith(":"):    # balanced, or the body opens here
            break
        head += 1
    head = min(head, len(lines) - 1)
    signature = lines[head].rstrip()
    if signature.endswith(":"):                        # an indented block
        end = head + 1
        last_body = head
        while end < len(lines):
            line = lines[end]
            if line.strip():
                if len(line) - len(line.lstrip()) <= indent:
                    break
                last_body = end
            end += 1
        return first, last_body + 1, head
    after = next((k for k in range(head + 1, len(lines)) if lines[k].strip()), None)
    if "{" not in "".join(lines[first:head + 1]) and after is not None and lines[after].strip().startswith("{"):
        head = after                                   # the brace on a line of its own (C#, Java, C)
    if "{" in "".join(lines[first:head + 1]):          # a braced block
        depth, seen = 0, False
        for index in range(first, len(lines)):
            depth += _depth_change(lines[index], "{", "}")
            seen = seen or "{" in lines[index]
            if seen and depth <= 0:
                return first, index + 1, head
        return first, len(lines), head                       # never closed: up to the end, nothing beyond it is "outside"
    return first, head + 1, head


def _inside(span, start: int, stop: int, insertion: bool) -> bool:
    """Is the changed range [start, stop) of the original inside the function body (the declaration, signature included, is not)?"""
    _first, end, head = span
    if insertion:                                      # a gap before original line `start`
        return head < start < end
    return head < start and stop <= end


def _moved_to_end(span, original: list, variant: list, lifted: Counter, tag: str, start: int, first: int, stop: int) -> bool:
    """Lines of the function lifted from inside it and set down right AFTER its last statement (moving an assert block past the
    last statement) are a move inside the function, not a change outside it. The gap at `end` is the same place for them and for
    a NEW line (that one stays `outside`: an addition at the end is not a body change), so the proof is that every inserted line
    was taken out of the function's body by the same edit, and is indented deeper than the declaration (new top-level code is
    not). Invariant kept (FR-59, the safe side): a line the edit did not lift, a blank-only insertion, one at the declaration's
    indentation or less, and a braced or one-line function stay `outside`."""
    first_line, end, head = span
    if tag != "insert" or start != end or not original[head].rstrip().endswith(":"):
        return False
    body_indent = len(original[first_line]) - len(original[first_line].lstrip())
    added = [line for line in variant[first:stop] if line.strip()]
    return (bool(added) and all(len(line) - len(line.lstrip()) > body_indent for line in added)
            and not (Counter(added) - lifted))


def variant_shape(original_text: str, variant_text: str, function_name: str) -> dict:
    original, variant = _lines(original_text), _lines(variant_text)
    span = function_span(original, function_name)
    kept = Counter(original) & Counter(variant)
    surplus_original, surplus_variant = Counter(original) - kept, Counter(variant) - kept

    removed, taken = [], Counter()
    for number, text in enumerate(original, 1):
        if taken[text] < surplus_original[text]:
            taken[text] += 1
            removed.append({"line": number, "text": text})
    added, taken = [], Counter()
    for number, text in enumerate(variant, 1):
        if taken[text] < surplus_variant[text]:
            taken[text] += 1
            added.append({"line": number, "text": text})

    # the order of the lines both texts share: unchanged when one run of matching blocks accounts for all of them
    # (the matcher may undercount a long shuffle, which reads as `moved` - the safe direction)
    matched = sum(block.size for block in SequenceMatcher(None, original, variant, autojunk=False).get_matching_blocks())
    moved = matched < sum(kept.values())

    outside = span is None
    if span is not None:
        codes = [c for c in SequenceMatcher(None, original, variant, autojunk=False).get_opcodes() if c[0] != "equal"]
        lifted = Counter(line for tag, i1, i2, _j1, _j2 in codes if tag in ("delete", "replace")
                         and _inside(span, i1, i2, insertion=False) for line in original[i1:i2])
        for tag, i1, i2, j1, j2 in codes:
            if not _inside(span, i1, i2, insertion=(tag == "insert")) and not _moved_to_end(span, original, variant, lifted, tag, i1, j1, j2):
                outside = True
                break
    return {"removed": removed, "added": added, "moved": moved, "outside": outside,
            "function_found": span is not None}
