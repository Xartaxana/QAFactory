"""t-2064 P1: the data rows a red probe on EVERY check reads, and their readers in `assertion_detectors` (AD).

What these pin, for each of the four languages the factory reads (python by the AST key, typescript, csharp and java by the table):
  - every entry STATES whether it has a soft form (`soft_assert_patterns`, `[]` = none); an absent key reads as `[]` with the note
    "the row does not say" and gives the same plan (AR-23);
  - `actual_arg` rows exist only where the order of arguments is verified (a form in doubt has no key), and are refused when malformed;
  - `s5_precheck._all_soft` of an empty list is False (an unknown never lifts a finding);
  - the retry flags go by what the test FILE imports, never by the language; a regex that fails gives `[]` and a note, not an exception;
  - `interruption_texts` is `[]` where absent.
"No soft form" is data and never a language branch (AR-1): a test below carries the same row to an entry of another language and
the reader answers the same. A red here names the language (the parameter id) and the branch (the test and its message).

Fast: no run, no project but one temp file. Runnable alone (`python -B scripts/tests/test_probe_every_check.py`) and collected by pytest."""
import json
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import assertion_detectors as AD  # noqa: E402
import s5_precheck as P  # noqa: E402

LANGUAGES = ("python", "typescript", "csharp", "java")
TABLE_LANGUAGES = ("typescript", "csharp", "java")
FLAG = "--retries=0"
PLAYWRIGHT_FILE = "import { test, expect } from '@playwright/test';\ntest('a', async () => {});\n"
PLAIN_FILE = "import { test } from 'vitest';\ntest('a', () => {});\n"


def shipped_doc() -> dict:
    return json.loads(Path(AD.DETECTORS_FILE).read_text(encoding="utf-8"))


def entry_of(language: str) -> dict:
    """The shipped entry of `language`, the AST key's for python."""
    if language == "python":
        return AD.ast_entry(".py")[1]
    return AD.assertion_detectors()[language]


def forms_of(language: str) -> list:
    entry = entry_of(language)
    return entry["forms"] if language == "python" else entry["assertions"]


def without(entry: dict, key: str) -> dict:
    return {k: v for k, v in entry.items() if k != key}


def refused(tmp_path: Path, doc: dict, language: str):
    """The DetectorEntryMalformed the loader raises for `doc` (the AST reader for python), or None when it loads."""
    path = tmp_path / "d.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    try:
        AD.ast_entry(".py", path) if language == "python" else AD.assertion_detectors(path)
    except AD.DetectorEntryMalformed as exc:
        return exc
    return None


def doc_key(language: str) -> str:
    return AD.AST_KEY if language == "python" else AD.KEY


@pytest.mark.parametrize("language", LANGUAGES)
def test_every_entry_says_soft(language):
    entry = entry_of(language)
    assert "soft_assert_patterns" in entry, f"{language}: the entry does not STATE its soft forms (`[]` = none)"
    patterns, note = AD.soft_stated(entry)
    assert note == "", f"{language}: a stated row must carry no note, got {note!r}"
    assert patterns == AD.soft_patterns(entry), f"{language}: soft_stated and soft_patterns read one row two ways"
    if language == "typescript":
        assert patterns == ["\\bexpect\\.soft\\s*\\("], f"{language}: its soft form is a data row"
    else:
        assert patterns == [], f"{language}: no soft form is stated as `[]`, got {patterns!r}"


@pytest.mark.parametrize("language", LANGUAGES)
def test_absent_soft_reads_empty_with_note(language, tmp_path):
    stated = dict(entry_of(language), soft_assert_patterns=[])
    absent = without(entry_of(language), "soft_assert_patterns")
    assert AD.soft_stated(absent) == ([], AD.SOFT_UNSAID), f"{language}: absent must read [] with the note"
    assert "does not say" in AD.SOFT_UNSAID
    assert AD.soft_stated(stated) == ([], ""), f"{language}: a stated [] reads the same plan without a note"
    assert AD.soft_stated(absent)[0] == AD.soft_stated(stated)[0] == AD.soft_patterns(absent), f"{language}: absent and [] give one plan"
    assert AD.soft_stated(None) == ([], AD.SOFT_UNSAID), f"{language}: no entry at all says nothing"
    broken = dict(entry_of(language), soft_assert_patterns=["(expect"])
    assert AD.soft_stated(broken)[0] == [] and "does not compile" in AD.soft_stated(broken)[1], \
        f"{language}: a regex that fails reads [] with a note, never an exception"
    doc = shipped_doc()
    doc[doc_key(language)][language]["soft_assert_patterns"] = []
    assert refused(tmp_path, doc, language) is None, f"{language}: the loader must accept an empty `soft_assert_patterns`"
    doc[doc_key(language)][language]["soft_assert_patterns"] = ["(expect"]
    exc = refused(tmp_path, doc, language)
    assert exc is not None and "soft_assert_patterns[0]" in exc.field, f"{language}: a broken soft regex is the loader's refusal"


# (head fragment of the table row | id of the AST row) -> the verified `actual_arg`. Every number is read in the library's own
# documentation and shown on a sample (t-2064 P1 report); a form in doubt has NO key and is listed in NO_KEY below.
VERIFIED = {
    "typescript": {"\\bexpect(?:\\.soft)?": 1},
    "csharp": {"Assert\\.Equal\\b": 2, "Assert\\.NotEqual\\b": 2, "Assert\\.True\\b": 1, "Assert\\.False\\b": 1,
               "Assert\\.Null\\b": 1, "Assert\\.NotNull\\b": 1, "Assert\\.Empty\\b": 1, "Assert\\.NotEmpty\\b": 1,
               "Assert\\.Contains\\b": 2, "Assert\\.DoesNotContain\\b": 2, "Assert\\.That\\b": 1,
               "Assert\\.AreEqual\\b": 2, "Assert\\.AreNotEqual\\b": 2},
    "java": {"assertThat\\s*\\(": 1},
    "python": {"PY-assert": "compare_left", "PY-assert_that": 1, "PY-pw-expect": 1},
}
# Forms left WITHOUT a key for doubt: JUnit's head also matches JUnit 4, whose message comes FIRST (measured: assertEquals("MSG", 3, 4)),
# so the number of the argument moves with a message; node's `assert` head holds several forms; unittest's names differ in order.
NO_KEY = {
    "typescript": ("\\bassert(?:",),
    "java": ("assertEquals\\b", "assertNotEquals\\b", "assertTrue\\b", "assertFalse\\b", "assertNull\\b", "assertNotNull\\b"),
    "python": ("PY-unittest", "PY-unittest-none", "PY-with-unittest", "PY-with-pytest"),
}


def form_by(language: str, fragment: str) -> dict:
    """The ONE form whose AST id is `fragment` (python) or whose head holds it (table)."""
    if language == "python":
        found = [form for form in forms_of(language) if form["id"] == fragment]
    else:
        found = [form for form in forms_of(language) if fragment in form["head"]]
    assert len(found) == 1, f"{language}: {fragment!r} must name exactly one form, found {len(found)}"
    return found[0]


@pytest.mark.parametrize("language", LANGUAGES)
def test_actual_arg_rows(language, tmp_path):
    for fragment, expected in VERIFIED[language].items():
        form = form_by(language, fragment)
        assert AD.actual_arg_of(form) == expected, f"{language} {fragment}: actual_arg must be {expected!r}, got {AD.actual_arg_of(form)!r}"
    for fragment in NO_KEY.get(language, ()):
        form = form_by(language, fragment)
        assert "actual_arg" not in form and AD.actual_arg_of(form) is None, \
            f"{language} {fragment}: a form in doubt must have no `actual_arg` (an unverified row is not written)"
    for form in forms_of(language):
        if form.get("matcher_at") == "after_args":
            assert AD.actual_arg_of(form) == 1, f"{language}: a form whose matcher follows the call's parentheses reads argument 1"
    # the reader: absent, bool, zero, a word it does not know and a non-form all read None, never raise
    for bad in (None, True, False, 0, -1, "1", "left", 1.5, [], {}):
        assert AD.actual_arg_of({"actual_arg": bad}) is None, f"{language}: {bad!r} is no actual_arg"
    assert AD.actual_arg_of({}) is None and AD.actual_arg_of(None) is None and AD.actual_arg_of("x") is None
    # the loader refuses a malformed value and names the field
    for bad in (0, True, "1", "right", 1.5, None):
        doc = shipped_doc()
        index = forms_of(language).index(form_by(language, next(iter(VERIFIED[language]))))
        holder = doc[doc_key(language)][language]["forms" if language == "python" else "assertions"][index]
        holder["actual_arg"] = bad
        exc = refused(tmp_path, doc, language)
        assert exc is not None and exc.field.endswith("].actual_arg"), f"{language}: actual_arg={bad!r} must be refused, got {exc!r}"


@pytest.mark.parametrize("language", LANGUAGES)
def test_all_soft_empty_list_false(language, tmp_path, monkeypatch):
    """`_all_soft` of a language whose soft list is `[]` is False (the finding stands), and the control - the same file, an entry that
    DOES name the form soft - is True, so the False is the empty list's and not a refusal of the file."""
    if language == "python":
        # a `.py` file has no table entry at all: `_span_entry` finds none, `_all_soft` is False before any soft list is read
        assert AD.entry_for_suffix(AD.assertion_detectors(), ".py") == (None, None), "python must not be an entry of the table"
        assert AD.soft_patterns(entry_of("python")) == [], "python: the AST entry states no soft form"
        return
    sources = {
        "typescript": "test('a', async () => {\n  expect.soft(a).toBe(1);\n});\n",
        "csharp": "class T {\n  void A() {\n    Assert.Equal(1, 2);\n  }\n}\n",
        "java": "class T {\n  void a() {\n    assertEquals(1, 2);\n  }\n}\n",
    }
    lines = {"typescript": 2, "csharp": 3, "java": 3}
    path = tmp_path / "t.txt"
    path.write_text(sources[language], encoding="utf-8")
    entry = entry_of(language)
    head = entry["assertions"][0]["head"] if language != "typescript" else "\\bexpect\\.soft\\s*\\("
    span = ("t.txt", lines[language], lines[language])

    def all_soft(patterns):
        monkeypatch.setattr(P, "_span_entry", lambda s, root: (path, language, dict(entry, soft_assert_patterns=patterns)))
        return P._all_soft(span, tmp_path)

    assert all_soft([]) is False, f"{language}: an empty `soft_assert_patterns` must never read as all-soft"
    assert all_soft([head]) is True, f"{language}: control - a head named soft must read as all-soft (else the False above proves nothing)"


@pytest.mark.parametrize("language", LANGUAGES)
def test_no_retry_by_source_not_by_language(language):
    row = {"source": "from\\s+['\"]@playwright/test['\"]", "flags": [FLAG]}
    # the shipped data: only the entry that carries the row answers, and only for a file that imports the library
    if language == "typescript":
        assert AD.no_retry_flags(entry_of(language), PLAYWRIGHT_FILE) == [FLAG], f"{language}: a Playwright file must get the flag"
        assert AD.no_retry_flags(entry_of(language), PLAIN_FILE) == [], f"{language}: a file with no Playwright import must get []"
        assert AD.no_retry_flags(entry_of(language), "") == [], f"{language}: an empty file must get []"
    else:
        assert AD.no_retry_flags(entry_of(language), PLAYWRIGHT_FILE) == [], f"{language}: no row, no flag"
    # the reader never asks the language: the same row on ANY entry answers the same, by the file's text alone
    carried = dict(entry_of(language), probe_no_retry=[row])
    assert AD.no_retry_flags(carried, PLAYWRIGHT_FILE) == [FLAG], f"{language}: the row decides, not the language"
    assert AD.no_retry_flags(carried, PLAIN_FILE) == [], f"{language}: a file with no import must get [] whatever the language"
    assert AD.no_retry_flags(without(carried, "probe_no_retry"), PLAYWRIGHT_FILE) == [], f"{language}: an entry with no row gives []"
    assert AD.no_retry_flags(carried, None) == [] and AD.no_retry_flags(None, PLAYWRIGHT_FILE) == []
    first = dict(entry_of(language), probe_no_retry=[{"source": "NEVER_MATCHES", "flags": ["--x"]}, row])
    assert AD.no_retry_flags(first, PLAYWRIGHT_FILE) == [FLAG], f"{language}: the first row that MATCHES wins"
    # a fresh list each call: the caller owns what it gets
    flags = AD.no_retry_flags(carried, PLAYWRIGHT_FILE)
    flags.append("--mutated")
    assert AD.no_retry_flags(carried, PLAYWRIGHT_FILE) == [FLAG], f"{language}: the answer must be a fresh list"


@pytest.mark.parametrize("language", LANGUAGES)
def test_no_retry_bad_regex_empty(language, tmp_path):
    bad = dict(entry_of(language), probe_no_retry=[{"source": "(unclosed", "flags": [FLAG]}])
    notes = []
    assert AD.no_retry_flags(bad, PLAYWRIGHT_FILE, notes) == [], f"{language}: a source that does not compile gives []"
    assert len(notes) == 1 and "does not compile" in notes[0], f"{language}: the failure leaves one note, got {notes!r}"
    assert AD.no_retry_flags(bad, PLAYWRIGHT_FILE) == [], f"{language}: with no list to note into it must still not raise"
    if language != "python":       # the AST key's entry holds no such row; the table's loader refuses a broken one
        doc = shipped_doc()
        doc[AD.KEY][language]["probe_no_retry"] = [{"source": "(unclosed", "flags": [FLAG]}]
        exc = refused(tmp_path, doc, language)
        assert exc is not None and "probe_no_retry[0].source" in exc.field, f"{language}: the loader must refuse a source that fails"
        for wrong in ([{"source": "x", "flags": []}], [{"source": "x"}], [{"source": "x", "flags": [FLAG], "more": 1}], "x"):
            doc[AD.KEY][language]["probe_no_retry"] = wrong
            exc = refused(tmp_path, doc, language)
            assert exc is not None and "probe_no_retry" in exc.field, f"{language}: {wrong!r} is a malformed row"


@pytest.mark.parametrize("language", LANGUAGES)
def test_interruption_absent_empty(language, tmp_path):
    entry = entry_of(language)
    if language == "typescript":
        texts = AD.interruption_texts(entry)
        assert texts and all(re.search(t, "Error: Test timeout of 6000ms exceeded.") for t in texts), \
            f"{language}: the runner's own cut text must match the measured line"
        assert not any(re.search(t, "Error: expect(received).toBe(expected)") for t in texts), f"{language}: an ordinary failure is no cut"
    else:
        assert AD.interruption_texts(entry) == [], f"{language}: no row, nothing to demote"
    assert AD.interruption_texts(without(entry, "interruption_texts")) == [], f"{language}: absent must read []"
    assert AD.interruption_texts(None) == [] and AD.interruption_texts({"interruption_texts": "x"}) == []
    assert AD.interruption_texts({"interruption_texts": ["a", 3, "", "b"]}) == ["a", "b"], f"{language}: strings only"
    if language != "python":
        doc = shipped_doc()
        doc[AD.KEY][language]["interruption_texts"] = ["(cut"]
        exc = refused(tmp_path, doc, language)
        assert exc is not None and "interruption_texts[0]" in exc.field, f"{language}: a broken regex is the loader's refusal"
        doc[AD.KEY][language]["interruption_texts"] = "cut"
        exc = refused(tmp_path, doc, language)
        assert exc is not None and "interruption_texts" in exc.field, f"{language}: a text that is not a list is refused"


# --- t-2064 P2: the list of a test's checks and the plan of runs (pure) -------------------------------------------------------
# One generic world per language: a test whose body is `a = 1` and then a chosen run of statements, each a SOFT form (the entry's
# `soft_assert_patterns` row says so - carried onto the entry, because only the table's TypeScript entry ships one) or a HARD one.
# A red names the language (the parameter id) and the branch (the test and its message).

import hashlib  # noqa: E402

import probe_by_code as PBC  # noqa: E402

# language -> {file, node, head (lines before the statements), tail, soft/hard statement templates ({n} = its label), soft pattern,
#              helper (one call + a file holding one check), two (two statements on ONE line)}
LANG = {
    "python": {
        "file": "tests/test_t.py", "node": "tests/test_t.py::test_run", "head": "def test_run():\n    a = 1\n", "tail": "",
        "soft": "    assert a == 1, \"{n}\"\n", "hard": "    assert_that(a, equal_to(1), \"{n}\")\n", "pattern": r"assert\s",
        "call": "    expect_cart(a)\n", "helper_file": "tests/helpers.py", "helper": "def expect_cart(n):\n    assert n == 1\n",
        "helper_check": 2, "two": "    assert a == 1; assert a == 2\n"},
    "typescript": {
        "file": "tests/t.spec.ts", "node": "tests/t.spec.ts::t",
        "head": "import { test, expect } from '@playwright/test';\ntest('t', async () => {\n  const a = 1;\n", "tail": "});\n",
        "soft": "  expect.soft(a, '{n}').toBe(1);\n", "hard": "  expect(a, '{n}').toBe(1);\n", "pattern": r"\bexpect\.soft\s*\(",
        "call": "  expectCart(a);\n", "helper_file": "tests/pages.ts",
        "helper": "export function expectCart(n: number) {\n  expect(n).toBe(1);\n}\n", "helper_check": 2,
        "two": "  expect(a).toBe(1); expect(a).toBe(2);\n"},
    "csharp": {
        "file": "tests/T.cs", "node": "tests/T.cs::T.Run",
        "head": "using Xunit;\npublic class T\n{\n    [Fact]\n    public void Run()\n    {\n        var a = 1;\n",
        "tail": "    }\n}\n", "soft": "        Assert.Equal(1, a);  // {n}\n", "hard": "        Assert.True(a > 0);  // {n}\n",
        "pattern": r"Assert\.Equal\b", "call": "        ExpectCart(a);\n", "helper_file": "tests/Pages.cs",
        "helper": "public class Pages\n{\n    public void ExpectCart(int n)\n    {\n        Assert.Equal(1, n);\n    }\n}\n",
        "helper_check": 5, "two": "        Assert.True(a > 0); Assert.True(a > 1);\n"},
    "java": {
        "file": "tests/T.java", "node": "tests/T.java::T.run",
        "head": "class T {\n    @Test\n    void run() {\n        int a = 1;\n", "tail": "    }\n}\n",
        "soft": "        assertEquals(1, a);  // {n}\n", "hard": "        assertTrue(a > 0);  // {n}\n",
        "pattern": r"assertEquals\b", "call": "        expectCart(a);\n", "helper_file": "tests/Pages.java",
        "helper": "class Pages {\n    void expectCart(int n) {\n        assertEquals(1, n);\n    }\n}\n", "helper_check": 3,
        "two": "        assertTrue(a > 0); assertTrue(a > 1);\n"},
}


def world(language: str, kinds: str, soft_row: bool = True, extra: str = ""):
    """(text, spec, reader_entry, keys): the test of `kinds` ("s" soft, "h" hard; one letter per statement, in order), the spec and
    reader entry carrying the soft row (or `[]`), and the key every statement should have. `extra` goes after the statements."""
    fx = LANG[language]
    body = "".join((fx["soft"] if kind == "s" else fx["hard"]).format(n=f"c{number}") for number, kind in enumerate(kinds, 1))
    text = fx["head"] + body + extra + fx["tail"]
    first = fx["head"].count("\n") + 1
    spec = PBC.parse_node(fx["node"])
    reader = PBC._reader_entry(spec)
    patterns = [fx["pattern"]] if soft_row else []
    if reader is None:
        spec = dict(spec, entry=dict(spec["entry"], soft_assert_patterns=patterns))
    else:
        reader = dict(reader, soft_assert_patterns=patterns)
        spec = dict(spec, entry=reader)
    return text, spec, reader, [f"{fx['file']}:{first + index}" for index in range(len(kinds))]


def checks(language: str, kinds: str, soft_row: bool = True, bindings=None, helpers=None, extra: str = ""):
    text, spec, reader, keys = world(language, kinds, soft_row, extra)
    notes: list = []
    return PBC.checks_of(text.encode(), spec, reader, bindings or [], helpers or [], notes), keys, notes, (text, spec, reader)


@pytest.mark.parametrize("language", LANGUAGES)
def test_plan_three_soft_one_run(language):
    listed, keys, _notes, _w = checks(language, "sss")
    assert [c["key"] for c in listed] == keys and all(c["soft"] and c["in_body"] for c in listed), f"{language}: three soft checks listed"
    assert PBC.run_plan(listed) == [{"run": 1, "keys": keys, "why": PBC.run_plan(listed)[0]["why"]}], \
        f"{language}: three non-stopping checks are ONE run"


@pytest.mark.parametrize("language", LANGUAGES)
def test_plan_soft_then_hard_joins_last(language):
    listed, keys, _notes, _w = checks(language, "ssh")
    runs = PBC.run_plan(listed)
    assert [r["keys"] for r in runs] == [keys], f"{language}: a stopping check after a collected group joins it as its LAST: {runs}"
    assert [c["soft"] for c in listed] == [True, True, False], f"{language}: the form row decides which stops"


@pytest.mark.parametrize("language", LANGUAGES)
def test_plan_hard_then_soft_two_runs(language):
    """The owner's case (`:122` stopping, `:128` soft...): the stopping check goes alone, the soft ones follow in the next run."""
    listed, keys, _notes, _w = checks(language, "hss")
    assert [r["keys"] for r in PBC.run_plan(listed)] == [keys[:1], keys[1:]], f"{language}: {PBC.run_plan(listed)}"
    # INV (position): no run holds a stopping check before another check
    by_key = {c["key"]: c for c in listed}
    for run in PBC.run_plan(listed):
        assert all(by_key[k]["soft"] for k in run["keys"][:-1]), f"{language}: a stopping check stands before another in {run}"


@pytest.mark.parametrize("language", LANGUAGES)
def test_plan_chain_of_three_three_runs(language):
    listed, keys, _notes, _w = checks(language, "hhh")
    assert [r["keys"] for r in PBC.run_plan(listed)] == [[k] for k in keys], f"{language}: n stopping links are n runs, never compressed"
    mixed, mixed_keys, _n, _w2 = checks(language, "hhshh")
    assert [r["keys"] for r in PBC.run_plan(mixed)] == [[mixed_keys[0]], [mixed_keys[1]], [mixed_keys[2], mixed_keys[3]],
                                                       [mixed_keys[4]]], f"{language}: a stop closes the group it joins and opens none"


@pytest.mark.parametrize("language", LANGUAGES)
def test_plan_no_soft_row_one_per_check(language):
    """A framework with no soft form is a data row (`[]`): the SAME function plans one run per check, and no branch asks the language."""
    listed, keys, notes, _w = checks(language, "sss", soft_row=False)
    assert not any(c["soft"] for c in listed), f"{language}: with `soft_assert_patterns: []` nothing is soft"
    assert [r["keys"] for r in PBC.run_plan(listed)] == [[k] for k in keys], f"{language}: one run per check"
    assert notes == [], f"{language}: a STATED `[]` carries no note, got {notes!r}"
    # absent key: the same plan, and the note says the row does not say (AR-23)
    text, spec, reader, _keys = world(language, "sss", soft_row=False)
    if reader is None:
        spec = dict(spec, entry=without(spec["entry"], "soft_assert_patterns"))
    else:
        reader = without(reader, "soft_assert_patterns")
        spec = dict(spec, entry=reader)
    said: list = []
    again = PBC.checks_of(text.encode(), spec, reader, [], [], said)
    assert [r["keys"] for r in PBC.run_plan(again)] == [[k] for k in keys] and AD.SOFT_UNSAID in said, f"{language}: {said!r}"


