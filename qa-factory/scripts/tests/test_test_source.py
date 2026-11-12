"""test_source.py: the ONE reader of a test file by the data of its language (EP1-37, p. 0).

What these pin: a declaration is read with its tags, its group chain and its template (the identity of a case is built from the
BARE title, the report id from the RAW one); a loop or an `each` makes a pattern, never invented rows; a template of fewer than
three literal characters is `unread`; a title that is not a literal is `unread` with its line; a language with no entry is
`language == ""` and a reason, never a raise and never a pass; CRLF and a BOM give the same lines; the identity of ONE test
(`instance_shas_of`) changes with everything above and around the test but not with a neighbour test, a blank line or a comment
(content_sha only); and the module imports in either order with `probe_by_code`.
"""
import hashlib
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness import check, check_eq, check_in, cleanup, finish, temp_dir  # noqa: E402

import test_source as TS  # noqa: E402

JOIN = " › "   # the data of the run form carries this; the test spells it once
BASE = """import { test, expect } from '@playwright/test';
const PRICE = 10;
test.describe('g', () => {
  test.beforeEach(async () => { await go(); });
  test('@api CART-1_TC_004 adds one', async () => {
    expect(PRICE).toBe(10);
  });
  // a comment above the next test
  test('CART-1_TC_005 adds two', async () => {
    expect(2).toBe(2);
  });
});
"""


def write(directory: Path, text: str, name: str = "a.spec.ts", crlf: bool = False, bom: bool = False) -> Path:
    path = directory / name
    data = text.replace("\n", "\r\n") if crlf else text
    path.write_bytes((b"\xef\xbb\xbf" if bom else b"") + data.encode("utf-8"))
    return path


def shas(path: Path, tail: str, match=None) -> dict:
    return TS.instance_shas_of(path, "a.spec.ts::" + tail, match, JOIN)


def one(directory: Path, text: str, tail: str) -> dict:
    return shas(write(directory, text), tail)


def reading(tmp: Path) -> None:
    got = TS.read_file(write(tmp, BASE), "tests/a.spec.ts")
    check_eq("language read from the entry", got["language"], "typescript")
    check_eq("no reason, nothing unread", (got["why_not"], got["unread"]), ("", []))
    first, second = got["declarations"]
    check_eq("title_path keeps the RAW title with its tag", first["title_path"], ["g", "@api CART-1_TC_004 adds one"])
    check_eq("bare_title has no tag (the id of a case is stable)", first["bare_title"], "CART-1_TC_004 adds one")
    check_eq("tags", first["tags"], ["@api"])
    check_eq("lines are the lines of the `test` token", (first["line"], second["line"]), (5, 9))
    check("a beforeEach is not a test", all("beforeEach" not in d["title"] for d in got["declarations"]))
    check("a plain test is not generated and has no pattern", not first["generated"] and first["pattern"] == "")
    check("body and span are inside the file", 0 < first["body"][0] < first["body"][1] < first["span"][1])
    for variant, label in ((dict(crlf=True), "CRLF"), (dict(bom=True), "BOM"), (dict(crlf=True, bom=True), "CRLF+BOM")):
        again = TS.read_file(write(tmp, BASE, **variant), "a.spec.ts")
        check_eq(f"{label}: the same lines", [(d["title"], d["line"]) for d in again["declarations"]],
                 [(d["title"], d["line"]) for d in got["declarations"]])


