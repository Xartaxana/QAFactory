#!/usr/bin/env python3
"""AR-13 for a bug draft's cases (spec t-2187, section 1 and node N3a): the cases a draft speaks for are read ONLY through
`bug_records.draft_cases` (`case`, `cases` and every manifestation's `case`). A reader that takes `case or cases` itself drops
the cases that only a manifestation names (a case covered only by a manifestation is "no draft speaks for it", and the packet,
the board and the trace each contradict the others, FR-10).

The test is a grep over every `scripts/*.py` outside `bug_records.py` (and outside `scripts/tests/`, which it never walks). The
forms it finds are the ones the readers had: `draft.get("cases")`, `data.get("case") or data.get("cases")`,
`C.case_ids(d.get("case")) or C.case_ids(d.get("cases"))`, a key loop `for key in ("id", "case", "cases")`, and the front-matter
spelling `listed("cases") or listed("case")`. It is written against the tree AFTER the whole batch: on the branch of one node it
may be red for exactly the lines a parallel node removes (the report of that node lists them).

A grep that finds nothing proves nothing (command hygiene 6): every pattern carries a positive control inside the test - the same
function finds a planted line in a temp file - and a negative control (a line that reads a plan's `cases`, not a draft's).
"""
import re
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
OWNER = "bug_records.py"          # the one reader
GET = r"""\.get\(\s*["']%s["']\s*\)"""
PATTERNS = {
    "a draft's `cases` read by hand": re.compile(r"\b(?:draft\w*|d|data|dr)" + GET % "cases"),
    "`case` or `cases` on one line": re.compile(r"""get\(\s*["']case["']\s*\)\)?\s+or\s+[\w.]*\(?\s*[\w.]*""" + GET % "cases"),
    "a key loop over `case`, `cases`": re.compile(r"""\(\s*(?:["']\w+["']\s*,\s*)*["']case["']\s*,\s*["']cases["']"""),
    "the front matter's `cases` or `case`": re.compile(r"""["']cases["']\s*\)\s*or\s*\w+\(\s*["']case["']"""),
}


def flagged(files) -> list:
    """`[(file name, line number, pattern name, line)]` of every line of `files` that reads a draft's cases by hand (a comment line
    is not a read)."""
    out = []
    for path in files:
        for number, line in enumerate(Path(path).read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
            if line.lstrip().startswith("#"):
                continue
            for name, pattern in PATTERNS.items():
                if pattern.search(line):
                    out.append((Path(path).name, number, name, line.strip()))
    return out


def package_files() -> list:
    return sorted(p for p in SCRIPTS.glob("*.py") if p.name != OWNER)


def test_every_pattern_finds_a_planted_line(tmp_path):
    """The positive control: the same function, on a temp file holding one line per pattern, finds each of them."""
    planted = {
        "a draft's `cases` read by hand": 'listed = draft.get("cases") if isinstance(draft, dict) else []',
        "`case` or `cases` on one line": 'cases = C.case_ids(data.get("case") or data.get("cases"))',
        "`case` or `cases` on one line ": 'cases = C.case_ids(d.get("case")) or C.case_ids(d.get("cases"))',
        "a key loop over `case`, `cases`": 'for key in ("id", "case", "cases"):',
        "the front matter's `cases` or `case`": 'cases = listed("cases") or listed("case")',
    }
    for n, (name, line) in enumerate(planted.items()):
        path = tmp_path / f"planted{n}.py"
        path.write_text("x = 1\n" + line + "\ny = 2\n", encoding="utf-8")
        found = flagged([path])
        assert [(f[1], f[2]) for f in found if f[2] == name.strip()] == [(2, name.strip())], (name, found)


def test_a_line_that_reads_something_else_is_not_flagged(tmp_path):
    """The negative control: a plan's `cases`, a request's `cases`, a comment and `draft_cases` itself are no hand read of a draft."""
    path = tmp_path / "clean.py"
    path.write_text("\n".join([
        'rows = len(plan.get("cases") or [])',
        'cases = [str(c) for c in (request.get("cases") or [])]',
        '# draft.get("cases") is what the reader replaced',
        "cases = BR.draft_cases(draft)",
        'case = str(row.get("case") or "")',
        'text = draft.get("case")',   # the single primary case (advice only), not the draft's cases
    ]) + "\n", encoding="utf-8")
    assert flagged([path]) == []


def test_the_pattern_set_would_have_caught_the_original_lines():
    """The lines the readers had before N3a (each is a real shape of the package), checked against the patterns."""
    before = ['                    data.get("case") or data.get("cases") or f"{stem} {stem.upper()}", artifacts)))',
              '        cases = C.case_ids(d.get("case")) or C.case_ids(d.get("cases"))',
              '            case = " ".join(str(draft.get("case") or draft.get("cases") or "").split()) or name']
    for line in before:
        assert any(p.search(line) for p in PATTERNS.values()), line


def test_the_owner_file_is_there_and_is_the_reader():
    assert (SCRIPTS / OWNER).is_file()
    assert "def draft_cases(" in (SCRIPTS / OWNER).read_text(encoding="utf-8")
    assert OWNER not in [p.name for p in package_files()]


# Named exemptions: (file, the stripped line) -> why the line is no read of a DRAFT's cases. A line that changes is red again.
EXEMPT = {
    ("validate_artifacts.py", 'cases = listed("cases") or listed("case")'):
        "reads the frontmatter of the bug FILE (`bugs/BUG-n.md`: `cases` as the reporter wrote it), not a draft; the draft of that file "
        "is read through `BR.draft_cases` further down in `check_bug_form`",
}


def test_every_exemption_is_still_a_line_the_pattern_flags_and_the_file_holds():
    """An exemption that no longer matches a flagged line is stale: it would hide a future read in that file."""
    for (name, line), why in EXEMPT.items():
        assert why.strip()
        hits = [f for f in flagged([SCRIPTS / name]) if f[3] == line]
        assert len(hits) >= 1, (name, line)


def test_no_script_outside_bug_records_reads_a_drafts_cases_by_hand():
    found = [f for f in flagged(package_files()) if (f[0], f[3]) not in EXEMPT]
    assert found == [], "read a draft's cases through bug_records.draft_cases (AR-13):\n" + "\n".join(
        f"  {name}:{number}  [{kind}]  {line}" for name, number, kind, line in found)


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-q", "-p", "no:cacheprovider"]))