def test_no_language_name_in_checks_of():
    """INV: the list reads no language name - the soft form, the head, the argument are rows (AR-1)."""
    import inspect
    for function in (PBC.checks_of, PBC.run_plan):
        source = inspect.getsource(function)
        assert not re.search(r"""["'](?:python|typescript|csharp|java)["']|\.endswith\(|spec\.get\(["']language|_is_table|\[["']reader["']\]""",
                             source), f"{function.__name__} asks the language"


@pytest.mark.parametrize("language", LANGUAGES)
def test_helper_alone(language):
    """EP-D: a check a binding names in a helper file stands outside the body and runs ALONE, after the body's runs; a helper's check
    that no binding names is not listed and a note counts it."""
    fx = LANG[language]
    helpers = [{"file": fx["helper_file"], "data": fx["helper"].encode(), "hop": True, "chain": False}]
    bound = [{"then": 3, "assertion_ref": f"{fx['helper_file']}:{fx['helper_check']}"}]
    listed, keys, notes, _w = checks(language, "ss", bindings=bound, helpers=helpers, extra=fx["call"])
    assert [c["in_body"] for c in listed] == [True, True, False], f"{language}: {listed}"
    assert listed[2]["key"] == f"{fx['helper_file']}:{fx['helper_check']}" and listed[2]["then"] == 3, f"{language}: {listed[2]}"
    assert [r["keys"] for r in PBC.run_plan(listed)] == [keys, [listed[2]["key"]]], f"{language}: {PBC.run_plan(listed)}"
    assert not any("not listed" in n for n in notes), f"{language}: the helper's check IS named, nothing to count: {notes!r}"
    alone, _k, notes, _w = checks(language, "ss", helpers=helpers, extra=fx["call"])
    assert [c["key"] for c in alone] == keys, f"{language}: a helper's check that no binding names is not listed: {alone}"
    assert any("1 check(s) in helpers the body calls" in n and "no binding names them" in n for n in notes), f"{language}: {notes!r}"


@pytest.mark.parametrize("language", LANGUAGES)
def test_body_without_check_lists_the_hop(language):
    """A body with no check of its own lists the checks of the ONE helper it calls (N5's hop), each alone; two helpers files holding
    the name are not told apart by the name: nothing is listed and a note says so."""
    fx = LANG[language]
    hop = {"file": fx["helper_file"], "data": fx["helper"].encode(), "hop": True, "chain": False}
    listed, _keys, notes, _w = checks(language, "", helpers=[hop], extra=fx["call"])
    assert [(c["key"], c["in_body"]) for c in listed] == [(f"{fx['helper_file']}:{fx['helper_check']}", False)], f"{language}: {listed}"
    assert any("one hop out" in n for n in notes), f"{language}: {notes!r}"
    twin = dict(hop, file="tests/other" + fx["helper_file"][fx["helper_file"].rindex("."):])
    listed, _keys, notes, _w = checks(language, "", helpers=[hop, twin], extra=fx["call"])
    assert listed == [] and any("not told by the name" in n for n in notes), f"{language}: {listed} {notes!r}"
    listed, _keys, notes, _w = checks(language, "", helpers=[], extra=fx["call"])
    assert listed == [] and any("holds no check and none of the helpers" in n for n in notes), f"{language}: {notes!r}"


@pytest.mark.parametrize("language", ["python", "typescript"])
def test_hop_of_checks_of_is_find_oracles_core(language, tmp_path):
    """AR-13: the hop is ONE function (`pick_hop`). The same fixture through `find_oracle` on disk and through `checks_of` with the
    sources supplied names the same helper and the same check line: a helper in the test's own file, and (AST reader) one in a conftest
    of the chain. An ambiguity is a refusal in the one and a note in the other, from the same verdict."""
    fx = LANG[language]
    own_helper = "\n\ndef expect_cart(n):\n    assert n == 1\n" if language == "python" else \
        "function expectCart(n: number) {\n  expect(n).toBe(1);\n}\n"
    text, spec, reader, _keys = world(language, "", extra=fx["call"])
    text += own_helper
    path = tmp_path / fx["file"]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    found, _note = PBC.find_oracle(text, spec, path, tmp_path, [], reader, {"tests_root": "tests"})
    notes: list = []
    listed = PBC.checks_of(text.encode(), spec, reader, [], [], notes)
    assert found is not None and [c["line"] for c in listed] == [found[3]] and listed[0]["file"] == fx["file"], f"{language}: {found} {listed}"
    assert [c["in_body"] for c in listed] == [False], f"{language}: the hop's check is outside the body"
    if language != "python":
        return
    conftest = tmp_path / "tests" / "conftest.py"
    conftest.write_text("def expect_cart(n):\n    assert n == 1\n", encoding="utf-8")
    bare, spec_b, _r, _k = world("python", "", extra=fx["call"])
    path.write_text(bare, encoding="utf-8")
    found, _note = PBC.find_oracle(bare, spec_b, path, tmp_path, [conftest], None, {"tests_root": "tests"})
    held = [{"file": "tests/conftest.py", "data": conftest.read_bytes(), "hop": True, "chain": True}]
    listed = PBC.checks_of(bare.encode(), spec_b, None, [], held, [])
    assert found[0] == conftest and [(c["file"], c["line"]) for c in listed] == [("tests/conftest.py", found[3])], f"{found} {listed}"
    # the same name holding a check in two files: a refusal for the probe, a note for the list - one verdict
    other = tmp_path / "tests" / "extra.py"
    other.write_text("def expect_cart(n):\n    assert n == 2\n", encoding="utf-8")
    both = [{"file": "tests/conftest.py", "data": conftest.read_bytes(), "hop": True, "chain": False},
            {"file": "tests/extra.py", "data": other.read_bytes(), "hop": True, "chain": False}]
    notes = []
    assert PBC.checks_of(bare.encode(), spec_b, None, [], both, notes) == [] and any("not told by the name" in n for n in notes), notes
    own = PBC._Hop(path, bare, None, fx["file"], "python")
    twin = [PBC._Hop(conftest, conftest.read_text(encoding="utf-8"), None, "tests/conftest.py", "python"),
            PBC._Hop(other, other.read_text(encoding="utf-8"), None, "tests/extra.py", "python")]
    assert PBC.pick_hop(own.test_unit(spec_b), [own] + twin, lambda h: False)[0] == "files"


@pytest.mark.parametrize("language", LANGUAGES)
def test_two_heads_one_line_keys(language):
    """EP-O: two heads on one line get distinct keys, `<file>:<line>` and `<file>:<line>#2`, by head order; each is on the plan."""
    fx = LANG[language]
    listed, _keys, _notes, (text, _spec, _reader) = checks(language, "", soft_row=False, extra=fx["two"])
    line = fx["head"].count("\n") + 1
    assert [c["key"] for c in listed] == [f"{fx['file']}:{line}", f"{fx['file']}:{line}#2"], f"{language}: {listed}"
    assert len({c["statement_sha"] for c in listed}) == 2, f"{language}: the two statements differ, so do their shas"
    assert [r["keys"] for r in PBC.run_plan(listed)] == [[c["key"]] for c in listed], f"{language}: the second is on the plan, owed"


@pytest.mark.parametrize("language", LANGUAGES)
def test_binding_on_blank_line_note(language):
    """Arm B's real case: a binding one line above the checks (`:46`, a blank line) gives no check and a note; `:47` and `:48` label
    their checks, and the third check (`:49`) has no Then (`then: null`)."""
    fx = LANG[language]
    first = fx["head"].count("\n") + 1          # the blank line; the statements stand on first+1 .. first+3
    spaced = fx["head"] + "\n" + "".join(fx["soft"].format(n=f"c{n}") for n in (1, 2, 3)) + fx["tail"]
    spec = PBC.parse_node(fx["node"])
    reader = PBC._reader_entry(spec)
    refs = [{"then": 1, "assertion_ref": f"{fx['file']}:{first}"}, {"then": 2, "assertion_ref": f"{fx['file']}:{first + 1}"},
            {"then": 3, "assertion_ref": f"{fx['file']}:{first + 2}"}]
    notes: list = []
    listed = PBC.checks_of(spaced.encode(), spec, reader, refs, [], notes)
    assert [(c["line"], c["then"]) for c in listed] == [(first + 1, 2), (first + 2, 3), (first + 3, None)], f"{language}: {listed}"
    assert f"binding `:{first}` holds no check" in notes, f"{language}: {notes!r}"
    assert len(listed) == 3, f"{language}: a binding on a blank line adds no check"


