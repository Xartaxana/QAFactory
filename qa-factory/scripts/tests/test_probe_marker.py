"""probe_by_code.py: the factory's own marker in the message of the broken check (t-1968 N1).

A mutation probe of a test that is not Python used to say "the broken check fired" only by a library wording its table
knew (`fires_as`). Now the inverted statement also carries a message holding `qa-probe-<token>`, joined at RUN TIME from two
pieces (so no source line, code frame or transpiled copy holds it contiguous), and a FAILED run whose failure/error problem
text holds that exact token was thrown by that check (`proved_by: marker`), whatever the wording and whatever site the frame
names. The marker only ADDS a proof: where no message variant applies the plan is the plain inversion and the table judges as
before (E1.1); a passed row is never looked at, an error row is never decided by the marker, the token of another probe and a
token that stands only in an echoed source line or in a system-out are not a proof.

What is pinned here: the rows (`message` per assertion form, `marker_expr` per language) and their reader; every variant of the
per-language table of the spec on a real-shaped line (the Playwright lines are the ones of the fixtures
`playwright-locator-author-message/`); the guards (run-time join, no format character, lines and brackets kept, no variant
applies -> plain statement and a note); the judge's marker step with its negative controls.

Measured with real libraries on this machine (05.11.2026, dotnet 8 SDK, NuGet cache): NUnit 4.1.0 and NUnit 3.14.0
`Assert.That(x, Is.Not.EqualTo(1), <string>)` and `AreNotEqual(1, 1, <string>)` compile and fail with the string as the first
line of the message; xunit.assert 2.5.3 `Assert.True(false, <string>)` / `Assert.False(true, <string>)` the same. E1.13 (a
Playwright matcher-internal error such as a strict-mode violation or a closed target carries the custom message header) was
MEASURED on Playwright 1.56.0 (the stand's `tr-arm-b/node_modules`, 05.11.2026, chromium headless, a throw-away spec; t-2007 F8): a
`expect(page.locator('div'), '<marker> step 1: x').not.toHaveText('zzz')` over two `div`s fails with `Error: <marker> step 1: x`
as the first line of the junit failure body, then `Error: strict mode violation: locator('div') resolved to 2 elements`, and the
call log repeats `<marker> step 1: x with timeout ...`; a plain wrong value and a page closed while the matcher waits (it
reported an empty value, not a "target closed" text) carry the header the same way. So the named residual HOLDS: such a run reads as fired (`proved_by: marker`), mitigated because the original
test was green on the same state. A throw inside the matcher's ARGUMENTS (before `expect` is built) carries no header (the source
of `lib/matchers/expect.js` 237-238 gives only Jest-shaped errors the custom message). The M-TS rows of the spec's section 6 stay
owed to the live proof.

Runnable alone (`python -B scripts/tests/test_probe_marker.py`) and collected by pytest."""
import copy
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness import FIXTURES, cleanup, temp_dir  # noqa: E402

import assertion_detectors as AD  # noqa: E402
import probe_by_code as PBC  # noqa: E402
import reporters  # noqa: E402

TOKEN = "abc123def456"
MARK = "qa-probe-" + TOKEN
TS_EXPR = "['qa-probe', '" + TOKEN + "'].join('-')"
CS_EXPR = 'string.Join("-", "qa-probe", "' + TOKEN + '")'
JAVA_EXPR = 'String.join("-", "qa-probe", "' + TOKEN + '")'
PW_IMPORT = "import { test, expect } from '@playwright/test';\n\n"
FRAMES = FIXTURES / "playwright-locator-author-message"

SOURCES = {
    "typescript": (PW_IMPORT + "test('adds', async ({ page }) => {\n  {stmt}\n});\n", "t/x.spec.ts::adds"),
    "typescript-plain": ("test('adds', async () => {\n  {stmt}\n});\n", "t/x.spec.ts::adds"),
    "csharp": ("using Xunit;\n\nnamespace Acme\n{\n    public class T\n    {\n        [Fact]\n        public void Adds()\n        {\n"
               "            {stmt}\n        }\n    }\n}\n", "t/T.cs::T.Adds"),
    "java": ("package com.acme;\n{imports}\nclass CalcTest {\n    @Test\n    void adds() {\n        {stmt}\n    }\n}\n",
             "t/CalcTest.java::CalcTest.adds"),
}
JUNIT5 = "import org.junit.jupiter.api.Assertions;\n"
JUNIT4 = "import org.junit.Assert;\n"
ASSERTJ = "import static org.assertj.core.api.Assertions.assertThat;\n"


def source(kind: str, stmt: str, imports: str = "") -> str:
    return SOURCES[kind][0].replace("{imports}", imports).replace("{stmt}", stmt)


def plan(kind: str, stmt: str, *, imports: str = "", token: str = TOKEN, mutate=None, text: str = None):
    """(mutated text, detail, spec) of `plan_detector_mutation` over a one-statement test of `kind`."""
    spec = PBC.parse_node(SOURCES[kind][1])
    if mutate is not None:
        spec["entry"] = copy.deepcopy(spec["entry"])
        mutate(spec["entry"])
    data = (text if text is not None else source(kind, stmt, imports)).encode("utf-8")
    mutated, detail, _context = PBC.plan_detector_mutation(data, spec, "IID", None, "", "", "t/file", marker_token=token)
    return mutated.decode("utf-8"), detail, spec