def shapes(tmp: Path) -> None:
    text = """
test.describe('g', () => {
  test.describe.configure({ mode: 'serial' });
  test.describe('inner', () => { test("CART-1_TC_006 nested", async () => { expect(1).toBe(1); }); });
});
for (const p of rows) {
  test(`CART-1_TC_007 loop [${p.id}]`, async () => { expect(p).toBeTruthy(); });
}
test.each(rows)('CART-1_TC_009 %s', async () => { expect(1).toBe(1); });
// test('x', () => { expect(1).toBe(1); });
const text = "test('y', () => { expect(1).toBe(1); })";
test.skip(true, 'a skip inside a test is no declaration');
test('it\\'s CART-1_TC_010', async () => { expect(1).toBe(1); });
"""
    got = TS.read_file(write(tmp, text), "a.spec.ts")
    by = {d["bare_title"]: d for d in got["declarations"]}
    check_eq("a nested describe is a chain, not a test", by["CART-1_TC_006 nested"]["title_path"], ["g", "inner", "CART-1_TC_006 nested"])
    loop = by["CART-1_TC_007 loop [${p.id}]"]
    check("a loop with a template: ONE row, generated, with a pattern",
          loop["generated"] and loop["pattern"] != "" and TS.pattern_matches(loop["pattern"], "CART-1_TC_007 loop [a]"))
    check("the pattern fits no other title", not TS.pattern_matches(loop["pattern"], "CART-1_TC_008 loop [a]"))
    each = by["CART-1_TC_009 %s"]
    check("each: generated, and its placeholder is a wildcard",
          each["generated"] and TS.pattern_matches(each["pattern"], "CART-1_TC_009 row one"))
    check_in("an escaped quote is unescaped", "it's CART-1_TC_010", by)
    check_eq("a comment, a string and a skip(cond) are no declaration", sorted(by),
             sorted(["CART-1_TC_006 nested", "CART-1_TC_007 loop [${p.id}]", "CART-1_TC_009 %s", "it's CART-1_TC_010"]))
    check_eq("nothing unread", got["unread"], [])
    check_eq("path pattern joins the group titles with the runner's join",
             TS.path_pattern(TS.read_file(write(tmp, "test.describe('g', () => { for (const p of r) { test(`CART-1_TC_007 [${p}]`, "
                                                    "async () => { expect(1).toBe(1); }); } });\n"), "a.spec.ts")["declarations"][0], JOIN)
             .count("g"), 1)
    names = TS.read_file(write(tmp, "test.describe('g', () => { for (const p of r) { test(`CART-1_TC_007 [${p}]`, "
                                    "async () => { expect(1).toBe(1); }); } });\n"), "a.spec.ts")["declarations"][0]
    check("the path pattern fits the whole report name", TS.pattern_matches(TS.path_pattern(names, JOIN), "g" + JOIN + "CART-1_TC_007 [x]"))
    # two equal titles in different groups: two declarations, different paths
    twin = TS.read_file(write(tmp, "test.describe('a', () => { test('CART-1_TC_011 x', async () => { expect(1).toBe(1); }); });\n"
                                   "test.describe('b', () => { test('CART-1_TC_011 x', async () => { expect(1).toBe(1); }); });\n"),
                        "a.spec.ts")
    check_eq("same title in two groups: two paths", [d["title_path"] for d in twin["declarations"]],
             [["a", "CART-1_TC_011 x"], ["b", "CART-1_TC_011 x"]])


def unread(tmp: Path) -> None:
    got = TS.read_file(write(tmp, "const name = 'x';\ntest(name, async () => { expect(1).toBe(1); });\n"), "a.spec.ts")
    check_eq("a title that is a variable is unread, with its line", [(u["line"]) for u in got["unread"]], [2])
    check_eq("and no declaration is invented for it", got["declarations"], [])
    cat = TS.read_file(write(tmp, "test('CART-1_TC_001 ' + suffix, async () => { expect(1).toBe(1); });\n"), "a.spec.ts")
    check("a concatenated title is unread, not cut at the quote", len(cat["unread"]) == 1 and cat["declarations"] == [])
    # AT and BEYOND: a template of only substitutions
    two = TS.read_file(write(tmp, "for (const p of r) { test(`${p}ab`, async () => { expect(1).toBe(1); }); }\n"), "a.spec.ts")
    three = TS.read_file(write(tmp, "for (const p of r) { test(`${p}abc`, async () => { expect(1).toBe(1); }); }\n"), "a.spec.ts")
    check("2 literal characters: unread (the pattern would bind every row)", len(two["unread"]) == 1 and not two["declarations"])
    check("3 literal characters: a declaration", len(three["declarations"]) == 1 and not three["unread"])
    conc = TS.read_file(write(tmp, "test('CART-1_TC_001 a', async () => expect(1).toBe(1));\n"), "a.spec.ts")
    check("a concise arrow has no block: unread with the lexer's words", len(conc["unread"]) == 1 and "no block opens" in conc["unread"][0]["why"])
    # E-3 (t-565): a group whose title is a template, or a `describe.each`, is a name no report group has: its tests are unread
    tpl = TS.read_file(write(tmp, "for (const b of bs) { test.describe(`on ${b}`, () => { test('TC_1 a', async () => { expect(1).toBe(1); }); }); }\n"),
                       "a.spec.ts")
    check_eq("E-3: a test in a templated group is unread, not a row that never binds", (tpl["declarations"], len(tpl["unread"])), ([], 1))
    check_in("E-3: ... and says it is the group", "group whose title", tpl["unread"][0]["why"])
    each = TS.read_file(write(tmp, "describe.each(rows)('g %s', () => { test('TC_1 a', async () => { expect(1).toBe(1); }); });\n"), "a.spec.ts")
    check_eq("E-3: a test in a describe.each is unread", (each["declarations"], len(each["unread"])), ([], 1))
    plain = TS.read_file(write(tmp, "test.describe('g', () => { test('TC_1 a', async () => { expect(1).toBe(1); }); });\n"), "a.spec.ts")
    check_eq("E-3 control: a plain group still binds", (len(plain["declarations"]), plain["unread"]), (1, []))
    # E-4: a member call and an in-body call are not a test the file failed to name
    member = TS.read_file(write(tmp, "const ok = /x/.test('abc');\ntest('TC_1 a', async () => { expect(/y/.test('abc')).toBe(true); });\n"), "a.spec.ts")
    check_eq("E-4: `/x/.test('abc')` at top level and in a body: no unread", (len(member["declarations"]), member["unread"]), (1, []))
    skip = TS.read_file(write(tmp, "test('TC_1 a', async () => { test.skip('x' === y, 'why'); expect(1).toBe(1); });\n"), "a.spec.ts")
    check_eq("E-4: `test.skip(cond, 'why')` inside a test: no unread, and the record has no offset",
             (len(skip["declarations"]), skip["unread"]), (1, []))
    check("E-4 control: an unread call outside any body keeps its record and has no `at`",
          all("at" not in u for u in conc["unread"]) and len(conc["unread"]) == 1)
    # E-8: an address in a title is not a tag
    mail = TS.read_file(write(tmp, "test('TC_1 send to user@example.com', async () => { expect(1).toBe(1); });\n"), "a.spec.ts")
    check_eq("E-8: user@example.com stays whole; no tag", (mail["declarations"][0]["bare_title"], mail["declarations"][0]["tags"]),
             ("TC_1 send to user@example.com", []))