def snapshot(folder: Path) -> dict:
    return {str(p.relative_to(folder)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(folder.rglob("*")) if p.is_file()}


def plan_project(tmp_path: Path, monkeypatch):
    """(project, task): a TypeScript test of three checks (`hss`) with one binding, the probe's roots pointed at it."""
    fx = LANG["typescript"]
    project, task = tmp_path / "proj", tmp_path / "task"
    (project / "tests").mkdir(parents=True)
    (task / "work").mkdir(parents=True)
    (project / fx["file"]).write_text(world("typescript", "hss")[0], encoding="utf-8")
    (task / "work" / "automation-manifest.json").write_text(json.dumps({
        "tests": [{"instance_id": "i1", "case": "TC-1", "covers": ["TC-1"], "file": fx["file"]}],
        "then_bindings": [{"case": "TC-1", "then": 1, "instance_id": "i1", "status": "covered", "assertion_ref": f"{fx['file']}:4"}]}),
        encoding="utf-8")
    monkeypatch.setattr(PBC, "project_root", lambda *a, **k: project)
    monkeypatch.setattr(PBC, "load_config", lambda *a, **k: {"tests_root": "tests"})
    monkeypatch.setattr(PBC, "story_root", lambda *a, **k: str(task))
    monkeypatch.setattr(PBC, "artifacts_dir", lambda *a, **k: task)
    monkeypatch.setattr(PBC, "_test_path", lambda root, cfg, spec, entry=None: (root / spec["file"], root))
    return project, task


def test_plan_names_ignored_flags(tmp_path, monkeypatch, capsys):
    """A flag `--plan` does not use is never dropped in silence: one note per flag, in the JSON and in the text; none given, no such
    note; exit 0 either way (the plan is pure, nothing is refused)."""
    fx = LANG["typescript"]
    plan_project(tmp_path, monkeypatch)
    base = ["--plan", "--task", "T-1", "--instance", "i1", "--test", f"{fx['file']}::t"]

    def run(extra: list, as_json: bool):
        monkeypatch.setattr(sys, "argv", ["probe_by_code.py"] + base + extra + (["--json"] if as_json else []))
        args = PBC._build_parser().parse_args(base + extra + (["--json"] if as_json else []))
        with pytest.raises(SystemExit) as stop:
            PBC._plan_cli(args)
        assert stop.value.code == 0
        return capsys.readouterr().out

    def said(out: str, as_json: bool) -> list:
        lines = json.loads(out)["notes"] if as_json else [ln[len("note: "):] for ln in out.splitlines() if ln.startswith("note: ")]
        return [n for n in lines if n.startswith("--plan lists and plans only")]

    for as_json in (True, False):
        assert said(run([], as_json), as_json) == [], f"json={as_json}: no flag, no note"
        assert said(run(["--at", "5"], as_json), as_json) == ["--plan lists and plans only: --at was not used"], f"json={as_json}"
        many = said(run(["--at", "5", "--oracle", "x", "--dispatch", "d1", "--mutation", "invert"], as_json), as_json)
        assert many == [f"--plan lists and plans only: {flag} was not used" for flag in ("--at", "--oracle", "--mutation")], \
            f"json={as_json}: {many}"      # `--dispatch` is USED since fix round E (F13): it names the model file the plan prints


def test_plan_prints_the_shape_the_doors_and_the_run_count(tmp_path, monkeypatch, capsys):
    """F13 (t-2490, AR-10, FR-38): the critic learns the entry shape and the size of the plan BEFORE the work. `--plan` (text and `--json`)
    carries the model file of the dispatch (a template when none is given), `MODELS_SHAPE` (the constant `_models_refusal` prints), the doors
    of each check (the same `_door_items`) and `plan_runs`; it writes nothing (the tree is the same bytes after) and no existing key moved.
    Killed by: a `--plan` without `models_shape` or `doors` (the shape reaches the critic only through the refusal, after the work), a
    `plan_runs` that is not the number of rows of `plan`, or a copy of the shape text instead of the constant."""
    fx = LANG["typescript"]
    project, task = plan_project(tmp_path, monkeypatch)
    base = ["--plan", "--task", "T-1", "--instance", "i1", "--test", f"{fx['file']}::t"]

    def run(extra: list, as_json: bool) -> str:
        argv = base + extra + (["--json"] if as_json else [])
        monkeypatch.setattr(sys, "argv", ["probe_by_code.py"] + argv)
        with pytest.raises(SystemExit) as stop:
            PBC._plan_cli(PBC._build_parser().parse_args(argv))
        assert stop.value.code == 0
        return capsys.readouterr().out

    tree = (snapshot(project), snapshot(task))
    report = json.loads(run(["--dispatch", "D7"], True))
    assert report["model_file"] == "work/probe-models/D7.json" and report["models_shape"] == PBC.MODELS_SHAPE, report
    assert report["plan_runs"] == len(report["plan"]) == 2, report
    assert [c["key"] for c in report["checks"]] == [f"{fx['file']}:{n}" for n in (4, 5, 6)] and all(c["doors"] for c in report["checks"]), report["checks"]
    assert all(set(c["doors"]) <= set(PBC.MODEL_KINDS) and "not_here" in c["doors"] for c in report["checks"]), report["checks"]
    assert {"checks", "plan", "notes"} <= set(report) and "key" in report["checks"][0] and "line" in report["checks"][0]
    assert json.loads(run([], True))["model_file"] == "work/probe-models/<dispatch id>.json", "no dispatch: the template, never a guess"
    text = run(["--dispatch", "D7"], False)
    assert text.count("model file: work/probe-models/D7.json") == 1 and text.count("entry shape: " + PBC.MODELS_SHAPE) == 1, text
    assert "plan_runs: 2" in text and all(f"doors of {c['key']} (line {c['line']}): {', '.join(c['doors'])}" in text for c in report["checks"]), text
    assert (snapshot(project), snapshot(task)) == tree, "`--plan` changed a file"


def test_plan_writes_nothing(tmp_path, monkeypatch, capsys):
    """The pure functions leave their arguments as they were, and `--plan` reads a project, prints, and writes, runs and locks nothing."""
    import copy
    import subprocess
    for language in LANGUAGES:
        text, spec, reader, _keys = world(language, "hss")
        before = copy.deepcopy((text, spec, reader))
        listed = PBC.checks_of(text.encode(), spec, reader, [{"then": 1, "assertion_ref": "nowhere:1"}], [])
        frozen = copy.deepcopy(listed)
        PBC.run_plan(listed)
        assert listed == frozen and (text, spec, reader) == before, f"{language}: an argument changed"
    fx = LANG["typescript"]
    project, task = plan_project(tmp_path, monkeypatch)

    def forbidden(*a, **k):
        raise AssertionError("`--plan` must write, run and lock nothing")

    for name in ("atomic_json", "claim_key", "os_try_lock", "begin_copy", "put_back"):
        if hasattr(PBC, name):
            monkeypatch.setattr(PBC, name, forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    tree = (snapshot(project), snapshot(task))
    args = PBC._build_parser().parse_args(["--plan", "--task", "T-1", "--instance", "i1", "--test", f"{fx['file']}::t", "--json"])
    with pytest.raises(SystemExit) as stop:
        PBC._plan_cli(args)
    assert stop.value.code == 0
    report = json.loads(capsys.readouterr().out)
    assert [c["key"] for c in report["checks"]] == [f"{fx['file']}:4", f"{fx['file']}:5", f"{fx['file']}:6"], report
    assert [r["keys"] for r in report["plan"]] == [[f"{fx['file']}:4"], [f"{fx['file']}:5", f"{fx['file']}:6"]], report
    assert report["checks"][0]["then"] == 1 and report["checks"][1]["then"] is None, report
    assert (snapshot(project), snapshot(task)) == tree, "`--plan` changed a file"


# Arm B's TC_019 (`add_to_cart.spec.ts:117-139`, MyBooks): the real statements, verbatim, under a plain title (the real one is a template
# string; the title is the declaration's business, not the checks').
ARM_B_TC019 = """import { test, expect } from '@playwright/test';
test.describe('failed add from the catalog card is not reported as success (R-1)', () => {
  for (const how of failures) {
    test('LOCAL-1_TC_019 failed POST /api/cart', async ({ page, admin, books }) => {
      const A = await admin.createBook(10);
      books.push(A);
      const catalog = new CatalogPage(page);
      await catalog.open(await titleOf(admin, A));
      await expect(catalog.cartBadge, 'step 1: badge empty before the add').toHaveCount(0);
      await failCall(page, 'POST', /^\\/api\\/cart$/, how);

      await catalog.clickAdd(A);

      // independent Thens first: a red error-toast assert stops the test
      await expect.soft(catalog.cartBadge, 'Then 2: badge stays 0').toHaveCount(0);
      expect.soft(await guestCart(page), 'Then 2: GET /api/cart holds no line').toEqual({});
      await expect.soft(catalog.successToast, 'Then 1: no success message after the failed add').toHaveCount(0);
      await expect.soft(catalog.errorToast, 'Then 1: an error text is shown').toBeVisible();

      await expect.soft(catalog.card(A), 'Then 3: the catalog list is still shown').toBeVisible();
      await page.unrouteAll({ behavior: 'ignoreErrors' });
      await expect.soft(catalog.addButton(A), 'Then 3: Add is enabled again').toBeEnabled();
      await catalog.clickAdd(A);
      await expect.soft(catalog.cartBadge, 'Then 3: Add works again, badge reads 1').toHaveText('1');
    });
  }
});
"""


def test_list_is_arm_b_tc019():
    """The worked example of §11.8: eight checks, `:122` (here the 9th line) stopping and the rest soft, two runs, and `then` by binding."""
    spec = PBC.parse_node("tests/e2e/cart/add_to_cart.spec.ts::LOCAL-1_TC_019 failed POST /api/cart")
    reader = PBC._reader_entry(spec)
    rows = [{"then": 2, "assertion_ref": "tests/e2e/cart/add_to_cart.spec.ts:15-16"},
            {"then": 1, "assertion_ref": "tests/e2e/cart/add_to_cart.spec.ts:17-18"},
            {"then": 3, "assertion_ref": "tests/e2e/cart/add_to_cart.spec.ts:20-24"}]
    notes: list = []
    listed = PBC.checks_of(ARM_B_TC019.encode(), spec, reader, rows, [], notes)
    name = "tests/e2e/cart/add_to_cart.spec.ts"
    assert [c["key"] for c in listed] == [f"{name}:{n}" for n in (9, 15, 16, 17, 18, 20, 22, 24)], listed
    assert [c["soft"] for c in listed] == [False] + [True] * 7 and all(c["in_body"] for c in listed), listed
    assert [c["then"] for c in listed] == [None, 2, 2, 1, 1, 3, 3, 3], [c["then"] for c in listed]
    runs = PBC.run_plan(listed)
    assert [r["keys"] for r in runs] == [[f"{name}:9"], [f"{name}:{n}" for n in (15, 16, 17, 18, 20, 22, 24)]], runs
    assert notes == [], notes


@pytest.mark.parametrize("language", LANGUAGES)
def test_statement_sha_ignores_whitespace(language):
    """`statement_sha` is the sha of the statement with its whitespace folded: re-spaced bytes give the same sha, a changed expected
    value another one (EP-U: a stored edit is never joined to a check whose expected value changed)."""
    fx = LANG[language]
    plain = fx["soft"].format(n="x")
    respaced = plain.replace(" == ", "   ==   ") if language == "python" else plain.replace(", ", ",\n        ", 1)
    changed_value = plain.replace("== 1", "== 2") if language == "python" else plain.replace("1", "2", 1)
    assert respaced != plain and changed_value != plain, f"{language}: the variants must differ from the original"
    _text, spec, reader, _keys = world(language, "")
    for changed, same in ((changed_value, False), (respaced, True)):
        other = fx["head"] + changed + fx["tail"]
        first = PBC.checks_of((fx["head"] + plain + fx["tail"]).encode(), spec, reader, [], [])
        second = PBC.checks_of(other.encode(), spec, reader, [], [])
        assert len(first) == len(second) == 1, f"{language}: {first} {second}"
        assert (first[0]["statement_sha"] == second[0]["statement_sha"]) is same, f"{language}: same={same}: {changed!r}"
        assert re.fullmatch(r"[0-9a-f]{64}", first[0]["statement_sha"])


# --- t-2064 P1b: soft SCOPES (a bracketed region whose checks do not stop one another) -------------------------------------------
# One fixture per FRAMEWORK that has a row (the id names it in a red): `scope(k)` is one scope of k message-less checks, `nested` a scope
# of four checks whose second and third stand in an inner scope, `empty` a scope that holds no check of a known form, `hard` one plain
# check, `word` what a check line holds (the lines of the checks are read from the text, never typed). The forms were run on samples
# (t-2064-p1b-report.md): each scope throws what its checks recorded where it CLOSES, so nothing after it ran.
THEN_LINE = "            softly.assertThat(a).isEqualTo(1);\n"
SCOPES = {
    "java-junit": {
        "file": "tests/T.java", "node": "tests/T.java::T.run", "word": "assertEquals(", "hard": "        assertEquals(1, a);\n",
        "head": "import static org.junit.jupiter.api.Assertions.*;\nclass T {\n    @Test\n    void run() {\n        int a = 1;\n",
        "tail": "    }\n}\n", "opener": "assertAll(", "fake": ("bundle(", r"\bbundle\s*\("), "at_reaches": False, "bare": "assertAll",
        "scope": lambda k: "        assertAll(\n" + ",\n".join(["            () -> assertEquals(1, a)"] * k) + "\n        );\n",
        "nested": "        assertAll(\n            () -> assertEquals(1, a),\n            () -> assertAll(\n"
                  "                () -> assertEquals(1, a),\n                () -> assertEquals(1, a)),\n"
                  "            () -> assertEquals(1, a)\n        );\n",
        "empty": "        assertAll(() -> helper(a), () -> other(a));\n"},
    "java-assertj": {
        "file": "tests/T.java", "node": "tests/T.java::T.run", "word": "assertThat(", "hard": "        assertThat(a).isEqualTo(1);\n",
        "head": "import static org.assertj.core.api.SoftAssertions.assertSoftly;\nclass T {\n    @Test\n    void run() {\n        int a = 1;\n",
        "tail": "    }\n}\n", "opener": "assertSoftly(", "fake": ("bundle(", r"\bbundle\s*\("), "at_reaches": True, "bare": "assertSoftly",
        "scope": lambda k: "        assertSoftly(softly -> {\n" + THEN_LINE * k + "        });\n",
        "nested": "        assertSoftly(softly -> {\n" + THEN_LINE + "            assertSoftly(inner -> {\n"
                  "                inner.assertThat(a).isEqualTo(1);\n                inner.assertThat(a).isEqualTo(1);\n"
                  "            });\n" + THEN_LINE + "        });\n",
        "empty": "        assertSoftly(softly -> {\n            helper(softly, a);\n        });\n"},
    "java-assertj-try": {
        "file": "tests/T.java", "node": "tests/T.java::T.run", "word": "assertThat(", "hard": "        assertThat(a).isEqualTo(1);\n",
        "head": "class T {\n    @Test\n    void run() {\n        int a = 1;\n", "tail": "    }\n}\n",
        "opener": "try (AutoCloseableSoftAssertions softly = new AutoCloseableSoftAssertions()) {",
        "fake": ("bundle {", r"\bbundle\s*\{"), "at_reaches": True, "bare": "AutoCloseableSoftAssertions",
        "scope": lambda k: "        try (AutoCloseableSoftAssertions softly = new AutoCloseableSoftAssertions()) {\n" + THEN_LINE * k + "        }\n",
        "nested": "        try (AutoCloseableSoftAssertions softly = new AutoCloseableSoftAssertions()) {\n" + THEN_LINE
                  + "            try (AutoCloseableSoftAssertions inner = new AutoCloseableSoftAssertions()) {\n"
                  "                inner.assertThat(a).isEqualTo(1);\n                inner.assertThat(a).isEqualTo(1);\n            }\n"
                  + THEN_LINE + "        }\n",
        "empty": "        try (AutoCloseableSoftAssertions softly = new AutoCloseableSoftAssertions()) {\n            helper(softly, a);\n        }\n"},
    "csharp-nunit": {
        "file": "tests/T.cs", "node": "tests/T.cs::T.Run", "word": "Assert.That(", "hard": "        Assert.That(a, Is.EqualTo(1));\n",
        "head": "using NUnit.Framework;\npublic class T\n{\n    [Test]\n    public void Run()\n    {\n        var a = 1;\n",
        "tail": "    }\n}\n", "opener": "Assert.Multiple(", "fake": ("bundle(", r"\bbundle\s*\("), "at_reaches": True, "bare": "Multiple",
        "scope": lambda k: "        Assert.Multiple(() =>\n        {\n" + "            Assert.That(a, Is.EqualTo(1));\n" * k + "        });\n",
        "nested": "        Assert.Multiple(() =>\n        {\n            Assert.That(a, Is.EqualTo(1));\n"
                  "            Assert.Multiple(() =>\n            {\n                Assert.That(a, Is.EqualTo(1));\n"
                  "                Assert.That(a, Is.EqualTo(1));\n            });\n            Assert.That(a, Is.EqualTo(1));\n        });\n",
        "empty": "        Assert.Multiple(() =>\n        {\n            Helper(a);\n        });\n"},
}
# Round 2 (t-2273): the scopes that end at a CALL, not at a bracket (a row with `closes`). The same keys as above, plus: `bracket` False (no
# unbalanced-source test applies), `member` (the line of one member, and `hard_in` the stopping line that replaces one), `declare(name)` /
# `close(name)` (the lines that open and close a variable `name`), `after(name)` (a call on the variable after it is closed), `marker` False
# where the form's message variants do not apply to this library (the marker goes by the existing door), `nested_runs` (the runs of the
# nested fixture, by member index: variable scopes are never merged, so an inner variable is a scope of its own).
VAR_MEMBER = "            softly.assertThat(a).isEqualTo(1);\n"
TESTNG_MEMBER = "            sa.assertEquals(a, 1);\n"
SCOPES["java-assertj-var"] = {
    "file": "tests/T.java", "node": "tests/T.java::T.run", "word": "assertThat(", "hard": "        assertThat(a).isEqualTo(1);\n",
    "head": "import static org.assertj.core.api.Assertions.assertThat;\nimport org.assertj.core.api.SoftAssertions;\nclass T {\n    @Test\n    void run() {\n        int a = 1;\n",
    "tail": "    }\n}\n", "opener": "SoftAssertions softly = new SoftAssertions();", "fake": ("Bundle softly = new Bundle();", r"(?P<var>\w+)\s*=\s*new\s+Bundle\s*\(\s*\)\s*;"),
    "at_reaches": True, "bare": "SoftAssertions", "bracket": False, "member": VAR_MEMBER, "hard_in": "            assertThat(a).isEqualTo(1);\n",
    "declare": lambda v: f"        SoftAssertions {v} = new SoftAssertions();\n", "close": lambda v: f"        {v}.assertAll();\n",
    "after": lambda v: f"        {v}.assertThat(a).isEqualTo(1);\n", "member_of": lambda v: f"            {v}.assertThat(a).isEqualTo(1);\n",
    "scope": lambda k: "        SoftAssertions softly = new SoftAssertions();\n" + VAR_MEMBER * k + "        softly.assertAll();\n",
    "nested": "        SoftAssertions softly = new SoftAssertions();\n" + VAR_MEMBER + "        SoftAssertions inner = new SoftAssertions();\n"
              "            inner.assertThat(a).isEqualTo(1);\n            inner.assertThat(a).isEqualTo(1);\n        inner.assertAll();\n"
              + VAR_MEMBER + "        softly.assertAll();\n",
    "nested_runs": [[0], [1, 2], [3]],
    "empty": "        SoftAssertions softly = new SoftAssertions();\n            helper(softly, a);\n        softly.assertAll();\n"}
SCOPES["java-testng"] = {
    "file": "tests/T.java", "node": "tests/T.java::T.run", "word": "assertEquals(", "hard": "        assertEquals(a, 1);\n",
    "head": "import static org.testng.Assert.assertEquals;\nimport org.testng.asserts.SoftAssert;\nclass T {\n    @Test\n    void run() {\n        int a = 1;\n",
    "tail": "    }\n}\n", "opener": "SoftAssert sa = new SoftAssert();", "fake": ("Bundle sa = new Bundle();", r"(?P<var>\w+)\s*=\s*new\s+Bundle\s*\(\s*\)\s*;"),
    "at_reaches": True, "bare": "SoftAssert", "bracket": False, "member": TESTNG_MEMBER, "hard_in": "            assertEquals(a, 1);\n", "marker": False,
    "declare": lambda v: f"        SoftAssert {v} = new SoftAssert();\n", "close": lambda v: f"        {v}.assertAll();\n",
    "after": lambda v: f"        {v}.assertEquals(a, 1);\n", "member_of": lambda v: f"            {v}.assertEquals(a, 1);\n",
    "scope": lambda k: "        SoftAssert sa = new SoftAssert();\n" + TESTNG_MEMBER * k + "        sa.assertAll();\n",
    "nested": "        SoftAssert sa = new SoftAssert();\n" + TESTNG_MEMBER + "        SoftAssert inner = new SoftAssert();\n"
              "            inner.assertEquals(a, 1);\n            inner.assertEquals(a, 1);\n        inner.assertAll();\n"
              + TESTNG_MEMBER + "        sa.assertAll();\n",
    "nested_runs": [[0], [1, 2], [3]],
    "empty": "        SoftAssert sa = new SoftAssert();\n            helper(sa, a);\n        sa.assertAll();\n"}
SCOPES["java-assertj"].update(member=THEN_LINE, hard_in="            assertThat(a).isEqualTo(1);\n")
FRAMEWORKS = tuple(SCOPES)
BRACKETED = tuple(f for f in SCOPES if SCOPES[f].get("bracket", True))
VARIABLES = tuple(f for f in SCOPES if not SCOPES[f].get("bracket", True))


def scope_world(framework: str, body: str, scope_rows=...):
    """(text, listed, notes, spec, reader): the test of this framework with `body` between its head and tail, listed by `checks_of`.
    `scope_rows` replaces the entry's `soft_scopes` (a list; `None` takes the key OUT; the default keeps the shipped rows)."""
    fx = SCOPES[framework]
    text = fx["head"] + body + fx["tail"]
    spec = PBC.parse_node(fx["node"])
    reader = PBC._reader_entry(spec)
    if scope_rows is None:
        reader = without(reader, "soft_scopes")
    elif scope_rows is not ...:
        reader = dict(reader, soft_scopes=scope_rows)
    spec = dict(spec, entry=reader)
    notes: list = []
    return text, PBC.checks_of(text.encode(), spec, reader, [], [], notes), notes, spec, reader


def check_lines(framework: str, text: str) -> list:
    """The 1-based lines of `text` that hold a check of this framework (read from the text, so no fixture types a line number)."""
    return [number for number, line in enumerate(text.splitlines(), 1) if SCOPES[framework]["word"] in line]


def keys_of(framework: str, text: str) -> list:
    return [f"{SCOPES[framework]['file']}:{n}" for n in check_lines(framework, text)]


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_scope_checks_do_not_stop(framework):
    """Every check inside the scope is its own listed check, non-stopping, in ONE run; the scope's opening is not a check; and the
    entry's `soft_assert_patterns` is still `[]` - the SCOPE row decided, not a soft head."""
    fx = SCOPES[framework]
    text, listed, notes, _spec, reader = scope_world(framework, fx["scope"](3))
    keys = keys_of(framework, text)
    assert len(keys) == 3 and [c["key"] for c in listed] == keys, f"{framework}: the opening is no check, the three members are: {listed}"
    assert all(c["soft"] and c["in_body"] and c["scope"] for c in listed), f"{framework}: {listed}"
    assert len({c["scope"] for c in listed}) == 1, f"{framework}: one scope, one id: {listed}"
    assert reader["soft_assert_patterns"] == [] and notes == [], f"{framework}: {notes!r}"
    assert [r["keys"] for r in PBC.run_plan(listed)] == [keys], f"{framework}: three non-stopping checks are ONE run"
    # the control: with the row taken out the same bytes are the plain read - the members stop, one run each
    _t, plain, _n, _s, _r = scope_world(framework, fx["scope"](3), scope_rows=[])
    assert not any(c["soft"] or c["scope"] for c in plain), f"{framework}: without the row nothing is soft: {plain}"
    assert [c["key"] for c in plain if c["key"] in keys] == keys, f"{framework}: the members are still listed without the row"
    # a stopping check INSIDE the scope (a static assertThat in assertSoftly) is not the scope's soft one, and never joins a run
    if "hard_in" in fx:
        inner = fx["scope"](2).replace(fx["member"], fx["hard_in"], 1)
        t2, mixed, _n2, _s2, _r2 = scope_world(framework, inner)
        lines = check_lines(framework, t2)
        assert [(c["soft"], bool(c["scope"])) for c in mixed] == [(False, True), (True, True)], f"{framework}: {mixed}"
        assert [r["keys"] for r in PBC.run_plan(mixed)] == [[f"{fx['file']}:{lines[0]}"], [f"{fx['file']}:{lines[1]}"]], \
            f"{framework}: a hard check inside a scope runs alone"


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_check_after_scope_stops(framework):
    """INV: a row never makes a stopping check soft outside its scope. A check after the scope closes stops as written and does not join
    the scope's run (the scope's end throws what it recorded: measured, nothing after it ran); a check before it runs alone; two scopes
    in a row are two runs."""
    fx = SCOPES[framework]
    text, listed, _notes, _s, _r = scope_world(framework, fx["scope"](2) + fx["hard"])
    keys = keys_of(framework, text)
    assert [(c["soft"], c["scope"] is not None) for c in listed] == [(True, True), (True, True), (False, False)], f"{framework}: {listed}"
    assert [r["keys"] for r in PBC.run_plan(listed)] == [keys[:2], keys[2:]], f"{framework}: {PBC.run_plan(listed)}"
    text, listed, _n, _s, _r = scope_world(framework, fx["hard"] + fx["scope"](2))
    keys = keys_of(framework, text)
    assert [r["keys"] for r in PBC.run_plan(listed)] == [keys[:1], keys[1:]], f"{framework}: a check before the scope runs alone"
    assert listed[0]["soft"] is False and listed[0]["scope"] is None, f"{framework}: {listed[0]}"
    text, listed, _n, _s, _r = scope_world(framework, fx["scope"](2) + fx["scope"](2))
    keys = keys_of(framework, text)
    assert listed[0]["scope"] != listed[2]["scope"], f"{framework}: two scopes are two ids: {listed}"
    assert [r["keys"] for r in PBC.run_plan(listed)] == [keys[:2], keys[2:]], f"{framework}: a scope's end is a stop, so two scopes are two runs"


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_scope_markers_differ(framework):
    """Each check inside a scope has its own key and its own marker, entered through the form's own message argument (the owner's word,
    Q4): the keys differ, every member's form carries a message variant, and the plan's edit of each member puts ITS token in ITS OWN
    statement and nowhere else. Where `--at` cannot reach a member (see `at_reaches`) the door is pinned instead of the marker."""
    import difflib
    fx = SCOPES[framework]
    text, listed, _notes, spec, _reader = scope_world(framework, fx["scope"](3))
    assert len({c["key"] for c in listed}) == 3 and all(c["has_message"] for c in listed), f"{framework}: {listed}"
    markers = []
    for check in listed:
        token = "tok%09d" % check["line"]
        if not fx["at_reaches"]:
            # JUnit's `assertAll(` is itself a head (a form with no inversion) whose statement spans its members, so the line of a member
            # names IT first: the edit refuses and the member goes by the existing door (a model or the critic). A finding for the walk.
            with pytest.raises(PBC.Refusal) as refusal:
                PBC.plan_detector_mutation(text.encode(), spec, "i1", at=check["line"], marker_token=token)
            assert "assertAll(" in str(refusal.value), f"{framework}: {refusal.value}"
            continue
        data, detail, _context = PBC.plan_detector_mutation(text.encode(), spec, "i1", at=check["line"], marker_token=token)
        if fx.get("marker", True):
            assert detail["message_marker"] == "qa-probe-" + token and detail["message_form"], f"{framework}: {detail}"
            assert token in detail["statement_after"], f"{framework}: the marker stands in the member's own statement"
        else:   # the form's message variants are gated on another library's import: no marker here, the existing door (a model or the critic)
            assert not detail["message_marker"] and token not in detail["statement_after"], f"{framework}: {detail}"
        edits = [op for op in difflib.SequenceMatcher(None, text.splitlines(), data.decode().splitlines()).get_opcodes() if op[0] != "equal"]
        changed = {n for _tag, i1, i2, _j1, _j2 in edits for n in range(i1 + 1, i2 + 1)}
        assert changed and all(check["line"] <= n <= check["end_line"] for n in changed), f"{framework}: edit outside its check {changed}"
        markers.append(detail["statement_after"])
    if fx["at_reaches"] and fx.get("marker", True):
        assert len(set(markers)) == 3, f"{framework}: each check has its own marker text: {markers}"


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_nested_scope_one_group(framework):
    """A nested scope: the OUTER one decides - one scope id, one run, and neither scope's opening is a check."""
    fx = SCOPES[framework]
    text, listed, notes, _s, _r = scope_world(framework, fx["nested"])
    keys = keys_of(framework, text)
    assert len(keys) == 4 and [c["key"] for c in listed] == keys, f"{framework}: {listed}"
    assert all(c["soft"] for c in listed) and notes == [], f"{framework}: {listed} {notes!r}"
    if framework in VARIABLES:
        # a variable opened inside another's range is a scope of its own, never merged (each throws at its own closing call): the inner
        # members are one run, the outer's members around them are one each
        assert len({c["scope"] for c in listed}) == 2 and listed[1]["scope"] == listed[2]["scope"] != listed[0]["scope"] == listed[3]["scope"], \
            f"{framework}: {listed}"
        assert [r["keys"] for r in PBC.run_plan(listed)] == [[keys[i] for i in run] for run in fx["nested_runs"]], f"{framework}: {PBC.run_plan(listed)}"
        return
    assert len({c["scope"] for c in listed}) == 1, f"{framework}: the outer decides: {listed}"
    assert [r["keys"] for r in PBC.run_plan(listed)] == [keys], f"{framework}: one group"


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_no_scope_row_plain_plan(framework):
    """No `soft_scopes` key and `soft_scopes: []` give the same list and the same plan - the plain one, a run per check, nothing soft
    (AR-23); a row that does not compile or does not end on a bracket is no scope and a note says so, never an exception."""
    fx = SCOPES[framework]
    body = fx["scope"](2) + fx["hard"]
    absent_text, absent, absent_notes, _s, _r = scope_world(framework, body, scope_rows=None)
    _t, empty, empty_notes, _s2, _r2 = scope_world(framework, body, scope_rows=[])
    assert absent == empty and absent_notes == empty_notes == [], f"{framework}: {absent} {absent_notes!r}"
    assert not any(c["soft"] or c["scope"] for c in absent), f"{framework}: {absent}"
    assert all(len(r["keys"]) == 1 for r in PBC.run_plan(absent)), f"{framework}: a run per check"
    assert set(keys_of(framework, absent_text)) <= {c["key"] for c in absent}, f"{framework}: every check is still listed"
    _t, broken, notes, _s3, _r3 = scope_world(framework, body, scope_rows=[{"opens": "(unclosed"}])
    assert broken == absent and any("not read" in n and "soft_scopes[0]" in n for n in notes), f"{framework}: {notes!r}"
    _t, bare, notes, _s4, _r4 = scope_world(framework, body, scope_rows=[{"opens": r"\b" + fx["bare"] + r"\b"}])
    assert all(not c["soft"] and not c["scope"] for c in bare), f"{framework}: a row that ends on no bracket is no scope: {bare}"
    assert any("does not end on an opening bracket" in n and "line " in n for n in notes), f"{framework}: {notes!r}"


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_empty_scope_is_an_unknown_head(framework):
    """EP-P: a scope that holds no check of a known form is no soft group; a note names its line, and what the table read before is
    still read (JUnit's `assertAll(` is a head of a form with no inversion: it stays listed, stopping)."""
    fx = SCOPES[framework]
    text, listed, notes, _s, _r = scope_world(framework, fx["empty"])
    assert not any(c["soft"] or c["scope"] for c in listed), f"{framework}: {listed}"
    assert any("holds no check of a form the factory reads" in n and "line " in n and "unknown form" in n for n in notes), \
        f"{framework}: {notes!r}"
    if framework == "java-junit":
        assert [c["key"] for c in listed] == [f"tests/T.java:{fx['head'].count(chr(10)) + 1}"], f"{framework}: {listed}"
    elif framework in VARIABLES:     # the closing call is a head of JUnit's `assertAll` form too; with no scope it stays listed, stopping
        closing = [n for n, line in enumerate(text.splitlines(), 1) if ".assertAll(" in line]
        assert [c["key"] for c in listed] == [f"tests/T.java:{n}" for n in closing], f"{framework}: {listed}"
    else:
        assert listed == [], f"{framework}: {listed}"


@pytest.mark.parametrize("framework", BRACKETED)
def test_unbalanced_source_reads_no_scope(framework):
    """A scope whose closing cannot be found: the lexer's own pairing refuses the whole file before any scope is read (a body that is not
    certainly the test's is never guessed), and it names the line - so no check of it is ever read as soft."""
    fx = SCOPES[framework]
    lines = fx["scope"](2).splitlines(keepends=True)
    broken = fx["head"] + "".join(lines[:-1]) + fx["tail"]           # the scope loses its closing line
    spec = PBC.parse_node(fx["node"])
    with pytest.raises(PBC.Refusal) as refusal:
        PBC.checks_of(broken.encode(), spec, PBC._reader_entry(spec), [], [], [])
    assert "do not balance at line" in str(refusal.value), f"{framework}: {refusal.value}"


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_no_language_name_in_branch(framework):
    """AR-1: the row decides, no code names a language or a framework. (1) Behaviour: the framework's own checks under a scope opener that
    NO code or table knows (`bundle`) are one soft group when a row names it, and the same bytes with the row gone are plain - the
    shipped row's own `head` filter carried along. (2) Static: no string literal outside a docstring in the functions that read scopes
    names a language, a framework or a form, and none compares against such a name."""
    import ast
    import inspect
    fx = SCOPES[framework]
    shipped = next(r for r in AD.soft_scopes_of(PBC._reader_entry(PBC.parse_node(fx["node"]))) if re.search(r["opens"], fx["opener"]))
    fake_text, fake_regex = fx["fake"]
    body = fx["scope"](2).replace(fx["opener"], fake_text, 1)
    assert fake_text in body, f"{framework}: the fixture lost its opener"
    row = {"opens": fake_regex, "head": shipped["head"], "closes": shipped["closes"]}
    _t, carried, notes, _s, _r = scope_world(framework, body, scope_rows=[row])
    assert len(carried) == 2 and all(c["soft"] and c["scope"] for c in carried) and notes == [], f"{framework}: {carried} {notes!r}"
    _t, plain, _n, _s, _r = scope_world(framework, body, scope_rows=[])
    assert not any(c["soft"] or c["scope"] for c in plain), f"{framework}: without the row nothing is soft: {plain}"
    names = re.compile(r"(?i)python|typescript|csharp|c#|java|playwright|nunit|junit|testng|assertj|assertall|assertsoftly|softassertions|multiple")
    for function in (PBC.checks_of, PBC.run_plan, AD.soft_scopes_of, AD._soft_scopes, AD.fill_scope_regex, AD._compiled_scope_row):
        tree = ast.parse(inspect.getsource(function).lstrip())
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.body and isinstance(node.body[0], ast.Expr) \
                    and isinstance(node.body[0].value, ast.Constant):
                node.body[0] = ast.Pass()                     # a docstring says what the code does; it is not code
        literals = [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)]
        assert not [t for t in literals if names.search(t)], f"{function.__name__} names a language or a framework in code: {literals}"


def _declared_line(framework: str) -> int:
    return SCOPES[framework]["head"].count("\n") + 1


@pytest.mark.parametrize("framework", VARIABLES)
def test_closes_scope_without_closing_call_is_plain(framework):
    """A variable that is never closed in its own body (returned, passed to a helper, closed in an after-each, closed only inside a
    conditional or a lambda) opens NO scope: the checks on it are read by the plain rule (stopping), and a note names the line. The safe
    side: a check wrongly read as stopping costs a run, a check wrongly read as soft hides what follows. A `closes` that does not compile
    once the variable is put in is the same: no scope and a note, never an exception."""
    fx = SCOPES[framework]
    decl, member, close = fx["declare"]("v"), fx["member_of"]("v"), fx["close"]("v")
    bodies = {"never closed": decl + member * 2,
              "passed to a helper": decl + member * 2 + "        helper(v);\n",
              "closed in a conditional block": decl + member * 2 + "        if (a > 0) {\n" + close + "        }\n",
              "closed in a lambda": decl + member * 2 + "        run(() -> v.assertAll());\n"}
    for what, body in bodies.items():
        text, listed, notes, _s, _r = scope_world(framework, body)
        members = [c for c in listed if c["key"] in keys_of(framework, text)]
        assert len(members) == 2 and not any(c["soft"] or c["scope"] for c in members), f"{framework} ({what}): {members}"
        assert all(len(r["keys"]) == 1 for r in PBC.run_plan(members)), f"{framework} ({what}): a run per check"
        assert any(f"line {_declared_line(framework)} of tests/T.java has no closing call" in n for n in notes), f"{framework} ({what}): {notes!r}"
    shipped = next(r for r in AD.soft_scopes_of(PBC._reader_entry(PBC.parse_node(fx["node"]))) if re.search(r["opens"], fx["opener"]))
    broken = {"opens": shipped["opens"], "head": shipped["head"], "closes": r"(?<={var}|z)\."}       # fixed width only for a one-letter name
    named = fx["declare"]("vv") + fx["member_of"]("vv") * 2 + fx["close"]("vv")
    text, listed, notes, _s, _r = scope_world(framework, named, scope_rows=[broken])
    assert not any(c["soft"] or c["scope"] for c in listed), f"{framework}: {listed}"
    assert any("does not compile once its name is put in" in n and f"line {_declared_line(framework)}" in n for n in notes), f"{framework}: {notes!r}"


@pytest.mark.parametrize("framework", VARIABLES)
def test_closes_two_variables_two_scopes(framework):
    """Two variables in one body are two scopes, never merged - one after the other or interleaved; the same variable opened twice is two
    scopes in order. Each scope's members carry its own id and `run_plan` closes a run where the id changes."""
    fx = SCOPES[framework]

    def part(name, members=2):
        return fx["declare"](name) + fx["member_of"](name) * members + fx["close"](name)

    text, listed, notes, _s, _r = scope_world(framework, part("p") + part("q"))
    keys = keys_of(framework, text)
    assert [c["key"] for c in listed] == keys and notes == [] and all(c["soft"] for c in listed), f"{framework}: {listed} {notes!r}"
    assert listed[0]["scope"] == listed[1]["scope"] != listed[2]["scope"] == listed[3]["scope"], f"{framework}: {listed}"
    assert [r["keys"] for r in PBC.run_plan(listed)] == [keys[:2], keys[2:]], f"{framework}: two scopes, two runs"
    both = fx["declare"]("p") + fx["declare"]("q") + "".join(fx["member_of"](n) for n in "pqpq") + fx["close"]("p") + fx["close"]("q")
    text, listed, notes, _s, _r = scope_world(framework, both)
    keys = keys_of(framework, text)
    assert [c["key"] for c in listed] == keys and notes == [] and all(c["soft"] for c in listed), f"{framework}: {listed} {notes!r}"
    assert listed[0]["scope"] == listed[2]["scope"] != listed[1]["scope"] == listed[3]["scope"], f"{framework}: never merged: {listed}"
    assert [r["keys"] for r in PBC.run_plan(listed)] == [[k] for k in keys], f"{framework}: interleaved scopes are a run each - the safe side"
    reopened = fx["declare"]("p").split(" p", 1)[1]       # " = new <Type>();": the same variable assigned again, with no type in front
    text, listed, notes, _s, _r = scope_world(framework, part("p") + "        p" + reopened + part("p")[len(fx["declare"]("p")):])
    keys = keys_of(framework, text)
    assert [c["key"] for c in listed] == keys and notes == [] and all(c["soft"] for c in listed), f"{framework}: {listed} {notes!r}"
    assert listed[0]["scope"] == listed[1]["scope"] != listed[2]["scope"] == listed[3]["scope"], f"{framework}: {listed}"
    assert int(listed[0]["scope"].split(":")[1]) < int(listed[2]["scope"].split(":")[1]), f"{framework}: in order"
    assert [r["keys"] for r in PBC.run_plan(listed)] == [keys[:2], keys[2:]], f"{framework}: {PBC.run_plan(listed)}"


@pytest.mark.parametrize("framework", VARIABLES)
def test_closes_check_after_close_stops(framework):
    """INV: a row never makes a stopping check soft outside its scope. A call on the variable AFTER its closing call is stopping as
    written and not joined to the scope's run; a closing call BEFORE any check is a scope with no check = no scope and a note."""
    fx = SCOPES[framework]
    text, listed, notes, _s, _r = scope_world(framework, fx["declare"]("v") + fx["member_of"]("v") * 2 + fx["close"]("v") + fx["after"]("v"))
    keys = keys_of(framework, text)
    assert [c["key"] for c in listed] == keys and notes == [], f"{framework}: the closing call is no check: {listed} {notes!r}"
    assert [(c["soft"], c["scope"] is not None) for c in listed] == [(True, True), (True, True), (False, False)], f"{framework}: {listed}"
    assert [r["keys"] for r in PBC.run_plan(listed)] == [keys[:2], keys[2:]], f"{framework}: {PBC.run_plan(listed)}"
    text, listed, notes, _s, _r = scope_world(framework, fx["declare"]("v") + fx["close"]("v") + fx["after"]("v"))
    after = [c for c in listed if c["key"] in keys_of(framework, text)]
    assert len(after) == 1 and not after[0]["soft"] and after[0]["scope"] is None, f"{framework}: {listed}"
    assert any("holds no check of a form the factory reads" in n and f"line {_declared_line(framework)}" in n for n in notes), f"{framework}: {notes!r}"


def test_opens_without_bracket_needs_closes(tmp_path):
    """The loader: a row whose `opens` does not end on an opening bracket is refused, naming `soft_scopes[n].opens`, unless the row has
    `closes`; `{name}` of a named group of `opens` is tried in `closes` and `head` with a dummy name, and a regex that fails then is
    refused at its own field. The reader meets the same unvalidated row as a note and no scope (`test_no_scope_row_plain_plan`)."""
    def refusal(rows):
        doc = shipped_doc()
        doc[AD.KEY]["java"]["soft_scopes"] = rows
        return refused(tmp_path, doc, "java")

    exc = refusal([{"opens": r"\bnew\s+X\b"}])
    assert exc is not None and exc.field.endswith("soft_scopes[0].opens") and "opening bracket" in str(exc) and "closes" in str(exc), repr(exc)
    assert refusal([{"opens": r"\bnew\s+X\b", "head": r"\bx"}]) is not None, "a head does not stand in for `closes`"
    for fine in ([{"opens": r"(?P<var>\w+)\s*=\s*new\s+X\s*;", "closes": r"\b{var}\.done\s*\(", "head": r"(?<={var}\.)"}],
                 [{"opens": r"\bf\s*\("}], [{"opens": r"\bf\s*[(]"}], [{"opens": r"\bf\s*\{"}], [{"opens": r"\bnew\s+X\b", "closes": r"\bdone\b"}]):
        assert refusal(fine) is None, f"{fine} must load"
    for field, row in (("closes", {"opens": r"(?P<var>\w+)\s*=", "closes": r"{var}\s*("}), ("head", {"opens": r"(?P<var>\w+)\s*=", "closes": "c", "head": "{var}("}),
                       ("closes", {"opens": r"\bnew\s+X\b", "closes": "(c"})):
        exc = refusal([row])
        assert exc is not None and exc.field.endswith(f"soft_scopes[0].{field}"), f"{row}: {exc!r}"
    notes: list = []
    entry = dict(entry_of("java"), soft_scopes=[{"opens": r"(?P<var>\w+)\s*=", "closes": r"{var}\s*("}, {"opens": r"\bf\s*\(", "closes": "(c"}])
    assert AD.soft_scopes_of(entry, notes) == [] and len(notes) == 2 and all("no scope from that row" in n for n in notes), notes
    assert AD.fill_scope_regex(r"\b{var}\.{other}\d{2}", {"var": "a$b", "other": "x"}) == r"\ba\$b\.x\d{2}", "a quantifier is not a name"


@pytest.mark.parametrize("language", LANGUAGES)
def test_soft_scopes_rows_and_loader(language, tmp_path):
    """The shipped rows exist only where a form was verified (java and csharp), read through `soft_scopes_of`; absent and `[]` read the
    same; a row that does not compile is left out with a note; the loader refuses a malformed row and names the field."""
    entry = entry_of(language)
    rows = AD.soft_scopes_of(entry)
    if language in ("java", "csharp"):
        assert rows and all(set(r) == {"opens", "head", "closes"} for r in rows), f"{language}: {rows}"
    else:
        assert rows == [] and "soft_scopes" not in entry, f"{language}: no verified scope form, so no row: {rows}"
    assert AD.soft_scopes_of(without(entry, "soft_scopes")) == [] == AD.soft_scopes_of(dict(entry, soft_scopes=[])), f"{language}: absent is []"
    assert AD.soft_scopes_of(None) == [] and AD.soft_scopes_of({"soft_scopes": "x"}) == [], f"{language}: nothing to read is []"
    notes: list = []
    leaves = dict(entry, soft_scopes=[{"opens": "(x"}, {"opens": "a", "head": "(y"}, {"head": "b"}, "c", {"opens": "ok", "head": None}])
    assert AD.soft_scopes_of(leaves, notes) == [{"opens": "ok", "head": None, "closes": None}], f"{language}: only the readable row is kept"
    assert len(notes) == 4 and all("no scope from that row" in n for n in notes), f"{language}: {notes!r}"
    assert AD.soft_scopes_of(leaves) == [{"opens": "ok", "head": None, "closes": None}], f"{language}: with no list to note into it must not raise"
    if language == "python":                        # the AST key's entry holds no such row (a table field only)
        return
    for wrong, field in (("x", "soft_scopes"), ([{"opens": "(x"}], "soft_scopes[0].opens"), ([{"opens": "a", "head": "(y"}], "soft_scopes[0].head"),
                         ([{"head": "b"}], "soft_scopes[0]"), ([{"opens": "a", "more": 1}], "soft_scopes[0]"), (["a"], "soft_scopes[0]")):
        doc = shipped_doc()
        doc[AD.KEY][language]["soft_scopes"] = wrong
        exc = refused(tmp_path, doc, language)
        assert exc is not None and exc.field.endswith(field), f"{language}: {wrong!r} must be refused at {field}, got {exc!r}"
    doc = shipped_doc()
    doc[AD.KEY][language]["soft_scopes"] = []
    assert refused(tmp_path, doc, language) is None, f"{language}: an empty `soft_scopes` is a legal row"


# --- t-2064 P3: the model file (`load_models`, `_models_refusal`) --------------------------------------------------------------------
# One entry per check, ONE kind each; the loader reads shape and presence and never meaning (AR-29). A red names the language (the
# parameter id: the check key is that language's file) and the branch (the test and its message).

def model_task(tmp_path: Path) -> Path:
    (tmp_path / "task" / "work" / "probe-models").mkdir(parents=True, exist_ok=True)
    return tmp_path / "task"


def put_models(task: Path, doc, name: str = "d1.json", raw: bytes = None) -> str:
    path = task / "work" / "probe-models" / name
    path.write_bytes(raw if raw is not None else json.dumps(doc).encode("utf-8"))
    return f"work/probe-models/{name}"


def refusal_of(call):
    try:
        call()
    except PBC.Refusal as exc:
        return str(exc)
    return None


def key_of(language: str, line: int = 4) -> str:
    return f"{LANG[language]['file']}:{line}"


def items_of(language: str, doors=("actual", "find", "invert", "not_here", "product")) -> list:
    return [{"key": key_of(language, 4), "line": 4, "doors": list(doors)}, {"key": key_of(language, 5), "line": 5, "doors": ["not_here"]}]


@pytest.mark.parametrize("language", LANGUAGES)
def test_models_good_file_reads_each_kind(language, tmp_path):
    key, task = key_of(language), model_task(tmp_path)
    doc = {"models": [{"check": key, "supposes": "the refusal answers 500", "actual": "500"},
                      {"check": key, "instance": "P-1", "supposes": "the line is lost", "find": "x = 1;", "replace": "x = 2;"},
                      {"check": key, "instance": "P-2", "invert": "no other value is known"},
                      {"check": key, "instance": "P-3", "not_here": "the branch is not taken"},
                      {"check": key, "instance": "P-4", "alternative": "TC-1:ALT-1", "product": "work/sensitivity-receipts/r.json"}]}
    got = PBC.load_models(task, put_models(task, doc), items_of(language))
    assert [e["kind"] for e in got] == ["actual", "find", "invert", "not_here", "product"], f"{language}: {got}"
    assert got[0]["actual"] == "500" and got[1]["replace"] == "x = 2;" and got[4]["alternative"] == "TC-1:ALT-1", f"{language}: {got}"


@pytest.mark.parametrize("language", LANGUAGES)
def test_models_one_kind_per_entry(language, tmp_path):
    key, task = key_of(language), model_task(tmp_path)
    cases = {
        "two kinds": {"check": key, "supposes": "s", "actual": "1", "invert": "r"},
        "no kind": {"check": key, "supposes": "s"},
        "an unknown kind": {"check": key, "supposes": "s", "replace_all": "1"},
        "a replace with no find": {"check": key, "supposes": "s", "replace": "1"},
        "a find with no replace": {"check": key, "supposes": "s", "find": "x"},
        "an unknown key beside a kind": {"check": key, "supposes": "s", "actual": "1", "colour": "red"},
    }
    for label, entry in cases.items():
        text = refusal_of(lambda: PBC.load_models(task, put_models(task, {"models": [entry]})))
        assert text is not None and "models[1]" in text and key in text and "EXACTLY ONE kind" in text, f"{language}: {label}: {text}"


@pytest.mark.parametrize("language", LANGUAGES)
def test_models_supposes_required_on_a_value_kind(language, tmp_path):
    key, task = key_of(language), model_task(tmp_path)
    for label, value in (("absent", None), ("empty", ""), ("blank", "   "), ("301 characters", "s" * 301), ("not a string", 5)):
        for entry in ({"check": key, "actual": "1"}, {"check": key, "find": "x", "replace": "y"}):
            if value is not None:
                entry = dict(entry, supposes=value)
            text = refusal_of(lambda: PBC.load_models(task, put_models(task, {"models": [entry]})))
            assert text is not None and "`supposes`" in text and "1 to 300" in text, f"{language}: {label}: {text}"
    for edge in ("s", "s" * 300, "any words at all, never read: )(*&"):        # AT the limit, and presence only
        assert PBC.load_models(task, put_models(task, {"models": [{"check": key, "actual": "1", "supposes": edge}]}))[0]["supposes"] == edge, \
            f"{language}: a supposes of {len(edge)} characters is accepted whatever it says"


@pytest.mark.parametrize("language", LANGUAGES)
def test_invert_needs_reason(language, tmp_path):
    key, task = key_of(language), model_task(tmp_path)
    for label, value in (("empty", ""), ("blank", "  \t"), ("not a string", None), ("a number", 3)):
        text = refusal_of(lambda: PBC.load_models(task, put_models(task, {"models": [{"check": key, "invert": value}]})))
        assert text is not None and "`invert` must be a non-empty string" in text and "no other value is known" in text, f"{language}: {label}: {text}"
    assert PBC.load_models(task, put_models(task, {"models": [{"check": key, "invert": "no other value is known"}]}))[0]["invert"] \
        == "no other value is known", f"{language}: a reason is accepted"


@pytest.mark.parametrize("language", LANGUAGES)
def test_not_here_needs_instance_and_why(language, tmp_path):
    key, task = key_of(language), model_task(tmp_path)
    for label, entry in (("no instance", {"check": key, "not_here": "why"}), ("empty why", {"check": key, "instance": "P", "not_here": ""}),
                         ("blank instance", {"check": key, "instance": " ", "not_here": "why"})):
        text = refusal_of(lambda: PBC.load_models(task, put_models(task, {"models": [entry]})))
        assert text is not None and ("`not_here` needs `instance`" in text or "non-empty string" in text), f"{language}: {label}: {text}"
    assert PBC.load_models(task, put_models(task, {"models": [{"check": key, "instance": "P", "not_here": "w"}]}))[0]["instance"] == "P", language


@pytest.mark.parametrize("language", LANGUAGES)
def test_two_entries_same_key_refused(language, tmp_path):
    key, task = key_of(language), model_task(tmp_path)
    a, b = {"check": key, "supposes": "s", "actual": "1"}, {"check": key, "invert": "r"}
    text = refusal_of(lambda: PBC.load_models(task, put_models(task, {"models": [a, b]})))
    assert text is not None and "models[1] and models[2]" in text and key in text, f"{language}: {text}"
    for other in (dict(b, instance="P-1"), dict(b, alternative="TC-1:ALT-1")):                    # another identity: not the same entry
        assert len(PBC.load_models(task, put_models(task, {"models": [a, other]}))) == 2, f"{language}: {other}"


@pytest.mark.parametrize("language", LANGUAGES)
def test_old_shape_refused_names_new(language, tmp_path):
    key, task = key_of(language), model_task(tmp_path)
    for label, doc in (("the old one-object shape", {"alternative": "TC-1:ALT-1", "find": "x", "replace": "y"}),
                       ("an old gap", {"alternative": "TC-1:ALT-1", "gap": "why"}), ("an old function", {"function": "a.py::f", "find": "x", "replace": "y"}),
                       ("no `models` key", {"check": key}), ("models not a list", {"models": {"check": key}}), ("a bare list", [{"check": key}])):
        text = refusal_of(lambda: PBC.load_models(task, put_models(task, doc)))
        assert text is not None and '{"models": [' in text and "EXACTLY ONE kind" in text, f"{language}: {label}: {text}"
    assert "`models`" in refusal_of(lambda: PBC.load_models(task, put_models(task, {"find": "x", "replace": "y"}))), f"{language}: names `models`"


@pytest.mark.parametrize("language", LANGUAGES)
def test_models_file_guards_are_the_alternatives(language, tmp_path):
    """The guards of `load_models` (`_read_model_file`): a size limit AT and BEYOND `MODEL_FILE_MAX`, UTF-8, JSON, one object, a path under the folder."""
    key, task = key_of(language), model_task(tmp_path)
    good = json.dumps({"models": [{"check": key, "invert": "r"}]})
    assert PBC.MODEL_FILE_MAX == 65536, "the limit of a window's file"
    at = good.ljust(PBC.MODEL_FILE_MAX).encode("utf-8")
    assert len(PBC.load_models(task, put_models(task, None, "at.json", at))) == 1, f"{language}: a file AT the limit is read"
    over = refusal_of(lambda: PBC.load_models(task, put_models(task, None, "over.json", at + b" ")))
    assert over is not None and "65536" in over, f"{language}: a file beyond the limit is refused naming it: {over}"
    for label, raw in (("not UTF-8", b"\xff\xfe{}"), ("not JSON", b"{models"), ("empty", b""), ("not an object", b"[1]")):
        text = refusal_of(lambda: PBC.load_models(task, put_models(task, None, "x.json", raw)))
        assert text is not None and "--model" in text, f"{language}: {label}: {text}"
    assert "not UTF-8" in refusal_of(lambda: PBC.load_models(task, put_models(task, None, "u.json", b"\xff\xfe{}"))), language
    outside = tmp_path / "elsewhere.json"
    outside.write_text(good, encoding="utf-8")
    text = refusal_of(lambda: PBC.load_models(task, str(outside)))
    assert text is not None and "is not under" in text, f"{language}: a path escaping the task root is refused: {text}"
    text = refusal_of(lambda: PBC.load_models(task, "work/probe-models/../../../elsewhere.json"))
    assert text is not None and "is not under" in text, f"{language}: a `..` path is refused: {text}"
    bom = put_models(task, None, "bom.json", b"\xef\xbb\xbf" + good.encode("utf-8"))
    assert len(PBC.load_models(task, bom)) == 1, f"{language}: a BOM is tolerated, as `load_models` does"


def _limit_entry(field: str, size: int) -> dict:
    """One model entry whose `field` is `size` characters long (the others as short as the shape allows)."""
    key = key_of("python")
    if field == "gap":
        return {"alternative": "TC-1:ALT-1", "gap": "g" * size}
    if field == "supposes":
        return {"check": key, "supposes": "s" * size, "actual": "2"}
    entry = {"check": key, "supposes": "s", "find": "f", "replace": "r"}
    if field == "actual":
        return {"check": key, "supposes": "s", "actual": "a" * size}
    entry[field] = field[0] * size
    return entry


@pytest.mark.parametrize("field, limit_name", [("actual", "MODEL_TEXT_MAX"), ("find", "MODEL_TEXT_MAX"), ("replace", "MODEL_TEXT_MAX"),
                                               ("supposes", "MODEL_SUPPOSES_MAX"), ("gap", "MODEL_GAP_MAX")])
def test_model_entry_limits_at_and_beyond(field, limit_name, tmp_path):
    """F3 (t-2490), rule 11: every per-entry limit of `load_models` is pinned AT and one BEYOND it: `actual`, `find`, `replace` at
    `MODEL_TEXT_MAX` (2000), `supposes` at `MODEL_SUPPOSES_MAX` (300), `gap` at `MODEL_GAP_MAX` (300). At the limit the file is read; one
    beyond is refused and the refusal names the field and the limit. Killed by: a limit raised, dropped or off by one in `load_models`
    (the file at the limit is refused, or the one beyond is read)."""
    limit, task = getattr(PBC, limit_name), model_task(tmp_path)
    assert limit == {"MODEL_TEXT_MAX": 2000, "MODEL_SUPPOSES_MAX": 300, "MODEL_GAP_MAX": 300}[limit_name], "the limit the rule names"
    at = PBC.load_models(task, put_models(task, {"models": [_limit_entry(field, limit)]}, "at.json"))
    assert len(at) == 1, f"{field}: AT the limit is read"
    text = refusal_of(lambda: PBC.load_models(task, put_models(task, {"models": [_limit_entry(field, limit + 1)]}, "over.json")))
    assert text is not None and f"`{field}`" in text and str(limit) in text, f"{field}: one beyond is refused naming the field and the limit: {text}"


@pytest.mark.parametrize("language", LANGUAGES)
def test_unknown_check_key_lists_the_plans_keys(language, tmp_path):
    key, task = key_of(language), model_task(tmp_path)
    items = items_of(language)
    text = refusal_of(lambda: PBC.load_models(task, put_models(task, {"models": [{"check": key + "9", "invert": "r"}]}), items))
    assert text is not None and "not a key of this plan" in text and key_of(language, 4) in text and key_of(language, 5) in text, f"{language}: {text}"
    assert len(PBC.load_models(task, put_models(task, {"models": [{"check": key, "invert": "r"}]}), items)) == 1, f"{language}: a known key passes"


@pytest.mark.parametrize("language", LANGUAGES)
def test_no_model_refused_names_checks(language, tmp_path):
    """F-P8: no file, an empty `models`: the refusal names each check with its line and its open doors, and the door OPENS - the second
    call, with an entry of a printed kind, loads."""
    task, items = model_task(tmp_path), items_of(language)
    for label, call in (("no file", lambda: PBC.load_models(task, "work/probe-models/none.json", items)),
                        ("an empty models", lambda: PBC.load_models(task, put_models(task, {"models": []}, "empty.json"), items))):
        text = refusal_of(call)
        assert text is not None, f"{language}: {label}: no refusal"
        assert all(f"{item['key']} (line {item['line']}): " in text for item in items), f"{language}: {label}: checks named with lines: {text}"
        assert "report `unverified`" in text and "Nothing was changed" in text, f"{language}: {label}: the exit is named: {text}"
    printed = [kind for kind in PBC.MODEL_KINDS if f"  {kind}: {{" in text]
    assert printed == list(PBC.MODEL_KINDS), f"{language}: every open door has its printed shape: {printed}"
    second = {"models": [{"check": key_of(language), "supposes": "s", "actual": "1"}, {"check": key_of(language, 5), "instance": "P", "not_here": "w"}]}
    assert len(PBC.load_models(task, put_models(task, second, "none.json"), items)) == 2, f"{language}: the second call, as printed, loads"


@pytest.mark.parametrize("language", LANGUAGES)
def test_refusal_prints_only_open_doors(language, tmp_path):
    """An `invert: null` form has no `invert` door: the text never says the word, and a check with one door lists that one."""
    task = model_task(tmp_path)
    items = [{"key": key_of(language), "line": 4, "doors": ["actual", "find", "not_here", "product"]},
             {"key": key_of(language, 5), "line": 5, "doors": ["not_here"]}]
    text = refusal_of(lambda: PBC.load_models(task, "work/probe-models/none.json", items))
    assert text is not None and "invert" not in text.lower(), f"{language}: no door of that name opens, so none is printed: {text}"
    assert f"{key_of(language)} (line 4): actual, find, not_here, product" in text and f"{key_of(language, 5)} (line 5): not_here\n" in text + "\n", \
        f"{language}: each check lists its own doors: {text}"
    narrow = str(PBC._models_refusal("p", items[1:]))
    assert "  not_here: {" in narrow and not any(f"  {kind}: {{" in narrow for kind in ("actual", "find", "invert", "product")), \
        f"{language}: only the door that opens is shown: {narrow}"


# --- t-2064 P3: the edit (`plan_model`, `_edit_shape`, `_model_region`) ------------------------------------------------------------------
# One check of each language: `actual` replaces the argument that holds the value and nothing else; `find` replaces code that stands once
# before the statement; whatever a model plants beyond that is a refusal that changes nothing. A red names the language (parameter id).

CHECK_T = {
    "python": '    assert {v} == 1, "c1"\n',
    "typescript": "  expect({v}, 'c1').toBe(1);\n",
    "csharp": "        Assert.Equal(1, {v});  // c1\n",
    "java": "        assertThat({v}).isEqualTo(1);  // c1\n",
}
CALL = {"python": "max(a, 1)", "typescript": "Math.max(a, 1)", "csharp": "Math.Max(a, 1)", "java": "Math.max(a, 1)"}
PRE_T = {"python": "    {n} = {call}\n", "typescript": "  const {n} = {call};\n", "csharp": "        var {n} = {call};\n",
         "java": "        int {n} = {call};\n"}
HELPER_T = {
    "python": "def other():\n    z = 7\n    return z\n\n\ndef expect_cart(n):\n    m = n + 1\n    assert n == 1\n",
    "typescript": "export function other() {\n  const z = 7;\n  return z;\n}\nexport function expectCart(n: number) {\n  const m = n + 1;\n"
                  "  expect(n).toBe(1);\n}\n",
    "csharp": "public class Pages\n{\n    public int Other()\n    {\n        var z = 7;\n        return z;\n    }\n    public void ExpectCart(int n)\n"
              "    {\n        var m = n + 1;\n        Assert.Equal(1, n);\n    }\n}\n",
    "java": "class Pages {\n    int other() {\n        int z = 7;\n        return z;\n    }\n    void expectCart(int n) {\n        int m = n + 1;\n"
            "        assertEquals(1, n);\n    }\n}\n",
}
# what a model plants into the value of the check: a bracket that closes what it did not open, and a second argument (the call's number
# of arguments changes); python: one expression that is a different comparison, and a tuple
PLANTED = {
    "python": ("500 == 400 or 1", "a, 2"),
    "typescript": ("x).toBe(1", "a, 'm'", "a).not.toBe(2); expect(a"),
    "csharp": ("a); Assert.True(a", "1, a"),
    "java": ("a).isEqualTo(2); assertThat(a", "a, 'm'"),
}
STATEMENT_TOKEN = {"python": "== 1", "typescript": ".toBe(1)", "csharp": "Assert.Equal", "java": ".isEqualTo(1)"}


def mworld(language: str, value: str = "a", pre: bool = True, second: bool = False, eol: str = "\n", bom: bool = False):
    """(data, spec, listed, text): the test of `language` with two lines of code before its check (`pre`), the check (value `value`),
    and a second check on its own line (`second`); `eol` and `bom` shape the bytes."""
    fx = LANG[language]
    lines = (PRE_T[language].format(n="b", call=CALL[language]) + PRE_T[language].format(n="c", call=CALL[language].replace("a, 1", "a, 2"))
             if pre else "")
    body = lines + CHECK_T[language].format(v=value) + (CHECK_T[language].format(v="a") if second else "")
    head = fx["head"] if pre else fx["head"][:fx["head"].rstrip("\n").rindex("\n") + 1]     # `pre` False: nothing stands before the check
    text = (head + body + fx["tail"]).replace("\n", eol)
    data = (b"\xef\xbb\xbf" if bom else b"") + text.encode("utf-8")
    spec = PBC.parse_node(fx["node"])
    listed = PBC.checks_of(data, spec, PBC._reader_entry(spec), [], [], [])
    return data, spec, listed, text


def entry_for(check: dict, kind: str, index: int = 1, **more) -> dict:
    base = {"index": index, "check": check["key"], "instance": "", "alternative": "", "kind": kind, "supposes": "s"}
    return dict(base, **more)


def text_of(data: bytes) -> str:
    return data.decode("utf-8-sig")


def plan_text(language: str, entries_of, **world_args):
    """`plan_model` over `mworld`: (new text, details, text) - `entries_of(listed)` builds the entries."""
    data, spec, listed, text = mworld(language, **world_args)
    out, details = PBC.plan_model(data, spec, entries_of(listed), listed)
    return text_of(out), details, text


def refusal_plan(language: str, entries_of, **world_args):
    data, spec, listed, _text = mworld(language, **world_args)
    return refusal_of(lambda: PBC.plan_model(data, spec, entries_of(listed), listed))


@pytest.mark.parametrize("language", LANGUAGES)
def test_actual_replaces_argument_only(language):
    new, details, text = plan_text(language, lambda c: [entry_for(c[0], "actual", actual="999")])
    assert new == text.replace(CHECK_T[language].format(v="a"), CHECK_T[language].format(v="999")), f"{language}: only the value changed: {new!r}"
    assert details[0]["removed"] == "a" and details[0]["added"] == "999" and details[0]["probe_kind"] == "actual", f"{language}: {details[0]}"
    assert details[0]["statement_after"] == CHECK_T[language].format(v="999").strip().split("  //")[0], f"{language}: {details[0]['statement_after']!r}"


@pytest.mark.parametrize("language", LANGUAGES)
def test_actual_with_brackets_replaced_by_literal(language):
    """Brackets REMOVED with the old value and none added: balanced, so never refused for them (`expect(r.status(), m)` with `500`)."""
    new, details, text = plan_text(language, lambda c: [entry_for(c[0], "actual", actual="500")], value=CALL[language])
    assert new == text.replace(CHECK_T[language].format(v=CALL[language]), CHECK_T[language].format(v="500")), f"{language}: {new!r}"
    assert details[0]["removed"] == CALL[language] and details[0]["added"] == "500", f"{language}: {details[0]}"


@pytest.mark.parametrize("language", LANGUAGES)
def test_actual_literal_replaced_by_brackets(language):
    other = CALL[language].replace("a, 1", "a, 3")
    new, _details, text = plan_text(language, lambda c: [entry_for(c[0], "actual", actual=other)])
    assert new == text.replace(CHECK_T[language].format(v="a"), CHECK_T[language].format(v=other)), f"{language}: {new!r}"


@pytest.mark.parametrize("language", LANGUAGES)
def test_find_bracket_change(language):
    """`find` of a balanced text that holds brackets, replaced by one with none, and a text with none replaced by one with a pair: a
    balanced edit is never refused for its brackets."""
    call = CALL[language]
    new, details, text = plan_text(language, lambda c: [entry_for(c[0], "find", find=call, replace="a")])
    assert new == text.replace(call, "a", 1) and details[0]["probe_kind"] == "find", f"{language}: {new!r}"
    new, _details, text = plan_text(language, lambda c: [entry_for(c[0], "find", find="a, 1", replace="(a, 1)")])
    assert new == text.replace("a, 1", "(a, 1)", 1), f"{language}: {new!r}"


@pytest.mark.parametrize("language", LANGUAGES)
def test_half_bracket_find_refused(language):
    """The table reader: `find` that opens a bracket it does not close is refused (its removed text is not balanced). The AST reader
    has no lexical shape and parses the new text instead: a half-bracket `find` that leaves the file parsing stands, one that does not
    parse is refused."""
    again = lambda c: [entry_for(c[0], "find", find="(a, 1", replace="(a, 2")]  # noqa: E731
    if language == "python":
        new, _d, text = plan_text(language, again)
        assert new == text.replace("(a, 1", "(a, 2", 1), f"{language}: a half-bracket find that parses is applied by the AST reader"
        broken = refusal_plan(language, lambda c: [entry_for(c[0], "find", find=CALL[language], replace="max(a, 2")])
        assert broken is not None and "does not parse" in broken and "Nothing was changed" in broken, f"{language}: {broken}"
        return
    text = refusal_plan(language, again)
    assert text is not None and "removed text's brackets are not balanced" in text and "Nothing was changed" in text, f"{language}: {text}"
    both = refusal_plan(language, lambda c: [entry_for(c[0], "find", find="a, 1)", replace="a, 1")])
    assert both is not None and "not balanced" in both, f"{language}: a find that closes what it did not open: {both}"


@pytest.mark.parametrize("language", LANGUAGES)
def test_added_unbalanced_refused(language):
    for added in ("a, 1)", "(a, 1") + (() if language == "python" else ("a, 1) + foo(2",)):
        text = refusal_plan(language, lambda c: [entry_for(c[0], "find", find="a, 1", replace=added)])
        assert text is not None and "Nothing was changed" in text, f"{language}: {added!r} must be refused: {text}"
        if language != "python":
            assert "added text's brackets are not balanced" in text, f"{language}: {added!r}: {text}"
    unclosed = refusal_plan(language, lambda c: [entry_for(c[0], "find", find="a, 1", replace="'a")])
    assert unclosed is not None and "Nothing was changed" in unclosed, f"{language}: an added text that ends inside a string: {unclosed}"


@pytest.mark.parametrize("language", LANGUAGES)
def test_find_before_statement(language):
    new, _d, text = plan_text(language, lambda c: [entry_for(c[0], "find", find="a, 2", replace="a, 5")])
    assert new == text.replace("a, 2", "a, 5", 1), f"{language}: a find standing once before the statement is applied: {new!r}"
    for label, find, count in (("zero times", "zzz-nowhere", "0 times"), ("twice", "(a, ", "2 times")):
        text = refusal_plan(language, lambda c: [entry_for(c[0], "find", find=find, replace="(a, 9")])
        assert text is not None and count in text and "not once" in text, f"{language}: {label}: {text}"
    nothing = refusal_plan(language, lambda c: [entry_for(c[0], "find", find="a, 1", replace=" a, 1 ")])
    assert nothing is not None and "nothing would change" in nothing, f"{language}: removed == added once stripped: {nothing}"
    lines = refusal_plan(language, lambda c: [entry_for(c[0], "find", find="a, 1", replace="a,\n 1")])
    assert lines is not None and "line breaks" in lines, f"{language}: an edit that moves a line: {lines}"


@pytest.mark.parametrize("language", LANGUAGES)
def test_find_in_statement_refused(language):
    text = refusal_plan(language, lambda c: [entry_for(c[0], "find", find=STATEMENT_TOKEN[language], replace="== 2")])
    assert text is not None and "inside the check's statement" in text and "Nothing was changed" in text, f"{language}: {text}"
    only = refusal_plan(language, lambda c: [entry_for(c[0], "find", find="a, 1", replace="a, 2")], pre=False)
    assert only is not None, f"{language}: with no line before the statement `find` has nowhere to look"


@pytest.mark.parametrize("language", LANGUAGES)
def test_find_in_helper_bounded_by_helper(language):
    """A check that stands in a helper: its region is that helper's own body - a line of ANOTHER function of the file is never found."""
    fx = LANG[language]
    helper = HELPER_T[language].encode("utf-8")
    hop = {"file": fx["helper_file"], "data": helper, "hop": True, "chain": False}
    listed, _keys, _notes, (_text, spec, _reader) = checks(language, "", helpers=[hop], extra=fx["call"])
    mine = [c for c in listed if not c["in_body"]]
    assert len(mine) == 1 and mine[0]["file"] == fx["helper_file"], f"{language}: {listed}"
    out, details = PBC.plan_model(helper, spec, [entry_for(mine[0], "find", find="m = n + 1", replace="m = n + 2")], listed)
    assert text_of(out) == HELPER_T[language].replace("m = n + 1", "m = n + 2"), f"{language}: the helper's own line is found: {text_of(out)!r}"
    other = refusal_of(lambda: PBC.plan_model(helper, spec, [entry_for(mine[0], "find", find="z = 7", replace="z = 8")], listed))
    assert other is not None and "0 times" in other, f"{language}: a line of the other function is outside the helper's body: {other}"


@pytest.mark.parametrize("language", LANGUAGES)
def test_expected_and_matcher_never_edited(language):
    """POSITION INVARIANT: a planted `actual` that reaches the matcher, the expected value, `.not` or the message is refused whole."""
    for planted in PLANTED[language]:
        text = refusal_plan(language, lambda c: [entry_for(c[0], "actual", actual=planted)])
        assert text is not None and "Nothing was changed" in text, f"{language}: {planted!r} was applied"
    good = plan_text(language, lambda c: [entry_for(c[0], "actual", actual="2")])[0]
    assert good.count("c1") == 1 and (".toBe(1)" in good or "== 1" in good or "Equal(1" in good or "isEqualTo(1)" in good), \
        f"{language}: the matcher, the expected value and the message stay as written: {good!r}"


@pytest.mark.parametrize("language", LANGUAGES)
def test_overlap_refused(language):
    """Two entries that edit the same bytes: refused naming both - identical edits included; entries of different bytes are not."""
    data, spec, listed, _text = mworld(language, second=True)
    first, second = listed[0], listed[1]
    same = [entry_for(first, "find", index=1, find="a, 1", replace="a, 5"), entry_for(second, "find", index=2, find="a, 1", replace="a, 5")]
    text = refusal_of(lambda: PBC.plan_model(data, spec, same, listed))
    assert text is not None and "models[1]" in text and "models[2]" in text and first["key"] in text and second["key"] in text, f"{language}: {text}"
    twice = [entry_for(first, "actual", index=1, actual="7", instance="P-1"), entry_for(first, "actual", index=2, actual="8", instance="P-2")]
    text = refusal_of(lambda: PBC.plan_model(data, spec, twice, listed))
    assert text is not None and "edit the same bytes" in text, f"{language}: two models of one value: {text}"
    apart = [entry_for(first, "find", index=1, find="a, 1", replace="a, 5"), entry_for(second, "find", index=2, find="a, 2", replace="a, 6")]
    out, _d = PBC.plan_model(data, spec, apart, listed)
    assert "a, 5" in text_of(out) and "a, 6" in text_of(out), f"{language}: different bytes do not overlap"


@pytest.mark.parametrize("language", LANGUAGES)
def test_edits_apply_bottom_up(language):
    """A longer edit ABOVE a shorter one below it: applied top-down the second offset would be stale. Both land whatever the entries' order."""
    data, spec, listed, text = mworld(language)
    check = listed[0]
    above = entry_for(check, "find", index=1, find="a, 1", replace="a, 1000000")
    below = entry_for(check, "actual", index=2, actual="999", instance="P-2")
    want = text.replace("a, 1", "a, 1000000", 1).replace(CHECK_T[language].format(v="a"), CHECK_T[language].format(v="999"))
    for entries in ([above, below], [below, above]):
        out, details = PBC.plan_model(data, spec, entries, listed)
        assert text_of(out) == want, f"{language}: {text_of(out)!r}"
        assert [d["probe_kind"] for d in details] == [e["kind"] for e in entries], f"{language}: one detail per entry, in the entries' order"


@pytest.mark.parametrize("language", LANGUAGES)
def test_line_count_kept(language):
    """CRLF and a BOM are kept, the line count and every line break too."""
    data, spec, listed, text = mworld(language, eol="\r\n", bom=True)
    entries = [entry_for(listed[0], "find", index=1, find="a, 1", replace="a, 7"), entry_for(listed[0], "actual", index=2, actual="42", instance="P")]
    out, _details = PBC.plan_model(data, spec, entries, listed)
    assert out.startswith(b"\xef\xbb\xbf") and not out.startswith(b"\xef\xbb\xbf\xef\xbb\xbf"), f"{language}: one BOM kept"
    assert out.count(b"\r\n") == data.count(b"\r\n") == out.count(b"\n") and out.count(b"\r") == data.count(b"\r"), f"{language}: line ends kept"
    assert len(out.splitlines()) == len(data.splitlines()), f"{language}: line count kept"
    assert b"a, 7" in out and b"42" in out, f"{language}: the edits are in"
    plain, _s, _l, _t = mworld(language)
    out, _details = PBC.plan_model(plain, spec, [entry_for(listed[0], "actual", actual="42")], listed)
    assert not out.startswith(b"\xef\xbb\xbf") and b"\r" not in out, f"{language}: a file with no BOM and LF gets neither"


@pytest.mark.parametrize("language", LANGUAGES)
def test_doors_come_from_check_doors(language, tmp_path):
    """The doors `_models_refusal` prints are `_check_doors`'s answer for each check, and the second call as printed loads. A check with
    no code before it has no `find`; a form with no `actual_arg` row has no `actual`."""
    data, spec, listed, _text = mworld(language)
    doors = PBC._check_doors(data, spec, listed[0])
    assert "actual" in doors and "find" in doors and doors[-2:] == ["not_here", "product"], f"{language}: {doors}"
    bare = mworld(language, pre=False)
    bare_doors = PBC._check_doors(bare[0], bare[1], bare[2][0])
    assert "actual" in bare_doors and "find" not in bare_doors, f"{language}: no line before the statement, no find: {bare_doors}"
    items = [{"key": c["key"], "line": c["line"], "doors": PBC._check_doors(data, spec, c)} for c in listed]
    task = model_task(tmp_path)
    text = refusal_of(lambda: PBC.load_models(task, "work/probe-models/none.json", items))
    assert text is not None and f"{listed[0]['key']} (line {listed[0]['line']}): {', '.join(doors)}" in text, f"{language}: {text}"
    doc = {"models": [{"check": listed[0]["key"], "supposes": "s", "actual": "5"}]}
    assert len(PBC.load_models(task, put_models(task, doc, "none.json"), items)) == 1, f"{language}: the second call loads"
    if language == "java":
        other = LANG["java"]
        text = other["head"] + "        assertEquals(1, a);\n" + other["tail"]
        spec_j = PBC.parse_node(other["node"])
        one = PBC.checks_of(text.encode(), spec_j, PBC._reader_entry(spec_j), [], [], [])[0]
        assert "actual" not in PBC._check_doors(text.encode(), spec_j, one), "java assertEquals names no argument: no `actual` door"
        message = refusal_of(lambda: PBC.plan_model(text.encode(), spec_j, [entry_for(one, "actual", actual="5")], [one]))
        assert message is not None and "Doors that open for it" in message and "actual" not in message.split("Doors that open for it")[1], message


# --- t-2064 P3: our marker on the check as written ---------------------------------------------------------------------------------------
# After the value edit one token per check goes into the message of the check that was not inverted. Every way the marker cannot go in is
# a plan WITHOUT it and a note (the row then goes to the role): the error direction is "the role decides", never `intended_failure`.

def token_of(key: str, started_at: str = "t0") -> str:
    return PBC.marker_token("IID", "sha", started_at, key)


def marked_plan(language: str, entries_of, tokens_of=None, **world_args):
    """(new text, details, listed, text) of `plan_model` with one token per check key of the plan."""
    data, spec, listed, text = mworld(language, **world_args)
    tokens = {c["key"]: token_of(c["key"]) for c in listed} if tokens_of is None else tokens_of(listed)
    out, details = PBC.plan_model(data, spec, entries_of(listed), listed, tokens, "IID")
    return text_of(out), details, listed, text, tokens


@pytest.mark.parametrize("language", LANGUAGES)
def test_marker_on_uninverted_statement(language):
    """A model's check carries the marker as written: the value edit is in, the matcher, the expected value and the line count are as
    written, the marker EXPRESSION is in the file and the contiguous `qa-probe-<token>` is nowhere (it is joined at run time). A form that
    takes no message (xUnit `Assert.Equal`) is planned the same and carries none."""
    for kind, entry_args in (("actual", {"actual": "999"}), ("find", {"find": "a, 2", "replace": "a, 5"})):
        new, details, listed, text, tokens = marked_plan(language, lambda c: [entry_for(c[0], kind, **entry_args)])
        token, expression = tokens[listed[0]["key"]], AD.marker_expression(entry_of(language), tokens[listed[0]["key"]])
        assert new.count("\n") == text.count("\n"), f"{language} {kind}: line count kept"
        assert "qa-probe-" + token not in new, f"{language} {kind}: the contiguous marker must not stand in the source"
        if kind == "actual":
            assert "999" in new and any(m in new for m in (".toBe(1)", "== 1", "Equal(1", "isEqualTo(1)")), f"{language}: the value edit is in, the matcher as written"
        if listed[0]["has_message"]:
            assert expression in new and details[0]["message_marker"] == "qa-probe-" + token and details[0]["message_form"], f"{language} {kind}: {details[0]}"
            assert expression in details[0]["statement_after"], f"{language} {kind}: the detail shows the statement as planned"
        else:
            assert expression not in new and details[0]["message_marker"] == "" and details[0]["message_form"] == "", f"{language} {kind}: {details[0]}"
            assert "takes no message" in details[0]["message_note"], f"{language}: the detail says why: {details[0]['message_note']}"
    assert [c["has_message"] for c in mworld(language)[2]][:1] == [language != "csharp"], f"{language}: which forms take a message is the table's"
    data, spec, listed, _text = mworld(language)
    if listed[0]["invertible"] and listed[0]["has_message"]:
        token = token_of(listed[0]["key"])
        out, details = PBC.plan_model(data, spec, [entry_for(listed[0], "invert", invert="no other value is known")], listed, {listed[0]["key"]: token}, "IID")
        assert details[0]["message_marker"] == "qa-probe-" + token and AD.marker_expression(entry_of(language), token) in text_of(out), \
            f"{language}: an `invert` entry keeps the planner's own marker: {details[0]}"


def python_world(body: str, head: str = "", node: str = "tests/test_t.py::test_run"):
    """(data, spec, listed) of a Python test whose body is `body`."""
    text = head + "def test_run():\n    a = 1\n" + body if not head else head + body
    spec = PBC.parse_node(node)
    return text.encode("utf-8"), spec, PBC.checks_of(text.encode("utf-8"), spec, None, [], [], [])


def python_marked(body: str, head: str = "", node: str = "tests/test_t.py::test_run", **entry_args):
    data, spec, listed = python_world(body, head, node)
    token = token_of(listed[0]["key"])
    entry = entry_for(listed[0], "find" if "find" in entry_args else "actual", **entry_args)
    out, details = PBC.plan_model(data, spec, [entry], listed, {listed[0]["key"]: token}, "IID")
    return text_of(out), details[0], AD.marker_expression(entry_of("python"), token), token


def test_python_assert_marker_uninverted():
    """The AST reader: `assert (<test>), <expression>` with the author's message replaced (N2's rule), `assert_that`'s message at its
    slot with the keywords kept and BEFORE them, the `unittest` method's `msg=` keyword, a Playwright chain's head `message=`; each parses and keeps the line count."""
    new, detail, expression, token = python_marked('    assert a == 1, "c1"\n', actual="999")
    assert new.endswith(f"    assert (999 == 1), {expression}\n") and "c1" not in new, f"the author's message is replaced: {new!r}"
    assert detail["message_marker"] == "qa-probe-" + token and detail["message_form"] == "PY-assert", detail
    new, _d, expression, _t = python_marked('    assert a == 1\n', actual="2")
    assert new.endswith(f"    assert (2 == 1), {expression}\n"), f"an assert with no message gets one: {new!r}"
    new, _d, expression, _t = python_marked('    assert (a ==\n            1), "x"\n', actual="2")
    assert new.count("\n") == 4 and expression in new, f"a statement over two lines keeps its lines: {new!r}"
    new, detail, expression, _t = python_marked('    assert_that(a, equal_to(1), reason="r")\n', actual="2")
    assert new.endswith(f"    assert_that(2, equal_to(1), {expression}, reason=\"r\")\n"), f"positional message BEFORE the keywords: {new!r}"
    uni = "import unittest\n\n\nclass T(unittest.TestCase):\n    def test_run(self):\n        b = 3\n"
    new, detail, expression, _t = python_marked('        self.assertEqual(b, 1, msg="x")\n', head=uni, node="tests/test_t.py::T::test_run", find="b = 3", replace="b = 4")
    assert f"self.assertEqual(b, 1, msg={expression})" in new and "b = 4" in new and '"x"' not in new, f"the unittest keyword is replaced: {new!r}"
    assert detail["message_form"] == "PY-unittest", detail
    pw = "from playwright.sync_api import expect\n\n\ndef test_run(page):\n    b = 3\n"
    new, detail, expression, _t = python_marked('    expect(page.locator("x")).to_have_text("y")\n', head=pw, find="b = 3", replace="b = 4")
    assert f'expect(page.locator("x"), message={expression}).to_have_text("y")' in new, f"the chain's head carries the message: {new!r}"


@pytest.mark.parametrize("language", LANGUAGES)
def test_two_tokens_no_prefix(language):
    """One token per check: 12 hex, never equal and never the prefix of another; two checks of one run each carry their own."""
    data, spec, listed, text = mworld(language, second=True)
    tokens = {c["key"]: token_of(c["key"]) for c in listed}
    a, b = tokens[listed[0]["key"]], tokens[listed[1]["key"]]
    assert a != b and re.fullmatch(r"[0-9a-f]{12}", a) and re.fullmatch(r"[0-9a-f]{12}", b), f"{language}: {a} {b}"
    many = {token_of(f"tests/x.spec.ts:{n}") for n in range(300)}
    assert len(many) == 300 and not any(x != y and (PBC.MARKER_PREFIX + y).startswith(PBC.MARKER_PREFIX + x) for x in many for y in many), \
        f"{language}: no token is the prefix of another"
    out, details = PBC.plan_model(data, spec, [entry_for(listed[0], "actual", index=1, actual="7"), entry_for(listed[1], "actual", index=2, actual="8")],
                                  listed, tokens, "IID")
    new = text_of(out)
    if listed[0]["has_message"]:
        entry = entry_of(language)
        assert AD.marker_expression(entry, a) in new and AD.marker_expression(entry, b) in new, f"{language}: each check carries its own: {new!r}"
        assert [d["message_marker"] for d in details] == ["qa-probe-" + a, "qa-probe-" + b], f"{language}: {details}"
    else:
        assert [d["message_marker"] for d in details] == ["", ""], f"{language}: no form takes a message, no marker: {details}"


@pytest.mark.parametrize("language", LANGUAGES)
def test_token_differs_per_run(language):
    """`started_at` is the run's: the same check in two runs gets two tokens (an alone rerun never shares the joint run's), and the file
    each plan writes carries only its own."""
    data, spec, listed, _text = mworld(language)
    key = listed[0]["key"]
    first, second = token_of(key, "run 1"), token_of(key, "run 2")
    assert first != second, f"{language}: one token per run"
    outs = [text_of(PBC.plan_model(data, spec, [entry_for(listed[0], "actual", actual="7")], listed, {key: t}, "IID")[0]) for t in (first, second)]
    if listed[0]["has_message"]:
        entry = entry_of(language)
        assert AD.marker_expression(entry, first) in outs[0] and AD.marker_expression(entry, second) not in outs[0], f"{language}: {outs[0]!r}"
        assert AD.marker_expression(entry, second) in outs[1], f"{language}: {outs[1]!r}"


@pytest.mark.parametrize("language", ["csharp", "typescript", "python"])
def test_model_no_message_form_no_marker(language):
    """A check whose form takes no message (xUnit Equal), one whose conditions miss (a Playwright expect in a file with no Playwright
    import), and a Python form with no message slot: the edit is planned, no marker, the detail says so, and no refusal."""
    if language == "csharp":
        data, spec, listed, _text = mworld(language)
    elif language == "typescript":
        fx = LANG[language]
        text = (fx["head"].replace("import { test, expect } from '@playwright/test';", "import { test, expect } from 'vitest';")
                + PRE_T[language].format(n="b", call=CALL[language]) + "  expect(a).toBe(1);\n" + fx["tail"])
        spec = PBC.parse_node(fx["node"])
        data, listed = text.encode("utf-8"), PBC.checks_of(text.encode("utf-8"), spec, PBC._reader_entry(spec), [], [], [])
    else:
        body = "    self_like = 1\n    with pytest.raises(ValueError):\n        raise ValueError()\n"
        data, spec, listed = python_world(body, head="import pytest\n\n\ndef test_run():\n")
    key = listed[0]["key"]
    entry = entry_for(listed[0], "find", find="a, 1", replace="a, 2") if language != "python" else entry_for(listed[0], "find", find="self_like = 1", replace="self_like = 2")
    if language == "csharp":
        entry = entry_for(listed[0], "actual", actual="999")
    out, details = PBC.plan_model(data, spec, [entry], listed, {key: token_of(key)}, "IID")
    assert details[0]["message_marker"] == "" and details[0]["message_form"] == "" and details[0]["message_note"], f"{language}: {details[0]}"
    assert "qa-probe" not in text_of(out), f"{language}: no marker in the file"
    assert text_of(out) != data.decode("utf-8-sig"), f"{language}: the edit is planned all the same"
    assert PBC.plan_model(data, spec, [entry], listed)[1][0]["message_note"] == "no marker is put in by this call", f"{language}: no token, no note about a marker"


# --- t-2064 P4b item 2: a call with no `--at` and no `--oracle` walks the plan (the flip of `_probe`) -------------------------------------
# End to end through `probe()` on the stub runner of `test_probe_walk.World`: the project, the story and the dispatch are the World's own
# (`flip`), the model file is written with `probe_entries` or by hand, the stage of the dispatch row is `world.stage`. A red names the
# branch (the test and its message); each test names the mutation of the code that kills it.

import probe_entries as PE  # noqa: E402
import test_probe_walk as TW  # noqa: E402


class Killed(BaseException):
    """The process dying between two rows (not an `Exception`: nothing in the tool may swallow it)."""


def flip(tmp_path, monkeypatch, kinds="sss", stage="S5", **world_args):
    """A World wired under `PBC.probe`: its root is the project, its task folder the story's, `world.stage` the stage `_dispatch_stage`
    reads (`--s6-close` is `ctx.stage == "S6"` and asks nobody)."""
    world = TW.World(tmp_path, kinds, **world_args).install(monkeypatch)
    world.stage = stage
    world.scenario = TW.fire(*range(len(world.keys)))
    monkeypatch.setattr(PBC, "project_root", lambda: world.root)
    monkeypatch.setattr(PBC, "artifacts_dir", lambda task: world.task_root)
    monkeypatch.setattr(PBC, "load_config", lambda: {})
    monkeypatch.setattr(PBC, "parse_node", lambda test, root=None: world.spec)
    monkeypatch.setattr(PBC, "manifest_entry", lambda task_root, iid: {"case": "TC-1"})
    monkeypatch.setattr(PBC, "_test_path", lambda root, cfg, spec, entry=None: (world.path, world.root))
    monkeypatch.setattr(PBC, "_dispatch_context",
                        lambda root, task, task_root, dispatch, case, s6_close: ("S6CLOSE", "S6") if s6_close else (dispatch, ""))
    monkeypatch.setattr(PBC, "_dispatch_stage", lambda root, task, dispatch, case: world.stage)
    # the binding facts a receipt claims (the manifest and run blocks the World has none of): the test bytes are the author's, as measured
    monkeypatch.setattr(PBC.proof_level, "binding_facts", lambda task_root, iid: {
        "case_version": "v1", "test_content_hash": hashlib.sha256(world.original).hexdigest(), "source_revision": "rev1", "build_id": "b1"})
    return world


def flip_call(world, **more):
    args = {"dispatch": "D", "mutation": "invert", "timeout": 100, "oracle": "", "at": None, **more}
    return PBC.probe("T", args.pop("dispatch"), TW.NODE, "i1", args.pop("mutation"), args.pop("timeout"), args.pop("oracle"), args.pop("at"), **args)


def flip_models(world, entries, dispatch="D"):
    path = world.task_root / "work" / "probe-models" / f"{dispatch}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"models": entries}), encoding="utf-8")


def flip_actual(world, keys=None, supposes="s"):
    return [{"check": key, "supposes": supposes, "actual": "2"} for key in (world.keys if keys is None else keys)]


def flip_snapshot(*roots) -> dict:
    return {f"{root.name}/{path.relative_to(root).as_posix()}": path.read_bytes() for root in roots for path in sorted(root.rglob("*")) if path.is_file()}


def flip_refusal(world, **more) -> str:
    with pytest.raises(PBC.Refusal) as caught:
        flip_call(world, **more)
    return str(caught.value)


def test_no_model_refused_before_a_byte(tmp_path, monkeypatch):
    """No model for any check under a role: the refusal names every key and its doors, and NOTHING moved - no run, no lock file, no
    record, no copy, the author's bytes as they were. Killed by: walking (or taking `_lock_test`) before `_models_refusal`."""
    world = flip(tmp_path, monkeypatch, "sss")
    before = flip_snapshot(world.root, world.task_root)
    text = flip_refusal(world)
    assert all(key in text for key in world.keys) and "work/probe-models/D.json" in text and "Nothing was changed" in text, text
    assert flip_snapshot(world.root, world.task_root) == before, "not a byte written: no record, no lock, no copy"
    assert world.runs == [], "no run"
    flip_models(world, flip_actual(world, world.keys[:2]))
    one_owed = flip_refusal(world)
    assert world.keys[2] in one_owed and world.keys[0] not in one_owed.split("Checks, with the doors")[1].split("Write work")[0], one_owed


@pytest.mark.parametrize("stage", ["S5", ""])
def test_mutation_invert_flag_is_no_bypass(tmp_path, monkeypatch, stage):
    """A critic's dispatch (stage S5, or a stage that cannot be read) with `--mutation invert` and no entry is refused: the flag selects
    nothing and is never read as "no role". Killed by: `_no_role` reading `ctx.mutation`."""
    world = flip(tmp_path, monkeypatch, "ss", stage=stage)
    text = flip_refusal(world, mutation="invert")
    assert "no model is stored" in text and world.runs == [], f"stage {stage!r}: {text}"


def test_s6_dispatch_is_no_role(tmp_path, monkeypatch):
    """A running S6 dispatch and no model: every check is inverted by code, `reason: "no role at this call"`, and the aggregate says so.
    Killed by: `_no_role` returning False for a dispatch row of stage S6 (the refusal comes)."""
    world = flip(tmp_path, monkeypatch, "sss", stage="S6")
    record = flip_call(world)
    assert [row["probe_kind"] for row in record["checks"]] == ["invert"] * 3, record["checks"]
    assert {row["reason"] for row in record["checks"]} == {PBC.NO_ROLE_REASON} == {"no role at this call"}
    assert all(row["entry"]["invert"] == "no role at this call" for row in record["checks"]), "the entry as written is stored"
    assert record["verdict"] == "intended_failure" and len(world.runs) == 1, "three soft checks, one joint run"
    assert json.loads((world.task_root / "work" / "probes" / "i1.json").read_text())["record"] == "work/probes/i1.json"


def test_s6_close_is_no_role(tmp_path, monkeypatch):
    """`--s6-close` is no role by itself: the dispatch row is not even asked. Killed by: `_no_role` asking only the dispatch row."""
    world = flip(tmp_path, monkeypatch, "ss", stage="S5")
    monkeypatch.setattr(PBC, "_dispatch_stage", lambda *a: pytest.fail("the S6 close context needs no dispatch row"))
    record = flip_call(world, dispatch="", s6_close=True)
    assert {row["probe_kind"] for row in record["checks"]} == {"invert"} and record["verdict"] == "intended_failure", record["checks"]
    assert record["dispatch_id"] == "S6CLOSE" or record["checks"], "the context's own id names the call"


@pytest.mark.parametrize("stage", ["", "s6", "S60", "S5", "S7"])
def test_unknown_stage_refuses(tmp_path, monkeypatch, stage):
    """A stage that is not exactly S6 - unreadable, another word, another spelling - assumes a role: the refusal, never an inversion; and
    the real reader of a dispatch that does not exist answers "". Killed by: `_no_role` true for anything but "S6"."""
    world = flip(tmp_path, monkeypatch, "ss", stage=stage)
    assert "no model is stored" in flip_refusal(world, dispatch="D"), f"stage {stage!r} is read as no role"
    assert world.runs == []
    monkeypatch.undo()
    assert PBC._dispatch_stage(tmp_path / "nowhere", "T", "D", "TC-1") == "", "a row that cannot be read is an empty stage"


def test_stored_entry_before_inversion(tmp_path, monkeypatch):
    """A model stored in the instance's aggregate is applied under no role BEFORE an inversion is written (EP-U), including after the key
    moved: it is joined by the statement's sha and its `check` rewritten. Killed by: step 3 (the inversion) before step 2 (the stored
    entry), or a join by line."""
    world = flip(tmp_path, monkeypatch, "ss", stage="S5")
    world.scenario = lambda w, run: [TW.row("passed")]
    flip_models(world, flip_actual(world))
    first = flip_call(world)
    assert {row["verdict"] for row in first["checks"]} == {"no_failure"} and (world.task_root / "work" / "probes" / "i1.json").is_file()
    (world.task_root / "work" / "probe-models" / "D.json").unlink()
    world.stage = "S6"
    world.scenario = lambda w, run: [TW.row("failed", TW.thrown(w, run, *run["tokens"]))]
    moved = world.text.replace("    a = 1\n", "    a = 1\n    b = 2\n")
    world.path.write_bytes(moved.encode())
    world.original = moved.encode()
    second = flip_call(world)
    assert [row["probe_kind"] for row in second["checks"]] == ["actual", "actual"], "the stored models, not inversions"
    assert [row["entry"]["check"] for row in second["checks"]] == [row["key"] for row in second["checks"]] != world.keys, "joined to the moved keys"
    assert any("joined by its sha" in note for note in second["notes"]), second["notes"]
    assert [row["key"] for row in second["checks"]] == [f"{TW.FILE}:4", f"{TW.FILE}:5"], "the keys moved by one line"


def test_stored_find_that_no_longer_stands_is_not_applied(tmp_path, monkeypatch):
    """A stored `find` whose text is gone from the bytes is not applied: owed under a role, an inversion with a note under no role.
    Killed by: joining a stored entry without asking the planner whether it stands."""
    world = flip(tmp_path, monkeypatch, "ss", stage="S5", extra="")
    world.text = world.text.replace("    a = 1\n", "    a = 1\n    seed = 7\n")
    world.path.write_bytes(world.text.encode())
    world.original = world.text.encode()
    world.checks = PBC.checks_of(world.original, world.spec, None, [], [], [])
    world.keys = [c["key"] for c in world.checks]
    world.scenario = lambda w, run: [TW.row("passed")]
    flip_models(world, [{"check": key, "supposes": "s", "find": "seed = 7", "replace": "seed = 8"} for key in world.keys])
    flip_call(world)
    gone = world.text.replace("    seed = 7\n", "    seed = 9\n")
    world.path.write_bytes(gone.encode())
    world.original = gone.encode()
    (world.task_root / "work" / "probe-models" / "D.json").unlink()
    assert "no model is stored" in flip_refusal(world), "a role: owed, the stored find does not stand"
    world.stage = "S6"
    record = flip_call(world)
    assert {row["probe_kind"] for row in record["checks"]} == {"invert"} and any("no longer stands" in n for n in record["notes"]), record["notes"]


def test_all_not_here_no_receipt(tmp_path, monkeypatch):
    """Every check `not_here`: nothing runs, the aggregate states `not_owed` rows and `incomplete`/`judgment` - never a proof, no receipt.
    Killed by: reading an all-`not_owed` plan as `intended_failure`, or not writing the record for a plan with no live key."""
    world = flip(tmp_path, monkeypatch, "ss", stage="S5")
    flip_models(world, [{"check": key, "instance": "i1", "not_here": "this instance never reaches it"} for key in world.keys])
    record = flip_call(world)
    assert world.runs == [] and [row["verdict"] for row in record["checks"]] == ["not_owed", "not_owed"], record["checks"]
    assert record["verdict"] == "incomplete" and record["cause"] == "judgment" and record["receipt"] is None and record["failure_kind"] is None
    assert (world.task_root / "work" / "probes" / "i1.json").is_file() and world.path.read_bytes() == world.original
    assert not (world.task_root / "work" / "sensitivity-receipts").exists()


def test_invert_null_under_no_role_others_walk(tmp_path, monkeypatch):
    """EP-R: under no role a check whose form has `invert: null` is not a refusal of the call: its row is `incomplete`, `cause: tooling`
    and says why, the others walk. Killed by: refusing the whole call, or inverting the form that has no inversion."""
    real = PBC.checks_of
    monkeypatch.setattr(PBC, "checks_of", lambda *a, **k: [dict(c, invertible=(i != 0)) for i, c in enumerate(real(*a, **k))])
    world = flip(tmp_path, monkeypatch, "sss", stage="S6")
    world.checks = PBC.checks_of(world.original, world.spec, None, [], [], [])
    world.keys = [c["key"] for c in world.checks]
    world.scenario = TW.fire(1, 2)
    record = flip_call(world)
    first, rest = record["checks"][0], record["checks"][1:]
    assert first["verdict"] == "incomplete" and first["cause"] == "tooling" and "invert: null" in first["note"], first
    assert [row["verdict"] for row in rest] == ["intended_failure"] * 2 and sorted(world.runs[0]["tokens"]) == world.keys[1:], "the others walk"
    assert record["verdict"] == "incomplete" and record["cause"] == "tooling", "a tooling row is no proof of the plan"


def test_killed_walk_keeps_rows(tmp_path, monkeypatch):
    """The process dies in row 2 before the restore: row 1's per-check record and the aggregate stand, the copy is left, and the next
    call restores it (`scan_copies` through `_lock_test`) and runs only what is not proved. Killed by: writing the aggregate only at the
    end, or planning the second call from the mutated bytes."""
    world = flip(tmp_path, monkeypatch, "hh", stage="S6")
    world.scenario = lambda w, run: [TW.row("failed", TW.thrown(w, run, *run["tokens"]))] if len(w.runs) == 1 else (_ for _ in ()).throw(Killed())
    real_restore = PBC.restore

    def dies(*a, **k):
        raise Killed()
    monkeypatch.setattr(PBC, "restore", lambda *a, **k: real_restore(*a, **k) if len(world.runs) == 1 else dies())
    with pytest.raises(Killed):
        flip_call(world)
    stored = json.loads((world.task_root / "work" / "probes" / "i1.json").read_text())
    assert [row["verdict"] for row in stored["checks"]] == ["intended_failure", "not_reached"] and stored["plan_unfinished"] is True, stored["checks"]
    assert (world.task_root / "work" / "probes" / "checks").is_dir() and len(list((world.task_root / "work" / "probes" / "checks").glob("*.json"))) == 1
    assert world.path.read_bytes() != world.original and list(PBC.copy_dir(world.root).glob("*.meta")), "the kill left the copy"
    monkeypatch.setattr(PBC, "restore", real_restore)
    world.scenario = lambda w, run: [TW.row("failed", TW.thrown(w, run, *run["tokens"]))]
    done = len(world.runs)
    record = flip_call(world)
    assert world.path.read_bytes() == world.original, "the next call put the author's bytes back"
    assert len(world.runs) == done + 1 and sorted(world.runs[-1]["tokens"]) == [world.keys[1]], "only the unproved row ran, on the author's bytes"
    assert record["verdict"] == "intended_failure" and record["plan_unfinished"] is False, record["checks"]


def test_repeat_skips_proved_runs_new_model(tmp_path, monkeypatch):
    """The same call on the same bytes with the same models runs nothing (proved rows are skipped, the answer is still the aggregate); a
    changed model runs its check again. Killed by: ignoring `_check_proved`, or leaving the entry's sha out of it."""
    world = flip(tmp_path, monkeypatch, "ss", stage="S5")
    flip_models(world, flip_actual(world))
    first = flip_call(world)
    assert first["verdict"] == "intended_failure" and len(world.runs) == 1
    again = flip_call(world)
    assert len(world.runs) == 1 and again["verdict"] == "intended_failure" and [r["verdict"] for r in again["checks"]] == ["intended_failure"] * 2
    receipt = first["receipt"]
    assert isinstance(receipt, dict) and again["receipt"] == receipt, "the receipt stands: the same file, the same bytes, nothing new written"
    assert len(list((world.task_root / "work" / "sensitivity-receipts").glob("*.json"))) == 1
    flip_models(world, flip_actual(world, supposes="another supposition"))
    changed = flip_call(world)
    assert len(world.runs) == 2, "a new entry sha runs again"
    assert changed["receipt"] and changed["receipt"]["path"] != receipt["path"], "a changed entry set is another receipt, never the old one"


def test_one_check_same_record_shape(tmp_path, monkeypatch):
    """A plan of ONE check answers in today's shape: location, reason, restore, record path and the failure kind the readers read (EP-A).
    Killed by: an aggregate that drops a key `acceptance` / `_receipt_core` read, or an unequal location pair."""
    world = flip(tmp_path, monkeypatch, "s", stage="S5")
    flip_models(world, flip_actual(world))
    record = flip_call(world)
    assert record["verdict"] == "intended_failure" and record["failure_kind"] == "assertion" and record["mutation"] == "invert"
    assert record["expected_location"] == record["actual_location"] == f"{TW.FILE}:3"
    assert record["expected_reason"] == record["actual_reason"] and record["restore"]["verified"] is True
    assert record["record"] == "work/probes/i1.json" and record["test_node"] == TW.NODE and record["mutation_detail"]["line"] == 3
    assert "at" not in record["mutation_detail"] and record["target"]["line"] == 3 and len(record["checks"]) == 1
    assert json.loads((world.task_root / "work" / "probes" / "i1.json").read_text())["verdict"] == "intended_failure"


def test_no_check_at_all_is_a_refusal(tmp_path, monkeypatch):
    """EP-A: a test with no check of a form the factory reads is a refusal naming the data row and `--at`, never a pass and never a
    record. Killed by: walking an empty plan into an aggregate."""
    world = flip(tmp_path, monkeypatch, "s", stage="S6")
    world.text = "def test_run():\n    a = 1\n"
    world.path.write_bytes(world.text.encode())
    world.original = world.text.encode()
    text = flip_refusal(world)
    assert "detectors.json" in text and "--at" in text and "never read as proved" in text, text
    assert not (world.task_root / "work" / "probes").exists() and world.runs == []


def test_printed_door_runs_second_call(tmp_path, monkeypatch):
    """The door the refusal prints opens: its model file path and its `invert` example, filled in, make the second call walk. Killed by:
    a refusal that prints a path other than the one `_entries_for` reads."""
    world = flip(tmp_path, monkeypatch, "ss", stage="S5")
    text = flip_refusal(world)
    path = re.search(r"the model file (work/probe-models/\S+?\.json):", text).group(1)
    assert path == "work/probe-models/D.json" and "Write work/probe-models/D.json as" in text, text      # the head and the Write name the real file
    example = next(line for line in text.splitlines() if line.strip().startswith("invert:")).split("invert:", 1)[1].strip()
    assert "<key>" in example
    target = world.task_root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({"models": [json.loads(example.replace("<key>", key).replace("<why no other value is known>", "no other value is known"))
                                              for key in world.keys]}), encoding="utf-8")
    record = flip_call(world)
    assert record["verdict"] == "intended_failure" and {row["probe_kind"] for row in record["checks"]} == {"invert"}
    assert {row["reason"] for row in record["checks"]} == {"no other value is known"}, "a critic's reason, not the code's"