def after_of(kind: str, stmt: str, **kw) -> str:
    return plan(kind, stmt, **kw)[1]["statement_after"]


def row(status: str, message: str = "", text: str = "", kind: str = "failure") -> dict:
    problems = [] if status in ("passed", "not_run") else [{"kind": kind, "message": message, "text": text}]
    return {"test_id": "x", "status": status, "problems": problems}


def judge(r: dict, detail: dict, spec: dict, *, line=None, site=None) -> dict:
    inside = {"location": f"t/x.spec.ts:{line or detail['line']}", "failure_kind": "assertion", "frame": "  at X"}
    return PBC.judge_probe_row(r, inside if site is None else site, spec["entry"], detail, among=False, argv=[])


# --- the rows ---------------------------------------------------------------------------------------

def test_marker_forms_are_rows():
    """AR-1: how a message attaches to a form is a ROW of detectors.json read by `message_forms`, and a malformed row is a
    typed refusal of the reader that names its field, never a half-read table (FR-41)."""
    table = AD.assertion_detectors()
    for language, entry in table.items():
        assert "{token}" in entry["marker_expr"], language
        for form in entry["assertions"]:
            assert AD.message_forms(form) == (form.get("message") or []), language   # the ONE reader hands the row out
            for variant in AD.message_forms(form):
                assert variant["insert"].count("{marker}") == 1 and variant["args"] >= 0
    shipped = json.loads(Path(AD.DETECTORS_FILE).read_text(encoding="utf-8"))
    heads = {f["head"] for e in shipped["assertion_probes"].values() for f in e["assertions"] if f.get("message")}
    assert len(heads) >= 12, "the per-language table of the spec: xUnit True/False, NUnit That/AreEqual/AreNotEqual, JUnit J1-J6, AssertJ, expect"
    assert AD.message_forms({"head": "x"}) == [] and AD.message_forms({"message": []}) == [] and AD.message_forms(None) == []
    tmp = temp_dir()
    try:
        for label, change in (
                ("a variant without insert", lambda d: d["csharp"]["assertions"][2]["message"][0].pop("insert")),
                ("an insert without {marker}", lambda d: d["csharp"]["assertions"][2]["message"][0].update(insert=", x")),
                ("an unknown `at`", lambda d: d["csharp"]["assertions"][2]["message"][0].update(at="middle")),
                ("a non-regex source", lambda d: d["java"]["assertions"][0]["message"][0].update(source="(")),
                ("a message that is not a list", lambda d: d["csharp"]["assertions"][2].update(message="none")),
                ("a marker_expr with no {token}", lambda d: d["typescript"].update(marker_expr="'qa-probe'"))):
            doc = json.loads(json.dumps(shipped))
            change(doc["assertion_probes"])
            path = Path(tmp) / "d.json"
            path.write_text(json.dumps(doc), encoding="utf-8")
            try:
                AD.assertion_detectors(path)
            except AD.DetectorEntryMalformed as exc:
                assert "assertion_probes." in str(exc) and "factory's data" in str(exc), label
            else:
                raise AssertionError(f"{label}: the reader accepted a malformed row")
    finally:
        cleanup(tmp)


def test_marker_token_is_per_run():
    """E1.4: the token binds the instance, the author's bytes, the moment of the run and (t-2064 P3) the check's key."""
    a = PBC.marker_token("I", "sha", "2026-11-05T10:00:00", "t/x.spec.ts:7")
    assert a == PBC.marker_token("I", "sha", "2026-11-05T10:00:00", "t/x.spec.ts:7") and re.fullmatch(r"[0-9a-f]{12}", a)
    assert len({a, PBC.marker_token("J", "sha", "2026-11-05T10:00:00", "t/x.spec.ts:7"),
                PBC.marker_token("I", "sha2", "2026-11-05T10:00:00", "t/x.spec.ts:7"),
                PBC.marker_token("I", "sha", "2026-11-05T10:00:01", "t/x.spec.ts:7"),
                PBC.marker_token("I", "sha", "2026-11-05T10:00:00", "t/x.spec.ts:8")}) == 5


def test_fires_none_skips_guard():
    """t-2064 P3: `_with_marker` of a statement nobody inverted has no `fires_as` (None): the echo guard is skipped - it used to raise
    `TypeError` inside `re.search` - and the marker goes in; with a `fires_as` that matches the statement the guard still refuses."""
    spec = PBC.parse_node(SOURCES["typescript"][1])
    entry = spec["entry"]
    text = source("typescript", "expect(a, 'step').toBe(1);")
    start = text.index("expect(a")
    statement = "expect(a, 'step').toBe(1);"
    form = entry["assertions"][next(i for i, f in enumerate(entry["assertions"]) if re.match(f["head"], statement))]
    after, variant, note = PBC._with_marker(text, start, statement, text, entry, form, None, TOKEN)
    assert variant and note == "" and TS_EXPR in after and after != statement, f"the marker goes into a statement with no fires_as: {after!r} {note!r}"
    again = PBC._with_marker(text, start, statement, text, entry, form, "expect", TOKEN)
    assert again == (statement, "", again[2]) and "would match the statement with the marker" in again[2], f"a fires_as that matches still refuses: {again}"


