"""assertion_detectors.py: the ONE strict reader of `references/detectors.json` `assertion_probes` (B-373 R2).

What these pin: the shipped table reads; an unreadable file, an absent key and a malformed entry are three
DIFFERENT refusals and a malformed one names its field (and its row); every regex compiles and every rule of
R1 is validated; every `fires_as` matches the message of the inverted form it is for and none of the original
form's own red (the seed table's "must NOT match" column, as a test); `P` - the spec-only shorthand - is
expanded in the data; `assertion_heads` is the accessor the other readers use, and importing the module pulls
in no runtime of the probe. The messages are estimates (measurement M2 replaces them), kept in
fixtures/probe-languages/samples.json.
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness import FIXTURES, check, check_eq, check_in, check_not_in, cleanup, finish, temp_dir  # noqa: E402

import assertion_detectors as AD  # noqa: E402

SHIPPED = Path(AD.DETECTORS_FILE)
SAMPLES = json.loads((FIXTURES / "probe-languages" / "samples.json").read_text(encoding="utf-8"))["pairs"]
PY = sys.executable


def shipped_doc() -> dict:
    return json.loads(SHIPPED.read_text(encoding="utf-8"))


def pairs_of(doc: dict):
    """(language, form index, pair index, pair) of every pair of every form."""
    for language, entry in doc["assertion_probes"].items():
        for fi, form in enumerate(entry["assertions"]):
            for pi, pair in enumerate(form["invert"] or []):
                yield language, fi, pi, pair


def reading(directory: Path, doc, name: str = "d.json"):
    """What `assertion_detectors(path)` raises (the class) or returns, for `doc` written to `directory`."""
    path = directory / name
    path.write_text(doc if isinstance(doc, str) else json.dumps(doc), encoding="utf-8")
    try:
        return AD.assertion_detectors(path)
    except AD.DetectorsError as exc:
        return exc


def the_shipped_table(tmp: Path) -> None:
    doc = AD.assertion_detectors()
    check_eq("the shipped table: three languages", sorted(doc), ["csharp", "java", "typescript"])
    check_eq("csharp owns .cs", doc["csharp"]["suffixes"], [".cs"])
    check_eq("java owns .java", doc["java"]["suffixes"], [".java"])
    check_eq("typescript owns the eight JS/TS suffixes",
             doc["typescript"]["suffixes"], [".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".mts", ".cts"])
    # F1: a single-line string that crosses a line break is a lexer error - set on the quote strings of every entry
    for language, entry in doc.items():
        single = {s["open"]: s.get("multiline", True) for s in entry["lexer"]["strings"]}
        check_eq(f"F1: {language}: the `'` and `\"` strings are single-line", (single.get("'", None), single.get('"', None)),
                 (False, False) if "'" in single else (None, False))
    check_eq("F1: the verbatim, raw and template strings stay multi-line",
             [s.get("multiline", True) for e in doc.values() for s in e["lexer"]["strings"] if s["open"] in ('@"', '"""', "`")],
             [True, True, True, True])
    check_in("F1: csharp has a conditional_directive that matches #if/#else and not #region",
             "#", doc["csharp"]["conditional_directive"])
    rx = re.compile(doc["csharp"]["conditional_directive"], re.M)
    check("F1: ...it matches `#if NET6` and `  # else` at the start of a line, not `#region` or a `#if` mid-line",
          bool(rx.search("a\n#if NET6\n")) and bool(rx.search("  # else\n")) and not rx.search("#region x\n") and not rx.search("x #if y"))
    every = [s for entry in doc.values() for s in entry["suffixes"]]
    check("a suffix belongs to exactly one entry, and `.py` to none", len(every) == len(set(every)) and ".py" not in every)
    check_eq("schema_version stays 1", shipped_doc()["schema_version"], 1)
    check("the note is there (assertion_probes_note) and names the estimates", "ESTIMATE" in shipped_doc()["assertion_probes_note"])
    check_eq("the styles: method for C# and Java, call for TypeScript",
             [doc[k]["declaration_style"] for k in ("csharp", "java", "typescript")], ["method", "method", "call"])
    check_eq("compiled: true, true, false", [doc[k]["compiled"] for k in ("csharp", "java", "typescript")], [True, True, False])
    # the other families of the file are untouched (validate_artifacts reads only its own keys)
    for key in ("sleep", "dead_code", "plan_antipatterns"):
        check(f"the family `{key}` is still a list of strings", all(isinstance(x, str) for x in shipped_doc()[key]))
    # every regex of the table really compiles (the reader validated it; here by hand, as a control)
    for language, fi, pi, pair in pairs_of(shipped_doc()):
        for field in ("find", "fires_as"):
            try:
                re.compile(pair[field])
                ok = True
            except re.error:
                ok = False
            check(f"{language} form {fi} pair {pair.get('id')}: {field} compiles", ok)
    # L9: the Java frames carry a `qual` group; L1/L8: the TS grammar
    check_in("java: the frames regex names `qual`", "(?P<qual>", doc["java"]["frames"][0])
    check_eq("java resolves frames by basename", doc["java"]["frame_path"], "basename")
    skip = doc["typescript"]["skip_frames"][0]
    check_in("L1: the Jest frame `(<anonymous>)` is skipped only at the end of the line", "\\(<anonymous>\\)\\s*$", skip)
    check_not_in("L1: the bare `<anonymous>` alternative of the draft is gone", "|<anonymous>", skip.replace("\\(<anonymous>\\)", "").replace("at\\s+<anonymous>", ""))
    jest_frame = "      at Object.<anonymous> (/clone/src/sum.test.ts:11:20)"
    check("L1: a Jest test frame is NOT skipped", re.search(skip, jest_frame) is None)
    check("L1: ... and is read by the first TS frame regex",
          re.search(doc["typescript"]["frames"][0], jest_frame) is not None)
    check("L1: `at new Promise (<anonymous>)` IS skipped", re.search(skip, "      at new Promise (<anonymous>)") is not None)
    check("L1: a bare `at <anonymous>` line IS skipped", re.search(skip, "    at <anonymous>") is not None)
    vitest = " " + chr(0x276F) + " src/sum.test.ts:11:20"  # U+276F built by chr(): only ASCII in the file
    check("L8: a Vitest arrow frame is read by the second TS frame regex",
          re.search(doc["typescript"]["frames"][1], vitest) is not None)
    check_eq("L8: Vitest row names `Calc > adds` are a report separator", doc["typescript"]["report_separators"], [" > "])
    # L6: NUnit alternatives carry (?m); X3's NUnit alternative is scoped
    by_id = {pair["id"]: pair for _l, _f, _p, pair in pairs_of(shipped_doc())}
    for pid in ("N1", "N2", "N3", "N4"):
        check(f"L6: {pid} starts with (?m)", by_id[pid]["fires_as"].startswith("(?m)"), by_id[pid]["fires_as"])
    check_in("L6: X3's NUnit alternative is (?m:...)", "(?m:^\\s*Expected: False", by_id["X3"]["fires_as"])
    # L8: J1/J2 allow a user message; A2 allows `.as()`
    check_in("L8: J1 allows `msg ==> `", "(?:.*? ==> )?", by_id["J1"]["fires_as"])
    check_in("L8: J2 allows `msg ==> `", "(?:.*? ==> )?", by_id["J2"]["fires_as"])
    check_in("L8: A2 allows a bracketed description", "(?:\\[.*?\\]\\s*)?", by_id["A2"]["fires_as"])
    # `P` is a spec-only shorthand: expanded in the data, none left over
    expanded = "(?:org\\.opentest4j\\.AssertionFailedError: |java\\.lang\\.AssertionError: )?"
    for pid in ("J1", "J2", "J3", "J4", "J5", "J6"):
        text = by_id[pid]["fires_as"]
        check(f"{pid}: `P` is expanded (the shorthand's body is there)", text.startswith("^" + expanded), text)
        check(f"{pid}: and no literal `^P` is left in the data", re.search(r"\^P(?![A-Za-z]*\()", text.replace(expanded, "")) is None
              and "^P" not in text.replace("^" + expanded, ""), text)
    check("no `fires_as` anywhere starts with a literal P shorthand",
          not any(re.match(r"\^P[^\w(]|\^P[a-z]|\^P\(\?:\.", p["fires_as"]) for _l, _f, _p, p in pairs_of(shipped_doc())))