def test_probe_entries_helper_writes_what_the_flip_reads(tmp_path, monkeypatch):
    """The wrappers' helper (`write_invert_entries`) feeds the same road a critic's file does. Killed by: a path or shape the loader
    does not read."""
    world = flip(tmp_path, monkeypatch, "ss", stage="S5")
    PE.write_invert_entries(world.task_root, "D", keys=world.keys)
    record = flip_call(world)
    assert {row["probe_kind"] for row in record["checks"]} == {"invert"} and record["verdict"] == "intended_failure" and len(world.runs) == 1


# --- t-2064 P4b item 4: the receipt of a walk (EP-K) ------------------------------------------------------------------------------------

def receipts_of(world) -> list:
    folder = world.task_root / "work" / "sensitivity-receipts"
    return sorted(folder.glob("*.json")) if folder.is_dir() else []


def read_receipt(world, record) -> dict:
    return json.loads((world.task_root / record["receipt"]["path"]).read_text(encoding="utf-8"))


def stored_aggregate(world) -> dict:
    return json.loads((world.task_root / "work" / "probes" / "i1.json").read_text(encoding="utf-8"))


def test_all_checks_or_no_receipt(tmp_path, monkeypatch):
    """A survivor among proved checks: no receipt (EP-K); the call that proves the last one attaches it. Killed by: attaching when at least
    one check is proved, or from the per-check records instead of the aggregate."""
    world = flip(tmp_path, monkeypatch, "sss", stage="S5")
    world.scenario = TW.absent_scenario(lambda w, run: [TW.row("passed")])
    flip_models(world, flip_actual(world))
    partial = flip_call(world)
    assert [r["verdict"] for r in partial["checks"]] == ["intended_failure", "no_failure", "no_failure"], partial["checks"]
    assert partial["verdict"] == "no_failure" and partial["receipt"] is None and receipts_of(world) == [], "two of three proved: no receipt"
    assert stored_aggregate(world)["receipt"] is None
    world.scenario = TW.fire(0, 1, 2)
    runs = len(world.runs)
    assert flip_call(world)["verdict"] == "no_failure" and len(world.runs) == runs, "t-2411 F3: the same entries on the same bytes carry the survivors, no run"
    flip_models(world, flip_actual(world, supposes="another supposition"))      # a changed entry is what runs the survivors again (repinned: it was the bare call)
    done = flip_call(world)
    assert done["verdict"] == "intended_failure" and done["receipt"] and len(receipts_of(world)) == 1, done["checks"]
    assert stored_aggregate(world)["receipt"] == done["receipt"], "the receipt is named by the aggregate, the one writer"