# --- the variants -----------------------------------------------------------------------------------

def test_ts_prepend_to_author_message():
    """M-TS1 on the real lines of the fixtures (`add_to_cart.spec.ts:43` and `:104`): the marker goes FIRST in the author's own message."""
    got = after_of("typescript", "expect(catalog.cartBadge, 'step 1: badge empty before the add').not.toHaveCount(0);")
    assert got == "expect(catalog.cartBadge, " + TS_EXPR + " + ' ' + 'step 1: badge empty before the add').toHaveCount(0);", got
    got = after_of("typescript", "expect(detail.addButton, 'Then 4: Add is disabled on B').not.toBeDisabled();")
    assert got == "expect(detail.addButton, " + TS_EXPR + " + ' ' + 'Then 4: Add is disabled on B').toBeDisabled();", got
    _t, detail, _s = plan("typescript", "expect(detail.addButton, 'Then 4: x').not.toBeDisabled();")
    assert (detail["message_form"], detail["message_marker"], detail["message_note"]) == ("M-TS1", MARK, "")
    assert detail["statement_inverted"] == "expect(detail.addButton, 'Then 4: x').toBeDisabled();"
    assert after_of("typescript", "expect.soft(x, 'why').toBe(3);").startswith("expect.soft(x, " + TS_EXPR)


def test_ts_add_message_only_with_playwright_import():
    """M-TS2: a statement with no message gets one only in a file that imports `expect` from @playwright/test."""
    got = after_of("typescript", "expect(catalog.cartBadge).not.toHaveCount(0);")
    assert got == "expect(catalog.cartBadge, " + TS_EXPR + ").toHaveCount(0);", got
    _t, detail, _s = plan("typescript-plain", "expect(catalog.cartBadge).not.toHaveCount(0);")
    assert detail["message_form"] == "" and detail["message_marker"] == "" and "M-TS2" in detail["message_note"]
    assert detail["statement_after"] == "expect(catalog.cartBadge).toHaveCount(0);"
    # a non-string second argument (Playwright's options object) is not a message
    _t, detail, _s = plan("typescript", "expect(a, { timeout: 1 }).not.toBe(3);")
    assert detail["message_form"] == "" and "string literal" in detail["message_note"]


def test_xunit_true_false_get_message():
    assert after_of("csharp", "Assert.True(x > 0);") == "Assert.False(x > 0, " + CS_EXPR + ");"
    assert after_of("csharp", "Assert.False(x);") == "Assert.True(x, " + CS_EXPR + ");"
    assert after_of("csharp", 'Assert.True(x, "why");') == "Assert.False(x, " + CS_EXPR + ' + " " + "why");'
    # the second argument is a variable, not a string literal: no marker, a note (never a guess about its type)
    _t, detail, _s = plan("csharp", "Assert.True(x, why);")
    assert detail["message_form"] == "" and "string literal" in detail["message_note"]
    # a comma inside a nested call or a string is not an argument boundary
    assert after_of("csharp", 'Assert.True(Foo(1, "a,b"));') == 'Assert.False(Foo(1, "a,b"), ' + CS_EXPR + ");"


def test_xunit_equal_gets_none():
    """`message: []` (AR-23): no message overload, the plan is the plain inversion, no note, never an error (E1.1)."""
    for stmt, inverted in (("Assert.Equal(4, x);", "Assert.NotEqual(4, x);"), ("Assert.Contains(\"a\", xs);", "Assert.DoesNotContain(\"a\", xs);"),
                           ("Assert.Null(x);", "Assert.NotNull(x);"), ("Assert.Empty(xs);", "Assert.NotEmpty(xs);")):
        _t, detail, _s = plan("csharp", stmt)
        assert detail["statement_after"] == inverted and detail["message_form"] == "" and detail["message_marker"] == "", stmt
        assert detail["message_note"] == "", stmt


def test_nunit_that_two_and_three_args():
    assert after_of("csharp", "Assert.That(x, Is.EqualTo(3));") == "Assert.That(x, Is.Not.EqualTo(3), " + CS_EXPR + ");"
    assert after_of("csharp", 'Assert.That(x, Is.Not.EqualTo(3), "why");') == \
        "Assert.That(x, Is.EqualTo(3), " + CS_EXPR + ' + " " + "why");'
    assert after_of("csharp", 'Assert.That(Foo(1, "a,b"), Is.EqualTo(3));') == \
        'Assert.That(Foo(1, "a,b"), Is.Not.EqualTo(3), ' + CS_EXPR + ");"
    # NUnit's own lambda message (Func<string>) is not a string literal: no marker
    _t, detail, _s = plan("csharp", "Assert.That(x, Is.EqualTo(3), () => why);")
    assert detail["message_form"] == ""


def test_nunit_classic_gets_message():
    assert after_of("csharp", "ClassicAssert.AreEqual(3, x);") == "ClassicAssert.AreNotEqual(3, x, " + CS_EXPR + ");"
    assert after_of("csharp", "Assert.AreNotEqual(3, x);") == "Assert.AreEqual(3, x, " + CS_EXPR + ");"
    _t, detail, _s = plan("csharp", "Assert.AreEqual(3.0, x, 0.1);")     # the delta overload: 3 arguments, not the message one
    assert detail["message_form"] == "" and "3 argument" in detail["message_note"]