def refusals_of_the_reader(tmp: Path) -> None:
    kt = TS.read_file(write(tmp, "class A\n", "A.kt"), "A.kt")
    check_eq("a language with no entry: language empty", kt["language"], "")
    check_eq("E-5: ... and `no_entry` says it is THAT case (a flag, not a phrase)", (kt["no_entry"], TS.read_file(tmp / "nope.spec.ts", "n.spec.ts")["no_entry"]), (True, False))
    check_in("and it says which suffix and where the row goes", "no entry for .kt in references/detectors.json assertion_probes", kt["why_not"])
    check_eq("no suffix", TS.read_file(write(tmp, "x\n", "Makefile"), "Makefile")["why_not"],
             "no entry for a file with no suffix in references/detectors.json assertion_probes")
    path = tmp / "bad.spec.ts"
    path.write_bytes(b"test('x', () => { \xff\xfe });\n")
    bad = TS.read_file(path, "bad.spec.ts")
    check("not UTF-8: a reason, the language is known, nothing guessed", bad["language"] == "typescript" and "not UTF-8" in bad["why_not"]
          and bad["declarations"] == [])
    nested = TS.read_file(write(tmp, "test(`a ${ `b ${c}` } d`, async () => { expect(1).toBe(1); });\nconst r = /can't/;\n"), "a.spec.ts")
    check("a text the lexer refuses: the lexer's reason, no declaration", nested["why_not"] != "" or nested["unread"] != [])
    empty = TS.read_file(write(tmp, ""), "a.spec.ts")
    check_eq("an empty file: no declaration, no reason, no raise", (empty["declarations"], empty["why_not"], empty["unread"]), ([], "", []))
    check_eq("a missing file never raises", TS.read_file(tmp / "nope.spec.ts", "nope.spec.ts")["language"], "typescript")
    check("a missing file has a reason", TS.read_file(tmp / "nope.spec.ts", "nope.spec.ts")["why_not"] != "")
    check("a directory never raises", TS.read_file(tmp, "x.spec.ts")["why_not"] != "")


def matching() -> None:
    check("equality for a plain declaration", TS.matches({"title": "a b", "pattern": ""}, "a b"))
    check("and not for another title", not TS.matches({"title": "a b", "pattern": ""}, "a c"))
    check("a pattern matches the whole title only", TS.pattern_matches("a.+", "ab") and not TS.pattern_matches("a.+", "xab"))
    check("a pattern that does not compile matches nothing", not TS.pattern_matches("a(", "a("))
    check("an empty pattern matches nothing", not TS.pattern_matches("", ""))