def test_all_not_here_through_to_the_receipt(tmp_path, monkeypatch):
    """Every check `not_here`: nothing proved, so no receipt file and the answer names none (the receipt rule reached, binding facts present).
    Killed by: reading an all-`not_owed` plan as complete."""
    world = flip(tmp_path, monkeypatch, "ss", stage="S5")
    flip_models(world, [{"check": key, "instance": "i1", "not_here": "never reached"} for key in world.keys])
    record = flip_call(world)
    assert record["receipt"] is None and record["receipt_missing"] == [] and receipts_of(world) == [], record


def test_not_here_counts_not_as_proof(tmp_path, monkeypatch):
    """A `not_here` row neither proves nor blocks: the other checks proved -> a receipt, whose `checks` shows the row as `not_owed`.
    Killed by: counting `not_owed` as unproved (no receipt), or as proved."""
    world = flip(tmp_path, monkeypatch, "sss", stage="S5")
    world.scenario = TW.fire(0, 1)
    models = flip_actual(world, world.keys[:2]) + [{"check": world.keys[2], "instance": "i1", "not_here": "never reached"}]
    flip_models(world, models)
    record = flip_call(world)
    assert record["verdict"] == "intended_failure" and record["receipt"], record["checks"]
    assert [c["verdict"] for c in read_receipt(world, record)["checks"]] == ["intended_failure", "intended_failure", "not_owed"]