def test_junit5_last_junit4_first():
    assert after_of("java", "assertEquals(4, x);", imports=JUNIT5) == "assertNotEquals(4, x, " + JAVA_EXPR + ");"
    assert after_of("java", "assertTrue(x > 0);", imports=JUNIT5) == "assertFalse(x > 0, " + JAVA_EXPR + ");"
    assert after_of("java", "Assert.assertEquals(4, x);", imports=JUNIT4) == "Assert.assertNotEquals(" + JAVA_EXPR + ", 4, x);"
    assert after_of("java", "assertNull(x);", imports=JUNIT4) == "assertNotNull(" + JAVA_EXPR + ", x);"
    # a message already there: the argument count no longer fits the row, nothing is added
    _t, detail, _s = plan("java", 'assertEquals(4, x, "why");', imports=JUNIT5)
    assert detail["message_form"] == ""


def test_junit_both_imports_gets_none():
    """R14: a file that imports BOTH libraries is ambiguous (message last or first) - neither variant applies."""
    _t, detail, _s = plan("java", "assertEquals(4, x);", imports=JUNIT5 + JUNIT4)
    assert detail["message_form"] == "" and detail["statement_after"] == "assertNotEquals(4, x);"


def test_junit_without_import_gets_none():
    _t, detail, _s = plan("java", "assertEquals(4, x);", imports="")
    assert detail["message_form"] == "" and detail["message_marker"] == "" and detail["statement_after"] == "assertNotEquals(4, x);"
    assert detail["message_note"].startswith("no message variant applies")


def test_assertj_as_inserted_and_skipped_when_described():
    assert after_of("java", "assertThat(x).isEqualTo(3);", imports=ASSERTJ) == \
        "assertThat(x).as(" + JAVA_EXPR + ").isNotEqualTo(3);"
    assert after_of("java", "assertThat(x).isNotNull();", imports=ASSERTJ) == "assertThat(x).as(" + JAVA_EXPR + ").isNull();"
    for described in ('assertThat(x).as("sum").isEqualTo(3);', 'assertThat(x).describedAs("s").isEqualTo(3);'):
        _t, detail, _s = plan("java", described, imports=ASSERTJ)
        assert detail["message_form"] == "" and "already followed by a description" in detail["message_note"], described


# --- the guards -------------------------------------------------------------------------------------

def test_marker_is_runtime_join_never_literal_plus():
    table = AD.assertion_detectors()
    for language, entry in table.items():
        expr = entry["marker_expr"]
        assert "qa-probe-" not in expr and "qa-probe-{token}" not in expr, language
        assert not re.search(r"""['"]\s*\+\s*['"]""", expr), f"{language}: a `+` of two literals is folded by a transpiler"
    # the guard itself: a row that DOES write the contiguous string is turned down at plan time (negative control)
    def contiguous(entry):
        entry["marker_expr"] = "'qa-probe-{token}'"
    _t, detail, _s = plan("typescript", "expect(a, 'why').not.toBe(3);", mutate=contiguous)
    assert detail["message_form"] == "" and "contiguous marker" in detail["message_note"]
    assert detail["statement_after"] == "expect(a, 'why').toBe(3);"


def test_marker_never_contiguous_in_source():
    cases = (("typescript", "expect(a, 'why').not.toBe(3);", ""), ("typescript", "expect(a).not.toBe(3);", ""),
             ("csharp", "Assert.True(x);", ""), ("csharp", "Assert.That(x, Is.EqualTo(3));", ""),
             ("java", "assertEquals(4, x);", JUNIT5), ("java", "assertThat(x).isEqualTo(3);", ASSERTJ))
    for kind, stmt, imports in cases:
        mutated, detail, _s = plan(kind, stmt, imports=imports)
        assert detail["message_marker"] == MARK, stmt
        assert MARK not in mutated and MARK not in detail["statement_after"], f"{stmt}: the contiguous marker is in the source"
        assert TOKEN in mutated, stmt       # the token itself is there, in a join piece of its own


def test_marker_has_no_format_characters():
    for kind, stmt, imports in (("typescript", "expect(a).not.toBe(3);", ""), ("csharp", "Assert.True(x);", ""), ("java", "assertEquals(1, x);", JUNIT5),
                                ("java", "assertThat(x).isEqualTo(3);", ASSERTJ)):
        inserted = plan(kind, stmt, imports=imports)[1]["statement_after"]
        plain = plan(kind, stmt, imports=imports, token="")[1]["statement_after"]
        assert not any(char in inserted for char in "%") and inserted.count("{") == plain.count("{"), stmt
    assert MARK.replace("-", "").isalnum()

    # negative control: a row whose insert carries a format character
    _t, detail, _s = plan("csharp", "Assert.True(x);", mutate=lambda e: e["assertions"][2]["message"][0].update(insert=", {marker} + \"%s\""))
    assert detail["message_form"] == "" and "format character" in detail["message_note"], detail["message_note"]