def identity(tmp: Path) -> None:
    base = one(tmp, BASE, "g › @api CART-1_TC_004 adds one")
    check("an identity is measured", bool(base) and base["scope"] == "file_skeleton")
    two = "g › @api CART-1_TC_004 adds one"
    pair = lambda text: TS.instance_shas_of(write(tmp, text), "a.spec.ts::" + two, None, JOIN)  # noqa: E731
    check_eq("a title with no match is no identity ({}), never a guess", one(tmp, BASE, "g › nope"), {})
    # the allowed error is "different": everything above and around the test
    check("a constant above the test changes both shas", pair(BASE.replace("PRICE = 10", "PRICE = 20"))["instance_code_sha"] != base["instance_code_sha"])
    check("a beforeEach changes both shas", pair(BASE.replace("await go()", "await go2()"))["instance_code_sha"] != base["instance_code_sha"])
    rows = BASE.replace("test.describe('g'", "const rows = [1, 2];\ntest.describe('g'")
    check("a table above the test changes the shas", pair(rows)["instance_code_sha"] != base["instance_code_sha"])
    check("the test's own body changes both shas", pair(BASE.replace("toBe(10)", "toBe(11)"))["instance_code_sha"] != base["instance_code_sha"])
    check("a group title changes the shas (the path is part of the test)", one(tmp, BASE.replace("'g'", "'h'"), "h › @api CART-1_TC_004 adds one")
          .get("instance_code_sha") != base["instance_code_sha"])
    # a neighbour test is nobody's business (as FB-10 does for Python)
    for label, text in (("edited", BASE.replace("toBe(2)", "toBe(3)")),
                        ("added", BASE.replace("  // a comment above the next test",
                                               "  test('CART-1_TC_006 new', async () => { expect(3).toBe(3); });\n  // a comment above the next test")),
                        ("removed with its comment", BASE.replace(
                            "  // a comment above the next test\n  test('CART-1_TC_005 adds two', async () => {\n    expect(2).toBe(2);\n  });\n", ""))):
        got = pair(text)
        check_eq(f"a neighbour test {label}: both shas are the same", (got["instance_content_sha"], got["instance_code_sha"]),
                 (base["instance_content_sha"], base["instance_code_sha"]))
    # a blank line or a comment above the test: the code is the same, the bytes are not
    shifted = pair("\n// a new comment\n" + BASE)
    check_eq("a blank line and a comment above: code_sha is the same", shifted["instance_code_sha"], base["instance_code_sha"])
    check("and content_sha is not", shifted["instance_content_sha"] != base["instance_content_sha"])
    check_eq("the line of the test moved, the declaration is still found (not by line)", bool(shifted), True)
    check_eq("CRLF: the code is the same", pair(BASE.replace("\n", "\r\n"))["instance_code_sha"], base["instance_code_sha"])
    # a helper outside the file is not covered, and the scope says so
    check_eq("scope says what is covered", base["scope"], "file_skeleton")
    # a template: by pattern, not by the raw text
    tpl = "for (const p of r) {\n  test(`CART-1_TC_007 loop [${p.id}]`, async () => { expect(p).toBeTruthy(); });\n}\n"
    declaration = TS.read_file(write(tmp, tpl), "a.spec.ts")["declarations"][0]
    match = {"pattern": TS.path_pattern(declaration, JOIN)}
    check("a templated test is found by its pattern", bool(TS.instance_shas_of(write(tmp, tpl), "a.spec.ts::x", match, JOIN)))
    check_eq("two tests with one pattern are no identity", TS.instance_shas_of(
        write(tmp, tpl + tpl), "a.spec.ts::x", match, JOIN), {})
    check_eq("a language with no entry is no identity", TS.instance_shas_of(write(tmp, "x", "A.kt"), "A.kt::x", None, JOIN), {})
    # the content sha is the sha of the bytes less the other tests: a one-test file has the file's own sha
    solo = "test('CART-1_TC_001 a', async () => { expect(1).toBe(1); });\n"
    got = TS.instance_shas_of(write(tmp, solo), "a.spec.ts::CART-1_TC_001 a", None, JOIN)
    check_eq("a file of one test: content_sha is the file's own", got["instance_content_sha"], hashlib.sha256(solo.encode()).hexdigest())


def import_order() -> None:
    scripts = str(Path(__file__).resolve().parents[1])
    for first, second in (("test_source", "probe_by_code"), ("probe_by_code", "test_source")):
        done = subprocess.run([sys.executable, "-B", "-c", f"import sys; sys.path.insert(0, {scripts!r}); import {first}; import {second}"],
                              capture_output=True, text=True)
        check(f"import {first} then {second} (separate processes): no cycle", done.returncode == 0, done.stderr[-300:])


def main() -> None:
    tmp = temp_dir()
    try:
        reading(tmp)
        shapes(tmp)
        unread(tmp)
        refusals_of_the_reader(tmp)
        matching()
        identity(tmp)
        import_order()
        no_language_in_the_module()
    finally:
        cleanup(tmp)
    finish("test_test_source")


def no_language_in_the_module() -> None:
    """AR-1: this module holds no word of any language; the data holds them (positive control: detectors.json)."""
    text = Path(TS.__file__).read_text(encoding="utf-8").lower()
    for word in (".ts", "playwright", "expect.soft", "\\u203a", "typescript"):
        check(f"AR-1: test_source.py has no `{word}` outside this one sentence", text.count(word) <= (1 if word == "typescript" else 0), word)
    data = (Path(TS.__file__).resolve().parents[1] / "references" / "detectors.json").read_text(encoding="utf-8")
    check("the control: the same words are found in detectors.json", ".ts" in data and "expect" in data)


if __name__ == "__main__":
    main()