def test_wall_leaves_plan_unfinished_then_continues(tmp_path, monkeypatch):
    """The wall cuts the walk: `plan_unfinished`, NO receipt; the continuing call finishes the plan and attaches it. Killed by: attaching on
    a plan that is unfinished, or not attaching after the continuing call completes."""
    world = flip(tmp_path, monkeypatch, "hhh", stage="S6")
    world.scenario = lambda w, run: [TW.row("failed", TW.thrown(w, run, *run["tokens"]))]
    world.step = 60.0
    cut = flip_call(world, timeout=100)
    assert cut["plan_unfinished"] is True and cut["verdict"] == "incomplete" and cut["receipt"] is None and receipts_of(world) == [], cut["checks"]
    world.step = 0.0
    done = flip_call(world, timeout=100)
    assert done["plan_unfinished"] is False and done["verdict"] == "intended_failure" and done["receipt"] and len(receipts_of(world)) == 1


def test_receipt_carries_checks(tmp_path, monkeypatch):
    """The receipt names each check: key, statement sha, the entry sha THE PER-CHECK RECORD carries, verdict; it points at the aggregate.
    Killed by: leaving `checks` out of `_receipt_core`, or an entry sha computed another way than the walk's."""
    world = flip(tmp_path, monkeypatch, "ss", stage="S5")
    flip_models(world, flip_actual(world))
    record = flip_call(world)
    receipt = read_receipt(world, record)
    assert receipt["probe_record"] == "work/probes/i1.json" and receipt["proof_level"] == PBC.proof_level.LIVE
    assert [(c["key"], c["verdict"]) for c in receipt["checks"]] == [(k, "intended_failure") for k in world.keys]
    assert [c["entry_sha"] for c in receipt["checks"]] == [world.record(k)["entry_sha"] for k in world.keys] and all(c["entry_sha"] for c in receipt["checks"])
    assert [c["statement_sha"] for c in receipt["checks"]] == [row["statement_sha"] for row in record["checks"]] and receipt["checks"][0]["statement_sha"]