def test_marker_keeps_lines_and_brackets():
    stmt = "expect(\n    catalog.cartBadge,\n    'step 1: badge'\n  ).not.toHaveCount(0);"
    base = source("typescript", stmt)
    mutated, detail, spec = plan("typescript", stmt)
    plain, plain_detail, _s = plan("typescript", stmt, token="")
    assert detail["message_form"] == "M-TS1" and mutated.count("\n") == base.count("\n") == plain.count("\n")
    assert (detail["line"], detail["end_line"]) == (plain_detail["line"], plain_detail["end_line"])
    lexer = spec["entry"]["lexer"]
    shape, state = PBC.lexical_shape(mutated, lexer)
    plain_shape, _ = PBC.lexical_shape(plain, lexer)
    added, _ = PBC.lexical_shape(TS_EXPR, lexer)
    assert state == "code" and shape == {k: plain_shape[k] + added[k] for k in plain_shape}
    assert len(mutated) - len(plain) <= PBC.MARKER_INSERT_CAP
    assert "\r" not in mutated
    # CRLF stays CRLF: the marker adds no line break of its own
    crlf, crlf_detail, _s = plan("typescript", "", text=base.replace("\n", "\r\n"))
    assert crlf.count("\r\n") == base.count("\n") and crlf.count("\n") == crlf.count("\r\n") and crlf_detail["message_form"] == "M-TS1"

    def breaking(entry):                                  # negative control: an insert with a line break
        entry["assertions"][0]["message"][0]["insert"] = "\n{marker} + ' ' + "
    _t, bad, _s = plan("typescript", "expect(a, 'why').not.toBe(3);", mutate=breaking)
    assert bad["message_form"] == "" and "line break" in bad["message_note"]

    def unbalanced(entry):                                # negative control: an insert that opens a bracket it does not close
        entry["assertions"][0]["message"][0]["insert"] = "{marker}.join( + ' ' + "
    _t, bad, _s = plan("typescript", "expect(a, 'why').not.toBe(3);", mutate=unbalanced)
    assert bad["message_form"] == "" and "brackets" in bad["message_note"]


def test_empty_message_list_skips_marker():
    plain = plan("csharp", "Assert.Equal(4, x);", token="")
    marked = plan("csharp", "Assert.Equal(4, x);")
    assert plain[0] == marked[0] and marked[1]["message_form"] == "" and marked[1]["message_note"] == ""
    # an entry with no marker_expr and a form with variants: no marker, a note that names the missing row
    _t, detail, _s = plan("csharp", "Assert.True(x);", mutate=lambda e: e.pop("marker_expr"))
    assert detail["message_form"] == "" and "marker_expr" in detail["message_note"]
    # no token (every caller older than this node): the plain inversion, no note at all
    _t, detail, _s = plan("csharp", "Assert.True(x);", token="")
    assert (detail["message_form"], detail["message_marker"], detail["message_note"]) == ("", "", "")


# --- the judge --------------------------------------------------------------------------------------

def ts_detail(stmt="expect(catalog.cartBadge, 'step 1: x').not.toHaveCount(0);"):
    _t, detail, spec = plan("typescript", stmt)
    assert detail["message_marker"] == MARK
    return detail, spec


def test_failed_row_with_marker_unknown_text_is_intended():
    detail, spec = ts_detail()
    got = judge(row("failed", "", f"Error: {MARK} step 1: x\n\nsomething no table row has ever seen"), detail, spec)
    assert (got["verdict"], got["proved_by"]) == ("intended_failure", "marker")
    assert "marker" in got["note"] and "factory's to correct" in got["note"]     # E1.8: the fires_as row that missed is named
    got = judge(row("failed", f"{MARK} step 1: x", ""), detail, spec, site={})    # the frame cannot even be read
    assert (got["verdict"], got["proved_by"]) == ("intended_failure", "marker")


def test_marker_with_frame_outside_statement_is_intended():
    """R9 / E1.12: a soft collector reports at the end of the test; the token is in the text of the check that threw."""
    detail, spec = ts_detail()
    got = judge(row("failed", "", f"Error: {MARK} step 1: x\n\n  at t/x.spec.ts:99:5"), detail, spec, line=99)
    assert (got["verdict"], got["proved_by"]) == ("intended_failure", "marker")
    got = judge(row("failed", "", "Error: step 1: x\n\n  at t/x.spec.ts:99:5"), detail, spec, line=99)     # same place, no marker
    assert got["verdict"] == "incomplete" and got["cause"] == "judgment" and "proved_by" not in got    # N3b: the place is a fact, not a verdict


def test_failed_row_without_marker_same_line_not_by_marker():
    detail, spec = ts_detail()
    library = "Error: expect(received).toHaveCount(expected)\n\nExpected: 0"
    fires = AD.assertion_detectors()["typescript"]["assertions"][0]["invert"][0]["fires_as"]
    got = judge(row("failed", "", "Error: expect(locator).toHaveCount(expected) failed"), dict(detail, fires_as=fires), spec)
    assert got["verdict"] == "incomplete" and got["cause"] == "judgment" and "proved_by" not in got     # N3b: a matching wording is judgment
    got = judge(row("failed", "", "Error: step 1: x\n\nan unknown wording"), detail, spec)    # E15 unchanged: advice, not a proof
    assert got["verdict"] == "incomplete" and got["cause"] == "judgment" and "proved_by" not in got   # t-1968 N2: the critic's to judge
    got = judge(row("failed", "", library), detail, spec)                                      # the sample text of the row's wording: no longer proves
    assert got["verdict"] == "incomplete" and got["cause"] == "judgment" and "proved_by" not in got, got