def three_distinct_refusals(tmp: Path) -> None:
    """K4: unreadable file / absent key / malformed entry are three different typed refusals (FR-41)."""
    gone = reading(tmp, "{}", "x.json")  # a real file with no key
    check_eq("an absent key is DetectorsKeyAbsent", (type(gone).__name__, getattr(gone, "kind", "")), ("DetectorsKeyAbsent", "absent"))
    check_in("...and says which key, and where the row goes", "`assertion_probes`", str(gone))
    check_in("...and shows the entry shape (the door)", "suffixes", str(gone))
    check_in("...and says it is the factory's data, not the test's", "not of the test", str(gone))
    try:
        AD.assertion_detectors(tmp / "no-such-file.json")
        got = None
    except AD.DetectorsError as exc:
        got = exc
    check_eq("an unreadable file is DetectorsUnreadable", (type(got).__name__, getattr(got, "kind", "")), ("DetectorsUnreadable", "unreadable"))
    check_in("...naming the file", "cannot be read", str(got))
    got = reading(tmp, "{not json", "bad.json")
    check_eq("a file that is not JSON is DetectorsUnreadable too", type(got).__name__, "DetectorsUnreadable")
    got = reading(tmp, ["a", "list"], "list.json")
    check_eq("a JSON file that is not an object is an absent key, not a crash", type(got).__name__, "DetectorsKeyAbsent")
    doc = shipped_doc()
    del doc["assertion_probes"]["csharp"]["frames"]
    got = reading(tmp, doc)
    check_eq("a malformed entry is DetectorEntryMalformed", (type(got).__name__, getattr(got, "kind", "")),
             ("DetectorEntryMalformed", "malformed"))
    check_eq("...naming the field", getattr(got, "field", ""), "assertion_probes.csharp.frames")
    check("the three are different classes",
          len({AD.DetectorsUnreadable, AD.DetectorsKeyAbsent, AD.DetectorEntryMalformed}) == 3
          and issubclass(AD.DetectorsUnreadable, AD.DetectorsError) and issubclass(AD.DetectorEntryMalformed, ValueError))
    doc = shipped_doc()
    doc["assertion_probes"] = {}
    check_eq("an empty table is malformed, not 'no entry'", type(reading(tmp, doc)).__name__, "DetectorEntryMalformed")
    doc["assertion_probes"] = ["x"]
    check_eq("a table that is not an object is malformed", type(reading(tmp, doc)).__name__, "DetectorEntryMalformed")


