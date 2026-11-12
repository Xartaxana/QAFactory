"""variant_shape.py: the ONE judge of the shape of a variant of a test file (t-1508 R4, shared with R7).

The diagnostic run wants a pure removal of lines of the instance's function; the `reorder` round wants the same lines in
another order. The helper only describes (removed / added / moved / outside); a doubt reads as `outside` or as a change.
Mutants: a copy that does not count a changed line as removed+added dies in `changed_line`; one that ignores the function's
extent dies in `line_outside_the_function`; one that reads a swap as nothing dies in `reordered`.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness import check_eq, finish  # noqa: E402

import variant_shape as VS  # noqa: E402

SOURCE = '''\
import pytest

LIMIT = 4


def helper():
    return 1


def test_put(client):
    response = client.put("/project")
    assert response.status == 200
    assert response.body["name"] == "x"
    assert response.body["teams"] == []
    assert response.body["limit"] == LIMIT


def test_other():
    assert helper() == 1
'''
LINES = SOURCE.splitlines()


def variant(drop=(), add=None, swap=None):
    """SOURCE without the 1-based lines `drop`, with `add` {after line: text}, with lines `swap` (a, b) exchanged."""
    out = list(LINES)
    if swap:
        out[swap[0] - 1], out[swap[1] - 1] = out[swap[1] - 1], out[swap[0] - 1]
    for number in sorted(drop, reverse=True):
        del out[number - 1]
    for number, text in sorted((add or {}).items(), reverse=True):
        out.insert(number, text)
    return "\n".join(out) + "\n"


def removal() -> None:
    got = VS.variant_shape(SOURCE, variant(drop=[13]), "test_put")
    check_eq("removing the second assert: one removed line, with its original number and text",
             got["removed"], [{"line": 13, "text": '    assert response.body["name"] == "x"'}])
    check_eq("...nothing added, nothing moved, nothing outside, the function found",
             (got["added"], got["moved"], got["outside"], got["function_found"]), ([], False, False, True))
    two = VS.variant_shape(SOURCE, variant(drop=[13, 14]), "test_put")
    check_eq("two removed lines are both listed, in order", [r["line"] for r in two["removed"]], [13, 14])
    check_eq("...and still inside", two["outside"], False)
    last = VS.variant_shape(SOURCE, variant(drop=[15]), "test_put")
    check_eq("the last line of the function is inside it (the boundary AT the end)", (last["outside"], len(last["removed"])), (False, 1))


def addition() -> None:
    got = VS.variant_shape(SOURCE, variant(add={13: "    assert True"}), "test_put")
    check_eq("an added line: listed as added with its number in the variant, nothing removed",
             (got["added"], got["removed"]), ([{"line": 14, "text": "    assert True"}], []))
    check_eq("...inside the function", got["outside"], False)


def changed_line() -> None:
    edited = SOURCE.replace('== "x"', '== "y"')
    got = VS.variant_shape(SOURCE, edited, "test_put")
    check_eq("a changed line is one removed and one added, never a removal alone",
             (len(got["removed"]), len(got["added"])), (1, 1))
    check_eq("...at the same place", (got["removed"][0]["line"], got["added"][0]["line"]), (13, 13))


def reordered() -> None:
    got = VS.variant_shape(SOURCE, variant(swap=(13, 14)), "test_put")
    check_eq("two asserts exchanged: the same lines, nothing added or removed, moved", (got["removed"], got["added"], got["moved"]),
             ([], [], True))
    check_eq("...inside the function", got["outside"], False)
    same = VS.variant_shape(SOURCE, SOURCE, "test_put")
    check_eq("an identical variant moves nothing and removes nothing", (same["removed"], same["added"], same["moved"], same["outside"]),
             ([], [], False, False))
    both = VS.variant_shape(SOURCE, variant(drop=[12], swap=(13, 14)), "test_put")
    check_eq("a removal together with a swap is both: removed AND moved", (len(both["removed"]), both["moved"]), (1, True))
    duplicate = "def test_d():\n    assert a\n    assert b\n    assert a\n"
    first_gone = VS.variant_shape(duplicate, "def test_d():\n    assert b\n    assert a\n", "test_d")
    check_eq("removing the first of two equal lines is a removal, not a move", (len(first_gone["removed"]), first_gone["moved"]), (1, False))


def line_outside_the_function() -> None:
    before = VS.variant_shape(SOURCE, variant(drop=[3]), "test_put")
    check_eq("a line before the function is outside", before["outside"], True)
    declaration = VS.variant_shape(SOURCE, variant(drop=[10]), "test_put")
    check_eq("the declaration line itself is outside (removing it is not a removal of a Then)", declaration["outside"], True)
    after = VS.variant_shape(SOURCE, variant(drop=[19]), "test_put")
    check_eq("a line of the NEXT function is outside (BEYOND the end)", after["outside"], True)
    gap = VS.variant_shape(SOURCE, variant(add={15: "    assert x"}), "test_put")
    check_eq("an insertion right after the last line is outside", gap["outside"], True)
    mixed = VS.variant_shape(SOURCE, variant(drop=[13, 19]), "test_put")
    check_eq("one line inside and one outside: outside", mixed["outside"], True)
    # tail B2 (t-1564): an assert block moved past the LAST statement is a move inside the function, not a change outside it
    moved = SOURCE.replace('    assert response.status == 200\n', '').replace('    assert response.body["limit"] == LIMIT\n',
                                                                                 '    assert response.body["limit"] == LIMIT\n    assert response.status == 200\n')
    got = VS.variant_shape(SOURCE, moved, "test_put")
    check_eq("a line moved past the last statement is moved, inside, nothing added", (got["moved"], got["outside"], got["added"]), (True, False, []))
    new_end = VS.variant_shape(SOURCE, SOURCE.replace('LIMIT\n\n', 'LIMIT\n    assert brand_new\n\n', 1), "test_put")
    check_eq("...but a NEW line at the end is still outside (the proof is that the edit lifted the line from the body)", new_end["outside"], True)
    top_level = VS.variant_shape(SOURCE, SOURCE.replace('    assert response.status == 200\n', '').replace('LIMIT\n\n', 'LIMIT\nassert response.status == 200\n\n', 1), "test_put")
    check_eq("...and a lifted line set down at the declaration's own indentation is outside", top_level["outside"], True)


def function_not_found_and_empty() -> None:
    missing = VS.variant_shape(SOURCE, variant(drop=[13]), "test_nope")
    check_eq("a function that is not in the original: outside, not found", (missing["outside"], missing["function_found"]), (True, False))
    blank = VS.variant_shape(SOURCE, variant(drop=[13]), "")
    check_eq("an empty name finds nothing", (blank["outside"], blank["function_found"]), (True, False))
    empty = "def test_e():\n    pass\n\n\ndef test_f():\n    assert 1\n"
    got = VS.variant_shape(empty, empty.replace("    pass\n", ""), "test_e")
    check_eq("the only body line of a function is inside it", (got["outside"], len(got["removed"])), (False, 1))
    only = "def test_e():\n    pass\n"
    got = VS.variant_shape(only, "def test_e():\n", "test_e")
    check_eq("a function that loses its whole body is still a removal inside it", (got["outside"], len(got["removed"])), (False, 1))
    stub = VS.variant_shape("def test_s(): pass\n", "", "test_s")
    check_eq("a one-line function: its only line is the declaration, so removing it is outside", stub["outside"], True)
    check_eq("an empty text of both sides finds no function", VS.variant_shape("", "", "test_s")["function_found"], False)


def other_languages() -> None:
    js = ('describe("x", () => {\n  it("puts", async () => {\n    expect(a).toBe(1);\n    expect(b).toBe(2);\n  });\n\n'
          '  it("other", () => {\n    expect(c).toBe(3);\n  });\n});\n')
    got = VS.variant_shape(js, js.replace("    expect(b).toBe(2);\n", ""), "puts")
    check_eq("a braced test: a removed expect inside the block", (len(got["removed"]), got["outside"]), (1, False))
    out = VS.variant_shape(js, js.replace("    expect(c).toBe(3);\n", ""), "puts")
    check_eq("...and one of the next test is outside", out["outside"], True)
    cs = "[Fact]\npublic void Puts()\n{\n    Assert.Equal(1, a);\n    Assert.Equal(2, b);\n}\n"
    got = VS.variant_shape(cs, cs.replace("    Assert.Equal(2, b);\n", ""), "Puts")
    check_eq("a C#-shaped method: a removed assert inside the braces", (len(got["removed"]), got["outside"]), (1, False))
    multiline = "def test_m(\n    client,\n    other,\n):\n    assert 1\n    assert 2\n\n\ndef test_n():\n    assert 3\n"
    got = VS.variant_shape(multiline, multiline.replace("    assert 2\n", ""), "test_m")
    check_eq("a signature over several lines: the body is found after it", (len(got["removed"]), got["outside"]), (1, False))
    param = VS.variant_shape(multiline, multiline.replace("    other,\n", ""), "test_m")
    check_eq("a line of the signature is inside the declaration: refused as outside", param["outside"], True)


def main() -> None:
    removal()
    addition()
    changed_line()
    reordered()
    line_outside_the_function()
    function_not_found_and_empty()
    other_languages()
    finish("test_variant_shape")


if __name__ == "__main__":
    main()