def test_other_token_not_counted():
    detail, spec = ts_detail()
    other = "qa-probe-" + PBC.marker_token("IID", "sha", "another run", "t/x.spec.ts:7")
    assert other != MARK
    got = judge(row("failed", "", f"Error: {other} step 1: x"), detail, spec)
    assert got["verdict"] == "incomplete" and "proved_by" not in got
    got = judge(row("failed", "", f"Error: {MARK[:-1]} step 1: x"), detail, spec)       # a cut token is not the token
    assert got["verdict"] == "incomplete"


def test_error_row_with_marker_not_intended():
    detail, spec = ts_detail()
    got = judge(row("error", f"{MARK} step 1: x", f"{MARK}", kind="error"), detail, spec)
    assert got["verdict"] == "incomplete" and "proved_by" not in got


def test_passed_row_ignores_marker():
    """E-P, both ways: a passed row with the token only in a key that is no problem is never proved; a row that HOLDS a failure problem
    with the marker is `failed` whatever its status says (`_row_status`), so it is proved by the marker."""
    detail, spec = ts_detail()
    passed = row("passed")
    passed["system_out"] = MARK       # the marker echoed outside the problem body: not read
    got = judge(passed, detail, spec, site={})
    assert got["verdict"] == "no_failure" and "proved_by" not in got
    holding = row("passed")
    holding["problems"] = [{"kind": "failure", "message": MARK, "text": MARK}]
    got = judge(holding, detail, spec, site={})
    assert got["verdict"] == "intended_failure" and got["proved_by"] == "marker", got


def test_marker_in_system_out_only_is_not_read():
    """R7 / E1.11: the report's problem body is the only text read; a step title or a system-out that echoes the runtime message of
    a check that PASSED proves nothing."""
    tmp = temp_dir()
    try:
        path = Path(tmp) / "report.junit.xml"
        path.write_text(
            '<testsuites><testsuite name="s"><testcase classname="x.spec.ts" name="adds">'
            f'<failure message="Error: step 1: x">Error: step 1: x\n  at t/x.spec.ts:3:5</failure>'
            f'<system-out>step: {MARK} step 1: x (passed)</system-out></testcase></testsuite></testsuites>', encoding="utf-8")
        rows = reporters.read_rows(path, "junit-xml")
        assert len(rows) == 1 and rows[0]["status"] == "failed" and MARK not in json.dumps(rows[0])
        detail, spec = ts_detail()
        got = judge(rows[0], detail, spec)
        assert got["verdict"] == "incomplete" and "proved_by" not in got
    finally:
        cleanup(tmp)


def test_fires_as_no_longer_proves():
    """E1.9, N3b: a detail planned before this node has no `message_marker`; the library's wording that a row's `fires_as` matches
    no longer proves - with no marker in the detail and with one (text without it) the row is the critic's, `cause: judgment`."""
    _t, detail, spec = plan("typescript", "expect(a).not.toBe(3);", token="")
    assert detail["message_marker"] == "" and detail["fires_as"]
    text = "Error: expect(received).toBe(expected) // Object.is equality\n\nExpected: 3"
    assert AD.fires_in(detail["fires_as"], text), "control: the row's wording DOES match this text"
    got = judge(row("failed", "", text), detail, spec)
    assert (got["verdict"], got["cause"]) == ("incomplete", "judgment") and "proved_by" not in got, got
    legacy = {k: v for k, v in detail.items() if k not in ("message_marker", "message_form", "message_note")}
    got = judge(row("failed", "", text), legacy, spec)
    assert (got["verdict"], got["cause"]) == ("incomplete", "judgment") and "proved_by" not in got, got
    # a marker in the detail, the text without it but in the table's wording: the same, still judgment
    detail2, spec2 = ts_detail("expect(a, 'why').not.toBe(3);")
    got = judge(row("failed", "", text), detail2, spec2)
    assert (got["verdict"], got["cause"]) == ("incomplete", "judgment") and "proved_by" not in got, got
    # the marker in the same detail proves, whatever the wording (the one proof): a null `fires_as` writes no crash and no note
    got = judge(row("failed", "", f"Error: {MARK} x"), dict(detail2, fires_as=None), spec2)
    assert (got["verdict"], got["proved_by"], got["note"]) == ("intended_failure", "marker", ""), got