def malformed_entries(tmp: Path) -> None:
    """Every rule of R1/R2 refuses, naming the field; a row with an id names it too."""
    def corrupt(label: str, fn, field: str, hint: str = "", row: str = "") -> None:
        doc = shipped_doc()
        fn(doc["assertion_probes"])
        got = reading(tmp, doc)
        check_eq(f"{label}: malformed", type(got).__name__, "DetectorEntryMalformed")
        check_eq(f"{label}: names the field", getattr(got, "field", ""), field)
        if hint:
            check_in(f"{label}: says what is wrong", hint, str(got))
        if row:
            check_in(f"{label}: names the row", f"({row})", str(got))
        check_in(f"{label}: and that it is the factory's data", "factory's data", str(got))

    cs = lambda p: p["csharp"]  # noqa: E731
    for key in ("suffixes", "lexer", "declaration_style", "test_declaration", "body_open", "helper_declaration",
                "name_separators", "tail_join", "statement_end", "assertions", "frames", "skip_frames", "frame_path",
                "compiled", "builds_by_default", "no_rebuild_flags"):
        corrupt(f"missing {key}", lambda p, k=key: cs(p).pop(k), f"assertion_probes.csharp.{key}", "is missing")
    corrupt("an unknown field", lambda p: cs(p).update(frames_typo=1), "assertion_probes.csharp.frames_typo", "not a field")
    corrupt("an entry that is not an object", lambda p: p.update(csharp=[1]), "assertion_probes.csharp.", "must be an object")
    corrupt(".py as a suffix", lambda p: cs(p).update(suffixes=[".cs", ".py"]), "assertion_probes.csharp.suffixes", "Python")
    corrupt("a suffix with no dot", lambda p: cs(p).update(suffixes=["cs"]), "assertion_probes.csharp.suffixes", "like `.cs`")
    corrupt("a suffix listed twice", lambda p: cs(p).update(suffixes=[".cs", ".CS"]), "assertion_probes.csharp.suffixes", "twice")
    corrupt("a suffix of two entries", lambda p: p["java"].update(suffixes=[".java", ".cs"]),
            "assertion_probes.java.suffixes", "exactly one entry")
    corrupt("an empty suffix list", lambda p: cs(p).update(suffixes=[]), "assertion_probes.csharp.suffixes", "not empty")
    corrupt("a bad declaration_style", lambda p: cs(p).update(declaration_style="block"),
            "assertion_probes.csharp.declaration_style", "method, call")
    corrupt("test_declaration without {name}", lambda p: cs(p).update(test_declaration="void\\s+x\\s*\\("),
            "assertion_probes.csharp.test_declaration", "exactly one {name} (got 0)")
    corrupt("test_declaration with two {name}", lambda p: cs(p).update(test_declaration="{name}{name}"),
            "assertion_probes.csharp.test_declaration", "(got 2)")
    corrupt("helper_declaration that does not compile", lambda p: cs(p).update(helper_declaration="(void{name}"),
            "assertion_probes.csharp.helper_declaration", "does not compile")
    corrupt("body_open that does not compile", lambda p: cs(p).update(body_open="("), "assertion_probes.csharp.body_open",
            "does not compile")
    corrupt("an optional display_name that does not compile", lambda p: p["java"].update(display_name="@Display("),
            "assertion_probes.java.display_name", "does not compile")
    corrupt("an empty tail_join", lambda p: cs(p).update(tail_join=""), "assertion_probes.csharp.tail_join", "non-empty")
    corrupt("a bad statement_end", lambda p: cs(p).update(statement_end="newline"),
            "assertion_probes.csharp.statement_end", "semicolon")
    corrupt("compiled that is not a boolean", lambda p: cs(p).update(compiled="yes"), "assertion_probes.csharp.compiled",
            "true or false")
    corrupt("name_separators that is not a list of strings", lambda p: cs(p).update(name_separators="::"),
            "assertion_probes.csharp.name_separators", "list of non-empty strings")
    corrupt("builds_by_default with a non-string", lambda p: cs(p).update(builds_by_default=[1]),
            "assertion_probes.csharp.builds_by_default", "list of non-empty strings")
    corrupt("a bad frame_path", lambda p: cs(p).update(frame_path="glob"), "assertion_probes.csharp.frame_path", "path, basename")
    corrupt("no assertions", lambda p: cs(p).update(assertions=[]), "assertion_probes.csharp.assertions", "non-empty list")
    corrupt("a lexer that is not an object", lambda p: cs(p).update(lexer=[]), "assertion_probes.csharp.lexer", "must be an object")
    corrupt("a lexer with no strings", lambda p: cs(p)["lexer"].update(strings=[]), "assertion_probes.csharp.lexer.strings",
            "non-empty list")
    corrupt("a lexer string with a bad escape", lambda p: cs(p)["lexer"]["strings"][0].update(escape="caret"),
            "assertion_probes.csharp.lexer.strings[0].escape", "backslash, double, none")
    corrupt("a lexer string with an empty delimiter", lambda p: cs(p)["lexer"]["strings"][0].update(open=""),
            "assertion_probes.csharp.lexer.strings[0]", "non-empty delimiters")
    corrupt("block comments that are not pairs", lambda p: cs(p)["lexer"].update(block_comments=[["/*"]]),
            "assertion_probes.csharp.lexer.block_comments", "pairs")
    corrupt("an unknown lexer field", lambda p: cs(p)["lexer"].update(raw=1), "assertion_probes.csharp.lexer", "unknown")
    # forms and pairs
    corrupt("a form with no head", lambda p: cs(p)["assertions"][0].pop("head"), "assertion_probes.csharp.assertions[0]",
            "{head, matcher_at, invert}")
    corrupt("a head that does not compile", lambda p: cs(p)["assertions"][0].update(head="Assert("),
            "assertion_probes.csharp.assertions[0].head", "does not compile")
    corrupt("a bad matcher_at", lambda p: cs(p)["assertions"][0].update(matcher_at="tail"),
            "assertion_probes.csharp.assertions[0].matcher_at", "head, after_args, second_arg")
    corrupt("an invert that is an empty list", lambda p: cs(p)["assertions"][0].update(invert=[]),
            "assertion_probes.csharp.assertions[0].invert", "null (no inversion) or a non-empty list")
    corrupt("a find that does not compile", lambda p: cs(p)["assertions"][0]["invert"][0].update(find="^(Assert"),
            "assertion_probes.csharp.assertions[0].invert[0].find", "does not compile", "X1")
    corrupt("a fires_as that does not compile", lambda p: cs(p)["assertions"][0]["invert"][0].update(fires_as="[x"),
            "assertion_probes.csharp.assertions[0].invert[0].fires_as", "does not compile", "X1")
    corrupt("a replace naming a group `find` lacks", lambda p: cs(p)["assertions"][0]["invert"][0].update(replace="\\1x"),
            "assertion_probes.csharp.assertions[0].invert[0].replace", "names group 1", "X1")
    corrupt("a replace that is not a string", lambda p: cs(p)["assertions"][0]["invert"][0].update(replace=None),
            "assertion_probes.csharp.assertions[0].invert[0].replace", "must be a string", "X1")
    corrupt("a pair with an extra key", lambda p: cs(p)["assertions"][0]["invert"][0].update(why="x"),
            "assertion_probes.csharp.assertions[0].invert[0]", "nothing else", "X1")
    corrupt("a pair with no fires_as", lambda p: cs(p)["assertions"][0]["invert"][0].pop("fires_as"),
            "assertion_probes.csharp.assertions[0].invert[0]", "{find, replace, fires_as}", "X1")
    # frames
    corrupt("frames that is empty", lambda p: cs(p).update(frames=[]), "assertion_probes.csharp.frames", "non-empty")
    corrupt("frames with no `line` group", lambda p: cs(p).update(frames=["at (?P<path>.+)"]),
            "assertion_probes.csharp.frames[0]", "`path` and `line`")
    corrupt("frames that do not compile", lambda p: cs(p).update(frames=["(?P<path>"]), "assertion_probes.csharp.frames[0]",
            "does not compile")
    corrupt("a basename grammar without `qual`", lambda p: p["java"].update(
        frames=["^\\s*at\\s+x\\((?P<path>[\\w$]+\\.java):(?P<line>\\d+)\\)"]), "assertion_probes.java.frames[0]", "`qual`")
    corrupt("skip_frames that do not compile", lambda p: cs(p).update(skip_frames=["(x"]),
            "assertion_probes.csharp.skip_frames[0]", "does not compile")
    corrupt("skip_frames that is a number", lambda p: cs(p).update(skip_frames=5), "assertion_probes.csharp.skip_frames",
            "regex or a list")
    # L7: a call-style row must be anchored
    def unanchor(p):
        p["typescript"]["assertions"][0]["invert"][0]["fires_as"] = "expect\\(received\\)\\.to|^Error: x"
    corrupt("L7: a TS alternative without a leading ^", unanchor,
            "assertion_probes.typescript.assertions[0].invert[0].fires_as", "start with `^`", "T1")
    def flagged(p):
        p["typescript"]["assertions"][0]["invert"][0]["fires_as"] = "(?s)^a|b"
    corrupt("L7: the second alternative of (?s)^a|b is not anchored", flagged,
            "assertion_probes.typescript.assertions[0].invert[0].fires_as", "start with `^`", "T1")
    # F3: a global `m` flag makes `^` match at every line - the very echo L7 keeps out - so it is not an anchor
    for flagged in ("(?m)^a|^b", "(?ms)^a|^b", "(?im)^a"):
        def multiline_flag(p, text=flagged):
            p["typescript"]["assertions"][0]["invert"][0]["fires_as"] = text
        corrupt(f"F3: a call-style row with the global flags {flagged[:5]}", multiline_flag,
                "assertion_probes.typescript.assertions[0].invert[0].fires_as", "start with `^`", "T1")
    # F1 (data): the new lexer and entry keys are validated
    corrupt("F1: a lexer string whose `multiline` is not a boolean", lambda p: cs(p)["lexer"]["strings"][2].update(multiline="no"),
            "assertion_probes.csharp.lexer.strings[2].multiline", "true or false")
    # F1b: the optional regex-literal spec of a lexer is validated
    ts = lambda p: p["typescript"]["lexer"]["regex_literal"]  # noqa: E731
    corrupt("F1b: a regex_literal that is not an object", lambda p: p["typescript"]["lexer"].update(regex_literal="/"),
            "assertion_probes.typescript.lexer.regex_literal", "must be {open")
    corrupt("F1b: a regex_literal missing `after`", lambda p: ts(p).pop("after"), "assertion_probes.typescript.lexer.regex_literal", "after")
    corrupt("F1b: a regex_literal with an unknown key", lambda p: ts(p).update(flags="g"), "assertion_probes.typescript.lexer.regex_literal",
            "must be {open")
    for key in ("open", "close", "escape", "class_open", "class_close"):
        corrupt(f"F1b: a regex_literal `{key}` of two characters", lambda p, k=key: ts(p).update({k: "//"}),
                f"assertion_probes.typescript.lexer.regex_literal.{key}", "exactly one character")
    corrupt("F1b: a regex_literal `multiline` that is not a boolean", lambda p: ts(p).update(multiline="no"),
            "assertion_probes.typescript.lexer.regex_literal.multiline", "true or false")
    corrupt("F1b: an `after` set that is empty", lambda p: ts(p).update(after={"chars": "", "words": []}),
            "assertion_probes.typescript.lexer.regex_literal.after", "not both empty")
    corrupt("F1b: an `after` with a non-string word", lambda p: ts(p).update(after={"chars": "(", "words": [1]}),
            "assertion_probes.typescript.lexer.regex_literal.after", "chars")
    doc = shipped_doc()
    del doc["assertion_probes"]["typescript"]["lexer"]["regex_literal"]
    check_eq("F1b: the regex_literal is optional (Java and C# have none)", type(reading(tmp, doc)).__name__, "dict")
    shipped = AD.assertion_detectors()
    check_eq("F1b: only the typescript entry has a regex_literal", {k: "regex_literal" in e["lexer"] for k, e in shipped.items()},
             {"csharp": False, "java": False, "typescript": True})
    spec = shipped["typescript"]["lexer"]["regex_literal"]
    check_eq("F1b: the shipped spec: `/`, escape `\\`, class [ ], single-line", (spec["open"], spec["close"], spec["escape"],
                                                                                spec["class_open"], spec["class_close"], spec["multiline"]),
             ("/", "/", "\\", "[", "]", False))
    check_eq("F1b: the shipped `after` chars are the operator and punctuation set",
             sorted(spec["after"]["chars"]), sorted("(,=:[!&|?{};+-*%<>~^"))
    check_eq("F1b: ...and the words", sorted(spec["after"]["words"]),
             sorted("return typeof instanceof in of new delete void throw case do else yield await".split()))
    check_eq("F1b: entry_for_suffix takes the table by that name", AD.entry_for_suffix(table=shipped, suffix=".cs")[0], "csharp")
    corrupt("F1: a conditional_directive that does not compile", lambda p: cs(p).update(conditional_directive="(#if"),
            "assertion_probes.csharp.conditional_directive", "does not compile")
    doc = shipped_doc()
    doc["assertion_probes"]["csharp"]["assertions"][0]["invert"][0]["fires_as"] = "Assert\\.NotEqual"  # method style: no anchor demanded
    check_eq("an unanchored fires_as is legal for a method-style entry", type(reading(tmp, doc)).__name__, "dict")
    doc = shipped_doc()
    doc["assertion_probes"]["typescript"]["frames"] = doc["assertion_probes"]["typescript"]["frames"][0]  # one regex as a string
    check_eq("frames as one regex string is legal", type(reading(tmp, doc)).__name__, "dict")
    doc = shipped_doc()
    del doc["assertion_probes"]["typescript"]["helper_body_open"]
    del doc["assertion_probes"]["typescript"]["report_separators"]
    check_eq("the optional fields may be absent", type(reading(tmp, doc)).__name__, "dict")
    # EP1-38: `soft_assert_patterns`, the optional list of forms that record a failure and let the test go on
    check_eq("EP1-38 / t-2064 P1: the shipped typescript entry names its soft form as data, the others STATE they have none (`[]`)",
             (shipped["typescript"].get("soft_assert_patterns"), shipped["csharp"].get("soft_assert_patterns"),
              AD.soft_patterns(shipped["typescript"]), AD.soft_patterns(shipped["java"])),
             (["\\bexpect\\.soft\\s*\\("], [], ["\\bexpect\\.soft\\s*\\("], []))
    check_eq("t-2064 P1: a stated `[]` is legal data for the loader", type(reading(tmp, {"assertion_probes": {"java": dict(
        shipped_doc()["assertion_probes"]["java"], soft_assert_patterns=[])}})).__name__, "dict")
    check_eq("EP1-38: a copy of the entry without the key is legal (the key is optional)",
             type(reading(tmp, {"assertion_probes": {"typescript": {k: v for k, v in shipped_doc()["assertion_probes"]["typescript"].items()
                                                                     if k != "soft_assert_patterns"}}})).__name__, "dict")
    corrupt("EP1-38: soft_assert_patterns that is not a list", lambda p: p["typescript"].update(soft_assert_patterns="expect"),
            "assertion_probes.typescript.soft_assert_patterns", "list of non-empty strings")
    corrupt("EP1-38: a soft_assert_patterns regex that does not compile",
            lambda p: p["typescript"].update(soft_assert_patterns=["(expect"]),
            "assertion_probes.typescript.soft_assert_patterns[0]", "does not compile")