def test_changed_model_old_receipt_not_live(tmp_path, monkeypatch):
    """One model changes and the rerun does not finish (a cut run: `not_executed`): the call returns NO receipt and the stored aggregate keeps
    the old proved record (`keep_standing_record`, with `last_attempt`); the field a reader compares is `receipt.checks[].entry_sha` against the entry set in
    play, and it differs for the changed check. When the call completes again, the receipt is another file. Killed by: a receipt with no
    `entry_sha` per check, or re-attaching the old receipt to the new set."""
    world = flip(tmp_path, monkeypatch, "ss", stage="S5")
    flip_models(world, flip_actual(world))
    first = flip_call(world)
    old = first["receipt"]
    new_models = flip_actual(world, supposes="another supposition")
    flip_models(world, new_models)
    real_run = PBC.run_request

    def cut(root, request_path, timeout):
        raise PBC.subprocess.TimeoutExpired("run", timeout)
    monkeypatch.setattr(PBC, "run_request", cut)
    second = flip_call(world)
    assert second["verdict"] != "intended_failure" and second["receipt"] is None, "no receipt while the plan is not proved"
    kept = stored_aggregate(world)
    assert kept["verdict"] == "intended_failure" and kept["receipt"] == old and kept["last_attempt"]["verdict"] == second["verdict"]
    stood_on = [c["entry_sha"] for c in json.loads((world.task_root / old["path"]).read_text(encoding="utf-8"))["checks"]]
    in_play = [PBC._entry_sha({**m, "kind": "actual", "instance": "", "alternative": ""}) for m in new_models]
    assert stood_on and all(a != b for a, b in zip(stood_on, in_play)), "the old receipt does not stand for the new entry set"
    monkeypatch.setattr(PBC, "run_request", real_run)
    third = flip_call(world)
    assert third["receipt"] and third["receipt"]["path"] != old["path"] and stored_aggregate(world)["receipt"] == third["receipt"]


def test_publish_binding_after_a_complete_walk_has_a_receipt(tmp_path, monkeypatch):
    """`publish_binding` on the answer of a complete walk no longer says "no live receipt"; on an incomplete one it publishes nothing.
    Killed by: not attaching the receipt in the aggregate (the old interim state)."""
    world = flip(tmp_path, monkeypatch, "ss", stage="S5")
    flip_models(world, flip_actual(world))
    monkeypatch.setattr(PBC, "_put_fragment", lambda task, fragment: PBC.subprocess.CompletedProcess([], 0, "", ""))
    said = PBC.publish_binding("T", world.task_root, flip_call(world))
    assert "no live receipt" not in said, said


def test_models_refusal_names_the_real_path_and_no_flag(tmp_path, monkeypatch):
    """FR-2: the refusal of a plain call names the model file at the real path of the dispatch id - no literal placeholder, and no
    `--model` flag the plain call does not take. Killed by: printing `<dispatch>` or `--model` again."""
    world = flip(tmp_path, monkeypatch, "ss", stage="S5")
    for dispatch in ("D", "D2"):
        text = flip_refusal(world, dispatch=dispatch)
        assert f"work/probe-models/{dispatch}.json" in text and "<dispatch>" not in text and "--model" not in text, text


# --- t-2064 P4b item 3: `--at` and `--oracle` are plans of the selected rows (EP-O, EP-S) ----------------------------------------------------
# The same road as a plain call (`flip`): one row (`--at`) or the checks of one function (`--oracle`) runs, the aggregate is rebuilt over the WHOLE
# plan, a receipt only when the plan is complete. A red names the branch (the test and its message); each test names the mutation that kills it.

HELPER_TWO = 'def expect(a):\n    assert a == 1, "h1"\n    assert a == 1, "h2"\n'
FIRE_ALL = lambda w, run: [TW.row("failed", "\n".join(f"AssertionError: qa-probe-{t}" for t in TW.TOKEN.findall(run["bytes"].decode())))]  # noqa: E731


def edited_lines(run: dict) -> list:
    """The 1-based lines of the run's bytes that carry a marker: what the run edited."""
    return [n for n, line in enumerate(run["bytes"].decode().splitlines(), 1) if TW.TOKEN.search(line)]


def test_at_no_entry_refused(tmp_path, monkeypatch):
    """`--at` on a check with no entry, under a role, is the refusal of a plain call - the keys, the doors, the real model file - and NOTHING
    moves; the flag `--mutation invert` beside it does not open a way out. Another owed check is not named. Killed by: `--at` skipping
    `_entries_for` (an inversion written for the critic), reading the flag as no role, or refusing for every owed check of the plan."""
    world = flip(tmp_path, monkeypatch, "sss", stage="S5")
    before = flip_snapshot(world.root, world.task_root)
    for more in ({}, {"mutation": "invert"}):
        text = flip_refusal(world, at=4, **more)
        assert world.keys[1] in text and "work/probe-models/D.json" in text and "Nothing was changed" in text, text
        assert world.keys[0] not in text and world.keys[2] not in text, f"only the selected row is owed here: {text}"
    assert flip_snapshot(world.root, world.task_root) == before and world.runs == [], "no run, no record, no copy"
    flip_models(world, flip_actual(world, [world.keys[0]]))
    assert world.keys[1] in flip_refusal(world, at=f"{TW.FILE}:4"), "an entry for ANOTHER check is no entry for the selected one"


def test_at_never_publishes_partial(tmp_path, monkeypatch):
    """One row of three proved: the aggregate says the plan is unfinished and NO receipt exists, the stored aggregate names none; the call that
    proves the last row attaches it. Killed by: attaching a receipt on a selection, or an aggregate that holds only the selected row."""
    world = flip(tmp_path, monkeypatch, "sss", stage="S5")
    world.scenario = FIRE_ALL
    flip_models(world, flip_actual(world))
    for line in (4, 3):
        record = flip_call(world, at=line)
        assert record["receipt"] is None and record["plan_unfinished"] is False and receipts_of(world) == [], (line, record["checks"])
        assert record["verdict"] == "incomplete" and record["cause"] == "judgment", "t-2411 cause: models owed to the critic, not the tool's failure"
        assert record["verdict"] != "intended_failure" and stored_aggregate(world)["receipt"] is None
    done = flip_call(world, at=5)
    assert [r["verdict"] for r in done["checks"]] == ["intended_failure"] * 3 and done["receipt"] and len(receipts_of(world)) == 1, done["checks"]
    assert done["plan_unfinished"] is False and [edited_lines(r) for r in world.runs] == [[4], [3], [5]], "one row per call"


def test_at_fills_the_aggregate(tmp_path, monkeypatch):
    """The selected row gets its per-check record (and only it); the aggregate lists the WHOLE plan in plan order, the unselected rows keep what
    their records say - proved on these bytes with the same entry: carried as proved, no run - and the receipt appears at once when that
    completes the plan. Killed by: no per-check record for the row, an aggregate of the selected row alone, a carried row that reads
    `not_reached`, or a carried row run again."""
    world = flip(tmp_path, monkeypatch, "sss", stage="S5")
    world.scenario = FIRE_ALL
    flip_models(world, flip_actual(world))
    first = flip_call(world, at=3)
    assert [r["key"] for r in first["checks"]] == world.keys and [r["verdict"] for r in first["checks"]][0] == "intended_failure"
    assert {r["verdict"] for r in first["checks"][1:]} == {"not_reached"}, "the rows the selection did not run are unsettled"
    assert len(list((world.task_root / "work" / "probes" / "checks").glob("*.json"))) == 1, "one per-check record: the selected row's"
    assert world.record(world.keys[0])["verdict"] == "intended_failure"
    flip_call(world, at=5)
    done = flip_call(world, at=4)
    assert [r["verdict"] for r in done["checks"]] == ["intended_failure"] * 3, done["checks"]
    assert [edited_lines(r) for r in world.runs] == [[3], [5], [4]], "the rows the record proves are carried and run no more"
    assert done["receipt"] and stored_aggregate(world)["receipt"] == done["receipt"] and len(receipts_of(world)) == 1


def test_at_second_on_line(tmp_path, monkeypatch):
    """`--at <line>` on a line with two checks is the first, `<line>#2` the second; the other stays on the plan, unrun. Killed by: reading
    `#2` as the first (the first runs), or the first's selection covering the second (EP-O)."""
    world = flip(tmp_path, monkeypatch, "s", stage="S5")
    text = 'def test_run():\n    a = 1\n    assert a == 1, "c1"; assert a == 1, "c2"\n'
    world.path.write_bytes(text.encode())
    world.original = text.encode()
    keys = [c["key"] for c in PBC._plan_of_test(world.ctx, world.root)[0]]
    assert keys == [f"{TW.FILE}:3", f"{TW.FILE}:3#2"], keys
    world.scenario = FIRE_ALL
    flip_models(world, flip_actual(world, keys))
    second = flip_call(world, at="3#2")
    assert [r["verdict"] for r in second["checks"]] == ["not_reached", "intended_failure"], second["checks"]
    run = world.runs[-1]["bytes"].decode()
    assert run.count("qa-probe") == 1 and run.index("qa-probe") > run.index('"c1"') and 'assert a == 1, "c1";' in run, "only the second was edited"
    first = flip_call(world, at=f"{TW.FILE}:3")
    assert [r["verdict"] for r in first["checks"]] == ["intended_failure"] * 2 and len(world.runs) == 2, "the first by head order, the second carried"
    assert "does not hold check number 3" in flip_refusal(world, at="3#3"), "a line with two checks has no third"


@pytest.mark.parametrize("given, want", [("12", 12), ("12#1", 12), ("12#2", "12#2"), ("tests/t.py:12", "tests/t.py:12"), ("tests/t.py:12#1", "tests/t.py:12"),
                                         ("tests/t.py:12#2", "tests/t.py:12#2"), ("a#b.py:7", "a#b.py:7")])
def test_at_arg_accepts_the_ordinal_spellings(given, want):
    """`--at` takes `<line>#<n>` and `<file>:<line>#<n>` (n >= 1; `#1` is no suffix), the spelling EP-O and the code's own texts promise.
    Killed by: `_at_arg` that does not know `#` (argparse refuses the documented spelling)."""
    assert PBC._at_arg(given) == want


@pytest.mark.parametrize("given", ["12#0", "12#x", "#", "12#", "#2", "12#-1", "-3", "tests/t.py:#2", "tests/t.py:12#0", ":12#2", ""])
def test_at_arg_refuses_the_other_spellings_naming_the_accepted_ones(given):
    """`#0`, `#x`, a bare `#`, a negative, an empty line part: the argument's refusal form, naming the accepted spellings.
    Killed by: a loose pattern that lets any `#...` tail through, or a refusal that does not name `#<n>`."""
    import argparse
    with pytest.raises(argparse.ArgumentTypeError) as caught:
        PBC._at_arg(given)
    assert "--at wants" in str(caught.value) and "12#2" in str(caught.value) and repr(given) in str(caught.value), str(caught.value)


def test_at_second_check_end_to_end_through_the_parser(tmp_path, monkeypatch):
    """`--at 3#2` as the COMMAND LINE spells it (the real parser, then the walk): the second check of a two-check line is proved and the
    first is not run. Killed by: `_at_arg` refusing `#2` (SystemExit at parse) or handing the line without the ordinal (the first runs)."""
    world = flip(tmp_path, monkeypatch, "s", stage="S5")
    text = 'def test_run():\n    a = 1\n    assert a == 1, "c1"; assert a == 1, "c2"\n'
    world.path.write_bytes(text.encode())
    world.original = text.encode()
    keys = [c["key"] for c in PBC._plan_of_test(world.ctx, world.root)[0]]
    world.scenario = FIRE_ALL
    flip_models(world, flip_actual(world, keys))
    args = PBC._build_parser().parse_args(["--task", "T", "--at", "3#2"])
    assert args.at == "3#2", args.at
    record = flip_call(world, at=args.at)
    assert [r["verdict"] for r in record["checks"]] == ["not_reached", "intended_failure"], record["checks"]


def test_oracle_selects_rows(tmp_path, monkeypatch):
    """`--oracle <function>` selects the checks of that function - and only them - through the same road: they run, the body's checks stay
    unsettled, no receipt. An oracle that names no function, or one that holds no check, is the refusal, never a pass, and nothing moves;
    `<file>::<function>` wins the file. Killed by: an oracle that selects the whole plan or the test's first check, a refusal that
    is a pass, or a selection that ignores the function's span."""
    world = flip(tmp_path, monkeypatch, "ss", stage="S5", extra=HELPER_TWO)
    world.scenario = FIRE_ALL
    before = flip_snapshot(world.root, world.task_root)
    for bad in ("nothing_here", "test_run_never_declared", f"{TW.FILE}::absent"):
        assert "selects no check" in flip_refusal(world, oracle=bad), bad
    assert flip_snapshot(world.root, world.task_root) == before and world.runs == [], "a refusal moved nothing"
    keys = [c["key"] for c in PBC._plan_of_test(world.ctx, world.root, [(TW.FILE, world.path, "5-7")])[0]]
    assert keys == [f"{TW.FILE}:{n}" for n in (3, 4, 6, 7)], keys
    flip_models(world, flip_actual(world, keys))
    for oracle in ("expect", f"{TW.FILE}::expect"):
        record = flip_call(world, oracle=oracle)
        assert [r["verdict"] for r in record["checks"]] == ["not_reached", "not_reached", "intended_failure", "intended_failure"], (oracle, record["checks"])
        assert record["receipt"] is None and receipts_of(world) == [] and record["plan_unfinished"] is False
        assert record["verdict"] == "incomplete" and record["cause"] == "judgment", "t-2411 cause: models owed to the critic, not the tool's failure"
    assert [edited_lines(r) for r in world.runs] == [[6], [7]], "a check outside the body runs alone, each once; the second call carries them as proved"
    done = flip_call(world)
    assert [r["verdict"] for r in done["checks"]] == ["intended_failure"] * 4 and done["receipt"], "a plain call finishes the plan: the receipt"
    assert [edited_lines(r) for r in world.runs][-1] == [3, 4], "only the body's checks were left to run"


def test_at_on_a_non_check_line_refused(tmp_path, monkeypatch):
    """A line that holds no check (the setup line, a blank, past the end) is the existing refusal - it names the nearest check below - and
    nothing moves; a nonsense `--at` is the call's mistake. Killed by: probing the nearest check instead, or a pass."""
    world = flip(tmp_path, monkeypatch, "ss", stage="S5")
    flip_models(world, flip_actual(world))
    before = flip_snapshot(world.root, world.task_root)
    text = flip_refusal(world, at=2)
    assert "line 2" in text and "holds no check" in text and "`--at 3`" in text, text
    assert "holds no check" in flip_refusal(world, at=99) and "count from 1" in flip_refusal(world, at=0) and "--at wants" in flip_refusal(world, at="abc")
    assert flip_snapshot(world.root, world.task_root) == before and world.runs == [], "nothing moved"


def test_at_helper_line_joins_the_plan_and_stays_owed(tmp_path, monkeypatch):
    """A check of a helper outside the plan is a real check: `--at` adds it to the plan (its row is in the aggregate, with the whole plan),
    and from then on it is owed - the next PLAIN call is refused for its entry, and `--plan`'s gatherer lists it. Killed by: a plan that does
    not take the line, or one that forgets it on the next call."""
    world = flip(tmp_path, monkeypatch, "ss", stage="S5", extra='def helper(a):\n    assert a == 1, "h"\n')
    world.scenario = FIRE_ALL
    assert world.keys == [f"{TW.FILE}:3", f"{TW.FILE}:4"], "the plan of the test alone has no helper line"
    helper = f"{TW.FILE}:6"
    flip_models(world, flip_actual(world, [helper]))
    record = flip_call(world, at=f"{TW.FILE}:6")
    assert [r["key"] for r in record["checks"]] == world.keys + [helper], record["checks"]
    assert record["checks"][-1]["verdict"] == "intended_failure" and record["receipt"] is None and edited_lines(world.runs[-1]) == [6]
    assert {r["verdict"] for r in record["checks"][:2]} == {"incomplete"}, "the body's checks are owed: no model stands for them yet"
    flip_models(world, flip_actual(world, world.keys))
    done = flip_call(world)
    assert [r["key"] for r in done["checks"]] == world.keys + [helper] and done["receipt"], "the next plain call walks the plan WITH the helper's row"
    assert [edited_lines(r) for r in world.runs][-1] == [3, 4], "the helper's row stands as proved: only the body's rows ran"
    keys = [c["key"] for c in PBC._plan_of_test(world.ctx, world.root)[0]]
    assert keys == world.keys + [helper], "the one gatherer of `--plan` and the walk lists it"
    changed = world.original.replace(b'assert a == 1, "h"', b'assert a == 3, "h"')
    world.path.write_bytes(changed)
    world.original = changed
    text = flip_refusal(world)
    assert helper in text and "no model is stored" in text and world.keys[0] not in text, f"a changed helper statement is owed again: {text}"


def test_mutation_expected_door_names_the_invert_entry(tmp_path, monkeypatch):
    """FR-2: the refusal of the removed `--mutation expected` names the `invert` ENTRY of the model file, not the flag `--mutation invert` (a
    flag selects nothing). Killed by: printing `use --mutation invert` again."""
    world = flip(tmp_path, monkeypatch, "ss", stage="S5")
    text = flip_refusal(world, mutation="expected")
    assert "--mutation expected was removed" in text and "`invert` entry" in text and '"invert":' in text and "work/probe-models/" in text, text
    assert "use --mutation invert" not in text and "Nothing was changed" in text and world.runs == []


# --- t-2064 P4b item 5: `--judge <instance> --check <key>` (the judgment is recorded per check, the aggregate re-folded) ----------------------

def judged_world(tmp_path, monkeypatch, kinds="hh", scenario=None):
    """A walk of `kinds` whose first check is owed a judgment (a failure with no marker) and whose others fire by their markers; the
    judge's reads of the instance (bytes, dispatch) are stubbed to the World's own."""
    world = flip(tmp_path, monkeypatch, kinds, stage="S5")
    world.scenario = scenario or (lambda w, run: [TW.row("failed", "boom: the badge was empty")] if len(w.runs) == 1
                                  else [TW.row("failed", TW.thrown(w, run, *run["tokens"]))])
    flip_models(world, flip_actual(world))
    record = flip_call(world)
    monkeypatch.setattr(PBC.proof_level, "current_test_sha", lambda entry, root: hashlib.sha256(world.original).hexdigest())
    monkeypatch.setattr(PBC, "_judge_dispatch_why", lambda root, record, dispatch: "")
    return world, record


def judge_check(world, check="", verdict="fires", quote="the badge was empty", why=""):
    return PBC.judge_record(world.task_root, world.root, "i1", "D", verdict, quote, why, check)


def judge_refusal(world, **more) -> str:
    with pytest.raises(PBC.Refusal) as caught:
        judge_check(world, **more)
    return str(caught.value)


