#!/usr/bin/env python3
"""`manifest_put` refuses an `assertion_id` whose line holds no check (thinking-roles TR2-1; finding 20261106-proby-cel-proby-i-ostatki).

Live runs: 7 of 41 `assertion_id` values stood one line above their check (a blank line), so a probe aimed there proved nothing.
The write now cross-references the id to the file it names through the ONE reader of "what is a check on this line"
(`probe_by_code.check_on_line`): a DATA check (AR-29), refused before the commit, the unknowns a note and never a refusal (FR-59).

Each test names the mutation that kills it. The worlds are one TypeScript and one Python test file with a blank line above a
two-line check; the project is a throwaway one (`Stand`), and `tree()` is what a refusal must leave as it found it.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402

sys.path.insert(0, str(harness.SCRIPTS))
import manifest_put as MP  # noqa: E402
from test_manifest_projection import Stand  # noqa: E402

CASE = "TC-001"

# `blank` stands one line above the check, `first` is its first line, `cont` a continuation line of its statement, `past` a line
# after the last check (the file has more lines than that).
WORLDS = {
    "typescript": {
        "file": "tests/t.spec.ts",
        "text": "import { test, expect } from '@playwright/test';\ntest('t', async () => {\n  const a = 1;\n\n"
                "  expect(a,\n    'msg').toBe(1);\n  const b = 2;\n});\n",
        "blank": 4, "first": 5, "cont": 6, "past": 7},
    "python": {
        "file": "tests/test_t.py",
        "text": "def test_run():\n    a = 1\n\n    assert (a ==\n            1)\n    b = 2\n",
        "blank": 3, "first": 4, "cont": 5, "past": 6},
}
LANGUAGES = sorted(WORLDS)


@pytest.fixture
def stand():
    with Stand() as s:
        yield s


def world(stand, language):
    w = WORLDS[language]
    target = stand.root / w["file"]
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(w["text"], encoding="utf-8")
    return w


def row(w, assertion_id=None, **more) -> dict:
    out = {"instance_id": "t_instance", "file": w["file"], "covers": [CASE], "status": "green", **more}
    if assertion_id is not None:
        out["assertion_id"] = assertion_id
    return out


def put(stand, *rows):
    return stand.put({"tests": list(rows)})


@pytest.mark.parametrize("language", LANGUAGES)
def test_blank_line_above_the_check_is_refused_naming_the_line_and_the_check_below(stand, language):
    """Kill: the id's line is not looked up (a write goes through) or the refusal drops the line / the nearest check below."""
    w = world(stand, language)
    before = stand.tree()
    code, out, err = put(stand, row(w, f"{w['file']}:{w['blank']}"))
    assert code == MP.EXIT_BAD_FRAGMENT, (code, out, err)
    assert f"line {w['blank']} of {w['file']} holds no check" in err, err
    assert f"`{w['file']}:{w['first']}`" in err, f"the door is the nearest check below: {err}"
    assert stand.tree() == before, "a refused row leaves the manifest, the journal and every file as they were"


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_first_line_of_the_check_is_written(stand, language):
    """Kill: a refusal of a line the check starts on (the rule counts `starts here`)."""
    w = world(stand, language)
    code, out, err = put(stand, row(w, f"{w['file']}:{w['first']}"))
    assert code == 0, (out, err)
    assert stand.manifest()["tests"][0]["assertion_id"] == f"{w['file']}:{w['first']}"
    assert "was not checked" not in out, out


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_continuation_line_of_a_multi_line_check_is_written(stand, language):
    """Kill: a reader that counts only the line a check starts on (the statement SPANS the line: Lead decision 2)."""
    w = world(stand, language)
    code, out, err = put(stand, row(w, f"{w['file']}:{w['cont']}"))
    assert code == 0, (out, err)


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_line_below_the_last_check_is_refused_with_no_check_below(stand, language):
    """Kill: the refusal names a check that does not exist, or lets the id through when `nearest_below` is None."""
    w = world(stand, language)
    before = stand.tree()
    code, out, err = put(stand, row(w, f"{w['file']}:{w['past']}"))
    assert code == MP.EXIT_BAD_FRAGMENT, (code, out, err)
    assert f"this test has no check below line {w['past']}" in err, err
    assert stand.tree() == before


def _note_case(stand, w, assertion_id) -> str:
    code, out, err = put(stand, row(w, assertion_id))
    assert code == 0, (assertion_id, out, err)
    assert stand.manifest()["tests"][0]["assertion_id"] == assertion_id, "the write went through"
    notes = [line for line in out.splitlines() if line.startswith("assertion_id: the line was not checked")]
    assert len(notes) == 1, f"ONE note line says it: {out!r}"
    return notes[0]