def test_code_frame_echo_cannot_prove():
    """E1.3 on the real fixture: the Playwright junit body carries a code frame of the source and the RUNTIME message. The statement
    in that frame (the planned one, with its join expression) never holds the contiguous token, and the real text has none."""
    detail, spec = ts_detail("expect(catalog.cartBadge, 'step 1: badge empty before the add').not.toHaveCount(0);")
    real = (FRAMES / "tc001-in-stock.failure.txt").read_text(encoding="utf-8")
    got = judge(row("failed", "step 1: badge empty before the add", real), detail, spec)
    assert got["verdict"] != "intended_failure" and "proved_by" not in got
    echoed = real.replace("await expect(catalog.cartBadge, 'step 1: badge empty before the add').not.toHaveCount(0);",
                          "await " + detail["statement_after"])
    assert echoed != real and TOKEN in echoed and MARK not in echoed
    got = judge(row("failed", "step 1: badge empty before the add", echoed), detail, spec)
    assert got["verdict"] != "intended_failure" and "proved_by" not in got
    # positive control of the same fixture shape: the RUNTIME message, as Playwright prints it, holds the token and proves
    runtime = real.replace("Error: step 1: badge empty", f"Error: {MARK} step 1: badge empty")
    got = judge(row("failed", "step 1: badge empty before the add", runtime), detail, spec)
    assert (got["verdict"], got["proved_by"]) == ("intended_failure", "marker")


def test_truncated_text_loses_proof():
    """E1.5: the marker is FIRST in the message; a cut that drops it only loses the proof."""
    detail, spec = ts_detail()
    full = f"Error: {MARK} step 1: x\n" + "padding " * 50
    assert judge(row("failed", "", full), detail, spec)["proved_by"] == "marker"
    tail = full[len(f"Error: {MARK} "):]
    assert judge(row("failed", "", tail), detail, spec)["verdict"] == "incomplete"


def test_rows_record_proved_by():
    """`_judge_rows` writes `proved_by` into the record beside `verdict` only when EVERY row is `intended_failure` by the marker
    (`_worst_of_rows`); no third value is written: a stub that says `fires_as` leaves the record without it (the judge is replaced
    by a stub, as in test_probe_by_code_languages.judge_rows)."""
    spec = PBC.parse_node("src/sum.test.ts::adds")
    detail = {"language": "typescript", "candidates": [3], "at": None, "line": 3, "end_line": 5}
    request = {"instance_contracts": {"adds": {"file": "src/sum.test.ts", "report_test_id": "sum.test.ts::adds", "classname_match": "file_suffix"}},
               "command": {"argv": ["npx", "playwright", "test"]}}
    old_judge, old_site = PBC.judge_probe_row, PBC.reporters.assertion_site

    def run(proved_by, verdict="intended_failure"):
        record = {"task": "T", "notes": [], "expected_location": "src/sum.test.ts:3", "expected_reason": "m", "verdict": "not_executed"}

        def stub(r, site, entry, detail_, *, among, argv):
            got = {"verdict": verdict, "actual_location": None, "actual_reason": None, "mismatches": [], "note": "",
                   "observed": {"status": r["status"]}}
            if proved_by:
                got["proved_by"] = proved_by
            return got
        PBC.judge_probe_row, PBC.reporters.assertion_site = stub, lambda *a, **k: {}
        try:
            PBC._judge_rows(Path("."), record, [{"test_id": "sum.test.ts::adds", "status": "failed", "problems": []}],
                                     "junit-xml", spec, detail, request, Path("x"), ["adds"], True)
        finally:
            PBC.judge_probe_row, PBC.reporters.assertion_site = old_judge, old_site
        return record
    assert run("marker")["proved_by"] == "marker" and "proved_by" not in run("fires_as")
    assert "proved_by" not in run(None) and "proved_by" not in run("marker", "wrong_location")


# --- Python: the AST reader's plan carries the same marker contract (t-2045 N2) ----------------------------------

PY_SRC = ("from calc import add\nfrom hamcrest import assert_that, equal_to\n\n\n"
          "def test_add():\n    assert add(2, 2) == 4, 'sum must be 4'\n\n\n"
          "def test_multi():\n    assert add(\n        2, 2\n    ) == 4\n\n\n"
          "def test_hamcrest():\n    assert_that(add(2, 2), equal_to(4), 'why')\n")
PY_EXPR = "'-'.join(['qa-probe', '" + TOKEN + "'])"


def py_plan(node: str = "test_add", data: bytes = None, token: str = TOKEN, **kw):
    data = PY_SRC.encode("utf-8") if data is None else data
    return PBC.plan_mutation(data, PBC.parse_node(f"t/test_calc.py::{node}"), "invert", "IID", marker_token=token, **kw) + (data,)


def test_python_marker_joined_at_run_time():
    """The message of the inverted assert is the AST entry's `marker_expr`, joined at run time: the contiguous marker is in
    neither the mutated bytes nor the statement, the token is there in a piece of its own; `assert_that` replaces its third
    argument the same way, and `message_marker` / `message_form` say what was put in."""
    for node, expected_head in (("test_add", "assert"), ("test_hamcrest", "assert_that")):
        mutated, detail, _data = py_plan(node)
        assert detail["message_marker"] == MARK and detail["message_form"] == {"assert": "PY-assert", "assert_that": "PY-assert_that"}[expected_head], node
        assert MARK not in mutated.decode() and MARK not in detail["statement_after"], node
        assert PY_EXPR in detail["statement_after"] and PY_EXPR not in detail["statement_inverted"], node
        assert "why" not in detail["statement_after"] and "sum must be 4" not in detail["statement_after"], node   # replaced, as before
    # the data is the source of the spelling, not the code (AR-1): the same expression is what the entry gives
    assert AD.marker_expression(AD.ast_entry(".py")[1], TOKEN) == PY_EXPR
    # no token = no marker: the message stays the human marker's text, `message_marker` is "" and the note is empty
    mutated, detail, _data = py_plan(token="")
    assert detail["message_marker"] == "" and detail["message_form"] == "" and detail["message_note"] == ""
    assert detail["statement_after"].endswith('"probe-IID invert: add(2, 2) == 4"')