def test_judge_by_check_rebuilds_aggregate(tmp_path, monkeypatch):
    """One check owes the judgment, the other is proved: `--judge` with no `--check` judges THAT one (the single unsettled), writes the
    judgment on its per-check record, and the aggregate is rebuilt by `_aggregate_record` from every record - `intended_failure`, the receipt
    now present. Killed by: judging the aggregate's flat keys (no per-check write), not re-folding the aggregate, a receipt on the old
    aggregate, or the per-check record left `incomplete` (the next walk would run it again)."""
    world, walked = judged_world(tmp_path, monkeypatch)
    assert [r["verdict"] for r in walked["checks"]] == ["incomplete", "intended_failure"] and walked["receipt"] is None, walked["checks"]
    facts = world.record(world.keys[0])["judgment_facts"]
    assert facts["check_key"] == world.keys[0] and facts["model"]["actual"] == "2" and facts["author_green"] is True, facts
    record = judge_check(world)
    assert record["verdict"] == "intended_failure" and [r["verdict"] for r in record["checks"]] == ["intended_failure"] * 2, record["checks"]
    assert record["checks"][0]["judgment"]["verdict"] == "fires" and record["checks"][0]["proved_by"] == "critic" and record["receipt"], record
    stored = world.record(world.keys[0])
    assert stored["verdict"] == "intended_failure" and stored["judgment"]["by"] == "D" and stored["entry_sha"], "the per-check record is the proof now"
    assert json.loads((world.task_root / "work" / "probes" / "i1.json").read_text())["receipt"] == record["receipt"], "the aggregate on disk"
    runs = len(world.runs)
    assert "already carries a judgment" in judge_refusal(world, check=world.keys[0]) and len(world.runs) == runs


def test_judge_check_named_among_several_unsettled(tmp_path, monkeypatch):
    """Two checks owe a judgment: no `--check` is a refusal that LISTS the unsettled keys (door names `--check`); an unknown key is a refusal
    that lists the plan's keys; naming one judges it and leaves the other owed - no receipt on one of two. `cannot_judge` re-folds too.
    Killed by: taking the first unsettled check, a refusal without keys, an unknown key read as 'none', or a receipt over an owed check."""
    world, walked = judged_world(tmp_path, monkeypatch, scenario=lambda w, run: [TW.row("failed", "boom: the badge was empty")])
    assert [r["verdict"] for r in walked["checks"]] == ["incomplete", "incomplete"], walked["checks"]
    before = flip_snapshot(world.root, world.task_root)
    text = judge_refusal(world)
    assert all(key in text for key in world.keys) and "--check" in text, text
    unknown = judge_refusal(world, check="nowhere.py:9")
    assert all(key in unknown for key in world.keys) and "nowhere.py:9" in unknown, unknown
    assert flip_snapshot(world.root, world.task_root) == before, "a refusal writes nothing"
    record = judge_check(world, check=world.keys[1], verdict="cannot_judge", quote="", why="the page is gone")
    assert [r["verdict"] for r in record["checks"]] == ["incomplete", "incomplete"] and record["checks"][1]["judgment"]["verdict"] == "cannot_judge"
    assert record["receipt"] is None and "judged by the code critic (D)" in record["notes"][-1]
    record = judge_check(world, check=world.keys[0])
    assert [r["verdict"] for r in record["checks"]] == ["intended_failure", "incomplete"] and record["verdict"] == "incomplete" and record["receipt"] is None


def test_judge_no_failure_refused_door(tmp_path, monkeypatch):
    """A check that survived its inversion (`no_failure`) is not weighed by `--judge`: the refusal names `not_here` and a `test_defect`
    finding. Killed by: judging a `no_failure` check as if a failure were owed, or a refusal with no door."""
    world, walked = judged_world(tmp_path, monkeypatch, "h", scenario=lambda w, run: [TW.row("passed")])
    assert walked["checks"][0]["verdict"] == "no_failure", walked["checks"]
    text = judge_refusal(world, check=world.keys[0])
    assert "no_failure" in text and "not_here" in text and "test_defect" in text and "Nothing was written" in text, text
    assert "no check of this probe owes a judgment" in judge_refusal(world)


AFTER_JUDGED = "2999-01-01T00:00:00+00:00"      # a person's word given after every judgment written by a test


def readers(world, walked) -> dict:
    """What the readers the window and the gate use say about the aggregate on disk NOW: `{owes, plain, could_not_run, state, facts}`."""
    pl, sha = PBC.proof_level, walked["test_file_sha256"]
    return {"owes": pl.probe_owes_judgment(world.task_root, "i1", sha), "plain": pl.probe_plain_call_owed(world.task_root, "i1", sha),
            "could_not_run": pl.probe_could_not_run(world.task_root, "i1", sha), "state": pl.probe_record_state(world.task_root, "i1", sha),
            "facts": pl.cannot_judge_facts(world.task_root, "i1", sha)}


def test_cannot_judge_per_check_opens_the_persons_door(tmp_path, monkeypatch):
    """B2 (fix round D), on records the REAL producers write (`_walk_plan` then `judge_record --check`, which re-folds): two checks owe a judgment
    - the walk reads `unjudged`, goes to the critic's `--judge`, the person's door is shut; the critic says `cannot_judge` on ONE - still
    `unjudged` (the other is owed), no facts; on BOTH - the aggregate itself reads `cannot_judge` (`probe_record_state`, `probe_owes_judgment`)
    and `cannot_judge_facts` gives the person the facts, `why` naming each key; `probe_could_not_run` stays False throughout (a judgment cause is
    never the tool's); the person's `probe not proved: <case>` word is read only then, and names the unproved checks. A settling judgment
    (`other_failure` on one, `cannot_judge` on the other) moves the aggregate on: the state is `judged`, no door of the person's. Killed by:
    `_judgment_fold` not writing the top-level `judgment` / `judgment_facts` (the person's door never opens: `owes` stays `unjudged`), writing
    them while one row still owes `--judge` (the person is asked early), or a fold that reads one `cannot_judge` among rows as all."""
    import contract as C
    import window_record as WR
    world, walked = judged_world(tmp_path, monkeypatch, scenario=lambda w, run: [TW.row("failed", "boom: the badge was empty")])
    keys = world.keys
    now = readers(world, walked)
    assert (now["owes"], now["plain"], now["could_not_run"], now["facts"]) == ("unjudged", False, False, None), now       # nobody judged: the critic's
    assert now["state"]["judgment_owed"] == keys, now["state"]
    after_one = judge_check(world, check=keys[1], verdict="cannot_judge", quote="", why="the page is gone")
    now = readers(world, after_one)
    assert (now["owes"], now["plain"], now["facts"]) == ("unjudged", False, None) and "judgment" not in after_one, (now, after_one.get("judgment"))
    assert now["state"]["judgment_owed"] == [keys[0]], now["state"]
    both = judge_check(world, check=keys[0], verdict="cannot_judge", quote="", why="it threw first")
    now = readers(world, both)
    assert both["verdict"] == "incomplete" and both["cause"] == "judgment" and both["judgment"]["verdict"] == "cannot_judge" and both["judgment_owed"] == []
    assert (now["owes"], now["plain"], now["could_not_run"], now["state"]["judgment"]) == ("cannot_judge", False, False, "cannot_judge"), now
    facts = now["facts"]
    assert facts is not None and keys[0] in facts["why"] and keys[1] in facts["why"] and "it threw first" in facts["why"] and "the page is gone" in facts["why"], facts
    assert facts["file"] == TW.FILE and facts["line"] and facts["at"], facts
    item = {"instance_id": "i1", "input_hash": walked["test_file_sha256"], "outcome": "passed"}
    word = {"stage_overrides": [{"stage": "S5", "match": "probe not proved: CASE-A", "decision": "go on", "at": AFTER_JUDGED}]}
    block = WR.probe_gap_block(world.task_root, item, ["CASE-A"], {}, None, C.probe_not_proved_words(word))
    assert block is not None and block["named_by"] == "probe not proved: CASE-A" and "could not judge it: " in block["why"], block
    assert WR.probe_gap_block(world.task_root, item, ["CASE-B"], {}, None, C.probe_not_proved_words(word)) is None, "a word about another case names nothing"
    # a settling judgment: the aggregate re-folds and the state moves on
    other = tmp_path / "b"
    other.mkdir()
    world2, walked2 = judged_world(other, monkeypatch, scenario=lambda w, run: [TW.row("failed", "boom: the badge was empty")])
    judge_check(world2, check=world2.keys[1], verdict="cannot_judge", quote="", why="the page is gone")
    settled = judge_check(world2, check=world2.keys[0], verdict="other_failure", quote="boom: the badge was empty")
    now = readers(world2, settled)
    assert settled["verdict"] == "wrong_location" and now["state"]["state"] == "judged" and now["owes"] == "" and now["facts"] is None, (settled["verdict"], now)


def test_selection_incomplete_routes_to_the_plain_call(tmp_path, monkeypatch):
    """B2, the first critic's routing note: an `--at` call over other unproved rows ends `incomplete`/`judgment` with NO check owing `--judge`
    (the rows are merely not selected). `judgment_owed` is `[]`, `probe_plain_call_owed` is True (the window's note and `probe_word_door` read it
    and name the plain call, not `--judge`, which would refuse), `probe_owes_judgment` still says `unjudged` (no person's word names it),
    `probe_could_not_run` is False. The control: a walk with a check that does owe a judgment is NOT plain-call-owed. Killed by:
    `probe_plain_call_owed` True for a record that lists an owed check (the critic sent to the plain call), or False for the selection
    (the critic sent to a `--judge` that refuses)."""
    import window_record as WR
    world = flip(tmp_path, monkeypatch, "sss", stage="S5")
    world.scenario = FIRE_ALL
    flip_models(world, flip_actual(world))
    record = flip_call(world, at=3)
    assert record["verdict"] == "incomplete" and record["cause"] == "judgment" and record["judgment_owed"] == [], record["checks"]
    now = readers(world, record)
    assert (now["owes"], now["plain"], now["could_not_run"], now["facts"]) == ("unjudged", True, False, None), now
    window = {"instances": [{"instance_id": "i1", "input_hash": record["test_file_sha256"], "outcome": "passed", "probe_gap": {"verdict": "incomplete"}}]}
    door = WR.probe_word_door(window, world.task_root, "T", "REST")
    assert WR.PLAIN_CALL_NOTE in door and WR.PROBE_DOOR in door and PBC.JUDGE_DOOR not in door and "REST" not in door, door
    control = tmp_path / "c"
    control.mkdir()
    cworld, cwalked = judged_world(control, monkeypatch, scenario=lambda w, run: [TW.row("failed", "boom: the badge was empty")])
    assert readers(cworld, cwalked)["plain"] is False
    cdoor = WR.probe_word_door({"instances": [{"instance_id": "i1", "input_hash": cwalked["test_file_sha256"], "outcome": "passed",
                                               "probe_gap": {"verdict": "incomplete"}}]}, cworld.task_root, "T", "REST")
    assert PBC.JUDGE_DOOR in cdoor and WR.PLAIN_CALL_NOTE not in cdoor, cdoor


# --- t-2064 P4b items 6 and 7: `not_here`, `product`, the wall ------------------------------------------------------------------------------

def product_receipt(world, location, level=None, name="r.json") -> str:
    path = world.task_root / "work" / "sensitivity-receipts" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"proof_level": level or PBC.proof_level.PRODUCT, "assertion_location": location}), encoding="utf-8")
    return path.relative_to(world.task_root).as_posix()


def test_not_here_door_on_no_failure(tmp_path, monkeypatch):
    """A check that survived its inversion reads `no_failure` and its row note names the door `not_here` (EP-T) and a `test_defect` finding;
    a `not_here` entry makes ONLY that check `not_owed`, with the entry's reason, and leaves the other row's standing alone. Killed by: a
    `no_failure` row note without the door, or a `not_here` entry that rewrites the other rows."""
    world = flip(tmp_path, monkeypatch, "hh", stage="S5")
    world.scenario = lambda w, run: [TW.row("passed")]
    flip_models(world, flip_actual(world))
    record = flip_call(world)
    assert [r["verdict"] for r in record["checks"]] == ["no_failure", "no_failure"], record["checks"]
    assert all("not_here" in r["note"] and "test_defect" in r["note"] for r in record["checks"]), record["checks"]
    world.scenario = TW.fire(0, 1)
    flip_models(world, [{"check": world.keys[0], "instance": "i1", "not_here": "this instance never reaches it"}]
                + flip_actual(world, world.keys[1:], supposes="another supposition"))      # a changed entry: a survivor of the same one is carried (t-2411 F3)
    again = flip_call(world)
    first, second = again["checks"]
    assert (first["verdict"], first["reason"], first["probe_kind"]) == ("not_owed", "this instance never reaches it", "not_here"), first
    assert second["verdict"] == "intended_failure" and second["probe_kind"] == "actual" and again["verdict"] == "intended_failure", second


def real_receipt(world, monkeypatch, location, *, hash_of=None, file=None) -> tuple:
    """`(path under the story folder, receipt dict)` of a product receipt written by the REAL producer (`red_sandbox.write_sensitivity_receipts`)
    for the world's test, and the manifest row `ctx.entry` that names its instance and file (what `manifest_entry` gives the call). `hash_of`
    binds the receipt to other bytes; `file` is the test file the producer reads the suffix from."""
    import red_sandbox as RS
    (world.task_root / "state").mkdir(exist_ok=True)
    (world.task_root / "state" / "controller.json").write_text(json.dumps({"plan_contract_mode": "new"}), encoding="utf-8")
    binding = {"case_version": "cv_abc", "test_content_hash": hash_of or hashlib.sha256(world.original).hexdigest(), "source_revision": "source",
               "build_id": "build", "restoration_evidence": "restored-hash"}
    target = {"instance_id": "i1", "expected_location": location, "expected_reason": "denied", "mutation_kind": "real_behavior"}
    result = {"instance_id": "i1", "status": "failed", "failure_kind": "assertion", "location": location, "reason": "denied",
              "semantic_verdict": "intended_failure"}
    refs = RS.write_sensitivity_receipts(world.task_root, {"repo": str(world.task_root), "original_hashes": {}, "targets": [target]}, [result],
                                         {"i1": binding}, identity={"i1": {"test_file": file}} if file else None)
    row = {"instance_id": "i1", "case": "TC-1", "file": TW.FILE, "case_version_links": [{"version": "cv_abc"}]}
    monkeypatch.setattr(PBC, "manifest_entry", lambda task_root, iid: dict(row))
    path = refs["i1"]["receipt_ref"]["path"]
    return path, json.loads((world.task_root / path).read_text(encoding="utf-8"))


def test_product_entry_holds_or_is_refused(tmp_path, monkeypatch):
    """B1 (fix round D): a `product` entry that names a receipt written by the REAL producer (`scope: one_check`, `checks: [its key]`) proves THAT
    check by the critic's word through the receipt's real validity (no monkeypatch of the reader): the row reads `product`, `critic`, no run for
    it; the other check stays owed (it survived), so the aggregate has no receipt of the walk. The same receipt for ANOTHER check, a receipt of
    other bytes, a `whole_unlisted` one, an absent path, another level, a path outside the story folder, an unread location: each is a refusal
    that names what actually failed, with the door, and nothing moves. An old receipt (no `scope`, no `checks`) holds as before. Killed by:
    `_product_entry_holds` asking `valid_level` (None for `one_check`: the first call refuses), dropping the key join (the `another check` case
    proves), a join that skips `product_receipt_holds`' byte guard (`other bytes`), or the `whole_unlisted` refusal removed."""
    world = flip(tmp_path, monkeypatch, "hh", stage="S5")
    keys = world.keys
    line, other_line = world.checks[0]["line"], world.checks[1]["line"]
    good, receipt = real_receipt(world, monkeypatch, f"{TW.FILE}:{line}")
    assert receipt["scope"] == "one_check" and [c["key"] for c in receipt["checks"]] == [f"{TW.FILE}:{line}"], receipt
    assert PBC.proof_level.valid_level(PBC.manifest_entry(world.task_root, "i1"), {"path": good}, world.task_root) is None, "the level reader says None by design"
    world.scenario = lambda w, run: [TW.row("passed")]      # the other check is walked and survives: it stays owed
    flip_models(world, [{"check": keys[0], "instance": "i1", "product": good}] + flip_actual(world, keys[1:]))
    record = flip_call(world)
    first, second = record["checks"]
    assert (first["verdict"], first["proved_by"], first["probe_kind"], first["product"]) == ("intended_failure", "critic", "product", good), first
    assert second["verdict"] == "no_failure" and record["verdict"] == "no_failure" and record["receipt"] is None, (second, record["verdict"])
    assert len(world.runs) == 1 and sorted(world.runs[0]["tokens"]) == keys[1:], "no run for the product row"
    # the join's own answers, by the one reader the entry calls
    held = PBC._product_entry_holds
    world_ctx = PBC.ProbeCtx(*world.ctx[:5], PBC.manifest_entry(world.task_root, "i1"), *world.ctx[6:])
    assert held(world_ctx, {"product": good}, world.checks[0]) == ""
    assert held(world_ctx, {"product": good}, world.checks[1]) != "" and keys[0].split(":")[1] in held(world_ctx, {"product": good}, world.checks[1])
    # an old receipt (no `scope`, no `checks`): holds by its location alone, as before
    from event_store import content_hash

    def old_style(name: str, **over) -> str:
        """The receipt as it was written before P6 (no `scope`, no `checks`), re-hashed, with `over` changed."""
        body = {k: v for k, v in receipt.items() if k not in ("scope", "checks", "receipt_hash")}
        body.update(over)
        body["receipt_hash"] = content_hash(body)
        path = world.task_root / "work" / "sensitivity-receipts" / name
        path.write_text(json.dumps(body), encoding="utf-8")
        return path.relative_to(world.task_root).as_posix()
    old_ref = old_style("old.json")
    assert held(world_ctx, {"product": old_ref}, world.checks[0]) == "" and "span" in held(world_ctx, {"product": old_ref}, world.checks[1])
    other_bytes, _r = real_receipt(world, monkeypatch, f"{TW.FILE}:{line}", hash_of="0" * 64)
    unlisted, _r = real_receipt(world, monkeypatch, "tests/t.zzz:4", file="tests/t.zzz")
    assert _r["scope"] == "whole_unlisted"
    for why, shown in (("it proves", real_receipt(world, monkeypatch, f"{TW.FILE}:{other_line}")[0]),         # a receipt of the OTHER check
                       ("other bytes", other_bytes),
                       ("cannot list", unlisted),
                       ("not on the span", old_style("a.json", assertion_location=f"{TW.FILE}:{line + 1}")),      # an old receipt names no key: the span alone
                       ("level", old_style("b.json", proof_level="live")),
                       ("no readable JSON receipt", "work/sensitivity-receipts/absent.json"),
                       ("not a path under the story folder", str((world.root / TW.FILE).resolve())),
                       ("does not speak", old_style("c.json", assertion_location=""))):      # no location: the receipt fails its OWN contract first, and says so
        flip_models(world, [{"check": keys[0], "instance": "i1", "product": shown}] + flip_actual(world, keys[1:]))
        before = flip_snapshot(world.root, world.task_root)
        text = flip_refusal(world)
        assert why in text and keys[0] in text and "Nothing was changed" in text and "`actual`, `find` or `invert`" in text, (why, text)
        if why in ("it proves", "cannot list", "not on the span"):      # the TRUE reason: not the old catch-all about the test's bytes
            assert "does not speak for the test as it stands" not in text, (why, text)
        if why == "does not speak":
            assert "assertion_location is required" in text, text
        assert flip_snapshot(world.root, world.task_root) == before and len(world.runs) == 1, f"{why}: a refusal moves nothing"


def test_plan_unfinished_not_a_persons_door(tmp_path, monkeypatch):
    """A walk the call's time cut off writes `incomplete`/`tooling`/`plan_unfinished: true`; `probe_record_state` reads it as the state
    `plan_unfinished` and `probe_could_not_run` is False (the same call again continues it, a person is not asked). The control: the same
    record without the key is `incomplete` and `could_not_run` stays True; a record of other bytes is `not_run`. Killed by: no
    `plan_unfinished` branch in `probe_record_state`, or `probe_could_not_run` true for it."""
    world = flip(tmp_path, monkeypatch, "hh", stage="S5")
    world.step = 500.0
    flip_models(world, flip_actual(world))
    record = flip_call(world, timeout=100)
    assert record["verdict"] == "incomplete" and record["cause"] == "tooling" and record["plan_unfinished"] is True and record["plan_remaining"], record
    sha = record["test_file_sha256"]
    state = PBC.proof_level.probe_record_state(world.task_root, "i1", sha)
    assert state["state"] == "plan_unfinished" and state["cause"] == "" and state["record"], state
    assert PBC.proof_level.probe_could_not_run(world.task_root, "i1", sha) is False
    path = PBC.record_path(world.task_root, "i1")
    stored = json.loads(path.read_text())
    del stored["plan_unfinished"]
    path.write_text(json.dumps(stored), encoding="utf-8")
    assert PBC.proof_level.probe_record_state(world.task_root, "i1", sha)["state"] == "incomplete", "an old record reads as before"
    assert PBC.proof_level.probe_could_not_run(world.task_root, "i1", sha) is True
    assert PBC.proof_level.probe_record_state(world.task_root, "i1", "0" * 64)["state"] == "not_run"


def test_oracle_aggregate_carries_function_and_helper_note(tmp_path, monkeypatch):
    """`--oracle <function>` leaves `oracle_function` in the aggregate's `mutation_detail` and keeps the old road's line in `notes`: the oracle was
    named by hand, and a check living in a helper other tests may share is mutated only for the length of one run (AR-21). A plain call
    carries neither. Killed by: dropping `oracle_function` from `mutation_detail`, or the helper line from the notes."""
    world = flip(tmp_path, monkeypatch, "ss", stage="S5", extra=HELPER_TWO)
    world.scenario = FIRE_ALL
    keys = [c["key"] for c in PBC._plan_of_test(world.ctx, world.root, [(TW.FILE, world.path, "5-7")])[0]]
    flip_models(world, flip_actual(world, keys))
    record = flip_call(world, oracle="expect")
    assert record["mutation_detail"]["oracle_function"] == "expect", record["mutation_detail"]
    assert any("oracle was named by hand: expect" in n and "other tests may share" in n for n in record["notes"]), record["notes"]
    plain = flip_call(world)
    assert "oracle_function" not in plain["mutation_detail"] and not any("named by hand" in n for n in plain["notes"])


def test_selected_not_here_row_keeps_earlier_proofs(tmp_path, monkeypatch):
    """`--at` on a row that is now `not_here` runs nothing, and the other rows are carried from their per-check records as PROVED, not
    `not_reached`; the receipt follows the plan's completeness alone. Killed by: an aggregate of a no-run selection that reads the unselected
    rows as `not_reached`."""
    world = flip(tmp_path, monkeypatch, "hh", stage="S5")
    flip_models(world, flip_actual(world))
    assert flip_call(world)["receipt"], "the whole plan proved first"
    runs = len(world.runs)
    flip_models(world, [{"check": world.keys[0], "instance": "i1", "not_here": "never reached by this instance"}])
    record = flip_call(world, at=world.checks[0]["line"])
    assert [r["verdict"] for r in record["checks"]] == ["not_owed", "intended_failure"], record["checks"]
    assert len(world.runs) == runs, "nothing ran"


def test_judge_check_flag_is_parsed():
    """`--check` is a flag of the tool; the old single form refuses it. Killed by: a parser with no `--check`."""
    assert PBC._build_parser().parse_args(["--judge", "i1", "--check", "k:3"]).check == "k:3"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q", "-p", "no:cacheprovider"]))