def fires_as_against_the_samples() -> None:
    """R2 / the seed table: every `fires_as` matches the message of ITS inverted form and none of the original
    form's own red, read by `AD.fires_in` (`re.search`, no flags, on the whole text and on each line - L7). A pair with
    no sample, or a sample for no pair, is a defect of this test's data."""
    table = list(pairs_of(shipped_doc()))
    ids = [pair["id"] for _l, _f, _p, pair in table]
    check_eq("every pair has an id", len(ids), len(set(ids)))
    check_eq("every pair has samples, and every sample belongs to a pair", sorted(ids), sorted(SAMPLES))
    for language, _fi, _pi, pair in table:
        sample = SAMPLES[pair["id"]]
        for text in sample["fires"]:
            check(f"{pair['id']}: fires_as matches its own inverted form's message {text[:40]!r}",
                  AD.fires_in(pair["fires_as"], text), pair["fires_as"])
        for text in sample["not"]:
            check(f"{pair['id']}: fires_as does NOT match the original form's red {text[:40]!r}",
                  not AD.fires_in(pair["fires_as"], text), pair["fires_as"])
        check(f"{pair['id']}: an empty message matches nothing", not AD.fires_in(pair["fires_as"], ""))
    # L7: no flags are added - `^` means the start of the text or of a line; a code frame echo is kept out by its
    # `> 11 |` prefix (the line does not start with the head), not by the anchor
    t1 = next(p for _l, _f, _p, p in table if p["id"] == "T1")
    echo = "Error: boom\n  > 11 |   expect(received).toBe(expected)\n"
    check("L7: a code frame echo line does not fire (its prefix, not the anchor, keeps it out)", not AD.fires_in(t1["fires_as"], echo))
    check("L7: the same statement on a line of its own DOES fire by line",
          AD.fires_in(t1["fires_as"], "boom\n  expect(received).toBe(expected)\n"))
    check("L7: ...and by the whole text only it does not (by_line=False is the whole text)",
          not AD.fires_in(t1["fires_as"], "boom\n  expect(received).toBe(expected)\n", by_line=False))
    check("L7: whole-text first line fires with by_line=False too",
          AD.fires_in(t1["fires_as"], "expect(received).toBe(expected)\n  > 11 |   x", by_line=False))
    check("a pattern that cannot compile never matches (a gap is not a verdict)", not AD.fires_matches("(", "x"))


def t_1953_locator_with_an_author_message() -> None:
    """t-1953 N6: a Playwright locator/page/response assertion carrying the author's message (`expect(x, 'msg')`) prints
    `Error: <msg>` on its own line and the library's `expect(locator).not.toBeDisabled() failed` UNPREFIXED on the next one,
    so the `Error: ` before the locator alternative of T1/T2 is optional. The two real reports are text copied from the
    arm B probe runs of MyBooks LOCAL-1 (TC_001 in-stock, TC_002 out-of-stock); the prefixed forms stay green."""
    rows = {p["id"]: p["fires_as"] for _l, _f, _p, p in pairs_of(shipped_doc())}
    t1, t2 = rows["T1"], rows["T2"]
    folder = FIXTURES / "playwright-locator-author-message"
    for name, line in (("tc001-in-stock.failure.txt", "expect(locator).not.toHaveCount(expected) failed"),
                       ("tc002-out-of-stock.failure.txt", "expect(locator).not.toBeDisabled() failed")):
        text = (folder / name).read_text(encoding="utf-8")
        check_in(f"{name}: the real report has the author's message line first and the library line unprefixed", line, text)
        check(f"{name}: the library line has no `Error: ` before it", ("Error: " + line) not in text)
        check(f"{name}: T2 (the inverted form of `.to...`) FIRES on the real report", AD.fires_in(t2, text), t2)
        check(f"{name}: T1 (the inverted form of `.not.to...`) does NOT fire on it (the direction)", not AD.fires_in(t1, text), t1)
        check(f"{name}: the code frame echo alone does not fire", not AD.fires_in(
            t2, "\n".join(x for x in text.splitlines() if x.lstrip().startswith((">", "|"))) + "\n"))
        check(f"{name}: the whole-text reading (the author's own message) does not fire", not AD.fires_in(t2, text, by_line=False))
    # the mirror, real unprefixed lines of other arm B reports: T1 fires on the non-`.not.` form, T2 does not
    for text in ("Error: Then 1: the badge shows 1\n\n    expect(locator).toBeVisible() failed\n\n    Locator: x\n",
                 "Error: ok\n\n    expect(page).toHaveURL(expected) failed\n"):
        check(f"mirror {text[-40:]!r}: T1 fires", AD.fires_in(t1, text))
        check(f"mirror {text[-40:]!r}: T2 does not", not AD.fires_in(t2, text))
    check("a `.not.` page report fires T2 only", AD.fires_in(t2, "    expect(page).not.toHaveURL(expected) failed\n")
          and not AD.fires_in(t1, "    expect(page).not.toHaveURL(expected) failed\n"))
    # both worlds: the prefixed forms (no author message) still fire
    for text, row in (("Error: expect(locator).not.toBeEnabled() failed\n", t2), ("Error: expect(locator).not.toBeVisible() failed\n", t2),
                      ("Error: Timed out 5000ms waiting for expect(locator).not.toBeVisible()\n", t2),
                      ("Error: expect(locator).toBeVisible() failed\n", t1),
                      ("Timed out 5000ms waiting for expect(locator).toBeVisible() failed\n", t1)):
        check(f"both worlds: {text.strip()[:60]!r} fires", AD.fires_in(row, text))
    # NEGATIVE controls: a quotation, an unrelated error, no report, an author message alone
    for label, text in (("an author message that quotes the locator form", "Error: see expect(locator).not.toBeDisabled() failed\n"),
                        ("a log line quoting it mid-line", "      - Then 4: waits, expect(locator).not.toBeDisabled() failed\n"),
                        ("the mutated statement itself, `expect(page).not.toHaveTitle('x');` (the probe's echo guard, A2)",
                         "expect(page).not.toHaveTitle('x');\n"),
                        ("the mutated statement itself, `expect(locator).toBeVisible();` (the same guard)",
                         "expect(locator).toBeVisible();\n"),
                        ("a code frame echo","    > 104 |     await expect(detail.addButton, 'x').not.toBeDisabled();\n"),
                        ("an unrelated Error line", "Error: something\n"),
                        ("an unrelated Error line naming a locator", "Error: locator.click: Timeout 10000ms exceeded\n"),
                        ("the author-message line alone", "Error: Then 4: Add is disabled on B\n"),
                        ("an empty report", ""), ("a blank report", "\n   \n")):
        check(f"negative: {label} fires neither T1 nor T2", not AD.fires_in(t1, text) and not AD.fires_in(t2, text), repr(text))