def test_python_detail_same_keys_as_detector():
    """Set equality with a TypeScript plan: one contract for both readers."""
    _m, py, _d = py_plan()
    _t, ts, _spec = plan("typescript", "expect(a, 'why').not.toBe(3);")
    assert set(py) == set(ts), sorted(set(py) ^ set(ts))
    assert py["language"] == "python" and py["style"] == "assert" and py["candidates"] == [] and py["pair"] is None
    assert py["fires_as"] is None and py["declaration_line"] == 5 and py["file"] == "t/test_calc.py"
    assert set(py_plan("test_hamcrest")[1]) == set(ts)
    assert "matcher_span" not in py and "matcher_span" not in ts       # fell with t-2064 11.3


def test_python_marker_line_count_kept():
    for node in ("test_add", "test_multi", "test_hamcrest"):
        mutated, detail, data = py_plan(node)
        assert mutated.count(b"\n") == data.count(b"\n"), node
        assert detail["statement_after"].count("\n") == detail["statement_before"].count("\n"), node
    # a BOM stays and the plan still reads (the AST path strips it before it counts a line or a column)
    bommed = b"\xef\xbb\xbf" + PY_SRC.encode("utf-8")
    mutated, detail, _d = py_plan("test_add", data=bommed)
    assert mutated.startswith(b"\xef\xbb\xbf") and detail["message_marker"] == MARK and detail["line"] == 6


def test_python_marker_echo_of_another_statement_is_not_the_marker():
    """E1.3 for Python, on a real pytest: the failure of ANOTHER statement whose traceback echoes the mutated line (the
    asserted expression raises before the message is built), with `-vv` and `--showlocals`, never holds the contiguous token;
    the negative control (the same shape where the inverted assert FIRES) does hold it as the message."""
    import subprocess
    tmp = temp_dir()
    try:
        raising = "def test_a():\n    n = int('abc')\n    assert n == 1, 'm'\n\n\ndef test_b():\n    assert int('abc') == 1\n"
        firing = "def test_a():\n    assert 1 == 1, 'm'\n"
        outputs = {}
        for label, text, node in (("echo", raising, "test_b"), ("fires", firing, "test_a")):
            mutated, _detail, _d = py_plan(node, data=text.encode("utf-8"))
            test_file = Path(tmp) / f"test_{label}.py"
            test_file.write_bytes(mutated)
            proc = subprocess.run([sys.executable, "-B", "-m", "pytest", str(test_file), "-vv", "--showlocals", "-p",
                                   "no:cacheprovider"], capture_output=True, text=True, encoding="utf-8", cwd=tmp)
            outputs[label] = proc.stdout + proc.stderr
        assert "ValueError" in outputs["echo"] and MARK not in outputs["echo"], outputs["echo"][-600:]
        assert "AssertionError: " + MARK in outputs["fires"], outputs["fires"][-600:]
    finally:
        cleanup(tmp)


def test_python_verdict_reads_the_joined_marker():
    """N3b: a Python row goes through the ONE row judge (`verdict_of` is gone): the run whose message holds the joined token is
    `intended_failure`, `proved_by: marker`; another token, or a detail with no `message_marker` (a record of before, whose
    message was the human marker's text), is `incomplete`, `cause: judgment` - the place and the wording are facts, not a proof."""
    _m, detail, _d = py_plan()
    assert not hasattr(PBC, "verdict_of") and not hasattr(PBC, "_judge_row")
    spec = PBC.parse_node("t/test_calc.py::test_add")
    site = {"location": f"t/test_calc.py:{detail['line']}", "failure_kind": "assertion"}

    def judged(message, d=detail):
        return PBC.judge_probe_row(row("failed", "AssertionError: " + message, ""), site, spec["entry"], d, among=False,
                                   argv=["python", "-m", "pytest"])
    got = judged(MARK)
    assert (got["verdict"], got["proved_by"], got["note"]) == ("intended_failure", "marker", ""), got      # `fires_as` is null: no crash
    got = judged("qa-probe-other")
    assert (got["verdict"], got["cause"]) == ("incomplete", "judgment") and "proved_by" not in got, got
    old = {k: v for k, v in detail.items() if k != "message_marker"}
    got = judged(detail["marker"], old)
    assert (got["verdict"], got["cause"]) == ("incomplete", "judgment") and "proved_by" not in got, got


ALL = [(name, fn) for name, fn in sorted(globals().items()) if name.startswith("test_") and callable(fn)]

if __name__ == "__main__":
    failed = 0
    for name, fn in ALL:
        try:
            fn()
            print(f"PASS {name}")
        except Exception as exc:  # noqa: BLE001 - the runner prints which key broke
            failed += 1
            print(f"FAIL {name}: {type(exc).__name__}: {exc}")
    print(f"{len(ALL) - failed}/{len(ALL)} passed")
    sys.exit(1 if failed else 0)