@pytest.mark.parametrize("language", LANGUAGES)
def test_an_unreadable_file_is_a_note_and_the_write_goes_through(stand, language):
    """Kill: an absent file refused (the unknown became a refusal) or passed with no word (a silent pass)."""
    w = world(stand, language)
    assert "cannot be read" in _note_case(stand, w, "tests/gone.spec.ts:3")


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_suffix_with_no_reader_is_a_note(stand, language):
    """Kill: a language the table has no entry for refused (P2: the factory does not guess a grammar), or passed in silence."""
    w = world(stand, language)
    (stand.root / "tests" / "t.zzz").write_text("one\n\nthree\n", encoding="utf-8")
    assert "cannot read" in _note_case(stand, w, "tests/t.zzz:2")


@pytest.mark.parametrize("language", LANGUAGES)
def test_an_id_not_of_the_file_line_form_is_a_note(stand, language):
    """Kill: a free-text id refused (the field has always held anything) or passed with no word."""
    w = world(stand, language)
    assert "not of the form <file>:<line>" in _note_case(stand, w, f"{w['file']} the third assert")


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_file_outside_the_project_root_is_a_note_and_never_read(stand, language):
    """Kill: the id's path followed out of the project (a read of a file the project does not own)."""
    w = world(stand, language)
    outside = stand.root.parent / "outside_t.spec.ts"
    outside.write_text(WORLDS["typescript"]["text"], encoding="utf-8")
    try:
        assert "outside the project root" in _note_case(stand, w, f"../{outside.name}:4")
    finally:
        outside.unlink()


def test_a_file_that_does_not_parse_is_a_note(stand):
    """Kill: a SyntaxError of the test file escapes `run` as a traceback, or refuses the row."""
    w = WORLDS["python"]
    (stand.root / w["file"]).write_text("def test_run(:\n    assert (\n", encoding="utf-8")
    assert "cannot read" in _note_case(stand, w, f"{w['file']}:2")


def test_an_unchanged_id_on_a_row_edited_for_another_field_is_not_rechecked(stand):
    """Kill: the check reads every id of a sent row (an old manifest is broken by an unrelated edit): the id is stored while the
    file is unreadable (a note), the file then appears with a blank line there, the row is edited for `why` with the SAME id ->
    written; the same row with a CHANGED id on a blank line -> refused (the control: the check is alive)."""
    w = WORLDS["typescript"]
    stale = f"{w['file']}:{w['blank']}"
    assert put(stand, row(w, stale))[0] == 0, "stored while the file is not there yet"
    world(stand, "typescript")
    code, out, err = put(stand, row(w, stale, why="an unrelated edit"))
    assert code == 0, (out, err)
    assert "was not checked" not in out and stand.manifest()["tests"][0]["why"] == "an unrelated edit", out
    code, out, err = put(stand, row(w, f"{w['file']}:3"))
    assert code == MP.EXIT_BAD_FRAGMENT, f"control: a changed id on a line with no check is refused: {out} {err}"


def test_one_bad_row_refuses_the_whole_call_and_a_row_with_no_id_is_never_read(stand):
    """Kill: the good row of the same call written while the bad one is refused (all-or-nothing), or a row with no id read."""
    w = world(stand, "typescript")
    before = stand.tree()
    good = row(w, f"{w['file']}:{WORLDS['typescript']['first']}")
    bad = row(w, f"{w['file']}:{WORLDS['typescript']['blank']}", instance_id="other_instance")
    code, out, err = put(stand, good, bad)
    assert code == MP.EXIT_BAD_FRAGMENT and "tests[1].assertion_id" in err and "tests[0]" not in err, (out, err)
    assert stand.tree() == before
    assert put(stand, row(w, instance_id="third"))[0] == 0, "a row that carries no assertion_id is not looked at"


def test_the_reader_is_imported_only_when_an_id_row_is_sent(stand, monkeypatch):
    """Kill: `probe_by_code` imported at the top of `manifest_put` (the cost paid by every write)."""
    w = world(stand, "typescript")
    monkeypatch.delitem(sys.modules, "probe_by_code", raising=False)
    assert put(stand, row(w))[0] == 0
    assert "probe_by_code" not in sys.modules, "a write with no id row never loads the probe's reader"
    assert put(stand, row(w, f"{w['file']}:{WORLDS['typescript']['first']}", why="id"))[0] == 0
    assert "probe_by_code" in sys.modules


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q", "-p", "no:cacheprovider"]))