def the_helpers() -> None:
    check_eq("top-level alternatives respect groups, classes and escapes",
             AD.top_level_alternatives("a|(b|c)|[|]|d\\|e"), ["a", "(b|c)", "[|]", "d\\|e"])
    check("anchored: every alternative starts with ^", AD.anchored("^a|^b"))
    check("anchored: a global flags group is skipped", AD.anchored("(?s)^a|^b"))
    check("anchored: one bare alternative fails", not AD.anchored("^a|b"))
    check("F3: a global m flag is not an anchor, whatever the alternatives", not any(
        AD.anchored(p) for p in ("(?m)^x|^y", "(?ms)^x|^y", "(?mi)^x")))
    check("F3 control: other global flags keep the anchor", AD.anchored("(?s)^x|^y") and AD.anchored("(?i)^x"))
    check("F3 control: a scoped (?m:...) group inside an anchored alternative is not a global flag",
          AD.anchored("^(?m:a|b)"))
    check("anchored: a group's own bar is not an alternative", AD.anchored("^(?:a|b)c"))
    doc = AD.assertion_detectors()
    check_eq("entry_for_suffix: .cs", AD.entry_for_suffix(doc, ".cs")[0], "csharp")
    check_eq("entry_for_suffix: case-insensitive", AD.entry_for_suffix(doc, ".TSX")[0], "typescript")
    check_eq("entry_for_suffix: .py has none", AD.entry_for_suffix(doc, ".py"), (None, None))
    check_eq("entry_for_suffix: no suffix has none", AD.entry_for_suffix(doc, ""), (None, None))
    check_eq("entry_for_suffix: .kt has none", AD.entry_for_suffix(doc, ".kt"), (None, None))
    frames, skip, how = AD.grammar_of(doc["typescript"])
    frames.append("mutated by the caller")
    check_eq("grammar_of hands out a fresh list (the table cannot be changed through it)",
             len(AD.grammar_of(doc["typescript"])[0]), 2)
    check_eq("grammar_of: the path mode", how, "path")
    one = dict(doc["csharp"], frames="^(?P<path>x):(?P<line>1)$")
    check_eq("grammar_of: a single regex string is one pattern, not a list of letters", len(AD.grammar_of(one)[0]), 1)
    rx = AD.declaration_regex(doc["csharp"], "A.b(c)")
    check("declaration_regex: the name is escaped (regex syntax in a name is literal)",
          rx.search("public void A.b(c) (") is not None and rx.search("public void AXb(c) (") is None)
    rx = AD.declaration_regex(doc["typescript"], "adds two numbers")
    check("declaration_regex: a TS title with spaces matches its own quote kinds",
          all(rx.search(f"test({q}adds two numbers{q}, () => {{") for q in ("'", '"', "`")))
    check("declaration_regex: and not another title", rx.search("test('adds', () => {") is None)
    heads = AD.assertion_heads(doc)
    check("assertion_heads: a list of strings", isinstance(heads, list) and all(isinstance(h, str) for h in heads))
    check_in("assertion_heads: carries the TS expect head", "\\bexpect(?:\\.soft)?\\s*\\(", heads)
    check_in("assertion_heads: carries the xUnit head", "\\bAssert\\.Equal\\b", heads)
    check_eq("assertion_heads: no repeats", len(heads), len(set(heads)))
    check_eq("assertion_heads: the same with no argument", AD.assertion_heads(), heads)
    check_eq("assertion_heads: the parameter is the validated `table`", AD.assertion_heads(table=doc), heads)
    # F6: B-407's reader takes the RAW detectors.json document; handing it here is a named refusal, not a crash
    for label, wrong in (("the raw detectors.json document", shipped_doc()), ("a list", ["x"]), ("an entry that is no object", {"csharp": 1}),
                         ("an entry with no assertions", {"csharp": {"suffixes": [".cs"]}})):
        try:
            AD.assertion_heads(wrong)
            got = None
        except ValueError as exc:
            got = str(exc)
        except Exception as exc:  # a crash is what F6 forbids
            got = "CRASH " + type(exc).__name__
        check(f"F6: {label} is a ValueError that names the expected shape",
              bool(got) and not got.startswith("CRASH") and "validated table" in got and "assertion_detectors()" in got, str(got))
    try:
        AD.assertion_heads(shipped_doc())
    except ValueError as exc:
        check_in("F6: the refusal says the raw document is the one that holds the key", "`assertion_probes`", str(exc))
    check_eq("F6: an empty table is a table with no heads", AD.assertion_heads({}), [])
    check_eq("assertion_heads: one per assertion form, in table order",
             heads, [f["head"] for entry in doc.values() for f in entry["assertions"]])


def the_path_and_the_environment(tmp: Path) -> None:
    broken = tmp / "broken.json"
    broken.write_text("{}", encoding="utf-8")
    saved = os.environ.get(AD.ENV_FILE)
    os.environ[AD.ENV_FILE] = str(broken)
    try:
        try:
            AD.assertion_detectors()
            got = None
        except AD.DetectorsKeyAbsent as exc:
            got = exc
        check("the environment variable points the reader at another file", got is not None)
        check_eq("a path given as an argument wins over it", sorted(AD.assertion_detectors(SHIPPED)), ["csharp", "java", "typescript"])
    finally:
        if saved is None:
            os.environ.pop(AD.ENV_FILE, None)
        else:
            os.environ[AD.ENV_FILE] = saved
    check_eq("without it the shipped file is read", AD.detectors_path(), SHIPPED)


def one_reader_no_runtime() -> None:
    """L10: a small stdlib module; importing it pulls in no runtime of probe_by_code, red_sandbox or
    validate_artifacts (B-407 imports it from validate_artifacts: a cycle would break the gate)."""
    code = ("import sys; sys.path.insert(0, %r); import assertion_detectors; "
            "print(sorted(m for m in ('probe_by_code', 'red_sandbox', 'validate_artifacts', 'reporters', 'contract') "
            "if m in sys.modules))" % str(Path(AD.__file__).parent))
    proc = subprocess.run([PY, "-B", "-c", code], capture_output=True, text=True, timeout=60,
                          env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
    check_eq("importing assertion_detectors imports none of the probe's runtimes", proc.stdout.strip(), "[]")
    source = Path(AD.__file__).read_text(encoding="utf-8")
    imports = re.findall(r"^(?:import|from)\s+(\w+)", source, re.M)
    check_eq("its imports are the standard library's",
             sorted(set(imports)), ["json", "os", "pathlib", "re"])
    # FR-17: nobody else parses the table's key - the probe and the sandbox read it through this module
    scripts = Path(AD.__file__).parent
    readers = sorted(p.name for p in scripts.glob("*.py") if p.name != "assertion_detectors.py"
                     and "assertion_probes" in p.read_text(encoding="utf-8")
                     and ('["assertion_probes"]' in p.read_text(encoding="utf-8")
                          or ".get(\"assertion_probes\")" in p.read_text(encoding="utf-8")))
    check_eq("no second reader of the key `assertion_probes` in the package's scripts", readers, [])


def ep1_37_the_reading_fields(tmp: Path) -> None:
    """EP1-37: the optional fields `test_source.read_file` reads a file by are validated like the rest: the shipped entry of the
    call-style language carries all six, a field that is there and broken is a gap of the data (malformed, naming the field), and
    an entry without them reads as before (no field is required)."""
    doc = shipped_doc()
    entry = doc["assertion_probes"]["typescript"]
    for field in ("title_tag", "title_template", "title_placeholders", "group_declaration", "each_declaration", "loop_heads"):
        check(f"the shipped call-style entry carries {field}", field in entry)
        check(f"{field} is an optional field of the reader", field in AD.ENTRY_FIELDS["optional"])
    check_in("the test_declaration takes the skip form", "skip", entry["test_declaration"])
    for field, bad in (("title_tag", "@("), ("group_declaration", "["), ("each_declaration", "(("), ("loop_heads", "*"),
                       ("title_template", {"open": "${"}), ("title_template", "${"), ("title_placeholders", ["%s", "("]),
                       ("title_placeholders", "%s")):
        broken = shipped_doc()
        broken["assertion_probes"]["typescript"][field] = bad
        got = reading(tmp, broken, f"broken-{field}.json")
        check(f"a broken {field} ({bad!r}) is refused as malformed", isinstance(got, AD.DetectorEntryMalformed), repr(got)[:120])
        if isinstance(got, AD.DetectorEntryMalformed):
            check_in(f"a broken {field} names the field", f"typescript.{field}", got.field)
    for field in ("title_tag", "title_template", "title_placeholders", "group_declaration", "each_declaration", "loop_heads"):
        plain = shipped_doc()
        del plain["assertion_probes"]["typescript"][field]
        check(f"an entry without {field} still reads", isinstance(reading(tmp, plain, f"plain-{field}.json"), dict))


def ast_reading(directory: Path, doc, suffix: str = ".py"):
    """What `ast_entry(suffix, path)` raises (the class) or returns, for `doc` written to `directory`."""
    path = directory / "ast.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    try:
        return AD.ast_entry(suffix, path)
    except AD.DetectorsError as exc:
        return exc


def test_ast_entry_shape():
    """t-2045 N2: `assertion_probes_ast` holds Python's shared contract, read through `ast_entry`; a broken or absent key is a typed
    refusal that names the field of THIS key (never `assertion_probes`), and the fields that fell with t-2064 11.3 are not there."""
    language, entry = AD.ast_entry(".py")
    assert language == "python" and entry["suffixes"] == [".py"]
    assert set(entry) == set(AD.AST_FIELDS["required"]) | {"frames_deepest", "marker_read", "soft_assert_patterns"}, sorted(entry)
    assert entry["soft_assert_patterns"] == [], "t-2064 P1: python STATES that its plain forms have no soft form"
    assert AD.marker_read(entry) == ["message"]      # t-2064 N3b B1: pytest echoes argument values in its text, so the token is read from the message only
    assert all(AD.marker_read(e) == ["message", "text"] for e in AD.assertion_detectors().values())
    assert not {"line_proof_runners", "no_proof_after", "no_proof_args", "matcher_span"} & set(entry)
    assert AD.marker_expression(entry, "T1") == "'-'.join(['qa-probe', 'T1'])"          # the table's reader takes this entry too
    assert AD.grammar_of(entry)[2] == "path" and AD.frames_deepest(entry) == "last"
    rx = re.compile(AD.grammar_of(entry)[0][0])
    got = rx.match("tests/test_n0.py:7: AssertionError")
    assert got and got.group("path") == "tests/test_n0.py" and got.group("line") == "7"
    tmp = temp_dir("qa-detectors-ast-")
    try:
        assert isinstance(ast_reading(tmp, {"x": 1}), AD.DetectorsKeyAbsent)
        assert isinstance(ast_reading(tmp, {AD.AST_KEY: []}), AD.DetectorEntryMalformed)
        for field, bad in (("marker_expr", "'qa-probe'"), ("frames", ["("]), ("frames", ["^(?P<path>x)$"]), ("suffixes", ["py"]),
                           ("compiled", "no"), ("frame_path", "dir"), ("builds_by_default", [1]), ("skip_frames", [7])):
            doc = shipped_doc()
            doc[AD.AST_KEY]["python"][field] = bad
            got = ast_reading(tmp, doc)
            assert isinstance(got, AD.DetectorEntryMalformed), (field, got)
            assert got.field.startswith(f"{AD.AST_KEY}.python.{field}") and got.field in str(got), (field, str(got)[:160])
        for field in ("marker_expr", "frames", "compiled"):
            doc = shipped_doc()
            del doc[AD.AST_KEY]["python"][field]
            got = ast_reading(tmp, doc)
            assert isinstance(got, AD.DetectorEntryMalformed) and got.field.endswith(field), (field, got)
        doc = shipped_doc()
        doc[AD.AST_KEY]["python"]["unknown_field"] = 1
        assert isinstance(ast_reading(tmp, doc), AD.DetectorEntryMalformed)
        doc = shipped_doc()
        del doc[AD.AST_KEY]["python"]["frames_deepest"]       # optional: an entry without it reads, and says unknown
        got = ast_reading(tmp, doc)
        assert isinstance(got, tuple) and AD.frames_deepest(got[1]) is None
    finally:
        cleanup(tmp)


def test_ast_forms_validated():
    """t-2045 N2b: `forms` is the Python check vocabulary, one validator (`ast_entry`). The shipped rows read; every field a row can get
    wrong is a typed refusal that names the field AND the row id, and the shape/kind/slot pairings are closed (negative controls)."""
    language, entry = AD.ast_entry(".py")
    forms = entry["forms"]
    assert [f["id"] for f in forms] == ["PY-assert", "PY-assert_that", "PY-unittest", "PY-unittest-none", "PY-pw-expect",
                                           "PY-with-unittest", "PY-with-pytest"]
    assert {f["shape"] for f in forms} == set(AD.AST_SHAPE_KIND) and forms[3]["invert"] is None
    tmp = temp_dir("qa-detectors-forms-")

    def broken(change, field, row_id):
        doc = shipped_doc()
        change(doc[AD.AST_KEY]["python"]["forms"])
        got = ast_reading(tmp, doc)
        assert isinstance(got, AD.DetectorEntryMalformed), (field, got)
        assert field in got.field and (f"({row_id})" in str(got) if row_id else True) and "gap of the factory's data" in str(got), \
            (field, str(got)[:200])
    try:
        cases = [
            (lambda f: f.__setitem__(slice(None), []), "forms", ""),
            (lambda f: f.append("x"), "forms[7]", ""),
            (lambda f: f[0].__delitem__("shape"), "forms[0].shape", "PY-assert"),
            (lambda f: f[0].update(shape="lambda"), "forms[0].shape", "PY-assert"),
            (lambda f: f[0].update(unknown=1), "forms[0].unknown", "PY-assert"),
            (lambda f: f[1].update(id="PY-assert"), "forms[1].id", "PY-assert"),
            (lambda f: f[0].update(id=""), "forms[0].id", ""),
            (lambda f: f[0].update(invert={"kind": "rename", "names": {}}), "forms[0].invert.kind", "PY-assert"),
            (lambda f: f[1].__delitem__("names"), "forms[1].names", "PY-assert_that"),
            (lambda f: f[1].update(min_args=1), "forms[1].min_args", "PY-assert_that"),
            (lambda f: f[1]["invert"].update(wrap="is_not(x)"), "forms[1].invert.wrap", "PY-assert_that"),
            (lambda f: f[1]["invert"].update(arg=-1), "forms[1].invert.arg", "PY-assert_that"),
            (lambda f: f[1]["message"].update(arg=1), "forms[1].message.arg", "PY-assert_that"),
            (lambda f: f[1]["message"].update(at="kw", kw="msg"), "forms[1].message.at", "PY-assert_that"),
            (lambda f: f[0].update(matcher_at="middle"), "forms[0].matcher_at", "PY-assert"),
            (lambda f: f[2].__delitem__("receivers"), "forms[2].receivers", "PY-unittest"),
            (lambda f: f[0].update(receivers=["self"]), "forms[0].receivers", "PY-assert"),
            (lambda f: f[2]["invert"]["names"]["assertEqual"].update(args="2"), "forms[2].invert.names.assertEqual.args", "PY-unittest"),
            (lambda f: f[2]["invert"]["names"].update(assertEqual={"to": ""}), "forms[2].invert.names.assertEqual", "PY-unittest"),
            (lambda f: f[2]["message"].update(kw="not an identifier"), "forms[2].message.kw", "PY-unittest"),
            (lambda f: f[3].update(message={"at": "kw", "kw": "msg"}), "forms[3].message", "PY-unittest-none"),
            (lambda f: f[3].update(fires_as=7), "forms[3].fires_as", "PY-unittest-none"),
            (lambda f: f[4]["message"].__delitem__("args"), "forms[4].message", "PY-pw-expect"),
            (lambda f: f[4]["invert"].update(pairs=[]), "forms[4].invert.pairs", "PY-pw-expect"),
            (lambda f: f[4]["invert"]["pairs"][0].update(replace="\\9"), "forms[4].invert.pairs[0].replace", "PY-pw-expect"),
        ]
        for change, field, row_id in cases:
            broken(change, field, row_id)
        doc = shipped_doc()
        del doc[AD.AST_KEY]["python"]["forms"]
        got = ast_reading(tmp, doc)
        assert isinstance(got, AD.DetectorEntryMalformed) and got.field.endswith("forms"), got       # the key is required
        assert isinstance(ast_reading(tmp, shipped_doc()), tuple)                                    # the control: unbroken reads
    finally:
        cleanup(tmp)


def test_ast_form_bad_regex_is_detectors_error():
    """A `source`, a `fires_as` or a pattern `find` that does not compile is a DetectorEntryMalformed (a DetectorsError) that names the
    field and the row - the probe never meets a broken regex at run time."""
    tmp = temp_dir("qa-detectors-forms-rx-")
    try:
        for change, field, row_id in (
                (lambda f: f[4].update(source="from ("), "forms[4].source", "PY-pw-expect"),
                (lambda f: f[0].update(fires_as="["), "forms[0].fires_as", "PY-assert"),
                (lambda f: f[4]["invert"]["pairs"][1].update(find="^to_(.+"), "forms[4].invert.pairs[1].find", "PY-pw-expect"),
                (lambda f: f[4].update(source=""), "forms[4].source", "PY-pw-expect")):
            doc = shipped_doc()
            change(doc[AD.AST_KEY]["python"]["forms"])
            got = ast_reading(tmp, doc)
            assert isinstance(got, AD.DetectorEntryMalformed) and isinstance(got, AD.DetectorsError), (field, got)
            assert field in got.field and f"({row_id})" in str(got), str(got)[:200]
            assert "does not compile" in str(got) or "non-empty regex" in str(got), str(got)[:200]
    finally:
        cleanup(tmp)


def test_ast_form_optional_keys_and_with_shape_validated():
    """t-2119: `matcher_at` (a word of the table's MATCHER_AT) and `head_kw.args` (a count) are validated, with the control that the
    good value reads; the `with` shape needs receivers and names, and its invert must stay null."""
    tmp = temp_dir("qa-detectors-forms-opt-")

    def reading_of(change):
        doc = shipped_doc()
        change(doc[AD.AST_KEY]["python"]["forms"])
        return ast_reading(tmp, doc)
    try:
        for word in AD.MATCHER_AT:
            assert isinstance(reading_of(lambda f, w=word: f[0].update(matcher_at=w)), tuple), word
        for bad in ("middle", 1, None, ["head"]):
            got = reading_of(lambda f, b=bad: f[0].update(matcher_at=b))
            assert isinstance(got, AD.DetectorEntryMalformed) and got.field.endswith("forms[0].matcher_at"), (bad, got)
        assert isinstance(reading_of(lambda f: f[4]["message"].update(args=0)), tuple)
        for bad in (-1, "1", 1.5, True, None):
            got = reading_of(lambda f, b=bad: f[4]["message"].update(args=b))
            assert isinstance(got, AD.DetectorEntryMalformed) and got.field.endswith("forms[4].message.args"), (bad, got)
        got = reading_of(lambda f: f[4]["message"].__delitem__("args"))
        assert isinstance(got, AD.DetectorEntryMalformed) and "forms[4].message" in got.field
        for change, field in ((lambda f: f[5].__delitem__("receivers"), "forms[5].receivers"),
                              (lambda f: f[5].__delitem__("names"), "forms[5].names"),
                              (lambda f: f[5].update(invert={"kind": "wrap_test"}), "forms[5].invert"),
                              (lambda f: f[5].update(message={"at": "assert_msg"}), "forms[5].message")):
            got = reading_of(change)
            assert isinstance(got, AD.DetectorEntryMalformed) and field in got.field and "(PY-with-unittest)" in str(got), (field, got)
    finally:
        cleanup(tmp)


def test_suffix_not_in_entry_for_suffix():
    """Negative control: the table's reader does NOT read the AST key (`.py` is never a table entry), and the AST reader claims
    only its own suffixes."""
    table = AD.assertion_detectors()
    assert AD.entry_for_suffix(table, ".py") == (None, None)
    assert sorted(table) == ["csharp", "java", "typescript"]
    assert AD.ast_entry(".cs") == (None, None) and AD.ast_entry(".ts") == (None, None) and AD.ast_entry("") == (None, None)
    assert AD.ast_entry(".PY")[0] == "python"               # the case is not part of a suffix, as in the table's reader
    assert AD.assertion_heads(table) == AD.assertion_heads()      # nothing of the AST key reached the heads


def test_frames_deepest_absent_is_none():
    """`frames_deepest`: first | last; absent, another word, another type and no entry are None (AR-23: unknown, never a guess).
    The shipped values: Playwright first and pytest last (N0 answer 4), csharp and java first (the runtimes' documented order)."""
    assert AD.frames_deepest({"frames_deepest": "first"}) == "first" and AD.frames_deepest({"frames_deepest": "last"}) == "last"
    for entry in ({}, {"frames_deepest": "middle"}, {"frames_deepest": ["first"]}, {"frames_deepest": None}, {"frames_deepest": ""},
                  None, "first", []):
        assert AD.frames_deepest(entry) is None, entry
    table = AD.assertion_detectors()
    assert {language: AD.frames_deepest(entry) for language, entry in table.items()} == {
        "csharp": "first", "java": "first", "typescript": "first"}
    assert AD.frames_deepest(AD.ast_entry(".py")[1]) == "last"
    # the optional field is a field of a table entry: a table entry without it still reads
    tmp = temp_dir("qa-detectors-deepest-")
    try:
        doc = shipped_doc()
        del doc["assertion_probes"]["typescript"]["frames_deepest"]
        got = reading(tmp, doc)
        assert isinstance(got, dict) and AD.frames_deepest(got["typescript"]) is None
    finally:
        cleanup(tmp)


def test_a_suffix_belongs_to_one_key():
    """t-2111 D2: a suffix claimed by both `assertion_probes` and `assertion_probes_ast` is a DetectorsError that names both owners,
    from either reader; a suffix listed twice inside the AST entry is refused too (the table's own check, shared)."""
    tmp = temp_dir("qa-detectors-claims-")
    try:
        doc = shipped_doc()
        doc[AD.AST_KEY]["python"]["suffixes"] = [".py", ".TS"]       # `.ts` is the typescript table entry's; the case is no difference
        got = ast_reading(tmp, doc)
        assert isinstance(got, AD.DetectorEntryMalformed), got
        assert got.field == f"{AD.AST_KEY}.python.suffixes" and "assertion_probes.typescript" in str(got), str(got)[:200]
        table_side = reading(tmp, doc, "claims.json")
        assert isinstance(table_side, AD.DetectorEntryMalformed) and "assertion_probes_ast.python" in str(table_side)
        twice = shipped_doc()
        twice[AD.AST_KEY]["python"]["suffixes"] = [".py", ".PY"]
        got = ast_reading(tmp, twice)
        assert isinstance(got, AD.DetectorEntryMalformed) and "listed twice" in str(got), got
        assert isinstance(ast_reading(tmp, shipped_doc()), tuple)           # the shipped rows claim each suffix once
    finally:
        cleanup(tmp)


def test_marker_expr_evaluates_to_the_prefix_and_token():
    """t-2111 Q4: with a sample token put in, every shipped `marker_expr` evaluates to exactly `MARKER_PREFIX + token`; a row that
    spells another message is refused by the validator of both keys (negative controls: a wrong prefix, a wrong separator)."""
    token = "ab12cd34ef56"
    assert AD.MARKER_PREFIX == "qa-probe-"
    exprs = [e["marker_expr"] for e in AD.assertion_detectors().values()] + [AD.ast_entry(".py")[1]["marker_expr"]]
    assert len(exprs) == 4
    for expr in exprs:
        assert AD.marker_value(expr, token) == AD.MARKER_PREFIX + token, expr
    tmp = temp_dir("qa-detectors-marker-")
    try:
        for bad in ("'-'.join(['qa-prob', '{token}'])", "'_'.join(['qa-probe', 'x', '{token}'])", "'{token}'"):
            doc = shipped_doc()
            doc[AD.AST_KEY]["python"]["marker_expr"] = bad
            got = ast_reading(tmp, doc)
            assert isinstance(got, AD.DetectorEntryMalformed) and got.field.endswith("marker_expr"), (bad, got)
            table = shipped_doc()
            table["assertion_probes"]["csharp"]["marker_expr"] = bad
            assert isinstance(reading(tmp, table, "m.json"), AD.DetectorEntryMalformed), bad
    finally:
        cleanup(tmp)


def test_import_forms_validated():
    """t-2045 N5: `import_forms` is how the probe follows ONE hop out of a test body, per language, as data. The shipped rows read (TypeScript
    relative, Java dotted, C# none); every way a row can be wrong is a typed refusal that names the field; an empty list is legal (this file only)."""
    table = AD.assertion_detectors()
    assert [(r["resolve"], "suffixes" in r) for r in table["typescript"]["import_forms"]] == [("relative", False)]
    assert [(r["resolve"], r["suffixes"]) for r in table["java"]["import_forms"]] == [("dotted", [".java"])]
    assert "import_forms" not in table["csharp"]
    tmp = temp_dir("qa-detectors-imports-")

    def reads(language, value):
        doc = shipped_doc()
        doc["assertion_probes"][language]["import_forms"] = value
        return reading(tmp, doc, "imports.json")
    try:
        for good in ([], [{"pattern": r"^using\s+(?P<path>[\w.]+);", "resolve": "dotted"}],
                     [{"pattern": r"(?P<path>x)", "resolve": "relative", "suffixes": [".cs", ".csx"]}]):
            assert isinstance(reads("csharp", good), dict), good
        # negative controls: each of these is a typed gap that names its field
        cases = [
            ("not a list", {"pattern": "(?P<path>x)", "resolve": "relative"}, "import_forms"),
            ("a row that is not an object", ["x"], "import_forms[0]"),
            ("a bad regex", [{"pattern": "from (", "resolve": "relative"}], "import_forms[0].pattern"),
            ("an empty pattern", [{"pattern": "", "resolve": "relative"}], "import_forms[0].pattern"),
            ("no group path", [{"pattern": r"from\s+(\S+)", "resolve": "relative"}], "import_forms[0].pattern"),
            ("a group with another name", [{"pattern": r"from\s+(?P<file>\S+)", "resolve": "relative"}], "import_forms[0].pattern"),
            ("an unknown resolve", [{"pattern": "(?P<path>x)", "resolve": "absolute"}], "import_forms[0].resolve"),
            ("no resolve", [{"pattern": "(?P<path>x)"}], "import_forms[0]"),
            ("an unknown key", [{"pattern": "(?P<path>x)", "resolve": "relative", "root": "src"}], "import_forms[0]"),
            ("suffixes not a list", [{"pattern": "(?P<path>x)", "resolve": "relative", "suffixes": ".ts"}], "import_forms[0].suffixes"),
            ("a suffix without a dot", [{"pattern": "(?P<path>x)", "resolve": "relative", "suffixes": ["ts"]}], "import_forms[0].suffixes"),
        ]
        for label, value, field in cases:
            got = reads("typescript", value)
            assert isinstance(got, AD.DetectorEntryMalformed), (label, got)
            assert field in got.field and "gap of the factory's data" in str(got), (label, got.field, str(got)[:160])
    finally:
        cleanup(tmp)


def test_passed_residual_validated():
    """t-2064 par.12 (d): `passed_residual` is an optional non-empty string on an entry of either key; the shipped TypeScript entry
    carries it, the Python entry has none; an empty or non-string value is a typed refusal that names the field."""
    assert "wrapper of its own" in AD.assertion_detectors()["typescript"]["passed_residual"]
    assert "passed_residual" not in AD.ast_entry(".py")[1]
    tmp = temp_dir("qa-detectors-residual-")
    try:
        for key, language in (("assertion_probes", "typescript"), ("assertion_probes_ast", "python")):
            for bad in ("", "   ", 3, None, ["x"]):
                doc = shipped_doc()
                doc[key][language]["passed_residual"] = bad
                path = tmp / "r.json"
                path.write_text(json.dumps(doc), encoding="utf-8")
                try:
                    AD.assertion_detectors(path) if key == "assertion_probes" else AD.ast_entry(".py", path)
                except AD.DetectorEntryMalformed as exc:
                    assert "passed_residual" in exc.field, (key, bad, exc.field)
                else:
                    raise AssertionError(f"{key} accepted passed_residual={bad!r}")
            doc = shipped_doc()
            doc[key][language]["passed_residual"] = "a sentence"
            path.write_text(json.dumps(doc), encoding="utf-8")
            assert (AD.assertion_detectors(path) if key == "assertion_probes" else AD.ast_entry(".py", path))
    finally:
        cleanup(tmp)


def main() -> None:
    tmp = temp_dir("qa-detectors-")
    try:
        test_import_forms_validated()
        test_passed_residual_validated()
        test_a_suffix_belongs_to_one_key()
        test_marker_expr_evaluates_to_the_prefix_and_token()
        test_ast_entry_shape()
        test_suffix_not_in_entry_for_suffix()
        test_frames_deepest_absent_is_none()
        the_shipped_table(tmp)
        three_distinct_refusals(tmp)
        malformed_entries(tmp)
        fires_as_against_the_samples()
        t_1953_locator_with_an_author_message()
        the_helpers()
        the_path_and_the_environment(tmp)
        one_reader_no_runtime()
        ep1_37_the_reading_fields(tmp)
    finally:
        cleanup(tmp)
    finish("test_assertion_detectors")


if __name__ == "__main__":
    main()
